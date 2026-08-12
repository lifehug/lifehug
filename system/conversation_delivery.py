#!/usr/bin/env python3
"""Lifehug — the conversation turn engine (issue #116, Wave 2 PR 3).

The post-answer moment used to be two disconnected messages: a warm
acknowledgment that is contractually forbidden from asking anything
(``answer_ack.py``) followed by a rotation-picked follow-up question that is
usually unrelated to what the user just said. This module makes that moment
ONE conversation turn: a single message that receives the answer, pays it
out, and cues the next question — and it degrades to exactly today's
behavior on any definitive failure.

This module is ORCHESTRATION only:

* prompts come from ``conversation.build_turn_prompt`` /
  ``conversation.build_closing_prompt`` (issue #115) — never assembled here;
* the behavior authority is ``interactions/conversation/`` — never restated
  in code;
* the deterministic lints come from ``conversation_lints`` (issue #115),
  whose config authority is ``interactions/conversation/evals/lints.yaml`` —
  never forked into constants here (recurring-defect doctrine);
* provider calls go through ``ai_provider.call_ai``; sends through
  ``lifehug_core.send_telegram_result``;
* session documents are touched ONLY through ``conversation``'s CRUD.

State (``state/conversation_deliveries.json``) and diagnostics carry
METADATA ONLY — session ids, turn indices, question ids, fixed reason codes,
lint ids, timestamps, attempt counts. Never an answer, a prompt, or
generated text. Same file shape and same exactly-once state machine as
``answer_ack_delivery`` (``{"version": 1, "entries": {...}}``): a confirmed
entry replays as a no-op, and an ambiguous entry is NEVER auto-retried.

Fallback guarantee (design §12 risk 1, binding): when the turn is skipped
for provider readiness or fails (provider error, unparseable/lint-rejected
generation, definitive send rejection), the same invocation degrades to
today's behavior — ``acknowledge_answer(...)`` then
``maybe_send_followup_question(...)``. Never silence, never worse than
today. The ONE exception is an ambiguous turn send: the turn may have
reached Telegram, so a fallback ack would risk a duplicate voice — it is
ledgered and surfaced, and nothing else is sent.
"""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable

import conversation
import conversation_lints
from ai_provider import (
    AIConfigurationError,
    AIProviderError,
    AIResponseError,
    AIUnavailableError,
    call_ai,
    provider_status,
)
from lifehug_core import (
    ANSWER_SCORES_FILE,
    CONVERSATION_DELIVERIES_FILE,
    TelegramSendResult,
    load_config,
    now_utc,
    read_json,
    record_learning_failure,
    send_telegram_result,
    write_json,
)

DELIVERY_STATE_FILE = CONVERSATION_DELIVERIES_FILE

#: Vault root for this module's session writes. ``None`` means "the
#: process-bound vault" (``conversation``'s own default). It is a module
#: attribute rather than a call-time-only argument so that a caller which
#: cannot thread arguments through — ``process_answer.run_post_answer_delivery``
#: and its tests — can still point the engine at a synthetic vault.
VAULT_ROOT: str | Path | None = None

#: Seated turn/closing model. Sonnet-class, same default-constant style as
#: answer_ack_delivery.DEFAULT_ACK_MODEL.
DEFAULT_CONVERSATION_MODEL = "claude-sonnet-5"
#: Cheap intent router (haiku-class). Key shipped here so the config surface
#: lands once; its consumer is Wave-2 PR 4 (`lifehug.py route`).
DEFAULT_ROUTER_MODEL = "claude-haiku-4-5"

STATUS_CONFIRMED = "confirmed"
STATUS_SKIPPED = "skipped"
STATUS_FAILED = "failed"
STATUS_AMBIGUOUS = "ambiguous"

#: Skip reasons that still degrade to today's behavior. Every other skip
#: reason means another writer is already handling this moment (single
#: flight) — sending an ack there would duplicate the voice.
FALLBACK_SKIP_REASONS = frozenset({"no_unattended_provider", "provider_unavailable"})

#: The lint ids that BLOCK a send at runtime (contract, "Runtime lints"):
#: one-question, banned phrases, length cap. Every other lint the shared
#: engine reports (question grammar, year questions, receipt-before-question)
#: is advisory — counted in the ledger, never a send-blocker, because a
#: false positive there would silently downgrade a good turn to the ack.
RUNTIME_BLOCKING_LINTS = ("one_question_per_turn", "banned_phrases", "length_caps")

#: Prompt-echo markers — the same class of structural check as
#: answer_ack_delivery._valid_completion, adapted to this prompt's blocks.
_ECHO_MARKERS = (
    "## turn_instructions",
    "## identity",
    "## behavior",
    "hard length cap for this message",
    "lifehug — closing takeaway",
)

_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE)
_SESSION_TS_RE = re.compile(r"^conv-(\d{8})-(\d{6})-[0-9a-f]{6}$")
#: A14 -> A14, A14b -> A14 (the suffix chain's root).
_CHAIN_ROOT_RE = re.compile(r"^([A-Z]\d+)[a-z]*$")


class TurnEngineError(Exception):
    """Base error for turn-engine operations (never raised into capture)."""


@dataclass(frozen=True)
class TurnOutcome:
    """Metadata-only result of one turn attempt."""

    session_id: str
    turn_index: int
    status: str
    reason: str
    attempted: bool
    fallback_used: bool = False
    followup_id: str | None = None
    question_free: bool = True
    lint_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class TurnShape:
    """The engine's deterministic turn-shape decision for this exchange."""

    position: str
    question_allowed: bool
    user_turns: int
    target_exchanges: int


# --------------------------------------------------------------------------
# Clock (module-level hook so timeout tests never sleep — jobs.py precedent)
# --------------------------------------------------------------------------


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_ts(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip().replace("Z", "+00:00")
    try:
        moment = datetime.fromisoformat(text)
    except ValueError:
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def _session_opened_at(session_id: str) -> datetime | None:
    """Zero-turn sessions have no turn timestamps — the id carries the UTC clock."""
    match = _SESSION_TS_RE.match(session_id or "")
    if not match:
        return None
    try:
        return datetime.strptime(
            f"{match.group(1)}{match.group(2)}", "%Y%m%d%H%M%S"
        ).replace(tzinfo=timezone.utc)
    except ValueError:
        return None


# --------------------------------------------------------------------------
# Ledger — same shape and state machine as state/answer_acknowledgments.json
# --------------------------------------------------------------------------


def _state(path: Path) -> dict:
    data = read_json(path, default={}) or {}
    if not isinstance(data, dict) or not isinstance(data.get("entries", {}), dict):
        return {"version": 1, "entries": {}}
    data.setdefault("version", 1)
    data.setdefault("entries", {})
    return data


def turn_key(session_id: str, turn_index: int) -> str:
    return f"turn:{session_id}:{turn_index}"


def close_key(session_id: str) -> str:
    return f"close:{session_id}"


def _write_outcome(
    path: Path,
    key: str,
    *,
    session_id: str,
    turn_index: int,
    question_id: str,
    status: str,
    reason: str,
    attempts: int,
    lint_ids: tuple[str, ...] | list[str] = (),
    advisory_lints: int = 0,
) -> None:
    data = _state(path)
    entry = {
        "session_id": session_id,
        "turn_index": turn_index,
        "question_id": question_id,
        "status": status,
        "reason": reason,
        "attempts": attempts,
        "updated_at": now_utc(),
    }
    if lint_ids:
        entry["lint_ids"] = sorted(set(lint_ids))
    if advisory_lints:
        entry["advisory_lints"] = advisory_lints
    if status == STATUS_CONFIRMED:
        entry["confirmed_at"] = entry["updated_at"]
    if status == STATUS_AMBIGUOUS:
        entry["operator_action"] = "verify Telegram before retrying"
    data["entries"][key] = entry
    write_json(path, data)


def _fixed_provider_reason(exc: BaseException) -> str:
    if isinstance(exc, AIConfigurationError):
        return "provider_configuration_error"
    if isinstance(exc, AIResponseError):
        return "provider_malformed_response"
    if isinstance(exc, AIUnavailableError):
        return "provider_unavailable"
    return "generation_failed"


def _diagnostic(operation: str, reason: str, session_id: str) -> None:
    """Fixed metadata only — never exception text, never model text."""
    record_learning_failure(
        "conversation_delivery",
        operation,
        reason,
        context={"session_id": session_id},
    )


# --------------------------------------------------------------------------
# Generation contract: parsing + linting
# --------------------------------------------------------------------------


def _output_contract_block(shape: TurnShape) -> str:
    """The engine's structured-output appendix to the Wave-1 turn prompt.

    The merged Wave-1 builder assembles behavior + context + filled turn
    instructions; it does not (and should not) pin a machine-readable output
    shape, because the same definition files also drive the keyless
    host-agent path where a human-readable message is the whole product.
    The ENGINE needs structure (the proposed follow-up text, the
    question-free flag, and the extraction deltas), so it appends this
    orchestration-owned block last — after the turn instructions, which the
    manifest requires to be the final behavior block.
    """
    if shape.question_allowed:
        question_rule = (
            "Ask AT MOST ONE question, and it must be a cued invitation that "
            "quotes the user's own phrase. Put that same question's text in "
            "\"followup_question\"."
        )
    elif shape.position == "third_exchange_exit_friendly":
        question_rule = (
            "Ask NO question. This is the exit-friendly turn: make stopping "
            "here feel like a good place to rest. Set \"followup_question\" "
            "to null and \"question_free\" to true."
        )
    else:
        question_rule = (
            "Ask NO question — keep receiving. Set \"followup_question\" to "
            "null and \"question_free\" to true."
        )
    return (
        "\n\n## OUTPUT FORMAT (runtime contract — reply with JSON only)\n\n"
        "Reply with a single JSON object and nothing else:\n\n"
        "{\n"
        '  "message": "the one Telegram message, plain text",\n'
        '  "followup_question": "the question you asked, verbatim, or null",\n'
        '  "question_free": true | false,\n'
        '  "rolling_summary": "a short running summary of this session",\n'
        '  "insight_receipts": 0,\n'
        '  "extracted": {"facts": [], "entities": [], "candidate_ideas": [], '
        '"mirror_responses": []}\n'
        "}\n\n"
        f"- {question_rule}\n"
        '- "insight_receipts" counts the contributions in this message that '
        "cite a provenance id from the record block.\n"
        "- Everything in \"message\" is sent to the user verbatim; nothing else is.\n"
    )


def _strip_fences(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = _FENCE_RE.sub("", stripped).strip()
    return stripped


def _valid_message(raw: object) -> str | None:
    """Structural sanity, same class as answer_ack_delivery._valid_completion."""
    if not isinstance(raw, str):
        return None
    message = raw.strip()
    if not message or "\x00" in message:
        return None
    if message.startswith(("```", "{", "[")):
        return None
    lowered = message.lower()
    if any(marker in lowered for marker in _ECHO_MARKERS):
        return None
    return message


def parse_turn_output(raw: object) -> dict | None:
    """Parse the structured turn output; None when it is unusable.

    Tolerates a ```json fence around the object (a common provider habit)
    but nothing looser — a turn we cannot read is a malformed generation,
    and malformed generations fall back rather than guess.
    """
    if not isinstance(raw, str):
        return None
    try:
        data = json.loads(_strip_fences(raw))
    except (ValueError, TypeError):
        return None
    if not isinstance(data, dict):
        return None
    message = _valid_message(data.get("message"))
    if message is None:
        return None
    followup = data.get("followup_question")
    followup_text = followup.strip() if isinstance(followup, str) else ""
    extracted = data.get("extracted")
    summary = data.get("rolling_summary")
    receipts = data.get("insight_receipts")
    return {
        "message": message,
        "followup_question": followup_text or None,
        "question_free": bool(data.get("question_free", not followup_text)),
        "rolling_summary": summary.strip() if isinstance(summary, str) else None,
        "insight_receipts": int(receipts) if isinstance(receipts, int) else 0,
        "extracted": extracted if isinstance(extracted, dict) else {},
    }


def _question_sentences(text: str) -> list[str]:
    """Question sentences per the shared lint engine's own heuristics.

    Imported from conversation_lints rather than re-implemented: the
    echoed-question stripping rule (a quoted span containing '?' is the
    USER's question, not ours) is exactly the subtlety a forked copy would
    get wrong.
    """
    stripped = conversation_lints._strip_echoed_questions(text)
    return [s for s in conversation_lints._split_sentences(stripped) if conversation_lints._is_question(s)]


def lint_outgoing(
    message: str,
    *,
    question_allowed: bool,
    is_reply_to_substantive: bool = True,
    config: dict | None = None,
) -> tuple[list[str], int]:
    """Return (blocking lint ids, advisory finding count) for one message.

    The checks themselves live in ``conversation_lints`` (single authority,
    config from ``evals/lints.yaml`` — including the ``cap.turn_chars``
    length cap, which this module deliberately does NOT pin independently).
    """
    findings = conversation_lints.lint_turn(
        message, is_reply_to_substantive=is_reply_to_substantive, config=config
    )
    blocking = [f["lint"] for f in findings if f.get("lint") in RUNTIME_BLOCKING_LINTS]
    advisory = len(findings) - len(blocking)
    if not question_allowed and _question_sentences(message):
        # The engine's own deterministic enforcement: a question-free turn
        # that asks anyway would spend initiative the gates already spent.
        blocking.append("question_not_permitted")
    return blocking, advisory


# --------------------------------------------------------------------------
# Turn shape
# --------------------------------------------------------------------------


def _manifest() -> dict:
    try:
        return conversation.load_interaction_manifest()
    except (OSError, ValueError):
        return {}


def _knob(manifest: dict, key: str, default: int) -> int:
    value = manifest.get(key)
    return value if isinstance(value, int) else default


def _count_user_turns(session: dict) -> int:
    return sum(1 for turn in (session.get("turns") or []) if turn.get("role") == "user")


def decide_turn_shape(
    session: dict,
    *,
    manifest: dict,
    planned_question: object | None,
) -> TurnShape:
    """Deterministic turn shape from session state + the cadence gates.

    Exchange 1..target-1 carry our initiative (a cued follow-up). The
    target-th exchange is the exit-friendly door: it receives and pays out
    but asks nothing, so stopping there reads as "a good place to rest"
    rather than a dropped question. Past the target we keep receiving for as
    long as the user keeps going — the target governs OUR initiative only,
    never the user's.

    When ``plan_adaptive_followup`` returned None (curfew, 3/day cap, pass
    transition, cadence off), the gates transfer to the turn: the turn is
    question-free. The gates move, they do not disappear.
    """
    user_turns = _count_user_turns(session)
    target = _knob(manifest, "knob.chat_target_exchanges", 3)
    if user_turns <= 1:
        position = "opening"
    elif user_turns < target:
        position = "mid_arc"
    elif user_turns == target:
        position = "third_exchange_exit_friendly"
    else:
        position = "past_target"
    question_allowed = planned_question is not None and user_turns < target
    return TurnShape(position, question_allowed, user_turns, target)


# --------------------------------------------------------------------------
# Session selection
# --------------------------------------------------------------------------


def _chain_root(question_id: str) -> str:
    match = _CHAIN_ROOT_RE.match(question_id or "")
    return match.group(1) if match else (question_id or "")


def _session_question_ids(session: dict) -> set[str]:
    ids = set()
    arc = session.get("arc") or {}
    if isinstance(arc, dict) and arc.get("question_id"):
        ids.add(str(arc["question_id"]))
    for turn in session.get("turns") or []:
        if turn.get("question_id"):
            ids.add(str(turn["question_id"]))
    pending = session.get("pending_question_id")
    if pending:
        ids.add(str(pending))
    return ids


def find_open_session_for_question(
    question_id: str,
    *,
    vault_root: str | Path | None = None,
) -> dict | None:
    """The open chat session whose question chain contains ``question_id``."""
    root = _chain_root(question_id)
    newest = None
    for summary in conversation.list_sessions(status="open", vault_root=vault_root):
        session_id = summary.get("session_id")
        if not session_id:
            continue
        try:
            doc = conversation.load_session(session_id, vault_root=vault_root)
        except (OSError, ValueError):
            continue
        if any(_chain_root(qid) == root for qid in _session_question_ids(doc)):
            newest = doc if newest is None else newest
    return newest


def find_open_session_for_channel(
    channel: str,
    *,
    mode: str | None = None,
    vault_root: str | Path | None = None,
    manifest: dict | None = None,
    now: datetime | None = None,
) -> dict | None:
    """The newest open, non-idle-expired session for this channel.

    Shared by the router (any mode — "any open non-expired session from the
    store", contract #117 Part B) and the story-turn entry point (mode
    "conversation" only — a story continues a conversation, never a chat).
    """
    manifest = manifest if manifest is not None else _manifest()
    reference = now or _now()
    newest = None
    for summary in conversation.list_sessions(status="open", vault_root=vault_root):
        if summary.get("channel") != channel:
            continue
        if mode is not None and summary.get("mode") != mode:
            continue
        session_id = summary.get("session_id")
        if not session_id:
            continue
        try:
            doc = conversation.load_session(session_id, vault_root=vault_root)
        except (OSError, ValueError):
            continue
        if is_idle_expired(doc, manifest=manifest, now=reference):
            continue
        if newest is None or str(session_id) > str(newest["session_id"]):
            newest = doc
    return newest


def _append_turn_resilient(
    session_id: str,
    turn: dict,
    *,
    expected_turns: int,
    vault_root: str | Path | None = None,
    attempts: int = 3,
) -> dict:
    """CAS-append, re-reading the count on conflict.

    Used ONLY after a confirmed send: at that point the message exists in
    the user's Telegram, so losing the record to a concurrent writer would
    be worse than replaying the compare-and-set against the fresh count.
    The pre-generation user-turn append deliberately does NOT use this — a
    conflict there is the single-flight signal.
    """
    count = expected_turns
    last: Exception | None = None
    for _ in range(max(1, attempts)):
        try:
            return conversation.append_turn(
                session_id, turn, expected_turns=count, vault_root=vault_root
            )
        except conversation.TurnConflictError as exc:
            last = exc
            fresh = conversation.load_session(session_id, vault_root=vault_root)
            count = len(fresh.get("turns") or [])
    raise last if last else TurnEngineError("append failed")


def _locate_user_turn(session: dict, question_id: str, answer_text: str) -> int | None:
    """Index of an already-recorded user turn for this exact answer, if any.

    Replay detection: ``run_post_answer_turn`` is called from the durable
    side of ``process-answer``, so a re-run of the same answer must not
    append a second user turn (and must not send a second message). The
    ledger still owns exactly-once for the SEND; this owns exactly-once for
    the session document.
    """
    text = (answer_text or "").strip()
    for index, turn in enumerate(session.get("turns") or []):
        if turn.get("role") != "user":
            continue
        if str(turn.get("question_id") or "") != question_id:
            continue
        if (turn.get("text") or "").strip() == text:
            return index
    return None


def _resolve_model(config: dict, key: str, default: str) -> str:
    return str(config.get(key) or default)


def _safe_config() -> dict:
    try:
        cfg = load_config()
    except Exception:  # noqa: BLE001 — a malformed local config never risks capture
        return {}
    return cfg if isinstance(cfg, dict) else {}


def arc_plan_model(config: dict | None = None) -> str:
    """arc_plan_model -> classify_model -> classify_story.DEFAULT_MODEL.

    Shipped here so the key set lands once (contract, "New config keys");
    the consumer is Wave-2 PR 5. The terminal fallback is imported from the
    classification authority rather than re-pinned as a literal.
    """
    cfg = config if isinstance(config, dict) else _safe_config()
    from classify_story import DEFAULT_MODEL  # noqa: PLC0415

    return str(cfg.get("arc_plan_model") or cfg.get("classify_model") or DEFAULT_MODEL)


def router_model(config: dict | None = None) -> str:
    cfg = config if isinstance(config, dict) else _safe_config()
    return _resolve_model(cfg, "router_model", DEFAULT_ROUTER_MODEL)


def conversation_model(config: dict | None = None) -> str:
    cfg = config if isinstance(config, dict) else _safe_config()
    return _resolve_model(cfg, "conversation_model", DEFAULT_CONVERSATION_MODEL)


# --------------------------------------------------------------------------
# Part B — the router (issue #117): classify one inbound message.
#
# `interactions/conversation/router/router.md` is the single definition both
# runtimes execute; this function is the OSS side of it. Read-only: it never
# writes rotation, session, or candidate state (contract, "route mutates
# nothing durable" — READ_ONLY_COMMANDS in lifehug.py).
# --------------------------------------------------------------------------

VALID_ROUTER_INTENTS = frozenset(
    {"answer", "new_story", "command", "continue_session", "out_of_scope"}
)

#: Fixed intent -> action mapping (contract, Part B mechanics #4).
#: "ask_user" is never in this table — it only ever comes from the
#: safe-default rule below, not from a classified intent.
_ROUTER_ACTION_BY_INTENT = {
    "answer": "file_answer",
    "new_story": "ingest_story",
    "command": "handle_command",
    "continue_session": "continue_session",
    "out_of_scope": "deflect",
}


def _parse_router_output(raw: object) -> tuple[str, float] | None:
    """Parse router.md's ``{"intent": ..., "confidence": ...}`` schema.

    None on anything unusable — malformed output is the "treat as
    unavailable" path (contract, Part B mechanics #2), never a guess.
    """
    if not isinstance(raw, str):
        return None
    try:
        data = json.loads(_strip_fences(raw))
    except (ValueError, TypeError):
        return None
    if not isinstance(data, dict):
        return None
    intent = data.get("intent")
    if intent not in VALID_ROUTER_INTENTS:
        return None
    confidence = data.get("confidence")
    if isinstance(confidence, bool) or not isinstance(confidence, (int, float)):
        return None
    confidence = float(confidence)
    if not (0.0 <= confidence <= 1.0):
        return None
    return intent, confidence


def route_message(
    text: str,
    *,
    channel: str = "cli",
    vault_root: str | Path | None = None,
    ai_call: Callable[[str, str], str] | None = None,
    status_resolver: Callable[..., object] | None = None,
    prompt_builder: Callable[[dict], str] | None = None,
    rotation: dict | None = None,
    open_session: dict | None = None,
    now: datetime | None = None,
) -> dict:
    """Classify one inbound message per router.md; never mutates anything.

    Returns ``{"intent", "confidence", "source", "action",
    "pending_question_id", "open_session_id"}`` — always, and always with
    exit-0 semantics for the CLI wrapper (``cmd_route`` in ``lifehug.py``):
    a provider that is not ready, a malformed model reply, or a
    below-threshold classification all resolve through the deterministic
    default rule below rather than raising.

    Injectable collaborators (``ai_call`` / ``status_resolver`` /
    ``prompt_builder`` / ``rotation`` / ``open_session``) mirror the turn
    engine's own testing seam.
    """
    vault_root = vault_root if vault_root is not None else VAULT_ROOT
    manifest = _manifest()
    threshold = manifest.get("knob.router_confidence_threshold")
    threshold = float(threshold) if isinstance(threshold, (int, float)) else 0.7

    if rotation is None:
        from lifehug_core import ROTATION_FILE  # noqa: PLC0415

        rotation = read_json(ROTATION_FILE, default={}) or {}
    pending_question_id = rotation.get("last_question_id") or None

    if open_session is None:
        open_session = find_open_session_for_channel(
            channel, vault_root=vault_root, manifest=manifest, now=now
        )
    open_session_id = str(open_session["session_id"]) if open_session else None

    config = _safe_config()
    model = router_model(config)
    resolve_status = status_resolver or provider_status
    selected = resolve_status(model, probe=False)

    model_intent: str | None = None
    model_confidence: float | None = None
    if getattr(selected, "ready", False):
        builder = prompt_builder or conversation.build_router_prompt
        payload = {
            "message": text,
            "session_open": open_session_id is not None,
            "pending_question_id": pending_question_id,
        }
        try:
            prompt = builder(payload)
            generated = (ai_call or call_ai)(prompt, model)
            parsed = _parse_router_output(generated)
        except Exception:  # noqa: BLE001 — a classify call is never capture
            parsed = None
        if parsed is None:
            _diagnostic("route_classify", "malformed_generation", open_session_id or "-")
        else:
            model_intent, model_confidence = parsed

    if model_intent is not None and model_confidence is not None and model_confidence >= threshold:
        intent = model_intent
        confidence = model_confidence
        source = "model"
        action = _ROUTER_ACTION_BY_INTENT[intent]
    else:
        source = "default"
        confidence = model_confidence if model_confidence is not None else 0.0
        if pending_question_id:
            intent = "answer"
            action = _ROUTER_ACTION_BY_INTENT[intent]
        elif open_session_id:
            intent = "continue_session"
            action = _ROUTER_ACTION_BY_INTENT[intent]
        else:
            # Terminal, per-runtime unsure-fallback (router.md step 3, OSS
            # side): report the model's best guess when there was one, else
            # new_story — either way, ask rather than guess.
            intent = model_intent if model_intent is not None else "new_story"
            action = "ask_user"

    return {
        "intent": intent,
        "confidence": round(float(confidence), 4),
        "source": source,
        "action": action,
        "pending_question_id": pending_question_id,
        "open_session_id": open_session_id,
    }


def _default_fallback(
    *,
    source_id: str,
    question_id: str,
    question_text: str,
    question_category: str,
    answer_text: str,
    planned_question: object | None,
) -> None:
    """Today's exact behavior: the warm ack, then the separate follow-up.

    Both steps swallow their own failures — this path exists precisely
    because something already went wrong, and answer durability always wins.
    """
    try:
        from answer_ack_delivery import acknowledge_answer  # noqa: PLC0415

        outcome = acknowledge_answer(
            source_id=source_id,
            question_id=question_id,
            question_text=question_text,
            question_category=question_category,
            answer_text=answer_text,
            followup_pending=planned_question is not None,
        )
        print(
            f"✓ Answer acknowledgment (turn fallback): {outcome.status} "
            f"({outcome.reason}; {source_id})"
        )
    except Exception:  # noqa: BLE001
        _diagnostic("fallback_acknowledgment", "internal_error", source_id)
    try:
        from process_answer import maybe_send_followup_question  # noqa: PLC0415

        maybe_send_followup_question(question_id, planned_question)
    except Exception:  # noqa: BLE001
        _diagnostic("fallback_followup", "internal_error", source_id)


def run_post_answer_turn(
    *,
    source_id: str,
    question_id: str,
    question_text: str,
    question_category: str,
    answer_text: str,
    planned_question: object | None = None,
    state_path: Path | None = None,
    vault_root: str | Path | None = None,
    channel: str = "telegram",
    pinned_session_id: str | None = None,
    allow_ambiguous_retry: bool = False,
    sweep: bool = True,
    ai_call: Callable[[str, str], str] | None = None,
    telegram_send: Callable[[str], TelegramSendResult] | None = None,
    status_resolver: Callable[..., object] | None = None,
    prompt_builder: Callable[[dict], str] | None = None,
    followup_minter: Callable[[str, list[str]], list[tuple[str, str]]] | None = None,
    rotation_updater: Callable[[str], None] | None = None,
    fallback: Callable[..., None] | None = None,
) -> TurnOutcome:
    """Run ONE conversation turn for a durable answer, or degrade to today.

    Called from ``process_answer.run_post_answer_delivery`` in place of the
    acknowledgment + separate-follow-up pair. Every failure mode either
    sends the fallback pair or (ambiguous only) stops after ledgering —
    nothing here can raise into the caller's durability path.
    """
    state_path = state_path if state_path is not None else DELIVERY_STATE_FILE
    vault_root = vault_root if vault_root is not None else VAULT_ROOT
    manifest = _manifest()
    if sweep:
        try:
            close_expired_sessions(
                vault_root=vault_root,
                state_path=state_path,
                ai_call=ai_call,
                telegram_send=telegram_send,
                status_resolver=status_resolver,
            )
        except Exception:  # noqa: BLE001 — a stuck sweep never blocks this turn
            _diagnostic("idle_sweep", "sweep_failed", source_id)

    if pinned_session_id:
        session = conversation.load_session(pinned_session_id, vault_root=vault_root)
    else:
        session = find_open_session_for_question(question_id, vault_root=vault_root)
    if session is None:
        # A chat session opens at the FIRST ANSWER, not at delivery: an arc
        # card waiting with a delivered question burns no idle clock.
        session = conversation.open_session("chat", channel, vault_root=vault_root)
    session_id = str(session["session_id"])

    existing_index = _locate_user_turn(session, question_id, answer_text)
    if existing_index is None:
        user_turn = {
            "role": "user",
            "text": answer_text,
            "channel": channel,
            "question_id": question_id,
        }
        try:
            session = conversation.append_turn(
                session_id,
                user_turn,
                expected_turns=len(session.get("turns") or []),
                vault_root=vault_root,
            )
        except (conversation.TurnConflictError, conversation.SessionClosedError):
            # Single flight: a concurrent entry for this session already
            # minted the turn. The loser sends nothing — no turn, and no
            # fallback ack either (the winner's message is the voice).
            return TurnOutcome(session_id, -1, STATUS_SKIPPED, "turn_already_minted", False)
        existing_index = len(session.get("turns") or []) - 1

    turn_index = existing_index + 1
    key = turn_key(session_id, turn_index)
    entries = _state(state_path)["entries"]
    previous = entries.get(key, {})
    previous_status = previous.get("status")
    if previous_status == STATUS_CONFIRMED:
        return TurnOutcome(session_id, turn_index, STATUS_CONFIRMED, "already_confirmed", False)
    if previous_status == STATUS_AMBIGUOUS and not allow_ambiguous_retry:
        return TurnOutcome(session_id, turn_index, STATUS_AMBIGUOUS, "ambiguous_not_retried", False)
    attempts = int(previous.get("attempts", 0) or 0) + 1

    fallback_call = fallback or _default_fallback

    def _degrade(status: str, reason: str, *, lint_ids: tuple[str, ...] = ()) -> TurnOutcome:
        _write_outcome(
            state_path,
            key,
            session_id=session_id,
            turn_index=turn_index,
            question_id=question_id,
            status=status,
            reason=reason,
            attempts=attempts,
            lint_ids=lint_ids,
        )
        degrades = status == STATUS_FAILED or reason in FALLBACK_SKIP_REASONS
        if degrades:
            fallback_call(
                source_id=source_id,
                question_id=question_id,
                question_text=question_text,
                question_category=question_category,
                answer_text=answer_text,
                planned_question=planned_question,
            )
        return TurnOutcome(
            session_id, turn_index, status, reason, True, fallback_used=degrades, lint_ids=lint_ids
        )

    config = _safe_config()
    model = conversation_model(config)
    resolve_status = status_resolver or provider_status
    selected = resolve_status(model, probe=False)
    if not getattr(selected, "ready", False):
        reason = (
            "no_unattended_provider"
            if getattr(selected, "provider", "") == "agent-task"
            else "provider_unavailable"
        )
        return _degrade(STATUS_SKIPPED, reason)

    shape = decide_turn_shape(session, manifest=manifest, planned_question=planned_question)
    builder = prompt_builder or conversation.build_turn_prompt
    try:
        prompt = builder({"session": session}) + _output_contract_block(shape)
        generated = (ai_call or call_ai)(prompt, model)
    except AIProviderError as exc:
        reason = _fixed_provider_reason(exc)
        _diagnostic("generation", reason, session_id)
        return _degrade(STATUS_FAILED, reason)
    except Exception:  # noqa: BLE001 — answer durability always wins
        _diagnostic("generation", "generation_failed", session_id)
        return _degrade(STATUS_FAILED, "generation_failed")

    parsed = parse_turn_output(generated)
    if parsed is None:
        _diagnostic("generation", "malformed_generation", session_id)
        return _degrade(STATUS_FAILED, "malformed_generation")

    message = parsed["message"]
    question_allowed = shape.question_allowed and not parsed["question_free"]
    blocking, advisory = lint_outgoing(
        message,
        question_allowed=question_allowed,
        config=_lints_config(),
    )
    if blocking:
        _diagnostic("lint", "malformed_generation", session_id)
        return _degrade(STATUS_FAILED, "malformed_generation", lint_ids=tuple(blocking))

    # Conservative replay position BEFORE the external effect.
    _write_outcome(
        state_path,
        key,
        session_id=session_id,
        turn_index=turn_index,
        question_id=question_id,
        status=STATUS_AMBIGUOUS,
        reason="send_in_progress",
        attempts=attempts,
        advisory_lints=advisory,
    )
    send_result = (telegram_send or send_telegram_result)(message)
    if send_result.status == "confirmed":
        status, reason = STATUS_CONFIRMED, "telegram_confirmed"
    elif send_result.status == "ambiguous":
        status, reason = STATUS_AMBIGUOUS, send_result.reason
    elif send_result.status == "not_attempted":
        status, reason = STATUS_SKIPPED, send_result.reason
    else:
        status, reason = STATUS_FAILED, send_result.reason

    if status != STATUS_CONFIRMED:
        _write_outcome(
            state_path,
            key,
            session_id=session_id,
            turn_index=turn_index,
            question_id=question_id,
            status=status,
            reason=reason,
            attempts=attempts,
            advisory_lints=advisory,
        )
        _diagnostic("telegram_send", reason, session_id)
        if status == STATUS_AMBIGUOUS:
            # The turn may have reached Telegram. A fallback ack here would
            # risk a duplicate voice — ledger it and stop (contract exception).
            return TurnOutcome(session_id, turn_index, status, reason, True)
        fallback_call(
            source_id=source_id,
            question_id=question_id,
            question_text=question_text,
            question_category=question_category,
            answer_text=answer_text,
            planned_question=planned_question,
        )
        return TurnOutcome(session_id, turn_index, status, reason, True, fallback_used=True)

    followup_id = None
    if question_allowed and parsed["followup_question"]:
        followup_id = _mint_followup(
            question_id,
            parsed["followup_question"],
            minter=followup_minter,
            rotation_updater=rotation_updater,
            session_id=session_id,
        )

    lifehug_turn = {
        "role": "lifehug",
        "text": message,
        "channel": channel,
        "model": model,
        "question_id": followup_id or question_id,
    }
    try:
        _append_turn_resilient(
            session_id, lifehug_turn, expected_turns=turn_index, vault_root=vault_root
        )
        conversation.merge_session_extraction(
            session_id,
            rolling_summary=parsed["rolling_summary"],
            extracted=parsed["extracted"],
            vault_root=vault_root,
        )
    except Exception:  # noqa: BLE001 — the message is already delivered
        _diagnostic("session_record", "session_write_failed", session_id)

    _write_outcome(
        state_path,
        key,
        session_id=session_id,
        turn_index=turn_index,
        question_id=followup_id or question_id,
        status=STATUS_CONFIRMED,
        reason="telegram_confirmed",
        attempts=attempts,
        advisory_lints=advisory,
    )
    if parsed["insight_receipts"]:
        _record_insight_receipts(state_path, key, parsed["insight_receipts"])
    return TurnOutcome(
        session_id,
        turn_index,
        STATUS_CONFIRMED,
        "telegram_confirmed",
        True,
        followup_id=followup_id,
        question_free=followup_id is None,
    )


# --------------------------------------------------------------------------
# Part A — story -> Conversation (issue #117).
#
# An unprompted story opens or continues a "conversation"-mode session and
# gets ONE immediate turn through the SAME machinery as the answer-path
# engine above — never a copy. Story follow-ups are conversational only
# (they live in the message + session document); they are never bank-minted,
# so unlike ``run_post_answer_turn`` there is no ``followup_minter`` /
# ``rotation_updater`` seam here (contract, "Turn identity for story
# follow-ups").
# --------------------------------------------------------------------------


def _story_turn_shape(session: dict, *, manifest: dict) -> TurnShape:
    """Conversation-mode turn shape: the 25-exchange cap governs OUR
    initiative (``knob.conversation_turn_cap_exchanges``), not the 3-exchange
    chat cadence ``decide_turn_shape`` uses — mirrors ``conversation.py``'s
    own ``_turn_position`` cap logic for this mode. A cued follow-up
    invitation is allowed on every turn up to the cap; past it the engine
    keeps receiving without spending further initiative."""
    user_turns = _count_user_turns(session)
    cap = _knob(manifest, "knob.conversation_turn_cap_exchanges", 25)
    if user_turns <= 1:
        position = "opening"
    elif user_turns >= cap:
        position = "past_target"
    else:
        position = "mid_arc"
    return TurnShape(position, user_turns < cap, user_turns, cap)


def _story_context_block(source_type: str) -> str:
    """Mechanical source-type signal, appended like ``_output_contract_block``.

    Orchestration-owned: this only makes the fact of the source type
    (``unprompted_story`` / ``witness_account`` / ``opinion``) available at
    runtime so the register can match it (a witness account is another
    person's words; an opinion gets Socratic energy). Any actual per-type
    guidance lives in ``interactions/conversation/`` — if a definition file
    has no branch for it yet, the engine still runs (contract, Part A #6).
    """
    return f"\n\n## SOURCE TYPE\n\n{source_type}\n"


def _virtual_story_session(channel: str, story_text: str, source_path: str) -> dict:
    """An in-memory session shape (never persisted) for the prompt builder.

    Used only while deciding whether a BRAND NEW conversation session is
    worth opening at all: the contract's no-session fallback ("no session
    created" on a definitive generation/lint/send failure while opening) is
    honored by generating against this virtual document first and only
    calling ``conversation.open_session`` once generation + lint have
    cleared — an already-open session simply appends the real turn instead
    (below). The virtual document's ``session_id`` is a placeholder; nothing
    the prompt builders read depends on it.
    """
    return {
        "session_version": conversation.SESSION_VERSION,
        "session_id": "(pending)",
        "mode": "conversation",
        "channel": channel,
        "status": "open",
        "arc": None,
        "turns": [{
            "role": "user",
            "text": story_text,
            "channel": channel,
            "ts": now_utc(),
            "source_path": source_path,
        }],
        "rolling_summary": "",
        "extracted": {"facts": [], "entities": [], "candidate_ideas": [], "mirror_responses": []},
    }


def run_story_conversation_turn(
    *,
    source_id: str,
    source_path: str,
    title: str,
    story_text: str,
    source_type: str,
    channel: str,
    state_path: Path | None = None,
    vault_root: str | Path | None = None,
    ai_call: Callable[[str, str], str] | None = None,
    telegram_send: Callable[[str], TelegramSendResult] | None = None,
    status_resolver: Callable[..., object] | None = None,
    prompt_builder: Callable[[dict], str] | None = None,
) -> TurnOutcome:
    """Open/continue a Conversation for one unprompted story; ONE turn.

    Called from the ingest path AFTER durability (``register_source``),
    wrapped by the caller in the same try/except + ``record_learning_failure``
    posture as ``run_post_answer_turn``'s callers. Never raises here either.

    No-session fallback (contract, Part A #3): when the provider is not
    ready, or generation/lint fails while OPENING a brand new session, no
    session is created at all — today's checkmark + filed template
    candidates are already the complete, correct outcome. Continuing an
    already-open session behaves like the answer-path engine: the user's
    turn lands regardless, and only a failed generation means the session
    simply does not gain a lifehug reply.
    """
    state_path = state_path if state_path is not None else DELIVERY_STATE_FILE
    vault_root = vault_root if vault_root is not None else VAULT_ROOT
    manifest = _manifest()

    config = _safe_config()
    model = conversation_model(config)
    resolve_status = status_resolver or provider_status
    selected = resolve_status(model, probe=False)
    if not getattr(selected, "ready", False):
        reason = (
            "no_unattended_provider"
            if getattr(selected, "provider", "") == "agent-task"
            else "provider_unavailable"
        )
        # Never touches the session store — no session created (contract).
        return TurnOutcome("", -1, STATUS_SKIPPED, reason, False)

    existing = find_open_session_for_channel(
        channel, mode="conversation", vault_root=vault_root, manifest=manifest
    )
    opening = existing is None
    if opening:
        # Not persisted yet — see the no-session-on-failure guarantee below.
        session_id = ""
        session = _virtual_story_session(channel, story_text, source_path)
    else:
        session_id = str(existing["session_id"])
        user_turn = {
            "role": "user",
            "text": story_text,
            "channel": channel,
            "source_path": source_path,
        }
        # No replay-detection here (unlike the answer-path engine's
        # `_locate_user_turn`): every real story ingest names a fresh,
        # unique `source_path` (`unique_source_path`), so there is no
        # "the same answer re-filed" scenario to guard against — each call
        # appends the next turn in the conversation, by design.
        try:
            session = conversation.append_turn(
                session_id, user_turn, expected_turns=len(existing.get("turns") or []),
                vault_root=vault_root,
            )
        except (conversation.TurnConflictError, conversation.SessionClosedError):
            return TurnOutcome(session_id, -1, STATUS_SKIPPED, "turn_already_minted", False)

        turn_index = len(session.get("turns") or [])
        key = turn_key(session_id, turn_index)

    attempts = 1  # no retry seam feeds this a prior attempt count (contract, Scope)

    def _ledger(status: str, reason: str, lint_ids: tuple[str, ...] = ()) -> None:
        if opening:
            # Nothing has been persisted yet — a ledger entry keyed to a
            # session that was never opened would be orphaned metadata.
            return
        _write_outcome(
            state_path, key, session_id=session_id, turn_index=turn_index,
            question_id="", status=status, reason=reason, attempts=attempts,
            lint_ids=lint_ids,
        )

    shape = _story_turn_shape(session, manifest=manifest)
    builder = prompt_builder or conversation.build_turn_prompt
    try:
        prompt = (
            builder({"session": session})
            + _story_context_block(source_type)
            + _output_contract_block(shape)
        )
        generated = (ai_call or call_ai)(prompt, model)
    except AIProviderError as exc:
        reason = _fixed_provider_reason(exc)
        _ledger(STATUS_FAILED, reason)
        _diagnostic("story_turn_generation", reason, session_id or "-")
        return TurnOutcome("", -1, STATUS_FAILED, reason, True) if opening else \
            TurnOutcome(session_id, turn_index, STATUS_FAILED, reason, True)
    except Exception:  # noqa: BLE001 — the ingest itself always wins
        _ledger(STATUS_FAILED, "generation_failed")
        _diagnostic("story_turn_generation", "generation_failed", session_id or "-")
        return TurnOutcome("", -1, STATUS_FAILED, "generation_failed", True) if opening else \
            TurnOutcome(session_id, turn_index, STATUS_FAILED, "generation_failed", True)

    parsed = parse_turn_output(generated)
    if parsed is None:
        _ledger(STATUS_FAILED, "malformed_generation")
        _diagnostic("story_turn_generation", "malformed_generation", session_id or "-")
        return TurnOutcome("", -1, STATUS_FAILED, "malformed_generation", True) if opening else \
            TurnOutcome(session_id, turn_index, STATUS_FAILED, "malformed_generation", True)

    message = parsed["message"]
    question_allowed = shape.question_allowed and not parsed["question_free"]
    blocking, advisory = lint_outgoing(
        message, question_allowed=question_allowed, config=_lints_config()
    )
    if blocking:
        _ledger(STATUS_FAILED, "malformed_generation", tuple(blocking))
        _diagnostic("story_turn_lint", "malformed_generation", session_id or "-")
        if opening:
            return TurnOutcome("", -1, STATUS_FAILED, "malformed_generation", True,
                                lint_ids=tuple(blocking))
        return TurnOutcome(session_id, turn_index, STATUS_FAILED, "malformed_generation", True,
                            lint_ids=tuple(blocking))

    if opening:
        # Generation + lint cleared — worth persisting now, right before the
        # external effect (same "conservative position before the send" as
        # the answer-path engine, just deferred one step further here).
        session = conversation.open_session("conversation", channel, vault_root=vault_root)
        session_id = str(session["session_id"])
        user_turn = {
            "role": "user",
            "text": story_text,
            "channel": channel,
            "source_path": source_path,
        }
        try:
            session = conversation.append_turn(
                session_id, user_turn, expected_turns=0, vault_root=vault_root,
            )
        except (conversation.TurnConflictError, conversation.SessionClosedError):
            return TurnOutcome(session_id, -1, STATUS_SKIPPED, "turn_already_minted", False)
        turn_index = len(session.get("turns") or [])
        key = turn_key(session_id, turn_index)

    _write_outcome(
        state_path, key, session_id=session_id, turn_index=turn_index, question_id="",
        status=STATUS_AMBIGUOUS, reason="send_in_progress", attempts=attempts,
    )
    send_result = (telegram_send or send_telegram_result)(message)
    if send_result.status == "confirmed":
        status, reason = STATUS_CONFIRMED, "telegram_confirmed"
    elif send_result.status == "ambiguous":
        status, reason = STATUS_AMBIGUOUS, send_result.reason
    elif send_result.status == "not_attempted":
        status, reason = STATUS_SKIPPED, send_result.reason
    else:
        status, reason = STATUS_FAILED, send_result.reason

    if status != STATUS_CONFIRMED:
        _write_outcome(
            state_path, key, session_id=session_id, turn_index=turn_index, question_id="",
            status=status, reason=reason, attempts=attempts, advisory_lints=advisory,
        )
        _diagnostic("story_turn_send", reason, session_id)
        return TurnOutcome(session_id, turn_index, status, reason, True)

    lifehug_turn = {"role": "lifehug", "text": message, "channel": channel, "model": model}
    try:
        _append_turn_resilient(
            session_id, lifehug_turn, expected_turns=turn_index, vault_root=vault_root
        )
        conversation.merge_session_extraction(
            session_id, rolling_summary=parsed["rolling_summary"], extracted=parsed["extracted"],
            vault_root=vault_root,
        )
    except Exception:  # noqa: BLE001 — the message is already delivered
        _diagnostic("story_turn_session_record", "session_write_failed", session_id)

    _write_outcome(
        state_path, key, session_id=session_id, turn_index=turn_index, question_id="",
        status=STATUS_CONFIRMED, reason="telegram_confirmed", attempts=attempts,
        advisory_lints=advisory,
    )
    if parsed["insight_receipts"]:
        _record_insight_receipts(state_path, key, parsed["insight_receipts"])
    return TurnOutcome(
        session_id, turn_index, STATUS_CONFIRMED, "telegram_confirmed", True,
        question_free=parsed["question_free"],
    )


def _lints_config() -> dict | None:
    try:
        return conversation_lints.load_lints_config()
    except (OSError, ValueError):
        return None


def _record_insight_receipts(state_path: Path, key: str, count: int) -> None:
    """Metadata-only receipt count, read back by the close step."""
    data = _state(state_path)
    entry = data["entries"].get(key)
    if isinstance(entry, dict):
        entry["insight_receipts"] = int(count)
        write_json(state_path, data)


def _mint_followup(
    question_id: str,
    followup_text: str,
    *,
    minter: Callable[[str, list[str]], list[tuple[str, str]]] | None,
    rotation_updater: Callable[[str], None] | None,
    session_id: str,
) -> str | None:
    """File the cued follow-up as an A14 -> A14b suffix-chain bank question.

    Minting happens only AFTER a confirmed send: a question the user never
    received must not appear in their bank. Rotation then targets the new id
    exactly as ``ask.mark_question_sent`` does, so the host agent files the
    next inbound against it — and cadence accounting still counts this send,
    keeping the 3/day cap governing our initiative.
    """
    try:
        if minter is None:
            from process_answer import append_followups  # noqa: PLC0415

            minter = append_followups
        added = minter(question_id, [followup_text])
    except Exception:  # noqa: BLE001
        _diagnostic("followup_mint", "mint_failed", session_id)
        return None
    if not added:
        return None
    new_id = str(added[0][0])
    try:
        if rotation_updater is None:
            rotation_updater = _default_rotation_update
        rotation_updater(new_id)
    except Exception:  # noqa: BLE001
        _diagnostic("rotation_update", "rotation_update_failed", session_id)
    return new_id


def _default_rotation_update(question_id: str) -> None:
    import ask  # noqa: PLC0415
    from lifehug_core import ROTATION_FILE, rebuild_coverage  # noqa: PLC0415

    rotation = read_json(ROTATION_FILE, default={}) or {}
    ask.mark_question_sent(rotation, question_id)
    rebuild_coverage()


# --------------------------------------------------------------------------
# Lifecycle: idle sweep, close, engagement capture, extracted filing
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class CloseOutcome:
    """Metadata-only result of closing one session."""

    session_id: str
    reason: str
    silent: bool
    takeaway_delivered: bool
    status: str
    detail: str
    filed: tuple[str, ...] = ()
    user_turns: int = 0


def _last_activity(session: dict) -> datetime | None:
    turns = session.get("turns") or []
    if turns:
        moment = _parse_ts(turns[-1].get("ts"))
        if moment is not None:
            return moment
    return _session_opened_at(str(session.get("session_id") or ""))


def idle_timeout_minutes(session: dict, manifest: dict) -> int:
    """Per-mode idle timeout from interaction.yaml (chat ~2h, conversation ~30m)."""
    if session.get("mode") == "conversation":
        return _knob(manifest, "knob.conversation_idle_timeout_minutes", 30)
    return _knob(manifest, "knob.chat_idle_timeout_minutes", 120)


def is_idle_expired(session: dict, *, manifest: dict, now: datetime | None = None) -> bool:
    moment = _last_activity(session)
    if moment is None:
        return False
    reference = now or _now()
    return reference - moment >= timedelta(minutes=idle_timeout_minutes(session, manifest))


def _filed_question_ids(session: dict) -> tuple[str, ...]:
    filed: list[str] = []
    for turn in session.get("turns") or []:
        if turn.get("role") != "user":
            continue
        qid = turn.get("question_id")
        if qid and str(qid) not in filed:
            filed.append(str(qid))
    return tuple(filed)


def _session_insight_receipts(state_path: Path, session_id: str) -> int:
    prefix = f"turn:{session_id}:"
    total = 0
    for key, entry in _state(state_path)["entries"].items():
        if key.startswith(prefix) and isinstance(entry, dict):
            total += int(entry.get("insight_receipts", 0) or 0)
    return total


def turn_length_trajectory(session: dict) -> str:
    """expanding | flat | contracting over this session's user turns."""
    lengths = [
        len((turn.get("text") or "").strip())
        for turn in session.get("turns") or []
        if turn.get("role") == "user"
    ]
    if len(lengths) < 2:
        return "flat"
    midpoint = len(lengths) // 2
    first = lengths[:midpoint] or lengths[:1]
    second = lengths[-midpoint:] or lengths[-1:]
    early = sum(first) / len(first)
    late = sum(second) / len(second)
    if early <= 0:
        return "flat"
    ratio = late / early
    if ratio >= 1.2:
        return "expanding"
    if ratio <= 0.8:
        return "contracting"
    return "flat"


def append_engagement(
    session: dict,
    *,
    close_reason: str,
    manifest: dict,
    scores_path: Path | None = None,
) -> list[str]:
    """Append the engagement object to each filed question's answer_scores record.

    Field names for the SHARED fields are #119's authority
    (``continuation_past_exit``, ``turn_length_trajectory``); ``session_id``,
    ``session_turns`` and ``close_reason`` are this PR's own contributions.
    ``time_to_answer_hours`` and ``unprompted_inbound`` are computed
    elsewhere (#119) and are deliberately left absent rather than guessed.
    Richness fields are never touched.

    MERGES into any existing ``engagement`` dict rather than replacing it
    (#119): ``process_answer.py`` may already have seeded
    ``time_to_answer_hours`` at filing time — strictly before a session can
    close — and #119's own close orchestration adds ``unprompted_inbound``
    strictly after this call returns. Two writers of one field must compose,
    not clobber (recurring-defect doctrine).
    """
    filed = _filed_question_ids(session)
    if not filed:
        return []
    scores_path = scores_path if scores_path is not None else ANSWER_SCORES_FILE
    data = read_json(scores_path, default=None)
    if not isinstance(data, dict) or not isinstance(data.get("scores"), list):
        return []
    user_turns = _count_user_turns(session)
    target = _knob(manifest, "knob.chat_target_exchanges", 3)
    engagement = {
        "session_id": str(session.get("session_id") or ""),
        "session_turns": len(session.get("turns") or []),
        "continuation_past_exit": user_turns > target,
        "turn_length_trajectory": turn_length_trajectory(session),
        "close_reason": close_reason,
    }
    touched: list[str] = []
    for record in data["scores"]:
        if not isinstance(record, dict):
            continue
        if str(record.get("question_id") or "") in filed:
            existing = record.get("engagement")
            merged = dict(existing) if isinstance(existing, dict) else {}
            merged.update(engagement)
            record["engagement"] = merged
            touched.append(str(record["question_id"]))
    if touched:
        data["last_updated"] = now_utc()
        write_json(scores_path, data)
    return touched


def file_candidate_ideas(
    session: dict,
    *,
    candidates_path: Path | None = None,
) -> list[str]:
    """File extracted.candidate_ideas into the candidate store, provenance conversation."""
    extracted = session.get("extracted") or {}
    ideas = extracted.get("candidate_ideas") if isinstance(extracted, dict) else None
    if not isinstance(ideas, list) or not ideas:
        return []
    import question_candidates  # noqa: PLC0415

    path = candidates_path or question_candidates.QUESTION_CANDIDATES_FILE
    store = question_candidates.load_store(path)
    existing = {
        question_candidates.normalize_question(str(c.get("text", "")))
        for c in store.get("candidates", [])
        if isinstance(c, dict)
    }
    session_id = str(session.get("session_id") or "")
    created = now_utc()
    added: list[str] = []
    for index, idea in enumerate(ideas, 1):
        text = idea.get("text") if isinstance(idea, dict) else idea
        if not isinstance(text, str) or not text.strip():
            continue
        clean = text.strip()
        if question_candidates.normalize_question(clean) in existing:
            continue
        existing.add(question_candidates.normalize_question(clean))
        cid = f"cand-{session_id}-{index}"
        store.setdefault("candidates", []).append({
            "id": cid,
            "text": clean,
            "source_path": None,
            "target_page": None,
            "kind": "conversation",
            "priority": 0.5,
            "reason": "Proposed inside a Lifehug conversation",
            "status": "candidate",
            "story_function": None,
            "created_at": created,
            "provenance": "conversation",
        })
        added.append(cid)
    if added:
        question_candidates.save_store(store, path)
    return added


def _story_source_paths(session: dict) -> tuple[str, ...]:
    """The distinct story ``source_path`` values behind this session's user
    turns (issue #117) — only story-mode ("conversation") user turns carry
    this field; a chat session's answer turns carry ``question_id`` instead
    and contribute nothing here."""
    paths: list[str] = []
    for turn in session.get("turns") or []:
        if turn.get("role") != "user":
            continue
        source_path = turn.get("source_path")
        if source_path and str(source_path) not in paths:
            paths.append(str(source_path))
    return tuple(paths)


def supersede_template_candidates_for_session(
    session: dict,
    *,
    candidates_path: Path | None = None,
) -> list[str]:
    """Flip this session's story-source template candidates to ``superseded``.

    Called only when the close step actually filed classifier-grade
    ``extracted.candidate_ideas`` (provenance ``conversation``) for this
    session — the templates are the documented no-session fallback and the
    immediate-value floor; a session that closes with nothing extracted
    leaves them live. Goes through ``question_candidates.update_candidate``
    so ``updated_at``-style bookkeeping stays consistent with every other
    status transition in that store (contract, implementation notes).
    """
    sources = _story_source_paths(session)
    if not sources:
        return []
    import question_candidates  # noqa: PLC0415

    path = candidates_path or question_candidates.QUESTION_CANDIDATES_FILE
    data = question_candidates.load_store(path)
    superseded: list[str] = []
    for candidate in data.get("candidates", []):
        if candidate.get("status") != "candidate":
            continue
        if str(candidate.get("source_path") or "") not in sources:
            continue
        question_candidates.update_candidate(data, candidate["id"], status="superseded")
        superseded.append(candidate["id"])
    if superseded:
        question_candidates.save_store(data, path)
    return superseded


def _entity_hints(session: dict) -> list[str]:
    extracted = session.get("extracted") or {}
    entities = extracted.get("entities") if isinstance(extracted, dict) else None
    if not isinstance(entities, list):
        return []
    hints: list[str] = []
    for entity in entities:
        name = entity.get("name") if isinstance(entity, dict) else entity
        if isinstance(name, str) and name.strip() and name.strip() not in hints:
            hints.append(name.strip())
    return hints


def close_session_now(
    session_id: str,
    *,
    reason: str = "done",
    state_path: Path | None = None,
    vault_root: str | Path | None = None,
    scores_path: Path | None = None,
    candidates_path: Path | None = None,
    channel: str = "telegram",
    ai_call: Callable[[str, str], str] | None = None,
    telegram_send: Callable[[str], TelegramSendResult] | None = None,
    status_resolver: Callable[..., object] | None = None,
    prompt_builder: Callable[[dict], str] | None = None,
    manifest: dict | None = None,
) -> CloseOutcome:
    """Close one session: closing takeaway when warranted, silence otherwise.

    The closing-takeaway criterion is the deterministic cross-runtime rule
    (platform #414 confirms the same rule): a close message goes out only
    when the session has at least TWO user turns. Zero-turn sessions and
    chats abandoned mid-exchange close SILENTLY — whatever was answered is
    already durably filed per turn, so a "you didn't finish" nudge would be
    pressure with no content. No-nag is owner-confirmed.
    """
    state_path = state_path if state_path is not None else DELIVERY_STATE_FILE
    vault_root = vault_root if vault_root is not None else VAULT_ROOT
    scores_path = scores_path if scores_path is not None else ANSWER_SCORES_FILE
    manifest = manifest if manifest is not None else _manifest()
    session = conversation.load_session(session_id, vault_root=vault_root)
    filed = _filed_question_ids(session)
    user_turns = _count_user_turns(session)
    receipts = _session_insight_receipts(state_path, session_id)
    takeaway = ""
    delivered = False
    status, detail = STATUS_SKIPPED, "no_close_message"

    if user_turns >= 2:
        status, detail, takeaway = _deliver_closing(
            session,
            state_path=state_path,
            channel=channel,
            ai_call=ai_call,
            telegram_send=telegram_send,
            status_resolver=status_resolver,
            prompt_builder=prompt_builder,
            vault_root=vault_root,
        )
        delivered = status == STATUS_CONFIRMED
    else:
        detail = "silent_no_nag"

    close = {
        "reason": reason,
        "takeaway": takeaway if delivered else "",
        "takeaway_delivered": delivered,
        "insight_receipts_count": receipts,
        "filed": list(filed),
    }
    hints = _entity_hints(session)
    if hints:
        # Classification hints for the weekly pass. The pass has no
        # dedicated hint surface today (verified against classify_story.py /
        # state/agent_tasks), so the close block IS the surface; wiring the
        # weekly consumer belongs to whoever owns that pass.
        close["entity_hints"] = hints
    closed = conversation.close_session(session_id, close, vault_root=vault_root)

    try:
        append_engagement(
            closed, close_reason=reason, manifest=manifest, scores_path=scores_path
        )
    except Exception:  # noqa: BLE001 — instrumentation never blocks a close
        _diagnostic("engagement_capture", "engagement_write_failed", session_id)
    added_candidates: list[str] = []
    try:
        added_candidates = file_candidate_ideas(closed, candidates_path=candidates_path)
    except Exception:  # noqa: BLE001
        _diagnostic("candidate_filing", "candidate_write_failed", session_id)

    if added_candidates:
        # Issue #117: classifier-grade extraction landed for this session —
        # supersede the template candidates it was standing in for. A close
        # with NO extracted candidate_ideas leaves the templates live
        # (contract, "the templates stay live" — the no-session fallback IS
        # the immediate-value floor when nothing better ever arrives).
        try:
            supersede_template_candidates_for_session(closed, candidates_path=candidates_path)
        except Exception:  # noqa: BLE001
            _diagnostic("candidate_supersede", "candidate_supersede_failed", session_id)

    return CloseOutcome(
        session_id,
        reason,
        silent=not delivered,
        takeaway_delivered=delivered,
        status=status,
        detail=detail,
        filed=filed,
        user_turns=user_turns,
    )


def _deliver_closing(
    session: dict,
    *,
    state_path: Path,
    channel: str,
    ai_call: Callable[[str, str], str] | None,
    telegram_send: Callable[[str], TelegramSendResult] | None,
    status_resolver: Callable[..., object] | None,
    prompt_builder: Callable[[dict], str] | None,
    vault_root: str | Path | None,
) -> tuple[str, str, str]:
    """Generate/lint/send the closing takeaway; ledger it under close:{id}.

    A failed close is SILENT, never a fallback ack: the ack is the
    post-answer voice, and every answer in this session already got one turn
    or one ack of its own. Returning (status, detail, takeaway).
    """
    session_id = str(session["session_id"])
    key = close_key(session_id)
    entries = _state(state_path)["entries"]
    previous = entries.get(key, {})
    if previous.get("status") == STATUS_CONFIRMED:
        return STATUS_CONFIRMED, "already_confirmed", str(previous.get("takeaway", ""))
    if previous.get("status") == STATUS_AMBIGUOUS:
        return STATUS_AMBIGUOUS, "ambiguous_not_retried", ""
    attempts = int(previous.get("attempts", 0) or 0) + 1
    turn_index = len(session.get("turns") or [])

    def ledger(status: str, reason: str, lint_ids: tuple[str, ...] = ()) -> None:
        _write_outcome(
            state_path,
            key,
            session_id=session_id,
            turn_index=turn_index,
            question_id="",
            status=status,
            reason=reason,
            attempts=attempts,
            lint_ids=lint_ids,
        )

    model = conversation_model()
    resolve_status = status_resolver or provider_status
    selected = resolve_status(model, probe=False)
    if not getattr(selected, "ready", False):
        reason = (
            "no_unattended_provider"
            if getattr(selected, "provider", "") == "agent-task"
            else "provider_unavailable"
        )
        ledger(STATUS_SKIPPED, reason)
        return STATUS_SKIPPED, reason, ""

    builder = prompt_builder or conversation.build_closing_prompt
    try:
        prompt = builder({"session": session}) + _closing_output_contract()
        generated = (ai_call or call_ai)(prompt, model)
    except AIProviderError as exc:
        reason = _fixed_provider_reason(exc)
        ledger(STATUS_FAILED, reason)
        _diagnostic("closing_generation", reason, session_id)
        return STATUS_FAILED, reason, ""
    except Exception:  # noqa: BLE001
        ledger(STATUS_FAILED, "generation_failed")
        _diagnostic("closing_generation", "generation_failed", session_id)
        return STATUS_FAILED, "generation_failed", ""

    parsed = parse_turn_output(generated)
    message = parsed["message"] if parsed else _valid_message(generated)
    if message is None:
        ledger(STATUS_FAILED, "malformed_generation")
        _diagnostic("closing_generation", "malformed_generation", session_id)
        return STATUS_FAILED, "malformed_generation", ""
    # Behavior rule 8: a close ends on the peak and STOPS — no trailing
    # question. That makes every closing message question-free by contract.
    blocking, _advisory = lint_outgoing(
        message, question_allowed=False, config=_lints_config()
    )
    if blocking:
        ledger(STATUS_FAILED, "malformed_generation", tuple(blocking))
        _diagnostic("closing_lint", "malformed_generation", session_id)
        return STATUS_FAILED, "malformed_generation", ""

    ledger(STATUS_AMBIGUOUS, "send_in_progress")
    send_result = (telegram_send or send_telegram_result)(message)
    if send_result.status == "confirmed":
        ledger(STATUS_CONFIRMED, "telegram_confirmed")
        try:
            _append_turn_resilient(
                session_id,
                {
                    "role": "lifehug",
                    "text": message,
                    "channel": channel,
                    "model": model,
                },
                expected_turns=turn_index,
                vault_root=vault_root,
            )
        except Exception:  # noqa: BLE001 — already delivered
            _diagnostic("session_record", "session_write_failed", session_id)
        return STATUS_CONFIRMED, "telegram_confirmed", message
    if send_result.status == "ambiguous":
        ledger(STATUS_AMBIGUOUS, send_result.reason)
        _diagnostic("closing_send", send_result.reason, session_id)
        return STATUS_AMBIGUOUS, send_result.reason, ""
    status = STATUS_SKIPPED if send_result.status == "not_attempted" else STATUS_FAILED
    ledger(status, send_result.reason)
    _diagnostic("closing_send", send_result.reason, session_id)
    return status, send_result.reason, ""


def _closing_output_contract() -> str:
    return (
        "\n\nReply with a single JSON object and nothing else:\n"
        '{"message": "the closing message, plain text", "question_free": true}\n'
        "The closing message ends on the peak and STOPS — no trailing question.\n"
    )


def find_expired_open_sessions(
    *,
    vault_root: str | Path | None = None,
    manifest: dict | None = None,
    now: datetime | None = None,
) -> list[str]:
    """Session ids for every OPEN session past its idle timeout.

    Pure discovery — deterministic, AI-free, no closing, no send: distinct
    from ``close_expired_sessions`` (which actually closes each one,
    generating and sending an AI takeaway where warranted). Issue #119's
    ``conversation-close --expired`` sweep entry point uses THIS to decide
    what to enqueue as durable jobs, keeping the discovery step itself free
    of AI calls; ``close_expired_sessions`` stays exactly as PR3 shipped it
    (the inline per-turn sweep's synchronous close, unchanged).
    """
    vault_root = vault_root if vault_root is not None else VAULT_ROOT
    manifest = manifest if manifest is not None else _manifest()
    reference = now or _now()
    ids: list[str] = []
    for summary in conversation.list_sessions(status="open", vault_root=vault_root):
        session_id = summary.get("session_id")
        if not session_id:
            continue
        try:
            session = conversation.load_session(session_id, vault_root=vault_root)
        except (OSError, ValueError):
            continue
        if is_idle_expired(session, manifest=manifest, now=reference):
            ids.append(str(session_id))
    return ids


def close_expired_sessions(
    *,
    now: datetime | None = None,
    vault_root: str | Path | None = None,
    state_path: Path | None = None,
    scores_path: Path | None = None,
    candidates_path: Path | None = None,
    ai_call: Callable[[str, str], str] | None = None,
    telegram_send: Callable[[str], TelegramSendResult] | None = None,
    status_resolver: Callable[..., object] | None = None,
    prompt_builder: Callable[[dict], str] | None = None,
) -> list[CloseOutcome]:
    """Lazy sweep: close every open session past its idle timeout.

    No daemon and no cron change in this PR — the sweep runs at the top of
    every post-answer turn and on demand via ``conversation-close --expired``
    (the same subcommand #119's jobs builder enqueues).
    """
    state_path = state_path if state_path is not None else DELIVERY_STATE_FILE
    vault_root = vault_root if vault_root is not None else VAULT_ROOT
    scores_path = scores_path if scores_path is not None else ANSWER_SCORES_FILE
    manifest = _manifest()
    reference = now or _now()
    outcomes: list[CloseOutcome] = []
    for summary in conversation.list_sessions(status="open", vault_root=vault_root):
        session_id = summary.get("session_id")
        if not session_id:
            continue
        try:
            session = conversation.load_session(session_id, vault_root=vault_root)
        except (OSError, ValueError):
            continue
        if not is_idle_expired(session, manifest=manifest, now=reference):
            continue
        try:
            outcomes.append(
                close_session_now(
                    session_id,
                    reason="idle_timeout",
                    state_path=state_path,
                    vault_root=vault_root,
                    scores_path=scores_path,
                    candidates_path=candidates_path,
                    ai_call=ai_call,
                    telegram_send=telegram_send,
                    status_resolver=status_resolver,
                    prompt_builder=prompt_builder,
                    manifest=manifest,
                )
            )
        except Exception:  # noqa: BLE001 — one bad session never stalls the sweep
            _diagnostic("idle_sweep", "close_failed", str(session_id))
    return outcomes


def retry_turn(
    session_id: str,
    turn_index: int,
    *,
    confirm_not_sent: bool = False,
    state_path: Path | None = None,
    vault_root: str | Path | None = None,
    ai_call: Callable[[str, str], str] | None = None,
    telegram_send: Callable[[str], TelegramSendResult] | None = None,
    status_resolver: Callable[..., object] | None = None,
) -> TurnOutcome:
    """Operator door: retry a definitively unsent turn.

    Ambiguous entries need ``--confirm-not-sent`` (operator verified
    Telegram), exactly like ``answer-ack-retry``. A retried turn is always
    question-free: the operator is recovering a lost receipt, not spending
    fresh question initiative.
    """
    state_path = state_path if state_path is not None else DELIVERY_STATE_FILE
    vault_root = vault_root if vault_root is not None else VAULT_ROOT
    session = conversation.load_session(session_id, vault_root=vault_root)
    turns = session.get("turns") or []
    user_index = turn_index - 1
    if user_index < 0 or user_index >= len(turns) or turns[user_index].get("role") != "user":
        raise ValueError(f"no user turn at index {user_index} in {session_id}")
    user_turn = turns[user_index]
    question_id = str(user_turn.get("question_id") or "")
    return run_post_answer_turn(
        source_id=f"answer:{question_id}" if question_id else session_id,
        question_id=question_id,
        question_text="",
        question_category="",
        answer_text=str(user_turn.get("text") or ""),
        planned_question=None,
        state_path=state_path,
        vault_root=vault_root,
        pinned_session_id=session_id,
        allow_ambiguous_retry=confirm_not_sent,
        sweep=False,
        ai_call=ai_call,
        telegram_send=telegram_send,
        status_resolver=status_resolver,
        fallback=lambda **_kwargs: None,
    )


# --------------------------------------------------------------------------
# CLI — conversation-status / conversation-close / conversation-turn-retry
# --------------------------------------------------------------------------


def print_status(session_id: str | None, *, full: bool = False, state_path: Path | None = None) -> int:
    """Session summary + delivery-ledger status (metadata only by default)."""
    state_path = state_path if state_path is not None else DELIVERY_STATE_FILE
    entries = _state(state_path)["entries"]
    if session_id:
        try:
            doc = conversation.load_session(session_id)
        except (FileNotFoundError, ValueError) as exc:
            print(f"Error: {exc}")
            return 1
        turns = doc.get("turns") or []
        print(f"{doc['session_id']}: {doc.get('status')} ({doc.get('mode')}/{doc.get('channel')})")
        print(f"turns: {len(turns)}")
        close = doc.get("close") or {}
        if close:
            print(
                f"close: {close.get('reason')} (takeaway_delivered="
                f"{bool(close.get('takeaway_delivered'))}; "
                f"insight_receipts={close.get('insight_receipts_count', 0)}; "
                f"filed={','.join(close.get('filed') or []) or '-'})"
            )
        if full:
            for turn in turns:
                print(f"  {turn.get('role')} [{turn.get('ts')}]: {turn.get('text')}")
        entries = {k: v for k, v in entries.items() if v.get("session_id") == session_id}
    else:
        for summary in conversation.list_sessions():
            print(
                f"{summary['session_id']}: {summary['status']} "
                f"({summary['mode']}/{summary['channel']}; turns={summary['turn_count']})"
            )
    if not entries:
        print("No conversation delivery metadata found.")
        return 0
    print("delivery ledger:")
    for key, entry in sorted(entries.items()):
        print(
            f"  {key}: {entry.get('status', 'unknown')} "
            f"({entry.get('reason', 'unknown')}; attempts={entry.get('attempts', 0)})"
        )
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    return print_status(args.session_id, full=args.full)


def cmd_close(args: argparse.Namespace) -> int:
    if args.expired:
        outcomes = close_expired_sessions()
        if not outcomes:
            print("No expired conversation sessions.")
            return 0
        for outcome in outcomes:
            print(
                f"{outcome.session_id}: closed ({outcome.reason}; "
                f"{'silent' if outcome.silent else 'takeaway sent'}; {outcome.detail})"
            )
        return 0
    if not args.session_id:
        print("Error: pass a session id or --expired")
        return 1
    try:
        outcome = close_session_now(args.session_id, reason=args.reason)
    except (FileNotFoundError, ValueError, conversation.ConversationError) as exc:
        print(f"Error: {exc}")
        return 1
    print(
        f"{outcome.session_id}: closed ({outcome.reason}; "
        f"{'silent' if outcome.silent else 'takeaway sent'}; {outcome.detail})"
    )
    return 0


def cmd_turn_retry(args: argparse.Namespace) -> int:
    try:
        outcome = retry_turn(
            args.session_id, args.turn_index, confirm_not_sent=args.confirm_not_sent
        )
    except (FileNotFoundError, ValueError, conversation.ConversationError) as exc:
        print(f"Error: {exc}")
        return 1
    print(f"{outcome.session_id} turn {outcome.turn_index}: {outcome.status} ({outcome.reason})")
    return 0 if outcome.status == STATUS_CONFIRMED else 1


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Conversation turn delivery: status, close/sweep, and retry"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("status", help="Session + delivery-ledger status (metadata only)")
    p.add_argument("session_id", nargs="?")
    p.add_argument("--full", action="store_true", help="Also print turn text (private content)")
    p.set_defaults(func=cmd_status)

    p = sub.add_parser("close", help="Close one session now, or sweep every expired one")
    p.add_argument("session_id", nargs="?")
    p.add_argument("--expired", action="store_true", help="Close every idle-expired session")
    p.add_argument("--reason", default="done", choices=sorted(conversation.VALID_CLOSE_REASONS))
    p.set_defaults(func=cmd_close)

    p = sub.add_parser("turn-retry", help="Retry a definitively unsent turn")
    p.add_argument("session_id")
    p.add_argument("turn_index", type=int)
    p.add_argument(
        "--confirm-not-sent",
        action="store_true",
        help="Retry an ambiguous send only after verifying Telegram did not receive it",
    )
    p.set_defaults(func=cmd_turn_retry)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
