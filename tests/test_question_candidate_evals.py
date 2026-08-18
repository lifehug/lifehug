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
            },
        )
        self.assertEqual(qce.check_gates(scores, gates), [])
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

    def test_live_seat_skips_loudly_without_provider(self):
        result = qce.run_live(
            qce.load_fixtures(),
            status_resolver=lambda *_args, **_kwargs: SimpleNamespace(ready=False),
        )
        self.assertEqual(result["status"], "skipped")
        self.assertIn("no unattended AI provider", result["reason"])

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
