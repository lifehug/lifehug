"""v193 — the Arc Walk seat gate (arc_walk_gates.*)."""

from __future__ import annotations

import copy
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SYSTEM = ROOT / "system"
sys.path.insert(0, str(SYSTEM))

import arc_walk  # noqa: E402
import arc_walk_evals as evals  # noqa: E402


class ArcWalkEvalsTests(unittest.TestCase):
    def setUp(self):
        self.fixtures = evals.load_fixtures()
        self.predictions = evals.load_sample_predictions()

    def test_fixtures_are_valid_and_carry_every_required_golden(self):
        self.assertEqual(evals.validate_fixtures(self.fixtures), [])
        self.assertEqual(
            {row["fixture_id"] for row in self.fixtures},
            set(evals.REQUIRED_GOLDEN_IDS),
        )
        self.assertGreaterEqual(len(self.fixtures), 9)

    def test_gates_cover_every_lint_class_exactly(self):
        gates = evals.load_gates()
        self.assertEqual(
            {name.removesuffix(".compliance") for name in gates},
            set(arc_walk.ARC_WALK_LINT_CLASSES),
        )
        self.assertTrue(all(value == 1.0 for value in gates.values()))

    def test_recorded_seat_passes_every_gate(self):
        scores = evals.score_goldens(self.fixtures, self.predictions)
        self.assertEqual(evals.check_gates(scores, evals.load_gates()), [])
        self.assertEqual(scores["_unmatched_fixtures"], [])
        self.assertEqual(scores["_answered_question_id_accuracy"], 1.0)

    def test_a_missing_prediction_is_reported_not_silently_passed(self):
        scores = evals.score_goldens(self.fixtures, self.predictions[1:])
        self.assertEqual(
            scores["_unmatched_fixtures"], ["arc-open-announces-agenda-once"]
        )

    def test_a_bad_prediction_fails_only_its_own_class(self):
        predictions = copy.deepcopy(self.predictions)
        by_id = {row["fixture_id"]: row for row in predictions}
        by_id["arc-close-summarizes-without-counters"]["turns"][0]["message"] = (
            "We covered the harbor and the boat — that's 2 of 3 done."
        )
        scores = evals.score_goldens(self.fixtures, predictions)
        failures = {
            name.split(".", 1)[0]
            for name in evals.check_gates(scores, evals.load_gates())
        }
        self.assertEqual(failures, {"no_counters", "close_summarizes"})

    def test_an_off_plan_question_id_costs_no_lint_and_files_nothing(self):
        """Golden 9's whole point."""
        fixture = next(
            row for row in self.fixtures
            if row["fixture_id"] == "arc-walk-unknown-question-id-rejected"
        )
        prediction = next(
            row for row in self.predictions
            if row["fixture_id"] == "arc-walk-unknown-question-id-rejected"
        )
        self.assertEqual(prediction["turns"][0]["answered_question_id"], "Z99")
        scores = evals.score_goldens([fixture], [prediction])
        self.assertEqual(evals.check_gates(scores, evals.load_gates()), [])
        self.assertEqual(scores["_answered_question_id_accuracy"], 1.0)

    def test_main_passes_in_recorded_mode(self):
        self.assertEqual(evals.main([]), 0)


if __name__ == "__main__":
    unittest.main()
