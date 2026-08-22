#!/usr/bin/env python3
"""Independent recorded/live eval harness for Focus Candidate."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import focus_candidate
from ai_provider import AIProviderError, call_ai, provider_status
from lifehug_core import INTERACTIONS_DIR, _parse_simple_yaml, load_config

EVALS_DIR = INTERACTIONS_DIR / "focus_candidate" / "evals"

# focus-onboarding-context (v189, Design §D): a SECOND, independent golden
# pair beside the research one above. The research fixtures/predictions model
# `parse_focus_candidate_output`'s frozen input/output shape (still the
# standalone CLI path's contract); the onboarding aside/question/settled
# behavior lives on the PARENT Conversation turn contract instead
# (`conversation_delivery.parse_turn_output` +
# `focus_candidate.lint_focus_setup_reply` / `validate_focus_setup`), so it
# gets its own pair rather than overloading the frozen one. Both pairs feed
# the SAME `check_gates` call — no scorer-checking change. This is exactly
# the split `question_candidate_evals` made for placement at v188.
ONBOARDING_FIXTURES_FILE = "onboarding_fixtures.json"
ONBOARDING_SAMPLE_PREDICTIONS_FILE = "onboarding_sample_predictions.json"
REQUIRED_ONBOARDING_GOLDEN_IDS = frozenset({
    "onboarding-establish-aside-and-one-question",
    "onboarding-establish-person-asks-relationship",
    "onboarding-establish-answer-already-told-asks-nothing",
    "onboarding-settled-silent",
    "onboarding-settled-user-renames-emits-setup",
    "onboarding-settled-unprompted-null",
    "onboarding-unknown-relationship-rejected",
})
#: The six focus_setup_gates.* classes (Design §D table), matching
#: focus_candidate.lint_focus_setup_reply's finding ids minus the
#: "focus_setup." prefix.
ONBOARDING_LINT_CLASSES = (
    "aside_single_sentence",
    "aside_not_a_question",
    "aside_never_repeated",
    "one_setup_question",
    "settled_silence",
    "no_mechanism_talk",
)
#: Which lint classes apply on a turn of a given {focus_stage}. The
#: one-question and mechanism rules hold on every turn; the aside rules are
#: stage-scoped.
_STAGE_SCOPED_ONBOARDING_LINTS = {
    "establish": frozenset({"aside_single_sentence", "aside_not_a_question"}),
    "settled": frozenset({"aside_never_repeated", "settled_silence"}),
}
_ALWAYS_APPLICABLE_ONBOARDING_LINTS = frozenset(
    {"one_setup_question", "no_mechanism_talk"}
)


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


def load_onboarding_fixtures(*, framework_root: str | Path | None = None) -> list[dict]:
    root = (
        Path(framework_root) / "interactions/focus_candidate/evals"
        if framework_root
        else EVALS_DIR
    )
    value = json.loads(
        (root / "goldens" / ONBOARDING_FIXTURES_FILE).read_text(encoding="utf-8")
    )
    if not isinstance(value, list) or not value:
        raise ValueError("focus onboarding fixtures must be a non-empty list")
    return value


def load_onboarding_sample_predictions(
    *, framework_root: str | Path | None = None
) -> list[dict]:
    root = (
        Path(framework_root) / "interactions/focus_candidate/evals"
        if framework_root
        else EVALS_DIR
    )
    value = json.loads(
        (root / "goldens" / ONBOARDING_SAMPLE_PREDICTIONS_FILE).read_text(
            encoding="utf-8"
        )
    )
    if not isinstance(value, list):
        raise TypeError("focus onboarding predictions must be a list")
    return value


def load_gates(*, framework_root: str | Path | None = None) -> dict[str, float]:
    """Both gate prefixes, flattened into ONE dict for ONE `check_gates`
    call — `research_gates.*` (the standalone research path) and
    `focus_setup_gates.*` (the Play onboarding path, v189). The prefixes
    are stripped, and the two families' class names do not collide.
    """
    root = (
        Path(framework_root) / "interactions/focus_candidate/evals"
        if framework_root
        else EVALS_DIR
    )
    raw = _parse_simple_yaml(root / "lints.yaml")
    gates: dict[str, float] = {}
    for key, value in raw.items():
        for prefix in ("research_gates.", "focus_setup_gates."):
            if key.startswith(prefix):
                gates[key.removeprefix(prefix)] = float(value)
                break
    return gates


def validate_onboarding_fixtures(fixtures: list[dict]) -> list[str]:
    """Deterministic fixture-shape errors for the onboarding golden pair."""
    errors: list[str] = []
    seen: set[str] = set()
    for index, row in enumerate(fixtures):
        if not isinstance(row, dict) or set(row) != {"fixture_id", "focus", "turns"}:
            errors.append(f"onboarding fixture[{index}] keys invalid")
            continue
        fixture_id = row["fixture_id"]
        if not isinstance(fixture_id, str) or not fixture_id.strip():
            errors.append(f"onboarding fixture[{index}] fixture_id invalid")
        elif fixture_id in seen:
            errors.append(f"onboarding fixture[{index}] duplicate id")
        if isinstance(fixture_id, str):
            seen.add(fixture_id)
        focus = row["focus"]
        if not isinstance(focus, dict) or set(focus) != {"label", "type"}:
            errors.append(f"onboarding fixture[{index}] focus keys invalid")
        elif focus["type"] not in focus_candidate.FOCUS_TYPES:
            errors.append(f"onboarding fixture[{index}] focus type invalid")
        turns = row["turns"]
        if not isinstance(turns, list) or not turns:
            errors.append(f"onboarding fixture[{index}] turns must be non-empty")
            continue
        for position, turn in enumerate(turns):
            if not isinstance(turn, dict) or set(turn) != {
                "stage", "user_signaled", "expected_focus_setup"
            }:
                errors.append(
                    f"onboarding fixture[{index}].turns[{position}] keys invalid"
                )
                continue
            if turn["stage"] not in focus_candidate.VALID_FOCUS_STAGES:
                errors.append(
                    f"onboarding fixture[{index}].turns[{position}] stage invalid"
                )
            if type(turn["user_signaled"]) is not bool:
                errors.append(
                    f"onboarding fixture[{index}].turns[{position}] user_signaled invalid"
                )
            expected = turn["expected_focus_setup"]
            if expected is not None and (
                not isinstance(expected, dict)
                or focus_candidate.validate_focus_setup(expected) != expected
            ):
                errors.append(
                    f"onboarding fixture[{index}].turns[{position}] expected_focus_setup invalid"
                )
    missing = REQUIRED_ONBOARDING_GOLDEN_IDS - seen
    if missing:
        errors.append(f"onboarding fixtures missing required ids: {sorted(missing)}")
    return errors


def score_onboarding_goldens(fixtures: list[dict], predictions: list[dict]) -> dict:
    """Score the six focus_setup_gates.* classes over the onboarding goldens.

    Each fixture is a short transcript; each parallel prediction supplies the
    reply text and the raw, pre-validation `focus_setup` value a model
    produced for each of those turns. Per turn:
    `focus_candidate.lint_focus_setup_reply` runs against the turn's
    `{focus_stage}` and the caller-owned `user_signaled` fact, scored into
    whichever classes apply at that stage; the raw `focus_setup` is passed
    through `focus_candidate.validate_focus_setup` (exercising BOTH
    validation layers together, as a real caller would) and compared with
    the fixture's `expected_focus_setup` — golden
    `onboarding-unknown-relationship-rejected` proves an off-vocabulary
    relationship normalizes to no setup change without a scored lint
    failure.
    """
    by_id = {
        row["fixture_id"]: row
        for row in predictions
        if isinstance(row, dict) and isinstance(row.get("fixture_id"), str)
    }
    counts = {name: [0, 0] for name in ONBOARDING_LINT_CLASSES}
    field_correct = 0
    field_total = 0
    unmatched: list[str] = []
    for fixture in fixtures:
        prediction = by_id.get(fixture["fixture_id"])
        if prediction is None:
            unmatched.append(fixture["fixture_id"])
            continue
        for turn, pred_turn in zip(fixture["turns"], prediction.get("turns") or []):
            stage = turn["stage"]
            message = pred_turn.get("message", "")
            findings = {
                item["lint"].split(".", 1)[1]
                for item in focus_candidate.lint_focus_setup_reply(
                    message, stage=stage, user_signaled=turn["user_signaled"]
                )
            }
            applicable = (
                _ALWAYS_APPLICABLE_ONBOARDING_LINTS
                | _STAGE_SCOPED_ONBOARDING_LINTS.get(stage, frozenset())
            )
            for lint_class in applicable:
                counts[lint_class][1] += 1
                counts[lint_class][0] += lint_class not in findings
            validated = focus_candidate.validate_focus_setup(
                pred_turn.get("focus_setup")
            )
            field_total += 1
            field_correct += validated == turn["expected_focus_setup"]
    scores: dict[str, object] = {
        f"{name}.compliance": (values[0] / values[1] if values[1] else 0.0)
        for name, values in counts.items()
    }
    scores["_focus_setup_field_accuracy"] = (
        field_correct / field_total if field_total else 0.0
    )
    scores["_unmatched_onboarding_fixtures"] = unmatched
    return scores


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
            findings = focus_candidate.lint_focus_candidate_reply(
                reply, seam_ok=fixture["expected_ready"]
            )
            totals["inherited_conversation"][0] += not findings
            totals["one_question"][0] += not any(
                finding["lint"] == "one_question_per_turn" for finding in findings
            )
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
    onboarding_fixtures = load_onboarding_fixtures()
    fixture_errors = validate_fixtures(fixtures) + validate_onboarding_fixtures(
        onboarding_fixtures
    )
    skipped = None
    try:
        predictions = (
            _live_predictions(fixtures) if args.live else load_sample_predictions()
        )
    except (AIProviderError, json.JSONDecodeError) as exc:
        predictions = []
        skipped = str(exc)
    scores = score_predictions(fixtures, predictions) if not skipped else {}
    if not skipped:
        # The onboarding pair is deterministic — recorded replies only, no
        # provider seat — so it scores even on a --live run (Design §D).
        scores.update(
            score_onboarding_goldens(
                onboarding_fixtures, load_onboarding_sample_predictions()
            )
        )
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
