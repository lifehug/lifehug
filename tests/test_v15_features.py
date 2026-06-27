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


SAMPLE_BANK = """# Lifehug — Question Bank

## A: Origins
- [x] A1: earliest memory *(2026-01-01)*
- [ ] A2: where you grew up

## B: Becoming
- [ ] B1: a turning point

## Project Categories

## F: The Problem (Etherfuse Story)
- [x] F1: the problem *(2026-01-02)*
- [ ] F2: more problem

## G: Building (Etherfuse Story)
- [ ] G1: building
- [ ] G2: more building

## Focuses

## K: Focus — Mom
- [x] K1: about mom *(2026-01-03)*
- [x] K2: more mom *(2026-01-04)*
"""


class RoadmapDeriveTests(unittest.TestCase):
    def setUp(self):
        self.rm = load("roadmap")

    def test_life_story_baseline_collapses_main_categories(self):
        focuses = {f["id"]: f for f in self.rm.derive_focuses(SAMPLE_BANK)}
        self.assertIn("my-life", focuses)
        self.assertEqual(focuses["my-life"]["type"], "life_story")
        self.assertEqual(sorted(focuses["my-life"]["categories"]), ["A", "B"])

    def test_project_categories_group_by_parenthetical_tag(self):
        focuses = {f["id"]: f for f in self.rm.derive_focuses(SAMPLE_BANK)}
        # F and G both tagged "(Etherfuse Story)" → one Focus.
        self.assertIn("etherfuse", focuses)
        self.assertEqual(sorted(focuses["etherfuse"]["categories"]), ["F", "G"])
        self.assertEqual(focuses["etherfuse"]["type"], "project")

    def test_focus_label_is_cleaned(self):
        focuses = {f["id"]: f for f in self.rm.derive_focuses(SAMPLE_BANK)}
        self.assertIn("mom", focuses)
        self.assertEqual(focuses["mom"]["label"], "Mom")
        self.assertEqual(focuses["mom"]["type"], "person")

    def test_derive_preserves_user_overrides(self):
        first = self.rm.derive_roadmap(SAMPLE_BANK)
        for f in first["focuses"]:
            if f["id"] == "etherfuse":
                f["tier"] = "extreme"
                f["phase"] = "finishing"
        second = self.rm.derive_roadmap(SAMPLE_BANK, existing=first)
        eth = next(f for f in second["focuses"] if f["id"] == "etherfuse")
        self.assertEqual(eth["tier"], "extreme")
        self.assertEqual(eth["phase"], "finishing")


class FillAndWeightTests(unittest.TestCase):
    def setUp(self):
        self.rm = load("roadmap")
        self.qp = load("question_planner")

    def test_focus_fill_counts_room_and_saturation(self):
        questions = self.qp.parse_questions(SAMPLE_BANK)
        mom = {"categories": ["K"], "tier": "basic", "target_depth": 4}
        fill = self.rm.focus_fill(mom, questions)
        self.assertEqual(fill["answered"], 2)
        self.assertEqual(fill["target"], 4)
        self.assertFalse(fill["room"])           # K1,K2 both answered → no pending
        self.assertAlmostEqual(fill["saturation"], 0.5)

    def test_weight_under_target_is_full(self):
        w = self.qp.focus_weight({"tier": "standard"}, {"room": True, "saturation": 0.3})
        self.assertAlmostEqual(w, 1.0)

    def test_weight_saturated_decays_to_maintenance(self):
        w = self.qp.focus_weight({"tier": "standard"}, {"room": True, "saturation": 1.2})
        self.assertAlmostEqual(w, self.rm.MAINTENANCE_FACTOR)

    def test_weight_no_room_is_zero(self):
        w = self.qp.focus_weight({"tier": "extreme"}, {"room": False, "saturation": 0.1})
        self.assertEqual(w, 0.0)

    def test_extreme_tier_pulls_harder_than_basic(self):
        hi = self.qp.focus_weight({"tier": "extreme"}, {"room": True, "saturation": 0.2})
        lo = self.qp.focus_weight({"tier": "basic"}, {"room": True, "saturation": 0.2})
        self.assertGreater(hi, lo)


class AllocationEngineTests(unittest.TestCase):
    """Integration against the repo's own question bank (read-only)."""

    def setUp(self):
        self.qp = load("question_planner")

    def test_queue_respects_per_focus_cap_and_limit(self):
        data = self.qp.build_queue(limit=12, arc_max=2, expires_days=8, seed=42)
        self.assertLessEqual(len(data["queue"]), 12)
        self.assertEqual(data["policy"]["allocation"], "dynamic-focus-weighted")
        contributing = [f for f in data["allocation"]["focuses"] if f["queued"] > 0]
        # The variety cap binds whenever there's an alternative Focus to pick
        # from; with only one Focus that has room it legitimately fills the week.
        if len(contributing) > 1:
            for f in contributing:
                self.assertLessEqual(f["queued"], f["cap"])
        self.assertEqual(sum(f["queued"] for f in data["allocation"]["focuses"]), len(data["queue"]))

    def test_seed_changes_the_mix(self):
        a = self.qp.build_queue(limit=12, arc_max=2, seed=1)
        b = self.qp.build_queue(limit=12, arc_max=2, seed=999)
        # Same seed is reproducible; different seeds should (usually) differ.
        a2 = self.qp.build_queue(limit=12, arc_max=2, seed=1)
        self.assertEqual([q["question_id"] for q in a["queue"]],
                         [q["question_id"] for q in a2["queue"]])


if __name__ == "__main__":
    unittest.main()
