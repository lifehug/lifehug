#!/usr/bin/env python3
"""v390 — handles: ``@katie`` is the record, typeable in any conversation.

Identity-unification design §3.1 / §4.1.4b (lifehug-platform#987), promise P14,
decision D9's exclusivity. Pure: every function reads the roster snapshots it
is handed (``{entity_type: roster}``) and none touches the disk except
:func:`rosters_from_disk`, which a host calls once and passes down.

**What a handle is.** Every identity record — a person, a place, an object, a
theme, a period — has an implicit handle, its slug with an ``@``
(``@katie-taylor``, ``@yucaipa``). A record may ALSO carry ONE short,
owner-chosen handle (``@katie``), stored as an ALIAS flagged ``handle`` in the
record's ``alias_meta`` (`identity_resolution.ROSTER_ALIAS_META_KEY`), exclusive
by construction: :func:`claimants` refuses it when ANY other record, of ANY
type, already holds the text as a name, an alias, a slug or a handle
(:data:`A_HANDLE_IS_UNIQUE_ACROSS_THE_VAULT`). The reader also tolerates the
alias-entry form ``{"text": "katie", "handle": true}`` so a roster written by
either seat resolves identically.

**What an @mention is.** An explicit reference that BYPASSES resolution:
:func:`parse_handles` finds the tokens (word-bounded; never inside an email or
a URL) and :func:`resolve_handle` answers ``resolved`` / ``ambiguous`` /
``unknown`` with no model, no fuzzy rung and no first-token rule. A token
matching records of two types is ``ambiguous`` and says both — never a guess.
"""

from __future__ import annotations

import re
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

SYSTEM_DIR = Path(__file__).resolve().parent
if str(SYSTEM_DIR) not in sys.path:
    sys.path.insert(0, str(SYSTEM_DIR))

import identity_resolution as ir  # noqa: E402

A_HANDLE_IS_UNIQUE_ACROSS_THE_VAULT = (
    "a handle is unique across every roster: it equals no other record's name, "
    "alias, slug or handle, of any type; a second claim is refused naming the "
    "claimant, never shared"
)

#: The roster types a handle may name, in the order the grammar lists
#: candidates (person first). Order is presentation only: a token matching two
#: types is ``ambiguous`` whatever the order.
HANDLE_TYPES = ("person", "place", "object", "theme", "period")

HANDLE_MAX_LENGTH = 64

#: The charset a handle is made of — a slug's: lowercase letters, digits and
#: hyphens, starting and ending alphanumeric.
HANDLE_NAME_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,62}[a-z0-9])?$")

#: An ``@handle`` in running text. Word-bounded on both sides:
#:
#: * not preceded by anything but the start or whitespace/opening punctuation
#:   — so ``me@example.com`` (a word character before the ``@``),
#:   ``https://host/@katie`` and ``a.b/@katie`` are NOT handles;
#: * not followed by a word character, another ``@`` or ``.word`` — so
#:   ``@katie.example.com`` is a host, while ``@katie.`` ending a sentence and
#:   ``@katie's`` are handles.
HANDLE_RE = re.compile(
    r"(?<![^\s(\[{\"'“‘,;:!?])"
    r"@(?P<handle>[a-z0-9](?:[a-z0-9-]{0,62}[a-z0-9])?)"
    r"(?![\w@-])(?!\.\w)",
    re.IGNORECASE,
)

RESOLVED = "resolved"
AMBIGUOUS = "ambiguous"
UNKNOWN = "unknown"

#: Reasons, named once.
REASON_HANDLE_ALIAS = "handle_alias"
REASON_SLUG = "slug"
REASON_UNKNOWN_HANDLE = "unknown_handle"
REASON_AMBIGUOUS = "ambiguous_handle"
REASON_UNRESOLVED = "unresolved"


@dataclass(frozen=True)
class HandleSpan:
    """One ``@handle`` token: where it is, what was typed, and what it names."""

    span: tuple[int, int]
    raw: str
    ref: str | None
    reason: str
    candidates: tuple[str, ...] = ()

    @property
    def handle(self) -> str:
        return self.raw.lstrip("@").casefold()


@dataclass(frozen=True)
class HandleResolution:
    kind: str
    ref: str = ""
    type: str = ""
    candidates: tuple[str, ...] = ()
    reason: str = ""

    @property
    def resolved(self) -> bool:
        return self.kind == RESOLVED


# --------------------------------------------------------------------------
# the record side: reading handles off a roster entity
# --------------------------------------------------------------------------

def normalize_handle(text: object) -> str:
    """The canonical handle text — lowercased, no ``@`` — or ``""`` when it is
    not a valid handle (charset, length)."""
    cleaned = str(text or "").strip().lstrip("@").casefold()
    return cleaned if HANDLE_NAME_RE.match(cleaned) else ""


def _alias_text(alias: object) -> str:
    if isinstance(alias, dict):
        return ir.collapsed_text(alias.get("text"))
    return ir.collapsed_text(alias)


def _alias_rows(entity: object) -> list[object]:
    raw = entity.get(ir.ROSTER_ALIAS_KEY) if isinstance(entity, dict) else None
    if isinstance(raw, (str, bytes)):
        return [raw]
    return list(raw or ())


def _key_form(text: object) -> str:
    """``Orange Shorts`` and ``orange-shorts`` both read ``orange-shorts``."""
    return ir.normalized_mention_key(text).replace(" ", "-")


def handle_aliases_of(entity: object) -> list[str]:
    """Every alias of this record flagged ``handle`` — as a handle string
    (``"katie"``). Reads both shapes: the ``alias_meta`` flag and a
    ``{"text", "handle": true}`` alias entry."""
    if not isinstance(entity, dict):
        return []
    meta = entity.get(ir.ROSTER_ALIAS_META_KEY)
    meta = meta if isinstance(meta, dict) else {}
    out: list[str] = []
    for alias in _alias_rows(entity):
        text = _alias_text(alias)
        if not text:
            continue
        flagged = bool(isinstance(alias, dict) and alias.get("handle"))
        entry = meta.get(ir.normalized_mention_key(text))
        flagged = flagged or bool(isinstance(entry, dict) and entry.get("handle"))
        handle = normalize_handle(_key_form(text)) if flagged else ""
        if handle and handle not in out:
            out.append(handle)
    return out


def handle_for(entity: object) -> str:
    """What a surface prints beside the name: the owner's short handle when one
    is set, else ``@<slug>`` (the implicit handle)."""
    short = handle_aliases_of(entity)
    if short:
        return f"@{short[0]}"
    slug = ir._entity_slug(entity) if isinstance(entity, dict) else ""
    return f"@{slug}" if slug else ""


def _entities(roster: object) -> list[dict]:
    rows = roster.get("entities") if isinstance(roster, dict) else roster
    return [row for row in rows or () if isinstance(row, dict)]


def _typed_rosters(rosters: object) -> list[tuple[str, list[dict]]]:
    if not isinstance(rosters, Mapping):
        return []
    types = [t for t in HANDLE_TYPES if t in rosters]
    types += [t for t in rosters if t not in types]
    return [(str(t), _entities(rosters[t])) for t in types]


def rosters_from_disk(*, vault_root: object = None) -> dict[str, dict]:
    """Every entity roster, ``{type: roster}`` — what a host passes down."""
    from entity_roster import ENTITY_TYPES, load_roster  # noqa: PLC0415

    return {t: load_roster(t, vault_root=vault_root) for t in ENTITY_TYPES}


# --------------------------------------------------------------------------
# resolution — an explicit reference, no model, no guess
# --------------------------------------------------------------------------

def resolve_handle(handle: object, rosters: object) -> HandleResolution:
    """One ``@handle`` against every roster.

    (a) an alias flagged ``handle`` on any record of any type; only if none
    claims it, (b) a record slug — person, place, object, theme, period.
    Fold pointers (a duplicate row that points at its survivor) never answer.
    Two refs ⇒ ``ambiguous`` naming both; none ⇒ ``unknown`` /
    ``unknown_handle``.
    """
    wanted = normalize_handle(handle)
    if not wanted:
        return HandleResolution(UNKNOWN, reason=REASON_UNKNOWN_HANDLE)
    by_handle: list[tuple[str, dict]] = []
    by_slug: list[tuple[str, dict]] = []
    for kind, entities in _typed_rosters(rosters):
        for entity in entities:
            if ir.is_alias_row(entity):
                continue
            if wanted in handle_aliases_of(entity):
                by_handle.append((kind, entity))
            if ir._entity_slug(entity) == wanted:
                by_slug.append((kind, entity))
    for found, reason in ((by_handle, REASON_HANDLE_ALIAS), (by_slug, REASON_SLUG)):
        if not found:
            continue
        refs = tuple(dict.fromkeys(
            ir.entity_ref(kind, ir._entity_slug(entity)) for kind, entity in found))
        if len(refs) == 1:
            return HandleResolution(RESOLVED, refs[0], found[0][0], refs, reason)
        return HandleResolution(AMBIGUOUS, "", "", refs, REASON_AMBIGUOUS)
    return HandleResolution(UNKNOWN, reason=REASON_UNKNOWN_HANDLE)


def parse_handles(text: object, rosters: object = None) -> list[HandleSpan]:
    """Every ``@handle`` token in ``text``, in order, as :class:`HandleSpan`.

    With ``rosters`` (``{type: roster}``) each carries its ``ref`` (or ``None``
    with ``reason`` ``unknown_handle`` / ``ambiguous_handle`` and the
    ``candidates``); without, ``ref`` is ``None`` and ``reason`` is
    ``unresolved`` — the grammar alone."""
    body = text if isinstance(text, str) else ""
    spans: list[HandleSpan] = []
    for match in HANDLE_RE.finditer(body):
        raw = match.group(0)
        if rosters is None:
            spans.append(HandleSpan(match.span(), raw, None, REASON_UNRESOLVED))
            continue
        found = resolve_handle(match.group("handle"), rosters)
        spans.append(HandleSpan(match.span(), raw, found.ref or None,
                                found.reason, found.candidates))
    return spans


# --------------------------------------------------------------------------
# uniqueness — the writer's refusal
# --------------------------------------------------------------------------

def claimants(handle: object, rosters: object, *,
              exclude: tuple[str, str] | None = None) -> list[dict]:
    """Every OTHER record that already holds ``handle`` as its slug, name,
    alias or handle — across ALL rosters
    (:data:`A_HANDLE_IS_UNIQUE_ACROSS_THE_VAULT`). ``exclude`` is the
    ``(type, slug)`` of the record asking. Fold-pointer rows count: they still
    hold their spellings. ``[{"ref", "name", "holds"}]``."""
    wanted = normalize_handle(handle)
    out: list[dict] = []
    for kind, entities in _typed_rosters(rosters):
        for entity in entities:
            slug = ir._entity_slug(entity)
            if exclude and (kind, slug) == tuple(exclude):
                continue
            holds = ""
            if slug == wanted:
                holds = "slug"
            elif _key_form(entity.get("name")) == wanted:
                holds = "name"
            elif any(_key_form(_alias_text(a)) == wanted for a in _alias_rows(entity)):
                holds = "handle" if wanted in handle_aliases_of(entity) else "alias"
            if holds:
                out.append({"ref": ir.entity_ref(kind, slug),
                            "name": ir.collapsed_text(entity.get("name")) or slug,
                            "holds": holds})
    return out


def refusal(handle: str, target_ref: str, target_name: str,
            colliders: list[dict]) -> dict:
    """The `identity_uncertain`-shaped refusal, claimants named."""
    candidates = [{"ref": target_ref, "name": target_name},
                  *({"ref": c["ref"], "name": c["name"]} for c in colliders)]
    names = " or ".join(str(c["name"]) for c in candidates)
    return {
        "applied": False,
        "reason": "identity_uncertain",
        "candidates": candidates,
        "claimed_as": [{"ref": c["ref"], "holds": c["holds"]} for c in colliders],
        "headline": f"“@{handle}” could be {names}",
        "alias": handle,
        "handle": True,
    }


def without_handle(entity: dict) -> dict:
    """``entity`` with its short handle UNFLAGGED (``--clear-handle``): the
    ``@<slug>`` handle stays implicit, and the alias string stays an ordinary
    alias — clearing a handle never deletes a name the record answers to."""
    flagged = set(handle_aliases_of(entity))
    if not flagged:
        return entity
    meta = {}
    for key, value in dict(entity.get(ir.ROSTER_ALIAS_META_KEY) or {}).items():
        if isinstance(value, dict) and _key_form(key) in flagged:
            value = {k: v for k, v in value.items() if k != ir.ALIAS_HANDLE}
            if not any(value.get(f) for f in (ir.ALIAS_SHARED_WITH,)) and \
                    value.get(ir.ALIAS_EXCLUSIVE, True):
                continue
        meta[key] = value
    rows = []
    for alias in _alias_rows(entity):
        if isinstance(alias, dict) and alias.get("handle"):
            alias = {k: v for k, v in alias.items() if k != "handle"}
        rows.append(alias)
    out = {**entity, ir.ROSTER_ALIAS_KEY: rows}
    if meta:
        out[ir.ROSTER_ALIAS_META_KEY] = meta
    else:
        out.pop(ir.ROSTER_ALIAS_META_KEY, None)
    return out


# --------------------------------------------------------------------------
# statements by handle — design §4.1.4b, promise P14. No model judgement.
# --------------------------------------------------------------------------

#: What a statement does. The verb is decided by the SHAPE of the sentence and
#: the TYPE of the record the handle names, never by a model.
KIND_ALIAS = "alias"
KIND_FOLD = "fold"
KIND_LOCATED_IN = "located_in"

#: Resolutions. ``resolved`` files its argv; every other one files NOTHING.
STATEMENT_RESOLVED = "resolved"
STATEMENT_AMBIGUOUS = "ambiguous"
STATEMENT_UNKNOWN_HANDLE = "unknown_handle"
STATEMENT_UNKNOWN_SUBJECT = "unknown_subject"
STATEMENT_UNSUPPORTED = "unsupported"
STATEMENT_NOOP = "noop"

BASIS_HANDLE = "handle"

#: Types a statement may NAME (alias / fold). Periods nest and are the Eras
#: program's; a statement about one files nothing here.
STATEMENT_TYPES = ("person", "place", "object", "theme")

A_HANDLE_STATEMENT_NEVER_MINTS = (
    "a statement by handle files an alias, a fold or a containment on records "
    "that already exist; it never passes --ensure, so a conversation never "
    "mints an identity record"
)

_H = r"@(?P<{n}>[a-z0-9](?:[a-z0-9-]{{0,62}}[a-z0-9])?)(?![\w@-])"

#: "@yucaipa is in @california" / "@yucaipa is a city inside @california".
_LOCATED_RE = re.compile(
    r"(?<![^\s(\[{\"'“‘,;:!?])" + _H.format(n="a")
    + r"\s+(?:is|are|was|were)\s+(?:(?:a|an|the|one)\s+)?(?:[a-z]+\s+){0,3}?"
    r"(?:in|inside|within|located\s+in|part\s+of)\s+"
    r"(?<![^\s(\[{\"'“‘,;:!?])" + _H.format(n="b"),
    re.IGNORECASE)

#: "same as @h" / "the same thing as @h" / "the same person as @h".
_SAME_RE = re.compile(
    r"\b(?:(?:is|are|was|were)\s+)?(?:(?:all\s+)?the\s+)?same"
    r"(?:\s+(?:thing|one|person|place|object|theme))?\s+as\s+"
    r"(?<![^\s(\[{\"'“‘,;:!?])" + _H.format(n="h"),
    re.IGNORECASE)

#: "this is @h" / "X is @h" / "that was @h".
_IS_RE = re.compile(
    r"\b(?P<verb>is|was|are|were)\s+(?:also\s+|really\s+|actually\s+)?"
    r"(?<![^\s(\[{\"'“‘,;:!?])" + _H.format(n="h"),
    re.IGNORECASE)

_SENTENCE_SPLIT = re.compile(r"(?<=[.!?;])\s+|\n+")

_PRONOUNS = frozenset({"this", "that", "these", "those", "it", "he", "she", "they",
                       "here", "there", "who", "which", "what", "one", "ones"})
_DETERMINERS = frozenset({"the", "a", "an", "my", "our", "his", "her", "their", "its"})
#: A subject run stops at a clause boundary word.
_BOUNDARY_WORDS = frozenset({
    "and", "but", "so", "because", "that", "then", "when", "if", "said", "says",
    "told", "tell", "call", "called", "named", "is", "was", "are", "were", "as",
    "with", "i", "we", "you", "oh", "yes", "no", "well", "actually", "also",
    "really", "just", "meant", "mean", "means"})
_SUBJECT_MAX_WORDS = 5
NAME_LIMIT = 80


@dataclass(frozen=True)
class HandleStatement:
    """One statement made by handle. ``argv`` is the ``entity-verdict`` call
    that files it — empty unless ``resolution`` is ``resolved``."""

    kind: str
    resolution: str
    handle: str
    ref: str = ""
    type: str = ""
    name: str = ""
    subject_ref: str = ""
    candidates: tuple[str, ...] = ()
    reason: str = ""
    evidence: str = ""
    basis: str = BASIS_HANDLE
    argv: tuple[str, ...] = ()

    @property
    def resolved(self) -> bool:
        return self.resolution == STATEMENT_RESOLVED

    def to_dict(self) -> dict:
        return {"kind": self.kind, "resolution": self.resolution, "basis": self.basis,
                "handle": self.handle, "ref": self.ref or None,
                "type": self.type or None, "name": self.name or None,
                "subject_ref": self.subject_ref or None,
                "candidates": list(self.candidates), "reason": self.reason,
                "evidence": self.evidence or None, "argv": list(self.argv)}


def _record_of(rosters: object, ref: str) -> tuple[str, dict | None]:
    kind, _, slug = str(ref).partition("/")
    for entity_type, entities in _typed_rosters(rosters):
        if entity_type != kind:
            continue
        for entity in entities:
            if ir._entity_slug(entity) == slug:
                return kind, entity
    return kind, None


def _subject_name(before: str) -> str:
    """The name a sentence's subject is, read from the words just before the
    verb — or ``""`` when it is a pronoun ("this", "these"), an empty run, or
    a role word ("my wife"), none of which is a name to file."""
    words = re.findall(r"[^\s,]+", before.rsplit(",", 1)[-1])
    run: list[str] = []
    for word in reversed(words):
        if word.casefold().strip("'’") in _BOUNDARY_WORDS:
            break
        run.append(word)
        if len(run) > _SUBJECT_MAX_WORDS:
            return ""
    run.reverse()
    if run and (run[-1].casefold() in _PRONOUNS - {"one", "ones"}
                or all(w.casefold() in _PRONOUNS for w in run)):
        return ""  # "I told her this is @katie": the pointer is the subject
    while run and run[0].casefold() in _DETERMINERS:
        run.pop(0)
    if not run or any("@" in w for w in run):
        return ""
    name = " ".join(run).strip(" \"'“”‘’")
    if name.casefold() in _PRONOUNS or not any(c.isalpha() for c in name):
        return ""
    return name[:NAME_LIMIT]


def _is_role_word(name: str) -> bool:
    key = ir.normalized_mention_key(name)
    return key in ir.RELATIONSHIP_MENTION_WORDS or ir.relation_word_stem(key) in \
        ir.RELATIONSHIP_MENTION_WORDS


def _key_matches(entity: dict, key: str) -> bool:
    if not key:
        return False
    names = [entity.get("name"), ir._entity_slug(entity), *(_alias_text(a) for a in _alias_rows(entity))]
    return any(ir.normalized_mention_key(n) == key for n in names if n)


def _holders(rosters: object, entity_type: str, name: str) -> list[dict]:
    """Live records of ``entity_type`` that already answer to ``name`` EXACTLY
    (name, slug or alias — never the first-name rung: a shared first name is
    never "already known")."""
    key = ir.normalized_mention_key(name)
    rows = dict(_typed_rosters(rosters)).get(entity_type, [])
    return [row for row in rows if not ir.is_alias_row(row) and _key_matches(row, key)]


def _statement(kind: str, found: HandleResolution, handle: str, evidence: str,
               **extra) -> HandleStatement:
    if found.kind == AMBIGUOUS:
        return HandleStatement(kind, STATEMENT_AMBIGUOUS, handle, candidates=found.candidates,
                               reason=REASON_AMBIGUOUS, evidence=evidence, **extra)
    return HandleStatement(kind, STATEMENT_UNKNOWN_HANDLE, handle,
                           reason=REASON_UNKNOWN_HANDLE, evidence=evidence, **extra)


def _alias_statement(rosters: object, found: HandleResolution, handle: str, name: str,
                     evidence: str, kind: str = KIND_ALIAS) -> HandleStatement:
    slug = found.ref.partition("/")[2]
    if found.type not in STATEMENT_TYPES:
        return HandleStatement(kind, STATEMENT_UNSUPPORTED, handle, ref=found.ref,
                               type=found.type, name=name, reason="handle_type_unsupported",
                               evidence=evidence)
    if _is_role_word(name):
        return HandleStatement(kind, STATEMENT_UNSUPPORTED, handle, ref=found.ref,
                               type=found.type, name=name, reason="role_word_is_not_a_name",
                               evidence=evidence)
    holders = _holders(rosters, found.type, name)
    others = [row for row in holders
              if ir.entity_ref(found.type, ir._entity_slug(row)) != found.ref]
    if others:
        # Somebody ELSE answers to that name: a collision, never a re-point.
        refs = tuple(dict.fromkeys(
            [found.ref, *(ir.entity_ref(found.type, ir._entity_slug(r)) for r in others)]))
        return HandleStatement(kind, STATEMENT_AMBIGUOUS, handle, ref=found.ref,
                               type=found.type, name=name, candidates=refs,
                               reason="name_held_by_another_record", evidence=evidence)
    if holders:
        return HandleStatement(kind, STATEMENT_NOOP, handle, ref=found.ref, type=found.type,
                               name=name, candidates=(found.ref,), reason="already_known",
                               evidence=evidence)
    return HandleStatement(
        kind, STATEMENT_RESOLVED, handle, ref=found.ref, type=found.type, name=name,
        candidates=(found.ref,), evidence=evidence,
        argv=("entity-verdict", found.type, slug, "clear", "--alias", name))


def _subject_for(rosters: object, found: HandleResolution, name: str, subject: str,
                 subject_ref: str) -> tuple[str, dict | None]:
    """The record the subject names, when it names one of the target's type."""
    if subject_ref:
        kind, row = _record_of(rosters, subject_ref)
        if row is not None and kind == found.type:
            return subject_ref, row
    holders = _holders(rosters, found.type, name or subject) if (name or subject) else []
    if len(holders) == 1:
        return ir.entity_ref(found.type, ir._entity_slug(holders[0])), holders[0]
    return "", None


def handle_statements(text: object, rosters: object, *, subject: str = "",
                      subject_ref: str = "") -> tuple[HandleStatement, ...]:
    """Every statement ``text`` makes BY HANDLE, resolved — deterministically.

    ``rosters`` is ``{type: roster}``. ``subject`` is what the host knows the
    message is ABOUT when the sentence only points ("this is @katie" — the
    question's unresolved subject name); ``subject_ref`` the record, when the
    host holds one ("these are the same as @orange-shorts" on an object page).

    Three shapes, decided by the sentence and the handle's type:

    * ``X is @h`` / ``this is @h`` — an ALIAS of the record ``@h`` names
      (person, place, object, theme);
    * ``X is the same as @h`` / ``same as @h`` — a person or place gains the
      name as an alias; an object or theme whose subject IS an existing record
      FOLDS into ``@h`` (a pointer, never a deletion), otherwise it too gains
      the name as an alias;
    * ``@a is in @b`` — ``located_in`` (both must be places).

    ``unknown_handle`` / ``ambiguous`` / ``unknown_subject`` /
    ``unsupported`` statements carry no argv. Nothing is ever ensured
    (:data:`A_HANDLE_STATEMENT_NEVER_MINTS`).
    """
    body = text if isinstance(text, str) else ""
    out: list[HandleStatement] = []
    seen: set = set()

    def add(statement: HandleStatement) -> None:
        key = (statement.kind, statement.handle, statement.name, statement.argv,
               statement.resolution, statement.reason)
        if key not in seen:
            seen.add(key)
            out.append(statement)

    for sentence in _SENTENCE_SPLIT.split(body):
        if "@" not in sentence:
            continue
        consumed: list[tuple[int, int]] = []
        for match in _LOCATED_RE.finditer(sentence):
            consumed.append(match.span())
            evidence = " ".join(match.group(0).split())
            a = resolve_handle(match.group("a"), rosters)
            b = resolve_handle(match.group("b"), rosters)
            bad = a if not a.resolved else (b if not b.resolved else None)
            if bad is not None:
                add(_statement(KIND_LOCATED_IN, bad, ("@" + (match.group("a") if bad is a
                                                           else match.group("b"))).casefold(),
                               evidence))
                continue
            if a.type != "place" or b.type != "place":
                add(HandleStatement(KIND_LOCATED_IN, STATEMENT_UNSUPPORTED,
                                    "@" + match.group("a").casefold(), ref=a.ref,
                                    candidates=(a.ref, b.ref), reason="containment_needs_two_places",
                                    evidence=evidence))
                continue
            if a.ref == b.ref:
                add(HandleStatement(KIND_LOCATED_IN, STATEMENT_NOOP,
                                    "@" + match.group("a").casefold(), ref=a.ref,
                                    reason="a_place_is_not_inside_itself", evidence=evidence))
                continue
            add(HandleStatement(
                KIND_LOCATED_IN, STATEMENT_RESOLVED, "@" + match.group("a").casefold(),
                ref=a.ref, type="place", candidates=(a.ref, b.ref), evidence=evidence,
                argv=("entity-verdict", "place", a.ref.partition("/")[2], "clear",
                      "--located-in", b.ref.partition("/")[2])))
        for match in _SAME_RE.finditer(sentence):
            consumed.append(match.span())
            handle = "@" + match.group("h").casefold()
            evidence = " ".join(sentence[:match.end()].split())
            found = resolve_handle(match.group("h"), rosters)
            if not found.resolved:
                add(_statement(KIND_ALIAS, found, handle, evidence))
                continue
            name = _subject_name(sentence[:match.start()]) or ""
            about = name or " ".join(str(subject or "").split())[:NAME_LIMIT]
            ref, row = _subject_for(rosters, found, name, about, subject_ref)
            if row is not None and found.type in ("object", "theme"):
                if ref == found.ref:
                    add(HandleStatement(KIND_FOLD, STATEMENT_NOOP, handle, ref=found.ref,
                                        type=found.type, name=about, subject_ref=ref,
                                        reason="already_the_same_record", evidence=evidence))
                    continue
                add(HandleStatement(
                    KIND_FOLD, STATEMENT_RESOLVED, handle, ref=found.ref, type=found.type,
                    name=about, subject_ref=ref, candidates=(found.ref, ref), evidence=evidence,
                    argv=("entity-verdict", found.type, ref.partition("/")[2], "clear",
                          "--fold-into", found.ref.partition("/")[2])))
                continue
            if not about:
                add(HandleStatement(KIND_ALIAS, STATEMENT_UNKNOWN_SUBJECT, handle, ref=found.ref,
                                    type=found.type, reason="no_subject", evidence=evidence))
                continue
            add(_alias_statement(rosters, found, handle, about, evidence))
        for match in _IS_RE.finditer(sentence):
            if any(start <= match.start() < end for start, end in consumed):
                continue
            # "@a is @b" — a handle is not a name to teach.
            handle = "@" + match.group("h").casefold()
            evidence = " ".join(sentence[:match.end()].split())
            found = resolve_handle(match.group("h"), rosters)
            if not found.resolved:
                add(_statement(KIND_ALIAS, found, handle, evidence))
                continue
            name = _subject_name(sentence[:match.start()])
            about = name or " ".join(str(subject or "").split())[:NAME_LIMIT]
            if not about:
                add(HandleStatement(KIND_ALIAS, STATEMENT_UNKNOWN_SUBJECT, handle, ref=found.ref,
                                    type=found.type, reason="no_subject", evidence=evidence))
                continue
            add(_alias_statement(rosters, found, handle, about, evidence))
    return tuple(out)


def statement_invocations(statements: object) -> list[list[str]]:
    """The ``entity-verdict`` argv that files each RESOLVED statement — ADR
    0021: the package names the argv, the host writes it. Order preserved,
    duplicates dropped, **never ``--ensure``**."""
    argvs: list[list[str]] = []
    for statement in statements or ():
        argv = list(getattr(statement, "argv", None) or
                    (statement.get("argv") if isinstance(statement, dict) else ()) or ())
        if argv and "--ensure" not in argv and argv not in argvs:
            argvs.append(argv)
    return argvs
