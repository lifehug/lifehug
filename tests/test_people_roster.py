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


pr = load("people_roster")

CANDS = [
    {"entity": "Trevor", "score": 12.0, "unique_answers": 3, "cross_categories": ["A", "D"], "evidence": []},
    {"entity": "Grandma", "score": 46.0, "unique_answers": 8, "cross_categories": ["A"], "evidence": []},
    {"entity": "Wife", "score": 41.0, "unique_answers": 6, "cross_categories": ["C"], "evidence": []},
    {"entity": "Pure", "score": 7.5, "unique_answers": 1, "cross_categories": ["A"], "evidence": []},
]
FOCUS_MAP = {"katie": "Katie", "dad": "Dad", "mom": "Mom"}


class NormalizeTests(unittest.TestCase):
    def test_real_person_over_threshold_is_eligible(self):
        people = pr.normalize_people(
            [{"name": "Trevor", "aliases": [], "is_real_person": True, "maps_to_focus": None}],
            CANDS, FOCUS_MAP, min_score=8, min_answers=2)
        self.assertEqual(people[0]["slug"], "trevor")
        self.assertTrue(people[0]["page_eligible"])

    def test_below_score_not_eligible(self):
        people = pr.normalize_people(
            [{"name": "Pure", "aliases": [], "is_real_person": True, "maps_to_focus": None}],
            CANDS, FOCUS_MAP, min_score=8, min_answers=2)
        self.assertFalse(people[0]["page_eligible"])  # score 7.5 < 8 and 1 answer < 2

    def test_alias_merge_uses_best_stats(self):
        people = pr.normalize_people(
            [{"name": "Grandma Betty Jo", "aliases": ["Grandma"], "is_real_person": True, "maps_to_focus": None}],
            CANDS, FOCUS_MAP, min_score=8, min_answers=2)
        self.assertTrue(people[0]["page_eligible"])      # picks up Grandma's score=46/answers=8
        self.assertEqual(people[0]["unique_answers"], 8)

    def test_mapped_to_focus_never_eligible(self):
        people = pr.normalize_people(
            [{"name": "Wife", "aliases": [], "is_real_person": True, "maps_to_focus": "katie"}],
            CANDS, FOCUS_MAP, min_score=8, min_answers=2)
        self.assertEqual(people[0]["maps_to_focus"], "katie")
        self.assertFalse(people[0]["page_eligible"])     # enriches Katie, no standalone page

    def test_own_slug_is_focus_maps_to_it(self):
        people = pr.normalize_people(
            [{"name": "Dad", "aliases": [], "is_real_person": True, "maps_to_focus": None}],
            CANDS, FOCUS_MAP, min_score=8, min_answers=2)
        self.assertEqual(people[0]["maps_to_focus"], "dad")
        self.assertFalse(people[0]["page_eligible"])


class DeterministicTests(unittest.TestCase):
    def test_role_word_without_focus_dropped(self):
        people = pr.deterministic_roster(
            [{"entity": "Wife", "score": 41.0, "unique_answers": 6, "cross_categories": [], "evidence": []}],
            {}, min_score=8, min_answers=2)
        self.assertFalse(people[0]["is_real_person"])
        self.assertFalse(people[0]["page_eligible"])

    def test_role_word_matching_focus_enriches_it(self):
        people = pr.deterministic_roster(
            [{"entity": "Mom", "score": 50.0, "unique_answers": 9, "cross_categories": [], "evidence": []}],
            {"mom": "Mom"}, min_score=8, min_answers=2)
        self.assertEqual(people[0]["maps_to_focus"], "mom")
        self.assertFalse(people[0]["page_eligible"])

    def test_proper_name_becomes_eligible_person(self):
        people = pr.deterministic_roster(
            [{"entity": "Trevor", "score": 12.0, "unique_answers": 3, "cross_categories": [], "evidence": []}],
            {}, min_score=8, min_answers=2)
        self.assertTrue(people[0]["is_real_person"])
        self.assertTrue(people[0]["page_eligible"])


if __name__ == "__main__":
    unittest.main()
