"""Read CF events + article metadata; compute and print the weekly digest.

Works against either synthetic data (from generate_synthetic_data.py)
or real CF data (from fetch_cf_data.py) — same schema.

Public entry points:
- compute_digest() -> dict: structured digest data (consumed by HTML / Slack renderers)
- print_digest(digest): renders the dict to stdout as text
- main(): convenience for `python src/aggregate.py`
"""
import json
import re
from collections import defaultdict
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
BRAND_NAME = "Toronto Life"

# Set False once affected bylines have given permission to be shown by name.
# When True, real authors are replaced with "Writer A", "Writer B", ...
# ranked by total scrape count.
ANONYMIZE_AUTHORS = True

# Non-article paths to skip when ranking articles. Hits to these paths
# still count toward bot totals (real crawlers fetch robots.txt + assets),
# but they're not editorially interesting.
EXCLUDE_PATH_PREFIXES = (
    "/category/", "/insider/", "/magazine/", "/contests/", "/cityguide/",
    "/_next/", "/api/", "/wp-", "/cdn-cgi/", "/feed/", "/mtg1pm/",
    "/tag/", "/author/", "/page/",
)
NON_ARTICLE_EXT_RE = re.compile(
    r"\.(cfm|js|css|xml|json|txt|png|jpg|jpeg|gif|webp|woff2?|ico|svg|map|pdf|html)(\?|$)"
)


def is_article(path):
    if any(p in path for p in EXCLUDE_PATH_PREFIXES):
        return False
    if NON_ARTICLE_EXT_RE.search(path):
        return False
    parts = [p for p in path.strip("/").split("/") if p]
    if len(parts) < 2 or len(parts) > 3:
        return False
    if len(parts[-1].replace("-", "")) < 8:
        return False
    return True


def slug_to_title(slug):
    return " ".join(w.capitalize() for w in slug.replace("-", " ").split())


def derive_section(path):
    parts = [p for p in path.strip("/").split("/") if p]
    if not parts:
        return "—"
    return parts[0].replace("-", " ").title()


def derive_meta(path):
    parts = [p for p in path.strip("/").split("/") if p]
    title = slug_to_title(parts[-1]) if parts else path
    return {
        "title": title,
        "author": "—",
        "section": derive_section(path),
    }


def load():
    articles = {a["path"]: a for a in json.loads((DATA / "articles.json").read_text())}
    cf = json.loads((DATA / "cf_events.json").read_text())
    rows = []
    for zone in cf["data"]["viewer"]["zones"]:
        for r in zone["httpRequestsAdaptiveGroups"]:
            rows.append({
                "zone": zone["zoneTag"],
                "bot": r["dimensions"]["userAgent"],
                "path": r["dimensions"]["clientRequestPath"],
                "date": date.fromisoformat(r["dimensions"]["date"]),
                "count": r["count"],
                "status": int(r["dimensions"].get("edgeResponseStatus", 0) or 0),
            })
    return articles, rows


def classify_status(status):
    if status == 200:
        return "allowed"
    if status in (403, 429):
        return "blocked"
    return "other"


def split_weeks(rows):
    all_dates = sorted({r["date"] for r in rows})
    this_end = all_dates[-1]
    this_start = all_dates[-7]
    prev_end = all_dates[-8]
    prev_start = all_dates[-14]
    this_week = [r for r in rows if this_start <= r["date"] <= this_end]
    prev_week = [r for r in rows if prev_start <= r["date"] <= prev_end]
    return this_week, prev_week, this_start, this_end


def wow_pct(curr, prev):
    if not prev:
        return 0.0
    return (curr - prev) / prev * 100


def fmt_delta(pct):
    sign = "+" if pct >= 0 else ""
    return f"{sign}{pct:.1f}% WoW"


def short_author(author):
    if not author or author == "—":
        return author
    for sep in [", ", " and "]:
        if sep in author:
            return author.split(sep)[0] + " et al."
    return author


def anon_label(rank):
    if rank < 26:
        return f"Writer {chr(ord('A') + rank)}"
    return f"Writer Z{rank - 25}"


def build_anon_map(by_author_totals):
    ranked = sorted(by_author_totals.items(), key=lambda x: -x[1])
    return {author: anon_label(i) for i, (author, _) in enumerate(ranked)}


def display_author(author, anon_map):
    if not author or author == "—":
        return "—"
    if ANONYMIZE_AUTHORS:
        return anon_map.get(author, "Writer ?")
    return short_author(author)


def fmt_date_range(start, end):
    if start.month == end.month and start.year == end.year:
        return f"{start.strftime('%B')} {start.day}–{end.day}, {end.year}"
    if start.year == end.year:
        return f"{start.strftime('%b')} {start.day} – {end.strftime('%b')} {end.day}, {end.year}"
    return f"{start.strftime('%b %d, %Y')} – {end.strftime('%b %d, %Y')}"


def compute_digest():
    """Return a structured dict with all data needed by any renderer."""
    articles, rows = load()
    this_week, prev_week, week_start, week_end = split_weeks(rows)

    total_all = sum(r["count"] for r in this_week)
    prev_total_all = sum(r["count"] for r in prev_week)

    this_articles = [r for r in this_week if is_article(r["path"])]
    prev_articles = [r for r in prev_week if is_article(r["path"])]
    total_articles = sum(r["count"] for r in this_articles)
    prev_total_articles = sum(r["count"] for r in prev_articles)

    by_bot = defaultdict(int)
    prev_by_bot = defaultdict(int)
    for r in this_week:
        by_bot[r["bot"]] += r["count"]
    for r in prev_week:
        prev_by_bot[r["bot"]] += r["count"]
    top_bots_pairs = sorted(by_bot.items(), key=lambda x: -x[1])

    by_article = defaultdict(lambda: defaultdict(int))
    for r in this_articles:
        by_article[r["path"]][r["bot"]] += r["count"]
    top_article_rows = sorted(
        ((path, sum(bots.values()), bots) for path, bots in by_article.items()),
        key=lambda x: -x[1],
    )[:10]

    by_section = defaultdict(int)
    prev_by_section = defaultdict(int)
    for r in this_articles:
        meta = articles.get(r["path"]) or derive_meta(r["path"])
        by_section[meta["section"]] += r["count"]
    for r in prev_articles:
        meta = articles.get(r["path"]) or derive_meta(r["path"])
        prev_by_section[meta["section"]] += r["count"]
    section_pairs = sorted(by_section.items(), key=lambda x: -x[1])

    by_author = defaultdict(int)
    for path, bots in by_article.items():
        meta = articles.get(path) or derive_meta(path)
        if meta["author"] != "—":
            by_author[meta["author"]] += sum(bots.values())
    top_author_pairs = sorted(by_author.items(), key=lambda x: -x[1])[:5]
    anon_map = build_anon_map(by_author) if ANONYMIZE_AUTHORS else {}

    status_by_bot = defaultdict(lambda: {"allowed": 0, "blocked": 0, "other": 0})
    for r in this_week:
        status_by_bot[r["bot"]][classify_status(r["status"])] += r["count"]

    return {
        "brand": BRAND_NAME,
        "anonymized": ANONYMIZE_AUTHORS,
        "week_start": week_start,
        "week_end": week_end,
        "week_label": fmt_date_range(week_start, week_end),
        "totals": {
            "all": total_all,
            "all_wow": wow_pct(total_all, prev_total_all),
            "articles": total_articles,
            "articles_wow": wow_pct(total_articles, prev_total_articles),
            "noise": total_all - total_articles,
        },
        "top_bots": [
            {
                "bot": bot,
                "count": c,
                "wow": wow_pct(c, prev_by_bot.get(bot, 0)),
            }
            for bot, c in top_bots_pairs[:6]
        ],
        "blocking_status": [
            {
                "bot": bot,
                "allowed": status_by_bot[bot]["allowed"],
                "blocked": status_by_bot[bot]["blocked"],
                "other": status_by_bot[bot]["other"],
                "total": sum(status_by_bot[bot].values()),
                "block_pct": (
                    status_by_bot[bot]["blocked"] / sum(status_by_bot[bot].values()) * 100
                    if sum(status_by_bot[bot].values()) else 0
                ),
            }
            for bot, _ in top_bots_pairs[:6]
        ],
        "by_section": [
            {
                "section": section,
                "count": c,
                "wow": wow_pct(c, prev_by_section.get(section, 0)),
            }
            for section, c in section_pairs[:8]
        ],
        "top_articles": [
            {
                "path": path,
                "title": (articles.get(path) or derive_meta(path))["title"],
                "section": (articles.get(path) or derive_meta(path))["section"],
                "author_display": display_author(
                    (articles.get(path) or derive_meta(path))["author"], anon_map
                ),
                "has_author": (articles.get(path) or derive_meta(path))["author"] != "—",
                "total_hits": total_hits,
                "top_bot": max(bots.items(), key=lambda x: x[1])[0],
                "top_bot_hits": max(bots.items(), key=lambda x: x[1])[1],
                "bot_breakdown": dict(bots),
            }
            for path, total_hits, bots in top_article_rows
        ],
        "top_authors": [
            {
                "author_display": display_author(author, anon_map),
                "count": c,
            }
            for author, c in top_author_pairs
        ],
    }


def print_digest(d):
    bar = "=" * 72
    print(bar)
    print(f"  AI CRAWLER DIGEST — {d['brand']} — Week of {d['week_label']}")
    print(bar)
    print()
    print(f"Total AI bot requests:        {d['totals']['all']:>10,}  ({fmt_delta(d['totals']['all_wow'])})")
    print(f"  → article scrapes:          {d['totals']['articles']:>10,}  ({fmt_delta(d['totals']['articles_wow'])})")
    print(f"  → noise (assets, robots.txt, etc.):  {d['totals']['noise']:>10,}")
    print()

    print("TOP BOTS THIS WEEK")
    print("-" * 72)
    for b in d["top_bots"]:
        print(f"  {b['bot']:<22} {b['count']:>10,}   {fmt_delta(b['wow'])}")
    print()

    print("BLOCKING STATUS BY BOT (CF edge response code)")
    print("-" * 72)
    print(f"  {'Bot':<20} {'Allowed':>8} {'Blocked':>8} {'Other*':>8}  {'Block %':>7}")
    for s in d["blocking_status"]:
        print(f"  {s['bot']:<20} {s['allowed']:>8,} {s['blocked']:>8,} {s['other']:>8,}  {s['block_pct']:>6.1f}%")
    print(f"  {'*':<20} Other = 304 Not Modified, 301 redirects, etc. — not blocking.")
    print()

    print("BY SECTION (articles only)")
    print("-" * 72)
    for sec in d["by_section"]:
        print(f"  {sec['section']:<22} {sec['count']:>10,}   {fmt_delta(sec['wow'])}")
    print()

    print("TOP 10 SCRAPED ARTICLES")
    print("-" * 72)
    for a in d["top_articles"]:
        by_line = f"by {a['author_display']}" if a["has_author"] else ""
        print(f"  [{a['section']}] {a['title']}")
        print(f"     {by_line} — {a['total_hits']:,} hits  (top: {a['top_bot']} {a['top_bot_hits']:,})")
    print()

    if d["top_authors"]:
        print("TOP AUTHORS BY SCRAPE COUNT")
        print("-" * 72)
        for au in d["top_authors"]:
            print(f"  {au['author_display']:<28} {au['count']:>10,}")
        print()

    print(bar)


def main():
    print_digest(compute_digest())


if __name__ == "__main__":
    main()
