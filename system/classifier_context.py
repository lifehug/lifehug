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
PROMPT_VERSION = "contextual-timeline:3"
EXTRACTOR_VERSION = "story-classifier:2"
MAX_CONTEXT_CANDIDATES = 64
MAX_CONTEXT_DECISIONS = 64
MAX_REFRESH_TARGETS = 50
#: v373 snapshot keys read only by `timeline_settlement`; never in a prompt
#: and never in ``context_digest``.
LINK_REMAP_FIELD = "link_remap"
CANDIDATE_IDENTITY_FIELD = "candidate_identity"
#: v375 snapshot key, read only by :func:`refresh_reason`; never in a prompt
#: and never in ``context_digest``: the stored links this source holds that the
#: drawing neither draws nor redirects.
LINK_ORPHANED_FIELD = "orphaned_links"
LINK_ORPHANED = "link_orphaned"
#: v375 snapshot key read only when a timeline refresh stamps its result
#: (:func:`snapshot_metadata_after_timeline_refile`).
REFILED_DIGEST_FIELD = "refiled_context_digest"

#: v375, the owner's ruling of 2026-09-29, in his words: "A software re-key is
#: not a change to my life; carry links over."
#:
#: `docs/pr-specs/classifier-independent-context.md` already binds that
#: "machine manifest rekeys ... cannot alter freshness"; a node id is a
#: machine key too (a hash of kind, subject WORDS and discriminator,
#: `temporal_projection.derive_node_id`), and until v375 the digest named every
#: candidate by it, so a rule move that re-minted ids re-read stories nothing
#: had changed. The digest now names a candidate by its IDENTITY, written in
#: the id space its classification was filed in: a candidate whose node id the
#: stored reading filed keeps that id; a candidate whose id is new stands for a
#: filed id that vanished when that id is provably the same thing (the
#: projection's own ``node_aliases`` walks to it, or, when no other candidate of
#: the event shares its kind and entities, the vanished id recomputes from its
#: kind, event kind, a word its entities are known by and a discriminator it
#: carries); anything else keeps its own id and is an honest change. Every
#: semantic field (roster terms, bounds, basis, conflict state, completeness,
#: ambiguities, human decisions, grounding identity) stays in the digest
#: exactly as before: the ruling narrows the machine-key dependency only.
#: A stored link whose node id the drawing neither draws nor redirects is
#: ``link_orphaned``, never silently ``anchor_unresolved``.
A_RE_KEY_IS_NOT_A_CHANGE_TO_A_LIFE = (
    "a software re-key is not a change to a life: freshness names each "
    "candidate by the id its classification filed for the same identity, so "
    "a node id that moved while nothing it means moved changes no context "
    "digest; a stored link follows its node through the projection's own "
    "redirect, and a link the drawing neither draws nor redirects is pending "
    "as link_orphaned"
)
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
    RELATION_SHAPE_INVALID = "context_relation_shape_invalid"
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
    # The timeline owns this normalization. Import locally because the
    # evidence/context modules are themselves timeline dependencies.
    from temporal_timeline import is_owner_reference_only

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
            # One exact key is not uniqueness when several people answer to the
            # word (v335). `identity_resolution` owns the census; this surface
            # reports the collision as the ambiguity it is rather than binding
            # whichever person the roster happened to spell shortest.
            bearers: set[str] = set()
            for kind, roster in rosters.items():
                bearers.update(
                    identity_resolution.shared_name_token_refs(
                        mention, roster, entity_type=kind
                    )
                )
            if len(bearers) > 1:
                ambiguities.append({
                    "mention": mention,
                    "candidate_refs": sorted(bearers),
                })
            else:
                refs.add(next(iter(matches)))
        elif len(matches) > 1:
            ambiguities.append({
                "mention": mention,
                "candidate_refs": sorted(matches),
            })
        elif is_owner_reference_only(mention):
            refs.add("self")
        elif "/" in mention or mention == "self":
            refs.add(mention)
        else:
            unresolved.add(mention)
    return sorted(refs), sorted(unresolved), sorted(ambiguities, key=_canonical)


#: Event roles that are single occurrences whatever precision dates them. A
#: wedding day, a birth, a death or a graduation has no inside to be `within`;
#: only a duration does.
POINT_EVENT_ROLES = frozenset({"birth", "death", "married", "wedding", "graduation"})


def temporal_shape(node_kind: object, event_kind: object, bounds: object) -> str:
    """``point`` or ``interval``: what `within` may legitimately attach to.

    A named period is always an interval. A point role (a wedding, a birth, a
    death, a graduation) is always a point, whatever its bounds. Everything
    else is an interval, even when it is recorded to the day: "the week we
    launched" sits inside a founding dated 2016-09-12 just as "during that
    year" sits inside a year, while "during that wedding day" would place a
    bankruptcy on a wedding. Shape follows the role, never the precision.
    """
    if str(node_kind or "") == "period":
        return "interval"
    if str(event_kind or "") in POINT_EVENT_ROLES:
        return "point"
    return "interval"


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
    if (unresolved_mentions and not entity_refs and not entity_ref_ambiguities
            and str(node.get("occurrence_subject_scope") or "") == "owner"):
        # The projection already scoped this occurrence to the owner and the
        # only mention is the node's own label: an employer, a school, a
        # company. That is the thing the owner did, not a person whose
        # identity is open. The entity is the owner; the label stays a name.
        # Compare after the owner rewrite so "speaker's mission" names the same
        # thing as the label "your mission".
        from temporal_timeline import owner_rewrite

        label_key = normalized_mention_key(owner_rewrite(node.get("label")))
        if label_key and all(
            normalized_mention_key(owner_rewrite(mention)) == label_key
            for mention in unresolved_mentions
        ):
            entity_refs, unresolved_mentions = ["self"], []
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
        "temporal_shape": temporal_shape(node_kind, event_kind, _bounds(usable)),
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


def _grounded_candidate_role(
    node: dict,
    claim_ids: object,
    claims_by_id: dict[str, dict],
) -> str:
    """Expose one grounded source role without rewriting episode authority."""
    canonical = str(node.get("event_kind") or "")
    if canonical not in ("", "moment"):
        return canonical
    roles = {
        str(claim.get("event_kind") or "")
        for claim_id in claim_ids or ()
        if isinstance((claim := claims_by_id.get(str(claim_id))), dict)
        and timeline_evidence.is_current_classifier_claim(claim)
        and str(claim.get("event_kind") or "") not in ("", "moment")
    }
    return next(iter(roles)) if len(roles) == 1 else canonical


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


def _landmark_place_refs(vault_root: Path) -> dict[str, str]:
    """``{landmark source_id: place_ref}`` for every promoted landmark record.

    v373. A landmark stay names the roster place it is (``place_ref``) while
    its node is keyed on the words it is called by (its nickname or label).
    When the person renames a stay the node id moves and the place does not;
    this map is how a stored link finds the renamed stay again
    (``timeline_settlement.A_RE_KEYED_LINK_REMAPS_BY_IDENTITY``). Unreadable
    records are skipped, the way every landmark reader degrades.
    """
    try:
        import landmark_projection  # noqa: PLC0415 - avoids an import cycle

        rows = landmark_projection.load_landmark_sources(vault_root)
    except Exception:  # noqa: BLE001 - an identity hint, never a failure
        return {}
    refs: dict[str, str] = {}
    for row in rows or ():
        if not isinstance(row, dict):
            continue
        record = row.get("record") if isinstance(row.get("record"), dict) else {}
        source_id = str(row.get("source_id") or "")
        place_ref = str(record.get("place_ref") or "")
        if source_id and place_ref:
            refs[source_id] = place_ref
    return refs


def _candidate_identity(
    node: dict,
    row: dict,
    claim_ids: object,
    claims_by_id: dict[str, dict],
    landmark_place_refs: dict[str, str],
) -> dict:
    """What a candidate IS, for re-key remapping only (v373).

    Never in the prompt and never in ``context_digest``: it is read only by
    ``timeline_settlement`` to prove that a vanished node id is this node under
    an earlier name. ``identity_refs`` are the candidate's own entity refs plus
    the roster place a landmark record says the stay is; ``discriminators`` are
    every value the node-id minters use to separate repeats (a stated start, a
    promoted source id, an episode id).
    """
    import identity_resolution as ident  # noqa: PLC0415

    refs = {str(ref) for ref in row.get("entity_refs") or () if ref}
    discriminators: set[str] = set()
    for value in (node.get("episode_id"),):
        if value:
            discriminators.add(str(value))
    best = node.get("best_temporal_value")
    if isinstance(best, dict):
        for key in ("best", "earliest"):
            text = str(best.get(key) or "").split("/")[0].strip()
            if text:
                discriminators.add(text)
    for claim_id in sorted(str(value) for value in claim_ids or () if value):
        claim = claims_by_id.get(claim_id)
        if not isinstance(claim, dict):
            continue
        source_ref = claim.get("source_ref") if isinstance(claim.get("source_ref"), dict) else {}
        source_id = str(source_ref.get("source_id") or "")
        if source_id in landmark_place_refs:
            refs.add(landmark_place_refs[source_id])
            discriminators.add(source_id)
        value = claim.get("temporal_value")
        if isinstance(value, dict):
            text = ident.episode_discriminator(value)
            if text:
                discriminators.add(text)
    return {
        "node_kind": str(node.get("node_kind") or ""),
        "event_kind": str(node.get("event_kind") or ""),
        "identity_refs": sorted(refs),
        "discriminators": sorted(discriminators),
    }


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

    landmark_place_refs = _landmark_place_refs(vault_root)
    candidate_identity: dict[str, dict] = {}
    candidates: list[tuple[dict, frozenset[str]]] = []
    for node in projection.nodes:
        if not isinstance(node, dict):
            continue
        claim_ids = frozenset(
            str(value) for value in node.get("input_claim_refs") or () if value
        )
        row = _candidate(node, roster_aliases=roster_aliases, rosters=rosters)
        if row is not None:
            candidate_identity[str(row["candidate_id"])] = _candidate_identity(
                node, row, claim_ids, independent_claims_by_id, landmark_place_refs,
            )
            row["grounding_identity"] = _grounding_identity(
                claim_ids, independent_claims_by_id
            )
            grounded_role = _grounded_candidate_role(
                node, claim_ids, independent_claims_by_id
            )
            if grounded_role and grounded_role != row.get("event_role"):
                row["event_role"] = grounded_role
                row["reference_keys"] = timeline_evidence.candidate_reference_keys(row)
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
            candidate_identity.setdefault(str(row["candidate_id"]), _candidate_identity(
                node, row, claim_ids, baseline_claims_by_id, landmark_place_refs,
            ))
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
        # v373: re-key remapping inputs. Neither reaches a prompt or a digest.
        "candidate_identity": candidate_identity,
        # v375: what the independent drawing publishes, so a stored link the
        # fold can neither draw nor redirect is named `link_orphaned`.
        "drawn_node_ids": frozenset(
            str(node.get("node_id") or "") for node in projection.nodes
            if isinstance(node, dict) and node.get("node_id")
        ),
        "node_aliases": {
            str(key): str(value)
            for key, value in dict(getattr(projection, "node_aliases", None) or {}).items()
            if key and value
        },
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
    candidates_by_id = {
        str(row.get("candidate_id") or ""): row for row in candidates
    }
    event_contexts: dict[str, dict] = {}
    # v375 A_RE_KEY_IS_NOT_A_CHANGE_TO_A_LIFE: per event, {current id: the id
    # the stored reading filed for the same identity}, and the digest's own
    # fingerprint keyed that way. Both are empty/equal to the prompt's own
    # fingerprint whenever no filed id vanished, so such digests are the v374
    # digests byte for byte.
    event_names: dict[str, dict] = {}
    digest_fingerprints: dict[str, str] = {}
    if existing and isinstance(existing.get("events"), list):
        for event in stored_events:
            context = timeline_evidence.build_event_context(
                _carried_link_event(event, candidates_by_id, catalog),
                candidates,
                forced_candidate_ids=forced_ids,
                max_candidates=max_candidates,
            )
            key = context["event_key"]
            event_contexts[key] = context
            names = _filed_identity_names(event, context, candidates_by_id, catalog)
            event_names[key] = names
            digest_fingerprints[key] = (
                timeline_evidence.identity_keyed_fingerprint(context, candidates_by_id, names)
                if names else context["input_fingerprint"]
            )
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
        digest_fingerprints[context["event_key"]] = context["input_fingerprint"]

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
                names = event_names.get(context["event_key"]) or {}
                digest_fingerprints[context["event_key"]] = timeline_evidence.digest({
                    "prior": digest_fingerprints[context["event_key"]],
                    "total_prompt_omitted": [names.get(value, value) for value in omitted],
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
        authority = {
            "human_identity_decisions": human_decisions,
            "source_roster_authority": _source_roster_authority(
                selected, context.get("candidate_ids"), roster_evidence
            ),
        }
        context["input_fingerprint"] = timeline_evidence.digest({
            "event_context": context["input_fingerprint"], **authority,
        })
        digest_fingerprints[context["event_key"]] = timeline_evidence.digest({
            "event_context": digest_fingerprints[context["event_key"]], **authority,
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
    def _digest_input(named: bool) -> dict:
        return {
            "schema_version": CONTEXT_SCHEMA_VERSION,
            "event_contexts": {
                key: {
                    "candidate_ids": (
                        _identity_named_ids(value.get("candidate_ids"), event_names.get(key))
                        if named else value.get("candidate_ids")
                    ),
                    "reference_keys": value.get("reference_keys"),
                    "unmatched_reference_keys": value.get("unmatched_reference_keys"),
                    "complete": value.get("complete"),
                    "remaining_candidate_count": value.get("remaining_candidate_count"),
                    "input_fingerprint": (
                        digest_fingerprints.get(key, value.get("input_fingerprint"))
                        if named else value.get("input_fingerprint")
                    ),
                }
                for key, value in sorted(event_contexts.items())
            },
            "human_identity_decisions": human_decisions,
        }

    digest_input = _digest_input(True)
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
    # v373: what `timeline_settlement` needs to remap a stored link whose node
    # id no longer exists. Excluded from context_digest and from every prompt:
    # it is how the framework avoids a model call, not what the model reads.
    snapshot[LINK_REMAP_FIELD] = _link_remap_inputs(stored_events, candidates, catalog)
    snapshot[LINK_ORPHANED_FIELD] = _orphaned_links(stored_events, candidates_by_id, catalog)
    # v375: the digest this source will have once a timeline refresh re-files
    # every event against today's ids (no filed id left to name). Equal to
    # ``context_digest`` whenever nothing was renamed.
    snapshot[REFILED_DIGEST_FIELD] = (
        _digest(_digest_input(False)) if any(event_names.values())
        else snapshot["context_digest"]
    )
    snapshot[CANDIDATE_IDENTITY_FIELD] = {
        str(row.get("candidate_id") or ""): catalog.get("candidate_identity", {}).get(
            str(row.get("candidate_id") or "")
        ) or {}
        for row in selected
    }
    return snapshot


def _link_remap_inputs(stored_events: list[dict], candidates: list[dict], catalog: dict) -> dict:
    """Per vanished stored link id: the projection's own alias and the linked
    entities' roster terms (the words the old node could have been keyed on)."""
    present = {str(row.get("candidate_id") or "") for row in candidates}
    roster_aliases = catalog.get("roster_aliases") or {}
    node_aliases = catalog.get("node_aliases") or {}
    remap: dict[str, dict] = {}
    for event in stored_events:
        relation = event.get("timeline_relation")
        if not isinstance(relation, dict):
            continue
        old = str(relation.get("candidate_id") or "")
        if not old or old in present:
            continue
        terms = remap.setdefault(old, {
            # v375: walked, so a chain of re-keys still reaches today's id.
            "alias": walk_node_alias(old, node_aliases, present) or None,
            "subject_terms": {},
        })["subject_terms"]
        for ref in relation.get("entity_refs") or ():
            ref = str(ref or "")
            if ref and not timeline_evidence.is_generic_owner_reference(ref):
                terms[ref] = sorted(set(roster_aliases.get(ref, ())))
    return remap


def walk_node_alias(node_id: object, aliases: object, present: object) -> str:
    """``node_id`` followed through ``node_aliases`` to an id in ``present``.

    The id itself when it is present; ``""`` on a cycle or when the redirects
    reach nothing present. The one walk v373's remap and v375's freshness share
    with the fold's own :func:`temporal_timeline._follow_node_alias`.
    """
    table = aliases if isinstance(aliases, dict) else {}
    current = timeline_evidence.collapsed_text(node_id)
    seen: set[str] = set()
    while current and current not in present:
        if current in seen:
            return ""
        seen.add(current)
        current = timeline_evidence.collapsed_text(table.get(current))
    return current if current in present else ""


def _identity_shape(identity: object) -> tuple:
    row = identity if isinstance(identity, dict) else {}
    return (
        str(row.get("node_kind") or ""),
        str(row.get("event_kind") or ""),
        tuple(sorted(str(ref) for ref in row.get("identity_refs") or ())),
    )


def has_identity_sibling(candidate_id: str, candidate_ids: object, identities: dict) -> bool:
    """Does another candidate share this one's kind, event kind and entities?

    Then only a discriminator tells the two apart (two stays at one house, two
    stints at one employer), and a re-key that re-orders discriminators would
    silently swap them. v375: such a candidate is never matched to a vanished
    id by recomputation, only by the projection's own redirect.
    """
    shape = _identity_shape(identities.get(candidate_id))
    return any(
        other != candidate_id and _identity_shape(identities.get(other)) == shape
        for other in (str(value) for value in candidate_ids or ())
    )


def identity_recomputes(old_id: str, identity: object, subject_terms: object) -> bool:
    """v373's proof: ``old_id`` is this identity minted on one of these words.

    ``derive_node_id(node_kind, event_kind, [word], discriminator)`` for a word
    in ``subject_terms`` and a discriminator the candidate carries (or none).
    """
    row = identity if isinstance(identity, dict) else {}
    discriminators = [None, *(row.get("discriminators") or ())]
    return any(
        temporal_projection.derive_node_id(
            node_kind=row.get("node_kind"),
            event_kind=row.get("event_kind"),
            subject_refs=[term],
            discriminator=discriminator,
        ) == old_id
        for term in subject_terms or ()
        for discriminator in discriminators
    )


def _own_subject_terms(identity: object, roster_aliases: dict) -> list[str]:
    """The words a candidate's own entities are known by (refs and aliases)."""
    row = identity if isinstance(identity, dict) else {}
    terms: list[str] = []
    for ref in row.get("identity_refs") or ():
        ref = str(ref or "")
        if ref and not timeline_evidence.is_generic_owner_reference(ref):
            terms.extend([ref, *roster_aliases.get(ref, ())])
    return terms


def _proven_successor(
    old_id: str, pool: list[str], catalog: dict, *, siblings_among: object = None,
) -> str:
    """The one candidate in ``pool`` provably the vanished ``old_id`` (v375).

    The projection's own redirect first; otherwise v373's recomputation, which
    must match exactly one candidate that has no identity sibling among
    ``siblings_among`` (default: the pool).
    """
    target = walk_node_alias(old_id, catalog.get("node_aliases") or {}, set(pool))
    if target:
        return target
    identities = catalog.get("candidate_identity") or {}
    roster_aliases = catalog.get("roster_aliases") or {}
    matches = [
        candidate_id for candidate_id in pool
        if identity_recomputes(
            old_id,
            identities.get(candidate_id),
            _own_subject_terms(identities.get(candidate_id), roster_aliases),
        )
    ]
    siblings = pool if siblings_among is None else siblings_among
    if len(matches) != 1 or has_identity_sibling(matches[0], siblings, identities):
        return ""
    return matches[0]


def _filed_ids(event: dict) -> set[str]:
    resolution = event.get("timeline_resolution")
    relation = event.get("timeline_relation")
    filed = {
        str(value) for value in (
            (resolution.get("candidate_ids") or ()) if isinstance(resolution, dict) else ()
        ) if value
    }
    if isinstance(relation, dict) and relation.get("candidate_id"):
        filed.add(str(relation["candidate_id"]))
    return filed


def _carried_link_event(event: dict, candidates_by_id: dict, catalog: dict) -> dict:
    """The stored event as context retrieval should read it (v375).

    A stored link forces its node into the event's candidate set. When that
    node's id was re-keyed, the node it provably became is forced instead, so
    a re-key cannot shrink the context it was filed against.
    """
    relation = event.get("timeline_relation")
    old = str(relation.get("candidate_id") or "") if isinstance(relation, dict) else ""
    if not old or old in candidates_by_id:
        return event
    target = _proven_successor(old, sorted(candidates_by_id), catalog)
    if not target:
        return event
    carried = dict(event)
    carried["timeline_relation"] = {**relation, "candidate_id": target}
    return carried


def _filed_identity_names(
    event: dict, context: dict, candidates_by_id: dict, catalog: dict,
) -> dict[str, str]:
    """``{current candidate id: filed id}`` for :data:`A_RE_KEY_IS_NOT_A_CHANGE_TO_A_LIFE`.

    Only a filed id that vanished from the catalog is ever a name, and only
    for a current candidate the stored reading did not file; the pairing must
    be one-to-one or nothing is renamed.
    """
    filed = _filed_ids(event)
    vanished = sorted(value for value in filed if value not in candidates_by_id)
    if not vanished:
        return {}
    context_ids = [str(value) for value in context.get("candidate_ids") or ()]
    unfiled = [value for value in context_ids if value not in filed]
    if not unfiled:
        return {}
    claimed: dict[str, list[str]] = {}
    for old in vanished:
        target = _proven_successor(old, unfiled, catalog, siblings_among=context_ids)
        if target:
            claimed.setdefault(target, []).append(old)
    return {target: olds[0] for target, olds in claimed.items() if len(olds) == 1}


def _identity_named_ids(candidate_ids: object, names: object) -> object:
    """The digest's ``candidate_ids``: unchanged unless a name applies."""
    if not names:
        return candidate_ids
    return sorted(names.get(str(value), str(value)) for value in candidate_ids or ())


def _orphaned_links(stored_events: list[dict], candidates_by_id: dict, catalog: dict) -> list[dict]:
    """Stored links the drawing neither draws nor redirects (``link_orphaned``)."""
    drawn = catalog.get("drawn_node_ids")
    drawn = set(drawn) if drawn is not None else set(candidates_by_id)
    drawn.update(candidates_by_id)
    aliases = catalog.get("node_aliases") or {}
    orphaned: list[dict] = []
    for event in stored_events:
        relation = event.get("timeline_relation")
        if not isinstance(relation, dict):
            continue
        old = str(relation.get("candidate_id") or "")
        if not old or old in drawn or walk_node_alias(old, aliases, drawn):
            continue
        orphaned.append({
            "event_key": timeline_evidence.event_key(event),
            "candidate_id": old,
        })
    return sorted(orphaned, key=lambda row: (row["event_key"], row["candidate_id"]))


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


def snapshot_metadata_after_timeline_refile(snapshot: dict) -> dict:
    """Four-key identity a timeline refresh stamps on the reading it files.

    v375: a timeline refresh re-files every stored event against today's
    candidate ids, so the filed ids that named re-keyed candidates in this
    snapshot's ``context_digest`` are gone from the new reading. Its stamp is
    the digest that reading will be judged by.
    """
    accepted = dict(snapshot)
    refiled = snapshot.get(REFILED_DIGEST_FIELD)
    if refiled:
        accepted["context_digest"] = refiled
    return snapshot_metadata(accepted)


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


def candidate_identity_is_resolved(candidate: dict) -> bool:
    """The whole candidate must have no unresolved or ambiguous identity flags."""
    return not (
        candidate.get("unresolved_entity_mentions")
        or candidate.get("entity_ref_ambiguities")
    )


#: Per-event failures that, under ``salvage``, downgrade the one event to the
#: conservative state the prompt itself asks for (null grounding, or a null
#: relation with an abstaining resolution) instead of refusing the whole
#: response. A ``timeline_resolution`` that fails its own contract is salvaged
#: the same way in ``validate_response`` (v326, ``_salvaged_resolution``).
#: Structural failures never salvage: they mean the response is not an answer
#: to this snapshot at all.
SALVAGE_RELATION_CODES = {
    ContextFailureCode.RELATION_INVALID: "missing_evidence",
    ContextFailureCode.CANDIDATE_UNKNOWN: "missing_evidence",
    ContextFailureCode.CONTEXT_INCOMPLETE: "incomplete",
    ContextFailureCode.CANDIDATE_AMBIGUOUS: "ambiguous",
    ContextFailureCode.EVIDENCE_NOT_MAPPING: "missing_evidence",
    ContextFailureCode.QUOTE_MISSING: "missing_evidence",
    ContextFailureCode.QUOTE_NOT_FOUND: "missing_evidence",
    ContextFailureCode.QUOTE_NOT_EXACT: "missing_evidence",
    ContextFailureCode.QUOTE_AMBIGUOUS: "missing_evidence",
    ContextFailureCode.ENTITY_REFS_INVALID: "missing_evidence",
    ContextFailureCode.CANDIDATE_NOT_DISAMBIGUATED: "ambiguous",
    ContextFailureCode.RELATION_SHAPE_INVALID: "missing_evidence",
}


def _validate_relation(
    relation: object, *, candidates: dict, context: dict, story_text: str,
) -> dict | None:
    """The selected candidate for a valid relation; raises the typed failure."""
    if relation is None:
        return None
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
    if not candidate_identity_is_resolved(candidate):
        raise ClassifierContextError(
            "timeline relation candidate identity is unresolved or ambiguous",
            code=ContextFailureCode.CANDIDATE_AMBIGUOUS,
        )
    if (relation.get("relation") == "within"
            and candidate.get("temporal_shape") == "point"):
        raise ClassifierContextError(
            "within needs an interval candidate; this candidate is a point occurrence",
            code=ContextFailureCode.RELATION_SHAPE_INVALID,
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
    evidence["start"] = start
    evidence["end"] = end
    return candidate


def _abstaining_resolution(raw: object, *, status: str, candidate_ids: list[str], code: str) -> dict:
    """The resolution an event keeps once its relation was downgraded.

    ``code`` is the operational label the note carries: a
    ``ContextFailureCode`` value for a relation downgrade, or the
    ``timeline_evidence`` code for a resolution the validator rebuilt.
    """
    reason = ""
    if isinstance(raw, dict) and isinstance(raw.get("reason"), str):
        reason = raw["reason"].strip()
    note = f"[validator downgrade: {code}]"
    limit = timeline_evidence.MAX_RESOLUTION_REASON_CHARS - len(note) - 1
    reason = (reason[:limit].rstrip() + " " + note).strip() if limit > 0 else note[:timeline_evidence.MAX_RESOLUTION_REASON_CHARS]
    return {"status": status, "candidate_ids": list(candidate_ids), "reason": reason}


def _salvaged_resolution(
    raw: object, *, relation: object, candidate_ids: list[str], complete: bool, code: str,
) -> dict:
    """The bookkeeping an event keeps when its own ``timeline_resolution`` failed.

    The resolution is the model's account of the link decision, not the
    event: a status that contradicts the context's coverage, an echoed
    candidate list the validator recomputes anyway, a reason past its length,
    a stray key. None of that is evidence about the moment, so under salvage
    the validator rebuilds the account from what it verified itself. A
    relation that already passed ``_validate_relation`` is kept and reported
    as ``linked``; otherwise the model's own non-link status stands when it
    agrees with coverage, and the coverage rule decides when it does not
    (``incomplete`` for a truncated context, ``missing_evidence`` for a
    complete one). Nothing here resolves a place or invents a candidate: the
    event's ``places`` stay the words the source used.
    """
    if relation is not None:
        status = "linked"
    else:
        status = "incomplete" if not complete else "missing_evidence"
        echoed = ""
        if isinstance(raw, dict):
            echoed = timeline_evidence.collapsed_text(raw.get("status"))
        if (echoed in timeline_evidence.RESOLUTION_STATUSES
                and echoed != "linked"
                and (echoed == "incomplete") == (not complete)):
            status = echoed
    return _abstaining_resolution(raw, status=status, candidate_ids=candidate_ids, code=code)


def validate_response(
    result: object,
    snapshot: dict,
    story_text: str,
    *,
    mode: str = "full",
    existing_events: object = None,
    require_event_contract: bool = False,
    salvage: bool = False,
    downgrades: list | None = None,
) -> dict:
    """Validate one model response against exactly the context it observed.

    With ``salvage`` a per-event evidence failure downgrades that one event to
    the conservative state the prompt asks the model for (a null grounding, or
    a null relation with an abstaining resolution over the supplied candidate
    set) and is recorded in ``downgrades`` as ``{event_key, field, code}``.
    Structural failures and snapshot mismatches still refuse the response.
    """
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
        raw_resolution = event.get("timeline_resolution")
        if (mode == "timeline" and isinstance(raw_resolution, dict)
                and "candidate_ids" not in raw_resolution):
            # v374: the timeline prompt no longer asks the model to echo the
            # event-local set; the framework fills it from the same context
            # it validates against, so the stored resolution is unchanged.
            raw_resolution = {**raw_resolution, "candidate_ids": list(candidate_ids)}
        try:
            _validate_relation(
                relation, candidates=candidates, context=context, story_text=story_text,
            )
        except ClassifierContextError as exc:
            if not salvage or exc.code not in SALVAGE_RELATION_CODES:
                raise
            status = SALVAGE_RELATION_CODES[exc.code]
            if status == "incomplete" and context.get("complete"):
                status = "missing_evidence"
            if status != "incomplete" and not context.get("complete"):
                status = "incomplete"
            relation = None
            event["timeline_relation"] = None
            raw_resolution = _abstaining_resolution(
                raw_resolution, status=status, candidate_ids=candidate_ids, code=exc.code.value,
            )
            if downgrades is not None:
                downgrades.append({"event_key": key, "field": "timeline_relation", "code": exc.code.value})

        grounding_input = event.get("source_grounding")
        if salvage and grounding_input is not None:
            try:
                timeline_evidence.normalize_source_grounding(
                    grounding_input,
                    base,
                    story_text=story_text,
                    source_revision=str(snapshot.get("source_revision") or ""),
                    grounding_allowed=bool(snapshot.get("grounding_allowed", True)),
                )
            except timeline_evidence.TimelineEvidenceError as exc:
                if not exc.code.startswith("grounding_"):
                    raise ClassifierContextError(str(exc), code=ContextFailureCode.RESOLUTION_INVALID) from None
                grounding_input = None
                if downgrades is not None:
                    downgrades.append({"event_key": key, "field": "source_grounding", "code": exc.code})
        if (salvage and isinstance(raw_resolution, dict)
                and isinstance(raw_resolution.get("candidate_ids"), list)
                and sorted(map(str, raw_resolution["candidate_ids"])) != sorted(candidate_ids)):
            # The echoed list is bookkeeping the validator recomputes: a link is
            # checked against the supplied set above, and an abstention over a
            # partial or stale echo asserts nothing about the rest. The supplied
            # set is the honest list either way.
            raw_resolution = {**raw_resolution, "candidate_ids": list(candidate_ids)}
            if downgrades is not None:
                downgrades.append({"event_key": key, "field": "timeline_resolution", "code": "resolution_candidates_completed"})

        try:
            grounding = timeline_evidence.normalize_source_grounding(
                grounding_input,
                base,
                story_text=story_text,
                source_revision=str(snapshot.get("source_revision") or ""),
                grounding_allowed=bool(snapshot.get("grounding_allowed", True)),
            )
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
            if not (salvage and exc.code.startswith("resolution_")):
                code = (
                    ContextFailureCode.GROUNDING_INVALID
                    if exc.code.startswith("grounding_") else ContextFailureCode.RESOLUTION_INVALID
                )
                raise ClassifierContextError(str(exc), code=code) from None
            # v326: a resolution that fails its own contract is bookkeeping
            # about the link, not the event. Rebuild it from what was verified
            # and file the event; the place words and stated date are kept
            # as the source gave them (owner's pasted vital records,
            # 2026-09-22: three readings refused in a row, no event filed).
            raw_resolution = _salvaged_resolution(
                raw_resolution,
                relation=relation,
                candidate_ids=candidate_ids,
                complete=bool(context.get("complete")),
                code=exc.code,
            )
            try:
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
            except timeline_evidence.TimelineEvidenceError as again:
                raise ClassifierContextError(
                    str(again), code=ContextFailureCode.RESOLUTION_INVALID,
                ) from None
            if downgrades is not None:
                downgrades.append({"event_key": key, "field": "timeline_resolution", "code": exc.code})
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
    if snapshot.get(LINK_ORPHANED_FIELD):
        # v375: a stored link naming a node the drawing neither draws nor
        # redirects. Visible and refreshable, never a silent unresolved anchor.
        return LINK_ORPHANED
    if recorded["prompt_version"] != current["prompt_version"]:
        return "relationship_changed"
    if recorded["context_digest"] != current["context_digest"]:
        return "context_changed"
    return None


#: The order a bounded refresh drains its backlog in: what a person just
#: told or corrected first, the classifier's own upgrades next, the ambient
#: context last. `stale` is a filed correction; `unclassified` and
#: `source_changed` are new words; `legacy_snapshot` / `classifier_changed`
#: are our own rule moves; `link_orphaned` (v375) is a stored link whose node
#: the drawing neither draws nor redirects; `relationship_changed` /
#: `context_changed` are the spine moving under an unchanged story.
REFRESH_REASON_PRIORITY: dict[str, int] = {
    "stale": 0,
    "unclassified": 1,
    "source_changed": 1,
    "legacy_snapshot": 2,
    "classifier_changed": 3,
    # v375: a link to a node nothing draws or redirects is a known defect in a
    # stored reading, ahead of the ambient context moving.
    LINK_ORPHANED: 4,
    "relationship_changed": 5,
    "context_changed": 6,
}


def unfinished_search_blocks_a_moment(classification: object) -> bool:
    """Does this source hold a moment the classifier never finished placing?

    v333. The classifier's bounded candidate search can run out before it has
    read all the relevant evidence; the event is filed `incomplete` and the
    status only clears when the refresh sweep reaches the source again. When
    the event ALSO says nothing datable of its own — `classifier_claims`'
    fourth rung, an ``occurrence`` reading: it happened, when is not known —
    that unfinished search is the only thing standing between the moment and a
    place on the timeline. Reuses the one reading definition rather than
    re-parsing the date block here.
    """
    import classifier_claims  # noqa: PLC0415 - avoids an import cycle at module load

    row = classification if isinstance(classification, dict) else {}
    for event in row.get("events") or ():
        if not isinstance(event, dict):
            continue
        resolution = event.get("timeline_resolution")
        status = (resolution or {}).get("status") if isinstance(resolution, dict) else None
        if timeline_evidence.collapsed_text(status) != "incomplete":
            continue
        reading = classifier_claims.temporal_reading(event)
        if timeline_evidence.collapsed_text(reading.get("claim_type")) == temporal_claims.OCCURRENCE_CLAIM_TYPE:
            return True
    return False


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
            "settle_counts": {"rule": 0, "model": 0},
        }

    records = _classification_records(root) if classifications is None else classifications
    catalog = _load_context_catalog(root)
    pending: list[dict] = []
    blocked: set[str] = set()
    for source in sources:
        relative = _relative_source(root, source)
        snapshot = _build_context_snapshot_from_catalog(root, source, catalog)
        record = records.get(relative)
        reason = refresh_reason(snapshot, record)
        if reason:
            pending.append({
                "source_path": relative,
                "reason": reason,
                "snapshot": snapshot_metadata(snapshot),
                # v373: still pending, but "rule" needs no model call — the
                # count a host budgets model calls by.
                "settle": _settle(source, snapshot, record, reason),
            })
            if unfinished_search_blocks_a_moment(record):
                blocked.add(relative)
    # Unfinished searches first (v333), then newest information (issue
    # lifehug#371). A story the person just told or corrected outranks a
    # backlog of context refreshes: without that a vault with hundreds of
    # `context_changed` rows starved a just-edited answer behind them for a
    # week. Ahead of BOTH sits the source holding a moment nothing but this
    # sweep can place — a search that ran out, on an event with no date of its
    # own. That set is small and self-draining (once refreshed the source
    # leaves the backlog), so it cannot starve the rest; leaving it at the back
    # of ~350 pending rows behind a 50-a-run cap is what left the owner looking
    # at a moment neither he nor the sweep could settle. Within one rank, path
    # order keeps the selection a pure function of the vault.
    pending.sort(key=lambda row: (0 if row["source_path"] in blocked else 1,
                                  REFRESH_REASON_PRIORITY.get(row["reason"], len(REFRESH_REASON_PRIORITY)),
                                  row["source_path"]))
    targets = pending[:cap]
    return {
        "targets": targets,
        "selected_count": len(targets),
        "pending_count": len(pending),
        "remaining_count": max(0, len(pending) - len(targets)),
        "complete": len(pending) <= len(targets),
        "limit": cap,
        "settle_counts": {
            value: sum(1 for row in pending if row["settle"] == value)
            for value in ("rule", "model")
        },
    }


def _settle(source: Path, snapshot: dict, record: object, reason: str) -> str:
    """``timeline_settlement.settle_mode`` for one pending report row."""
    import timeline_settlement  # noqa: PLC0415 - it imports this module

    if reason not in timeline_settlement.TIMELINE_REFRESH_REASONS:
        return timeline_settlement.SETTLE_MODEL
    try:
        import classify_story  # noqa: PLC0415 - the one story-text reader

        _fm, story_text = classify_story.load_source_text(source)
    except Exception:  # noqa: BLE001 - the model reads what we cannot
        return timeline_settlement.SETTLE_MODEL
    return timeline_settlement.settle_mode(snapshot, record, story_text, reason=reason)

# ---------------------------------------------------------------------------
# v387 — the classifier knows the people (identity design §4.1.3, P3)
# ---------------------------------------------------------------------------
#
# Before v387 the classifier prompt carried NO person-roster block: roster
# terms reached it only attached to timeline candidates ("retrieval, never
# binding"), so a full name it had never been shown was a stranger, and the
# person it calls "the author's father" was recommended as a new Focus. The
# block below is the people the vault already holds; the post-processor after
# it rewrites a classifier name to the roster's own name when — and only when —
# person resolution says ``resolved``.
#
# Neither is part of the context SNAPSHOT: the snapshot's digest decides when a
# classification is stale, and putting the roster into it would make every
# alias added anywhere re-classify every source. The block is retrieval for
# the model; the post-processor is deterministic and re-runnable.

#: How many people the block lists. The recorder's known-entries block caps
#: at 21 lines because its whole prompt is a few hundred haiku-class tokens;
#: the classifier is one sonnet-class call of ~17k tokens (the E-C3 backfill's
#: measured mean), so 30 lines of ~70 characters (~500 tokens, ~3%) buys the
#: whole of a typical family plus the people this story actually names. The
#: ORDER is what makes the cap safe: people the story names first, then
#: family, then everyone else, so what is cut is never someone the story is
#: about.
KNOWN_PEOPLE_LIMIT = 30

#: The additive field on a classification record that says what the
#: post-processor did to each person name: ``resolved`` (rewritten to the
#: roster's name when it differed), ``ambiguous`` or ``unknown`` (left as the
#: classifier wrote it).
IDENTITY_RESOLUTION_FIELD = "identity_resolution"

_PERSON_FOCUS_TYPES = frozenset({"", "person"})


def render_known_people(person_roster: object, *, story_text: str = "",
                        limit: int = KNOWN_PEOPLE_LIMIT) -> str:
    """The "People you already know" block — `person_resolution
    .render_known_people`, the ONE renderer the classifier and the general
    listener share, at the classifier's cap (:data:`KNOWN_PEOPLE_LIMIT`)."""
    import person_resolution as pr  # noqa: PLC0415

    return pr.render_known_people(person_roster, story_text=story_text,
                                  limit=limit)


def resolve_classification_people(classification: dict,
                                  person_roster: object) -> dict:
    """Rewrite ``people[].name`` / person ``focus_opportunities[].entity`` to
    the roster's own name when person resolution is ``resolved``.

    ``ambiguous`` and ``unknown`` leave the classifier's words untouched. What
    was done to each name is recorded on :data:`IDENTITY_RESOLUTION_FIELD`
    (additive; omitted when the roster holds no person at all, so a vault with
    no roster keeps its classification bytes). Mutates and returns
    ``classification``.
    """
    import person_resolution as pr  # noqa: PLC0415

    rows = pr.person_rows(person_roster)
    if not isinstance(classification, dict) or not rows:
        return classification
    names = {pr.ref_of(entity): str(entity.get("name") or "").strip()
             for entity in rows}
    notes: list[dict] = []

    def visit(field_name: str, key: str, item: dict, index: int,
              relationship: object = None) -> None:
        mention = str(item.get(key) or "").strip()
        if not mention:
            return
        context = {"relationship": relationship} if relationship else None
        found = pr.resolve_person(mention, person_roster, context=context)
        note: dict = {"field": field_name, "index": index,
                      "mention": mention, "kind": found.kind}
        # v388: the first-name rung alone never rewrites a name — the block
        # promises "never match a stranger to a listed person because a first
        # name is shared".
        if found.resolved and found.reason != "first_name" and names.get(found.ref):
            note["ref"] = found.ref
            note["name"] = names[found.ref]
            note["rewritten"] = names[found.ref] != mention
            item[key] = names[found.ref]
        elif found.candidates:
            note["candidates"] = list(found.candidates)
        notes.append(note)

    for index, person in enumerate(classification.get("people") or ()):
        if isinstance(person, dict):
            visit("people", "name", person, index,
                  relationship=person.get("relationship"))
    for index, focus in enumerate(classification.get("focus_opportunities") or ()):
        if isinstance(focus, dict) and normalized_mention_key(
                focus.get("type")) in _PERSON_FOCUS_TYPES:
            visit("focus_opportunities", "entity", focus, index)
    classification[IDENTITY_RESOLUTION_FIELD] = notes
    return classification


__all__ = [
    "ClassifierContextError",
    "ContextFailureCode",
    "CONTEXT_SCHEMA_VERSION",
    "EXTRACTOR_VERSION",
    "IDENTITY_RESOLUTION_FIELD",
    "KNOWN_PEOPLE_LIMIT",
    "A_RE_KEY_IS_NOT_A_CHANGE_TO_A_LIFE",
    "LINK_ORPHANED",
    "LINK_ORPHANED_FIELD",
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
    "render_known_people",
    "resolve_classification_people",
    "select_refresh_targets",
    "snapshot_metadata",
    "source_revision",
    "unfinished_search_blocks_a_moment",
    "validate_response",
]
