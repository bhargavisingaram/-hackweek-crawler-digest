"""Render the digest as a *brief* Slack Block Kit JSON payload — designed for
Monday-morning scroll, not deep reading.

Output: output/digest_blockkit.json

Headline + biggest concern + top 3 articles + top author + link to full HTML report.
For the full breakdown (10 articles, full bot table, all sections) see digest.html.

Preview: paste contents into https://app.slack.com/block-kit-builder
"""
import json
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from aggregate import compute_digest

ROOT = HERE.parent
OUT_FILE = ROOT / "output" / "digest_blockkit.json"


def fmt_wow(pct):
    arrow = "▲" if pct >= 0 else "▼"
    sign = "+" if pct >= 0 else ""
    return f"{arrow} {sign}{pct:.1f}%"


def find_leaks(blocking_status, leak_threshold_pct=80, min_volume=500):
    """Return bots that are leaking — meaningful scraping volume + below the
    leak threshold. Sorted worst-first. Bots where most traffic is cache-check
    (low allowed+blocked share) are excluded since block % isn't meaningful."""
    leaks = []
    for s in blocking_status:
        if s["total"] == 0:
            continue
        meaningful_volume = s["allowed"] + s["blocked"]
        if meaningful_volume / s["total"] < 0.2:
            continue  # mostly cache-checks; block rate isn't a useful metric
        if meaningful_volume < min_volume:
            continue  # too small to alert on
        if s["block_pct"] >= leak_threshold_pct:
            continue  # tightly blocked
        leaks.append(s)
    leaks.sort(key=lambda x: x["block_pct"])
    return leaks


def section(text):
    return {"type": "section", "text": {"type": "mrkdwn", "text": text}}


def build_blocks(d):
    blocks = []

    # Header
    blocks.append({
        "type": "header",
        "text": {
            "type": "plain_text",
            "text": f":robot_face: AI Crawler Digest — {d['brand']}",
        },
    })

    # Subtitle
    blocks.append({
        "type": "context",
        "elements": [{
            "type": "mrkdwn",
            "text": f"Week of *{d['week_label']}*",
        }],
    })

    blocks.append({"type": "divider"})

    # Bypass headline — leads with the number leadership actually wanted
    total_allowed = sum(s["allowed"] for s in d["blocking_status"])
    total_blocked = sum(s["blocked"] for s in d["blocking_status"])
    overall_total = total_allowed + total_blocked
    overall_block_pct = (total_blocked / overall_total * 100) if overall_total else 0
    blocks.append(section(
        f":rotating_light:  *{total_allowed:,} AI bot requests bypassed bot management this week.*\n"
        f"     {total_blocked:,} successfully blocked  ·  *{overall_block_pct:.0f}% overall block rate*"
    ))

    # Specific bypassers — which bots got past the bot management
    leaks = find_leaks(d["blocking_status"])
    if leaks:
        leak_lines = []
        for i, l in enumerate(leaks):
            emoji = ":rotating_light:" if i == 0 else ":warning:"
            label = "Biggest bypass" if i == 0 else "Also bypassing"
            leak_lines.append(
                f"{emoji}  *{label}: {l['bot']}* — {l['allowed']:,} requests got through "
                f"({l['block_pct']:.1f}% block rate)"
            )
        blocks.append(section("\n".join(leak_lines)))

    # Top 3 articles
    if d["top_articles"]:
        article_lines = ["*Top 3 scraped articles this week:*"]
        for i, a in enumerate(d["top_articles"][:3], 1):
            by_line = f" — *{a['author_display']}*" if a["has_author"] else ""
            article_lines.append(
                f"`{i}.` *[{a['section']}]* {a['title']}{by_line}  ·  "
                f"{a['total_hits']:,} hits"
            )
        blocks.append(section("\n".join(article_lines)))

    # Top author callout
    if d["top_authors"]:
        top_author = d["top_authors"][0]
        article_counts = Counter(
            a["author_display"] for a in d["top_articles"] if a["has_author"]
        )
        piece_count = article_counts.get(top_author["author_display"], 0)
        piece_text = f"across {piece_count} pieces" if piece_count > 1 else "this week"
        blocks.append(section(
            f":bookmark_tabs:  *Most-scraped writer:* {top_author['author_display']}  —  "
            f"*{top_author['count']:,}* hits {piece_text}"
        ))

    blocks.append({"type": "divider"})

    # Footer. In production this becomes a link to the hosted weekly archive.
    footer_parts = [":bar_chart: *Full report*"]
    if d["anonymized"]:
        footer_parts.append("Bylines anonymized for demo")
    footer_parts.append("CF GraphQL capped at 10k rows")
    blocks.append({
        "type": "context",
        "elements": [{"type": "mrkdwn", "text": "  ·  ".join(footer_parts)}],
    })

    return {"blocks": blocks}


def main():
    digest = compute_digest()
    payload = build_blocks(digest)
    OUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    OUT_FILE.write_text(json.dumps(payload, indent=2))
    print(f"wrote {OUT_FILE.relative_to(ROOT)} ({len(payload['blocks'])} blocks)")
    print(f"preview at: https://app.slack.com/block-kit-builder")


if __name__ == "__main__":
    main()
