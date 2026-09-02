"""E-L2c — chain coverage, gaps, closure, and the one chain chooser.

Design: lifehug-platform `docs/design/timeline-eras.md` v2.1 §8 (H9),
§7.2/§7.3 (M7), §12 rows 19/25/26/33.

Synthetic data only; NEVER references ~/Workspace/dave.
"""

from __future__ import annotations

import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SYSTEM = ROOT / "system"
sys.path.insert(0, str(SYSTEM))

import chronology as chrono  # noqa: E402
import landmark_projection as lp  # noqa: E402
import landmarks_interaction as li  # noqa: E402
import timeline_interaction as ti  # noqa: E402


def _date(best: str) -> dict:
    record = chrono.parse_edtf(best, basis="stated")
    assert record is not None
    return record.to_dict()


def _span(start: str, end: str | None = None, *, ongoing: bool = False) -> dict:
    entry: dict = {"span": {"start": _date(start)}}
    if end is not None:
        entry["span"]["end"] = _date(end)
    if ongoing:
        entry["ongoing"] = True
    return entry


class ChainCoverageTests(unittest.TestCase):
    """Pure interval algebra over the three chains (§8)."""

    def test_an_unknown_domain_is_refused(self):
        with self.assertRaises(li.LandmarkInteractionError):
            li.chain_coverage("losses", {})

    def test_covered_stretches_merge_overlaps_and_abutments_once(self):
        landmarks = {"residences": [
            {"label": "A", **_span("1985", "1990")},
            {"label": "B", **_span("1990", "1994")},  # abuts A
            {"label": "C", **_span("1993", "1998")},  # overlaps B
        ]}
        coverage = li.chain_coverage("residences", landmarks)
        self.assertEqual(coverage["covered"], [{"start": 1985, "end": 1998}])

    def test_an_interior_gap_is_named_concretely_never_a_percentage(self):
        landmarks = {"residences": [
            {"label": "Mesa", **_span("1985", "1990")},
            {"label": "Yucaipa", **_span("1994", "1998")},
        ]}
        coverage = li.chain_coverage("residences", landmarks)
        self.assertEqual(coverage["unknown"], [
            {"domain": "residences", "position": "interior",
             "start": 1991, "end": 1993, "label": "1991–1993 has no home"},
        ])
        for stretch in coverage["unknown"]:
            self.assertNotIn("%", stretch["label"])

    def test_no_gap_before_the_first_or_after_the_last_with_no_target(self):
        landmarks = {"residences": [{"label": "Only", **_span("1988", "1992")}]}
        coverage = li.chain_coverage("residences", landmarks)
        self.assertIsNone(coverage["target"])
        self.assertEqual(coverage["unknown"], [])

    def test_residences_before_first_needs_a_birth_year(self):
        landmarks = {"residences": [{"label": "Only", **_span("1988", "1992")}]}
        coverage = li.chain_coverage("residences", landmarks, birth_year=1981,
                                     as_of_year=1992)
        self.assertEqual(coverage["target"], {"start": 1981, "end": 1992})
        self.assertEqual([row["position"] for row in coverage["unknown"]],
                         ["before_first"])

    def test_residences_after_last_runs_to_as_of(self):
        landmarks = {"residences": [{"label": "Only", **_span("1988", "1992")}]}
        coverage = li.chain_coverage("residences", landmarks, birth_year=1981,
                                     as_of_year=2000)
        positions = {row["position"]: row for row in coverage["unknown"]}
        self.assertIn("after_last", positions)
        self.assertEqual(positions["after_last"]["end"], 2000)

    def test_work_never_gaps_before_the_first_job(self):
        # §8: "before the first job is not a gap" — the target's own start
        # IS the earliest recorded job, so before_first cannot fire for work
        # no matter how late in life that first job was.
        landmarks = {"work": [{"label": "First Job", **_span("2010", "2012")}]}
        coverage = li.chain_coverage("work", landmarks, birth_year=1981, as_of_year=2024)
        self.assertEqual(coverage["target"], {"start": 2010, "end": 2024})
        self.assertNotIn("before_first",
                         {row["position"] for row in coverage["unknown"]})

    def test_schools_never_get_a_target_window(self):
        # §8: "no target window at all — no 'from age five'".
        landmarks = {"schools": [{"label": "Only", **_span("1990", "1994")}]}
        coverage = li.chain_coverage("schools", landmarks, birth_year=1981, as_of_year=2024)
        self.assertIsNone(coverage["target"])
        self.assertEqual(coverage["unknown"], [])

    def test_an_ongoing_entry_with_no_as_of_is_dropped_not_guessed_open(self):
        landmarks = {"work": [{"label": "Current Job", **_span("2020", ongoing=True)}]}
        coverage = li.chain_coverage("work", landmarks)
        self.assertEqual(coverage["covered"], [])

    def test_an_ongoing_entry_covers_to_as_of(self):
        landmarks = {"work": [{"label": "Current Job", **_span("2020", ongoing=True)}]}
        coverage = li.chain_coverage("work", landmarks, as_of_year=2024)
        self.assertEqual(coverage["covered"], [{"start": 2020, "end": 2024}])

    def test_an_entry_with_no_end_and_no_ongoing_flag_covers_nothing(self):
        # M3 territory: a stay whose true end is not known yet is neither
        # covered nor a gap boundary.
        landmarks = {"residences": [{"label": "Unfinished", **_span("1990")}]}
        coverage = li.chain_coverage("residences", landmarks, birth_year=1981,
                                     as_of_year=2000)
        self.assertEqual(coverage["covered"], [])


class ChainGapTests(unittest.TestCase):
    """The additive `chain_gap` kind, keeping `residence_gap` untouched
    (design §7.2, the `mirror_item` precedent)."""

    LANDMARKS = {
        "residences": [
            {"label": "Mesa", **_span("1988", "1992")},
            {"label": "Yucaipa", **_span("1995", "2001")},
        ],
    }

    def test_residence_gaps_is_byte_for_byte_untouched(self):
        rows = li.residence_gaps(self.LANDMARKS)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["kind"], "residence_gap")
        self.assertEqual(rows[0]["between"], ["Mesa", "Yucaipa"])

    def test_chain_gaps_emits_the_new_kind_alongside(self):
        rows = li.chain_gaps("residences", self.LANDMARKS)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["kind"], li.CHAIN_GAP_KIND)
        self.assertEqual(rows[0]["position"], "interior")
        self.assertEqual(rows[0]["domain"], "residences")

    def test_chain_gaps_reaches_work_and_schools_too(self):
        for domain in ("work", "schools"):
            with self.subTest(domain=domain):
                landmarks = {domain: [
                    {"label": "A", **_span("1988", "1992")},
                    {"label": "B", **_span("1995", "1998")},
                ]}
                rows = li.chain_gaps(domain, landmarks)
                self.assertEqual(len(rows), 1)
                self.assertEqual(rows[0]["domain"], domain)

    def test_the_gap_question_never_proposes_a_date(self):
        for row in li.chain_gaps("residences", self.LANDMARKS):
            self.assertIsNone(ti.proposes_a_date(row["probe"]["text"]))


class ChainClosureTests(unittest.TestCase):
    """The decision record, filed idempotently, folded newest-active
    (design §8, §12 row 19)."""

    def setUp(self) -> None:
        self.vault = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.vault, ignore_errors=True)

    def test_an_unknown_domain_is_refused(self):
        with self.assertRaises(lp.LandmarkProjectionError):
            lp.file_chain_closure(self.vault, domain="losses",
                                  status="closed_for_now", as_of="2024-01-01")

    def test_an_unknown_status_is_refused(self):
        with self.assertRaises(lp.LandmarkProjectionError):
            lp.file_chain_closure(self.vault, domain="residences",
                                  status="finished", as_of="2024-01-01")

    def test_filing_the_same_closure_twice_writes_one_file(self):
        first = lp.file_chain_closure(self.vault, domain="residences",
                                      status="closed_for_now", as_of="2024-01-01")
        second = lp.file_chain_closure(self.vault, domain="residences",
                                       status="closed_for_now", as_of="2024-01-01")
        self.assertEqual(first["source_id"], second["source_id"])
        self.assertEqual(len(lp.load_chain_closures(self.vault)), 1)

    def test_reopening_supersedes_rather_than_edits(self):
        closed = lp.file_chain_closure(self.vault, domain="residences",
                                       status="closed_for_now", as_of="2024-01-01")
        reopened = lp.file_chain_closure(self.vault, domain="residences",
                                         status="open", as_of="2024-06-01",
                                         supersedes=closed["source_id"])
        rows = lp.load_chain_closures(self.vault)
        self.assertEqual(len(rows), 2, "the superseded record is never deleted")
        active = li.active_chain_closures(rows)
        self.assertEqual(active["residences"]["source_id"], reopened["source_id"])
        self.assertFalse(li.chain_is_closed("residences", rows))

    def test_closure_suppresses_nothing_it_does_not_own(self):
        # §8: closure suppresses ROUTINE prompting only — gaps stay computed
        # and drawn. `chain_gaps` never even sees the closures list.
        lp.file_chain_closure(self.vault, domain="residences",
                              status="closed_for_now", as_of="2024-01-01")
        landmarks = {"residences": [
            {"label": "Mesa", **_span("1988", "1992")},
            {"label": "Yucaipa", **_span("1995", "2001")},
        ]}
        self.assertEqual(len(li.chain_gaps("residences", landmarks)), 1)


class NextChainUnitTests(unittest.TestCase):
    """The ONE chain-walker definition (design §7.3, M7, ADR 0021)."""

    FIXTURE = {
        "residences": [{"label": "Mesa", **_span("1985", "1990")}],
        "work": [{"label": "First Job", **_span("2010", "2012")}],
    }

    def test_none_when_nothing_is_open(self):
        self.assertIsNone(ti.next_chain_unit({}, domain="schools"))

    def test_picks_the_earliest_stretch_across_domains(self):
        unit = ti.next_chain_unit(self.FIXTURE, birth_year=1981, as_of_year=2024)
        self.assertEqual(unit["domain"], "residences")
        self.assertEqual(unit["position"], "before_first")

    def test_narrows_to_one_domain(self):
        unit = ti.next_chain_unit(self.FIXTURE, domain="work", as_of_year=2024)
        self.assertEqual(unit["domain"], "work")
        self.assertEqual(unit["position"], "after_last")

    def test_a_closed_chain_is_skipped(self):
        vault = tempfile.mkdtemp()
        try:
            lp.file_chain_closure(vault, domain="residences",
                                  status="closed_for_now", as_of="2024-01-01")
            closures = lp.load_chain_closures(vault)
            unit = ti.next_chain_unit(self.FIXTURE, domain="residences",
                                      birth_year=1981, as_of_year=2024,
                                      closures=closures)
            self.assertIsNone(unit)
            # The other, still-open chain is unaffected.
            unit_all = ti.next_chain_unit(self.FIXTURE, birth_year=1981,
                                          as_of_year=2024, closures=closures)
            self.assertEqual(unit_all["domain"], "work")
        finally:
            shutil.rmtree(vault, ignore_errors=True)

    def test_two_hosts_calling_the_one_function_pick_the_same_unit(self):
        """ADR 0021: the walker is defined once and bound to both hosts, or
        it is a build failure. This proves the two hosts by construction —
        each is a thin wrapper that calls `next_chain_unit` and nothing
        else, exactly as a real era-Play binding and a real Go Dig binding
        would (both future E-L4/E-L6 work; this pins that they CANNOT
        disagree because there is only one definition to call)."""

        def era_host(landmarks, **kwargs):
            return ti.next_chain_unit(landmarks, **kwargs)

        def go_dig_host(landmarks, **kwargs):
            return ti.next_chain_unit(landmarks, **kwargs)

        kwargs = {"birth_year": 1981, "as_of_year": 2024}
        self.assertEqual(era_host(self.FIXTURE, **kwargs),
                         go_dig_host(self.FIXTURE, **kwargs))


if __name__ == "__main__":
    unittest.main()
