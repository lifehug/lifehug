"""v342 — a merged node keeps its date, and an alias never names a drawn node.

The incident, measured on a scratch clone of the owner's vault at
`101719e5` with v341 bytes (`bind-episodes --apply` filed 535 envelopes and
140 proposals, then a publish took generation 149 to 150). v340's own
guarantees held — Yucaipa stayed two moves, the owner's 1981-07-11 anchor
stayed single, 471 "lost" placements were re-keyed with the same date — and
ONE placed node lost its date anyway:

* BEFORE, `node:883802c17ba32910522bb663` "Brittney's birth" was placed
  1987-12-17, certain/stated, on the strength of ONE claim — a resolver
  reading answered FOR that node id (`resolver:883802c17ba32910522bb663`);
* AFTER, that same node id was still drawn, `best_temporal_value: null`,
  with a NEW ``precision_gap`` card, *"When was Brittney born?"*, minted
  against it — while `node:a12d4c388c7a4b27140502a2` "Brittney Mason's
  birth" carried the reading's claim, the household-birthdays claim and the
  date 1987-12-17;
* and `node_aliases` ALREADY said the first id is the second. The alias was
  right. Nothing followed it.

The mechanism is the seam between the two layers: the identity layer binds a
TELLING, the fold groups a CLAIM. The claim that kept the old node alive is
`claim:5428d7becc4888d11d9cce2b`, a `landmark_reading` over one whole
conversation (`conversation:msg-150f894b07bcd1f4cd55dcee`) whose other claims
are *"Kristine 10"* and *"Dad graduated"* — a telling no rung may bind to a
birth episode, because binding the telling would drag two unrelated facts in
with it. So the bind took the reading and the household telling, aliased the
node id they had both pointed at, and left one claim behind still grouping
under it. The fixtures below mint the incident's own node id from the
incident's own subject and event kind (`Brittney` / `child_born`), which is
why `node:883802c17ba32910522bb663` appears in a synthetic test.

A third way a node id moves turned up in the same audit and is fixed here too:
an episode's node id is derived FROM its episode id, so an episode that gains a
member takes a new node id — 68 rows on the owner's vault, and 61 of the
placements a v341 apply appeared to lose outright — while `episode_aliases`
recorded the act and `node_aliases`, the table readers follow, did not.

Both deliverables are guarded here: the repro as a unit
(:class:`AMergedNodeKeepsItsDateTests`), and v340's promise restated as an
invariant over every node of a vault rather than over named ones
(:class:`EveryPlacementSurvivesAnApplyTests`). Every negative was run against
a build with its guard removed and SEEN failing first.
"""

from __future__ import annotations

import shutil
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "system"))
sys.path.insert(0, str(ROOT / "tests"))

import chronology as chrono  # noqa: E402
import episode_binder as eb  # noqa: E402
import episode_fold as ef  # noqa: E402
import identity_resolution as ident  # noqa: E402
import temporal_publication as pub  # noqa: E402
from tempdirs import root_parent_tmp  # noqa: E402

# The v340 fixtures, reused rather than re-derived: one claim builder, one
# EDTF value builder, one vault writer, one clock. A second spelling of "the
# shape a vault's receipts actually have" is how two tests come to disagree
# about what a vault is.
from test_v340_apply_keeps_placements import (  # noqa: E402
    NOW,
    claim,
    owner_age,
    owner_birth,
    value,
    write_vault,
    yucaipa_claims,
)

# --------------------------------------------------------------------------
# The incident's own vault, in three tellings
# --------------------------------------------------------------------------

#: The node the fold mints for a bare *"Brittney"* + ``child_born`` — the
#: owner's vault's own `node:883802c17ba32910522bb663`, through the substrate's
#: one minter rather than pasted in as a literal.
BRITTNEY_NODE = ident.derive_episode_ref(
    event_kind="child_born", subject_ref="Brittney", counterpart_ref=None
)

#: The whole-message telling: a `landmark_reading` over one conversation. It
#: holds three facts, which is exactly why no rung can bind it.
CONVERSATION = "conversation:msg-150f894b07bcd1f4cd55dcee"

#: The resolver's reading, declared under a ref naming the NODE it answered
#: (v333's `resolver.READING_IS_NOT_AN_EVENT`), which is what makes it a
#: derived reading to `episode_binder.reads_node`.
READING = f"resolver:{BRITTNEY_NODE.split(':', 1)[1]}"

#: The household birthdays sheet: the same person, written out in full.
HOUSEHOLD = "classification:sources-manual-birthdays#5841bd41f032"

BIRTHDAY = "1987-12-17"


def brittney_claims() -> list:
    """The incident's three tellings, in the shapes its extractors filed."""
    return [
        # 1. The bare-first-name telling, with no event_ref of its own: the
        #    fold MINTS `BRITTNEY_NODE` from its subject and kind, and that
        #    minted id is what the resolver was later asked about.
        claim(claim_type="occurrence", subject_mention="Brittney",
              event_kind="child_born", source=CONVERSATION,
              event_mention="Brittney born",
              quote="Brittney born"),
        # …and the two other facts the same message mentions. They are the
        # reason the telling is unbindable, so they are part of the fixture and
        # not decoration.
        claim(claim_type="occurrence", subject_mention="Kristine",
              event_kind="event", source=CONVERSATION,
              event_mention="Kristine 10", quote="Kristine 10"),
        claim(claim_type="occurrence", subject_mention="Dad",
              event_kind="graduation", source=CONVERSATION,
              event_mention="Dad graduated", quote="Dad graduated"),
        # 2. The resolver reading, answered FOR that node id.
        claim(claim_type="date", subject_mention="Brittney",
              event_kind="child_born", source=READING,
              source_kind=eb.DERIVED_READING_SOURCE_KIND,
              extractor_version="resolver/rule:3", event_ref=BRITTNEY_NODE,
              event_mention="Brittney's birth", temporal_value=value(BIRTHDAY),
              quote="Brittney was born on 17 December 1987."),
        # 3. The household-birthdays telling, full name.
        claim(claim_type="date", subject_mention="Brittney Mason",
              event_kind="birth", source=HOUSEHOLD,
              event_mention="Brittney Mason's birth date",
              temporal_value=value(BIRTHDAY),
              quote="Brittney Mason — 17 December 1987."),
    ]


# --------------------------------------------------------------------------
# Reading a projection: the audit's own vocabulary
# --------------------------------------------------------------------------


def placed(projection: dict) -> dict:
    """``{node id: best_temporal_value}`` for every node the drawing dates."""
    found: dict[str, dict] = {}
    for node in projection.get("nodes") or ():
        node_id = node.get("id") or node.get("node_id")
        row = node.get("best_temporal_value") or {}
        if node_id and row.get("best"):
            found[node_id] = row
    return found


def drawn(projection: dict) -> set:
    """Every node id the drawing publishes, dated or not."""
    return {
        node.get("id") or node.get("node_id")
        for node in projection.get("nodes") or ()
        if node.get("id") or node.get("node_id")
    }


def follow(node_id: str, aliases: dict) -> str:
    """``node_aliases``, followed to its end, with a cycle guard."""
    current, seen = node_id, {node_id}
    while current in aliases:
        nxt = aliases[current]
        if nxt in seen:
            return current
        seen.add(nxt)
        current = nxt
    return current


def dates_are_compatible(before: dict, after: dict) -> bool:
    """Is there any date the two placements could BOTH be?

    The same arithmetic `episode_binder._dates_agree` refuses a merge on —
    `chronology.intersect` — so "compatible" means one thing in this repo and
    a narrowing (1986-06/1988-06 → 1987-12-17) is not a loss.
    """
    left, right = chrono.from_dict(before), chrono.from_dict(after)
    if left is None or right is None:
        return False
    return chrono.intersect(left, right) is not None


def keeps_the_rival(node: dict, before_row: dict, items: object) -> bool:
    """Did the merge move this date OUT LOUD rather than silently?

    v340's own ruling, in the audit's vocabulary. `R2a` and `R2b` are
    deliberately NOT governed by *a merge never moves a dated moment*: their key
    is the identity of ONE fact, and two readings of one fact that disagree
    about its date are exactly the contradiction a fold exists to surface —
    which is how the owner's four duplicate-birth nodes fold at all. So a merged
    node MAY carry the other reading's date instead of this one, on two
    conditions: the old reading is still there among ``alternate_values``, and
    the node carries a ``contradiction`` card asking which is right. A date that
    moved with the disagreement on the page is the fold doing its job; a date
    that moved with nothing said is the loss.
    """
    kept = any(
        dates_are_compatible(before_row, row)
        for row in (node.get("alternate_values") or ())
    )
    node_id = node.get("id") or node.get("node_id")
    asked = any(
        item.get("kind") == "contradiction"
        and (item.get("node_ref") or item.get("event_ref")) == node_id
        for item in items or ()
    )
    return kept and asked


def lost_placements(before: dict, after: dict) -> list:
    """v340's guarantee as an INVARIANT: what a bind cost this vault.

    Every node placed in ``before`` must, in ``after``, be placed at a
    compatible date — or be GONE from the drawing and present in
    ``node_aliases`` pointing (through any chain) at a node that is placed at a
    compatible date, or at one that KEEPS the old reading as a rival and says so
    (:func:`keeps_the_rival`). Anything else is a placement the apply lost, and
    this list is what must be empty.

    The order of those clauses is the incident. An alias redirects a REFERENCE;
    it cannot excuse a node that is still on the page without its date.
    `node:883802c17ba32910522bb663` was aliased at a node carrying the very same
    1987-12-17 — and was still drawn, undated, with its card re-minted — so an
    audit that tried the alias first passed the run that lost the date. A node
    still drawn is judged on its own placement, and only a node the drawing has
    let go of may be answered for by its alias.
    """
    aliases = dict(after.get("node_aliases") or {})
    after_placed, after_drawn = placed(after), drawn(after)
    after_nodes = {node.get("id") or node.get("node_id"): node
                   for node in after.get("nodes") or ()}
    items = after.get("work_items") or ()
    lost: list[dict] = []
    for node_id, row in sorted(placed(before).items()):
        if node_id in after_placed:
            if dates_are_compatible(row, after_placed[node_id]):
                continue
            if keeps_the_rival(after_nodes[node_id], row, items):
                continue
            lost.append({"node_id": node_id, "before": row.get("best"),
                         "after": after_placed[node_id].get("best"),
                         "why": "still drawn, at an incompatible date"})
            continue
        if node_id in after_drawn:
            lost.append({"node_id": node_id, "before": row.get("best"),
                         "why": "drawn without a date"})
            continue
        target = follow(node_id, aliases)
        if target == node_id:
            lost.append({"node_id": node_id, "before": row.get("best"),
                         "why": "gone, and no alias redirects it"})
            continue
        if target not in after_placed:
            lost.append({"node_id": node_id, "before": row.get("best"),
                         "alias_target": target,
                         "why": "aliased at a node with no date"})
            continue
        if dates_are_compatible(row, after_placed[target]):
            continue
        if keeps_the_rival(after_nodes[target], row, items):
            continue
        lost.append({"node_id": node_id, "before": row.get("best"),
                     "alias_target": target,
                     "after": after_placed[target].get("best"),
                     "why": "aliased at an incompatible date, with the rival dropped"})
    return lost


def stale_aliases(projection: dict) -> list:
    """Keys of ``node_aliases`` the drawing still publishes as nodes.

    :data:`episode_fold.AN_ALIAS_NEVER_NAMES_A_NODE_THE_DRAWING_PUBLISHES`,
    checkable in one line. A key that is also a node id is the incident: a
    reader that follows the table lands on the merged node while the drawing
    keeps the old one beside it, undated, and the work-item seat re-asks the
    question the merged node answers.
    """
    published = drawn(projection)
    return sorted(key for key in (projection.get("node_aliases") or {})
                  if key in published)


def cards_about(projection: dict, node_id: str) -> list:
    return sorted(
        (item.get("prompt_intent") or "")
        for item in projection.get("work_items") or ()
        if (item.get("node_ref") or item.get("event_ref")) == node_id
    )


def date_cards(projection: dict) -> set:
    return {
        (item.get("node_ref"), item.get("prompt_intent"))
        for item in projection.get("work_items") or ()
        if item.get("requested_field") == "date"
    }


#: The kind of date card that ASKS WHICH of two readings the vault already holds
#: is right. It is the fold surfacing a contradiction, so a node that carries one
#: is not a node missing a date — the audit below counts the other kinds.
CHOOSING_CARD_KIND = "contradiction"


def asking_cards(projection: dict) -> set:
    """Date cards that ask for a date the vault does NOT have."""
    return {
        (item.get("node_ref"), item.get("prompt_intent"))
        for item in projection.get("work_items") or ()
        if item.get("requested_field") == "date"
        and item.get("kind") != CHOOSING_CARD_KIND
    }


#: The vaults the invariant below is asked on. A tuple of pairs rather than a
#: class attribute, so the set is one thing three tests read.
VAULTS = (
    ("the incident", brittney_claims),
    ("v340's own vault",
     lambda: [*yucaipa_claims(), owner_birth(), owner_age()]),
    ("both at once",
     lambda: [*brittney_claims(), *yucaipa_claims(), owner_birth(), owner_age()]),
)


class VaultCase(unittest.TestCase):
    """A vault on disk, published and bound through the real verbs only."""

    claims: tuple = ()
    prefix = "v342-"

    def setUp(self):
        self.root = root_parent_tmp(self, ROOT, prefix=self.prefix)
        write_vault(self.root, self.claims)

    def publish(self) -> dict:
        pub.publish(self.root, roster_snapshot=(), now=NOW, full=True)
        return pub.read_projection(self.root) or {}

    def bind(self) -> dict:
        return eb.bind_episodes(self.root, apply=True, now=NOW)


# --------------------------------------------------------------------------
# The incident, reproduced and fixed
# --------------------------------------------------------------------------


class AMergedNodeKeepsItsDateTests(VaultCase):
    """:data:`episode_fold.AN_ALIAS_NEVER_NAMES_A_NODE_THE_DRAWING_PUBLISHES`."""

    prefix = "v342-brittney-"

    def setUp(self):
        self.claims = brittney_claims()
        super().setUp()
        self.before = self.publish()
        self.outcome = self.bind()
        self.after = self.publish()

    # -- the fixture is the incident's own shape --------------------------

    def test_the_fixture_mints_the_incidents_own_node_id(self):
        """Not a coincidence worth leaving unstated: the owner's vault minted
        this id from this subject and this kind, so the repro is the same
        arithmetic and not a lookalike."""
        self.assertEqual(BRITTNEY_NODE, "node:883802c17ba32910522bb663")
        self.assertEqual(READING, "resolver:883802c17ba32910522bb663")
        self.assertEqual(placed(self.before)[BRITTNEY_NODE]["best"], BIRTHDAY)
        self.assertEqual(placed(self.before)[BRITTNEY_NODE]["basis"], "stated")

    def test_the_bind_takes_the_reading_and_leaves_the_whole_message_telling(self):
        """The seam, asserted rather than assumed. `R2b` joins the reading to
        the household sheet; the conversation telling is NOT a member, because
        it also says "Kristine 10" and "Dad graduated"."""
        groups = [set(group["members"]) for group in self.outcome["plan"].exact_groups]
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0], {READING, HOUSEHOLD})
        self.assertNotIn(CONVERSATION, groups[0])
        self.assertEqual(self.outcome["plan"].exact_groups[0]["rule_ids"],
                         (eb.RULE_ID_MILESTONE,))

    def test_the_alias_is_filed_for_the_node_the_reading_answered(self):
        """Law 5 did its half: the id the reading named is redirected."""
        self.assertEqual(
            (self.after.get("node_aliases") or {}).get(BRITTNEY_NODE),
            self.the_episode_node(),
        )

    # -- the fix ----------------------------------------------------------

    def the_episode_node(self) -> str:
        rows = [node_id for node_id in placed(self.after)
                if placed(self.after)[node_id]["best"] == BIRTHDAY]
        self.assertEqual(len(rows), 1, f"{BIRTHDAY} names {len(rows)} nodes")
        return rows[0]

    def test_the_date_survives_the_apply(self):
        """The whole point: the fact is still dated 17 December 1987, once."""
        self.assertTrue(dates_are_compatible(
            placed(self.before)[BRITTNEY_NODE],
            placed(self.after)[self.the_episode_node()],
        ))
        self.assertEqual(lost_placements(self.before, self.after), [])

    def test_the_old_id_is_no_longer_drawn(self):
        """A redirected id names no node, so a reader that follows the table
        and a reader that reads the drawing see the same one fact."""
        self.assertNotIn(BRITTNEY_NODE, drawn(self.after))
        self.assertEqual(stale_aliases(self.after), [])

    def test_the_leftover_claim_went_WITH_the_node(self):
        """Not merely hidden: the conversation's own claim is evidence ON the
        merged node. A fix that dropped it would have made the drawing tidier
        and the vault poorer."""
        merged = [node for node in self.after["nodes"]
                  if (node.get("id") or node.get("node_id")) == self.the_episode_node()]
        refs = set(merged[0].get("input_claim_refs") or ())
        leftover = [row["claim_id"] for row in self.claims
                    if row["source_ref"]["source_id"] == CONVERSATION
                    and row["event_mention"] == "Brittney born"]
        self.assertEqual(len(leftover), 1)
        self.assertIn(leftover[0], refs)

    def test_no_second_date_card_is_minted_for_a_fact_the_merge_dates(self):
        """The card the incident minted, and the count that showed it."""
        self.assertEqual(cards_about(self.after, BRITTNEY_NODE), [])
        self.assertNotIn(
            "When was Brittney born?",
            [item.get("prompt_intent") for item in self.after["work_items"]],
        )
        self.assertEqual(date_cards(self.after), date_cards(self.before))

    def test_the_other_two_facts_of_that_telling_are_untouched(self):
        """The carry follows ONE node's alias, never the telling: "Kristine 10"
        and "Dad graduated" keep their own nodes and their own open cards."""
        for mention in ("Kristine 10", "Dad graduated"):
            rows = [node for node in self.after["nodes"]
                    if node.get("label") == mention]
            self.assertEqual(len(rows), 1, mention)
            self.assertIsNone(rows[0].get("best_temporal_value"))

    def test_the_fold_says_out_loud_that_it_followed_the_alias(self):
        found = self.after.get("identity_diagnostics") or {}
        codes = [row.get("code") for row in found.get("findings") or ()]
        self.assertIn(ef.DIAGNOSTIC_ALIAS_FOLLOWED, codes)
        self.assertNotIn(ef.DIAGNOSTIC_ALIAS_CONTESTED, codes)

    def test_a_replay_changes_nothing(self):
        second = eb.bind_episodes(self.root, apply=True, now="2027-01-01T00:00:00Z")
        self.assertEqual(second["plan"].exact_groups, [])
        self.assertEqual(placed(self.publish()), placed(self.after))

    # -- the negative: the guard removed ---------------------------------

    def test_without_the_carry_the_node_loses_its_date_and_is_asked_again(self):
        """v341's fold, restored for one call. This is the run measured on the
        clone: the old id still drawn, undated, beside the merged node, with
        "When was Brittney born?" minted against it."""
        original = ef.EpisodeIdentity.carried_node_for
        ef.EpisodeIdentity.carried_node_for = lambda self, claim: ""
        try:
            lost = self.publish()
        finally:
            ef.EpisodeIdentity.carried_node_for = original
        self.assertIn(BRITTNEY_NODE, drawn(lost))
        self.assertNotIn(BRITTNEY_NODE, placed(lost))
        self.assertEqual(cards_about(lost, BRITTNEY_NODE), ["When was Brittney born?"])
        self.assertEqual(stale_aliases(lost), [BRITTNEY_NODE])
        self.assertEqual(
            [row["node_id"] for row in lost_placements(self.before, lost)],
            [BRITTNEY_NODE],
        )
        # …and the republish with the guard back restores it, so the loss is a
        # function of the rule and of nothing that was written to disk.
        self.assertEqual(placed(self.publish()), placed(self.after))


# --------------------------------------------------------------------------
# `carried_node_for`, as a unit
# --------------------------------------------------------------------------


class PlanningTheCarriesTests(unittest.TestCase):
    """:meth:`episode_fold.EpisodeIdentity.plan_carries`, without a vault."""

    def identity(self, aliases: dict, *, episode_of_node: dict | None = None,
                 active: dict | None = None) -> ef.EpisodeIdentity:
        found = ef.EpisodeIdentity()
        # An identity layer with nothing bound does no identity work at all,
        # which is CERT-11's own promise — so the unit has to say it is armed.
        found.active = active if active is not None else {"t": ()}
        # An empty seed means "derive the table", which is what the live fold
        # does — the episode rows below are part of that derivation.
        found._aliases = dict(aliases) if aliases else None
        found.episode_of_node = dict(episode_of_node or {})
        return found

    def reading(self, claim_id, key, episode_node="", bounds=None, telling="t") -> tuple:
        return (claim_id, telling, key, episode_node, bounds)

    def dated(self, text: str):
        return chrono.parse_edtf(text)

    def test_a_key_nobody_aliased_is_not_carried(self):
        found = self.identity({"node:a": "node:b"})
        self.assertEqual(found.plan_carries([self.reading("c", "node:z")]), {})

    def test_an_undated_leftover_follows_its_node(self):
        found = self.identity({})
        carried = found.plan_carries([
            self.reading("bound", "node:a", "node:b", self.dated("1987-12-17"),
                         telling="bound-telling"),
            self.reading("left", "node:a"),
        ])
        self.assertEqual(carried, {"left": "node:b"})
        self.assertEqual(found.node_aliases(), {"node:a": "node:b"})

    def test_a_chain_is_followed_to_its_end(self):
        found = self.identity({"node:a": "node:b", "node:b": "node:c"})
        self.assertEqual(found.plan_carries([self.reading("c1", "node:a")]),
                         {"c1": "node:c"})

    def test_a_cycle_is_refused_rather_than_looped(self):
        found = self.identity({"node:a": "node:b", "node:b": "node:a"})
        self.assertEqual(found.plan_carries([self.reading("c1", "node:a")]), {})

    def test_a_contradicting_date_stays_and_the_key_is_not_redirected(self):
        """The Etherfuse/Ridgeline bucket: one undiscriminated `job` id for two
        different jobs, seven years apart. Un-bucketing is what the bind is for,
        so the 2015 leftover keeps the id — and the id keeps no alias, because a
        redirect to one of two meanings is worse than none."""
        found = self.identity({})
        carried = found.plan_carries([
            self.reading("etherfuse", "node:a", "node:e", self.dated("2022-05"),
                         telling="landmark:entry-etherfuse"),
            self.reading("ridgeline", "node:a", "", self.dated("2015"),
                         telling="landmark:entry-ridgeline"),
        ])
        self.assertEqual(carried, {})
        self.assertEqual(found.node_aliases(), {})
        codes = [row["code"] for row in found.identity_diagnostics()["findings"]]
        self.assertIn(ef.DIAGNOSTIC_ALIAS_CONTESTED, codes)

    def test_an_agreeing_date_is_carried(self):
        found = self.identity({})
        carried = found.plan_carries([
            self.reading("bound", "node:a", "node:b", self.dated("1987-12-17"),
                         telling="one"),
            self.reading("left", "node:a", "", self.dated("1987"), telling="two"),
        ])
        self.assertEqual(carried, {"left": "node:b"})

    def test_a_key_two_episodes_claim_redirects_to_neither(self):
        """An id that means two things redirects to neither — never resolved by
        whichever claim the fold happened to read first."""
        found = self.identity({})
        found.plan_carries([
            self.reading("one", "node:a", "node:one"),
            self.reading("two", "node:a", "node:two"),
        ])
        self.assertEqual(found.node_aliases(), {})
        codes = [row["code"] for row in found.identity_diagnostics()["findings"]]
        self.assertIn(ef.DIAGNOSTIC_ALIAS_CONTESTED, codes)

    def test_a_not_same_telling_is_never_carried_in_by_the_back_door(self):
        """§6.1's negative outranks the table. The person has said this telling
        is not that episode, so the key stays its own — and stays unaliased."""
        found = self.identity(
            {"node:a": "node:b"},
            episode_of_node={"node:b": "episode:1"},
            active={"t": ({"relation": ef.NEGATIVE_RELATION,
                           "episode_id": "episode:1"},)},
        )
        self.assertEqual(found.plan_carries([self.reading("c", "node:a")]), {})
        self.assertEqual(found.node_aliases(), {})

    def test_a_not_same_about_ANOTHER_episode_does_not_block_the_carry(self):
        found = self.identity(
            {"node:a": "node:b"},
            episode_of_node={"node:b": "episode:1"},
            active={"t": ({"relation": ef.NEGATIVE_RELATION,
                           "episode_id": "episode:9"},)},
        )
        self.assertEqual(found.plan_carries([self.reading("c", "node:a")]),
                         {"c": "node:b"})

    def test_the_contract_s_own_alias_row_is_a_former_key_too(self):
        """A key I0 aliased from a claim's `event_ref` is followed even when no
        bound claim in this pass minted it."""
        found = self.identity({"node:a": "node:b"})
        self.assertEqual(found.plan_carries([self.reading("left", "node:a")]),
                         {"left": "node:b"})

    def test_an_absorbed_episodes_node_id_redirects_too(self):
        """The third way a node id moves. An episode's node id is derived FROM
        its episode id, so an episode that gains a member takes a new node id
        while every work item and URL still names the old one. On the owner's
        vault that is 68 rows and 61 of the placements a v341 apply looked to
        lose outright."""
        found = self.identity({})
        found.operations = ({"status": "active", "op": "create",
                             "episode_id": "episode:new",
                             "aliases_created": ["episode:old"]},)
        found.node_of_episode = {"episode:old": "node:old", "episode:new": "node:new"}
        self.assertEqual(found.episode_aliases(), {"episode:old": "episode:new"})
        self.assertEqual(found.node_aliases(), {"node:old": "node:new"})
        # …and the carry follows it like any other alias row.
        self.assertEqual(found.plan_carries([self.reading("c", "node:old")]),
                         {"c": "node:new"})

    def test_an_episode_the_projection_draws_no_node_for_adds_no_row(self):
        """A row is only a redirect when both ends are nodes the drawing has."""
        found = self.identity({})
        found.operations = ({"status": "active", "op": "create",
                             "episode_id": "episode:new",
                             "aliases_created": ["episode:old"]},)
        found.node_of_episode = {"episode:new": "node:new"}
        self.assertEqual(found.node_aliases(), {})

    def test_an_unarmed_identity_layer_carries_nothing(self):
        found = ef.EpisodeIdentity()
        self.assertFalse(found.applies)
        self.assertEqual(found.plan_carries([self.reading("c", "node:a")]), {})
        self.assertEqual(found.carried_node_for({"claim_id": "c"}), "")
        self.assertEqual(found.node_aliases(), {})


# --------------------------------------------------------------------------
# The invariant, over whole vaults
# --------------------------------------------------------------------------


class EveryPlacementSurvivesAnApplyTests(unittest.TestCase):
    """v340 stated as an invariant rather than as a list of named nodes.

    v340 proved the Yucaipa moves and the age placement by name. Naming them
    is what let this release's node through: nobody had asked the general
    question. So the general question is asked here, on every vault these
    tests build, and :func:`lost_placements` is the one definition of the
    answer.
    """

    vaults = VAULTS

    def run_vault(self, claims) -> tuple:
        root = root_parent_tmp(self, ROOT, prefix="v342-invariant-")
        shutil.rmtree(root, ignore_errors=True)
        root.mkdir(parents=True, exist_ok=True)
        write_vault(root, claims)
        pub.publish(root, roster_snapshot=(), now=NOW, full=True)
        before = pub.read_projection(root) or {}
        eb.bind_episodes(root, apply=True, now=NOW)
        pub.publish(root, roster_snapshot=(), now=NOW, full=True)
        return before, (pub.read_projection(root) or {})

    def test_no_apply_loses_a_placement(self):
        for name, build in self.vaults:
            with self.subTest(vault=name):
                before, after = self.run_vault(build())
                self.assertTrue(placed(before), "the vault placed nothing to lose")
                self.assertEqual(lost_placements(before, after), [])

    def test_no_alias_names_a_node_the_drawing_publishes(self):
        for name, build in self.vaults:
            with self.subTest(vault=name):
                _, after = self.run_vault(build())
                self.assertEqual(stale_aliases(after), [])

    def test_no_apply_mints_a_date_card_for_a_fact_it_just_dated(self):
        """The other half of the incident's cost: cards 51 → 46 hid one NEW
        one. A date card that appears for a node whose date the apply itself
        placed is the question the vault already answers."""
        for name, build in self.vaults:
            with self.subTest(vault=name):
                before, after = self.run_vault(build())
                aliases = dict(after.get("node_aliases") or {})
                placed_after = placed(after)
                for node_ref, intent in asking_cards(after) - asking_cards(before):
                    target = follow(node_ref, aliases) if node_ref else ""
                    self.assertNotIn(
                        target, placed_after,
                        f"{name}: {intent!r} asks for a date {target} carries",
                    )

    def test_without_the_carry_plan_two_dated_nodes_leave_with_nothing(self):
        """Both halves, seen failing at the one seat that decides them.

        `plan_carries` does two things, and the vault needs both: it FOLLOWS a
        re-keyed id so the leftover claim goes along (the incident's own node),
        and it publishes the alias for a key I0's contract cannot see — a
        telling whose claims carry no ``event_ref`` still HAD a node, the fold
        minted it and drew it, and the vault's work items and URLs point at it.
        With the whole plan removed, the household sheet's own dated node leaves
        generation two with nothing redirecting it, and "Brittney's birth" is
        drawn again without its date."""
        household_node = ident.derive_episode_ref(
            event_kind="birth", subject_ref="Brittney Mason", counterpart_ref=None)
        original = ef.EpisodeIdentity.plan_carries
        ef.EpisodeIdentity.plan_carries = lambda self, readings: {}
        try:
            before, after = self.run_vault(brittney_claims())
        finally:
            ef.EpisodeIdentity.plan_carries = original
        self.assertIn(household_node, placed(before))
        lost = {row["node_id"]: row["why"] for row in lost_placements(before, after)}
        self.assertEqual(lost, {
            BRITTNEY_NODE: "drawn without a date",
            household_node: "gone, and no alias redirects it",
        })
        # With the plan back, the same vault loses nothing and both ids redirect.
        before, after = self.run_vault(brittney_claims())
        self.assertEqual(lost_placements(before, after), [])
        aliases = after.get("node_aliases") or {}
        self.assertEqual(follow(household_node, aliases), follow(BRITTNEY_NODE, aliases))
        self.assertIn(follow(BRITTNEY_NODE, aliases), placed(after))

    def test_the_invariant_catches_the_incident(self):
        """The audit's own negative: with the carry removed, the vault that
        reproduced the incident fails it. An invariant nothing can fail is a
        comment."""
        original = ef.EpisodeIdentity.carried_node_for
        ef.EpisodeIdentity.carried_node_for = lambda self, claim: ""
        try:
            before, after = self.run_vault(brittney_claims())
        finally:
            ef.EpisodeIdentity.carried_node_for = original
        self.assertEqual([row["node_id"] for row in lost_placements(before, after)],
                         [BRITTNEY_NODE])
        self.assertEqual(stale_aliases(after), [BRITTNEY_NODE])


class TheAuditReadsAProjectionTests(unittest.TestCase):
    """:func:`lost_placements` itself, so the invariant's own arithmetic is not
    taken on trust: a narrowing passes, a move fails, an undated ghost fails."""

    def projection(self, nodes, aliases=None) -> dict:
        return {"nodes": nodes, "node_aliases": dict(aliases or {}), "work_items": []}

    def node(self, node_id, best=None) -> dict:
        row = {"id": node_id}
        if best:
            row["best_temporal_value"] = {
                "best": best, "earliest": best.split("/")[0],
                "latest": best.split("/")[-1], "granularity": "range",
                "basis": "stated", "confidence": "certain",
            }
        return row

    def test_a_node_that_kept_its_date_is_no_loss(self):
        before = self.projection([self.node("node:a", "1981-07-11")])
        self.assertEqual(lost_placements(before, before), [])

    def test_a_rekey_to_the_same_date_is_no_loss(self):
        before = self.projection([self.node("node:a", "1987-12-17")])
        after = self.projection([self.node("node:b", "1987-12-17")],
                                {"node:a": "node:b"})
        self.assertEqual(lost_placements(before, after), [])

    def test_a_rekey_that_NARROWS_the_window_is_no_loss(self):
        before = self.projection([self.node("node:a", "1986-06/1988-06")])
        after = self.projection([self.node("node:b", "1987-12-17")],
                                {"node:a": "node:b"})
        self.assertEqual(lost_placements(before, after), [])

    def test_a_chain_of_rekeys_is_followed(self):
        before = self.projection([self.node("node:a", "1987-12-17")])
        after = self.projection([self.node("node:c", "1987-12-17")],
                                {"node:a": "node:b", "node:b": "node:c"})
        self.assertEqual(lost_placements(before, after), [])

    def test_an_undated_ghost_at_the_aliased_id_is_a_loss(self):
        """The incident's own shape, and the one a same-date check misses."""
        before = self.projection([self.node("node:a", "1987-12-17")])
        after = self.projection(
            [self.node("node:a"), self.node("node:b", "1987-12-17")],
            {"node:a": "node:b"},
        )
        lost = lost_placements(before, after)
        self.assertEqual([row["node_id"] for row in lost], ["node:a"])
        self.assertEqual(lost[0]["why"], "drawn without a date")
        self.assertEqual(stale_aliases(after), ["node:a"])

    def test_a_merge_onto_a_contradicting_date_is_a_loss(self):
        """v340's Yucaipa half, in the audit's own vocabulary: an alias is not
        a licence to move a moment 32 years."""
        before = self.projection([self.node("node:a", "1981-07-11/1982-07")])
        after = self.projection([self.node("node:b", "2013-06/2014-06")],
                                {"node:a": "node:b"})
        lost = lost_placements(before, after)
        self.assertEqual(lost[0]["why"],
                         "aliased at an incompatible date, with the rival dropped")

    def test_a_merge_that_keeps_the_rival_and_asks_is_no_loss(self):
        """v340's own exception, guarded so it is an exception and not a hole:
        `R2b` folds the owner's duplicate births and the merged node may carry
        the other reading's date — as long as this one is still an alternate AND
        a `contradiction` card asks which is right."""
        before = self.projection([self.node("node:a", "2020")])
        merged = self.node("node:b", "2021-10-11")
        merged["alternate_values"] = [{"best": "2020", "earliest": "2020",
                                       "latest": "2020", "granularity": "year",
                                       "basis": "stated", "confidence": "certain"}]
        after = self.projection([merged], {"node:a": "node:b"})
        after["work_items"] = [{
            "kind": "contradiction", "requested_field": "date", "node_ref": "node:b",
            "prompt_intent": "Two dates are claimed for your birth — "
                             "11 October 2021 and 2020. Which is right?",
        }]
        self.assertEqual(lost_placements(before, after), [])
        # …and it is the SURFACING that earns it: drop the alternate, or drop the
        # card, and the same merge is a silent loss again.
        without_alternate = self.projection([self.node("node:b", "2021-10-11")],
                                            {"node:a": "node:b"})
        without_alternate["work_items"] = after["work_items"]
        self.assertTrue(lost_placements(before, without_alternate))
        without_card = self.projection([merged], {"node:a": "node:b"})
        self.assertTrue(lost_placements(before, without_card))

    def test_a_vanished_node_with_no_alias_is_a_loss(self):
        before = self.projection([self.node("node:a", "1987-12-17")])
        after = self.projection([self.node("node:b", "1987-12-17")])
        self.assertEqual([row["why"] for row in lost_placements(before, after)],
                         ["gone, and no alias redirects it"])

    def test_an_alias_to_an_undated_node_is_a_loss(self):
        before = self.projection([self.node("node:a", "1987-12-17")])
        after = self.projection([self.node("node:b")], {"node:a": "node:b"})
        self.assertEqual([row["why"] for row in lost_placements(before, after)],
                         ["aliased at a node with no date"])

    def test_a_cycle_in_the_table_is_a_loss_and_never_a_hang(self):
        before = self.projection([self.node("node:a", "1987-12-17")])
        after = self.projection([self.node("node:b")],
                                {"node:a": "node:b", "node:b": "node:a"})
        self.assertTrue(lost_placements(before, after))


class DeterminismTests(VaultCase):
    """One vault, two orders, one drawing."""

    prefix = "v342-determinism-"

    def test_the_carry_does_not_depend_on_claim_order(self):
        import random

        claims = brittney_claims()
        shuffled = list(claims)
        random.Random(342).shuffle(shuffled)
        left = self._run(claims)
        right = self._run(shuffled)
        self.assertEqual(left, right)

    def _run(self, claims) -> tuple:
        root = root_parent_tmp(self, ROOT, prefix="v342-order-")
        shutil.rmtree(root, ignore_errors=True)
        root.mkdir(parents=True, exist_ok=True)
        write_vault(root, claims)
        pub.publish(root, roster_snapshot=(), now=NOW, full=True)
        eb.bind_episodes(root, apply=True, now=NOW)
        pub.publish(root, roster_snapshot=(), now=NOW, full=True)
        found = pub.read_projection(root) or {}
        return (sorted(placed(found).items()),
                sorted((found.get("node_aliases") or {}).items()))


class TheRuleIsWrittenDownOnceTests(unittest.TestCase):
    def test_the_law_names_the_claim_and_the_table(self):
        text = ef.AN_ALIAS_NEVER_NAMES_A_NODE_THE_DRAWING_PUBLISHES
        for word in ("claim", "re-keys", "node_aliases"):
            self.assertIn(word, text)

    def test_the_fold_reads_the_identity_layers_own_method(self):
        """One definition, one reader: `temporal_timeline` asks the identity
        layer and holds no alias arithmetic of its own."""
        source = (ROOT / "system" / "temporal_timeline.py").read_text(encoding="utf-8")
        self.assertIn("identity.carried_node_for(claim)", source)
        self.assertIn("identity.plan_carries(", source)
        self.assertNotIn("_alias_table", source)


if __name__ == "__main__":
    unittest.main()
