import importlib.util
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SYSTEM = ROOT / "system"
sys.path.insert(0, str(SYSTEM))


def load(name):
    spec = importlib.util.spec_from_file_location(name, SYSTEM / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class IngestStoryTests(unittest.TestCase):
    def test_title_from_text_uses_first_words(self):
        ingest = load("ingest_story")
        self.assertEqual(
            ingest.title_from_text("redlands was where the story really started for me"),
            "Redlands Was Where The Story Really Started For",
        )

    def test_generate_candidates_uses_source_path(self):
        ingest = load("ingest_story")
        candidates = ingest.generate_candidates(
            "Redlands Memory",
            "This is a story about money, family, and growing up.",
            "sources/manual/2026-01-01-redlands-memory.md",
            "2026-01-01T00:00:00Z",
        )
        self.assertGreaterEqual(len(candidates), 4)
        self.assertTrue(all(c["source_path"].startswith("sources/manual/") for c in candidates))
        self.assertTrue(all(c["status"] == "candidate" for c in candidates))


class PlannerTests(unittest.TestCase):
    def test_qid_key_sorts_suffixes_after_base_number(self):
        planner = load("question_planner")
        self.assertLess(planner.qid_key("A14"), planner.qid_key("A14a"))

    def test_story_function_detects_scene_questions(self):
        planner = load("question_planner")
        self.assertEqual(
            planner.infer_story_function("Walk me through that day. What did the room look like?"),
            "scene",
        )

    def test_queue_stale_detection_uses_expiry(self):
        planner = load("question_planner")
        self.assertTrue(planner.queue_is_stale({
            "queue": [{"question_id": "A1"}],
            "expires_at": "2000-01-01T00:00:00Z",
        }))


class CandidateManagerTests(unittest.TestCase):
    def test_promote_candidate_appends_next_question_and_preserves_provenance(self):
        candidates = load("question_candidates")
        bank = (
            "# Lifehug — Question Bank\n\n"
            "## A: Origins\n"
            "- [x] A1: Existing answered question *(2026-01-01)*\n"
            "- [ ] A2: Existing open question\n\n"
            "## B: Becoming\n"
            "- [ ] B1: Another question\n"
        )
        store = {
            "version": 1,
            "candidates": [{
                "id": "cand-redlands-1",
                "text": "What did the room look like when you realized things had changed?",
                "source_path": "sources/manual/redlands.md",
                "status": "accepted",
                "priority": 0.8,
            }],
        }
        updated, question_id = candidates.promote_candidate_record(store, bank, "cand-redlands-1", "A")
        self.assertEqual(question_id, "A3")
        self.assertIn("- [ ] A3: What did the room look like", updated)
        self.assertIn("candidate: cand-redlands-1", updated)
        self.assertIn("source: sources/manual/redlands.md", updated)
        self.assertEqual(store["candidates"][0]["status"], "promoted")
        self.assertEqual(store["candidates"][0]["promoted_question_id"], "A3")

    def test_promote_candidate_rejects_duplicate_question_text(self):
        candidates = load("question_candidates")
        bank = (
            "## A: Origins\n"
            "- [ ] A1: What did the room look like when you realized things had changed?\n"
        )
        store = {
            "version": 1,
            "candidates": [{
                "id": "cand-duplicate",
                "text": "What did the room look like when you realized things had changed?",
                "source_path": "sources/manual/redlands.md",
                "status": "candidate",
            }],
        }
        with self.assertRaises(ValueError):
            candidates.promote_candidate_record(store, bank, "cand-duplicate", "A")
        self.assertEqual(store["candidates"][0]["status"], "candidate")


if __name__ == "__main__":
    unittest.main()
