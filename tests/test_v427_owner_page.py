"""v427 (ADR 0047, design D4/D5) — the owner's page is the hub.

O1 (v426) marked the owner's roster row ``relationship: "self"`` and took away
its ``page_eligible``; this is the page half. Every vault here is SYNTHETIC: an
invented owner ("Theo", full name "Theodore Ash Marlow", aliases "Theo Marlow"
and "Theodore Marlow", the wrong possessive "Theo's kids") with the SHAPE of a
pre-v426 roster — the owner rostered as a page-eligible person with a mention
page at ``wiki/people/theo.md`` — and invented relatives. The compile and the
viewer run in a subprocess against a throwaway vault.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SYSTEM = ROOT / "system"
sys.path.insert(0, str(SYSTEM))
sys.path.insert(0, str(ROOT / "tests"))

import owner_identity as oi  # noqa: E402
import wiki_compile  # noqa: E402
from tempdirs import root_parent_tmp  # noqa: E402

PROFILE = {"name": "Theo", "full_name": "Theodore Ash Marlow"}
HUB = "theodore-ash-marlow"

BANK = """# Bank

## A: Origins
- [x] A1: Earliest memory? *(2026-01-01)*

## B: Work
- [x] B1: First job? *(2026-01-02)*

## Focuses

## K: Focus — Mara
- [x] K1: What was Mara like when you met? *(2026-01-01)*
"""

ANSWERS = {
    "A1": "Theo Marlow grew up by the harbor. Mara Quill lived two doors down.",
    "B1": "Theo's first job was at the cannery; Ned Orr hired him.",
    "K1": "Mara Quill laughed on the dock the day we met.",
}

OLD_OWNER_PAGE = """---
title: "Theo"
type: person
status: active
visibility: owner_only
sensitivity: private
origin: mention
synthesized: false
person_ref: "person/theo"
created: 2026-09-01
last_updated: 2026-09-01
sources:
  - "answers/A1.md"
sources_count: 1
related:
---

# Theo

> A person in the author's life, compiled automatically from 1 mentions.
"""


def person(name, slug, **extra):
    row = {"name": name, "slug": slug, "aliases": [], "qualifies": True, "score": 9,
           "unique_answers": 2, "page_eligible": False, "focus": None, "folded_into": None}
    row.update(extra)
    return row


def roster():
    return [
        # The pre-v426 shape: the owner as an ordinary page-eligible person.
        person("Theo", "theo", aliases=["Theo Marlow", "Theodore Marlow", "Theo's kids"],
               page_eligible=True, unique_answers=40, score=30),
        person("Mara Quill", "mara-quill", focus="mara", relationship="spouse",
               unique_answers=3),
        person("Ned Orr", "ned-orr", page_eligible=True, relationship="friend"),
        person("Ivy Hale", "ivy-hale", relationship="friend"),
    ]


class Vault:
    def __init__(self, case: unittest.TestCase, *, owner_page: bool = True,
                 drafts: dict | None = None):
        self.root = root_parent_tmp(case, ROOT, prefix="lifehug-v427-")
        (self.root / "state" / "entity_rosters").mkdir(parents=True)
        (self.root / "answers").mkdir()
        (self.root / "question-bank.md").write_text(BANK, encoding="utf-8")
        (self.root / "profile.yaml").write_text(
            'name: "Theo"\nfull_name: "Theodore Ash Marlow"\n', encoding="utf-8")
        (self.root / "state" / "rotation.json").write_text(json.dumps({
            "version": 1, "current_pass": 1, "pass_names": ["skeleton"],
            "last_question_id": None, "last_asked_at": None, "questions_asked": 0,
            "questions_answered": 0, "next_question_id": None, "focus_frequency": 4}))
        (self.root / "state" / "coverage.json").write_text(json.dumps({
            "version": 1, "last_updated": None, "categories": {}}))
        (self.root / "state" / "entity_rosters" / "person.json").write_text(
            json.dumps({"version": 1, "type": "person", "entities": roster()}))
        for qid, body in ANSWERS.items():
            (self.root / "answers" / f"{qid}.md").write_text(
                f"---\nquestion_id: {qid}\n---\n{body}\n", encoding="utf-8")
        if owner_page:
            (self.root / "wiki" / "people").mkdir(parents=True)
            (self.root / "wiki" / "people" / "theo.md").write_text(OLD_OWNER_PAGE, encoding="utf-8")
        self.env = {**os.environ, "LIFEHUG_VAULT_ROOT": str(self.root),
                    "LIFEHUG_FRAMEWORK_SYSTEM_DIR": str(SYSTEM),
                    "PYTHONDONTWRITEBYTECODE": "1"}
        if drafts:
            synth = Path(self.run_py("-c", "import sys; sys.path.insert(0, %r); "
                                     "import lifehug_core as c; print(c.SYNTHESIS_DIR)"
                                     % str(SYSTEM)).strip())
            synth.mkdir(parents=True, exist_ok=True)
            for slug, text in drafts.items():
                (synth / f"{slug}.md").write_text(text, encoding="utf-8")

    def run_py(self, *args: str) -> str:
        done = subprocess.run([sys.executable, *args], env=self.env, capture_output=True,
                              text=True, timeout=180, cwd=self.root)
        assert done.returncode == 0, done.stderr or done.stdout
        return done.stdout

    def compile(self) -> str:
        return self.run_py(str(SYSTEM / "wiki_compile.py"), "--no-ai")

    def serve(self, expression: str):
        code = ("import sys, json; sys.path.insert(0, %r); import serve_wiki as sw; "
                "print(json.dumps(%s))" % (str(SYSTEM), expression))
        return json.loads(self.run_py("-c", code).strip().splitlines()[-1])

    def page(self, rel: str) -> str:
        return (self.root / "wiki" / rel).read_text(encoding="utf-8")


class TheOwnersPageIsTheHub(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._holder = unittest.TestCase()
        cls.vault = Vault(cls._holder, drafts={
            # A page whose prose and related name the owner's old page.
            "ned-orr": "Related: theo, mara-quill\n\nNed Orr hired [[Theo]] at the cannery; "
                       "later [[theo|his boss's favourite]] ran the line.",
        })
        cls.out = cls.vault.compile()

    @classmethod
    def tearDownClass(cls):
        cls._holder.doCleanups()

    def test_the_old_person_page_is_a_stub_to_the_hub(self):
        stub = self.vault.page("people/theo.md")
        self.assertIn(f"redirect_to: life/{HUB}", stub)
        self.assertIn("origin: redirect", stub)
        self.assertIn('person_ref: "person/theo"', stub)
        self.assertIn(f"This page moved to [[{HUB}]].", stub)
        self.assertTrue((self.vault.root / "wiki" / "life" / f"{HUB}.md").is_file())

    def test_a_second_compile_keeps_the_stub(self):
        self.vault.compile()
        self.assertIn(f"redirect_to: life/{HUB}", self.vault.page("people/theo.md"))

    def test_the_hub_carries_the_record(self):
        hub = self.vault.page(f"life/{HUB}.md")
        for line in ('person_ref: "person/theo"', 'handle: "@theo"', "aliases:",
                     '  - "Theo Marlow"', '  - "Theodore Marlow"', 'relationship: "self"'):
            self.assertIn(line, hub)
        self.assertNotIn("Theo's kids", hub)

    def test_relationship_pages_name_the_hub_and_the_hub_lists_them(self):
        rel = self.vault.page("relationships/theo-and-mara.md")
        self.assertIn(f'  - "[[{HUB}]]"', rel)
        self.assertIn('  - "[[mara-quill]]"', rel)
        hub = self.vault.page(f"life/{HUB}.md")
        self.assertIn('  - "[[theo-and-mara]]"', hub)

    def test_links_to_the_owner_repoint_to_the_hub(self):
        ned = self.vault.page("people/ned-orr.md")
        self.assertIn(f'  - "[[{HUB}]]"', ned)
        self.assertNotIn('"[[theo]]"', ned)
        self.assertIn("hired [[Theodore Ash Marlow]] at the cannery", ned)
        self.assertIn("[[Theodore Ash Marlow|his boss's favourite]]", ned)

    def test_the_index_lists_the_hub_once_and_never_the_stub(self):
        index = self.vault.page("index.md")
        self.assertEqual(index.count(f"wiki/life/{HUB}.md"), 1)
        self.assertNotIn("wiki/people/theo.md", index)

    def test_the_roster_row_is_self(self):
        data = json.loads(self.vault.run_py(
            "-c", "import sys, json; sys.path.insert(0, %r); import entity_roster as er; "
                  "print(json.dumps(er.load_roster('person')))" % str(SYSTEM)))
        row = next(e for e in data["entities"] if e["slug"] == "theo")
        self.assertEqual(row["relationship"], "self")
        self.assertFalse(row["page_eligible"])

    # --- the viewer -------------------------------------------------------

    def test_graph_has_one_owner_node(self):
        graph = self.vault.serve("sw.graph_data()")
        ids = [n["id"] for n in graph["nodes"]]
        self.assertIn(f"wiki/life/{HUB}.md", ids)
        self.assertNotIn("wiki/people/theo.md", ids)
        self.assertNotIn("owner", {n["kind"] for n in graph["nodes"]})
        rels = {e["page"]: e for e in graph["edges"] if e.get("kind") == "relationship"}
        edge = rels["wiki/relationships/theo-and-mara.md"]
        self.assertEqual({edge["source"], edge["target"]},
                         {f"wiki/life/{HUB}.md", "wiki/people/mara-quill.md"})
        # The stub's edge (Ned's related: theo) lands on the hub.
        pairs = {tuple(sorted((e["source"], e["target"]))) for e in graph["edges"]}
        self.assertIn(tuple(sorted(("wiki/people/ned-orr.md", f"wiki/life/{HUB}.md"))), pairs)

    def test_page_index_sends_the_stub_and_every_spelling_to_the_hub(self):
        index = self.vault.serve("sw.page_index()")
        for slug in ("theo", "theo-marlow", "theodore-marlow", HUB):
            self.assertEqual(index[slug], f"wiki/life/{HUB}.md", slug)

    def test_nav_people_group_shows_you_once(self):
        nav = self.vault.serve("sw.nav_html()")
        self.assertEqual(nav.count("You · Theodore Ash Marlow"), 1)
        self.assertNotIn("wiki/people/theo.md", nav)
        self.assertNotIn(">Theo<", nav)

    def test_known_without_page_and_add_list_exclude_the_owner(self):
        known = self.vault.serve("[r['slug'] for r in sw.known_without_page('person')]")
        self.assertNotIn("theo", known)
        self.assertIn("ivy-hale", known)
        addable = self.vault.serve("[r['slug'] for r in sw._roster_without_focus()]")
        self.assertNotIn("theo", addable)
        self.assertIn("ivy-hale", addable)

    def test_the_add_flash_refuses_the_owner(self):
        for typed in ("Theo", "Theodore Marlow", "Theo (narrator)"):
            with self.subTest(typed=typed):
                back, flash, job = self.vault.serve(
                    "list(sw.act_focus_new({'search': [%r], 'tier': ['basic']}))" % typed)
                self.assertIsNone(job)
                self.assertIn("THE_OWNER_IS_NOT_A_PERSON_FOCUS", flash)

    def test_identity_header_renders_on_the_hub(self):
        header = self.vault.serve(
            "sw.identity_header_html(open(sw.WIKI_DIR / 'life' / %r).read())" % f"{HUB}.md")
        self.assertIn('data-record="person/theo"', header)
        self.assertIn("@theo", header)
        self.assertIn("Theo Marlow", header)
        self.assertIn("you", header)
        self.assertIn("Fold it into this one", header)  # others fold INTO the owner
        other = self.vault.serve(
            "sw.identity_header_html(open(sw.WIKI_DIR / 'people' / 'ned-orr.md').read())")
        self.assertNotIn('value="theo"', other)  # never the owner as the loser

    def test_foundation_primary_row_says_it_is_you(self):
        holder = unittest.TestCase()
        self.addCleanup(holder.doCleanups)
        vault = Vault(holder)
        vault.run_py("-c", "import sys; sys.path.insert(0, %r); import roadmap; "
                           "roadmap.rebuild_roadmap(write=True)" % str(SYSTEM))
        _title, body, _wide = vault.serve("list(sw.view_foundation())")
        self.assertEqual(body.count('">you</span>'), 1)
        # With a roadmap, the converter gives the owner's row the primary Focus.
        data = json.loads(vault.run_py(
            "-c", "import sys, json; sys.path.insert(0, %r); import entity_roster as er; "
                  "print(json.dumps(er.load_roster('person')))" % str(SYSTEM)))
        row = next(e for e in data["entities"] if e["slug"] == "theo")
        self.assertEqual(row["focus"], "my-life")

    def test_the_entity_lane_never_lists_the_owner(self):
        html = self.vault.serve("sw._entities_section_html()")
        self.assertNotIn("<td>Theo</td>", html)
        self.assertIn("<td>Ivy Hale</td>", html)
        # Folding a row INTO the owner stays offered, labelled "You".
        self.assertIn('<option value="theo">You (Theo)</option>', html)


class NoStubWithoutAPage(unittest.TestCase):
    def test_no_page_no_stub_and_no_person_page_planned(self):
        holder = unittest.TestCase()
        self.addCleanup(holder.doCleanups)
        vault = Vault(holder, owner_page=False)
        vault.compile()
        self.assertFalse((vault.root / "wiki" / "people" / "theo.md").exists())
        self.assertTrue((vault.root / "wiki" / "life" / f"{HUB}.md").is_file())


class Units(unittest.TestCase):
    def test_redirect_stub_text_takes_a_target(self):
        desc = {"title": "Mara", "slug": "mara-quill", "identity": {"ref": "person/mara-quill"}}
        self.assertIn("redirect_to: people/mara-quill", wiki_compile.redirect_stub_text(desc))
        text = wiki_compile.redirect_stub_text(desc, redirect_to=f"life/{HUB}")
        self.assertIn(f"redirect_to: life/{HUB}", text)
        self.assertIn(f"[[{HUB}]]", text)

    def test_owner_stub_text(self):
        text = wiki_compile.owner_stub_text("Theo", HUB, "person/theo")
        self.assertIn(f"redirect_to: life/{HUB}", text)
        self.assertIn('person_ref: "person/theo"', text)
        self.assertEqual(oi.hub_target(PROFILE), f"life/{HUB}")

    def test_plan_entities_skips_the_self_row(self):
        rows = {"entities": [person("Theo", "theo", relationship="self", page_eligible=True)]}
        answers = {"A1": {"id": "A1", "source": "answers/A1.md", "body": "Theo Theo",
                          "category": "A"}}
        self.assertEqual(wiki_compile.plan_entities("person", answers, {}, rows, set()), [])

    def test_owner_spellings_drop_possessives(self):
        rows = {"entities": [person("Theo", "theo", relationship="self",
                                    aliases=["Theo Marlow", "Theo's kids"])]}
        spellings = oi.owner_spellings(PROFILE, rows)
        self.assertIn("Theo Marlow", spellings)
        self.assertIn(HUB, spellings)
        self.assertNotIn("Theo's kids", spellings)
        self.assertEqual(oi.owner_page_slugs(PROFILE, rows), ("theo",))

    def test_repoint_wikilinks(self):
        text = "met [[Theo]] and [[theo|him]] and [[Mara]]"
        self.assertEqual(wiki_compile.repoint_wikilinks(text, ["theo"], "Theodore Ash Marlow"),
                         "met [[Theodore Ash Marlow]] and [[Theodore Ash Marlow|him]] and [[Mara]]")


if __name__ == "__main__":
    unittest.main()
