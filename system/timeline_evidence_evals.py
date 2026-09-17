#!/usr/bin/env python3
"""Synthetic recorded/live evaluation for incremental timeline evidence links."""

from __future__ import annotations

import argparse
import copy
import hashlib
import io
import json
import tempfile
import time
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace

import classifier_claims
import classifier_context
import classify_story
import timeline_evidence
from ai_provider import AIProviderError, call_ai, provider_status
from lifehug_core import REPO_DIR, read_text, write_text

FIXTURES_PATH = REPO_DIR / "tests/goldens/timeline_evidence_links.json"
QUALITY_NOTE = (
    "Recorded fixture replay validates deterministic retrieval, validation, and "
    "scoring plumbing only; run with --timeline-live to measure stable-event "
    "link quality or --live to diagnose full extraction with a configured model."
)
CATALOG_QUALITY_NOTE = (
    "The catalog probe uses synthetic ordinary files and the production filing, "
    "migration, catalog, prompt, and validation paths; it never reads a private vault."
)


def load_fixtures(path: str | Path = FIXTURES_PATH) -> list[dict]:
    value = json.loads(read_text(Path(path), encoding="utf-8"))
    if not isinstance(value, list) or not value:
        raise ValueError("timeline evidence fixtures must be a non-empty list")
    return value


def _bounds(value: str) -> dict:
    parts = value.split("/", 1)
    return {
        "best": value,
        "earliest": parts[0],
        "latest": parts[-1],
        "granularity": "range" if len(parts) == 2 else "year",
    }


def _candidate(value: dict) -> dict:
    candidate_id = str(value["candidate_id"])
    row = {
        "candidate_id": candidate_id,
        "episode_id": candidate_id.replace("node:", "episode:", 1),
        "node_kind": "episode",
        "kind": value["event_role"],
        "event_role": value["event_role"],
        "name": value["name"],
        "aliases": list(value.get("aliases") or ()),
        "canonical_roster_terms": [],
        "entity_refs": list(value["entity_refs"]),
        "unresolved_entity_mentions": [],
        "entity_ref_ambiguities": [],
        "supported_bounds": _bounds(value["bounds"]),
        "basis": "explicit",
        "conflict_state": "none",
        "alternatives": [],
        "grounding_identity": [{
            "claim_type": "date",
            "subject_ref": value["entity_refs"][0],
            "subject_mention": value["name"],
            "source_path": f"sources/manual/{candidate_id.removeprefix('node:')}.md",
            "source_revision": "sha256:" + "a" * 64,
            "temporal_value": _bounds(value["bounds"]),
            "evidence": [{"quote": "Synthetic independent date evidence."}],
        }],
    }
    row["reference_keys"] = timeline_evidence.candidate_reference_keys(row)
    return row


def build_case(fixture: dict) -> dict:
    story_text = str(fixture["source_text"])
    candidates = [_candidate(value) for value in fixture.get("candidates") or ()]
    provisional = {
        "title": str(fixture.get("title") or "Synthetic source"),
        "description": story_text,
        "subject": "self",
        "places": [],
        "date": None,
    }
    context = timeline_evidence.build_event_context(provisional, candidates)
    selected = set(context["candidate_ids"])
    for row in candidates:
        row["candidate_set_complete"] = bool(context["complete"])
        row["relevant_event_keys"] = (
            [context["event_key"]] if row["candidate_id"] in selected else []
        )
    source_revision = "sha256:" + hashlib.sha256(
        story_text.encode("utf-8")
    ).hexdigest()
    event_contexts = {context["event_key"]: context}
    snapshot = {
        "schema_version": 1,
        "source_revision": source_revision,
        "context_digest": timeline_evidence.digest({
            "schema_version": 1,
            "event_contexts": event_contexts,
            "human_identity_decisions": [],
        }),
        "prompt_version": classifier_context.PROMPT_VERSION,
        "extractor_version": classifier_context.EXTRACTOR_VERSION,
        "context_complete": context["complete"],
        "context_truncated": not context["complete"],
        "candidate_count": len(candidates),
        "remaining_candidate_count": context["remaining_candidate_count"],
        "catalog_omitted_count": 0,
        "remaining_decision_count": 0,
        "candidates": candidates,
        "event_contexts": event_contexts,
        "human_identity_decisions": [],
        "prior_event_identities": [],
        "source_roster_evidence": [],
        "grounding_allowed": True,
    }
    return {"fixture": fixture, "story_text": story_text, "snapshot": snapshot}


def recorded_response(case: dict) -> dict:
    return {
        "_classification_mode": "full",
        "_classification_snapshot": classifier_context.snapshot_metadata(case["snapshot"]),
        "events": [copy.deepcopy(case["fixture"]["recorded_event"])],
    }


def emitted_prompt(case: dict) -> str:
    fixture = case["fixture"]
    with tempfile.TemporaryDirectory(prefix="lifehug-timeline-eval-") as raw_root:
        root = Path(raw_root)
        source = root / "sources/manual/source.md"
        source.parent.mkdir(parents=True)
        write_text(source, case["story_text"])
        old_values = (
            classify_story.REPO_DIR,
            classify_story.SOURCES_DIR,
            classify_story.CLASSIFICATIONS_DIR,
        )
        try:
            classify_story.REPO_DIR = root
            classify_story.SOURCES_DIR = root / "sources"
            classify_story.CLASSIFICATIONS_DIR = root / "state/classifications"
            return classify_story.build_prompt(
                source,
                {
                    "title": str(fixture.get("title") or "Synthetic source"),
                    "type": "synthetic-eval",
                },
                case["story_text"],
                context_snapshot=case["snapshot"],
                mode="full",
                include_candidates=False,
            )
        finally:
            (
                classify_story.REPO_DIR,
                classify_story.SOURCES_DIR,
                classify_story.CLASSIFICATIONS_DIR,
            ) = old_values


def build_timeline_case(fixture: dict) -> dict:
    """Use one stored extraction and refresh only its evidence-link fields."""
    case = build_case(fixture)
    existing = copy.deepcopy(fixture["recorded_event"])
    existing["source_grounding"] = None
    existing["timeline_relation"] = None
    existing.pop("timeline_resolution", None)
    context = timeline_evidence.build_event_context(
        existing,
        copy.deepcopy(case["snapshot"]["candidates"]),
    )
    for candidate in case["snapshot"]["candidates"]:
        candidate["candidate_set_complete"] = bool(context["complete"])
        candidate["relevant_event_keys"] = (
            [context["event_key"]]
            if candidate["candidate_id"] in context["candidate_ids"] else []
        )
    case["snapshot"]["event_contexts"] = {context["event_key"]: context}
    case["snapshot"]["context_complete"] = bool(context["complete"])
    case["snapshot"]["context_truncated"] = not context["complete"]
    case["snapshot"]["remaining_candidate_count"] = context[
        "remaining_candidate_count"
    ]
    case["snapshot"]["context_digest"] = timeline_evidence.digest({
        "schema_version": 1,
        "event_contexts": case["snapshot"]["event_contexts"],
        "human_identity_decisions": [],
    })
    case["existing_events"] = [existing]
    return case


def recorded_timeline_response(case: dict) -> dict:
    expected = case["fixture"]["recorded_event"]
    return {
        "_classification_mode": "timeline",
        "_classification_snapshot": classifier_context.snapshot_metadata(case["snapshot"]),
        "events": [{
            "event_key": timeline_evidence.event_key(case["existing_events"][0]),
            "source_grounding": copy.deepcopy(expected.get("source_grounding")),
            "timeline_relation": copy.deepcopy(expected.get("timeline_relation")),
            "timeline_resolution": copy.deepcopy(expected["timeline_resolution"]),
        }],
    }


def emitted_timeline_prompt(case: dict) -> str:
    fixture = case["fixture"]
    with tempfile.TemporaryDirectory(prefix="lifehug-timeline-mode-eval-") as raw_root:
        root = Path(raw_root)
        source = root / "sources/manual/source.md"
        source.parent.mkdir(parents=True)
        write_text(source, case["story_text"])
        old_values = (
            classify_story.REPO_DIR,
            classify_story.SOURCES_DIR,
            classify_story.CLASSIFICATIONS_DIR,
        )
        try:
            classify_story.REPO_DIR = root
            classify_story.SOURCES_DIR = root / "sources"
            classify_story.CLASSIFICATIONS_DIR = root / "state/classifications"
            path = classify_story.classification_path(source)
            path.parent.mkdir(parents=True)
            write_text(path, json.dumps({
                "source_path": "sources/manual/source.md",
                "events": case["existing_events"],
            }))
            return classify_story.build_prompt(
                source,
                {
                    "title": str(fixture.get("title") or "Synthetic source"),
                    "type": "synthetic-eval",
                },
                case["story_text"],
                context_snapshot=case["snapshot"],
                mode="timeline",
                include_candidates=False,
            )
        finally:
            (
                classify_story.REPO_DIR,
                classify_story.SOURCES_DIR,
                classify_story.CLASSIFICATIONS_DIR,
            ) = old_values


def _full_response(snapshot: dict, event: dict) -> dict:
    context = next(iter(snapshot.get("event_contexts", {}).values()))
    row = copy.deepcopy(event)
    row["timeline_resolution"] = {
        "status": "missing_evidence",
        "candidate_ids": list(context.get("candidate_ids") or ()),
        "reason": "No contextual relation is asserted by this producer source.",
    }
    return {
        "_classification_mode": "full",
        "_classification_snapshot": classifier_context.snapshot_metadata(snapshot),
        "people": [],
        "places": [],
        "time_periods": [],
        "themes": [],
        "projects": [],
        "contradictions": [],
        "possible_outputs": [],
        "focus_opportunities": [],
        "self_understanding_insights": [],
        "suggested_sensitivity": "private",
        "sensitivity_reason": "Synthetic catalog evaluation.",
        "scene_slots": {},
        "situation_vs_story": "balanced",
        "events": [row],
        "candidate_questions": [],
    }


def build_filed_catalog_case() -> dict:
    """Build a held-out prompt from grounded ordinary files, never hand-built candidates."""
    with tempfile.TemporaryDirectory(prefix="lifehug-timeline-catalog-eval-") as raw_root:
        root = Path(raw_root)
        sources = root / "sources/manual"
        classifications = root / "state/classifications"
        rosters = root / "state/entity_rosters"
        for directory in (sources, classifications, rosters, root / "answers"):
            directory.mkdir(parents=True, exist_ok=True)
        write_text(rosters / "organization.json", json.dumps({
            "version": 1,
            "type": "organization",
            "entities": [{
                "name": "Harborlight",
                "slug": "harborlight",
                "aliases": [],
            }],
        }))

        producer_rows = (
            (
                "opening.md",
                "I opened Harborlight in 2011.",
                "Harborlight opening",
                "2011",
            ),
            (
                "employment.md",
                "Harborlight hired me in 2016.",
                "Harborlight employment",
                "2016",
            ),
        )
        old_values = {
            name: getattr(classify_story, name)
            for name in (
                "REPO_DIR", "SOURCES_DIR", "MANUAL_SOURCES_DIR", "ANSWERS_DIR",
                "CLASSIFICATIONS_DIR", "QUESTION_CANDIDATES_FILE",
            )
        }
        try:
            classify_story.REPO_DIR = root
            classify_story.SOURCES_DIR = root / "sources"
            classify_story.MANUAL_SOURCES_DIR = sources
            classify_story.ANSWERS_DIR = root / "answers"
            classify_story.CLASSIFICATIONS_DIR = classifications
            classify_story.QUESTION_CANDIDATES_FILE = (
                root / "state/question_candidates.json"
            )
            for filename, story_text, title, year in producer_rows:
                source = sources / filename
                write_text(
                    source,
                    f"---\ntitle: Synthetic source\n---\n{story_text}\n",
                )
                snapshot = classifier_context.build_context_snapshot(root, source)
                event = {
                    "title": title,
                    "description": story_text,
                    "subject": "Harborlight",
                    "places": [],
                    "date": {
                        "stated": year,
                        "age": None,
                        "anchor_ref": None,
                        "relation": None,
                    },
                    "source_grounding": {
                        "quote": story_text,
                        "temporal_quote": year,
                        "subject_quote": "Harborlight",
                        "kind": "date",
                    },
                    "timeline_relation": None,
                }
                with redirect_stdout(io.StringIO()):
                    result = classify_story.classify_file(
                        source,
                        "synthetic-recorded",
                        skip_candidates=True,
                        precomputed_result=_full_response(snapshot, event),
                    )
                if result != 0:
                    raise RuntimeError("synthetic producer classification failed")

            with redirect_stdout(io.StringIO()):
                classifier_claims.migrate_classifier_moments(
                    root,
                    classifications_dir=classifications,
                    publish=False,
                    dry_run=False,
                    now="2026-09-17T12:00:00Z",
                )
            story_text = "The borrowed desk is where I launched Harborlight."
            consumer = sources / "source.md"
            write_text(
                consumer,
                f"---\ntitle: Synthetic source\n---\n{story_text}\n",
            )
            existing_event = {
                "title": "Harborlight launch",
                "description": story_text,
                "subject": "Harborlight",
                "places": [],
                "when_hint": None,
                "anchor": None,
                "date": None,
                "source_grounding": None,
                "timeline_relation": None,
            }
            write_text(
                classify_story.classification_path(consumer),
                json.dumps({
                    "source_path": "sources/manual/source.md",
                    "events": [existing_event],
                }),
            )
            snapshot = classifier_context.build_context_snapshot(root, consumer)
            candidates = [
                row for row in snapshot["candidates"]
                if row.get("entity_refs") == ["organization/harborlight"]
            ]
            roles = {row.get("event_role") for row in candidates}
            if roles != {"founded", "job"}:
                raise RuntimeError(f"ordinary catalog roles were not preserved: {sorted(roles)}")
            founded = next(row for row in candidates if row["event_role"] == "founded")
            prompt = classify_story.build_prompt(
                consumer,
                {"title": "Synthetic source", "type": "synthetic-eval"},
                story_text,
                context_snapshot=snapshot,
                mode="timeline",
                include_candidates=False,
            )
            return {
                "story_text": story_text,
                "snapshot": snapshot,
                "prompt": prompt,
                "expected_candidate_id": founded["candidate_id"],
                "candidate_roles": sorted(roles),
                "candidate_ids": sorted(row["candidate_id"] for row in candidates),
                "existing_events": [existing_event],
            }
        finally:
            for name, value in old_values.items():
                setattr(classify_story, name, value)


def catalog_live_probe() -> tuple[dict, str | None]:
    """Run one configured-model case over a real synthetic filed-fact catalog."""
    case = build_filed_catalog_case()
    model = classify_story.get_model(SimpleNamespace(model=None))
    status = provider_status(model, probe=False)
    if not getattr(status, "ready", False):
        return {}, "no configured live provider"
    try:
        response = classify_story.extract_json(call_ai(case["prompt"], model))
        normalized = classifier_context.validate_response(
            response,
            case["snapshot"],
            case["story_text"],
            mode="timeline",
            existing_events=case["existing_events"],
            require_event_contract=True,
        )
    except (AIProviderError, json.JSONDecodeError, ValueError) as exc:
        return {}, str(exc)
    linked = [
        event for event in normalized["events"]
        if (event.get("timeline_resolution") or {}).get("status") == "linked"
        and (event.get("timeline_relation") or {}).get("candidate_id")
        == case["expected_candidate_id"]
        and (event.get("timeline_relation") or {}).get("relation") == "within"
    ]
    return {
        "candidate_roles": case["candidate_roles"],
        "candidate_ids": case["candidate_ids"],
        "expected_candidate_id": case["expected_candidate_id"],
        "event_count": len(normalized["events"]),
        "matching_link_count": len(linked),
        "passed": bool(linked),
    }, None


def _event_outcome(event: dict) -> dict:
    resolution = event.get("timeline_resolution") or {}
    relation = event.get("timeline_relation") or {}
    date = event.get("date") or {}
    return {
        "status": resolution.get("status"),
        "candidate_id": relation.get("candidate_id"),
        "relation": relation.get("relation"),
        "grounded": event.get("source_grounding") is not None,
        "date_anchor_ref": date.get("anchor_ref"),
        "date_relation": date.get("relation"),
    }


def _outcome_matches(actual: dict, oracle: dict) -> bool:
    required = ("status", "candidate_id", "relation", "grounded")
    optional = ("date_anchor_ref", "date_relation")
    return all(actual.get(key) == oracle.get(key) for key in required) and all(
        key not in oracle or actual.get(key) == oracle.get(key)
        for key in optional
    )


def evaluate(fixtures: list[dict], responses: list[dict]) -> dict:
    started = time.perf_counter()
    if len(responses) != len(fixtures):
        raise ValueError("one response is required for every evaluation fixture")
    outcomes = []
    retrieval_elapsed = 0.0
    validation_elapsed = 0.0
    for fixture, response in zip(fixtures, responses):
        retrieval_started = time.perf_counter()
        case = build_case(fixture)
        context = next(iter(case["snapshot"]["event_contexts"].values()))
        expected_candidates = set(
            fixture["recorded_event"]["timeline_resolution"]["candidate_ids"]
        )
        retrieved_candidates = set(context["candidate_ids"])
        retrieval_passed = expected_candidates <= retrieved_candidates
        retrieval_elapsed += time.perf_counter() - retrieval_started
        failure = None
        status = candidate_id = None
        grounded = False
        event_count = 0
        unexpected_ordered_links = 0
        actual_outcomes: list[dict] = []
        additional_outcomes: list[dict] = []
        unexpected_outcomes: list[dict] = []
        validation_started = time.perf_counter()
        try:
            normalized = classifier_context.validate_response(
                copy.deepcopy(response),
                case["snapshot"],
                case["story_text"],
                mode="full",
                require_event_contract=True,
            )
            event_count = len(normalized["events"])
            expected = fixture["expected"]
            expected_relation = fixture["recorded_event"].get("timeline_relation") or {}
            primary_oracle = {
                **expected,
                "relation": expected_relation.get("relation"),
            }
            extra_oracles = list(fixture.get("allowed_extra_outcomes") or ())
            primary_matches = []
            for index, event in enumerate(normalized["events"]):
                actual = _event_outcome(event)
                actual_outcomes.append({"event_index": index, **actual})
                if _outcome_matches(actual, primary_oracle):
                    primary_matches.append(actual)
                    continue
                matched_extra = next(
                    (
                        oracle_index
                        for oracle_index, oracle in enumerate(extra_oracles)
                        if _outcome_matches(actual, oracle)
                    ),
                    None,
                )
                if matched_extra is not None:
                    additional_outcomes.append({
                        "event_index": index,
                        "oracle_index": matched_extra,
                        **actual,
                    })
                    continue
                unexpected_outcomes.append({"event_index": index, **actual})
                if actual.get("relation") in ("before", "after"):
                    unexpected_ordered_links += 1
            if primary_matches:
                status = primary_matches[0]["status"]
                candidate_id = primary_matches[0]["candidate_id"]
                grounded = primary_matches[0]["grounded"]
            elif failure is None:
                failure = "expected_target_missing"
            if unexpected_outcomes:
                failure = "unexpected_event_outcome"
        except (KeyError, TypeError, ValueError, classifier_context.ClassifierContextError) as exc:
            failure = getattr(exc, "code", type(exc).__name__)
        validation_elapsed += time.perf_counter() - validation_started
        expected = fixture["expected"]
        validation_passed = (
            failure is None
            and status == expected["status"]
            and candidate_id == expected["candidate_id"]
            and grounded is bool(expected["grounded"])
        )
        outcomes.append({
            "fixture_id": fixture["fixture_id"],
            "passed": retrieval_passed and validation_passed,
            "retrieval_passed": retrieval_passed,
            "validation_passed": validation_passed,
            "status": status,
            "candidate_id": candidate_id,
            "grounded": grounded,
            "event_count": event_count,
            "actual_outcomes": actual_outcomes,
            "additional_outcomes": additional_outcomes,
            "unexpected_outcomes": unexpected_outcomes,
            "unexpected_ordered_links": unexpected_ordered_links,
            "failure": str(failure) if failure is not None else None,
        })
    passed_count = sum(row["passed"] for row in outcomes)
    retrieval_count = sum(row["retrieval_passed"] for row in outcomes)
    validation_count = sum(row["validation_passed"] for row in outcomes)
    return {
        "fixture_count": len(fixtures),
        "passed_count": passed_count,
        "retrieval_coverage": retrieval_count / len(fixtures) if fixtures else 0.0,
        "validation_accuracy": validation_count / len(fixtures) if fixtures else 0.0,
        "stage_timings_ms": {
            "retrieval": round(retrieval_elapsed * 1000, 3),
            "validation": round(validation_elapsed * 1000, 3),
            "total": round((time.perf_counter() - started) * 1000, 3),
        },
        "outcomes": outcomes,
    }


def evaluate_timeline(fixtures: list[dict], responses: list[dict]) -> dict:
    """Score exact link-only deltas against immutable stored extractions."""
    started = time.perf_counter()
    if len(responses) != len(fixtures):
        raise ValueError("one response is required for every evaluation fixture")
    outcomes = []
    retrieval_elapsed = validation_elapsed = 0.0
    for fixture, response in zip(fixtures, responses):
        retrieval_started = time.perf_counter()
        case = build_timeline_case(fixture)
        context = next(iter(case["snapshot"]["event_contexts"].values()))
        expected_candidates = set(
            fixture["recorded_event"]["timeline_resolution"]["candidate_ids"]
        )
        retrieval_passed = expected_candidates <= set(context["candidate_ids"])
        retrieval_elapsed += time.perf_counter() - retrieval_started
        failure = None
        status = candidate_id = relation_kind = None
        grounded = False
        validation_started = time.perf_counter()
        try:
            normalized = classifier_context.validate_response(
                copy.deepcopy(response),
                case["snapshot"],
                case["story_text"],
                mode="timeline",
                existing_events=case["existing_events"],
                require_event_contract=True,
            )
            if len(normalized["events"]) != 1:
                raise ValueError("timeline mode must return the one stored event")
            event = normalized["events"][0]
            status = event["timeline_resolution"]["status"]
            relation = event.get("timeline_relation") or {}
            candidate_id = relation.get("candidate_id")
            relation_kind = relation.get("relation")
            grounded = event.get("source_grounding") is not None
        except (KeyError, TypeError, ValueError, classifier_context.ClassifierContextError) as exc:
            failure = getattr(exc, "code", type(exc).__name__)
        validation_elapsed += time.perf_counter() - validation_started
        expected = fixture["expected"]
        expected_relation = fixture["recorded_event"].get("timeline_relation") or {}
        validation_passed = (
            failure is None
            and status == expected["status"]
            and candidate_id == expected["candidate_id"]
            and relation_kind == expected_relation.get("relation")
            and grounded is bool(expected["grounded"])
        )
        outcomes.append({
            "fixture_id": fixture["fixture_id"],
            "passed": retrieval_passed and validation_passed,
            "retrieval_passed": retrieval_passed,
            "validation_passed": validation_passed,
            "status": status,
            "candidate_id": candidate_id,
            "relation": relation_kind,
            "grounded": grounded,
            "failure": str(failure) if failure is not None else None,
        })
    return {
        "fixture_count": len(fixtures),
        "passed_count": sum(row["passed"] for row in outcomes),
        "retrieval_coverage": (
            sum(row["retrieval_passed"] for row in outcomes) / len(fixtures)
            if fixtures else 0.0
        ),
        "validation_accuracy": (
            sum(row["validation_passed"] for row in outcomes) / len(fixtures)
            if fixtures else 0.0
        ),
        "stage_timings_ms": {
            "retrieval": round(retrieval_elapsed * 1000, 3),
            "validation": round(validation_elapsed * 1000, 3),
            "total": round((time.perf_counter() - started) * 1000, 3),
        },
        "outcomes": outcomes,
    }


def lifecycle_probe() -> dict:
    """Exercise selective invalidation without claiming a model evaluation."""
    started = time.perf_counter()
    event = {
        "title": "Blue letter",
        "description": "I found the blue letter during our River House stay.",
        "subject": "self",
        "places": ["River House"],
        "date": None,
    }
    candidate = _candidate({
        "candidate_id": "node:river-stay",
        "name": "River House stay",
        "event_role": "residence",
        "entity_refs": ["place/river-house"],
        "bounds": "1991/1993",
    })
    before = timeline_evidence.build_event_context(copy.deepcopy(event), [])
    after_new_evidence = timeline_evidence.build_event_context(
        copy.deepcopy(event), [copy.deepcopy(candidate)]
    )
    corrected = copy.deepcopy(candidate)
    corrected["supported_bounds"] = _bounds("1992/1994")
    corrected["grounding_identity"][0].update({
        "source_revision": "sha256:" + "b" * 64,
        "temporal_value": _bounds("1992/1994"),
        "evidence": [{"quote": "Corrected synthetic date evidence."}],
    })
    after_bound_correction = timeline_evidence.build_event_context(
        copy.deepcopy(event), [corrected]
    )
    unchanged = timeline_evidence.build_event_context(
        copy.deepcopy(event), [copy.deepcopy(corrected)]
    )
    checks = {
        "new_evidence_invalidates": (
            before["input_fingerprint"] != after_new_evidence["input_fingerprint"]
            and after_new_evidence["candidate_ids"] == ["node:river-stay"]
        ),
        "bound_only_reuses_link": (
            after_bound_correction["input_fingerprint"]
            == after_new_evidence["input_fingerprint"]
        ),
        "unchanged_is_stable": unchanged == after_bound_correction,
    }
    return {
        "before": {"candidate_ids": before["candidate_ids"]},
        "after_new_evidence": {
            "candidate_ids": after_new_evidence["candidate_ids"],
        },
        "after_bound_correction": {
            "candidate_ids": after_bound_correction["candidate_ids"],
            "refresh_required": not checks["bound_only_reuses_link"],
        },
        "unchanged": {"refresh_required": not checks["unchanged_is_stable"]},
        "checks": checks,
        "elapsed_ms": round((time.perf_counter() - started) * 1000, 3),
    }


def live_responses(fixtures: list[dict]) -> tuple[list[dict], str | None]:
    model = classify_story.get_model(SimpleNamespace(model=None))
    status = provider_status(model, probe=False)
    if not getattr(status, "ready", False):
        return [], "no configured live provider"
    responses = []
    try:
        for fixture in fixtures:
            case = build_case(fixture)
            responses.append(classify_story.extract_json(call_ai(emitted_prompt(case), model)))
    except (AIProviderError, json.JSONDecodeError, ValueError) as exc:
        return [], str(exc)
    return responses, None


def timeline_live_responses(fixtures: list[dict]) -> tuple[list[dict], str | None]:
    model = classify_story.get_model(SimpleNamespace(model=None))
    status = provider_status(model, probe=False)
    if not getattr(status, "ready", False):
        return [], "no configured live provider"
    responses = []
    try:
        for fixture in fixtures:
            case = build_timeline_case(fixture)
            responses.append(classify_story.extract_json(
                call_ai(emitted_timeline_prompt(case), model)
            ))
    except (AIProviderError, json.JSONDecodeError, ValueError) as exc:
        return [], str(exc)
    return responses, None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--live", action="store_true")
    modes.add_argument("--timeline-live", action="store_true")
    modes.add_argument("--catalog-live", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    if args.catalog_live:
        report, skipped = catalog_live_probe()
        result = {
            "evaluation": "timeline-evidence-links-filed-catalog",
            "mode": "catalog-live",
            "quality_note": CATALOG_QUALITY_NOTE,
            "skipped": skipped,
            "report": report,
            "passed": skipped is None and bool(report.get("passed")),
        }
        print(json.dumps(result, indent=2, sort_keys=True) if args.json else result)
        return 0 if result["passed"] or skipped is not None else 1
    fixtures = load_fixtures()
    if args.timeline_live:
        responses, skipped = timeline_live_responses(fixtures)
    elif args.live:
        responses, skipped = live_responses(fixtures)
    else:
        responses = [recorded_response(build_case(fixture)) for fixture in fixtures]
        skipped = None
    report = (
        evaluate_timeline(fixtures, responses)
        if skipped is None and args.timeline_live
        else evaluate(fixtures, responses) if skipped is None else {}
    )
    lifecycle = lifecycle_probe()
    report_passed = (
        skipped is None
        and report.get("retrieval_coverage") == 1.0
        and report.get("validation_accuracy") == 1.0
        and all(lifecycle["checks"].values())
    )
    result = {
        "evaluation": "timeline-evidence-links",
        "mode": (
            "timeline-live" if args.timeline_live else
            "live" if args.live else "recorded"
        ),
        "quality_note": None if args.live or args.timeline_live else QUALITY_NOTE,
        "skipped": skipped,
        "report": report,
        "lifecycle": lifecycle,
        "passed": report_passed,
    }
    print(json.dumps(result, indent=2, sort_keys=True) if args.json else result)
    return 0 if result["passed"] or skipped is not None else 1


if __name__ == "__main__":
    raise SystemExit(main())
