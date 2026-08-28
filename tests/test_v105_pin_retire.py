"""v105 — caught-up pins retire automatically.

Once the re-derived classification places a pinned moment in its period by
itself, the weekly `timeline-retire` step removes the pin (moving it to the
placements file's `retired` list, correction link intact). The filed date
assertion is the durable information; nothing is lost. Orphaned pins never
auto-retire — they stay surfaced as stale notices for the owner.

v253 (lifehug#276) narrowed what "orphaned" means, and this file records the
change. Until v253 a pin whose moment had merely been RECLASSIFIED counted as
orphaned forever, because the identity is content-addressed and the classifier
rewrites descriptions every week. `resolve_placements`' third rung re-keys such
a pin to the one live moment its source mints, so the pin is now judged like
any other: it retires when the loop has caught up with it and stays when the
owner is still overriding the heuristic. Genuinely orphaned pins — the source
mints no live moment, or it mints several and the repair refuses to guess, or
the period page is gone — still never retire.
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

    def test_a_reclassified_moment_is_re_keyed_and_then_judged_normally(self):
        """v253: a rewritten description is not an orphan. The pin re-keys to
        the one live moment its source mints, and then the ordinary rule
        applies — here the heuristic agrees with the pin, so the loop has
        caught up and the pin retires with its correction intact. Before v253
        this pin survived every weekly pass forever, pinning nothing."""
        e = event("The old description", when_hint="in college")
        key = self._pin(e, "college")
        rewritten = event("A rewritten description", when_hint="in college")
        self.assertNotEqual(tl.placement_key(rewritten), key,
                            "the fixture must actually move the key")
        retired = self._retire([rewritten])
        self.assertEqual([r["description"] for r in retired],
                         ["The old description"])
        self.assertEqual(retired[0]["correction"], "sources/corrections/c1.md")
        self.assertEqual(tl.load_placements()["placements"], [])

    def test_a_reclassified_pin_the_owner_still_overrides_stays(self):
        """Re-keying is not retirement. A pin whose period still disagrees with
        the heuristic keeps doing its job under its moment's new identity."""
        e = event("The old description", when_hint="in college")
        self._pin(e, "childhood")
        rewritten = event("A rewritten description", when_hint="in college")
        self.assertEqual(self._retire([rewritten]), [])
        self.assertEqual(len(tl.load_placements()["placements"]), 1)

    def test_an_ambiguous_orphan_never_retires(self):
        """Two live moments of one source: the repair refuses to guess, so the
        pin is still orphaned and still never auto-retires."""
        e = event("The old description", when_hint="in college")
        self._pin(e, "college")
        rewritten = event("A rewritten description", when_hint="in college")
        other = event("Something else entirely", when_hint="in college")
        self.assertEqual(self._retire([rewritten, other]), [])
        self.assertEqual(len(tl.load_placements()["placements"]), 1)

    def test_a_pin_whose_source_is_gone_never_retires(self):
        """Nothing to re-key to at all — the v105 shape, unchanged."""
        e = event("The old description", when_hint="in college")
        self._pin(e, "college")
        survivor = event("A moment from another answer", source="answers/Q9.md",
                         when_hint="in college")
        self.assertEqual(self._retire([survivor]), [])
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
