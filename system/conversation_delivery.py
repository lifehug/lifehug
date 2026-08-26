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
import sys
from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable

import chronology as _chrono
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
    SYSTEM_DIR,
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
#: v201 (lifehug#206): "no_repetition" joins the blocking set. A turn that
#: re-asks what this same voice asked two turns ago is never worth
#: sending, and the degrade/retry path this set feeds is exactly where
#: such a turn should land.
RUNTIME_BLOCKING_LINTS = (
    "one_question_per_turn", "banned_phrases", "length_caps", "no_repetition",
)

#: ADR 0015 (issue #167, content-first close): close reasons that fire ONLY
#: from a sweep/janitor/day-rollover context — no person is necessarily
#: present in the moment. When ``build_closing_prompt`` starves here
#: (``conversation.ConversationPromptError``), the degradation is SILENCE
#: (the existing no-takeaway close path) — the session still closes
#: cleanly. Every other reason ("done", "exit_taken") is a live,
#: budget-reached closing beat: a starved builder there degrades to an
#: ordinary question-free turn instead — never silence on a present
#: person — and the close itself is deferred to a later attempt.
SWEEP_CLOSE_REASONS = frozenset({"idle_timeout", "day_rollover"})

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
    # question-candidate-placement-aside (issue #181): additive, default
    # None. A caller composing a Play/candidate turn sets this to the
    # {placement_stage} value ("assert" | "ask" | "settled" — Design §D)
    # to have _output_contract_block() append the one optional "placement"
    # output key; every other caller leaves it None and the appendix stays
    # byte-identical to pre-#181 output (required test:
    # test_output_contract_block_byte_identical_without_roster).
    placement_stage: str | None = None
    # focus-onboarding-context (v189, Design §B): additive, default None.
    # A caller composing a focus-onboarding turn sets this to the
    # {focus_stage} value ("establish" | "settled" — Design §C) to have
    # _output_contract_block() append the one optional "focus_setup"
    # output key; every other caller leaves it None and the appendix stays
    # byte-identical to pre-v189 output (required test:
    # test_output_contract_block_byte_identical_without_focus_stage).
    focus_stage: str | None = None
    # entity-identity-context (v190, Design §B): additive, default None.
    # A caller composing an entity-identity turn sets this to the
    # {entity_stage} value ("establish" | "settled" — Design §C) to have
    # _output_contract_block() append the one optional "entity_setup"
    # output key; every other caller leaves it None and the appendix stays
    # byte-identical to pre-v190 output (required test:
    # test_output_contract_block_byte_identical_without_entity_stage).
    entity_stage: str | None = None
    # arc-walk-interaction (v193, Design §C): additive, default None. A
    # caller composing an arc-walk turn sets this to the {arc_stage} value
    # ("open" | "walk" | "close" — Design §B.4) to have
    # _output_contract_block() append the one optional
    # "answered_question_id" output key; every other caller leaves it None
    # and the appendix stays byte-identical to pre-v193 output (required
    # test: test_output_contract_block_byte_identical_without_arc_stage —
    # owner ruling 6's mechanical form: the passive daily question's prompt
    # does not move by one byte).
    arc_stage: str | None = None
    # timeline-chronology (v195, Design §D): additive, default None. A caller
    # composing a timeline-placement turn sets this to the {timeline_stage}
    # value ("open" | "place" | "close") to have _output_contract_block()
    # append the one optional "placed" output key; every other caller leaves
    # it None and the appendix stays byte-identical to pre-v195 output
    # (required test:
    # test_output_contract_block_byte_identical_without_timeline_stage —
    # owner ruling 7's mechanical form: the passive daily question's prompt
    # does not move by one byte).
    timeline_stage: str | None = None
    # landmarks (v197, Design §D): additive, default None. A caller composing
    # a landmark-collection turn sets this to the {landmark_stage} value
    # ("open" | "ask" | "close") to have _output_contract_block() append the
    # one optional "landmark" output key; every other caller leaves it None
    # and the appendix stays byte-identical to pre-v197 output (required
    # test: test_output_contract_block_byte_identical_without_landmark_stage
    # — the passive daily question's prompt does not move by one byte).
    landmark_stage: str | None = None
    # the Reading Room (v204, ADR 0025): additive, default None, and the one
    # gate that opens TWO existing keys rather than a new one. A Reading Room
    # turn can produce a dated moment (`placed`, the Timeline lane's shape) or
    # a landmark (`landmark`, the Landmarks lane's shape) — it mints no third
    # vocabulary of its own. Every other caller leaves it None and the
    # appendix stays byte-identical (required test:
    # test_output_contract_block_byte_identical_without_reading_room_stage).
    reading_room_stage: str | None = None


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
    hook: str | None = None,
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
    # ADR 0014 (issue #163): the structured close's machine-only hook,
    # ledgered alongside the closing ledger entry so a replayed
    # close_session_now (already_confirmed path) reconstructs the SAME
    # close block — conversation.close_session's idempotency check requires
    # byte-identical close payloads on a repeat call.
    if hook:
        entry["hook"] = hook
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


#: The basis vocabulary the output contract advertises, DERIVED from
#: `chronology.BASES` (recurring-defect doctrine: one authoritative
#: definition). Before v204 this was a hand-typed literal in two places, so a
#: basis added to the tuple silently never reached the model.
_BASIS_VOCABULARY = " | ".join(_chrono.BASES)


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
            "Ask AT MOST ONE question, and it must be either a cued "
            "invitation that quotes the user's own phrase, OR — when one "
            "fits naturally — a held question from the ASKING_SUPPLY block "
            "below, asked verbatim or lightly adapted and introduced "
            "honestly as held (never passed off as improvised). Put that "
            "same question's text in \"followup_question\"."
        )
    else:
        question_rule = (
            "Ask NO question — keep receiving — UNLESS the user's own last "
            "message genuinely invites another question (an explicit "
            "request like \"what else you got\", or open-ended receptivity "
            "like \"that's all I remember\") AND the question you'd ask is "
            "one of ASKING_SUPPLY's held questions; when genuinely unsure "
            "whether they invited it, treat it as invited (fail toward "
            "asking). Otherwise set \"followup_question\" to null and "
            "\"question_free\" to true."
        )
    # question-candidate-placement-aside (issue #181, Design §C1): the one
    # additive "placement" output key exists ONLY when the caller set
    # shape.placement_stage; absent it, this whole block — line and note
    # alike — stays out, so an ordinary turn's appendix is byte-identical
    # to pre-#181 output.
    placement_line = (
        '  "placement": {"category": "the exact roster letter"} | null,\n'
        if shape.placement_stage is not None
        else ""
    )
    placement_note = (
        '- "placement" is null on every turn except one where the USER named '
        "where this belongs; then it is the exact roster letter from "
        "CATEGORY_ROSTER and nothing else. Never invent a letter, never "
        "guess, never fill it to look decisive.\n"
        if shape.placement_stage is not None
        else ""
    )
    # focus-onboarding-context (v189, Design §B): the one additive
    # "focus_setup" output key exists ONLY when the caller set
    # shape.focus_stage; absent it, line and note alike stay out, so an
    # ordinary turn's appendix is byte-identical to pre-v189 output.
    focus_setup_line = (
        '  "focus_setup": {"objective": "what this focus is for", "type": '
        '"one of the focus types", "relationship": "how they are related to '
        'you", "living": true | false, "label": "what to call this focus"} '
        "| null,\n"
        if shape.focus_stage is not None
        else ""
    )
    focus_setup_note = (
        '- "focus_setup" is null on every turn except one where the USER '
        "supplied or changed what this focus is about — its purpose, its "
        "type, how the person is related to you, whether they are living, "
        "or what to call it. Include only the keys they actually gave you. "
        "Never invent a value, never fill it to look decisive.\n"
        if shape.focus_stage is not None
        else ""
    )
    # entity-identity-context (v190, Design §B): the one additive
    # "entity_setup" output key exists ONLY when the caller set
    # shape.entity_stage; absent it, line and note alike stay out, so an
    # ordinary turn's appendix is byte-identical to pre-v190 output.
    entity_setup_line = (
        '  "entity_setup": {"aliases": ["other names they go by"], '
        '"relationship": "how they are related to you", "living": true | '
        'false, "type": "one of the entity types", "maps_to": "the slug of '
        'the existing page this really is", "start_focus": true | false} '
        "| null,\n"
        if shape.entity_stage is not None
        else ""
    )
    entity_setup_note = (
        '- "entity_setup" is null on every turn except one where the USER '
        "supplied or changed who this is — other names they go by, how they "
        "are related to you, whether they are living, what kind of thing "
        "this is, that this is really an existing page, or a yes to starting "
        "a focus. Include only the keys they actually gave you. Never invent "
        "a value, never fill it to look decisive.\n"
        if shape.entity_stage is not None
        else ""
    )
    # arc-walk-interaction (v193, Design §C): the one additive
    # "answered_question_id" output key exists ONLY when the caller set
    # shape.arc_stage; absent it, line and note alike stay out, so an
    # ordinary turn's appendix is byte-identical to pre-v193 output.
    answered_question_line = (
        '  "answered_question_id": "the agenda question id this answer '
        'addressed" | null,\n'
        if shape.arc_stage is not None
        else ""
    )
    answered_question_note = (
        '- "answered_question_id" is null on every turn except one where the '
        "USER's answer addressed a DIFFERENT question from the agenda than "
        "the one on the table; then it is that question's exact id from the "
        "agenda and nothing else. When an answer covers two, name the primary "
        "one only. Never invent an id, never name one that isn't on the "
        "agenda.\n"
        if shape.arc_stage is not None
        else ""
    )
    # timeline-chronology (v195, Design §D): the one additive "placed" output
    # key exists ONLY when the caller set shape.timeline_stage; absent it,
    # line and note alike stay out, so an ordinary turn's appendix is
    # byte-identical to pre-v195 output.
    placed_line = (
        '  "placed": {"best": "the EDTF date", "earliest": "the earliest it '
        'could be", "latest": "the latest it could be", "granularity": "day | '
        'month | season | year | range | era", "confidence": "certain | '
        f'approximate | inferred | conjectural", "basis": "{_BASIS_VOCABULARY}"'
        ', "anchors": ["the landmark '
        'keys you used"]} | null,\n'
        if shape.timeline_stage is not None or shape.reading_room_stage is not None
        else ""
    )
    placed_note = (
        '- "placed" is null on every turn except one where the USER gave you '
        "something that actually dates the moment. Record ONLY what they said "
        "— a date, an age, or a before/after against a landmark from ANCHORS — "
        "and never a year they did not supply. An interval is a finding, not a "
        'failure: bounds you are sure of beat a point you are not — "about '
        'preschool, three to five" is a real placement, not a miss. When they '
        "say they will find out, that is an ordinary answer: receive it, ask "
        'nothing more, and leave "placed" null. '
        "Never invent an anchor key that is not in ANCHORS.\n"
        if shape.timeline_stage is not None or shape.reading_room_stage is not None
        else ""
    )
    # landmarks (v197, Design §D): the one additive "landmark" output key
    # exists ONLY when the caller set shape.landmark_stage; absent it, line
    # and note alike stay out, so an ordinary turn's appendix is
    # byte-identical to pre-v197 output.
    landmark_line = (
        '  "landmark": {"domain": "the landmark domain you asked about", '
        '"label": "what it is called", "date": {"best": "the EDTF date", '
        '"granularity": "day | month | season | year | range | era", '
        '"confidence": "certain | approximate | inferred | conjectural", '
        f'"basis": "{_BASIS_VOCABULARY}"}}, '
        '"span": {"start": {…}, "end": {…}}, "skipped": true | false, '
        '"none": true | false} | null,\n'
        if shape.landmark_stage is not None or shape.reading_room_stage is not None
        else ""
    )
    landmark_note = (
        '- "landmark" is null on every turn except one where the USER actually '
        "gave you a landmark. Use the domain you were asking about and put "
        "what they said in that rung's own key — the town in \"city\", the "
        "street in \"address\", the school or the place in \"label\". A date "
        "or a span only when they supplied one. A coarse answer is an answer: "
        '"the eighties" is a real span, not a miss. When they skip, it is '
        '{"domain": "<the domain>", "skipped": true}. When they say it never '
        'happened at all — "I never served", "we didn\'t have children" — '
        'that is a real, finished answer: {"domain": "<the domain>", "none": '
        "true}. Never invent a place, a date, a name, or a domain you were "
        "not given.\n"
        if shape.landmark_stage is not None or shape.reading_room_stage is not None
        else ""
    )
    return (
        "\n\n## OUTPUT FORMAT (runtime contract — reply with JSON only)\n\n"
        "Reply with a single JSON object and nothing else:\n\n"
        "{\n"
        '  "message": "the one Telegram message, plain text",\n'
        '  "followup_question": "the question you asked, verbatim, or null",\n'
        '  "question_free": true | false,\n'
        '  "user_invited_question": true | false,\n'
        '  "held_question_id": "the [qid] you asked from ASKING_SUPPLY, or null",\n'
        f"{placement_line}"
        f"{focus_setup_line}"
        f"{entity_setup_line}"
        f"{answered_question_line}"
        f"{placed_line}"
        f"{landmark_line}"
        '  "rolling_summary": "a short running summary of this session",\n'
        '  "insight_receipts": 0,\n'
        '  "extracted": {"facts": [], "entities": [], "candidate_ideas": [], '
        '"mirror_responses": []}\n'
        "}\n\n"
        f"- {question_rule}\n"
        '- "user_invited_question" is your own judgment of whether the '
        "user's latest message invites another question at all — true for "
        "an explicit request or open-ended receptivity, false otherwise, "
        "and true whenever you are genuinely unsure.\n"
        '- "held_question_id" is the ASKING_SUPPLY qid of the question you '
        "asked, only when you actually asked one from that block; null "
        "otherwise. Never a qid that wasn't actually offered there.\n"
        f"{placement_note}"
        f"{focus_setup_note}"
        f"{entity_setup_note}"
        f"{answered_question_note}"
        f"{placed_note}"
        f"{landmark_note}"
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
    # ADR 0016 (issue #168, asking-supply): additive fields — absent on any
    # generation from before this PR, or from an overlay that hasn't caught
    # up, degrade to "no invitation, no held qid" (the pre-existing discard
    # behavior), never an error.
    held_question_id = data.get("held_question_id")
    held_question_id = held_question_id.strip() if isinstance(held_question_id, str) else None
    return {
        "message": message,
        "followup_question": followup_text or None,
        "question_free": bool(data.get("question_free", not followup_text)),
        "user_invited_question": bool(data.get("user_invited_question", False)),
        "held_question_id": held_question_id or None,
        "placement": _parse_placement(data.get("placement")),
        "focus_setup": _parse_focus_setup(data.get("focus_setup")),
        "entity_setup": _parse_entity_setup(data.get("entity_setup")),
        "answered_question_id": _parse_answered_question_id(
            data.get("answered_question_id")
        ),
        "placed": _parse_placed(data.get("placed")),
        "landmark": _parse_landmark(data.get("landmark")),
        "rolling_summary": summary.strip() if isinstance(summary, str) else None,
        "insight_receipts": int(receipts) if isinstance(receipts, int) else 0,
        "extracted": extracted if isinstance(extracted, dict) else {},
    }


_PLACEMENT_CATEGORY_MAX_CHARS = 8


def _parse_placement(raw: object) -> dict | None:
    """Structural layer of the additive ``placement`` field (Design §A.1,
    question-candidate-placement-aside / issue #181).

    Accepts only an object with exactly the key ``category`` whose value is
    a non-empty string of at most 8 characters after ``.strip()``;
    uppercases it. Anything else — missing, ``null``, a bare string, extra
    keys, wrong type — degrades to ``None``, exactly as ``held_question_id``
    degrades above: never an error. This function owns no roster and
    performs no membership check — closed-roster validation is
    ``question_candidate.validate_placement``'s job.
    """
    if not isinstance(raw, dict) or set(raw) != {"category"}:
        return None
    category = raw["category"]
    if not isinstance(category, str):
        return None
    category = category.strip()
    if not category or len(category) > _PLACEMENT_CATEGORY_MAX_CHARS:
        return None
    return {"category": category.upper()}


#: focus-onboarding-context (v189, Design §B.1): the closed key set of the
#: additive ``focus_setup`` object. The VALUES' vocabularies (roadmap focus
#: types, the relationship list) are deliberately NOT known here —
#: ``focus_candidate.validate_focus_setup`` owns those, exactly as
#: ``question_candidate.validate_placement`` owns the category roster.
_FOCUS_SETUP_KEYS = frozenset({"objective", "type", "relationship", "living", "label"})
_FOCUS_SETUP_TEXT_MAX_CHARS = 500


def _parse_focus_setup(raw: object) -> dict | None:
    """Structural layer of the additive ``focus_setup`` field (Design §B.1,
    focus-onboarding-context / v189).

    Accepts only an object whose keys are a SUBSET of
    ``{objective, type, relationship, living, label}`` — all five optional,
    because a turn carries only what the person actually supplied. Each
    string value is stripped and must be non-empty and at most 500
    characters; ``living`` must be a real ``bool`` (never ``0``/``1``/
    ``"yes"``, which JSON makes easy to emit by accident). An individually
    invalid value is dropped; a non-object, an unknown key, or an object
    that ends up empty degrades to ``None`` — never an error, exactly as
    ``held_question_id`` and ``placement`` degrade above.

    This function owns no vocabulary and performs no membership check:
    closed validation is ``focus_candidate.validate_focus_setup``'s job.
    """
    if not isinstance(raw, dict) or not set(raw) <= _FOCUS_SETUP_KEYS:
        return None
    parsed: dict[str, object] = {}
    for key in ("objective", "type", "relationship", "label"):
        if key not in raw:
            continue
        value = raw[key]
        if not isinstance(value, str):
            continue
        value = value.strip()
        if value and len(value) <= _FOCUS_SETUP_TEXT_MAX_CHARS:
            parsed[key] = value
    living = raw.get("living")
    if isinstance(living, bool):
        parsed["living"] = living
    return parsed or None


#: entity-identity-context (v190, Design §B.1): the closed key set of the
#: additive ``entity_setup`` object. The VALUES' vocabularies (the entity
#: types, the relationship list, which slugs actually exist in the roster)
#: are deliberately NOT known here — ``entity_candidate.validate_entity_setup``
#: owns those, exactly as ``question_candidate.validate_placement`` owns the
#: category roster and ``focus_candidate.validate_focus_setup`` owns the focus
#: vocabularies.
_ENTITY_SETUP_KEYS = frozenset(
    {"aliases", "relationship", "living", "type", "maps_to", "start_focus"}
)
_ENTITY_SETUP_TEXT_MAX_CHARS = 500
_ENTITY_SETUP_MAX_ALIASES = 32


def _parse_entity_setup(raw: object) -> dict | None:
    """Structural layer of the additive ``entity_setup`` field (Design §B.1,
    entity-identity-context / v190).

    Accepts only an object whose keys are a SUBSET of
    ``{aliases, relationship, living, type, maps_to, start_focus}`` — all six
    optional, because a turn carries only what the person actually supplied.
    Each string value is stripped and must be non-empty and at most 500
    characters; ``aliases`` must be a list whose non-empty trimmed string
    entries survive (at most 32 of them, so a runaway generation cannot
    balloon a turn record); ``living`` and ``start_focus`` must be real
    ``bool``s (never ``0``/``1``/``"yes"``, which JSON makes easy to emit by
    accident). An individually invalid value is dropped; a non-object, an
    unknown key, or an object that ends up empty degrades to ``None`` — never
    an error, exactly as ``held_question_id``, ``placement`` and
    ``focus_setup`` degrade above.

    This function owns no vocabulary and performs no membership check: closed
    validation is ``entity_candidate.validate_entity_setup``'s job.
    """
    if not isinstance(raw, dict) or not set(raw) <= _ENTITY_SETUP_KEYS:
        return None
    parsed: dict[str, object] = {}
    for key in ("relationship", "type", "maps_to"):
        if key not in raw:
            continue
        value = raw[key]
        if not isinstance(value, str):
            continue
        value = value.strip()
        if value and len(value) <= _ENTITY_SETUP_TEXT_MAX_CHARS:
            parsed[key] = value
    aliases = raw.get("aliases")
    if isinstance(aliases, list):
        cleaned = [
            item.strip()
            for item in aliases
            if isinstance(item, str)
            and item.strip()
            and len(item.strip()) <= _ENTITY_SETUP_TEXT_MAX_CHARS
        ]
        if cleaned:
            parsed["aliases"] = cleaned[:_ENTITY_SETUP_MAX_ALIASES]
    for flag in ("living", "start_focus"):
        value = raw.get(flag)
        if isinstance(value, bool):
            parsed[flag] = value
    return parsed or None


#: arc-walk-interaction (v193, Design §C.1): the additive
#: ``answered_question_id`` field is a bank question id — ``A14``, ``G5c`` —
#: so the structural cap is short. WHICH ids are legitimate is deliberately
#: NOT known here: ``arc_walk.validate_answered_question_id`` owns exact
#: membership in the episode's own plan, exactly as
#: ``question_candidate.validate_placement`` owns the category roster.
_ANSWERED_QUESTION_ID_MAX_CHARS = 16


def _parse_answered_question_id(raw: object) -> str | None:
    """Structural layer of the additive ``answered_question_id`` field
    (Design §C.1, arc-walk-interaction / v193).

    Accepts only a non-empty string of at most 16 characters after
    ``.strip()``. Anything else — missing, ``null``, a number, an object, a
    list, a 17-character value — degrades to ``None``, exactly as
    ``held_question_id``, ``placement``, ``focus_setup`` and ``entity_setup``
    degrade above: never an error.

    This function owns no plan and performs no membership check.
    """
    if not isinstance(raw, str):
        return None
    value = raw.strip()
    if not value or len(value) > _ANSWERED_QUESTION_ID_MAX_CHARS:
        return None
    return value


#: timeline-chronology (v195, Design §D): the additive ``placed`` field is a
#: date record or a deferral. The keys and their lengths are structural facts;
#: WHICH granularity/confidence/basis values are legitimate, whether the EDTF
#: parses, and whether the anchors were ever offered are deliberately NOT
#: known here — ``timeline_interaction.validate_placed`` owns all of that,
#: exactly as ``arc_walk.validate_answered_question_id`` owns plan membership.
_PLACED_KEYS = frozenset({
    "best", "earliest", "latest", "granularity", "confidence", "basis",
    "anchors", "provenance",
})
_PLACED_TEXT_MAX_CHARS = 32
_PLACED_MAX_ANCHORS = 6
_PLACED_ANCHOR_MAX_CHARS = 64


def _parse_placed(raw: object) -> dict | None:
    """Structural layer of the additive ``placed`` field.

    Accepts an object whose keys are a non-empty subset of
    :data:`_PLACED_KEYS` with short string values and a bounded anchor list.
    Anything else — missing, ``null``, a bare string, an extra key, a
    33-character granularity, and (since v196) ``{"deferred": true}`` —
    degrades to ``None``, exactly as
    ``held_question_id``, ``placement``, ``focus_setup``, ``entity_setup`` and
    ``answered_question_id`` degrade above: never an error.
    """
    if not isinstance(raw, dict) or not raw:
        return None
    if not set(raw) <= _PLACED_KEYS:
        return None
    parsed: dict = {}
    for key in ("best", "earliest", "latest", "granularity", "confidence", "basis"):
        value = raw.get(key)
        if value is None:
            continue
        if not isinstance(value, str):
            return None
        value = value.strip()
        if not value or len(value) > _PLACED_TEXT_MAX_CHARS:
            return None
        parsed[key] = value
    anchors = raw.get("anchors")
    if anchors is not None:
        if isinstance(anchors, str):
            anchors = [anchors]
        if not isinstance(anchors, list):
            return None
        cleaned = [item.strip() for item in anchors
                   if isinstance(item, str) and item.strip()
                   and len(item.strip()) <= _PLACED_ANCHOR_MAX_CHARS]
        if cleaned:
            parsed["anchors"] = cleaned[:_PLACED_MAX_ANCHORS]
    if not any(parsed.get(key) for key in ("best", "earliest", "latest")):
        return None
    return parsed


#: landmarks (v197, Design §D): the structural layer of the additive
#: ``landmark`` field. Keys are the union of the ladder rung names across the
#: question set plus the record's own fields — deliberately a CLOSED set here
#: and a second time in `landmarks_interaction.validate_landmark`, which
#: checks the domain against the question set the structural layer cannot see.
_LANDMARK_KEYS = frozenset({
    "domain", "label", "place", "subject", "date", "span", "skipped",
    "chain_complete",
    # v202 (family-landmark): `birth_order` is a free-text field alongside
    # label/place/subject, not a rung.
    "birth_order",
    # v204: the none terminal — "I never served", "no children". Structurally
    # a sibling of `skipped`; semantically its opposite (a skip is "not now",
    # a none is "there is nothing here"). Which domains may carry it is
    # `landmarks_interaction.domain_accepts_none`'s call, not this layer's.
    "none",
    # ladder rungs
    "year", "month", "day", "city", "address", "household",
    "name", "grades", "happened", "who", "what", "where", "branch",
    "relation", "living",
})

#: v202: rungs whose value is a real bool. `living` is TRI-STATE — absent is
#: UNKNOWN — and a stated ``False`` is a FACT, so it must survive the string
#: check below rather than degrading the whole record.
_LANDMARK_BOOL_KEYS = frozenset({"living"})
_LANDMARK_TEXT_MAX_CHARS = 160
_LANDMARK_DATE_KEYS = frozenset({
    "best", "earliest", "latest", "granularity", "confidence", "basis",
    "anchors", "provenance",
})
#: A provenance entry is a small flat object — `{"claim", "basis", "source"}`
#: and the witness's `{"name", "said_at"}` (`chronology.witness_provenance`).
#: Bounded exactly as the anchor list is: this is a structural layer, and a
#: structural layer that accepts an unbounded nested object is an injection
#: surface, not a parser.
_LANDMARK_MAX_PROVENANCE = 6
_LANDMARK_PROVENANCE_MAX_CHARS = 160


def _parse_landmark_date(raw: object) -> dict | None:
    """Structural layer of a landmark's date — interval AND warrant.

    v222 (B4): ``anchors`` and ``provenance`` were in :data:`_LANDMARK_DATE_KEYS`
    from the start — a payload carrying them PASSED the subset check — and then
    the copy loop below read only the six string keys and dropped them on the
    floor. A date the recorder had anchored on the person's birth and quoted
    ("you said you were about five") arrived at the writer as a bare interval,
    which is how the warrant went missing before anything even reached an argv.
    Both now survive, bounded the way `_parse_placed` bounds its anchors.
    """
    if not isinstance(raw, dict) or not raw or not set(raw) <= _LANDMARK_DATE_KEYS:
        return None
    parsed: dict = {}
    for key in ("best", "earliest", "latest", "granularity", "confidence", "basis"):
        value = raw.get(key)
        if value is None:
            continue
        if not isinstance(value, str):
            return None
        value = value.strip()
        if not value or len(value) > _PLACED_TEXT_MAX_CHARS:
            return None
        parsed[key] = value
    if not any(parsed.get(key) for key in ("best", "earliest", "latest")):
        return None
    anchors = raw.get("anchors")
    if anchors is not None:
        if isinstance(anchors, str):
            anchors = [anchors]
        if not isinstance(anchors, list):
            return None
        cleaned = [item.strip() for item in anchors
                   if isinstance(item, str) and item.strip()
                   and len(item.strip()) <= _PLACED_ANCHOR_MAX_CHARS]
        if cleaned:
            parsed["anchors"] = cleaned[:_PLACED_MAX_ANCHORS]
    provenance = raw.get("provenance")
    if provenance is not None:
        if isinstance(provenance, dict):
            provenance = [provenance]
        # Same shape rule the anchor list above uses: a warrant of the wrong
        # TYPE rejects the whole date, junk WITHIN the list is filtered.
        if not isinstance(provenance, list):
            return None
        cleaned = _parse_landmark_provenance(provenance)
        if cleaned:
            parsed["provenance"] = cleaned
    return parsed


def _parse_landmark_provenance(raw: list) -> list[dict]:
    """A bounded list of flat, short-stringed provenance objects."""
    out: list[dict] = []
    for item in raw:
        if not isinstance(item, dict) or not item:
            continue
        entry: dict = {}
        for key, value in item.items():
            if not isinstance(key, str) or not key.strip():
                continue
            # A provenance value is a short string or a plain number —
            # `{"source": "A12"}`, `{"confidence": 0.8}`. `bool` is an `int`,
            # so a stated flag passes here too.
            if isinstance(value, (int, float)):
                entry[key.strip()] = value
                continue
            if not isinstance(value, str):
                continue
            text = value.strip()
            if text and len(text) <= _LANDMARK_PROVENANCE_MAX_CHARS:
                entry[key.strip()] = text
        if entry:
            out.append(entry)
        if len(out) >= _LANDMARK_MAX_PROVENANCE:
            break
    return out


def _parse_landmark(raw: object) -> dict | None:
    """Structural layer of the additive ``landmark`` field.

    Accepts an object whose keys are a non-empty subset of
    :data:`_LANDMARK_KEYS`, with short string values, an optional date, and an
    optional ``{"start", "end"}`` span. Anything else — missing, ``null``, a
    bare string, an extra key, an over-long label — degrades to ``None``,
    exactly as every other additive field degrades: never an error. The
    DOMAIN is not checked here; that is
    `landmarks_interaction.validate_landmark`'s job, because only the question
    set knows the closed domain list.
    """
    if not isinstance(raw, dict) or not raw:
        return None
    if not set(raw) <= _LANDMARK_KEYS:
        return None
    parsed: dict = {}
    for key, value in raw.items():
        if key in ("date", "span", "skipped", "chain_complete", "none"):
            continue
        if key in _LANDMARK_BOOL_KEYS and isinstance(value, bool):
            parsed[key] = value
            continue
        if value is True:
            parsed[key] = True
            continue
        if not isinstance(value, str):
            return None
        text = value.strip()
        if not text or len(text) > _LANDMARK_TEXT_MAX_CHARS:
            return None
        parsed[key] = text
    date = _parse_landmark_date(raw.get("date"))
    if date is not None:
        parsed["date"] = date
    span = raw.get("span")
    if isinstance(span, dict) and set(span) <= {"start", "end"}:
        bounds = {}
        for bound in ("start", "end"):
            value = _parse_landmark_date(span.get(bound))
            if value is not None:
                bounds[bound] = value
        if bounds:
            parsed["span"] = bounds
    if raw.get("skipped") is True:
        parsed["skipped"] = True
    if raw.get("none") is True:
        parsed["none"] = True
    if raw.get("chain_complete") is True:
        parsed["chain_complete"] = True
    if not parsed.get("domain"):
        return None
    return parsed


def parse_closing_output(raw: object) -> dict | None:
    """Parse the structured close output; None when it is unusable.

    ADR 0014 (issue #163): the closing model emits ONLY
    ``{"takeaway_prose": str, "hook": str|null}`` — never the free-form
    ``{"message": ...}`` shape ordinary turns use (``parse_turn_output``,
    above). Same fence-tolerance convention (a ```json fence is tolerated,
    nothing looser), and ``_valid_message`` is the single authority for "is
    this renderable text" on BOTH paths (recurring-defect doctrine — one
    structural-sanity check, not a forked copy).

    Deliberately no raw-text fallback: the pre-#163 behavior tried
    ``_valid_message(generated)`` directly when JSON parsing failed
    entirely, which is exactly the gap the incident exploited — a close
    that isn't valid structured JSON is a malformed generation full stop,
    and malformed generations degrade to silence (never deliver unparsed
    text).
    """
    if not isinstance(raw, str):
        return None
    try:
        data = json.loads(_strip_fences(raw))
    except (ValueError, TypeError):
        return None
    if not isinstance(data, dict):
        return None
    prose = _valid_message(data.get("takeaway_prose"))
    if prose is None:
        return None
    hook = data.get("hook")
    hook_text = hook.strip() if isinstance(hook, str) else None
    return {"takeaway_prose": prose, "hook": hook_text or None}


def _question_sentences(text: str) -> list[str]:
    """Question sentences per the shared lint engine's own heuristics.

    Imported from conversation_lints rather than re-implemented: the
    echoed-question stripping rule (a quoted span containing '?' is the
    USER's question, not ours) is exactly the subtlety a forked copy would
    get wrong.
    """
    stripped = conversation_lints._strip_echoed_questions(text)
    return [s for s in conversation_lints._split_sentences(stripped) if conversation_lints._is_question(s)]


def session_prior_asks(session: dict) -> list[list[str]]:
    """Every earlier lifehug turn's asks, oldest first (v201, lifehug#206).

    The input `lint_outgoing`'s repetition check wants. Derived from the
    session's own turns through `conversation_lints.asks_in`, never
    re-implemented here.
    """
    return [
        conversation_lints.asks_in(str(turn.get("text") or ""))
        for turn in (session.get("turns") or [])
        if isinstance(turn, dict) and turn.get("role") == "lifehug"
    ]


def lint_outgoing(
    message: str,
    *,
    question_allowed: bool,
    is_reply_to_substantive: bool = True,
    is_closing: bool = False,
    prior_asks: Sequence[Sequence[str]] = (),
    config: dict | None = None,
) -> tuple[list[str], int]:
    """Return (blocking lint ids, advisory finding count) for one message.

    The checks themselves live in ``conversation_lints`` (single authority,
    config from ``evals/lints.yaml`` — including the ``cap.turn_chars``
    length cap, which this module deliberately does NOT pin independently).

    ``is_closing`` (issue #139, pure-chat wave) additionally blocks banned
    closing meta-phrases ("leave it here", "for now", ...) via
    ``conversation_lints.lint_closing_phrases`` — the declarative-close
    doctrine's other half, checked ONLY on closing turns (never folded
    into the turn-wide ``banned_phrases`` lint, since these same words are
    often fine mid-conversation). The "no question at all" half is already
    covered below by the existing ``question_allowed=False`` check that
    every closing call already makes.
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
    if is_closing:
        blocking.extend(
            f["lint"] for f in conversation_lints.lint_closing_phrases(message, config=config)
        )
    # v201 (lifehug#206) — behavior.md rule 13's structural floor. Skipped
    # on closing turns, which ask nothing at all, and a no-op whenever the
    # caller passes no prior asks (every pre-v201 call site, byte-identical).
    if prior_asks and not is_closing:
        blocking.extend(
            f["lint"] for f in conversation_lints.lint_repetition(
                message, prior_asks, config=config
            )
        )
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
    target-th exchange, and every one after it, simply receives and pays
    out with no question — the budget governs OUR initiative silently
    (pure-chat wave, issue #139: there is no dedicated "offer to stop"
    turn distinct from ordinary question-free receiving; reply-is-consent
    means the budget needs no announcement). Past the target we keep
    receiving for as long as the user keeps going — the target governs OUR
    initiative only, never the user's. The actual close, when it comes, is
    a separate, later, declarative event (``close_session_now`` /
    ``_deliver_closing`` — behavior.md rule 8), never signaled here.

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
    else:
        position = "past_target"
    question_allowed = planned_question is not None and user_turns < target
    return TurnShape(position, question_allowed, user_turns, target)


# --------------------------------------------------------------------------
# Session selection
# --------------------------------------------------------------------------


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
    root = conversation._chain_root(question_id)  # noqa: SLF001 — single authority, see conversation.py
    newest = None
    for summary in conversation.list_sessions(status="open", vault_root=vault_root):
        session_id = summary.get("session_id")
        if not session_id:
            continue
        try:
            doc = conversation.load_session(session_id, vault_root=vault_root)
        except (OSError, ValueError):
            continue
        if any(conversation._chain_root(qid) == root for qid in _session_question_ids(doc)):  # noqa: SLF001
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


def find_last_closed_session_for_channel(
    channel: str,
    *,
    mode: str | None = None,
    vault_root: str | Path | None = None,
) -> dict | None:
    """The most recently active CLOSED session for this channel (pure-chat
    wave, issue #139 — the reply-after-close routing rung, design K item
    6): when no session is currently open, a message still resumes the
    last subject THIS channel closed on rather than guessing ``new_story``.

    "Most recently active" is by last-turn timestamp (``_last_activity``,
    the same proxy the idle/janitor sweeps already use — ``close_session``
    itself writes no ``closed_at`` field, and adding one would break its
    idempotency contract, see the PR spec), not by session-id sort — an
    age-independent lookup by design ("same day or later").
    """
    newest: dict | None = None
    newest_activity: datetime | None = None
    for summary in conversation.list_sessions(status="closed", vault_root=vault_root):
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
        activity = _last_activity(doc)
        if activity is None:
            continue
        if newest_activity is None or activity > newest_activity:
            newest = doc
            newest_activity = activity
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


def _detect_declined_held_question(session: dict, user_turn_index: int) -> str | None:
    """Issue #168 / ADR 0016, Scope 4's deterministic decline rule.

    The turn immediately before ``user_turn_index`` asked a held question
    from asking_supply (``role: lifehug`` + ``asked_from_supply: true``) IFF
    this user turn's own ``question_id`` doesn't match that held qid (a
    different qid, or none at all): that held question was declined —
    moved past, not engaged. Returns the declined qid, or None when there
    is nothing to detect (no preceding lifehug turn, it wasn't a held ask,
    or the user turn actually engaged it).
    """
    turns = session.get("turns") or []
    if user_turn_index <= 0 or user_turn_index >= len(turns):
        return None
    prior = turns[user_turn_index - 1]
    if not isinstance(prior, dict) or prior.get("role") != "lifehug" or not prior.get("asked_from_supply"):
        return None
    held_qid = prior.get("question_id")
    if not held_qid:
        return None
    current = turns[user_turn_index]
    if not isinstance(current, dict):
        return str(held_qid)
    if str(current.get("question_id") or "") == str(held_qid):
        return None  # engaged — not declined
    return str(held_qid)


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


def _parse_router_output(
    raw: object, *, valid_targets: frozenset[str] | None = None
) -> tuple[str, float, str | None] | None:
    """Parse router.md's ``{"intent": ..., "confidence": ..., "target": ...}``
    schema. ``target`` is additive (issue #169, ADR 0017 — the thread
    binder): strict — it must be a roster id from ``valid_targets``, the
    literal string ``"new"``, or ``null``; anything else (a hallucinated
    id, wrong type, or any value at all when ``valid_targets`` is None —
    no roster was given, so no binding judgment applies) becomes ``None``
    rather than discarding the whole parse. The classified ``intent`` is
    never dropped for an invalid ``target`` (contract, Scope 4).

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
    target = data.get("target")
    target_out_of_roster = (
        isinstance(target, str) and valid_targets is not None
        and target != "new" and target not in valid_targets
    )
    if valid_targets is None or not isinstance(target, str) or target_out_of_roster:
        target = None
    return intent, confidence, target


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
    threads: list | None = None,
) -> dict:
    """Classify one inbound message per router.md; never mutates anything.

    Returns ``{"intent", "confidence", "source", "action", "target",
    "pending_question_id", "open_session_id", "reopen_session_id"}`` —
    always, and always with exit-0 semantics for the CLI wrapper
    (``cmd_route`` in ``lifehug.py``): a provider that is not ready, a
    malformed model reply, or a below-threshold classification all resolve
    through the deterministic default rule below rather than raising.

    ``reopen_session_id`` (issue #139, pure-chat wave, design K item 6) is
    the most-recently-CLOSED session on this channel when no session is
    currently open — never an append target (a closed session's store
    invariant forbids appending to it by design), but the subject a
    ``continue_session`` result should seed a FRESH session from, exactly
    like the platform's thread-composer pattern for a closed thread. A
    reply landing in that gap is never guessed as an unrelated
    ``new_story`` — see the Reply-after-close rule in ``router.md``.

    ``threads`` (issue #169, ADR 0017 — the thread binder, additive) is an
    optional bounded roster passed straight through to
    ``build_router_prompt``; ``target`` in the result reflects the
    model's own binding judgment (a roster id, ``"new"``, or ``None``)
    ONLY when the model's classification was itself accepted (``source ==
    "model"``) — any fallback path is honestly "no binding judgment",
    never a guess. OSS's single-open-session model has nothing to bind
    multiple candidates INTO today, so this is a pass-through: the value
    is reported, never consumed to redirect routing (ADR 0017 records
    this — the hosted platform is the first full consumer).

    Injectable collaborators (``ai_call`` / ``status_resolver`` /
    ``prompt_builder`` / ``rotation`` / ``open_session``) mirror the turn
    engine's own testing seam.
    """
    vault_root = vault_root if vault_root is not None else VAULT_ROOT
    manifest = _manifest()
    threshold = manifest.get("knob.router_confidence_threshold")
    threshold = float(threshold) if isinstance(threshold, (int, float)) else 0.7
    reference = now or _now()

    if rotation is None:
        from lifehug_core import ROTATION_FILE  # noqa: PLC0415

        rotation = read_json(ROTATION_FILE, default={}) or {}
    pending_question_id = rotation.get("last_question_id") or None

    if open_session is None:
        open_session = find_open_session_for_channel(
            channel, vault_root=vault_root, manifest=manifest, now=reference
        )
    open_session_id = str(open_session["session_id"]) if open_session else None

    closed_session = None
    if open_session_id is None:
        closed_session = find_last_closed_session_for_channel(channel, vault_root=vault_root)
    reopen_session_id = str(closed_session["session_id"]) if closed_session else None
    same_day_reopen = False
    if closed_session is not None:
        closed_activity = _last_activity(closed_session)
        if closed_activity is not None:
            same_day_reopen = closed_activity.astimezone(timezone.utc).date() == reference.astimezone(timezone.utc).date()

    config = _safe_config()
    model = router_model(config)
    resolve_status = status_resolver or provider_status
    selected = resolve_status(model, probe=False)

    roster_ids = frozenset(
        candidate["id"]
        for candidate in (threads or [])
        if isinstance(candidate, dict) and isinstance(candidate.get("id"), str)
    ) if threads else None

    model_intent: str | None = None
    model_confidence: float | None = None
    model_target: str | None = None
    if getattr(selected, "ready", False):
        builder = prompt_builder or conversation.build_router_prompt
        payload = {
            "message": text,
            "session_open": open_session_id is not None,
            "pending_question_id": pending_question_id,
            "recently_closed": reopen_session_id is not None,
        }
        if threads:
            payload["threads"] = threads
        try:
            prompt = builder(payload)
            generated = (ai_call or call_ai)(prompt, model)
            parsed = _parse_router_output(generated, valid_targets=roster_ids)
        except Exception:  # noqa: BLE001 — a classify call is never capture
            parsed = None
        if parsed is None:
            _diagnostic("route_classify", "malformed_generation", open_session_id or "-")
        else:
            model_intent, model_confidence, model_target = parsed

    target: str | None = None
    if model_intent is not None and model_confidence is not None and model_confidence >= threshold:
        intent = model_intent
        confidence = model_confidence
        source = "model"
        target = model_target
        if intent == "new_story" and same_day_reopen:
            # Reply-after-close rule (design K item 6, owner ruling): a
            # same-day reply after a close is never an unrelated new
            # story — "they're not talking about something else." This is
            # a structural override, not a model judgment call — the
            # owner's ruling admits no ambiguity for the same-day case.
            intent = "continue_session"
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
        elif reopen_session_id:
            # Reopen a recently closed session (router.md unsure-fallback
            # step 3, issue #139): before guessing new_story, resume the
            # last subject this channel closed on — any age, "same day or
            # later" (this rung only fires when there is no live
            # classifier to weigh nuance, so resuming a known subject is
            # always safer than guessing new_story).
            intent = "continue_session"
            action = _ROUTER_ACTION_BY_INTENT[intent]
        else:
            # Terminal, per-runtime unsure-fallback (router.md step 4, OSS
            # side): report the model's best guess when there was one, else
            # new_story — either way, ask rather than guess.
            intent = model_intent if model_intent is not None else "new_story"
            action = "ask_user"

    return {
        "intent": intent,
        "confidence": round(float(confidence), 4),
        "source": source,
        "action": action,
        "target": target,
        "pending_question_id": pending_question_id,
        "open_session_id": open_session_id,
        "reopen_session_id": reopen_session_id if open_session_id is None else None,
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


# --------------------------------------------------------------------------
# The timeline seam on the answer path (v196, timeline-whispers-and-keystones)
# --------------------------------------------------------------------------


def _question_bank_text(vault_root: str | Path | None) -> str:
    """The bank as text, or "" — a bank we cannot read is simply a vault with
    no minted keystone questions, never an error on the answer path."""
    try:
        from vault_paths import read_vault_text, vault_data_path  # noqa: PLC0415
        root = Path(vault_root) if vault_root is not None else VAULT_ROOT
        return read_vault_text(
            vault_data_path("question_bank", vault_root=root, framework_system_dir=SYSTEM_DIR),
            vault_root=root,
        )
    except Exception:  # noqa: BLE001
        return ""


def timeline_item_for_turn(session: dict, question_id: str, *,
                           vault_root: str | Path | None = None) -> dict | None:
    """The timeline item this turn carries, or None — guarded.

    ONE lookup for both ways a keystone becomes a question: the day's question
    IS a minted keystone question (an exact `timeline_probe_index` hit), or the
    session's arc card carries a whisper. Gated on the one-per-conversation
    budget: once a turn in this session has raised the timeline, the next turn
    carries no item, so the rule holds structurally and the lint is the belt to
    that braces (`timeline_gates.one_per_conversation`).
    """
    try:
        import timeline_interaction  # noqa: PLC0415

        if timeline_interaction.timeline_asks_so_far(session) >= 1:
            return None
        index = timeline_interaction.timeline_probe_index(_question_bank_text(vault_root))
        return timeline_interaction.timeline_item_for_session(
            session, question_id=question_id, probe_index=index,
        )
    except Exception:  # noqa: BLE001 — a timeline problem never costs a turn
        return None


def _file_placement(item: dict, placed: dict, *, session_id: str,
                    question_id: str, question_text: str,
                    vault_root: str | Path | None = None) -> bool:
    """Run the package's own `timeline-place` for an accepted placement.

    The package NAMES the date, the host WRITES it (ADR 0018/0023/0024) — and
    on this path the host is the package's own CLI, invoked exactly as the
    Review lane invokes it. Never raises: the message is already delivered.

    `place_invocation` returns argv AND the stdin the command requires
    (`timeline_interaction.PlaceInvocation`); both are passed here. Running the
    argv without `input=` is what made every conversational date exit 1 into a
    silent `place_failed` (lifehug#223), and the vault is selected explicitly
    with `--vault-root` rather than by a working directory the CLI never reads.
    """
    try:
        import subprocess  # noqa: PLC0415

        import timeline_interaction  # noqa: PLC0415

        invocation = timeline_interaction.place_invocation(
            placed,
            source=str(item.get("source") or f"answers/{question_id}.md"),
            description=str(item.get("label") or question_text or question_id),
            period=str(item.get("period") or timeline_interaction.anchor_slug(item.get("anchor"))),
            # v215 (lifehug#228): the item's OWN key. `label` is the moment's
            # title, and hashing a title against a join that expects the
            # description filed a record that rendered nowhere — exit 0, and
            # the date the person named was gone. The clamp moved into
            # `place_invocation`, so there is one description length too.
            placement_key=str(item.get("placement_key") or ""),
        )
        if invocation is None:
            return False
        root = vault_root if vault_root is not None else VAULT_ROOT
        command = [sys.executable, str(SYSTEM_DIR / "lifehug.py")]
        if root is not None:
            command += ["--vault-root", str(root)]
        result = subprocess.run(  # noqa: S603
            [*command, *invocation.argv],
            input=invocation.stdin_text,
            capture_output=True, text=True, timeout=120,
            cwd=str(root) if root is not None else None,
        )
        if result.returncode != 0:
            _diagnostic("timeline_place", "place_failed", session_id)
            return False
        return True
    except Exception:  # noqa: BLE001
        _diagnostic("timeline_place", "place_failed", session_id)
        return False


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

    # Session-scoped decline memory (issue #168 / ADR 0016, Scope 4): if the
    # turn just before this user turn asked a HELD question (asking_supply
    # pick — asked_from_supply) and this user turn's own question_id doesn't
    # match it, the held question was declined — a simple deterministic
    # rule, never a model judgment call. Recorded before the prompt is built
    # so THIS turn's own asking_supply block already excludes it.
    declined_qid = _detect_declined_held_question(session, existing_index)
    if declined_qid:
        session = conversation.record_declined_questions(
            session_id, [declined_qid], vault_root=vault_root
        )

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
    # v196: the timeline seam. An item — a minted keystone question being
    # answered, or the week's whisper riding this session's arc card — is the
    # ONLY thing that puts the `placed` key in the output contract, so an
    # ordinary answer's prompt does not move by one byte.
    timeline_item = timeline_item_for_turn(session, question_id, vault_root=vault_root)
    if timeline_item is not None:
        import timeline_interaction as _ti  # noqa: PLC0415

        shape = replace(
            shape,
            timeline_stage=_ti.timeline_stage_for_session(session),
        )
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
    # ADR 0016 (issue #168, asking-supply): past target the blocking lint
    # amends from "no questions" to "no UNINVITED questions" — a question is
    # permitted there IFF the model declared user_invited_question AND the
    # qid it asked is actually present in this session's asking_supply
    # selection (never trusted on the model's say-so alone). Within target,
    # behavior is unchanged (shape.question_allowed already covers it) — the
    # held-question option is just another way to fill the one question
    # slot. asking_supply_question_ids is resolved lazily (only when the
    # model actually named a held_question_id) so the common ordinary-turn
    # path pays no extra cost.
    held_id = parsed.get("held_question_id")
    asking_supply_ids = conversation.asking_supply_question_ids(session) if held_id else frozenset()
    hatch_honored = bool(parsed.get("user_invited_question")) and held_id in asking_supply_ids
    question_allowed = (shape.question_allowed or hatch_honored) and not parsed["question_free"]
    blocking, advisory = lint_outgoing(
        message,
        question_allowed=question_allowed,
        prior_asks=session_prior_asks(session),
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
    asked_from_supply = False
    if question_allowed and held_id and held_id in asking_supply_ids:
        # A held pick, not a delivery (contract, Scope 3 / consumption
        # semantics precedent): no mint, no rotation mutation, no queue/
        # ledger write — the bank already has this question; the reply
        # files against it through the ordinary turn-chain below.
        followup_id = held_id
        asked_from_supply = True
    elif question_allowed and parsed["followup_question"]:
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
    if asked_from_supply:
        lifehug_turn["asked_from_supply"] = True
    # v196: the placement rides the turn it was named on — `placed` is what
    # `timeline_interaction.precision_so_far` reads, and `timeline_probe_id`
    # is what makes "at most one timeline ask per conversation" checkable
    # without a new state file.
    placed_record = None
    if timeline_item is not None:
        lifehug_turn["timeline_probe_id"] = str(timeline_item.get("question_id") or "")
        try:
            import timeline_interaction as _ti  # noqa: PLC0415

            placed_record = _ti.answer_timeline_probe(timeline_item, parsed["placed"])
        except Exception:  # noqa: BLE001 — never costs a delivered turn
            placed_record = None
        if placed_record:
            lifehug_turn["placed"] = placed_record
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
    if placed_record and timeline_item is not None:
        _file_placement(
            timeline_item, placed_record, session_id=session_id,
            question_id=question_id, question_text=question_text,
            vault_root=vault_root,
        )
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
        message, question_allowed=question_allowed,
        prior_asks=session_prior_asks(session), config=_lints_config(),
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


def is_janitor_expired(session: dict, *, manifest: dict, now: datetime | None = None) -> bool:
    """Mode-independent safety net for abandoned conversation-mode sessions
    (design §D, Chats-per-Focus, 2026-08-12): day rollover + user
    transitions are the real close lifecycle now, not a timer — this sweep
    is a 36h-class janitor, no user-facing role. ``knob.janitor_idle_hours``
    replaces the old per-mode idle knobs for ``--expired``/the inline
    per-turn sweep; ``chat_idle_timeout_minutes``/``conversation_idle_timeout_minutes``
    (``is_idle_expired`` above) stay in force for "is this open session still
    current" continuation checks, raised to day-scale."""
    moment = _last_activity(session)
    if moment is None:
        return False
    reference = now or _now()
    hours = _knob(manifest, "knob.janitor_idle_hours", 36)
    return reference - moment >= timedelta(hours=hours)


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
    hook: str | None = None
    delivered = False
    status, detail = STATUS_SKIPPED, "no_close_message"

    if user_turns >= 2:
        status, detail, takeaway, hook = _deliver_closing(
            session,
            state_path=state_path,
            channel=channel,
            ai_call=ai_call,
            telegram_send=telegram_send,
            status_resolver=status_resolver,
            prompt_builder=prompt_builder,
            vault_root=vault_root,
            close_reason=reason,
        )
        delivered = status == STATUS_CONFIRMED
        if detail == "starved_fallback_turn":
            # ADR 0015: the builder starved (no user turns, no rolling
            # summary — structurally shouldn't happen given user_turns >= 2
            # above, but the engine still honors its own degradation table
            # defensively) and this was a live/budget-reached closing beat,
            # not a sweep. The engine sent an ordinary reply instead of a
            # close and the close itself is deferred — the session stays
            # OPEN; it does not close today.
            return CloseOutcome(
                session_id,
                reason,
                silent=False,
                takeaway_delivered=False,
                status=status,
                detail=detail,
                filed=filed,
                user_turns=user_turns,
            )
    else:
        detail = "silent_no_nag"

    close = {
        "reason": reason,
        "takeaway": takeaway if delivered else "",
        "takeaway_delivered": delivered,
        "insight_receipts_count": receipts,
        "filed": list(filed),
    }
    # ADR 0014 (issue #163): the structured close's hook is persisted
    # additively, filed only alongside an actually-delivered takeaway — a
    # rejected/silent close carries no hook either (nothing was confirmed
    # to have happened for the next thread to continue from).
    if delivered and hook:
        close["hook"] = hook
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


def _deliver_starvation_fallback_turn(
    session: dict,
    *,
    channel: str,
    ai_call: Callable[[str, str], str] | None,
    telegram_send: Callable[[str], TelegramSendResult] | None,
    status_resolver: Callable[..., object] | None,
    vault_root: str | Path | None,
    session_id: str,
) -> bool:
    """ADR 0015 (issue #167): a starved, budget-reached closing beat still
    owes the person a real reply. Builds and sends an ORDINARY,
    question-free turn via ``conversation.build_turn_prompt`` — the same
    generation/lint/send shape ``run_post_answer_turn`` uses, never the
    closing path — so the person gets a genuine response instead of
    silence. The close itself was already deferred by the caller; this is
    purely best-effort on top of that: any failure here just means the
    fallback also goes silent, which is no worse than the close it
    replaced. Returns True only on a confirmed send.
    """
    model = conversation_model()
    resolve_status = status_resolver or provider_status
    selected = resolve_status(model, probe=False)
    if not getattr(selected, "ready", False):
        return False
    turns = session.get("turns") or []
    shape = TurnShape("past_target", False, _count_user_turns(session), 0)
    try:
        prompt = conversation.build_turn_prompt({"session": session}) + _output_contract_block(shape)
        generated = (ai_call or call_ai)(prompt, model)
    except Exception:  # noqa: BLE001 — a failed fallback is silence, not worse
        return False
    parsed = parse_turn_output(generated)
    if parsed is None:
        return False
    message = parsed["message"]
    blocking, _advisory = lint_outgoing(
        message, question_allowed=False,
        prior_asks=session_prior_asks(session), config=_lints_config(),
    )
    if blocking:
        return False
    send_result = (telegram_send or send_telegram_result)(message)
    if send_result.status != "confirmed":
        return False
    try:
        _append_turn_resilient(
            session_id,
            {"role": "lifehug", "text": message, "channel": channel, "model": model},
            expected_turns=len(turns),
            vault_root=vault_root,
        )
    except Exception:  # noqa: BLE001 — already delivered
        _diagnostic("session_record", "session_write_failed", session_id)
    return True


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
    close_reason: str = "done",
) -> tuple[str, str, str, str | None]:
    """Generate/lint/send the closing takeaway; ledger it under close:{id}.

    A failed close is SILENT, never a fallback ack: the ack is the
    post-answer voice, and every answer in this session already got one turn
    or one ack of its own. Returning (status, detail, takeaway, hook) — ADR
    0014 (issue #163) adds ``hook``, the structured close's machine-only
    continuity label; it is None whenever the close wasn't confirmed-sent,
    or the model supplied none.

    ``close_reason`` (ADR 0015, issue #167) is ``close_session_now``'s own
    ``reason`` — the ONLY signal this function has for which of the
    starvation guard's two degradation classes applies when
    ``conversation.build_closing_prompt`` raises ``ConversationPromptError``:
    a sweep/idle/day close (``SWEEP_CLOSE_REASONS``) degrades to silence;
    every other reason is a live, budget-reached closing beat and degrades
    to an ordinary question-free turn instead (see the except clause below).
    """
    session_id = str(session["session_id"])
    key = close_key(session_id)
    entries = _state(state_path)["entries"]
    previous = entries.get(key, {})
    if previous.get("status") == STATUS_CONFIRMED:
        previous_hook = previous.get("hook")
        return (
            STATUS_CONFIRMED,
            "already_confirmed",
            str(previous.get("takeaway", "")),
            previous_hook if isinstance(previous_hook, str) else None,
        )
    if previous.get("status") == STATUS_AMBIGUOUS:
        return STATUS_AMBIGUOUS, "ambiguous_not_retried", "", None
    attempts = int(previous.get("attempts", 0) or 0) + 1
    turn_index = len(session.get("turns") or [])

    def ledger(
        status: str,
        reason: str,
        lint_ids: tuple[str, ...] = (),
        hook: str | None = None,
    ) -> None:
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
            hook=hook,
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
        return STATUS_SKIPPED, reason, "", None

    builder = prompt_builder or conversation.build_closing_prompt
    try:
        prompt = builder({"session": session}) + _closing_output_contract()
        generated = (ai_call or call_ai)(prompt, model)
    except conversation.ConversationPromptError:
        # ADR 0015 (issue #167): the builder refused — no user turns and no
        # rolling summary, nothing to close on. Degrade per the engine's
        # table, keyed on WHY this close was attempted, never by emitting a
        # starved prompt.
        _diagnostic("closing_generation", "starved_no_content", session_id)
        if close_reason in SWEEP_CLOSE_REASONS:
            ledger(STATUS_FAILED, "starved_no_content")
            return STATUS_FAILED, "starved_no_content", "", None
        # A live, budget-reached closing beat: never silence on a present
        # person. Send an ordinary, question-free reply instead of a close
        # and defer the close itself — "the thread lands another day."
        _deliver_starvation_fallback_turn(
            session,
            channel=channel,
            ai_call=ai_call,
            telegram_send=telegram_send,
            status_resolver=status_resolver,
            vault_root=vault_root,
            session_id=session_id,
        )
        ledger(STATUS_SKIPPED, "starved_fallback_turn")
        return STATUS_SKIPPED, "starved_fallback_turn", "", None
    except AIProviderError as exc:
        reason = _fixed_provider_reason(exc)
        ledger(STATUS_FAILED, reason)
        _diagnostic("closing_generation", reason, session_id)
        return STATUS_FAILED, reason, "", None
    except Exception:  # noqa: BLE001
        ledger(STATUS_FAILED, "generation_failed")
        _diagnostic("closing_generation", "generation_failed", session_id)
        return STATUS_FAILED, "generation_failed", "", None

    # ADR 0014 (issue #163): structured close — parse {takeaway_prose, hook}
    # ONLY; no raw-text fallback (see parse_closing_output's docstring for
    # why that fallback was the gap the incident exploited).
    parsed = parse_closing_output(generated)
    if parsed is None:
        ledger(STATUS_FAILED, "malformed_generation")
        _diagnostic("closing_generation", "malformed_generation", session_id)
        return STATUS_FAILED, "malformed_generation", "", None
    message = parsed["takeaway_prose"]
    hook = parsed["hook"]
    # Behavior rule 8: a close ends on the peak and STOPS — no trailing
    # question, no meta-framing that narrates the ending (issue #139), and
    # (ADR 0014) no leaked scaffolding — labeled fields, meta-commentary,
    # future-turn instructions, raw markdown. Lints run against
    # takeaway_prose ONLY — hook is machine-only and never rendered, so it
    # is never linted as channel text.
    blocking, _advisory = lint_outgoing(
        message, question_allowed=False, is_closing=True, config=_lints_config()
    )
    if blocking:
        ledger(STATUS_FAILED, "malformed_generation", tuple(blocking))
        _diagnostic("closing_lint", "malformed_generation", session_id)
        return STATUS_FAILED, "malformed_generation", "", None

    ledger(STATUS_AMBIGUOUS, "send_in_progress", hook=hook)
    send_result = (telegram_send or send_telegram_result)(message)
    if send_result.status == "confirmed":
        ledger(STATUS_CONFIRMED, "telegram_confirmed", hook=hook)
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
        return STATUS_CONFIRMED, "telegram_confirmed", message, hook
    if send_result.status == "ambiguous":
        ledger(STATUS_AMBIGUOUS, send_result.reason, hook=hook)
        _diagnostic("closing_send", send_result.reason, session_id)
        return STATUS_AMBIGUOUS, send_result.reason, "", None
    status = STATUS_SKIPPED if send_result.status == "not_attempted" else STATUS_FAILED
    ledger(status, send_result.reason)
    _diagnostic("closing_send", send_result.reason, session_id)
    return status, send_result.reason, "", None


def _closing_output_contract() -> str:
    # ADR 0014 (issue #163): structured close — the model emits ONLY this
    # JSON object. takeaway_prose is EVERYTHING the user will ever see;
    # hook is a compact machine-only continuity label, filed onto the
    # session's close block (close.hook) and never rendered. This replaces
    # the pre-#163 {"message": ..., "question_free": ...} contract for the
    # closing path specifically (ordinary turns keep that shape).
    return (
        "\n\nReply with a single JSON object and nothing else:\n"
        '{"takeaway_prose": "the complete closing message, plain text", '
        '"hook": "a compact label for the next thread, or null"}\n\n'
        "takeaway_prose is EVERYTHING the user will see — ONE woven "
        "declarative statement that ends on the peak and STOPS:\n"
        "  - No trailing question.\n"
        "  - No labeled fields (\"Hook for next time:\", \"Takeaway:\", "
        "\"For next time:\") — weave the hook into the prose naturally "
        "when there is one; never render it as its own line.\n"
        "  - No commentary on the conversation's quality or the author's "
        "own conversational behavior (\"I appreciated that you pushed "
        "back\", \"that made this useful\") — appreciate what they shared, "
        "never how they conversed.\n"
        "  - No instructions addressed to a future turn or session "
        "(\"next time, pick up wherever...\", \"no need to re-explain\") — "
        "continuity is the machine's job via the hook field below, not "
        "prose talking to the next session's model.\n"
        "  - No raw markdown emphasis (**like this**) — this channel never "
        "renders it.\n\n"
        "hook is a SEPARATE short label for the next thread, for MACHINE "
        "use only — it is never shown to the user, so it may restate the "
        "same continuity idea takeaway_prose already wove in, or be null "
        "when there isn't one.\n"
    )


def find_expired_open_sessions(
    *,
    vault_root: str | Path | None = None,
    manifest: dict | None = None,
    now: datetime | None = None,
) -> list[str]:
    """Session ids for every OPEN session past the janitor threshold.

    Pure discovery — deterministic, AI-free, no closing, no send: distinct
    from ``close_expired_sessions`` (which actually closes each one,
    generating and sending an AI takeaway where warranted). Issue #119's
    ``conversation-close --expired`` sweep entry point uses THIS to decide
    what to enqueue as durable jobs, keeping the discovery step itself free
    of AI calls; ``close_expired_sessions`` stays exactly as PR3 shipped it
    (the inline per-turn sweep's synchronous close, unchanged).

    "Expired" is the janitor's 36h-class ``knob.janitor_idle_hours``
    threshold as of design §D (Chats-per-Focus, 2026-08-12) — day rollover
    and user transitions are the real close lifecycle now; this sweep is
    only the safety net for abandoned conversation-mode sessions, no longer
    a user-facing timer.
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
        if is_janitor_expired(session, manifest=manifest, now=reference):
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
    """Lazy sweep: close every open session past the janitor threshold.

    No daemon and no cron change in this PR — the sweep runs at the top of
    every post-answer turn and on demand via ``conversation-close --expired``
    (the same subcommand #119's jobs builder enqueues). Design §D
    (2026-08-12) demotes this from a user-facing idle timer to a 36h-class
    janitor (``is_janitor_expired`` / ``knob.janitor_idle_hours``) — day
    rollover (``close_all_open_sessions`` below) and user transitions are
    the real close lifecycle.
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
        if not is_janitor_expired(session, manifest=manifest, now=reference):
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


def find_open_sessions(*, vault_root: str | Path | None = None) -> list[str]:
    """Every OPEN session id, regardless of idle age.

    Day rollover's pure discovery (design §D, Chats-per-Focus, 2026-08-12):
    the day owns the surface, not a timer — a session opened seconds ago
    still closes at rollover. Deterministic, AI-free, no closing, no send;
    distinct from ``find_expired_open_sessions`` (janitor-filtered).
    ``lifehug.py``'s ``conversation-close --day-rollover`` uses THIS to
    decide what to enqueue as durable jobs, mirroring how
    ``find_expired_open_sessions`` feeds ``--expired``.
    """
    vault_root = vault_root if vault_root is not None else VAULT_ROOT
    ids: list[str] = []
    for summary in conversation.list_sessions(status="open", vault_root=vault_root):
        session_id = summary.get("session_id")
        if session_id:
            ids.append(str(session_id))
    return ids


def close_all_open_sessions(
    *,
    vault_root: str | Path | None = None,
    state_path: Path | None = None,
    scores_path: Path | None = None,
    candidates_path: Path | None = None,
    ai_call: Callable[[str, str], str] | None = None,
    telegram_send: Callable[[str], TelegramSendResult] | None = None,
    status_resolver: Callable[..., object] | None = None,
    prompt_builder: Callable[[dict], str] | None = None,
) -> list[CloseOutcome]:
    """Day rollover: close EVERY open session — no idle filter (design §D).

    Mirrors ``close_expired_sessions`` exactly, minus the janitor filter;
    the closing-takeaway criterion is unchanged (>=2 user turns earns a
    takeaway, appended in-thread; fewer closes silently — ``close_session_now``'s
    existing rule, not re-decided here). This is the synchronous engine
    entry point for ``conversation-close --day-rollover``; ``lifehug.py``'s
    CLI wrapper enqueues one durable job per session instead of calling this
    directly, for operational parity with how ``--expired`` is transported
    (``_enqueue_expired_conversation_closes``).
    """
    state_path = state_path if state_path is not None else DELIVERY_STATE_FILE
    vault_root = vault_root if vault_root is not None else VAULT_ROOT
    scores_path = scores_path if scores_path is not None else ANSWER_SCORES_FILE
    manifest = _manifest()
    outcomes: list[CloseOutcome] = []
    for session_id in find_open_sessions(vault_root=vault_root):
        try:
            outcomes.append(
                close_session_now(
                    session_id,
                    reason="day_rollover",
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
        except Exception:  # noqa: BLE001 — one bad session never stalls rollover
            _diagnostic("day_rollover", "close_failed", str(session_id))
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
    if args.day_rollover:
        outcomes = close_all_open_sessions()
        if not outcomes:
            print("No open conversation sessions for day rollover.")
            return 0
        for outcome in outcomes:
            print(
                f"{outcome.session_id}: closed ({outcome.reason}; "
                f"{'silent' if outcome.silent else 'takeaway sent'}; {outcome.detail})"
            )
        return 0
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

    p = sub.add_parser(
        "close", help="Close one session now, sweep the janitor, or roll over the day"
    )
    p.add_argument("session_id", nargs="?")
    p.add_argument(
        "--expired", action="store_true",
        help="Close every session past the janitor threshold (knob.janitor_idle_hours)",
    )
    p.add_argument(
        "--day-rollover", action="store_true",
        help="Close every open session regardless of idle age (design §D day rollover)",
    )
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
