"""Generate a synthetic CF GraphQL response for the digest demo."""
import json
import random
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

RANDOM_SEED = 42
START_DATE = date(2026, 4, 27)
END_DATE = date(2026, 5, 10)

BOT_WEIGHTS = {
    "GPTBot": 1.00,
    "ClaudeBot": 0.55,
    "PerplexityBot": 0.40,
    "CCBot": 0.30,
    "Bytespider": 0.25,
    "Google-Extended": 0.20,
    "Applebot-Extended": 0.12,
    "Amazonbot": 0.10,
    "meta-externalagent": 0.08,
}

# (start, end) multipliers — linear ramp over the 14-day window.
# Each bot trends independently so the WoW view shows a believable mix of
# rising/falling/flat crawlers instead of one heroic spike against dead air.
BOT_RAMP = {
    "GPTBot": (0.95, 1.05),
    "ClaudeBot": (0.93, 1.08),
    "PerplexityBot": (0.85, 1.18),
    "CCBot": (1.06, 0.94),
    "Bytespider": (0.30, 2.10),
    "Google-Extended": (0.88, 1.14),
    "Applebot-Extended": (1.00, 1.00),
    "Amazonbot": (1.04, 0.92),
    "meta-externalagent": (0.96, 1.06),
}

BASE_HITS_PER_BOT_PER_ARTICLE_PER_DAY = 45


def main():
    random.seed(RANDOM_SEED)
    root = Path(__file__).resolve().parent.parent
    articles = json.loads((root / "data" / "articles.json").read_text())

    by_brand = defaultdict(list)
    for a in articles:
        by_brand[a["brand"]].append(a)

    total_days = (END_DATE - START_DATE).days + 1
    zones_out = []
    for brand, brand_articles in by_brand.items():
        rows = []
        for d_offset in range(total_days):
            day = START_DATE + timedelta(days=d_offset)
            weekend_factor = 0.65 if day.weekday() >= 5 else 1.0
            for article in brand_articles:
                pop = article.get("popularity", 1.0)
                for bot, weight in BOT_WEIGHTS.items():
                    ramp_start, ramp_end = BOT_RAMP[bot]
                    day_factor = ramp_start + (ramp_end - ramp_start) * d_offset / (total_days - 1)
                    jitter = random.uniform(0.7, 1.3)
                    count = int(
                        BASE_HITS_PER_BOT_PER_ARTICLE_PER_DAY
                        * weight
                        * pop
                        * weekend_factor
                        * day_factor
                        * jitter
                    )
                    if count <= 0:
                        continue
                    rows.append({
                        "count": count,
                        "dimensions": {
                            "botCategory": "AI Crawler",
                            "userAgent": bot,
                            "clientRequestPath": article["path"],
                            "date": day.isoformat(),
                        },
                    })
        zones_out.append({"zoneTag": brand, "httpRequestsAdaptiveGroups": rows})

    response = {"data": {"viewer": {"zones": zones_out}}}
    out = root / "data" / "cf_events.json"
    out.write_text(json.dumps(response, indent=2))
    total_rows = sum(len(z["httpRequestsAdaptiveGroups"]) for z in zones_out)
    total_hits = sum(
        r["count"] for z in zones_out for r in z["httpRequestsAdaptiveGroups"]
    )
    print(f"wrote {out.relative_to(root)} — {total_rows:,} rows, {total_hits:,} total hits "
          f"across {len(zones_out)} zones, {START_DATE} to {END_DATE}")


if __name__ == "__main__":
    main()
