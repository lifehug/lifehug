"""E-L2b — `residence_overlap`, and the move that mints nothing.

Controlling design: lifehug-platform `docs/design/timeline-eras.md` v2.1 §1
decision 2 (put to the owner on 2026-09-01 with the alternative spelled out
and answered: *no roles; one home at a time; overlaps fixed by editing
dates*), §3.2 "One home at a time", §7.2, §12 row 3, §14.1.

    Two stays overlapping by more than three months mint exactly one
    `residence_overlap` item, an overlap within a move mints nothing, and
    neither refuses a store.

Both halves matter and the second one is the easy one to get wrong: a person
leaving one home and settling in the next overlaps two leases for a few weeks,
and asking them about it every time would turn an ordinary move into a chore.

Synthetic data only; NEVER references ~/Workspace/dave.
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "system"))
sys.path.insert(0, str(ROOT / "tests"))

import episode_fold as ef  # noqa: E402
import landmark_projection as lp  # noqa: E402
import mirror_work as mw  # noqa: E402
import question_planner as qp  # noqa: E402
import temporal_projection as tp  # noqa: E402
import temporal_work_items as twi  # noqa: E402
import temporal_store as ts  # noqa: E402
import temporal_timeline as tt  # noqa: E402
import timeline_interaction as ti  # noqa: E402
from tempdirs import root_parent_tmp  # noqa: E402

NOW = "2026-09-01T12:00:00Z"

ROSTERS = {
    "place": {"type": "place", "entities": [
        {"name": "Cedarport", "slug": "cedarport", "aliases": []},
        {"name": "Millgate", "slug": "millgate", "aliases": []},
    ]},
}


def value(text: str, *, confidence: str = "certain") -> dict:
    grain = {4: "year", 7: "month", 10: "day"}[len(text)]
    return {"best": text, "earliest": text, "latest": text, "granularity": grain,
            "basis": "stated", "confidence": confidence}


def stay(label: str, start: str, end: str, *, confidence: str = "certain",
         end_confidence: str | None = None) -> tuple:
    return ("residences", {
        "label": label, "city": label,
        "span": {"start": value(start, confidence=confidence),
                 "end": value(end, confidence=end_confidence or confidence)},
    })


class OverlapCase(unittest.TestCase):
    ENTRIES: tuple = ()

    def setUp(self) -> None:
        self.root = root_parent_tmp(self, ROOT, prefix="el2b-ov-")
        (self.root / "state").mkdir(parents=True, exist_ok=True)
        (self.root / "sources").mkdir(parents=True, exist_ok=True)
        rosters = self.root / "state" / "entity_rosters"
        rosters.mkdir(parents=True, exist_ok=True)
        for kind, snapshot in ROSTERS.items():
            (rosters / f"{kind}.json").write_text(json.dumps(snapshot), "utf-8")
        for ordinal, (domain, entry) in enumerate(self.ENTRIES, start=1):
            lp.file_landmark_record(self.root, domain, entry, ordinal=ordinal, now=NOW)
        ts.rebuild_active_index(self.root)
        self.timeline = self.fold()

    def fold(self):
        return tt.derive_calculated_timeline(
            ts.fold_active_index(self.root),
            episode_records=ef.load_episode_records(self.root),
            landmark_entries=lp.load_landmark_sources(self.root),
            now=NOW,
        )

    def overlaps(self, timeline=None) -> list:
        rows = (timeline or self.timeline).work_items
        return [row for row in rows if row["kind"] == "residence_overlap"]


class TwoHomesAtOnce(OverlapCase):
    """§12 row 3, the minting half: an overlap beyond a move is one question."""

    ENTRIES = (
        stay("Cedarport", "1996-06", "2001-08"),
        stay("Millgate", "1998-03", "2004-11"),
    )

    def test_both_stays_are_stored_and_drawn(self):
        """*Never a refusal to store, never a silent loser.* Both bars exist."""
        stays = [row for row in self.timeline.nodes if row["event_kind"] == "residence"]
        self.assertEqual(len(stays), 2)

    def test_exactly_one_item_is_minted(self):
        self.assertEqual(len(self.overlaps()), 1)

    def test_the_question_names_both_stays_with_their_spans(self):
        item = self.overlaps()[0]
        self.assertEqual(
            item["prompt_intent"],
            "You've told me you were living in two places at once — Cedarport "
            "(June 1996–August 2001) and Millgate (March 1998–November 2004). "
            "Which of those dates needs fixing — or was one of them not really "
            "a home?",
        )

    def test_it_is_minted_on_the_earlier_stay(self):
        earlier = [row for row in self.timeline.nodes
                   if row["event_kind"] == "residence" and row["label"] == "Cedarport"]
        self.assertEqual(self.overlaps()[0]["event_ref"], earlier[0]["node_id"])

    def test_it_cites_both_stays_own_dated_claims(self):
        item = self.overlaps()[0]
        self.assertGreaterEqual(len(item["claim_refs"]), 4)

    def test_it_reaches_mirror_and_not_the_daily_queue(self):
        item = self.overlaps()[0]
        self.assertEqual(sorted(item["allowed_surfaces"]), ["mirror", "timeline"])
        self.assertIn("residence_overlap", mw.MIRROR_WORK_ITEM_KINDS)

    def test_the_kind_is_registered_everywhere_an_openable_item_needs(self):
        """ADR 0021: a kind whose answer nothing can route is the silent
        under-delivery this repo refuses. Five tables, one kind."""
        self.assertIn("residence_overlap", tp.WORK_ITEM_KINDS)
        self.assertIn("residence_overlap", ti.WORK_ITEM_KINDS)
        self.assertIn("residence_overlap", ti.WORK_ITEM_PROBES)
        self.assertIn("residence_overlap", qp.WORK_ITEM_PLACEMENT_GAIN)
        self.assertIn("residence_overlap", tt.SURFACES_BY_KIND)
        self.assertIn("residence_overlap", tt.WORK_ITEM_VALUE_DEFAULTS)
        self.assertIn("residence_overlap", tt.WORK_ITEM_PRECEDENCE)

    def test_a_date_correction_closes_it(self):
        """§5 rule 7 / §12 row 3's tail — the FIRST Play answer. A superseding
        claim, and the next generation simply does not mint the item; nothing
        is edited and nothing is deleted."""
        ids = lp.active_claim_ids_for_entry(
            self.root, domain="residences", entry_key="millgate")
        ts.supersede_claims(
            self.root, ids,
            reason="the Millgate stay actually began in 2002",
            scope="landmarks/residences",
        )
        lp.file_landmark_record(
            self.root, "residences",
            {"label": "Millgate", "city": "Millgate",
             "span": {"start": value("2002-01"), "end": value("2004-11")}},
            ordinal=99, now=NOW,
        )
        ts.rebuild_active_index(self.root)
        self.assertEqual(self.overlaps(self.fold()), [])

    def test_this_stay_was_not_a_home_closes_it(self):
        """§5 rule 6 — the SECOND Play answer. A `retract` correction on that
        stay's own promoted source: the episode leaves the fold, the evidence
        stays on disk, and the other stay is untouched."""
        lp.retire_entry(
            self.root, domain="residences", entry_key="millgate", slot=0,
            reason="that was never a home; I only stored things there",
        )
        ts.rebuild_active_index(self.root)
        later = self.fold()
        self.assertEqual(self.overlaps(later), [])
        stays = [row for row in later.nodes if row["event_kind"] == "residence"]
        self.assertEqual([row["label"] for row in stays], ["Cedarport"])

    def test_a_stored_reference_to_the_item_still_resolves(self):
        """`work_item_aliases` is published in the SAME generation as the items
        it describes, so a host holding a stored id never has to guess."""
        item = self.overlaps()[0]
        self.assertEqual(
            twi.resolve_work_item_id(item["work_item_id"],
                                     aliases=self.timeline.work_item_aliases),
            item["work_item_id"],
        )


class AMoveMintsNothing(OverlapCase):
    """The three-month tolerance: leaving one home and settling in the next."""

    ENTRIES = (
        stay("Cedarport", "1996-06", "2001-08"),
        stay("Millgate", "2001-06", "2005-01"),
    )

    def test_a_three_month_overlap_is_a_move(self):
        self.assertEqual(self.overlaps(), [])

    def test_the_tolerance_is_three_months(self):
        self.assertEqual(tt.RESIDENCE_MOVE_TOLERANCE_MONTHS, 3)


class AFourthMonthIsNotAMove(OverlapCase):
    """The boundary, from the other side — proved rather than asserted."""

    ENTRIES = (
        stay("Cedarport", "1996-06", "2001-09"),
        stay("Millgate", "2001-06", "2005-01"),
    )

    def test_a_four_month_overlap_is_asked(self):
        self.assertEqual(len(self.overlaps()), 1)


class AHedgedBoundMintsNothing(OverlapCase):
    """§3.2 / §6: *or where either touching bound is approximate*.

    A bracketed date is the person saying they are not sure, and §2.2 forbids
    demanding precision they already told us they do not have. Two stays whose
    touching bounds are hedged do not disagree; they are imprecise about one
    move.
    """

    ENTRIES = (
        stay("Cedarport", "1996-06", "2001-08", end_confidence="approximate"),
        stay("Millgate", "1999-03", "2005-01"),
    )

    def test_an_approximate_touching_bound_is_a_move(self):
        self.assertEqual(self.overlaps(), [])


class AnUndatedStayOverlapsNothing(OverlapCase):
    """M3: an undated stay has its own span question and no stretch to
    disagree with."""

    ENTRIES = (
        stay("Cedarport", "1996-06", "2001-08"),
        ("residences", {"label": "Millgate", "city": "Millgate"}),
    )

    def test_no_item_is_minted_about_a_stay_nobody_dated(self):
        self.assertEqual(self.overlaps(), [])


class TwoJobsAtOnceAreOrdinary(OverlapCase):
    """Owner decision 2 is about HOMES. Two jobs at once is a life, not a
    defect, and this rule never touches them (§3.2, §16)."""

    ENTRIES = (
        ("work", {"label": "Tidewheel Works", "what": "Tidewheel Works",
                  "span": {"start": value("2002-01"), "end": value("2008-01")}}),
        ("work", {"label": "Alder Foundry", "what": "Alder Foundry",
                  "span": {"start": value("2004-01"), "end": value("2009-01")}}),
    )

    def test_overlapping_tenures_mint_nothing(self):
        self.assertEqual(self.overlaps(), [])


if __name__ == "__main__":
    unittest.main()
