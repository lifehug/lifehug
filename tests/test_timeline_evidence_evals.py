"""Recorded and optional-live timeline evidence evaluation contract."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "system"))

import timeline_evidence_evals as evals  # noqa: E402


class TimelineEvidenceEvalTests(unittest.TestCase):
    def test_recorded_report_is_exact_and_disclaims_live_quality(self) -> None:
        fixtures = evals.load_fixtures()
        responses = [evals.recorded_response(evals.build_case(row)) for row in fixtures]
        report = evals.evaluate(fixtures, responses)
        self.assertEqual(report["fixture_count"], 5)
        self.assertEqual(report["passed_count"], 5)
        self.assertEqual(report["retrieval_coverage"], 1.0)
        self.assertEqual(report["validation_accuracy"], 1.0)
        self.assertEqual(
            sorted(report["stage_timings_ms"]), ["retrieval", "total", "validation"]
        )
        self.assertIn("plumbing only", evals.QUALITY_NOTE)

    def test_lifecycle_probe_covers_invalidation_reuse_and_fixed_point(self) -> None:
        probe = evals.lifecycle_probe()
        self.assertEqual(probe["before"]["candidate_ids"], [])
        self.assertEqual(
            probe["after_new_evidence"]["candidate_ids"], ["node:river-stay"]
        )
        self.assertFalse(probe["after_bound_correction"]["refresh_required"])
        self.assertFalse(probe["unchanged"]["refresh_required"])
        self.assertTrue(all(probe["checks"].values()))

    def test_live_path_uses_the_actual_full_extraction_prompt(self) -> None:
        fixture = evals.load_fixtures()[0]
        case = evals.build_case(fixture)
        response = evals.recorded_response(case)
        prompts = []

        def answer(prompt, _model):
            prompts.append(prompt)
            return json.dumps(response)

        with mock.patch.object(evals, "load_config", return_value={
            "classify_model": "synthetic-model"
        }), mock.patch.object(
            evals, "provider_status", return_value=mock.Mock(ready=True)
        ), mock.patch.object(evals, "call_ai", side_effect=answer):
            responses, skipped = evals.live_responses([fixture])

        self.assertIsNone(skipped)
        self.assertEqual(responses, [response])
        self.assertEqual(len(prompts), 1)
        self.assertIn('"event_contexts"', prompts[0])
        self.assertIn("Compute this event's relevant candidates", prompts[0])
        self.assertIn("provisional full-extraction", prompts[0])
        self.assertNotIn("across the ENTIRE supplied candidate list", prompts[0])


if __name__ == "__main__":
    unittest.main()
