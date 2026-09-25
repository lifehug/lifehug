#!/usr/bin/env python3
"""Receipts, the fold, and the promoted source — truth you can rebuild (v221).

:mod:`temporal_claims` (v220) says what a temporal interpretation *is*. This
module is the only place that puts one on disk and reads it back. It is wave B
of the audited final timeline build plan: the immutable receipt store, the pure
deterministic fold that turns receipts and corrections into the active claim
index, the correction records that supersede and retract, and the owner's
amendment-2/option-B promotion that gives a conversational message a durable
vault source *before* any claim cites it.

The one invariant this module exists to make true
------------------------------------------------

**Delete the active index, rebuild it from the checked-in receipts, and get the
same bytes.** :func:`fold_active_index` is a pure function of what is on disk —
no clock, no model, no iteration-order luck, and deliberately no ``generated_at``
field, because a timestamp in a rebuildable artifact is a byte that cannot be
reproduced and therefore a lie about what "identical" means. Everything else
here is arranged to protect that property:

* the fold's every collection is sorted by a stable key before it is emitted;
* status is resolved by *precedence over an unordered set of marks*, never by
  "last writer wins", so the order corrections are discovered in cannot change
  the answer;
* a receipt is written once and never rewritten — re-extraction is a new
  interpretation at a new path (:func:`temporal_claims.receipt_relative_path`),
  so yesterday's reading of the same sentence is still on disk with its
  provenance intact;
* the index is a *materialized view*. It is the one file here that may be
  deleted at any time. Receipts and correction sources are the truth.

Nothing is ever deleted
-----------------------

A superseded, retracted or disputed claim keeps its record and gains a status
plus the marks that explain it. Plan §2.5 forbids silent resolution, and a fold
that dropped the losing claim would be exactly that — the contradiction would
stop being visible the moment it was resolved, and nobody could ever ask why.

Order of operations, and the crash between them
-----------------------------------------------

A message that produces claims is filed in exactly this order:

1. :func:`promote_conversational_source` writes the durable vault source;
2. :func:`write_receipt` writes the receipt that cites it.

Both are idempotent — the source's path is a pure function of the utterance's
identity and the receipt's path is a pure function of (source revision,
extractor) — so a crash between them leaves a re-runnable state and never a
receipt citing a source that does not exist. :func:`file_message_extraction`
performs both in that order for callers who should not have to remember it.
:func:`write_receipt` also refuses, by name, a receipt whose source declares a
``source_path`` that is not in the vault.

What this module does not do
----------------------------

It does not call a model, does not resolve a person, does not compute an
interval from an age and does not build the calculated timeline — those are
waves C and D. It also does not fold :class:`temporal_claims.OrderingConstraint`
records; the constraint contract exists and a correction source is its natural
carrier, but constraint resolution belongs with the projection that consumes it.

Controlling contract: the audited final timeline build plan, §4.2 (receipts and
the fold) and §4.1 (authority), plus owner amendment 2 / option B.
"""

from __future__ import annotations

import contextlib
import contextvars
import copy
import hashlib
import json
import os
import re
import stat
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable, Sequence

SYSTEM_DIR = Path(__file__).resolve().parent
if str(SYSTEM_DIR) not in sys.path:
    sys.path.insert(0, str(SYSTEM_DIR))

from temporal_claims import (  # noqa: E402
    ACTIVE_INDEX_FILE,
    TEMPORAL_STATE_DIR,
    CLAIM_STATUSES,
    CONSTRAINT_ID_PREFIX,
    CONSTRAINT_RELATIONS,
    CORRECTION_SOURCES_DIR,
    RECEIPTS_DIR,
    SCHEMA_VERSION,
    ExtractionReceipt,
    SourceRef,
    TemporalContractError,
    collapsed_text,
    derive_extraction_idempotency_key,
    digest_id,
    extractor_identity,
    normalized_timestamp,
    receipt_from_dict,
    receipt_relative_path,
    validate_evidence_span,
    validate_extraction_receipt,
    validate_ordering_constraint,
    validate_source_ref,
)
from vault_paths import (  # noqa: E402
    VaultDirectoryInventory,
    atomic_create_vault_bytes,
    atomic_write_vault_text,
    read_vault_text,
    stat_signature,
    validate_contained_path,
)

# --------------------------------------------------------------------------
# Layout and vocabulary
# --------------------------------------------------------------------------

#: v354 (lifehug#409). The unit the fold elects a winning receipt WITHIN.
#: Receipts are grouped by ``(source_id, revision, extractor identity)`` — WHO
#: read the document as well as WHICH bytes they read
#: (`temporal_claims.AN_EXTRACTORS_NAME_IS_WHO_READ_IT`) — because a later
#: version of ONE reader is a later interpretation of the same words and
#: another reader is not. Grouping by ``(source_id, revision)`` alone made
#: `answer_placement`'s receipt on a promoted reply retire the
#: `general_listener` reading of that same reply wholesale, and the owner's
#: 2006 graduation lost its dated node to it.
A_READING_IS_ONLY_SUPERSEDED_BY_THE_SAME_READER = (
    "a receipt supersedes another only when the same reader re-read the same "
    "revision of the same document. Two extractors reading one message are two "
    "readings of it, both legitimate, and neither retires the other"
)

#: Promoted conversational sources (owner amendment 2 / option B). A message
#: that produced a claim is an evidence document like any other, so it lives
#: under ``sources/`` beside manual stories, imports and corrections rather
#: than in ``state/`` — state is rebuildable and evidence never is.
CONVERSATION_SOURCES_DIR = "sources/conversations"

#: The active index's own format version (the file's ``version`` field). It is
#: independent of :data:`temporal_claims.SCHEMA_VERSION`, which versions the
#: records inside it.
INDEX_VERSION = 1

#: v318. The sidecar that says what the PUBLISHED active index was folded from:
#: one signature per receipt and per correction source, plus each receipt's
#: ``extractor`` declaration (the one thing the telling manifest needs that
#: the index itself does not carry). It is an INPUT cache and never an output
#: one — nothing here is ever returned as a fold result; a signature that
#: still matches only buys the right to skip re-reading and re-validating one
#: file. A missing, stale, unparseable or self-inconsistent sidecar costs
#: exactly one full read, which is what v317 did every time.
#:
#: v322: the sidecar's signatures are CONTENT signatures (size and SHA-256 of
#: the bytes), so the file means the same thing on every machine and travels
#: with the vault — the contract declares it ``tracked: true``. A fresh clone
#: hashes every receipt once (reading, not parsing or validating) and reuses
#: everything whose bytes did not move. Inside one process the stat signature
#: still vouches first, so an unchanged file is not even re-hashed.
FOLD_CACHE_FILE = f"{TEMPORAL_STATE_DIR}/fold-cache.json"

#: Bumped when the sidecar's own shape changes. An older or newer number is not
#: migrated and not read — it is one full fold, and the next write replaces it.
#: 1 was v318's stat-signature sidecar; 2 carries content signatures.
FOLD_CACHE_VERSION = 2

#: The first element of every content signature. A stat signature is six
#: integers; a content signature is ``(CONTENT_SIGNATURE_KIND, size, hex)``.
CONTENT_SIGNATURE_KIND = "sha256"

#: Set to ``0`` to fold every receipt from disk on every call. The escape hatch
#: for a person who suspects the sidecar rather than the receipts; the
#: in-process equivalents are `fold_active_index(..., full=True)` and
#: `temporal_publication.verify`, which never consult it.
FOLD_CACHE_ENV = "LIFEHUG_TEMPORAL_FOLD_CACHE"

#: Frontmatter ``type`` values this module writes and reads back.
CONVERSATION_SOURCE_TYPE = "conversation_message"
TEMPORAL_CORRECTION_TYPE = "temporal_correction"

#: What a correction can say. Each maps onto exactly one claim status; there is
#: no fourth verb and no "delete".
CORRECTION_KINDS = ("supersede", "retract", "dispute")
STATUS_BY_CORRECTION_KIND = {
    "supersede": "superseded",
    "retract": "retracted",
    "dispute": "disputed",
}

#: Weakest to strongest. A claim carrying several marks takes the strongest —
#: a retraction outranks a supersession outranks a dispute — which is what makes
#: the fold independent of the order the marks were discovered in.
STATUS_PRECEDENCE = ("active", "disputed", "superseded", "retracted")

#: FROZEN. What makes two promotions the same utterance: the words, and where
#: they were said. Not the wall clock, not the channel, not the speaker label —
#: an annotation that drifted between two attempts would fork the source and
#: give one sentence two identities.
PROMOTION_IDENTITY_KEYS = ("message_text", "session_ref", "turn_ref")

#: FROZEN. What makes two corrections the same correction. ``created_at`` is
#: deliberately absent: re-filing the same correction is a no-op, not a second
#: record.
CORRECTION_IDENTITY_KEYS = ("kind", "claim_ids", "reason", "scope")

CORRECTION_ID_PREFIX = "temporal_correction"

#: Digest prefix length used in generated filenames. Long enough that a
#: collision is not a thing that happens; short enough to read.
FILENAME_DIGEST_LENGTH = 24

_HEX_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")

#: Frontmatter key order for the sources this module writes. Keys outside it are
#: emitted sorted, exactly as ``source_integrity.format_frontmatter`` does — the
#: algorithm is shared (and pinned by a parity test); only the key list is local.
FRONTMATTER_ORDER = (
    "title",
    "type",
    "source_id",
    "source_medium",
    "session_ref",
    "turn_ref",
    "speaker",
    "correction_id",
    "correction_kind",
    "claim_ids",
    "correction_scope",
    "relation",
    "subject_node_id",
    "anchor_node_ids",
    "supersedes_constraint_id",
    "evidence",
    "promotion_digest",
    "captured_at",
    "visibility",
    "status",
    "immutable",
    "schema_version",
    "source_path",
    "content_sha256",
)


class TemporalStoreError(TemporalContractError):
    """A durable temporal record could not be filed or read, with a named code."""


#: Every code this module raises, so a host can count rejections by reason and
#: retry exactly one class (plan §12).
STORE_ERROR_CODES = (
    "vault_root_missing",
    "unsafe_store_path",
    "receipt_immutable_conflict",
    "receipt_source_missing",
    "source_content_drifted",
    "source_frontmatter_missing",
    "message_text_required",
    "correction_kind_unknown",
    "correction_claim_ids_required",
    "correction_reason_required",
    "correction_target_unsafe",
    "constraint_relation_unknown",
    "constraint_subject_required",
    "constraint_target_unsafe",
    "active_index_unreadable",
)


# --------------------------------------------------------------------------
# Paths — one derivation, no module invents its own directory
# --------------------------------------------------------------------------


def _vault_root(vault_root: str | Path) -> Path:
    root = Path(vault_root).expanduser()
    if not root.is_absolute():
        root = Path.cwd() / root
    if not root.is_dir():
        raise TemporalStoreError(
            "vault_root_missing", f"vault root is not a directory: {root}"
        )
    return root


def store_path(vault_root: str | Path, relative: str) -> Path:
    """Absolute path for a store-relative POSIX path, symlink-escapes refused."""
    root = _vault_root(vault_root)
    try:
        return validate_contained_path(root / relative, root, label="temporal store path")
    except ValueError as exc:
        raise TemporalStoreError("unsafe_store_path", str(exc)) from exc


def receipt_path(
    vault_root: str | Path, source_ref: object, extractor_version: object
) -> Path:
    """Absolute path of the receipt for one (source revision, extractor)."""
    return store_path(vault_root, receipt_relative_path(source_ref, extractor_version))


def active_index_path(vault_root: str | Path) -> Path:
    return store_path(vault_root, ACTIVE_INDEX_FILE)


def conversation_source_relative_path(promotion_digest: str) -> str:
    """``sources/conversations/msg-<24 hex>.md``.

    The filename is a pure function of the utterance's identity, which is what
    lets a re-promotion find the existing file without consulting an index that
    could itself be stale.
    """
    digest = collapsed_text(promotion_digest).lower()
    if not _HEX_DIGEST_RE.fullmatch(digest):
        raise TemporalStoreError(
            "unsafe_store_path", f"not a sha256 promotion digest: {promotion_digest!r}"
        )
    return f"{CONVERSATION_SOURCES_DIR}/msg-{digest[:FILENAME_DIGEST_LENGTH]}.md"


def correction_relative_path(correction_id: str) -> str:
    """``sources/corrections/temporal-<24 hex>.md`` — deterministic, so re-filing
    the same correction lands on the same file and writes nothing new."""
    text = collapsed_text(correction_id)
    _prefix, _, digest = text.partition(":")
    if not re.fullmatch(r"[0-9a-f]{24}", digest):
        raise TemporalStoreError(
            "unsafe_store_path", f"not a correction id: {correction_id!r}"
        )
    return f"{CORRECTION_SOURCES_DIR}/temporal-{digest}.md"


# --------------------------------------------------------------------------
# Frontmatter — the same shape every other vault source uses
# --------------------------------------------------------------------------


def format_frontmatter(metadata: dict, *, order: Sequence[str] = FRONTMATTER_ORDER) -> str:
    """Known keys in ``order``, then the rest sorted — one YAML-ish block.

    Byte-identical to ``source_integrity.format_frontmatter`` for the same
    metadata and key order (pinned by a parity test). It is reimplemented rather
    than imported because ``source_integrity`` reaches ``lifehug_core``, whose
    import *binds the interpreter to one vault root* — and this module's whole
    API is "tell me which vault", so it must stay importable without one.
    """
    keys = [key for key in order if key in metadata]
    keys.extend(sorted(key for key in metadata if key not in keys))
    lines = ["---"]
    for key in keys:
        lines.append(f"{key}: {json.dumps(metadata[key], ensure_ascii=True)}")
    lines.append("---")
    return "\n".join(lines)


def split_frontmatter(content: str) -> tuple[dict, str]:
    """Frontmatter mapping and body — the ``lifehug_core`` reader, unbound."""
    if not content.startswith("---\n"):
        return {}, content
    lines = content.splitlines()
    end_index = None
    for idx, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            end_index = idx
            break
    if end_index is None:
        return {}, content
    metadata: dict = {}
    for raw in lines[1:end_index]:
        line = raw.strip()
        if not line or line.startswith("#") or ":" not in line:
            continue
        key, _, value = line.partition(":")
        key = key.strip()
        value = value.strip()
        if not key:
            continue
        if not value:
            metadata[key] = ""
            continue
        try:
            metadata[key] = json.loads(value)
        except json.JSONDecodeError:
            metadata[key] = value.strip('"').strip("'")
    body = "\n".join(lines[end_index + 1:])
    if body.startswith("\n"):
        body = body[1:]
    if content.endswith("\n"):
        body += "\n"
    return metadata, body


def normalize_payload(text: str) -> str:
    """``source_integrity``'s payload normalization: one newline convention."""
    cleaned = text.replace("\r\n", "\n").replace("\r", "\n").strip()
    return f"{cleaned}\n" if cleaned else ""


def payload_sha256(text: str) -> str:
    return hashlib.sha256(normalize_payload(text).encode("utf-8")).hexdigest()


def _canonical_json(payload: object) -> str:
    return json.dumps(payload, sort_keys=True, indent=2, ensure_ascii=False) + "\n"


def read_store_text(vault_root: str | Path, relative: str) -> str | None:
    """The text of one store-relative file, or ``None`` when it is not there.

    Public since E3: `era_identity` files records in exactly this module's
    shape and must read them back the same way. A second reader would be a
    second answer to "did the bytes drift", which is the one question this
    substrate is not allowed to have two of.
    """
    root = _vault_root(vault_root)
    path = store_path(root, relative)
    if not path.is_file():
        return None
    try:
        return read_vault_text(path, vault_root=root)
    except (OSError, ValueError):
        return None


def create_or_keep(vault_root: str | Path, relative: str, content: str) -> tuple[Path, bool]:
    """Publish a new immutable file; report whether this call created it.

    Public since E3 for the same reason :func:`read_store_text` is: the era
    records are content-addressed immutable sources in this module's shape,
    and "replay writes nothing" has to be ONE implementation or it is a
    property nobody actually holds.
    """
    root = _vault_root(vault_root)
    path = store_path(root, relative)
    try:
        atomic_create_vault_bytes(path, content.encode("utf-8"), vault_root=root)
    except FileExistsError:
        return path, False
    except ValueError as exc:
        raise TemporalStoreError("unsafe_store_path", str(exc)) from exc
    return path, True


#: The private spellings these two carried before E3 made them public. Kept as
#: aliases rather than renamed at every call site: a rename touches thirty
#: lines to say nothing, and a caller written against either name is right.
_read_text = read_store_text
_create_or_keep = create_or_keep


# --------------------------------------------------------------------------
# Option B — the promoted conversational source
# --------------------------------------------------------------------------


#: Event identity I2b. The additive frontmatter key a promoted source carries
#: when the session that produced it was ASKING ABOUT a container (§12b ruling
#: 5). ONE HOME: `episode_binder.read_question_contexts` reads this name and
#: nothing re-spells it.
QUESTION_CONTEXT_KEY = "question_context"


def promotion_digest(message_text: object, metadata: object = None) -> str:
    """The sha256 that identifies one utterance (:data:`PROMOTION_IDENTITY_KEYS`).

    Same words in the same turn of the same session = same digest = same source
    file. The same words said again in a different turn are a different
    utterance and get their own source, which is the honest answer: two people
    can say "we married in 1978" twice and both sentences are evidence.
    """
    meta = metadata if isinstance(metadata, dict) else {}
    payload = {
        "message_text": normalize_payload(str(message_text or "")),
        "session_ref": collapsed_text(meta.get("session_ref")) or None,
        "turn_ref": collapsed_text(meta.get("turn_ref")) or None,
    }
    blob = json.dumps(
        {key: payload[key] for key in PROMOTION_IDENTITY_KEYS},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _promotion_title(message_text: str, metadata: dict) -> str:
    supplied = collapsed_text(metadata.get("title"))
    if supplied:
        return supplied
    words = collapsed_text(message_text)
    if len(words) <= 72:
        return words or "Conversation message"
    return f"{words[:71].rstrip()}…"


def _source_ref_from_metadata(metadata: dict, relative: str) -> SourceRef:
    source_id = collapsed_text(metadata.get("source_id"))
    digest = collapsed_text(metadata.get("content_sha256")).lower()
    if not source_id or not _HEX_DIGEST_RE.fullmatch(digest):
        raise TemporalStoreError(
            "source_frontmatter_missing",
            f"{relative} does not declare a source_id and content_sha256",
        )
    normalized = validate_source_ref(
        {"source_id": source_id, "revision": f"sha256:{digest}", "source_path": relative}
    )
    return SourceRef(
        source_id=normalized["source_id"],
        revision=normalized["revision"],
        source_path=normalized.get("source_path"),
    )


def read_source_ref(vault_root: str | Path, relative: str) -> SourceRef | None:
    """The :class:`SourceRef` a filed vault source names, verified against its bytes.

    The revision is the source's own ``content_sha256``, so a claim citing it is
    pinned to the exact words that were read. If the file's payload no longer
    digests to the declared value the source has been edited under the claims
    that cite it, which is a named failure and never a shrug.
    """
    content = _read_text(vault_root, relative)
    if content is None:
        return None
    metadata, body = split_frontmatter(content)
    if not metadata:
        raise TemporalStoreError(
            "source_frontmatter_missing", f"{relative} carries no frontmatter"
        )
    source_ref = _source_ref_from_metadata(metadata, relative)
    actual = payload_sha256(body)
    if actual != source_ref.revision.split(":", 1)[1]:
        raise TemporalStoreError(
            "source_content_drifted",
            f"{relative} no longer matches the revision its frontmatter declares",
            detail={"declared": source_ref.revision, "actual": f"sha256:{actual}"},
        )
    return source_ref


def promote_conversational_source(
    vault_root: str | Path,
    message_text: str,
    metadata: object = None,
    *,
    source_type: str | None = None,
) -> SourceRef:
    """File a claim-bearing message as a durable vault source and return its ref.

    Owner amendment 2 / option B: no claim's only citation may be a session row,
    so the message becomes an ordinary source document *before* anything cites
    it. One message with N facts is promoted **once** — every receipt and every
    claim over it cites the same :class:`SourceRef`.

    Idempotent on the utterance's identity digest: promoting the same message
    twice returns the same ref and writes no second file. The existing file is
    re-read rather than trusted from memory, so a partially-written vault is
    detected here (:data:`source_content_drifted`) instead of downstream.

    ``metadata`` is optional and understood keys are ``session_ref``,
    ``turn_ref``, ``speaker``, ``channel``/``source_medium``, ``occurred_at``,
    ``title``, ``visibility`` and — event identity **I2b** —
    ``question_context``. Only the first two participate in identity.

    ``source_type`` overrides the frontmatter ``type`` this source carries,
    defaulting to :data:`CONVERSATION_SOURCE_TYPE` (unchanged behavior for
    every existing caller). E-L3 (timeline-eras design §10.3) uses it to file
    a Go Dig unit's free-text note as ``type: go_dig_note`` while reusing this
    function's storage path, digest and ``question_context`` mechanics
    whole — the note is still an ordinary promoted conversational source in
    every way that matters to the fold, just labeled for what produced it.

    **``question_context`` is the recorder's stamp** (event-identity amendment
    v4.2 §12b ruling 5): the CONTAINER the session's question targeted — the
    work-item or era Play target the host already holds when it opens the
    conversation. *"A lot of the Etherfuse questions and answers are Etherfuse
    questions, so we should place those in Etherfuse by default."* That makes
    it a FACT about what was asked, not an inference from what was said, which
    is why `episode_binder` files it as a deterministic `part_of` rather than
    as a proposal. It rides the SOURCE and not the claim because §9 froze
    `TemporalClaim`'s fields; it is additive, absent by default, and never
    part of :data:`PROMOTION_IDENTITY_KEYS` — the same words said to two
    different questions are still one utterance.
    """
    meta = dict(metadata) if isinstance(metadata, dict) else {}
    text = normalize_payload(str(message_text or ""))
    if not text.strip():
        raise TemporalStoreError(
            "message_text_required", "a promoted source needs the words that were said"
        )

    digest = promotion_digest(message_text, meta)
    relative = conversation_source_relative_path(digest)
    title = _promotion_title(text, meta)
    payload = f"# {title}\n\n{text.strip()}\n"

    frontmatter: dict = {
        "title": title,
        "type": collapsed_text(source_type) or CONVERSATION_SOURCE_TYPE,
        "source_id": f"conversation:msg-{digest[:FILENAME_DIGEST_LENGTH]}",
        "source_medium": collapsed_text(meta.get("channel") or meta.get("source_medium"))
        or "conversation",
        "promotion_digest": f"sha256:{digest}",
        "captured_at": normalized_timestamp(
            meta.get("occurred_at"), error=TemporalStoreError
        ),
        "visibility": collapsed_text(meta.get("visibility")) or "owner_only",
        "status": "raw",
        "immutable": True,
        "schema_version": SCHEMA_VERSION,
        "source_path": relative,
        "content_sha256": payload_sha256(payload),
    }
    for key in ("session_ref", "turn_ref", "speaker", QUESTION_CONTEXT_KEY):
        value = collapsed_text(meta.get(key))
        if value:
            frontmatter[key] = value

    _create_or_keep(
        vault_root, relative, f"{format_frontmatter(frontmatter)}\n\n{payload}"
    )
    source_ref = read_source_ref(vault_root, relative)
    if source_ref is None:  # pragma: no cover - the create above guarantees it
        raise TemporalStoreError(
            "source_frontmatter_missing", f"{relative} vanished during promotion"
        )
    return source_ref


# --------------------------------------------------------------------------
# The receipt store
# --------------------------------------------------------------------------


def write_receipt(
    vault_root: str | Path,
    receipt: object,
    *,
    now: object = None,
) -> Path:
    """Publish one immutable extraction receipt; return its path.

    Re-running the *same* extractor over the *same* source revision is a no-op:
    the path is already occupied and nothing is written. Re-running a
    *different* extractor writes a new receipt beside the old one, because a
    later model reading the same prose is a new interpretation and not a cache
    rebuild (plan §1.3). Whether the fold then treats that new receipt as
    SUPERSEDING the old one is a separate question and it is answered by
    :data:`A_READING_IS_ONLY_SUPERSEDED_BY_THE_SAME_READER`: a later version of
    one reader supersedes; a different reader stands beside. An attempt to change what an existing receipt ASSERTS
    is refused by name — that is the only thing this store treats as corruption
    rather than as history, and :data:`RECEIPT_ANNOTATION_KEYS` says exactly
    what "asserts" excludes.

    The source must be present when the receipt declares a ``source_path``, so
    a crash between promotion and filing can never leave a receipt citing a
    source that is not in the vault.
    """
    root = _vault_root(vault_root)
    normalized = validate_extraction_receipt(receipt, now=now)
    source_path = normalized["source_ref"].get("source_path")
    if source_path and not store_path(root, source_path).is_file():
        raise TemporalStoreError(
            "receipt_source_missing",
            f"receipt cites {source_path}, which is not in the vault",
            detail=normalized["source_ref"],
        )

    relative = receipt_relative_path(
        normalized["source_ref"], normalized["extractor_version"]
    )
    content = _canonical_json(normalized)
    path, created = _create_or_keep(root, relative, content)
    if created:
        return path
    existing = _read_text(root, relative)
    if existing is not None:
        try:
            stored = json.loads(existing)
        except json.JSONDecodeError:
            stored = None
        if isinstance(stored, dict) and _assertion_view(stored) == _assertion_view(normalized):
            # The same interpretation, filed again. The bytes already on disk
            # win — including their original timestamps and their original
            # declaration — because a retry is later, not different, and a
            # declaration is made at filing time and cannot be back-dated.
            return path
    raise TemporalStoreError(
        "receipt_immutable_conflict",
        f"{relative} already holds a different interpretation; "
        "re-extraction writes a new receipt, it never rewrites one",
        detail={"receipt_id": normalized["receipt_id"]},
    )


#: What a receipt ANNOTATES rather than asserts, so re-filing one is a no-op
#: instead of corruption. Two keys, each for a stated reason.
#:
#: ``created_at`` — a re-run of the same extraction stamps a fresh clock on the
#: receipt and on each claim. That is annotation, exactly as it is for
#: :func:`temporal_claims.derive_claim_id`, and treating it as a difference
#: would turn "file this again" — the retry every idempotent caller depends on
#: — into a corruption error the moment the second attempt crossed a one-second
#: boundary.
#:
#: ``extractor`` — the extraction's own DECLARATION about itself, the block
#: `event_identity.declare_tellings` builds. What a receipt asserts is its
#: source revision, its extractor version and its claims; how richly the
#: extractor described its own run is provenance beside that assertion, and a
#: later framework version legitimately declares MORE about the identical
#: claims. Event identity I1 (v267) is the live instance: it wired
#: ``telling_keys`` and ``document_revision`` into the classifier's and the
#: recorder's blocks, and the founder vault's 839 classifier receipts — filed
#: at v263, byte-identical in every claim — became un-refilable at their own
#: identity, so re-running `migrate-classifier-moments` crashed
#: ``receipt_immutable_conflict`` on the first one. Naming the whole block,
#: rather than listing the three fields I1 happened to add, is what keeps a
#: fourth declaration field from reopening this by construction.
#:
#: Everything else must match, so a genuinely different READING at the same
#: identity is still refused: to assert something else you move the identity —
#: a new source revision, or a new rule version — which is what supersession is
#: for.
RECEIPT_ANNOTATION_KEYS = ("created_at", "extractor")


def _assertion_view(receipt: dict) -> dict:
    """What a receipt ASSERTS — itself minus :data:`RECEIPT_ANNOTATION_KEYS`."""
    view = {
        key: value
        for key, value in receipt.items()
        if key not in RECEIPT_ANNOTATION_KEYS
    }
    view["claims"] = [
        {key: value for key, value in claim.items() if key != "created_at"}
        for claim in (receipt.get("claims") or ())
        if isinstance(claim, dict)
    ]
    return view


def _signature_map(root: Path, relative_dir: str, pattern: str) -> dict[str, tuple]:
    """``{store-relative path: stat signature}`` for one directory's members.

    ONE enumeration, shared by the listers and by the fold's input cache
    (recurring-defect doctrine): a cache that decided "unchanged" from a
    different walk than the loader's would eventually disagree with it about
    which files exist, and the disagreement would read as a correct fold.
    Symlinks and non-regular files are skipped here exactly as every reader
    here has always skipped them, so the two can never diverge.
    """
    base = store_path(root, relative_dir)
    if not base.is_dir():
        return {}
    found: dict[str, tuple] = {}
    for path in base.rglob(pattern):
        try:
            info = path.lstat()
        except OSError:
            continue
        if not stat.S_ISREG(info.st_mode):
            continue
        found[path.relative_to(root).as_posix()] = stat_signature(info)
    return found


def receipt_relative_paths(vault_root: str | Path) -> list[str]:
    """Every checked-in receipt path, sorted, for unscoped receipt loading."""
    return sorted(_signature_map(_vault_root(vault_root), RECEIPTS_DIR, "*.json"))


@dataclass
class _ReceiptReadBatch:
    root: Path
    inventory: VaultDirectoryInventory
    receipts: dict[str, tuple[tuple, ExtractionReceipt]] = field(default_factory=dict)
    closed: bool = False


_RECEIPT_READ_BATCH: contextvars.ContextVar[_ReceiptReadBatch | None] = (
    contextvars.ContextVar("temporal_receipt_read_batch", default=None)
)


@contextlib.contextmanager
def receipt_read_batch(vault_root: str | Path):
    """Reuse validated immutable inputs only within one vault's bounded act.

    Folds refresh directory membership and file signatures and load corrections
    anew. Only unchanged directory names and validated receipts are reused;
    no derived index, missing file or parse failure is cached.
    """
    root = Path(os.path.abspath(_vault_root(vault_root)))
    parent = _RECEIPT_READ_BATCH.get()
    if parent is not None and parent.closed:
        parent = None
    if parent is not None and parent.root != root:
        raise TemporalStoreError("unsafe_store_path", "receipt batch cannot cross vaults")
    try:
        batch = parent or _ReceiptReadBatch(root, VaultDirectoryInventory(root, RECEIPTS_DIR))
    except (OSError, ValueError) as exc:
        raise TemporalStoreError("unsafe_store_path", str(exc)) from exc
    token = _RECEIPT_READ_BATCH.set(batch)
    try:
        yield
    finally:
        _RECEIPT_READ_BATCH.reset(token)
        if parent is None:
            batch.closed = True
            batch.receipts.clear()
            batch.inventory.clear()


def _receipt_file_signature(path: Path) -> tuple | None:
    try:
        info = path.stat(follow_symlinks=False)
    except OSError:
        return None
    return stat_signature(info)


def read_receipt(vault_root: str | Path, relative: str) -> ExtractionReceipt | None:
    """Tolerant read (compat rule 2): unknown keys ignored, unknown schema
    versions read for the fields this version knows, unreadable files ``None``."""
    batch = _RECEIPT_READ_BATCH.get()
    if batch is not None and batch.closed:
        batch = None
    signature = None
    if batch is not None:
        if Path(os.path.abspath(_vault_root(vault_root))) != batch.root:
            raise TemporalStoreError("unsafe_store_path", "receipt batch cannot cross vaults")
        try:
            batch.inventory.check_root()
        except (OSError, ValueError) as exc:
            raise TemporalStoreError("unsafe_store_path", str(exc)) from exc
        # Repeat containment/symlink checks even on a cache hit. The old reader
        # remains the only way a new or changed receipt enters this scope.
        path = store_path(vault_root, relative)
        signature = _receipt_file_signature(path)
        cached = batch.receipts.get(relative)
        if signature is not None and cached is not None and signature == cached[0]:
            return copy.deepcopy(cached[1])
        batch.receipts.pop(relative, None)
    content = _read_text(vault_root, relative)
    if content is None:
        return None
    try:
        payload = json.loads(content)
    except json.JSONDecodeError:
        return None
    receipt = receipt_from_dict(payload)
    if (batch is not None and signature is not None and receipt is not None
            and _receipt_file_signature(path) == signature):
        batch.receipts[relative] = (signature, copy.deepcopy(receipt))
    return receipt


def load_receipts(
    vault_root: str | Path,
) -> tuple[list[ExtractionReceipt], list[str]]:
    """``(receipts, unreadable_relative_paths)`` — both sorted, neither hidden."""
    receipts: list[ExtractionReceipt] = []
    unreadable: list[str] = []
    batch = _RECEIPT_READ_BATCH.get()
    if batch is not None and batch.closed:
        batch = None
    if batch is None:
        rows = [(relative, read_receipt(vault_root, relative))
                for relative in receipt_relative_paths(vault_root)]
    else:
        if Path(os.path.abspath(_vault_root(vault_root))) != batch.root:
            raise TemporalStoreError("unsafe_store_path", "receipt batch cannot cross vaults")
        rows = []
        observed: set[str] = set()

        def read_validated(relative: str, signature: tuple) -> None:
            observed.add(relative)
            cached = batch.receipts.get(relative)
            if cached is not None and cached[0] == signature:
                receipt = copy.deepcopy(cached[1])
            else:
                # The ordinary reader remains the only parser and revalidates
                # changed/new files. Metadata never licenses a new input.
                batch.receipts.pop(relative, None)
                receipt = read_receipt(vault_root, relative)
            rows.append((relative, receipt))

        try:
            batch.inventory.visit_files(read_validated)
        except (OSError, ValueError) as exc:
            batch.inventory.clear()
            batch.receipts.clear()
            raise TemporalStoreError("unsafe_store_path", str(exc)) from exc
        batch.receipts = {key: value for key, value in batch.receipts.items() if key in observed}
        rows.sort(key=lambda row: row[0])
    for relative, receipt in rows:
        if receipt is None:
            unreadable.append(relative)
        else:
            receipts.append(receipt)
    receipts.sort(key=receipt_sort_key)
    return receipts, unreadable


def receipt_sort_key(receipt: ExtractionReceipt) -> tuple[str, str, str]:
    """Total order over receipts for one source revision.

    ``created_at`` leads because extractor version *strings* have no meaningful
    order — ``prompt:a1b2`` is not "before" ``prompt:9f0e`` — and the plan's
    "latest interpretation wins" is a statement about time, not about lexical
    sorting. The remaining components only break ties, and they break them the
    same way on every machine.
    """
    return (receipt.created_at, receipt.extractor_version, receipt.receipt_id)


# --------------------------------------------------------------------------
# Corrections — supersession and retraction, as durable sources
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class TemporalCorrection:
    """A human or system statement that a filed claim no longer stands.

    It is a **source**, not state: written once, never edited, kept forever, and
    read by the fold every time. A correction says only which claims stop
    standing and why. Saying what is true *instead* is a separate act — promote
    the correction's own text as the source and file a receipt over it — which
    keeps the replacement claim's provenance as traceable as the claim it
    replaces, and keeps this record free of a circular self-citation.
    """

    correction_id: str
    kind: str
    claim_ids: tuple[str, ...]
    reason: str
    source_ref: SourceRef
    created_at: str
    scope: str | None = None
    relative_path: str = ""
    schema_version: int = SCHEMA_VERSION

    def to_dict(self) -> dict:
        payload: dict = {
            "correction_id": self.correction_id,
            "schema_version": self.schema_version,
            "kind": self.kind,
            "claim_ids": list(self.claim_ids),
            "reason": self.reason,
            "source_ref": self.source_ref.to_dict(),
            "created_at": self.created_at,
            "relative_path": self.relative_path,
        }
        if self.scope:
            payload["scope"] = self.scope
        return payload


def derive_correction_id(
    *, kind: object, claim_ids: object, reason: object, scope: object = None
) -> str:
    """``temporal_correction:<24 hex>`` over :data:`CORRECTION_IDENTITY_KEYS`.

    The same correction filed twice — a retried request, a double tap, a replayed
    job — is one record, because identity is what the correction *says* and not
    when it was said.
    """
    payload = {
        "kind": collapsed_text(kind).lower(),
        "claim_ids": _claim_id_list(claim_ids),
        "reason": collapsed_text(reason),
        "scope": collapsed_text(scope) or None,
    }
    return digest_id(
        CORRECTION_ID_PREFIX, {key: payload[key] for key in CORRECTION_IDENTITY_KEYS}
    )


def _claim_id_list(value: object) -> list[str]:
    if isinstance(value, (str, bytes)):
        value = [value]
    cleaned = {collapsed_text(item) for item in (value or ())}
    return sorted(item for item in cleaned if item)


def file_temporal_correction(
    vault_root: str | Path,
    *,
    kind: str,
    claim_ids: Iterable[str],
    reason: str,
    scope: str | None = None,
    title: str | None = None,
    author: str | None = None,
    occurred_at: object = None,
) -> TemporalCorrection:
    """File a supersession, retraction or dispute; idempotent on its content.

    The correction lands as a markdown source under
    :data:`temporal_claims.CORRECTION_SOURCES_DIR` with its machine-readable
    fields in the frontmatter and the human reason as the body — the same shape
    every other correction in the vault already has, so the source scanner,
    the manifest and a person reading the directory all see one kind of thing.
    """
    verb = collapsed_text(kind).lower()
    if verb not in CORRECTION_KINDS:
        raise TemporalStoreError(
            "correction_kind_unknown",
            f"a correction supersedes, retracts or disputes; got {kind!r}",
        )
    targets = _claim_id_list(claim_ids)
    if not targets:
        raise TemporalStoreError(
            "correction_claim_ids_required",
            "a correction names the claims it acts on",
        )
    for target in targets:
        if "/" in target or "\n" in target:
            raise TemporalStoreError(
                "correction_target_unsafe", f"not a claim id: {target!r}"
            )
    prose = collapsed_text(reason)
    if not prose:
        raise TemporalStoreError(
            "correction_reason_required",
            "a correction records why, or the fold cannot explain itself later",
        )

    correction_id = derive_correction_id(
        kind=verb, claim_ids=targets, reason=prose, scope=scope
    )
    relative = correction_relative_path(correction_id)
    heading = collapsed_text(title) or f"{verb.title()} {len(targets)} temporal claim(s)"
    payload = f"# {heading}\n\n{prose}\n"

    frontmatter: dict = {
        "title": heading,
        "type": TEMPORAL_CORRECTION_TYPE,
        "source_id": f"correction:temporal-{correction_id.split(':', 1)[1]}",
        "source_medium": collapsed_text(author) or "owner",
        "correction_id": correction_id,
        "correction_kind": verb,
        "claim_ids": targets,
        "captured_at": normalized_timestamp(occurred_at, error=TemporalStoreError),
        "visibility": "owner_only",
        "status": "raw",
        "immutable": True,
        "schema_version": SCHEMA_VERSION,
        "source_path": relative,
        "content_sha256": payload_sha256(payload),
    }
    if collapsed_text(scope):
        frontmatter["correction_scope"] = collapsed_text(scope)

    _create_or_keep(
        vault_root, relative, f"{format_frontmatter(frontmatter)}\n\n{payload}"
    )
    correction = read_temporal_correction(vault_root, relative)
    if correction is None:  # pragma: no cover - the create above guarantees it
        raise TemporalStoreError(
            "source_frontmatter_missing", f"{relative} vanished during filing"
        )
    return correction


def supersede_claims(
    vault_root: str | Path,
    claim_ids: Iterable[str],
    *,
    reason: str,
    scope: str | None = None,
    title: str | None = None,
    author: str | None = None,
    occurred_at: object = None,
) -> TemporalCorrection:
    """"These claims are no longer the operative reading."

    Saying what *is* true instead is a separate, traceable act: promote the
    correcting words as a source and file a receipt over them.
    """
    return file_temporal_correction(
        vault_root,
        kind="supersede",
        claim_ids=claim_ids,
        reason=reason,
        scope=scope,
        title=title,
        author=author,
        occurred_at=occurred_at,
    )


def retract_claims(
    vault_root: str | Path,
    claim_ids: Iterable[str],
    *,
    reason: str,
    scope: str | None = None,
    title: str | None = None,
    author: str | None = None,
    occurred_at: object = None,
) -> TemporalCorrection:
    """"These claims should never have been asserted." Kept on disk regardless."""
    return file_temporal_correction(
        vault_root,
        kind="retract",
        claim_ids=claim_ids,
        reason=reason,
        scope=scope,
        title=title,
        author=author,
        occurred_at=occurred_at,
    )


def dispute_claims(
    vault_root: str | Path,
    claim_ids: Iterable[str],
    *,
    reason: str,
    scope: str | None = None,
    title: str | None = None,
    author: str | None = None,
    occurred_at: object = None,
) -> TemporalCorrection:
    """"Something here contradicts something else." Visible, unresolved, honest."""
    return file_temporal_correction(
        vault_root,
        kind="dispute",
        claim_ids=claim_ids,
        reason=reason,
        scope=scope,
        title=title,
        author=author,
        occurred_at=occurred_at,
    )


def read_temporal_correction(
    vault_root: str | Path, relative: str
) -> TemporalCorrection | None:
    """Read one correction source; ``None`` when the file is not one of ours."""
    content = _read_text(vault_root, relative)
    if content is None:
        return None
    metadata, body = split_frontmatter(content)
    if collapsed_text(metadata.get("type")) != TEMPORAL_CORRECTION_TYPE:
        return None
    verb = collapsed_text(metadata.get("correction_kind")).lower()
    if verb not in CORRECTION_KINDS:
        return None
    targets = _claim_id_list(metadata.get("claim_ids"))
    if not targets:
        return None
    source_ref = _source_ref_from_metadata(metadata, relative)
    actual = payload_sha256(body)
    if actual != source_ref.revision.split(":", 1)[1]:
        raise TemporalStoreError(
            "source_content_drifted",
            f"{relative} no longer matches the revision its frontmatter declares",
            detail={"declared": source_ref.revision, "actual": f"sha256:{actual}"},
        )
    correction_id = collapsed_text(metadata.get("correction_id")) or derive_correction_id(
        kind=verb,
        claim_ids=targets,
        reason=_correction_reason(body),
        scope=metadata.get("correction_scope"),
    )
    return TemporalCorrection(
        correction_id=correction_id,
        kind=verb,
        claim_ids=tuple(targets),
        reason=_correction_reason(body),
        source_ref=source_ref,
        created_at=normalized_timestamp(
            metadata.get("captured_at"), error=TemporalStoreError
        ),
        scope=collapsed_text(metadata.get("correction_scope")) or None,
        relative_path=relative,
    )


def _correction_reason(body: str) -> str:
    lines = [line for line in body.splitlines() if not line.startswith("# ")]
    return collapsed_text(" ".join(lines))


def _correction_from_row(row: dict) -> TemporalCorrection:
    """The inverse of :meth:`TemporalCorrection.to_dict`, exactly.

    A correction round-trips through its own serialization: the fold already
    publishes every one of them into the active index in this shape, so
    reading one back is reading a record this store wrote, not re-deriving it.
    """
    ref = row.get("source_ref") if isinstance(row.get("source_ref"), dict) else {}
    return TemporalCorrection(
        correction_id=collapsed_text(row.get("correction_id")),
        kind=collapsed_text(row.get("kind")),
        claim_ids=tuple(collapsed_text(value) for value in (row.get("claim_ids") or ())),
        reason=str(row.get("reason") or ""),
        source_ref=SourceRef(
            source_id=collapsed_text(ref.get("source_id")),
            revision=collapsed_text(ref.get("revision")),
            source_path=ref.get("source_path"),
        ),
        created_at=collapsed_text(row.get("created_at")),
        scope=collapsed_text(row.get("scope")) or None,
        relative_path=collapsed_text(row.get("relative_path")),
        schema_version=int(row.get("schema_version") or SCHEMA_VERSION),
    )


def load_temporal_corrections(
    vault_root: str | Path, *, full: bool = False
) -> list[TemporalCorrection]:
    """Every temporal correction in the vault, sorted by id.

    v318: the directory is walked every time and only a file whose signature
    moved is re-read. This function is called three times in one filing cycle
    — the fold, the ordering-constraint fold, and the derivation's constraint
    read — over a directory that on a large vault holds thousands of sources.
    """
    root = _vault_root(vault_root)
    signatures = _signature_map(root, CORRECTION_SOURCES_DIR, "*.md")
    rows = _correction_rows(root, signatures, _prior_inputs(root, full=full))
    corrections = [
        _correction_from_row(row) for row in rows.values() if isinstance(row, dict)
    ]
    corrections.sort(key=lambda item: (item.correction_id, item.relative_path))
    return corrections


# --------------------------------------------------------------------------
# Ordering constraints — what a drag writes, and where it lives
# --------------------------------------------------------------------------

#: Frontmatter ``type`` for the source a move files. It sits under
#: :data:`temporal_claims.CORRECTION_SOURCES_DIR` beside the supersede/retract
#: records because a move IS a correction — the person is telling the system its
#: reading of the order was wrong — and a reader opening that directory should
#: find one kind of thing: statements that the current interpretation is not it.
ORDERING_CONSTRAINT_TYPE = "ordering_constraint"

#: The ``correction_scope`` a retraction carries when its target is a constraint
#: rather than a claim. The fold over claims ignores such a row by construction
#: (a ``constraint:`` id matches no claim), and :func:`load_ordering_constraints`
#: reads exactly these — one correction machine, two kinds of target.
CONSTRAINT_CORRECTION_SCOPE = "ordering_constraint"

#: v349. The ``correction_scope`` a retraction carries when its target is
#: another CORRECTION rather than a claim — one correction machine, now three
#: kinds of target. A ``retract`` under this scope is a REINSTATEMENT: the
#: marks the named corrections laid stop standing, and every claim they
#: superseded is active again on the next fold.
#:
#: It exists because a defect retired thirty landmark entries the owner had
#: stated (see `landmarks_interaction.A_STATED_ENTRY_IS_NEVER_RETIRED_BY_SHAPE`)
#: and the vault had no verb for *"that correction was not a correction"*.
#: Undo is a STATEMENT here exactly as it is for a move: the 29 supersessions
#: stay on disk with their reasons, and a reinstatement explains that they no
#: longer stand. Nothing is edited and nothing is deleted.
#:
#: The fold stays order-independent because reinstatement is resolved as a SET
#: before any mark is laid (:func:`_fold`) — not as a later writer beating an
#: earlier one. A reinstatement of a reinstatement is deliberately not a thing:
#: re-deciding that those claims should go needs a NEW supersession, whose own
#: reason says why, which is the same rule
#: :data:`CONSTRAINT_CORRECTION_SCOPE` holds a move to.
CORRECTION_CORRECTION_SCOPE = "temporal_correction"

#: FROZEN. What makes two moves the same move: the gesture's *meaning*, plus the
#: record it replaces. Deliberately absent are the wall clock, the explanation,
#: the device, and any idempotency token a host invented — a retried drag, a
#: double tap and an optimistic client that resends all say the identical thing
#: and must land on one file. ``supersedes_constraint_id`` is in the set because
#: "move it back after undoing" is a genuinely NEW statement about the order,
#: and an amendment that adds evidence is a new record that names the one it
#: replaces rather than an edit of an immutable source.
MOVE_IDENTITY_KEYS = (
    "relation",
    "subject_node_id",
    "anchor_node_ids",
    "supersedes_constraint_id",
)

#: Cap on the explanation a move carries in its body. The person's words are
#: evidence, not an essay, and an unbounded field in an immutable source is a
#: file nobody can review.
MOVE_REASON_MAX_CHARS = 2000


def move_digest(
    *,
    relation: object,
    subject_node_id: object,
    anchor_node_ids: object,
    supersedes_constraint_id: object = None,
) -> str:
    """The sha256 that identifies one move (:data:`MOVE_IDENTITY_KEYS`).

    A pure function of what the gesture *asserts*, which is what lets a re-filed
    drag find its existing source without consulting an index that could itself
    be stale — the same property :func:`promotion_digest` buys for an utterance.
    """
    anchors = anchor_node_ids
    if isinstance(anchors, (str, bytes)):
        anchors = [anchors]
    payload = {
        "relation": collapsed_text(relation).lower(),
        "subject_node_id": collapsed_text(subject_node_id),
        "anchor_node_ids": sorted(
            {collapsed_text(a) for a in (anchors or ()) if collapsed_text(a)}
        ),
        "supersedes_constraint_id": collapsed_text(supersedes_constraint_id) or None,
    }
    blob = json.dumps(
        {key: payload[key] for key in MOVE_IDENTITY_KEYS},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def constraint_relative_path(digest: str) -> str:
    """``sources/corrections/move-<24 hex>.md`` — deterministic, like every other
    immutable source this module writes."""
    text = collapsed_text(digest).lower()
    if not _HEX_DIGEST_RE.fullmatch(text):
        raise TemporalStoreError(
            "unsafe_store_path", f"not a sha256 move digest: {digest!r}"
        )
    return f"{CORRECTION_SOURCES_DIR}/move-{text[:FILENAME_DIGEST_LENGTH]}.md"


def _constraint_id_guard(value: object) -> str:
    target = collapsed_text(value)
    if not target.startswith(f"{CONSTRAINT_ID_PREFIX}:") or "/" in target or "\n" in target:
        raise TemporalStoreError(
            "constraint_target_unsafe", f"not a constraint id: {value!r}"
        )
    return target


def _move_sentence(relation: str, subject: str, anchors: Sequence[str]) -> str:
    """The move, said plainly, for the body of a source that has no explanation.

    It states the gesture and nothing else. Plan §2.6 is explicit that a drag
    must not persist "a pixel coordinate, array index, or fabricated exact
    date", and this sentence is held to the same rule: it names the relation and
    the nodes, so a person reading the correction directory in five years sees
    what was asserted, and no precision is invented on their behalf.
    """
    named = ", ".join(anchors)
    if relation == "within":
        return f"{subject} falls within {named}."
    if relation == "between":
        return f"{subject} falls between {named}."
    return f"{subject} comes {relation} {named}."


def file_ordering_constraint(
    vault_root: str | Path,
    *,
    relation: str,
    subject_node_id: str,
    anchor_node_ids: Iterable[str],
    reason: str | None = None,
    evidence: object = (),
    supersedes_constraint_id: str | None = None,
    subject_label: str | None = None,
    anchor_labels: Iterable[str] | None = None,
    title: str | None = None,
    author: str | None = None,
    occurred_at: object = None,
) -> dict:
    """File a move as a durable correction source; return the normalized constraint.

    This is the write half of the drag transaction (plan §2.6, §8.4 step 4). It
    files exactly one thing — the weakest truthful statement the gesture makes —
    and it is idempotent on that statement, so an optimistic client that resends
    and a job that replays converge on one record rather than stacking two.

    ``reason`` is OPTIONAL by contract: "the move remains saved if the person
    closes the conversation or provides no explanation". When it is absent the
    body states the move itself, so the source is still readable prose and still
    carries no invented precision.

    ``subject_label``/``anchor_labels`` are display names for the body's prose
    only — "College comes after High School" reads better in the corrections
    directory than a pair of node ids. They never touch identity: the digest is
    over the node ids, so the same move labelled two ways is still one file.

    An explanation that arrives *later* does not require a second gesture
    (§8.4 step 6): file again with the same relation and anchors, the new
    ``evidence``, and ``supersedes_constraint_id`` set to the record being
    amended. The old record keeps its bytes and gains ``superseded``; the new
    one carries the words. Undo is :func:`retract_ordering_constraint`, which
    marks without erasing for the same reason.
    """
    anchors = anchor_node_ids
    if isinstance(anchors, (str, bytes)):
        anchors = [anchors]
    anchor_list = sorted({collapsed_text(a) for a in (anchors or ()) if collapsed_text(a)})
    subject = collapsed_text(subject_node_id)
    verb = collapsed_text(relation).lower()
    if not subject:
        raise TemporalStoreError(
            "constraint_subject_required", "a move names the node it moves"
        )
    if verb not in CONSTRAINT_RELATIONS:
        raise TemporalStoreError(
            "constraint_relation_unknown",
            f"a move is {', '.join(CONSTRAINT_RELATIONS)}; got {relation!r}",
        )
    supersedes = (
        _constraint_id_guard(supersedes_constraint_id) if supersedes_constraint_id else None
    )

    digest = move_digest(
        relation=verb,
        subject_node_id=subject,
        anchor_node_ids=anchor_list,
        supersedes_constraint_id=supersedes,
    )
    relative = constraint_relative_path(digest)
    labels = [collapsed_text(a) for a in (anchor_labels or ()) if collapsed_text(a)]
    sentence = _move_sentence(
        verb,
        collapsed_text(subject_label) or subject,
        labels if len(labels) == len(anchor_list) else anchor_list,
    )
    prose = collapsed_text(reason)[:MOVE_REASON_MAX_CHARS] or sentence
    heading = collapsed_text(title) or sentence
    payload = f"# {heading}\n\n{prose}\n"

    raw_evidence = evidence
    if isinstance(raw_evidence, (str, dict)) or hasattr(raw_evidence, "to_dict"):
        raw_evidence = [raw_evidence]
    spans = [validate_evidence_span(span) for span in (raw_evidence or ())]

    frontmatter: dict = {
        "title": heading,
        "type": ORDERING_CONSTRAINT_TYPE,
        "source_id": f"correction:move-{digest[:FILENAME_DIGEST_LENGTH]}",
        "source_medium": collapsed_text(author) or "owner",
        "relation": verb,
        "subject_node_id": subject,
        "anchor_node_ids": anchor_list,
        "evidence": spans,
        "captured_at": normalized_timestamp(occurred_at, error=TemporalStoreError),
        "visibility": "owner_only",
        "status": "raw",
        "immutable": True,
        "schema_version": SCHEMA_VERSION,
        "source_path": relative,
        "content_sha256": payload_sha256(payload),
    }
    if supersedes:
        frontmatter["supersedes_constraint_id"] = supersedes

    # Validate the record the file WOULD carry before a byte lands. An immutable
    # source that cannot be read back as a constraint is not a bad request, it
    # is litter — and `_create_or_keep` would keep it forever.
    validate_ordering_constraint(
        {
            "relation": verb,
            "subject_node_id": subject,
            "anchor_node_ids": anchor_list,
            "source_ref": {
                "source_id": frontmatter["source_id"],
                "revision": f"sha256:{frontmatter['content_sha256']}",
                "source_path": relative,
            },
            "evidence": spans,
            "created_at": frontmatter["captured_at"],
            **({"supersedes_constraint_id": supersedes} if supersedes else {}),
        }
    )

    _create_or_keep(
        vault_root, relative, f"{format_frontmatter(frontmatter)}\n\n{payload}"
    )
    constraint = read_ordering_constraint(vault_root, relative)
    if constraint is None:  # pragma: no cover - the create above guarantees it
        raise TemporalStoreError(
            "source_frontmatter_missing", f"{relative} vanished during filing"
        )
    return constraint


def read_ordering_constraint(vault_root: str | Path, relative: str) -> dict | None:
    """Read one move source back as a normalized constraint; ``None`` when the
    file is not one of ours.

    The ``source_ref`` is rebuilt from the file's own bytes, so the constraint id
    a reader derives is pinned to the words on disk — the same guarantee
    :func:`read_source_ref` gives a claim's citation, and the reason a drifted
    source is a named failure here rather than a silently different id.
    """
    content = _read_text(vault_root, relative)
    if content is None:
        return None
    metadata, body = split_frontmatter(content)
    if collapsed_text(metadata.get("type")) != ORDERING_CONSTRAINT_TYPE:
        return None
    source_ref = _source_ref_from_metadata(metadata, relative)
    actual = payload_sha256(body)
    if actual != source_ref.revision.split(":", 1)[1]:
        raise TemporalStoreError(
            "source_content_drifted",
            f"{relative} no longer matches the revision its frontmatter declares",
            detail={"declared": source_ref.revision, "actual": f"sha256:{actual}"},
        )
    row: dict = {
        "relation": metadata.get("relation"),
        "subject_node_id": metadata.get("subject_node_id"),
        "anchor_node_ids": metadata.get("anchor_node_ids"),
        "source_ref": source_ref.to_dict(),
        "evidence": metadata.get("evidence") or [],
        "created_at": metadata.get("captured_at"),
    }
    if metadata.get("supersedes_constraint_id"):
        row["supersedes_constraint_id"] = metadata.get("supersedes_constraint_id")
    try:
        normalized = validate_ordering_constraint(row)
    except TemporalContractError:
        return None
    normalized["relative_path"] = relative
    normalized["reason"] = _correction_reason(body)
    return normalized


def reinstate_corrections(
    vault_root: str | Path,
    correction_ids: Iterable[str],
    *,
    reason: str,
    title: str | None = None,
    author: str | None = None,
    occurred_at: object = None,
) -> TemporalCorrection:
    """"Those corrections were not corrections." One record, idempotent.

    v349. Files ONE ``retract`` scoped to
    :data:`CORRECTION_CORRECTION_SCOPE` naming every correction that stops
    standing, so the claims they superseded are active again on the next fold.
    The superseded corrections stay on disk with their own reasons — undo is a
    statement, never a delete, exactly as it is for a move.

    Deterministic and idempotent by construction: the targets are sorted by
    :func:`_claim_id_list` and the record's id is
    :func:`derive_correction_id` over what it SAYS, so re-filing the same
    reinstatement finds its own existing file rather than minting a sibling.
    """
    targets = _claim_id_list(correction_ids)
    if not targets:
        raise TemporalStoreError(
            "correction_claim_ids_required",
            "a reinstatement names the corrections it voids",
        )
    for target in targets:
        if not target.startswith(f"{CORRECTION_ID_PREFIX}:"):
            raise TemporalStoreError(
                "reinstate_target_not_a_correction",
                f"a reinstatement names a correction id, not {target!r}",
            )
    return file_temporal_correction(
        vault_root,
        kind="retract",
        claim_ids=targets,
        reason=reason,
        scope=CORRECTION_CORRECTION_SCOPE,
        title=title or f"Reinstate {len(targets)} correction(s)",
        author=author,
        occurred_at=occurred_at,
    )


def reinstated_correction_ids(vault_root: str | Path) -> tuple[str, ...]:
    """Every correction id a reinstatement has voided, sorted. v349.

    What a repair verb reads to know what it has already done, so a second run
    proposes nothing rather than re-filing.
    """
    found: set[str] = set()
    for correction in load_temporal_corrections(vault_root):
        if correction.scope == CORRECTION_CORRECTION_SCOPE and correction.kind == "retract":
            found.update(correction.claim_ids)
    return tuple(sorted(found))


def retract_ordering_constraint(
    vault_root: str | Path,
    constraint_id: str,
    *,
    reason: str,
    title: str | None = None,
    author: str | None = None,
    occurred_at: object = None,
) -> TemporalCorrection:
    """Undo a move — mark it retracted, keep every byte of it (plan §2.6).

    Undo is a *statement*, not a delete: the move's source stays on disk with
    its evidence, and this record explains that it no longer stands. It rides
    the correction machine that already exists, scoped to
    :data:`CONSTRAINT_CORRECTION_SCOPE` so the claim fold — which would find no
    claim by this id anyway — is not asked to guess what kind of thing was
    retracted.
    """
    target = _constraint_id_guard(constraint_id)
    return file_temporal_correction(
        vault_root,
        kind="retract",
        claim_ids=[target],
        reason=reason,
        scope=CONSTRAINT_CORRECTION_SCOPE,
        title=title or f"Undo move {target}",
        author=author,
        occurred_at=occurred_at,
    )


def load_ordering_constraints(vault_root: str | Path) -> list[dict]:
    """Every filed move, with its status resolved. Pure, and order-independent.

    Status comes from *marks over an unordered set* exactly as
    :func:`fold_active_index` resolves a claim's: a constraint named by an
    active constraint's ``supersedes_constraint_id`` is superseded, one named by
    a scoped retraction is retracted, and the strongest mark wins. Nothing here
    consults a clock or a file's mtime, so deleting the vault's caches and
    reading again yields the same list in the same order.

    The rows are what :func:`temporal_publication.publish` passes to the
    derivation — plan §8.4 step 7's republish, reading the home this function
    gives constraints.
    """
    root = _vault_root(vault_root)
    base = store_path(root, CORRECTION_SOURCES_DIR)
    if not base.is_dir():
        return []

    rows: dict[str, dict] = {}
    for relative in sorted(_signature_map(root, CORRECTION_SOURCES_DIR, "move-*.md")):
        row = read_ordering_constraint(root, relative)
        if row is not None:
            rows.setdefault(row["constraint_id"], row)

    marks: dict[str, list[dict]] = {}
    for correction in load_temporal_corrections(root):
        if correction.scope != CONSTRAINT_CORRECTION_SCOPE:
            continue
        status = STATUS_BY_CORRECTION_KIND.get(correction.kind)
        if not status:
            continue
        for target in correction.claim_ids:
            marks.setdefault(target, []).append(
                _mark(status, correction.reason, correction.correction_id)
            )

    for row in rows.values():
        superseded = row.get("supersedes_constraint_id")
        if superseded and superseded in rows:
            marks.setdefault(superseded, []).append(
                _mark("superseded", "a later move replaced it", row["constraint_id"])
            )

    resolved: list[dict] = []
    for constraint_id in sorted(rows):
        row = dict(rows[constraint_id])
        own = sorted(
            {_mark_key(mark): mark for mark in marks.get(constraint_id, ())}.values(),
            key=_mark_key,
        )
        row["status"] = _strongest(own)
        row["marks"] = own
        resolved.append(row)
    return resolved


def active_ordering_constraints(vault_root: str | Path) -> list[dict]:
    """The moves a projection must honour — status ``active``, in id order."""
    return [row for row in load_ordering_constraints(vault_root) if row["status"] == "active"]


# --------------------------------------------------------------------------
# The fold
# --------------------------------------------------------------------------


def _mark(status: str, reason: str, by: str) -> dict:
    return {"status": status, "reason": reason, "by": by}


def _mark_key(mark: dict) -> str:
    return json.dumps(mark, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _strongest(marks: Sequence[dict]) -> str:
    best = "active"
    for mark in marks:
        status = mark.get("status", "active")
        if status not in STATUS_PRECEDENCE:
            continue
        if STATUS_PRECEDENCE.index(status) > STATUS_PRECEDENCE.index(best):
            best = status
    return best


@dataclass(frozen=True)
class _Contribution:
    """What ONE receipt contributes to the fold, and nothing else about it.

    Everything the fold reads off a receipt, flattened once so the arithmetic
    below never asks whether it is holding a freshly parsed
    :class:`temporal_claims.ExtractionReceipt` or a row the previous index
    already proved. ``claims`` are the rows the fold files verbatim — the
    claim's own ``to_dict`` plus which receipt carried it.
    """

    #: Where the bytes actually are. The fold's stable tiebreaker and the key
    #: every signature is recorded under, because a signature is a statement
    #: about a FILE.
    file_path: str
    #: What the receipt says its path is — derived from its source revision and
    #: extractor version, and what every emitted row cites. Equal to
    #: ``file_path`` for every receipt this store has written; kept separate
    #: because a receipt read from somewhere else must still cite itself.
    relative_path: str
    receipt_id: str
    source_id: str
    revision: str
    source_ref: dict
    extractor_version: str
    created_at: str
    extractor: dict
    claims: tuple[dict, ...]

    @property
    def sort_key(self) -> tuple[str, str, str]:
        """:func:`receipt_sort_key`, off the flattened row."""
        return (self.created_at, self.extractor_version, self.receipt_id)


@dataclass
class _FoldInputs:
    """Every durable input of one fold, with the signature that vouches for it.

    ``receipt_signatures`` / ``correction_signatures`` are whatever vouched for
    the file when it was last believed: a stat signature inside one process, a
    content signature when the inputs came back from the sidecar on disk.
    ``content_signatures`` is what the sidecar will be written from; a file
    without one is simply re-read by the next fold that starts from disk.
    """

    receipt_signatures: dict[str, tuple]
    correction_signatures: dict[str, tuple]
    contributions: dict[str, _Contribution]
    unreadable: dict[str, tuple]
    #: ``None`` means "this file is under ``sources/corrections/`` and is not a
    #: correction" — a move, or a source of some other kind. Remembering the
    #: negative is what keeps a vault's ordering constraints from being
    #: re-parsed as candidate corrections on every fold.
    corrections: dict[str, dict | None]
    content_signatures: dict[str, tuple] = field(default_factory=dict)
    #: The index object the last fold over exactly these inputs returned, so
    #: :func:`write_active_index` can tell whether the file it is about to
    #: publish is the one this sidecar would describe.
    folded: object = None
    #: The no-follow walker that produced ``receipt_signatures``. Held across
    #: folds in one process so an unchanged directory's names are read once,
    #: exactly as `receipt_read_batch` has always held one.
    inventory: object = None


#: At most this many vaults' inputs are remembered in one interpreter. A host
#: holds one vault and a test suite holds hundreds; the cap is what keeps the
#: second case from being a memory leak dressed as a cache.
_FOLD_MEMO_LIMIT = 4
_FOLD_MEMO: dict[str, _FoldInputs] = {}


def _fold_cache_enabled() -> bool:
    return collapsed_text(os.environ.get(FOLD_CACHE_ENV, "1")).lower() not in {
        "0", "off", "false", "no",
    }


def _memo_key(root: Path) -> str:
    return str(Path(os.path.abspath(root)))


def _remember(root: Path, inputs: _FoldInputs) -> None:
    key = _memo_key(root)
    _FOLD_MEMO.pop(key, None)
    _FOLD_MEMO[key] = inputs
    while len(_FOLD_MEMO) > _FOLD_MEMO_LIMIT:
        _FOLD_MEMO.pop(next(iter(_FOLD_MEMO)))


def forget_fold_inputs(vault_root: str | Path | None = None) -> None:
    """Drop the in-process input memo — for one vault, or for all of them.

    A test that rewrites a receipt's bytes inside one stat granule, or a host
    that wants the next fold to start from the files, calls this. It can only
    ever cost time: every caller re-reads what it drops.
    """
    if vault_root is None:
        _FOLD_MEMO.clear()
        return
    _FOLD_MEMO.pop(_memo_key(Path(os.path.abspath(Path(vault_root).expanduser()))), None)


def _contribution_of(receipt: ExtractionReceipt, file_path: str) -> _Contribution:
    claims: list[dict] = []
    for claim in receipt.claims:
        row = claim.to_dict()
        row["receipt_id"] = receipt.receipt_id
        row["receipt_path"] = receipt.relative_path
        claims.append(row)
    return _Contribution(
        file_path=file_path,
        relative_path=receipt.relative_path,
        receipt_id=receipt.receipt_id,
        source_id=receipt.source_ref.source_id,
        revision=receipt.source_ref.revision,
        source_ref=receipt.source_ref.to_dict(),
        extractor_version=receipt.extractor_version,
        created_at=receipt.created_at,
        extractor=dict(receipt.extractor or {}),
        claims=tuple(claims),
    )


def _read_fold_cache(root: Path) -> dict | None:
    """The sidecar, or ``None`` when there is nothing this version may trust."""
    text = _read_text(root, FOLD_CACHE_FILE)
    if text is None:
        return None
    try:
        payload = json.loads(text)
    except (TypeError, ValueError):
        return None
    if not isinstance(payload, dict):
        return None
    if payload.get("cache_version") != FOLD_CACHE_VERSION:
        return None
    if payload.get("index_version") != INDEX_VERSION:
        return None
    if payload.get("claim_schema_version") != SCHEMA_VERSION:
        return None
    return payload


def _signature_of(value: object) -> tuple | None:
    if not isinstance(value, list) or not value:
        return None
    return tuple(value)


def _is_content_signature(signature: tuple | None) -> bool:
    return (
        isinstance(signature, tuple)
        and len(signature) == 3
        and signature[0] == CONTENT_SIGNATURE_KIND
    )


def _content_signature(root: Path, relative: str) -> tuple | None:
    """``(kind, size, sha256)`` of one file's bytes, through the store's own
    no-follow reader; ``None`` for a file that reader will not hand back."""
    text = _read_text(root, relative)
    if text is None:
        return None
    data = text.encode("utf-8")
    return (CONTENT_SIGNATURE_KIND, len(data), hashlib.sha256(data).hexdigest())


def _still_vouched(
    root: Path, relative: str, signature: tuple, prior: _FoldInputs | None, table: dict[str, tuple]
) -> tuple | None:
    """The content signature to carry forward when ``prior`` still vouches for
    ``relative`` — by the same stat signature (same process) or by the same
    bytes (a sidecar from disk, possibly another machine's) — else ``None``."""
    if prior is None:
        return None
    remembered = table.get(relative)
    if remembered is None:
        return None
    if remembered == signature:
        return prior.content_signatures.get(relative) or (
            remembered if _is_content_signature(remembered) else None
        )
    if _is_content_signature(remembered) and _content_signature(root, relative) == remembered:
        return remembered
    return None


def _contributions_from_index(index: dict, declared: dict) -> dict[str, _Contribution] | None:
    """Rebuild each receipt's contribution from the index it already produced.

    The published index is the cache: every claim row in it is the row the
    fold filed, verbatim apart from the two keys the fold ADDED (``status``
    and ``status_marks``), and every receipt row carries the source ref, the
    extractor version and the creation time the grouping needs.

    The one thing the index can lose is a claim id filed by two receipts —
    ``entries`` is keyed by claim id, so the later writer wins and the earlier
    receipt's row is not on disk to be found. That is why both counts are
    checked, globally and per receipt: a vault where they agree has no such
    collision and the reconstruction is exact; a vault where they do not gets
    ``None`` and one honest full read.
    """
    claims = index.get("claims")
    receipts = index.get("receipts")
    if not isinstance(claims, list) or not isinstance(receipts, list):
        return None
    by_receipt: dict[str, list[dict]] = {}
    for row in claims:
        if not isinstance(row, dict):
            return None
        by_receipt.setdefault(collapsed_text(row.get("receipt_id")), []).append(
            {key: value for key, value in row.items()
             if key not in ("status", "status_marks")}
        )
    if len(claims) != sum(
        int(row.get("claim_count") or 0) for row in receipts if isinstance(row, dict)
    ):
        return None

    found: dict[str, _Contribution] = {}
    for row in receipts:
        if not isinstance(row, dict):
            return None
        relative = collapsed_text(row.get("relative_path"))
        receipt_id = collapsed_text(row.get("receipt_id"))
        source_ref = row.get("source_ref")
        if not relative or not receipt_id or not isinstance(source_ref, dict):
            return None
        if relative in found:
            return None
        rows = by_receipt.get(receipt_id, [])
        if len(rows) != int(row.get("claim_count") or 0):
            return None
        entry = declared.get(relative)
        block = entry.get("extractor") if isinstance(entry, dict) else None
        found[relative] = _Contribution(
            file_path=relative,
            relative_path=relative,
            receipt_id=receipt_id,
            source_id=collapsed_text(source_ref.get("source_id")),
            revision=collapsed_text(source_ref.get("revision")),
            source_ref=source_ref,
            extractor_version=collapsed_text(row.get("extractor_version")),
            created_at=collapsed_text(row.get("created_at")),
            extractor=block if isinstance(block, dict) else {},
            claims=tuple(rows),
        )
    return found


def _disk_inputs(root: Path) -> _FoldInputs | None:
    """The previous fold's inputs, reconstructed from what it published."""
    cache = _read_fold_cache(root)
    if cache is None:
        return None
    index_text = _read_text(root, ACTIVE_INDEX_FILE)
    if index_text is None:
        return None
    if hashlib.sha256(index_text.encode("utf-8")).hexdigest() != cache.get("index_sha256"):
        # Somebody republished the index without the sidecar, or the other way
        # round. Neither file is wrong; they just no longer describe each other.
        return None
    try:
        index = json.loads(index_text)
    except (TypeError, ValueError):
        return None
    if not isinstance(index, dict):
        return None

    declared = cache.get("receipts")
    declared = declared if isinstance(declared, dict) else {}
    contributions = _contributions_from_index(index, declared)
    if contributions is None:
        return None

    # `contributions` is keyed by the path each receipt CITES; the signatures
    # are keyed by the file those bytes were read from. They are the same
    # string for everything this store writes, and the sidecar records the
    # mapping anyway so that the one case where they differ reuses nothing
    # rather than reusing the wrong row.
    by_file: dict[str, _Contribution] = {}
    receipt_signatures: dict[str, tuple] = {}
    for relative, entry in declared.items():
        if not isinstance(entry, dict):
            continue
        signature = _signature_of(entry.get("signature"))
        cited = collapsed_text(entry.get("receipt_path")) or relative
        contribution = contributions.get(cited)
        if signature is None or contribution is None:
            continue
        receipt_signatures[relative] = signature
        by_file[relative] = _Contribution(
            file_path=relative,
            relative_path=contribution.relative_path,
            receipt_id=contribution.receipt_id,
            source_id=contribution.source_id,
            revision=contribution.revision,
            source_ref=contribution.source_ref,
            extractor_version=contribution.extractor_version,
            created_at=contribution.created_at,
            extractor=contribution.extractor,
            claims=contribution.claims,
        )

    unreadable: dict[str, tuple] = {}
    for relative, value in (cache.get("unreadable_receipts") or {}).items():
        signature = _signature_of(value)
        if signature is not None:
            unreadable[relative] = signature
            receipt_signatures[relative] = signature

    rows = index.get("corrections")
    by_path: dict[str, dict] = {}
    for row in (rows if isinstance(rows, list) else ()):
        # A correction row reaches the fold's mark arithmetic by name. One that
        # does not carry a kind this version knows, or an id, is not a record
        # this cache may hand back — the whole sidecar is refused rather than a
        # row quietly dropped, because "fewer corrections" is a wrong answer
        # that looks exactly like a right one.
        if not isinstance(row, dict) or not isinstance(row.get("claim_ids"), list):
            return None
        if row.get("kind") not in STATUS_BY_CORRECTION_KIND:
            return None
        relative = collapsed_text(row.get("relative_path"))
        if not relative or not collapsed_text(row.get("correction_id")):
            return None
        by_path[relative] = row
    correction_signatures: dict[str, tuple] = {}
    corrections: dict[str, dict | None] = {}
    for relative, entry in (cache.get("corrections") or {}).items():
        signature = _signature_of(entry.get("signature") if isinstance(entry, dict) else None)
        if signature is None:
            continue
        correction_signatures[relative] = signature
        corrections[relative] = by_path.get(relative)

    return _FoldInputs(
        receipt_signatures=receipt_signatures,
        correction_signatures=correction_signatures,
        contributions=by_file,
        unreadable=unreadable,
        corrections=corrections,
    )


def _receipt_inventory(root: Path) -> VaultDirectoryInventory:
    """The one no-follow walker over this vault's receipts.

    A live :func:`receipt_read_batch` owns one; a bare fold borrows the
    process memo's; a first fold builds one. There is never a second walker
    over the same tree, because two of them would each be able to say a
    directory was unchanged on the strength of the other's visit.
    """
    absolute = Path(os.path.abspath(root))
    batch = _RECEIPT_READ_BATCH.get()
    if batch is not None and not batch.closed:
        if batch.root != absolute:
            raise TemporalStoreError(
                "unsafe_store_path", "receipt batch cannot cross vaults"
            )
        return batch.inventory
    memo = _FOLD_MEMO.get(_memo_key(root))
    if memo is not None and isinstance(memo.inventory, VaultDirectoryInventory):
        return memo.inventory
    try:
        return VaultDirectoryInventory(absolute, RECEIPTS_DIR)
    except (OSError, ValueError) as exc:
        raise TemporalStoreError("unsafe_store_path", str(exc)) from exc


def _receipt_signature_map(
    root: Path, inventory: VaultDirectoryInventory
) -> dict[str, tuple]:
    """``{receipt path: signature}``, through the no-follow walk, every time.

    This is the one step v318 never skips and never caches. A symlink at any
    ancestor, a swapped directory, a replaced vault root: the walk fails
    closed on all of them, and it has to happen before any signature may be
    believed, because a signature is only evidence about a file the walk
    actually reached.
    """
    found: dict[str, tuple] = {}
    try:
        inventory.visit_files(lambda relative, signature: found.__setitem__(relative, signature))
    except (OSError, ValueError) as exc:
        raise TemporalStoreError("unsafe_store_path", str(exc)) from exc
    return found


def _prior_inputs(root: Path, *, full: bool) -> _FoldInputs | None:
    """What this process, or the published index, already proved about the vault."""
    if full or not _fold_cache_enabled():
        return None
    return _FOLD_MEMO.get(_memo_key(root)) or _disk_inputs(root)


def _correction_rows(
    root: Path,
    signatures: dict[str, tuple],
    prior: _FoldInputs | None,
    content: dict[str, tuple | None] | None = None,
) -> dict[str, dict | None]:
    if content is None:
        content = {}
    rows: dict[str, dict | None] = {}
    for relative, signature in signatures.items():
        vouched = (
            _still_vouched(root, relative, signature, prior, prior.correction_signatures)
            if prior is not None and relative in prior.corrections
            else None
        )
        if vouched is not None or (
            prior is not None
            and relative in prior.corrections
            and prior.correction_signatures.get(relative) == signature
        ):
            rows[relative] = prior.corrections[relative]
            content[relative] = vouched or _content_signature(root, relative)
            continue
        record = read_temporal_correction(root, relative)
        rows[relative] = None if record is None else record.to_dict()
        content[relative] = _content_signature(root, relative)
    return rows


def fold_inputs(vault_root: str | Path, *, full: bool = False) -> _FoldInputs:
    """Read every durable fold input, re-reading only what actually moved.

    The directory walk is never skipped: names, sizes, inodes and modification
    times are collected fresh on every call, because "did anything change" is
    the one question a cache may not answer for itself. What a matching
    signature buys is the right not to open, parse and re-validate that one
    file — which is where v317 spent 7 of its 9 seconds on a 9,000-receipt
    vault, almost all of it in the no-follow path checks each open repeats.

    ``full=True`` and ``LIFEHUG_TEMPORAL_FOLD_CACHE=0`` both read everything.
    """
    root = _vault_root(vault_root)
    inventory = _receipt_inventory(root)
    if full:
        # A full read re-scans every directory too, not only every file: the
        # escape hatch has to be able to say "believe nothing you remember".
        inventory.clear()
    receipt_signatures = _receipt_signature_map(root, inventory)
    correction_signatures = _signature_map(root, CORRECTION_SOURCES_DIR, "*.md")

    prior = _prior_inputs(root, full=full)

    fresh = _FoldInputs(
        receipt_signatures=receipt_signatures,
        correction_signatures=correction_signatures,
        contributions={},
        unreadable={},
        corrections={},
        inventory=inventory,
    )
    for relative, signature in receipt_signatures.items():
        vouched = _still_vouched(root, relative, signature, prior, prior.receipt_signatures) \
            if prior is not None else None
        same_stat = prior is not None and prior.receipt_signatures.get(relative) == signature
        if vouched is not None or same_stat:
            reused = prior.contributions.get(relative)
            if reused is not None:
                fresh.contributions[relative] = reused
                if vouched is not None:
                    fresh.content_signatures[relative] = vouched
                continue
            if relative in prior.unreadable:
                fresh.unreadable[relative] = signature
                if vouched is not None:
                    fresh.content_signatures[relative] = vouched
                continue
        receipt = read_receipt(root, relative)
        if receipt is None:
            fresh.unreadable[relative] = signature
        else:
            fresh.contributions[relative] = _contribution_of(receipt, relative)
        digest = _content_signature(root, relative)
        if digest is not None:
            fresh.content_signatures[relative] = digest

    correction_content: dict[str, tuple | None] = {}
    fresh.corrections = _correction_rows(root, correction_signatures, prior, correction_content)
    for relative, digest in correction_content.items():
        if digest is not None:
            fresh.content_signatures[relative] = digest

    if _fold_cache_enabled():
        _remember(root, fresh)
    return fresh


def _fold(inputs: _FoldInputs) -> dict:
    """The fold itself — pure arithmetic over :class:`_FoldInputs`, no I/O.

    Byte-for-byte the v221 algorithm. It is separated from the reading only so
    that "what the fold computes" and "how the inputs were obtained" can be
    tested against each other: the incremental read and the full read hand
    this function the same inputs, so they cannot produce different bytes.
    """
    contributions = sorted(inputs.contributions.values(), key=lambda item: item.file_path)
    contributions.sort(key=lambda item: item.sort_key)
    correction_rows = sorted(
        (row for row in inputs.corrections.values() if isinstance(row, dict)),
        key=lambda row: (
            collapsed_text(row.get("correction_id")),
            collapsed_text(row.get("relative_path")),
        ),
    )
    unreadable = sorted(inputs.unreadable)

    # :data:`A_READING_IS_ONLY_SUPERSEDED_BY_THE_SAME_READER`. The third
    # member of the key is the EXTRACTOR, and it is what makes the election an
    # election between re-readings rather than between readers.
    groups: dict[tuple[str, str, str], list[_Contribution]] = {}
    for contribution in contributions:
        groups.setdefault(
            (
                contribution.source_id,
                contribution.revision,
                extractor_identity(contribution.extractor_version),
            ),
            [],
        ).append(contribution)

    entries: dict[str, dict] = {}
    marks: dict[str, list[dict]] = {}
    receipt_rows: list[dict] = []
    source_rows: list[dict] = []
    selected_ids: set[str] = set()

    for key in sorted(groups):
        ordered = sorted(groups[key], key=lambda item: item.sort_key)
        winner = ordered[-1]
        selected_ids.add(winner.receipt_id)
        source_rows.append(
            {
                "source_id": key[0],
                "revision": key[1],
                "extractor_identity": key[2],
                "selected_receipt_id": winner.receipt_id,
                "selected_receipt_path": winner.relative_path,
                "receipt_ids": sorted(item.receipt_id for item in ordered),
            }
        )
        for contribution in ordered:
            is_winner = contribution.receipt_id == winner.receipt_id
            for row in contribution.claims:
                claim_id = collapsed_text(row.get("claim_id"))
                entries[claim_id] = copy.deepcopy(row)
                marks.setdefault(claim_id, [])
                if not is_winner:
                    marks[claim_id].append(
                        _mark("superseded", "reextracted", winner.receipt_id)
                    )

    for contribution in contributions:
        if contribution.receipt_id not in selected_ids:
            continue
        for row in contribution.claims:
            for target in row.get("supersedes_claim_ids") or ():
                marks.setdefault(collapsed_text(target), []).append(
                    _mark("superseded", "superseded_by_claim", collapsed_text(row.get("claim_id")))
                )

    # v349. Reinstatement is resolved as a SET, before any mark is laid, so the
    # fold stays a function of the corrections on disk and not of the order
    # they were discovered in. A `retract` scoped to
    # `CORRECTION_CORRECTION_SCOPE` names CORRECTIONS, never claims: the marks
    # those corrections laid stop standing, which is how the vault says "that
    # correction was not a correction" without editing or deleting a byte of
    # it. See the scope's own note for the incident that needed the verb.
    reinstated = {
        collapsed_text(target)
        for correction in correction_rows
        if correction.get("scope") == CORRECTION_CORRECTION_SCOPE
        and correction["kind"] == "retract"
        for target in correction.get("claim_ids") or ()
    }

    unresolved: set[str] = set()
    for correction in correction_rows:
        if correction.get("scope") == CORRECTION_CORRECTION_SCOPE:
            # It acts on corrections, not on claims. Its targets are not claim
            # ids and must never be reported as unresolved ones.
            continue
        if correction["correction_id"] in reinstated:
            continue
        status = STATUS_BY_CORRECTION_KIND[correction["kind"]]
        for target in correction.get("claim_ids") or ():
            if target not in entries:
                unresolved.add(target)
            marks.setdefault(target, []).append(
                _mark(status, f"correction_{correction['kind']}", correction["correction_id"])
            )

    claims: list[dict] = []
    counts = {status: 0 for status in CLAIM_STATUSES}
    for claim_id in sorted(entries):
        row = dict(entries[claim_id])
        claim_marks = sorted(marks.get(claim_id, []), key=_mark_key)
        row["status"] = _strongest(claim_marks)
        row["status_marks"] = claim_marks
        counts[row["status"]] = counts.get(row["status"], 0) + 1
        claims.append(row)

    for contribution in contributions:
        receipt_rows.append(
            {
                "receipt_id": contribution.receipt_id,
                "relative_path": contribution.relative_path,
                "source_ref": copy.deepcopy(contribution.source_ref),
                "extractor_version": contribution.extractor_version,
                "created_at": contribution.created_at,
                "claim_count": len(contribution.claims),
                "selected": contribution.receipt_id in selected_ids,
            }
        )
    receipt_rows.sort(key=lambda row: (row["relative_path"], row["receipt_id"]))

    counts.update(
        {
            "claims": len(claims),
            "receipts": len(receipt_rows),
            "selected_receipts": len(selected_ids),
            # One row per READING (v354), so the count of source revisions is
            # taken over the rows rather than from their number: a reader that
            # arrives beside another must not make a vault look as though it
            # grew a source.
            "readings": len(source_rows),
            "sources": len({(row["source_id"], row["revision"]) for row in source_rows}),
            "corrections": len(correction_rows),
        }
    )

    return {
        "version": INDEX_VERSION,
        "claim_schema_version": SCHEMA_VERSION,
        "counts": counts,
        "sources": source_rows,
        "receipts": receipt_rows,
        "corrections": copy.deepcopy(correction_rows),
        "claims": claims,
        "active_claim_ids": [
            row["claim_id"] for row in claims if row["status"] == "active"
        ],
        "unresolved_correction_targets": sorted(unresolved),
        "unreadable_receipt_paths": unreadable,
    }


def fold_active_index(vault_root: str | Path, *, full: bool = False) -> dict:
    """Rebuild the active claim index from receipts and corrections. Pure.

    The whole algorithm, in the order it runs — and none of it depends on the
    order anything was discovered in:

    1. **Group receipts by (source_id, revision, extractor identity).** Within
       a group the winner is the latest by :func:`receipt_sort_key`; every other
       receipt in the group is a *previous interpretation* of the same words by
       the same reader, and its claims are kept with status ``superseded``. That
       is what "re-extraction is a new interpretation, never a cache rebuild"
       costs and buys. The extractor is in the key
       (:data:`A_READING_IS_ONLY_SUPERSEDED_BY_THE_SAME_READER`, v354) because
       a prompt edit, a new model or a bumped rule version is a later version
       of ONE reader — which is exactly what supersession is for — while
       `general_listener` and `answer_placement` reading one promoted reply are
       two readings of it and neither retires the other.
    2. **Apply ``supersedes_claim_ids``** carried by claims from *winning*
       receipts only. A stale interpretation does not get to retire anything.
    3. **Apply corrections.** Each cited claim collects a mark; supersede,
       retract and dispute each set their one status.
    4. **Resolve each claim's status as the strongest mark it carries**, not the
       last one applied, and emit every mark alongside so a person can see why.

    Nothing is dropped. A correction naming a claim that does not exist is
    reported in ``unresolved_correction_targets`` instead of vanishing, and a
    receipt that will not parse is reported in ``unreadable_receipt_paths``.

    The returned mapping contains **no wall-clock field**, which is what makes
    "delete the index, rebuild it, compare the bytes" a real test rather than a
    slogan.

    v318: the READING is incremental (:func:`fold_inputs`) and the arithmetic
    (:func:`_fold`) is not. A receipt whose stat signature has not moved is not
    opened again; everything else is read exactly as before, and the fold runs
    over the whole vault's inputs every time. So the output is a function of
    the receipts and corrections on disk and of nothing else — the cache can
    only make the same answer arrive sooner, never make a different one
    arrive at all. ``full=True`` reads every file regardless, which is what
    `temporal_publication.verify` and the ``--rebuild`` repair path use.
    """
    root = _vault_root(vault_root)
    inputs = fold_inputs(root, full=full)
    index = _fold(inputs)
    inputs.folded = index
    return index


def receipt_declarations(
    vault_root: str | Path, *, full: bool = False
) -> tuple[dict[str, dict], list[str]]:
    """``({receipt_id: {"extractor": block}}, unreadable_paths)``.

    What a reader needs about a receipt that the active index does not carry:
    the extractor's DECLARATION about its own run — `event_identity`'s telling
    keys, document revision and recorder event id all live there. Shaped as a
    mapping so `event_identity._extractor_block` reads it exactly as it reads
    a receipt, and served from the same incremental inputs as the fold, so a
    manifest rebuild no longer re-parses nine thousand receipts to find eight
    thousand declarations it already had.
    """
    inputs = fold_inputs(_vault_root(vault_root), full=full)
    return (
        {
            contribution.receipt_id: {"extractor": copy.deepcopy(contribution.extractor)}
            for contribution in inputs.contributions.values()
        },
        sorted(inputs.unreadable),
    )


def active_index_bytes(index: dict) -> str:
    """The index's one serialization — canonical, sorted, newline-terminated."""
    return _canonical_json(index)


def _fold_cache_payload(inputs: _FoldInputs, index_text: str) -> dict:
    """Content signatures only: a file this fold never hashed is left out of
    the sidecar, and the next fold that starts from disk reads it."""
    receipts: dict[str, dict] = {}
    for file_path, contribution in inputs.contributions.items():
        digest = inputs.content_signatures.get(file_path)
        if digest is None:
            continue
        entry: dict = {"signature": list(digest)}
        if contribution.relative_path != file_path:
            entry["receipt_path"] = contribution.relative_path
        if contribution.extractor:
            entry["extractor"] = contribution.extractor
        receipts[file_path] = entry
    return {
        "cache_version": FOLD_CACHE_VERSION,
        "index_version": INDEX_VERSION,
        "claim_schema_version": SCHEMA_VERSION,
        "index_sha256": hashlib.sha256(index_text.encode("utf-8")).hexdigest(),
        "receipts": receipts,
        "unreadable_receipts": {
            path: list(inputs.content_signatures[path])
            for path in inputs.unreadable
            if path in inputs.content_signatures
        },
        "corrections": {
            path: {"signature": list(inputs.content_signatures[path])}
            for path in inputs.correction_signatures
            if path in inputs.content_signatures
        },
    }


def _write_fold_cache(root: Path, index: dict, index_text: str) -> None:
    """Record what the index just published was folded FROM — or record nothing.

    The sidecar is written only for an index this process folded, identified by
    object identity rather than by a re-read: a caller that hands
    :func:`write_active_index` an index it built some other way gets its file
    published and no claim made about its inputs, and the next fold reads
    every receipt. A stale sidecar is harmless for the same reason — it names
    a digest the index no longer has, and :func:`_disk_inputs` refuses it.
    """
    if not _fold_cache_enabled():
        return
    inputs = _FOLD_MEMO.get(_memo_key(root))
    if inputs is None or inputs.folded is not index:
        return
    try:
        atomic_write_vault_text(
            store_path(root, FOLD_CACHE_FILE),
            _canonical_json(_fold_cache_payload(inputs, index_text)),
            vault_root=root,
        )
    except (OSError, ValueError, KeyError):
        # A cache that cannot be written is a cache that is not there. The
        # index is already published and correct; the next fold is just slow.
        return


def write_active_index(vault_root: str | Path, index: dict) -> Path:
    """Publish the index atomically. This is the one file here that may be
    replaced, because it is a materialized view and never evidence.

    v318: an index whose bytes are already the bytes on disk is not rewritten.
    On a large vault that is 27 MiB of I/O and a git-visible mtime per compile,
    for a file that would come out identical — and the sidecar beside it is
    what a later fold reads instead of nine thousand receipts, so the two are
    written together or not at all.
    """
    root = _vault_root(vault_root)
    path = store_path(root, ACTIVE_INDEX_FILE)
    text = active_index_bytes(index)
    if _read_text(root, ACTIVE_INDEX_FILE) != text:
        try:
            atomic_write_vault_text(path, text, vault_root=root)
        except ValueError as exc:
            raise TemporalStoreError("unsafe_store_path", str(exc)) from exc
    _write_fold_cache(root, index, text)
    return path


def rebuild_active_index(vault_root: str | Path, *, full: bool = False) -> dict:
    """Fold, publish, return. Deleting the file first must change nothing.

    ``full=True`` is the escape hatch: every receipt and every correction is
    read from disk, whatever the sidecar says, and the sidecar is rewritten
    from that reading.
    """
    index = fold_active_index(vault_root, full=full)
    write_active_index(vault_root, index)
    return index


def read_active_index(vault_root: str | Path) -> dict | None:
    """The published index, or ``None`` when it has never been built."""
    content = _read_text(vault_root, ACTIVE_INDEX_FILE)
    if content is None:
        return None
    try:
        value = json.loads(content)
    except json.JSONDecodeError as exc:
        raise TemporalStoreError(
            "active_index_unreadable", f"{ACTIVE_INDEX_FILE} is not JSON"
        ) from exc
    return value if isinstance(value, dict) else None


def active_claims(index: dict) -> list[dict]:
    """The claims a projection may calculate from — status ``active``, in id order."""
    rows = index.get("claims") if isinstance(index, dict) else None
    return [row for row in (rows or ()) if row.get("status") == "active"]


# --------------------------------------------------------------------------
# The pairing rule, in one call
# --------------------------------------------------------------------------


def file_message_extraction(
    vault_root: str | Path,
    *,
    message_text: str,
    extractor_version: str,
    claims_for: Callable[[SourceRef], Sequence[object]],
    metadata: object = None,
    extractor: object = None,
    recorder: str | None = None,
    now: object = None,
) -> tuple[SourceRef, Path]:
    """Promote the message, then file the receipt — in that order, both idempotent.

    ``claims_for`` receives the promoted :class:`SourceRef` and returns the
    claims, because a claim's identity is derived from the source it interprets:
    the source must exist before a claim can name itself. A crash after the
    promotion and before the receipt leaves a source with no receipt, which the
    next identical call completes; a crash cannot leave a receipt with no source,
    which is the asymmetry the whole ordering exists to buy.
    """
    meta = dict(metadata) if isinstance(metadata, dict) else {}
    source_ref = promote_conversational_source(vault_root, message_text, meta)
    claims: list[dict] = []
    for raw in claims_for(source_ref) or ():
        claim = dict(raw.to_dict()) if hasattr(raw, "to_dict") else dict(raw)  # type: ignore[union-attr]
        claim.setdefault("source_ref", source_ref.to_dict())
        claim.setdefault("extractor_version", extractor_version)
        claims.append(claim)

    payload = {
        "source_ref": source_ref.to_dict(),
        "extractor_version": extractor_version,
        "extractor": dict(extractor) if isinstance(extractor, dict) else {},
        "claims": claims,
        "idempotency_key": derive_extraction_idempotency_key(
            session_ref=meta.get("session_ref"),
            turn_ref=meta.get("turn_ref"),
            source_ref=source_ref,
            recorder=recorder,
            extractor_version=extractor_version,
        ),
    }
    if recorder:
        payload["recorder"] = recorder
    return source_ref, write_receipt(vault_root, payload, now=now)


__all__ = [
    "A_READING_IS_ONLY_SUPERSEDED_BY_THE_SAME_READER",
    "CONSTRAINT_CORRECTION_SCOPE",
    "CORRECTION_CORRECTION_SCOPE",
    "CONVERSATION_SOURCES_DIR",
    "CONVERSATION_SOURCE_TYPE",
    "CORRECTION_IDENTITY_KEYS",
    "CORRECTION_ID_PREFIX",
    "CORRECTION_KINDS",
    "CONTENT_SIGNATURE_KIND",
    "FOLD_CACHE_ENV",
    "FOLD_CACHE_FILE",
    "FOLD_CACHE_VERSION",
    "FRONTMATTER_ORDER",
    "MOVE_IDENTITY_KEYS",
    "MOVE_REASON_MAX_CHARS",
    "ORDERING_CONSTRAINT_TYPE",
    "INDEX_VERSION",
    "PROMOTION_IDENTITY_KEYS",
    "RECEIPT_ANNOTATION_KEYS",
    "STATUS_BY_CORRECTION_KIND",
    "STATUS_PRECEDENCE",
    "STORE_ERROR_CODES",
    "TEMPORAL_CORRECTION_TYPE",
    "TemporalCorrection",
    "TemporalStoreError",
    "active_claims",
    "active_index_bytes",
    "active_ordering_constraints",
    "active_index_path",
    "constraint_relative_path",
    "create_or_keep",
    "conversation_source_relative_path",
    "correction_relative_path",
    "derive_correction_id",
    "dispute_claims",
    "file_message_extraction",
    "file_ordering_constraint",
    "file_temporal_correction",
    "fold_active_index",
    "fold_inputs",
    "forget_fold_inputs",
    "format_frontmatter",
    "load_ordering_constraints",
    "load_receipts",
    "load_temporal_corrections",
    "normalize_payload",
    "payload_sha256",
    "move_digest",
    "promote_conversational_source",
    "promotion_digest",
    "read_active_index",
    "read_ordering_constraint",
    "read_receipt",
    "read_source_ref",
    "read_store_text",
    "read_temporal_correction",
    "rebuild_active_index",
    "receipt_declarations",
    "receipt_path",
    "receipt_relative_paths",
    "receipt_sort_key",
    "retract_claims",
    "retract_ordering_constraint",
    "split_frontmatter",
    "store_path",
    "reinstate_corrections",
    "reinstated_correction_ids",
    "supersede_claims",
    "write_active_index",
    "write_receipt",
]
