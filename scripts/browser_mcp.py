"""Small synchronous adapter for the official MCP SDK and Browser MCP 2.5.0.

The SDK contexts live in one async task, on a worker thread. Each fetch owns a
client and background tab; exiting disconnects stdio, never the shared daemon.
"""
from __future__ import annotations

import asyncio
import atexit
import base64
from concurrent.futures import Future
import json
import queue
import re
import shutil
import threading
import time
import uuid
import warnings

MCP_PACKAGE = "@browsermcp/mcp@2.5.0"
CHUNK_SIZE = 4000
_PAGES = set()
_LOCK = threading.RLock()


class MCPClient:
    def __init__(self, timeout: float):
        if not shutil.which("npx"):
            raise RuntimeError("Browser MCP requires Node.js/npm (npx on PATH)")
        try:
            import mcp  # noqa: F401
        except ImportError as exc:
            raise RuntimeError("Install requirements.txt (mcp==1.30.0 required)") from exc
        self.timeout = max(15, timeout)
        self.requests = queue.Queue()
        self.ready = Future()
        self.closed = False
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()
        try:
            self.ready.result(timeout=75)
        except BaseException:
            self.close()
            raise

    def _run(self):
        failure = RuntimeError("Browser MCP client disconnected")
        try:
            asyncio.run(self._serve())
        except BaseException as exc:
            failure = RuntimeError(f"Browser MCP connection failed ({type(exc).__name__}); check extension connection")
        finally:
            self.closed = True
            if not self.ready.done():
                self.ready.set_exception(failure)
            while not self.requests.empty():
                item = self.requests.get_nowait()
                if item is not None and not item[1].done():
                    item[1].set_exception(failure)

    async def _serve(self):
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client

        params = StdioServerParameters(command=shutil.which("npx"), args=["--yes", MCP_PACKAGE])
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await asyncio.wait_for(session.initialize(), 60)
                available = await session.list_tools()
                if "browser" not in {tool.name for tool in available.tools}:
                    raise RuntimeError("Browser MCP browser tool is unavailable")
                self.ready.set_result(True)
                while True:
                    item = await asyncio.to_thread(self.requests.get)
                    if item is None:
                        return
                    commands, future = item
                    try:
                        result = await asyncio.wait_for(
                            session.call_tool("browser", {"commands": commands}), self.timeout
                        )
                        if result.isError:
                            # Never echo HTML, cookies, or authenticated URLs in errors.
                            raise RuntimeError("Browser MCP command failed: " + commands.splitlines()[-1].split()[0])
                        output = "\n".join(c.text for c in result.content if c.type == "text")
                        future.set_result(output)
                    except Exception as exc:
                        future.set_exception(exc)

    def call(self, commands):
        if self.closed:
            raise RuntimeError("Browser MCP client is closed")
        future = Future()
        self.requests.put((commands, future))
        return future.result(timeout=self.timeout + 5)

    def close(self):
        if not self.closed:
            self.requests.put(None)
            self.thread.join(timeout=self.timeout + 10)
        if self.thread.is_alive():
            raise RuntimeError("Browser MCP client did not disconnect in time")


def eval_command(function, args=()):
    # Encode the *source and arguments*, not the eval argument. Browser MCP keeps
    # backslashes verbatim. This also preserves multiline JS and // comments.
    payload = base64.b64encode(json.dumps([function, args], ensure_ascii=True).encode("ascii")).decode("ascii")
    return ('eval "async () => { const [source,args]=JSON.parse(atob(\'' + payload +
            '\')); return {airsResult: (await (0,eval)(\'(\'+source+\')\')(...args)) ?? null}; }"')


_FREEZE_HTML = r"""(key) => {
    const markup = (document.doctype ? new XMLSerializer().serializeToString(document.doctype) + '\n' : '')
        + document.documentElement.outerHTML;
    const body = JSON.stringify(markup).replace(/[\u007f-\uffff]/g,
        c => '\\u' + c.charCodeAt(0).toString(16).padStart(4,'0'));
    let hash = 2166136261;
    for (let i=0; i<body.length; i++) hash = Math.imul(hash ^ body.charCodeAt(i), 16777619) >>> 0;
    window[key] = body;
    return {length:body.length, hash};
}"""


class BrowserPage:
    def __init__(self, timeout_ms=45000):
        self.timeout_ms = timeout_ms
        self.client = None
        self.tab = None
        self.transfer_stats = None
        self._html_cache = None

    def __enter__(self):
        self.client = MCPClient(self.timeout_ms / 1000)
        with _LOCK:
            _PAGES.add(self)
        try:
            output = self.client.call("tab new about:blank")
            match = re.search(r"— tab (\d+)", output)
            if not match:
                raise RuntimeError("Browser MCP returned no task tab ID; check extension")
            self.tab = match[1]
            return self
        except BaseException:
            self.close()
            raise

    def command(self, command):
        if self.tab is None:
            raise RuntimeError("No owned Browser MCP tab")
        # tab select sets this client's target; Browser MCP does not activate it
        # in Chrome. Always target explicitly, including in concurrent clients.
        return self.client.call("tab select " + self.tab + "\n" + command)

    def evaluate(self, function, args=()):
        output = self.command(eval_command(function, args))
        start = output.find('{"airsResult":')
        if start < 0:
            raise RuntimeError("Browser MCP returned no structured page result")
        try:
            data, _ = json.JSONDecoder().raw_decode(output[start:])
            return data["airsResult"]
        except (ValueError, KeyError) as exc:
            raise RuntimeError("Browser MCP result truncated or invalid") from exc

    def goto(self, url, **_):
        if not isinstance(url, str) or any(c in url for c in '\r\n"'):
            raise ValueError("Invalid browser URL")
        self.command('goto "' + url + '"')

    @staticmethod
    def wait_for_timeout(ms):
        time.sleep(ms / 1000)

    def wait_for_selector(self, selector, timeout):
        deadline = time.monotonic() + timeout / 1000
        while not self.evaluate("s => !!document.querySelector(s)", [selector]):
            if time.monotonic() >= deadline:
                raise TimeoutError("Timed out waiting for page selector")
            self.wait_for_timeout(150)

    def content(self):
        key = "__airsHTML_" + uuid.uuid4().hex
        status = self.evaluate(_FREEZE_HTML, [key])
        try:
            if self._html_cache is not None and self._html_cache[0] == status:
                return self._html_cache[1]
            parts = []
            for offset in range(0, status["length"], CHUNK_SIZE):
                part = self.evaluate("(key,start,size) => window[key].slice(start,start+size)", [key, offset, CHUNK_SIZE])
                if not isinstance(part, str) or len(part) != min(CHUNK_SIZE, status["length"] - offset):
                    raise RuntimeError("Incomplete Browser MCP HTML chunk")
                parts.append(part)
            body = "".join(parts)
            checksum = 2166136261
            for char in body:
                checksum = ((checksum ^ ord(char)) * 16777619) & 0xffffffff
            if len(body) != status["length"] or checksum != status["hash"]:
                raise RuntimeError("Browser MCP HTML integrity check failed")
            markup = json.loads(body)
            if not isinstance(markup, str):
                raise RuntimeError("Invalid Browser MCP HTML")
            self.transfer_stats = {**status, "chunks": len(parts), "html_length": len(markup)}
            self._html_cache = (status, markup)
            return markup
        finally:
            self.evaluate("key => { delete window[key]; return true; }", [key])

    def find_load_more(self):
        found = self.evaluate(r"""() => {
            const visible = e => e.getClientRects().length && getComputedStyle(e).visibility !== 'hidden';
            const e = [...document.querySelectorAll('button,[role=button]'), ...document.querySelectorAll('a')].find(e =>
                visible(e) && !e.disabled && e.getAttribute('aria-disabled') !== 'true' &&
                /load\s*more|show\s*more|see\s*more|view\s*more|加载更多|查看更多|显示更多|更多/i.test(
                    e.innerText || e.getAttribute('aria-label') || ''));
            document.querySelectorAll('[data-airs-load-more]').forEach(e => e.removeAttribute('data-airs-load-more'));
            if (e) e.setAttribute('data-airs-load-more','true');
            return !!e;
        }""")
        return _LoadMore(self) if found else None

    def close(self):
        if self.client is None:
            return
        try:
            if self.tab is not None:
                for attempt in range(2):
                    try:
                        self.client.call("tab close " + self.tab)
                        self.tab = None
                        break
                    except Exception:
                        if attempt:
                            raise RuntimeError("Could not close owned Browser MCP tab " + self.tab)
        finally:
            self.client.close()
            self.client = None
            with _LOCK:
                _PAGES.discard(self)

    def __exit__(self, exc_type, exc, tb):
        self.close()


class _LoadMore:
    def __init__(self, page):
        self.page = page

    def scroll_into_view_if_needed(self, **_):
        self.page.evaluate("() => { document.querySelector('[data-airs-load-more]')?.scrollIntoView({block:'center'}); return true; }")

    def click(self, **_):
        self.page.command("click [data-airs-load-more='true']")


def close_browser_session():
    with _LOCK:
        pages = list(_PAGES)
    for page in pages:
        try:
            page.close()
        except Exception as exc:
            warnings.warn(str(exc), RuntimeWarning)


atexit.register(close_browser_session)
