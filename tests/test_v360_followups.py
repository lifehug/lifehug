"""v360 (owner, 2026-09-25): the follow-up batch.

Nine follow-ups to the owner's 2026-09-25 session, each guarded here on synthetic
vaults with the real shapes (the real write seat, the real binder rung, the
real fold and the real publication seam):

1. `resolver.AN_ESTIMATE_WIDER_THAN_FIVE_YEARS_STAYS_A_WINDOW` (owner agreed:
   cap inferred estimates at about five years) and
   `temporal_publication.A_WIDE_ESTIMATE_IS_ASKED_ONLY_WHEN_HOT`.
2. `temporal_timeline.A_PLACE_MENTION_IS_AN_OUTER_BOUND` — "in Arizona" bounds
   a moment its other evidence narrows; never across a gap between stays.
3. `cornerstones.A_CORNERSTONE_IS_TITLED_BY_ITS_OWN_NAME` — the wedding is
   "Married Katie Ann Merrill", not its reception.
4. `temporal_timeline.A_HANDLE_NAMING_A_CORNERSTONE_BINDS_TO_IT`,
   `temporal_timeline.A_CORNERSTONE_IS_ASKED_IN_ITS_OWN_WORDS`,
   `episode_binder.A_TELLING_TITLED_AS_A_MILESTONE_IS_THAT_MILESTONE` and
   `episode_binder.A_MILESTONE_NEVER_JOINS_TWO_ROSTER_PEOPLE` — one node, one
   question for his father's death.
5. `resolver.AN_ANSWER_WITH_NO_END_IS_ONGOING`.
6. `entity_roster.with_grandparent_side_cards`, wired into publish, and
   `entity_roster.A_GRANDPARENT_SIDE_HE_SAID_IS_KNOWN`.
7. `landmark_identity.A_RELATION_WORDS_HOME_IS_A_RELATIVE_PLACE` — "Dad's
   house could be many houses."
8. `temporal_timeline.A_HOUSE_LIVED_IN_TWICE_SPANS_BOTH_STAYS` — Williams,
   both stays, minus the mission between them.
9. `relation_words.HIS_OWN_TELLINGS_ARE_READ_BY_A_NAME_HE_USES` — "my
   beautiful daughter Charlee".

Synthetic data only; NEVER references any real vault.
"""
from __future__ import annotations

import copy
import json
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "system"))
sys.path.insert(0, str(ROOT / "tests"))

import chronology as chrono  # noqa: E402
import cornerstones as cs  # noqa: E402
import entity_roster as er  # noqa: E402
import episode_binder as eb  # noqa: E402
import landmark_identity as lid  # noqa: E402
import landmark_projection as lp  # noqa: E402
import relation_words as rw  # noqa: E402
import resolver  # noqa: E402
import temporal_claims as tc  # noqa: E402
import temporal_projection as tp  # noqa: E402
import temporal_publication as pub  # noqa: E402
import temporal_store as ts  # noqa: E402
import temporal_timeline as tt  # noqa: E402
import timeline  # noqa: E402

import test_v360_look_before_asking as lba  # noqa: E402
import test_v360_one_place_one_landmark as opl  # noqa: E402
from test_v342_a_merged_node_keeps_its_date import lost_placements  # noqa: E402

NOW = "2026-09-25T12:00:00Z"
OWNER_BIRTH = "1981-07-11"

#: The owner's own roster shapes: his father, whom he calls Dad, and two
#: grandparents.
ROSTER = {"version": 1, "type": "person", "entities": [
    {"name": "James Taylor", "slug": "james-taylor", "relationship": "parent",
     "aliases": ["James Taylor (Dad)", "dad", "my dad", "father", "my father"]},
    {"name": "Desiree Taylor", "slug": "desiree-taylor", "relationship": "parent",
     "aliases": ["Desi", "mom", "my mom", "mother", "my mother"]},
    {"name": "James Edwin Taylor Sr.", "slug": "james-edwin-taylor-sr",
     "relationship": "grandparent", "aliases": ["grandfather", "grandpa"]},
    {"name": "Grandma Betty Jo", "slug": "grandma-betty-jo", "relationship": "grandparent",
     "aliases": ["Grandma", "Betty Jo", "BJ"]},
    {"name": "Katie Taylor", "slug": "katie-taylor", "relationship": "spouse",
     "aliases": ["Katie"]},
    {"name": "Charlee Joy Taylor", "slug": "charlee-joy-taylor", "relationship": "child",
     "aliases": []},
]}


def _date(text: str) -> dict:
    return chrono.parse_stated_date(text).to_dict()


# --------------------------------------------------------------------------
# 1 — an estimate wider than about five years stays a window
# --------------------------------------------------------------------------


class AWideEstimateStaysAWindowTests(unittest.TestCase):

    def setUp(self):
        self.vault = lba.Vault(self)
        self.vault.owner_birth()
        self.shop = self.vault.claim("shop", "The shop opened at some point after we moved.",
                                     label="shop opening", claim_type="relative_order",
                                     value={"relation": "after", "anchors": ["the move to Cedarport"]})
        self.node_id = self.shop["event_ref"]
        self.vault.publish()

    def file(self, earliest: str, latest: str) -> dict:
        item = resolver.plan_items(self.vault.root, limit=5)["items"][0]
        return resolver.file_envelope(self.vault.root, lba.envelope(item, [lba.unknown(
            self.node_id, question="Roughly which year did the shop open?", estimate={
                "earliest": earliest, "latest": latest, "confidence": 0.5,
                "basis": [{"kind": "residence", "text": "the Cedarport years"}]})]), now=NOW)

    def test_the_cap_is_named_and_is_sixty_months(self):
        self.assertEqual(resolver.MAX_PLACING_ESTIMATE_MONTHS, 60)
        grounded = [{"kind": "tenure", "text": "x"}]
        self.assertTrue(resolver.estimate_places(
            {"earliest": "1996", "latest": "2000", "basis": grounded}, {}))
        self.assertFalse(resolver.estimate_places(
            {"earliest": "1996", "latest": "2001-01", "basis": grounded}, {}))

    def test_a_wide_estimate_files_no_placement_and_keeps_its_window(self):
        report = self.file("1996", "2004")
        self.assertEqual(report["placed_by_estimate"], 0)
        row = resolver.load_ledger(self.vault.root)["nodes"][self.node_id]
        self.assertEqual(row["estimate_not_placed"], "wider_than_five_years")
        node = self.vault.nodes()["shop opening"]
        self.assertFalse(node.get("usable_placement"))
        self.assertEqual(node["probable_window"]["earliest"], "1996")

    def test_a_wide_window_is_not_asked_unless_hot(self):
        self.file("1996", "2004")
        cards = [row for row in self.vault.cards()
                 if row.get("node_ref") == self.node_id and row["kind"] == "precision_gap"]
        self.assertEqual(cards, [])

    def test_a_narrow_estimate_still_places(self):
        report = self.file("1996", "1999")
        self.assertEqual(report["placed_by_estimate"], 1)
        self.assertTrue(self.vault.nodes()["shop opening"]["usable_placement"])

    def test_an_estimate_never_retires_his_own_words(self):
        """`resolver.AN_ESTIMATE_NEVER_RETIRES_HIS_WORDS`: his "after the move
        to Cedarport" stays active under the estimate."""
        self.file("1996", "1999")
        by_id = {c["claim_id"]: c for c in ts.fold_active_index(self.vault.root)["claims"]}
        self.assertEqual(by_id[self.shop["claim_id"]]["status"], "active")

    def test_an_estimate_filed_before_the_cap_is_retired_by_the_backfill(self):
        self.file("1996", "1999")
        ledger = resolver.load_ledger(self.vault.root)
        claim_id = ledger["nodes"][self.node_id]["placed_by_estimate"]["claim_id"]
        ledger["nodes"][self.node_id]["estimate"]["latest"] = "2008"
        resolver.save_ledger(self.vault.root, ledger)
        report = resolver.resolve_vault(self.vault.root, model="test-model", execute=True,
                                        limit=0, concurrency=1,
                                        only_sources={"answers/none.md"}, force=False, now=NOW)
        self.assertEqual(report["standing_estimates_retired_wide"], 1)
        by_id = {c["claim_id"]: c for c in ts.fold_active_index(self.vault.root)["claims"]}
        self.assertEqual(by_id[claim_id]["status"], "superseded")
        self.assertFalse(self.vault.nodes()["shop opening"].get("usable_placement"))


# --------------------------------------------------------------------------
# 2 and 8 — a place is an outer bound; a house lived in twice spans both
# --------------------------------------------------------------------------

#: His Arizona and California stays, with 701 N Williams twice and his
#: mission between the two Williams stays.
SEED = copy.deepcopy(opl.SEED)
SEED["residences"] += [
    opl.stay("Williams", "701 N Williams, Mesa, AZ", "Mesa, Arizona", "1997-06", "2000-08"),
    opl.stay("Williams", "701 N Williams, Mesa, AZ", "Mesa, Arizona", "2002-06", "2005-06"),
]
SEED["birth"] = [{"domain": "birth", "label": "birth", "date": {
    **opl.when(OWNER_BIRTH), "confidence": "certain"}}]


class PlaceVault(opl.VaultTestCase):

    def setUp(self) -> None:
        with mock.patch.object(opl, "SEED", SEED):
            super().setUp()

    def tell(self, text: str, *, claim_type: str = "occurrence",
             temporal_value: object = None, mention: str = "") -> None:
        """`VaultTestCase.tell`, with the per-moment ``event_ref`` the
        classifier files (without it two tellings in one vault are unbound)."""
        event_ref = tp.derive_node_id(node_kind="event", event_kind="moment",
                                      subject_refs=["self"], discriminator=mention or text)

        def claims_for(ref):
            payload = {
                "claim_type": claim_type, "subject_mention": "self",
                "event_kind": "moment", "event_mention": mention or text[:60],
                "event_ref": event_ref,
                "source_kind": "conversation", "source_ref": ref.to_dict(),
                "evidence": [{"quote": text}], "extractor_version": "classifier:1",
                "created_at": NOW, "basis": "explicit", "confidence": 0.9,
                "status": "active",
            }
            if temporal_value is not None:
                payload["temporal_value"] = temporal_value
            return [tc.validate_temporal_claim(payload)]

        ts.file_message_extraction(
            self.vault, message_text=text, extractor_version="classifier:1",
            claims_for=claims_for, metadata={"session_ref": f"chat:{mention or text}",
                                             "turn_ref": "0"}, now=NOW)

    def best(self, projection: dict, label: str) -> dict:
        node = self.node(projection, label)
        self.assertIsNotNone(node, label)
        return node.get("best_temporal_value") or {}

    def window(self, projection: dict, label: str) -> tuple:
        value = self.best(projection, label)
        return (value.get("earliest"), value.get("latest"))


class APlaceIsAnOuterBoundTests(PlaceVault):

    def test_the_eagle_scout_project_reads_the_eagle_scout_not_all_of_arizona(self):
        self.tell("I earned my Eagle Scout at 16, when I lived in Arizona",
                  claim_type="age", temporal_value="16",
                  mention="Earned Eagle Scout in Arizona")
        self.tell("My Eagle Scout project was painting the junior high lunch chairs",
                  claim_type="relative_order", mention="Eagle Scout project",
                  temporal_value={"relation": "within",
                                  "anchors": ["earning Eagle Scout in Arizona"]})
        projection = self.projection()
        earned = self.window(projection, "Earned Eagle Scout in Arizona")
        project = self.window(projection, "Eagle Scout project")
        self.assertEqual(project, earned)
        # Before: the envelope of every Arizona stay, 1982-08 .. 2009-06.
        self.assertNotEqual(project, ("1982-08", "2009-06"))
        self.assertTrue("1996" <= project[0] and project[1] <= "1999")

    def test_a_window_is_clipped_to_the_stays_it_touches(self):
        # 13 is July 1994 – July 1995; Arizona starts again at Hope, June 1995.
        self.tell("I was 13, when we lived in Arizona", claim_type="age",
                  temporal_value="13", mention="Paper route")
        value = self.best(self.projection(), "Paper route")
        self.assertEqual(value["earliest"], "1995-06")
        self.assertTrue(value["latest"].startswith("1995-07"))

    def test_evidence_wholly_in_a_gap_stands(self):
        # 12 is July 1993 – July 1994: Yucaipa, California — an Arizona gap.
        self.tell("I was 12, when we lived in Arizona", claim_type="age",
                  temporal_value="12", mention="Summer camp")
        value = self.best(self.projection(), "Summer camp")
        self.assertTrue(value["earliest"].startswith("1993-07"))
        self.assertEqual(value["basis"], "age")

    def test_an_undated_mention_is_still_the_whole_envelope(self):
        self.tell("I broke my arm when I lived in Arizona", mention="Broke an arm")
        self.assertEqual(self.window(self.projection(), "Broke an arm"),
                         ("1982-08", "2009-06"))

    def test_no_placement_is_lost(self):
        self.tell("I broke my arm when I lived in Arizona", mention="Broke an arm")
        before = self.projection()
        self.tell("I was 13, when we lived in Arizona", claim_type="age",
                  temporal_value="13", mention="Paper route")
        self.assertEqual(lost_placements(before, self.projection()), [])


class WilliamsSpansBothStaysTests(PlaceVault):

    def test_a_bare_williams_spans_both_stays_with_the_gap_recorded(self):
        self.tell("That happened when we lived at Williams", mention="Garage band")
        value = self.best(self.projection(), "Garage band")
        self.assertEqual((value["earliest"], value["latest"]), ("1997-06", "2005-06"))
        gaps = [row for row in value.get("provenance") or ()
                if row.get("rule") == "place_anchor_gap"]
        self.assertEqual(gaps[0]["gaps"], ["2000-09/2002-05"])

    def test_a_teenager_lands_in_the_first_stay(self):
        # 19 is July 2000 – July 2001: the end of the first stay, then the
        # mission. Clipped out of the gap, it is the first stay's last weeks.
        self.tell("I was 19, when we lived at Williams", claim_type="age",
                  temporal_value="19", mention="Mission call")
        value = self.best(self.projection(), "Mission call")
        self.assertTrue(value["earliest"].startswith("2000-07"))
        self.assertEqual(value["latest"], "2000-08")

    def test_after_the_mission_lands_in_the_second_stay(self):
        # 20 is July 2001 – July 2002: the mission, then home. Clipped out of
        # the gap, it is the second stay's first weeks.
        self.tell("I was 20, when we lived at Williams", claim_type="age",
                  temporal_value="20", mention="Back from the mission")
        value = self.best(self.projection(), "Back from the mission")
        self.assertEqual(value["earliest"], "2002-06")
        self.assertTrue(value["latest"].startswith("2002-07"))

    def test_no_which_time_card_for_one_place(self):
        self.tell("The Williams backyard barbecue", mention="Williams backyard barbecue")
        projection = self.projection()
        self.assertEqual([row for row in projection.get("work_items") or ()
                          if row.get("kind") == "place_ambiguous"], [])
        self.assertEqual(self.cards_about(projection, "Which time"), [])
        self.assertEqual(self.window(projection, "Williams backyard barbecue"),
                         ("1997-06", "2005-06"))


# --------------------------------------------------------------------------
# 3 and 4 — cornerstones: their own name, one node, one question
# --------------------------------------------------------------------------


class ACornerstoneIsTitledByItsOwnNameTests(unittest.TestCase):

    def setUp(self):
        self.vault = lba.Vault(self)
        self.vault.roster(ROSTER)
        self.vault.owner_birth()

    def test_the_wedding_is_married_katie_ann_merrill(self):
        wedding = self.vault.claim("wed1", "I married Katie Ann Merrill January 11th, 2007.",
                                   label="Married Katie Ann Merrill", claim_type="date",
                                   value=_date("2007-01-11"), event_kind="married")
        self.vault.claim("wed2", "The reception was in my mother-in-law's backyard.",
                         label="Wedding reception in mother-in-law's backyard",
                         event_ref=wedding["event_ref"])
        self.vault.claim("wed3", "Married Katie", label="Married Katie",
                         event_ref=wedding["event_ref"])
        self.vault.publish()
        labels = {node["label"] for node in pub.read_projection(self.vault.root)["nodes"]}
        self.assertIn("Married Katie Ann Merrill", labels)
        self.assertNotIn("Wedding reception in mother-in-law's backyard", labels)

    def test_the_title_rule_reads_only_milestone_titles(self):
        claims = [{"event_mention": "Wedding reception in mother-in-law's backyard",
                   "event_kind": "moment"},
                  {"event_mention": "Married Katie", "event_kind": "moment"}]
        self.assertEqual(cs.cornerstone_title(claims, "wedding", name_words=["Katie"]),
                         "Married Katie")
        self.assertEqual(cs.cornerstone_title(
            [{"event_mention": "Honeymoon in Hawaii", "event_kind": "moment"}], "wedding"), "")

    def test_a_moment_that_is_not_a_cornerstone_keeps_its_longest_telling(self):
        node = self.vault.claim("trip", "We went to the lake.", label="Lake trip")
        self.vault.claim("trip2", "The long lake trip with the cousins.",
                         label="The long lake trip with the cousins",
                         event_ref=node["event_ref"])
        self.vault.publish()
        labels = {n["label"] for n in pub.read_projection(self.vault.root)["nodes"]}
        self.assertIn("The long lake trip with the cousins", labels)


class HisFathersDeathIsOneQuestionTests(unittest.TestCase):

    def setUp(self):
        self.vault = lba.Vault(self)
        self.vault.roster(ROSTER)
        self.vault.owner_birth()
        self.death = self.vault.claim(
            "d15", "My dad died of COVID in the early days of the pandemic.",
            label="Father dies of COVID", claim_type="date", subject="narrator's father",
            value=_date("2020-03/2020-06"))
        # His other telling, folded in by the binder: "right before we started
        # Etherfuse" (2022), filed under his own subject.
        self.vault.claim("d2", "My dad died right before we started Etherfuse.",
                         label="Father's death", claim_type="date", subject="self",
                         value={**_date("2022-01/2022-04"), "basis": "anchor",
                                "confidence": "inferred"},
                         basis="inferred", event_ref=self.death["event_ref"])
        self.mom = self.vault.claim(
            "c9", "For the rest of her life after Dad's death, Mom lived with my sister.",
            label="Mom moves in with sister permanently", claim_type="relative_order",
            subject="Mom", value={"relation": "after", "anchors": ["Dad's death"]})
        self.vault.publish()
        self.projection = pub.read_projection(self.vault.root)

    def node(self, node_id):
        return next(n for n in self.projection["nodes"] if n["node_id"] == node_id)

    def test_one_question_worded_as_his_fathers_death(self):
        """One card, about his father's death. It used to be the contradiction
        "Two dates are claimed for your father's death — March 2020–June 2020
        and early 2022"; since `temporal_timeline.A_DEATH_IS_DATED_BY_ITS_DATE`
        (v360, owner 2026-09-25) an anchor-worked window is a finding and never a
        rival of the date he stated, so what is left is the day card."""
        cards = [row for row in self.projection["work_items"]
                 if row.get("node_ref") == self.death["event_ref"]]
        self.assertEqual([row["kind"] for row in cards], ["precision_gap"])
        self.assertEqual(cards[0]["prompt_intent"],
                         "Do you know the day of your father's death?")
        self.assertIn(tt.DIAGNOSTIC_DEATH_RIVAL_IS_NOT_A_DATE,
                      {row.get("finding") for row in self.projection["diagnostics"]["findings"]})

    def test_the_node_is_titled_as_the_cornerstone(self):
        self.assertEqual(self.node(self.death["event_ref"])["label"], "Father's death")

    def test_dads_death_binds_to_his_fathers_death(self):
        mom = self.node(self.mom["event_ref"])
        self.assertTrue(mom.get("usable_placement"))
        self.assertTrue(mom["best_temporal_value"]["earliest"].startswith("2020"))
        self.assertFalse(any("Dad's death" in (row.get("question") or "")
                             for row in self.projection.get("keystones") or ()))
        self.assertFalse(any("Dad's death" in (row.get("prompt_intent") or "")
                             for row in self.projection["work_items"]))

    def test_the_day_card_speaks_of_his_father(self):
        vault = lba.Vault(self)
        vault.roster(ROSTER)
        vault.owner_birth()
        vault.claim("d15", "My dad died of COVID.", label="Father dies of COVID",
                    claim_type="date", subject="narrator's father",
                    value=_date("2020-03/2020-06"))
        vault.publish()
        prompts = [row["prompt_intent"] for row in vault.cards()
                   if row["kind"] == "precision_gap"]
        self.assertIn("Do you know the day of your father's death?", prompts)


class TheBinderReadsTheMilestoneTitleTests(unittest.TestCase):

    def view(self, label, people=("james", "taylor"), entities=("person/james-taylor",)):
        return eb.TellingView(
            telling_ref=f"t:{label}", event_kind="moment", label=label, stem="",
            tokens=frozenset(), places=frozenset(), participants=frozenset(),
            eras=frozenset(), documents=frozenset(), people=frozenset(people),
            entities=frozenset(entities))

    def test_dies_is_a_death_and_an_adjunct_noun_is_not(self):
        self.assertEqual(eb.milestone_of(self.view("Father dies of COVID")), "death")
        self.assertEqual(eb.milestone_of(self.view("Father's death")), "death")
        self.assertEqual(eb.milestone_of(self.view("Begins processing father's death years later")), "")
        self.assertEqual(eb.milestone_of(self.view("Father's death and marriage strain")), "")

    def test_two_roster_people_are_never_one_death(self):
        father = self.view("Father dies of COVID")
        grandfather = self.view("Grandfather's death at 66",
                                people=("james", "edwin", "taylor", "grandpa"),
                                entities=("person/james-edwin-taylor-sr",))
        self.assertTrue(eb._two_roster_people(father, grandfather))
        self.assertFalse(eb._two_roster_people(father, self.view("Father's death")))


# --------------------------------------------------------------------------
# 5 — an answer with no end is ongoing
# --------------------------------------------------------------------------


class AnAnswerWithNoEndIsOngoingTests(unittest.TestCase):

    def test_a_null_end_on_a_stretch_is_open(self):
        record = resolver._record({"earliest": "2016", "latest": None},
                                  target={"label": "Ongoing therapy throughout childhood",
                                          "event_kind": "moment"})
        self.assertEqual((record.earliest, record.latest), ("2016", None))
        record = resolver._record({"earliest": "2019-05", "latest": None},
                                  target={"label": "Working at Etherfuse", "event_kind": "job"})
        self.assertIsNone(record.latest)

    def test_an_explicit_open_end_is_open_whatever_the_shape(self):
        for end in ("..", "present", "Ongoing", "now"):
            record = resolver._record({"earliest": "2019", "latest": end},
                                      target={"label": "Dottie's birth", "event_kind": "birth"})
            self.assertIsNone(record.latest, end)

    def test_a_point_is_still_a_point(self):
        record = resolver._record({"earliest": "2018-01-15", "latest": None},
                                  target={"label": "Dottie's birth", "event_kind": "birth"})
        self.assertEqual((record.earliest, record.latest), ("2018-01-15", "2018-01-15"))
        self.assertEqual(resolver._record({"earliest": "1997", "latest": None}).latest, "1997")


# --------------------------------------------------------------------------
# 6 — the grandparent-side card, wired
# --------------------------------------------------------------------------


class TheGrandparentSideCardIsPublishedTests(unittest.TestCase):

    def vault(self, *tellings):
        vault = lba.Vault(self)
        vault.roster(ROSTER)
        vault.owner_birth()
        for n, text in enumerate(tellings):
            vault.claim(f"g{n}", text, label=f"telling {n}", quote=text)
        vault.publish()
        return vault

    def side_cards(self, vault):
        return [row for row in vault.cards() if row.get("requested_field") == "grandparent_side"]

    def test_betty_jo_gets_one_card_in_the_house_wording(self):
        vault = self.vault("my grandpa James Edwin Taylor Sr., my dad's dad, died of a heart attack")
        cards = self.side_cards(vault)
        self.assertEqual([row["prompt_intent"] for row in cards],
                         ["Is Grandma Betty Jo on your mom's side or your dad's?"])
        self.assertEqual(cards[0]["kind"], rw.RELATION_WORD_KIND)
        projection = pub.read_projection(vault.root)["work_items"]
        self.assertIn(cards[0]["work_item_id"], {row["work_item_id"] for row in projection})

    def test_a_side_he_said_is_not_asked(self):
        vault = self.vault(
            "my grandpa James Edwin Taylor Sr., my dad's dad, died of a heart attack",
            "My dad's parents are James Edwin Taylor Sr. and his mom Betty Jo Taylor.")
        self.assertEqual(self.side_cards(vault), [])

    def test_the_reader_is_one_clause_and_his_words(self):
        entity = ROSTER["entities"][2]
        self.assertEqual(er.stated_grandparent_side(
            entity, ["my grandpa James Edwin Taylor Sr., my dad's dad, died"])["side"],
            er.PATERNAL)
        self.assertIsNone(er.stated_grandparent_side(
            entity, ["James Edwin Taylor Sr. died. My mom's mother lived on."]))


# --------------------------------------------------------------------------
# 7 — "Dad's house could be many houses"
# --------------------------------------------------------------------------


class DadsHouseIsARelativePlaceTests(opl.VaultTestCase):

    RECORD = {"domain": "residences", "label": "dad's house", "subject": "subject and father"}

    def test_the_write_seat_files_no_entry(self):
        findings: list = []
        timeline.save_landmark("residences", dict(self.RECORD), findings=findings)
        self.assertNotIn("dad's house", [label.lower() for label in self.labels()])
        self.assertEqual(findings[-1]["reason"], lid.RELATIVE_PLACE_REFERENCE)

    def test_the_words_never_resolve_to_a_stay(self):
        stays = [{"id": "node:a", "record": {"label": "Dad's house", "nickname": "Dad's house"}}]
        self.assertIsNone(lid.resolve_place("dad's house", stays))
        self.assertTrue(lid.is_relative_place({"label": "mom's place"}))
        self.assertFalse(lid.is_relative_place({"label": "BJ's House"}))

    def test_an_existing_entry_retires_as_a_mention_not_a_merge(self):
        filed = lp.file_landmark_record(
            self.vault, "residences", dict(self.RECORD), ordinal=lp.next_ordinal(self.vault),
            extractor_version=lp.LIVE_EXTRACTOR, now=NOW)
        timeline.redraw_landmarks()
        before = self.projection()
        self.assertIsNotNone(self.node(before, "Dad's house"))
        plan = lp.duplicate_fold_plan(lp.load_landmark_sources(self.vault))
        step = next(row for row in plan if filed["source_ref"].source_id in row["source_ids"])
        self.assertEqual((step["kind"], step["reason"]),
                         (lp.MERGE_AS_MENTION, lid.RELATIVE_PLACE_REFERENCE))
        lp.file_landmark_merge(self.vault, domain="residences",
                               merged_source_id=filed["source_ref"].source_id,
                               kind=lp.MERGE_AS_MENTION, reason=step["reason"])
        timeline.redraw_landmarks()
        after = self.projection()
        self.assertIsNone(self.node(after, "Dad's house"))
        self.assertEqual(self.cards_about(after, "dad's house"), [])
        self.assertEqual(lost_placements(before, after), [])


# --------------------------------------------------------------------------
# 9 — his own tellings, by the name he uses
# --------------------------------------------------------------------------


class HisOwnTellingsFillTheRelationWordTests(unittest.TestCase):

    def test_my_beautiful_daughter_charlee_fills_the_full_name_row(self):
        told = {"answers/E27.md": ["I have my young buddy Harvey, my beautiful daughter "
                                   "Charlee, and everyone's home."]}
        rows = {row["name"]: row for row in rw.relation_word_rows(ROSTER, told=told)}
        self.assertEqual(rows["Charlee Joy Taylor"]["word"], "daughter")
        self.assertFalse(rows["Charlee Joy Taylor"]["askable"])

    def test_without_his_words_the_card_stays(self):
        rows = {row["name"]: row for row in rw.relation_word_rows(ROSTER)}
        self.assertTrue(rows["Charlee Joy Taylor"]["askable"])

    def test_a_longer_name_after_the_word_is_somebody_else(self):
        roster = {"version": 1, "type": "person", "entities": [
            {"name": "Desiree Taylor", "slug": "desiree-taylor", "relationship": "parent",
             "aliases": ["mom", "my mom"]}]}
        told = {"answers/K14.md": ["My mom's name was Desiree Ann Beauchamp, and after "
                                   "she married my dad Desiree Ann Taylor."]}
        rows = {row["name"]: row for row in rw.relation_word_rows(roster, told=told)}
        self.assertEqual(rows["Desiree Taylor"]["word"], "mother")

    def test_the_tellings_are_read_from_his_own_sources_only(self):
        vault = lba.Vault(self)
        (vault.root / "answers" / "E27.md").write_text(
            "---\ntype: prompted_answer\n---\n\n# Question E27: who is your daughter?\n\n"
            "I have my beautiful daughter Charlee.\n", "utf-8")
        (vault.root / "sources" / "gmail").mkdir(parents=True)
        (vault.root / "sources" / "gmail" / "x.md").write_text(
            "---\ntype: external_record\n---\n\nmy son Charlee\n", "utf-8")
        told = rw.own_telling_texts(vault.root)
        self.assertEqual(told, {"answers/E27.md": ["I have my beautiful daughter Charlee."]})


class TheRulesAreNamedTests(unittest.TestCase):

    def test_every_rule_is_a_named_sentence(self):
        for rule in (resolver.AN_ESTIMATE_WIDER_THAN_FIVE_YEARS_STAYS_A_WINDOW,
                     pub.A_WIDE_ESTIMATE_IS_ASKED_ONLY_WHEN_HOT,
                     tt.A_PLACE_MENTION_IS_AN_OUTER_BOUND,
                     tt.A_HOUSE_LIVED_IN_TWICE_SPANS_BOTH_STAYS,
                     tt.A_HANDLE_NAMING_A_CORNERSTONE_BINDS_TO_IT,
                     tt.A_CORNERSTONE_IS_ASKED_IN_ITS_OWN_WORDS,
                     cs.A_CORNERSTONE_IS_TITLED_BY_ITS_OWN_NAME,
                     eb.A_TELLING_TITLED_AS_A_MILESTONE_IS_THAT_MILESTONE,
                     eb.A_MILESTONE_NEVER_JOINS_TWO_ROSTER_PEOPLE,
                     resolver.AN_ANSWER_WITH_NO_END_IS_ONGOING,
                     resolver.AN_ESTIMATE_NEVER_RETIRES_HIS_WORDS,
                     er.A_GRANDPARENT_SIDE_HE_SAID_IS_KNOWN,
                     lid.A_RELATION_WORDS_HOME_IS_A_RELATIVE_PLACE,
                     rw.HIS_OWN_TELLINGS_ARE_READ_BY_A_NAME_HE_USES):
            self.assertIsInstance(rule, str)
            self.assertGreater(len(rule), 40)

    def test_the_rule_versions_moved(self):
        self.assertEqual(tt.CALCULATION_RULE_VERSION, "timeline-rules:25")
        self.assertEqual(rw.RELATION_WORD_RULE_VERSION, "relation-words:2")


if __name__ == "__main__":
    unittest.main()
