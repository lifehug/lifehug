"""v92 — keyless agent mode reaches the maintenance Loop (issue #38).

Every AI module already had a keyless agent path; the weekly/monthly
orchestrators never routed to them. These tests pin: ai_available() route
detection, classify_story --emit-prompts batch emission (prompts + manifest),
the lifehug.py wrapper passthrough, and the shell orchestrators' keyless
contract (emit tasks, don't record raw failures on the happy path).
"""

import importlib.util
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SYSTEM = ROOT / "system"
sys.path.insert(0, str(SYSTEM))


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


re_mod = load("research_expand")
cs = load("classify_story")
lh = load("lifehug")


SOURCE_MD = """---
type: "prompted_answer"
question_id: "A1"
---

# Question A1: What's your earliest memory?

Running through the orange grove behind Grandma's house in Mesa.
"""


class AiAvailableTests(unittest.TestCase):
    def test_keyless_when_no_gateway_no_key_no_config(self):
        with mock.patch.object(re_mod, "_openclaw_gateway", return_value=None), \
             mock.patch.dict(re_mod.os.environ, {}, clear=True), \
             mock.patch.object(re_mod, "load_config", return_value={}):
            self.assertIsNone(re_mod.ai_available())

    def test_gateway_wins(self):
        with mock.patch.object(re_mod, "_openclaw_gateway",
                               return_value=("http://localhost:18789/v1", "tok")):
            self.assertEqual(re_mod.ai_available(), "gateway")

    def test_env_key_detected(self):
        with mock.patch.object(re_mod, "_openclaw_gateway", return_value=None), \
             mock.patch.dict(re_mod.os.environ, {"ANTHROPIC_API_KEY": "sk-test"}, clear=True):
            self.assertEqual(re_mod.ai_available(), "sdk-key")

    def test_config_key_detected(self):
        with mock.patch.object(re_mod, "_openclaw_gateway", return_value=None), \
             mock.patch.dict(re_mod.os.environ, {}, clear=True), \
             mock.patch.object(re_mod, "load_config",
                               return_value={"anthropic_api_key": "sk-test"}):
            self.assertEqual(re_mod.ai_available(), "sdk-key")

    def test_config_read_failure_means_keyless_not_crash(self):
        with mock.patch.object(re_mod, "_openclaw_gateway", return_value=None), \
             mock.patch.dict(re_mod.os.environ, {}, clear=True), \
             mock.patch.object(re_mod, "load_config", side_effect=OSError("boom")):
            self.assertIsNone(re_mod.ai_available())


class AiStatusCommandTests(unittest.TestCase):
    def test_exit_codes(self):
        # cmd_ai_status resolves research_expand through sys.modules at call
        # time — patch the live module, not this file's import-time reference
        # (another test file may have reloaded it since).
        re_live = sys.modules["research_expand"]
        with mock.patch.object(re_live, "ai_available", return_value="gateway"):
            self.assertEqual(lh.cmd_ai_status(None), 0)
        with mock.patch.object(re_live, "ai_available", return_value=None):
            self.assertEqual(lh.cmd_ai_status(None), 1)

    def test_missing_optional_sdk_reports_keyless(self):
        re_live = sys.modules["research_expand"]
        with mock.patch.object(re_live, "_openclaw_gateway", return_value=None), \
             mock.patch.dict(re_live.os.environ, {"ANTHROPIC_API_KEY": "synthetic-key"}, clear=True), \
             mock.patch.object(re_live, "load_config", return_value={}), \
             mock.patch.object(re_live, "_anthropic_sdk_available", return_value=False), \
             mock.patch("sys.stdout") as stdout:
            self.assertEqual(lh.cmd_ai_status(None), 1)
        self.assertIn("keyless", "".join(
            call.args[0] for call in stdout.write.call_args_list
        ))


class EmitPromptsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: shutil.rmtree(self.tmp, ignore_errors=True))
        self.src_a = self.tmp / "A1.md"
        self.src_a.write_text(SOURCE_MD, encoding="utf-8")
        self.src_b = self.tmp / "B2.md"
        self.src_b.write_text(SOURCE_MD.replace("A1", "B2"), encoding="utf-8")
        self.out = self.tmp / "tasks"

    def test_emits_one_prompt_per_source_plus_manifest(self):
        rc = cs.emit_prompts([self.src_a, self.src_b], self.out)
        self.assertEqual(rc, 0)
        manifest = json.loads((self.out / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["task"], "classify")
        self.assertIn("--from-response", manifest["ingest_command"])
        self.assertEqual(len(manifest["items"]), 2)
        for item in manifest["items"]:
            prompt_file = self.out / item["prompt"]
            self.assertTrue(prompt_file.exists())
            self.assertIn("candidate_questions", prompt_file.read_text(encoding="utf-8"))
            self.assertTrue(item["response"].endswith(".response.json"))
            self.assertNotEqual(item["prompt"], item["response"])

    def test_empty_body_source_is_skipped_not_fatal(self):
        empty = self.tmp / "empty.md"
        empty.write_text("---\ntype: x\n---\n", encoding="utf-8")
        rc = cs.emit_prompts([self.src_a, empty], self.out)
        self.assertEqual(rc, 0)
        manifest = json.loads((self.out / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(len(manifest["items"]), 1)

    def test_classify_all_dispatches_to_emit_prompts(self):
        parser = cs.build_parser()
        args = parser.parse_args(
            ["--classify-all", "--unclassified", "--emit-prompts", str(self.out)]
        )
        with mock.patch.object(cs, "all_source_files",
                               return_value=[self.src_a, self.src_b]), \
             mock.patch.object(cs, "is_classified", return_value=False):
            rc = cs.cmd_classify_all(args)
        self.assertEqual(rc, 0)
        self.assertTrue((self.out / "manifest.json").exists())

    def test_no_pending_sources_short_circuits_before_emission(self):
        parser = cs.build_parser()
        args = parser.parse_args(
            ["--classify-all", "--unclassified", "--emit-prompts", str(self.out)]
        )
        with mock.patch.object(cs, "all_source_files", return_value=[self.src_a]), \
             mock.patch.object(cs, "is_classified", return_value=True):
            rc = cs.cmd_classify_all(args)
        self.assertEqual(rc, 0)
        self.assertFalse(self.out.exists())


class WrapperPassthroughTests(unittest.TestCase):
    def _flags_for(self, argv):
        parser = lh.build_parser()
        args = parser.parse_args(argv)
        captured = {}
        with mock.patch.object(lh, "run_python",
                               side_effect=lambda script, flags: captured.setdefault("flags", flags) or 0):
            args.func(args)
        return captured["flags"]

    def test_emit_prompts_passthrough(self):
        flags = self._flags_for([
            "classify-story", "--classify-all", "--unclassified",
            "--emit-prompts", "state/agent_tasks/classify", "--limit", "5",
        ])
        self.assertIn("--emit-prompts", flags)
        self.assertIn("state/agent_tasks/classify", flags)
        self.assertIn("--unclassified", flags)

    def test_from_response_passthrough(self):
        flags = self._flags_for([
            "classify-story", "--from-response", "resp.json", "--source", "answers/A1.md",
        ])
        self.assertEqual(flags[:4], ["--from-response", "resp.json", "--source", "answers/A1.md"])


class OrchestratorContractTests(unittest.TestCase):
    """The shell scripts' keyless contract, pinned the same way v86 pinned the
    report contract: the guard exists, routes to task emission, and the happy
    keyless path is a ⏸ pause, not a recorded failure."""

    weekly = (SYSTEM / "weekly_maintenance.sh").read_text(encoding="utf-8")
    monthly = (SYSTEM / "monthly_research.sh").read_text(encoding="utf-8")

    def test_weekly_checks_ai_status_and_emits(self):
        self.assertIn("ai-status", self.weekly)
        self.assertIn('--emit-prompts "$AGENT_TASKS_DIR/classify"', self.weekly)
        self.assertIn("⏸ keyless", self.weekly)

    def test_weekly_keyless_failure_is_distinct_operation(self):
        # Emission failures record under their own operation name so a broken
        # emit path is distinguishable from a broken AI call.
        self.assertIn("classify_story_emit", self.weekly)

    def test_monthly_checks_ai_status_and_emits_roster_tasks(self):
        self.assertIn("ai-status", self.monthly)
        self.assertIn('--emit-task "$AGENT_TASKS_DIR/roster/${etype}.json"', self.monthly)
        self.assertIn("⏸ keyless", self.monthly)

    def test_monthly_keyless_never_runs_keyed_roster_refresh_blind(self):
        # The keyless branch must gate the plain refresh (which would fall to
        # the deterministic roster — the v90 junk-roster lesson).
        self.assertIn('if [[ "$KEYLESS" == "1" ]]', self.monthly)

    def test_monthly_research_prompts_emitted_keyless(self):
        self.assertIn('$AGENT_TASKS_DIR/research', self.monthly)
        self.assertIn("--from-response", self.monthly)


if __name__ == "__main__":
    unittest.main()
