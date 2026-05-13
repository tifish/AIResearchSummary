"""Extract metadata and readable text from one configured source article."""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from html.parser import HTMLParser
from typing import Any


DATE_RE = re.compile(
    r"\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{1,2},\s+\d{4}\b"
)
OPENAI_RSS_URL = "https://openai.com/news/rss.xml"
OPENAI_RESEARCH_CATEGORIES = {"Product", "Safety", "Publication", "Research"}


def clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(value)).strip()


def normalize_url(value: str) -> str:
    parsed = urllib.parse.urlsplit(value)
    path = parsed.path.rstrip("/") or "/"
    return urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, path, "", ""))


def fetch_text(url: str) -> str:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 ai-research-summary/1.0",
            "Accept": "text/html,application/xhtml+xml,application/rss+xml,application/xml",
        },
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        charset = response.headers.get_content_charset() or "utf-8"
        return response.read().decode(charset, errors="replace")


class ArticleParser(HTMLParser):
    content_tags = {"h1", "h2", "h3", "h4", "p", "li", "blockquote"}
    skip_tags = {"script", "style", "svg", "noscript"}

    def __init__(self, url: str) -> None:
        super().__init__(convert_charrefs=True)
        self.url = normalize_url(url)
        self.meta: dict[str, str] = {}
        self.title = ""
        self.date = ""
        self.category = ""
        self.blocks: list[str] = []

        self.in_article = False
        self.article_depth = 0
        self.skip_depth = 0
        self.current_tag: str | None = None
        self.buffer: list[str] = []
        self.pre_title_texts: list[str] = []
        self.seen_title = False
        self.stop_collecting = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr = {name: value or "" for name, value in attrs}

        if tag == "meta":
            key = attr.get("property") or attr.get("name")
            content = clean_text(attr.get("content", ""))
            if key and content:
                self.meta[key] = content
            return

        if tag in self.skip_tags:
            self.skip_depth += 1
            return

        if self.skip_depth:
            return

        if tag == "article" and not self.in_article:
            self.in_article = True
            self.article_depth = 1
            return

        if not self.in_article:
            return

        self.article_depth += 1
        if tag in self.content_tags or tag == "time":
            self.current_tag = tag
            self.buffer = []

    def handle_data(self, data: str) -> None:
        if self.skip_depth or not self.in_article:
            return

        text = clean_text(data)
        if not text:
            return

        if not self.date:
            match = DATE_RE.search(text)
            if match:
                self.date = clean_text(match.group(0))

        if self.current_tag:
            self.buffer.append(data)
        elif not self.seen_title:
            self.pre_title_texts.append(text)

    def handle_endtag(self, tag: str) -> None:
        if self.skip_depth:
            if tag in self.skip_tags:
                self.skip_depth -= 1
            return

        if not self.in_article:
            return

        if self.current_tag == tag:
            self._finish_block(tag)

        self.article_depth -= 1
        if self.article_depth <= 0:
            self.in_article = False

    def _finish_block(self, tag: str) -> None:
        text = clean_text(" ".join(self.buffer))
        self.current_tag = None
        self.buffer = []
        if not text:
            return

        if not self.date:
            match = DATE_RE.search(text)
            if match:
                self.date = clean_text(match.group(0))

        if tag == "time":
            self.date = text
            return

        if tag == "h1" and not self.title:
            self.title = text
            self.seen_title = True
            return

        if text.lower() in {"related content", "more from anthropic"}:
            self.stop_collecting = True
            return

        if not self.stop_collecting and self.seen_title:
            if not self.blocks or self.blocks[-1] != text:
                self.blocks.append(text)

    def result(self) -> dict[str, Any]:
        if not self.title:
            self.title = self.meta.get("og:title", "").replace(" \\ Anthropic", "").strip()

        if not self.date:
            published = self.meta.get("article:published_time", "")
            if published:
                self.date = published

        if not self.category:
            ignored = {self.title, self.date, "Anthropic"}
            for item in self.pre_title_texts:
                if item not in ignored and not DATE_RE.search(item) and 2 <= len(item) <= 80:
                    self.category = item
                    break
        if not self.category:
            self.category = "Economic Research"

        article_text = "\n\n".join(self.blocks).strip()
        source_hash = hashlib.sha256(article_text.encode("utf-8")).hexdigest()
        return {
            **source_for_url(self.url),
            "url": self.url,
            "title": self.title,
            "date": self.date,
            "category": self.category,
            "source_hash": source_hash,
            "article_text": article_text,
        }


def source_for_url(url: str) -> dict[str, str]:
    host = urllib.parse.urlsplit(url).netloc.lower()
    if "openai.com" in host:
        return {"source": "openai", "source_name": "OpenAI"}
    if "cursor.com" in host:
        return {"source": "cursor", "source_name": "Cursor"}
    if "anthropic.com" in host:
        return {"source": "anthropic", "source_name": "Anthropic"}
    return {"source": "unknown", "source_name": "Unknown"}


def openai_rss_fallback(url: str) -> dict[str, Any] | None:
    target = normalize_url(url)
    root = ET.fromstring(fetch_text(OPENAI_RSS_URL))
    for item in root.findall("./channel/item"):
        link = normalize_url(clean_text(item.findtext("link", "")))
        category = clean_text(item.findtext("category", ""))
        if link != target or category not in OPENAI_RESEARCH_CATEGORIES:
            continue
        description = clean_text(item.findtext("description", ""))
        title = clean_text(item.findtext("title", ""))
        pub_date = clean_text(item.findtext("pubDate", ""))
        source_hash = hashlib.sha256(description.encode("utf-8")).hexdigest()
        return {
            **source_for_url(target),
            "url": target,
            "title": title,
            "date": parse_rss_date(pub_date),
            "category": category,
            "source_hash": source_hash,
            "article_text": description,
        }
    return None


def parse_rss_date(value: str) -> str:
    if not value:
        return ""
    import email.utils

    parsed = email.utils.parsedate_to_datetime(value)
    return parsed.strftime("%b %#d, %Y") if sys.platform == "win32" else parsed.strftime("%b %-d, %Y")


def extract(url: str) -> dict[str, Any]:
    if "openai.com/" in url:
        fallback = openai_rss_fallback(url)
        if fallback:
            return fallback

    parser = ArticleParser(url)
    parser.feed(fetch_text(url))
    result = parser.result()
    if result["source"] == "cursor" and result["category"] == "Blog":
        result["category"] = "Research"
    return result


def main() -> int:
    arg_parser = argparse.ArgumentParser(description="Extract one Anthropic article page.")
    arg_parser.add_argument("url", help="Anthropic article URL.")
    args = arg_parser.parse_args()

    try:
        payload = extract(args.url)
    except (OSError, urllib.error.URLError) as exc:
        print(f"extract_article.py: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
