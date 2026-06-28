#!/usr/bin/env python3
"""Refresh the AI research summary site by chaining the pipeline scripts:

    discover -> (per new article) extract -> summarize [-> digest] -> render

Kept intentionally thin: every real step lives in scripts/ and is reused here.
"""

from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "scripts"))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

from discover_articles import (  # noqa: E402
    DEFAULT_SINCE,
    SOURCES,
    default_state_path,
    discover,
    normalize_url,
    read_existing_urls,
)
from extract_article import extract  # noqa: E402
from generate_digest import make_digest  # noqa: E402
from generate_summary import summarize, upsert  # noqa: E402
from render_site import default_site_dir, load_articles, render_page, summary_slug  # noqa: E402


def render(site, state) -> None:
    (site / "index.html").write_text(render_page(load_articles(state), site), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Discover -> summarize (+digest) -> render the AI research summary site.")
    parser.add_argument("--agent", choices=["codex", "claude"], default="codex")
    parser.add_argument("--summary-only", action="store_true", help="只生成摘要，跳过独立总结页。")
    parser.add_argument("--sources", default=None, help="逗号分隔的来源 id，默认全部。")
    parser.add_argument("--dry-run", action="store_true", help="只发现并列出将处理的新文章，不调用 Agent、不写文件。")
    args = parser.parse_args()

    sources = [s.strip() for s in args.sources.split(",") if s.strip()] if args.sources else list(SOURCES)
    state = default_state_path()
    site = default_site_dir()

    print("Discovering new AI research articles...")
    articles, source_errors = discover(sources, DEFAULT_SINCE)
    for err in source_errors:
        print(f"  source error: {err}")
    existing = read_existing_urls(state)
    new_articles = [a for a in articles if normalize_url(a["url"]) not in existing]
    print(f"Discovered {len(articles)}, {len(new_articles)} new.")

    if args.dry_run:
        for art in new_articles:
            print(f"  would process: {art.get('date', '')} | {art.get('source', '')} | {art.get('title', '')}")
        return 0

    if not new_articles:
        render(site, state)
        print("No new articles. Rendered site/index.html.")
        return 0

    summaries = digests = 0
    for art in new_articles:
        url = art["url"]
        print(f"- {art.get('title', url)}")
        try:
            extracted = extract(url)
            meta = {**art, "article_text": extracted["article_text"], "source_hash": extracted["source_hash"]}
            vals = summarize(meta, args.agent)
            upsert(state, meta, vals["summary_zh"], vals["value_zh"])
            summaries += 1
        except Exception as exc:  # keep the batch going on a single bad article
            print(f"    summary skipped: {exc}")
            continue
        if args.summary_only:
            continue
        slug = summary_slug(url)
        out_path = site / "summaries" / f"{slug}.html"
        if not slug or out_path.exists():
            continue
        try:
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(make_digest(meta, args.agent), encoding="utf-8")
            digests += 1
        except Exception as exc:
            print(f"    digest skipped: {exc}")

    render(site, state)
    print(f"Done. {summaries} summaries, {digests} digest pages. Open site/index.html.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
