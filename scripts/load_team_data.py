
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

API = "https://v3.football.api-sports.io"
KEY = os.environ.get("API_SPORTS_KEY", "").strip()

GLOBAL = Path("data/global-soccer.json")
OUTPUT = Path("data/team-intelligence.json")

MAX_REQUESTS = 12
HISTORICAL_SEASON = 2024

# Try the current season when permitted by the subscription.
# API season means the starting year of the competition season.
TRY_CURRENT_SEASON = True

# Existing leagues stay as fallback priorities.
PRIORITY = [
    39, 61, 140, 78, 135, 94,
    88, 253, 71, 128, 203, 179
]

if not KEY:
    sys.exit("Missing API_SPORTS_KEY secret")

if not GLOBAL.exists():
    sys.exit("Missing data/global-soccer.json")

with GLOBAL.open(encoding="utf-8") as f:
    global_data = json.load(f)

fixtures = global_data.get("fixtures", [])

if not isinstance(fixtures, list):
    sys.exit("Invalid fixture list")

# Load existing cache. Never discard successful old downloads.
previous = {}

if OUTPUT.exists():
    try:
        with OUTPUT.open(encoding="utf-8") as f:
            previous = json.load(f)
    except (ValueError, OSError) as exc:
        print("Could not read previous cache:", exc)

leagues = dict(previous.get("leagues") or {})

requests_used = 0
errors = []
blocked_seasons = set()


def api_get(league_id, season):
    global requests_used

    if requests_used >= MAX_REQUESTS:
        return None

    params = urllib.parse.urlencode({
        "league": league_id,
        "season": season
    })

    url = f"{API}/fixtures?{params}"

    request = urllib.request.Request(
        url,
        headers={
            "x-apisports-key": KEY,
            "Accept": "application/json"
        }
    )

    requests_used += 1

    try:
        with urllib.request.urlopen(
            request, timeout=60
        ) as response:
            payload = json.load(response)

            print(
                "Daily API requests remaining:",
                response.headers.get(
                    "x-ratelimit-requests-remaining",
                    "unknown"
                )
            )

    except urllib.error.HTTPError as exc:
        if exc.code == 429:
            raise RuntimeError("RATE_LIMIT_429")
        raise RuntimeError(
            f"HTTP {exc.code}: {exc.reason}"
        )

    if payload.get("errors"):
        raise RuntimeError(
            str(payload["errors"])
        )

    records = payload.get("response")

    if not isinstance(records, list):
        raise RuntimeError(
            "Unexpected API response format"
        )

    return records


def summarize(games):
    n = len(games)

    if not n:
        return {
            "games": 0,
            "scored_05": None,
            "scored_15": None,
            "conceded_05": None,
            "goals_for": None,
            "goals_against": None,
            "first_half_scored": None
        }

    half = [
        g for g in games
        if g["first_half_goals"] is not None
    ]

    return {
        "games": n,
        "scored_05": round(
            sum(g["gf"] >= 1 for g in games) / n, 4
        ),
        "scored_15": round(
            sum(g["gf"] >= 2 for g in games) / n, 4
        ),
        "conceded_05": round(
            sum(g["ga"] >= 1 for g in games) / n, 4
        ),
        "goals_for": round(
            sum(g["gf"] for g in games) / n, 3
        ),
        "goals_against": round(
            sum(g["ga"] for g in games) / n, 3
        ),
        "first_half_scored": (
            round(
                sum(
                    g["first_half_goals"] >= 1
                    for g in half
                ) / len(half),
                4
            )
            if half else None
        )
    }


def process_league(records, league_id, season):
    teams = defaultdict(list)
    names = {}

    for record in records:
        fixture = record.get("fixture") or {}
        status = (
            fixture.get("status") or {}
        ).get("short")

        if status not in ("FT", "AET", "PEN"):
            continue

        sides = record.get("teams") or {}
        home = sides.get("home") or {}
        away = sides.get("away") or {}

        goals = record.get("goals") or {}
        score = record.get("score") or {}
        halftime = score.get("halftime") or {}

        hid = home.get("id")
        aid = away.get("id")
        hg = goals.get("home")
        ag = goals.get("away")

        if None in (hid, aid, hg, ag):
            continue

        names[str(hid)] = home.get("name", "")
        names[str(aid)] = away.get("name", "")

        date = fixture.get("date", "")

        for team_id, venue, gf, ga, first_half in [
            (
                hid, "home", hg, ag,
                halftime.get("home")
            ),
            (
                aid, "away", ag, hg,
                halftime.get("away")
            )
        ]:
            teams[str(team_id)].append({
                "date": date,
                "venue": venue,
                "gf": gf,
                "ga": ga,
                "first_half_goals": first_half
            })

    result = {}

    for team_id, games in teams.items():
        games.sort(
            key=lambda g: g["date"],
            reverse=True
        )

        current = season != HISTORICAL_SEASON

        result[team_id] = {
            "team_id": int(team_id),
            "team": names[team_id],
            "league_id": league_id,
            "season": season,
            "coverage": (
                "CURRENT" if current
                else "HISTORICAL"
            ),
            "all": summarize(games),
            "last5_of_historical_season": (
                summarize(games[:5])
                if not current else None
            ),
            "last5": summarize(games[:5]),
            "home": summarize([
                g for g in games
                if g["venue"] == "home"
            ]),
            "away": summarize([
                g for g in games
                if g["venue"] == "away"
            ])
        }

    return result


def season_for_fixture(match):
    """
    Determine API season start year from the fixture.
    For common European Aug-May seasons, October 2026
    belongs to API season 2026.
    """
    date = str(match.get("kickoff") or "")

    try:
        year = int(date[:4])
        month = int(date[5:7])
    except (ValueError, TypeError):
        return None

    if month < 7:
        return year - 1

    return year


# Determine which leagues today's fixture list needs.
league_fixtures = defaultdict(list)

for match in fixtures:
    league_id = match.get("league_id")

    if league_id is None:
        continue

    try:
        league_id = int(league_id)
    except (TypeError, ValueError):
        continue

    league_fixtures[league_id].append(match)


def existing_team_ids():
    ids = set()

    for entry in leagues.values():
        if entry.get("status") == "OK":
            ids.update(
                str(x) for x in
                (entry.get("teams") or {})
            )

    return ids


def missing_count(league_id, known):
    count = 0

    for match in league_fixtures.get(
        league_id, []
    ):
        for field in ("home_id", "away_id"):
            team_id = match.get(field)

            if (
                team_id is not None
                and str(team_id) not in known
            ):
                count += 1

    return count


# Prioritize leagues that appear in the fixture feed,
# especially leagues with teams missing intelligence.
known_ids = existing_team_ids()

ordered_leagues = sorted(
    league_fixtures,
    key=lambda lid: (
        -missing_count(lid, known_ids),
        -len(league_fixtures[lid]),
        lid
    )
)

# Fallback: retain the original priority leagues.
for league_id in PRIORITY:
    if league_id not in ordered_leagues:
        ordered_leagues.append(league_id)

print("=" * 55)
print("DOC'S GLOBAL SOCCER INTELLIGENCE")
print("Fixtures in feed:", len(fixtures))
print("Leagues in feed:", len(league_fixtures))
print("Existing cached leagues:", len(leagues))
print("Missing team references:", sum(
    missing_count(lid, known_ids)
    for lid in league_fixtures
))
print("=" * 55)


def cache_key(league_id, season):
    return f"{league_id}-{season}"


def already_loaded(league_id, season):
    entry = leagues.get(
        cache_key(league_id, season)
    )

    return bool(
        entry and entry.get("status") == "OK"
    )


def fetch_league(league_id, season):
    if already_loaded(league_id, season):
        print(
            "CACHED:", league_id, season
        )
        return "CACHED"

    if requests_used >= MAX_REQUESTS:
        return "BUDGET_EXHAUSTED"

    print(
        "FETCHING:", league_id, season
    )

    try:
        records = api_get(league_id, season)

        if records is None:
            return "BUDGET_EXHAUSTED"

        teams = process_league(
            records, league_id, season
        )

        key = cache_key(
            league_id, season
        )

        leagues[key] = {
            "league_id": league_id,
            "season": season,
            "status": (
                "OK" if teams else "EMPTY"
            ),
            "matches_received": len(records),
            "teams": teams
        }

        print(
            "LOADED:",
            league_id,
            season,
            "Matches:", len(records),
            "Teams:", len(teams)
        )

        return (
            "OK" if teams else "EMPTY"
        )

    except Exception as exc:
        message = str(exc)

        errors.append({
            "league_id": league_id,
            "season": season,
            "error": message
        })

        print(
            "UNAVAILABLE:",
            league_id, season, message
        )

        if "RATE_LIMIT_429" in message:
            return "RATE_LIMIT"

        if (
            "plan" in message.lower()
            or "subscription" in message.lower()
        ):
            blocked_seasons.add(season)

        return "ERROR"


# Load competition data with a strict API request budget.
rate_limited = False

for league_id in ordered_leagues:
    if requests_used >= MAX_REQUESTS:
        break

    league_matches = league_fixtures.get(
        league_id, []
    )

    seasons = Counter(
        season_for_fixture(m)
        for m in league_matches
        if season_for_fixture(m) is not None
    )

    if seasons:
        current_season = seasons.most_common(1)[0][0]
    else:
        current_season = None

    candidates = []

    if (
        TRY_CURRENT_SEASON
        and current_season is not None
        and current_season != HISTORICAL_SEASON
        and current_season not in blocked_seasons
    ):
        candidates.append(current_season)

    if HISTORICAL_SEASON not in candidates:
        candidates.append(HISTORICAL_SEASON)

    # Skip fully covered leagues when possible.
    known_ids = existing_team_ids()

    if (
        missing_count(league_id, known_ids) == 0
        and league_matches
    ):
        print(
            "TEAMS ALREADY COVERED:",
            league_id
        )
        continue

    for season in candidates:
        if requests_used >= MAX_REQUESTS:
            break

        result = fetch_league(
            league_id, season
        )

        if result == "RATE_LIMIT":
            rate_limited = True
            break

        if result in ("OK", "CACHED"):
            # If current-season data loaded, we have
            # no need to spend another call on 2024.
            if season != HISTORICAL_SEASON:
                break

        time.sleep(0.5)

    if rate_limited:
        print(
            "Rate limit reached. Stopping safely."
        )
        break


# Rebuild team-ID lookup without changing the board's
# expected JSON structure.
by_team_id = {}

for entry in leagues.values():
    if entry.get("status") != "OK":
        continue

    for team_id, team in (
        entry.get("teams") or {}
    ).items():
        by_team_id.setdefault(
            str(team_id), []
        ).append(team)


# Prefer current records for lookup order,
# then larger samples for the same season.
for team_id, records in by_team_id.items():
    records.sort(
        key=lambda t: (
            int(t.get("season") or 0),
            int(
                (t.get("all") or {}).get("games")
                or 0
            )
        ),
        reverse=True
    )


coverage = []
both = 0
partial = 0
missing = 0

for match in fixtures:
    hid = str(match.get("home_id"))
    aid = str(match.get("away_id"))

    home_data = by_team_id.get(
        hid, []
    )
    away_data = by_team_id.get(
        aid, []
    )

    if home_data and away_data:
        label = "HISTORICAL_BOTH"
        both += 1
    elif home_data or away_data:
        label = "HISTORICAL_PARTIAL"
        partial += 1
    else:
        label = "MISSING"
        missing += 1

    coverage.append({
        "fixture_id": match.get("id"),
        "home": match.get("home"),
        "away": match.get("away"),
        "home_historical_available": bool(
            home_data
        ),
        "away_historical_available": bool(
            away_data
        ),
        "home_current_available": any(
            t.get("coverage") == "CURRENT"
            for t in home_data
        ),
        "away_current_available": any(
            t.get("coverage") == "CURRENT"
            for t in away_data
        ),
        "coverage": label
    })


output = {
    "generated_utc": datetime.now(
        timezone.utc
    ).isoformat(),
    "historical_season": HISTORICAL_SEASON,
    "requests_used": requests_used,
    "leagues": leagues,
    "by_team_id": by_team_id,
    "fixture_coverage": coverage,
    "errors": errors,
    "warning": (
        "Records may be from different seasons. "
        "Historical scoring frequency is not a "
        "current-match probability. Current data "
        "and verified market odds are required "
        "before confirming a betting edge."
    )
}

OUTPUT.parent.mkdir(
    parents=True, exist_ok=True
)

temp = OUTPUT.with_suffix(
    ".json.tmp"
)

with temp.open(
    "w", encoding="utf-8"
) as f:
    json.dump(
        output, f,
        indent=2,
        ensure_ascii=False
    )

os.replace(temp, OUTPUT)

print("=" * 55)
print("TEAM INTELLIGENCE LOAD COMPLETE")
print("API requests used:", requests_used)
print("Cached league seasons:", len(leagues))
print("Unique team IDs:", len(by_team_id))
print("Fixtures checked:", len(coverage))
print("Both teams covered:", both)
print("One team covered:", partial)
print("Neither team covered:", missing)
print("Errors:", len(errors))
print("=" * 55)
