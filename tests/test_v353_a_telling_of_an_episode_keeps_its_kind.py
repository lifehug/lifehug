"""v353 — a telling of an episode keeps its kind, and a bad node never stops the drawing.

THE INCIDENT (the owner's own vault, on staging, framework v352 already pinned
and live when it was found; the daily maintenance scheduler was paused to keep
the broken path off his vault while this shipped).

v352's `place-answers` read 28 promoted answers carrying a card, placed one from
the recency reading and filed 7 as ``telling_only``. One of those seven was his
reply *"This happened in the middle of sixth grade for James."*
(``sources/conversations/msg-3737a80061e5fd4938204b9b.md``, work item
``work:2f5dec9f0e57ad5a31b9947a``), filed as an ``occurrence`` on
``node:22784323839a0481b081ceab`` — *"James Everett moved between baseball
teams"*. That node is an EPISODE: ``episode:59ae397ae9edf8b6719355f7``, created
deterministically over two classification tellings, canonical kind ``moment``,
one of its tellings' claims still in the index. The next
``temporal_publication.publish`` RAISED::

    temporal_projection.TimelineNodeError: episode_block_on_non_episode_node:
    node:22784323839a0481b081ceab carries an episode_id but its node_kind is 'event'

and drew NOTHING. Not one bad node — no projection at all, which on the hosted
platform parks the compile job and stops the vault updating for everything.

TWO THINGS WERE WRONG.

**The kind was read off the wrong thing.** `temporal_timeline._group_claims`
created the group for that node id from the first claim it read and asked THAT
CLAIM whether a bind had put it in an episode. The answer's telling is bound to
nothing — no rung has looked at it, and `answer_placement` is a claim filer and
not an identity decider — so the group was made an ``event``, and it was that
claim which created the group only because its id sorts first
(``claim:cb8c3d…`` before ``claim:d7232e…``; `temporal_store.active_claims` is
in claim-id order). `episode_fold.EpisodeIdentity.node_block` then read the
PUBLISHED episode↔node map, which knows nothing about claim order, and stamped
the episode block on it. Two readings of *"is this node an episode?"* — one per
claim, one per node — disagreeing about a node whose id was MINTED with
``node_kind: episode`` inside its own digest. v353: there is ONE reading
(:meth:`episode_fold.EpisodeIdentity.episode_of`), it is asked of the NODE ID,
and both the grouping and the episode block go through it
(`episode_fold.AN_EPISODE_NODES_KIND_IS_THE_NODES_AND_NOT_ITS_FIRST_CLAIMS`).

**And the writer is right as it stands.** A telling of an episode is not
refused: the reply really is another telling of that episode, which is exactly
the unit `answer_placement.answer_telling_ref` already mints, and the repeat
kinds are where *"when did X happen?"* cards cluster, so a refusal would drop
the owner's answers for the commonest card class there is. What the writer must
not do is argue with the node about what it is — and it does not, because
`answer_placement.answer_claim` takes ``event_kind`` from the CARD's node, which
for an episode is that episode's own canonical kind.

**Nothing may take `publish` down for a whole vault over one node's shape.**
`temporal_timeline._node_dict_or_finding` repairs exactly the one class a
legitimately filed claim can provoke and reports
`temporal_timeline.DIAGNOSTIC_EPISODE_NODE_REDRAWN`, the way
`landmark_projection`'s refusals and v340's ``owner_birth_anchor_ambiguous``
report rather than raise. Every other member of
`temporal_projection.ERROR_CODES` still stops the drawing, because those mean
the fold computed something it cannot explain.

The fixture is synthetic and its ids are the owner's own — content addressing
means an episode built from the same two telling refs about the same subject
mints ``episode:59ae397ae9edf8b6719355f7``, is drawn at
``node:22784323839a0481b081ceab``, carries ``work:2f5dec9f0e57ad5a31b9947a`` and
receives ``claim:cb8c3d3dd46438ea6a76720d`` from that reply. Nothing here reads
his vault.

Every negative below was run against a build with its guard removed and SEEN
failing first; the reproduction was seen raising the exception above before any
fix existed.
"""

from __future__ import annotations

import hashlib
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "system"))
sys.path.insert(0, str(ROOT / "tests"))

import answer_placement as ap  # noqa: E402
import chronology as chrono  # noqa: E402
import episode_fold as ef  # noqa: E402
import episode_fold_contract as efc  # noqa: E402
import event_identity as ei  # noqa: E402
import temporal_claims as tc  # noqa: E402
import temporal_projection as tp  # noqa: E402
import temporal_publication as pub  # noqa: E402
import temporal_store as ts  # noqa: E402
import temporal_timeline as tt  # noqa: E402
from tempdirs import root_parent_tmp  # noqa: E402
from test_v340_apply_keeps_placements import NOW, write_vault  # noqa: E402
from test_v345_a_telling_of_a_landmark_folds_onto_it import (  # noqa: E402
    placement_audit,
)

# --------------------------------------------------------------------------
# The owner's own episode, rebuilt from what made it rather than copied
# --------------------------------------------------------------------------

#: His son. The node's subject, and the claim's, and the card's.
SUBJECT = "person/james-everett-taylor"
#: The label on the node and on the card the answer was filed against.
LABEL = "James Everett moved between baseball teams"
#: The two classification tellings `bind-episodes` created the episode over.
#: ``TOLD``'s claim is still in his active index; ``DORMANT``'s is not, which is
#: why the drawn node reads ``telling_count: 1`` against a two-member episode.
TOLD = "classification:answers-c20#6b9a4a640d1f"
DORMANT = "classification:answers-c20#007c24a07d01"
#: What content addressing then mints, on his vault and on this fixture alike.
EPISODE = "episode:59ae397ae9edf8b6719355f7"
EPISODE_NODE = "node:22784323839a0481b081ceab"
CARD = "work:2f5dec9f0e57ad5a31b9947a"
#: His reply, verbatim, and the claim id it produces.
REPLY = "This happened in the middle of sixth grade for James."
CAPTURED = "2026-09-24T01:09:30Z"
ANSWER_CLAIM = "claim:cb8c3d3dd46438ea6a76720d"

#: The revision of the classification the told claim comes from. A content hash
#: of a document this fixture does not have, so it is a seed — and the seed is
#: CHOSEN, because the defect only fires when the answer's claim id sorts ahead
#: of the bound claim's (the index is in claim-id order, and on his vault
#: ``claim:cb8c3d…`` came before ``claim:d7232e…``). That ordering is asserted
#: below rather than assumed, so a future change to the claim digest fails this
#: file loudly instead of quietly folding the defect away.
TOLD_REVISION = "sha256:" + hashlib.sha256(
    b"the classification the owner's vault holds").hexdigest()


def told_claim() -> dict:
    """The classification's own ``occurrence`` — the one input the episode node
    had before the answer arrived, carrying the ``event_ref`` the classifier
    froze rather than the episode's id."""
    return tc.validate_temporal_claim({
        "source_kind": "conversation",
        "source_ref": {"source_id": TOLD, "revision": TOLD_REVISION},
        "evidence": [{"quote": "James repeatedly moved between baseball teams"}],
        "extractor_version": "classifier-claims/rule:5",
        "created_at": "2026-01-01T00:00:00Z",
        "basis": "explicit",
        "confidence": 0.9,
        "status": "active",
        "claim_type": tc.OCCURRENCE_CLAIM_TYPE,
        "subject_mention": SUBJECT,
        "event_kind": "moment",
        "event_mention": LABEL,
        "event_ref": tp.derive_node_id(node_kind="event", event_kind="moment",
                                       subject_refs=[SUBJECT], discriminator=LABEL),
    })


def episode_plan() -> dict:
    """The deterministic `create` over the two tellings, as `episode_binder`
    files one: one operation, one ``same`` binding per member."""
    members = tuple(sorted((TOLD, DORMANT)))
    operation_id = ei.operation_digest(
        authority="deterministic", op="create",
        rule_version=ei.IDENTITY_RULE_VERSION, member_refs=members,
    )
    episode_id = ei.episode_id_for(operation_id)
    bindings = [{"telling_ref": ref, "episode_id": episode_id, "relation": "same",
                 "origin": "deterministic", "rule_id": "R2",
                 "operation_id": operation_id, "created_at": NOW}
                for ref in members]
    return {
        "members": members,
        "operation_id": operation_id,
        "episode_id": episode_id,
        "bindings": bindings,
        "binding_ids": [ei.validate_event_identity(row)["identity_id"]
                        for row in bindings],
    }


class EpisodeVault:
    """A synthetic vault holding ONE episode with a card on it, published by the
    real minter so the question, the node and the card id are the ones his vault
    carries rather than hand-written fixtures."""

    def __init__(self, test: unittest.TestCase, *, records: bool = True):
        self.root = root_parent_tmp(test, ROOT, prefix="lifehug-v353-")
        for folder in ("state/temporal_claims", "sources/conversations"):
            (self.root / folder).mkdir(parents=True, exist_ok=True)
        write_vault(self.root, [told_claim()])
        self.plan = episode_plan()
        if records:
            ei.file_episode_operation(
                self.root, authority="deterministic", op="create",
                episode_id=self.plan["episode_id"], members=list(self.plan["members"]),
                creates_binding_ids=self.plan["binding_ids"],
                canonical_event_kind="moment", created_at=NOW,
            )
            for row in self.plan["bindings"]:
                ei.file_event_identity(self.root, **row)
        self.publish()

    def publish(self, *, now: str = NOW) -> None:
        ts.rebuild_active_index(self.root)
        ei.rebuild_telling_manifest(self.root)
        pub.publish(self.root, now=now)

    def nodes(self) -> dict[str, dict]:
        payload = pub.read_projection(self.root) or {}
        return {row["node_id"]: row for row in payload.get("nodes") or ()
                if isinstance(row, dict) and row.get("node_id")}

    def work_items(self) -> list[dict]:
        payload = pub.read_work_items(self.root) or {}
        return [row for row in payload.get("work_items") or ()
                if isinstance(row, dict)]

    def card(self) -> dict:
        """The one open card asking when this moment happened — found by the
        question, so a vault WITHOUT the identity records (where the same
        tellings are drawn at their own minted id) finds its own card."""
        rows = [row for row in self.work_items()
                if LABEL in (row.get("prompt_intent") or "")]
        assert len(rows) == 1, f"{LABEL!r} carries {len(rows)} cards"
        return rows[0]

    def cards_by_kind(self) -> dict[str, int]:
        found: dict[str, int] = {}
        for row in self.work_items():
            found[row.get("kind") or "?"] = found.get(row.get("kind") or "?", 0) + 1
        return found

    def answer(self, reply: str = REPLY, *, captured: str = CAPTURED):
        """Promote the reply exactly as the platform's promote-message driver
        does, with the session that names this card."""
        return ts.promote_conversational_source(self.root, reply, {
            "session_ref": f"conversation:cand:work_item:{self.card()['work_item_id']}",
            "turn_ref": "0", "speaker": "person", "occurred_at": captured})

    def claim_ids(self) -> list[str]:
        return [row.get("claim_id")
                for row in ts.fold_active_index(self.root).get("claims") or ()]

    def derived(self) -> object:
        return tt.derive_calculated_timeline(
            ts.fold_active_index(self.root),
            episode_records=ef.load_episode_records(self.root), now=NOW,
        )


def findings(result) -> list[dict]:
    return list(result.diagnostics.get("findings") or ())


# --------------------------------------------------------------------------
# 1. The fixture is the owner's own episode and his own card
# --------------------------------------------------------------------------

class TheFixtureIsTheOwnersOwnEpisodeTests(unittest.TestCase):
    """Content addressing, used as the evidence it is: the same two telling refs
    about the same subject mint the same episode, node and card he answered."""

    def setUp(self):
        self.vault = EpisodeVault(self)

    def test_the_episode_and_its_node_are_the_owners_own_ids(self):
        self.assertEqual(self.vault.plan["episode_id"], EPISODE)
        self.assertEqual(
            efc.episode_node_id(canonical_event_kind="moment",
                                subject_keys=ef.EPISODE_SUBJECT_KEYS,
                                episode_id=EPISODE),
            EPISODE_NODE,
        )

    def test_the_node_is_an_episode_before_anybody_answers(self):
        node = self.vault.nodes()[EPISODE_NODE]
        self.assertEqual(node["node_kind"], "episode")
        self.assertEqual(node["event_kind"], "moment")
        self.assertEqual(node["episode_id"], EPISODE)
        self.assertEqual(node["label"], LABEL)
        self.assertIsNone(node["best_temporal_value"])
        self.assertEqual(node["input_claim_refs"], [told_claim()["claim_id"]])

    def test_the_card_is_the_owners_own_card(self):
        card = self.vault.card()
        self.assertEqual(card["work_item_id"], CARD)
        self.assertEqual(card["state"], "open")
        self.assertEqual(
            card["prompt_intent"],
            f"When did {LABEL} happen?",
        )

    def test_the_episode_node_id_carries_the_kind_inside_its_digest(self):
        """Why the repair is arithmetic and not a guess: the id itself says what
        the node is."""
        identity = efc.episode_node_identity(
            canonical_event_kind="moment",
            subject_keys=ef.EPISODE_SUBJECT_KEYS, episode_id=EPISODE)
        self.assertEqual(identity["node_kind"], "episode")
        self.assertIn("node_kind", tp.NODE_IDENTITY_KEYS)


# --------------------------------------------------------------------------
# 2. The reproduction: the answer lands, and the publish used to die
# --------------------------------------------------------------------------

class AnAnswerToAnEpisodesCardTests(unittest.TestCase):
    """The whole act, end to end, through the real verb and the real publish."""

    def setUp(self):
        self.vault = EpisodeVault(self)
        self.before = self.vault.derived()
        self.cards_before = self.vault.cards_by_kind()
        self.vault.answer()
        self.report = ap.place_answers(self.vault.root, now=NOW)

    def test_the_reply_files_as_a_telling_of_the_episodes_node(self):
        self.assertEqual(self.report["answers"], 1)
        self.assertEqual(self.report["tellings"], 1)
        self.assertEqual(self.report["placed"], 0)
        self.assertEqual(self.report["by_reading"][ap.READING_TELLING], 1)
        self.assertEqual(self.report["errors"], [])
        self.assertEqual(
            [(row["claim_id"], row["node_ref"], row["reading"])
             for row in self.report["filed"]],
            [(ANSWER_CLAIM, EPISODE_NODE, ap.READING_TELLING)],
        )

    def test_an_episode_target_is_not_refused(self):
        """The writer's decision, pinned: no refusal names an episode target, and
        none of the five fires here."""
        self.assertEqual(sum(self.report["refused"].values()), 0)
        self.assertNotIn("episode", " ".join(ap.REFUSALS))

    def test_the_claim_never_argues_with_the_node_about_what_it_is(self):
        """`answer_claim` takes the kind from the CARD's node, so the episode's
        own canonical kind is what the claim carries."""
        filed = [row for row in ts.fold_active_index(self.vault.root)["claims"]
                 if row.get("claim_id") == ANSWER_CLAIM]
        self.assertEqual(len(filed), 1)
        self.assertEqual(filed[0]["event_kind"], "moment")
        self.assertEqual(filed[0]["event_ref"], EPISODE_NODE)
        self.assertEqual(filed[0]["subject_mention"], SUBJECT)
        self.assertEqual(filed[0]["claim_type"], tc.OCCURRENCE_CLAIM_TYPE)

    def test_the_answers_claim_id_really_does_sort_first(self):
        """The defect's own condition, asserted rather than assumed: the index is
        in claim-id order, and the answer's claim is the one that creates the
        group."""
        ids = self.vault.claim_ids()
        self.assertEqual(ids, sorted(ids))
        self.assertEqual(ids[0], ANSWER_CLAIM)

    def test_the_publish_succeeds_and_the_node_keeps_its_kind(self):
        """The reproduction: on v352 this raised
        ``episode_block_on_non_episode_node`` and published nothing."""
        self.vault.publish(now="2026-09-25T12:00:00Z")
        node = self.vault.nodes()[EPISODE_NODE]
        self.assertEqual(node["node_kind"], "episode")
        self.assertEqual(node["episode_id"], EPISODE)
        self.assertEqual(node["event_kind"], "moment")
        self.assertEqual(node["label"], LABEL)

    def test_the_owners_words_are_on_the_node(self):
        self.vault.publish(now="2026-09-25T12:00:00Z")
        node = self.vault.nodes()[EPISODE_NODE]
        self.assertIn(ANSWER_CLAIM, node["input_claim_refs"])
        self.assertEqual(len(node["input_claim_refs"]), 2)

    def test_the_answers_telling_is_declared_and_not_bound(self):
        """Binding is `episode_binder`'s decision under Law 6, never a claim
        filer's: the telling is a published input, and the episode's member list
        is untouched."""
        self.vault.publish(now="2026-09-25T12:00:00Z")
        node = self.vault.nodes()[EPISODE_NODE]
        self.assertEqual(node["tellings"], [TOLD])
        self.assertEqual(node["telling_count"], 1)
        self.assertEqual(node["identity_origins"], ["deterministic"])

    def test_the_card_stays_open_because_nobody_said_when(self):
        self.vault.publish(now="2026-09-25T12:00:00Z")
        self.assertEqual(self.vault.card()["state"], "open")

    def test_the_drawing_reports_no_finding_for_an_ordinary_telling(self):
        """A telling of an episode is a normal thing for a person to file, so it
        is not an anomaly and the fold says nothing about it."""
        after = self.vault.derived()
        self.assertEqual(
            [row for row in findings(after)
             if row.get("finding") == tt.DIAGNOSTIC_EPISODE_NODE_REDRAWN],
            [],
        )

    def test_the_placement_audit_is_empty_over_the_whole_act(self):
        """v340/v342: nothing placed is lost, no dated moment moves, no node is
        drawn at an aliased id."""
        self.assertEqual(
            placement_audit(self.before, self.vault.derived()),
            {"lost": [], "drawn_at_an_alias": [], "moved": []},
        )

    def test_the_cards_by_kind_are_unchanged_by_a_telling(self):
        self.vault.publish(now="2026-09-25T12:00:00Z")
        self.assertEqual(self.vault.cards_by_kind(), self.cards_before)

    def test_filing_twice_files_nothing_twice(self):
        again = ap.place_answers(self.vault.root, now=NOW)
        self.assertEqual([row["claim_id"] for row in again["filed"]], [ANSWER_CLAIM])
        self.vault.publish(now="2026-09-25T12:00:00Z")
        self.assertEqual(
            len(self.vault.nodes()[EPISODE_NODE]["input_claim_refs"]), 2)


class ADatedAnswerPlacesTheEpisodeTests(unittest.TestCase):
    """The other half of the same card: a reply that DOES carry a time places the
    episode, and placing it does not change what it is either."""

    def setUp(self):
        self.vault = EpisodeVault(self)
        self.before = self.vault.derived()
        self.vault.answer("March 1998")
        self.report = ap.place_answers(self.vault.root, now=NOW)
        self.vault.publish(now="2026-09-25T12:00:00Z")

    def test_the_episode_is_placed_from_the_date_he_typed(self):
        self.assertEqual(self.report["placed"], 1)
        self.assertEqual(self.report["by_reading"][ap.READING_DATE], 1)
        node = self.vault.nodes()[EPISODE_NODE]
        self.assertEqual(node["best_temporal_value"]["best"], "1998-03")
        self.assertEqual(node["node_kind"], "episode")
        self.assertEqual(node["episode_id"], EPISODE)

    def test_the_precision_gap_card_closes(self):
        self.assertEqual(
            [row for row in self.vault.work_items()
             if row.get("node_ref") == EPISODE_NODE and row.get("state") == "open"],
            [],
        )

    def test_the_audit_is_empty(self):
        self.assertEqual(
            placement_audit(self.before, self.vault.derived()),
            {"lost": [], "drawn_at_an_alias": [], "moved": []},
        )


# --------------------------------------------------------------------------
# 3. One reading of "is this node an episode?"
# --------------------------------------------------------------------------

class OneReadingOfWhetherANodeIsAnEpisodeTests(unittest.TestCase):
    """`AN_EPISODE_NODES_KIND_IS_THE_NODES_AND_NOT_ITS_FIRST_CLAIMS`, as the two
    readers that used to disagree."""

    def setUp(self):
        self.vault = EpisodeVault(self)
        self.vault.answer()
        ap.place_answers(self.vault.root, now=NOW)
        index = ts.fold_active_index(self.vault.root)
        self.claims = index["claims"]
        self.identity = ef.EpisodeIdentity(
            self.claims, ef.load_episode_records(self.vault.root))

    def test_the_node_id_names_its_episode(self):
        self.assertEqual(self.identity.episode_of(EPISODE_NODE), EPISODE)

    def test_a_node_the_identity_layer_never_made_names_none(self):
        self.assertEqual(self.identity.episode_of("node:" + "0" * 24), "")
        self.assertEqual(self.identity.episode_of(None), "")

    def test_the_bind_and_the_node_are_two_different_questions(self):
        """The answer's claim is bound to nothing AND its node is an episode.
        Reading the second off the first is what v353 fixed."""
        answer = next(row for row in self.claims if row["claim_id"] == ANSWER_CLAIM)
        self.assertEqual(self.identity.episode_node_for(answer), "")
        self.assertEqual(self.identity.episode_of(answer["event_ref"]), EPISODE)

    def test_the_episode_block_reads_the_same_seat(self):
        block = self.identity.node_block(EPISODE_NODE, self.claims)
        self.assertEqual(block["episode_id"], self.identity.episode_of(EPISODE_NODE))

    def test_a_vault_with_no_records_reads_no_episode_anywhere(self):
        """CERT-11: delete the layer and the drawing returns. `episode_of` is
        gated on the same `active` flag `node_block` is."""
        bare = ef.EpisodeIdentity(self.claims, ())
        self.assertFalse(bare.applies)
        self.assertEqual(bare.episode_of(EPISODE_NODE), "")
        self.assertEqual(bare.node_block(EPISODE_NODE, self.claims), {})

    def test_without_the_records_the_node_is_not_an_episode_at_all(self):
        plain = EpisodeVault(self, records=False)
        plain.answer()
        ap.place_answers(plain.root, now=NOW)
        plain.publish(now="2026-09-25T12:00:00Z")
        drawn = [row for row in plain.nodes().values() if row["label"] == LABEL]
        self.assertTrue(drawn)
        for node in drawn:
            self.assertEqual(node["node_kind"], "event")
            self.assertIsNone(node.get("episode_id"))


# --------------------------------------------------------------------------
# 4. The drawing fails SOFT for this one class and for no other
# --------------------------------------------------------------------------

class ABadShapeNeverStopsTheDrawingTests(unittest.TestCase):
    """`publish` raising is not one bad node: on the hosted platform it parks the
    compile job and the vault stops updating for everything. So the one class a
    legitimately filed claim can provoke is repaired and REPORTED, following
    `landmark_projection`'s refusals and v340's `owner_birth_anchor_ambiguous`.
    """

    def group(self, kind: str = "event") -> dict:
        claim = told_claim()
        return {"node_id": EPISODE_NODE, "event_kind": "moment", "node_kind": kind,
                "subject": SUBJECT, "subjects": [SUBJECT], "resolved": True,
                "claims": [claim]}

    def draw(self, group: dict, identity: dict, diagnostics: list) -> dict:
        return tt._node_dict_or_finding(
            group, {"alternates": (), "conflict": 0.0},
            diagnostics=diagnostics, best=None, extra_alternates=(),
            extra_claim_refs=(), contradicted=False, constraint_refs=(),
            label=LABEL, generation=1, identity=identity,
        )

    def test_the_declared_finding_id_is_the_one_the_projection_refuses(self):
        self.assertEqual(tp.EPISODE_BLOCK_ON_NON_EPISODE_NODE,
                         "episode_block_on_non_episode_node")
        self.assertIn(tp.EPISODE_BLOCK_ON_NON_EPISODE_NODE, tp.ERROR_CODES)

    def test_an_episode_block_on_a_non_episode_node_is_drawn_correctly(self):
        diagnostics: list = []
        node = self.draw(self.group(), {"episode_id": EPISODE, "tellings": [TOLD],
                                        "telling_count": 1,
                                        "identity_origins": ["deterministic"]},
                         diagnostics)
        self.assertEqual(node["node_kind"], "episode")
        self.assertEqual(node["episode_id"], EPISODE)

    def test_it_says_so_by_name(self):
        diagnostics: list = []
        self.draw(self.group(), {"episode_id": EPISODE, "tellings": [TOLD],
                                 "telling_count": 1,
                                 "identity_origins": ["deterministic"]},
                  diagnostics)
        self.assertEqual(diagnostics, [{
            "finding": tt.DIAGNOSTIC_EPISODE_NODE_REDRAWN,
            "node_id": EPISODE_NODE,
            "episode_id": EPISODE,
            "drawn_as": "event",
        }])

    def test_an_episode_group_is_drawn_and_reported_about_at_all(self):
        diagnostics: list = []
        node = self.draw(self.group("episode"),
                         {"episode_id": EPISODE, "tellings": [TOLD],
                          "telling_count": 1,
                          "identity_origins": ["deterministic"]}, diagnostics)
        self.assertEqual(node["node_kind"], "episode")
        self.assertEqual(diagnostics, [])

    def test_every_other_invalid_shape_still_stops_the_drawing(self):
        """Narrow by design: the rest of `ERROR_CODES` means the fold computed
        something it cannot explain, and swallowing those would publish a
        drawing nobody can trust."""
        diagnostics: list = []
        with self.assertRaises(tp.TimelineNodeError) as caught:
            self.draw(self.group("episode"),
                      {"episode_id": EPISODE, "tellings": [TOLD, DORMANT],
                       "telling_count": 1,
                       "identity_origins": ["deterministic"]}, diagnostics)
        self.assertEqual(caught.exception.code, "telling_count_disagrees")
        self.assertEqual(diagnostics, [])

    def test_the_repair_never_hides_a_second_bad_shape(self):
        """The repaired node is validated again, so a shape that is wrong in a
        second way still refuses — the belt repairs one class, it does not
        rubber-stamp a node."""
        diagnostics: list = []
        with self.assertRaises(tp.TimelineNodeError) as caught:
            self.draw(self.group(),
                      {"episode_id": EPISODE, "tellings": [TOLD, DORMANT],
                       "telling_count": 1,
                       "identity_origins": ["deterministic"]}, diagnostics)
        self.assertEqual(caught.exception.code, "telling_count_disagrees")
        self.assertEqual([row["finding"] for row in diagnostics],
                         [tt.DIAGNOSTIC_EPISODE_NODE_REDRAWN])

    def test_a_node_with_no_inputs_still_stops_the_drawing(self):
        diagnostics: list = []
        empty = {**self.group(), "claims": []}
        with self.assertRaises(tp.TimelineNodeError) as caught:
            self.draw(empty, None, diagnostics)
        self.assertEqual(caught.exception.code, "node_without_inputs")
        self.assertEqual(diagnostics, [])


# --------------------------------------------------------------------------
# 5. This release adds no derivation
# --------------------------------------------------------------------------

class TheDrawingRuleDoesNotMoveTests(unittest.TestCase):
    """`CALCULATION_RULE_VERSION` stays where v352 left it. Every input the new
    branch touches used to produce NO drawing at all — an exception — so no
    vault whose head has not moved draws anything different, and no golden
    moves."""

    def test_the_calculation_rule_version_is_unchanged(self):
        self.assertEqual(tt.CALCULATION_RULE_VERSION, "timeline-rules:17")

    def test_a_vault_nobody_answered_draws_exactly_what_it_drew(self):
        vault = EpisodeVault(self)
        first = vault.derived()
        vault.publish(now="2026-09-25T12:00:00Z")
        second = vault.derived()
        self.assertEqual([row["node_id"] for row in first.nodes],
                         [row["node_id"] for row in second.nodes])
        for was, now in zip(first.nodes, second.nodes, strict=True):
            self.assertEqual(was["node_kind"], now["node_kind"])
            self.assertEqual(was["input_fingerprint"], now["input_fingerprint"])
            self.assertEqual(
                chrono.display_date(chrono.from_dict(was.get("best_temporal_value")),
                                    with_basis=False),
                chrono.display_date(chrono.from_dict(now.get("best_temporal_value")),
                                    with_basis=False),
            )

    def test_the_rule_is_named_once_and_read_from_there(self):
        self.assertIn("node_kind: episode",
                      ef.AN_EPISODE_NODES_KIND_IS_THE_NODES_AND_NOT_ITS_FIRST_CLAIMS)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
