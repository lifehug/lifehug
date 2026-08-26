#!/usr/bin/env python3
"""One fact, one record, one source — the temporal claim contracts (v219).

Every date the system holds is an *interpretation of a source*. This module is
the single authoritative definition of what such an interpretation looks like:
the claim, the ordering constraint a correction writes, the extraction receipt
that makes a claim traceable, and the deterministic identities that make all
three idempotent. It is pure — no I/O, no model, no vault. The store, the
fold, and the projection are built on top of it (waves B–D of the audited
timeline build plan, §9); the shapes are frozen here so they cannot drift
apart across the package, the CLI, the worker, the API and the hosted
platform.

The pipeline these contracts sit in (plan §3)::

    operational conversation turn
            |
            v
    durable vault source / correction        <- SourceRef, always
            |
            v
    versioned temporal extraction receipt    <- ExtractionReceipt
            |
            v
    deterministic active temporal claims     <- TemporalClaim
            |                                   + OrderingConstraint
            v
    pure calculated timeline                 <- temporal_projection.py

Four rules the shapes enforce rather than merely describe:

**One fact, one record.** ``"I have four children: Ada, Bo, Cy, and Della"`` is
four claims, never one aggregate pseudo-person (plan §5.1, §10). The validator
refuses an enumerated ``subject_mention`` by name — :func:`split_subject_enumeration`
tells the caller exactly which claims to mint instead.

**Person identity and event transitions are distinct records.** A date is
always the date *of an event*, never of a person, so every dated claim carries
an ``event_kind``; an ``identity`` claim carries no date and no event. First
meeting, dating start, engagement, marriage, separation and reconciliation are
therefore six different records about the same two people (plan §5.1, §6.3).

**One source, universally.** ``source_ref`` always names a vault source plus an
immutable revision (owner amendment Q2/option B, 2026-08-26). A conversational
message that produces a claim is promoted to a vault source record *first*;
there is no "this one only lives in the session store" claim. The turn that
carried the sentence is recorded in the evidence, not in place of the source.

**The raw mention is never lost.** ``subject_mention`` is required even after
``subject_ref`` resolves, and it — not the resolved ref — is what the claim's
identity is derived from, so resolving an alias later never re-mints the claim
(plan §6.3, §5.1).

Deterministic identity
----------------------

:func:`derive_claim_id`, :func:`derive_constraint_id` and
:func:`derive_extraction_idempotency_key` are pure functions of a frozen key
list. Re-running an extraction over the same source revision with the same
extractor produces the same ids, so a retry cannot double-file a claim, a
person, an event or a correction (plan §6.1, §10). Identity deliberately
excludes everything that is annotation rather than assertion — ``created_at``,
``confidence``, ``status``, ``evidence``, ``subject_ref``, ``event_ref`` — so
later resolution and later supersession leave ids alone.

Dates
-----

``temporal_value`` is a :class:`chronology.DateRecord` (the package's one date
definition: an EDTF interval with a granularity, a confidence, a basis, its
anchors and its provenance) or an :class:`OrderingRelation` for a claim that
only fixes order. There is no second date parser here and there must never be
one; ``chronology`` owns EDTF, intervals, arithmetic and reconciliation.

Note the two ``basis`` vocabularies are different questions and both are
needed. ``chronology.BASES`` answers *how was this interval arrived at*
(stated, age, anchor, order, public_event, connector, document, photo,
relative). :data:`CLAIM_BASES` answers the coarser epistemic question the
product surfaces render — *did the person say it, did we compute it, or did we
judge it* (explicit / calculated / inferred, plan §5.1, §8.1).
:data:`CLAIM_BASIS_BY_DATE_BASIS` is the one mapping between them and covers
every value of ``chronology.BASES``, so a new date basis fails this module's
tests rather than silently rendering as "inferred".

Schema version and compatibility
--------------------------------

:data:`SCHEMA_VERSION` is ``1``. The compatibility rule, which is what makes
"versioned receipts mean old receipts stay parseable forever" true rather than
aspirational (plan §4.2):

1. **Evolution is additive only.** A new version may add optional fields with
   defaults. It may never remove a field, rename a field, narrow a field's
   type, or repurpose a field's meaning. Removing or repurposing requires a new
   schema version *and* keeping the old reader.
2. **Readers are tolerant; writers are strict.** ``*_from_dict`` never raises:
   an unknown key is ignored and a missing optional key takes its default, so a
   receipt written by version 1 is readable by every later version and a
   receipt written by a *newer* version degrades to the fields this version
   knows instead of failing the fold. ``validate_*`` raises typed errors and is
   the door every write goes through.
3. **Identity key lists are frozen per schema version.**
   :data:`CLAIM_IDENTITY_KEYS`, :data:`CONSTRAINT_IDENTITY_KEYS` and
   :data:`IDEMPOTENCY_KEYS` are pinned by golden tests and the schema version
   is deliberately *not* part of any digest. Adding a field therefore cannot
   move an existing id, which is what lets a version-1 receipt and a version-3
   fold agree on which claims are the same claim.
4. **Every record carries its own ``schema_version``.** A receipt states the
   version it was written under; the fold reads it and applies that version's
   defaults. Old receipts are never rewritten in place — re-extraction writes a
   *new* receipt under a new extractor version (plan §1.3, §4.2) and the older
   interpretation stays on disk with its provenance intact.

Controlling contract: the audited final timeline build plan, §4.2 and §5.
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

SYSTEM_DIR = Path(__file__).resolve().parent
if str(SYSTEM_DIR) not in sys.path:
    sys.path.insert(0, str(SYSTEM_DIR))

import chronology as chrono  # noqa: E402

#: Bumped only for a change the additive rule above cannot express.
SCHEMA_VERSION = 1

# --------------------------------------------------------------------------
# The closed vocabularies
# --------------------------------------------------------------------------

#: Where the claim's source came from. ``system_derived`` is the plan's
#: ``system-derived`` spelled the way every other vocabulary in this package
#: spells a two-word token (``chronology.BASES``' ``public_event``).
SOURCE_KINDS = ("conversation", "correction", "import", "system_derived")

#: What the claim asserts. ``identity`` asserts *who* and carries no date;
#: everything else asserts *when* and carries an ``event_kind``.
CLAIM_TYPES = ("date", "range", "age", "duration", "relative_order", "identity")

#: The epistemic class the product surfaces render (plan §5.1, §8.1) — NOT
#: ``chronology.BASES``, which answers how the interval was arrived at.
CLAIM_BASES = ("explicit", "calculated", "inferred")

#: One claim's standing in the fold. A losing claim is never deleted (plan
#: §6.5): it is ``superseded`` by a later claim, ``retracted`` by the person,
#: or left ``disputed`` beside the claim it disagrees with.
CLAIM_STATUSES = ("active", "superseded", "retracted", "disputed")

#: The relations a correction or a relative-order claim can express. This is
#: *placement between nodes* and is a different vocabulary from
#: ``chronology.RELATIONS`` (``before | after | during``), which compares two
#: date records. ``within`` narrows into one period; ``between`` brackets.
CONSTRAINT_RELATIONS = ("before", "after", "between", "within")

#: How many anchors each relation needs. A drag says the weakest truthful
#: thing (plan §2.6), and "the weakest truthful thing" has an arity.
RELATION_ANCHOR_ARITY = {
    "before": (1, 1),
    "after": (1, 1),
    "between": (2, 2),
    "within": (1, 1),
}

#: SEED set, not a closed one — plan §5.1 ends its list with ``...`` and the
#: nine landmark domains (``interactions/landmarks/questions.yaml``) plus §10's
#: required relationship distinctions are what seed it. An unknown kind is
#: accepted when it matches :data:`EVENT_KIND_RE`, because refusing an event
#: the listener genuinely heard would drop the claim, and dropping claims is
#: the defect this whole substrate exists to end. Use :func:`is_seed_event_kind`
#: when a caller wants to know whether it is on the seeded list.
EVENT_KINDS = (
    # birth / losses
    "birth", "death", "loss",
    # partnerships — six records about the same two people, never one
    "met", "dating_started", "engaged", "married", "separated",
    "divorced", "reconciled",
    # schools
    "school", "graduation",
    # residences
    "move",
    # work / military
    "job", "job_ended", "military",
    # children
    "child_born",
)

EVENT_KIND_RE = re.compile(r"^[a-z][a-z0-9_]{1,39}$")

#: ``chronology.BASES`` -> :data:`CLAIM_BASES`. Something the person or a
#: document *stated* is explicit; arithmetic off an anchor is calculated;
#: order-only and a photograph's window are judgements, so they are inferred.
#: ``relative`` is explicit because somebody did state it — that it was a
#: second mouth is carried by the claim's provenance, not by demoting the
#: basis (``chronology`` §6.4).
CLAIM_BASIS_BY_DATE_BASIS = {
    "stated": "explicit",
    "document": "explicit",
    "relative": "explicit",
    "age": "calculated",
    "anchor": "calculated",
    "public_event": "calculated",
    "connector": "calculated",
    "order": "inferred",
    "photo": "inferred",
}

#: A bounded quotation is evidence; an unbounded one is a copy of the source.
MAX_EVIDENCE_QUOTE_CHARS = 300
#: A subject mention longer than this is a sentence, not a subject.
MAX_SUBJECT_MENTION_CHARS = 200
#: Parts of an enumeration are names and short phrases; anything longer means
#: the "and" was grammar rather than a list (see :func:`split_subject_enumeration`).
MAX_ENUMERATION_PART_WORDS = 4

#: Hex characters kept from each identity digest (96 bits).
ID_DIGEST_LENGTH = 24

#: Firestore document ids must not contain ``/`` (platform incident
#: 2026-08-22), so every id this module mints is ``<prefix>:<lowercase hex>``
#: and nothing else. :func:`is_safe_id` is the guard.
ID_RE = re.compile(rf"^[a-z_]+:[0-9a-f]{{{ID_DIGEST_LENGTH}}}$")

CLAIM_ID_PREFIX = "claim"
CONSTRAINT_ID_PREFIX = "constraint"
RECEIPT_ID_PREFIX = "receipt"
IDEMPOTENCY_ID_PREFIX = "idem"

# --------------------------------------------------------------------------
# Where these records live (paths only — the store is wave B's)
# --------------------------------------------------------------------------

#: Plan §4.2's layout, as pure relative POSIX strings. This module performs no
#: file I/O; :func:`receipt_relative_path` exists so the writer, the reader and
#: the platform mirror cannot each invent their own directory.
TEMPORAL_STATE_DIR = "state/temporal_claims"
RECEIPTS_DIR = f"{TEMPORAL_STATE_DIR}/receipts"
ACTIVE_INDEX_FILE = f"{TEMPORAL_STATE_DIR}/active-index.json"
#: Human corrections are durable *source* records, not state (plan §4.2).
CORRECTION_SOURCES_DIR = "sources/corrections"

#: A source key is a filename component, so it is bounded and slug-safe. The
#: budget matches ``source_integrity.MAX_LINKED_SOURCE_FILENAME_BYTES``' intent:
#: stay well inside the most conservative path limit any host imposes.
MAX_SOURCE_KEY_CHARS = 96
SOURCE_KEY_HASH_LENGTH = 12


# --------------------------------------------------------------------------
# Typed errors
# --------------------------------------------------------------------------


class TemporalContractError(ValueError):
    """A temporal record failed its contract, with a named finding.

    ``code`` is a stable finding id so observability can count rejections by
    reason (plan §12) and a host can retry exactly one class.
    """

    def __init__(self, code: str, message: str, *, detail: object = None) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message
        self.detail = detail


class SourceRefError(TemporalContractError):
    """A source reference does not name a vault source and a revision."""


class TemporalClaimError(TemporalContractError):
    """A claim is not one fact, one record, one source."""


class OrderingConstraintError(TemporalContractError):
    """An ordering constraint is malformed or under-anchored."""


class ExtractionReceiptError(TemporalContractError):
    """A receipt does not make its claims traceable."""


#: Every finding id this module can raise, so tests and dashboards enumerate
#: rather than guess.
ERROR_CODES = (
    "source_ref_not_a_mapping",
    "source_ref_missing_source_id",
    "source_ref_missing_revision",
    "source_ref_revision_unrecognized",
    "source_ref_unsafe_component",
    "unknown_source_kind",
    "unknown_claim_type",
    "unknown_claim_basis",
    "unknown_claim_status",
    "unknown_event_kind",
    "unknown_relation",
    "relation_anchor_arity",
    "claim_not_a_mapping",
    "subject_mention_required",
    "subject_mention_too_long",
    "aggregate_subject_mention",
    "identity_claim_carries_no_temporal_value",
    "identity_claim_carries_no_event",
    "temporal_claim_needs_event_kind",
    "temporal_claim_needs_value",
    "temporal_value_unusable",
    "relative_order_needs_relation",
    "ordered_claim_needs_date",
    "evidence_required",
    "evidence_not_a_mapping",
    "evidence_quote_required",
    "evidence_span_reversed",
    "confidence_out_of_range",
    "extractor_version_required",
    "timestamp_unusable",
    "supersedes_self",
    "constraint_not_a_mapping",
    "constraint_needs_subject_node",
    "constraint_anchor_is_subject",
    "receipt_not_a_mapping",
    "receipt_claim_source_mismatch",
    "receipt_claim_extractor_mismatch",
    "receipt_duplicate_claim_id",
)


# --------------------------------------------------------------------------
# Small pure helpers
# --------------------------------------------------------------------------


def collapsed_text(value: object) -> str:
    """Whitespace-collapsed text; ``""`` for anything unusable."""
    if value is None or isinstance(value, (dict, list, tuple, set)):
        return ""
    return " ".join(str(value).split())


def optional_text(value: object) -> str | None:
    """:func:`collapsed_text`, with ``""`` reported as ``None``."""
    cleaned = collapsed_text(value)
    return cleaned or None


#: Internal shorthand. Public names are the contract; these are for reading.
_text = collapsed_text
_opt_text = optional_text


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


_TIMESTAMP_FORMATS = (
    "%Y-%m-%dT%H:%M:%SZ",
    "%Y-%m-%dT%H:%M:%S.%fZ",
    "%Y-%m-%dT%H:%M:%S%z",
    "%Y-%m-%d",
)


def normalized_timestamp(value: object, *, error: type[TemporalContractError]) -> str:
    """One timestamp spelling — ``YYYY-MM-DDTHH:MM:SSZ``, always UTC.

    A blank value takes "now"; an unparseable one is a named failure rather
    than a silently invented time.
    """
    text = _text(value)
    if not text:
        return _utc_now()
    for fmt in _TIMESTAMP_FORMATS:
        try:
            parsed = datetime.strptime(text, fmt)
        except ValueError:
            continue
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    raise error("timestamp_unusable", f"not an ISO-8601 timestamp: {text!r}")


def bounded_quote(text: object, *, limit: int = MAX_EVIDENCE_QUOTE_CHARS) -> str:
    """A quotation cut to ``limit`` characters **at a word boundary**.

    Evidence is a bounded quotation, not a copy of the source (plan §4.2), and
    a cut mid-word is a misquotation, so the cut lands on whitespace and marks
    itself with an ellipsis.
    """
    cleaned = _text(text)
    if len(cleaned) <= limit:
        return cleaned
    head = cleaned[: max(1, limit - 1)]
    cut = head.rfind(" ")
    if cut > 0:
        head = head[:cut]
    return head.rstrip(" ,;:-") + "…"


_ENUMERATION_SPLIT_RE = re.compile(
    r"\s*,\s*(?:and\s+|&\s+|or\s+)?|\s+and\s+|\s+&\s+", re.IGNORECASE
)


def split_subject_enumeration(text: object) -> tuple[str, ...]:
    """``"Ada, Bo, Cy, and Della"`` -> four parts; anything else -> one part.

    The founder shape the plan names by hand — *"I have four children: Ada, Bo,
    Cy, and Della"* — must become four person records and never one aggregate
    pseudo-person (plan §5.1, §10). This is the deterministic decision about
    what "four" means, used both by :func:`validate_temporal_claim` (to refuse
    the aggregate) and by callers (to mint the four).

    A lead-in clause is dropped at the last colon, so the whole sentence and
    just the list behave the same. A split is only believed when every part is
    a name-sized phrase (``MAX_ENUMERATION_PART_WORDS`` words or fewer);
    otherwise the "and" was grammar — *"the summer after we moved and settled
    in"* is one mention — and the original comes back whole.

    Known and accepted: a single subject whose own name contains "and" splits.
    The subject slot names one subject; a wedding, a shop or a band with a
    conjunction in its name belongs in the event or the resolved ref, and the
    plan's cardinality defect is worth that trade.
    """
    cleaned = _text(text)
    if not cleaned:
        return ()
    tail = cleaned.rsplit(":", 1)[-1].strip() if ":" in cleaned else cleaned
    if not tail:
        tail = cleaned
    parts = [part.strip(" ,;") for part in _ENUMERATION_SPLIT_RE.split(tail)]
    parts = [part for part in parts if part]
    if len(parts) < 2:
        return (cleaned,)
    if any(len(part.split()) > MAX_ENUMERATION_PART_WORDS for part in parts):
        return (cleaned,)
    return tuple(parts)


def is_seed_event_kind(value: object) -> bool:
    """Is this one of the seeded :data:`EVENT_KINDS`?"""
    return _text(value) in EVENT_KINDS


def claim_basis_for_date_basis(basis: object) -> str:
    """``chronology`` basis -> :data:`CLAIM_BASES`; unknown -> ``"inferred"``.

    Unknown degrades to the *weakest* class on purpose: an unrecognized basis
    must never be rendered as something the person said.
    """
    return CLAIM_BASIS_BY_DATE_BASIS.get(_text(basis), "inferred")


def is_safe_id(value: object) -> bool:
    """Does this look like an id this module minted, with no path separator?"""
    return bool(ID_RE.fullmatch(_text(value)))


def digest_id(prefix: str, payload: object) -> str:
    """``<prefix>:<24 hex>`` over canonical JSON — the ONE id derivation.

    Every identity in the temporal substrate is minted here so that "same
    payload, same id" is a property of one function rather than a convention
    four modules are each trusted to follow. The JSON is canonical (sorted
    keys, no whitespace) so key order and formatting cannot move an id.
    """
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return f"{prefix}:{hashlib.sha256(blob.encode('utf-8')).hexdigest()[:ID_DIGEST_LENGTH]}"


def normalized_mention_key(text: object) -> str:
    """The identity form of a raw mention: collapsed, casefolded, unpunctuated.

    ``"Aunt  Della"``, ``"aunt della"`` and ``"Aunt Della."`` are one subject
    said three ways; identity should not fork on typography.
    """
    cleaned = collapsed_text(text).casefold()
    return " ".join(re.sub(r"[^\w\s]", " ", cleaned, flags=re.UNICODE).split())


_digest = digest_id
_normalized_mention_key = normalized_mention_key


# --------------------------------------------------------------------------
# SourceRef — a vault source and an immutable revision, universally
# --------------------------------------------------------------------------

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_GIT_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_PREFIXED_REVISION_RE = re.compile(r"^(?:sha256:[0-9a-f]{64}|git:[0-9a-f]{40})$")


@dataclass(frozen=True)
class SourceRef:
    """The vault source a claim interprets, pinned to one immutable revision.

    Owner amendment Q2/option B (2026-08-26): claims cite vault sources
    **universally**. A conversational message that produces a claim is promoted
    to a vault source record first, so there is no claim whose only citation is
    a session row. ``turn_ref`` on the claim's :class:`EvidenceSpan` records
    which turn carried the sentence; it does not substitute for the source.
    """

    source_id: str
    revision: str
    source_path: str | None = None

    def to_dict(self) -> dict:
        payload: dict = {"source_id": self.source_id, "revision": self.revision}
        if self.source_path:
            payload["source_path"] = self.source_path
        return payload

    @property
    def key(self) -> str:
        """``"<source_id>@<revision>"`` — the identity form used in digests."""
        return f"{self.source_id}@{self.revision}"


def normalized_revision(value: object) -> str | None:
    """One revision spelling. ``None`` when the value names no revision.

    Accepts ``sha256:<64 hex>``, ``git:<40 hex>``, a bare 64-hex content digest
    (normalized to ``sha256:``) and a bare 40-hex git object id (normalized to
    ``git:``). Both forms exist in this repo already — sources carry
    ``content_sha256``, ``exact_file_git`` carries commit ids — and a claim may
    cite either, but it may not cite "latest".
    """
    text = _text(value).lower()
    if not text:
        return None
    if _PREFIXED_REVISION_RE.fullmatch(text):
        return text
    if _SHA256_RE.fullmatch(text):
        return f"sha256:{text}"
    if _GIT_SHA_RE.fullmatch(text):
        return f"git:{text}"
    return None


def validate_source_ref(value: object) -> dict:
    """Normalize a source reference or raise :class:`SourceRefError`."""
    if isinstance(value, SourceRef):
        value = value.to_dict()
    if isinstance(value, str):
        # "<source_id>@<revision>" — the key form round-trips.
        head, _, tail = value.rpartition("@")
        value = {"source_id": head, "revision": tail}
    if not isinstance(value, dict):
        raise SourceRefError("source_ref_not_a_mapping", "source_ref must be a mapping")
    source_id = _text(value.get("source_id"))
    if not source_id:
        raise SourceRefError(
            "source_ref_missing_source_id",
            "every claim cites a vault source (owner amendment Q2/option B)",
        )
    if "\n" in source_id or "@" in source_id:
        raise SourceRefError(
            "source_ref_unsafe_component", f"source_id is malformed: {source_id!r}"
        )
    raw_revision = value.get("revision")
    if not _text(raw_revision):
        raise SourceRefError(
            "source_ref_missing_revision",
            f"source {source_id} is cited without an immutable revision",
        )
    revision = normalized_revision(raw_revision)
    if revision is None:
        raise SourceRefError(
            "source_ref_revision_unrecognized",
            f"revision must be sha256:<64 hex> or git:<40 hex>, got {raw_revision!r}",
        )
    normalized: dict = {"source_id": source_id, "revision": revision}
    source_path = _opt_text(value.get("source_path"))
    if source_path:
        normalized["source_path"] = source_path
    return normalized


def source_ref_from_dict(value: object) -> SourceRef | None:
    """Tolerant reader — ``None`` rather than an exception (compat rule 2)."""
    try:
        normalized = validate_source_ref(value)
    except TemporalContractError:
        return None
    return SourceRef(
        source_id=normalized["source_id"],
        revision=normalized["revision"],
        source_path=normalized.get("source_path"),
    )


def bounded_source_key(source_id: object) -> str:
    """A filename-safe, bounded key for a source id (plan §4.2's layout).

    Long or exotic source ids are slugged and, when the slug would overflow
    :data:`MAX_SOURCE_KEY_CHARS` or lose information, suffixed with a digest of
    the original so two different sources can never share a key.
    """
    text = _text(source_id)
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", text).strip("-").lower() or "source"
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()[:SOURCE_KEY_HASH_LENGTH]
    if slug == text.lower() and len(slug) <= MAX_SOURCE_KEY_CHARS:
        return slug
    budget = MAX_SOURCE_KEY_CHARS - SOURCE_KEY_HASH_LENGTH - 1
    return f"{slug[:budget].strip('-')}-{digest}"


def receipt_relative_path(source_ref: object, extractor_version: object) -> str:
    """``state/temporal_claims/receipts/<key>/<revision>/<extractor>.json``.

    Pure string derivation of plan §4.2's layout. Re-extraction by a *new*
    extractor lands on a new path, which is the mechanism behind "re-extraction
    writes a new receipt; it does not silently overwrite the prior
    interpretation".
    """
    normalized = validate_source_ref(source_ref)
    extractor = _text(extractor_version)
    if not extractor:
        raise ExtractionReceiptError(
            "extractor_version_required", "a receipt names the extractor that wrote it"
        )
    key = bounded_source_key(normalized["source_id"])
    revision = normalized["revision"].replace(":", "-")
    return f"{RECEIPTS_DIR}/{key}/{revision}/{bounded_source_key(extractor)}.json"


def extractor_version_string(
    name: object,
    *,
    schema_version: object = None,
    prompt_version: object = None,
    model: object = None,
    rule_version: object = None,
) -> str:
    """One canonical spelling of "which extractor produced this".

    ``extractor_version_string("listener", schema_version=1, prompt_version="a1b2",
    model="claude-opus-4")`` -> ``"listener/schema:1/prompt:a1b2/model:claude-opus-4"``.
    A deterministic rule extractor uses ``rule_version`` and names no model:
    ``"prescreen/rule:3"``. Absent parts are omitted, and the order is fixed so
    the string is comparable and sortable.

    Both the claim's ``extractor_version`` and the receipt's structured
    ``extractor`` block render through this one function — the plan requires
    model and deterministic versions to be told apart (§11, §15) and two
    spellings of the same extractor would defeat that.
    """
    label = re.sub(r"[^A-Za-z0-9._-]+", "-", _text(name)).strip("-")
    if not label:
        raise ExtractionReceiptError(
            "extractor_version_required", "an extractor version needs a name"
        )
    parts = [label]
    for key, value in (
        ("schema", schema_version),
        ("prompt", prompt_version),
        ("model", model),
        ("rule", rule_version),
    ):
        cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", _text(value)).strip("-")
        if cleaned:
            parts.append(f"{key}:{cleaned}")
    return "/".join(parts)


# --------------------------------------------------------------------------
# Evidence
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class EvidenceSpan:
    """What in the source says this, bounded so it is evidence and not a copy.

    ``turn_ref`` names the operational conversation turn that carried the
    sentence — connective transcript is the session store's authority (plan
    §4.1), and recording the pointer here is how a claim stays explainable
    without the claim depending on that store.
    """

    quote: str
    start: int | None = None
    end: int | None = None
    turn_ref: str | None = None
    session_ref: str | None = None

    def to_dict(self) -> dict:
        payload: dict = {"quote": self.quote}
        for key, value in (
            ("start", self.start),
            ("end", self.end),
            ("turn_ref", self.turn_ref),
            ("session_ref", self.session_ref),
        ):
            if value is not None:
                payload[key] = value
        return payload


def validate_evidence_span(value: object) -> dict:
    """Normalize one evidence span or raise :class:`TemporalClaimError`."""
    if isinstance(value, EvidenceSpan):
        value = value.to_dict()
    if isinstance(value, str):
        value = {"quote": value}
    if not isinstance(value, dict):
        raise TemporalClaimError("evidence_not_a_mapping", "evidence must be a mapping")
    quote = bounded_quote(value.get("quote"))
    if not quote:
        raise TemporalClaimError(
            "evidence_quote_required", "evidence carries a bounded quotation"
        )
    normalized: dict = {"quote": quote}
    start = _as_offset(value.get("start"))
    end = _as_offset(value.get("end"))
    if start is not None and end is not None and end <= start:
        raise TemporalClaimError(
            "evidence_span_reversed", f"evidence span {start}..{end} is not forward"
        )
    if start is not None:
        normalized["start"] = start
    if end is not None:
        normalized["end"] = end
    for key in ("turn_ref", "session_ref"):
        cleaned = _opt_text(value.get(key))
        if cleaned:
            normalized[key] = cleaned
    return normalized


def _as_offset(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        return None
    try:
        offset = int(value)
    except (TypeError, ValueError):
        return None
    return offset if offset >= 0 else None


def evidence_from_dict(value: object) -> EvidenceSpan | None:
    try:
        normalized = validate_evidence_span(value)
    except TemporalContractError:
        return None
    return EvidenceSpan(
        quote=normalized["quote"],
        start=normalized.get("start"),
        end=normalized.get("end"),
        turn_ref=normalized.get("turn_ref"),
        session_ref=normalized.get("session_ref"),
    )


# --------------------------------------------------------------------------
# OrderingRelation — order without inventing precision
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class OrderingRelation:
    """"After the move", with the anchors it is relative to and nothing more.

    Two bindings of one vocabulary (ADR 0021's one-definition rule): a *claim*
    carries this with anchors that may still be raw mentions ("we moved"), and
    an :class:`OrderingConstraint` carries it with resolved node ids. Neither
    may invent a date to express order (plan §2.6).
    """

    relation: str
    anchors: tuple[str, ...] = ()

    def to_dict(self) -> dict:
        return {"relation": self.relation, "anchors": list(self.anchors)}


def validate_ordering_relation(
    value: object, *, error: type[TemporalContractError] = TemporalClaimError
) -> dict:
    """Normalize a relation and enforce :data:`RELATION_ANCHOR_ARITY`."""
    if isinstance(value, OrderingRelation):
        value = value.to_dict()
    if not isinstance(value, dict):
        raise error("relative_order_needs_relation", "an ordering relation must be a mapping")
    relation = _text(value.get("relation")).lower()
    if relation not in CONSTRAINT_RELATIONS:
        raise error("unknown_relation", f"unknown relation: {relation!r}")
    raw = value.get("anchors")
    if isinstance(raw, (str, bytes)):
        raw = [raw]
    anchors = tuple(dict.fromkeys(_text(a) for a in (raw or ()) if _text(a)))
    low, high = RELATION_ANCHOR_ARITY[relation]
    if not low <= len(anchors) <= high:
        raise error(
            "relation_anchor_arity",
            f"{relation} needs {low}..{high} anchors, got {len(anchors)}",
            detail=anchors,
        )
    return {"relation": relation, "anchors": list(anchors)}


def ordering_relation_from_dict(value: object) -> OrderingRelation | None:
    try:
        normalized = validate_ordering_relation(value)
    except TemporalContractError:
        return None
    return OrderingRelation(
        relation=normalized["relation"], anchors=tuple(normalized["anchors"])
    )


# --------------------------------------------------------------------------
# The temporal value: a date record or an ordering relation
# --------------------------------------------------------------------------

#: Claim types whose ``temporal_value`` is a :class:`chronology.DateRecord`.
DATED_CLAIM_TYPES = ("date", "range", "age", "duration")


def normalized_temporal_value(value: object, *, claim_type: str) -> object:
    """The claim's value in its one legal shape for that claim type.

    ``date | range | age | duration`` normalize through ``chronology`` — there
    is one date definition in this package and this module does not add a
    second parser. ``relative_order`` normalizes through
    :func:`validate_ordering_relation`. ``identity`` carries no value at all.
    """
    if claim_type == "identity":
        if value is not None:
            raise TemporalClaimError(
                "identity_claim_carries_no_temporal_value",
                "an identity claim asserts who, not when",
            )
        return None
    if claim_type == "relative_order":
        return validate_ordering_relation(value)
    record = chrono.from_dict(value)
    if record is None and isinstance(value, str):
        record = chrono.parse_edtf(value)
    if record is None:
        raise TemporalClaimError(
            "temporal_value_unusable",
            f"{claim_type} claim needs a chronology date record, got {value!r}",
        )
    return chrono.normalized_date(record) or record.to_dict()


def _temporal_identity(value: object) -> object:
    """The part of a temporal value that decides *which* claim this is.

    Provenance, anchors and the confidence word are annotation: two extractions
    of the same sentence that differ only in how much provenance they attached
    are the same claim, so identity reduces a date record to its interval.
    """
    if value is None:
        return None
    if isinstance(value, dict) and "relation" in value:
        return {
            "kind": "order",
            "relation": value.get("relation"),
            "anchors": sorted(_normalized_mention_key(a) for a in value.get("anchors") or ()),
        }
    record = chrono.from_dict(value)
    if record is None:
        return {"kind": "opaque", "value": _text(value)}
    return {
        "kind": "date",
        "edtf": chrono.to_edtf(record),
        "earliest": record.earliest,
        "latest": record.latest,
        "granularity": record.granularity,
    }


# --------------------------------------------------------------------------
# TemporalClaim
# --------------------------------------------------------------------------

#: FROZEN for schema version 1 (compatibility rule 3). Adding a field to the
#: claim must not move an existing claim id, so nothing joins this list without
#: a schema version bump and a documented re-identification.
CLAIM_IDENTITY_KEYS = (
    "claim_type",
    "subject_key",
    "event_kind",
    "temporal_identity",
    "source_ref",
    "extractor_version",
)


@dataclass(frozen=True)
class TemporalClaim:
    """One interpretation of one source about one subject's one event.

    Fields are plan §5.1's list. ``subject_resolution`` is the reversibility
    record §6.3 requires — the candidate set and the reason an alias resolved —
    and is annotation, never identity.
    """

    claim_id: str
    source_ref: SourceRef
    source_kind: str
    claim_type: str
    subject_mention: str
    temporal_value: object = None
    subject_ref: str | None = None
    event_ref: str | None = None
    event_kind: str | None = None
    evidence: tuple[EvidenceSpan, ...] = ()
    basis: str = "inferred"
    confidence: float = 0.0
    status: str = "active"
    extractor_version: str = ""
    created_at: str = ""
    supersedes_claim_ids: tuple[str, ...] = ()
    subject_resolution: dict | None = None
    schema_version: int = SCHEMA_VERSION

    def to_dict(self) -> dict:
        payload: dict = {
            "claim_id": self.claim_id,
            "schema_version": self.schema_version,
            "source_ref": self.source_ref.to_dict(),
            "source_kind": self.source_kind,
            "claim_type": self.claim_type,
            "subject_mention": self.subject_mention,
            "temporal_value": self.temporal_value,
            "evidence": [span.to_dict() for span in self.evidence],
            "basis": self.basis,
            "confidence": self.confidence,
            "status": self.status,
            "extractor_version": self.extractor_version,
            "created_at": self.created_at,
            "supersedes_claim_ids": list(self.supersedes_claim_ids),
        }
        for key, value in (
            ("subject_ref", self.subject_ref),
            ("event_ref", self.event_ref),
            ("event_kind", self.event_kind),
            ("subject_resolution", self.subject_resolution),
        ):
            if value is not None:
                payload[key] = value
        return payload


def claim_identity_payload(
    *,
    claim_type: str,
    subject_mention: object,
    event_kind: object,
    temporal_value: object,
    source_ref: object,
    extractor_version: object,
) -> dict:
    """The exact digest input behind :func:`derive_claim_id`, exposed so a test
    can pin it and a debugging human can see why two claims collided."""
    ref = source_ref if isinstance(source_ref, dict) else validate_source_ref(source_ref)
    payload = {
        "claim_type": _text(claim_type),
        "subject_key": _normalized_mention_key(subject_mention),
        "event_kind": _text(event_kind) or None,
        "temporal_identity": _temporal_identity(temporal_value),
        "source_ref": f"{ref['source_id']}@{ref['revision']}",
        "extractor_version": _text(extractor_version),
    }
    return {key: payload[key] for key in CLAIM_IDENTITY_KEYS}


def derive_claim_id(
    *,
    claim_type: str,
    subject_mention: object,
    event_kind: object,
    temporal_value: object,
    source_ref: object,
    extractor_version: object,
) -> str:
    """``claim:<24 hex>`` — stable, idempotency-bound (plan §5.1, §6.1).

    Same source revision + same extractor + same asserted fact = same id, so a
    retried or replayed extraction files nothing twice. Deliberately *not* in
    the digest: ``created_at`` (a retry is later), ``confidence`` and ``status``
    (they change without the fact changing), ``evidence`` (the same fact said
    twice in one source is one claim), and ``subject_ref``/``event_ref``
    (resolution happens after the claim exists and must not re-mint it).
    """
    return _digest(
        CLAIM_ID_PREFIX,
        claim_identity_payload(
            claim_type=claim_type,
            subject_mention=subject_mention,
            event_kind=event_kind,
            temporal_value=temporal_value,
            source_ref=source_ref,
            extractor_version=extractor_version,
        ),
    )


def validate_temporal_claim(value: object, *, now: object = None) -> dict:
    """Normalize a claim or raise :class:`TemporalClaimError`.

    This is the door. It enforces plan §5.1's rules as rules rather than as
    prose:

    * the raw ``subject_mention`` is required and survives resolution;
    * an enumerated mention is refused by name, with the parts in the error, so
      *"Ada, Bo, Cy, and Della"* becomes four claims and never one;
    * ``identity`` claims carry no date and no event; every dated claim carries
      an ``event_kind``, because a date is the date of an event and never of a
      person;
    * evidence is required and bounded;
    * ``claim_id`` is derived, and a supplied id that disagrees with the
      derivation is replaced (the derivation is the authority).
    """
    if isinstance(value, TemporalClaim):
        value = value.to_dict()
    if not isinstance(value, dict):
        raise TemporalClaimError("claim_not_a_mapping", "a claim must be a mapping")

    claim_type = _text(value.get("claim_type"))
    if claim_type not in CLAIM_TYPES:
        raise TemporalClaimError("unknown_claim_type", f"unknown claim_type: {claim_type!r}")

    source_kind = _text(value.get("source_kind"))
    if source_kind not in SOURCE_KINDS:
        raise TemporalClaimError("unknown_source_kind", f"unknown source_kind: {source_kind!r}")

    source_ref = validate_source_ref(value.get("source_ref"))

    subject_mention = _text(value.get("subject_mention"))
    if not subject_mention:
        raise TemporalClaimError(
            "subject_mention_required",
            "the raw mention is retained even when subject_ref resolves",
        )
    if len(subject_mention) > MAX_SUBJECT_MENTION_CHARS:
        raise TemporalClaimError(
            "subject_mention_too_long",
            f"subject_mention is {len(subject_mention)} chars; a subject is not a sentence",
        )
    parts = split_subject_enumeration(subject_mention)
    if len(parts) > 1:
        raise TemporalClaimError(
            "aggregate_subject_mention",
            f"{subject_mention!r} names {len(parts)} subjects; emit one claim each",
            detail=parts,
        )

    event_kind = _opt_text(value.get("event_kind"))
    event_ref = _opt_text(value.get("event_ref"))
    if claim_type == "identity":
        if event_kind or event_ref:
            raise TemporalClaimError(
                "identity_claim_carries_no_event",
                "person identity and event transitions are distinct records",
            )
    else:
        if not event_kind:
            raise TemporalClaimError(
                "temporal_claim_needs_event_kind",
                "a date is the date of an event, never of a person",
            )
        if not EVENT_KIND_RE.fullmatch(event_kind):
            raise TemporalClaimError(
                "unknown_event_kind",
                f"event_kind must be a lowercase token, got {event_kind!r}",
            )
        if value.get("temporal_value") is None:
            raise TemporalClaimError(
                "temporal_claim_needs_value", f"a {claim_type} claim needs a temporal_value"
            )

    temporal_value = normalized_temporal_value(
        value.get("temporal_value"), claim_type=claim_type
    )
    if claim_type == "relative_order" and not isinstance(temporal_value, dict):
        raise TemporalClaimError(
            "relative_order_needs_relation", "a relative_order claim carries a relation"
        )
    if claim_type in DATED_CLAIM_TYPES and not isinstance(temporal_value, dict):
        raise TemporalClaimError("ordered_claim_needs_date", f"a {claim_type} claim needs a date")

    raw_evidence = value.get("evidence")
    if isinstance(raw_evidence, (str, dict, EvidenceSpan)):
        raw_evidence = [raw_evidence]
    evidence = [validate_evidence_span(span) for span in (raw_evidence or ())]
    if not evidence:
        raise TemporalClaimError(
            "evidence_required", "a claim is traceable to its source or it is not a claim"
        )

    basis = _text(value.get("basis")) or "inferred"
    if basis not in CLAIM_BASES:
        raise TemporalClaimError("unknown_claim_basis", f"unknown basis: {basis!r}")

    status = _text(value.get("status")) or "active"
    if status not in CLAIM_STATUSES:
        raise TemporalClaimError("unknown_claim_status", f"unknown status: {status!r}")

    confidence = _as_unit_float(value.get("confidence"), error=TemporalClaimError)

    extractor_version = _text(value.get("extractor_version"))
    if not extractor_version:
        raise TemporalClaimError(
            "extractor_version_required",
            "a claim names the extractor version that produced it",
        )

    created_at = normalized_timestamp(
        value.get("created_at") or now, error=TemporalClaimError
    )

    claim_id = derive_claim_id(
        claim_type=claim_type,
        subject_mention=subject_mention,
        event_kind=event_kind,
        temporal_value=temporal_value,
        source_ref=source_ref,
        extractor_version=extractor_version,
    )

    raw_supersedes = value.get("supersedes_claim_ids")
    if isinstance(raw_supersedes, str):
        raw_supersedes = [raw_supersedes]
    supersedes = tuple(dict.fromkeys(_text(c) for c in (raw_supersedes or ()) if _text(c)))
    if claim_id in supersedes:
        raise TemporalClaimError(
            "supersedes_self", f"{claim_id} cannot supersede itself"
        )

    normalized: dict = {
        "claim_id": claim_id,
        "schema_version": SCHEMA_VERSION,
        "source_ref": source_ref,
        "source_kind": source_kind,
        "claim_type": claim_type,
        "subject_mention": subject_mention,
        "temporal_value": temporal_value,
        "evidence": evidence,
        "basis": basis,
        "confidence": confidence,
        "status": status,
        "extractor_version": extractor_version,
        "created_at": created_at,
        "supersedes_claim_ids": list(supersedes),
    }
    subject_ref = _opt_text(value.get("subject_ref"))
    if subject_ref:
        normalized["subject_ref"] = subject_ref
    if event_ref:
        normalized["event_ref"] = event_ref
    if event_kind:
        normalized["event_kind"] = event_kind
    resolution = value.get("subject_resolution")
    if isinstance(resolution, dict) and resolution:
        normalized["subject_resolution"] = _normalized_resolution(resolution)
    return normalized


def _normalized_resolution(value: dict) -> dict:
    """§6.3's reversibility record: candidates, reason, confidence."""
    normalized: dict = {}
    candidates = value.get("candidates")
    if isinstance(candidates, (str, bytes)):
        candidates = [candidates]
    cleaned = [_text(c) for c in (candidates or ()) if _text(c)]
    if cleaned:
        normalized["candidates"] = cleaned
    reason = _opt_text(value.get("reason"))
    if reason:
        normalized["reason"] = reason
    if value.get("confidence") is not None:
        normalized["confidence"] = _as_unit_float(
            value.get("confidence"), error=TemporalClaimError
        )
    return normalized


def unit_score(value: object, *, error: type[TemporalContractError]) -> float:
    """Calibrated support in ``0.0..1.0``; never a substitute for provenance."""
    if value is None or value == "":
        return 0.0
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        raise error("confidence_out_of_range", f"not a number: {value!r}") from None
    if not 0.0 <= number <= 1.0:
        raise error("confidence_out_of_range", f"confidence must be 0..1, got {number}")
    return round(number, 4)


_as_unit_float = unit_score


def claim_from_dict(value: object) -> TemporalClaim | None:
    """Tolerant reader — ``None`` rather than an exception (compat rule 2)."""
    try:
        normalized = validate_temporal_claim(value)
    except TemporalContractError:
        return None
    return TemporalClaim(
        claim_id=normalized["claim_id"],
        source_ref=SourceRef(
            source_id=normalized["source_ref"]["source_id"],
            revision=normalized["source_ref"]["revision"],
            source_path=normalized["source_ref"].get("source_path"),
        ),
        source_kind=normalized["source_kind"],
        claim_type=normalized["claim_type"],
        subject_mention=normalized["subject_mention"],
        temporal_value=normalized["temporal_value"],
        subject_ref=normalized.get("subject_ref"),
        event_ref=normalized.get("event_ref"),
        event_kind=normalized.get("event_kind"),
        evidence=tuple(
            EvidenceSpan(
                quote=span["quote"],
                start=span.get("start"),
                end=span.get("end"),
                turn_ref=span.get("turn_ref"),
                session_ref=span.get("session_ref"),
            )
            for span in normalized["evidence"]
        ),
        basis=normalized["basis"],
        confidence=normalized["confidence"],
        status=normalized["status"],
        extractor_version=normalized["extractor_version"],
        created_at=normalized["created_at"],
        supersedes_claim_ids=tuple(normalized["supersedes_claim_ids"]),
        subject_resolution=normalized.get("subject_resolution"),
        schema_version=int(normalized.get("schema_version") or SCHEMA_VERSION),
    )


# --------------------------------------------------------------------------
# OrderingConstraint — what a drag writes
# --------------------------------------------------------------------------

#: FROZEN for schema version 1 (compatibility rule 3).
CONSTRAINT_IDENTITY_KEYS = ("relation", "subject_node_id", "anchor_node_ids", "source_ref")


@dataclass(frozen=True)
class OrderingConstraint:
    """A move, said as the weakest truthful thing (plan §2.6, §5.2).

    Dragging College after High School says *only* that College is after High
    School. No pixel coordinate, no array index, no fabricated exact date ever
    reaches storage through this record.
    """

    constraint_id: str
    relation: str
    subject_node_id: str
    anchor_node_ids: tuple[str, ...]
    source_ref: SourceRef
    evidence: tuple[EvidenceSpan, ...] = ()
    status: str = "active"
    created_at: str = ""
    supersedes_constraint_id: str | None = None
    schema_version: int = SCHEMA_VERSION

    def to_dict(self) -> dict:
        payload: dict = {
            "constraint_id": self.constraint_id,
            "schema_version": self.schema_version,
            "relation": self.relation,
            "subject_node_id": self.subject_node_id,
            "anchor_node_ids": list(self.anchor_node_ids),
            "source_ref": self.source_ref.to_dict(),
            "evidence": [span.to_dict() for span in self.evidence],
            "status": self.status,
            "created_at": self.created_at,
        }
        if self.supersedes_constraint_id:
            payload["supersedes_constraint_id"] = self.supersedes_constraint_id
        return payload


def derive_constraint_id(
    *, relation: object, subject_node_id: object, anchor_node_ids: object, source_ref: object
) -> str:
    """``constraint:<24 hex>`` — the same drag twice is one constraint.

    A retried move (a flaky network, a double tap, an optimistic client that
    resends) must not stack duplicate constraints, so identity is the gesture's
    meaning plus the correction source it was written against.
    """
    ref = source_ref if isinstance(source_ref, dict) else validate_source_ref(source_ref)
    anchors = anchor_node_ids
    if isinstance(anchors, (str, bytes)):
        anchors = [anchors]
    payload = {
        "relation": _text(relation).lower(),
        "subject_node_id": _text(subject_node_id),
        "anchor_node_ids": sorted(_text(a) for a in (anchors or ()) if _text(a)),
        "source_ref": f"{ref['source_id']}@{ref['revision']}",
    }
    return _digest(CONSTRAINT_ID_PREFIX, {k: payload[k] for k in CONSTRAINT_IDENTITY_KEYS})


def validate_ordering_constraint(value: object, *, now: object = None) -> dict:
    """Normalize a constraint or raise :class:`OrderingConstraintError`."""
    if isinstance(value, OrderingConstraint):
        value = value.to_dict()
    if not isinstance(value, dict):
        raise OrderingConstraintError(
            "constraint_not_a_mapping", "a constraint must be a mapping"
        )
    subject_node_id = _text(value.get("subject_node_id"))
    if not subject_node_id:
        raise OrderingConstraintError(
            "constraint_needs_subject_node", "a constraint moves a named node"
        )
    relation = validate_ordering_relation(
        {"relation": value.get("relation"), "anchors": value.get("anchor_node_ids")},
        error=OrderingConstraintError,
    )
    if subject_node_id in relation["anchors"]:
        raise OrderingConstraintError(
            "constraint_anchor_is_subject",
            f"{subject_node_id} cannot be its own anchor",
        )
    source_ref = validate_source_ref(value.get("source_ref"))

    raw_evidence = value.get("evidence")
    if isinstance(raw_evidence, (str, dict, EvidenceSpan)):
        raw_evidence = [raw_evidence]
    evidence = [validate_evidence_span(span) for span in (raw_evidence or ())]

    status = _text(value.get("status")) or "active"
    if status not in CLAIM_STATUSES:
        raise OrderingConstraintError("unknown_claim_status", f"unknown status: {status!r}")

    constraint_id = derive_constraint_id(
        relation=relation["relation"],
        subject_node_id=subject_node_id,
        anchor_node_ids=relation["anchors"],
        source_ref=source_ref,
    )
    normalized: dict = {
        "constraint_id": constraint_id,
        "schema_version": SCHEMA_VERSION,
        "relation": relation["relation"],
        "subject_node_id": subject_node_id,
        "anchor_node_ids": relation["anchors"],
        "source_ref": source_ref,
        "evidence": evidence,
        "status": status,
        "created_at": normalized_timestamp(
            value.get("created_at") or now, error=OrderingConstraintError
        ),
    }
    supersedes = _opt_text(value.get("supersedes_constraint_id"))
    if supersedes:
        normalized["supersedes_constraint_id"] = supersedes
    return normalized


def constraint_from_dict(value: object) -> OrderingConstraint | None:
    """Tolerant reader — ``None`` rather than an exception (compat rule 2)."""
    try:
        normalized = validate_ordering_constraint(value)
    except TemporalContractError:
        return None
    return OrderingConstraint(
        constraint_id=normalized["constraint_id"],
        relation=normalized["relation"],
        subject_node_id=normalized["subject_node_id"],
        anchor_node_ids=tuple(normalized["anchor_node_ids"]),
        source_ref=SourceRef(
            source_id=normalized["source_ref"]["source_id"],
            revision=normalized["source_ref"]["revision"],
            source_path=normalized["source_ref"].get("source_path"),
        ),
        evidence=tuple(
            EvidenceSpan(
                quote=span["quote"],
                start=span.get("start"),
                end=span.get("end"),
                turn_ref=span.get("turn_ref"),
                session_ref=span.get("session_ref"),
            )
            for span in normalized["evidence"]
        ),
        status=normalized["status"],
        created_at=normalized["created_at"],
        supersedes_constraint_id=normalized.get("supersedes_constraint_id"),
        schema_version=int(normalized.get("schema_version") or SCHEMA_VERSION),
    )


# --------------------------------------------------------------------------
# ExtractionReceipt — the immutable interpretation record
# --------------------------------------------------------------------------

#: FROZEN for schema version 1 (compatibility rule 3). The idempotency key ties
#: session, turn, source revision, recorder and extraction version together
#: (plan §6.1), which is what makes a retry a no-op rather than a duplicate.
IDEMPOTENCY_KEYS = (
    "session_ref",
    "turn_ref",
    "source_ref",
    "recorder",
    "extractor_version",
)


def derive_extraction_idempotency_key(
    *,
    session_ref: object,
    turn_ref: object,
    source_ref: object,
    recorder: object,
    extractor_version: object,
) -> str:
    """``idem:<24 hex>`` — plan §6.1's key, in one place.

    Retries must not create duplicate claims, people, events, questions or
    corrections. Every writer on the capture path derives its key here so the
    focused recorder and the general listener cannot disagree about whether two
    attempts are the same attempt.
    """
    ref = source_ref if isinstance(source_ref, dict) else validate_source_ref(source_ref)
    payload = {
        "session_ref": _text(session_ref) or None,
        "turn_ref": _text(turn_ref) or None,
        "source_ref": f"{ref['source_id']}@{ref['revision']}",
        "recorder": _text(recorder) or None,
        "extractor_version": _text(extractor_version),
    }
    return _digest(IDEMPOTENCY_ID_PREFIX, {key: payload[key] for key in IDEMPOTENCY_KEYS})


@dataclass(frozen=True)
class ExtractionReceipt:
    """One model (or rule) pass over one source revision, kept forever.

    Plan §4.2's invariants live in this shape: the receipt identifies the source
    revision, the extractor's prompt/schema/model version, the creation time and
    every emitted claim, each with its bounded evidence. Re-extraction writes a
    *new* receipt at a new path (:func:`receipt_relative_path`) — the earlier
    interpretation is never overwritten, because a later model reading the same
    prose is a new interpretation and not a cache rebuild (plan §1.3).

    Deleting the active index and rebuilding the deterministic fold from the
    checked-in receipts must reproduce the same claims with no model call; that
    fold is wave B's, and this module writes no files.
    """

    receipt_id: str
    source_ref: SourceRef
    extractor_version: str
    created_at: str
    claims: tuple[TemporalClaim, ...] = ()
    extractor: dict = field(default_factory=dict)
    recorder: str | None = None
    idempotency_key: str | None = None
    schema_version: int = SCHEMA_VERSION

    def to_dict(self) -> dict:
        payload: dict = {
            "receipt_id": self.receipt_id,
            "schema_version": self.schema_version,
            "source_ref": self.source_ref.to_dict(),
            "extractor_version": self.extractor_version,
            "extractor": dict(self.extractor),
            "created_at": self.created_at,
            "claims": [claim.to_dict() for claim in self.claims],
        }
        for key, value in (
            ("recorder", self.recorder),
            ("idempotency_key", self.idempotency_key),
        ):
            if value is not None:
                payload[key] = value
        return payload

    @property
    def relative_path(self) -> str:
        return receipt_relative_path(self.source_ref, self.extractor_version)


def derive_receipt_id(*, source_ref: object, extractor_version: object) -> str:
    """``receipt:<24 hex>`` — one receipt per (source revision, extractor)."""
    ref = source_ref if isinstance(source_ref, dict) else validate_source_ref(source_ref)
    return _digest(
        RECEIPT_ID_PREFIX,
        {
            "source_ref": f"{ref['source_id']}@{ref['revision']}",
            "extractor_version": _text(extractor_version),
        },
    )


def validate_extraction_receipt(value: object, *, now: object = None) -> dict:
    """Normalize a receipt or raise :class:`ExtractionReceiptError`.

    Every claim in the receipt must cite the receipt's own source revision and
    extractor version — a receipt that carries somebody else's claim is not
    evidence of anything — and no claim id may appear twice.
    """
    if isinstance(value, ExtractionReceipt):
        value = value.to_dict()
    if not isinstance(value, dict):
        raise ExtractionReceiptError("receipt_not_a_mapping", "a receipt must be a mapping")
    source_ref = validate_source_ref(value.get("source_ref"))
    extractor_version = _text(value.get("extractor_version"))
    extractor = value.get("extractor") if isinstance(value.get("extractor"), dict) else {}
    if not extractor_version and extractor:
        extractor_version = extractor_version_string(
            extractor.get("name"),
            schema_version=extractor.get("schema_version"),
            prompt_version=extractor.get("prompt_version"),
            model=extractor.get("model"),
            rule_version=extractor.get("rule_version"),
        )
    if not extractor_version:
        raise ExtractionReceiptError(
            "extractor_version_required", "a receipt names the extractor that wrote it"
        )

    claims: list[dict] = []
    seen: set[str] = set()
    for raw in value.get("claims") or ():
        claim = validate_temporal_claim(raw, now=now)
        if claim["source_ref"] != source_ref:
            raise ExtractionReceiptError(
                "receipt_claim_source_mismatch",
                f"claim {claim['claim_id']} cites a different source revision",
                detail=claim["source_ref"],
            )
        if claim["extractor_version"] != extractor_version:
            raise ExtractionReceiptError(
                "receipt_claim_extractor_mismatch",
                f"claim {claim['claim_id']} cites extractor "
                f"{claim['extractor_version']!r}, receipt is {extractor_version!r}",
            )
        if claim["claim_id"] in seen:
            raise ExtractionReceiptError(
                "receipt_duplicate_claim_id",
                f"claim {claim['claim_id']} appears twice in one receipt",
            )
        seen.add(claim["claim_id"])
        claims.append(claim)

    normalized: dict = {
        "receipt_id": derive_receipt_id(
            source_ref=source_ref, extractor_version=extractor_version
        ),
        "schema_version": SCHEMA_VERSION,
        "source_ref": source_ref,
        "extractor_version": extractor_version,
        "extractor": {k: v for k, v in extractor.items() if v is not None},
        "created_at": normalized_timestamp(
            value.get("created_at") or now, error=ExtractionReceiptError
        ),
        "claims": claims,
    }
    recorder = _opt_text(value.get("recorder"))
    if recorder:
        normalized["recorder"] = recorder
    idempotency_key = _opt_text(value.get("idempotency_key"))
    if idempotency_key:
        normalized["idempotency_key"] = idempotency_key
    return normalized


def receipt_from_dict(value: object) -> ExtractionReceipt | None:
    """Tolerant reader — ``None`` rather than an exception (compat rule 2)."""
    try:
        normalized = validate_extraction_receipt(value)
    except TemporalContractError:
        return None
    claims = tuple(claim for claim in (claim_from_dict(c) for c in normalized["claims"]) if claim)
    return ExtractionReceipt(
        receipt_id=normalized["receipt_id"],
        source_ref=SourceRef(
            source_id=normalized["source_ref"]["source_id"],
            revision=normalized["source_ref"]["revision"],
            source_path=normalized["source_ref"].get("source_path"),
        ),
        extractor_version=normalized["extractor_version"],
        created_at=normalized["created_at"],
        claims=claims,
        extractor=dict(normalized["extractor"]),
        recorder=normalized.get("recorder"),
        idempotency_key=normalized.get("idempotency_key"),
        schema_version=int(normalized.get("schema_version") or SCHEMA_VERSION),
    )


__all__ = [
    "ACTIVE_INDEX_FILE",
    "CLAIM_BASES",
    "CLAIM_BASIS_BY_DATE_BASIS",
    "CLAIM_IDENTITY_KEYS",
    "CLAIM_STATUSES",
    "CLAIM_TYPES",
    "CONSTRAINT_IDENTITY_KEYS",
    "CONSTRAINT_RELATIONS",
    "CORRECTION_SOURCES_DIR",
    "DATED_CLAIM_TYPES",
    "ERROR_CODES",
    "EVENT_KINDS",
    "EVENT_KIND_RE",
    "IDEMPOTENCY_KEYS",
    "MAX_EVIDENCE_QUOTE_CHARS",
    "RECEIPTS_DIR",
    "RELATION_ANCHOR_ARITY",
    "SCHEMA_VERSION",
    "SOURCE_KINDS",
    "TEMPORAL_STATE_DIR",
    "EvidenceSpan",
    "ExtractionReceipt",
    "ExtractionReceiptError",
    "OrderingConstraint",
    "OrderingConstraintError",
    "OrderingRelation",
    "SourceRef",
    "SourceRefError",
    "TemporalClaim",
    "TemporalClaimError",
    "TemporalContractError",
    "bounded_quote",
    "bounded_source_key",
    "claim_basis_for_date_basis",
    "claim_from_dict",
    "claim_identity_payload",
    "collapsed_text",
    "constraint_from_dict",
    "derive_claim_id",
    "derive_constraint_id",
    "derive_extraction_idempotency_key",
    "derive_receipt_id",
    "digest_id",
    "evidence_from_dict",
    "extractor_version_string",
    "is_safe_id",
    "is_seed_event_kind",
    "normalized_mention_key",
    "normalized_revision",
    "normalized_temporal_value",
    "normalized_timestamp",
    "optional_text",
    "ordering_relation_from_dict",
    "receipt_from_dict",
    "receipt_relative_path",
    "source_ref_from_dict",
    "split_subject_enumeration",
    "unit_score",
    "validate_evidence_span",
    "validate_extraction_receipt",
    "validate_ordering_constraint",
    "validate_ordering_relation",
    "validate_source_ref",
    "validate_temporal_claim",
]
