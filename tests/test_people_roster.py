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
    spec = importlib.util.spec_from_file_location(name, SYSTEM / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
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
