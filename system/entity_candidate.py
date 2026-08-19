#!/usr/bin/env python3
"""Runtime authority for the registered Entity Candidate Interaction."""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Callable, Sequence
from pathlib import Path

import candidate_research
import conversation_lints
import interaction_registry
from lifehug_core import REPO_DIR
from vault_paths import read_vault_text, vault_data_path

SCHEMA_VERSION = 1
ENTITY_DIMENSIONS = (
    "identity_disambiguation",
    "relationship_relevance_and_significance",
    "timeline_context",
    "connections",
    "tension_or_open_question",
    "type_specific_context",
    "grounded_evidence",
)
ENTITY_TO_RESEARCH_DIMENSION = {
    "identity_disambiguation": "identity_or_disambiguation",
    "relationship_relevance_and_significance": "relevance_or_relationship",
    "timeline_context": "history",
    "connections": "connections",
    "tension_or_open_question": "tension_or_open_question",
    "type_specific_context": "type_specific_context",
}
ENTITY_TYPE_SPECIFIC_MIN_REFS = {
    "person": 1,
    "place": 1,
    "period": 1,
    "object": 1,
    "theme": 2,
}
ENTITY_GAP_PRIORITY = {
    "person": (
        "identity_disambiguation",
        "relationship_relevance_and_significance",
        "grounded_evidence",
        "timeline_context",
        "type_specific_context",
        "connections",
        "tension_or_open_question",
    ),
    "place": (
        "identity_disambiguation",
        "relationship_relevance_and_significance",
        "type_specific_context",
        "grounded_evidence",
        "timeline_context",
        "connections",
        "tension_or_open_question",
    ),
    "period": (
        "identity_disambiguation",
        "timeline_context",
        "type_specific_context",
        "grounded_evidence",
        "relationship_relevance_and_significance",
        "connections",
        "tension_or_open_question",
    ),
    "object": (
        "identity_disambiguation",
        "type_specific_context",
        "relationship_relevance_and_significance",
        "grounded_evidence",
        "timeline_context",
        "connections",
        "tension_or_open_question",
    ),
    "theme": (
        "identity_disambiguation",
        "relationship_relevance_and_significance",
        "grounded_evidence",
        "type_specific_context",
        "timeline_context",
        "connections",
        "tension_or_open_question",
    ),
}
ACTIONS = frozenset(
    {"ask_gap", "offer_confirmation", "accept_confirmation", "continue"}
)
STATUSES = frozenset({"continue", "awaiting_confirmation", "complete", "invalid"})
MAX_PROPOSAL_SPANS = 16
MAX_REPLY_CHARS = 2_200
MAX_PREVIOUS_QUESTION_CHARS = 2_200
_REVISION_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_CANDIDATE_ID_RE = re.compile(
    r"^entity:(person|place|period|object|theme):([a-z0-9]+(?:-[a-z0-9]+)*)$"
)
# Confirmation is a closed, whole-span language rather than a positive prefix.
# A leading "yes" is not consent when it is qualified or negated later in the
# same exact user span.
_EXPLICIT_CONFIRMATION_RE = re.compile(
    r"^\s*(?:"
    r"yes(?:\s*,?\s*(?:please\s+)?preserve\s+(?:it|this|these)"
    r"(?:\s+exact)?(?:\s+(?:research|excerpts))?)?"
    r"|i\s+confirm(?:\s+(?:it|this|these)(?:\s+exact)?"
    r"(?:\s+(?:research|excerpts))?)?"
    r"|confirmed"
    r"|that(?:'s|\s+is)\s+right"
    r"|looks\s+right"
    r"|go\s+ahead"
    r")\s*[.!]*\s*$",
    re.IGNORECASE,
)
_AUTHORITY_CLAIM_RE = re.compile(
    r"\b(?:i|we)\s+(?:(?:have|has|had|will)\s+)?"
    r"(?:approved|created|scaffolded|wrote|saved|persisted|committed|"
    r"pushed|promoted)\b"
    r"|\b(?:the|a|your)\s+(?:focus|recommendation|research|"
    r"candidate\s+research|commit)\s+(?:(?:has|have)\s+been\s+|was\s+|is\s+)?"
    r"(?:approved|created|scaffolded|written|saved|persisted|committed|"
    r"pushed|promoted)\b"
    r"|\bcommit\s+[0-9a-f]{7,40}\b",
    re.IGNORECASE,
)
_INTERNAL_SCHEMA_KEY_RE = re.compile(
    r"\b(?:"
    + "|".join(re.escape(name) for name in ENTITY_DIMENSIONS)
    + r"|schema_version|candidate_id|subject_revision|assessment_revision|"
    r"decision_revision|dimension_evidence|evidence_spans|confirmation_span)\b",
    re.IGNORECASE,
)
_INPUT_KEYS = frozenset(
    {
        "schema_version",
        "candidate_id",
        "subject_revision",
        "authoritative_turns",
        "assessment",
        "latest_turn_id",
        "previous_question",
    }
)
_OUTPUT_KEYS = frozenset(
    {
        "reply",
        "action",
        "next_gap",
        "evidence_spans",
        "dimension_evidence",
        "seed_questions",
        "confirmation_span",
    }
)
_SPAN_PROPOSAL_KEYS = frozenset({"turn_id", "start", "end", "evidence_kind"})
_CONFIRMATION_SPAN_KEYS = frozenset({"turn_id", "start", "end"})
_DECISION_KEYS = frozenset(
    {
        "schema_version",
        "status",
        "action",
        "candidate_id",
        "subject_revision",
        "reply",
        "next_gap",
        "assessment",
        "ready",
        "complete",
        "decision_revision",
    }
)


class EntityCandidateError(ValueError):
    """Entity Candidate input or proposal violated the closed contract."""


def _object(value: object, *, name: str, keys: frozenset[str]) -> dict:
    if not isinstance(value, dict):
        raise EntityCandidateError(f"{name} must be an object")
    actual = frozenset(value)
    if actual != keys:
        raise EntityCandidateError(
            f"{name} keys invalid: missing={sorted(keys - actual)}, "
            f"unknown={sorted(actual - keys)}"
        )
    return value


def _text(value: object, *, name: str, maximum: int) -> str:
    if not isinstance(value, str) or not value.strip():
        raise EntityCandidateError(f"{name} must be a non-empty string")
    if len(value) > maximum:
        raise EntityCandidateError(f"{name} exceeds {maximum} characters")
    return value


def _nullable_text(value: object, *, name: str, maximum: int) -> str | None:
    if value is None:
        return None
    return _text(value, name=name, maximum=maximum)


def _state_path(entity_type: str, vault_root: str | Path | None) -> Path:
    root = Path(vault_root) if vault_root is not None else REPO_DIR
    return vault_data_path("entity_rosters", vault_root=root) / f"{entity_type}.json"


def _vault_root(vault_root: str | Path | None) -> Path:
    return Path(vault_root) if vault_root is not None else REPO_DIR


def load_entity_candidate_subject(
    candidate_id: str, *, vault_root: str | Path | None = None
) -> dict:
    """Resolve one active roster row; labels and lifecycle stay server-side."""
    candidate_id = _text(candidate_id, name="candidate_id", maximum=256)
    match = _CANDIDATE_ID_RE.fullmatch(candidate_id)
    if match is None:
        raise EntityCandidateError("entity candidate id is invalid")
    entity_type, slug = match.groups()
    root = _vault_root(vault_root)
    path = _state_path(entity_type, root)
    try:
        state = json.loads(read_vault_text(path, vault_root=root, encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise EntityCandidateError("cannot load canonical entity roster") from exc
    if not isinstance(state, dict) or state.get("version") != 1:
        raise EntityCandidateError("entity roster state schema is invalid")
    rows = state.get("entities")
    if not isinstance(rows, list):
        raise EntityCandidateError("entity roster entities is invalid")
    matches = [row for row in rows if isinstance(row, dict) and row.get("slug") == slug]
    if len(matches) != 1:
        raise EntityCandidateError("entity candidate id must resolve exactly once")
    try:
        subject = candidate_research.build_entity_candidate_subject(
            entity_type, matches[0]
        )
        if subject["candidate_id"] != candidate_id:
            raise EntityCandidateError(
                "entity candidate identity disagrees with roster"
            )
        return candidate_research.validate_candidate_research_subject(
            subject, require_active=True
        )
    except candidate_research.CandidateResearchError as exc:
        raise EntityCandidateError(str(exc)) from exc


def build_entity_candidate_input(
    *,
    candidate_id: str,
    authoritative_turns: Sequence[dict],
    assessment: dict | None,
    latest_turn_id: str | None,
    previous_question: str | None,
    current_subject: dict,
) -> dict:
    subject = candidate_research.validate_candidate_research_subject(
        current_subject, require_active=True
    )
    if candidate_id != subject["candidate_id"]:
        raise EntityCandidateError("candidate_id does not match current subject")
    payload = {
        "schema_version": SCHEMA_VERSION,
        "candidate_id": candidate_id,
        "subject_revision": subject["subject_revision"],
        "authoritative_turns": list(authoritative_turns),
        "assessment": assessment,
        "latest_turn_id": latest_turn_id,
        "previous_question": previous_question,
    }
    return validate_entity_candidate_input(payload, current_subject=subject)


def validate_entity_candidate_input(value: object, *, current_subject: dict) -> dict:
    payload = _object(value, name="input", keys=_INPUT_KEYS)
    if payload["schema_version"] != SCHEMA_VERSION:
        raise EntityCandidateError("input.schema_version must be 1")
    subject = candidate_research.validate_candidate_research_subject(
        current_subject, require_active=True
    )
    candidate_id = _text(payload["candidate_id"], name="candidate_id", maximum=256)
    if candidate_id != subject["candidate_id"]:
        raise EntityCandidateError("candidate_id does not match current subject")
    revision = payload["subject_revision"]
    if not isinstance(revision, str) or not _REVISION_RE.fullmatch(revision):
        raise EntityCandidateError("subject_revision must be sha256:<64 lowercase hex>")
    if revision != subject["subject_revision"]:
        raise EntityCandidateError("entity candidate subject revision is stale")
    turns = (
        [
            candidate_research.validate_authoritative_user_turn(turn)
            for turn in payload["authoritative_turns"]
        ]
        if isinstance(payload["authoritative_turns"], list)
        else None
    )
    if turns is None:
        raise EntityCandidateError("authoritative_turns must be a list")
    ids = [turn["turn_id"] for turn in turns]
    if len(ids) != len(set(ids)):
        raise EntityCandidateError("authoritative turn ids must be unique")
    latest = _nullable_text(
        payload["latest_turn_id"], name="latest_turn_id", maximum=256
    )
    if latest is not None and latest not in ids:
        raise EntityCandidateError("latest_turn_id is not authoritative")
    previous = _nullable_text(
        payload["previous_question"],
        name="previous_question",
        maximum=MAX_PREVIOUS_QUESTION_CHARS,
    )
    assessment = payload["assessment"]
    if assessment is not None:
        assessment = candidate_research.validate_research_assessment(
            assessment,
            authoritative_turns=turns,
            current_subject=subject,
        )
        if assessment["complete"]:
            raise EntityCandidateError("completed entity research cannot continue")
    return {
        "schema_version": SCHEMA_VERSION,
        "candidate_id": candidate_id,
        "subject_revision": revision,
        "authoritative_turns": turns,
        "assessment": assessment,
        "latest_turn_id": latest,
        "previous_question": previous,
    }


def build_entity_candidate_prompt(value: dict, *, current_subject: dict) -> str:
    payload = validate_entity_candidate_input(value, current_subject=current_subject)
    assets = [
        interaction_registry.compose_interaction_asset("entity_candidate", path)
        for path in (
            "prompt/identity.md",
            "prompt/behavior.md",
            "prompt/examples.md",
            "prompt/turn-instructions.md",
        )
    ]
    untrusted = {
        **payload,
        "candidate": current_subject,
        "entity_dimensions": ENTITY_DIMENSIONS,
    }
    return (
        "\n".join(assets)
        + "\n<!-- runtime-boundary:untrusted-data -->\nUNTRUSTED_DATA\n"
        + json.dumps(untrusted, ensure_ascii=False, sort_keys=True, indent=2)
        + "\nEND_UNTRUSTED_DATA\n"
    )


def _proposal(raw: object) -> dict:
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise EntityCandidateError("model output is not JSON") from exc
    return _object(raw, name="model_output", keys=_OUTPUT_KEYS)


def _question_count(reply: str) -> int:
    return sum(
        1 for part in re.findall(r"[^.!?]+[.!?]*", reply) if part.rstrip().endswith("?")
    )


def lint_inherited_reply(
    text: str, *, is_reply_to_substantive: bool = False, seam_ok: bool = False
) -> list[dict]:
    """Apply the one inherited Conversation lint authority."""
    return conversation_lints.lint_turn(
        text,
        is_reply_to_substantive=is_reply_to_substantive,
        seam_ok=seam_ok,
    )


def lint_entity_candidate_reply(
    text: str, *, is_reply_to_substantive: bool = False, seam_ok: bool = False
) -> list[dict]:
    """Apply inherited Conversation lints plus this Interaction's authority guard."""
    findings = lint_inherited_reply(
        text,
        is_reply_to_substantive=is_reply_to_substantive,
        seam_ok=seam_ok,
    )
    if _AUTHORITY_CLAIM_RE.search(text):
        findings.append(
            {
                "lint": "entity_candidate_authority_claim",
                "detail": "reply claims lifecycle or durable-write authority",
                "span": [0, len(text)],
            }
        )
    if _INTERNAL_SCHEMA_KEY_RE.search(text):
        findings.append(
            {
                "lint": "entity_candidate_schema_leak",
                "detail": "reply exposes an internal Entity Candidate schema key",
                "span": [0, len(text)],
            }
        )
    return findings


def _is_explicit_confirmation(text: str) -> bool:
    return bool(
        _EXPLICIT_CONFIRMATION_RE.match(text)
    ) and not text.lstrip().lower().startswith(("no", "not", "don't", "do not"))


def _prior_parts(payload: dict) -> tuple[list[dict], dict[str, list[str]], list[dict]]:
    assessment = payload["assessment"]
    if assessment is None:
        return [], {name: [] for name in candidate_research.ENTITY_DIMENSIONS}, []
    return (
        list(assessment["evidence"]),
        {name: list(refs) for name, refs in assessment["dimension_evidence"].items()},
        list(assessment["seed_questions"]),
    )


def _unsupported_dimensions(assessment: dict, subject: dict) -> set[str]:
    """Derive the seven interaction gates without changing v183's schema."""
    unsupported = {
        name
        for name, research_name in ENTITY_TO_RESEARCH_DIMENSION.items()
        if not assessment["dimension_evidence"][research_name]
    }
    if assessment["readiness"]["concrete_evidence_count"] < 1:
        unsupported.add("grounded_evidence")
    refs = assessment["dimension_evidence"]["type_specific_context"]
    if len(refs) < ENTITY_TYPE_SPECIFIC_MIN_REFS[subject["subject_type"]]:
        unsupported.add("type_specific_context")
    return unsupported


def _interaction_ready(assessment: dict, subject: dict) -> bool:
    return assessment["readiness"]["ready"] and not _unsupported_dimensions(
        assessment, subject
    )


def _expected_next_gap(assessment: dict, subject: dict) -> str | None:
    unsupported = _unsupported_dimensions(assessment, subject)
    return next(
        (
            gap
            for gap in ENTITY_GAP_PRIORITY[subject["subject_type"]]
            if gap in unsupported
        ),
        None,
    )


def _invalid(
    payload: dict, *, reply: str | None = None, action: str | None = None
) -> dict:
    source = {
        "schema_version": SCHEMA_VERSION,
        "status": "invalid",
        "action": action,
        "candidate_id": payload["candidate_id"],
        "subject_revision": payload["subject_revision"],
        "reply": reply,
        "next_gap": None,
        "assessment": payload["assessment"],
        "ready": bool(
            payload["assessment"]
            and _interaction_ready(
                payload["assessment"], payload["assessment"]["subject"]
            )
        ),
        "complete": False,
    }
    return {
        **source,
        "decision_revision": candidate_research.canonical_revision(source),
    }


def _is_substantive_latest(payload: dict) -> bool:
    latest = payload["latest_turn_id"]
    if latest is None:
        return False
    turn = next(
        row for row in payload["authoritative_turns"] if row["turn_id"] == latest
    )
    return len(turn["text"].strip()) >= 20


def parse_entity_candidate_output(
    raw: object,
    *,
    payload: dict,
    current_subject: dict,
    confirmed_at: str | None = None,
) -> dict:
    """Normalize an untrusted model proposal and recompute all authority facts."""
    canonical = validate_entity_candidate_input(
        payload, current_subject=current_subject
    )
    try:
        proposal = _proposal(raw)
        reply = _text(proposal["reply"], name="reply", maximum=MAX_REPLY_CHARS)
        action = proposal["action"]
        if action not in ACTIONS:
            raise EntityCandidateError("action is invalid")
        seam_ok = action == "offer_confirmation"
        if lint_entity_candidate_reply(
            reply,
            is_reply_to_substantive=_is_substantive_latest(canonical),
            seam_ok=seam_ok,
        ):
            raise EntityCandidateError("reply violates inherited Conversation lints")
        next_gap = proposal["next_gap"]
        if next_gap is not None and next_gap not in ENTITY_DIMENSIONS:
            raise EntityCandidateError("next_gap is invalid")
        raw_spans = proposal["evidence_spans"]
        if not isinstance(raw_spans, list) or len(raw_spans) > MAX_PROPOSAL_SPANS:
            raise EntityCandidateError("evidence_spans is invalid")
        turns_by_id = {
            turn["turn_id"]: turn for turn in canonical["authoritative_turns"]
        }
        new_spans: list[dict] = []
        for index, raw_span in enumerate(raw_spans):
            span = _object(
                raw_span, name=f"evidence_spans[{index}]", keys=_SPAN_PROPOSAL_KEYS
            )
            turn = turns_by_id.get(span["turn_id"])
            if turn is None:
                raise EntityCandidateError(
                    "evidence span names a non-authoritative turn"
                )
            new_spans.append(
                candidate_research.extract_research_evidence_span(
                    turn, span["start"], span["end"], span["evidence_kind"]
                )
            )
        raw_dimensions = _object(
            proposal["dimension_evidence"],
            name="dimension_evidence",
            keys=frozenset(ENTITY_DIMENSIONS),
        )
        referenced: dict[str, list[dict]] = {}
        for dimension in ENTITY_DIMENSIONS:
            refs = raw_dimensions[dimension]
            if not isinstance(refs, list) or any(
                isinstance(ref, bool)
                or not isinstance(ref, int)
                or ref < 0
                or ref >= len(new_spans)
                for ref in refs
            ):
                raise EntityCandidateError(f"dimension {dimension} indices are invalid")
            if len(refs) != len(set(refs)):
                raise EntityCandidateError(f"dimension {dimension} indices repeat")
            referenced[dimension] = [new_spans[ref] for ref in refs]
        if any(
            span["evidence_kind"] not in candidate_research.CONCRETE_EVIDENCE_KINDS
            for span in referenced["grounded_evidence"]
        ):
            raise EntityCandidateError("grounded_evidence requires concrete spans")
        used = {
            span["evidence_revision"] for spans in referenced.values() for span in spans
        }
        if used != {span["evidence_revision"] for span in new_spans}:
            raise EntityCandidateError("every proposed span must support a dimension")
        evidence, dimensions, questions = _prior_parts(canonical)
        known = {span["evidence_revision"] for span in evidence}
        evidence.extend(
            span for span in new_spans if span["evidence_revision"] not in known
        )
        for (
            entity_dimension,
            research_dimension,
        ) in ENTITY_TO_RESEARCH_DIMENSION.items():
            existing = dimensions[research_dimension]
            for span in referenced[entity_dimension]:
                revision = span["evidence_revision"]
                if revision not in existing:
                    existing.append(revision)
        # Concrete spans must also support a source dimension; grounded_evidence
        # is an Interaction gate, not an eighth v183 source-schema key.
        grounded = {s["evidence_revision"] for s in referenced["grounded_evidence"]}
        source_refs = {ref for refs in dimensions.values() for ref in refs}
        if not grounded <= source_refs:
            raise EntityCandidateError(
                "grounded evidence must support a source dimension"
            )
        raw_questions = proposal["seed_questions"]
        if not isinstance(raw_questions, list):
            raise EntityCandidateError("seed_questions must be a list")
        known_questions = {row["question"] for row in questions}
        for index, question in enumerate(raw_questions):
            clean = _text(question, name=f"seed_questions[{index}]", maximum=1_000)
            if not clean.endswith("?") or _question_count(clean) != 1:
                raise EntityCandidateError(
                    "seed questions must be worthwhile questions"
                )
            if clean not in known_questions:
                questions.append({"question": clean, "evidence": False})
                known_questions.add(clean)
        assessment = candidate_research.build_research_assessment(
            subject=current_subject,
            evidence=evidence,
            dimension_evidence=dimensions,
            seed_questions=questions,
            authoritative_turns=canonical["authoritative_turns"],
        )
        ready = _interaction_ready(assessment, current_subject)
        expected_next_gap = _expected_next_gap(assessment, current_subject)
        confirmation_span = proposal["confirmation_span"]
        prior_ready = bool(
            canonical["assessment"] and canonical["assessment"]["readiness"]["ready"]
        )
        status = "continue"
        if action == "ask_gap":
            if (
                expected_next_gap is None
                or next_gap != expected_next_gap
                or _question_count(reply) != 1
            ):
                raise EntityCandidateError(
                    "ask_gap must ask one unsupported highest-value gap"
                )
            if (
                canonical["previous_question"]
                and canonical["previous_question"] in reply
            ):
                raise EntityCandidateError("ask_gap repeats the previous question")
            if confirmation_span is not None:
                raise EntityCandidateError("ask_gap cannot confirm")
        elif action == "offer_confirmation":
            if not ready or next_gap is not None or confirmation_span is not None:
                raise EntityCandidateError("offer_confirmation requires ready research")
            if _question_count(reply) != 1:
                raise EntityCandidateError("offer_confirmation must ask one question")
            status = "awaiting_confirmation"
        elif action == "accept_confirmation":
            if (
                not prior_ready
                or next_gap is not None
                or new_spans
                or raw_questions
                or any(referenced.values())
            ):
                raise EntityCandidateError(
                    "accept_confirmation requires a previously ready assessment"
                )
            if confirmed_at is None:
                raise EntityCandidateError(
                    "accept_confirmation requires trusted confirmed_at"
                )
            raw_confirmation = _object(
                confirmation_span,
                name="confirmation_span",
                keys=_CONFIRMATION_SPAN_KEYS,
            )
            turn = turns_by_id.get(raw_confirmation["turn_id"])
            if (
                turn is None
                or raw_confirmation["turn_id"] != canonical["latest_turn_id"]
            ):
                raise EntityCandidateError(
                    "confirmation must be in the latest user turn"
                )
            confirmation_text = turn["text"][
                raw_confirmation["start"] : raw_confirmation["end"]
            ]
            if not _is_explicit_confirmation(confirmation_text):
                raise EntityCandidateError("confirmation span is not explicit consent")
            assessment = candidate_research.confirm_research_assessment(
                assessment,
                turn=turn,
                start=raw_confirmation["start"],
                end=raw_confirmation["end"],
                confirmed_at=confirmed_at,
                authoritative_turns=canonical["authoritative_turns"],
                current_subject=current_subject,
            )
            status = "complete"
        else:
            if (
                next_gap is not None
                or confirmation_span is not None
                or _question_count(reply)
            ):
                raise EntityCandidateError("continue cannot ask or confirm")
        source = {
            "schema_version": SCHEMA_VERSION,
            "status": status,
            "action": action,
            "candidate_id": canonical["candidate_id"],
            "subject_revision": canonical["subject_revision"],
            "reply": reply,
            "next_gap": next_gap,
            "assessment": assessment,
            "ready": ready,
            "complete": assessment["complete"],
        }
        return {
            **source,
            "decision_revision": candidate_research.canonical_revision(source),
        }
    except (
        EntityCandidateError,
        candidate_research.CandidateResearchError,
        TypeError,
        ValueError,
    ):
        return _invalid(canonical)


def validate_entity_candidate_decision(
    decision: object, *, payload: dict, current_subject: dict
) -> dict:
    canonical = validate_entity_candidate_input(
        payload, current_subject=current_subject
    )
    value = _object(decision, name="decision", keys=_DECISION_KEYS)
    source = {key: value[key] for key in value if key != "decision_revision"}
    if value["decision_revision"] != candidate_research.canonical_revision(source):
        raise EntityCandidateError("decision_revision does not match decision")
    if (
        value["candidate_id"] != canonical["candidate_id"]
        or value["subject_revision"] != canonical["subject_revision"]
    ):
        raise EntityCandidateError("entity candidate decision is stale")
    if not isinstance(value["status"], str) or value["status"] not in STATUSES:
        raise EntityCandidateError("decision status is invalid")
    if value["action"] is not None and not isinstance(value["action"], str):
        raise EntityCandidateError("decision action is invalid")
    if type(value["ready"]) is not bool or type(value["complete"]) is not bool:
        raise EntityCandidateError("decision ready and complete must be booleans")
    matrix = {
        "continue": {"ask_gap", "continue"},
        "awaiting_confirmation": {"offer_confirmation"},
        "complete": {"accept_confirmation"},
        "invalid": {None},
    }
    if value["action"] not in matrix[value["status"]]:
        raise EntityCandidateError("decision action/status combination is invalid")
    if value["reply"] is not None:
        reply = _text(value["reply"], name="decision.reply", maximum=MAX_REPLY_CHARS)
        if lint_entity_candidate_reply(
            reply,
            is_reply_to_substantive=_is_substantive_latest(canonical),
            seam_ok=value["action"] == "offer_confirmation",
        ):
            raise EntityCandidateError("decision reply violates inherited authority")
    else:
        reply = None
    assessment = None
    if value["assessment"] is not None:
        assessment = candidate_research.validate_research_assessment(
            value["assessment"],
            authoritative_turns=canonical["authoritative_turns"],
            current_subject=current_subject,
        )
        if (
            value["ready"] is not assessment["readiness"]["ready"]
            or value["complete"] is not assessment["complete"]
        ):
            raise EntityCandidateError("decision readiness is forged")
    action = value["action"]
    next_gap = value["next_gap"]
    if action == "ask_gap":
        if (
            next_gap not in ENTITY_DIMENSIONS
            or reply is None
            or _question_count(reply) != 1
        ):
            raise EntityCandidateError("ask_gap decision shape is invalid")
    elif action == "continue":
        if next_gap is not None or reply is None or _question_count(reply):
            raise EntityCandidateError("continue decision shape is invalid")
    elif action == "offer_confirmation":
        if (
            next_gap is not None
            or reply is None
            or _question_count(reply) != 1
            or not value["ready"]
            or value["complete"]
        ):
            raise EntityCandidateError("offer_confirmation decision shape is invalid")
    elif action == "accept_confirmation":
        if (
            assessment is None
            or next_gap is not None
            or reply is None
            or value["ready"] is not True
            or value["complete"] is not True
            or assessment["readiness"]["ready"] is not True
            or assessment["complete"] is not True
        ):
            raise EntityCandidateError("accept_confirmation decision shape is invalid")
        confirmation = assessment["confirmation"]
        if (
            confirmation is None
            or confirmation["evidence"]["turn_id"] != canonical["latest_turn_id"]
        ):
            raise EntityCandidateError("completion confirmation is not current")
        latest_turn = next(
            turn
            for turn in canonical["authoritative_turns"]
            if turn["turn_id"] == canonical["latest_turn_id"]
        )
        evidence = confirmation["evidence"]
        if not _is_explicit_confirmation(
            latest_turn["text"][evidence["start"] : evidence["end"]]
        ):
            raise EntityCandidateError(
                "completion confirmation is not explicit consent"
            )
    elif next_gap is not None or value["complete"]:
        raise EntityCandidateError("invalid decision carries authoritative facts")
    return dict(value)


def resolve_entity_candidate_completion(
    assessment: dict,
    *,
    authoritative_turns: Sequence[dict],
    candidate_id: str,
    current_subject_loader: Callable[[], dict],
    authority: candidate_research.CandidateResearchGitAuthority = (
        candidate_research.EXACT_FILE_GIT_AUTHORITY
    ),
    vault_root: str | Path | None = None,
    push: bool = True,
    failpoint: Callable[[str], None] | None = None,
) -> dict:
    if not callable(current_subject_loader):
        raise EntityCandidateError("current_subject_loader must be callable")
    try:
        subject = candidate_research.validate_candidate_research_subject(
            current_subject_loader(), require_active=True
        )
    except candidate_research.CandidateResearchError as exc:
        raise EntityCandidateError(str(exc)) from exc
    if (
        subject["candidate_id"] != candidate_id
        or subject["candidate_kind"] != "entity_candidate"
    ):
        raise EntityCandidateError(
            "completion candidate does not match current subject"
        )
    try:
        return candidate_research.resolve_candidate_research_source(
            assessment,
            authoritative_turns=authoritative_turns,
            current_subject_loader=current_subject_loader,
            authority=authority,
            vault_root=vault_root,
            push=push,
            failpoint=failpoint,
        )
    except candidate_research.CandidateResearchError as exc:
        raise EntityCandidateError(str(exc)) from exc


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    prompt = sub.add_parser("prompt")
    prompt.add_argument("--candidate-id", required=True)
    complete = sub.add_parser("complete")
    complete.add_argument("--candidate-id", required=True)
    complete.add_argument("--no-push", action="store_true")
    complete.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    try:
        raw = json.load(sys.stdin)

        def loader() -> dict:
            return load_entity_candidate_subject(args.candidate_id)

        subject = loader()
        if args.command == "prompt":
            payload = build_entity_candidate_input(
                candidate_id=args.candidate_id,
                authoritative_turns=raw["authoritative_turns"],
                assessment=raw.get("assessment"),
                latest_turn_id=raw.get("latest_turn_id"),
                previous_question=raw.get("previous_question"),
                current_subject=subject,
            )
            print(build_entity_candidate_prompt(payload, current_subject=subject))
        else:
            receipt = resolve_entity_candidate_completion(
                raw["assessment"],
                authoritative_turns=raw["authoritative_turns"],
                candidate_id=args.candidate_id,
                current_subject_loader=loader,
                vault_root=REPO_DIR,
                push=not args.no_push,
            )
            print(json.dumps(receipt, sort_keys=True))
        return 0
    except (
        KeyError,
        json.JSONDecodeError,
        EntityCandidateError,
        interaction_registry.InteractionRegistryError,
    ) as exc:
        print(f"focus-candidate: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
