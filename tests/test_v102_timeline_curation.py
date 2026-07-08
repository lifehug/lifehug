"""Tests for interactive timeline curation (v102): the manual placement
overlay, stale detection, viewer actions, and the timeline.md export."""

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SYSTEM = ROOT / "system"
sys.path.insert(0, str(SYSTEM))

import serve_wiki  # noqa: E402
import timeline as tl  # noqa: E402


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


class PlacementLayerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self._orig = tl.PLACEMENTS_FILE
        tl.PLACEMENTS_FILE = self.tmp / "timeline_placements.json"

    def tearDown(self):
        tl.PLACEMENTS_FILE = self._orig

    def test_key_is_stable_and_content_derived(self):
        e = event("The porch dog summer")
        self.assertEqual(tl.placement_key(e), tl.placement_key(dict(e)))
        self.assertNotEqual(tl.placement_key(e),
                            tl.placement_key(event("A different moment")))
        self.assertEqual(len(tl.placement_key(e)), 12)

    def test_save_replace_remove_roundtrip(self):
        e = event("The porch dog summer")
        key = tl.placement_key(e)
        tl.save_placement(key, e["source"], e["description"], "childhood")
        tl.save_placement(key, e["source"], e["description"], "college",
                          when_hint="freshman year")
        data = tl.load_placements()
        self.assertEqual(len(data["placements"]), 1)  # replaced, not duplicated
        self.assertEqual(data["placements"][0]["period"], "college")
        self.assertTrue(tl.remove_placement(key))
        self.assertFalse(tl.remove_placement(key))
        self.assertEqual(tl.load_placements()["placements"], [])

    def test_manual_placement_wins_and_overrides_when_hint(self):
        # "college" keyword would place this in college; the owner says childhood.
        e = event("First bike", when_hint="my college years")
        key = tl.placement_key(e)
        tl.save_placement(key, e["source"], e["description"], "childhood",
                          when_hint="the summer I turned six")
        placed, unplaced = tl.place_events([e], PERIODS, tl.load_placements())
        self.assertEqual(unplaced, [])
        self.assertEqual(len(placed["childhood"]), 1)
        got = placed["childhood"][0]
        self.assertEqual(got["placement"], "manual")
        self.assertEqual(got["placement_key"], key)
        self.assertEqual(got["when_hint"], "the summer I turned six")
        # The original event dict is untouched (overlay copies).
        self.assertNotIn("placement", e)

    def test_default_arg_keeps_old_behavior(self):
        e = event("Campus rain", when_hint="in college")
        placed, unplaced = tl.place_events([e], PERIODS)
        self.assertEqual(len(placed["college"]), 1)
        self.assertNotIn("placement", placed["college"][0])

    def test_placement_for_unknown_period_is_ignored(self):
        e = event("Lost moment")
        key = tl.placement_key(e)
        tl.save_placement(key, e["source"], e["description"], "gone-era")
        placed, unplaced = tl.place_events([e], PERIODS, tl.load_placements())
        self.assertEqual(len(unplaced), 1)  # falls through to heuristics


class StaleDetectionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self._saved = {name: getattr(tl, name) for name in
                       ("PLACEMENTS_FILE", "CLASSIFICATIONS_DIR", "WIKI_DIR",
                        "STATE_DIR", "MANUAL_SOURCES_DIR")}
        tl.PLACEMENTS_FILE = self.tmp / "placements.json"
        tl.CLASSIFICATIONS_DIR = self.tmp / "classifications"
        tl.WIKI_DIR = self.tmp / "wiki"
        tl.STATE_DIR = self.tmp / "state"
        tl.MANUAL_SOURCES_DIR = self.tmp / "manual"
        (self.tmp / "classifications").mkdir()
        (self.tmp / "classifications" / "answers-z1.json").write_text(json.dumps({
            "source_path": "answers/Z1.md",
            "events": [{"description": "The porch dog summer", "when_hint": "", "anchor": ""}],
        }))

    def tearDown(self):
        for name, val in self._saved.items():
            setattr(tl, name, val)

    def test_orphaned_placement_surfaces_as_stale(self):
        live = event("The porch dog summer", source="answers/Z1.md")
        tl.save_placement(tl.placement_key(live), live["source"],
                          live["description"], "some-era")
        tl.save_placement("deadbeef0000", "answers/OLD.md",
                          "A rewritten description", "some-era")
        data = tl.timeline_data()
        stale_keys = {p["key"] for p in data["stale_placements"]}
        # The dead key is stale; the live one is stale only because its
        # period page doesn't exist in this fixture — both surfaced, never
        # silently misapplied.
        self.assertIn("deadbeef0000", stale_keys)


class TimelineActionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self._orig = tl.PLACEMENTS_FILE
        tl.PLACEMENTS_FILE = self.tmp / "placements.json"

    def tearDown(self):
        tl.PLACEMENTS_FILE = self._orig

    def test_place_action_saves_and_unplace_removes(self):
        # v103: placing always files a date assertion via the CLI — stub it.
        with mock.patch.object(serve_wiki, "_run_cli",
                               lambda *a, **k: (0, "✓ Created correction source: sources/corrections/c.md")), \
                mock.patch.object(tl, "load_periods", lambda: []):
            redirect, flash, job = serve_wiki.act_timeline_place({
                "source": ["answers/Z1.md"], "description": ["The porch dog summer"],
                "period": ["childhood"], "when_hint": ["summer of first grade"],
            })
        self.assertIn("✓ placed in Childhood", flash)
        self.assertIsNone(job)
        data = tl.load_placements()
        self.assertEqual(len(data["placements"]), 1)
        key = data["placements"][0]["key"]
        redirect, flash, _ = serve_wiki.act_timeline_unplace({"key": [key]})
        self.assertIn("✓ placement removed", flash)
        self.assertEqual(tl.load_placements()["placements"], [])

    def test_place_action_requires_period(self):
        _, flash, _ = serve_wiki.act_timeline_place({
            "source": ["answers/Z1.md"], "description": ["x"], "period": [""]})
        self.assertIn("✗", flash)
        self.assertEqual(tl.load_placements()["placements"], [])


if __name__ == "__main__":
    unittest.main()
