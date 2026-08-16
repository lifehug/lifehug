#!/usr/bin/env python3
"""Lifehug — the Conversation Interaction eval harness (issue #120).

The Conversation Interaction is model-agnostic by requirement: the
behavior contract lives in portable files under `interactions/conversation/`,
and any qualified model may be seated in it **only after passing this
harness**. This module is the model contract, executable: a model change,
a prompt-file change, or an overlay change is a PR that must pass this
harness in CI, exactly like code.

Four layers, always in this order:

1. **Deterministic lints** (`conversation_lints`, issue #115/#120) — always
   run, dependency-free. This module never re-implements lint logic
   (recurring-defect doctrine); it IMPORTS the shared engine.
2. **Router fixtures + scorer** — schema-validates
   `evals/goldens/router_fixtures.json` (always run) and scores
   predictions per class against `router_gates.*` (flat dotted keys in
   `evals/lints.yaml`). Two prediction sources, both scored by the SAME
   `score_predictions`/`check_router_gates` pair:
   - **Deterministic offline** (always run, keyless): the router's own
     safe-default fallback (`conversation_delivery.route_message` with a
     forced-not-ready status resolver) applied to every fixture. This is
     RECALL-SAFE BY CONSTRUCTION, not a classifier — router.md's own
     unsure-fallback rule only ever resolves to `answer` (a pending
     question), `continue_session` (an open session), or the terminal
     `new_story` fallback; fixtures carry no `pending_question_id`, so
     `answer` is structurally unreachable offline. This harness therefore
     reports the deterministic run's per-class numbers as INFORMATIONAL
     and separately asserts the two safe-default guarantees it actually
     makes (100% recall on `continue_session` when a session is open, 100%
     recall on `new_story` as the terminal no-session fallback) rather than
     gating it against `router_gates.*`, which targets a real classifier.
   - **Live** (optional, skip-annotated keyless) — `lifehug.py route`'s own
     path (`conversation_delivery.route_message` with a real provider),
     gated against `router_gates.*` for real.
   Until a live provider is available, `check_router_gates` against the
   committed `router_sample_predictions.json` fixture proves the scorer's
   arithmetic and gate enforcement deterministically (contract: "the
   scorer + a committed sample predictions fixture prove the gate math
   deterministically").
3. **Golden-transcript property assertions** — always run, over every
   committed `evals/goldens/*.json` transcript: the closed vocabulary
   (`receipt_quotes_user`, `no_new_topic_mid_arc`,
   `closing_has_takeaway_and_hook`, `closing_is_declarative`,
   `closing_engages_final_message`, `deflects_off_scope`,
   `demonstrated_knowledge_opener_shape`) plus Layer-1 lints over every
   lifehug turn (seam_ok-aware).
4. **Judge rubrics + personas** — model-backed, keyless-skippable. Every
   model-backed step is SKIPPED loudly (named step + reason), never
   silently green, never red without keys. `--emit-tasks` writes agent-task
   prompts under `state/agent_tasks/evals/` (the existing keyless emit
   idiom — see `arc_planner.emit_tasks`).

Public surface (each function pure except where documented):

    load_router_fixtures / validate_router_fixtures / score_predictions /
    load_router_gates / check_router_gates / deterministic_router_predictions
    load_goldens / validate_golden_schema / check_golden
    build_judge_prompt / parse_judge_response / run_judge
    build_persona_prompt / parse_persona_response / run_persona
    run (the orchestrator) / main (the CLI, `lifehug.py conversation-evals`)

No new dependencies; stdlib only. Asset loading is framework-scoped (like
`conversation_lints`'s own `_conversation_evals_path`), never vault-scoped.
"""

from __future__ import annotations

import argparse
import json
import random
import re
import sys
from pathlib import Path
from typing import Callable

import conversation
import conversation_lints
from ai_provider import AIProviderError, ProviderStatus, call_ai, provider_status
from lifehug_core import AGENT_TASKS_DIR, INTERACTIONS_DIR, load_config, now_utc, write_json, write_text

# --------------------------------------------------------------------------
# Paths + shared constants
# --------------------------------------------------------------------------

EVALS_DIR = INTERACTIONS_DIR / "conversation" / "evals"
GOLDENS_DIR = EVALS_DIR / "goldens"
ROUTER_FIXTURES_FILE = "router_fixtures.json"
ROUTER_SAMPLE_PREDICTIONS_FILE = "router_sample_predictions.json"
#: ADR 0014 (issue #163): a deliberately-broken closing fixture that
#: reproduces the leaked-scaffolding SHAPE, used only to prove the new
#: structured-close lints trip (tests/test_structured_close.py loads it
#: directly). It is NOT a correct reference transcript, so — like the
#: router fixture files above — it is excluded from load_goldens()'s sweep
#: rather than required to pass check_golden like every other committed
#: golden.
CLOSING_SCAFFOLD_LEAK_FIXTURE_FILE = "closing-scaffold-leak-bad-01.json"
#: Golden-transcript filenames living in goldens/ that are NOT golden
#: transcripts (router fixture/prediction data + the format doc, plus the
#: intentionally-broken lint fixture above) — excluded from load_goldens()'s
#: glob.
NON_GOLDEN_FILENAMES = frozenset({
    ROUTER_FIXTURES_FILE,
    ROUTER_SAMPLE_PREDICTIONS_FILE,
    CLOSING_SCAFFOLD_LEAK_FIXTURE_FILE,
})

VALID_ROUTER_INTENTS = frozenset(
    {"answer", "new_story", "command", "continue_session", "out_of_scope"}
)
VALID_MODES = frozenset({"chat", "conversation"})
VALID_REGISTERS = frozenset({"celebration", "hard", "neutral"})
VALID_TURN_KINDS = frozenset({"opener", "receipt", "receipt_payout", "closing", "deflection"})

#: The closed property-assertion vocabulary (contract, golden schema).
#: "closing_is_declarative" (issue #139, pure-chat wave) is an additive
#: extension: a closing turn has no question anywhere and no banned
#: closing meta-phrase — behavior.md rule 8's declarative-close doctrine.
#: "closing_engages_final_message" (ADR 0015, issue #167, content-first
#: close) is a NEW property id as of this PR — FLAGGED for the platform's
#: closed-vocabulary reconciliation at the next pin bump (contract,
#: Scope 4): a closing turn must demonstrably respond to the final user
#: turn, not just the rolling summary.
#: FIVE NEW property ids as of issue #168 / ADR 0016 (asking-supply) —
#: FLAGGED for the platform's closed-vocabulary reconciliation at the next
#: pin bump: "held_question_offered_as_door", "no_uninvited_question_past_target",
#: "invitation_hatch_honored", "empty_supply_honest_reply",
#: "coverage_not_volunteered".
PROPERTY_IDS = frozenset({
    "receipt_quotes_user",
    "no_new_topic_mid_arc",
    "closing_has_takeaway_and_hook",
    "closing_is_declarative",
    "closing_engages_final_message",
    "deflects_off_scope",
    "demonstrated_knowledge_opener_shape",
    "held_question_offered_as_door",
    "no_uninvited_question_past_target",
    "invitation_hatch_honored",
    "empty_supply_honest_reply",
    "coverage_not_volunteered",
})

#: The seven-persona suite (filenames under evals/personas/, contract order).
PERSONAS = (
    "terse", "rambler", "topic-switcher", "off-scope-prober",
    "grief-fresh", "ruminator", "enthusiast",
)
#: Personas whose runs must demonstrate one NAMED behavioral observation
#: (contract, Binding facts): grief-fresh -> deferral, ruminator -> back-off,
#: enthusiast -> no hard stop. The other four personas still run through
#: Layer 1 + the judge rubric; they just have no dedicated structural check.
NAMED_OBSERVATIONS = {
    "grief-fresh": "deferral",
    "ruminator": "back_off",
    "enthusiast": "no_hard_stop",
}

RUBRIC_CLAUSE_COUNT = 13  # behavior.md's 13 hard rules; rubrics.md is 1:1


# --------------------------------------------------------------------------
# Layer 2 — router fixtures + scorer
# --------------------------------------------------------------------------


def _goldens_path(*parts: str, framework_root: str | Path | None = None) -> Path:
    base = Path(framework_root) / "interactions" / "conversation" / "evals" / "goldens" \
        if framework_root is not None else GOLDENS_DIR
    return base.joinpath(*parts)


def load_router_fixtures(*, framework_root: str | Path | None = None) -> list[dict]:
    """Read the committed router_fixtures.json list."""
    path = _goldens_path(ROUTER_FIXTURES_FILE, framework_root=framework_root)
    data = json.loads(path.read_text(encoding="utf-8"))
    return data if isinstance(data, list) else []


def load_router_sample_predictions(*, framework_root: str | Path | None = None) -> list[dict]:
    """Read the committed router_sample_predictions.json list — a hand-authored
    'what a good live model would say' fixture used to prove the scorer's
    arithmetic and router_gates enforcement deterministically and keylessly."""
    path = _goldens_path(ROUTER_SAMPLE_PREDICTIONS_FILE, framework_root=framework_root)
    data = json.loads(path.read_text(encoding="utf-8"))
    return data if isinstance(data, list) else []


def validate_router_fixture(entry: object) -> list[str]:
    """Schema errors for one {text, session_open, intent} fixture; [] if clean."""
    if not isinstance(entry, dict):
        return ["fixture is not an object"]
    errors = []
    text = entry.get("text")
    if not isinstance(text, str) or not text.strip():
        errors.append("fixture.text must be a non-empty string")
    session_open = entry.get("session_open")
    if not isinstance(session_open, bool):
        errors.append("fixture.session_open must be a boolean")
    intent = entry.get("intent")
    if intent not in VALID_ROUTER_INTENTS:
        errors.append(f"fixture.intent must be one of {sorted(VALID_ROUTER_INTENTS)}, got {intent!r}")
    return errors


def validate_router_fixtures(fixtures: object) -> list[str]:
    """Schema errors across the whole fixtures list, one line per bad entry."""
    if not isinstance(fixtures, list) or not fixtures:
        return ["router_fixtures.json must be a non-empty JSON list"]
    errors: list[str] = []
    for index, entry in enumerate(fixtures):
        for detail in validate_router_fixture(entry):
            errors.append(f"fixture[{index}]: {detail}")
    return errors


def score_predictions(fixtures: list[dict], predictions: list[dict]) -> dict[str, dict]:
    """Per-class precision/recall from a predictions file matched to fixtures by text.

    Returns {class: {"tp", "fp", "fn", "precision", "recall"}} for every
    class in VALID_ROUTER_INTENTS that appears in either the fixtures or the
    predictions, plus "_unmatched" (predictions whose text matched no
    fixture — never silently dropped). Matching is exact on `text` (the
    fixture and its prediction describe the same inbound message); a
    fixture with no matching prediction counts toward that class's FN only.
    """
    by_text: dict[str, str] = {}
    for prediction in predictions:
        if not isinstance(prediction, dict):
            continue
        text = prediction.get("text")
        predicted = prediction.get("predicted")
        if isinstance(text, str) and predicted in VALID_ROUTER_INTENTS:
            by_text[text] = predicted

    counts = {intent: {"tp": 0, "fp": 0, "fn": 0} for intent in VALID_ROUTER_INTENTS}
    unmatched: list[str] = []
    matched_texts: set[str] = set()
    for fixture in fixtures:
        text = fixture.get("text")
        truth = fixture.get("intent")
        if not isinstance(text, str) or truth not in VALID_ROUTER_INTENTS:
            continue
        predicted = by_text.get(text)
        matched_texts.add(text)
        if predicted is None:
            counts[truth]["fn"] += 1
            continue
        if predicted == truth:
            counts[truth]["tp"] += 1
        else:
            counts[truth]["fn"] += 1
            counts[predicted]["fp"] += 1

    for text in by_text:
        if text not in matched_texts:
            unmatched.append(text)

    scores: dict[str, dict] = {}
    for intent, c in counts.items():
        tp, fp, fn = c["tp"], c["fp"], c["fn"]
        precision = tp / (tp + fp) if (tp + fp) else None
        recall = tp / (tp + fn) if (tp + fn) else None
        scores[intent] = {"tp": tp, "fp": fp, "fn": fn, "precision": precision, "recall": recall}
    scores["_unmatched"] = unmatched
    return scores


def load_router_gates(config: dict | None = None) -> dict[str, dict[str, float]]:
    """Parse router_gates.<class>.<precision|recall> flat dotted keys from lints.yaml.

    Reuses conversation_lints.load_lints_config's raw loader rather than
    re-parsing the file (single authority for the flat-scalar-subset format).
    """
    raw = config if config is not None else conversation_lints.load_lints_config()
    gates: dict[str, dict[str, float]] = {}
    for key, value in raw.items():
        if not key.startswith("router_gates."):
            continue
        parts = key.split(".")
        if len(parts) != 3 or parts[2] not in ("precision", "recall"):
            continue
        _, intent, metric = parts
        try:
            gates.setdefault(intent, {})[metric] = float(value)
        except (TypeError, ValueError):
            continue
    return gates


def check_router_gates(scores: dict[str, dict], gates: dict[str, dict[str, float]]) -> list[str]:
    """Failure strings for every configured gate the scores don't clear.

    A class with no configured gate is never enforced (contract: gates are
    opt-in per class, expressed as flat dotted keys). A None precision/recall
    (no predictions for that class) with a configured gate is a failure —
    a gate that can never be checked is not a passed gate.
    """
    failures: list[str] = []
    for intent, thresholds in gates.items():
        class_scores = scores.get(intent, {})
        for metric, threshold in thresholds.items():
            actual = class_scores.get(metric)
            if actual is None or actual < threshold:
                failures.append(
                    f"router_gates.{intent}.{metric}: {actual!r} < {threshold} required"
                )
    return failures


def deterministic_router_predictions(
    fixtures: list[dict], *, status_resolver: Callable[..., object] | None = None
) -> list[dict]:
    """The router's own deterministic safe-default applied to every fixture.

    Forces the offline (not-ready) path via an injected status_resolver so
    the result is reproducible in CI regardless of whether the machine
    running this happens to have a provider configured — this function's
    whole point is proving the SAFE-DEFAULT rule, not the live model.
    """
    from conversation_delivery import route_message  # noqa: PLC0415

    forced_offline = status_resolver or (
        lambda *a, **k: ProviderStatus("offline", "offline", False, "forced offline (deterministic eval)")
    )
    predictions = []
    for fixture in fixtures:
        session_open = bool(fixture.get("session_open"))
        result = route_message(
            str(fixture.get("text", "")),
            channel="cli",
            rotation={},
            open_session={"session_id": "eval-fixture"} if session_open else None,
            status_resolver=forced_offline,
        )
        predictions.append({"text": fixture.get("text"), "predicted": result["intent"]})
    return predictions


def check_deterministic_safe_default(fixtures: list[dict], predictions: list[dict]) -> list[str]:
    """The two guarantees the safe default actually makes (see module docstring):
    every open-session fixture predicts continue_session; every closed-session
    fixture (no pending question, by fixture-schema construction) predicts the
    terminal new_story fallback. Anything else is a safe-default regression."""
    by_text = {p.get("text"): p.get("predicted") for p in predictions if isinstance(p, dict)}
    errors: list[str] = []
    for fixture in fixtures:
        text = fixture.get("text")
        expected = "continue_session" if fixture.get("session_open") else "new_story"
        actual = by_text.get(text)
        if actual != expected:
            errors.append(
                f"safe-default regression for {text!r}: expected {expected!r}, got {actual!r}"
            )
    return errors


def run_router_live(
    fixtures: list[dict],
    *,
    model: str | None = None,
    ai_call: Callable[[str, str], str] | None = None,
    status_resolver: Callable[..., object] | None = None,
) -> dict:
    """Live router predictions over every fixture, keyless = skip.

    Returns {"status": "skipped", "reason": ...} or
    {"status": "ran", "model": ..., "scores": ..., "gate_failures": [...]}.
    """
    from conversation_delivery import route_message, router_model  # noqa: PLC0415

    config = _safe_config()
    resolved_model = model or router_model(config)
    resolve_status = status_resolver or provider_status
    selected = resolve_status(resolved_model, probe=False)
    if not getattr(selected, "ready", False):
        return {"status": "skipped", "reason": "no unattended AI provider is ready"}

    predictions = []
    for fixture in fixtures:
        session_open = bool(fixture.get("session_open"))
        result = route_message(
            str(fixture.get("text", "")),
            channel="cli",
            rotation={},
            open_session={"session_id": "eval-fixture"} if session_open else None,
            ai_call=ai_call,
            status_resolver=resolve_status,
        )
        predictions.append({"text": fixture.get("text"), "predicted": result["intent"]})

    scores = score_predictions(fixtures, predictions)
    gates = load_router_gates()
    failures = check_router_gates(scores, gates)
    return {"status": "ran", "model": resolved_model, "scores": scores, "gate_failures": failures}


# --------------------------------------------------------------------------
# Layer 3 — golden-transcript property assertions
# --------------------------------------------------------------------------


def load_goldens(*, framework_root: str | Path | None = None) -> list[dict]:
    """Every golden transcript under goldens/*.json (router fixture data excluded)."""
    base = Path(framework_root) / "interactions" / "conversation" / "evals" / "goldens" \
        if framework_root is not None else GOLDENS_DIR
    goldens = []
    for path in sorted(base.glob("*.json")):
        if path.name in NON_GOLDEN_FILENAMES:
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            goldens.append(data)
    return goldens


def validate_golden_schema(golden: object) -> list[str]:
    """Structural schema errors for one golden transcript; [] if clean."""
    if not isinstance(golden, dict):
        return ["golden is not an object"]
    errors: list[str] = []
    golden_id = golden.get("golden_id")
    if not isinstance(golden_id, str) or not golden_id.strip():
        errors.append("golden_id must be a non-empty string")
    label = golden_id if isinstance(golden_id, str) else "<unknown>"

    if golden.get("mode") not in VALID_MODES:
        errors.append(f"{label}: mode must be one of {sorted(VALID_MODES)}")
    if golden.get("register") not in VALID_REGISTERS:
        errors.append(f"{label}: register must be one of {sorted(VALID_REGISTERS)}")

    arc = golden.get("arc")
    if not isinstance(arc, dict):
        errors.append(f"{label}: arc must be an object")
        arc = {}
    if "question_id" not in arc:
        errors.append(f"{label}: arc.question_id is required")
    if not isinstance(arc.get("intents"), list):
        errors.append(f"{label}: arc.intents must be a list")

    turns = golden.get("turns")
    if not isinstance(turns, list) or not turns:
        errors.append(f"{label}: turns must be a non-empty list")
        turns = []

    declared_properties: set[str] = set()
    for index, turn in enumerate(turns):
        if not isinstance(turn, dict):
            errors.append(f"{label}: turns[{index}] is not an object")
            continue
        role = turn.get("role")
        if role not in ("user", "lifehug"):
            errors.append(f"{label}: turns[{index}].role must be user|lifehug")
        if not isinstance(turn.get("text"), str) or not turn["text"].strip():
            errors.append(f"{label}: turns[{index}].text must be a non-empty string")
        if role != "lifehug":
            continue
        annotations = turn.get("annotations")
        if not isinstance(annotations, dict):
            errors.append(f"{label}: turns[{index}].annotations is required for lifehug turns")
            continue
        if annotations.get("kind") not in VALID_TURN_KINDS:
            errors.append(f"{label}: turns[{index}].annotations.kind must be one of {sorted(VALID_TURN_KINDS)}")
        properties = annotations.get("properties") or []
        if not isinstance(properties, list):
            errors.append(f"{label}: turns[{index}].annotations.properties must be a list")
            properties = []
        for prop in properties:
            if prop not in PROPERTY_IDS:
                errors.append(f"{label}: turns[{index}] declares unknown property {prop!r}")
            declared_properties.add(prop)

    if "no_new_topic_mid_arc" in declared_properties:
        topics = arc.get("topics")
        if not isinstance(topics, list) or not topics:
            errors.append(
                f"{label}: arc.topics (this harness's extension) is required "
                "when no_new_topic_mid_arc is declared"
            )

    # issue #168 / ADR 0016 (asking-supply): arc.asking_supply is this
    # harness's own extension for the ASKING_SUPPLY block's contents —
    # [{"qid": ..., "text": ...}, ...], possibly empty/absent (the honest
    # empty case). Required, and non-empty, when a golden declares a
    # property that asserts something was actually offered from it.
    if declared_properties & {
        "held_question_offered_as_door", "invitation_hatch_honored", "no_uninvited_question_past_target",
    }:
        supply = arc.get("asking_supply")
        if not isinstance(supply, list) or not supply:
            errors.append(
                f"{label}: arc.asking_supply (this harness's extension) must "
                "be a non-empty list when held_question_offered_as_door, "
                "invitation_hatch_honored, or no_uninvited_question_past_target "
                "is declared"
            )
    if "empty_supply_honest_reply" in declared_properties:
        supply = arc.get("asking_supply")
        if supply not in (None, []):
            errors.append(
                f"{label}: arc.asking_supply must be empty or absent when "
                "empty_supply_honest_reply is declared"
            )
        coverage = arc.get("coverage")
        if not isinstance(coverage, dict) or not isinstance(coverage.get("answered"), int) \
                or not isinstance(coverage.get("total"), int):
            errors.append(
                f"{label}: arc.coverage.{{answered,total}} (ints) is required "
                "when empty_supply_honest_reply is declared"
            )

    return errors


def _lifehug_turns(golden: dict) -> list[tuple[int, dict]]:
    return [
        (i, t) for i, t in enumerate(golden.get("turns") or [])
        if isinstance(t, dict) and t.get("role") == "lifehug"
    ]


def _preceding_user_text(golden: dict, turn_index: int) -> str | None:
    turns = golden.get("turns") or []
    for i in range(turn_index - 1, -1, -1):
        turn = turns[i]
        if isinstance(turn, dict) and turn.get("role") == "user":
            return turn.get("text")
    return None


def _turns_with_property(golden: dict, prop: str) -> list[tuple[int, dict]]:
    return [
        (i, t) for i, t in _lifehug_turns(golden)
        if prop in ((t.get("annotations") or {}).get("properties") or [])
    ]


def _check_receipt_quotes_user(golden: dict) -> list[str]:
    errors = []
    for index, turn in _turns_with_property(golden, "receipt_quotes_user"):
        annotations = turn.get("annotations") or {}
        quoted_span = annotations.get("quoted_span")
        if not isinstance(quoted_span, str) or not quoted_span:
            errors.append(f"turns[{index}]: receipt_quotes_user requires a non-empty quoted_span")
            continue
        prior_user_text = _preceding_user_text(golden, index) or ""
        if quoted_span not in prior_user_text:
            errors.append(
                f"turns[{index}]: quoted_span {quoted_span!r} is not a verbatim "
                "substring of the prior user turn"
            )
        if quoted_span not in (turn.get("text") or ""):
            errors.append(
                f"turns[{index}]: quoted_span {quoted_span!r} is not a verbatim "
                "substring of the receipt turn itself"
            )
    return errors


def _check_no_new_topic_mid_arc(golden: dict) -> list[str]:
    if not _turns_with_property(golden, "no_new_topic_mid_arc"):
        return []
    allowed = set((golden.get("arc") or {}).get("topics") or [])
    errors = []
    for index, turn in _lifehug_turns(golden):
        topic = (turn.get("annotations") or {}).get("topic")
        if topic and allowed and topic not in allowed:
            errors.append(
                f"turns[{index}]: topic {topic!r} is outside the arc's declared "
                f"set {sorted(allowed)}"
            )
    return errors


def _check_closing_has_takeaway_and_hook(golden: dict) -> list[str]:
    errors = []
    for index, turn in _turns_with_property(golden, "closing_has_takeaway_and_hook"):
        annotations = turn.get("annotations") or {}
        if annotations.get("kind") != "closing":
            errors.append(f"turns[{index}]: closing_has_takeaway_and_hook requires kind == 'closing'")
        text = (turn.get("text") or "").rstrip().rstrip('"”’\'')
        if text.endswith("?"):
            errors.append(f"turns[{index}]: closing turn ends with a trailing question")
        if not isinstance(annotations.get("takeaway"), str) or not annotations["takeaway"].strip():
            errors.append(f"turns[{index}]: closing turn requires a non-empty takeaway annotation")
        if not isinstance(annotations.get("hook"), str) or not annotations["hook"].strip():
            errors.append(f"turns[{index}]: closing turn requires a non-empty hook annotation")
    return errors


def _check_closing_is_declarative(golden: dict) -> list[str]:
    """behavior.md rule 8's declarative-close doctrine (issue #139,
    pure-chat wave): a closing turn has NO question anywhere (stricter
    than the ordinary one-question-per-turn lint — a close permits zero,
    not one) and no banned closing meta-phrase. Reuses
    ``conversation_lints.lint_closing_phrases`` — the same authority the
    runtime's ``lint_outgoing(is_closing=True)`` checks — rather than a
    forked phrase list (recurring-defect doctrine)."""
    errors = []
    for index, turn in _turns_with_property(golden, "closing_is_declarative"):
        annotations = turn.get("annotations") or {}
        if annotations.get("kind") != "closing":
            errors.append(f"turns[{index}]: closing_is_declarative requires kind == 'closing'")
        text = turn.get("text") or ""
        stripped = conversation_lints._strip_echoed_questions(text)  # noqa: SLF001 — shared authority
        if "?" in stripped:
            errors.append(
                f"turns[{index}]: closing turn contains a question — closes must be "
                "purely declarative (rule 8)"
            )
        for finding in conversation_lints.lint_closing_phrases(text):
            errors.append(f"turns[{index}]: {finding['detail']}")
    return errors


#: "Distinctive" content tokens for the overlap check below — plain
#: alphabetic words of at least this length, lowercased. Deliberately
#: crude (contract, Scope 4: "keep the checker honest and simple") — this
#: is not an NLP overlap measure, just a concrete, verifiable signal that
#: the closing turn's text shares real content with the final user turn
#: rather than being generic.
_DISTINCTIVE_TOKEN_MIN_LEN = 6
_WORD_RE = re.compile(r"[A-Za-z']+")


def _distinctive_tokens(text: str) -> set[str]:
    return {
        word.lower() for word in _WORD_RE.findall(text or "")
        if len(word) >= _DISTINCTIVE_TOKEN_MIN_LEN
    }


def _check_closing_engages_final_message(golden: dict) -> list[str]:
    """ADR 0015 (issue #167): the closing turn must engage the final user
    turn's actual content, not just a generic sign-off. Verifiable via
    content-token overlap — the closing text must share at least one
    distinctive token with the immediately preceding user turn."""
    errors = []
    for index, turn in _turns_with_property(golden, "closing_engages_final_message"):
        annotations = turn.get("annotations") or {}
        if annotations.get("kind") != "closing":
            errors.append(f"turns[{index}]: closing_engages_final_message requires kind == 'closing'")
        prior_user_text = _preceding_user_text(golden, index) or ""
        final_tokens = _distinctive_tokens(prior_user_text)
        if not final_tokens:
            errors.append(
                f"turns[{index}]: closing_engages_final_message requires a "
                "preceding user turn with distinctive content tokens to check against"
            )
            continue
        closing_tokens = _distinctive_tokens(turn.get("text") or "")
        if not (final_tokens & closing_tokens):
            errors.append(
                f"turns[{index}]: closing turn shares no distinctive content "
                f"token with the final user message (candidates: {sorted(final_tokens)})"
            )
    return errors


def _check_deflects_off_scope(golden: dict) -> list[str]:
    errors = []
    for index, turn in _turns_with_property(golden, "deflects_off_scope"):
        annotations = turn.get("annotations") or {}
        if annotations.get("kind") != "deflection":
            errors.append(f"turns[{index}]: deflects_off_scope requires kind == 'deflection'")
        turns = golden.get("turns") or []
        preceding = turns[index - 1] if index > 0 else None
        if not isinstance(preceding, dict) or preceding.get("role") != "user" or not preceding.get("off_scope"):
            errors.append(
                f"turns[{index}]: deflects_off_scope requires the immediately preceding "
                "turn to be a user turn flagged off_scope: true"
            )
    return errors


def _check_demonstrated_knowledge_opener_shape(golden: dict) -> list[str]:
    errors = []
    for index, turn in _turns_with_property(golden, "demonstrated_knowledge_opener_shape"):
        annotations = turn.get("annotations") or {}
        if annotations.get("kind") != "opener":
            errors.append(f"turns[{index}]: demonstrated_knowledge_opener_shape requires kind == 'opener'")
        text = turn.get("text") or ""
        stripped = conversation_lints._strip_echoed_questions(text)  # noqa: SLF001 — shared authority
        sentences = [s for s in conversation_lints._split_sentences(stripped) if s.strip()]  # noqa: SLF001
        questions = [s for s in sentences if conversation_lints._is_question(s)]  # noqa: SLF001
        if len(questions) != 1:
            errors.append(
                f"turns[{index}]: opener must contain exactly one gap-invitation "
                f"question, found {len(questions)}"
            )
        elif sentences[-1] is not questions[-1] or sentences.index(questions[-1]) == 0:
            errors.append(
                f"turns[{index}]: opener must be summary-then-gap — one or more "
                "record-summary sentences, THEN the single question, last"
            )
    return errors


#: issue #168 / ADR 0016 (asking-supply) checkers below.


def _asking_supply_qids(golden: dict) -> set[str]:
    supply = (golden.get("arc") or {}).get("asking_supply") or []
    return {str(item.get("qid")) for item in supply if isinstance(item, dict) and item.get("qid")}


#: A crude, concrete, "introduced honestly as held" signal (contract, Scope
#: 5: "keep the checker honest and simple" — same spirit as
#: _distinctive_tokens above, not an NLP quality measure).
_HELD_FRAMING_MARKERS = ("holding", "been sitting with", "been meaning to ask")


def _check_held_question_offered_as_door(golden: dict) -> list[str]:
    """A held question, when offered, is the turn's declinable door —
    introduced honestly as held and actually drawn from arc.asking_supply
    (never fabricated)."""
    errors = []
    supply_qids = _asking_supply_qids(golden)
    for index, turn in _turns_with_property(golden, "held_question_offered_as_door"):
        annotations = turn.get("annotations") or {}
        held_qid = annotations.get("held_question_id")
        if not held_qid or str(held_qid) not in supply_qids:
            errors.append(
                f"turns[{index}]: held_question_offered_as_door requires "
                "annotations.held_question_id to be one of arc.asking_supply's qids"
            )
        text = (turn.get("text") or "").lower()
        if not any(marker in text for marker in _HELD_FRAMING_MARKERS):
            errors.append(
                f"turns[{index}]: held_question_offered_as_door requires the "
                "question to be introduced honestly as held (e.g. containing "
                f"one of {_HELD_FRAMING_MARKERS!r})"
            )
    return errors


def _check_no_uninvited_question_past_target(golden: dict) -> list[str]:
    """Past target, with supply present, an uninvited moment gets no
    question at all — the gate's discard behavior, demonstrated as a
    correct turn shape."""
    errors = []
    for index, turn in _turns_with_property(golden, "no_uninvited_question_past_target"):
        annotations = turn.get("annotations") or {}
        if annotations.get("user_invited_question") is not False:
            errors.append(
                f"turns[{index}]: no_uninvited_question_past_target requires "
                "annotations.user_invited_question == false"
            )
        stripped = conversation_lints._strip_echoed_questions(turn.get("text") or "")  # noqa: SLF001
        if "?" in stripped:
            errors.append(
                f"turns[{index}]: no_uninvited_question_past_target requires "
                "no question in the turn text"
            )
    return errors


def _check_invitation_hatch_honored(golden: dict) -> list[str]:
    """Past target, an invited moment ("what else you got?") gets exactly
    one question, drawn from asking_supply, with the invitation honestly
    declared."""
    errors = []
    supply_qids = _asking_supply_qids(golden)
    for index, turn in _turns_with_property(golden, "invitation_hatch_honored"):
        annotations = turn.get("annotations") or {}
        if annotations.get("user_invited_question") is not True:
            errors.append(
                f"turns[{index}]: invitation_hatch_honored requires "
                "annotations.user_invited_question == true"
            )
        held_qid = annotations.get("held_question_id")
        if not held_qid or str(held_qid) not in supply_qids:
            errors.append(
                f"turns[{index}]: invitation_hatch_honored requires "
                "annotations.held_question_id to be one of arc.asking_supply's qids"
            )
        stripped = conversation_lints._strip_echoed_questions(turn.get("text") or "")  # noqa: SLF001
        sentences = [s for s in conversation_lints._split_sentences(stripped) if s.strip()]  # noqa: SLF001
        questions = [s for s in sentences if conversation_lints._is_question(s)]  # noqa: SLF001
        if len(questions) != 1:
            errors.append(
                f"turns[{index}]: invitation_hatch_honored requires exactly "
                f"one question in the turn, found {len(questions)}"
            )
    return errors


def _check_empty_supply_honest_reply(golden: dict) -> list[str]:
    """A hatch with nothing in the supply gets an honest no-questions
    reply naming answered/total — never a fabricated question."""
    errors = []
    supply_qids = _asking_supply_qids(golden)
    coverage = (golden.get("arc") or {}).get("coverage") or {}
    for index, turn in _turns_with_property(golden, "empty_supply_honest_reply"):
        if supply_qids:
            errors.append(
                f"turns[{index}]: empty_supply_honest_reply requires "
                "arc.asking_supply to be empty or absent"
            )
        answered, total = coverage.get("answered"), coverage.get("total")
        if not isinstance(answered, int) or not isinstance(total, int):
            errors.append(
                f"turns[{index}]: empty_supply_honest_reply requires "
                "arc.coverage.answered/total (ints) to check against"
            )
            continue
        text = turn.get("text") or ""
        stripped = conversation_lints._strip_echoed_questions(text)  # noqa: SLF001
        if "?" in stripped:
            errors.append(
                f"turns[{index}]: empty_supply_honest_reply requires no "
                "fabricated question when the supply is empty"
            )
        if str(answered) not in text or str(total) not in text:
            errors.append(
                f"turns[{index}]: empty_supply_honest_reply requires the "
                f"reply to actually name the coverage numbers ({answered} "
                f"of {total})"
            )
    return errors


#: Crude, concrete "an answered/total count was stated" signal — same
#: honest-and-simple spirit as _distinctive_tokens/_HELD_FRAMING_MARKERS
#: above, not a language-understanding check.
_COVERAGE_STATEMENT_RE = re.compile(r"\d+\s+of\s+\d+", re.IGNORECASE)


def _check_coverage_not_volunteered(golden: dict) -> list[str]:
    """Coverage numbers ride in context but are never volunteered
    unprompted (Defaults) — this checker asserts the DECLARING turn's own
    text contains no answered/total statement."""
    errors = []
    for index, turn in _turns_with_property(golden, "coverage_not_volunteered"):
        if _COVERAGE_STATEMENT_RE.search(turn.get("text") or ""):
            errors.append(
                f"turns[{index}]: coverage_not_volunteered requires the "
                "reply not to state an answered/total count unprompted"
            )
    return errors


PROPERTY_CHECKERS: dict[str, Callable[[dict], list[str]]] = {
    "receipt_quotes_user": _check_receipt_quotes_user,
    "no_new_topic_mid_arc": _check_no_new_topic_mid_arc,
    "closing_has_takeaway_and_hook": _check_closing_has_takeaway_and_hook,
    "closing_is_declarative": _check_closing_is_declarative,
    "closing_engages_final_message": _check_closing_engages_final_message,
    "deflects_off_scope": _check_deflects_off_scope,
    "demonstrated_knowledge_opener_shape": _check_demonstrated_knowledge_opener_shape,
    "held_question_offered_as_door": _check_held_question_offered_as_door,
    "no_uninvited_question_past_target": _check_no_uninvited_question_past_target,
    "invitation_hatch_honored": _check_invitation_hatch_honored,
    "empty_supply_honest_reply": _check_empty_supply_honest_reply,
    "coverage_not_volunteered": _check_coverage_not_volunteered,
}


def check_golden_properties(golden: dict) -> list[str]:
    """Run every DECLARED property's checker (a golden only proves what it declares)."""
    declared: set[str] = set()
    for _, turn in _lifehug_turns(golden):
        declared.update((turn.get("annotations") or {}).get("properties") or [])
    errors: list[str] = []
    for prop in sorted(declared):
        checker = PROPERTY_CHECKERS.get(prop)
        if checker is None:
            errors.append(f"unknown property id: {prop}")
            continue
        errors.extend(checker(golden))
    return errors


def check_golden_lints(golden: dict) -> list[str]:
    """Every lifehug turn must pass Layer 1 (seam_ok-aware, contract requirement)."""
    findings = conversation_lints.lint_transcript(golden.get("turns") or [])
    return [
        f"turns[{f['turn_index']}]: {f['lint']} — {f['detail']}" for f in findings
    ]


def check_golden(golden: dict) -> list[str]:
    """Schema + Layer-1 lints + declared property assertions, combined."""
    errors = validate_golden_schema(golden)
    if errors:
        # A structurally invalid golden can't be safely lint/property-checked.
        return errors
    return check_golden_lints(golden) + check_golden_properties(golden)


# --------------------------------------------------------------------------
# Layer 4 — judge rubrics + personas (model-backed, keyless-skippable)
# --------------------------------------------------------------------------


def _safe_config() -> dict:
    try:
        return load_config()
    except Exception:  # noqa: BLE001 — a malformed local config never blocks the harness
        return {}


def judge_model(config: dict | None = None) -> str:
    """judge_model -> classify_model -> classify_story.DEFAULT_MODEL (contract)."""
    cfg = config if isinstance(config, dict) else _safe_config()
    from classify_story import DEFAULT_MODEL  # noqa: PLC0415

    return str(cfg.get("judge_model") or cfg.get("classify_model") or DEFAULT_MODEL)


_RUBRIC_CLAUSE_RE = re.compile(
    r'^\d+\.\s+\*\*(?P<title>[^*]+)\*\*\s*(?P<body>.*)$', re.MULTILINE
)


def load_rubric_clauses(*, framework_root: str | Path | None = None) -> list[dict]:
    """Parse rubrics.md's numbered binary clauses into [{"number", "title", "text"}]."""
    text = conversation.read_conversation_definition(
        "evals", "rubrics.md", framework_root=framework_root
    )
    clauses = []
    for number, match in enumerate(_RUBRIC_CLAUSE_RE.finditer(text), start=1):
        clauses.append({
            "number": number,
            "title": match.group("title").strip(),
            "text": match.group("body").strip(),
        })
    return clauses


def build_judge_prompt(payload: dict) -> str:
    """Pure builder: rubric clauses (pre-ordered by the caller) + a transcript.

    ``payload``: {"turns": [...], "clause_order": [clause dicts, already
    shuffled by the caller — randomized clause order is the RUNNER's job,
    per the contract's "randomized clause order"; this stays pure/testable}.
    """
    turns = payload["turns"]
    clauses = payload["clause_order"]
    transcript_lines = [f"{t.get('role')}: {t.get('text')}" for t in turns]
    clause_lines = [f"{c['number']}. {c['title']} {c['text']}" for c in clauses]
    return (
        "You are grading ONE conversation transcript against Lifehug's Conversation "
        "Interaction hard rules. Answer EVERY clause below with a binary verdict — "
        "\"yes\" means the rule was upheld throughout the transcript; a single "
        "violation anywhere is \"no\", even if every other turn was clean.\n\n"
        "## TRANSCRIPT\n\n" + "\n".join(transcript_lines) + "\n\n"
        "## CLAUSES (answer every one, in this order)\n\n" + "\n".join(clause_lines) + "\n\n"
        "## OUTPUT\n\nReturn STRICT JSON only (no prose, no code fence): "
        '{"verdicts": {"<clause number>": true|false, ...}}\n'
    )


def parse_judge_response(raw: object) -> dict[str, bool] | None:
    """Parse the judge's {"verdicts": {...}} shape; None on anything unusable."""
    if not isinstance(raw, str):
        return None
    try:
        data = json.loads(_strip_fences(raw))
    except (ValueError, TypeError):
        return None
    if not isinstance(data, dict):
        return None
    verdicts = data.get("verdicts")
    if not isinstance(verdicts, dict) or not verdicts:
        return None
    parsed: dict[str, bool] = {}
    for key, value in verdicts.items():
        if isinstance(value, bool):
            parsed[str(key)] = value
    return parsed or None


def _strip_fences(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```[a-zA-Z]*\n", "", stripped)
        stripped = re.sub(r"\n```\s*$", "", stripped)
    return stripped.strip()


def run_judge(
    goldens: list[dict],
    *,
    model: str | None = None,
    ai_call: Callable[[str, str], str] | None = None,
    status_resolver: Callable[..., object] | None = None,
    rng: random.Random | None = None,
) -> dict:
    """Judge every golden's transcript against every rubric clause. Keyless = skip."""
    config = _safe_config()
    resolved_model = model or judge_model(config)
    resolve_status = status_resolver or provider_status
    selected = resolve_status(resolved_model, probe=False)
    if not getattr(selected, "ready", False):
        return {"status": "skipped", "reason": "no unattended AI provider is ready"}

    rng = rng or random.Random()
    clauses = load_rubric_clauses()
    results = []
    for golden in goldens:
        order = list(clauses)
        rng.shuffle(order)
        prompt = build_judge_prompt({"turns": golden.get("turns") or [], "clause_order": order})
        try:
            generated = (ai_call or call_ai)(prompt, resolved_model)
            verdicts = parse_judge_response(generated)
        except AIProviderError:
            verdicts = None
        results.append({
            "golden_id": golden.get("golden_id"),
            "verdicts": verdicts,
            "failed_clauses": [c for c, ok in (verdicts or {}).items() if not ok],
        })
    return {"status": "ran", "model": resolved_model, "results": results}


# ---- Personas ----


def build_persona_prompt(persona: str, persona_description: str) -> str:
    """Pure builder: identity + behavior + the persona description -> a request
    for one full STRICT-JSON simulated session (both roles, one model call)."""
    identity = conversation.read_conversation_definition("prompt", "identity.md")
    behavior = conversation.read_conversation_definition("prompt", "behavior.md")
    return (
        f"## IDENTITY\n\n{identity}\n\n## BEHAVIOR\n\n{behavior}\n\n"
        f"## PERSONA (you will play BOTH roles)\n\n{persona_description}\n\n"
        "## TASK\n\nSimulate one full Lifehug chat session (aim for the target "
        f"~3 exchanges unless the persona ({persona}) calls for more) between this "
        "user persona and Lifehug, following every hard rule above. Return STRICT "
        "JSON only (no prose, no code fence):\n"
        '{"turns": [{"role": "lifehug"|"user", "text": "..."}, ...]}\n'
    )


def parse_persona_response(raw: object) -> list[dict] | None:
    if not isinstance(raw, str):
        return None
    try:
        data = json.loads(_strip_fences(raw))
    except (ValueError, TypeError):
        return None
    if not isinstance(data, dict):
        return None
    turns = data.get("turns")
    if not isinstance(turns, list) or not turns:
        return None
    cleaned = []
    for turn in turns:
        if isinstance(turn, dict) and turn.get("role") in ("user", "lifehug") and isinstance(turn.get("text"), str):
            cleaned.append({"role": turn["role"], "text": turn["text"]})
    return cleaned or None


def _has_question(text: str) -> bool:
    stripped = conversation_lints._strip_echoed_questions(text)  # noqa: SLF001
    return any(
        conversation_lints._is_question(s)  # noqa: SLF001
        for s in conversation_lints._split_sentences(stripped)  # noqa: SLF001
    )


def _check_deferral(turns: list[dict]) -> list[str]:
    """grief-fresh: the first lifehug reply after the loss is mentioned must be
    question-free (receipt with warmth, no exploration) — approximated here as
    the first lifehug turn overall, since the persona mentions the loss early."""
    lifehug_turns = [t for t in turns if t.get("role") == "lifehug"]
    if not lifehug_turns:
        return ["no lifehug turns generated"]
    first = lifehug_turns[0]
    if _has_question(first.get("text", "")):
        return ["deferral violated: the first reply to a fresh-grief mention asks a question"]
    return []


def _check_back_off(turns: list[dict]) -> list[str]:
    """ruminator: heuristic — a session that only ever deepens with more questions
    never demonstrates back-off. At least one lifehug turn, once 2+ exchanges have
    happened, must be question-free (a distancing lens or a topic door)."""
    lifehug_turns = [t for t in turns if t.get("role") == "lifehug"]
    if len(lifehug_turns) < 3:
        return []  # too short a session to expect a back-off turn yet
    later = lifehug_turns[2:]
    if all(_has_question(t.get("text", "")) for t in later):
        return ["back-off not observed: every later lifehug turn still asks a question"]
    return []


def _check_no_hard_stop(turns: list[dict]) -> list[str]:
    """enthusiast: the session must not be artificially cut short — the user
    keeps going, so the exchange count should exceed the ~3-exchange chat
    target rather than stopping right at it."""
    user_turns = [t for t in turns if t.get("role") == "user"]
    if len(user_turns) <= 3:
        return ["no-hard-stop not demonstrated: session ended at/under the chat target"]
    return []


_OBSERVATION_CHECKERS: dict[str, Callable[[list[dict]], list[str]]] = {
    "deferral": _check_deferral,
    "back_off": _check_back_off,
    "no_hard_stop": _check_no_hard_stop,
}


def run_persona(
    persona: str,
    *,
    model: str | None = None,
    ai_call: Callable[[str, str], str] | None = None,
    status_resolver: Callable[..., object] | None = None,
) -> dict:
    """Simulate + Layer-1-lint + (when named) observation-check one persona. Keyless = skip."""
    from conversation_delivery import conversation_model  # noqa: PLC0415

    config = _safe_config()
    resolved_model = model or conversation_model(config)
    resolve_status = status_resolver or provider_status
    selected = resolve_status(resolved_model, probe=False)
    if not getattr(selected, "ready", False):
        return {"status": "skipped", "reason": "no unattended AI provider is ready", "persona": persona}

    description = conversation.read_conversation_definition("evals", "personas", f"{persona}.md")
    prompt = build_persona_prompt(persona, description)
    try:
        generated = (ai_call or call_ai)(prompt, resolved_model)
        turns = parse_persona_response(generated)
    except AIProviderError:
        turns = None
    if turns is None:
        return {"status": "ran", "persona": persona, "model": resolved_model, "error": "malformed_generation"}

    lint_findings = conversation_lints.lint_transcript(turns)
    observation = NAMED_OBSERVATIONS.get(persona)
    observation_errors = _OBSERVATION_CHECKERS[observation](turns) if observation else []
    return {
        "status": "ran",
        "persona": persona,
        "model": resolved_model,
        "turns": turns,
        "lint_findings": lint_findings,
        "observation": observation,
        "observation_errors": observation_errors,
    }


# --------------------------------------------------------------------------
# --emit-tasks — the keyless idiom (mirrors arc_planner.emit_tasks)
# --------------------------------------------------------------------------


def emit_tasks(out_dir: Path | None = None) -> Path:
    """Write judge + persona agent-task prompts under state/agent_tasks/evals/.

    Every write goes through lifehug_core's vault-guarded helpers (v120
    runtime guard) — never a bare Path.write_text.
    """
    out_dir = out_dir if out_dir is not None else (AGENT_TASKS_DIR / "evals")
    out_dir.mkdir(parents=True, exist_ok=True)

    items = []
    clauses = load_rubric_clauses()
    for golden in load_goldens():
        golden_id = golden.get("golden_id", "unknown")
        order = list(clauses)
        random.Random(golden_id).shuffle(order)
        prompt = build_judge_prompt({"turns": golden.get("turns") or [], "clause_order": order})
        prompt_file = out_dir / f"judge.{golden_id}.prompt.md"
        write_text(prompt_file, prompt)
        items.append({"task": "judge", "golden_id": golden_id, "prompt": prompt_file.name,
                      "response": f"judge.{golden_id}.response.json"})

    for persona in PERSONAS:
        description = conversation.read_conversation_definition("evals", "personas", f"{persona}.md")
        prompt = build_persona_prompt(persona, description)
        prompt_file = out_dir / f"persona.{persona}.prompt.md"
        write_text(prompt_file, prompt)
        items.append({"task": "persona", "persona": persona, "prompt": prompt_file.name,
                      "response": f"persona.{persona}.response.json"})

    manifest = out_dir / "manifest.json"
    write_json(manifest, {
        "task": "conversation-evals",
        "emitted_at": now_utc(),
        "ingest_note": "Write strict JSON (per each prompt's OUTPUT section) to the "
                        "named *.response.json file next to its prompt; this harness "
                        "does not (yet) ingest agent-task responses automatically — "
                        "re-run conversation-evals with a configured provider for a "
                        "single live pass instead, or review responses by hand.",
        "items": items,
    })
    return manifest


# --------------------------------------------------------------------------
# Orchestrator + CLI
# --------------------------------------------------------------------------


def run(*, emit_tasks_flag: bool = False, seed: int | None = None) -> tuple[int, list[str]]:
    """Run every layer. Always exit 0 unless a deterministic (keyless) layer
    itself fails — model-backed layers only ever skip or report, never fail
    the exit code (contract: "never red without keys")."""
    report: list[str] = []
    ok = True

    # Layer 1 — sanity: the shared engine loads and classifies at all.
    lints_config = conversation_lints.load_lints_config()
    lint_ids = sorted(k[len("lint."):] for k, v in lints_config.items() if k.startswith("lint.") and v)
    report.append(f"Layer 1 (deterministic lints): {len(lint_ids)} lint ids active — {', '.join(lint_ids)}")

    # Layer 2 — router fixtures + scorer.
    fixtures = load_router_fixtures()
    fixture_errors = validate_router_fixtures(fixtures)
    if fixture_errors:
        ok = False
        report.append(f"Layer 2 (router fixtures): FAILED schema — {len(fixture_errors)} error(s)")
        for detail in fixture_errors:
            report.append(f"  ✗ {detail}")
    else:
        report.append(f"Layer 2 (router fixtures): {len(fixtures)} fixtures validated OK")

    det_predictions = deterministic_router_predictions(fixtures)
    det_errors = check_deterministic_safe_default(fixtures, det_predictions)
    if det_errors:
        ok = False
        report.append(f"Layer 2 (deterministic safe-default): FAILED — {len(det_errors)} regression(s)")
        for detail in det_errors:
            report.append(f"  ✗ {detail}")
    else:
        report.append("Layer 2 (deterministic safe-default): PASSED — safe-default recall proven "
                       "(informational only against router_gates.*; see module docstring)")

    sample_predictions = load_router_sample_predictions()
    gates = load_router_gates()
    sample_scores = score_predictions(fixtures, sample_predictions)
    gate_failures = check_router_gates(sample_scores, gates)
    if gate_failures:
        ok = False
        report.append("Layer 2 (scorer self-check, committed sample predictions): FAILED")
        for detail in gate_failures:
            report.append(f"  ✗ {detail}")
    else:
        report.append("Layer 2 (scorer self-check, committed sample predictions): PASSED all "
                       f"{sum(len(v) for v in gates.values())} configured router_gates.*")

    live_router = run_router_live(fixtures)
    if live_router["status"] == "skipped":
        report.append(f"Layer 2 (live router model): SKIPPED ({live_router['reason']})")
    else:
        failures = live_router["gate_failures"]
        if failures:
            ok = False
            report.append(f"Layer 2 (live router model, {live_router['model']}): FAILED")
            for detail in failures:
                report.append(f"  ✗ {detail}")
        else:
            report.append(f"Layer 2 (live router model, {live_router['model']}): PASSED all router_gates.*")

    # Layer 3 — golden-transcript properties.
    goldens = load_goldens()
    property_pass = 0
    for golden in goldens:
        errors = check_golden(golden)
        if errors:
            ok = False
            report.append(f"Layer 3 ({golden.get('golden_id', '?')}): FAILED — {len(errors)} error(s)")
            for detail in errors:
                report.append(f"  ✗ {detail}")
        else:
            property_pass += 1
    report.append(f"Layer 3 (golden transcripts): {property_pass}/{len(goldens)} goldens passed "
                   f"(schema + Layer-1 lints + declared properties)")
    covered = {p for g in goldens for _, t in _lifehug_turns(g)
               for p in ((t.get("annotations") or {}).get("properties") or [])}
    missing = PROPERTY_IDS - covered
    if missing:
        report.append(f"Layer 3 (property coverage): NOT exercised by any committed golden — {sorted(missing)}")
    else:
        report.append(f"Layer 3 (property coverage): all {len(PROPERTY_IDS)} properties exercised")

    # Layer 4 — judge + personas (model-backed, keyless = skip loudly).
    judge_result = run_judge(goldens)
    if judge_result["status"] == "skipped":
        report.append(f"Layer 4 (judge rubrics over {len(goldens)} goldens): SKIPPED ({judge_result['reason']})")
    else:
        failed = sum(1 for r in judge_result["results"] if r["failed_clauses"])
        report.append(f"Layer 4 (judge rubrics, {judge_result['model']}): ran over {len(goldens)} "
                       f"goldens, {failed} with at least one failed clause")

    persona_skipped = 0
    persona_ran = 0
    for persona in PERSONAS:
        result = run_persona(persona)
        if result["status"] == "skipped":
            persona_skipped += 1
        else:
            persona_ran += 1
    if persona_ran == 0:
        report.append(f"Layer 4 (personas, {len(PERSONAS)} total): SKIPPED (no unattended AI provider is ready)")
    else:
        report.append(f"Layer 4 (personas): {persona_ran} ran, {persona_skipped} skipped")

    if emit_tasks_flag:
        manifest = emit_tasks()
        report.append(f"✓ Emitted judge/persona agent tasks — manifest: {manifest}")

    report.append(f"SUMMARY: {'PASSED' if ok else 'FAILED'} (deterministic layers 1-3; "
                   "model-backed layer 4 reported above, never failing the exit code)")
    return (0 if ok else 1), report


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run the Conversation Interaction eval harness (issue #120)."
    )
    parser.add_argument(
        "--emit-tasks", action="store_true",
        help="Also write judge/persona agent-task prompts to state/agent_tasks/evals/",
    )
    args = parser.parse_args()
    code, report = run(emit_tasks_flag=args.emit_tasks)
    for line in report:
        print(line)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
