"""Drive the configured agent CLI (codex/claude) for a single generation step.

The generate_* test scripts use these helpers to produce one article's summary or
digest through the same CLI the full Refresh flow uses — no API key required.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
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
    r"internal server error|bad gateway|service unavailable|timeout|timed out|temporarily",
    re.I,
)


def run_agent(prompt: str, agent: str = "codex", retries: int = 3) -> str:
    """Pipe prompt to the agent CLI via stdin and return its stdout.

    Transient errors (rate limit / overload / 5xx / timeout) are retried with
    exponential backoff, so higher --jobs concurrency doesn't drop articles on a
    momentary API hiccup. Non-transient errors (e.g. auth) fail immediately.
    """
    if agent == "codex":
        cmd = ["codex", "exec", "--skip-git-repo-check",
               "--dangerously-bypass-approvals-and-sandbox", "-"]
    elif agent == "claude":
        cmd = ["claude", "--print", "--dangerously-skip-permissions"]
    else:
        raise ValueError(f"Unknown agent '{agent}'. Use 'codex' or 'claude'.")

    detail, code = "", None
    for attempt in range(1, retries + 1):
        try:
            proc = subprocess.run(cmd, input=prompt, capture_output=True, text=True, encoding="utf-8")
        except FileNotFoundError as exc:
            raise RuntimeError(
                f"Agent CLI '{agent}' not found on PATH. Install and log in to it first."
            ) from exc
        if proc.returncode == 0:
            return proc.stdout
        # Some CLIs (e.g. claude) print the real error to stdout, not stderr.
        detail = "\n".join(s for s in ((proc.stderr or "").strip(), (proc.stdout or "").strip()) if s)
        code = proc.returncode
        if attempt < retries and _TRANSIENT_RE.search(detail):
            time.sleep(min(2 ** attempt, 20))
            continue
        break
    raise RuntimeError(f"{agent} CLI failed (exit {code}): {detail[:800]}")


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
