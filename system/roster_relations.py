#!/usr/bin/env python3
"""E-L2c: organizations, place hierarchy and alias decisions on the roster.

Design: lifehug-platform `docs/design/timeline-eras.md` v2.1 §3.1 (durable
entities), §3.3 (the typed relation matrix — `located_in`), §4.3 (alias
binding, the collision rule). Everything here is PURE — a snapshot in, a
snapshot (or a refusal naming a collision) out — the same shape
`identity_resolution` and `episode_containers` already hold to, so a caller
decides when and whether to persist a change rather than this module
guessing at a vault root.

**Why a new module rather than widening `entity_roster.ENTITY_TYPES`.**
`entity_roster.py` already owns an AI-assisted candidate pipeline
(`resolve`/`--from-response`), wiki-serving thresholds
(`entity_roster.THRESHOLDS`) and graduation rules keyed to exactly the five
existing types — `person | place | period | object | theme`. Widening that
global tuple would touch every consumer of it (`serve_wiki.py`,
`recommend_focuses.py`, `entity_verdict.py`, `focus_merge.py`, `jobs.py`)
with no organization-shaped prompt, threshold or wiki template behind any of
them — a much larger, untested surface than this program's identity-substrate
scope. `episode_containers.py` already anticipated exactly this split in its
own comment on `ENTITY_ROSTER_TYPES`: the containment binder's entity index
needs organizations; the AI/wiki roster pipeline does not, yet. So
organizations are added to `episode_containers.ENTITY_ROSTER_TYPES` only —
same JSON-snapshot shape, same alias mechanics, same file layout
(`state/entity_rosters/organization.json`), read by the same generic
`identity_resolution.roster_index` — and the wiki/candidate-generation
pipeline is a named follow-on.

**Why alias/`located_in` decisions stay roster-JSON state, not a durable
source.** Design §3.5 classifies these as "authored" facts that survive a
`state/` deletion. Today the roster itself (`state/entity_rosters/*.json`,
M5's own finding) is where a place's aliases already live, and it lives
under `state/` — the honest reading of the substrate as it exists, not as a
future version might. Building a parallel durable decision-record type
(with its own fold back into the roster on rebuild) is a bigger, separate
architectural change than this program's bounded identity-substrate scope;
this module keeps aliases and `located_in` exactly where places' aliases
already are, and names the gap rather than silently building around it.
"""

from __future__ import annotations

import sys
from pathlib import Path

_SYSTEM_DIR = Path(__file__).resolve().parent
if str(_SYSTEM_DIR) not in sys.path:
    sys.path.insert(0, str(_SYSTEM_DIR))

import identity_resolution as ir  # noqa: E402

#: Employers and schools alike (design §3.1); `schools` are organizations
#: whose `organization_kind` is `school`.
ORGANIZATION_ENTITY_TYPE = "organization"
ORGANIZATION_KINDS = ("school", "employer", "other")

#: Reused verbatim from the eras program's own shared-alias rule
#: (`event_binding.AMBIGUOUS_WORK_ITEM_KIND`) — one word for "the resolver
#: honestly could not tell which of these you meant", regardless of what
#: kind of entity is ambiguous.
IDENTITY_UNCERTAIN_KIND = "identity_uncertain"


class RosterRelationError(ValueError):
    """A roster relation could not be resolved, minted or filed."""


def roster_entities(snapshot: object) -> list[dict]:
    """Every entity row in a roster snapshot, tolerant of both stored shapes
    (`entity_roster.load_roster`'s ``{"entities": [...]}`` or a bare list)."""
    if isinstance(snapshot, dict):
        entities = snapshot.get("entities")
        return [e for e in entities if isinstance(e, dict)] if isinstance(entities, list) else []
    if isinstance(snapshot, list):
        return [e for e in snapshot if isinstance(e, dict)]
    return []


def _slug_of(entity: dict) -> str:
    """The entity's slug, falling back to its name — the same fallback
    `identity_resolution._entity_slug` uses, re-derived here rather than
    imported so this module never reaches across a private name."""
    key = ir.normalized_mention_key(entity.get("slug")) or ir.normalized_mention_key(entity.get("name"))
    return key.replace(" ", "-")


def entity_ref(entity_type: str, entity: dict) -> str:
    """The same ``type/slug`` ref shape every other reader of this roster
    already uses (`identity_resolution.entity_ref`)."""
    return ir.entity_ref(entity_type, _slug_of(entity))


def find_by_name(snapshot: object, name: object) -> dict | None:
    key = ir.normalized_mention_key(name)
    if not key:
        return None
    for entity in roster_entities(snapshot):
        if ir.normalized_mention_key(entity.get("name")) == key:
            return entity
    return None


def find_by_ref(entity_type: str, snapshot: object, ref: object) -> dict | None:
    target = str(ref or "").strip()
    if not target:
        return None
    for entity in roster_entities(snapshot):
        if entity_ref(entity_type, entity) == target:
            return entity
    return None


def find_by_alias(snapshot: object, alias: object) -> list[dict]:
    """Every entity whose NAME or an existing ALIAS matches ``alias``
    (case/whitespace-insensitive) — the collision candidates for
    :func:`alias_decision`."""
    key = ir.normalized_mention_key(alias)
    if not key:
        return []
    hits = []
    for entity in roster_entities(snapshot):
        keys = {ir.normalized_mention_key(entity.get("name"))}
        keys.update(ir.normalized_mention_key(a) for a in entity.get("aliases") or ())
        if key in keys:
            hits.append(entity)
    return hits


def resolve_or_create(entity_type: str, name: object, snapshot: object, *,
                      organization_kind: str | None = None) -> tuple[str, dict, bool]:
    """``(ref, updated_snapshot, created)`` — a pure "find or mint" (design
    §10.3: "``place_ref`` — the roster entity, created if absent").

    Matches an existing entity by exact case/whitespace-insensitive NAME
    only — never by alias, which is :func:`alias_decision`'s ambiguity check
    to make, not this function's silent reuse. A genuinely new name mints a
    minimal entity (``name``, ``slug``, ``aliases: []``) and, for an
    organization, its ``organization_kind`` when one was given.
    """
    label = str(name or "").strip()
    if not label:
        raise RosterRelationError("a roster entity needs a name")
    snap = snapshot if isinstance(snapshot, dict) else {
        "version": 1, "type": entity_type, "entities": [],
    }
    entities = roster_entities(snap)
    existing = find_by_name(snap, label)
    if existing is not None:
        return entity_ref(entity_type, existing), snap, False
    base_slug = ir.normalized_mention_key(label).replace(" ", "-") or "entity"
    used = {_slug_of(e) for e in entities}
    slug, suffix = base_slug, 2
    while slug in used:
        slug = f"{base_slug}-{suffix}"
        suffix += 1
    new_entity: dict = {"name": label, "slug": slug, "aliases": []}
    if entity_type == ORGANIZATION_ENTITY_TYPE and organization_kind:
        kind = str(organization_kind).strip()
        if kind not in ORGANIZATION_KINDS:
            raise RosterRelationError(f"unknown organization_kind: {organization_kind!r}")
        new_entity["organization_kind"] = kind
    updated = {**snap, "entities": [*entities, new_entity]}
    return entity_ref(entity_type, new_entity), updated, True


def alias_decision(entity_type: str, ref: object, alias: object, snapshot: object) -> dict:
    """Add ``alias`` to the entity at ``ref``, or refuse with a collision.

    Design §4.3, reusing the eras program's shared-alias rule verbatim: two
    entities answering to the same alias bind to NEITHER — this call refuses
    and returns the :data:`IDENTITY_UNCERTAIN_KIND` naming both, exactly the
    shape `event_binding.ambiguous_work_item` already mints for two eras
    sharing a label. Adding an alias that is already present is an idempotent
    success with ``changed: False``.

    Returns one of:
      ``{"applied": True, "snapshot": ..., "changed": bool}``
      ``{"applied": False, "reason": "identity_uncertain", "candidates": [...]}``
      ``{"applied": False, "reason": "entity_not_found"}``
      ``{"applied": False, "reason": "alias_empty"}``
    """
    alias_text = str(alias or "").strip()
    if not alias_text:
        return {"applied": False, "reason": "alias_empty"}
    snap = snapshot if isinstance(snapshot, dict) else {"entities": []}
    entities = roster_entities(snap)
    target = find_by_ref(entity_type, snap, ref)
    if target is None:
        return {"applied": False, "reason": "entity_not_found"}
    target_ref = entity_ref(entity_type, target)
    colliders: dict[str, dict] = {}
    for entity in find_by_alias(snap, alias_text):
        entity_ref_value = entity_ref(entity_type, entity)
        if entity_ref_value != target_ref:
            colliders[entity_ref_value] = entity
    if colliders:
        candidates = [{"ref": target_ref, "name": target.get("name")}]
        candidates.extend(
            {"ref": r, "name": e.get("name")}
            for r, e in sorted(colliders.items())
        )
        names = " or ".join(str(c["name"]) for c in candidates)
        return {
            "applied": False,
            "reason": IDENTITY_UNCERTAIN_KIND,
            "candidates": candidates,
            "headline": f"“{alias_text}” could be {names}",
        }
    existing_aliases = [str(a) for a in target.get("aliases") or ()]
    if any(ir.normalized_mention_key(a) == ir.normalized_mention_key(alias_text)
          for a in existing_aliases):
        return {"applied": True, "snapshot": snap, "changed": False}
    updated_entities = []
    for entity in entities:
        if entity is target:
            entity = {**entity, "aliases": [*existing_aliases, alias_text]}
        updated_entities.append(entity)
    return {"applied": True, "snapshot": {**snap, "entities": updated_entities}, "changed": True}


def located_in(child_ref: object, parent_ref: object, snapshot: object) -> dict:
    """Set ``located_in`` on the child PLACE entity (design §3.3, §4.1's
    "city rule" — the hierarchy `located_in` records, home -> city).

    Pure and idempotent; re-filing the same edge is a no-op change. A
    different parent is a new decision that overwrites the old edge — this
    module does not itself keep a history of prior parents (§3.5's "survives
    state deletion" caveat applies here exactly as it does to aliases, see
    the module docstring).
    """
    entities = roster_entities(snapshot)
    child = str(child_ref or "").strip()
    parent = str(parent_ref or "").strip()
    if not child or not parent:
        raise RosterRelationError("located_in needs both a child and a parent ref")
    updated = []
    found = False
    for entity in entities:
        if entity_ref("place", entity) == child:
            entity = {**entity, "located_in": parent}
            found = True
        updated.append(entity)
    if not found:
        raise RosterRelationError(f"unknown place: {child!r}")
    snap = snapshot if isinstance(snapshot, dict) else {"entities": []}
    return {**snap, "entities": updated}


def located_in_chain(place_ref: object, snapshot: object, *,
                     max_depth: int = 8) -> tuple[str, ...]:
    """The place's own `located_in` chain, nearest first (home, city, region).

    Cycle-safe: a chain that would repeat an already-visited ref stops rather
    than looping — a malformed roster degrades to a shorter chain, never a
    hang, matching every other reader's "degrade, never raise" contract.
    """
    entities_by_ref = {
        entity_ref("place", entity): entity for entity in roster_entities(snapshot)
    }
    chain: list[str] = []
    seen: set[str] = set()
    current = str(place_ref or "").strip()
    while current and current not in seen and len(chain) < max_depth:
        seen.add(current)
        entity = entities_by_ref.get(current)
        if entity is None:
            break
        parent = str(entity.get("located_in") or "").strip()
        if not parent:
            break
        chain.append(parent)
        current = parent
    return tuple(chain)
