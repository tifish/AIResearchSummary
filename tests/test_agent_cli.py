"""Offline unit tests for the single-backend Antigravity CLI runner."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import agent_cli  # noqa: E402
import generate  # noqa: E402


def _ndjson(*events: dict) -> str:
    return "\n".join(json.dumps(ev, ensure_ascii=False) for ev in events) + "\n"


class AgentCliTests(unittest.TestCase):
    def test_run_agy_cli_command_and_stream_json_parsing(self):
        captured = {}

        def fake_run(cmd, **kwargs):
            captured["cmd"] = cmd
            captured["kwargs"] = kwargs
            stdout = _ndjson(
                {"event": "init", "conversation_id": "conv-1", "init": {"model": "gemini-4-neon-high"}},
                {"event": "step_update", "step_update": {"step_type": "agent_response", "text_delta": "hello"}},
                {
                    "event": "result",
                    "result": {
                        "conversation_id": "conv-1",
                        "status": "SUCCESS",
                        "response": "line1\r\nline2\n",
                    },
                },
            )
            return subprocess.CompletedProcess(cmd, 0, stdout=stdout, stderr="")

        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("AIRS_AGY_BIN", None)
            os.environ.pop("AIRS_AGY_MODEL", None)
            os.environ.pop("AIRS_AGY_TIMEOUT", None)
            with patch.object(agent_cli.subprocess, "run", side_effect=fake_run):
                text = agent_cli.run_agent("summarize this")

        self.assertEqual(text, "line1\nline2")
        cmd = captured["cmd"]
        self.assertEqual(cmd[0], "agy")
        self.assertIn("--input-format", cmd)
        self.assertEqual(cmd[cmd.index("--input-format") + 1], "stream-json")
        self.assertEqual(cmd[cmd.index("--output-format") + 1], "stream-json")
        self.assertEqual(cmd[cmd.index("--model") + 1], "gemini-4-neon-high")
        self.assertIn("--disable-slash-commands", cmd)
        self.assertEqual(cmd[cmd.index("--print-timeout") + 1], "600s")
        settings = json.loads(cmd[cmd.index("--settings") + 1])
        self.assertEqual(settings["toolPermission"], "strict")
        self.assertIn("command(*)", settings["permissions"]["deny"])
        self.assertIn("write_file(*)", settings["permissions"]["deny"])

        sent = json.loads(captured["kwargs"]["input"])
        self.assertEqual(sent, {"event": "user", "message": {"content": "summarize this"}})
        self.assertEqual(captured["kwargs"]["timeout"], 630)

    def test_error_envelope_raises_without_retrying(self):
        stdout = _ndjson(
            {
                "event": "result",
                "result": {
                    "status": "ERROR",
                    "response": "",
                    "error": "invalid model selection",
                },
            }
        )
        proc = subprocess.CompletedProcess(["agy"], 1, stdout=stdout, stderr="")
        with patch.object(agent_cli.subprocess, "run", return_value=proc) as mock_run:
            with self.assertRaisesRegex(RuntimeError, "invalid model selection"):
                agent_cli.run_agent("prompt", retries=3)
        self.assertEqual(mock_run.call_count, 1)

    def test_auth_error_containing_timeout_does_not_retry(self):
        proc = subprocess.CompletedProcess(
            ["agy"],
            1,
            stdout="",
            stderr="Authentication required. Waiting for authentication (timeout 60s)...",
        )
        with patch.object(agent_cli.subprocess, "run", return_value=proc) as mock_run:
            with self.assertRaisesRegex(RuntimeError, "Authentication required"):
                agent_cli.run_agent("prompt", retries=3)
        self.assertEqual(mock_run.call_count, 1)

    def test_transient_error_retries_and_recovers(self):
        fail = subprocess.CompletedProcess(["agy"], 1, stdout="", stderr="429 RESOURCE_EXHAUSTED")
        ok = subprocess.CompletedProcess(
            ["agy"],
            0,
            stdout=_ndjson({"event": "result", "result": {"status": "SUCCESS", "response": "recovered"}}),
            stderr="",
        )
        with patch.object(agent_cli.subprocess, "run", side_effect=[fail, ok]) as mock_run, \
             patch.object(agent_cli.time, "sleep") as mock_sleep:
            self.assertEqual(agent_cli.run_agent("prompt", retries=3), "recovered")
        self.assertEqual(mock_run.call_count, 2)
        mock_sleep.assert_called_once_with(2)

    def test_subprocess_env_strips_nested_harness_overrides(self):
        fake_env = {
            "PATH": "C:\\bin",
            "ANTIGRAVITY_APP_DATA_DIR": "C:/isolated",
            "ANTIGRAVITY_AGENT": "1",
            "AGY_ACP_FORCE_FILE_STORAGE": "1",
            "GEMINI_HOME": "C:/isolated",
            "SSH_CONNECTION": "127.0.0.1 0 127.0.0.1 0",
        }
        with patch.dict(os.environ, fake_env, clear=True):
            cleaned = agent_cli._agy_subprocess_env()
        self.assertEqual(cleaned["PATH"], "C:\\bin")
        self.assertEqual(cleaned["AGY_CLI_DISABLE_AUTO_UPDATE"], "1")
        for key in (
            "ANTIGRAVITY_APP_DATA_DIR",
            "ANTIGRAVITY_AGENT",
            "AGY_ACP_FORCE_FILE_STORAGE",
            "GEMINI_HOME",
            "SSH_CONNECTION",
        ):
            self.assertNotIn(key, cleaned)

    def test_missing_binary_reports_helpful_error(self):
        with patch.object(agent_cli.subprocess, "run", side_effect=FileNotFoundError("agy")):
            with self.assertRaisesRegex(RuntimeError, "Antigravity CLI"):
                agent_cli.run_agent("prompt", retries=1)

    def test_generate_uses_single_agent_without_agent_arg(self):
        meta = {
            "title": "Test Paper",
            "source": "anthropic",
            "source_name": "Anthropic",
            "date": "2026-11-21",
            "category": "Research",
            "url": "https://www.anthropic.com/research/test-paper",
            "article_text": "Body text.",
            "article_images": [],
        }
        fake_output = (
            "===TITLE_ZH===\n测试论文\n"
            "===SUMMARY===\n结论：测试通过。关键数据：100%。\n"
            "===VALUE===\n验证单后端生成链路正常工作。\n"
            "===DIGEST===\n"
            "<!doctype html><html lang=\"zh-CN\"><head><meta charset=\"utf-8\"></head>"
            "<body><main><section id=\"translation\"><h2>完整译文</h2><p>正文。</p></section></main></body></html>"
        )
        with patch.object(generate, "run_agent", return_value=fake_output) as mock_run:
            result = generate.generate(meta)
        mock_run.assert_called_once()
        self.assertEqual(result["title_zh"], "测试论文")
        self.assertIn("结论：", result["summary_zh"])
        self.assertEqual(result["value_zh"], "验证单后端生成链路正常工作。")
        self.assertIn('id="translation"', result["html"])


if __name__ == "__main__":
    unittest.main()
