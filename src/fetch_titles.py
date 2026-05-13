
import json
import re
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path

try:
    import cloudscraper
except ImportError:
    sys.exit("Install: pip install -r requirements.txt")

try:
    from bs4 import BeautifulSoup
except ImportError:
    sys.exit("Install: pip install -r requirements.txt")

ROOT = Path(__file__).resolve().parent.parent
CF_DATA = ROOT / "data" / "cf_events.json"
OUT_FILE = ROOT / "data" / "articles_real.json"
TOP_N = 10

EXCLUDE = (
    "/category/", "/insider/", "/magazine/", "/contests/", "/cityguide/",
    "/_next/", "/api/", "/wp-", "/cdn-cgi/", "/feed/", "/mtg1pm/",
    "/tag/", "/author/", "/page/",
)
NON_ARTICLE_EXT = re.compile(
    r"\.(cfm|js|css|xml|json|txt|png|jpg|jpeg|gif|webp|woff2?|ico|svg|map|pdf|html)(\?|$)"
)


def is_article(path):
    if any(p in path for p in EXCLUDE):
        return False
    if NON_ARTICLE_EXT.search(path):
        return False
    parts = [p for p in path.strip("/").split("/") if p]
    if len(parts) < 2 or len(parts) > 3:
        return False
    if len(parts[-1].replace("-", "")) < 8:
        return False
    return True


def top_article_paths(n):
    data = json.load(open(CF_DATA))
    rows = data["data"]["viewer"]["zones"][0]["httpRequestsAdaptiveGroups"]
    all_dates = sorted({date.fromisoformat(r["dimensions"]["date"]) for r in rows})
    this_start = all_dates[-7]
    by_path = defaultdict(int)
    for r in rows:
        if date.fromisoformat(r["dimensions"]["date"]) < this_start:
            continue
        p = r["dimensions"]["clientRequestPath"]
        if is_article(p):
            by_path[p] += r["count"]
    return sorted(by_path.items(), key=lambda x: -x[1])[:n]


SITE_SUFFIXES = (" - Toronto Life", " | Toronto Life", " – Toronto Life", " — Toronto Life")


def strip_site_suffix(title):
    for s in SITE_SUFFIXES:
        if title.endswith(s):
            return title[: -len(s)].strip()
    return title.strip()


def jsonld_blocks(soup):
    """Yield decoded JSON-LD blocks from the page."""
    for script in soup.find_all("script", type="application/ld+json"):
        raw = script.string or script.get_text() or ""
        try:
            data = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            continue
        if isinstance(data, list):
            for item in data:
                yield item
        else:
            yield data
            if isinstance(data, dict) and "@graph" in data:
                for item in data["@graph"]:
                    yield item


def extract_title(soup):
    og = soup.find("meta", attrs={"property": "og:title"})
    if og and og.get("content"):
        return strip_site_suffix(og["content"].strip())
    if soup.title and soup.title.string:
        t = soup.title.string
        for sep in [" | ", " - ", " – ", " — "]:
            if sep in t:
                t = t.split(sep)[0]
                break
        return t.strip()
    h1 = soup.find("h1")
    if h1:
        return h1.get_text(strip=True)
    return "?"


def _author_from_value(val):
    if isinstance(val, str) and val.strip():
        return val.strip()
    if isinstance(val, dict):
        name = val.get("name")
        if isinstance(name, str) and name.strip():
            return name.strip()
    if isinstance(val, list) and val:
        return _author_from_value(val[0])
    return None


def extract_author(soup):
    for block in jsonld_blocks(soup):
        if not isinstance(block, dict):
            continue
        if block.get("@type") in ("Article", "NewsArticle", "BlogPosting", "WebPage"):
            name = _author_from_value(block.get("author"))
            if name:
                return name
    for block in jsonld_blocks(soup):
        if isinstance(block, dict):
            name = _author_from_value(block.get("author"))
            if name:
                return name
    for attrs in [
        {"property": "article:author"},
        {"name": "author"},
        {"property": "author"},
    ]:
        m = soup.find("meta", attrs=attrs)
        if m and m.get("content"):
            v = m["content"].strip()
            if v and not v.startswith("http"):
                return v
    a = soup.find("a", attrs={"rel": "author"})
    if a:
        return a.get_text(strip=True)
    for sel in [".byline", ".author-name", ".entry-author", ".post-author", ".author a", ".byline-name"]:
        el = soup.select_one(sel)
        if el:
            text = el.get_text(strip=True)
            text = re.sub(r"^[Bb]y\s+", "", text)
            if text:
                return text
    return "?"


def extract_pubdate(soup):
    for block in jsonld_blocks(soup):
        if isinstance(block, dict):
            d = block.get("datePublished") or block.get("dateCreated")
            if isinstance(d, str) and len(d) >= 10:
                return d[:10]
    m = soup.find("meta", attrs={"property": "article:published_time"})
    if m and m.get("content"):
        return m["content"][:10]
    return ""


def extract_section(soup, path):
    parts = [p for p in path.strip("/").split("/") if p]
    return parts[0].replace("-", " ").title() if parts else "?"


def main():
    top = top_article_paths(TOP_N)
    if not top:
        sys.exit("No article paths found in cf_events.json.")

    print(f"Fetching titles for top {len(top)} articles via cloudscraper…\n")
    scraper = cloudscraper.create_scraper()
    results = []
    failed = 0

    for i, (path, hits) in enumerate(top, 1):
        url = f"https://torontolife.com{path}"
        print(f"[{i}/{len(top)}] {path}")
        try:
            resp = scraper.get(url, timeout=20)
            if resp.status_code != 200:
                print(f"        HTTP {resp.status_code} — skipped")
                failed += 1
                continue
            soup = BeautifulSoup(resp.text, "html.parser")
            title = extract_title(soup)
            author = extract_author(soup)
            section = extract_section(soup, path)
            pubdate = extract_pubdate(soup)
            results.append({
                "id": f"tl-real-{i:03d}",
                "brand": "torontolife",
                "brand_display": "Toronto Life",
                "path": path,
                "title": title,
                "author": author,
                "section": section,
                "published_date": pubdate,
                "popularity": 1.0,
                "_hits_this_week": hits,
            })
            print(f"        title:   {title}")
            print(f"        author:  {author}")
            print(f"        section: {section}")
        except Exception as e:
            print(f"        ERROR: {e}")
            failed += 1
        print()

    print(f"\nDone. {len(results)} successful, {failed} failed.")

    if not results:
        sys.exit(
            "\n0 articles fetched. CF is blocking cloudscraper too.\n"
            "Fall back to manual lookup."
        )

    OUT_FILE.write_text(json.dumps(results, indent=2))
    print(f"\nWrote {OUT_FILE.relative_to(ROOT)}")
    print("Review it, then to use these as the real articles:")
    print(f"  cp {OUT_FILE.relative_to(ROOT)} data/articles.json")
    print("  python src/aggregate.py")


if __name__ == "__main__":
    main()
