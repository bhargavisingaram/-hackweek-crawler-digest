"""Render the digest as a styled HTML preview to output/digest.html.

Open the file in a browser to see the demo-ready view.
"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

try:
    from jinja2 import Environment, FileSystemLoader, select_autoescape
except ImportError:
    sys.exit("Install jinja2: pip install -r requirements.txt")

from aggregate import compute_digest, fmt_delta

ROOT = HERE.parent
TEMPLATES = ROOT / "templates"
OUT_FILE = ROOT / "output" / "digest.html"


def main():
    digest = compute_digest()
    env = Environment(
        loader=FileSystemLoader(str(TEMPLATES)),
        autoescape=select_autoescape(["html", "j2"]),
    )
    env.globals["fmt_delta"] = fmt_delta
    template = env.get_template("digest.html.j2")
    OUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    OUT_FILE.write_text(template.render(d=digest))
    print(f"wrote {OUT_FILE.relative_to(ROOT)}")
    print(f"open: file://{OUT_FILE}")


if __name__ == "__main__":
    main()
