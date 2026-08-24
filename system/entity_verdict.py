#!/usr/bin/env python3
"""Lifehug — `entity-verdict`, the owner's graduation accelerator/veto (ADR 0013).

The entity-candidates lane graduates entities into wiki pages fully
automatically (the Convergence Principle's floor, ADR 0006 — untouched by
this module). This is the accelerator half: two settled overrides the owner
can stamp on any roster entity, mirroring the focus lane's dismiss-forever
and the candidate lane's promote-override.

    entity-verdict <type> <slug> graduate|never|clear
        [--alias A]... [--relationship R] [--living|--not-living] [--maps-to SLUG]
        [--ensure [--name NAME]]

  - `graduate` — an entity the owner knows matters shouldn't have to wait
    for its second mention: `page_eligible` is forced true regardless of
    score/answer thresholds (the entity must still be UNMAPPED —
    `maps_to_focus` wins; refused on a mapped entity, which already has a
    home), and `wiki_compile.plan_entities`'s real-mention bar drops to >= 1
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

from entity_roster import (  # noqa: E402
    ENTITY_TYPES,
    THRESHOLDS,
    _focus_map,
    apply_owner_verdict,
    base_page_eligible,
    roster_file,
)
from lifehug_core import read_json, write_json  # noqa: E402

VERDICTS = ("graduate", "never", "clear")


class EntityVerdictError(ValueError):
    """A verdict that must not apply — unknown type/slug, or `graduate` on
    a mapped entity. Always raised BEFORE any write: a refused verdict
    leaves the roster file byte-for-byte unchanged."""


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


def _union_aliases(entry: dict, additions: Sequence[str]) -> None:
    """Union `additions` into `entry["aliases"]` in place — trimmed, order
    preserved, deduplicated case-insensitively, and never the entry's own
    canonical name. Idempotent: a second identical call is a no-op."""
    canonical = str(entry.get("name") or "").strip().lower()
    existing = [str(a or "").strip() for a in entry.get("aliases", []) if str(a or "").strip()]
    seen = {a.lower() for a in existing} | {canonical}
    for alias in additions:
        if alias.lower() in seen:
            continue
        seen.add(alias.lower())
        existing.append(alias)
    entry["aliases"] = existing


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
        "maps_to_focus": None,
        "source": ENSURED_SOURCE,
    }


def apply_verdict(entity_type: str, slug: str, verdict: str, *,
                  aliases: Sequence[str] = (),
                  relationship: str | None = None,
                  living: bool | None = None,
                  maps_to: str | None = None,
                  ensure: bool = False,
                  name: str | None = None) -> dict:
    """Apply one verdict — and, since v190, one round of identity facts — to
    one roster entity, atomically. Returns the entity's post-verdict record
    (the same dict object written to disk). Raises `EntityVerdictError` on
    refusal — nothing is written in that case.

    Every identity argument is optional and defaults to "unchanged", so a
    pre-v190 three-argument call behaves exactly as it did. The whole call is
    ONE roster write, and re-running the identical call converges to the
    identical roster bytes."""
    if entity_type not in ENTITY_TYPES:
        raise EntityVerdictError(
            f"unknown entity type: {entity_type!r} (known: {', '.join(ENTITY_TYPES)})")
    if verdict not in VERDICTS:
        raise EntityVerdictError(f"unknown verdict: {verdict!r} (graduate|never|clear)")
    aliases, relationship, living = _validated_identity(aliases, relationship, living)
    maps_to = str(maps_to).strip() if maps_to is not None else None
    if maps_to == "":
        raise EntityVerdictError("--maps-to requires a slug")
    if maps_to is not None and maps_to == slug:
        raise EntityVerdictError(f"refusing: {slug!r} cannot map to itself")

    path = roster_file(entity_type)
    data = read_json(path, default=None)
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

    if maps_to is None and verdict == "graduate" and target.get("maps_to_focus"):
        raise EntityVerdictError(
            f"refusing: {slug!r} already maps to Focus {target['maps_to_focus']!r} — "
            "graduate is refused on a mapped entity (it already has a home there)")

    # The merge target must exist before anything is written: another entity
    # in THIS roster, or a known Focus slug. A typo must never produce a
    # dangling map.
    merge_into = None
    if maps_to is not None:
        merge_into = next(
            (e for e in entities
             if isinstance(e, dict) and e.get("slug") == maps_to and e is not target),
            None,
        )
        if merge_into is None and maps_to not in _focus_map():
            raise EntityVerdictError(
                f"refusing: --maps-to {maps_to!r} names neither another {entity_type} "
                "on this roster nor a known Focus slug")

    # Identity facts first — they apply whatever the verdict is.
    if aliases:
        _union_aliases(target, aliases)
    if relationship is not None:
        target["relationship"] = relationship
    if living is not None:
        target["living"] = living

    if maps_to is not None:
        # maps-to WINS over graduate (module docstring): a mapped entity
        # already has a home, so the graduation is skipped rather than the
        # whole call failing. An owner_verdict already on the record is left
        # alone; `apply_owner_verdict` and `base_page_eligible` both make
        # `maps_to_focus` beat `graduate` continuously anyway.
        target["maps_to_focus"] = maps_to
        if merge_into is not None:
            # The merge lives on the SURVIVOR: the loser's canonical name and
            # every alias fold into the target's aliases, which is exactly how
            # `wiki_compile.plan_entities` (matching `[name] + aliases`) and
            # `entity_roster.apply_previous_decisions` (folding by
            # `_entity_keys`) already express "this is really that page".
            _union_aliases(
                merge_into,
                [str(target.get("name") or "").strip(),
                 *[str(a or "").strip() for a in target.get("aliases", [])]],
            )
        if verdict == "never":
            target["owner_verdict"] = "never"
        elif verdict == "clear":
            target.pop("owner_verdict", None)
        min_score, min_answers = THRESHOLDS.get(entity_type, (8.0, 2))
        target["page_eligible"] = base_page_eligible(
            entity_type, bool(target.get("qualifies")), target.get("maps_to_focus"),
            float(target.get("score", 0.0) or 0.0), int(target.get("unique_answers", 0) or 0),
            min_score, min_answers)
        apply_owner_verdict(entity_type, target)
        write_json(path, data)
        return target

    if verdict == "clear":
        target.pop("owner_verdict", None)
        min_score, min_answers = THRESHOLDS.get(entity_type, (8.0, 2))
        target["page_eligible"] = base_page_eligible(
            entity_type, bool(target.get("qualifies")), target.get("maps_to_focus"),
            float(target.get("score", 0.0) or 0.0), int(target.get("unique_answers", 0) or 0),
            min_score, min_answers)
    else:
        target["owner_verdict"] = verdict
        apply_owner_verdict(entity_type, target)

    write_json(path, data)
    return target


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
    parser.add_argument("--maps-to", metavar="SLUG",
                        help="This entity is really that existing page — another "
                             "entity on this roster, or a Focus slug. Wins over "
                             "graduate in the same call.")
    parser.add_argument("--ensure", action="store_true",
                        help="Create the roster entry when the slug is unknown, "
                             "rather than refusing — for a person a LANDMARK "
                             "named (v202). Never page-eligible on creation.")
    parser.add_argument("--name", metavar="NAME",
                        help="With --ensure: the person's name on the created entry")
    parser.add_argument("--json", action="store_true", help="Print the result as JSON")
    args = parser.parse_args(argv)

    try:
        entity = apply_verdict(
            args.type, args.slug, args.verdict,
            aliases=args.alias, relationship=args.relationship,
            living=args.living, maps_to=args.maps_to,
            ensure=args.ensure, name=args.name,
        )
    except EntityVerdictError as exc:
        print(f"✗ entity-verdict: {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(entity, indent=2, ensure_ascii=False))
        return 0

    verb = {
        "graduate": "graduated (owner override)",
        "never": "vetoed — never a page (owner override)",
        "clear": "cleared to automatic",
    }[args.verdict]
    if args.maps_to:
        verb = f"mapped to {args.maps_to} (owner override)"
    eligible = "eligible" if entity.get("page_eligible") else "not eligible"
    print(f"✓ {args.type}/{args.slug} {verb} — page_eligible: {eligible}")
    if args.maps_to and args.verdict == "graduate":
        print(f"  note: graduate superseded by --maps-to {args.maps_to} — "
              "a mapped entity already has a home there")
    learned = []
    if args.alias:
        learned.append(f"aliases: {', '.join(entity.get('aliases', []))}")
    if args.relationship:
        learned.append(f"relationship: {entity['relationship']}")
    if args.living is not None:
        learned.append(f"living: {'yes' if entity['living'] else 'no'}")
    if learned:
        print(f"  identity — {'; '.join(learned)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
