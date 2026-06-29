"""Drive the configured agent for a single generation step.

Three backends, all reusing your existing login (no per-token API key needed):
  - codex       : Codex CLI (`codex exec`)
  - claude      : Claude Code CLI (`claude --print`), output parsed from stdout
  - claude-sdk  : Claude Agent SDK (`claude-agent-sdk`) over the same Claude Code
                  subscription login — structured results + typed errors instead
                  of scraping stdout. Set AIRS_CLAUDE_MODEL to pick a model.

The generate_* test scripts use these helpers to produce one article's summary or
digest through the same backend the full Refresh flow uses.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")


def prompts_dir() -> Path:
    return Path(__file__).resolve().parents[1] / "prompts"


def load_prompt(name: str) -> str:
    return (prompts_dir() / name).read_text(encoding="utf-8")


_TRANSIENT_RE = re.compile(
    r"rate.?limit|overloaded|too many requests|\b429\b|\b500\b|\b502\b|\b503\b|\b529\b|"
    r"internal server error|bad gateway|service unavailable|timeout|timed out|temporarily|"
    r"maximum number of turns",  # claude-sdk: occasional long output doesn't finish in one turn — retry
    re.I,
)


def _run_claude_sdk(prompt: str) -> str:
    """One Claude Agent SDK call over the user's Claude Code subscription login.

    Pure text generation: all tools disabled, single turn, no user/project
    CLAUDE.md or settings loaded — so the model is driven only by `prompt` and the
    output is reproducible. Returns the assistant's full text (same contract as the
    CLI path). Raises RuntimeError on failure; the caller decides if it's transient.
    """
    try:
        from claude_agent_sdk import (
            AssistantMessage,
            ClaudeAgentOptions,
            CLINotFoundError,
            ResultMessage,
            TextBlock,
            query,
        )
    except ImportError as exc:
        raise RuntimeError(
            "claude-agent-sdk not installed. Run: python -m pip install claude-agent-sdk"
        ) from exc

    options = ClaudeAgentOptions(
        model=os.environ.get("AIRS_CLAUDE_MODEL") or None,  # None -> account default
        allowed_tools=[],            # pure LLM call: no filesystem/tool access
        permission_mode="dontAsk",   # headless: never block on a permission prompt
        max_turns=1,                 # single shot
        setting_sources=[],          # ignore user/project CLAUDE.md & settings
    )

    async def _collect() -> str:
        parts: list[str] = []
        result_text, error_detail = None, None
        async for msg in query(prompt=prompt, options=options):
            if isinstance(msg, AssistantMessage):
                parts.extend(b.text for b in msg.content if isinstance(b, TextBlock))
            elif isinstance(msg, ResultMessage):
                result_text = msg.result
                if msg.is_error:
                    error_detail = msg.result or msg.api_error_status or msg.subtype
        if error_detail:
            raise RuntimeError(f"result error: {error_detail}")
        text = "".join(parts).strip() or (result_text or "").strip()
        if not text:
            raise RuntimeError("returned no text")
        return text

    try:
        return asyncio.run(_collect())
    except CLINotFoundError as exc:
        raise RuntimeError(
            "Claude Code CLI not found / not logged in — run `claude` once to log in."
        ) from exc


def run_agent(prompt: str, agent: str = "codex", retries: int = 3) -> str:
    """Run one generation step through the chosen backend and return its text.

    Transient errors (rate limit / overload / 5xx / timeout) are retried with
    exponential backoff, so higher --jobs concurrency doesn't drop articles on a
    momentary API hiccup. Non-transient errors (e.g. auth) fail immediately.
    """
    tmpdir = None
    last_msg = None  # codex: read the clean final message from here, not noisy stdout
    if agent == "codex":
        tmpdir = tempfile.mkdtemp(prefix="airs_codex_")
        last_msg = Path(tmpdir) / "last.txt"
        cmd = ["codex", "exec", "--skip-git-repo-check",
               "--dangerously-bypass-approvals-and-sandbox",
               "-o", str(last_msg), "-"]
    elif agent == "claude":
        cmd = ["claude", "--print", "--dangerously-skip-permissions"]
    elif agent == "claude-sdk":
        cmd = None
    else:
        raise ValueError(f"Unknown agent '{agent}'. Use 'codex', 'claude', or 'claude-sdk'.")

    try:
        detail, code = "", None
        for attempt in range(1, retries + 1):
            if agent == "claude-sdk":
                try:
                    return _run_claude_sdk(prompt)
                except RuntimeError as exc:
                    detail, code = str(exc), None
            else:
                try:
                    proc = subprocess.run(cmd, input=prompt, capture_output=True, text=True, encoding="utf-8")
                except FileNotFoundError as exc:
                    raise RuntimeError(
                        f"Agent CLI '{agent}' not found on PATH. Install and log in to it first."
                    ) from exc
                if proc.returncode == 0:
                    if last_msg is not None:  # codex: final message is in the file, stdout is just progress noise
                        text = last_msg.read_text(encoding="utf-8") if last_msg.exists() else ""
                        if text.strip():
                            return text
                        detail, code = "codex exited 0 but wrote no final message", proc.returncode
                    else:
                        return proc.stdout
                else:
                    # Some CLIs (e.g. claude) print the real error to stdout, not stderr.
                    detail = "\n".join(s for s in ((proc.stderr or "").strip(), (proc.stdout or "").strip()) if s)
                    code = proc.returncode
            if attempt < retries and _TRANSIENT_RE.search(detail):
                time.sleep(min(2 ** attempt, 20))
                continue
            break
        raise RuntimeError(f"{agent} failed (exit {code}): {detail[:800]}")
    finally:
        if tmpdir:
            shutil.rmtree(tmpdir, ignore_errors=True)


def extract_json(text: str) -> str:
    """Return the first VALID JSON object found in possibly-noisy agent output.

    codex in particular interleaves prose/progress (and stray braces like {x})
    with the answer, so a first-brace-to-last-brace match is unsafe. Try the whole
    output first, then scan for the first balanced {...} that actually parses.
    """
    cleaned = text.strip()
    fence = re.match(r"^```[a-zA-Z]*\n(.*)\n```$", cleaned, re.S)
    if fence:
        cleaned = fence.group(1).strip()
    try:
        json.loads(cleaned)
        return cleaned
    except ValueError:
        pass

    start = None
    depth = 0
    in_str = False
    escape = False
    for index, char in enumerate(cleaned):
        if start is None:
            if char == "{":
                start, depth, in_str, escape = index, 1, False, False
            continue
        if in_str:
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == '"':
                in_str = False
            continue
        if char == '"':
            in_str = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                candidate = cleaned[start:index + 1]
                try:
                    json.loads(candidate)
                    return candidate
                except ValueError:
                    start = None
    raise ValueError("No valid JSON object found in agent output.")


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
