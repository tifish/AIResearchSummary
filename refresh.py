#!/usr/bin/env python3
"""Refresh the AI research summary site (single flow):

    discover -> per new article: extract -> generate (摘要 + 总结 in ONE agent call) -> render

Thin orchestrator; the real work lives in scripts/. Use --url to process just one
article (testing); otherwise it processes every newly discovered article.
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

import generate  # noqa: E402
from discover_articles import (  # noqa: E402
    DEFAULT_SINCE,
    SOURCES,
    default_state_path,
    discover,
    normalize_url,
    read_existing_urls,
)
from extract_article import extract  # noqa: E402
from render_site import default_site_dir, load_articles, render_page, summary_slug  # noqa: E402


def render(site, state) -> None:
    (site / "index.html").write_text(render_page(load_articles(state), site), encoding="utf-8")


def process(meta, agent, site, state, force) -> bool:
    result = generate.generate(meta, agent)
    generate.upsert_summary(state, meta, result["summary_zh"], result["value_zh"])
    return generate.write_digest(site, summary_slug(meta["url"]), result["html"], force)


def main() -> int:
    parser = argparse.ArgumentParser(description="Discover -> generate (summary + digest) -> render the site.")
    parser.add_argument("--agent", choices=["codex", "claude"], default="codex")
    parser.add_argument("--sources", default=None, help="逗号分隔的来源 id，默认全部。")
    parser.add_argument("--discover-only", action="store_true", help="只做发现（步骤一），列出发现到的文章，不生成、不渲染。")
    parser.add_argument("--url", default=None, help="只对这一篇文章生成摘要和总结（步骤二，单篇测试，覆盖已有总结页）。")
    parser.add_argument("--dry-run", action="store_true", help="不调用 Agent、不写文件。")
    args = parser.parse_args()

    state = default_state_path()
    site = default_site_dir()
    sources = [s.strip() for s in args.sources.split(",") if s.strip()] if args.sources else list(SOURCES)

    if args.discover_only:
        articles, source_errors = discover(sources, DEFAULT_SINCE)
        existing = read_existing_urls(state)
        for err in source_errors:
            print(f"  source error: {err}")
        new = 0
        for art in articles:
            is_new = normalize_url(art["url"]) not in existing
            new += 1 if is_new else 0
            print(f"  [{'NEW' if is_new else '   '}] {art.get('date', '')} | {art.get('source', '')} | {art.get('title', '')}")
        print(f"Total discovered {len(articles)}, {new} new.")
        return 0

    if args.url:
        try:
            meta = extract(args.url)
        except (RuntimeError, ValueError, OSError) as exc:
            print(f"refresh.py: extract failed: {exc}", file=sys.stderr)
            return 1
        if not meta.get("article_text"):
            print(f"refresh.py: no article text for {args.url}", file=sys.stderr)
            return 1
        if args.dry_run:
            print(generate.build_prompt(meta))
            return 0
        try:
            wrote = process(meta, args.agent, site, state, force=True)
        except Exception as exc:
            print(f"refresh.py: {exc}", file=sys.stderr)
            return 1
        render(site, state)
        print(f"Done: {meta['title']} (digest {'written' if wrote else 'skipped'}). Open site/index.html.")
        return 0

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

    done = 0
    for art in new_articles:
        print(f"- {art.get('title', art['url'])}")
        try:
            extracted = extract(art["url"])
            meta = {**art, "article_text": extracted["article_text"], "source_hash": extracted["source_hash"]}
            process(meta, args.agent, site, state, force=False)
            done += 1
        except Exception as exc:  # keep the batch going on a single bad article
            print(f"    skipped: {exc}")
    render(site, state)
    print(f"Done. {done} articles processed. Open site/index.html.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
