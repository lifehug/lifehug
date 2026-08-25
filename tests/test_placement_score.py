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
