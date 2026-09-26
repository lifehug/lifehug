"""v360 (owner, 2026-09-25) — his records, and two answer shapes the system could not read.

THE OWNER, on his own landmarks (v360, 2026-09-25):

1. *"He went to Mountain View until he graduated in June 1999."* The 11th-12th
   telling of Mountain View carried the WILLIAMS STAY's bounds (1997-06 to
   2000-08, "from the dates of the Williams stay"), and because it abutted the
   9th-10th telling the key folded the two into ONE entry whose grades read
   "11th and 12th" over 1995-06 to 1997-06.
   (`landmark_projection.A_STATED_GRADUATION_ENDS_THE_SCHOOL`,
   `landmarks_interaction.TWO_STATED_GRADE_STRETCHES_ARE_TWO_STAYS`.)
2. *"Katie Ann Merrill"* filed as a school (2006) — his wife's name where the
   school goes, from "Katie graduated esthetician school".
3. *"It's still my company and it's still ongoing."* Etherfuse, "May 2022 -
   Present", read as a missing end (`landmark_projection.HIS_WORD_PRESENT_IS_ONGOING`).
4. *"SAFE conversion"* filed as a job. *"It is signing a paper."*
5. *"Castle Island Ventures"* filed as a partnership: a fund, an ordinary moment
   at his company (`landmark_projection.A_RECORD_IS_FILED_WHERE_IT_BELONGS`).
6. Two answers the readers could not read: *"This happened in the middle of
   sixth grade for James."* (`chronology.A_SCHOOL_GRADE_IS_AN_AGE_ON_THE_SCHOOL_CALENDAR`)
   and *"Six to eight months ago"* (`chronology.N_MONTHS_AGO_IS_COUNTED_BACK_FROM_THE_TELLING`).

The records here are the shapes his vault holds, byte for byte where it
matters. Synthetic vault only; NEVER references ~/Workspace/dave.
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

import answer_placement as ap  # noqa: E402
import chronology as chrono  # noqa: E402
import classifier_claims as cc  # noqa: E402
import landmark_projection as lp  # noqa: E402
import landmarks_interaction as li  # noqa: E402
import resolver  # noqa: E402
import temporal_claims as tc  # noqa: E402
import temporal_projection as tp  # noqa: E402
import temporal_publication as pub  # noqa: E402
import temporal_store as ts  # noqa: E402
import temporal_timeline as tt  # noqa: E402
import timeline  # noqa: E402

NOW = "2026-09-25T12:00:00Z"
OWNER_BIRTH = "1981-07-11"
SON_BIRTH = "2013-05-10"


def when(text: str, *, basis: str = "stated", confidence: str = "certain",
         provenance: list | None = None) -> dict:
    grain = {4: "year", 7: "month", 10: "day"}[len(text)]
    return {"best": text, "earliest": text, "latest": text, "granularity": grain,
            "confidence": confidence, "basis": basis, "anchors": [],
            "provenance": provenance or []}


def inferred(text: str, stay: str) -> dict:
    """A bound the old offer reader inferred from a residence stay."""
    return when(text, basis="anchor", confidence="inferred",
                provenance=[{"basis": "inferred", "claim": f"from the dates of the {stay} stay"}])


#: His landmarks, in the shapes his vault holds them.
SEED = {
    "birth": [{"domain": "birth", "label": "Birth", "date": when(OWNER_BIRTH)}],
    "residences": [
        {"domain": "residences", "label": "Hope", "nickname": "Hope",
         "address": "2624 E Hope St, Mesa, AZ", "city": "Mesa, Arizona",
         "span": {"start": when("1995-06"), "end": when("1997-06")}},
        {"domain": "residences", "label": "Williams", "nickname": "Williams",
         "address": "701 N Williams, Mesa, AZ", "city": "Mesa, Arizona",
         "span": {"start": when("1997-06"), "end": when("2000-08")}},
    ],
    "schools": [
        {"domain": "schools", "grades": "9th and 10th grade", "label": "Mountain View",
         "name": "Mountain View",
         "span": {"start": inferred("1995-06", "Hope"), "end": inferred("1997-06", "Hope")}},
        {"domain": "schools", "grades": "11th and 12th", "label": "Mountain View",
         "name": "Mountain View", "place": "Mesa, Arizona",
         "span": {"start": inferred("1997-06", "Williams"),
                  "end": inferred("2000-08", "Williams")}},
    ],
    "work": [
        {"domain": "work", "label": "Etherfuse", "what": "Chief Executive Officer",
         "where": "Mexico City, Mexico",
         "span": {"start": when("2022-05", provenance=[
             {"claim": "May 2022 - Present",
              "source": "manual:2026-08-24-my-total-history-of-work-without-any-specificity"}])}},
        {"domain": "work", "label": "Memo", "what": "Memo",
         "span": {"start": inferred("2019-08", "Christamon")}},
    ],
    "partnerships": [
        {"domain": "partnerships", "label": "Katie Ann Merrill", "who": "Katie Ann Merrill",
         "date": when("2007-01-11", provenance=[
             {"claim": "I married Katie Ann Merrill January 11th, 2007."}])},
    ],
    "children": [
        {"domain": "children", "label": "James Everett Taylor", "who": "James Everett Taylor",
         "date": when(SON_BIRTH)},
    ],
}

#: The three misfiled shapes, byte for byte what the reflect filings wrote.
KATIE_SCHOOL = {"date": when("2006", basis="anchor"), "domain": "schools",
                "label": "Katie Ann Merrill"}
SAFE = {"date": when("2025-08-28", basis="anchor"), "domain": "work",
        "label": "SAFE conversion", "what": "SAFE conversion terms negotiation"}
CASTLE_SEED = {"date": when("2024-04", basis="anchor"), "domain": "partnerships",
               "label": "Castle Island Ventures", "subject": "Etherfuse",
               "who": "Castle Island Ventures"}
CASTLE_SERIES_A = {**CASTLE_SEED, "date": when("2025-05", basis="anchor")}


class VaultTestCase(unittest.TestCase):

    def setUp(self) -> None:
        self.vault = Path(tempfile.mkdtemp(prefix="lifehug-records-",
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

    def drawn(self, domain: str) -> list[dict]:
        return list(timeline.load_landmarks().get(domain) or ())

    def projection(self) -> dict:
        pub.publish(self.vault, roster_snapshot=(), now=NOW, full=True)
        return pub.read_projection(self.vault) or {}

    def nodes(self, projection: dict, label: str) -> list[dict]:
        return [node for node in projection.get("nodes") or ()
                if str(node.get("label") or "").lower() == label.lower()]

    def tell(self, text: str, *, claim_type: str = "date", temporal_value: object = None,
             mention: str = "", subject: str = "self", event_kind: str = "moment") -> None:
        """File one telling of his, the way a reader of a message files it."""
        def claims_for(ref):
            payload = {
                "claim_type": claim_type, "subject_mention": subject,
                "event_kind": event_kind, "event_mention": mention or text[:60],
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

    def graduated(self) -> None:
        self.tell("I graduated from high school in 1999.",
                  temporal_value=chrono.parse_stated_date("1999").to_dict(),
                  mention="high school graduation", subject="high school graduation",
                  event_kind="graduation")

    def file_raw(self, domain: str, record: dict) -> str:
        """File a record the way the reflect filing did BEFORE the rule."""
        filed = lp.file_landmark_record(
            self.vault, domain, dict(record), ordinal=lp.next_ordinal(self.vault),
            extractor_version=lp.LIVE_EXTRACTOR, now=NOW)
        timeline.redraw_landmarks()
        return filed["source_ref"].source_id

    def run_refile(self, *, apply: bool) -> str:
        import lifehug

        args = argparse.Namespace(apply=apply, json=False)
        buffer = io.StringIO()
        with mock.patch.object(lifehug, "REPO_DIR", self.vault), \
                contextlib.redirect_stdout(buffer):
            self.assertEqual(lifehug.cmd_landmark_refile(args), 0)
        return buffer.getvalue()


# --------------------------------------------------------------------------
# 1. Mountain View ends at his graduation; junior year still holds
# --------------------------------------------------------------------------


class MountainViewTests(VaultTestCase):

    def stays(self) -> list[tuple]:
        return [(entry.get("grades"),
                 entry["span"]["start"]["best"], entry["span"]["end"]["best"])
                for entry in self.drawn("schools") if entry.get("label") == "Mountain View"]

    def stretch_ends(self) -> dict:
        """Each telling's own end, as the fold reads it."""
        index = ts.fold_active_index(self.vault, full=True)
        sources = lp.load_landmark_sources(self.vault)
        grades = {row["source_id"]: row["record"].get("grades") for row in sources
                  if row["domain"] == "schools"}
        return {grades[c["source_ref"]["source_id"]]: c["temporal_value"]["best"]
                for c in lp.read_landmark_dates(ts.active_claims(index), sources)
                if c["source_ref"]["source_id"] in grades and c.get("event_kind") == "ended"}

    def test_two_grade_stretches_are_one_continuous_tenure(self) -> None:
        self.assertEqual(self.stays(),
                         [("9th and 10th grade; 11th and 12th", "1995-06", "2000-08")])

    def test_without_a_stated_graduation_the_inferred_end_stands(self) -> None:
        # The rule reads his graduation; with none, the stay's end is untouched.
        self.assertEqual(self.stretch_ends()["11th and 12th"], "2000-08")

    def test_his_stated_graduation_ends_the_school(self) -> None:
        self.graduated()
        timeline.redraw_landmarks()
        self.assertEqual(self.stays(),
                         [("9th and 10th grade; 11th and 12th", "1995-06", "1999-06")])
        self.assertEqual(self.stretch_ends(), {"9th and 10th grade": "1997-06",
                                               "11th and 12th": "1999-06"})
        end = next(entry for entry in self.drawn("schools")
                   if entry.get("label") == "Mountain View")["span"]["end"]
        self.assertEqual(end["provenance"][0]["claim"],
                         "from your stated graduation from Mountain View")
        self.assertEqual(end["basis"], "anchor")

    def test_the_school_node_ends_there_too(self) -> None:
        self.graduated()
        node = self.nodes(self.projection(), "Mountain View")
        self.assertEqual(len(node), 1)
        value = node[0]["best_temporal_value"]
        self.assertEqual((value["earliest"], value["latest"]), ("1995-06", "1999-06"))

    def test_a_graduation_of_somebody_else_ends_nothing(self) -> None:
        self.tell("Dad graduated from high school in 1972.",
                  temporal_value=chrono.parse_stated_date("1972").to_dict(),
                  mention="Dad's high school graduation", subject="Dad",
                  event_kind="graduation")
        timeline.redraw_landmarks()
        self.assertEqual(self.stretch_ends()["11th and 12th"], "2000-08")

    def test_junior_year_is_still_august_1997_to_june_1998(self) -> None:
        self.assertEqual(chrono.school_year_record(OWNER_BIRTH, 11).best, "1997-08/1998-06")
        self.assertIn("11th grade (junior) -> 1997-08 to 1998-06",
                      resolver.grade_table(OWNER_BIRTH))
        self.assertEqual(resolver.grade_table(OWNER_BIRTH),
                         chrono.grade_table_lines(OWNER_BIRTH))


#: His 15 September document: "School: Longfellow Elementary" under three
#: consecutive homes, each stretch filed with the HOME's dates.
LONGFELLOW = [
    {"domain": "schools", "label": "Longfellow Elementary", "name": "Longfellow Elementary",
     "span": {"start": inferred("1982-08", "Figers House"),
              "end": inferred("1986-06", "Figers House")}},
    {"domain": "schools", "grades": "2nd grade", "label": "Longfellow Elementary",
     "name": "Longfellow Elementary",
     "span": {"start": inferred("1988-06", "Our house (owned)"),
              "end": inferred("1989-06", "Our house (owned)")}},
    {"domain": "schools", "grades": "PK and 1st grade", "label": "Longfellow Elementary",
     "name": "Longfellow Elementary",
     "span": {"start": inferred("1986-06", "Fisches House"),
              "end": inferred("1988-06", "Fisches House")}},
]


class LongfellowTests(VaultTestCase):

    def setUp(self) -> None:
        super().setUp()
        for record in LONGFELLOW:
            lp.file_landmark_record(self.vault, "schools", dict(record),
                                    ordinal=lp.next_ordinal(self.vault),
                                    extractor_version=lp.LIVE_EXTRACTOR, now=NOW)
        timeline.redraw_landmarks()

    def longfellow(self) -> list[dict]:
        return [e for e in self.drawn("schools") if e.get("label") == "Longfellow Elementary"]

    def test_three_stretches_are_one_continuous_school(self) -> None:
        entries = self.longfellow()
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["grades"], "PK and 1st grade; 2nd grade")
        self.assertEqual(entries[0]["span"]["end"]["best"], "1989-06")

    def test_he_did_not_start_school_at_one(self) -> None:
        start = self.longfellow()[0]["span"]["start"]
        # Born 1981-07-11: kindergarten August 1986, pre-kindergarten August
        # 1985; the Figers House stay ended June 1986.
        self.assertEqual((start["earliest"], start["latest"]), ("1985-08", "1986-06"))
        self.assertIn("Figers House", start["provenance"][0]["claim"])

    def test_the_school_node_agrees(self) -> None:
        node = self.nodes(self.projection(), "Longfellow Elementary")
        self.assertEqual(len(node), 1)
        self.assertEqual(node[0]["best_temporal_value"]["earliest"], "1985-08")
        self.assertEqual(node[0]["best_temporal_value"]["latest"], "1989-06")

    def test_the_reading_moves_the_drawing_and_not_the_node(self) -> None:
        index = ts.fold_active_index(self.vault, full=True)
        sources = lp.load_landmark_sources(self.vault)
        first = next(row["source_id"] for row in sources
                     if row["domain"] == "schools" and not row["record"].get("grades")
                     and row["record"].get("label") == "Longfellow Elementary")
        read = [c for c in lp.read_landmark_dates(ts.active_claims(index), sources)
                if c["source_ref"]["source_id"] == first]
        started = next(c for c in read if c["event_kind"] == "started")
        self.assertEqual(started["temporal_value"]["earliest"], "1985-08")
        # The episode is still discriminated by the start it was FILED with.
        self.assertEqual(lp._span_start_value(read), "1982-08")
        validated = tc.validate_temporal_claim(started)
        self.assertEqual(lp.filed_value_of(validated["temporal_value"])["best"], "1982-08")

    def test_a_school_he_returned_to_years_later_is_a_second_tenure(self) -> None:
        later = {"domain": "schools", "label": "Longfellow Elementary",
                 "name": "Longfellow Elementary", "grades": "5th grade",
                 "span": {"start": when("1991-08"), "end": when("1992-06")}}
        lp.file_landmark_record(self.vault, "schools", later, ordinal=lp.next_ordinal(self.vault),
                                extractor_version=lp.LIVE_EXTRACTOR, now=NOW)
        timeline.redraw_landmarks()
        self.assertEqual(len(self.longfellow()), 2)


class GradeKeyTests(unittest.TestCase):
    """The key alone: grades, overlap, and the incremental fill."""

    ROW = {"collection": "sequence"}

    def entry(self, start: str, end: str, grades: str | None = None) -> dict:
        record = {"span": {"start": when(start), "end": when(end)}}
        if grades:
            record["grades"] = grades
        return record

    def test_different_grades_never_join(self) -> None:
        self.assertFalse(li.same_landmark_stay(
            self.entry("1995-06", "1997-06", "9th and 10th grade"),
            self.entry("1997-06", "2000-08", "11th and 12th"), self.ROW))

    def test_the_same_grades_spelled_twice_join(self) -> None:
        self.assertTrue(li.same_landmark_stay(
            self.entry("1995-06", "1997-06", "9th and 10th grade"),
            self.entry("1995-08", "1997-06", "9th and 10th"), self.ROW))

    def test_one_side_graded_joins_only_what_it_overlaps(self) -> None:
        # Longfellow: 1982-08..1986-06 (no grades), then "PK and 1st grade"
        # from 1986-06 — a stretch that abuts, not the same stretch.
        self.assertFalse(li.same_landmark_stay(
            self.entry("1982-08", "1986-06"),
            self.entry("1986-06", "1988-06", "PK and 1st grade"), self.ROW))
        self.assertTrue(li.same_landmark_stay(
            self.entry("1995-06", "1999-06"),
            self.entry("1995-06", "1999-06", "9th through 12th"), self.ROW))

    def test_an_undated_telling_still_fills_in(self) -> None:
        self.assertTrue(li.same_landmark_stay(
            self.entry("1995-06", "1997-06", "9th and 10th grade"),
            {"grades": "sophomore or junior year"}, self.ROW))


# --------------------------------------------------------------------------
# 3. Etherfuse is ongoing, and only because he said so
# --------------------------------------------------------------------------


class OngoingTests(VaultTestCase):

    def test_may_2022_present_is_ongoing(self) -> None:
        etherfuse = next(e for e in self.drawn("work") if e.get("label") == "Etherfuse")
        self.assertTrue(etherfuse.get("ongoing"))
        self.assertNotIn("end", etherfuse["span"])

    def test_a_start_with_no_end_and_no_words_is_not_ongoing(self) -> None:
        memo = next(e for e in self.drawn("work") if e.get("label") == "Memo")
        self.assertFalse(memo.get("ongoing"))

    def test_an_end_closes_it(self) -> None:
        entry = {"span": {"start": SEED["work"][0]["span"]["start"], "end": when("2027-01")}}
        self.assertFalse(lp.stated_as_ongoing(entry, {"collection": "sequence"}))

    def test_an_inferred_clause_is_never_his_word(self) -> None:
        entry = {"span": {"start": when("2022-05", provenance=[
            {"basis": "inferred", "claim": "from the dates of the Present stay"}])}}
        self.assertFalse(lp.stated_as_ongoing(entry, {"collection": "sequence"}))


# --------------------------------------------------------------------------
# 2, 4, 5. A person is not a school, an event is not a job, a fund is not a partner
# --------------------------------------------------------------------------


class MisfiledRuleTests(unittest.TestCase):

    PEOPLE = frozenset({"katie ann merrill", "james everett taylor"})
    ORGS = frozenset({"etherfuse", "memo"})

    def reason(self, domain: str, record: dict) -> str | None:
        return lp.misfiled_landmark(domain, record, people=self.PEOPLE,
                                    organizations=self.ORGS)

    def test_the_three_incidents(self) -> None:
        self.assertEqual(self.reason("schools", KATIE_SCHOOL), lp.PERSON_IS_NOT_A_SCHOOL)
        self.assertEqual(self.reason("work", SAFE), lp.EVENT_IS_NOT_A_JOB)
        self.assertEqual(self.reason("partnerships", CASTLE_SEED),
                         lp.ORGANIZATION_IS_NOT_A_PARTNER)

    def test_his_real_entries_stand(self) -> None:
        for domain, rows in SEED.items():
            for record in rows:
                self.assertIsNone(self.reason(domain, record), record)
        # A school named for a person he never named, a job with a span, his
        # sister's husband: all stand.
        self.assertIsNone(self.reason("schools", {"domain": "schools", "label": "Horace Mann",
                                                  "date": when("1990")}))
        self.assertIsNone(self.reason("work", {**SAFE, "span": {"start": when("2025-08")}}))
        self.assertIsNone(self.reason("partnerships", {"domain": "partnerships",
                                                       "label": "Brett", "who": "Brett",
                                                       "subject": "Jacque"}))

    def test_a_fund_by_its_name_alone(self) -> None:
        self.assertEqual(self.reason("partnerships", {"domain": "partnerships",
                                                      "who": "Sequoia Capital"}),
                         lp.ORGANIZATION_IS_NOT_A_PARTNER)


class RefileTests(VaultTestCase):

    def setUp(self) -> None:
        super().setUp()
        self.katie = self.file_raw("schools", KATIE_SCHOOL)
        self.safe = self.file_raw("work", SAFE)
        self.castle = [self.file_raw("partnerships", CASTLE_SERIES_A),
                       self.file_raw("partnerships", CASTLE_SEED)]

    def test_before_they_are_drawn_as_landmarks(self) -> None:
        self.assertIn("Katie Ann Merrill", [e.get("label") for e in self.drawn("schools")])
        self.assertIn("SAFE conversion", [e.get("label") for e in self.drawn("work")])
        self.assertIn("Castle Island Ventures",
                      [e.get("label") for e in self.drawn("partnerships")])

    def test_the_dry_run_names_exactly_the_four_and_writes_nothing(self) -> None:
        printed = self.run_refile(apply=False)
        self.assertIn("4 record(s) would be refiled", printed)
        self.assertFalse((self.vault / lp.REFILE_SOURCES_DIR).exists())

    def test_apply_refiles_and_a_second_apply_files_nothing(self) -> None:
        self.run_refile(apply=True)
        self.assertNotIn("Katie Ann Merrill", [e.get("label") for e in self.drawn("schools")])
        self.assertNotIn("SAFE conversion", [e.get("label") for e in self.drawn("work")])
        self.assertEqual([e.get("label") for e in self.drawn("partnerships")],
                         ["Katie Ann Merrill"])
        files = sorted((self.vault / lp.REFILE_SOURCES_DIR).glob("*.md"))
        self.assertEqual(len(files), 4)
        self.assertIn("no misfiled landmark records", self.run_refile(apply=True))
        self.assertEqual(sorted((self.vault / lp.REFILE_SOURCES_DIR).glob("*.md")), files)

    def test_the_event_stays_an_ordinary_moment_and_the_person_is_retired(self) -> None:
        self.run_refile(apply=True)
        projection = self.projection()
        safe = self.nodes(projection, "SAFE conversion")
        self.assertEqual(len(safe), 1)
        self.assertEqual(safe[0]["event_kind"], "moment")
        self.assertEqual(safe[0]["best_temporal_value"]["best"], "2025-08-28")
        # Only his wedding is drawn under her name; the "school" is gone.
        self.assertEqual([n["event_kind"] for n in self.nodes(projection, "Katie Ann Merrill")],
                         ["transition"])

    def test_castle_island_is_one_moment_and_its_two_dates_stay_a_question(self) -> None:
        self.run_refile(apply=True)
        projection = self.projection()
        castle = self.nodes(projection, "Castle Island Ventures")
        self.assertEqual(len(castle), 1)
        self.assertEqual(castle[0]["event_kind"], "moment")
        cards = [item for item in projection.get("work_items") or ()
                 if item.get("node_ref") == castle[0]["node_id"]]
        self.assertEqual([item["kind"] for item in cards], ["contradiction"])
        self.assertIn("April 2024", cards[0]["prompt_intent"])
        self.assertIn("May 2025", cards[0]["prompt_intent"])

    def test_a_refiled_record_read_back_by_the_classifier_is_the_record(self) -> None:
        self.run_refile(apply=True)
        paths = lp.refiled_record_paths(self.vault)
        self.assertEqual(len(paths), 4)
        for source_id in [self.katie, self.safe] + self.castle:
            self.assertIn(f"sources/landmarks/{source_id.split(':')[1]}.md", paths)


class TheWriteSeatRefilesTests(VaultTestCase):

    def test_a_new_misfiled_record_is_refiled_the_moment_it_lands(self) -> None:
        findings: list = []
        saved = timeline.save_landmark("work", dict(SAFE), findings=findings)
        self.assertEqual(saved["not_written"], lp.EVENT_IS_NOT_A_JOB)
        self.assertEqual(saved["refiled_as"], lp.REFILE_AS_MOMENT)
        self.assertNotIn("SAFE conversion", [e.get("label") for e in self.drawn("work")])
        self.assertEqual([f["lint"] for f in findings], ["landmark_refiled"])
        self.assertEqual(self.nodes(self.projection(), "SAFE conversion")[0]["event_kind"],
                         "moment")

    def test_a_real_record_is_filed_as_ever(self) -> None:
        saved = timeline.save_landmark("work", {"domain": "work", "label": "Boeing",
                                                "what": "Boeing",
                                                "span": {"start": "2012", "end": "2015"}})
        self.assertNotIn("not_written", saved)
        self.assertIn("Boeing", [e.get("label") for e in self.drawn("work")])


# --------------------------------------------------------------------------
# 6. "middle of sixth grade for James" and "six to eight months ago"
# --------------------------------------------------------------------------


class GradeReadingTests(unittest.TestCase):

    def test_his_answer(self) -> None:
        found = chrono.school_grade_of("This happened in the middle of sixth grade for James.")
        self.assertEqual((found["grade"], found["part"], found["speaker"], found["who"]),
                         (6, "middle", "named", "James"))
        record = chrono.school_year_record(SON_BIRTH, 6, part="middle")
        self.assertEqual((record.earliest, record.latest), ("2024-12", "2025-02"))
        self.assertEqual(record.basis, "age")

    def test_the_shapes(self) -> None:
        for text, grade, high in (("freshman year", 9, None), ("in kindergarten", 0, None),
                                  ("6th grade", 6, None), ("grade 3", 3, None),
                                  ("sixth or seventh grade", 6, 7),
                                  ("during junior and senior year", 11, 12)):
            found = chrono.school_grade_of(text)
            self.assertEqual((found["grade"], found["grade_high"]), (grade, high), text)
        for text in ("junior high", "freshman year of college", "sixth grade in 1993"):
            self.assertIsNone(chrono.school_grade_of(text), text)

    def test_whose_grade(self) -> None:
        self.assertEqual(chrono.school_grade_of("when I was in 6th grade")["speaker"], "narrator")
        self.assertEqual(chrono.school_grade_of(
            "Dad got laid off, narrator was probably in third grade")["speaker"], "narrator")
        self.assertEqual(chrono.school_grade_of("James's freshman year")["who"], "James")
        self.assertIsNone(chrono.school_grade_of("Mother homeschools him in sixth grade")["speaker"])

    def test_the_answer_seat_reads_it_on_the_cards_own_person(self) -> None:
        reading = ap.answer_reading("This happened in the middle of sixth grade for James.",
                                    captured="2026-09-24T18:51:47Z",
                                    question="When did James Everett moved between baseball teams happen?")
        self.assertEqual(reading["reading"], ap.READING_GRADE)
        self.assertEqual(reading["temporal_value"]["grade"], 6)
        card = {"node_ref": "node:ccc3c95f86df77e67861a1b9",
                "subject_ref": "person/james-everett-taylor",
                "label": "James Everett moved between baseball teams", "event_kind": "moment"}
        ref = {"source_id": "conversation:msg-3737a80061e5fd4938204b9b",
               "revision": "sha256:" + "0" * 64,
               "source_path": "sources/conversations/msg-3737a80061e5fd4938204b9b.md"}
        claim = ap.answer_claim(card, reading, source_ref=ref, quote="middle of sixth grade")
        self.assertEqual(claim["subject_mention"], "person/james-everett-taylor")
        self.assertEqual(claim["temporal_value"]["grade_part"], "middle")
        # Somebody the card is not about is that person's grade.
        other = ap.answer_claim(card, ap.answer_reading("That was Charlee's sixth grade."),
                                source_ref=ref, quote="x")
        self.assertEqual(other["subject_mention"], "Charlee")

    def test_the_classifier_seat_reads_the_same_way(self) -> None:
        event = {"title": "Dad got laid off", "subject": "narrator's father",
                 "description": "Dad got laid off, narrator was probably in third grade",
                 "when_hint": "I was probably in third grade, maybe even younger"}
        reading = cc.grade_reading(event)
        self.assertEqual(reading["temporal_value"]["grade"], 3)
        self.assertEqual(reading["subject_mention"], "self")
        self.assertEqual(cc.temporal_reading(event)["claim_type"], "age")


class GradeFoldTests(unittest.TestCase):
    """The fold measures a grade against the SUBJECT's birth."""

    def claim(self, *, claim_type: str, subject: str, value: object, event_kind: str,
              label: str, n: int) -> dict:
        return tc.validate_temporal_claim({
            "source_kind": "import", "claim_type": claim_type, "subject_mention": subject,
            "event_kind": event_kind, "event_mention": label,
            "event_ref": tp.derive_node_id(node_kind="event", event_kind=event_kind,
                                           subject_refs=[subject], discriminator=label),
            "evidence": [{"quote": label}], "basis": "explicit", "confidence": 0.8,
            "extractor_version": "classifier-claims/rule:5",
            "source_ref": {"source_id": f"classification:answers-x#{n:012x}",
                           "revision": "sha256:" + f"{n:064x}", "source_path": "answers/x.md"},
            "temporal_value": value}, now=NOW)

    def test_middle_of_sixth_grade_for_james_places_the_moment(self) -> None:
        claims = [
            self.claim(claim_type="date", subject="self", event_kind="birth",
                       value=chrono.parse_stated_date(OWNER_BIRTH).to_dict(),
                       label="my birth", n=1),
            self.claim(claim_type="date", subject="James Everett Taylor", event_kind="birth",
                       value=chrono.parse_stated_date(SON_BIRTH).to_dict(),
                       label="James Everett Taylor's birth", n=2),
            self.claim(claim_type="age", subject="James Everett Taylor", event_kind="moment",
                       value=chrono.school_grade_quantity(chrono.school_grade_of(
                           "the middle of sixth grade")),
                       label="James Everett moved between baseball teams", n=3),
        ]
        index = {"claims": claims, "active_claim_ids": [c["claim_id"] for c in claims]}
        result = tt.derive_calculated_timeline(index, landmark_entries=(), now=NOW)
        node = next(n for n in result.nodes
                    if n["label"].lower() == "james everett moved between baseball teams")
        value = node["best_temporal_value"]
        self.assertEqual((value["earliest"], value["latest"]), ("2024-12", "2025-02"))

    def test_a_grade_is_part_of_the_claims_identity(self) -> None:
        grade = chrono.school_grade_quantity(chrono.school_grade_of("sixth grade"))
        band = {k: v for k, v in grade.items() if k not in ("grade", "text")}
        one = self.claim(claim_type="age", subject="self", event_kind="moment",
                         value=grade, label="x", n=9)
        two = self.claim(claim_type="age", subject="self", event_kind="moment",
                         value=band, label="x", n=9)
        self.assertNotEqual(one["claim_id"], two["claim_id"])
        self.assertEqual(one["temporal_value"]["grade"], 6)


class MonthsAgoTests(unittest.TestCase):

    def test_six_to_eight_months_ago(self) -> None:
        record = chrono.from_recency(
            "2026-09-24T18:51:47Z",
            "Six to eight months ago, the author and James were hanging out every day "
            "practicing baseball")
        self.assertEqual((record.earliest, record.latest), ("2026-01", "2026-03"))
        self.assertEqual(record.basis, "stated")
        self.assertEqual(record.provenance[0]["source"], chrono.MONTHS_AGO_PROVENANCE_SOURCE)

    def test_the_shapes(self) -> None:
        told = "2026-09-24"
        self.assertEqual(chrono.from_recency(told, "3 months ago").best, "2026-06")
        self.assertEqual(chrono.from_recency(told, "about three months ago").best,
                         "2026-05/2026-07")
        self.assertEqual(chrono.from_recency(told, "twenty-one months ago").best, "2024-12")
        self.assertIsNone(chrono.from_months_ago(told, "six months ago in 1998"))
        # A plain recency word still reads as before.
        self.assertEqual(chrono.from_recency(told, "recently").earliest, "2026-03-24")

    def test_the_classifier_seat_places_the_moment(self) -> None:
        event = {"title": "Daily baseball practice together", "subject": "self",
                 "description": "Six to eight months ago, the author and James were "
                                "hanging out every day practicing baseball",
                 "when_hint": "six to eight months ago"}
        reading = cc.temporal_reading(event, {"captured": "2026-09-24T18:51:47Z"})
        self.assertEqual(reading["claim_type"], "date")
        self.assertEqual(reading["temporal_value"]["best"], "2026-01/2026-03")


class ARereadIsALaterVersionOfTheSameReaderTests(unittest.TestCase):
    """An answer filed as a telling, read again as a grade, supersedes itself."""

    def setUp(self) -> None:
        self.vault = Path(tempfile.mkdtemp(prefix="lifehug-reread-",
                                           dir="/private/tmp" if Path("/private/tmp").is_dir() else None))
        self.addCleanup(shutil.rmtree, self.vault, ignore_errors=True)
        ref = ts.promote_conversational_source(
            self.vault, "This happened in the middle of sixth grade for James.",
            {"session_ref": "conversation:cand:work_item:work:2f5dec9f0e57ad5a31b9947a",
             "turn_ref": "0", "captured_at": "2026-09-24T18:51:47Z"})
        self.path = ref.source_path
        self.card = {"node_ref": "node:ccc3c95f86df77e67861a1b9",
                     "subject_ref": "person/james-everett-taylor",
                     "label": "James Everett moved between baseball teams",
                     "event_kind": "moment", "work_item_id": "work:2f5dec9f0e57ad5a31b9947a"}

    def file(self, reading: dict) -> dict:
        return ap.file_answer(self.vault, source_path=self.path, card=self.card,
                              reading=reading, text="middle of sixth grade for James", now=NOW)

    def test_the_new_reading_stands_and_the_telling_is_superseded(self) -> None:
        first = self.file(ap.telling_reading())
        grade = ap.grade_reading("This happened in the middle of sixth grade for James.")
        second = self.file(grade)
        self.assertNotEqual(first["receipt_path"], second["receipt_path"])
        self.assertIn("/reread:", Path(second["receipt_path"]).read_text())
        active = [c for c in ts.active_claims(ts.fold_active_index(self.vault, full=True))
                  if c["source_ref"]["source_path"] == self.path]
        self.assertEqual([c["claim_type"] for c in active], ["age"])
        # A re-run finds its own receipt and writes nothing new.
        self.assertEqual(self.file(grade)["receipt_path"], second["receipt_path"])


class RuleVersionTests(unittest.TestCase):

    def test_the_rule_version_moved(self) -> None:
        self.assertEqual(tt.CALCULATION_RULE_VERSION, "timeline-rules:25")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
