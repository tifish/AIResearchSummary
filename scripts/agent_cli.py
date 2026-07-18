"""Drive the configured agent for a single generation step.

Three backends, all headless CLI subprocesses reusing an existing local login
(no per-backend SDK dependency — the CLIs get new models/flags first):
  - codex   : Codex CLI (`codex exec`).
              AIRS_CODEX_MODEL picks a model (default = account default).
              AIRS_CODEX_REASONING_EFFORT picks its reasoning effort.
              AIRS_CODEX_BIN can override the Codex CLI executable.
  - claude  : Claude Code CLI (`claude -p`).
              AIRS_CLAUDE_MODEL picks a model (default = account default).
              AIRS_CLAUDE_EFFORT picks its effort level.
              AIRS_CLAUDE_BIN can override the Claude Code executable.
  - grok    : Grok Build CLI in supported headless JSON mode.
              AIRS_GROK_MODEL picks a model (default = account default).
              AIRS_GROK_REASONING_EFFORT picks its reasoning effort.

All return the model's final text (the generate flow then splits it on the
===SUMMARY===/===VALUE===/===DIGEST=== markers). The generate_* test scripts use
these helpers to produce one article's summary/digest the same way Refresh does.
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


def prompts_dir() -> Path:
    return Path(__file__).resolve().parents[1] / "prompts"


def load_prompt(name: str) -> str:
    return (prompts_dir() / name).read_text(encoding="utf-8")


_TRANSIENT_RE = re.compile(
    r"rate.?limit|overloaded|too many requests|\b429\b|\b500\b|\b502\b|\b503\b|\b529\b|"
    r"internal server error|bad gateway|service unavailable|timeout|timed out|temporarily|"
    r"maximum number of turns|"   # claude: occasional long output doesn't finish in one turn — retry
    r"ServerBusyError|RetryLimitExceededError|server busy|"
    r"exceeded retry limit|stream disconnected",  # codex transient errors
    re.I,
)


def _run_claude_cli(prompt: str) -> str:
    """One headless Claude Code CLI call over the user's subscription login.

    Pure text generation: all built-in tools and MCP servers disabled, no
    user/project CLAUDE.md or settings loaded, no session files written — so the
    model is driven only by `prompt` and the output is reproducible. The prompt
    goes in over stdin (no Windows command-line length limit); `--output-format
    json` gives a stable `result` field for the final text. Raises RuntimeError
    on failure; the caller decides if it's transient.
    """
    command = [
        os.environ.get("AIRS_CLAUDE_BIN") or "claude",
        "-p",
        "--output-format", "json",
        "--tools", "",               # pure LLM call: no filesystem/tool access
        "--strict-mcp-config",       # with no --mcp-config: no MCP servers
        "--permission-mode", "dontAsk",  # headless: never block on a prompt
        "--setting-sources", "",     # ignore user/project CLAUDE.md & settings
        "--no-session-persistence",
    ]
    model = os.environ.get("AIRS_CLAUDE_MODEL")
    if model:
        command.extend(["--model", model])
    effort = os.environ.get("AIRS_CLAUDE_EFFORT")
    if effort:
        command.extend(["--effort", effort])

    try:
        result = subprocess.run(
            command,
            input=prompt,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
    except FileNotFoundError as exc:
        raise RuntimeError(
            "Claude Code CLI not found — install it and run `claude` once to log in."
        ) from exc

    payload = None
    try:
        payload = json.loads(extract_json(result.stdout))
    except ValueError:
        pass

    if result.returncode != 0 or (payload is not None and payload.get("is_error")):
        detail = ""
        if payload is not None:
            detail = str(payload.get("result") or payload.get("subtype") or "")
        detail = detail or (result.stderr or result.stdout).strip()
        raise RuntimeError(
            f"Claude Code exited with code {result.returncode}: {detail[:800]}"
        )
    if payload is None:
        raise RuntimeError(f"Claude Code returned invalid JSON: {result.stdout[:800]}")

    text = str(payload.get("result") or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    if not text:
        raise RuntimeError(
            f"Claude Code returned no text (subtype={payload.get('subtype')})"
        )
    return text


def _run_codex_cli(prompt: str) -> str:
    """One headless Codex CLI call (`codex exec`) over the user's login.

    Pure text generation: read-only sandbox, ephemeral session (no session files
    on disk), non-interactive so it never blocks on an approval prompt. The
    prompt goes in over stdin (no Windows command-line length limit) and the
    final text comes back through --output-last-message, so noisy progress
    output on stdout never reaches the parser. Raises RuntimeError on failure;
    the caller decides if it's transient.
    """
    out_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as out_file:
            out_path = Path(out_file.name)

        command = [
            os.environ.get("AIRS_CODEX_BIN") or "codex",
            "exec",
            "--sandbox", "read-only",
            "--skip-git-repo-check",
            "--ephemeral",
            "--color", "never",
            "--output-last-message", str(out_path),
        ]
        model = os.environ.get("AIRS_CODEX_MODEL")
        if model:
            command.extend(["--model", model])
        effort = os.environ.get("AIRS_CODEX_REASONING_EFFORT")
        if effort:
            command.extend(["-c", f'model_reasoning_effort="{effort}"'])
        command.append("-")  # read the prompt from stdin

        try:
            result = subprocess.run(
                command,
                input=prompt,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=False,
            )
        except FileNotFoundError as exc:
            raise RuntimeError(
                "Codex CLI not found. Install it and run `codex login` once."
            ) from exc

        if result.returncode != 0:
            detail = (result.stderr or result.stdout).strip()
            raise RuntimeError(
                f"codex exited with code {result.returncode}: {detail[:800]}"
            )

        text = out_path.read_text(encoding="utf-8", errors="replace")
        text = text.replace("\r\n", "\n").replace("\r", "\n").strip()
        if not text:
            detail = (result.stderr or result.stdout).strip()
            raise RuntimeError(f"codex returned no text: {detail[-400:]}")
        return text
    finally:
        if out_path is not None:
            out_path.unlink(missing_ok=True)


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
        attempt_fn = _run_codex_cli
    elif agent == "claude":
        attempt_fn = _run_claude_cli
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
