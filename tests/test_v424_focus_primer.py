"""v424 (ADR 0046) — a Focus starts with a primer, and Foundation manages Focuses.

`focus-new --primer-file/--person`, `focus-set --primer-file`, and the viewer's
Add / Edit / Remove / Tier actions, every one reached through the CLI door
(`system/lifehug.py`): the viewer files a job and the job runs the verb.
Every fixture is SYNTHETIC (Grandpa Joe, Katie); nothing is copied from any
real vault.
"""

from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SYSTEM = ROOT / "system"
sys.path.insert(0, str(SYSTEM))
sys.path.insert(0, str(ROOT / "tests"))

import focus_candidate  # noqa: E402
import jobs  # noqa: E402
import serve_wiki  # noqa: E402
from test_v389_compile_by_record import Vault, person  # noqa: E402
from test_v394_focus_complete import PRIMARY, bank, katie  # noqa: E402


def make_vault(case, *, focuses=None, people=None):
    people = people if people is not None else [
        person("Grandpa Joe", "grandpa-joe", aliases=["Joe"], relationship="grandparent"),
        person("Katie Orr", "katie-orr", focus="katie"),
    ]
    vault = Vault(case, {"person": people}, {})
    (vault.root / "question-bank.md").write_text(bank(3, 2), encoding="utf-8")
    (vault.root / "state" / "roadmap.json").write_text(
        json.dumps({"version": 1, "focuses": focuses or [PRIMARY, katie()]}), encoding="utf-8")
    return vault


def door(vault, *argv, stdin=None):
    return subprocess.run([sys.executable, str(SYSTEM / "lifehug.py"), *argv],
                          env=vault.env, capture_output=True, text=True, timeout=180,
                          cwd=vault.root, input=stdin)


def roadmap_of(vault):
    return json.loads((vault.root / "state" / "roadmap.json").read_text())["focuses"]


def row(vault, fid):
    return next(f for f in roadmap_of(vault) if f["id"] == fid)


def write_primer(vault, data, name="primer.json"):
    path = vault.root / name
    path.write_text(json.dumps(data), encoding="utf-8")
    return str(path)


class Primer(unittest.TestCase):
    def setUp(self):
        self.vault = make_vault(self)

    def test_focus_new_persists_the_primer(self):
        path = write_primer(self.vault, {
            "objective": "His farm years", "relationship": "grandparent",
            "living": False, "context": "  He farmed barley and told stories.  "})
        r = door(self.vault, "focus-new", "Grandpa Joe", "--type", "person", "--tier", "basic",
                 "--no-generate", "--primer-file", path, "--person", "grandpa-joe")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        f = row(self.vault, "grandpa-joe")
        self.assertEqual(f["primer"], "He farmed barley and told stories.")
        self.assertEqual(f["objective"], "His farm years")
        self.assertEqual(f["relationship"], "grandparent")
        self.assertIs(f["living"], False)
        self.assertEqual(f["person_ref"], "person/grandpa-joe")

    def test_flags_override_the_file(self):
        path = write_primer(self.vault, {"objective": "from file", "relationship": "grandparent",
                                         "living": False, "context": "x"})
        r = door(self.vault, "focus-new", "Grandpa Joe", "--type", "person", "--no-generate",
                 "--primer-file", path, "--objective", "from flag", "--living",
                 "--relationship", "parent")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        f = row(self.vault, "grandpa-joe")
        self.assertEqual((f["objective"], f["relationship"], f["living"]),
                         ("from flag", "parent", True))

    def test_a_long_context_is_refused_and_nothing_is_written(self):
        before = (self.vault.root / "question-bank.md").read_bytes()
        path = write_primer(self.vault, {"context": "x" * 2001})
        r = door(self.vault, "focus-new", "Grandpa Joe", "--type", "person", "--no-generate",
                 "--primer-file", path)
        self.assertEqual(r.returncode, 1)
        self.assertIn("2001 characters; the limit is 2000", r.stdout)
        self.assertEqual((self.vault.root / "question-bank.md").read_bytes(), before)
        self.assertNotIn("grandpa-joe", [f["id"] for f in roadmap_of(self.vault)])
        # exactly 2000 (after trim) is fine
        ok = write_primer(self.vault, {"context": " " + "y" * 2000 + " "}, "ok.json")
        r = door(self.vault, "focus-new", "Grandpa Joe", "--type", "person", "--no-generate",
                 "--primer-file", ok)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(len(row(self.vault, "grandpa-joe")["primer"]), 2000)

    def test_a_bad_file_is_a_clear_error(self):
        r = door(self.vault, "focus-new", "Grandpa Joe", "--no-generate",
                 "--primer-file", str(self.vault.root / "missing.json"))
        self.assertEqual(r.returncode, 1)
        self.assertIn("cannot read primer file", r.stdout)
        r = door(self.vault, "focus-new", "Grandpa Joe", "--no-generate", "--primer-file",
                 write_primer(self.vault, {"context": "ok", "nonsense": 1}))
        self.assertEqual(r.returncode, 1)
        self.assertIn("unknown key", r.stdout)

    def test_stdin_is_a_primer_door(self):
        r = door(self.vault, "focus-new", "Grandpa Joe", "--no-generate", "--primer-file", "-",
                 stdin=json.dumps({"context": "From stdin."}))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(row(self.vault, "grandpa-joe")["primer"], "From stdin.")

    def test_focus_set_updates_the_primer_only(self):
        before = dict(row(self.vault, "katie"))
        r = door(self.vault, "focus-set", "katie", "--primer-file",
                 write_primer(self.vault, {"context": "Katie, my daughter.", "objective": "ignored"}))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        after = row(self.vault, "katie")
        self.assertEqual(after["primer"], "Katie, my daughter.")
        self.assertEqual({k: v for k, v in after.items() if k != "primer"}, before)
        r = door(self.vault, "focus-set", "katie", "--primer-file",
                 write_primer(self.vault, {"context": "z" * 2001}, "long.json"))
        self.assertEqual(r.returncode, 1)
        self.assertEqual(row(self.vault, "katie")["primer"], "Katie, my daughter.")

    def test_the_primer_survives_a_rebuild(self):
        door(self.vault, "focus-set", "katie", "--primer-file",
             write_primer(self.vault, {"context": "kept"}))
        self.assertEqual(door(self.vault, "roadmap-rebuild").returncode, 0)
        self.assertEqual(row(self.vault, "katie")["primer"], "kept")

    def test_roadmap_prints_presence_never_the_text(self):
        door(self.vault, "focus-set", "katie", "--primer-file",
             write_primer(self.vault, {"context": "SECRET-PRIMER-TEXT"}))
        out = door(self.vault, "roadmap").stdout
        self.assertIn("primer: yes", out)
        self.assertIn("primer: no", out)
        self.assertNotIn("SECRET-PRIMER-TEXT", out)

    def test_one_parser_for_the_viewer_and_the_cli(self):
        self.assertEqual(focus_candidate.normalize_primer({"context": " a "}), {"context": "a"})
        with self.assertRaises(ValueError):
            focus_candidate.normalize_primer([])
        self.assertEqual(focus_candidate.MAX_PRIMER_CHARS, 2000)


class Person(unittest.TestCase):
    def setUp(self):
        self.vault = make_vault(self)

    def test_person_binds_the_record(self):
        r = door(self.vault, "focus-new", "Grandpa Joe", "--type", "person", "--no-generate",
                 "--person", "grandpa-joe")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(row(self.vault, "grandpa-joe")["person_ref"], "person/grandpa-joe")
        roster = json.loads((self.vault.root / "state" / "entity_rosters" / "person.json").read_text())
        joe = next(e for e in roster["entities"] if e["slug"] == "grandpa-joe")
        self.assertEqual(joe["focus"], "grandpa-joe")

    def test_a_twin_is_refused(self):
        before = (self.vault.root / "state" / "roadmap.json").read_bytes()
        r = door(self.vault, "focus-new", "Kate", "--type", "person", "--no-generate",
                 "--person", "katie-orr")
        self.assertEqual(r.returncode, 1)
        self.assertIn("refusing a twin", r.stdout)
        self.assertEqual((self.vault.root / "state" / "roadmap.json").read_bytes(), before)

    def test_unknown_record_and_wrong_type_are_refused(self):
        r = door(self.vault, "focus-new", "Nobody", "--type", "person", "--no-generate",
                 "--person", "nobody")
        self.assertEqual(r.returncode, 1)
        self.assertIn("no such person record", r.stdout)
        r = door(self.vault, "focus-new", "Grandpa Joe", "--type", "theme", "--no-generate",
                 "--person", "grandpa-joe")
        self.assertEqual(r.returncode, 1)
        self.assertIn("--type person", r.stdout)


# ---------------------------------------------------------------------------
# The viewer: each action files a job and the job runs the lifehug.py verb.
# ---------------------------------------------------------------------------


def run_action(vault, action, form):
    """Call the viewer action with a capturing job queue, then run every filed
    job's invocation through lifehug.py (the CLI door) in the vault."""
    filed = []

    def start(kind, payload=None):
        filed.append((kind, payload or {}))
        return {"id": f"job-{len(filed)}"}

    with mock.patch.object(serve_wiki, "_start_job", start), \
            mock.patch.object(serve_wiki, "_identity_records",
                              lambda t="person": json.loads(
                                  (vault.root / "state" / "entity_rosters" / f"{t}.json").read_text()
                              )["entities"]):
        redirect, flash, job = action(form)
    results = []
    for kind, payload in filed:
        (invocation,) = jobs.COMMANDS[kind].build(payload)
        results.append(door(vault, *invocation.arguments, stdin=invocation.stdin_text))
    return redirect, flash, job, filed, results


class Viewer(unittest.TestCase):
    def setUp(self):
        self.vault = make_vault(self)

    def test_remove_then_add_back(self):
        redirect, flash, job, filed, results = run_action(
            self.vault, serve_wiki.act_focus_unselect, {"id": ["katie"]})
        self.assertEqual(redirect, "/views/foundation")
        self.assertEqual(filed, [("focus-unselect", {"focus_id": "katie"})])
        self.assertEqual(results[0].returncode, 0, results[0].stdout + results[0].stderr)
        self.assertIs(row(self.vault, "katie")["selected"], False)
        self.assertIn("nothing is deleted", flash)
        _, _, _, filed, results = run_action(
            self.vault, serve_wiki.act_focus_select, {"id": ["katie"]})
        self.assertEqual(results[0].returncode, 0, results[0].stdout + results[0].stderr)
        self.assertIs(row(self.vault, "katie")["selected"], True)
        self.assertEqual(row(self.vault, "katie")["selection"]["reason"], "added")

    def test_remove_and_tier_take_several_rows(self):
        _, _, _, filed, results = run_action(
            self.vault, serve_wiki.act_focus_tier, {"id": ["katie", "my-life"], "tier": ["extreme"]})
        self.assertEqual([k for k, _ in filed], ["focus-tier", "focus-tier"])
        self.assertTrue(all(r.returncode == 0 for r in results), [r.stdout for r in results])
        self.assertEqual(row(self.vault, "katie")["tier"], "extreme")

    def test_error_paths_file_no_job(self):
        for action, form in ((serve_wiki.act_focus_select, {}),
                             (serve_wiki.act_focus_unselect, {}),
                             (serve_wiki.act_focus_tier, {"id": ["katie"], "tier": ["huge"]}),
                             (serve_wiki.act_focus_tier, {"tier": ["basic"]}),
                             (serve_wiki.act_focus_new, {"search": [""]}),
                             (serve_wiki.act_focus_new, {"search": ["X"], "context": ["q" * 2001]})):
            redirect, flash, job, filed, _ = run_action(self.vault, action, form)
            self.assertEqual(redirect, "/views/foundation")
            self.assertTrue(flash.startswith("✗"), flash)
            self.assertIsNone(job)
            self.assertEqual(filed, [])

    def test_the_verb_refuses_an_unknown_focus(self):
        _, _, _, _, results = run_action(
            self.vault, serve_wiki.act_focus_unselect, {"id": ["nobody"]})
        self.assertEqual(results[0].returncode, 1)
        self.assertIn("No such focus", results[0].stdout)

    def test_add_a_roster_person_with_a_primer(self):
        _, flash, job, filed, results = run_action(self.vault, serve_wiki.act_focus_new, {
            "search": ["Grandpa Joe"], "type": ["theme"], "tier": ["basic"],
            "objective": ["His farm years"], "relationship": ["grandparent"], "living": ["no"],
            "context": ["He farmed barley."]})
        (kind, payload), = filed
        self.assertEqual(kind, "focus-new")
        self.assertEqual(payload["person"], "grandpa-joe")
        self.assertEqual(payload["type"], "person")
        self.assertEqual(payload["primer"]["context"], "He farmed barley.")
        self.assertEqual(results[0].returncode, 0, results[0].stdout + results[0].stderr)
        f = row(self.vault, "grandpa-joe")
        self.assertEqual((f["person_ref"], f["primer"], f["tier"], f["living"]),
                         ("person/grandpa-joe", "He farmed barley.", "basic", False))
        self.assertEqual(f["objective"], "His farm years")

    def test_add_a_typed_name_has_no_person(self):
        _, _, _, filed, results = run_action(self.vault, serve_wiki.act_focus_new, {
            "search": ["The Orchard"], "type": ["place"], "tier": ["standard"],
            "context": ["Our apple orchard."]})
        self.assertNotIn("person", filed[0][1])
        self.assertEqual(results[0].returncode, 0, results[0].stdout + results[0].stderr)
        f = row(self.vault, "the-orchard")
        self.assertEqual((f["type"], f["primer"]), ("place", "Our apple orchard."))
        self.assertNotIn("person_ref", f)

    def test_adding_a_person_who_has_a_focus_types_a_name_and_a_twin_is_refused(self):
        # Katie Orr already has a Focus, so she is not offered; typing her name
        # as a person-typed Focus is a plain Focus and the verb's own twin
        # guard answers.
        _, _, _, filed, results = run_action(self.vault, serve_wiki.act_focus_new, {
            "search": ["Katie Orr"], "type": ["person"], "tier": ["basic"]})
        self.assertNotIn("person", filed[0][1])
        self.assertEqual(results[0].returncode, 1)
        self.assertIn("refusing a twin", results[0].stdout)

    def test_foundation_renders_the_header_and_previously_used(self):
        data = [PRIMARY, katie(), katie(id="old-friend", label="Old Friend", categories=["K"],
                                        person_ref="person/zzz", selected=False,
                                        selection={"by": "owner", "at": "2026-10-19T00:00:00Z",
                                                   "reason": "removed"})]
        (self.vault.root / "state" / "roadmap.json").write_text(
            json.dumps({"version": 1, "focuses": data}), encoding="utf-8")
        page = self.vault.serve("print(sw.view_foundation()[1])")
        for needle in ("＋ Add", ">Edit<", "Previously used", "Old Friend",
                       'action="/actions/focus-select"', 'action="/actions/focus-new"',
                       'formaction="/actions/focus-unselect"', 'formaction="/actions/focus-tier"',
                       'value="Grandpa Joe"', 'name="context"'):
            self.assertIn(needle, page)
        # Katie has a Focus: she is not offered as a person to start one for.
        self.assertNotIn('<option value="Katie Orr">', page)

    def test_every_action_is_routed(self):
        for route in ("focus-select", "focus-unselect", "focus-tier", "focus-new"):
            self.assertIn(f"/actions/{route}", serve_wiki.ACTIONS)

    def test_job_builders_reject_bad_payloads(self):
        for kind, payload in (("focus-select", {"focus_id": "../x"}),
                              ("focus-tier", {"focus_id": "katie", "tier": "huge"}),
                              ("focus-new", {"label": "-x", "type": "theme", "tier": "basic"}),
                              ("focus-new", {"label": "X", "type": "theme", "tier": "basic",
                                             "primer": "text"})):
            with self.assertRaises(ValueError):
                jobs.COMMANDS[kind].build(payload)


class Help(unittest.TestCase):
    def test_flags_are_on_the_door(self):
        for verb, flags in (("focus-new", ("--primer-file", "--person")),
                            ("focus-set", ("--primer-file",))):
            r = subprocess.run([sys.executable, str(SYSTEM / "lifehug.py"), verb, "--help"],
                               capture_output=True, text=True, timeout=120)
            self.assertEqual(r.returncode, 0, r.stderr)
            for flag in flags:
                self.assertIn(flag, r.stdout)


if __name__ == "__main__":
    unittest.main()
