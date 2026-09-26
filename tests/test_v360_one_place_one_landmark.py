"""v360 (owner, 2026-09-25) — one place, one landmark.

THE OWNER'S RULING: *"The mention must not become a new place. It should be
tied to a landmark I've given. This also gives you the fidelity I care about.
If I say Arizona, I really just care that it's in Arizona. If I say Kristen or
BJ's house, I'm giving you the higher fidelity that I care about."*

WHERE IT WAS SEEN. His 15 September residences/schools/work document is fully
dated, with addresses. Overnight on 2026-09-25 (05:16-08:20Z) the nightly
sweep's ``landmark-record`` filings wrote twelve entries, ten of them empty
copies of entries he had given ("Thunderhead Street, San Diego" beside
"Thunderhead", "Mountain View High" beside "Mountain View", "Mesa, Arizona"
twice, one of them ``subject: they``), and earlier ones ("Fiegers' house"
beside "Figers House", "701 North Williams" beside "Williams") had landed the
same way. Each became an undated node and a *"When did X happen?"* card,
because the entry key is the case-folded label.

THE RULES (`landmark_identity.ONE_PLACE_ONE_LANDMARK`,
`landmark_identity.A_PLACE_MENTION_TIES_TO_HIS_LANDMARKS`):

1. At the write seat (`timeline.save_landmark`) a record that is the same
   thing as an entry he gave (same address, same street and city, a house
   name misheard by voice-to-text; the same school name core; the same
   employer; the same person) is filed as a TELLING of that entry through a
   merge record, and adds only what is new. With no date and nothing new it is
   not written at all.
2. A city or state named as a residence, when he has stays there, is a mention
   of those stays and never a residence; someone else's residence is never his.
3. The fold ties a place a telling names to his stays at the level he named
   it: a city or a state is the union of his stays there, a house is that
   stay, "left <house>" is that stay's end, month-grained at most.
4. `lifehug.py landmark-fold-duplicates` folds what landed before the rule,
   through merge records beside the immutable sources, with the old node ids
   redirected so nothing that named them is lost.

Synthetic data only; NEVER references ~/Workspace/dave.
"""

from __future__ import annotations

import argparse
import contextlib
import copy
import io
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "system"))
sys.path.insert(0, str(ROOT / "tests"))

import landmark_identity as lid  # noqa: E402
import landmark_projection as lp  # noqa: E402
import temporal_claims as tc  # noqa: E402
import temporal_publication as pub  # noqa: E402
import temporal_store as ts  # noqa: E402
import temporal_timeline as tt  # noqa: E402
import timeline  # noqa: E402

NOW = "2026-09-25T12:00:00Z"


def when(text: str) -> dict:
    grain = {4: "year", 7: "month", 10: "day"}[len(text)]
    return {"best": text, "earliest": text, "latest": text, "granularity": grain,
            "confidence": "approximate", "basis": "stated", "anchors": [],
            "provenance": []}


def stay(label: str, address: str, city: str, start: str, end: str, **extra) -> dict:
    return {"domain": "residences", "label": label, "nickname": label,
            "address": address, "city": city,
            "span": {"start": when(start), "end": when(end)}, **extra}


#: His residences document, in its real shapes (addresses as he gave them).
SEED = {
    "residences": [
        stay("Figers House", "1656 E 2nd Ave, Mesa, AZ 85204", "Mesa, Arizona",
             "1982-08", "1986-06"),
        stay("Thunderhead", "13353 Thunderhead St, San Diego, CA 92129",
             "San Diego, California", "1989-06", "1990-06"),
        stay("Beauchamps", "35430 Tresa Ln, Yucaipa, CA", "Yucaipa, California",
             "1990-06", "1991-06"),
        stay("Horsepool's House", "34375 Pecan Ave, Yucaipa, CA",
             "Yucaipa, California", "1992-06", "1994-06"),
        stay("Hope", "2624 E Hope St, Mesa, AZ", "Mesa, Arizona",
             "1995-06", "1997-06"),
        stay("Kristen", "734 N Kristen, Mesa, AZ 85213", "Mesa, Arizona",
             "2007-08", "2009-06"),
    ],
    "schools": [
        {"domain": "schools", "label": "Mountain View", "name": "Mountain View",
         "grades": "11th and 12th",
         "span": {"start": when("1997-06"), "end": when("1999-06")}},
    ],
}

#: The overnight shapes, byte for byte what the sweep filed.
THUNDERHEAD_STREET = {"address": "Thunderhead Street", "city": "San Diego",
                      "domain": "residences",
                      "label": "Thunderhead Street, San Diego"}
FIEGERS = {"address": "the Fiegers' house", "domain": "residences",
           "label": "Fiegers' house"}
MOUNTAIN_VIEW_HIGH = {"domain": "schools", "label": "Mountain View High",
                      "name": "Mountain View High", "place": "Mesa, Arizona"}
HIGH_SCHOOL = {"domain": "schools", "grades": "sophomore or junior year",
               "label": "high school", "name": "high school"}
MESA = {"city": "Mesa", "domain": "residences", "label": "Mesa, Arizona"}
MESA_THEY = {"city": "Mesa", "domain": "residences", "label": "Mesa, Arizona",
             "subject": "they"}


# --------------------------------------------------------------------------
# The identity rules, pure
# --------------------------------------------------------------------------


class IdentityRuleTests(unittest.TestCase):

    def residences(self) -> list[dict]:
        return copy.deepcopy(SEED["residences"])

    def test_thunderhead_street_san_diego_is_thunderhead(self) -> None:
        found = lid.matches("residences", THUNDERHEAD_STREET, self.residences())
        self.assertEqual([entry["label"] for entry, _ in found], ["Thunderhead"])
        self.assertEqual(found[0][1], "same_street_and_city")

    def test_voice_to_text_figers_is_fiegers(self) -> None:
        found = lid.matches("residences", FIEGERS, self.residences())
        self.assertEqual([entry["label"] for entry, _ in found], ["Figers House"])
        self.assertTrue(lid.same_word("Fiegers", "Figers"))

    def test_the_threshold_keeps_his_distinct_houses_apart(self) -> None:
        # One edit and one Soundex joins a mishearing; his real houses stay
        # apart ("Fisches" is three edits from "Figers" and sounds different),
        # and a short word must match exactly.
        self.assertFalse(lid.same_word("Fisches", "Figers"))
        self.assertFalse(lid.same_word("Hope", "Hops"))
        self.assertFalse(lid.same_word("Harris", "Hope"))
        rows = self.residences()
        for i, left in enumerate(rows):
            for right in rows[i + 1:]:
                self.assertIsNone(lid.same_residence(left, right),
                                  (left["label"], right["label"]))

    def test_north_and_n_street_and_st_are_one_address(self) -> None:
        williams = stay("Williams", "701 N Williams, Mesa, AZ", "Mesa, Arizona",
                        "1997-06", "2000-08")
        self.assertEqual(lid.same_residence(
            {"address": "701 North Williams", "label": "701 North Williams"},
            williams), "same_address")
        self.assertIsNone(lid.same_residence(
            {"address": "702 North Williams"}, williams))

    def test_mountain_view_high_is_mountain_view(self) -> None:
        found = lid.matches("schools", MOUNTAIN_VIEW_HIGH, SEED["schools"])
        self.assertEqual([entry["label"] for entry, _ in found], ["Mountain View"])
        self.assertEqual(lid.matches("schools", HIGH_SCHOOL, SEED["schools"])[0][1],
                         "the_one_school_at_that_level")

    def test_a_city_only_residence_is_a_mention_of_his_stays(self) -> None:
        decision = lid.decide("residences", MESA, self.residences())
        self.assertEqual(decision["decision"], lid.NOT_WRITTEN)
        self.assertEqual(decision["reason"], lid.PLACE_LEVEL_MENTION)
        self.assertEqual(sorted(entry["label"] for entry in decision["stays"]),
                         ["Figers House", "Hope", "Kristen"])

    def test_someone_elses_residence_is_never_his(self) -> None:
        decision = lid.decide("residences", {"city": "Boise", "label": "Boise",
                                             "subject": "they"}, self.residences())
        self.assertEqual(decision["reason"], lid.NOT_HIS_RESIDENCE)
        self.assertTrue(lid.is_his({"subject": "subject and father"}))

    def test_the_same_person_and_the_same_employer(self) -> None:
        kids = [{"label": "Harvey Rex Taylor", "who": "Harvey Rex Taylor"},
                {"label": "Charlee Joy Taylor", "who": "Charlee Joy Taylor"}]
        self.assertEqual(lid.same_person({"label": "Harvey", "who": "Harvey"},
                                         kids[0], kids), "same_person_first_name")
        self.assertEqual(lid.same_person(
            {"label": "James just turned 13", "who": "James Everett Taylor"},
            {"label": "James Everett Taylor", "who": "James Everett Taylor"}),
            "same_person")
        self.assertEqual(lid.same_employer({"label": "A.J.'s Pizza"},
                                           {"label": "AJ's Pizza"}), "same_employer")
        self.assertIsNone(lid.same_employer({"label": "Boeing in Seattle"},
                                            {"label": "Boeing"}))

    def test_the_place_phrases_a_telling_uses(self) -> None:
        self.assertEqual(lid.anchor_place_phrase("when I lived in Arizona"),
                         ("during", "Arizona"))
        self.assertEqual(lid.anchor_place_phrase(
            "After I left Kristen, we moved in together with my dad"), ("end", "Kristen"))
        self.assertEqual(lid.anchor_place_phrase("in Yucaipa"), ("during", "Yucaipa"))
        self.assertIsNone(lid.anchor_place_phrase("while living in the desert"))


# --------------------------------------------------------------------------
# A throwaway vault
# --------------------------------------------------------------------------


class VaultTestCase(unittest.TestCase):

    def setUp(self) -> None:
        self.vault = Path(tempfile.mkdtemp(prefix="lifehug-one-place-",
                                           dir="/private/tmp" if Path("/private/tmp").is_dir() else None))
        self.addCleanup(shutil.rmtree, self.vault, ignore_errors=True)
        self.store = self.vault / "state" / "landmarks.json"
        self.store.parent.mkdir(parents=True, exist_ok=True)
        for patch in (mock.patch.object(timeline, "LANDMARKS_STORE", self.store),
                      mock.patch.object(timeline, "_projection_vault_root",
                                        lambda: self.vault)):
            patch.start()
            self.addCleanup(patch.stop)
        self.store.write_text(json.dumps({"version": 1, "domains": copy.deepcopy(SEED)},
                                         indent=2) + "\n", encoding="utf-8")
        timeline.flip_landmarks_if_needed()

    def labels(self, domain: str = "residences") -> list[str]:
        return sorted(entry.get("label") or "" for entry in
                      (timeline.load_landmarks().get(domain) or ()))

    def projection(self) -> dict:
        pub.publish(self.vault, roster_snapshot=(), now=NOW, full=True)
        return pub.read_projection(self.vault) or {}

    def node(self, projection: dict, label: str) -> dict | None:
        return next((node for node in projection.get("nodes") or ()
                     if str(node.get("label") or "").lower() == label.lower()), None)  # titles are sentence-cased

    def cards_about(self, projection: dict, words: str) -> list[str]:
        return [item.get("prompt_intent") or "" for item in projection.get("work_items") or ()
                if words in (item.get("prompt_intent") or "")]

    def tell(self, text: str, *, claim_type: str = "occurrence",
             temporal_value: object = None, mention: str = "") -> None:
        """File one telling of his, the way a reader of a message files it."""
        def claims_for(ref):
            payload = {
                "claim_type": claim_type, "subject_mention": "self",
                "event_kind": "moment", "event_mention": mention or text[:60],
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
            claims_for=claims_for, metadata={"session_ref": f"chat:{text[:12]}",
                                             "turn_ref": "0"}, now=NOW)


class TheWriteSeatTests(VaultTestCase):
    """Rules 1 and 2 at `timeline.save_landmark`."""

    def test_thunderhead_street_san_diego_is_not_a_second_place(self) -> None:
        findings: list = []
        saved = timeline.save_landmark("residences", dict(THUNDERHEAD_STREET),
                                       findings=findings)
        self.assertEqual(saved["label"], "Thunderhead")
        self.assertEqual(saved["not_written"], lid.NOTHING_NEW)
        self.assertEqual(findings[0]["lint"], lid.NOT_WRITTEN_LINT)
        self.assertNotIn("Thunderhead Street, San Diego", self.labels())
        projection = self.projection()
        self.assertIsNone(self.node(projection, "Thunderhead Street, San Diego"))
        self.assertEqual(self.cards_about(projection, "Thunderhead Street"), [])

    def test_fiegers_house_is_figers_house(self) -> None:
        saved = timeline.save_landmark("residences", dict(FIEGERS))
        self.assertEqual(saved["label"], "Figers House")
        self.assertEqual(len(self.labels()), 6)

    def test_mountain_view_high_adds_only_its_place(self) -> None:
        findings: list = []
        saved = timeline.save_landmark("schools", dict(MOUNTAIN_VIEW_HIGH),
                                       findings=findings)
        self.assertEqual(findings[0]["lint"], lid.JOINED_LINT)
        self.assertEqual(self.labels("schools"), ["Mountain View"])
        self.assertEqual(saved["label"], "Mountain View")
        self.assertEqual(saved["name"], "Mountain View")
        self.assertEqual(saved["place"], "Mesa, Arizona")
        self.assertEqual(saved["grades"], "11th and 12th")
        # A merge record names the new source; the source itself is his words.
        merges = lp.load_landmark_merges(self.vault)
        self.assertEqual(len(merges), 1)
        self.assertEqual(merges[0]["into_entry_key"], "mountain view")
        projection = self.projection()
        self.assertIsNone(self.node(projection, "Mountain View High"))
        self.assertEqual(self.cards_about(projection, "Mountain View High"), [])

    def test_high_school_with_grades_already_given_is_not_written(self) -> None:
        saved = timeline.save_landmark("schools", dict(HIGH_SCHOOL))
        self.assertEqual(saved["not_written"], lid.NOTHING_NEW)
        self.assertEqual(saved["grades"], "11th and 12th")

    def test_a_city_only_mesa_is_never_a_residence(self) -> None:
        saved = timeline.save_landmark("residences", dict(MESA))
        self.assertEqual(saved["not_written"], lid.PLACE_LEVEL_MENTION)
        self.assertNotIn("Mesa, Arizona", self.labels())
        self.assertEqual(len(lp.load_landmark_sources(self.vault)), 7)

    def test_subject_they_is_never_filed_as_his(self) -> None:
        saved = timeline.save_landmark("residences", dict(MESA_THEY))
        self.assertEqual(saved["not_written"], lid.NOT_HIS_RESIDENCE)
        saved = timeline.save_landmark("residences", {
            "city": "Boise", "domain": "residences", "label": "Boise", "subject": "they"})
        self.assertEqual(saved["not_written"], lid.NOT_HIS_RESIDENCE)
        self.assertNotIn("Boise", self.labels())

    def test_a_genuinely_new_residence_is_still_written(self) -> None:
        record = stay("Bothell", "8700 NE Bothell Way B204, Bothell, WA 98011",
                      "Bothell, Washington", "2013-07", "2014-07")
        findings: list = []
        saved = timeline.save_landmark("residences", record, findings=findings)
        self.assertEqual(findings, [])
        self.assertNotIn("not_written", saved)
        self.assertIn("Bothell", self.labels())
        self.assertEqual(len(self.labels()), 7)

    def test_a_dated_telling_of_his_place_joins_it(self) -> None:
        # A record with a date is never dropped: it is his word, and it files
        # as a telling of the entry it names.
        record = {"domain": "residences", "label": "Kristen house",
                  "address": "734 North Kristen",
                  "span": {"start": when("2007-08"), "end": when("2009-06")}}
        findings: list = []
        timeline.save_landmark("residences", record, findings=findings)
        self.assertEqual(findings[0]["lint"], lid.JOINED_LINT)
        self.assertEqual(self.labels().count("Kristen"), 1)
        self.assertNotIn("Kristen house", self.labels())


class ThePlaceAnchorTests(VaultTestCase):
    """Rule 3 in the fold: the level he named sets the grain."""

    def test_when_i_lived_in_arizona_is_his_arizona_stays_at_month_grain(self) -> None:
        self.tell("I broke my arm when I lived in Arizona", mention="Broke an arm")
        node = self.node(self.projection(), "Broke an arm")
        value = node["best_temporal_value"]
        # The union of his Arizona stays: Figers House 1982-08 .. Kristen 2009-06.
        self.assertEqual((value["earliest"], value["latest"]), ("1982-08", "2009-06"))
        self.assertEqual(len(value["earliest"]), 7)
        self.assertEqual(value["basis"], "anchor")

    def test_in_yucaipa_is_his_yucaipa_stays(self) -> None:
        self.tell("Scout camping while living in Yucaipa", mention="Scout camping")
        value = self.node(self.projection(), "Scout camping")["best_temporal_value"]
        self.assertEqual((value["earliest"], value["latest"]), ("1990-06", "1994-06"))

    def test_left_kristen_is_the_end_of_that_stay(self) -> None:
        self.tell("After I left Kristen, we moved in together with my dad",
                  claim_type="relative_order", mention="moving in with dad",
                  temporal_value={"relation": "after", "anchors": ["left Kristen"]})
        projection = self.projection()
        value = self.node(projection, "moving in with dad")["best_temporal_value"]
        self.assertEqual(value["earliest"], "2009-06")
        self.assertIsNone(value["latest"])
        self.assertEqual(self.cards_about(projection, "left Kristen"), [])

    def test_a_house_he_named_is_that_stay(self) -> None:
        self.tell("That was when we lived at the Fiegers' house", mention="Tiger fight")
        value = self.node(self.projection(), "Tiger fight")["best_temporal_value"]
        self.assertEqual((value["earliest"], value["latest"]), ("1982-08", "1986-06"))

    def test_a_place_he_never_lived_places_nothing_and_mints_nothing(self) -> None:
        self.tell("That happened when I lived in Ohio", mention="Ohio thing")
        projection = self.projection()
        self.assertFalse((self.node(projection, "Ohio thing").get("best_temporal_value")
                          or {}).get("best"))
        self.assertEqual(len(timeline.load_landmarks().get("residences")), 6)

    def test_the_rule_version_moved(self) -> None:
        self.assertEqual(tt.CALCULATION_RULE_VERSION, "timeline-rules:25")


class TheFoldTests(VaultTestCase):
    """Rule 4: what landed before the rule, folded through merge records."""

    def file_raw(self, domain: str, record: dict) -> str:
        """File a record the way the sweep did BEFORE the rule existed."""
        filed = lp.file_landmark_record(
            self.vault, domain, dict(record), ordinal=lp.next_ordinal(self.vault),
            extractor_version=lp.LIVE_EXTRACTOR, now=NOW)
        timeline.redraw_landmarks()
        return filed["source_ref"].source_id

    def run_verb(self, *, apply: bool) -> str:
        import lifehug

        args = argparse.Namespace(pair=[], apply=apply, json=False)
        buffer = io.StringIO()
        with mock.patch.object(lifehug, "REPO_DIR", self.vault), \
                contextlib.redirect_stdout(buffer):
            self.assertEqual(lifehug.cmd_landmark_fold_duplicates(args), 0)
        return buffer.getvalue()

    def test_the_overnight_duplicates_fold_into_the_entries_he_gave(self) -> None:
        for record in (THUNDERHEAD_STREET, FIEGERS, MESA, MESA_THEY):
            self.file_raw("residences", record)
        self.file_raw("schools", MOUNTAIN_VIEW_HIGH)
        before = self.projection()
        dup = self.node(before, "Thunderhead Street, San Diego")
        self.assertIsNotNone(dup)
        self.assertTrue(self.cards_about(before, "Thunderhead Street"))

        dry = self.run_verb(apply=False)
        self.assertIn("nothing written", dry)
        self.assertEqual(lp.load_landmark_merges(self.vault), [])
        printed = self.run_verb(apply=True)
        self.assertIn("folded", printed)

        self.assertEqual(len(self.labels()), 6)
        self.assertEqual(self.labels("schools"), ["Mountain View"])
        after = self.projection()
        for label in ("Thunderhead Street, San Diego", "Fiegers' house",
                      "Mesa, Arizona", "Mountain View High"):
            self.assertIsNone(self.node(after, label), label)
            self.assertEqual(self.cards_about(after, label), [], label)
        thunderhead = self.node(after, "Thunderhead")
        self.assertEqual(after["node_aliases"][dup["node_id"]], thunderhead["node_id"])
        self.assertEqual(thunderhead["best_temporal_value"]["best"], "1989-06/1990-06")
        # Idempotent, and the sources are never touched.
        self.assertIn("no landmark duplicates", self.run_verb(apply=True))
        self.assertEqual(len(lp.load_landmark_sources(self.vault, apply_merges=False)), 12)

    def test_the_fold_keeps_every_placement(self) -> None:
        from test_v342_a_merged_node_keeps_its_date import lost_placements

        self.file_raw("residences", THUNDERHEAD_STREET)
        self.tell("I learned to ride a bike while living in San Diego", mention="Bike")
        before = self.projection()
        self.run_verb(apply=True)
        after = self.projection()
        self.assertEqual(lost_placements(before, after), [])
        self.assertEqual(self.node(after, "Bike")["best_temporal_value"]["best"],
                         "1989-06/1990-06")


if __name__ == "__main__":
    unittest.main()
