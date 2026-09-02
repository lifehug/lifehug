#!/usr/bin/env python3
"""The calculated side: nodes, work items, fingerprints (v220).

``temporal_claims`` holds the *evidence* — what a source said, who extracted
it, and when. This module holds what the deterministic fold *calculates from*
it: the timeline node the person sees, and the typed work item that asks for
the next missing thing. Both are derived artifacts. Neither is ever edited as
the source of truth: the calculated timeline is a **materialized view** that
can be deleted and rebuilt from the active claim substrate (plan §4.1, §7),
and a work item is a question the substrate currently implies.

This module is pure — no I/O, no model, no vault. The fold that produces these
records is wave D's; the shapes are frozen here (wave A) so the fold, the
Timeline page, Mirror, the whisper lane and the daily queue cannot each invent
their own.

Three properties are load-bearing:

**Stable identity, now.** :func:`derive_node_id` and
:func:`derive_work_item_id` are pure functions of semantic identity, not of
position in a list or of generation number. A node keeps its id across
rebuilds, so a correction can name it; a work item keeps its id across
surfaces, so answering it on Timeline closes the same item in the queue and
suppresses the same whisper (plan §2.3, §5.4, §10). One id, answered once,
updated everywhere.

**Fingerprints, now; a dirty-node scheduler, not yet.**
:func:`derive_input_fingerprint` records exactly which claims and constraints a
node was calculated from. That is what makes future incremental recomputation
*possible* without taking on invalidation bugs today (plan §1.2, §7, §7.1). A
persisted reverse-dependency graph is explicitly out of scope until the
measured wave-H gate is crossed.

**Disagreement is never erased.** A node carries ``alternate_values`` beside
``best_temporal_value`` and a ``conflict_state`` that must admit them: a node
holding alternates while claiming to be settled is refused by name
(``node_hides_alternatives``). Reconciliation happens in the pure fold —
``chronology.reconcile`` — and never as a mutating write authority (plan §6.5),
and the losing claim is never deleted merely because another currently ranks
higher.

``landmarks.json`` becomes a projection over these nodes in wave B (owner
amendment Q1, 2026-08-26). It is named here because that is what "the schemas
it will be projected FROM" means concretely: a landmark is a
:class:`CalculatedTimelineNode` with its ``input_claim_refs`` pointing back at
the claims that placed it, and the file stops being a place anything is
written by hand.

Schema version and compatibility: :data:`temporal_claims.SCHEMA_VERSION` covers
this module too, under the same additive-only rule stated in that module's
docstring. :data:`NODE_IDENTITY_KEYS` and :data:`WORK_ITEM_IDENTITY_KEYS` are
frozen per schema version and pinned by golden tests, so adding a field can
never move an existing id.

Controlling contract: the audited final timeline build plan, §5.3, §5.4, §6.5,
§7 and §8.5.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

SYSTEM_DIR = Path(__file__).resolve().parent
if str(SYSTEM_DIR) not in sys.path:
    sys.path.insert(0, str(SYSTEM_DIR))

import chronology as chrono  # noqa: E402
from temporal_claims import (  # noqa: E402
    CLAIM_BASES,
    SCHEMA_VERSION,
    TEMPORAL_STATE_DIR,
    TemporalContractError,
    collapsed_text,
    digest_id,
    normalized_mention_key,
    normalized_timestamp,
    optional_text,
    unit_score,
)

# --------------------------------------------------------------------------
# The closed vocabularies
# --------------------------------------------------------------------------

#: What a calculated node *is*. An ``episode`` is a recurring relationship or a
#: repeated period — plan §6.3 forbids collapsing every event involving the
#: same people into one timeless relationship, and forbids collapsing a
#: repeated school or job into one incompatible span.
NODE_KINDS = ("event", "period", "episode")

#: The event kinds a ``period`` node holds. ``age_frame`` is E1's calculated
#: coordinate system; ``named_era`` is E3's person-made era. One tuple, read by
#: the fold's ``_node_kind_for`` and by this module, so "is this a period?"
#: cannot be answered two ways (eras design §2.1-2.2).
PERIOD_EVENT_KINDS = ("age_frame", "named_era")

#: The event kind of an age frame, spelled once.
AGE_FRAME_EVENT_KIND = "age_frame"

#: The event kind of a person-made era (E3), spelled once for the same reason.
NAMED_ERA_EVENT_KIND = "named_era"

#: Where a node sits against the life clip (eras design §2.6). ``lived`` and
#: ``future_plan`` are E1's; E2 adds the two that need the occurrence-subject
#: machinery — ``contradictory`` for an OWNER-subject occurrence wholly before
#: the supported birth interval (Mirror owns the row, and the claim is never
#: censored), and ``unresolved`` for a subject nobody has identified, which is
#: emphatically not the same thing as the owner (§2.6: *never `self` by
#: default*).
LIFE_VIEWS = ("lived", "future_plan", "contradictory", "unresolved")

#: WHOSE occurrence a node is (eras design §2.5). It names the person the event
#: happened to, and it is **never rewritten to the owner**: a moment about
#: somebody else stays about somebody else no matter how it got onto a page.
OCCURRENCE_SUBJECT_SCOPES = ("owner", "other_person", "unresolved")

#: WHY a node is on the OWNER's axis (eras design §2.5), which is a different
#: question from whose occurrence it is and is answered by different evidence.
#:
#: ``participated`` — the owner was in it (their own life, a partnership
#: landmark's first-met/married). ``lived_effect`` — it happened to somebody
#: else and the owner lived through it (a child's birth, a loss). Both put the
#: row on the axis. ``contextual_only`` — a stated relationship exists and this
#: particular occurrence is not owner-relevant (a relative's unrelated event,
#: pre-birth family history); the row renders under "Not placed yet · about
#: someone else" and gets no membership. ``none`` — no relationship is stated
#: at all. ``unresolved`` — identity has not landed yet.
OWNER_TIMELINE_RELATIONS = (
    "participated",
    "lived_effect",
    "contextual_only",
    "none",
    "unresolved",
)

#: The relations that put a row ON the owner's axis, spelled once so the fold
#: and the legacy pass cannot answer "is this on the timeline?" two ways.
AXIS_RELATIONS = ("participated", "lived_effect")

#: The evidence ref a FRAME membership cites. A frame membership is arithmetic
#: over the member's own dates and the birth origin — there is no receipt to
#: point at — so it cites the rule by name rather than leaving ``evidence_refs``
#: empty, which the schema refuses. A NAMED ERA never uses this: date overlap
#: alone is not a membership (design §2.4).
FRAME_MEMBERSHIP_RULE = "rule:age-frame-arithmetic:1"

#: Where a node sits on the calendar (eras design §2.2). ``unplaced`` has no
#: supported value; ``partial`` has one that is materially wider than the event
#: deserves; ``placed`` is at or finer than its precision target;
#: ``contradictory`` means the supporting evidence cannot all be true and the
#: node's readings are in ``alternate_values``. E-BO assigns exactly two of
#: them — a provisional birth origin is ``partial``, or ``contradictory`` when
#: the age evidence is disjoint; E2 assigns the rest. Absent means a phase that
#: does not yet answer the question has not guessed at it.
TEMPORAL_STATES = ("unplaced", "partial", "placed", "contradictory")

#: How an age frame's origin was arrived at: the person's stated birthday, or
#: the interval calculated from age statements (E-BO). It is a CLAIM basis, and
#: ``temporal_claims.CLAIM_BASIS_BY_DATE_BASIS`` is the one mapping onto it.
ORIGIN_BASES = ("explicit", "calculated")

#: How a member sits inside an era or a frame (eras design §2.2).
MEMBERSHIP_RELATIONS = ("within", "overlaps", "starts_in", "associated_with")

#: Which container a member RENDERS in. Display only — never chronology.
MEMBERSHIP_DISPLAY_ROLES = ("primary", "secondary", "none")

#: What the node's inputs currently say about each other. ``alternatives``
#: means materially supported readings coexist; ``contradicted`` means two
#: claims cannot both be true and Mirror owns a row for it (plan §2.5, §8.2).
CONFLICT_STATES = ("none", "alternatives", "contradicted")

#: Typed work, one identity across every surface (plan §5.4, §14 row 6). A
#: contradiction is not forced into an API named only for "gaps".
#:
#: v2, additive (event identity I1, §3.5). The keys one identity LINK row
#: carries — a containment, a `related` edge or a proposal. Frozen here so the
#: fold, the platform's card and a test read one spelling; the row is a view of
#: a durable `event_identity` record, never a record itself.
IDENTITY_LINK_KEYS = (
    "telling_ref",
    "episode_id",
    "episode_node_id",
    "relation",
    "origin",
)

#: ``tenure_ambiguous`` is E-L2a's sibling of ``place_ambiguous`` for the two
#: domains whose entity is an ORGANIZATION rather than a place (§7.2). One
#: kind could not carry both: *"which time in Cedarport was this"* and *"which
#: time at Tidewheel Works was this"* are different sentences about different
#: nouns, and a host that wants to route or count them apart — Mirror does —
#: cannot do it from a `reason` string.
#:
#: ``place_ambiguous`` arrives with Timeline Fix 05 §8.3 (``timeline-rules:4``):
#: a moment names a place the person was in MORE THAN ONCE, so the co-location
#: rule declines to infer and asks WHICH TIME instead. It is its own kind and
#: not a ``missing_anchor`` because the answer is a choice between spans the
#: substrate already holds, not a date typed from nothing — and because the
#: question a person can actually answer is *"which time in San Diego?"*.
#:
#: ``same_event`` and ``possible_overmerge`` arrive with event identity I3
#: (`docs/design/event-identity.md` v4 §6.1/§6.3). I2's binder module
#: emitted both as pairwise OUTPUTS — the pair key, every §4.2 condition's
#: pass/fail, and the inputs this module's own value scoring reads — but
#: deliberately left both kinds unregistered here: a kind whose answer
#: nothing can file is the silent under-delivery ADR 0021 refuses. I3 is the
#: probe, the five answers and the filing (`resolve-work-item`), so the
#: registration lands here, now that something can act on it.
#: ``residence_overlap`` arrives with E-L2b (§7.2, owner decision 2): two
#: stays that claim the same weeks beyond a move. It is its own kind and not a
#: ``contradiction`` because the disagreement is not between two readings of
#: ONE fact — both stays are true as far as the substrate knows — and because
#: its answer is a correction to one of two dates or a retraction of a stay,
#: which is a different Play from "which of these readings is right".
#: ``chain_gap`` arrives with E-L2c (§7.2/§8), generalizing the ladder's own
#: `residence_gap` to three chains (residences, work, schools) and to
#: before/after gaps, not only interior ones. It is routine incompleteness
#: like ``place_ambiguous``/``tenure_ambiguous`` — never a disagreement — so
#: it never reaches Mirror; unlike them it is produced OUTSIDE the fold, by
#: `landmarks_interaction.chain_gaps` reading landmark entries directly
#: (the same shape `residence_gap` already has), so this registration is
#: what lets a `chain_gap` row become a Play target through the ordinary
#: work-item machinery rather than a second one.
WORK_ITEM_KINDS = (
    "missing_anchor", "precision_gap", "contradiction", "identity_uncertain",
    "place_ambiguous", "tenure_ambiguous", "residence_overlap", "chain_gap",
    "same_event", "possible_overmerge",
)

#: ``offered`` is "shown to the person and not yet answered"; ``obsolete`` is
#: "the substrate no longer implies this question" — which is how answering
#: elsewhere closes an item without anybody having to answer it twice.
WORK_ITEM_STATES = ("open", "offered", "answered", "resolved", "dismissed", "obsolete")

#: Where an item is allowed to appear. ``allowed_surfaces`` is the mechanism
#: behind plan §2.4's loss rule — a generic loss-discovery item simply does not
#: list ``daily_question`` — and behind §2.3's no-self-competition rule, since
#: the same ``work_item_id`` on two surfaces is detectable by construction.
WORK_ITEM_SURFACES = ("timeline", "mirror", "whisper", "daily_question")

#: The normalized score components (plan §5.4, §8.5). Each is ``0.0..1.0``;
#: ``combined_score`` is wave F's to compute, and this module only refuses an
#: out-of-range number.
WORK_ITEM_SCORE_FIELDS = (
    "person_value",
    "system_value",
    "interaction_cost",
    "sensitivity",
    "context_fit",
    "combined_score",
)

#: The whole materialized projection (plan §7). One file, published atomically:
#: readers see the prior complete generation or the next complete generation,
#: never a partial mix. The publisher is wave D's; this module names the path
#: so three hosts cannot pick three.
PROJECTION_FILE = f"{TEMPORAL_STATE_DIR}/calculated-timeline.json"
WORK_ITEMS_FILE = f"{TEMPORAL_STATE_DIR}/work-items.json"

NODE_ID_PREFIX = "node"
WORK_ITEM_ID_PREFIX = "work"
FINGERPRINT_PREFIX = "fp"
MEMBERSHIP_ID_PREFIX = "membership"
CHAPTER_OVERLAY_ID_PREFIX = "overlay"

#: An age frame's id is READABLE on purpose: it is the ``?play=frame:`` key,
#: the zoom key and the alias target `timeline.legacy_period_ref` resolves
#: legacy slugs onto (eras design §3.5, §5.4). A digest would be stable too and
#: unreadable in every one of those places.
AGE_FRAME_ID_PREFIX = "age"

#: The CALCULATED PROJECTION's own schema version (eras design §7.8).
#:
#: It is deliberately NOT :data:`temporal_claims.SCHEMA_VERSION`, which stamps
#: every claim, constraint, receipt and the active index: v2 adds optional
#: fields to a NODE, and moving the receipt store's version for a node-shape
#: change would be the opposite of additive. Readers are tolerant of both — a
#: v1 node simply lacks the v2 keys — and the writer is the platform's flag to
#: turn off (§7.8 step 3).
#:
#: **This is the WRITER's default and E-L2d does not move it.** Schema v3 is
#: declared (:data:`PROJECTION_SCHEMA_VERSION_LATEST`) and written only when
#: the flag says so (:func:`projection_schema_version`) — the same §7.8
#: rollout discipline the eras program used for v2: tolerant readers first,
#: writer behind a flag, rollback = flag off.
PROJECTION_SCHEMA_VERSION = 2

#: The newest node/projection shape this package knows how to WRITE.
PROJECTION_SCHEMA_VERSION_LATEST = 3

#: Every projection schema a reader in this package tolerates. v1 is "no v2
#: keys", v2 is today's writer, v3 is E-L2d's additive shape.
PROJECTION_SCHEMA_VERSIONS = (1, 2, 3)

#: The flag. An environment variable rather than an argument because the
#: choice is a DEPLOYMENT's, not a caller's: every writer in a process must
#: agree, or one job publishes v3 nodes and the next republishes them as v2.
#: Unset — or set to anything that is not a version this package writes —
#: means :data:`PROJECTION_SCHEMA_VERSION`, so a typo rolls BACK rather than
#: crashing a deploy, which is the direction §7.8 step 3 wants a mistake to
#: fall.
PROJECTION_SCHEMA_FLAG = "LIFEHUG_PROJECTION_SCHEMA_VERSION"

#: The versions the flag may select. v1 is a READ shape (a projection written
#: before the eras program), never a writer target: nothing in this package
#: can un-write `definition_span`.
PROJECTION_SCHEMA_WRITABLE = (2, 3)


def projection_schema_version() -> int:
    """The schema this process WRITES — :data:`PROJECTION_SCHEMA_VERSION`
    unless :data:`PROJECTION_SCHEMA_FLAG` selects another writable one.

    Read at call time rather than at import, so a test (and an operator) can
    flip the flag without reloading the package, and so the whole of v3 is one
    switch rather than a constant somebody has to remember to move in four
    modules.
    """
    raw = os.environ.get(PROJECTION_SCHEMA_FLAG)
    try:
        chosen = int(str(raw).strip())
    except (TypeError, ValueError):
        return PROJECTION_SCHEMA_VERSION
    if chosen not in PROJECTION_SCHEMA_WRITABLE:
        return PROJECTION_SCHEMA_VERSION
    return chosen


#: What a published node's ``value_shape`` may say (design §3.4, H3).
#:
#: The distinction already existed structurally — `definition_span` (a period's
#: duration), `best_temporal_value` (an occurrence), `possible_temporal_value`
#: (an era `within` a frame, or a containment's outer range) — in four fields
#: with four "never a bound" comments and NO single tag, so a renderer could
#: read a window as a bar and did. This is that one tag.
VALUE_SHAPES = ("duration", "point", "window", "none")

#: The three lanes a row group draws (design §9.2), keyed by the participation
#: episode's own event kind. ``military`` draws in ``worked``: a stint of
#: service is time served somewhere, and giving it a fourth lane of its own
#: would put one bar in a lane most lives never open.
#:
#: The KEYS are the one definition of "which event kinds are participation
#: episodes", and `tests/test_projection_schema_v3.py` pins them against
#: `landmark_projection.PARTICIPATION_EPISODE_KINDS`' own values, so a fifth
#: span domain fails the build here instead of drawing in no lane.
LANES_BY_EVENT_KIND = {
    "residence": "lived",
    "job": "worked",
    "school": "schooled",
    "military": "worked",
}

#: The lanes themselves, in the order §9.2 names them.
LANES = ("lived", "worked", "schooled")

#: The event kinds :data:`LANES_BY_EVENT_KIND` covers — a participation
#: episode's own interval is a ``duration`` (design §3.4).
PARTICIPATION_EVENT_KINDS = tuple(sorted(LANES_BY_EVENT_KIND))

#: What one lane row says (schema v3, design §9.6).
LANE_ROW_KEYS = ("group_id", "lane", "episode_node_ids")


#: FROZEN for schema version 1.
NODE_IDENTITY_KEYS = ("node_kind", "event_kind", "subject_keys", "discriminator")
#: FROZEN for schema version 1. Subject/event identity plus the missing field
#: is what makes "the same gap" the same gap wherever it is asked.
WORK_ITEM_IDENTITY_KEYS = ("kind", "subject_key", "event_key", "requested_field")


class TimelineNodeError(TemporalContractError):
    """A calculated node is not explainable from its inputs."""


class TemporalWorkItemError(TemporalContractError):
    """A work item cannot be answered once and closed everywhere."""


#: Every finding id this module can raise (plan §12 counts rejections by
#: reason). ``temporal_claims.ERROR_CODES`` holds the evidence side's.
ERROR_CODES = (
    "node_not_a_mapping",
    "node_needs_id",
    "unknown_node_kind",
    "unknown_conflict_state",
    "unknown_claim_basis",
    "node_without_inputs",
    "node_hides_alternatives",
    "node_value_unusable",
    "node_needs_rule_version",
    "unknown_origin_basis",
    "unknown_temporal_state",
    "unknown_life_view",
    "unknown_occurrence_subject_scope",
    "unknown_owner_timeline_relation",
    # Schema v3 (E-L2d): a lane row that names no row group, or a lane
    # outside the three §9.2 declares.
    "lane_needs_group",
    "unknown_lane",
    "membership_not_a_mapping",
    "membership_needs_member",
    "membership_needs_era",
    "unknown_membership_relation",
    "unknown_membership_display_role",
    "membership_without_evidence",
    "overlay_not_a_mapping",
    "overlay_needs_chapter",
    "overlay_without_frames",
    "work_item_not_a_mapping",
    "unknown_work_item_kind",
    "unknown_work_item_state",
    "unknown_work_item_surface",
    "work_item_needs_surface",
    "work_item_needs_subject_or_event",
    "work_item_needs_requested_field",
    "contradiction_needs_two_claims",
    "score_out_of_range",
    "timestamp_unusable",
    "episode_block_on_non_episode_node",
    "telling_count_disagrees",
    "identity_link_malformed",
)


# --------------------------------------------------------------------------
# Deterministic identity
# --------------------------------------------------------------------------


def derive_node_id(
    *,
    node_kind: object,
    event_kind: object = None,
    subject_refs: object = (),
    discriminator: object = None,
) -> str:
    """``node:<24 hex>`` — a semantic identity that survives every rebuild.

    The id is what a correction, a Mirror row and a work item all point at, so
    it is deliberately independent of the projection generation, of the node's
    calculated date, and of its position in any list. ``discriminator``
    separates repeats that are genuinely different episodes — a second stint at
    the same employer, a second period at the same school — and is the caller's
    stable ordinal or slug, never a timestamp.
    """
    refs = subject_refs
    if isinstance(refs, (str, bytes)):
        refs = [refs]
    payload = {
        "node_kind": collapsed_text(node_kind),
        "event_kind": collapsed_text(event_kind) or None,
        "subject_keys": sorted(
            {normalized_mention_key(ref) for ref in (refs or ()) if collapsed_text(ref)}
        ),
        "discriminator": collapsed_text(discriminator) or None,
    }
    return digest_id(NODE_ID_PREFIX, {key: payload[key] for key in NODE_IDENTITY_KEYS})


def age_frame_node_id(band: object, *, subject: object = "self") -> str:
    """``age:<subject>:<band>`` — an age frame's identity (eras design §3.5).

    The one place the string is built. It is not a digest, and that is the
    decision: this id is the ``?play=frame:`` key, the per-vault zoom key and
    the target every legacy period slug aliases onto, and all three are read by
    humans. The identity is nonetheless exactly the tuple
    :func:`derive_node_id` would digest — ``(period, age_frame, subject, band)``
    — which :func:`age_frame_identity` states so a test can pin it.
    """
    return "{}:{}:{}".format(
        AGE_FRAME_ID_PREFIX,
        normalized_mention_key(subject) or "self",
        collapsed_text(band),
    )


def age_frame_identity(band: object, *, subject: object = "self") -> dict:
    """The identity tuple behind :func:`age_frame_node_id`, spelled out."""
    return {
        "node_kind": "period",
        "event_kind": AGE_FRAME_EVENT_KIND,
        "subject_keys": [normalized_mention_key(subject) or "self"],
        "discriminator": collapsed_text(band) or None,
    }


def derive_membership_id(*, member_node_id: object, era_node_id: object,
                         relation: object) -> str:
    """``membership:<24 hex>`` — one calculated membership, semantically.

    Two independent assertions that a moment sits inside College are ONE
    membership carrying two evidence refs (design §2.4, T-M-09), which is what
    keying the identity on the pair plus the relation buys.
    """
    return digest_id(MEMBERSHIP_ID_PREFIX, {
        "member_node_id": collapsed_text(member_node_id),
        "era_node_id": collapsed_text(era_node_id),
        "relation": collapsed_text(relation),
    })


def derive_chapter_overlay_id(*, chapter_node_id: object) -> str:
    """``overlay:<24 hex>`` — one chapter's overlay across the frames.

    Keyed on the CHAPTER alone, not on the frames it happens to cover: a
    chapter that grows to touch a fourth frame is the same overlay with a
    longer ``frame_node_ids``, and giving it a new identity every time its
    span moved would make "the same chapter" undetectable.
    """
    return digest_id(CHAPTER_OVERLAY_ID_PREFIX, {
        "chapter_node_id": collapsed_text(chapter_node_id),
    })


def derive_work_item_id(
    *,
    kind: object,
    subject_ref: object = None,
    event_ref: object = None,
    requested_field: object = None,
) -> str:
    """``work:<24 hex>`` — one identity for work, across every surface.

    Timeline, Mirror, the whisper lane and the daily queue all derive the id
    the same way, so the same gap minted twice is one row: answering it on one
    surface closes it on the others, and an item that is today's main question
    can be suppressed as a whisper in the same interaction (plan §2.3, §5.4,
    §8.5, §10). The score, the state and the timestamps are annotation and are
    deliberately absent from the digest — a re-scored item is the same item.
    """
    payload = {
        "kind": collapsed_text(kind),
        "subject_key": normalized_mention_key(subject_ref) or None,
        "event_key": collapsed_text(event_ref) or None,
        "requested_field": collapsed_text(requested_field) or None,
    }
    return digest_id(WORK_ITEM_ID_PREFIX, {key: payload[key] for key in WORK_ITEM_IDENTITY_KEYS})


def derive_input_fingerprint(
    *,
    claim_ids: object = (),
    constraint_ids: object = (),
    calculation_rule_version: object = "",
    epoch: object = None,
) -> str:
    """``fp:<24 hex>`` — exactly what this node was calculated from.

    Two rebuilds from identical receipts, corrections, rules and versions
    produce identical fingerprints; a changed input or a changed rule changes
    the fingerprint (plan §7). That is the correctness oracle's comparison key
    today, and the option on incremental recomputation tomorrow — the option
    the plan insists we keep without building the scheduler (§1.2, §7.1).
    """
    claims = claim_ids
    if isinstance(claims, (str, bytes)):
        claims = [claims]
    constraints = constraint_ids
    if isinstance(constraints, (str, bytes)):
        constraints = [constraints]
    payload = {
        "claim_ids": sorted({collapsed_text(c) for c in (claims or ()) if collapsed_text(c)}),
        "constraint_ids": sorted({collapsed_text(c) for c in (constraints or ()) if collapsed_text(c)}),
        "calculation_rule_version": collapsed_text(calculation_rule_version),
    }
    # An age frame is calculated from the birthday AND from which frames the
    # person has reached — crossing a boundary changes the answer on unchanged
    # claims (eras design §3.4, §7 row "Age frame node"). The key is added ONLY
    # when an epoch is supplied, so every fingerprint already on disk stays
    # byte-identical: `digest_id` is canonical JSON, and an always-present key
    # would move all of them.
    epoch_key = collapsed_text(epoch)
    if epoch_key:
        payload["epoch"] = epoch_key
    return digest_id(FINGERPRINT_PREFIX, payload)


# --------------------------------------------------------------------------
# CalculatedTimelineNode
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class CalculatedTimelineNode:
    """One placed thing in the calculated timeline (plan §5.3).

    ``best_temporal_value`` is what Timeline shows; ``alternate_values`` is what
    it must also signal when the support is materially divided. ``basis`` says
    whether the person stated it, we calculated it, or we judged it — the
    distinction §8.1 requires on the page. A node is *deletable*: the whole
    projection can be thrown away and rebuilt from the active claims.
    """

    node_id: str
    node_kind: str
    input_claim_refs: tuple[str, ...]
    input_fingerprint: str
    calculation_rule_version: str
    subject_refs: tuple[str, ...] = ()
    event_kind: str | None = None
    label: str | None = None
    best_temporal_value: dict | None = None
    alternate_values: tuple[dict, ...] = ()
    input_constraint_refs: tuple[str, ...] = ()
    provenance_summary: str | None = None
    basis: str = "inferred"
    confidence: float = 0.0
    model_version: str | None = None
    projection_generation: int = 0
    conflict_state: str = "none"
    #: v2, additive (eras design §2.2). A ``period`` node's own interval, with
    #: an EXCLUSIVE end; where the life clip stops (``present`` is a view token
    #: resolved at read time, never a stored date); how the origin was arrived
    #: at; the legacy slugs that alias onto this node; and where the node sits
    #: against the clip. Absent on every v1 node and on every node that is not
    #: a frame — absent means unchanged.
    definition_span: dict | None = None
    #: v2, additive (eras design §2.2/§4.2), E3. A ``named_era`` that nobody
    #: has dated but that somebody said sits INSIDE a frame — *"College was in
    #: my 20s"* — gets a possible value here and **nothing** in
    #: ``best_temporal_value``. The distinction is the whole of §4.2: a
    #: `within` is a containment, not a bound, and publishing the containing
    #: frame's interval as the era's own date is exactly how an era ends up
    #: dated by something other than what the person said. Absent means the
    #: era has no such relation.
    possible_temporal_value: dict | None = None
    life_clip_end: str | None = None
    origin_basis: str | None = None
    legacy_refs: tuple[str, ...] = ()
    life_view: str | None = None
    #: v2, additive (eras design §2.2, E-BO). Where the node sits on the
    #: calendar; see :data:`TEMPORAL_STATES`. Absent on every node written so
    #: far, and absent means unchanged.
    temporal_state: str | None = None
    #: v2, additive (eras design §2.5). Whose occurrence this is, why it is on
    #: the owner's axis, and the records that say so — a landmark entry's
    #: ``source_id`` and the identity claim that named the person. A relation of
    #: ``contextual_only`` with real evidence refs is an HONEST answer, not a
    #: missing one: it says a relationship is stated and this occurrence still
    #: is not the owner's.
    occurrence_subject_scope: str | None = None
    owner_timeline_relation: str | None = None
    relation_evidence_refs: tuple[str, ...] = ()
    #: v2, additive (eras design §2.2, §2.4). A named era's COVERAGE of its
    #: explicit members. It is never a bound: it does not enter
    #: ``best_temporal_value``, ``definition_span`` or
    #: ``possible_temporal_value``, because dating an era from what got sorted
    #: into it is the founder's own "College 1990-1991 before High School".
    observed_envelope: dict | None = None
    #: v2, additive (event identity I1, design §3.5). What the identity layer
    #: says about this node. The first four ride an EPISODE node only — a node
    #: an `event_identity` binding actually made — because publishing
    #: ``telling_count: 1`` on every node in a vault that has never bound
    #: anything would be a schema change dressed as a fact. ``containments``,
    #: ``related`` and ``proposed_links`` ride any node whose telling carries
    #: such a record. Absent means no record, which is where every node starts.
    #:
    #: ``proposed_links`` is the one that must never draw anything (§2.3): a
    #: proposal ranks the question queue and renders at most a soft "possibly
    #: the same as…" line, so it is published as a link and NEVER folded into
    #: grouping, the date, or the containment range.
    episode_id: str | None = None
    tellings: tuple[str, ...] = ()
    telling_count: int = 0
    identity_origins: tuple[str, ...] = ()
    containments: tuple[dict, ...] = ()
    related: tuple[dict, ...] = ()
    proposed_links: tuple[dict, ...] = ()
    #: v3, additive, DERIVED (design §3.4, H3). Which of the four fields above
    #: says when this node happened — see :func:`derive_value_shape`. It is
    #: never an input: the validator recomputes it from the node every time,
    #: so it cannot drift from the fields it describes. Absent on v1 and v2
    #: nodes, and absent means "derive it yourself", which every tolerant
    #: reader can do because the function is pure.
    value_shape: str | None = None
    schema_version: int = PROJECTION_SCHEMA_VERSION

    def to_dict(self) -> dict:
        payload: dict = {
            "node_id": self.node_id,
            "schema_version": self.schema_version,
            "node_kind": self.node_kind,
            "subject_refs": list(self.subject_refs),
            "best_temporal_value": self.best_temporal_value,
            "alternate_values": [dict(v) for v in self.alternate_values],
            "input_claim_refs": list(self.input_claim_refs),
            "input_constraint_refs": list(self.input_constraint_refs),
            "input_fingerprint": self.input_fingerprint,
            "basis": self.basis,
            "confidence": self.confidence,
            "calculation_rule_version": self.calculation_rule_version,
            "projection_generation": self.projection_generation,
            "conflict_state": self.conflict_state,
        }
        for key, value in (
            ("event_kind", self.event_kind),
            ("label", self.label),
            ("provenance_summary", self.provenance_summary),
            ("model_version", self.model_version),
            ("definition_span", self.definition_span),
            ("possible_temporal_value", self.possible_temporal_value),
            ("life_clip_end", self.life_clip_end),
            ("origin_basis", self.origin_basis),
            ("life_view", self.life_view),
            ("temporal_state", self.temporal_state),
            ("occurrence_subject_scope", self.occurrence_subject_scope),
            ("owner_timeline_relation", self.owner_timeline_relation),
            ("observed_envelope", self.observed_envelope),
        ):
            if value is not None:
                payload[key] = value
        if self.legacy_refs:
            payload["legacy_refs"] = list(self.legacy_refs)
        if self.relation_evidence_refs:
            payload["relation_evidence_refs"] = list(self.relation_evidence_refs)
        if self.episode_id:
            payload["episode_id"] = self.episode_id
            payload["tellings"] = list(self.tellings)
            payload["telling_count"] = int(self.telling_count)
            payload["identity_origins"] = list(self.identity_origins)
        for key, rows in (("containments", self.containments),
                          ("related", self.related),
                          ("proposed_links", self.proposed_links)):
            if rows:
                payload[key] = [dict(row) for row in rows]
        if self.value_shape:
            payload["value_shape"] = self.value_shape
        return payload


def _normalized_node_value(value: object) -> dict | None:
    """One date, through ``chronology`` — there is no second date definition."""
    if value is None:
        return None
    record = chrono.from_dict(value)
    if record is None and isinstance(value, str):
        record = chrono.parse_edtf(value)
    if record is None:
        raise TimelineNodeError(
            "node_value_unusable", f"not a chronology date record: {value!r}"
        )
    return chrono.normalized_date(record) or record.to_dict()


def validate_calculated_timeline_node(value: object) -> dict:
    """Normalize a calculated node or raise :class:`TimelineNodeError`.

    Two refusals carry the plan's weight:

    * ``node_without_inputs`` — a node with no ``input_claim_refs`` is not a
      calculation, it is a fabrication. Every displayed change must be
      traceable to durable evidence (plan §8, exit gate E).
    * ``node_hides_alternatives`` — a node carrying ``alternate_values`` while
      declaring ``conflict_state: none`` is the silent resolution §2.5 forbids.
      Timeline must signal material uncertainty, not smooth it away.
    """
    if isinstance(value, CalculatedTimelineNode):
        value = value.to_dict()
    if not isinstance(value, dict):
        raise TimelineNodeError("node_not_a_mapping", "a node must be a mapping")

    node_id = collapsed_text(value.get("node_id"))
    if not node_id:
        raise TimelineNodeError("node_needs_id", "a node needs a stable semantic id")
    node_kind = collapsed_text(value.get("node_kind"))
    if node_kind not in NODE_KINDS:
        raise TimelineNodeError("unknown_node_kind", f"unknown node_kind: {node_kind!r}")

    basis = collapsed_text(value.get("basis")) or "inferred"
    if basis not in CLAIM_BASES:
        raise TimelineNodeError("unknown_claim_basis", f"unknown basis: {basis!r}")

    conflict_state = collapsed_text(value.get("conflict_state")) or "none"
    if conflict_state not in CONFLICT_STATES:
        raise TimelineNodeError(
            "unknown_conflict_state", f"unknown conflict_state: {conflict_state!r}"
        )

    claim_refs = _ref_tuple(value.get("input_claim_refs"))
    if not claim_refs:
        raise TimelineNodeError(
            "node_without_inputs", f"{node_id} cites no claims; a node is calculated, not asserted"
        )
    constraint_refs = _ref_tuple(value.get("input_constraint_refs"))

    best = _normalized_node_value(value.get("best_temporal_value"))
    raw_alternates = value.get("alternate_values")
    if isinstance(raw_alternates, (str, dict)):
        raw_alternates = [raw_alternates]
    alternates = [
        alternate
        for alternate in (_normalized_node_value(v) for v in (raw_alternates or ()))
        if alternate is not None
    ]
    if alternates and conflict_state == "none":
        raise TimelineNodeError(
            "node_hides_alternatives",
            f"{node_id} carries {len(alternates)} alternates but declares no conflict",
        )

    rule_version = collapsed_text(value.get("calculation_rule_version"))
    if not rule_version:
        raise TimelineNodeError(
            "node_needs_rule_version",
            "a calculated node names the rule version that calculated it",
        )

    fingerprint = collapsed_text(value.get("input_fingerprint")) or derive_input_fingerprint(
        claim_ids=claim_refs,
        constraint_ids=constraint_refs,
        calculation_rule_version=rule_version,
    )

    generation = value.get("projection_generation")
    try:
        generation = int(generation or 0)
    except (TypeError, ValueError):
        generation = 0

    origin_basis = collapsed_text(value.get("origin_basis"))
    if origin_basis and origin_basis not in ORIGIN_BASES:
        raise TimelineNodeError("unknown_origin_basis", f"unknown origin_basis: {origin_basis!r}")
    life_view = collapsed_text(value.get("life_view"))
    if life_view and life_view not in LIFE_VIEWS:
        raise TimelineNodeError("unknown_life_view", f"unknown life_view: {life_view!r}")
    temporal_state = collapsed_text(value.get("temporal_state"))
    if temporal_state and temporal_state not in TEMPORAL_STATES:
        raise TimelineNodeError(
            "unknown_temporal_state", f"unknown temporal_state: {temporal_state!r}"
        )
    scope = collapsed_text(value.get("occurrence_subject_scope"))
    if scope and scope not in OCCURRENCE_SUBJECT_SCOPES:
        raise TimelineNodeError(
            "unknown_occurrence_subject_scope",
            f"unknown occurrence_subject_scope: {scope!r}",
        )
    relation = collapsed_text(value.get("owner_timeline_relation"))
    if relation and relation not in OWNER_TIMELINE_RELATIONS:
        raise TimelineNodeError(
            "unknown_owner_timeline_relation",
            f"unknown owner_timeline_relation: {relation!r}",
        )
    envelope = _normalized_node_value(value.get("observed_envelope"))
    span = value.get("definition_span")
    definition_span = None
    if isinstance(span, dict):
        definition_span = {
            "start": _normalized_node_value(span.get("start")),
            "end": _normalized_node_value(span.get("end")),
        }

    schema_version = projection_schema_version()
    normalized: dict = {
        "node_id": node_id,
        "schema_version": schema_version,
        "node_kind": node_kind,
        "subject_refs": list(_ref_tuple(value.get("subject_refs"))),
        "best_temporal_value": best,
        "alternate_values": alternates,
        "input_claim_refs": list(claim_refs),
        "input_constraint_refs": list(constraint_refs),
        "input_fingerprint": fingerprint,
        "basis": basis,
        "confidence": unit_score(value.get("confidence"), error=TimelineNodeError),
        "calculation_rule_version": rule_version,
        "projection_generation": max(0, generation),
        "conflict_state": conflict_state,
    }
    for key in ("event_kind", "label", "provenance_summary", "model_version",
                "life_clip_end"):
        cleaned = optional_text(value.get(key))
        if cleaned:
            normalized[key] = cleaned
    if definition_span is not None:
        normalized["definition_span"] = definition_span
    possible = _normalized_node_value(value.get("possible_temporal_value"))
    if possible is not None:
        normalized["possible_temporal_value"] = possible
    if origin_basis:
        normalized["origin_basis"] = origin_basis
    if life_view:
        normalized["life_view"] = life_view
    if temporal_state:
        normalized["temporal_state"] = temporal_state
    if scope:
        normalized["occurrence_subject_scope"] = scope
    if relation:
        normalized["owner_timeline_relation"] = relation
    if envelope is not None:
        normalized["observed_envelope"] = envelope
    episode_id = collapsed_text(value.get("episode_id"))
    if episode_id:
        # An episode block on a node the identity layer did not make would be
        # a claim about grouping that grouping never made. `node_kind` is
        # INSIDE the id digest (`NODE_IDENTITY_KEYS`), so the two cannot
        # disagree without one of them being a fabrication.
        if node_kind != "episode":
            raise TimelineNodeError(
                "episode_block_on_non_episode_node",
                f"{node_id} carries an episode_id but its node_kind is {node_kind!r}",
            )
        tellings = _ref_tuple(value.get("tellings"))
        declared = value.get("telling_count")
        try:
            declared = int(declared)
        except (TypeError, ValueError):
            declared = len(tellings)
        if declared != len(tellings):
            raise TimelineNodeError(
                "telling_count_disagrees",
                f"{node_id} lists {len(tellings)} tellings and declares {declared}",
            )
        normalized["episode_id"] = episode_id
        normalized["tellings"] = list(tellings)
        normalized["telling_count"] = len(tellings)
        normalized["identity_origins"] = list(_ref_tuple(value.get("identity_origins")))
    for key in ("containments", "related", "proposed_links"):
        rows = _identity_links(node_id, key, value.get(key))
        if rows:
            normalized[key] = rows
    legacy_refs = _ref_tuple(value.get("legacy_refs"))
    if legacy_refs:
        normalized["legacy_refs"] = list(legacy_refs)
    relation_refs = _ref_tuple(value.get("relation_evidence_refs"))
    if relation_refs:
        normalized["relation_evidence_refs"] = list(relation_refs)
    # THE ONE DERIVATION (design §3.4). Recomputed from the normalized node,
    # never copied from the input, and written only by the v3 writer — a v2
    # publication stays byte-identical (§7.8 step 3's rollback).
    if schema_version >= 3:
        normalized["value_shape"] = derive_value_shape(normalized)
    return normalized


def _identity_links(node_id: str, field_name: str, value: object) -> list:
    """One identity link list, normalized to :data:`IDENTITY_LINK_KEYS`.

    Sorted here rather than trusted from the caller, so two hosts assembling
    the same records in two orders publish the same bytes.
    """
    rows = [value] if isinstance(value, dict) else list(value or ())
    found = []
    for row in rows:
        if not isinstance(row, dict):
            raise TimelineNodeError(
                "identity_link_malformed",
                f"{node_id}.{field_name} holds {row!r}, which is not a link row",
            )
        cleaned = {key: collapsed_text(row.get(key)) for key in IDENTITY_LINK_KEYS}
        if not cleaned["episode_id"]:
            raise TimelineNodeError(
                "identity_link_malformed",
                f"{node_id}.{field_name} holds a link that names no episode",
            )
        found.append(cleaned)
    found.sort(key=lambda row: tuple(row[key] for key in IDENTITY_LINK_KEYS))
    return found


def _ref_tuple(value: object) -> tuple[str, ...]:
    if isinstance(value, (str, bytes)):
        value = [value]
    return tuple(dict.fromkeys(collapsed_text(v) for v in (value or ()) if collapsed_text(v)))


def node_from_dict(value: object) -> CalculatedTimelineNode | None:
    """Tolerant reader — ``None`` rather than an exception."""
    try:
        normalized = validate_calculated_timeline_node(value)
    except TemporalContractError:
        return None
    return CalculatedTimelineNode(
        node_id=normalized["node_id"],
        node_kind=normalized["node_kind"],
        input_claim_refs=tuple(normalized["input_claim_refs"]),
        input_fingerprint=normalized["input_fingerprint"],
        calculation_rule_version=normalized["calculation_rule_version"],
        subject_refs=tuple(normalized["subject_refs"]),
        event_kind=normalized.get("event_kind"),
        label=normalized.get("label"),
        best_temporal_value=normalized["best_temporal_value"],
        alternate_values=tuple(normalized["alternate_values"]),
        input_constraint_refs=tuple(normalized["input_constraint_refs"]),
        provenance_summary=normalized.get("provenance_summary"),
        basis=normalized["basis"],
        confidence=normalized["confidence"],
        model_version=normalized.get("model_version"),
        projection_generation=normalized["projection_generation"],
        conflict_state=normalized["conflict_state"],
        definition_span=normalized.get("definition_span"),
        possible_temporal_value=normalized.get("possible_temporal_value"),
        life_clip_end=normalized.get("life_clip_end"),
        origin_basis=normalized.get("origin_basis"),
        legacy_refs=tuple(normalized.get("legacy_refs") or ()),
        life_view=normalized.get("life_view"),
        temporal_state=normalized.get("temporal_state"),
        occurrence_subject_scope=normalized.get("occurrence_subject_scope"),
        owner_timeline_relation=normalized.get("owner_timeline_relation"),
        relation_evidence_refs=tuple(normalized.get("relation_evidence_refs") or ()),
        observed_envelope=normalized.get("observed_envelope"),
        episode_id=normalized.get("episode_id"),
        tellings=tuple(normalized.get("tellings") or ()),
        telling_count=int(normalized.get("telling_count") or 0),
        identity_origins=tuple(normalized.get("identity_origins") or ()),
        containments=tuple(dict(row) for row in normalized.get("containments") or ()),
        related=tuple(dict(row) for row in normalized.get("related") or ()),
        proposed_links=tuple(dict(row) for row in normalized.get("proposed_links") or ()),
        value_shape=normalized.get("value_shape"),
        schema_version=int(normalized.get("schema_version") or PROJECTION_SCHEMA_VERSION),
    )


def derive_value_shape(node: object) -> str:
    """Design §3.4's ONE tag, derived from the node and nothing else.

    Never an input. A caller that hands in a ``value_shape`` has it
    overwritten, because the whole point of H3's fix is that the shape is a
    FUNCTION of the three fields that already exist rather than a fifth field
    somebody can set inconsistently with them.

    The order of the branches is the contract, and the third one is the one
    the audit caught (§12 row 8): a POINT event that gained a containment
    window carries a window record whose interval is the containing episode's
    — years wide — and reading its width would draw it as a bar across a
    decade of somebody's life. A possible value is a window whatever its
    width, always.

    * ``duration`` — the node's OWN interval: a frame's ``definition_span``,
      or a participation episode's ``started``/``ended`` pair (its event kind
      is in :data:`LANES_BY_EVENT_KIND`, which is what says the value came
      from `episode_containers.span_from_claims` rather than from a date).
    * ``point`` — a ``best_temporal_value``, drawn as a mark as wide as its
      stated grain and never wider.
    * ``window`` — no value of its own: a ``possible_temporal_value``, which
      is either an era `within` a frame (§4.2) or the containment outer range
      (the intersection when there are several).
    * ``none`` — unplaced; the cloud.
    """
    row = node.to_dict() if hasattr(node, "to_dict") else node
    if not isinstance(row, dict):
        return "none"
    if isinstance(row.get("definition_span"), dict):
        return "duration"
    if row.get("best_temporal_value") is not None:
        if (collapsed_text(row.get("node_kind")) == "episode"
                and collapsed_text(row.get("event_kind")) in LANES_BY_EVENT_KIND):
            return "duration"
        return "point"
    if row.get("possible_temporal_value") is not None:
        return "window"
    return "none"


def validate_lane_row(value: object) -> dict:
    """One ``lanes`` row, normalized (schema v3, design §9.2/§9.6).

    A row is a row GROUP's lane, not a node's: ``group_id`` is the frame or
    era node the lane is drawn inside, and ``episode_node_ids`` are the
    participation episodes that belong to it. Sorted here so two hosts
    assembling the same group in two orders publish the same bytes.
    """
    row = value if isinstance(value, dict) else {}
    group_id = collapsed_text(row.get("group_id"))
    lane = collapsed_text(row.get("lane"))
    if not group_id:
        raise TimelineNodeError("lane_needs_group", "a lane row names its row group")
    if lane not in LANES:
        raise TimelineNodeError("unknown_lane", f"unknown lane: {lane!r}")
    members = _ref_tuple(row.get("episode_node_ids"))
    return {
        "group_id": group_id,
        "lane": lane,
        "episode_node_ids": sorted(members),
    }


# --------------------------------------------------------------------------
# CalculatedMembership
# --------------------------------------------------------------------------


class CalculatedMembershipError(TemporalContractError):
    """A membership cannot say what evidence puts a thing inside a container."""


@dataclass(frozen=True)
class CalculatedMembership:
    """One thing inside one era or frame, and why (eras design §2.2, §2.4).

    **The schema lands in E1 and E2 writes the rows.** It is here now because
    the projection's key set is what a tolerant reader is written against: E2
    adds memberships, not a new top-level key nobody's reader knows about.

    ``relation`` is arithmetic for a frame (``within`` when the interval is
    inside one frame, ``overlaps`` per frame a wider interval touches) and
    evidence-backed for a named era. ``evidence_refs`` is never empty: date
    overlap alone yields no named-era membership, and a membership that cannot
    cite a receipt, a constraint or a declared rule is a fabrication in exactly
    the sense ``node_without_inputs`` names for a node. ``display_role`` is
    rendering ONLY — it never changes chronology.
    """

    membership_id: str
    member_node_id: str
    era_node_id: str
    relation: str
    evidence_refs: tuple[str, ...]
    basis: str = "inferred"
    confidence: float = 0.0
    display_role: str = "none"
    input_fingerprint: str | None = None
    schema_version: int = PROJECTION_SCHEMA_VERSION

    def to_dict(self) -> dict:
        payload = {
            "membership_id": self.membership_id,
            "schema_version": self.schema_version,
            "member_node_id": self.member_node_id,
            "era_node_id": self.era_node_id,
            "relation": self.relation,
            "evidence_refs": list(self.evidence_refs),
            "basis": self.basis,
            "confidence": self.confidence,
            "display_role": self.display_role,
        }
        if self.input_fingerprint is not None:
            payload["input_fingerprint"] = self.input_fingerprint
        return payload


def validate_calculated_membership(value: object) -> dict:
    """Normalize a membership or raise :class:`CalculatedMembershipError`.

    The id is always RE-DERIVED, like a work item's: a supplied id is
    annotation, and identity is what the three keys say it is.
    """
    if isinstance(value, CalculatedMembership):
        value = value.to_dict()
    if not isinstance(value, dict):
        raise CalculatedMembershipError(
            "membership_not_a_mapping", "a membership must be a mapping"
        )
    member = collapsed_text(value.get("member_node_id"))
    if not member:
        raise CalculatedMembershipError(
            "membership_needs_member", "a membership needs the node it is about"
        )
    era = collapsed_text(value.get("era_node_id"))
    if not era:
        raise CalculatedMembershipError(
            "membership_needs_era", "a membership needs the era or frame it is inside"
        )
    relation = collapsed_text(value.get("relation"))
    if relation not in MEMBERSHIP_RELATIONS:
        raise CalculatedMembershipError(
            "unknown_membership_relation", f"unknown relation: {relation!r}"
        )
    display_role = collapsed_text(value.get("display_role")) or "none"
    if display_role not in MEMBERSHIP_DISPLAY_ROLES:
        raise CalculatedMembershipError(
            "unknown_membership_display_role", f"unknown display_role: {display_role!r}"
        )
    basis = collapsed_text(value.get("basis")) or "inferred"
    if basis not in CLAIM_BASES:
        raise CalculatedMembershipError("unknown_claim_basis", f"unknown basis: {basis!r}")
    evidence = _ref_tuple(value.get("evidence_refs"))
    if not evidence:
        raise CalculatedMembershipError(
            "membership_without_evidence",
            f"{member} in {era} cites nothing; date overlap alone is not a membership",
        )
    normalized = {
        "membership_id": derive_membership_id(
            member_node_id=member, era_node_id=era, relation=relation
        ),
        "schema_version": PROJECTION_SCHEMA_VERSION,
        "member_node_id": member,
        "era_node_id": era,
        "relation": relation,
        "evidence_refs": list(evidence),
        "basis": basis,
        "confidence": unit_score(value.get("confidence"), error=CalculatedMembershipError),
        "display_role": display_role,
    }
    fingerprint = collapsed_text(value.get("input_fingerprint"))
    if fingerprint:
        normalized["input_fingerprint"] = fingerprint
    return normalized


def membership_from_dict(value: object) -> CalculatedMembership | None:
    """Tolerant reader — ``None`` rather than an exception."""
    try:
        normalized = validate_calculated_membership(value)
    except TemporalContractError:
        return None
    return CalculatedMembership(
        membership_id=normalized["membership_id"],
        member_node_id=normalized["member_node_id"],
        era_node_id=normalized["era_node_id"],
        relation=normalized["relation"],
        evidence_refs=tuple(normalized["evidence_refs"]),
        basis=normalized["basis"],
        confidence=normalized["confidence"],
        display_role=normalized["display_role"],
        input_fingerprint=normalized.get("input_fingerprint"),
        schema_version=int(normalized.get("schema_version") or PROJECTION_SCHEMA_VERSION),
    )


# --------------------------------------------------------------------------
# ChapterOverlay
# --------------------------------------------------------------------------


class ChapterOverlayError(TemporalContractError):
    """An overlay cannot say which chapter it is, or what it covers."""


@dataclass(frozen=True)
class ChapterOverlay:
    """One chapter drawn ACROSS the age frames it covers (eras design §5.2).

    §5.2's rendering reads "period nodes; every frame is a band; chapters as
    ``chapter_overlays``". A chapter is not a band — it is a stripe laid over
    however many frames its span reaches — so it is a TOP-LEVEL row of the
    projection, keyed on the chapter, and not a list repeated on every frame
    node it touches. Repeating it per frame would write one chapter's identity
    five times with no single place to correct it, which is precisely the
    parallel-definition shape ADR 0021 exists to stop (`O-E1b` finding 3).

    **The schema lands here and E3 writes the rows**, for the same reason
    :class:`CalculatedMembership` landed empty in E1: a tolerant reader is
    written against a key set, and a phase that adds rows to a declared key is
    a data change, while a phase that adds the key is a schema change every
    host has to learn again.
    """

    overlay_id: str
    chapter_node_id: str
    frame_node_ids: tuple[str, ...]
    label: str | None = None
    span: dict | None = None
    schema_version: int = PROJECTION_SCHEMA_VERSION

    def to_dict(self) -> dict:
        payload: dict = {
            "overlay_id": self.overlay_id,
            "schema_version": self.schema_version,
            "chapter_node_id": self.chapter_node_id,
            "frame_node_ids": list(self.frame_node_ids),
        }
        for key, value in (("label", self.label), ("span", self.span)):
            if value is not None:
                payload[key] = value
        return payload


#: The overlay's field names, as DATA, so a host's wire contract and a parity
#: guard read them instead of re-typing them (ADR 0021).
CHAPTER_OVERLAY_FIELDS = (
    "overlay_id",
    "schema_version",
    "chapter_node_id",
    "frame_node_ids",
    "label",
    "span",
)


def validate_chapter_overlay(value: object) -> dict:
    """Normalize an overlay or raise :class:`ChapterOverlayError`.

    An overlay covering NO frame is refused for the reason
    ``membership_without_evidence`` refuses an uncited membership: a stripe
    across nothing is not a rendering instruction, it is a row that would make
    a page draw an empty band a person never lived in.
    """
    if isinstance(value, ChapterOverlay):
        value = value.to_dict()
    if not isinstance(value, dict):
        raise ChapterOverlayError("overlay_not_a_mapping", "an overlay must be a mapping")
    chapter = collapsed_text(value.get("chapter_node_id"))
    if not chapter:
        raise ChapterOverlayError(
            "overlay_needs_chapter", "an overlay needs the chapter it draws"
        )
    frames = _ref_tuple(value.get("frame_node_ids"))
    if not frames:
        raise ChapterOverlayError(
            "overlay_without_frames", f"{chapter} covers no frame; an overlay draws across frames"
        )
    normalized: dict = {
        "overlay_id": derive_chapter_overlay_id(chapter_node_id=chapter),
        "schema_version": PROJECTION_SCHEMA_VERSION,
        "chapter_node_id": chapter,
        "frame_node_ids": list(frames),
    }
    label = optional_text(value.get("label"))
    if label:
        normalized["label"] = label
    span = _normalized_node_value(value.get("span"))
    if span is not None:
        normalized["span"] = span
    return normalized


def chapter_overlay_from_dict(value: object) -> ChapterOverlay | None:
    """Tolerant reader — ``None`` rather than an exception."""
    try:
        normalized = validate_chapter_overlay(value)
    except TemporalContractError:
        return None
    return ChapterOverlay(
        overlay_id=normalized["overlay_id"],
        chapter_node_id=normalized["chapter_node_id"],
        frame_node_ids=tuple(normalized["frame_node_ids"]),
        label=normalized.get("label"),
        span=normalized.get("span"),
        schema_version=int(normalized.get("schema_version") or PROJECTION_SCHEMA_VERSION),
    )


# --------------------------------------------------------------------------
# TemporalWorkItem
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class TemporalWorkItem:
    """One thing the timeline still wants to know (plan §5.4).

    Gaps and contradictions are typed instances of one shape, not two systems:
    plan §14 row 6 says extend the gap path into typed temporal work items, and
    §5.4 says do not force contradictions into an API named only for "gaps".
    The identity is stable across Timeline, Mirror, whispers and the daily
    queue, which is what "answer or resolve once, update everywhere" means.

    Open items are an invitation, never a debt: nothing in this shape records
    an overdue date, and Timeline renders them as questions rather than tasks
    (plan §2.3, §8.1).
    """

    work_item_id: str
    kind: str
    state: str = "open"
    subject_ref: str | None = None
    event_ref: str | None = None
    node_ref: str | None = None
    claim_refs: tuple[str, ...] = ()
    evidence_refs: tuple[str, ...] = ()
    requested_field: str | None = None
    prompt_intent: str | None = None
    allowed_surfaces: tuple[str, ...] = ()
    #: Which versioned arithmetic minted ``system_value`` (O-E6). Optional and
    #: additive: an item written before the field existed reads as ``None``,
    #: and a reader that does not know it is unaffected. It is deliberately NOT
    #: in :data:`WORK_ITEM_IDENTITY_KEYS` — a re-scored item is the same item.
    score_rule: str | None = None
    scores: dict = field(default_factory=dict)
    created_at: str = ""
    updated_at: str = ""
    schema_version: int = SCHEMA_VERSION

    def to_dict(self) -> dict:
        payload: dict = {
            "work_item_id": self.work_item_id,
            "schema_version": self.schema_version,
            "kind": self.kind,
            "state": self.state,
            "claim_refs": list(self.claim_refs),
            "evidence_refs": list(self.evidence_refs),
            "allowed_surfaces": list(self.allowed_surfaces),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }
        payload.update(dict(self.scores))
        for key, value in (
            ("subject_ref", self.subject_ref),
            ("event_ref", self.event_ref),
            ("node_ref", self.node_ref),
            ("requested_field", self.requested_field),
            ("prompt_intent", self.prompt_intent),
            ("score_rule", self.score_rule),
        ):
            if value is not None:
                payload[key] = value
        return payload


def validate_temporal_work_item(value: object, *, now: object = None) -> dict:
    """Normalize a work item or raise :class:`TemporalWorkItemError`.

    The refusals that matter:

    * ``work_item_needs_subject_or_event`` — an item nothing can be asked about
      is not a question.
    * ``work_item_needs_requested_field`` — a gap that does not say *which*
      field is missing cannot generate a precise, event-specific question
      (plan §2.3), and cannot be closed by an answer either.
    * ``contradiction_needs_two_claims`` — a contradiction is a disagreement
      between claims; with fewer than two it is a gap wearing the wrong type.
    * ``work_item_needs_surface`` — an item allowed nowhere is invisible work.
      Restricting surfaces is how §2.4's loss rule is expressed: a generic
      loss-discovery item simply omits ``daily_question``.
    """
    if isinstance(value, TemporalWorkItem):
        value = value.to_dict()
    if not isinstance(value, dict):
        raise TemporalWorkItemError("work_item_not_a_mapping", "a work item must be a mapping")

    kind = collapsed_text(value.get("kind"))
    if kind not in WORK_ITEM_KINDS:
        raise TemporalWorkItemError("unknown_work_item_kind", f"unknown kind: {kind!r}")
    state = collapsed_text(value.get("state")) or "open"
    if state not in WORK_ITEM_STATES:
        raise TemporalWorkItemError("unknown_work_item_state", f"unknown state: {state!r}")

    subject_ref = optional_text(value.get("subject_ref"))
    event_ref = optional_text(value.get("event_ref"))
    if not subject_ref and not event_ref:
        raise TemporalWorkItemError(
            "work_item_needs_subject_or_event",
            "a work item is about a subject or an event",
        )

    requested_field = optional_text(value.get("requested_field"))
    if kind in ("missing_anchor", "precision_gap") and not requested_field:
        raise TemporalWorkItemError(
            "work_item_needs_requested_field",
            f"a {kind} names the field it is missing",
        )

    claim_refs = _ref_tuple(value.get("claim_refs"))
    if kind == "contradiction" and len(claim_refs) < 2:
        raise TemporalWorkItemError(
            "contradiction_needs_two_claims",
            f"a contradiction cites the claims that disagree, got {len(claim_refs)}",
        )

    raw_surfaces = value.get("allowed_surfaces")
    if isinstance(raw_surfaces, (str, bytes)):
        raw_surfaces = [raw_surfaces]
    surfaces = tuple(dict.fromkeys(collapsed_text(s) for s in (raw_surfaces or ()) if collapsed_text(s)))
    for surface in surfaces:
        if surface not in WORK_ITEM_SURFACES:
            raise TemporalWorkItemError(
                "unknown_work_item_surface", f"unknown surface: {surface!r}"
            )
    if not surfaces:
        raise TemporalWorkItemError(
            "work_item_needs_surface", "a work item allowed nowhere is invisible work"
        )

    scores: dict = {}
    for name in WORK_ITEM_SCORE_FIELDS:
        if value.get(name) is None:
            continue
        try:
            scores[name] = unit_score(value.get(name), error=TemporalWorkItemError)
        except TemporalContractError as exc:
            raise TemporalWorkItemError(
                "score_out_of_range", f"{name}: {exc.message}"
            ) from None

    created_at = normalized_timestamp(
        value.get("created_at") or now, error=TemporalWorkItemError
    )
    updated_at = normalized_timestamp(
        value.get("updated_at") or value.get("created_at") or now,
        error=TemporalWorkItemError,
    )

    work_item_id = derive_work_item_id(
        kind=kind,
        subject_ref=subject_ref,
        event_ref=event_ref,
        requested_field=requested_field,
    )

    normalized: dict = {
        "work_item_id": work_item_id,
        "schema_version": SCHEMA_VERSION,
        "kind": kind,
        "state": state,
        "claim_refs": list(claim_refs),
        "evidence_refs": list(_ref_tuple(value.get("evidence_refs"))),
        "allowed_surfaces": list(surfaces),
        "created_at": created_at,
        "updated_at": updated_at,
    }
    normalized.update(scores)
    for key, cleaned in (
        ("subject_ref", subject_ref),
        ("event_ref", event_ref),
        ("node_ref", optional_text(value.get("node_ref"))),
        ("requested_field", requested_field),
        ("prompt_intent", optional_text(value.get("prompt_intent"))),
        ("score_rule", optional_text(value.get("score_rule"))),
        # Timeline Fix 07 (lifehug-platform#761). Additive and optional: WHY
        # this item has no `prompt_intent`. An item may legitimately have no
        # sentence — the composer refused to print a template at a person —
        # and the host already refuses to open an item with no intent, so the
        # reason is what turns a silent absence into an honest line on the
        # page. Absent on every item that HAS a question.
        ("withheld_reason", optional_text(value.get("withheld_reason"))),
    ):
        if cleaned:
            normalized[key] = cleaned
    # Timeline Fix 07 D4: the kinds this item ABSORBED because one node gets
    # one question. Additive; absent when nothing was absorbed.
    superseded = tuple(dict.fromkeys(
        collapsed_text(name) for name in (value.get("superseded_kinds") or ())
        if collapsed_text(name)
    ))
    if superseded:
        normalized["superseded_kinds"] = list(superseded)
    return normalized


def work_item_from_dict(value: object) -> TemporalWorkItem | None:
    """Tolerant reader — ``None`` rather than an exception."""
    try:
        normalized = validate_temporal_work_item(value)
    except TemporalContractError:
        return None
    return TemporalWorkItem(
        work_item_id=normalized["work_item_id"],
        kind=normalized["kind"],
        state=normalized["state"],
        subject_ref=normalized.get("subject_ref"),
        event_ref=normalized.get("event_ref"),
        node_ref=normalized.get("node_ref"),
        claim_refs=tuple(normalized["claim_refs"]),
        evidence_refs=tuple(normalized["evidence_refs"]),
        requested_field=normalized.get("requested_field"),
        prompt_intent=normalized.get("prompt_intent"),
        score_rule=normalized.get("score_rule"),
        allowed_surfaces=tuple(normalized["allowed_surfaces"]),
        scores={k: normalized[k] for k in WORK_ITEM_SCORE_FIELDS if k in normalized},
        created_at=normalized["created_at"],
        updated_at=normalized["updated_at"],
        schema_version=int(normalized.get("schema_version") or SCHEMA_VERSION),
    )


def surfaces_conflict(items: object) -> tuple[str, ...]:
    """Work item ids appearing more than once — the same item competing itself.

    Plan §2.3: an item presented as the main daily question must not also
    appear as a whisper in the same interaction. Because the id is stable
    across surfaces, "is this the same item?" is a set operation, and this is
    it — the selection policy that acts on the answer is wave F's.
    """
    seen: dict[str, int] = {}
    for item in items or ():
        identifier = collapsed_text(
            item.get("work_item_id") if isinstance(item, dict) else getattr(item, "work_item_id", "")
        )
        if identifier:
            seen[identifier] = seen.get(identifier, 0) + 1
    return tuple(sorted(key for key, count in seen.items() if count > 1))


__all__ = [
    "AGE_FRAME_EVENT_KIND",
    "NAMED_ERA_EVENT_KIND",
    "AXIS_RELATIONS",
    "CONFLICT_STATES",
    "FRAME_MEMBERSHIP_RULE",
    "LIFE_VIEWS",
    "OCCURRENCE_SUBJECT_SCOPES",
    "OWNER_TIMELINE_RELATIONS",
    "MEMBERSHIP_DISPLAY_ROLES",
    "MEMBERSHIP_RELATIONS",
    "ORIGIN_BASES",
    "PERIOD_EVENT_KINDS",
    "PROJECTION_SCHEMA_FLAG",
    "PROJECTION_SCHEMA_VERSION",
    "PROJECTION_SCHEMA_VERSIONS",
    "PROJECTION_SCHEMA_VERSION_LATEST",
    "PROJECTION_SCHEMA_WRITABLE",
    "LANES",
    "LANES_BY_EVENT_KIND",
    "LANE_ROW_KEYS",
    "PARTICIPATION_EVENT_KINDS",
    "VALUE_SHAPES",
    "TEMPORAL_STATES",
    "ERROR_CODES",
    "NODE_IDENTITY_KEYS",
    "NODE_KINDS",
    "PROJECTION_FILE",
    "WORK_ITEMS_FILE",
    "WORK_ITEM_IDENTITY_KEYS",
    "WORK_ITEM_KINDS",
    "WORK_ITEM_SCORE_FIELDS",
    "WORK_ITEM_STATES",
    "WORK_ITEM_SURFACES",
    "CalculatedMembership",
    "CalculatedMembershipError",
    "CHAPTER_OVERLAY_FIELDS",
    "CHAPTER_OVERLAY_ID_PREFIX",
    "ChapterOverlay",
    "ChapterOverlayError",
    "CalculatedTimelineNode",
    "TemporalWorkItem",
    "TemporalWorkItemError",
    "TimelineNodeError",
    "age_frame_identity",
    "age_frame_node_id",
    "derive_input_fingerprint",
    "derive_membership_id",
    "derive_node_id",
    "derive_value_shape",
    "derive_work_item_id",
    "projection_schema_version",
    "validate_lane_row",
    "membership_from_dict",
    "node_from_dict",
    "surfaces_conflict",
    "validate_calculated_membership",
    "validate_chapter_overlay",
    "chapter_overlay_from_dict",
    "derive_chapter_overlay_id",
    "validate_calculated_timeline_node",
    "validate_temporal_work_item",
    "work_item_from_dict",
]
