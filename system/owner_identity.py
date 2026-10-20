#!/usr/bin/env python3
"""Who the owner is — the ONE definition every seat asks (v426, ADR 0047).

The owner, 2026-10-20: *"looks like the system doesn't connect that Dave and
David James Taylor are both me."* The profile said ``name: Dave``,
``full_name: David James Taylor``; the Timeline fold read that and folded the
roster row ``dave`` into the owner, while the roster, the wiki, the
recommender, the classifier context and the verdict verb each spelled the
owner for themselves — or did not spell him at all — and treated the same row
as a stranger with his own person page, a Focus waiting to be recommended and
an alias ("Dave's kids") that belonged to a relation query.

This module is the one place the owner is defined:

* :data:`THE_OWNER_IS_ONE_RECORD` — the owner is the roster row that answers
  to the profile names, marked ``relationship: "self"`` (the word
  `cornerstones.SELF`, `landmark_edit.CATEGORY_RELATIONSHIP` and
  `temporal_work_items.OWNER_SUBJECT_REF` already use). Its Focus is the
  primary life-story Focus and its page is the life hub, never
  ``wiki/people/``.
* :data:`A_ROSTER_NEVER_MAKES_A_STRANGER_OF_THE_OWNER` — a mention of the
  owner (:func:`is_owner_mention`) merges into that row; it never becomes a
  second row, a person Focus, a recommendation or a census stranger.

The profile readers (:func:`owner_profile`, :func:`owner_names_from_profile`,
:func:`owner_name_variants`, :func:`owner_identity_inputs`) moved here from
`temporal_publication`, which re-exports them unchanged (v328's names).
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from pathlib import Path

SYSTEM_DIR = Path(__file__).resolve().parent
if str(SYSTEM_DIR) not in sys.path:
    sys.path.insert(0, str(SYSTEM_DIR))

import identity_resolution as ir  # noqa: E402

THE_OWNER_IS_ONE_RECORD = (
    "the owner is one record: the roster row that answers to the profile "
    "names, marked relationship self, attended by the primary life-story Focus, "
    "whose page is the life hub; no seat spells the owner for itself"
)
A_ROSTER_NEVER_MAKES_A_STRANGER_OF_THE_OWNER = (
    "a mention of the owner (his profile spellings, his given name with his "
    "surname, a narrator or author word) merges into the owner's row; it never "
    "mints a second row, a person Focus, a recommendation, a person page or a "
    "subject other than self"
)
THE_OWNER_IS_NOT_A_PERSON_FOCUS = (
    "the owner is attended by the primary life-story Focus; a person Focus for "
    "the owner is refused"
)

#: The relationship value the owner's row carries (`cornerstones.SELF`).
SELF_RELATIONSHIP = "self"

#: The one refusal reason a seat gives when an act would treat the owner as
#: somebody else (`entity_verdict.EntityIsOwner`, the platform's 409).
ENTITY_IS_OWNER = "ENTITY_IS_OWNER"

#: How :func:`find_owner_row` found the row (``note``).
FOUND_SELF = "self"
FOUND_NAME = "name"
FOUND_NONE = "none"
FOUND_AMBIGUOUS = "ambiguous"

#: The profile keys that spell the owner's own name, in the order the fold is
#: handed them. WHOLE spellings only: a middle name is not the owner
#: (`tests/test_owner_name_subject.py`), so no key here is ever tokenized.
OWNER_NAME_PROFILE_KEYS = ("name", "full_name")

#: J4: the classifier's "Dave (narrator)" — a spelling with a role in brackets.
_ROLE_SUFFIX_RE = re.compile(
    r"^(?P<name>.+?)\s*\(\s*(?:the\s+)?(?:narrator|author|self|me)\s*\)\s*$",
    re.IGNORECASE)


def _spelling(value: object) -> str:
    return " ".join(str(value or "").split())


# --------------------------------------------------------------------------
# The profile (moved from temporal_publication, v328)
# --------------------------------------------------------------------------


def owner_profile(vault_root: str | Path) -> dict:
    """The owner's profile as THIS vault spells it.

    ``profile.yaml`` (committed: name, full_name) under ``config.yaml`` (local,
    wins on conflict) — the same two files and the same precedence as
    `lifehug_core.load_config`, read from the vault being published rather
    than from the process binding. A vault without either is ``{}``.
    """
    try:
        from lifehug_core import load_config  # noqa: PLC0415
        from vault_paths import vault_data_path  # noqa: PLC0415

        root = Path(str(vault_root))
        merged: dict = {}
        for name in ("profile", "config"):
            merged.update(load_config(vault_data_path(name, vault_root=root)) or {})
        return merged
    except Exception:  # noqa: BLE001 — no readable profile is simply no profile
        return {}


def bound_owner_profile() -> dict:
    """The profile of the vault this process is bound to (`load_config`)."""
    try:
        from lifehug_core import load_config  # noqa: PLC0415

        return dict(load_config() or {})
    except Exception:  # noqa: BLE001
        return {}


def owner_names_from_profile(profile: object) -> tuple[str, ...]:
    """The owner's own spellings: ``name`` and ``full_name``, whole, deduplicated.

    This is the set `temporal_timeline` folds with (`timeline-rules:8`, via
    `identity_resolution.owner_name_refs`): a roster entity answering to one of
    these WHOLE spellings is the owner. Interior tokens never enter — "Pat
    Quincy Example" puts "Pat Quincy Example" in, not "Quincy".
    """
    row = profile if isinstance(profile, dict) else {}
    names: list[str] = []
    for key in OWNER_NAME_PROFILE_KEYS:
        text = _spelling(row.get(key))
        if text and text not in names:
            names.append(text)
    return tuple(names)


def author_names(profile: object) -> tuple[str, str]:
    """``(name, full_name)`` as the compiler writes pages with them: ``name``
    falls back to "Me" and ``full_name`` to ``name`` (`focus_pages.author_names`)."""
    row = profile if isinstance(profile, dict) else {}
    author = _spelling(row.get("name")) or "Me"
    full = _spelling(row.get("full_name")) or author
    return author, full


def owner_name_variants(owner_names: object) -> tuple[str, ...]:
    """The whole spellings PLUS each one's first word ("Dave", "David").

    For the RESOLVER only (`resolver.spine`'s ``owner_names``, v325): the
    `subject_age_not_owner` refusal must not fire on the owner's own nickname.
    Never an input to the fold — a first name alone would make every namesake
    in the roster the owner, which is exactly the leak `timeline-rules:8`
    refuses. Order: the whole spellings first, then the new first words.
    """
    out: list[str] = []
    for name in owner_names or ():
        text = _spelling(name)
        if text and text not in out:
            out.append(text)
    for text in list(out):
        first = text.split()[0]
        if first not in out:
            out.append(first)
    return tuple(out)


def owner_identity_inputs(vault_root: str | Path) -> tuple[object, tuple[str, ...]]:
    """``(roster_snapshot, owner_names)`` for a fold of ``vault_root``.

    The one definition behind every publish seat (ADR 0021's "one definition,
    many hosts"): `timeline.publish_calculated_timeline`, a Mirror resolution's
    republish, the frame-display command, the CLI, `verify` — and
    `resolver.spine`, through :func:`owner_names_from_profile`. Before v328 each
    seat spelled its own inputs, and a vault whose roster listed the owner
    changed its mind about whose nodes they were according to which seat had
    republished last.

    * the roster is this vault's ``person`` roster (`entity_roster.load_roster`
      with ``vault_root``), an unreadable one being no roster (``()``);
    * the names are :func:`owner_names_from_profile` over :func:`owner_profile`.

    Both are read from the vault being published, never from the process
    binding, so the roster and the substrate can never come from two vaults
    (the split `timeline._projection_vault_root` exists to make impossible).
    """
    root = Path(str(vault_root))
    roster: object
    try:
        import entity_roster  # noqa: PLC0415

        roster = entity_roster.load_roster("person", vault_root=root)
    except Exception:  # noqa: BLE001 — a roster problem is "no roster"
        roster = ()
    return roster, owner_names_from_profile(owner_profile(root))


def owner_slug(profile: object) -> str:
    """The slug of the profile ``name`` ("dave") — the owner-and-person
    relationship pages' prefix (`focus_pages.relationship_slug`, J1)."""
    from lifehug_core import slugify  # noqa: PLC0415

    author, _full = author_names(profile)
    return slugify(author)


def hub_page(profile: object) -> str:
    """The owner's page: the life hub, ``wiki/life/<slug(full_name)>.md``."""
    import focus_pages  # noqa: PLC0415

    _author, full = author_names(profile)
    return focus_pages.hub_page(full)


# --------------------------------------------------------------------------
# The primary Focus (the life story attends to the owner, J2)
# --------------------------------------------------------------------------


def primary_focus_id(roadmap: object) -> str:
    """The id of the roadmap's primary life-story Focus, or ``""``."""
    focuses = roadmap.get("focuses") if isinstance(roadmap, dict) else None
    for focus in focuses or ():
        if isinstance(focus, dict) and focus.get("primary") and _spelling(focus.get("id")):
            return _spelling(focus.get("id"))
    return ""


def _read_roadmap(path: Path) -> dict:
    try:
        import json  # noqa: PLC0415

        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


@dataclass(frozen=True)
class OwnerContext:
    """What the roster converter needs to know about the owner: his whole
    spellings and the primary Focus id (``""`` when there is no roadmap)."""

    names: tuple[str, ...] = ()
    primary_focus: str = ""


def owner_context(vault_root: str | Path | None = None) -> OwnerContext:
    """The owner's names and primary Focus for ``vault_root`` (or the bound
    vault when ``None``). Never raises: an unreadable vault is no context."""
    try:
        if vault_root is None:
            from lifehug_core import ROADMAP_FILE  # noqa: PLC0415

            profile = bound_owner_profile()
            roadmap = _read_roadmap(Path(ROADMAP_FILE))
        else:
            from vault_paths import vault_data_path  # noqa: PLC0415

            root = Path(str(vault_root))
            profile = owner_profile(root)
            roadmap = _read_roadmap(vault_data_path("roadmap", vault_root=root))
    except Exception:  # noqa: BLE001
        return OwnerContext()
    return OwnerContext(owner_names_from_profile(profile), primary_focus_id(roadmap))


# --------------------------------------------------------------------------
# The predicates
# --------------------------------------------------------------------------


def _rows(roster: object) -> list[dict]:
    if isinstance(roster, dict):
        rows = roster.get("entities") or []
    else:
        rows = roster or []
    return [row for row in rows if isinstance(row, dict)]


def _slug_of(row: dict) -> str:
    key = ir.normalized_mention_key(row.get("slug")) or ir.normalized_mention_key(row.get("name"))
    return key.replace(" ", "-")


def row_ref(row: dict) -> str:
    """``person/<slug>`` for a person roster row."""
    return ir.entity_ref("person", _slug_of(row))


def is_owner_row(row: object) -> bool:
    """Is this roster row the owner's (``relationship: "self"``, live)?"""
    return (isinstance(row, dict) and not ir.is_alias_row(row)
            and ir.normalized_mention_key(row.get("relationship")) == SELF_RELATIONSHIP)


@dataclass(frozen=True)
class OwnerRowFinding:
    """:func:`find_owner_row`'s answer: the row (or ``None``), how it was
    found (``self`` / ``name`` / ``none`` / ``ambiguous``) and, when
    ambiguous, every candidate's slug."""

    row: dict | None
    note: str
    candidates: tuple[str, ...] = ()


def find_owner_row(roster: object, owner_names: object = ()) -> OwnerRowFinding:
    """The owner's row, and how it was found — never a guess.

    A live row marked ``self`` wins. Without one, the row
    `identity_resolution.owner_name_refs` finds for the profile names — exactly
    one; two or more is ``ambiguous`` and names nobody. Two rows both marked
    ``self`` is ambiguous too."""
    live = [row for row in _rows(roster) if not ir.is_alias_row(row)]
    marked = [row for row in live if is_owner_row(row)]
    if len(marked) == 1:
        return OwnerRowFinding(marked[0], FOUND_SELF)
    if len(marked) > 1:
        return OwnerRowFinding(None, FOUND_AMBIGUOUS, tuple(sorted(_slug_of(r) for r in marked)))
    names = tuple(n for n in (_spelling(x) for x in owner_names or ()) if n)
    if not names:
        return OwnerRowFinding(None, FOUND_NONE)
    try:
        refs = ir.owner_name_refs(roster, names)
    except Exception:  # noqa: BLE001 — an unreadable roster names nobody
        refs = frozenset()
    found = [row for row in live if row_ref(row) in refs]
    if len(found) == 1:
        return OwnerRowFinding(found[0], FOUND_NAME)
    if len(found) > 1:
        return OwnerRowFinding(None, FOUND_AMBIGUOUS, tuple(sorted(_slug_of(r) for r in found)))
    return OwnerRowFinding(None, FOUND_NONE)


def owner_row(roster: object, owner_names: object = ()) -> dict | None:
    """The owner's roster row (:func:`find_owner_row`), or ``None``."""
    return find_owner_row(roster, owner_names).row


def owner_ref(roster: object, owner_names: object = ()) -> str | None:
    """``person/<slug>`` of the owner's row, or ``None``."""
    row = owner_row(roster, owner_names)
    return row_ref(row) if row is not None else None


def _given_and_surnames(owner_names: object) -> tuple[frozenset, frozenset]:
    given: set[str] = set()
    surnames: set[str] = set()
    for name in owner_names or ():
        words = _spelling(name).casefold().split()
        if not words:
            continue
        given.add(words[0])
        if len(words) > 1:
            surnames.add(words[-1])
    return frozenset(given), frozenset(surnames)


def names_the_owner(text: object, owner_names: object = ()) -> bool:
    """Is this text one of the owner's NAMES — a whole profile spelling, or a
    2–4 word name whose first word is his given name and last his surname
    ("Dave Taylor", "David J. Taylor")? A bare first word that is not a whole
    spelling never is ("David" is every namesake)."""
    body = _spelling(text)
    if not body:
        return False
    folded = body.casefold()
    if any(folded == _spelling(name).casefold() for name in owner_names or ()):
        return True
    words = folded.split()
    given, surnames = _given_and_surnames(owner_names)
    return 2 <= len(words) <= 4 and words[0] in given and words[-1] in surnames


def strip_role_suffix(text: object) -> str:
    """``"Dave (narrator)"`` → ``"Dave"`` (J4); anything else unchanged."""
    body = _spelling(text)
    match = _ROLE_SUFFIX_RE.match(body)
    return _spelling(match.group("name")) if match else body


def is_owner_mention(text: object, owner_names: object = ()) -> bool:
    """Does this mention name the OWNER (:data:`A_ROSTER_NEVER_MAKES_A_STRANGER_OF_THE_OWNER`)?

    True for an owner-only word (`identity_resolution.OWNER_SUBJECT_MENTIONS`:
    me, self, the narrator, the author …), for one of his names
    (:func:`names_the_owner`), and for a name of his with a role in brackets —
    the classifier's "Dave (narrator)" (J4). A relative who shares his surname
    is not him ("Katie Taylor")."""
    body = _spelling(text)
    if not body:
        return False
    key = ir.normalized_mention_key(body)
    if key in ir.OWNER_SUBJECT_MENTIONS or body.casefold() in ir.OWNER_SUBJECT_MENTIONS:
        return True
    if names_the_owner(body, owner_names):
        return True
    inner = strip_role_suffix(body)
    return inner != body and names_the_owner(inner, owner_names)


def is_owner_possessive(text: object, owner_names: object = ()) -> bool:
    """Is this an owner POSSESSIVE ("Dave's kids", "David James Taylor's mom")
    — a phrase about somebody of his, never a name of his?"""
    body = _spelling(text).replace("’", "'").replace("‘", "'")
    match = re.match(r"^(?P<who>.+?)'s?\s+\S", body)
    if not match:
        return False
    who = match.group("who").rstrip("'")
    folded = who.casefold()
    return any(folded == variant.casefold() for variant in owner_name_variants(owner_names)) \
        or folded in ir.OWNER_SUBJECT_MENTIONS


__all__ = [
    "A_ROSTER_NEVER_MAKES_A_STRANGER_OF_THE_OWNER",
    "ENTITY_IS_OWNER",
    "OWNER_NAME_PROFILE_KEYS",
    "OwnerContext",
    "OwnerRowFinding",
    "SELF_RELATIONSHIP",
    "THE_OWNER_IS_NOT_A_PERSON_FOCUS",
    "THE_OWNER_IS_ONE_RECORD",
    "author_names",
    "bound_owner_profile",
    "find_owner_row",
    "hub_page",
    "is_owner_mention",
    "is_owner_possessive",
    "is_owner_row",
    "names_the_owner",
    "owner_context",
    "owner_identity_inputs",
    "owner_name_variants",
    "owner_names_from_profile",
    "owner_profile",
    "owner_ref",
    "owner_row",
    "owner_slug",
    "primary_focus_id",
    "row_ref",
    "strip_role_suffix",
]
