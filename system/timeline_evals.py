#!/usr/bin/env python3
"""Independent recorded/live eval harness for Timeline (v195)."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import conversation_delivery
import timeline_interaction
from ai_provider import AIProviderError, call_ai, provider_status
from lifehug_core import INTERACTIONS_DIR, _parse_simple_yaml, load_config

EVALS_DIR = INTERACTIONS_DIR / "timeline" / "evals"

FIXTURES_FILE = "timeline_fixtures.json"
SAMPLE_PREDICTIONS_FILE = "timeline_sample_predictions.json"
REQUIRED_GOLDEN_IDS = frozenset({
    "timeline-open-anchors-not-years",
    "timeline-place-residence-anchor",
    "timeline-place-age-arithmetic",
    "timeline-place-offers-bounds",
    "timeline-place-sequence-cue",
    "timeline-place-parallel-domain",
    "timeline-close-convergence",
    "timeline-ill-find-out-is-accepted",
    "timeline-contradiction-keeps-both",
    "timeline-skeleton-episode",
    # v196 (whispers): the lane's first goldens — the whisper that fits and
    # files, the one that never fits (and the turn that must not ask twice),
    # and the partial range that is a placement, not a miss.
    "timeline-whisper-fits-and-files",
    "timeline-whisper-does-not-fit",
    "timeline-whisper-partial-range",
})
#: The one-question and never-invent rules hold on every turn; the others are
#: scoped to the stage or the playbook rung the turn is actually on.
_ALWAYS_APPLICABLE_LINTS = frozenset({
    "one_question_per_reply",
    "never_invents_a_date",
    # v198 (go-deep.md §4.3): unconditional. There is no rung, and no stage,
    # where naming a date and inviting agreement is correct.
    "never_proposes_a_date",
})
_EARLY_RUNGS = frozenset({"content", "residence", "role"})


def _applicable(stage: str, probe_step: str | None,
                timeline_asks_so_far: int = 0) -> frozenset[str]:
    applicable = set(_ALWAYS_APPLICABLE_LINTS)
    if stage == "open" or probe_step in _EARLY_RUNGS or probe_step is None:
        applicable.add("no_year_opener")
    if probe_step == "bounds":
        applicable.add("offers_bounds")
    if probe_step == "defer" or stage == "close":
        applicable.add("accepts_defer")
    # v196: only a turn that could ask again can be judged on asking again.
    if int(timeline_asks_so_far or 0) >= 1 and probe_step not in (None, "convergence", "defer"):
        applicable.add("one_per_conversation")
    return frozenset(applicable)


def _root(framework_root: str | Path | None) -> Path:
    return (
        Path(framework_root) / "interactions/timeline/evals"
        if framework_root
        else EVALS_DIR
    )


def load_fixtures(*, framework_root: str | Path | None = None) -> list[dict]:
    value = json.loads(
        (_root(framework_root) / "goldens" / FIXTURES_FILE).read_text(encoding="utf-8")
    )
    if not isinstance(value, list) or not value:
        raise ValueError("timeline fixtures must be a non-empty list")
    return value


def load_sample_predictions(*, framework_root: str | Path | None = None) -> list[dict]:
    value = json.loads(
        (_root(framework_root) / "goldens" / SAMPLE_PREDICTIONS_FILE).read_text(
            encoding="utf-8"
        )
    )
    if not isinstance(value, list):
        raise TypeError("timeline predictions must be a list")
    return value


def load_gates(*, framework_root: str | Path | None = None) -> dict[str, float]:
    raw = _parse_simple_yaml(_root(framework_root) / "lints.yaml")
    prefix = "timeline_gates."
    return {
        key.removeprefix(prefix): float(value)
        for key, value in raw.items()
        if key.startswith(prefix)
    }


def validate_fixtures(fixtures: list[dict]) -> list[str]:
    """Deterministic fixture-shape errors for the timeline goldens."""
    errors: list[str] = []
    seen: set[str] = set()
    for index, row in enumerate(fixtures):
        # v196: `context` is optional prose about the conversation a whisper
        # golden lives in — additive, so every v195 fixture stays valid.
        if not isinstance(row, dict) or not {"fixture_id", "unknown", "turns"} <= set(row) \
                or not set(row) <= {"fixture_id", "unknown", "turns", "context"}:
            errors.append(f"fixture[{index}] keys invalid")
            continue
        fixture_id = row["fixture_id"]
        if not isinstance(fixture_id, str) or not fixture_id.strip():
            errors.append(f"fixture[{index}] fixture_id invalid")
        elif fixture_id in seen:
            errors.append(f"fixture[{index}] duplicate id")
        if isinstance(fixture_id, str):
            seen.add(fixture_id)
        unknown = row["unknown"]
        if not isinstance(unknown, dict) or set(unknown) != {
            "kind", "label", "anchors", "known_years",
        }:
            errors.append(f"fixture[{index}] unknown keys invalid")
            continue
        if not isinstance(unknown["anchors"], list) or any(
            not isinstance(anchor, dict) or not str(anchor.get("key") or "").strip()
            for anchor in unknown["anchors"]
        ):
            errors.append(f"fixture[{index}] anchors invalid")
            continue
        if not isinstance(unknown["known_years"], list) or any(
            not isinstance(year, str) for year in unknown["known_years"]
        ):
            errors.append(f"fixture[{index}] known_years invalid")
            continue
        turns = row["turns"]
        if not isinstance(turns, list) or not turns:
            errors.append(f"fixture[{index}] turns must be non-empty")
            continue
        for position, turn in enumerate(turns):
            if not isinstance(turn, dict) or not {
                "stage", "probe_step", "expected_placed",
            } <= set(turn) or not set(turn) <= {
                "stage", "probe_step", "expected_placed",
                "timeline_asks_so_far", "expected_raised",
            }:
                errors.append(f"fixture[{index}].turns[{position}] keys invalid")
                continue
            if turn["stage"] not in timeline_interaction.VALID_TIMELINE_STAGES:
                errors.append(f"fixture[{index}].turns[{position}] stage invalid")
            step = turn["probe_step"]
            if step is not None and step not in timeline_interaction.PLAYBOOK_ORDER:
                errors.append(f"fixture[{index}].turns[{position}] probe_step invalid")
            expected = turn["expected_placed"]
            if expected is not None and timeline_interaction.validate_placed(
                expected, anchors=unknown["anchors"]
            ) != expected:
                errors.append(
                    f"fixture[{index}].turns[{position}] "
                    "expected_placed does not survive its own validator"
                )
    missing = REQUIRED_GOLDEN_IDS - seen
    if missing:
        errors.append(f"fixtures missing required ids: {sorted(missing)}")
    return errors


def score_goldens(fixtures: list[dict], predictions: list[dict]) -> dict:
    """Score the five `timeline_gates.*` classes over the timeline goldens.

    Each fixture is one placement; each parallel prediction supplies the reply
    text and the raw, pre-validation `placed` object a model produced for each
    of those turns. Per turn: `timeline_interaction.lint_timeline_reply` runs
    against the turn's `{timeline_stage}`, its playbook rung, and the years the
    person actually supplied, scored into whichever classes apply there; the
    raw field is passed through BOTH validation layers together —
    `conversation_delivery._parse_placed` then
    `timeline_interaction.validate_placed` — exactly as a real caller would,
    and compared with the fixture's expectation.
    """
    by_id = {
        row["fixture_id"]: row
        for row in predictions
        if isinstance(row, dict) and isinstance(row.get("fixture_id"), str)
    }
    counts = {name: [0, 0] for name in timeline_interaction.TIMELINE_LINT_CLASSES}
    field_correct = 0
    field_total = 0
    raised_correct = 0
    raised_total = 0
    unmatched: list[str] = []
    for fixture in fixtures:
        prediction = by_id.get(fixture["fixture_id"])
        if prediction is None:
            unmatched.append(fixture["fixture_id"])
            continue
        unknown = fixture["unknown"]
        for turn, pred_turn in zip(fixture["turns"], prediction.get("turns") or []):
            stage = turn["stage"]
            step = turn["probe_step"]
            asks = int(turn.get("timeline_asks_so_far", 0) or 0)
            findings = {
                item["lint"].split(".", 1)[1]
                for item in timeline_interaction.lint_timeline_reply(
                    pred_turn.get("message", ""),
                    stage=stage,
                    probe_step=step,
                    known_years=unknown["known_years"],
                    timeline_asks_so_far=asks,
                )
            }
            for lint_class in _applicable(stage, step, asks):
                counts[lint_class][1] += 1
                counts[lint_class][0] += lint_class not in findings
            if turn.get("expected_raised") is not None:
                raised_total += 1
                raised_correct += bool(pred_turn.get("raised")) == bool(turn["expected_raised"])
            structural = conversation_delivery._parse_placed(  # noqa: SLF001
                pred_turn.get("placed")
            )
            validated = timeline_interaction.validate_placed(
                structural, anchors=unknown["anchors"]
            )
            field_total += 1
            field_correct += validated == turn["expected_placed"]
    scores: dict[str, object] = {
        f"{name}.compliance": (values[0] / values[1] if values[1] else 1.0)
        for name, values in counts.items()
    }
    scores["_placed_accuracy"] = field_correct / field_total if field_total else 0.0
    scores["_raised_accuracy"] = raised_correct / raised_total if raised_total else 1.0
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
        raise AIProviderError("no configured live provider; Timeline live seat skipped")
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
        "interaction": "timeline",
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
