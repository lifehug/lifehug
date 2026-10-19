"""v423 (ADR 0046) — a Focus is a queue preference; selection is one field.

The owner's ruling (2026-10-19): removing a Focus "should only mean that it's
no longer preferential in the queue, not anything more, no deletion or
anything. If I re-added that focus it would once again get preference". A Focus
that reaches 100% unselects automatically so other Focuses get the queue's
space. Every fixture is SYNTHETIC (Katie, invented people); nothing is copied
from any real vault.
"""

from __future__ import annotations

import contextlib
import io
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
import lifehug_core  # noqa: E402
import question_planner as qp  # noqa: E402
import recommend_focuses  # noqa: E402
import roadmap  # noqa: E402
import serve_wiki  # noqa: E402
from tempdirs import root_parent_tmp  # noqa: E402
from test_v394_focus_complete import PRIMARY, Base, bank, katie  # noqa: E402

NOW = "2026-10-19T15:00:00Z"


class TheRule(unittest.TestCase):
    def test_absent_means_selected(self):
        self.assertTrue(fs.is_selected({}))
        self.assertTrue(fs.is_selected({"selected": True}))
        self.assertFalse(fs.is_selected({"selected": False}))

    def test_select_and_unselect_write_the_receipt_and_are_idempotent(self):
        focus = {"id": "katie"}
        self.assertTrue(fs.unselect(focus, by="owner", reason="removed", now=NOW))
        self.assertEqual(focus["selected"], False)
        self.assertEqual(focus["selection"], {"by": "owner", "at": NOW, "reason": "removed"})
        self.assertFalse(fs.unselect(focus, by="owner", reason="removed", now="later"))
        self.assertEqual(focus["selection"]["at"], NOW)
        self.assertTrue(fs.select(focus, by="owner", reason="added", now=NOW))
        self.assertTrue(fs.is_selected(focus))
        with self.assertRaises(ValueError):
            fs.select(focus, by="someone", reason="added")
        with self.assertRaises(ValueError):
            fs.select(focus, by="owner", reason="because")

    def test_should_rest(self):
        under = {"saturation": 0.5, "pending": 3}
        at = {"saturation": 1.0, "pending": 3}
        self.assertFalse(fs.should_rest({}, under))
        self.assertTrue(fs.should_rest({}, at))
        self.assertTrue(fs.should_rest({"phase": "complete"}, {"saturation": 0.4, "pending": 0}))
        self.assertFalse(fs.should_rest({"selected": False}, at))
        owner = {"selection": {"by": "owner", "reason": "added", "at": NOW}}
        self.assertFalse(fs.should_rest(owner, at))
        self.assertFalse(fs.should_rest(dict(owner, phase="complete"),
                                        {"saturation": 2.0, "pending": 0}))


# ---------------------------------------------------------------------------
# The planner: unselected => weight 0 and absent from the week; selected =>
# exactly what it was.
# ---------------------------------------------------------------------------


# A synthetic vault shaped like a real one (the v368 queue suite's shape): the
# primary life story, one project, six people, one of them saturated.
PEOPLE = ["mom", "dad", "spouse", "son", "daughter", "brother"]
PEOPLE_CATS = "KLMNOP"
TEXTS = ("Walk me through that day.", "What was the hardest part?", "When did it change?",
         "What did it teach you?", "Tell me about the house.", "Who was there with you?")


def _q(qid, *, answered=False, text="Tell me about that."):
    return {"id": qid, "category": qid[0], "text": text, "answered": answered}


def _rows(cat, count):
    return [_q(f"{cat}{n}", text=TEXTS[n % len(TEXTS)]) for n in range(1, 1 + count)]


def synthetic_state():
    questions, categories = [], {}
    for cat in "ABCDE":
        categories[cat] = {"group": "main", "name": cat}
        questions += _rows(cat, 12)
    categories["F"] = {"group": "project", "name": "Company"}
    questions += _rows("F", 24)
    for cat, count in zip(PEOPLE_CATS, (30, 4, 12, 8, 8, 6)):
        categories[cat] = {"group": "focus", "name": cat}
        questions += _rows(cat, count)
    questions += [_q(f"M{n}", answered=True) for n in range(20, 45)]
    return questions, categories, {"categories": {}}


def synthetic_roadmap():
    focuses = [{"id": "my-life", "type": "life_story", "primary": True, "tier": "extreme",
                "cap": 0.4, "categories": list("ABCDE")},
               {"id": "company", "type": "project", "tier": "extreme", "cap": 0.3,
                "categories": ["F"]}]
    for person, cat in zip(PEOPLE, PEOPLE_CATS):
        focuses.append({"id": person, "type": "person", "tier": "standard", "cap": 0.3,
                        "categories": [cat], "target_depth": 20})
    return {"focuses": focuses}


@contextlib.contextmanager
def planner_vault(roadmap_data):
    patches = [
        mock.patch.object(qp, "load_question_state", side_effect=synthetic_state),
        mock.patch.object(qp, "resolve_roadmap", return_value=roadmap_data),
        mock.patch.object(qp, "load_candidates", return_value=[]),
        mock.patch.object(qp, "read_answer_dates", return_value={}),
        mock.patch.object(qp, "global_fullness", return_value=0.5),
    ]
    for p in patches:
        p.start()
    try:
        yield
    finally:
        for p in reversed(patches):
            p.stop()


def build(roadmap_data, seed):
    with planner_vault(roadmap_data):
        return qp.build_queue(8, 2, 8, qp.default_planner_state(), seed=seed,
                              previous_queue={"queue": []})


def with_selection(fn):
    data = synthetic_roadmap()
    for focus in data["focuses"]:
        fn(focus)
    return data


class Planner(unittest.TestCase):
    SEEDS = range(40)

    def test_an_unselected_focus_weighs_zero_and_is_absent_from_the_week(self):
        def drop_mom(focus):
            if focus["id"] == "mom":
                fs.unselect(focus, by="owner", reason="removed", now=NOW)
        data = with_selection(drop_mom)
        questions, _cats, _cov = synthetic_state()
        index = qp.build_focus_index(data["focuses"], questions)
        self.assertEqual(index["info"]["mom"]["weight"], 0.0)
        self.assertGreater(index["info"]["dad"]["weight"], 0.0)
        for seed in self.SEEDS:
            built = build(data, seed)
            self.assertNotIn("mom", {item.get("focus") for item in built["queue"]}, seed)
            rows = {r["id"]: r for r in built["allocation"]["focuses"]}
            self.assertIs(rows["mom"]["selected"], False)
            self.assertEqual(rows["mom"]["weight"], 0.0)
            self.assertIs(rows["dad"]["selected"], True)

    def test_an_all_selected_roadmap_plans_byte_identically(self):
        explicit = with_selection(lambda f: f.update(selected=True))
        for seed in range(12):
            absent = build(synthetic_roadmap(), seed)
            stated = build(explicit, seed)
            self.assertEqual(json.dumps(absent["queue"], sort_keys=True),
                             json.dumps(stated["queue"], sort_keys=True), seed)
            self.assertEqual(json.dumps(absent["allocation"], sort_keys=True),
                             json.dumps(stated["allocation"], sort_keys=True), seed)

    def test_selecting_again_restores_the_preference(self):
        focus = {"id": "dad", "type": "person", "tier": "standard", "categories": ["L"],
                 "target_depth": 20}
        fill = {"room": True, "saturation": 0.1, "pending": 4}
        before = qp.focus_weight(focus, fill)
        fs.unselect(focus, by="owner", reason="removed", now=NOW)
        self.assertEqual(qp.focus_weight(focus, fill), 0.0)
        fs.select(focus, by="owner", reason="added", now=NOW)
        self.assertEqual(qp.focus_weight(focus, fill), before)


# ---------------------------------------------------------------------------
# The weekly sweep: rest at the tier target and at complete, never against the
# owner's word.
# ---------------------------------------------------------------------------


class Sweep(Base):
    def test_rests_at_the_tier_target(self):
        self.put(bank(3, 2), [PRIMARY, katie(target_depth=3)])
        out = self.sweep()
        self.assertEqual(out["completed"], [])
        self.assertEqual([(r["focus"], r["reason"]) for r in out["rested"]],
                         [("katie", "tier_target")])
        focus = self.focus()
        self.assertFalse(fs.is_selected(focus))
        self.assertEqual(focus["selection"]["by"], "sweep")
        self.assertEqual(focus["phase"], "active")
        self.assertTrue(fs.is_selected(self.focus("my-life")))

    def test_does_not_rest_below_the_target(self):
        self.put(bank(3, 2), [PRIMARY, katie(target_depth=8)])
        self.assertEqual(self.sweep()["rested"], [])
        self.assertTrue(fs.is_selected(self.focus()))

    def test_rests_at_complete(self):
        self.put(bank(3, 0), [PRIMARY, katie(target_depth=50)])
        out = self.sweep()
        self.assertEqual([c["focus"] for c in out["completed"]], ["katie"])
        self.assertEqual([r["reason"] for r in out["rested"]], ["complete"])
        self.assertFalse(fs.is_selected(self.focus()))

    def test_never_rests_what_the_owner_selected(self):
        owner = {"by": "owner", "at": NOW, "reason": "added"}
        self.put(bank(3, 2), [PRIMARY, katie(target_depth=3, selected=True, selection=owner)])
        self.assertEqual(self.sweep()["rested"], [])
        self.assertTrue(fs.is_selected(self.focus()))

    def test_dry_run_reports_and_writes_nothing(self):
        self.put(bank(3, 0), [PRIMARY, katie()])
        before = self.rm_file.read_bytes()
        out = self.sweep(dry_run=True)
        self.assertEqual([r["reason"] for r in out["rested"]], ["complete"])
        self.assertEqual(self.rm_file.read_bytes(), before)

    def test_keep_going_reselects_and_the_next_sweep_leaves_it_alone(self):
        self.put(bank(3, 0), [PRIMARY, katie()])
        self.sweep()
        self.assertFalse(fs.is_selected(self.focus()))
        fc.play("katie", "keep_going", now="2026-10-20T00:00:00Z")
        focus = self.focus()
        self.assertTrue(fs.is_selected(focus))
        self.assertEqual(focus["selection"]["by"], "owner")
        self.assertEqual(focus["selection"]["reason"], "added")
        self.assertEqual(self.sweep(now="2026-10-27T12:00:00Z")["rested"], [])
        self.assertTrue(fs.is_selected(self.focus()))

    def test_rest_unselects_a_complete_focus_the_sweep_had_not(self):
        self.put(bank(3, 0), [PRIMARY, katie(
            phase="complete", completion={"completed_at": NOW, "row": "open",
                                          "answered": 3, "total": 3})])
        fc.play("katie", "rest", now=NOW)
        focus = self.focus()
        self.assertFalse(fs.is_selected(focus))
        self.assertEqual(focus["selection"], {"by": "owner", "at": NOW, "reason": "removed"})

    def test_a_reopen_undoes_only_the_sweeps_complete_rest(self):
        self.put(bank(3, 0), [PRIMARY, katie()])
        self.sweep()
        self.bank_file.write_text(bank(3, 1))
        out = self.sweep(now="2026-10-27T12:00:00Z")
        self.assertEqual(out["reopened"], ["katie"])
        focus = self.focus()
        self.assertTrue(fs.is_selected(focus))
        self.assertEqual(focus["selection"]["reason"], "reopened")
        # The owner's Remove is never undone by a reopen.
        self.put(bank(3, 0), [PRIMARY, katie()])
        self.sweep()
        fs.set_by_owner("katie", False, now=NOW)
        self.bank_file.write_text(bank(3, 1))
        roadmap.rebuild_roadmap(write=True)
        self.assertFalse(fs.is_selected(self.focus()))

    def test_focus_set_tier_does_not_change_selection(self):
        self.put(bank(3, 2), [PRIMARY, katie(target_depth=3)])
        self.sweep()
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(roadmap.cli(["set", "katie", "--tier", "extreme"]), 0)
        self.assertFalse(fs.is_selected(self.focus()))
        self.assertEqual(self.focus()["tier"], "extreme")

    def test_selection_survives_a_roadmap_rebuild(self):
        self.put(bank(3, 2), [PRIMARY, katie(target_depth=3)])
        self.sweep()
        rebuilt = roadmap.rebuild_roadmap(write=True)
        focus = roadmap.find_focus(rebuilt, "katie")
        self.assertFalse(fs.is_selected(focus))
        self.assertEqual(focus["selection"]["reason"], "tier_target")

    def test_the_autopilot_count_skips_an_unselected_focus(self):
        self.put(bank(3, 2), [PRIMARY, katie(target_depth=100)])
        qs = lifehug_core.parse_questions(bank(3, 2))
        self.assertEqual(len(recommend_focuses._developing_focuses(roadmap.load_roadmap(), qs)), 1)
        fs.set_by_owner("katie", False, now=NOW)
        self.assertEqual(recommend_focuses._developing_focuses(roadmap.load_roadmap(), qs), [])


# ---------------------------------------------------------------------------
# The viewer: Foundation lists selected Focuses only.
# ---------------------------------------------------------------------------


class Foundation(Base):
    def html(self):
        with mock.patch.object(serve_wiki, "QUESTIONS_FILE", self.bank_file):
            return serve_wiki.view_foundation()[1]

    def test_an_unselected_focus_is_not_rendered(self):
        self.put(bank(3, 2), [PRIMARY, katie(target_depth=100)])
        self.assertIn(">Katie<", self.html())
        fs.set_by_owner("katie", False, now=NOW)
        page = self.html()
        self.assertNotIn(">Katie<", page)
        self.assertNotIn("Not part of any focus", page)   # its category is still its own
        self.assertIn("My Life", page)

    def test_a_complete_focus_the_owner_keeps_shows_its_mark(self):
        self.put(bank(3, 0), [PRIMARY, katie()])
        self.sweep()
        self.assertNotIn("fnd-complete", self.html())
        fc.play("katie", "keep_going", now=NOW)
        self.assertIn("fnd-complete", self.html())


# ---------------------------------------------------------------------------
# The CLI door: lifehug.py focus-select / focus-unselect.
# ---------------------------------------------------------------------------


class Door(unittest.TestCase):
    def setUp(self):
        self.root = root_parent_tmp(self, ROOT, prefix="lifehug-v423-")
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
        (self.root / "state" / "roadmap.json").write_text(
            json.dumps({"version": 1, "focuses": [PRIMARY, katie()]}), encoding="utf-8")
        self.env = {**os.environ, "LIFEHUG_VAULT_ROOT": str(self.root),
                    "LIFEHUG_FRAMEWORK_SYSTEM_DIR": str(SYSTEM),
                    "PYTHONDONTWRITEBYTECODE": "1"}

    def door(self, *argv):
        return subprocess.run([sys.executable, str(SYSTEM / "lifehug.py"), *argv],
                              env=self.env, capture_output=True, text=True, timeout=120,
                              cwd=self.root)

    def katie(self):
        data = json.loads((self.root / "state" / "roadmap.json").read_text())
        return next(f for f in data["focuses"] if f["id"] == "katie")

    def test_unselect_then_select(self):
        r = self.door("focus-unselect", "katie")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("Katie is unselected", r.stdout)
        self.assertEqual(self.katie()["selected"], False)
        self.assertEqual(self.katie()["selection"]["by"], "owner")
        self.assertEqual(self.katie()["selection"]["reason"], "removed")
        r = self.door("focus-select", "katie")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("Katie is selected", r.stdout)
        self.assertEqual(self.katie()["selected"], True)
        self.assertEqual(self.katie()["selection"]["reason"], "added")

    def test_json(self):
        r = self.door("focus-unselect", "katie", "--json")
        self.assertEqual(r.returncode, 0, r.stderr)
        out = json.loads(r.stdout.strip().splitlines()[-1])
        self.assertEqual(out["focus"], "katie")
        self.assertIs(out["selected"], False)
        self.assertIs(out["changed"], True)
        self.assertEqual(out["selection"]["reason"], "removed")
        r = self.door("focus-unselect", "katie", "--json")
        self.assertIs(json.loads(r.stdout.strip().splitlines()[-1])["changed"], False)

    def test_unknown_id(self):
        before = (self.root / "state" / "roadmap.json").read_bytes()
        r = self.door("focus-select", "nobody")
        self.assertEqual(r.returncode, 1)
        self.assertIn("No such focus", r.stdout)
        r = self.door("focus-unselect", "nobody", "--json")
        self.assertEqual(r.returncode, 1)
        self.assertEqual(json.loads(r.stdout.strip().splitlines()[-1])["error"], "unknown_focus")
        self.assertEqual((self.root / "state" / "roadmap.json").read_bytes(), before)

    def test_help_builds(self):
        for verb in ("focus-select", "focus-unselect"):
            r = subprocess.run([sys.executable, str(SYSTEM / "lifehug.py"), verb, "--help"],
                               capture_output=True, text=True, timeout=120)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn("--json", r.stdout)

    def test_roadmap_prints_selected(self):
        self.door("focus-unselect", "katie")
        r = self.door("roadmap")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("unselected", r.stdout)
        self.assertIn("selected: no", r.stdout)


# ---------------------------------------------------------------------------
# One definition: nothing outside focus_selection.py reads the flag inline.
# ---------------------------------------------------------------------------

_INLINE = re.compile(r"""(\.get\(\s*['"]selected['"]|\[\s*['"]selected['"]\s*\])""")


class OneDefinition(unittest.TestCase):
    def test_no_inline_selection_reads_outside_the_module(self):
        offenders = []
        for path in sorted(SYSTEM.rglob("*.py")):
            if path.name == "focus_selection.py":
                continue
            for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                if _INLINE.search(line):
                    offenders.append(f"{path.relative_to(ROOT)}:{n}: {line.strip()}")
        self.assertEqual(offenders, [], "read selection through focus_selection.is_selected")

    def test_the_readers_import_the_module(self):
        for name in ("question_planner.py", "recommend_focuses.py", "focus_complete.py",
                     "serve_wiki.py", "roadmap.py"):
            text = (SYSTEM / name).read_text(encoding="utf-8")
            self.assertRegex(text, r"(import focus_selection|from focus_selection import)", name)


if __name__ == "__main__":
    unittest.main()
