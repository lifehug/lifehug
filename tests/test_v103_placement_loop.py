"""v103 — placement feeds the Loop.

Placing a timeline moment always files a date-kind correction (the pin in
state/timeline_placements.json is display-only; the correction is the
information), and any correction marks its target's classification stale so
the weekly batch re-derives events/people/themes from the corrected facts.
"""

import json
import io
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SYSTEM = ROOT / "system"
sys.path.insert(0, str(SYSTEM))

import classify_story as cs  # noqa: E402
import lifehug  # noqa: E402
import source_integrity as si  # noqa: E402
import timeline as tl  # noqa: E402
from lifehug_core import write_json  # noqa: E402

PERIODS = [
    {"slug": "childhood", "name": "Childhood", "chrono": 1,
     "sources": set(), "page": None, "approximate_dates": ""},
    {"slug": "college", "name": "College", "chrono": 2,
     "sources": set(), "page": None, "approximate_dates": ""},
]


def event(desc, source="answers/Z1.md", when_hint="", eras=None):
    return {"description": desc, "when_hint": when_hint, "anchor": "",
            "source": source, "source_short": Path(source).stem,
            "eras": eras or []}


class PlaceFilesAssertionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: __import__("shutil").rmtree(self.tmp, ignore_errors=True))
        self._orig = tl.PLACEMENTS_FILE
        tl.PLACEMENTS_FILE = self.tmp / "placements.json"
        self.addCleanup(lambda: setattr(tl, "PLACEMENTS_FILE", self._orig))

    def _place(self, cli_rc=0,
               cli_out="✓ Created correction source: sources/corrections/c1.md",
               when_hint="summer of first grade"):
        calls = []

        def fake_run(args, **kwargs):
            calls.append((args, kwargs))
            return __import__("subprocess").CompletedProcess(args, cli_rc, cli_out, "")

        args = type("Args", (), {
            "source": "answers/Z1.md", "period": "childhood",
            "when_hint": when_hint, "note": "",
        })()
        with mock.patch.object(lifehug.subprocess, "run", fake_run), \
                mock.patch.object(tl, "load_periods",
                                  lambda: [{"slug": "childhood", "name": "Childhood"}]), \
                mock.patch("sys.stdin", io.StringIO("The porch dog summer")):
            result = lifehug.cmd_timeline_place(args)
        return result, calls

    def test_place_always_files_date_assertion(self):
        result, calls = self._place()
        self.assertEqual(result, 0)
        self.assertEqual(len(calls), 1)
        args, kwargs = calls[0]
        self.assertTrue(str(args[1]).endswith("source_integrity.py"))
        self.assertEqual(args[2:4], ["correct", "answers/Z1.md"])
        right = kwargs["input"]
        # v251: the body is the DATE DECISION and nothing else — the person's
        # own words for when, never the era the pin lands in. The era is
        # information the ROW carries (`period`, read by rung 0); asserting it
        # in an immutable source record made a derived name as authoritative as
        # a stated date. See `timeline.placement_assertion`.
        self.assertIn("summer of first grade", right)
        self.assertNotIn("Childhood", right)
        self.assertNotIn("during", right)
        self.assertEqual(args[args.index("--kind") + 1], "date")
        rec = tl.load_placements()["placements"][0]
        self.assertEqual(rec["correction"], "sources/corrections/c1.md")

    def test_place_without_when_hint_still_files(self):
        """A period-only pin still files its durable half — and now says the
        honest thing, which is that no date was stated. It used to state the
        era as fact, and that was the ONLY temporal thing it said."""
        result, calls = self._place(when_hint="")
        self.assertEqual(result, 0)
        right = calls[0][1]["input"]
        self.assertIn("The porch dog summer", right)
        self.assertIn("I stated no date", right)
        self.assertNotIn("Childhood", right)

    def test_cli_failure_does_not_create_pin(self):
        result, _ = self._place(cli_rc=1, cli_out="boom")
        self.assertEqual(result, 1)
        self.assertEqual(tl.load_placements()["placements"], [])

    def test_unplace_mentions_surviving_assertion(self):
        self._place()
        key = tl.load_placements()["placements"][0]["key"]
        args = type("Args", (), {"key": key})()
        with mock.patch("sys.stdout", new_callable=io.StringIO) as stdout:
            result = lifehug.cmd_timeline_unplace(args)
        self.assertEqual(result, 0)
        self.assertIn("Placement removed", stdout.getvalue())
        self.assertIn("assertion remains", stdout.getvalue())
        self.assertIn("sources/corrections/c1.md", stdout.getvalue())
        self.assertEqual(tl.load_placements()["placements"], [])


class RedundantPinTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: __import__("shutil").rmtree(self.tmp, ignore_errors=True))
        self._orig = tl.PLACEMENTS_FILE
        tl.PLACEMENTS_FILE = self.tmp / "placements.json"
        self.addCleanup(lambda: setattr(tl, "PLACEMENTS_FILE", self._orig))

    def test_pin_matching_heuristic_is_redundant(self):
        e = event("Campus rain", when_hint="in college")
        key = tl.placement_key(e)
        tl.save_placement(key, e["source"], e["description"], "college",
                          correction="sources/corrections/c1.md")
        placed, _ = tl.place_events([e], PERIODS, tl.load_placements())
        got = placed["college"][0]
        self.assertTrue(got["placement_redundant"])  # the loop caught up
        self.assertEqual(got["placement_correction"], "sources/corrections/c1.md")

    def test_pin_overriding_heuristic_is_not_redundant(self):
        e = event("First bike", when_hint="my college years")
        key = tl.placement_key(e)
        tl.save_placement(key, e["source"], e["description"], "childhood")
        placed, _ = tl.place_events([e], PERIODS, tl.load_placements())
        got = placed["childhood"][0]
        self.assertFalse(got["placement_redundant"])


class StaleClassificationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: __import__("shutil").rmtree(self.tmp, ignore_errors=True))
        self._orig = cs.CLASSIFICATIONS_DIR
        cs.CLASSIFICATIONS_DIR = self.tmp / "classifications"
        cs.CLASSIFICATIONS_DIR.mkdir()
        self.addCleanup(lambda: setattr(cs, "CLASSIFICATIONS_DIR", self._orig))
        self.target = self.tmp / "N10.md"
        self.target.write_text("# story\n", encoding="utf-8")
        self.clf = cs.classification_path(self.target)

    def test_mark_stale_flips_is_classified(self):
        write_json(self.clf, {"events": []})
        self.assertTrue(cs.is_classified(self.target))
        self.assertTrue(cs.mark_stale(self.target, "correction filed: sources/corrections/c1.md"))
        data = json.loads(self.clf.read_text(encoding="utf-8"))
        self.assertTrue(data["stale"])
        self.assertIn("correction filed", data["stale_reason"])
        self.assertTrue(data["stale_at"])
        self.assertFalse(cs.is_classified(self.target))  # now counts as work

    def test_mark_stale_without_classification_returns_false(self):
        self.assertFalse(cs.mark_stale(self.target, "x"))
        self.assertFalse(cs.is_classified(self.target))

    def test_fresh_rewrite_clears_stale(self):
        write_json(self.clf, {"events": []})
        cs.mark_stale(self.target, "x")
        write_json(self.clf, {"events": [], "model": "m"})  # re-classification
        self.assertTrue(cs.is_classified(self.target))


class CorrectionMarksStaleTests(unittest.TestCase):
    """Integration through source_integrity: filing a correction (any kind)
    marks the target's classification stale; reflections do not."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: __import__("shutil").rmtree(self.tmp, ignore_errors=True))
        self.target = self.tmp / "N10.md"
        self.target.write_text(
            '---\ntype: "prompted_answer"\nsource_id: "answer:N10"\n---\n\n# Q\n\nmoved in 2006\n',
            encoding="utf-8")
        self._orig = cs.CLASSIFICATIONS_DIR
        cs.CLASSIFICATIONS_DIR = self.tmp / "classifications"
        cs.CLASSIFICATIONS_DIR.mkdir()
        self.addCleanup(lambda: setattr(cs, "CLASSIFICATIONS_DIR", self._orig))
        self.clf = cs.classification_path(self.target)
        write_json(self.clf, {"events": [{"description": "the move", "when_hint": ""}]})

    def _create(self, source_type):
        with mock.patch.object(si, "SOURCES_DIR", self.tmp), \
                mock.patch.object(si, "CORRECTION_SOURCES_DIR", self.tmp / "corrections"), \
                mock.patch.object(si, "resolve_source_target", lambda v: self.target), \
                mock.patch.object(si, "register_source", lambda p: {}):
            return si.create_linked_source(
                "answers/N10.md", "It was 2004, not 2006.",
                source_type=source_type, title=None, source_medium="fix",
                correction_kind="date")

    def test_correction_marks_target_classification_stale(self):
        path = self._create("source_correction")
        data = json.loads(self.clf.read_text(encoding="utf-8"))
        self.assertTrue(data.get("stale"))
        self.assertIn(path.name, data.get("stale_reason", ""))
        self.assertFalse(cs.is_classified(self.target))

    def test_reflection_does_not_mark_stale(self):
        self._create("source_reflection")
        data = json.loads(self.clf.read_text(encoding="utf-8"))
        self.assertFalse(data.get("stale"))
        self.assertTrue(cs.is_classified(self.target))


if __name__ == "__main__":
    unittest.main()
