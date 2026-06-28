"""Discover new AI research articles from configured sources."""

from __future__ import annotations

import argparse
import html
import json
import re
import ssl
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime
from pathlib import Path
from typing import Any, Callable


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

SOURCES = {
    "anthropic": {
        "name": "Anthropic",
        "url": "https://www.anthropic.com/research",
    },
    "openai": {
        "name": "OpenAI",
        "url": "https://openai.com/research/index",
        "render": True,
    },
    "cursor": {
        "name": "Cursor",
        "url": "https://cursor.com/blog/topic/research",
    },
}

DEFAULT_SINCE = date(2026, 1, 1)
DATE_RE = re.compile(
    r"\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{1,2},\s+\d{4}\b"
)
OPENAI_CATEGORIES = (
    "Global Affairs",
    "Product",
    "Safety",
    "Publication",
    "Release",
    "Milestone",
    "Conclusion",
    "Research",
)
ANTHROPIC_CATEGORY_PREFIXES = (
    "Economic Research",
    "Societal Impacts",
    "Interpretability",
    "Frontier Red Team",
    "Alignment",
    "Research",
    "Policy",
    "Science",
)
BROWSER_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
)


def workspace_root() -> Path:
    return Path(__file__).resolve().parents[1]


def default_state_path() -> Path:
    return workspace_root() / "site" / "articles.json"


def clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(value)).strip()


def normalize_url(value: str) -> str:
    parsed = urllib.parse.urlsplit(value)
    path = parsed.path.rstrip("/") or "/"
    return urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, path, "", ""))


def source_fields(source_id: str) -> dict[str, str]:
    source = SOURCES[source_id]
    return {"source": source_id, "source_name": str(source["name"])}


def parse_date(value: str) -> date | None:
    value = clean_text(value)
    if not value:
        return None

    match = DATE_RE.search(value)
    if match:
        text = re.sub(r"\bSept\b", "Sep", match.group(0).replace(".", ""))
        for fmt in ("%b %d, %Y", "%B %d, %Y"):
            try:
                return datetime.strptime(text, fmt).date()
            except ValueError:
                pass

    iso_value = value.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(iso_value).date()
    except ValueError:
        return None


def parse_since(value: str) -> date:
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError as exc:
        raise argparse.ArgumentTypeError("--since must be in YYYY-MM-DD format.") from exc


def ensure_dependencies() -> Any:
    try:
        from bs4 import BeautifulSoup
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "Missing dependency: beautifulsoup4. Run `python -m pip install -r requirements.txt`."
        ) from exc

    return BeautifulSoup


def https_context() -> ssl.SSLContext | None:
    try:
        import certifi
    except ModuleNotFoundError:
        return None
    return ssl.create_default_context(cafile=certifi.where())


def fetch_listing_html(source_id: str) -> str:
    source = SOURCES[source_id]
    if source.get("render"):
        from browser_fetch import fetch_rendered

        return fetch_rendered(str(source["url"]))
    request = urllib.request.Request(
        str(source["url"]),
        headers={
            "User-Agent": BROWSER_USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml",
        },
    )
    with urllib.request.urlopen(request, timeout=30, context=https_context()) as response:
        charset = response.headers.get_content_charset() or "utf-8"
        return response.read().decode(charset, errors="replace")


def article_in_range(article: dict[str, str], since: date) -> bool:
    parsed = parse_date(article.get("date", ""))
    return parsed is not None and parsed >= since


def title_from_openai_text(text: str, category: str, date_text: str) -> tuple[str, str]:
    text = clean_text(text)
    if not text:
        return "", ""

    aria_suffix = f" - {category} - {date_text}"
    if category and date_text and text.endswith(aria_suffix):
        return clean_text(text[: -len(aria_suffix)]), ""

    scrubbed = text
    if category:
        scrubbed = re.sub(rf"\b{re.escape(category)}\b", " ", scrubbed, count=1)
    if date_text:
        scrubbed = scrubbed.replace(date_text, " ", 1)
    scrubbed = clean_text(scrubbed)

    separators = (" Explore ", " Introducing ", " OpenAI ", " GPT-", " How ")
    for separator in separators:
        index = scrubbed.find(separator)
        if index > 12:
            return clean_text(scrubbed[:index]), clean_text(scrubbed[index:])
    return scrubbed, ""


def nearest_text_with_date(node: Any) -> str:
    current = node
    for _ in range(7):
        text = clean_text(current.get_text(" ", strip=True))
        if DATE_RE.search(text) and len(text) < 2500:
            return text
        current = current.parent
        if current is None:
            break
    return clean_text(node.get_text(" ", strip=True))


def parse_openai_articles(markup: str) -> list[dict[str, str]]:
    BeautifulSoup = ensure_dependencies()
    soup = BeautifulSoup(markup, "html.parser")
    articles: list[dict[str, str]] = []
    for anchor in soup.find_all("a", href=True):
        href = str(anchor["href"])
        if not href.startswith("/index/") and "openai.com/index/" not in href:
            continue

        text_scope = nearest_text_with_date(anchor)
        date_match = DATE_RE.search(text_scope)
        if not date_match:
            continue
        date_text = date_match.group(0)
        category = next((item for item in OPENAI_CATEGORIES if re.search(rf"\b{re.escape(item)}\b", text_scope)), "")

        title_source = clean_text(str(anchor.get("aria-label") or anchor.get_text(" ", strip=True)))
        title, description = title_from_openai_text(title_source, category, date_text)
        if not title:
            continue

        paragraphs = [clean_text(item.get_text(" ", strip=True)) for item in anchor.find_all("p")]
        for paragraph in paragraphs:
            if paragraph and paragraph != title:
                description = paragraph
                break

        article = {
            **source_fields("openai"),
            "url": normalize_url(urllib.parse.urljoin(str(SOURCES["openai"]["url"]), href)),
            "title": title,
            "date": date_text,
            "category": category or "Research",
        }
        if description:
            article["description"] = description
        articles.append(article)
    return dedupe_articles(articles)


def text_after_date(value: str, date_text: str) -> str:
    return clean_text(value.split(date_text, 1)[-1]) if date_text in value else value


def find_exact_text_root(soup: Any, text: str) -> Any | None:
    node = soup.find(string=lambda value: value is not None and clean_text(str(value)) == text)
    return node.parent if node else None


def anthropic_publications_root(soup: Any) -> Any:
    heading = find_exact_text_root(soup, "Publications")
    if not heading:
        return soup
    section = heading.find_parent("section")
    if section:
        return section
    current = heading.parent
    for _ in range(6):
        if current is None:
            break
        text = clean_text(current.get_text(" ", strip=True))
        if "Date Category Title" in text:
            return current
        current = current.parent
    return heading.parent or soup


def parse_anthropic_title_category(anchor: Any, date_text: str) -> tuple[str, str, str]:
    title_node = (
        anchor.find(class_=re.compile("title", re.I))
        or anchor.find(["h1", "h2", "h3", "h4"])
        or anchor.find("p")
    )
    title = clean_text(title_node.get_text(" ", strip=True)) if title_node else ""

    category_node = anchor.find(class_=re.compile("subject|category|caption", re.I))
    category = clean_text(category_node.get_text(" ", strip=True)) if category_node else ""

    if not title:
        remainder = text_after_date(clean_text(anchor.get_text(" ", strip=True)), date_text)
        for prefix in ANTHROPIC_CATEGORY_PREFIXES:
            if remainder.startswith(prefix):
                category = category or prefix
                title = clean_text(remainder[len(prefix) :])
                break
        if not title:
            title = remainder

    if not category:
        text = clean_text(anchor.get_text(" ", strip=True))
        category = next((prefix for prefix in ANTHROPIC_CATEGORY_PREFIXES if prefix in text), "Research")

    description = ""
    paragraphs = [clean_text(item.get_text(" ", strip=True)) for item in anchor.find_all("p")]
    for paragraph in paragraphs:
        if paragraph and paragraph != title:
            description = paragraph
            break

    return title, category, description


def parse_anthropic_articles(markup: str) -> list[dict[str, str]]:
    BeautifulSoup = ensure_dependencies()
    soup = BeautifulSoup(markup, "html.parser")
    root = anthropic_publications_root(soup)
    articles: list[dict[str, str]] = []
    for anchor in root.find_all("a", href=True):
        href = str(anchor["href"])
        url = normalize_url(urllib.parse.urljoin(str(SOURCES["anthropic"]["url"]), href))
        parsed = urllib.parse.urlsplit(url)
        if parsed.netloc != "www.anthropic.com" or not parsed.path.startswith(("/research/", "/news/", "/features/")):
            continue

        time_node = anchor.find("time")
        date_text = clean_text(time_node.get_text(" ", strip=True)) if time_node else ""
        if not date_text:
            match = DATE_RE.search(clean_text(anchor.get_text(" ", strip=True)))
            date_text = match.group(0) if match else ""
        if not date_text:
            continue

        title, category, description = parse_anthropic_title_category(anchor, date_text)
        if not title or title.lower() == "read more":
            continue

        article = {
            **source_fields("anthropic"),
            "url": url,
            "title": title,
            "date": date_text,
            "category": category or "Research",
        }
        if description:
            article["description"] = description
        articles.append(article)
    return dedupe_articles(articles)


def parse_cursor_articles(markup: str) -> list[dict[str, str]]:
    BeautifulSoup = ensure_dependencies()
    soup = BeautifulSoup(markup, "html.parser")
    articles: list[dict[str, str]] = []
    for anchor in soup.find_all("a", href=True):
        href = str(anchor["href"])
        url = normalize_url(urllib.parse.urljoin(str(SOURCES["cursor"]["url"]), href))
        parsed = urllib.parse.urlsplit(url)
        if parsed.netloc not in ("cursor.com", "www.cursor.com"):
            continue
        if "/topic/" in parsed.path or not re.match(r"^/blog/[^/]+$", parsed.path):
            continue

        time_node = anchor.find("time")
        date_text = clean_text(time_node.get_text(" ", strip=True)) if time_node else ""
        if not DATE_RE.search(date_text):
            match = DATE_RE.search(clean_text(anchor.get_text(" ", strip=True)))
            date_text = match.group(0) if match else ""
        if not date_text:
            continue

        title_node = anchor.find("p") or anchor.find(["h1", "h2", "h3", "h4"])
        title = clean_text(title_node.get_text(" ", strip=True)) if title_node else ""
        if not title:
            continue

        articles.append(
            {
                **source_fields("cursor"),
                "url": url,
                "title": title,
                "date": date_text,
                "category": "Research",
            }
        )
    return dedupe_articles(articles)


PARSERS: dict[str, Callable[[str], list[dict[str, str]]]] = {
    "anthropic": parse_anthropic_articles,
    "openai": parse_openai_articles,
    "cursor": parse_cursor_articles,
}


def dedupe_articles(articles: list[dict[str, str]]) -> list[dict[str, str]]:
    deduped: list[dict[str, str]] = []
    seen: set[str] = set()
    for article in articles:
        url = normalize_url(article["url"])
        if url in seen:
            continue
        seen.add(url)
        article["url"] = url
        deduped.append(article)
    return deduped


def discover_source(source_id: str, since: date) -> list[dict[str, str]]:
    parser = PARSERS[source_id]
    markup = fetch_listing_html(source_id)
    articles = parser(markup)
    return [article for article in articles if article_in_range(article, since)]


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


def discover(source_ids: list[str], since: date) -> tuple[list[dict[str, str]], list[str]]:
    articles: list[dict[str, str]] = []
    errors: list[str] = []
    for source_id in source_ids:
        try:
            articles.extend(discover_source(source_id, since))
        except (RuntimeError, OSError, urllib.error.URLError, ValueError) as exc:
            errors.append(f"{source_id}: {exc}")
    return dedupe_articles(articles), errors


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
        help=f"Comma-separated source ids or 'all'. Available: {', '.join(SOURCES)}.",
    )
    arg_parser.add_argument("--state", type=Path, default=default_state_path(), help="Path to site/articles.json.")
    arg_parser.add_argument("--all", action="store_true", help="Print all discovered articles, not only new ones.")
    arg_parser.add_argument("--since", type=parse_since, default=DEFAULT_SINCE, help="Earliest article date, YYYY-MM-DD.")
    args = arg_parser.parse_args()

    try:
        articles, source_errors = discover(args.sources, args.since)
        existing_urls = read_existing_urls(args.state)
    except (json.JSONDecodeError, ValueError) as exc:
        print(f"discover_articles.py: {exc}", file=sys.stderr)
        return 1

    new_articles = [item for item in articles if normalize_url(item["url"]) not in existing_urls]
    payload = {
        "sources": args.sources,
        "state": str(args.state),
        "since": args.since.isoformat(),
        "discovered_count": len(articles),
        "existing_count": len(existing_urls),
        "new_count": len(new_articles),
        "source_errors": source_errors,
        "articles": articles if args.all else new_articles,
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
