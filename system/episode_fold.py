#!/usr/bin/env python3
"""I1 — the fold applies bindings. The identity layer, wired.

Controlling design: lifehug-platform `docs/design/event-identity.md` (v4),
§3.5, §5.1–§5.4, §5.6 and §5.8 rows 1–3 and 10. The pure decisions this
module APPLIES were settled in phase I0 and live in
`system/episode_fold_contract.py` (C3) and `system/event_identity.py`
(C1/C2); nothing here re-implements one of them, and that is deliberate — a
second implementation of the key the whole substrate is identified by is
exactly the class of defect this program exists to remove.

**What I1 adds and what it deliberately does not.** It adds one fold input,
``episode_records``, and everything that follows from reading it: grouping
through active ``same`` bindings, the additive node and envelope fields §3.5
enumerates, the containment edge's possible outer range, the entailment
``same(A,E) ∧ not_same(B,E) ⇒ not_same(A,B)`` computed at fold time, and the
refusals §5.4 requires. It adds **no binder** — nothing here decides that two
tellings are one thing. Records arrive already made (I2 makes them; until
then, by hand), the fold only applies them, and `compile` stays zero-model.

**Three shapes, one input.** ``episode_records`` is a mapping of
``operations`` (the §3.2 envelopes), ``bindings`` (the §3.3 records) and an
optional ``manifest`` (C1's telling manifest). A bare sequence is read as the
bindings alone, because a fixture that only wants to prove grouping should
not have to mint an envelope to do it. When the manifest is absent, the
claim→telling map is derived from the claims' own source ids through C1's
`event_identity.telling_ref_for_claim` — the same function the manifest
itself is built from, so the two can never disagree about which moment is
which.

**The episode's node id, and the one place the design could not be honored
as written.** §3.5 mints it as ``derive_node_id(node_kind="episode",
canonical_event_kind, subject_keys, discriminator=episode_id)``. The frozen
minter, the unchanged keys and the episode id as the discriminator are all
exactly that. ``subject_keys`` is :data:`EPISODE_SUBJECT_KEYS` — EMPTY — and
the reason is Law 5, *"ids persist"*: the episode id is already a complete
discriminator, so any content-derived component would add nothing to
uniqueness while moving the node id every time a member joined, a subject
resolved, or a claim was retracted. An episode whose node id churns takes an
open session, a Mirror row and a URL with it. The canonical event kind is
read from the episode's own CREATE envelope (§3.2: *"recorded at creation and
changed only by a superseding operation"*), never from whichever claim
happened to arrive first, so it does not churn either.

Everything in this module is pure except :func:`load_episode_records`, which
is the one function that touches a vault.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

SYSTEM_DIR = Path(__file__).resolve().parent
if str(SYSTEM_DIR) not in sys.path:
    sys.path.insert(0, str(SYSTEM_DIR))

import episode_fold_contract as efc  # noqa: E402
import event_identity as ei  # noqa: E402
from temporal_claims import TemporalContractError, collapsed_text  # noqa: E402

# --------------------------------------------------------------------------
# The input
# --------------------------------------------------------------------------

#: The keys ``episode_records`` may carry. Named so a caller that misspells
#: one gets a refusal instead of a silently identity-free fold.
IDENTITY_INPUT_KEYS = ("operations", "bindings", "manifest")

#: §3.5's ``subject_keys``, decided once. See the module docstring: the
#: episode id is the whole discriminator, and a content-derived component
#: would only make the node id churn. Named rather than inlined so I2 or I-P
#: can change the decision in ONE place if the founder review asks for it.
EPISODE_SUBJECT_KEYS: tuple = ()

#: The four keys §3.5 publishes on the envelope. Named so CERT-11's
#: "byte-identical modulo excluded envelope keys" has one spelling.
IDENTITY_ENVELOPE_KEYS = (
    "node_aliases",
    "episode_aliases",
    "identity_rule_version",
    "identity_diagnostics",
)

#: The seven keys §3.5 publishes on a node. The first four ride an EPISODE
#: node only — a node the identity layer actually made — and the last three
#: ride any node whose telling carries such a record. Absent means unchanged,
#: which is `temporal_projection`'s own convention for every additive field.
IDENTITY_NODE_KEYS = (
    "episode_id",
    "tellings",
    "telling_count",
    "identity_origins",
    "containments",
    "related",
    "proposed_links",
)

#: §5.4, raised by the LOADER rather than by the fold: an envelope naming a
#: binding record that is not on disk. `event_identity.load_operation_envelope`
#: is what raises it; this constant exists so a caller can catch the code
#: without importing two modules to spell it.
REFUSAL_ENVELOPE_INCOMPLETE = "identity_envelope_incomplete"


class EpisodeFoldError(TemporalContractError):
    """An identity input could not be read as one."""


# --------------------------------------------------------------------------
# Episodes, from the operation graph
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class EpisodeView:
    """One episode, as the fold needs it: an identity and a node id.

    It holds no content — §2.1's whole point — and every field on it comes
    from an operation envelope or from the frozen minter. ``label`` is
    deliberately absent: §3.4 makes the label its own decision record, and
    inventing one here from the members' words is exactly the drift that
    record exists to prevent.
    """

    episode_id: str
    node_id: str
    canonical_event_kind: str | None = None
    created_by: str = ""
    adopted: bool = False
    absorbed: tuple = ()

    def as_dict(self) -> dict:
        return {
            "episode_id": self.episode_id,
            "node_id": self.node_id,
            "canonical_event_kind": self.canonical_event_kind,
            "created_by": self.created_by,
            "adopted": self.adopted,
            "absorbed": list(self.absorbed),
        }


def _active(rows: object) -> list:
    return [
        row
        for row in (rows or ())
        if isinstance(row, dict)
        and collapsed_text(row.get("status") or "active") == "active"
    ]


def episode_index(operations: object, bindings: object = ()) -> dict:
    """``{episode_id: EpisodeView}`` from the operation graph.

    The operations are the authority for what an episode IS — its canonical
    event kind is recorded at creation and moves only by a superseding
    operation (§3.2) — and the bindings are the authority for what is IN it
    (§3.2/F2). Reading the two the other way round is the two-authorities
    defect, so this function reads ``members`` for nothing.

    An episode a binding names but no operation created still gets a view.
    That is not a hole being papered over: an adopted human record is
    legitimately filed against an episode whose CREATE envelope lives under a
    ``state/`` directory somebody has since deleted (§5.8 row 10), and a fold
    that refused it would lose the person's decision to a cache eviction.
    """
    rows = sorted(_active(operations), key=lambda row: collapsed_text(row.get("operation_id")))
    kinds: dict[str, str | None] = {}
    created_by: dict[str, str] = {}
    adopted: set = set()
    absorbed: dict[str, list] = {}
    order: list = []
    for row in rows:
        episode_id = collapsed_text(row.get("episode_id"))
        if not episode_id:
            continue
        op = collapsed_text(row.get("op"))
        if episode_id not in kinds:
            kinds[episode_id] = None
            order.append(episode_id)
        kind = collapsed_text(row.get("canonical_event_kind")) or None
        # `adopt` CARRIES the kind, it does not decide one (§3.2 + G1): the
        # create envelope lives under `state/`, deleting it is a supported
        # act, and an adopted episode whose node id could not be re-derived
        # from `sources/` alone is exactly the orphan G1 refuses.
        if op in ("create", "retitle", "adopt") and kind:
            kinds[episode_id] = kind
        if op == "create":
            created_by[episode_id] = collapsed_text(row.get("operation_id"))
        if op == "adopt":
            adopted.add(episode_id)
        if op == "merge":
            gone = collapsed_text(row.get("absorbed_episode_id"))
            if gone:
                absorbed.setdefault(episode_id, []).append(gone)

    for row in _active(bindings):
        episode_id = collapsed_text(row.get("episode_id"))
        if episode_id and episode_id not in kinds:
            kinds[episode_id] = None
            order.append(episode_id)

    views: dict[str, EpisodeView] = {}
    for episode_id in sorted(order):
        views[episode_id] = EpisodeView(
            episode_id=episode_id,
            node_id=efc.episode_node_id(
                canonical_event_kind=kinds.get(episode_id),
                subject_keys=EPISODE_SUBJECT_KEYS,
                episode_id=episode_id,
            ),
            canonical_event_kind=kinds.get(episode_id),
            created_by=created_by.get(episode_id, ""),
            adopted=episode_id in adopted,
            absorbed=tuple(sorted(absorbed.get(episode_id, ()))),
        )
    return views


def normalize_episode_records(episode_records: object) -> dict:
    """``{"operations", "bindings", "manifest"}`` from whatever a caller passed.

    A mapping is read by its keys; anything else is read as the bindings
    alone, because a fixture proving grouping should not have to mint an
    envelope to do it. An unknown key is a refusal rather than a shrug: a
    misspelled ``bindings`` would otherwise fold silently as no identity at
    all, which looks exactly like "the records did not apply".
    """
    if episode_records is None:
        return {"operations": [], "bindings": [], "manifest": None}
    if isinstance(episode_records, dict):
        unknown = sorted(set(episode_records) - set(IDENTITY_INPUT_KEYS))
        if unknown:
            raise EpisodeFoldError(
                "identity_input_unknown_key",
                f"episode_records carries {unknown}; it holds {list(IDENTITY_INPUT_KEYS)}",
                detail={"unknown": unknown},
            )
        return {
            "operations": [row for row in (episode_records.get("operations") or ())
                           if isinstance(row, dict)],
            "bindings": [row for row in (episode_records.get("bindings") or ())
                         if isinstance(row, dict)],
            "manifest": episode_records.get("manifest"),
        }
    return {
        "operations": [],
        "bindings": [row for row in (episode_records or ()) if isinstance(row, dict)],
        "manifest": None,
    }


def telling_manifest_view(claims: object, manifest: object = None) -> dict:
    """A manifest-SHAPED payload, supplied or synthesized (C1's own schema).

    C3's two readers take the manifest in two shapes —
    `episode_fold_contract.grouping_key` accepts a prebuilt
    ``{claim_id: telling_ref}`` index, `fold_diagnostics` insists on the
    payload — so this module holds ONE payload and derives the index from it
    rather than handing each reader whichever shape happened to be nearby.
    Getting that wrong is silent: an index passed where a payload is expected
    reads as "no tellings at all", every binding is reported dormant, and the
    projection is still correct, which is the worst way for a diagnostic to be
    wrong.
    """
    if manifest is not None:
        return manifest
    by_telling: dict[str, list] = {}
    for claim_id, telling_ref in sorted(claim_telling_index(claims).items()):
        by_telling.setdefault(telling_ref, []).append(claim_id)
    return {
        "schema_version": ei.MANIFEST_SCHEMA_VERSION,
        "rule_version": efc.IDENTITY_RULE_VERSION,
        "tellings": [
            {"telling_ref": telling_ref, "claim_ids": claim_ids, "status": "active"}
            for telling_ref, claim_ids in sorted(by_telling.items())
        ],
    }


def claim_telling_index(claims: object, manifest: object = None) -> dict:
    """``{claim_id: telling_ref}`` — from the manifest when there is one.

    Without a manifest the map is derived from the claims themselves through
    C1's `event_identity.telling_ref_for_claim`, which is the SAME function
    `build_telling_manifest` derives its rows from. So the fold and the
    manifest cannot disagree about which moment a claim belongs to, and a
    vault that has never run the binder still folds — with every telling
    standing alone, which is what it is.

    A claim citing no source belongs to no telling; that is C1's refusal at
    manifest-build time and here it is simply an absence, because the fold's
    answer for a claim with no telling is v264's own key.
    """
    if manifest is not None:
        return efc.manifest_claim_index(manifest)
    index: dict[str, str] = {}
    for claim in claims or ():
        row = claim if isinstance(claim, dict) else {}
        claim_id = collapsed_text(row.get("claim_id"))
        if not claim_id:
            continue
        try:
            index[claim_id] = ei.telling_ref_for_claim(row)
        except TemporalContractError:
            continue
    return index


def _enriched(binding: dict, episodes: dict) -> dict:
    """One binding plus the two fields the id minter reads off its episode.

    A `event_identity` record deliberately carries neither — a binding says
    WHICH episode, never what the episode is — so the fold hands
    `episode_fold_contract.grouping_key` the episode's own canonical kind and
    subject keys rather than letting it mint an id from nothing.
    """
    view = episodes.get(collapsed_text(binding.get("episode_id")))
    row = dict(binding)
    row["canonical_event_kind"] = view.canonical_event_kind if view else None
    row["subject_keys"] = list(EPISODE_SUBJECT_KEYS)
    return row


# --------------------------------------------------------------------------
# The adapter the fold holds
# --------------------------------------------------------------------------


class EpisodeIdentity:
    """Everything `temporal_timeline` needs from the identity layer, prepared.

    Constructed once per fold, from the claims and ``episode_records``. Every
    decision it serves is I0's; this class is the wiring, the enrichment and
    the per-node assembly, and it holds no rule of its own.

    The refusals are LOUD and they are raised HERE, at construction, before a
    single node is drawn: two active ``same`` bindings for one telling is
    ``identity_conflict`` (§5.4, the narrow reading I0 pinned), and a
    telling whose claims disagree about whether they are about an era is
    ``telling_mixes_event_identities``. A fold that drew half a projection
    and then refused would be worse than one that refused.
    """

    def __init__(self, claims: object = (), episode_records: object = ()) -> None:
        records = normalize_episode_records(episode_records)
        self.operations = tuple(_active(records["operations"]))
        self.manifest = records["manifest"]
        self.episodes = episode_index(records["operations"], records["bindings"])
        self.bindings = tuple(
            _enriched(row, self.episodes) for row in records["bindings"]
        )
        self.claims = [row for row in (claims or ()) if isinstance(row, dict)]
        self.active = efc.active_binding_index(self.bindings)
        self.node_of_episode = {
            episode_id: view.node_id for episode_id, view in self.episodes.items()
        }
        self.episode_of_node = {
            view.node_id: episode_id for episode_id, view in self.episodes.items()
        }
        # A vault with no records does no identity work at all — not one pass
        # over the claims, not one digest. That is what makes CERT-11's
        # "delete the layer and the drawing returns" cheap as well as true,
        # and it is why every reader below asks `self.active` first.
        self.manifest_view: dict = {"tellings": []}
        self.telling_of: dict = {}
        self._decisions: dict[str, efc.GroupingKey] = {}
        self.diagnostics: tuple = ()
        self.entailments: tuple = ()
        self._members_by_episode: dict[str, dict] = {}
        if not self.active:
            return
        self.manifest_view = telling_manifest_view(self.claims, self.manifest)
        self.telling_of = efc.manifest_claim_index(self.manifest_view)
        for claim in self.claims:
            claim_id = collapsed_text(claim.get("claim_id"))
            if claim_id:
                self._decisions[claim_id] = efc.grouping_key(
                    claim, self.telling_of, self.active
                )
        self.diagnostics = efc.fold_diagnostics(
            self.claims, self.manifest_view, self.active
        )
        self.entailments = efc.entailed_not_same(self.active)
        # One pass over the bindings instead of one pass PER NODE. §5.7 budgets
        # a dict lookup per claim and one entailment pass; assembling an
        # episode's member list by re-scanning every binding for every node
        # would be the quadratic term that budget does not have.
        for telling_ref, rows in self.active.items():
            for row in rows:
                if collapsed_text(row.get("relation")) != efc.GROUPING_RELATION:
                    continue
                if collapsed_text(row.get("origin")) not in efc.GROUPING_ORIGINS:
                    continue
                episode_id = collapsed_text(row.get("episode_id"))
                if episode_id:
                    self._members_by_episode.setdefault(episode_id, {})[telling_ref] = row

    # -- the grouping decision ------------------------------------------

    @property
    def applies(self) -> bool:
        """Is there anything to apply at all?

        A vault with no records folds through the v264 path untouched, which
        is what makes CERT-11's *"delete the layer and the drawing returns"*
        an arithmetic identity rather than a hope.
        """
        return bool(self.active)

    def episode_node_for(self, claim: object) -> str:
        """The episode node this claim groups under, or ``""`` to stand aside."""
        if not self.active:
            return ""
        decision = self._decisions.get(collapsed_text((claim or {}).get("claim_id")))
        if decision is None or decision.kind != "episode":
            return ""
        return decision.key

    def decision_for(self, claim: object) -> efc.GroupingKey | None:
        return self._decisions.get(collapsed_text((claim or {}).get("claim_id")))

    def telling_for(self, claim: object) -> str:
        return collapsed_text(
            self.telling_of.get(collapsed_text((claim or {}).get("claim_id")))
        )

    # -- the published tables -------------------------------------------

    def node_aliases(self) -> dict:
        """``{former node id: episode node id}`` (§3.5, Law 5)."""
        if not self.active:
            return {}
        return efc.node_aliases(tuple(self._decisions.values()))

    def episode_aliases(self) -> dict:
        """``{absorbed episode id: surviving episode id}`` (§3.2, row 8)."""
        return efc.episode_aliases(self.operations)

    def identity_diagnostics(self) -> dict:
        """What the fold saw and what it entailed — derived, never stored.

        ``entailed_not_same`` is published because §2.2 requires the negative
        to be CONSULTABLE by the binder and the planner, and computed here
        because it must disappear the moment either premise does. Storing the
        closure is how a retracted binding leaves a permanent phantom
        negative behind, so it is a view of this generation and nothing else.
        """
        return {
            "findings": [dict(row) for row in self.diagnostics],
            "entailed_not_same": [list(pair) for pair in self.entailments],
            "counts": {
                "episodes": len(self.episodes),
                "operations": len(self.operations),
                "bindings": len(self.bindings),
                "bound_tellings": len(self.active),
                "findings": len(self.diagnostics),
                "entailed_not_same": len(self.entailments),
            },
        }

    def identity_mapping(self) -> dict:
        """§3.5's published ``episode_id ↔ node_id`` map, both ways."""
        return efc.identity_mapping(
            [
                {
                    "episode_id": view.episode_id,
                    "canonical_event_kind": view.canonical_event_kind,
                    "subject_keys": EPISODE_SUBJECT_KEYS,
                }
                for view in self.episodes.values()
            ]
        )

    # -- per-node assembly ----------------------------------------------

    def _rows_for(self, telling_refs: object, relations: object, origins: object) -> list:
        found = []
        for telling_ref in sorted(set(telling_refs or ())):
            for row in self.active.get(telling_ref) or ():
                relation = collapsed_text(row.get("relation"))
                origin = collapsed_text(row.get("origin"))
                if relation not in relations or origin not in origins:
                    continue
                episode_id = collapsed_text(row.get("episode_id"))
                found.append({
                    "telling_ref": telling_ref,
                    "episode_id": episode_id,
                    "episode_node_id": self.node_of_episode.get(episode_id, ""),
                    "relation": relation,
                    "origin": origin,
                })
        found.sort(key=lambda row: (row["telling_ref"], row["episode_id"], row["relation"]))
        return found

    def node_block(self, node_id: object, group_claims: object) -> dict:
        """The additive §3.5 block for one node, or ``{}``.

        Four of the seven keys ride an EPISODE node only — a node the
        identity layer actually made — because publishing ``telling_count: 1``
        on every node in a vault that has never bound anything would be a
        schema change dressed as a fact. The other three ride any node whose
        telling carries such a record.
        """
        if not self.active:
            return {}
        key = collapsed_text(node_id)
        tellings = sorted({
            self.telling_for(claim) for claim in (group_claims or ())
        } - {""})
        block: dict = {}
        episode_id = self.episode_of_node.get(key)
        if episode_id:
            bound = self._members_by_episode.get(episode_id) or {}
            # Intersected with the tellings whose claims actually landed in
            # this group: a member whose claims were all retracted is a
            # DORMANT binding (reported by `fold_diagnostics`), and counting
            # it here would publish a `telling_count` the node cannot show.
            members = sorted(set(bound) & set(tellings))
            origins = sorted({
                collapsed_text(bound[telling_ref].get("origin"))
                for telling_ref in members
            })
            block["episode_id"] = episode_id
            block["tellings"] = members
            block["telling_count"] = len(members)
            block["identity_origins"] = origins
        containments = self._rows_for(tellings, ("part_of",), efc.GROUPING_ORIGINS)
        if containments:
            block["containments"] = containments
        related = self._rows_for(tellings, ("related",), efc.GROUPING_ORIGINS)
        if related:
            block["related"] = related
        proposed = self._rows_for(tellings, efc.RELATIONS, ("proposed",))
        if proposed:
            block["proposed_links"] = proposed
        return block

    # -- containment ------------------------------------------------------

    def containing_episodes(self, telling_refs: object) -> list:
        """The episodes these tellings are ``part_of``, in a stable order."""
        return [row["episode_id"] for row in
                self._rows_for(telling_refs, ("part_of",), efc.GROUPING_ORIGINS)]

    def containment_value(self, telling_refs: object, *, placed: object,
                          labels: object = None):
        """§5.3's possible outer range for a contained member with no value.

        Delegated to `episode_fold_contract.possible_outer_range`, where every
        clause of the rule is structural: the bounds are the episode's own,
        copied; ``member_value is None`` is the only branch; ``anchors`` is
        empty; nothing is written. This function's whole job is to find the
        containing episode's span, and to refuse to choose when a telling is
        contained by two episodes that were placed differently — an ambiguity
        is a Mirror row for I3, never a pick.
        """
        found = []
        for episode_id in self.containing_episodes(telling_refs):
            node_id = self.node_of_episode.get(episode_id)
            span = (placed or {}).get(node_id) if node_id else None
            if span is None:
                continue
            found.append((episode_id, node_id, span))
        if len(found) != 1:
            return None
        episode_id, node_id, span = found[0]
        return efc.possible_outer_range(
            None, span, episode_id=episode_id,
            episode_label=(labels or {}).get(node_id) or episode_id,
        )


# --------------------------------------------------------------------------
# The one function that touches a vault
# --------------------------------------------------------------------------


def load_episode_records(vault_root: str | Path, *, manifest: object = None) -> dict:
    """Every identity record a vault holds — BOTH authorities — validated.

    §3.3's storage split is a fact about durability, not about precedence:
    ``sources/identity/`` holds what a person decided and ``state/
    temporal_claims/identities/`` holds what a rule derived, and the fold
    reads both because a grouping authority that ignored half its records
    would draw a timeline nobody filed.

    Two refusals happen here rather than downstream. Every envelope is read
    back through `event_identity.load_operation_envelope`, so an operation
    naming a binding the vault does not hold is
    :data:`REFUSAL_ENVELOPE_INCOMPLETE` — never a partially applied episode.
    And the whole binding set goes through
    `event_identity.validate_identity_set`, which is where an unsuperseded
    semantic twin across the two directories is refused instead of settled by
    recency.
    """
    operations = ei.load_episode_operations(vault_root)
    bindings = ei.load_event_identities(vault_root)
    for operation in operations:
        ei.load_operation_envelope(vault_root, operation)
    ei.validate_identity_set(bindings)
    return {
        "operations": operations,
        "bindings": bindings,
        "manifest": manifest if manifest is not None
        else ei.read_telling_manifest(vault_root),
    }


__all__ = [
    "EPISODE_SUBJECT_KEYS",
    "IDENTITY_ENVELOPE_KEYS",
    "IDENTITY_INPUT_KEYS",
    "IDENTITY_NODE_KEYS",
    "REFUSAL_ENVELOPE_INCOMPLETE",
    "EpisodeFoldError",
    "EpisodeIdentity",
    "EpisodeView",
    "claim_telling_index",
    "episode_index",
    "load_episode_records",
    "normalize_episode_records",
    "telling_manifest_view",
]
