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

import chronology as chrono  # noqa: E402
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

#: v342 (the 2026-09-24 sweep on the owner's vault). An alias is a REDIRECT,
#: and until this release the fold published it without following it. The
#: identity layer binds a TELLING; the fold groups a CLAIM. So a claim of a
#: whole-message telling — a `landmark_reading` over one conversation, which
#: holds every fact that message mentions and can therefore never be bound to
#: one episode — kept grouping under the node id the fold minted for it even
#: after a bind had aliased that exact id into an episode. The drawing then
#: held BOTH: the merged node with the date, and the old id with the same
#: label, no date, and a freshly minted "when did this happen?" card asking the
#: question the merged node beside it already answers.
#:
#: On the owner's vault that is `node:883802c17ba32910522bb663` "Brittney's
#: birth", placed 17 December 1987 by a resolver reading answered FOR that node
#: id, unplaced after the sweep while `node:a12d4c388c7a4b27140502a2` carried
#: the same date and the same two claims — with `node_aliases` already saying
#: the first IS the second. The alias was right; nothing followed it.
#:
#: So the claim follows the node — and it follows it only where the node really
#: is one fact. An UNDISCRIMINATED id is a bucket: a repeatable kind with no
#: discriminator mints one id for every one of them, and un-bucketing it is what
#: a bind is FOR. So a leftover claim whose own date contradicts the merge stays
#: where it is and the key is not redirected at all — reported contested, absent
#: from the table — because a redirect to one of the two things an id means is
#: worse than no redirect. The invariant is then checkable in one line: after a
#: fold, no key of ``node_aliases`` is the id of a node the drawing publishes.
AN_ALIAS_NEVER_NAMES_A_NODE_THE_DRAWING_PUBLISHES = (
    "a claim follows the node it folds under: when a bind re-keys that node "
    "every remaining claim of it goes along unless its own date contradicts the "
    "merge, and a key some claim still holds is not redirected at all — so no "
    "node is ever drawn at an id node_aliases has already redirected"
)

#: v353, and the second half of the same lesson: a node's KIND is the node's,
#: not its first claim's.
#:
#: THE INCIDENT (owner's vault, staging, 2026-09-25 07:24 UTC, framework v352).
#: `place-answers` filed the owner's reply *"This happened in the middle of
#: sixth grade for James."* as a `telling_only` `occurrence` on
#: `node:22784323839a0481b081ceab` — *"James Everett moved between baseball
#: teams"*, the node the card he answered is about, and an EPISODE
#: (`episode:59ae397ae9edf8b6719355f7`, one bound telling, canonical kind
#: `moment`). The next `temporal_publication.publish` RAISED
#: `episode_block_on_non_episode_node` and drew nothing at all: the vault
#: stopped updating for every node, not just that one.
#:
#: Why: the answer's telling is not bound to the episode — no rung has looked
#: at it yet, and `answer_placement` is a claim filer and not an identity
#: decider — so `episode_node_for` stood aside for it, and because its claim id
#: happened to sort first (`claim:cb8c3d…` before `claim:d7232e…`; the active
#: index is in claim-id order) it CREATED the group and the group was made an
#: `event` from its own `event_kind`. :meth:`EpisodeIdentity.node_block` then
#: read the published episode↔node map — which knows nothing about claim order
#: — and stamped the episode block on it. Two readings of "is this node an
#: episode?", one per claim and one per node, disagreeing about a node whose id
#: was MINTED with `node_kind: episode` inside its digest.
#:
#: So there is one reading (:meth:`EpisodeIdentity.episode_of`), it is asked of
#: the node id, and both the grouping and the episode block go through it. A
#: telling of an episode is an ordinary, honest thing for a person to file —
#: their reply really is another telling of that episode — and it must not be
#: able to change what the node IS.
AN_EPISODE_NODES_KIND_IS_THE_NODES_AND_NOT_ITS_FIRST_CLAIMS = (
    "an episode's node id is minted with node_kind: episode inside its digest, "
    "so a group drawn at that id is that episode whatever its claims say and "
    "whichever of them was read first — one reading of it, asked of the node "
    "and shared by the grouping and the episode block, so the fold can never "
    "draw a node the projection must refuse"
)

#: The relation a person files about an episode their telling is NOT
#: (§6.1). Named here because :meth:`EpisodeIdentity._refuses` is the second
#: reader of it and `episode_fold_contract` spells the positive one only.
NEGATIVE_RELATION = "not_same"

#: Reported, never raised: a key an episode aliased that the fold could not
#: follow, because the person has said that telling is not that episode. The
#: row is dropped from `node_aliases` rather than published as a redirect to a
#: node the drawing still draws.
DIAGNOSTIC_ALIAS_CONTESTED = "identity_node_alias_contested"

#: Reported, never raised: a key the fold FOLLOWED — one claim's own node id
#: redirected into an episode by a bind that could not take its telling. Not a
#: fault; the one line that says the drawing and the alias table agree.
DIAGNOSTIC_ALIAS_FOLLOWED = "identity_node_alias_followed"

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
        self.active = efc.active_binding_index(self.bindings, self.manifest)
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
        self._aliases: dict | None = None
        #: ``{former key: episode node}`` the fold actually FOLLOWED, and the
        #: ones a `not_same` refused. Both are filled during grouping, which is
        #: the only pass that knows the key a claim would otherwise publish.
        self._carried: dict[str, str] = {}
        self._contested: dict[str, str] = {}
        #: ``{former key: episode node}`` for a BOUND claim whose own key the
        #: contract could not see — see :meth:`note_former_key`.
        self._noted: dict[str, str] = {}
        #: ``{claim_id: episode node}`` — what :meth:`plan_carries` decided.
        self._carried_for: dict[str, str] = {}
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

    def episode_of(self, node_id: object) -> str:
        """The episode a NODE ID *is*, or ``""`` — v353's one reading of it.

        :meth:`episode_node_for` answers a question about a CLAIM: did a bind
        put this telling in an episode? This answers a question about a NODE:
        is this id an episode's own id? They are not the same question, and
        v353's incident is what happens when the second one is answered by
        asking the first. An episode's node id is minted with
        ``node_kind: episode`` INSIDE its digest
        (:func:`episode_fold_contract.episode_node_id`,
        `temporal_projection.NODE_IDENTITY_KEYS`), so the id itself already
        says what the node is — whoever filed the claim that happened to be
        read first does not.

        Every reader of "is this node an episode?" goes through here — the
        fold's grouping and :meth:`node_block`'s own episode block — so the
        two cannot disagree and produce a node the projection refuses. Gated on
        :attr:`active` for CERT-11's reason: a vault with no active binding
        does no identity work at all.
        """
        if not self.active:
            return ""
        return collapsed_text(self.episode_of_node.get(collapsed_text(node_id)))

    def decision_for(self, claim: object) -> efc.GroupingKey | None:
        return self._decisions.get(collapsed_text((claim or {}).get("claim_id")))

    def telling_for(self, claim: object) -> str:
        return collapsed_text(
            self.telling_of.get(collapsed_text((claim or {}).get("claim_id")))
        )

    # -- the alias, followed rather than merely published ----------------

    def plan_carries(self, readings: object) -> dict:
        """Decide, over the WHOLE claim set, which claims follow a re-keyed node.

        :data:`AN_ALIAS_NEVER_NAMES_A_NODE_THE_DRAWING_PUBLISHES`, as one pure
        pass. ``readings`` is what only the fold can supply — per claim, the key
        it would publish under, the episode a bind put it in (``""`` when none),
        and its own dated bounds as a `chronology.DateRecord`:
        ``(claim_id, telling_ref, key, episode_node, bounds)``. The answer is
        ``{claim_id: episode node}`` for the claims that move.

        Three decisions, and each one is a case the owner's vault holds:

        * **The key is followed through chains** — a merge of a merge leaves
          ``A -> B -> C`` and the claim belongs to ``C`` — with a cycle guard,
          because a superseding operation can make the table circular.
        * **A contradicting date is never carried** — v340's own rule, *a merge
          never moves a dated moment*, through the arithmetic both readers share
          (`chronology.dates_agree`). Named rather than imported: `compile`
          never reaches the binder, and a guard test sweeps this file for the
          word. An UNDISCRIMINATED node
          id is a bucket rather than a fact: a repeatable kind with no
          discriminator mints one id for every one of them, so "Started
          Etherfuse" (May 2022) and "Joined Ridgeline" (2015) share a key. A
          bind that pulls one of them into an episode is UN-bucketing, and
          dragging the other one along on the strength of a shared bucket id
          would move a dated moment 7 years. An undated leftover contradicts
          nothing and goes.
        * **A key the drawing still holds is not redirected at all** — it is
          reported CONTESTED and dropped from :meth:`node_aliases`, because a
          redirect to one of the two things an id means is worse than none.
          Same for a `not_same` (§6.1): the person has said that telling is not
          that episode, and no table carries it in by the back door.
        """
        rows = [self._reading(row) for row in (readings or ())]
        if not self.active:
            return {}
        aliases = self._alias_table()
        keys: dict[str, dict] = {}
        for claim_id, telling_ref, key, episode_node, bounds in rows:
            if not key:
                continue
            slot = keys.setdefault(key, {"targets": set(), "bound": [], "left": []})
            if episode_node:
                slot["targets"].add(episode_node)
                slot["bound"].append(bounds)
            else:
                slot["left"].append((claim_id, telling_ref, bounds))
        # A key the CONTRACT aliased from a claim's own `event_ref` is a former
        # key too, even when no row above named it: I0 saw the ref, this pass
        # sees the mint, and both are keys the drawing must let go of.
        for key, target in sorted(aliases.items()):
            keys.setdefault(key, {"targets": {target}, "bound": [], "left": []})
        for key in sorted(keys):
            slot = keys[key]
            target = self._follow(key, aliases)
            if len(slot["targets"]) == 1 and not target:
                target = next(iter(slot["targets"]))
            if not target or target == key:
                if len(slot["targets"]) > 1:
                    self._contested[key] = min(slot["targets"])
                continue
            if len(slot["targets"]) > 1:
                self._contested[key] = target
                continue
            stayed = False
            for claim_id, telling_ref, bounds in slot["left"]:
                agrees = all(chrono.dates_agree(bounds, other) for other in slot["bound"])
                if agrees and not self._refuses(telling_ref, target):
                    self._carried_for[claim_id] = target
                else:
                    stayed = True
            if stayed:
                self._contested[key] = target
                for claim_id, _, _ in slot["left"]:
                    self._carried_for.pop(claim_id, None)
                continue
            self._carried[key] = target
            self._noted[key] = target
            self._aliases = None
        for key in self._contested:
            self._noted.pop(key, None)
            self._carried.pop(key, None)
        self._aliases = None
        return dict(self._carried_for)

    def carried_node_for(self, claim: object) -> str:
        """The episode node this claim follows, or ``""`` — :meth:`plan_carries`'
        answer, read back per claim. No arithmetic of its own."""
        return self._carried_for.get(
            collapsed_text((claim or {}).get("claim_id")), ""
        ) if self.active else ""

    def _reading(self, row: object) -> tuple:
        claim_id, telling_ref, key, episode_node, bounds = row
        return (collapsed_text(claim_id), collapsed_text(telling_ref),
                collapsed_text(key), collapsed_text(episode_node), bounds)

    def _follow(self, key: str, aliases: dict) -> str:
        """``node_aliases`` walked to its end, or ``""`` on a cycle."""
        target, seen = key, {key}
        while target in aliases:
            nxt = aliases[target]
            if nxt in seen:
                return ""
            seen.add(nxt)
            target = nxt
        return "" if target == key else target

    def _alias_table(self) -> dict:
        if self._aliases is None:
            self._aliases = {
                **self._absorbed_episode_nodes(),
                **efc.node_aliases(tuple(self._decisions.values())),
                **self._noted,
            }
        return self._aliases

    def _absorbed_episode_nodes(self) -> dict:
        """``{absorbed episode's node id: surviving episode's node id}`` (v342).

        The third way a node id moves, and the one neither C3 nor the mint can
        see. An episode's node id is derived FROM its episode id (§3.5), so an
        episode that grows a member or is absorbed by a merge takes a new
        episode id and therefore a new node id — while a work item, an open
        session and a URL still name the old one. `episode_aliases` records the
        act; this composes it through ``node_of_episode`` so Law 5's promise
        covers it in the table readers actually follow.

        On the owner's vault this is 68 rows and 61 of the placements a v341
        apply appeared to lose: "Father started pool company in Yucaipa" moved
        from `node:401521b0…` to `node:2162c370…`, with the same two claims and
        the same 1990-06/1991-06, because its episode was re-created with one
        more member.
        """
        table: dict[str, str] = {}
        for absorbed, surviving in sorted(self.episode_aliases().items()):
            left = collapsed_text(self.node_of_episode.get(absorbed))
            right = collapsed_text(self.node_of_episode.get(surviving))
            if left and right and left != right:
                table[left] = right
        return table

    def _refuses(self, telling_ref: object, node_id: str) -> bool:
        """Has this telling been told it is NOT the episode drawn as ``node_id``?"""
        episode_id = collapsed_text(self.episode_of_node.get(node_id))
        if not episode_id:
            return False
        for row in self.active.get(collapsed_text(telling_ref)) or ():
            if collapsed_text(row.get("relation")) != NEGATIVE_RELATION:
                continue
            if collapsed_text(row.get("episode_id")) == episode_id:
                return True
        return False

    # -- the published tables -------------------------------------------

    def node_aliases(self) -> dict:
        """``{former node id: episode node id}`` (§3.5, Law 5).

        Three sources, one table (v342): C3's rows from each bound claim's own
        ``event_ref``, the key the fold MINTED for a bound telling that had none
        (:meth:`plan_carries`), and the node id of an episode a merge absorbed
        (:meth:`_absorbed_episode_nodes`). A CONTESTED key is absent — see
        :meth:`plan_carries`. After grouping, every remaining key names a node
        the drawing no longer draws, which is
        :data:`AN_ALIAS_NEVER_NAMES_A_NODE_THE_DRAWING_PUBLISHES` as a table.
        """
        if not self.active:
            return {}
        table = {**self._alias_table(), **self._noted}
        for key in self._contested:
            table.pop(key, None)
        return dict(sorted(table.items()))

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

        The two alias rows are appended by GROUPING rather than by the
        constructor, because the key a claim would otherwise have published is
        only known where it is minted (v342). A caller that never grouped sees
        the constructor's findings alone, which is what it is.
        """
        findings = [dict(row) for row in self.diagnostics]
        for key, target in sorted(self._carried.items()):
            findings.append({
                "code": DIAGNOSTIC_ALIAS_FOLLOWED, "telling_ref": "",
                "episode_id": collapsed_text(self.episode_of_node.get(target)),
                "detail": f"{key} -> {target}",
            })
        for key, target in sorted(self._contested.items()):
            findings.append({
                "code": DIAGNOSTIC_ALIAS_CONTESTED, "telling_ref": "",
                "episode_id": collapsed_text(self.episode_of_node.get(target)),
                "detail": f"{key} -> {target}",
            })
        return {
            "findings": findings,
            "entailed_not_same": [list(pair) for pair in self.entailments],
            "counts": {
                "episodes": len(self.episodes),
                "operations": len(self.operations),
                "bindings": len(self.bindings),
                "bound_tellings": len(self.active),
                "findings": len(findings),
                "entailed_not_same": len(self.entailments),
                "aliases_followed": len(self._carried),
                "aliases_contested": len(self._contested),
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
        episode_id = self.episode_of(key)
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

    # -- participation episodes (E-L2a) -----------------------------------

    def adopt_participation_episodes(self, mapping: object) -> None:
        """Teach the fold which node a landmark-minted episode is drawn as.

        A participation episode (`landmark_projection.ParticipationEpisodes`)
        is minted by the RECORDER's own entry rather than by an identity
        operation, so it has no create envelope and never appears in
        :attr:`episodes` — and until this map existed the ``part_of`` record
        the `entity_span` rung files named an ``episode_id`` the projection
        had no node for. :func:`containment_value` then found no span and drew
        no window, which is why a residence a person filed in conversation
        could not contain a story (design §0.2 M1).

        Only ``node_of_episode`` is extended. ``episode_of_node`` is left
        alone ON PURPOSE: :func:`node_block` reads it to publish
        ``telling_count`` and ``identity_origins``, and a participation
        episode has no member tellings of its own, so registering it there
        would publish a ``telling_count: 0`` nobody filed.

        An episode an operation CREATED always wins: the real episode is the
        identity layer's, and this is the answer for the one that is not. An
        episode known only from a BINDING is the prospective-container case,
        and `episode_fold_contract.episode_node_id` mints that one a node id
        no group ever lands on — a synthetic id pointing at nothing, which is
        exactly what a dangling ``episode_node_id`` on a containment row was.
        """
        for episode_id, node_id in sorted(dict(mapping or {}).items()):
            key, value = collapsed_text(episode_id), collapsed_text(node_id)
            if not key or not value:
                continue
            view = self.episodes.get(key)
            if view is not None and view.created_by:
                continue
            self.node_of_episode[key] = value

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
        if not found:
            return None
        # E-L2a §4.2 — SEVERAL CONTAINMENTS INTERSECT. A story in Bothell at
        # Boeing is inside a residence episode AND an employment episode, and
        # both are the person's own dated claims, so the honest window is
        # where they overlap. Each single containment is still "never narrower
        # than the span" (§5.3, unchanged); the intersection is narrower only
        # because two person-dated spans BOTH hold.
        narrowed = found[0][2]
        for _episode_id, _node_id, span in found[1:]:
            narrowed = chrono.intersect(narrowed, span)
            if narrowed is None:
                # An empty intersection draws NOTHING and is reported as a
                # material contradiction citing both containments (§4.2). The
                # old rule's `len(found) != 1 -> None` said the same thing for
                # this case and said it silently, which is the half of it that
                # was wrong: a member the substrate cannot place is a question,
                # not a shrug.
                return None
        episode_id, node_id, _span = found[0]
        label = ", ".join(
            (labels or {}).get(row[1]) or row[0] for row in found
        )
        return efc.possible_outer_range(
            None, narrowed, episode_id=episode_id, episode_label=label,
        )

    def containment_conflict(self, telling_refs: object, *, placed: object) -> list:
        """The containments whose spans do NOT overlap, for §4.2's row.

        Returns the ``[(episode_id, node_id, span), ...]`` a contradiction
        should cite, or ``[]`` when the windows intersect (or when there is
        nothing to intersect). Separate from :func:`containment_value` because
        a value function that also minted questions would have two jobs and
        one return type.
        """
        found = []
        for episode_id in self.containing_episodes(telling_refs):
            node_id = self.node_of_episode.get(episode_id)
            span = (placed or {}).get(node_id) if node_id else None
            if span is not None:
                found.append((episode_id, node_id, span))
        if len(found) < 2:
            return []
        narrowed = found[0][2]
        for row in found[1:]:
            narrowed = chrono.intersect(narrowed, row[2])
            if narrowed is None:
                return found
        return []


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
        # v331: the binding set read ONCE above is the one every envelope is
        # checked against — the fold is O(operations + bindings), not their
        # product (see `load_operation_envelope`).
        ei.load_operation_envelope(vault_root, operation, bindings=bindings)
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
