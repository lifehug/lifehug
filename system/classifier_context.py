#!/usr/bin/env python3
"""Bounded contextual timeline input and freshness for story classification.

The classifier may relate an event only to candidates supplied here. Freshness
is semantic: source bytes, prompt/extractor versions, and a stable digest of
the supplied timeline context. Projection generations and timestamps are never
inputs. Candidates are folded from independent evidence before classifier
claims can contribute metadata, so filing and publication cannot feed back.
"""

from __future__ import annotations

import hashlib
import json
import re
from enum import Enum
from pathlib import Path

import chronology as chrono
import entity_roster
import event_identity
import identity_resolution
import source_integrity
import temporal_placement as placement
import temporal_claims
import temporal_projection
import temporal_store
import timeline_evidence
from ai_provider import AIResponseError
from temporal_claims import normalized_mention_key
from vault_paths import vault_data_path

CONTEXT_SCHEMA_VERSION = 1
PROMPT_VERSION = "contextual-timeline:2"
EXTRACTOR_VERSION = "story-classifier:2"
MAX_CONTEXT_CANDIDATES = 64
MAX_CONTEXT_DECISIONS = 64
MAX_REFRESH_TARGETS = 50
SNAPSHOT_KEYS = (
    "source_revision",
    "context_digest",
    "prompt_version",
    "extractor_version",
)
RELATIONS = ("within", "before", "after")
LANDMARK_EVENT_KINDS = (
    "birth", "death", "married", "marriage", "divorce", "move",
    "graduation", "education", "job", "work", "military", "relationship",
)

CALCULATED_TIMELINE_PATH = Path(temporal_projection.PROJECTION_FILE)
ACTIVE_INDEX_PATH = Path(temporal_store.ACTIVE_INDEX_FILE)
TELLING_MANIFEST_PATH = Path(event_identity.TELLING_MANIFEST_FILE)


class ContextFailureCode(Enum):
    """Closed operational vocabulary; never source or model-derived values."""

    RESPONSE_NOT_MAPPING = "context_response_not_mapping"
    SNAPSHOT_MISMATCH = "context_snapshot_mismatch"
    EVENTS_NOT_LIST = "context_events_not_list"
    EVENT_NOT_MAPPING = "context_event_not_mapping"
    RELATION_INVALID = "context_relation_invalid"
    CANDIDATE_UNKNOWN = "context_candidate_unknown"
    CONTEXT_INCOMPLETE = "context_incomplete"
    CANDIDATE_AMBIGUOUS = "context_candidate_ambiguous"
    EVIDENCE_NOT_MAPPING = "context_evidence_not_mapping"
    QUOTE_MISSING = "context_quote_missing"
    QUOTE_NOT_FOUND = "context_quote_not_found"
    QUOTE_NOT_EXACT = "context_quote_not_exact"
    QUOTE_AMBIGUOUS = "context_quote_ambiguous"
    ENTITY_REFS_INVALID = "context_entity_refs_invalid"
    CANDIDATE_NOT_DISAMBIGUATED = "context_candidate_not_disambiguated"
    EVENT_KEYS_INVALID = "context_event_keys_invalid"
    GROUNDING_INVALID = "context_grounding_invalid"
    RESOLUTION_INVALID = "context_resolution_invalid"


class ClassifierContextError(AIResponseError, ValueError):
    """A response was not grounded in the source/context snapshot it echoes."""

    def __init__(self, message: str, *, code: ContextFailureCode) -> None:
        if not isinstance(code, ContextFailureCode):
            raise ValueError("invalid classifier context diagnostic code")
        self.code = code
        super().__init__(
            message,
            provider="ai",
            operation="classify-schema",
            status=code.value,
        )


def _read_json(path: Path, default):
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, TypeError, ValueError):
        return default
    return value


def _canonical(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _digest(value: object) -> str:
    return "sha256:" + hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def source_revision(source_path: str | Path, *, source_bytes: bytes | None = None) -> str:
    raw = Path(source_path).read_bytes() if source_bytes is None else source_bytes
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def effective_source_revision(
    vault_root: str | Path,
    source_path: str | Path,
    *,
    source_bytes: bytes | None = None,
    correction_records: list[source_integrity.CorrectionRecord] | None = None,
) -> str:
    """Hash every authoritative source input visible to the classifier.

    Uncorrected sources retain their historical raw-byte revision. Once a
    source has active corrections, the revision also binds the ordered bodies
    selected by ``source_integrity``'s canonical supersession graph. This keeps
    the four-key snapshot stable while making add/supersede correction races
    impossible to adopt as an interpretation of the old input.
    """
    root = Path(vault_root)
    source = Path(source_path)
    raw_revision = source_revision(source, source_bytes=source_bytes)
    if correction_records is None:
        active = source_integrity.active_corrections_for(
            source,
            corrections_dir=root / "sources" / "corrections",
            repo_dir=root,
        )
    else:
        active = source_integrity.active_correction_leaves(
            source_integrity.corrections_targeting(
                source,
                repo_dir=root,
                records=correction_records,
            )
        )
    if not active:
        return raw_revision
    return _digest({
        "raw_source_revision": raw_revision,
        "active_correction_bodies": [record.body for record in active],
    })


def snapshot_metadata(snapshot: object) -> dict:
    """The minimal manifest/response echo: no candidate payload or generation."""
    row = snapshot if isinstance(snapshot, dict) else {}
    return {key: str(row.get(key) or "") for key in SNAPSHOT_KEYS}


def _relative_source(vault_root: Path, source_path: Path) -> str:
    try:
        return source_path.resolve().relative_to(vault_root.resolve()).as_posix()
    except ValueError:
        return str(source_path)


def _claim_catalog(payload: dict) -> tuple[dict[str, list[dict]], dict[str, bool]]:
    """Index source provenance from the operation's already-folded claims."""
    claims_by_source: dict[str, list[dict]] = {}
    classifier_claim: dict[str, bool] = {}
    for claim in temporal_store.active_claims(payload if isinstance(payload, dict) else {}):
        if not isinstance(claim, dict):
            continue
        source_ref = claim.get("source_ref")
        if not isinstance(source_ref, dict):
            continue
        source_id = str(source_ref.get("source_id") or "")
        source_path_value = str(source_ref.get("source_path") or "")
        claim_id = str(claim.get("claim_id") or "")
        is_classifier = source_id.startswith("classification:")
        if claim_id:
            classifier_claim[claim_id] = is_classifier
        if source_path_value:
            claims_by_source.setdefault(source_path_value, []).append(claim)
    return claims_by_source, classifier_claim


def _claim_context_from_catalog(
    relative_source: str,
    claims_by_source: dict[str, list[dict]],
    classifier_claim: dict[str, bool],
) -> tuple[set[str], set[str]]:
    """Filter preloaded claims to one source without rereading the index."""
    own: set[str] = set()
    refs: set[str] = set()
    for claim in claims_by_source.get(relative_source, ()):
        source_ref = claim.get("source_ref")
        if not isinstance(source_ref, dict):
            continue
        claim_id = str(claim.get("claim_id") or "")
        source_id = str(source_ref.get("source_id") or "")
        is_classifier = source_id.startswith("classification:")
        if claim_id:
            is_classifier = classifier_claim.get(claim_id, is_classifier)
        if is_classifier and claim_id:
            own.add(claim_id)
        if is_classifier:
            continue
        for key in ("subject_ref", "place_ref"):
            value = str(claim.get(key) or "")
            if "/" in value and not value.startswith("unresolved:"):
                refs.add(value)
        for key in ("subject_refs", "place_refs"):
            for value in claim.get(key) or ():
                text = str(value or "")
                if "/" in text and not text.startswith("unresolved:"):
                    refs.add(text)
    return own, refs


def _bounds(record: object) -> dict | None:
    value = chrono.from_dict(record)
    if value is None:
        return None
    return {
        "best": value.best,
        "earliest": value.earliest,
        "latest": value.latest,
        "granularity": value.granularity,
    }


def _resolved_subject_refs(
    values: object,
    *,
    rosters: dict[str, identity_resolution.RosterIndex],
) -> tuple[list[str], list[str], list[dict]]:
    """Resolve legacy labels only when the canonical roster has one answer."""
    refs: set[str] = set()
    unresolved: set[str] = set()
    ambiguities: list[dict] = []
    for value in values if isinstance(values, (list, tuple, set)) else ():
        mention = str(value or "").strip()
        if not mention:
            continue
        matches: dict[str, dict] = {}
        for kind, roster in rosters.items():
            for match in identity_resolution.candidates_for(
                mention, roster, entity_type=kind
            ):
                ref = str(match.get("ref") or "")
                if ref:
                    matches[ref] = match
        if len(matches) == 1:
            refs.add(next(iter(matches)))
        elif len(matches) > 1:
            ambiguities.append({
                "mention": mention,
                "candidate_refs": sorted(matches),
            })
        elif "/" in mention or mention == "self":
            refs.add(mention)
        else:
            unresolved.add(mention)
    return sorted(refs), sorted(unresolved), sorted(ambiguities, key=_canonical)


def _candidate(
    node: dict,
    *,
    roster_aliases: dict[str, tuple[str, ...]],
    rosters: dict[str, identity_resolution.RosterIndex],
) -> dict | None:
    candidate_id = str(node.get("node_id") or "")
    if not candidate_id:
        return None
    node_kind = str(node.get("node_kind") or "")
    event_kind = str(node.get("event_kind") or "")
    if node_kind == "period" and event_kind != "named_era":
        return None
    if node_kind not in ("event", "period", "episode"):
        return None
    usable = placement.usable_temporal_value(node)
    if usable is None:
        return None
    entity_refs, unresolved_mentions, entity_ref_ambiguities = _resolved_subject_refs(
        node.get("subject_refs"), rosters=rosters
    )
    aliases = {
        str(value) for value in (
            *(node.get("legacy_refs") or ()),
        ) if value
    }
    for ref in entity_refs:
        aliases.update(roster_aliases.get(ref, ()))
    canonical_roster_terms = [
        {"entity_ref": ref, "terms": list(roster_aliases[ref])}
        for ref in entity_refs
        if ref in roster_aliases
    ]
    alternatives = [
        value for value in (_bounds(row) for row in node.get("alternate_values") or ())
        if value is not None
    ]
    row = {
        "candidate_id": candidate_id,
        "node_kind": node_kind,
        "episode_id": node.get("episode_id"),
        "kind": node.get("event_kind") or node.get("node_kind"),
        "name": node.get("label") or node.get("event_kind") or candidate_id,
        "aliases": sorted(aliases),
        # Kept separate from projection-provided legacy aliases so freshness
        # can bind canonical roster authority without classifier self-churn.
        "canonical_roster_terms": canonical_roster_terms,
        "entity_refs": entity_refs,
        "unresolved_entity_mentions": unresolved_mentions,
        "entity_ref_ambiguities": entity_ref_ambiguities,
        "supported_bounds": _bounds(usable),
        "basis": node.get("basis"),
        "conflict_state": node.get("conflict_state", "none"),
        "alternatives": alternatives,
    }
    row["event_role"] = event_kind
    row["reference_keys"] = timeline_evidence.candidate_reference_keys(row)
    return row


def _normalized_human_identity_records(
    identities: object,
    operations: object,
) -> list[dict]:
    """Validated human identity decisions, with operational metadata removed."""
    rows: list[dict] = []
    for value in identities if isinstance(identities, list) else ():
        if not isinstance(value, dict):
            continue
        if value.get("origin") not in event_identity.HUMAN_ORIGINS:
            continue
        rows.append({
            key: value.get(key)
            for key in (
                "identity_id", "telling_ref", "episode_id", "relation",
                "origin", "supersedes", "telling_aliases",
            )
        })
    for value in operations if isinstance(operations, list) else ():
        if not isinstance(value, dict):
            continue
        if value.get("authority") != "human":
            continue
        rows.append({
            key: value.get(key)
            for key in (
                "operation_id", "op", "episode_id", "member_refs",
                "acted_on_episode_ids", "aliases_created",
            )
        })
    return sorted(rows, key=_canonical)


def _human_identity_records(vault_root: Path) -> list[dict]:
    return _normalized_human_identity_records(
        event_identity.load_event_identities(vault_root),
        event_identity.load_episode_operations(vault_root),
    )


def _applicable_human_identity_records(
    human_identity_records: list[dict],
    *,
    candidates: list[dict],
    prior_identities: list[dict],
) -> list[dict]:
    """Human decisions touching this source's tellings or supplied episodes."""
    episode_refs = {
        str(value)
        for row in candidates
        for value in (row.get("candidate_id"), row.get("episode_id"))
        if value
    }
    telling_refs = {
        str(value)
        for row in prior_identities
        for value in (
            row.get("telling_ref"),
            *(row.get("aliases") or ()),
        )
        if value
    }
    applicable: list[dict] = []
    for row in human_identity_records:
        row_tellings = {
            str(value)
            for value in (row.get("telling_ref"), *(row.get("telling_aliases") or ()))
            if value
        }
        row_episodes = {
            str(value)
            for value in (
                row.get("episode_id"),
                *(row.get("member_refs") or ()),
                *(row.get("acted_on_episode_ids") or ()),
                *(row.get("aliases_created") or ()),
            )
            if value
        }
        if row_tellings.intersection(telling_refs) or row_episodes.intersection(episode_refs):
            applicable.append(row)
    return applicable


def _load_roster_catalog(vault_root: Path) -> tuple[
    dict[str, tuple[str, ...]],
    dict[str, identity_resolution.RosterIndex],
    dict,
]:
    """Load and normalize each canonical roster once."""
    aliases: dict[str, tuple[str, ...]] = {}
    rosters: dict[str, identity_resolution.RosterIndex] = {}
    person_roster: dict = {}
    # Organizations use the same generic roster snapshot as the core entity
    # types even though they are deliberately outside entity_roster's
    # AI-assisted graduation pipeline. Timeline roles such as founding versus
    # employment need that existing canonical identity to remain distinct.
    for kind in ("person", "place", "period", "organization"):
        roster = entity_roster.load_roster(kind, vault_root=vault_root)
        if kind == "person":
            person_roster = roster
        rosters[kind] = identity_resolution.roster_index(roster, entity_type=kind)
        for entity in roster.get("entities") or () if isinstance(roster, dict) else ():
            if not isinstance(entity, dict):
                continue
            name = str(entity.get("name") or "").strip()
            slug = str(entity.get("slug") or name).strip()
            if not slug:
                continue
            ref = identity_resolution.entity_ref(kind, slug)
            terms = tuple(dict.fromkeys(
                text for text in (
                    name,
                    *(str(value).strip() for value in entity.get("aliases") or ()),
                ) if text
            ))
            aliases[ref] = terms
    return aliases, rosters, person_roster


def _mentioned_roster_refs(
    roster_aliases: dict[str, tuple[str, ...]],
    story_text: str,
    *,
    matchers: tuple[tuple[str, str, re.Pattern], ...] | None = None,
) -> set[str]:
    """Find exact roster phrases for retrieval, without treating them as bindings."""
    mentioned: set[str] = set()
    lowered = story_text.casefold()
    if matchers is not None:
        for ref, _term, pattern in matchers:
            if pattern.search(lowered):
                mentioned.add(ref)
        return mentioned
    for ref, terms in roster_aliases.items():
        for term in terms:
            pattern = rf"(?<!\w){re.escape(term.casefold())}(?!\w)"
            if re.search(pattern, lowered):
                mentioned.add(ref)
                break
    return mentioned


def _matched_roster_evidence(
    story_text: str,
    matchers: tuple[tuple[str, str, re.Pattern], ...],
) -> list[dict]:
    """Canonical roster terms that matched this source, including ambiguity."""
    lowered = story_text.casefold()
    matched: dict[str, list[str]] = {}
    for ref, term, pattern in matchers:
        if pattern.search(lowered):
            matched.setdefault(ref, []).append(term)
    return [
        {"entity_ref": ref, "terms": sorted(set(terms))}
        for ref, terms in sorted(matched.items())
    ]


def _source_roster_authority(
    candidates: list[dict], candidate_ids: object, roster_evidence: object,
) -> list[dict]:
    """Roster matches that can change identity for this event-local set."""
    selected = {str(value) for value in (candidate_ids or ()) if value}
    selected_terms = {
        str(term).casefold()
        for row in candidates
        if row.get("candidate_id") in selected
        for authority in row.get("canonical_roster_terms") or ()
        if isinstance(authority, dict)
        for term in authority.get("terms") or ()
        if str(term).strip()
    }
    return [
        row for row in (roster_evidence or ())
        if isinstance(row, dict) and selected_terms.intersection(
            str(term).casefold() for term in row.get("terms") or ()
        )
    ]


def _roster_context(
    vault_root: Path,
    story_text: str,
) -> tuple[
    dict[str, tuple[str, ...]],
    set[str],
    dict[str, identity_resolution.RosterIndex],
]:
    """Canonical roster aliases and exact-phrase refs used only for retrieval."""
    aliases, rosters, _person_roster = _load_roster_catalog(vault_root)
    return aliases, _mentioned_roster_refs(aliases, story_text), rosters


def _locate_unique_exact_quote(story_text: str, quote: str) -> tuple[int, int]:
    """Locate one exact quote through the canonical locator, refusing repeats."""
    import landmark_offer  # noqa: PLC0415 - avoids the timeline import cycle

    located = landmark_offer.locate(story_text, quote)
    if located is None:
        raise ClassifierContextError(
            "timeline relation evidence is not a source quote",
            code=ContextFailureCode.QUOTE_NOT_FOUND,
        )
    start = located["offset"]
    end = start + len(quote)
    if story_text[start:end] != quote:
        # The shared locator also supports whitespace-normalized readings. This
        # classifier contract deliberately accepts only byte-faithful text.
        raise ClassifierContextError(
            "timeline relation evidence is not an exact source quote",
            code=ContextFailureCode.QUOTE_NOT_EXACT,
        )
    if story_text.find(quote, end) >= 0:
        raise ClassifierContextError(
            "timeline relation evidence quote is ambiguous",
            code=ContextFailureCode.QUOTE_AMBIGUOUS,
        )
    return start, end


def _freshness_candidate(row: dict) -> dict:
    """Stable context semantics, excluding labels and machine telling aliases."""
    return {
        key: row.get(key)
        for key in (
            "candidate_id", "episode_id", "kind", "event_role", "entity_refs",
            "canonical_roster_terms",
            "unresolved_entity_mentions", "entity_ref_ambiguities",
            "supported_bounds", "basis", "conflict_state", "alternatives",
            "grounding_identity", "reference_keys",
        )
    }


def _independent_grounded_classifier_claim(claim: dict, retracted_paths: set[str]) -> bool:
    """Only verified direct facts may cross v306's classifier exclusion."""
    source_ref = claim.get("source_ref") if isinstance(claim.get("source_ref"), dict) else {}
    source_id = str(source_ref.get("source_id") or "")
    if not source_id.startswith("classification:"):
        return True
    if str(source_ref.get("source_path") or "") in retracted_paths:
        return False
    if claim.get("claim_type") not in ("date", "age") or claim.get("basis") != "explicit":
        return False
    if not timeline_evidence.is_current_classifier_claim(claim):
        return False
    return any(
        isinstance(span, dict)
        and isinstance(span.get("start"), int)
        and isinstance(span.get("end"), int)
        for span in claim.get("evidence") or ()
    )


def _grounding_identity(claim_ids: object, claims_by_id: dict[str, dict]) -> list[dict]:
    rows: list[dict] = []
    for claim_id in sorted(str(value) for value in (claim_ids or ()) if value):
        claim = claims_by_id.get(claim_id)
        if not isinstance(claim, dict):
            continue
        source_ref = claim.get("source_ref") if isinstance(claim.get("source_ref"), dict) else {}
        rows.append({
            "claim_type": claim.get("claim_type"),
            "temporal_value": claim.get("temporal_value"),
            "subject_ref": claim.get("subject_ref"),
            "subject_mention": claim.get("subject_mention"),
            "source_path": source_ref.get("source_path"),
            "source_revision": source_ref.get("revision"),
            "evidence": claim.get("evidence"),
        })
    return rows


def _prior_identities_from_manifest(manifest: object, relative_source: str) -> list[dict]:
    rows: list[dict] = []
    for row in manifest.get("tellings") or () if isinstance(manifest, dict) else ():
        if (not isinstance(row, dict)
                or str(row.get("source_path") or "") != relative_source):
            continue
        rows.append({
            "telling_ref": row.get("telling_ref"),
            "recorder_event_id": row.get("recorder_event_id"),
            "event_refs": list(row.get("event_refs") or ()),
            "era_refs": list(row.get("era_refs") or ()),
            "aliases": list(row.get("aliases") or ()),
            "superseded_by": row.get("superseded_by"),
            "bound_identity_ids": list(row.get("bound_identity_ids") or ()),
        })
    return sorted(rows, key=_canonical)


def _prior_identities(vault_root: Path, source_path: Path) -> list[dict]:
    try:
        manifest = event_identity.read_telling_manifest(vault_root) or {}
    except (OSError, ValueError):
        manifest = {}
    return _prior_identities_from_manifest(
        manifest, _relative_source(vault_root, source_path)
    )


def _derive_context_timeline(vault_root: Path, index: dict, records: dict, roster: dict):
    """Use publication's input authorities and its existing pure temporal fold."""
    import temporal_publication  # noqa: PLC0415
    import temporal_timeline  # noqa: PLC0415

    return temporal_timeline.derive_calculated_timeline(
        index, roster_snapshot=roster,
        **temporal_publication.load_derivation_inputs(vault_root, episode_records=records),
    )


def _load_context_catalog(vault_root: Path) -> dict:
    """Load source-independent classifier context for one invocation."""
    import episode_fold  # noqa: PLC0415 - avoids the timeline import cycle

    roster_aliases, rosters, person_roster = _load_roster_catalog(vault_root)
    roster_matchers = tuple(
        (ref, term, re.compile(rf"(?<!\w){re.escape(term.casefold())}(?!\w)"))
        for ref, terms in roster_aliases.items()
        for term in terms
    )
    index = temporal_store.fold_active_index(vault_root)
    retracted_paths = timeline_evidence.active_global_retracted_paths(vault_root)
    # Filter before the canonical fold. Contextual classifier claims remain
    # excluded; only exact-source direct date/age facts may become candidates.
    independent_index = {**index, "claims": [
        row for row in index.get("claims") or ()
        if _independent_grounded_classifier_claim(row, retracted_paths)
    ]}
    claims_by_source, classifier_claims = _claim_catalog(independent_index)
    independent_claims_by_id = {
        str(row.get("claim_id") or ""): row
        for row in independent_index.get("claims") or ()
        if isinstance(row, dict) and row.get("claim_id")
    }
    records = episode_fold.load_episode_records(vault_root, manifest={})
    identities, operations = records["bindings"], records["operations"]
    independent_manifest = event_identity.build_telling_manifest(
        vault_root, bindings=identities, active_index=independent_index
    )
    records["manifest"] = independent_manifest
    projection = _derive_context_timeline(vault_root, independent_index, records, person_roster)
    try:
        manifest = event_identity.read_telling_manifest(vault_root) or {}
    except (OSError, ValueError):
        manifest = {}

    # Human decisions can name a historical classifier telling. Resolve only
    # their explicit refs through immutable receipt provenance, not through the
    # mutable manifest's inferred aliases, successors or bound_identity_ids.
    human_records = _normalized_human_identity_records(identities, operations)
    explicit_refs = {
        str(ref) for row in human_records
        for ref in (row.get("telling_ref"), *(row.get("telling_aliases") or ()))
        if ref
    }
    human_tellings_by_source: dict[str, set[str]] = {}
    for row in index.get("claims") or ():
        source_ref = row.get("source_ref") or {}
        ref = str(source_ref.get("source_id") or "")
        path = str(source_ref.get("source_path") or "")
        if ref in explicit_refs and path:
            human_tellings_by_source.setdefault(path, set()).add(ref)

    candidates: list[tuple[dict, frozenset[str]]] = []
    for node in projection.nodes:
        if not isinstance(node, dict):
            continue
        claim_ids = frozenset(
            str(value) for value in node.get("input_claim_refs") or () if value
        )
        row = _candidate(node, roster_aliases=roster_aliases, rosters=rosters)
        if row is not None:
            row["grounding_identity"] = _grounding_identity(
                claim_ids, independent_claims_by_id
            )
            candidates.append((row, claim_ids))
    candidates.sort(key=lambda item: (
        0 if item[0].get("node_kind") == "episode" else 1,
        str(item[0].get("kind") or ""),
        str(item[0].get("candidate_id") or ""),
    ))
    # A mixed node can contain a target source's newly grounded fact plus an
    # older independent recorder claim.  Keep a source-free form of those
    # nodes so the target never receives bounds, conflicts, or aliases derived
    # from its own output.  This is one additional pure fold per catalog, not
    # one fold per source; candidates supported only by classifier facts are
    # conservatively absent from the baseline.
    baseline_candidates: dict[str, dict] = {}
    if any(classifier_claims.values()):
        baseline_index = {**independent_index, "claims": [
            row for row in independent_index.get("claims") or ()
            if not str((row.get("source_ref") or {}).get("source_id") or "").startswith(
                "classification:"
            )
        ]}
        baseline_claims_by_id = {
            str(row.get("claim_id") or ""): row
            for row in baseline_index["claims"]
            if isinstance(row, dict) and row.get("claim_id")
        }
        baseline_records = dict(records)
        baseline_records["manifest"] = event_identity.build_telling_manifest(
            vault_root, bindings=identities, active_index=baseline_index
        )
        baseline_projection = _derive_context_timeline(
            vault_root, baseline_index, baseline_records, person_roster
        )
        for node in baseline_projection.nodes:
            if not isinstance(node, dict):
                continue
            claim_ids = frozenset(
                str(value) for value in node.get("input_claim_refs") or () if value
            )
            row = _candidate(node, roster_aliases=roster_aliases, rosters=rosters)
            if row is None:
                continue
            row["grounding_identity"] = _grounding_identity(
                claim_ids, baseline_claims_by_id
            )
            baseline_candidates[str(row.get("candidate_id") or "")] = row
    return {
        "roster_aliases": roster_aliases,
        "roster_matchers": roster_matchers,
        "claims_by_source": claims_by_source,
        "classifier_claims": classifier_claims,
        "identities_by_id": {
            str(row.get("identity_id") or ""): row
            for row in identities
            if isinstance(row, dict)
        },
        "human_identity_records": human_records,
        "human_tellings_by_source": human_tellings_by_source,
        "independent_manifest": independent_manifest,
        "manifest": manifest,
        "correction_records": source_integrity.read_correction_records(
            corrections_dir=vault_root / "sources" / "corrections",
            repo_dir=vault_root,
        ),
        "classifications": _classification_records(vault_root),
        "retracted_paths": retracted_paths,
        "candidates": candidates,
        "baseline_candidates": baseline_candidates,
    }


def _build_context_snapshot_from_catalog(
    vault_root: Path,
    source_path: Path,
    catalog: dict,
    *,
    source_bytes: bytes | None = None,
    max_candidates: int = MAX_CONTEXT_CANDIDATES,
) -> dict:
    """Apply source-specific retrieval and exclusions to one loaded catalog."""
    root = Path(vault_root)
    source = Path(source_path)
    raw = source.read_bytes() if source_bytes is None else source_bytes
    story_text = raw.decode("utf-8", errors="replace")
    relative = _relative_source(root, source)
    own_claims, grounded_refs = _claim_context_from_catalog(
        relative,
        catalog["claims_by_source"],
        catalog["classifier_claims"],
    )
    roster_evidence = _matched_roster_evidence(
        story_text,
        catalog["roster_matchers"],
    )
    grounded_refs |= {
        row["entity_ref"] for row in roster_evidence
    }
    prior_identities = _prior_identities_from_manifest(catalog["manifest"], relative)
    authority_tellings = _prior_identities_from_manifest(
        catalog["independent_manifest"], relative
    ) + [
        {"telling_ref": ref}
        for ref in sorted(catalog["human_tellings_by_source"].get(relative, ()))
    ]
    source_decisions = _applicable_human_identity_records(
        catalog["human_identity_records"], candidates=[], prior_identities=authority_tellings
    )
    identities = catalog["identities_by_id"]
    bound_episode_ids = {
        str(identities[identity_id].get("episode_id") or "")
        for telling in authority_tellings
        for identity_id in telling.get("bound_identity_ids") or ()
        if identity_id in identities and identities[identity_id].get("episode_id")
    }
    bound_episode_ids.update(
        str(row["episode_id"]) for row in source_decisions if row.get("episode_id")
    )
    # A target source must not consume its own grounded fact through a mixed
    # episode.  Replace that enriched form with the source-free baseline; if
    # no independent baseline exists, exclude the candidate conservatively.
    candidates = []
    for row, claim_ids in catalog["candidates"]:
        candidate = row
        if own_claims.intersection(claim_ids):
            candidate = catalog["baseline_candidates"].get(
                str(row.get("candidate_id") or "")
            )
            if candidate is None:
                continue
        candidates.append(dict(candidate))

    forced_ids = set(bound_episode_ids)
    forced_ids.update(
        str(row.get("candidate_id") or "")
        for row in candidates
        if {
            ref for ref in row.get("entity_refs") or ()
            if not timeline_evidence.is_generic_owner_reference(ref)
        }.intersection(
            ref for ref in grounded_refs
            if not timeline_evidence.is_generic_owner_reference(ref)
        )
    )
    existing = catalog.get("classifications", {}).get(relative) or {}
    stored_events = [
        dict(row) for row in existing.get("events") or () if isinstance(row, dict)
    ]
    event_contexts: dict[str, dict] = {}
    if existing and isinstance(existing.get("events"), list):
        for event in stored_events:
            context = timeline_evidence.build_event_context(
                event,
                candidates,
                forced_candidate_ids=forced_ids,
                max_candidates=max_candidates,
            )
            event_contexts[context["event_key"]] = context
    else:
        # A full extraction has no stable event keys yet. Search the source as
        # one provisional context; event-local contexts replace it after filing.
        provisional = {
            "title": source.stem,
            "description": story_text,
            "subject": "self",
            "places": [],
            "date": None,
        }
        context = timeline_evidence.build_event_context(
            provisional,
            candidates,
            forced_candidate_ids=forced_ids,
            max_candidates=max_candidates,
        )
        event_contexts[context["event_key"]] = context

    selected_ids = {
        candidate_id
        for context in event_contexts.values()
        for candidate_id in context.get("candidate_ids") or ()
    }
    selected = [
        row for row in candidates if str(row.get("candidate_id") or "") in selected_ids
    ]
    selected.sort(key=lambda row: str(row.get("candidate_id") or ""))
    if len(selected) > timeline_evidence.MAX_TOTAL_CANDIDATES:
        retained = {
            str(row.get("candidate_id") or "")
            for row in selected[:timeline_evidence.MAX_TOTAL_CANDIDATES]
        }
        selected = selected[:timeline_evidence.MAX_TOTAL_CANDIDATES]
        for context in event_contexts.values():
            omitted = [
                candidate_id for candidate_id in context.get("candidate_ids") or ()
                if candidate_id not in retained
            ]
            if omitted:
                context["candidate_ids"] = [
                    candidate_id for candidate_id in context["candidate_ids"]
                    if candidate_id in retained
                ]
                context["complete"] = False
                context["remaining_candidate_count"] += len(omitted)
                context["input_fingerprint"] = timeline_evidence.digest({
                    "prior": context["input_fingerprint"],
                    "total_prompt_omitted": omitted,
                })
    truncated = any(not row.get("complete") for row in event_contexts.values())
    human_decisions_all = _applicable_human_identity_records(
        catalog["human_identity_records"],
        candidates=selected,
        prior_identities=authority_tellings,
    )
    human_decisions = human_decisions_all
    decision_truncated = False
    context_truncated = truncated
    for context in event_contexts.values():
        context["input_fingerprint"] = timeline_evidence.digest({
            "event_context": context["input_fingerprint"],
            "human_identity_decisions": human_decisions,
            "source_roster_authority": _source_roster_authority(
                selected, context.get("candidate_ids"), roster_evidence
            ),
        })
    for row in selected:
        memberships = [
            context for context in event_contexts.values()
            if row.get("candidate_id") in (context.get("candidate_ids") or ())
        ]
        row["candidate_set_complete"] = all(
            context.get("complete") for context in memberships
        )
        row["relevant_event_keys"] = sorted(
            context["event_key"] for context in memberships
        )
    digest_input = {
        "schema_version": CONTEXT_SCHEMA_VERSION,
        "event_contexts": {
            key: {
                "candidate_ids": value.get("candidate_ids"),
                "reference_keys": value.get("reference_keys"),
                "unmatched_reference_keys": value.get("unmatched_reference_keys"),
                "complete": value.get("complete"),
                "remaining_candidate_count": value.get("remaining_candidate_count"),
                "input_fingerprint": value.get("input_fingerprint"),
            }
            for key, value in sorted(event_contexts.items())
        },
        "human_identity_decisions": human_decisions,
    }
    active_corrections = source_integrity.active_correction_leaves(
        source_integrity.corrections_targeting(
            source, repo_dir=root, records=catalog["correction_records"]
        )
    )
    snapshot = {
        "schema_version": CONTEXT_SCHEMA_VERSION,
        "source_revision": effective_source_revision(
            root,
            source,
            source_bytes=raw,
            correction_records=catalog["correction_records"],
        ),
        "context_digest": _digest(digest_input),
        "prompt_version": PROMPT_VERSION,
        "extractor_version": EXTRACTOR_VERSION,
        "context_complete": not context_truncated,
        "context_truncated": context_truncated,
        "candidate_count": len(selected),
        "remaining_candidate_count": max(
            (
                context.get("remaining_candidate_count") or 0
                for context in event_contexts.values()
            ),
            default=0,
        ),
        "catalog_omitted_count": max(0, len(candidates) - len(selected)),
        "decision_count": len(human_decisions),
        "remaining_decision_count": max(0, len(human_decisions_all) - len(human_decisions)),
        "candidates": selected,
        "event_contexts": event_contexts,
        "source_roster_evidence": roster_evidence,
        "grounding_allowed": not bool(active_corrections),
        "human_identity_decisions": human_decisions,
        "source_identity_decision_ids": sorted(
            str(row.get("identity_id") or "") for row in source_decisions
            if row.get("identity_id")
        ),
        # Useful to the prompt but excluded from context_digest: classifier
        # rereads may rekey these identities and must not trigger themselves.
        "prior_event_identities": prior_identities,
    }
    return snapshot


def build_context_snapshot(
    vault_root: str | Path,
    source_path: str | Path,
    *,
    source_bytes: bytes | None = None,
    max_candidates: int = MAX_CONTEXT_CANDIDATES,
) -> dict:
    """Build the bounded prompt context from independently fresh durable reads."""
    root = Path(vault_root)
    return _build_context_snapshot_from_catalog(
        root,
        Path(source_path),
        _load_context_catalog(root),
        source_bytes=source_bytes,
        max_candidates=max_candidates,
    )


def load_context_catalog(vault_root: str | Path) -> dict:
    """Load the immutable-for-one-operation context catalog once.

    Batch planners and batch filers use this public boundary so hundreds of
    source-specific snapshots do not refold independent evidence or reread
    claims, rosters, identity decisions and manifests hundreds of times.
    """
    return _load_context_catalog(Path(vault_root))


def build_context_snapshot_from_catalog(
    vault_root: str | Path,
    source_path: str | Path,
    catalog: dict,
    *,
    source_bytes: bytes | None = None,
    max_candidates: int = MAX_CONTEXT_CANDIDATES,
) -> dict:
    """Build one source snapshot from a caller-owned shared catalog."""
    return _build_context_snapshot_from_catalog(
        Path(vault_root),
        Path(source_path),
        catalog,
        source_bytes=source_bytes,
        max_candidates=max_candidates,
    )


def _event_context(snapshot: dict, event: dict) -> dict:
    key = timeline_evidence.event_key(event)
    contexts = snapshot.get("event_contexts")
    if isinstance(contexts, dict) and isinstance(contexts.get(key), dict):
        return contexts[key]
    candidates = [row for row in snapshot.get("candidates") or () if isinstance(row, dict)]
    # Context lookup must not add event_key to a loaded base classification;
    # the caller owns when that schema enrichment is persisted.
    context = timeline_evidence.build_event_context(dict(event), candidates)
    if snapshot.get("context_truncated"):
        context["complete"] = False
    selected = set(context.get("candidate_ids") or ())
    if any(
        row.get("candidate_id") in selected
        and not row.get("candidate_set_complete", True)
        for row in candidates
    ):
        context["complete"] = False
    context["input_fingerprint"] = timeline_evidence.digest({
        "event_context": context["input_fingerprint"],
        "human_identity_decisions": snapshot.get("human_identity_decisions") or [],
        "source_roster_authority": _source_roster_authority(
            candidates,
            context.get("candidate_ids"),
            snapshot.get("source_roster_evidence") or [],
        ),
    })
    return context


def snapshot_metadata_for_events(snapshot: dict, events: object) -> dict:
    """Four-key snapshot identity for the event-local context just accepted."""
    candidates = [row for row in snapshot.get("candidates") or () if isinstance(row, dict)]
    raw_contexts = [
        timeline_evidence.build_event_context(event, candidates)
        for event in (events if isinstance(events, list) else ())
        if isinstance(event, dict)
    ]
    selected_ids = {
        candidate_id for context in raw_contexts
        for candidate_id in context.get("candidate_ids") or ()
    }
    selected_episodes = {
        str(row.get("episode_id") or "") for row in candidates
        if row.get("candidate_id") in selected_ids and row.get("episode_id")
    }
    source_decision_ids = set(snapshot.get("source_identity_decision_ids") or ())
    decisions = [
        row for row in snapshot.get("human_identity_decisions") or ()
        if (row.get("identity_id") in source_decision_ids
            or row.get("episode_id") in selected_episodes)
    ]
    accepted_snapshot = {**snapshot, "human_identity_decisions": decisions}
    contexts = {
        context["event_key"]: context
        for event in (events if isinstance(events, list) else ())
        if isinstance(event, dict)
        for context in (_event_context(accepted_snapshot, event),)
    }
    digest_input = {
        "schema_version": CONTEXT_SCHEMA_VERSION,
        "event_contexts": {
            key: {
                "candidate_ids": value.get("candidate_ids"),
                "reference_keys": value.get("reference_keys"),
                "unmatched_reference_keys": value.get("unmatched_reference_keys"),
                "complete": value.get("complete"),
                "remaining_candidate_count": value.get("remaining_candidate_count"),
                "input_fingerprint": value.get("input_fingerprint"),
            }
            for key, value in sorted(contexts.items())
        },
        "human_identity_decisions": decisions,
    }
    accepted = dict(accepted_snapshot)
    accepted["context_digest"] = _digest(digest_input)
    return snapshot_metadata(accepted)


def validate_response(
    result: object,
    snapshot: dict,
    story_text: str,
    *,
    mode: str = "full",
    existing_events: object = None,
    require_event_contract: bool = False,
) -> dict:
    """Validate one model response against exactly the context it observed."""
    if not isinstance(result, dict):
        raise ClassifierContextError(
            "classification response must be a mapping",
            code=ContextFailureCode.RESPONSE_NOT_MAPPING,
        )
    expected = snapshot_metadata(snapshot)
    echoed = snapshot_metadata(result.get("_classification_snapshot"))
    if not all(echoed.values()) or echoed != expected:
        raise ClassifierContextError(
            "classification snapshot is missing or stale",
            code=ContextFailureCode.SNAPSHOT_MISMATCH,
        )
    all_candidates = {
        str(row.get("candidate_id")): row
        for row in snapshot.get("candidates") or ()
        if isinstance(row, dict) and row.get("candidate_id")
    }
    events = result.get("events", [])
    if not isinstance(events, list):
        raise ClassifierContextError(
            "events must be a list", code=ContextFailureCode.EVENTS_NOT_LIST,
        )
    bases: dict[str, dict] = {}
    if mode == "timeline":
        for value in existing_events if isinstance(existing_events, list) else ():
            if not isinstance(value, dict):
                continue
            key = timeline_evidence.event_key(value)
            if key in bases:
                raise ClassifierContextError(
                    "base classification has duplicate event keys",
                    code=ContextFailureCode.EVENT_KEYS_INVALID,
                )
            bases[key] = value
        supplied = [
            str(value.get("event_key") or "") if isinstance(value, dict) else ""
            for value in events
        ]
        if (any(not key for key in supplied)
                or len(supplied) != len(set(supplied))
                or set(supplied) != set(bases)):
            raise ClassifierContextError(
                "timeline response must contain each existing event key exactly once",
                code=ContextFailureCode.EVENT_KEYS_INVALID,
            )

    normalized_events: list[dict] = []
    for event in events:
        if not isinstance(event, dict):
            raise ClassifierContextError(
                "each event must be a mapping", code=ContextFailureCode.EVENT_NOT_MAPPING,
            )
        if mode == "timeline":
            if set(event) != timeline_evidence.EVENT_DELTA_KEYS:
                raise ClassifierContextError(
                    "timeline event is not a link-only delta",
                    code=ContextFailureCode.EVENT_KEYS_INVALID,
                )
            key = str(event["event_key"])
            base = bases[key]
        else:
            base = event
            try:
                key = timeline_evidence.ensure_event_key(base)
            except timeline_evidence.TimelineEvidenceError as exc:
                raise ClassifierContextError(
                    str(exc), code=ContextFailureCode.EVENT_KEYS_INVALID,
                ) from None

        context = _event_context(snapshot, base)
        candidate_ids = list(context.get("candidate_ids") or ())
        candidates = {
            candidate_id: all_candidates[candidate_id]
            for candidate_id in candidate_ids if candidate_id in all_candidates
        }
        relation = event.get("timeline_relation")
        if relation is None:
            candidate = None
        else:
            if not isinstance(relation, dict) or relation.get("relation") not in RELATIONS:
                raise ClassifierContextError(
                    "timeline relation must be within, before, or after",
                    code=ContextFailureCode.RELATION_INVALID,
                )
            candidate_id = str(relation.get("candidate_id") or "")
            candidate = candidates.get(candidate_id)
            if candidate is None:
                raise ClassifierContextError(
                    "timeline relation references an unknown event candidate id",
                    code=ContextFailureCode.CANDIDATE_UNKNOWN,
                )
            if not context.get("complete"):
                raise ClassifierContextError(
                    "timeline relation candidate set is incomplete",
                    code=ContextFailureCode.CONTEXT_INCOMPLETE,
                )
            if (candidate.get("unresolved_entity_mentions")
                    or candidate.get("entity_ref_ambiguities")):
                raise ClassifierContextError(
                    "timeline relation candidate identity is unresolved or ambiguous",
                    code=ContextFailureCode.CANDIDATE_AMBIGUOUS,
                )
            evidence = relation.get("evidence")
            if not isinstance(evidence, dict):
                raise ClassifierContextError(
                    "timeline relation requires source evidence",
                    code=ContextFailureCode.EVIDENCE_NOT_MAPPING,
                )
            quote = evidence.get("quote")
            if not isinstance(quote, str) or not quote:
                raise ClassifierContextError(
                    "timeline relation evidence quote is required",
                    code=ContextFailureCode.QUOTE_MISSING,
                )
            start, end = _locate_unique_exact_quote(story_text, quote)
            evidence["start"] = start
            evidence["end"] = end
            refs = relation.get("entity_refs")
            allowed = set(candidate.get("entity_refs") or ())
            if (not isinstance(refs, list) or not refs
                    or any(str(ref) not in allowed for ref in refs)):
                raise ClassifierContextError(
                    "timeline relation entity refs are not allowlisted",
                    code=ContextFailureCode.ENTITY_REFS_INVALID,
                )
            if not timeline_evidence.quote_disambiguates(
                    candidate, list(candidates.values()), quote):
                raise ClassifierContextError(
                    "source quote does not disambiguate competing candidates",
                    code=ContextFailureCode.CANDIDATE_NOT_DISAMBIGUATED,
                )

        try:
            grounding = timeline_evidence.normalize_source_grounding(
                event.get("source_grounding"),
                base,
                story_text=story_text,
                source_revision=str(snapshot.get("source_revision") or ""),
                grounding_allowed=bool(snapshot.get("grounding_allowed", True)),
            )
            raw_resolution = event.get("timeline_resolution")
            if raw_resolution is None and not require_event_contract:
                raw_resolution = {
                    "status": (
                        "linked" if relation is not None else
                        "incomplete" if not context.get("complete") else
                        "missing_evidence"
                    ),
                    "candidate_ids": candidate_ids,
                    "reason": "Legacy event awaits an explicit evidence-link outcome.",
                }
            resolution = timeline_evidence.normalize_resolution(
                raw_resolution,
                event_key_value=key,
                candidate_ids=candidate_ids,
                context_complete=bool(context.get("complete")),
                source_revision=str(snapshot.get("source_revision") or ""),
                prompt_version=str(snapshot.get("prompt_version") or ""),
                input_fingerprint=str(context.get("input_fingerprint") or ""),
                relation=relation,
            )
        except timeline_evidence.TimelineEvidenceError as exc:
            code = (
                ContextFailureCode.GROUNDING_INVALID
                if exc.code.startswith("grounding_") else ContextFailureCode.RESOLUTION_INVALID
            )
            raise ClassifierContextError(str(exc), code=code) from None
        event["source_grounding"] = grounding
        event["timeline_resolution"] = resolution
        normalized_events.append(event)
    result["events"] = normalized_events
    return result


def _classification_records(vault_root: Path) -> dict[str, dict]:
    records: dict[str, dict] = {}
    root = vault_data_path("classifications", vault_root=vault_root)
    if not root.exists():
        return records
    for path in sorted(root.glob("*.json")):
        value = _read_json(path, None)
        if isinstance(value, dict) and value.get("source_path"):
            records[str(value["source_path"])] = value
    return records


def refresh_reason(snapshot: dict, classification: object) -> str | None:
    row = classification if isinstance(classification, dict) else {}
    if not row:
        return "unclassified"
    if row.get("stale"):
        return "stale"
    recorded = snapshot_metadata(row.get("classification_snapshot"))
    current = snapshot_metadata(snapshot)
    if not all(recorded.values()):
        return "legacy_snapshot"
    if recorded["source_revision"] != current["source_revision"]:
        return "source_changed"
    if recorded["extractor_version"] != current["extractor_version"]:
        return "classifier_changed"
    if recorded["prompt_version"] != current["prompt_version"]:
        return "relationship_changed"
    if recorded["context_digest"] != current["context_digest"]:
        return "context_changed"
    return None


def select_refresh_targets(
    vault_root: str | Path,
    source_paths: object,
    *,
    limit: int = MAX_REFRESH_TARGETS,
    classifications: dict[str, dict] | None = None,
) -> dict:
    """Canonical bounded refresh selection for maintenance and host schedulers."""
    root = Path(vault_root)
    cap = max(0, min(int(limit), MAX_REFRESH_TARGETS))
    sources: list[Path] = []
    for value in source_paths if isinstance(source_paths, (list, tuple, set)) else ():
        source = Path(value)
        if not source.is_absolute():
            source = root / source
        if not source.exists() or not source.is_file():
            continue
        sources.append(source)
    if not sources:
        return {
            "targets": [],
            "selected_count": 0,
            "pending_count": 0,
            "remaining_count": 0,
            "complete": True,
            "limit": cap,
        }

    records = _classification_records(root) if classifications is None else classifications
    catalog = _load_context_catalog(root)
    pending: list[dict] = []
    for source in sources:
        relative = _relative_source(root, source)
        snapshot = _build_context_snapshot_from_catalog(root, source, catalog)
        reason = refresh_reason(snapshot, records.get(relative))
        if reason:
            pending.append({"source_path": relative, "reason": reason, "snapshot": snapshot_metadata(snapshot)})
    pending.sort(key=lambda row: (row["reason"] != "stale", row["source_path"]))
    targets = pending[:cap]
    return {
        "targets": targets,
        "selected_count": len(targets),
        "pending_count": len(pending),
        "remaining_count": max(0, len(pending) - len(targets)),
        "complete": len(pending) <= len(targets),
        "limit": cap,
    }


__all__ = [
    "ClassifierContextError",
    "ContextFailureCode",
    "CONTEXT_SCHEMA_VERSION",
    "EXTRACTOR_VERSION",
    "MAX_CONTEXT_CANDIDATES",
    "MAX_CONTEXT_DECISIONS",
    "MAX_REFRESH_TARGETS",
    "PROMPT_VERSION",
    "RELATIONS",
    "SNAPSHOT_KEYS",
    "build_context_snapshot",
    "build_context_snapshot_from_catalog",
    "effective_source_revision",
    "load_context_catalog",
    "refresh_reason",
    "select_refresh_targets",
    "snapshot_metadata",
    "source_revision",
    "validate_response",
]
