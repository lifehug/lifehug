#!/usr/bin/env python3
"""Runtime authority for the registered Focus Candidate Interaction."""

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
from roadmap import FOCUS_TYPES
from vault_paths import read_vault_text, vault_data_path

SCHEMA_VERSION = 1
FOCUS_DIMENSIONS = (
    "focus_identity",
    "why_it_matters",
    "scope_boundary",
    "present_state_direction",
    "relationships",
    "grounded_evidence",
    "tensions",
    "open_questions",
)
FOCUS_TO_RESEARCH_DIMENSION = {
    "focus_identity": "identity",
    "why_it_matters": "why_it_matters",
    "scope_boundary": "scope_boundary",
    "present_state_direction": "present_state_or_direction",
    "relationships": "relationships",
    "tensions": "tensions",
    "open_questions": "open_questions",
}
ACTIONS = frozenset(
    {"ask_gap", "offer_confirmation", "accept_confirmation", "continue"}
)
STATUSES = frozenset({"continue", "awaiting_confirmation", "complete", "invalid"})
MAX_PROPOSAL_SPANS = 16
#: focus-onboarding-context (v189, Design §B.2): the closed relationship
#: vocabulary for `focus_setup.relationship` and roadmap.py's `relationship`
#: user field (`_USER_FIELDS`, whose own comment names it "which interview
#: bank fits (parent/spouse/child/...)"). Every entry maps to a real
#: `research_expand.INTERVIEW_BANKS` bank (see FOCUS_RELATIONSHIP_BANK) so a
#: validated value always selects a question bank rather than silently
#: falling through to the generic one.
FOCUS_RELATIONSHIPS = (
    "parent",
    "grandparent",
    "child",
    "sibling",
    "spouse",
    "partner",
    "friend",
    "colleague",
    "mentor",
    "other",
)
#: relationship -> the `research_expand.INTERVIEW_BANKS` key that fits it.
#: Only the three that have no bank of their own are mapped; the rest are
#: bank names already. `living is False` overrides all of this with the
#: `remembering` bank (Design §E.2).
FOCUS_RELATIONSHIP_BANK = {
    "partner": "spouse",
    "colleague": "cofounder",
    "other": "friend",
}
MAX_FOCUS_OBJECTIVE_CHARS = 200
MAX_FOCUS_LABEL_CHARS = 80
MAX_FIRST_ANSWER_CHARS = 1_200
#: The two `{focus_stage}` values the leaf is keyed on (Design §A.2/§C).
VALID_FOCUS_STAGES = frozenset({"establish", "settled"})
MAX_REPLY_CHARS = 2_200
MAX_PREVIOUS_QUESTION_CHARS = 2_200
_REVISION_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
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
    r"|preserve\s+(?:it|this|these)(?:\s+exact)?"
    r"(?:\s+(?:research|excerpts))?"
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
    + "|".join(re.escape(name) for name in FOCUS_DIMENSIONS)
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


class FocusCandidateError(ValueError):
    """Focus Candidate input or proposal violated the closed contract."""


def _object(value: object, *, name: str, keys: frozenset[str]) -> dict:
    if not isinstance(value, dict):
        raise FocusCandidateError(f"{name} must be an object")
    actual = frozenset(value)
    if actual != keys:
        raise FocusCandidateError(
            f"{name} keys invalid: missing={sorted(keys - actual)}, "
            f"unknown={sorted(actual - keys)}"
        )
    return value


def _text(value: object, *, name: str, maximum: int) -> str:
    if not isinstance(value, str) or not value.strip():
        raise FocusCandidateError(f"{name} must be a non-empty string")
    if len(value) > maximum:
        raise FocusCandidateError(f"{name} exceeds {maximum} characters")
    return value


def _nullable_text(value: object, *, name: str, maximum: int) -> str | None:
    if value is None:
        return None
    return _text(value, name=name, maximum=maximum)


def _state_path(vault_root: str | Path | None) -> Path:
    root = Path(vault_root) if vault_root is not None else REPO_DIR
    return vault_data_path("focus_recommendations", vault_root=root)


def _vault_root(vault_root: str | Path | None) -> Path:
    return Path(vault_root) if vault_root is not None else REPO_DIR


def load_focus_candidate_subject(
    candidate_id: str, *, vault_root: str | Path | None = None
) -> dict:
    """Resolve one recommendation from canonical state; never trust a client anchor."""
    candidate_id = _text(candidate_id, name="candidate_id", maximum=256)
    root = _vault_root(vault_root)
    path = _state_path(root)
    try:
        state = json.loads(read_vault_text(path, vault_root=root, encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise FocusCandidateError(
            "cannot load canonical focus recommendations"
        ) from exc
    if not isinstance(state, dict) or state.get("version") != 1:
        raise FocusCandidateError("focus recommendation state schema is invalid")
    matches: list[tuple[str, dict]] = []
    allowed_statuses = {
        "recommendations": {"pending", "approved"},
        "dismissed": {"dismissed", "expired"},
    }
    for collection in ("recommendations", "dismissed"):
        rows = state.get(collection, [])
        if not isinstance(rows, list):
            raise FocusCandidateError(f"focus recommendation {collection} is invalid")
        for row in rows:
            if not isinstance(row, dict) or row.get("id") != candidate_id:
                continue
            if row.get("status") not in allowed_statuses[collection]:
                raise FocusCandidateError(
                    "focus recommendation collection/status contradiction"
                )
            matches.append((collection, row))
    if len(matches) != 1:
        raise FocusCandidateError("focus candidate id must resolve exactly once")
    try:
        subject = candidate_research.build_focus_candidate_subject(matches[0][1])
        return candidate_research.validate_candidate_research_subject(
            subject, require_active=True
        )
    except candidate_research.CandidateResearchError as exc:
        raise FocusCandidateError(str(exc)) from exc


def build_focus_candidate_input(
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
        raise FocusCandidateError("candidate_id does not match current subject")
    payload = {
        "schema_version": SCHEMA_VERSION,
        "candidate_id": candidate_id,
        "subject_revision": subject["subject_revision"],
        "authoritative_turns": list(authoritative_turns),
        "assessment": assessment,
        "latest_turn_id": latest_turn_id,
        "previous_question": previous_question,
    }
    return validate_focus_candidate_input(payload, current_subject=subject)


def validate_focus_candidate_input(value: object, *, current_subject: dict) -> dict:
    payload = _object(value, name="input", keys=_INPUT_KEYS)
    if payload["schema_version"] != SCHEMA_VERSION:
        raise FocusCandidateError("input.schema_version must be 1")
    subject = candidate_research.validate_candidate_research_subject(
        current_subject, require_active=True
    )
    candidate_id = _text(payload["candidate_id"], name="candidate_id", maximum=256)
    if candidate_id != subject["candidate_id"]:
        raise FocusCandidateError("candidate_id does not match current subject")
    revision = payload["subject_revision"]
    if not isinstance(revision, str) or not _REVISION_RE.fullmatch(revision):
        raise FocusCandidateError("subject_revision must be sha256:<64 lowercase hex>")
    if revision != subject["subject_revision"]:
        raise FocusCandidateError("focus candidate subject revision is stale")
    turns = (
        [
            candidate_research.validate_authoritative_user_turn(turn)
            for turn in payload["authoritative_turns"]
        ]
        if isinstance(payload["authoritative_turns"], list)
        else None
    )
    if turns is None:
        raise FocusCandidateError("authoritative_turns must be a list")
    ids = [turn["turn_id"] for turn in turns]
    if len(ids) != len(set(ids)):
        raise FocusCandidateError("authoritative turn ids must be unique")
    latest = _nullable_text(
        payload["latest_turn_id"], name="latest_turn_id", maximum=256
    )
    if latest is not None and latest not in ids:
        raise FocusCandidateError("latest_turn_id is not authoritative")
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
            raise FocusCandidateError("completed focus research cannot continue")
    return {
        "schema_version": SCHEMA_VERSION,
        "candidate_id": candidate_id,
        "subject_revision": revision,
        "authoritative_turns": turns,
        "assessment": assessment,
        "latest_turn_id": latest,
        "previous_question": previous,
    }


#: focus-onboarding-context (v189, Design §A.3): the RESEARCH-mode output
#: contract, byte-for-byte as `prompt/turn-instructions.md` carried it
#: through v188. It moved out of the leaf because the leaf is now REPLAYed
#: by the platform and appended to an ordinary Conversation prompt that
#: already declares its own OUTPUT FORMAT appendix — two competing "return
#: exactly one JSON object with exactly these keys" contracts in one prompt
#: is a defect, not a composition. This is the parent's own pattern, not an
#: invention: `conversation_delivery._output_contract_block` exists for the
#: same reason — the ENGINE appends the machine-readable shape, the leaf
#: holds behavior. `parse_focus_candidate_output` and the standalone
#: `focus-candidate-prompt` / `focus-candidate-complete` CLI path are
#: unchanged; test_research_output_contract_survives_the_leaf_move pins it.
_RESEARCH_OUTPUT_CONTRACT = """Return exactly one JSON object with exactly these keys and no prose or fence:

```json
{
  "reply": "string",
  "action": "ask_gap|offer_confirmation|accept_confirmation|continue",
  "next_gap": "focus_identity|why_it_matters|scope_boundary|present_state_direction|relationships|grounded_evidence|tensions|open_questions|null",
  "evidence_spans": [{"turn_id":"string","start":0,"end":1,"evidence_kind":"statement|concrete_event|concrete_observation"}],
  "dimension_evidence": {
    "focus_identity": [], "why_it_matters": [], "scope_boundary": [],
    "present_state_direction": [], "relationships": [],
    "grounded_evidence": [], "tensions": [], "open_questions": []
  },
  "seed_questions": ["string"],
  "confirmation_span": null
}
```

Offsets are Unicode code-point slices of exact user turns. Dimension arrays
index only this output's evidence spans. Mark grounded evidence only for a
concrete event or observation, and also connect that span to a substantive
dimension. Ask at most one natural open question. Use `offer_confirmation`
only when the supplied deterministic state is ready. Use
`accept_confirmation` only for an explicit confirmation in the latest user
turn and identify its exact span. Never claim a write, commit, approval, Focus,
category, question, source, or receipt.
"""


def _research_output_contract_block() -> str:
    """The standalone research path's structured-output appendix."""
    return _RESEARCH_OUTPUT_CONTRACT


def build_focus_candidate_prompt(value: dict, *, current_subject: dict) -> str:
    payload = validate_focus_candidate_input(value, current_subject=current_subject)
    assets = [
        interaction_registry.compose_interaction_asset("focus_candidate", path)
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
        "focus_dimensions": FOCUS_DIMENSIONS,
    }
    return (
        "\n".join(assets)
        + "\n"
        + _research_output_contract_block()
        + "\n<!-- runtime-boundary:untrusted-data -->\nUNTRUSTED_DATA\n"
        + json.dumps(untrusted, ensure_ascii=False, sort_keys=True, indent=2)
        + "\nEND_UNTRUSTED_DATA\n"
    )


def _proposal(raw: object) -> dict:
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise FocusCandidateError("model output is not JSON") from exc
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


def lint_focus_candidate_reply(
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
                "lint": "focus_candidate_authority_claim",
                "detail": "reply claims lifecycle or durable-write authority",
                "span": [0, len(text)],
            }
        )
    if _INTERNAL_SCHEMA_KEY_RE.search(text):
        findings.append(
            {
                "lint": "focus_candidate_schema_leak",
                "detail": "reply exposes an internal Focus Candidate schema key",
                "span": [0, len(text)],
            }
        )
    return findings


# --------------------------------------------------------------------------
# Onboarding (focus-onboarding-context, v189) — the Play path
#
# Platform ADR 0020 + review-loop/54 retired this Interaction's original
# premise: Play is no longer read-only research toward a later approval, it
# IS the approval, and the conversation it opens exists to establish what the
# focus is about well enough that the seeded questions are worth asking. The
# research-mode machinery above is unchanged and still serves the standalone
# `focus-candidate-prompt` / `focus-candidate-complete` CLI path; everything
# below is the Play path, and it is deliberately the same shape
# `question_candidate` took for placement at v188: one pure opener, one
# transcript-derived stage, one closed validator, one lint family.
# --------------------------------------------------------------------------

#: The first thing the person sees when Play opens the tab — one short,
#: natural line per focus type, with no machinery in it. `theme` is the
#: fallback for an unknown or blank type, because "what should this focus be
#: about?" is true of every focus.
_OPENING_QUESTIONS = {
    "person": "Tell me about {entity} — who are they to you?",
    "relationship": "Tell me about {entity} — who are they to you?",
    "place": "Tell me about {entity} — what happened there that makes it matter?",
    "period": "Tell me about {entity} — what was that stretch of your life like?",
    "event": "Tell me about {entity} — what happened, and what has it meant since?",
    "project": "Tell me about {entity} — what are you making, and what is it for?",
    "lifes_work": "Tell me about {entity} — what are you making, and what is it for?",
    "self": "Tell me about {entity} — what do you want to understand about yourself here?",
    "theme": "Tell me about {entity} — what should this focus be about?",
}


def opening_question(entity: str, focus_type: str | None = None) -> str:
    """The onboarding opener for a focus Play session (Design §A.4).

    Pure — no vault, no model, no I/O. The platform shows this as the tab's
    framing line (review-loop/54 §A.2, `question_text`). A blank `entity`
    raises: an opener with no subject is a caller bug, not something to
    degrade around. An unknown or blank `focus_type` falls back to the
    `theme` line rather than failing, because a focus whose type nobody
    settled is exactly the one worth asking "what should this be about?".
    """
    subject = (entity or "").strip()
    if not subject:
        raise FocusCandidateError("opening_question requires a focus subject")
    template = _OPENING_QUESTIONS.get(
        (focus_type or "").strip(), _OPENING_QUESTIONS["theme"]
    )
    return template.format(entity=subject)


def focus_stage_for_session(session: dict) -> str:
    """Derive ``{focus_stage}`` from the transcript alone (Design §C) — no
    new session field, no new lifecycle status.

    ``"settled"`` once the session already carries any assistant
    (``role == "lifehug"``) turn: the aside and the one onboarding question
    both live on the FIRST reply, so "have we onboarded?" is exactly "does
    this session have an assistant turn?". Before that, ``"establish"``.
    Mirrors ``question_candidate.placement_stage_for_session`` exactly,
    minus the confidence branch (a focus always has a label to name).
    """
    turns = session.get("turns") or []
    if any(isinstance(turn, dict) and turn.get("role") == "lifehug" for turn in turns):
        return "settled"
    return "establish"


#: The closed key set of the additive ``focus_setup`` object, mirrored from
#: `conversation_delivery._FOCUS_SETUP_KEYS` — imported rather than
#: re-listed would create an import cycle through the delivery engine, so
#: the parity is pinned by a test instead
#: (test_focus_setup_keys_match_the_structural_layer).
_FOCUS_SETUP_KEYS = frozenset({"objective", "type", "relationship", "living", "label"})


def _capped_text(value: object, *, maximum: int) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text or len(text) > maximum:
        return None
    return text


def validate_focus_setup(value: object) -> dict | None:
    """Closed layer of the additive ``focus_setup`` field (Design §B.2).

    ``value`` is the structural layer's own output — the
    ``{objective?, type?, relationship?, living?, label?} | None`` that
    ``conversation_delivery._parse_focus_setup`` produces — or any other
    untrusted shape a caller hands in directly (this function re-checks
    shape itself so it is safe to call standalone).

    Exact membership only, in both closed vocabularies: ``type`` against
    ``roadmap.FOCUS_TYPES`` and ``relationship`` against
    ``FOCUS_RELATIONSHIPS`` — no fuzzy match, no case-fold, no derivation
    from prose, exactly as ``question_candidate.validate_placement`` treats
    the category roster. ``living`` must be a real ``bool``. ``objective``
    and ``label`` are trimmed and length-capped.

    An individually invalid value drops THAT key rather than the whole
    object (a person who told us their relationship and mistyped the focus
    type still told us their relationship); no valid key remaining returns
    ``None``.
    """
    if not isinstance(value, dict) or not set(value) <= _FOCUS_SETUP_KEYS:
        return None
    validated: dict[str, object] = {}
    objective = _capped_text(value.get("objective"), maximum=MAX_FOCUS_OBJECTIVE_CHARS)
    if objective is not None:
        validated["objective"] = objective
    label = _capped_text(value.get("label"), maximum=MAX_FOCUS_LABEL_CHARS)
    if label is not None:
        validated["label"] = label
    focus_type = value.get("type")
    if isinstance(focus_type, str) and focus_type in FOCUS_TYPES:
        validated["type"] = focus_type
    relationship = value.get("relationship")
    if isinstance(relationship, str) and relationship in FOCUS_RELATIONSHIPS:
        validated["relationship"] = relationship
    living = value.get("living")
    if isinstance(living, bool):
        validated["living"] = living
    return validated or None


def normalize_onboarding_context(value: object) -> dict:
    """Normalize the `--context-file` payload for seed generation
    (Design §E.1). Returns ``{}`` when nothing usable survives — an empty
    context is NOT an error, because Play with no answers must still seed
    from the recommendation's own evidence (owner ruling 6).

    The five setup keys go through ``validate_focus_setup`` (one authority,
    not a second copy of the vocabularies); ``first_answer`` is the user's
    own first words about the focus, trimmed and capped so a long opening
    story cannot crowd the rest of the seed prompt out.
    """
    if not isinstance(value, dict):
        return {}
    setup = {key: item for key, item in value.items() if key in _FOCUS_SETUP_KEYS}
    context = dict(validate_focus_setup(setup) or {})
    first_answer = value.get("first_answer")
    if isinstance(first_answer, str) and first_answer.strip():
        context["first_answer"] = first_answer.strip()[:MAX_FIRST_ANSWER_CHARS]
    return context


def interview_bank_key(relationship: str | None, *, living: object = None) -> str | None:
    """Which ``research_expand.INTERVIEW_BANKS`` bank fits this person
    (Design §E.2). ``living is False`` wins over everything — the
    `remembering` bank exists for exactly the case `_USER_FIELDS`' own
    comment names ("living: false on a person Focus = deceased … you can't
    ask"). ``None`` when there is no relationship to go on.
    """
    if living is False:
        return "remembering"
    if not isinstance(relationship, str) or relationship not in FOCUS_RELATIONSHIPS:
        return None
    return FOCUS_RELATIONSHIP_BANK.get(relationship, relationship)


# --------------------------------------------------------------------------
# focus_setup lints (Design §D)
# --------------------------------------------------------------------------

#: The aside's invariant anchor — "I've started a **<label>** focus — tell me
#: if the name or scope is off." The model varies the connective tissue
#: around it but not the move (owner ruling 4); this phrase is what every
#: aside lint locates.
_FOCUS_ASIDE_MARKER_RE = re.compile(
    r"\bstarted\s+(?:a|an|the)\b[^.!?]*\bfocus\b", re.IGNORECASE
)
_FOCUS_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")
#: focus_setup.settled_silence — a settled turn re-opening the focus's name,
#: type, or scope when the USER did not is the "re-litigating" failure ruling
#: 4 forbids.
_SETUP_TALK_PHRASES = (
    "name or scope",
    "rename this focus",
    "rename the focus",
    "call this focus",
    "the scope of this focus",
    "what this focus covers",
    "what this focus should cover",
    "change the focus name",
)
#: focus_setup.no_mechanism_talk — the scaffold is silent; narrating it is not.
_FOCUS_MECHANISM_PHRASES = (
    "i'll create",
    "i will create",
    "scaffold",
    "setting up your focus",
    "set up your focus",
    "adding a category",
    "seeding questions",
    "seed questions",
    "the system will",
)
def _focus_sentences(text: str) -> list[str]:
    return [s.strip() for s in _FOCUS_SENTENCE_SPLIT_RE.split(text.strip()) if s.strip()]


def _focus_span_of(text: str, needle: str) -> list[int]:
    clean = needle.strip()
    start = text.find(clean) if clean else -1
    if start == -1:
        return [0, len(text)]
    return [start, start + len(clean)]


def lint_focus_setup_reply(
    text: str, *, stage: str, user_signaled: bool = False
) -> list[dict]:
    """Deterministic findings for the six ``focus_setup_gates.*`` classes
    (Design §D). Pure — no model, no I/O. ``stage`` is the same
    ``{focus_stage}`` value the turn-instructions leaf receives
    (``"establish" | "settled"``); an unrecognized stage is treated as
    ``"settled"`` (fail toward the strictest rule: no setup talk at all).
    ``user_signaled`` is the caller's own fact — did THIS turn's user
    message change the focus's name, type, or scope — and is the only thing
    that licenses setup talk on a settled turn (owner ruling 4).

    Findings share ``conversation_lints.lint_turn``'s shape —
    ``{"lint": "<id>", "detail": "...", "span": [start, end]}`` — so a
    caller can merge them with ``lint_focus_candidate_reply``'s output
    uniformly.
    """
    findings: list[dict] = []
    sentences = _focus_sentences(text)
    aside_sentences = [s for s in sentences if _FOCUS_ASIDE_MARKER_RE.search(s)]

    if stage == "establish":
        if len(aside_sentences) != 1:
            findings.append({
                "lint": "focus_setup.aside_single_sentence",
                "detail": "the focus aside must appear exactly once, as exactly one sentence",
                "span": [0, len(text)],
            })
        elif "?" in aside_sentences[0]:
            findings.append({
                "lint": "focus_setup.aside_not_a_question",
                "detail": "the focus aside must not be a question",
                "span": _focus_span_of(text, aside_sentences[0]),
            })
    else:
        if aside_sentences:
            findings.append({
                "lint": "focus_setup.aside_never_repeated",
                "detail": "a settled turn must never restate that the focus was started",
                "span": _focus_span_of(text, aside_sentences[0]),
            })
        if not user_signaled:
            lowered_setup = text.lower()
            for phrase in _SETUP_TALK_PHRASES:
                idx = lowered_setup.find(phrase)
                if idx != -1:
                    findings.append({
                        "lint": "focus_setup.settled_silence",
                        "detail": f"setup talk on a settled turn the user did not signal: {phrase!r}",
                        "span": [idx, idx + len(phrase)],
                    })
                    break

    if text.count("?") > 1:
        findings.append({
            "lint": "focus_setup.one_setup_question",
            "detail": "at most one question per reply — onboarding never interrogates",
            "span": [0, len(text)],
        })

    lowered = text.lower()
    for phrase in _FOCUS_MECHANISM_PHRASES:
        idx = lowered.find(phrase)
        if idx != -1:
            findings.append({
                "lint": "focus_setup.no_mechanism_talk",
                "detail": f"mechanism talk: {phrase!r}",
                "span": [idx, idx + len(phrase)],
            })
            break

    return findings


def _is_explicit_confirmation(text: str) -> bool:
    return bool(
        _EXPLICIT_CONFIRMATION_RE.match(text)
    ) and not text.lstrip().lower().startswith(("no", "not", "don't", "do not"))


def _prior_parts(payload: dict) -> tuple[list[dict], dict[str, list[str]], list[dict]]:
    assessment = payload["assessment"]
    if assessment is None:
        return [], {name: [] for name in candidate_research.FOCUS_DIMENSIONS}, []
    return (
        list(assessment["evidence"]),
        {name: list(refs) for name, refs in assessment["dimension_evidence"].items()},
        list(assessment["seed_questions"]),
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
            payload["assessment"] and payload["assessment"]["readiness"]["ready"]
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


def parse_focus_candidate_output(
    raw: object,
    *,
    payload: dict,
    current_subject: dict,
    confirmed_at: str | None = None,
) -> dict:
    """Normalize an untrusted model proposal and recompute all authority facts."""
    canonical = validate_focus_candidate_input(payload, current_subject=current_subject)
    try:
        proposal = _proposal(raw)
        reply = _text(proposal["reply"], name="reply", maximum=MAX_REPLY_CHARS)
        action = proposal["action"]
        if action not in ACTIONS:
            raise FocusCandidateError("action is invalid")
        seam_ok = action == "offer_confirmation"
        if lint_focus_candidate_reply(
            reply,
            is_reply_to_substantive=_is_substantive_latest(canonical),
            seam_ok=seam_ok,
        ):
            raise FocusCandidateError("reply violates inherited Conversation lints")
        next_gap = proposal["next_gap"]
        if next_gap is not None and next_gap not in FOCUS_DIMENSIONS:
            raise FocusCandidateError("next_gap is invalid")
        raw_spans = proposal["evidence_spans"]
        if not isinstance(raw_spans, list) or len(raw_spans) > MAX_PROPOSAL_SPANS:
            raise FocusCandidateError("evidence_spans is invalid")
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
                raise FocusCandidateError(
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
            keys=frozenset(FOCUS_DIMENSIONS),
        )
        referenced: dict[str, list[dict]] = {}
        for dimension in FOCUS_DIMENSIONS:
            refs = raw_dimensions[dimension]
            if not isinstance(refs, list) or any(
                isinstance(ref, bool)
                or not isinstance(ref, int)
                or ref < 0
                or ref >= len(new_spans)
                for ref in refs
            ):
                raise FocusCandidateError(f"dimension {dimension} indices are invalid")
            if len(refs) != len(set(refs)):
                raise FocusCandidateError(f"dimension {dimension} indices repeat")
            referenced[dimension] = [new_spans[ref] for ref in refs]
        if any(
            span["evidence_kind"] not in candidate_research.CONCRETE_EVIDENCE_KINDS
            for span in referenced["grounded_evidence"]
        ):
            raise FocusCandidateError("grounded_evidence requires concrete spans")
        used = {
            span["evidence_revision"] for spans in referenced.values() for span in spans
        }
        if used != {span["evidence_revision"] for span in new_spans}:
            raise FocusCandidateError("every proposed span must support a dimension")
        evidence, dimensions, questions = _prior_parts(canonical)
        known = {span["evidence_revision"] for span in evidence}
        evidence.extend(
            span for span in new_spans if span["evidence_revision"] not in known
        )
        for focus_dimension, research_dimension in FOCUS_TO_RESEARCH_DIMENSION.items():
            existing = dimensions[research_dimension]
            for span in referenced[focus_dimension]:
                revision = span["evidence_revision"]
                if revision not in existing:
                    existing.append(revision)
        # Concrete spans must also support a source dimension; grounded_evidence
        # is an Interaction gate, not an eighth v183 source-schema key.
        grounded = {s["evidence_revision"] for s in referenced["grounded_evidence"]}
        source_refs = {ref for refs in dimensions.values() for ref in refs}
        if not grounded <= source_refs:
            raise FocusCandidateError(
                "grounded evidence must support a source dimension"
            )
        raw_questions = proposal["seed_questions"]
        if not isinstance(raw_questions, list):
            raise FocusCandidateError("seed_questions must be a list")
        known_questions = {row["question"] for row in questions}
        for index, question in enumerate(raw_questions):
            clean = _text(question, name=f"seed_questions[{index}]", maximum=1_000)
            if not clean.endswith("?") or _question_count(clean) != 1:
                raise FocusCandidateError("seed questions must be worthwhile questions")
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
        ready = assessment["readiness"]["ready"]
        unsupported = {
            focus_dimension
            for focus_dimension, research_dimension in (
                FOCUS_TO_RESEARCH_DIMENSION.items()
            )
            if not assessment["dimension_evidence"][research_dimension]
        }
        if assessment["readiness"]["concrete_evidence_count"] < 1:
            unsupported.add("grounded_evidence")
        confirmation_span = proposal["confirmation_span"]
        prior_ready = bool(
            canonical["assessment"] and canonical["assessment"]["readiness"]["ready"]
        )
        status = "continue"
        if action == "ask_gap":
            if (
                not unsupported
                or next_gap not in unsupported
                or _question_count(reply) != 1
            ):
                raise FocusCandidateError(
                    "ask_gap must ask one unsupported highest-value gap"
                )
            if (
                canonical["previous_question"]
                and canonical["previous_question"] in reply
            ):
                raise FocusCandidateError("ask_gap repeats the previous question")
            if confirmation_span is not None:
                raise FocusCandidateError("ask_gap cannot confirm")
        elif action == "offer_confirmation":
            if not ready or next_gap is not None or confirmation_span is not None:
                raise FocusCandidateError("offer_confirmation requires ready research")
            if _question_count(reply) != 1:
                raise FocusCandidateError("offer_confirmation must ask one question")
            status = "awaiting_confirmation"
        elif action == "accept_confirmation":
            if (
                not prior_ready
                or next_gap is not None
                or new_spans
                or raw_questions
                or any(referenced.values())
            ):
                raise FocusCandidateError(
                    "accept_confirmation requires a previously ready assessment"
                )
            if confirmed_at is None:
                raise FocusCandidateError(
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
                raise FocusCandidateError(
                    "confirmation must be in the latest user turn"
                )
            confirmation_text = turn["text"][
                raw_confirmation["start"] : raw_confirmation["end"]
            ]
            if not _is_explicit_confirmation(confirmation_text):
                raise FocusCandidateError("confirmation span is not explicit consent")
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
                raise FocusCandidateError("continue cannot ask or confirm")
        source = {
            "schema_version": SCHEMA_VERSION,
            "status": status,
            "action": action,
            "candidate_id": canonical["candidate_id"],
            "subject_revision": canonical["subject_revision"],
            "reply": reply,
            "next_gap": next_gap,
            "assessment": assessment,
            "ready": assessment["readiness"]["ready"],
            "complete": assessment["complete"],
        }
        return {
            **source,
            "decision_revision": candidate_research.canonical_revision(source),
        }
    except (
        FocusCandidateError,
        candidate_research.CandidateResearchError,
        TypeError,
        ValueError,
    ):
        return _invalid(canonical)


def validate_focus_candidate_decision(
    decision: object, *, payload: dict, current_subject: dict
) -> dict:
    canonical = validate_focus_candidate_input(payload, current_subject=current_subject)
    value = _object(decision, name="decision", keys=_DECISION_KEYS)
    source = {key: value[key] for key in value if key != "decision_revision"}
    if value["decision_revision"] != candidate_research.canonical_revision(source):
        raise FocusCandidateError("decision_revision does not match decision")
    if (
        value["candidate_id"] != canonical["candidate_id"]
        or value["subject_revision"] != canonical["subject_revision"]
    ):
        raise FocusCandidateError("focus candidate decision is stale")
    if not isinstance(value["status"], str) or value["status"] not in STATUSES:
        raise FocusCandidateError("decision status is invalid")
    if value["action"] is not None and not isinstance(value["action"], str):
        raise FocusCandidateError("decision action is invalid")
    if type(value["ready"]) is not bool or type(value["complete"]) is not bool:
        raise FocusCandidateError("decision ready and complete must be booleans")
    matrix = {
        "continue": {"ask_gap", "continue"},
        "awaiting_confirmation": {"offer_confirmation"},
        "complete": {"accept_confirmation"},
        "invalid": {None},
    }
    if value["action"] not in matrix[value["status"]]:
        raise FocusCandidateError("decision action/status combination is invalid")
    if value["reply"] is not None:
        reply = _text(value["reply"], name="decision.reply", maximum=MAX_REPLY_CHARS)
        if lint_focus_candidate_reply(
            reply,
            is_reply_to_substantive=_is_substantive_latest(canonical),
            seam_ok=value["action"] == "offer_confirmation",
        ):
            raise FocusCandidateError("decision reply violates inherited authority")
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
            raise FocusCandidateError("decision readiness is forged")
    action = value["action"]
    next_gap = value["next_gap"]
    if action == "ask_gap":
        if (
            next_gap not in FOCUS_DIMENSIONS
            or reply is None
            or _question_count(reply) != 1
        ):
            raise FocusCandidateError("ask_gap decision shape is invalid")
    elif action == "continue":
        if next_gap is not None or reply is None or _question_count(reply):
            raise FocusCandidateError("continue decision shape is invalid")
    elif action == "offer_confirmation":
        if (
            next_gap is not None
            or reply is None
            or _question_count(reply) != 1
            or not value["ready"]
            or value["complete"]
        ):
            raise FocusCandidateError("offer_confirmation decision shape is invalid")
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
            raise FocusCandidateError("accept_confirmation decision shape is invalid")
        confirmation = assessment["confirmation"]
        if (
            confirmation is None
            or confirmation["evidence"]["turn_id"] != canonical["latest_turn_id"]
        ):
            raise FocusCandidateError("completion confirmation is not current")
        latest_turn = next(
            turn
            for turn in canonical["authoritative_turns"]
            if turn["turn_id"] == canonical["latest_turn_id"]
        )
        evidence = confirmation["evidence"]
        if not _is_explicit_confirmation(
            latest_turn["text"][evidence["start"] : evidence["end"]]
        ):
            raise FocusCandidateError("completion confirmation is not explicit consent")
    elif next_gap is not None or value["complete"]:
        raise FocusCandidateError("invalid decision carries authoritative facts")
    return dict(value)


def resolve_focus_candidate_completion(
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
        raise FocusCandidateError("current_subject_loader must be callable")
    try:
        subject = candidate_research.validate_candidate_research_subject(
            current_subject_loader(), require_active=True
        )
    except candidate_research.CandidateResearchError as exc:
        raise FocusCandidateError(str(exc)) from exc
    if (
        subject["candidate_id"] != candidate_id
        or subject["candidate_kind"] != "focus_candidate"
    ):
        raise FocusCandidateError("completion candidate does not match current subject")
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
        raise FocusCandidateError(str(exc)) from exc


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
            return load_focus_candidate_subject(args.candidate_id)

        subject = loader()
        if args.command == "prompt":
            payload = build_focus_candidate_input(
                candidate_id=args.candidate_id,
                authoritative_turns=raw["authoritative_turns"],
                assessment=raw.get("assessment"),
                latest_turn_id=raw.get("latest_turn_id"),
                previous_question=raw.get("previous_question"),
                current_subject=subject,
            )
            print(build_focus_candidate_prompt(payload, current_subject=subject))
        else:
            receipt = resolve_focus_candidate_completion(
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
        FocusCandidateError,
        interaction_registry.InteractionRegistryError,
    ) as exc:
        print(f"focus-candidate: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
