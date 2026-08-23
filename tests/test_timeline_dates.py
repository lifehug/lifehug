"""v195 / ADR 0024 — the timeline holds dates.

Events get titles and date records, periods/chapters/places get spans,
`chrono` is derived from the dates when they exist, and `bands` renders the
owner's Chapter -> Places -> Events hierarchy. Nothing here is allowed to
change what a vault with NO dates renders.

Synthetic data only; NEVER references ~/Workspace/dave.
"""

from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SYSTEM = ROOT / "system"
sys.path.insert(0, str(SYSTEM))


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


# `timeline` imports the canonical `chronology`; the test must hold the
# SAME module object, or every record it builds is a foreign class.
import chronology as chrono  # noqa: E402

tl = load("timeline")


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


def timeline_roots(root: Path) -> dict[str, Path]:
    state = root / "state"
    roots = {
        "CLASSIFICATIONS_DIR": state / "classifications",
        "CONNECTORS_STATE_DIR": state / "connectors",
        "DEFERRED_FILE": state / "timeline_deferred.json",
        "ENTITY_ROSTERS_DIR": state / "entity_rosters",
        "MANUAL_SOURCES_DIR": root / "sources" / "manual",
        "PLACEMENTS_FILE": state / "timeline_placements.json",
        "STATE_DIR": state,
        "WIKI_DIR": root / "wiki",
    }
    assert set(roots) == set(tl.VAULT_ROOT_NAMES), sorted(
        set(roots).symmetric_difference(tl.VAULT_ROOT_NAMES))
    return roots


class VaultFixture(unittest.TestCase):
    """A synthetic vault: two dated eras with an undated one between them, two
    places (one with a written span), one dated life chapter, and four events
    carrying every kind of date claim."""

    CHAPTERS = """# Life Chapters

## Chapter 1 — The Mesa Years

We moved into the little house and everything started there. It runs from
1984 to 1990. It ends when we left for the coast.

## Chapter 2 — After The Coast

Whatever came next.
"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.root = root
        (root / "wiki" / "periods").mkdir(parents=True)
        (root / "wiki" / "places").mkdir(parents=True)
        (root / "sources" / "manual").mkdir(parents=True)
        (root / "state" / "classifications").mkdir(parents=True)
        (root / "state" / "entity_rosters").mkdir()
        (root / "state" / "connectors").mkdir()

        (root / "wiki" / "periods" / "childhood.md").write_text(
            PAGE.format(title="Childhood", page_type="period", chrono=1,
                        extra="date: 1984/1990\n", sources=_sources(["A1", "A2"])),
            encoding="utf-8")
        (root / "wiki" / "periods" / "the-lost-years.md").write_text(
            PAGE.format(title="The Lost Years", page_type="period", chrono=2,
                        extra="", sources=_sources(["A3"])),
            encoding="utf-8")
        (root / "wiki" / "periods" / "my-30s.md").write_text(
            PAGE.format(title="My 30s", page_type="period", chrono=3,
                        extra="date: 2005/2015\n", sources=_sources(["A4"])),
            encoding="utf-8")
        (root / "wiki" / "places" / "mesa.md").write_text(
            PAGE.format(title="Mesa", page_type="place", chrono=0,
                        extra="date: 1984/1990\n", sources=_sources(["A1", "A2"])),
            encoding="utf-8")
        (root / "wiki" / "places" / "the-coast.md").write_text(
            PAGE.format(title="The Coast", page_type="place", chrono=0,
                        extra="", sources=_sources(["A4"])),
            encoding="utf-8")
        (root / "sources" / "manual" / "2026-01-01-life-chapters.md").write_text(
            self.CHAPTERS, encoding="utf-8")

        self.write_roster()
        self.write_classifications()
        self._orig = {name: getattr(tl, name) for name in tl.VAULT_ROOT_NAMES}
        for name, value in timeline_roots(root).items():
            setattr(tl, name, value)

    def tearDown(self):
        for name, value in self._orig.items():
            setattr(tl, name, value)
        self.tmp.cleanup()

    def write_roster(self, **overrides):
        entities = [
            {"name": "Childhood", "slug": "childhood", "chrono": 1,
             "page_eligible": True, "date": "1984/1990"},
            {"name": "The Lost Years", "slug": "the-lost-years", "chrono": 2,
             "page_eligible": True},
            {"name": "My 30s", "slug": "my-30s", "chrono": 3,
             "page_eligible": True, "date": "2005/2015"},
        ]
        for entity in entities:
            entity.update(overrides.get(entity["slug"], {}))
        (self.root / "state" / "entity_rosters" / "period.json").write_text(
            json.dumps({"version": 1, "type": "period", "entities": entities}),
            encoding="utf-8")

    def write_classifications(self, events=None):
        payloads = {
            "answers-a1.json": {
                "source_path": "answers/A1.md",
                "events": events if events is not None else [
                    {"title": "Grandpa's two-page letter",
                     "description": "Grandpa sent a two-page letter about the farm.",
                     "when_hint": "when I was about five", "anchor": None,
                     "date": {"age": "about five"}},
                    {"description": "We moved into the little house on Alder.",
                     "when_hint": "", "anchor": "the move",
                     "date": {"stated": "1984"}},
                ],
            },
            "answers-a2.json": {
                "source_path": "answers/A2.md",
                "events": [
                    {"title": "The bike with no brakes",
                     "description": "I rode a bike with no brakes down the hill.",
                     "when_hint": "sixth grade", "anchor": None, "date": None},
                ],
            },
            "answers-a4.json": {
                "source_path": "answers/A4.md",
                "events": [
                    {"title": "The coast house",
                     "description": "We bought the coast house.",
                     "when_hint": "", "anchor": None,
                     "date": {"stated": "2008"}},
                ],
            },
        }
        for name, payload in payloads.items():
            (self.root / "state" / "classifications" / name).write_text(
                json.dumps(payload), encoding="utf-8")


class EventTests(VaultFixture):
    def test_events_carry_the_classifiers_title(self):
        events = tl.load_events()
        titles = {event["title"] for event in events}
        self.assertIn("Grandpa's two-page letter", titles)

    def test_a_missing_title_falls_back_to_the_first_clause(self):
        title = tl.event_title({"description": "We moved into the little house on Alder."})
        self.assertEqual(title, "We moved into the little house on")
        self.assertEqual(len(title.split()), tl.EVENT_TITLE_MAX_WORDS)

    def test_event_title_is_the_one_fallback_and_never_invents(self):
        self.assertEqual(tl.event_title({}), "")
        self.assertEqual(tl.event_title({"title": "  Kept  "}), "Kept")

    def test_a_stated_claim_is_resolved_without_any_anchor(self):
        by_title = {tl.event_title(e): e for e in tl.load_events()}
        record = by_title["We moved into the little house on"]["date"]
        self.assertEqual(chrono.to_edtf(record), "1984")
        self.assertEqual(record.basis, "stated")

    def test_an_age_claim_needs_the_birthday_and_gets_it_from_timeline_data(self):
        by_title = {tl.event_title(e): e for e in tl.load_events()}
        self.assertIsNone(by_title["Grandpa's two-page letter"]["date"])
        data = tl.timeline_data(birth_date="1979")
        placed = [e for rows in data["event_lineup"].values() for e in rows]
        letter = next(e for e in placed if e["title"] == "Grandpa's two-page letter")
        self.assertEqual(letter["date"].basis, "age")
        self.assertEqual(letter["date"].best, "1984~")

    def test_an_undatable_event_keeps_its_when_hint_and_no_record(self):
        data = tl.timeline_data()
        placed = [e for rows in data["event_lineup"].values() for e in rows]
        bike = next(e for e in placed if e["title"] == "The bike with no brakes")
        self.assertIsNone(bike["date"])
        self.assertEqual(bike["when_hint"], "sixth grade")

    def test_dated_moments_sort_first_and_in_date_order(self):
        data = tl.timeline_data(birth_date="1979")
        rows = data["event_lineup"]["childhood"]
        dated = [chrono.year_of(e["date"]) for e in rows if e.get("date")]
        self.assertEqual(dated, sorted(dated))
        self.assertTrue(rows[0].get("date") is not None)


class PeriodDateTests(VaultFixture):
    def test_a_period_reads_its_span_from_the_roster(self):
        childhood = next(p for p in tl.load_periods() if p["slug"] == "childhood")
        self.assertEqual(chrono.to_edtf(childhood["date"]), "1984/1990")

    def test_approximate_dates_survives_as_the_derived_display_alias(self):
        childhood = next(p for p in tl.load_periods() if p["slug"] == "childhood")
        self.assertEqual(childhood["approximate_dates"], "1984–1990")

    def test_a_legacy_approximate_dates_string_still_produces_a_record(self):
        (self.root / "wiki" / "periods" / "childhood.md").write_text(
            PAGE.format(title="Childhood", page_type="period", chrono=1,
                        extra="", sources=_sources(["A1", "A2"])),
            encoding="utf-8")
        self.write_roster(childhood={"date": None, "approximate_dates": "2010–2013"})
        childhood = next(p for p in tl.load_periods() if p["slug"] == "childhood")
        self.assertEqual(chrono.to_edtf(childhood["date"]), "2010/2013")

    def test_an_undated_period_has_no_record_and_says_so(self):
        lost = next(p for p in tl.load_periods() if p["slug"] == "the-lost-years")
        self.assertIsNone(lost["date"])


class DeriveChronoTests(unittest.TestCase):
    @staticmethod
    def _period(slug, chrono_rank, date=None):
        return {"slug": slug, "name": slug.title(), "chrono": chrono_rank,
                "chrono_source": "roster" if chrono_rank is not None else None,
                "date": chrono.parse_edtf(date) if date else None, "sources": set()}

    def test_with_nothing_dated_the_order_is_byte_identical_to_v194(self):
        periods = [self._period("c", 3), self._period("a", 1),
                   self._period("b", 2), self._period("z", None)]
        before = sorted(periods, key=lambda p: (p["chrono"] is None, p["chrono"] or 0, p["slug"]))
        self.assertEqual([p["slug"] for p in tl.derive_chrono(periods)],
                         [p["slug"] for p in before])
        self.assertEqual([p["chrono"] for p in periods if p["slug"] == "a"], [1])

    def test_a_dated_period_re_anchors_the_order(self):
        periods = [self._period("late", 1, "2005"), self._period("early", 2, "1984")]
        ordered = tl.derive_chrono(periods)
        self.assertEqual([p["slug"] for p in ordered], ["early", "late"])
        self.assertEqual([p["chrono"] for p in ordered], [1, 2])
        self.assertEqual({p["chrono_source"] for p in ordered}, {"date"})

    def test_undated_periods_interpolate_between_their_dated_neighbours(self):
        periods = [self._period("first", 1, "1980"), self._period("middle", 2),
                   self._period("last", 3, "2000")]
        ordered = tl.derive_chrono(periods)
        self.assertEqual([p["slug"] for p in ordered], ["first", "middle", "last"])
        self.assertEqual(ordered[1]["chrono_source"], "roster")

    def test_the_ranks_are_dense_and_start_at_one(self):
        periods = [self._period("a", 7, "1980"), self._period("b", 9, "1990")]
        self.assertEqual([p["chrono"] for p in tl.derive_chrono(periods)], [1, 2])


class ChapterDateTests(VaultFixture):
    def test_a_chapter_span_is_read_from_the_exercises_own_words(self):
        first = tl.load_chapters()[0]
        self.assertEqual(chrono.to_edtf(first["date"]), "1984/1990")
        self.assertEqual(first["date"].basis, "stated")

    def test_a_chapter_with_no_years_is_honestly_undated(self):
        self.assertIsNone(tl.load_chapters()[1]["date"])

    def test_two_bare_years_give_an_inferred_interval_not_a_guessed_point(self):
        record = tl.chapter_date({"title": "x", "body": "It began in 1991 and 1996 ended it."})
        self.assertEqual(chrono.to_edtf(record), "1991/1996")
        self.assertEqual(record.confidence, "inferred")

    def test_one_bare_year_is_marked_conjectural(self):
        record = tl.chapter_date({"title": "x", "body": "Somewhere around 1991."})
        self.assertEqual(record.confidence, "conjectural")

    def test_align_chapters_prefers_date_containment(self):
        periods = tl.load_periods()
        aligned = tl.align_chapters(tl.load_chapters(), periods)
        self.assertEqual(aligned[0]["aligned_period"], "childhood")

    def test_name_match_remains_the_fallback_for_an_undated_chapter(self):
        periods = tl.load_periods()
        aligned = tl.align_chapters(
            [{"number": 1, "title": "The childhood era", "body": "", "date": None}], periods)
        self.assertEqual(aligned[0]["aligned_period"], "childhood")


class PlaceAndBandTests(VaultFixture):
    def test_a_place_page_span_is_read_from_its_frontmatter(self):
        mesa = next(e for e in tl.load_entities() if e["slug"] == "mesa")
        self.assertEqual(chrono.to_edtf(mesa["date"]), "1984/1990")

    def test_a_chapter_band_wins_wherever_it_covers(self):
        data = tl.timeline_data(birth_date="1979")
        kinds = {band["ref"]: band["kind"] for band in data["bands"]}
        self.assertEqual(kinds["1"], "chapter")
        self.assertNotIn("childhood", kinds)

    def test_a_period_band_fills_every_stretch_no_chapter_covers(self):
        data = tl.timeline_data(birth_date="1979")
        period_bands = {b["ref"] for b in data["bands"] if b["kind"] == "period"}
        self.assertIn("my-30s", period_bands)
        self.assertIn("the-lost-years", period_bands)

    def test_places_nest_inside_their_band_with_their_events(self):
        data = tl.timeline_data(birth_date="1979")
        chapter = next(b for b in data["bands"] if b["kind"] == "chapter")
        mesa = next(pl for pl in chapter["places"] if pl["slug"] == "mesa")
        self.assertEqual(chrono.to_edtf(mesa["date"]), "1984/1990")
        self.assertTrue(any(e["title"] == "Grandpa's two-page letter" for e in mesa["events"]))

    def test_an_event_matching_no_place_falls_to_the_bands_own_bucket(self):
        data = tl.timeline_data()
        band = next(b for b in data["bands"] if b["ref"] == "the-lost-years")
        self.assertEqual(band["places"], [])
        self.assertEqual(band["unplaced_events"], [])

    def test_places_by_chapter_and_by_period_are_views_over_bands(self):
        data = tl.timeline_data(birth_date="1979")
        self.assertEqual(data["places_by_chapter"]["1"],
                         next(b for b in data["bands"] if b["ref"] == "1")["places"])
        self.assertIn("my-30s", data["places_by_period"])

    def test_an_undated_place_takes_its_span_from_the_moments_that_happened_there(self):
        data = tl.timeline_data()
        band = next(b for b in data["bands"] if b["ref"] == "my-30s")
        coast = next(pl for pl in band["places"] if pl["slug"] == "the-coast")
        self.assertEqual(chrono.to_edtf(coast["date"]), "2008?")


class AnchorTests(VaultFixture):
    def test_the_anchor_index_is_the_life_history_calendar(self):
        data = tl.timeline_data(birth_date="1979")
        anchors = data["anchors"]
        self.assertEqual(anchors["birth"]["kind"], "birth")
        self.assertEqual(anchors["mesa"]["kind"], "residence")
        self.assertEqual(anchors["childhood"]["kind"], "period")

    def test_no_birthday_simply_means_no_birth_anchor(self):
        self.assertNotIn("birth", tl.timeline_data()["anchors"])


class PlacementDateTests(VaultFixture):
    def test_a_pin_can_carry_its_own_date_record(self):
        record = chrono.parse_edtf("1987~")
        tl.save_placement("key123456789", "answers/A3.md", "Something", "the-lost-years",
                          date=record)
        stored = tl.load_placements()["placements"][0]
        self.assertEqual(stored["date"]["best"], "1987~")

    def test_a_placement_without_a_date_is_byte_identical_to_v194(self):
        tl.save_placement("key123456789", "answers/A3.md", "Something", "the-lost-years")
        stored = tl.load_placements()["placements"][0]
        self.assertNotIn("date", stored)

    def test_the_pins_date_wins_on_the_placed_event(self):
        events = tl.load_events()
        target = next(e for e in events if e["title"] == "The bike with no brakes")
        key = tl.placement_key(target)
        tl.save_placement(key, target["source"], target["description"], "the-lost-years",
                          date=chrono.parse_edtf("1991"))
        data = tl.timeline_data()
        placed = next(e for e in data["event_lineup"]["the-lost-years"]
                      if e["title"] == "The bike with no brakes")
        self.assertEqual(chrono.to_edtf(placed["date"]), "1991")


if __name__ == "__main__":
    unittest.main()
