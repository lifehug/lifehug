"""v217 / person dates — born and died get a home on the person.

Birth and death are the most common datable facts in a life story and until
v217 they had nowhere to live: `entity_roster._SETTLED_IDENTITY_FIELDS` held
only `relationship` and `living`, `entity-verdict` had no date flags, and TWO
dates the landmark set already collects were dropped on the floor — a family
member's stated birth year (`family` carries it; the roster invocation never
emitted it) and a `losses` person's death year (whose person never reached the
roster at all, because the join read only `filed["family"]`).

Synthetic data only; NEVER references ~/Workspace/dave.
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SYSTEM = ROOT / "system"
sys.path.insert(0, str(SYSTEM))
sys.path.insert(0, str(ROOT / "tests"))

import chronology as chrono  # noqa: E402
import entity_roster  # noqa: E402
import entity_verdict  # noqa: E402
import landmarks_interaction as li  # noqa: E402
from tempdirs import root_parent_tmp  # noqa: E402


def _date(best: str, basis: str = "stated") -> dict:
    record = chrono.parse_edtf(best, basis=basis)
    assert record is not None
    return record.to_dict()


def _family(label, relation, *, year=None, living=None):
    entry = {"domain": "family", "label": label, "who": label, "relation": relation}
    if year is not None:
        entry["date"] = _date(year)
    if living is not None:
        entry["living"] = living
    return entry


def _loss(label, *, year=None):
    entry = {"domain": "losses", "label": label, "who": label, "happened": True}
    if year is not None:
        entry["year"] = year
        entry["date"] = _date(year)
    return entry


LANDMARKS = {
    "family": [
        _family("James", "sibling", year="1976", living=True),
        _family("Betty Jo", "grandparent", living=False),
        _family("Nobody", ""),
    ],
    "losses": [
        _loss("Grandpa Ray", year="2003"),
        _loss("Someone Undated"),
    ],
}


class RosterShapeTests(unittest.TestCase):
    """The two fields are SETTLED facts, or a refresh silently drops them."""

    def test_born_and_died_are_settled_identity_fields(self):
        for field in ("born", "died"):
            self.assertIn(field, entity_roster._SETTLED_IDENTITY_FIELDS)

    def test_the_date_field_list_is_named_once(self):
        self.assertEqual(entity_roster.PERSON_DATE_FIELDS, ("born", "died"))
        self.assertTrue(
            set(entity_roster.PERSON_DATE_FIELDS)
            <= set(entity_roster._SETTLED_IDENTITY_FIELDS))

    def test_normalize_keeps_both_dates_and_fills_their_bounds(self):
        """A bare `best` dates nothing until `normalized_date` fills bounds."""
        entries = entity_roster.normalize(
            "person",
            [{"name": "Ada", "qualifies": True,
              "born": {"best": "1948", "basis": "stated"},
              "died": {"best": "2019", "basis": "stated"}}],
            [], {}, 8.0, 2)
        self.assertEqual(entries[0]["born"]["earliest"], "1948")
        self.assertEqual(entries[0]["born"]["latest"], "1948")
        self.assertEqual(entries[0]["died"]["best"], "2019")

    def test_normalize_drops_an_unreadable_date_rather_than_storing_junk(self):
        entries = entity_roster.normalize(
            "person", [{"name": "Ada", "qualifies": True, "born": "not a date"}],
            [], {}, 8.0, 2)
        self.assertNotIn("born", entries[0])

    def test_a_refresh_that_omits_the_dates_preserves_them(self):
        """The exact `keywords`/`relationship` recipe, for the new fields."""
        previous = {"entities": [{"name": "Ada", "slug": "ada", "aliases": [],
                                  "born": _date("1948"), "died": _date("2019"),
                                  "relationship": "parent"}]}
        folded, _ = entity_roster.apply_previous_decisions(
            [{"name": "Ada", "qualifies": True}], previous)
        self.assertEqual(folded[0]["born"]["best"], "1948")
        self.assertEqual(folded[0]["died"]["best"], "2019")

    def test_a_dated_person_survives_a_refresh_that_drops_them_entirely(self):
        previous = {"entities": [{"name": "Ada", "slug": "ada", "aliases": [],
                                  "born": _date("1948")}]}
        folded, _ = entity_roster.apply_previous_decisions(
            [{"name": "Someone Else", "qualifies": True}], previous)
        self.assertIn("ada", [e.get("slug") for e in folded])

    def test_an_empty_refresh_does_not_lose_a_dated_person(self):
        previous = {"entities": [{"name": "Ada", "slug": "ada", "aliases": [],
                                  "died": _date("2019")}]}
        folded, _ = entity_roster.apply_previous_decisions([], previous)
        self.assertEqual(folded[0]["slug"], "ada")


class VerdictDateFlagTests(unittest.TestCase):
    """`entity-verdict --born/--died`, on the ONE roster writer."""

    def _empty_roster(self):
        tmp = root_parent_tmp(self, ROOT)
        path = tmp / "person.json"
        path.write_text(json.dumps(
            {"version": 1, "type": "person", "entities": []}), encoding="utf-8")
        for module in (entity_roster, entity_verdict):
            patcher = mock.patch.object(module, "roster_file", lambda _t, p=path: p)
            patcher.start()
            self.addCleanup(patcher.stop)
        return path

    def test_the_dates_reuse_the_landmark_clis_own_date_reader(self):
        """ONE date definition. A human form the landmark CLI accepts works."""
        record = entity_verdict.parse_person_date("born", "spring 1948")
        self.assertEqual(record["best"], chrono.parse_edtf("spring 1948").best)
        self.assertEqual(record["basis"], "stated")
        self.assertTrue(record["earliest"] and record["latest"])

    def test_an_unreadable_date_refuses_before_any_write(self):
        path = self._empty_roster()
        before = path.read_bytes()
        with self.assertRaises(entity_verdict.EntityVerdictError):
            entity_verdict.apply_verdict("person", "ada", "clear", born="banana",
                                         ensure=True, name="Ada")
        self.assertEqual(path.read_bytes(), before)

    def test_an_unknown_basis_refuses(self):
        with self.assertRaises(entity_verdict.EntityVerdictError):
            entity_verdict.parse_person_date("born", "1948", "vibes")

    def test_ensure_creates_a_dated_row_that_is_never_page_eligible(self):
        self._empty_roster()
        entry = entity_verdict.apply_verdict(
            "person", "ada", "clear", born="1948", died="2019",
            ensure=True, name="Ada")
        self.assertEqual(entry["born"]["best"], "1948")
        self.assertEqual(entry["died"]["best"], "2019")
        self.assertFalse(entry["page_eligible"])

    def test_re_filing_the_same_dates_converges_to_identical_bytes(self):
        path = self._empty_roster()
        entity_verdict.apply_verdict("person", "ada", "clear", born="1948",
                                     ensure=True, name="Ada")
        once = path.read_bytes()
        entity_verdict.apply_verdict("person", "ada", "clear", born="1948",
                                     ensure=True, name="Ada")
        self.assertEqual(path.read_bytes(), once)


class DatePrecedenceTests(unittest.TestCase):
    """Derived never overwrites stated; same basis wins by recency."""

    def _empty_roster(self):
        tmp = root_parent_tmp(self, ROOT)
        path = tmp / "person.json"
        path.write_text(json.dumps(
            {"version": 1, "type": "person", "entities": []}), encoding="utf-8")
        for module in (entity_roster, entity_verdict):
            patcher = mock.patch.object(module, "roster_file", lambda _t, p=path: p)
            patcher.start()
            self.addCleanup(patcher.stop)
        return path

    def test_a_weaker_basis_never_overwrites_a_stated_date(self):
        self._empty_roster()
        entity_verdict.apply_verdict("person", "ada", "clear", born="1948",
                                     born_basis="stated", ensure=True, name="Ada")
        entry = entity_verdict.apply_verdict("person", "ada", "clear", born="1950",
                                             born_basis="order")
        self.assertEqual(entry["born"]["best"], "1948")
        self.assertEqual(entry["born"]["basis"], "stated")

    def test_the_same_basis_wins_by_recency(self):
        self._empty_roster()
        entity_verdict.apply_verdict("person", "ada", "clear", born="1948",
                                     born_basis="stated", ensure=True, name="Ada")
        entry = entity_verdict.apply_verdict("person", "ada", "clear", born="1949",
                                             born_basis="stated")
        self.assertEqual(entry["born"]["best"], "1949")

    def test_a_stronger_basis_replaces_a_weaker_one(self):
        self._empty_roster()
        entity_verdict.apply_verdict("person", "ada", "clear", born="1950",
                                     born_basis="order", ensure=True, name="Ada")
        entry = entity_verdict.apply_verdict("person", "ada", "clear", born="1948",
                                             born_basis="document")
        self.assertEqual(entry["born"]["best"], "1948")

    def test_the_rule_is_chronologys_own_claim_score_not_a_second_table(self):
        strong = _date("1948", basis="document")
        weak = _date("1950", basis="order")
        self.assertIs(entity_verdict._preferred_date(strong, weak), strong)
        self.assertIs(entity_verdict._preferred_date(weak, strong), strong)

    def test_a_call_that_names_no_date_leaves_the_stored_one_alone(self):
        self._empty_roster()
        entity_verdict.apply_verdict("person", "ada", "clear", born="1948",
                                     ensure=True, name="Ada")
        entry = entity_verdict.apply_verdict("person", "ada", "graduate",
                                             relationship="parent")
        self.assertEqual(entry["born"]["best"], "1948")


class LandmarkToRosterTests(unittest.TestCase):
    """The two dropped-on-the-floor dates, and the losses join."""

    def test_a_family_members_stated_birth_year_now_reaches_the_roster(self):
        argv = next(a for a in li.person_roster_invocations(LANDMARKS)
                    if a[2] == "james")
        self.assertIn("--born", argv)
        self.assertEqual(argv[argv.index("--born") + 1], "1976")
        self.assertEqual(argv[argv.index("--born-basis") + 1], "stated")

    def test_an_undated_family_member_emits_no_date_flag(self):
        argv = next(a for a in li.person_roster_invocations(LANDMARKS)
                    if a[2] == "betty-jo")
        self.assertNotIn("--born", argv)

    def test_a_losses_person_reaches_the_roster_with_their_death_year(self):
        argv = next(a for a in li.person_roster_invocations(LANDMARKS)
                    if a[2] == "grandpa-ray")
        self.assertEqual(argv[:4], ["entity-verdict", "person", "grandpa-ray", "clear"])
        self.assertIn("--not-living", argv)
        self.assertEqual(argv[argv.index("--died") + 1], "2003")
        self.assertIn("--ensure", argv)
        self.assertNotIn("--relationship", argv)

    def test_an_undated_loss_still_files_the_person(self):
        argv = next(a for a in li.person_roster_invocations(LANDMARKS)
                    if a[2] == "someone-undated")
        self.assertNotIn("--died", argv)
        self.assertIn("--not-living", argv)

    def test_the_pre_v217_name_is_the_same_function(self):
        self.assertIs(li.family_roster_invocations, li.person_roster_invocations)

    def test_the_wrapper_forwards_the_date_flags_to_the_one_writer(self):
        """`lifehug.py entity-verdict` is a pass-through; the dates must pass."""
        import lifehug  # noqa: PLC0415

        seen = []
        parser = lifehug.build_parser()
        args = parser.parse_args(
            ["entity-verdict", "person", "ada", "clear",
             "--born", "1948", "--born-basis", "document",
             "--died", "2019", "--died-basis", "stated"])
        with mock.patch.object(lifehug, "run_python",
                               lambda _script, flags: seen.append(flags) or 0):
            self.assertEqual(lifehug.cmd_entity_verdict(args), 0)
        self.assertEqual(seen[0][seen[0].index("--born") + 1], "1948")
        self.assertEqual(seen[0][seen[0].index("--born-basis") + 1], "document")
        self.assertEqual(seen[0][seen[0].index("--died") + 1], "2019")
        self.assertEqual(seen[0][seen[0].index("--died-basis") + 1], "stated")

    def test_every_flag_the_invocations_emit_is_a_real_cli_flag(self):
        import lifehug  # noqa: PLC0415

        parser = lifehug.build_parser()
        for argv in li.person_roster_invocations(LANDMARKS):
            with self.subTest(slug=argv[2]):
                args = parser.parse_args(argv)
                self.assertEqual(args.type, "person")
                self.assertEqual(args.verdict, "clear")
                self.assertTrue(args.ensure)

    def test_lost_people_reads_only_the_losses_domain(self):
        self.assertEqual([p["slug"] for p in li.lost_people(LANDMARKS)],
                         ["grandpa-ray", "someone-undated"])
        self.assertEqual(li.lost_people({"family": LANDMARKS["family"]}), ())

    def test_a_none_answer_on_losses_names_nobody(self):
        self.assertEqual(li.lost_people({"losses": [{"domain": "losses", "none": True}]}), ())

    def test_the_invocations_file_the_dates_end_to_end(self):
        tmp = root_parent_tmp(self, ROOT)
        path = tmp / "person.json"
        path.write_text(json.dumps(
            {"version": 1, "type": "person", "entities": []}), encoding="utf-8")
        for module in (entity_roster, entity_verdict):
            patcher = mock.patch.object(module, "roster_file", lambda _t, p=path: p)
            patcher.start()
            self.addCleanup(patcher.stop)
        import lifehug  # noqa: PLC0415

        parser = lifehug.build_parser()
        for argv in li.person_roster_invocations(LANDMARKS):
            args = parser.parse_args(argv)
            entity_verdict.apply_verdict(
                "person", args.slug, args.verdict, relationship=args.relationship,
                living=args.living, born=args.born, born_basis=args.born_basis,
                died=args.died, died_basis=args.died_basis,
                ensure=True, name=args.name)
        rows = {e["slug"]: e for e in json.loads(path.read_text())["entities"]}
        self.assertEqual(rows["james"]["born"]["best"], "1976")
        self.assertEqual(rows["grandpa-ray"]["died"]["best"], "2003")
        self.assertIs(rows["grandpa-ray"]["living"], False)
        for row in rows.values():
            self.assertFalse(row["page_eligible"])


class PersonAnchorTests(unittest.TestCase):
    """The `entity_date` unlock finally has a consumer."""

    ROSTER = {"entities": [
        {"slug": "ada", "name": "Ada", "born": _date("1948"), "died": _date("2019")},
        {"slug": "james", "name": "James", "born": _date("1976")},
        {"slug": "grandpa-ray", "name": "Grandpa Ray", "died": _date("2003")},
        {"slug": "undated", "name": "Undated"},
    ]}

    def test_the_unlock_is_declared_and_now_consumed(self):
        rows = {row["domain"]: row for row in li.load_questions()}
        self.assertIn("entity_date", rows["partnerships"]["unlocks"])
        self.assertIn("entity_date", rows["children"]["unlocks"])
        self.assertTrue(li.anchors_from_people(self.ROSTER))

    def test_a_person_mints_a_born_and_a_died_anchor(self):
        anchors = li.anchors_from_people(self.ROSTER)
        self.assertIn("person:ada:born", anchors)
        self.assertIn("person:ada:died", anchors)
        self.assertEqual(anchors["person:ada:born"]["label"], "Ada was born")
        self.assertEqual(anchors["person:ada:died"]["label"], "Ada died")
        self.assertEqual(chrono.year_of(anchors["person:ada:born"]["date"]), 1948)

    def test_an_undated_person_mints_nothing(self):
        self.assertNotIn("person:undated:born", li.anchors_from_people(self.ROSTER))

    def test_the_landmark_store_wins_over_the_rosters_derived_copy(self):
        """D10: ONE anchor per person per fact, decided deterministically."""
        anchors = li.anchors_from_people(self.ROSTER, LANDMARKS)
        self.assertNotIn("person:james:born", anchors,
                         "the family landmark already anchors James's birth")
        self.assertNotIn("person:grandpa-ray:died", anchors,
                         "the losses landmark already anchors Ray's death")
        self.assertIn("person:ada:born", anchors,
                      "a person the landmark set never named still anchors")

    def test_the_two_indexes_together_hold_no_duplicate_person_fact(self):
        landmark_anchors = li.anchors_from_landmarks(LANDMARKS)
        people = li.anchors_from_people(self.ROSTER, LANDMARKS)
        self.assertEqual(set(landmark_anchors) & set(people), set())
        joined = {**landmark_anchors, **people}
        births = [k for k in joined if "james" in k and k.endswith("birth")]
        self.assertEqual(len(births), 1)

    def test_a_roster_list_works_as_well_as_a_roster_dict(self):
        self.assertEqual(li.anchors_from_people(self.ROSTER["entities"]),
                         li.anchors_from_people(self.ROSTER))

    def test_the_anchors_reach_the_persons_calendar(self):
        import timeline_interaction as ti  # noqa: PLC0415

        labels = {row["label"] for row in
                  ti.anchors_for_person(landmarks=LANDMARKS, people=self.ROSTER)}
        self.assertIn("Ada was born", labels)
        self.assertIn("Ada died", labels)
        self.assertIn("James was born", labels,
                      "the family landmark supplies James, not the roster copy")
        without = {row["label"] for row in
                   ti.anchors_for_person(landmarks=LANDMARKS)}
        self.assertNotIn("Ada was born", without,
                         "a caller that passes no roster gets the pre-v217 set")
        self.assertEqual(sum(1 for label in labels if label == "James was born"), 1)

    def test_the_anchors_reach_the_timeline_index_like_any_other(self):
        import timeline  # noqa: PLC0415

        anchors = timeline.anchor_index(
            [], [], [], landmarks=li.anchors_from_people(self.ROSTER))
        self.assertIn("person:ada:born", anchors)


class PersonPageTests(unittest.TestCase):
    """The page shows what the roster knows."""

    def test_the_summary_names_both_dates(self):
        import wiki_compile as wc  # noqa: PLC0415

        self.assertEqual(
            wc._person_dates_sentence({"born": _date("1948"), "died": _date("2019")}),
            "Born 1948, died 2019. ")

    def test_a_person_with_no_dates_reads_exactly_as_before(self):
        import wiki_compile as wc  # noqa: PLC0415

        self.assertEqual(wc._person_dates_sentence({}), "")

    def test_the_frontmatter_carries_the_edtf(self):
        import wiki_compile as wc  # noqa: PLC0415

        text = wc.frontmatter("Ada", "person", [], born_edtf="1948", died_edtf="2019")
        self.assertIn("\nborn: 1948\n", text)
        self.assertIn("\ndied: 2019\n", text)

    def test_the_frontmatter_omits_the_keys_when_unknown(self):
        import wiki_compile as wc  # noqa: PLC0415

        text = wc.frontmatter("Ada", "person", [])
        self.assertNotIn("born:", text)
        self.assertNotIn("died:", text)

    def test_the_page_edtf_comes_from_the_roster_record(self):
        import wiki_compile as wc  # noqa: PLC0415

        self.assertEqual(wc._person_date_edtf({"born": _date("1948")}, "born"), "1948")
        self.assertEqual(wc._person_date_edtf({}, "born"), "")


class OneDateDefinitionTests(unittest.TestCase):
    """The recurring-defect doctrine: one normalization body, not two."""

    def test_the_landmark_normalizer_is_the_chronology_one(self):
        self.assertIs(li._normalized_date, chrono.normalized_date)

    def test_the_normalizer_fills_bounds_a_bare_best_lacks(self):
        record = chrono.normalized_date({"best": "1948", "basis": "stated"})
        self.assertEqual((record["earliest"], record["latest"]), ("1948", "1948"))

    def test_the_normalizer_degrades_rather_than_raising(self):
        self.assertIsNone(chrono.normalized_date(None))
        self.assertIsNone(chrono.normalized_date("not a date"))


if __name__ == "__main__":
    unittest.main()
