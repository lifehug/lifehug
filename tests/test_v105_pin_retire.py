"""v105 — caught-up pins retire automatically.

Once the re-derived classification places a pinned moment in its period by
itself, the weekly `timeline-retire` step removes the pin (moving it to the
placements file's `retired` list, correction link intact). The filed date
assertion is the durable information; nothing is lost. Orphaned pins (event
rewritten, period gone) never auto-retire — they stay surfaced as stale
notices for the owner.
"""

import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SYSTEM = ROOT / "system"
sys.path.insert(0, str(SYSTEM))

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


class RetireRedundantPlacementsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: __import__("shutil").rmtree(self.tmp, ignore_errors=True))
        self._orig = tl.PLACEMENTS_FILE
        tl.PLACEMENTS_FILE = self.tmp / "placements.json"
        self.addCleanup(lambda: setattr(tl, "PLACEMENTS_FILE", self._orig))

    def _retire(self, events, dry_run=False):
        with mock.patch.object(tl, "load_periods", lambda: PERIODS), \
                mock.patch.object(tl, "load_events", lambda: events):
            return tl.retire_redundant_placements(dry_run=dry_run)

    def _pin(self, e, period, correction="sources/corrections/c1.md"):
        key = tl.placement_key(e)
        tl.save_placement(key, e["source"], e["description"], period,
                          correction=correction)
        return key

    def test_caught_up_pin_retires(self):
        e = event("Campus rain", when_hint="in college")
        self._pin(e, "college")
        retired = self._retire([e])
        self.assertEqual(len(retired), 1)
        self.assertEqual(retired[0]["description"], "Campus rain")
        self.assertEqual(retired[0]["correction"], "sources/corrections/c1.md")
        self.assertTrue(retired[0]["retired_at"])
        data = tl.load_placements()
        self.assertEqual(data["placements"], [])  # pin is gone
        self.assertEqual(len(data["retired"]), 1)  # provenance survives
        # And the event still renders in its period, sans pin.
        placed, _ = tl.place_events([e], PERIODS, data)
        self.assertEqual(len(placed["college"]), 1)
        self.assertNotEqual(placed["college"][0].get("placement"), "manual")

    def test_overriding_pin_stays(self):
        e = event("First bike", when_hint="my college years")
        self._pin(e, "childhood")  # owner disagrees with the heuristic
        self.assertEqual(self._retire([e]), [])
        self.assertEqual(len(tl.load_placements()["placements"]), 1)

    def test_orphaned_pin_never_retires(self):
        e = event("The old description", when_hint="in college")
        self._pin(e, "college")
        rewritten = event("A rewritten description", when_hint="in college")
        self.assertEqual(self._retire([rewritten]), [])
        self.assertEqual(len(tl.load_placements()["placements"]), 1)

    def test_pin_on_vanished_period_never_retires(self):
        e = event("Campus rain", when_hint="in college")
        self._pin(e, "mission-years")  # period page no longer exists
        self.assertEqual(self._retire([e]), [])
        self.assertEqual(len(tl.load_placements()["placements"]), 1)

    def test_dry_run_reports_but_writes_nothing(self):
        e = event("Campus rain", when_hint="in college")
        self._pin(e, "college")
        retired = self._retire([e], dry_run=True)
        self.assertEqual(len(retired), 1)
        data = tl.load_placements()
        self.assertEqual(len(data["placements"]), 1)  # untouched
        self.assertEqual(data["retired"], [])

    def test_mixed_pins_only_caught_up_one_retires(self):
        caught = event("Campus rain", when_hint="in college")
        held = event("First bike", when_hint="my college years")
        self._pin(caught, "college")
        self._pin(held, "childhood", correction="")
        retired = self._retire([caught, held])
        self.assertEqual([r["description"] for r in retired], ["Campus rain"])
        data = tl.load_placements()
        self.assertEqual([p["description"] for p in data["placements"]],
                         ["First bike"])


if __name__ == "__main__":
    unittest.main()
