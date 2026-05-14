"""Render the AI research Chinese summary site."""

from __future__ import annotations

import argparse
import html
import json
import urllib.parse
from datetime import datetime
from pathlib import Path
from typing import Any


SOURCE_HOME_URLS = {
    "anthropic": "https://www.anthropic.com/economic-futures",
    "openai": "https://openai.com/research/index/",
    "cursor": "https://cursor.com/blog/topic/research",
}


def workspace_root() -> Path:
    script_path = Path(__file__).resolve()
    skill_parent = script_path.parents[2]
    if skill_parent.name == "skills" and skill_parent.parent.name == ".agents":
        return script_path.parents[4]
    if skill_parent.name == "skills":
        return script_path.parents[3]
    return skill_parent


def default_site_dir() -> Path:
    return workspace_root() / "site"


def load_articles(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    records = data.get("articles", data) if isinstance(data, dict) else data
    if not isinstance(records, list):
        raise ValueError(f"{path} must contain a JSON list or an object with an articles list.")
    return [record for record in records if isinstance(record, dict)]


def parse_date(value: str) -> datetime:
    for fmt in ("%b %d, %Y", "%B %d, %Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    return datetime.min


def esc(value: Any) -> str:
    return html.escape(str(value or ""), quote=True)


def summary_slug(url: str) -> str:
    path = urllib.parse.urlsplit(url).path.rstrip("/")
    slug = path.rsplit("/", 1)[-1]
    return slug


def summary_href(record: dict[str, Any], site_dir: Path) -> str:
    slug = summary_slug(str(record.get("url", "")))
    if not slug:
        return ""
    summary_path = site_dir / "summaries" / f"{slug}.html"
    if not summary_path.exists():
        return ""
    return f"summaries/{slug}.html"


def render_summary(summary: str, value: str) -> str:
    combined = summary if not value else f"{summary} 价值：{value}"
    parts = []
    labels = ("结论：", "关键数据：", "价值：")
    for index, label in enumerate(labels):
        start = combined.find(label)
        if start < 0:
            continue
        end_candidates = [combined.find(next_label, start + len(label)) for next_label in labels[index + 1 :]]
        end_candidates = [candidate for candidate in end_candidates if candidate >= 0]
        end = min(end_candidates) if end_candidates else len(combined)
        body = combined[start + len(label) : end].strip()
        if body:
            parts.append(f'<p class="summary-line"><strong>{esc(label[:-1])}</strong><span>{esc(body)}</span></p>')
    if parts:
        return "\n        ".join(parts)
    return f"<p>{esc(combined)}</p>"


def render_article(record: dict[str, Any], site_dir: Path) -> str:
    summary = str(record.get("summary_zh", "")).strip()
    value = str(record.get("value_zh", "")).strip()
    source = str(record.get("source", "") or "unknown").strip().lower()
    source_name = str(record.get("source_name", "") or source or "Unknown").strip()
    source_home_url = SOURCE_HOME_URLS.get(source, str(record.get("url", "")))
    search_text = " ".join(
        str(record.get(key, ""))
        for key in ("source", "source_name", "title", "date", "category", "summary_zh", "value_zh")
    )
    summary_html = render_summary(summary, value)
    local_summary_href = summary_href(record, site_dir)
    summary_link = (
        f'<a class="source-link summary-link" href="{esc(local_summary_href)}" target="_blank" rel="noopener noreferrer">阅读总结</a>'
        if local_summary_href
        else ""
    )
    return f"""
      <article class="article-card source-{esc(source)}" data-search="{esc(search_text.lower())}" data-source="{esc(source)}">
        <div class="meta">
          <a class="source-badge" href="{esc(source_home_url)}" target="_blank" rel="noopener noreferrer">{esc(source_name)}</a>
          <time>{esc(record.get("date"))}</time>
          <span>{esc(record.get("category"))}</span>
        </div>
        <h2>{esc(record.get("title"))}</h2>
        <div class="summary">
        {summary_html}
        </div>
        <div class="article-actions">
          {summary_link}
          <a class="source-link" href="{esc(record.get("url"))}" target="_blank" rel="noopener noreferrer">阅读原文</a>
        </div>
      </article>"""


def render_page(articles: list[dict[str, Any]], site_dir: Path | None = None) -> str:
    site_dir = site_dir or default_site_dir()
    sorted_articles = sorted(articles, key=lambda item: parse_date(str(item.get("date", ""))), reverse=True)
    updated_at = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M %Z")
    cards = "\n".join(render_article(record, site_dir) for record in sorted_articles)
    empty = "" if cards else '<p class="empty">还没有文章。运行 skill 更新后会在这里显示摘要。</p>'
    source_counts: dict[str, int] = {}
    source_ids: dict[str, str] = {}
    for article in sorted_articles:
        source_name = str(article.get("source_name", "") or article.get("source", "") or "Unknown")
        source_id = str(article.get("source", "") or source_name).strip().lower()
        source_counts[source_name] = source_counts.get(source_name, 0) + 1
        source_ids[source_name] = source_id
    source_summary = " · ".join(f"{esc(name)} {count}" for name, count in sorted(source_counts.items()))
    source_buttons = "\n".join(
        f'<button type="button" class="filter-button" data-source-filter="{esc(source_ids[name])}">{esc(name)}</button>'
        for name in sorted(source_counts)
    )
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>AI Research 中文简介</title>
  <style>
    :root {{
      color-scheme: light;
      --ink: #191816;
      --muted: #6f6a62;
      --line: #d9d1c4;
      --paper: #f7f4ed;
      --panel: #fffdf8;
      --accent: #1f6f5b;
      --accent-dark: #164d40;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      background: var(--paper);
      color: var(--ink);
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "Microsoft YaHei", sans-serif;
      line-height: 1.55;
    }}
    .page {{
      width: min(1120px, calc(100% - 32px));
      margin: 0 auto;
      padding: 42px 0 56px;
    }}
    header {{
      display: grid;
      grid-template-columns: 1fr minmax(260px, 360px);
      gap: 24px;
      align-items: end;
      padding-bottom: 24px;
      border-bottom: 1px solid var(--line);
    }}
    h1 {{
      margin: 0 0 10px;
      font-size: clamp(30px, 5vw, 54px);
      line-height: 1.05;
      letter-spacing: 0;
    }}
    .lede {{
      margin: 0;
      max-width: 720px;
      color: var(--muted);
      font-size: 16px;
    }}
    .tools {{
      display: grid;
      gap: 10px;
    }}
    .filters {{
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
    }}
    .filter-button {{
      min-height: 32px;
      border: 1px solid var(--line);
      border-radius: 999px;
      padding: 4px 12px;
      background: var(--panel);
      color: var(--ink);
      font: inherit;
      font-size: 13px;
      cursor: pointer;
    }}
    .filter-button[aria-pressed="true"] {{
      border-color: var(--accent-dark);
      background: var(--accent-dark);
      color: #fff;
    }}
    label {{
      font-size: 13px;
      color: var(--muted);
    }}
    input {{
      width: 100%;
      border: 1px solid var(--line);
      border-radius: 6px;
      padding: 11px 12px;
      background: var(--panel);
      color: var(--ink);
      font: inherit;
    }}
    .stats {{
      margin: 14px 0 0;
      color: var(--muted);
      font-size: 13px;
    }}
    .list {{
      display: grid;
      gap: 14px;
      margin-top: 24px;
    }}
    .article-card {{
      display: grid;
      gap: 10px;
      padding: 20px;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: var(--panel);
    }}
    .article-card[hidden] {{ display: none; }}
    .meta {{
      display: flex;
      flex-wrap: wrap;
      gap: 8px 14px;
      color: var(--muted);
      font-size: 13px;
    }}
    .source-badge {{
      display: inline-flex;
      align-items: center;
      min-height: 22px;
      border: 1px solid var(--line);
      border-radius: 999px;
      padding: 1px 9px;
      color: var(--ink);
      background: #eef4f1;
      font-weight: 650;
      text-decoration: none;
    }}
    .source-badge:hover {{ border-color: var(--accent-dark); }}
    .source-openai .source-badge {{ background: #eef2ff; }}
    .source-cursor .source-badge {{ background: #f0f0f0; }}
    .source-anthropic .source-badge {{ background: #f7eadf; }}
    h2 {{
      margin: 0;
      font-size: 20px;
      line-height: 1.3;
      letter-spacing: 0;
    }}
    p {{
      margin: 0;
    }}
    .summary {{
      display: grid;
      gap: 6px;
    }}
    .summary-line {{
      display: grid;
      grid-template-columns: 76px 1fr;
      gap: 8px;
      margin: 0;
    }}
    .summary-line strong {{
      color: var(--accent-dark);
      font-weight: 700;
    }}
    .article-actions {{
      display: flex;
      flex-wrap: wrap;
      gap: 10px 16px;
      align-items: center;
    }}
    .source-link {{
      width: fit-content;
      color: var(--accent-dark);
      font-weight: 650;
      text-decoration: none;
      border-bottom: 1px solid currentColor;
    }}
    .summary-link {{
      color: #8a4b10;
    }}
    .source-link:hover {{
      color: var(--accent);
    }}
    .empty {{
      margin-top: 28px;
      color: var(--muted);
    }}
    @media (max-width: 760px) {{
      header {{
        grid-template-columns: 1fr;
        align-items: start;
      }}
      .page {{
        width: min(100% - 24px, 1120px);
        padding-top: 28px;
      }}
      .article-card {{
        padding: 16px;
      }}
      .summary-line {{
        grid-template-columns: 1fr;
        gap: 2px;
      }}
    }}
  </style>
</head>
<body>
  <main class="page">
    <header>
      <div>
        <h1>AI Research 中文简介</h1>
        <p class="lede">每篇文章保留一段中文简介，包含结论、关键数据和阅读价值；点击“阅读原文”可打开对应来源原文。</p>
        <p class="stats"><span id="visible-count">{len(sorted_articles)}</span> / {len(sorted_articles)} 篇文章 · {source_summary} · 更新于 {esc(updated_at)}</p>
      </div>
      <div class="tools">
        <label for="search">搜索来源、标题、分类或简介</label>
        <input id="search" type="search" autocomplete="off" placeholder="输入关键词">
        <div class="filters" aria-label="来源筛选">
          <button type="button" class="filter-button" data-source-filter="all" aria-pressed="true">全部</button>
          {source_buttons}
        </div>
      </div>
    </header>
    <section class="list" id="article-list" aria-label="文章列表">
      {cards}
    </section>
    {empty}
  </main>
  <script>
    const search = document.querySelector("#search");
    const cards = Array.from(document.querySelectorAll(".article-card"));
    const filterButtons = Array.from(document.querySelectorAll(".filter-button"));
    const visibleCount = document.querySelector("#visible-count");
    let activeSource = "all";
    function applyFilters() {{
      const query = search.value.trim().toLowerCase();
      let visible = 0;
      for (const card of cards) {{
        const sourceMatch = activeSource === "all" || card.dataset.source === activeSource;
        const textMatch = !query || card.dataset.search.includes(query);
        const match = sourceMatch && textMatch;
        card.hidden = !match;
        if (match) visible += 1;
      }}
      visibleCount.textContent = visible;
    }}
    search?.addEventListener("input", applyFilters);
    for (const button of filterButtons) {{
      button.addEventListener("click", () => {{
        activeSource = button.dataset.sourceFilter || "all";
        for (const item of filterButtons) {{
          item.setAttribute("aria-pressed", String(item === button));
        }}
        applyFilters();
      }});
    }}
  </script>
</body>
</html>
"""


def main() -> int:
    parser = argparse.ArgumentParser(description="Render the Economic Futures summary site.")
    parser.add_argument("--state", type=Path, default=default_site_dir() / "articles.json")
    parser.add_argument("--output", type=Path, default=default_site_dir() / "index.html")
    args = parser.parse_args()

    articles = load_articles(args.state)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(render_page(articles, args.output.parent), encoding="utf-8")
    print(f"Rendered {len(articles)} articles to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
