"""v365 (owner, 2026-09-26) (the owner): landmark BOUNDARY lines and the move fold.

Two rules, one anchor grammar (``landmark:<entry_id>:<stay_index>:start|end``):

* `drag_tighten.A_DROP_AT_A_BOUNDARY_IS_INSIDE_WHAT_STARTS_OR_ENDS_THERE` — a
  drop just below a boundary stack is inside everything that starts there,
  just above one inside everything that ends there. The move names the
  boundary with ``timeline-move --boundary``; without it, nothing changes.
* `landmark_fold.A_MOVE_MOMENT_FOLDS_INTO_ITS_LANDMARK` — a moment that IS a
  landmark's own start or end ("Move to Figers House", "Moved in from Yucaipa
  Avenue F") is marked folded and not drawn as a row; its tellings ride the
  landmark. "Family moved to Arizona" stays a row (owner-confirmed).

Synthetic data only; NEVER references ~/Workspace/dave.
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
import landmark_fold as lf  # noqa: E402
import temporal_publication as pub  # noqa: E402
import temporal_store as ts  # noqa: E402
from test_v365_drag_tighten import NOW, DropVault, moment, when  # noqa: E402


def stay(start, end, index=0, ongoing=False):
    return {"start": start, "end": end, "stay_index": index, "ongoing": ongoing}


VIEW = {"domains": [
    {"domain": "residences", "landmarks": [
        {"entry_id": "residences:avenue-f", "label": "Avenue F", "nickname": "Avenue F",
         "address": "35292 Avenue F", "city": "Yucaipa", "node_ids": ["node:lm-avenue-f"],
         "stays": [stay("1981-07-11", "1982-07")]},
        {"entry_id": "residences:figers-house", "label": "Figers House", "nickname": "Figers House",
         "node_ids": ["node:lm-figers"], "stays": [stay("1982-08", "1986-06")]},
        {"entry_id": "residences:hope", "label": "Hope", "nickname": "Hope", "address": "2624 E Hope St",
         "city": "Mesa", "node_ids": [], "stays": [stay("1995-06", "1997-06")]},
        {"entry_id": "residences:kristen", "label": "Kristen", "nickname": "Kristen", "node_ids": [],
         "stays": [stay("2007-08", "2009-06")]},
    ]},
    {"domain": "schools", "landmarks": [
        {"entry_id": "schools:longfellow-elementary", "label": "Longfellow Elementary",
         "node_ids": [], "stays": [stay("1985-08", "1989-06")]},
        {"entry_id": "schools:arizona-state-university", "label": "Arizona State University",
         "node_ids": [], "stays": [stay("2012-04", "2013-06")]},
    ]},
    {"domain": "work", "landmarks": [
        {"entry_id": "work:apple", "label": "Apple", "node_ids": [], "stays": [stay("2015", "2018-11")]},
        {"entry_id": "work:janitor", "label": "Janitor (Mesa Public Schools)", "node_ids": [],
         "stays": [stay("1995-06", "1997-06")]},
        {"entry_id": "work:etherfuse", "label": "Etherfuse", "node_ids": [],
         "stays": [stay("2022-05", None, ongoing=True)]},
    ]},
    {"domain": "missions", "landmarks": [
        {"entry_id": "missions:mtc", "label": "MTC", "nickname": "MTC", "node_ids": [],
         "stays": [stay("2000-08", "2000-10")]},
        {"entry_id": "missions:wetzikon", "label": "Wetzikon, Switzerland", "node_ids": [],
         "stays": [stay("2001-12", "2002-06-06")]},
    ]},
]}


def row(node_id, label, earliest, latest=None, *, kind="moment", scope="owner", claims=()):
    latest = latest or earliest
    return {"node_id": node_id, "node_kind": "event", "event_kind": kind, "label": label,
            "occurrence_subject_scope": scope, "input_claim_refs": list(claims),
            "best_temporal_value": {"best": earliest if earliest == latest else f"{earliest}/{latest}",
                                    "earliest": earliest, "latest": latest}}


NODES = [
    row("n:into-figers", "Move to Figers House", "1982-08", claims=["claim:figers", "claim:derived"]),
    row("n:from-avenue", "Moved in from Yucaipa Avenue F", "1982-08", kind="move"),
    row("n:out-figers", "Move out of Figers House", "1986-06"),
    row("n:asu", "Graduation from ASU", "2013-05"),
    row("n:apple", "Started at Apple", "2015-06-08"),
    row("n:mission", "Leaving for the mission", "2000-08"),
    row("n:departed", "Departed on church mission at 19", "2000"),
    row("n:home", "Returned home from the mission", "2002-06"),
    # These stay rows.
    row("n:arizona", "Family moved to Arizona", "1982-08"),
    row("n:mentions", "Frequent childhood moves", "1981-07", "1997-06"),
    row("n:preparing", "Preparing to leave on mission at 18", "1999"),
    row("n:aunt", "Aunt's family moves into Avenue F", "1982-08", scope="other_person"),
    row("n:misdated", "Move to Figers House", "1984-02"),
    row("node:lm-figers", "Figers House", "1982-08", "1986-06", kind="residence"),
    # Owner 2026-09-26: "I don't think we need rows for landmark information."
    row("n:longfellow", "Longfellow Elementary", "1985-08", "1989-06", kind="school"),
    row("n:hope-st", "Residence at Hope St.", "1995-06"),
    row("n:switzerland", "Mission to Switzerland at 19", "2000-07", "2001-07"),
    # A story with content beyond the start or end stays a row.
    row("n:snowboarding", "Quitting janitor job over snowboarding", "1995-06", "1997-06"),
    row("n:markets", "Started Etherfuse to serve non-US markets", "2022-05"),
    row("n:kristen", "You leaves Kristen", "2009-06", "2009-07"),
    row("n:hope-later", "Residence at Hope St.", "2010-01"),
]


class TheFoldRule(unittest.TestCase):

    def folds(self) -> dict:
        return {r["node_id"]: r for r in lf.fold_candidates(NODES, VIEW)}

    def test_a_landmarks_own_start_or_end_folds_into_it(self) -> None:
        folds = self.folds()
        self.assertEqual((folds["n:into-figers"]["entry_id"], folds["n:into-figers"]["boundary"]),
                         ("residences:figers-house", "start"))
        self.assertEqual(folds["n:out-figers"]["boundary"], "end")
        # "from" names Avenue F's END, not Figers' start.
        self.assertEqual((folds["n:from-avenue"]["entry_id"], folds["n:from-avenue"]["boundary"]),
                         ("residences:avenue-f", "end"))
        self.assertEqual(folds["n:asu"]["entry_id"], "schools:arizona-state-university")
        # A stay given only as a year is matched by that year.
        self.assertEqual(folds["n:apple"]["entry_id"], "work:apple")
        self.assertEqual((folds["n:mission"]["entry_id"], folds["n:mission"]["boundary"]),
                         ("missions:mtc", "start"))
        self.assertEqual(folds["n:departed"]["anchor"], "landmark:missions:mtc:0:start")
        self.assertEqual((folds["n:home"]["entry_id"], folds["n:home"]["boundary"]),
                         ("missions:wetzikon", "end"))
        self.assertEqual(folds["n:into-figers"]["anchor"], "landmark:residences:figers-house:0:start")

    def test_a_state_a_mention_another_person_or_another_date_stays_a_row(self) -> None:
        folds = self.folds()
        for node_id in ("n:arizona", "n:mentions", "n:preparing", "n:aunt", "n:snowboarding",
                        "n:markets", "n:kristen", "n:hope-later"):
            self.assertNotIn(node_id, folds, node_id)

    def test_a_node_that_is_or_restates_a_landmark_folds_into_its_stay(self) -> None:
        folds = self.folds()
        self.assertEqual((folds["node:lm-figers"]["boundary"], folds["node:lm-figers"]["why"]),
                         ("stay", "the landmark's own node"))
        self.assertIsNone(folds["node:lm-figers"]["anchor"])
        self.assertEqual(folds["n:longfellow"]["entry_id"], "schools:longfellow-elementary")
        self.assertEqual((folds["n:hope-st"]["entry_id"], folds["n:hope-st"]["boundary"]),
                         ("residences:hope", "stay"))
        self.assertEqual((folds["n:switzerland"]["domain"], folds["n:switzerland"]["boundary"]),
                         ("missions", "stay"))
        # A misdated "Move to Figers House" inside the stay is still its start.
        self.assertEqual(folds["n:misdated"]["boundary"], "start")

    def test_folding_marks_the_node_and_gives_the_landmark_his_words(self) -> None:
        nodes = json.loads(json.dumps(NODES))
        view = json.loads(json.dumps(VIEW))
        claims = [{"claim_id": "claim:figers", "source_kind": "conversation",
                   "evidence": [{"quote": "We moved to Figers House that August."},
                                {"quote": '"best":"1982-08"'}, {"quote": "residences.span =…"}]},
                  {"claim_id": "claim:derived", "source_kind": "system_derived",
                   "evidence": [{"quote": "spine: Figers House: August 1982"}]}]
        rows = lf.apply_folds(nodes, view, claims=claims)
        self.assertEqual(len(rows), 13)
        own = next(n for n in nodes if n["node_id"] == "node:lm-figers")
        self.assertEqual(own["folded_as"], "restatement")
        self.assertNotIn("folded_boundary", own)
        node = next(n for n in nodes if n["node_id"] == "n:into-figers")
        self.assertEqual(node["folded_into_landmark"], "residences:figers-house")
        self.assertEqual(node["folded_boundary"], "landmark:residences:figers-house:0:start")
        self.assertEqual(len(nodes), len(NODES))  # nothing deleted
        figers = view["domains"][0]["landmarks"][1]
        told = {t["node_id"]: t for t in figers["tellings"]}
        self.assertEqual(told["n:into-figers"]["words"], ["We moved to Figers House that August."])
        self.assertEqual(told["n:out-figers"]["boundary"], "end")
        self.assertEqual(view["fold_rule_version"], lf.LANDMARK_FOLD_RULE_VERSION)
        self.assertEqual({r["node_id"] for r in view["folds"]}, {r["node_id"] for r in rows})

    def test_nothing_to_fold_publishes_as_before(self) -> None:
        view = json.loads(json.dumps(VIEW))
        arizona = next(n for n in NODES if n["node_id"] == "n:arizona")
        self.assertEqual(lf.apply_folds([arizona], view), [])
        self.assertNotIn("folds", view)

    def test_the_anchor_grammar_round_trips(self) -> None:
        anchor = lf.boundary_anchor("residences:figers-house", 1, "end")
        self.assertEqual(lf.parse_boundary_anchor(anchor), ("residences:figers-house", 1, "end"))
        for bad in ("landmark:x:1:middle", "node:abc", "landmark::0:start", "landmark:x:a:start"):
            self.assertIsNone(lf.parse_boundary_anchor(bad), bad)


class ADropAtABoundaryIsInsideWhatStartsOrEndsThere(unittest.TestCase):
    """`drag_tighten.decide` over a hand-built projection."""

    def projection(self) -> dict:
        def node(node_id, earliest, latest):
            return {"node_id": node_id, "node_kind": "event", "label": node_id, "basis": "explicit",
                    "best_temporal_value": {"best": f"{earliest}/{latest}", "earliest": earliest,
                                            "latest": latest}}
        loose = node("n:x", "1981-07", "1994-06")
        loose["basis"] = "calculated"
        return {"nodes": [node("n:p", "1985-01", "1985-01"), node("n:q", "1987-03", "1987-03"), loose],
                "landmarks_view": {"domains": [{"domain": "residences", "landmarks": [
                    {"entry_id": "r:figers", "label": "Figers", "stays": [stay("1982-08", "1986-06")]},
                    {"entry_id": "r:fisches", "label": "Fisches", "stays": [stay("1986-06", "1988-06")]},
                ]}]}}

    def decide(self, *boundaries: str) -> dict:
        return dt.decide(self.projection(), subject_node_id="n:x", relation="between",
                         anchor_node_ids=["n:p", "n:q"], boundary_anchors=boundaries)

    def test_without_a_boundary_it_decides_exactly_as_before(self) -> None:
        decision = self.decide()
        self.assertEqual(decision["window"], {"earliest": "1985-01", "latest": "1987-03"})
        self.assertEqual(decision["boundaries"], [])
        self.assertEqual(decision["rule_version"], "drag-tighten:4")

    def test_below_a_stack_is_inside_what_starts_there(self) -> None:
        decision = self.decide("landmark:r:fisches:0:start")
        self.assertEqual(decision["window"], {"earliest": "1986-06", "latest": "1987-03"})
        self.assertEqual(decision["boundaries"][0]["side"], "start")
        self.assertEqual(decision["boundaries"][0]["month"], "1986-06")
        self.assertIn("Just after Fisches began (Jun 1986).", dt.evidence_sentence(decision))

    def test_above_a_stack_is_inside_what_ends_there_up_to_its_last_month(self) -> None:
        decision = self.decide("landmark:r:figers:0:end")
        self.assertEqual(decision["window"], {"earliest": "1985-01", "latest": "1986-06"})
        self.assertIn("Before Figers ended (Jun 1986).", dt.evidence_sentence(decision))

    def test_an_anchor_naming_no_stay_is_recorded_and_bounds_nothing(self) -> None:
        decision = self.decide("landmark:r:nowhere:0:start")
        self.assertEqual(decision["window"], {"earliest": "1985-01", "latest": "1987-03"})
        self.assertEqual(decision["boundaries_unknown"], ["landmark:r:nowhere:0:start"])


class TheVerbsCarryTheBoundary(DropVault):
    """The real `timeline-move --boundary` argv, and the fold on a publish."""

    def entry_id(self, label: str) -> str:
        view = self.projection()["landmarks_view"]
        return next(l["entry_id"] for d in view["domains"] for l in d["landmarks"] if l["label"] == label)

    def test_a_drop_below_a_start_is_bounded_by_that_start(self) -> None:
        """Between the prom (Apr 1997) and the concert (1999), just below the
        Jun 1997 stack: inside Williams from Jun 1997."""
        anchor = lf.boundary_anchor(self.entry_id("Williams"), 0, "start")
        out = self.move("worry", "between", "prom", "concert", extra=("--boundary", anchor))
        decision = out["tighten"]
        self.assertEqual(decision["outcome"], dt.OUTCOME_TIGHTENED)
        self.assertEqual(decision["window"], {"earliest": "1997-06", "latest": "1999-01"})
        self.assertEqual([b["anchor"] for b in decision["boundaries"]], [anchor])
        best = self.node("worry")["best_temporal_value"]
        self.assertEqual((best["earliest"], best["latest"]), ("1997-06", "1999-01"))
        receipt = json.loads(self.tighten_receipts()[0].read_text())
        self.assertEqual(receipt["extractor"]["boundaries"][0]["anchor"], anchor)

    def test_the_same_drop_without_a_boundary_is_todays_rule(self) -> None:
        out = self.move("worry", "between", "prom", "concert")
        self.assertEqual(out["tighten"]["window"], {"earliest": "1997-04", "latest": "1999-01"})

    def test_a_malformed_boundary_files_nothing(self) -> None:
        argv = [sys.executable, str(SYSTEM / "lifehug.py"), "timeline-move", self.ids["worry"],
                "--relation", "before", "--anchor", self.ids["car"], "--boundary", "landmark:bogus"]
        result = subprocess.run(argv, capture_output=True, text=True, env=self.env, cwd=self.vault,
                                timeout=300, stdin=subprocess.DEVNULL)
        self.assertEqual(result.returncode, 1)
        self.assertIn("not a landmark boundary", result.stderr)
        self.assertEqual(ts.load_ordering_constraints(self.vault), [])

    def test_a_move_into_williams_folds_into_it_on_publish(self) -> None:
        claim = moment("into-williams", "Moved into Williams residence", when("1997-06"), his=True)
        ts.write_receipt(self.vault, {"source_ref": claim["source_ref"],
                                      "extractor_version": "listener:1", "claims": [claim]})
        pub.publish(self.vault, now=NOW, full=True)
        node = self.node_titled("Moved into Williams residence")
        williams = self.entry_id("Williams")
        self.assertEqual(node["folded_into_landmark"], williams)
        self.assertEqual(node["folded_boundary"], f"landmark:{williams}:0:start")
        view = self.projection()["landmarks_view"]
        landmark = next(l for d in view["domains"] for l in d["landmarks"] if l["entry_id"] == williams)
        told = {t["label"]: t for t in landmark["tellings"]}
        self.assertEqual(told["Moved into Williams residence"]["words"], ["Moved into Williams residence."])
        # The landmark's own node (its stay, drawn as a row until now) folds too.
        self.assertEqual(told["Williams"]["boundary"], "stay")
        # Every other moment is untouched.
        self.assertNotIn("folded_into_landmark", self.node("worry"))


if __name__ == "__main__":
    unittest.main()
