#!/usr/bin/env python3
"""Independent recorded/live eval harness for Entity Candidate."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import entity_candidate
from ai_provider import AIProviderError, call_ai, provider_status
from lifehug_core import INTERACTIONS_DIR, _parse_simple_yaml, load_config

EVALS_DIR = INTERACTIONS_DIR / "entity_candidate" / "evals"

# entity-identity-context (v190, Design §D): a SECOND, independent golden pair
# beside the research one. The research fixtures/predictions model
# `parse_entity_candidate_output`'s frozen input/output shape (still the
# standalone CLI path's contract); the identity aside/question/offer/settled
# behavior lives on the PARENT Conversation turn contract instead
# (`conversation_delivery.parse_turn_output` +
# `entity_candidate.lint_entity_setup_reply` / `validate_entity_setup`), so it
# gets its own pair rather than overloading the frozen one. Both pairs feed
# the SAME `check_gates` call — no scorer-checking change. Exactly the split
# `question_candidate_evals` made for placement at v188 and
# `focus_candidate_evals` made for onboarding at v189.
IDENTITY_FIXTURES_FILE = "identity_fixtures.json"
IDENTITY_SAMPLE_PREDICTIONS_FILE = "identity_sample_predictions.json"
REQUIRED_IDENTITY_GOLDEN_IDS = frozenset({
    "identity-establish-aside-and-one-question",
    "identity-establish-duplicate-asks-same-as",
    "identity-establish-answer-already-told-asks-nothing",
    "identity-establish-offer-worthy-appends-offer",
    "identity-settled-silent",
    "identity-settled-user-signals-emits-setup",
    "identity-settled-offer-not-repeated",
    "identity-unknown-relationship-rejected",
})
#: The seven entity_setup_gates.* classes (Design §D table), matching
#: entity_candidate.lint_entity_setup_reply's finding ids minus the
#: "entity_setup." prefix.
IDENTITY_LINT_CLASSES = (
    "aside_single_sentence",
    "aside_not_a_question",
    "aside_never_repeated",
    "one_identity_question",
    "settled_silence",
    "offer_at_most_once",
    "no_mechanism_talk",
)
#: Which lint classes apply on a turn of a given {entity_stage}. The
#: one-question, offer-cap and mechanism rules hold on every turn; the aside
#: rules are stage-scoped.
_STAGE_SCOPED_IDENTITY_LINTS = {
    "establish": frozenset({"aside_single_sentence", "aside_not_a_question"}),
    "settled": frozenset({"aside_never_repeated", "settled_silence"}),
}
_ALWAYS_APPLICABLE_IDENTITY_LINTS = frozenset(
    {"one_identity_question", "offer_at_most_once", "no_mechanism_talk"}
)


def load_fixtures(*, framework_root: str | Path | None = None) -> list[dict]:
    root = (
        Path(framework_root) / "interactions/entity_candidate/evals"
        if framework_root
        else EVALS_DIR
    )
    value = json.loads((root / "goldens/fixtures.json").read_text(encoding="utf-8"))
    if not isinstance(value, list) or not value:
        raise ValueError("entity candidate fixtures must be a non-empty list")
    return value


def load_sample_predictions(*, framework_root: str | Path | None = None) -> list[dict]:
    root = (
        Path(framework_root) / "interactions/entity_candidate/evals"
        if framework_root
        else EVALS_DIR
    )
    value = json.loads(
        (root / "goldens/sample_predictions.json").read_text(encoding="utf-8")
    )
    if not isinstance(value, list):
        raise TypeError("entity candidate predictions must be a list")
    return value


def load_gates(*, framework_root: str | Path | None = None) -> dict[str, float]:
    root = (
        Path(framework_root) / "interactions/entity_candidate/evals"
        if framework_root
        else EVALS_DIR
    )
    raw = _parse_simple_yaml(root / "lints.yaml")
    gates: dict[str, float] = {}
    for key, value in raw.items():
        # Both gate prefixes, flattened into ONE dict for ONE `check_gates`
        # call — `research_gates.*` (the standalone research path) and
        # `entity_setup_gates.*` (the Play identity path, v190). The prefixes
        # are stripped, and the two families' class names do not collide.
        for prefix in ("research_gates.", "entity_setup_gates."):
            if key.startswith(prefix):
                gates[key.removeprefix(prefix)] = float(value)
                break
    return gates


def load_identity_fixtures(*, framework_root: str | Path | None = None) -> list[dict]:
    root = (
        Path(framework_root) / "interactions/entity_candidate/evals"
        if framework_root
        else EVALS_DIR
    )
    value = json.loads(
        (root / "goldens" / IDENTITY_FIXTURES_FILE).read_text(encoding="utf-8")
    )
    if not isinstance(value, list) or not value:
        raise ValueError("entity identity fixtures must be a non-empty list")
    return value


def load_identity_sample_predictions(
    *, framework_root: str | Path | None = None
) -> list[dict]:
    root = (
        Path(framework_root) / "interactions/entity_candidate/evals"
        if framework_root
        else EVALS_DIR
    )
    value = json.loads(
        (root / "goldens" / IDENTITY_SAMPLE_PREDICTIONS_FILE).read_text(encoding="utf-8")
    )
    if not isinstance(value, list):
        raise TypeError("entity identity predictions must be a list")
    return value


def validate_identity_fixtures(fixtures: list[dict]) -> list[str]:
    """Deterministic fixture-shape errors for the identity golden pair."""
    errors: list[str] = []
    seen: set[str] = set()
    for index, row in enumerate(fixtures):
        if not isinstance(row, dict) or set(row) != {"fixture_id", "entity", "turns"}:
            errors.append(f"identity fixture[{index}] keys invalid")
            continue
        fixture_id = row["fixture_id"]
        if not isinstance(fixture_id, str) or not fixture_id.strip():
            errors.append(f"identity fixture[{index}] fixture_id invalid")
        elif fixture_id in seen:
            errors.append(f"identity fixture[{index}] duplicate id")
        if isinstance(fixture_id, str):
            seen.add(fixture_id)
        entity = row["entity"]
        if not isinstance(entity, dict) or set(entity) != {
            "name", "type", "possible_duplicates", "roster_slugs"
        }:
            errors.append(f"identity fixture[{index}] entity keys invalid")
            entity = {}
        elif entity["type"] not in entity_candidate.entity_roster.ENTITY_TYPES:
            errors.append(f"identity fixture[{index}] entity type invalid")
        roster_slugs = entity.get("roster_slugs")
        if not isinstance(roster_slugs, list) or any(
            not isinstance(slug, str) for slug in roster_slugs
        ):
            errors.append(f"identity fixture[{index}] roster_slugs invalid")
            roster_slugs = []
        if not isinstance(entity.get("possible_duplicates", []), list):
            errors.append(f"identity fixture[{index}] possible_duplicates invalid")
        turns = row["turns"]
        if not isinstance(turns, list) or not turns:
            errors.append(f"identity fixture[{index}] turns must be non-empty")
            continue
        for position, turn in enumerate(turns):
            if not isinstance(turn, dict) or set(turn) != {
                "stage", "user_signaled", "offered_before", "expected_entity_setup"
            }:
                errors.append(
                    f"identity fixture[{index}].turns[{position}] keys invalid"
                )
                continue
            if turn["stage"] not in entity_candidate.VALID_ENTITY_STAGES:
                errors.append(
                    f"identity fixture[{index}].turns[{position}] stage invalid"
                )
            for flag in ("user_signaled", "offered_before"):
                if type(turn[flag]) is not bool:
                    errors.append(
                        f"identity fixture[{index}].turns[{position}] {flag} invalid"
                    )
            expected = turn["expected_entity_setup"]
            if expected is not None and (
                not isinstance(expected, dict)
                or entity_candidate.validate_entity_setup(
                    expected, roster_slugs=roster_slugs
                ) != expected
            ):
                errors.append(
                    f"identity fixture[{index}].turns[{position}] "
                    "expected_entity_setup invalid"
                )
    missing = REQUIRED_IDENTITY_GOLDEN_IDS - seen
    if missing:
        errors.append(f"identity fixtures missing required ids: {sorted(missing)}")
    return errors


def score_identity_goldens(fixtures: list[dict], predictions: list[dict]) -> dict:
    """Score the seven entity_setup_gates.* classes over the identity goldens.

    Each fixture is a short transcript; each parallel prediction supplies the
    reply text and the raw, pre-validation `entity_setup` value a model
    produced for each of those turns. Per turn:
    `entity_candidate.lint_entity_setup_reply` runs against the turn's
    `{entity_stage}` and the caller-owned `user_signaled` / `offered_before`
    facts, scored into whichever classes apply at that stage; the raw
    `entity_setup` is passed through `entity_candidate.validate_entity_setup`
    (exercising BOTH validation layers together, as a real caller would) and
    compared with the fixture's `expected_entity_setup` — golden
    `identity-unknown-relationship-rejected` proves an off-vocabulary
    relationship normalizes to no identity change without a scored lint
    failure.
    """
    by_id = {
        row["fixture_id"]: row
        for row in predictions
        if isinstance(row, dict) and isinstance(row.get("fixture_id"), str)
    }
    counts = {name: [0, 0] for name in IDENTITY_LINT_CLASSES}
    field_correct = 0
    field_total = 0
    unmatched: list[str] = []
    for fixture in fixtures:
        prediction = by_id.get(fixture["fixture_id"])
        if prediction is None:
            unmatched.append(fixture["fixture_id"])
            continue
        roster_slugs = fixture["entity"].get("roster_slugs") or []
        for turn, pred_turn in zip(fixture["turns"], prediction.get("turns") or []):
            stage = turn["stage"]
            message = pred_turn.get("message", "")
            findings = {
                item["lint"].split(".", 1)[1]
                for item in entity_candidate.lint_entity_setup_reply(
                    message,
                    stage=stage,
                    user_signaled=turn["user_signaled"],
                    offered_before=turn["offered_before"],
                )
            }
            applicable = (
                _ALWAYS_APPLICABLE_IDENTITY_LINTS
                | _STAGE_SCOPED_IDENTITY_LINTS.get(stage, frozenset())
            )
            for lint_class in applicable:
                counts[lint_class][1] += 1
                counts[lint_class][0] += lint_class not in findings
            validated = entity_candidate.validate_entity_setup(
                pred_turn.get("entity_setup"), roster_slugs=roster_slugs
            )
            field_total += 1
            field_correct += validated == turn["expected_entity_setup"]
    scores: dict[str, object] = {
        f"{name}.compliance": (values[0] / values[1] if values[1] else 0.0)
        for name, values in counts.items()
    }
    scores["_entity_setup_field_accuracy"] = (
        field_correct / field_total if field_total else 0.0
    )
    scores["_unmatched_identity_fixtures"] = unmatched
    return scores


def validate_fixtures(fixtures: list[dict]) -> list[str]:
    errors: list[str] = []
    seen: set[str] = set()
    expected_keys = {
        "fixture_id",
        "candidate_id",
        "entity_type",
        "turns",
        "expected_next_gap",
        "expected_ready",
        "expected_type_specific_context",
    }
    for index, row in enumerate(fixtures):
        if not isinstance(row, dict) or set(row) != expected_keys:
            errors.append(f"fixture[{index}] keys invalid")
            continue
        if row["fixture_id"] in seen:
            errors.append(f"fixture[{index}] duplicate id")
        seen.add(row["fixture_id"])
        if row["expected_next_gap"] not in entity_candidate.ENTITY_DIMENSIONS + (None,):
            errors.append(f"fixture[{index}] next gap invalid")
        if row["entity_type"] not in entity_candidate.ENTITY_TYPE_SPECIFIC_MIN_REFS:
            errors.append(f"fixture[{index}] entity type invalid")
        if type(row["expected_ready"]) is not bool:
            errors.append(f"fixture[{index}] ready invalid")
        if type(row["expected_type_specific_context"]) is not bool:
            errors.append(f"fixture[{index}] type rubric invalid")
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
        "type_specific.precision": [0, 0],
        "type_specific.recall": [0, 0],
    }
    per_type = {
        entity_type: {"precision": [0, 0], "recall": [0, 0]}
        for entity_type in entity_candidate.ENTITY_TYPE_SPECIFIC_MIN_REFS
    }
    false_positive = false_positive_total = recall = ready_total = 0
    for fixture in fixtures:
        prediction = by_id.get(fixture["fixture_id"])
        for name in (
            "inherited_conversation",
            "grounding",
            "identity_safety",
            "one_question",
            "next_gap",
        ):
            values = totals[name]
            values[1] += 1
        expected_type_specific = fixture["expected_type_specific_context"]
        if expected_type_specific:
            totals["type_specific.recall"][1] += 1
            per_type[fixture["entity_type"]]["recall"][1] += 1
        if fixture["expected_ready"]:
            ready_total += 1
        else:
            false_positive_total += 1
        if not isinstance(prediction, dict):
            continue
        reply = prediction.get("reply")
        if isinstance(reply, str):
            findings = entity_candidate.lint_entity_candidate_reply(
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
        predicted_type_specific = prediction.get("type_specific_context") is True
        if predicted_type_specific:
            totals["type_specific.precision"][1] += 1
            per_type[fixture["entity_type"]]["precision"][1] += 1
            if expected_type_specific:
                totals["type_specific.precision"][0] += 1
                per_type[fixture["entity_type"]]["precision"][0] += 1
        if expected_type_specific:
            if predicted_type_specific:
                totals["type_specific.recall"][0] += 1
                per_type[fixture["entity_type"]]["recall"][0] += 1
        if not fixture["expected_ready"]:
            false_positive += predicted_ready
        else:
            recall += predicted_ready

    def ratio(values: list[int]) -> float:
        return values[0] / values[1] if values[1] else 0.0

    scores = {
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
    scores.update(
        {
            name: ratio(values)
            for name, values in totals.items()
            if name.startswith("type_specific.")
        }
    )
    for entity_type, metrics in per_type.items():
        scores.update(
            {
                f"type_specific.{entity_type}.{name}": ratio(values)
                for name, values in metrics.items()
            }
        )
    return scores


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
            "no configured live provider; Entity Candidate live seat skipped"
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
    identity_fixtures = load_identity_fixtures()
    fixture_errors = validate_fixtures(fixtures) + validate_identity_fixtures(
        identity_fixtures
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
        # The identity pair is deterministic — recorded replies only, no
        # provider seat — so it scores even on a --live run (Design §D).
        scores.update(
            score_identity_goldens(
                identity_fixtures, load_identity_sample_predictions()
            )
        )
    failures = fixture_errors + ([] if skipped else check_gates(scores, load_gates()))
    result = {
        "interaction": "entity_candidate",
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
