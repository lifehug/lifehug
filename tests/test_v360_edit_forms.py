"""v360 (owner, 2026-09-25): the owner's EDIT FORMS (`landmark_edit`).

"For each landmark when I press the play button, I want just to pop up a form
with every field … when I press play it adds it as user updated." And for the
Cornerstones grid: "Darvin Burrows Beauchamp is my grandpa, and it's in Others.
There needs to be a way I can … change the category."

Every record is synthetic; nothing here reads a real vault.
"""

from __future__ import annotations

import copy
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

import entity_roster  # noqa: E402
import landmark_edit as le  # noqa: E402
import landmark_projection as lp  # noqa: E402
import temporal_publication as pub  # noqa: E402
import temporal_store as ts  # noqa: E402
import timeline  # noqa: E402

NOW = "2026-09-25T12:00:00Z"


def when(text: str) -> dict:
    grain = {4: "year", 7: "month", 10: "day"}[len(text)]
    return {"best": text, "earliest": text, "latest": text, "granularity": grain,
            "confidence": "certain", "basis": "stated", "anchors": [], "provenance": []}


def stay(label: str, address: str, city: str, start: str, end: str, **extra) -> dict:
    return {"domain": "residences", "label": label, "nickname": label, "address": address,
            "city": city, "span": {"start": when(start), "end": when(end)}, **extra}


SEED = {
    "birth": [{"domain": "birth", "year": "1981", "month": "07", "day": "11",
               "date": when("1981-07-11")}],
    "residences": [
        stay("Figers House", "1656 E 2nd Ave, Mesa, AZ 85204", "Mesa, Arizona",
             "1982-08", "1986-06", link="https://maps.example/figers"),
        stay("Thunderhead", "13353 Thunderhead St, San Diego, CA 92129",
             "San Diego, California", "1989-06", "1990-06",
             place_ref="place/residence-thunderhead", link="https://maps.example/thunder"),
        stay("Hope", "2624 E Hope St, Mesa, AZ", "Mesa, Arizona", "1995-06", "1997-06"),
    ],
    "schools": [
        {"domain": "schools", "label": "Mountain View", "name": "Mountain View",
         "grades": "11th and 12th", "place": "Mesa, Arizona",
         "span": {"start": when("1997-08"), "end": when("1999-06")}},
    ],
    "family": [
        {"domain": "family", "label": "Darvin Burrows Beauchamp",
         "who": "Darvin Burrows Beauchamp", "date": when("1929-09-30")},
    ],
    "losses": [
        {"domain": "losses", "label": "Darvin Burrows Beauchamp",
         "who": "Darvin Burrows Beauchamp", "date": when("1996")},
    ],
}

ROSTER = {"version": 1, "type": "person", "entities": [
    {"name": "Desiree Taylor", "slug": "desiree-taylor", "relationship": "parent",
     "aliases": ["mom", "my mom"], "born": when("1955-06-19")},
]}


class FormVault(unittest.TestCase):
    """A synthetic vault bound the way `lifehug.py` binds the real one."""

    def setUp(self) -> None:
        self.vault = Path(tempfile.mkdtemp(prefix="lifehug-forms-",
                                           dir="/private/tmp" if Path("/private/tmp").is_dir() else None))
        self.addCleanup(shutil.rmtree, self.vault, ignore_errors=True)
        self.store = self.vault / "state" / "landmarks.json"
        rosters = self.vault / "state" / "entity_rosters"
        rosters.mkdir(parents=True, exist_ok=True)
        (rosters / "person.json").write_text(json.dumps(ROSTER, indent=2) + "\n", encoding="utf-8")
        (self.vault / "profile.yaml").write_text("name: Dave\nfull_name: David James Taylor\n",
                                                 encoding="utf-8")
        for patch in (mock.patch.object(timeline, "LANDMARKS_STORE", self.store),
                      mock.patch.object(timeline, "_projection_vault_root", lambda: self.vault),
                      mock.patch.object(entity_roster, "ENTITY_DIR", rosters)):
            patch.start()
            self.addCleanup(patch.stop)
        self.store.write_text(json.dumps({"version": 1, "domains": copy.deepcopy(SEED)},
                                         indent=2) + "\n", encoding="utf-8")
        timeline.flip_landmarks_if_needed()

    # -- reading back ---------------------------------------------------------

    def projection(self) -> dict:
        return pub.read_projection(self.vault) or {}

    def view_landmark(self, domain: str, label: str) -> dict | None:
        view = self.projection().get("landmarks_view") or {}
        for row in view.get("domains") or ():
            if row["domain"] == domain:
                return next((lm for lm in row["landmarks"] if lm["label"] == label), None)
        return None

    def sources(self) -> list[Path]:
        return sorted((self.vault / "sources" / "landmarks").glob("entry-*.md"))

    def roster(self) -> dict:
        path = self.vault / "state" / "entity_rosters" / "person.json"
        return {row["slug"]: row for row in json.loads(path.read_text())["entities"]}


class TheLandmarkFormTests(FormVault):

    def setUp(self) -> None:
        super().setUp()
        pub.publish(self.vault, now=NOW, full=True)

    def thunderhead_form(self, **changes) -> dict:
        landmark = self.view_landmark("residences", "Thunderhead")
        self.assertIsNotNone(landmark)
        fields = {"nickname": "Thunderhead", "address": landmark["address_full"],
                  "city": "San Diego", "state": "California", "country": "United States",
                  "link": landmark["link"]}
        fields.update(changes.pop("fields", {}))
        stays = [{"ref": s["ref"], "from": s["start"], "to": s["end"]} for s in landmark["stays"]]
        for index, override in changes.pop("stays", {}).items():
            stays[index].update(override)
        return {"mode": "save", "kind": "residences", "fields": fields, "stays": stays}

    def test_every_stay_carries_the_ref_it_was_drawn_under(self) -> None:
        landmark = self.view_landmark("residences", "Thunderhead")
        self.assertEqual(landmark["stays"][0]["ref"],
                         {"domain": "residences", "entry_key": "thunderhead", "slot": 0})
        self.assertEqual(landmark["refs"], [landmark["stays"][0]["ref"]])
        self.assertEqual(landmark["link"], "https://maps.example/thunder")
        # The drawing itself never carries a ref (byte-identical landmarks.json).
        drawn = json.loads(self.store.read_text())["domains"]["residences"]
        self.assertFalse(any("ref" in entry for entry in drawn))

    def test_editing_a_homes_dates_moves_the_stay(self) -> None:
        before = self.sources()
        result = le.edit_landmark(self.vault, self.thunderhead_form(
            stays={0: {"from": "1989-08", "to": "1990-09-15"}}))
        self.assertEqual(len(result["filed"]), 1)
        self.assertEqual(len(result["corrections"]), 1)
        landmark = self.view_landmark("residences", "Thunderhead")
        self.assertEqual((landmark["stays"][0]["start"], landmark["stays"][0]["end"]),
                         ("1989-08", "1990-09-15"))
        # His record is filed as stated; the old telling stays on disk.
        self.assertTrue(set(before) <= set(self.sources()))
        self.assertEqual(landmark["place_ref"], "place/residence-thunderhead")
        entry = next(e for e in timeline.load_landmarks()["residences"] if e["label"] == "Thunderhead")
        self.assertEqual(entry["span"]["start"]["basis"], "stated")
        self.assertNotIn("span_alternates", entry)

    def test_the_same_save_twice_files_once(self) -> None:
        form = self.thunderhead_form(fields={"nickname": "Thunder House"})
        first = le.edit_landmark(self.vault, form)
        self.assertEqual(len(first["filed"]), 1)
        count = len(self.sources())
        again = self.view_landmark("residences", "Thunder House")
        form = {**form, "stays": [{"ref": again["stays"][0]["ref"], "from": "1989-06", "to": "1990-06"}]}
        second = le.edit_landmark(self.vault, form)
        self.assertEqual((second["filed"], second["unchanged"]), ([], 1))
        self.assertEqual(len(self.sources()), count)
        self.assertIsNone(self.view_landmark("residences", "Thunderhead"))

    def test_delete_takes_it_off_the_view_and_keeps_the_source(self) -> None:
        before = self.sources()
        landmark = self.view_landmark("residences", "Thunderhead")
        result = le.edit_landmark(self.vault, {"mode": "delete", "refs": landmark["refs"]})
        self.assertIsNone(self.view_landmark("residences", "Thunderhead"))
        self.assertEqual(self.sources(), before)
        le.edit_landmark(self.vault, {"mode": "undo", "corrections": result["corrections"]})
        self.assertIsNotNone(self.view_landmark("residences", "Thunderhead"))

    def test_a_new_school_from_the_add_form(self) -> None:
        le.edit_landmark(self.vault, {"mode": "save", "kind": "schools",
                                      "fields": {"name": "Missionary Training Center",
                                                 "level": "training", "city": "Provo",
                                                 "state": "Utah"},
                                      "stays": [{"from": "2000-08", "to": "2000-10"}]})
        school = self.view_landmark("schools", "Missionary Training Center")
        self.assertEqual((school["level"], school["city"], school["state"]),
                         ("training", "Provo", "Utah"))

    def test_a_bad_form_writes_nothing(self) -> None:
        before = self.sources()
        with self.assertRaises(le.LandmarkEditError):
            le.edit_landmark(self.vault, self.thunderhead_form(
                stays={0: {"from": "1991-01", "to": "1990-01"}}))
        with self.assertRaises(le.LandmarkEditError):
            le.edit_landmark(self.vault, {"mode": "save", "kind": "schools",
                                          "fields": {"name": "X", "level": "kindergarten"}})
        self.assertEqual(self.sources(), before)


class ThePersonFormTests(FormVault):

    def setUp(self) -> None:
        super().setUp()
        pub.publish(self.vault, now=NOW, full=True)

    def cornerstones(self) -> dict:
        return self.projection().get("cornerstones_view") or {}

    def grandparents(self) -> list[dict]:
        return next((g["people"] for g in self.cornerstones().get("groups") or ()
                     if g["group"] == "grandparents"), [])

    def test_darvin_starts_in_others(self) -> None:
        others = [row["name"] for row in self.cornerstones()["others"]]
        self.assertIn("Darvin Burrows Beauchamp", others)
        self.assertEqual(self.grandparents(), [])

    def test_recategorising_darvin_moves_him_to_grandparents(self) -> None:
        other = next(row for row in self.cornerstones()["others"]
                     if row["name"] == "Darvin Burrows Beauchamp")
        result = le.edit_person(self.vault, {
            "mode": "save", "person_ref": other["person_ref"],
            "name": "Darvin Burrows Beauchamp", "category": "grandparent",
            "relation_word": "Grandpa", "side": "maternal"})
        self.assertEqual(result["roster"]["relationship"], "grandparent")
        row = self.roster()["darvin-burrows-beauchamp"]
        self.assertEqual((row["relationship"], row["grandparent_side"], row["relation_word"]),
                         ("grandparent", "maternal", "Grandpa"))
        self.assertEqual(row.get("relation_gender"), "male")
        people = self.grandparents()
        darvin = next(p for p in people if p["name"] == "Darvin Burrows Beauchamp")
        self.assertEqual((darvin["side"], darvin["display_name"]), ("maternal", "Grandpa"))
        self.assertEqual(darvin["born"]["value"], "1929-09-30")
        self.assertNotIn("Darvin Burrows Beauchamp",
                         [r["name"] for r in self.cornerstones()["others"]])
        # Idempotent: the same form again changes no roster byte.
        path = self.vault / "state" / "entity_rosters" / "person.json"
        bytes_before = path.read_bytes()
        le.edit_person(self.vault, {
            "mode": "save", "person_ref": darvin["person_ref"],
            "name": "Darvin Burrows Beauchamp", "category": "grandparent",
            "relation_word": "Grandpa", "side": "maternal"})
        self.assertEqual(path.read_bytes(), bytes_before)

    def test_a_date_on_the_person_form_is_the_cell(self) -> None:
        le.edit_person(self.vault, {
            "mode": "save", "person_ref": "person/desiree-taylor", "name": "Desiree Taylor",
            "category": "parent", "relation_word": "Mom",
            "born": {"year": "1955", "month": "6", "day": "20"}})
        mom = next(p for g in self.cornerstones()["groups"] for p in g["people"]
                   if p["person_ref"] == "person/desiree-taylor")
        self.assertEqual((mom["born"]["value"], mom["born"]["status"]), ("1955-06-20", "exact"))
        self.assertEqual(self.roster()["desiree-taylor"]["born"]["best"], "1955-06-20")

    def test_an_others_row_delete_is_undoable(self) -> None:
        other = next(row for row in self.cornerstones()["others"]
                     if row["name"] == "Darvin Burrows Beauchamp" and row["milestone"] == "birth")
        self.assertTrue(other["claim_ids"])
        result = le.edit_person(self.vault, {"mode": "delete", "person_ref": other["person_ref"],
                                             "milestone": "birth", "claim_ids": other["claim_ids"]})
        self.assertFalse(any(r["name"] == "Darvin Burrows Beauchamp" and r["milestone"] == "birth"
                             for r in self.cornerstones()["others"]))
        le.edit_person(self.vault, {"mode": "undo", "corrections": result["corrections"]})
        self.assertTrue(any(r["name"] == "Darvin Burrows Beauchamp" and r["milestone"] == "birth"
                            for r in self.cornerstones()["others"]))


class ThePureRulesTests(unittest.TestCase):

    def test_form_dates_keep_the_grain_he_gave(self) -> None:
        self.assertEqual(le.form_date("1989")["granularity"], "year")
        self.assertEqual(le.form_date({"year": "1989", "month": "6"})["best"], "1989-06")
        self.assertEqual(le.form_date("1989-06-01")["basis"], "stated")
        self.assertIsNone(le.form_date(""))
        with self.assertRaises(le.LandmarkEditError):
            le.form_date("June 1989")

    def test_a_mission_area_files_as_a_residence(self) -> None:
        record = le.build_record("missions", {"area": "Solothurn", "city": "Solothurn",
                                              "country": "Switzerland"},
                                 {"from": "2000-10", "to": "2000-12"})
        self.assertEqual((record["domain"], record["label"], record["city"]),
                         ("residences", "Solothurn", "Solothurn, Switzerland"))

    def test_still_here_is_ongoing_with_no_end(self) -> None:
        record = le.build_record("work", {"employer": "Etherfuse", "role": "CEO"},
                                 {"from": "2022-05", "to": "2024-01", "still_here": True})
        self.assertTrue(record["ongoing"])
        self.assertNotIn("end", record["span"])


if __name__ == "__main__":
    unittest.main()
