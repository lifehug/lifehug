#!/usr/bin/env python3
"""Synthetic recorded/live evaluation for incremental timeline evidence links."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import tempfile
import time
from pathlib import Path

import classifier_context
import classify_story
import timeline_evidence
from ai_provider import AIProviderError, call_ai, provider_status
from lifehug_core import REPO_DIR, load_config

FIXTURES_PATH = REPO_DIR / "tests/goldens/timeline_evidence_links.json"
QUALITY_NOTE = (
    "Recorded fixture replay validates deterministic retrieval, validation, and "
    "scoring plumbing only; run with --live to measure a configured model."
)


def load_fixtures(path: str | Path = FIXTURES_PATH) -> list[dict]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
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
        "title": fixture["fixture_id"],
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
        source = root / "sources/manual" / f"{fixture['fixture_id']}.md"
        source.parent.mkdir(parents=True)
        source.write_text(case["story_text"], encoding="utf-8")
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
                {"title": fixture["fixture_id"], "type": "synthetic-eval"},
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
        validation_started = time.perf_counter()
        try:
            normalized = classifier_context.validate_response(
                copy.deepcopy(response),
                case["snapshot"],
                case["story_text"],
                mode="full",
                require_event_contract=True,
            )
            if len(normalized["events"]) != 1:
                raise ValueError("expected exactly one event")
            event = normalized["events"][0]
            status = event["timeline_resolution"]["status"]
            relation = event.get("timeline_relation") or {}
            candidate_id = relation.get("candidate_id")
            grounded = event.get("source_grounding") is not None
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
    config = load_config()
    model = str(config.get("classify_model") or "sonnet-class")
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    fixtures = load_fixtures()
    if args.live:
        responses, skipped = live_responses(fixtures)
    else:
        responses = [recorded_response(build_case(fixture)) for fixture in fixtures]
        skipped = None
    report = evaluate(fixtures, responses) if skipped is None else {}
    lifecycle = lifecycle_probe()
    report_passed = (
        skipped is None
        and report.get("retrieval_coverage") == 1.0
        and report.get("validation_accuracy") == 1.0
        and all(lifecycle["checks"].values())
    )
    result = {
        "evaluation": "timeline-evidence-links",
        "mode": "live" if args.live else "recorded",
        "quality_note": None if args.live else QUALITY_NOTE,
        "skipped": skipped,
        "report": report,
        "lifecycle": lifecycle,
        "passed": report_passed,
    }
    print(json.dumps(result, indent=2, sort_keys=True) if args.json else result)
    return 0 if result["passed"] or skipped is not None else 1


if __name__ == "__main__":
    raise SystemExit(main())
