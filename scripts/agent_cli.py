"""Drive the configured agent for a single generation step.

Three backends, all reusing an existing local login:
  - codex   : OpenAI Codex SDK (`openai-codex`) over the Codex CLI login.
              AIRS_CODEX_MODEL picks a model (default = account default).
              AIRS_CODEX_REASONING_EFFORT picks its reasoning effort.
              AIRS_CODEX_BIN can override the Codex CLI executable.
  - claude  : Claude Agent SDK (`claude-agent-sdk`) over the Claude Code login.
              AIRS_CLAUDE_MODEL picks a model (default = account default).
              AIRS_CLAUDE_EFFORT picks its effort level.
  - grok    : Grok Build CLI in supported headless JSON mode.
              AIRS_GROK_MODEL picks a model (default = account default).
              AIRS_GROK_REASONING_EFFORT picks its reasoning effort.

All return the model's final text (the generate flow then splits it on the
===SUMMARY===/===VALUE===/===DIGEST=== markers). The generate_* test scripts use
these helpers to produce one article's summary/digest the same way Refresh does.
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
    r"maximum number of turns|"   # claude (SDK): occasional long output doesn't finish in one turn — retry
    r"ServerBusyError|RetryLimitExceededError|server busy",  # codex (SDK) transient error types
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
        effort=os.environ.get("AIRS_CLAUDE_EFFORT") or None,
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


def _run_codex_sdk(prompt: str) -> str:
    """One Codex SDK call over the user's Codex CLI login.

    Pure text generation: read-only sandbox + deny-all approvals so it never writes
    files or blocks on an approval prompt (the prompt is self-contained). Returns
    the turn's final text. Raises RuntimeError on failure; the caller decides if
    it's transient.
    """
    try:
        from openai_codex import ApprovalMode, Codex, CodexConfig, CodexError, Sandbox
    except ImportError as exc:
        raise RuntimeError(
            "openai-codex not installed. Run: python -m pip install openai-codex"
        ) from exc

    model = os.environ.get("AIRS_CODEX_MODEL") or None  # None -> account default
    effort = os.environ.get("AIRS_CODEX_REASONING_EFFORT") or None
    codex_bin = os.environ.get("AIRS_CODEX_BIN") or shutil.which("codex")
    codex_config = CodexConfig(codex_bin=codex_bin) if codex_bin else CodexConfig()
    try:
        with Codex(codex_config) as codex:
            thread = codex.thread_start(
                sandbox=Sandbox.read_only,
                approval_mode=ApprovalMode.deny_all,
                model=model,
            )
            result = thread.run(prompt, effort=effort)
    except CodexError as exc:
        raise RuntimeError(f"codex error ({type(exc).__name__}): {exc}") from exc

    if getattr(result, "error", None):
        raise RuntimeError(f"codex result error: {result.error}")
    text = (result.final_response or "").strip()
    if not text:
        raise RuntimeError(f"codex returned no text (status={getattr(result, 'status', None)})")
    return text


def _run_grok_cli(prompt: str) -> str:
    """One headless Grok Build call over the user's existing login.

    The prompt goes through a temporary UTF-8 file instead of the command line,
    because an extracted article can exceed Windows' command-line length limit.
    JSON output gives us a stable final-text field and keeps diagnostics separate.
    Tools, web search, memory, and subagents are disabled for this pure generation
    step; ``dontAsk`` prevents a headless run from waiting for approval.
    """
    prompt_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", suffix=".md", delete=False
        ) as prompt_file:
            prompt_file.write(prompt)
            prompt_path = Path(prompt_file.name)

        command = [
            "grok",
            "--no-auto-update",
            "--prompt-file",
            str(prompt_path),
            "--output-format",
            "json",
            "--permission-mode",
            "dontAsk",
            "--max-turns",
            "1",
            "--no-memory",
            "--no-subagents",
            "--disable-web-search",
            "--tools",
            "",
            "--verbatim",
        ]
        model = os.environ.get("AIRS_GROK_MODEL")
        if model:
            command.extend(["--model", model])
        effort = os.environ.get("AIRS_GROK_REASONING_EFFORT")
        if effort:
            command.extend(["--reasoning-effort", effort])

        try:
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=False,
            )
        except FileNotFoundError as exc:
            raise RuntimeError(
                "Grok Build CLI not found. Install it and run `grok login` once."
            ) from exc

        if result.returncode != 0:
            detail = (result.stderr or result.stdout).strip()
            raise RuntimeError(
                f"Grok Build exited with code {result.returncode}: {detail[:800]}"
            )

        try:
            payload = json.loads(extract_json(result.stdout))
        except (ValueError, json.JSONDecodeError) as exc:
            raise RuntimeError(
                f"Grok Build returned invalid JSON: {result.stdout[:800]}"
            ) from exc

        text = str(payload.get("text") or "").replace("\r\n", "\n").replace("\r", "\n").strip()
        if not text:
            reason = payload.get("stopReason") or "unknown"
            raise RuntimeError(f"Grok Build returned no text (stopReason={reason})")
        return text
    finally:
        if prompt_path is not None:
            prompt_path.unlink(missing_ok=True)


def run_agent(prompt: str, agent: str = "codex", retries: int = 3) -> str:
    """Run one generation step through the chosen backend and return its text.

    Transient errors (rate limit / overload / 5xx / timeout) are retried with
    exponential backoff, so higher --jobs concurrency doesn't drop articles on a
    momentary API hiccup. Non-transient errors (e.g. auth) fail immediately.
    """
    if agent == "codex":
        attempt_fn = _run_codex_sdk
    elif agent == "claude":
        attempt_fn = _run_claude_sdk
    elif agent == "grok":
        attempt_fn = _run_grok_cli
    else:
        raise ValueError(f"Unknown agent '{agent}'. Use 'codex', 'claude', or 'grok'.")

    detail = ""
    for attempt in range(1, retries + 1):
        try:
            return attempt_fn(prompt)
        except RuntimeError as exc:
            detail = str(exc)
        if attempt < retries and _TRANSIENT_RE.search(detail):
            time.sleep(min(2 ** attempt, 20))
            continue
        break
    raise RuntimeError(f"{agent} failed: {detail[:800]}")


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
