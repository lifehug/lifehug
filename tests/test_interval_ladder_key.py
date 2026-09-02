"""E-L2b — the INTERVAL-AWARE ladder key (design §3.2, audit finding H1).

Controlling design: lifehug-platform `docs/design/timeline-eras.md` v2.1 §0.1
H1, §0.2 M11, §3.2 ("The ladder key", "Undated stays"), §12 rows 1, 2, 30 and
§14.1. The finding, in the design's own words:

    `landmark_entry_key` keys purely on the case-folded label with no date, and
    `merge_landmark_entry` reconciles the two spans into ONE entry with the
    loser's bounds as alternates. So two stays in the same city collapse at the
    LADDER, before any claim exists.

That is what the first class below asserts against, and it is exactly what the
projection did on this branch's parent: two Cedarport stays produced ONE entry
whose `span` was 1988–1990 and whose `span_alternates` held 1996 and 1999 — a
second stay that no longer existed anywhere in the vault.

Everything runs through the REAL path: the recorder's own writer
(`landmark_projection.file_landmark_record`, which is what `landmark-record`
and the hosts' `landmark_invocations` call), the promoted source, the receipt,
the active index and the fold. Synthetic data only; NEVER references
~/Workspace/dave.
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "system"))
sys.path.insert(0, str(ROOT / "tests"))

import chronology as chrono  # noqa: E402
import episode_fold as ef  # noqa: E402
import landmark_projection as lp  # noqa: E402
import landmarks_interaction as li  # noqa: E402
import temporal_store as ts  # noqa: E402
import temporal_timeline as tt  # noqa: E402
from tempdirs import root_parent_tmp  # noqa: E402

NOW = "2026-09-01T12:00:00Z"

ROSTERS = {
    "place": {"type": "place", "entities": [
        {"name": "Cedarport", "slug": "cedarport", "aliases": ["the Cedarport house"]},
        {"name": "Millgate", "slug": "millgate", "aliases": []},
    ]},
    "object": {"type": "object", "entities": [
        {"name": "Tidewheel Works", "slug": "tidewheel-works", "aliases": ["Tidewheel"]},
    ]},
}


def value(text: str, *, confidence: str = "certain") -> dict:
    grain = {4: "year", 7: "month", 10: "day"}[len(text)]
    return {"best": text, "earliest": text, "latest": text, "granularity": grain,
            "basis": "stated", "confidence": confidence}


def span(start: str | None, end: str | None = None, **kwargs) -> dict:
    out: dict = {}
    if start:
        out["start"] = value(start, **kwargs)
    if end:
        out["end"] = value(end, **kwargs)
    return out


class LadderCase(unittest.TestCase):
    """One synthetic vault, filed through the recorder, drawn on demand."""

    ENTRIES: tuple = ()

    def setUp(self) -> None:
        self.root = root_parent_tmp(self, ROOT, prefix="el2b-")
        (self.root / "state").mkdir(parents=True, exist_ok=True)
        (self.root / "sources").mkdir(parents=True, exist_ok=True)
        rosters = self.root / "state" / "entity_rosters"
        rosters.mkdir(parents=True, exist_ok=True)
        for kind, snapshot in ROSTERS.items():
            (rosters / f"{kind}.json").write_text(json.dumps(snapshot), "utf-8")
        for ordinal, (domain, entry) in enumerate(self.ENTRIES, start=1):
            lp.file_landmark_record(self.root, domain, entry, ordinal=ordinal, now=NOW)
        ts.rebuild_active_index(self.root)

    # -- helpers ---------------------------------------------------------

    def drawn(self) -> dict:
        return lp.redraw(self.root)

    def entries(self, domain: str) -> list:
        return list((self.drawn().get("domains") or {}).get(domain) or [])

    def bounds(self, entry: dict) -> tuple:
        return (
            ((entry.get("span") or {}).get("start") or {}).get("best"),
            ((entry.get("span") or {}).get("end") or {}).get("best"),
        )

    def timeline(self):
        return tt.derive_calculated_timeline(
            ts.fold_active_index(self.root),
            episode_records=ef.load_episode_records(self.root),
            landmark_entries=lp.load_landmark_sources(self.root),
            now=NOW,
        )


class TwoStaysAtOneAddress(LadderCase):
    """§12 row 1 — same home, two non-contiguous stays; and row 2's twin for
    an employer. Two entries, two episodes, one entity."""

    ENTRIES = (
        ("residences", {"label": "Cedarport", "city": "Cedarport",
                        "span": span("1988", "1990")}),
        ("residences", {"label": "Cedarport", "city": "Cedarport",
                        "span": span("1996", "1999")}),
        ("work", {"label": "Tidewheel Works", "what": "Tidewheel Works",
                  "span": span("2002", "2004")}),
        ("work", {"label": "Tidewheel Works", "what": "Tidewheel Works",
                  "span": span("2010", "2013")}),
    )

    def test_two_stays_at_one_city_are_two_entries(self):
        rows = self.entries("residences")
        self.assertEqual(len(rows), 2)
        self.assertEqual([self.bounds(row) for row in rows],
                         [("1988", "1990"), ("1996", "1999")])

    def test_two_tenures_at_one_employer_are_two_entries(self):
        rows = self.entries("work")
        self.assertEqual(len(rows), 2)
        self.assertEqual([self.bounds(row) for row in rows],
                         [("2002", "2004"), ("2010", "2013")])

    def test_the_second_stay_is_not_the_first_ones_alternate(self):
        """H1's exact signature. Before this key, the loser's bounds were
        filed as `span_alternates` on the survivor and the second stay ceased
        to exist as an entry anywhere."""
        for domain in ("residences", "work"):
            for row in self.entries(domain):
                self.assertNotIn("span_alternates", row, domain)

    def test_the_identity_half_of_the_key_is_untouched(self):
        """The frontmatter key on every promoted source still reads the
        case-folded identity — no source is rewritten and no digest moves."""
        keys = sorted({row["entry_key"] for row in lp.load_landmark_sources(self.root)})
        self.assertEqual(keys, ["cedarport", "tidewheel works"])

    def test_both_stays_reach_their_own_episode(self):
        stays = [row for row in self.timeline().nodes if row["event_kind"] == "residence"]
        self.assertEqual(len(stays), 2)
        self.assertEqual(
            sorted(chrono.display_date(row["best_temporal_value"], with_basis=False)
                   for row in stays),
            ["1988–1990", "1996–1999"],
        )

    def test_the_drawing_is_idempotent(self):
        """§12 row 30 for the landmark projection: redraw twice, byte-identical."""
        first = json.dumps(self.drawn(), sort_keys=True, default=str)
        second = json.dumps(self.drawn(), sort_keys=True, default=str)
        self.assertEqual(first, second)

    def test_deleting_derived_state_and_rebuilding_changes_nothing(self):
        """§3.5's certification, for the half this PR moves: nothing under
        `sources/` is touched, the index is rebuilt from the receipts, and the
        split is derived again rather than remembered."""
        before = json.dumps(self.drawn(), sort_keys=True, default=str)
        index = self.root / "state" / "temporal_claims" / "active_index.json"
        if index.exists():
            index.unlink()
        ts.rebuild_active_index(self.root)
        self.assertEqual(json.dumps(self.drawn(), sort_keys=True, default=str), before)


class TheIncrementalFillStillWorks(LadderCase):
    """§3.2 — the city today, the span next week, ONE entry.

    The rule only ever SPLITS records that are provably disjoint; a record
    that states no start joins the entry that is already there.
    """

    ENTRIES = (
        ("residences", {"label": "Millgate", "city": "Millgate"}),
        ("residences", {"label": "Millgate", "city": "Millgate",
                        "span": span("2004-05", "2009-11")}),
        ("residences", {"label": "Millgate", "address": "12 Elm Row"}),
    )

    def test_three_tellings_of_one_stay_are_one_entry(self):
        rows = self.entries("residences")
        self.assertEqual(len(rows), 1)
        self.assertEqual(self.bounds(rows[0]), ("2004-05", "2009-11"))
        self.assertEqual(rows[0].get("address"), "12 Elm Row")

    def test_the_undated_stay_and_its_dated_telling_are_one_episode(self):
        stays = [row for row in self.timeline().nodes if row["event_kind"] == "residence"]
        self.assertEqual(len(stays), 1)

    def test_the_re_key_publishes_the_old_id(self):
        """M3's alias: the id the undated telling would have carried alone
        still resolves, derived rather than remembered."""
        self.assertTrue(self.timeline().node_aliases)


class ARefilledSpanIsStillOneStay(LadderCase):
    """Two tellings of ONE stay whose stated stretches differ but touch."""

    ENTRIES = (
        ("residences", {"label": "Millgate", "city": "Millgate",
                        "span": span("1994", "1996")}),
        ("residences", {"label": "Millgate", "city": "Millgate",
                        "span": span("1995", "1997")}),
    )

    def test_overlapping_tellings_reconcile_into_one_entry(self):
        rows = self.entries("residences")
        self.assertEqual(len(rows), 1)


class ASetDomainKeepsTodaysKey(LadderCase):
    """`set` and `singleton` domains are untouched — a second telling about
    one child is never a second child (§3.2)."""

    ENTRIES = (
        ("children", {"who": "Rosa", "date": value("2010-12-21")}),
        ("children", {"who": "Rosa", "date": value("2010-12-21")}),
        ("children", {"who": "Milo", "date": value("2013-05-10")}),
    )

    def test_two_tellings_of_one_child_stay_one_entry(self):
        rows = self.entries("children")
        self.assertEqual(len(rows), 2)
        self.assertEqual(sorted(row.get("who") for row in rows), ["Milo", "Rosa"])


class ThePredicateItself(unittest.TestCase):
    """`landmarks_interaction.same_landmark_stay`, at the boundary."""

    def setUp(self) -> None:
        self.row = li.domain_row("residences")
        self.children = li.domain_row("children")

    def stay(self, start=None, end=None, **kwargs):
        return {"label": "Cedarport", "span": span(start, end, **kwargs)} if start or end \
            else {"label": "Cedarport"}

    def test_an_undated_record_is_always_the_same_entry(self):
        self.assertTrue(li.same_landmark_stay(
            self.stay(), self.stay("1996", "1999"), self.row))
        self.assertTrue(li.same_landmark_stay(
            self.stay("1996", "1999"), self.stay(), self.row))

    def test_intersecting_stretches_are_one_entry(self):
        self.assertTrue(li.same_landmark_stay(
            self.stay("1996", "2001"), self.stay("1999", "2004"), self.row))

    def test_abutting_within_a_year_is_one_entry(self):
        self.assertTrue(li.same_landmark_stay(
            self.stay("1996", "1999"), self.stay("2000", "2003"), self.row))

    def test_disjoint_by_more_than_a_year_is_a_second_stay(self):
        self.assertFalse(li.same_landmark_stay(
            self.stay("1988", "1990"), self.stay("1996", "1999"), self.row))

    def test_the_boundary_is_twelve_months(self):
        self.assertEqual(li.SEQUENCE_ENTRY_ABUT_MONTHS, 12)
        # 1990 and 1992 are one whole year apart; 1990 and 1993 are two.
        self.assertTrue(li.same_landmark_stay(
            self.stay("1990"), self.stay("1992"), self.row))
        self.assertFalse(li.same_landmark_stay(
            self.stay("1990"), self.stay("1993"), self.row))

    def test_a_set_domain_is_never_split(self):
        self.assertTrue(li.same_landmark_stay(
            {"who": "Rosa", "date": value("2010-12-21")},
            {"who": "Rosa", "date": value("2013-05-10")},
            self.children,
        ))

    def test_an_unclosed_stay_is_bounded_by_its_own_start(self):
        """The one place this reading differs from `span_from_claims`: an
        absent end is what the person did not say, not a claim over every
        year since. Letting it reach forward would merge a 1988 stay and a
        1996 one into a single eleven-year fiction."""
        interval = li.entry_stay_interval(self.stay("1988"))
        self.assertEqual((interval["earliest"], interval["latest"]), ("1988", "1988"))
        self.assertFalse(li.same_landmark_stay(
            self.stay("1988"), self.stay("1996", "1999"), self.row))


class TheIntervalArithmetic(unittest.TestCase):
    """`chronology.overlap_months` / `gap_months` — one arithmetic, two reads."""

    def record(self, earliest, latest=None):
        return {"best": earliest, "earliest": earliest, "latest": latest or earliest,
                "granularity": "year", "basis": "stated", "confidence": "certain"}

    def test_a_year_fills_to_its_own_edges(self):
        self.assertEqual(chrono.overlap_months(self.record("1988"),
                                               self.record("1988", "1990")), 12)

    def test_touching_years_share_nothing_and_gap_by_nothing(self):
        self.assertEqual(chrono.overlap_months(self.record("1990"), self.record("1991")), 0)
        self.assertEqual(chrono.gap_months(self.record("1990"), self.record("1991")), 0)

    def test_a_gap_is_counted_in_whole_months(self):
        self.assertEqual(chrono.gap_months(self.record("1990"), self.record("1992")), 12)
        self.assertIsNone(chrono.gap_months(self.record("1990", "1996"),
                                            self.record("1992")))

    def test_an_open_end_overlaps_rather_than_gaps(self):
        open_ended = {"best": "2022-05/..", "earliest": "2022-05", "latest": None,
                      "granularity": "range", "basis": "stated", "confidence": "certain"}
        self.assertIsNone(chrono.gap_months(open_ended, self.record("2024")))
        self.assertEqual(chrono.overlap_months(open_ended, self.record("2024")), 12)

    def test_a_three_month_overlap_reads_as_three(self):
        left = {"best": "1996-06/2001-08", "earliest": "1996-06", "latest": "2001-08",
                "granularity": "range", "basis": "stated", "confidence": "certain"}
        right = {"best": "2001-06/2005-01", "earliest": "2001-06", "latest": "2005-01",
                 "granularity": "range", "basis": "stated", "confidence": "certain"}
        self.assertEqual(chrono.overlap_months(left, right), 3)


if __name__ == "__main__":
    unittest.main()
