"""Render data/*/*/*/candidates.json into a static site for GitHub Pages.

Run with:  python scripts/build_pages.py
Writes the site into ./dist (index.html + static/).
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

REPO_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = REPO_ROOT / "data"
TEMPLATES_DIR = REPO_ROOT / "webui" / "templates"
STATIC_DIR = REPO_ROOT / "webui" / "static"
DIST_DIR = REPO_ROOT / "dist"

STATIC_FILES = ("pages_style.css", "pages_app.js")


def scan_candidate_groups() -> list[dict]:
    groups = []
    for path in sorted(DATA_DIR.glob("*/*/*/candidates.json"), reverse=True):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        groups.append(data)
    return groups


def main() -> None:
    if DIST_DIR.exists():
        shutil.rmtree(DIST_DIR)
    DIST_DIR.mkdir(parents=True)

    env = Environment(
        loader=FileSystemLoader(str(TEMPLATES_DIR)),
        autoescape=select_autoescape(["html"]),
    )
    template = env.get_template("pages_index.html")
    html = template.render(groups=scan_candidate_groups())
    (DIST_DIR / "index.html").write_text(html, encoding="utf-8")

    dist_static = DIST_DIR / "static"
    dist_static.mkdir()
    for name in STATIC_FILES:
        shutil.copy(STATIC_DIR / name, dist_static / name)

    # tells GitHub Pages not to run Jekyll processing over the site
    (DIST_DIR / ".nojekyll").touch()
    print(f"wrote {DIST_DIR}")


if __name__ == "__main__":
    main()
