"""Drive Antigravity CLI (`agy`) for a single generation step.

Single headless CLI backend reusing the local Antigravity login:
  - Default model: `gemini-4-neon-high` (Gemini 4 Neon, High effort)
  - Optional env overrides:
      * AIRS_AGY_BIN     : override the `agy` executable path (default: `agy`)
      * AIRS_AGY_MODEL   : override the model slug (default: `gemini-4-neon-high`)
      * AIRS_AGY_TIMEOUT : per-call timeout in seconds (default: `600`)

Returns the model's final text (the generate flow then splits it on the
===TITLE_ZH===/===SUMMARY===/===VALUE===/===DIGEST=== markers).
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

DEFAULT_MODEL = "gemini-4-neon-high"
DEFAULT_TIMEOUT = 600

# Pure text generation: block shell, file, web, and MCP tools for this session only.
_PURE_TEXT_SETTINGS = json.dumps(
    {
        "toolPermission": "strict",
        "permissions": {
            "deny": [
                "command(*)",
                "write_file(*)",
                "read_file(*)",
                "read_url(*)",
                "execute_url(*)",
                "mcp(*)",
            ]
        },
    },
    separators=(",", ":"),
)

_AUTH_ERROR_RE = re.compile(
    r"authentication required|please sign in|waiting for authentication|"
    r"not authenticated|unauthorized|\b401\b",
    re.I,
)

_TRANSIENT_RE = re.compile(
    r"rate.?limit|overloaded|too many requests|\b429\b|\b500\b|\b502\b|\b503\b|\b529\b|"
    r"internal server error|bad gateway|service unavailable|resource.?exhausted|"
    r"deadline exceeded|timeout|timed out|temporarily|server busy|"
    r"connection reset|broken pipe|stream disconnected",
    re.I,
)


def prompts_dir() -> Path:
    return Path(__file__).resolve().parents[1] / "prompts"


def load_prompt(name: str) -> str:
    return (prompts_dir() / name).read_text(encoding="utf-8")


def _parse_stream_json_result(stdout: str) -> dict | None:
    """Return the final `result` payload from `agy --output-format stream-json`."""
    result_payload: dict | None = None
    for raw_line in stdout.splitlines():
        line = raw_line.strip()
        if not line or not line.startswith("{"):
            continue
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if not isinstance(event, dict):
            continue
        if event.get("event") == "result" and isinstance(event.get("result"), dict):
            result_payload = event["result"]
        elif "status" in event and ("response" in event or "error" in event):
            result_payload = event
    return result_payload


def _agy_subprocess_env() -> dict[str, str]:
    """Build a clean environment for standalone headless `agy` execution.

    When `refresh.py` is invoked from inside an Antigravity / T3 Code agent
    session, the parent process sets `ANTIGRAVITY_*`, `AGY_ACP_*`, `GEMINI_HOME`,
    and a synthetic loopback `SSH_CONNECTION` (`127.0.0.1 0 127.0.0.1 0`).
    Those redirect `agy` away from the user's normal `~/.gemini/antigravity-cli`
    profile and OS credential store, causing headless runs to appear signed out.
    """
    raw = dict(os.environ)
    nested_harness = bool(
        raw.get("ANTIGRAVITY_APP_DATA_DIR")
        or raw.get("AGY_ACP_FORCE_FILE_STORAGE")
        or raw.get("ANTIGRAVITY_AGENT")
    )
    env = {
        k: v
        for k, v in raw.items()
        if not k.startswith(("ANTIGRAVITY_", "AGY_ACP_"))
    }
    if nested_harness:
        env.pop("GEMINI_HOME", None)
    if raw.get("SSH_CONNECTION") == "127.0.0.1 0 127.0.0.1 0":
        env.pop("SSH_CONNECTION", None)
        env.pop("SSH_CLIENT", None)
        env.pop("SSH_TTY", None)
    env.setdefault("AGY_CLI_DISABLE_AUTO_UPDATE", "1")
    return env


def _run_agy_cli(prompt: str) -> str:
    """One headless Antigravity CLI call over the user's local login.

    Streams the prompt over stdin (`--input-format stream-json --output-format
    stream-json`) to avoid Windows command-line length limits, isolates execution
    in an empty temp working directory with all tools denied via `--settings`,
    and extracts the final turn's `response` from the terminal `result` event.
    """
    agy_bin = os.environ.get("AIRS_AGY_BIN") or "agy"
    model = os.environ.get("AIRS_AGY_MODEL") or DEFAULT_MODEL
    timeout = int(os.environ.get("AIRS_AGY_TIMEOUT", str(DEFAULT_TIMEOUT)))

    command = [
        agy_bin,
        "--input-format", "stream-json",
        "--output-format", "stream-json",
        "--model", model,
        "--disable-slash-commands",
        "--print-timeout", f"{timeout}s",
        "--settings", _PURE_TEXT_SETTINGS,
    ]
    stdin_payload = json.dumps(
        {"event": "user", "message": {"content": prompt}},
        ensure_ascii=False,
    ) + "\n"

    with tempfile.TemporaryDirectory(prefix="airs-agy-") as tmpdir:
        try:
            result = subprocess.run(
                command,
                input=stdin_payload,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=False,
                cwd=tmpdir,
                env=_agy_subprocess_env(),
                timeout=timeout + 30,
            )
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError(
                f"agy timed out after {timeout} seconds; set AIRS_AGY_TIMEOUT to adjust."
            ) from exc
        except FileNotFoundError as exc:
            raise RuntimeError(
                "Antigravity CLI (`agy`) not found. Install it and run `agy` once to sign in."
            ) from exc

    payload = _parse_stream_json_result(result.stdout)
    stderr_text = (result.stderr or "").strip()

    if payload is not None:
        status = str(payload.get("status") or "")
        if result.returncode != 0 or status != "SUCCESS":
            detail = str(payload.get("error") or status or stderr_text or result.stdout).strip()
            raise RuntimeError(f"agy exited with code {result.returncode} (status={status or 'unknown'}): {detail[:800]}")
        text = str(payload.get("response") or "").replace("\r\n", "\n").replace("\r", "\n").strip()
        if not text:
            raise RuntimeError(f"agy returned no text (status={status})")
        return text

    detail = stderr_text or result.stdout.strip()
    if result.returncode != 0:
        raise RuntimeError(f"agy exited with code {result.returncode}: {detail[:800]}")
    raise RuntimeError(f"agy returned no result event: {detail[:800]}")


def run_agent(prompt: str, retries: int = 3) -> str:
    """Run one generation step through Antigravity CLI and return its text.

    Transient errors (rate limit / overload / 5xx / timeout) are retried with
    exponential backoff, so higher --jobs concurrency doesn't drop articles on a
    momentary API hiccup. Auth and other non-transient errors fail immediately.
    """
    detail = ""
    for attempt in range(1, retries + 1):
        try:
            return _run_agy_cli(prompt)
        except RuntimeError as exc:
            detail = str(exc)
        if attempt < retries and not _AUTH_ERROR_RE.search(detail) and _TRANSIENT_RE.search(detail):
            time.sleep(min(2 ** attempt, 20))
            continue
        break
    raise RuntimeError(f"antigravity failed: {detail[:800]}")


def extract_html(text: str) -> str:
    """Pull the HTML document out of possibly-noisy agent output."""
    low = text.lower()
    start = low.find("<!doctype")
    if start < 0:
        start = low.find("<html")
    end = low.rfind("</html>")
    if start >= 0 and end >= 0:
        return text[start:end + len("</html>")]
    return text.strip()
