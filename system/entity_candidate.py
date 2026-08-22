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
import entity_roster
import interaction_registry
from lifehug_core import REPO_DIR, slugify
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
# These are deliberately conservative semantic signals, not a substitute for
# the model's judgment.  The model proposes exact evidence; this authority
# rejects a proposed type-context mapping unless the quoted user material
# contains the contract-specific meaning.  Keeping this here (rather than in a
# prompt or evaluator) makes every entry point enforce the same boundary.
_TYPE_RUBRIC_PATTERNS = {
    "person": {
        "human": re.compile(
            r"\b(?:he|she|they|my|mother|father|parent|sister|brother|aunt|uncle|"
            r"grandm(?:other|a)|grandf(?:ather|a)|friend|neighbor|teacher|coach|"
            r"mentor|partner|colleague|child|son|daughter)\b",
            re.IGNORECASE,
        ),
        "action": re.compile(
            r"\b(?:said|told|asked|taught|showed|helped|made|kept|worked|"
            r"laughed|sang|fixed|built|called|visited|held|changed|became|"
            r"worry|worried|hoped|believed|wanted|refused|forgave)\b",
            re.IGNORECASE,
        ),
    },
    "place": {
        "character": re.compile(
            r"\b(?:street|room|house|home|harbor|pier|shore|river|lake|"
            r"neighborhood|town|city|school|church|yard|kitchen|apartment|"
            r"smell(?:ed|s)?|sound(?:ed|s)?|quiet|crowded|salt|dusty|warm|cold)\b",
            re.IGNORECASE,
        ),
        "inhabited": re.compile(
            r"\b(?:lived|grew up|stayed|returned|visited|walked|worked|"
            r"played|slept|waited|belonged|used to go|spent .* there)\b",
            re.IGNORECASE,
        ),
    },
    "period": {
        "texture": re.compile(
            r"\b(?:every day|each day|most days|typical|morning|afternoon|"
            r"evening|routine|weekday|weekend|worked|studied|commuted|"
            r"school|college|job|home)\b",
            re.IGNORECASE,
        ),
        "boundary": re.compile(
            r"\b(?:before|after|when .* ended|when .* began|transition|"
            r"moved|graduated|left|started|became|until|between)\b",
            re.IGNORECASE,
        ),
    },
    "object": {
        "provenance_or_use": re.compile(
            r"\b(?:gave|gift|inherited|bought|found|kept|carried|used|"
            r"wore|held|made|owned|belongs|came from|passed down)\b",
            re.IGNORECASE,
        ),
        "meaning": re.compile(
            r"\b(?:means|meaning|reminds|symbol|represents|memory|"
            r"connection|matters|comfort|promise|belonging)\b",
            re.IGNORECASE,
        ),
    },
    "theme": {
        "recurrence": re.compile(
            r"\b(?:again|recurs?|kept|always|repeated|another|later|"
            r"at school|at work|at home|in .* relationship|across)\b",
            re.IGNORECASE,
        ),
        "meaning_change": re.compile(
            r"\b(?:changed|change|grew|growth|used to|now|then|but|"
            r"although|contradiction|different)\b",
            re.IGNORECASE,
        ),
    },
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
    r"(?:approved|created|scaffolded|wrote|saved|persisted|preserved|"
    r"recorded|stored|committed|pushed|promoted)\b"
    r"|\b(?:the|a|your)\s+(?:recommendation|research|"
    r"candidate\s+research|entity\s+page|page|source|excerpt(?:s)?|record|commit)\s+"
    r"(?:(?:has|have)\s+been\s+|was\s+|were\s+|is\s+|are\s+)?"
    r"(?:approved|created|scaffolded|written|saved|persisted|preserved|"
    r"recorded|stored|committed|pushed|promoted)\b"
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


#: entity-identity-context (v190, Design §A.3): the research-mode structured
#: output contract, moved OUT of `prompt/turn-instructions.md` and into the
#: runtime, byte-for-byte what the leaf carried at v189. The leaf is now the
#: stage-keyed identity leaf the platform REPLAYs on top of an ordinary
#: Conversation prompt, and two competing "return exactly one JSON object
#: with exactly these keys" contracts in one prompt is a defect, not a
#: composition. This is the parent's own pattern, not an invention:
#: `conversation_delivery._output_contract_block` exists for the same reason —
#: the ENGINE appends the machine-readable shape, the leaf holds behavior.
#: `parse_entity_candidate_output` and the standalone
#: `entity-candidate-prompt` / `entity-candidate-complete` CLI path are
#: unchanged; test_research_output_contract_survives_the_leaf_move pins it.
_RESEARCH_OUTPUT_CONTRACT = """Return exactly one JSON object with exactly these keys and no prose or fence:

```json
{
  "reply": "string",
  "action": "ask_gap|offer_confirmation|accept_confirmation|continue",
  "next_gap": "identity_disambiguation|relationship_relevance_and_significance|timeline_context|connections|tension_or_open_question|type_specific_context|grounded_evidence|null",
  "evidence_spans": [{"turn_id":"string","start":0,"end":1,"evidence_kind":"statement|concrete_event|concrete_observation"}],
  "dimension_evidence": {
    "identity_disambiguation": [], "relationship_relevance_and_significance": [], "timeline_context": [],
    "connections": [], "tension_or_open_question": [],
    "type_specific_context": [], "grounded_evidence": []
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
turn and identify its exact span. Never claim a write, commit, approval,
graduation, page, source, or receipt.
"""


def _research_output_contract_block() -> str:
    """The standalone research path's structured-output appendix."""
    return _RESEARCH_OUTPUT_CONTRACT


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


# --------------------------------------------------------------------------
# entity-identity-context (v190) — the Play path
#
# Play graduates the entity in a background job and opens this conversation;
# its job is IDENTITY (who/what this is), not scope. Everything below is the
# same four-part shape `focus_candidate` took for onboarding at v189 and
# `question_candidate` took for placement at v188: one pure opener, one
# transcript-derived stage, one closed validator, one lint family — plus the
# two facts an entity has that a focus does not (a duplicate list, and whether
# offering a focus is even appropriate).
# --------------------------------------------------------------------------

#: The two `{entity_stage}` values the leaf is keyed on (Design §A.2/§C).
VALID_ENTITY_STAGES = frozenset({"establish", "settled"})
#: The closed key set of the additive ``entity_setup`` object, mirrored from
#: `conversation_delivery._ENTITY_SETUP_KEYS` — importing it would create an
#: import cycle through the delivery engine, so the parity is pinned by a test
#: instead (test_entity_setup_keys_match_the_structural_layer).
ENTITY_SETUP_KEYS = frozenset(
    {"aliases", "relationship", "living", "type", "maps_to", "start_focus"}
)
MAX_ENTITY_ALIASES = 8
MAX_ENTITY_ALIAS_CHARS = 80
#: How many likely-same pages the leaf is allowed to carry. The question is
#: "is this the same one as X?" — a list is already a worse question than a
#: name, and an unbounded list would let the roster crowd the turn out.
MAX_POSSIBLE_DUPLICATES = 5

#: The first thing the person sees when Play opens the tab — one short,
#: natural line per entity type, with no machinery in it. The generic line is
#: the fallback for an unknown or blank type.
_OPENING_QUESTIONS = {
    "person": "Tell me about {name} — who are they to you?",
    "place": "Tell me about {name} — what happened there that makes it matter?",
    "period": "Tell me about {name} — what was that stretch of your life like?",
    "object": "Tell me about {name} — what makes it worth keeping?",
    "theme": "Tell me about {name} — where does that show up in your life?",
}
_GENERIC_OPENING_QUESTION = "Tell me about {name} — what should I know about it?"


def opening_question(name: str, entity_type: str | None = None) -> str:
    """The identity opener for an entity Play session (Design §A.4).

    Pure — no vault, no model, no I/O. The platform shows this as the tab's
    framing line (review-loop/57 §A, ``question_text``). A blank ``name``
    raises: an opener with no subject is a caller bug, not something to
    degrade around. An unknown or blank ``entity_type`` falls back to the
    generic line rather than failing.
    """
    subject = (name or "").strip()
    if not subject:
        raise EntityCandidateError("opening_question requires an entity name")
    template = _OPENING_QUESTIONS.get(
        (entity_type or "").strip(), _GENERIC_OPENING_QUESTION
    )
    return template.format(name=subject)


def entity_stage_for_session(session: dict) -> str:
    """Derive ``{entity_stage}`` from the transcript alone (Design §C) — no
    new session field, no new lifecycle status.

    ``"settled"`` once the session already carries any assistant
    (``role == "lifehug"``) turn: the aside and the one identity question both
    live on the FIRST reply, so "have we onboarded?" is exactly "does this
    session have an assistant turn?". Before that, ``"establish"``. The exact
    twin of ``focus_candidate.focus_stage_for_session``.
    """
    turns = session.get("turns") or []
    if any(isinstance(turn, dict) and turn.get("role") == "lifehug" for turn in turns):
        return "settled"
    return "establish"


def possible_duplicates(entity_type: str, name: str, roster: dict) -> list[str]:
    """Existing roster pages that might already BE this entity (Design §C).

    Reuses the roster's own matchers and adds none (the recurring-defect
    doctrine's whole point — a second entity matcher is how the four Jameses
    happened):

      - ``entity_roster._entity_keys`` — name + slug + aliases, normalized
        through ``lifehug_core.normalized_focus_key`` (the ONE authoritative
        normalization every Focus-creation door already shares). Any entry
        whose key set intersects the subject's is a duplicate candidate.
      - ``focus_dupes._token_subset_pairs`` — the repo's existing near-name
        shape ("Jim" vs "Jim Reynolds"), which deliberately EXCLUDES exact
        normalized collisions because the key-set layer above already has
        those.

    ``entity_type`` selects nothing here (the caller passes the roster it
    already loaded for that type) but is part of the signature the platform
    twin table names, and is used to keep the call honest about which roster
    was read. Entries vetoed ``never`` and the subject's own row are excluded.
    Result preserves roster order, then near-name order, capped at
    ``MAX_POSSIBLE_DUPLICATES``.
    """
    from focus_dupes import _token_subset_pairs  # noqa: PLC0415

    subject = (name or "").strip()
    if not subject:
        return []
    entities = [
        entity
        for entity in ((roster or {}).get("entities") or [])
        if isinstance(entity, dict) and str(entity.get("name") or "").strip()
    ]
    subject_slug = slugify(subject)
    subject_keys = entity_roster._entity_keys(
        {"name": subject, "slug": subject_slug, "aliases": []}
    )

    matches: list[str] = []
    remaining: list[tuple[str, str]] = []
    for entity in entities:
        entity_name = str(entity["name"]).strip()
        entity_slug = str(entity.get("slug") or slugify(entity_name))
        if entity_slug == subject_slug:
            continue  # the subject's own row
        if entity.get("owner_verdict") == "never":
            continue  # settled: never a page, so never a merge target
        if subject_keys & entity_roster._entity_keys(entity):
            if entity_name not in matches:
                matches.append(entity_name)
            continue
        remaining.append((f"entity:{entity_slug}", entity_name))

    subject_id = "__subject__"
    for pair in _token_subset_pairs([(subject_id, subject), *remaining]):
        if pair["shorter_id"] == subject_id:
            other = pair["longer_label"]
        elif pair["longer_id"] == subject_id:
            other = pair["shorter_label"]
        else:
            continue
        if other not in matches:
            matches.append(other)
    return matches[:MAX_POSSIBLE_DUPLICATES]


def is_offer_worthy(entity_type: str, roster_entry: dict | None = None) -> bool:
    """May the identity conversation OFFER to start a focus (owner ruling 4)?

    True only for person/place/period/theme — read from
    ``recommend_focuses.FOCUS_RECOMMENDATION_TYPES``, the one module that can
    actually express a focus recommendation of a given type, rather than
    re-typing ruling 4's list here — AND only when the entry is neither
    owner-vetoed (``owner_verdict == "never"``) nor already mapped
    (``maps_to_focus``): an entity that already has a focus does not need an
    offer, and one the owner has permanently vetoed is not a growth program.

    The package decides; the platform only reads the answer (ruling 5).
    """
    from recommend_focuses import FOCUS_RECOMMENDATION_TYPES  # noqa: PLC0415

    if (entity_type or "").strip() not in FOCUS_RECOMMENDATION_TYPES:
        return False
    entry = roster_entry or {}
    if not isinstance(entry, dict):
        return False
    if entry.get("owner_verdict") == "never":
        return False
    return not entry.get("maps_to_focus")


def _entity_alias_list(value: object) -> list[str]:
    """Trim, drop blanks, dedupe case-insensitively (order preserved), cap."""
    if not isinstance(value, list):
        return []
    seen: set[str] = set()
    out: list[str] = []
    for item in value:
        if not isinstance(item, str):
            continue
        alias = item.strip()
        if not alias or len(alias) > MAX_ENTITY_ALIAS_CHARS:
            continue
        if alias.lower() in seen:
            continue
        seen.add(alias.lower())
        out.append(alias)
        if len(out) == MAX_ENTITY_ALIASES:
            break
    return out


def validate_entity_setup(value: object, *, roster_slugs: Sequence[str] = ()) -> dict | None:
    """Closed layer of the additive ``entity_setup`` field (Design §B.2).

    ``value`` is the structural layer's own output — the
    ``{aliases?, relationship?, living?, type?, maps_to?, start_focus?} | None``
    that ``conversation_delivery._parse_entity_setup`` produces — or any other
    untrusted shape a caller hands in directly (this function re-checks shape
    itself so it is safe to call standalone).

    Exact membership only, in both closed vocabularies: ``type`` against
    ``entity_roster.ENTITY_TYPES`` and ``relationship`` against
    ``focus_candidate.FOCUS_RELATIONSHIPS`` (imported, never re-listed — the
    focus lane and the entity lane ask the same question and must not drift).
    ``living`` and ``start_focus`` must be real ``bool``s. ``maps_to`` must be
    a member of the caller-supplied ``roster_slugs``: the package refuses to
    invent a merge target, so a slug nobody has heard of drops the key rather
    than producing a dangling map.

    An individually invalid value drops THAT key rather than the whole object
    (a person who told us their aliases and mistyped the type still told us
    their aliases); no valid key remaining returns ``None``.
    """
    from focus_candidate import FOCUS_RELATIONSHIPS  # noqa: PLC0415

    if not isinstance(value, dict) or not set(value) <= ENTITY_SETUP_KEYS:
        return None
    validated: dict[str, object] = {}
    aliases = _entity_alias_list(value.get("aliases"))
    if aliases:
        validated["aliases"] = aliases
    relationship = value.get("relationship")
    if isinstance(relationship, str) and relationship in FOCUS_RELATIONSHIPS:
        validated["relationship"] = relationship
    entity_type = value.get("type")
    if isinstance(entity_type, str) and entity_type in entity_roster.ENTITY_TYPES:
        validated["type"] = entity_type
    maps_to = value.get("maps_to")
    if isinstance(maps_to, str) and maps_to.strip() in set(roster_slugs or ()):
        validated["maps_to"] = maps_to.strip()
    for flag in ("living", "start_focus"):
        candidate = value.get(flag)
        if isinstance(candidate, bool):
            validated[flag] = candidate
    return validated or None


# --------------------------------------------------------------------------
# entity_setup lints (Design §D)
# --------------------------------------------------------------------------

#: The aside's invariant anchor — "I've added **<name>** as a <type> in your
#: story — tell me if that's the wrong name or the wrong person." The model
#: varies the connective tissue around it but not the move (owner ruling 3);
#: this phrase is what every aside lint locates.
_ENTITY_ASIDE_MARKER_RE = re.compile(
    r"\badded\b[^.!?]*\bin your story\b", re.IGNORECASE
)
#: The OFFER's anchor: a conditional AND "start a focus" in one sentence.
#: Deliberately narrower than "mentions a focus" — a reply that merely
#: RECORDS a yes ("Jo, then.") is not an offer, and a reply that CLAIMS a
#: focus was started is caught by no_mechanism_talk instead.
_ENTITY_OFFER_RE = re.compile(
    r"\b(?:if|want|wanted|would you)\b[^.!?]*\bstart(?:ing)?\s+a\s+focus\b",
    re.IGNORECASE,
)
_ENTITY_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")
#: entity_setup.settled_silence — a settled turn re-opening who this is when
#: the USER did not is the "re-litigating" failure ruling 3 forbids.
_IDENTITY_TALK_PHRASES = (
    "the wrong name",
    "the wrong person",
    "is this the same as",
    "is this the same one as",
    "are these the same",
    "the same person as",
    "what should i call them",
    "what do you call them",
)
#: entity_setup.no_mechanism_talk — graduation is silent; narrating it is not.
#: "graduate"/"graduating" are deliberately NOT here: in a life-story
#: conversation "when did you graduate?" is an ordinary, legitimate question.
_ENTITY_MECHANISM_PHRASES = (
    "i'll create",
    "i will create",
    "wiki page",
    "the roster",
    "entity roster",
    "the system will",
    "i've started a focus",
    "i started a focus",
    "adding a page",
    "page_eligible",
)


def _entity_sentences(text: str) -> list[str]:
    return [
        s.strip() for s in _ENTITY_SENTENCE_SPLIT_RE.split(text.strip()) if s.strip()
    ]


def _entity_span_of(text: str, needle: str) -> list[int]:
    clean = needle.strip()
    start = text.find(clean) if clean else -1
    if start == -1:
        return [0, len(text)]
    return [start, start + len(clean)]


def lint_entity_setup_reply(
    text: str,
    *,
    stage: str,
    user_signaled: bool = False,
    offered_before: bool = False,
) -> list[dict]:
    """Deterministic findings for the seven ``entity_setup_gates.*`` classes
    (Design §D). Pure — no model, no I/O. ``stage`` is the same
    ``{entity_stage}`` value the turn-instructions leaf receives
    (``"establish" | "settled"``); an unrecognized stage is treated as
    ``"settled"`` (fail toward the strictest rule: no identity talk at all).
    ``user_signaled`` and ``offered_before`` are the caller's own facts — did
    THIS turn's user message change an identity fact, and has the focus offer
    already been made in this session — and are the only things that license
    identity talk on a settled turn and forbid a second offer (owner rulings
    3 and 4).

    Findings share ``conversation_lints.lint_turn``'s shape —
    ``{"lint": "<id>", "detail": "...", "span": [start, end]}`` — so a caller
    can merge them with ``lint_entity_candidate_reply``'s output uniformly.
    """
    findings: list[dict] = []
    sentences = _entity_sentences(text)
    aside_sentences = [s for s in sentences if _ENTITY_ASIDE_MARKER_RE.search(s)]

    if stage == "establish":
        if len(aside_sentences) != 1:
            findings.append({
                "lint": "entity_setup.aside_single_sentence",
                "detail": "the identity aside must appear exactly once, as exactly one sentence",
                "span": [0, len(text)],
            })
        elif "?" in aside_sentences[0]:
            findings.append({
                "lint": "entity_setup.aside_not_a_question",
                "detail": "the identity aside must not be a question",
                "span": _entity_span_of(text, aside_sentences[0]),
            })
    else:
        if aside_sentences:
            findings.append({
                "lint": "entity_setup.aside_never_repeated",
                "detail": "a settled turn must never restate that the entity was added",
                "span": _entity_span_of(text, aside_sentences[0]),
            })
        if not user_signaled:
            lowered_identity = text.lower()
            for phrase in _IDENTITY_TALK_PHRASES:
                idx = lowered_identity.find(phrase)
                if idx != -1:
                    findings.append({
                        "lint": "entity_setup.settled_silence",
                        "detail": f"identity talk on a settled turn the user did not signal: {phrase!r}",
                        "span": [idx, idx + len(phrase)],
                    })
                    break

    if text.count("?") > 1:
        findings.append({
            "lint": "entity_setup.one_identity_question",
            "detail": "at most one question per reply — identity onboarding never interrogates",
            "span": [0, len(text)],
        })

    if offered_before:
        offer = next(
            (s for s in sentences if _ENTITY_OFFER_RE.search(s)),
            None,
        )
        if offer is not None:
            findings.append({
                "lint": "entity_setup.offer_at_most_once",
                "detail": "the focus offer is made at most once per session",
                "span": _entity_span_of(text, offer),
            })

    lowered = text.lower()
    for phrase in _ENTITY_MECHANISM_PHRASES:
        idx = lowered.find(phrase)
        if idx != -1:
            findings.append({
                "lint": "entity_setup.no_mechanism_talk",
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
    if not type_specific_context_passes(assessment, subject=subject):
        unsupported.add("type_specific_context")
    return unsupported


def _type_specific_quotes(assessment: dict) -> list[str]:
    evidence_by_revision = {
        span["evidence_revision"]: span["quote"] for span in assessment["evidence"]
    }
    return [
        evidence_by_revision[revision]
        for revision in assessment["dimension_evidence"]["type_specific_context"]
    ]


def type_specific_context_passes(assessment: dict, *, subject: dict) -> bool:
    """Return whether exact type-context evidence meets its closed meaning rule.

    This is intentionally recomputed from canonical quotes at parse, decision,
    and completion time.  A model cannot turn a bare reference count into a
    person, place, period, object, or theme semantic pass.
    """
    entity_type = subject["subject_type"]
    quotes = _type_specific_quotes(assessment)
    if len(quotes) < ENTITY_TYPE_SPECIFIC_MIN_REFS[entity_type]:
        return False
    text = "\n".join(quotes)
    patterns = _TYPE_RUBRIC_PATTERNS[entity_type]
    if entity_type == "person":
        return bool(patterns["human"].search(text) and patterns["action"].search(text))
    if entity_type == "place":
        return bool(
            patterns["character"].search(text) and patterns["inhabited"].search(text)
        )
    if entity_type == "period":
        return bool(
            patterns["texture"].search(text) and patterns["boundary"].search(text)
        )
    if entity_type == "object":
        return bool(
            patterns["provenance_or_use"].search(text)
            and patterns["meaning"].search(text)
        )
    # Themes need separate manifestations, not repeated wording from one
    # moment, and a continuity/change/contradiction in their significance.
    return bool(
        len(set(quotes)) >= 2
        and any(patterns["recurrence"].search(quote) for quote in quotes)
        and patterns["meaning_change"].search(text)
    )


def _interaction_ready(assessment: dict, subject: dict) -> bool:
    return assessment["readiness"]["ready"] and not _unsupported_dimensions(
        assessment, subject
    )


def validate_entity_candidate_completion_assessment(
    assessment: object,
    *,
    authoritative_turns: Sequence[dict],
    candidate_id: str,
    current_subject: dict,
) -> dict:
    """The one Entity-specific pre-write authority for every completion path."""
    try:
        subject = candidate_research.validate_candidate_research_subject(
            current_subject, require_active=True
        )
        canonical = candidate_research.validate_research_assessment(
            assessment,
            authoritative_turns=authoritative_turns,
            current_subject=subject,
        )
    except candidate_research.CandidateResearchError as exc:
        raise EntityCandidateError(str(exc)) from exc
    if (
        candidate_id != subject["candidate_id"]
        or subject["candidate_kind"] != "entity_candidate"
    ):
        raise EntityCandidateError(
            "completion candidate does not match current subject"
        )
    if not _interaction_ready(canonical, subject):
        raise EntityCandidateError("completion requires recomputed Entity readiness")
    confirmation = canonical["confirmation"]
    if not canonical["complete"] or confirmation is None:
        raise EntityCandidateError("completion requires a confirmed ready assessment")
    turns = [
        candidate_research.validate_authoritative_user_turn(turn)
        for turn in authoritative_turns
    ]
    latest_turn = turns[-1] if turns else None
    evidence = confirmation["evidence"]
    if latest_turn is None or evidence["turn_id"] != latest_turn["turn_id"]:
        raise EntityCandidateError("completion confirmation is not current")
    if not _is_explicit_confirmation(
        latest_turn["text"][evidence["start"] : evidence["end"]]
    ):
        raise EntityCandidateError("completion confirmation is not explicit consent")
    return canonical


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
        # is an Interaction gate, not an additional v183 source-schema key.
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
    canonical = validate_entity_candidate_completion_assessment(
        assessment,
        authoritative_turns=authoritative_turns,
        candidate_id=candidate_id,
        current_subject=current_subject_loader(),
    )
    try:
        return candidate_research.resolve_candidate_research_source(
            canonical,
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
        print(f"entity-candidate: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
