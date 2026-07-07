"""v83 — detached answer filer hardening (audit of v82).

The wrapper is bash, so these tests pin its contract at the text level
(notification goes through `lifehug.py notify`, never a raw Telegram curl;
LIFEHUG_CHAT_ID maps to the framework's TELEGRAM_CHAT_ID; a lock serializes
filings) and exercise the framework plumbing it now relies on
(resolve_telegram_target's env override and group_chat_id fallback).
"""

import importlib.util
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SYSTEM = ROOT / "system"
sys.path.insert(0, str(SYSTEM))

FILER = SYSTEM / "file_answer_bg.sh"


def load(name):
    """Load a private copy of system/<name>.py WITHOUT clobbering the shared
    sys.modules entry — other test modules bind the canonical module at import
    time, and replacing it mid-suite splits state across two module objects."""
    spec = importlib.util.spec_from_file_location(name, SYSTEM / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    orig = sys.modules.get(name)
    sys.modules[name] = mod
    try:
        spec.loader.exec_module(mod)
    finally:
        if orig is not None:
            sys.modules[name] = orig
        else:
            sys.modules.pop(name, None)
    return mod


core = load("lifehug_core")


class FilerScriptContractTests(unittest.TestCase):
    def setUp(self):
        self.text = FILER.read_text(encoding="utf-8")

    def test_bash_syntax_valid(self):
        result = subprocess.run(["bash", "-n", str(FILER)],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_notification_reuses_notify_not_raw_curl(self):
        # The whole point of v83: one Telegram path (env-first token,
        # group fallback, chunking) instead of a weaker reimplementation.
        self.assertIn("lifehug.py notify", self.text)
        self.assertNotIn("api.telegram.org", self.text)
        self.assertNotIn("curl", self.text)

    def test_legacy_chat_id_env_maps_to_framework_env(self):
        self.assertIn("LIFEHUG_CHAT_ID", self.text)
        self.assertIn("TELEGRAM_CHAT_ID", self.text)

    def test_filings_serialize_on_lock(self):
        self.assertIn("state/.filing.lock", self.text)
        self.assertIn("mkdir", self.text)

    def test_executable(self):
        self.assertTrue(os.access(FILER, os.X_OK))


class ResolveTelegramTargetTests(unittest.TestCase):
    """Behavior the wrapper now depends on — previously untested."""

    def _with_config(self, config_body, env):
        tmp = tempfile.NamedTemporaryFile(  # noqa: SIM115
            "w", suffix=".yaml", delete=False)
        tmp.write(config_body)
        tmp.close()
        self.addCleanup(os.unlink, tmp.name)
        missing = Path(tmp.name).with_suffix(".absent")
        with mock.patch.object(core, "PROFILE_FILE", missing), \
                mock.patch.object(core, "CONFIG_FILE", Path(tmp.name)), \
                mock.patch.dict(os.environ, env, clear=False):
            for var in ("TELEGRAM_CHAT_ID", "TELEGRAM_BOT_TOKEN"):
                if var not in env:
                    os.environ.pop(var, None)
            return core.resolve_telegram_target()

    def test_env_chat_id_overrides_config(self):
        token, chat_id = self._with_config(
            "telegram_chat_id: 111\n",
            {"TELEGRAM_CHAT_ID": "999", "TELEGRAM_BOT_TOKEN": "tok"})
        self.assertEqual(chat_id, "999")
        self.assertEqual(token, "tok")

    def test_group_chat_id_fallback(self):
        _, chat_id = self._with_config(
            "group_chat_id: -100123\n", {"TELEGRAM_BOT_TOKEN": "tok"})
        self.assertEqual(chat_id, "-100123")

    def test_telegram_chat_id_beats_group(self):
        _, chat_id = self._with_config(
            "telegram_chat_id: 111\ngroup_chat_id: -100123\n",
            {"TELEGRAM_BOT_TOKEN": "tok"})
        self.assertEqual(chat_id, "111")


if __name__ == "__main__":
    unittest.main()
