"""v360 (owner, 2026-09-25) (lifehug#413): a mission contains its stays.

v356 made a mission a span that "can contain stays and moments". Its author
filed the owner's mission in a scratch rig as a stated span (2000-08 ->
2002-06-06) and the containment rung proposed a 96-member container — 13
dated, 83 undated — keyed on ONE roster entity, `period/switzerland-mission`,
whose aliases include the bare word "mission". None of his MTC or Swiss-area
stays were members (a stay's entities are its places), and tellings that only
SAID the word were: "I have not served in the military…", "AJ left on his
mission", "Painted for father's company before mission".

The rule (`episode_containers.A_MISSION_CONTAINS_ITS_PLACES`) extends the
entity rung's grouping key for a place-containing span; there is no second
containment path. A member joins through a mission PLACE (the MTC, an area a
telling of the mission sets it in, a stay the mission's own tenure was dated
from, a place the entry names), through the mission named as its SETTING, or
— dated wholly inside the span — through a REGION the mission covers.

The shapes are the owner's; every record is synthetic and nothing here reads a
real vault.
"""

from __future__ import annotations

import hashlib
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "system"))

import episode_binder as eb  # noqa: E402
import episode_containers as ec  # noqa: E402
import landmark_projection as lp  # noqa: E402
import landmarks_interaction as li  # noqa: E402
import temporal_claims as tc  # noqa: E402
import temporal_projection as tp  # noqa: E402

NOW = "2026-09-25T12:00:00Z"


def revision(seed: str) -> str:
    return "sha256:" + hashlib.sha256(seed.encode("utf-8")).hexdigest()


def stated(best: str) -> dict:
    grain = {4: "year", 7: "month", 10: "day"}[len(best)]
    return {"best": best, "earliest": best, "latest": best, "granularity": grain,
            "confidence": "certain", "basis": "stated"}


def inherited(best: str, stay: str) -> dict:
    """R7's inherited end (`landmark_offer.inherit_dates`), verbatim clause."""
    return {"best": best, "earliest": best, "latest": best, "granularity": "month",
            "confidence": "inferred", "basis": "anchor", "anchors": [],
            "provenance": [{"basis": "inferred",
                            "claim": f"from the dates of the {stay} stay"}]}


ROSTERS = {
    "period": {"type": "period", "entities": [
        # The owner's roster really does alias the bare word.
        {"name": "Switzerland Mission", "slug": "switzerland-mission",
         "aliases": ["mission", "swiss mission", "the mission"]},
    ]},
    "person": {"type": "person", "entities": [
        {"name": "AJ", "slug": "aj", "aliases": ["A.J."]},
    ]},
    "place": {"type": "place", "entities": [
        {"name": "Provo, Utah", "slug": "provo-utah", "aliases": []},
        {"name": "2005 North 900 East, Provo, UT 84602, Provo, Utah",
         "slug": "residence-mtc", "aliases": ["MTC"]},
        {"name": "Solothurn, Switzerland", "slug": "solothurn-switzerland", "aliases": []},
        {"name": "Friedrichshafen, Germany", "slug": "friedrichshafen-germany",
         "aliases": []},
        {"name": "Luzern, Switzerland", "slug": "luzern-switzerland", "aliases": []},
        {"name": "Mesa, Arizona", "slug": "mesa-arizona", "aliases": []},
    ]},
}

MISSION = "landmark:entry-mission"
MISSION_ENTRY = {
    "domain": "missions",
    "happened": "yes",
    "label": "Switzerland Zurich Mission",
    "where": "Switzerland Zurich Mission",
    "span": {"start": {**stated("2000-08"), "provenance": [
                 {"basis": "stated", "claim": "Departed on church mission at 19"}]},
             "end": {**stated("2002-06-06"), "provenance": [
                 {"basis": "stated", "claim": "Returned home from mission"}]}},
}

#: (source, label, city, start, end). The first four are inside the mission;
#: Mesa is a home in the same months, elsewhere.
STAYS = (
    ("landmark:entry-mtc", "MTC", "Provo, Utah", "2000-08", "2000-10"),
    ("landmark:entry-solothurn", "Solothurn, Switzerland", "Solothurn, Switzerland",
     "2000-10", "2000-12"),
    ("landmark:entry-friedrichshafen", "Friedrichshafen, Germany",
     "Friedrichshafen, Germany", "2000-12", "2001-03"),
    ("landmark:entry-luzern", "Luzern, Switzerland", "Luzern, Switzerland",
     "2001-04", "2001-06"),
)
MESA = ("landmark:entry-mesa", "Mesa, Arizona", "Mesa, Arizona", "2001-01", "2001-05")

#: His mission, still filed under `work` and dated by R7 from a stay.
TENURE = "landmark:entry-missionary"
TENURE_ENTRY = {
    "domain": "work",
    "label": "Missionary - The Church of Jesus Christ of Latter Day Saints",
    "what": "Missionary - The Church of Jesus Christ of Latter Day Saints",
    "span": {"start": inherited("2000-12", "Friedrichshafen, Germany"),
             "end": inherited("2001-03", "Friedrichshafen, Germany")},
}

MILITARY = "manual:2026-08-24-i-have-not-served-in-the-military-it-s"
JOINS = {
    "conversation:msg-assignment": "Mission assignment to Solothurn",
    "conversation:msg-mtc": "Residence at the MTC",
    "conversation:msg-missing-mom": "Missing mom on my mission",
    "conversation:msg-president": "Neil Hall serves as mission president",
    "conversation:msg-begins": "LDS mission service begins",
}
NEVER = {
    MILITARY: "Served two-year Mormon mission",
    "conversation:msg-statement": "Joy Labs had the wrong mission statement",
    "conversation:msg-before": "Painted for father's company before mission",
    "conversation:msg-home": "Returned home from mission",
    "conversation:msg-aj": "AJ left on his mission",
    "conversation:msg-prep": "Preparing to leave on mission at 18",
}
MESA_MOMENT = "conversation:msg-mesa"


def source_ref(source: str) -> dict:
    return {"source_id": source, "revision": revision(source),
            "source_path": f"sources/{source.replace(':', '/')}.md"}


def moment(source: str, label: str, *, subject: str = "self",
           places: tuple = (), when: dict | None = None) -> dict:
    payload = {
        "source_kind": "conversation",
        "source_ref": source_ref(source),
        "evidence": [{"quote": label}],
        "extractor_version": "classifier:1",
        "created_at": "2026-09-20T00:00:00Z",
        "basis": "explicit",
        "confidence": 0.9,
        "status": "active",
        "claim_type": "date" if when else "occurrence",
        "event_kind": "moment",
        "event_mention": label,
        "subject_mention": subject,
        "event_ref": tp.derive_node_id(node_kind="event", event_kind="moment",
                                       subject_refs=["I"], discriminator=source),
    }
    if places:
        payload["place_mentions"] = list(places)
    if when:
        payload["temporal_value"] = when
    return tc.validate_temporal_claim(payload)


def entry(source: str, domain: str, record: dict) -> tuple:
    """``(claims, landmark source row)`` for one filed landmark entry."""
    validated = li.validate_landmark(record)
    claims = lp.entry_claims(domain, validated, source_ref=source_ref(source), now=NOW)
    row = {"source_id": source, "relative_path": source_ref(source)["source_path"],
           "domain": domain, "entry_key": record.get("label", "").casefold(),
           "ordinal": 1, "record": validated}
    return claims, row


def stay_record(label: str, city: str, start: str, end: str) -> dict:
    return {"domain": "residences", "label": label, "city": city,
            "span": {"start": stated(start), "end": stated(end)}}


def vault(*, with_mesa: bool = True, extra: tuple = ()) -> tuple:
    claims: list = []
    rows: list = []
    for source, domain, record in (
        (MISSION, "missions", MISSION_ENTRY),
        (TENURE, "work", TENURE_ENTRY),
        *[(source, "residences", stay_record(label, city, start, end))
          for source, label, city, start, end in STAYS + ((MESA,) if with_mesa else ())],
    ):
        these, row = entry(source, domain, record)
        claims.extend(these)
        rows.append(row)
    claims.append(moment("conversation:msg-assignment", JOINS["conversation:msg-assignment"],
                         places=("Solothurn, Switzerland",)))
    for source in ("conversation:msg-mtc", "conversation:msg-missing-mom",
                   "conversation:msg-president", "conversation:msg-begins"):
        claims.append(moment(source, JOINS[source]))
    claims.append(moment(MILITARY, NEVER[MILITARY]))
    claims.append(moment(MILITARY, "Two-year Mormon mission in Zurich"))
    for source in ("conversation:msg-statement", "conversation:msg-before",
                   "conversation:msg-home", "conversation:msg-prep"):
        claims.append(moment(source, NEVER[source]))
    claims.append(moment("conversation:msg-aj", NEVER["conversation:msg-aj"],
                         subject="A.J. (brother)"))
    # A dated moment at home in Mesa in the mission's months.
    claims.append(moment(MESA_MOMENT, "Dad's paint business grows",
                         places=("Mesa, Arizona",), when=stated("2001-03")))
    claims.extend(extra)
    return claims, rows


def plan(claims: list, rows: list):
    return eb.plan(claims, entity_index=ec.entity_index(ROSTERS),
                   landmark_entries=rows, now=NOW)


def mission_block(result) -> dict:
    blocks = [block for block in result.containments
              if block["event_kind"] == "mission"]
    assert len(blocks) == 1, [block["label"] for block in result.containments]
    return blocks[0]


def members(result) -> dict:
    return {row["telling_ref"]: row for row in mission_block(result)["members"]}


class AMissionContainsItsStaysTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.claims, cls.rows = vault()
        cls.result = plan(cls.claims, cls.rows)
        cls.members = members(cls.result)

    def test_the_mtc_and_every_area_stay_join(self):
        for source, label, *_ in STAYS:
            with self.subTest(stay=label):
                self.assertIn(source, self.members)
                self.assertTrue(self.members[source]["dated"])
                self.assertTrue(self.members[source]["date_inside_span"])

    def test_each_stay_joins_through_its_own_link(self):
        keys = {source: set(self.members[source]["entities"]) for source, *_ in STAYS}
        # The MTC by name — its three letters are below the roster floor.
        self.assertIn("setting/mission", keys["landmark:entry-mtc"])
        # Solothurn: the area a telling of the mission sets it in.
        self.assertIn("place/solothurn-switzerland", keys["landmark:entry-solothurn"])
        # Friedrichshafen: the stay R7 dated his missionary tenure from.
        self.assertIn("place/friedrichshafen-germany",
                      keys["landmark:entry-friedrichshafen"])
        # Luzern: dated inside the span, in the country the entry names.
        self.assertEqual(keys["landmark:entry-luzern"], {"region/switzerland"})

    def test_the_mission_names_its_places_and_regions(self):
        container = next(c for c in self.result.containers.values()
                         if c.event_kind == "mission")
        self.assertEqual(container.places, frozenset({
            "place/solothurn-switzerland", "place/friedrichshafen-germany"}))
        self.assertEqual(container.regions, frozenset({"switzerland", "germany"}))
        # The MTC is a setting, not an area: Utah is not covered.
        self.assertNotIn("utah", container.regions)

    def test_a_home_in_mesa_in_the_same_months_does_not_join(self):
        self.assertNotIn(MESA[0], self.members)
        self.assertNotIn(MESA_MOMENT, self.members)

    def test_undated_moments_join_only_by_a_link(self):
        for source, label in JOINS.items():
            with self.subTest(moment=label):
                self.assertIn(source, self.members)
                self.assertFalse(self.members[source]["dated"])
        self.assertIn("place/solothurn-switzerland",
                      self.members["conversation:msg-assignment"]["entities"])

    def test_i_have_not_served_in_the_military_does_not_join(self):
        self.assertNotIn(MILITARY, self.members)

    def test_a_bare_mention_of_the_word_never_joins(self):
        for source, label in NEVER.items():
            with self.subTest(telling=label):
                self.assertNotIn(source, self.members)

    def test_the_missions_own_roster_entity_is_not_a_key(self):
        for row in self.members.values():
            self.assertNotIn("period/switzerland-mission", row["entities"])


class TheOldKeyWouldHaveFailedTests(unittest.TestCase):
    """The defect reproduced: grouped on the shared roster entity alone (the
    v356 key), the stays are out and the word is in."""

    def test_the_roster_key_alone_reproduces_lifehug_413(self):
        claims, rows = vault()
        index = ec.entity_index(ROSTERS)
        views = eb.telling_views(
            claims, entity_index=index,
            participation_kinds=lp.participation_kinds_by_telling(rows),
            landmark_entries=rows)
        units = eb.candidates(views)
        found = {key: c for key, c in ec.containers(views, units,
                                                     entity_index=index).items()
                 if c.event_kind == "mission"}
        (key, container), = found.items()
        v356 = {key: ec.Container(
            key=container.key, episode_id=container.episode_id, label=container.label,
            entities=container.entities, span=container.span,
            opened_by=container.opened_by, kind=container.kind, event_kind="")}
        old = {row["telling_ref"] for row in ec.containment_rows(views, v356)}
        self.assertTrue({MILITARY, "conversation:msg-aj", "conversation:msg-before"} <= old)
        self.assertFalse({source for source, *_ in STAYS} & old)


class TheSettingVocabularyTests(unittest.TestCase):

    def test_settings(self):
        for text in ("Missing mom on his mission", "First isolation during mission in Zurich",
                     "Neil Hall serves as mission president", "Residence at the MTC",
                     "Mission assignment to Solothurn", "LDS mission service begins",
                     "Missionary Training Center stay", "Two years away on church mission"):
            with self.subTest(text=text):
                self.assertEqual(ec.span_settings([text], ["self"])[0],
                                 frozenset({"mission"}))

    def test_not_settings(self):
        for text in ("I have not served in the military", "Served two-year Mormon mission",
                     "Two-year Mormon mission in Zurich", "Returned home from mission",
                     "Coming home from mission", "Late-night returns before mission",
                     "Ellsworth remains bishop after mission return",
                     "Bishop Ellsworth guides mission preparation",
                     "Preparing to leave on mission at 18", "the wrong mission statement",
                     "Founding Etherfuse's accessibility mission",
                     "Flight home to Mesa from mission"):
            with self.subTest(text=text):
                self.assertEqual(ec.span_settings([text], ["self"])[0], frozenset())

    def test_someone_elses_mission_is_not_his(self):
        index = ec.entity_index(ROSTERS)
        subject = ec.resolve_entity_set(["A.J. (brother)"], index)
        self.assertEqual(ec.span_settings(["AJ on his mission"], ["A.J. (brother)"],
                                          subject)[0], frozenset())
        # "Neil Hall / the narrator" and "narrator's family" are still his.
        self.assertEqual(ec.span_settings(["Family finances improved during mission"],
                                          ["narrator's family"])[0], frozenset({"mission"}))


class OtherContainersAreUntouchedTests(unittest.TestCase):

    def test_a_residence_still_contains_by_its_own_entity(self):
        claims, rows = vault(extra=(moment("conversation:msg-luzern-lake",
                                           "Swimming in the lake at Luzern, Switzerland"),))
        result = plan(claims, rows)
        luzern = [block for block in result.containments
                  if block["label"] == "Luzern, Switzerland"]
        self.assertEqual(len(luzern), 1)
        self.assertIn("conversation:msg-luzern-lake",
                      {row["telling_ref"] for row in luzern[0]["members"]})
        self.assertNotIn("places", luzern[0])
        # Undated and named only by a region-level stay, it is not a mission
        # member: Luzern is covered for DATED tellings only.
        self.assertNotIn("conversation:msg-luzern-lake", members(result))


if __name__ == "__main__":
    unittest.main()
