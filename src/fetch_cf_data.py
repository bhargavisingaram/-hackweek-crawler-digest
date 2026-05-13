"""Fetch real AI-bot traffic from Cloudflare GraphQL Analytics API.

Writes data/cf_events.json in the same shape the synthetic generator produces,
so aggregate.py reads it without any changes.

Strategy: run one query per known AI-bot user-agent string. Avoids depending
on CF's bot-category enum names (which vary by plan/dataset).

Reads CLOUDFLARE_API_TOKEN and CLOUDFLARE_ZONE_ID from .env (gitignored).
"""
import json
import re
import sys
from datetime import date, timedelta
from pathlib import Path

try:
    import requests
except ImportError:
    sys.exit("Install requests first: pip install -r requirements.txt")

ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = ROOT / ".env"
OUT_FILE = ROOT / "data" / "cf_events.json"
GRAPHQL_URL = "https://api.cloudflare.com/client/v4/graphql"

AI_BOT_USER_AGENTS = [
    "GPTBot",
    "ClaudeBot",
    "PerplexityBot",
    "CCBot",
    "Bytespider",
    "Google-Extended",
    "Applebot-Extended",
    "Amazonbot",
    "meta-externalagent",
]

QUERY = """
query AIBotTraffic($zoneTag: String!, $since: Date!, $until: Date!, $uaPattern: String!) {
  viewer {
    zones(filter: {zoneTag: $zoneTag}) {
      httpRequestsAdaptiveGroups(
        filter: {
          date_geq: $since,
          date_leq: $until,
          userAgent_like: $uaPattern
        }
        limit: 10000
        orderBy: [count_DESC]
      ) {
        count
        dimensions {
          userAgent
          clientRequestPath
          date
          edgeResponseStatus
        }
      }
    }
  }
}
"""


def load_env(path):
    if not path.exists():
        sys.exit(f"Missing {path}. Add CLOUDFLARE_API_TOKEN and CLOUDFLARE_ZONE_ID.")
    env = {}
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        m = re.match(r"^([A-Z_]+)\s*=\s*(.+)$", line)
        if m:
            env[m.group(1)] = m.group(2).strip().strip('"').strip("'")
    return env


def fetch_for_bot(token, zone_id, since, until, ua):
    resp = requests.post(
        GRAPHQL_URL,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        json={
            "query": QUERY,
            "variables": {
                "zoneTag": zone_id,
                "since": since.isoformat(),
                "until": until.isoformat(),
                "uaPattern": f"%{ua}%",
            },
        },
        timeout=30,
    )

    if resp.status_code == 401:
        sys.exit("HTTP 401 — invalid or expired token. Check CLOUDFLARE_API_TOKEN.")
    if resp.status_code == 403:
        sys.exit("HTTP 403 — token lacks Analytics:Read on this zone, or zone ID is wrong.")
    if resp.status_code != 200:
        sys.exit(f"HTTP {resp.status_code}: {resp.text[:500]}")

    body = resp.json()
    if body.get("errors"):
        sys.exit(f"GraphQL errors for {ua}:\n{json.dumps(body['errors'], indent=2)}")

    zones = body.get("data", {}).get("viewer", {}).get("zones", [])
    if not zones:
        sys.exit("No zones returned — check zone ID matches torontolife.com.")

    return zones[0].get("httpRequestsAdaptiveGroups", [])


def main():
    env = load_env(ENV_FILE)
    token = env.get("CLOUDFLARE_API_TOKEN")
    zone_id = env.get("CLOUDFLARE_ZONE_ID")
    if not token or not zone_id:
        sys.exit("Need CLOUDFLARE_API_TOKEN and CLOUDFLARE_ZONE_ID in .env")

    until = date.today() - timedelta(days=1)
    since = until - timedelta(days=13)
    print(f"Fetching AI-bot traffic for zone {zone_id[:8]}… ({since} to {until})")

    all_rows = []
    for ua in AI_BOT_USER_AGENTS:
        rows = fetch_for_bot(token, zone_id, since, until, ua)
        hits = sum(r["count"] for r in rows)
        print(f"  {ua:<22} {len(rows):>5} rows  {hits:>10,} hits")
        for r in rows:
            r["_botName"] = ua
        all_rows.extend(rows)

    output = {
        "data": {
            "viewer": {
                "zones": [
                    {
                        "zoneTag": "torontolife",
                        "httpRequestsAdaptiveGroups": [
                            {
                                "count": r["count"],
                                "dimensions": {
                                    "botCategory": "AI Crawler",
                                    "userAgent": r["_botName"],
                                    "clientRequestPath": r["dimensions"]["clientRequestPath"],
                                    "date": r["dimensions"]["date"],
                                    "edgeResponseStatus": r["dimensions"].get("edgeResponseStatus", 0),
                                },
                            }
                            for r in all_rows
                        ],
                    }
                ]
            }
        }
    }

    OUT_FILE.write_text(json.dumps(output, indent=2))
    total = sum(r["count"] for r in all_rows)
    unique_paths = len({r["dimensions"]["clientRequestPath"] for r in all_rows})
    print(
        f"\nwrote {OUT_FILE.relative_to(ROOT)} — {len(all_rows):,} rows, "
        f"{total:,} total hits across {unique_paths} unique paths"
    )

    if not all_rows:
        print(
            "\nWARNING: 0 AI-bot rows. Either no AI traffic this period,\n"
            "or the userAgent strings don't match what CF records."
        )


if __name__ == "__main__":
    main()
