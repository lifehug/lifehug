import contextlib
import importlib.util
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path


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


class NeighborhoodReadinessTests(unittest.TestCase):
    def setUp(self):
        self.neighborhoods = load("neighborhoods")

    def test_candidate_only_arc_is_not_draft_ready(self):
        neighborhood = {
            "arc": [
                {"story_function": "self_image", "question_id": "cand-self-1"},
                {"story_function": "value", "question_id": "cand-self-2"},
            ],
        }
        candidates = {
            "candidates": [
                {"id": "cand-self-1"},
                {"id": "cand-self-2"},
            ],
        }

        result = self.neighborhoods.apply_readiness(neighborhood, candidates, [])

        self.assertEqual(result["question_arc_completeness"], 1.0)
        self.assertEqual(result["promoted_completeness"], 0.0)
        self.assertEqual(result["answered_completeness"], 0.0)
        self.assertFalse(result["ready_to_draft"])
        self.assertEqual(result["readiness_status"], "questions_generated")

    def test_promoted_questions_are_not_answer_ready_until_answered(self):
        neighborhood = {
            "arc": [
                {"story_function": "self_image", "question_id": "cand-self-1"},
                {"story_function": "value", "question_id": "cand-self-2"},
            ],
        }
        candidates = {
            "candidates": [
                {"id": "cand-self-1", "promoted_question_id": "E20"},
                {"id": "cand-self-2", "promoted_question_id": "E21"},
            ],
        }
        questions = [
            {"id": "E20", "answered": False},
            {"id": "E21", "answered": False},
        ]

        result = self.neighborhoods.apply_readiness(neighborhood, candidates, questions)

        self.assertEqual(result["promoted_completeness"], 1.0)
        self.assertEqual(result["answered_completeness"], 0.0)
        self.assertFalse(result["ready_to_draft"])
        self.assertEqual(result["readiness_status"], "promoted")

    def test_answered_material_controls_draft_readiness(self):
        arc = [
            {"story_function": f"slot_{i}", "question_id": f"cand-self-{i}"}
            for i in range(1, 7)
        ]
        candidates = {
            "candidates": [
                {"id": f"cand-self-{i}", "promoted_question_id": f"E{i}"}
                for i in range(1, 7)
            ],
        }
        questions = [
            {"id": f"E{i}", "answered": i <= 5}
            for i in range(1, 7)
        ]

        result = self.neighborhoods.apply_readiness({"arc": arc}, candidates, questions)

        self.assertEqual(result["arc_lifecycle_counts"]["answers_captured"], 5)
        self.assertEqual(result["answered_completeness"], 0.833)
        self.assertTrue(result["ready_to_draft"])
        self.assertEqual(result["readiness_status"], "answer_ready")


class ProgressReadinessTests(unittest.TestCase):
    def test_progress_does_not_mark_candidate_only_neighborhood_ready(self):
        progress = load("progress")
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            bank = root / "question-bank.md"
            candidates = root / "question_candidates.json"
            neighborhoods = root / "neighborhoods.json"
            bank.write_text(
                "# Bank\n\n"
                "## E: Reflection\n"
                "- [ ] E1: Who are you becoming?\n",
                encoding="utf-8",
            )
            candidates.write_text(json.dumps({
                "version": 1,
                "candidates": [{"id": "cand-self-1"}],
            }), encoding="utf-8")
            neighborhoods.write_text(json.dumps({
                "version": 1,
                "neighborhoods": [{
                    "title": "Who I am becoming",
                    "type": "self",
                    "target_output": "essay",
                    "arc": [{"story_function": "self_image", "question_id": "cand-self-1"}],
                }],
            }), encoding="utf-8")

            original_bank = progress.QUESTIONS_FILE
            original_candidates = progress.QUESTION_CANDIDATES_FILE
            original_neighborhoods = progress.NEIGHBORHOODS_FILE
            original_load_roadmap = progress.load_roadmap
            original_rebuild_roadmap = progress.rebuild_roadmap
            try:
                progress.QUESTIONS_FILE = bank
                progress.QUESTION_CANDIDATES_FILE = candidates
                progress.NEIGHBORHOODS_FILE = neighborhoods
                progress.load_roadmap = lambda: {"focuses": []}
                progress.rebuild_roadmap = lambda write=False: {"focuses": []}

                out = io.StringIO()
                with contextlib.redirect_stdout(out):
                    rc = progress.run()
            finally:
                progress.QUESTIONS_FILE = original_bank
                progress.QUESTION_CANDIDATES_FILE = original_candidates
                progress.NEIGHBORHOODS_FILE = original_neighborhoods
                progress.load_roadmap = original_load_roadmap
                progress.rebuild_roadmap = original_rebuild_roadmap

        self.assertEqual(rc, 0)
        text = out.getvalue()
        self.assertIn("0% answer-ready", text)
        self.assertIn("questions generated", text)
        self.assertNotIn("← ready to draft", text)


if __name__ == "__main__":
    unittest.main()
