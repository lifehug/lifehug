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

import re
import sys
import time
from dataclasses import dataclass, field, replace
from pathlib import Path

SYSTEM_DIR = Path(__file__).resolve().parent
if str(SYSTEM_DIR) not in sys.path:
    sys.path.insert(0, str(SYSTEM_DIR))

import birth_origin as bo  # noqa: E402
import chronology as chrono  # noqa: E402
import conversation_lints as cl  # noqa: E402
import cross_dating as cd  # noqa: E402
import episode_containers as ec  # noqa: E402
import era_memberships as era  # noqa: E402
import episode_fold as ef  # noqa: E402
import episode_fold_contract as efc  # noqa: E402
import event_binding as eb
import identity_resolution as ident  # noqa: E402
import landmark_projection as lp  # noqa: E402
import temporal_claims as tc  # noqa: E402
import temporal_projection as tp  # noqa: E402
import temporal_work_items as twi  # noqa: E402
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
#:
#: ``timeline-rules:3`` (eras E2): memberships, occurrence scope and owner
#: relevance. The same claims calculate to a projection that says which frames
#: a moment is in and whose life it happened in — and to a SMALLER axis, since
#: a `contextual_only` node now gets no membership at all. The design named
#: `:2` for the whole of E1+E2; E1 took that slot, so E2 takes the next one
#: rather than shipping two different meanings under one version.
#:
#: ``timeline-rules:4`` (Timeline Fix 05 §8.3): PLACE CO-LOCATION. An undated
#: moment whose place resolves to exactly one dated residence/work episode on
#: the owner's axis is INFERRED into that episode's span. The same claims now
#: calculate to a projection where things the person never dated nonetheless
#: sit somewhere — labelled ``inferred``, worth half a stated placement in the
#: score, and discarded the moment a real value arrives.
#: ``timeline-rules:5`` (event identity I1, design §3.5/§5.1): GROUPING READS
#: THE IDENTITY LAYER. An active ``same`` binding groups a telling's claims
#: under its episode's node instead of under the key v264 would have used, and
#: a containment edge gives a valueless member a possible outer range. Grouping
#: is the first input every other phase reads, so EVERY node's
#: ``input_fingerprint`` moves with this bump whether or not that node is
#: bound — which is the honest signal, since a stale projection calculated by
#: :4 rules is stale everywhere, not only where a binding landed.
CALCULATION_RULE_VERSION = "timeline-rules:5"

#: E-L2a retired `place_co_location` (design §0.2 M1, §4.1). The rule, its
#: episode-kind list, its provenance sentences and its ``order`` basis are all
#: gone, and this note is deliberately left in their place: the pass fired only
#: on episode groups whose ``event_kind`` was one of
#: ``("residence", "move", "span", "job", "work")`` and NOTHING in this package
#: ever produced one of those, so on a real vault it yielded nothing for its
#: whole life. Its two jobs now have one home each — a member's window is the
#: possible outer range of the containment record the `entity_span` rung filed
#: (`episode_fold_contract.possible_outer_range`), and its refusal-to-guess is
#: :func:`_apply_entity_ambiguity`'s question. Two definitions of "an undated
#: thing during a dated stay" was the defect class; there is now one.
COLOCATION_RETIRED = (
    "place_co_location was retired into the one containment rung at E-L2a; "
    "the window is the filed part_of record's possible outer range and the "
    "ambiguity is place_ambiguous / tenure_ambiguous"
)

#: The combined-score formula's own version, separate from the rules above
#: because scoring is recalibrated on a different cadence from the arithmetic.
#: **The weights below are deliberately simple and deliberately uncalibrated.**
#: Wave F owns calibration (§8.5); what wave D owes it is the raw components and
#: one stable identity per item, both of which are here.
#:
#: O-E6 moved it to ``temporal-score:2``: the birth origin's ``system_value`` is
#: no longer reach alone (`temporal_work_items.birth_origin_system_value`).
#: Defined there, with the rule it names, so the envelope and the item's own
#: ``score_rule`` cannot disagree.
SCORE_FORMULA_VERSION = twi.SCORE_FORMULA_VERSION

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
#: :attr:`CalculatedTimeline.reach` for wave F to calibrate against. Defined in
#: `temporal_work_items` — it is a property of what a work item is worth, and
#: the birth-origin rule needs the same number — and re-exported here under the
#: name every caller already imports.
REACH_SATURATION = twi.REACH_SATURATION

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
    # A place ambiguity is routine incompleteness, not a disagreement, so it
    # goes where the other gaps go and stays off Mirror (§2.3).
    "place_ambiguous": ("timeline", "whisper", "daily_question"),
    "tenure_ambiguous": ("timeline", "whisper", "daily_question"),
    # E-L2b §3.2. Two stays that claim the same weeks IS a disagreement
    # between two things the person said, so it reaches Mirror like a
    # `contradiction` does — and it stays off the daily queue, because the
    # answer is an edit to a date the person has to be looking at.
    "residence_overlap": ("timeline", "mirror"),
    # E-L2c §7.2/§8. A chain gap is routine incompleteness like
    # `place_ambiguous` — nothing disagrees, a stretch simply has no entry
    # yet — so it goes where the other gaps go and stays off Mirror.
    "chain_gap": ("timeline", "whisper", "daily_question"),
    # Event identity I3 (design §6.1/§6.3). Both are a person's own words
    # disagreeing with the substrate's grouping guess — the same class of
    # question as `contradiction` — so both reach Mirror and the daily queue,
    # not only Timeline's voluntary surface.
    "same_event": ("timeline", "mirror", "daily_question"),
    "possible_overmerge": ("timeline", "mirror", "daily_question"),
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
    # Cheaper than a bare date question and worth more: the person is choosing
    # between stretches they already told us about, not recalling a number.
    "place_ambiguous": {"person_value": 0.55, "interaction_cost": 0.2, "context_fit": 0.55},
    # E-L2a: an organization's tenure is the same shape of choice as a place's.
    "tenure_ambiguous": {"person_value": 0.55, "interaction_cost": 0.2, "context_fit": 0.55},
    # E-L2b: scored like a `contradiction` because it is one — two things the
    # person said cannot both be true — and a beat cheaper, because the fix is
    # a date they are already looking at rather than a judgment about meaning.
    "residence_overlap": {"person_value": 0.6, "interaction_cost": 0.4, "context_fit": 0.45},
    # E-L2c: a beat cheaper than an identity choice — the question names its
    # own stretch (`landmarks_interaction.chain_gaps`' own `label`), and
    # "what was going on then" fits an ordinary conversation the way "which
    # of these two times" does not need to.
    "chain_gap": {"person_value": 0.5, "interaction_cost": 0.25, "context_fit": 0.5},
    # Event identity I3. `same_event` costs a beat more than an ordinary
    # identity question — the person is comparing two whole tellings, not
    # picking a name off a short list — and is worth slightly less than a
    # `contradiction` because a miss here is cheap (Law 6): declining leaves
    # two nodes standing, never a wrong merge.
    "same_event": {"person_value": 0.55, "interaction_cost": 0.35, "context_fit": 0.45},
    # `possible_overmerge` is the safeguard the design ships WITH R1, not
    # after it (§4.5) — it is scored like a `contradiction` because it IS
    # one: the substrate already grouped two tellings and something now
    # disagrees about whether it should have.
    "possible_overmerge": {"person_value": 0.6, "interaction_cost": 0.45, "context_fit": 0.4},
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
#: callers with a real owner entity ref pass ``owner_ref=`` and get that. One
#: spelling of "me", defined beside the work-item vocabulary that has to
#: recognize it in a stored reference.
DEFAULT_OWNER_REF = twi.OWNER_SUBJECT_REF

#: The phases §7.1 asks to instrument *within* the pure derivation. Extraction,
#: the claim fold and projection publication are measured by their own owners;
#: what this module can honestly report is what it does.
TIMING_PHASES = ("resolve", "group", "reconcile", "propagate", "age_frames",
                 "memberships", "work_items", "total")

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
    #: Chapters drawn ACROSS the frames they cover (eras design §5.2). Same
    #: reasoning as ``memberships`` and the same phase discipline: the key
    #: lands declared and empty in E1/`O-E1b`, E3 fills the rows.
    chapter_overlays: tuple[dict, ...] = ()
    #: E-L2d (design §9.2, §9.6). The three peer lanes inside each row group:
    #: ``{group_id, lane, episode_node_ids}``. Derived from the memberships and
    #: the participation episodes' own kinds, so a stay that belongs to two
    #: frames draws in both and nothing here picks a winner — that is the
    #: display role's job.
    lanes: tuple[dict, ...] = ()
    #: E-L2d (design §9.1, §15.1). One row per age frame: how it is told, and
    #: whether the system has something to propose. NOTHING here is applied —
    #: `proposal_pending` is the one line the frame row offers, and the
    #: decision is the person's.
    frame_display: tuple[dict, ...] = ()
    #: ``{legacy_work_item_id: canonical_work_item_id}`` — O-E6's derived
    #: migration map, so a bank marker, a session or a Play target minted under
    #: an older identity still resolves to the item it was always about.
    work_item_aliases: dict = field(default_factory=dict)
    #: Event identity I1 (design §3.5). ``{former node id: episode node id}`` —
    #: every key a bound telling's claims WOULD have grouped under, so an open
    #: session, a Mirror row, a work item and an old URL all keep resolving
    #: after a bind (Law 5).
    node_aliases: dict = field(default_factory=dict)
    #: The reached age frames this generation calculated, as
    #: `cross_dating.AgeFrame` objects (eras E1). **In-memory only** — it is in
    #: neither :meth:`to_dict` nor `structural_signature`, so it publishes
    #: nothing and moves no fingerprint. It exists because the age frames are
    #: derived from the RESOLVED owner-birth group, which only this function
    #: can identify (`_owner_birth` plus `birth_origin.provisional_origin`),
    #: and a caller that needed them had no choice but to write a second,
    #: worse owner-birth predicate over raw claims. Event identity I2's binder
    #: was exactly that caller and exactly that bug: on a vault whose owner
    #: birth claim carries `subject_mention: "birth"` and no `subject_ref`, its
    #: own predicate matched nothing, every frame was missing and the
    #: `bounds_in_frame` retrieval signal was dead on every pair. One
    #: definition, many readers (ADR 0021).
    age_frames: tuple = ()
    #: ``{absorbed episode id: surviving episode id}``, read off the merge
    #: receipts' own ``aliases_created`` so the table cannot drift from the act
    #: that created it.
    episode_aliases: dict = field(default_factory=dict)
    #: The identity layer's own rule version, stamped beside the fold's so a
    #: rule-version upgrade can name exactly what it re-derives.
    identity_rule_version: str = efc.IDENTITY_RULE_VERSION
    #: What the fold saw in the records and what it ENTAILED — dormant
    #: bindings, bindings on era-bound claims, proposals deliberately not
    #: applied, and the ``not_same`` closure, which is computed here and
    #: never stored (§2.2).
    identity_diagnostics: dict = field(default_factory=dict)
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
            "chapter_overlays": [dict(row) for row in self.chapter_overlays],
            "work_item_aliases": dict(self.work_item_aliases),
            "node_aliases": dict(self.node_aliases),
            "episode_aliases": dict(self.episode_aliases),
            "identity_rule_version": self.identity_rule_version,
            "identity_diagnostics": dict(self.identity_diagnostics),
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
        "chapter_overlays": [dict(row) for row in current.chapter_overlays],
        # E-L2d: both are DERIVED — from the memberships, the episodes' kinds
        # and the frame display decisions — so a rebuild reproduces them
        # exactly and a drift is a signature diff, whichever schema the writer
        # is publishing.
        "lanes": [dict(row) for row in current.lanes],
        "frame_display": [dict(row) for row in current.frame_display],
        # Derived from the items above, so a rebuild reproduces it exactly and
        # a drift between the map and the set it describes is a signature diff.
        "work_item_aliases": dict(current.work_item_aliases),
        # Event identity I1: all four are derived from the records the fold was
        # handed, so a rebuild reproduces them exactly and a drift between the
        # tables and the drawing they describe is a signature diff.
        "node_aliases": dict(current.node_aliases),
        "episode_aliases": dict(current.episode_aliases),
        "identity_rule_version": current.identity_rule_version,
        "identity_diagnostics": dict(current.identity_diagnostics),
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


# --------------------------------------------------------------------------
# The question writer (Timeline Fix 07, lifehug-platform#761)
# --------------------------------------------------------------------------
#
# The owner read his own Timeline on 2026-08-29 and found "When did speaker's
# mission — transition — happen?", "When did San Diego — span — happen?" and
# "When did I — span — happen?". Three composers were printing
# `{node.label} — {event_kind}` into a sentence: `label` is whatever the
# extractor wrote (its third-person handle for the OWNER, or a bare subject
# string), and `event_kind` is an internal node kind nobody outside this
# module has ever needed to see.
#
# A question is a sentence a person would say. That is one definition — this
# one — used by `_node_label` (so the page's titles and its questions can
# never drift) and by every composer in `_derive_work_items`. It is pure and
# deterministic: no model call, no vault read, REPLAY-able by the hosted
# platform, and testable one string at a time.


#: Third person → second person. The extractor writes about the vault owner
#: from outside ("the speaker's mission", "Author's birth"); the person reading
#: the question is that owner, so every one of these handles is rewritten
#: before it reaches a sentence. Keys are matched whole-word and
#: case-insensitively, longest first; ``’`` is folded to ``'`` first so one
#: key covers both apostrophes.
OWNER_REFERENCE_REWRITES = {
    "the speaker's": "your",
    "the author's": "your",
    "the subject's": "your",
    "the narrator's": "your",
    "the speaker": "you",
    "the author": "you",
    "the subject": "you",
    "the narrator": "you",
    "speaker's": "your",
    "author's": "your",
    "narrator's": "your",
    "speaker": "you",
    "author": "you",
    "narrator": "you",
    "self": "you",
    "myself": "yourself",
    "mine": "yours",
    "my": "your",
    "me": "you",
    "i": "you",
}

#: What a rewritten reference collapses to when the mention was NOTHING BUT a
#: reference to the owner — the founder's "I — span" node. "When did you
#: happen?" is not a question, so a node whose only human text is one of these
#: has no sentence and is withheld (see :func:`compose_question`).
OWNER_BARE_REFERENCES = frozenset({"you", "your", "yours", "yourself"})

_OWNER_REWRITE_RES = tuple(
    (re.compile(r"(?<!\w)" + re.escape(key) + r"(?!\w)", re.IGNORECASE), value)
    for key, value in sorted(
        OWNER_REFERENCE_REWRITES.items(), key=lambda row: -len(row[0])
    )
)

#: A "move" node's own text usually already contains the verb the sentence
#: needs ("move to San Diego"), so the composer strips the lead rather than
#: wrapping it in a second one ("When did move to San Diego happen?").
_MOVE_LEAD_RE = re.compile(
    r"^(?:the\s+)?(?:move[ds]?|moving)\s+(?:to|into|out\s+to|back\s+to)\s+",
    re.IGNORECASE,
)

#: An anchor handle the extractor wrote as a CLAUSE ("my dad graduated from
#: college") cannot be conjugated into "When did …?" without inventing grammar,
#: so it is quoted back instead. Detected, never guessed: three or more words
#: and at least one token that reads as a verb.
_CLAUSE_VERB_RE = re.compile(
    r"(?<!\w)(?:\w+(?:ed|ing)|is|was|were|are|has|had|have|went|got|"
    r"became|came|goes|left|died|born)(?!\w)",
    re.IGNORECASE,
)


def owner_rewrite(text: object) -> str:
    """Every third-person handle for the vault owner, in second person.

    *"speaker's mission"* → *"your mission"*; *"my dad"* → *"your dad"*;
    *"I"* → *"you"*. Whole-word and case-insensitive, longest key first, so
    "Authorized" and "Iris" are untouched and "the speaker's" never resolves
    as "speaker's" with a stray "the" in front of it.
    """
    body = collapsed_text(text).replace("’", "'")
    if not body:
        return ""
    for pattern, replacement in _OWNER_REWRITE_RES:
        body = pattern.sub(replacement, body)
    return collapsed_text(body)


def _possessive(text: object) -> str:
    """``James`` → ``James's``; a text that is already possessive is untouched.

    English style admits ``James'``; the product says ``James's`` because a
    reader parses it as one word about one person and the apostrophe is not
    left dangling at a line break.
    """
    body = collapsed_text(text)
    if not body:
        return ""
    if body.endswith("'s") or body.endswith("s'") or body.endswith("’s"):
        return body
    return body + "'s"


def is_owner_reference_only(text: object) -> bool:
    """Is this text NOTHING but a reference to the owner (the "I — span" node)?"""
    return owner_rewrite(text).strip().lower().rstrip(".") in OWNER_BARE_REFERENCES


def _is_bare_kind_word(text: object) -> bool:
    """Is this "human text" actually just an internal kind word?

    ``birth — birth`` was a real node title: the extractor's subject mention was
    the event's own name. Naming the kind twice is not a subject.
    """
    body = collapsed_text(text).lower().replace("_", " ")
    return bool(body) and body in {
        word for word in cl.TEMPLATE_KIND_WORDS
    } | {"named era", "age frame"}


#: One row per event kind: the node's TITLE and the sentence each work-item
#: kind asks. ``None`` is the default row. Slots:
#:
#: * ``{who}`` — the subject as a person ("you", "James Taylor")
#: * ``{whose}`` — the same, possessive ("your", "James Taylor's")
#: * ``{who_was}`` / ``{who_did}`` — conjugated pairs ("were you" / "was James")
#: * ``{what}`` — the node's own human text, owner-rewritten
#: * ``{target}`` — the precision being asked for ("year", "month", "day")
#: * ``{readings}`` — the rival dates, for a contradiction
#:
#: **No row prints ``event_kind``.** That is the rule this table exists to make
#: structural rather than remembered.
KIND_SENTENCES = {
    "birth": {
        "title": "{whose} birth",
        "missing_anchor": "When {who_was} born?",
        "precision_undated": "When {who_was} born?",
        "precision_coarse": "Do you know the {target} of {whose} birth?",
        "contradiction": "Two dates are claimed for {whose} birth — {readings}. "
                         "Which is right?",
    },
    "child_born": {
        "title": "{whose} birth",
        "missing_anchor": "When {who_was} born?",
        "precision_undated": "When {who_was} born?",
        "precision_coarse": "Do you know the {target} of {whose} birth?",
        "contradiction": "Two dates are claimed for {whose} birth — {readings}. "
                         "Which is right?",
    },
    "death": {
        "title": "{whose} death",
        "missing_anchor": "When {who_did} die?",
        "precision_undated": "When {who_did} die?",
        "precision_coarse": "Do you know the {target} of {whose} death?",
        "contradiction": "Two dates are claimed for {whose} death — {readings}. "
                         "Which is right?",
    },
    "first_met": {
        "title": "meeting {who}",
        "missing_anchor": "When did you first meet {who}?",
        "precision_undated": "When did you first meet {who}?",
        "precision_coarse": "Do you know the {target} you first met {who}?",
        "contradiction": "Two dates are claimed for when you met {who} — "
                         "{readings}. Which is right?",
    },
    "dating_started": {
        "title": "you and {who}",
        "missing_anchor": "When did you and {who} start seeing each other?",
        "precision_undated": "When did you and {who} start seeing each other?",
        "precision_coarse": "Do you know the {target} you and {who} started "
                            "seeing each other?",
        "contradiction": "Two dates are claimed for when you and {who} started "
                         "— {readings}. Which is right?",
    },
    "married": {
        "title": "{what}",
        "missing_anchor": "When did you get married?",
        "precision_undated": "When did you get married?",
        "precision_coarse": "Do you know the {target} you got married?",
        "contradiction": "Two dates are claimed for when you got married — "
                         "{readings}. Which is right?",
    },
    "span": {
        "title": "{what}",
        "missing_anchor": "When did {what} begin?",
        "precision_undated": "When was {what}?",
        "precision_coarse": "Do you know the {target} for {what}?",
        "contradiction": "Two dates are claimed for {what} — {readings}. "
                         "Which is right?",
    },
    "started": {
        "title": "{what}",
        "missing_anchor": "When did {what} start?",
        "precision_undated": "When did {what} start?",
        "precision_coarse": "Do you know the {target} for when {what} started?",
        "contradiction": "Two dates are claimed for when {what} started — "
                         "{readings}. Which is right?",
    },
    "ended": {
        "title": "{what}",
        "missing_anchor": "When did {what} end?",
        "precision_undated": "When did {what} end?",
        "precision_coarse": "Do you know the {target} for when {what} ended?",
        "contradiction": "Two dates are claimed for when {what} ended — "
                         "{readings}. Which is right?",
    },
    "move": {
        "title": "{what}",
        "missing_anchor": "When did you move to {place}?",
        "precision_undated": "When did you move to {place}?",
        "precision_coarse": "Do you know the {target} you moved to {place}?",
        "contradiction": "Two dates are claimed for when you moved to {place} "
                         "— {readings}. Which is right?",
    },
    "school": {
        "title": "{what}",
        "missing_anchor": "When did you start at {what}?",
        "precision_undated": "When were you at {what}?",
        "precision_coarse": "Do you know the {target} for {what}?",
        "contradiction": "Two dates are claimed for {what} — {readings}. "
                         "Which is right?",
    },
    "graduation": {
        "title": "{what}",
        "missing_anchor": "When did you graduate from {what}?",
        "precision_undated": "When did you graduate from {what}?",
        "precision_coarse": "Do you know the {target} you graduated from {what}?",
        "contradiction": "Two dates are claimed for when you graduated from "
                         "{what} — {readings}. Which is right?",
    },
    "job": {
        "title": "{what}",
        "missing_anchor": "When did you start at {what}?",
        "precision_undated": "When were you at {what}?",
        "precision_coarse": "Do you know the {target} for {what}?",
        "contradiction": "Two dates are claimed for {what} — {readings}. "
                         "Which is right?",
    },
    "named_era": {
        "title": "{what}",
        "missing_anchor": "When did {what} begin?",
        "precision_undated": "When was {what}?",
        "precision_coarse": "Do you know the {target} for {what}?",
        "contradiction": "Two dates are claimed for {what} — {readings}. "
                         "Which is right?",
    },
    None: {
        "title": "{what}",
        "missing_anchor": "When did {what} happen?",
        "precision_undated": "When did {what} happen?",
        "precision_coarse": "Do you know the {target} for {what}?",
        "contradiction": "Two dates are claimed for {what} — {readings}. "
                         "Which is right?",
    },
}

#: A place-shaped ``span`` is a residence, and residences read better as
#: "When were you in Yucaipa?" than "When was Yucaipa?".
PLACE_SPAN_SENTENCES = {
    "missing_anchor": "When did you move to {what}?",
    "precision_undated": "When were you in {what}?",
    "precision_coarse": "Do you know the {target} you were in {what}?",
}

#: D5 (owner's 14:21 staging screenshot, 2026-08-29). An AGE FRAME's boundary
#: is arithmetic off the birth origin (`cross_dating.age_frames`, ADR 0030) —
#: the permanent calculated coordinate system, never something a person is
#: asked about. "When did Childhood end — before or after First big paycheck
#: arrives by mail?" is three defects in one sentence and this is the first:
#: the frame is not a question at all.
UNASKABLE_EVENT_KINDS = frozenset({tp.AGE_FRAME_EVENT_KIND})

#: Which sentence a work-item kind asks for.
_ITEM_KIND_SLOTS = {
    "missing_anchor": "missing_anchor",
    "precision_gap": "precision_undated",
    "precision_gap_coarse": "precision_coarse",
    "contradiction": "contradiction",
    "title": "title",
}


def compose_question(
    item_kind: object,
    event_kind: object,
    *,
    who: object = "",
    what: object = "",
    target: object = "",
    readings: object = "",
    is_owner: bool = False,
    is_place: bool = False,
) -> str | None:
    """The sentence this work item asks, or ``None`` — *withheld*.

    Pure, deterministic and one definition for every host (ADR 0021): the
    hosted platform REPLAYs this and never re-words, so Today's tab, the
    Timeline row, Mirror and the Telegram send cannot say four different
    things about one node.

    ``None`` is a first-class outcome and it is the honest one. A node whose
    only human text is a bare pronoun, a bare internal kind word, or an age
    frame's boundary HAS no sentence, and the alternative to withholding is
    the template the owner read on his own timeline. The caller mints the item
    with ``prompt_intent=None`` and files a ``question_withheld`` diagnostic;
    the page then shows the node with no play control and one honest line.
    """
    kind = collapsed_text(event_kind) or None
    if kind in UNASKABLE_EVENT_KINDS:
        return None
    slot = _ITEM_KIND_SLOTS.get(collapsed_text(item_kind))
    if slot is None:
        return None
    row = KIND_SENTENCES.get(kind) or KIND_SENTENCES[None]
    template = row.get(slot)
    if not template:
        return None

    who_text = "you" if is_owner else owner_rewrite(who)
    what_text = "you" if (is_owner and not collapsed_text(what)) else owner_rewrite(what)
    if not what_text and who_text:
        what_text = who_text
    if not who_text and what_text:
        who_text = what_text

    # The three shapes with no sentence in them.
    if not what_text and not who_text:
        return None
    if slot != "title" and is_owner_reference_only(what_text) and "{what}" in template:
        return None
    if _is_bare_kind_word(what_text) and "{what}" in template:
        return None

    place = _MOVE_LEAD_RE.sub("", what_text).strip() or what_text
    if "{place}" in template and (
        not place or is_owner_reference_only(place) or _is_bare_kind_word(place)
    ):
        return None

    if is_place and kind == "span" and slot in PLACE_SPAN_SENTENCES:
        template = PLACE_SPAN_SENTENCES[slot]

    whose = "your" if is_owner else _possessive(who_text)
    text = template.format(
        who=who_text,
        whose=whose,
        who_was="were you" if is_owner else f"was {who_text}",
        who_did="did you" if is_owner else f"did {who_text}",
        what=what_text,
        place=place,
        target=collapsed_text(target) or DEFAULT_PRECISION_TARGET,
        readings=collapsed_text(readings) or "two different times",
    )
    text = collapsed_text(text)
    if not text or cl.lint_question(text):
        return None
    return text


def compose_place_ambiguity_question(places, spans, *, preposition: str = "in") -> str | None:
    """*"Which time in San Diego was this — 1988–1990, or 1996–1999?"*

    Two shapes and no third: ONE place the person was in more than once, and
    two or more DIFFERENT places each with a stretch of their own. Both read
    as a choice between things already on the table, which is the same move a
    contradiction's probe makes and the opposite of naming one and inviting a
    yes (`go-deep.md` §4.3).

    ``preposition`` is E-L2a's one concession to English: a person is *in*
    Cedarport and *at* Tidewheel Works, and the caller knows which because the
    landmark domain says so. It is a preposition and nothing else — the shapes,
    the refusals and the "choice already on the table" move are identical for
    both kinds, which is why this stayed one composer rather than becoming two.

    ``None`` when there is nothing to name — the caller mints the item with a
    withheld reason rather than a template, exactly as every other composer's
    refusal is handled (`_mint_work_item`, D3).
    """
    names = [collapsed_text(name) for name in (places or ()) if collapsed_text(name)]
    stretches = [collapsed_text(span) for span in (spans or ()) if collapsed_text(span)]
    if not names:
        return None
    if len(names) == 1:
        if not stretches:
            return None
        listed = _english_list(stretches, joiner="or")
        return f"Which time {preposition} {names[0]} was this — {listed}?"
    listed = _english_list(names, joiner="or")
    return f"Was this in {listed}?"


def compose_residence_overlap_question(label: str, span: str,
                                       others: object) -> str | None:
    """*"You've told me you were living in two places at once — Cedarport
    (1996–2001) and Millgate (1998–2004). Which of those dates needs fixing?"*

    §3.2's `residence_overlap`, as the sentence the person answers. It names
    BOTH stays with the stretches they were filed with, because the answer is
    a correction to one of them and a person cannot correct a date they have
    not been shown. It asks for a fix rather than announcing a mistake: the
    overlap is a disagreement between two things the person said, and the
    substrate has no opinion about which one is wrong (owner decision 2 — no
    roles, one home at a time, fixed by editing dates).

    ``None`` when a stay cannot be named or dated, which is `_mint_work_item`'s
    withheld-reason path rather than a template leak (D3).
    """
    name = collapsed_text(label)
    stretch = collapsed_text(span)
    rows = [collapsed_text(text) for text in (others or ()) if collapsed_text(text)]
    if not name or not stretch or not rows:
        return None
    listed = _english_list(rows, joiner="and")
    return (f"You've told me you were living in two places at once — "
            f"{name} ({stretch}) and {listed}. Which of those dates needs "
            f"fixing — or was one of them not really a home?")


def _english_list(items, *, joiner: str) -> str:
    """``a``, ``a or b``, ``a, b, or c`` — one spelling, so two questions in
    the same lane cannot punctuate differently."""
    rows = [item for item in items if item]
    if not rows:
        return ""
    if len(rows) == 1:
        return rows[0]
    if len(rows) == 2:
        return f"{rows[0]} {joiner} {rows[1]}"
    return ", ".join(rows[:-1]) + f", {joiner} {rows[-1]}"


def compose_anchor_question(text: object) -> str | None:
    """The sentence for an ANCHOR HANDLE — free text nobody has resolved yet.

    The substrate's other composers know an event kind and a subject; this one
    has only what somebody said ("my dad graduated from college", "the
    Switzerland mission"). A noun phrase asks directly; a CLAUSE is quoted back
    rather than conjugated, because turning "graduated" into "graduate"
    correctly for arbitrary English is grammar this module has no business
    inventing — and a wrong conjugation is exactly the not-a-sentence defect
    the whole contract is about.
    """
    body = owner_rewrite(text)
    if not body or is_owner_reference_only(body) or _is_bare_kind_word(body):
        return None
    words = body.split()
    clause = len(words) >= 3 and bool(_CLAUSE_VERB_RE.search(body))
    question = (
        f"You mentioned {body} — when was that?" if clause else f"When was {body}?"
    )
    if cl.lint_question(question):
        return None
    return question


def _event_words(event_kind: object) -> str:
    """The kind as words — for DIAGNOSTICS and ids only, never for a person.

    Timeline Fix 07: every user-facing string goes through
    :func:`compose_question` or :func:`_node_label`. This survives because a
    diagnostic row and a node id still need the kind spelled out, and deleting
    it would push callers back to inlining ``replace("_", " ")``.
    """
    return collapsed_text(event_kind).replace("_", " ")


def _node_label(subject_display: str, event_kind: object, *,
                what: object = "", is_owner: bool = False) -> str:
    """What the node is CALLED — a phrase a person would recognise.

    Before Timeline Fix 07 this was ``f"{subject_display} — {event_kind}"``,
    which is where "I — span" and "birth — birth" on the founder's own page
    came from. It now reads the SAME :data:`KIND_SENTENCES` table the questions
    read, so a title and the question about it can never describe one node two
    ways.
    """
    title = compose_question(
        "title", event_kind,
        who=subject_display,
        what=what or subject_display,
        is_owner=is_owner,
    )
    if title:
        return title
    return collapsed_text(subject_display) or _event_words(event_kind)


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


def _group_claims(claims: list[dict], *, owner_ref: str, era_views: object = (),
                  identity: object = None, participation: object = None) -> dict:
    """Claims → ``node_id -> group``, in one deterministic pass.

    The grouping key is the EPISODE's node id when an active ``same`` binding
    says this telling is that episode (event identity I1, design §5.1) — the
    identity layer is consulted FIRST and its decision is
    `episode_fold_contract.grouping_key`'s, never a second copy of it made
    here. Otherwise it is the claim's own ``event_ref`` when the recorder
    minted one — or when E3's binder RESOLVED one — and the derived node id
    otherwise. ``identity`` claims form no node: they assert *who*, not
    *when*, and their contribution to the projection is the resolution they
    feed, not a row on the page.

    An episode group's ``event_kind`` is the episode's CANONICAL kind when its
    creation recorded one (§3.2) and the first member claim's kind otherwise;
    its ``node_kind`` is ``episode``, which is what the id was minted with, so
    the group and the digest cannot disagree about what the node is.

    ``era_views`` seeds the era groups first (:func:`_era_groups`), so a
    `period_started` claim bound to an era lands IN that era's node instead of
    minting a second one keyed on the claim's own event kind. The seeded
    group's `event_kind` is `named_era` and its `node_kind` is `period`, and
    the merge below never overwrites either — an era is what it is, whatever
    the claims about it happen to be called.
    """
    groups: dict[str, dict] = _era_groups(era_views, owner_ref=owner_ref)
    # E-L2a (design §3.2). A landmark entry of a span domain seeds ITS OWN
    # episode group before any claim is read, which is what gives an UNDATED
    # stay a node — it has no dated claim to mint one from, and "I lived in
    # Yucaipa, not sure when" must still be a row a person can place.
    if participation is not None:
        groups.update(participation.seed_groups())
    for claim in claims:
        # A participation entry's `identity` claim is the ONE identity claim
        # that reaches a group: it is the entry's own assertion that this stay
        # happened, and without it an undated entry would carry no evidence at
        # all. Every other identity claim still asserts *who*, not *when*.
        stay = participation.node_for(claim) if participation is not None else ""
        if claim.get("claim_type") == "identity" and not stay:
            continue
        event_kind = collapsed_text(claim.get("event_kind"))
        subject = _subject_handle(claim)
        if not subject or (not event_kind and not stay):
            continue
        episode_node = identity.episode_node_for(claim) if identity is not None else ""
        node_id = episode_node or stay or collapsed_text(claim.get("event_ref")) \
            or _mint_node_id(
                event_kind=event_kind, subject=subject, owner_ref=owner_ref
            )
        group = groups.get(node_id)
        if group is None:
            episode_id = (
                identity.episode_of_node.get(node_id) if episode_node else None
            )
            canonical = (
                (identity.episodes.get(episode_id).canonical_event_kind
                 if episode_id and identity.episodes.get(episode_id) else None)
                if episode_node else None
            )
            group = {
                "node_id": node_id,
                "event_kind": canonical or event_kind,
                "node_kind": (efc.EPISODE_NODE_KIND if episode_node
                              else _node_kind_for(canonical or event_kind)),
                "subject": subject,
                "subjects": [],
                "resolved": False,
                "claims": [],
            }
            if episode_node:
                group["episode_id"] = episode_id
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
# Participation episodes (E-L2a, design §3.2)
# --------------------------------------------------------------------------


def _apply_participation_span(group: dict, calculated: dict, *, diagnostics: list) -> None:
    """A stay's two ends are ONE stretch, not two rival readings of a date.

    `episode_containers.span_from_claims` is the ONE definition of "the span
    this telling's own words open" — the containment rung already reads it to
    decide what a container IS — so the node's value is that same record and
    not a second reading of the same two claims. Reusing it is what keeps the
    stretch the Timeline DRAWS and the stretch the rung places INSIDE from
    ever disagreeing (the recurring-defect doctrine, and ADR 0021's one
    definition).

    Reconciliation is deliberately overruled here rather than taught a new
    case. ``reconcile`` ranks RIVAL readings of one fact and would read June
    1996 and August 2001 as two irreconcilable answers to "when?", which at
    ``MATERIAL_CONFLICT`` mints a contradiction about a stay nobody disagrees
    about. A start and an end are not rivals; they are two ends, and the
    alternates and the conflict score are cleared for exactly that reason and
    for no other — every claim stays on disk and stays in ``claim_refs``.
    """
    span, open_ended = ec.span_from_claims(group.get("claims") or ())
    if span is None:
        return
    calculated["best"] = span
    calculated["alternates"] = []
    calculated["conflict"] = 0.0
    calculated["span_open_ended"] = bool(open_ended)
    diagnostics.append({
        "finding": "participation_span_applied",
        "node_id": group["node_id"],
        "event_kind": collapsed_text(group.get("event_kind")),
        "open_ended": bool(open_ended),
    })


# --------------------------------------------------------------------------
# Place co-location (`timeline-rules:4`, Timeline Fix 05 §8.3)
# --------------------------------------------------------------------------


def _place_ref_index(roster_snapshot: object) -> dict:
    """``normalized mention key -> canonical place ref``, or ``{}``.

    Built from `identity_resolution.roster_index` so "SD" and "San Diego" fold
    exactly the way every other mention in this substrate folds, and ONLY from
    a roster that declares itself a PLACE roster — the same refusal
    :func:`_place_keys` makes, and for the same reason: forcing
    ``entity_type="place"`` over a person roster would file the founder's
    children as cities.

    A key that names more than one place is left OUT. Two places with one name
    is an identity question, and answering it by picking the first is how a
    moment ends up in the wrong decade.
    """
    if not isinstance(roster_snapshot, dict):
        return {}
    if collapsed_text(roster_snapshot.get("type")) != "place":
        return {}
    try:
        index = ident.roster_index(roster_snapshot)
    except TemporalContractError:
        return {}
    out: dict[str, str] = {}
    for table in (index.by_name_key, index.by_alias_key):
        for key, refs in table.items():
            if len(refs) != 1:
                out.pop(key, None)
                continue
            existing = out.get(key)
            if existing is not None and existing != refs[0]:
                out.pop(key, None)
                continue
            out[key] = refs[0]
    return out


def _entity_mention_key(text: object, place_refs: dict) -> str:
    """The identity a place or organization mention folds to.

    The roster's ref when the roster knows the name, else the normalized
    mention key itself. The fallback is deliberate: most vaults have no place
    roster at all, and *"San Diego"* said twice is still one place — what a
    roster adds is knowing that *"SD"* is the same one.
    """
    key = normalized_mention_key(text)
    if not key:
        return ""
    return place_refs.get(key, key)


def _group_place_mentions(group: dict) -> list[str]:
    """Every place this node's claims named, source order, de-duplicated.

    Order is the sources' own — claims are read in id order and each claim's
    ``place_mentions`` keeps the order the source used
    (`temporal_claims.normalized_place_mentions`) — so the rule is a pure
    function of the claim set and not of dictionary iteration.
    """
    seen: set[str] = set()
    out: list[str] = []
    for claim in group.get("claims") or ():
        for mention in claim.get("place_mentions") or ():
            text = collapsed_text(mention)
            key = normalized_mention_key(text)
            if not text or not key or key in seen:
                continue
            seen.add(key)
            out.append(text)
    return out


def _episode_entity_names(group: dict, display: str) -> list[str]:
    """The names one participation episode answers to.

    Its SUBJECT always — a residence's subject is the place, a job's is the
    employer, a schooling's is the school — plus whatever places its own
    claims named, which is how a job episode contributes a city it never had
    as a subject. This is the same list the retired co-location pass built,
    widened from "kinds whose subject is a place" to every participation kind,
    because that is precisely what M1 found missing: an employer is an
    identity a story can name, and refusing to read it was refusing the
    `tenure_ambiguous` question before it could be asked.
    """
    names: list[str] = []
    for candidate in (display, group.get("subject")):
        text = collapsed_text(candidate)
        if text and text not in names:
            names.append(text)
    for mention in _group_place_mentions(group):
        if mention not in names:
            names.append(mention)
    return names


def _member_names_entity(group: dict, display: str, name: str) -> bool:
    """Does this member NAME that episode's entity, as a whole word?

    Exact substring on a word boundary, the identical conservatism
    `cross_dating._names` applies to a landmark label: "Mesa" matches "we
    moved to Mesa" and does not match "Mesabi". A one- or two-character name
    matches nothing at all.
    """
    text = collapsed_text(name)
    if len(text) < 3:
        return False
    pattern = re.compile(rf"(?<!\w){re.escape(text)}(?!\w)", re.IGNORECASE)
    fields = [display, collapsed_text(group.get("subject"))]
    for claim in group.get("claims") or ():
        fields.append(collapsed_text(claim.get("event_mention")))
        for evidence in claim.get("evidence") or ():
            if isinstance(evidence, dict):
                fields.append(collapsed_text(evidence.get("quote")))
    return any(field and pattern.search(field) for field in fields)


def _episode_on_owner_axis(group: dict, *, is_place_subject: bool, best: object,
                           entry_index: dict, owner: str, birth: object) -> bool:
    """Is this episode evidence about where the OWNER was?

    Two ways to be, and the second one is not a shortcut. `_owner_relevance` is
    the substrate's one answer to "whose occurrence is this" and it answers
    about PEOPLE — so a residence whose subject resolved to a place in the
    place roster comes back ``other_person`` / ``contextual_only``, which is
    not a verdict about the owner at all; it is the question not applying.

    A residence's subject being a place is exactly the case the rest of this
    module already reads as the owner's own — `PLACE_SPAN_SENTENCES` asks
    *"When were you in Yucaipa?"*, not *"When was Yucaipa?"*. Reading it the
    other way here would mean the rule silently stopped working the moment a
    vault gained a place roster, which is the reverse of what a roster is for.
    """
    if is_place_subject:
        return True
    relevance = _owner_relevance(
        group, best=best, entry_index=entry_index, owner=owner, birth=birth
    )
    return relevance["owner_timeline_relation"] in tp.AXIS_RELATIONS


#: The stretch two consecutive stays may overlap and still be ONE MOVE (design
#: §3.2, owner decision 2). A person leaves one home and settles in the next
#: over a few weeks and the two leases overlap; that is a transition, not two
#: homes, and it mints nothing. Longer than this and both stays stand, both
#: are drawn, and exactly one question is asked.
RESIDENCE_MOVE_TOLERANCE_MONTHS = 3

#: The domain whose episodes this rule applies to. Work and school overlap
#: legitimately — two jobs at once is an ordinary life — and owner decision 2
#: is about HOMES specifically: at any instant at most one active residence
#: episode, and no role vocabulary to say otherwise (§16 names that as the
#: follow-on).
RESIDENCE_OVERLAP_DOMAIN = "residences"


def _bound_is_approximate(group: dict, event_kind: str) -> bool:
    """Did the person hedge THIS end of the stay? (§3.2, §6.)

    An `approximate` bound is the person saying they are not sure — a bracket
    in the Go Dig grammar, `about 1996` in conversation — and §2.2 forbids
    demanding precision they already told us they do not have. Two stays whose
    touching bounds are hedged do not disagree; they are imprecise about the
    same move.
    """
    for claim in group.get("claims") or ():
        if collapsed_text(claim.get("event_kind")) != event_kind:
            continue
        record = chrono.from_dict(claim.get("temporal_value"))
        if record is not None and record.confidence != "certain":
            return True
    return False


def _residence_overlaps(groups: dict, calculated: dict, *, participation: object,
                        entry_index: dict, owner: str, birth: object,
                        displays: dict, place_flags: dict,
                        diagnostics: list) -> dict:
    """§3.2's `residence_overlap` rows — one per stay that outlives its move.

    ONE HOME AT A TIME (owner decision 2, put to the owner on 2026-09-01 with
    the alternative spelled out and chosen against roles). The invariant is a
    VALIDATION, never a refusal to store: both stays are filed, both are
    drawn, neither is silently demoted to an alternate, and the disagreement
    becomes one question the person resolves by correcting a date (§5 rule 7)
    or by retracting a stay that was never a home (§5 rule 6).

    The tolerance is the move itself (:data:`RESIDENCE_MOVE_TOLERANCE_MONTHS`)
    and the hedge (:func:`_bound_is_approximate`). Both are reasons the two
    spans do not actually disagree, so both mint nothing rather than minting a
    question the person would have to answer "no, that's just the move".
    """
    stays: list[tuple[str, object]] = []
    for node_id in sorted(groups):
        if node_id not in participation.seeds:
            continue
        group = groups[node_id]
        if collapsed_text(group.get("participation_domain")) != RESIDENCE_OVERLAP_DOMAIN:
            continue
        span = calculated.get(node_id, {}).get("best")
        if span is None:
            # M3: an undated stay overlaps nothing. It has its own span
            # question already and inventing a second one about a stretch
            # nobody stated would be the guess this substrate refuses.
            continue
        if not _episode_on_owner_axis(
            group,
            is_place_subject=bool(place_flags.get(node_id)),
            best=span, entry_index=entry_index, owner=owner, birth=birth,
        ):
            continue
        stays.append((node_id, span))

    stays.sort(key=lambda row: (getattr(row[1], "earliest", "") or "",
                               getattr(row[1], "latest", "") or "", row[0]))
    found: dict[str, dict] = {}
    for index, (node_id, span) in enumerate(stays):
        partners: list[str] = []
        for other_id, other_span in stays[index + 1:]:
            months = chrono.overlap_months(span, other_span)
            if months <= RESIDENCE_MOVE_TOLERANCE_MONTHS:
                continue
            if _bound_is_approximate(groups[node_id], "ended") or \
                    _bound_is_approximate(groups[other_id], "started"):
                continue
            partners.append(other_id)
        if not partners:
            continue
        found[node_id] = {
            "node_id": node_id,
            "kind": "residence_overlap",
            "label": displays.get(node_id, "") or collapsed_text(
                groups[node_id].get("subject")),
            "span": chrono.display_date(span, with_basis=False),
            "overlapping_node_ids": list(partners),
            "overlapping": [
                f"{displays.get(other, '') or collapsed_text(groups[other].get('subject'))}"
                f" ({chrono.display_date(calculated[other]['best'], with_basis=False)})"
                for other in partners
            ],
        }
        diagnostics.append({
            "finding": "residence_overlap",
            "node_id": node_id,
            "overlapping_node_ids": list(partners),
            "tolerance_months": RESIDENCE_MOVE_TOLERANCE_MONTHS,
        })
    return found


def _apply_entity_ambiguity(groups: dict, calculated: dict, *,
                            participation: object, roster_snapshot: object,
                            entry_index: dict, owner: str, birth: object,
                            displays: dict, place_flags: dict,
                            diagnostics: list) -> dict:
    """§4.1 condition 4, as the question it owes. Deterministic; no model call.

    What is LEFT of `place_co_location` after E-L2a retired it. The pass used
    to do two things: infer a member's span from the one stay that could hold
    it, and refuse to infer when several could. The first is now the
    containment rung's `part_of` record and its possible outer range — one
    definition of "an undated thing during a dated stay", which is the whole
    point of the retirement — and the second is this, because a refusal that
    asks nothing is a refusal nobody can act on.

    So this pass NEVER writes a value. It finds members that name a
    participation entity the person visited more than once, and hands
    :func:`_derive_work_items` the candidates for one `place_ambiguous`
    (places) or `tenure_ambiguous` (organizations and schools) row.

    The binder's own rung refuses the same pairs on the same rule
    (`episode_containers.ambiguous_entities`), so nothing is filed that this
    then contradicts; the two hosts differ only in how they FIND candidates —
    the rung through the vault's full roster entity index, this pass through
    the place roster and the episode's own filed label — which is named here
    rather than hidden.
    """
    place_refs = _place_ref_index(roster_snapshot)

    by_entity: dict[str, list[str]] = {}
    entity_names: dict[str, str] = {}
    entity_kinds: dict[str, str] = {}
    for node_id in sorted(groups):
        if node_id not in participation.seeds:
            continue
        group = groups[node_id]
        span = calculated.get(node_id, {}).get("best")
        if span is None:
            # M3: an undated stay is never a container, so it is never one of
            # the stays a question chooses between either.
            continue
        if not _episode_on_owner_axis(
            group,
            is_place_subject=bool(place_flags.get(node_id)),
            best=span, entry_index=entry_index, owner=owner, birth=birth,
        ):
            continue
        domain = collapsed_text(group.get("participation_domain"))
        for name in _episode_entity_names(group, displays.get(node_id, "")):
            key = _entity_mention_key(name, place_refs)
            if not key:
                continue
            entity_names.setdefault(key, name)
            entity_kinds.setdefault(key, domain)
            if node_id not in by_entity.setdefault(key, []):
                by_entity[key].append(node_id)

    ambiguous: dict[str, dict] = {}
    if not by_entity:
        return ambiguous

    for node_id in sorted(groups):
        group = groups[node_id]
        if group.get("node_kind") in ("episode", "period"):
            continue
        if calculated.get(node_id, {}).get("best") is not None:
            continue
        display = displays.get(node_id, "")
        matched: list[str] = []
        matched_keys: list[str] = []
        for key in sorted(by_entity):
            name = entity_names[key]
            named = any(
                _entity_mention_key(mention, place_refs) == key
                for mention in _group_place_mentions(group)
            ) or _member_names_entity(group, display, name)
            if not named:
                continue
            if len(by_entity[key]) < 2:
                # Exactly one compatible stay: the rung places it. Nothing to
                # ask, and nothing inferred here — that is the record's job.
                continue
            if key not in matched_keys:
                matched_keys.append(key)
            for episode_id in by_entity[key]:
                if episode_id not in matched:
                    matched.append(episode_id)
        if not matched_keys:
            continue
        organization = any(entity_kinds.get(key) in ("work", "schools")
                           for key in matched_keys)
        kind = "tenure_ambiguous" if organization else "place_ambiguous"
        ambiguous[node_id] = {
            "node_id": node_id,
            "kind": kind,
            "preposition": "at" if organization else "in",
            "episode_node_ids": sorted(matched),
            "place_keys": list(matched_keys),
            "places": [entity_names.get(key, key) for key in matched_keys],
            # CHRONOLOGICAL, not node-id order. The sentence reads "which
            # time … — 1988–1990 or 1996–1999?", and a person answering it is
            # scanning a life, not a digest. `sorted(matched)` stays the
            # identity list; this is the one place order is a reading
            # decision rather than a determinism one, and it is deterministic
            # either way because the tie-break is the node id.
            "spans": [
                chrono.display_date(calculated[episode_id]["best"], with_basis=False)
                for episode_id in sorted(
                    matched,
                    key=lambda ref: (
                        getattr(calculated[ref]["best"], "earliest", "") or "",
                        getattr(calculated[ref]["best"], "latest", "") or "",
                        ref,
                    ),
                )
            ],
        }
        diagnostics.append({
            "finding": "participation_entity_ambiguous",
            "node_id": node_id,
            "kind": kind,
            "places": [entity_names.get(key, key) for key in matched_keys],
            "episode_node_ids": sorted(matched),
        })
    return ambiguous


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
    origin_basis = _origin_basis_of(best)
    frames = cd.age_frames(best, as_of=as_of, death=death,
                           origin_basis=origin_basis)
    if not frames:
        return []
    epoch = f"age-frame-epoch:{len(frames)}:{frames[-1].band}"
    basis = tc.CLAIM_BASIS_BY_DATE_BASIS.get(
        chrono.from_dict(best).basis if best is not None else "", "calculated"
    )
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


# --------------------------------------------------------------------------
# Owner relevance — whose occurrence, and why it is on the owner's axis (E2)
# --------------------------------------------------------------------------


def _landmark_entry_index(landmark_entries: object) -> dict:
    """``source_id -> {"source_id", "domain", "entry_key"}``.

    The rows are ``landmark_projection.load_landmark_sources``' own, passed in
    rather than read, so the fold stays a pure function of its arguments. The
    join key is the ``source_id`` every claim minted from that entry cites, so
    the landmark DOMAIN reaches a claim through a durable record rather than by
    parsing the free-text quote it happens to carry.
    """
    index: dict[str, dict] = {}
    for row in landmark_entries or ():
        if not isinstance(row, dict):
            continue
        source_id = collapsed_text(row.get("source_id"))
        domain = collapsed_text(row.get("domain"))
        if not source_id or not domain:
            continue
        index[source_id] = {
            "source_id": source_id,
            "domain": domain,
            "entry_key": collapsed_text(row.get("entry_key")),
        }
    return index


def _before_birth(best: object, birth: object) -> bool:
    """Is this occurrence WHOLLY before the supported birth interval?

    "Wholly" is doing real work: an interval that merely starts before the
    birth's latest reading overlaps it, and an overlap is not a contradiction —
    it is a person who does not know the month yet.
    """
    record = chrono.from_dict(best) if not isinstance(best, chrono.DateRecord) else best
    origin = chrono.from_dict(birth) if not isinstance(birth, chrono.DateRecord) else birth
    if record is None or origin is None:
        return False
    latest = chrono._ordinal(record.latest or record.best, end=True)  # noqa: SLF001
    earliest = chrono._ordinal(origin.earliest or origin.best, end=False)  # noqa: SLF001
    if latest is None or earliest is None:
        return False
    return latest < earliest


def _group_entries(group: dict, entry_index: dict) -> list[dict]:
    """The landmark entries (`landmark_projection.load_landmark_sources` rows)
    behind this group's claims — join key `claim.source_ref.source_id`."""
    out: list[dict] = []
    seen: set[str] = set()
    for claim in group.get("claims") or ():
        ref = claim.get("source_ref")
        source_id = collapsed_text(ref.get("source_id")) if isinstance(ref, dict) else ""
        entry = entry_index.get(source_id)
        if entry is not None and source_id not in seen:
            seen.add(source_id)
            out.append(entry)
    return out


def _mention_is_ambiguous(group: dict) -> bool:
    """Did identity resolution find MORE THAN ONE roster candidate for this
    subject and stop rather than guess (`identity_resolution.resolve_mention`,
    ``reason: "ambiguous_candidates"``)?

    This — not "no `subject_ref` landed" — is what "an unresolved mention"
    means (eras design §2.5): a mention with **zero** roster candidates
    (`"no_candidate"`) is not ambiguous, it simply names nobody the roster
    knows, which is the ordinary shape of the owner's OWN narration ("the
    reunion", "the wedding") and defaults to the owner below — never to
    `unresolved`, which is reserved for a genuine standoff between candidates.
    """
    for claim in group.get("claims") or ():
        resolution = claim.get("subject_resolution")
        if isinstance(resolution, dict) and resolution.get("reason") == "ambiguous_candidates":
            return True
    return False


def _owner_relevance(group: dict, *, best: object, entry_index: dict, owner: str,
                     birth: object) -> dict:
    """Whose occurrence this is, why it is on the owner's axis, and the proof.

    Four answers and no fifth (eras design §2.5):

    1. the subject resolves to the OWNER, or every landmark entry behind this
       claim is one of the OWNER's OWN LIFE domains (residences, schools,
       work, military, birth) — their own axis, ``participated``, no evidence
       owed. `landmark_projection.OWNER_RELEVANCE_BY_DOMAIN` is deliberately a
       table of the FOUR other-person domains, not the nine; an entry from any
       domain outside it never reaches the subject question at all;
    2. identity landed on more than one candidate and stopped rather than
       guess — ``unresolved`` / ``unresolved``. **Never the owner by
       default**: `_derive_work_items` already carries this to Mirror as an
       ``identity_uncertain`` row, and guessing `self` here is exactly how
       somebody else's life ends up drawn as the owner's. A mention that
       matches NO roster candidate at all is not this case — see rule 1's
       fallback below;
    3. somebody else, and a LANDMARK ENTRY behind this claim makes this
       particular occurrence owner-relevant — ``lived_effect`` for a child's
       birth or a loss, ``participated`` for a partnership, citing the entry;
    4. somebody else and nothing does — ``contextual_only``, which is an
       ANSWER: a relationship may well be stated, and this occurrence still is
       not the owner's. Rule 4 also swallows rule 3 when the occurrence is
       wholly before the owner's birth: a grandmother's birth is family
       history, not something the owner lived through.

    The occurrence subject is never rewritten to the owner in any of them.
    """
    subject = collapsed_text(group.get("subject"))
    entries = _group_entries(group, entry_index)
    domains = {entry["domain"] for entry in entries}
    owner_row = {
        "occurrence_subject_scope": "owner",
        "owner_timeline_relation": "participated",
        "relation_evidence_refs": (),
    }
    if normalized_mention_key(subject) == normalized_mention_key(owner):
        return owner_row
    if entries and domains.isdisjoint(lp.OWNER_RELEVANCE_BY_DOMAIN):
        # Every entry behind this claim is one of the owner's own-life
        # domains — a residence/school/work/military/birth entry's subject is
        # the owner whatever its raw mention text happens to be (a domain-word
        # fallback is common when the entry names nobody else).
        return owner_row
    if _mention_is_ambiguous(group):
        return {
            "occurrence_subject_scope": "unresolved",
            "owner_timeline_relation": "unresolved",
            "relation_evidence_refs": (),
        }

    event_kind = collapsed_text(group.get("event_kind"))
    relation = None
    refs: list[str] = []
    for entry in entries:
        granted = lp.owner_relevance_for(entry["domain"], event_kind)
        if granted is None:
            continue
        relation = granted if relation is None else relation
        if entry["source_id"] not in refs:
            refs.append(entry["source_id"])
    if relation is None and not entries and not group.get("resolved"):
        # No landmark entry at all, and no roster candidate either — an
        # ordinary, self-narrated claim naming nobody the roster knows. Rule
        # 2's veto is for a genuine standoff between candidates; the absence
        # of any candidate is the ordinary shape of the owner's own life.
        return owner_row
    if relation is not None and _before_birth(best, birth):
        # Family history the owner was not alive for. The relationship is
        # stated and the evidence stands; what it does not support is a row on
        # a life that had not started.
        relation = "contextual_only"
    return {
        "occurrence_subject_scope": "other_person",
        "owner_timeline_relation": relation or "contextual_only",
        "relation_evidence_refs": tuple(refs),
    }


def _relevance_life_view(relevance: dict, *, best: object, birth: object,
                         as_of: object, diagnostics: list, node_id: str,
                         birth_node_id: object) -> str:
    """E1's ``lived``/``future_plan``, plus §2.6's two occurrence-subject rows.

    An OWNER-subject occurrence wholly before the supported birth interval is
    ``contradictory`` and mints a diagnostic naming the birth node — Mirror's
    row, not a censored claim; §2.6 is explicit that this is never a deletion.
    An unresolved subject is ``unresolved``, which is how the page knows not to
    draw it on the axis while the identity question is open.
    """
    scope = relevance["occurrence_subject_scope"]
    if scope == "unresolved":
        return "unresolved"
    if scope == "owner" and _before_birth(best, birth):
        diagnostics.append({
            "finding": "before_owner_birth",
            "node_ids": [node_id],
            "birth_node_id": collapsed_text(birth_node_id) or None,
        })
        return "contradictory"
    return _life_view(best, as_of)


# --------------------------------------------------------------------------
# Memberships — arithmetic for frames, receipts for named eras (E2)
# --------------------------------------------------------------------------


def _membership_row(*, member: str, era: str, relation: str, evidence,
                    basis: str, confidence: float, fingerprint: object = None) -> dict:
    payload = {
        "member_node_id": member,
        "era_node_id": era,
        "relation": relation,
        "evidence_refs": list(evidence),
        "basis": basis,
        "confidence": confidence,
    }
    if fingerprint:
        payload["input_fingerprint"] = fingerprint
    return tp.validate_calculated_membership(payload)


def _frame_memberships(nodes: list[dict], frames, *, on_axis: dict) -> list[dict]:
    """Every dated, owner-relevant node's place in the age frames. Arithmetic.

    `cross_dating.frames_touching` is the whole rule and there is no second
    copy of it: one containing frame is ``within``, anything wider or straddling
    is ``overlaps`` in EVERY frame it touches, and nothing picks a winner —
    which frame the row renders in is a display role, decided below.

    Two gates, both of them refusals rather than guesses. A node with no
    ``best_temporal_value`` gets no membership (an undated moment is not
    secretly in childhood), and a node whose ``owner_timeline_relation`` does
    not put it on the axis gets none either — that is §2.5's *"Not placed yet ·
    about someone else"* expressed as an absence rather than as a row somebody
    has to notice is wrong.
    """
    if not frames:
        return []
    by_band = {frame.band: tp.age_frame_node_id(frame.band) for frame in frames}
    rows: list[dict] = []
    for node in nodes:
        node_id = collapsed_text(node.get("node_id"))
        if node.get("node_kind") == "period" or not node_id:
            continue
        if not on_axis.get(node_id):
            continue
        best = node.get("best_temporal_value")
        if not isinstance(best, dict):
            continue
        refs = list(node.get("input_claim_refs") or ())
        refs.append(tp.FRAME_MEMBERSHIP_RULE)
        for band, relation in cd.frames_touching(frames, best):
            era_node_id = by_band.get(band)
            if not era_node_id:
                continue
            rows.append(_membership_row(
                member=node_id, era=era_node_id, relation=relation,
                evidence=refs, basis=collapsed_text(node.get("basis")) or "inferred",
                confidence=float(node.get("confidence") or 0.0),
                fingerprint=node.get("input_fingerprint"),
            ))
    return rows


def _asserted_memberships(assertions: object, *, node_ids: set) -> list[dict]:
    """The union of active membership receipts — ONE membership, N evidence.

    Grouped by ``(member, era, relation)``, which is exactly
    `temporal_projection.derive_membership_id`'s identity, so two independent
    witnesses to one containment are one calculated membership carrying both
    ``assertion_id``s (T-M-09) and retracting either leaves it standing on the
    other (T-M-10). The receipts are the only source: a claim's ``event_ref``
    is never read for membership, because an era's own bounds claims carry the
    era's ``event_ref`` and an event's claim carries the event's — *"graduated
    in 2011 during college"* is one date claim plus one assertion (§2.4).
    """
    grouped: dict[tuple, dict] = {}
    for row in assertions or ():
        if not isinstance(row, dict):
            continue
        member = collapsed_text(row.get("member_node_id"))
        era = collapsed_text(row.get("era_node_id"))
        relation = collapsed_text(row.get("relation")) or "within"
        assertion = collapsed_text(row.get("assertion_id"))
        if not member or not era or not assertion:
            continue
        # A receipt about a node this projection does not hold is kept out of
        # the projection and NOT deleted: the assertion is still on disk, and
        # the node may arrive with the next extraction.
        if node_ids and member not in node_ids:
            continue
        key = (member, era, relation)
        bucket = grouped.setdefault(key, {"evidence": [], "basis": "explicit"})
        if assertion not in bucket["evidence"]:
            bucket["evidence"].append(assertion)
        basis = collapsed_text(row.get("basis"))
        if basis in ("explicit", "calculated", "inferred"):
            bucket["basis"] = basis if bucket["basis"] == "explicit" else bucket["basis"]
    rows: list[dict] = []
    for (member, era, relation) in sorted(grouped):
        bucket = grouped[(member, era, relation)]
        evidence = sorted(bucket["evidence"])
        rows.append(_membership_row(
            member=member, era=era, relation=relation, evidence=evidence,
            basis=bucket["basis"],
            # Two independent witnesses support a containment more than one
            # does, and the ladder saturates: this is a display ORDER, never a
            # probability, which is why it is capped and stated here rather
            # than dressed up as a calibrated number.
            confidence=min(0.95, 0.6 + 0.15 * (len(evidence) - 1)),
        ))
    return rows


def _apply_display_roles(memberships: list[dict], *, decisions: object,
                         node_index: dict) -> list[dict]:
    """Exactly one ``primary`` per member; everything else ``secondary``.

    The design's own order (§2.4), and every rung of it is deterministic: an
    active display decision naming this container wins; otherwise a direct
    event-level assertion (a ``within`` receipt) outranks calculated
    arithmetic; otherwise the highest-supported membership (confidence, then
    evidence count); otherwise the MOST SPECIFIC era, measured as the narrowest
    interval the container node carries; and finally the era node id, so two
    equal candidates never swap between rebuilds.

    Display roles are rendering. Nothing downstream reads one for a date, an
    order or a membership.
    """
    chosen: dict[str, str] = {}
    for row in decisions or ():
        if not isinstance(row, dict):
            continue
        member = collapsed_text(row.get("member_node_id"))
        container = collapsed_text(row.get("primary_container_id"))
        if member and container:
            chosen[member] = container

    by_member: dict[str, list[dict]] = {}
    for row in memberships:
        by_member.setdefault(row["member_node_id"], []).append(row)

    def specificity(era_node_id: str) -> float:
        node = node_index.get(era_node_id) or {}
        record = chrono.from_dict(node.get("best_temporal_value"))
        if record is None:
            return float("inf")
        low = chrono._ordinal(record.earliest or record.best, end=False)  # noqa: SLF001
        high = chrono._ordinal(record.latest or record.best, end=True)  # noqa: SLF001
        if low is None or high is None:
            return float("inf")
        return float(high[0] - low[0]) + (high[1] - low[1]) / 12.0

    def is_calculated(row: dict) -> bool:
        """Frame arithmetic cites its own rule name and nothing else does —
        a direct receipt-backed assertion never carries it (design §2.4's
        "a direct event-level assertion outranks calculated arithmetic")."""
        return tp.FRAME_MEMBERSHIP_RULE in row.get("evidence_refs", ())

    out: list[dict] = []
    for member in sorted(by_member):
        rows = by_member[member]
        decided = chosen.get(member)
        ranked = sorted(
            rows,
            key=lambda row: (
                row["era_node_id"] != decided,
                row["relation"] != "within",
                is_calculated(row),
                -row["confidence"],
                -len(row["evidence_refs"]),
                specificity(row["era_node_id"]),
                row["era_node_id"],
            ),
        )
        for index, row in enumerate(ranked):
            out.append({**row, "display_role": "primary" if index == 0 else "secondary"})
    out.sort(key=lambda row: (row["member_node_id"], row["era_node_id"], row["relation"]))
    return out


# --------------------------------------------------------------------------
# Lanes and the frame display proposal (E-L2d, design §9.1-§9.2)
# --------------------------------------------------------------------------


def lane_rows(nodes: list[dict], memberships: object) -> list[dict]:
    """The Lived · Worked · Schooled lanes of every row group (design §9.2).

    A lane is a property of a ROW GROUP, not of a node: the same stay draws in
    every frame and era it belongs to, which is what its memberships already
    say, so this reads them rather than re-deciding containment. An
    ``associated_with`` membership is deliberately skipped — §3.3: an
    association is a rendered link and never chronology, and a lane is a bar
    on a life axis.

    Nothing is invented and nothing is dropped: a participation episode with
    no membership (undated, or off the owner's axis) simply has no lane, which
    is the same absence `_frame_memberships` files for it.
    """
    kinds = {
        collapsed_text(row.get("node_id")): collapsed_text(row.get("event_kind"))
        for row in nodes
        if row.get("node_kind") == "episode"
        and collapsed_text(row.get("event_kind")) in tp.LANES_BY_EVENT_KIND
    }
    if not kinds:
        return []
    grouped: dict[tuple[str, str], set] = {}
    for row in memberships or ():
        if not isinstance(row, dict):
            continue
        if collapsed_text(row.get("relation")) == "associated_with":
            continue
        member = collapsed_text(row.get("member_node_id"))
        group = collapsed_text(row.get("era_node_id"))
        kind = kinds.get(member)
        if not kind or not group:
            continue
        grouped.setdefault((group, tp.LANES_BY_EVENT_KIND[kind]), set()).add(member)
    return [
        tp.validate_lane_row({
            "group_id": group, "lane": lane, "episode_node_ids": sorted(members),
        })
        for (group, lane), members in sorted(
            grouped.items(), key=lambda item: (item[0][0], tp.LANES.index(item[0][1]))
        )
    ]


def _era_is_a_dated_stretch(group: object) -> bool:
    """Does this era COUNT toward tiling (design §9.1)?

    Two conditions and no third: it is a ``stretch`` (a thread has no honest
    end, ruling 21), and the person gave it BOTH bounds. A thread and an
    undated era never count — an era nobody dated cannot tile anything, and
    reading a bound off the moments sorted into it is the founder's own
    "College 1990–1991 before High School" all over again.
    """
    row = group if isinstance(group, dict) else {}
    if collapsed_text(row.get("era_kind")) != "stretch":
        return False
    found = set()
    for claim in row.get("claims") or ():
        kind = collapsed_text(claim.get("event_kind"))
        if (kind in PERIOD_BOUND_EVENT_KINDS
                and collapsed_text(claim.get("claim_type")) in tc.DATED_CLAIM_TYPES):
            found.add(kind)
    return set(PERIOD_BOUND_EVENT_KINDS) <= found


def frame_display_rows(nodes: list[dict], groups: dict, *, decisions: object) -> list[dict]:
    """One row per age frame: how it is told, and what may be proposed.

    `era_memberships.FRAME_DISPLAY_RULE_TEXT`, applied. The mode comes from
    the person's own decision and defaults to ``frame``; ``proposal_pending``
    is TRUE only when there is no active ``eras`` decision AND the frame's
    dated stretch eras tile it (`cross_dating.frame_tiling`, the one
    arithmetic). ``leftover`` is the geometric truth — the frame's uncovered
    sub-intervals — because that is what the leftover row draws, and naming
    that row is the host's job, not this one's.

    Nothing here applies anything. A proposal is a line on a frame row.
    """
    chosen = era.frame_display_rows_by_frame(decisions)
    intervals = [
        node.get("best_temporal_value")
        for node in nodes
        if node.get("event_kind") == tp.NAMED_ERA_EVENT_KIND
        and node.get("best_temporal_value") is not None
        and _era_is_a_dated_stretch(groups.get(collapsed_text(node.get("node_id"))))
    ]
    rows: list[dict] = []
    for node in nodes:
        if node.get("event_kind") != tp.AGE_FRAME_EVENT_KIND:
            continue
        frame_id = collapsed_text(node.get("node_id"))
        span = node.get("definition_span")
        if not frame_id or not isinstance(span, dict):
            continue
        tiling = cd.frame_tiling(span, intervals)
        decision = chosen.get(frame_id) or {}
        mode = collapsed_text(decision.get("mode")) or era.FRAME_DISPLAY_DEFAULT_MODE
        rows.append({
            "frame_id": frame_id,
            "frame_display": mode,
            "proposal_pending": bool(mode != "eras" and tiling["tiled"]),
            "leftover": [dict(row) for row in tiling["leftover"]],
            "decision_id": collapsed_text(decision.get("decision_id")) or None,
        })
    rows.sort(key=lambda row: row["frame_id"])
    return rows


def observed_envelope(memberships: object, node_index: dict, era_node_id: str) -> dict | None:
    """One named era's COVERAGE of its explicit members — never a bound.

    This is the single most dangerous number in the whole design and the
    docstring is where the danger is named: the founder's Timeline said
    *"College 1990-1991"* because an era was DATED from whatever got sorted into
    it. So the envelope is computed, published on its own key, stamped
    ``basis: order``, and is never written into ``best_temporal_value``,
    ``definition_span`` or ``possible_temporal_value``. It says what the era's
    members happen to span. It does not say when the era was.
    """
    dated = []
    for row in memberships or ():
        if collapsed_text(row.get("era_node_id")) != collapsed_text(era_node_id):
            continue
        node = node_index.get(collapsed_text(row.get("member_node_id"))) or {}
        record = chrono.from_dict(node.get("best_temporal_value"))
        if record is not None:
            dated.append({"date": record})
    if not dated:
        return None
    span = cd.span_from_dated(dated)
    return span.to_dict() if span is not None else None


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
    relevance: dict | None = None,
    life_view: str | None = None,
    identity: dict | None = None,
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
    basis = twi.node_claim_basis(best)
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
            "life_view": life_view or _life_view(best, as_of),
            **({"possible_temporal_value": possible.to_dict()}
               if possible is not None else {}),
            **(relevance or {}),
            # Event identity I1 (§3.5), additive: absent means this node's
            # tellings carry no identity record, which is the state every node
            # in every vault is in until somebody binds one.
            **(identity or {}),
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


def work_item_score(
    kind: str, *, system_value: float = 0.0, event_kind: object = None,
    subject_ref: object = None, resolved: bool = False,
) -> dict:
    """The public door onto :func:`_score_components` (event identity I3).

    §4.1's own ruling: "identity pairs enter the EXISTING work-item value
    scoring like every other kind... never a score of its own." A CALLER
    OUTSIDE THIS MODULE is not a node-derivation caller and has no business
    reaching into an underscore-prefixed helper across a module boundary —
    this is the one home that formula lives in, exposed rather than re-typed
    a second time (ADR 0021). Deliberately named rather than importing this
    module BY name in a docstring: `compile`'s own reachability sweep
    (`test_the_binder_never_runs_inside_compile`) greps this file's bytes for
    the identity-decision module's name, and a docstring mention would trip
    it exactly as a real import would.
    """
    return _score_components(
        kind, system_value=system_value, event_kind=event_kind,
        subject_ref=subject_ref, resolved=resolved,
    )


def work_item_surfaces(
    kind: str, *, event_kind: object = None, subject_ref: object = None, resolved: bool = False,
) -> tuple[str, ...]:
    """The public door onto :func:`_surfaces_for` — see :func:`work_item_score`."""
    return _surfaces_for(kind, event_kind=event_kind, subject_ref=subject_ref, resolved=resolved)


#: D4 (Timeline Fix 07): ONE NODE, ONE QUESTION. Two derivation paths reached
#: the same node with different `requested_field`s and minted two rows — the
#: founder saw "When did San Diego begin?" and "When did San Diego — span —
#: happen?" side by side. Highest precedence first, and the order is an
#: argument: you cannot refine a date you do not have, and you cannot date a
#: person you cannot identify.
WORK_ITEM_PRECEDENCE = (
    "identity_uncertain",
    "contradiction",
    # Event identity I3, just below `contradiction`: both are the substrate's
    # own grouping guess meeting a disagreement, and an over-merge audit is
    # the more urgent of the two (it names an EXISTING bind the person may
    # need to undo) while a same-event pair is still a proposal nothing has
    # committed to.
    "possible_overmerge",
    "same_event",
    # §8.3: "which time in San Diego?" is strictly more answerable than "when
    # did this happen?" about the same node, and answering it answers both.
    # E-L2b: above the ambiguity pair and below `contradiction`. A stay whose
    # dates are wrong makes every question that reads its span wrong too, so
    # it is asked before "which time in Cedarport was this".
    "residence_overlap",
    "place_ambiguous",
    "tenure_ambiguous",
    "missing_anchor",
    "precision_gap",
)


def _precedence(kind: object) -> int:
    name = collapsed_text(kind)
    return (WORK_ITEM_PRECEDENCE.index(name) if name in WORK_ITEM_PRECEDENCE
            else len(WORK_ITEM_PRECEDENCE))


def _union_refs(*rows: dict, field_name: str) -> list[str]:
    out: set[str] = set()
    for row in rows:
        out |= set(row.get(field_name) or ())
    return sorted(out)


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
    score_rule: object = None,
    by_node: dict | None = None,
    diagnostics: list | None = None,
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
    # Timeline Fix 07 D3, the REFUSING backstop. Two ways an item arrives with
    # no sentence, and both are recorded rather than silent: the composer
    # already declined (`compose_question` returned None), or a hand-written
    # intent still carries a template leak. Prompt prose alone is not
    # certifiable (ADR 0028's audit); a deterministic refusal is.
    intent = collapsed_text(prompt_intent)
    withheld = ""
    if intent:
        findings = cl.lint_question(intent)
        if findings:
            withheld = f"{findings[0]['lint']}: {findings[0]['detail']}"
            intent = ""
    elif prompt_intent is None:
        withheld = "question_withheld: no sentence could be composed for this node"
    payload = {
        "kind": kind,
        "state": "open",
        "subject_ref": subject_ref,
        "event_ref": event_ref,
        "node_ref": node_ref,
        "requested_field": requested_field,
        "prompt_intent": intent or None,
        "withheld_reason": withheld or None,
        "claim_refs": list(claim_refs),
        "evidence_refs": list(evidence_refs),
        "allowed_surfaces": list(
            _surfaces_for(
                kind, event_kind=event_kind, subject_ref=subject_ref, resolved=subject_resolved
            )
        ),
    }
    payload.update(scores)
    if collapsed_text(score_rule):
        # Which arithmetic minted `system_value`. The envelope carries the
        # release's own `SCORE_FORMULA_VERSION`; this is the item saying it for
        # itself, so a row read alone is still readable (O-E6, design §7).
        payload["score_rule"] = collapsed_text(score_rule)
    try:
        row = tp.validate_temporal_work_item(payload, now=now)
    except TemporalContractError:
        return ""
    key = row["work_item_id"]
    if withheld and diagnostics is not None:
        diagnostics.append({
            "finding": "question_withheld",
            "work_item_id": key,
            "node_id": collapsed_text(node_ref) or None,
            "detail": withheld,
        })
    node = collapsed_text(node_ref)
    if node and by_node is not None and key not in sink:
        standing_key = by_node.get(node)
        standing = sink.get(standing_key) if standing_key else None
        if standing is not None and standing_key != key:
            # D4: one node, one question. The higher-precedence kind survives
            # and ABSORBS the other's evidence — nothing is lost, and the
            # loser's kind is recorded on the survivor so the page can still
            # say what else this node implies.
            if _precedence(kind) < _precedence(standing.get("kind")):
                merged = dict(row)
                merged["claim_refs"] = _union_refs(row, standing, field_name="claim_refs")
                merged["evidence_refs"] = _union_refs(row, standing, field_name="evidence_refs")
                merged["superseded_kinds"] = sorted(
                    set(standing.get("superseded_kinds") or ())
                    | set(row.get("superseded_kinds") or ())
                    | {collapsed_text(standing.get("kind"))}
                )
                sink.pop(standing_key, None)
                components.pop(standing_key, None)
                sink[key] = tp.validate_temporal_work_item(merged, now=now)
                components[key] = scores
                by_node[node] = key
                return key
            merged = dict(standing)
            merged["claim_refs"] = _union_refs(standing, row, field_name="claim_refs")
            merged["evidence_refs"] = _union_refs(standing, row, field_name="evidence_refs")
            merged["superseded_kinds"] = sorted(
                set(standing.get("superseded_kinds") or ()) | {kind}
            )
            sink[standing_key] = tp.validate_temporal_work_item(merged, now=now)
            return standing_key
    current = sink.get(key)
    if current is None:
        sink[key] = row
        components[key] = scores
        if node and by_node is not None:
            by_node.setdefault(node, key)
        return key
    merged = dict(current)
    for field_name in ("claim_refs", "evidence_refs"):
        merged[field_name] = sorted(set(current.get(field_name) or ()) | set(row.get(field_name) or ()))
    if row.get("system_value", 0.0) > current.get("system_value", 0.0):
        for name in (*tp.WORK_ITEM_SCORE_FIELDS, "score_rule"):
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


def _evidence_claim_refs(group: dict) -> list[str]:
    """Every claim behind this node, dated or not.

    `_dated_claim_refs` is the right set for a contradiction — the claims that
    DISAGREE — and the wrong one here: a co-located moment has no dated claim
    at all, and an item citing nothing cannot be closed by an answer.
    """
    return [
        collapsed_text(claim.get("claim_id"))
        for claim in group["claims"]
        if collapsed_text(claim.get("claim_id"))
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
    episode_records: object = (),
    era_views: object = (),
    roster_snapshot: object = (),
    constraints: object = (),
    membership_assertions: object = (),
    display_decisions: object = (),
    frame_display_decisions: object = (),
    landmark_entries: object = (),
    birth_date: object = None,
    owner_ref: object = None,
    projection_generation: int = 0,
    now: object = None,
) -> CalculatedTimeline:
    """Active claims in, a whole calculated timeline out. Pure and deterministic.

    ``active_index`` is ``temporal_store.fold_active_index``'s mapping (or its
    ``claims`` list, or a bare list of claim mappings). ``constraints`` are the
    :class:`~temporal_claims.OrderingConstraint` records a drag wrote.
    ``membership_assertions``, ``display_decisions`` and
    ``frame_display_decisions`` are ``era_memberships.active_era_memberships``
    / ``active_era_displays`` / ``active_frame_displays``' rows,
    and ``landmark_entries`` are ``landmark_projection.load_landmark_sources``'.
    All three arrive as ARGUMENTS rather than being read here, for the reason
    ``roster_snapshot`` does: this function must stay a pure function of what it
    is handed, so a test can hand it two receipts and assert one membership.

    ``episode_records`` is the identity layer's own fold input (event identity
    I1, design §3.5): ``{"operations", "bindings", "manifest"}``, or a bare
    sequence read as the bindings alone. It is a SIBLING of
    ``event_resolution_records`` and never touches ``event_ref``, whose v247
    era meaning is unchanged — an era-bound claim is refused as a binding
    target and reported, exactly as `episode_fold_contract` decided in I0.
    ``episode_fold.load_episode_records`` is what reads them off a vault; this
    function stays pure and is handed the result.

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

    # Event identity I1 (§3.5). Built BEFORE grouping because grouping is what
    # it changes, and built from the RESOLVED claims below rather than these —
    # a telling ref is a function of the claim's source, which subject
    # resolution never touches, so either set gives the same map and the
    # cheaper one is the one already in hand. The refusals (§5.4) are raised
    # inside the constructor: a fold that drew half a projection and then
    # refused would be worse than one that refused.
    identity = ef.EpisodeIdentity(claims, episode_records)

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
    # E-L2a: the landmark index is built HERE rather than at its old reader
    # below, because participation episodes are grouping input and grouping is
    # the first thing that reads it. One index, three readers.
    entry_index = _landmark_entry_index(landmark_entries)
    participation = lp.ParticipationEpisodes(resolved, landmark_entries)
    # The join the containment window needs: a container the binder has not
    # bound is named by `episode_containers.container_episode_id`, and without
    # this the `part_of` record the rung files names an episode the projection
    # has no node for — which is exactly why a residence could never contain a
    # story. Only `node_of_episode` is extended, never `episode_of_node`: a
    # participation episode is minted by the recorder's own entry rather than
    # by an identity operation, so it has no member tellings of its own and
    # publishing `telling_count: 0` on it would be a fact nobody filed.
    identity.adopt_participation_episodes(participation.node_of_episode)
    groups = _group_claims(resolved, owner_ref=owner, era_views=era_views,
                           identity=identity, participation=participation)
    roster_names = _roster_names(roster_snapshot)
    displays = {
        node_id: _subject_display(group["subject"], group["claims"], roster_names)
        for node_id, group in groups.items()
    }
    # Timeline Fix 07: one derivation of "what is this node, in words", read by
    # the title AND by every question about it, so the two cannot disagree.
    whats = {
        node_id: _node_what(group, displays[node_id])
        for node_id, group in groups.items()
    }
    owner_flags = {
        node_id: _is_owner_subject(group, owner) for node_id, group in groups.items()
    }
    place_refs, place_name_keys = _place_keys(roster_snapshot)
    place_flags = {
        node_id: _is_place_subject(group, displays[node_id], place_refs, place_name_keys)
        for node_id, group in groups.items()
    }
    labels = {
        node_id: (collapsed_text(group.get("era_label"))
                  or _node_label(displays[node_id], group["event_kind"],
                                 what=whats[node_id],
                                 is_owner=owner_flags[node_id]))
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
    # After the durations (a duration is what gives an open-ended stay its far
    # end) and before the edges (a span is an ordinary seed for the fixpoint).
    for node_id in sorted(participation.seeds):
        if node_id in groups:
            _apply_participation_span(groups[node_id], calculated[node_id],
                                      diagnostics=diagnostics)
    # E-L2a retires `place_co_location` into the ONE containment rung
    # (design §0.2 M1, §4.1). What the pass could still do that the rung
    # cannot — ask WHICH of several stays a mention belongs to — stays here as
    # its own pass, and the inference half is gone: a member's window is now
    # the containment record's outer range, computed from what was FILED.
    ambiguity = _apply_entity_ambiguity(
        groups, calculated,
        participation=participation,
        roster_snapshot=roster_snapshot,
        entry_index=entry_index,
        owner=owner,
        birth=birth,
        displays=displays,
        place_flags=place_flags,
        diagnostics=diagnostics,
    )
    # §3.2's other half of "one home at a time": the rung's refusal asks WHICH
    # stay a story belongs to; this asks the person to reconcile two stays that
    # claim the same weeks. Both read the person's own reconciled spans, both
    # are pure, and neither writes a value.
    overlaps = _residence_overlaps(
        groups, calculated,
        participation=participation,
        entry_index=entry_index,
        owner=owner,
        birth=birth,
        displays=displays,
        place_flags=place_flags,
        diagnostics=diagnostics,
    )
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
    # Timeline Fix 07 D1 — THE ORIGIN FLOOR (lifehug-platform#761). The owner's
    # birth is the origin of the coordinate system, so an interval on the
    # owner's own axis that opens before it is claiming a stretch the system
    # already knows to be empty — and it is that opening bound the certainty
    # chart draws and the ordering questions enumerate. Only INFERRED bounds
    # are clamped: a date somebody STATED before their own birth is a
    # contradiction to surface, never a number to quietly rewrite.
    for node_id in sorted(placed):
        group = groups.get(node_id)
        if group is None or not _is_owner_subject(group, owner):
            continue
        clamped = _clamp_to_origin(placed[node_id], birth)
        if clamped is not None:
            placed[node_id] = clamped
            diagnostics.append({
                "finding": "origin_floor_applied",
                "node_id": node_id,
                "detail": "an inferred interval opened before the birth origin",
            })
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
    frames: tuple = ()
    provisional_node: dict | None = None
    birth_node_id: str | None = None
    birth_origin_basis: str | None = None
    resolved_origin: dict | None = None
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
        frames = cd.age_frames(
            resolved_origin["best"], as_of=as_of,
            death=_owner_death(groups, calculated, placed, owner),
            origin_basis=birth_origin_basis,
        )
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

    # The owner relevance layer (eras E2). Needs the origin resolved above —
    # `origin_best` is the birth (explicit or provisional) `_age_frame_nodes`
    # just used, falling back to the plain reconciled `birth` (used for
    # `_reconcile_group`) when neither exists — reading the origin twice would
    # be two definitions of "the owner's birthday".
    origin_best = resolved_origin["best"] if resolved_origin is not None else birth
    relevance = {
        node_id: _owner_relevance(
            groups[node_id], best=placed.get(node_id), entry_index=entry_index,
            owner=owner, birth=origin_best,
        )
        for node_id in sorted(groups)
    }

    possibilities = {
        node_id: _within_only_possibility(
            node_id, groups[node_id], calculated[node_id], placed.get(node_id),
            edges, constraints=constraints, frame_values=frame_values,
        )
        for node_id in sorted(groups)
    }
    containment_conflicts: dict[str, list] = {}
    # Event identity I1, §5.3 — CONTAINMENT'S INHERITED VALUE. A member the
    # person put INSIDE an episode and never dated renders the episode's own
    # span as a POSSIBLE outer range: it lands in `possible_temporal_value`
    # beside E3's `within`, which is what keeps every clause of the rule
    # structural rather than asserted. It is never `best_temporal_value`, so
    # it cannot override, cannot anchor and cannot be mistaken for a date the
    # person gave; `placed` is untouched, so the member's own precision
    # question is minted exactly as it was before the containment existed.
    if identity.applies:
        for node_id in sorted(groups):
            if possibilities.get(node_id) is not None or placed.get(node_id) is not None:
                continue
            tellings = {identity.telling_for(claim)
                        for claim in groups[node_id]["claims"]}
            contained = identity.containment_value(
                tellings, placed=placed, labels=labels,
            )
            if contained is not None:
                possibilities[node_id] = contained
                continue
            # §4.2: containments whose person-dated spans cannot both hold.
            # No window is drawn — that is `containment_value` returning None,
            # unchanged — AND the disagreement is now said out loud, which is
            # the half the old "more than one container, so nothing" swallowed.
            conflict = identity.containment_conflict(tellings, placed=placed)
            if conflict:
                containment_conflicts[node_id] = [
                    {"episode_id": episode_id, "episode_node_id": episode_node_id,
                     "span": chrono.display_date(span, with_basis=False),
                     "label": labels.get(episode_node_id) or episode_id}
                    for episode_id, episode_node_id, span in conflict
                ]
    identity_blocks = {
        node_id: identity.node_block(node_id, groups[node_id]["claims"])
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
            relevance=relevance[node_id],
            life_view=_relevance_life_view(
                relevance[node_id], best=placed.get(node_id), birth=origin_best,
                as_of=as_of, diagnostics=diagnostics, node_id=node_id,
                birth_node_id=birth_node_id,
            ),
            identity=identity_blocks.get(node_id),
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

    # Memberships (eras E2). Arithmetic for the frames, receipts for the named
    # eras, and one display role decided over the union of both.
    mark = clock()
    node_index = {collapsed_text(row.get("node_id")): row for row in nodes}
    on_axis = {
        node_id: relevance[node_id]["owner_timeline_relation"] in tp.AXIS_RELATIONS
        for node_id in relevance
    }
    memberships = _frame_memberships(nodes, frames, on_axis=on_axis)
    memberships.extend(
        _asserted_memberships(membership_assertions, node_ids=set(node_index))
    )
    memberships = _apply_display_roles(
        memberships, decisions=display_decisions, node_index=node_index
    )
    # A named era's envelope is COVERAGE of its explicit members. E3 (now
    # merged) mints the `named_era` nodes this loop draws the envelope onto.
    for index, row in enumerate(nodes):
        if row.get("event_kind") != "named_era":
            continue
        envelope = observed_envelope(memberships, node_index, row.get("node_id"))
        if envelope is not None:
            nodes[index] = tp.validate_calculated_timeline_node(
                {**row, "observed_envelope": envelope}
            )
    # E-L2d (design §9.1-§9.2). Both are pure functions of what the fold has
    # already decided — the memberships above, the episodes' own kinds, and
    # the person's own display decisions — so they cost one pass and nothing
    # else, and they are the same on every rebuild.
    lanes = lane_rows(nodes, memberships)
    frames_display = frame_display_rows(nodes, groups, decisions=frame_display_decisions)
    timings["memberships"] = clock() - mark

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
        whats=whats,
        owner_flags=owner_flags,
        place_flags=place_flags,
        roster_snapshot=roster_snapshot,
        ambiguity=ambiguity,
        residence_overlaps=overlaps,
        containment_conflicts=containment_conflicts,
        owner=owner,
        now=now,
    )
    timings["work_items"] = clock() - mark
    timings["total"] = clock() - started

    return CalculatedTimeline(
        nodes=tuple(nodes),
        work_items=tuple(items),
        lanes=tuple(lanes),
        frame_display=tuple(frames_display),
        # In-memory only; see the field's own note. This is the ONE answer to
        # "what are this life's age frames", handed to whoever asks instead of
        # being re-derived by them.
        age_frames=tuple(frames),
# Derived, never stored (O-E6, design §7 row 6): every id these items
        # have ever been addressed by, mapped onto the id they are addressed by
        # now. Computed here so it is published in the SAME generation as the
        # items it describes — a reader can never hold a map for a different
        # set — and so deleting the file and rebuilding is byte-identical.
        work_item_aliases=twi.work_item_aliases(items),
        # Event identity I1 (§3.5). All four are derived from `episode_records`
        # in this same generation, so a reader can never hold a table that
        # describes a different drawing.
        # E-L2a: the identity layer's aliases, plus a participation stay's
        # own re-key when its first stated start moved its discriminator. The
        # identity layer wins a collision: a person's decision outranks an
        # arithmetic one, and this map is read to FOLLOW citations.
        node_aliases={**participation.node_aliases, **identity.node_aliases()},
        episode_aliases=identity.episode_aliases(),
        identity_rule_version=efc.IDENTITY_RULE_VERSION,
        identity_diagnostics=identity.identity_diagnostics(),
        memberships=tuple(memberships),
        timings={phase: round(timings.get(phase, 0.0), 9) for phase in TIMING_PHASES},
        score_components=components,
        reach=reach,
        diagnostics={
            "findings": diagnostics,
            "claims": len(claims),
            "nodes": len(nodes),
            "memberships": len(memberships),
            "edges": len(edges),
            "unplaced": sorted(
                node_id for node_id in groups if placed.get(node_id) is None
            ),
        },
        projection_generation=projection_generation,
    )


def _has_explicit_owner_birth(groups: dict, placed: dict, owner: object) -> bool:
    """Does this vault hold a birth for the OWNER that somebody actually stated?

    §3.1's compatibility rule read as a predicate: an owner birth is a group
    whose `event_kind` is `birth` and whose subject is the owner — under the
    canonical `self` or under the legacy domain-word mention `"birth"` that
    pre-O-E0b extraction minted, both of which resolve to the same person.

    §3.2's rule read as the second half: the node's published class must be
    ``explicit``. A **provisional origin calculated from age statements is not
    a birthday**, so it leaves the ask open; that is the whole reason this is a
    basis check rather than an existence check.
    """
    wanted = normalized_mention_key(owner)
    for node_id, group in groups.items():
        if collapsed_text(group.get("event_kind")) != twi.BIRTH_ORIGIN_EVENT_KIND:
            continue
        subject = group.get("subject")
        if normalized_mention_key(subject) != wanted and not twi.is_birth_anchor(subject):
            continue
        if twi.is_explicit_origin(placed.get(node_id)):
            return True
    return False


#: Bases that mean SOMEBODY SAID SO. A stated date before the origin is a
#: contradiction for the person to settle, never a bound to silently move.
STATED_BASES = ("stated", "document")

#: The provenance rule one clamp records, so a moved bound is explainable.
ORIGIN_FLOOR_RULE = "origin_floor"


def _clamp_to_origin(record: object, birth: object):
    """The record with its `earliest` raised to the birth origin, or ``None``.

    ``None`` means "nothing to do" — no birth, no record, a stated basis, or an
    interval that already starts at or after the origin. The clamp keeps every
    other field and appends one provenance entry, because a bound that moved
    with no reason attached is exactly the unexplainable number ADR 0027
    forbids the score to rest on.
    """
    if birth is None or record is None:
        return None
    parsed = record if isinstance(record, chrono.DateRecord) else chrono.from_dict(record)
    if parsed is None or parsed.basis in STATED_BASES:
        return None
    floor = birth.earliest
    if not floor or not parsed.earliest or parsed.earliest >= floor:
        return None
    latest = parsed.latest
    if latest and latest < floor:
        # The whole interval is before the origin: that is a disagreement with
        # the birthday, not a bound to slide, and it stays for the contradiction
        # machinery to surface.
        return None
    return replace(
        parsed,
        earliest=floor,
        provenance=parsed.provenance + ({"rule": ORIGIN_FLOOR_RULE,
                                         "was": parsed.earliest,
                                         "origin": floor},),
    )


def _rival_readings(calculated_row: dict) -> str:
    """``"20 March 1990 and 1991"`` — the dates a contradiction is between.

    A contradiction that names neither reading is not answerable; it is a
    before/after against something unrelated, which is exactly the move
    `timeline_interaction.work_item_probe` already refuses.
    """
    records = [calculated_row.get("best")] + list(calculated_row.get("alternates") or ())
    shown: list[str] = []
    for record in records:
        parsed = record if isinstance(record, chrono.DateRecord) else chrono.from_dict(record)
        if parsed is None:
            continue
        text = chrono.display_date(parsed, with_basis=False)
        if text and text not in shown:
            shown.append(text)
    return " and ".join(shown[:2])


def _node_what(group: dict, display: str) -> str:
    """The node's own HUMAN text — what a person would call this thing.

    An era's own label first (somebody named it), then the longest
    ``event_mention`` among its claims (what the person called the event, kept
    verbatim beside the fact since v239), then the subject display. Never the
    ``event_kind``: that is the string the founder read on his own page.
    """
    era = collapsed_text(group.get("era_label"))
    if era:
        return era
    mentions = [collapsed_text(claim.get("event_mention")) for claim in group.get("claims", ())]
    mentions = [text for text in mentions if text]
    if mentions:
        return max(mentions, key=len)
    return collapsed_text(display)


def _is_owner_subject(group: dict, owner: object) -> bool:
    """Is this node about the vault's owner — the person reading the question?"""
    if collapsed_text(group.get("subject")) == collapsed_text(owner):
        return True
    return any(
        is_owner_reference_only(claim.get("subject_mention"))
        for claim in group.get("claims", ())
    )


def _place_keys(roster_snapshot: object) -> tuple[set, set]:
    """``(refs, name keys)`` for every PLACE the roster knows.

    A ``span`` whose subject is a place is a residence, and a residence reads
    as "When were you in Yucaipa?" rather than "When was Yucaipa?". The signal
    is the roster's OWN DECLARED TYPE — never a guess from the words, and never
    `entity_type="place"` forced over a person roster, which would mint a place
    ref for every person in it and call the founder's children residences.
    """
    if not isinstance(roster_snapshot, dict):
        return set(), set()
    if collapsed_text(roster_snapshot.get("type")) != "place":
        return set(), set()
    try:
        index = ident.roster_index(roster_snapshot)
    except TemporalContractError:
        return set(), set()
    keys = set(index.by_name_key) | set(index.by_alias_key)
    return set(index.refs), keys


def _is_place_subject(group: dict, display: str, refs: set, keys: set) -> bool:
    if collapsed_text(group.get("subject")) in refs:
        return True
    return normalized_mention_key(display) in keys


#: The nouns an anchor handle trails after the subject it is really about —
#: "James's birth", "my dad's graduation". Stripping one is how the handle
#: becomes a NAME the roster can be asked about (D2).
ANCHOR_EVENT_NOUNS = (
    "birth", "birthday", "death", "funeral", "wedding", "marriage",
    "graduation", "move", "job", "school", "military service", "passing",
)
_ANCHOR_EVENT_NOUN_RE = re.compile(
    r"(?:['\u2019]s|s['\u2019])?\s+(" + "|".join(
        re.escape(word) for word in sorted(ANCHOR_EVENT_NOUNS, key=len, reverse=True)
    ) + r")\s*$",
    re.IGNORECASE,
)
_TRAILING_POSSESSIVE_RE = re.compile(r"['\u2019]s$|s['\u2019]$")

#: The event kind each trailing noun names, so "James's birth" can be checked
#: against the James—birth node rather than against any James node at all.
ANCHOR_NOUN_EVENT_KINDS = {
    "birth": "birth", "birthday": "birth",
    "death": "death", "funeral": "death", "passing": "death",
    "wedding": "married", "marriage": "married",
    "graduation": "graduation", "move": "move", "job": "job",
    "school": "school", "military service": "military",
}


def _anchor_handle_subject(text: object) -> tuple[str, str]:
    """``"James's birth"`` → ``("James", "birth")``; a bare name keeps ``""``.

    Deterministic and deliberately shallow: one trailing event noun from
    :data:`ANCHOR_EVENT_NOUNS`, one possessive. Anything richer is a clause,
    and a clause is not a name.
    """
    body = collapsed_text(text)
    if not body:
        return "", ""
    match = _ANCHOR_EVENT_NOUN_RE.search(body)
    if not match:
        return body, ""
    subject = _TRAILING_POSSESSIVE_RE.sub("", body[: match.start()]).strip()
    noun = match.group(1).lower()
    return (subject or body), ANCHOR_NOUN_EVENT_KINDS.get(noun, noun)


def _dated_node_for(groups: dict, placed: dict, ref: str, event_kind: str) -> str:
    """The node id that already answers this handle, or ``""``.

    D2, the founder's own defect: *"When was James's birth? — no date yet"* sat
    on the page beside *"20 March 1990 · James — birth · two claims disagree"*.
    The handle had never been looked up: an unresolved anchor string was minted
    straight into a `missing_anchor`. This is the lookup.
    """
    for node_id in sorted(groups):
        group = groups[node_id]
        if collapsed_text(group.get("subject")) != collapsed_text(ref):
            continue
        if event_kind and collapsed_text(group.get("event_kind")) != event_kind:
            continue
        if placed.get(node_id) is not None:
            return node_id
    return ""


def _derive_work_items(
    *, groups, calculated, placed, edges, diagnostics, records, by_mention, displays,
    whats=None, owner_flags=None, place_flags=None, roster_snapshot=(),
    ambiguity=None, residence_overlaps=None, containment_conflicts=None, owner, now
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
    #: D4: node ref -> the ONE item id standing for it.
    by_node: dict[str, str] = {}
    whats = whats or {}
    owner_flags = owner_flags or {}
    place_flags = place_flags or {}
    ambiguity = ambiguity or {}
    containment_conflicts = containment_conflicts or {}
    residence_overlaps = residence_overlaps or {}

    def sentence(item_kind, node_id, group, **extra):
        """This node's question through the ONE composer (D3)."""
        return compose_question(
            item_kind,
            group.get("event_kind"),
            who=displays.get(node_id, group.get("subject")),
            what=whats.get(node_id) or displays.get(node_id, group.get("subject")),
            is_owner=bool(owner_flags.get(node_id)),
            is_place=bool(place_flags.get(node_id)),
            **extra,
        )

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
            by_node=by_node,
            diagnostics=diagnostics,
            now=now,
        )
        if item_id:
            reach[item_id] = raw

    # -- anchor handles: already answered, ambiguous, or genuinely new (D2) --
    #
    # The founder read "When was James's birth? — no date yet" beside a dated
    # James — birth node with two rival claims on it. To him that was one
    # question asked twice, and the second copy was false. The handle now goes
    # through the roster before it is allowed to become a date question:
    # one candidate with a dated node mints NOTHING (the anchor resolves late
    # and the next fold binds it), two candidates mint an IDENTITY question
    # ("which James?"), and only an unrecognised name asks for a date.
    for key in sorted(handle_text):
        raw = len(handle_reach.get(key, ()))
        text = handle_text[key]
        refs = sorted(handle_claims.get(key, ()))
        name, noun_kind = _anchor_handle_subject(text)
        cands = ident.candidates_for(name, roster_snapshot) if name else ()
        if len(cands) == 1:
            answered = _dated_node_for(groups, placed, cands[0]["ref"], noun_kind)
            if answered:
                diagnostics.append({
                    "finding": "anchor_resolved_late",
                    "anchor": text,
                    "subject_ref": cands[0]["ref"],
                    "node_id": answered,
                })
                continue
        if len(cands) > 1:
            names = " or ".join(c["name"] or c["ref"] for c in cands)
            item_id = _mint_work_item(
                items,
                components,
                kind="identity_uncertain",
                subject_ref=ident.unresolved_subject_ref(text),
                requested_field=ident.IDENTITY_REQUESTED_FIELD,
                prompt_intent=f"Which {name} is this: {names}?",
                claim_refs=refs,
                system_value=min(1.0, raw / REACH_SATURATION),
                by_node=by_node,
                diagnostics=diagnostics,
                now=now,
            )
            if item_id:
                reach[item_id] = raw
            continue
        item_id = _mint_work_item(
            items,
            components,
            kind="missing_anchor",
            subject_ref=ident.unresolved_subject_ref(text),
            requested_field="date",
            prompt_intent=compose_anchor_question(text),
            claim_refs=refs,
            system_value=min(1.0, raw / REACH_SATURATION),
            by_node=by_node,
            diagnostics=diagnostics,
            now=now,
        )
        if item_id:
            reach[item_id] = raw

    # -- the birth origin: the coordinate system, open until somebody says it -
    #
    # O-E6 (`eras.md` §3, §7). Two things changed and both are the same
    # correction: this item used to exist only when an age claim had already
    # tripped over its absence, and it used to be worth its reach alone. The
    # birth origin is what every age frame is DERIVED from, so a vault with no
    # birthday and nothing yet dated by age is precisely the vault that needs
    # the question — and scored it zero.
    #
    # Closure is by the published CLASS of the owner's birth, never by the
    # presence of a node: §3.2's provisional origin arrives as ``calculated``
    # and deliberately does not close the explicit-birthday ask.
    age_claims = sorted(
        {
            row.get("claim_id")
            for row in diagnostics
            if row.get("finding") == "age_without_birth_anchor" and row.get("claim_id")
        }
    )
    if not _has_explicit_owner_birth(groups, placed, owner):
        counted = len(age_claims)
        placeable = (
            f" {counted} thing{'s' if counted != 1 else ''} "
            "you dated by age can be placed once it is known."
            if counted
            else ""
        )
        item_id = _mint_work_item(
            items,
            components,
            kind=twi.BIRTH_ORIGIN_KIND,
            subject_ref=owner,
            event_kind=twi.BIRTH_ORIGIN_EVENT_KIND,
            requested_field=twi.REQUESTED_FIELD_BIRTH_DATE,
            subject_resolved=True,
            prompt_intent=f"What is your date of birth?{placeable}",
            claim_refs=age_claims,
            system_value=twi.birth_origin_system_value(counted),
            score_rule=twi.BIRTH_ORIGIN_SCORE_RULE,
            diagnostics=diagnostics,
            now=now,
        )
        if item_id:
            reach[item_id] = counted

    # -- missing anchors: a duration with no start ------------------------
    for row in sorted(
        (r for r in diagnostics if r.get("finding") == "duration_without_start"),
        key=lambda r: (r.get("node_id") or "", r.get("claim_id") or ""),
    ):
        node_id = row.get("node_id")
        group = groups.get(node_id)
        if group is None or collapsed_text(group["event_kind"]) in UNASKABLE_EVENT_KINDS:
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
            prompt_intent=sentence("missing_anchor", node_id, group),
            claim_refs=[row.get("claim_id")] if row.get("claim_id") else [],
            evidence_refs=_evidence_refs(group),
            system_value=min(1.0, node_reach.get(node_id, 0) / REACH_SATURATION),
            by_node=by_node,
            diagnostics=diagnostics,
            now=now,
        )

    # -- precision gaps ---------------------------------------------------
    for node_id in sorted(groups):
        group = groups[node_id]
        # §7.1 / H6: render-placeable is not date-resolved. A member drawn
        # inside a container has a WINDOW, never a value of its own, so
        # `placed` holds nothing for it and the precision question survives —
        # structurally, rather than by an exclusion list a later pass could
        # forget to update.
        best = placed.get(node_id)
        if not _wants_precision(best, group["event_kind"]):
            continue
        # D5: an age frame's boundary is arithmetic off the birth origin, never
        # a question (ADR 0030). "When did Childhood end?" is not askable.
        if collapsed_text(group["event_kind"]) in UNASKABLE_EVENT_KINDS:
            continue
        raw = node_reach.get(node_id, 0)
        target = _precision_target(group["event_kind"])
        intent = sentence(
            "precision_gap" if best is None else "precision_gap_coarse",
            node_id, group, target=target,
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
            by_node=by_node,
            diagnostics=diagnostics,
            now=now,
        )
        if item_id:
            reach[item_id] = raw

    # -- entity ambiguity (§4.1 condition 4) -------------------------------
    #
    # The person was at that place — or at that employer, or that school —
    # more than once, so the containment rung declined to place the telling.
    # What the substrate CAN answer is not "when did this happen" (they
    # clearly do not remember the year) but "which of the times you were there
    # was this?", with the stretches they already told us about named in the
    # sentence.
    for node_id in sorted(ambiguity):
        row = ambiguity[node_id]
        group = groups.get(node_id)
        if group is None or collapsed_text(group["event_kind"]) in UNASKABLE_EVENT_KINDS:
            continue
        raw = len(row.get("episode_node_ids") or ())
        item_id = _mint_work_item(
            items,
            components,
            kind=collapsed_text(row.get("kind")) or "place_ambiguous",
            event_ref=node_id,
            node_ref=node_id,
            event_kind=group["event_kind"],
            subject_ref=group["subject"],
            requested_field="date",
            subject_resolved=group["resolved"],
            prompt_intent=compose_place_ambiguity_question(
                row.get("places") or (), row.get("spans") or (),
                preposition=collapsed_text(row.get("preposition")) or "in",
            ),
            claim_refs=_evidence_claim_refs(group),
            evidence_refs=_evidence_refs(group),
            system_value=min(1.0, raw / REACH_SATURATION),
            by_node=by_node,
            diagnostics=diagnostics,
            now=now,
        )
        if item_id:
            reach[item_id] = raw

    # -- two homes at once (§3.2, owner decision 2) ------------------------
    #
    # Both stays are filed and both are drawn; what is asked is which of the
    # two dates needs fixing. The item is keyed on the EARLIER stay, so a
    # person who overlapped three homes is asked once per stay that outlives
    # its move rather than once per pair — and the moment the overlap is gone
    # (a date corrected, a stay retracted) the next generation simply does not
    # mint it, which is how every derived item closes.
    for node_id in sorted(residence_overlaps):
        row = residence_overlaps[node_id]
        group = groups.get(node_id)
        if group is None:
            continue
        item_id = _mint_work_item(
            items,
            components,
            kind="residence_overlap",
            event_ref=node_id,
            node_ref=node_id,
            event_kind=group["event_kind"],
            subject_ref=group["subject"],
            requested_field="date",
            subject_resolved=group["resolved"],
            prompt_intent=compose_residence_overlap_question(
                row.get("label") or "", row.get("span") or "",
                row.get("overlapping") or (),
            ),
            # The claims that disagree are the two stays' own dated claims —
            # the same shape §4.2's empty-intersection row uses, and for the
            # same reason: neither stay is wrong on its own, the two of them
            # are wrong together.
            claim_refs=[
                *_dated_claim_refs(group),
                *[
                    ref
                    for other in row.get("overlapping_node_ids") or ()
                    for ref in _dated_claim_refs(groups.get(other) or {"claims": []})
                ],
            ],
            evidence_refs=_evidence_refs(group),
            system_value=1.0,
            by_node=by_node,
            diagnostics=diagnostics,
            now=now,
        )
        if item_id:
            reach[item_id] = len(row.get("overlapping_node_ids") or ())

    # -- contradictions ---------------------------------------------------
    for node_id in sorted(groups):
        group = groups[node_id]
        conflict = float(calculated[node_id].get("conflict") or 0.0)
        if conflict < MATERIAL_CONFLICT:
            continue
        if collapsed_text(group["event_kind"]) in UNASKABLE_EVENT_KINDS:
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
            prompt_intent=sentence(
                "contradiction", node_id, group,
                readings=_rival_readings(calculated[node_id]),
            ),
            claim_refs=refs,
            evidence_refs=_evidence_refs(group),
            system_value=conflict,
            by_node=by_node,
            diagnostics=diagnostics,
            now=now,
        )
        if item_id:
            reach[item_id] = len(refs)

    # -- containments that cannot both hold (E-L2a §4.2) -------------------
    #
    # Two person-dated containers whose spans do not overlap, with one telling
    # inside both. `MATERIAL_CONFLICT` is untouched: this is material BY
    # CONSTRUCTION — the person's own two stated spans are disjoint and one
    # story cannot have been in both — so it never passes through the
    # reconcile score at all. The row cites both containments so the answer
    # can be "fix a date" or "remove one containment" rather than a bare
    # "when was this?".
    for node_id in sorted(containment_conflicts):
        group = groups.get(node_id)
        if group is None or collapsed_text(group["event_kind"]) in UNASKABLE_EVENT_KINDS:
            continue
        rows = containment_conflicts[node_id]
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
            prompt_intent=sentence(
                "contradiction", node_id, group,
                readings=_english_list(
                    [f"{row['label']} ({row['span']})" for row in rows],
                    joiner="and",
                ),
            ),
            # The claims that disagree are the two CONTAINERS' own dated
            # claims, not the member's — the member said nothing about when.
            # `contradiction_needs_two_claims` is satisfied by the person's
            # own two spans, which is exactly what the row is about.
            claim_refs=[
                *_evidence_claim_refs(group),
                *[
                    ref
                    for row in rows
                    for ref in _dated_claim_refs(
                        groups.get(row["episode_node_id"]) or {"claims": []}
                    )
                ],
            ],
            evidence_refs=_evidence_refs(group),
            system_value=1.0,
            by_node=by_node,
            diagnostics=diagnostics,
            now=now,
        )
        if item_id:
            reach[item_id] = len(rows)

    # -- a birth origin its own evidence contradicts (E-BO) ---------------
    for row in diagnostics:
        if row.get("finding") == bo.CONTRADICTION_FINDING:
            _mint_work_item(items, components, now=now, by_node=by_node,
                            diagnostics=diagnostics, **bo.contradiction_work_item(row))

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
                    + ", ".join(owner_rewrite(whats.get(n) or displays.get(n, n))
                                for n in cycle)
                ),
                claim_refs=refs,
                system_value=1.0,
                diagnostics=diagnostics,
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
                "The order given for "
                f"{owner_rewrite(whats.get(node_id) or displays.get(node_id, group['subject']))}"
                " does not fit the date claimed for it."
            ),
            claim_refs=refs,
            evidence_refs=_evidence_refs(group),
            system_value=1.0,
            by_node=by_node,
            diagnostics=diagnostics,
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
    "COLOCATION_RETIRED",
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
    "WORK_ITEM_PRECEDENCE",
    "WORK_ITEM_VALUE_DEFAULTS",
    "CalculatedTimeline",
    "TemporalTimelineError",
    "active_claim_rows",
    "age_text_for_band",
    "compose_place_ambiguity_question",
    "derive_calculated_timeline",
    "structural_signature",
    "work_item_score",
    "work_item_surfaces",
]
