"""Discover new AI research articles from configured sources."""

from __future__ import annotations

import argparse
import email.utils
import html
import json
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from html.parser import HTMLParser
from pathlib import Path
from typing import Any


SOURCES = {
    "anthropic": {
        "name": "Anthropic",
        "url": "https://www.anthropic.com/economic-futures",
        "kind": "anthropic",
    },
    "openai": {
        "name": "OpenAI",
        "page_url": "https://openai.com/research/index/",
        "rss_url": "https://openai.com/news/rss.xml",
        "kind": "openai-rss",
    },
    "cursor": {
        "name": "Cursor",
        "url": "https://cursor.com/blog/topic/research",
        "kind": "cursor",
    },
}

OPENAI_RESEARCH_CATEGORIES = {"Product", "Safety", "Publication", "Research"}
OPENAI_INDEX_FALLBACK_URLS = (
    "https://openai.com/index/advancing-voice-intelligence-with-new-models-in-the-api",
    "https://openai.com/index/gpt-5-5-instant-system-card",
    "https://openai.com/index/gpt-5-5-instant",
    "https://openai.com/index/where-the-goblins-came-from",
    "https://openai.com/index/gpt-5-5-system-card",
    "https://openai.com/index/introducing-gpt-5-5",
    "https://openai.com/index/introducing-openai-privacy-filter",
    "https://openai.com/index/introducing-chatgpt-images-2-0",
    "https://openai.com/index/introducing-gpt-rosalind",
)
DATE_RE = re.compile(
    r"\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{1,2},\s+\d{4}\b"
)


def workspace_root() -> Path:
    script_path = Path(__file__).resolve()
    skill_parent = script_path.parents[2]
    if skill_parent.name == "skills" and skill_parent.parent.name == ".agents":
        return script_path.parents[4]
    if skill_parent.name == "skills":
        return script_path.parents[3]
    return skill_parent


def default_state_path() -> Path:
    return workspace_root() / "site" / "articles.json"


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


def source_fields(source_id: str) -> dict[str, str]:
    source = SOURCES[source_id]
    return {"source": source_id, "source_name": str(source["name"])}


class PublicationListParser(HTMLParser):
    def __init__(self, base_url: str, source_id: str) -> None:
        super().__init__(convert_charrefs=True)
        self.base_url = base_url
        self.source_id = source_id
        self.articles: list[dict[str, str]] = []
        self.current: dict[str, Any] | None = None
        self.current_field: str | None = None
        self.field_buffer: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr = {name: value or "" for name, value in attrs}
        cls = attr.get("class", "")

        if tag == "a" and self.current is None:
            href = attr.get("href", "")
            if "PublicationList" in cls and "listItem" in cls and href:
                self.current = {"url": urllib.parse.urljoin(self.base_url, href)}
            return

        if self.current is None:
            return

        if tag == "time":
            self._start_field("date")
        elif tag == "span" and "subject" in cls:
            self._start_field("category")
        elif tag == "span" and "title" in cls:
            self._start_field("title")

    def handle_data(self, data: str) -> None:
        if self.current is not None and self.current_field is not None:
            self.field_buffer.append(data)

    def handle_endtag(self, tag: str) -> None:
        if self.current is None:
            return

        if self.current_field and tag in {"time", "span"}:
            self._finish_field()

        if tag == "a":
            article = {
                **source_fields(self.source_id),
                "url": normalize_url(str(self.current.get("url", ""))),
                "title": clean_text(str(self.current.get("title", ""))),
                "date": clean_text(str(self.current.get("date", ""))),
                "category": clean_text(str(self.current.get("category", ""))),
            }
            if article["url"] and article["title"]:
                self.articles.append(article)
            self.current = None
            self.current_field = None
            self.field_buffer = []

    def _start_field(self, field: str) -> None:
        self.current_field = field
        self.field_buffer = []

    def _finish_field(self) -> None:
        if self.current is not None and self.current_field is not None:
            self.current[self.current_field] = clean_text(" ".join(self.field_buffer))
        self.current_field = None
        self.field_buffer = []


class CursorTopicParser(HTMLParser):
    def __init__(self, base_url: str) -> None:
        super().__init__(convert_charrefs=True)
        self.base_url = base_url
        self.articles: list[dict[str, str]] = []
        self.current_href = ""
        self.current_text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "a":
            return
        attr = {name: value or "" for name, value in attrs}
        href = attr.get("href", "")
        if href.startswith("/blog/") and href != "/blog/":
            self.current_href = href
            self.current_text = []

    def handle_data(self, data: str) -> None:
        if self.current_href:
            self.current_text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag != "a" or not self.current_href:
            return

        text = clean_text(" ".join(self.current_text))
        date_match = DATE_RE.search(text)
        title = title_from_cursor_text(text)
        article = {
            **source_fields("cursor"),
            "url": normalize_url(urllib.parse.urljoin(self.base_url, self.current_href)),
            "title": title,
            "date": date_match.group(0) if date_match else "",
            "category": "Research",
        }
        if article["url"] and article["title"]:
            self.articles.append(article)
        self.current_href = ""
        self.current_text = []


def title_from_cursor_text(text: str) -> str:
    text = DATE_RE.sub("", text, count=1).strip()
    text = re.sub(r"\b\d+m\b.*$", "", text).strip()
    text = re.sub(r"\s+", " ", text)
    if not text:
        return ""
    # The topic page repeats author names after the title. Keep the leading title-like segment.
    by_author = re.split(r"\s{2,}| [A-Z][a-z]+(?:,| &| ·)", text, maxsplit=1)[0].strip()
    return by_author or text


class OpenAIResearchIndexParser(HTMLParser):
    def __init__(self, base_url: str) -> None:
        super().__init__(convert_charrefs=True)
        self.base_url = base_url
        self.articles: list[dict[str, str]] = []
        self.pending_category = ""
        self.pending_date = ""
        self.capture_anchor = False
        self.current_href = ""
        self.current_text: list[str] = []
        self.stop = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if self.stop or tag != "a":
            return
        attr = {name: value or "" for name, value in attrs}
        href = attr.get("href", "")
        if href.startswith("/index/") and self.pending_category and self.pending_date:
            self.capture_anchor = True
            self.current_href = href
            self.current_text = []

    def handle_data(self, data: str) -> None:
        text = clean_text(data)
        if not text or self.stop:
            return
        if text == "Load more":
            self.stop = True
            return
        if self.capture_anchor:
            self.current_text.append(text)
            return
        if text in OPENAI_RESEARCH_CATEGORIES:
            self.pending_category = text
        elif DATE_RE.fullmatch(text):
            self.pending_date = text

    def handle_endtag(self, tag: str) -> None:
        if tag != "a" or not self.capture_anchor:
            return
        text = clean_text(" ".join(self.current_text))
        title, description = split_openai_card_text(text)
        if title:
            self.articles.append(
                {
                    **source_fields("openai"),
                    "url": normalize_url(urllib.parse.urljoin(self.base_url, self.current_href)),
                    "title": title,
                    "date": self.pending_date,
                    "category": self.pending_category,
                    "description": description,
                }
            )
        self.capture_anchor = False
        self.current_href = ""
        self.current_text = []
        self.pending_category = ""
        self.pending_date = ""


def split_openai_card_text(text: str) -> tuple[str, str]:
    if not text:
        return "", ""
    separators = (" Explore ", " Introducing ", " OpenAI ", " GPT-", " How ")
    for separator in separators:
        index = text.find(separator)
        if index > 12:
            title = text[:index].strip()
            description = text[index:].strip()
            return title, description
    return text.strip(), ""


def parse_rss_date(value: str) -> str:
    if not value:
        return ""
    parsed = email.utils.parsedate_to_datetime(value)
    return parsed.strftime("%b %-d, %Y") if sys.platform != "win32" else parsed.strftime("%b %#d, %Y")


def discover_anthropic(source_id: str) -> list[dict[str, str]]:
    source = SOURCES[source_id]
    parser = PublicationListParser(str(source["url"]), source_id)
    parser.feed(fetch_text(str(source["url"])))
    return parser.articles


def discover_openai() -> list[dict[str, str]]:
    try:
        parser = OpenAIResearchIndexParser(str(SOURCES["openai"]["page_url"]))
        parser.feed(fetch_text(str(SOURCES["openai"]["page_url"])))
        if parser.articles:
            return parser.articles
    except (OSError, urllib.error.URLError):
        pass

    return discover_openai_from_rss(OPENAI_INDEX_FALLBACK_URLS)


def discover_openai_from_rss(allowed_urls: tuple[str, ...]) -> list[dict[str, str]]:
    allowed_links = [normalize_url(url) for url in allowed_urls]
    root = ET.fromstring(fetch_text(str(SOURCES["openai"]["rss_url"])))
    by_link: dict[str, dict[str, str]] = {}
    articles: list[dict[str, str]] = []
    for item in root.findall("./channel/item"):
        category = clean_text(item.findtext("category", ""))
        link = normalize_url(clean_text(item.findtext("link", "")))
        if category not in OPENAI_RESEARCH_CATEGORIES:
            continue
        by_link[link] = {
            **source_fields("openai"),
            "url": link,
            "title": clean_text(item.findtext("title", "")),
            "date": parse_rss_date(clean_text(item.findtext("pubDate", ""))),
            "category": category,
            "description": clean_text(item.findtext("description", "")),
        }
    for link in allowed_links:
        if link in by_link:
            articles.append(by_link[link])
    return articles


def discover_cursor() -> list[dict[str, str]]:
    parser = CursorTopicParser(str(SOURCES["cursor"]["url"]))
    parser.feed(fetch_text(str(SOURCES["cursor"]["url"])))
    return parser.articles


def read_existing_urls(state_path: Path) -> set[str]:
    if not state_path.exists():
        return set()
    data = json.loads(state_path.read_text(encoding="utf-8"))
    records = data.get("articles", data) if isinstance(data, dict) else data
    urls: set[str] = set()
    if isinstance(records, list):
        for record in records:
            if isinstance(record, dict) and record.get("url"):
                urls.add(normalize_url(str(record["url"])))
    return urls


def discover(source_ids: list[str]) -> list[dict[str, str]]:
    articles: list[dict[str, str]] = []
    for source_id in source_ids:
        kind = SOURCES[source_id]["kind"]
        if kind == "anthropic":
            articles.extend(discover_anthropic(source_id))
        elif kind == "openai-rss":
            articles.extend(discover_openai())
        elif kind == "cursor":
            articles.extend(discover_cursor())
        else:
            raise ValueError(f"Unknown source kind: {kind}")

    deduped: list[dict[str, str]] = []
    seen: set[str] = set()
    for article in articles:
        url = normalize_url(article["url"])
        if url not in seen:
            seen.add(url)
            article["url"] = url
            deduped.append(article)
    return deduped


def parse_sources(value: str) -> list[str]:
    if value == "all":
        return list(SOURCES)
    source_ids = [item.strip() for item in value.split(",") if item.strip()]
    unknown = [item for item in source_ids if item not in SOURCES]
    if unknown:
        raise argparse.ArgumentTypeError(f"Unknown source(s): {', '.join(unknown)}")
    return source_ids


def main() -> int:
    arg_parser = argparse.ArgumentParser(description="Discover new AI research articles.")
    arg_parser.add_argument(
        "--sources",
        type=parse_sources,
        default=list(SOURCES),
        help="Comma-separated source ids or 'all'. Available: anthropic, openai, cursor.",
    )
    arg_parser.add_argument("--state", type=Path, default=default_state_path(), help="Path to site/articles.json.")
    arg_parser.add_argument("--all", action="store_true", help="Print all discovered articles, not only new ones.")
    args = arg_parser.parse_args()

    try:
        articles = discover(args.sources)
        existing_urls = read_existing_urls(args.state)
    except (OSError, urllib.error.URLError, json.JSONDecodeError, ET.ParseError, ValueError) as exc:
        print(f"discover_articles.py: {exc}", file=sys.stderr)
        return 1

    new_articles = [item for item in articles if normalize_url(item["url"]) not in existing_urls]
    payload = {
        "sources": args.sources,
        "state": str(args.state),
        "discovered_count": len(articles),
        "existing_count": len(existing_urls),
        "new_count": len(new_articles),
        "articles": articles if args.all else new_articles,
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
