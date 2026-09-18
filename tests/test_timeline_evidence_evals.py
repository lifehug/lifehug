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
        self.assertEqual(report["fixture_count"], 8)
        self.assertEqual(report["passed_count"], 8)
        self.assertEqual(report["retrieval_coverage"], 1.0)
        self.assertEqual(report["validation_accuracy"], 1.0)
        wrong = copy.deepcopy(responses)
        wrong[0]["events"][0]["timeline_relation"]["relation"] = "after"
        rejected = evals.evaluate(fixtures, wrong)
        self.assertEqual(rejected["passed_count"], 7)
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
        self.assertIn("compute this event's relevant candidates", prompt)
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
        self.assertIn("before it starts", prompt)
        self.assertIn("after it ends", prompt)
        self.assertIn('"early in", and "late in"', prompt)
        self.assertIn('"two weeks after the wedding" are both `after`', prompt)
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
        self.assertEqual(report["passed_count"], 8)
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

    def test_full_and_timeline_share_verbatim_eligibility_instructions(self) -> None:
        fixture = evals.load_fixtures()[-1]
        block = evals.classify_story._TIMELINE_CANDIDATE_ELIGIBILITY
        prompts = (
            evals.emitted_prompt(evals.build_case(fixture)),
            evals.emitted_timeline_prompt(evals.build_timeline_case(fixture)),
        )
        for prompt in prompts:
            with self.subTest(mode="timeline" if "Existing Events" in prompt else "full"):
                self.assertEqual(prompt.count(block), 1)
                text = " ".join(prompt.split())
                for rule in (
                    "copy the exact `event_contexts[event_key].candidate_ids` list",
                    "including alternatives and ineligible candidates",
                    "Do not recompute, filter, add, or omit IDs, even when abstaining",
                    "must have no `unresolved_entity_mentions` and no `entity_ref_ambiguities`",
                    "literal whole-candidate eligibility check: ANY nonempty list blocks the relation",
                    "even when its mention seems unrelated to the matched place or role",
                    "Do not reinterpret or dismiss the supplied flags",
                    "With complete coverage, return null relation plus `ambiguous`, preserving the entire event-local candidate ID list",
                    "Never choose an ID in `identity_blocked_candidate_ids`",
                    "`entity_refs` must be a nonempty list of exact refs supplied on THAT candidate",
                    "one exact, unchanged substring of Story Text occurring exactly once",
                    "return `source_grounding: null`",
                    "Null grounding still permits an independently valid relative `timeline_relation`",
                    "When `complete: false`, always return `incomplete` with a null relation",
                ):
                    self.assertIn(rule, text)
        sentinel = "SYNTHETIC_SHARED_ELIGIBILITY_SENTINEL"
        with mock.patch.object(evals.classify_story, "_TIMELINE_CANDIDATE_ELIGIBILITY", sentinel):
            for prompt in (
                evals.emitted_prompt(evals.build_case(fixture)),
                evals.emitted_timeline_prompt(evals.build_timeline_case(fixture)),
            ):
                self.assertEqual(prompt.count(sentinel), 1)
                self.assertNotIn("candidate must have no `unresolved_entity_mentions`", prompt)

    def test_rendered_identity_blocks_match_in_both_modes_without_snapshot_mutation(self) -> None:
        fixtures = evals.load_fixtures()
        rendered = []
        for mode in ("full", "timeline"):
            with self.subTest(mode=mode):
                case = (evals.build_timeline_case(fixtures[-1]) if mode == "timeline"
                        else evals.build_case(fixtures[-1]))
                for fixture in fixtures[5:7]:
                    case["snapshot"]["candidates"].extend(
                        evals.build_case(fixture)["snapshot"]["candidates"]
                    )
                before = copy.deepcopy(case["snapshot"])
                prompt = (evals.emitted_timeline_prompt(case) if mode == "timeline"
                          else evals.emitted_prompt(case))
                context_text = prompt.split("## Canonical Timeline Context\n", 1)[1]
                context, _ = json.JSONDecoder().raw_decode(context_text[context_text.index("{"):])
                self.assertEqual(context["identity_blocked_candidate_ids"], [
                    "node:amber-job", "node:cedar-first", "node:willow-stay",
                ])
                self.assertNotIn("node:cedar-second", context["identity_blocked_candidate_ids"])
                self.assertEqual(context["candidates"], before["candidates"])
                self.assertEqual(context["event_contexts"], before["event_contexts"])
                self.assertEqual(context["classification_snapshot"],
                                 evals.classifier_context.snapshot_metadata(before))
                self.assertEqual(case["snapshot"], before)
                self.assertNotIn("identity_blocked_candidate_ids", case["snapshot"])
                rendered.append(context["identity_blocked_candidate_ids"])
        self.assertEqual(*rendered)

    def test_identity_predicate_preserves_existing_truthiness_policy(self) -> None:
        predicate = evals.classifier_context.candidate_identity_is_resolved
        self.assertTrue(predicate({}))
        for unresolved in (None, [], "", ["unrelated caretaker"]):
            for ambiguous in (None, [], "", [{"mention": "unrelated name"}]):
                with self.subTest(unresolved=unresolved, ambiguous=ambiguous):
                    candidate = {"unresolved_entity_mentions": unresolved,
                                 "entity_ref_ambiguities": ambiguous}
                    self.assertEqual(predicate(candidate), not (unresolved or ambiguous))

    def test_renderer_and_validator_use_the_same_identity_predicate(self) -> None:
        case = evals.build_timeline_case(evals.load_fixtures()[-1])
        response = evals.recorded_timeline_response(case)
        with mock.patch.object(
            evals.classifier_context, "candidate_identity_is_resolved", return_value=False
        ) as predicate:
            context = json.loads(evals.classify_story._timeline_prompt_context(case["snapshot"]))
            self.assertEqual(context["identity_blocked_candidate_ids"],
                             ["node:cedar-first", "node:cedar-second"])
            self.assertEqual(predicate.call_count, 2)
            with self.assertRaises(evals.classifier_context.ClassifierContextError) as caught:
                evals.classifier_context.validate_response(
                    response, case["snapshot"], case["story_text"], mode="timeline",
                    existing_events=case["existing_events"], require_event_contract=True,
                )
            self.assertEqual(caught.exception.code,
                             evals.classifier_context.ContextFailureCode.CANDIDATE_AMBIGUOUS)
            self.assertEqual(predicate.call_count, 3)

    def test_ineligible_candidates_stay_in_resolution_but_cannot_be_linked(self) -> None:
        fixtures = evals.load_fixtures()[5:7]
        for fixture in fixtures:
            for mode in ("full", "timeline"):
                with self.subTest(fixture=fixture["fixture_id"], mode=mode):
                    case = (evals.build_timeline_case(fixture) if mode == "timeline"
                            else evals.build_case(fixture))
                    response = (evals.recorded_timeline_response(case) if mode == "timeline"
                                else evals.recorded_response(case))
                    kwargs = {
                        "mode": mode,
                        "existing_events": case.get("existing_events"),
                        "require_event_contract": True,
                    }
                    normalized = evals.classifier_context.validate_response(
                        copy.deepcopy(response), case["snapshot"], case["story_text"], **kwargs
                    )
                    self.assertEqual(normalized["events"][0]["timeline_resolution"]["candidate_ids"],
                                     fixture["recorded_event"]["timeline_resolution"]["candidate_ids"])
                    candidate = case["snapshot"]["candidates"][0]
                    response["events"][0]["timeline_relation"] = {
                        "relation": "within", "candidate_id": candidate["candidate_id"],
                        "entity_refs": candidate["entity_refs"],
                        "evidence": {"quote": case["story_text"]},
                    }
                    response["events"][0]["timeline_resolution"]["status"] = "linked"
                    with self.assertRaises(evals.classifier_context.ClassifierContextError) as caught:
                        evals.classifier_context.validate_response(
                            response, case["snapshot"], case["story_text"], **kwargs
                        )
                    self.assertEqual(caught.exception.code,
                                     evals.classifier_context.ContextFailureCode.CANDIDATE_AMBIGUOUS)

    def test_timeline_candidate_ids_are_event_local_and_unfiltered(self) -> None:
        fixture = evals.load_fixtures()[5]
        case = evals.build_timeline_case(fixture)
        valid = evals.recorded_timeline_response(case)
        for ids in ([], ["node:willow-stay", "node:oak-job"]):
            with self.subTest(ids=ids):
                response = copy.deepcopy(valid)
                response["events"][0]["timeline_resolution"]["candidate_ids"] = ids
                with self.assertRaises(evals.classifier_context.ClassifierContextError) as caught:
                    evals.classifier_context.validate_response(
                        response, case["snapshot"], case["story_text"], mode="timeline",
                        existing_events=case["existing_events"], require_event_contract=True,
                    )
                self.assertEqual(caught.exception.code,
                                 evals.classifier_context.ContextFailureCode.RESOLUTION_INVALID)

    def test_legacy_direct_date_without_literal_proof_can_still_link(self) -> None:
        fixture = evals.load_fixtures()[-1]
        case = evals.build_timeline_case(fixture)
        response = evals.recorded_timeline_response(case)
        self.assertEqual(case["existing_events"][0]["date"]["stated"], "2001")
        report = evals.evaluate_timeline([fixture], [response])
        self.assertEqual(report["passed_count"], 1)
        self.assertFalse(report["outcomes"][0]["grounded"])
        response["events"][0]["timeline_resolution"]["candidate_ids"] = ["node:cedar-second"]
        refused = evals.evaluate_timeline([fixture], [response])
        self.assertEqual(refused["passed_count"], 0)
        self.assertEqual(
            refused["outcomes"][0]["failure"],
            str(evals.classifier_context.ContextFailureCode.RESOLUTION_INVALID),
        )

    def test_shared_link_prerequisites_remain_strict_in_both_modes(self) -> None:
        fixture = evals.load_fixtures()[-1]
        code = evals.classifier_context.ContextFailureCode
        mutations = (
            ("empty_refs", "entity_refs", [], code.ENTITY_REFS_INVALID),
            ("foreign_refs", "entity_refs", ["place/another"], code.ENTITY_REFS_INVALID),
            ("foreign_candidate", "candidate_id", "node:another", code.CANDIDATE_UNKNOWN),
            ("paraphrase", "evidence", {"quote": "I fixed the clock."}, code.QUOTE_NOT_FOUND),
            ("repeated_quote", None, None, code.QUOTE_AMBIGUOUS),
        )
        for mode in ("full", "timeline"):
            for name, field, value, expected in mutations:
                with self.subTest(mode=mode, mutation=name):
                    case = (evals.build_timeline_case(fixture) if mode == "timeline"
                            else evals.build_case(fixture))
                    response = (evals.recorded_timeline_response(case) if mode == "timeline"
                                else evals.recorded_response(case))
                    story = case["story_text"]
                    if field:
                        response["events"][0]["timeline_relation"][field] = value
                    else:
                        story = story + " " + story
                    with self.assertRaises(evals.classifier_context.ClassifierContextError) as caught:
                        evals.classifier_context.validate_response(
                            response, case["snapshot"], story, mode=mode,
                            existing_events=case.get("existing_events"), require_event_contract=True,
                        )
                    self.assertEqual(caught.exception.code, expected)

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
