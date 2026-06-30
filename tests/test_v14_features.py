"""Tests for v14 features: quality checker, ingest, classifications, neighborhoods, focuses."""

import importlib.util
import contextlib
import io
import argparse
import json
import sys
import tempfile
import unittest
import importlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SYSTEM = ROOT / "system"
sys.path.insert(0, str(SYSTEM))


def load(name):
    spec = importlib.util.spec_from_file_location(name, SYSTEM / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class QualityCheckerTests(unittest.TestCase):
    def setUp(self):
        self.candidates = load("question_candidates")

    def test_yes_no_question_flagged(self):
        result = self.candidates.check_quality("Did you enjoy growing up there?")
        self.assertIn("yes_no_wording", result["flags"])
        self.assertLess(result["score"], 1.0)

    def test_good_scene_question_scores_high(self):
        result = self.candidates.check_quality(
            "Walk me through that day — what did the room look like when you realized things had changed?",
            source_path="answers/A1.md",
        )
        self.assertGreaterEqual(result["score"], 0.8)
        self.assertFalse(result["flags"])

    def test_too_short_question_flagged(self):
        result = self.candidates.check_quality("Why?", source_path="test.md")
        self.assertIn("too_short", result["flags"])

    def test_no_source_flagged(self):
        result = self.candidates.check_quality("What happened next?")
        self.assertIn("no_source_citation", result["flags"])

    def test_duplicate_detection(self):
        existing = [{"id": "A1", "text": "What is your earliest memory?"}]
        result = self.candidates.check_quality(
            "What is your earliest memory?",
            source_path="test.md",
            existing_questions=existing,
        )
        self.assertTrue(any("duplicate" in f for f in result["flags"]))

    def test_validate_story_function(self):
        self.assertEqual(self.candidates.validate_story_function("scene"), "scene")
        self.assertEqual(self.candidates.validate_story_function("tension"), "tension")
        self.assertIsNone(self.candidates.validate_story_function("invalid"))
        self.assertIsNone(self.candidates.validate_story_function(None))


class IngestPatternTests(unittest.TestCase):
    def setUp(self):
        self.ingest = load("ingest")

    def test_source_record_creation(self):
        record = self.ingest.SourceRecord(
            text="This is a test story about growing up in Redlands.",
            source_type="file",
            source_id="test-001",
            title="Test Story",
        )
        self.assertEqual(record.source_type, "file")
        self.assertEqual(record.dedup_key(), "file:test-001")
        d = record.to_dict()
        self.assertEqual(d["text"], "This is a test story about growing up in Redlands.")

    def test_source_record_auto_title(self):
        record = self.ingest.SourceRecord(
            text="The day I moved to California was the hardest day of my life.",
            source_type="x",
            source_id="tweet-123",
        )
        self.assertTrue(record.title)
        self.assertIn("Day", record.title)

    def test_connector_registry(self):
        connectors = self.ingest.discover_connectors()
        self.assertIn("file", connectors)
        self.assertIn("x", connectors)
        self.assertIn("email", connectors)
        self.assertIn("instagram", connectors)

    def test_generate_candidates_from_record(self):
        record = self.ingest.SourceRecord(
            text="A long story about growing up in a small town in California.",
            source_type="x",
            source_id="tweet-456",
            title="California Story",
        )
        candidates = self.ingest.generate_candidates(record, "sources/x/california-story.md")
        self.assertGreaterEqual(len(candidates), 3)
        self.assertTrue(all(c["status"] == "candidate" for c in candidates))
        self.assertTrue(all(c["source_path"] == "sources/x/california-story.md" for c in candidates))


class ClassifyStoryTests(unittest.TestCase):
    def test_module_imports(self):
        mod = load("classify_story")
        self.assertTrue(hasattr(mod, "build_prompt"))
        self.assertTrue(hasattr(mod, "main"))

    def test_classify_uses_shared_openclaw_first_ai_path(self):
        mod = load("classify_story")
        research_expand = importlib.import_module("research_expand")
        original = research_expand.call_ai
        calls = []

        def fake_call_ai(prompt, model):
            calls.append((prompt, model))
            return json.dumps({
                "people": [],
                "places": [],
                "time_periods": [],
                "themes": ["identity"],
                "projects": [],
                "contradictions": [],
                "possible_outputs": [],
                "focus_opportunities": [],
                "self_understanding_insights": [],
                "candidate_questions": [],
            })

        try:
            research_expand.call_ai = fake_call_ai
            result = mod.classify_with_ai("prompt text", "test-model")
        finally:
            research_expand.call_ai = original

        self.assertEqual(result["themes"], ["identity"])
        self.assertEqual(calls, [("prompt text", "test-model")])

    def test_dry_run_does_not_call_model_or_write(self):
        mod = load("classify_story")
        with tempfile.TemporaryDirectory() as td:
            original_dir = mod.CLASSIFICATIONS_DIR
            source = Path(td) / "story.md"
            source.write_text("# Story\n\nA meaningful memory about Dad and Arizona.\n", encoding="utf-8")
            original = mod.classify_with_ai

            def fail_if_called(*_args, **_kwargs):
                raise AssertionError("dry-run must not call the model")

            try:
                mod.CLASSIFICATIONS_DIR = Path(td) / "classifications"
                mod.classify_with_ai = fail_if_called
                buf = io.StringIO()
                with contextlib.redirect_stdout(buf):
                    rc = mod.classify_file(source, "test-model", dry_run=True)
            finally:
                mod.classify_with_ai = original
                mod.CLASSIFICATIONS_DIR = original_dir

            self.assertEqual(rc, 0)
            self.assertIn("[dry-run] would classify", buf.getvalue())
            self.assertFalse(mod.classification_path(source).exists())

    def test_classification_paths_are_repo_relative_with_legacy_compatibility(self):
        mod = load("classify_story")
        source = ROOT / "sources" / "manual" / "memory.md"
        path_names = [path.name for path in mod.classification_paths(source)]

        self.assertEqual(path_names[0], "sources-manual-memory.json")
        self.assertIn("memory.json", path_names)

    def test_legacy_classification_file_counts_as_classified(self):
        mod = load("classify_story")
        with tempfile.TemporaryDirectory() as td:
            original_dir = mod.CLASSIFICATIONS_DIR
            try:
                mod.CLASSIFICATIONS_DIR = Path(td)
                source = ROOT / "sources" / "manual" / "memory.md"
                mod.legacy_classification_path(source).write_text("{}", encoding="utf-8")
                self.assertTrue(mod.is_classified(source))
            finally:
                mod.CLASSIFICATIONS_DIR = original_dir

    def test_classify_all_limit_caps_batch(self):
        mod = load("classify_story")
        original_all = mod.all_source_files
        original_is_classified = mod.is_classified
        original_classify = mod.classify_file
        calls = []

        try:
            mod.all_source_files = lambda: [Path("a.md"), Path("b.md"), Path("c.md")]
            mod.is_classified = lambda _path: False

            def fake_classify(path, model, *, dry_run=False, verbose=False):
                calls.append((path, model, dry_run, verbose))
                return 0

            mod.classify_file = fake_classify
            args = argparse.Namespace(
                unclassified=True,
                limit=2,
                model="test-model",
                dry_run=True,
                verbose=False,
            )
            rc = mod.cmd_classify_all(args)
        finally:
            mod.all_source_files = original_all
            mod.is_classified = original_is_classified
            mod.classify_file = original_classify

        self.assertEqual(rc, 0)
        self.assertEqual([call[0] for call in calls], [Path("a.md"), Path("b.md")])


class ResearchExpandTests(unittest.TestCase):
    def test_module_imports(self):
        mod = load("research_expand")
        self.assertTrue(hasattr(mod, "main"))

    def test_gap_keywords_defined(self):
        mod = load("research_expand")
        # Should have gap detection keywords
        self.assertTrue(
            hasattr(mod, "TIME_PERIOD_KEYWORDS")
            or hasattr(mod, "FAMILY_KEYWORDS")
            or hasattr(mod, "GAP_KEYWORDS")
            or hasattr(mod, "_scan_gaps")
            or hasattr(mod, "detect_gaps")
            or hasattr(mod, "cmd_gaps")
        )


class RecommendFocusesTests(unittest.TestCase):
    def test_module_imports(self):
        mod = load("recommend_focuses")
        self.assertTrue(hasattr(mod, "main"))


class PlannerEnhancementTests(unittest.TestCase):
    def test_planner_imports_new_paths(self):
        mod = load("question_planner")
        # Should reference new state files
        source = (SYSTEM / "question_planner.py").read_text()
        self.assertIn("NEIGHBORHOODS_FILE", source)
        self.assertIn("FOCUS_RECS_FILE", source)
        self.assertIn("CLASSIFICATIONS_DIR", source)

    def test_planner_counts_path_based_and_legacy_classifications(self):
        mod = load("question_planner")
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td)
            source_dir = repo / "sources" / "manual"
            classification_dir = repo / "state" / "classifications"
            source_dir.mkdir(parents=True)
            classification_dir.mkdir(parents=True)
            (source_dir / "memory.md").write_text("story", encoding="utf-8")

            original_repo = mod.REPO_DIR
            original_sources = mod.SOURCES_DIR
            original_classifications = mod.CLASSIFICATIONS_DIR
            try:
                mod.REPO_DIR = repo
                mod.SOURCES_DIR = repo / "sources"
                mod.CLASSIFICATIONS_DIR = classification_dir

                (classification_dir / "sources-manual-memory.json").write_text("{}", encoding="utf-8")
                self.assertEqual(mod._count_classified("manual"), 1)

                (classification_dir / "sources-manual-memory.json").unlink()
                (classification_dir / "memory.json").write_text("{}", encoding="utf-8")
                self.assertEqual(mod._count_classified("manual"), 1)
            finally:
                mod.REPO_DIR = original_repo
                mod.SOURCES_DIR = original_sources
                mod.CLASSIFICATIONS_DIR = original_classifications


class LifehugWrapperTests(unittest.TestCase):
    def test_new_commands_registered(self):
        mod = load("lifehug")
        parser = mod.build_parser()
        # Check that new commands are in the parser
        subparsers_actions = [
            action
            for action in parser._subparsers._actions
            if isinstance(action, type(parser._subparsers._actions[0]))
        ]
        # Get all command names from help text
        help_text = parser.format_help()
        for cmd in [
            "classify-story",
            "research-expand",
            "recommend-focuses",
            "focus-approve",
            "focus-dismiss",
            "ingest",
            "candidates-stats",
        ]:
            self.assertIn(cmd, help_text, f"Command '{cmd}' not found in parser")


if __name__ == "__main__":
    unittest.main()
