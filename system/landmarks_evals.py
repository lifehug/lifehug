#!/usr/bin/env python3
"""Independent recorded/live eval harness for Landmarks (v199)."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import conversation_delivery
import landmarks_interaction
from ai_provider import AIProviderError, call_ai, provider_status
from lifehug_core import INTERACTIONS_DIR, _parse_simple_yaml, load_config

EVALS_DIR = INTERACTIONS_DIR / "landmarks" / "evals"

FIXTURES_FILE = "landmark_fixtures.json"
SAMPLE_PREDICTIONS_FILE = "landmark_sample_predictions.json"
REQUIRED_GOLDEN_IDS = frozenset({
    "landmarks-open-birthday",
    "landmarks-residence-chain",
    "landmarks-vague-is-an-answer",
    "landmarks-skip-is-final",
    "landmarks-school-grades-not-years",
    "landmarks-losses-offered-never-pressed",
    "landmarks-one-domain-per-turn",
    "landmarks-never-invents-a-domain",
    # v198 (go-deep.md §4.3): reporting the derivation is right;
    # naming a date and inviting agreement is the banned move.
    "landmarks-reports-the-arithmetic-never-asks-agreement",
})

#: These hold on every landmark turn. `never_presses_sensitive` is scoped to a
#: sensitive domain and `no_year_demand` is suspended for `birth` — the one
#: carve-out (landmarks.md §2.1) — so neither is unconditional.
_ALWAYS_APPLICABLE_LINTS = frozenset({
    "accepts_vague",
    "no_form_voice",
    "one_domain_per_turn",
    # v198 (go-deep.md §4.3): unconditional. There is no domain, not even
    # `birth`, where naming a date and inviting agreement is correct.
    "never_proposes_a_date",
})


def _applicable(domain: object, sensitive: bool) -> frozenset[str]:
    applicable = set(_ALWAYS_APPLICABLE_LINTS)
    if str(domain or "") != "birth":
        applicable.add("no_year_demand")
    if sensitive:
        applicable.add("never_presses_sensitive")
    return frozenset(applicable)


def _root(framework_root: str | Path | None) -> Path:
    return (
        Path(framework_root) / "interactions/landmarks/evals"
        if framework_root
        else EVALS_DIR
    )


def load_fixtures(*, framework_root: str | Path | None = None) -> list[dict]:
    value = json.loads(
        (_root(framework_root) / "goldens" / FIXTURES_FILE).read_text(encoding="utf-8")
    )
    if not isinstance(value, list) or not value:
        raise ValueError("landmark fixtures must be a non-empty list")
    return value


def load_sample_predictions(*, framework_root: str | Path | None = None) -> list[dict]:
    value = json.loads(
        (_root(framework_root) / "goldens" / SAMPLE_PREDICTIONS_FILE).read_text(
            encoding="utf-8"
        )
    )
    if not isinstance(value, list):
        raise TypeError("landmark predictions must be a list")
    return value


def load_gates(*, framework_root: str | Path | None = None) -> dict[str, float]:
    raw = _parse_simple_yaml(_root(framework_root) / "lints.yaml")
    prefix = "landmark_gates."
    return {
        key.removeprefix(prefix): float(value)
        for key, value in raw.items()
        if key.startswith(prefix)
    }


_FIXTURE_KEYS = {"fixture_id", "landmarks", "turns"}
_TURN_KEYS = {"stage", "domain", "rung", "sensitive", "expected_landmark",
              "domains_named"}


def validate_fixtures(fixtures: list[dict]) -> list[str]:
    """Deterministic fixture-shape errors for the landmark goldens."""
    errors: list[str] = []
    seen: set[str] = set()
    domains = {row["domain"] for row in landmarks_interaction.load_questions()}
    for index, row in enumerate(fixtures):
        if not isinstance(row, dict) or not _FIXTURE_KEYS <= set(row) \
                or not set(row) <= _FIXTURE_KEYS:
            errors.append(f"fixture[{index}] keys invalid")
            continue
        fixture_id = row["fixture_id"]
        if not isinstance(fixture_id, str) or not fixture_id:
            errors.append(f"fixture[{index}] has no id")
            continue
        if fixture_id in seen:
            errors.append(f"duplicate fixture id: {fixture_id}")
        seen.add(fixture_id)
        if not isinstance(row["landmarks"], dict):
            errors.append(f"{fixture_id}: landmarks must be an object")
        turns = row["turns"]
        if not isinstance(turns, list) or not turns:
            errors.append(f"{fixture_id}: turns must be a non-empty list")
            continue
        for position, turn in enumerate(turns):
            if not isinstance(turn, dict) or not set(turn) <= _TURN_KEYS:
                errors.append(f"{fixture_id}.turns[{position}] keys invalid")
                continue
            if turn.get("stage") not in landmarks_interaction.VALID_LANDMARK_STAGES:
                errors.append(f"{fixture_id}.turns[{position}] bad stage")
            domain = turn.get("domain")
            if domain is not None and domain not in domains:
                errors.append(f"{fixture_id}.turns[{position}] unknown domain {domain!r}")
    missing = REQUIRED_GOLDEN_IDS - seen
    if missing:
        errors.append("missing required goldens: " + ", ".join(sorted(missing)))
    return errors


def score_goldens(fixtures: list[dict], predictions: list[dict]) -> dict:
    """Score the five ``landmark_gates.*`` classes over the landmark goldens.

    Per turn: `landmarks_interaction.lint_landmark_reply` runs against the
    turn's domain and sensitivity, scored into whichever classes apply there;
    the raw field is passed through BOTH validation layers together —
    `conversation_delivery._parse_landmark` then
    `landmarks_interaction.validate_landmark` — exactly as a real caller
    would, and compared with the fixture's expectation.
    """
    by_id = {
        row["fixture_id"]: row
        for row in predictions
        if isinstance(row, dict) and isinstance(row.get("fixture_id"), str)
    }
    counts = {name.split(".", 1)[1]: [0, 0]
              for name in landmarks_interaction.LANDMARK_LINT_CLASSES}
    field_correct = 0
    field_total = 0
    unmatched: list[str] = []
    for fixture in fixtures:
        prediction = by_id.get(fixture["fixture_id"])
        if prediction is None:
            unmatched.append(fixture["fixture_id"])
            continue
        for turn, pred_turn in zip(fixture["turns"], prediction.get("turns") or []):
            domain = turn.get("domain")
            sensitive = bool(turn.get("sensitive"))
            findings = {
                item["lint"].split(".", 1)[1]
                for item in landmarks_interaction.lint_landmark_reply(
                    pred_turn.get("message", ""),
                    stage=turn["stage"],
                    domain=domain,
                    sensitive=sensitive,
                    domains_named=turn.get("domains_named") or (),
                )
            }
            for lint_class in _applicable(domain, sensitive):
                counts[lint_class][1] += 1
                counts[lint_class][0] += lint_class not in findings
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
    scores["_landmark_accuracy"] = field_correct / field_total if field_total else 0.0
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
        raise AIProviderError("no configured live provider; Landmarks live seat skipped")
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
        "interaction": "landmarks",
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
