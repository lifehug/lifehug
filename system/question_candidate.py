#!/usr/bin/env python3
"""Pure runtime contract for the registered Question Candidate Interaction.

This module validates exact candidate/category/lifecycle facts, composes the
Interaction prompt, normalizes an untrusted model proposal, and revalidates a
decision against current revisions.  It performs no durable writes.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections.abc import Mapping

import conversation_lints
import interaction_registry

SCHEMA_VERSION = 1
PLACEMENT_CONFIDENCE_THRESHOLD = 0.8
CATEGORY_ROSTER_MAX = 64
VALID_ASSOCIATION_STAGES = frozenset({"before_answer", "during_answer", "after_answer"})
VALID_ANSWER_STATUSES = frozenset({"none", "held", "durable"})
VALID_REQUESTED_OUTCOMES = frozenset({"engage", "decline", "defer"})
VALID_TURN_KINDS = frozenset({"placement_only", "answer", "mixed"})
VALID_PLACEMENT_ACTIONS = frozenset({"resolved", "ask_now", "defer"})
VALID_STATUSES = frozenset(
    {"active", "needs_clarification", "complete", "declined", "deferred", "invalid"}
)
VALID_CANDIDATE_OUTCOMES = frozenset({"engaged", "answered", "declined", "deferred"})
REVISION_RE = re.compile(r"^sha256:[0-9a-f]{64}$")

_ANCHOR_KEYS = frozenset(
    {
        "schema_version",
        "candidate_id",
        "question",
        "source_revision",
        "candidate_revision",
    }
)
_CATEGORY_SOURCE_KEYS = frozenset(
    {"category_id", "label", "group", "qualifier", "focus_id", "focus_label"}
)
_CATEGORY_KEYS = _CATEGORY_SOURCE_KEYS | {"category_revision"}
_ROSTER_KEYS = frozenset({"schema_version", "roster_revision", "categories"})
_INPUT_KEYS = frozenset(
    {
        "schema_version",
        "candidate",
        "roster",
        "association_stage",
        "provisional_category_id",
        "latest_user_turn",
        "previous_placement_question",
        "conversation_context",
        "answer_status",
        "requested_outcome",
    }
)
_CONVERSATION_CONTEXT_KEYS = frozenset(
    {
        "profile",
        "record",
        "asking_supply",
        "session",
        "arc_card_current_intent",
        "previous_turn_summary",
        "turn_position",
        "applicable_rule_hints",
    }
)
_MODEL_OUTPUT_KEYS = frozenset(
    {
        "reply",
        "turn_kind",
        "placement_action",
        "category_id",
        "confidence",
        "placement_question",
    }
)


class QuestionCandidateError(ValueError):
    """Question Candidate input or proposal violated the closed contract."""


def canonical_revision(value: object) -> str:
    payload = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(payload).hexdigest()}"


def _object(value: object, *, name: str, keys: frozenset[str]) -> dict:
    if not isinstance(value, dict):
        raise QuestionCandidateError(f"{name} must be an object")
    actual = frozenset(value)
    if actual != keys:
        raise QuestionCandidateError(
            f"{name} keys invalid: missing={sorted(keys - actual)}, unknown={sorted(actual - keys)}"
        )
    return value


def _text(value: object, *, name: str, maximum: int) -> str:
    if not isinstance(value, str) or not value.strip():
        raise QuestionCandidateError(f"{name} must be a non-empty string")
    if len(value) > maximum:
        raise QuestionCandidateError(f"{name} exceeds {maximum} characters")
    return value


def _nullable_text(value: object, *, name: str, maximum: int) -> str | None:
    if value is None:
        return None
    return _text(value, name=name, maximum=maximum)


def _revision(value: object, *, name: str) -> str:
    if not isinstance(value, str) or not REVISION_RE.fullmatch(value):
        raise QuestionCandidateError(f"{name} must be sha256:<64 lowercase hex>")
    return value


def build_candidate_anchor(
    candidate_id: str, question: str, source_revision: str
) -> dict:
    candidate_id = _text(candidate_id, name="candidate_id", maximum=256)
    question = _text(question, name="question", maximum=20_000)
    source_revision = _text(source_revision, name="source_revision", maximum=512)
    source = {
        "candidate_id": candidate_id,
        "question": question,
        "source_revision": source_revision,
    }
    return {
        "schema_version": SCHEMA_VERSION,
        **source,
        "candidate_revision": canonical_revision(source),
    }


def _validate_candidate(value: object) -> dict:
    candidate = _object(value, name="candidate", keys=_ANCHOR_KEYS)
    if candidate["schema_version"] != SCHEMA_VERSION:
        raise QuestionCandidateError("candidate.schema_version must be 1")
    expected = build_candidate_anchor(
        candidate["candidate_id"], candidate["question"], candidate["source_revision"]
    )
    supplied = _revision(
        candidate["candidate_revision"], name="candidate.candidate_revision"
    )
    if supplied != expected["candidate_revision"]:
        raise QuestionCandidateError("candidate revision does not match exact anchor")
    return expected


def _category_source(value: Mapping[str, object], *, index: int) -> dict:
    focus_id = _nullable_text(
        value.get("focus_id"), name=f"categories[{index}].focus_id", maximum=256
    )
    focus_label = _nullable_text(
        value.get("focus_label"), name=f"categories[{index}].focus_label", maximum=512
    )
    if (focus_id is None) != (focus_label is None):
        raise QuestionCandidateError(
            f"categories[{index}] focus_id and focus_label must both be null or non-null"
        )
    return {
        "category_id": _text(
            value.get("category_id"),
            name=f"categories[{index}].category_id",
            maximum=64,
        ),
        "label": _text(
            value.get("label"), name=f"categories[{index}].label", maximum=512
        ),
        "group": _nullable_text(
            value.get("group"), name=f"categories[{index}].group", maximum=256
        ),
        "qualifier": _nullable_text(
            value.get("qualifier"), name=f"categories[{index}].qualifier", maximum=512
        ),
        "focus_id": focus_id,
        "focus_label": focus_label,
    }


def build_category_roster(categories: list[dict]) -> dict:
    if not isinstance(categories, list):
        raise QuestionCandidateError("categories must be a list")
    if not 1 <= len(categories) <= CATEGORY_ROSTER_MAX:
        raise QuestionCandidateError(
            f"categories must contain 1..{CATEGORY_ROSTER_MAX} complete entries"
        )
    normalized: list[dict] = []
    seen: set[str] = set()
    for index, value in enumerate(categories):
        if not isinstance(value, dict):
            raise QuestionCandidateError(f"categories[{index}] must be an object")
        actual = frozenset(value)
        if actual not in {_CATEGORY_SOURCE_KEYS, _CATEGORY_KEYS}:
            raise QuestionCandidateError(f"categories[{index}] keys are invalid")
        source = _category_source(value, index=index)
        if source["category_id"] in seen:
            raise QuestionCandidateError(
                f"duplicate category_id: {source['category_id']}"
            )
        seen.add(source["category_id"])
        category_revision = canonical_revision(source)
        if "category_revision" in value:
            supplied = _revision(
                value["category_revision"],
                name=f"categories[{index}].category_revision",
            )
            if supplied != category_revision:
                raise QuestionCandidateError(
                    f"categories[{index}] revision does not match category"
                )
        normalized.append({**source, "category_revision": category_revision})
    return {
        "schema_version": SCHEMA_VERSION,
        "roster_revision": canonical_revision(normalized),
        "categories": normalized,
    }


def _validate_roster(value: object) -> dict:
    roster = _object(value, name="roster", keys=_ROSTER_KEYS)
    if roster["schema_version"] != SCHEMA_VERSION:
        raise QuestionCandidateError("roster.schema_version must be 1")
    supplied = _revision(roster["roster_revision"], name="roster.roster_revision")
    canonical = build_category_roster(roster["categories"])
    if supplied != canonical["roster_revision"]:
        raise QuestionCandidateError(
            "roster revision does not match ordered categories"
        )
    return canonical


def validate_question_candidate_input(value: object) -> dict:
    payload = _object(value, name="input", keys=_INPUT_KEYS)
    if payload["schema_version"] != SCHEMA_VERSION:
        raise QuestionCandidateError("input.schema_version must be 1")
    candidate = _validate_candidate(payload["candidate"])
    roster = _validate_roster(payload["roster"])
    stage = payload["association_stage"]
    if stage not in VALID_ASSOCIATION_STAGES:
        raise QuestionCandidateError("association_stage is invalid")
    provisional = _nullable_text(
        payload["provisional_category_id"], name="provisional_category_id", maximum=64
    )
    ids = {entry["category_id"] for entry in roster["categories"]}
    if provisional is not None and provisional not in ids:
        raise QuestionCandidateError("provisional_category_id is outside the roster")
    latest = _nullable_text(
        payload["latest_user_turn"], name="latest_user_turn", maximum=50_000
    )
    previous = _nullable_text(
        payload["previous_placement_question"],
        name="previous_placement_question",
        maximum=2_200,
    )
    raw_context = payload["conversation_context"]
    conversation_context = None
    if raw_context is not None:
        raw_context = _object(
            raw_context,
            name="conversation_context",
            keys=_CONVERSATION_CONTEXT_KEYS,
        )
        conversation_context = {
            key: _nullable_text(
                raw_context[key],
                name=f"conversation_context.{key}",
                maximum=12_000 if key in {"record", "session"} else 4_000,
            )
            for key in sorted(_CONVERSATION_CONTEXT_KEYS)
        }
    answer_status = payload["answer_status"]
    if answer_status not in VALID_ANSWER_STATUSES:
        raise QuestionCandidateError("answer_status is invalid")
    requested = payload["requested_outcome"]
    if requested not in VALID_REQUESTED_OUTCOMES:
        raise QuestionCandidateError("requested_outcome is invalid")
    if latest is None and stage != "before_answer":
        raise QuestionCandidateError("a stage after before_answer requires a user turn")
    if stage == "before_answer" and answer_status == "durable":
        raise QuestionCandidateError("a durable answer cannot be before_answer")
    return {
        "schema_version": SCHEMA_VERSION,
        "candidate": candidate,
        "roster": roster,
        "association_stage": stage,
        "provisional_category_id": provisional,
        "latest_user_turn": latest,
        "previous_placement_question": previous,
        "conversation_context": conversation_context,
        "answer_status": answer_status,
        "requested_outcome": requested,
    }


def _manifest_number(name: str, fallback: float) -> float:
    manifest = interaction_registry.load_interaction_manifest("question_candidate")
    try:
        return float(manifest[name])
    except (KeyError, TypeError, ValueError):
        return fallback


def build_question_candidate_prompt(payload: dict) -> str:
    canonical = validate_question_candidate_input(payload)
    assets = [
        interaction_registry.compose_interaction_asset("question_candidate", path)
        for path in (
            "prompt/identity.md",
            "prompt/behavior.md",
            "prompt/examples.md",
            "prompt/turn-instructions.md",
        )
    ]
    threshold = _manifest_number(
        "knob.placement_confidence_threshold", PLACEMENT_CONFIDENCE_THRESHOLD
    )
    untrusted = {
        **canonical,
        "placement_confidence_threshold": threshold,
    }
    return (
        "\n".join(asset.rstrip() for asset in assets)
        + "\n\n<!-- runtime-boundary:untrusted-data -->\n"
        + "UNTRUSTED_DATA\n"
        + json.dumps(untrusted, ensure_ascii=False, sort_keys=True, indent=2)
        + "\nEND_UNTRUSTED_DATA\n"
    )


def _category(roster: dict, category_id: str | None) -> dict | None:
    return next(
        (
            entry
            for entry in roster["categories"]
            if entry["category_id"] == category_id
        ),
        None,
    )


def _placement_revision(candidate_revision: str, category: dict) -> str:
    return canonical_revision(
        {
            "candidate_revision": candidate_revision,
            "category_id": category["category_id"],
            "category_revision": category["category_revision"],
        }
    )


def _completion(
    *, answer_status: str, placement_resolved: bool, candidate_outcome: str | None
) -> dict:
    outcome_resolved = candidate_outcome in {"answered", "declined", "deferred"}
    complete = (
        answer_status == "durable"
        and placement_resolved
        and candidate_outcome == "answered"
    )
    return {
        "answer_durable": answer_status == "durable",
        "placement_resolved": placement_resolved,
        "outcome_resolved": outcome_resolved,
        "complete": complete,
    }


def _decision(
    payload: dict,
    *,
    status: str,
    candidate_outcome: str | None,
    category: dict | None = None,
    turn_kind: str | None = None,
    reply: str | None = None,
    placement_question: str | None = None,
) -> dict:
    candidate = payload["candidate"]
    placement_resolved = category is not None
    return {
        "schema_version": SCHEMA_VERSION,
        "status": status,
        "candidate_outcome": candidate_outcome,
        "candidate_id": candidate["candidate_id"],
        "candidate_revision": candidate["candidate_revision"],
        "source_revision": candidate["source_revision"],
        "association_stage": payload["association_stage"],
        "category_id": category["category_id"] if category else None,
        "category_revision": category["category_revision"] if category else None,
        "placement_revision": (
            _placement_revision(candidate["candidate_revision"], category)
            if category
            else None
        ),
        "answer_status": payload["answer_status"],
        "turn_kind": turn_kind,
        "reply": reply,
        "placement_question": placement_question,
        "completion": _completion(
            answer_status=payload["answer_status"],
            placement_resolved=placement_resolved,
            candidate_outcome=candidate_outcome,
        ),
    }


def _invalid(
    payload: dict, *, turn_kind: str | None = None, reply: str | None = None
) -> dict:
    return _decision(
        payload,
        status="invalid",
        candidate_outcome=None,
        turn_kind=turn_kind,
        reply=reply,
    )


def _proposal(raw: object) -> dict:
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise QuestionCandidateError("model output is not JSON") from exc
    return _object(raw, name="model_output", keys=_MODEL_OUTPUT_KEYS)


def lint_inherited_reply(
    text: str, *, is_reply_to_substantive: bool = False
) -> list[dict]:
    """Apply the inherited Conversation lint authority without duplicating it."""
    return conversation_lints.lint_turn(
        text,
        is_reply_to_substantive=is_reply_to_substantive,
        seam_ok=False,
    )


def _question_is_valid(question: str, *, reply: str) -> bool:
    if question.count("?") != 1 or not question.rstrip().endswith("?"):
        return False
    if reply.count(question) != 1:
        return False
    return reply.count("?") == 1


def parse_question_candidate_output(raw: object, *, payload: dict) -> dict:
    """Normalize an untrusted proposal into portable coordination facts."""
    canonical = validate_question_candidate_input(payload)
    requested = canonical["requested_outcome"]
    if requested in {"decline", "defer"}:
        status = "declined" if requested == "decline" else "deferred"
        return _decision(canonical, status=status, candidate_outcome=status)

    provisional = canonical["provisional_category_id"]
    if provisional is not None:
        category = _category(canonical["roster"], provisional)
        answered = canonical["answer_status"] == "durable"
        return _decision(
            canonical,
            status="complete" if answered else "active",
            candidate_outcome="answered" if answered else "engaged",
            category=category,
        )

    try:
        proposal = _proposal(raw)
    except (QuestionCandidateError, TypeError, ValueError):
        return _invalid(canonical)

    latest = canonical["latest_user_turn"]
    reply = proposal["reply"]
    turn_kind = proposal["turn_kind"]
    if latest is None:
        if reply is not None or turn_kind is not None:
            return _invalid(canonical)
    else:
        try:
            reply = _text(reply, name="model_output.reply", maximum=2_200)
        except QuestionCandidateError:
            return _invalid(canonical)
        if turn_kind not in VALID_TURN_KINDS:
            return _invalid(canonical, reply=reply)
        if lint_inherited_reply(
            reply, is_reply_to_substantive=len(latest.strip()) >= 20
        ):
            return _invalid(canonical, turn_kind=turn_kind, reply=reply)

    action = proposal["placement_action"]
    confidence = proposal["confidence"]
    if action not in VALID_PLACEMENT_ACTIONS:
        return _invalid(canonical, turn_kind=turn_kind, reply=reply)
    if isinstance(confidence, bool) or not isinstance(confidence, (int, float)):
        return _invalid(canonical, turn_kind=turn_kind, reply=reply)
    confidence = float(confidence)
    if not 0.0 <= confidence <= 1.0:
        return _invalid(canonical, turn_kind=turn_kind, reply=reply)
    category_id = proposal["category_id"]
    placement_question = proposal["placement_question"]
    threshold = _manifest_number(
        "knob.placement_confidence_threshold", PLACEMENT_CONFIDENCE_THRESHOLD
    )

    if action == "resolved":
        if placement_question is not None or not isinstance(category_id, str):
            return _invalid(canonical, turn_kind=turn_kind, reply=reply)
        category = _category(canonical["roster"], category_id)
        if category is None or confidence < threshold:
            return _invalid(canonical, turn_kind=turn_kind, reply=reply)
        answered = canonical["answer_status"] == "durable"
        return _decision(
            canonical,
            status="complete" if answered else "active",
            candidate_outcome="answered" if answered else "engaged",
            category=category,
            turn_kind=turn_kind,
            reply=reply,
        )

    if category_id is not None:
        return _invalid(canonical, turn_kind=turn_kind, reply=reply)
    if action == "defer":
        if placement_question is not None:
            return _invalid(canonical, turn_kind=turn_kind, reply=reply)
        return _decision(
            canonical,
            status="active",
            candidate_outcome="engaged",
            turn_kind=turn_kind,
            reply=reply,
        )

    if latest is None:
        return _invalid(canonical)
    try:
        placement_question = _text(
            placement_question, name="model_output.placement_question", maximum=1_000
        )
    except QuestionCandidateError:
        return _invalid(canonical, turn_kind=turn_kind, reply=reply)
    if confidence >= threshold or not _question_is_valid(
        placement_question, reply=reply
    ):
        return _invalid(canonical, turn_kind=turn_kind, reply=reply)
    if canonical["previous_placement_question"] == placement_question:
        return _invalid(canonical, turn_kind=turn_kind, reply=reply)
    return _decision(
        canonical,
        status="needs_clarification",
        candidate_outcome="engaged",
        turn_kind=turn_kind,
        reply=reply,
        placement_question=placement_question,
    )


def validate_question_candidate_decision(
    decision: dict, *, current_candidate: dict, current_roster: dict
) -> dict:
    """Revalidate identity and selected-category revisions before transition."""
    candidate = _validate_candidate(current_candidate)
    roster = _validate_roster(current_roster)
    if not isinstance(decision, dict):
        raise QuestionCandidateError("decision must be an object")
    required = frozenset(
        {
            "schema_version",
            "status",
            "candidate_outcome",
            "candidate_id",
            "candidate_revision",
            "source_revision",
            "association_stage",
            "category_id",
            "category_revision",
            "placement_revision",
            "answer_status",
            "turn_kind",
            "reply",
            "placement_question",
            "completion",
        }
    )
    if frozenset(decision) != required:
        raise QuestionCandidateError("decision keys are invalid")
    if decision["schema_version"] != SCHEMA_VERSION:
        raise QuestionCandidateError("decision.schema_version must be 1")
    if decision["status"] not in VALID_STATUSES:
        raise QuestionCandidateError("decision.status is invalid")
    if decision["candidate_outcome"] not in VALID_CANDIDATE_OUTCOMES | {None}:
        raise QuestionCandidateError("decision.candidate_outcome is invalid")
    if decision["association_stage"] not in VALID_ASSOCIATION_STAGES:
        raise QuestionCandidateError("decision.association_stage is invalid")
    if decision["answer_status"] not in VALID_ANSWER_STATUSES:
        raise QuestionCandidateError("decision.answer_status is invalid")
    if decision["turn_kind"] not in VALID_TURN_KINDS | {None}:
        raise QuestionCandidateError("decision.turn_kind is invalid")
    completion = decision["completion"]
    if not isinstance(completion, dict) or set(completion) != {
        "answer_durable",
        "placement_resolved",
        "outcome_resolved",
        "complete",
    }:
        raise QuestionCandidateError("decision.completion keys are invalid")
    if any(not isinstance(value, bool) for value in completion.values()):
        raise QuestionCandidateError("decision.completion values must be booleans")
    expected_completion = _completion(
        answer_status=decision["answer_status"],
        placement_resolved=decision["category_id"] is not None,
        candidate_outcome=decision["candidate_outcome"],
    )
    if completion != expected_completion:
        raise QuestionCandidateError("decision.completion is inconsistent")
    status_outcomes = {
        "active": "engaged",
        "needs_clarification": "engaged",
        "complete": "answered",
        "declined": "declined",
        "deferred": "deferred",
        "invalid": None,
    }
    if decision["candidate_outcome"] != status_outcomes[decision["status"]]:
        raise QuestionCandidateError("decision status/outcome is inconsistent")
    if decision["status"] == "complete" and not completion["complete"]:
        raise QuestionCandidateError("complete status requires complete facts")

    def invalidated() -> dict:
        return {
            **decision,
            "status": "invalid",
            "candidate_outcome": None,
            "category_id": None,
            "category_revision": None,
            "placement_revision": None,
            "completion": _completion(
                answer_status=decision["answer_status"],
                placement_resolved=False,
                candidate_outcome=None,
            ),
        }

    if (
        decision["candidate_id"] != candidate["candidate_id"]
        or decision["candidate_revision"] != candidate["candidate_revision"]
        or decision["source_revision"] != candidate["source_revision"]
    ):
        return invalidated()
    if decision["category_id"] is None:
        if (
            decision["category_revision"] is not None
            or decision["placement_revision"] is not None
        ):
            return invalidated()
        return dict(decision)
    category = _category(roster, decision["category_id"])
    if (
        category is None
        or category["category_revision"] != decision["category_revision"]
    ):
        return invalidated()
    expected = _placement_revision(candidate["candidate_revision"], category)
    if decision["placement_revision"] != expected:
        return invalidated()
    return dict(decision)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser(
        "prompt", help="read input JSON on stdin; print composed prompt"
    )
    args = parser.parse_args(argv)
    if args.command == "prompt":
        try:
            payload = json.load(sys.stdin)
            print(build_question_candidate_prompt(payload))
        except (
            json.JSONDecodeError,
            QuestionCandidateError,
            interaction_registry.InteractionRegistryError,
        ) as exc:
            print(f"question-candidate: {exc}", file=sys.stderr)
            return 2
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
