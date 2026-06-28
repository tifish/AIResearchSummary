#!/usr/bin/env python3
"""Refresh the AI research summary site (single flow):

    discover -> per new article: extract -> generate (摘要 + 总结 in ONE agent call) -> render

Thin orchestrator; the real work lives in scripts/. Extraction is serial (OpenAI uses
local Chrome); generation runs in parallel (--jobs). Modes: default batch (newly
discovered), --url (one article), --discover-only (list), --missing-digests (backfill).
"""

from __future__ import annotations

import argparse
import os
import sys
import time

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


def process_batch(work, args, state, site, force_digest=False) -> int:
    """Extract serially, then generate summaries+digests in parallel and apply."""
    prepared = []
    for idx, art in enumerate(work):
        if idx and args.fetch_delay > 0:
            time.sleep(args.fetch_delay)
        try:
            extracted = extract(art["url"])
            prepared.append({**art, "article_text": extracted["article_text"], "source_hash": extracted["source_hash"]})
        except Exception as exc:
            print(f"  extract skipped {art.get('url')}: {exc}")

    def _generate(meta):
        try:
            return meta, generate.generate(meta, args.agent)
        except Exception as exc:  # noqa: BLE001 - report per-article and keep going
            return meta, exc

    def _apply(meta, res) -> bool:
        # Runs in the main thread, so articles.json writes stay serialized.
        title = meta.get("title", meta["url"])
        if not isinstance(res, dict):
            print(f"  skipped {title}: {res}")
            return False
        generate.upsert_summary(state, meta, res["summary_zh"], res["value_zh"])
        generate.write_digest(site, summary_slug(meta["url"]), res["html"], force_digest)
        print(f"  done: {title}")
        return True

    jobs = max(1, args.jobs)
    print(f"Generating {len(prepared)} article(s) with {jobs} parallel job(s)...")
    done = 0
    if jobs == 1:
        for meta in prepared:
            if _apply(*_generate(meta)):
                done += 1
    else:
        from concurrent.futures import ThreadPoolExecutor, as_completed

        with ThreadPoolExecutor(max_workers=jobs) as pool:
            futures = [pool.submit(_generate, meta) for meta in prepared]
            for fut in as_completed(futures):  # write each as it finishes (resilient)
                if _apply(*fut.result()):
                    done += 1
    render(site, state)
    print(f"Done. {done}/{len(prepared)} generated (jobs={jobs}). Open site/index.html.")
    return done


def main() -> int:
    parser = argparse.ArgumentParser(description="Discover -> generate (summary + digest) -> render the site.")
    parser.add_argument("--agent", choices=["codex", "claude"], default="codex")
    parser.add_argument("--sources", default=None, help="逗号分隔的来源 id，默认全部。")
    parser.add_argument("--discover-only", action="store_true", help="只做发现（步骤一），列出发现到的文章，不生成、不渲染。")
    parser.add_argument("--url", default=None, help="只对这一篇文章生成摘要和总结（步骤二，单篇测试，覆盖已有总结页）。")
    parser.add_argument("--missing-digests", action="store_true", help="为 articles.json 中缺独立总结页的文章补生成（摘要+总结）。")
    parser.add_argument("--jobs", type=int, default=12, help="生成摘要+总结的并发数（并行调用 claude/codex CLI，默认 12；1=串行；只受 API 速率限制约束，瞬时错误自动重试）。")
    parser.add_argument("--fetch-delay", type=float, default=1.5, help="抓取文章正文之间的间隔秒数（默认 1.5，对来源站点友好；抓网页是串行的）。")
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

    if args.missing_digests:
        records = load_articles(state)
        work = [
            r for r in records
            if r.get("url") and not (site / "summaries" / f"{summary_slug(str(r['url']))}.html").exists()
        ]
        print(f"{len(work)} article(s) missing a digest page.")
        if args.dry_run:
            for r in work:
                print(f"  would regenerate: {r.get('date', '')} | {r.get('source', '')} | {r.get('title', '')}")
            return 0
        if not work:
            render(site, state)
            print("All articles already have a digest page.")
            return 0
        process_batch(work, args, state, site, force_digest=True)
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

    process_batch(new_articles, args, state, site, force_digest=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
