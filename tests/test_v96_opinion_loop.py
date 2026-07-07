"""v96: classifier opinion addendum + self-arc integration."""

import importlib.util
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


class ClassifierOpinionTests(unittest.TestCase):
    def setUp(self):
        self.classify = load("classify_story")

    def _prompt(self, source_type):
        fm = {"title": "The Mantle", "type": source_type, "captured_at": "2026-07-06"}
        return self.classify.build_prompt(
            Path("sources/manual/2026-07-06-the-mantle.md"), fm,
            "Parents wore a mantle of responsibility.")

    def test_opinion_prompt_contains_addendum(self):
        prompt = self._prompt("opinion")
        self.assertIn("OPINION ADDENDUM", prompt)
        self.assertIn('prefixed with "position: "', prompt)
        self.assertIn("SOCRATIC", prompt)

    def test_non_opinion_prompt_baseline_identical(self):
        story_prompt = self._prompt("unprompted_story")
        self.assertNotIn("OPINION ADDENDUM", story_prompt)
        # the addendum is a pure suffix: the opinion prompt minus the addendum
        # equals a prompt whose only difference is the Type: line
        opinion_prompt = self._prompt("opinion")
        prefix = opinion_prompt.split("### OPINION ADDENDUM")[0]
        self.assertEqual(
            prefix.replace("Type: opinion", "Type: unprompted_story").rstrip("\n"),
            story_prompt.rstrip("\n"))

    def test_build_classification_passes_position_insights(self):
        ai_result = {
            "people": [], "places": [], "time_periods": [], "themes": ["family"],
            "projects": [], "contradictions": [],
            "possible_outputs": [], "focus_opportunities": [],
            "self_understanding_insights": [
                "position: parents who wore the mantle deserve gratitude",
            ],
            "candidate_questions": [],
        }
        record = self.classify.build_classification(
            Path("sources/manual/2026-07-06-the-mantle.md"),
            {"title": "The Mantle", "type": "opinion"}, ai_result,
            model="test", classified_at="2026-07-06T00:00:00Z", candidate_ids=[])
        insights = record.get("self_understanding_insights")
        self.assertEqual(len(insights), 1)
        self.assertTrue(insights[0].startswith("position: "))


class SelfArcGroundingTests(unittest.TestCase):
    def test_positions_reach_self_signals(self):
        research = load("research_expand")
        import lifehug_core
        with tempfile.TemporaryDirectory() as td:
            cls_dir = Path(td) / "classifications"
            cls_dir.mkdir()
            (cls_dir / "the-mantle.json").write_text(json.dumps({
                "self_understanding_insights": [
                    "position: parents who wore the mantle deserve gratitude",
                ],
                "contradictions": ["grieves the reversion he argues we should honor"],
            }))
            original = lifehug_core.CLASSIFICATIONS_DIR
            lifehug_core.CLASSIFICATIONS_DIR = cls_dir
            try:
                signals = research.load_classified_self_signals()
            finally:
                lifehug_core.CLASSIFICATIONS_DIR = original
        joined = "\n".join(signals)
        self.assertIn("position: parents who wore the mantle", joined)
        self.assertIn("[contradiction]", joined)


class CrossModuleContractTests(unittest.TestCase):
    def test_opinion_candidate_story_functions_are_planner_self_functions(self):
        """The weekly planner's self-knowledge floor selects by SELF_FUNCTIONS;
        opinion ingest candidates must stay inside that vocabulary or they
        silently drop out of the weekly Loop."""
        ingest = load("ingest_story")
        from question_planner import SELF_FUNCTIONS
        candidates = ingest.generate_opinion_candidates(
            "t", "sources/manual/t.md", "2026-07-06T00:00:00Z")
        for candidate in candidates:
            self.assertIn(candidate["story_function"], SELF_FUNCTIONS)

    def test_self_focus_maps_to_wiki_dir(self):
        roadmap = load("roadmap")
        self.assertEqual(roadmap.TYPE_TO_WIKI_DIR.get("self"), "self")


if __name__ == "__main__":
    unittest.main()
