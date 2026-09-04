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
#: Cut 6a (ADR 0033). The `offer` mode's own goldens — one per example in
#: decision record §5.6. They are a DIFFERENT SHAPE from the reply goldens
#: above and are scored by a different function, because they judge a
#: different artifact: a PROPOSAL (with its units, questions, stories and
#: unrecognized spans) and the worker's reply about it, not a landmark turn.
#: Each fixture carries the RECORDED completions of both extraction passes, so
#: `score_offer_goldens` replays the real `landmark_offer.propose` — the
#: grammar pass, the listener, the per-domain recorder, the basis rule and the
#: partition — rather than scoring a transcript of what it once did.
OFFER_FIXTURES_FILE = "offer_fixtures.json"
REQUIRED_GOLDEN_IDS = frozenset({
    "landmarks-open-birthday",
    "landmarks-residence-chain",
    "landmarks-vague-is-an-answer",
    "landmarks-skip-is-final",
    "landmarks-school-grades-not-years",
    "landmarks-losses-offered-never-pressed",
    "landmarks-one-domain-per-turn",
    "landmarks-never-invents-a-domain",
    # v198 (ADR 0025's suggestive-interviewing hazard): reporting the
    # derivation is right; naming a date and inviting agreement is the
    # banned move.
    "landmarks-reports-the-arithmetic-never-asks-agreement",
    # v202 (family-landmark): the ninth domain, and the two "unknowns are
    # concrete" rulings that came with it.
    "landmarks-family-opening",
    "landmarks-family-sibling-interval",
    "landmarks-family-elder-gently",
    "landmarks-family-decline-respected",
    "landmarks-family-named-follow-up",
    "landmarks-residence-gap-is-a-question",
    # v203 (owner ruling 6): a life with none of a thing must be able to
    # FINISH that domain, and a later reversal must supersede the none
    # rather than argue with it.
    "landmarks-none-is-a-finished-answer",
    "landmarks-none-is-superseded-not-fought",
    "landmarks-none-completes-children",
    # lifehug#219: the ladder reads what the writer writes. Both priors are
    # founder shapes, structurally verbatim with synthetic surnames — a
    # partnership and four children carrying only `label`, and the three
    # `thing` chains carrying only `label`. Before the fix these turns asked
    # the domain's OPENING question again.
    "landmarks-the-label-is-the-name-it-asked-for",
    "landmarks-a-bare-label-climbs-the-thing-ladders",
    # v212 (lifehug#221): replying is not recording. Both live failures, as
    # the turns they should have been, plus the ambiguous turn that must NOT
    # be punished for staying quiet.
    "landmarks-military-none-with-a-story-alongside",
    "landmarks-losses-are-recorded-not-only-received",
    "landmarks-ambiguous-answer-is-not-a-missed-record",
})

#: These hold on every landmark turn. `never_presses_sensitive` is scoped to a
#: sensitive domain and `no_year_demand` is suspended for a PERSON'S BIRTH
#: (`landmarks_interaction.YEAR_OPENER_DOMAINS`; landmarks.md §2.1 + §2.9), so
#: neither is unconditional.
_ALWAYS_APPLICABLE_LINTS = frozenset({
    "accepts_vague",
    "no_form_voice",
    "one_domain_per_turn",
    # v198 (ADR 0025's suggestive-interviewing hazard): unconditional. There
    # is no domain, not even `birth`, where naming a date and inviting
    # agreement is correct.
    "never_proposes_a_date",
})


def _applicable(domain: object, sensitive: bool, *,
                answered: bool = False) -> frozenset[str]:
    applicable = set(_ALWAYS_APPLICABLE_LINTS)
    # v212 (lifehug#221): scored only on a turn whose fixture supplies the
    # person's own message. Without it the class cannot fire at all, so
    # scoring it there would be free compliance — a gate that measures
    # nothing.
    if answered:
        applicable.add("answer_must_record")
    # v202: the year-opener carve-out is a NAMED SET on the interaction module
    # (`birth`, `family`, `children` — see YEAR_OPENER_DOMAINS), read here
    # rather than re-derived, so the harness and the lint can never disagree.
    if str(domain or "") not in landmarks_interaction.YEAR_OPENER_DOMAINS:
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


REQUIRED_OFFER_GOLDEN_IDS = frozenset({
    # Cut 6f (owner rulings R6-R9): the five readings the reading contract is
    # pinned against. They replace the §5.6 grammar-era set, which pinned the
    # three-pass shape R6 deleted.
    "offer-residence-document",
    "offer-free-prose-stay",
    "offer-single-dated-event",
    "offer-story-not-a-landmark",
    "offer-mixed-paste",
})

_OFFER_FIXTURE_KEYS = {"fixture_id", "why", "source_text", "completions",
                       "expected", "reply"}


def load_offer_fixtures(*, framework_root: str | Path | None = None) -> list[dict]:
    value = json.loads(
        (_root(framework_root) / "goldens" / OFFER_FIXTURES_FILE).read_text(
            encoding="utf-8")
    )
    if not isinstance(value, list) or not value:
        raise ValueError("offer fixtures must be a non-empty list")
    return value


def validate_offer_fixtures(fixtures: list[dict]) -> list[str]:
    """Deterministic fixture-shape errors for the offer goldens."""
    errors: list[str] = []
    seen: set[str] = set()
    domains = {row["domain"] for row in landmarks_interaction.load_questions()}
    for index, row in enumerate(fixtures):
        if not isinstance(row, dict) or set(row) != _OFFER_FIXTURE_KEYS:
            errors.append(f"offer fixture[{index}] keys invalid")
            continue
        fixture_id = row["fixture_id"]
        if not isinstance(fixture_id, str) or not fixture_id:
            errors.append(f"offer fixture[{index}] has no id")
            continue
        if fixture_id in seen:
            errors.append(f"duplicate offer fixture id: {fixture_id}")
        seen.add(fixture_id)
        if not str(row.get("source_text") or "").strip():
            errors.append(f"{fixture_id}: source_text is required")
        completions = row.get("completions")
        if not isinstance(completions, dict) or "reading" not in completions:
            errors.append(f"{fixture_id}: completions need a reading")
            continue
        reading = completions.get("reading")
        units = reading.get("units") if isinstance(reading, dict) else ()
        for unit in (units or ()):
            domain = unit.get("domain") if isinstance(unit, dict) else None
            if domain is not None and domain not in domains:
                errors.append(f"{fixture_id}: unknown domain {domain!r}")
        expected = row.get("expected")
        if not isinstance(expected, dict) or "state" not in expected:
            errors.append(f"{fixture_id}: expected needs a state")
    missing = REQUIRED_OFFER_GOLDEN_IDS - seen
    if missing:
        errors.append("missing required offer goldens: "
                      + ", ".join(sorted(missing)))
    return errors


class _RecordedCall:
    """One recorded ``call`` over the ONE reading pass (Cut 6f, R6/R9).

    There is one prompt per submission now, so there is nothing to dispatch
    on: whatever `propose` composes, the golden's recorded reading answers.
    A fixture with no reading answers an EMPTY reading rather than raising.
    """

    EMPTY = '{"units": [], "events": [], "stories": [], "unplaced": []}'

    def __init__(self, completions: dict) -> None:
        self._reading = completions.get("reading")

    @staticmethod
    def _as_text(value: object) -> str:
        return value if isinstance(value, str) else json.dumps(value)

    def __call__(self, prompt: str, model: str) -> str:  # noqa: ARG002
        if self._reading is None:
            return self.EMPTY
        return self._as_text(self._reading)


def _offer_unit_matches(unit: dict, expected: dict) -> bool:
    dates = unit.get("dates") or {}
    inherited = dates.get("inherited_from") or {}
    checks = [
        ("domain", unit.get("domain")),
        ("kind", unit.get("kind")),
        ("subject", unit.get("subject")),
        ("basis", dates.get("basis")),
        ("confidence", dates.get("confidence")),
        ("start", dates.get("start")),
        ("end", dates.get("end")),
        ("auto_file_eligible", unit.get("auto_file_eligible")),
        # Cut 6f: the reading's own relation and provenance are part of what a
        # golden pins, not incidental output.
        ("clause", dates.get("clause")),
        ("inherited_from", inherited.get("subject")),
        ("estimated", dates.get("estimated")),
        ("names", unit.get("names")),
    ]
    for key, actual in checks:
        if key in expected and expected[key] != actual:
            return False
    if "quote" in expected:
        quote = unit.get("quote") or {}
        if quote.get("text") != expected["quote"]:
            return False
    if "entity_confidence" in expected:
        found = [row.get("confidence")
                 for row in (unit.get("entity_candidates") or ())]
        if expected["entity_confidence"] not in found:
            return False
    return True


def _within_subject(unit: dict, by_id: dict) -> str | None:
    """The SUBJECT of the unit this one belongs to, for a readable golden.

    A golden pins ``"within": "The Blue House"``, never a content-addressed
    `unit_id` that moves whenever a quote or a date moves — which would make
    every fixture a hash nobody can read or check by eye.
    """
    parent = by_id.get(unit.get("within"))
    return parent.get("subject") if isinstance(parent, dict) else None


def score_offer_goldens(fixtures: list[dict]) -> dict:
    """Replay `landmark_offer.propose` over the offer goldens and score it.

    No vault and no live model: the fixture supplies the recorded completions
    and the vault context is empty and explicit, which is what makes
    ``propose`` a pure function here (see its own docstring). The four
    `landmark_gates.offer_*` classes are scored per fixture — two over the
    PROPOSAL and two over the worker's reply — and ``_offer_accuracy`` is the
    fraction of fixtures whose reading matched the golden exactly.
    """
    import landmark_offer as offer  # noqa: PLC0415

    counts = {name.split(".", 1)[1]: [0, 0] for name in offer.OFFER_LINT_CLASSES}
    correct = 0
    total = 0
    mismatched: list[str] = []
    for fixture in fixtures:
        fixture_id = str(fixture.get("fixture_id") or "")
        expected = fixture.get("expected") or {}
        proposal = offer.propose(
            fixture["source_text"], None,
            call=_RecordedCall(fixture.get("completions") or {}),
            write=False, landmarks={}, roster={}, generation=0,
        )
        proposal_findings = {row["lint"] for row
                             in offer.lint_offer_proposal(proposal)}
        reply_findings = {row["lint"] for row
                          in offer.lint_offer_reply(fixture.get("reply") or "")}
        found = proposal_findings | reply_findings
        for name in offer.OFFER_LINT_CLASSES:
            key = name.split(".", 1)[1]
            counts[key][1] += 1
            counts[key][0] += name not in found
        total += 1
        matched = proposal.get("state") == expected.get("state")
        units = [unit for unit in (proposal.get("units") or ())]
        if "unit_count" in expected:
            matched = matched and len(units) == expected["unit_count"]
        by_id = {unit.get("unit_id"): unit for unit in units}
        if "units" in expected:
            matched = matched and len(units) == len(expected["units"])
            if matched:
                matched = all(
                    _offer_unit_matches(unit, want)
                    and ("within" not in want
                         or _within_subject(unit, by_id) == want["within"])
                    for unit, want in zip(units, expected["units"]))
        if "events" in expected:
            found = [{"text": row.get("text"), "kind": row.get("kind"),
                      "filing": row.get("filing"),
                      "within": (by_id.get(row.get("within")) or {}).get("subject")}
                     for row in (proposal.get("events") or ())]
            matched = matched and found == list(expected["events"])
        if "findings" in expected:
            matched = matched and list(proposal.get("findings") or ()) == \
                list(expected["findings"])
        if "questions" in expected:
            asked = [row.get("domain") for row in (proposal.get("questions") or ())]
            matched = matched and asked == [row.get("domain") for row
                                            in expected["questions"]]
        for key in ("stories", "unrecognized"):
            if key in expected:
                spans = [row.get("text") for row in (proposal.get(key) or ())]
                matched = matched and spans == list(expected[key])
        correct += bool(matched)
        if not matched:
            mismatched.append(fixture_id)
    scores: dict[str, object] = {
        f"{name}.compliance": (values[0] / values[1] if values[1] else 1.0)
        for name, values in counts.items()
    }
    scores["_offer_accuracy"] = correct / total if total else 0.0
    scores["_offer_mismatched"] = mismatched
    return scores


def load_gates(*, framework_root: str | Path | None = None) -> dict[str, float]:
    raw = _parse_simple_yaml(_root(framework_root) / "lints.yaml")
    prefix = "landmark_gates."
    return {
        key.removeprefix(prefix): float(value)
        for key, value in raw.items()
        if key.startswith(prefix)
    }


def load_offer_gates(*, framework_root: str | Path | None = None) -> dict[str, float]:
    """The `offer` mode's own gates, from its own namespace.

    Cut 6a. `landmark_gates.*` is one-to-one with
    `landmarks_interaction.LANDMARK_LINT_CLASSES` and is scored over the
    collect-mode reply goldens; the offer classes judge a proposal and are
    scored over the offer goldens, so they carry
    `landmark_offer.OFFER_GATE_PREFIX` and are loaded — and checked — apart.
    Same `check_gates`, two vocabularies kept honest.
    """
    import landmark_offer as offer  # noqa: PLC0415

    raw = _parse_simple_yaml(_root(framework_root) / "lints.yaml")
    prefix = f"{offer.OFFER_GATE_PREFIX}."
    return {
        key.removeprefix(prefix): float(value)
        for key, value in raw.items()
        if key.startswith(prefix)
    }


_FIXTURE_KEYS = {"fixture_id", "landmarks", "turns"}
_TURN_KEYS = {"stage", "domain", "rung", "sensitive", "expected_landmark",
              "domains_named",
              # v212 (lifehug#221): the person's own message this reply
              # answers, and the labels already in LANDMARKS — the two inputs
              # `landmark_gates.answer_must_record` needs to be honest.
              "user_message", "known_labels"}


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
            structural = conversation_delivery._parse_landmark(  # noqa: SLF001
                pred_turn.get("landmark")
            )
            validated = landmarks_interaction.validate_landmark(structural)
            findings = {
                item["lint"].split(".", 1)[1]
                for item in landmarks_interaction.lint_landmark_reply(
                    pred_turn.get("message", ""),
                    stage=turn["stage"],
                    domain=domain,
                    sensitive=sensitive,
                    domains_named=turn.get("domains_named") or (),
                    # v212: the recording gate reads what the turn emitted and
                    # what the person actually said — exactly what a real
                    # caller holds at this point.
                    landmark=validated,
                    user_message=turn.get("user_message"),
                    known_labels=turn.get("known_labels") or (),
                )
            }
            for lint_class in _applicable(
                domain, sensitive, answered=bool(turn.get("user_message"))
            ):
                counts[lint_class][1] += 1
                counts[lint_class][0] += lint_class not in findings
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
    # Cut 6a: the offer goldens are scored on the SAME seat run, in both
    # modes. They spend no completion — the fixture carries the recorded
    # ones — so there is no `--live` half of this half and nothing to skip.
    offer_fixtures = load_offer_fixtures()
    fixture_errors = fixture_errors + validate_offer_fixtures(offer_fixtures)
    offer_scores = ({} if fixture_errors
                    else score_offer_goldens(offer_fixtures))
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
    failures = failures + ([] if fixture_errors
                          else check_gates(offer_scores, load_offer_gates()))
    # The two families share one report and must not share one key: the offer
    # classes are scored against `load_offer_gates`, and the report prefixes
    # them so a reader can tell `no_form_voice` (a reply lint) from
    # `offer_nothing_dropped` (a proposal lint) at a glance.
    scores.update({(f"offer_{key}" if key.endswith(".compliance") else key): value
                   for key, value in offer_scores.items()})
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
