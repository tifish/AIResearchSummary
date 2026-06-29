"""Fetch fully-rendered HTML through a local Chrome browser.

Used for sources whose pages are JS-rendered or bot-protected (e.g. OpenAI, which
returns HTTP 403 to plain HTTP clients). Drives the locally installed Google Chrome
via Playwright; a real browser with a persistent profile passes the Cloudflare/bot
checks that block urllib.

Always runs headed (so Cloudflare / human checks can render) and reuses a fixed
persistent profile (<repo>/.chrome-profile) so clearance cookies survive between runs.
"Load more" pagination stops by article DATE (a caller-supplied stop_when), not a
click count.

Optional environment variables:
  AIRS_CHROME_CDP       Attach to an already-running Chrome instead of launching one.
                        Start Chrome with `chrome --remote-debugging-port=9222`, then
                        set AIRS_CHROME_CDP=http://localhost:9222. Best Cloudflare bypass.
  AIRS_CHROME_CHANNEL   Chrome channel to launch (default "chrome"; set empty to use
                        Playwright's bundled Chromium).
"""

from __future__ import annotations

import argparse
import os
import re
import sys
import time
from pathlib import Path


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

DEFAULT_TIMEOUT_MS = 45000
SAFETY_MAX_LOADS = 100  # backstop only; the real stop is the date-based stop_when
LOAD_MORE_POLL_MS = 150
LOAD_MORE_SETTLE_MS = 500
LOAD_MORE_MAX_WAIT_MS = 8000
LOAD_MORE_MIN_GROWTH = 500
LOAD_MORE_RE = re.compile(r"load\s*more|show\s*more|see\s*more|view\s*more|加载更多|查看更多|显示更多|更多", re.I)


def _ensure_playwright():
    try:
        from playwright.sync_api import sync_playwright
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "Missing dependency: playwright. Run `python -m pip install -r requirements.txt`. "
            "Local Chrome is used to render OpenAI pages."
        ) from exc
    return sync_playwright


def _profile_dir() -> str:
    return str(Path(__file__).resolve().parents[1] / ".chrome-profile")


def _find_load_more(page):
    for getter in (
        lambda: page.get_by_role("button", name=LOAD_MORE_RE),
        lambda: page.get_by_role("link", name=LOAD_MORE_RE),
        lambda: page.locator("button, a, [role=button]").filter(has_text=LOAD_MORE_RE),
    ):
        try:
            loc = getter()
            if loc.count() > 0 and loc.first.is_visible():
                return loc.first
        except Exception:
            continue
    return None


def _count_links(page) -> int:
    try:
        return page.locator("a[href]").count()
    except Exception:
        return 0


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
    if not load_more:
        try:
            page.wait_for_load_state("networkidle", timeout=timeout_ms)
        except Exception:
            pass
    if wait_selector:
        try:
            page.wait_for_selector(wait_selector, timeout=timeout_ms)
        except Exception:
            pass
    if load_more:
        _click_load_more(page, max_loads, timeout_ms, stop_when)
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
    """Return the fully-rendered HTML of url using a local Chrome browser.

    When load_more is True, repeatedly click a 'Load more' control so paginated
    listings (e.g. OpenAI) expose more than the first page. stop_when(html) -> bool,
    if given, is the intended stop condition (e.g. articles reached the date cutoff);
    max_loads is only a safety cap.
    """
    sync_playwright = _ensure_playwright()
    cdp = os.environ.get("AIRS_CHROME_CDP")
    headless = False  # always headed so Cloudflare / human checks can render
    channel = os.environ.get("AIRS_CHROME_CHANNEL", "chrome") or None
    if max_loads is None:
        max_loads = SAFETY_MAX_LOADS

    with sync_playwright() as playwright:
        if cdp:
            browser = playwright.chromium.connect_over_cdp(cdp)
            context = browser.contexts[0] if browser.contexts else browser.new_context()
            page = context.new_page()
            try:
                return _load(page, url, wait_selector, timeout_ms, load_more, max_loads, stop_when)
            finally:
                page.close()
                browser.close()

        launch_kwargs: dict = {
            "headless": headless,
            "args": ["--disable-blink-features=AutomationControlled"],
        }
        if channel:
            launch_kwargs["channel"] = channel
        context = playwright.chromium.launch_persistent_context(_profile_dir(), **launch_kwargs)
        page = context.new_page()
        try:
            return _load(page, url, wait_selector, timeout_ms, load_more, max_loads, stop_when)
        finally:
            context.close()


def main() -> int:
    arg_parser = argparse.ArgumentParser(description="Print fully-rendered HTML of a URL via local Chrome.")
    arg_parser.add_argument("url")
    arg_parser.add_argument("--wait-selector", default=None, help="Optional CSS selector to wait for.")
    arg_parser.add_argument("--load-more", action="store_true", help="Click 'Load more' until exhausted.")
    arg_parser.add_argument("--max-loads", type=int, default=None, help="Max 'Load more' clicks (default 25).")
    args = arg_parser.parse_args()

    try:
        print(fetch_rendered(args.url, wait_selector=args.wait_selector, load_more=args.load_more, max_loads=args.max_loads))
    except Exception as exc:
        print(f"browser_fetch.py: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
