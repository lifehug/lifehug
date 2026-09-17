"""Recorded and optional-live timeline evidence evaluation contract."""

from __future__ import annotations

import copy
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
        wrong = copy.deepcopy(responses)
        wrong[0]["events"][0]["timeline_relation"]["relation"] = "after"
        rejected = evals.evaluate(fixtures, wrong)
        self.assertEqual(rejected["passed_count"], 4)
        self.assertFalse(rejected["outcomes"][0]["validation_passed"])
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

        def answer(prompt, model):
            prompts.append(prompt)
            self.assertEqual(model, evals.classify_story.DEFAULT_MODEL)
            return json.dumps(response)

        with mock.patch.object(
            evals.classify_story, "load_config", return_value={}
        ), mock.patch.object(
            evals, "provider_status", return_value=mock.Mock(ready=True)
        ), mock.patch.object(evals, "call_ai", side_effect=answer):
            responses, skipped = evals.live_responses([fixture])

        self.assertIsNone(skipped)
        self.assertEqual(responses, [response])
        self.assertEqual(len(prompts), 1)
        prompt = " ".join(prompts[0].split())
        self.assertIn('"event_contexts"', prompt)
        self.assertIn("Compute this event's relevant candidates", prompt)
        self.assertIn("provisional full-extraction", prompt)
        self.assertIn("Timeline Evidence Uses Two Independent Decisions", prompt)
        self.assertIn("does NOT need a calendar date or age", prompt)
        self.assertIn("an empty candidate set for a real event is `missing_evidence`", prompt)
        self.assertIn(
            "A supported rough `before` or `after` placement is also valid",
            prompt,
        )
        self.assertIn("do not invent `within` merely to tighten bounds", prompt)
        self.assertIn(
            "CURRENT EXTRACTED EVENT relative to SELECTED CANDIDATE",
            prompt,
        )
        self.assertIn("candidate's WHOLE occurrence", prompt)
        self.assertIn("before that duration starts", prompt)
        self.assertIn("after it ends", prompt)
        self.assertIn('"early in", and "late in"', prompt)
        self.assertIn('"After the wedding"', prompt)
        self.assertIn("date.anchor_ref", prompt)
        self.assertIn(
            f"1-{evals.timeline_evidence.MAX_RESOLUTION_REASON_CHARS} character explanation",
            prompt,
        )
        self.assertIn(
            f"{evals.timeline_evidence.MAX_RESOLUTION_REASON_CHARS} characters",
            prompt,
        )
        self.assertNotIn("TIGHTEST SUPPORTED TIME BOUNDS", prompt)
        self.assertNotIn("across the ENTIRE supplied candidate list", prompt)
        self.assertNotIn(fixture["fixture_id"], prompt)

    def test_timeline_live_path_uses_stored_event_deltas(self) -> None:
        fixture = evals.load_fixtures()[0]
        case = evals.build_timeline_case(fixture)
        response = evals.recorded_timeline_response(case)
        prompts = []

        def answer(prompt, model):
            prompts.append(prompt)
            self.assertEqual(model, evals.classify_story.DEFAULT_MODEL)
            return json.dumps(response)

        with mock.patch.object(
            evals.classify_story, "load_config", return_value={}
        ), mock.patch.object(
            evals, "provider_status", return_value=mock.Mock(ready=True)
        ), mock.patch.object(evals, "call_ai", side_effect=answer):
            responses, skipped = evals.timeline_live_responses([fixture])

        self.assertIsNone(skipped)
        self.assertEqual(responses, [response])
        self.assertIn("refreshing only the timeline evidence", prompts[0])
        self.assertIn("Existing Events (immutable", prompts[0])
        self.assertNotIn(fixture["fixture_id"], prompts[0])

    def test_recorded_timeline_mode_scores_all_stable_events_exactly(self) -> None:
        fixtures = evals.load_fixtures()
        responses = [
            evals.recorded_timeline_response(evals.build_timeline_case(row))
            for row in fixtures
        ]
        report = evals.evaluate_timeline(fixtures, responses)
        self.assertEqual(report["passed_count"], 5)
        self.assertEqual(report["retrieval_coverage"], 1.0)
        self.assertEqual(report["validation_accuracy"], 1.0)

    def test_machine_fixture_ids_never_enter_model_prompts(self) -> None:
        for fixture in evals.load_fixtures():
            with self.subTest(fixture_id=fixture["fixture_id"]):
                prompt = evals.emitted_prompt(evals.build_case(fixture))
                self.assertNotIn(fixture["fixture_id"], prompt)
                timeline_prompt = evals.emitted_timeline_prompt(
                    evals.build_timeline_case(fixture)
                )
                self.assertNotIn(fixture["fixture_id"], timeline_prompt)

    def test_full_scorer_allows_safe_split_but_rejects_extra_ordered_link(self) -> None:
        fixture = evals.load_fixtures()[0]
        case = evals.build_case(fixture)
        response = evals.recorded_response(case)
        extra = {
            "title": "Northstar payroll",
            "description": "I later joined Northstar's payroll.",
            "subject": "self",
            "places": [],
            "date": {
                "stated": None,
                "age": None,
                "anchor_ref": "launched Northstar from the spare room",
                "relation": "after",
            },
            "source_grounding": None,
            "timeline_relation": {
                "relation": "within",
                "candidate_id": "node:northstar-job",
                "entity_refs": ["organization/northstar"],
                "evidence": {"quote": "before I ever joined its payroll"},
            },
            "timeline_resolution": {
                "status": "linked",
                "candidate_ids": ["node:northstar-founded", "node:northstar-job"],
                "reason": "The payroll wording identifies the employment candidate.",
            },
        }
        response["events"].append(extra)
        safe = evals.evaluate([fixture], [response])
        self.assertEqual(safe["passed_count"], 1)
        self.assertEqual(safe["outcomes"][0]["event_count"], 2)
        self.assertEqual(len(safe["outcomes"][0]["additional_outcomes"]), 1)

        canonical = copy.deepcopy(response)
        canonical["events"][1]["date"]["anchor_ref"] = "node:northstar-founded"
        self.assertEqual(evals.evaluate([fixture], [canonical])["passed_count"], 1)

        wrong_raw_direction = copy.deepcopy(response)
        wrong_raw_direction["events"][1]["date"]["relation"] = "before"
        self.assertEqual(
            evals.evaluate([fixture], [wrong_raw_direction])["passed_count"], 0
        )

        wrong_raw_target = copy.deepcopy(response)
        wrong_raw_target["events"][1]["date"]["anchor_ref"] = (
            "joined Northstar's payroll"
        )
        self.assertEqual(
            evals.evaluate([fixture], [wrong_raw_target])["passed_count"], 0
        )

        wrong = copy.deepcopy(response)
        wrong["events"][1]["timeline_relation"]["relation"] = "after"
        unsafe = evals.evaluate([fixture], [wrong])
        self.assertEqual(unsafe["passed_count"], 0)
        self.assertEqual(
            unsafe["outcomes"][0]["failure"], "unexpected_event_outcome"
        )

        swapped = copy.deepcopy(response)
        swapped["events"][0]["timeline_relation"]["candidate_id"] = (
            "node:northstar-job"
        )
        swapped["events"][1]["timeline_relation"]["candidate_id"] = (
            "node:northstar-founded"
        )
        rejected = evals.evaluate([fixture], [swapped])
        self.assertEqual(rejected["passed_count"], 0)
        self.assertIsNotNone(rejected["outcomes"][0]["failure"])

    def test_filed_catalog_probe_uses_ordinary_grounded_producers(self) -> None:
        case = evals.build_filed_catalog_case()
        self.assertEqual(case["candidate_roles"], ["founded", "job"])
        self.assertEqual(len(case["candidate_ids"]), 2)
        self.assertIn(case["expected_candidate_id"], case["candidate_ids"])
        self.assertIn("The borrowed desk is where I launched Harborlight.", case["prompt"])
        self.assertIn('"event_role": "founded"', case["prompt"])
        self.assertIn('"event_role": "job"', case["prompt"])
        self.assertNotIn("fixture_id", case["prompt"])

    def test_catalog_live_path_validates_the_model_response(self) -> None:
        case = evals.build_filed_catalog_case()
        context = next(iter(case["snapshot"]["event_contexts"].values()))
        response = {
            "_classification_mode": "timeline",
            "_classification_snapshot": evals.classifier_context.snapshot_metadata(
                case["snapshot"]
            ),
            "events": [{
                "event_key": evals.timeline_evidence.event_key(case["existing_events"][0]),
            "source_grounding": None,
            "timeline_relation": {
                "relation": "within",
                "candidate_id": case["expected_candidate_id"],
                "entity_refs": ["organization/harborlight"],
                "evidence": {"quote": case["story_text"]},
            },
                "timeline_resolution": {
                    "status": "linked",
                    "candidate_ids": list(context["candidate_ids"]),
                    "reason": "The launch wording identifies the opening candidate.",
                },
            }],
        }
        with mock.patch.object(
            evals.classify_story, "load_config", return_value={}
        ), mock.patch.object(
            evals, "provider_status", return_value=mock.Mock(ready=True)
        ), mock.patch.object(
            evals, "call_ai", return_value=json.dumps(response)
        ):
            report, skipped = evals.catalog_live_probe()
        self.assertIsNone(skipped)
        self.assertTrue(report["passed"])
        self.assertEqual(report["matching_link_count"], 1)


if __name__ == "__main__":
    unittest.main()
