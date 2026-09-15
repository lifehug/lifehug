#!/usr/bin/env python3
"""Bounded contextual timeline input and freshness for story classification.

The classifier may relate an event only to candidates supplied here. Freshness
is semantic: source bytes, prompt/extractor versions, and a stable digest of
the supplied timeline context. Projection generations and timestamps are never
inputs, and nodes touched by this source's own classifier claims are excluded
so a reread cannot invalidate itself.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

import chronology as chrono
import entity_roster
import event_identity
import identity_resolution
import temporal_placement as placement
import temporal_projection
import temporal_store
from temporal_claims import normalized_mention_key
from vault_paths import vault_data_path

CONTEXT_SCHEMA_VERSION = 1
PROMPT_VERSION = "contextual-timeline:1"
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


class ClassifierContextError(ValueError):
    """A response was not grounded in the source/context snapshot it echoes."""


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


def snapshot_metadata(snapshot: object) -> dict:
    """The minimal manifest/response echo: no candidate payload or generation."""
    row = snapshot if isinstance(snapshot, dict) else {}
    return {key: str(row.get(key) or "") for key in SNAPSHOT_KEYS}


def _relative_source(vault_root: Path, source_path: Path) -> str:
    try:
        return source_path.resolve().relative_to(vault_root.resolve()).as_posix()
    except ValueError:
        return str(source_path)


def _claim_context(vault_root: Path, source_path: Path) -> tuple[set[str], set[str], dict[str, bool]]:
    """Own classifier ids, grounded entity refs, and classifier provenance."""
    try:
        payload = temporal_store.read_active_index(vault_root) or {}
    except (OSError, ValueError):
        payload = {}
    relative = _relative_source(vault_root, source_path)
    own: set[str] = set()
    refs: set[str] = set()
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
        if source_id.startswith("classification:") and source_path_value == relative:
            if claim_id:
                own.add(claim_id)
        if source_path_value != relative or is_classifier:
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
    return own, refs, classifier_claim


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
    if node_kind == "event" and event_kind not in LANDMARK_EVENT_KINDS:
        return None
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
    alternatives = [
        value for value in (_bounds(row) for row in node.get("alternate_values") or ())
        if value is not None
    ]
    return {
        "candidate_id": candidate_id,
        "node_kind": node_kind,
        "episode_id": node.get("episode_id"),
        "kind": node.get("event_kind") or node.get("node_kind"),
        "name": node.get("label") or node.get("event_kind") or candidate_id,
        "aliases": sorted(aliases),
        "entity_refs": entity_refs,
        "unresolved_entity_mentions": unresolved_mentions,
        "entity_ref_ambiguities": entity_ref_ambiguities,
        "supported_bounds": _bounds(usable),
        "basis": node.get("basis"),
        "conflict_state": node.get("conflict_state", "none"),
        "alternatives": alternatives,
    }


def _human_identity_records(vault_root: Path) -> list[dict]:
    """Validated human identity decisions, with operational metadata removed."""
    rows: list[dict] = []
    for value in event_identity.load_event_identities(vault_root):
        if value.get("origin") not in event_identity.HUMAN_ORIGINS:
            continue
        rows.append({
            key: value.get(key)
            for key in (
                "identity_id", "telling_ref", "episode_id", "relation",
                "origin", "supersedes", "telling_aliases",
            )
        })
    for value in event_identity.load_episode_operations(vault_root):
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


def _applicable_human_identity_records(
    vault_root: Path,
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
    for row in _human_identity_records(vault_root):
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


def _roster_context(
    vault_root: Path,
    story_text: str,
) -> tuple[
    dict[str, tuple[str, ...]],
    set[str],
    dict[str, identity_resolution.RosterIndex],
]:
    """Canonical roster aliases and exact-phrase refs used only for retrieval."""
    aliases: dict[str, tuple[str, ...]] = {}
    mentioned: set[str] = set()
    rosters: dict[str, identity_resolution.RosterIndex] = {}
    lowered = story_text.casefold()
    for kind in ("person", "place", "period"):
        roster = entity_roster.load_roster(kind, vault_root=vault_root)
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
            for term in terms:
                # Exact roster phrase retrieval is not a binding: the model must
                # still return an allowlisted candidate/ref pair and evidence.
                pattern = rf"(?<!\w){re.escape(term.casefold())}(?!\w)"
                if re.search(pattern, lowered):
                    mentioned.add(ref)
    return aliases, mentioned, rosters


def _locate_unique_exact_quote(story_text: str, quote: str) -> tuple[int, int]:
    """Locate one exact quote through the canonical locator, refusing repeats."""
    import landmark_offer  # noqa: PLC0415 - avoids the timeline import cycle

    located = landmark_offer.locate(story_text, quote)
    if located is None:
        raise ClassifierContextError("timeline relation evidence is not a source quote")
    start = located["offset"]
    end = start + len(quote)
    if story_text[start:end] != quote:
        # The shared locator also supports whitespace-normalized readings. This
        # classifier contract deliberately accepts only byte-faithful text.
        raise ClassifierContextError("timeline relation evidence is not an exact source quote")
    if story_text.find(quote, end) >= 0:
        raise ClassifierContextError("timeline relation evidence quote is ambiguous")
    return start, end


def _freshness_candidate(row: dict) -> dict:
    """Stable context semantics, excluding labels and machine telling aliases."""
    return {
        key: row.get(key)
        for key in (
            "candidate_id", "episode_id", "kind", "entity_refs",
            "unresolved_entity_mentions", "entity_ref_ambiguities",
            "supported_bounds", "basis", "conflict_state", "alternatives",
        )
    }


def _prior_identities(vault_root: Path, source_path: Path) -> list[dict]:
    try:
        manifest = event_identity.read_telling_manifest(vault_root) or {}
    except (OSError, ValueError):
        manifest = {}
    relative = _relative_source(vault_root, source_path)
    rows: list[dict] = []
    for row in manifest.get("tellings") or () if isinstance(manifest, dict) else ():
        if not isinstance(row, dict) or str(row.get("source_path") or "") != relative:
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


def build_context_snapshot(
    vault_root: str | Path,
    source_path: str | Path,
    *,
    source_bytes: bytes | None = None,
    max_candidates: int = MAX_CONTEXT_CANDIDATES,
) -> dict:
    """Build the bounded prompt context and stable freshness snapshot."""
    import temporal_publication  # noqa: PLC0415 - avoids the timeline import cycle

    root = Path(vault_root)
    source = Path(source_path)
    try:
        projection = temporal_publication.read_projection(root) or {}
    except (OSError, ValueError):
        projection = {}
    raw = source.read_bytes() if source_bytes is None else source_bytes
    story_text = raw.decode("utf-8", errors="replace")
    roster_aliases, roster_refs, rosters = _roster_context(root, story_text)
    own_claims, grounded_refs, classifier_claims = _claim_context(root, source)
    grounded_refs |= roster_refs
    prior_identities = _prior_identities(root, source)
    identities = {
        str(row.get("identity_id") or ""): row
        for row in event_identity.load_event_identities(root)
        if isinstance(row, dict)
    }
    bound_episode_ids = {
        str(identities[identity_id].get("episode_id") or "")
        for telling in prior_identities
        for identity_id in telling.get("bound_identity_ids") or ()
        if identity_id in identities and identities[identity_id].get("episode_id")
    }
    candidates: list[dict] = []
    for node in projection.get("nodes") or () if isinstance(projection, dict) else ():
        if not isinstance(node, dict):
            continue
        claim_ids = {str(value) for value in node.get("input_claim_refs") or () if value}
        if own_claims.intersection(claim_ids):
            continue
        # Pure classifier readings are not landmark context. They are exactly
        # the output-derived noise that could make two sources refresh each
        # other forever; independently grounded nodes and mixed-support episodes
        # remain eligible.
        if claim_ids and all(classifier_claims.get(claim_id, False) for claim_id in claim_ids):
            continue
        row = _candidate(node, roster_aliases=roster_aliases, rosters=rosters)
        if row is not None:
            candidates.append(row)
    candidates.sort(key=lambda row: (
        0 if row.get("node_kind") == "episode" else 1,
        str(row.get("kind") or ""),
        str(row.get("candidate_id") or ""),
    ))
    cap = max(0, min(int(max_candidates), MAX_CONTEXT_CANDIDATES))
    relevant = [
        row for row in candidates
        if set(row.get("entity_refs") or ()).intersection(grounded_refs)
        or row.get("candidate_id") in bound_episode_ids
        or row.get("episode_id") in bound_episode_ids
    ]
    competitor_refs = {
        ref
        for row in relevant
        if row.get("node_kind") == "episode"
        for ref in row.get("entity_refs") or ()
        if ref in grounded_refs
    }
    if competitor_refs:
        relevant.extend(
            row for row in candidates
            if row.get("node_kind") == "episode"
            and set(row.get("entity_refs") or ()).intersection(competitor_refs)
        )
    by_id = {row["candidate_id"]: row for row in relevant}
    relevant = [by_id[key] for key in sorted(by_id)]
    birth = [row for row in candidates if row.get("kind") == "birth"]
    required = list(relevant)
    for row in birth:
        if row["candidate_id"] not in by_id:
            required.append(row)
    if relevant:
        selected = required[:cap]
        truncated = len(required) > len(selected)
    else:
        selected = candidates[:cap]
        truncated = len(candidates) > len(selected)
    human_decisions_all = _applicable_human_identity_records(
        root, candidates=selected, prior_identities=prior_identities
    )
    human_decisions = human_decisions_all[:MAX_CONTEXT_DECISIONS]
    decision_truncated = len(human_decisions_all) > len(human_decisions)
    context_truncated = truncated or decision_truncated
    for row in selected:
        row["candidate_set_complete"] = not context_truncated
    digest_input = {
        "schema_version": CONTEXT_SCHEMA_VERSION,
        "candidates": [_freshness_candidate(row) for row in selected],
        "context_truncated": context_truncated,
        "human_identity_decisions": human_decisions,
    }
    snapshot = {
        "schema_version": CONTEXT_SCHEMA_VERSION,
        "source_revision": source_revision(source, source_bytes=raw),
        "context_digest": _digest(digest_input),
        "prompt_version": PROMPT_VERSION,
        "extractor_version": EXTRACTOR_VERSION,
        "context_complete": not context_truncated,
        "context_truncated": context_truncated,
        "candidate_count": len(selected),
        "remaining_candidate_count": max(
            0, (len(required) if relevant else len(candidates)) - len(selected)
        ),
        "catalog_omitted_count": max(0, len(candidates) - len(selected)),
        "decision_count": len(human_decisions),
        "remaining_decision_count": max(0, len(human_decisions_all) - len(human_decisions)),
        "candidates": selected,
        "human_identity_decisions": human_decisions,
        # Useful to the prompt but excluded from context_digest: classifier
        # rereads may rekey these identities and must not trigger themselves.
        "prior_event_identities": prior_identities,
    }
    return snapshot


def validate_response(result: object, snapshot: dict, story_text: str) -> dict:
    """Validate one model response against exactly the context it observed."""
    if not isinstance(result, dict):
        raise ClassifierContextError("classification response must be a mapping")
    expected = snapshot_metadata(snapshot)
    echoed = snapshot_metadata(result.get("_classification_snapshot"))
    if not all(echoed.values()) or echoed != expected:
        raise ClassifierContextError("classification snapshot is missing or stale")
    candidates = {
        str(row.get("candidate_id")): row
        for row in snapshot.get("candidates") or ()
        if isinstance(row, dict) and row.get("candidate_id")
    }
    events = result.get("events", [])
    if not isinstance(events, list):
        raise ClassifierContextError("events must be a list")
    for event in events:
        if not isinstance(event, dict):
            raise ClassifierContextError("each event must be a mapping")
        relation = event.get("timeline_relation")
        if relation is None:
            continue
        if not isinstance(relation, dict) or relation.get("relation") not in RELATIONS:
            raise ClassifierContextError("timeline relation must be within, before, or after")
        candidate_id = str(relation.get("candidate_id") or "")
        candidate = candidates.get(candidate_id)
        if candidate is None:
            raise ClassifierContextError("timeline relation references an unknown candidate id")
        if snapshot.get("context_truncated") or not candidate.get("candidate_set_complete"):
            raise ClassifierContextError("timeline relation candidate set is incomplete")
        if (candidate.get("unresolved_entity_mentions")
                or candidate.get("entity_ref_ambiguities")):
            raise ClassifierContextError(
                "timeline relation candidate identity is unresolved or ambiguous"
            )
        evidence = relation.get("evidence")
        if not isinstance(evidence, dict):
            raise ClassifierContextError("timeline relation requires source evidence")
        quote = evidence.get("quote")
        if not isinstance(quote, str) or not quote:
            raise ClassifierContextError("timeline relation evidence quote is required")
        start, end = _locate_unique_exact_quote(story_text, quote)
        evidence["start"] = start
        evidence["end"] = end
        refs = relation.get("entity_refs")
        allowed = set(candidate.get("entity_refs") or ())
        if not isinstance(refs, list) or not refs or any(str(ref) not in allowed for ref in refs):
            raise ClassifierContextError("timeline relation entity refs are not allowlisted")
        ref_counts = {
            str(ref): sum(
                str(ref) in set(row.get("entity_refs") or ())
                for row in candidates.values()
            )
            for ref in refs
        }
        if not any(count == 1 for count in ref_counts.values()):
            raise ClassifierContextError("timeline relation does not disambiguate competing candidates")
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
    if recorded["prompt_version"] != current["prompt_version"] or recorded["extractor_version"] != current["extractor_version"]:
        return "classifier_changed"
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
    records = _classification_records(root) if classifications is None else classifications
    pending: list[dict] = []
    for value in source_paths if isinstance(source_paths, (list, tuple, set)) else ():
        source = Path(value)
        if not source.is_absolute():
            source = root / source
        if not source.exists() or not source.is_file():
            continue
        relative = _relative_source(root, source)
        snapshot = build_context_snapshot(root, source)
        reason = refresh_reason(snapshot, records.get(relative))
        if reason:
            pending.append({"source_path": relative, "reason": reason, "snapshot": snapshot_metadata(snapshot)})
    pending.sort(key=lambda row: (row["reason"] != "stale", row["source_path"]))
    cap = max(0, min(int(limit), MAX_REFRESH_TARGETS))
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
    "CONTEXT_SCHEMA_VERSION",
    "EXTRACTOR_VERSION",
    "MAX_CONTEXT_CANDIDATES",
    "MAX_CONTEXT_DECISIONS",
    "MAX_REFRESH_TARGETS",
    "PROMPT_VERSION",
    "RELATIONS",
    "SNAPSHOT_KEYS",
    "build_context_snapshot",
    "refresh_reason",
    "select_refresh_targets",
    "snapshot_metadata",
    "source_revision",
    "validate_response",
]
