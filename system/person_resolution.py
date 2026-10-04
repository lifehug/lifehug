#!/usr/bin/env python3
"""v387 — person resolution for the classifier and the identity listener.

**A THIN ADAPTER, NOT A SECOND RESOLVER.** The identity-unification design
(lifehug-platform#987, `docs/design/identity.md` §4.1.2) gives
`identity_resolution` ONE typed resolver per entity type —
``resolve_person(text, roster, *, context) -> Resolution`` — and a
disambiguated ``display_name(record, roster)`` (v388, ADR 0043). This module
DELEGATES to them; the v387 fallback bodies were deleted at the v388 rebase,
as promised. What stays here is what the two callers (the classifier's "People
you already know" block and post-processor, the general listener's
``person_identity`` list) need on top: the refs-only :class:`Resolution` view
with a ``basis``, the explicit ``@handle`` path (I-4 replaces it with
`identity_resolution.parse_handles`), and the block renderer.

The adapter never guesses: ``ambiguous`` and ``unknown`` pass through.
It is pure: it reads the roster snapshot it is handed and never the disk.
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

SYSTEM_DIR = Path(__file__).resolve().parent
if str(SYSTEM_DIR) not in sys.path:
    sys.path.insert(0, str(SYSTEM_DIR))

import identity_resolution as ir

RESOLVED = "resolved"
AMBIGUOUS = "ambiguous"
UNKNOWN = "unknown"
RESOLUTION_KINDS = (RESOLVED, AMBIGUOUS, UNKNOWN)

#: How a resolution was reached. ``handle`` is an explicit ``@slug`` the
#: person typed (design §4.1.4b) — no model judgement, no fuzzy rung.
BASIS_HANDLE = "handle"
BASIS_STATEMENT = "statement"

#: An explicit reference typed by the person: ``@mara-holt``.
HANDLE_RE = re.compile(r"(?<![\w@])@(?P<handle>[a-z0-9][a-z0-9-]*)", re.IGNORECASE)


@dataclass(frozen=True)
class Resolution:
    """I-1's shape: ``kind`` + the one ``ref`` when resolved + the running."""

    kind: str
    ref: str = ""
    candidates: tuple[str, ...] = field(default=())
    reason: str = ""
    basis: str = BASIS_STATEMENT

    @property
    def resolved(self) -> bool:
        return self.kind == RESOLVED


def _entities(roster: object) -> list[dict]:
    if isinstance(roster, dict):
        rows = roster.get("entities") or ()
    else:
        rows = roster or ()
    return [row for row in rows if isinstance(row, dict)]


def _is_person_row(entity: dict) -> bool:
    """A real, individual person record: not a fold pointer, not a
    placeholder role/collective row ("Son", "Kids")."""
    import relation_words

    if ir.is_alias_row(entity):
        return False
    return not (relation_words.is_role_row(entity)
                or relation_words.is_collective_row(entity))


def person_rows(roster: object) -> list[dict]:
    """Every individual person record, roster order."""
    return [row for row in ir.split_legacy_pointers(_entities(roster)) if _is_person_row(row)]


def ref_of(entity: dict) -> str:
    return ir.entity_ref("person", ir._entity_slug(entity))


def slug_of_ref(ref: object) -> str:
    text = str(ref or "")
    return text.split("/", 1)[1] if "/" in text else text


def _from_upstream(result: ir.Resolution) -> Resolution:
    kind = str(getattr(result, "kind", "") or UNKNOWN)
    ref = str(getattr(result, "ref", "") or "")
    raw = getattr(result, "candidates", ()) or ()
    candidates = tuple(
        str(c.get("ref") if isinstance(c, dict) else getattr(c, "ref", c))
        for c in raw)
    return Resolution(kind if kind in RESOLUTION_KINDS else UNKNOWN, ref,
                      candidates, str(getattr(result, "reason", "") or ""))


# --------------------------------------------------------------------------
# handles — design §4.1.4b (I-4 builds `identity_resolution.parse_handles`)
# --------------------------------------------------------------------------

def parse_handles(text: object) -> tuple[str, ...]:
    """Every ``@handle`` in ``text``, lowercased, in order, deduplicated."""
    upstream = getattr(ir, "parse_handles", None)
    if callable(upstream):
        return tuple(str(h).lstrip("@").casefold() for h in upstream(text))
    body = text if isinstance(text, str) else ""
    return tuple(dict.fromkeys(m.group("handle").casefold()
                               for m in HANDLE_RE.finditer(body)))


def resolve_handle(handle: object, roster: object) -> Resolution:
    """An explicit ``@slug`` — EXACT slug match only, never a fuzzy rung.

    I-4 adds owner-chosen short handles; until then a handle is a slug.
    """
    wanted = str(handle or "").lstrip("@").casefold()
    for entity in person_rows(roster):
        if ir._entity_slug(entity) == wanted:
            return Resolution(RESOLVED, ref_of(entity), (ref_of(entity),),
                              "handle", BASIS_HANDLE)
    return Resolution(UNKNOWN, reason="unknown_handle", basis=BASIS_HANDLE)


# --------------------------------------------------------------------------
# resolve_person — the adapter
# --------------------------------------------------------------------------

def resolve_person(text: object, roster: object, *,
                   context: dict | None = None) -> Resolution:
    """``resolved`` / ``ambiguous`` / ``unknown`` for one person mention —
    `identity_resolution.resolve_person`, viewed as refs.

    A mention that is exactly one ``@handle`` takes the handle path.
    ``context`` may carry ``relationship`` (a relationship WORD said in the
    same clause); it reaches the resolver as that clause ("my <word>"), which
    is how `identity_resolution.ResolveContext` reads a relationship.
    """
    mention = ir.collapsed_text(text)
    handles = parse_handles(mention)
    if handles and mention.lstrip("@").casefold() == handles[0]:
        return resolve_handle(handles[0], roster)
    ctx = dict(context or {})
    word = ir.collapsed_text(ctx.pop("relationship", ""))
    if word and not ctx.get("clause"):
        ctx["clause"] = f"my {word}"
    return _from_upstream(ir.resolve_person(mention, roster, context=ctx or None))


# --------------------------------------------------------------------------
# display_name — D7, colliding names carry a disambiguator
# --------------------------------------------------------------------------

def display_name(record: dict, roster: object) -> str:
    """`identity_resolution.display_name` — the bare name when unique;
    ``Name (relation[, b. YYYY])`` when another person record shares its name
    or given name (design D7)."""
    return ir.display_name(record, roster)


def record_view(record: dict, roster: object) -> dict:
    """`identity_resolution.record_view` — ref, name, display name and the
    handle fields, never inline."""
    return ir.record_view(record, roster)


# --------------------------------------------------------------------------
# the "People you already know" block — one renderer, two prompts
# --------------------------------------------------------------------------

#: Aliases shown per person — the spellings, not the whole history.
KNOWN_PEOPLE_ALIASES = 6

#: The default cap. The classifier passes its own
#: (`classifier_context.KNOWN_PEOPLE_LIMIT`, same number); the listener's
#: haiku-class prompt uses :data:`LISTENER_KNOWN_PEOPLE_LIMIT`.
KNOWN_PEOPLE_LIMIT = 30

#: The listener's cap: the recorder's own known-entries total (21), because
#: the listener prompt is the same small haiku-class pass, and the ORDER
#: (named in this message first, then family) keeps what it cuts irrelevant.
LISTENER_KNOWN_PEOPLE_LIMIT = 21

NO_KNOWN_PEOPLE = "(no people on file yet)"


def _story_key(text: object) -> str:
    return f" {ir.normalized_mention_key(text)} "


def named_in_text(entity: dict, text_key: str) -> bool:
    """Does the (normalized, space-padded) text name this person — any
    spelling whole, or its given name (3+ letters) as a word?"""
    for spelling in (entity.get("name"), *(entity.get("aliases") or ())):
        key = ir.normalized_mention_key(spelling)
        if not key:
            continue
        if f" {key} " in text_key:
            return True
        given = key.split()[0]
        if len(given) >= 3 and f" {given} " in text_key:
            return True
    return False


def person_focus(entity: dict) -> str:
    """The Focus that attends to this person (I-1's ``focus`` field)."""
    return str(entity.get("focus") or "").strip()


def render_known_people(person_roster: object, *, story_text: str = "",
                        limit: int = KNOWN_PEOPLE_LIMIT) -> str:
    """One line per person record, bounded, saying what it hid.

    ``- <display name> — also: <aliases> · <relationship> · focus: <slug>``,
    the display name disambiguated when two records share it (design D7).
    Ordered people-this-text-names first, then family, then everyone else,
    roster order within a tier, so the surviving set is stable. Pure.
    """
    from landmarks_interaction import person_date_relations

    rows = person_rows(person_roster)
    if not rows:
        return NO_KNOWN_PEOPLE
    text_key = _story_key(story_text)
    family = person_date_relations()

    def tier(entity: dict) -> int:
        if text_key.strip() and named_in_text(entity, text_key):
            return 0
        rel = ir.normalized_mention_key(entity.get(ir.ROSTER_RELATIONSHIP_KEY))
        return 1 if rel in family else 2

    ordered = sorted(enumerate(rows), key=lambda pair: (tier(pair[1]), pair[0]))
    lines: list[str] = []
    for _index, entity in ordered[:max(int(limit), 0)]:
        own = ir.normalized_mention_key(entity.get("name"))
        aliases = [str(a).strip() for a in entity.get("aliases") or ()
                   if str(a).strip() and ir.normalized_mention_key(a) != own]
        aliases = list(dict.fromkeys(aliases))[:KNOWN_PEOPLE_ALIASES]
        tail: list[str] = []
        if aliases:
            tail.append("also: " + ", ".join(aliases))
        shown = display_name(entity, person_roster)
        rel = ir.collapsed_text(entity.get(ir.ROSTER_RELATIONSHIP_KEY))
        if rel and not shown.endswith(")"):
            # A disambiguated name already says the relationship.
            tail.append(rel)
        focus = person_focus(entity)
        if focus:
            tail.append(f"focus: {focus}")
        line = f"- {shown}"
        if tail:
            line += " — " + " · ".join(tail)
        lines.append(line)
    hidden = len(ordered) - len(lines)
    if hidden > 0:
        lines.append(f"- …and {hidden} more people on file")
    return "\n".join(lines)
