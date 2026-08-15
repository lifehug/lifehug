#!/usr/bin/env python3
"""Lifehug — `entity-verdict`, the owner's graduation accelerator/veto (ADR 0013).

The entity-candidates lane graduates entities into wiki pages fully
automatically (the Convergence Principle's floor, ADR 0006 — untouched by
this module). This is the accelerator half: two settled overrides the owner
can stamp on any roster entity, mirroring the focus lane's dismiss-forever
and the candidate lane's promote-override.

    entity-verdict <type> <slug> graduate|never|clear

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

Usage:
    python3 system/entity_verdict.py person betty-jo graduate
    python3 system/entity_verdict.py object the-orange-cone never --json
    python3 system/entity_verdict.py place old-house clear
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

SYSTEM_DIR = Path(__file__).resolve().parent
if str(SYSTEM_DIR) not in sys.path:
    sys.path.insert(0, str(SYSTEM_DIR))

from entity_roster import (  # noqa: E402
    ENTITY_TYPES,
    THRESHOLDS,
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


def apply_verdict(entity_type: str, slug: str, verdict: str) -> dict:
    """Apply one verdict to one roster entity, atomically. Returns the
    entity's post-verdict record (the same dict object written to disk).
    Raises `EntityVerdictError` on refusal — nothing is written in that
    case."""
    if entity_type not in ENTITY_TYPES:
        raise EntityVerdictError(
            f"unknown entity type: {entity_type!r} (known: {', '.join(ENTITY_TYPES)})")
    if verdict not in VERDICTS:
        raise EntityVerdictError(f"unknown verdict: {verdict!r} (graduate|never|clear)")

    path = roster_file(entity_type)
    data = read_json(path, default=None)
    entities = data.get("entities") if isinstance(data, dict) else None
    if not isinstance(entities, list):
        raise EntityVerdictError(
            f"no {entity_type} roster on disk yet — run entity-roster first")

    target = None
    for entity in entities:
        if isinstance(entity, dict) and entity.get("slug") == slug:
            target = entity
            break
    if target is None:
        known = ", ".join(sorted(
            str(e.get("slug", "")) for e in entities
            if isinstance(e, dict) and e.get("slug")))
        raise EntityVerdictError(f"no such {entity_type}: {slug!r} (known: {known or 'none'})")

    if verdict == "graduate" and target.get("maps_to_focus"):
        raise EntityVerdictError(
            f"refusing: {slug!r} already maps to Focus {target['maps_to_focus']!r} — "
            "graduate is refused on a mapped entity (it already has a home there)")

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
    parser.add_argument("--json", action="store_true", help="Print the result as JSON")
    args = parser.parse_args(argv)

    try:
        entity = apply_verdict(args.type, args.slug, args.verdict)
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
    eligible = "eligible" if entity.get("page_eligible") else "not eligible"
    print(f"✓ {args.type}/{args.slug} {verb} — page_eligible: {eligible}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
