"""Generate ONLY the index-page Chinese summary (摘要) for one article — for testing.

Runs the deterministic extract step, asks the agent CLI to produce summary_zh /
value_zh, and upserts the record into site/articles.json. Does NOT generate the
standalone digest page (see generate_digest.py for that).

    python scripts/generate_summary.py --url "https://www.anthropic.com/research/..."
    python scripts/generate_summary.py --url "<URL>" --agent claude
    python scripts/generate_summary.py --url "<URL>" --dry-run    # just print the prompt
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

from agent_cli import extract_json, load_prompt, run_agent
from extract_article import extract, normalize_url
from render_site import default_site_dir, load_articles, render_page


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")


def build_prompt(meta: dict) -> str:
    return (
        f"{load_prompt('summary.md')}\n\n## 文章\n"
        f"标题：{meta['title']}\n"
        f"来源：{meta['source_name']}\n"
        f"日期：{meta['date']}\n"
        f"分类：{meta['category']}\n"
        f"URL：{meta['url']}\n\n"
        f"正文：\n{meta['article_text']}\n"
    )


def summarize(meta: dict, agent: str) -> dict:
    """Call the agent to produce {summary_zh, value_zh} for an extracted article."""
    data = json.loads(extract_json(run_agent(build_prompt(meta), agent)))
    summary_zh = str(data.get("summary_zh", "")).strip()
    value_zh = str(data.get("value_zh", "")).strip()
    if not summary_zh:
        raise ValueError("agent did not return a summary_zh")
    return {"summary_zh": summary_zh, "value_zh": value_zh}


def upsert(state_path: Path, meta: dict, summary_zh: str, value_zh: str) -> None:
    records = load_articles(state_path) if state_path.exists() else []
    url = normalize_url(meta["url"])
    for record in records:
        if normalize_url(str(record.get("url", ""))) == url:
            record["summary_zh"] = summary_zh
            record["value_zh"] = value_zh
            break
    else:
        records.append({
            "source": meta["source"],
            "source_name": meta["source_name"],
            "url": url,
            "title": meta["title"],
            "date": meta["date"],
            "category": meta["category"],
            "summary_zh": summary_zh,
            "value_zh": value_zh,
            "added_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "source_hash": meta["source_hash"],
        })
    state_path.write_text(json.dumps(records, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate only the Chinese index summary (摘要) for one article.")
    parser.add_argument("--url", required=True, help="Article URL.")
    parser.add_argument("--agent", choices=["codex", "claude"], default="claude",
                        help="Agent CLI to call. Default claude (--print gives clean output for capture).")
    parser.add_argument("--dry-run", action="store_true", help="Print the assembled prompt and exit; do not call the agent.")
    parser.add_argument("--no-render", action="store_true", help="Do not re-render site/index.html afterward.")
    args = parser.parse_args()

    try:
        meta = extract(args.url)
    except (RuntimeError, ValueError, OSError) as exc:
        print(f"generate_summary.py: {exc}", file=sys.stderr)
        return 1
    if not meta.get("article_text"):
        print(f"generate_summary.py: no article text extracted for {args.url}", file=sys.stderr)
        return 1

    if args.dry_run:
        print(build_prompt(meta))
        return 0

    try:
        vals = summarize(meta, args.agent)
    except (RuntimeError, ValueError, json.JSONDecodeError) as exc:
        print(f"generate_summary.py: {exc}", file=sys.stderr)
        return 1

    site = default_site_dir()
    try:
        upsert(site / "articles.json", meta, vals["summary_zh"], vals["value_zh"])
        print(f"Updated summary for: {meta['title']}")
        if not args.no_render:
            (site / "index.html").write_text(render_page(load_articles(site / "articles.json"), site), encoding="utf-8")
            print("Re-rendered site/index.html")
    except (ValueError, json.JSONDecodeError, OSError) as exc:
        print(f"generate_summary.py: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
