"""v359 — an answer outlives its card.

THE INCIDENT, on the owner's own vault. He answered his father's mission card
*"19-21 years old"* (``sources/conversations/msg-fc9845c47f8dc2b5099724a5.md``,
``session_ref: conversation:cand:work_item:work:b7525efb7ce0bb69be2d7129``,
captured 2026-09-23T02:36:54Z). Before the answer was placed, the 2026-09-23
resolver run dated that node from its own reading and v350's identity re-key
moved it (``node:b69a5be503b14977a6ba0077`` → ``node:80f419115b858c37a7b051f3``
*"Father's mission to New Zealand"*). The card left the published generation,
and v352's placement refused the answer ``card_not_published`` — as it refused
**20 of the 28** card answers on a clone of his vault. Nothing said so except a
count.

THE CENSUS, measured on that clone (generation 192) against the vault's own
publication history. The 20 were ALL ``card_not_published``, and that one
refusal hid five different fates:

=====================================  =======  ===========================
what happened to the card              answers  after v359
=====================================  =======  ===========================
another reading dated its node, and its  8     placed / telling (re-derived)
id then re-keyed (6 cards)
a classifier age dated its node, same id  1     placed (re-derived)
node's only claim retracted by the        3     ``card_node_not_drawn``,
resolver as not an event (2 duplicate,          listed with the asked node
1 fact statement)
an anchor card (no node) whose handle     6     ``card_not_published``, listed
the resolver since bound
an August contradiction card ("James's    2     ``card_not_published``, listed
birth") on a node since redrawn, no alias
=====================================  =======  ===========================

THE RULE (`answer_placement.AN_ANSWER_OUTLIVES_ITS_CARD`): an answer to a card
the person was shown counts however the card has closed since. The card is not
remembered, it is RE-DERIVED — a work id is `derive_work_item_id` over kind,
subject, node and field, so the ids every node the vault still holds could have
been asked under are arithmetic — and the node is followed through
``node_aliases`` to where it is drawn now. An answer is refused only when no
node could have asked its card, or when the node it asked about is no longer
drawn; and every refused answer is LISTED, never only counted.

AND ONE MORE THING THE CLOSED CARDS SURFACED, in this module's own seat: *"This
would have happened, probably when I was 4 or 5"*, answering "When did Dad wins
pet snake at fair happen?", is the OWNER's age. Filed under the card node's
subject it would have been measured from his father's 1954 birth — lifehug#415's
first gap, here (`answer_placement.NARRATOR_AGE_RE`). A first-person age is the
narrator's, still on the card's node.

Every negative below was run against a build with its guard removed and SEEN
failing first.
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "system"))
sys.path.insert(0, str(ROOT / "tests"))

import answer_placement as ap  # noqa: E402
import general_listener as gl  # noqa: E402
import landmark_recorder as lr  # noqa: E402
import temporal_projection as tp  # noqa: E402
import temporal_publication as pub  # noqa: E402
import temporal_store as ts  # noqa: E402
import temporal_timeline as tt  # noqa: E402
import temporal_work_items as twi  # noqa: E402
from test_v340_apply_keeps_placements import (  # noqa: E402
    NOW,
    claim,
    index_of,
    write_vault,
)
from test_v345_a_telling_of_a_landmark_folds_onto_it import (  # noqa: E402
    placement_audit,
)
from test_v352_answering_a_card_places_its_moment import (  # noqa: E402
    FATHER_BIRTH,
    MISSION_CAPTURED,
    MISSION_REPLY,
    OWNER,
    VaultFixture,
    birth,
    owners_vault_claims,
    undated,
)

# --------------------------------------------------------------------------
# The owner's real shapes
# --------------------------------------------------------------------------

#: The father's mission card, exactly as his vault minted it: the ids are his.
MISSION_WORK_ITEM = "work:b7525efb7ce0bb69be2d7129"
MISSION_ASKED_NODE = "node:b69a5be503b14977a6ba0077"
MISSION_NODE_NOW = "node:80f419115b858c37a7b051f3"
MISSION_ASKED_SUBJECT = "James Edwin Taylor"
MISSION_CLAIM = "claim:c351966a890f34ca08d487df"

#: The resolver's own reading of the mission, as it was filed on 2026-09-23:
#: month-grained, basis anchor.
RESOLVER_WINDOW = {"best": "1973-06/1976-06", "earliest": "1973-06",
                   "latest": "1976-06", "granularity": "range",
                   "basis": "anchor", "confidence": "inferred"}

#: The day-exact window: ages 19 to 21 from 1954-06-04.
MISSION_WINDOW = ("1973-06-04", "1976-06-03")

SNAKE_REPLY = ("This would have happened, probably when I was 4 or 5, when we "
               "lived at the Fiegers' house.")
SNAKE_CAPTURED = "2026-09-24T21:54:14Z"
OWNER_BIRTH = "1981-07-11"


def the_owners_projection() -> dict:
    """The one node and the one alias his generation 192 publishes for it."""
    return {
        "nodes": [{"node_id": MISSION_NODE_NOW,
                   "label": "Father's mission to New Zealand",
                   "event_kind": "moment",
                   "subject_refs": ["person/james-taylor"],
                   "input_claim_refs": [MISSION_CLAIM]}],
        "node_aliases": {MISSION_ASKED_NODE: MISSION_NODE_NOW},
    }


def the_owners_claims() -> list[dict]:
    """The classifier's telling of the mission: the raw mention the card was
    minted from before v356 resolved it, still on the claim."""
    return [{"claim_id": MISSION_CLAIM, "subject_mention": MISSION_ASKED_SUBJECT,
             "claim_type": "occurrence", "status": "active"}]


class Vault(VaultFixture):
    """v352's synthetic vault, plus the acts that close a card."""

    def card(self, words: str) -> dict:
        return self.card_asking_about(words)

    def close_by_resolver(self, node_ref: str, *, window: dict | None = None) -> None:
        """The 2026-09-23 run's shape: a dated reading ON the node."""
        write_vault(self.root, [claim(
            source="resolver:" + node_ref.rsplit(":", maxsplit=1)[-1],
            claim_type="date",
            subject_mention="person/james-taylor", event_kind="span",
            event_ref=node_ref, temporal_value=window or RESOLVER_WINDOW,
            basis="inferred", confidence=0.8, extractor_version="resolver/rule:3",
            quote="He was 19-21 not me. I wasn't born yet.")])
        self.publish()

    def drop_from_publication(self, work_item_id: str) -> None:
        """A generation that no longer carries the card, whatever closed it —
        the node itself untouched and still undated."""
        path = self.root / "state" / "temporal_claims" / "work-items.json"
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["work_items"] = [row for row in payload["work_items"]
                                 if row.get("work_item_id") != work_item_id]
        path.write_text(json.dumps(payload), encoding="utf-8")

    def answer_card(self, work_item_id: str, reply: str, captured: str):
        return ts.promote_conversational_source(self.root, reply, {
            "session_ref": f"conversation:cand:work_item:{work_item_id}",
            "turn_ref": "0", "speaker": "person", "occurred_at": captured})

    def claims_from(self, source_path: str) -> list[dict]:
        index = ts.fold_active_index(self.root)
        wanted = ts.read_source_ref(self.root, source_path).source_id
        return [row for row in index["claims"]
                if (row.get("source_ref") or {}).get("source_id") == wanted
                and row.get("status") == "active"]


# --------------------------------------------------------------------------
# 1. The derivation, on the owner's own ids
# --------------------------------------------------------------------------

class TheCardIsReDerivedFromWhatItAskedTests(unittest.TestCase):
    """A work id IS what the card asked. His card re-derives from his node."""

    def test_his_card_id_is_the_digest_of_what_it_asked(self):
        self.assertEqual(tp.derive_work_item_id(
            kind="precision_gap", subject_ref=MISSION_ASKED_SUBJECT,
            event_ref=MISSION_ASKED_NODE, requested_field="date"), MISSION_WORK_ITEM)

    def test_the_re_keyed_node_re_derives_his_card(self):
        found = ap.closed_cards({MISSION_WORK_ITEM}, projection=the_owners_projection(),
                                claims=the_owners_claims())
        self.assertEqual(found[MISSION_WORK_ITEM], {
            "work_item_id": MISSION_WORK_ITEM, "asked_node_ref": MISSION_ASKED_NODE,
            "subject_ref": MISSION_ASKED_SUBJECT, "kind": "precision_gap",
            "requested_field": "date"})

    def test_the_answer_lands_where_the_moment_is_drawn_now(self):
        closed = ap.closed_cards({MISSION_WORK_ITEM},
                                 projection=the_owners_projection(),
                                 claims=the_owners_claims())
        card, refusal = ap.card_for_work_item(
            MISSION_WORK_ITEM, work_items={"work_items": []},
            projection=the_owners_projection(), closed=closed)
        self.assertEqual(refusal, "")
        self.assertEqual(card["node_ref"], MISSION_NODE_NOW)
        self.assertEqual(card["asked_node_ref"], MISSION_ASKED_NODE)
        self.assertEqual(card["card"], ap.CARD_CLOSED)
        # The SUBJECT is the node's own, resolved — never the raw mention the
        # card was minted from, which v335's shared-name rule cannot measure.
        self.assertEqual(card["subject_ref"], "person/james-taylor")

    def test_the_defect_without_the_derivation(self):
        """v352's refusal, reproduced: the same answer, the same generation, and
        nothing re-derived."""
        card, refusal = ap.card_for_work_item(
            MISSION_WORK_ITEM, work_items={"work_items": []},
            projection=the_owners_projection())
        self.assertIsNone(card)
        self.assertEqual(refusal, ap.REFUSED_CARD_NOT_PUBLISHED)

    def test_without_the_alias_the_re_keyed_card_does_not_re_derive(self):
        """The alias is what says where the moment went; the derivation never
        guesses one."""
        projection = {**the_owners_projection(), "node_aliases": {}}
        self.assertEqual(ap.closed_cards({MISSION_WORK_ITEM}, projection=projection,
                                         claims=the_owners_claims()), {})

    def test_the_raw_mention_on_the_claim_is_what_re_derives_it(self):
        """Resolution is data ABOUT a claim: without the mention the card was
        minted from, the resolved subject alone mints a different id."""
        self.assertEqual(ap.closed_cards({MISSION_WORK_ITEM},
                                         projection=the_owners_projection(),
                                         claims=[]), {})

    def test_a_node_a_filed_claim_names_re_derives_even_undrawn(self):
        """The retired node's shape: its only claim retracted, its id still on
        that claim's ``event_ref``."""
        node = "node:5273593ca6c107b65fd028bc"
        wid = tp.derive_work_item_id(kind="precision_gap", subject_ref="self",
                                     event_ref=node, requested_field="date")
        found = ap.closed_cards({wid}, projection={"nodes": []}, claims=[
            {"claim_id": "claim:c46a979df8a51b6b6fc3d34d", "event_ref": node,
             "subject_mention": "self", "status": "retracted"}])
        self.assertEqual(found[wid]["asked_node_ref"], node)
        card, refusal = ap.card_for_work_item(
            wid, work_items={"work_items": []}, projection={"nodes": []}, closed=found)
        self.assertIsNone(card)
        self.assertEqual(refusal, ap.REFUSED_NODE_NOT_DRAWN)

    def test_a_legacy_field_spelling_re_derives(self):
        wid = tp.derive_work_item_id(kind="precision_gap",
                                     subject_ref=MISSION_ASKED_SUBJECT,
                                     event_ref=MISSION_ASKED_NODE,
                                     requested_field=twi.LEGACY_REQUESTED_FIELD)
        found = ap.closed_cards({wid}, projection=the_owners_projection(),
                                claims=the_owners_claims())
        self.assertEqual(found[wid]["requested_field"], twi.LEGACY_REQUESTED_FIELD)

    def test_nothing_wanted_derives_nothing(self):
        self.assertEqual(ap.closed_cards((), projection=the_owners_projection(),
                                         claims=the_owners_claims()), {})

    def test_a_published_card_is_never_read_as_closed(self):
        """A card still in the generation is the published one, whatever the
        derivation would also say."""
        row = {"work_item_id": MISSION_WORK_ITEM, "state": "open",
               "node_ref": MISSION_NODE_NOW, "subject_ref": "person/james-taylor",
               "kind": "precision_gap", "requested_field": "date",
               "prompt_intent": "When was Father's mission to New Zealand?"}
        card, refusal = ap.card_for_work_item(
            MISSION_WORK_ITEM, work_items={"work_items": [row]},
            projection=the_owners_projection(),
            closed={MISSION_WORK_ITEM: {"asked_node_ref": "node:" + "0" * 24}})
        self.assertEqual(refusal, "")
        self.assertEqual(card["card"], ap.CARD_PUBLISHED)
        self.assertEqual(card["question"], "When was Father's mission to New Zealand?")


class WhichStatesAreAnswerableTests(unittest.TestCase):
    """A card that has been SHOWN is a card an answer is to; a card somebody
    recorded as settled is still refused, as v352 refused it."""

    def rows(self, state: str) -> dict:
        return {"work_items": [{"work_item_id": MISSION_WORK_ITEM, "state": state,
                                "node_ref": MISSION_NODE_NOW, "kind": "precision_gap",
                                "subject_ref": "person/james-taylor"}]}

    def test_an_offered_card_is_answerable(self):
        card, refusal = ap.card_for_work_item(
            MISSION_WORK_ITEM, work_items=self.rows("offered"),
            projection=the_owners_projection())
        self.assertEqual(refusal, "")
        self.assertEqual(card["node_ref"], MISSION_NODE_NOW)

    def test_a_settled_state_is_still_refused(self):
        for state in ("answered", "resolved", "dismissed", "obsolete"):
            with self.subTest(state=state):
                card, refusal = ap.card_for_work_item(
                    MISSION_WORK_ITEM, work_items=self.rows(state),
                    projection=the_owners_projection())
                self.assertIsNone(card)
                self.assertEqual(refusal, ap.REFUSED_CARD_NOT_OPEN)


# --------------------------------------------------------------------------
# 2. End to end: the resolver closes the card, then the answer arrives
# --------------------------------------------------------------------------

class TheResolverClosedTheCardFirstTests(unittest.TestCase):
    """The incident's order of events, on a synthetic vault minted by the real
    minter: the card is shown, the resolver dates its node, the card leaves the
    generation, THEN the owner's answer is placed."""

    def setUp(self):
        self.vault = Vault(self)
        card = self.vault.card("mission")
        self.work_item, self.node = card["work_item_id"], card["node_ref"]
        self.vault.close_by_resolver(self.node)
        self.before = self.vault.derived()
        self.promoted = self.vault.answer_card(self.work_item, MISSION_REPLY,
                                               MISSION_CAPTURED)

    def test_the_card_really_closed(self):
        ids = {row["work_item_id"] for row in self.vault.work_items()}
        self.assertNotIn(self.work_item, ids)
        self.assertEqual(self.vault.placed("Dad's mission"),
                         ("1973-06/1976-06", "anchor"))

    def test_the_answer_is_placed_on_the_node_it_answered(self):
        report = ap.place_answers(self.vault.root, now=NOW)
        self.assertEqual(report["errors"], [])
        self.assertEqual((report["answers"], report["placed"]), (1, 1))
        self.assertEqual(report["through_a_closed_card"], 1)
        self.assertEqual(report["unplaced"], [])
        filed = report["filed"][0]
        self.assertEqual((filed["node_ref"], filed["card"], filed["reading"]),
                         (self.node, ap.CARD_CLOSED, ap.READING_AGE))
        claims = self.vault.claims_from(self.promoted.source_path)
        self.assertEqual([(c["claim_type"], c["subject_mention"], c["event_ref"])
                          for c in claims],
                         [("age", "person/james-taylor", self.node)])

    def test_the_answer_joins_the_placement_it_agrees_with(self):
        """v345's ruling, unchanged: an age that agrees with a dated moment is
        evidence ON the placement, not a rival — and the answer is now that
        evidence, measured day-exact from the father's own birth."""
        ap.place_answers(self.vault.root, now=NOW)
        self.vault.publish()
        record = self.vault.best("Dad's mission")
        self.assertEqual((record["best"], record["basis"]),
                         ("1973-06/1976-06", "anchor"))
        claim_id = self.vault.claims_from(self.promoted.source_path)[0]["claim_id"]
        self.assertIn(claim_id, {row.get("claim_id") for row in record["provenance"]})
        findings = [row for row in (pub.read_projection(self.vault.root) or {})
                    ["diagnostics"]["findings"]
                    if row.get("finding") == tt.DIAGNOSTIC_AGE_CORROBORATES]
        self.assertEqual([row["age_window"] for row in findings],
                         ["/".join(MISSION_WINDOW)])

    def test_the_placement_loses_nothing(self):
        ap.place_answers(self.vault.root, now=NOW)
        self.assertEqual(placement_audit(self.before, self.vault.derived()),
                         {"lost": [], "drawn_at_an_alias": [], "moved": []})

    def test_filing_twice_files_nothing_twice(self):
        ap.place_answers(self.vault.root, now=NOW)
        receipts = sorted(ts.receipt_relative_paths(self.vault.root))
        again = ap.place_answers(self.vault.root, now=NOW)
        self.assertEqual(sorted(ts.receipt_relative_paths(self.vault.root)), receipts)
        self.assertEqual(again["filed"][0]["claim_id"],
                         self.vault.claims_from(self.promoted.source_path)[0]["claim_id"])

    def test_a_dry_run_writes_nothing_and_still_says_what_it_would_do(self):
        receipts = sorted(ts.receipt_relative_paths(self.vault.root))
        report = ap.place_answers(self.vault.root, dry_run=True, now=NOW)
        self.assertEqual(sorted(ts.receipt_relative_paths(self.vault.root)), receipts)
        self.assertEqual(report["through_a_closed_card"], 1)
        self.assertEqual(report["filed"][0]["card"], ap.CARD_CLOSED)

    def test_the_sweep_carries_it(self):
        import classifier_claims as ccl  # noqa: PLC0415

        report = ccl.migrate_classifier_moments(self.vault.root, now=NOW)
        self.assertEqual(report["answers"]["through_a_closed_card"], 1)
        self.assertIn("  through a card that has since closed: 1",
                      ap.describe(report["answers"]))

    def test_the_listener_seat_aims_at_the_closed_card_too(self):
        """`landmark_recorder.file_claims` asks the same function, so the
        listener's ``they`` draft lands on the node and mints no ``they``."""
        draft, _finding = gl.validate_claim_draft({
            "claim_type": "age", "subject_mention": "they", "event_kind": "span",
            "temporal_value": "19-21", "evidence": [{"quote": MISSION_REPLY}],
            "basis": "explicit"})
        filed = lr.file_claims(
            self.vault.root, [draft], message_text=MISSION_REPLY,
            extractor_version="listener:1",
            session_ref=f"conversation:cand:work_item:{self.work_item}",
            turn_ref="1", speaker="person", occurred_at=MISSION_CAPTURED, now=NOW)
        self.assertIsNotNone(filed)
        self.assertNotIn("they", {label.lower() for label in self.vault.nodes()})
        listener = [row for row in ts.fold_active_index(self.vault.root)["claims"]
                    if row.get("extractor_version") == "listener:1"]
        self.assertEqual([row["event_ref"] for row in listener], [self.node])


class TheAnswerAlonePlacesTheMomentTests(unittest.TestCase):
    """When nothing else dated the node, the answer is what places it — 19–21
    from 1954-06-04, day-exact, basis age."""

    def setUp(self):
        self.vault = Vault(self)
        card = self.vault.card("mission")
        self.work_item = card["work_item_id"]
        self.vault.drop_from_publication(self.work_item)
        self.vault.answer_card(self.work_item, MISSION_REPLY, MISSION_CAPTURED)

    def test_before_the_rule_the_answer_was_refused(self):
        card, refusal = ap.card_for_work_item(
            self.work_item, work_items=pub.read_work_items(self.vault.root),
            projection=pub.read_projection(self.vault.root))
        self.assertEqual((card, refusal), (None, ap.REFUSED_CARD_NOT_PUBLISHED))

    def test_the_answer_places_the_mission(self):
        report = ap.place_answers(self.vault.root, now=NOW)
        self.assertEqual((report["placed"], report["through_a_closed_card"]), (1, 1))
        self.vault.publish()
        record = self.vault.best("Dad's mission")
        self.assertEqual(record["basis"], "age")
        self.assertEqual((record["earliest"], record["latest"]), MISSION_WINDOW)


# --------------------------------------------------------------------------
# 3. What is still refused — by name, and listed
# --------------------------------------------------------------------------

class RefusedAnswersAreListedTests(unittest.TestCase):
    """Only two refusals are left for a closed card, and neither is silent."""

    def setUp(self):
        self.moment_node = tp.derive_node_id(
            node_kind="event", event_kind="moment", subject_refs=[OWNER],
            discriminator="copy-machine")
        self.telling = claim(
            source="classification:sources-copy#c46a979df8a5",
            claim_type="occurrence", subject_mention=OWNER, event_kind="moment",
            event_ref=self.moment_node, event_mention="Copy machine warning memory")
        self.vault = Vault(self, claims=[*owners_vault_claims(), self.telling])
        self.work_item = self.vault.card("copy machine")["work_item_id"]

    def retire_the_moment(self) -> None:
        """The resolver's not-an-event verdict: the node's only claim retracted."""
        ts.retract_claims(self.vault.root, [self.telling["claim_id"]],
                          reason="Not an event (duplicate) by resolver/rule:3",
                          scope="resolver_not_an_event", author="resolver",
                          occurred_at=NOW)
        self.vault.publish()

    def test_a_retired_node_is_refused_and_names_what_was_asked(self):
        self.retire_the_moment()
        promoted = self.vault.answer_card(
            self.work_item, "This is when I lived in the Horsepools house.",
            "2026-09-22T23:17:47Z")
        report = ap.place_answers(self.vault.root, now=NOW)
        self.assertEqual(report["refused"][ap.REFUSED_NODE_NOT_DRAWN], 1)
        self.assertEqual(report["unplaced"], [{
            "source_path": promoted.source_path, "work_item_id": self.work_item,
            "refused": ap.REFUSED_NODE_NOT_DRAWN, "asked_node_ref": self.moment_node}])
        self.assertIn(f"  unplaced {promoted.source_path}: card_node_not_drawn "
                      f"({self.work_item}, asked about {self.moment_node})",
                      ap.describe(report))

    def test_a_card_nothing_could_have_asked_is_refused_and_listed(self):
        nobody = "work:" + "0" * 24
        promoted = self.vault.answer_card(nobody, "19-21 years old", MISSION_CAPTURED)
        report = ap.place_answers(self.vault.root, now=NOW)
        self.assertEqual(report["unplaced"], [{
            "source_path": promoted.source_path, "work_item_id": nobody,
            "refused": ap.REFUSED_CARD_NOT_PUBLISHED, "asked_node_ref": None}])


# --------------------------------------------------------------------------
# 4. A first-person age is the narrator's
# --------------------------------------------------------------------------

class AFirstPersonAgeIsTheNarratorsTests(unittest.TestCase):
    """*"probably when I was 4 or 5"* on his father's card is HIS age."""

    def setUp(self):
        claims = [
            birth("classification:sources-birth#aaaaaaaaaaaa", OWNER, OWNER_BIRTH,
                  "My birth"),
            birth("classification:sources-dad#cccccccccccc", "person/james-taylor",
                  FATHER_BIRTH, "Dad's birth"),
            undated("classification:answers-m4#3d327cf4fe86", "person/james-taylor",
                    "Dad wins pet snake at fair"),
        ]
        self.vault = Vault(self, claims=claims)
        self.work_item = self.vault.card("snake")["work_item_id"]

    def test_the_reading_names_whose_age_it_is(self):
        reading = ap.answer_reading(SNAKE_REPLY, captured=SNAKE_CAPTURED)
        self.assertEqual((reading["claim_type"], reading["temporal_value"]),
                         ("age", "4"))
        self.assertEqual(reading["subject_ref"], ap.NARRATOR_SUBJECT_REF)

    def test_a_third_person_age_stays_the_nodes(self):
        for reply in ("He only really started talking when he was 4",
                      "19-21 years old", "when she was 19", "aged 19"):
            with self.subTest(reply=reply):
                self.assertNotIn("subject_ref", ap.answer_reading(reply, captured=NOW))

    def test_every_first_person_phrasing(self):
        for reply, age in (("when I was 4", "4"), ("I was 19 years old", "19"),
                           ("I'm 30 years old now", "30"),
                           ("when we were 19-21", "19-21"),
                           ("while we were about 12 years old", "12")):
            with self.subTest(reply=reply):
                self.assertEqual(ap.age_phrase(reply), age)
                self.assertTrue(ap.age_is_the_narrators(reply, age))

    def test_it_is_measured_from_the_owners_birth(self):
        self.vault.answer_card(self.work_item, SNAKE_REPLY, SNAKE_CAPTURED)
        report = ap.place_answers(self.vault.root, now=NOW)
        self.assertEqual(report["placed"], 1)
        self.vault.publish()
        record = self.vault.best("Dad wins pet snake at fair")
        self.assertEqual(record["basis"], "age")
        self.assertEqual((record["earliest"], record["latest"]),
                         ("1985-07-11", "1986-07-10"))

    def test_without_the_rule_it_would_be_his_fathers_age(self):
        """The defect this guards, measured: the same age under the node's
        subject reads 1958 — his father at four."""
        card, _refusal = ap.card_for_answer(
            self.vault.root, f"conversation:cand:work_item:{self.work_item}")
        reading = {**ap.answer_reading(SNAKE_REPLY, captured=SNAKE_CAPTURED)}
        reading.pop("subject_ref")
        wrong = ap.answer_claim(card, reading, source_ref={
            "source_id": "conversation:x", "revision": "sha256:" + "0" * 64},
            quote=SNAKE_REPLY, now=NOW)
        self.assertEqual(wrong["subject_mention"], "person/james-taylor")


# --------------------------------------------------------------------------
# 5. The release
# --------------------------------------------------------------------------

class TheReleaseTests(unittest.TestCase):
    """The release ships, with its test in the manifest."""

    def manifest(self) -> dict:
        path = ROOT / "system" / "version.json"
        return json.loads(path.read_text(encoding="utf-8"))

    def test_the_release_has_shipped(self):
        self.assertGreaterEqual(self.manifest()["version"], 359)

    def test_the_test_ships_in_framework_files(self):
        self.assertIn("tests/test_v359_an_answer_outlives_its_card.py",
                      self.manifest()["framework_files"])

    def test_the_rule_is_stated_once_and_reported(self):
        self.assertIn("re-derived", ap.AN_ANSWER_OUTLIVES_ITS_CARD)
        report = ap.empty_report()
        self.assertEqual(report["closed_card_rule"], ap.AN_ANSWER_OUTLIVES_ITS_CARD)
        self.assertEqual((report["through_a_closed_card"], report["unplaced"]), (0, []))

    def test_the_fold_rule_version_does_not_move(self):
        """This release files CLAIMS an answer was owed; it changes no
        derivation, so a vault with no closed-card answer draws what it drew."""
        self.assertEqual(tt.CALCULATION_RULE_VERSION, "timeline-rules:18")
        self.assertEqual(
            tt.derive_calculated_timeline(
                index_of([]), now=NOW).calculation_rule_version,
            tt.CALCULATION_RULE_VERSION)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
