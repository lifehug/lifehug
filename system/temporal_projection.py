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

#: What the node's inputs currently say about each other. ``alternatives``
#: means materially supported readings coexist; ``contradicted`` means two
#: claims cannot both be true and Mirror owns a row for it (plan §2.5, §8.2).
CONFLICT_STATES = ("none", "alternatives", "contradicted")

#: Typed work, one identity across every surface (plan §5.4, §14 row 6). A
#: contradiction is not forced into an API named only for "gaps".
WORK_ITEM_KINDS = ("missing_anchor", "precision_gap", "contradiction", "identity_uncertain")

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
    schema_version: int = SCHEMA_VERSION

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
        ):
            if value is not None:
                payload[key] = value
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

    normalized: dict = {
        "node_id": node_id,
        "schema_version": SCHEMA_VERSION,
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
    for key in ("event_kind", "label", "provenance_summary", "model_version"):
        cleaned = optional_text(value.get(key))
        if cleaned:
            normalized[key] = cleaned
    return normalized


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
        schema_version=int(normalized.get("schema_version") or SCHEMA_VERSION),
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
    ):
        if cleaned:
            normalized[key] = cleaned
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
    "CONFLICT_STATES",
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
    "CalculatedTimelineNode",
    "TemporalWorkItem",
    "TemporalWorkItemError",
    "TimelineNodeError",
    "derive_input_fingerprint",
    "derive_node_id",
    "derive_work_item_id",
    "node_from_dict",
    "surfaces_conflict",
    "validate_calculated_timeline_node",
    "validate_temporal_work_item",
    "work_item_from_dict",
]
