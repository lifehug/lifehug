"""v365 (owner, 2026-09-26) (the owner): combine and fold by drag, the empty-landmark
row, and the Solothurn restatements.

* `timeline_combine.A_ROW_DROPPED_ON_A_ROW_IS_THE_SAME_MOMENT` — a row dropped
  ONTO a row: one moment carrying both tellings, his statement, undoable. It
  runs event identity's own same_event confirm and its undo is the split.
* `timeline_combine.A_ROW_DROPPED_ON_A_LANDMARK_FOLDS_INTO_IT` — a row dropped
  onto a landmark line folds into it (`folded_into_landmark`), undoable.
* `drag_tighten.A_DROP_ON_AN_EMPTY_LANDMARK_IS_INSIDE_IT` — a drop onto an
  empty landmark's slim row is inside that stay's span, with its bands.
* `landmark_fold.A_LANDMARK_RESTATEMENT_FOLDS_INTO_IT` — "Brief residence in
  Solothurn" and "Mission assignment to Solothurn" only restate Solothurn.
* A landmark starting at a band's very first month (Avenue F, Jul 1981) is a
  boundary like any other: a drop just below its start line is inside it.

Through the real `lifehug.py` argv the platform runs. Synthetic vault only;
NEVER references ~/Workspace/dave.
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
import event_identity as ei  # noqa: E402
import landmark_fold as lf  # noqa: E402
import temporal_claims as tc  # noqa: E402
import temporal_publication as pub  # noqa: E402
import temporal_store as ts  # noqa: E402
import timeline_combine as tcm  # noqa: E402
from test_v365_drag_tighten import NOW, DropVault, when  # noqa: E402
from test_v365_landmark_boundaries import VIEW, row, stay  # noqa: E402


def told(seed: str, title: str, value: object) -> dict:
    """A moment told in one story, whose source id is a telling ref."""
    import hashlib  # noqa: PLC0415

    digest = hashlib.sha256(seed.encode()).hexdigest()
    return tc.validate_temporal_claim({
        "source_kind": "conversation",
        "source_ref": {"source_id": f"story:{seed}", "revision": f"sha256:{digest}"},
        "evidence": [{"quote": f"{title}."}], "extractor_version": "listener:1",
        "created_at": "2026-09-01T00:00:00Z", "claim_type": "date",
        "subject_mention": "Dave", "event_kind": "moment", "event_mention": title,
        "event_ref": "node:" + digest[:24],
        "temporal_value": value, "basis": "explicit", "confidence": 0.9, "status": "active",
    })


class GesturesVault(DropVault):
    """The drag-tighten vault plus two tellings of one night and a third moment."""

    def setUp(self) -> None:
        super().setUp()
        for seed, title, value in (("nail-a", "Fell on a nail", when("1996-05")),
                                   ("nail-b", "Stepped on a nail at the pool", when("1996-05")),
                                   ("dance", "Homecoming dance", when("1997-10"))):
            claim = told(seed, title, value)
            ts.write_receipt(self.vault, {"source_ref": claim["source_ref"],
                                          "extractor_version": "listener:1", "claims": [claim]})
        pub.publish(self.vault, now=NOW, full=True)

    def run_verb(self, *argv: str, ok: bool = True) -> subprocess.CompletedProcess:
        result = subprocess.run([sys.executable, str(SYSTEM / "lifehug.py"), *argv],
                                capture_output=True, text=True, env=self.env, cwd=self.vault,
                                timeout=300, stdin=subprocess.DEVNULL)
        if ok:
            self.assertEqual(result.returncode, 0, result.stderr)
        return result

    def json_of(self, result: subprocess.CompletedProcess) -> dict:
        return json.loads(next(line for line in result.stdout.splitlines() if line.startswith("{")))

    def rows(self) -> list[dict]:
        return [n for n in self.projection()["nodes"]
                if n.get("node_kind") != "period" and not n.get("folded_into_landmark")]

    def titled(self, title: str) -> list[dict]:
        return [n for n in self.rows() if n.get("label") == title]


class ARowDroppedOnARowIsTheSameMoment(GesturesVault):

    def combine(self) -> dict:
        a = self.titled("Fell on a nail")[0]["node_id"]
        b = self.titled("Stepped on a nail at the pool")[0]["node_id"]
        return self.json_of(self.run_verb("timeline-combine", a, "--with", b, "--json"))

    def test_the_two_rows_become_one_moment_carrying_both_tellings(self) -> None:
        before = len(self.rows())
        out = self.combine()
        self.assertEqual(out["rule"], "A_ROW_DROPPED_ON_A_ROW_IS_THE_SAME_MOMENT")
        self.assertRegex(out["combine_id"], r"^combine:[0-9a-f]{24}$")
        self.assertEqual(len(self.rows()), before - 1)
        merged = [n for n in self.rows() if n.get("episode_id") == out["episode_id"]]
        self.assertEqual(len(merged), 1)
        self.assertEqual(sorted(merged[0]["tellings"]), ["story:nail-a", "story:nail-b"])
        # His statement: one correction source, and every identity record it
        # wrote cites it.
        source = self.vault / out["source"]
        meta, _ = ts.split_frontmatter(source.read_text())
        self.assertEqual((meta["type"], meta["source_medium"]), ("timeline_combine", "owner"))
        self.assertEqual(meta["before"], {"story:nail-a": None, "story:nail-b": None})
        cited = [b for b in ei.load_event_identities(self.vault) if b.get("source_ref") == out["source"]]
        self.assertEqual(sorted(b["telling_ref"] for b in cited), ["story:nail-a", "story:nail-b"])
        self.assertTrue(all(b["origin"] == "confirmed" and b["relation"] == "same" for b in cited))
        # The other moments are untouched.
        self.assertEqual(len(self.titled("Homecoming dance")), 1)

    def test_undo_splits_them_apart_and_a_second_combine_joins_them_again(self) -> None:
        before = len(self.rows())
        out = self.combine()
        undone = self.json_of(self.run_verb("timeline-combine-undo", out["combine_id"], "--json"))
        self.assertTrue(undone["undone"])
        self.assertEqual(undone["destinations"], {"story:nail-a": "standalone", "story:nail-b": "standalone"})
        self.assertEqual(len(self.rows()), before)
        self.assertEqual(len(self.titled("Fell on a nail")), 1)
        self.assertEqual(len(self.titled("Stepped on a nail at the pool")), 1)
        # Undoing twice files nothing more.
        again = self.json_of(self.run_verb("timeline-combine-undo", out["combine_id"], "--json"))
        self.assertFalse(again["undone"])
        # Combined again after the undo: a new statement, and one row again.
        second = self.combine()
        self.assertNotEqual(second["combine_id"], out["combine_id"])
        self.assertEqual(len(self.rows()), before - 1)

    def test_combining_twice_is_one_statement(self) -> None:
        first = self.combine()
        a = next(n for n in self.rows() if n.get("episode_id") == first["episode_id"])
        self.assertEqual(len(list((self.vault / "sources" / "corrections").glob("combine-*.md"))), 1)
        self.assertTrue(a["tellings"])

    def test_a_row_onto_itself_or_a_band_files_nothing(self) -> None:
        nail = self.titled("Fell on a nail")[0]["node_id"]
        result = self.run_verb("timeline-combine", nail, "--with", nail, ok=False)
        self.assertEqual(result.returncode, 1)
        self.assertIn("combine_needs_two_rows", result.stderr)
        band = next(n["node_id"] for n in self.projection()["nodes"] if n.get("node_kind") == "period")
        result = self.run_verb("timeline-combine", nail, "--with", band, ok=False)
        self.assertIn("combine_node_not_drawn", result.stderr)
        self.assertFalse(list((self.vault / "sources" / "corrections").glob("combine-*.md")))


class ARowDroppedOnALandmarkFoldsIntoIt(GesturesVault):

    def williams(self) -> str:
        view = self.projection()["landmarks_view"]
        return next(l["entry_id"] for d in view["domains"] for l in d["landmarks"] if l["label"] == "Williams")

    def test_the_row_folds_its_telling_shows_in_the_form_and_undo_gives_it_back(self) -> None:
        dance = self.titled("Homecoming dance")[0]["node_id"]
        before = len(self.rows())
        out = self.json_of(self.run_verb("timeline-fold", dance, "--landmark", self.williams(), "--json"))
        self.assertRegex(out["fold_id"], r"^fold:[0-9a-f]{24}$")
        node = next(n for n in self.projection()["nodes"] if n["node_id"] == dance)
        self.assertEqual((node["folded_into_landmark"], node["folded_as"], node["fold_id"]),
                         (self.williams(), "stated", out["fold_id"]))
        self.assertEqual(len(self.rows()), before - 1)
        view = self.projection()["landmarks_view"]
        landmark = next(l for d in view["domains"] for l in d["landmarks"] if l["entry_id"] == self.williams())
        telling = next(t for t in landmark["tellings"] if t["node_id"] == dance)
        self.assertEqual((telling["words"], telling["stated"]), (["Homecoming dance."], True))
        fold = next(r for r in view["folds"] if r["node_id"] == dance)
        self.assertEqual(fold["why"], "you folded it")
        self.run_verb("timeline-fold-undo", out["fold_id"])
        self.assertEqual(len(self.rows()), before)
        self.assertNotIn("folded_into_landmark",
                         next(n for n in self.projection()["nodes"] if n["node_id"] == dance))

    def test_a_fold_naming_no_landmark_files_nothing(self) -> None:
        dance = self.titled("Homecoming dance")[0]["node_id"]
        result = self.run_verb("timeline-fold", dance, "--landmark", "residences:nowhere", ok=False)
        self.assertIn("fold_landmark_unknown", result.stderr)
        self.assertEqual(tcm.stated_folds(self.vault), [])

    def test_a_stated_fold_outranks_a_guessed_one_and_follows_its_telling(self) -> None:
        nodes = [row("n:into-figers", "Move to Figers House", "1982-08")]
        nodes[0]["tellings"] = ["story:figers"]
        view = json.loads(json.dumps(VIEW))
        stated = [{"fold_id": "fold:" + "a" * 24, "node_id": "n:gone", "entry_id": "residences:hope",
                   "stay_index": 0, "tellings": ["story:figers"]}]
        rows = lf.apply_folds(nodes, view, stated=stated)
        self.assertEqual([(r["entry_id"], r["boundary"], r["stated"]) for r in rows],
                         [("residences:hope", "stay", True)])
        self.assertEqual(nodes[0]["folded_as"], "stated")
        # A stated fold into a stay the landmark does not have is dropped.
        stated[0]["stay_index"] = 7
        self.assertEqual(lf.stated_fold_rows(nodes, view, stated), [])


class ADropOnAnEmptyLandmarkIsInsideIt(unittest.TestCase):
    """`drag_tighten.decide` with a ``landmark:<entry>:<stay>:stay`` anchor."""

    MTC = "landmark:missions:mtc:0:stay"

    def projection(self, earliest: str, latest: str, *, his: bool = False) -> dict:
        def node(node_id, a, b, basis="explicit"):
            return {"node_id": node_id, "node_kind": "event", "label": node_id, "basis": basis,
                    "best_temporal_value": {"best": f"{a}/{b}", "earliest": a, "latest": b}}
        return {"nodes": [node("n:above", "2000-01", "2000-01"), node("n:below", "2001-06", "2001-06"),
                          node("n:x", earliest, latest, "explicit" if his else "calculated"),
                          {"node_id": "age:self:teens", "node_kind": "period", "event_kind": "age_frame",
                           "label": "Teen years",
                           "best_temporal_value": {"best": "1994-07/2000-09", "earliest": "1994-07",
                                                   "latest": "2000-09"}}],
                "landmarks_view": {"domains": [{"domain": "missions", "landmarks": [
                    {"entry_id": "missions:mtc", "label": "MTC", "nickname": "MTC",
                     "stays": [stay("2000-08", "2000-10")]}]}]}}

    def decide(self, projection: dict) -> dict:
        return dt.decide(projection, subject_node_id="n:x", relation="between",
                         anchor_node_ids=["n:above", "n:below"], boundary_anchors=[self.MTC])

    def test_a_loose_moment_is_placed_inside_the_stay_and_its_band(self) -> None:
        decision = self.decide(self.projection("1999-01", "2003-01"))
        self.assertEqual(decision["rule"], "A_DROP_ON_AN_EMPTY_LANDMARK_IS_INSIDE_IT")
        self.assertEqual(decision["outcome"], dt.OUTCOME_TIGHTENED)
        # MTC is Aug–Oct 2000; the Teen years band ends Sep 2000.
        self.assertEqual(decision["window"], {"earliest": "2000-08", "latest": "2000-09"})
        self.assertEqual([m["label"] for m in decision["landmarks"]], ["MTC"])
        self.assertEqual(decision["boundaries"][0]["side"], "stay")
        self.assertIn("Inside MTC (mission).", dt.evidence_sentence(decision))

    def test_the_rows_either_side_do_not_bound_it(self) -> None:
        decision = self.decide(self.projection("1999-01", "2003-01"))
        self.assertEqual(decision["neighbours"]["above"]["label"], "n:above")
        self.assertNotEqual(decision["window"]["earliest"], "2000-01")

    def test_a_moment_already_inside_is_left_as_it_is(self) -> None:
        decision = self.decide(self.projection("2000-08", "2000-09"))
        self.assertEqual(decision["outcome"], dt.OUTCOME_NOT_NARROWER)

    def test_a_date_he_gave_outside_it_raises_the_question(self) -> None:
        decision = self.decide(self.projection("2001-03", "2001-03", his=True))
        self.assertEqual(decision["outcome"], dt.OUTCOME_HIS_DATE_DISAGREES)
        self.assertEqual(decision["window"], {"earliest": "2000-08", "latest": "2000-09"})

    def test_the_anchor_grammar_takes_the_whole_stay(self) -> None:
        self.assertEqual(lf.parse_boundary_anchor(self.MTC), ("missions:mtc", 0, "stay"))
        self.assertEqual(lf.boundary_anchor("missions:mtc", 0, "stay"), self.MTC)


class TheEmptyLandmarkDropThroughTheVerb(GesturesVault):

    def test_timeline_move_with_a_stay_anchor_files_his_window(self) -> None:
        view = self.projection()["landmarks_view"]
        williams = next(l["entry_id"] for d in view["domains"] for l in d["landmarks"] if l["label"] == "Williams")
        out = self.move("worry", "between", "prom", "concert",
                        extra=("--boundary", lf.boundary_anchor(williams, 0, "stay")))
        decision = out["tighten"]
        self.assertEqual(decision["outcome"], dt.OUTCOME_TIGHTENED)
        # Williams Jun 1997 – Aug 2000, inside the Teen years, and his current
        # loose reading (Jul 1994 – Jun 2001).
        self.assertEqual(decision["window"], {"earliest": "1997-06", "latest": "2000-08"})
        # Placed inside it; the move's own ordering (before the 1999 concert)
        # still holds as it always did.
        best = self.node("worry")["best_temporal_value"]
        self.assertEqual((best["earliest"], best["latest"]), ("1997-06", "1999"))


class ALandmarkAtABandsFirstMonthIsABoundaryLikeAnyOther(unittest.TestCase):
    """Avenue F starts Jul 1981, Childhood's first month. A drop at the head of
    Childhood, just below its start line, is inside Avenue F."""

    def test_the_start_line_at_the_bands_first_month_bounds_the_drop(self) -> None:
        def node(node_id, a, b, kind="event", basis="calculated"):
            return {"node_id": node_id, "node_kind": kind, "label": node_id, "basis": basis,
                    "event_kind": "age_frame" if kind == "period" else "moment",
                    "best_temporal_value": {"best": f"{a}/{b}", "earliest": a, "latest": b}}
        projection = {
            "nodes": [node("age:self:childhood", "1981-07", "1994-07", "period"),
                      node("n:birth", "1981-07", "1981-07", basis="explicit"),
                      node("n:x", "1981-07", "1994-06")],
            "landmarks_view": {"domains": [{"domain": "residences", "landmarks": [
                {"entry_id": "residences:avenue-f", "label": "Avenue F", "nickname": "Avenue F",
                 "stays": [stay("1981-07-11", "1982-07")]}]}]},
        }
        decision = dt.decide(projection, subject_node_id="n:x", relation="before",
                             anchor_node_ids=["n:birth"],
                             boundary_anchors=["landmark:residences:avenue-f:0:start"])
        self.assertEqual(decision["boundaries"][0]["month"], "1981-07")
        self.assertEqual(decision["window"], {"earliest": "1981-07", "latest": "1981-07"})


class TheSolothurnRestatementsFold(unittest.TestCase):

    VIEW = {"domains": [{"domain": "missions", "landmarks": [
        {"entry_id": "missions:solothurn-switzerland", "label": "Solothurn, Switzerland",
         "city": "Solothurn", "country": "Switzerland", "node_ids": [],
         "stays": [stay("2000-10", "2000-12")]}]}]}

    def test_brief_residence_and_mission_assignment_restate_solothurn(self) -> None:
        nodes = [row("n:brief", "Brief residence in Solothurn", "2000-10"),
                 row("n:assignment", "Mission assignment to Solothurn", "2000-10", "2000-12"),
                 row("n:time", "Time at Solothurn", "2000-11"),
                 row("n:story", "Brief trip to Solothurn with friends", "2000-11")]
        folds = {r["node_id"]: r for r in lf.fold_candidates(nodes, self.VIEW)}
        for node_id in ("n:brief", "n:assignment", "n:time"):
            self.assertEqual((folds[node_id]["entry_id"], folds[node_id]["boundary"]),
                             ("missions:solothurn-switzerland", "stay"), node_id)
        self.assertNotIn("n:story", folds)


if __name__ == "__main__":
    unittest.main()
