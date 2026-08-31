"""Event identity — the telling manifest, episode operations and bindings.

Controlling design: lifehug-platform `docs/design/event-identity.md` v4,
§3.1 (C1) and §3.2-§3.3 (C2). Phase **I0** — the executable half of the
contracts. This module owns RECORDS and one PROJECTION. It does not group
anything: there is no fold change here, no binder, no CLI verb. Those are
I1/I2/I3, and the whole point of I0 is that they arrive against a schema
that has already been argued with.

**The idea in three nouns.** A *telling* is one source-local account of one
event — the classifier's ``classification:<stem>#<event key>`` unit, a
recorder entry, one event inside a promoted message. An *episode* is the
system's conclusion that several tellings are about one thing: an opaque
identity minted by an explicit operation receipt. A *binding* attaches one
telling to one episode with a relation and an origin, and is the SOLE
authority the fold will ever read for grouping (design F2). Tellings and
claims are never rewritten; re-deciding is a new record naming what it
supersedes.

**Why a manifest at all (audit F1/G2).** ``classification:<stem>#<event
key>`` is a hash of the model's own ``title`` and ``description``
(`classifier_claims.event_key`), so a re-extraction that rewords either
MOVES the identity of a telling nobody corrected. The manifest is the one
place that says which telling a claim belongs to, what document revision it
came from, and — when the words moved — whether the new row is the same
telling under a new key or a different account that merely happens to be the
only other one left. **Cardinality never answers that question.** "Exactly
one old unmatched event and exactly one new unmatched event" is satisfied
just as well by a re-extraction that dropped one event and discovered
another, and carrying a confirmed binding across that is the silent wrong
merge the whole design exists to refuse. So the one-candidate condition is a
uniqueness GATE applied on top of evidence, never evidence itself
(:func:`rekey_evidence`).

**Why the manifest may live under ``state/``.** Every input it reads is
durable: extraction receipts are immutable and are never deleted
(`temporal_store.create_or_keep`), corrections are sources, and human
identity records live under ``sources/identity/``. Delete
``state/temporal_claims/telling_manifest.json`` and rebuild it and you get
the same bytes back — :func:`build_telling_manifest` is a pure function of
what is on disk, and a test proves it.

**Storage split (design §3.2/§3.3).** Authority decides the directory, and
the directory is the whole of CERT-11's promise:

===================================  ======================================
``sources/identity/operations/``     human envelopes — merges, splits,
                                     stated creations, ``adopt``
``sources/identity/bindings/``       every person-made relation
``state/…/identities/operations/``   deterministic envelopes, rebuildable
``state/…/identities/bindings/``     deterministic and proposed bindings
===================================  ======================================

Deleting everything under ``state/`` therefore removes what a rule can
re-derive and keeps every decision a person made — and re-running the binder
on identical durable inputs lands on the SAME ids, because a deterministic
operation id digests semantic inputs only: no invocation id, no wall clock
(:func:`operation_digest`, audit G1).

This module never binds itself to a vault: like `temporal_store`, every
function takes the vault root, because the writer runs inside a hosted job
against a checkout the interpreter did not select.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Mapping, Sequence

SYSTEM_DIR = Path(__file__).resolve().parent
if str(SYSTEM_DIR) not in sys.path:
    sys.path.insert(0, str(SYSTEM_DIR))

import temporal_store as store  # noqa: E402
from episode_fold_contract import (  # noqa: E402
    DETERMINISTIC_CONTAINMENT_RULE_IDS,
    GROUPING_ORIGINS,
    GROUPING_RELATION,
    IDENTITY_RULE_VERSION,
    ORIGINS,
    RELATIONS,
    deterministic_relation_allowed,
)
from vault_paths import atomic_write_vault_text  # noqa: E402
from temporal_claims import (  # noqa: E402
    SCHEMA_VERSION,
    TemporalContractError,
    collapsed_text,
    digest_id,
    normalized_mention_key,
    normalized_revision,
    normalized_timestamp,
)

# --------------------------------------------------------------------------
# Vocabulary and layout
# --------------------------------------------------------------------------

#: ONE HOME (ADR 0021). `IDENTITY_RULE_VERSION`, `RELATIONS`, `ORIGINS`,
#: `GROUPING_RELATION` and `GROUPING_ORIGINS` are C3's
#: (`system/episode_fold_contract.py`) and are IMPORTED here, never restated —
#: a second copy of the identity layer's own vocabulary is precisely the drift
#: this program exists to refuse, and `test_event_identity_i0_fold.py`'s
#: one-home sweep fails the build on one.
TEMPORAL_STATE_DIR = "state/temporal_claims"

#: The projection this module builds (design §3.1). A PROJECTION: rebuilt from
#: durable inputs, never hand-edited, safe to delete.
TELLING_MANIFEST_FILE = f"{TEMPORAL_STATE_DIR}/telling_manifest.json"

#: Deterministic and proposed identity records — rebuildable by re-running the
#: binder at the same rule version, which is what makes CERT-11's
#: delete-the-layer-and-refold row meaningful.
IDENTITY_STATE_DIR = f"{TEMPORAL_STATE_DIR}/identities"
STATE_BINDINGS_DIR = f"{IDENTITY_STATE_DIR}/bindings"
STATE_OPERATIONS_DIR = f"{IDENTITY_STATE_DIR}/operations"

#: Human authority. Law 7: human decisions are sources, not state.
IDENTITY_SOURCES_DIR = "sources/identity"
HUMAN_BINDINGS_DIR = f"{IDENTITY_SOURCES_DIR}/bindings"
HUMAN_OPERATIONS_DIR = f"{IDENTITY_SOURCES_DIR}/operations"

#: The fold's own read model over the bindings. Declared here so there is one
#: spelling of the path; I0 does not build it (that is I1's fold work).
IDENTITY_INDEX_FILE = f"{TEMPORAL_STATE_DIR}/identity_index.json"

BINDING_TYPE = "event_identity"
OPERATION_TYPE = "episode_operation"

EPISODE_ID_PREFIX = "episode"
OPERATION_ID_PREFIX = "eop"
BINDING_ID_PREFIX = "eid"

#: Design §3.3's schema admits ONE value the four world-assertions of
#: :data:`RELATIONS` do not: ``none``, the relation a SPLIT leaves behind —
#: *this telling is not a member of that episode any more*. It is deliberately
#: not ``not_same``, which says the two are different EVENTS, and it is
#: deliberately not a fifth assertion, which is why it is named separately
#: here rather than added to C3's tuple. ``unknown`` is absent from both: it is
#: an epistemic state about a pair, it lives on the work item, it asserts
#: nothing.
SPLIT_DEPARTURE_RELATION = "none"

#: What the ``relation`` FIELD of an `event_identity` record may hold — the
#: four assertions plus the departure. Derived, so it cannot drift from C3.
BINDING_RELATIONS = RELATIONS + (SPLIT_DEPARTURE_RELATION,)

#: Which origins are a person's and which are a rule's. Derived from
#: :data:`ORIGINS` rather than re-listed, so adding a fifth origin upstream
#: cannot leave a stale partition down here.
HUMAN_ORIGINS = ("stated", "confirmed")
MACHINE_ORIGINS = tuple(origin for origin in ORIGINS if origin not in HUMAN_ORIGINS)

OPERATIONS = ("create", "merge", "split", "adopt", "retitle")
AUTHORITIES = ("human", "deterministic")
RECORD_STATUSES = ("active", "superseded")

#: FROZEN for schema v1 (design §3.2). The exact, ordered digest input behind
#: :func:`operation_digest`. Semantic inputs only — an invocation id or a wall
#: clock in this tuple would be the G1 defect: deleting deterministic state
#: would mint new episode ids and orphan every human decision that pointed at
#: the old ones.
OPERATION_IDENTITY_KEYS = (
    "authority",
    "op",
    "rule_version",
    "member_refs_sorted",
    "acted_on_episode_ids",
)

#: FROZEN for schema v1 (design §3.3). What makes two bindings the same
#: decision. Everything outside this tuple — ``created_at``, ``evidence``,
#: ``candidates``, ``confidence`` — is annotation written once at create and
#: never overwritten (the canonical-bytes rule, audit A6).
IDENTITY_IDENTITY_KEYS = (
    "telling_ref",
    "episode_id",
    "relation",
    "rule_version",
    "supersedes",
)

#: The digest domain names. Kept as constants so a test can pin the exact
#: strings the ids are minted under rather than re-typing them.
OPERATION_DIGEST_DOMAIN = "episode-op"
EPISODE_DIGEST_DOMAIN = "episode"
BINDING_DIGEST_DOMAIN = "event-identity"

# --------------------------------------------------------------------------
# Telling refs — one mint per source kind (design §3.1)
# --------------------------------------------------------------------------

#: The three source kinds that produce tellings today. A fourth would need its
#: own mint and its own row in the re-key table, which is the point of naming
#: them rather than sniffing prefixes at four call sites.
TELLING_SOURCE_KINDS = ("classifier", "landmark", "conversation")

CLASSIFIER_TELLING_PREFIX = "classification"
LANDMARK_TELLING_PREFIX = "landmark"
CONVERSATION_TELLING_PREFIX = "conversation"

#: The receipt's ``extractor`` block may DECLARE its tellings outright:
#: ``{claim_id: telling_ref}``. The classifier needs no declaration because
#: its per-event source id already IS the telling ref; the recorder will
#: declare ``landmark:<entry id>``; a promoted message declares
#: ``<promoted source id>#<event key>``. A declaration is durable because a
#: receipt is immutable, which is what keeps the manifest rebuildable.
TELLING_KEYS_FIELD = "telling_keys"

#: The receipt's ``extractor`` block may also declare the revision of the
#: UNDERLYING DOCUMENT — the thing a person corrects — as distinct from the
#: revision of the extraction output the claims cite. The two are different
#: for the classifier: rewording a title moves the classification's own
#: revision while the story file has not changed a byte. Without this field
#: the manifest cannot tell a model rewording (design case 2) from a human
#: source correction (case 4), so it refuses to re-key at all and says so —
#: see :data:`UNDECLARED_DOCUMENT_REVISION`.
DOCUMENT_REVISION_FIELD = "document_revision"

#: A durable, recorder-minted per-event id, when the extractor has one. It is
#: re-key evidence of the strongest kind: it does not move when words do.
RECORDER_EVENT_ID_FIELD = "recorder_event_id"

_TELLING_REF_RE = re.compile(r"^[a-z][a-z0-9_]*:[^\s]+$")
_HEX24_RE = re.compile(r"^[0-9a-f]{24}$")
_EPISODE_ID_RE = re.compile(r"^episode:[0-9a-f]{24}$")
_OPERATION_ID_RE = re.compile(r"^eop:[0-9a-f]{24}$")
_BINDING_ID_RE = re.compile(r"^eid:[0-9a-f]{24}$")
_ERA_REF_RE = re.compile(r"^era:[0-9a-f]{24}$")


class EventIdentityError(TemporalContractError):
    """An identity record or the manifest could not be built, with a code."""


#: Every code this module raises. Enumerated so tests and dashboards read the
#: list instead of guessing at it (the `temporal_claims.ERROR_CODES` shape).
EVENT_IDENTITY_ERROR_CODES = (
    # C1 — tellings and the manifest
    "telling_ref_required",
    "telling_ref_malformed",
    "telling_spans_two_events",
    "telling_manifest_unreadable",
    "telling_entry_id_required",
    "telling_event_key_required",
    # C2 — operations
    "operation_not_a_mapping",
    "operation_authority_unknown",
    "operation_kind_unknown",
    "operation_id_malformed",
    "operation_needs_members",
    "operation_needs_episode",
    "operation_split_needs_destinations",
    "operation_destination_unknown",
    "operation_merge_needs_absorbed",
    "operation_status_unknown",
    "operation_record_unreadable",
    "identity_members_disagree",
    "identity_envelope_incomplete",
    # C2 — bindings
    "identity_not_a_mapping",
    "identity_binding_id_malformed",
    "identity_relation_unknown",
    "identity_origin_unknown",
    "identity_needs_telling",
    "identity_needs_episode",
    "identity_deterministic_relation_unsupported",
    "identity_binding_unreadable",
    "identity_unsuperseded_twin",
    "identity_conflict",
)


def _require(condition: object, code: str, message: str, **detail: object) -> None:
    if not condition:
        raise EventIdentityError(code, message, detail=detail or None)


def classifier_telling_ref(stem: object, event: object) -> str:
    """``classification:<stem>#<event key>`` — the classifier's own unit.

    Bound to `classifier_claims.event_source_id` rather than re-derived: the
    12-hex key is over the event's own words and there must be exactly one
    implementation of that, or the manifest and the extractor would disagree
    about which moment is which. Imported lazily to keep this module cheap to
    import from the fold.
    """
    import classifier_claims as cc  # noqa: PLC0415

    return cc.event_source_id(stem, event)


def landmark_telling_ref(entry_id: object) -> str:
    """``landmark:<entry id>`` — a recorder entry, keyed by a durable id.

    The strongest of the three mints: the entry id is minted by the recorder
    and does not move when a later model describes the same entry with other
    words, so a landmark telling never needs the re-key machinery at all.
    """
    text = collapsed_text(entry_id)
    _require(text, "telling_entry_id_required", "a landmark telling names its entry id")
    return f"{LANDMARK_TELLING_PREFIX}:{text}"


def conversation_telling_ref(promoted_source_id: object, event_key: object) -> str:
    """``<promoted source id>#<event key>`` — one event inside one message.

    Amendment Q2 promotes a claim-bearing message to a vault source before
    anything cites it, so the message half of this ref is already durable; the
    event half is the recorder's per-event key inside that one utterance.
    """
    source = collapsed_text(promoted_source_id)
    _require(source, "telling_ref_required", "a conversation telling names its promoted source")
    key = collapsed_text(event_key)
    _require(key, "telling_event_key_required", "a conversation telling names its event key")
    return f"{source}#{key}"


def validate_telling_ref(value: object) -> str:
    """Normalize a telling ref or raise. ``<prefix>:<rest>``, no whitespace."""
    text = collapsed_text(value)
    _require(text, "telling_ref_required", "a telling is named by a ref")
    _require(
        _TELLING_REF_RE.fullmatch(text),
        "telling_ref_malformed",
        f"not a telling ref: {value!r}",
    )
    return text


def telling_source_kind(telling_ref: object) -> str:
    """Which of :data:`TELLING_SOURCE_KINDS` minted this ref.

    A ref whose prefix is none of the three is reported as ``"other"`` rather
    than refused: the substrate can hold a source kind this phase has not met,
    and pretending otherwise would make an unknown extractor an outage instead
    of a row nobody groups yet.
    """
    text = validate_telling_ref(telling_ref)
    prefix = text.split(":", 1)[0]
    if prefix == CLASSIFIER_TELLING_PREFIX:
        return "classifier"
    if prefix == LANDMARK_TELLING_PREFIX:
        return "landmark"
    if prefix == CONVERSATION_TELLING_PREFIX:
        return "conversation"
    return "other"


def split_telling_ref(telling_ref: object) -> tuple[str, str | None]:
    """``(source id, source-local key | None)``.

    The classifier's ref is its source id whole, ``#`` included, because that
    is what the claims cite; the local key is still the part after ``#`` and
    is what makes the row legible. A landmark ref has no source id of its own
    in this phase — the entry id IS the key.
    """
    text = validate_telling_ref(telling_ref)
    head, sep, tail = text.partition("#")
    if not sep:
        return text, None
    return text, tail or None


def telling_ref_for_claim(claim: object, *, receipt: object = None) -> str:
    """The telling one claim belongs to (design §3.1's "no new claim field").

    Order of authority: the receipt's own declaration
    (:data:`TELLING_KEYS_FIELD`) first, because an extractor that mints
    per-event units knows which is which and nothing downstream should have to
    guess; then the claim's ``source_ref.source_id``, which for the classifier
    already carries the event key. ``TemporalClaim`` gains no field, exactly as
    §9 promised.
    """
    row = claim if isinstance(claim, dict) else {}
    claim_id = collapsed_text(row.get("claim_id"))
    declared = _declared_telling_keys(receipt).get(claim_id)
    if declared:
        return validate_telling_ref(declared)
    source_ref = row.get("source_ref")
    source_id = ""
    if isinstance(source_ref, dict):
        source_id = collapsed_text(source_ref.get("source_id"))
    elif source_ref is not None:
        source_id = collapsed_text(getattr(source_ref, "source_id", ""))
    _require(
        source_id,
        "telling_ref_required",
        f"claim {claim_id or '<unnamed>'} cites no source, so it belongs to no telling",
    )
    return validate_telling_ref(source_id)


def _extractor_block(receipt: object) -> dict:
    if isinstance(receipt, dict):
        block = receipt.get("extractor")
    else:
        block = getattr(receipt, "extractor", None)
    return block if isinstance(block, dict) else {}


def _declared_telling_keys(receipt: object) -> dict[str, str]:
    declared = _extractor_block(receipt).get(TELLING_KEYS_FIELD)
    if not isinstance(declared, dict):
        return {}
    return {
        collapsed_text(key): collapsed_text(value)
        for key, value in declared.items()
        if collapsed_text(key) and collapsed_text(value)
    }


def declare_tellings(
    extractor: object = None,
    *,
    telling_keys: Mapping[str, str] | None = None,
    document_revision: object = None,
    recorder_event_id: object = None,
) -> dict:
    """Build (or extend) a receipt's ``extractor`` block with I0's three fields.

    One call so an extractor's wiring in I1 is a line rather than three string
    literals copied into three modules — the recurring-defect doctrine applied
    before the defect: this is the shape `classifier_claims` and
    `landmark_recorder` will both need, and there is one spelling of it.
    """
    block = dict(extractor) if isinstance(extractor, dict) else {}
    if telling_keys:
        rows = {
            collapsed_text(key): validate_telling_ref(value)
            for key, value in telling_keys.items()
            if collapsed_text(key)
        }
        merged = dict(block.get(TELLING_KEYS_FIELD) or {})
        merged.update(rows)
        block[TELLING_KEYS_FIELD] = dict(sorted(merged.items()))
    revision = normalized_revision(document_revision)
    if revision:
        block[DOCUMENT_REVISION_FIELD] = revision
    recorder = collapsed_text(recorder_event_id)
    if recorder:
        block[RECORDER_EVENT_ID_FIELD] = recorder
    return block


# --------------------------------------------------------------------------
# The event signature — what a re-key may reason from
# --------------------------------------------------------------------------

#: The four independent components of a telling's signature (design §3.1c).
#: Independent is the load-bearing word: two of these agreeing is evidence
#: precisely because a re-extraction that rewrote the label did not also
#: rewrite the place roster and the participant set to match by accident.
SIGNATURE_COMPONENTS = ("label_stem", "place_set", "participant_set", "temporal_value")

#: How many independent components must agree, exactly, for the signature rung
#: to count as evidence. Two, with zero contradictions.
MIN_SIGNATURE_AGREEMENT = 2

#: The owner is on every telling; agreeing about the owner is not evidence.
OWNER_SUBJECT_KEYS = ("self", "owner", "me", "i")


def telling_signature(claims: Sequence[object]) -> dict:
    """The event signature of one telling — pure, over its claims' own fields.

    Label, places and participants are normalized through
    `temporal_claims.normalized_mention_key`, the repo's one mention
    normalization, so "Aunt Della." and "aunt  della" are one participant here
    for the same reason they are one subject there.
    """
    labels: list[str] = []
    places: set[str] = set()
    participants: set[str] = set()
    values: list[str] = []
    for claim in claims or ():
        row = claim if isinstance(claim, dict) else {}
        label = normalized_mention_key(
            row.get("event_mention") or row.get("subject_mention")
        )
        if label:
            labels.append(label)
        for place in row.get("place_mentions") or ():
            key = normalized_mention_key(place)
            if key:
                places.add(key)
        subject = collapsed_text(row.get("subject_ref")) or normalized_mention_key(
            row.get("subject_mention")
        )
        if subject and subject.casefold() not in OWNER_SUBJECT_KEYS:
            participants.add(subject)
        value = row.get("temporal_value")
        if value not in (None, "", {}, []):
            values.append(
                json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
            )
    return {
        "label_stem": sorted(dict.fromkeys(labels))[0] if labels else None,
        "place_set": sorted(places),
        "participant_set": sorted(participants),
        "temporal_value": sorted(dict.fromkeys(values)) or None,
    }


def telling_locator(claims: Sequence[object]) -> dict | None:
    """The source-local locator: character spans and turn refs, never words.

    Deliberately NOT the evidence quote. A quote is the model's transcription
    of the source and moves when the model's reading moves; a span and a turn
    ref are coordinates in the source itself, which is the whole reason the
    design lets an unchanged locator carry a re-key on its own.
    """
    spans: set[tuple[int, int]] = set()
    turns: set[str] = set()
    for claim in claims or ():
        row = claim if isinstance(claim, dict) else {}
        for span in row.get("evidence") or ():
            cell = span if isinstance(span, dict) else {}
            start, end = cell.get("start"), cell.get("end")
            if isinstance(start, int) and isinstance(end, int):
                spans.add((start, end))
            turn = collapsed_text(cell.get("turn_ref"))
            if turn:
                turns.add(turn)
    if not spans and not turns:
        return None
    return {
        "spans": [list(pair) for pair in sorted(spans)],
        "turn_refs": sorted(turns),
    }


def compare_signatures(left: object, right: object) -> tuple[list[str], list[str]]:
    """``(agreeing components, contradicting components)`` — nothing else.

    A component where either side is empty is neither: absence is not
    agreement and it is not a contradiction. That asymmetry is what stops an
    undated, place-less re-extraction from looking like a match to everything.
    """
    a = left if isinstance(left, dict) else {}
    b = right if isinstance(right, dict) else {}
    agreeing: list[str] = []
    contradicting: list[str] = []
    for component in SIGNATURE_COMPONENTS:
        first, second = a.get(component), b.get(component)
        if not first or not second:
            continue
        if first == second:
            agreeing.append(component)
        else:
            contradicting.append(component)
    return agreeing, contradicting


# --------------------------------------------------------------------------
# Re-key — the four cases, as a table (design §3.1, audit G2)
# --------------------------------------------------------------------------

#: The four cases §3.1 enumerates, plus the one this phase adds because the
#: substrate cannot yet tell two of them apart honestly.
REKEY_CASES = (
    "extractor_remint",
    "reworded",
    "fragmented",
    "source_corrected",
    "undeclared_document_revision",
    "durable_alias",
    "no_successor",
)

#: What a case DOES. ``same_ref`` never retires anything; ``rekeyed`` moves the
#: key and carries the bindings; ``preserve_both`` keeps two rows and asks;
#: ``retired`` keeps the row visible with a ``superseded_by`` and carries
#: nothing.
REKEY_OUTCOMES = ("same_ref", "rekeyed", "preserve_both", "retired")

#: The kinds of evidence that may carry a re-key, strongest first.
REKEY_EVIDENCE_KINDS = ("locator", "recorder_event_id", "signature_agreement")

#: Emitted, loudly, whenever two rows are preserved because nothing stronger
#: than cardinality was available. A confirmed binding on the retired row
#: raises the resulting question's value; it never moves by itself.
REKEY_DIAGNOSTIC = "telling_rekey"

#: Emitted when a telling was split into, or merged out of, several new rows
#: inside one extraction. Bindings never transfer here, by rule.
FRAGMENT_DIAGNOSTIC = "telling_fragmented"

#: Emitted when the document itself moved under the extraction — a human
#: correction. A new telling by definition; never an alias.
CORRECTION_DIAGNOSTIC = "telling_source_corrected"

#: Emitted when no extractor declared :data:`DOCUMENT_REVISION_FIELD`, so the
#: manifest cannot distinguish a rewording from a correction. Conservative by
#: construction: it takes the correction reading and re-keys nothing.
UNDECLARED_DOCUMENT_REVISION = "telling_document_revision_undeclared"

MANIFEST_DIAGNOSTICS = (
    REKEY_DIAGNOSTIC,
    FRAGMENT_DIAGNOSTIC,
    CORRECTION_DIAGNOSTIC,
    UNDECLARED_DOCUMENT_REVISION,
)


class TellingTransition:
    """One row of the re-key transition table — data, not prose."""

    __slots__ = ("case", "trigger", "outcome", "bindings", "diagnostic")

    def __init__(
        self, case: str, trigger: str, outcome: str, bindings: str, diagnostic: str | None
    ) -> None:
        self.case = case
        self.trigger = trigger
        self.outcome = outcome
        self.bindings = bindings
        self.diagnostic = diagnostic

    def to_dict(self) -> dict:
        return {
            "case": self.case,
            "trigger": self.trigger,
            "outcome": self.outcome,
            "bindings": self.bindings,
            "diagnostic": self.diagnostic,
        }

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"TellingTransition({self.case!r} -> {self.outcome!r})"


#: **The transition table.** Design §3.1's four cases, in code, each with a
#: fixture in `tests/test_event_identity_i0_tellings.py`. Read the ``bindings``
#: column as the answer to the only question that actually matters: does a
#: confirmed binding follow the words, or does the person get asked?
TELLING_TRANSITIONS = (
    TellingTransition(
        case="extractor_remint",
        trigger="a new extractor version re-mints claims and the words are unchanged",
        outcome="same_ref",
        bindings="untouched",
        diagnostic=None,
    ),
    TellingTransition(
        case="reworded",
        trigger="one candidate at the same document revision with stable evidence",
        outcome="rekeyed",
        bindings="carried to the new ref",
        diagnostic=None,
    ),
    TellingTransition(
        case="reworded",
        trigger="one candidate at the same document revision with no stable evidence",
        outcome="preserve_both",
        bindings="left on the retired row; the pair becomes a question",
        diagnostic=REKEY_DIAGNOSTIC,
    ),
    TellingTransition(
        case="fragmented",
        trigger="one telling becomes two, or two become one, inside one extraction",
        outcome="retired",
        bindings="never transferred; a confirmed binding mints a question per fragment",
        diagnostic=FRAGMENT_DIAGNOSTIC,
    ),
    TellingTransition(
        case="source_corrected",
        trigger="the underlying document's revision moved",
        outcome="retired",
        bindings="follow the superseded claims out of the active set",
        diagnostic=CORRECTION_DIAGNOSTIC,
    ),
    TellingTransition(
        case="undeclared_document_revision",
        trigger="no extractor declared the document revision, so a rewording and a "
        "correction are indistinguishable",
        outcome="preserve_both",
        bindings="left on the retired row",
        diagnostic=UNDECLARED_DOCUMENT_REVISION,
    ),
    TellingTransition(
        case="durable_alias",
        trigger="a durable binding record carries the old ref in telling_aliases",
        outcome="rekeyed",
        bindings="already durable; the manifest reports the alias",
        diagnostic=None,
    ),
    TellingTransition(
        case="no_successor",
        trigger="every claim of the telling is inactive and nothing replaced it",
        outcome="retired",
        bindings="dormant; reported, never an error",
        diagnostic=None,
    ),
)


def transition_for(case: str, outcome: str) -> TellingTransition | None:
    """The table row for one (case, outcome) — so tests read the table."""
    for row in TELLING_TRANSITIONS:
        if row.case == case and row.outcome == outcome:
            return row
    return None


def rekey_evidence(old_row: object, new_row: object) -> dict:
    """Is there evidence — stronger than cardinality — that these are one telling?

    Design §3.1: ``(a)`` an unchanged source locator/span recorded in BOTH
    receipts, ``(b)`` a durable recorder-minted event id, or ``(c)`` exact
    agreement on at least :data:`MIN_SIGNATURE_AGREEMENT` independent
    signature components with ZERO contradicting components.

    Returns the whole reasoning, not a boolean, because the dry-run has to
    print per-pair reasons and a caller that only ever sees ``True``/``False``
    cannot.
    """
    old = old_row if isinstance(old_row, dict) else {}
    new = new_row if isinstance(new_row, dict) else {}
    kinds: list[str] = []
    old_locator, new_locator = old.get("locator"), new.get("locator")
    if old_locator and new_locator and old_locator == new_locator:
        kinds.append("locator")
    old_event, new_event = (
        collapsed_text(old.get("recorder_event_id")),
        collapsed_text(new.get("recorder_event_id")),
    )
    if old_event and old_event == new_event:
        kinds.append("recorder_event_id")
    agreeing, contradicting = compare_signatures(old.get("signature"), new.get("signature"))
    if len(agreeing) >= MIN_SIGNATURE_AGREEMENT and not contradicting:
        kinds.append("signature_agreement")
    return {
        "kinds": kinds,
        "agreeing": agreeing,
        "contradicting": contradicting,
        "sufficient": bool(kinds),
    }


# --------------------------------------------------------------------------
# One telling, one event identity (design §5.1, promise 13.1)
# --------------------------------------------------------------------------

#: A telling whose claims are ABOUT an era — its boundary, its naming — is not
#: episode-groupable. A telling about an event that HAPPENED WITHIN an era
#: keeps full eligibility; the era relationship is a membership on the
#: episode's node, never a reason to discard the binding (audit F-pin 1).
INELIGIBLE_TELLING_IS_AN_ERA = "telling_is_about_an_era"


def event_identities_in(claims: Sequence[object]) -> dict:
    """``{"event_refs": [...], "era_refs": [...]}`` for one telling's claims."""
    events: set[str] = set()
    eras: set[str] = set()
    for claim in claims or ():
        row = claim if isinstance(claim, dict) else {}
        ref = collapsed_text(row.get("event_ref"))
        if not ref:
            continue
        (eras if _ERA_REF_RE.fullmatch(ref) else events).add(ref)
    return {"event_refs": sorted(events), "era_refs": sorted(eras)}


def telling_is_about_an_era(claims: Sequence[object]) -> bool:
    """Does this telling assert something about an era ITSELF?

    The tell is the subject: `era_identity` files an era's own identity claim
    with ``subject_mention`` set to the era id. Nothing else in the substrate
    makes an era the subject of a claim, so this is a read of a fact rather
    than a guess about intent.
    """
    for claim in claims or ():
        row = claim if isinstance(claim, dict) else {}
        if _ERA_REF_RE.fullmatch(collapsed_text(row.get("subject_mention"))):
            return True
        if _ERA_REF_RE.fullmatch(collapsed_text(row.get("subject_ref"))):
            return True
    return False


def assert_one_event_identity(telling_ref: object, claims: Sequence[object]) -> dict:
    """Refuse a telling whose claims describe more than one event identity.

    Design §13.1: *"a telling whose claims describe more than one event
    identity is a manifest-build refusal, never a partial bind."* Two distinct
    non-era ``event_ref`` values under one telling means the extractor put two
    events in one unit, and binding that unit to an episode would drag the
    second event along silently. Era refs are excluded from the count on
    purpose: "this happened during College" is a membership, not a second
    event.
    """
    ref = validate_telling_ref(telling_ref)
    found = event_identities_in(claims)
    _require(
        len(found["event_refs"]) <= 1,
        "telling_spans_two_events",
        f"{ref} carries {len(found['event_refs'])} distinct event identities; "
        "a telling is one source-local account of ONE event",
        telling_ref=ref,
        event_refs=found["event_refs"],
    )
    return found


# --------------------------------------------------------------------------
# The telling manifest (C1)
# --------------------------------------------------------------------------

MANIFEST_SCHEMA_VERSION = 1

#: FROZEN for manifest schema v1. Every row carries every key — a missing key
#: and a null key are different questions and a reader should never have to
#: ask which one it got.
TELLING_ROW_KEYS = (
    "telling_ref",
    "source_kind",
    "source_id",
    "local_key",
    "source_path",
    "document_key",
    "document_revision",
    "extraction_revisions",
    "extractor_versions",
    "recorder_event_id",
    "claim_ids",
    "active_claim_ids",
    "status",
    "episode_eligible",
    "ineligible_reason",
    "event_refs",
    "era_refs",
    "signature",
    "locator",
    "aliases",
    "superseded_by",
    "rekey_case",
    "rekey_evidence",
    "bound_identity_ids",
)


def build_telling_manifest(
    vault_root: str | Path,
    *,
    bindings: Sequence[object] | None = None,
) -> dict:
    """The manifest, as a PURE projection of durable inputs (design §3.1).

    Inputs, all of them durable: the extraction receipts (immutable, never
    deleted, so both the old wording and the new one are still on disk), the
    corrections that retired claims, and the identity bindings — whose
    optional ``telling_aliases`` annotation is where a re-key that a person
    already confirmed rides, so the alias survives even this file being
    deleted.

    Not an input: the clock. Nothing in the output is stamped with a time, so
    "delete it and rebuild it byte-identically" is arithmetic rather than a
    hope.
    """
    index = store.fold_active_index(vault_root)
    receipts, unreadable = store.load_receipts(vault_root)
    by_receipt = {receipt.receipt_id: receipt for receipt in receipts}
    records = (
        list(bindings) if bindings is not None else load_event_identities(vault_root)
    )

    grouped: dict[str, list[dict]] = {}
    for claim in index.get("claims") or ():
        row = claim if isinstance(claim, dict) else {}
        receipt = by_receipt.get(collapsed_text(row.get("receipt_id")))
        ref = telling_ref_for_claim(row, receipt=receipt)
        grouped.setdefault(ref, []).append(row)

    rows = [
        _telling_row(ref, claims, by_receipt)
        for ref, claims in sorted(grouped.items())
    ]
    by_ref = {row["telling_ref"]: row for row in rows}
    diagnostics: list[dict] = []
    _apply_durable_aliases(by_ref, records)
    _apply_rekeys(rows, _generations(rows), diagnostics)
    _attach_bindings(by_ref, records)

    counts = {
        "tellings": len(rows),
        "active": sum(1 for row in rows if row["status"] == "active"),
        "retired": sum(1 for row in rows if row["status"] == "retired"),
        "episode_eligible": sum(1 for row in rows if row["episode_eligible"]),
        "rekeyed": sum(1 for row in rows if row["aliases"]),
        "diagnostics": len(diagnostics),
    }
    return {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "claim_schema_version": SCHEMA_VERSION,
        "rule_version": IDENTITY_RULE_VERSION,
        "counts": counts,
        "tellings": rows,
        "diagnostics": sorted(
            diagnostics, key=lambda row: (row["finding"], json.dumps(row, sort_keys=True))
        ),
        "unreadable_receipt_paths": list(unreadable),
    }


def _telling_row(ref: str, claims: Sequence[dict], by_receipt: Mapping[str, object]) -> dict:
    found = assert_one_event_identity(ref, claims)
    source_id, local_key = split_telling_ref(ref)
    kind = telling_source_kind(ref)
    active = sorted(
        collapsed_text(row.get("claim_id"))
        for row in claims
        if collapsed_text(row.get("status")) == "active"
    )
    paths: set[str] = set()
    revisions: set[str] = set()
    extractors: set[str] = set()
    document_revisions: set[str] = set()
    recorder_ids: set[str] = set()
    for row in claims:
        source_ref = row.get("source_ref")
        if isinstance(source_ref, dict):
            path = collapsed_text(source_ref.get("source_path"))
            if path:
                paths.add(path)
            revision = collapsed_text(source_ref.get("revision"))
            if revision:
                revisions.add(revision)
        version = collapsed_text(row.get("extractor_version"))
        if version:
            extractors.add(version)
        block = _extractor_block(by_receipt.get(collapsed_text(row.get("receipt_id"))))
        declared = normalized_revision(block.get(DOCUMENT_REVISION_FIELD))
        if declared:
            document_revisions.add(declared)
        recorder = collapsed_text(block.get(RECORDER_EVENT_ID_FIELD))
        if recorder:
            recorder_ids.add(recorder)
    if kind == "landmark" and local_key is None:
        # `landmark:<entry id>` — the entry id IS the durable recorder event id.
        recorder_ids.add(ref.split(":", 1)[1])
    about_era = telling_is_about_an_era(claims)
    return {
        "telling_ref": ref,
        "source_kind": kind,
        "source_id": source_id,
        "local_key": local_key,
        "source_path": sorted(paths)[0] if paths else None,
        "document_key": (sorted(paths)[0] if paths else source_id.partition("#")[0]),
        "document_revision": sorted(document_revisions)[0] if len(document_revisions) == 1 else None,
        "extraction_revisions": sorted(revisions),
        "extractor_versions": sorted(extractors),
        "recorder_event_id": sorted(recorder_ids)[0] if len(recorder_ids) == 1 else None,
        "claim_ids": sorted(collapsed_text(row.get("claim_id")) for row in claims),
        "active_claim_ids": active,
        "status": "active" if active else "retired",
        "episode_eligible": not about_era,
        "ineligible_reason": INELIGIBLE_TELLING_IS_AN_ERA if about_era else None,
        "event_refs": found["event_refs"],
        "era_refs": found["era_refs"],
        "signature": telling_signature(claims),
        "locator": telling_locator(claims),
        "aliases": [],
        "superseded_by": [],
        "rekey_case": None,
        "rekey_evidence": None,
        "bound_identity_ids": [],
    }


def _apply_durable_aliases(by_ref: Mapping[str, dict], records: Sequence[object]) -> None:
    """A binding may carry ``telling_aliases`` — the durable half of a re-key.

    Design §3.1's lineage clause: aliases ride the binding/operation records,
    not only the manifest, so deleting this file cannot lose a re-key the
    person already lives with.
    """
    for record in records or ():
        row = record if isinstance(record, dict) else {}
        target = collapsed_text(row.get("telling_ref"))
        live = by_ref.get(target)
        if live is None:
            continue
        for alias in row.get("telling_aliases") or ():
            old = collapsed_text(alias)
            if not old or old == target:
                continue
            if old not in live["aliases"]:
                live["aliases"].append(old)
                live["aliases"].sort()
            live["rekey_case"] = "durable_alias"
            retired = by_ref.get(old)
            if retired is not None and target not in retired["superseded_by"]:
                retired["superseded_by"].append(target)
                retired["superseded_by"].sort()
                retired["rekey_case"] = "durable_alias"


def _apply_rekeys(
    rows: Sequence[dict],
    generations: Mapping[tuple[str, str], set[str]],
    diagnostics: list[dict],
) -> None:
    """The transition table, applied. Nothing here re-keys on cardinality."""
    by_document: dict[str, list[dict]] = {}
    for row in rows:
        by_document.setdefault(row["document_key"], []).append(row)

    proposals: list[tuple[dict, dict, dict]] = []
    for document, members in sorted(by_document.items()):
        live = [row for row in members if row["status"] == "active"]
        retired = [
            row
            for row in members
            if row["status"] == "retired" and not row["superseded_by"]
        ]
        if not retired:
            continue
        for row in retired:
            cohort = _cohort_refs(row, generations)
            candidates = [
                other for other in live if other["telling_ref"] not in cohort
            ]
            if not candidates:
                row["rekey_case"] = "no_successor"
                continue
            if len(candidates) > 1:
                row["rekey_case"] = "fragmented"
                row["superseded_by"] = sorted(
                    other["telling_ref"] for other in candidates
                )
                diagnostics.append(
                    {
                        "finding": FRAGMENT_DIAGNOSTIC,
                        "telling_ref": row["telling_ref"],
                        "document_key": document,
                        "successors": list(row["superseded_by"]),
                    }
                )
                continue
            candidate = candidates[0]
            old_revision, new_revision = row["document_revision"], candidate["document_revision"]
            if not old_revision or not new_revision:
                row["rekey_case"] = "undeclared_document_revision"
                diagnostics.append(
                    {
                        "finding": UNDECLARED_DOCUMENT_REVISION,
                        "telling_ref": row["telling_ref"],
                        "candidate": candidate["telling_ref"],
                        "document_key": document,
                    }
                )
                continue
            if old_revision != new_revision:
                row["rekey_case"] = "source_corrected"
                diagnostics.append(
                    {
                        "finding": CORRECTION_DIAGNOSTIC,
                        "telling_ref": row["telling_ref"],
                        "candidate": candidate["telling_ref"],
                        "document_key": document,
                    }
                )
                continue
            evidence = rekey_evidence(row, candidate)
            row["rekey_evidence"] = evidence
            if not evidence["sufficient"]:
                row["rekey_case"] = "reworded"
                diagnostics.append(
                    {
                        "finding": REKEY_DIAGNOSTIC,
                        "telling_ref": row["telling_ref"],
                        "candidate": candidate["telling_ref"],
                        "document_key": document,
                        "agreeing": evidence["agreeing"],
                        "contradicting": evidence["contradicting"],
                    }
                )
                continue
            proposals.append((row, candidate, evidence))

    # A candidate claimed by two retired rows is a MERGE inside one extraction
    # (design case 3), not two re-keys. Bindings never transfer through it.
    claimed: dict[str, list[dict]] = {}
    for row, candidate, _evidence in proposals:
        claimed.setdefault(candidate["telling_ref"], []).append(row)
    for target, owners in sorted(claimed.items()):
        if len(owners) == 1:
            continue
        for row in owners:
            row["rekey_case"] = "fragmented"
            row["rekey_evidence"] = None
            row["superseded_by"] = [target]
            diagnostics.append(
                {
                    "finding": FRAGMENT_DIAGNOSTIC,
                    "telling_ref": row["telling_ref"],
                    "document_key": row["document_key"],
                    "successors": [target],
                    "merged_with": sorted(
                        other["telling_ref"] for other in owners if other is not row
                    ),
                }
            )

    for row, candidate, evidence in proposals:
        if row["rekey_case"] == "fragmented":
            continue
        row["rekey_case"] = "reworded"
        row["superseded_by"] = [candidate["telling_ref"]]
        if row["telling_ref"] not in candidate["aliases"]:
            candidate["aliases"].append(row["telling_ref"])
            candidate["aliases"].sort()
        candidate["rekey_case"] = candidate["rekey_case"] or "reworded"
        candidate["rekey_evidence"] = evidence


def _generations(rows: Sequence[dict]) -> dict[tuple[str, str], set[str]]:
    """``{(document, extraction revision): {telling refs}}`` — one extraction.

    The generation, not the receipt, is the unit: one classification run mints
    a separate per-event source id (and therefore a separate receipt) for every
    event it finds, so "which tellings existed together" is a question about
    the run, and the run is identified by the revision every one of its
    receipts cites.
    """
    found: dict[tuple[str, str], set[str]] = {}
    for row in rows:
        for revision in row["extraction_revisions"]:
            found.setdefault((row["document_key"], revision), set()).add(row["telling_ref"])
    return found


def _cohort_refs(row: dict, generations: Mapping[tuple[str, str], set[str]]) -> set[str]:
    """Every telling ref that existed alongside this one in its own extraction.

    A row that co-existed with the retired one is not its successor — it is
    the other event that was always there. This is what keeps "one candidate"
    meaning "one thing that appeared when this one disappeared" rather than
    "one other thing in the document".
    """
    cohort = {row["telling_ref"]}
    for revision in row["extraction_revisions"]:
        cohort |= generations.get((row["document_key"], revision), set())
    return cohort


def _attach_bindings(by_ref: Mapping[str, dict], records: Sequence[object]) -> None:
    for record in records or ():
        row = record if isinstance(record, dict) else {}
        live = by_ref.get(collapsed_text(row.get("telling_ref")))
        identity_id = collapsed_text(row.get("identity_id"))
        if live is None or not identity_id:
            continue
        if identity_id not in live["bound_identity_ids"]:
            live["bound_identity_ids"].append(identity_id)
            live["bound_identity_ids"].sort()


def telling_manifest_bytes(manifest: object) -> str:
    """The manifest's one serialization — sorted, indented, newline-terminated."""
    return json.dumps(manifest, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def write_telling_manifest(vault_root: str | Path, manifest: object) -> Path:
    """Publish the manifest atomically through the vault's no-follow authority.

    The one file this module may REPLACE, for `temporal_store.write_active_index`'s
    reason: it is a materialized view and never evidence. Every byte still goes
    through `vault_paths`, which is what the v120 runtime guard enforces —
    a bare ``path.write_text`` here would be a symlink-following write into a
    vault this interpreter did not select.
    """
    # `store_path(root, ".")` is the store's own public, validated resolution of
    # the vault root; this module does not add a second one (`temporal_store`
    # keeps its normalizer private and there is no reason to re-type it here).
    root = store.store_path(vault_root, ".")
    path = store.store_path(root, TELLING_MANIFEST_FILE)
    try:
        atomic_write_vault_text(path, telling_manifest_bytes(manifest), vault_root=root)
    except ValueError as exc:
        raise EventIdentityError("telling_manifest_unreadable", str(exc)) from exc
    return path


def read_telling_manifest(vault_root: str | Path) -> dict | None:
    text = store.read_store_text(vault_root, TELLING_MANIFEST_FILE)
    if text is None:
        return None
    try:
        payload = json.loads(text)
    except (TypeError, ValueError) as exc:
        raise EventIdentityError(
            "telling_manifest_unreadable", f"{TELLING_MANIFEST_FILE} is not JSON"
        ) from exc
    if not isinstance(payload, dict):
        raise EventIdentityError(
            "telling_manifest_unreadable", f"{TELLING_MANIFEST_FILE} is not a mapping"
        )
    return payload


def rebuild_telling_manifest(vault_root: str | Path) -> dict:
    """Build it and write it. The binder step's one call."""
    manifest = build_telling_manifest(vault_root)
    write_telling_manifest(vault_root, manifest)
    return manifest


# --------------------------------------------------------------------------
# Episode operations (C2, design §3.2)
# --------------------------------------------------------------------------

#: A split's destination for a departing telling.
STANDALONE_DESTINATION = "standalone"


def canonical_operation_inputs(
    *,
    authority: str,
    op: str,
    rule_version: object = IDENTITY_RULE_VERSION,
    member_refs: Sequence[object] = (),
    acted_on_episode_ids: Sequence[object] = (),
) -> dict:
    """The exact digest input behind :func:`operation_digest`, exposed.

    Exposed for the same reason `temporal_claims.claim_identity_payload` is:
    a test should be able to pin the payload, and a human debugging why two
    operations collided should be able to see it rather than infer it.
    """
    payload = {
        "authority": collapsed_text(authority),
        "op": collapsed_text(op),
        "rule_version": collapsed_text(rule_version) or IDENTITY_RULE_VERSION,
        "member_refs_sorted": sorted(
            dict.fromkeys(collapsed_text(ref) for ref in member_refs or () if collapsed_text(ref))
        ),
        "acted_on_episode_ids": sorted(
            dict.fromkeys(
                collapsed_text(value)
                for value in acted_on_episode_ids or ()
                if collapsed_text(value)
            )
        ),
    }
    return {key: payload[key] for key in OPERATION_IDENTITY_KEYS}


def operation_digest(**kwargs: object) -> str:
    """``eop:<24 hex>`` over semantic inputs only (design §3.2, audit G1).

    No invocation id. No wall clock. That is the whole promise: delete every
    deterministic identity record, re-run the binder on identical durable
    inputs, and the operation ids — and therefore the episode ids, the
    aliases, the node ids and every downstream target — come back byte-for-byte
    the same. A fresh uuid here would make state deletion an orphaning event
    for everything a person had already renamed, dragged or placed.
    """
    return digest_id(OPERATION_ID_PREFIX, canonical_operation_inputs(**kwargs))  # type: ignore[arg-type]


def episode_id_for(operation_id: object) -> str:
    """``episode:<24 hex>`` from the creating act — the `era_id` pattern.

    An episode's identity is a function of the operation that created it and
    nothing else, so it survives a rename, a re-title, a member leaving, and
    the deletion of every cache in the vault.
    """
    key = collapsed_text(operation_id)
    _require(key, "operation_id_malformed", "an episode id is seeded by its creation operation")
    return digest_id(EPISODE_DIGEST_DOMAIN, {"creation_operation_id": key})


def episode_id_at_rule_version(
    *,
    authority: str,
    op: str = "create",
    rule_version: object,
    member_refs: Sequence[object] = (),
    acted_on_episode_ids: Sequence[object] = (),
) -> str:
    """The episode id a GIVEN rule version would have minted (design §3.2/G1).

    The rule-version transition needs this: an unadopted episode is superseded
    by the new rule's ``create``, which computes the OLD id from the OLD
    formula and lists it in ``aliases_created`` — with no stored state, because
    both ids are arithmetic over the same durable inputs.
    """
    return episode_id_for(
        operation_digest(
            authority=authority,
            op=op,
            rule_version=rule_version,
            member_refs=member_refs,
            acted_on_episode_ids=acted_on_episode_ids,
        )
    )


def operations_dir(authority: object) -> str:
    text = collapsed_text(authority)
    _require(text in AUTHORITIES, "operation_authority_unknown", f"unknown authority: {authority!r}")
    return HUMAN_OPERATIONS_DIR if text == "human" else STATE_OPERATIONS_DIR


def operation_relative_path(authority: object, operation_id: object) -> str:
    return f"{operations_dir(authority)}/{_hex24(operation_id)}.json"


def _hex24(value: object) -> str:
    text = collapsed_text(value).lower()
    _prefix, _, digest = text.rpartition(":")
    digest = digest or text
    _require(_HEX24_RE.fullmatch(digest), "operation_id_malformed", f"not a 24-hex id: {value!r}")
    return digest


def validate_episode_operation(value: object) -> dict:
    """Normalize one envelope or raise — every refusal named (design §3.2/G4).

    The envelope is a TRANSACTION AND AUDIT record. It names, by id, every
    binding it installs and every binding it retires; ``members`` is an audit
    copy the fold never reads for grouping, and a validator asserts it equals
    the tellings of the bindings it names (:func:`validate_envelope`). Two
    truths about membership is the F2 defect, and this is where it is refused.
    """
    _require(isinstance(value, dict) and value, "operation_not_a_mapping", "an operation is a mapping")
    row = dict(value)  # type: ignore[arg-type]
    authority = collapsed_text(row.get("authority"))
    _require(authority in AUTHORITIES, "operation_authority_unknown", f"unknown authority: {row.get('authority')!r}")
    op = collapsed_text(row.get("op"))
    _require(op in OPERATIONS, "operation_kind_unknown", f"unknown operation: {row.get('op')!r}")
    rule_version = collapsed_text(row.get("rule_version")) or IDENTITY_RULE_VERSION
    status = collapsed_text(row.get("status")) or "active"
    _require(status in RECORD_STATUSES, "operation_status_unknown", f"unknown status: {status!r}")

    members = sorted(
        dict.fromkeys(
            validate_telling_ref(ref) for ref in row.get("members") or () if collapsed_text(ref)
        )
    )
    acted_on = sorted(
        dict.fromkeys(
            _episode_id(value) for value in row.get("acted_on_episode_ids") or () if collapsed_text(value)
        )
    )
    if op == "create":
        _require(members, "operation_needs_members", "a create envelope names the tellings it groups")
    if op in ("merge", "split", "adopt", "retitle"):
        _require(
            collapsed_text(row.get("episode_id")),
            "operation_needs_episode",
            f"a {op} envelope names the episode it acts on",
        )

    inputs = canonical_operation_inputs(
        authority=authority,
        op=op,
        rule_version=rule_version,
        member_refs=members,
        acted_on_episode_ids=acted_on or _implicit_acted_on(op, row),
    )
    operation_id = digest_id(OPERATION_ID_PREFIX, inputs)
    # The derivation is the authority, exactly as it is for `claim_id`
    # (`temporal_claims.validate_temporal_claim`): a create's episode id is a
    # function of its own operation id, and a supplied value that disagrees is
    # replaced rather than believed.
    episode_id = (
        episode_id_for(operation_id) if op == "create" else collapsed_text(row.get("episode_id"))
    )
    _require(
        episode_id and _EPISODE_ID_RE.fullmatch(episode_id),
        "operation_needs_episode",
        f"not an episode id: {row.get('episode_id')!r}",
    )

    destinations: dict[str, str] = {}
    for ref, where in (row.get("destinations") or {}).items():
        telling = validate_telling_ref(ref)
        target = collapsed_text(where)
        _require(
            target == STANDALONE_DESTINATION or bool(_EPISODE_ID_RE.fullmatch(target)),
            "operation_destination_unknown",
            f"a split destination is {STANDALONE_DESTINATION!r} or an episode id; got {where!r}",
        )
        destinations[telling] = target
    if op == "split":
        _require(
            destinations,
            "operation_split_needs_destinations",
            "a split names each departing telling and where it goes",
        )
    if op == "merge":
        _require(
            collapsed_text(row.get("absorbed_episode_id")),
            "operation_merge_needs_absorbed",
            "a merge names the episode it absorbs",
        )

    normalized: dict = {
        "record_type": OPERATION_TYPE,
        "schema_version": int(row.get("schema_version") or SCHEMA_VERSION),
        "operation_id": operation_id,
        "authority": authority,
        "op": op,
        "episode_id": episode_id,
        "members": members,
        "creates_binding_ids": _binding_ids(row.get("creates_binding_ids")),
        "supersedes_binding_ids": _binding_ids(row.get("supersedes_binding_ids")),
        "destinations": dict(sorted(destinations.items())),
        "absorbed_episode_id": _optional_episode_id(row.get("absorbed_episode_id")),
        "aliases_created": sorted(
            dict.fromkeys(
                _episode_id(value) for value in row.get("aliases_created") or () if collapsed_text(value)
            )
        ),
        "canonical_inputs": inputs,
        "canonical_event_kind": collapsed_text(row.get("canonical_event_kind")) or None,
        "status": status,
        "supersedes": _optional_operation_id(row.get("supersedes")),
        "source_ref": collapsed_text(row.get("source_ref")) or None,
        "rule_version": rule_version,
        "created_at": normalized_timestamp(row.get("created_at"), error=EventIdentityError),
    }
    return normalized


def _implicit_acted_on(op: str, row: Mapping[str, object]) -> list[str]:
    """An op that acts on an episode digests that episode even if the caller
    forgot to repeat it in ``acted_on_episode_ids`` — otherwise two adopts of
    two different episodes would collide on one id."""
    if op == "create":
        return []
    found = [collapsed_text(row.get("episode_id"))]
    absorbed = collapsed_text(row.get("absorbed_episode_id"))
    if absorbed:
        found.append(absorbed)
    return [value for value in found if value]


def _binding_ids(values: object) -> list[str]:
    rows = [collapsed_text(value) for value in values or () if collapsed_text(value)]
    for value in rows:
        _require(
            _BINDING_ID_RE.fullmatch(value),
            "identity_binding_id_malformed",
            f"not a binding id: {value!r}",
        )
    return sorted(dict.fromkeys(rows))


def _episode_id(value: object) -> str:
    text = collapsed_text(value)
    _require(_EPISODE_ID_RE.fullmatch(text), "operation_needs_episode", f"not an episode id: {value!r}")
    return text


def _optional_episode_id(value: object) -> str | None:
    return _episode_id(value) if collapsed_text(value) else None


def _optional_operation_id(value: object) -> str | None:
    text = collapsed_text(value)
    if not text:
        return None
    _require(_OPERATION_ID_RE.fullmatch(text), "operation_id_malformed", f"not an operation id: {value!r}")
    return text


def adopted_inputs_view(creation_canonical_inputs: object) -> dict:
    """The creation's own canonical inputs, in the frozen key order.

    Carried on the adopt envelope so an adopted id stays explainable from first
    principles after every cache in the vault is gone — the difference between
    "this id is durable" and "this id is durable and we can still say why".
    """
    inputs = creation_canonical_inputs if isinstance(creation_canonical_inputs, dict) else {}
    return {key: inputs.get(key) for key in OPERATION_IDENTITY_KEYS}


def adopt_envelope(
    *,
    episode_id: object,
    creation_canonical_inputs: object,
    canonical_event_kind: object = None,
    source_ref: object = None,
    created_at: object = None,
) -> dict:
    """The ``adopt`` envelope (design §3.2/G1) — the first human reference.

    The moment a person labels, drags, era-places or answers about a
    deterministic episode, its identity stops being a rule's output and
    becomes durable human authority. Written in the SAME mutation commit as
    the decision it accompanies, and carrying the creation's own
    ``canonical_inputs`` so the adopted id is still explainable from first
    principles after every cache in the vault is gone.

    ``canonical_event_kind`` is CARRIED, not decided (I1). §3.2 records the
    kind at creation and changes it only by a superseding operation, and the
    create envelope lives under ``state/`` where deleting it is a supported
    act — so an adopt that does not carry the kind leaves the surviving
    sources-side records unable to re-derive the episode's NODE id, which is
    the very orphan G1 exists to prevent. It is outside
    :data:`OPERATION_IDENTITY_KEYS`, so carrying it moves no digest.
    """
    record = validate_episode_operation(
        {
            "authority": "human",
            "op": "adopt",
            "episode_id": episode_id,
            "acted_on_episode_ids": [episode_id],
            "canonical_event_kind": canonical_event_kind,
            "source_ref": source_ref,
            "created_at": created_at,
        }
    )
    record["adopted_canonical_inputs"] = adopted_inputs_view(creation_canonical_inputs)
    return record


def file_adopt_envelope(
    vault_root: str | Path,
    *,
    episode_id: object,
    creation_canonical_inputs: object,
    canonical_event_kind: object = None,
    source_ref: object = None,
    created_at: object = None,
) -> tuple[dict, bool]:
    """Build and file the adopt envelope in one call. Replay creates nothing."""
    record = adopt_envelope(
        episode_id=episode_id,
        creation_canonical_inputs=creation_canonical_inputs,
        canonical_event_kind=canonical_event_kind,
        source_ref=source_ref,
        created_at=created_at,
    )
    relative = operation_relative_path(record["authority"], record["operation_id"])
    _write, created = _write_json_record(vault_root, relative, record)
    if not created:
        existing = read_episode_operation(vault_root, relative)
        if existing is not None:
            existing["relative_path"] = relative
            return existing, False
    record["relative_path"] = relative
    return record, created


def is_adopted(vault_root: str | Path, episode_id: object) -> bool:
    """Has a person acted on this episode? (Design §3.2's rule-version rule.)

    An adopted episode is untouched by a new deterministic rule version — the
    new rule may file proposals against it, and may not move it.
    """
    target = collapsed_text(episode_id)
    for record in load_episode_operations(vault_root):
        if record.get("authority") != "human":
            continue
        if record.get("episode_id") == target:
            return True
        if target in (record.get("canonical_inputs") or {}).get("acted_on_episode_ids", ()):
            return True
    return False


def _write_json_record(vault_root: str | Path, relative: str, record: Mapping[str, object]) -> tuple[dict, bool]:
    content = json.dumps(dict(record), indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    try:
        _path, created = store.create_or_keep(vault_root, relative, content)
    except store.TemporalStoreError as exc:
        raise EventIdentityError(
            getattr(exc, "code", "") or "operation_record_unreadable", str(exc)
        ) from exc
    return dict(record), created


def file_episode_operation(vault_root: str | Path, **kwargs: object) -> tuple[dict, bool]:
    """File one envelope. ``(record, created)``; replay creates nothing.

    Canonical-bytes create-or-keep: a second filing of the same semantic
    operation KEEPS the bytes already on disk — including their original
    ``created_at`` — and reports ``created=False``. A retry is later, not
    different.
    """
    record = validate_episode_operation(kwargs)
    relative = operation_relative_path(record["authority"], record["operation_id"])
    _record, created = _write_json_record(vault_root, relative, record)
    if not created:
        existing = read_episode_operation(vault_root, relative)
        if existing is not None:
            existing["relative_path"] = relative
            return existing, False
    record["relative_path"] = relative
    return record, created


def read_episode_operation(vault_root: str | Path, relative: str) -> dict | None:
    text = store.read_store_text(vault_root, relative)
    if text is None:
        return None
    try:
        payload = json.loads(text)
    except (TypeError, ValueError):
        return None
    if not isinstance(payload, dict) or payload.get("record_type") != OPERATION_TYPE:
        return None
    try:
        record = validate_episode_operation(payload)
    except TemporalContractError:
        return None
    for key in ("adopted_canonical_inputs",):
        if key in payload:
            record[key] = payload[key]
    record["relative_path"] = relative
    return record


def load_episode_operations(vault_root: str | Path) -> list[dict]:
    """Every filed envelope, both authorities, in path order."""
    found: list[dict] = []
    for directory in (HUMAN_OPERATIONS_DIR, STATE_OPERATIONS_DIR):
        root = store.store_path(vault_root, directory)
        if not root.is_dir():
            continue
        for path in sorted(root.glob("*.json")):
            record = read_episode_operation(vault_root, f"{directory}/{path.name}")
            if record is not None:
                found.append(record)
    found.sort(key=lambda row: (row["relative_path"], row["operation_id"]))
    return found


# --------------------------------------------------------------------------
# Bindings (C2, design §3.3)
# --------------------------------------------------------------------------


def binding_identity_payload(
    *,
    telling_ref: object,
    episode_id: object,
    relation: object,
    rule_version: object = IDENTITY_RULE_VERSION,
    supersedes: object = None,
) -> dict:
    payload = {
        "telling_ref": collapsed_text(telling_ref),
        "episode_id": collapsed_text(episode_id),
        "relation": collapsed_text(relation),
        "rule_version": collapsed_text(rule_version) or IDENTITY_RULE_VERSION,
        "supersedes": collapsed_text(supersedes) or None,
    }
    return {key: payload[key] for key in IDENTITY_IDENTITY_KEYS}


def binding_digest(**kwargs: object) -> str:
    """``eid:<24 hex>`` over :data:`IDENTITY_IDENTITY_KEYS` and nothing else."""
    return digest_id(BINDING_ID_PREFIX, binding_identity_payload(**kwargs))  # type: ignore[arg-type]


def bindings_dir(origin: object) -> str:
    """Origin decides the directory — and the directory is CERT-11's promise.

    ``stated``/``confirmed`` are a person's decision and live under
    ``sources/``; ``deterministic``/``proposed`` are a rule's output and live
    under ``state/``, where deleting them is a supported act.
    """
    text = collapsed_text(origin)
    _require(text in ORIGINS, "identity_origin_unknown", f"unknown origin: {origin!r}")
    return HUMAN_BINDINGS_DIR if text in HUMAN_ORIGINS else STATE_BINDINGS_DIR


def binding_relative_path(origin: object, identity_id: object) -> str:
    return f"{bindings_dir(origin)}/{_hex24(identity_id)}.json"


def validate_event_identity(value: object) -> dict:
    """Normalize one binding or raise — every refusal named (design §3.3)."""
    _require(isinstance(value, dict) and value, "identity_not_a_mapping", "a binding is a mapping")
    row = dict(value)  # type: ignore[arg-type]
    telling_ref = validate_telling_ref(row.get("telling_ref"))
    episode_id = _episode_id(row.get("episode_id"))
    relation = collapsed_text(row.get("relation"))
    _require(
        relation in BINDING_RELATIONS,
        "identity_relation_unknown",
        f"unknown relation: {row.get('relation')!r}",
    )
    origin = collapsed_text(row.get("origin"))
    _require(origin in ORIGINS, "identity_origin_unknown", f"unknown origin: {row.get('origin')!r}")
    rule_id = collapsed_text(row.get("rule_id")) or None
    # §12b ruling 5 widened this gate by EXACTLY two rule ids and no more. The
    # predicate lives in C1's vocabulary module so the write door and the rung
    # that mints containment records cannot read the ruling differently; the
    # refusal keeps its name, because a `deterministic` `related`, a
    # `deterministic` `not_same`, and a `deterministic` `part_of` under any
    # third rule id are all still the same mistake.
    _require(
        origin != "deterministic" or deterministic_relation_allowed(relation, rule_id),
        "identity_deterministic_relation_unsupported",
        f"a deterministic rung binds {GROUPING_RELATION!r}, and 'part_of' only under "
        f"{list(DETERMINISTIC_CONTAINMENT_RULE_IDS)} (design §4.2, amendment v4.2 §12b.5); "
        f"got relation={relation!r} rule_id={rule_id!r}",
    )
    rule_version = collapsed_text(row.get("rule_version")) or IDENTITY_RULE_VERSION
    supersedes = collapsed_text(row.get("supersedes")) or None
    if supersedes:
        _require(
            _BINDING_ID_RE.fullmatch(supersedes),
            "identity_binding_id_malformed",
            f"not a binding id: {supersedes!r}",
        )
    status = collapsed_text(row.get("status")) or "active"
    _require(status in RECORD_STATUSES, "operation_status_unknown", f"unknown status: {status!r}")

    evidence = row.get("evidence")
    normalized: dict = {
        "record_type": BINDING_TYPE,
        "schema_version": int(row.get("schema_version") or SCHEMA_VERSION),
        "identity_id": binding_digest(
            telling_ref=telling_ref,
            episode_id=episode_id,
            relation=relation,
            rule_version=rule_version,
            supersedes=supersedes,
        ),
        "telling_ref": telling_ref,
        "claim_ids_at_bind": sorted(
            dict.fromkeys(
                collapsed_text(value) for value in row.get("claim_ids_at_bind") or () if collapsed_text(value)
            )
        ),
        "episode_id": episode_id,
        "relation": relation,
        "origin": origin,
        "rule_version": rule_version,
        "rule_id": rule_id,
        "evidence": evidence if isinstance(evidence, dict) else {},
        "candidates": sorted(
            dict.fromkeys(
                _episode_id(value) for value in row.get("candidates") or () if collapsed_text(value)
            )
        ),
        "telling_aliases": sorted(
            dict.fromkeys(
                validate_telling_ref(value)
                for value in row.get("telling_aliases") or ()
                if collapsed_text(value)
            )
        ),
        "operation_id": _optional_operation_id(row.get("operation_id")),
        "source_ref": collapsed_text(row.get("source_ref")) or None,
        "status": status,
        "supersedes": supersedes,
        "created_at": normalized_timestamp(row.get("created_at"), error=EventIdentityError),
    }
    return normalized


def file_event_identity(vault_root: str | Path, **kwargs: object) -> tuple[dict, bool]:
    """File one binding. ``(record, created)``.

    Canonical-bytes create-or-keep (audit A6): meeting an existing record with
    the same digest KEEPS the existing bytes and REPORTS, never overwrites —
    so a re-derivation cannot quietly restamp a decision's evidence or its
    clock. Re-deciding is a new record with ``supersedes``.
    """
    record = validate_event_identity(kwargs)
    relative = binding_relative_path(record["origin"], record["identity_id"])
    _record, created = _write_json_record(vault_root, relative, record)
    if not created:
        existing = read_event_identity(vault_root, relative)
        if existing is not None:
            existing["relative_path"] = relative
            return existing, False
    record["relative_path"] = relative
    return record, created


def read_event_identity(vault_root: str | Path, relative: str) -> dict | None:
    text = store.read_store_text(vault_root, relative)
    if text is None:
        return None
    try:
        payload = json.loads(text)
    except (TypeError, ValueError):
        return None
    if not isinstance(payload, dict) or payload.get("record_type") != BINDING_TYPE:
        return None
    try:
        record = validate_event_identity(payload)
    except TemporalContractError:
        return None
    record["relative_path"] = relative
    return record


def load_event_identities(vault_root: str | Path) -> list[dict]:
    """Every filed binding, both directories, in path order."""
    found: list[dict] = []
    for directory in (HUMAN_BINDINGS_DIR, STATE_BINDINGS_DIR):
        root = store.store_path(vault_root, directory)
        if not root.is_dir():
            continue
        for path in sorted(root.glob("*.json")):
            record = read_event_identity(vault_root, f"{directory}/{path.name}")
            if record is not None:
                found.append(record)
    found.sort(key=lambda row: (row["relative_path"], row["identity_id"]))
    return found


def binding_semantic_key(record: object) -> tuple[str, str, str]:
    """``(telling_ref, episode_id, relation)`` — what two directories may not
    both hold ACTIVE at once."""
    row = record if isinstance(record, dict) else {}
    return (
        collapsed_text(row.get("telling_ref")),
        collapsed_text(row.get("episode_id")),
        collapsed_text(row.get("relation")),
    )


def validate_identity_set(records: Sequence[object]) -> list[dict]:
    """The origin-transition rule and the one-decision rule, together.

    Design §3.3: a ``proposed → confirmed`` transition files the sources-side
    record WITH ``supersedes`` naming the state-side proposal, *so identical
    semantic keys in two directories are never two active authorities*. An
    unsuperseded twin is a refusal, not a recency contest — the same reasoning
    `event_binding.event_resolution_index` uses when two writers disagree
    about what a sentence meant.

    The second refusal is §5.4's: two ACTIVE bindings for one telling with no
    ``supersedes`` between them is ``identity_conflict``, never a silent pick.
    """
    parsed: list[dict] = []
    for record in records or ():
        row = record if isinstance(record, dict) else {}
        if not row:
            continue
        if row.get("record_type") not in (None, BINDING_TYPE):
            continue
        parsed.append(validate_event_identity(row))
    superseded = {row["supersedes"] for row in parsed if row["supersedes"]}
    active = [
        row
        for row in parsed
        if row["status"] == "active" and row["identity_id"] not in superseded
    ]

    by_semantic: dict[tuple[str, str, str], list[dict]] = {}
    for row in active:
        by_semantic.setdefault(binding_semantic_key(row), []).append(row)
    for key, rows in sorted(by_semantic.items()):
        if len(rows) < 2:
            continue
        origins = {row["origin"] for row in rows}
        code = (
            "identity_unsuperseded_twin"
            if origins & set(HUMAN_ORIGINS) and origins & set(MACHINE_ORIGINS)
            else "identity_conflict"
        )
        raise EventIdentityError(
            code,
            f"{key[0]} → {key[1]} ({key[2]}) is asserted by {len(rows)} active records "
            "and none supersedes another",
            detail={
                "telling_ref": key[0],
                "episode_id": key[1],
                "relation": key[2],
                "identity_ids": sorted(row["identity_id"] for row in rows),
                "origins": sorted(origins),
            },
        )

    # §5.4's telling-level refusal is about GROUPING and nothing else — the
    # narrow reading `episode_fold_contract`'s own comment pinned at I0 and
    # `active_binding_index` has always implemented. I0's C2 half read
    # `part_of` into it as well, and the two halves of one contract disagreed
    # in silence until a containment rung actually minted a second membership.
    #
    # **Amendment v4.2 settles it toward the narrow reading**, and not as a
    # convenience: §13.5 promises in so many words that *"a member of two
    # containers renders in both with one primary display decision"*, which is
    # the eras program's own paradigm — a membership is a RECEIPT, not a
    # bound; an event may belong to several stretches; the display role a
    # person picks is a separate decision that never destroys a secondary
    # membership. A telling still belongs to at most ONE episode by `same`:
    # that is the identity collapse the whole floor exists to protect, and it
    # is unchanged. Containment is not identity.
    by_telling: dict[str, list[dict]] = {}
    for row in active:
        if row["relation"] == GROUPING_RELATION:
            by_telling.setdefault(row["telling_ref"], []).append(row)
    for telling_ref, rows in sorted(by_telling.items()):
        if len(rows) < 2:
            continue
        raise EventIdentityError(
            "identity_conflict",
            f"{telling_ref} carries {len(rows)} active `{GROUPING_RELATION}` bindings "
            "and none supersedes another; a telling belongs to one episode or to none",
            detail={
                "telling_ref": telling_ref,
                "identity_ids": sorted(row["identity_id"] for row in rows),
            },
        )
    return active


# --------------------------------------------------------------------------
# The envelope — atomic, or a loud refusal (design §3.2/G4)
# --------------------------------------------------------------------------


def validate_envelope(operation: object, bindings: Sequence[object]) -> dict:
    """The envelope's own integrity: every named record present, members honest.

    Two refusals, both loud:

    * ``identity_envelope_incomplete`` — the envelope names a binding id that
      is not among the records supplied. A partially applied episode is the
      one outcome §3.2 will not have, so a reader that finds half of one stops
      rather than folding what it can see.
    * ``identity_members_disagree`` — ``members`` is an audit copy, and an
      audit copy that has drifted from the bindings it claims to summarize is
      exactly the two-authorities defect (F2) wearing a validator's coat.
    """
    record = validate_episode_operation(operation)
    supplied = {}
    for binding in bindings or ():
        row = validate_event_identity(binding)
        supplied[row["identity_id"]] = row
    named = list(record["creates_binding_ids"]) + list(record["supersedes_binding_ids"])
    missing = sorted({value for value in named if value not in supplied})
    _require(
        not missing,
        "identity_envelope_incomplete",
        f"{record['operation_id']} names {len(missing)} binding record(s) that are not "
        "present; an incomplete envelope is never partially applied",
        operation_id=record["operation_id"],
        missing_binding_ids=missing,
    )
    if record["op"] in ("create", "merge"):
        created = sorted(
            {supplied[value]["telling_ref"] for value in record["creates_binding_ids"]}
        )
        _require(
            created == record["members"],
            "identity_members_disagree",
            f"{record['operation_id']} lists {record['members']} as members but its "
            f"bindings name {created}",
            operation_id=record["operation_id"],
            members=record["members"],
            binding_tellings=created,
        )
    if record["op"] == "split":
        departing = sorted(
            {supplied[value]["telling_ref"] for value in record["supersedes_binding_ids"]}
        )
        _require(
            departing == sorted(record["destinations"]),
            "operation_split_needs_destinations",
            f"{record['operation_id']} supersedes bindings for {departing} but routes "
            f"{sorted(record['destinations'])}",
            operation_id=record["operation_id"],
        )
    return {"operation": record, "bindings": [supplied[key] for key in sorted(supplied)]}


def load_operation_envelope(vault_root: str | Path, operation: object) -> dict:
    """Read one envelope back off disk, refusing loudly if it is incomplete."""
    record = validate_episode_operation(operation)
    found: list[dict] = []
    by_id = {row["identity_id"]: row for row in load_event_identities(vault_root)}
    named = list(record["creates_binding_ids"]) + list(record["supersedes_binding_ids"])
    missing = sorted({value for value in named if value not in by_id})
    _require(
        not missing,
        "identity_envelope_incomplete",
        f"{record['operation_id']} names {len(missing)} binding record(s) that are not on "
        "disk; an incomplete envelope is a refusal, never a partial episode",
        operation_id=record["operation_id"],
        missing_binding_ids=missing,
    )
    for value in sorted(set(named)):
        found.append(by_id[value])
    return validate_envelope(record, found)


def file_operation_envelope(
    vault_root: str | Path,
    *,
    operation: Mapping[str, object],
    bindings: Sequence[Mapping[str, object]] = (),
) -> dict:
    """File an envelope's bindings and then its operation, in that order.

    Order is the point. The operation is the only record anything reads to
    find an envelope, so writing it LAST means a process that dies half way
    leaves bindings nobody has been told about — inert — rather than an
    operation that promises records the vault does not hold. The atomic
    one-commit guarantee is the mutation seat's; this ordering is what makes a
    crash inside the seat recoverable rather than corrupting, and
    :func:`load_operation_envelope` is the loud refusal for the case the seat
    could not save.
    """
    filed: list[dict] = []
    created_any = False
    for binding in bindings or ():
        record, created = file_event_identity(vault_root, **dict(binding))
        filed.append(record)
        created_any = created_any or created
    operation_record, operation_created = file_episode_operation(vault_root, **dict(operation))
    validate_envelope(operation_record, filed)
    return {
        "operation": operation_record,
        "bindings": filed,
        "created": operation_created or created_any,
        "operation_created": operation_created,
    }


#: Everything a re-run legitimately re-stamps. The clock is ANNOTATION — it is
#: outside :data:`OPERATION_IDENTITY_KEYS` and :data:`IDENTITY_IDENTITY_KEYS`
#: for the same reason `temporal_store._assertion_view` drops it from a
#: receipt comparison: a retry is later, not different, and treating a second
#: elapsed second as a changed decision turns idempotency into corruption.
ANNOTATION_KEYS = ("created_at", "relative_path")


def identity_assertion_view(record: object) -> dict:
    """What a record ASSERTS, with every clock and path removed.

    The comparison the G1 release promise is actually about: delete all
    deterministic identity state, re-run on identical durable inputs, and
    every id — and everything that is not a timestamp — comes back the same.
    """
    row = dict(record) if isinstance(record, dict) else {}
    return {key: value for key, value in row.items() if key not in ANNOTATION_KEYS}


__all__ = [
    "ANNOTATION_KEYS",
    "AUTHORITIES",
    "BINDING_DIGEST_DOMAIN",
    "BINDING_ID_PREFIX",
    "BINDING_TYPE",
    "CONVERSATION_TELLING_PREFIX",
    "CLASSIFIER_TELLING_PREFIX",
    "CORRECTION_DIAGNOSTIC",
    "DOCUMENT_REVISION_FIELD",
    "EPISODE_DIGEST_DOMAIN",
    "EPISODE_ID_PREFIX",
    "EVENT_IDENTITY_ERROR_CODES",
    "EventIdentityError",
    "FRAGMENT_DIAGNOSTIC",
    "BINDING_RELATIONS",
    "GROUPING_ORIGINS",
    "GROUPING_RELATION",
    "HUMAN_BINDINGS_DIR",
    "HUMAN_OPERATIONS_DIR",
    "HUMAN_ORIGINS",
    "IDENTITY_IDENTITY_KEYS",
    "IDENTITY_INDEX_FILE",
    "IDENTITY_RULE_VERSION",
    "IDENTITY_SOURCES_DIR",
    "IDENTITY_STATE_DIR",
    "INELIGIBLE_TELLING_IS_AN_ERA",
    "LANDMARK_TELLING_PREFIX",
    "MACHINE_ORIGINS",
    "MANIFEST_DIAGNOSTICS",
    "MANIFEST_SCHEMA_VERSION",
    "MIN_SIGNATURE_AGREEMENT",
    "OPERATIONS",
    "OPERATION_DIGEST_DOMAIN",
    "OPERATION_ID_PREFIX",
    "OPERATION_IDENTITY_KEYS",
    "OPERATION_TYPE",
    "ORIGINS",
    "OWNER_SUBJECT_KEYS",
    "RECORDER_EVENT_ID_FIELD",
    "RECORD_STATUSES",
    "REKEY_CASES",
    "REKEY_DIAGNOSTIC",
    "REKEY_EVIDENCE_KINDS",
    "REKEY_OUTCOMES",
    "RELATIONS",
    "SIGNATURE_COMPONENTS",
    "SPLIT_DEPARTURE_RELATION",
    "STANDALONE_DESTINATION",
    "STATE_BINDINGS_DIR",
    "STATE_OPERATIONS_DIR",
    "TELLING_KEYS_FIELD",
    "TELLING_MANIFEST_FILE",
    "TELLING_ROW_KEYS",
    "TELLING_SOURCE_KINDS",
    "TELLING_TRANSITIONS",
    "TellingTransition",
    "UNDECLARED_DOCUMENT_REVISION",
    "adopt_envelope",
    "adopted_inputs_view",
    "assert_one_event_identity",
    "binding_digest",
    "binding_identity_payload",
    "binding_relative_path",
    "binding_semantic_key",
    "bindings_dir",
    "build_telling_manifest",
    "canonical_operation_inputs",
    "classifier_telling_ref",
    "compare_signatures",
    "conversation_telling_ref",
    "declare_tellings",
    "episode_id_at_rule_version",
    "episode_id_for",
    "event_identities_in",
    "file_adopt_envelope",
    "file_episode_operation",
    "file_event_identity",
    "file_operation_envelope",
    "identity_assertion_view",
    "is_adopted",
    "landmark_telling_ref",
    "load_episode_operations",
    "load_event_identities",
    "load_operation_envelope",
    "operation_digest",
    "operation_relative_path",
    "operations_dir",
    "read_episode_operation",
    "read_event_identity",
    "read_telling_manifest",
    "rebuild_telling_manifest",
    "rekey_evidence",
    "split_telling_ref",
    "telling_is_about_an_era",
    "telling_locator",
    "telling_manifest_bytes",
    "telling_ref_for_claim",
    "telling_signature",
    "telling_source_kind",
    "transition_for",
    "validate_envelope",
    "validate_episode_operation",
    "validate_event_identity",
    "validate_identity_set",
    "validate_telling_ref",
    "write_telling_manifest",
]
