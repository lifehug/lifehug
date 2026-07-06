"""v90 — the AJ regression: classification stats must credit real answers
(qid from source_path, dict/str entries handled), and a role-word roster
canonical (Brother) must yield to the person's proper name (AJ)."""

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
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


rf = load("recommend_focuses")
er = load("entity_roster")


class ClassificationStatsTests(unittest.TestCase):
    def test_qid_derived_from_source_path(self):
        # Classification files identify their source only by source_path —
        # without deriving the qid from it, every classification-derived
        # entity accrues zero unique_answers and never clears the roster gate.
        stats = rf._build_entity_stats({}, [], [
            {"source_path": "answers/C1.md", "people": [{"name": "AJ"}]},
            {"source_path": "answers/D3.md", "people": [{"name": "AJ"}]},
        ])
        entry = stats[("person", "AJ")]
        self.assertEqual(entry["answers"], {"C1", "D3"})
        self.assertEqual(entry["categories"], {"C", "D"})

    def test_explicit_question_id_still_wins(self):
        stats = rf._build_entity_stats({}, [], [
            {"question_id": "B2", "source_path": "answers/C1.md",
             "people": [{"name": "AJ"}]},
        ])
        self.assertEqual(stats[("person", "AJ")]["answers"], {"B2"})

    def test_dict_entries_are_recorded_not_skipped(self):
        # Regression: `x.get("name") or x if isinstance(x, str) else None`
        # parsed as a conditional over the whole expression, so dict entries
        # yielded None and were silently dropped.
        stats = rf._build_entity_stats({}, [], [
            {"source_path": "answers/A1.md",
             "people": [{"name": "AJ", "relationship": "brother"}],
             "places": [{"name": "Arizona"}],
             "themes": [{"name": "loyalty"}]},
        ])
        self.assertIn(("person", "AJ"), stats)
        self.assertIn(("place", "Arizona"), stats)
        self.assertIn(("theme", "loyalty"), stats)

    def test_string_entries_do_not_crash(self):
        # Regression: the same precedence bug made plain-string entries call
        # .get() and crash the whole recommend-focuses run (swallowed by
        # `|| true` in monthly_research.sh since the 2026-07-04 backfill).
        stats = rf._build_entity_stats({}, [], [
            {"source_path": "answers/A1.md",
             "people": ["AJ"], "places": ["Arizona"], "themes": ["loyalty"]},
        ])
        self.assertIn(("person", "AJ"), stats)
        self.assertIn(("theme", "loyalty"), stats)

    def test_manual_source_classification_keeps_qid_none(self):
        stats = rf._build_entity_stats({}, [], [
            {"source_path": "sources/manual/2026-07-01-story.md",
             "people": [{"name": "AJ"}]},
        ])
        entry = stats[("person", "AJ")]
        self.assertEqual(entry["mention_count"], 1)
        self.assertEqual(entry["answers"], set())  # no fabricated answer ids

    def test_two_letter_name_scores_past_person_thresholds(self):
        # The end-to-end arithmetic that buried AJ: enough classified answers
        # must clear the person page bar (score >= 8, answers >= 2).
        clfs = [{"source_path": f"answers/{q}.md", "people": [{"name": "AJ"}]}
                for q in ("C1", "C6", "C7", "D3", "G1")]
        entry = rf._build_entity_stats({}, [], clfs)[("person", "AJ")]
        self.assertGreaterEqual(rf._score(entry), 8.0)
        self.assertGreaterEqual(len(entry["answers"]), 2)


PREV_WITH_BROTHER = {"entities": [
    {"name": "Brother", "slug": "brother", "aliases": [], "qualifies": False,
     "maps_to_focus": None, "score": 16.0, "unique_answers": 3, "page_eligible": False},
    {"name": "Grandma Betty Jo", "slug": "grandma-betty-jo",
     "aliases": ["Grandma", "Betty Jo"], "qualifies": True,
     "maps_to_focus": None, "score": 46.0, "unique_answers": 8, "page_eligible": True},
]}


class RoleWordPromotionTests(unittest.TestCase):
    def test_role_word_canonical_promotes_to_proper_name(self):
        # The lock-in regression: once "Brother" was the settled canonical,
        # a resolved "AJ" was renamed back to "Brother" forever.
        out, _ = er.apply_previous_decisions([
            {"name": "AJ", "aliases": ["Brother", "AJ Taylor"], "qualifies": True,
             "maps_to_focus": None},
        ], PREV_WITH_BROTHER)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["name"], "AJ")
        self.assertIn("brother", [a.lower() for a in out[0]["aliases"]])
        self.assertNotIn("aj", [a.lower() for a in out[0]["aliases"]])

    def test_promoted_entry_normalizes_to_proper_slug(self):
        out, _ = er.apply_previous_decisions([
            {"name": "AJ", "aliases": ["Brother"], "qualifies": True,
             "maps_to_focus": None},
        ], PREV_WITH_BROTHER)
        people = er.normalize("person", out, [
            {"entity": "AJ", "score": 52.0, "unique_answers": 10,
             "cross_categories": ["B", "C", "D", "G", "H", "I"], "evidence": []},
        ], {}, min_score=8, min_answers=2)
        self.assertEqual(people[0]["slug"], "aj")
        self.assertTrue(people[0]["page_eligible"])

    def test_role_word_raw_still_folds_to_role_word(self):
        # No proper name on offer -> the settled role-word decision holds.
        out, _ = er.apply_previous_decisions([
            {"name": "Brother", "aliases": [], "qualifies": False,
             "maps_to_focus": None},
        ], PREV_WITH_BROTHER)
        self.assertEqual(out[0]["name"], "Brother")

    def test_proper_name_canonical_is_never_renamed(self):
        # Promotion is role-word-only; real-name slugs stay stable (v67 core).
        out, _ = er.apply_previous_decisions([
            {"name": "Betty Jo", "aliases": [], "qualifies": True,
             "maps_to_focus": None},
        ], PREV_WITH_BROTHER)
        self.assertEqual(out[0]["name"], "Grandma Betty Jo")

    def test_collapsed_slot_upgrades_when_proper_name_arrives_second(self):
        # Even if the AI wrongly re-splits (Brother + AJ), the fold collapses
        # them into ONE entry and the proper name wins the canonical.
        out, _ = er.apply_previous_decisions([
            {"name": "Brother", "aliases": [], "qualifies": False,
             "maps_to_focus": None},
            {"name": "AJ", "aliases": ["Brother"], "qualifies": True,
             "maps_to_focus": None},
        ], PREV_WITH_BROTHER)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["name"], "AJ")
        self.assertTrue(out[0]["qualifies"])
        self.assertIn("brother", [a.lower() for a in out[0]["aliases"]])

    def test_prompt_carries_the_promotion_exception(self):
        prompt = er.build_prompt("person", [], {}, previous_roster=PREV_WITH_BROTHER)
        self.assertIn("kinship/role word", prompt)
        self.assertIn("use the proper name", prompt)


if __name__ == "__main__":
    unittest.main()
