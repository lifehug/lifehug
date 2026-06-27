import importlib.util
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SYSTEM = ROOT / "system"
sys.path.insert(0, str(SYSTEM))


def load_wrapper():
    spec = importlib.util.spec_from_file_location("lifehug", SYSTEM / "lifehug.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class LifehugWrapperTests(unittest.TestCase):
    def test_parser_accepts_canonical_commands(self):
        mod = load_wrapper()
        parser = mod.build_parser()
        for command in [
            ["status"],
            ["next"],
            ["compile", "--dry-run"],
            ["source-scan"],
            ["source-manifest", "--rebuild"],
            ["source-lint", "--fix", "--no-write-findings"],
            ["source-findings"],
            ["correct-source", "answers/A1.md", "--kind", "factual"],
            ["reflect-source", "answers/A1.md"],
            ["ingest-story", "--source", "telegram", "--title", "A Story"],
            ["candidates-list", "--status", "candidate", "--limit", "10"],
            ["candidates-review", "--source", "manual"],
            ["candidates-update", "cand-1", "--status", "accepted", "--target-category", "A"],
            ["candidates-promote", "cand-1", "--category", "A"],
            ["planner-report", "--limit", "5"],
            ["planner-queue", "--limit", "7", "--arc-max", "2", "--expires-days", "5"],
            ["planner-clear"],
            ["planner-state", "--init"],
            ["planner-objective-add", "Prepare Mom letter", "--category", "K", "--keyword", "mom"],
            ["planner-objective-clear"],
            ["serve", "--port", "8765"],
            ["rebuild"],
            ["process-answer", "A1", "--source", "text"],
            ["daily-dry-run"],
            ["weekly-maintenance", "--dry-run"],
            ["monthly-research", "--dry-run", "--gap-limit", "2", "--self-topic", "Who I am becoming", "--spotlight-min-score", "15"],
            ["followups-status"],
            ["followups-prompt"],
            ["doctor", "--daily"],
        ]:
            with self.subTest(command=command):
                args = parser.parse_args(command)
                self.assertTrue(callable(args.func))

    def test_telegram_target_detection_uses_config_or_env(self):
        mod = load_wrapper()
        self.assertTrue(mod.has_telegram_target({"telegram_chat_id": "123"}))
        self.assertTrue(mod.has_telegram_target({"group_chat_id": "-100123"}))
        self.assertFalse(mod.has_telegram_target({}))


if __name__ == "__main__":
    unittest.main()
