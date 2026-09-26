"""v365 (owner, 2026-09-26) (the owner): a drop inside the landmark brackets TIGHTENS.

"That's a loose range that lets the user drop it and make it tighter. Your
system can use those landmarks as a way to make those ranges tighter because if
it fits within three, the smallest set of those landmarks is the new added
range." / "I don't want this to change how the system works when movement
happens today, other than to be additive. If it is a more narrow range, move it
and add more information. Yes the moments above and below it are also
information. And it counts as my statement. Conflict brings it up."

`drag_tighten.A_DROP_INSIDE_LANDMARKS_TIGHTENS_TO_THEIR_OVERLAP`, through the
real `lifehug.py timeline-move` / `timeline-move-undo` argv the platform runs
(``LIFEHUG_VAULT_ROOT`` bound, as its package runner does). Synthetic vault
only; NEVER references ~/Workspace/dave.
"""

from __future__ import annotations

import copy
import json
import os
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SYSTEM = ROOT / "system"
sys.path.insert(0, str(SYSTEM))
sys.path.insert(0, str(ROOT / "tests"))

import drag_tighten as dt  # noqa: E402
import mirror_work  # noqa: E402
import temporal_claims as tc  # noqa: E402
import temporal_publication as pub  # noqa: E402
import temporal_store as ts  # noqa: E402
import timeline  # noqa: E402
from tempdirs import root_parent_tmp  # noqa: E402
from test_conversation_close import make_vault  # noqa: E402

NOW = "2026-09-26T12:00:00Z"


def when(text: str) -> dict:
    grain = {4: "year", 7: "month", 10: "day"}[len(text)]
    return {"best": text, "earliest": text, "latest": text, "granularity": grain,
            "confidence": "certain", "basis": "stated", "anchors": [], "provenance": []}


#: Born Jul 1981, so Teen years run Jul 1994 – Jul 2001. In the teens he
#: lived at Hope (Jun 1993 – Jun 1997) and went to Mountain View (Jun 1994 –
#: Jun 1998): the brackets through the head of the Teen list overlap from
#: Jun 1994 to Jun 1997.
SEED = {
    "birth": [{"domain": "birth", "year": "1981", "month": "07", "day": "11",
               "date": when("1981-07-11")}],
    "residences": [
        {"domain": "residences", "label": "Hope", "nickname": "Hope",
         "address": "2624 E Hope St, Mesa, AZ", "city": "Mesa, Arizona",
         "span": {"start": when("1993-06"), "end": when("1997-06")}},
        {"domain": "residences", "label": "Williams", "nickname": "Williams",
         "address": "701 N Williams, Mesa, AZ", "city": "Mesa, Arizona",
         "span": {"start": when("1997-06"), "end": when("2000-08")}},
    ],
    "schools": [
        {"domain": "schools", "label": "Mountain View", "name": "Mountain View",
         "place": "Mesa, Arizona",
         "span": {"start": when("1994-06"), "end": when("1998-06")}},
    ],
}


def source_ref(seed: str) -> dict:
    import hashlib  # noqa: PLC0415

    return {"source_id": f"src-{seed}",
            "revision": "sha256:" + hashlib.sha256(seed.encode()).hexdigest()}


def moment(seed: str, title: str, value: object, *, his: bool) -> dict:
    """One moment, dated either in his own words or by the system."""
    return tc.validate_temporal_claim({
        "source_kind": "conversation", "source_ref": source_ref(seed),
        "evidence": [{"quote": f"{title}."}], "extractor_version": "listener:1",
        "created_at": "2026-09-01T00:00:00Z", "claim_type": "date",
        "subject_mention": "Dave", "event_kind": "moment", "event_mention": title,
        # Its own event, as the recorder mints one per moment it hears.
        "event_ref": "node:" + source_ref(seed)["revision"][7:31],
        "temporal_value": value, "basis": "explicit" if his else "inferred",
        "confidence": 0.9 if his else 0.4, "status": "active",
    })


def loose(earliest: str, latest: str) -> dict:
    return {"best": f"{earliest}/{latest}", "earliest": earliest, "latest": latest,
            "granularity": "range", "confidence": "inferred", "basis": "anchor",
            "anchors": [], "provenance": []}


MOMENTS = {
    # The loose one he drags: the system's own wide reading of his teens.
    "worry": ("Money worries at home", loose("1994-07", "2001-06"), False),
    "prom": ("Junior prom", "1997-04", True),
    "car": ("Bought first car", "1996-02", True),
    "job": ("Started at the pizza place", "1996-09", True),
    # A date he gave himself, a year wide.
    "concert": ("First concert", "1999", True),
}


class DropVault(unittest.TestCase):
    """A real on-disk vault; seeding runs in-process, the verbs in a subprocess."""

    def setUp(self) -> None:
        self.tmp = root_parent_tmp(self, ROOT, prefix="lifehug-drag-tighten-")
        self.vault = make_vault(self.tmp / "vault")
        (self.vault / "profile.yaml").write_text("name: Dave\nfull_name: David James Taylor\n",
                                                 encoding="utf-8")
        self.store = self.vault / "state" / "landmarks.json"
        for patch in (mock.patch.object(timeline, "LANDMARKS_STORE", self.store),
                      mock.patch.object(timeline, "_projection_vault_root", lambda: self.vault)):
            patch.start()
            self.addCleanup(patch.stop)
        self.store.write_text(json.dumps({"version": 1, "domains": copy.deepcopy(SEED)},
                                         indent=2) + "\n", encoding="utf-8")
        timeline.flip_landmarks_if_needed()
        for seed, (title, value, his) in MOMENTS.items():
            claim = moment(seed, title, value, his=his)
            ts.write_receipt(self.vault, {"source_ref": claim["source_ref"],
                                          "extractor_version": "listener:1", "claims": [claim]})
        pub.publish(self.vault, now=NOW, full=True)
        self.env = os.environ.copy()
        self.env.update({"LIFEHUG_VAULT_ROOT": str(self.vault), "PYTHONDONTWRITEBYTECODE": "1"})
        self.env.pop("WORKSPACE", None)
        self.env.pop("PYTHONPATH", None)
        self.ids = {seed: self.node_titled(title)["node_id"] for seed, (title, _, _) in MOMENTS.items()}

    # -- reading ----------------------------------------------------------------

    def projection(self) -> dict:
        return pub.read_projection(self.vault) or {}

    def node_titled(self, title: str) -> dict:
        found = [n for n in self.projection()["nodes"] if n.get("label") == title]
        self.assertEqual(len(found), 1, title)
        return found[0]

    def node(self, seed: str) -> dict:
        return next(n for n in self.projection()["nodes"] if n["node_id"] == self.ids[seed])

    def tighten_receipts(self) -> list[Path]:
        return sorted(p for p in (self.vault / "state" / "temporal_claims").rglob("*.json")
                      if "drag-tighten" in p.read_text(encoding="utf-8")
                      and p.parent.name != "temporal_claims")

    # -- the verbs --------------------------------------------------------------

    def move(self, subject: str, relation: str, *anchors: str, extra: tuple = ()) -> dict:
        argv = ["timeline-move", self.ids[subject], "--relation", relation]
        for anchor in anchors:
            argv += ["--anchor", self.ids[anchor]]
        result = subprocess.run([sys.executable, str(SYSTEM / "lifehug.py"), *argv, "--json", *extra],
                                capture_output=True, text=True, env=self.env, cwd=self.vault,
                                timeout=300, stdin=subprocess.DEVNULL)
        self.assertEqual(result.returncode, 0, result.stderr)
        line = next(row for row in result.stdout.splitlines() if row.startswith("{"))
        return {"stdout": result.stdout, **json.loads(line)}

    def undo(self, constraint_id: str) -> str:
        result = subprocess.run([sys.executable, str(SYSTEM / "lifehug.py"), "timeline-move-undo",
                                 constraint_id], capture_output=True, text=True, env=self.env,
                                cwd=self.vault, timeout=300, stdin=subprocess.DEVNULL)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout


class ADropInsideTheBracketsNarrowsToTheirOverlap(DropVault):

    def test_the_head_of_a_list_is_bounded_by_the_home_and_school_overlap(self) -> None:
        """Dropped over "Bought first car" at the head of the Teen list: the
        brackets through that gap are Hope and Mountain View, whose overlap
        starts Jun 1994 — the later of their starts — and the car bounds it
        below."""
        out = self.move("worry", "before", "car")
        decision = out["tighten"]
        self.assertEqual(decision["outcome"], dt.OUTCOME_TIGHTENED)
        # 2026-09-26: the Teen years band bounds it too, so it starts at 13, not June 1994.
        self.assertEqual(decision["window"], {"earliest": "1994-07", "latest": "1996-02"})
        self.assertEqual(sorted(m["label"] for m in decision["landmarks"]), ["Hope", "Mountain View"])
        self.assertEqual(decision["neighbours"]["below"]["label"], "Bought first car")
        best = self.node("worry")["best_temporal_value"]
        # The window is his, whole: the frame is not a bound, the brackets are.
        self.assertEqual((best["earliest"], best["latest"], best["basis"]), ("1994-07", "1996-02", "stated"))
        self.assertIn("tightened (tightened): Jul 1994 – Feb 1996, your statement", out["stdout"])

    def test_it_counts_as_his_statement_citing_the_move(self) -> None:
        out = self.move("worry", "before", "car")
        receipts = self.tighten_receipts()
        self.assertEqual(len(receipts), 1)
        receipt = json.loads(receipts[0].read_text())
        claim = receipt["claims"][0]
        self.assertEqual((claim["basis"], claim["temporal_value"]["basis"]), ("explicit", "stated"))
        self.assertEqual(claim["event_ref"], self.ids["worry"])
        self.assertEqual(claim["source_ref"]["source_path"], out["source"])
        self.assertEqual(receipt["extractor"]["rule"], "A_DROP_INSIDE_LANDMARKS_TIGHTENS_TO_THEIR_OVERLAP")
        self.assertEqual(receipt["extractor"]["constraint_id"], out["constraint_id"])
        self.assertIn("Inside Hope (home), Mountain View (school).", claim["evidence"][0]["quote"])
        self.assertEqual(self.node("worry")["basis"], "explicit")


class TheNeighboursBoundIt(DropVault):

    def test_between_two_moments_is_after_the_one_above_and_before_the_one_below(self) -> None:
        out = self.move("worry", "between", "car", "job")
        self.assertEqual(out["tighten"]["window"], {"earliest": "1996-02", "latest": "1996-09"})
        self.assertEqual(out["tighten"]["neighbours"]["above"]["label"], "Bought first car")
        self.assertEqual(out["tighten"]["neighbours"]["below"]["label"], "Started at the pizza place")
        best = self.node("worry")["best_temporal_value"]
        self.assertEqual((best["earliest"], best["latest"]), ("1996-02", "1996-09"))

    def test_a_drop_at_the_tail_is_closed_by_the_band(self) -> None:
        """Under the concert (1999), at the tail: no bracket runs through the
        gap, but the Teen years band ends Jul 2001, so the drop now says
        "after the concert, while still a teen" (owner, 2026-09-26: every band
        is a bound)."""
        out = self.move("worry", "after", "concert")
        self.assertEqual(out["tighten"]["outcome"], dt.OUTCOME_TIGHTENED)
        self.assertEqual(out["tighten"]["window"]["latest"], "2001-07")
        self.assertIn("Teen years", [b["label"] for b in out["tighten"]["bands"]][0])


class NotNarrowerIsTodaysMoveExactly(DropVault):

    def test_a_precise_moment_moved_wide_files_only_the_move(self) -> None:
        before = self.node("car")
        out = self.move("car", "before", "prom")  # window Jun 1994 – Apr 1997, wider than Feb 1996
        self.assertEqual(out["tighten"]["outcome"], dt.OUTCOME_NOT_NARROWER)
        self.assertEqual(self.tighten_receipts(), [])
        after = self.node("car")
        self.assertEqual(after["best_temporal_value"], before["best_temporal_value"])
        self.assertEqual(after["input_claim_refs"], before["input_claim_refs"])
        self.assertEqual(after["input_constraint_refs"], [out["constraint_id"]])

    def test_the_flag_off_files_the_same_move_and_nothing_else(self) -> None:
        out = self.move("worry", "before", "car", extra=("--no-tighten",))
        self.assertIsNone(out["tighten"])
        self.assertEqual(self.tighten_receipts(), [])
        self.assertEqual(self.node("worry")["input_constraint_refs"], [out["constraint_id"]])


class AConflictWithHisDateIsAQuestion(DropVault):

    def test_a_window_that_misses_his_own_date_is_filed_and_raised(self) -> None:
        """He said the concert was 1999; dropping it between the car and the
        pizza job says Feb – Sep 1996. Both are his: never a silent move."""
        out = self.move("concert", "between", "car", "job")
        self.assertEqual(out["tighten"]["outcome"], dt.OUTCOME_HIS_DATE_DISAGREES)
        self.assertIn("it disagrees with a date you gave", out["stdout"])
        node = self.node("concert")
        self.assertNotEqual(node["conflict_state"], "none")
        alternates = {(v.get("earliest"), v.get("latest")) for v in node.get("alternate_values") or ()}
        shown = (node["best_temporal_value"]["earliest"], node["best_temporal_value"]["latest"])
        self.assertIn(("1996-02", "1996-09"), alternates | {shown})
        self.assertIn(("1999", "1999"), alternates | {shown})
        kinds = {row.kind for row in mirror_work.load_mirror_rows(self.vault)}
        self.assertIn("contradiction", kinds)
        # The card names HIS drop, not only the move's ordering edge.
        claim_id = json.loads(self.tighten_receipts()[0].read_text())["claims"][0]["claim_id"]
        items = (pub.read_work_items(self.vault) or {}).get("work_items") or []
        cards = [item for item in items
                 if item.get("kind") == "contradiction" and item.get("event_ref") == self.ids["concert"]]
        self.assertEqual(len(cards), 1, [i.get("kind") for i in items])
        self.assertIn(claim_id, cards[0]["claim_refs"])
        self.assertIn("1999", cards[0]["prompt_intent"])
        # His 1999 still shows: nothing moved silently.
        self.assertEqual(node["best_temporal_value"]["best"], "1999")


class UndoRestores(DropVault):

    def test_undo_retracts_the_window_with_the_move_and_keeps_both_records(self) -> None:
        before = self.node("worry")["best_temporal_value"]
        out = self.move("worry", "before", "car")
        claim_id = json.loads(self.tighten_receipts()[0].read_text())["claims"][0]["claim_id"]
        said = self.undo(out["constraint_id"])
        self.assertIn(f"the drop's window is undone too: {claim_id}", said)
        node = self.node("worry")
        self.assertEqual(node["best_temporal_value"]["earliest"], before["earliest"])
        self.assertEqual(node["best_temporal_value"]["latest"], before["latest"])
        self.assertEqual(node["input_constraint_refs"], [])
        # Nothing deleted: the move source and the receipt are still on disk.
        self.assertTrue((self.vault / out["source"]).is_file())
        self.assertEqual(len(self.tighten_receipts()), 1)


class TheDecisionIsPure(unittest.TestCase):
    """`drag_tighten.decide` over a hand-built projection — the bracket rule."""

    def projection(self) -> dict:
        def node(node_id, earliest, latest, basis="calculated", kind="event"):
            return {"node_id": node_id, "node_kind": kind, "label": node_id, "basis": basis,
                    "best_temporal_value": {"best": f"{earliest}/{latest}", "earliest": earliest,
                                            "latest": latest}}
        frame = node("age:self:childhood", "1981-07-11", "1994-07-10", "explicit", "period")
        frame["event_kind"] = "age_frame"
        return {"nodes": [frame, node("n:a", "1986-06", "1986-06", "explicit"),
                          node("n:b", "1987-03", "1987-03", "explicit"),
                          node("n:x", "1981-07", "1994-06")],
                "landmarks_view": {"domains": [
                    {"domain": "residences", "landmarks": [
                        {"entry_id": "r:figers", "label": "Figers", "stays": [
                            {"start": "1982-08", "end": "1986-06", "stay_index": 0}]},
                        {"entry_id": "r:fisches", "label": "Fisches", "stays": [
                            {"start": "1986-06", "end": "1988-06", "stay_index": 0}]}]}]}}

    def test_a_move_month_belongs_to_the_stay_it_starts(self) -> None:
        stays = dt.landmark_stays(self.projection())
        self.assertEqual(dt.drawn_landmark(stays, "home", dt.month_of("1986-06"))["label"], "Fisches")
        self.assertEqual(dt.drawn_landmark(stays, "home", dt.month_of("1986-05"))["label"], "Figers")
        self.assertIsNone(dt.drawn_landmark(stays, "school", dt.month_of("1986-05")))

    def test_within_a_frame_is_not_a_drop_among_the_rows(self) -> None:
        decision = dt.decide(self.projection(), subject_node_id="n:x", relation="within",
                             anchor_node_ids=["age:self:childhood"])
        self.assertEqual(decision["outcome"], dt.OUTCOME_NO_WINDOW)

    def test_between_names_the_bracket_through_the_gap(self) -> None:
        decision = dt.decide(self.projection(), subject_node_id="n:x", relation="between",
                             anchor_node_ids=["n:a", "n:b"])
        self.assertEqual(decision["window"], {"earliest": "1986-06", "latest": "1987-03"})
        self.assertEqual([m["label"] for m in decision["landmarks"]], ["Fisches"])
        self.assertEqual(decision["outcome"], dt.OUTCOME_TIGHTENED)


class EveryBandIsABound(unittest.TestCase):
    """Owner, 2026-09-26: "all bands should be additive… mission, Wetzikon, 20s
    don't conflict but the subset narrow ranges for higher fidelity"."""

    @staticmethod
    def node(node_id, earliest, latest, basis="calculated", kind="event", event_kind=None):
        row = {"node_id": node_id, "node_kind": kind, "label": node_id, "basis": basis,
               "best_temporal_value": {"best": f"{earliest}/{latest}", "earliest": earliest,
                                       "latest": latest}}
        if event_kind:
            row["event_kind"] = event_kind
        return row

    def test_a_drop_at_the_head_of_teen_years_never_starts_before_thirteen(self) -> None:
        teen = self.node("Teen years", "1994-07-11", "2001-07-10", "explicit", "period", "age_frame")
        projection = {"nodes": [teen, self.node("n:first", "1995-06", "1995-06", "explicit"),
                                self.node("n:x", "1981-07", "1999-06")],
                      "landmarks_view": {"domains": [{"domain": "residences", "landmarks": [
                          {"entry_id": "r:crossridge", "label": "Crossridge", "stays": [
                              {"start": "1994-06", "end": "1995-06", "stay_index": 0}]}]}]}}
        decision = dt.decide(projection, subject_node_id="n:x", relation="before",
                             anchor_node_ids=["n:first"])
        self.assertEqual(decision["window"]["earliest"], "1994-07")
        self.assertEqual([b["label"] for b in decision["bands"]], ["Teen years"])

    def test_mission_wetzikon_and_twenties_intersect(self) -> None:
        twenties = self.node("My 20s", "2001-07-11", "2011-07-10", "explicit", "period", "age_frame")
        mission = self.node("Mission", "2000-08", "2002-06", "explicit", "period", "era")
        projection = {"nodes": [twenties, mission,
                                self.node("n:a", "2001-12", "2001-12", "explicit"),
                                self.node("n:b", "2002-05", "2002-05", "explicit"),
                                self.node("n:x", "2000-08", "2005-06")],
                      "landmarks_view": {"domains": [{"domain": "residences", "landmarks": [
                          {"entry_id": "r:wetzikon", "label": "Wetzikon", "stays": [
                              {"start": "2001-12", "end": "2002-06", "stay_index": 0}]}]}]}}
        decision = dt.decide(projection, subject_node_id="n:x", relation="between",
                             anchor_node_ids=["n:a", "n:b"])
        self.assertEqual(decision["window"], {"earliest": "2001-12", "latest": "2002-05"})
        self.assertEqual(sorted(b["label"] for b in decision["bands"]), ["Mission", "My 20s"])
        self.assertEqual([m["label"] for m in decision["landmarks"]], ["Wetzikon"])
        self.assertEqual(decision["outcome"], dt.OUTCOME_TIGHTENED)


if __name__ == "__main__":
    unittest.main()
