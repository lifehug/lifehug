"""v360 (owner, 2026-09-25): the Landmark and Cornerstone VIEWS (`timeline_views`).

The owner's design: two square buttons under the Timeline's chart open a view
of what he has given — his landmarks as lanes and a list, with gaps (░) and
covered stretches (◇, his mission) shown and never asked, and his cornerstones
as a grid by person with ✓ exact day, ◐ needs the day, ⚠ disagreement, — not
given. "In my case you should have everything."

The shapes are the owner's (his Mesa addresses, his mission's MTC and Swiss
stays, his two Williams stays, his parents' wedding and his own); every record
is synthetic and nothing here reads a real vault.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "system"))
sys.path.insert(0, str(ROOT / "tests"))

import cornerstones as cs  # noqa: E402
import landmark_projection as lp  # noqa: E402
import temporal_publication as pub  # noqa: E402
import temporal_timeline as tt  # noqa: E402
import timeline_views as tv  # noqa: E402
from test_v358_a_gendered_word_when_it_is_known import (  # noqa: E402
    NOW, OWNER_NAMES, VaultFixture, owners_roster, row,
)


def rec(best: str, *, confidence: str = "certain") -> dict:
    grain = {4: "year", 7: "month", 10: "day"}[len(best)]
    return {"best": best, "earliest": best, "latest": best, "granularity": grain,
            "confidence": confidence, "basis": "stated", "anchors": [], "provenance": []}


def span(start: str, end: str | None = None) -> dict:
    out = {"start": rec(start)}
    if end:
        out["end"] = rec(end)
    return out


def home(label: str, start: str, end: str | None, **fields) -> dict:
    return {"domain": "residences", "label": label, "span": span(start, end), **fields}


def owners_homes() -> list[dict]:
    """His residences' shapes, around the mission."""
    return [
        home("Hope", "1995-06", "1997-06", nickname="Hope",
             address="2624 E Hope St, Mesa, AZ", city="Mesa, Arizona"),
        home("Williams", "1997-06", "2000-08", nickname="Williams",
             address="701 N Williams, Mesa, AZ", city="Mesa, Arizona",
             place_ref="place/residence-williams"),
        home("MTC", "2000-08", "2000-10", nickname="MTC",
             address="2005 North 900 East, Provo, UT 84602", city="Provo, Utah"),
        home("Solothurn, Switzerland", "2000-10", "2000-12",
             address="Hermesbühlstrasse 4, 4500 Solothurn, Switzerland",
             city="Solothurn, Switzerland"),
        # A hole inside the mission (2001-01 -> 2001-06) is covered, not a gap.
        home("Wetzikon, Switzerland", "2001-06", "2002-06-06",
             address="Bahnhofstrasse 278, 8623 Kempten, Switzerland",
             city="Wetzikon, Switzerland"),
        home("Williams", "2002-06-07", "2005-06", nickname="Williams",
             address="701 N Williams, Mesa, AZ", city="Mesa, Arizona",
             place_ref="place/residence-williams"),
        # A real hole: 2005-06 -> 2007-06, nothing covers it.
        home("Kristen", "2007-06", "2009-06", nickname="Kristen",
             address="734 N Kristen, Mesa, AZ 85213", city="Mesa, Arizona"),
        # One month between stays is not a gap.
        home("BJ's House", "2009-08", "2010-12", nickname="BJ's House",
             address="3356 E Fairbrook St, Mesa, AZ 85213", city="Mesa, Arizona"),
        home("Christamon", "2019-08", None, nickname="Christamon", ongoing=True,
             address="6 Christamon E, Irvine, CA 92620", city="Irvine, California"),
    ]


def owners_domains() -> dict:
    return {
        "residences": owners_homes(),
        "schools": [
            {"domain": "schools", "label": "Mountain View", "span": span("1995-08", "1999-06")},
            {"domain": "schools", "label": "Missionary Training Center (MTC)",
             "span": span("2000-08", "2000-10")},
            {"domain": "schools", "label": "Community College", "span": span("2002-08", "2005-06")},
        ],
        "work": [
            {"domain": "work", "label": "Arizona Car Company", "span": span("1997-06", "2000-08")},
            {"domain": "work", "label": "Missionary - The Church of Jesus Christ of Latter Day Saints",
             "span": span("2000-10", "2002-06-06")},
            {"domain": "work", "label": "Taylor Design Studio", "span": span("2002-06-07", "2005-06")},
            {"domain": "work", "label": "Taylor Design Studio", "span": span("2007-06", "2007-08")},
            {"domain": "work", "label": "Etherfuse", "span": span("2022-05")},
            {"domain": "work", "label": "SEO work"},
        ],
        "military": [{"none": True}],
        "children": [{"domain": "children", "label": "Harvey Rex Taylor",
                      "who": "Harvey Rex Taylor", "date": rec("2021-10-11")}],
    }


def by_domain(view: dict) -> dict:
    return {row["domain"]: row for row in view["domains"]}


def landmark(view: dict, domain: str, label: str) -> dict:
    return next(row for row in by_domain(view)[domain]["landmarks"] if row["label"] == label)


class AHomeShowsEveryFieldTests(unittest.TestCase):
    """:data:`timeline_views.A_HOME_SHOWS_EVERY_FIELD`."""

    def test_a_mesa_home(self):
        fields = tv.residence_fields({"nickname": "Kristen", "city": "Mesa, Arizona",
                                      "address": "734 N Kristen, Mesa, AZ 85213"})
        self.assertEqual(fields["nickname"], "Kristen")
        self.assertEqual(fields["address"], "734 N Kristen")
        self.assertEqual(fields["city"], "Mesa")
        self.assertEqual(fields["state"], "Arizona")
        self.assertEqual(fields["country"], "United States")
        self.assertEqual(fields["postal_code"], "85213")

    def test_a_state_code_alone_names_the_state(self):
        fields = tv.residence_fields({"address": "2624 E Hope St, Mesa, AZ"})
        self.assertEqual((fields["city"], fields["state"], fields["country"]),
                         ("Mesa", "Arizona", "United States"))

    def test_a_mission_area_is_in_switzerland(self):
        fields = tv.residence_fields({"city": "Wetzikon, Switzerland",
                                      "address": "Bahnhofstrasse 278, 8623 Kempten, Switzerland"})
        self.assertEqual((fields["city"], fields["state"], fields["country"]),
                         ("Wetzikon", None, "Switzerland"))
        self.assertEqual(fields["address"], "Bahnhofstrasse 278")

    def test_friedrichshafen_is_in_germany(self):
        fields = tv.residence_fields(
            {"address": "Ravensburger Str. 39, D-88046 Friedrichshafen, Germany"})
        self.assertEqual((fields["city"], fields["country"]), ("Friedrichshafen", "Germany"))
        self.assertIsNone(fields["state"])

    def test_nothing_is_invented(self):
        fields = tv.residence_fields({"nickname": "Grandma's"})
        self.assertEqual(fields["nickname"], "Grandma's")
        for key in ("address", "city", "state", "country", "postal_code"):
            self.assertIsNone(fields[key], key)
        # A trailing word that is neither a state nor a known country is left.
        fields = tv.residence_fields({"city": "Oaxaca, Oax"})
        self.assertEqual(fields["city"], "Oaxaca")
        self.assertIsNone(fields["state"])
        self.assertIsNone(fields["country"])


class TheLandmarksViewTests(unittest.TestCase):

    def setUp(self):
        self.view = tv.landmarks_view(owners_domains())

    def test_domains_come_in_the_owners_order_span_kinds_only(self):
        """Landmarks = span kinds only (2026-09-25): homes, schools, work,
        and mission (mention-opened — derived from the Missionary work entry
        + MTC school entry's covered stretch, item 3) UNDER work — military
        said "none", so it is HIDDEN outright, and children (a point kind)
        never rides here at all, whatever the fold files under it."""
        self.assertEqual([row["domain"] for row in self.view["domains"]],
                         ["residences", "schools", "work", "missions"])
        self.assertEqual(by_domain(self.view)["residences"]["label"], "Homes")
        self.assertNotIn("military", by_domain(self.view))
        self.assertNotIn("children", by_domain(self.view))

    def test_no_point_kinds_ever_ride_the_landmarks_lanes(self):
        """Partnerships/marriage, children, family, losses and birth are
        cornerstone material now — never a Landmarks lane, even when the fold
        still files entries under them (defensive)."""
        domains = dict(owners_domains())
        domains["partnerships"] = [{"domain": "partnerships", "label": "Katie",
                                    "who": "Katie", "date": rec("2007-01-11")}]
        domains["family"] = [{"domain": "family", "who": "Dad", "relation": "parent",
                              "date": rec("1954-06-04")}]
        domains["losses"] = [{"domain": "losses", "who": "Grandpa", "date": rec("1996-04-04")}]
        domains["birth"] = [{"domain": "birth", "date": rec("1981-07-11")}]
        view = tv.landmarks_view(domains)
        seen = {row["domain"] for row in view["domains"]}
        self.assertEqual(seen & set(tv.NON_SPAN_DOMAINS), set())

    def test_a_mentioned_kind_shows_a_hidden_one_does_not(self):
        """Mission is mention-opened: absent when nothing mentions it (no
        Missionary work entry, no MTC school entry, no filed `missions`
        entry — no covered stretch to derive it from), present when either a
        REAL `missions` domain entry is filed OR one can be derived
        (item 3, 2026-09-25)."""
        bare = {"residences": owners_homes()[:2],
               "schools": [{"domain": "schools", "label": "Mountain View",
                            "span": span("1995-08", "1999-06")}],
               "work": [{"domain": "work", "label": "Arizona Car Company",
                        "span": span("1997-06", "2000-08")}]}
        self.assertNotIn("missions", by_domain(tv.landmarks_view(bare)))
        filed = dict(bare)
        filed["missions"] = [{"domain": "missions", "label": "Swiss Mission",
                              "span": span("2000-08", "2002-06-06")}]
        self.assertIn("missions", by_domain(tv.landmarks_view(filed)))
        # The base fixture derives it too, from the Missionary/MTC entries.
        self.assertIn("missions", by_domain(self.view))

    def test_a_stay_he_had_twice_is_one_landmark_with_both_stays(self):
        williams = landmark(self.view, "residences", "Williams")
        self.assertEqual([(s["start"], s["end"]) for s in williams["stays"]],
                         [("1997-06", "2000-08"), ("2002-06-07", "2005-06")])
        self.assertEqual([s["start_grain"] for s in williams["stays"]], ["month", "day"])
        homes = by_domain(self.view)["residences"]["landmarks"]
        self.assertEqual(sum(1 for row in homes if row["label"] == "Williams"), 1)
        design = landmark(self.view, "work", "Taylor Design Studio")
        self.assertEqual(len(design["stays"]), 2)

    def test_a_real_hole_is_a_gap(self):
        gaps = by_domain(self.view)["residences"]["gaps"]
        self.assertEqual([(g["start"], g["end"]) for g in gaps],
                         [("2005-06", "2007-06"), ("2010-12", "2019-08")])
        self.assertEqual(gaps[0]["label"], "nothing recorded")
        self.assertEqual(gaps[0]["after"], "residences:williams")
        self.assertEqual(gaps[0]["before"], "residences:kristen")

    def test_the_gap_names_the_one_residence_gap_unknown(self):
        """`landmarks_interaction.residence_gaps` stays the one definition of
        the residence-gap unknown; the view names its key."""
        gap = by_domain(self.view)["residences"]["gaps"][0]
        self.assertEqual(gap["unknown_key"], "residence_gap:williams:kristen")

    def test_one_month_between_stays_is_not_a_gap(self):
        rows = by_domain(self.view)["residences"]["rows"]
        self.assertFalse(any(r["kind"] == "gap" and r["start"] == "2009-06" for r in rows))

    def test_nothing_after_an_ongoing_stay_is_a_gap(self):
        work = by_domain(self.view)["work"]
        # Etherfuse has a start and no end and is not marked ongoing: a
        # reading problem, and a point — not "open to today".
        self.assertEqual(work["rows"][-1]["entry_id"], "work:etherfuse")
        christamon = landmark(self.view, "residences", "Christamon")
        self.assertTrue(christamon["stays"][0]["ongoing"])
        self.assertNotIn("missing_end", christamon["problems"])

    def test_the_mission_covers_its_stretch(self):
        """:data:`timeline_views.A_COVERED_STRETCH_IS_NOT_A_GAP`. Once the
        mission has its own lane (item 3, 2026-09-25), Homes no longer draws
        a redundant covered banner over stays that are simply THERE — only
        the one real HOLE (2000-12 to 2001-06, no residence stay at all)
        still reads as ◇, because that still explains a gap."""
        stretch = self.view["covered"][0]
        self.assertEqual((stretch["kind"], stretch["start"], stretch["end"]),
                         ("missions", "2000-08", "2002-06-06"))
        self.assertEqual(stretch["label"], "on your mission")
        homes = by_domain(self.view)["residences"]
        # The hole inside the mission is covered, never a gap.
        self.assertFalse(any(g["start"] == "2000-12" for g in homes["gaps"]))
        covered = [r for r in homes["rows"] if r["kind"] == "covered"]
        self.assertEqual(len(covered), 1)
        # v360 (owner, 2026-09-25) (edit-forms round,
        # `timeline_views.A_MISSION_HOME_IS_LISTED_UNDER_MISSIONS`): the
        # mission's homes are listed under Missions only, so Homes carries ONE
        # line for the whole stretch — "on your mission · Aug 2000 – Jun 2002".
        self.assertEqual((covered[0]["start"], covered[0]["end"]), ("2000-08", "2002-06-06"))
        self.assertEqual(covered[0]["label"], "on your mission")
        self.assertEqual(covered[0]["covered_by"][0]["domain"], "schools")
        self.assertEqual([lm["label"] for lm in homes["landmarks"] if lm["label"] in
                          ("MTC", "Solothurn, Switzerland", "Wetzikon, Switzerland")], [])
        # Stays that are simply there (MTC, Solothurn, Wetzikon) are plain —
        # no "within", no nested/dashed banner — Homes shows every stay flat.
        self.assertFalse(any(r.get("within") for r in homes["rows"]))
        self.assertFalse(any(r.get("header") for r in homes["rows"]))

    def test_the_mission_gets_its_own_lane_under_work(self):
        """Item 3, 2026-09-25: the mission is derived from the covered
        stretch (never filed as its own domain here) and gets its own lane,
        positioned right under Work, with the MTC and Swiss/German stays
        nested — each its own bar, tooltip and click target, same as Homes."""
        names = [row["domain"] for row in self.view["domains"]]
        self.assertEqual(names.index("missions"), names.index("work") + 1)
        mission = by_domain(self.view)["missions"]
        self.assertEqual([lm["label"] for lm in mission["landmarks"]],
                         ["MTC", "Solothurn, Switzerland", "Wetzikon, Switzerland"])
        mtc = landmark(self.view, "missions", "MTC")
        self.assertEqual((mtc["stays"][0]["start"], mtc["stays"][0]["end"]), ("2000-08", "2000-10"))
        self.assertEqual(mtc["city"], "Provo")  # the same residence fields, copied

    def test_rows_run_oldest_first(self):
        rows = [r for r in by_domain(self.view)["residences"]["rows"] if not r.get("header")]
        starts = [r["start"][:7] for r in rows]
        self.assertEqual(starts, sorted(starts))

    def test_work_gaps_are_neutral_and_reading_problems_are_named(self):
        work = by_domain(self.view)["work"]
        self.assertTrue(all(g["label"] == "nothing recorded" for g in work["gaps"]))
        problems = {row["label"]: row["problems"] for row in self.view["problems"]}
        self.assertIn("missing_end", problems["Etherfuse"])
        self.assertIn("undated", problems["SEO work"])

    def test_a_landmark_plays_its_open_work_item_or_its_ladder(self):
        nodes = [{"node_id": "node:kristen", "event_kind": "residence", "label": "Kristen",
                  "subject_refs": ["Kristen"]}]
        items = [{"work_item_id": "work:kristen", "kind": "contradiction", "state": "open",
                  "node_ref": "node:kristen"}]
        view = tv.landmarks_view(owners_domains(), nodes=nodes, work_items=items)
        self.assertEqual(landmark(view, "residences", "Kristen")["play"],
                         {"kind": "work_item", "work_item_id": "work:kristen"})
        self.assertEqual(landmark(view, "residences", "Hope")["play"],
                         {"kind": "landmark", "domain": "residences", "subject": "Hope"})


def node(node_id: str, kind: str, label: str, subjects, best: str | None, *,
         conflict: str = "none") -> dict:
    return {"node_id": node_id, "event_kind": kind, "node_kind": "event", "label": label,
            "subject_refs": list(subjects), "conflict_state": conflict,
            "best_temporal_value": rec(best) if best else None}


def owners_nodes() -> list[dict]:
    return [
        node("node:born", "birth", "Born in Redlands", ["self"], "1981-07-11"),
        node("node:harvey", "birth", "Harvey's birth", ["person/harvey"], "2021",
             conflict="contradicted"),
        node("node:james", "birth", "James Everett Taylor's birth",
             ["person/james-everett-taylor"], "2013-05"),
        node("node:dad", "birth", "James Taylor's birth", ["person/james-taylor"], "1954-06-04"),
        node("node:grandpa", "death", "James Edwin Taylor Sr.'s death",
             ["person/james-edwin-taylor-sr"], "1996-04-04"),
        node("node:grandpa-born", "birth", "James Edwin Taylor Sr.'s birth",
             ["person/james-edwin-taylor-sr"], "1930-10-17"),
        node("node:parents-wedding", "married", "Parents' wedding", ["person/parents"],
             "1976-06-25"),
        # His own wedding, with his mother wrongly read as a subject too.
        node("node:wedding", "married", "Wedding reception in mother-in-law's backyard",
             ["self", "person/desiree-taylor"], "2007-01-11", conflict="contradicted"),
    ]


class TheCornerstonesViewTests(unittest.TestCase):

    def setUp(self):
        self.roster = owners_roster()
        relations = cs.Relations(self.roster, (), owner_names=OWNER_NAMES)
        items = [{"work_item_id": "work:harvey", "kind": "contradiction", "state": "open",
                  "node_ref": "node:harvey"},
                 {"work_item_id": "work:wedding", "kind": "contradiction", "state": "open",
                  "node_ref": "node:wedding"}]
        called = {"person/james-taylor": ("dad", "my dad"),
                  "person/desiree-taylor": ("Desi", "mom", "my mom"),
                  "person/anthon-james-taylor": ("AJ",),
                  "person/james-edwin-taylor-sr": ("grandfather", "grandpa")}
        self.view = tv.cornerstones_view(owners_nodes(), relations, roster=self.roster,
                                         work_items=items, called_by=called,
                                         owner_name="David James Taylor")
        self.rows = {row["person_ref"]: row for group in self.view["groups"]
                     for row in group["people"]}

    def test_the_groups_are_the_owners(self):
        self.assertEqual([g["group"] for g in self.view["groups"]],
                         ["you", "spouse", "children", "parents", "siblings", "grandparents"])
        self.assertEqual(self.view["columns"], ["born", "married", "divorced", "died"])

    def test_what_he_calls_them(self):
        self.assertEqual(self.rows["person/james-taylor"]["display_name"], "Dad")
        self.assertEqual(self.rows["person/desiree-taylor"]["display_name"], "Mom")
        self.assertEqual(self.rows["person/anthon-james-taylor"]["display_name"], "AJ")
        self.assertEqual(self.rows["person/james-edwin-taylor-sr"]["display_name"], "Grandpa")
        self.assertEqual(self.rows["self"]["display_name"], "You")

    def test_statuses(self):
        self.assertEqual(self.rows["self"]["born"]["status"], tv.EXACT)
        self.assertEqual(self.rows["person/james-everett-taylor"]["born"]["status"], tv.NEEDS_DAY)
        self.assertEqual(self.rows["person/harvey"]["born"]["status"], tv.DISAGREEMENT)
        self.assertEqual(self.rows["person/katie-taylor"]["born"]["status"], tv.MISSING)
        self.assertEqual(self.rows["person/james-edwin-taylor-sr"]["died"]["status"], tv.EXACT)
        # A grandparent's birth is shown though it is never a card.
        self.assertEqual(self.rows["person/james-edwin-taylor-sr"]["born"]["value"], "1930-10-17")

    def test_a_death_nobody_told_is_not_owed(self):
        self.assertEqual(self.rows["person/katie-taylor"]["died"]["status"], tv.NOT_OWED)
        self.assertIsNone(self.rows["person/katie-taylor"]["died"]["play"])
        self.assertIsNone(self.rows["self"]["died"])

    def test_married_is_his_and_his_parents(self):
        mine = self.rows["self"]["married"]
        self.assertEqual((mine["value"], mine["status"]), ("2007-01-11", tv.DISAGREEMENT))
        self.assertEqual(self.rows["person/katie-taylor"]["married"]["value"], "2007-01-11")
        for parent in ("person/james-taylor", "person/desiree-taylor"):
            cell = self.rows[parent]["married"]
            self.assertEqual((cell["value"], cell["status"]), ("1976-06-25", tv.EXACT))
        # Harvey's wedding was never mentioned: NOT_OWED (blank), never a
        # default question — but still a cell, not a hard skip.
        self.assertEqual(self.rows["person/harvey"]["married"]["status"], tv.NOT_OWED)

    def test_a_kids_wedding_joins_the_required_set_once_mentioned(self):
        """"Kids' partnerships, business, and record fixes" (2026-09-25): a
        child's wedding/divorce is never a default question, but once he
        mentions it, it sits in the REQUIRED set (his children's own row),
        not Others."""
        nodes = [*owners_nodes(),
                 node("node:james-wedding", "married", "James married Ashley",
                      ["person/james-everett-taylor"], "2035-06-14")]
        relations = cs.Relations(self.roster, (), owner_names=OWNER_NAMES)
        view = tv.cornerstones_view(nodes, relations, roster=self.roster,
                                    owner_name="David James Taylor")
        rows = {r["person_ref"]: r for g in view["groups"] for r in g["people"]}
        cell = rows["person/james-everett-taylor"]["married"]
        self.assertEqual((cell["value"], cell["status"]), ("2035-06-14", tv.EXACT))
        self.assertFalse(any(o["person_ref"] == "person/james-everett-taylor"
                             for o in view["others"]))

    def test_play_only_where_something_needs_settling(self):
        self.assertIsNone(self.rows["self"]["born"]["play"])
        self.assertEqual(self.rows["person/harvey"]["born"]["play"],
                         {"kind": "work_item", "work_item_id": "work:harvey"})
        self.assertEqual(self.rows["self"]["married"]["play"],
                         {"kind": "work_item", "work_item_id": "work:wedding"})
        self.assertEqual(self.rows["person/james-everett-taylor"]["born"]["play"],
                         {"kind": "landmark", "domain": "children",
                          "subject": "James Everett Taylor"})


class TheCornerstoneMarkersTests(unittest.TestCase):
    """Item 2: one ◆ row pinned at the top of the Landmarks lanes — a marker
    per required-set birth/wedding/death, a tooltip naming the cornerstone
    and the residence that covers its date, and a click target that is the
    Cornerstones row's own ``person_ref``."""

    def setUp(self):
        domains = tv.landmarks_view(owners_domains())["domains"]
        self.homes = next(d for d in domains if d["domain"] == "residences")["landmarks"]

    @staticmethod
    def cview(**people_by_group) -> dict:
        return {"groups": [{"group": key, "people": rows} for key, rows in people_by_group.items()]}

    def test_a_birth_marker_names_the_cornerstone_and_the_residence_then(self):
        view = self.cview(children=[{
            "person_ref": "person/charlee", "display_name": "Charlee",
            "born": {"value": "2010-12-21", "grain": "day"},
            "married": None, "divorced": None, "died": None,
        }])
        markers = tv.cornerstone_markers(view, residences=self.homes)
        self.assertEqual(len(markers), 1)
        marker = markers[0]
        self.assertEqual(marker["kind"], "birth")
        self.assertEqual(marker["person_ref"], "person/charlee")  # the click target
        self.assertEqual(marker["tooltip"], "Charlee born · 21 Dec 2010 · while at BJ's House")

    def test_a_wedding_marker_is_one_per_couple_a_plain_diamond_no_line(self):
        """Owner, 2026-09-25: "marriage is a discrete date" — a wedding is a
        plain ◆, never a line (he read the earlier open-span line as him
        somehow being shown as married at birth)."""
        view = self.cview(
            you=[{"person_ref": "self", "display_name": "You",
                  "born": {"value": "1981-07-11", "grain": "day"},
                  "married": {"value": "2007-01-11", "grain": "day"},
                  "divorced": None, "died": None}],
            spouse=[{"person_ref": "person/katie-taylor", "display_name": "Katie",
                     "born": None,
                     "married": {"value": "2007-01-11", "grain": "day"},
                     "divorced": None, "died": None}])
        markers = tv.cornerstone_markers(view, residences=self.homes)
        weddings = [m for m in markers if m["kind"] == "wedding"]
        self.assertEqual(len(weddings), 1)  # one couple shares one date, one marker
        self.assertEqual(weddings[0]["person_ref"], "self")
        self.assertNotIn("line_to", weddings[0])
        self.assertNotIn("ongoing", weddings[0])

    def test_a_cornerstone_before_his_own_birth_produces_no_marker(self):
        """The axis is his life (owner, 2026-09-25): his parents' wedding, and
        a parent's own birth, both predate him and would read as HIS when
        clamped to an axis that starts at his birth — omitted here, though
        they still show in the Cornerstones grid itself."""
        view = self.cview(
            you=[{"person_ref": "self", "display_name": "You",
                  "born": {"value": "1981-07-11", "grain": "day"},
                  "married": {"value": "2007-01-11", "grain": "day"},
                  "divorced": None, "died": None}],
            parents=[{"person_ref": "person/james-taylor", "display_name": "Dad",
                      "born": {"value": "1954-06-04", "grain": "day"},
                      "married": {"value": "1976-06-25", "grain": "day"},
                      "divorced": None, "died": None}])
        markers = tv.cornerstone_markers(view, residences=self.homes)
        # Dad's birth (1954) and his wedding (1976, his parents') both predate
        # 1981-07-11: omitted. His own 2007 wedding and 1981 birth are not.
        self.assertFalse(any(m["person_ref"] == "person/james-taylor" for m in markers))
        self.assertTrue(any(m["person_ref"] == "self" and m["kind"] == "birth" for m in markers))
        self.assertTrue(any(m["person_ref"] == "self" and m["kind"] == "wedding" for m in markers))

    def test_a_death_marker(self):
        view = self.cview(parents=[{
            "person_ref": "person/james-taylor", "display_name": "Dad",
            "born": None, "married": None, "divorced": None,
            "died": {"value": "1996-04-04", "grain": "day"}}])
        marker = tv.cornerstone_markers(view, residences=self.homes)[0]
        self.assertEqual(marker["kind"], "death")
        self.assertEqual(marker["tooltip"].split(" · ")[0], "Dad died")

    def test_no_view_no_markers(self):
        self.assertEqual(tv.cornerstone_markers(None, residences=self.homes), [])
        self.assertEqual(tv.cornerstone_markers({"groups": []}, residences=self.homes), [])


def other_partnership(subject: str, partner: str, date_iso: str) -> dict:
    return {"domain": "partnerships", "subject": subject, "label": partner, "date": rec(date_iso)}


class TheOthersSectionTests(unittest.TestCase):
    """"OTHERS": another person's cornerstone-type event or partnership, only
    with a discrete date; never a business partner; never his or his kids'
    own partnerships (personal, drawn — or not — in the required set)."""

    def setUp(self):
        self.roster = {"version": 1, "type": "person", "entities": [
            *owners_roster()["entities"],
            row("Jacque Taylor", "jacque-taylor", "sibling"),
            row("Brett Cook", "brett-cook"),
        ]}
        self.relations = cs.Relations(self.roster, (), owner_names=OWNER_NAMES)
        anchor_only = {"best": "1970", "earliest": "1970", "latest": "1970",
                       "granularity": "year", "confidence": "estimated",
                       "basis": "anchor", "anchors": [], "provenance": []}
        friend_wedding = node("node:friend-wedding", "married", "A friend's wedding",
                             ["person/brett-cook"], None)
        friend_wedding["best_temporal_value"] = anchor_only
        nodes = [*owners_nodes(),
                 node("node:jacque-divorce", "divorced", "Jacque's divorce",
                      ["person/jacque-taylor"], "2015"),
                 friend_wedding]
        domains = {"partnerships": [
            other_partnership("Jacque Taylor", "Brett Cook", "2016-03"),
            other_partnership("Jacque Taylor", "Castle Island Ventures", "2019-05"),
        ]}
        self.view = tv.cornerstones_view(nodes, self.relations, roster=self.roster,
                                         landmark_domains=domains,
                                         owner_name="David James Taylor")
        self.others = {(o["person_ref"], o["milestone"]): o for o in self.view["others"]}

    def test_a_discrete_dated_event_shows(self):
        self.assertIn(("person/jacque-taylor", "divorce"), self.others)
        self.assertEqual(self.others[("person/jacque-taylor", "divorce")]["value"], "2015")

    def test_a_story_derived_reading_never_shows(self):
        self.assertFalse(any(o["milestone"] == "wedding" for o in self.view["others"]))

    def test_another_persons_partnership_shows_with_a_discrete_date(self):
        entry = self.others[("person/jacque-taylor", "partnership")]
        self.assertEqual(entry["partner"], "Brett Cook")
        self.assertEqual(entry["value"], "2016-03")

    def test_a_business_partner_never_appears(self):
        self.assertFalse(any("ventures" in (o.get("partner") or "").casefold()
                             for o in self.view["others"]))
        self.assertFalse(any("ventures" in (o.get("name") or "").casefold()
                             for o in self.view["others"]))

    def test_his_and_his_kids_partnerships_are_never_others(self):
        domains = {"partnerships": [other_partnership("David James Taylor", "Katie", "2007-01-11"),
                                    other_partnership("James Everett Taylor", "Ashley", "2035-06-14")]}
        view = tv.cornerstones_view(owners_nodes(), self.relations, roster=self.roster,
                                    landmark_domains=domains, owner_name="David James Taylor")
        self.assertFalse(any(o["milestone"] == "partnership" for o in view["others"]))


class ThePublishedViewsTests(unittest.TestCase):
    """Both views ride the published projection; the view block serves them."""

    def setUp(self):
        self.vault = VaultFixture(self)
        for ordinal, entry in enumerate(owners_homes()[:3], start=1):
            lp.file_landmark_record(self.vault.root, "residences", entry,
                                    ordinal=ordinal, now=NOW)
        lp.file_landmark_record(self.vault.root, "children", {
            "domain": "children", "label": "Harvey Rex Taylor", "who": "Harvey Rex Taylor",
            "date": rec("2021-10-11")}, ordinal=4, now=NOW)
        self.vault.publish()

    def test_the_projection_carries_both_and_the_view_serves_them(self):
        projection = pub.read_projection(self.vault.root)
        homes = next(d for d in projection["landmarks_view"]["domains"]
                     if d["domain"] == "residences")
        self.assertEqual([row["label"] for row in homes["landmarks"]], ["Hope", "Williams", "MTC"])
        self.assertIn("cornerstones_view", projection)
        view = pub.calculated_view(self.vault.root)
        self.assertEqual(view["landmarks_view"], projection["landmarks_view"])
        self.assertEqual(view["cornerstones_view"], projection["cornerstones_view"])
        self.assertIn("landmarks_view", pub.view_block_keys())
        self.assertIn("cornerstones_view", pub.view_block_keys())

    def test_the_views_move_no_rule_version(self):
        projection = pub.read_projection(self.vault.root)
        self.assertEqual(projection["calculation_rule_version"], tt.CALCULATION_RULE_VERSION)

    def test_the_rebuild_oracle_reproduces_them(self):
        self.assertTrue(pub.verify(self.vault.root, now=NOW)["identical"])


class NothingToShowPublishesNoKeyTests(unittest.TestCase):

    def test_a_vault_with_no_landmarks_publishes_no_landmarks_view(self):
        vault = VaultFixture(self)
        self.assertNotIn("landmarks_view", pub.read_projection(vault.root))
        self.assertIsNone(pub.calculated_view(vault.root)["landmarks_view"])


if __name__ == "__main__":
    unittest.main()
