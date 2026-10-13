"""v420 (lifehug#487) — whose mission, what a mission is, and two stints of one employer.

THE INCIDENT, in synthetic shapes (the owner's own identities stay out of every
fixture; nothing here reads a real vault):

1. A relative's mission ("Ridgeline mission", ``subject: "my
   uncle"``) was filed under `missions` and drawn on the OWNER's axis as
   ``owner``/``participated``, because every entry outside
   `landmark_projection.OWNER_RELEVANCE_BY_DOMAIN` was read as the owner's own
   life whatever its subject said — and, being a REAL `missions` entry, it hid
   the mission lane his own covered stretch derives
   (`landmark_projection.A_RELATIVES_ENTRY_IS_THEIRS`).
2. "legal action" (``where: unknown``, 2025-08, no provenance, no span) was
   filed by the ladder as a mission. A dated event is not a mission
   (`landmark_projection.EVENT_IS_NOT_A_MISSION`).
3. Two dated tellings of one employer — Cedarport 2012-07-01 to 2013-08-01,
   Harbor City 2013-08 to 2015-08 — abutted, folded into one stay, and the
   day-grain Cedarport end won: the chain drew a hole that never happened
   (`landmarks_interaction.TWO_STATED_PLACE_STRETCHES_ARE_TWO_STAYS`).
"""

from __future__ import annotations

import copy
import json
import os
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SYSTEM = ROOT / "system"
sys.path.insert(0, str(SYSTEM))
sys.path.insert(0, str(ROOT / "tests"))

import landmark_projection as lp  # noqa: E402
import landmarks_interaction as li  # noqa: E402
import temporal_publication as pub  # noqa: E402
import temporal_timeline as tt  # noqa: E402
import timeline  # noqa: E402
import timeline_views as tv  # noqa: E402
from tempdirs import root_parent_tmp  # noqa: E402
from test_conversation_close import make_vault  # noqa: E402

NOW = "2026-10-13T12:00:00Z"


def when(text: str, *, basis: str = "stated", confidence: str = "certain",
         provenance: list | None = None) -> dict:
    grain = {4: "year", 7: "month", 10: "day"}[len(text)]
    return {"best": text, "earliest": text, "latest": text, "granularity": grain,
            "confidence": confidence, "basis": basis, "anchors": [],
            "provenance": provenance or []}


def span(start: str, end: str | None = None) -> dict:
    out = {"start": when(start)}
    if end:
        out["end"] = when(end)
    return out


SEED = {"birth": [{"domain": "birth", "label": "Birth", "date": when("1980-03-02")}]}

UNCLES_MISSION = {"domain": "missions", "label": "Ridgeline mission",
                  "subject": "my uncle", "where": "Ridgeline",
                  "span": span("2019-03", "2020-02")}
LEGAL_ACTION = {"domain": "missions", "label": "legal action", "where": "unknown",
                "date": when("2025-08", basis="anchor")}
#: A real mission: a stretch, in a field.
NORTHFIELD_MISSION = {"domain": "missions", "label": "Northfield mission",
                      "where": "Northfield", "span": span("2000-09", "2002-08")}

CEDARPORT = {"domain": "work", "label": "Orbital Dynamics", "what": "Engineer",
             "where": "Cedarport, AZ", "span": span("2012-07-01", "2013-08-01")}
HARBOR_CITY = {"domain": "work", "label": "Orbital Dynamics", "what": "Engineer",
               "where": "Harbor City, WA", "span": span("2013-08", "2015-08")}
MASHED = {"domain": "work", "label": "Orbital Dynamics", "what": "Engineer",
          "where": "Cedarport, Harbor City, AZ, WA"}
NEXT_EMPLOYER = {"domain": "work", "label": "Lattice Works", "what": "Engineer",
                 "where": "Harbor City, WA", "span": span("2015-09", "2018-01")}


class Vault(unittest.TestCase):
    """A real on-disk vault; records filed the way the ladder files them."""

    def setUp(self) -> None:
        tmp = root_parent_tmp(self, ROOT, prefix="lifehug-v420-")
        self.vault = make_vault(tmp / "vault")
        self.store = self.vault / "state" / "landmarks.json"
        for patch in (mock.patch.object(timeline, "LANDMARKS_STORE", self.store),
                      mock.patch.object(timeline, "_projection_vault_root",
                                        lambda: self.vault)):
            patch.start()
            self.addCleanup(patch.stop)
        self.store.write_text(json.dumps({"version": 1, "domains": copy.deepcopy(SEED)},
                                         indent=2) + "\n", encoding="utf-8")
        timeline.flip_landmarks_if_needed()

    def file_raw(self, domain: str, record: dict) -> str:
        """File a record the way the ladder did BEFORE the v420 rules."""
        filed = lp.file_landmark_record(
            self.vault, domain, copy.deepcopy(record), ordinal=lp.next_ordinal(self.vault),
            extractor_version=lp.LIVE_EXTRACTOR, now=NOW)
        timeline.redraw_landmarks()
        return filed["source_ref"].source_id

    def drawn(self, domain: str) -> list[dict]:
        return list(timeline.load_landmarks().get(domain) or ())

    def projection(self) -> dict:
        pub.publish(self.vault, roster_snapshot=(), now=NOW, full=True)
        return pub.read_projection(self.vault) or {}

    def node(self, label: str) -> dict:
        found = [node for node in self.projection().get("nodes") or ()
                 if str(node.get("label") or "").lower() == label.lower()]
        self.assertEqual(len(found), 1, label)
        return found[0]


# --------------------------------------------------------------------------
# 1. A relative's mission is theirs
# --------------------------------------------------------------------------


class WhoseEntryTests(unittest.TestCase):

    def test_a_relation_word_names_somebody_else(self) -> None:
        for subject in ("my uncle", "Dad", "Dad's mission", "the narrator's father",
                        "Grandma"):
            self.assertTrue(lp.entry_subject_is_another_person({"subject": subject}), subject)

    def test_the_owner_and_no_subject_are_his(self) -> None:
        for record in ({}, {"subject": ""}, {"subject": "self"}, {"subject": "me"},
                       {"subject": "the narrator"}, {"subject": "we"},
                       {"subject": "my mission"}, {"subject": "Mom and me"}):
            self.assertFalse(lp.entry_subject_is_another_person(record), record)

    def test_a_bare_name_is_not_decided_against_him(self) -> None:
        self.assertFalse(lp.entry_subject_is_another_person({"subject": "Kestrel"}))


class ARelativesMissionFoldTests(Vault):

    def test_the_uncles_mission_is_his_uncles(self) -> None:
        self.file_raw("missions", UNCLES_MISSION)
        node = self.node(UNCLES_MISSION["label"])
        self.assertEqual(node["occurrence_subject_scope"], "other_person")
        self.assertEqual(node["owner_timeline_relation"], "contextual_only")

    def test_the_same_entry_with_no_subject_is_still_his(self) -> None:
        own = {key: value for key, value in UNCLES_MISSION.items() if key != "subject"}
        self.file_raw("missions", own)
        node = self.node(UNCLES_MISSION["label"])
        self.assertEqual(node["occurrence_subject_scope"], "owner")
        self.assertEqual(node["owner_timeline_relation"], "participated")

    def test_the_rule_version_moved(self) -> None:
        self.assertEqual(tt.CALCULATION_RULE_VERSION, "timeline-rules:32")


def his_mission_domains() -> dict:
    """His mission filed as a Missionary work entry + MTC school + MTC stay
    (the 2026-09-25 shape), plus his uncle's mission filed under `missions`."""
    return {
        "residences": [
            {"domain": "residences", "label": "Elm Street", "city": "Fairhaven, Oregon",
             "span": span("1997-06", "2000-08")},
            {"domain": "residences", "label": "MTC", "city": "Provo, Utah",
             "span": span("2000-08", "2000-10")},
            {"domain": "residences", "label": "Northfield", "city": "Northfield",
             "span": span("2000-10", "2002-08")},
        ],
        "schools": [{"domain": "schools", "label": "Missionary Training Center (MTC)",
                     "span": span("2000-08", "2000-10")}],
        "work": [{"domain": "work", "label": "Missionary - Northfield Mission",
                  "span": span("2000-10", "2002-08")}],
        "missions": [copy.deepcopy(UNCLES_MISSION)],
    }


class ARelativesMissionViewTests(unittest.TestCase):

    def lane(self, domains: dict) -> dict | None:
        return next((row for row in tv.landmarks_view(domains)["domains"]
                     if row["domain"] == "missions"), None)

    def test_the_uncles_mission_is_not_on_his_missions_lane(self) -> None:
        lane = self.lane(his_mission_domains())
        self.assertIsNotNone(lane)
        labels = [landmark["label"] for landmark in lane["landmarks"]]
        self.assertNotIn(UNCLES_MISSION["label"], labels)

    def test_his_derived_mission_lane_returns(self) -> None:
        lane = self.lane(his_mission_domains())
        derived = self.lane({k: v for k, v in his_mission_domains().items()
                             if k != "missions"})
        self.assertEqual(lane, derived)
        self.assertTrue(lane["landmarks"])

    def test_his_own_missions_entry_still_wins(self) -> None:
        domains = his_mission_domains()
        domains["missions"].append(copy.deepcopy(NORTHFIELD_MISSION))
        lane = self.lane(domains)
        self.assertEqual([landmark["label"] for landmark in lane["landmarks"]],
                         ["Northfield mission"])


# --------------------------------------------------------------------------
# 2. A dated event is not a mission
# --------------------------------------------------------------------------


class EventIsNotAMissionRuleTests(unittest.TestCase):

    def test_legal_action_is_an_event(self) -> None:
        self.assertEqual(lp.misfiled_landmark("missions", LEGAL_ACTION),
                         lp.EVENT_IS_NOT_A_MISSION)
        self.assertEqual(lp.REFILE_KIND_FOR[lp.EVENT_IS_NOT_A_MISSION], lp.REFILE_AS_MOMENT)
        self.assertIn(lp.EVENT_IS_NOT_A_MISSION, lp.MISFILED_REASONS)

    def test_event_words_with_a_place_still_read_as_an_event(self) -> None:
        record = {**LEGAL_ACTION, "label": "court hearing", "where": "Ridgeline"}
        self.assertEqual(lp.misfiled_landmark("missions", record), lp.EVENT_IS_NOT_A_MISSION)

    def test_no_place_and_no_warrant_is_an_event(self) -> None:
        record = {"domain": "missions", "label": "the trip", "date": when("2025-08")}
        self.assertEqual(lp.misfiled_landmark("missions", record), lp.EVENT_IS_NOT_A_MISSION)

    def test_a_real_mission_stands(self) -> None:
        self.assertIsNone(lp.misfiled_landmark("missions", NORTHFIELD_MISSION))
        self.assertIsNone(lp.misfiled_landmark("missions", UNCLES_MISSION))
        # A span is a stretch, whatever its words say.
        self.assertIsNone(lp.misfiled_landmark(
            "missions", {**LEGAL_ACTION, "span": span("2025-08", "2025-09")}))
        # A placed mission told by one date, with a warrant, stands.
        self.assertIsNone(lp.misfiled_landmark("missions", {
            "domain": "missions", "label": "Northfield mission", "where": "Northfield",
            "date": when("2001", provenance=[{"claim": "I was out in 2001"}])}))
        self.assertIsNone(lp.misfiled_landmark("missions", {
            "domain": "missions", "label": "the mission", "where": "unknown",
            "date": when("2001", provenance=[{"claim": "I left in 2001"}])}))


class EventIsNotAMissionRefileTests(Vault):

    def test_the_write_seat_refiles_it_the_moment_it_lands(self) -> None:
        findings: list = []
        saved = timeline.save_landmark("missions", copy.deepcopy(LEGAL_ACTION),
                                       findings=findings)
        self.assertEqual(saved["not_written"], lp.EVENT_IS_NOT_A_MISSION)
        self.assertEqual(saved["refiled_as"], lp.REFILE_AS_MOMENT)
        self.assertNotIn("legal action", [e.get("label") for e in self.drawn("missions")])
        self.assertEqual([f["lint"] for f in findings], ["landmark_refiled"])

    def test_refile_apply_makes_it_a_moment_at_its_own_date(self) -> None:
        self.file_raw("missions", LEGAL_ACTION)
        self.file_raw("missions", NORTHFIELD_MISSION)
        self.assertIn("legal action", [e.get("label") for e in self.drawn("missions")])
        index = lp.store.fold_active_index(self.vault)
        plan = lp.refile_plan(lp.load_landmark_sources(self.vault), index)
        self.assertEqual([(step["label"], step["reason"]) for step in plan],
                         [("legal action", lp.EVENT_IS_NOT_A_MISSION)])
        for step in plan:
            lp.file_landmark_refile(self.vault, step, active_index=index, now=NOW)
        timeline.redraw_landmarks()
        self.assertEqual([e.get("label") for e in self.drawn("missions")],
                         ["Northfield mission"])
        moment = self.node("legal action")
        self.assertEqual(moment["event_kind"], "moment")
        self.assertEqual(moment["best_temporal_value"]["best"], "2025-08")


class RefileCliDoorTests(Vault):
    """`lifehug.py landmark-refile` under the running interpreter."""

    def run_verb(self, *argv: str) -> dict:
        env = os.environ.copy()
        env.update({"LIFEHUG_VAULT_ROOT": str(self.vault), "PYTHONDONTWRITEBYTECODE": "1"})
        env.pop("WORKSPACE", None)
        env.pop("PYTHONPATH", None)
        result = subprocess.run(
            [sys.executable, str(SYSTEM / "lifehug.py"), "landmark-refile", *argv, "--json"],
            capture_output=True, text=True, env=env, cwd=self.vault, timeout=300)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def test_dry_run_then_apply_then_nothing(self) -> None:
        self.file_raw("missions", LEGAL_ACTION)
        self.file_raw("missions", NORTHFIELD_MISSION)
        dry = self.run_verb()
        self.assertEqual([(s["label"], s["reason"]) for s in dry["plan"]],
                         [("legal action", lp.EVENT_IS_NOT_A_MISSION)])
        self.assertEqual((dry["filed"], dry["applied"]), ([], False))
        self.assertFalse((self.vault / lp.REFILE_SOURCES_DIR).exists())
        applied = self.run_verb("--apply")
        self.assertEqual(len(applied["filed"]), 1)
        again = self.run_verb("--apply")
        self.assertEqual((again["plan"], again["filed"]), ([], []))


# --------------------------------------------------------------------------
# 3. Two stints of one employer in two places are two stays
# --------------------------------------------------------------------------


class PlaceKeyTests(unittest.TestCase):

    ROW = {"domain": "work", "collection": "sequence"}

    def test_two_places_never_join(self) -> None:
        self.assertTrue(li.different_places(CEDARPORT, HARBOR_CITY))
        self.assertFalse(li.same_landmark_stay(CEDARPORT, HARBOR_CITY, self.ROW))

    def test_one_city_spelled_twice_joins(self) -> None:
        later = {**HARBOR_CITY, "where": "Cedarport, Arizona"}
        self.assertTrue(li.same_landmark_stay(CEDARPORT, later, self.ROW))

    def test_two_cities_in_one_state_are_two_places(self) -> None:
        later = {**HARBOR_CITY, "where": "Dunmore, AZ"}
        self.assertFalse(li.same_landmark_stay(CEDARPORT, later, self.ROW))

    def test_a_mashed_place_intersects_both(self) -> None:
        self.assertTrue(li.names_several_places(MASHED))
        self.assertFalse(li.different_places(CEDARPORT, MASHED))
        self.assertFalse(li.different_places(HARBOR_CITY, MASHED))

    def test_an_undated_or_placeless_telling_still_fills_in(self) -> None:
        self.assertTrue(li.same_landmark_stay(CEDARPORT, {"where": "Harbor City"}, self.ROW))
        placeless = {key: value for key, value in HARBOR_CITY.items() if key != "where"}
        self.assertTrue(li.same_landmark_stay(CEDARPORT, placeless, self.ROW))

    def test_residences_are_left_to_their_address(self) -> None:
        row = {"domain": "residences", "collection": "sequence"}
        self.assertTrue(li.same_landmark_stay(
            {"city": "Cedarport", "span": span("2012-07", "2013-08")},
            {"city": "Harbor City", "span": span("2013-08", "2015-08")}, row))


class TwoStintsTests(Vault):

    def orbital(self) -> list[tuple]:
        return [(entry["span"]["start"]["best"], entry["span"]["end"]["best"])
                for entry in self.drawn("work") if entry.get("label") == "Orbital Dynamics"]

    def work_rows(self) -> list[tuple]:
        view = tv.landmarks_view(timeline.load_landmarks())
        lane = next(row for row in view["domains"] if row["domain"] == "work")
        return [(row["kind"], row["start"], row["end"]) for row in lane["rows"]]

    def test_two_stays_each_with_its_own_end(self) -> None:
        for record in (CEDARPORT, HARBOR_CITY, NEXT_EMPLOYER):
            self.file_raw("work", record)
        self.assertEqual(self.orbital(), [("2012-07-01", "2013-08-01"), ("2013-08", "2015-08")])

    def test_the_chain_has_no_gap(self) -> None:
        for record in (CEDARPORT, HARBOR_CITY, NEXT_EMPLOYER):
            self.file_raw("work", record)
        self.assertEqual(self.work_rows(), [("stay", "2012-07-01", "2013-08-01"),
                                            ("stay", "2013-08", "2015-08"),
                                            ("stay", "2015-09", "2018-01")])

    def test_a_mashed_telling_opens_no_third_stay(self) -> None:
        # Undated, after the first stay: it fills that stay in and never
        # makes the Harbor City telling read as the same place.
        for record in (CEDARPORT, MASHED, HARBOR_CITY, NEXT_EMPLOYER):
            self.file_raw("work", record)
        self.assertEqual(self.orbital(), [("2012-07-01", "2013-08-01"), ("2013-08", "2015-08")])

    def test_a_dated_mashed_telling_joins_the_stay_it_falls_in(self) -> None:
        inside = {**MASHED, "span": span("2012-09", "2013-06")}
        for record in (CEDARPORT, inside, HARBOR_CITY):
            self.file_raw("work", record)
        self.assertEqual(self.orbital(), [("2012-07-01", "2013-08-01"), ("2013-08", "2015-08")])

    def test_two_tellings_in_one_city_that_abut_still_join(self) -> None:
        later = {**HARBOR_CITY, "where": "Cedarport, AZ"}
        for record in (CEDARPORT, later):
            self.file_raw("work", record)
        self.assertEqual(len(self.orbital()), 1)


if __name__ == "__main__":
    unittest.main()
