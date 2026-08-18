#!/usr/bin/env python3
"""Pure candidate-research evidence, assessment, source, and receipt authority.

The live Git transaction is intentionally injected.  PR #173/v182 owns the
single vault writer/Git authority; this module never acquires a writer lease or
invokes Git itself.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import re
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Protocol

from lifehug_core import slugify, split_frontmatter
from question_candidate import REVISION_RE, canonical_revision
from source_integrity import (
    CANDIDATE_RESEARCH_MANIFEST_FIELDS,
    format_frontmatter,
    payload_sha256,
)

SCHEMA_VERSION = 1
RESEARCH_KINDS = frozenset({"focus_candidate", "entity_candidate"})
FOCUS_SUBJECT_TYPES = frozenset({"person", "place", "period", "theme"})
ENTITY_SUBJECT_TYPES = frozenset({"person", "place", "period", "object", "theme"})
SUBJECT_STATES = frozenset({"active", "consumed", "tombstoned"})
EVIDENCE_KINDS = frozenset(
    {"statement", "concrete_event", "concrete_observation", "confirmation"}
)
CONCRETE_EVIDENCE_KINDS = frozenset({"concrete_event", "concrete_observation"})

FOCUS_DIMENSIONS = (
    "identity",
    "why_it_matters",
    "scope_boundary",
    "present_state_or_direction",
    "relationships",
    "tensions",
    "open_questions",
)
ENTITY_DIMENSIONS = (
    "identity_or_disambiguation",
    "relevance_or_relationship",
    "history",
    "connections",
    "tension_or_open_question",
    "type_specific_context",
)

SUBSTANTIVE_MIN_CHARACTERS = 24
SUBSTANTIVE_MIN_WORDS = 4
FOCUS_MIN_EVIDENCE_SPANS = 3
ENTITY_MIN_EVIDENCE_SPANS = {
    "person": 2,
    "place": 3,
    "period": 3,
    "object": 2,
    "theme": 3,
}
FOCUS_MIN_SEED_QUESTIONS = 2
MAX_EVIDENCE_SPANS = 64
MAX_SEED_QUESTIONS = 8
MAX_TURN_TEXT = 100_000

TURN_ID_RE = re.compile(r"^[A-Za-z0-9._:-]{1,256}$")
SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
UTC_SECONDS_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
CONTENT_HASH_RE = re.compile(r"^[0-9a-f]{64}$")
COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
WORD_RE = re.compile(r"\w+", re.UNICODE)

SOURCE_ROOT = PurePosixPath("sources/candidate-research")
MARKER_PREFIX = "<!-- lifehug:candidate-research:v1 "
MARKER_SUFFIX = " -->"
MAX_MARKER_PAYLOAD_BYTES = 16_384

_SUBJECT_KEYS = frozenset(
    {
        "schema_version",
        "candidate_kind",
        "candidate_id",
        "subject_type",
        "subject_label",
        "subject_slug",
        "subject_aliases",
        "candidate_state",
        "identity_revision",
        "subject_revision",
    }
)
_TURN_KEYS = frozenset({"schema_version", "turn_id", "role", "text", "turn_revision"})
_SPAN_KEYS = frozenset(
    {
        "schema_version",
        "turn_id",
        "turn_revision",
        "start",
        "end",
        "quote",
        "evidence_kind",
        "evidence_revision",
    }
)
_SEED_QUESTION_KEYS = frozenset({"question", "evidence"})
_READINESS_KEYS = frozenset(
    {
        "ready",
        "missing",
        "substantive_evidence_count",
        "concrete_evidence_count",
        "seed_question_count",
    }
)
_CONFIRMATION_KEYS = frozenset(
    {
        "status",
        "assessment_revision",
        "evidence",
        "confirmed_at",
        "confirmation_revision",
    }
)
_ASSESSMENT_KEYS = frozenset(
    {
        "schema_version",
        "subject",
        "evidence",
        "dimension_evidence",
        "seed_questions",
        "readiness",
        "assessment_revision",
        "confirmation",
        "complete",
        "research_revision",
    }
)
_MARKER_KEYS = frozenset(
    {
        "schema_version",
        "candidate_kind",
        "candidate_id",
        "identity_revision",
        "subject_revision",
        "assessment_revision",
        "research_revision",
        "source_id",
        "source_path",
    }
)
_AUTHORITY_RECEIPT_KEYS = frozenset({"source_path", "changed", "commit_sha"})


class CandidateResearchError(ValueError):
    """Candidate research violated a closed schema or authority boundary."""


class CandidateResearchConflict(CandidateResearchError):
    """Canonical candidate research already exists with different facts."""


class CandidateResearchGitAuthority(Protocol):
    """The exact v182-backed mutation seam; implementations own lease + Git."""

    def resolve_exact_source(
        self,
        plan: dict,
        *,
        vault_root: str | Path | None = None,
        push: bool = True,
        failpoint: Callable[[str], None] | None = None,
    ) -> dict: ...


def _object(value: object, *, name: str, keys: frozenset[str]) -> dict:
    if not isinstance(value, dict):
        raise CandidateResearchError(f"{name} must be an object")
    actual = frozenset(value)
    if actual != keys:
        raise CandidateResearchError(
            f"{name} keys invalid: missing={sorted(keys - actual)}, "
            f"unknown={sorted(actual - keys)}"
        )
    return value


def _text(value: object, *, name: str, maximum: int) -> str:
    if not isinstance(value, str) or not value.strip():
        raise CandidateResearchError(f"{name} must be a non-empty string")
    if len(value) > maximum:
        raise CandidateResearchError(f"{name} exceeds {maximum} characters")
    return value


def _revision(value: object, *, name: str) -> str:
    if not isinstance(value, str) or not REVISION_RE.fullmatch(value):
        raise CandidateResearchError(f"{name} must be sha256:<64 lowercase hex>")
    return value


def _utc_seconds(value: object, *, name: str) -> str:
    if not isinstance(value, str) or not UTC_SECONDS_RE.fullmatch(value):
        raise CandidateResearchError(f"{name} must be UTC RFC3339 seconds")
    try:
        datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError as exc:
        raise CandidateResearchError(f"{name} is not a real timestamp") from exc
    return value


def _aliases(value: object) -> list[str]:
    if not isinstance(value, list) or len(value) > 64:
        raise CandidateResearchError(
            "subject_aliases must be a list of at most 64 strings"
        )
    aliases: list[str] = []
    seen: set[str] = set()
    for index, alias in enumerate(value):
        alias = _text(alias, name=f"subject_aliases[{index}]", maximum=512)
        if alias in seen:
            raise CandidateResearchError("subject_aliases must not contain duplicates")
        seen.add(alias)
        aliases.append(alias)
    return aliases


def _identity_source(
    candidate_kind: str,
    candidate_id: str,
    subject_type: str,
    subject_label: str,
    subject_slug: str,
    subject_aliases: list[str],
) -> dict:
    return {
        "candidate_kind": candidate_kind,
        "candidate_id": candidate_id,
        "subject_type": subject_type,
        "subject_label": subject_label,
        "subject_slug": subject_slug,
        "subject_aliases": subject_aliases,
    }


def build_candidate_research_subject(
    *,
    candidate_kind: str,
    candidate_id: str,
    subject_type: str,
    subject_label: str,
    subject_slug: str,
    subject_aliases: list[str],
    candidate_state: str,
) -> dict:
    if candidate_kind not in RESEARCH_KINDS:
        raise CandidateResearchError("candidate_kind is invalid")
    allowed_types = (
        FOCUS_SUBJECT_TYPES
        if candidate_kind == "focus_candidate"
        else ENTITY_SUBJECT_TYPES
    )
    if subject_type not in allowed_types:
        raise CandidateResearchError("subject_type is invalid for candidate_kind")
    candidate_id = _text(candidate_id, name="candidate_id", maximum=256)
    subject_label = _text(subject_label, name="subject_label", maximum=512)
    subject_slug = _text(subject_slug, name="subject_slug", maximum=256)
    if not SLUG_RE.fullmatch(subject_slug):
        raise CandidateResearchError("subject_slug must be a canonical safe slug")
    aliases = _aliases(subject_aliases)
    if candidate_state not in SUBJECT_STATES:
        raise CandidateResearchError("candidate_state is invalid")
    identity_source = _identity_source(
        candidate_kind,
        candidate_id,
        subject_type,
        subject_label,
        subject_slug,
        aliases,
    )
    identity_revision = canonical_revision(identity_source)
    subject_source = {**identity_source, "candidate_state": candidate_state}
    return {
        "schema_version": SCHEMA_VERSION,
        **subject_source,
        "identity_revision": identity_revision,
        "subject_revision": canonical_revision(
            {
                "identity_revision": identity_revision,
                "candidate_state": candidate_state,
            }
        ),
    }


def build_focus_candidate_subject(recommendation: Mapping[str, object]) -> dict:
    if not isinstance(recommendation, Mapping):
        raise CandidateResearchError("focus recommendation must be an object")
    status = str(recommendation.get("status") or "")
    if status == "pending":
        candidate_state = "active"
    elif status == "approved":
        candidate_state = "consumed"
    elif status in {"dismissed", "expired"}:
        candidate_state = "tombstoned"
    else:
        raise CandidateResearchError("focus recommendation status is invalid")
    label = _text(recommendation.get("entity"), name="entity", maximum=512)
    return build_candidate_research_subject(
        candidate_kind="focus_candidate",
        candidate_id=_text(recommendation.get("id"), name="id", maximum=256),
        subject_type=str(recommendation.get("type") or ""),
        subject_label=label,
        subject_slug=slugify(label),
        subject_aliases=[],
        candidate_state=candidate_state,
    )


def build_entity_candidate_subject(
    entity_type: str, roster_entry: Mapping[str, object]
) -> dict:
    if entity_type not in ENTITY_SUBJECT_TYPES:
        raise CandidateResearchError("entity_type is invalid")
    if not isinstance(roster_entry, Mapping):
        raise CandidateResearchError("entity roster entry must be an object")
    label = _text(roster_entry.get("name"), name="name", maximum=512)
    slug = str(roster_entry.get("slug") or slugify(label))
    aliases = list(roster_entry.get("aliases") or [])
    verdict = roster_entry.get("owner_verdict")
    if verdict not in {None, "", "never", "graduate"}:
        raise CandidateResearchError("entity owner_verdict is invalid")
    if verdict == "never":
        candidate_state = "tombstoned"
    elif (
        verdict == "graduate"
        or bool(roster_entry.get("page_eligible"))
        or bool(roster_entry.get("maps_to_focus"))
    ):
        candidate_state = "consumed"
    else:
        candidate_state = "active"
    return build_candidate_research_subject(
        candidate_kind="entity_candidate",
        candidate_id=f"entity:{entity_type}:{slug}",
        subject_type=entity_type,
        subject_label=label,
        subject_slug=slug,
        subject_aliases=aliases,
        candidate_state=candidate_state,
    )


def validate_candidate_research_subject(value: object, *, require_active: bool) -> dict:
    subject = _object(value, name="subject", keys=_SUBJECT_KEYS)
    if subject["schema_version"] != SCHEMA_VERSION:
        raise CandidateResearchError("subject.schema_version must be 1")
    canonical = build_candidate_research_subject(
        candidate_kind=subject["candidate_kind"],
        candidate_id=subject["candidate_id"],
        subject_type=subject["subject_type"],
        subject_label=subject["subject_label"],
        subject_slug=subject["subject_slug"],
        subject_aliases=subject["subject_aliases"],
        candidate_state=subject["candidate_state"],
    )
    if (
        _revision(subject["identity_revision"], name="identity_revision")
        != canonical["identity_revision"]
    ):
        raise CandidateResearchError(
            "identity_revision does not match subject identity"
        )
    if (
        _revision(subject["subject_revision"], name="subject_revision")
        != canonical["subject_revision"]
    ):
        raise CandidateResearchError("subject_revision does not match subject state")
    if require_active and canonical["candidate_state"] != "active":
        raise CandidateResearchError("candidate research subject is not active")
    return canonical


def revalidate_candidate_research_subject(
    subject: object, current_subject: object
) -> dict:
    original = validate_candidate_research_subject(subject, require_active=True)
    current = validate_candidate_research_subject(current_subject, require_active=True)
    if original != current:
        raise CandidateResearchError("candidate research subject is stale")
    return original


def build_authoritative_user_turn(turn_id: str, text: str) -> dict:
    turn_id = _text(turn_id, name="turn_id", maximum=256)
    if not TURN_ID_RE.fullmatch(turn_id):
        raise CandidateResearchError("turn_id contains non-portable characters")
    text = _text(text, name="text", maximum=MAX_TURN_TEXT)
    source = {"turn_id": turn_id, "role": "user", "text": text}
    return {
        "schema_version": SCHEMA_VERSION,
        **source,
        "turn_revision": canonical_revision(source),
    }


def validate_authoritative_user_turn(value: object) -> dict:
    turn = _object(value, name="user_turn", keys=_TURN_KEYS)
    if turn["schema_version"] != SCHEMA_VERSION:
        raise CandidateResearchError("user_turn.schema_version must be 1")
    if turn["role"] != "user":
        raise CandidateResearchError("only authoritative user turns are evidence")
    canonical = build_authoritative_user_turn(turn["turn_id"], turn["text"])
    if (
        _revision(turn["turn_revision"], name="turn_revision")
        != canonical["turn_revision"]
    ):
        raise CandidateResearchError("turn_revision does not match exact user turn")
    return canonical


def _turn_index(authoritative_turns: Sequence[dict]) -> dict[str, dict]:
    if not isinstance(authoritative_turns, Sequence) or isinstance(
        authoritative_turns, (str, bytes)
    ):
        raise CandidateResearchError("authoritative_turns must be a sequence")
    result: dict[str, dict] = {}
    for turn in authoritative_turns:
        canonical = validate_authoritative_user_turn(turn)
        if canonical["turn_id"] in result:
            raise CandidateResearchError("authoritative turn ids must be unique")
        result[canonical["turn_id"]] = canonical
    return result


def extract_research_evidence_span(
    turn: dict, start: int, end: int, evidence_kind: str
) -> dict:
    canonical_turn = validate_authoritative_user_turn(turn)
    if isinstance(start, bool) or isinstance(end, bool):
        raise CandidateResearchError("evidence offsets must be integers")
    if not isinstance(start, int) or not isinstance(end, int):
        raise CandidateResearchError("evidence offsets must be integers")
    if start < 0 or end <= start or end > len(canonical_turn["text"]):
        raise CandidateResearchError("evidence offsets are out of bounds")
    if evidence_kind not in EVIDENCE_KINDS:
        raise CandidateResearchError("evidence_kind is invalid")
    source = {
        "turn_id": canonical_turn["turn_id"],
        "turn_revision": canonical_turn["turn_revision"],
        "start": start,
        "end": end,
        "quote": canonical_turn["text"][start:end],
        "evidence_kind": evidence_kind,
    }
    return {
        "schema_version": SCHEMA_VERSION,
        **source,
        "evidence_revision": canonical_revision(source),
    }


def validate_research_evidence_span(
    value: object, authoritative_turns: Sequence[dict]
) -> dict:
    span = _object(value, name="evidence_span", keys=_SPAN_KEYS)
    if span["schema_version"] != SCHEMA_VERSION:
        raise CandidateResearchError("evidence_span.schema_version must be 1")
    turns = _turn_index(authoritative_turns)
    turn_id = _text(span["turn_id"], name="evidence_span.turn_id", maximum=256)
    turn = turns.get(turn_id)
    if turn is None:
        raise CandidateResearchError("evidence_span names a non-authoritative turn")
    if (
        _revision(span["turn_revision"], name="evidence_span.turn_revision")
        != turn["turn_revision"]
    ):
        raise CandidateResearchError("evidence_span turn revision is stale")
    canonical = extract_research_evidence_span(
        turn, span["start"], span["end"], span["evidence_kind"]
    )
    if span["quote"] != canonical["quote"]:
        raise CandidateResearchError("evidence quote is not the exact user-turn slice")
    if (
        _revision(span["evidence_revision"], name="evidence_span.evidence_revision")
        != canonical["evidence_revision"]
    ):
        raise CandidateResearchError("evidence_revision does not match exact span")
    return canonical


def _is_substantive(span: dict) -> bool:
    quote = str(span["quote"])
    characters = len(re.sub(r"\s", "", quote))
    return (
        characters >= SUBSTANTIVE_MIN_CHARACTERS
        and len(WORD_RE.findall(quote)) >= SUBSTANTIVE_MIN_WORDS
    )


def _validate_evidence(
    evidence: object, authoritative_turns: Sequence[dict]
) -> list[dict]:
    if not isinstance(evidence, list) or len(evidence) > MAX_EVIDENCE_SPANS:
        raise CandidateResearchError(
            f"evidence must be a list of at most {MAX_EVIDENCE_SPANS} spans"
        )
    canonical = [
        validate_research_evidence_span(span, authoritative_turns) for span in evidence
    ]
    seen: set[str] = set()
    by_turn: dict[str, list[tuple[int, int]]] = {}
    for span in canonical:
        if span["evidence_kind"] == "confirmation":
            raise CandidateResearchError("confirmation spans do not belong in evidence")
        revision = span["evidence_revision"]
        if revision in seen:
            raise CandidateResearchError("evidence spans must not be duplicated")
        seen.add(revision)
        intervals = by_turn.setdefault(span["turn_id"], [])
        for start, end in intervals:
            if span["start"] < end and start < span["end"]:
                raise CandidateResearchError(
                    "evidence spans from one turn must not overlap"
                )
        intervals.append((span["start"], span["end"]))
    return canonical


def _dimensions_for(subject: dict) -> tuple[str, ...]:
    return (
        FOCUS_DIMENSIONS
        if subject["candidate_kind"] == "focus_candidate"
        else ENTITY_DIMENSIONS
    )


def _normalize_dimensions(
    subject: dict, dimension_evidence: object, evidence: list[dict]
) -> dict[str, list[str]]:
    if not isinstance(dimension_evidence, dict):
        raise CandidateResearchError("dimension_evidence must be an object")
    expected = frozenset(_dimensions_for(subject))
    actual = frozenset(dimension_evidence)
    if actual != expected:
        raise CandidateResearchError(
            "dimension_evidence must contain the exact dimension roster"
        )
    valid = {span["evidence_revision"]: span for span in evidence}
    used: set[str] = set()
    normalized: dict[str, list[str]] = {}
    for dimension in _dimensions_for(subject):
        refs = dimension_evidence[dimension]
        if not isinstance(refs, list):
            raise CandidateResearchError(f"dimension {dimension} must be a list")
        if len(refs) != len(set(refs)):
            raise CandidateResearchError(
                f"dimension {dimension} has duplicate evidence"
            )
        clean: list[str] = []
        for ref in refs:
            ref = _revision(ref, name=f"dimension_evidence.{dimension}")
            span = valid.get(ref)
            if span is None:
                raise CandidateResearchError(
                    f"dimension {dimension} references unknown evidence"
                )
            if not _is_substantive(span):
                raise CandidateResearchError(
                    f"dimension {dimension} references non-substantive evidence"
                )
            clean.append(ref)
            used.add(ref)
        normalized[dimension] = clean
    if used != set(valid):
        raise CandidateResearchError(
            "every evidence span must support at least one dimension"
        )
    return normalized


def _normalize_seed_questions(value: object) -> list[dict]:
    if not isinstance(value, list) or len(value) > MAX_SEED_QUESTIONS:
        raise CandidateResearchError(
            f"seed_questions must be a list of at most {MAX_SEED_QUESTIONS} entries"
        )
    out: list[dict] = []
    seen: set[str] = set()
    for index, raw in enumerate(value):
        row = _object(raw, name=f"seed_questions[{index}]", keys=_SEED_QUESTION_KEYS)
        question = _text(
            row["question"], name=f"seed_questions[{index}].question", maximum=1_000
        )
        if row["evidence"] is not False:
            raise CandidateResearchError(
                "generated seed questions must declare evidence=false"
            )
        if question in seen:
            raise CandidateResearchError("seed questions must not be duplicated")
        seen.add(question)
        out.append({"question": question, "evidence": False})
    return out


def recompute_research_assessment(
    *,
    subject: dict,
    evidence: list[dict],
    dimension_evidence: dict[str, list[str]],
    seed_questions: list[dict],
) -> dict:
    subject = validate_candidate_research_subject(subject, require_active=True)
    substantive = sum(1 for span in evidence if _is_substantive(span))
    concrete = sum(
        1 for span in evidence if span["evidence_kind"] in CONCRETE_EVIDENCE_KINDS
    )
    missing = [
        f"dimension:{dimension}"
        for dimension in _dimensions_for(subject)
        if not dimension_evidence[dimension]
    ]
    if subject["candidate_kind"] == "focus_candidate":
        minimum = FOCUS_MIN_EVIDENCE_SPANS
        if len(seed_questions) < FOCUS_MIN_SEED_QUESTIONS:
            missing.append("seed_questions")
    else:
        minimum = ENTITY_MIN_EVIDENCE_SPANS[subject["subject_type"]]
    if substantive < minimum:
        missing.append(f"substantive_evidence:{minimum}")
    if concrete < 1:
        missing.append("concrete_evidence")
    return {
        "ready": not missing,
        "missing": sorted(missing),
        "substantive_evidence_count": substantive,
        "concrete_evidence_count": concrete,
        "seed_question_count": len(seed_questions),
    }


def _assessment_core(
    subject: dict,
    evidence: list[dict],
    dimension_evidence: dict[str, list[str]],
    seed_questions: list[dict],
    readiness: dict,
) -> dict:
    return {
        "subject": subject,
        "evidence": evidence,
        "dimension_evidence": dimension_evidence,
        "seed_questions": seed_questions,
        "readiness": readiness,
    }


def _normalize_confirmation(
    value: object,
    *,
    assessment_revision: str,
    authoritative_turns: Sequence[dict],
) -> dict | None:
    if value is None:
        return None
    confirmation = _object(value, name="confirmation", keys=_CONFIRMATION_KEYS)
    if confirmation["status"] != "confirmed":
        raise CandidateResearchError("confirmation.status must be confirmed")
    supplied_assessment = _revision(
        confirmation["assessment_revision"], name="confirmation.assessment_revision"
    )
    if supplied_assessment != assessment_revision:
        raise CandidateResearchError("confirmation binds a stale assessment")
    span = validate_research_evidence_span(
        confirmation["evidence"], authoritative_turns
    )
    if span["evidence_kind"] != "confirmation":
        raise CandidateResearchError("confirmation requires an exact confirmation span")
    confirmed_at = _utc_seconds(
        confirmation["confirmed_at"], name="confirmation.confirmed_at"
    )
    source = {
        "status": "confirmed",
        "assessment_revision": assessment_revision,
        "evidence": span,
        "confirmed_at": confirmed_at,
    }
    revision = canonical_revision(source)
    if (
        _revision(
            confirmation["confirmation_revision"],
            name="confirmation.confirmation_revision",
        )
        != revision
    ):
        raise CandidateResearchError(
            "confirmation_revision does not match confirmation"
        )
    return {**source, "confirmation_revision": revision}


def build_research_confirmation(
    assessment: dict,
    *,
    turn: dict,
    start: int,
    end: int,
    confirmed_at: str,
    authoritative_turns: Sequence[dict],
) -> dict:
    canonical = validate_research_assessment(
        assessment, authoritative_turns=authoritative_turns
    )
    if not canonical["readiness"]["ready"]:
        raise CandidateResearchError("research cannot be confirmed before readiness")
    span = extract_research_evidence_span(turn, start, end, "confirmation")
    if span != validate_research_evidence_span(span, authoritative_turns):
        raise CandidateResearchError("confirmation turn is not authoritative")
    source = {
        "status": "confirmed",
        "assessment_revision": canonical["assessment_revision"],
        "evidence": span,
        "confirmed_at": _utc_seconds(confirmed_at, name="confirmed_at"),
    }
    return {**source, "confirmation_revision": canonical_revision(source)}


def build_research_assessment(
    *,
    subject: dict,
    evidence: list[dict],
    dimension_evidence: dict[str, list[str]],
    seed_questions: list[dict],
    authoritative_turns: Sequence[dict],
    confirmation: dict | None = None,
) -> dict:
    subject = validate_candidate_research_subject(subject, require_active=True)
    canonical_evidence = _validate_evidence(evidence, authoritative_turns)
    dimensions = _normalize_dimensions(subject, dimension_evidence, canonical_evidence)
    questions = _normalize_seed_questions(seed_questions)
    readiness = recompute_research_assessment(
        subject=subject,
        evidence=canonical_evidence,
        dimension_evidence=dimensions,
        seed_questions=questions,
    )
    core = _assessment_core(
        subject, canonical_evidence, dimensions, questions, readiness
    )
    assessment_revision = canonical_revision(core)
    canonical_confirmation = _normalize_confirmation(
        confirmation,
        assessment_revision=assessment_revision,
        authoritative_turns=authoritative_turns,
    )
    complete = bool(readiness["ready"] and canonical_confirmation is not None)
    research_revision = canonical_revision(
        {
            "assessment_revision": assessment_revision,
            "confirmation": canonical_confirmation,
        }
    )
    return {
        "schema_version": SCHEMA_VERSION,
        **core,
        "assessment_revision": assessment_revision,
        "confirmation": canonical_confirmation,
        "complete": complete,
        "research_revision": research_revision,
    }


def validate_research_assessment(
    value: object,
    *,
    authoritative_turns: Sequence[dict],
    current_subject: dict | None = None,
) -> dict:
    assessment = _object(value, name="assessment", keys=_ASSESSMENT_KEYS)
    if assessment["schema_version"] != SCHEMA_VERSION:
        raise CandidateResearchError("assessment.schema_version must be 1")
    canonical = build_research_assessment(
        subject=assessment["subject"],
        evidence=assessment["evidence"],
        dimension_evidence=assessment["dimension_evidence"],
        seed_questions=assessment["seed_questions"],
        authoritative_turns=authoritative_turns,
        confirmation=assessment["confirmation"],
    )
    if current_subject is not None:
        revalidate_candidate_research_subject(canonical["subject"], current_subject)
    supplied_readiness = _object(
        assessment["readiness"], name="readiness", keys=_READINESS_KEYS
    )
    if supplied_readiness != canonical["readiness"]:
        raise CandidateResearchError("readiness does not match recomputation")
    if (
        _revision(assessment["assessment_revision"], name="assessment_revision")
        != canonical["assessment_revision"]
    ):
        raise CandidateResearchError("assessment_revision does not match assessment")
    if assessment["complete"] is not canonical["complete"]:
        raise CandidateResearchError(
            "complete does not match readiness and confirmation"
        )
    if (
        _revision(assessment["research_revision"], name="research_revision")
        != canonical["research_revision"]
    ):
        raise CandidateResearchError("research_revision does not match assessment")
    return canonical


def confirm_research_assessment(
    assessment: dict,
    *,
    turn: dict,
    start: int,
    end: int,
    confirmed_at: str,
    authoritative_turns: Sequence[dict],
) -> dict:
    confirmation = build_research_confirmation(
        assessment,
        turn=turn,
        start=start,
        end=end,
        confirmed_at=confirmed_at,
        authoritative_turns=authoritative_turns,
    )
    return build_research_assessment(
        subject=assessment["subject"],
        evidence=assessment["evidence"],
        dimension_evidence=assessment["dimension_evidence"],
        seed_questions=assessment["seed_questions"],
        authoritative_turns=authoritative_turns,
        confirmation=confirmation,
    )


def _identity_digest(candidate_kind: str, candidate_id: str) -> str:
    return hashlib.sha256(f"{candidate_kind}\0{candidate_id}".encode()).hexdigest()


def candidate_research_source_path(candidate_kind: str, candidate_id: str) -> str:
    if candidate_kind not in RESEARCH_KINDS:
        raise CandidateResearchError("candidate_kind is invalid")
    candidate_id = _text(candidate_id, name="candidate_id", maximum=256)
    digest = _identity_digest(candidate_kind, candidate_id)[:32]
    return (SOURCE_ROOT / candidate_kind / f"{digest}.md").as_posix()


def candidate_research_source_id(candidate_kind: str, candidate_id: str) -> str:
    if candidate_kind not in RESEARCH_KINDS:
        raise CandidateResearchError("candidate_kind is invalid")
    candidate_id = _text(candidate_id, name="candidate_id", maximum=256)
    return f"candidate-research:{candidate_kind}:{_identity_digest(candidate_kind, candidate_id)}"


def _marker_payload(assessment: dict, source_id: str, source_path: str) -> dict:
    subject = assessment["subject"]
    return {
        "schema_version": SCHEMA_VERSION,
        "candidate_kind": subject["candidate_kind"],
        "candidate_id": subject["candidate_id"],
        "identity_revision": subject["identity_revision"],
        "subject_revision": subject["subject_revision"],
        "assessment_revision": assessment["assessment_revision"],
        "research_revision": assessment["research_revision"],
        "source_id": source_id,
        "source_path": source_path,
    }


def encode_candidate_research_marker(payload: dict) -> str:
    payload = _object(payload, name="marker", keys=_MARKER_KEYS)
    if payload["schema_version"] != SCHEMA_VERSION:
        raise CandidateResearchError("marker.schema_version must be 1")
    raw = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    return f"{MARKER_PREFIX}{base64.b64encode(raw).decode('ascii')}{MARKER_SUFFIX}"


def decode_candidate_research_marker(line: str) -> dict:
    if (
        not isinstance(line, str)
        or not line.startswith(MARKER_PREFIX)
        or not line.endswith(MARKER_SUFFIX)
    ):
        raise CandidateResearchError("candidate-research marker is malformed")
    encoded = line[len(MARKER_PREFIX) : -len(MARKER_SUFFIX)]
    if len(encoded) > MAX_MARKER_PAYLOAD_BYTES * 2:
        raise CandidateResearchError("candidate-research marker is too large")
    try:
        raw = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise CandidateResearchError(
            "candidate-research marker base64 is invalid"
        ) from exc
    if len(raw) > MAX_MARKER_PAYLOAD_BYTES:
        raise CandidateResearchError("candidate-research marker payload is too large")
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CandidateResearchError(
            "candidate-research marker JSON is invalid"
        ) from exc
    payload = _object(payload, name="marker", keys=_MARKER_KEYS)
    if encode_candidate_research_marker(payload) != line:
        raise CandidateResearchError(
            "candidate-research marker encoding is non-canonical"
        )
    return payload


def _indented_literal(text: str) -> list[str]:
    return [f"    {line}" if line else "    " for line in text.split("\n")]


def _source_body(assessment: dict, marker_line: str) -> str:
    reverse_dimensions: dict[str, list[str]] = {}
    for dimension, revisions in assessment["dimension_evidence"].items():
        for revision in revisions:
            reverse_dimensions.setdefault(revision, []).append(dimension)
    lines = [
        marker_line,
        "# Candidate research evidence",
        "",
        "Only the literal user-turn excerpts below are evidence.",
        "",
        "## User-grounded evidence",
    ]
    for index, span in enumerate(assessment["evidence"], start=1):
        dimensions = ", ".join(reverse_dimensions[span["evidence_revision"]])
        lines.extend(
            [
                "",
                f"### Evidence {index} — {span['evidence_kind'].replace('_', ' ')}",
                "",
                f"Turn `{span['turn_id']}` · code points {span['start']}:{span['end']} · "
                f"dimensions: {dimensions}",
                "",
                *_indented_literal(span["quote"]),
            ]
        )
    lines.extend(["", "## Generated seed questions — not evidence"])
    if assessment["seed_questions"]:
        for index, question in enumerate(assessment["seed_questions"], start=1):
            lines.extend(
                [
                    "",
                    f"### Generated question {index} (not evidence)",
                    "",
                    *_indented_literal(question["question"]),
                ]
            )
    else:
        lines.extend(["", "None."])
    return "\n".join(lines).rstrip() + "\n"


def build_candidate_research_source(
    assessment: dict,
    *,
    authoritative_turns: Sequence[dict],
    current_subject: dict | None = None,
) -> dict:
    assessment = validate_research_assessment(
        assessment,
        authoritative_turns=authoritative_turns,
        current_subject=current_subject,
    )
    if not assessment["complete"]:
        raise CandidateResearchError("only confirmed ready research can become source")
    subject = assessment["subject"]
    source_path = candidate_research_source_path(
        subject["candidate_kind"], subject["candidate_id"]
    )
    source_id = candidate_research_source_id(
        subject["candidate_kind"], subject["candidate_id"]
    )
    marker = _marker_payload(assessment, source_id, source_path)
    marker_line = encode_candidate_research_marker(marker)
    body = _source_body(assessment, marker_line)
    metadata = {
        "title": f"Candidate research — {subject['subject_label']}",
        "type": "candidate_research",
        "source_id": source_id,
        "source_medium": "candidate_research",
        "source_trust": "user_attested_primary",
        "authority": "first_person_memory",
        "candidate_kind": subject["candidate_kind"],
        "candidate_id": subject["candidate_id"],
        "subject_type": subject["subject_type"],
        "subject_label": subject["subject_label"],
        "subject_slug": subject["subject_slug"],
        "subject_aliases": subject["subject_aliases"],
        "identity_revision": subject["identity_revision"],
        "subject_revision": subject["subject_revision"],
        "assessment_revision": assessment["assessment_revision"],
        "research_revision": assessment["research_revision"],
        "user_confirmed": True,
        "evidence_span_count": len(assessment["evidence"]),
        "generated_seed_questions_evidence": False,
        "captured_at": assessment["confirmation"]["confirmed_at"],
        "visibility": "owner_only",
        "status": "raw",
        "immutable": True,
        "schema_version": SCHEMA_VERSION,
        "source_path": source_path,
        "content_sha256": payload_sha256(body),
    }
    source_text = f"{format_frontmatter(metadata)}\n\n{body}"
    return {
        "schema_version": SCHEMA_VERSION,
        "candidate_kind": subject["candidate_kind"],
        "candidate_id": subject["candidate_id"],
        "subject_type": subject["subject_type"],
        "source_id": source_id,
        "source_path": source_path,
        "research_revision": assessment["research_revision"],
        "content_sha256": metadata["content_sha256"],
        "marker_line": marker_line,
        "metadata": metadata,
        "manifest_fields": {
            key: metadata[key] for key in CANDIDATE_RESEARCH_MANIFEST_FIELDS
        },
        "source_bytes": source_text.encode("utf-8"),
    }


def _validate_source_path(
    path: object, *, candidate_kind: str, candidate_id: str
) -> str:
    path = _text(path, name="source_path", maximum=512)
    parsed = PurePosixPath(path)
    if parsed.is_absolute() or ".." in parsed.parts or "\\" in path:
        raise CandidateResearchError("candidate research source path is unsafe")
    expected = candidate_research_source_path(candidate_kind, candidate_id)
    if path != expected:
        raise CandidateResearchConflict(
            "candidate research source path conflicts with identity"
        )
    return path


def validate_candidate_research_source_text(
    content: str, *, expected_path: str | None = None
) -> dict:
    if not isinstance(content, str):
        raise CandidateResearchError("candidate research source must be text")
    metadata, body = split_frontmatter(content)
    if body == content or not isinstance(metadata, dict):
        raise CandidateResearchError("candidate research source requires frontmatter")
    marker_lines = [
        line for line in body.splitlines() if line.startswith(MARKER_PREFIX)
    ]
    if len(marker_lines) != 1 or body.splitlines()[0] != marker_lines[0]:
        raise CandidateResearchError(
            "candidate research source requires one leading marker"
        )
    marker = decode_candidate_research_marker(marker_lines[0])
    if marker["schema_version"] != SCHEMA_VERSION:
        raise CandidateResearchError("candidate research marker schema is invalid")
    kind = marker["candidate_kind"]
    candidate_id = marker["candidate_id"]
    path = _validate_source_path(
        metadata.get("source_path"), candidate_kind=kind, candidate_id=candidate_id
    )
    if expected_path is not None and path != expected_path:
        raise CandidateResearchConflict("candidate research file lives at another path")
    fixed = {
        "type": "candidate_research",
        "source_id": marker["source_id"],
        "source_medium": "candidate_research",
        "source_trust": "user_attested_primary",
        "authority": "first_person_memory",
        "candidate_kind": kind,
        "candidate_id": candidate_id,
        "identity_revision": marker["identity_revision"],
        "subject_revision": marker["subject_revision"],
        "assessment_revision": marker["assessment_revision"],
        "research_revision": marker["research_revision"],
        "user_confirmed": True,
        "generated_seed_questions_evidence": False,
        "visibility": "owner_only",
        "status": "raw",
        "immutable": True,
        "schema_version": SCHEMA_VERSION,
        "source_path": path,
    }
    for key, expected in fixed.items():
        if metadata.get(key) != expected:
            raise CandidateResearchError(
                f"candidate research metadata {key} is invalid"
            )
    subject_type = metadata.get("subject_type")
    allowed = FOCUS_SUBJECT_TYPES if kind == "focus_candidate" else ENTITY_SUBJECT_TYPES
    if subject_type not in allowed:
        raise CandidateResearchError("candidate research subject_type is invalid")
    _text(metadata.get("subject_label"), name="subject_label", maximum=512)
    subject_slug = _text(metadata.get("subject_slug"), name="subject_slug", maximum=256)
    if not SLUG_RE.fullmatch(subject_slug):
        raise CandidateResearchError("candidate research subject_slug is invalid")
    _aliases(metadata.get("subject_aliases"))
    source_id = candidate_research_source_id(kind, candidate_id)
    if marker["source_id"] != source_id or marker["source_path"] != path:
        raise CandidateResearchError("candidate research marker identity is invalid")
    for key in (
        "identity_revision",
        "subject_revision",
        "assessment_revision",
        "research_revision",
    ):
        _revision(marker[key], name=f"marker.{key}")
    count = metadata.get("evidence_span_count")
    if (
        isinstance(count, bool)
        or not isinstance(count, int)
        or not 1 <= count <= MAX_EVIDENCE_SPANS
    ):
        raise CandidateResearchError(
            "candidate research evidence_span_count is invalid"
        )
    if body.count("\n### Evidence ") != count:
        raise CandidateResearchError(
            "candidate research evidence count does not match body"
        )
    if "## Generated seed questions — not evidence" not in body:
        raise CandidateResearchError(
            "candidate research seed questions are not labeled"
        )
    declared_hash = metadata.get("content_sha256")
    if not isinstance(declared_hash, str) or not CONTENT_HASH_RE.fullmatch(
        declared_hash
    ):
        raise CandidateResearchError("candidate research content_sha256 is invalid")
    if declared_hash != payload_sha256(body):
        raise CandidateResearchError(
            "candidate research content hash does not match body"
        )
    return {"metadata": metadata, "marker": marker, "body": body, "source_path": path}


def resolve_candidate_research_source(
    assessment: dict,
    *,
    authoritative_turns: Sequence[dict],
    authority: CandidateResearchGitAuthority,
    current_subject: dict | None = None,
    vault_root: str | Path | None = None,
    push: bool = True,
    failpoint: Callable[[str], None] | None = None,
) -> dict:
    plan = build_candidate_research_source(
        assessment,
        authoritative_turns=authoritative_turns,
        current_subject=current_subject,
    )
    raw = authority.resolve_exact_source(
        plan,
        vault_root=vault_root,
        push=push,
        failpoint=failpoint,
    )
    result = _object(raw, name="authority_receipt", keys=_AUTHORITY_RECEIPT_KEYS)
    if result["source_path"] != plan["source_path"]:
        raise CandidateResearchConflict(
            "Git authority returned a different source path"
        )
    if type(result["changed"]) is not bool:
        raise CandidateResearchError("Git authority changed must be boolean")
    commit_sha = result["commit_sha"]
    if not isinstance(commit_sha, str) or not COMMIT_RE.fullmatch(commit_sha):
        raise CandidateResearchError("Git authority commit_sha is invalid")
    return {
        "candidate_kind": plan["candidate_kind"],
        "candidate_id": plan["candidate_id"],
        "subject_type": plan["subject_type"],
        "source_id": plan["source_id"],
        "source_path": plan["source_path"],
        "research_revision": plan["research_revision"],
        "content_sha256": plan["content_sha256"],
        "changed": result["changed"],
        "commit_sha": commit_sha,
    }
