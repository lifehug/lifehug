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

import hashlib
import json
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
PLACE_IDENTITY_FIELDS = ("place_kind", "residence_identity", "located_in", "alias_ownership")


class RosterRelationError(ValueError):
    """A roster relation could not be resolved, minted or filed."""


class RosterIdentityUncertain(RosterRelationError):
    """Existing house identity is ambiguous; minting is not a resolution."""


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


def resolve_residence_place(record: dict, snapshot: object) -> tuple[str | None, dict]:
    """Resolve a house independently of its stays; a city is only its parent.

    Exact supplied address/city are identity evidence, never dates or a maps
    lookup. An established individual ref wins, but a containing city ref does
    not. Legacy city aliases are left untouched for the alias authority to
    report as ambiguity. No fuzzy address equivalence or automatic migration.
    """
    snap = snapshot if isinstance(snapshot, dict) else {"type": "place", "entities": []}
    city = str(record.get("city") or "").strip()
    address = str(record.get("address") or "").strip()
    nickname = str(record.get("nickname") or "").strip()
    explicit = find_by_ref("place", snap, record.get("place_ref"))
    city_matches = {entity_ref("place", e) for e in find_by_alias(snap, city)}
    is_city = (explicit is not None and explicit.get("place_kind") != "residence" and (
        entity_ref("place", explicit) in city_matches
        or explicit.get("place_kind") in {"city", "region", "country"}))
    individual_names = {ir.normalized_mention_key(v) for v in (address, nickname) if v}
    explicit_names = ({ir.normalized_mention_key(explicit.get("name"))}
                      | {ir.normalized_mention_key(a) for a in explicit.get("aliases") or ()}
                      if explicit else set())
    if explicit is not None and not is_city and (
            explicit.get("place_kind") == "residence"
            or individual_names & explicit_names):
        return entity_ref("place", explicit), snap
    if not address and not nickname:
        if city:
            ref, snap, _ = resolve_or_create("place", city, snap)
            return ref, snap
        return (entity_ref("place", explicit) if explicit else None), snap

    def norm(value: str) -> str:
        return " ".join(value.casefold().split())
    identity = {"city": norm(city), "address": norm(address)} if address else {
        "city": norm(city), "nickname": norm(nickname)}
    matches = [e for e in roster_entities(snap) if e.get("residence_identity") == identity]
    if len(matches) == 1:
        return entity_ref("place", matches[0]), snap
    if len(matches) > 1:
        raise RosterIdentityUncertain("multiple places have the supplied residence identity")
    if not address:
        named = [e for e in find_by_alias(snap, nickname)
                 if e.get("place_kind") == "residence"
                 and (not city or (e.get("residence_identity") or {}).get("city") == norm(city))]
        if len(named) == 1:
            return entity_ref("place", named[0]), snap
        if len(named) > 1:
            raise RosterIdentityUncertain("the nickname identifies multiple houses; supply an individual place ref or address")

    digest = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()[:20]
    slug = f"residence-{digest}"
    if any(_slug_of(e) == slug for e in roster_entities(snap)):
        raise RosterIdentityUncertain("residence identity is ambiguous")
    # A nickname-only place still needs an independent name so retracting its
    # alias does not leave that same alias active as the entity's primary name.
    label = ", ".join(v for v in (address, city) if v) if address else f"Residence {digest}"
    house = {"name": label, "slug": slug, "aliases": [], "place_kind": "residence",
             "residence_identity": identity}
    snap = {**snap, "entities": [*roster_entities(snap), house]}
    ref = entity_ref("place", house)
    if city:
        parent, snap, _ = resolve_or_create("place", city, snap)
        snap = located_in(ref, parent, snap)
    return ref, snap


def settled_place_refs(snapshot: object) -> set[str]:
    """Explicit place decisions and their containing places survive refresh.

    The roster is already the alias/hierarchy authority; a model's refreshed
    mention list may not delete its decisions or coalesce their identities.
    """
    refs = {entity_ref("place", e) for e in roster_entities(snapshot)
            if any(e.get(field) is not None for field in PLACE_IDENTITY_FIELDS)}
    for ref in tuple(refs):
        refs.update(located_in_chain(ref, snapshot))
    return refs


def alias_decision(entity_type: str, ref: object, alias: object, snapshot: object, *,
                   owner: str | None = None) -> dict:
    """Add ``alias`` to the entity at ``ref``, or refuse with a collision.

    Design §4.3, reusing the eras program's shared-alias rule verbatim: two
    entities answering to the same alias bind to NEITHER — this call refuses
    and returns the :data:`IDENTITY_UNCERTAIN_KIND` naming both, exactly the
    shape `event_binding.ambiguous_work_item` already mints for two eras
    sharing a label. Adding an alias that is already present is an idempotent
    success with ``changed: False``.

    With a telling-ref ``owner``, record the owned claim even when it collides:
    the existing multi-match resolver must see both candidates. Such a result
    remains ``applied: False`` and names the ambiguity; ``changed`` describes
    recorded state, not a successful unique identity decision. Ownership is
    retained separately from whether this call first inserted the alias.

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
    refusal = {}
    if colliders:
        candidates = [{"ref": target_ref, "name": target.get("name")}]
        candidates.extend(
            {"ref": r, "name": e.get("name")}
            for r, e in sorted(colliders.items())
        )
        names = " or ".join(str(c["name"]) for c in candidates)
        refusal = {
            "applied": False,
            "reason": IDENTITY_UNCERTAIN_KIND,
            "candidates": candidates,
            "headline": f"“{alias_text}” could be {names}",
        }
        if not owner:
            return refusal
    existing_aliases = [str(a) for a in target.get("aliases") or ()]
    key = ir.normalized_mention_key(alias_text)
    exists = any(ir.normalized_mention_key(a) == key for a in existing_aliases)
    ownership = dict(target.get("alias_ownership") or {})
    old_ownership = dict(ownership)
    if owner:
        standing = ownership.get(key) or {"owners": [], "created": not exists}
        ownership[key] = {**standing, "owners": sorted(set(standing["owners"]) | {owner})}
    if exists and ownership == old_ownership:
        return {"applied": True, "snapshot": snap, "changed": False, **refusal,
                **({"owner": owner} if owner else {})}
    updated_entities = []
    for entity in entities:
        if entity is target:
            entity = {**entity, "aliases": existing_aliases if exists else [*existing_aliases, alias_text]}
            if owner:
                entity["alias_ownership"] = ownership
        updated_entities.append(entity)
    # Owned conflicting claims stay discoverable by the existing multi-match
    # resolver. This records ambiguity, NOT a successful unique alias mapping.
    return {"applied": True, "snapshot": {**snap, "entities": updated_entities},
            "changed": not exists, **refusal,
            **({"owner": owner, "ownership_changed": ownership != old_ownership} if owner else {})}


def retract_alias(entity_type: str, ref: object, alias: object,
                  snapshot: object, *, owner: str | None = None) -> dict:
    """Take ``alias`` back off the entity at ``ref``. The undo of
    :func:`alias_decision`, and its exact mirror.

    Add Landmark's `retract` (v292) undoes the NAMES an apply filed, and a
    nickname filed as a roster alias is one of them. Pure and idempotent: an
    alias that is not there returns ``changed: False`` and the snapshot
    unchanged, so a second retraction of the same receipt removes nothing a
    second time. Matching is `identity_resolution.normalized_mention_key`'s,
    the same key :func:`alias_decision` refuses a duplicate by — one
    definition of "the same alias", not two.

    Returns ``{"applied": bool, "snapshot": ..., "changed": bool}`` or
    ``{"applied": False, "reason": "entity_not_found" | "alias_empty"}``.
    """
    alias_text = str(alias or "").strip()
    if not alias_text:
        return {"applied": False, "reason": "alias_empty"}
    snap = snapshot if isinstance(snapshot, dict) else {"entities": []}
    target = find_by_ref(entity_type, snap, ref)
    if target is None:
        return {"applied": False, "reason": "entity_not_found"}
    wanted = ir.normalized_mention_key(alias_text)
    ownership = dict(target.get("alias_ownership") or {})
    if owner:
        standing = ownership.get(wanted) or {}
        if owner not in standing.get("owners", ()):
            return {"applied": True, "snapshot": snap, "changed": False}
        remaining = [value for value in standing["owners"] if value != owner]
        if remaining:
            ownership[wanted] = {**standing, "owners": remaining}
        else:
            del ownership[wanted]
        remove = not remaining and standing.get("created")
    else:
        remove = not (ownership.get(wanted) or {}).get("owners")
    kept = [str(value) for value in target.get("aliases") or ()
            if not remove or ir.normalized_mention_key(str(value)) != wanted]
    changed = len(kept) != len(list(target.get("aliases") or ()))
    if not changed and not owner:
        return {"applied": True, "snapshot": snap, "changed": False}
    updated = [{**entity, "aliases": kept,
                **({"alias_ownership": ownership} if owner else {})} if entity is target else entity
               for entity in roster_entities(snap)]
    return {"applied": True, "snapshot": {**snap, "entities": updated},
            "changed": changed, **({"ownership_changed": True} if owner else {})}


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
