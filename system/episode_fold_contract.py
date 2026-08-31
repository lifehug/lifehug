#!/usr/bin/env python3
"""I0-C3 — fold semantics and id mapping, as pure decisions. Nothing live moves.

Controlling design: lifehug-platform `docs/design/event-identity.md` (v4),
§3.5, §5.1–§5.4 and §5.6. Contract doc: `docs/contracts/event-identity-i0-fold.md`.

**What this module is and is not.** Phase I0 is the executable half of the
plan the auditor demanded before any implementation phase begins: the
decisions the fold WILL make, written as pure functions with exhaustive
fixtures, so that I1 wires an already-proven contract into
`temporal_timeline` rather than deciding these questions inside a 4 000-line
fold. Nothing here is called by `temporal_timeline` yet, no claim shape
changes, `CALCULATION_RULE_VERSION` does not move (I1 takes
``timeline-rules:5`` when grouping actually changes), and every function is
pure — no I/O, no vault, no model, no clock.

Four decisions live here, each one an audit finding the plan had to answer:

**1. What groups with what** (:func:`grouping_key`, §5.1). An active ``same``
binding is the grouping authority: the telling's claims fold under the
episode's node instead of under the key v264 would have used. Two things the
design pins claim-precisely rather than telling-blanket, and both are
fixtures: a telling ABOUT an era — the person naming or bounding College —
is refused as a binding target, because that claim's ``event_ref`` is the
era and the era is not an episode; a telling about an event WITHIN an era
keeps full episode eligibility, because era membership is a receipt ABOUT a
node (`era_memberships`) and never a reason to discard a binding. A telling
whose claims disagree about which of the two they are is a refusal, never a
partial bind.

**2. Which id the group publishes** (:func:`episode_node_id`, §3.5). The
frozen minter, unchanged keys: ``derive_node_id(node_kind="episode",
event_kind=canonical_event_kind, subject_refs=subject_keys,
discriminator=episode_id)``. ``episode_id`` and ``node_id`` are two
identifiers with a DURABLE PUBLISHED MAPPING, not one identifier wearing two
names, and every telling's former node id lands in ``node_aliases`` so an
open session, a Mirror row and an old URL keep resolving.

**3. What a negative entails** (:func:`entailed_not_same`, §2.2).
``same(A,E) ∧ not_same(B,E) ⇒ not_same(A,B)``, computed at fold time from the
active bindings and NEVER stored expanded — storing the closure is how a
retracted binding leaves a permanent phantom negative behind.

**4. What a containment edge draws** (:func:`possible_outer_range`, §5.3).
The same discipline `temporal_timeline._colocation_record` already holds to,
which is why this function is written against `chronology.DateRecord` and not
against a shape of its own: the bounds are the episode's OWN bounds copied
(never narrower, structurally), the rule reads ``best is None`` and nothing
else (never overrides, structurally), ``anchors`` is empty (never an anchor,
structurally), and the member keeps its own precision question — better
anchored, not suppressed.

**The refusals are loud** (§5.4). Two active ``same`` bindings for one
telling, neither superseding the other, RAISE
:data:`REFUSAL_IDENTITY_CONFLICT` rather than resolving by recency, for
`event_binding`'s reason: the later record is not more right, it is just
later. A dormant binding — one whose telling has no active claims — is
reported and ignored, because a retracted claim is not a bug in the binding.

**The determinism contract is the honest one** (§5.6, audit F4/G3). A fixed
set of receipts folds byte-identically under any application order, and
:func:`grouping_fingerprint` is what a permutation test compares. There is NO
partition-equality promise across arrival orders and no claim that divergence
can only over-split: an early sole-candidate bind can attach a telling to E1
where another order would have seen E2 as well. The contract is that such a
divergence is SURFACED — `episode_routing_contract.reaudit` mints one
``possible_overmerge`` naming both sides — never silently resolved.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

SYSTEM_DIR = Path(__file__).resolve().parent
if str(SYSTEM_DIR) not in sys.path:
    sys.path.insert(0, str(SYSTEM_DIR))

import chronology as chrono  # noqa: E402
import temporal_projection as tp  # noqa: E402
from temporal_claims import (  # noqa: E402
    TemporalContractError,
    collapsed_text,
    digest_id,
)

# --------------------------------------------------------------------------
# The vocabulary — one home, so a second copy is a build failure
# --------------------------------------------------------------------------

#: The identity layer's own rule version (design §7). It is deliberately NOT
#: `temporal_timeline.CALCULATION_RULE_VERSION`: the fold's arithmetic and the
#: identity layer's rules are recalibrated by different people for different
#: reasons, and a binding record stamps THIS one (`event_identity.rule_version`,
#: §3.3) so a rule-version upgrade can name exactly what it re-derives.
#:
#: **One definition, many hosts** (ADR 0021). Every module that needs it —
#: C1's manifest, C2's operations and bindings, C4's routing, I1's fold and the
#: platform's own vocabulary — IMPORTS it from here.
#: `tests/test_event_identity_i0_fold.py` sweeps `system/` and fails on a
#: second assignment.
IDENTITY_RULE_VERSION = "event-identity:1"

#: §2.2. Assertions about the world. ``unknown`` is deliberately absent: it is
#: an epistemic state about a PAIR, lives on the work item, and asserts
#: nothing.
RELATIONS = ("same", "part_of", "related", "not_same")

#: The only relation that co-groups tellings into one node (§2.2).
GROUPING_RELATION = "same"

#: §2.3. Where a binding came from, visibly.
ORIGINS = ("stated", "confirmed", "deterministic", "proposed")

#: §2.3: *"Only the first three affect grouping."* A ``proposed`` binding
#: changes no drawing — it ranks the question queue and renders at most a soft
#: "possibly the same as…" line.
GROUPING_ORIGINS = ("stated", "confirmed", "deterministic")

#: `temporal_projection.NODE_KINDS` already holds it; named here so the fold
#: and this contract cannot spell it two ways.
EPISODE_NODE_KIND = "episode"

#: What a claim's ``event_ref`` can name. An ``era:`` ref is E3's binder
#: (`event_binding`) recording that the person NAMED that stretch of life in
#: this utterance; a ``node:`` ref is v221's recorder-minted episode
#: (`identity_resolution.derive_episode_ref`).
ERA_REF_PREFIX = "era:"
NODE_REF_PREFIX = "node:"

#: §5.1, written down rather than described, for `COLOCATION_RULE_TEXT`'s
#: reason: the era half of the rule has two cases and only one of them is a
#: refusal, and the plan was audited twice over exactly that distinction.
GROUPING_RULE_TEXT = (
    "A telling with an active `same` binding whose origin is stated, "
    "confirmed or deterministic groups all of its active claims under the "
    "episode's node; the node id is derive_node_id(node_kind='episode', "
    "canonical_event_kind, subject_keys, discriminator=episode_id) and every "
    "key the telling's claims would otherwise have grouped under is published "
    "in node_aliases. A claim whose event_ref names an ERA is not "
    "episode-groupable — the telling is about the era itself, its boundary or "
    "its naming — and a binding found on it is reported at fold time and "
    "refused at write time. A telling about an event that happened WITHIN an "
    "era carries no era event_ref at all: it keeps full episode eligibility, "
    "and the era relationship is a membership on the episode's node. A "
    "recorder-minted episode event_ref and an episode binding COMPOSE: when "
    "the binding names the same node the ref already names, the two are one "
    "identity; when it names a different episode, the binding wins for "
    "grouping and the recorder's ref becomes a node alias. A telling whose "
    "claims disagree about which of these they are is a refusal, never a "
    "partial bind. A proposed binding groups nothing."
)

#: §5.3, likewise verbatim. Every clause of it is structural in
#: :func:`possible_outer_range` rather than asserted afterwards.
CONTAINMENT_RULE_TEXT = (
    "A contained member with no temporal value of its own renders a POSSIBLE "
    "OUTER RANGE — the containing episode's span, copied — with basis "
    "inferred and one provenance clause naming the episode. It is never "
    "stored, never narrower than the span, never overrides any value, never "
    "counts as an anchor, and never suppresses the member's own precision "
    "question: the probe just gets better, from \"when did this happen?\" to "
    "\"was that early or late in {episode}?\"."
)

#: The rule id every containment provenance clause carries, so a reader can
#: filter for "what did the SYSTEM put here" without parsing prose — the same
#: affordance `temporal_timeline.COLOCATION_RULE_ID` gives co-location.
CONTAINMENT_RULE_ID = "episode_containment"

#: A containment is a CONTAINMENT statement — "during the stretch that was
#: going on" — which is exactly what ``order`` means, and
#: `temporal_claims.CLAIM_BASIS_BY_DATE_BASIS` already publishes ``order`` as
#: ``inferred``. No new basis is minted, for `COLOCATION_DATE_BASIS`'s reason:
#: a seventh entry in `chronology.BASES` would reach the conversation prompt's
#: own basis vocabulary and invite a model to write it.
CONTAINMENT_DATE_BASIS = "order"

#: The clause the provenance entry reads. ``{span}`` is
#: `chronology.display_date(..., with_basis=False)`'s own rendering, so the sentence a person sees
#: under a contained row and the sentence under a co-located one are built the
#: same way.
CONTAINMENT_CLAIM_SENTENCE = "sometime during {episode} {span}"

#: The probe a contained member still gets (§5.3). Its existence IS the
#: promise that containment never suppresses the precision question.
CONTAINMENT_PROBE_TEXT = "Was that early or late in {episode}?"

# --------------------------------------------------------------------------
# Containment as a DETERMINISTIC rung (amendment v4.2 §12b rulings 2 and 5)
# --------------------------------------------------------------------------

#: The two evidence-grade containment rules, and the whole list. §12b ruling 5
#: is a CLOSED widening of C2's origin gate: *"deterministic containment is
#: admitted for the two evidence-grade rules (`question_context`; the
#: entity+span rung), and for nothing else."* A third rule id filing at
#: ``deterministic`` origin is refused by name, which is what makes this a gate
#: rather than a door left open.
#:
#: ONE HOME (ADR 0021). `event_identity.validate_event_identity` — the write
#: door — and `episode_containers` — the rung that mints them — both read this
#: tuple; a second spelling anywhere in `system/` fails the one-home sweep in
#: `tests/test_event_identity_i0_fold.py`.
RULE_ID_ENTITY_SPAN = "entity_span"
RULE_ID_QUESTION_CONTEXT = "question_context"
DETERMINISTIC_CONTAINMENT_RULE_IDS = (RULE_ID_ENTITY_SPAN, RULE_ID_QUESTION_CONTEXT)

#: §12b ruling 5, in the module rather than in a diff.
DETERMINISTIC_CONTAINMENT_RULE_TEXT = (
    "A deterministic rung binds `same` and — since amendment v4.2 — `part_of` "
    "for exactly two rule ids: `entity_span` (the telling shares a resolved "
    "entity with a container whose span came from the person's own words, and "
    "its date is inside that span or absent) and `question_context` (the "
    "answer was given to a question that targeted the container). Every other "
    "rule id filing a deterministic `part_of` is refused by name."
)

#: §12b ruling 6. Whether a containment record is a BINDING the drawing obeys
#: or a proposal beside it is the HOST's flag, never the rung's opinion — the
#: platform flips it to ``applied`` when the drag-out gesture that removes a
#: wrong placement is live (I-P), and until then the same records file as
#: proposals so nothing appears that a person cannot yet take back.
CONTAINMENT_AUTHORITIES = ("applied", "proposed")

#: The default. A vault whose host cannot yet undo a placement gets proposals.
DEFAULT_CONTAINMENT_AUTHORITY = "proposed"

#: The ONE thing the flag changes. ``origin`` is outside
#: :data:`event_identity.IDENTITY_IDENTITY_KEYS`, so the two authorities mint
#: the SAME ``identity_id``, the same evidence, the same rule id and the same
#: directory under ``state/`` — and the only consequence is which side of
#: :data:`GROUPING_ORIGINS` the record lands on, which is to say whether the
#: fold publishes it as ``containments`` or as ``proposed_links``.
CONTAINMENT_ORIGIN_BY_AUTHORITY = {"applied": "deterministic", "proposed": "proposed"}

CONTAINMENT_AUTHORITY_RULE_TEXT = (
    "The authority flag chooses one field — `origin` — and that field is "
    "outside the binding digest, so flipping it re-keys nothing, rewrites no "
    "evidence and moves no file: `applied` files `deterministic` and the fold "
    "publishes `containments`; `proposed` files `proposed` and the fold "
    "publishes `proposed_links`. Nothing else in the record differs."
)

#: The ONE in-place origin move the identity layer admits, and the whole list.
#:
#: :data:`CONTAINMENT_AUTHORITY_RULE_TEXT` already promises that flipping the
#: authority "re-keys nothing, rewrites no evidence and moves no file" — the
#: two authorities mint the same ``identity_id`` and
#: :func:`event_identity.bindings_dir` sends ``proposed`` and ``deterministic``
#: to the SAME directory. A run at the stronger authority therefore meets its
#: own record at its own path under its own id, and the only honest thing left
#: to do is move the one field the flag owns. Before this pair existed, that
#: run met create-or-keep, kept the proposal, and reported
#: ``containment_members: 0`` — which reads as *the rung found nothing*, the
#: exact misreading :func:`containment_origin` refuses an unknown authority to
#: prevent.
#:
#: ONE HOME (ADR 0021). `event_identity` is the write door and the only module
#: that acts on this; the binder and the containment rung read it to say what a
#: run WOULD do. A second spelling anywhere is a second answer to "which way
#: may an origin move".
ORIGIN_UPGRADES = (("proposed", "deterministic"),)

CONTAINMENT_AUTHORITY_UPGRADE_RULE_TEXT = (
    "Re-running the containment rung at `applied` authority over a record it "
    "already filed at `proposed` — identical in every field but `origin`, "
    "created_at included and preserved — moves that record's `origin` to "
    "`deterministic` IN PLACE: same file, same identity_id, same evidence, "
    "same clock, one field. The run counts it as an upgrade rather than a "
    "creation, because nothing was decided that was not decided before; only "
    "the host grew the gesture that lets a person take the placement back. "
    "The reverse is not a move. A run at `proposed` authority meeting a filed "
    "`deterministic` record KEEPS it and counts the keep, because a host that "
    "forgot its flag must not silently un-draw a containment the person can "
    "already see and already drag out. A record differing in anything besides "
    "`origin` is not an upgrade target at all: ordinary create-or-keep stands, "
    "and the difference is reported rather than resolved."
)

#: What one re-filing of a binding did. ``kept`` covers the byte-identical
#: replay; ``kept_stronger`` is the refused downgrade above; ``kept_differs``
#: is create-or-keep meeting a record that says something else.
BINDING_FILING_OUTCOMES = (
    "created", "upgraded", "kept", "kept_stronger", "kept_differs",
)


def origin_move(filed: object, minted: object) -> str:
    """``"same"`` · ``"upgrade"`` · ``"downgrade"`` · ``"unrelated"``.

    Pure, and deliberately about the ORIGINS alone: whether the two records
    are otherwise identical is a separate question, answered on the bytes by
    `event_identity.refile_event_identity` and never inferred from here.
    """
    left = collapsed_text(filed)
    right = collapsed_text(minted)
    if left == right:
        return "same"
    if (left, right) in ORIGIN_UPGRADES:
        return "upgrade"
    if (right, left) in ORIGIN_UPGRADES:
        return "downgrade"
    return "unrelated"


def containment_origin(authority: object) -> str:
    """The binding origin one authority files (:data:`CONTAINMENT_AUTHORITIES`).

    An unknown authority is a refusal rather than a fallback: a host that
    misspells its flag would otherwise silently get proposals and read the
    absence of drawn containments as "the rung found nothing".
    """
    text = collapsed_text(authority) or DEFAULT_CONTAINMENT_AUTHORITY
    if text not in CONTAINMENT_AUTHORITIES:
        raise TemporalContractError(
            "containment_authority_unknown",
            f"unknown containment authority: {authority!r}",
            detail={"authorities": list(CONTAINMENT_AUTHORITIES)},
        )
    return CONTAINMENT_ORIGIN_BY_AUTHORITY[text]


def deterministic_relation_allowed(relation: object, rule_id: object) -> bool:
    """May a ``deterministic`` binding assert this relation under this rule?

    C2's gate, as one predicate so the write door and the rung that mints the
    records cannot read §12b ruling 5 two different ways.
    """
    name = collapsed_text(relation)
    if name == GROUPING_RELATION:
        return True
    return (name == "part_of"
            and collapsed_text(rule_id) in DETERMINISTIC_CONTAINMENT_RULE_IDS)


# --------------------------------------------------------------------------
# Findings — raised loudly, or reported and ignored
# --------------------------------------------------------------------------

#: §5.4. Two active ``same`` bindings for one telling naming different
#: episodes, neither superseding the other — or one (telling, episode) pair
#: carrying two active bindings that disagree about the relation. Raised, for
#: `event_binding.event_resolution_ambiguous`'s reason.
#:
#: **The design's wording, pinned.** §5.4 reads *"two active bindings for one
#: telling without supersedes"*, which taken literally would also refuse the
#: five-answer model §6.1 requires: a telling legitimately carries ``same`` to
#: one episode and ``not_same`` to every episode the person has already
#: rejected. The conflict is therefore about the GROUPING decision — two
#: ``same`` bindings, or one pair decided twice — and nothing else.
REFUSAL_IDENTITY_CONFLICT = "identity_conflict"

#: §5.1/§13.1. A telling whose claims describe more than one event identity —
#: one claim about the era itself beside one about an event inside it. C1
#: refuses this at manifest build; the fold refuses it too rather than binding
#: the half that happens to look bindable.
REFUSAL_TELLING_MIXES_IDENTITIES = "telling_mixes_event_identities"

#: §5.4. Reported at fold time, refused at write time (C2 owns the write side).
DIAGNOSTIC_BINDING_TO_ERA_CLAIM = "identity_binding_to_era_bound_claim"

#: §3.3 lifecycle. A binding whose telling has no active claims. Reported,
#: ignored, never an error — a retracted claim is not a bug in the binding.
DIAGNOSTIC_DORMANT_BINDING = "identity_binding_dormant"

#: §5.1. A recorder-minted episode ref that the binding re-pointed. Not a
#: problem — it is the alias row's own receipt.
DIAGNOSTIC_EPISODE_REF_ALIASED = "identity_episode_ref_aliased"

#: §2.3. A ``proposed`` binding was seen and deliberately not applied.
DIAGNOSTIC_PROPOSAL_NOT_APPLIED = "identity_proposal_not_applied"

#: Every code this module can emit, so a host can count rejections by reason
#: and a test can prove the set is closed.
FOLD_FINDINGS = (
    REFUSAL_IDENTITY_CONFLICT,
    REFUSAL_TELLING_MIXES_IDENTITIES,
    DIAGNOSTIC_BINDING_TO_ERA_CLAIM,
    DIAGNOSTIC_DORMANT_BINDING,
    DIAGNOSTIC_EPISODE_REF_ALIASED,
    DIAGNOSTIC_PROPOSAL_NOT_APPLIED,
)

# --------------------------------------------------------------------------
# The manifest adapter — C1 owns the schema; this reads two fields of it
# --------------------------------------------------------------------------

#: The manifest fields this module reads, and the only ones. C1
#: (`docs/contracts/event-identity-i0-telling.md`) owns the schema; naming the
#: read surface here means a C1 schema change that breaks the fold breaks one
#: named function instead of a dozen call sites.
MANIFEST_READ_FIELDS = ("tellings", "telling_ref", "claim_ids", "status")


def manifest_claim_index(manifest: object) -> dict:
    """``{claim_id: telling_ref}`` from the telling manifest (§3.1).

    A retired manifest row (``status`` other than ``active``) contributes
    nothing: its claims have either moved to a successor row or left the
    active set, and either way the fold must not group through it.

    A claim listed by two ACTIVE rows is the manifest's own contradiction, not
    the fold's, and it raises :data:`REFUSAL_TELLING_MIXES_IDENTITIES` here
    rather than picking one — the same refusal C1 makes at manifest build,
    made again by the reader so a hand-edited manifest cannot slip past it.
    """
    rows = manifest.get("tellings") if isinstance(manifest, dict) else manifest
    index: dict[str, str] = {}
    for row in rows or ():
        if not isinstance(row, dict):
            continue
        status = collapsed_text(row.get("status")) or "active"
        if status != "active":
            continue
        telling_ref = collapsed_text(row.get("telling_ref"))
        if not telling_ref:
            continue
        for claim_id in row.get("claim_ids") or ():
            key = collapsed_text(claim_id)
            if not key:
                continue
            existing = index.get(key)
            if existing and existing != telling_ref:
                raise TemporalContractError(
                    REFUSAL_TELLING_MIXES_IDENTITIES,
                    "one claim is claimed by two active tellings; the manifest "
                    "must say which event identity it belongs to",
                    detail={"claim_id": key, "tellings": sorted([existing, telling_ref])},
                )
            index[key] = telling_ref
    return index


def telling_ref_for_claim(claim: object, manifest: object) -> str:
    """The telling a claim belongs to, or ``""`` when the manifest has no row.

    ``""`` is not an error: a claim extracted before the binder ever ran has
    no telling yet, and the fold's answer for it is v264's own key.
    """
    index = manifest if isinstance(manifest, dict) and "tellings" not in manifest \
        else manifest_claim_index(manifest)
    claim_id = collapsed_text(
        claim.get("claim_id") if isinstance(claim, dict) else claim
    )
    return collapsed_text(index.get(claim_id)) if claim_id else ""


# --------------------------------------------------------------------------
# Active bindings — supersession followed, conflicts raised
# --------------------------------------------------------------------------


def active_binding_index(bindings: object) -> dict:
    """``{telling_ref: (binding, …)}`` — the active bindings per telling.

    Supersession is followed first: a record named by another record's
    ``supersedes`` is out, whatever its timestamp. What survives may be
    several bindings for one telling and that is CORRECT — the five-answer
    model files ``same`` to one episode and ``not_same`` to each episode the
    person has already rejected (§6.1). What survives may NOT be two grouping
    decisions: two active ``same`` bindings naming different episodes, or one
    (telling, episode) pair decided twice with different relations, raise
    :data:`REFUSAL_IDENTITY_CONFLICT`.

    Ordering is deterministic — by ``identity_id`` — so the tuple a permuted
    input produces is the same tuple.
    """
    rows = [row for row in (bindings or ()) if isinstance(row, dict)]
    superseded = {
        collapsed_text(row.get("supersedes"))
        for row in rows
        if collapsed_text(row.get("supersedes"))
    }
    by_telling: dict[str, list[dict]] = {}
    for row in rows:
        if collapsed_text(row.get("status") or "active") != "active":
            continue
        identity_id = collapsed_text(row.get("identity_id"))
        if identity_id and identity_id in superseded:
            continue
        telling_ref = collapsed_text(row.get("telling_ref"))
        if not telling_ref:
            continue
        by_telling.setdefault(telling_ref, []).append(row)

    index: dict[str, tuple] = {}
    for telling_ref, found in sorted(by_telling.items()):
        found.sort(key=lambda row: collapsed_text(row.get("identity_id")))
        same_episodes = sorted({
            collapsed_text(row.get("episode_id"))
            for row in found
            if collapsed_text(row.get("relation")) == GROUPING_RELATION
            and collapsed_text(row.get("origin")) in GROUPING_ORIGINS
        })
        if len(same_episodes) > 1:
            raise TemporalContractError(
                REFUSAL_IDENTITY_CONFLICT,
                "one telling holds two active `same` bindings and neither "
                "supersedes the other; the fold will not pick the later one",
                detail={"telling_ref": telling_ref, "episode_ids": same_episodes},
            )
        seen_pairs: dict[tuple, str] = {}
        for row in found:
            pair = (telling_ref, collapsed_text(row.get("episode_id")))
            relation = collapsed_text(row.get("relation"))
            previous = seen_pairs.get(pair)
            if previous is not None and previous != relation:
                raise TemporalContractError(
                    REFUSAL_IDENTITY_CONFLICT,
                    "one (telling, episode) pair carries two active bindings "
                    "that disagree about the relation",
                    detail={"telling_ref": telling_ref, "episode_id": pair[1],
                            "relations": sorted([previous, relation])},
                )
            seen_pairs[pair] = relation
        index[telling_ref] = tuple(found)
    return index


def grouping_binding(telling_ref: object, active_bindings: object) -> dict | None:
    """The one binding that decides grouping for a telling, or ``None``.

    ``proposed`` is filtered here rather than at the call site so §2.3's
    *"only the first three affect grouping"* has exactly one implementation.
    """
    rows = (active_bindings or {}).get(collapsed_text(telling_ref)) or ()
    for row in rows:
        if collapsed_text(row.get("relation")) != GROUPING_RELATION:
            continue
        if collapsed_text(row.get("origin")) not in GROUPING_ORIGINS:
            continue
        return row
    return None


# --------------------------------------------------------------------------
# Era composition — the two cases, claim-precise
# --------------------------------------------------------------------------


def claim_event_ref_kind(claim: object) -> str:
    """``"era"`` · ``"episode"`` · ``"none"`` — what this claim's ref names.

    The prefix IS the evidence, and it is not a heuristic: an ``era:`` ref
    reaches a claim only through `event_binding`, which mints one when the
    person NAMED that stretch of life in this very utterance, and a ``node:``
    ref reaches it only through `identity_resolution.derive_episode_ref`.
    "This telling is about the College era" and "this episode happened within
    College" are therefore already distinguishable in the substrate: the first
    carries the era ref, the second carries no era ref at all and gains its
    era relationship as a MEMBERSHIP on its node, computed by frame arithmetic
    (`era_memberships`) after grouping.
    """
    ref = collapsed_text(
        claim.get("event_ref") if isinstance(claim, dict) else claim
    )
    if not ref:
        return "none"
    if ref.startswith(ERA_REF_PREFIX):
        return "era"
    if ref.startswith(NODE_REF_PREFIX):
        return "episode"
    return "none"


def telling_era_role(claims: object) -> str:
    """``"about_the_era"`` · ``"within_an_era"`` · ``"mixed"`` (§5.1, F-pin 1).

    ``"within_an_era"`` is the honest name for "carries no era ref", because
    that is all the substrate can see and all the rule needs: episode
    eligibility is the DEFAULT and an era ref is the one thing that removes
    it. Reading it the other way — requiring proof of membership before
    allowing a bind — is the F-pin's own failure case, *"never discard the
    latter's episode eligibility merely because another claim carried an era
    ref."*
    """
    kinds = {claim_event_ref_kind(claim) for claim in (claims or ())}
    if "era" in kinds and (kinds - {"era"}):
        return "mixed"
    if "era" in kinds:
        return "about_the_era"
    return "within_an_era"


# --------------------------------------------------------------------------
# Ids — the frozen minter, the published mapping, the aliases
# --------------------------------------------------------------------------


def episode_node_identity(*, canonical_event_kind: object, subject_keys: object,
                          episode_id: object) -> dict:
    """The exact digest input behind :func:`episode_node_id`, spelled out.

    Written the way `temporal_projection.age_frame_identity` is, and for the
    same reason: a test can pin the tuple, and a person debugging a collision
    can see WHY two episodes share an id without reading a digest.
    """
    refs = subject_keys
    if isinstance(refs, (str, bytes)):
        refs = [refs]
    return {
        "node_kind": EPISODE_NODE_KIND,
        "event_kind": collapsed_text(canonical_event_kind) or None,
        "subject_keys": sorted({
            tp.normalized_mention_key(ref)
            for ref in (refs or ())
            if collapsed_text(ref)
        }),
        "discriminator": collapsed_text(episode_id) or None,
    }


def episode_node_id(*, canonical_event_kind: object, subject_keys: object,
                    episode_id: object) -> str:
    """``node:<24 hex>`` for a bound episode — the FROZEN minter, unchanged.

    `temporal_projection.derive_node_id` with ``node_kind="episode"`` (already
    in `NODE_KINDS`), the episode's ``canonical_event_kind`` (decided at
    creation, §3.2, never inherited from whichever claim arrived first) and
    the ``episode_id`` as the discriminator — which is exactly what a
    discriminator is for: *"repeats that are genuinely different episodes."*
    `NODE_IDENTITY_KEYS` does not move, so no existing node id moves.
    """
    if not collapsed_text(episode_id):
        raise TemporalContractError(
            "episode_node_needs_episode_id",
            "an episode's node id is discriminated by its episode id; "
            "minting one without it would collide every episode of a kind",
        )
    return tp.derive_node_id(
        node_kind=EPISODE_NODE_KIND,
        event_kind=canonical_event_kind,
        subject_refs=subject_keys,
        discriminator=episode_id,
    )


def identity_mapping(episodes: object) -> dict:
    """The published ``episode_id ↔ node_id`` mapping (§3.5), both ways.

    Two identifiers, one durable mapping — never one identifier wearing two
    names. ``episode_id`` is what a human decision, an operation receipt and a
    binding all point at; ``node_id`` is what the drawing, an open session and
    a work item point at. The mapping is published so neither has to be
    re-derived by a reader that does not hold the episode's canonical kind.
    """
    node_by_episode: dict[str, str] = {}
    episode_by_node: dict[str, str] = {}
    for row in episodes or ():
        if not isinstance(row, dict):
            continue
        episode_id = collapsed_text(row.get("episode_id"))
        if not episode_id:
            continue
        node_id = episode_node_id(
            canonical_event_kind=row.get("canonical_event_kind"),
            subject_keys=row.get("subject_keys"),
            episode_id=episode_id,
        )
        node_by_episode[episode_id] = node_id
        episode_by_node[node_id] = episode_id
    return {
        "identity_rule_version": IDENTITY_RULE_VERSION,
        "episode_node_ids": dict(sorted(node_by_episode.items())),
        "node_episode_ids": dict(sorted(episode_by_node.items())),
    }


def node_aliases(groupings: object) -> dict:
    """``{former_node_id: episode_node_id}`` (§3.5, Law 5).

    Every key a bound telling's claims WOULD have grouped under is published
    here, so an open session, a Mirror row, a work item and an old URL all
    keep resolving after a bind. A telling that had no key of its own — the
    fold would have minted one from its own claims — contributes no row, and
    that absence is not a gap: there is no stored id to redirect.
    """
    table: dict[str, str] = {}
    for grouping in groupings or ():
        if not isinstance(grouping, GroupingKey):
            continue
        if grouping.kind != "episode":
            continue
        for former in grouping.aliased_from:
            if former and former != grouping.key:
                table[former] = grouping.key
    return dict(sorted(table.items()))


def episode_aliases(operations: object) -> dict:
    """``{absorbed_episode_id: surviving_episode_id}`` (§3.2, matrix row 8).

    Derived from the operation envelopes' own ``aliases_created`` — the merge
    receipt is the alias's source, so the table cannot drift from the act that
    created it. Chains are left as written; :func:`~episode_routing_contract.
    resolve_episode_alias` is what follows them.
    """
    table: dict[str, str] = {}
    for row in operations or ():
        if not isinstance(row, dict):
            continue
        if collapsed_text(row.get("status") or "active") != "active":
            continue
        survivor = collapsed_text(row.get("episode_id"))
        if not survivor:
            continue
        for absorbed in row.get("aliases_created") or ():
            key = collapsed_text(absorbed)
            if key and key != survivor:
                table[key] = survivor
    return dict(sorted(table.items()))


# --------------------------------------------------------------------------
# Grouping — the decision itself
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class GroupingKey:
    """What one claim groups under, and why.

    ``kind="episode"`` is the identity layer speaking. ``kind="existing"`` is
    the identity layer standing aside: the v264 fold's own key applies,
    unchanged, and ``key`` carries the claim's ``event_ref`` when it has one
    or ``""`` when the fold would mint the key from the claim itself. I0 does
    NOT reimplement `_mint_node_id`, because a second implementation of the
    key the whole substrate is identified by is exactly the class of defect
    this program exists to remove.
    """

    kind: str
    key: str
    reason: str
    telling_ref: str = ""
    episode_id: str = ""
    aliased_from: tuple = ()

    def as_dict(self) -> dict:
        return {
            "kind": self.kind,
            "key": self.key,
            "reason": self.reason,
            "telling_ref": self.telling_ref,
            "episode_id": self.episode_id,
            "aliased_from": list(self.aliased_from),
        }


#: Every ``reason`` :func:`grouping_key` can give. Closed, and pinned by test:
#: a fold whose reasons are open-ended cannot be audited.
GROUPING_REASONS = (
    "episode_binding",             # an active `same` binding grouped it
    "episode_binding_composes",    # …and the recorder's own ref already agreed
    "no_binding",                  # nothing bound this telling; v264's key
    "no_telling",                  # the manifest has no row for this claim
    "era_claim_not_groupable",     # the telling is about the era itself
    "proposal_not_applied",        # a `proposed` binding, deliberately inert
)


def grouping_key(claim: object, manifest: object, active_bindings: object) -> GroupingKey:
    """:data:`GROUPING_RULE_TEXT`, applied to one claim. Pure; no model.

    The episode binding WINS for grouping — that is the whole point of §3.5's
    separate fold input — but it wins over the *key*, never over the era
    layer: an era-bound claim is refused as a binding target here, whatever
    the binding says, and the binding itself is reported by
    :func:`fold_diagnostics` and refused at write time by C2.
    """
    claim_row = claim if isinstance(claim, dict) else {}
    event_ref = collapsed_text(claim_row.get("event_ref"))
    ref_kind = claim_event_ref_kind(claim_row)
    telling_ref = telling_ref_for_claim(claim_row, manifest)

    if ref_kind == "era":
        return GroupingKey(
            kind="existing", key=event_ref, reason="era_claim_not_groupable",
            telling_ref=telling_ref,
        )
    if not telling_ref:
        return GroupingKey(kind="existing", key=event_ref, reason="no_telling")

    binding = grouping_binding(telling_ref, active_bindings)
    if binding is None:
        rows = (active_bindings or {}).get(telling_ref) or ()
        proposed = any(
            collapsed_text(row.get("relation")) == GROUPING_RELATION
            and collapsed_text(row.get("origin")) == "proposed"
            for row in rows
        )
        return GroupingKey(
            kind="existing", key=event_ref,
            reason="proposal_not_applied" if proposed else "no_binding",
            telling_ref=telling_ref,
        )

    episode_id = collapsed_text(binding.get("episode_id"))
    node_id = episode_node_id(
        canonical_event_kind=binding.get("canonical_event_kind"),
        subject_keys=binding.get("subject_keys"),
        episode_id=episode_id,
    )
    composes = ref_kind == "episode" and event_ref == node_id
    return GroupingKey(
        kind="episode",
        key=node_id,
        reason="episode_binding_composes" if composes else "episode_binding",
        telling_ref=telling_ref,
        episode_id=episode_id,
        aliased_from=(event_ref,) if event_ref and event_ref != node_id else (),
    )


def fold_grouping(claims: object, manifest: object, bindings: object) -> dict:
    """``{grouping key: (claim_id, …)}`` over a whole receipt set.

    The fold's shape, small enough to permute. Claims with no key of their own
    and no binding land under ``""`` — v264's own minting, deliberately not
    duplicated here.
    """
    active = bindings if isinstance(bindings, dict) else active_binding_index(bindings)
    index = manifest_claim_index(manifest)
    grouped: dict[str, list[str]] = {}
    for claim in claims or ():
        decision = grouping_key(claim, index, active)
        claim_id = collapsed_text((claim or {}).get("claim_id"))
        grouped.setdefault(decision.key, []).append(claim_id)
    return {key: tuple(sorted(value)) for key, value in sorted(grouped.items())}


def grouping_fingerprint(grouping: object) -> str:
    """One digest over a whole grouping, so a permutation test compares one
    string instead of walking a nested structure and hoping it looked."""
    payload = {
        collapsed_text(key): sorted(collapsed_text(item) for item in (value or ()))
        for key, value in (grouping or {}).items()
    }
    return digest_id("grouping", {"groups": payload})


def fold_diagnostics(claims: object, manifest: object, bindings: object) -> tuple:
    """Everything §5.4 says to REPORT rather than raise, in a stable order.

    Dormant bindings, bindings found on era-bound claims, recorder refs the
    binding re-pointed, and proposals the fold deliberately did not apply. A
    diagnostic is not a failure — it is the fold saying out loud what it did
    with a record it could not simply obey.
    """
    active = bindings if isinstance(bindings, dict) else active_binding_index(bindings)
    index = manifest_claim_index(manifest)
    claims_by_telling: dict[str, list[dict]] = {}
    for claim in claims or ():
        telling_ref = collapsed_text(index.get(collapsed_text((claim or {}).get("claim_id"))))
        if telling_ref:
            claims_by_telling.setdefault(telling_ref, []).append(claim)

    findings: list[dict] = []
    for telling_ref, rows in sorted(active.items()):
        held = claims_by_telling.get(telling_ref) or ()
        for row in rows:
            episode_id = collapsed_text(row.get("episode_id"))
            relation = collapsed_text(row.get("relation"))
            origin = collapsed_text(row.get("origin"))
            if not held:
                findings.append({
                    "code": DIAGNOSTIC_DORMANT_BINDING, "telling_ref": telling_ref,
                    "episode_id": episode_id,
                    "detail": "the telling has no active claims; ignored, not an error",
                })
                continue
            if relation == GROUPING_RELATION and origin == "proposed":
                findings.append({
                    "code": DIAGNOSTIC_PROPOSAL_NOT_APPLIED, "telling_ref": telling_ref,
                    "episode_id": episode_id,
                    "detail": "a proposal ranks the queue; it changes no drawing",
                })
            if relation != GROUPING_RELATION:
                continue
            role = telling_era_role(held)
            if role == "mixed":
                raise TemporalContractError(
                    REFUSAL_TELLING_MIXES_IDENTITIES,
                    "a telling's claims disagree about whether they are about "
                    "an era or about an event; the fold will not bind half of it",
                    detail={"telling_ref": telling_ref},
                )
            if role == "about_the_era":
                findings.append({
                    "code": DIAGNOSTIC_BINDING_TO_ERA_CLAIM, "telling_ref": telling_ref,
                    "episode_id": episode_id,
                    "detail": "an era is not an episode; refused at write time",
                })
                continue
            for claim in held:
                decision = grouping_key(claim, index, active)
                for former in decision.aliased_from:
                    findings.append({
                        "code": DIAGNOSTIC_EPISODE_REF_ALIASED,
                        "telling_ref": telling_ref, "episode_id": episode_id,
                        "detail": former,
                    })
    findings.sort(key=lambda row: (row["code"], row["telling_ref"],
                                   row["episode_id"], str(row["detail"])))
    return tuple(findings)


# --------------------------------------------------------------------------
# Entailment — computed, never stored
# --------------------------------------------------------------------------


def entailed_not_same(bindings: object) -> tuple:
    """``same(A,E) ∧ not_same(B,E) ⇒ not_same(A,B)`` (§2.2), as sorted pairs.

    Computed at fold time from the active bindings and returned; NOTHING is
    written. Storing the closure is how a retracted binding leaves a permanent
    phantom negative behind — the entailed pair must disappear the moment
    either premise does, and the only way to guarantee that is to never have
    persisted it.
    """
    active = bindings if isinstance(bindings, dict) else active_binding_index(bindings)
    members: dict[str, set] = {}
    negatives: dict[str, set] = {}
    for telling_ref, rows in active.items():
        for row in rows:
            episode_id = collapsed_text(row.get("episode_id"))
            relation = collapsed_text(row.get("relation"))
            if not episode_id:
                continue
            if relation == GROUPING_RELATION and \
                    collapsed_text(row.get("origin")) in GROUPING_ORIGINS:
                members.setdefault(episode_id, set()).add(telling_ref)
            elif relation == "not_same":
                negatives.setdefault(episode_id, set()).add(telling_ref)
    pairs: set = set()
    for episode_id, inside in members.items():
        for outside in negatives.get(episode_id, ()):  # noqa: PLC0206
            for member in inside:
                if member != outside:
                    pairs.add(tuple(sorted((member, outside))))
    return tuple(sorted(pairs))


def is_not_same(telling_a: object, telling_b: object, bindings: object) -> bool:
    """Are these two tellings known to be different things — stated or entailed?

    The binder consults this before proposing anything (§4.2 condition 6) and
    the planner consults it before asking. One function, so "we already know
    the answer to that" cannot be true on one surface and false on another.
    """
    left, right = collapsed_text(telling_a), collapsed_text(telling_b)
    if not left or not right or left == right:
        return False
    return tuple(sorted((left, right))) in set(entailed_not_same(bindings))


# --------------------------------------------------------------------------
# Containment — the possible outer range (§5.3)
# --------------------------------------------------------------------------


def possible_outer_range(member_value: object, episode_span: object, *,
                         episode_id: object, episode_label: object = None
                         ) -> chrono.DateRecord | None:
    """:data:`CONTAINMENT_RULE_TEXT`, applied. Deterministic; no model call.

    Every clause of the rule is STRUCTURAL rather than checked afterwards,
    which is the discipline `temporal_timeline._colocation_record` established
    and the reason this function is written against the same type:

    * **never overrides** — the function reads ``member_value is None`` and
      nothing else, so there is no branch in which a stated value loses;
    * **never narrower** — the bounds returned are the episode's OWN bounds,
      copied, so there is no arithmetic that could shrink them;
    * **never an anchor** — ``anchors`` is ``()``, so cross-dating cannot
      later treat a containment as something the person said;
    * **never stored** — nothing here writes; the caller recomputes it from
      the receipts on every rebuild and it disappears the moment the member
      gains a value of its own;
    * **never suppresses the question** — see :func:`containment_probe`.

    The episode's own provenance is DROPPED: its sources dated the episode,
    not this member, and carrying them across would attribute to the person a
    sentence they never said about this thing.
    """
    if member_value is not None:
        return None
    record = episode_span if isinstance(episode_span, chrono.DateRecord) \
        else chrono.from_dict(episode_span)
    if record is None or record.best is None:
        return None
    label = collapsed_text(episode_label) or collapsed_text(episode_id)
    return chrono.DateRecord(
        best=record.best,
        earliest=record.earliest,
        latest=record.latest,
        granularity=record.granularity,
        confidence="inferred",
        basis=CONTAINMENT_DATE_BASIS,
        anchors=(),
        provenance=({
            "basis": chrono.INFERRED_PROVENANCE_BASIS,
            "rule": CONTAINMENT_RULE_ID,
            "claim": CONTAINMENT_CLAIM_SENTENCE.format(
                episode=label, span=chrono.display_date(record, with_basis=False),
            ).strip(),
            "source": f"containment:{collapsed_text(episode_id)}",
        },),
    )


def containment_probe(episode_label: object) -> str:
    """The precision question a contained member still gets (§5.3).

    Its existence is the promise: a containment is a BOUND, not an answer, and
    a rule that quietly retired the ▸ would have made the Timeline less
    answerable by knowing more — v264 learned that from co-location and this
    inherits it rather than rediscovering it.
    """
    return CONTAINMENT_PROBE_TEXT.format(episode=collapsed_text(episode_label))


__all__ = [
    "RULE_ID_QUESTION_CONTEXT",
    "RULE_ID_ENTITY_SPAN",
    "DETERMINISTIC_CONTAINMENT_RULE_TEXT",
    "DETERMINISTIC_CONTAINMENT_RULE_IDS",
    "DEFAULT_CONTAINMENT_AUTHORITY",
    "CONTAINMENT_ORIGIN_BY_AUTHORITY",
    "CONTAINMENT_AUTHORITY_RULE_TEXT",
    "CONTAINMENT_AUTHORITY_UPGRADE_RULE_TEXT",
    "CONTAINMENT_AUTHORITIES",
    "BINDING_FILING_OUTCOMES",
    "CONTAINMENT_CLAIM_SENTENCE",
    "CONTAINMENT_DATE_BASIS",
    "CONTAINMENT_PROBE_TEXT",
    "CONTAINMENT_RULE_ID",
    "CONTAINMENT_RULE_TEXT",
    "DIAGNOSTIC_BINDING_TO_ERA_CLAIM",
    "DIAGNOSTIC_DORMANT_BINDING",
    "DIAGNOSTIC_EPISODE_REF_ALIASED",
    "DIAGNOSTIC_PROPOSAL_NOT_APPLIED",
    "EPISODE_NODE_KIND",
    "ERA_REF_PREFIX",
    "FOLD_FINDINGS",
    "GROUPING_ORIGINS",
    "GROUPING_REASONS",
    "GROUPING_RELATION",
    "GROUPING_RULE_TEXT",
    "IDENTITY_RULE_VERSION",
    "MANIFEST_READ_FIELDS",
    "NODE_REF_PREFIX",
    "ORIGINS",
    "ORIGIN_UPGRADES",
    "REFUSAL_IDENTITY_CONFLICT",
    "REFUSAL_TELLING_MIXES_IDENTITIES",
    "RELATIONS",
    "GroupingKey",
    "active_binding_index",
    "claim_event_ref_kind",
    "containment_probe",
    "origin_move",
    "deterministic_relation_allowed",
    "containment_origin",
    "entailed_not_same",
    "episode_aliases",
    "episode_node_id",
    "episode_node_identity",
    "fold_diagnostics",
    "fold_grouping",
    "grouping_binding",
    "grouping_fingerprint",
    "grouping_key",
    "identity_mapping",
    "is_not_same",
    "manifest_claim_index",
    "node_aliases",
    "possible_outer_range",
    "telling_era_role",
    "telling_ref_for_claim",
]
