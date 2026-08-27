"""v195 / ADR 0024 — the Timeline seat gate.

`timeline-evals` is what decides which models may be seated in the Timeline
Interaction. This suite pins the fixture contract, the ten required goldens,
and the fact that the shipped recorded seat passes every gate at its own
threshold.

Synthetic data only; NEVER references ~/Workspace/dave.
"""

from __future__ import annotations

import copy
import json
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SYSTEM = ROOT / "system"
sys.path.insert(0, str(SYSTEM))

import timeline_evals as te  # noqa: E402
import timeline_interaction as ti  # noqa: E402


class FixtureContractTests(unittest.TestCase):
    def setUp(self):
        self.fixtures = te.load_fixtures()

    def test_the_shipped_fixtures_are_valid(self):
        self.assertEqual(te.validate_fixtures(self.fixtures), [])

    def test_the_ten_required_goldens_are_present(self):
        ids = {row["fixture_id"] for row in self.fixtures}
        self.assertEqual(te.REQUIRED_GOLDEN_IDS - ids, set())
        self.assertGreaterEqual(len(te.REQUIRED_GOLDEN_IDS), 10)

    def test_the_skeleton_episode_walks_birthday_then_residences(self):
        skeleton = next(row for row in self.fixtures
                        if row["fixture_id"] == "timeline-skeleton-episode")
        steps = [turn["probe_step"] for turn in skeleton["turns"]]
        self.assertEqual(steps[:2], ["content", "residence"])
        placed = [turn["expected_placed"] for turn in skeleton["turns"]]
        self.assertTrue(any(p and p.get("basis") == "stated" for p in placed))
        self.assertTrue(any(p and p.get("basis") == "age" for p in placed))

    def test_the_contradiction_golden_keeps_both_accounts(self):
        row = next(r for r in self.fixtures
                   if r["fixture_id"] == "timeline-contradiction-keeps-both")
        message = next(p for p in te.load_sample_predictions()
                       if p["fixture_id"] == row["fixture_id"])["turns"][0]["message"]
        self.assertIn("keep both", message.lower())

    def test_the_defer_golden_files_nothing_and_asks_nothing(self):
        """v196: "I'll find out" is an ordinary answer. It is still received
        without a question — and it files nothing at all."""
        row = next(r for r in self.fixtures
                   if r["fixture_id"] == "timeline-ill-find-out-is-accepted")
        self.assertIsNone(row["turns"][-1]["expected_placed"])
        message = next(p for p in te.load_sample_predictions()
                       if p["fixture_id"] == row["fixture_id"])["turns"][-1]["message"]
        self.assertNotIn("?", message)

    def _broken(self, mutate):
        fixtures = copy.deepcopy(self.fixtures)
        mutate(fixtures)
        return te.validate_fixtures(fixtures)

    def test_every_malformed_fixture_row_is_caught(self):
        cases = {
            "extra key": lambda f: f[0].update({"stray": 1}),
            "duplicate id": lambda f: f.append(copy.deepcopy(f[0])),
            "bad stage": lambda f: f[0]["turns"][0].update({"stage": "wander"}),
            "bad probe step": lambda f: f[0]["turns"][0].update({"probe_step": "vibes"}),
            "no turns": lambda f: f[0].update({"turns": []}),
            "bad anchors": lambda f: f[0]["unknown"].update({"anchors": [{"label": "x"}]}),
            "bad known_years": lambda f: f[0]["unknown"].update({"known_years": [1979]}),
            "unvalidatable placed": lambda f: f[0]["turns"][0].update(
                {"expected_placed": {"best": "1984", "anchors": ["never-offered"]}}),
        }
        for name, mutate in cases.items():
            with self.subTest(case=name):
                self.assertTrue(self._broken(mutate), f"{name} was not caught")

    def test_a_missing_required_golden_is_caught(self):
        self.assertTrue(te.validate_fixtures([f for f in self.fixtures
                                              if f["fixture_id"] != "timeline-skeleton-episode"]))


class ScoringTests(unittest.TestCase):
    def setUp(self):
        self.fixtures = te.load_fixtures()
        self.predictions = te.load_sample_predictions()

    def test_the_shipped_recorded_seat_passes_every_gate(self):
        scores = te.score_goldens(self.fixtures, self.predictions)
        self.assertEqual(te.check_gates(scores, te.load_gates()), [])
        self.assertEqual(scores["_placed_accuracy"], 1.0)
        self.assertEqual(scores["_unmatched_fixtures"], [])

    def test_every_gate_class_is_scored(self):
        scores = te.score_goldens(self.fixtures, self.predictions)
        for name in ti.TIMELINE_LINT_CLASSES:
            self.assertIn(f"{name}.compliance", scores)
        self.assertEqual(set(te.load_gates()),
                         {f"{name}.compliance" for name in ti.TIMELINE_LINT_CLASSES})

    def test_a_year_demanding_opener_fails_its_gate(self):
        broken = copy.deepcopy(self.predictions)
        broken[0]["turns"][0]["message"] = "What year was that?"
        scores = te.score_goldens(self.fixtures, broken)
        self.assertLess(scores["no_year_opener.compliance"], 1.0)

    def test_an_off_anchor_placement_normalizes_to_no_filing_change(self):
        broken = copy.deepcopy(self.predictions)
        target = next(p for p in broken if p["fixture_id"] == "timeline-place-age-arithmetic")
        target["turns"][0]["placed"]["anchors"] = ["a-landmark-nobody-offered"]
        scores = te.score_goldens(self.fixtures, broken)
        self.assertLess(scores["_placed_accuracy"], 1.0)
        self.assertEqual(scores["no_year_opener.compliance"], 1.0)

    def test_a_missing_prediction_is_reported_not_silently_passed(self):
        # The dropped fixture is named by POSITION, not by a hardcoded id: this
        # assertion is "an unmatched fixture is reported", and pinning the last
        # golden's name made every new golden look like a regression (v234).
        scores = te.score_goldens(self.fixtures, self.predictions[:-1])
        self.assertEqual(scores["_unmatched_fixtures"],
                         [self.predictions[-1]["fixture_id"]])


class CliTests(unittest.TestCase):
    def test_the_recorded_harness_passes_and_prints_json(self):
        result = subprocess.run(
            [sys.executable, str(SYSTEM / "lifehug.py"), "timeline-evals", "--json"],
            capture_output=True, text=True, cwd=ROOT, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["interaction"], "timeline")
        self.assertEqual(payload["mode"], "recorded")
        self.assertTrue(payload["passed"])
        self.assertEqual(payload["failures"], [])


if __name__ == "__main__":
    unittest.main()
