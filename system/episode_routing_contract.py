#!/usr/bin/env python3
"""I0-C4 — merge and split, per reference. Pure routing; nothing live moves.

Controlling design: lifehug-platform `docs/design/event-identity.md` (v4),
§5.5, §5.6 and the §5.8 lifecycle matrix rows 8, 9, 11 and 12. Contract doc:
`docs/contracts/event-identity-i0-fold.md`.

**Why this is a table and not a slogan.** v1 of the plan promised that a split
"restores the prior drawing byte-identically." The auditor's B1 finding is
that this is only true before downstream activity: once the person has
labelled the merged episode, dragged it into an era, answered a work item
about it or left a session open on it, a split has to decide where each of
those references GOES, and "restore the prior drawing" says nothing about any
of them. So the contract is a table with one rule per reference kind
(:data:`SPLIT_REFERENCE_RULES`), one test per row, and one rule that governs
the rows it does not cover: **no post-merge decision is ever copied to both
sides.** Anything whose target provenance is genuinely ambiguous becomes one
inspectable Mirror judgment row — a question with a person's name on it —
rather than a guess made twice.

**Why re-audit returns exactly one action.** §5.6, after audit G3, deletes
both the partition-equality promise and the "never an over-merge" claim. A
telling can satisfy R1 against E1 while E1 is the sole candidate, and a later
arrival can introduce an E2 that would also have survived. The plan does not
prove that divergence is refinement-only, so it does not claim it. What it
promises instead is that the divergence is SURFACED: :func:`reaudit` returns
``mint_possible_overmerge`` naming the existing bind and the new candidate
side by side, and it can return nothing else. Moving the bind, splitting it,
or re-confirming it are all decisions the system is not entitled to make on
its own, and :data:`FORBIDDEN_REAUDIT_ACTIONS` exists so a test can say so.

**Everything here is pure.** No I/O, no vault, no model, no clock. The
functions take the envelope and the references that hang off the episode and
return a plan; C2 owns writing the envelope, I1 owns applying the plan, and
I3 owns the Play flow that shows the Mirror row.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

SYSTEM_DIR = Path(__file__).resolve().parent
if str(SYSTEM_DIR) not in sys.path:
    sys.path.insert(0, str(SYSTEM_DIR))

import temporal_work_items as twi  # noqa: E402
from episode_fold_contract import (  # noqa: E402
    GROUPING_RELATION,
    IDENTITY_RULE_VERSION,
    active_binding_index,
)
from temporal_claims import (  # noqa: E402
    TemporalContractError,
    collapsed_text,
    digest_id,
)

# --------------------------------------------------------------------------
# §5.5 — the per-reference rules table
# --------------------------------------------------------------------------

#: Where a departing telling goes. ``standalone`` means back to its own node
#: with nothing attached; a ``episode:`` id means a new episode created in the
#: SAME envelope (§3.2), which is why a destination is never a dangling id.
SPLIT_DESTINATION_STANDALONE = "standalone"

#: The reference kinds §5.5 enumerates, plus the catch-all the rule's own last
#: clause requires. A kind absent from this tuple is routed by
#: :data:`UNKNOWN_REFERENCE_RULE` — to a Mirror judgment — rather than
#: silently dropped, because a reference nobody thought about is exactly the
#: thing that must not be resolved by a default.
SPLIT_REFERENCE_KINDS = (
    "ordering_constraint",
    "era_membership",
    "display_decision",
    "episode_label",
    "work_item",
    "open_session",
    "other_decision",
)

#: The table, as data. Each row is one sentence of §5.5 with the reason it
#: says that, so a reader can check the code against the design without
#: holding both in their head. ``routes_to`` is the routing function's own
#: vocabulary: ``anchor_side`` · ``survivor`` · ``departing`` · ``alias`` ·
#: ``mirror_judgment``.
SPLIT_REFERENCE_RULES = (
    {
        "reference_kind": "ordering_constraint",
        "routes_to": "anchor_side",
        "rule": "an ordering constraint re-attaches to whichever side carries "
                "the anchor claim it was stated against",
        "because": "the constraint is a fact about that claim's position, and "
                   "the claim went to exactly one side",
        "design": "§5.5",
    },
    {
        "reference_kind": "era_membership",
        "routes_to": "survivor",
        "rule": "era memberships stay with the surviving episode id; the "
                "departing telling reverts to its own node with none",
        "because": "a membership is a receipt about an episode's identity, and "
                   "the survivor keeps that identity (Law 5)",
        "design": "§5.5",
    },
    {
        "reference_kind": "display_decision",
        "routes_to": "survivor",
        "rule": "the display role the person picked stays with the surviving "
                "episode id",
        "because": "the person picked it for that episode, not for a telling",
        "design": "§5.5",
    },
    {
        "reference_kind": "episode_label",
        "routes_to": "survivor",
        "rule": "the label stays with the episode id",
        "because": "§3.4 — the label is a decision record about the identity, "
                   "and identity never moves",
        "design": "§5.5, §3.4",
    },
    {
        "reference_kind": "work_item",
        "routes_to": "alias",
        "rule": "work items re-key through work_item_aliases",
        "because": "an item answered on any surface must still close the same "
                   "item everywhere (O-E6's one id)",
        "design": "§5.5, matrix row 12",
    },
    {
        "reference_kind": "open_session",
        "routes_to": "alias",
        "rule": "open sessions keep their target through node_aliases",
        "because": "a session the person is inside must not lose its subject "
                   "because the substrate reorganised underneath it",
        "design": "§5.5, matrix row 12",
    },
    {
        "reference_kind": "other_decision",
        "routes_to": "mirror_judgment",
        "rule": "any decision whose target provenance is genuinely ambiguous "
                "becomes one inspectable Mirror judgment row",
        "because": "copying it to both sides would invent a decision the "
                   "person never made, twice",
        "design": "§5.5",
    },
)

#: The rule for a reference kind the table does not name.
UNKNOWN_REFERENCE_RULE = "mirror_judgment"

#: A merge that leaves a membership live, or forgets the absorbed id's alias.
REFUSAL_MERGE_INCOMPLETE = "merge_envelope_incomplete"

#: The finding a Mirror judgment row carries, so Mirror can allow-list it and
#: a host can count them.
MIRROR_JUDGMENT_KIND = "identity_split_unattributable"

#: §5.5's governing clause, verbatim, for `COLOCATION_RULE_TEXT`'s reason.
SPLIT_RULE_TEXT = (
    "A split routes every reference the episode carries to exactly ONE "
    "destination. Ordering constraints re-attach to the side carrying the "
    "anchor claim; era memberships, display decisions and the label stay with "
    "the surviving episode id and the departing telling reverts to its own "
    "node with none; work items re-key through work_item_aliases and open "
    "sessions through node_aliases. NO post-merge decision is ever copied to "
    "both sides: anything whose target provenance is genuinely ambiguous "
    "becomes one inspectable Mirror judgment row instead of a guess."
)


@dataclass(frozen=True)
class ReferenceRoute:
    """One reference, one destination, one reason. Never two destinations."""

    reference_kind: str
    reference_id: str
    destination: str
    rule: str
    detail: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {
            "reference_kind": self.reference_kind,
            "reference_id": self.reference_id,
            "destination": self.destination,
            "rule": self.rule,
            "detail": dict(self.detail),
        }


@dataclass(frozen=True)
class RoutingPlan:
    """What an operation does to everything that pointed at the episode."""

    routes: tuple = ()
    mirror_judgments: tuple = ()
    node_aliases: dict = field(default_factory=dict)
    episode_aliases: dict = field(default_factory=dict)
    work_item_aliases: dict = field(default_factory=dict)
    superseded_binding_ids: tuple = ()

    def as_dict(self) -> dict:
        return {
            "routes": [route.as_dict() for route in self.routes],
            "mirror_judgments": [dict(row) for row in self.mirror_judgments],
            "node_aliases": dict(self.node_aliases),
            "episode_aliases": dict(self.episode_aliases),
            "work_item_aliases": dict(self.work_item_aliases),
            "superseded_binding_ids": list(self.superseded_binding_ids),
        }

    def destinations_for(self, reference_id: object) -> tuple:
        """Every destination one reference reached. The table's own guard:
        this is length 1 for every reference in a well-formed plan, and the
        test that asserts so is what proves "never copied to both sides."
        """
        wanted = collapsed_text(reference_id)
        return tuple(
            route.destination for route in self.routes
            if route.reference_id == wanted
        ) + tuple(
            row["destination"] for row in self.mirror_judgments
            if row.get("reference_id") == wanted
        )


def _rule_for(reference_kind: str) -> dict:
    for row in SPLIT_REFERENCE_RULES:
        if row["reference_kind"] == reference_kind:
            return row
    return {
        "reference_kind": reference_kind, "routes_to": UNKNOWN_REFERENCE_RULE,
        "rule": "a reference kind the table does not name is never routed by "
                "default; it becomes one Mirror judgment",
        "because": "an unenumerated reference is exactly the thing a default "
                   "must not decide",
        "design": "§5.5",
    }


def _mirror_row(*, reference_kind: str, reference_id: str, reason: str,
                candidates: object) -> dict:
    return {
        "kind": MIRROR_JUDGMENT_KIND,
        "reference_kind": reference_kind,
        "reference_id": reference_id,
        "destination": "mirror_judgment",
        "reason": reason,
        "candidates": sorted({collapsed_text(item) for item in (candidates or ())
                              if collapsed_text(item)}),
        "identity_rule_version": IDENTITY_RULE_VERSION,
    }


def split_routing(*, envelope: object, references: object,
                  telling_node_ids: object = None) -> RoutingPlan:
    """:data:`SPLIT_RULE_TEXT`, applied. Pure; one destination per reference.

    ``envelope`` is the ``split`` operation (§3.2): ``episode_id`` is the
    SURVIVOR, ``destinations`` maps each departing ``telling_ref`` to
    ``standalone`` or a ``new_episode_id`` created in the same envelope, and
    ``supersedes_binding_ids`` names the bindings it retires.

    ``references`` is everything currently pointing at the episode, each row
    ``{"reference_kind", "reference_id", …}``. An ordering constraint carries
    ``anchor_telling_ref`` — the telling whose claim it was stated against —
    and that field is what decides its side. A constraint with no anchor, or
    one whose anchor is not a party to the split, is unattributable and
    becomes a Mirror judgment; it is NOT sent to both sides and it is NOT
    silently kept by the survivor.
    """
    row = envelope if isinstance(envelope, dict) else {}
    if collapsed_text(row.get("op")) not in ("split", ""):
        raise TemporalContractError(
            "split_routing_wrong_op",
            "split_routing routes a `split` envelope; merge_routing routes a merge",
            detail={"op": collapsed_text(row.get("op"))},
        )
    survivor = collapsed_text(row.get("episode_id"))
    if not survivor:
        raise TemporalContractError(
            "split_needs_surviving_episode",
            "a split keeps the episode id with its remaining members (Law 5)",
        )
    destinations = row.get("destinations")
    if not isinstance(destinations, dict) or not destinations:
        raise TemporalContractError(
            "split_needs_destinations",
            "a split names each departing telling and where it goes; a split "
            "envelope with no destinations is incomplete (G4)",
            detail={"episode_id": survivor},
        )
    departing = {
        collapsed_text(telling): collapsed_text(target) or SPLIT_DESTINATION_STANDALONE
        for telling, target in destinations.items()
        if collapsed_text(telling)
    }
    node_ids = {
        collapsed_text(key): collapsed_text(value)
        for key, value in (telling_node_ids or {}).items()
        if collapsed_text(key)
    }

    routes: list[ReferenceRoute] = []
    judgments: list[dict] = []
    node_alias_rows: dict[str, str] = {}
    work_item_alias_rows: dict[str, str] = {}

    for reference in references or ():
        if not isinstance(reference, dict):
            continue
        kind = collapsed_text(reference.get("reference_kind"))
        reference_id = collapsed_text(reference.get("reference_id"))
        rule = _rule_for(kind)
        routes_to = rule["routes_to"]

        if routes_to == "anchor_side":
            anchor = collapsed_text(reference.get("anchor_telling_ref"))
            if anchor and anchor in departing:
                target = departing[anchor]
                routes.append(ReferenceRoute(
                    reference_kind=kind, reference_id=reference_id,
                    destination=target, rule=rule["rule"],
                    detail={"anchor_telling_ref": anchor},
                ))
            elif anchor:
                routes.append(ReferenceRoute(
                    reference_kind=kind, reference_id=reference_id,
                    destination=survivor, rule=rule["rule"],
                    detail={"anchor_telling_ref": anchor},
                ))
            else:
                judgments.append(_mirror_row(
                    reference_kind=kind, reference_id=reference_id,
                    reason="the constraint names no anchor claim, so which "
                           "side it belongs to is a person's judgment",
                    candidates=[survivor, *sorted(set(departing.values()))],
                ))
            continue

        if routes_to == "survivor":
            routes.append(ReferenceRoute(
                reference_kind=kind, reference_id=reference_id,
                destination=survivor, rule=rule["rule"],
            ))
            continue

        if routes_to == "alias":
            if kind == "work_item":
                new_id = collapsed_text(reference.get("rekeyed_to"))
                if new_id and new_id != reference_id:
                    work_item_alias_rows[reference_id] = new_id
                routes.append(ReferenceRoute(
                    reference_kind=kind, reference_id=reference_id,
                    destination=new_id or reference_id, rule=rule["rule"],
                    detail={"via": "work_item_aliases"},
                ))
            else:
                telling = collapsed_text(reference.get("telling_ref"))
                target = departing.get(telling, survivor)
                former = collapsed_text(reference.get("node_id"))
                new_node = node_ids.get(telling) if target == SPLIT_DESTINATION_STANDALONE \
                    else node_ids.get(target, "")
                if former and new_node and former != new_node:
                    node_alias_rows[former] = new_node
                routes.append(ReferenceRoute(
                    reference_kind=kind, reference_id=reference_id,
                    destination=new_node or former or survivor, rule=rule["rule"],
                    detail={"via": "node_aliases"},
                ))
            continue

        judgments.append(_mirror_row(
            reference_kind=kind, reference_id=reference_id,
            reason=rule["rule"],
            candidates=[survivor, *sorted(set(departing.values()))],
        ))

    return RoutingPlan(
        routes=tuple(routes),
        mirror_judgments=tuple(judgments),
        node_aliases=dict(sorted(node_alias_rows.items())),
        work_item_aliases=dict(sorted(work_item_alias_rows.items())),
        superseded_binding_ids=tuple(sorted(
            collapsed_text(item) for item in (row.get("supersedes_binding_ids") or ())
            if collapsed_text(item)
        )),
    )


def merge_routing(*, envelope: object, references: object,
                  bindings: object = ()) -> RoutingPlan:
    """Matrix row 8: one receipt moves every member, the absorbed id aliases.

    A merge is always human authority in v1 (§4.2 condition 7 refuses to join
    two episodes deterministically), so this function's job is not to decide
    anything — it is to prove the envelope moved EVERYTHING. Every active
    ``same`` binding on the absorbed episode must appear in
    ``supersedes_binding_ids``; one left behind is
    :data:`REFUSAL_MERGE_INCOMPLETE`, because a member that keeps a live
    binding to an id that no longer draws is exactly the half-applied episode
    G4 forbids.
    """
    row = envelope if isinstance(envelope, dict) else {}
    survivor = collapsed_text(row.get("episode_id"))
    absorbed = collapsed_text(row.get("absorbed_episode_id"))
    if not survivor or not absorbed:
        raise TemporalContractError(
            "merge_needs_two_episodes",
            "a merge names the survivor and the episode it absorbs",
            detail={"episode_id": survivor, "absorbed_episode_id": absorbed},
        )
    aliases_created = {
        collapsed_text(item) for item in (row.get("aliases_created") or ())
        if collapsed_text(item)
    }
    if absorbed not in aliases_created:
        raise TemporalContractError(
            REFUSAL_MERGE_INCOMPLETE,
            "the absorbed episode id must be recorded as an alias forever; "
            "an id that stops resolving orphans every URL that held it",
            detail={"absorbed_episode_id": absorbed},
        )
    superseded = {
        collapsed_text(item) for item in (row.get("supersedes_binding_ids") or ())
        if collapsed_text(item)
    }
    active = bindings if isinstance(bindings, dict) else active_binding_index(bindings)
    missed = sorted({
        collapsed_text(binding.get("identity_id"))
        for rows in active.values() for binding in rows
        if collapsed_text(binding.get("episode_id")) == absorbed
        and collapsed_text(binding.get("relation")) == GROUPING_RELATION
        and collapsed_text(binding.get("identity_id")) not in superseded
    } - {""})
    if missed:
        raise TemporalContractError(
            REFUSAL_MERGE_INCOMPLETE,
            "a merge supersedes every membership of the absorbed episode in "
            "one receipt; these were left live",
            detail={"absorbed_episode_id": absorbed, "binding_ids": missed},
        )

    routes: list[ReferenceRoute] = []
    work_item_alias_rows: dict[str, str] = {}
    node_alias_rows: dict[str, str] = {}
    for reference in references or ():
        if not isinstance(reference, dict):
            continue
        kind = collapsed_text(reference.get("reference_kind"))
        reference_id = collapsed_text(reference.get("reference_id"))
        rule = _rule_for(kind)
        if kind == "work_item":
            new_id = collapsed_text(reference.get("rekeyed_to"))
            if new_id and new_id != reference_id:
                work_item_alias_rows[reference_id] = new_id
            routes.append(ReferenceRoute(
                reference_kind=kind, reference_id=reference_id,
                destination=new_id or reference_id, rule=rule["rule"],
                detail={"via": "work_item_aliases"},
            ))
            continue
        if kind == "open_session":
            former = collapsed_text(reference.get("node_id"))
            new_node = collapsed_text(reference.get("survivor_node_id"))
            if former and new_node and former != new_node:
                node_alias_rows[former] = new_node
            routes.append(ReferenceRoute(
                reference_kind=kind, reference_id=reference_id,
                destination=new_node or former, rule=rule["rule"],
                detail={"via": "node_aliases"},
            ))
            continue
        routes.append(ReferenceRoute(
            reference_kind=kind, reference_id=reference_id,
            destination=survivor, rule="a merge unions; every reference the "
                                       "absorbed episode carried points at the survivor",
            detail={"absorbed_episode_id": absorbed},
        ))

    return RoutingPlan(
        routes=tuple(routes),
        mirror_judgments=(),
        node_aliases=dict(sorted(node_alias_rows.items())),
        episode_aliases={absorbed: survivor},
        work_item_aliases=dict(sorted(work_item_alias_rows.items())),
        superseded_binding_ids=tuple(sorted(superseded - {""})),
    )


# --------------------------------------------------------------------------
# Alias resolution (matrix row 12) — pure, chained, cycle-safe
# --------------------------------------------------------------------------


def resolve_episode_alias(episode_id: object, aliases: object = None) -> str:
    """An absorbed episode id → the survivor. Purely.

    Written the way `temporal_work_items.resolve_work_item_id` is, and
    deliberately so: an id that is already canonical, or that no map knows,
    comes back UNCHANGED — resolution never invents an identity — chains are
    followed (A absorbed into B, B into C, an old URL holding A lands on C),
    and cycles terminate, because a published map is data and data can be
    wrong.
    """
    wanted = collapsed_text(episode_id)
    if not wanted:
        return ""
    table = aliases if isinstance(aliases, dict) else {}
    seen: set = set()
    while wanted in table and wanted not in seen:
        seen.add(wanted)
        nxt = collapsed_text(table[wanted])
        if not nxt:
            break
        wanted = nxt
    return wanted


#: §6.1: the work item's ``event_key`` serialises the PAIR, so a negative is
#: persisted per (telling, candidate episode) and "never ask this pair again"
#: is literal rather than approximate.
PAIR_KEY_SEPARATOR = "|"


def pair_event_key(telling_ref: object, candidate_episode_id: object) -> str:
    """``"{a}|{b}"`` with the components SORTED (§6.1).

    Sorted rather than positional so the key cannot depend on which side the
    caller happened to name first — the same reason
    `identity_resolution.derive_episode_ref` order-normalises a relationship
    edge.
    """
    parts = sorted(
        part for part in (collapsed_text(telling_ref),
                          collapsed_text(candidate_episode_id)) if part
    )
    if len(parts) != 2:
        raise TemporalContractError(
            "pair_key_needs_both_sides",
            "a pair work item is identified by a telling AND a candidate "
            "episode; one of them alone is the identity F3 rejected",
        )
    return PAIR_KEY_SEPARATOR.join(parts)


def resolve_pair(telling_ref: object, candidate_episode_id: object, *,
                 episode_aliases: object = None,
                 work_item_aliases: object = None) -> dict:
    """The pair an old reference means today (matrix row 12).

    Both halves resolve: the episode through :func:`resolve_episode_alias`,
    the item id through `temporal_work_items.resolve_work_item_id` — the ONE
    lookup, not a second table that agrees with it most of the time.
    """
    episode_id = resolve_episode_alias(candidate_episode_id, episode_aliases)
    key = pair_event_key(telling_ref, episode_id)
    return {
        "telling_ref": collapsed_text(telling_ref),
        "candidate_episode_id": episode_id,
        "event_key": key,
        "work_item_id": twi.resolve_work_item_id(key, aliases=work_item_aliases or {}),
    }


#: What :func:`route_delayed_pair_answer` can decide. Three outcomes and no
#: fourth: a delayed answer is filed as given, filed against the re-keyed
#: pair, or acknowledged and dropped with a note. It is never MISFILED, which
#: is the whole content of matrix row 12's last clause.
DELAYED_ANSWER_OUTCOMES = ("filed", "filed_rekeyed", "acknowledged_and_dropped")


def route_delayed_pair_answer(*, telling_ref: object, candidate_episode_id: object,
                              episode_aliases: object = None,
                              work_item_aliases: object = None,
                              retired_tellings: object = ()) -> dict:
    """An answer that arrives after its episode merged or its telling re-keyed.

    Three outcomes, and the third is the one the matrix exists to pin: a pair
    whose TELLING re-keyed away is **acknowledged and dropped with a note**,
    never re-pointed at whatever telling now occupies that source. §3.1 case 3
    is explicit that bindings never transfer automatically on a re-key, and an
    answer is a binding — filing it against a successor telling would be the
    silent merge the whole program is built to refuse.
    """
    telling = collapsed_text(telling_ref)
    retired = {collapsed_text(item) for item in (retired_tellings or ())
               if collapsed_text(item)}
    if telling in retired:
        return {
            "outcome": "acknowledged_and_dropped",
            "telling_ref": telling,
            "candidate_episode_id": resolve_episode_alias(candidate_episode_id,
                                                          episode_aliases),
            "note": "the telling this answer was about has been re-keyed; the "
                    "answer is acknowledged and filed nowhere, because a "
                    "binding never transfers to a successor telling on its own",
        }
    resolved = resolve_pair(
        telling, candidate_episode_id,
        episode_aliases=episode_aliases, work_item_aliases=work_item_aliases,
    )
    moved = resolved["candidate_episode_id"] != collapsed_text(candidate_episode_id)
    resolved["outcome"] = "filed_rekeyed" if moved else "filed"
    return resolved


# --------------------------------------------------------------------------
# §5.6 — the re-audit, and the one thing it may return
# --------------------------------------------------------------------------

#: Every trigger §5.6 enumerates. Exhaustive by contract: a trigger absent
#: here is a bind that can drift without anybody being asked, which is
#: precisely the G3 failure. The weekly sweep is deliberately last — it is the
#: catch-all, not the mechanism.
REAUDIT_TRIGGERS = (
    "new_telling",
    "new_date_evidence",
    "new_place_evidence",
    "new_participant_evidence",
    "entity_resolution_change",
    "telling_rekey",
    "rule_version_change",
    "episode_merge",
    "maintenance_sweep",
)

#: The ONLY action a re-audit may take.
REAUDIT_MINT = "mint_possible_overmerge"

#: …and nothing.
REAUDIT_NO_ACTION = "no_action"

#: Named so a test can assert none of them is reachable. Each one is a
#: decision the system would be making on the person's behalf about which of
#: two readings of their life is right, on evidence that by construction
#: supports both.
FORBIDDEN_REAUDIT_ACTIONS = ("move", "split", "keep", "confirm", "rebind", "drop")

#: The work-item kind the re-audit mints (§6.3), Mirror-allowlisted with Play.
POSSIBLE_OVERMERGE_KIND = "possible_overmerge"

#: §5.6, verbatim.
REAUDIT_RULE_TEXT = (
    "When a new plausible candidate appears for a telling that is already "
    "deterministically bound, the bind is never silently moved, split or "
    "kept: one possible_overmerge item is minted showing the existing bind "
    "and the new candidate side by side. Every trigger re-runs this audit — a "
    "new telling in retrieval range, new date, place or participant evidence "
    "on either side, an entity-resolution change, a telling re-key, a "
    "rule-version change, an episode merge, and the weekly maintenance sweep "
    "as the catch-all. Re-triggering dedupes on the pair."
)


def possible_overmerge_id(*, telling_ref: object, bound_episode_id: object,
                          candidate_episode_id: object) -> str:
    """The item's identity, keyed on the PAIR OF PAIRS, so re-triggering dedupes.

    Deliberately NOT keyed on the trigger: seven triggers noticing the same
    ambiguity are one question, and minting seven of them would turn the
    honest contract ("ambiguity is surfaced") into a queue nobody can read.
    """
    return digest_id(POSSIBLE_OVERMERGE_KIND, {
        "telling_ref": collapsed_text(telling_ref),
        "episode_ids": sorted({collapsed_text(bound_episode_id),
                               collapsed_text(candidate_episode_id)} - {""}),
        "rule_version": IDENTITY_RULE_VERSION,
    })


def reaudit(*, trigger: object, telling_ref: object, bound_episode_id: object,
            candidate_episode_id: object, bindings: object = (),
            answered_pairs: object = (), open_items: object = ()) -> dict:
    """:data:`REAUDIT_RULE_TEXT`, applied. Returns one action or none.

    Three reasons to return :data:`REAUDIT_NO_ACTION`, and all three are
    promises rather than optimisations: the candidate IS the bound episode
    (nothing is ambiguous); the pair already carries an active ``not_same``
    or an answered record (§13.4 — *a pair answered Different is never
    proposed or asked again*); or the item already exists (the dedupe).

    Everything else mints. It never moves, splits, keeps or re-confirms the
    bind — see :data:`FORBIDDEN_REAUDIT_ACTIONS`.
    """
    name = collapsed_text(trigger)
    if name not in REAUDIT_TRIGGERS:
        raise TemporalContractError(
            "reaudit_unknown_trigger",
            "the re-audit's triggers are enumerated so none can be forgotten; "
            "this one is not among them",
            detail={"trigger": name, "known": list(REAUDIT_TRIGGERS)},
        )
    telling = collapsed_text(telling_ref)
    bound = collapsed_text(bound_episode_id)
    candidate = collapsed_text(candidate_episode_id)
    if not telling or not bound or not candidate:
        raise TemporalContractError(
            "reaudit_needs_a_pair",
            "a re-audit compares an existing bind with a new candidate; both "
            "sides and the telling are required",
        )
    item_id = possible_overmerge_id(
        telling_ref=telling, bound_episode_id=bound, candidate_episode_id=candidate,
    )
    if candidate == bound:
        return {"action": REAUDIT_NO_ACTION, "trigger": name,
                "reason": "the candidate is the episode the telling is already bound to"}

    answered = {
        pair_event_key(row.get("telling_ref"), row.get("candidate_episode_id"))
        for row in (answered_pairs or ()) if isinstance(row, dict)
    }
    pair_key = pair_event_key(telling, candidate)
    if pair_key in answered:
        return {"action": REAUDIT_NO_ACTION, "trigger": name, "pair": pair_key,
                "reason": "this pair has been answered; an answered pair is "
                          "never proposed or asked again"}

    active = bindings if isinstance(bindings, dict) else active_binding_index(bindings)
    for row in (active.get(telling) or ()):
        if collapsed_text(row.get("episode_id")) == candidate and \
                collapsed_text(row.get("relation")) == "not_same":
            return {"action": REAUDIT_NO_ACTION, "trigger": name, "pair": pair_key,
                    "reason": "the person already said these are different things"}

    if item_id in {collapsed_text(item) for item in (open_items or ())}:
        return {"action": REAUDIT_NO_ACTION, "trigger": name, "pair": pair_key,
                "item_id": item_id,
                "reason": "the same ambiguity is already open; re-triggering "
                          "dedupes on the pair"}

    return {
        "action": REAUDIT_MINT,
        "trigger": name,
        "kind": POSSIBLE_OVERMERGE_KIND,
        "item_id": item_id,
        "pair": pair_key,
        "telling_ref": telling,
        "existing_bind": bound,
        "new_candidate": candidate,
        "identity_rule_version": IDENTITY_RULE_VERSION,
        "reason": "a new plausible candidate appeared for a telling that is "
                  "already bound; the bind is untouched and both readings are "
                  "shown side by side",
    }


# --------------------------------------------------------------------------
# "Not sure" — an epistemic state on the PAIR, never a relation (I3, §2.2)
# --------------------------------------------------------------------------

#: §12 ruling 3, approved verbatim. Material new evidence reopens sooner —
#: :func:`cooldown_active` is what makes "sooner" mechanical rather than a
#: promise nobody checks.
DEFERRAL_COOLDOWN_DAYS = 90


def _parse_instant(value: object) -> datetime:
    text = collapsed_text(value)
    if not text:
        raise TemporalContractError(
            "deferral_needs_an_instant", "a deferral is timestamped or it cannot cool down"
        )
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(text)
    except ValueError as exc:
        raise TemporalContractError(
            "deferral_instant_unusable", f"not a usable timestamp: {value!r}"
        ) from exc


def defer_pair(*, telling_ref: object, candidate_episode_id: object,
                evidence_signature: object = None, now: object) -> dict:
    """One "Not sure" deferral — asserts nothing about the world (§2.2).

    Lives beside the pair key so it re-keys and dedupes exactly like every
    other pair record. ``evidence_signature`` is the caller's snapshot of
    whatever would make the pair's evidence MATERIALLY different next time —
    each side's own dated value is what §13.4 means by "a new date on either
    side" — so :func:`cooldown_active` can tell "the same unresolved pair"
    from "something changed" without re-deriving anything itself.
    """
    telling = collapsed_text(telling_ref)
    candidate = collapsed_text(candidate_episode_id)
    if not telling or not candidate:
        raise TemporalContractError(
            "deferral_needs_a_pair", "a deferral names the pair it defers"
        )
    moment = _parse_instant(now)
    return {
        "event_key": pair_event_key(telling, candidate),
        "telling_ref": telling,
        "candidate_episode_id": candidate,
        "deferred_at": collapsed_text(now),
        "defer_until": (moment + timedelta(days=DEFERRAL_COOLDOWN_DAYS)).isoformat().replace(
            "+00:00", "Z"
        ),
        "evidence_signature": (
            dict(evidence_signature) if isinstance(evidence_signature, dict) else {}
        ),
    }


def material_new_evidence(old_signature: object, new_signature: object) -> bool:
    """Did either side of the pair pick up a date it did not have before?

    §13.4: *"reopens early on material new evidence — a new date on either
    side."* Absence is not evidence of absence: an empty prior signature
    (the caller had nothing to snapshot) never counts as a change, and
    neither does an unchanged one — only a genuine disagreement between the
    two dictionaries does.
    """
    old = old_signature if isinstance(old_signature, dict) else {}
    new = new_signature if isinstance(new_signature, dict) else {}
    if not old or not new:
        return False
    return old != new


def cooldown_active(deferral: object, *, evidence_signature: object = None, now: object) -> bool:
    """Is a "Not sure" pair still on ice?

    False the moment either half of the promise stops holding: the 90 days
    elapsed, or the evidence the deferral was taken against has materially
    changed. A malformed or dateless deferral is never treated as active —
    the cooldown is a courtesy to the person, not a lock the substrate can
    use to justify never asking again.
    """
    row = deferral if isinstance(deferral, dict) else {}
    until = collapsed_text(row.get("defer_until"))
    if not until:
        return False
    if material_new_evidence(row.get("evidence_signature"), evidence_signature):
        return False
    try:
        return _parse_instant(now) < _parse_instant(until)
    except TemporalContractError:
        return False


__all__ = [
    "DEFERRAL_COOLDOWN_DAYS",
    "DELAYED_ANSWER_OUTCOMES",
    "FORBIDDEN_REAUDIT_ACTIONS",
    "MIRROR_JUDGMENT_KIND",
    "PAIR_KEY_SEPARATOR",
    "POSSIBLE_OVERMERGE_KIND",
    "REAUDIT_MINT",
    "REAUDIT_NO_ACTION",
    "REAUDIT_RULE_TEXT",
    "REAUDIT_TRIGGERS",
    "REFUSAL_MERGE_INCOMPLETE",
    "SPLIT_DESTINATION_STANDALONE",
    "SPLIT_REFERENCE_KINDS",
    "SPLIT_REFERENCE_RULES",
    "SPLIT_RULE_TEXT",
    "UNKNOWN_REFERENCE_RULE",
    "ReferenceRoute",
    "RoutingPlan",
    "cooldown_active",
    "defer_pair",
    "material_new_evidence",
    "merge_routing",
    "pair_event_key",
    "possible_overmerge_id",
    "reaudit",
    "resolve_episode_alias",
    "resolve_pair",
    "route_delayed_pair_answer",
    "split_routing",
]
