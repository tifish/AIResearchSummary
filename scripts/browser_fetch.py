"""Render pages through Browser MCP's connected, logged-in daily browser.

Only this fetch's background tab is operated on or closed. No browser launch,
profile, debug port, global MCP configuration, or shared daemon shutdown.
"""
from __future__ import annotations

import argparse
import sys
import time

from browser_mcp import BrowserPage, close_browser_session

DEFAULT_TIMEOUT_MS = 45000
CONTENT_READY_MAX_WAIT_MS = 8000
CONTENT_READY_POLL_MS = 150
CONTENT_READY_STABLE_MS = 500
CONTENT_READY_MIN_ARTICLE_TEXT = 300
CONTENT_READY_MIN_HEADING_TEXT = 120
SAFETY_MAX_LOADS = 100  # backstop only; the real stop is the date-based stop_when
LOAD_MORE_POLL_MS = 150
LOAD_MORE_SETTLE_MS = 500
LOAD_MORE_MAX_WAIT_MS = 8000
LOAD_MORE_MIN_GROWTH = 500

def _find_load_more(page):
    return page.find_load_more()


def _count_links(page) -> int:
    return page.evaluate('() => document.querySelectorAll("a[href]").length')


def _content_snapshot(page) -> dict:
    return page.evaluate(
        """() => {
            const root = document.querySelector("article, main") || document.body;
            const text = root ? (root.innerText || "").trim() : "";
            return {
                textLength: text.length,
                hasArticle: Boolean(document.querySelector("article, main")),
                hasHeading: Boolean(document.querySelector("h1"))
            };
        }"""
    )


def _wait_for_content_ready(page, timeout_ms: int) -> None:
    wait_ms = min(timeout_ms, CONTENT_READY_MAX_WAIT_MS)
    deadline = time.monotonic() + wait_ms / 1000
    last_len = -1
    stable_since = time.monotonic()

    while time.monotonic() < deadline:
        try:
            snapshot = _content_snapshot(page)
        except Exception:
            page.wait_for_timeout(CONTENT_READY_POLL_MS)
            continue

        text_len = int(snapshot.get("textLength") or 0)
        has_article = bool(snapshot.get("hasArticle"))
        has_heading = bool(snapshot.get("hasHeading"))
        ready = (
            (has_article and text_len >= CONTENT_READY_MIN_ARTICLE_TEXT)
            or (has_heading and text_len >= CONTENT_READY_MIN_HEADING_TEXT)
            or text_len >= 1000
        )
        if text_len != last_len:
            last_len = text_len
            stable_since = time.monotonic()
        elif ready:
            if (time.monotonic() - stable_since) * 1000 >= CONTENT_READY_STABLE_MS:
                return

        page.wait_for_timeout(CONTENT_READY_POLL_MS)


def _wait_for_load_more_target(page, timeout_ms: int):
    deadline = time.monotonic() + min(timeout_ms, LOAD_MORE_MAX_WAIT_MS) / 1000
    while time.monotonic() < deadline:
        target = _find_load_more(page)
        if target is not None:
            return target
        page.wait_for_timeout(LOAD_MORE_POLL_MS)
    return _find_load_more(page)


def _wait_for_load_more_update(page, before_len: int, before_links: int, timeout_ms: int, stop_when=None) -> bool:
    wait_ms = min(timeout_ms, LOAD_MORE_MAX_WAIT_MS)
    deadline = time.monotonic() + wait_ms / 1000
    last_len = before_len
    last_links = before_links
    last_change = time.monotonic()
    saw_new_content = False

    while time.monotonic() < deadline:
        page.wait_for_timeout(LOAD_MORE_POLL_MS)
        markup = page.content()
        current_len = len(markup)
        current_links = _count_links(page)
        now = time.monotonic()

        if stop_when is not None:
            try:
                if stop_when(markup):
                    return True
            except Exception:
                pass

        if current_len != last_len or current_links != last_links:
            last_len = current_len
            last_links = current_links
            last_change = now
            if current_links > before_links or current_len - before_len >= LOAD_MORE_MIN_GROWTH:
                saw_new_content = True

        if saw_new_content and (now - last_change) * 1000 >= LOAD_MORE_SETTLE_MS:
            return True

    return _count_links(page) > before_links or len(page.content()) - before_len >= LOAD_MORE_MIN_GROWTH


def _click_load_more(page, max_loads: int, timeout_ms: int, stop_when=None) -> int:
    """Click 'Load more' until the caller's stop_when(html) is true (e.g. the loaded
    articles reach back past the date cutoff), the button is gone, no new content
    loads, or the max_loads safety cap is hit. stop_when (not the cap) is the
    intended stop condition.
    """
    clicks = 0
    for _ in range(max_loads):
        if stop_when is not None:
            try:
                if stop_when(page.content()):
                    break
            except Exception:
                pass
        target = _wait_for_load_more_target(page, timeout_ms) if clicks == 0 else _find_load_more(page)
        if target is None:
            break
        before = len(page.content())
        before_links = _count_links(page)
        try:
            target.scroll_into_view_if_needed(timeout=4000)
            target.click(timeout=4000)
        except Exception:
            break
        clicks += 1
        if not _wait_for_load_more_update(page, before, before_links, timeout_ms, stop_when):
            break
    return clicks


def _load(page, url: str, wait_selector: str | None, timeout_ms: int,
          load_more: bool = False, max_loads: int = 100, stop_when=None) -> str:
    page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
    if wait_selector:
        try:
            page.wait_for_selector(wait_selector, timeout=min(timeout_ms, CONTENT_READY_MAX_WAIT_MS))
        except Exception:
            pass
    if load_more:
        _click_load_more(page, max_loads, timeout_ms, stop_when)
    else:
        _wait_for_content_ready(page, timeout_ms)
    return page.content()


def fetch_rendered(
    url: str,
    *,
    wait_selector: str | None = None,
    timeout_ms: int = DEFAULT_TIMEOUT_MS,
    load_more: bool = False,
    max_loads: int | None = None,
    stop_when=None,
) -> str:
    """Return the fully-rendered HTML of url using a Browser MCP connected browser.

    When load_more is True, repeatedly click a 'Load more' control so paginated
    listings (e.g. OpenAI) expose more than the first page. stop_when(html) -> bool,
    if given, is the intended stop condition (e.g. articles reached the date cutoff);
    max_loads is only a safety cap.
    """
    if max_loads is None:
        max_loads = SAFETY_MAX_LOADS
    with BrowserPage(timeout_ms=timeout_ms) as page:
        return _load(page, url, wait_selector, timeout_ms, load_more, max_loads, stop_when)


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")
    arg_parser = argparse.ArgumentParser(description="Print fully-rendered HTML of a URL via Browser MCP.")
    arg_parser.add_argument("url")
    arg_parser.add_argument("--wait-selector", default=None, help="Optional CSS selector to wait for.")
    arg_parser.add_argument("--load-more", action="store_true", help="Click 'Load more' until exhausted.")
    arg_parser.add_argument("--max-loads", type=int, default=None, help="Max 'Load more' clicks (default 100).")
    args = arg_parser.parse_args()

    try:
        print(fetch_rendered(args.url, wait_selector=args.wait_selector, load_more=args.load_more, max_loads=args.max_loads))
    except Exception as exc:
        print(f"browser_fetch.py: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
