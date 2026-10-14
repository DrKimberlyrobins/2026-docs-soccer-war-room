
import os
import json
import math
import urllib.request
import urllib.parse
import urllib.error
from datetime import datetime, timezone

KEY = os.environ.get("API_SPORTS_KEY")
BASE = "https://v3.football.api-sports.io"
LEAGUE = 39  # English Premier League
SEASONS = [2026, 2024, 2023]
MAX_CALLS = 8
calls = 0

if not KEY:
    raise SystemExit("Missing API_SPORTS_KEY")

def fetch(endpoint, params):
    global calls
    if calls >= MAX_CALLS:
        raise RuntimeError("Discovery call budget reached")
    calls += 1
    url = BASE + endpoint + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(
        url, headers={"x-apisports-key": KEY}
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            data = json.load(r)
            remaining = r.headers.get(
                "x-ratelimit-requests-remaining"
            )
        return data, remaining
    except urllib.error.HTTPError as e:
        return {
            "errors": {"http": str(e.code)},
            "response": []
        }, None

def finished(f):
    return f.get("fixture", {}).get("status", {}).get(
        "short"
    ) in ("FT", "AET", "PEN")

def calculate(fixtures):
    records = {}
    for f in fixtures:
        if not finished(f):
            continue
        teams = f.get("teams", {})
        goals = f.get("goals", {})
        home = teams.get("home", {})
        away = teams.get("away", {})
        hg, ag = goals.get("home"), goals.get("away")
        if hg is None or ag is None:
            continue
        for side, team, gf, ga in [
            ("home", home, hg, ag),
            ("away", away, ag, hg)
        ]:
            tid = team.get("id")
            if tid is None:
                continue
            r = records.setdefault(tid, {
                "team": team.get("name"),
                "games": [],
                "home": [],
                "away": []
            })
            game = {
                "date": f["fixture"].get("date"),
                "goals_for": gf,
                "goals_against": ga,
                "scored_1": int(gf >= 1),
                "scored_2": int(gf >= 2),
                "conceded_1": int(ga >= 1)
            }
            r["games"].append(game)
            r[side].append(game)

    output = []
    for r in records.values():
        games = sorted(
            r["games"], key=lambda g: g["date"] or "",
            reverse=True
        )
        def summary(sample):
            n = len(sample)
            if not n:
                return None
            return {
                "matches": n,
                "scored_1_rate": round(
                    sum(g["scored_1"] for g in sample) / n, 3
                ),
                "scored_2_rate": round(
                    sum(g["scored_2"] for g in sample) / n, 3
                ),
                "conceded_1_rate": round(
                    sum(g["conceded_1"] for g in sample) / n, 3
                ),
                "goals_per_game": round(
                    sum(g["goals_for"] for g in sample) / n, 2
                )
            }
        output.append({
            "team": r["team"],
            "season": summary(games),
            "last_5": summary(games[:5]),
            "last_10": summary(games[:10]),
            "home": summary(r["home"]),
            "away": summary(r["away"])
        })
    return sorted(output, key=lambda x: x["team"] or "")

audit = []
selected = None
fixtures = []

for season in SEASONS:
    data, remaining = fetch("/fixtures", {
        "league": LEAGUE, "season": season
    })
    errors = data.get("errors")
    response = data.get("response", [])
    count = len(response) if isinstance(response, list) else 0
    completed = [
        f for f in response if finished(f)
    ] if isinstance(response, list) else []

    entry = {
        "season": season,
        "results": count,
        "completed": len(completed),
        "errors": errors,
        "remaining": remaining
    }
    audit.append(entry)
    print("SEASON TEST:", json.dumps(entry))

    if completed:
        selected = season
        fixtures = completed
        break

result = {
    "checked_at": datetime.now(timezone.utc).isoformat(),
    "league": "Premier League",
    "selected_season": selected,
    "historical_only": True,
    "season_tests": audit,
    "teams": calculate(fixtures),
    "requests_used_by_test": calls,
    "note": (
        "Historical rates are descriptive, not calibrated "
        "future probabilities or betting recommendations."
    )
}

os.makedirs("data", exist_ok=True)
with open("data/scoring-lab.json", "w") as f:
    json.dump(result, f, indent=2)

print("Teams analyzed:", len(result["teams"]))
print("Requests used:", calls)
print("Scoring laboratory complete.")
