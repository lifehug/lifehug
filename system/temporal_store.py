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

import hashlib
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, Sequence

SYSTEM_DIR = Path(__file__).resolve().parent
if str(SYSTEM_DIR) not in sys.path:
    sys.path.insert(0, str(SYSTEM_DIR))

from temporal_claims import (  # noqa: E402
    ACTIVE_INDEX_FILE,
    CLAIM_STATUSES,
    CORRECTION_SOURCES_DIR,
    RECEIPTS_DIR,
    SCHEMA_VERSION,
    ExtractionReceipt,
    SourceRef,
    TemporalContractError,
    collapsed_text,
    derive_extraction_idempotency_key,
    digest_id,
    normalized_timestamp,
    receipt_from_dict,
    receipt_relative_path,
    validate_extraction_receipt,
    validate_source_ref,
)
from vault_paths import (  # noqa: E402
    atomic_create_vault_bytes,
    atomic_write_vault_text,
    read_vault_text,
    validate_contained_path,
)

# --------------------------------------------------------------------------
# Layout and vocabulary
# --------------------------------------------------------------------------

#: Promoted conversational sources (owner amendment 2 / option B). A message
#: that produced a claim is an evidence document like any other, so it lives
#: under ``sources/`` beside manual stories, imports and corrections rather
#: than in ``state/`` — state is rebuildable and evidence never is.
CONVERSATION_SOURCES_DIR = "sources/conversations"

#: The active index's own format version (the file's ``version`` field). It is
#: independent of :data:`temporal_claims.SCHEMA_VERSION`, which versions the
#: records inside it.
INDEX_VERSION = 1

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


def _read_text(vault_root: str | Path, relative: str) -> str | None:
    root = _vault_root(vault_root)
    path = store_path(root, relative)
    if not path.is_file():
        return None
    try:
        return read_vault_text(path, vault_root=root)
    except (OSError, ValueError):
        return None


def _create_or_keep(vault_root: str | Path, relative: str, content: str) -> tuple[Path, bool]:
    """Publish a new immutable file; report whether this call created it."""
    root = _vault_root(vault_root)
    path = store_path(root, relative)
    try:
        atomic_create_vault_bytes(path, content.encode("utf-8"), vault_root=root)
    except FileExistsError:
        return path, False
    except ValueError as exc:
        raise TemporalStoreError("unsafe_store_path", str(exc)) from exc
    return path, True


# --------------------------------------------------------------------------
# Option B — the promoted conversational source
# --------------------------------------------------------------------------


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
    ``title`` and ``visibility``. Only the first two participate in identity.
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
        "type": CONVERSATION_SOURCE_TYPE,
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
    for key in ("session_ref", "turn_ref", "speaker"):
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
    the path is already occupied by byte-identical content and nothing is
    written. Re-running a *different* extractor writes a new receipt beside the
    old one, because a later model reading the same prose is a new
    interpretation and not a cache rebuild (plan §1.3). An attempt to change an
    existing receipt's bytes in place is refused by name — that is the only
    thing this store treats as corruption rather than as history.

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
    if existing == content:
        return path
    raise TemporalStoreError(
        "receipt_immutable_conflict",
        f"{relative} already holds a different interpretation; "
        "re-extraction writes a new receipt, it never rewrites one",
        detail={"receipt_id": normalized["receipt_id"]},
    )


def receipt_relative_paths(vault_root: str | Path) -> list[str]:
    """Every checked-in receipt path, sorted — the fold's only input listing."""
    root = _vault_root(vault_root)
    base = store_path(root, RECEIPTS_DIR)
    if not base.is_dir():
        return []
    found: list[str] = []
    for path in base.rglob("*.json"):
        if path.is_symlink() or not path.is_file():
            continue
        found.append(path.relative_to(root).as_posix())
    return sorted(found)


def read_receipt(vault_root: str | Path, relative: str) -> ExtractionReceipt | None:
    """Tolerant read (compat rule 2): unknown keys ignored, unknown schema
    versions read for the fields this version knows, unreadable files ``None``."""
    content = _read_text(vault_root, relative)
    if content is None:
        return None
    try:
        payload = json.loads(content)
    except json.JSONDecodeError:
        return None
    return receipt_from_dict(payload)


def load_receipts(
    vault_root: str | Path,
) -> tuple[list[ExtractionReceipt], list[str]]:
    """``(receipts, unreadable_relative_paths)`` — both sorted, neither hidden."""
    receipts: list[ExtractionReceipt] = []
    unreadable: list[str] = []
    for relative in receipt_relative_paths(vault_root):
        receipt = read_receipt(vault_root, relative)
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


def load_temporal_corrections(vault_root: str | Path) -> list[TemporalCorrection]:
    """Every temporal correction in the vault, sorted by id."""
    root = _vault_root(vault_root)
    base = store_path(root, CORRECTION_SOURCES_DIR)
    if not base.is_dir():
        return []
    corrections: list[TemporalCorrection] = []
    for path in sorted(base.rglob("*.md")):
        if path.is_symlink() or not path.is_file():
            continue
        correction = read_temporal_correction(root, path.relative_to(root).as_posix())
        if correction is not None:
            corrections.append(correction)
    corrections.sort(key=lambda item: (item.correction_id, item.relative_path))
    return corrections


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


def fold_active_index(vault_root: str | Path) -> dict:
    """Rebuild the active claim index from receipts and corrections. Pure.

    The whole algorithm, in the order it runs — and none of it depends on the
    order anything was discovered in:

    1. **Group receipts by (source_id, revision).** Within a group the winner is
       the latest by :func:`receipt_sort_key`; every other receipt in the group
       is a *previous interpretation* of the same words, and its claims are kept
       with status ``superseded``. That is what "re-extraction is a new
       interpretation, never a cache rebuild" costs and buys.
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
    """
    receipts, unreadable = load_receipts(vault_root)
    corrections = load_temporal_corrections(vault_root)

    groups: dict[tuple[str, str], list[ExtractionReceipt]] = {}
    for receipt in receipts:
        key = (receipt.source_ref.source_id, receipt.source_ref.revision)
        groups.setdefault(key, []).append(receipt)

    entries: dict[str, dict] = {}
    marks: dict[str, list[dict]] = {}
    receipt_rows: list[dict] = []
    source_rows: list[dict] = []
    selected_ids: set[str] = set()

    for key in sorted(groups):
        ordered = sorted(groups[key], key=receipt_sort_key)
        winner = ordered[-1]
        selected_ids.add(winner.receipt_id)
        source_rows.append(
            {
                "source_id": key[0],
                "revision": key[1],
                "selected_receipt_id": winner.receipt_id,
                "selected_receipt_path": winner.relative_path,
                "receipt_ids": sorted(item.receipt_id for item in ordered),
            }
        )
        for receipt in ordered:
            is_winner = receipt.receipt_id == winner.receipt_id
            for claim in receipt.claims:
                row = claim.to_dict()
                row["receipt_id"] = receipt.receipt_id
                row["receipt_path"] = receipt.relative_path
                entries[claim.claim_id] = row
                marks.setdefault(claim.claim_id, [])
                if not is_winner:
                    marks[claim.claim_id].append(
                        _mark("superseded", "reextracted", winner.receipt_id)
                    )

    for receipt in receipts:
        if receipt.receipt_id not in selected_ids:
            continue
        for claim in receipt.claims:
            for target in claim.supersedes_claim_ids:
                marks.setdefault(target, []).append(
                    _mark("superseded", "superseded_by_claim", claim.claim_id)
                )

    unresolved: set[str] = set()
    for correction in corrections:
        status = STATUS_BY_CORRECTION_KIND[correction.kind]
        for target in correction.claim_ids:
            if target not in entries:
                unresolved.add(target)
            marks.setdefault(target, []).append(
                _mark(status, f"correction_{correction.kind}", correction.correction_id)
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

    for receipt in receipts:
        receipt_rows.append(
            {
                "receipt_id": receipt.receipt_id,
                "relative_path": receipt.relative_path,
                "source_ref": receipt.source_ref.to_dict(),
                "extractor_version": receipt.extractor_version,
                "created_at": receipt.created_at,
                "claim_count": len(receipt.claims),
                "selected": receipt.receipt_id in selected_ids,
            }
        )
    receipt_rows.sort(key=lambda row: (row["relative_path"], row["receipt_id"]))

    counts.update(
        {
            "claims": len(claims),
            "receipts": len(receipt_rows),
            "selected_receipts": len(selected_ids),
            "sources": len(source_rows),
            "corrections": len(corrections),
        }
    )

    return {
        "version": INDEX_VERSION,
        "claim_schema_version": SCHEMA_VERSION,
        "counts": counts,
        "sources": source_rows,
        "receipts": receipt_rows,
        "corrections": [correction.to_dict() for correction in corrections],
        "claims": claims,
        "active_claim_ids": [
            row["claim_id"] for row in claims if row["status"] == "active"
        ],
        "unresolved_correction_targets": sorted(unresolved),
        "unreadable_receipt_paths": unreadable,
    }


def active_index_bytes(index: dict) -> str:
    """The index's one serialization — canonical, sorted, newline-terminated."""
    return _canonical_json(index)


def write_active_index(vault_root: str | Path, index: dict) -> Path:
    """Publish the index atomically. This is the one file here that may be
    replaced, because it is a materialized view and never evidence."""
    root = _vault_root(vault_root)
    path = store_path(root, ACTIVE_INDEX_FILE)
    try:
        atomic_write_vault_text(path, active_index_bytes(index), vault_root=root)
    except ValueError as exc:
        raise TemporalStoreError("unsafe_store_path", str(exc)) from exc
    return path


def rebuild_active_index(vault_root: str | Path) -> dict:
    """Fold, publish, return. Deleting the file first must change nothing."""
    index = fold_active_index(vault_root)
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
    "CONVERSATION_SOURCES_DIR",
    "CONVERSATION_SOURCE_TYPE",
    "CORRECTION_IDENTITY_KEYS",
    "CORRECTION_ID_PREFIX",
    "CORRECTION_KINDS",
    "FRONTMATTER_ORDER",
    "INDEX_VERSION",
    "PROMOTION_IDENTITY_KEYS",
    "STATUS_BY_CORRECTION_KIND",
    "STATUS_PRECEDENCE",
    "STORE_ERROR_CODES",
    "TEMPORAL_CORRECTION_TYPE",
    "TemporalCorrection",
    "TemporalStoreError",
    "active_claims",
    "active_index_bytes",
    "active_index_path",
    "conversation_source_relative_path",
    "correction_relative_path",
    "derive_correction_id",
    "dispute_claims",
    "file_message_extraction",
    "file_temporal_correction",
    "fold_active_index",
    "format_frontmatter",
    "load_receipts",
    "load_temporal_corrections",
    "normalize_payload",
    "payload_sha256",
    "promote_conversational_source",
    "promotion_digest",
    "read_active_index",
    "read_receipt",
    "read_source_ref",
    "read_temporal_correction",
    "rebuild_active_index",
    "receipt_path",
    "receipt_relative_paths",
    "receipt_sort_key",
    "retract_claims",
    "split_frontmatter",
    "store_path",
    "supersede_claims",
    "write_active_index",
    "write_receipt",
]
