"""v410 — a remembered story never opens at the birth; better context beats the band.

The owner (born 1981-07-11), 2026-10-10: *"A kid's story shouldn't span from
birth. You should look for better context."* His calculated timeline held ~20
episodes opening exactly on his birth day because the telling said "as a kid"
/ "growing up" / "childhood" and nothing stated a date — "Friday McDonald's
trips as a kid" 1981-07-11→1990-06, "Drew Manning's older brother seemed
scary" (a NEIGHBOUR) 1981-07-11→1988-06, "Arguing with sister Jackie growing
up" 1981-07-11→2000-08 — a resolver / anchor-range reading the origin floor
slid onto the birth.

`remembered_story.A_REMEMBERED_STORY_OPENS_AFTER_INFANCY` and
`remembered_story.BETTER_CONTEXT_BEATS_THE_BAND`. Every placement test below was
run against v404 bytes (main before this release) and SEEN failing first.

Synthetic people and places only (the Calder family of Lakeview, Port Ellis and
Bend); NEVER reads a real vault.
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
import remembered_story as rs  # noqa: E402
import temporal_claims as tc  # noqa: E402
import temporal_projection as tp  # noqa: E402
import temporal_publication as pub  # noqa: E402
import temporal_store as ts  # noqa: E402
import temporal_timeline as tt  # noqa: E402

import test_v360_one_place_one_landmark as opl  # noqa: E402

NOW = "2026-10-10T12:00:00Z"
BIRTH = "1981-07-11"
FOURTH_BIRTHDAY = "1985-07-11"

#: The Calder vault: three homes, his birth.
SEED = {
    "residences": [
        opl.stay("Juniper Court", "14 Juniper Ct, Lakeview, OR", "Lakeview, Oregon",
                 "1981-07", "1986-06"),
        opl.stay("Harbor Lane", "220 Harbor Ln, Port Ellis, WA", "Port Ellis, Washington",
                 "1986-06", "1992-06"),
        opl.stay("Cedar Ridge", "9 Cedar Ridge Rd, Bend, OR", "Bend, Oregon",
                 "1992-06", "2000-08"),
    ],
    "birth": [{"domain": "birth", "label": "birth",
               "date": {**opl.when(BIRTH), "confidence": "certain"}}],
}


def _date(text: str) -> dict:
    grain = {4: "year", 7: "month", 10: "day"}[len(text)]
    return {"best": text, "earliest": text, "latest": text, "granularity": grain,
            "basis": "stated", "confidence": "certain"}


def person(name, slug, relationship, *, born=None, died=None, aliases=()):
    row = {"name": name, "slug": slug, "aliases": list(aliases),
           "relationship": relationship, "source": "landmark:family",
           "qualifies": False, "page_eligible": False}
    if born:
        row["born"] = chrono.normalized_date(_date(born))
    if died:
        row["died"] = chrono.normalized_date(_date(died))
    return row


ROSTER = {"version": 1, "type": "person", "entities": [
    person("Wren Calder", "wren-calder", "sibling", born="1987-02-10",
           aliases=["Wren", "sister Wren"]),
    person("Opal Calder", "opal-calder", "grandparent", born="1920-03-01",
           died="1989-11-03", aliases=["Grandma Opal"]),
]}


def inferred(earliest: str, latest: str) -> dict:
    """A resolver / anchor-range reading: never something he said."""
    return {"best": f"{earliest}/{latest}", "earliest": earliest, "latest": latest,
            "granularity": "range", "basis": "anchor", "confidence": "inferred"}


class RememberedVault(opl.VaultTestCase):

    def setUp(self) -> None:
        with mock.patch.object(opl, "SEED", SEED):
            super().setUp()

    def tell(self, text: str, *, mention: str, temporal_value: object = None,
             claim_type: str = "date") -> None:
        event_ref = tp.derive_node_id(node_kind="event", event_kind="moment",
                                      subject_refs=["self"], discriminator=mention)

        def claims_for(ref):
            payload = {
                "claim_type": claim_type if temporal_value is not None else "occurrence",
                "subject_mention": "self", "event_kind": "moment",
                "event_mention": mention, "event_ref": event_ref,
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
            claims_for=claims_for, metadata={"session_ref": f"chat:{mention}",
                                             "turn_ref": "0"}, now=NOW)

    def projection(self) -> dict:
        pub.publish(self.vault, roster_snapshot=copy.deepcopy(ROSTER), now=NOW, full=True)
        return pub.read_projection(self.vault) or {}

    def value(self, projection: dict, label: str) -> dict:
        node = self.node(projection, label)
        self.assertIsNotNone(node, label)
        return node.get("best_temporal_value") or {}

    def window(self, projection: dict, label: str) -> tuple:
        value = self.value(projection, label)
        return value.get("earliest"), value.get("latest")

    def finding(self, projection: dict, label: str) -> dict | None:
        node = self.node(projection, label)
        rows = (projection.get("diagnostics") or {}).get("findings") or ()
        return next((row for row in rows if row.get("finding") == rs.FINDING
                     and row.get("node_id") == node["node_id"]), None)


# --------------------------------------------------------------------------
# 1. A remembered story opens after infancy
# --------------------------------------------------------------------------


class ARememberedStoryOpensAfterInfancy(RememberedVault):

    def test_a_kids_story_opens_at_the_fourth_birthday_not_the_birth(self):
        self.tell("Every Friday we drove out for burgers as a kid",
                  mention="Friday burger trips as a kid",
                  temporal_value=inferred("1981", "1990-06"))
        projection = self.projection()
        self.assertEqual(self.window(projection, "Friday burger trips as a kid"),
                         (FOURTH_BIRTHDAY, "1990-06"))
        rules = [row.get("rule") for row in
                 self.value(projection, "Friday burger trips as a kid")["provenance"]]
        self.assertIn(tt.ORIGIN_FLOOR_RULE, rules)
        self.assertIn(rs.REMEMBERED_STORY_FLOOR_RULE, rules)
        row = self.finding(projection, "Friday burger trips as a kid")
        self.assertEqual((row["stage"], row["phrase"], row["remembered"]),
                         ("kid", "as a kid", True))
        self.assertTrue(row["band_applied"])
        self.assertEqual([c["context"] for c in row["contexts_tried"]], list(rs.CONTEXTS))

    def test_a_teenager_opens_at_thirteen(self):
        self.tell("As a teenager I worked the fuel dock at the marina",
                  mention="Working the marina fuel dock",
                  temporal_value=inferred("1981", "2000-08"))
        self.assertEqual(self.window(self.projection(), "Working the marina fuel dock"),
                         ("1994-07-11", "2000-08"))

    def test_a_third_person_fact_keeps_the_existing_bands(self):
        self.tell("Dad was in school during my early childhood",
                  mention="Dad in school during early childhood",
                  temporal_value=inferred("1981", "1986"))
        projection = self.projection()
        self.assertEqual(self.window(projection, "Dad in school during early childhood"),
                         (BIRTH, "1986"))
        self.assertFalse(self.finding(projection,
                                      "Dad in school during early childhood")["remembered"])

    def test_a_stated_date_always_wins(self):
        self.tell("As a kid in 1983 we got our first dog", mention="First dog",
                  temporal_value=_date("1983"))
        projection = self.projection()
        self.assertEqual(self.window(projection, "First dog"), ("1983", "1983"))
        self.assertIsNone(self.finding(projection, "First dog"))

    def test_the_earliest_memory_age_is_the_vaults_to_change(self):
        (self.vault / "profile.yaml").write_text("earliest_memory_age: 5\n", encoding="utf-8")
        self.tell("Every Friday we drove out for burgers as a kid",
                  mention="Friday burger trips as a kid",
                  temporal_value=inferred("1981", "1990-06"))
        self.assertEqual(self.window(self.projection(), "Friday burger trips as a kid"),
                         ("1986-07-11", "1990-06"))


# --------------------------------------------------------------------------
# 2. Better context beats the band
# --------------------------------------------------------------------------


class BetterContextBeatsTheBand(RememberedVault):

    def test_a_neighbour_is_at_the_home_where_they_were_neighbours(self):
        self.tell("When we lived at Juniper Court, Tobin Vance lived next door",
                  mention="Tobin Vance next door")
        self.tell("Tobin Vance's older brother seemed scary when I was little",
                  mention="Tobin Vance's older brother seemed scary",
                  temporal_value=inferred("1981", "1995-06"))
        projection = self.projection()
        self.assertEqual(self.window(projection, "Tobin Vance's older brother seemed scary"),
                         (FOURTH_BIRTHDAY, "1986-06"))
        row = self.finding(projection, "Tobin Vance's older brother seemed scary")
        tried = {c["context"]: c for c in row["contexts_tried"]}
        self.assertEqual(tried["name_tied_to_one_stay"]["outcome"], "replaced_inferred")  # v415: a locator replaces the band
        self.assertIn("Juniper Court", tried["name_tied_to_one_stay"]["text"])
        self.assertFalse(row["band_applied"])

    def test_a_younger_sister_bounds_a_story_about_her(self):
        self.tell("My sister Wren and I argued constantly growing up",
                  mention="Arguing with sister Wren growing up",
                  temporal_value=inferred("1981", "2000-08"))
        projection = self.projection()
        self.assertEqual(self.window(projection, "Arguing with sister Wren growing up"),
                         ("1987-02-10", "2000-08"))
        tried = {c["context"]: c for c in
                 self.finding(projection, "Arguing with sister Wren growing up")["contexts_tried"]}
        self.assertEqual(tried["person_lifetime"]["outcome"], "narrowed")

    def test_a_grandmothers_death_closes_a_story_with_her(self):
        self.tell("As a kid I stayed with Grandma Opal at the lake every summer",
                  mention="Summers with Grandma Opal",
                  temporal_value=inferred("1981", "2000-08"))
        self.assertEqual(self.window(self.projection(), "Summers with Grandma Opal"),
                         (FOURTH_BIRTHDAY, "1989-11-03"))

    def test_a_home_named_in_the_telling_bounds_it(self):
        self.tell("As a kid at Harbor Lane I broke my arm on the swings",
                  mention="Broken arm on the swings",
                  temporal_value=inferred("1981", "1997"))
        self.assertEqual(self.window(self.projection(), "Broken arm on the swings"),
                         ("1986-06", "1992-06"))

    def test_a_stated_grade_is_the_school_year(self):
        self.tell("In third grade, as a kid, I won the spelling bee",
                  mention="Won the spelling bee",
                  temporal_value=inferred("1981", "1995"))
        self.assertEqual(self.window(self.projection(), "Won the spelling bee"),
                         ("1989-08", "1990-06"))


# --------------------------------------------------------------------------
# The phrases, the table, the names
# --------------------------------------------------------------------------


class ThePhrasesAndTheTable(unittest.TestCase):

    def test_the_stages(self):
        cases = {
            "constantly having to move as a kid all the time because we had money problems":
                ("kid", True),
            "When I was little we lived by the tracks": ("kid", True),
            "My sister and I argued growing up": ("growing_up", True),
            "As a teenager I mowed lawns": ("teens", True),
            "A difficult childhood: poverty and my father's temper": ("childhood", True),
            "Dad was in school during my early childhood": ("childhood", False),
        }
        for text, (stage, remembered) in cases.items():
            with self.subTest(text=text):
                found = rs.life_stage([text])
                self.assertEqual((found["stage"], found["remembered"]), (stage, remembered))
        self.assertIsNone(rs.life_stage(["We moved to Bend in the fall"]))

    def test_the_default_table(self):
        config = rs.load_config()
        self.assertEqual(config["earliest_memory_age"], 4)
        self.assertEqual(config["bands"], {"teens": (13, 19), "growing_up": (4, 18),
                                           "kid": (4, 12), "childhood": (4, 12)})
        raw = json.loads(rs.CONFIG_PATH.read_text(encoding="utf-8"))
        self.assertEqual(raw["earliest_memory_age"], 4)

    def test_an_override_moves_every_band_floor_and_a_bad_one_is_refused(self):
        self.assertEqual(rs.load_config({"earliest_memory_age": 5})["bands"]["kid"], (5, 12))
        for bad in ({"earliest_memory_age": "five"}, {"earliest_memory_age": 40}):
            with self.subTest(bad=bad), self.assertRaises(rs.RememberedStoryConfigError):
                rs.load_config(bad)
        self.assertEqual(rs.profile_overrides({"earliest_memory_age": "3"}),
                         {"earliest_memory_age": 3})
        self.assertIsNone(rs.profile_overrides({"name": "Sam"}))

    def test_the_childhood_age_frame_is_unchanged(self):
        import cross_dating as cd  # noqa: PLC0415
        self.assertEqual(cd.AGE_FRAME_FIXED_BANDS, (("childhood", 0, 13), ("teens", 13, 20)))

    def test_a_resolver_quote_is_read_without_its_citation_prefixes(self):
        claim = {"source_kind": "system_derived", "event_mention": "Constantly moving",
                 "evidence": [{"quote": "story: we moved as a kid | spine: Bend 1992-06"}]}
        every, own = rs.group_texts({"claims": [claim]})
        self.assertIn("we moved as a kid", every)
        self.assertEqual(own, [])

    def test_proper_names_drop_their_lead_words(self):
        self.assertEqual(
            rs.proper_names(["Neighbor Tobin Vance's brother was mean",
                             "When we lived at Juniper Court"]),
            {"Tobin Vance", "Juniper Court"})

    def test_every_rule_is_a_named_sentence(self):
        for rule in (rs.A_REMEMBERED_STORY_OPENS_AFTER_INFANCY,
                     rs.BETTER_CONTEXT_BEATS_THE_BAND,
                     tt.A_REMEMBERED_STORY_OPENS_AFTER_INFANCY,
                     tt.BETTER_CONTEXT_BEATS_THE_BAND):
            self.assertIsInstance(rule, str)
            self.assertGreater(len(rule), 40)

    def test_the_rule_version_moved(self):
        self.assertEqual(tt.CALCULATION_RULE_VERSION, "timeline-rules:31")


if __name__ == "__main__":
    unittest.main()
