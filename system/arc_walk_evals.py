#!/usr/bin/env python3
"""Independent recorded/live eval harness for Arc Walk (v193)."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import arc_walk
import conversation_delivery
from ai_provider import AIProviderError, call_ai, provider_status
from lifehug_core import INTERACTIONS_DIR, _parse_simple_yaml, load_config

EVALS_DIR = INTERACTIONS_DIR / "arc_walk" / "evals"

FIXTURES_FILE = "arc_fixtures.json"
SAMPLE_PREDICTIONS_FILE = "arc_sample_predictions.json"
REQUIRED_GOLDEN_IDS = frozenset({
    "arc-open-announces-agenda-once",
    "arc-walk-bridges-to-next-question",
    "arc-walk-user-tangent-keeps-plan",
    "arc-walk-decline-skips",
    "arc-close-summarizes-without-counters",
    "arc-walk-two-questions-in-one-answer-files-primary",
    "arc-walk-passive-single-question-is-byte-identical",
    "arc-close-user-signals-leaving",
    "arc-walk-unknown-question-id-rejected",
})
#: Which lint classes apply on a turn of a given {arc_stage}. The
#: one-question, counter, mechanism and pressure rules hold on every turn;
#: the agenda and close rules are stage-scoped.
_STAGE_SCOPED_LINTS = {
    "open": frozenset({"agenda_announced_once"}),
    "walk": frozenset({"agenda_never_repeated"}),
    "close": frozenset({"agenda_never_repeated", "close_summarizes"}),
}
_ALWAYS_APPLICABLE_LINTS = frozenset({
    "one_question_per_reply",
    "no_counters",
    "no_mechanism_talk",
    "no_pressure",
})


def _root(framework_root: str | Path | None) -> Path:
    return (
        Path(framework_root) / "interactions/arc_walk/evals"
        if framework_root
        else EVALS_DIR
    )


def load_fixtures(*, framework_root: str | Path | None = None) -> list[dict]:
    value = json.loads(
        (_root(framework_root) / "goldens" / FIXTURES_FILE).read_text(encoding="utf-8")
    )
    if not isinstance(value, list) or not value:
        raise ValueError("arc walk fixtures must be a non-empty list")
    return value


def load_sample_predictions(*, framework_root: str | Path | None = None) -> list[dict]:
    value = json.loads(
        (_root(framework_root) / "goldens" / SAMPLE_PREDICTIONS_FILE).read_text(
            encoding="utf-8"
        )
    )
    if not isinstance(value, list):
        raise TypeError("arc walk predictions must be a list")
    return value


def load_gates(*, framework_root: str | Path | None = None) -> dict[str, float]:
    raw = _parse_simple_yaml(_root(framework_root) / "lints.yaml")
    prefix = "arc_walk_gates."
    return {
        key.removeprefix(prefix): float(value)
        for key, value in raw.items()
        if key.startswith(prefix)
    }


def _plan_for(fixture: dict) -> dict:
    """The plan a fixture's turns are scored against — the fixture's own
    question ids, in a plan-shaped object. Built here rather than through
    `build_arc_plan` on purpose: the goldens grade REPLY behavior and field
    validation, not the planner's ranking (which
    `tests/test_arc_walk.py` pins directly)."""
    ids = fixture["target"]["plan_question_ids"]
    return {
        "target": {
            "kind": "focus",
            "ref": fixture["fixture_id"],
            "label": fixture["target"]["label"],
            "categories": tuple(sorted({str(qid)[:1] for qid in ids})),
        },
        "focus_label": fixture["target"]["label"],
        "questions": [
            {"id": str(qid), "text": "", "category": str(qid)[:1], "intent": None}
            for qid in ids
        ],
        "episode_size": len(ids),
        "plan_n": len(ids),
        "answered_k": 0,
    }


def validate_fixtures(fixtures: list[dict]) -> list[str]:
    """Deterministic fixture-shape errors for the arc golden pair."""
    errors: list[str] = []
    seen: set[str] = set()
    for index, row in enumerate(fixtures):
        if not isinstance(row, dict) or set(row) != {"fixture_id", "target", "turns"}:
            errors.append(f"fixture[{index}] keys invalid")
            continue
        fixture_id = row["fixture_id"]
        if not isinstance(fixture_id, str) or not fixture_id.strip():
            errors.append(f"fixture[{index}] fixture_id invalid")
        elif fixture_id in seen:
            errors.append(f"fixture[{index}] duplicate id")
        if isinstance(fixture_id, str):
            seen.add(fixture_id)
        target = row["target"]
        if not isinstance(target, dict) or set(target) != {
            "label",
            "plan_question_ids",
        }:
            errors.append(f"fixture[{index}] target keys invalid")
            continue
        ids = target["plan_question_ids"]
        if not isinstance(ids, list) or not ids or any(
            not isinstance(qid, str) or not qid.strip() for qid in ids
        ):
            errors.append(f"fixture[{index}] plan_question_ids invalid")
            continue
        plan = _plan_for(row)
        turns = row["turns"]
        if not isinstance(turns, list) or not turns:
            errors.append(f"fixture[{index}] turns must be non-empty")
            continue
        for position, turn in enumerate(turns):
            if not isinstance(turn, dict) or set(turn) != {
                "stage",
                "agenda_announced",
                "user_leaving",
                "expected_answered_question_id",
            }:
                errors.append(f"fixture[{index}].turns[{position}] keys invalid")
                continue
            if turn["stage"] not in arc_walk.VALID_ARC_STAGES:
                errors.append(f"fixture[{index}].turns[{position}] stage invalid")
            for flag in ("agenda_announced", "user_leaving"):
                if type(turn[flag]) is not bool:
                    errors.append(
                        f"fixture[{index}].turns[{position}] {flag} invalid"
                    )
            expected = turn["expected_answered_question_id"]
            if expected is not None and arc_walk.validate_answered_question_id(
                expected, plan=plan
            ) != expected:
                errors.append(
                    f"fixture[{index}].turns[{position}] "
                    "expected_answered_question_id is not on the plan"
                )
    missing = REQUIRED_GOLDEN_IDS - seen
    if missing:
        errors.append(f"fixtures missing required ids: {sorted(missing)}")
    return errors


def score_goldens(fixtures: list[dict], predictions: list[dict]) -> dict:
    """Score the seven arc_walk_gates.* classes over the arc goldens.

    Each fixture is a short episode; each parallel prediction supplies the
    reply text and the raw, pre-validation `answered_question_id` a model
    produced for each of those turns. Per turn:
    `arc_walk.lint_arc_reply` runs against the turn's `{arc_stage}` and the
    caller-owned `agenda_announced` fact, scored into whichever classes
    apply at that stage; the raw field is passed through BOTH validation
    layers together — `conversation_delivery._parse_answered_question_id`
    then `arc_walk.validate_answered_question_id` — exactly as a real
    caller would, and compared with the fixture's expectation. Golden
    `arc-walk-unknown-question-id-rejected` proves an off-plan qid
    normalizes to no filing change without a scored lint failure.
    """
    by_id = {
        row["fixture_id"]: row
        for row in predictions
        if isinstance(row, dict) and isinstance(row.get("fixture_id"), str)
    }
    counts = {name: [0, 0] for name in arc_walk.ARC_WALK_LINT_CLASSES}
    field_correct = 0
    field_total = 0
    unmatched: list[str] = []
    for fixture in fixtures:
        prediction = by_id.get(fixture["fixture_id"])
        if prediction is None:
            unmatched.append(fixture["fixture_id"])
            continue
        plan = _plan_for(fixture)
        for turn, pred_turn in zip(fixture["turns"], prediction.get("turns") or []):
            stage = turn["stage"]
            message = pred_turn.get("message", "")
            findings = {
                item["lint"].split(".", 1)[1]
                for item in arc_walk.lint_arc_reply(
                    message,
                    stage=stage,
                    agenda_announced=turn["agenda_announced"],
                )
            }
            applicable = _ALWAYS_APPLICABLE_LINTS | _STAGE_SCOPED_LINTS.get(
                stage, frozenset()
            )
            for lint_class in applicable:
                counts[lint_class][1] += 1
                counts[lint_class][0] += lint_class not in findings
            structural = conversation_delivery._parse_answered_question_id(  # noqa: SLF001
                pred_turn.get("answered_question_id")
            )
            validated = arc_walk.validate_answered_question_id(structural, plan=plan)
            field_total += 1
            field_correct += validated == turn["expected_answered_question_id"]
    scores: dict[str, object] = {
        f"{name}.compliance": (values[0] / values[1] if values[1] else 1.0)
        for name, values in counts.items()
    }
    scores["_answered_question_id_accuracy"] = (
        field_correct / field_total if field_total else 0.0
    )
    scores["_unmatched_fixtures"] = unmatched
    return scores


def check_gates(scores: dict[str, float], gates: dict[str, float]) -> list[str]:
    failures = []
    for name, threshold in gates.items():
        actual = scores.get(name)
        if actual is None:
            failures.append(f"missing score: {name}")
        elif actual < threshold:
            failures.append(f"{name} {actual:.3f} < {threshold:.3f}")
    return failures


def _live_predictions(fixtures: list[dict]) -> list[dict]:
    config = load_config()
    model = config.get("conversation_model", "sonnet-class")
    status = provider_status(model, probe=False)
    if not getattr(status, "ready", False):
        raise AIProviderError("no configured live provider; Arc Walk live seat skipped")
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
    scores = score_goldens(fixtures, predictions) if not skipped else {}
    failures = fixture_errors + ([] if skipped else check_gates(scores, load_gates()))
    result = {
        "interaction": "arc_walk",
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
