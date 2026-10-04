#!/usr/bin/env python3
"""v387 — person resolution for the classifier and the identity listener.

**A THIN ADAPTER, NOT A SECOND RESOLVER.** The identity-unification design
(lifehug-platform#987, `docs/design/identity.md` §4.1.2) gives
`identity_resolution` ONE typed resolver per entity type —
``resolve_person(text, roster, *, context) -> Resolution`` with ``kind`` one
of ``resolved`` / ``ambiguous`` / ``unknown`` — and a disambiguated
``display_name(record, roster)``. That work (I-1) lands in a sibling release.
Until it does, the two callers this release adds (the classifier's "People you
already know" block and its post-processor, and the general listener's
``person_identity`` list) are written against THAT signature, through this
module:

* when `identity_resolution` already exports ``resolve_person`` /
  ``display_name`` / ``parse_handles``, this module DELEGATES to them;
* otherwise it falls back to today's deterministic readings — the exact
  name/alias/full-name/relationship-qualified rungs of
  `identity_resolution.resolve_mention`, the owner's possessive read as his
  "my" (`identity_resolution.owner_possessive_as_my`), and a relationship WORD
  resolved against the roster's own ``relationship`` field ONLY when the word
  has cardinality one (:data:`CARDINALITY_ONE_WORDS`).

When I-1 lands, the rebase deletes the fallback bodies and leaves the
delegations (or deletes this module and repoints its two importers).

The adapter never guesses: two candidates are ``ambiguous``, a set-valued
relationship word ("my son") with no name is ``ambiguous`` over the set (or
``unknown`` when the set is empty), and a name nobody bears is ``unknown``.
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

#: Relationship words that name ONE person (design §3.1, "relations are sets,
#: not aliases"): "my wife" can be resolved by the word alone when exactly one
#: spouse is on record; "my son" never can, because a family may hold two.
#: I-1 moves the cardinality table into `relation_words`; until then this is
#: the narrow, conservative list — every other word is a SET.
CARDINALITY_ONE_WORDS = frozenset({
    "wife", "husband", "spouse", "dad", "father", "mom", "mother",
})

#: An explicit reference typed by the person: ``@mara-holt``.
HANDLE_RE = re.compile(r"(?<![\w@])@(?P<handle>[a-z0-9][a-z0-9-]*)", re.IGNORECASE)

_EVIDENCE_REF = "person_resolution:adapter"


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
    return [row for row in _entities(roster) if _is_person_row(row)]


def ref_of(entity: dict) -> str:
    return ir.entity_ref("person", ir._entity_slug(entity))


def slug_of_ref(ref: object) -> str:
    text = str(ref or "")
    return text.split("/", 1)[1] if "/" in text else text


def _from_upstream(result: object) -> Resolution:
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

def _relationship_set(word: str, roster: object) -> list[str]:
    wanted = ir.RELATIONSHIP_MENTION_WORDS.get(word, frozenset())
    out: list[str] = []
    for entity in person_rows(roster):
        rel = ir.normalized_mention_key(entity.get(ir.ROSTER_RELATIONSHIP_KEY))
        if rel and rel in wanted:
            ref = ref_of(entity)
            if ref not in out:
                out.append(ref)
    return out


def resolve_person(text: object, roster: object, *,
                   context: dict | None = None) -> Resolution:
    """``resolved`` / ``ambiguous`` / ``unknown`` for one person mention.

    ``context`` may carry ``relationship`` (a relationship WORD said in the
    same clause), which narrows a shared name and — for a cardinality-one word
    only — resolves a mention that is the word alone.
    """
    upstream = getattr(ir, "resolve_person", None)
    if callable(upstream):
        return _from_upstream(upstream(text, roster, context=context or {}))
    mention = ir.collapsed_text(text)
    handles = parse_handles(mention)
    if handles and mention.lstrip("@").casefold() == handles[0]:
        return resolve_handle(handles[0], roster)
    mine = ir.owner_possessive_as_my(mention)
    if mine:
        mention = mine
    ctx_word = ir.relation_word_stem((context or {}).get("relationship"))
    names, relations = ir.mention_tokens(mention)
    words = list(relations)
    if ctx_word and ctx_word in ir.RELATIONSHIP_MENTION_WORDS and ctx_word not in words:
        words.append(ctx_word)
    if not mention and not words:
        return Resolution(UNKNOWN, reason="empty")
    rows = person_rows(roster)
    if names:
        record = ir.resolve_mention(mention, roster=rows,
                                    evidence_ref=_EVIDENCE_REF)
        found = tuple(str(c.get("ref") if isinstance(c, dict) else c)
                      for c in (getattr(record, "candidates", ()) or ()))
        if record.resolution == "same" and record.resolved_ref:
            return Resolution(RESOLVED, record.resolved_ref, found,
                              str(record.reason))
        if found and words:
            wanted: set[str] = set()
            for word in words:
                wanted |= ir.RELATIONSHIP_MENTION_WORDS.get(word, frozenset())
            index = ir.roster_index(rows)
            narrowed = tuple(ref for ref in found
                             if index.relationship_of.get(ref, "") in wanted)
            if len(narrowed) == 1:
                return Resolution(RESOLVED, narrowed[0], found,
                                  "relationship_narrowed")
        if found:
            return Resolution(AMBIGUOUS, candidates=found,
                              reason=str(record.reason))
        return Resolution(UNKNOWN, reason="no_candidate")
    # A relationship word and no name.
    word = words[0] if words else ""
    members = _relationship_set(word, rows) if word else []
    if not members:
        return Resolution(UNKNOWN, reason="no_candidate")
    if word in CARDINALITY_ONE_WORDS and len(members) == 1:
        return Resolution(RESOLVED, members[0], tuple(members),
                          "cardinality_one_relationship")
    reason = ("relationship_is_a_set" if word not in CARDINALITY_ONE_WORDS
              else "ambiguous_candidates")
    return Resolution(AMBIGUOUS, candidates=tuple(members), reason=reason)


# --------------------------------------------------------------------------
# display_name — D7, colliding names carry a disambiguator
# --------------------------------------------------------------------------

def _born_year(entity: dict) -> str:
    born = entity.get("born")
    if isinstance(born, dict):
        born = born.get("edtf") or born.get("lower") or born.get("best") or born
    match = re.search(r"(1[89]\d{2}|20\d{2})", str(born or ""))
    return match.group(1) if match else ""


def display_name(record: dict, roster: object) -> str:
    """The bare name when unique; ``Name (relation[, b. YYYY])`` when another
    person record shares its name or its given name (design D7)."""
    upstream = getattr(ir, "display_name", None)
    if callable(upstream):
        return str(upstream(record, roster))
    name = ir.collapsed_text(record.get("name")) or ir._entity_slug(record)
    key = ir.normalized_mention_key(name)
    given = key.split()[0] if key else ""
    mine = ref_of(record)
    collides = False
    for other in person_rows(roster):
        if ref_of(other) == mine:
            continue
        other_key = ir.normalized_mention_key(other.get("name"))
        if other_key and (other_key == key or other_key.split()[0] == given):
            collides = True
            break
    if not collides:
        return name
    bits = [ir.collapsed_text(record.get(ir.ROSTER_RELATIONSHIP_KEY))]
    year = _born_year(record)
    if year:
        bits.append(f"b. {year}")
    bits = [bit for bit in bits if bit]
    return f"{name} ({', '.join(bits)})" if bits else name


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
