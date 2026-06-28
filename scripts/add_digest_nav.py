"""Add the standard nav (back to index + original article) to existing digest pages.

For each site/summaries/*.html, look up the article URL in site/articles.json and
inject the nav (idempotent). New pages get the nav automatically via generate.py.
"""

from __future__ import annotations

import sys

from render_site import default_site_dir, inject_nav, load_articles, summary_slug


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


def main() -> int:
    site = default_site_dir()
    summaries = site / "summaries"
    if not summaries.exists():
        print("No summaries directory.")
        return 0
    articles = load_articles(site / "articles.json")
    url_by_slug = {
        summary_slug(str(a.get("url", ""))): str(a.get("url", ""))
        for a in articles
        if a.get("url")
    }
    changed = unchanged = missing = 0
    for page in sorted(summaries.glob("*.html")):
        url = url_by_slug.get(page.stem)
        if not url:
            print(f"  no URL in articles.json for {page.name} (skip)")
            missing += 1
            continue
        html = page.read_text(encoding="utf-8")
        new_html = inject_nav(html, url)
        if new_html != html:
            page.write_text(new_html, encoding="utf-8")
            print(f"  + nav: {page.name}")
            changed += 1
        else:
            print(f"  = already has nav: {page.name}")
            unchanged += 1
    print(f"Done: {changed} updated, {unchanged} unchanged, {missing} without a URL.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
