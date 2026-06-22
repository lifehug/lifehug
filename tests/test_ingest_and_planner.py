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


if __name__ == "__main__":
    unittest.main()
