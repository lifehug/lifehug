"""v425 (ADR 0046 amendment 2026-10-20, lifehug#497) — a Focus at 100% rests
whoever selected it; Keep going and a re-add at the target raise the tier.

The owner's rulings (2026-10-19): "keep going will need to raise the tier and
if I want to add it again we'll need to raise the tier", and "if I want to keep
adding it as a focus we keep raising the tier proportional to what I size it".
Every fixture is SYNTHETIC (Katie, invented); nothing is copied from any real
vault.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SYSTEM = ROOT / "system"
sys.path.insert(0, str(SYSTEM))
sys.path.insert(0, str(ROOT / "tests"))

import focus_complete as fc  # noqa: E402
import focus_selection as fs  # noqa: E402
import roadmap  # noqa: E402
import serve_wiki  # noqa: E402
from tempdirs import root_parent_tmp  # noqa: E402
from test_v394_focus_complete import PRIMARY, Base, bank, katie  # noqa: E402

NOW = "2026-10-20T15:00:00Z"


class RaiseTier(unittest.TestCase):
    def raised(self, **focus):
        f = dict(focus)
        return roadmap.raise_tier(f), f

    def test_basic_to_standard(self):
        out, f = self.raised(tier="basic", target_depth=8)
        self.assertEqual(out, {"tier": "standard", "target_depth": 20,
                               "was": {"tier": "basic", "target_depth": 8}})
        self.assertEqual((f["tier"], f["target_depth"]), ("standard", 20))

    def test_standard_to_extreme(self):
        out, _ = self.raised(tier="standard", target_depth=20)
        self.assertEqual((out["tier"], out["target_depth"]), ("extreme", 50))

    def test_extreme_is_not_a_ceiling(self):
        out, f = self.raised(tier="extreme", target_depth=50)
        self.assertEqual((out["tier"], out["target_depth"]), ("extreme", 100))
        out = roadmap.raise_tier(f)
        self.assertEqual((out["tier"], out["target_depth"]), ("extreme", 150))
        self.assertEqual(out["was"], {"tier": "extreme", "target_depth": 100})

    def test_the_whole_ladder(self):
        f = {"tier": "basic", "target_depth": 8}
        seen = [roadmap.raise_tier(f)["target_depth"] for _ in range(5)]
        self.assertEqual(seen, [20, 50, 100, 150, 200])

    def test_an_owner_set_target_is_never_lowered(self):
        # max(next tier's base, target + current tier's base)
        self.assertEqual(self.raised(tier="standard", target_depth=30)[0]["target_depth"], 50)
        self.assertEqual(self.raised(tier="basic", target_depth=15)[0]["target_depth"], 23)
        self.assertEqual(self.raised(tier="extreme", target_depth=70)[0]["target_depth"], 120)
        self.assertEqual(self.raised(tier="standard", target_depth=45)[0]["target_depth"], 65)

    def test_absent_target_reads_the_tier_base(self):
        out, _ = self.raised(tier="basic")
        self.assertEqual(out["was"]["target_depth"], 8)
        self.assertEqual(out["target_depth"], 20)

    def test_the_doctrine_is_named(self):
        self.assertIn("extreme is not a ceiling", fs.A_RAISE_IS_PROPORTIONAL_TO_THE_TIER)
        self.assertIn("whoever selected it", fs.A_FOCUS_AT_ITS_TARGET_RESTS)

    def test_one_definition(self):
        # Nothing but roadmap.raise_tier steps through TIER_ORDER to raise.
        for name in ("focus_complete.py", "focus_selection.py"):
            text = (SYSTEM / name).read_text(encoding="utf-8")
            self.assertIn("raise_tier(", text, name)
            self.assertNotRegex(text, r"TIER_ORDER\.index", name)


class Rest(unittest.TestCase):
    def test_no_owner_exemption(self):
        at = {"saturation": 1.0, "pending": 3}
        for by in ("owner", "sweep"):
            for reason in ("added", "kept_going", "reopened"):
                focus = {"selection": {"by": by, "reason": reason, "at": NOW}}
                self.assertTrue(fs.should_rest(focus, at), (by, reason))
        self.assertFalse(fs.should_rest({"selection": {"by": "owner", "reason": "added"}},
                                        {"saturation": 0.9, "pending": 3}))


class Paths(Base):
    def test_keep_going_raises_and_selects(self):
        self.put(bank(3, 0), [PRIMARY, katie()])
        self.sweep()
        out = fc.play("katie", "keep_going", now=NOW)
        self.assertEqual(out["raised"], {"tier": "standard", "target_depth": 20,
                                         "was": {"tier": "basic", "target_depth": 8}})
        focus = self.focus()
        self.assertEqual((focus["tier"], focus["target_depth"]), ("standard", 20))
        self.assertTrue(fs.is_selected(focus))
        self.assertEqual(focus["selection"], {"by": "owner", "at": NOW, "reason": "kept_going"})

    def test_kept_going_while_drained_rests_as_complete_and_the_reopen_selects(self):
        self.put(bank(3, 0), [PRIMARY, katie()])
        self.sweep()
        fc.play("katie", "keep_going", now=NOW)
        out = self.sweep(now="2026-10-27T12:00:00Z")
        self.assertEqual([r["reason"] for r in out["rested"]], ["complete"])
        self.bank_file.write_text(bank(3, 1))
        out = self.sweep(now="2026-11-03T12:00:00Z")
        self.assertEqual(out["reopened"], ["katie"])
        self.assertTrue(fs.is_selected(self.focus()))
        self.assertEqual(self.focus()["selection"]["reason"], "reopened")

    def test_a_readd_at_the_target_raises_and_the_next_sweep_leaves_it(self):
        self.put(bank(3, 2), [PRIMARY, katie(target_depth=3)])
        self.sweep()
        self.assertFalse(fs.is_selected(self.focus()))
        result = fs.set_by_owner("katie", True, now=NOW)
        self.assertTrue(result["changed"])
        self.assertEqual(result["raised"], {"tier": "standard", "target_depth": 20,
                                            "was": {"tier": "basic", "target_depth": 3}})
        focus = self.focus()
        self.assertEqual((focus["tier"], focus["target_depth"]), ("standard", 20))
        self.assertEqual(focus["selection"]["reason"], "added")
        self.assertEqual(self.sweep(now="2026-10-27T12:00:00Z")["rested"], [])
        self.assertTrue(fs.is_selected(self.focus()))

    def test_a_readd_below_the_target_does_not_raise(self):
        self.put(bank(3, 2), [PRIMARY, katie(target_depth=8)])
        fs.set_by_owner("katie", False, now=NOW)
        result = fs.set_by_owner("katie", True, now=NOW)
        self.assertIsNone(result["raised"])
        focus = self.focus()
        self.assertEqual((focus["tier"], focus["target_depth"]), ("basic", 8))

    def test_a_readd_past_extreme_keeps_growing(self):
        self.put(bank(3, 2), [PRIMARY, katie(tier="extreme", target_depth=3)])
        result = fs.set_by_owner("katie", True, now=NOW)
        # max(extreme base 50, 3 + 50) = 53: an owner-set target, raised by the step.
        self.assertEqual((result["raised"]["tier"], result["raised"]["target_depth"]),
                         ("extreme", 53))

    def test_the_primary_is_never_raised_by_an_add(self):
        self.put(bank(3, 2), [dict(PRIMARY, target_depth=1), katie(target_depth=8)])
        result = fs.set_by_owner("my-life", True, now=NOW)
        self.assertIsNone(result["raised"])
        self.assertEqual(self.focus("my-life")["tier"], "extreme")


class Viewer(Base):
    def html(self):
        with mock.patch.object(serve_wiki, "QUESTIONS_FILE", self.bank_file):
            return serve_wiki.view_foundation()[1]

    def test_the_add_sheet_says_an_add_at_the_target_raises(self):
        self.put(bank(3, 2), [PRIMARY, katie(target_depth=3)])
        self.sweep()
        self.assertIn("adding it back raises the tier", self.html())

    def test_below_the_target_it_says_nothing(self):
        self.put(bank(3, 2), [PRIMARY, katie(target_depth=8)])
        fs.set_by_owner("katie", False, now=NOW)
        self.assertNotIn("raises the tier", self.html())

    def test_the_flash_says_so(self):
        self.put(bank(3, 2), [PRIMARY, katie(target_depth=3)])
        self.sweep()
        with mock.patch.object(serve_wiki, "QUESTIONS_FILE", self.bank_file), \
                mock.patch.object(serve_wiki, "load_roadmap", roadmap.load_roadmap), \
                mock.patch.object(serve_wiki, "_start_job", return_value={"id": "j1"}):
            _back, flash, job = serve_wiki.act_focus_select({"id": ["katie"]})
        self.assertEqual(job, "j1")
        self.assertRegex(flash, r"katie is at the target, so the add raises the tier")


class Door(unittest.TestCase):
    def setUp(self):
        self.root = root_parent_tmp(self, ROOT, prefix="lifehug-v425-")
        (self.root / "state").mkdir()
        (self.root / "answers").mkdir()
        (self.root / "question-bank.md").write_text(bank(3, 2), encoding="utf-8")
        (self.root / "state" / "rotation.json").write_text(json.dumps({
            "version": 1, "current_pass": 1,
            "pass_names": ["skeleton", "depth", "connections", "polish"],
            "last_question_id": None, "last_asked_at": None, "questions_asked": 0,
            "questions_answered": 0, "next_question_id": None, "focus_frequency": 4}))
        (self.root / "state" / "coverage.json").write_text(json.dumps({
            "version": 1, "last_updated": None, "categories": {}}))
        rested = {"by": "sweep", "at": NOW, "reason": "tier_target"}
        (self.root / "state" / "roadmap.json").write_text(json.dumps({
            "version": 1, "focuses": [PRIMARY, katie(target_depth=3, selected=False,
                                                     selection=rested)]}), encoding="utf-8")
        self.env = {**os.environ, "LIFEHUG_VAULT_ROOT": str(self.root),
                    "LIFEHUG_FRAMEWORK_SYSTEM_DIR": str(SYSTEM),
                    "PYTHONDONTWRITEBYTECODE": "1"}

    def door(self, *argv):
        return subprocess.run([sys.executable, str(SYSTEM / "lifehug.py"), *argv],
                              env=self.env, capture_output=True, text=True, timeout=120,
                              cwd=self.root)

    def test_focus_select_at_the_target_raises(self):
        r = self.door("focus-select", "katie", "--json")
        self.assertEqual(r.returncode, 0, r.stderr)
        out = json.loads(r.stdout.strip().splitlines()[-1])
        self.assertEqual(out["raised"]["tier"], "standard")
        self.assertEqual(out["raised"]["target_depth"], 20)
        data = json.loads((self.root / "state" / "roadmap.json").read_text())
        focus = next(f for f in data["focuses"] if f["id"] == "katie")
        self.assertEqual((focus["tier"], focus["target_depth"], focus["selected"]),
                         ("standard", 20, True))

    def test_the_line_says_so(self):
        r = self.door("focus-select", "katie")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(re.search(r"raised to standard \(target 3 -> 20\)", r.stdout), r.stdout)


if __name__ == "__main__":
    unittest.main()
