#!/usr/bin/env python3
"""Pure evidence-link helpers for incremental timeline classification.

This module owns no files and calls no model.  It turns stable event words and
independent candidate semantics into bounded lookup contexts, then validates
the event-local evidence returned by the classifier.  The surrounding
classifier keeps ownership of snapshots, batch transport, and persistence.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

import chronology as chrono
from temporal_claims import collapsed_text, normalized_mention_key

EVENT_KEY_LENGTH = 12
CLASSIFIER_CLAIMS_RULE_VERSION = "2"
CLASSIFIER_CLAIMS_EXTRACTOR = (
    f"classifier-claims/rule:{CLASSIFIER_CLAIMS_RULE_VERSION}"
)
MAX_RELEVANT_CANDIDATES = 64
MAX_TOTAL_CANDIDATES = 256
MAX_RESOLUTION_REASON_CHARS = 300
RESOLUTION_STATUSES = frozenset({
    "linked", "missing_evidence", "ambiguous", "incomplete", "not_temporal",
})
EVENT_DELTA_KEYS = frozenset({
    "event_key", "source_grounding", "timeline_relation", "timeline_resolution",
})
GROUNDING_KEYS = frozenset({
    "quote", "temporal_quote", "subject_quote", "kind",
})
RESOLUTION_KEYS = frozenset({"status", "candidate_ids", "reason"})

_WORD_RE = re.compile(r"[a-z0-9]+")
_OWNER_TERMS = frozenset({
    "i", "me", "my", "mine", "myself", "self", "owner", "speaker", "author",
    "the speaker", "the author", "the owner",
})
_GENERIC_REFERENCE_TERMS = _OWNER_TERMS | frozenset({
    "person self", "person owner", "person speaker", "person author",
})
_ROLE_TERMS = {
    "birth": ("birth", "born", "birthday"),
    "death": ("death", "died", "passed away"),
    "job": ("job", "work", "worked", "hired", "joined", "employment", "payroll"),
    "work": ("job", "work", "worked", "hired", "joined", "employment", "payroll"),
    "started": ("started", "began", "founded", "created", "launched"),
    "founded": ("founded", "founding", "started", "created", "launched"),
    "move": ("move", "moved", "lived", "home", "residence"),
    "residence": ("move", "moved", "lived", "home", "residence", "stay"),
    "span": ("lived", "residence", "stay", "worked", "attended"),
    "school": ("school", "attended", "graduated", "college"),
    "graduation": ("graduated", "graduation", "school", "college"),
    "married": ("married", "marriage", "wedding"),
    "marriage": ("married", "marriage", "wedding"),
    "relationship": ("relationship", "dating", "together", "married"),
    "military": ("military", "army", "navy", "service", "served"),
    "visit": ("visit", "visited", "trip", "stayed"),
}
_EVENT_ROLE_TERMS = {
    "birth": ("birth", "born", "birthday"),
    "death": ("death", "died", "passed away"),
    "founded": ("founded", "founding", "launch", "launched", "created"),
    "job": ("job", "work", "worked", "hired", "joined", "employment", "payroll"),
    "married": ("married", "marriage", "wedding"),
    "move": ("move", "moved", "relocated"),
    "residence": ("lived", "residence", "stay", "stayed", "home"),
    "graduation": ("graduated", "graduation"),
    "school": ("school", "attended", "college", "university"),
    "military": ("military", "army", "navy", "service", "served"),
    "visit": ("visit", "visited", "trip"),
    "relationship": ("relationship", "dating", "together"),
}


class TimelineEvidenceError(ValueError):
    """A link delta or direct-source proof does not satisfy the contract."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


def _canonical(value: object) -> str:
    # Event identity predates this helper. Keep the exact v306 serializer used
    # by landmark_projection.canonical_json so Unicode titles/descriptions do
    # not re-key existing events or their manual references.
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def digest(value: object) -> str:
    return "sha256:" + hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def event_key(event: object) -> str:
    """Stable key over extraction-owned event words, never link metadata."""
    row = event if isinstance(event, dict) else {}
    payload = {
        "title": collapsed_text(row.get("title")),
        "description": collapsed_text(row.get("description")),
    }
    return hashlib.sha256(_canonical(payload).encode("utf-8")).hexdigest()[:EVENT_KEY_LENGTH]


def ensure_event_key(event: dict) -> str:
    key = event_key(event)
    supplied = collapsed_text(event.get("event_key"))
    if supplied and supplied != key:
        raise TimelineEvidenceError("event_key_changed", "event_key does not match stored event words")
    event["event_key"] = key
    return key


def is_current_classifier_claim(claim: object) -> bool:
    """Whether a claim belongs to the grounded-fact extractor generation."""
    row = claim if isinstance(claim, dict) else {}
    source_ref = row.get("source_ref") if isinstance(row.get("source_ref"), dict) else {}
    return (
        collapsed_text(source_ref.get("source_id")).startswith("classification:")
        and collapsed_text(row.get("extractor_version")) == CLASSIFIER_CLAIMS_EXTRACTOR
    )


def _search_key(value: object) -> str:
    return " ".join(_WORD_RE.findall(collapsed_text(value).casefold()))


def _search_terms(value: object) -> set[str]:
    phrase = _search_key(value)
    if not phrase:
        return set()
    terms = {phrase}
    words = phrase.split()
    terms.update(word for word in words if len(word) >= 4)
    return {term for term in terms if term not in _GENERIC_REFERENCE_TERMS}


def is_generic_owner_reference(value: object) -> bool:
    key = _search_key(value)
    if key in _GENERIC_REFERENCE_TERMS:
        return True
    return key.startswith("person ") and key.split()[-1] in _OWNER_TERMS


def _candidate_specific_reference_keys(candidate: dict) -> set[str]:
    values: list[object] = [
        candidate.get("name"),
        *(
            value for value in candidate.get("aliases") or ()
            if ":" not in collapsed_text(value)
        ),
        *(candidate.get("unresolved_entity_mentions") or ()),
    ]
    for row in candidate.get("canonical_roster_terms") or ():
        if isinstance(row, dict):
            values.extend(row.get("terms") or ())
    for row in candidate.get("entity_ref_ambiguities") or ():
        if isinstance(row, dict):
            values.append(row.get("mention"))
    keys: set[str] = set()
    for value in values:
        keys.update(_search_terms(value))
    return keys


def _candidate_role_reference_keys(candidate: dict) -> set[str]:
    role = _search_key(candidate.get("event_role") or candidate.get("kind"))
    keys = _search_terms(role)
    for value in _ROLE_TERMS.get(role, ()):
        keys.update(_search_terms(value))
    return keys


def candidate_reference_keys(candidate: dict) -> list[str]:
    """Deterministic entity, label, role and unresolved-reference lookup keys."""
    keys = _candidate_specific_reference_keys(candidate)
    keys.update(_candidate_role_reference_keys(candidate))
    return sorted(keys)


def event_reference_keys(event: dict) -> list[str]:
    """Explicit event handles retained even when no current candidate matches."""
    date = event.get("date") if isinstance(event.get("date"), dict) else {}
    values: list[object] = [
        event.get("title"), event.get("subject"), event.get("anchor"),
        date.get("anchor_ref"), *(event.get("places") or ()),
    ]
    keys: set[str] = set()
    for value in values:
        if isinstance(value, dict):
            value = value.get("name") or value.get("place")
        if not is_generic_owner_reference(value):
            keys.update(_search_terms(value))
    return sorted(keys)


def _event_haystack(event: dict) -> str:
    date = event.get("date") if isinstance(event.get("date"), dict) else {}
    values: list[object] = [
        event.get("title"), event.get("description"), event.get("subject"),
        event.get("when_hint"), event.get("anchor"), date.get("anchor_ref"),
        *(event.get("places") or ()),
    ]
    parts: list[str] = []
    for value in values:
        if isinstance(value, dict):
            value = value.get("name") or value.get("place")
        text = "" if is_generic_owner_reference(value) else _search_key(value)
        if text:
            parts.append(text)
    return " ".join(parts)


def _term_occurs(term: str, haystack: str) -> bool:
    return bool(term) and re.search(rf"(?<![a-z0-9]){re.escape(term)}(?![a-z0-9])", haystack) is not None


def event_role(event: object) -> str | None:
    """Preserve an explicit role from stable event words, or abstain."""
    row = event if isinstance(event, dict) else {}
    for value in (row.get("title"), row.get("description")):
        text = _search_key(value)
        matches = {
            role for role, terms in _EVENT_ROLE_TERMS.items()
            if any(_term_occurs(term, text) for term in terms)
        }
        if len(matches) == 1:
            return next(iter(matches))
    return None


def _candidate_semantics(candidate: dict) -> dict:
    keys = (
        "candidate_id", "episode_id", "node_kind", "kind", "event_role",
        "entity_refs", "canonical_roster_terms", "unresolved_entity_mentions",
        "entity_ref_ambiguities", "basis", "conflict_state", "alternatives",
        "reference_keys",
    )
    semantics = {key: candidate.get(key) for key in keys}
    semantics["grounding_identity"] = [
        {
            "claim_type": row.get("claim_type"),
            "subject_ref": row.get("subject_ref"),
            "subject_mention": row.get("subject_mention"),
            "source_path": row.get("source_path"),
        }
        for row in candidate.get("grounding_identity") or ()
        if isinstance(row, dict)
    ]
    return semantics


def build_event_context(
    event: dict,
    candidates: list[dict],
    *,
    forced_candidate_ids: object = (),
    max_candidates: int = MAX_RELEVANT_CANDIDATES,
) -> dict:
    """Return the complete bounded candidate set relevant to one stored event."""
    key = ensure_event_key(event)
    haystack = _event_haystack(event)
    forced = {collapsed_text(value) for value in (forced_candidate_ids or ()) if collapsed_text(value)}
    relation = event.get("timeline_relation") if isinstance(event.get("timeline_relation"), dict) else {}
    linked_id = collapsed_text(relation.get("candidate_id"))
    if linked_id:
        forced.add(linked_id)

    matched: list[dict] = []
    role_matched: list[tuple[dict, set[str]]] = []
    matched_keys: set[str] = set()
    for candidate in candidates:
        reference_keys = list(candidate.get("reference_keys") or candidate_reference_keys(candidate))
        candidate["reference_keys"] = reference_keys
        specific_hits = {
            term for term in _candidate_specific_reference_keys(candidate)
            if _term_occurs(term, haystack)
        }
        role_hits = {
            term for term in _candidate_role_reference_keys(candidate)
            if _term_occurs(term, haystack)
        }
        if specific_hits or collapsed_text(candidate.get("candidate_id")) in forced:
            matched.append(candidate)
            matched_keys.update(specific_hits)
            matched_keys.update(role_hits)
        elif role_hits:
            role_matched.append((candidate, role_hits))

    if not matched:
        for candidate, role_hits in role_matched:
            matched.append(candidate)
            matched_keys.update(role_hits)

    # A matched entity admits every competing role/stay for that same entity.
    entity_refs = {
        collapsed_text(ref)
        for row in matched
        for ref in row.get("entity_refs") or ()
        if collapsed_text(ref) and not is_generic_owner_reference(ref)
    }
    if entity_refs:
        matched.extend(
            row for row in candidates
            if entity_refs.intersection(collapsed_text(ref) for ref in row.get("entity_refs") or ())
        )
    by_id = {
        collapsed_text(row.get("candidate_id")): row
        for row in matched if collapsed_text(row.get("candidate_id"))
    }
    relevant = [by_id[candidate_id] for candidate_id in sorted(by_id)]
    cap = max(0, min(int(max_candidates), MAX_RELEVANT_CANDIDATES))
    selected = relevant[:cap]
    complete = len(selected) == len(relevant)
    selected_ids = [collapsed_text(row.get("candidate_id")) for row in selected]

    explicit_keys = set(event_reference_keys(event))
    unmatched = sorted(term for term in explicit_keys if term not in matched_keys)
    fingerprint_candidates = []
    for row in selected:
        fingerprint_candidates.append(_candidate_semantics(row))
    fingerprint = digest({
        "candidate_semantics": fingerprint_candidates,
        "reference_keys": sorted(matched_keys),
        "unmatched_reference_keys": unmatched,
        "complete": complete,
        "remaining_candidate_count": len(relevant) - len(selected),
    })
    return {
        "event_key": key,
        "candidate_ids": selected_ids,
        "reference_keys": sorted(matched_keys),
        "unmatched_reference_keys": unmatched,
        "complete": complete,
        "remaining_candidate_count": len(relevant) - len(selected),
        "input_fingerprint": fingerprint,
    }


def quote_disambiguates(candidate: dict, competitors: list[dict], quote: str) -> bool:
    """Require source words that distinguish same-entity competing candidates."""
    selected_refs = set(candidate.get("entity_refs") or ())
    rivals = [
        row for row in competitors
        if collapsed_text(row.get("candidate_id")) != collapsed_text(candidate.get("candidate_id"))
        and selected_refs.intersection(row.get("entity_refs") or ())
    ]
    if not rivals:
        return True
    quote_key = _search_key(quote)
    own = set(candidate.get("reference_keys") or candidate_reference_keys(candidate))
    rival = {
        term for row in rivals
        for term in (row.get("reference_keys") or candidate_reference_keys(row))
    }
    return any(_term_occurs(term, quote_key) for term in own - rival)


def _unique_exact_span(story_text: str, quote: object, *, code: str) -> tuple[str, int, int]:
    if not isinstance(quote, str) or not quote:
        raise TimelineEvidenceError(code, "an exact source quote is required")
    start = story_text.find(quote)
    if start < 0:
        raise TimelineEvidenceError(code, "quote is not present in the source")
    end = start + len(quote)
    if story_text.find(quote, end) >= 0:
        raise TimelineEvidenceError(code, "quote occurs more than once in the source")
    return quote, start, end


def _contained_exact(whole: str, part: object, *, code: str) -> str:
    if not isinstance(part, str) or not part or part not in whole:
        raise TimelineEvidenceError(code, "evidence fragment must occur exactly inside quote")
    return part


def _same_date(left: object, right: object) -> tuple[bool, dict | None]:
    a = chrono.parse_loose_date(left)
    b = chrono.parse_loose_date(right)
    if a is None or b is None:
        return False, None
    fields = ("earliest", "latest", "granularity")
    return all(a.get(field) == b.get(field) for field in fields), b


def _subject_supported(
    subject: object,
    subject_quote: str,
    *,
    aliases: object = (),
) -> bool:
    wanted = normalized_mention_key(subject)
    proof = normalized_mention_key(subject_quote)
    if wanted in _OWNER_TERMS:
        return proof in _OWNER_TERMS
    if not wanted or not proof:
        return False
    supported = {wanted}
    if "/" in collapsed_text(subject):
        supported.add(normalized_mention_key(collapsed_text(subject).rsplit("/", 1)[-1]))
    supported.update(
        normalized_mention_key(value)
        for value in (aliases or ())
        if normalized_mention_key(value)
    )
    return proof in supported


def normalize_source_grounding(
    grounding: object,
    event: dict,
    *,
    story_text: str,
    source_revision: str,
    grounding_allowed: bool = True,
) -> dict | None:
    if grounding is None:
        return None
    if not grounding_allowed:
        raise TimelineEvidenceError(
            "grounding_corrected_source", "active corrections require a new authoritative proof",
        )
    if not isinstance(grounding, dict) or set(grounding) != GROUNDING_KEYS:
        raise TimelineEvidenceError("grounding_schema_invalid", "source_grounding fields are invalid")
    kind = collapsed_text(grounding.get("kind"))
    if kind not in ("date", "age"):
        raise TimelineEvidenceError("grounding_kind_invalid", "grounding kind must be date or age")
    quote, start, end = _unique_exact_span(
        story_text, grounding.get("quote"), code="grounding_quote_invalid",
    )
    temporal_quote = _contained_exact(
        quote, grounding.get("temporal_quote"), code="grounding_temporal_quote_invalid",
    )
    subject_quote = _contained_exact(
        quote, grounding.get("subject_quote"), code="grounding_subject_quote_invalid",
    )
    if not _subject_supported(
        event.get("subject") or "self",
        subject_quote,
        aliases=event.get("subject_aliases") or (),
    ):
        raise TimelineEvidenceError(
            "grounding_subject_mismatch", "subject evidence does not support the event subject",
        )
    date = event.get("date") if isinstance(event.get("date"), dict) else {}
    if kind == "date":
        same, normalized = _same_date(date.get("stated"), temporal_quote)
        if not same:
            raise TimelineEvidenceError(
                "grounding_temporal_mismatch", "date evidence does not support date.stated",
            )
    else:
        stated_age = date.get("age")
        if chrono.YEAR_RE.search(collapsed_text(stated_age)) or chrono.YEAR_RE.search(temporal_quote):
            raise TimelineEvidenceError("grounding_temporal_mismatch", "a year is not age evidence")
        stated = chrono.parse_age(stated_age)
        quoted = chrono.parse_age(temporal_quote)
        if stated is None or quoted is None or stated != quoted:
            raise TimelineEvidenceError(
                "grounding_temporal_mismatch", "age evidence does not support date.age",
            )
        normalized = {
            "low": quoted[0], "high": quoted[1], "approximate": quoted[2],
        }
    return {
        "quote": quote,
        "temporal_quote": temporal_quote,
        "subject_quote": subject_quote,
        "kind": kind,
        "start": start,
        "end": end,
        "source_revision": source_revision,
        "normalized_temporal_value": normalized,
    }


def normalize_resolution(
    resolution: object,
    *,
    event_key_value: str,
    candidate_ids: list[str],
    context_complete: bool,
    source_revision: str,
    prompt_version: str,
    input_fingerprint: str,
    relation: object,
) -> dict:
    if not isinstance(resolution, dict) or set(resolution) != RESOLUTION_KEYS:
        raise TimelineEvidenceError("resolution_schema_invalid", "timeline_resolution fields are invalid")
    status = collapsed_text(resolution.get("status"))
    if status not in RESOLUTION_STATUSES:
        raise TimelineEvidenceError("resolution_status_invalid", "timeline_resolution status is invalid")
    supplied_ids = resolution.get("candidate_ids")
    if (not isinstance(supplied_ids, list)
            or any(not isinstance(value, str) or not value for value in supplied_ids)
            or len(set(supplied_ids)) != len(supplied_ids)
            or sorted(supplied_ids) != sorted(candidate_ids)):
        raise TimelineEvidenceError(
            "resolution_candidates_incomplete", "candidate_ids must equal the complete supplied event set",
        )
    reason = collapsed_text(resolution.get("reason"))
    if not reason or len(reason) > MAX_RESOLUTION_REASON_CHARS:
        raise TimelineEvidenceError("resolution_reason_invalid", "resolution reason is missing or too long")
    if status == "linked" and not isinstance(relation, dict):
        raise TimelineEvidenceError("resolution_relation_missing", "linked requires timeline_relation")
    if status != "linked" and relation is not None:
        raise TimelineEvidenceError("resolution_relation_unexpected", "only linked may carry timeline_relation")
    if status == "incomplete" and context_complete:
        raise TimelineEvidenceError("resolution_incomplete_false", "complete search cannot resolve as incomplete")
    if not context_complete and status != "incomplete":
        raise TimelineEvidenceError("resolution_incomplete_required", "incomplete search must stay incomplete")
    return {
        "status": status,
        "candidate_ids": sorted(candidate_ids),
        "reason": reason,
        "source_revision": source_revision,
        "event_key": event_key_value,
        "prompt_version": prompt_version,
        "input_fingerprint": input_fingerprint,
    }


def active_global_retracted_paths(vault_root: str | Path) -> set[str]:
    """Return sha-pinned, unvoided, globally retracted narrative source paths."""
    from lifehug_core import split_frontmatter  # noqa: PLC0415

    root = Path(vault_root)
    directory = root / "sources" / "corrections"
    if not directory.exists():
        return set()
    retracted: set[str] = set()
    for path in sorted(directory.glob("*.md")):
        try:
            metadata, _body = split_frontmatter(path.read_text(encoding="utf-8", errors="replace"))
        except OSError:
            continue
        if (str(metadata.get("type") or "") != "source_retraction"
                or metadata.get("voided")
                or (metadata.get("suppress_on") or [])):
            continue
        target = collapsed_text(metadata.get("retracts_path"))
        if not target:
            continue
        target_path = root / target
        try:
            target_meta, _payload = split_frontmatter(
                target_path.read_text(encoding="utf-8", errors="replace")
            )
        except OSError:
            continue
        pinned = collapsed_text(metadata.get("retracts_sha256"))
        current = collapsed_text(target_meta.get("content_sha256"))
        if not pinned or pinned == current:
            retracted.add(target)
    return retracted
