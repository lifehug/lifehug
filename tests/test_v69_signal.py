"""v69 — Stop the signal bleed: unified story-function vocabulary, focus
attribution, classifier-field consumers, group-cap enforcement."""

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


core = load("lifehug_core")
qp = load("question_planner")
qprof = load("quality_profile")
rf = load("recommend_focuses")
re_mod = load("research_expand")


class VocabularyTests(unittest.TestCase):
    def test_legacy_names_normalize(self):
        self.assertEqual(qprof.canonical_story_function("origin_story"), "foundation")
        self.assertEqual(qprof.canonical_story_function("stakes_and_risk"), "tension")
        self.assertEqual(qprof.canonical_story_function("scene"), "scene")
        self.assertEqual(qprof.canonical_story_function(None), "unknown")

    def test_profile_inference_uses_planner_classifier(self):
        # The profile's classifier must emit ONLY canonical vocabulary now.
        samples = [
            "Tell me about your first job and what it taught you",
            "Who was your closest friend growing up?",
            "Walk me through the moment everything changed",
            "What are you most afraid of becoming?",
        ]
        for text in samples:
            fn = qprof._infer_story_function(text)
            self.assertIn(fn, core.STORY_FUNCTIONS, f"{text!r} → {fn}")

    def test_aggregate_merges_legacy_buckets(self):
        scores = [
            {"story_function": "origin_story", "richness_score": 0.8},
            {"story_function": "foundation", "richness_score": 0.6},
            {"story_function": "stakes_and_risk", "richness_score": 0.5},
        ]
        agg = qprof._aggregate(scores, "story_function")
        self.assertNotIn("origin_story", agg)
        self.assertNotIn("stakes_and_risk", agg)
        self.assertEqual(agg["foundation"]["count"], 2)  # legacy merged in
        self.assertEqual(agg["tension"]["count"], 1)

    def test_planner_keywords_contain_no_user_names(self):
        for keywords in qp.STORY_FUNCTION_KEYWORDS.values():
            self.assertNotIn("katie", keywords)
            self.assertNotIn("aj", keywords)


class FocusAttributionTests(unittest.TestCase):
    def test_focus_for_category_reads_roadmap(self):
        with tempfile.TemporaryDirectory() as d:
            roadmap_file = Path(d) / "roadmap.json"
            core.write_json(roadmap_file, {"version": 1, "focuses": [
                {"id": "mom", "categories": ["K"]},
                {"id": "etherfuse", "categories": ["F", "G"]},
            ]})
            import roadmap as roadmap_mod
            orig = roadmap_mod.ROADMAP_FILE
            roadmap_mod.ROADMAP_FILE = roadmap_file
            try:
                self.assertEqual(qprof.focus_for_category("K"), "mom")
                self.assertEqual(qprof.focus_for_category("G"), "etherfuse")
                self.assertIsNone(qprof.focus_for_category("Z"))
            finally:
                roadmap_mod.ROADMAP_FILE = orig

    def test_wiki_nodes_added_weight_retired(self):
        self.assertEqual(qprof.WEIGHTS_LIVE["wiki_nodes_added"], 0.0)
        self.assertAlmostEqual(sum(qprof.WEIGHTS_LIVE.values()), 1.0)


class ClassifierConsumerTests(unittest.TestCase):
    def test_focus_opportunities_feed_entity_stats(self):
        stats = rf._build_entity_stats({}, {}, [{
            "question_id": "A1",
            "people": [], "places": [], "themes": [],
            "focus_opportunities": [
                {"entity": "The Bankruptcy", "type": "theme",
                 "evidence_strength": "strong", "reason": "anchors the redemption arc"},
            ],
        }])
        self.assertIn(("theme", "The Bankruptcy"), stats)
        entry = stats[("theme", "The Bankruptcy")]
        self.assertGreaterEqual(entry["emotional_weight"], 3.0)  # strong boost
        self.assertTrue(any("classifier: strong" in e for e in entry["evidence"]))

    def test_self_signals_loaded_from_classifications(self):
        with tempfile.TemporaryDirectory() as d:
            clf_dir = Path(d) / "classifications"
            clf_dir.mkdir()
            (clf_dir / "A1.json").write_text(json.dumps({
                "contradictions": ["Claims self-sufficiency but names four rescuers"],
                "self_understanding_insights": [{"description": "Money = safety, not status"}],
            }), encoding="utf-8")
            # load_classified_self_signals resolves lifehug_core via sys.modules
            # at call time; later test files reload the module, so patch there.
            live_core = sys.modules["lifehug_core"]
            orig = live_core.CLASSIFICATIONS_DIR
            live_core.CLASSIFICATIONS_DIR = clf_dir
            try:
                signals = re_mod.load_classified_self_signals()
            finally:
                live_core.CLASSIFICATIONS_DIR = orig
            self.assertEqual(len(signals), 2)
            self.assertTrue(any(s.startswith("[contradiction]") for s in signals))
            self.assertTrue(any("Money = safety" in s for s in signals))

    def test_self_signals_render_in_prompt(self):
        prompt = re_mod.build_expansion_prompt(
            topic="Who I am becoming", topic_type="self", target_output="essay",
            mission="", source_content="", relevant_answers=[],
            question_bank_categories="",
            self_signals=["[contradiction] Claims self-sufficiency but names four rescuers"],
        )
        self.assertIn("OBSERVED PATTERNS IN THIS AUTHOR", prompt)
        self.assertIn("four rescuers", prompt)

    def test_no_signals_no_section(self):
        prompt = re_mod.build_expansion_prompt(
            topic="Yucaipa", topic_type="place", target_output="chapter",
            mission="", source_content="", relevant_answers=[],
            question_bank_categories="", self_signals=None,
        )
        self.assertNotIn("OBSERVED PATTERNS IN THIS AUTHOR", prompt)


class RecommendationDedupeTests(unittest.TestCase):
    def test_existing_wiki_page_slugs_scanned(self):
        with tempfile.TemporaryDirectory() as d:
            wiki = Path(d)
            (wiki / "themes").mkdir()
            (wiki / "themes" / "money.md").write_text("x", encoding="utf-8")
            (wiki / "people").mkdir()
            (wiki / "people" / "betty-jo.md").write_text("x", encoding="utf-8")
            orig = rf.WIKI_DIR
            rf.WIKI_DIR = wiki
            try:
                slugs = rf._existing_wiki_page_slugs()
            finally:
                rf.WIKI_DIR = orig
            self.assertEqual(slugs, {"money", "betty-jo"})


class GroupCapTests(unittest.TestCase):
    def test_source_type_caps_removed_from_defaults(self):
        state = qp.default_planner_state()
        self.assertNotIn("source_type", state["caps"])
        self.assertIn("group", state["caps"])
        self.assertIn("story_function", state["caps"])


if __name__ == "__main__":
    unittest.main()
