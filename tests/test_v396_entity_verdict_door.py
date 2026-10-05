"""v396 — the identity flags reach `lifehug.py entity-verdict`, the package's one CLI door.

I-1 (v387) added --handle/--retract-alias/--share-alias/--with/--located-in/
--fold-into (and --focus/--clear-handle) to entity_verdict.py's own parser only;
through `lifehug.py` they exited 2 ("unrecognized arguments"). Module-level
tests called entity_verdict.main directly and proved nothing about the door.
Synthetic vault only.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SYSTEM = ROOT / "system"
sys.path.insert(0, str(SYSTEM))
sys.path.insert(0, str(ROOT / "tests"))

import entity_verdict  # noqa: E402
import identity_resolution as ir  # noqa: E402
from test_v389_compile_by_record import Vault, person  # noqa: E402

FLAGS = ("--retract-alias", "--share-alias", "--with", "--located-in", "--fold-into",
         "--handle", "--clear-handle", "--focus")


def place(name, slug, **extra):
    return person(name, slug, **extra)


def door_vault(case):
    people = [
        person("Sam Orr", "sam-orr", aliases=["Sammy", "Sam"], relationship="friend"),
        person("Sam Pell", "sam-pell", aliases=["Sam"], relationship="friend"),
        person("Jo Lane", "jo-lane", aliases=["Joey"], relationship="friend"),
    ]
    places = [place("Orchard Cove", "orchard-cove"), place("Yucaipa", "yucaipa"),
              place("Yucaipa Valley", "yucaipa-valley")]
    return Vault(case, {"person": people, "place": places}, {})


def option_strings(parser: argparse.ArgumentParser) -> set[str]:
    return {o for a in parser._actions for o in a.option_strings} - {"-h", "--help"}


def _captured_parser(call) -> argparse.ArgumentParser:
    holder = {}
    real = argparse.ArgumentParser.parse_args

    def spy(self, *a, **k):
        holder["p"] = self
        raise SystemExit(0)

    argparse.ArgumentParser.parse_args = spy  # type: ignore[method-assign]
    try:
        try:
            call()
        except SystemExit:
            pass
    finally:
        argparse.ArgumentParser.parse_args = real  # type: ignore[method-assign]
    return holder["p"]


def lifehug_entity_parser() -> argparse.ArgumentParser:
    import lifehug  # noqa: PLC0415

    old = sys.argv
    sys.argv = ["lifehug.py", "--help"]
    try:
        top = _captured_parser(lifehug.main)
    finally:
        sys.argv = old
    sub = next(a for a in top._actions if isinstance(a, argparse._SubParsersAction))
    return sub.choices["entity-verdict"]


class Door(unittest.TestCase):
    def door(self, vault, *argv):
        return subprocess.run(
            [sys.executable, str(SYSTEM / "lifehug.py"), "entity-verdict", *argv],
            env=vault.env, capture_output=True, text=True, timeout=120, cwd=vault.root)

    def roster(self, vault, kind):
        data = json.loads((vault.root / "state" / "entity_rosters" / f"{kind}.json").read_text())
        return {r["slug"]: r for r in data["entities"]}

    def short_handle(self, vault):
        rows = self.roster(vault, "person")
        return ir.record_view(rows["jo-lane"], {"entities": list(rows.values())}).get("short_handle")

    def test_help_lists_every_identity_flag(self):
        r = subprocess.run([sys.executable, str(SYSTEM / "lifehug.py"), "entity-verdict", "--help"],
                           capture_output=True, text=True, timeout=120)
        self.assertEqual(r.returncode, 0, r.stderr)
        for flag in FLAGS:
            self.assertIn(flag, r.stdout)

    def test_handle_and_retract_through_the_door(self):
        v = door_vault(self)
        r = self.door(v, "person", "jo-lane", "clear", "--handle", "jo")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.short_handle(v), "@jo")
        r = self.door(v, "person", "jo-lane", "clear", "--clear-handle")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertFalse(self.short_handle(v))
        r = self.door(v, "person", "sam-orr", "clear", "--retract-alias", "Sammy")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertNotIn("Sammy", self.roster(v, "person")["sam-orr"]["aliases"])

    def test_share_alias_through_the_door(self):
        v = door_vault(self)
        r = self.door(v, "person", "sam-orr", "clear", "--share-alias", "Sammy",
                      "--with", "a cousin (no record)")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertNotEqual(self.roster(v, "person")["sam-orr"], {})
        self.assertIn("a cousin (no record)",
                      (v.root / "state" / "entity_rosters" / "person.json").read_text())

    def test_located_in_and_fold_into_through_the_door(self):
        v = door_vault(self)
        r = self.door(v, "place", "yucaipa-valley", "clear", "--fold-into", "yucaipa")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.roster(v, "place")["yucaipa-valley"].get("folded_into"), "yucaipa")
        r = self.door(v, "place", "orchard-cove", "clear", "--located-in", "yucaipa")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.roster(v, "place")["orchard-cove"]["located_in"], "place/yucaipa")


class OneDefinition(unittest.TestCase):
    def test_both_doors_declare_the_same_option_set(self):
        module = _captured_parser(lambda: entity_verdict.main(["person", "x", "clear"]))
        door = lifehug_entity_parser()
        self.assertEqual(option_strings(module) ^ option_strings(door), set(),
                         "entity-verdict flags differ between the two doors")
        self.assertTrue(set(FLAGS) <= option_strings(door))


if __name__ == "__main__":
    unittest.main()
