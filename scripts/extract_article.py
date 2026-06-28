"""Extract metadata and readable text from one configured source article."""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
import ssl
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from html.parser import HTMLParser
from typing import Any


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")


DATE_RE = re.compile(
    r"\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{1,2},\s+\d{4}\b"
)
DEFAULT_CATEGORIES = {
    "anthropic": "Research",
    "openai": "Research",
    "cursor": "Research",
}
BROWSER_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
)
KNOWN_CATEGORY_WORDS = {
    "Alignment",
    "Company",
    "Conclusion",
    "Economic Research",
    "Ideas",
    "Interpretability",
    "Milestone",
    "Policy",
    "Product",
    "Publication",
    "Release",
    "Research",
    "Safety",
    "Science",
    "Security",
    "Societal Impacts",
}


def clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(value)).strip()


def normalize_url(value: str) -> str:
    parsed = urllib.parse.urlsplit(value)
    path = parsed.path.rstrip("/") or "/"
    return urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, path, "", ""))


def normalize_date_text(value: str) -> str:
    value = clean_text(value)
    match = DATE_RE.search(value)
    if match:
        value = match.group(0).replace(".", "")
    value = re.sub(r"\bSept\b", "Sep", value)
    for fmt in ("%b %d, %Y", "%B %d, %Y"):
        try:
            parsed = datetime.strptime(value, fmt)
            return parsed.strftime("%b %#d, %Y") if sys.platform == "win32" else parsed.strftime("%b %-d, %Y")
        except ValueError:
            pass
    iso_match = re.match(r"\d{4}-\d{2}-\d{2}", value)
    if iso_match:
        try:
            parsed = datetime.strptime(iso_match.group(0), "%Y-%m-%d")
            return parsed.strftime("%b %#d, %Y") if sys.platform == "win32" else parsed.strftime("%b %-d, %Y")
        except ValueError:
            pass
    return value


def https_context() -> ssl.SSLContext | None:
    try:
        import certifi
    except ModuleNotFoundError:
        return None
    return ssl.create_default_context(cafile=certifi.where())


def fetch_text(url: str) -> str:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": BROWSER_USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml",
        },
    )
    with urllib.request.urlopen(request, timeout=30, context=https_context()) as response:
        charset = response.headers.get_content_charset() or "utf-8"
        return response.read().decode(charset, errors="replace")


def ensure_bs4() -> Any:
    try:
        from bs4 import BeautifulSoup
    except ModuleNotFoundError as exc:
        raise RuntimeError("Missing dependency: beautifulsoup4. Run `python -m pip install -r requirements.txt`.") from exc
    return BeautifulSoup


class ArticleParser(HTMLParser):
    content_tags = {"h1", "h2", "h3", "h4", "p", "li", "blockquote"}
    skip_tags = {"script", "style", "svg", "noscript"}
    void_tags = {
        "area", "base", "br", "col", "embed", "hr", "img",
        "input", "link", "meta", "param", "source", "track", "wbr",
    }

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

        if tag not in self.void_tags:
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

        if tag in self.void_tags:
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
            self.category = default_category(self.url)

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
    if "anthropic.com" in host:
        return {"source": "anthropic", "source_name": "Anthropic"}
    if "cursor.com" in host or "cursor.sh" in host:
        return {"source": "cursor", "source_name": "Cursor"}
    return {"source": "unknown", "source_name": "Unknown"}


def default_category(url: str) -> str:
    source = source_for_url(url)["source"]
    return DEFAULT_CATEGORIES.get(source, "Research")


def meta_content(soup: Any, *names: str) -> str:
    for name in names:
        node = soup.find("meta", attrs={"property": name}) or soup.find("meta", attrs={"name": name})
        if node and node.get("content"):
            return clean_text(str(node["content"]))
    return ""


def extract_with_bs4(url: str, markup: str) -> dict[str, Any]:
    BeautifulSoup = ensure_bs4()
    soup = BeautifulSoup(markup, "html.parser")
    for node in soup(["script", "style", "svg", "noscript", "form", "button", "nav", "footer", "header"]):
        node.decompose()

    title_node = soup.find("h1")
    title = clean_text(title_node.get_text(" ", strip=True)) if title_node else ""
    if not title:
        title = meta_content(soup, "og:title", "twitter:title")
    title = re.sub(r"\s+[\\|]\s+(?:Anthropic|OpenAI).*$", "", title).strip()

    title_context = ""
    if title_node and title_node.parent:
        title_context = clean_text(title_node.parent.get_text(" ", strip=True))

    date_node = None if DATE_RE.search(title_context) else soup.find("time")
    raw_date = ""
    if date_node:
        time_text = clean_text(date_node.get_text(" ", strip=True))
        if DATE_RE.search(time_text):
            raw_date = time_text
        else:
            raw_date = clean_text(str(date_node.get("datetime") or time_text))
    if not raw_date:
        raw_date = meta_content(soup, "article:published_time", "date", "datePublished")
    date_match = DATE_RE.search(title_context) or DATE_RE.search(raw_date)
    date_text = normalize_date_text(date_match.group(0) if date_match else raw_date)

    category = meta_content(soup, "article:section")
    if not category and title_context:
        before_title = title_context.split(title, 1)[0]
        before_title = DATE_RE.sub(" ", before_title)
        matches = [item for item in KNOWN_CATEGORY_WORDS if re.search(rf"\b{re.escape(item)}\b", before_title)]
        if matches:
            category = sorted(matches, key=lambda item: before_title.rfind(item))[-1]
        else:
            candidates = [item for item in re.split(r"\s{2,}| · | - ", before_title) if 2 <= len(item.strip()) <= 40]
            if candidates:
                category = clean_text(candidates[-1])
    if not category:
        category = default_category(url)

    container = soup.find("article") or soup.find("main") or soup.body
    blocks: list[str] = []
    if container:
        for node in container.find_all(["h2", "h3", "h4", "p", "li", "blockquote"]):
            text = clean_text(node.get_text(" ", strip=True))
            if not text or text in {title, date_text, category}:
                continue
            if text.lower() in {"related content", "more from anthropic", "share", "copy link"}:
                break
            if len(text) < 3:
                continue
            if not blocks or blocks[-1] != text:
                blocks.append(text)

    article_text = "\n\n".join(blocks).strip()
    source_hash = hashlib.sha256(article_text.encode("utf-8")).hexdigest()
    return {
        **source_for_url(url),
        "url": normalize_url(url),
        "title": title,
        "date": date_text,
        "category": category,
        "source_hash": source_hash,
        "article_text": article_text,
    }


def extract_from_markup(url: str, markup: str) -> dict[str, Any]:
    parser = ArticleParser(url)
    parser.feed(markup)
    parsed = parser.result()
    fallback = extract_with_bs4(url, markup)
    if parsed["article_text"] and parsed["title"]:
        if fallback["date"]:
            parsed["date"] = fallback["date"]
        if fallback["category"]:
            parsed["category"] = fallback["category"]
        return parsed
    if parsed["title"] and not fallback["title"]:
        fallback["title"] = parsed["title"]
    if parsed["date"] and not fallback["date"]:
        fallback["date"] = parsed["date"]
    if parsed["category"] and fallback["category"] == default_category(url):
        fallback["category"] = parsed["category"]
    return fallback


def extract(url: str) -> dict[str, Any]:
    errors: list[str] = []
    try:
        result = extract_from_markup(url, fetch_text(url))
        if result["article_text"]:
            return result
        errors.append("static page did not expose readable article text")
    except (OSError, urllib.error.URLError) as exc:
        errors.append(str(exc))

    # Static fetch failed or yielded no text: fall back to a local Chrome render
    # (handles JS-rendered / bot-protected pages such as OpenAI's 403-guarded site).
    try:
        from browser_fetch import fetch_rendered

        result = extract_from_markup(url, fetch_rendered(url))
        if result["article_text"]:
            return result
        errors.append("rendered page did not expose readable article text")
    except RuntimeError as exc:
        errors.append(str(exc))
    except Exception as exc:  # browser launch / navigation failure
        errors.append(f"browser render failed: {exc}")

    reason = "; ".join(errors) if errors else "static page did not expose readable article text"
    raise ValueError(f"Could not extract article text from {url}: {reason}.")


def main() -> int:
    arg_parser = argparse.ArgumentParser(description="Extract one configured source article page.")
    arg_parser.add_argument("url", help="Anthropic or OpenAI article URL.")
    args = arg_parser.parse_args()

    try:
        payload = extract(args.url)
    except (RuntimeError, ValueError, OSError, urllib.error.URLError) as exc:
        print(f"extract_article.py: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
