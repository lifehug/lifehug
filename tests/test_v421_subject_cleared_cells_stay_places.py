"""v421 (owner, 2026-10-15): subject is whose line, not who; a withdrawn
record read back says nothing; a cleared cell is the owner's no; a stay names
its own place.

The incident, synthetic here: the cornerstones grid and the Timeline marker
row said his sister "died · 2024". A `losses` entry {label/who "Brett",
subject "Jacque"} — his sister's loss, retired on the landmark form days
earlier — made one Person named both "Brett" and "Jacque", it folded into her
roster row, and the classifier's own reading of the entry's file ("Brett's
death") was keyed to her. And the person form had no way to say "it hasn't
happened"; and the landmark form stamped one city on every stay.

Every record is synthetic; nothing here reads a real vault.
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

import classifier_claims as cc  # noqa: E402
import cornerstones as cs  # noqa: E402
import entity_verdict as ev  # noqa: E402
import landmark_edit as le  # noqa: E402
import landmark_projection as lp  # noqa: E402
import temporal_publication as pub  # noqa: E402
import temporal_store as ts  # noqa: E402
import test_v360_edit_forms as forms  # noqa: E402
import timeline_views as tv  # noqa: E402

OWNER_NAMES = ("Dave", "David James Taylor")
SISTER = {"name": "Jacque Cook", "slug": "jacque-cook", "relationship": "sibling",
          "aliases": ["Jacque"], "born": forms.when("1978-04-02")}
#: Her loss: Brett died, and the loss sits on HER line.
BRETTS_LOSS = {"domain": "losses", "label": "Brett", "who": "Brett", "subject": "Jacque",
               "date": forms.when("2024")}


def _source(record: dict, digest: str = "b0001") -> dict:
    return {"source_id": f"landmark:entry-{digest}", "domain": record["domain"],
            "entry_key": record["label"].casefold(), "ordinal": 1, "record": dict(record)}


def _roster(*rows: dict) -> dict:
    return {"version": 1, "type": "person", "entities": [dict(r) for r in rows]}


def _death_node(subject: str, label: str) -> dict:
    return {"node_id": f"node-{subject.casefold()}", "event_kind": "death", "label": label,
            "subject_refs": [subject], "best_temporal_value": forms.when("2024"),
            "input_claim_refs": []}


# --------------------------------------------------------------------------
# 1. cornerstones.A_SUBJECT_IS_WHOSE_LINE_NOT_WHO (pure)
# --------------------------------------------------------------------------


class SubjectIsWhoseLineTests(unittest.TestCase):

    def relations(self, *entries: dict, index: object = None) -> cs.Relations:
        sources = [_source(e, f"b{i:04d}") for i, e in enumerate(entries)]
        if index is not None:
            sources = lp.standing_landmark_sources(sources, index)
        return cs.Relations(_roster(SISTER), sources, owner_names=OWNER_NAMES)

    def test_the_mourner_is_not_a_name_of_the_dead(self) -> None:
        relations = self.relations(BRETTS_LOSS)
        brett = relations.person_for("Brett")
        sister = relations.person_for("person/jacque-cook")
        self.assertIsNotNone(brett)
        self.assertIsNot(brett, sister)
        self.assertNotIn("Jacque", brett.names)
        self.assertEqual(sister.key, "person/jacque-cook")

    def test_bretts_death_is_not_keyed_to_the_sister(self) -> None:
        relations = self.relations(BRETTS_LOSS)
        held = tv.milestone_nodes([_death_node("Brett", "Brett's death")], relations)
        self.assertNotIn(("death", "person/jacque-cook"), held)
        self.assertIn(("death", "landmark:brett"), held)

    def test_the_grid_reads_no_death_for_her(self) -> None:
        relations = self.relations(BRETTS_LOSS)
        view = tv.cornerstones_view([_death_node("Brett", "Brett's death")], relations,
                                    roster=_roster(SISTER),
                                    landmark_domains={"losses": [BRETTS_LOSS]})
        her = next(p for g in view["groups"] for p in g["people"]
                   if p["person_ref"] == "person/jacque-cook")
        self.assertIsNone(her["died"]["value"])
        self.assertEqual(her["died"]["status"], tv.NOT_OWED)

    def test_a_partnerships_subject_is_still_not_the_owners_spouse(self) -> None:
        theirs = {"domain": "partnerships", "label": "Rowan Pike", "who": "Rowan Pike",
                  "subject": "Jacque", "event": "married", "date": forms.when("2001")}
        relations = self.relations(theirs)
        self.assertIsNone(relations.person_for("Rowan Pike"))

    def test_a_withdrawn_loss_introduces_nobody(self) -> None:
        source = _source(BRETTS_LOSS, "b0000")
        index = {"claims": [{"claim_id": "c-identity", "claim_type": "identity",
                             "source_ref": {"source_id": source["source_id"]}}],
                 "corrections": []}
        with mock.patch.object(ts, "active_claims", lambda _index: []):
            relations = self.relations(BRETTS_LOSS, index=index)
        self.assertIsNone(relations.person_for("Brett"))
        self.assertEqual([p.key for p in relations.people], ["person/jacque-cook"])


# --------------------------------------------------------------------------
# A synthetic vault: the sister on the roster, her loss filed and retired
# --------------------------------------------------------------------------


class _Vault(forms.FormVault):
    SEED_LOSSES: list = []

    def setUp(self) -> None:
        roster = copy.deepcopy(forms.ROSTER)
        roster["entities"].append(copy.deepcopy(SISTER))
        seed = copy.deepcopy(forms.SEED)
        seed["losses"] = seed["losses"] + copy.deepcopy(self.SEED_LOSSES)
        with mock.patch.object(forms, "ROSTER", roster), mock.patch.object(forms, "SEED", seed):
            super().setUp()
        pub.publish(self.vault, now=forms.NOW, full=True)

    def row(self, person_ref: str) -> dict:
        view = self.projection().get("cornerstones_view") or {}
        return next(p for g in view.get("groups") or () for p in g["people"]
                    if p["person_ref"] == person_ref)

    def markers(self) -> list[str]:
        view = self.projection().get("landmarks_view") or {}
        return [m.get("marker_id") for m in view.get("cornerstone_markers") or ()]

    def classify(self, source_path: str, *events: dict) -> dict:
        directory = self.vault / "state" / "classifications"
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "brett-entry.json").write_text(json.dumps({
            "source_path": source_path, "source_type": "landmark_entry",
            "people": [], "places": [], "time_periods": [], "themes": [],
            "events": list(events)}), encoding="utf-8")
        return cc.migrate_classifier_moments(self.vault, classifications_dir=directory,
                                             dry_run=False, now=forms.NOW)


BRETTS_DEATH_EVENT = {"title": "Brett's death", "description": "Brett died in November 2023.",
                      "when_hint": None, "anchor": None, "people": ["Brett"],
                      "date": {"stated": "2023-11", "age": None, "anchor_ref": None,
                               "relation": None}}


class AWithdrawnRecordReadBackSaysNothingTests(_Vault):
    """2. `classifier_claims.A_WITHDRAWN_RECORD_READ_BACK_SAYS_NOTHING`."""

    SEED_LOSSES = [BRETTS_LOSS]

    def brett_source(self) -> dict:
        return next(s for s in lp.load_landmark_sources(self.vault)
                    if s["record"].get("label") == "Brett")

    def bretts_claims(self) -> list[dict]:
        return [row for row in ts.active_claims(ts.fold_active_index(self.vault))
                if cc.is_classifier_source_id((row.get("source_ref") or {}).get("source_id"))
                and "brett" in json.dumps(row).casefold()]

    def test_the_classifiers_claims_from_a_retired_entry_are_superseded(self) -> None:
        source = self.brett_source()
        first = self.classify(source["relative_path"], BRETTS_DEATH_EVENT)
        self.assertEqual(first["deduped_withdrawn_records"], 0)
        self.assertTrue(self.bretts_claims(), "the classifier filed Brett's death")
        lp.retire_entry(self.vault, domain="losses", entry_key=source["entry_key"],
                        reason="retired by the owner on the landmark form (test)")
        self.assertEqual(lp.withdrawn_record_paths(self.vault),
                         frozenset({source["relative_path"]}))
        again = self.classify(source["relative_path"], BRETTS_DEATH_EVENT)
        self.assertEqual(again["deduped_withdrawn_records"], 1)
        self.assertEqual(again["claims"], 0)
        self.assertGreaterEqual(again["superseded_claims"], 1)
        self.assertEqual(self.bretts_claims(), [])
        nodes = [n for n in self.projection().get("nodes") or ()
                 if "Brett" in str(n.get("label"))]
        self.assertEqual(nodes, [])
        her = self.row("person/jacque-cook")
        self.assertIsNone(her["died"]["value"])
        self.assertNotIn("cornerstone:death:person/jacque-cook", self.markers())

    def test_a_standing_entry_is_read_as_before(self) -> None:
        self.assertEqual(lp.withdrawn_record_paths(self.vault), frozenset())
        report = self.classify(self.brett_source()["relative_path"], BRETTS_DEATH_EVENT)
        self.assertEqual(report["deduped_withdrawn_records"], 0)

    def test_the_sister_is_never_dead_even_while_the_loss_stands(self) -> None:
        self.classify(self.brett_source()["relative_path"], BRETTS_DEATH_EVENT)
        her = self.row("person/jacque-cook")
        self.assertIsNone(her["died"]["value"])
        self.assertNotIn("cornerstone:death:person/jacque-cook", self.markers())


# --------------------------------------------------------------------------
# 3. landmark_edit.A_CLEARED_CELL_IS_THE_OWNERS_NO
# --------------------------------------------------------------------------


SISTER_FORM = {"mode": "save", "person_ref": "person/jacque-cook", "name": "Jacque Cook",
               "category": "sibling", "relation_word": "Sister"}


class AClearedCellIsTheOwnersNoTests(_Vault):

    def roster_row(self) -> dict:
        return self.roster()["jacque-cook"]

    def test_a_died_date_cleared_reads_empty_and_not_owed_and_undo_restores(self) -> None:
        le.edit_person(self.vault, {**SISTER_FORM, "died": "2024-02-03"})
        self.assertEqual(self.row("person/jacque-cook")["died"]["value"], "2024-02-03")
        self.assertIn("cornerstone:death:person/jacque-cook", self.markers())
        self.assertEqual(self.roster_row()["died"]["best"], "2024-02-03")

        result = le.edit_person(self.vault, {**SISTER_FORM, "cleared": ["died"]})
        self.assertEqual(result["cleared"], ["died"])
        self.assertTrue(result["corrections"])
        died = self.row("person/jacque-cook")["died"]
        self.assertIsNone(died["value"])
        self.assertEqual(died["status"], tv.NOT_OWED)
        self.assertNotIn("cornerstone:death:person/jacque-cook", self.markers())
        self.assertNotIn("died", self.roster_row())
        self.assertIs(self.roster_row()["living"], True)
        losses = (json.loads(self.store.read_text())["domains"].get("losses") or [])
        self.assertNotIn("Jacque Cook", [e.get("label") for e in losses])

        le.edit_person(self.vault, {"mode": "undo", "corrections": result["corrections"]})
        self.assertEqual(self.row("person/jacque-cook")["died"]["value"], "2024-02-03")
        self.assertIn("cornerstone:death:person/jacque-cook", self.markers())

    def test_a_cleared_birth_takes_the_roster_date_too(self) -> None:
        le.edit_person(self.vault, {**SISTER_FORM, "born": "1978-04-02"})
        self.assertEqual(self.row("person/jacque-cook")["born"]["value"], "1978-04-02")
        le.edit_person(self.vault, {**SISTER_FORM, "cleared": ["born"]})
        self.assertIsNone(self.row("person/jacque-cook")["born"]["value"])
        self.assertNotIn("born", self.roster_row())

    def test_his_own_birth_is_never_cleared(self) -> None:
        before = sorted(p.name for p in (self.vault / "sources").rglob("*"))
        with self.assertRaises(le.LandmarkEditError):
            le.edit_person(self.vault, {"mode": "save", "person_ref": "self",
                                        "category": "self", "cleared": ["born"]})
        self.assertEqual(sorted(p.name for p in (self.vault / "sources").rglob("*")), before)

    def test_a_field_is_a_date_or_cleared_not_both(self) -> None:
        with self.assertRaises(le.LandmarkEditError):
            le.edit_person(self.vault, {**SISTER_FORM, "died": "2024", "cleared": ["died"]})
        with self.assertRaises(le.LandmarkEditError):
            le.edit_person(self.vault, {**SISTER_FORM, "cleared": ["graduated"]})

    def test_the_roster_clear_is_explicit(self) -> None:
        ev.apply_verdict("person", "jacque-cook", "clear", died="2020")
        self.assertIn("died", self.roster_row())
        with self.assertRaises(ev.EntityVerdictError):
            ev.apply_verdict("person", "jacque-cook", "clear", died="2020", clear_died=True)
        ev.apply_verdict("person", "jacque-cook", "clear", clear_died=True)
        self.assertNotIn("died", self.roster_row())


# --------------------------------------------------------------------------
# 4. landmark_edit.A_STAY_NAMES_ITS_OWN_PLACE
# --------------------------------------------------------------------------


class AStayNamesItsOwnPlaceTests(forms.FormVault):

    def setUp(self) -> None:
        super().setUp()
        pub.publish(self.vault, now=forms.NOW, full=True)

    def work(self) -> dict:
        landmark = self.view_landmark("work", "Orbital Dynamics")
        self.assertIsNotNone(landmark)
        return landmark

    def test_pure_a_stay_place_overrides_the_forms_for_that_stay(self) -> None:
        fields = {"employer": "Orbital Dynamics", "role": "Engineer", "city": "Cedarport",
                  "state": "Arizona"}
        own = le.build_record("work", fields, {"from": "2013-08", "to": "2015-08",
                                               "where": "Harbor City, Washington"})
        shared = le.build_record("work", fields, {"from": "2012-07", "to": "2013-08"})
        self.assertEqual(own["where"], "Harbor City, Washington")
        self.assertEqual(shared["where"], "Cedarport, Arizona")
        school = le.build_record("schools", {"name": "Lakeside"}, {"where": "Mesa, Arizona"})
        self.assertEqual(school["place"], "Mesa, Arizona")
        home = le.build_record("residences", {"nickname": "The flat"},
                               {"where": "Solothurn, Switzerland"})
        self.assertEqual(home["city"], "Solothurn, Switzerland")

    def test_two_cities_one_save_two_stays_and_a_role_edit_keeps_each_place(self) -> None:
        le.edit_landmark(self.vault, {
            "mode": "save", "kind": "work",
            "fields": {"employer": "Orbital Dynamics", "role": "Engineer",
                       "city": "Cedarport", "state": "Arizona"},
            "stays": [{"from": "2012-07", "to": "2013-08", "where": "Cedarport, Arizona"},
                      {"from": "2013-09", "to": "2015-08", "where": "Harbor City, Washington"}]})
        filed = sorted(s["record"].get("where") for s in lp.load_landmark_sources(self.vault)
                       if s["record"].get("label") == "Orbital Dynamics")
        self.assertEqual(filed, ["Cedarport, Arizona", "Harbor City, Washington"])
        landmark = self.work()
        self.assertEqual([s["detail"].get("where") for s in landmark["stays"]],
                         ["Cedarport, Arizona", "Harbor City, Washington"])

        stays = [{"ref": s["ref"], "from": s["start"], "to": s["end"],
                  "where": s["detail"]["where"]} for s in landmark["stays"]]
        le.edit_landmark(self.vault, {
            "mode": "save", "kind": "work",
            "fields": {"employer": "Orbital Dynamics", "role": "Staff engineer",
                       "city": "Cedarport", "state": "Arizona"},
            "stays": stays})
        landmark = self.work()
        self.assertEqual([(s["detail"].get("what"), s["detail"].get("where"))
                          for s in landmark["stays"]],
                         [("Staff engineer", "Cedarport, Arizona"),
                          ("Staff engineer", "Harbor City, Washington")])


if __name__ == "__main__":
    unittest.main()
