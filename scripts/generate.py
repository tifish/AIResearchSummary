"""Generate an article's Chinese title, summary, digest, and translation in ONE agent call.

The agent returns all parts in a single response with explicit markers, so the
article body and the agent overhead are paid once.
"""

from __future__ import annotations

import json
import re
import sys
from datetime import datetime
from pathlib import Path

from agent_cli import extract_html, load_prompt, run_agent
from extract_article import ensure_bs4, normalize_url
from render_site import load_articles, prepare_digest_html


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

TITLE_ZH_MARK = "===TITLE_ZH==="
SUMMARY_MARK = "===SUMMARY==="
VALUE_MARK = "===VALUE==="
DIGEST_MARK = "===DIGEST==="
TRANSLATION_SECTION_RE = re.compile(r"<section\b[^>]*\bid\s*=\s*(['\"])translation\1", re.IGNORECASE)
TRANSLATION_HEADING_MARK = "完整译文"


def build_prompt(meta: dict) -> str:
    images = meta.get("article_images", [])
    image_context = (
        "\n\n原文图片（index 是固定编号，after_block 表示图片前已有多少个正文内容块）：\n"
        + json.dumps(images, ensure_ascii=False, indent=2)
        if images
        else "\n\n原文图片：无\n"
    )
    return (
        f"{load_prompt('article.md')}\n\n## 文章\n"
        f"标题：{meta['title']}\n"
        f"来源：{meta['source_name']}\n"
        f"日期：{meta['date']}\n"
        f"分类：{meta['category']}\n"
        f"URL：{meta['url']}\n\n"
        f"正文：\n{meta['article_text']}"
        f"{image_context}\n"
    )


def inject_original_images(html_text: str, images: list[dict]) -> str:
    """Replace model-positioned image markers with exact source image elements."""
    if not images:
        return html_text

    BeautifulSoup = ensure_bs4()
    soup = BeautifulSoup(html_text, "html.parser")
    expected_indexes = {str(image["index"]) for image in images}
    expected_order = [str(image["index"]) for image in images]
    markers = soup.find_all(attrs={"data-source-image": True})
    actual_indexes = [str(marker.get("data-source-image", "")) for marker in markers]
    if len(actual_indexes) != len(expected_indexes) or set(actual_indexes) != expected_indexes:
        raise ValueError("agent did not position every original article image exactly once")
    if actual_indexes != expected_order:
        raise ValueError("agent did not preserve the original article image order")

    translation = soup.find("section", id="translation")
    for image in images:
        index = str(image["index"])
        matched = soup.find_all(attrs={"data-source-image": index})
        if len(matched) != 1 or matched[0].name != "figure":
            raise ValueError(f"agent returned an invalid marker for original article image {index}")
        figure = matched[0]
        if translation is None or translation not in figure.parents:
            raise ValueError(f"agent placed original article image {index} outside the translation section")
        caption = figure.find("figcaption", recursive=False)
        if image.get("caption") and (caption is None or not caption.get_text(" ", strip=True)):
            raise ValueError(f"agent did not translate the caption for original article image {index}")
        for existing_image in figure.find_all("img"):
            existing_image.decompose()

        def image_attrs(src: str, extra_classes: list[str] | None = None) -> dict[str, str]:
            attrs = {
                "src": src,
                "alt": str(image.get("alt", "")),
                "loading": "lazy",
                "decoding": "async",
            }
            if extra_classes:
                attrs["class"] = " ".join(extra_classes)
            if image.get("width"):
                attrs["width"] = str(image["width"])
            if image.get("height"):
                attrs["height"] = str(image["height"])
            return attrs

        theme_sources = image.get("theme_sources", {})
        if set(theme_sources) == {"light", "dark"}:
            light_image = soup.new_tag(
                "img",
                attrs=image_attrs(str(theme_sources["light"]), ["source-image", "source-image-light"]),
            )
            dark_image = soup.new_tag(
                "img",
                attrs=image_attrs(str(theme_sources["dark"]), ["source-image", "source-image-dark"]),
            )
            figure.insert(0, light_image)
            figure.insert(1, dark_image)
        else:
            source_image = soup.new_tag("img", attrs=image_attrs(str(image["src"])))
            figure.insert(0, source_image)
        classes = list(figure.get("class", []))
        if "source-figure" not in classes:
            classes.append("source-figure")
        figure["class"] = classes
    all_images = soup.find_all("img")
    expected_image_count = sum(
        2 if set(image.get("theme_sources", {})) == {"light", "dark"} else 1
        for image in images
    )
    if len(all_images) != expected_image_count:
        raise ValueError("agent added images that were not present in the original article")
    if any(translation not in image.parents for image in all_images):
        raise ValueError("agent placed an image outside the translation section")
    return str(soup)


def generate(meta: dict, agent: str) -> dict:
    """One agent call -> {title_zh, summary_zh, value_zh, html}.

    Output is marker-delimited plain text (not JSON), so the model can write
    Chinese with arbitrary quotes/punctuation without breaking a JSON parse.
    """
    output = run_agent(build_prompt(meta), agent)
    if SUMMARY_MARK not in output or VALUE_MARK not in output or DIGEST_MARK not in output:
        raise ValueError("agent output is missing a ===SUMMARY===/===VALUE===/===DIGEST=== marker")
    before_summary, after_summary = output.split(SUMMARY_MARK, 1)
    title_zh = ""
    if TITLE_ZH_MARK in before_summary:
        title_zh = before_summary.split(TITLE_ZH_MARK, 1)[1].strip()
    summary_zh, after_value = after_summary.split(VALUE_MARK, 1)
    value_zh, digest_part = after_value.split(DIGEST_MARK, 1)
    summary_zh = summary_zh.strip()
    value_zh = value_zh.strip()
    if not summary_zh:
        raise ValueError("agent did not return summary text")
    html = extract_html(digest_part)
    if "<html" not in html.lower():
        raise ValueError("agent did not return an HTML digest")
    if not TRANSLATION_SECTION_RE.search(html) or TRANSLATION_HEADING_MARK not in html:
        raise ValueError("agent did not return the required complete translation section")
    html = inject_original_images(html, list(meta.get("article_images", [])))
    html = prepare_digest_html(html, meta["url"])
    return {"title_zh": title_zh, "summary_zh": summary_zh, "value_zh": value_zh, "html": html}


def upsert_summary(state_path: Path, meta: dict, summary_zh: str, value_zh: str, title_zh: str = "") -> None:
    records = load_articles(state_path) if state_path.exists() else []
    url = normalize_url(meta["url"])
    resolved_title_zh = str(title_zh or meta.get("title_zh", "")).strip()
    for record in records:
        if normalize_url(str(record.get("url", ""))) == url:
            record["summary_zh"] = summary_zh
            record["value_zh"] = value_zh
            if resolved_title_zh:
                record["title_zh"] = resolved_title_zh
            if meta.get("source_hash"):
                record["source_hash"] = meta["source_hash"]
            break
    else:
        records.append({
            "source": meta["source"],
            "source_name": meta["source_name"],
            "url": url,
            "title": meta["title"],
            "title_zh": resolved_title_zh,
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
