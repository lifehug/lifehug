import importlib.util
import contextlib
import io
import sys
import tempfile
import types
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SYSTEM = ROOT / "system"
sys.path.insert(0, str(SYSTEM))


def load(name):
    """Load a private copy of system/<name>.py WITHOUT clobbering the shared
    sys.modules entry — other test modules (serve_wiki & friends) bind the
    canonical module at import time, and replacing it mid-suite splits state
    across two module objects (the v100 test-pollution lesson)."""
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


er = load("entity_roster")

CANDS = [
    {"entity": "Trevor", "score": 12.0, "unique_answers": 3, "cross_categories": ["A", "D"], "evidence": []},
    {"entity": "Grandma", "score": 46.0, "unique_answers": 8, "cross_categories": ["A"], "evidence": []},
    {"entity": "Wife", "score": 41.0, "unique_answers": 6, "cross_categories": ["C"], "evidence": []},
    {"entity": "Pure", "score": 7.5, "unique_answers": 1, "cross_categories": ["A"], "evidence": []},
]
FOCUS_MAP = {"katie": "Katie", "dad": "Dad", "mom": "Mom"}


class NormalizeTests(unittest.TestCase):
    def test_real_person_over_threshold_is_eligible(self):
        people = er.normalize("person",
            [{"name": "Trevor", "aliases": [], "qualifies": True, "maps_to_focus": None}],
            CANDS, FOCUS_MAP, min_score=8, min_answers=2)
        self.assertEqual(people[0]["slug"], "trevor")
        self.assertTrue(people[0]["page_eligible"])

    def test_below_score_not_eligible(self):
        people = er.normalize("person",
            [{"name": "Pure", "aliases": [], "qualifies": True, "maps_to_focus": None}],
            CANDS, FOCUS_MAP, min_score=8, min_answers=2)
        self.assertFalse(people[0]["page_eligible"])  # score 7.5 < 8 and 1 answer < 2

    def test_alias_merge_uses_best_stats(self):
        people = er.normalize("person",
            [{"name": "Grandma Betty Jo", "aliases": ["Grandma"], "qualifies": True, "maps_to_focus": None}],
            CANDS, FOCUS_MAP, min_score=8, min_answers=2)
        self.assertTrue(people[0]["page_eligible"])      # picks up Grandma's score=46/answers=8
        self.assertEqual(people[0]["unique_answers"], 8)

    def test_mapped_to_focus_never_eligible(self):
        people = er.normalize("person",
            [{"name": "Wife", "aliases": [], "qualifies": True, "maps_to_focus": "katie"}],
            CANDS, FOCUS_MAP, min_score=8, min_answers=2)
        self.assertEqual(people[0]["maps_to_focus"], "katie")
        self.assertFalse(people[0]["page_eligible"])     # enriches Katie, no standalone page

    def test_own_slug_is_focus_maps_to_it(self):
        people = er.normalize("person",
            [{"name": "Dad", "aliases": [], "qualifies": True, "maps_to_focus": None}],
            CANDS, FOCUS_MAP, min_score=8, min_answers=2)
        self.assertEqual(people[0]["maps_to_focus"], "dad")
        self.assertFalse(people[0]["page_eligible"])


class DeterministicTests(unittest.TestCase):
    def test_role_word_without_focus_dropped(self):
        people = er.deterministic("person",
            [{"entity": "Wife", "score": 41.0, "unique_answers": 6, "cross_categories": [], "evidence": []}],
            {}, min_score=8, min_answers=2)
        self.assertFalse(people[0]["qualifies"])
        self.assertFalse(people[0]["page_eligible"])

    def test_role_word_matching_focus_enriches_it(self):
        people = er.deterministic("person",
            [{"entity": "Mom", "score": 50.0, "unique_answers": 9, "cross_categories": [], "evidence": []}],
            {"mom": "Mom"}, min_score=8, min_answers=2)
        self.assertEqual(people[0]["maps_to_focus"], "mom")
        self.assertFalse(people[0]["page_eligible"])

    def test_proper_name_becomes_eligible_person(self):
        people = er.deterministic("person",
            [{"entity": "Trevor", "score": 12.0, "unique_answers": 3, "cross_categories": [], "evidence": []}],
            {}, min_score=8, min_answers=2)
        self.assertTrue(people[0]["qualifies"])
        self.assertTrue(people[0]["page_eligible"])


class ObjectRosterSafetyTests(unittest.TestCase):
    def test_answer_excerpts_sample_across_archive(self):
        old_answers, old_entity_dir = er.ANSWERS_DIR, er.ENTITY_DIR
        try:
            with tempfile.TemporaryDirectory() as d:
                root = Path(d)
                answers = root / "answers"
                answers.mkdir()
                er.ANSWERS_DIR = answers
                er.ENTITY_DIR = root / "entity_rosters"
                for i in range(1, 81):
                    (answers / f"A{i}.md").write_text(
                        f"# A{i}\n\n---\n\nAnswer {i} with a symbolic detail.\n",
                        encoding="utf-8",
                    )
                excerpts = er.answer_excerpts(limit=10, cap=80)
                ids = [e["id"] for e in excerpts]
                self.assertEqual(len(excerpts), 10)
                self.assertIn("A80", ids)
                self.assertTrue(any(int(qid[1:]) > 60 for qid in ids))
        finally:
            er.ANSWERS_DIR, er.ENTITY_DIR = old_answers, old_entity_dir

    def test_object_ai_failure_preserves_existing_roster(self):
        old_entity_dir, old_answers, old_questions = er.ENTITY_DIR, er.ANSWERS_DIR, er.QUESTIONS_FILE
        old_argv = sys.argv[:]
        old_research = sys.modules.get("research_expand")
        try:
            with tempfile.TemporaryDirectory() as d:
                root = Path(d)
                er.ENTITY_DIR = root / "entity_rosters"
                er.ANSWERS_DIR = root / "answers"
                er.QUESTIONS_FILE = root / "questions.md"
                er.ANSWERS_DIR.mkdir()
                er.QUESTIONS_FILE.write_text("", encoding="utf-8")
                existing = {
                    "version": 1,
                    "type": "object",
                    "resolved_at": "old",
                    "entities": [{
                        "name": "The Cleats",
                        "slug": "the-cleats",
                        "aliases": ["cleats"],
                        "qualifies": True,
                        "maps_to_focus": None,
                        "score": 0.0,
                        "unique_answers": 0,
                        "page_eligible": True,
                    }],
                }
                er.write_json(er.roster_file("object"), existing)

                def fail_ai(*_args, **_kwargs):
                    raise RuntimeError("offline")

                sys.modules["research_expand"] = types.SimpleNamespace(
                    DEFAULT_MODEL="test",
                    call_ai=fail_ai,
                    parse_ai_json=lambda text: {},
                )
                sys.argv = ["entity_roster.py", "--type", "object"]
                output = io.StringIO()
                with contextlib.redirect_stdout(output):
                    self.assertEqual(er.main(), 0)
                self.assertEqual(er.read_json(er.roster_file("object")), existing)
                self.assertIn("roster preserved", output.getvalue())
        finally:
            er.ENTITY_DIR, er.ANSWERS_DIR, er.QUESTIONS_FILE = old_entity_dir, old_answers, old_questions
            sys.argv = old_argv
            if old_research is None:
                sys.modules.pop("research_expand", None)
            else:
                sys.modules["research_expand"] = old_research

    def test_object_response_carries_forward_unmentioned_existing_objects(self):
        previous = {"entities": [{
            "name": "The Cleats",
            "slug": "the-cleats",
            "aliases": ["cleats"],
            "qualifies": True,
            "maps_to_focus": None,
            "score": 0.0,
            "unique_answers": 0,
            "page_eligible": True,
        }]}
        new = er.normalize("object", [{"name": "The Orange Shorts", "qualifies": True}],
                           [], {}, 0, 1)
        merged, preserved = er.carry_forward_objects(new, previous)
        self.assertEqual(preserved, 1)
        self.assertEqual([e["slug"] for e in merged], ["the-orange-shorts", "the-cleats"])

    def test_object_response_can_explicitly_disqualify_existing_object(self):
        previous = {"entities": [{
            "name": "The Cleats",
            "slug": "the-cleats",
            "aliases": ["cleats"],
            "qualifies": True,
            "maps_to_focus": None,
            "score": 0.0,
            "unique_answers": 0,
            "page_eligible": True,
        }]}
        replacement = er.normalize("object", [{"name": "The Cleats", "qualifies": False}],
                                   [], {}, 0, 1)
        merged, preserved = er.carry_forward_objects(replacement, previous)
        self.assertEqual(preserved, 0)
        self.assertEqual(len(merged), 1)
        self.assertFalse(merged[0]["page_eligible"])


PREV_ROSTER = {"entities": [
    {"name": "Grandma Betty Jo", "slug": "grandma-betty-jo",
     "aliases": ["Grandma", "Grandma Betty", "Betty Jo"], "qualifies": True,
     "maps_to_focus": None, "score": 46.0, "unique_answers": 8, "page_eligible": True},
    {"name": "Wife", "slug": "wife", "aliases": [], "qualifies": True,
     "maps_to_focus": "katie", "score": 41.0, "unique_answers": 6, "page_eligible": False},
]}


class PreviousRosterPromptTests(unittest.TestCase):
    def test_prompt_includes_previous_roster_block(self):
        prompt = er.build_prompt("person", CANDS, FOCUS_MAP, previous_roster=PREV_ROSTER)
        self.assertIn("Previous roster", prompt)
        self.assertIn('"Grandma Betty Jo" (slug: grandma-betty-jo)', prompt)
        self.assertIn("Grandma, Grandma Betty, Betty Jo", prompt)
        self.assertIn("maps_to_focus: katie", prompt)
        self.assertIn("Never re-split", prompt)

    def test_prompt_omits_block_without_previous_roster(self):
        for prev in (None, {"entities": []}):
            prompt = er.build_prompt("person", CANDS, FOCUS_MAP, previous_roster=prev)
            self.assertNotIn("Previous roster", prompt)

    def test_person_coreference_rule_person_only(self):
        person_prompt = er.build_prompt("person", CANDS, FOCUS_MAP)
        place_prompt = er.build_prompt("place", CANDS, FOCUS_MAP)
        self.assertIn("kinship/role word", person_prompt)
        self.assertNotIn("kinship/role word", place_prompt)


class ApplyPreviousDecisionsTests(unittest.TestCase):
    def test_resplit_collapses_into_previous_entry(self):
        # The exact regression: the AI re-split a merged person into two entries.
        raw, forced = er.apply_previous_decisions([
            {"name": "Grandma", "aliases": [], "qualifies": True, "maps_to_focus": None},
            {"name": "Betty Jo", "aliases": [], "qualifies": True, "maps_to_focus": None},
        ], PREV_ROSTER)
        merged = [e for e in raw if e["name"] == "Grandma Betty Jo"]
        self.assertEqual(len(raw), 1)
        self.assertEqual(len(merged), 1)
        self.assertGreater(forced, 0)
        self.assertEqual(sorted(a.lower() for a in merged[0]["aliases"]),
                         ["betty jo", "grandma", "grandma betty"])
        self.assertTrue(merged[0]["qualifies"])

    def test_end_to_end_normalize_keeps_stable_slug(self):
        raw, _ = er.apply_previous_decisions([
            {"name": "Grandma", "aliases": [], "qualifies": True, "maps_to_focus": None},
            {"name": "Betty Jo", "aliases": [], "qualifies": True, "maps_to_focus": None},
        ], PREV_ROSTER)
        people = er.normalize("person", raw, CANDS, FOCUS_MAP, min_score=8, min_answers=2)
        self.assertEqual(people[0]["slug"], "grandma-betty-jo")
        self.assertTrue(people[0]["page_eligible"])  # inherits Grandma's 46.0/8 via alias stats

    def test_dropped_maps_to_focus_is_restored(self):
        raw, _ = er.apply_previous_decisions([
            {"name": "Wife", "aliases": [], "qualifies": True, "maps_to_focus": None},
        ], PREV_ROSTER)
        self.assertEqual(raw[0]["maps_to_focus"], "katie")

    def test_unmatched_new_names_pass_through(self):
        raw, forced = er.apply_previous_decisions([
            {"name": "Trevor", "aliases": [], "qualifies": True, "maps_to_focus": None},
        ], PREV_ROSTER)
        self.assertEqual(forced, 0)
        self.assertEqual(raw[0]["name"], "Trevor")

    def test_no_previous_roster_is_identity(self):
        entries = [{"name": "Grandma", "aliases": [], "qualifies": True, "maps_to_focus": None}]
        raw, forced = er.apply_previous_decisions(entries, None)
        self.assertEqual(raw, entries)
        self.assertEqual(forced, 0)

    def test_ai_can_still_demote_via_all_variants_unqualified(self):
        raw, _ = er.apply_previous_decisions([
            {"name": "Grandma", "aliases": [], "qualifies": False, "maps_to_focus": None},
            {"name": "Betty Jo", "aliases": [], "qualifies": False, "maps_to_focus": None},
        ], PREV_ROSTER)
        self.assertEqual(len(raw), 1)
        self.assertFalse(raw[0]["qualifies"])

    def test_deterministic_fallback_honors_previous_decisions(self):
        people = er.deterministic("person", [
            {"entity": "Grandma", "score": 46.0, "unique_answers": 8, "cross_categories": [], "evidence": []},
        ], {}, min_score=8, min_answers=2, previous_roster=PREV_ROSTER)
        self.assertEqual(people[0]["slug"], "grandma-betty-jo")


class LoadCandidatesTests(unittest.TestCase):
    def test_two_char_initials_name_survives(self):
        # A 2-char detector candidate (AJ) must reach the AI curator, not be
        # dropped by a min-length filter. Single-char junk is still excluded.
        orig = er.load_recommendation_state
        er.load_recommendation_state = lambda: {"recommendations": [
            {"entity": "AJ", "type": "person", "score": 20.0, "unique_answers": 4,
             "cross_categories": ["C"], "evidence": []},
            {"entity": "X", "type": "person", "score": 20.0, "unique_answers": 4,
             "cross_categories": ["C"], "evidence": []},
        ]}
        try:
            names = [c["entity"] for c in er.load_candidates("person", min_answers=1)]
        finally:
            er.load_recommendation_state = orig
        self.assertIn("AJ", names)
        self.assertNotIn("X", names)


if __name__ == "__main__":
    unittest.main()
