"""E-L2d — the `frame_display` decision, and the tiling that only PROPOSES it.

Controlling design: lifehug-platform `docs/design/timeline-eras.md` v2.1 §0.1
H8, §1 decision 1, §9.1, §12 row 36, §14.5, §15.1; `docs/design/eras.md` A1 as
amended 2026-09-01.

    Eras DO replace a frame's row — but per frame, on the person's one-tap
    confirmation of a system proposal, stored as a display decision,
    reversible, with the frame kept on the ruler … There is no coverage
    percentage (the system proposes when eras tile the frame; the person
    decides). (H8)

Every test here was run against **v277 (`6356745`)** first and seen failing —
`AttributeError: module 'era_memberships' has no attribute
'file_frame_display'` and `module 'cross_dating' has no attribute
'frame_tiling'`.

Synthetic data only; NEVER references ~/Workspace/dave.
"""

from __future__ import annotations

import json
import os
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "system"))
sys.path.insert(0, str(ROOT / "tests"))

import chronology as chrono  # noqa: E402
import cross_dating as cd  # noqa: E402
import era_identity as ei  # noqa: E402
import era_memberships as era  # noqa: E402
import era_record as er  # noqa: E402
import landmark_projection as lp  # noqa: E402
import lifehug  # noqa: E402
import temporal_projection as tp  # noqa: E402
import temporal_publication as pub  # noqa: E402
import temporal_store as ts  # noqa: E402
import temporal_timeline as tt  # noqa: E402
from tempdirs import root_parent_tmp  # noqa: E402

NOW = "2026-09-01T12:00:00Z"
BIRTH_DAY = "1981-07-11"

#: My 20s for a 1981-07-11 birthday: [2001-07-11, 2011-07-11).
TWENTIES = "age:self:20s"


def value(text: str) -> dict:
    grain = {4: "year", 7: "month", 10: "day"}[len(text)]
    return {"best": text, "earliest": text, "latest": text, "granularity": grain,
            "basis": "stated", "confidence": "certain"}


def span(start: str, end: str) -> dict:
    return {"start": chrono.parse_edtf(start).to_dict(),
            "end": chrono.parse_edtf(end).to_dict()}


def era_payload(label: str, started: str, ended: str | None,
                *, era_kind: str = "stretch") -> dict:
    claims = [
        {"claim_type": "date", "subject_mention": "me",
         "event_kind": "period_started", "event_mention": label,
         "temporal_value": started,
         "evidence": f"{label} started in {started}"},
    ]
    if ended is not None:
        claims.append(
            {"claim_type": "date", "subject_mention": "me",
             "event_kind": "period_ended", "event_mention": label,
             "temporal_value": ended,
             "evidence": f"{label} ended in {ended}"},
        )
    return {
        "label": label,
        "era_kind": era_kind,
        "session_ref": f"s-{label}",
        "turn_ref": f"t-{label}",
        "message_text": f"I think of {started} onward as {label}.",
        "claims": claims,
    }


# ---------------------------------------------------------------------------
# The arithmetic (§9.1) — half-open, grain-honest, edge-tolerant
# ---------------------------------------------------------------------------


class TheTilingArithmetic(unittest.TestCase):
    """One definition (`cross_dating.frame_tiling`), stated in
    `FRAME_TILING_RULE_TEXT` and applied by nothing else."""

    FRAME = span("2001-07-11", "2011-07-11")

    def tiling(self, *eras):
        return cd.frame_tiling(
            self.FRAME, [chrono.parse_edtf(text).to_dict() for text in eras]
        )

    def test_one_era_covering_the_whole_frame_tiles_it(self):
        out = self.tiling("2001/2011")
        self.assertTrue(out["tiled"])
        self.assertEqual(out["leftover"], [])

    def test_two_eras_abut_at_year_grain_rather_than_leaving_a_hole(self):
        """Grain-honest: a year-grain end (…-12-31) and a year-grain start of
        the next year are ONE covered stretch, not two with a day between."""
        out = self.tiling("2001/2005", "2006/2011")
        self.assertTrue(out["tiled"])
        self.assertEqual(out["leftover"], [])
        self.assertEqual(len(out["covered"]), 1)

    def test_an_interior_hole_is_never_tolerated(self):
        out = self.tiling("2001/2004", "2006/2011")
        self.assertFalse(out["tiled"])
        self.assertEqual(out["leftover"],
                         [{"start": "2005-01-01", "end": "2006-01-01"}])

    def test_an_edge_sliver_shorter_than_the_bounds_grain_still_tiles(self):
        """*"2002 to 2011"* at year grain about a frame that opens on a July
        birthday did not deliberately leave the first half of 2001 out."""
        out = self.tiling("2002/2011")
        self.assertTrue(out["tiled"])
        self.assertEqual(out["leftover"],
                         [{"start": "2001-07-11", "end": "2002-01-01"}])

    def test_an_edge_gap_longer_than_a_grain_unit_is_a_hole(self):
        out = self.tiling("2004/2011")
        self.assertFalse(out["tiled"])

    def test_a_day_grain_bound_gets_a_day_grain_tolerance(self):
        """The tolerance is the person's own stated grain, not a constant: a
        day-grain answer that leaves two months out left two months out."""
        out = self.tiling("2001-09-01/2011")
        self.assertFalse(out["tiled"])

    def test_no_eras_at_all_never_tiles_and_the_whole_frame_is_leftover(self):
        out = self.tiling()
        self.assertFalse(out["tiled"])
        self.assertEqual(out["leftover"],
                         [{"start": "2001-07-11", "end": "2011-07-11"}])

    def test_overlapping_eras_are_one_covered_stretch(self):
        out = self.tiling("2001/2006", "2004/2011")
        self.assertTrue(out["tiled"])
        self.assertEqual(len(out["covered"]), 1)

    def test_an_era_outside_the_frame_contributes_nothing(self):
        out = self.tiling("1990/1995")
        self.assertFalse(out["tiled"])
        self.assertEqual(out["covered"], [])

    def test_the_leftover_is_geometric_truth_even_when_it_tiles(self):
        """The tolerance decides whether to PROPOSE; it never edits the years
        the leftover row is about (§9.1: the leftover renders as the frame's
        own row)."""
        out = self.tiling("2002/2011")
        self.assertTrue(out["tiled"])
        self.assertTrue(out["leftover"])

    def test_a_frame_with_no_definition_span_tiles_nothing(self):
        self.assertEqual(cd.frame_tiling(None, []),
                         {"tiled": False, "leftover": [], "covered": []})

    def test_the_rule_is_written_down_once(self):
        self.assertIn("half-open", cd.FRAME_TILING_RULE_TEXT)
        self.assertIn("NOTHING is auto-applied", cd.FRAME_TILING_RULE_TEXT)


# ---------------------------------------------------------------------------
# The record (§9.1, §15.1)
# ---------------------------------------------------------------------------


class TheDecisionRecord(unittest.TestCase):

    def setUp(self) -> None:
        self.root = root_parent_tmp(self, ROOT, prefix="el2d-fd-")
        (self.root / "state").mkdir(parents=True, exist_ok=True)
        (self.root / "sources").mkdir(parents=True, exist_ok=True)

    def file(self, mode="eras", **kwargs):
        return era.file_frame_display(
            self.root, frame_id=TWENTIES, mode=mode, frame_label="My 20s", **kwargs
        )

    def test_it_lands_beside_the_member_display_decisions(self):
        row = self.file()
        self.assertTrue(row["relative_path"].startswith(era.DISPLAY_SOURCES_DIR))
        self.assertEqual(row["frame_id"], TWENTIES)
        self.assertEqual(row["mode"], "eras")
        self.assertTrue(row["decision_id"].startswith(f"{era.FRAME_DECISION_ID_PREFIX}:"))

    def test_filing_the_same_decision_twice_writes_one_file(self):
        first = self.file()
        again = self.file()
        self.assertEqual(first["decision_id"], again["decision_id"])
        self.assertEqual(len(era.load_frame_displays(self.root)), 1)

    def test_the_identity_is_the_digest_of_what_it_says(self):
        row = self.file()
        self.assertEqual(
            row["decision_id"],
            era.frame_decision_id_of(era.frame_display_digest(
                frame_id=TWENTIES, mode="eras", supersedes=None,
            )),
        )

    def test_a_mode_nobody_declared_is_refused(self):
        with self.assertRaises(era.EraReceiptError) as caught:
            self.file(mode="graduated")
        self.assertEqual(caught.exception.code, "frame_display_mode_unknown")

    def test_a_decision_with_no_frame_is_refused(self):
        with self.assertRaises(era.EraReceiptError) as caught:
            era.file_frame_display(self.root, frame_id="  ", mode="eras")
        self.assertEqual(caught.exception.code, "frame_display_frame_required")

    def test_an_unsafe_supersedes_target_is_refused(self):
        with self.assertRaises(era.EraReceiptError) as caught:
            self.file(supersedes="../../etc/passwd")
        self.assertEqual(caught.exception.code, "frame_display_target_unsafe")

    def test_undo_supersedes_rather_than_deletes(self):
        first = self.file()
        second = self.file(mode="frame", supersedes=first["decision_id"])
        rows = {row["decision_id"]: row for row in era.load_frame_displays(self.root)}
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[first["decision_id"]]["status"], "superseded")
        self.assertEqual(rows[second["decision_id"]]["status"], "active")
        self.assertEqual(era.frame_display_modes(era.active_frame_displays(self.root)),
                         {TWENTIES: "frame"})

    def test_the_two_display_families_do_not_read_each_other(self):
        """A member's `era_display` and a frame's `frame_display` share a
        directory and nothing else: each reader sees only its own type."""
        self.file()
        era.file_era_display(self.root, member_node_id="node:a",
                             primary_container_id="era:b")
        self.assertEqual([row["frame_id"] for row in era.active_frame_displays(self.root)],
                         [TWENTIES])
        self.assertEqual([row["member_node_id"] for row in era.active_era_displays(self.root)],
                         ["node:a"])

    def test_it_is_owner_only_and_immutable_like_every_other_receipt(self):
        row = self.file()
        text = (self.root / row["relative_path"]).read_text("utf-8")
        self.assertIn('visibility: "owner_only"', text)
        self.assertIn("immutable: true", text.lower())


# ---------------------------------------------------------------------------
# §12 row 36, end to end
# ---------------------------------------------------------------------------


class RowThirtySix(unittest.TestCase):
    """*A frame's eras tile it; the person confirms; then undoes* → proposal
    flag in the projection → `frame_display: eras` → a superseding `frame`
    decision · frame id unchanged · presentation only; chronology untouched ·
    no-op on replay · the leftover row carries the frame's name."""

    def setUp(self) -> None:
        self.root = root_parent_tmp(self, ROOT, prefix="el2d-r36-")
        (self.root / "state").mkdir(parents=True, exist_ok=True)
        (self.root / "sources").mkdir(parents=True, exist_ok=True)
        lp.file_landmark_record(
            self.root, "birth", {"label": "born", "date": value(BIRTH_DAY)},
            ordinal=1, now=NOW,
        )
        # Two dated stretch eras that tile My 20s between them, plus one
        # thread and one undated era that must NOT count (§9.1, A9).
        er.record_era(self.root, era_payload("College Years", "2001", "2005"), now=NOW)
        er.record_era(self.root, era_payload("The Mill Years", "2006", "2011"), now=NOW)
        er.record_era(self.root, era_payload("Fatherhood", "2001", None,
                                             era_kind="thread"), now=NOW)
        ts.rebuild_active_index(self.root)
        self.publish()

    def publish(self) -> dict:
        os.environ[tp.PROJECTION_SCHEMA_FLAG] = "3"
        self.addCleanup(os.environ.pop, tp.PROJECTION_SCHEMA_FLAG, None)
        pub.publish(self.root, roster_snapshot=(), birth_date=BIRTH_DAY, now=NOW)
        return pub.read_projection(self.root) or {}

    def block(self, payload: dict | None = None) -> dict:
        rows = (payload or self.publish())["frame_display"]
        return next(row for row in rows if row["frame_id"] == TWENTIES)

    def chronology(self, payload: dict) -> list:
        """Everything about WHEN — the half a display decision may not move."""
        return [
            {key: row.get(key) for key in
             ("node_id", "best_temporal_value", "possible_temporal_value",
              "definition_span", "observed_envelope", "value_shape")}
            for row in payload["nodes"]
        ]

    # -- the three steps -------------------------------------------------

    def test_the_proposal_is_pending_before_anybody_decides(self):
        row = self.block()
        self.assertEqual(row["frame_display"], "frame")
        self.assertTrue(row["proposal_pending"])
        self.assertIsNone(row["decision_id"])

    def test_a_frame_its_eras_do_not_tile_proposes_nothing(self):
        row = next(r for r in self.publish()["frame_display"]
                   if r["frame_id"] == "age:self:30s")
        self.assertFalse(row["proposal_pending"])
        self.assertTrue(row["leftover"])

    def test_confirming_files_the_decision_and_the_proposal_stops(self):
        decision = era.file_frame_display(
            self.root, frame_id=TWENTIES, mode="eras", frame_label="My 20s",
        )
        row = self.block()
        self.assertEqual(row["frame_display"], "eras")
        self.assertFalse(row["proposal_pending"])
        self.assertEqual(row["decision_id"], decision["decision_id"])

    def test_undoing_puts_the_frame_back_and_the_proposal_returns(self):
        first = era.file_frame_display(
            self.root, frame_id=TWENTIES, mode="eras", frame_label="My 20s",
        )
        era.file_frame_display(
            self.root, frame_id=TWENTIES, mode="frame", frame_label="My 20s",
            supersedes=first["decision_id"],
        )
        row = self.block()
        self.assertEqual(row["frame_display"], "frame")
        self.assertTrue(row["proposal_pending"])

    def test_the_frame_id_never_changes(self):
        before = {row["frame_id"] for row in self.publish()["frame_display"]}
        era.file_frame_display(self.root, frame_id=TWENTIES, mode="eras")
        after = {row["frame_id"] for row in self.publish()["frame_display"]}
        self.assertEqual(before, after)
        self.assertIn(TWENTIES, after)

    def test_presentation_only_chronology_is_byte_identical(self):
        """The whole of §14.5's promise: a display decision changes what is
        DRAWN and nothing about when anything happened."""
        before = self.chronology(self.publish())
        era.file_frame_display(self.root, frame_id=TWENTIES, mode="eras")
        after = self.chronology(self.publish())
        self.assertEqual(json.dumps(before, sort_keys=True),
                         json.dumps(after, sort_keys=True))

    def test_replaying_the_decision_is_a_no_op(self):
        era.file_frame_display(self.root, frame_id=TWENTIES, mode="eras")
        first = pub.rebuild_signature(self.publish())
        era.file_frame_display(self.root, frame_id=TWENTIES, mode="eras")
        self.assertEqual(pub.rebuild_signature(self.publish()), first)

    def test_the_leftover_the_platform_names_is_published(self):
        """*The leftover row's name is the platform's job* — what the package
        owes it is the years: the frame's uncovered sub-intervals."""
        row = self.block()
        self.assertIn("leftover", row)
        for gap in row["leftover"]:
            self.assertEqual(sorted(gap), ["end", "start"])
            self.assertLess(gap["start"], gap["end"])

    def test_the_thread_is_a_real_era_that_contributes_no_covering(self):
        """A9 and ruling 21: the thread exists, it is drawn, and it tiles
        nothing. Hand the fold ONLY the thread and one stretch and My 20s
        stops tiling — proof the tiling read the stretches and not the count
        of eras in the frame."""
        rows = [row for row in self.publish()["nodes"]
                if row.get("event_kind") == tp.NAMED_ERA_EVENT_KIND]
        self.assertEqual(len(rows), 3)
        self.assertEqual(
            len([row for row in rows if row.get("label") == "Fatherhood"]), 1
        )
        views = ei.era_views(self.root)
        kept = {era_id: view for era_id, view in views.items()
                if view["label"] in ("College Years", "Fatherhood")}
        self.assertEqual(len(kept), 2)
        timeline = tt.derive_calculated_timeline(
            ts.fold_active_index(self.root), birth_date=BIRTH_DAY, now=NOW,
            era_views=kept,
        )
        blocks = {row["frame_id"]: row for row in timeline.frame_display}
        self.assertFalse(blocks[TWENTIES]["proposal_pending"])
        self.assertTrue(blocks[TWENTIES]["leftover"])


# ---------------------------------------------------------------------------
# The verb (§9.1's one door)
# ---------------------------------------------------------------------------


class TheWriterVerb(unittest.TestCase):

    def test_it_is_a_direct_vault_mutation_like_era_record(self):
        self.assertIn("frame-display", lifehug.DIRECT_MUTATION_COMMANDS)

    def test_the_parser_declares_it(self):
        parser = lifehug.build_parser()
        choices = parser._subparsers._group_actions[0].choices  # noqa: SLF001
        self.assertIn("frame-display", choices)
        self.assertIn("--undo", choices["frame-display"].format_usage())


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
