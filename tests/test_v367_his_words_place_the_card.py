"""v367 — the two card answers of 2026-09-27, placed from his own words.

THE INCIDENT (owner, staging, 2026-09-27 22:01Z). He answered two Timeline
cards a minute apart:

* "Roughly when did the investor threaten legal action over his token
  allotment …?" — *"August of 2025 "*;
* "What year did the foreclosure on 701 North Williams happen?" — *"This
  happened at the same time we moved out, when my parents moved into BJ's
  house and I moved in with them. When I moved into BJ's house, that's when
  701 was foreclosed on. "*

The dated card left Needs Placing (its turn filed a `resolve-work-item` job);
the relative one did not move at all. Traced on staging and on a clone of his
vault:

1. ``"August of 2025"`` read as NO date to the card seat: the loose parser read
   "August 2025" and refused "Month of YYYY", so even once the queued job ran,
   the answer would have filed as a telling and the card come back unplaced.
2. The relative answer filed NOTHING on the turn — `work_item_resolution`
   waited for a model `placed` date, and there is no number in his words — and
   the card seat could not read it either: "moved into BJ's house" was not a
   reading, and the fold had "left <house>" (a stay's end) but no start.

His rulings this answers: "What the owner says is the placement" and "A place
mention ties to a landmark he gave" (2026-09-25) — BJ's House is a stay he gave
(July 2009 on), so the foreclosure is July 2009, at the month the stay carries
("Month is enough").

Every negative below was run against a build with its guard removed and SEEN
failing first.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "system"))
sys.path.insert(0, str(ROOT / "tests"))

import answer_placement as ap  # noqa: E402
import chronology as chrono  # noqa: E402
import landmark_identity as lid  # noqa: E402
import timeline_interaction as ti  # noqa: E402
from test_v352_answering_a_card_places_its_moment import VaultFixture  # noqa: E402
from test_v360_one_place_one_landmark import SEED, VaultTestCase, stay  # noqa: E402

INVESTOR_ANSWER = "August of 2025 "
FORECLOSURE_ANSWER = (
    "This happened at the same time we moved out, when my parents moved into BJ's "
    "house and I moved in with them. When I moved into BJ's house, that's when 701 "
    "was foreclosed on. ")

#: The two cards as staging published them (generation 216).
INVESTOR_ITEM = {
    "kind": "precision_gap", "work_item_id": "work:d98335d4405dbd031ffcd7f1",
    "node_ref": "node:9671eb410f460185a5e0f472",
    "event_ref": "node:9671eb410f460185a5e0f472", "subject_ref": "self",
    "prompt_intent": ("Roughly when did the investor threaten legal action over his "
                      "token allotment — during Etherfuse's 2021–2022 legal/"
                      "token-structuring period, or later in 2023?"),
    "requested_field": "date", "state": "open", "resolves": [],
}
FORECLOSURE_ITEM = {
    "kind": "precision_gap", "work_item_id": "work:b7d7e642c55f679fc8283843",
    "node_ref": "node:72481c8a1f0bdc4c22212b89",
    "event_ref": "node:72481c8a1f0bdc4c22212b89",
    "subject_ref": "foreclosure on 701 North Williams",
    "prompt_intent": "What year did the foreclosure on 701 North Williams happen?",
    "requested_field": "date", "state": "open", "resolves": [],
}


class MonthOfYearIsADateTests(unittest.TestCase):
    def test_august_of_2025_is_august_2025(self):
        record = chrono.parse_stated_date(INVESTOR_ANSWER.strip())
        self.assertIsNotNone(record)
        self.assertEqual((record.best, record.granularity, record.basis),
                         ("2025-08", "month", "stated"))

    def test_his_reply_reads_as_that_date(self):
        reading = ap.answer_reading(INVESTOR_ANSWER)
        self.assertEqual(reading["reading"], ap.READING_DATE)
        self.assertEqual(reading["temporal_value"]["best"], "2025-08")

    def test_the_other_spellings(self):
        for text, best in (("may of 1999", "1999-05"), ("Aug. of 2001", "2001-08"),
                           ("It was August of 2025", "2025-08")):
            with self.subTest(text=text):
                self.assertEqual(ap.answer_reading(text)["temporal_value"]["best"], best)

    def test_of_without_a_month_is_still_not_a_month(self):
        self.assertIsNone(chrono.parse_stated_date("end of 2020"))


class MovingIntoAHouseIsItsStartTests(unittest.TestCase):
    def test_his_foreclosure_reply_names_one_moving_day(self):
        clauses = lid.move_clauses(FORECLOSURE_ANSWER)
        self.assertEqual({(row["relation"], row["handle"], row["side"]) for row in clauses},
                         {("within", "moved into BJ's house", "start")})

    def test_his_reply_is_a_relative_order_against_that_day(self):
        reading = ap.answer_reading(FORECLOSURE_ANSWER)
        self.assertEqual(reading["reading"], ap.READING_ANCHOR)
        self.assertEqual(reading["claim_type"], "relative_order")
        self.assertEqual(reading["temporal_value"],
                         {"relation": "within", "anchors": ["moved into BJ's house"]})

    def test_one_side_of_the_moving_day(self):
        self.assertEqual(ap.answer_reading("Right after we moved into the Fiegers house")
                         ["temporal_value"], {"relation": "after",
                                              "anchors": ["moved into the Fiegers house"]})
        self.assertEqual(ap.answer_reading("just before I left Kristen")["temporal_value"],
                         {"relation": "before", "anchors": ["moved out of Kristen"]})

    def test_the_fold_reads_the_handle_as_the_stays_start(self):
        self.assertEqual(lid.anchor_place_phrase("moved into BJ's house"),
                         ("start", "BJ's house"))

    def test_two_different_moving_days_stay_a_telling(self):
        self.assertIsNone(ap.anchor_reading(
            "When I moved into BJ's house, or maybe when we moved into Kristen"))

    def test_no_named_place_is_no_reading(self):
        for text in ("at the same time we moved out", "when I moved into a new place",
                     "when we moved to Mesa"):
            with self.subTest(text=text):
                self.assertIsNone(ap.anchor_reading(text))


class TheTurnFilesWhatTheCardSeatCanReadTests(unittest.TestCase):
    """`timeline_interaction.A_REPLY_THE_CARD_SEAT_CAN_READ_IS_FILED_NOW`."""

    def test_the_relative_answer_is_filed_on_the_turn(self):
        kwargs = ti.work_item_resolution(ti.work_item_target(FORECLOSURE_ITEM), None,
                                         resolution_text=FORECLOSURE_ANSWER)
        self.assertIsNotNone(kwargs)
        self.assertEqual(kwargs["correction_kind"], ti.CORRECTION_KIND_PLACE)
        self.assertEqual(kwargs["work_item_id"], FORECLOSURE_ITEM["work_item_id"])

    def test_the_dated_answer_is_filed_even_when_the_model_gave_no_placed(self):
        kwargs = ti.work_item_resolution(ti.work_item_target(INVESTOR_ITEM), None,
                                         resolution_text=INVESTOR_ANSWER)
        self.assertEqual(kwargs["correction_kind"], ti.CORRECTION_KIND_PLACE)

    def test_a_reply_nobody_can_read_still_waits(self):
        self.assertIsNone(ti.work_item_resolution(
            ti.work_item_target(FORECLOSURE_ITEM), None, resolution_text="no idea"))


class TheCardSeatPlacesTheDatedAnswerTests(unittest.TestCase):
    def test_august_of_2025_places_the_card_at_the_month(self):
        vault = VaultFixture(self)
        session = vault.session_for("cussing")
        placed = ap.place_card_answer(vault.root, session_ref=session, text=INVESTOR_ANSWER)
        self.assertEqual(placed["report"]["by_reading"][ap.READING_DATE], 1, placed)
        self.assertEqual(placed["report"]["tellings"], 0)


BJS_HOUSE = stay("BJ's House", "1234 E Main St, Mesa, AZ", "Mesa, Arizona",
                 "2009-07", "2010-12")


class TheFoldPlacesTheForeclosureTests(VaultTestCase):
    """The claim the card seat files, folded against his stays."""

    def setUp(self) -> None:
        SEED["residences"].append(BJS_HOUSE)
        self.addCleanup(SEED["residences"].remove, BJS_HOUSE)
        super().setUp()

    def file_his_reply(self, text: str, mention: str) -> None:
        reading = ap.answer_reading(text)
        self.tell(text, claim_type=reading["claim_type"],
                  temporal_value=reading["temporal_value"], mention=mention)

    def test_the_foreclosure_is_the_month_he_moved_into_bjs_house(self):
        self.file_his_reply(FORECLOSURE_ANSWER, "Foreclosure on 701 North Williams")
        projection = self.projection()
        node = self.node(projection, "Foreclosure on 701 North Williams")
        value = node["best_temporal_value"]
        self.assertEqual((value["earliest"], value["latest"]), ("2009-07", "2009-07"))
        self.assertTrue(node["usable_placement"])
        self.assertEqual(self.cards_about(projection, "moved into BJ's house"), [])

    def test_right_after_moving_in_is_on_or_after_that_month(self):
        self.file_his_reply("Right after I moved into BJ's House", "Got the dog")
        value = self.node(self.projection(), "Got the dog")["best_temporal_value"]
        self.assertEqual(value["earliest"], "2009-07")

    def test_a_house_he_never_gave_places_nothing_and_mints_nothing(self):
        self.file_his_reply("When I moved into Grant's House", "Grant thing")
        projection = self.projection()
        self.assertFalse((self.node(projection, "Grant thing").get("best_temporal_value")
                          or {}).get("best"))


if __name__ == "__main__":
    unittest.main()
