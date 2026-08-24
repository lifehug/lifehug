#!/usr/bin/env python3
"""Independent recorded/live eval harness for the Reading Room (v204)."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import conversation_delivery
import landmarks_interaction
import reading_room
from ai_provider import AIProviderError, call_ai, provider_status
from lifehug_core import INTERACTIONS_DIR, _parse_simple_yaml, load_config

EVALS_DIR = INTERACTIONS_DIR / "reading_room" / "evals"

FIXTURES_FILE = "reading_room_fixtures.json"
SAMPLE_PREDICTIONS_FILE = "reading_room_sample_predictions.json"
REQUIRED_GOLDEN_IDS = frozenset({
    "reading-room-opens-with-the-inventory",
    # The album session: the evidence IS the photograph, so the record is a
    # window with `basis: photo` (go-deep.md §5.1).
    "reading-room-album-dates-by-photo",
    # The etiquette case: the challenge is attributed to the SOURCE, and both
    # claims are kept (§3.3).
    "reading-room-document-beats-memory",
    # The relayed answer: `basis: relative`, the witness named in provenance,
    # and confidence capped because proxy report supplements the index report
    # rather than replacing it (§6.4).
    "reading-room-mom-on-the-phone",
    # The precision grade: a school's ADDRESS, and what the address buys.
    "reading-room-asks-for-the-address-grade",
    # The decline: "I'll find out" is an ordinary answer and grows no queue.
    "reading-room-i-will-find-out",
})

#: These hold on every reading-room turn. `one_ask_per_turn` is the only
#: conditional one — a `close` turn asks nothing at all, so the rule has
#: nothing to score there.
_ALWAYS_APPLICABLE_LINTS = frozenset({
    "artifact_carries_the_burden",
    "no_pressure",
    "accepts_i_will_find_out",
    "never_proposes_a_date",
})


def _applicable(stage: object) -> frozenset[str]:
    applicable = set(_ALWAYS_APPLICABLE_LINTS)
    if str(stage or "") != "close":
        applicable.add("one_ask_per_turn")
    return frozenset(applicable)


def _root(framework_root: str | Path | None) -> Path:
    return (
        Path(framework_root) / "interactions/reading_room/evals"
        if framework_root
        else EVALS_DIR
    )


def load_fixtures(*, framework_root: str | Path | None = None) -> list[dict]:
    value = json.loads(
        (_root(framework_root) / "goldens" / FIXTURES_FILE).read_text(encoding="utf-8")
    )
    if not isinstance(value, list) or not value:
        raise ValueError("reading room fixtures must be a non-empty list")
    return value


def load_sample_predictions(*, framework_root: str | Path | None = None) -> list[dict]:
    value = json.loads(
        (_root(framework_root) / "goldens" / SAMPLE_PREDICTIONS_FILE).read_text(
            encoding="utf-8"
        )
    )
    if not isinstance(value, list):
        raise TypeError("reading room predictions must be a list")
    return value


def load_gates(*, framework_root: str | Path | None = None) -> dict[str, float]:
    raw = _parse_simple_yaml(_root(framework_root) / "lints.yaml")
    prefix = "reading_room_gates."
    return {
        key.removeprefix(prefix): float(value)
        for key, value in raw.items()
        if key.startswith(prefix)
    }


_FIXTURE_KEYS = {"fixture_id", "inventory", "anchors", "turns"}
_TURN_KEYS = {"stage", "witness", "expected_placed", "expected_landmark"}


def validate_fixtures(fixtures: list[dict]) -> list[str]:
    """Deterministic fixture-shape errors for the reading-room goldens."""
    errors: list[str] = []
    seen: set[str] = set()
    for index, row in enumerate(fixtures):
        if not isinstance(row, dict) or set(row) != _FIXTURE_KEYS:
            errors.append(f"fixture[{index}] keys invalid")
            continue
        fixture_id = row["fixture_id"]
        if not isinstance(fixture_id, str) or not fixture_id:
            errors.append(f"fixture[{index}] has no id")
            continue
        if fixture_id in seen:
            errors.append(f"duplicate fixture id: {fixture_id}")
        seen.add(fixture_id)
        if not isinstance(row["inventory"], str):
            errors.append(f"{fixture_id}: inventory must be a string")
        if not isinstance(row["anchors"], dict):
            errors.append(f"{fixture_id}: anchors must be an object")
        turns = row["turns"]
        if not isinstance(turns, list) or not turns:
            errors.append(f"{fixture_id}: turns must be a non-empty list")
            continue
        for position, turn in enumerate(turns):
            if not isinstance(turn, dict) or set(turn) != _TURN_KEYS:
                errors.append(f"{fixture_id}.turns[{position}] keys invalid")
                continue
            if turn["stage"] not in reading_room.VALID_READING_ROOM_STAGES:
                errors.append(f"{fixture_id}.turns[{position}] bad stage")
            witness = turn.get("witness")
            if witness is not None and not isinstance(witness, dict):
                errors.append(f"{fixture_id}.turns[{position}] bad witness")
    missing = REQUIRED_GOLDEN_IDS - seen
    if missing:
        errors.append("missing required goldens: " + ", ".join(sorted(missing)))
    return errors


def score_goldens(fixtures: list[dict], predictions: list[dict]) -> dict:
    """Score the five ``reading_room_gates.*`` classes over the goldens.

    Per turn: `reading_room.lint_reading_room_reply` runs against the turn's
    stage, scored into whichever classes apply there; each of the TWO REUSED
    fields is passed through both of its own validation layers exactly as a
    real caller would — `conversation_delivery._parse_placed` then
    `reading_room.validate_evidence` (which delegates the vocabularies to
    `timeline_interaction.validate_placed`), and
    `conversation_delivery._parse_landmark` then
    `landmarks_interaction.validate_landmark` — and compared with the
    fixture's expectation.
    """
    by_id = {
        row["fixture_id"]: row
        for row in predictions
        if isinstance(row, dict) and isinstance(row.get("fixture_id"), str)
    }
    counts = {name.split(".", 1)[1]: [0, 0]
              for name in reading_room.READING_ROOM_LINT_CLASSES}
    field_correct = 0
    field_total = 0
    unmatched: list[str] = []
    for fixture in fixtures:
        prediction = by_id.get(fixture["fixture_id"])
        if prediction is None:
            unmatched.append(fixture["fixture_id"])
            continue
        anchors = fixture.get("anchors") or {}
        for turn, pred_turn in zip(fixture["turns"], prediction.get("turns") or []):
            stage = turn["stage"]
            findings = {
                item["lint"].split(".", 1)[1]
                for item in reading_room.lint_reading_room_reply(
                    pred_turn.get("message", ""), stage=stage
                )
            }
            for lint_class in _applicable(stage):
                counts[lint_class][1] += 1
                counts[lint_class][0] += lint_class not in findings
            structural = conversation_delivery._parse_placed(  # noqa: SLF001
                pred_turn.get("placed")
            )
            validated = reading_room.validate_evidence(
                structural, anchors=anchors, witness=turn.get("witness")
            )
            field_total += 1
            field_correct += validated == turn["expected_placed"]
            structural = conversation_delivery._parse_landmark(  # noqa: SLF001
                pred_turn.get("landmark")
            )
            validated = landmarks_interaction.validate_landmark(structural)
            field_total += 1
            field_correct += validated == turn["expected_landmark"]
    scores: dict[str, object] = {
        f"{name}.compliance": (values[0] / values[1] if values[1] else 1.0)
        for name, values in counts.items()
    }
    scores["_field_accuracy"] = field_correct / field_total if field_total else 0.0
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
        raise AIProviderError(
            "no configured live provider; Reading Room live seat skipped"
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
    scores = score_goldens(fixtures, predictions) if not skipped else {}
    failures = fixture_errors + ([] if skipped else check_gates(scores, load_gates()))
    result = {
        "interaction": "reading_room",
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
