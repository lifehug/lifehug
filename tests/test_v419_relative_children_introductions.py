"""v419 — "they are Britt's kids": a (son)/(daughter)/(child) list line under an
introduced sibling or child introduces that relative's child.

v407 left a household memo's two sons unintroduced
(`A_HOUSEHOLD_SURNAME_IS_NOT_A_RELATION`). The owner's ruling (2026-10-11) is
that he can say it in the source: `(son)` on the line. Synthetic names; NEVER
reads any real vault.
"""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "system"))
sys.path.insert(0, str(ROOT / "tests"))

import axis_membership as axm  # noqa: E402
import entity_roster  # noqa: E402
import roster_relations as rr  # noqa: E402
from tempdirs import root_parent_tmp  # noqa: E402

from test_v340_apply_keeps_placements import write_vault  # noqa: E402
from test_v403_birthday_anchors import roster, roster_birth, row  # noqa: E402

OWNER_NAMES = ("Dave", "David James Taylor")
NOTE = "sources/manual/2026-09-15-marnie-quill-household-birthdays.md"
SOURCE = "manual:2026-09-15-marnie-quill-household-birthdays"
MARNIE = "- Marnie Quill — December 17, 1987 (Dave’s younger sister; born at Fisher House)"
CORBIN = "- Corbin Quill — February 28, 1990 (husband)"
ELLIOT = "- Elliot Quill — March 9, 2014 (son)"
GRAHAM = "- Graham Quill — June 2, 2016 (son)"
LINES = [MARNIE, CORBIN, ELLIOT, GRAHAM]
BIRTHS = (("Marnie Quill", "1987-12-17"), ("Corbin Quill", "1990-02-28"),
          ("Elliot Quill", "2014-03-09"), ("Graham Quill", "2016-06-02"))


def births(skip=()):
    return [roster_birth(n, d, path=NOTE, source=SOURCE) for n, d in BIRTHS if n not in skip]


class ChildLineTests(unittest.TestCase):

    def plan(self, lines=LINES, roster_snapshot=None, claims=None):
        return rr.relative_birth_introductions(
            claims if claims is not None else births(),
            roster=roster_snapshot or roster(), telling_texts={NOTE: lines},
            owner_names=OWNER_NAMES)

    def rows(self, **kw):
        return {r["slug"]: r for r in self.plan(**kw)["rows"]}

    def test_the_real_memo_shape_with_the_spouse_line_between(self):
        plan = self.plan()
        rows = {r["slug"]: r for r in plan["rows"]}
        self.assertEqual(set(rows), {"marnie-quill", "corbin-quill", "elliot-quill", "graham-quill"})
        for slug, born in (("elliot-quill", "2014-03-09"), ("graham-quill", "2016-06-02")):
            kid = rows[slug]
            self.assertEqual((kid["relationship"], kid["relationship_word"], kid["child_of"], kid["born"]),
                             (rr.FALLBACK_RELATIONSHIP, "nephew", "marnie-quill", born))
            self.assertEqual(kid["rule"], rr.A_CHILD_LINE_UNDER_A_RELATIVE_IS_THAT_RELATIVES_CHILD)
            self.assertNotIn("spouse_of", kid)
            self.assertNotIn(kid["relationship"], axm.IMMEDIATE_FAMILY_RELATIONSHIPS)
        self.assertEqual(plan["unintroduced"], ())

    def test_the_words_under_a_sibling(self):
        for word, expect in (("son", "nephew"), ("Daughter", "niece"), ("child", "nephew or niece"),
                             ("kid", "nephew or niece"), ("boy", "nephew"), ("girl", "niece")):
            with self.subTest(word):
                lines = [MARNIE, f"- Elliot Quill — March 9, 2014 ({word}, b. at home)"]
                self.assertEqual(self.rows(lines=lines)["elliot-quill"]["relationship_word"], expect)

    def test_the_words_under_a_child(self):
        for word, expect in (("son", "grandson"), ("daughter", "granddaughter"),
                             ("child", "grandchild"), ("kid", "grandchild")):
            with self.subTest(word):
                lines = ["- Marnie Quill — December 17, 1987 (my daughter)",
                         f"- Elliot Quill — March 9, 2014 ({word})"]
                kid = self.rows(lines=lines)["elliot-quill"]
                self.assertEqual((kid["relationship_word"], kid["child_of"]), (expect, "marnie-quill"))

    def test_an_unlabeled_line_is_still_unintroduced_and_told_how_to_say_it(self):
        lines = [MARNIE, CORBIN, "- Elliot Quill — March 9, 2014", GRAHAM]
        plan = self.plan(lines=lines)
        self.assertNotIn("elliot-quill", {r["slug"] for r in plan["rows"]})
        self.assertIn("graham-quill", {r["slug"] for r in plan["rows"]})
        left = plan["unintroduced"]
        self.assertEqual([r["name"] for r in left], ["Elliot Quill"])
        self.assertEqual(left[0]["reason"], rr.UNINTRODUCED_HOUSEHOLD_REASON)
        self.assertIn("(son)", left[0]["how_to_say"])

    def test_a_child_line_under_the_owner_or_nobody_files_nothing(self):
        for lines in (["- David James Taylor — June 1, 1980", ELLIOT],
                      ["- Dave Taylor — June 1, 1980 (me)", ELLIOT],
                      ["- Marnie Quill — December 17, 1987 (neighbour)", ELLIOT],
                      [ELLIOT]):
            with self.subTest(lines[0]):
                plan = self.plan(lines=lines, claims=births(skip=("Marnie Quill", "Corbin Quill", "Graham Quill")))
                self.assertEqual(plan["rows"], ())

    def test_a_child_line_after_a_blank_line_is_another_list(self):
        self.assertNotIn("elliot-quill", self.rows(lines=[MARNIE, "", ELLIOT]))

    def test_a_parent_or_stranger_above_is_not_a_relative_with_children(self):
        lines = ["- Marnie Quill — December 17, 1987 (Dave’s mother)", ELLIOT]
        self.assertNotIn("elliot-quill", self.rows(lines=lines))

    def test_a_rostered_sibling_is_enough(self):
        sister = row("Marnie Quill", "marnie-quill", "sibling", born="1987-12-17")
        rows = self.rows(lines=[MARNIE, ELLIOT], roster_snapshot=roster(sister),
                         claims=births(skip=("Marnie Quill",)))
        self.assertEqual(rows["elliot-quill"]["child_of"], "marnie-quill")


class TheIntroducerFilesTheChildrenTests(unittest.TestCase):

    def setUp(self):
        import lifehug_core  # noqa: PLC0415

        self.root = root_parent_tmp(self, ROOT, prefix="lifehug-v419-roster-")
        (self.root / "system").mkdir(parents=True, exist_ok=True)
        (self.root / "state" / "entity_rosters").mkdir(parents=True, exist_ok=True)
        (self.root / "profile.yaml").write_text("name: Dave\n", encoding="utf-8")
        self.path = self.root / "state" / "entity_rosters" / "person.json"
        self.path.write_text(json.dumps(roster()), encoding="utf-8")
        for module, name, value_ in ((lifehug_core, "REPO_DIR", self.root),
                                     (entity_roster, "ENTITY_DIR", self.path.parent)):
            saved = getattr(module, name)
            setattr(module, name, value_)
            self.addCleanup(setattr, module, name, saved)
        self.note = self.root / NOTE
        self.note.parent.mkdir(parents=True, exist_ok=True)
        self.write_note(LINES)

    def write_note(self, lines):
        self.note.write_text("---\ntype: \"unprompted_story\"\n---\n\n" + "\n".join(lines) + "\n",
                             encoding="utf-8")

    def run_pass(self, *, dry_run=False):
        write_vault(self.root, births())
        with mock.patch.object(entity_roster, "recount_stats", return_value={}):
            result = entity_roster.ensure_introduced_relatives(dry_run=dry_run)
        result["roster"] = json.loads(self.path.read_text(encoding="utf-8"))
        return result

    def test_dry_run_lists_the_children_with_their_rule(self):
        result = self.run_pass(dry_run=True)
        kids = {r["slug"]: r for r in result["introduced"] if r.get("child_of")}
        self.assertEqual(set(kids), {"elliot-quill", "graham-quill"})
        self.assertEqual(kids["elliot-quill"]["rule"],
                         rr.A_CHILD_LINE_UNDER_A_RELATIVE_IS_THAT_RELATIVES_CHILD)
        self.assertEqual(result["unintroduced"], [])
        self.assertEqual(result["roster"]["entities"], [])

    def test_the_listing_and_the_unintroduced_hint_read_aloud(self):
        import contextlib  # noqa: PLC0415
        import io  # noqa: PLC0415

        def listing(lines, *, dry):
            self.write_note(lines)
            write_vault(self.root, births())
            out = io.StringIO()
            with mock.patch.object(entity_roster, "recount_stats", return_value={}), \
                    mock.patch.object(sys, "argv", ["entity-roster", "--ensure-introduced",
                                                    *(["--dry-run"] if dry else [])]), \
                    contextlib.redirect_stdout(out):
                entity_roster.main()
            return out.getvalue()

        text = listing(LINES, dry=True)
        self.assertIn("elliot-quill: Elliot Quill — other (from “nephew”, born 2014-03-09, child of marnie-quill)", text)
        text = listing([MARNIE, CORBIN, "- Elliot Quill — March 9, 2014", GRAHAM], dry=True)
        self.assertIn("(son)", text)
        self.assertIn("on the line introduces the relative's child", text)

    def test_apply_files_them_once_and_idempotent(self):
        first = self.run_pass()
        rows = {r["slug"]: r for r in first["roster"]["entities"]}
        self.assertEqual(set(rows), {"marnie-quill", "corbin-quill", "elliot-quill", "graham-quill"})
        elliot = rows["elliot-quill"]
        self.assertEqual((elliot["relationship"], elliot["child_of"], elliot["born"]["best"]),
                         ("other", "marnie-quill", "2014-03-09"))
        self.assertNotIn("spouse_of", elliot)
        self.assertEqual(rows["corbin-quill"]["spouse_of"], "marnie-quill")
        second = self.run_pass()
        self.assertEqual(second["filed"], 0)
        self.assertEqual(second.get("retired", []), [])
        self.assertEqual(second["roster"], first["roster"])

    def test_an_unlabeled_line_files_nothing_and_a_child_under_the_owner_files_nothing(self):
        self.write_note([MARNIE, CORBIN, "- Elliot Quill — March 9, 2014", "- Graham Quill — June 2, 2016"])
        rows = {r["slug"] for r in self.run_pass()["roster"]["entities"]}
        self.assertEqual(rows, {"marnie-quill", "corbin-quill"})

    def test_child_of_survives_a_roster_refresh(self):
        self.assertIn("child_of", entity_roster._SETTLED_IDENTITY_FIELDS)
        previous = self.run_pass()["roster"]
        kept, _ = entity_roster.apply_previous_decisions(
            [{"name": "Elliot Quill", "aliases": []}], previous)
        elliot = next(e for e in kept if e["name"] == "Elliot Quill")
        self.assertEqual(elliot.get("child_of"), "marnie-quill")


if __name__ == "__main__":
    unittest.main()
