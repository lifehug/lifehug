"""Era identity, label and kind — an era is an id, never a name.

Eras design §2.3/§4.1 (lifehug-platform `docs/design/eras.md`), phase E3.

**The whole point.** A legacy roster period IS its name: rename it and every
attachment goes with the old string, spell it twice and there are two eras,
and the "date" it carries is a side effect of whatever keyword placement
sorted into it. That is the defect that put College at 1990-1991 in front of
High School on the founder's own Timeline. So a named era here has an
**opaque immutable id** seeded by the CREATING ACT — not by anything the
person might later change their mind about — and its label, its aliases and
its kind are *decision records on that id*. Renaming mints no era. Merging
retires one and keeps its aliases. Duplicate detection in a later
conversation is identity resolution, never label-as-identity.

    era_id = digest_id("era", {"creation_operation_id": <operation id>})

where the operation id is the **mutation/idempotency key of the creating
act** — ``session_ref#turn_ref`` for something a person said, or
``migration:<batch>:<legacy_slug>`` for a roster row. Which means the id is
a function of the act and nothing else: a job that dies half way through
creating an era and is retried under the same mutation id lands on the SAME
id and the same file, so "replay is a no-op" is arithmetic rather than a
lock.

**Three records, one shape.** All three are immutable vault sources in
exactly the shape `temporal_store.promote_conversational_source` and
`temporal_store.file_ordering_constraint` already use — frontmatter, prose
body, `content_sha256` over the body, published through a create-or-keep so
a second identical filing writes nothing:

===============  ============================================================
identity         ``sources/eras/era-<24hex>.md``
label / alias    ``sources/eras/era-<24hex>/labels/<24hex>.md``
kind             ``sources/eras/era-<24hex>/kind/<24hex>.md``
===============  ============================================================

**One deviation from the design's prose, stated.** §2.3 writes the paths as
``sources/eras/<era_id>...``. An ``era_id`` is ``era:<24hex>`` and a ``:``
is not a safe path component — the platform's own document ids ban ``/`` for
the same class of reason. The file stem is therefore ``era-<24hex>``,
exactly the convention ``sources/corrections/temporal-<24hex>.md`` already
uses for a ``temporal_correction:<24hex>``. The full id lives INSIDE the
file, and :func:`era_relative_path` is the one derivation.

**This module never binds itself to a vault.** Like `temporal_store`, every
function takes the vault root, because the writer runs inside a hosted job
against a checkout the interpreter did not select.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Iterable, Sequence

SYSTEM_DIR = Path(__file__).resolve().parent
if str(SYSTEM_DIR) not in sys.path:
    sys.path.insert(0, str(SYSTEM_DIR))

import temporal_store as store  # noqa: E402
from temporal_claims import (  # noqa: E402
    SCHEMA_VERSION,
    TemporalContractError,
    collapsed_text,
    digest_id,
    normalized_timestamp,
)

# --------------------------------------------------------------------------
# Layout and vocabulary
# --------------------------------------------------------------------------

#: Every era record lives under one directory, so "delete the eras" is one
#: path and a vault contract entry is one row.
ERA_SOURCES_DIR = "sources/eras"

ERA_IDENTITY_TYPE = "era_identity"
ERA_LABEL_TYPE = "era_label"
ERA_KIND_TYPE = "era_kind"

ERA_ID_PREFIX = "era"

#: Ruling 21 (design §4.5). A **stretch** is a bounded span of the life axis;
#: a **thread** is a recurring presence with no honest end. The distinction is
#: decided from the person's own words at creation and is a decision RECORD,
#: so flipping it changes no identity and loses no history.
ERA_KINDS = ("stretch", "thread")

#: Where an era came from. ``legacy_roster`` is the migration's own origin and
#: is what makes a migrated era legible as "we inherited this, nobody said it".
ERA_ORIGINS = ("person", "legacy_roster", "recommendation")

#: FROZEN. What makes two era identities the same era: the creating act.
#: Deliberately NOT the label — that is the entire thesis of this module.
ERA_IDENTITY_KEYS = ("creation_operation_id",)

#: FROZEN. What makes two label decisions the same decision. ``created_at`` is
#: absent for the same reason it is absent from a correction's identity:
#: re-filing the same rename is a no-op, not a second rename.
ERA_LABEL_IDENTITY_KEYS = ("era_id", "label", "aliases", "supersedes")

#: FROZEN. Same rule for the kind decision.
ERA_KIND_IDENTITY_KEYS = ("era_id", "era_kind", "supersedes")

#: Frontmatter order for the three records. The algorithm is
#: `temporal_store.format_frontmatter`'s (shared, parity-pinned); only the key
#: list is local, exactly as that module says.
FRONTMATTER_ORDER = (
    "title",
    "type",
    "source_id",
    "source_medium",
    "era_id",
    "origin",
    "era_kind",
    "label",
    "aliases",
    "legacy_slug",
    "supersedes",
    "session_ref",
    "turn_ref",
    "creation_operation_id",
    "captured_at",
    "visibility",
    "status",
    "immutable",
    "schema_version",
    "source_path",
    "content_sha256",
)

MAX_LABEL_CHARS = 120
MAX_ALIASES = 24

_ERA_ID_RE = re.compile(r"^era:[0-9a-f]{24}$")
_HEX24_RE = re.compile(r"^[0-9a-f]{24}$")

#: Collapsed to one space, casefolded — the ONE normalization the binder and
#: the duplicate check both read. Two spellings that differ only by case or
#: run of whitespace are one label; nothing else is folded, because
#: "St. Mary's" and "St Marys" are not the same words and pretending they are
#: is exactly the guess §4.3 forbids.
_WHITESPACE_RE = re.compile(r"\s+")


class EraIdentityError(TemporalContractError):
    """An era record could not be filed or read, with a named code."""


#: Every code this module raises.
ERA_ERROR_CODES = (
    "era_operation_id_required",
    "era_origin_unknown",
    "era_kind_unknown",
    "era_id_malformed",
    "era_label_required",
    "era_label_too_long",
    "era_too_many_aliases",
    "era_identity_missing",
    "era_record_unreadable",
)


# --------------------------------------------------------------------------
# Identity
# --------------------------------------------------------------------------


def turn_operation_id(session_ref: object, turn_ref: object) -> str:
    """The operation id of an era a person created in one turn.

    The same two fields `temporal_store.PROMOTION_IDENTITY_KEYS` uses to
    identify the utterance, in the same order, so the era and the promoted
    source it came from are two derivations of ONE act rather than two acts
    that happen to look alike.
    """
    session = collapsed_text(session_ref)
    turn = collapsed_text(turn_ref)
    if not session or not turn:
        raise EraIdentityError(
            "era_operation_id_required",
            "an era created in conversation names its session and its turn",
        )
    return f"{session}#{turn}"


def migration_operation_id(batch: object, legacy_slug: object) -> str:
    """The operation id of a migrated roster period (design §4.1).

    ``batch`` is what makes a re-run of the SAME migration idempotent and a
    deliberate second migration a different act. Re-running batch ``1`` over
    the same roster mints the same ids and writes nothing.
    """
    label = collapsed_text(batch)
    slug = collapsed_text(legacy_slug)
    if not label or not slug:
        raise EraIdentityError(
            "era_operation_id_required",
            "a migrated era names its batch and the roster slug it came from",
        )
    return f"migration:{label}:{slug}"


def era_id_for(operation_id: object) -> str:
    """``era:<24 hex>`` from the creating act's own idempotency key."""
    key = collapsed_text(operation_id)
    if not key:
        raise EraIdentityError(
            "era_operation_id_required", "an era id is seeded by the act that created it"
        )
    return digest_id(ERA_ID_PREFIX, {"creation_operation_id": key})


def era_digest(era_id: object) -> str:
    """The 24 hex characters of an era id, guarded."""
    text = collapsed_text(era_id)
    if not _ERA_ID_RE.fullmatch(text):
        raise EraIdentityError("era_id_malformed", f"not an era id: {era_id!r}")
    return text.split(":", 1)[1]


def era_relative_path(era_id: object) -> str:
    """``sources/eras/era-<24hex>.md`` — the identity document."""
    return f"{ERA_SOURCES_DIR}/era-{era_digest(era_id)}.md"


def era_label_relative_path(era_id: object, digest: object) -> str:
    """``sources/eras/era-<24hex>/labels/<24hex>.md``."""
    return f"{ERA_SOURCES_DIR}/era-{era_digest(era_id)}/labels/{_hex24(digest)}.md"


def era_kind_relative_path(era_id: object, digest: object) -> str:
    """``sources/eras/era-<24hex>/kind/<24hex>.md``."""
    return f"{ERA_SOURCES_DIR}/era-{era_digest(era_id)}/kind/{_hex24(digest)}.md"


def _hex24(value: object) -> str:
    text = collapsed_text(value).lower()
    _prefix, _, digest = text.rpartition(":")
    digest = digest or text
    if not _HEX24_RE.fullmatch(digest):
        raise EraIdentityError("era_id_malformed", f"not a 24-hex digest: {value!r}")
    return digest


def normalize_label(value: object) -> str:
    """The ONE label normalization: collapsed whitespace, casefolded.

    Read by the binder (§4.3's "exact case-folded whole-label match"), by the
    duplicate check in the migration report, and by nothing else — so the
    three cannot disagree about whether *"the Mission"* and *"The Mission"*
    are one name. They are.
    """
    return _WHITESPACE_RE.sub(" ", str(value or "").strip()).casefold()


def _label_list(values: object) -> list[str]:
    if isinstance(values, (str, bytes)):
        values = [values]
    seen: dict[str, str] = {}
    for value in values or ():
        text = collapsed_text(value)
        if not text:
            continue
        if len(text) > MAX_LABEL_CHARS:
            raise EraIdentityError(
                "era_label_too_long", f"an alias is {len(text)} chars: {text[:40]!r}…"
            )
        seen.setdefault(normalize_label(text), text)
    if len(seen) > MAX_ALIASES:
        raise EraIdentityError(
            "era_too_many_aliases", f"{len(seen)} aliases; an era is not a thesaurus"
        )
    return [seen[key] for key in sorted(seen)]


# --------------------------------------------------------------------------
# Writing
# --------------------------------------------------------------------------


def _publish(
    vault_root: str | Path,
    relative: str,
    *,
    frontmatter: dict,
    heading: str,
    prose: str,
) -> tuple[dict, bool]:
    """File one immutable era record; report whether THIS call created it.

    The body carries the words, the frontmatter carries the facts, and
    ``content_sha256`` is over the body — the same three-part shape every
    other source in this vault has, so an era record is readable by the same
    tools and citable by the same `SourceRef`.
    """
    payload = f"# {heading}\n\n{prose.strip()}\n"
    row = dict(frontmatter)
    row["source_path"] = relative
    row["content_sha256"] = store.payload_sha256(payload)
    content = f"{store.format_frontmatter(row, order=FRONTMATTER_ORDER)}\n\n{payload}"
    try:
        _path, created = store.create_or_keep(vault_root, relative, content)
    except store.TemporalStoreError as exc:
        raise EraIdentityError(getattr(exc, "code", "") or "era_record_unreadable", str(exc)) from exc
    record = read_era_record(vault_root, relative)
    if record is None:  # pragma: no cover - the create above guarantees it
        raise EraIdentityError("era_record_unreadable", f"{relative} vanished during filing")
    return record, created


def file_era_identity(
    vault_root: str | Path,
    *,
    operation_id: object,
    origin: str = "person",
    era_kind: object = None,
    legacy_slug: object = None,
    session_ref: object = None,
    turn_ref: object = None,
    author: object = None,
    occurred_at: object = None,
    label_hint: object = None,
) -> tuple[dict, bool]:
    """Ensure this act's era exists. Returns ``(record, created)``.

    ``label_hint`` is prose for the body only — a directory listing that says
    ``era-3f2a…`` and nothing else is unreadable by the human who has to
    audit it. It touches no identity: the digest is over the operation id, so
    the same act with two different hints is still ONE era and the second
    filing writes nothing.
    """
    key = collapsed_text(operation_id)
    era_id = era_id_for(key)
    where = collapsed_text(origin) or "person"
    if where not in ERA_ORIGINS:
        raise EraIdentityError("era_origin_unknown", f"unknown era origin: {origin!r}")
    kind = collapsed_text(era_kind)
    if kind and kind not in ERA_KINDS:
        raise EraIdentityError("era_kind_unknown", f"an era is {' or '.join(ERA_KINDS)}; got {era_kind!r}")

    hint = collapsed_text(label_hint)
    heading = f"Era — {hint}" if hint else f"Era {era_id}"
    prose = (
        f"An era with the opaque identity `{era_id}`, created by `{key}`.\n\n"
        "Its label, its aliases and its kind are decision records on this id "
        "and are not part of it: renaming this era mints nothing and loses "
        "nothing."
    )
    frontmatter: dict = {
        "title": heading,
        "type": ERA_IDENTITY_TYPE,
        "source_id": f"era:{era_digest(era_id)}",
        "source_medium": collapsed_text(author) or "owner",
        "era_id": era_id,
        "origin": where,
        "creation_operation_id": key,
        "captured_at": normalized_timestamp(occurred_at, error=EraIdentityError),
        "visibility": "owner_only",
        "status": "raw",
        "immutable": True,
        "schema_version": SCHEMA_VERSION,
    }
    if kind:
        frontmatter["era_kind"] = kind
    slug = collapsed_text(legacy_slug)
    if slug:
        frontmatter["legacy_slug"] = slug
    for name, value in (("session_ref", session_ref), ("turn_ref", turn_ref)):
        text = collapsed_text(value)
        if text:
            frontmatter[name] = text
    return _publish(
        vault_root,
        era_relative_path(era_id),
        frontmatter=frontmatter,
        heading=heading,
        prose=prose,
    )


def label_digest(
    *, era_id: object, label: object, aliases: Sequence[str] = (), supersedes: object = None
) -> str:
    """The label decision's identity (:data:`ERA_LABEL_IDENTITY_KEYS`)."""
    payload = {
        "era_id": collapsed_text(era_id),
        "label": collapsed_text(label),
        "aliases": _label_list(aliases),
        "supersedes": collapsed_text(supersedes) or None,
    }
    return digest_id(
        "era_label", {key: payload[key] for key in ERA_LABEL_IDENTITY_KEYS}
    ).split(":", 1)[1]


def kind_digest(*, era_id: object, era_kind: object, supersedes: object = None) -> str:
    """The kind decision's identity (:data:`ERA_KIND_IDENTITY_KEYS`)."""
    payload = {
        "era_id": collapsed_text(era_id),
        "era_kind": collapsed_text(era_kind),
        "supersedes": collapsed_text(supersedes) or None,
    }
    return digest_id(
        "era_kind", {key: payload[key] for key in ERA_KIND_IDENTITY_KEYS}
    ).split(":", 1)[1]


def file_era_label(
    vault_root: str | Path,
    *,
    era_id: object,
    label: object,
    aliases: Iterable[str] = (),
    supersedes: object = None,
    author: object = None,
    occurred_at: object = None,
    reason: object = None,
) -> tuple[dict, bool]:
    """Name (or rename) an era. Returns ``(record, created)``.

    A rename is a NEW label record naming its predecessor in ``supersedes``.
    The old record keeps every byte — which is what makes "what did I used to
    call this?" answerable, and what makes T-NE-17 (rename preserves the
    ``era_id``, its memberships, work items, links and sessions) true by
    construction rather than by care.
    """
    era = collapsed_text(era_id)
    era_digest(era)  # guard
    text = collapsed_text(label)
    if not text:
        raise EraIdentityError("era_label_required", "a label record carries a label")
    if len(text) > MAX_LABEL_CHARS:
        raise EraIdentityError(
            "era_label_too_long", f"a label is {len(text)} chars; that is a sentence"
        )
    alias_list = _label_list(aliases)
    previous = collapsed_text(supersedes) or None
    digest = label_digest(era_id=era, label=text, aliases=alias_list, supersedes=previous)

    heading = f"Era label — {text}"
    prose = collapsed_text(reason) or (
        f"“{text}” is what this era is called."
        + (f" Also answers to: {', '.join(alias_list)}." if alias_list else "")
        + (f" Replaces label decision {previous}." if previous else "")
    )
    frontmatter: dict = {
        "title": heading,
        "type": ERA_LABEL_TYPE,
        "source_id": f"era_label:{digest}",
        "source_medium": collapsed_text(author) or "owner",
        "era_id": era,
        "label": text,
        "aliases": alias_list,
        "captured_at": normalized_timestamp(occurred_at, error=EraIdentityError),
        "visibility": "owner_only",
        "status": "raw",
        "immutable": True,
        "schema_version": SCHEMA_VERSION,
    }
    if previous:
        frontmatter["supersedes"] = previous
    return _publish(
        vault_root,
        era_label_relative_path(era, digest),
        frontmatter=frontmatter,
        heading=heading,
        prose=prose,
    )


def file_era_kind(
    vault_root: str | Path,
    *,
    era_id: object,
    era_kind: object,
    supersedes: object = None,
    author: object = None,
    occurred_at: object = None,
    reason: object = None,
) -> tuple[dict, bool]:
    """Decide (or flip) stretch vs thread. Returns ``(record, created)``."""
    era = collapsed_text(era_id)
    era_digest(era)  # guard
    kind = collapsed_text(era_kind)
    if kind not in ERA_KINDS:
        raise EraIdentityError(
            "era_kind_unknown", f"an era is {' or '.join(ERA_KINDS)}; got {era_kind!r}"
        )
    previous = collapsed_text(supersedes) or None
    digest = kind_digest(era_id=era, era_kind=kind, supersedes=previous)

    heading = f"Era kind — {kind}"
    prose = collapsed_text(reason) or (
        "A stretch of the life axis with a beginning and an end."
        if kind == "stretch"
        else "A recurring presence rather than a stretch; it has no honest end."
    ) + (f" Replaces kind decision {previous}." if previous else "")
    frontmatter: dict = {
        "title": heading,
        "type": ERA_KIND_TYPE,
        "source_id": f"era_kind:{digest}",
        "source_medium": collapsed_text(author) or "owner",
        "era_id": era,
        "era_kind": kind,
        "captured_at": normalized_timestamp(occurred_at, error=EraIdentityError),
        "visibility": "owner_only",
        "status": "raw",
        "immutable": True,
        "schema_version": SCHEMA_VERSION,
    }
    if previous:
        frontmatter["supersedes"] = previous
    return _publish(
        vault_root,
        era_kind_relative_path(era, digest),
        frontmatter=frontmatter,
        heading=heading,
        prose=prose,
    )


# --------------------------------------------------------------------------
# Reading
# --------------------------------------------------------------------------

_TYPES = {ERA_IDENTITY_TYPE, ERA_LABEL_TYPE, ERA_KIND_TYPE}


def read_era_record(vault_root: str | Path, relative: str) -> dict | None:
    """One era record back as a dict, or ``None`` when the file is not one of ours.

    Tolerant by the substrate's own rule (compat rule 2): a file we cannot
    read as an era record is not an exception, it is not an era record. The
    ``content_sha256`` IS verified, because a record whose body drifted under
    the decisions that cite it is a named failure and never a shrug.
    """
    content = store.read_store_text(vault_root, relative)
    if content is None:
        return None
    metadata, body = store.split_frontmatter(content)
    if not metadata or collapsed_text(metadata.get("type")) not in _TYPES:
        return None
    declared = collapsed_text(metadata.get("content_sha256")).lower()
    actual = store.payload_sha256(body)
    if declared and declared != actual:
        raise EraIdentityError(
            "era_record_unreadable",
            f"{relative} no longer matches the digest its frontmatter declares",
            detail={"declared": declared, "actual": actual},
        )
    row = dict(metadata)
    row["relative_path"] = relative
    row["aliases"] = _as_list(metadata.get("aliases"))
    row["body"] = body.strip()
    return row


def _as_list(value: object) -> list[str]:
    if isinstance(value, (list, tuple)):
        return [collapsed_text(item) for item in value if collapsed_text(item)]
    text = collapsed_text(value)
    if not text or text in {"[]", "-"}:
        return []
    return [part.strip() for part in text.split(",") if part.strip()]


def _era_paths(vault_root: str | Path) -> list[str]:
    root = store.store_path(vault_root, ERA_SOURCES_DIR)
    if not root.is_dir():
        return []
    return sorted(
        f"{ERA_SOURCES_DIR}/{path.relative_to(root).as_posix()}"
        for path in root.rglob("*.md")
        if path.is_file()
    )


def load_era_records(vault_root: str | Path, *, kind: object = None) -> list[dict]:
    """Every era record in the vault, in path order. ``kind`` filters by ``type``."""
    wanted = collapsed_text(kind)
    rows = []
    for relative in _era_paths(vault_root):
        record = read_era_record(vault_root, relative)
        if record is None:
            continue
        if wanted and collapsed_text(record.get("type")) != wanted:
            continue
        rows.append(record)
    return rows


def load_era_identities(vault_root: str | Path) -> list[dict]:
    return load_era_records(vault_root, kind=ERA_IDENTITY_TYPE)


def load_era_labels(vault_root: str | Path) -> list[dict]:
    return load_era_records(vault_root, kind=ERA_LABEL_TYPE)


def load_era_kinds(vault_root: str | Path) -> list[dict]:
    return load_era_records(vault_root, kind=ERA_KIND_TYPE)


def _newest_active(records: Sequence[dict], *, digest_of) -> dict | None:
    """The one decision that counts: the record nothing supersedes.

    Superseded ids are collected first and the survivors are then ordered by
    ``captured_at`` with the record's own digest as the tie break, so the
    answer never depends on directory order. Several survivors is legitimate
    (two independent renames on two devices) and the newest wins; ZERO
    survivors means the chain is a cycle, and then the newest record wins
    outright rather than the era losing its name.
    """
    if not records:
        return None
    superseded = {
        collapsed_text(row.get("supersedes"))
        for row in records
        if collapsed_text(row.get("supersedes"))
    }
    ordered = sorted(
        records,
        key=lambda row: (collapsed_text(row.get("captured_at")), digest_of(row)),
    )
    survivors = [row for row in ordered if digest_of(row) not in superseded]
    return (survivors or ordered)[-1]


def _digest_of(record: dict) -> str:
    source_id = collapsed_text(record.get("source_id"))
    return source_id.rpartition(":")[2]


def era_views(vault_root: str | Path) -> dict:
    """``{era_id: view}`` — what each era currently IS, folded from its records.

    A view is the answer to "what is this era called, what else does it answer
    to, is it a stretch or a thread, where did it come from" — every one of
    them read off the newest active decision record and none of them stored
    twice. ``label`` may legitimately be empty: an era created before anybody
    named it is a real era with no name yet, and inventing one here would be
    the fabrication the whole design refuses.
    """
    views: dict[str, dict] = {}
    for record in load_era_identities(vault_root):
        era_id = collapsed_text(record.get("era_id"))
        if not era_id:
            continue
        views[era_id] = {
            "era_id": era_id,
            "origin": collapsed_text(record.get("origin")) or "person",
            "era_kind": collapsed_text(record.get("era_kind")),
            "legacy_slug": collapsed_text(record.get("legacy_slug")),
            "creation_operation_id": collapsed_text(record.get("creation_operation_id")),
            "created_at": collapsed_text(record.get("captured_at")),
            "label": "",
            "aliases": [],
            "identity_path": record.get("relative_path"),
            "label_path": None,
            "kind_path": None,
        }
    by_era_label: dict[str, list[dict]] = {}
    for record in load_era_labels(vault_root):
        by_era_label.setdefault(collapsed_text(record.get("era_id")), []).append(record)
    by_era_kind: dict[str, list[dict]] = {}
    for record in load_era_kinds(vault_root):
        by_era_kind.setdefault(collapsed_text(record.get("era_id")), []).append(record)

    for era_id, view in views.items():
        label = _newest_active(by_era_label.get(era_id, ()), digest_of=_digest_of)
        if label is not None:
            view["label"] = collapsed_text(label.get("label"))
            view["aliases"] = list(label.get("aliases") or ())
            view["label_path"] = label.get("relative_path")
        kind = _newest_active(by_era_kind.get(era_id, ()), digest_of=_digest_of)
        if kind is not None:
            view["era_kind"] = collapsed_text(kind.get("era_kind"))
            view["kind_path"] = kind.get("relative_path")
    return dict(sorted(views.items()))


def label_index(views: object) -> dict:
    """``{normalized name: (era_id, …)}`` over labels AND aliases.

    A tuple, not a single id, because *two eras sharing an alias is a real
    state* and the binder's whole correctness rests on seeing it. §4.3: two
    candidates means NO bind and an `identity_uncertain` work item naming
    both — which is only possible if this function refuses to pick one.
    """
    rows = views.values() if isinstance(views, dict) else (views or ())
    index: dict[str, list[str]] = {}
    for view in rows:
        if not isinstance(view, dict):
            continue
        era_id = collapsed_text(view.get("era_id"))
        if not era_id:
            continue
        names = [view.get("label"), *(view.get("aliases") or ())]
        for name in names:
            key = normalize_label(name)
            if not key:
                continue
            bucket = index.setdefault(key, [])
            if era_id not in bucket:
                bucket.append(era_id)
    return {key: tuple(sorted(value)) for key, value in sorted(index.items())}


# --------------------------------------------------------------------------
# Migration (design §4.1)
# --------------------------------------------------------------------------

#: The batch label a migration uses when the caller names none. It is part of
#: the operation id, so it is part of every migrated era's identity — which is
#: why it is a NAMED default rather than a timestamp: a timestamp would give
#: the same roster row a new era id on every run.
DEFAULT_MIGRATION_BATCH = "1"


def _period_rows(roster_snapshot: object) -> list[dict]:
    rows: list[dict] = []
    for roster in roster_snapshot or ():
        if not isinstance(roster, dict) or collapsed_text(roster.get("type")) != "period":
            continue
        rows.extend(row for row in (roster.get("entities") or ()) if isinstance(row, dict))
    return rows


def _is_age_band(row: dict) -> bool:
    import cross_dating as cd  # noqa: PLC0415

    names = [row.get("name"), row.get("slug"), *(row.get("aliases") or ())]
    return any(cd.age_frame_band_of(name) for name in names)


#: Roster fields that look like authority and are NOT imported as any (§4.1).
#: They are counted and reported so "we dropped your dates" is a stated fact
#: rather than a silence, and never filed, because a date nobody said is not a
#: claim and an era dated by its membership is the original defect.
LEGACY_DATE_FIELDS = ("chrono", "approximate_dates", "start", "end", "years")


def migrate_legacy_periods(
    vault_root: str | Path,
    *,
    roster_snapshot: object,
    batch: object = DEFAULT_MIGRATION_BATCH,
    dry_run: bool = True,
    now: object = None,
) -> dict:
    """One identity + one label per `page_eligible` non-age roster period.

    Design §4.1, and every clause of it is a refusal:

    * **age-band rows are skipped** — `Childhood`, `My 20s` and their kin are
      E1's calculated frames and contribute ALIASES to those frames, never an
      era (§3.5). Migrating one would mint a second, person-made "My 20s"
      that could then disagree with the arithmetic.
    * **no roster date is imported.** Not `chrono`, not `approximate_dates`,
      not a span the monthly model wrote. Every one found is reported under
      ``unsupported_legacy_dates`` and left where it is. An era's dates come
      from claims or the era is undated, and undated is honest.
    * **the wiki page keeps its slug path.** Nothing here moves a file.
    * **duplicates are reported, not merged.** Two rows normalizing to one
      label are two identities today and one identity-resolution question
      later (§4.1) — merging them here would be label-as-identity wearing a
      different hat.

    ``dry_run`` writes NOTHING and returns the same report, so the report can
    be read before the vault moves.
    """
    report: dict = {
        "batch": collapsed_text(batch) or DEFAULT_MIGRATION_BATCH,
        "dry_run": bool(dry_run),
        "mapped": {},
        "aliases": {},
        "orphans": [],
        "duplicates": {},
        "unsupported_legacy_dates": {},
        "skipped_age_bands": [],
        "skipped_not_page_eligible": [],
        "created_identities": 0,
        "created_labels": 0,
    }
    by_label: dict[str, list[str]] = {}
    for row in _period_rows(roster_snapshot):
        name = collapsed_text(row.get("name"))
        slug = collapsed_text(row.get("slug"))
        if _is_age_band(row):
            report["skipped_age_bands"].append(slug or name)
            continue
        if not row.get("page_eligible"):
            report["skipped_not_page_eligible"].append(slug or name)
            continue
        if not slug:
            report["orphans"].append(name or "(unnamed period)")
            continue
        operation = migration_operation_id(report["batch"], slug)
        era_id = era_id_for(operation)
        aliases = _label_list(row.get("aliases") or ())
        report["mapped"][slug] = era_id
        if aliases:
            report["aliases"][slug] = aliases
        found = {
            field: row[field]
            for field in LEGACY_DATE_FIELDS
            if row.get(field) not in (None, "", [], {})
        }
        if found:
            report["unsupported_legacy_dates"][slug] = sorted(found)
        by_label.setdefault(normalize_label(name or slug), []).append(slug)

        if dry_run:
            continue
        _identity, created = file_era_identity(
            vault_root,
            operation_id=operation,
            origin="legacy_roster",
            legacy_slug=slug,
            occurred_at=now,
            label_hint=name or slug,
        )
        report["created_identities"] += int(created)
        _label, made = file_era_label(
            vault_root,
            era_id=era_id,
            label=name or slug,
            aliases=aliases,
            occurred_at=now,
            reason=(
                f"Migrated from the roster period `{slug}` (origin: legacy_roster). "
                "No roster date was imported as authority."
            ),
        )
        report["created_labels"] += int(made)

    report["duplicates"] = {
        label: sorted(slugs) for label, slugs in sorted(by_label.items()) if len(slugs) > 1
    }
    return report


def describe_migration(report: object) -> list[str]:
    """The dry-run report as lines a human reads before a vault moves."""
    row = report if isinstance(report, dict) else {}
    lines = [
        f"Era migration batch {row.get('batch')}"
        + (" (dry run — nothing written)" if row.get("dry_run") else ""),
        f"  mapped: {len(row.get('mapped') or {})} roster period(s)",
    ]
    for slug, era_id in sorted((row.get("mapped") or {}).items()):
        aliases = (row.get("aliases") or {}).get(slug) or ()
        suffix = f" (aliases: {', '.join(aliases)})" if aliases else ""
        lines.append(f"    {slug} → {era_id}{suffix}")
    for name, values in (
        ("orphans (no slug)", row.get("orphans")),
        ("skipped — age band, E1 owns these", row.get("skipped_age_bands")),
        ("skipped — not page_eligible", row.get("skipped_not_page_eligible")),
    ):
        if values:
            lines.append(f"  {name}: {', '.join(str(v) for v in values)}")
    for slug, fields in sorted((row.get("unsupported_legacy_dates") or {}).items()):
        lines.append(
            f"  unsupported legacy date on {slug}: {', '.join(fields)} — reported, NOT filed"
        )
    for label, slugs in sorted((row.get("duplicates") or {}).items()):
        lines.append(f"  duplicate label {label!r}: {', '.join(slugs)} — two identities, one question")
    if not row.get("dry_run"):
        lines.append(
            f"  wrote {row.get('created_identities')} identity record(s), "
            f"{row.get('created_labels')} label record(s)"
        )
    return lines


__all__ = [
    "DEFAULT_MIGRATION_BATCH",
    "ERA_ERROR_CODES",
    "ERA_ID_PREFIX",
    "ERA_IDENTITY_KEYS",
    "ERA_IDENTITY_TYPE",
    "ERA_KINDS",
    "ERA_KIND_IDENTITY_KEYS",
    "ERA_KIND_TYPE",
    "ERA_LABEL_IDENTITY_KEYS",
    "ERA_LABEL_TYPE",
    "ERA_ORIGINS",
    "ERA_SOURCES_DIR",
    "EraIdentityError",
    "FRONTMATTER_ORDER",
    "LEGACY_DATE_FIELDS",
    "MAX_ALIASES",
    "MAX_LABEL_CHARS",
    "describe_migration",
    "era_digest",
    "era_id_for",
    "era_kind_relative_path",
    "era_label_relative_path",
    "era_relative_path",
    "era_views",
    "file_era_identity",
    "file_era_kind",
    "file_era_label",
    "kind_digest",
    "label_digest",
    "label_index",
    "load_era_identities",
    "load_era_kinds",
    "load_era_labels",
    "load_era_records",
    "migrate_legacy_periods",
    "migration_operation_id",
    "normalize_label",
    "read_era_record",
    "turn_operation_id",
]
