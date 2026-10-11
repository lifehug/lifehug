"""v407 — a household memo introduces its people; a stranger's birth is never
the owner's own.

The owner's vault (2026-10-10): `sources/manual/2026-09-15-<sister>-household-
birthdays.md` (type unprompted_story) lists

    - Marnie Quill — December 17, 1987 (Dave’s younger sister; born at Fisher House)
    - Corbin Quill — February 28, 1990 (husband)
    - Elliot Quill — March 9, 2014
    - Graham Quill — June 2, 2016

`entity-roster --ensure-introduced` filed the OTHER sisters (a leading "Sister
Kristine ..." header) but not this one: her relation sits in a parenthetical
after the date, with a curly apostrophe. And the four births sat on the
calculated timeline with `axis_membership: "owner"` and bare-name subjects: a
stranger's birth drawn as the owner's own lived event.

Synthetic names; NEVER reads any real vault.
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
import temporal_timeline as tt  # noqa: E402
from tempdirs import root_parent_tmp  # noqa: E402

from test_v340_apply_keeps_placements import claim, index_of, value, write_vault  # noqa: E402
from test_v344_a_birthday_is_a_birth import derive, owner_birth  # noqa: E402
from test_v403_birthday_anchors import roster, roster_birth, row  # noqa: E402

OWNER_NAMES = ("Dave", "David James Taylor")
NOTE = "sources/manual/2026-09-15-marnie-quill-household-birthdays.md"
SOURCE = "manual:2026-09-15-marnie-quill-household-birthdays"
LINES = [
    "- Marnie Quill — December 17, 1987 (Dave’s younger sister; born at Fisher House)",
    "- Corbin Quill — February 28, 1990 (husband)",
    "- Elliot Quill — March 9, 2014",
    "- Graham Quill — June 2, 2016",
]
BIRTHS = (("Marnie Quill", "1987-12-17"), ("Corbin Quill", "1990-02-28"),
          ("Elliot Quill", "2014-03-09"), ("Graham Quill", "2016-06-02"))


def births():
    return [roster_birth(name, day, path=NOTE, source=SOURCE) for name, day in BIRTHS]


class ParentheticalRelationTests(unittest.TestCase):

    def plan(self, lines=LINES, claims=None, roster_snapshot=None):
        return rr.relative_birth_introductions(
            claims if claims is not None else births(),
            roster=roster_snapshot or roster(), telling_texts={NOTE: lines},
            owner_names=OWNER_NAMES)

    def rows(self, **kw):
        return {r["slug"]: r for r in self.plan(**kw)["rows"]}

    def test_the_sister_is_filed_with_her_birth(self):
        sister = self.rows()["marnie-quill"]
        self.assertEqual((sister["name"], sister["relationship"], sister["born"]),
                         ("Marnie Quill", "sibling", "1987-12-17"))
        self.assertEqual(sister["relationship_word"], "sister")

    def test_my_form_and_straight_apostrophe_and_other_words(self):
        for paren, relationship in (("my older brother", "sibling"),
                                    ("Dave's mother", "parent"),
                                    ("Dave’s half-sister", "sibling"),
                                    ("my daughter; b. at home", "child")):
            with self.subTest(paren):
                lines = [f"- Marnie Quill — December 17, 1987 ({paren})"]
                self.assertEqual(self.rows(lines=lines)["marnie-quill"]["relationship"],
                                 relationship)

    def test_somebody_elses_relation_or_an_in_law_introduces_nobody(self):
        for paren in ("Blair’s sister", "Dave’s mother-in-law", "a neighbour",
                      "Daveson’s sister"):
            with self.subTest(paren):
                lines = [f"- Marnie Quill — December 17, 1987 ({paren})"]
                self.assertEqual(self.rows(lines=lines), {})

    def test_the_husband_is_her_spouse_never_the_owners(self):
        rows = self.rows()
        husband = rows["corbin-quill"]
        self.assertEqual(husband["relationship"], "other")
        self.assertEqual(husband["relationship_word"], "brother-in-law")
        self.assertEqual(husband["spouse_of"], "marnie-quill")
        self.assertEqual(husband["born"], "1990-02-28")
        self.assertNotIn(husband["relationship"], axm.IMMEDIATE_FAMILY_RELATIONSHIPS)
        wife = self.rows(lines=[
            "- Marnie Quill — December 17, 1987 (Dave’s older brother)",
            "- Corbin Quill — February 28, 1990 (wife)"])["corbin-quill"]
        self.assertEqual(wife["relationship_word"], "sister-in-law")

    def test_a_spouse_line_under_nobody_introduces_nobody(self):
        lines = ["- Marnie Quill — December 17, 1987 (neighbour)",
                 "- Corbin Quill — February 28, 1990 (husband)"]
        self.assertEqual(self.rows(lines=lines), {})

    def test_the_sons_are_left_unintroduced_and_said_so(self):
        plan = self.plan()
        self.assertEqual({r["slug"] for r in plan["rows"]}, {"marnie-quill", "corbin-quill"})
        left = {r["name"]: r for r in plan["unintroduced"]}
        self.assertEqual(set(left), {"Elliot Quill", "Graham Quill"})
        self.assertEqual(left["Elliot Quill"]["reason"], rr.UNINTRODUCED_HOUSEHOLD_REASON)
        self.assertEqual(left["Elliot Quill"]["household_of"], ["corbin-quill", "marnie-quill"])
        self.assertEqual(left["Graham Quill"]["born"], "2016-06-02")

    def test_a_different_surname_or_another_list_is_not_the_household(self):
        lines = [*LINES[:2], "- Elliot Hart — March 9, 2014", "", "Notes:",
                 "- Graham Quill — June 2, 2016"]
        plan = self.plan(lines=lines)
        self.assertEqual(plan["unintroduced"], ())

    def test_the_v403_header_reading_is_untouched(self):
        lines = ["Sister Kristine (Kris) Thompson + household:",
                 "- Kris Thompson — November 20, 1977"]
        rows = rr.relative_birth_introductions(
            [roster_birth("Kris Thompson", "1977-11-20", path=NOTE, source=SOURCE)],
            roster=roster(), telling_texts={NOTE: lines}, owner_names=OWNER_NAMES)
        self.assertEqual([r["slug"] for r in rows["rows"]], ["kristine-thompson"])
        self.assertEqual(rows["unintroduced"], ())


class TheIntroducerFilesTheHouseholdTests(unittest.TestCase):
    """`entity-roster --ensure-introduced` end to end, on a throwaway vault."""

    def setUp(self):
        import lifehug_core  # noqa: PLC0415

        self.root = root_parent_tmp(self, ROOT, prefix="lifehug-v407-roster-")
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
        note = self.root / NOTE
        note.parent.mkdir(parents=True, exist_ok=True)
        note.write_text("---\ntype: \"unprompted_story\"\n---\n\n" + "\n".join(LINES) + "\n",
                        encoding="utf-8")

    def run_pass(self, *, dry_run=False):
        write_vault(self.root, births())
        with mock.patch.object(entity_roster, "recount_stats", return_value={}):
            result = entity_roster.ensure_introduced_relatives(dry_run=dry_run)
        result["roster"] = json.loads(self.path.read_text(encoding="utf-8"))
        return result

    def test_dry_run_names_the_sons_and_writes_nothing(self):
        result = self.run_pass(dry_run=True)
        self.assertEqual({r["slug"] for r in result["introduced"]},
                         {"marnie-quill", "corbin-quill"})
        self.assertEqual({r["name"] for r in result["unintroduced"]},
                         {"Elliot Quill", "Graham Quill"})
        self.assertEqual(result["roster"]["entities"], [])

    def test_filed_once_with_the_spouse_pointer_and_idempotent(self):
        first = self.run_pass()
        rows = {r["slug"]: r for r in first["roster"]["entities"]}
        self.assertEqual(set(rows), {"marnie-quill", "corbin-quill"})
        self.assertEqual(rows["marnie-quill"]["relationship"], "sibling")
        self.assertEqual(rows["marnie-quill"]["born"]["best"], "1987-12-17")
        self.assertEqual(rows["corbin-quill"]["relationship"], "other")
        self.assertEqual(rows["corbin-quill"]["spouse_of"], "marnie-quill")
        self.assertEqual(rows["corbin-quill"]["born"]["best"], "1990-02-28")
        second = self.run_pass()
        self.assertEqual(second["filed"], 0)
        self.assertEqual(second.get("retired", []), [])
        self.assertEqual(second["roster"], first["roster"])

    def test_spouse_of_survives_a_roster_refresh(self):
        previous = self.run_pass()["roster"]
        kept, _ = entity_roster.apply_previous_decisions(
            [{"name": "Corbin Quill", "aliases": []}], previous)
        corbin = next(e for e in kept if e["name"] == "Corbin Quill")
        self.assertEqual(corbin.get("spouse_of"), "marnie-quill")


class AStrangersBirthIsNeverTheOwnersTests(unittest.TestCase):
    """`axis_membership.A_NAMED_OTHER_SUBJECT_IS_NEVER_THE_OWNERS`."""

    def rule(self, **kw):
        payload = {"occurrence_subject_scope": "owner",
                   "owner_timeline_relation": "participated",
                   "family_tier": axm.UNKNOWN_TIER, "before_owner_birth": False,
                   "named_other_subject": True}
        payload.update(kw)
        out = axm.axis_membership(**payload)
        return out["axis_membership"], out["axis_membership_reason"]

    def test_the_rule_itself(self):
        self.assertEqual(self.rule(), ("none", "subject_unresolved"))
        self.assertEqual(self.rule(family_tier=axm.IMMEDIATE_FAMILY_TIER),
                         ("family", "immediate_family_in_lifetime"))
        self.assertEqual(self.rule(before_owner_birth=True), ("none", "pre_birth"))
        # Not flagged: the owner's own occurrence stays his.
        self.assertEqual(self.rule(named_other_subject=False), ("owner", "lived"))

    def test_the_fold_keeps_the_four_births_off_his_axis(self):
        result = derive([owner_birth(), *births()], roster_snapshot=roster())
        by_label = {n["label"]: n for n in result.nodes}
        for name, _ in BIRTHS:
            node = by_label[f"{name}'s birth"]
            with self.subTest(name):
                self.assertEqual(node["axis_membership"], "none")
                self.assertEqual(node["axis_membership_reason"], "subject_unresolved")
                self.assertFalse(axm.on_owner_axis(node))
        found = [d for d in result.diagnostics.get("findings") or ()
                 if d.get("finding") == tt.DIAGNOSTIC_STRANGER_SUBJECT_UNRESOLVED]
        self.assertEqual(sorted(d["subject"] for d in found), sorted(n for n, _ in BIRTHS))

    def test_the_owners_own_birth_and_a_resolved_sister_are_untouched(self):
        sister = row("Marnie Quill", "marnie-quill", "sibling", born="1987-12-17")
        result = derive([owner_birth(), *births()[:1]], roster_snapshot=roster(sister))
        by_label = {n["label"]: n for n in result.nodes}
        self.assertEqual(by_label["Marnie Quill's birth"]["axis_membership"], "family")
        owner = [n for n in result.nodes if n.get("event_kind") == "birth"
                 and n["label"] != "Marnie Quill's birth"]
        self.assertTrue(owner and all(n["axis_membership"] == "owner" for n in owner))

    def test_every_once_per_subject_kind_is_covered(self):
        import identity_resolution as ir  # noqa: PLC0415

        for kind in ir.ONCE_PER_SUBJECT_EVENT_KINDS:
            with self.subTest(kind):
                self.assertTrue(tt._names_a_stranger(
                    {"event_kind": kind, "subject": "Blair Quill", "resolved": False,
                     "claims": []}, entries=[], owner="person/self", owner_names=OWNER_NAMES))
        for kind, subject in (("birth", "Dave"), ("birth", "self"), ("moment", "Blair Quill"),
                              ("birth", "David James Taylor"), ("birth", "birth")):
            with self.subTest(kind=kind, subject=subject):
                self.assertFalse(tt._names_a_stranger(
                    {"event_kind": kind, "subject": subject, "resolved": False, "claims": []},
                    entries=[], owner="person/self", owner_names=OWNER_NAMES))


if __name__ == "__main__":
    unittest.main()
