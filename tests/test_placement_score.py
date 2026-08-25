"""v208 / ADR 0027 — the placement score, the certainty line's arithmetic.

The level ("how placed is this life, 0 → 1") and the margin ("one answer
would place 53 things") are ONE arithmetic — the width-sum `unknown_width`
has ranked on since v204 — and this suite is where that stays true.

What is pinned here:

* `unknown_years` — one definition of the interval a thing occupies absent an
  answer, one case per unknown kind;
* `placement_score` — the level, the pair, the band, the strip, the margin,
  and the guarded absence when there is no birth landmark;
* `prior_span` — the ghost's source, reconstructed rather than stored;
* row `resolves` / `leverage` — the glow's source, raw and unranked.

Synthetic data only; NEVER references ~/Workspace/dave.
"""

from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SYSTEM = ROOT / "system"
sys.path.insert(0, str(SYSTEM))

import chronology as chrono  # noqa: E402
import cross_dating as xd  # noqa: E402


def load(name):
    spec = importlib.util.spec_from_file_location(name, SYSTEM / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    orig = sys.modules.get(name)
    sys.modules[name] = mod
    try:
        spec.loader.exec_module(mod)
    finally:
        if orig is not None:
            sys.modules[name] = orig
        else:
            sys.modules.pop(name, None)
    return mod


tl = load("timeline")

LIFE = (1981, 2026)


def edtf(text):
    return chrono.parse_edtf(text, basis="stated")


class UnknownYearsTests(unittest.TestCase):
    """§A — one definition, one case per kind (contract §E.6)."""

    def test_a_moment_in_a_dated_era_takes_the_bands_span(self):
        data = {"periods": [{"slug": "childhood", "name": "Childhood",
                             "date": edtf("1984/1990")}]}
        row = {"kind": "moment", "period": "childhood"}
        self.assertEqual(tl.unknown_years(row, data, life=LIFE), [1984, 1990])

    def test_a_moment_in_an_undated_era_takes_the_life(self):
        data = {"periods": [{"slug": "lost", "name": "The Lost Years", "date": None}]}
        row = {"kind": "moment", "period": "lost"}
        self.assertEqual(tl.unknown_years(row, data, life=LIFE), [1981, 2026])

    def test_an_unplaced_moment_takes_the_life(self):
        row = {"kind": "moment", "period": None}
        self.assertEqual(tl.unknown_years(row, {}, life=LIFE), [1981, 2026])

    def test_a_moment_takes_the_covering_chapter_band_when_its_era_has_none(self):
        data = {"periods": [{"slug": "lost", "name": "Lost", "date": None}],
                "bands": [{"kind": "chapter", "ref": "3", "date": edtf("1995/1999"),
                           "periods": ["lost"]}]}
        row = {"kind": "moment", "period": "lost"}
        self.assertEqual(tl.unknown_years(row, data, life=LIFE), [1995, 1999])

    def test_a_period_bound_takes_its_own_derived_span_first(self):
        data = {"periods": [{"slug": "childhood", "name": "Childhood",
                             "date": edtf("1984/1990"),
                             "date_derived": {"rule": "moments"}}]}
        row = {"kind": "period_bound", "slug": "childhood", "period": "childhood"}
        self.assertEqual(tl.unknown_years(row, data, life=LIFE), [1984, 1990])

    def test_a_period_bound_otherwise_takes_the_hole_between_its_dated_neighbours(self):
        data = {"periods": [
            {"slug": "childhood", "name": "Childhood", "date": edtf("1984/1990")},
            {"slug": "lost", "name": "The Lost Years", "date": None},
            {"slug": "my-30s", "name": "My 30s", "date": edtf("2002/2012")},
        ]}
        row = {"kind": "period_bound", "slug": "lost", "period": "lost"}
        self.assertEqual(tl.unknown_years(row, data, life=LIFE), [1991, 2001])

    def test_a_period_bound_with_no_dated_neighbour_falls_to_the_life(self):
        data = {"periods": [{"slug": "lost", "name": "Lost", "date": None}]}
        row = {"kind": "period_bound", "slug": "lost", "period": "lost"}
        self.assertEqual(tl.unknown_years(row, data, life=LIFE), [1981, 2026])

    def test_a_place_span_takes_its_bands_span(self):
        data = {"periods": [{"slug": "childhood", "name": "Childhood",
                             "date": edtf("1984/1990")}]}
        row = {"kind": "place_span", "slug": "mesa", "period": "childhood"}
        self.assertEqual(tl.unknown_years(row, data, life=LIFE), [1984, 1990])

    def test_a_place_span_in_an_undated_band_falls_to_the_life(self):
        data = {"periods": [{"slug": "lost", "name": "Lost", "date": None}]}
        row = {"kind": "place_span", "slug": "mesa", "period": "lost"}
        self.assertEqual(tl.unknown_years(row, data, life=LIFE), [1981, 2026])

    def test_an_era_gap_keeps_the_interval_it_already_carries(self):
        row = {"kind": "era_gap", "years": [1991, 2001],
               "between": ["childhood", "my-30s"]}
        self.assertEqual(tl.unknown_years(row, {}, life=LIFE), [1991, 2001])

    def test_a_date_contradiction_takes_the_union_of_the_disputed_claims(self):
        row = {"kind": "date_contradiction", "period": "childhood",
               "years": [1984, 1996]}
        self.assertEqual(tl.unknown_years(row, {}, life=LIFE), [1984, 1996])

    def test_a_residence_gap_reads_its_own_reported_years_as_ints(self):
        row = {"kind": "residence_gap", "years": ["1992", "1995"]}
        self.assertEqual(tl.unknown_years(row, {}, life=LIFE), [1992, 1995])

    def test_a_landmark_subject_falls_to_the_life(self):
        row = {"kind": "landmark_subject", "domain": "family", "label": "Jackie"}
        self.assertEqual(tl.unknown_years(row, {}, life=LIFE), [1981, 2026])

    def test_with_no_birth_landmark_there_is_no_floor_to_invent(self):
        row = {"kind": "moment", "period": None}
        self.assertEqual(tl.unknown_years(row, {}, life=None), [])
        # …but a row that carries its OWN interval still carries it.
        gap = {"kind": "era_gap", "years": [1991, 2001]}
        self.assertEqual(tl.unknown_years(gap, {}, life=None), [1991, 2001])


class UnknownWidthFloorTests(unittest.TestCase):
    """§A — the 1.0 no-interval floor STAYS, so go-deep.md §8.2's degeneration
    property still holds on a birthless vault."""

    def test_a_row_with_no_interval_still_weighs_one(self):
        self.assertEqual(tl.unknown_width({"kind": "moment"}), 1.0)
        self.assertEqual(tl.unknown_width({"years": ["x", "y"]}), 1.0)
        self.assertEqual(tl.unknown_width(None), 1.0)

    def test_a_row_that_now_carries_an_interval_weighs_it(self):
        self.assertEqual(tl.unknown_width({"kind": "era_gap", "years": [1984, 1990]}), 6.0)


class LifeSpanTests(unittest.TestCase):
    def test_the_life_comes_from_the_birth_anchor(self):
        data = {"anchors": {"birth": {"label": "when you were born",
                                      "date": edtf("1981-07-11")}}}
        span = tl.life_span(data)
        self.assertEqual(span[0], 1981)
        self.assertGreaterEqual(span[1], 2026)

    def test_no_birth_anchor_is_no_life(self):
        self.assertIsNone(tl.life_span({"anchors": {}}))
        self.assertIsNone(tl.life_span({}))


# ---------------------------------------------------------------------------
# §B — the level, the pair, the band, the strip, the margin.
# ---------------------------------------------------------------------------

BIRTHDAY = {"best": "1981-07-11", "earliest": "1981-07-11", "latest": "1981-07-11",
            "granularity": "day", "confidence": "certain", "basis": "stated"}


def crema_payload(*, pinned: bool, per_era: int = 5, eras: int = 5) -> dict:
    """Crema's own case (research §2.2), as a timeline payload.

    `eras` five-year eras, `per_era` moments in each. **Smeared**: every moment
    is undated and therefore occupies its whole era. **Pinned**: every moment
    carries a day. The summed aoristic density is identical by construction —
    which is exactly Crema's point, and exactly what the score must not be
    fooled by.
    """
    periods, lineup, answers = [], {}, 0
    for index in range(eras):
        first = 1985 + 5 * index
        slug = f"era-{index}"
        periods.append({"slug": slug, "name": f"Era {index}", "chrono": index + 1,
                        "date": edtf(f"{first}/{first + 4}")})
        rows = []
        for _ in range(per_era):
            answers += 1
            ref = f"A{answers}"
            rows.append({
                "title": f"Moment {ref}", "description": f"Something happened ({ref}).",
                "when_hint": "", "anchor": None, "source": f"answers/{ref}.md",
                "source_short": ref,
                "date": edtf(f"{first + 1}-07-11") if pinned else None,
            })
        lineup[slug] = rows
    return {
        "anchors": {"birth": {"label": "when you were born", "date": edtf("1981-07-11"),
                              "kind": "birth"}},
        "periods": periods,
        "event_lineup": lineup,
        "unplaced_events": [],
        "entity_lineup": {},
        "bands": [{"kind": "period", "ref": p["slug"], "label": p["name"],
                   "date": p["date"], "periods": [p["slug"]], "places": [],
                   "unplaced_events": []} for p in periods],
        "gaps_by_period": {},
        "global_gaps": [],
    }


class CremaSeparationTests(unittest.TestCase):
    """§E.1 — the load-bearing golden.

    Crema 2012 (via `chronology-vis.md` §2.2): five events smeared uniformly
    over five blocks and five events precisely placed in those blocks give the
    IDENTICAL summed vector — "aoristic analysis does not distinguish between
    the two scenarios." The placement payload must.
    """

    def setUp(self):
        self.smeared = tl.placement_score(crema_payload(pinned=False))
        self.pinned = tl.placement_score(crema_payload(pinned=True))

    def test_the_summed_density_really_is_the_same_by_construction(self):
        # Each side puts the same number of moments in the same five eras —
        # the input Crema shows a summed curve cannot tell apart.
        for payload in (crema_payload(pinned=False), crema_payload(pinned=True)):
            self.assertEqual(sum(len(rows) for rows in payload["event_lineup"].values()), 25)

    def test_the_score_separates_them(self):
        self.assertGreater(self.pinned["score"], self.smeared["score"])
        self.assertGreater(self.pinned["score"], 0.97)
        self.assertLess(self.smeared["score"], 0.95)

    def test_the_strip_separates_them_where_the_moments_actually_sit(self):
        year = 1986  # era-0's moments, pinned or smeared
        pinned = next(r for r in self.pinned["per_year_band"] if r["year"] == year)
        smeared = next(r for r in self.smeared["per_year_band"] if r["year"] == year)
        self.assertGreater(pinned["pinned_fraction"], 0.8)
        self.assertLess(smeared["pinned_fraction"], 0.35)

    def test_the_cloud_membership_is_zero_against_five_and_twenty(self):
        undated = [row for row in tl.unknowns(crema_payload(pinned=False))
                   if row["kind"] == "moment"]
        self.assertEqual(len(undated), 25)
        self.assertEqual([row for row in tl.unknowns(crema_payload(pinned=True))
                          if row["kind"] == "moment"], [])

    def test_every_undated_row_carries_the_interval_the_score_counted(self):
        payload = crema_payload(pinned=False)
        rows = {row["key"]: row for row in tl.unknowns(payload)}
        row = rows["moment:era-0:A1"]
        self.assertEqual(row["years"], [1985, 1989])


class LevelTests(unittest.TestCase):
    """§B.1 — the properties the arithmetic must have."""

    def test_narrowing_an_interval_raises_the_score(self):
        before = tl.placement_score(crema_payload(pinned=False))["score"]
        after = tl.placement_score(crema_payload(pinned=True))["score"]
        self.assertGreater(after, before)

    def test_narrowing_exactly_one_interval_strictly_raises_the_score(self):
        """§B.1's property, pinned on ONE interval rather than on all of them:
        the population does not move, a single width does, and the score
        follows it."""
        payload = crema_payload(pinned=False)
        before = tl.placement_score(payload)
        payload["event_lineup"]["era-0"][0]["date"] = edtf("1986-07-11")
        after = tl.placement_score(payload)
        self.assertGreater(after["score"], before["score"])
        self.assertEqual(after["things"], before["things"])

    def test_adding_an_undated_moment_lowers_the_score(self):
        payload = crema_payload(pinned=True)
        before = tl.placement_score(payload)["score"]
        payload["unplaced_events"] = [
            {"title": "The dog that followed me home",
             "description": "A dog followed me home and stayed.", "when_hint": "",
             "anchor": None, "source": "answers/Z9.md", "source_short": "Z9",
             "date": None},
        ]
        self.assertLess(tl.placement_score(payload)["score"], before)

    def test_an_empty_vault_scores_nothing(self):
        self.assertIsNone(tl.placement_score({}))
        self.assertIsNone(tl.placement_score({
            "anchors": {"birth": {"date": edtf("1981-07-11")}}}))

    def test_a_day_pinned_thing_is_floored_at_one_day_never_zero(self):
        self.assertEqual(tl._record_width(edtf("1981-07-11"), LIFE), tl.DAY_YEARS)
        self.assertGreater(tl._record_width(edtf("1981"), LIFE), tl.DAY_YEARS)

    def test_an_open_bound_is_clamped_to_the_life_not_treated_as_a_point(self):
        self.assertGreater(tl._record_width(edtf("1984/.."), LIFE), 40.0)


class BandTests(unittest.TestCase):
    """§B.3 — fixed thresholds, documented as arbitrary but stable."""

    def test_the_five_bands_are_the_documented_cutoffs(self):
        self.assertEqual(tl.PLACEMENT_BANDS, (0.2, 0.4, 0.6, 0.8))
        self.assertEqual([tl.placement_score_band(v)
                          for v in (0.0, 0.19, 0.2, 0.39, 0.4, 0.59, 0.6, 0.79, 0.8, 1.0)],
                         [1, 1, 2, 2, 3, 3, 4, 4, 5, 5])

    def test_the_payload_carries_the_band_and_the_floor_caveat(self):
        score = tl.placement_score(crema_payload(pinned=True))
        self.assertEqual(score["band"], tl.placement_score_band(score["score"]))
        self.assertIs(score["caveat_floor"], True)


class PayloadShapeTests(unittest.TestCase):
    def test_the_block_carries_every_field_the_platform_twin_names(self):
        score = tl.placement_score(crema_payload(pinned=True))
        self.assertEqual(set(score), {
            "score", "score_stated", "band", "stated_fraction", "derived_fraction",
            "life_span_years", "things", "per_year_band", "caveat_floor", "next_gain",
        })
        self.assertEqual(score["things"], 30)  # 25 moments + 5 eras
        self.assertEqual(len(score["per_year_band"]), score["life_span_years"] + 1)
        for row in score["per_year_band"]:
            self.assertEqual(set(row), {"year", "pinned_fraction", "stated_vs_derived"})

    def test_the_stated_and_derived_fractions_are_shares_of_the_dated_things(self):
        score = tl.placement_score(crema_payload(pinned=True))
        self.assertAlmostEqual(score["stated_fraction"] + score["derived_fraction"], 1.0)
        self.assertEqual(score["derived_fraction"], 0.0)

    def test_an_empty_year_reads_zero_rather_than_being_left_out(self):
        score = tl.placement_score(crema_payload(pinned=True))
        empty = [row for row in score["per_year_band"] if row["pinned_fraction"] == 0.0]
        self.assertTrue(empty)  # 1981–1984 precede every era in the fixture
        self.assertTrue(all(row["year"] < 1985 or row["year"] > 2009 for row in empty))


# ---------------------------------------------------------------------------
# End to end, through `timeline_data` — the pair, the margin, the guard.
# ---------------------------------------------------------------------------

PAGE = """---
title: "{title}"
type: {page_type}
chrono: {chrono}
{extra}sources:
{sources}---

# {title}
"""


def _sources(refs):
    return "".join(f'  - "answers/{ref}.md"\n' for ref in refs)


class VaultFixture(unittest.TestCase):
    """One era with four moments the classifier could not date, and a birthday.

    Deliberately austere: no dated place, no age words, no landmark markers in
    any description. The ONLY thing that can date these moments is the era's
    own span, so `period:childhood` is the keystone and the margin's promise is
    exactly what filing that era's date delivers.
    """

    REFS = ("A1", "A2", "A3", "A4")
    LANDMARKS = {"version": 1, "domains": {"birth": [{"label": "birth", "date": BIRTHDAY}]}}

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.root = root
        (root / "wiki" / "periods").mkdir(parents=True)
        (root / "sources" / "manual").mkdir(parents=True)
        (root / "state" / "classifications").mkdir(parents=True)
        (root / "state" / "entity_rosters").mkdir()
        (root / "state" / "connectors").mkdir()

        self.write_period(dated=None)
        (root / "state" / "entity_rosters" / "period.json").write_text(json.dumps({
            "version": 1, "type": "period", "entities": [
                {"name": "Childhood", "slug": "childhood", "chrono": 1,
                 "page_eligible": True},
            ]}), encoding="utf-8")
        titles = ("The bike with no brakes", "The dog that followed me home",
                  "The letter about the farm", "The hill behind the house")
        for ref, title in zip(self.REFS, titles):
            (root / "state" / "classifications" / f"answers-{ref.lower()}.json").write_text(
                json.dumps({"source_path": f"answers/{ref}.md", "events": [
                    {"title": title, "description": f"{title}.", "when_hint": "",
                     "anchor": None, "date": None}]}), encoding="utf-8")

        self.store = root / "state" / "landmarks.json"
        self.store.write_text(json.dumps(self.LANDMARKS), encoding="utf-8")

        self._orig = {name: getattr(tl, name) for name in tl.VAULT_ROOT_NAMES}
        state = root / "state"
        for name, value in {
            "CLASSIFICATIONS_DIR": state / "classifications",
            "CONNECTORS_STATE_DIR": state / "connectors",
            "ENTITY_ROSTERS_DIR": state / "entity_rosters",
            "MANUAL_SOURCES_DIR": root / "sources" / "manual",
            "PLACEMENTS_FILE": state / "timeline_placements.json",
            "STATE_DIR": state,
            "WIKI_DIR": root / "wiki",
        }.items():
            setattr(tl, name, value)

    def tearDown(self):
        for name, value in self._orig.items():
            setattr(tl, name, value)
        self.tmp.cleanup()

    def write_period(self, *, dated):
        (self.root / "wiki" / "periods" / "childhood.md").write_text(
            PAGE.format(title="Childhood", page_type="period", chrono=1,
                        extra=f"date: {dated}\n" if dated else "",
                        sources=_sources(self.REFS)),
            encoding="utf-8")
        roster = self.root / "state" / "entity_rosters" / "period.json"
        if roster.exists():
            payload = json.loads(roster.read_text(encoding="utf-8"))
            for row in payload["entities"]:
                if dated:
                    row["date"] = dated
                else:
                    row.pop("date", None)
            roster.write_text(json.dumps(payload), encoding="utf-8")

    def data(self, *, landmarks=True):
        store = self.store if landmarks else self.root / "state" / "nothing.json"
        with mock.patch.object(tl, "LANDMARKS_STORE", store):
            return tl.timeline_data()


class ThePairIsImmovableTests(VaultFixture):
    """§E.3 / ruling 3 — the cross-dating pass moves `score` and cannot move
    `score_stated`. Bayliss's italic convention (research §1.5) as two numbers,
    and the Goodhart guard's display half."""

    EMPTY_REPORT = {"derived": 0, "by_rule": {}, "by_join": {}, "moments": [],
                    "bands": {"derived": 0, "by_rule": {}, "by_join": {}, "bands": []}}

    def without_the_pass(self):
        with mock.patch.object(tl.cross_dating, "cross_date",
                               return_value=dict(self.EMPTY_REPORT)):
            return self.data()

    def setUp(self):
        super().setUp()
        # An era the band ladder CAN date: its moments carry dates of their own,
        # so `span_from_dated` gives Childhood a derived span and containment
        # then reaches the rest.
        (self.root / "state" / "classifications" / "answers-a1.json").write_text(
            json.dumps({"source_path": "answers/A1.md", "events": [
                {"title": "The bike with no brakes",
                 "description": "The bike with no brakes.", "when_hint": "",
                 "anchor": None, "date": {"stated": "1990"}}]}), encoding="utf-8")

    def test_the_pass_derives_something_at_all(self):
        self.assertGreater(self.data()["counts"]["periods_cross_dated"], 0)

    def test_the_pass_moves_the_score(self):
        self.assertGreater(self.data()["placement"]["score"],
                           self.without_the_pass()["placement"]["score"])

    def test_the_pass_leaves_the_stated_score_byte_identical(self):
        self.assertEqual(self.data()["placement"]["score_stated"],
                         self.without_the_pass()["placement"]["score_stated"])

    def test_the_derived_fraction_reports_what_the_pass_did(self):
        self.assertGreater(self.data()["placement"]["derived_fraction"], 0.0)
        self.assertEqual(self.without_the_pass()["placement"]["derived_fraction"], 0.0)


class PromiseEqualsDeliveryTests(VaultFixture):
    """§E.4 — the #633 reconciliation guard, applied to the score.

    `next_gain` says what answering the star is worth. Filing that answer at
    the grain the margin assumes must deliver exactly that, or the level and
    the margin have drifted apart again.
    """

    def test_the_star_is_the_era_and_the_margin_names_it(self):
        gain = self.data()["placement"]["next_gain"]
        self.assertEqual(gain["anchor"], "period:childhood")
        self.assertEqual(set(gain), {"anchor", "count", "delta"})

    def test_a_wholly_unplaced_life_scores_zero(self):
        self.assertEqual(self.data()["placement"]["score"], 0.0)

    def test_filing_the_answer_delivers_the_promised_delta(self):
        before = self.data()["placement"]
        promised = before["next_gain"]["delta"]
        self.assertGreater(promised, 0.0)
        self.write_period(dated="1986")
        after = self.data()["placement"]
        self.assertAlmostEqual(after["score"] - before["score"], promised, places=4)

    def test_the_promised_count_is_the_moments_that_actually_date(self):
        before = self.data()
        promised = before["placement"]["next_gain"]["count"]
        undated = [row for row in before["unknowns"] if row["kind"] == "moment"]
        self.assertEqual(promised, len(undated))
        self.write_period(dated="1986")
        after = self.data()
        dated_now = [event for rows in after["event_lineup"].values() for event in rows
                     if event.get("date") is not None]
        self.assertEqual(promised, len(dated_now))

    def test_the_margin_is_absent_rather_than_faked_when_nothing_is_left(self):
        self.write_period(dated="1986")
        self.assertIsNone(self.data()["placement"]["next_gain"])


class NoBirthNoBlockTests(VaultFixture):
    """§E.5 — no birthday, no denominator, no score; and a scoring problem
    never takes the timeline down."""

    def test_no_birth_landmark_means_no_placement_block(self):
        data = self.data(landmarks=False)
        self.assertNotIn("placement", data)
        self.assertNotIn("placement_band", data["counts"])

    def test_the_rest_of_the_timeline_is_unaffected(self):
        data = self.data(landmarks=False)
        self.assertTrue(data["unknowns"])
        self.assertTrue(data["periods"])
        self.assertIn("reading_room", data)

    def test_a_broken_landmark_store_leaves_the_timeline_standing(self):
        broken = self.root / "state" / "broken.json"
        broken.write_text("{ not json", encoding="utf-8")
        with mock.patch.object(tl, "LANDMARKS_STORE", broken):
            data = tl.timeline_data()
        self.assertNotIn("placement", data)
        self.assertTrue(data["unknowns"])

    def test_a_scoring_failure_is_swallowed_and_the_payload_survives(self):
        with mock.patch.object(tl, "placement_score", side_effect=RuntimeError("boom")):
            data = self.data()
        self.assertNotIn("placement", data)
        self.assertTrue(data["keystones"])
        self.assertIn("reading_room", data)

    def test_the_block_is_present_when_the_birthday_is(self):
        self.assertIn("placement", self.data())
        self.assertEqual(self.data()["counts"]["placement_band"],
                         self.data()["placement"]["band"])


# ---------------------------------------------------------------------------
# §C — `prior_span`, the ghost's source (contract §E.7).
# ---------------------------------------------------------------------------


class PriorSpanTests(unittest.TestCase):
    PERIODS = [{"slug": "childhood", "name": "Childhood", "date": edtf("1984/1990")}]

    def test_an_era_spanned_moment_carries_the_ghost(self):
        lineup = {"childhood": [{"title": "The bike", "date": edtf("1986-07-11")}]}
        self.assertEqual(xd.stamp_prior_spans(event_lineup=lineup, periods=self.PERIODS,
                                              birth_date=edtf("1981-07-11")), 1)
        self.assertEqual(lineup["childhood"][0]["prior_span"], [1984, 1990])

    def test_the_founders_shape_born_in_redlands(self):
        """The mark is the day the birthday gives; the ghost is the era it sits
        in, which is where the timeline could have put it before."""
        lineup = {"childhood": [{"title": "Born in Redlands", "source_short": "A1",
                                 "date": edtf("1981-07-11")}]}
        xd.stamp_prior_spans(event_lineup=lineup, periods=self.PERIODS,
                             birth_date=edtf("1981-07-11"))
        row = lineup["childhood"][0]
        self.assertEqual(chrono.to_edtf(row["date"]), "1981-07-11")
        self.assertEqual(row["prior_span"], [1984, 1990])

    def test_a_reconstruction_no_wider_than_the_moment_is_omitted(self):
        periods = [{"slug": "childhood", "name": "Childhood", "date": edtf("1986")}]
        lineup = {"childhood": [{"title": "The long stretch", "date": edtf("1984/1990")}]}
        self.assertEqual(xd.stamp_prior_spans(event_lineup=lineup, periods=periods,
                                              birth_date=edtf("1981-07-11")), 0)
        self.assertNotIn("prior_span", lineup["childhood"][0])

    def test_an_unplaced_dated_moment_ghosts_the_whole_life(self):
        unplaced = [{"title": "The dog", "date": edtf("1993-04-02")}]
        xd.stamp_prior_spans(event_lineup={}, unplaced_events=unplaced,
                             periods=self.PERIODS, birth_date=edtf("1981-07-11"))
        self.assertEqual(unplaced[0]["prior_span"][0], 1981)

    def test_with_no_birthday_an_unbounded_moment_has_no_ghost(self):
        unplaced = [{"title": "The dog", "date": edtf("1993-04-02")}]
        self.assertEqual(xd.stamp_prior_spans(event_lineup={}, unplaced_events=unplaced,
                                              periods=self.PERIODS), 0)
        self.assertNotIn("prior_span", unplaced[0])

    def test_an_undated_moment_never_gets_one(self):
        lineup = {"childhood": [{"title": "The bike", "date": None}]}
        self.assertEqual(xd.stamp_prior_spans(event_lineup=lineup, periods=self.PERIODS,
                                              birth_date=edtf("1981-07-11")), 0)
        self.assertNotIn("prior_span", lineup["childhood"][0])

    def test_a_stated_and_a_derived_moment_are_ghosted_alike(self):
        lineup = {"childhood": [
            {"title": "Stated", "date": edtf("1986-07-11")},
            {"title": "Derived", "date": edtf("1987-01-02"),
             "date_derived": {"rule": "containment"}},
        ]}
        xd.stamp_prior_spans(event_lineup=lineup, periods=self.PERIODS,
                             birth_date=edtf("1981-07-11"))
        self.assertEqual([row["prior_span"] for row in lineup["childhood"]],
                         [[1984, 1990], [1984, 1990]])

    def test_the_ghost_tightens_when_the_era_tightens(self):
        """The stateless trade, stated plainly: a ghost is today's honest
        reconstruction of "before", not a screenshot of what the page said."""
        lineup = {"childhood": [{"title": "The bike", "date": edtf("1986-07-11")}]}
        xd.stamp_prior_spans(event_lineup=lineup, periods=self.PERIODS,
                             birth_date=edtf("1981-07-11"))
        self.assertEqual(lineup["childhood"][0]["prior_span"], [1984, 1990])
        tighter = [{"slug": "childhood", "name": "Childhood", "date": edtf("1985/1987")}]
        xd.stamp_prior_spans(event_lineup=lineup, periods=tighter,
                             birth_date=edtf("1981-07-11"))
        self.assertEqual(lineup["childhood"][0]["prior_span"], [1985, 1987])

    def test_the_ghost_is_recomputed_not_accumulated(self):
        lineup = {"childhood": [{"title": "The bike", "date": edtf("1986-07-11")}]}
        xd.stamp_prior_spans(event_lineup=lineup, periods=self.PERIODS,
                             birth_date=edtf("1981-07-11"))
        undated_era = [{"slug": "childhood", "name": "Childhood", "date": None}]
        xd.stamp_prior_spans(event_lineup=lineup, periods=undated_era, birth_date=None)
        self.assertNotIn("prior_span", lineup["childhood"][0])

    def test_the_walk_leaves_no_scratch_key_behind(self):
        lineup = {"childhood": [{"title": "The bike", "date": edtf("1986-07-11")}]}
        xd.stamp_prior_spans(event_lineup=lineup, periods=self.PERIODS,
                             birth_date=edtf("1981-07-11"))
        self.assertEqual(set(lineup["childhood"][0]),
                         {"title", "date", "prior_span"})


class PriorSpanThroughTimelineDataTests(VaultFixture):
    """End to end: the pass stamps it, and the report says how many."""

    def setUp(self):
        super().setUp()
        self.write_period(dated="1984/1990")

    def test_the_dated_moments_carry_the_ghost_after_a_real_read(self):
        data = self.data()
        rows = [event for group in data["event_lineup"].values() for event in group]
        self.assertTrue(rows)
        for row in rows:
            self.assertIsNotNone(row.get("date"))
            # Containment gives them the era's own span, so there is nothing
            # wider left to ghost — the honest answer is no ghost at all.
            self.assertNotIn("prior_span", row)

    def test_a_day_pinned_moment_inside_the_era_does_carry_one(self):
        (self.root / "state" / "classifications" / "answers-a1.json").write_text(
            json.dumps({"source_path": "answers/A1.md", "events": [
                {"title": "The bike with no brakes",
                 "description": "The bike with no brakes.", "when_hint": "",
                 "anchor": None, "date": {"stated": "1986-07-11"}}]}), encoding="utf-8")
        data = self.data()
        rows = {row["title"]: row for group in data["event_lineup"].values() for row in group}
        self.assertEqual(rows["The bike with no brakes"]["prior_span"], [1984, 1990])
        self.assertGreaterEqual(data["cross_dating"]["prior_spans"], 1)
