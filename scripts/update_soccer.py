
import csv
import io
import json
import math
import os
import urllib.request
from collections import defaultdict
from datetime import datetime, timezone, date

SOURCE = "https://www.football-data.co.uk/mmz4281/2627/E0.csv"
OUTPUT = "data/soccer-current.json"
TODAY = datetime.now(timezone.utc).date()

def number(value):
    try:
        return float(value)
    except (ValueError, TypeError):
        return None

def load():
    request = urllib.request.Request(
        SOURCE,
        headers={"User-Agent": "Mozilla/5.0 SoccerResearch/1.0"}
    )
    with urllib.request.urlopen(request, timeout=40) as response:
        raw = response.read().decode("utf-8-sig")
    return list(csv.DictReader(io.StringIO(raw)))

def rate(games, key):
    if not games:
        return None
    return round(sum(bool(g[key]) for g in games) / len(games), 4)

def average(games, key):
    values = [g[key] for g in games if g[key] is not None]
    return round(sum(values) / len(values), 3) if values else None

def summarize(games):
    return {
        "n": len(games),
        "scored_05": rate(games, "scored_05"),
        "scored_15": rate(games, "scored_15"),
        "conceded_05": rate(games, "conceded_05"),
        "first_half_scored": rate(games, "first_half_scored"),
        "goals_for": average(games, "gf"),
        "goals_against": average(games, "ga"),
        "xg_for": average(games, "xgf"),
        "xg_against": average(games, "xga"),
        "shots_on_target": average(games, "sot")
    }

rows = load()
matches = []
rejected = []

for row in rows:
    try:
        raw_date = (row.get("Date") or "").strip()
        match_date = datetime.strptime(
            raw_date, "%d/%m/%Y"
        ).date()
        home = (row.get("HomeTeam") or "").strip()
        away = (row.get("AwayTeam") or "").strip()
        hg = number(row.get("FTHG"))
        ag = number(row.get("FTAG"))
        if not home or not away or hg is None or ag is None:
            continue
        if match_date > TODAY or hg < 0 or ag < 0:
            continue
        if not hg.is_integer() or not ag.is_integer():
            continue
        matches.append({
            "date": match_date.isoformat(),
            "home": home,
            "away": away,
            "hg": int(hg),
            "ag": int(ag),
            "hthg": number(row.get("HTHG")),
            "htag": number(row.get("HTAG")),
            "hxg": number(row.get("HxG")),
            "axg": number(row.get("AxG")),
            "hst": number(row.get("HST")),
            "ast": number(row.get("AST"))
        })
    except (ValueError, TypeError) as exc:
        rejected.append(str(exc))

matches.sort(key=lambda x: x["date"])
if not matches:
    raise SystemExit("No valid completed matches; refusing overwrite")

teams = defaultdict(list)

for m in matches:
    for venue in ("home", "away"):
        is_home = venue == "home"
        gf = m["hg"] if is_home else m["ag"]
        ga = m["ag"] if is_home else m["hg"]
        ht = m["hthg"] if is_home else m["htag"]
        team = m["home"] if is_home else m["away"]
        opponent = m["away"] if is_home else m["home"]
        teams[team].append({
            "date": m["date"],
            "opponent": opponent,
            "venue": venue,
            "gf": gf,
            "ga": ga,
            "scored_05": gf >= 1,
            "scored_15": gf >= 2,
            "conceded_05": ga >= 1,
            "first_half_scored": ht >= 1 if ht is not None else False,
            "xgf": m["hxg"] if is_home else m["axg"],
            "xga": m["axg"] if is_home else m["hxg"],
            "sot": m["hst"] if is_home else m["ast"]
        })

output_teams = []

for name, games in teams.items():
    games.sort(key=lambda x: x["date"], reverse=True)
    home = [g for g in games if g["venue"] == "home"]
    away = [g for g in games if g["venue"] == "away"]
    output_teams.append({
        "name": name,
        "season": summarize(games),
        "last5": summarize(games[:5]),
        "last10": summarize(games[:10]),
        "home": summarize(home),
        "away": summarize(away),
        "games": games
    })

output_teams.sort(
    key=lambda t: (
        -(t["season"]["scored_05"] or 0),
        -(t["season"]["goals_for"] or 0),
        t["name"]
    )
)

result = {
    "league": "English Premier League",
    "season": "2026-27",
    "source": SOURCE,
    "updated_utc": datetime.now(timezone.utc).isoformat(),
    "latest_match": matches[-1]["date"],
    "matches_count": len(matches),
    "team_count": len(output_teams),
    "rejected_rows": len(rejected),
    "historical_only": True,
    "teams": output_teams,
    "matches": matches,
    "note": (
        "Historical scoring frequencies are not predictions. "
        "No current betting prices or lineup verification included."
    )
}

os.makedirs("data", exist_ok=True)
temp = OUTPUT + ".tmp"
with open(temp, "w", encoding="utf-8") as file:
    json.dump(result, file, indent=2)
os.replace(temp, OUTPUT)

print("SOCCER DATA UPDATED")
print("Matches:", len(matches))
print("Teams:", len(output_teams))
print("Latest:", matches[-1]["date"])
print("Rejected:", len(rejected))
for team in output_teams[:5]:
    print(
        team["name"],
        team["season"]["n"],
        team["season"]["scored_05"]
    )
