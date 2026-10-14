
import json
import os
import sys
import urllib.parse
import urllib.request
from collections import defaultdict
from datetime import datetime, timezone

API = "https://v3.football.api-sports.io"
KEY = os.environ.get("API_SPORTS_KEY", "").strip()
GLOBAL = "data/global-soccer.json"
OUTPUT = "data/team-intelligence.json"

# Up to 12 league-season requests per manual run.
MAX_REQUESTS = 12
HISTORICAL_SEASON = 2024

# Prioritize major domestic leagues.
PRIORITY = [
    39,   # English Premier League
    61,   # French Ligue 1
    140,  # Spanish La Liga
    78,   # German Bundesliga
    135,  # Italian Serie A
    94,   # Portuguese Primeira Liga
    88,   # Dutch Eredivisie
    253,  # MLS
    71,   # Brazilian Serie A
    128,  # Argentina Primera Division
    203,  # Turkish Super Lig
    179,  # Scottish Premiership
]

if not KEY:
    sys.exit("Missing API_SPORTS_KEY secret")

if not os.path.exists(GLOBAL):
    sys.exit("Run Global Soccer War Room first")

with open(GLOBAL, encoding="utf-8") as f:
    global_data = json.load(f)

def api_get(params):
    query = urllib.parse.urlencode(params)
    request = urllib.request.Request(
        f"{API}/fixtures?{query}",
        headers={
            "x-apisports-key": KEY,
            "Accept": "application/json"
        }
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        data = json.load(response)
        remaining = response.headers.get(
            "x-ratelimit-requests-remaining"
        )
        print("Daily requests remaining:", remaining)

    if data.get("errors"):
        raise RuntimeError(str(data["errors"]))

    records = data.get("response")
    if not isinstance(records, list):
        raise RuntimeError("Unexpected API response")

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
        g for g in games if g["first_half_goals"] is not None
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
                sum(g["first_half_goals"] >= 1 for g in half)
                / len(half), 4
            )
            if half else None
        )
    }

def process_league(records, league_id):
    teams = defaultdict(list)
    names = {}

    for record in records:
        fixture = record.get("fixture") or {}
        status = (fixture.get("status") or {}).get("short")
        if status not in ("FT", "AET", "PEN"):
            continue

        sides = record.get("teams") or {}
        home = sides.get("home") or {}
        away = sides.get("away") or {}
        goals = record.get("goals") or {}
        score = record.get("score") or {}
        halftime = score.get("halftime") or {}

        hid, aid = home.get("id"), away.get("id")
        hg, ag = goals.get("home"), goals.get("away")

        if None in (hid, aid, hg, ag):
            continue

        names[str(hid)] = home.get("name", "")
        names[str(aid)] = away.get("name", "")

        match_date = fixture.get("date", "")

        for team_id, venue, gf, ga, half_goals in [
            (hid, "home", hg, ag, halftime.get("home")),
            (aid, "away", ag, hg, halftime.get("away"))
        ]:
            teams[str(team_id)].append({
                "date": match_date,
                "venue": venue,
                "gf": gf,
                "ga": ga,
                "first_half_goals": half_goals
            })

    result = {}

    for team_id, games in teams.items():
        games.sort(key=lambda g: g["date"], reverse=True)

        result[team_id] = {
            "team_id": int(team_id),
            "team": names[team_id],
            "league_id": league_id,
            "season": HISTORICAL_SEASON,
            "coverage": "HISTORICAL",
            "all": summarize(games),
            "last5_of_historical_season": summarize(games[:5]),
            "home": summarize([
                g for g in games if g["venue"] == "home"
            ]),
            "away": summarize([
                g for g in games if g["venue"] == "away"
            ])
        }

    return result

# Reuse previously downloaded data to avoid repeated API calls.
saved = {}
if os.path.exists(OUTPUT):
    try:
        with open(OUTPUT, encoding="utf-8") as f:
            previous = json.load(f)
        saved = previous.get("leagues", {})
    except (ValueError, OSError):
        print("Existing intelligence unreadable; starting fresh")

leagues = dict(saved)
requests_used = 0
errors = []

for league_id in PRIORITY:
    key = f"{league_id}-{HISTORICAL_SEASON}"

    if key in leagues and leagues[key].get("status") == "OK":
        print("Using cached league:", key)
        continue

    if requests_used >= MAX_REQUESTS:
        break

    print("Loading league:", league_id, HISTORICAL_SEASON)
    requests_used += 1

    try:
        records = api_get({
            "league": league_id,
            "season": HISTORICAL_SEASON
        })

        teams = process_league(records, league_id)

        leagues[key] = {
            "league_id": league_id,
            "season": HISTORICAL_SEASON,
            "status": "OK" if teams else "EMPTY",
            "matches_received": len(records),
            "teams": teams
        }

        print(
            "Matches:", len(records),
            "Teams:", len(teams)
        )

    except Exception as exc:
        print("Unavailable:", league_id, str(exc))
        errors.append({
            "league_id": league_id,
            "error": str(exc)
        })

# Build direct team lookup by stable API team ID.
by_team_id = {}

for entry in leagues.values():
    if entry.get("status") != "OK":
        continue

    for team_id, team in entry["teams"].items():
        by_team_id.setdefault(team_id, []).append(team)

fixtures = global_data.get("fixtures", [])
coverage = []

for match in fixtures:
    hid = str(match.get("home_id"))
    aid = str(match.get("away_id"))

    home_data = by_team_id.get(hid, [])
    away_data = by_team_id.get(aid, [])

    coverage.append({
        "fixture_id": match.get("id"),
        "home": match.get("home"),
        "away": match.get("away"),
        "home_historical_available": bool(home_data),
        "away_historical_available": bool(away_data),
        "coverage": (
            "HISTORICAL_BOTH" if home_data and away_data
            else "HISTORICAL_PARTIAL"
            if home_data or away_data
            else "MISSING"
        )
    })

output = {
    "generated_utc": datetime.now(timezone.utc).isoformat(),
    "historical_season": HISTORICAL_SEASON,
    "requests_used": requests_used,
    "leagues": leagues,
    "by_team_id": by_team_id,
    "fixture_coverage": coverage,
    "errors": errors,
    "warning": (
        "Historical data is not current-season form. "
        "A team may have changed leagues, players or coaches. "
        "No calibrated probabilities or market edges provided."
    )
}

os.makedirs("data", exist_ok=True)
temp = OUTPUT + ".tmp"

with open(temp, "w", encoding="utf-8") as f:
    json.dump(output, f, indent=2, ensure_ascii=False)

os.replace(temp, OUTPUT)

print("=" * 50)
print("TEAM INTELLIGENCE LOADER COMPLETE")
print("API requests used:", requests_used)
print("Historical leagues:", sum(
    x.get("status") == "OK" for x in leagues.values()
))
print("Historical team IDs:", len(by_team_id))
print("Fixtures checked:", len(coverage))
print("Errors:", len(errors))
print("=" * 50)
