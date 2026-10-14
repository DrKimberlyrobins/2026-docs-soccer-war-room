
import os
import json
import urllib.request
import urllib.error
from datetime import datetime, timezone

KEY = os.environ.get("API_SPORTS_KEY", "")
BASE = "https://v3.football.api-sports.io"

if not KEY:
    raise SystemExit("ERROR: API_SPORTS_KEY is missing.")

def get(path):
    request = urllib.request.Request(
        BASE + path,
        headers={
            "x-apisports-key": KEY,
            "Accept": "application/json"
        }
    )
    try:
        with urllib.request.urlopen(request, timeout=25) as response:
            data = json.load(response)
            return {
                "status": response.status,
                "results": data.get("results"),
                "errors": data.get("errors"),
                "response": data.get("response", []),
                "remaining": response.headers.get(
                    "x-ratelimit-requests-remaining"
                )
            }
    except urllib.error.HTTPError as error:
        return {
            "status": error.code,
            "errors": error.read(500).decode(errors="replace")
        }
    except Exception as error:
        return {
            "status": "connection-error",
            "errors": str(error)
        }

checks = {}

today = datetime.now(timezone.utc).date().isoformat()

endpoints = [
    ("status", "/status"),
    ("leagues", "/leagues"),
    ("fixtures_today", "/fixtures?date=" + today)
]

for name, path in endpoints:
    result = get(path)

    record = {
        "http_status": result["status"],
        "results": result.get("results"),
        "errors": result.get("errors"),
        "remaining": result.get("remaining")
    }

    if name == "status" and result.get("response"):
        account = result["response"][0]
        record["subscription"] = account.get("subscription")
        record["requests"] = account.get("requests")

    if name == "leagues":
        leagues = result.get("response") or []
        record["sample_leagues"] = [
            {
                "name": item.get("league", {}).get("name"),
                "country": item.get("country", {}).get("name"),
                "seasons": [
                    season.get("year")
                    for season in item.get("seasons", [])
                ][-4:]
            }
            for item in leagues[:8]
        ]

    if name == "fixtures_today":
        fixtures = result.get("response") or []
        record["sample_fixtures"] = [
            {
                "home": item.get("teams", {}).get(
                    "home", {}
                ).get("name"),
                "away": item.get("teams", {}).get(
                    "away", {}
                ).get("name"),
                "league": item.get("league", {}).get("name")
            }
            for item in fixtures[:8]
        ]

    checks[name] = record

    print(
        name,
        "HTTP:", result["status"],
        "Results:", result.get("results"),
        "Errors:", str(result.get("errors"))[:250]
    )

os.makedirs("data", exist_ok=True)

with open("data/api-discovery.json", "w") as file:
    json.dump(
        {
            "checked_at_utc": datetime.now(
                timezone.utc
            ).isoformat(),
            "checks": checks
        },
        file,
        indent=2
    )

print("Discovery complete. Results saved.")
