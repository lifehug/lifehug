#!/usr/bin/env python3
"""Timeline refresh outcomes the framework settles without a model (v373).

A context refresh (``refresh_reason`` ``context_changed`` or
``relationship_changed``) re-reads only an existing classification's three
link fields. Two kinds of event need no judgment to do that, and this module
is the one definition of both:

``A_RULE_FORCED_OUTCOME_NEEDS_NO_MODEL``
    The validator already decides the outcome. An event whose candidate
    search is incomplete can only be ``incomplete``; one whose complete
    candidate set is empty can only be ``missing_evidence``; one whose every
    candidate carries an unresolved or ambiguous identity can only be
    ``ambiguous``. (An event previously judged ``not_temporal`` keeps that
    status in the last two cases: whether an item is an event at all does not
    depend on the timeline around it.) Asking a model for these spends a whole
    prompt to learn what the rule already says.

``A_RE_KEYED_LINK_REMAPS_BY_IDENTITY``
    A stored link names a node id that no longer exists. Node ids are hashes
    of kind, subject words and discriminator, so renaming the words a stay is
    known by (a landmark's nickname) moves the id while the stay stays put.
    When exactly one candidate in the event's own complete set is provably the
    old node — the projection's own ``node_aliases`` says so, or the old id
    recomputes from that candidate's kind and discriminator with a subject
    word of an entity the link already cited, and that entity is one the
    candidate is — the link moves to it unchanged (same relation, same quote)
    with a ``remapped_from`` note, and it is validated exactly as a model's
    link would be. No unique proof, no remap: the event goes to the model.

Every other event needs judgment and is the only thing a prompt carries. The
rule's deltas are the same four-key link deltas a model returns and pass
through the same validator. Nothing here changes ``context_digest``,
``PROMPT_VERSION`` or ``EXTRACTOR_VERSION``.
"""

from __future__ import annotations

import copy
import json

import classifier_context as classifier_ctx
import temporal_projection
import timeline_evidence
from temporal_claims import collapsed_text

A_RULE_FORCED_OUTCOME_NEEDS_NO_MODEL = "A_RULE_FORCED_OUTCOME_NEEDS_NO_MODEL"
A_RE_KEYED_LINK_REMAPS_BY_IDENTITY = "A_RE_KEYED_LINK_REMAPS_BY_IDENTITY"
RULES = (A_RULE_FORCED_OUTCOME_NEEDS_NO_MODEL, A_RE_KEYED_LINK_REMAPS_BY_IDENTITY)

#: Classification fields (additive, v373). ``settled_by`` is ``"rule"`` when
#: no model read this refresh and ``"model"`` when one did; the per-event
#: account is ``rule_settlements``. ``model_used`` keeps naming the model that
#: last read the source, which for a rule-only refresh is the earlier reader.
SETTLED_BY_FIELD = "settled_by"
RULE_SETTLEMENTS_FIELD = "rule_settlements"
#: The plan/report key and its two values.
SETTLE_FIELD = "settle"
SETTLE_RULE = "rule"
SETTLE_MODEL = "model"
TIMELINE_REFRESH_REASONS = ("context_changed", "relationship_changed")

_REASONS = {
    "incomplete": (
        "Settled by rule: this event's candidate search is incomplete, so "
        "no link can be chosen until it completes."
    ),
    "missing_evidence": (
        "Settled by rule: the complete candidate search found no candidate "
        "for this event."
    ),
    "ambiguous": (
        "Settled by rule: every candidate for this event has an unresolved "
        "or ambiguous identity, so none can be linked."
    ),
    "not_temporal": (
        "Settled by rule: this item was read as not an event, and no "
        "linkable candidate exists to revisit that."
    ),
    "linked": (
        "Settled by rule: the linked node was re-keyed; the same relation "
        "and quote now name its current id."
    ),
}


def _stored_status(event: dict) -> str:
    resolution = event.get("timeline_resolution")
    if not isinstance(resolution, dict):
        return ""
    return collapsed_text(resolution.get("status"))


def _abstain(key: str, status: str, candidate_ids: list[str]) -> dict:
    return {
        "event_key": key,
        "source_grounding": None,
        "timeline_relation": None,
        "timeline_resolution": {
            "status": status,
            "candidate_ids": list(candidate_ids),
            "reason": _REASONS[status],
        },
    }


def _forced_status(event: dict, context: dict, candidates: dict) -> str | None:
    """The one outcome the validator allows, or ``None`` when judgment is needed."""
    candidate_ids = list(context.get("candidate_ids") or ())
    if not context.get("complete"):
        return "incomplete"
    keep_not_temporal = _stored_status(event) == "not_temporal"
    if not candidate_ids:
        return "not_temporal" if keep_not_temporal else "missing_evidence"
    rows = [candidates.get(candidate_id) for candidate_id in candidate_ids]
    if all(
        isinstance(row, dict) and not classifier_ctx.candidate_identity_is_resolved(row)
        for row in rows
    ):
        return "not_temporal" if keep_not_temporal else "ambiguous"
    return None


def _remap_target(
    relation: dict,
    context: dict,
    snapshot: dict,
) -> str | None:
    """The one candidate provably equal to the vanished linked node, if any."""
    old = collapsed_text(relation.get("candidate_id"))
    remap = (snapshot.get(classifier_ctx.LINK_REMAP_FIELD) or {}).get(old)
    if not old or not isinstance(remap, dict):
        return None
    candidate_ids = [str(value) for value in context.get("candidate_ids") or ()]
    identities = snapshot.get(classifier_ctx.CANDIDATE_IDENTITY_FIELD) or {}
    subject_terms = remap.get("subject_terms") if isinstance(remap.get("subject_terms"), dict) else {}
    matches: set[str] = set()
    alias = collapsed_text(remap.get("alias"))
    if alias and alias in candidate_ids:
        matches.add(alias)
    for candidate_id in candidate_ids:
        identity = identities.get(candidate_id)
        if not isinstance(identity, dict):
            continue
        shared = set(subject_terms).intersection(identity.get("identity_refs") or ())
        if not shared:
            continue
        discriminators = [None, *(identity.get("discriminators") or ())]
        for ref in sorted(shared):
            terms = [ref, *(subject_terms.get(ref) or ())]
            if any(
                temporal_projection.derive_node_id(
                    node_kind=identity.get("node_kind"),
                    event_kind=identity.get("event_kind"),
                    subject_refs=[term],
                    discriminator=discriminator,
                ) == old
                for term in terms
                for discriminator in discriminators
            ):
                matches.add(candidate_id)
                break
    return next(iter(matches)) if len(matches) == 1 else None


def _remapped_delta(
    key: str,
    event: dict,
    context: dict,
    candidates: dict,
    snapshot: dict,
    story_text: str,
) -> dict | None:
    relation = event.get("timeline_relation")
    if (not isinstance(relation, dict) or _stored_status(event) != "linked"
            or not isinstance(relation.get("evidence"), dict)):
        return None
    old = collapsed_text(relation.get("candidate_id"))
    if not old or old in candidates:
        return None
    target = _remap_target(relation, context, snapshot)
    if target is None:
        return None
    candidate = candidates.get(target)
    refs = sorted(str(ref) for ref in (candidate or {}).get("entity_refs") or () if ref)
    if not refs:
        return None
    remapped = {
        "relation": relation.get("relation"),
        "candidate_id": target,
        "entity_refs": refs,
        "evidence": {"quote": relation["evidence"].get("quote")},
    }
    local = {
        candidate_id: candidates[candidate_id]
        for candidate_id in context.get("candidate_ids") or ()
        if candidate_id in candidates
    }
    try:
        classifier_ctx._validate_relation(  # noqa: SLF001 - the one relation check
            copy.deepcopy(remapped), candidates=local, context=context, story_text=story_text,
        )
    except classifier_ctx.ClassifierContextError:
        return None
    remapped["remapped_from"] = old
    return {
        "event_key": key,
        "source_grounding": None,
        "timeline_relation": remapped,
        "timeline_resolution": {
            "status": "linked",
            "candidate_ids": list(context.get("candidate_ids") or ()),
            "reason": _REASONS["linked"],
        },
    }


def settle(snapshot: dict, existing: object, story_text: str) -> dict:
    """Split one timeline refresh into rule-settled deltas and judgment keys.

    Returns ``{"deltas": {event_key: delta}, "notes": [..], "judgment_keys":
    [..]}`` in stored event order. Pure: reads the snapshot and the stored
    classification, writes nothing.
    """
    row = existing if isinstance(existing, dict) else {}
    candidates = {
        str(candidate.get("candidate_id")): candidate
        for candidate in snapshot.get("candidates") or ()
        if isinstance(candidate, dict) and candidate.get("candidate_id")
    }
    deltas: dict[str, dict] = {}
    notes: list[dict] = []
    judgment: list[str] = []
    for stored in row.get("events") or ():
        if not isinstance(stored, dict):
            continue
        event = copy.deepcopy(stored)
        try:
            key = timeline_evidence.ensure_event_key(event)
        except timeline_evidence.TimelineEvidenceError:
            judgment.append(timeline_evidence.event_key(event))
            continue
        context = classifier_ctx._event_context(snapshot, event)  # noqa: SLF001
        status = _forced_status(event, context, candidates)
        if status is not None:
            deltas[key] = _abstain(key, status, list(context.get("candidate_ids") or ()))
            notes.append({
                "event_key": key,
                "rule": A_RULE_FORCED_OUTCOME_NEEDS_NO_MODEL,
                "status": status,
            })
            continue
        delta = _remapped_delta(key, event, context, candidates, snapshot, story_text)
        if delta is not None:
            deltas[key] = delta
            notes.append({
                "event_key": key,
                "rule": A_RE_KEYED_LINK_REMAPS_BY_IDENTITY,
                "status": "linked",
                "remapped_from": delta["timeline_relation"]["remapped_from"],
                "candidate_id": delta["timeline_relation"]["candidate_id"],
            })
            continue
        judgment.append(key)
    return {"deltas": deltas, "notes": notes, "judgment_keys": judgment}


def settle_mode(snapshot: dict, existing: object, story_text: str, *, reason: object) -> str:
    """``"rule"`` when this pending refresh needs no model call at all."""
    if reason not in TIMELINE_REFRESH_REASONS or not isinstance(existing, dict):
        return SETTLE_MODEL
    try:
        settled = settle(snapshot, existing, story_text)
    except Exception:  # noqa: BLE001 - an unreadable base is the model's to read
        return SETTLE_MODEL
    return SETTLE_MODEL if settled["judgment_keys"] else SETTLE_RULE


def rule_response(snapshot: dict) -> dict:
    """The exact timeline response for a source settled entirely by rule.

    A host that sees ``settle: "rule"`` on a plan item files this (with no
    model call) through the same ``--from-batch-response`` path.
    """
    return {
        "_classification_mode": "timeline",
        "_classification_snapshot": classifier_ctx.snapshot_metadata(snapshot),
        "events": [],
    }


def rule_response_text(snapshot: dict) -> str:
    return json.dumps(rule_response(snapshot), sort_keys=True)


__all__ = [
    "A_RE_KEYED_LINK_REMAPS_BY_IDENTITY",
    "A_RULE_FORCED_OUTCOME_NEEDS_NO_MODEL",
    "RULES",
    "RULE_SETTLEMENTS_FIELD",
    "SETTLED_BY_FIELD",
    "SETTLE_FIELD",
    "SETTLE_MODEL",
    "SETTLE_RULE",
    "rule_response",
    "rule_response_text",
    "settle",
    "settle_mode",
]
