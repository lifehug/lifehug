"""Recorded Focus Candidate seat gates."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "system"))

import focus_candidate_evals as evals  # noqa: E402


class FocusCandidateEvalTests(unittest.TestCase):
    def test_recorded_fixture_contract_and_gates(self):
        fixtures = evals.load_fixtures()
        self.assertEqual(evals.validate_fixtures(fixtures), [])
        scores = evals.score_predictions(fixtures, evals.load_sample_predictions())
        self.assertEqual(evals.check_gates(scores, evals.load_gates()), [])
        self.assertEqual(scores["readiness.false_positive_rate"], 0.0)
        self.assertEqual(scores["grounding.compliance"], 1.0)
        self.assertGreaterEqual(scores["next_gap.accuracy"], 0.85)
        self.assertGreaterEqual(scores["readiness.recall"], 0.90)

    def test_false_positive_and_ungrounded_predictions_fail(self):
        fixtures = evals.load_fixtures()
        predictions = evals.load_sample_predictions()
        predictions[0] = {
            **predictions[0],
            "ready": True,
            "evidence_quotes": ["fabricated"],
        }
        failures = evals.check_gates(
            evals.score_predictions(fixtures, predictions), evals.load_gates()
        )
        self.assertTrue(any("false_positive_rate" in item for item in failures))
        self.assertTrue(any("grounding.compliance" in item for item in failures))

    def test_one_question_score_uses_the_inherited_lint_result(self):
        fixture = {
            "fixture_id": "quoted-question",
            "candidate_id": "rec-synthetic-harbor",
            "turns": [],
            "expected_next_gap": "focus_identity",
            "expected_ready": False,
        }
        prediction = {
            "fixture_id": "quoted-question",
            "candidate_id": "rec-synthetic-harbor",
            "reply": 'You once asked, "was it hard?". What comes to mind now?',
            "next_gap": "focus_identity",
            "ready": False,
            "evidence_quotes": [],
        }
        scores = evals.score_predictions([fixture], [prediction])
        self.assertEqual(scores["one_question.compliance"], 1.0)

    def test_recorded_eval_rejects_indirect_durability_claim(self):
        fixture = {
            "fixture_id": "durability-claim",
            "candidate_id": "rec-synthetic-harbor",
            "turns": [],
            "expected_next_gap": "focus_identity",
            "expected_ready": False,
        }
        prediction = {
            "fixture_id": "durability-claim",
            "candidate_id": "rec-synthetic-harbor",
            "reply": "Your research has been saved.",
            "next_gap": "focus_identity",
            "ready": False,
            "evidence_quotes": [],
        }
        scores = evals.score_predictions([fixture], [prediction])
        self.assertEqual(scores["inherited_conversation.compliance"], 0.0)


if __name__ == "__main__":
    unittest.main()
