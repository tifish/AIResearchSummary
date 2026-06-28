"""Stage new articles (discover + extract bodies) for PARALLEL generation.

Discovery + extraction use the local Chrome / network and run serially here; the
slow LLM step (summary + digest) is then done in parallel by a Workflow over the
manifest this prints, and applied with apply_batch.py.

    python scripts/prepare_batch.py --sources cursor [--limit N] [--out DIR]
prints JSON: {"manifest": <path>, "count": N, "batch_dir": <dir>}
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
import time
from pathlib import Path

from discover_articles import (
    DEFAULT_SINCE,
    SOURCES,
    default_state_path,
    discover,
    normalize_url,
    read_existing_urls,
)
from extract_article import extract
from render_site import default_site_dir, summary_slug


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Discover + extract new articles, staged for parallel generation.")
    parser.add_argument("--sources", default=None, help="逗号分隔来源 id，默认全部。")
    parser.add_argument("--limit", type=int, default=None, help="最多准备多少篇（测试用）。")
    parser.add_argument("--out", default=None, help="批次目录（默认临时目录）。")
    parser.add_argument("--fetch-delay", type=float, default=1.5, help="抓取文章正文之间的间隔秒数（默认 1.5，对来源站点友好）。")
    args = parser.parse_args()

    sources = [s.strip() for s in args.sources.split(",") if s.strip()] if args.sources else list(SOURCES)
    state = default_state_path()
    site = default_site_dir()

    print("Discovering...", file=sys.stderr)
    articles, errors = discover(sources, DEFAULT_SINCE)
    for err in errors:
        print(f"  source error: {err}", file=sys.stderr)
    existing = read_existing_urls(state)
    new = [a for a in articles if normalize_url(a["url"]) not in existing]
    if args.limit is not None:
        new = new[: args.limit]
    print(f"  {len(new)} new article(s) to prepare", file=sys.stderr)

    batch_dir = Path(args.out) if args.out else Path(tempfile.mkdtemp(prefix="airs-batch-"))
    batch_dir.mkdir(parents=True, exist_ok=True)

    items = []
    for i, art in enumerate(new):
        if i and args.fetch_delay > 0:
            time.sleep(args.fetch_delay)
        try:
            extracted = extract(art["url"])
        except Exception as exc:
            print(f"  extract failed, skip {art['url']}: {exc}", file=sys.stderr)
            continue
        if not extracted.get("article_text"):
            print(f"  no text, skip {art['url']}", file=sys.stderr)
            continue
        record = {**art, "article_text": extracted["article_text"], "source_hash": extracted["source_hash"]}
        slug = summary_slug(art["url"])
        input_path = batch_dir / f"{i:03d}.json"
        input_path.write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")
        items.append({
            "i": i,
            "url": art["url"],
            "slug": slug,
            "title": art.get("title", ""),
            "input": str(input_path),
            "out_file": str(site / "summaries" / f"{slug}.html"),
        })
        print(f"  prepared [{i}] {art.get('title','')[:50]}", file=sys.stderr)

    manifest = {
        "spec_path": str(Path(__file__).resolve().parents[1] / "prompts" / "article.md"),
        "state_path": str(state),
        "site_dir": str(site),
        "items": items,
    }
    manifest_path = batch_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"manifest": str(manifest_path), "count": len(items), "batch_dir": str(batch_dir)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
