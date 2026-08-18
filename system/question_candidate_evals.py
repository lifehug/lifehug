#!/usr/bin/env python3
"""Independent eval harness for the Question Candidate Interaction."""

from __future__ import annotations

import argparse
import json
from collections.abc import Callable
from pathlib import Path

import eval_gates
import interaction_registry
import question_candidate
from ai_provider import AIProviderError, call_ai, provider_status
from lifehug_core import INTERACTIONS_DIR, _parse_simple_yaml, load_config

EVALS_DIR = INTERACTIONS_DIR / "question_candidate" / "evals"
FIXTURES_FILE = "fixtures.json"
SAMPLE_PREDICTIONS_FILE = "sample_predictions.json"
GATE_PREFIX = "placement_gates"


def _evals_dir(framework_root: str | Path | None = None) -> Path:
    if framework_root is None:
        return EVALS_DIR
    return Path(framework_root) / "interactions" / "question_candidate" / "evals"


def load_fixtures(*, framework_root: str | Path | None = None) -> list[dict]:
    path = _evals_dir(framework_root) / "goldens" / FIXTURES_FILE
    value = json.loads(path.read_text(encoding="utf-8"))
    return value if isinstance(value, list) else []


def load_sample_predictions(*, framework_root: str | Path | None = None) -> list[dict]:
    path = _evals_dir(framework_root) / "goldens" / SAMPLE_PREDICTIONS_FILE
    value = json.loads(path.read_text(encoding="utf-8"))
    return value if isinstance(value, list) else []


def load_gates(
    *, framework_root: str | Path | None = None
) -> dict[str, dict[str, float]]:
    raw = _parse_simple_yaml(_evals_dir(framework_root) / "lints.yaml")
    gates: dict[str, dict[str, float]] = {}
    for key, value in raw.items():
        if not key.startswith(f"{GATE_PREFIX}."):
            continue
        parts = key.split(".")
        if len(parts) != 3:
            continue
        try:
            gates.setdefault(parts[1], {})[parts[2]] = float(value)
        except ValueError:
            continue
    return gates


def validate_fixture(entry: object) -> list[str]:
    if not isinstance(entry, dict) or set(entry) != {"fixture_id", "input", "expected"}:
        return ["fixture must contain exact fixture_id/input/expected keys"]
    errors: list[str] = []
    if not isinstance(entry["fixture_id"], str) or not entry["fixture_id"].strip():
        errors.append("fixture_id must be non-empty")
    try:
        question_candidate.validate_question_candidate_input(entry["input"])
    except (TypeError, ValueError) as exc:
        errors.append(f"input invalid: {exc}")
    expected = entry["expected"]
    expected_keys = {"status", "category_id", "turn_kind", "complete", "timing_valid"}
    if not isinstance(expected, dict) or set(expected) != expected_keys:
        errors.append("expected keys are invalid")
        return errors
    if expected["status"] not in question_candidate.VALID_STATUSES:
        errors.append("expected.status is invalid")
    if expected["turn_kind"] not in question_candidate.VALID_TURN_KINDS | {None}:
        errors.append("expected.turn_kind is invalid")
    if not isinstance(expected["complete"], bool) or not isinstance(
        expected["timing_valid"], bool
    ):
        errors.append("expected complete/timing_valid must be booleans")
    return errors


def validate_fixtures(fixtures: object) -> list[str]:
    if not isinstance(fixtures, list) or not fixtures:
        return ["fixtures must be a non-empty list"]
    errors: list[str] = []
    seen: set[str] = set()
    for index, entry in enumerate(fixtures):
        if isinstance(entry, dict) and isinstance(entry.get("fixture_id"), str):
            if entry["fixture_id"] in seen:
                errors.append(f"fixture[{index}] duplicate fixture_id")
            seen.add(entry["fixture_id"])
        errors.extend(f"fixture[{index}] {item}" for item in validate_fixture(entry))
    stages = {
        entry.get("input", {}).get("association_stage")
        for entry in fixtures
        if isinstance(entry, dict)
    }
    missing = question_candidate.VALID_ASSOCIATION_STAGES - stages
    if missing:
        errors.append(f"fixtures missing association stages: {sorted(missing)}")
    return errors


def _prediction_map(predictions: list[dict]) -> tuple[dict[str, object], list[str]]:
    output: dict[str, object] = {}
    malformed: list[str] = []
    for index, prediction in enumerate(predictions):
        if not isinstance(prediction, dict) or set(prediction) != {
            "fixture_id",
            "model_output",
        }:
            malformed.append(f"prediction[{index}]")
            continue
        fixture_id = prediction["fixture_id"]
        if not isinstance(fixture_id, str) or fixture_id in output:
            malformed.append(f"prediction[{index}]")
            continue
        output[fixture_id] = prediction["model_output"]
    return output, malformed


def _ratio(correct: int, total: int) -> float | None:
    return correct / total if total else None


def _stale_selected_category_rejected(decision: dict, payload: dict) -> bool:
    if decision["category_id"] is None:
        return True
    changed: list[dict] = []
    for category in payload["roster"]["categories"]:
        source = {
            key: value for key, value in category.items() if key != "category_revision"
        }
        if source["category_id"] == decision["category_id"]:
            source["label"] = f"{source['label']} changed"
        changed.append(source)
    roster = question_candidate.build_category_roster(changed)
    stale = question_candidate.validate_question_candidate_decision(
        decision,
        current_candidate=payload["candidate"],
        current_roster=roster,
    )
    return stale["status"] == "invalid"


def score_predictions(fixtures: list[dict], predictions: list[dict]) -> dict[str, dict]:
    by_id, malformed = _prediction_map(predictions)
    counts = {
        "category": [0, 0],
        "turn_kind": [0, 0],
        "closed_roster": [0, 0],
        "question": [0, 0],
        "timing": [0, 0],
        "completion": [0, 0],
        "stale_revision": [0, 0],
    }
    matched: set[str] = set()
    for fixture in fixtures:
        fixture_id = fixture["fixture_id"]
        expected = fixture["expected"]
        payload = fixture["input"]
        if fixture_id not in by_id:
            for count in counts.values():
                count[1] += 1
            continue
        matched.add(fixture_id)
        decision = question_candidate.parse_question_candidate_output(
            by_id[fixture_id], payload=payload
        )
        counts["category"][1] += 1
        counts["category"][0] += decision["category_id"] == expected["category_id"]
        counts["turn_kind"][1] += 1
        counts["turn_kind"][0] += decision["turn_kind"] == expected["turn_kind"]
        roster_ids = {row["category_id"] for row in payload["roster"]["categories"]}
        counts["closed_roster"][1] += 1
        counts["closed_roster"][0] += (
            decision["category_id"] is None or decision["category_id"] in roster_ids
        )
        counts["question"][1] += 1
        question_ok = expected["status"] != "needs_clarification" or (
            decision["status"] == "needs_clarification"
            and isinstance(decision["placement_question"], str)
        )
        counts["question"][0] += question_ok
        counts["timing"][1] += 1
        counts["timing"][0] += (
            decision["status"] == expected["status"] and expected["timing_valid"]
        )
        counts["completion"][1] += 1
        counts["completion"][0] += (
            decision["completion"]["complete"] == expected["complete"]
        )
        counts["stale_revision"][1] += 1
        counts["stale_revision"][0] += _stale_selected_category_rejected(
            decision, payload
        )
    metrics = {
        "category": "accuracy",
        "turn_kind": "accuracy",
        "closed_roster": "compliance",
        "question": "validity",
        "timing": "validity",
        "completion": "validity",
        "stale_revision": "rejection",
    }
    scores = {
        name: {"correct": values[0], "total": values[1], metric: _ratio(*values)}
        for name, values in counts.items()
        for metric in (metrics[name],)
    }
    scores["_unmatched"] = sorted(set(by_id) - matched)
    scores["_missing"] = sorted({f["fixture_id"] for f in fixtures} - matched)
    scores["_malformed"] = malformed
    return scores


def check_gates(
    scores: dict[str, dict], gates: dict[str, dict[str, float]]
) -> list[str]:
    return eval_gates.check_score_gates(scores, gates, prefix=GATE_PREFIX)


def inherited_lint_action_failures(payload: dict) -> list[str]:
    """Return actions whose structurally valid reply bypassed parent lints."""
    outputs = {
        "resolved": {
            "reply": "That must have been difficult.",
            "turn_kind": "answer",
            "placement_action": "resolved",
            "category_id": payload["roster"]["categories"][0]["category_id"],
            "confidence": 0.95,
            "placement_question": None,
        },
        "defer": {
            "reply": "That must have been difficult.",
            "turn_kind": "answer",
            "placement_action": "defer",
            "category_id": None,
            "confidence": 0.5,
            "placement_question": None,
        },
        "ask_now": {
            "reply": "That must have been difficult. Who were you going through it with?",
            "turn_kind": "mixed",
            "placement_action": "ask_now",
            "category_id": None,
            "confidence": 0.4,
            "placement_question": "Who were you going through it with?",
        },
    }
    return [
        action
        for action, output in outputs.items()
        if question_candidate.parse_question_candidate_output(output, payload=payload)[
            "status"
        ]
        != "invalid"
    ]


def run_live(
    fixtures: list[dict],
    *,
    model: str | None = None,
    ai_call: Callable[[str, str], str] | None = None,
    status_resolver: Callable[..., object] | None = None,
) -> dict:
    config = load_config()
    resolved_model = model or config.get("conversation_model", "sonnet-class")
    selected = (status_resolver or provider_status)(resolved_model, probe=False)
    if not getattr(selected, "ready", False):
        return {"status": "skipped", "reason": "no unattended AI provider is ready"}
    predictions: list[dict] = []
    for fixture in fixtures:
        payload = fixture["input"]
        if (
            payload["requested_outcome"] != "engage"
            or payload["provisional_category_id"]
        ):
            raw: object = None
        else:
            try:
                raw = (ai_call or call_ai)(
                    question_candidate.build_question_candidate_prompt(payload),
                    resolved_model,
                )
            except AIProviderError:
                raw = ""
        predictions.append({"fixture_id": fixture["fixture_id"], "model_output": raw})
    scores = score_predictions(fixtures, predictions)
    return {
        "status": "ran",
        "model": resolved_model,
        "scores": scores,
        "gate_failures": check_gates(scores, load_gates()),
    }


def run() -> tuple[int, str]:
    report: list[str] = ["Question Candidate Interaction evals"]
    errors = interaction_registry.audit_interaction_package("question_candidate")
    if errors:
        report.append(f"Layer 0 (registry/composition audit): FAILED {len(errors)}")
        report.extend(f"  ✗ {error}" for error in errors)
        return 1, "\n".join(report)
    report.append("Layer 0 (registry/composition audit): PASSED")
    fixtures = load_fixtures()
    fixture_errors = validate_fixtures(fixtures)
    if fixture_errors:
        report.append(f"Layer 1 (synthetic fixtures): FAILED {len(fixture_errors)}")
        report.extend(f"  ✗ {error}" for error in fixture_errors)
        return 1, "\n".join(report)
    report.append(f"Layer 1 (synthetic fixtures): PASSED {len(fixtures)}")
    scores = score_predictions(fixtures, load_sample_predictions())
    failures = check_gates(scores, load_gates())
    if failures:
        report.append(f"Layer 2 (sample gates): FAILED {len(failures)}")
        report.extend(f"  ✗ {failure}" for failure in failures)
        return 1, "\n".join(report)
    report.append(f"Layer 2 (sample gates): PASSED {len(load_gates())} gate classes")
    # Structural proof that inherited Conversation lints execute for every
    # model-controlled reply action in this seat.
    inherited_findings = question_candidate.lint_inherited_reply(
        "Did it happen? Or not?"
    )
    action_payload = next(
        fixture["input"]
        for fixture in fixtures
        if fixture["input"]["latest_user_turn"] is not None
    )
    action_failures = inherited_lint_action_failures(action_payload)
    if (
        not any(row["lint"] == "one_question_per_turn" for row in inherited_findings)
        or action_failures
    ):
        report.append("Layer 3 (inherited Conversation parity): FAILED")
        report.extend(f"  ✗ lint bypass: {action}" for action in action_failures)
        return 1, "\n".join(report)
    report.append("Layer 3 (inherited Conversation parity): PASSED")
    live = run_live(fixtures)
    if live["status"] == "skipped":
        report.append(f"Layer 4 (live seat): SKIPPED ({live['reason']})")
    elif live["gate_failures"]:
        report.append(f"Layer 4 (live seat): FAILED {len(live['gate_failures'])}")
        return 1, "\n".join(report)
    else:
        report.append(f"Layer 4 (live seat, {live['model']}): PASSED")
    return 0, "\n".join(report)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args(argv)
    code, report = run()
    print(report)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
