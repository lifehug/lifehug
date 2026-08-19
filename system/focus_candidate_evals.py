#!/usr/bin/env python3
"""Independent recorded/live eval harness for Focus Candidate."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import conversation_lints
import focus_candidate
from ai_provider import AIProviderError, call_ai, provider_status
from lifehug_core import INTERACTIONS_DIR, _parse_simple_yaml, load_config

EVALS_DIR = INTERACTIONS_DIR / "focus_candidate" / "evals"


def load_fixtures(*, framework_root: str | Path | None = None) -> list[dict]:
    root = (
        Path(framework_root) / "interactions/focus_candidate/evals"
        if framework_root
        else EVALS_DIR
    )
    value = json.loads((root / "goldens/fixtures.json").read_text(encoding="utf-8"))
    if not isinstance(value, list) or not value:
        raise ValueError("focus candidate fixtures must be a non-empty list")
    return value


def load_sample_predictions(*, framework_root: str | Path | None = None) -> list[dict]:
    root = (
        Path(framework_root) / "interactions/focus_candidate/evals"
        if framework_root
        else EVALS_DIR
    )
    value = json.loads(
        (root / "goldens/sample_predictions.json").read_text(encoding="utf-8")
    )
    if not isinstance(value, list):
        raise TypeError("focus candidate predictions must be a list")
    return value


def load_gates(*, framework_root: str | Path | None = None) -> dict[str, float]:
    root = (
        Path(framework_root) / "interactions/focus_candidate/evals"
        if framework_root
        else EVALS_DIR
    )
    raw = _parse_simple_yaml(root / "lints.yaml")
    return {
        key.removeprefix("research_gates."): float(value)
        for key, value in raw.items()
        if key.startswith("research_gates.")
    }


def validate_fixtures(fixtures: list[dict]) -> list[str]:
    errors: list[str] = []
    seen: set[str] = set()
    expected_keys = {
        "fixture_id",
        "candidate_id",
        "turns",
        "expected_next_gap",
        "expected_ready",
    }
    for index, row in enumerate(fixtures):
        if not isinstance(row, dict) or set(row) != expected_keys:
            errors.append(f"fixture[{index}] keys invalid")
            continue
        if row["fixture_id"] in seen:
            errors.append(f"fixture[{index}] duplicate id")
        seen.add(row["fixture_id"])
        if row["expected_next_gap"] not in focus_candidate.FOCUS_DIMENSIONS + (None,):
            errors.append(f"fixture[{index}] next gap invalid")
        if type(row["expected_ready"]) is not bool:
            errors.append(f"fixture[{index}] ready invalid")
        if not isinstance(row["turns"], list) or any(
            not isinstance(turn, str) for turn in row["turns"]
        ):
            errors.append(f"fixture[{index}] turns invalid")
    return errors


def score_predictions(fixtures: list[dict], predictions: list[dict]) -> dict:
    by_id = {row.get("fixture_id"): row for row in predictions if isinstance(row, dict)}
    totals = {
        "inherited_conversation": [0, 0],
        "grounding": [0, 0],
        "identity_safety": [0, 0],
        "one_question": [0, 0],
        "next_gap": [0, 0],
    }
    false_positive = false_positive_total = recall = ready_total = 0
    for fixture in fixtures:
        prediction = by_id.get(fixture["fixture_id"])
        for values in totals.values():
            values[1] += 1
        if not isinstance(prediction, dict):
            if fixture["expected_ready"]:
                ready_total += 1
            continue
        reply = prediction.get("reply")
        if isinstance(reply, str):
            findings = conversation_lints.lint_turn(
                reply, seam_ok=fixture["expected_ready"]
            )
            totals["inherited_conversation"][0] += not findings
            totals["one_question"][0] += reply.count("?") <= 1
        quotes = prediction.get("evidence_quotes")
        grounded = isinstance(quotes, list) and all(
            isinstance(quote, str)
            and any(
                quote == turn[start:end]
                for turn in fixture["turns"]
                for start in range(len(turn) + 1)
                for end in (start + len(quote),)
                if end <= len(turn)
            )
            for quote in quotes
        )
        totals["grounding"][0] += grounded
        totals["identity_safety"][0] += (
            prediction.get("candidate_id") == fixture["candidate_id"]
        )
        totals["next_gap"][0] += (
            prediction.get("next_gap") == fixture["expected_next_gap"]
        )
        predicted_ready = prediction.get("ready") is True
        if not fixture["expected_ready"]:
            false_positive_total += 1
            false_positive += predicted_ready
        else:
            ready_total += 1
            recall += predicted_ready

    def ratio(values: list[int]) -> float:
        return values[0] / values[1] if values[1] else 0.0

    return {
        "inherited_conversation.compliance": ratio(totals["inherited_conversation"]),
        "grounding.compliance": ratio(totals["grounding"]),
        "identity_safety.compliance": ratio(totals["identity_safety"]),
        "one_question.compliance": ratio(totals["one_question"]),
        "next_gap.accuracy": ratio(totals["next_gap"]),
        "readiness.false_positive_rate": false_positive / false_positive_total
        if false_positive_total
        else 0.0,
        "readiness.recall": recall / ready_total if ready_total else 0.0,
    }


def check_gates(scores: dict[str, float], gates: dict[str, float]) -> list[str]:
    failures = []
    for name, threshold in gates.items():
        actual = scores.get(name)
        if actual is None:
            failures.append(f"missing score: {name}")
        elif name == "readiness.false_positive_rate":
            if actual > threshold:
                failures.append(f"{name} {actual:.3f} > {threshold:.3f}")
        elif actual < threshold:
            failures.append(f"{name} {actual:.3f} < {threshold:.3f}")
    return failures


def _live_predictions(fixtures: list[dict]) -> list[dict]:
    config = load_config()
    model = config.get("conversation_model", "sonnet-class")
    status = provider_status(model, probe=False)
    if not getattr(status, "ready", False):
        raise AIProviderError(
            "no configured live provider; Focus Candidate live seat skipped"
        )
    predictions = []
    for fixture in fixtures:
        raw = call_ai(json.dumps(fixture, ensure_ascii=False), model)
        prediction = json.loads(raw)
        prediction["fixture_id"] = fixture["fixture_id"]
        predictions.append(prediction)
    return predictions


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    fixtures = load_fixtures()
    fixture_errors = validate_fixtures(fixtures)
    skipped = None
    try:
        predictions = (
            _live_predictions(fixtures) if args.live else load_sample_predictions()
        )
    except (AIProviderError, json.JSONDecodeError) as exc:
        predictions = []
        skipped = str(exc)
    scores = score_predictions(fixtures, predictions) if not skipped else {}
    failures = fixture_errors + ([] if skipped else check_gates(scores, load_gates()))
    result = {
        "interaction": "focus_candidate",
        "mode": "live" if args.live else "recorded",
        "scores": scores,
        "failures": failures,
        "skipped": skipped,
        "passed": not failures and skipped is None,
    }
    print(json.dumps(result, indent=2, sort_keys=True) if args.json else result)
    return 0 if result["passed"] or skipped else 1


if __name__ == "__main__":
    raise SystemExit(main())
