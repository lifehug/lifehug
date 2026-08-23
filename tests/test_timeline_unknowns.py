"""v195 / ADR 0024 — unknowns, leverage, keystones, and the deferred memory.

Every gap becomes a Play-able unknown carrying the playbook's cheapest probe;
a dated hole between dated eras is the new `era_gap` kind; leverage counts
what one anchor would resolve; keystones are capped at two; and a deferred
unknown goes quiet without ever being counted as outstanding.

Synthetic data only; NEVER references ~/Workspace/dave.
"""

from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SYSTEM = ROOT / "system"
sys.path.insert(0, str(SYSTEM))

import chronology as chrono  # noqa: E402
import timeline_interaction as ti  # noqa: E402


def load(name):
    spec = importlib.util.spec_from_file_location(name, SYSTEM / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    orig = sys.modules.get(name)
    sys.modules[name] = mod
    try:
        spec.loader.exec_module(mod)
    finally:
        if orig is not None:
            sys.modules[name] = orig
        else:
            sys.modules.pop(name, None)
    return mod


tl = load("timeline")

PAGE = """---
title: "{title}"
type: {page_type}
chrono: {chrono}
{extra}sources:
{sources}---

# {title}
"""


def _sources(refs):
    return "".join(f'  - "answers/{ref}.md"\n' for ref in refs)


class UnknownsFixture(unittest.TestCase):
    """Two dated eras twelve years apart with nothing between them, one
    undated era, one place, and two events — one dated, one not."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.root = root
        (root / "wiki" / "periods").mkdir(parents=True)
        (root / "wiki" / "places").mkdir(parents=True)
        (root / "sources" / "manual").mkdir(parents=True)
        (root / "state" / "classifications").mkdir(parents=True)
        (root / "state" / "entity_rosters").mkdir()
        (root / "state" / "connectors").mkdir()

        (root / "wiki" / "periods" / "childhood.md").write_text(
            PAGE.format(title="Childhood", page_type="period", chrono=1,
                        extra="date: 1984/1990\n", sources=_sources(["A1"])),
            encoding="utf-8")
        (root / "wiki" / "periods" / "my-30s.md").write_text(
            PAGE.format(title="My 30s", page_type="period", chrono=2,
                        extra="date: 2002/2012\n", sources=_sources(["A2"])),
            encoding="utf-8")
        (root / "wiki" / "periods" / "the-lost-years.md").write_text(
            PAGE.format(title="The Lost Years", page_type="period", chrono=3,
                        extra="", sources=_sources([])),
            encoding="utf-8")
        (root / "wiki" / "places" / "mesa.md").write_text(
            PAGE.format(title="Mesa", page_type="place", chrono=0,
                        extra="date: 1984/1990\n", sources=_sources(["A1"])),
            encoding="utf-8")
        (root / "state" / "entity_rosters" / "period.json").write_text(json.dumps({
            "version": 1, "type": "period", "entities": [
                {"name": "Childhood", "slug": "childhood", "chrono": 1,
                 "page_eligible": True, "date": "1984/1990"},
                {"name": "My 30s", "slug": "my-30s", "chrono": 2,
                 "page_eligible": True, "date": "2002/2012"},
                {"name": "The Lost Years", "slug": "the-lost-years", "chrono": 3,
                 "page_eligible": True},
            ]}), encoding="utf-8")
        (root / "state" / "classifications" / "answers-a1.json").write_text(json.dumps({
            "source_path": "answers/A1.md",
            "events": [
                {"title": "The move to Mesa", "description": "We moved to Mesa.",
                 "when_hint": "", "anchor": None, "date": {"stated": "1984"}},
                {"title": "The bike with no brakes",
                 "description": "I rode a bike with no brakes.",
                 "when_hint": "", "anchor": None, "date": None},
            ]}), encoding="utf-8")
        (root / "state" / "classifications" / "answers-a2.json").write_text(json.dumps({
            "source_path": "answers/A2.md",
            "events": [
                {"title": "The coast house", "description": "We bought the coast house.",
                 "when_hint": "", "anchor": None, "date": {"stated": "2008"}},
            ]}), encoding="utf-8")

        self._orig = {name: getattr(tl, name) for name in tl.VAULT_ROOT_NAMES}
        state = root / "state"
        for name, value in {
            "CLASSIFICATIONS_DIR": state / "classifications",
            "CONNECTORS_STATE_DIR": state / "connectors",
            "DEFERRED_FILE": state / "timeline_deferred.json",
            "ENTITY_ROSTERS_DIR": state / "entity_rosters",
            "MANUAL_SOURCES_DIR": root / "sources" / "manual",
            "PLACEMENTS_FILE": state / "timeline_placements.json",
            "STATE_DIR": state,
            "WIKI_DIR": root / "wiki",
        }.items():
            setattr(tl, name, value)
        self.data = tl.timeline_data()

    def tearDown(self):
        for name, value in self._orig.items():
            setattr(tl, name, value)
        self.tmp.cleanup()


class UnknownRecordTests(UnknownsFixture):
    def test_every_gap_becomes_exactly_one_play_able_unknown(self):
        rows = self.data["unknowns"]
        self.assertTrue(rows)
        self.assertEqual(len(rows), len({row["key"] for row in rows}))
        for row in rows:
            self.assertIn(row["kind"], tl.UNKNOWN_KINDS)
            self.assertTrue(row["label"])
            self.assertIn(row["probe"]["step"], ti.PLAYBOOK_ORDER)
            self.assertTrue(row["probe"]["text"])

    def test_the_keys_are_stable_and_content_derived(self):
        first = {row["key"] for row in tl.unknowns(self.data)}
        second = {row["key"] for row in tl.unknowns(self.data)}
        self.assertEqual(first, second)
        self.assertIn("no_events:the-lost-years", first)

    def test_an_era_gap_is_emitted_between_two_dated_eras(self):
        keys = {row["key"] for row in self.data["unknowns"]}
        self.assertIn("era_gap:childhood:my-30s", keys)
        row = next(r for r in self.data["unknowns"] if r["key"] == "era_gap:childhood:my-30s")
        self.assertEqual(row["years"], [1991, 2001])
        self.assertIn("1991–2001", row["label"])

    def test_no_era_gap_when_a_neighbour_is_undated(self):
        periods = [{"slug": "a", "name": "A", "date": chrono.parse_edtf("1984/1990")},
                   {"slug": "b", "name": "B", "date": None}]
        self.assertEqual(tl.era_gaps(periods, {}), [])

    def test_no_era_gap_when_the_eras_touch(self):
        periods = [{"slug": "a", "name": "A", "date": chrono.parse_edtf("1984/1990")},
                   {"slug": "b", "name": "B", "date": chrono.parse_edtf("1991/1999")}]
        self.assertEqual(tl.era_gaps(periods, {}), [])

    def test_an_occupied_hole_is_not_a_gap(self):
        periods = [{"slug": "a", "name": "A", "date": chrono.parse_edtf("1984/1990")},
                   {"slug": "b", "name": "B", "date": chrono.parse_edtf("2002/2012")}]
        lineup = {"a": [{"date": chrono.parse_edtf("1995"), "source_short": "A9"}]}
        self.assertEqual(tl.era_gaps(periods, lineup), [])


class LeverageTests(UnknownsFixture):
    def test_a_period_anchor_resolves_its_own_unknowns_and_the_eras_it_touches(self):
        index = tl.dependency_index(self.data)
        self.assertIn("period:childhood", index)
        self.assertIn("era_gap:childhood:my-30s", index["period:childhood"])
        self.assertGreater(tl.leverage("period:childhood", index), 0)

    def test_leverage_of_an_unknown_anchor_is_zero(self):
        self.assertEqual(tl.leverage("period:nowhere", tl.dependency_index(self.data)), 0)

    def test_keystones_are_capped_at_two_and_ordered_by_leverage(self):
        rows = self.data["keystones"]
        self.assertLessEqual(len(rows), tl.KEYSTONE_CAP)
        self.assertEqual(tl.KEYSTONE_CAP, 2)
        self.assertEqual([r["leverage"] for r in rows],
                         sorted((r["leverage"] for r in rows), reverse=True))
        for row in rows:
            self.assertTrue(row["probe"]["text"])

    def test_keystone_slugs_name_the_thing_behind_the_anchor(self):
        slugs = tl.keystone_slugs(self.data)
        self.assertTrue(slugs)
        self.assertTrue(all(":" not in slug for slug in slugs))

    def test_asking_for_no_keystones_returns_none(self):
        self.assertEqual(tl.keystones(self.data, n=0), [])


class DeferredMemoryTests(UnknownsFixture):
    def test_a_deferral_is_recorded_and_honoured(self):
        key = "era_gap:childhood:my-30s"
        self.assertFalse(tl.is_deferred(key))
        tl.defer_unknown(key)
        self.assertTrue(tl.is_deferred(key))

    def test_deferring_twice_refreshes_rather_than_duplicates(self):
        tl.defer_unknown("k")
        tl.defer_unknown("k")
        self.assertEqual(len(tl.load_deferred()["deferred"]), 1)

    def test_the_quiet_window_expires(self):
        tl.defer_unknown("k")
        later = datetime.now(timezone.utc) + timedelta(days=tl.DEFERRED_QUIET_DAYS + 1)
        self.assertFalse(tl.is_deferred("k", now=later))

    def test_a_corrupt_stamp_keeps_the_unknown_quiet_rather_than_nagging(self):
        path = tl.DEFERRED_FILE
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"version": 1, "deferred": [
            {"key": "k", "deferred_at": "not-a-time"}]}), encoding="utf-8")
        self.assertTrue(tl.is_deferred("k"))

    def test_a_deferred_unknown_is_marked_and_gets_the_defer_probe(self):
        key = "era_gap:childhood:my-30s"
        tl.defer_unknown(key)
        row = next(r for r in tl.unknowns(tl.timeline_data()) if r["key"] == key)
        self.assertTrue(row["deferred"])
        self.assertEqual(row["probe"]["step"], "defer")

    def test_a_deferred_unknown_is_never_offered_but_is_still_listed(self):
        key = "era_gap:childhood:my-30s"
        tl.defer_unknown(key)
        plan = ti.build_timeline_plan(tl.timeline_data())
        self.assertNotIn(key, [row["key"] for row in plan["offered"]])
        self.assertIn(key, [row["key"] for row in plan["deferred"]])
        self.assertIn(key, [row["key"] for row in plan["unknowns"]])


class TimelinePlanTests(UnknownsFixture):
    def test_the_plan_orders_by_leverage_then_playbook_cost(self):
        plan = ti.build_timeline_plan(self.data)
        offered = plan["offered"]
        self.assertTrue(offered)
        keys = [(not row["starred"], -row["leverage"], row["probe"]["cost"]) for row in offered]
        self.assertEqual(keys, sorted(keys))

    def test_era_scoping_keeps_only_that_eras_unknowns(self):
        plan = ti.build_timeline_plan(self.data, era="the-lost-years")
        self.assertTrue(plan["unknowns"])
        for row in plan["unknowns"]:
            self.assertIn("the-lost-years",
                          [row.get("period")] + list(row.get("between") or []))

    def test_the_target_is_a_timeline_target_not_an_arc_walk_one(self):
        self.assertEqual(ti.build_timeline_plan(self.data)["target"]["kind"], "timeline")

    def test_describe_renders_every_offered_row_with_its_probe(self):
        lines = "\n".join(ti.describe_timeline_plan(ti.build_timeline_plan(self.data)))
        self.assertIn("Timeline plan", lines)
        self.assertIn("probe (", lines)


class PlannerLeverageBoostTests(unittest.TestCase):
    def setUp(self):
        self.qp = load("question_planner")

    def test_the_knob_ships_with_a_modest_default(self):
        self.assertEqual(self.qp.DEFAULT_LANE_POLICY["leverage_boost"], 1.2)

    def test_an_empty_keystone_set_leaves_the_week_byte_identical(self):
        without = self.qp.build_queue(limit=8, arc_max=2, seed=11)
        with_empty = self.qp.build_queue(limit=8, arc_max=2, seed=11, keystone_slugs=())
        self.assertEqual([q["question_id"] for q in without["queue"]],
                         [q["question_id"] for q in with_empty["queue"]])
        self.assertEqual(with_empty["allocation"]["leverage"]["matched"], 0)

    def test_keystone_slugs_are_reported_and_only_matching_questions_are_marked(self):
        data = self.qp.build_queue(limit=8, arc_max=2, seed=11,
                                   keystone_slugs=["definitely-not-a-real-focus"])
        leverage = data["allocation"]["leverage"]
        self.assertEqual(leverage["keystones"], ["definitely-not-a-real-focus"])
        self.assertEqual(leverage["matched"], 0)
        self.assertEqual(leverage["boost"], self.qp.DEFAULT_LANE_POLICY["leverage_boost"])

    def test_the_guarded_read_never_raises(self):
        original = sys.modules.get("timeline")
        sys.modules["timeline"] = object()  # a module with no keystone_slugs
        try:
            self.assertEqual(self.qp.current_keystone_slugs(), ())
        finally:
            if original is None:
                sys.modules.pop("timeline", None)
            else:
                sys.modules["timeline"] = original


if __name__ == "__main__":
    unittest.main()
