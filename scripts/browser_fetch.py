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
import sys
from pathlib import Path


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

DEFAULT_TIMEOUT_MS = 45000


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


def _load(page, url: str, wait_selector: str | None, timeout_ms: int) -> str:
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
    return page.content()


def fetch_rendered(
    url: str,
    *,
    wait_selector: str | None = None,
    timeout_ms: int = DEFAULT_TIMEOUT_MS,
) -> str:
    """Return the fully-rendered HTML of url using a local Chrome browser."""
    sync_playwright = _ensure_playwright()
    cdp = os.environ.get("AIRS_CHROME_CDP")
    headless = os.environ.get("AIRS_CHROME_HEADLESS", "0") == "1"
    channel = os.environ.get("AIRS_CHROME_CHANNEL", "chrome") or None

    with sync_playwright() as playwright:
        if cdp:
            browser = playwright.chromium.connect_over_cdp(cdp)
            context = browser.contexts[0] if browser.contexts else browser.new_context()
            page = context.new_page()
            try:
                return _load(page, url, wait_selector, timeout_ms)
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
            return _load(page, url, wait_selector, timeout_ms)
        finally:
            context.close()


def main() -> int:
    arg_parser = argparse.ArgumentParser(description="Print fully-rendered HTML of a URL via local Chrome.")
    arg_parser.add_argument("url")
    arg_parser.add_argument("--wait-selector", default=None, help="Optional CSS selector to wait for.")
    args = arg_parser.parse_args()

    try:
        print(fetch_rendered(args.url, wait_selector=args.wait_selector))
    except Exception as exc:
        print(f"browser_fetch.py: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
