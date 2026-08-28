#!/usr/bin/env python3
"""The calculated timeline: pure, whole, explainable (wave D, items D1 + D2).

``temporal_claims`` froze what a temporal interpretation *is*; ``temporal_store``
put it on disk so the active set can be rebuilt from its evidence;
``identity_resolution`` answered who a mention is and which episode a claim
belongs to. This module is the step those three were building toward — the one
that turns a pile of claims into **the chronology a person sees**, and into the
typed questions that chronology still wants answered.

It is a **whole projection**, not an incremental one. The audited final timeline
build plan is explicit about this (§1.2, §7, §7.1): build a correct, pure, full
derivation backed by versioned evidence and stable semantic identities; keep the
stable node ids, the input edges and the fingerprints that make incremental
recomputation *possible*; and do **not** put a persisted node-level
dirty/invalidation scheduler on the critical path. There is no dirty-node
scheduler here, and adding one is gated on measurement (§7.1) rather than on
taste. :func:`derive_calculated_timeline` returns its own phase timings so that
gate has a number from the first day rather than an argument.

The pipeline, in the order it runs
----------------------------------

1. **Active claims.** The claims whose status is ``active`` in the folded index
   — the losing interpretations are still on disk, and this projection simply
   does not calculate from them.
2. **Identity and episode resolution.** ``identity_resolution``'s deterministic
   layers, taken as *records* the caller may supply or as a resolution run
   against a roster snapshot. An uncertain mention is never dropped: it keeps
   its claim, and it becomes an ``identity_uncertain`` work item (§6.3, §2.5).
3. **Grouping.** Claims about the same subject's same event become one node.
   Episode *splitting* is the recorder's job, not the fold's — see "Two stints"
   below.
4. **Reconciliation.** ``chronology.reconcile`` per node, in the pure
   derivation and never as a mutating write authority (§6.5). The best-supported
   value is what Timeline shows; every rival survives as an alternate; the
   conflict strength is what mints a Mirror row.
5. **Interval and partial-order calculation.** Exact dates pass through. Ages
   and durations become intervals *only where an anchor exists*.
   ``relative_order`` claims and ``OrderingConstraint``s (the drag's semantic
   residue) narrow intervals through a bounded fixpoint. An order cycle emits a
   contradiction and never hangs.
6. **Work items.** Typed instances of one shape — missing anchors, precision
   gaps, contradictions, uncertain identities — carrying one stable id across
   Timeline, Mirror, whispers and the daily queue (§5.4, §2.3).

What this module refuses to do
------------------------------

**It never renders false precision.** An inferred interval is an interval. §10's
case is verbatim: *"I was about 12"* produces a fuzzy interval with a calibrated
basis, not an exact birthday-derived day. The conversion from a
:class:`~temporal_claims.TemporalQuantity` to a calendar interval lives here —
where the anchor is known — exactly as v220 intended when it refused to let a
fabricated interval reach storage at claim time.

**It never erases disagreement.** Two incompatible explicit dates are both
preserved; Timeline shows the best-supported one and signals the conflict; a
``contradiction`` work item names both claims. An unresolved contradiction
blocks nothing else — every other node is calculated exactly as it would have
been (§2.5, §10).

**It never invents an episode split.** *Two stints at the same employer are two
episodes* (§6.3) — and what makes them two is the recorder minting two
``event_ref``s through :func:`identity_resolution.derive_episode_ref` at capture
time. When claims arrive with no ``event_ref``, nothing in them distinguishes a
second stint from a disagreement about the first, so the fold groups them as one
node with alternates and a visible conflict rather than guessing. Guessing would
be a silent merge on one side and a silent split on the other; showing the
disagreement is correctable, and a stable node id is what makes the correction
land.

**It never writes anything.** No I/O, no model, no vault, no clock it did not
receive except the two the caller may pass (``now`` for work-item stamps) and
``time.perf_counter`` for the timings, which §7 names as *explicitly excluded
runtime metadata*. :func:`structural_signature` is the comparison key that
excludes them, so "rebuild twice and compare" is a real test rather than a
slogan.

Where this connects
-------------------

``timeline.timeline_data()`` consuming this projection is the wiring PR, and is
deliberately not here — this module exports clean entry points and touches no
existing derivation. Publication of the whole projection (§7's atomic
generation swap) is likewise its own step; what this module owns is the pure
function from evidence to chronology.

Controlling contract: the audited final timeline build plan §5.3, §5.4, §6.4,
§6.5, §7, §7.1, §8.5, §10, and owner amendments 1 and 2 (2026-08-26).
"""

from __future__ import annotations

import sys
import time
from dataclasses import dataclass, field, replace
from pathlib import Path

SYSTEM_DIR = Path(__file__).resolve().parent
if str(SYSTEM_DIR) not in sys.path:
    sys.path.insert(0, str(SYSTEM_DIR))

import birth_origin as bo  # noqa: E402
import chronology as chrono  # noqa: E402
import cross_dating as cd  # noqa: E402
import event_binding as eb
import identity_resolution as ident  # noqa: E402
import temporal_claims as tc  # noqa: E402
import temporal_projection as tp  # noqa: E402
from temporal_claims import (  # noqa: E402
    TemporalContractError,
    collapsed_text,
    normalized_mention_key,
    optional_text,
)

# --------------------------------------------------------------------------
# Versioned rules
# --------------------------------------------------------------------------

#: Stamped on every node as ``calculation_rule_version`` and folded into every
#: input fingerprint. Bump it whenever a rule in this module changes what the
#: same claims calculate to — that is what makes a stale projection detectable
#: rather than merely wrong (§5.3, §7).
#:
#: ``timeline-rules:2`` (eras E1): the fold mints ``period`` nodes for the age
#: frames, so the same claims now calculate to a strictly larger projection.
CALCULATION_RULE_VERSION = "timeline-rules:2"

#: The combined-score formula's own version, separate from the rules above
#: because scoring is recalibrated on a different cadence from the arithmetic.
#: **The weights below are deliberately simple and deliberately uncalibrated.**
#: Wave F owns calibration (§8.5); what wave D owes it is the raw components and
#: one stable identity per item, both of which are here.
SCORE_FORMULA_VERSION = "temporal-score:1"

#: How hard two surviving claims must contradict each other before the node is
#: ``contradicted`` and Mirror gets a row. ``chronology.conflict_strength``
#: returns how well supported the best *disjoint* rival is relative to the
#: winner, so ``0.5`` means "a rival at least half as well supported as the
#: claim we are showing". Below it the node is ``alternatives``: the reading is
#: divided, but not materially so.
MATERIAL_CONFLICT = 0.5

#: The bounded fixpoint's round cap. Narrowing is monotone so the fixpoint
#: converges long before this; the cap exists so that a rule change can never
#: turn a derivation into a hang, and reaching it is reported in
#: ``diagnostics`` rather than swallowed.
MAX_PROPAGATION_ROUNDS = 16

#: Reach saturates: an anchor that would place five unplaced nodes is already
#: as valuable as this release knows how to say. The raw count travels in
#: :attr:`CalculatedTimeline.reach` for wave F to calibrate against.
REACH_SATURATION = 5

#: The precision an event's date is worth asking to (§2.2 — *ask at the
#: precision appropriate to the event*, never demand false precision). Anything
#: not named here targets :data:`DEFAULT_PRECISION_TARGET`, and a node already
#: at or finer than its target mints no gap at all.
PRECISION_TARGETS = {
    "birth": "day",
    "death": "day",
    "married": "day",
    "child_born": "day",
    "first_met": "month",
    "dating_started": "month",
    "graduation": "month",
}
DEFAULT_PRECISION_TARGET = "year"

#: Coarsest first — the same ordering ``chronology.GRANULARITIES`` uses, read
#: from it rather than re-listed, so a new granularity cannot drift.
_GRANULARITY_RANK = {name: index for index, name in enumerate(chrono.GRANULARITIES)}

#: Loss is offer-only (§2.4). A temporal question about a loss whose subject is
#: not a specific named person is discovery, and discovery never enters the
#: daily queue. Once the person names who died, the ordinary surfaces apply.
LOSS_EVENT_KINDS = ("loss", "death")

#: Where each kind of work may appear. ``timeline`` is universal — Timeline is
#: the place a person voluntarily visits to improve the portrait, and an open
#: item there is an invitation rather than a debt (§2.3, §8.1).
SURFACES_BY_KIND = {
    "missing_anchor": ("timeline", "whisper", "daily_question"),
    "precision_gap": ("timeline", "whisper", "daily_question"),
    "contradiction": ("timeline", "mirror"),
    "identity_uncertain": tuple(ident.IDENTITY_WORK_SURFACES),
}

#: Surfaces a loss-discovery item may use. Timeline only: the system may OFFER
#: the Losses area, and must not put a generic loss prompt in the queue.
LOSS_DISCOVERY_SURFACES = ("timeline",)

#: Per-kind starting points for the §8.5 components this release can state
#: deterministically. ``system_value`` is *not* here: it is calculated from
#: reach and conflict severity, which is the whole point of computing it in the
#: derivation rather than guessing it at selection time.
WORK_ITEM_VALUE_DEFAULTS = {
    "missing_anchor": {"person_value": 0.5, "interaction_cost": 0.3, "context_fit": 0.5},
    "precision_gap": {"person_value": 0.45, "interaction_cost": 0.2, "context_fit": 0.5},
    "contradiction": {"person_value": 0.6, "interaction_cost": 0.5, "context_fit": 0.4},
    "identity_uncertain": {"person_value": 0.5, "interaction_cost": 0.4, "context_fit": 0.4},
}

#: How sensitive asking about this event is, before any per-person signal. A
#: death or a loss is not a neutral date question and never scores like one.
SENSITIVITY_BY_EVENT_KIND = {
    "death": 0.8,
    "loss": 0.8,
    "separated": 0.6,
    "divorced": 0.6,
}
DEFAULT_SENSITIVITY = 0.1

#: The uncalibrated weights of :data:`SCORE_FORMULA_VERSION`. Positive terms are
#: reasons to ask; negative terms are reasons to wait.
SCORE_WEIGHTS = {
    "person_value": 0.35,
    "system_value": 0.35,
    "context_fit": 0.15,
    "interaction_cost": -0.15,
    "sensitivity": -0.20,
}

#: The vault owner's handle in a relationship edge. *"I married Katie"* is a
#: fact about the edge between two people (§6.3), and the edge needs both ends;
#: callers with a real owner entity ref pass ``owner_ref=`` and get that.
DEFAULT_OWNER_REF = "self"

#: The phases §7.1 asks to instrument *within* the pure derivation. Extraction,
#: the claim fold and projection publication are measured by their own owners;
#: what this module can honestly report is what it does.
TIMING_PHASES = ("resolve", "group", "reconcile", "propagate", "age_frames", "work_items", "total")

#: The highest ``chronology.claim_score`` any single claim can reach, computed
#: from chronology's own weights so the normalizer cannot drift from them.
MAX_CLAIM_SCORE = (
    max(chrono.BASIS_WEIGHT.values())
    + max(chrono.CONFIDENCE_WEIGHT.values())
    + chrono.MAX_CONSILIENCE_SOURCES * chrono.CONSILIENCE_WEIGHT
)

class TemporalTimelineError(TemporalContractError):
    """A derivation could not proceed on the inputs it was given."""


#: Every finding this module raises or reports, in one place (the substrate's
#: convention). ``derivation_*`` are raised; the rest are diagnostic keys.
ERROR_CODES = (
    "active_index_unusable",
    "propagation_cap_reached",
    "order_cycle",
    "anchor_unresolved",
    "anchor_undated",
    "age_without_birth_anchor",
    "duration_without_start",
    "constraint_contradicts_date",
    "quantity_band_unrepresentable",
)


# --------------------------------------------------------------------------
# The result
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class CalculatedTimeline:
    """One whole projection, plus what it noticed on the way.

    Unpacks as ``nodes, work_items = derive_calculated_timeline(...)`` because
    those two are the contract; the rest is what wave E, wave F and wave H each
    need and would otherwise have to recompute.

    ``timings`` and the work items' ``created_at``/``updated_at`` are §7's
    *explicitly excluded runtime metadata* — :func:`structural_signature` is the
    comparison key that drops them.
    """

    nodes: tuple[dict, ...] = ()
    work_items: tuple[dict, ...] = ()
    #: Calculated memberships (eras design §2.2). The KEY lands in E1 so a
    #: tolerant reader is written once; E2 fills the rows.
    memberships: tuple[dict, ...] = ()
    timings: dict = field(default_factory=dict)
    score_components: dict = field(default_factory=dict)
    reach: dict = field(default_factory=dict)
    diagnostics: dict = field(default_factory=dict)
    calculation_rule_version: str = CALCULATION_RULE_VERSION
    score_formula_version: str = SCORE_FORMULA_VERSION
    projection_generation: int = 0

    def __iter__(self):
        yield self.nodes
        yield self.work_items

    def node(self, node_id: object) -> dict | None:
        """One node by id — the lookup every surface would otherwise re-write."""
        wanted = collapsed_text(node_id)
        for row in self.nodes:
            if row.get("node_id") == wanted:
                return row
        return None

    def to_dict(self) -> dict:
        return {
            "calculation_rule_version": self.calculation_rule_version,
            "score_formula_version": self.score_formula_version,
            "projection_generation": self.projection_generation,
            "nodes": [dict(row) for row in self.nodes],
            "work_items": [dict(row) for row in self.work_items],
            "memberships": [dict(row) for row in self.memberships],
            "reach": dict(self.reach),
            "score_components": {k: dict(v) for k, v in self.score_components.items()},
            "diagnostics": dict(self.diagnostics),
        }


def structural_signature(result: object) -> dict:
    """The projection minus its runtime metadata — the rebuild oracle's key.

    §7: *"Rebuilding twice from identical receipts, corrections, rules, and
    versions produces structurally identical output apart from explicitly
    excluded runtime metadata."* This function names the exclusions rather than
    leaving each caller to guess them: the phase timings, and the wall-clock
    stamps a work item carries because a queue needs them.
    """
    current = result if isinstance(result, CalculatedTimeline) else None
    if current is None:
        raise TemporalTimelineError(
            "active_index_unusable", "structural_signature takes a CalculatedTimeline"
        )
    items = []
    for row in current.work_items:
        trimmed = {k: v for k, v in row.items() if k not in ("created_at", "updated_at")}
        items.append(trimmed)
    return {
        "calculation_rule_version": current.calculation_rule_version,
        "score_formula_version": current.score_formula_version,
        "nodes": [dict(row) for row in current.nodes],
        "work_items": items,
        "memberships": [dict(row) for row in current.memberships],
        "reach": dict(current.reach),
        "diagnostics": dict(current.diagnostics),
    }


# --------------------------------------------------------------------------
# Reading the substrate
# --------------------------------------------------------------------------


def active_claim_rows(active_index: object) -> list[dict]:
    """The claims a projection may calculate from — ``status: active``, id-ordered.

    Accepts the folded index mapping (``temporal_store.fold_active_index``'s
    return), its ``claims`` list, or a bare list of claim mappings, because the
    hosted platform reads the published file and a test builds the list by hand
    and both are the same question.

    This is deliberately the *same predicate* as
    ``temporal_store.active_claims``; ``tests/test_temporal_timeline.py`` pins
    the two against each other rather than trusting the coincidence, which is
    what the recurring-defect doctrine asks for when one fact has two readers.
    """
    rows = active_index
    if isinstance(active_index, dict):
        rows = active_index.get("claims")
    if isinstance(rows, dict) or rows is None:
        rows = ()
    if not isinstance(rows, (list, tuple)):
        raise TemporalTimelineError(
            "active_index_unusable", f"cannot read claims from {type(active_index).__name__}"
        )
    active = [row for row in rows if isinstance(row, dict) and row.get("status") == "active"]
    return sorted(active, key=lambda row: collapsed_text(row.get("claim_id")))


def _source_key(claim: dict) -> str:
    """``source_id@revision`` — the evidence handle a work item cites."""
    ref = claim.get("source_ref")
    if not isinstance(ref, dict):
        return ""
    return f"{collapsed_text(ref.get('source_id'))}@{collapsed_text(ref.get('revision'))}"


def _subject_handle(claim: dict) -> str:
    """The resolved ref when identity landed, the raw mention when it did not.

    §2.5's "never dropped" has to survive exactly where identity is hardest, so
    an unresolved subject still carries its events. The raw mention remains on
    the claim either way — resolution is data *about* a claim, never an edit of
    one.
    """
    return collapsed_text(claim.get("subject_ref")) or collapsed_text(
        claim.get("subject_mention")
    )


def _node_kind_for(event_kind: object) -> str:
    """``period`` for a stretch of life, ``episode`` for a repeat, else ``event``.

    ``period`` arrives with eras E1: an age frame is a stretch of the life
    axis, not a thing that happened, and `temporal_projection.NODE_KINDS` has
    declared the kind since the substrate landed while nothing ever minted it.
    The event kinds that mean "period" are read from
    :data:`~temporal_projection.PERIOD_EVENT_KINDS` rather than listed here, so
    E3's ``named_era`` needs no second edit.

    The other two are read off ``identity_resolution``'s own two predicates so
    this module and :func:`identity_resolution.derive_episode_ref` cannot
    disagree about a node id's own payload — ``node_kind`` is *inside* the
    digest, so a disagreement here would silently mint two ids for one thing.
    """
    if collapsed_text(event_kind) in tp.PERIOD_EVENT_KINDS:
        return "period"
    if ident.is_relationship_event(event_kind) or ident.is_repeatable_event(event_kind):
        return "episode"
    return "event"


def _mint_node_id(*, event_kind: str, subject: str, owner_ref: str) -> str:
    """The node id for a subject's event, through the substrate's one minter.

    Relationship transitions go through :func:`~identity_resolution.derive_episode_ref`
    with the owner as counterpart, so *"married Katie"* attaches to the edge
    between the two people and gives the same id whichever end is named the
    subject. A repeatable kind arriving with no ``event_ref`` and therefore no
    discriminator is refused by that function — correctly, because minting one
    would be a guess — so this falls back to the undiscriminated node id and the
    fold shows the claims as one node with alternates. See the module docstring,
    "It never invents an episode split".
    """
    relationship = ident.is_relationship_event(event_kind)
    try:
        return ident.derive_episode_ref(
            event_kind=event_kind,
            subject_ref=subject,
            counterpart_ref=owner_ref if relationship else None,
        )
    except ident.IdentityResolutionError:
        subjects = [subject, owner_ref] if relationship else [subject]
        return tp.derive_node_id(
            node_kind=_node_kind_for(event_kind),
            event_kind=event_kind,
            subject_refs=subjects,
        )


# --------------------------------------------------------------------------
# Identity, applied
# --------------------------------------------------------------------------


def _resolution_index(records: object) -> dict:
    """Resolution records by mention key, latest-per-key, deterministically.

    A caller may hand over a ledger holding several decisions about one mention
    (a resolution, its reversal, a later owner verdict). The one that counts is
    the last by ``created_at``, ties broken by the record's own reason so the
    answer never depends on list order.
    """
    index: dict[str, dict] = {}
    for value in records or ():
        record = value if isinstance(value, ident.ResolutionRecord) else ident.record_from_dict(value)
        if record is None:
            continue
        key = record.mention_key or normalized_mention_key(record.mention)
        current = index.get(key)
        if current is None or (record.created_at, record.reason) >= (
            current["record"].created_at,
            current["record"].reason,
        ):
            index[key] = {"record": record}
    return {key: value["record"] for key, value in index.items()}


def _resolve_subjects(
    claims, *, resolution_records, roster_snapshot, now, owner_ref: object = None
):
    """Attach identity to every claim, keeping the ones that will not resolve.

    Four layers, in order, each of them ``identity_resolution``'s and none of
    them re-implemented here:

    1. a claim that already carries ``subject_ref`` is left alone — the recorder
       resolved it, and re-deciding would make the projection disagree with the
       evidence;
    2. a supplied :class:`~identity_resolution.ResolutionRecord` for the
       mention wins next, because it may carry a model rung's or an owner's
       verdict that no deterministic rule can reach;
    3. a legacy birth landmark whose subject is the DOMAIN WORD resolves to the
       owner through :func:`~identity_resolution.owner_birth_domain_resolution`
       (design §3.1). The rule is narrow by construction — the word *and* the
       birth event kind — and it produces a record, not an edit, so the receipt
       still says what it said and the mapping can be reversed;
    4. otherwise the deterministic resolver runs against the roster snapshot.

    Layers 3 and 4 keep SEPARATE caches on purpose. They are both keyed by
    mention, and a vault holding both a birth claim and some other claim that
    happens to say "birth" would otherwise answer whichever arrived first —
    an order-dependent identity, which is the one thing this fold promises
    never to have. The returned mapping prefers the rule's record for such a
    key because it is the more specific of the two.

    Returns ``(resolved_claims, records_by_mention_key, claim_ids_by_mention_key)``.
    The third is what turns one ambiguous mention into ONE Mirror row citing
    every claim that ever said it (§5.4's answer-once).
    """
    owner = collapsed_text(owner_ref) or DEFAULT_OWNER_REF
    supplied = _resolution_index(resolution_records)
    rule_records: dict[str, ident.ResolutionRecord] = {}
    roster_records: dict[str, ident.ResolutionRecord] = {}
    by_mention: dict[str, list[str]] = {}
    resolved: list[dict] = []

    for claim in claims:
        mention = collapsed_text(claim.get("subject_mention"))
        key = normalized_mention_key(mention)
        by_mention.setdefault(key, []).append(collapsed_text(claim.get("claim_id")))
        if collapsed_text(claim.get("subject_ref")):
            resolved.append(claim)
            continue
        evidence_ref = _source_key(claim) or collapsed_text(claim.get("claim_id"))
        record = supplied.get(key)
        if record is None and ident.is_owner_birth_domain_word(
            mention, claim.get("event_kind")
        ):
            record = rule_records.get(key)
            if record is None:
                record = ident.owner_birth_domain_resolution(
                    mention, owner_ref=owner, evidence_ref=evidence_ref, now=now
                )
                rule_records[key] = record
        if record is None:
            record = roster_records.get(key)
            if record is None:
                record = ident.resolve_mention(
                    mention,
                    roster=roster_snapshot,
                    evidence_ref=evidence_ref,
                    now=now,
                )
                roster_records[key] = record
        try:
            resolved.append(ident.apply_resolution(claim, record, now=now))
        except TemporalContractError:
            # A resolution that cannot be attached is a resolution we do not
            # apply — never a claim we drop.
            resolved.append(claim)

    records: dict[str, ident.ResolutionRecord] = dict(roster_records)
    records.update(rule_records)
    records.update(supplied)
    return resolved, records, by_mention


def _is_owner_birth_group(group: dict, owner: str) -> bool:
    """Is this the OWNER's birth — under either spelling (design §3.1)?

    The resolved subject is the answer whenever identity landed, which after
    layer 3 above is every legacy receipt too. The raw-mention half is the
    belt: a supplied record that leaves the mention ``uncertain`` pops
    ``subject_ref`` back off the claim, and a vault whose only birth receipt is
    a legacy one must not lose its birthday to that.
    """
    if normalized_mention_key(group["subject"]) == normalized_mention_key(owner):
        return True
    return any(
        ident.is_owner_birth_domain_word(claim.get("subject_mention"), claim.get("event_kind"))
        for claim in group["claims"]
    )


# --------------------------------------------------------------------------
# Claims to date records
# --------------------------------------------------------------------------


def age_text_for_band(low: float, high: float, approximate: bool) -> str | None:
    """A phrase ``chronology.parse_age`` reads back as exactly this band.

    The band→phrase direction: what a stored
    :class:`~temporal_claims.TemporalQuantity` would have to have said to mean
    what it means, for any surface that wants to quote a band back in words.

    It was also, briefly, how this module got from a stored band to an
    interval: build a phrase, verify it re-parses, hand it to
    ``chronology.from_age``. That round trip is gone —
    ``chronology.from_age_band`` takes the band directly — and this function's
    remaining load-bearing job is to be the OLD path the new one is pinned
    against, so the two can never silently disagree
    (``test_the_band_door_and_the_phrase_door_agree``).

    ``None`` when no phrase reproduces the band (a hand-built quantity with a
    fractional or out-of-range age) — the same domain
    ``chronology.from_age_band`` refuses.
    """
    if low != int(low) or high != int(high) or low < 0 or high > 120 or high < low:
        return None
    lo, hi = int(low), int(high)
    if approximate:
        # `parse_age` widens a hedged band by a year on each side, so the phrase
        # must name the band BEFORE widening: the stored low/high are already
        # the parsed band, and re-parsing the hedge must reproduce them.
        candidate = f"about {lo}" if lo == hi else f"about {lo} or {hi}"
    else:
        candidate = f"{lo}" if lo == hi else f"{lo} or {hi}"
    parsed = chrono.parse_age(candidate)
    if parsed != (lo, hi, approximate):
        return None
    return candidate


def _claim_provenance(claim: dict) -> dict:
    """The provenance entry a claim contributes to the record it dates.

    ``chronology.claim_score`` counts DISTINCT provenance ``source`` values as
    consilience, so two independent sources saying the same thing corroborate
    and one source saying it twice does not. The claim id rides along because a
    person looking at a contradiction should be able to get from the displayed
    date back to the sentence that produced it.
    """
    entry = {"source": _source_key(claim), "claim_id": collapsed_text(claim.get("claim_id"))}
    return {key: value for key, value in entry.items() if value}


def _record_for_dated_claim(claim: dict) -> chrono.DateRecord | None:
    """A ``date``/``range`` claim's stored value, carrying its source."""
    record = chrono.from_dict(claim.get("temporal_value"))
    if record is None:
        return None
    entry = _claim_provenance(claim)
    if entry and entry not in [dict(p) for p in record.provenance]:
        record = replace(record, provenance=record.provenance + (entry,))
    return record


def _record_for_age_claim(claim: dict, birth: object) -> tuple[chrono.DateRecord | None, str]:
    """An ``age`` claim as an interval — only where the birth anchor exists.

    §10 verbatim: *"I was about 12"* produces a fuzzy interval and a calibrated
    basis, not an exact birthday-derived day. Without a birth anchor there is no
    interval to produce and the honest answer is to say which anchor is missing,
    which is what the second element of the return is for.

    The STORED BAND is what the arithmetic reads — ``chronology.from_age_band``
    — and the stored phrase rides along as provenance. The band is the parsed,
    validated value; re-parsing the phrase here would be a second reading of an
    assertion that has already been read once.
    """
    quantity = claim.get("temporal_value")
    if not isinstance(quantity, dict):
        return None, "quantity_band_unrepresentable"
    if birth is None:
        return None, "age_without_birth_anchor"
    record = chrono.from_age_band(
        birth,
        quantity.get("low"),
        quantity.get("high"),
        approximate=bool(quantity.get("approximate")),
        claim=optional_text(quantity.get("text")),
    )
    if record is None:
        return None, "quantity_band_unrepresentable"
    entry = _claim_provenance(claim)
    if entry:
        record = replace(record, provenance=record.provenance + (entry,))
    return record, ""


# --------------------------------------------------------------------------
# Grouping: claims about the same subject's same event are one node
# --------------------------------------------------------------------------


def _event_words(event_kind: object) -> str:
    return collapsed_text(event_kind).replace("_", " ")


def _node_label(subject_display: str, event_kind: object) -> str:
    """What the node is called before Timeline styles it (wave E owns the page)."""
    words = _event_words(event_kind)
    return f"{subject_display} — {words}" if subject_display and words else (
        subject_display or words
    )


def _subject_display(subject: str, claims: list[dict], roster_names: dict) -> str:
    """The roster's name for a resolved subject; the raw mention otherwise.

    A display label is never a primary key — the node id is — so this is free to
    prefer whatever reads best without anything downstream depending on it.
    """
    named = roster_names.get(subject)
    if named:
        return named
    for claim in claims:
        mention = collapsed_text(claim.get("subject_mention"))
        if mention:
            return mention
    return subject


def _roster_names(roster_snapshot: object) -> dict:
    """``ref -> display name`` from the roster snapshot, or an empty map."""
    try:
        index = ident.roster_index(roster_snapshot)
    except TemporalContractError:
        return {}
    return {ref: name or ref for ref, name in index.refs.items()}


def _era_groups(era_views: object, *, owner_ref: str) -> dict:
    """One seeded ``named_era`` group per known era (eras E3, design §7).

    An era EXISTS as soon as somebody made one, and it has to be able to
    appear on the Timeline undated — in "Not placed yet", with a ▸ on it —
    before anybody says a year. So the era's own identity record is what mints
    the node, and the claims resolved to it are what date it; the node cites
    the era's `identity` claim, which is the "identity claim → node" of §7's
    table and is what keeps `node_without_inputs` an honest rule rather than a
    thing eras are excused from.

    The label is the era's OWN label, handed in rather than derived: the fold
    is pure and never reads a vault, and *"Me's named era"* is not what
    anybody called it.
    """
    views = era_views.values() if isinstance(era_views, dict) else (era_views or ())
    groups: dict[str, dict] = {}
    for view in views:
        if not isinstance(view, dict):
            continue
        era_id = collapsed_text(view.get("era_id"))
        if not era_id:
            continue
        groups[era_id] = {
            "node_id": era_id,
            "event_kind": tp.NAMED_ERA_EVENT_KIND,
            "node_kind": "period",
            "subject": owner_ref,
            "subjects": [owner_ref],
            "resolved": True,
            "claims": [],
            "era_label": collapsed_text(view.get("label")),
            "era_kind": collapsed_text(view.get("era_kind")),
            "identity_claim_id": collapsed_text(view.get("identity_claim_id")),
        }
    return groups


def _group_claims(claims: list[dict], *, owner_ref: str, era_views: object = ()) -> dict:
    """Claims → ``node_id -> group``, in one deterministic pass.

    The grouping key is the claim's own ``event_ref`` when the recorder minted
    one — or when E3's binder RESOLVED one — and the derived node id
    otherwise. ``identity`` claims form no node: they assert *who*, not
    *when*, and their contribution to the projection is the resolution they
    feed, not a row on the page.

    ``era_views`` seeds the era groups first (:func:`_era_groups`), so a
    `period_started` claim bound to an era lands IN that era's node instead of
    minting a second one keyed on the claim's own event kind. The seeded
    group's `event_kind` is `named_era` and its `node_kind` is `period`, and
    the merge below never overwrites either — an era is what it is, whatever
    the claims about it happen to be called.
    """
    groups: dict[str, dict] = _era_groups(era_views, owner_ref=owner_ref)
    for claim in claims:
        if claim.get("claim_type") == "identity":
            continue
        event_kind = collapsed_text(claim.get("event_kind"))
        subject = _subject_handle(claim)
        if not event_kind or not subject:
            continue
        node_id = collapsed_text(claim.get("event_ref")) or _mint_node_id(
            event_kind=event_kind, subject=subject, owner_ref=owner_ref
        )
        group = groups.get(node_id)
        if group is None:
            group = {
                "node_id": node_id,
                "event_kind": event_kind,
                "node_kind": _node_kind_for(event_kind),
                "subject": subject,
                "subjects": [],
                "resolved": False,
                "claims": [],
            }
            groups[node_id] = group
        if subject not in group["subjects"]:
            group["subjects"].append(subject)
        if collapsed_text(claim.get("subject_ref")):
            group["resolved"] = True
        group["claims"].append(claim)
    for group in groups.values():
        group["claims"].sort(key=lambda row: collapsed_text(row.get("claim_id")))
        group["subjects"].sort()
    return groups


# --------------------------------------------------------------------------
# Reconciliation: the best-supported reading, with every rival kept
# --------------------------------------------------------------------------


def _reconcile_group(group: dict, *, birth: object, diagnostics: list) -> dict:
    """One node's claims → ``{best, alternates, conflict, ...}``. Never destructive.

    §6.5: reconciliation runs in the deterministic derivation, returns the
    best-supported value *and* every materially supported alternative *and*
    enough provenance to mint a stable Mirror row — and never deletes the losing
    claim merely because another currently ranks higher.
    """
    records: list[chrono.DateRecord] = []
    relations: list[dict] = []
    durations: list[dict] = []
    for claim in group["claims"]:
        claim_type = collapsed_text(claim.get("claim_type"))
        if claim_type in tc.DATED_CLAIM_TYPES:
            record = _record_for_dated_claim(claim)
            if record is not None:
                records.append(record)
            continue
        if claim_type == "age":
            record, finding = _record_for_age_claim(claim, birth)
            if record is not None:
                records.append(record)
            elif finding:
                diagnostics.append(
                    {
                        "finding": finding,
                        "node_id": group["node_id"],
                        "claim_id": collapsed_text(claim.get("claim_id")),
                    }
                )
            continue
        if claim_type == "duration":
            durations.append(claim)
            continue
        if claim_type == "relative_order":
            value = claim.get("temporal_value")
            if isinstance(value, dict):
                relations.append({"claim": claim, "relation": value})
    outcome = chrono.reconcile(records)
    span = _era_span(group)
    return {
        "best": span if span is not None else outcome["best_supported"],
        "alternates": list(outcome["alternates"]),
        "conflict": float(outcome["conflict"]),
        "relations": relations,
        "durations": durations,
    }


#: The two event kinds that are the ENDS of an era, not events in it (§4.2).
PERIOD_BOUND_EVENT_KINDS = ("period_started", "period_ended")


def _era_span(group: dict) -> object:
    """An era's own interval, composed from its bound claims. Or ``None``.

    `chronology.reconcile` is right for every other node and wrong for exactly
    this one: it reads a group's dated claims as RIVAL READINGS of one moment
    and picks the best-supported, which turns *"2007 through 2011"* into
    "2007, and something disagrees". A `period_started` and a `period_ended`
    are not rivals. They are the two ends of one thing, and composing them is
    the whole difference between an era that reads *2007–2011* and an era that
    reads *2007* with a contradiction hanging off it.

    Only ``named_era`` groups take this path, and only for the two bound
    kinds; anything else said ABOUT an era (an event that happened in it)
    reaches the node through a membership, never through this. Two claims of
    the same bound still reconcile against each other first — two different
    answers to "when did College start" IS a disagreement — so this composes
    the reconciled start with the reconciled end and invents nothing.
    """
    if group.get("event_kind") != tp.NAMED_ERA_EVENT_KIND:
        return None
    ends: dict[str, object] = {}
    for kind in PERIOD_BOUND_EVENT_KINDS:
        records = [
            record
            for claim in group["claims"]
            if collapsed_text(claim.get("event_kind")) == kind
            and collapsed_text(claim.get("claim_type")) in tc.DATED_CLAIM_TYPES
            for record in (_record_for_dated_claim(claim),)
            if record is not None
        ]
        if records:
            ends[kind] = chrono.reconcile(records)["best_supported"]
    started = ends.get("period_started")
    ended = ends.get("period_ended")
    if started is None and ended is None:
        return None
    if started is not None and ended is None:
        return started
    if started is None:
        return ended
    return chrono.DateRecord(
        best=f"{started.best}/{ended.best}",
        earliest=started.earliest,
        latest=ended.latest,
        granularity="range",
        # The WEAKER of the two ends. `chronology.CONFIDENCES` runs
        # certain → conjectural, so the weaker one is the later index: a span
        # is only as firmly held as its shakiest end, and a certain start
        # must not launder a conjectural finish.
        confidence=max(
            (started.confidence, ended.confidence),
            key=lambda name: chrono.CONFIDENCES.index(name)
            if name in chrono.CONFIDENCES else len(chrono.CONFIDENCES),
        ),
        basis=started.basis,
        anchors=tuple(dict.fromkeys([*started.anchors, *ended.anchors])),
        provenance=tuple([*started.provenance, *ended.provenance]),
    )


def _apply_durations(group: dict, calculated: dict, *, diagnostics: list) -> None:
    """A duration bounds the far end of a span it has a start for (§6.4).

    The arithmetic is ``chronology.from_duration``'s — one home for date
    arithmetic — and what belongs here is which finding to report when it
    declines: an unconvertible quantity and a span with no start are different
    problems, and only the second one is a question worth asking a person.

    *"We lived there three years"* says nothing at all until something says when
    it began; once a start exists, the duration says where the span ends, and
    the result is an interval rather than a date because that is what was
    asserted. With no start bound the claim is retained and the missing anchor
    is reported — never filled in.
    """
    best = calculated.get("best")
    for claim in calculated.get("durations") or ():
        quantity = claim.get("temporal_value")
        if chrono.duration_years_band(quantity) is None:
            diagnostics.append(
                {
                    "finding": "quantity_band_unrepresentable",
                    "node_id": group["node_id"],
                    "claim_id": collapsed_text(claim.get("claim_id")),
                }
            )
            continue
        span = chrono.from_duration(best, quantity) if best is not None else None
        if span is None:
            diagnostics.append(
                {
                    "finding": "duration_without_start",
                    "node_id": group["node_id"],
                    "claim_id": collapsed_text(claim.get("claim_id")),
                }
            )
            continue
        if best.latest and best.latest >= span.latest:
            # The span already reaches at least that far: a duration widens a
            # span and never shortens one.
            continue
        entry = _claim_provenance(claim)
        calculated["best"] = replace(
            span, provenance=span.provenance + ((entry,) if entry else ())
        )
        best = calculated["best"]


# --------------------------------------------------------------------------
# Partial order: relative claims and drags, without inventing precision
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class _Edge:
    """One ordering statement, with both ends resolved to node ids."""

    subject: str
    relation: str
    anchors: tuple[str, ...]
    claim_refs: tuple[str, ...] = ()
    constraint_refs: tuple[str, ...] = ()

    def sort_key(self) -> tuple:
        return (self.subject, self.relation, self.anchors, self.claim_refs, self.constraint_refs)


def _anchor_index(groups: dict, displays: dict) -> dict:
    """``key -> node ids`` for every handle an ordering anchor might name.

    Exact keys and a uniqueness gate, exactly as ``identity_resolution`` does
    it: no containment, no edit distance. A key two nodes answer to resolves to
    neither — an anchor that might mean either of two things has not been
    understood, and pretending otherwise is the silent merge the prior audit
    rejected.
    """
    index: dict[str, list[str]] = {}

    def add(key: object, node_id: str) -> None:
        cleaned = normalized_mention_key(key)
        if not cleaned:
            return
        index.setdefault(cleaned, [])
        if node_id not in index[cleaned]:
            index[cleaned].append(node_id)

    for node_id, group in groups.items():
        index.setdefault(node_id, [node_id])
        display = displays.get(node_id, "")
        words = _event_words(group["event_kind"])
        add(display, node_id)
        add(_node_label(display, group["event_kind"]), node_id)
        add(f"{display} {words}", node_id)
        add(words, node_id)
        for claim in group["claims"]:
            add(claim.get("subject_mention"), node_id)
    return {key: tuple(value) for key, value in index.items()}


def _resolve_anchor(text: object, index: dict) -> str:
    """One node id, or ``""`` when the anchor is unknown or ambiguous."""
    raw = collapsed_text(text)
    if raw in index and len(index[raw]) == 1:
        return index[raw][0]
    matches = index.get(normalized_mention_key(raw)) or ()
    return matches[0] if len(matches) == 1 else ""


def _build_edges(groups: dict, calculated: dict, constraints: object, index: dict):
    """Ordering claims and drag constraints → resolved edges + what did not resolve.

    A relative claim whose anchor names nothing the substrate knows is **kept**:
    the node stays retained-but-unplaced, its relation stays visible in the
    node's provenance summary, and the missing anchor becomes a work item. §6.4
    is explicit that *"the summer after we moved"* must be retained even when it
    cannot yet be placed.
    """
    edges: list[_Edge] = []
    unresolved: list[dict] = []

    for node_id in sorted(groups):
        for entry in calculated[node_id]["relations"]:
            relation = entry["relation"]
            claim_id = collapsed_text(entry["claim"].get("claim_id"))
            anchors: list[str] = []
            missing: list[str] = []
            for anchor in relation.get("anchors") or ():
                resolved = _resolve_anchor(anchor, index)
                if resolved and resolved != node_id:
                    anchors.append(resolved)
                else:
                    missing.append(collapsed_text(anchor))
            if missing or not anchors:
                unresolved.append(
                    {
                        "finding": "anchor_unresolved",
                        "node_id": node_id,
                        "claim_id": claim_id,
                        "relation": collapsed_text(relation.get("relation")),
                        "anchors": missing or [collapsed_text(a) for a in relation.get("anchors") or ()],
                    }
                )
                continue
            edges.append(
                _Edge(
                    subject=node_id,
                    relation=collapsed_text(relation.get("relation")),
                    anchors=tuple(anchors),
                    claim_refs=(claim_id,) if claim_id else (),
                )
            )

    for value in constraints or ():
        try:
            row = tc.validate_ordering_constraint(value)
        except TemporalContractError:
            continue
        if row["status"] != "active":
            continue
        subject = row["subject_node_id"]
        anchors = tuple(a for a in row["anchor_node_ids"] if a in groups)
        if subject not in groups or len(anchors) != len(row["anchor_node_ids"]):
            unresolved.append(
                {
                    "finding": "anchor_unresolved",
                    "node_id": subject,
                    "constraint_id": row["constraint_id"],
                    "relation": row["relation"],
                    "anchors": [a for a in row["anchor_node_ids"] if a not in groups],
                }
            )
            continue
        edges.append(
            _Edge(
                subject=subject,
                relation=row["relation"],
                anchors=anchors,
                constraint_refs=(row["constraint_id"],),
            )
        )

    edges.sort(key=_Edge.sort_key)
    return edges, unresolved


def _strict_arcs(edge: _Edge) -> tuple[tuple[str, str], ...]:
    """The earlier→later arcs an edge asserts. ``within`` asserts none."""
    if edge.relation == "before":
        return ((edge.subject, edge.anchors[0]),)
    if edge.relation == "after":
        return ((edge.anchors[0], edge.subject),)
    if edge.relation == "between" and len(edge.anchors) == 2:
        return ((edge.anchors[0], edge.subject), (edge.subject, edge.anchors[1]))
    return ()


def _order_cycles(edges) -> list[tuple[str, ...]]:
    """Every cycle in the strict-order graph, each as a sorted node-id tuple.

    A cycle is a contradiction the person stated — *"A after B"* and *"B after
    A"* cannot both hold — and it must become a Mirror row rather than a
    divergent loop. The walk is a deterministic depth-first search over sorted
    ids, so the same claims always report the same cycles.
    """
    graph: dict[str, list[str]] = {}
    for edge in edges:
        for start, end in _strict_arcs(edge):
            graph.setdefault(start, [])
            if end not in graph[start]:
                graph[start].append(end)
    for arcs in graph.values():
        arcs.sort()

    found: set[tuple[str, ...]] = set()
    state: dict[str, int] = {}
    stack: list[str] = []

    def walk(node: str) -> None:
        state[node] = 1
        stack.append(node)
        for neighbour in graph.get(node, ()):
            colour = state.get(neighbour, 0)
            if colour == 0:
                walk(neighbour)
            elif colour == 1:
                cut = stack.index(neighbour)
                found.add(tuple(sorted(stack[cut:])))
        stack.pop()
        state[node] = 2

    for node in sorted(graph):
        if state.get(node, 0) == 0:
            walk(node)
    return sorted(found)


def _bound_from_edge(edge: _Edge, bounds: dict) -> chrono.DateRecord | None:
    """What this edge says about its subject, given where its anchors sit.

    Every conversion goes through :func:`chronology.from_anchor` — a relation
    plus a landmark yields BOUNDS, never a named date, which is §2.6's rule that
    a move must not persist a fabricated exact date, applied to reading as well
    as to writing.
    """
    anchors = [bounds.get(ref) for ref in edge.anchors]
    if any(record is None for record in anchors):
        return None
    if edge.relation == "before":
        return chrono.from_anchor(anchors[0], "before")
    if edge.relation == "after":
        return chrono.from_anchor(anchors[0], "after")
    if edge.relation == "within":
        return chrono.from_anchor(anchors[0], "during")
    if edge.relation == "between" and len(anchors) == 2:
        forward = chrono.intersect(
            chrono.from_anchor(anchors[0], "after"), chrono.from_anchor(anchors[1], "before")
        )
        if forward is not None:
            return forward
        # "Between A and B" does not promise A came first.
        return chrono.intersect(
            chrono.from_anchor(anchors[1], "after"), chrono.from_anchor(anchors[0], "before")
        )
    return None


def _credit(contributions: dict, edge: _Edge) -> None:
    """Record that this edge's anchors (and theirs) placed its subject."""
    bucket = contributions.setdefault(edge.subject, set())
    for anchor in edge.anchors:
        bucket.add(anchor)
        bucket |= contributions.get(anchor, set())
    bucket.discard(edge.subject)


def _propagate(edges, bounds: dict, *, diagnostics: list, rejected: dict, contributions: dict) -> dict:
    """Narrow every node's interval by every edge, to a bounded fixpoint.

    Narrowing is monotone — an interval only ever shrinks — so the loop settles;
    :data:`MAX_PROPAGATION_ROUNDS` is the guarantee that a future rule change
    cannot turn "settles" into "hangs", and reaching it is reported rather than
    swallowed. Edges inside an order cycle are excluded before the walk begins:
    a contradiction is shown, not chased.

    An edge whose bound is DISJOINT from a value the node already holds is the
    §2.6/§10 case — a move against an explicit incompatible date. Both are kept,
    the explicit date keeps the display, and the conflict becomes a work item.

    ``contributions`` collects, per node, every anchor node that actually moved
    its bounds — transitively, because an anchor may itself have been placed by
    another. That is what lets the node's ``input_claim_refs`` name the evidence
    that placed it rather than only the claims that mention it, and therefore
    what lets ``input_fingerprint`` change when a *new anchor* tightens the
    interval (§6.4's "a new anchor can tighten affected calculated intervals",
    §7's fingerprint contract).
    """
    cycles = _order_cycles(edges)
    in_cycle = {node for cycle in cycles for node in cycle}
    for cycle in cycles:
        diagnostics.append({"finding": "order_cycle", "node_ids": list(cycle)})

    live = [
        edge
        for edge in edges
        if edge.subject not in in_cycle and not any(a in in_cycle for a in edge.anchors)
    ]

    placed = dict(bounds)
    settled = False
    for _ in range(MAX_PROPAGATION_ROUNDS):
        changed = False
        for edge in live:
            derived = _bound_from_edge(edge, placed)
            if derived is None:
                continue
            current = placed.get(edge.subject)
            if current is None:
                placed[edge.subject] = derived
                _credit(contributions, edge)
                changed = True
                continue
            merged = chrono.intersect(current, derived)
            if merged is None:
                # Both are kept. The explicit date keeps the display; the order
                # this edge asserts becomes an ALTERNATE on the node, so the
                # disagreement is visible on Timeline and actionable in Mirror
                # rather than silently discarded (§2.6, §10).
                bucket = rejected.setdefault(edge.subject, [])
                if all(record.to_dict() != derived.to_dict() for record in bucket):
                    bucket.append(derived)
                    diagnostics.append(
                        {
                            "finding": "constraint_contradicts_date",
                            "node_id": edge.subject,
                            "relation": edge.relation,
                            "anchors": list(edge.anchors),
                            "claim_refs": list(edge.claim_refs),
                            "constraint_refs": list(edge.constraint_refs),
                        }
                    )
                continue
            if (merged.earliest, merged.latest) == (current.earliest, current.latest):
                continue
            placed[edge.subject] = merged
            _credit(contributions, edge)
            changed = True
        if not changed:
            settled = True
            break
    if not settled:
        diagnostics.append({"finding": "propagation_cap_reached", "rounds": MAX_PROPAGATION_ROUNDS})
    return placed


# --------------------------------------------------------------------------
# Nodes
# --------------------------------------------------------------------------


def _provenance_summary(group: dict, calculated: dict, best: object) -> str:
    """One sentence a person could read: how many claims, from how many sources.

    A node that could not be placed says what it is waiting for, because §6.4
    requires *"the summer after we moved"* to stay visible as a relation rather
    than disappear into an empty row.
    """
    claims = group["claims"]
    sources = sorted({_source_key(claim) for claim in claims if _source_key(claim)})
    parts = [f"{len(claims)} claim{'s' if len(claims) != 1 else ''}"]
    if sources:
        parts.append(f"from {len(sources)} source{'s' if len(sources) != 1 else ''}")
    record = chrono.from_dict(best) if best is not None else None
    if record is not None:
        parts.append(f"best: {record.basis} ({record.confidence})")
    else:
        relations = calculated.get("relations") or ()
        if relations:
            spoken = sorted(
                {
                    f"{collapsed_text(entry['relation'].get('relation'))} "
                    f"{', '.join(collapsed_text(a) for a in entry['relation'].get('anchors') or ())}".strip()
                    for entry in relations
                }
            )
            parts.append("unplaced: " + "; ".join(spoken))
        else:
            parts.append("unplaced: no date claimed")
    alternates = calculated.get("alternates") or ()
    if alternates:
        parts.append(f"{len(alternates)} alternate{'s' if len(alternates) != 1 else ''}")
    return "; ".join(parts)


def _node_confidence(best: object, conflict: float) -> float:
    """Calibrated support in ``0..1``, damped by how hard the rivals disagree.

    ``chronology.claim_score`` is the package's one measure of how well a dating
    claim is held; this normalizes it by the highest score that function can
    return and then halves it toward zero as the conflict approaches a dead tie.
    Confidence is never a substitute for provenance — it sits beside the
    alternates and the claim refs, which are what a person actually checks.
    """
    if best is None:
        return 0.0
    raw = chrono.claim_score(best) / MAX_CLAIM_SCORE if MAX_CLAIM_SCORE else 0.0
    return max(0.0, min(1.0, raw * (1.0 - 0.5 * max(0.0, min(1.0, conflict)))))


def _conflict_state(*, alternates, conflict: float, contradicted: bool) -> str:
    if contradicted or conflict >= MATERIAL_CONFLICT:
        return "contradicted"
    return "alternatives" if alternates else "none"


def as_of_day(now: object) -> str:
    """``YYYY-MM-DD`` for the fold's clock — the one ``as_of`` definition.

    Every ``as_of`` question in the fold (which frames has the person reached?
    is this event lived or planned?) is answered against this one day, so a
    projection derived twice at one ``now`` is byte-identical. It is never
    stored: ``present`` is resolved again at read time, with the reader's own
    ``as_of`` and timezone (eras design §3.4).
    """
    return tc.normalized_timestamp(now, error=TemporalTimelineError)[:10]


def _life_view(best: object, as_of: object) -> str:
    """``future_plan`` when a node starts after today, else ``lived`` (§2.6).

    An undated node is ``lived``: "we do not know when" is not "it has not
    happened", and the honest reading of an unplaced memory is that it is
    somewhere in the life already lived.
    """
    day = collapsed_text(as_of)
    record = chrono.from_dict(best)
    if record is None or not day:
        return "lived"
    start = chrono._ordinal(record.earliest, end=False)  # noqa: SLF001
    today = chrono._ordinal(day, end=False)  # noqa: SLF001
    if start is None or today is None:
        return "lived"
    return "future_plan" if start > today else "lived"


def _owner_birth(groups: dict, calculated: dict, placed: dict, owner: str,
                 diagnostics: list) -> tuple[str, dict] | None:
    """The owner's ONE birth group — the frames' origin, or a named refusal.

    Post-`O-E0b` the owner's birth receipt resolves to subject ``self`` under
    either spelling, so this is a single-key lookup rather than the seeding
    block's two-step fallback. Zero groups and two groups are both refusals
    with their own diagnostic: frames calculated from a birthday nobody can
    identify would be a coordinate system for somebody else's life.
    """
    any_birth = [
        (node_id, group)
        for node_id, group in sorted(groups.items())
        if group.get("event_kind") == "birth"
    ]
    births = [
        (node_id, group) for node_id, group in any_birth
        if normalized_mention_key(_subject_handle_of(group)) == normalized_mention_key(owner)
    ]
    if not births:
        # A vault with NO birth at all is not a surprise and mints no finding:
        # the substrate already says so through the `missing_anchor birth_date`
        # work item, and a diagnostic on every empty vault is noise. A vault
        # that holds SOMEBODY's birth and not the owner's is the founder's own
        # incident (design §1 item 5) and is worth saying out loud.
        if any_birth:
            diagnostics.append({
                "finding": "age_frames_without_birth_anchor", "subject_ref": owner,
                "node_ids": [node_id for node_id, _ in any_birth],
            })
        return None
    if len(births) > 1:
        diagnostics.append({
            "finding": "age_frames_ambiguous_birth", "subject_ref": owner,
            "node_ids": [node_id for node_id, _ in births],
        })
        return None
    node_id, group = births[0]
    best = placed.get(node_id) or (calculated.get(node_id) or {}).get("best")
    if best is None:
        diagnostics.append({"finding": "age_frames_without_birth_anchor",
                            "subject_ref": owner, "node_ids": [node_id]})
        return None
    return node_id, {"group": group, "best": best}


def _subject_handle_of(group: dict) -> str:
    return collapsed_text(group.get("subject"))


def _owner_death(groups: dict, calculated: dict, placed: dict, owner: str) -> object:
    """The owner's death, when the substrate holds exactly one (design §3.4).

    Contract only — nothing in this phase WRITES an owner death claim. What is
    built is the reading: a life clip that ends where the life did, and no
    frames after it.
    """
    deaths = [
        node_id
        for node_id, group in sorted(groups.items())
        if group.get("event_kind") == "death"
        and normalized_mention_key(_subject_handle_of(group)) == normalized_mention_key(owner)
    ]
    if len(deaths) != 1:
        return None
    return placed.get(deaths[0]) or (calculated.get(deaths[0]) or {}).get("best")


def _origin_basis_of(value: object) -> str:
    """"explicit" for a stated birth, "calculated" otherwise — the ONE mapping
    (design §3.2, binding fact 7), read through
    `temporal_claims.CLAIM_BASIS_BY_DATE_BASIS` and no second table. Shared by
    the age frames (which have always needed it) and the birth node itself
    (E-BO: an explicit birth's own node carries `origin_basis` too, so the
    provisional and the promoted view read the same shape on the one node
    both of them are).
    """
    basis = tc.CLAIM_BASIS_BY_DATE_BASIS.get(
        chrono.from_dict(value).basis if value is not None else "", "calculated"
    )
    return "explicit" if basis == "explicit" else "calculated"


def _age_frame_nodes(*, origin: dict, claim_refs, as_of: str, death: object,
                     roster_snapshot: object, generation: int) -> list[dict]:
    """The reached age frames, as validated ``period`` nodes (design §3.3).

    The arithmetic is `cross_dating.age_frames` and there is no second copy of
    it here. What this adds is everything that is substrate rather than
    calendar: the readable identity, the claims the frame cites, the origin
    BASIS through the substrate's one date-basis mapping, the legacy slugs that
    alias onto the node, and the reached-frame epoch inside the fingerprint.
    """
    best = origin["best"]
    frames = cd.age_frames(best, as_of=as_of, death=death)
    if not frames:
        return []
    epoch = f"age-frame-epoch:{len(frames)}:{frames[-1].band}"
    basis = tc.CLAIM_BASIS_BY_DATE_BASIS.get(
        chrono.from_dict(best).basis if best is not None else "", "calculated"
    )
    origin_basis = _origin_basis_of(best)
    aliases = _legacy_period_aliases(roster_snapshot)
    refs = tuple(ref for ref in dict.fromkeys(collapsed_text(r) for r in claim_refs) if ref)
    rows: list[dict] = []
    for frame in frames:
        rows.append(
            tp.validate_calculated_timeline_node({
                "node_id": tp.age_frame_node_id(frame.band),
                "node_kind": _node_kind_for(tp.AGE_FRAME_EVENT_KIND),
                "event_kind": tp.AGE_FRAME_EVENT_KIND,
                "subject_refs": [DEFAULT_OWNER_REF],
                "label": frame.label,
                "best_temporal_value": frame.value.to_dict(),
                "definition_span": {"start": frame.start.to_dict(),
                                    "end": frame.end.to_dict()},
                "life_clip_end": frame.life_clip_end,
                "origin_basis": origin_basis,
                "legacy_refs": list(aliases.get(frame.band, ())),
                "input_claim_refs": list(refs),
                "input_fingerprint": tp.derive_input_fingerprint(
                    claim_ids=refs,
                    constraint_ids=(),
                    calculation_rule_version=CALCULATION_RULE_VERSION,
                    epoch=epoch,
                ),
                "basis": basis,
                "confidence": _node_confidence(frame.value, 0.0),
                "calculation_rule_version": CALCULATION_RULE_VERSION,
                "projection_generation": generation,
                "conflict_state": "none",
                "provenance_summary": bo.origin_provenance_summary(origin_basis),
                "life_view": _life_view(frame.value.to_dict(), as_of),
            })
        )
    return rows


def _legacy_period_aliases(roster_snapshot: object) -> dict:
    """`{band: (legacy refs…)}` — the slugs that alias onto each frame.

    The canonical three spellings per band (``period:``/``tl:``/``band:``), plus
    whatever a roster row NAMED like a band adds. A roster row contributes
    aliases and nothing else (design §3.5): it does not create a frame, date
    one, rename one or order one.
    """
    aliases: dict[str, list[str]] = {}
    for band, slugs in cd.age_frame_legacy_slugs().items():
        aliases[band] = [f"{prefix}:{slug}" for slug in slugs
                         for prefix in ("period", "tl", "band")]
    for entity in _roster_period_rows(roster_snapshot):
        names = [entity.get("name"), entity.get("slug"), *(entity.get("aliases") or ())]
        band = next((found for found in (cd.age_frame_band_of(name) for name in names)
                     if found), None)
        if band is None:
            continue
        slug = collapsed_text(entity.get("slug")) or cd.age_frame_slug(entity.get("name"))
        for prefix in ("period", "tl", "band"):
            ref = f"{prefix}:{slug}"
            if slug and ref not in aliases.setdefault(band, []):
                aliases[band].append(ref)
    return {band: tuple(dict.fromkeys(refs)) for band, refs in aliases.items()}


def _roster_period_rows(roster_snapshot: object) -> list[dict]:
    rows: list[dict] = []
    for roster in roster_snapshot or ():
        if not isinstance(roster, dict) or collapsed_text(roster.get("type")) != "period":
            continue
        rows.extend(row for row in (roster.get("entities") or ()) if isinstance(row, dict))
    return rows


def _node_dict(
    group: dict,
    calculated: dict,
    *,
    best: object,
    extra_alternates,
    extra_claim_refs,
    contradicted: bool,
    constraint_refs,
    label: str,
    generation: int,
    as_of: str | None = None,
    possible: object = None,
) -> dict:
    """One validated :class:`~temporal_projection.CalculatedTimelineNode`.

    Every claim in the group is an input, including the ones that produced no
    interval: a ``relative_order`` claim that could not be placed and a
    ``duration`` waiting for a start are both part of what this node was
    calculated from, and leaving them out of ``input_claim_refs`` would make the
    fingerprint lie about what would change the answer. So are the claims that
    placed an ANCHOR this node was calculated against: *"the summer after we
    moved"* is calculated from the move's date, and a node that did not cite it
    would keep a stale fingerprint on the day that date arrives.
    """
    own = [collapsed_text(c.get("claim_id")) for c in group["claims"]]
    own.extend(collapsed_text(ref) for ref in extra_claim_refs)
    claim_refs = tuple(ref for ref in dict.fromkeys(own) if ref)
    constraints = tuple(dict.fromkeys(collapsed_text(c) for c in constraint_refs if collapsed_text(c)))
    alternates = [record.to_dict() for record in (calculated.get("alternates") or ())]
    alternates.extend(record.to_dict() for record in extra_alternates)
    conflict = float(calculated.get("conflict") or 0.0)
    state = _conflict_state(alternates=alternates, conflict=conflict, contradicted=contradicted)
    basis = tc.CLAIM_BASIS_BY_DATE_BASIS.get(
        chrono.from_dict(best).basis if best is not None else "", "inferred"
    )
    return tp.validate_calculated_timeline_node(
        {
            "node_id": group["node_id"],
            "node_kind": group["node_kind"],
            "subject_refs": list(group["subjects"]),
            "event_kind": group["event_kind"],
            "label": label,
            "best_temporal_value": best.to_dict() if best is not None else None,
            "alternate_values": alternates,
            "input_claim_refs": list(claim_refs),
            "input_constraint_refs": list(constraints),
            "input_fingerprint": tp.derive_input_fingerprint(
                claim_ids=claim_refs,
                constraint_ids=constraints,
                calculation_rule_version=CALCULATION_RULE_VERSION,
            ),
            "basis": basis,
            "confidence": _node_confidence(best, conflict),
            "calculation_rule_version": CALCULATION_RULE_VERSION,
            "projection_generation": generation,
            "conflict_state": state,
            "provenance_summary": _provenance_summary(group, calculated, best),
            "life_view": _life_view(best, as_of),
            **({"possible_temporal_value": possible.to_dict()}
               if possible is not None else {}),
        }
    )


#: Design §4.2. A `within` says an era sits inside a frame; it does NOT say
#: when the era began or ended. So a named era with no dating claims of its
#: own keeps `best_temporal_value` EMPTY and publishes the containment here,
#: at a confidence that cannot be mistaken for something the person said.
POSSIBLE_VALUE_CONFIDENCE = "inferred"


def _within_frame_anchors(node_id: str, constraints: object, frame_values: dict):
    """The FRAME intervals an era's active `within` constraints point at.

    A frame is not a node in ``groups`` — it is calculated from the owner's
    birth after the fixpoint has run — so ``_build_edges`` legitimately files
    an `anchor_unresolved` diagnostic for it and ``_propagate`` never sees it.
    That is fine for a bound, because a `within` is not one; it is exactly
    what this reads instead.
    """
    found = []
    for value in constraints or ():
        try:
            row = tc.validate_ordering_constraint(value)
        except TemporalContractError:
            continue
        if row["status"] != "active" or row["relation"] != "within":
            continue
        if row["subject_node_id"] != node_id:
            continue
        for anchor in row["anchor_node_ids"]:
            record = frame_values.get(anchor)
            if record is not None:
                found.append((anchor, record))
    return found


def _within_only_possibility(node_id: str, group: dict, calculated: dict,
                             placed: object, edges, *, constraints: object = (),
                             frame_values: dict | None = None) -> object:
    """The `possible_temporal_value` for an era placed ONLY by containment.

    Two conditions, both necessary. The node is a `named_era` — an age
    frame's interval IS its definition and a moment's containment is an
    ordinary bound. And its own claims dated it not at all — one stated bound
    makes the era `partial` and the containment is then corroboration, not the
    only thing we have.

    Two roads reach it. An era inside another ERA propagated through
    ``_propagate`` like anything else, and is used only when EVERY edge that
    touched it was a `within` (an era placed by *"after High School"* has been
    genuinely bounded by an ordering claim, and that is a bound). An era
    inside a FRAME never propagated at all, because a frame is not a node in
    the fixpoint, so its constraint is read directly and converted through
    `chronology.from_anchor` — the one conversion, which yields BOUNDS from a
    relation and never a named date.

    Returns the record to publish as possible (and the caller then publishes
    NO best), or ``None`` when the ordinary path stands.
    """
    if group.get("event_kind") != tp.NAMED_ERA_EVENT_KIND:
        return None
    if calculated.get("best") is not None:
        return None

    record = None
    if placed is not None:
        touching = [edge for edge in edges if edge.subject == node_id]
        if touching and all(edge.relation == "within" for edge in touching):
            record = chrono.from_dict(
                placed.to_dict() if hasattr(placed, "to_dict") else placed
            )
    if record is None:
        for _anchor, frame in _within_frame_anchors(
            node_id, constraints, frame_values or {}
        ):
            during = chrono.from_anchor(frame, "during")
            record = during if record is None else chrono.intersect(record, during)
        if record is None:
            return None
    return chrono.DateRecord(
        best=record.best,
        earliest=record.earliest,
        latest=record.latest,
        granularity=record.granularity,
        confidence=POSSIBLE_VALUE_CONFIDENCE,
        basis="anchor",
        anchors=tuple(record.anchors or ()),
        provenance=tuple(record.provenance or ()),
    )


def _node_sort_key(row: dict) -> tuple:
    """Best-supported order: placed nodes chronologically, unplaced after.

    ISO bounds sort correctly as text at every granularity, and the node id is
    the final tiebreak so two things dated the same day never swap between
    rebuilds.
    """
    value = row.get("best_temporal_value")
    if not isinstance(value, dict):
        return (1, "", "", row.get("node_id") or "")
    return (0, value.get("earliest") or "", value.get("latest") or "", row.get("node_id") or "")


# --------------------------------------------------------------------------
# Work items
# --------------------------------------------------------------------------


def _is_loss_discovery(event_kind: object, subject_ref: object, resolved: bool) -> bool:
    """§2.4: a loss question with nobody named in it is discovery, not a question.

    Discovery is offer-only — the system may offer the Losses area and must
    never put a generic loss prompt into the daily queue. The moment the person
    names who died, the subject *resolves to a roster entity* and the ordinary
    surfaces apply, which is exactly what §2.4 says should happen.

    "Resolved" is the caller's fact, not a guess from the string: a raw mention
    and an entity ref are both text, and inferring which is which from a slash
    would make the loss rule depend on typography.
    """
    if collapsed_text(event_kind) not in LOSS_EVENT_KINDS:
        return False
    ref = collapsed_text(subject_ref)
    return not resolved or not ref or ident.is_unresolved_ref(ref)


def _score_components(
    kind: str, *, system_value: float, event_kind: object, subject_ref: object, resolved: bool
) -> dict:
    """§8.5's raw components, plus the versioned combination of them.

    The weights are simple on purpose. What wave F needs from wave D is the
    *components* — reach, severity, sensitivity — computed where the evidence
    is, and one stable work-item id to hang a calibrated score on later. A
    plausible-looking calibrated number invented here would be the harder thing
    to replace.
    """
    base = dict(WORK_ITEM_VALUE_DEFAULTS.get(kind, {}))
    base["system_value"] = max(0.0, min(1.0, system_value))
    base["sensitivity"] = SENSITIVITY_BY_EVENT_KIND.get(
        collapsed_text(event_kind), DEFAULT_SENSITIVITY
    )
    if _is_loss_discovery(event_kind, subject_ref, resolved):
        base["sensitivity"] = max(base["sensitivity"], 0.9)
    combined = sum(SCORE_WEIGHTS[name] * base.get(name, 0.0) for name in SCORE_WEIGHTS)
    base["combined_score"] = round(max(0.0, min(1.0, combined)), 6)
    return base


def _surfaces_for(kind: str, *, event_kind: object, subject_ref: object, resolved: bool) -> tuple[str, ...]:
    if _is_loss_discovery(event_kind, subject_ref, resolved):
        return LOSS_DISCOVERY_SURFACES
    return SURFACES_BY_KIND.get(kind, ("timeline",))


def _mint_work_item(
    sink: dict,
    components: dict,
    *,
    kind: str,
    event_kind: object = None,
    subject_ref: object = None,
    event_ref: object = None,
    node_ref: object = None,
    requested_field: object = None,
    prompt_intent: object = None,
    claim_refs=(),
    evidence_refs=(),
    system_value: float = 0.0,
    subject_resolved: bool = False,
    now: object = None,
) -> str:
    """Validate one item into the sink, merging on a repeated identity.

    Two derivation paths can reach the same question — a coarse date is both the
    node's own precision gap and the reason a relative claim cannot be placed —
    and because the id is a pure function of what is being asked, that is ONE
    row with the union of the evidence rather than two rows competing (§5.4,
    §2.3). The higher system value wins, since the merged item is asking for
    both reasons at once.
    """
    scores = _score_components(
        kind,
        system_value=system_value,
        event_kind=event_kind,
        subject_ref=subject_ref,
        resolved=subject_resolved,
    )
    payload = {
        "kind": kind,
        "state": "open",
        "subject_ref": subject_ref,
        "event_ref": event_ref,
        "node_ref": node_ref,
        "requested_field": requested_field,
        "prompt_intent": prompt_intent,
        "claim_refs": list(claim_refs),
        "evidence_refs": list(evidence_refs),
        "allowed_surfaces": list(
            _surfaces_for(
                kind, event_kind=event_kind, subject_ref=subject_ref, resolved=subject_resolved
            )
        ),
    }
    payload.update(scores)
    try:
        row = tp.validate_temporal_work_item(payload, now=now)
    except TemporalContractError:
        return ""
    key = row["work_item_id"]
    current = sink.get(key)
    if current is None:
        sink[key] = row
        components[key] = scores
        return key
    merged = dict(current)
    for field_name in ("claim_refs", "evidence_refs"):
        merged[field_name] = sorted(set(current.get(field_name) or ()) | set(row.get(field_name) or ()))
    if row.get("system_value", 0.0) > current.get("system_value", 0.0):
        for name in tp.WORK_ITEM_SCORE_FIELDS:
            if name in row:
                merged[name] = row[name]
        components[key] = scores
    sink[key] = tp.validate_temporal_work_item(merged, now=now)
    return key


def _precision_target(event_kind: object) -> str:
    return PRECISION_TARGETS.get(collapsed_text(event_kind), DEFAULT_PRECISION_TARGET)


def _wants_precision(best: object, event_kind: object) -> bool:
    """Is this node coarser than its event is worth asking about (§2.2)?

    A node already at or finer than its target mints nothing: Timeline is an
    invitation, not a backlog, and re-asking for a day when the year is what the
    event deserves is exactly the false precision §2.2 forbids.
    """
    if best is None:
        return True
    record = chrono.from_dict(best)
    if record is None:
        return True
    target = _precision_target(event_kind)
    return _GRANULARITY_RANK.get(record.granularity, 99) > _GRANULARITY_RANK.get(target, 0)


def _dated_claim_refs(group: dict) -> list[str]:
    """The claims that actually asserted a date — the ones a conflict is between."""
    return [
        collapsed_text(claim.get("claim_id"))
        for claim in group["claims"]
        if collapsed_text(claim.get("claim_type")) in tc.DATED_CLAIM_TYPES + tc.QUANTITY_CLAIM_TYPES
        and collapsed_text(claim.get("claim_id"))
    ]


def _evidence_refs(group: dict) -> list[str]:
    return sorted({_source_key(claim) for claim in group["claims"] if _source_key(claim)})


# --------------------------------------------------------------------------
# The derivation
# --------------------------------------------------------------------------


def derive_calculated_timeline(
    active_index: object,
    *,
    resolution_records: object = (),
    event_resolution_records: object = (),
    era_views: object = (),
    roster_snapshot: object = (),
    constraints: object = (),
    birth_date: object = None,
    owner_ref: object = None,
    projection_generation: int = 0,
    now: object = None,
) -> CalculatedTimeline:
    """Active claims in, a whole calculated timeline out. Pure and deterministic.

    ``active_index`` is ``temporal_store.fold_active_index``'s mapping (or its
    ``claims`` list, or a bare list of claim mappings). ``constraints`` are the
    :class:`~temporal_claims.OrderingConstraint` records a drag wrote.
    ``birth_date`` is the anchor ages are measured from; when it is not supplied
    and the substrate holds exactly one ``birth`` node, that node's own
    best-supported value is used, and when neither exists ages stay unplaced and
    say so.

    Determinism is a property of every step: claims are read in id order, groups
    and edges are sorted, the fixpoint is bounded, and nothing consults a clock
    except the work-item stamps and the phase timings, both of which
    :func:`structural_signature` excludes. Two runs over the same inputs in any
    input order produce the same projection.

    Nothing here writes, publishes, or mutates. Wiring this into
    ``timeline.timeline_data()`` and publishing the generation atomically are
    separate steps by design (§7).
    """
    clock = time.perf_counter
    started = clock()
    timings: dict[str, float] = {}
    diagnostics: list[dict] = []
    owner = collapsed_text(owner_ref) or DEFAULT_OWNER_REF
    as_of = as_of_day(now)

    claims = active_claim_rows(active_index)

    # E3 (§4.3): EVENT resolution, before subjects and before grouping,
    # because the grouping key IS the resolved `event_ref`. This is the same
    # seam `resolution_records` already is, extended from subjects to events:
    # a caller that keeps ONE ledger of decisions may hand it in either
    # argument, so the `event_resolution`-typed rows are harvested out of both
    # rather than requiring every caller to sort its own ledger.
    claims, event_findings = eb.resolve_events(
        claims,
        [
            row
            for row in (list(event_resolution_records or ())
                        + list(resolution_records or ()))
            if isinstance(row, dict) and row.get("type") == eb.EVENT_RESOLUTION_TYPE
        ],
    )
    diagnostics.extend(event_findings)

    mark = clock()
    resolved, records, by_mention = _resolve_subjects(
        claims,
        resolution_records=resolution_records,
        roster_snapshot=roster_snapshot,
        now=now,
        owner_ref=owner,
    )
    timings["resolve"] = clock() - mark

    mark = clock()
    groups = _group_claims(resolved, owner_ref=owner, era_views=era_views)
    roster_names = _roster_names(roster_snapshot)
    displays = {
        node_id: _subject_display(group["subject"], group["claims"], roster_names)
        for node_id, group in groups.items()
    }
    labels = {
        node_id: (collapsed_text(group.get("era_label"))
                  or _node_label(displays[node_id], group["event_kind"]))
        for node_id, group in groups.items()
    }
    timings["group"] = clock() - mark

    mark = clock()
    # Ages need the birth anchor, and the birth anchor is itself a node, so the
    # dated claims settle first and the quantities read the result.
    birth = chrono.from_dict(birth_date) if birth_date is not None else None
    if birth is None:
        # The owner's birth, and only the owner's. There used to be a fallback
        # here — "if that is not exactly one, take whatever birth exists" —
        # and it was wrong in both directions: with a child's birth filed it
        # matched two and picked nothing, and with none of the owner's filed it
        # silently promoted somebody else's birthday to the owner's age anchor.
        births = [
            group
            for group in groups.values()
            if group["event_kind"] == "birth" and _is_owner_birth_group(group, owner)
        ]
        if len(births) == 1:
            seeded = _reconcile_group(births[0], birth=None, diagnostics=[])
            birth = seeded["best"]

    calculated = {
        node_id: _reconcile_group(group, birth=birth, diagnostics=diagnostics)
        for node_id, group in sorted(groups.items())
    }
    for node_id, group in sorted(groups.items()):
        _apply_durations(group, calculated[node_id], diagnostics=diagnostics)
    timings["reconcile"] = clock() - mark

    mark = clock()
    anchor_index = _anchor_index(groups, displays)
    edges, unresolved_anchors = _build_edges(groups, calculated, constraints, anchor_index)
    diagnostics.extend(unresolved_anchors)
    seeds = {node_id: calculated[node_id]["best"] for node_id in sorted(groups)}
    rejected: dict[str, list] = {}
    contributions: dict[str, set] = {}
    placed = _propagate(
        edges,
        seeds,
        diagnostics=diagnostics,
        rejected=rejected,
        contributions=contributions,
    )
    anchor_claim_refs = {
        node_id: [
            collapsed_text(claim.get("claim_id"))
            for anchor in sorted(anchors)
            for claim in (groups.get(anchor) or {}).get("claims", ())
        ]
        for node_id, anchors in contributions.items()
    }
    timings["propagate"] = clock() - mark

    cycle_nodes = {
        node
        for row in diagnostics
        if row.get("finding") == "order_cycle"
        for node in row.get("node_ids") or ()
    }
    contradicted_nodes = cycle_nodes | {
        row.get("node_id")
        for row in diagnostics
        if row.get("finding") == "constraint_contradicts_date"
    }

    constraints_by_node: dict[str, list[str]] = {}
    for edge in edges:
        for ref in edge.constraint_refs:
            constraints_by_node.setdefault(edge.subject, []).append(ref)

    # The age frames (eras E1). They are calculated FROM the reconciled owner
    # birth node — the whole point of `age:self:<band>` being a projection of
    # the substrate rather than a roster row somebody's monthly model wrote —
    # and they are calculated BEFORE the group nodes are rendered because E3's
    # `within(frame)` needs their intervals: a frame is not in `groups`, so
    # `_propagate` cannot see it, and an era told it sits in somebody's 20s
    # would otherwise be told nothing at all.
    mark = clock()
    frame_nodes: list[dict] = []
    provisional_node: dict | None = None
    birth_node_id: str | None = None
    birth_origin_basis: str | None = None
    origin = _owner_birth(groups, calculated, placed, owner, diagnostics)
    if origin is None:
        # No stated birthday. What the person has already said about their age
        # may still bound one (eras design §3.2, E-BO) — `birth_origin` seeds a
        # PROVISIONAL origin node, or withholds the frames and reports a
        # contradiction. It never suppresses the explicit-birthday question.
        provisional = bo.provisional_origin(
            groups=groups, calculated=calculated, owner=owner,
            node_id=_mint_node_id(event_kind="birth", subject=owner, owner_ref=owner),
            node_kind=_node_kind_for("birth"),
            label=_node_label(_subject_display(owner, [], _roster_names(roster_snapshot)),
                              "birth"),
            rule_version=CALCULATION_RULE_VERSION,
            generation=projection_generation,
            confidence_of=_node_confidence,
            diagnostics=diagnostics,
        )
        if provisional is not None:
            # Held until the group nodes exist — E3 renders them AFTER the
            # frames so `within(frame)` can resolve, so the provisional birth
            # node joins `nodes` below, beside the frames it seeded.
            provisional_node = provisional.node
            origin = provisional.origin
    if origin is not None:
        _birth_node_id, resolved_origin = origin
        birth_node_id = _birth_node_id
        birth_origin_basis = _origin_basis_of(resolved_origin["best"])
        frame_nodes = list(_age_frame_nodes(
            origin=resolved_origin,
            claim_refs=[claim.get("claim_id")
                        for claim in resolved_origin["group"].get("claims", ())],
            as_of=as_of,
            death=_owner_death(groups, calculated, placed, owner),
            roster_snapshot=roster_snapshot,
            generation=projection_generation,
        ))
    frame_values = {
        row["node_id"]: chrono.from_dict(row.get("best_temporal_value"))
        for row in frame_nodes
        if row.get("best_temporal_value")
    }

    possibilities = {
        node_id: _within_only_possibility(
            node_id, groups[node_id], calculated[node_id], placed.get(node_id),
            edges, constraints=constraints, frame_values=frame_values,
        )
        for node_id in sorted(groups)
    }
    nodes = [
        _node_dict(
            groups[node_id],
            calculated[node_id],
            best=None if possibilities.get(node_id) is not None else placed.get(node_id),
            possible=possibilities.get(node_id),
            extra_alternates=rejected.get(node_id, ()),
            extra_claim_refs=[
                *anchor_claim_refs.get(node_id, ()),
                *([groups[node_id]["identity_claim_id"]]
                  if groups[node_id].get("identity_claim_id") else ()),
            ],
            contradicted=node_id in contradicted_nodes,
            constraint_refs=constraints_by_node.get(node_id, ()),
            label=labels[node_id],
            generation=projection_generation,
            as_of=as_of,
        )
        for node_id in sorted(groups)
    ]
    if provisional_node is not None:
        nodes.append(provisional_node)
    if birth_node_id is not None:
        # The birth node itself learns `origin_basis` too (E-BO) — not just its
        # frames — so the provisional node and the one it is promoted into read
        # the same shape: ONE node, whose origin_basis flips explicit the
        # moment a stated birthday exists. The provisional node already set
        # this in `birth_origin.provisional_origin`; an explicit birth's own
        # node (built generically by `_node_dict`, which knows nothing about
        # origins) has not, so it is stamped here and only here.
        for node in nodes:
            if node.get("node_id") == birth_node_id and node.get("origin_basis") is None:
                node["origin_basis"] = birth_origin_basis
                break
    nodes.extend(frame_nodes)
    timings["age_frames"] = clock() - mark
    nodes.sort(key=_node_sort_key)

    mark = clock()
    items, components, reach = _derive_work_items(
        groups=groups,
        calculated=calculated,
        placed=placed,
        edges=edges,
        diagnostics=diagnostics,
        records=records,
        by_mention=by_mention,
        displays=displays,
        owner=owner,
        now=now,
    )
    timings["work_items"] = clock() - mark
    timings["total"] = clock() - started

    return CalculatedTimeline(
        nodes=tuple(nodes),
        work_items=tuple(items),
        timings={phase: round(timings.get(phase, 0.0), 9) for phase in TIMING_PHASES},
        score_components=components,
        reach=reach,
        diagnostics={
            "findings": diagnostics,
            "claims": len(claims),
            "nodes": len(nodes),
            "edges": len(edges),
            "unplaced": sorted(
                node_id for node_id in groups if placed.get(node_id) is None
            ),
        },
        projection_generation=projection_generation,
    )


def _derive_work_items(
    *, groups, calculated, placed, edges, diagnostics, records, by_mention, displays, owner, now
):
    """Everything the substrate currently implies a question about (§5.4, D2).

    Four typed kinds out of one shape, each with the identity that makes
    "answer once, update everywhere" mechanical rather than aspirational.
    Scoring calibration belongs to wave F; what this produces is the raw value
    components §8.5 lists — above all **reach**, the number of unplaced nodes an
    anchor would place, which is the number that makes a keystone win on merit
    rather than on its type (§2.3).
    """
    items: dict[str, dict] = {}
    components: dict[str, dict] = {}
    reach: dict[str, int] = {}

    unplaced = {node_id for node_id in groups if placed.get(node_id) is None}

    node_reach: dict[str, int] = {}
    for edge in edges:
        if edge.subject not in unplaced:
            continue
        for anchor in edge.anchors:
            node_reach[anchor] = node_reach.get(anchor, 0) + 1

    handle_reach: dict[str, set] = {}
    handle_claims: dict[str, set] = {}
    handle_text: dict[str, str] = {}
    for row in diagnostics:
        if row.get("finding") != "anchor_unresolved":
            continue
        for anchor in row.get("anchors") or ():
            key = normalized_mention_key(anchor)
            if not key:
                continue
            handle_text.setdefault(key, collapsed_text(anchor))
            handle_reach.setdefault(key, set()).add(row.get("node_id"))
            if row.get("claim_id"):
                handle_claims.setdefault(key, set()).add(row["claim_id"])

    # -- identity ---------------------------------------------------------
    for key in sorted(records):
        record = records[key]
        refs = sorted(set(by_mention.get(key, ())))
        row = ident.identity_work_item(record, claim_refs=refs, now=now)
        if row is None:
            continue
        raw = len(refs)
        item_id = _mint_work_item(
            items,
            components,
            kind="identity_uncertain",
            subject_ref=row.get("subject_ref"),
            requested_field=row.get("requested_field"),
            prompt_intent=row.get("prompt_intent"),
            claim_refs=row.get("claim_refs") or (),
            evidence_refs=row.get("evidence_refs") or (),
            system_value=min(1.0, raw / REACH_SATURATION),
            now=now,
        )
        if item_id:
            reach[item_id] = raw

    # -- missing anchors: an ordering anchor the substrate does not know --
    for key in sorted(handle_text):
        raw = len(handle_reach.get(key, ()))
        text = handle_text[key]
        item_id = _mint_work_item(
            items,
            components,
            kind="missing_anchor",
            subject_ref=ident.unresolved_subject_ref(text),
            requested_field="date",
            prompt_intent=f"When was {text}?",
            claim_refs=sorted(handle_claims.get(key, ())),
            system_value=min(1.0, raw / REACH_SATURATION),
            now=now,
        )
        if item_id:
            reach[item_id] = raw

    # -- missing anchors: an age with no birthday to measure it from ------
    age_claims = sorted(
        {
            row.get("claim_id")
            for row in diagnostics
            if row.get("finding") == "age_without_birth_anchor" and row.get("claim_id")
        }
    )
    if age_claims:
        item_id = _mint_work_item(
            items,
            components,
            kind="missing_anchor",
            subject_ref=owner,
            event_kind="birth",
            requested_field="birth_date",
            subject_resolved=True,
            prompt_intent=(
                "What is your date of birth? "
                f"{len(age_claims)} thing{'s' if len(age_claims) != 1 else ''} "
                "you dated by age can be placed once it is known."
            ),
            claim_refs=age_claims,
            system_value=min(1.0, len(age_claims) / REACH_SATURATION),
            now=now,
        )
        if item_id:
            reach[item_id] = len(age_claims)

    # -- missing anchors: a duration with no start ------------------------
    for row in sorted(
        (r for r in diagnostics if r.get("finding") == "duration_without_start"),
        key=lambda r: (r.get("node_id") or "", r.get("claim_id") or ""),
    ):
        node_id = row.get("node_id")
        group = groups.get(node_id)
        if group is None:
            continue
        _mint_work_item(
            items,
            components,
            kind="missing_anchor",
            event_ref=node_id,
            node_ref=node_id,
            event_kind=group["event_kind"],
            subject_ref=group["subject"],
            requested_field="start_date",
            subject_resolved=group["resolved"],
            prompt_intent=f"When did {displays.get(node_id, group['subject'])} begin?",
            claim_refs=[row.get("claim_id")] if row.get("claim_id") else [],
            evidence_refs=_evidence_refs(group),
            system_value=min(1.0, node_reach.get(node_id, 0) / REACH_SATURATION),
            now=now,
        )

    # -- precision gaps ---------------------------------------------------
    for node_id in sorted(groups):
        group = groups[node_id]
        best = placed.get(node_id)
        if not _wants_precision(best, group["event_kind"]):
            continue
        raw = node_reach.get(node_id, 0)
        display = displays.get(node_id, group["subject"])
        target = _precision_target(group["event_kind"])
        intent = (
            f"When did {display} — {_event_words(group['event_kind'])} — happen?"
            if best is None
            else f"Do you know the {target} for {display} — {_event_words(group['event_kind'])}?"
        )
        item_id = _mint_work_item(
            items,
            components,
            kind="precision_gap",
            event_ref=node_id,
            node_ref=node_id,
            event_kind=group["event_kind"],
            subject_ref=group["subject"],
            requested_field="date",
            subject_resolved=group["resolved"],
            prompt_intent=intent,
            claim_refs=_dated_claim_refs(group),
            evidence_refs=_evidence_refs(group),
            system_value=min(1.0, raw / REACH_SATURATION),
            now=now,
        )
        if item_id:
            reach[item_id] = raw

    # -- contradictions ---------------------------------------------------
    for node_id in sorted(groups):
        group = groups[node_id]
        conflict = float(calculated[node_id].get("conflict") or 0.0)
        if conflict < MATERIAL_CONFLICT:
            continue
        refs = _dated_claim_refs(group)
        if len(refs) < 2:
            continue
        item_id = _mint_work_item(
            items,
            components,
            kind="contradiction",
            event_ref=node_id,
            node_ref=node_id,
            event_kind=group["event_kind"],
            subject_ref=group["subject"],
            requested_field="date",
            subject_resolved=group["resolved"],
            prompt_intent=(
                f"Two dates are claimed for {displays.get(node_id, group['subject'])} — "
                f"{_event_words(group['event_kind'])}. Which is right?"
            ),
            claim_refs=refs,
            evidence_refs=_evidence_refs(group),
            system_value=conflict,
            now=now,
        )
        if item_id:
            reach[item_id] = len(refs)

    # -- a birth origin its own evidence contradicts (E-BO) ---------------
    for row in diagnostics:
        if row.get("finding") == bo.CONTRADICTION_FINDING:
            _mint_work_item(items, components, now=now, **bo.contradiction_work_item(row))

    for row in diagnostics:
        if row.get("finding") == "order_cycle":
            cycle = list(row.get("node_ids") or ())
            refs = sorted(
                {
                    ref
                    for edge in edges
                    if edge.subject in cycle
                    for ref in edge.claim_refs + edge.constraint_refs
                }
            )
            if len(cycle) < 2 or len(refs) < 2:
                continue
            head = groups.get(cycle[0])
            _mint_work_item(
                items,
                components,
                kind="contradiction",
                event_ref=cycle[0],
                node_ref=cycle[0],
                event_kind=head["event_kind"] if head else None,
                subject_ref=head["subject"] if head else None,
                requested_field="order",
                prompt_intent=(
                    "These cannot all be in the order they were given: "
                    + ", ".join(displays.get(n, n) for n in cycle)
                ),
                claim_refs=refs,
                system_value=1.0,
                now=now,
            )
            continue
        if row.get("finding") != "constraint_contradicts_date":
            continue
        node_id = row.get("node_id")
        group = groups.get(node_id)
        if group is None:
            continue
        refs = sorted(
            set(_dated_claim_refs(group))
            | set(row.get("claim_refs") or ())
            | set(row.get("constraint_refs") or ())
        )
        if len(refs) < 2:
            continue
        _mint_work_item(
            items,
            components,
            kind="contradiction",
            event_ref=node_id,
            node_ref=node_id,
            event_kind=group["event_kind"],
            subject_ref=group["subject"],
            requested_field="date",
            prompt_intent=(
                f"The order given for {displays.get(node_id, group['subject'])} does not fit "
                "the date claimed for it."
            ),
            claim_refs=refs,
            evidence_refs=_evidence_refs(group),
            system_value=1.0,
            now=now,
        )

    ordered = sorted(
        items.values(),
        key=lambda row: (
            -float(row.get("combined_score") or 0.0),
            row.get("kind") or "",
            row.get("work_item_id") or "",
        ),
    )
    return ordered, components, reach


__all__ = [
    "CALCULATION_RULE_VERSION",
    "DEFAULT_OWNER_REF",
    "DEFAULT_PRECISION_TARGET",
    "DEFAULT_SENSITIVITY",
    "ERROR_CODES",
    "LOSS_DISCOVERY_SURFACES",
    "LOSS_EVENT_KINDS",
    "MATERIAL_CONFLICT",
    "MAX_CLAIM_SCORE",
    "MAX_PROPAGATION_ROUNDS",
    "PRECISION_TARGETS",
    "REACH_SATURATION",
    "SCORE_FORMULA_VERSION",
    "SCORE_WEIGHTS",
    "SENSITIVITY_BY_EVENT_KIND",
    "SURFACES_BY_KIND",
    "TIMING_PHASES",
    "WORK_ITEM_VALUE_DEFAULTS",
    "CalculatedTimeline",
    "TemporalTimelineError",
    "active_claim_rows",
    "age_text_for_band",
    "derive_calculated_timeline",
    "structural_signature",
]
