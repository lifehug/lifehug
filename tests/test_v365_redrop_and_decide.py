"""v365 (owner, 2026-09-26): a re-drop after an Undo re-files, and the drop's
decision is readable before anything is filed.

"Re-dropping a row where it was before an undo re-files." A move's source is
content-addressed, so before v365 the same drop after its Undo landed on its
own, already-retracted file and filed nothing (`temporal_store.
redrop_supersedes`). And the page asks what a drop WOULD tighten to while the
drag hovers (`drag_tighten.decide_drop`, `timeline-move-decide`) — the same
decision `timeline-move` makes, with nothing written. Synthetic vault only.
"""

from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SYSTEM = ROOT / "system"
sys.path.insert(0, str(SYSTEM))
sys.path.insert(0, str(ROOT / "tests"))

import drag_tighten as dt  # noqa: E402
import temporal_store as ts  # noqa: E402
from test_v365_drag_tighten import DropVault  # noqa: E402


class AReDropAfterAnUndoReFiles(DropVault):

    def test_the_same_drop_after_its_undo_is_a_new_standing_move(self) -> None:
        first = self.move("worry", "before", "car")
        self.undo(first["constraint_id"])
        self.assertEqual(self.node("worry")["input_constraint_refs"], [])
        again = self.move("worry", "before", "car")
        self.assertNotEqual(again["constraint_id"], first["constraint_id"])
        self.assertEqual(self.node("worry")["input_constraint_refs"], [again["constraint_id"]])
        rows = {row["constraint_id"]: row for row in ts.load_ordering_constraints(self.vault)}
        self.assertEqual(rows[first["constraint_id"]]["status"], "retracted")
        self.assertEqual(rows[again["constraint_id"]]["status"], "active")
        self.assertEqual(rows[again["constraint_id"]]["supersedes_constraint_id"], first["constraint_id"])
        # The drop tightened again, citing the new move.
        self.assertEqual(again["tighten"]["outcome"], dt.OUTCOME_TIGHTENED)
        best = self.node("worry")["best_temporal_value"]
        self.assertEqual((best["earliest"], best["latest"]), ("1994-07", "1996-02"))

    def test_undo_and_redrop_twice_walks_the_chain(self) -> None:
        first = self.move("worry", "before", "car")
        self.undo(first["constraint_id"])
        second = self.move("worry", "before", "car")
        self.undo(second["constraint_id"])
        third = self.move("worry", "before", "car")
        self.assertEqual(len({first["constraint_id"], second["constraint_id"], third["constraint_id"]}), 3)
        self.assertEqual(self.node("worry")["input_constraint_refs"], [third["constraint_id"]])

    def test_a_resend_while_the_move_stands_is_still_one_record(self) -> None:
        first = self.move("worry", "before", "car")
        again = self.move("worry", "before", "car")
        self.assertEqual(again["constraint_id"], first["constraint_id"])
        self.assertEqual(len(ts.load_ordering_constraints(self.vault)), 1)


class TheDecisionBeforeTheFiling(DropVault):

    def decide(self, *argv: str) -> dict:
        result = subprocess.run([sys.executable, str(SYSTEM / "lifehug.py"), "timeline-move-decide", *argv],
                                capture_output=True, text=True, env=self.env, cwd=self.vault,
                                timeout=120, stdin=subprocess.DEVNULL)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout.strip().splitlines()[-1])

    def test_the_verb_says_what_the_move_will_file_and_writes_nothing(self) -> None:
        before = sorted(str(p) for p in self.vault.rglob("*") if p.is_file())
        decided = self.decide(self.ids["worry"], "--relation", "before", "--anchor", self.ids["car"])
        self.assertEqual(sorted(str(p) for p in self.vault.rglob("*") if p.is_file()), before)
        self.assertEqual(decided["outcome"], dt.OUTCOME_TIGHTENED)
        self.assertEqual(decided["window"], {"earliest": "1994-07", "latest": "1996-02"})
        self.assertEqual(decided["filing_outcomes"], list(dt.FILING_OUTCOMES))
        self.assertEqual(decided["projection_generation"], self.projection().get("projection_generation"))
        filed = self.move("worry", "before", "car")
        self.assertEqual(filed["tighten"]["window"], decided["window"])
        self.assertEqual(filed["tighten"]["outcome"], decided["outcome"])

    def test_a_given_projection_file_is_decided_against(self) -> None:
        path = self.tmp / "seen.json"
        path.write_text(json.dumps(self.projection()), encoding="utf-8")
        decided = self.decide(self.ids["worry"], "--relation", "between", "--anchor", self.ids["car"],
                              "--anchor", self.ids["job"], "--projection", str(path))
        self.assertEqual(decided["window"], {"earliest": "1996-02", "latest": "1996-09"})

    def test_the_function_equals_decide_with_the_projections_month(self) -> None:
        seen = self.projection()
        direct = dt.decide(seen, subject_node_id=self.ids["worry"], relation="before",
                           anchor_node_ids=[self.ids["car"]], now_month=dt.month_of(seen.get("published_at")))
        wrapped = dt.decide_drop(seen, node=self.ids["worry"], relation="before", anchors=[self.ids["car"]])
        self.assertEqual({k: v for k, v in wrapped.items()
                          if k not in ("filing_outcomes", "projection_generation")}, direct)


if __name__ == "__main__":
    unittest.main()
