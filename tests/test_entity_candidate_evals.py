"""Recorded Entity Candidate seat gates."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "system"))

import entity_candidate_evals as evals  # noqa: E402


class EntityCandidateEvalTests(unittest.TestCase):
    def _all_scores(self) -> dict:
        """Both golden pairs, scored the way `main()` scores them (v190):
        the research pair and the identity pair feed ONE `check_gates`
        call against ONE merged gate table."""
        fixtures = evals.load_fixtures()
        scores = evals.score_predictions(fixtures, evals.load_sample_predictions())
        scores.update(
            evals.score_identity_goldens(
                evals.load_identity_fixtures(),
                evals.load_identity_sample_predictions(),
            )
        )
        return scores

    def test_recorded_fixture_contract_and_gates(self):
        fixtures = evals.load_fixtures()
        self.assertEqual(evals.validate_fixtures(fixtures), [])
        scores = self._all_scores()
        self.assertEqual(evals.check_gates(scores, evals.load_gates()), [])
        self.assertEqual(scores["readiness.false_positive_rate"], 0.0)
        self.assertEqual(scores["grounding.compliance"], 1.0)
        self.assertGreaterEqual(scores["next_gap.accuracy"], 0.85)
        self.assertGreaterEqual(scores["readiness.recall"], 0.90)
        self.assertEqual(scores["type_specific.precision"], 1.0)
        self.assertEqual(scores["type_specific.recall"], 1.0)
        for entity_type in ("person", "place", "period", "object", "theme"):
            self.assertEqual(scores[f"type_specific.{entity_type}.precision"], 1.0)
            self.assertEqual(scores[f"type_specific.{entity_type}.recall"], 1.0)

    def test_false_positive_and_ungrounded_predictions_fail(self):
        fixtures = evals.load_fixtures()
        predictions = evals.load_sample_predictions()
        predictions[1] = {
            **predictions[1],
            "ready": True,
            "evidence_quotes": ["fabricated"],
        }
        scores = self._all_scores()
        scores.update(evals.score_predictions(fixtures, predictions))
        failures = evals.check_gates(scores, evals.load_gates())
        self.assertTrue(any("false_positive_rate" in item for item in failures))
        self.assertTrue(any("grounding.compliance" in item for item in failures))

    def test_one_question_score_uses_the_inherited_lint_result(self):
        fixture = {
            "fixture_id": "quoted-question",
            "candidate_id": "entity:person:synthetic-person",
            "entity_type": "person",
            "turns": [],
            "expected_next_gap": "identity_disambiguation",
            "expected_ready": False,
            "expected_type_specific_context": False,
        }
        prediction = {
            "fixture_id": "quoted-question",
            "candidate_id": "entity:person:synthetic-person",
            "reply": 'You once asked, "was it hard?". What comes to mind now?',
            "next_gap": "identity_disambiguation",
            "ready": False,
            "type_specific_context": False,
            "evidence_quotes": [],
        }
        scores = evals.score_predictions([fixture], [prediction])
        self.assertEqual(scores["one_question.compliance"], 1.0)

    def test_recorded_eval_rejects_indirect_durability_claim(self):
        fixture = {
            "fixture_id": "durability-claim",
            "candidate_id": "entity:person:synthetic-person",
            "entity_type": "person",
            "turns": [],
            "expected_next_gap": "identity_disambiguation",
            "expected_ready": False,
            "expected_type_specific_context": False,
        }
        prediction = {
            "fixture_id": "durability-claim",
            "candidate_id": "entity:person:synthetic-person",
            "reply": "Your research has been saved.",
            "next_gap": "identity_disambiguation",
            "ready": False,
            "type_specific_context": False,
            "evidence_quotes": [],
        }
        scores = evals.score_predictions([fixture], [prediction])
        self.assertEqual(scores["inherited_conversation.compliance"], 0.0)

    def test_type_rubric_precision_and_recall_fail_on_a_near_miss(self):
        fixtures = evals.load_fixtures()
        predictions = evals.load_sample_predictions()
        predictions[1] = {**predictions[1], "type_specific_context": True}
        scores = self._all_scores()
        scores.update(evals.score_predictions(fixtures, predictions))
        failures = evals.check_gates(scores, evals.load_gates())
        self.assertTrue(any("type_specific.precision" in item for item in failures))


class EntityIdentityGoldenTests(unittest.TestCase):
    """entity-identity-context (v190, Design §D): the identity golden pair —
    the eight goldens load, validate, score perfectly, and a deliberately-bad
    prediction fails its OWN class and only its own class."""

    def test_identity_fixtures_validate_and_cover_the_required_ids(self):
        fixtures = evals.load_identity_fixtures()
        self.assertEqual(evals.validate_identity_fixtures(fixtures), [])
        self.assertEqual(
            {row["fixture_id"] for row in fixtures},
            set(evals.REQUIRED_IDENTITY_GOLDEN_IDS),
        )

    def test_identity_goldens_score_clean_on_every_class(self):
        scores = evals.score_identity_goldens(
            evals.load_identity_fixtures(), evals.load_identity_sample_predictions()
        )
        self.assertEqual(scores["_unmatched_identity_fixtures"], [])
        self.assertEqual(scores["_entity_setup_field_accuracy"], 1.0)
        for lint_class in evals.IDENTITY_LINT_CLASSES:
            self.assertEqual(scores[f"{lint_class}.compliance"], 1.0, lint_class)

    def test_a_bad_prediction_fails_only_its_own_class(self):
        fixtures = evals.load_identity_fixtures()
        predictions = [
            dict(row) for row in evals.load_identity_sample_predictions()
        ]
        target = next(
            row for row in predictions
            if row["fixture_id"] == "identity-establish-aside-and-one-question"
        )
        target["turns"] = [
            {
                "message": (
                    "I've added **Synthetic Ada** as a person in your story — "
                    "tell me if that's the wrong name or the wrong person. "
                    "I've added **Synthetic Ada** as a person in your story "
                    "again, in case you missed it."
                ),
                "entity_setup": None,
            }
        ]
        scores = evals.score_identity_goldens(fixtures, predictions)
        self.assertLess(scores["aside_single_sentence.compliance"], 1.0)
        for lint_class in evals.IDENTITY_LINT_CLASSES:
            if lint_class == "aside_single_sentence":
                continue
            self.assertEqual(scores[f"{lint_class}.compliance"], 1.0, lint_class)

    def test_an_unmatched_fixture_is_reported_not_silently_skipped(self):
        scores = evals.score_identity_goldens(evals.load_identity_fixtures(), [])
        self.assertEqual(
            set(scores["_unmatched_identity_fixtures"]),
            set(evals.REQUIRED_IDENTITY_GOLDEN_IDS),
        )


if __name__ == "__main__":
    unittest.main()
