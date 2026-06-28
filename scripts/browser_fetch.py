"""Fetch fully-rendered HTML through a local Chrome browser.

Used for sources whose pages are JS-rendered or bot-protected (e.g. OpenAI, which
returns HTTP 403 to plain HTTP clients). Drives the locally installed Google Chrome
via Playwright; a real browser with a persistent profile passes the Cloudflare/bot
checks that block urllib.

Configuration (all optional, via environment variables):
  AIRS_CHROME_CDP       Attach to an already-running Chrome instead of launching one.
                        Start Chrome with `chrome --remote-debugging-port=9222`, then
                        set AIRS_CHROME_CDP=http://localhost:9222. Best Cloudflare bypass.
  AIRS_CHROME_CHANNEL   Chrome channel to launch (default "chrome"; set empty to use
                        Playwright's bundled Chromium).
  AIRS_CHROME_HEADLESS  "1" for headless (default "0" / headed, so human checks render).
  AIRS_CHROME_PROFILE   Persistent user-data dir (default <repo>/.chrome-profile).
                        Keeps Cloudflare clearance cookies between runs.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

DEFAULT_TIMEOUT_MS = 45000
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
    custom = os.environ.get("AIRS_CHROME_PROFILE")
    if custom:
        return custom
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
        target = _find_load_more(page)
        if target is None:
            break
        before = len(page.content())
        try:
            target.scroll_into_view_if_needed(timeout=4000)
            target.click(timeout=4000)
        except Exception:
            break
        clicks += 1
        try:
            page.wait_for_load_state("networkidle", timeout=timeout_ms)
        except Exception:
            pass
        page.wait_for_timeout(700)
        if len(page.content()) <= before:
            break
    return clicks


def _load(page, url: str, wait_selector: str | None, timeout_ms: int,
          load_more: bool = False, max_loads: int = 100, stop_when=None) -> str:
    page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
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
    headless = os.environ.get("AIRS_CHROME_HEADLESS", "0") == "1"
    channel = os.environ.get("AIRS_CHROME_CHANNEL", "chrome") or None
    if max_loads is None:
        try:
            max_loads = int(os.environ.get("AIRS_CHROME_MAX_LOADS", "100"))
        except ValueError:
            max_loads = 100

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
