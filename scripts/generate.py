"""Generate an article's Chinese summary (摘要) and standalone digest (总结) in ONE agent call.

The agent returns both parts in a single response, separated by ===SUMMARY=== /
===DIGEST=== markers, so the article body and the agent overhead are paid once.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

from agent_cli import extract_html, extract_json, load_prompt, run_agent
from extract_article import normalize_url
from render_site import load_articles


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

SUMMARY_MARK = "===SUMMARY==="
DIGEST_MARK = "===DIGEST==="


def build_prompt(meta: dict) -> str:
    return (
        f"{load_prompt('article.md')}\n\n## 文章\n"
        f"标题：{meta['title']}\n"
        f"来源：{meta['source_name']}\n"
        f"日期：{meta['date']}\n"
        f"分类：{meta['category']}\n"
        f"URL：{meta['url']}\n\n"
        f"正文：\n{meta['article_text']}\n"
    )


def generate(meta: dict, agent: str) -> dict:
    """One agent call -> {summary_zh, value_zh, html}."""
    output = run_agent(build_prompt(meta), agent)
    if DIGEST_MARK not in output:
        raise ValueError("agent output is missing the ===DIGEST=== marker")
    head, _, tail = output.partition(DIGEST_MARK)
    summary_part = head.split(SUMMARY_MARK, 1)[-1]
    data = json.loads(extract_json(summary_part))
    summary_zh = str(data.get("summary_zh", "")).strip()
    value_zh = str(data.get("value_zh", "")).strip()
    if not summary_zh:
        raise ValueError("agent did not return summary_zh")
    html = extract_html(tail)
    if "<html" not in html.lower():
        raise ValueError("agent did not return an HTML digest")
    return {"summary_zh": summary_zh, "value_zh": value_zh, "html": html}


def upsert_summary(state_path: Path, meta: dict, summary_zh: str, value_zh: str) -> None:
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


def write_digest(site_dir: Path, slug: str, html: str, force: bool = False) -> bool:
    if not slug:
        return False
    out_path = site_dir / "summaries" / f"{slug}.html"
    if out_path.exists() and not force:
        return False
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(html, encoding="utf-8")
    return True
