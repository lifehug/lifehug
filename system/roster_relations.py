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
import re
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


# --------------------------------------------------------------------------
# v344 — the person a relationship phrase INTRODUCES
# --------------------------------------------------------------------------
#
# WHERE IT WAS SEEN. The owner filed "Desiree Taylor (Dave's mom, also called
# Desi) — birthday June 19, 1955." on 2026-09-14. The classifier read the date
# perfectly and the roster never heard of her: its thirteen person rows held a
# COLLECTIVE `parents` ("Mom and Dad (parents)") and no mother. So "Desiree
# Taylor", "Desi", "Mom" and "mother" answered to nobody, his mother's birthday
# anchored nothing, and "Mom married dad at 21" stayed unplaced with her
# birthday sitting in the same vault.
#
# THE RULE. A source that introduces a named person with a RELATIONSHIP PHRASE
# — "Dave's mom", "my mother", "(wife)", "(brother)" — has said who that person
# is, and a person the vault has been told about EXISTS. The phrase is the
# owner's own words, so the relationship it states is filed as a roster
# relationship through the one writer that already creates rows this way
# (`entity_verdict.apply_verdict(..., ensure=True)`, `source: "landmark:family"`
# — the door `james` and `anthon-james-taylor` came through), never by editing
# the file. Everything here is PURE: claims and a roster snapshot in, rows out;
# the caller decides whether to file them.

#: The one statement of the rule, quoted by the seats that apply it.
A_RELATIONSHIP_PHRASE_INTRODUCES_A_PERSON = (
    "a named subject the roster has never heard of, introduced in its own "
    "source by a relationship phrase the owner used, is a person with that "
    "relationship — one roster row, through the roster's own writer"
)

#: Determiners a relationship phrase may be possessed by, besides an owner
#: spelling. "my mom" and "our mother" are the owner speaking.
INTRODUCTION_POSSESSIVES = ("my", "our")

#: An in-law is never the relation its phrase is built out of, so the row it
#: makes carries ``other`` — `axis_membership.DISTANT_RELATIONSHIPS`' own
#: bucket for exactly this case. Read from that module so there is one
#: definition of "this phrase says in-law".
FALLBACK_RELATIONSHIP = "other"


def roster_relationship_for(word: object) -> str:
    """The roster ``relationship`` a mention's relationship WORD states.

    Derived, never re-typed: `identity_resolution.RELATIONSHIP_MENTION_WORDS`
    already maps each word to the roster values that satisfy it, and
    `focus_candidate.FOCUS_RELATIONSHIPS` is the roster's own closed
    vocabulary. The answer is the first member of that vocabulary the word's set
    contains — so ``mother`` -> ``parent``, ``wife`` -> ``spouse`` (``spouse``
    precedes ``partner`` in the vocabulary), ``brother`` -> ``sibling`` — and
    :data:`FALLBACK_RELATIONSHIP` for a word the vocabulary has no seat for
    (``uncle``, ``aunt``, ``cousin``), which is where the owner's ruling puts
    them anyway.
    """
    from focus_candidate import FOCUS_RELATIONSHIPS  # noqa: PLC0415

    wanted = ir.RELATIONSHIP_MENTION_WORDS.get(
        ir.normalized_mention_key(word), frozenset()
    )
    if not wanted:
        return ""
    return next((value for value in FOCUS_RELATIONSHIPS if value in wanted),
                FALLBACK_RELATIONSHIP)


def relationship_aliases(word: object) -> tuple[str, ...]:
    """The mention spellings a person introduced by ``word`` also answers to.

    Every word in `identity_resolution.RELATIONSHIP_MENTION_WORDS` that
    satisfies EXACTLY the same roster values as ``word``, plus its ``my …``
    form — so "mom" brings "mother" (both satisfy ``{parent, mother}``) and
    never "dad" (``{parent, father}``), which is the whole reason the test is
    set EQUALITY and not "maps to the same relationship". "wife" brings only
    itself, because "husband" and "spouse" satisfy different sets. No second
    list of synonyms exists anywhere. Deterministic order.

    These are CANDIDATE aliases. :func:`alias_decision` is what decides whether
    each one may actually bind, and its shared-alias refusal is what keeps this
    from re-introducing the v335 ambiguity: a word two people already answer to
    binds to neither.
    """
    key = ir.normalized_mention_key(word)
    wanted = ir.RELATIONSHIP_MENTION_WORDS.get(key)
    if wanted is None:
        base = [key] if key else []
    else:
        base = sorted(
            other for other, values in ir.RELATIONSHIP_MENTION_WORDS.items()
            if values == wanted
        )
    out: list[str] = []
    for spelling in base:
        for form in (spelling, f"my {spelling}"):
            if form not in out:
                out.append(form)
    return tuple(out)


_NICKNAME_RE = re.compile(r"^[A-Z][\w'’.-]*(?:\s+[A-Z][\w'’.-]*)?$")


def _parentheticals(text: str) -> list[str]:
    return [body.strip() for body in re.findall(r"\(([^)]*)\)", text)]


def introduced_name(mention: object) -> tuple[str, tuple[str, ...]]:
    """``(name, nicknames)`` for a subject mention, or ``("", ())``.

    ``"Desiree Taylor (Desi)"`` -> ``("Desiree Taylor", ("Desi",))``. The name
    is the mention with its parentheticals removed; a parenthetical that reads
    as a short name of its own — one or two capitalised words, and not a
    relationship phrase — is a nickname. A mention with no NAME TOKEN at all
    ("mother", "my mom") names nobody this rule can file, which is exactly
    right: it is the thing the introduction is supposed to give a name to.
    """
    body = collapsed_text_of(mention)
    if not body:
        return "", ()
    nicknames: list[str] = []
    for inner in _parentheticals(body):
        names, relations = ir.mention_tokens(inner)
        if names and not relations and _NICKNAME_RE.match(inner):
            nicknames.append(inner)
    name = collapsed_text_of(re.sub(r"\([^)]*\)", " ", body))
    names, _ = ir.mention_tokens(name)
    if not names:
        return "", ()
    return name, tuple(nicknames)


def collapsed_text_of(value: object) -> str:
    """One space between words, nothing at the ends. The same normalisation
    every other reader of a mention uses, spelled through
    `identity_resolution` so this module keeps no second copy."""
    return " ".join(str(value or "").split())


def relationship_phrase(name: str, texts: object, *, owner_names: object = ()) -> str:
    """The relationship WORD a text introduces ``name`` with, or ``""``.

    Three shapes, all anchored on the name itself so a relation word loose
    elsewhere in the sentence never reaches it:

    * ``<Name> (…<possessive> <word>…`` / ``<Name>, <possessive> <word>`` —
      "Desiree Taylor (Dave's mom, also called Desi)", "Desiree Taylor, my
      mother". The possessive is ``my``/``our`` or an OWNER spelling's
      possessive, because "Katie's mom" is not the owner's mother;
    * ``<Name> (<word>)`` — "Katie Taylor (wife)", "A.J. (brother)", the
      household-roster shape, where the bracket itself is the apposition;
    * ``<possessive> <word> <Name>`` — "my mother Desiree Taylor".

    An in-law phrase ("my mother-in-law Ruth") returns the WORD it is built out
    of; :func:`roster_relationship_for` is not what decides that case —
    :func:`relationship_introduction` is, and it files ``other``.
    """
    if not name:
        return ""
    words = "|".join(
        re.escape(word) for word in sorted(ir.RELATIONSHIP_MENTION_WORDS, key=len,
                                           reverse=True)
    )
    possessives = [re.escape(word) for word in INTRODUCTION_POSSESSIVES]
    for spelling in owner_names or ():
        body = collapsed_text_of(spelling)
        if body:
            possessives.append(re.escape(body) + r"['’]s")
    possessive = "(?:" + "|".join(possessives) + r")\s+"
    anchor = re.escape(name)
    # An IN-LAW suffix is allowed to trail the word and is NOT stripped from the
    # reading: "my mother-in-law Ruth" introduces Ruth, and it is
    # :func:`relationship_introduction` — reading `axis_membership.IN_LAW_RE` over
    # the same text — that decides she is not the owner's mother.
    in_law = r"(?:[-\s]?in[-\s]?laws?)?"
    patterns = (
        rf"(?<!\w){anchor}\s*[(,]\s*(?:{possessive})?(?P<word>{words}){in_law}(?!\w)",
        rf"(?<!\w){possessive}(?P<word>{words}){in_law}\s+{anchor}(?!\w)",
    )
    for text in texts or ():
        body = collapsed_text_of(text)
        if not body:
            continue
        for pattern in patterns:
            match = re.search(pattern, body, re.IGNORECASE)
            if match is not None:
                return match.group("word").casefold()
    return ""


def relationship_introduction(mention: object, texts: object, *,
                              owner_names: object = ()) -> dict | None:
    """One introduced person, or ``None``
    (:data:`A_RELATIONSHIP_PHRASE_INTRODUCES_A_PERSON`).

    ``{"name", "slug", "relationship", "relationship_word", "aliases"}``. The
    aliases are the mention as written, any nickname it carries and the
    relationship spellings the phrase licenses — the exact set that has to bind
    for "Desi", "Mom" and "mother" to reach her — and each of them still goes
    through :func:`alias_decision`'s collision refusal at filing.

    An IN-LAW phrase files ``other``, whatever relation word it is built out of:
    "mother-in-law" contains "mother" and is not the owner's mother
    (`axis_membership.IN_LAW_RE`, the one definition of that reading).
    """
    import axis_membership as axm  # noqa: PLC0415

    name, nicknames = introduced_name(mention)
    if not name or ir.normalized_mention_key(mention) in ir.OWNER_SUBJECT_MENTIONS:
        return None
    word = relationship_phrase(name, texts, owner_names=owner_names)
    if not word:
        return None
    in_law = any(axm.IN_LAW_RE.search(collapsed_text_of(text)) for text in texts or ())
    relationship = FALLBACK_RELATIONSHIP if in_law else roster_relationship_for(word)
    if not relationship:
        return None
    slug = ir.normalized_mention_key(name).replace(" ", "-")
    if not slug:
        return None
    aliases: list[str] = []
    for alias in (collapsed_text_of(mention), *nicknames,
                  *(() if in_law else relationship_aliases(word))):
        if alias and alias != name and alias not in aliases:
            aliases.append(alias)
    return {
        "name": name,
        "slug": slug,
        "relationship": relationship,
        "relationship_word": word,
        "aliases": tuple(aliases),
    }


def relationship_introductions(claims: object, *, roster: object = (),
                               owner_names: object = ()) -> tuple[dict, ...]:
    """Every person the CLAIM SUBSTRATE introduces and the roster lacks.

    One row per subject mention, in mention-key order so two runs file the same
    rows in the same order. The texts a mention is read against are its OWN
    source's — every ``event_mention``, evidence quote and subject mention of
    the claims citing that ``source_id`` — which is what "introduced with a
    relationship phrase IN THE SAME SOURCE" means, and why a relation word in
    an unrelated answer cannot name somebody.

    A mention that already carries a ``subject_ref``, or that any roster row
    already answers to, is skipped: this rule creates the row nobody has
    written, and never re-decides one somebody has. A ``born`` date rides along
    when the introducing source also states that person's BIRTHDAY
    (`landmark_projection.birth_event_subject`), because it is the same
    sentence and the roster's ``born`` is the second tier the age arithmetic
    reads.
    """
    import chronology as chrono  # noqa: PLC0415
    import landmark_projection as lp  # noqa: PLC0415

    rows = [claim for claim in claims or () if isinstance(claim, dict)]
    by_source: dict[str, list[dict]] = {}
    for claim in rows:
        ref = claim.get("source_ref")
        source_id = collapsed_text_of(ref.get("source_id")) if isinstance(ref, dict) else ""
        by_source.setdefault(source_id, []).append(claim)

    index = None
    try:
        index = ir.roster_index(roster, entity_type="person")
    except Exception:  # noqa: BLE001  — a roster we cannot read knows nobody
        index = None

    def known(mention: str) -> bool:
        if index is None:
            return False
        key = ir.normalized_mention_key(mention)
        return bool(index.by_name_key.get(key) or index.by_alias_key.get(key)
                    or index.has_ref(collapsed_text_of(mention)))

    out: dict[str, dict] = {}
    for source_id, group in sorted(by_source.items()):
        texts: list[str] = []
        for claim in group:
            for value in (claim.get("event_mention"), claim.get("subject_mention")):
                body = collapsed_text_of(value)
                if body and body not in texts:
                    texts.append(body)
            for item in claim.get("evidence") or ():
                body = collapsed_text_of(item.get("quote")) if isinstance(item, dict) else ""
                if body and body not in texts:
                    texts.append(body)
        for claim in group:
            if collapsed_text_of(claim.get("subject_ref")):
                continue
            mention = collapsed_text_of(claim.get("subject_mention"))
            key = ir.normalized_mention_key(mention)
            if not key or key in out or known(mention):
                continue
            row = relationship_introduction(mention, texts, owner_names=owner_names)
            if row is None:
                continue
            row = {**row, "source_id": source_id, "mention": mention}
            born = _introduced_birth(row["name"], group, chrono=chrono, lp=lp)
            if born is not None:
                row["born"], row["born_basis"] = born
            out[key] = row
    return _without_contested_aliases(tuple(out[key] for key in sorted(out)))


def _without_contested_aliases(rows: tuple) -> tuple[dict, ...]:
    """The v335 rule applied to the BATCH, before anything is written.

    Two people introduced by the same relationship word — the owner's vault
    names his father twice, as "James Taylor (Dad)" and as "James Edwin Taylor
    Sr." — both claim "dad". Filing them one at a time would give the alias to
    whichever row went first, which is an identity decided by file order; and
    :func:`alias_decision` refusing the second would leave the first holding it
    alone, which is the same defect wearing a refusal. So an alias more than one
    row claims is dropped from EVERY row: two people answering to one word bind
    to neither, which is the roster's own shared-alias rule stated over the whole
    set at once. Each row keeps its own name and nicknames, which nobody
    contests.
    """
    census: dict[str, int] = {}
    for row in rows:
        for alias in row.get("aliases") or ():
            key = ir.normalized_mention_key(alias)
            census[key] = census.get(key, 0) + 1
    out = []
    for row in rows:
        kept = tuple(alias for alias in row.get("aliases") or ()
                     if census.get(ir.normalized_mention_key(alias), 0) == 1)
        contested = tuple(alias for alias in row.get("aliases") or ()
                          if alias not in kept)
        row = {**row, "aliases": kept}
        if contested:
            row["contested_aliases"] = contested
        out.append(row)
    return tuple(out)


def _introduced_birth(name: str, claims: object, *, chrono, lp) -> tuple | None:
    """``(edtf, basis)`` when one of these claims states THIS person's birthday.

    The date claim is read through the same `landmark_projection` reading the
    fold uses, so the roster's ``born`` and the timeline's birth node can never
    come from two different opinions about which sentence is a birthday.
    """
    wanted = ir.normalized_mention_key(name)
    for claim in claims or ():
        subject = lp.birth_event_subject(claim.get("event_mention"))
        if not subject or ir.normalized_mention_key(subject) != wanted:
            continue
        record = chrono.from_dict(claim.get("temporal_value"))
        if record is None or record.granularity not in ("day", "month", "year"):
            continue
        return record.best, (record.basis or "stated")
    return None


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
