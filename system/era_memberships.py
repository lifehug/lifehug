#!/usr/bin/env python3
"""Era membership assertions and display decisions — the two receipts (E2).

Eras design §2.3 rows "Membership assertion" and "Display decision". Two
immutable, content-addressed source records under ``sources/eras/``:

* ``sources/eras/memberships/<hex>.md`` (``type: era_membership``) — *"this
  thing is inside that era"*, identified by
  ``digest(member_node_id, era_node_id, relation, source_ref)``. The
  ``source_ref`` is INSIDE the identity on purpose: two independent pieces of
  evidence for one containment are two receipts and one calculated membership,
  and retracting one of them leaves the membership standing on the other
  (design §2.4, T-M-09/10).
* ``sources/eras/display/<hex>.md`` (``type: era_display``) — *"render it
  there"*, identified by ``digest(member_node_id, primary_container_id,
  supersedes)``. **Never chronology.** A display decision cannot move a date,
  an order or a membership; it decides which container a row is drawn in when
  it legitimately belongs to several.

Why a separate module rather than more of :mod:`temporal_store`
--------------------------------------------------------------

These records are not claims and they are not corrections. They are
*decisions about eras*, and E3 adds three more of exactly that shape (era
identity, label, kind) on the same directory. One module per family keeps the
receipt machine — digest, ``_create_or_keep``, frontmatter, status folding —
shared through :mod:`temporal_store` while the vocabularies stay where a
reader can find them.

What this module reuses and does not re-implement
------------------------------------------------

Every mechanical part is :mod:`temporal_store`'s and is called, not copied:
:func:`~temporal_store._create_or_keep` (write-once), :func:`
~temporal_store.format_frontmatter`, :func:`~temporal_store.payload_sha256`,
:func:`~temporal_store.read_source_ref` (a ``source_ref`` rebuilt from the
file's own bytes) and the whole correction machine —
:func:`~temporal_store.file_temporal_correction` with a scope, resolved by
*marks over an unordered set* exactly as :func:`
~temporal_store.load_ordering_constraints` resolves a move's status. No clock,
no mtime, no last-writer-wins: delete nothing, read again, get the same list.

Controlling contract: ``docs/pr-specs/eras-o-e2-memberships.md`` (O-E2a).
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Sequence

SYSTEM_DIR = Path(__file__).resolve().parent
if str(SYSTEM_DIR) not in sys.path:
    sys.path.insert(0, str(SYSTEM_DIR))

import temporal_store as store  # noqa: E402
from temporal_claims import (  # noqa: E402
    CLAIM_BASES,
    SCHEMA_VERSION,
    TemporalContractError,
    collapsed_text,
    normalized_timestamp,
    validate_evidence_span,
)

# --------------------------------------------------------------------------
# Layout and vocabulary
# --------------------------------------------------------------------------

#: Everything an era decides about itself lives here. E3 adds
#: ``sources/eras/<era_id>.md`` and the label/kind subdirectories beside these
#: two, which is why the parent is named once.
ERA_SOURCES_DIR = "sources/eras"

#: One membership assertion per independent piece of evidence.
MEMBERSHIP_SOURCES_DIR = f"{ERA_SOURCES_DIR}/memberships"

#: One display decision per member, superseded rather than edited.
DISPLAY_SOURCES_DIR = f"{ERA_SOURCES_DIR}/display"

#: Frontmatter ``type`` values this module writes and reads back.
ERA_MEMBERSHIP_TYPE = "era_membership"
ERA_DISPLAY_TYPE = "era_display"

#: E-L2d (timeline-eras design §9.1, §15.1; eras A1 as amended 2026-09-01). A
#: FRAME's own display decision — "tell My 20s by its eras" — filed beside the
#: member-level `era_display` decisions because it is the same kind of fact
#: about the same layer: presentation, superseded rather than edited, never
#: chronology. It is a separate TYPE and not a flag on `era_display` because
#: its subject is a frame rather than a member, and a reader that had to
#: branch on "which id is in `member_node_id`" would be guessing.
FRAME_DISPLAY_TYPE = "frame_display"

#: Id prefixes. They are digests, not readable strings, because unlike an age
#: frame's id (which is a deep-link key a person reads) these are never typed
#: by anybody — they are cited by other records.
ASSERTION_ID_PREFIX = "assertion"
DECISION_ID_PREFIX = "display"
FRAME_DECISION_ID_PREFIX = "frame_display"

#: What a frame's display decision may SAY (design §9.1). ``eras`` replaces
#: the frame's heading row with its era rows; ``frame`` is the default
#: presentation and is also what an undo files — a decision, not a deletion.
FRAME_DISPLAY_MODES = ("eras", "frame")

#: The mode a frame is in when nobody has decided (§9.1: *"a frame without
#: that decision renders exactly as in Frames"*).
FRAME_DISPLAY_DEFAULT_MODE = "frame"

#: What an ASSERTION may say. Deliberately narrower than
#: ``temporal_projection.MEMBERSHIP_RELATIONS``: ``overlaps`` and ``starts_in``
#: are *calculated* relations — the frame arithmetic decides them and nobody
#: asserts them — so a receipt that claimed one would be asserting a
#: derivation. A person asserts containment (``within``) or association
#: (``associated_with``) and the fold does the rest (design §2.3).
ASSERTION_RELATIONS = ("within", "associated_with")

#: The ``correction_scope`` a retraction carries when its target is a
#: membership assertion rather than a claim. The claim fold ignores such a row
#: by construction (an ``assertion:`` id matches no claim) — one correction
#: machine, three kinds of target now.
MEMBERSHIP_CORRECTION_SCOPE = "era_membership"

#: FROZEN. What makes two membership assertions the same assertion. The
#: ``source_ref`` is in the set and that is the whole design: without it two
#: independent witnesses to one containment would collapse into one receipt and
#: retracting either would silently remove the other's evidence.
MEMBERSHIP_IDENTITY_KEYS = (
    "member_node_id",
    "era_node_id",
    "relation",
    "source_ref",
)

#: FROZEN. What makes two display decisions the same decision. ``supersedes``
#: is in the set because "put it back where it was" is a genuinely new decision
#: and not a re-file of the old one.
DISPLAY_IDENTITY_KEYS = (
    "member_node_id",
    "primary_container_id",
    "supersedes",
)

#: FROZEN. What makes two frame display decisions the same decision. Same
#: shape and same reason as :data:`DISPLAY_IDENTITY_KEYS`: "put it back the
#: way it was" is a genuinely new decision, so ``supersedes`` is in the set
#: and an undo is a file of its own rather than a re-file of the first.
FRAME_DISPLAY_IDENTITY_KEYS = (
    "frame_id",
    "mode",
    "supersedes",
)

#: Cap on the explanation either record carries in its body — the same bound
#: :data:`temporal_store.MOVE_REASON_MAX_CHARS` puts on a move's, for the same
#: reason: an unbounded field in an immutable source is a file nobody reviews.
REASON_MAX_CHARS = store.MOVE_REASON_MAX_CHARS

ERROR_CODES = (
    "membership_member_required",
    "membership_era_required",
    "membership_relation_unknown",
    "membership_source_required",
    "membership_target_unsafe",
    "display_member_required",
    "display_container_required",
    "display_target_unsafe",
    "frame_display_frame_required",
    "frame_display_mode_unknown",
    "frame_display_target_unsafe",
)


class EraReceiptError(TemporalContractError):
    """A membership assertion or display decision could not be filed or read."""


# --------------------------------------------------------------------------
# Identity
# --------------------------------------------------------------------------


def _digest(payload: dict, keys: Sequence[str]) -> str:
    blob = json.dumps(
        {key: payload[key] for key in keys},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def membership_digest(
    *,
    member_node_id: object,
    era_node_id: object,
    relation: object,
    source_ref: object,
) -> str:
    """The sha256 that identifies one membership assertion.

    A pure function of what the assertion *says*, so a retried drag, a replayed
    job and an optimistic client that resends all land on one file without
    consulting an index that could itself be stale — the property
    :func:`temporal_store.move_digest` buys for a move.

    ``source_ref`` is reduced to its ``source_id`` and ``revision``: the
    evidence is the source AT that revision, and the same document at a new
    revision is genuinely new evidence.
    """
    payload = {
        "member_node_id": collapsed_text(member_node_id),
        "era_node_id": collapsed_text(era_node_id),
        "relation": collapsed_text(relation).lower(),
        "source_ref": _source_key(source_ref),
    }
    return _digest(payload, MEMBERSHIP_IDENTITY_KEYS)


def display_digest(
    *,
    member_node_id: object,
    primary_container_id: object,
    supersedes: object = None,
) -> str:
    """The sha256 that identifies one display decision."""
    payload = {
        "member_node_id": collapsed_text(member_node_id),
        "primary_container_id": collapsed_text(primary_container_id),
        "supersedes": collapsed_text(supersedes) or None,
    }
    return _digest(payload, DISPLAY_IDENTITY_KEYS)


def frame_display_digest(
    *,
    frame_id: object,
    mode: object,
    supersedes: object = None,
) -> str:
    """The sha256 that identifies one frame display decision."""
    payload = {
        "frame_id": collapsed_text(frame_id),
        "mode": collapsed_text(mode).lower(),
        "supersedes": collapsed_text(supersedes) or None,
    }
    return _digest(payload, FRAME_DISPLAY_IDENTITY_KEYS)


def _source_key(source_ref: object) -> str:
    """``<source_id>@<revision>`` — a source AT a revision, as one string."""
    row = source_ref
    if hasattr(row, "to_dict"):
        row = row.to_dict()
    if isinstance(row, str):
        return collapsed_text(row)
    if not isinstance(row, dict):
        return ""
    source_id = collapsed_text(row.get("source_id"))
    revision = collapsed_text(row.get("revision"))
    if not source_id:
        return ""
    return f"{source_id}@{revision}" if revision else source_id


def membership_relative_path(digest: str) -> str:
    """``sources/eras/memberships/<24 hex>.md``."""
    return _relative_path(MEMBERSHIP_SOURCES_DIR, digest)


def display_relative_path(digest: str) -> str:
    """``sources/eras/display/<24 hex>.md``."""
    return _relative_path(DISPLAY_SOURCES_DIR, digest)


def frame_display_relative_path(digest: str) -> str:
    """``sources/eras/display/<24 hex>.md`` — the same directory as a member's
    display decision, because they are the same kind of record about the same
    layer, and the frontmatter ``type`` is what tells the two readers apart."""
    return _relative_path(DISPLAY_SOURCES_DIR, digest)


def _relative_path(directory: str, digest: str) -> str:
    text = collapsed_text(digest).lower()
    if not store._HEX_DIGEST_RE.fullmatch(text):  # noqa: SLF001 — one regex, not two
        raise EraReceiptError(
            "unsafe_store_path", f"not a sha256 digest: {digest!r}"
        )
    return f"{directory}/{text[:store.FILENAME_DIGEST_LENGTH]}.md"


def _id_guard(value: object, prefix: str, code: str) -> str:
    target = collapsed_text(value)
    if not target.startswith(f"{prefix}:") or "/" in target or "\n" in target:
        raise EraReceiptError(code, f"not an {prefix} id: {value!r}")
    return target


def assertion_id_of(digest: str) -> str:
    """``assertion:<24 hex>`` for a membership digest."""
    return f"{ASSERTION_ID_PREFIX}:{collapsed_text(digest)[:store.FILENAME_DIGEST_LENGTH]}"


def decision_id_of(digest: str) -> str:
    """``display:<24 hex>`` for a display digest."""
    return f"{DECISION_ID_PREFIX}:{collapsed_text(digest)[:store.FILENAME_DIGEST_LENGTH]}"


def frame_decision_id_of(digest: str) -> str:
    """``frame_display:<24 hex>`` for a frame display digest."""
    return (
        f"{FRAME_DECISION_ID_PREFIX}:"
        f"{collapsed_text(digest)[:store.FILENAME_DIGEST_LENGTH]}"
    )


# --------------------------------------------------------------------------
# Membership assertions
# --------------------------------------------------------------------------


def _membership_sentence(relation: str, member: str, era: str) -> str:
    if relation == "within":
        return f"{member} belongs inside {era}."
    return f"{member} is associated with {era}."


def file_era_membership(
    vault_root: str | Path,
    *,
    member_node_id: str,
    era_node_id: str,
    source_ref: object,
    relation: str = "within",
    basis: str = "explicit",
    reason: str | None = None,
    evidence: object = (),
    member_label: str | None = None,
    era_label: str | None = None,
    title: str | None = None,
    author: str | None = None,
    occurred_at: object = None,
) -> dict:
    """File one membership assertion; return the normalized record.

    Idempotent on what the assertion *says* (:data:`MEMBERSHIP_IDENTITY_KEYS`),
    so a replayed job converges on one file. ``reason`` is optional by
    contract — a person who drags a moment into College and closes the tab has
    still said something durable — and the body then states the assertion
    itself, inventing no precision.

    ``member_label``/``era_label`` are prose for the body only. They never
    touch identity: the digest is over the node ids, so the same assertion
    labelled two ways is still one file.
    """
    member = collapsed_text(member_node_id)
    era = collapsed_text(era_node_id)
    verb = collapsed_text(relation).lower() or "within"
    if not member:
        raise EraReceiptError(
            "membership_member_required", "a membership names the thing inside"
        )
    if not era:
        raise EraReceiptError(
            "membership_era_required", "a membership names the era or frame"
        )
    if verb not in ASSERTION_RELATIONS:
        raise EraReceiptError(
            "membership_relation_unknown",
            f"an asserted membership is {', '.join(ASSERTION_RELATIONS)}; got {relation!r}",
        )
    if basis not in CLAIM_BASES:
        raise EraReceiptError("unknown_claim_basis", f"unknown basis: {basis!r}")
    key = _source_key(source_ref)
    if not key:
        raise EraReceiptError(
            "membership_source_required",
            "a membership cites the source that says so; date overlap is not evidence",
        )

    digest = membership_digest(
        member_node_id=member,
        era_node_id=era,
        relation=verb,
        source_ref=source_ref,
    )
    relative = membership_relative_path(digest)
    sentence = _membership_sentence(
        verb,
        collapsed_text(member_label) or member,
        collapsed_text(era_label) or era,
    )
    heading = collapsed_text(title) or sentence
    prose = collapsed_text(reason)[:REASON_MAX_CHARS] or sentence
    payload = f"# {heading}\n\n{prose}\n"

    raw_evidence = evidence
    if isinstance(raw_evidence, (str, dict)) or hasattr(raw_evidence, "to_dict"):
        raw_evidence = [raw_evidence]
    spans = [validate_evidence_span(span) for span in (raw_evidence or ())]

    frontmatter = {
        "title": heading,
        "type": ERA_MEMBERSHIP_TYPE,
        "source_id": f"era:membership-{digest[:store.FILENAME_DIGEST_LENGTH]}",
        "source_medium": collapsed_text(author) or "owner",
        "assertion_id": assertion_id_of(digest),
        "member_node_id": member,
        "era_node_id": era,
        "relation": verb,
        "basis": basis,
        "evidence_source_ref": key,
        "evidence": spans,
        "captured_at": normalized_timestamp(occurred_at, error=EraReceiptError),
        "visibility": "owner_only",
        "status": "raw",
        "immutable": True,
        "schema_version": SCHEMA_VERSION,
        "source_path": relative,
        "content_sha256": store.payload_sha256(payload),
    }

    store._create_or_keep(  # noqa: SLF001 — write-once, one implementation
        vault_root, relative, f"{store.format_frontmatter(frontmatter)}\n\n{payload}"
    )
    row = read_era_membership(vault_root, relative)
    if row is None:  # pragma: no cover - the create above guarantees it
        raise EraReceiptError(
            "source_frontmatter_missing", f"{relative} vanished during filing"
        )
    return row


def read_era_membership(vault_root: str | Path, relative: str) -> dict | None:
    """Read one assertion back; ``None`` when the file is not one of ours.

    The ``source_ref`` of the RECORD ITSELF is rebuilt from the file's bytes
    (:func:`temporal_store.read_source_ref`), so a hand-edited assertion is a
    different assertion and says so.
    """
    metadata = _frontmatter(vault_root, relative, ERA_MEMBERSHIP_TYPE)
    if metadata is None:
        return None
    member = collapsed_text(metadata.get("member_node_id"))
    era = collapsed_text(metadata.get("era_node_id"))
    relation = collapsed_text(metadata.get("relation")).lower()
    evidence_source = collapsed_text(metadata.get("evidence_source_ref"))
    if not member or not era or relation not in ASSERTION_RELATIONS or not evidence_source:
        return None
    own = store.read_source_ref(vault_root, relative)
    basis = collapsed_text(metadata.get("basis")) or "explicit"
    return {
        "assertion_id": collapsed_text(metadata.get("assertion_id")),
        "member_node_id": member,
        "era_node_id": era,
        "relation": relation,
        "basis": basis if basis in CLAIM_BASES else "explicit",
        "evidence_source_ref": evidence_source,
        "source_ref": own.to_dict() if own is not None else None,
        "relative_path": relative,
        "created_at": collapsed_text(metadata.get("captured_at")),
        "status": "active",
        "marks": [],
    }


def load_era_memberships(vault_root: str | Path) -> list[dict]:
    """Every filed assertion, with its status resolved. Pure and order-free.

    Status is :func:`temporal_store.load_ordering_constraints`' algorithm with
    a different scope: marks over an unordered set, strongest mark wins,
    nothing consults a clock. A retraction names ONE ``assertion_id``, so the
    calculated membership survives on whatever other receipts remain — which is
    the whole reason ``source_ref`` is inside the identity.
    """
    return _load(
        vault_root,
        directory=MEMBERSHIP_SOURCES_DIR,
        reader=read_era_membership,
        id_key="assertion_id",
        scope=MEMBERSHIP_CORRECTION_SCOPE,
    )


def active_era_memberships(vault_root: str | Path) -> list[dict]:
    """The assertions the fold must honour — status ``active``, in id order."""
    return [row for row in load_era_memberships(vault_root) if row["status"] == "active"]


def retract_era_membership(
    vault_root: str | Path,
    assertion_id: str,
    *,
    reason: str,
    title: str | None = None,
    author: str | None = None,
    occurred_at: object = None,
) -> object:
    """Undo ONE membership assertion — mark it, keep every byte of it.

    The receipt stays on disk with its evidence and this correction explains
    that it no longer stands. It rides the correction machine that already
    exists, scoped to :data:`MEMBERSHIP_CORRECTION_SCOPE` so the claim fold —
    which would find no claim by this id anyway — is not asked to guess what
    kind of thing was retracted.
    """
    target = _id_guard(assertion_id, ASSERTION_ID_PREFIX, "membership_target_unsafe")
    return store.file_temporal_correction(
        vault_root,
        kind="retract",
        claim_ids=[target],
        reason=reason,
        scope=MEMBERSHIP_CORRECTION_SCOPE,
        title=title or f"Undo membership {target}",
        author=author,
        occurred_at=occurred_at,
    )


# --------------------------------------------------------------------------
# Display decisions
# --------------------------------------------------------------------------


def file_era_display(
    vault_root: str | Path,
    *,
    member_node_id: str,
    primary_container_id: str,
    reason: str | None = None,
    evidence: object = (),
    supersedes: str | None = None,
    member_label: str | None = None,
    container_label: str | None = None,
    title: str | None = None,
    author: str | None = None,
    occurred_at: object = None,
) -> dict:
    """File one display decision; return the normalized record.

    A display decision says WHERE a row is drawn when it legitimately belongs
    to several containers. It is not chronology and it cannot become
    chronology: nothing in the fold reads it for a date, an order or a
    membership, and the projection carries it only as ``display_role``.

    Correcting one is SUPERSESSION, never an edit: file again naming the record
    being replaced. The old bytes stay and gain ``superseded``.
    """
    member = collapsed_text(member_node_id)
    container = collapsed_text(primary_container_id)
    if not member:
        raise EraReceiptError(
            "display_member_required", "a display decision names the row it moves"
        )
    if not container:
        raise EraReceiptError(
            "display_container_required", "a display decision names the container"
        )
    previous = (
        _id_guard(supersedes, DECISION_ID_PREFIX, "display_target_unsafe")
        if supersedes
        else None
    )

    digest = display_digest(
        member_node_id=member,
        primary_container_id=container,
        supersedes=previous,
    )
    relative = display_relative_path(digest)
    sentence = (
        f"{collapsed_text(member_label) or member} is shown in "
        f"{collapsed_text(container_label) or container}."
    )
    heading = collapsed_text(title) or sentence
    prose = collapsed_text(reason)[:REASON_MAX_CHARS] or sentence
    payload = f"# {heading}\n\n{prose}\n"

    raw_evidence = evidence
    if isinstance(raw_evidence, (str, dict)) or hasattr(raw_evidence, "to_dict"):
        raw_evidence = [raw_evidence]
    spans = [validate_evidence_span(span) for span in (raw_evidence or ())]

    frontmatter = {
        "title": heading,
        "type": ERA_DISPLAY_TYPE,
        "source_id": f"era:display-{digest[:store.FILENAME_DIGEST_LENGTH]}",
        "source_medium": collapsed_text(author) or "owner",
        "decision_id": decision_id_of(digest),
        "member_node_id": member,
        "primary_container_id": container,
        "evidence": spans,
        "captured_at": normalized_timestamp(occurred_at, error=EraReceiptError),
        "visibility": "owner_only",
        "status": "raw",
        "immutable": True,
        "schema_version": SCHEMA_VERSION,
        "source_path": relative,
        "content_sha256": store.payload_sha256(payload),
    }
    if previous:
        frontmatter["supersedes"] = previous

    store._create_or_keep(  # noqa: SLF001
        vault_root, relative, f"{store.format_frontmatter(frontmatter)}\n\n{payload}"
    )
    row = read_era_display(vault_root, relative)
    if row is None:  # pragma: no cover
        raise EraReceiptError(
            "source_frontmatter_missing", f"{relative} vanished during filing"
        )
    return row


def read_era_display(vault_root: str | Path, relative: str) -> dict | None:
    """Read one display decision back; ``None`` when the file is not ours."""
    metadata = _frontmatter(vault_root, relative, ERA_DISPLAY_TYPE)
    if metadata is None:
        return None
    member = collapsed_text(metadata.get("member_node_id"))
    container = collapsed_text(metadata.get("primary_container_id"))
    if not member or not container:
        return None
    own = store.read_source_ref(vault_root, relative)
    return {
        "decision_id": collapsed_text(metadata.get("decision_id")),
        "member_node_id": member,
        "primary_container_id": container,
        "supersedes": collapsed_text(metadata.get("supersedes")) or None,
        "source_ref": own.to_dict() if own is not None else None,
        "relative_path": relative,
        "created_at": collapsed_text(metadata.get("captured_at")),
        "status": "active",
        "marks": [],
    }


def load_era_displays(vault_root: str | Path) -> list[dict]:
    """Every filed display decision, with its status resolved.

    A decision named by another active decision's ``supersedes`` is superseded,
    exactly as one move supersedes another. So ``active_era_displays`` is at
    most one decision per member without anybody deleting a file.
    """
    return _load(
        vault_root,
        directory=DISPLAY_SOURCES_DIR,
        reader=read_era_display,
        id_key="decision_id",
        scope=MEMBERSHIP_CORRECTION_SCOPE,
        supersedes_key="supersedes",
    )


def active_era_displays(vault_root: str | Path) -> list[dict]:
    """The display decisions rendering must honour — status ``active``."""
    return [row for row in load_era_displays(vault_root) if row["status"] == "active"]


# --------------------------------------------------------------------------
# Frame display decisions (E-L2d, design §9.1)
# --------------------------------------------------------------------------

FRAME_DISPLAY_RULE_TEXT = (
    "A frame's row is replaced by its era rows only by a per-frame decision "
    "the person confirmed from a system proposal, reversible, with the frame "
    "kept on the ruler, as a tag on each era row and as the name of the row "
    "holding any years no era claims. No coverage arithmetic decides "
    "presentation: tiling PROPOSES and the person decides. Undo is a "
    "superseding `frame` decision, never a deletion."
)


def file_frame_display(
    vault_root: str | Path,
    *,
    frame_id: str,
    mode: str,
    reason: str | None = None,
    evidence: object = (),
    supersedes: str | None = None,
    frame_label: str | None = None,
    title: str | None = None,
    author: str | None = None,
    occurred_at: object = None,
) -> dict:
    """File one frame display decision; return the normalized record.

    :data:`FRAME_DISPLAY_RULE_TEXT`, applied. Presentation and nothing else:
    the fold reads it for one published string per frame and for no date, no
    order and no membership, exactly as it reads a member's `era_display`.

    Idempotent by digest — filing the same decision twice writes one file, so
    a retried tap, a replayed job and an optimistic client all land on the
    same record — and corrected by SUPERSESSION, never by an edit.
    """
    frame = collapsed_text(frame_id)
    chosen = collapsed_text(mode).lower()
    if not frame:
        raise EraReceiptError(
            "frame_display_frame_required", "a frame display decision names its frame"
        )
    if chosen not in FRAME_DISPLAY_MODES:
        raise EraReceiptError(
            "frame_display_mode_unknown",
            f"a frame is told by {' or '.join(FRAME_DISPLAY_MODES)}; got {mode!r}",
        )
    previous = (
        _id_guard(supersedes, FRAME_DECISION_ID_PREFIX, "frame_display_target_unsafe")
        if supersedes
        else None
    )

    digest = frame_display_digest(frame_id=frame, mode=chosen, supersedes=previous)
    relative = frame_display_relative_path(digest)
    name = collapsed_text(frame_label) or frame
    sentence = (
        f"{name} is told by its eras."
        if chosen == "eras"
        else f"{name} is told as one frame."
    )
    heading = collapsed_text(title) or sentence
    prose = collapsed_text(reason)[:REASON_MAX_CHARS] or sentence
    payload = f"# {heading}\n\n{prose}\n"

    raw_evidence = evidence
    if isinstance(raw_evidence, (str, dict)) or hasattr(raw_evidence, "to_dict"):
        raw_evidence = [raw_evidence]
    spans = [validate_evidence_span(span) for span in (raw_evidence or ())]

    frontmatter = {
        "title": heading,
        "type": FRAME_DISPLAY_TYPE,
        "source_id": f"era:frame-display-{digest[:store.FILENAME_DIGEST_LENGTH]}",
        "source_medium": collapsed_text(author) or "owner",
        "decision_id": frame_decision_id_of(digest),
        "frame_id": frame,
        "mode": chosen,
        "evidence": spans,
        "captured_at": normalized_timestamp(occurred_at, error=EraReceiptError),
        "visibility": "owner_only",
        "status": "raw",
        "immutable": True,
        "schema_version": SCHEMA_VERSION,
        "source_path": relative,
        "content_sha256": store.payload_sha256(payload),
    }
    if previous:
        frontmatter["supersedes"] = previous

    store._create_or_keep(  # noqa: SLF001
        vault_root, relative, f"{store.format_frontmatter(frontmatter)}\n\n{payload}"
    )
    row = read_frame_display(vault_root, relative)
    if row is None:  # pragma: no cover
        raise EraReceiptError(
            "source_frontmatter_missing", f"{relative} vanished during filing"
        )
    return row


def read_frame_display(vault_root: str | Path, relative: str) -> dict | None:
    """Read one frame display decision back; ``None`` when it is not ours."""
    metadata = _frontmatter(vault_root, relative, FRAME_DISPLAY_TYPE)
    if metadata is None:
        return None
    frame = collapsed_text(metadata.get("frame_id"))
    mode = collapsed_text(metadata.get("mode")).lower()
    if not frame or mode not in FRAME_DISPLAY_MODES:
        return None
    own = store.read_source_ref(vault_root, relative)
    return {
        "decision_id": collapsed_text(metadata.get("decision_id")),
        "frame_id": frame,
        "mode": mode,
        "supersedes": collapsed_text(metadata.get("supersedes")) or None,
        "source_ref": own.to_dict() if own is not None else None,
        "relative_path": relative,
        "created_at": collapsed_text(metadata.get("captured_at")),
        "status": "active",
        "marks": [],
    }


def load_frame_displays(vault_root: str | Path) -> list[dict]:
    """Every filed frame display decision, with its status resolved.

    Same supersession fold as :func:`load_era_displays`, so an undo leaves
    both files on disk and exactly one of them active.
    """
    return _load(
        vault_root,
        directory=DISPLAY_SOURCES_DIR,
        reader=read_frame_display,
        id_key="decision_id",
        scope=MEMBERSHIP_CORRECTION_SCOPE,
        supersedes_key="supersedes",
    )


def active_frame_displays(vault_root: str | Path) -> list[dict]:
    """The frame display decisions rendering must honour — status ``active``."""
    return [row for row in load_frame_displays(vault_root) if row["status"] == "active"]


def frame_display_rows_by_frame(decisions: object) -> dict:
    """``{frame_id: decision row}`` over active decisions — the fold's lookup.

    Later decisions win over earlier ones for one frame if a vault somehow
    holds two actives (two independent chains, neither superseding the other);
    ordering is by ``created_at`` then ``decision_id``, so the answer is the
    same on every rebuild rather than filesystem-ordered.
    """
    rows = [row for row in (decisions or ())
            if isinstance(row, dict) and collapsed_text(row.get("frame_id"))
            and collapsed_text(row.get("mode")).lower() in FRAME_DISPLAY_MODES]
    chosen: dict[str, dict] = {}
    for row in sorted(rows, key=lambda item: (collapsed_text(item.get("created_at")),
                                              collapsed_text(item.get("decision_id")))):
        chosen[collapsed_text(row.get("frame_id"))] = dict(row)
    return chosen


def frame_display_modes(decisions: object) -> dict:
    """``{frame_id: mode}`` — the same fold, reduced to the one string a
    caller that only renders needs."""
    return {frame: collapsed_text(row.get("mode")).lower()
            for frame, row in frame_display_rows_by_frame(decisions).items()}


# --------------------------------------------------------------------------
# Shared reading
# --------------------------------------------------------------------------


def _frontmatter(vault_root: str | Path, relative: str, expected: str) -> dict | None:
    content = store._read_text(vault_root, relative)  # noqa: SLF001
    if content is None:
        return None
    metadata, _body = store.split_frontmatter(content)
    if not metadata or collapsed_text(metadata.get("type")) != expected:
        return None
    return metadata


def _load(
    vault_root: str | Path,
    *,
    directory: str,
    reader,
    id_key: str,
    scope: str,
    supersedes_key: str | None = None,
) -> list[dict]:
    root = Path(vault_root)
    base = store.store_path(root, directory)
    if not base.is_dir():
        return []

    rows: dict[str, dict] = {}
    for path in sorted(base.glob("*.md")):
        if path.is_symlink() or not path.is_file():
            continue
        row = reader(root, path.relative_to(root).as_posix())
        if row is None or not row.get(id_key):
            continue
        rows.setdefault(row[id_key], row)

    marks: dict[str, list[dict]] = {}
    for correction in store.load_temporal_corrections(root):
        if correction.scope != scope:
            continue
        status = store.STATUS_BY_CORRECTION_KIND.get(correction.kind)
        if not status:
            continue
        for target in correction.claim_ids:
            marks.setdefault(target, []).append(
                store._mark(status, correction.reason, correction.correction_id)  # noqa: SLF001
            )

    if supersedes_key:
        for row in rows.values():
            previous = row.get(supersedes_key)
            if previous and previous in rows:
                marks.setdefault(previous, []).append(
                    store._mark(  # noqa: SLF001
                        "superseded", "a later decision replaced it", row[id_key]
                    )
                )

    resolved: list[dict] = []
    for key in sorted(rows):
        row = dict(rows[key])
        own = sorted(
            {store._mark_key(mark): mark  # noqa: SLF001
             for mark in marks.get(key, ())}.values(),
            key=store._mark_key,  # noqa: SLF001
        )
        row["status"] = store._strongest(own)  # noqa: SLF001
        row["marks"] = own
        resolved.append(row)
    return resolved


__all__ = [
    "ASSERTION_ID_PREFIX",
    "FRAME_DECISION_ID_PREFIX",
    "FRAME_DISPLAY_DEFAULT_MODE",
    "FRAME_DISPLAY_IDENTITY_KEYS",
    "FRAME_DISPLAY_MODES",
    "FRAME_DISPLAY_RULE_TEXT",
    "FRAME_DISPLAY_TYPE",
    "active_frame_displays",
    "file_frame_display",
    "frame_decision_id_of",
    "frame_display_digest",
    "frame_display_modes",
    "frame_display_relative_path",
    "frame_display_rows_by_frame",
    "load_frame_displays",
    "read_frame_display",
    "ASSERTION_RELATIONS",
    "DECISION_ID_PREFIX",
    "DISPLAY_IDENTITY_KEYS",
    "DISPLAY_SOURCES_DIR",
    "ERA_DISPLAY_TYPE",
    "ERA_MEMBERSHIP_TYPE",
    "ERA_SOURCES_DIR",
    "ERROR_CODES",
    "EraReceiptError",
    "MEMBERSHIP_CORRECTION_SCOPE",
    "MEMBERSHIP_IDENTITY_KEYS",
    "MEMBERSHIP_SOURCES_DIR",
    "REASON_MAX_CHARS",
    "active_era_displays",
    "active_era_memberships",
    "assertion_id_of",
    "decision_id_of",
    "display_digest",
    "display_relative_path",
    "file_era_display",
    "file_era_membership",
    "load_era_displays",
    "load_era_memberships",
    "membership_digest",
    "membership_relative_path",
    "read_era_display",
    "read_era_membership",
    "retract_era_membership",
]
