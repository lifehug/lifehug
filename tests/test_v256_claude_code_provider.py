"""v256 — headless `claude -p` provider, route C (issue #281).

`claude-code` runs `claude -p --output-format json` with the composed prompt
on stdin so a local backfill (`classify_story.py --classify-all --unclassified
--stale-first`) can proceed under the owner's own Claude Code subscription
with no agent session watching every prompt. It is explicit-only: never part
of `auto` resolution, and it never falls through to another provider.
"""

import json
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SYSTEM = ROOT / "system"
sys.path.insert(0, str(SYSTEM))

import ai_provider as aip  # noqa: E402


def claude_code_config(**overrides) -> dict[str, object]:
    cfg: dict[str, object] = {"ai_provider": "claude-code"}
    cfg.update(overrides)
    return cfg


def fake_completed(*, returncode=0, result="claude-code answer", raw_stdout=None):
    stdout = raw_stdout if raw_stdout is not None else json.dumps({
        "type": "result",
        "subtype": "success",
        "is_error": False,
        "result": result,
    })
    return subprocess.CompletedProcess(
        args=["claude", "-p", "--output-format", "json"],
        returncode=returncode,
        stdout=stdout,
        stderr="",
    )


class ClaudeCodeProviderChoiceTests(unittest.TestCase):
    def test_provider_choice_returns_claude_code_only_when_configured(self):
        with mock.patch.object(
            aip, "load_config", return_value=claude_code_config()
        ), mock.patch.dict(aip.os.environ, {}, clear=True):
            self.assertEqual(aip._provider_choice("claude-sonnet-5", aip._config()), "claude-code")

    def test_auto_never_selects_claude_code(self):
        # An unconfigured machine with no other provider settled falls to
        # agent-task, exactly as before this provider existed — claude-code
        # is never part of auto resolution.
        with mock.patch.object(aip, "load_config", return_value={}), \
                mock.patch.dict(aip.os.environ, {}, clear=True), \
                mock.patch.object(aip, "_openclaw_gateway", return_value=None):
            self.assertEqual(aip._provider_choice("claude-sonnet-5", aip._config()), "agent-task")

    def test_env_var_also_selects_claude_code_explicitly(self):
        with mock.patch.object(aip, "load_config", return_value={}), \
                mock.patch.dict(
                    aip.os.environ, {"LIFEHUG_AI_PROVIDER": "claude-code"}, clear=True
                ):
            self.assertEqual(aip._provider_choice("claude-sonnet-5", aip._config()), "claude-code")


class ClaudeCodeCallTests(unittest.TestCase):
    def test_success_returns_result_text_and_never_uses_a_shell(self):
        with mock.patch.object(aip, "load_config", return_value=claude_code_config()), \
                mock.patch.dict(aip.os.environ, {}, clear=True), \
                mock.patch.object(
                    aip.subprocess, "run", return_value=fake_completed(result="hello there")
                ) as run:
            self.assertEqual(aip.call_ai("compose a question", "claude-sonnet-5"), "hello there")
        args, kwargs = run.call_args
        self.assertEqual(args[0], ["claude", "-p", "--output-format", "json"])
        self.assertNotIn("shell", kwargs)
        self.assertEqual(kwargs.get("input"), "compose a question")
        self.assertTrue(kwargs.get("text"))

    def test_optional_model_config_adds_the_model_flag(self):
        cfg = claude_code_config(claude_code_model="claude-opus-4-8")
        with mock.patch.object(aip, "load_config", return_value=cfg), \
                mock.patch.dict(aip.os.environ, {}, clear=True), \
                mock.patch.object(
                    aip.subprocess, "run", return_value=fake_completed()
                ) as run:
            aip.call_ai("prompt", "claude-sonnet-5")
        args, _kwargs = run.call_args
        self.assertEqual(
            args[0],
            ["claude", "-p", "--output-format", "json", "--model", "claude-opus-4-8"],
        )

    def test_env_var_model_override_takes_precedence_like_other_providers(self):
        cfg = claude_code_config(claude_code_model="config-model")
        with mock.patch.object(aip, "load_config", return_value=cfg), \
                mock.patch.dict(
                    aip.os.environ,
                    {"LIFEHUG_CLAUDE_CODE_MODEL": "env-model"},
                    clear=True,
                ), \
                mock.patch.object(
                    aip.subprocess, "run", return_value=fake_completed()
                ) as run:
            aip.call_ai("prompt", "claude-sonnet-5")
        args, _kwargs = run.call_args
        self.assertIn("env-model", args[0])
        self.assertNotIn("config-model", args[0])

    def test_no_configured_model_omits_the_model_flag(self):
        with mock.patch.object(aip, "load_config", return_value=claude_code_config()), \
                mock.patch.dict(aip.os.environ, {}, clear=True), \
                mock.patch.object(
                    aip.subprocess, "run", return_value=fake_completed()
                ) as run:
            aip.call_ai("prompt", "claude-sonnet-5")
        args, _kwargs = run.call_args
        self.assertEqual(args[0], ["claude", "-p", "--output-format", "json"])

    def test_non_zero_exit_raises_unavailable_with_bounded_metadata(self):
        secret = "PRIVATE_PROMPT_MUST_NOT_LEAK"
        with mock.patch.object(aip, "load_config", return_value=claude_code_config()), \
                mock.patch.dict(aip.os.environ, {}, clear=True), \
                mock.patch.object(
                    aip.subprocess, "run",
                    return_value=fake_completed(returncode=1, raw_stdout=secret),
                ), \
                self.assertRaises(aip.AIUnavailableError) as caught:
            aip.call_ai(secret, "claude-sonnet-5")
        self.assertEqual(caught.exception.provider, "claude-code")
        self.assertEqual(caught.exception.status, "exit_1")
        self.assertNotIn(secret, str(caught.exception))

    def test_malformed_json_raises_response_error_without_leaking_body(self):
        secret = "PRIVATE_MALFORMED_STDOUT"
        with mock.patch.object(aip, "load_config", return_value=claude_code_config()), \
                mock.patch.dict(aip.os.environ, {}, clear=True), \
                mock.patch.object(
                    aip.subprocess, "run",
                    return_value=fake_completed(raw_stdout=f"not json {secret}"),
                ), \
                self.assertRaises(aip.AIResponseError) as caught:
            aip.call_ai("prompt", "claude-sonnet-5")
        self.assertEqual(caught.exception.status, "malformed")
        self.assertNotIn(secret, str(caught.exception))

    def test_json_missing_result_field_raises_response_error(self):
        with mock.patch.object(aip, "load_config", return_value=claude_code_config()), \
                mock.patch.dict(aip.os.environ, {}, clear=True), \
                mock.patch.object(
                    aip.subprocess, "run",
                    return_value=fake_completed(raw_stdout=json.dumps({"type": "result"})),
                ), \
                self.assertRaises(aip.AIResponseError) as caught:
            aip.call_ai("prompt", "claude-sonnet-5")
        self.assertEqual(caught.exception.status, "malformed")

    def test_empty_result_text_raises_response_error(self):
        with mock.patch.object(aip, "load_config", return_value=claude_code_config()), \
                mock.patch.dict(aip.os.environ, {}, clear=True), \
                mock.patch.object(
                    aip.subprocess, "run", return_value=fake_completed(result="   ")
                ), \
                self.assertRaises(aip.AIResponseError) as caught:
            aip.call_ai("prompt", "claude-sonnet-5")
        self.assertEqual(caught.exception.status, "empty")

    def test_missing_binary_raises_unavailable(self):
        with mock.patch.object(aip, "load_config", return_value=claude_code_config()), \
                mock.patch.dict(aip.os.environ, {}, clear=True), \
                mock.patch.object(
                    aip.subprocess, "run", side_effect=FileNotFoundError()
                ), \
                self.assertRaises(aip.AIUnavailableError) as caught:
            aip.call_ai("prompt", "claude-sonnet-5")
        self.assertEqual(caught.exception.status, "binary_missing")
        self.assertEqual(caught.exception.provider, "claude-code")

    def test_timeout_raises_unavailable_and_never_falls_through(self):
        secret = "PRIVATE_TIMED_OUT_PROMPT"
        with mock.patch.object(aip, "load_config", return_value=claude_code_config()), \
                mock.patch.dict(aip.os.environ, {}, clear=True), \
                mock.patch.object(
                    aip.subprocess, "run",
                    side_effect=subprocess.TimeoutExpired(cmd=["claude"], timeout=1),
                ), \
                mock.patch.object(aip, "_call_openclaw") as openclaw, \
                mock.patch.object(aip, "_call_anthropic") as anthropic, \
                self.assertRaises(aip.AIUnavailableError) as caught:
            aip.call_ai(secret, "claude-sonnet-5")
        self.assertEqual(caught.exception.status, "timeout")
        self.assertNotIn(secret, str(caught.exception))
        openclaw.assert_not_called()
        anthropic.assert_not_called()

    def test_provider_status_reports_readiness_from_which_without_a_subprocess_call(self):
        with mock.patch.object(aip, "load_config", return_value=claude_code_config()), \
                mock.patch.dict(aip.os.environ, {}, clear=True), \
                mock.patch.object(aip.shutil, "which", return_value="/usr/local/bin/claude") as which, \
                mock.patch.object(aip.subprocess, "run") as run:
            status = aip.provider_status(probe=True)
        self.assertEqual(status.provider, "claude-code")
        self.assertTrue(status.ready)
        which.assert_called_once_with("claude")
        run.assert_not_called()

    def test_provider_status_reports_not_ready_when_binary_absent(self):
        with mock.patch.object(aip, "load_config", return_value=claude_code_config()), \
                mock.patch.dict(aip.os.environ, {}, clear=True), \
                mock.patch.object(aip.shutil, "which", return_value=None):
            status = aip.provider_status(probe=True)
        self.assertEqual(status.provider, "claude-code")
        self.assertFalse(status.ready)


if __name__ == "__main__":
    unittest.main()
