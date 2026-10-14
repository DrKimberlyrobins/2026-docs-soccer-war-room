
import json
import os
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

BASE = "https://v3.football.api-sports.io"
KEY = os.environ.get("API_SPORTS_KEY", "").strip()
OUTPUT = "data/global-soccer.json"

if not KEY:
    sys.exit("Missing API_SPORTS_KEY GitHub secret")

def fetch_fixtures(day):
    params = urllib.parse.urlencode({"date": day})
    request = urllib.request.Request(
        f"{BASE}/fixtures?{params}",
        headers={
            "x-apisports-key": KEY,
            "Accept": "application/json"
        }
    )

    with urllib.request.urlopen(request, timeout=45) as response:
        data = json.load(response)
        remaining = response.headers.get(
            "x-ratelimit-requests-remaining"
        )
        print(f"{day}: requests remaining = {remaining}")

    errors = data.get("errors")
    if errors:
        raise RuntimeError(f"API error for {day}: {errors}")

    if not isinstance(data.get("response"), list):
        raise RuntimeError("Invalid fixture response")

    return data["response"]

def normalize(item):
    fixture = item.get("fixture") or {}
    league = item.get("league") or {}
    teams = item.get("teams") or {}
    home = teams.get("home") or {}
    away = teams.get("away") or {}
    goals = item.get("goals") or {}
    status = fixture.get("status") or {}

    return {
        "id": fixture.get("id"),
        "kickoff": fixture.get("date"),
        "status": status.get("short", "UNKNOWN"),
        "status_long": status.get("long", ""),
        "league": league.get("name", "Unknown"),
        "league_id": league.get("id"),
        "country": league.get("country", ""),
        "round": league.get("round", ""),
        "home": home.get("name", "TBD"),
        "home_id": home.get("id"),
        "away": away.get("name", "TBD"),
        "away_id": away.get("id"),
        "home_goals": goals.get("home"),
        "away_goals": goals.get("away")
    }

now = datetime.now(timezone.utc)
today = now.date()

# Free API access currently allows today and tomorrow.
# Two requests per run.
days = [
    today.isoformat(),
    (today + timedelta(days=1)).isoformat()
]

fixtures = []

for day in days:
    print("Fetching", day)
    records = fetch_fixtures(day)
    fixtures.extend(normalize(x) for x in records)

unique = {}
for match in fixtures:
    if match["id"] is not None:
        unique[str(match["id"])] = match

fixtures = sorted(
    unique.values(),
    key=lambda x: (
        x.get("kickoff") or "",
        x.get("league") or ""
    )
)

if not fixtures:
    raise RuntimeError(
        "No fixtures returned. Previous data preserved."
    )

teams = []
domestic_source = None
existing = "data/soccer-current.json"

if os.path.exists(existing):
    with open(existing, encoding="utf-8") as file:
        previous = json.load(file)

    teams = previous.get("teams", [])
    domestic_source = previous.get("source")

output = {
    "generated_utc": now.isoformat(),
    "window_start": days[0],
    "window_end": days[-1],
    "fixture_count": len(fixtures),
    "league_count": len(set(
        (m["country"], m["league_id"])
        for m in fixtures
    )),
    "fixtures": fixtures,
    "domestic_teams": teams,
    "domestic_source": domestic_source,
    "limitations": [
        "Free API fixture dates are restricted.",
        "Current coverage is today and tomorrow.",
        "Not all teams have current-season statistics.",
        "Market prices and lineups are not verified."
    ]
}

os.makedirs("data", exist_ok=True)
temporary = OUTPUT + ".tmp"

with open(temporary, "w", encoding="utf-8") as file:
    json.dump(output, file, indent=2, ensure_ascii=False)

os.replace(temporary, OUTPUT)

print("=" * 45)
print("GLOBAL SOCCER DISCOVERY COMPLETE")
print("Fixtures:", output["fixture_count"])
print("Competitions:", output["league_count"])
print("Domestic teams:", len(teams))
print("Dates:", days[0], "to", days[-1])
print("=" * 45)
