#!/usr/bin/env python3
"""Lifehug — `entity-verdict`, the owner's graduation accelerator/veto (ADR 0013).

The entity-candidates lane graduates entities into wiki pages fully
automatically (the Convergence Principle's floor, ADR 0006 — untouched by
this module). This is the accelerator half: two settled overrides the owner
can stamp on any roster entity, mirroring the focus lane's dismiss-forever
and the candidate lane's promote-override.

    entity-verdict <type> <slug> graduate|never|clear
        [--alias A]... [--relationship R] [--living|--not-living]
        [--born EDTF [--born-basis B]] [--died EDTF [--died-basis B]]
        [--fold-into ROW | --focus FOCUS] [--retract-alias A]...
        [--share-alias A --with WHO] [--located-in PLACE] [--handle H | --clear-handle]
        [--ensure [--name NAME]]   (--maps-to: deprecated, rewritten)

  - `graduate` — an entity the owner knows matters shouldn't have to wait
    for its second mention: `page_eligible` is forced true regardless of
    score/answer thresholds (the entity must still have no home — a
    `focus` or `folded_into` wins; refused on such an entity, which already
    has a page there), and `wiki_compile.plan_entities`'s real-mention bar drops to >= 1
    for it. Never a zero-mention page: a page still needs at least one real
    source.
  - `never` — a permanent veto for the junk class the AI keeps
    re-considering: `page_eligible` is forced false, forever. The entity
    REMAINS on the roster — attribution and alias folding continue; only
    the standalone page is suppressed. The candidates lane and viewer stop
    proposing it.
  - `clear` — returns the entity to fully automatic eligibility (recomputed
    via `entity_roster.base_page_eligible`, the same formula `normalize()`
    uses).

Both settled verdicts are enforced ON the roster record — `normalize()` and
`apply_previous_decisions()` (`system/entity_roster.py`) make an
`owner_verdict` a fact the AI can never remove or overturn, surviving every
subsequent refresh, including one whose raw output tries to re-qualify or
re-disqualify the entity, or omits it from its candidate list entirely.
There is no parallel ledger: the roster IS the settled-identity store for
entities (contract: entity-owner-verdicts, ADR 0013).

entity-identity-context (v190) adds the identity half. Play graduates in the
background AND opens the identity conversation (platform ADR 0020,
review-loop/57), so the same background job carries both the verdict and
whatever the conversation learned — aliases, relationship, living, and the
merge. Extending this verb rather than adding a second one is deliberate: two
verbs would mean two writers for one roster file and two doors for one settled
fact, which is exactly what the recurring-defect doctrine exists to prevent.

  - `--alias A` (repeatable) — unioned into the entry's `aliases` (trimmed,
    deduplicated case-insensitively, capped). The compiler matches sources
    against `[name] + aliases`, so an alias is the fact that lets a page find
    its own material.
  - `--relationship R` — closed against `focus_candidate.FOCUS_RELATIONSHIPS`
    (the focus lane's list, imported rather than re-typed).
  - `--living` / `--not-living` — a real bool on the entry.
  - `--born EDTF` / `--died EDTF` (v217) — the two most common datable
    facts in a life story, finally with a home on the person they belong
    to. Parsed by `chronology.parse_edtf` and normalized by
    `chronology.normalized_date` — the SAME two calls `lifehug.py
    landmark-record --date` makes, not a second date reader — and stored
    as a full `DateRecord` dict so a bare year still carries real bounds
    and can date something. `--born-basis` / `--died-basis` name the
    warrant (`chronology.BASES`, default `stated`); they are what makes
    the precedence rule below expressible from the command line.
    Both fields are in `entity_roster._SETTLED_IDENTITY_FIELDS`, so a
    roster refresh can never drop them.
  - `--ensure` (v202) — an absent slug is CREATED rather than refused, for a
    person the family landmark set named who has no answer mentions yet. The
    created row is never page-eligible (ADR 0013's mention floor); it exists
    to hold the settled identity facts. Idempotent.
  - `--maps-to SLUG` — the merge. SLUG must be another entity in the SAME
    roster or a known Focus slug. **maps-to wins over graduate**: supplied
    together, the mapping applies and the graduation does not, because a
    mapped entity already has a home (the same rationale as the pre-existing
    refusal below). Nothing raises, because the platform's identity job is a
    single background call that always carries the graduation — failing it
    would strand the identity. Without `--maps-to`, `graduate` on an
    already-mapped entity keeps raising exactly as it did before v190.

v383 (ADR 0041 — the roster is the identity ledger): every alias this verb
writes — each `--alias`, and the loser's name + aliases during `--maps-to` —
is a decision under `roster_relations.alias_decision`'s collision rule. An
alias another row already answers to binds to NEITHER: the WHOLE verdict is
refused (no partial union, the roster file untouched), the package's refusal
— `{"applied": false, "reason": "identity_uncertain", "candidates": [...]}`,
both claimants named — is printed as JSON on stdout, and the CLI exits 2. A
re-add of an alias already present stays an idempotent success. A fold is a
pointer, never a deletion: the loser keeps its row with `folded_into =
<survivor>` (v386; `maps_to_focus` before). After a successful `--maps-to`/`--alias` the CLI runs the
keyless `entity_roster.recount` for the touched type, so the fold's effect on
mention counts is visible on the next read.

v386 (ADR 0043 — one person, one record): `--maps-to` meant two things
and is split. `--fold-into ROW` is the duplicate fold (the loser becomes a
pointer, `folded_into`); `--focus FOCUS` attaches a Focus to this record,
which STAYS a live person (`focus`). `--maps-to` is accepted for one version
and rewritten (a row slug → `--fold-into`, else `--focus`) with a
deprecation line on stderr. `--retract-alias` undoes an alias for every type
(`roster_relations.retract_alias`); `--share-alias A --with WHO` marks an alias
shared with somebody who has no record (D9); `--located-in` is the place join
(D8 — a place fold is refused unless the rows are true duplicates);
`--handle` files the record's exclusive short @handle (unique across every
roster, charset-checked); `--clear-handle` removes it.

Usage:
    python3 system/entity_verdict.py person betty-jo graduate
    python3 system/entity_verdict.py object the-orange-cone never --json
    python3 system/entity_verdict.py place old-house clear
    python3 system/entity_verdict.py person ada graduate --alias Jo \
        --relationship parent --not-living
    python3 system/entity_verdict.py person jim graduate --maps-to jim-reynolds
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

SYSTEM_DIR = Path(__file__).resolve().parent
if str(SYSTEM_DIR) not in sys.path:
    sys.path.insert(0, str(SYSTEM_DIR))

import chronology  # noqa: E402
import identity_handles  # noqa: E402
import identity_resolution as ir  # noqa: E402
import roster_relations  # noqa: E402
from entity_roster import (  # noqa: E402
    ENTITY_TYPES,
    PERSON_DATE_FIELDS,
    THRESHOLDS,
    _focus_map,
    apply_owner_verdict,
    base_page_eligible,
    read_roster_payload,
)
from lifehug_core import write_json  # noqa: E402

VERDICTS = ("graduate", "never", "clear")

#: `entity_roster.GRANDPARENT_SIDE_FIELD`'s two values (the side card's own).
GRANDPARENT_SIDE_FIELD = "grandparent_side"
GRANDPARENT_SIDES = ("maternal", "paternal")
#: The word he calls this person by ("Grandpa", "Mom") — v360, owner 2026-09-25.
RELATION_WORD_FIELD = "relation_word"


class EntityVerdictError(ValueError):
    """A verdict that must not apply — unknown type/slug, or `graduate` on
    a mapped entity. Always raised BEFORE any write: a refused verdict
    leaves the roster file byte-for-byte unchanged."""


#: The CLI's exit code for a verdict refused by the alias collision rule
#: (v383, ADR 0041) — distinct from 1 (a malformed or impossible verdict) so a
#: host can render the two claimants and ask, rather than report an error.
EXIT_IDENTITY_UNCERTAIN = 2


class EntityAliasContested(EntityVerdictError):
    """v383 (ADR 0041): an alias this verdict would write already answers to
    ANOTHER roster row. `roster_relations.alias_decision`'s collision rule —
    one alias claimed by two entities binds to NEITHER — refuses the WHOLE
    verdict: no partial union, the roster file untouched. ``result`` is the
    package's own refusal (``{"applied": False, "reason":
    "identity_uncertain", "candidates": [...], ...}``) plus the ``alias`` that
    collided, so a host names both claimants and asks; it never picks."""

    def __init__(self, result: dict) -> None:
        self.result = result
        names = " or ".join(str(c.get("name")) for c in result.get("candidates") or ())
        super().__init__(f"alias {result.get('alias')!r} is contested — it could be {names}; "
                         "nothing was written")


def _validated_identity(
    aliases: Sequence[str], relationship: str | None, living: object
) -> tuple[list[str], str | None, bool | None]:
    """Closed-vocabulary checks for the identity flags, BEFORE any read or
    write. `focus_candidate.FOCUS_RELATIONSHIPS` and
    `entity_candidate.MAX_ENTITY_ALIASES` are imported lazily: this verb is on
    the vault-mutation path and has no business pulling the whole Interaction
    runtime in just to name two constants."""
    from entity_candidate import MAX_ENTITY_ALIASES, MAX_ENTITY_ALIAS_CHARS  # noqa: PLC0415
    from focus_candidate import FOCUS_RELATIONSHIPS  # noqa: PLC0415

    cleaned: list[str] = []
    seen: set[str] = set()
    for raw in aliases or ():
        alias = str(raw or "").strip()
        if not alias:
            continue
        if len(alias) > MAX_ENTITY_ALIAS_CHARS:
            raise EntityVerdictError(
                f"alias too long (max {MAX_ENTITY_ALIAS_CHARS} characters): {alias!r}")
        if alias.lower() in seen:
            continue
        seen.add(alias.lower())
        cleaned.append(alias)
    if len(cleaned) > MAX_ENTITY_ALIASES:
        raise EntityVerdictError(
            f"too many aliases in one call (max {MAX_ENTITY_ALIASES})")

    if relationship is not None:
        relationship = str(relationship).strip()
        if relationship not in FOCUS_RELATIONSHIPS:
            raise EntityVerdictError(
                f"unknown relationship: {relationship!r} "
                f"(known: {', '.join(FOCUS_RELATIONSHIPS)})")
    if living is not None and not isinstance(living, bool):
        raise EntityVerdictError("living must be a bool (--living / --not-living)")
    return cleaned, relationship, living


def parse_person_date(flag: str, value: object, basis: object = None) -> dict | None:
    """One `--born`/`--died` value as a stored `DateRecord` dict, or ``None``.

    ONE date definition, reused: `chronology.parse_edtf` reads the expression
    exactly as `lifehug.py landmark-record --date` does, and
    `chronology.normalized_date` fills the bounds exactly as every landmark
    date already gets them. Nothing here re-implements EDTF.

    Raises `EntityVerdictError` — never writes — on an unreadable date or an
    unknown basis, so a typo leaves the roster byte-for-byte unchanged.
    """
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        raise EntityVerdictError(f"--{flag} requires a date")
    basis_name = str(basis).strip() if basis is not None else "stated"
    if basis_name not in chronology.BASES:
        raise EntityVerdictError(
            f"--{flag}-basis must be one of {', '.join(chronology.BASES)}")
    record = chronology.parse_edtf(text, basis=basis_name)
    if record is None:
        raise EntityVerdictError(f"--{flag} is not a date I can read: {text!r}")
    return chronology.normalized_date(record.to_dict())


def _preferred_date(existing: object, incoming: object) -> object:
    """Which of two claims for the same person-date the roster keeps.

    **Derived never overwrites stated.** A `born` the person stated outright
    must not lose to one some later pass inferred from an anchor, an age
    statement or an ordering — those are the cheapest claims in the vault and
    they arrive on every refresh, so "last writer wins" would quietly erode
    the best fact on the entry.

    **Same-basis update wins by recency.** Two claims of equal support are the
    person correcting themself (or a better-corroborated re-statement of the
    same fact), and the newer one is the one they meant.

    The strength order is not re-typed here: it is `chronology.claim_score`,
    the package's one definition of how well-supported a dating claim is
    (basis weight + confidence weight + consilience). Incoming wins on a tie,
    which is exactly the recency rule; a strictly weaker incoming claim is
    dropped.
    """
    if incoming is None:
        return existing
    if existing is None:
        return incoming
    return incoming if chronology.claim_score(incoming) >= chronology.claim_score(existing) \
        else existing


def _points_at(entity: dict, slug: str) -> bool:
    """A pointer row (a folded duplicate) whose ``folded_into`` names
    ``slug`` — the same identity as ``slug``, never a rival claimant (v386:
    a row that merely shares a Focus is a different record)."""
    return bool(slug) and ir.folded_into_of(entity) == slug


def _decided_aliases(entity_type: str, entities: Sequence[dict], entry: dict,
                     additions: Sequence[str], *, same_identity: Sequence[dict] = ()) -> list[str]:
    """``entry``'s alias list after ``additions``, every one decided by
    `roster_relations.alias_decision` (v383, ADR 0041 — the collision rule).

    Nothing is mutated: the caller writes the returned list only once EVERY
    alias of the verdict has been decided, so a refusal leaves no partial
    union. The entry's own canonical name is never added as an alias of
    itself. Rows that are the SAME identity are not rival claimants and are
    left out of the collision snapshot: ``same_identity`` (the loser of the
    fold in flight, or its survivor) and any pointer row already folded into
    ``entry``. Raises :class:`EntityAliasContested` on a collision; an alias
    already present is an idempotent success.
    """
    slug = str(entry.get("slug") or "").strip()
    excluded = {id(e) for e in same_identity}
    snapshot = {"entities": [
        e for e in entities
        if isinstance(e, dict) and (e is entry or (id(e) not in excluded and not _points_at(e, slug)))
    ]}
    ref = roster_relations.entity_ref(entity_type, entry)
    canonical = ir.normalized_mention_key(entry.get("name"))
    for raw in additions:
        alias = str(raw or "").strip()
        if not alias or ir.normalized_mention_key(alias) == canonical:
            continue
        decision = roster_relations.alias_decision(entity_type, ref, alias, snapshot)
        if decision.get("applied"):
            snapshot = decision["snapshot"]
            continue
        if decision.get("reason") == roster_relations.IDENTITY_UNCERTAIN_KIND:
            raise EntityAliasContested({**decision, "alias": alias})
        raise EntityVerdictError(f"alias {alias!r} refused: {decision.get('reason')}")
    decided = roster_relations.find_by_ref(entity_type, snapshot, ref) or entry
    return [str(a) for a in decided.get("aliases") or () if str(a or "").strip()]


#: v202 (family-landmark §D): the entry `ensure` creates for a person the
#: roster has never heard of. `qualifies` and `page_eligible` are False ON
#: PURPOSE — ADR 0013 put a >=1-mention floor on graduated pages, and a brother
#: named once in an intake answer has not earned a wiki page. The row exists to
#: hold the SETTLED IDENTITY facts (`entity_roster._SETTLED_IDENTITY_FIELDS`)
#: durably from day one; `entity_roster.apply_previous_decisions` folds it into
#: the real entry by name/alias the moment they are actually mentioned.
ENSURED_SOURCE = "landmark:family"


def _ensured_entry(slug: str, name: str | None) -> dict:
    return {
        "name": (name or slug.replace("-", " ")).strip(),
        "slug": slug,
        "aliases": [],
        "qualifies": False,
        "score": 0.0,
        "unique_answers": 0,
        "page_eligible": False,
        "focus": None,
        "folded_into": None,
        "source": ENSURED_SOURCE,
    }


def apply_verdict(entity_type: str, slug: str, verdict: str, *,
                  aliases: Sequence[str] = (),
                  relationship: str | None = None,
                  living: bool | None = None,
                  born: object = None,
                  born_basis: object = None,
                  died: object = None,
                  died_basis: object = None,
                  maps_to: str | None = None,
                  ensure: bool = False,
                  name: str | None = None,
                  grandparent_side: str | None = None,
                  relation_word: str | None = None,
                  fold_into: str | None = None,
                  focus: str | None = None,
                  retract_aliases: Sequence[str] = (),
                  share_alias: str | None = None,
                  shared_with: str | None = None,
                  located_in: str | None = None,
                  handle: str | None = None,
                  clear_handle: bool = False) -> dict:
    """Apply one verdict — and, since v190, one round of identity facts — to
    one roster entity, atomically. Returns the entity's post-verdict record
    (the same dict object written to disk). Raises `EntityVerdictError` on
    refusal — nothing is written in that case.

    Every identity argument is optional and defaults to "unchanged", so a
    pre-v190 three-argument call behaves exactly as it did. The whole call is
    ONE roster write, and re-running the identical call converges to the
    identical roster bytes.

    v360 (owner, 2026-09-25) (the person form): ``grandparent_side``
    (``maternal``/``paternal``, or ``""`` to clear — `entity_roster
    .GRANDPARENT_SIDE_FIELD`, the field the side card asks for) and
    ``relation_word`` (the word he calls them by — "Grandpa", "Mom"; ``""``
    clears) ride the same one write. Both are settled identity fields a
    refresh keeps."""
    if entity_type not in ENTITY_TYPES:
        raise EntityVerdictError(
            f"unknown entity type: {entity_type!r} (known: {', '.join(ENTITY_TYPES)})")
    if verdict not in VERDICTS:
        raise EntityVerdictError(f"unknown verdict: {verdict!r} (graduate|never|clear)")
    aliases, relationship, living = _validated_identity(aliases, relationship, living)
    # v217: both person dates are parsed BEFORE any read, so an unreadable
    # date refuses the whole call and leaves the roster untouched.
    dates = {
        "born": parse_person_date("born", born, born_basis),
        "died": parse_person_date("died", died, died_basis),
    }
    if grandparent_side is not None:
        grandparent_side = str(grandparent_side).strip().casefold()
        if grandparent_side not in GRANDPARENT_SIDES + ("",):
            raise EntityVerdictError(
                f"grandparent side must be one of {', '.join(GRANDPARENT_SIDES)}")
    if relation_word is not None:
        relation_word = " ".join(str(relation_word).split())[:40]
    fold_into = str(fold_into).strip() if fold_into is not None else None
    focus = str(focus).strip() if focus is not None else None
    maps_to = str(maps_to).strip() if maps_to is not None else None
    if maps_to == "":
        raise EntityVerdictError("--maps-to requires a slug")
    if fold_into == "":
        raise EntityVerdictError("--fold-into requires a row slug")
    if focus == "":
        raise EntityVerdictError("--focus requires a Focus slug")
    if fold_into is not None and focus is not None:
        raise EntityVerdictError("--fold-into and --focus are different acts — pass one")
    if slug in (maps_to, fold_into):
        raise EntityVerdictError(f"refusing: {slug!r} cannot fold into itself")
    if share_alias is not None and not str(shared_with or "").strip():
        raise EntityVerdictError("--share-alias needs --with (who else answers to it)")
    if located_in is not None and entity_type != "place":
        raise EntityVerdictError("--located-in is a place join (place rows only)")

    path, data = read_roster_payload(entity_type)
    entities = data.get("entities") if isinstance(data, dict) else None
    if not isinstance(entities, list):
        if not ensure:
            raise EntityVerdictError(
                f"no {entity_type} roster on disk yet — run entity-roster first")
        data = {"version": 1, "type": entity_type, "entities": []}
        entities = data["entities"]

    target = None
    for entity in entities:
        if isinstance(entity, dict) and entity.get("slug") == slug:
            target = entity
            break
    if target is None and ensure:
        # v202: a person the LANDMARK SET just named may legitimately have no
        # roster row yet — the roster is derived from answer mentions, and an
        # intake answer that names a brother is the first time we have heard
        # of him. Creating the row is the only way the relationship fact has
        # anywhere durable to live; it does NOT create a page (see
        # `_ensured_entry`). Idempotent: a second identical call finds the row.
        target = _ensured_entry(slug, name)
        entities.append(target)
    if target is None:
        known = ", ".join(sorted(
            str(e.get("slug", "")) for e in entities
            if isinstance(e, dict) and e.get("slug")))
        raise EntityVerdictError(f"no such {entity_type}: {slug!r} (known: {known or 'none'})")

    # v386 (ADR 0043): the legacy `--maps-to` is rewritten into the act it
    # meant — a row slug folds, anything else attaches a Focus.
    if maps_to is not None:
        if any(isinstance(e, dict) and e.get("slug") == maps_to and e is not target
               for e in entities):
            fold_into = maps_to
        else:
            focus = maps_to

    # The pure, per-alias acts first — retract, share, handle, located_in — so
    # a refusal leaves the file untouched.
    snapshot = {"entities": entities}
    ref = roster_relations.entity_ref(entity_type, target)
    for alias in retract_aliases or ():
        result = roster_relations.retract_alias(entity_type, ref, alias, snapshot)
        if not result.get("applied"):
            raise EntityVerdictError(f"--retract-alias {alias!r} refused: {result.get('reason')}")
        snapshot = result["snapshot"]
    if share_alias is not None:
        result = roster_relations.share_alias(entity_type, ref, share_alias, shared_with, snapshot)
        if not result.get("applied"):
            if result.get("reason") == roster_relations.IDENTITY_UNCERTAIN_KIND:
                raise EntityAliasContested({**result, "alias": share_alias})
            raise EntityVerdictError(f"--share-alias refused: {result.get('reason')}")
        snapshot = result["snapshot"]
    if handle is not None and clear_handle:
        raise EntityVerdictError("--handle and --clear-handle are different acts — pass one")
    if handle is not None:
        # v390 (§4.1.4b): a handle is lowercase letters, digits and hyphens, and
        # unique across EVERY roster's names, aliases, slugs and handles — the
        # claimant is named and nothing is written.
        handle_text = identity_handles.normalize_handle(handle)
        if not handle_text:
            raise EntityVerdictError(
                f"invalid handle {str(handle)!r}: lowercase letters, digits and "
                f"hyphens, up to {identity_handles.HANDLE_MAX_LENGTH} characters")
        rosters = {t: (snapshot if t == entity_type else read_roster_payload(t)[1])
                   for t in ENTITY_TYPES}
        colliders = identity_handles.claimants(handle_text, rosters,
                                               exclude=(entity_type, slug))
        if colliders:
            raise EntityAliasContested(identity_handles.refusal(
                handle_text, ref, str(target.get("name") or slug), colliders))
        result = roster_relations.alias_decision(entity_type, ref, handle_text,
                                                 snapshot, handle=True)
        if not result.get("applied"):
            if result.get("reason") == roster_relations.IDENTITY_UNCERTAIN_KIND:
                raise EntityAliasContested({**result, "alias": handle_text})
            raise EntityVerdictError(f"--handle refused: {result.get('reason')}")
        snapshot = result["snapshot"]
    if clear_handle:
        entities_now = [identity_handles.without_handle(e) if e.get("slug") == slug else e
                        for e in snapshot["entities"] if isinstance(e, dict)]
        snapshot = {**snapshot, "entities": entities_now}
    if located_in is not None:
        parent_slug = located_in.split("/", 1)[-1] if located_in.startswith("place/") else located_in
        parent = next((e for e in snapshot["entities"] if e.get("slug") == parent_slug), None)
        if parent is None or parent_slug == slug:
            raise EntityVerdictError(f"refusing: --located-in {located_in!r} names no other place")
        parent_ref = roster_relations.entity_ref("place", parent)
        if ref in roster_relations.located_in_chain(parent_ref, snapshot) or parent_ref == ref:
            raise EntityVerdictError("refusing: that containment would be a cycle")
        snapshot = roster_relations.located_in(ref, parent_ref, snapshot)
    if snapshot["entities"] is not entities:
        entities = [e for e in snapshot["entities"]]
        data["entities"] = entities
        target = next(e for e in entities if isinstance(e, dict) and e.get("slug") == slug)

    if fold_into is None and focus is None and verdict == "graduate" and ir.has_home(target):
        raise EntityVerdictError(
            f"refusing: {slug!r} already has a home ({ir.roster_home(target)!r}) — "
            "graduate is refused on an entity with a Focus or a fold (it already has a page there)")

    # The fold target must exist before anything is written: another entity in
    # THIS roster. A Focus target must be a known Focus that no OTHER record
    # already holds (v386 — one person, one record: never a twin).
    merge_into = None
    if fold_into is not None:
        merge_into = next(
            (e for e in entities
             if isinstance(e, dict) and e.get("slug") == fold_into and e is not target),
            None,
        )
        if merge_into is None:
            raise EntityVerdictError(
                f"refusing: --fold-into {fold_into!r} names no other {entity_type} on this roster")
        if ir.is_alias_row(merge_into):
            raise EntityVerdictError(
                f"refusing: {fold_into!r} is itself folded into {ir.folded_into_of(merge_into)!r} — "
                "fold into the survivor")
        if entity_type == "place":
            reason = roster_relations.place_fold_refusal(target, merge_into, {"entities": entities})
            if reason:
                raise EntityVerdictError(f"refusing: {reason}")
        if ir.focus_of(target) and ir.focus_of(merge_into) and \
                ir.focus_of(target) != ir.focus_of(merge_into):
            raise EntityVerdictError(
                "refusing: both records have a Focus — merge the Focuses first (focus-merge)")
    if focus is not None:
        if focus not in _focus_map():
            raise EntityVerdictError(f"refusing: --focus {focus!r} is not a known Focus slug")
        twin = next((e for e in entities if isinstance(e, dict) and e is not target
                     and not ir.is_alias_row(e) and ir.focus_of(e) == focus), None)
        if twin is not None:
            raise EntityVerdictError(
                f"refusing: Focus {focus!r} already attends to {twin.get('slug')!r} — "
                f"fold {slug!r} into it instead (one person, one record)")

    # v383 (ADR 0041): every alias this verdict writes is DECIDED first, by the
    # package's one collision rule, before anything is mutated — a contested
    # alias refuses the whole verdict and the roster file stays untouched.
    fold_peers = (merge_into,) if merge_into is not None else ()
    target_aliases = (
        _decided_aliases(entity_type, entities, target, aliases, same_identity=fold_peers)
        if aliases else None)
    survivor_aliases = None
    if merge_into is not None:
        loser_names = [str(target.get("name") or "").strip(),
                       *(target_aliases if target_aliases is not None
                         else [str(a or "").strip() for a in target.get("aliases", [])])]
        survivor_aliases = _decided_aliases(
            entity_type, entities, merge_into, loser_names, same_identity=(target,))

    # Identity facts first — they apply whatever the verdict is.
    if target_aliases is not None:
        target["aliases"] = target_aliases
    if relationship is not None:
        target["relationship"] = relationship
    if living is not None:
        target["living"] = living
    for field_name, value in ((GRANDPARENT_SIDE_FIELD, grandparent_side),
                              (RELATION_WORD_FIELD, relation_word)):
        if value is None:
            continue
        if value:
            target[field_name] = value
        else:
            target.pop(field_name, None)
    # v217 (person dates): derived never overwrites stated; a same-basis
    # restatement wins by recency. `_preferred_date` is the whole rule.
    for date_field in PERSON_DATE_FIELDS:
        chosen = _preferred_date(target.get(date_field), dates[date_field])
        if chosen is not None:
            target[date_field] = chosen

    if fold_into is not None or focus is not None:
        # A fold or a Focus WINS over graduate (module docstring): the record
        # already has a home, so the graduation is skipped rather than the
        # whole call failing. `apply_owner_verdict` and `base_page_eligible`
        # both make a home beat `graduate` continuously anyway.
        target.pop("maps_to_focus", None)
        if focus is not None:
            target["focus"] = focus
            target.setdefault("folded_into", None)
        else:
            target["folded_into"] = fold_into
            if ir.focus_of(target) and not ir.focus_of(merge_into):
                merge_into["focus"] = ir.focus_of(target)
            target["focus"] = None
        if merge_into is not None and survivor_aliases is not None:
            # The merge lives on the SURVIVOR: the loser's canonical name and
            # every alias fold into the target's aliases, which is exactly how
            # `wiki_compile.plan_entities` (matching `[name] + aliases`) and
            # `entity_roster.apply_previous_decisions` (folding by
            # `_entity_keys`) already express "this is really that page".
            # The loser KEEPS its row as a pointer (`folded_into` above) —
            # a fold is never a deletion (ADR 0012's shape, ADR 0041).
            merge_into["aliases"] = survivor_aliases
        if verdict == "never":
            target["owner_verdict"] = "never"
        elif verdict == "clear":
            target.pop("owner_verdict", None)
        min_score, min_answers = THRESHOLDS.get(entity_type, (8.0, 2))
        target["page_eligible"] = base_page_eligible(
            entity_type, bool(target.get("qualifies")), ir.roster_home(target),
            float(target.get("score", 0.0) or 0.0), int(target.get("unique_answers", 0) or 0),
            min_score, min_answers)
        apply_owner_verdict(entity_type, target)
        write_json(path, data)
        return target

    if verdict == "clear":
        target.pop("owner_verdict", None)
        min_score, min_answers = THRESHOLDS.get(entity_type, (8.0, 2))
        target["page_eligible"] = base_page_eligible(
            entity_type, bool(target.get("qualifies")), ir.roster_home(target),
            float(target.get("score", 0.0) or 0.0), int(target.get("unique_answers", 0) or 0),
            min_score, min_answers)
    else:
        target["owner_verdict"] = verdict
        apply_owner_verdict(entity_type, target)

    write_json(path, data)
    return target


def attach_focus(slug: str, focus_slug: str) -> dict:
    """v386 (ADR 0043): attach Focus ``focus_slug`` to the person record
    ``slug`` — the one write `roadmap.focus_new`/`approve_recommendation` make
    when a Focus is created for a person. The record stays a live person;
    ``page_eligible`` is recomputed (its page is now the Focus's). Idempotent.
    Refuses a twin: a Focus another live record already holds. Unlike
    :func:`apply_verdict` it does not consult the bank's Focus list, because
    the caller has just created the Focus."""
    path, data = read_roster_payload("person")
    entities = (data or {}).get("entities") or []
    target = next((e for e in entities if isinstance(e, dict) and e.get("slug") == slug), None)
    if target is None:
        raise EntityVerdictError(f"no such person: {slug!r}")
    if ir.is_alias_row(target):
        raise EntityVerdictError(f"refusing: {slug!r} is folded into {ir.folded_into_of(target)!r}")
    twin = next((e for e in entities if isinstance(e, dict) and e is not target
                 and not ir.is_alias_row(e) and ir.focus_of(e) == focus_slug), None)
    if twin is not None:
        raise EntityVerdictError(
            f"refusing: Focus {focus_slug!r} already attends to {twin.get('slug')!r}")
    if ir.focus_of(target) == focus_slug and "maps_to_focus" not in target:
        return target
    target.pop("maps_to_focus", None)
    target["focus"] = focus_slug
    target.setdefault("folded_into", None)
    min_score, min_answers = THRESHOLDS.get("person", (8.0, 2))
    target["page_eligible"] = base_page_eligible(
        "person", bool(target.get("qualifies")), ir.roster_home(target),
        float(target.get("score", 0.0) or 0.0), int(target.get("unique_answers", 0) or 0),
        min_score, min_answers)
    apply_owner_verdict("person", target)
    write_json(path, data)
    return target


IDENTITY_FLAG_DESTS = ("fold_into", "focus", "retract_alias", "share_alias",
                       "shared_with", "located_in", "handle", "clear_handle")


def add_identity_flags(parser: argparse.ArgumentParser) -> None:
    """The identity-edit flags (I-1, v387) — ONE definition for BOTH doors:
    this module's own CLI and `lifehug.py entity-verdict` (v396). A flag added
    here reaches both; `cmd_entity_verdict` forwards by `IDENTITY_FLAG_DESTS`."""
    parser.add_argument("--fold-into", dest="fold_into", metavar="ROW",
                        help="This record is a duplicate of that row: keep it as a "
                             "pointer, union its names onto the survivor (ADR 0041). "
                             "Wins over graduate. Refused for a place unless both "
                             "are true duplicates (use --located-in).")
    parser.add_argument("--focus", metavar="FOCUS",
                        help="Attach this record to that Focus (the Focus attends to "
                             "this person; the record stays live). Refused when "
                             "another record already holds the Focus.")
    parser.add_argument("--retract-alias", dest="retract_alias", action="append",
                        default=[], metavar="NAME",
                        help="Take a name back off this record (repeatable)")
    parser.add_argument("--share-alias", dest="share_alias", metavar="NAME",
                        help="Mark a name as shared with somebody who has no record "
                             "(needs --with): a bare mention of it is held, never "
                             "attributed; nobody is minted (D9)")
    parser.add_argument("--with", dest="shared_with", metavar="WHO",
                        help="With --share-alias: who else answers to it, free text "
                             "(\"a friend (no record)\")")
    parser.add_argument("--located-in", dest="located_in", metavar="PLACE",
                        help="place only: this place is inside that place "
                             "(containment, never a fold — D8)")
    parser.add_argument("--handle", metavar="HANDLE",
                        help="The record's short @handle: lowercase letters, digits and "
                             "hyphens, unique across every record's name, alias, slug and "
                             "handle in the vault (refused, exit 2, naming the claimant)")
    parser.add_argument("--clear-handle", dest="clear_handle", action="store_true",
                        help="Remove the short @handle (the @<slug> handle stays)")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Owner override for one roster entity's graduation — "
                    "graduate now, never a page, or clear back to automatic (ADR 0013).")
    parser.add_argument("type", choices=ENTITY_TYPES)
    parser.add_argument("slug", help="The roster entity's slug (state/entity_rosters/<type>.json)")
    parser.add_argument("verdict", choices=VERDICTS)
    parser.add_argument("--alias", action="append", default=[], metavar="NAME",
                        help="Another name this entity goes by (repeatable); "
                             "unioned into the roster entry's aliases")
    parser.add_argument("--relationship", metavar="R",
                        help="How this person is related to the author "
                             "(focus_candidate.FOCUS_RELATIONSHIPS)")
    living = parser.add_mutually_exclusive_group()
    living.add_argument("--living", dest="living", action="store_true", default=None,
                        help="This person is still living")
    living.add_argument("--not-living", dest="living", action="store_false",
                        help="This person is no longer living")
    parser.add_argument("--born", metavar="EDTF",
                        help="When this person was born (EDTF or a human form: "
                             "1948, 1948-03, spring 1948, about 1948)")
    parser.add_argument("--born-basis", metavar="B", default=None,
                        help=f"How the birth date was arrived at "
                             f"({', '.join(chronology.BASES)}; default stated)")
    parser.add_argument("--died", metavar="EDTF",
                        help="When this person died (same date forms as --born)")
    parser.add_argument("--died-basis", metavar="B", default=None,
                        help=f"How the death date was arrived at "
                             f"({', '.join(chronology.BASES)}; default stated)")
    parser.add_argument("--maps-to", metavar="SLUG",
                        help="DEPRECATED (v386, one version): rewritten to "
                             "--fold-into when SLUG is a row, else --focus.")
    add_identity_flags(parser)
    parser.add_argument("--ensure", action="store_true",
                        help="Create the roster entry when the slug is unknown, "
                             "rather than refusing — for a person a LANDMARK "
                             "named (v202). Never page-eligible on creation.")
    parser.add_argument("--name", metavar="NAME",
                        help="With --ensure: the person's name on the created entry")
    parser.add_argument("--grandparent-side", dest="grandparent_side", default=None,
                        help="maternal|paternal (empty clears) — whose side a "
                             "grandparent is on")
    parser.add_argument("--relation-word", dest="relation_word", default=None,
                        help="The word the owner calls this person by (Grandpa, Mom)")
    parser.add_argument("--json", action="store_true", help="Print the result as JSON")
    args = parser.parse_args(argv)
    if args.maps_to is not None:
        print("⚠ entity-verdict: --maps-to is deprecated (v386, ADR 0043) — rewritten to "
              "--fold-into when it names a row, else --focus; use those", file=sys.stderr)

    try:
        entity = apply_verdict(
            args.type, args.slug, args.verdict,
            aliases=args.alias, relationship=args.relationship,
            living=args.living,
            born=args.born, born_basis=args.born_basis,
            died=args.died, died_basis=args.died_basis,
            maps_to=args.maps_to,
            ensure=args.ensure, name=args.name,
            grandparent_side=args.grandparent_side,
            relation_word=args.relation_word,
            fold_into=args.fold_into, focus=args.focus,
            retract_aliases=args.retract_alias,
            share_alias=args.share_alias, shared_with=args.shared_with,
            located_in=args.located_in, handle=args.handle,
            clear_handle=args.clear_handle,
        )
    except EntityAliasContested as exc:
        # v383 (ADR 0041): the package's own refusal, verbatim, on stdout —
        # both claimants named — so a host renders them and asks.
        print(json.dumps(exc.result, indent=2, ensure_ascii=False, sort_keys=True))
        print(f"✗ entity-verdict: {exc}", file=sys.stderr)
        return EXIT_IDENTITY_UNCERTAIN
    except EntityVerdictError as exc:
        print(f"✗ entity-verdict: {exc}", file=sys.stderr)
        return 1

    if args.maps_to or args.alias or args.fold_into or args.retract_alias or args.share_alias \
            or args.handle or args.clear_handle:
        # v383 (ADR 0041): a fold or an alias moves mention counts; the
        # keyless recount makes that visible on the next read instead of at
        # the next monthly model call. Deterministic, no model.
        from entity_roster import recount  # noqa: PLC0415
        recounted = recount(args.type)
        entity = next((e for e in recounted["entities"] if e.get("slug") == args.slug), entity)

    if args.json:
        print(json.dumps(entity, indent=2, ensure_ascii=False))
        return 0

    verb = {
        "graduate": "graduated (owner override)",
        "never": "vetoed — never a page (owner override)",
        "clear": "cleared to automatic",
    }[args.verdict]
    home = ir.roster_home(entity)
    if args.maps_to or args.fold_into or args.focus:
        verb = (f"folded into {ir.folded_into_of(entity)} (owner override)" if ir.folded_into_of(entity)
                else f"attached to Focus {ir.focus_of(entity)} (owner override)")
    eligible = "eligible" if entity.get("page_eligible") else "not eligible"
    print(f"✓ {args.type}/{args.slug} {verb} — page_eligible: {eligible}")
    if (args.maps_to or args.fold_into or args.focus) and args.verdict == "graduate":
        print(f"  note: graduate superseded by {home} — "
              "the record already has a home there")
    learned = []
    if args.alias:
        learned.append(f"aliases: {', '.join(entity.get('aliases', []))}")
    if args.relationship:
        learned.append(f"relationship: {entity['relationship']}")
    if args.living is not None:
        learned.append(f"living: {'yes' if entity['living'] else 'no'}")
    for flag, field in (("born", "born"), ("died", "died")):
        if getattr(args, flag, None) and entity.get(field):
            learned.append(
                f"{field}: {chronology.display_date(entity[field], with_basis=False)}")
    if args.handle or args.clear_handle:
        learned.append(f"handle: {identity_handles.handle_for(entity)}")
    if learned:
        print(f"  identity — {'; '.join(learned)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
