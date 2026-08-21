"""Independent Question Candidate fixture, scorer, and seating gates."""

from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
SYSTEM = ROOT / "system"
sys.path.insert(0, str(SYSTEM))

import eval_gates  # noqa: E402
import interaction_evals  # noqa: E402
import lifehug  # noqa: E402
import question_candidate as qc  # noqa: E402
import question_candidate_evals as qce  # noqa: E402


class QuestionCandidateEvalTests(unittest.TestCase):
    def test_committed_fixtures_validate_and_cover_timing_lifecycle(self):
        fixtures = qce.load_fixtures()
        self.assertEqual(qce.validate_fixtures(fixtures), [])
        self.assertEqual(
            {row["input"]["association_stage"] for row in fixtures},
            {"before_answer", "during_answer", "after_answer"},
        )
        statuses = {row["expected"]["status"] for row in fixtures}
        self.assertTrue(
            {"active", "needs_clarification", "complete", "declined", "deferred"}
            <= statuses
        )

    def test_committed_samples_clear_all_seven_gate_classes(self):
        scores = qce.score_predictions(
            qce.load_fixtures(), qce.load_sample_predictions()
        )
        gates = qce.load_gates()
        self.assertEqual(
            set(gates),
            {
                "category",
                "turn_kind",
                "closed_roster",
                "question",
                "timing",
                "completion",
                "stale_revision",
            }
            | set(qce.PLACEMENT_LINT_CLASSES),
        )
        # Only the ADR-0018 fixtures/predictions pair is scored here; the
        # placement classes are exercised by
        # test_committed_placement_samples_clear_all_placement_gates below.
        adr0018_gates = {
            name: thresholds
            for name, thresholds in gates.items()
            if name not in qce.PLACEMENT_LINT_CLASSES
        }
        self.assertEqual(qce.check_gates(scores, adr0018_gates), [])
        self.assertEqual(scores["_missing"], [])
        self.assertEqual(scores["_unmatched"], [])

    def test_corrupt_category_and_missing_prediction_trip_gates(self):
        predictions = [dict(row) for row in qce.load_sample_predictions()]
        for row in predictions:
            output = row.get("model_output")
            if isinstance(output, dict) and output.get("category_id") is not None:
                row["model_output"] = {**output, "category_id": "NOT-IN-ROSTER"}
        scores = qce.score_predictions(qce.load_fixtures(), predictions[1:])
        failures = qce.check_gates(scores, qce.load_gates())
        self.assertTrue(
            any("placement_gates.category" in failure for failure in failures)
        )
        self.assertTrue(scores["_missing"])

    def test_generic_gate_arithmetic_matches_conversation_checker(self):
        scores = {"answer": {"recall": 0.5}}
        gates = {"answer": {"recall": 0.8}}
        direct = eval_gates.check_score_gates(scores, gates, prefix="router_gates")
        self.assertEqual(interaction_evals.check_router_gates(scores, gates), direct)

    def test_inherited_lints_cover_every_model_reply_action(self):
        payload = next(
            row["input"]
            for row in qce.load_fixtures()
            if row["input"]["latest_user_turn"] is not None
        )
        self.assertEqual(qce.inherited_lint_action_failures(payload), [])

    def test_live_seat_skips_loudly_without_provider(self):
        result = qce.run_live(
            qce.load_fixtures(),
            status_resolver=lambda *_args, **_kwargs: SimpleNamespace(ready=False),
        )
        self.assertEqual(result["status"], "skipped")
        self.assertIn("no unattended AI provider", result["reason"])

    def test_placement_fixtures_cover_all_seven_golden_ids(self):
        fixtures = qce.load_placement_fixtures()
        self.assertEqual(qce.validate_placement_fixtures(fixtures), [])
        self.assertEqual(
            {row["fixture_id"] for row in fixtures},
            set(qce.REQUIRED_PLACEMENT_GOLDEN_IDS),
        )

    def test_committed_placement_samples_clear_all_placement_gates(self):
        scores = qce.score_placement_goldens(
            qce.load_placement_fixtures(), qce.load_placement_sample_predictions()
        )
        gates = {
            name: thresholds
            for name, thresholds in qce.load_gates().items()
            if name in qce.PLACEMENT_LINT_CLASSES
        }
        self.assertEqual(set(gates), set(qce.PLACEMENT_LINT_CLASSES))
        self.assertEqual(qce.check_gates(scores, gates), [])
        self.assertEqual(scores["_unmatched_placement_fixtures"], [])
        self.assertEqual(scores["_missing_placement_fixtures"], [])
        self.assertEqual(scores["_placement_field_accuracy"], 1.0)

    def test_golden_assert_never_repeated_pins_silence_after_the_first_reply(self):
        # golden 2: the same session's turns 2 and 3 carry no placement
        # sentence and placement: null (ruling 3/4's "never again" pin).
        fixtures = {row["fixture_id"]: row for row in qce.load_placement_fixtures()}
        predictions = {
            row["fixture_id"]: row for row in qce.load_placement_sample_predictions()
        }
        fixture = fixtures["placement-assert-never-repeated"]
        prediction = predictions["placement-assert-never-repeated"]
        roster = qc.build_category_roster(fixture["roster"])
        for turn, pred_turn in list(zip(fixture["turns"], prediction["turns"]))[1:]:
            self.assertEqual(turn["stage"], "settled")
            findings = qc.lint_placement_reply(
                pred_turn["message"], stage="settled", roster=roster
            )
            self.assertEqual(findings, [])
            self.assertIsNone(pred_turn["placement"])

    def test_golden_user_disagrees_emits_move_with_no_confirmation(self):
        # golden 5: "no, that's Boatworks" on turn 3 -> placement carries the
        # exact roster letter, receipted in one clause, no confirmation
        # question, no mechanism talk.
        fixtures = {row["fixture_id"]: row for row in qce.load_placement_fixtures()}
        predictions = {
            row["fixture_id"]: row for row in qce.load_placement_sample_predictions()
        }
        fixture = fixtures["placement-user-disagrees-emits-move"]
        prediction = predictions["placement-user-disagrees-emits-move"]
        roster = qc.build_category_roster(fixture["roster"])
        turn, pred_turn = fixture["turns"][2], prediction["turns"][2]
        self.assertEqual(turn["expected_placement"], {"category": "W"})
        self.assertEqual(pred_turn["placement"], {"category": "W"})
        self.assertEqual(
            qc.lint_placement_reply(pred_turn["message"], stage="settled", roster=roster),
            [],
        )
        self.assertNotIn("?", pred_turn["message"])

    def test_golden_unknown_letter_normalizes_to_no_placement_without_failing_the_turn(self):
        # golden 7: a proposal naming "Z" against a roster without Z
        # normalizes to no placement and does not fail the turn.
        fixtures = {row["fixture_id"]: row for row in qce.load_placement_fixtures()}
        predictions = {
            row["fixture_id"]: row for row in qce.load_placement_sample_predictions()
        }
        fixture = fixtures["placement-unknown-letter-rejected"]
        prediction = predictions["placement-unknown-letter-rejected"]
        roster = qc.build_category_roster(fixture["roster"])
        turn, pred_turn = fixture["turns"][0], prediction["turns"][0]
        self.assertEqual(pred_turn["placement"], {"category": "Z"})
        self.assertIsNone(qc.validate_placement(pred_turn["placement"], roster=roster))
        self.assertEqual(turn["expected_placement"], None)
        # The turn itself is not blocked/failed by the unknown letter.
        self.assertEqual(
            qc.lint_placement_reply(pred_turn["message"], stage="settled", roster=roster),
            [],
        )

    def test_cli_is_independent_read_only_and_green(self):
        proc = subprocess.run(
            [sys.executable, str(SYSTEM / "lifehug.py"), "question-candidate-evals"],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("Question Candidate Interaction evals", proc.stdout)
        self.assertIn("SKIPPED", proc.stdout)
        self.assertIn("question-candidate-evals", lifehug.READ_ONLY_COMMANDS)
        self.assertNotIn("question-candidate-evals", lifehug.DIRECT_MUTATION_COMMANDS)


if __name__ == "__main__":
    unittest.main()
