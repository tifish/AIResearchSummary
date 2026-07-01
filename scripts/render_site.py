"""Render the AI research Chinese summary site."""

from __future__ import annotations

import argparse
import html
import json
import re
import urllib.parse
from datetime import datetime
from pathlib import Path
from typing import Any


SOURCE_HOME_URLS = {
    "anthropic": "https://www.anthropic.com/research",
    "openai": "https://openai.com/research/index/",
    "cursor": "https://cursor.com/blog/topic/research",
}


def workspace_root() -> Path:
    return Path(__file__).resolve().parents[1]


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
    value = re.sub(r"\bSept\b", "Sep", value.strip())
    for fmt in ("%b %d, %Y", "%B %d, %Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    return datetime.min


def year_key(record: dict[str, Any]) -> str:
    parsed = parse_date(str(record.get("date", "")))
    return "unknown" if parsed == datetime.min else parsed.strftime("%Y")


def month_num(record: dict[str, Any]) -> str:
    parsed = parse_date(str(record.get("date", "")))
    return "unknown" if parsed == datetime.min else parsed.strftime("%m")


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


DIGEST_THEME_HEAD = """  <script id="airs-digest-theme-boot">
    try {
      var saved = localStorage.getItem("theme");
      if (saved && saved !== "auto") document.documentElement.dataset.theme = saved;
    } catch (e) {}
  </script>
  <style id="airs-digest-theme-style">
    :root {
      color-scheme: light;
      --airs-digest-ink: #191816;
      --airs-digest-muted: #6f6a62;
      --airs-digest-line: #d9d1c4;
      --airs-digest-paper: #f7f4ed;
      --airs-digest-panel: #fffdf8;
      --airs-digest-accent: #1f6f5b;
      --airs-digest-accent-strong: #164d40;
      --airs-digest-highlight: #eef4f1;
      --bg: var(--airs-digest-paper);
      --card: var(--airs-digest-panel);
      --ink: var(--airs-digest-ink);
      --muted: var(--airs-digest-muted);
      --line: var(--airs-digest-line);
      --accent: var(--airs-digest-accent);
      --accent2: var(--airs-digest-accent-strong);
      --accent3: #6f589e;
      --hl: #fff4e6;
      --hl2: #eaf3f0;
      --warn: #9b5a00;
      --danger: #a43d45;
    }
    @media (prefers-color-scheme: dark) {
      :root:not([data-theme="light"]) {
        color-scheme: dark;
        --airs-digest-ink: #ece7dc;
        --airs-digest-muted: #aaa194;
        --airs-digest-line: #38332b;
        --airs-digest-paper: #15130f;
        --airs-digest-panel: #211d17;
        --airs-digest-accent: #5cc3a6;
        --airs-digest-accent-strong: #8fd8c0;
        --airs-digest-highlight: #20302b;
        --accent3: #c2abf2;
        --hl: #33291d;
        --hl2: #20302b;
        --warn: #e0a063;
        --danger: #ff9ba4;
      }
    }
    :root[data-theme="dark"] {
      color-scheme: dark;
      --airs-digest-ink: #ece7dc;
      --airs-digest-muted: #aaa194;
      --airs-digest-line: #38332b;
      --airs-digest-paper: #15130f;
      --airs-digest-panel: #211d17;
      --airs-digest-accent: #5cc3a6;
      --airs-digest-accent-strong: #8fd8c0;
      --airs-digest-highlight: #20302b;
      --accent3: #c2abf2;
      --hl: #33291d;
      --hl2: #20302b;
      --warn: #e0a063;
      --danger: #ff9ba4;
    }
    html {
      background: var(--airs-digest-paper);
    }
    body {
      background: var(--airs-digest-paper) !important;
      color: var(--airs-digest-ink) !important;
    }
    body :where(p, li, h1, h2, h3, h4, h5, h6, td, th, blockquote, figcaption) {
      color: inherit;
    }
    body :where(section, article, .wrap, .container, .content, .card, .panel, .lede, .lead, .callout, .insight, .takeaways, .final, .pill, .chip) {
      border-color: var(--airs-digest-line) !important;
    }
    body :where(section, article, .card, .panel, .lede, .lead, .callout, .pill, .chip, .takeaways, .final) {
      background: var(--airs-digest-panel) !important;
      color: var(--airs-digest-ink) !important;
    }
    body :where(.muted, .meta, .kicker, small) {
      color: var(--airs-digest-muted) !important;
    }
    body a {
      color: var(--airs-digest-accent-strong) !important;
    }
    body :where(th) {
      background: var(--airs-digest-highlight) !important;
      color: var(--airs-digest-accent-strong) !important;
    }
    body :where(td, th) {
      border-color: var(--airs-digest-line) !important;
    }
    .airs-digest-nav {
      display: flex;
      gap: 12px 18px;
      flex-wrap: wrap;
      align-items: center;
      justify-content: space-between;
      padding: 10px 16px;
      margin: 0;
      background: var(--airs-digest-panel);
      border-bottom: 1px solid var(--airs-digest-line);
      color: var(--airs-digest-ink);
      font: 14px/1.6 -apple-system, BlinkMacSystemFont, "Segoe UI", "Microsoft YaHei", sans-serif;
    }
    .airs-digest-nav a {
      color: var(--airs-digest-accent-strong);
      font-weight: 650;
      text-decoration: none;
    }
    .airs-digest-nav a:hover {
      color: var(--airs-digest-accent);
    }
    .airs-digest-nav-links {
      display: flex;
      gap: 18px;
      flex-wrap: wrap;
      align-items: center;
    }
    .airs-digest-theme-toggle {
      min-height: 30px;
      border: 1px solid var(--airs-digest-line);
      border-radius: 999px;
      padding: 3px 12px;
      background: var(--airs-digest-panel);
      color: var(--airs-digest-muted);
      font: inherit;
      font-size: 12px;
      cursor: pointer;
    }
    .airs-digest-theme-toggle:hover {
      border-color: var(--airs-digest-accent-strong);
      color: var(--airs-digest-ink);
    }
  </style>"""

DIGEST_THEME_SCRIPT = """  <script id="airs-digest-theme-script">
    (() => {
      const root = document.documentElement;
      const buttons = Array.from(document.querySelectorAll("[data-airs-theme-toggle]"));
      const modes = ["auto", "light", "dark"];
      const labels = { auto: "主题 · 跟随系统", light: "主题 · 浅色", dark: "主题 · 深色" };
      function applyTheme(mode) {
        if (!modes.includes(mode)) mode = "auto";
        if (mode === "auto") root.removeAttribute("data-theme");
        else root.dataset.theme = mode;
        for (const button of buttons) button.textContent = labels[mode];
        return mode;
      }
      let mode = "auto";
      try { mode = localStorage.getItem("theme") || "auto"; } catch (e) {}
      mode = applyTheme(mode);
      for (const button of buttons) {
        button.addEventListener("click", () => {
          mode = modes[(modes.indexOf(mode) + 1) % modes.length];
          try { localStorage.setItem("theme", mode); } catch (e) {}
          mode = applyTheme(mode);
        });
      }
    })();
  </script>"""


def inject_digest_theme(html: str) -> str:
    if "airs-digest-theme-style" not in html:
        head_match = re.search(r"</head\s*>", html, re.IGNORECASE)
        if head_match:
            html = html[: head_match.start()] + DIGEST_THEME_HEAD + "\n" + html[head_match.start() :]
        else:
            html = DIGEST_THEME_HEAD + "\n" + html
    if "airs-digest-theme-script" in html:
        return html
    body_match = re.search(r"</body\s*>", html, re.IGNORECASE)
    if body_match:
        return html[: body_match.start()] + DIGEST_THEME_SCRIPT + "\n" + html[body_match.start() :]
    return html + "\n" + DIGEST_THEME_SCRIPT


def inject_nav(html: str, url: str) -> str:
    """Insert a standard nav bar (back to index + original article) at the top of a
    digest page. Idempotent (marked with the airs-digest-nav class)."""
    if "airs-digest-nav" in html:
        return html
    nav = (
        '<nav class="airs-digest-nav">'
        '<div class="airs-digest-nav-links">'
        '<a href="../index.html">&#8592; 返回索引</a>'
        f'<a href="{esc(url)}" target="_blank" rel="noopener noreferrer">阅读原文 &#8599;</a>'
        "</div>"
        '<button type="button" class="airs-digest-theme-toggle" data-airs-theme-toggle>主题 · 跟随系统</button>'
        "</nav>"
    )
    match = re.search(r"<body[^>]*>", html, re.IGNORECASE)
    if match:
        return html[: match.end()] + "\n" + nav + html[match.end() :]
    return nav + html


def prepare_digest_html(html: str, url: str) -> str:
    return inject_digest_theme(inject_nav(html, url))


def render_summary(summary: str, value: str) -> str:
    if value and "价值：" not in summary:
        combined = f"{summary} 价值：{value}"
    else:
        combined = summary
    labels = ("结论：", "关键数据：", "价值：")
    positions = sorted((combined.find(label), label) for label in labels if combined.find(label) >= 0)
    sections: dict[str, str] = {}
    for index, (start, label) in enumerate(positions):
        end = positions[index + 1][0] if index + 1 < len(positions) else len(combined)
        body = combined[start + len(label) : end].strip()
        if body:
            sections[label] = body

    parts = []
    for label in ("价值：", "结论：", "关键数据："):
        body = sections.get(label)
        if body:
            parts.append(f'<p class="summary-line"><strong>{esc(label[:-1])}</strong><span>{esc(body)}</span></p>')
    if parts:
        return "\n        ".join(parts)
    return f"<p>{esc(combined)}</p>"


def render_article(record: dict[str, Any], site_dir: Path) -> str:
    summary = str(record.get("summary_zh", "")).strip()
    value = str(record.get("value_zh", "")).strip()
    title_zh = str(record.get("title_zh", "")).strip()
    source = str(record.get("source", "") or "unknown").strip().lower()
    source_name = str(record.get("source_name", "") or source or "Unknown").strip()
    source_home_url = SOURCE_HOME_URLS.get(source, str(record.get("url", "")))
    art_year = year_key(record)
    art_month = month_num(record)
    search_text = " ".join(
        str(record.get(key, ""))
        for key in ("source", "source_name", "title", "title_zh", "date", "category", "summary_zh", "value_zh")
    )
    summary_html = render_summary(summary, value)
    title = str(record.get("title", "")).strip()
    if title_zh:
        title_html = f'<h2 lang="zh-CN">{esc(title_zh)}</h2>\n          <p class="title-en" lang="en">{esc(title)}</p>'
    else:
        title_html = f"<h2>{esc(title)}</h2>"
    local_summary_href = summary_href(record, site_dir)
    summary_link = (
        f'<a class="source-link summary-link" href="{esc(local_summary_href)}" target="_blank" rel="noopener noreferrer">阅读总结</a>'
        if local_summary_href
        else ""
    )
    return f"""
      <article class="article-card source-{esc(source)}" data-search="{esc(search_text.lower())}" data-source="{esc(source)}" data-year="{esc(art_year)}" data-month="{esc(art_month)}">
        <div class="meta">
          <a class="source-badge" href="{esc(source_home_url)}" target="_blank" rel="noopener noreferrer">{esc(source_name)}</a>
          <time>{esc(record.get("date"))}</time>
          <span>{esc(record.get("category"))}</span>
        </div>
        <div class="title-block">
          {title_html}
        </div>
        <div class="summary">
        {summary_html}
        </div>
        <div class="article-actions">
          {summary_link}
          <a class="source-link" href="{esc(record.get("url"))}" target="_blank" rel="noopener noreferrer">阅读原文</a>
        </div>
      </article>"""


def _chip(filter_attr: str, value: str, label: str, count: int, pressed: bool) -> str:
    return (
        f'<button type="button" class="chip-button" data-{filter_attr}="{esc(value)}" '
        f'aria-pressed="{str(pressed).lower()}">'
        f'<span>{esc(label)}</span><strong>{count}</strong></button>'
    )


def render_page(articles: list[dict[str, Any]], site_dir: Path | None = None) -> str:
    site_dir = site_dir or default_site_dir()
    sorted_articles = sorted(articles, key=lambda item: parse_date(str(item.get("date", ""))), reverse=True)
    updated_at = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M %Z")
    total = len(sorted_articles)

    year_counts: dict[str, int] = {}
    month_counts: dict[str, int] = {}
    for article in sorted_articles:
        year_counts[year_key(article)] = year_counts.get(year_key(article), 0) + 1
        month_counts[month_num(article)] = month_counts.get(month_num(article), 0) + 1

    year_keys = sorted(year_counts, key=lambda k: (-1 if k == "unknown" else int(k)), reverse=True)
    month_keys = sorted(month_counts, key=lambda k: (-1 if k == "unknown" else int(k)), reverse=True)

    year_buttons = "\n".join(
        [_chip("year-filter", "all", "全部年份", total, True)]
        + [
            _chip("year-filter", key, ("未知" if key == "unknown" else f"{key} 年"), year_counts[key], False)
            for key in year_keys
        ]
    )
    month_buttons = "\n".join(
        [_chip("month-filter", "all", "全部月份", total, True)]
        + [
            _chip("month-filter", key, ("未知" if key == "unknown" else f"{int(key)} 月"), month_counts[key], False)
            for key in month_keys
        ]
    )

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

    cards = "\n".join(render_article(record, site_dir) for record in sorted_articles)
    empty = "" if cards else '<p class="empty">还没有文章。运行 refresh.py 更新后会在这里显示摘要。</p>'

    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>AI Research 中文简介</title>
  <script>
    try {{
      var saved = localStorage.getItem("theme");
      if (saved && saved !== "auto") document.documentElement.dataset.theme = saved;
    }} catch (e) {{}}
  </script>
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
      --emphasis: #164d40;
      --chip-bg: #ece5d9;
      --badge-bg: #eef4f1;
      --badge-anthropic: #f7eadf;
      --badge-openai: #eef2ff;
      --badge-cursor: #e9e7f3;
      --summary-link: #8a4b10;
    }}
    @media (prefers-color-scheme: dark) {{
      :root:not([data-theme="light"]) {{
        color-scheme: dark;
        --ink: #ece7dc;
        --muted: #9c9486;
        --line: #38332b;
        --paper: #15130f;
        --panel: #211d17;
        --accent: #5cc3a6;
        --accent-dark: #2b8e76;
        --emphasis: #8fd8c0;
        --chip-bg: #2e2a22;
        --badge-bg: #20302b;
        --badge-anthropic: #33291d;
        --badge-openai: #20243a;
        --badge-cursor: #2a2740;
        --summary-link: #e0a063;
      }}
    }}
    :root[data-theme="dark"] {{
      color-scheme: dark;
      --ink: #ece7dc;
      --muted: #9c9486;
      --line: #38332b;
      --paper: #15130f;
      --panel: #211d17;
      --accent: #5cc3a6;
      --accent-dark: #2b8e76;
      --emphasis: #8fd8c0;
      --chip-bg: #2e2a22;
      --badge-bg: #20302b;
      --badge-anthropic: #33291d;
      --badge-openai: #20243a;
      --badge-cursor: #2a2740;
      --summary-link: #e0a063;
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
    .theme-toggle {{
      justify-self: end;
      min-height: 30px;
      border: 1px solid var(--line);
      border-radius: 999px;
      padding: 3px 12px;
      background: var(--panel);
      color: var(--muted);
      font: inherit;
      font-size: 12px;
      cursor: pointer;
    }}
    .theme-toggle:hover {{ border-color: var(--accent-dark); color: var(--ink); }}
    .facets {{
      display: grid;
      gap: 8px;
      padding-top: 14px;
      margin-top: 20px;
      border-top: 1px solid var(--line);
    }}
    .chip-nav {{
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      gap: 8px;
    }}
    .nav-label {{
      color: var(--muted);
      font-size: 12px;
      min-width: 30px;
    }}
    .filters {{
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
    }}
    .filter-button,
    .chip-button {{
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
    .chip-button {{
      display: inline-flex;
      align-items: center;
      gap: 8px;
      white-space: nowrap;
    }}
    .chip-button strong {{
      display: inline-flex;
      align-items: center;
      justify-content: center;
      min-width: 22px;
      min-height: 22px;
      border-radius: 999px;
      background: var(--chip-bg);
      color: var(--ink);
      font-size: 12px;
      line-height: 1;
    }}
    .filter-button[aria-pressed="true"],
    .chip-button[aria-pressed="true"] {{
      border-color: var(--accent-dark);
      background: var(--accent-dark);
      color: #fff;
    }}
    .chip-button[aria-pressed="true"] strong {{
      background: rgba(255, 255, 255, 0.2);
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
      background: var(--badge-bg);
      font-weight: 650;
      text-decoration: none;
    }}
    .source-badge:hover {{ border-color: var(--accent-dark); }}
    .source-openai .source-badge {{ background: var(--badge-openai); }}
    .source-anthropic .source-badge {{ background: var(--badge-anthropic); }}
    .source-cursor .source-badge {{ background: var(--badge-cursor); }}
    h2 {{
      margin: 0;
      font-size: 20px;
      line-height: 1.3;
      letter-spacing: 0;
    }}
    .title-block {{
      display: grid;
      gap: 4px;
    }}
    .title-en {{
      margin: 0;
      color: var(--muted);
      font-size: 20px;
      font-weight: 700;
      line-height: 1.3;
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
      color: var(--emphasis);
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
      color: var(--emphasis);
      font-weight: 650;
      text-decoration: none;
      border-bottom: 1px solid currentColor;
    }}
    .summary-link {{
      color: var(--summary-link);
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
        <p class="lede">每篇文章先给阅读价值，再给结论和关键数据；点击“阅读原文”可打开对应来源原文。</p>
        <p class="stats">共 {total} 篇文章 · 可见 <span id="visible-count">{total}</span> 篇 · {source_summary} · 更新于 {esc(updated_at)}</p>
      </div>
      <div class="tools">
        <button type="button" id="theme-toggle" class="theme-toggle">主题 · 跟随系统</button>
        <label for="search">搜索来源、标题、分类或简介</label>
        <input id="search" type="search" autocomplete="off" placeholder="输入关键词">
        <div class="filters" aria-label="来源筛选">
          <button type="button" class="filter-button" data-source-filter="all" aria-pressed="true">全部</button>
          {source_buttons}
        </div>
      </div>
    </header>
    <div class="facets">
      <nav class="chip-nav" aria-label="年份筛选">
        <span class="nav-label">年份</span>
        {year_buttons}
      </nav>
      <nav class="chip-nav" aria-label="月份筛选">
        <span class="nav-label">月份</span>
        {month_buttons}
      </nav>
    </div>
    <section class="list" id="article-list" aria-label="文章列表">
      {cards}
    </section>
    {empty}
    <p class="empty" id="empty-state" hidden>当前筛选条件下没有文章。</p>
  </main>
  <script>
    const q = (sel) => document.querySelector(sel);
    const all = (sel) => Array.from(document.querySelectorAll(sel));
    const search = q("#search");
    const cards = all(".article-card");
    const sourceButtons = all(".filter-button");
    const yearButtons = all("[data-year-filter]");
    const monthButtons = all("[data-month-filter]");
    const visibleCount = q("#visible-count");
    const emptyState = q("#empty-state");
    let activeSource = "all";
    let activeYear = "all";
    let activeMonth = "all";

    function applyFilters() {{
      const query = search.value.trim().toLowerCase();
      let visible = 0;
      for (const card of cards) {{
        const yearMatch = activeYear === "all" || card.dataset.year === activeYear;
        const monthMatch = activeMonth === "all" || card.dataset.month === activeMonth;
        const sourceMatch = activeSource === "all" || card.dataset.source === activeSource;
        const textMatch = !query || card.dataset.search.includes(query);
        const match = yearMatch && monthMatch && sourceMatch && textMatch;
        card.hidden = !match;
        if (match) visible += 1;
      }}
      visibleCount.textContent = visible;
      if (emptyState) emptyState.hidden = visible !== 0 || cards.length === 0;
    }}

    function wire(buttons, setActive) {{
      for (const button of buttons) {{
        button.addEventListener("click", () => {{
          setActive(button);
          for (const item of buttons) item.setAttribute("aria-pressed", String(item === button));
          applyFilters();
        }});
      }}
    }}
    wire(sourceButtons, (b) => {{ activeSource = b.dataset.sourceFilter || "all"; }});
    wire(yearButtons, (b) => {{ activeYear = b.dataset.yearFilter || "all"; }});
    wire(monthButtons, (b) => {{ activeMonth = b.dataset.monthFilter || "all"; }});
    search?.addEventListener("input", applyFilters);

    const themeToggle = q("#theme-toggle");
    const themeModes = ["auto", "light", "dark"];
    const themeLabels = {{ auto: "主题 · 跟随系统", light: "主题 · 浅色", dark: "主题 · 深色" }};
    function applyTheme(mode) {{
      if (mode === "auto") document.documentElement.removeAttribute("data-theme");
      else document.documentElement.dataset.theme = mode;
      if (themeToggle) themeToggle.textContent = themeLabels[mode];
    }}
    let themeMode = "auto";
    try {{ themeMode = localStorage.getItem("theme") || "auto"; }} catch (e) {{}}
    applyTheme(themeMode);
    themeToggle?.addEventListener("click", () => {{
      themeMode = themeModes[(themeModes.indexOf(themeMode) + 1) % themeModes.length];
      try {{ localStorage.setItem("theme", themeMode); }} catch (e) {{}}
      applyTheme(themeMode);
    }});

    applyFilters();
  </script>
</body>
</html>
"""


def main() -> int:
    parser = argparse.ArgumentParser(description="Render the AI research Chinese summary site.")
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
