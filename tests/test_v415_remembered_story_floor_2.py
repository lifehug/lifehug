"""v415 — the remembered-story floor reaches the stories the owner's republish
showed it missing, and says what it did.

v410's pass moved ONE of his examples on the real vault. The five gaps, each
reproduced here with synthetic names, every placement test SEEN failing on
v411 bytes first:

1. "Friday McDonald's trips as a kid" — subject ``narrator (as a kid)``; the
   life stage was only in the subject's note, and the resolver's cited grade
   ("When I was in 4th or 5th grade we just never went out") is negated.
2. "Birthday Sizzler tradition with Grandma", "Dinner at Black Angus with
   grandkids" — no life-stage phrase at all; the resolver's interval simply
   opened at the birth.
3. "Neighbor Nicholas Reece's brothers were mean" — "when I was really young";
   the resolver cited a related moment at one house ("Witnessing Horsepool
   brothers being mean").
4. "Drew Manning's older brother seemed scary" — the telling says "in San
   Diego", and the interval (to 1988-06) never touched his San Diego stay.
5. Nothing in the published files said what the pass tried or declined.

Synthetic people and places only; NEVER reads a real vault.
"""
from __future__ import annotations

import copy
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "system"))
sys.path.insert(0, str(ROOT / "tests"))

import chronology as chrono  # noqa: E402
import remembered_story as rs  # noqa: E402
import resolver  # noqa: E402
import temporal_claims as tc  # noqa: E402
import temporal_projection as tp  # noqa: E402
import temporal_publication as pub  # noqa: E402
import temporal_receipts as trcpt  # noqa: E402
import temporal_store as ts  # noqa: E402
import temporal_timeline as tt  # noqa: E402

import test_v360_one_place_one_landmark as opl  # noqa: E402
from test_v410_remembered_story_floor import person  # noqa: E402

NOW = "2026-10-10T12:00:00Z"
BIRTH = "1981-07-11"
FOURTH_BIRTHDAY = "1985-07-11"

SEED = {
    "residences": [
        opl.stay("Juniper Court", "14 Juniper Ct, Lakeview, OR", "Lakeview, Oregon",
                 "1981-07", "1986-06"),
        opl.stay("Harbor Lane", "220 Harbor Ln, Port Ellis, WA", "Port Ellis, Washington",
                 "1986-06", "1989-06"),
        opl.stay("Gull Street", "1335 Gull St, Seabright, CA", "Seabright, California",
                 "1989-06", "1990-06"),
        opl.stay("Ridgeview", "35 Ridgeview Ln, Brookfield, CA", "Brookfield, California",
                 "1990-06", "1991-06"),
        opl.stay("Ashgrove's House", "34 Pecan Ave, Brookfield, CA", "Brookfield, California",
                 "1992-06", "1994-06"),
    ],
    "birth": [{"domain": "birth", "label": "birth",
               "date": {**opl.when(BIRTH), "confidence": "certain"}}],
}

ROSTER = {"version": 1, "type": "person", "entities": [
    person("Beatrice Joan Hale", "beatrice-joan-hale", "grandparent", born="1931-04-02",
           died="2019-01-24", aliases=["Grandma Bea", "BJ"]),
]}


class RepublishVault(opl.VaultTestCase):

    def setUp(self) -> None:
        with mock.patch.object(opl, "SEED", SEED):
            super().setUp()
        story = self.vault / "answers" / "a1.md"
        story.parent.mkdir(parents=True, exist_ok=True)
        story.write_text("# A story\n\nWhat he told.\n", encoding="utf-8")

    def told(self, text: str, *, mention: str, subject: str = "self") -> str:
        """His telling, undated (the classifier's occurrence)."""
        event_ref = tp.derive_node_id(node_kind="event", event_kind="moment",
                                      subject_refs=["self"], discriminator=mention)

        def claims_for(ref):
            return [tc.validate_temporal_claim({
                "claim_type": "occurrence", "subject_mention": subject,
                "event_kind": "moment", "event_mention": mention, "event_ref": event_ref,
                "source_kind": "conversation", "source_ref": ref.to_dict(),
                "evidence": [{"quote": text}], "extractor_version": "classifier:1",
                "created_at": NOW, "basis": "explicit", "confidence": 0.9,
                "status": "active"})]

        ts.file_message_extraction(
            self.vault, message_text=text, extractor_version="classifier:1",
            claims_for=claims_for, metadata={"session_ref": f"chat:{mention}",
                                             "turn_ref": "0"}, now=NOW)
        return event_ref

    def resolved(self, event_ref: str, *, mention: str, earliest: str, latest: str,
                 citations: list, subject: str = "self") -> None:
        """The resolver's inferred reading of it, filed as the resolver files."""
        target = {"node_id": event_ref, "event_ref": event_ref, "label": mention,
                  "event_kind": "moment", "subject": subject, "event": {}, "handles": []}
        resolver.file_resolution(self.vault, target, {
            "record": {"best": f"{earliest}/{latest}", "earliest": earliest, "latest": latest,
                       "granularity": "range", "basis": "stated", "confidence": "approximate",
                       "anchors": [], "provenance": []},
            "basis": "inferred", "confidence": 0.5, "fact_key": "life_shape",
            "citations": [{"doc": doc, "quote": quote} for doc, quote in citations],
            "reason": "From the shape of his life."},
            story_path="answers/a1.md", model="test-model", now=NOW, prior={})

    def projection(self) -> dict:
        pub.publish(self.vault, roster_snapshot=copy.deepcopy(ROSTER), now=NOW, full=True)
        return pub.read_projection(self.vault) or {}

    def window(self, projection: dict, label: str) -> tuple:
        node = self.node(projection, label)
        self.assertIsNotNone(node, label)
        value = node.get("best_temporal_value") or {}
        return value.get("earliest"), value.get("latest")

    def row(self, projection: dict, label: str) -> dict:
        node = self.node(projection, label)
        rows = (projection.get("diagnostics") or {}).get("remembered_story") or ()
        return next(row for row in rows if row.get("node_id") == node["node_id"])

    def tried(self, projection: dict, label: str) -> dict:
        return {c["context"]: c for c in self.row(projection, label)["contexts_tried"]}


class TheRepublishGaps(RepublishVault):

    def test_1_narrator_as_a_kid_with_a_negated_grade(self):
        ref = self.told("We'd go out for burgers on Fridays", mention="Friday burger trips",
                        subject="narrator (as a kid)")
        self.resolved(ref, mention="Friday burger trips", subject="narrator (as a kid)",
                      earliest=BIRTH, latest="1990-06", citations=[
                          ("story", "When I was in 4th or 5th grade we just never went out"),
                          ("spine", "(Ridgeview): June 1990–June 1991")])
        projection = self.projection()
        self.assertEqual(self.window(projection, "Friday burger trips"),
                         (FOURTH_BIRTHDAY, "1990-06"))
        self.assertEqual(self.row(projection, "Friday burger trips")["stage"], "kid")
        tried = self.tried(projection, "Friday burger trips")
        self.assertEqual(tried["stated_grade"]["outcome"], "negated")
        # The spine line the resolver guessed from is never context.
        self.assertEqual(tried["named_stay"]["outcome"], "not_found")

    def test_2_a_remembered_moment_with_no_life_stage_phrase(self):
        ref = self.told("Every birthday Grandma Bea took us to the Sizzler",
                        mention="Birthday Sizzler tradition with Grandma", subject="narrator")
        self.resolved(ref, mention="Birthday Sizzler tradition with Grandma", subject="narrator",
                      earliest=BIRTH, latest="2000-08",
                      citations=[("spine", "Training center: August 2000")])
        ref = self.told("Grandma would take all the grandkids to the steakhouse",
                        mention="Dinner at the steakhouse with grandkids")
        self.resolved(ref, mention="Dinner at the steakhouse with grandkids",
                      earliest=BIRTH, latest="2000-08",
                      citations=[("spine", "Training center: August 2000")])
        projection = self.projection()
        for label in ("Birthday Sizzler tradition with Grandma",
                      "Dinner at the steakhouse with grandkids"):
            with self.subTest(label=label):
                self.assertEqual(self.window(projection, label), (FOURTH_BIRTHDAY, "2000-08"))
                self.assertEqual(self.row(projection, label)["stage"], rs.REMEMBERED_STAGE)
        lifetime = self.tried(projection, "Birthday Sizzler tradition with Grandma")["person_lifetime"]
        self.assertIn("Beatrice Joan Hale died 2019-01-24", lifetime["text"])
        self.assertEqual(lifetime["outcome"], "no_change")

    def test_3_really_young_and_a_neighbour_at_one_house(self):
        ref = self.told("when I was really young was my neighbor Nicholas Rowe and his "
                        "brothers were mean", mention="Neighbor Nicholas Rowe's brothers were mean")
        self.resolved(ref, mention="Neighbor Nicholas Rowe's brothers were mean",
                      earliest=BIRTH, latest="1992-06", citations=[
                          ("story", "when I was really young was my neighbor Nicholas Rowe"),
                          ("p2", "Witnessing Ashgrove brothers being mean — June 1992–June 1994")])
        projection = self.projection()
        self.assertEqual(self.window(projection, "Neighbor Nicholas Rowe's brothers were mean"),
                         ("1992-06", "1994-06"))
        tried = self.tried(projection, "Neighbor Nicholas Rowe's brothers were mean")
        self.assertEqual(tried["named_stay"]["outcome"], "replaced_inferred")
        self.assertEqual(rs.life_stage(["when I was really young"])["stage"], "kid")

    def test_4_a_place_named_outright_beats_a_disjoint_inferred_band(self):
        text = ("The Kestrels were one in Seabright. Our neighbors were Dax Kestrel "
                "and his older brother.")
        ref = self.told(text, mention="Dax Kestrel's older brother seemed scary")
        self.resolved(ref, mention="Dax Kestrel's older brother seemed scary",
                      earliest=BIRTH, latest="1988-06", citations=[("story", text)])
        projection = self.projection()
        self.assertEqual(self.window(projection, "Dax Kestrel's older brother seemed scary"),
                         ("1989-06", "1990-06"))

    def test_5_the_published_files_say_what_was_moved_and_declined(self):
        ref = self.told("Every birthday Grandma Bea took us to the Sizzler",
                        mention="Birthday Sizzler tradition with Grandma", subject="narrator")
        self.resolved(ref, mention="Birthday Sizzler tradition with Grandma", subject="narrator",
                      earliest=BIRTH, latest="2000-08",
                      citations=[("spine", "Training center: August 2000")])
        ref = self.told("Dad worked nights at the cannery", mention="Dad's cannery nights")
        self.resolved(ref, mention="Dad's cannery nights", earliest=BIRTH, latest="1990",
                      citations=[("story", "Dad worked nights at the cannery")])
        projection = self.projection()
        self.assertEqual(self.window(projection, "Dad's cannery nights"), (BIRTH, "1990"))
        declined = self.row(projection, "Dad's cannery nights")
        self.assertEqual((declined["finding"], declined["reason"]),
                         (rs.DECLINED_FINDING, "third_person_fact"))
        receipt = trcpt.read_receipt(self.vault, projection["projection_generation"])
        summary = receipt["remembered_story"]
        self.assertEqual(summary["declined"], {"third_person_fact": 1})
        moved = {row["node_id"]: row for row in summary["moved"]}
        sizzler = self.node(projection, "Birthday Sizzler tradition with Grandma")["node_id"]
        self.assertEqual(moved[sizzler]["now"], f"{FOURTH_BIRTHDAY}/2000-08")

    def test_a_stated_date_and_a_home_are_still_untouched(self):
        ref = self.told("We got our first dog in 1983", mention="First dog")
        self.resolved(ref, mention="First dog", earliest="1983", latest="1983",
                      citations=[("story", "We got our first dog in 1983")])
        projection = self.projection()
        self.assertEqual(self.window(projection, "First dog"), ("1983", "1983"))
        self.assertEqual(self.window(projection, "Juniper Court")[0][:7], "1981-07")


class TheHelpers(unittest.TestCase):

    def test_owner_handles(self):
        for text in ("narrator (as a kid)", "Narrator's family", "Self", "the narrator"):
            with self.subTest(text=text):
                self.assertTrue(rs.owner_handle(text))
        for text in ("Dad", "Grandma Bea", "narrator's father"):
            with self.subTest(text=text):
                self.assertFalse(rs.owner_handle(text))

    def test_the_spine_is_never_read_as_the_story(self):
        claim = {"source_kind": "system_derived", "event_mention": "Friday trips",
                 "evidence": [{"quote": "story: we went as a kid | spine: (Ridgeview): June 1990"}]}
        every, _own = rs.group_texts({"claims": [claim]})
        self.assertNotIn("(Ridgeview): June 1990", every)

    def test_the_rule_version_moved(self):
        self.assertEqual(tt.CALCULATION_RULE_VERSION, "timeline-rules:31")


if __name__ == "__main__":
    unittest.main()
