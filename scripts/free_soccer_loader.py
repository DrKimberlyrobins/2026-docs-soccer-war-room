
import json
import re
import unicodedata
import urllib.error
import urllib.request
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

FIXTURES = Path("data/global-soccer.json")
OUTPUT = Path("data/free-soccer-intelligence.json")

SEASON = "2026-27"

BASE = (
    "https://raw.githubusercontent.com/"
    "openfootball/football.json/master"
)

# Verified competition mappings to API-Football league IDs.
LEAGUES = {
    39: "en.1",
    40: "en.2",
    41: "en.3",
    42: "en.4",
    78: "de.1",
    79: "de.2",
    140: "es.1",
    141: "es.2",
    135: "it.1",
    136: "it.2",
    61: "fr.1",
    62: "fr.2",
}


def normalize(value):
    value = unicodedata.normalize(
        "NFKD", str(value or "")
    )

    value = "".join(
        c for c in value
        if not unicodedata.combining(c)
    )

    value = value.casefold().replace("&", "and")
    value = re.sub(
        r"[^a-z0-9]+", " ", value
    ).strip()

    # Never remove City, United, U19, etc.
    return re.sub(
        r"^(fc|afc|sc) | (fc|afc|sc)$",
        "", value
    ).strip()


def fetch(url):
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "DocsSoccerWarRoom/1.0"
        }
    )

    with urllib.request.urlopen(
        request, timeout=30
    ) as response:
        return json.load(response)


def summary(rows):
    n = len(rows)

    empty = {
        "games": 0,
        "scored_05": None,
        "scored_15": None,
        "conceded_05": None,
        "goals_for": None,
        "goals_against": None,
        "first_half_scored": None
    }

    if not n:
        return empty

    half = [
        r for r in rows
        if r["ht"] is not None
    ]

    return {
        "games": n,
        "scored_05": round(
            sum(r["gf"] >= 1 for r in rows) / n, 4
        ),
        "scored_15": round(
            sum(r["gf"] >= 2 for r in rows) / n, 4
        ),
        "conceded_05": round(
            sum(r["ga"] >= 1 for r in rows) / n, 4
        ),
        "goals_for": round(
            sum(r["gf"] for r in rows) / n, 3
        ),
        "goals_against": round(
            sum(r["ga"] for r in rows) / n, 3
        ),
        "first_half_scored": (
            round(
                sum(
                    r["ht"] >= 1 for r in half
                ) / len(half), 4
            )
            if half else None
        )
    }


def main():
    if not FIXTURES.exists():
        raise SystemExit(
            "Run Global Soccer War Room first"
        )

    with FIXTURES.open(encoding="utf-8") as f:
        data = json.load(f)

    fixtures = data.get("fixtures", [])

    if not isinstance(fixtures, list):
        raise SystemExit("Invalid fixture data")

    # Exclude today's results to avoid using
    # the target match in its own pre-match stats.
    cutoff = (
        datetime.now(timezone.utc)
        .date()
        .isoformat()
    )

    loaded = {}
    errors = []

    for league_id, slug in LEAGUES.items():
        url = (
            f"{BASE}/{SEASON}/{slug}.json"
        )

        try:
            payload = fetch(url)
            matches = payload.get(
                "matches", []
            )

            if not isinstance(matches, list):
                raise ValueError(
                    "Missing matches array"
                )

            per_team = defaultdict(list)

            for m in matches:
                date = str(
                    m.get("date", "")
                )[:10]

                score = m.get("score")

                ft = (
                    score.get("ft")
                    if isinstance(score, dict)
                    else None
                )

                ht = (
                    score.get("ht")
                    if isinstance(score, dict)
                    else None
                )

                if not date or date >= cutoff:
                    continue

                if not (
                    isinstance(ft, list)
                    and len(ft) == 2
                    and all(
                        type(x) is int and x >= 0
                        for x in ft
                    )
                ):
                    continue

                home = m.get("team1")
                away = m.get("team2")

                if not home or not away:
                    continue

                hth = (
                    ht[0]
                    if isinstance(ht, list)
                    and len(ht) == 2
                    and type(ht[0]) is int
                    else None
                )

                hta = (
                    ht[1]
                    if isinstance(ht, list)
                    and len(ht) == 2
                    and type(ht[1]) is int
                    else None
                )

                per_team[home].append({
                    "date": date,
                    "venue": "home",
                    "gf": ft[0],
                    "ga": ft[1],
                    "ht": hth
                })

                per_team[away].append({
                    "date": date,
                    "venue": "away",
                    "gf": ft[1],
                    "ga": ft[0],
                    "ht": hta
                })

            teams = {}

            for name, rows in per_team.items():
                rows.sort(
                    key=lambda r: r["date"],
                    reverse=True
                )

                teams[name] = {
                    "team": name,
                    "league_id": league_id,
                    "season": SEASON,
                    "coverage": "CURRENT",
                    "source": url,
                    "latest_match": rows[0]["date"],
                    "all": summary(rows),
                    "last5": summary(rows[:5]),
                    "home": summary([
                        r for r in rows
                        if r["venue"] == "home"
                    ]),
                    "away": summary([
                        r for r in rows
                        if r["venue"] == "away"
                    ])
                }

            loaded[str(league_id)] = {
                "source": url,
                "teams": teams,
                "status": (
                    "OK" if teams else "EMPTY"
                )
            }

            print(
                "League", league_id,
                "| Teams:", len(teams),
                "| Matches:",
                sum(
                    len(v)
                    for v in per_team.values()
                ) // 2
            )

        except (
            urllib.error.URLError,
            ValueError,
            KeyError,
            TimeoutError
        ) as exc:
            errors.append({
                "league_id": league_id,
                "source": url,
                "error": str(exc)
            })

            print(
                "League unavailable:",
                league_id, exc
            )

    # Match teams only within the same league.
    # Never guess identities from similar names.
    by_team_id = {}
    unmatched = []
    ambiguous = []
    seen = set()

    for match in fixtures:
        league_id = str(
            match.get("league_id")
        )

        teams = (
            loaded.get(league_id, {})
            .get("teams", {})
        )

        for side in ("home", "away"):
            team_id = match.get(
                f"{side}_id"
            )
            name = match.get(side)

            if team_id is None or not name:
                continue

            key = (
                league_id,
                str(team_id)
            )

            if key in seen:
                continue

            seen.add(key)

            candidates = [
                t for t in teams.values()
                if normalize(t["team"])
                == normalize(name)
            ]

            if len(candidates) == 1:
                entry = dict(
                    candidates[0],
                    team_id=team_id,
                    fixture_name=name
                )

                by_team_id.setdefault(
                    str(team_id), []
                ).append(entry)

            elif len(candidates) > 1:
                ambiguous.append({
                    "league_id": league_id,
                    "team_id": team_id,
                    "name": name
                })

            else:
                unmatched.append({
                    "league_id": league_id,
                    "team_id": team_id,
                    "name": name
                })

    both = 0
    one = 0
    neither = 0

    for match in fixtures:
        home = bool(
            by_team_id.get(
                str(match.get("home_id"))
            )
        )

        away = bool(
            by_team_id.get(
                str(match.get("away_id"))
            )
        )

        if home and away:
            both += 1
        elif home or away:
            one += 1
        else:
            neither += 1

    output = {
        "generated_utc": (
            datetime.now(timezone.utc)
            .isoformat()
        ),
        "source": (
            "OpenFootball public-domain football.json"
        ),
        "season": SEASON,
        "result_cutoff_utc_date_exclusive": cutoff,
        "leagues": loaded,
        "by_team_id": by_team_id,
        "unmatched": unmatched,
        "ambiguous": ambiguous,
        "errors": errors,
        "coverage": {
            "fixtures_checked": len(fixtures),
            "both": both,
            "one": one,
            "neither": neither
        },
        "warning": (
            "Upstream results may be stale. "
            "No odds, xG, or calibrated match "
            "probabilities are provided. "
            "Not yet connected to the War Room."
        )
    }

    OUTPUT.parent.mkdir(
        parents=True,
        exist_ok=True
    )

    temp = OUTPUT.with_suffix(
        ".json.tmp"
    )

    with temp.open(
        "w", encoding="utf-8"
    ) as f:
        json.dump(
            output,
            f,
            indent=2,
            ensure_ascii=False
        )

    temp.replace(OUTPUT)

    print("=" * 45)
    print("FREE SOCCER DATA LOAD COMPLETE")
    print("Fixture count:", len(fixtures))
    print(
        "Current-season team IDs matched:",
        len(by_team_id)
    )
    print("Both teams covered:", both)
    print("One team covered:", one)
    print("Neither team covered:", neither)
    print(
        "Unmatched team IDs:",
        len(unmatched)
    )
    print(
        "Ambiguous matches:",
        len(ambiguous)
    )
    print("Source errors:", len(errors))
    print("=" * 45)


if __name__ == "__main__":
    main()
