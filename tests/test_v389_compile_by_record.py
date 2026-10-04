"""v389 (ADR 0043 "Pages are views") — compile by record, and the viewer's
identity header.

lifehug-platform `docs/design/identity.md` §4.1.7–8 / P6 (compile half). Every
vault here is SYNTHETIC: invented people, an invented Focus, an invented state.
The compile and the viewer run in a subprocess against a throwaway vault, the
way a real install runs them.
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

import focus_pages  # noqa: E402
import jobs  # noqa: E402
import wiki_compile  # noqa: E402
from tempdirs import root_parent_tmp  # noqa: E402

BANK = """# Bank

## A: Origins
- [x] A1: Earliest memory? *(2026-01-01)*

## Focuses

## K: Focus — Mara
- [x] K1: What was Mara like when you met? *(2026-01-01)*
"""


def person(name, slug, **extra):
    row = {"name": name, "slug": slug, "aliases": [], "qualifies": True, "score": 9,
           "unique_answers": 2, "page_eligible": False, "focus": None, "folded_into": None}
    row.update(extra)
    return row


class Vault:
    """A throwaway vault plus a way to run the compiler and the viewer in it."""

    def __init__(self, case: unittest.TestCase, rosters: dict, answers: dict):
        self.root = root_parent_tmp(case, ROOT, prefix="lifehug-v389-")
        (self.root / "state" / "entity_rosters").mkdir(parents=True)
        (self.root / "answers").mkdir()
        (self.root / "question-bank.md").write_text(BANK, encoding="utf-8")
        (self.root / "state" / "rotation.json").write_text(json.dumps({
            "version": 1, "current_pass": 1,
            "pass_names": ["skeleton", "depth", "connections", "polish"],
            "last_question_id": None, "last_asked_at": None, "questions_asked": 0,
            "questions_answered": 0, "next_question_id": None, "focus_frequency": 4}))
        (self.root / "state" / "coverage.json").write_text(json.dumps({
            "version": 1, "last_updated": None,
            "categories": {"A": {"total": 1, "answered": 1, "status": "green"}}}))
        for kind, entities in rosters.items():
            (self.root / "state" / "entity_rosters" / f"{kind}.json").write_text(
                json.dumps({"version": 1, "type": kind, "entities": entities}))
        for qid, body in answers.items():
            (self.root / "answers" / f"{qid}.md").write_text(
                f"---\nquestion_id: {qid}\n---\n{body}\n", encoding="utf-8")
        self.env = {**os.environ, "LIFEHUG_VAULT_ROOT": str(self.root),
                    "LIFEHUG_FRAMEWORK_SYSTEM_DIR": str(SYSTEM),
                    "PYTHONDONTWRITEBYTECODE": "1"}

    def run_py(self, *args: str) -> str:
        done = subprocess.run([sys.executable, *args], env=self.env, capture_output=True,
                              text=True, timeout=120, cwd=self.root)
        assert done.returncode == 0, done.stderr or done.stdout
        return done.stdout

    def compile(self) -> str:
        return self.run_py(str(SYSTEM / "wiki_compile.py"), "--no-ai")

    def serve(self, expression: str) -> str:
        code = ("import sys; sys.path.insert(0, %r); import serve_wiki as sw; %s"
                % (str(SYSTEM), expression))
        return self.run_py("-c", code)

    def page(self, rel: str) -> str:
        return (self.root / "wiki" / rel).read_text(encoding="utf-8")

    def tree(self) -> dict:
        return {p.relative_to(self.root).as_posix(): p.read_bytes()
                for p in sorted((self.root / "wiki").rglob("*")) if p.is_file()}


def mara_vault(case, **overrides) -> Vault:
    people = overrides.pop("people", None) or [
        person("Mara Quill", "mara-quill", aliases=["Mara Ann Voss"], focus="mara",
               relationship="spouse", unique_answers=3),
        person("Ned Orr", "ned-orr", aliases=["Neddy"], page_eligible=True,
               relationship="friend"),
    ]
    answers = overrides.pop("answers", None) or {
        "K1": "Mara Ann Voss laughed on the dock.",
        "A1": "Neddy told me about the red kitchen.",
    }
    rosters = {"person": people}
    rosters.update(overrides)
    return Vault(case, rosters, answers)


class PagesAreViewsOfRecords(unittest.TestCase):

    def test_frontmatter_carries_the_record_and_a_focus_persons_aliases_reach_the_scan(self):
        vault = mara_vault(self)
        vault.compile()
        page = vault.page("people/mara-quill.md")
        for line in ('person_ref: "person/mara-quill"', 'handle: "@mara-quill"',
                     'relationship: "spouse"', "answers: 3", "aliases:",
                     '  - "Mara Ann Voss"', "origin: focus"):
            self.assertIn(line, page)
        # The alias is the only place the Focus's own answer names her: the page
        # found K1 through it (and the mention in A1 is not hers).
        self.assertIn("answers/K1.md", page)
        # The reader the platform shares parses it without a YAML library.
        meta, _ = wiki_compile.split_frontmatter(page)
        self.assertEqual(meta["person_ref"], "person/mara-quill")
        self.assertEqual(meta["answers"], 3)

    def test_the_old_focus_path_is_a_one_line_redirect_stub(self):
        vault = mara_vault(self)
        vault.compile()
        stub = vault.page("people/mara.md")
        self.assertIn("redirect_to: people/mara-quill", stub)
        self.assertIn("origin: redirect", stub)
        self.assertIn('person_ref: "person/mara-quill"', stub)
        body = stub.split("---\n")[-1].strip()
        self.assertEqual(body, "This page moved to [[mara-quill]].")
        self.assertTrue(focus_pages.is_redirect_stub(stub))
        self.assertFalse(focus_pages.is_redirect_stub(vault.page("people/mara-quill.md")))
        # A stub is never an index entry; the record's page is.
        index = vault.page("index.md")
        self.assertIn("people/mara-quill.md", index)
        self.assertNotIn("people/mara.md", index)

    def test_a_record_whose_slug_equals_its_focus_needs_no_stub(self):
        vault = mara_vault(self, people=[person("Mara", "mara", focus="mara")],
                           answers={"K1": "Mara laughed.", "A1": "x"})
        vault.compile()
        self.assertEqual(sorted(p.name for p in (vault.root / "wiki/people").glob("*.md")),
                         ["mara.md"])

    def test_a_second_compile_is_byte_stable(self):
        vault = mara_vault(self)
        vault.compile()
        first = vault.tree()
        self.assertIn("0 page updates", vault.compile())
        self.assertEqual(first, vault.tree())

    def test_relationship_page_keeps_its_path_and_names_the_record(self):
        vault = mara_vault(self)
        vault.compile()
        edge = vault.page("relationships/me-and-mara.md")
        self.assertIn('person_ref: "person/mara-quill"', edge)
        self.assertIn("[[mara-quill]]", edge)

    def test_a_focus_page_with_prose_survives_the_move_keylessly(self):
        vault = mara_vault(self)
        old = vault.root / "wiki" / "people"
        old.mkdir(parents=True)
        (old / "mara.md").write_text(
            '---\ntitle: "Mara"\ntype: person\norigin: focus\nsynthesized: true\n---\n\n'
            "# Mara\n\nHand-synthesized prose that must not be lost.\n", encoding="utf-8")
        vault.compile()
        self.assertIn("Hand-synthesized prose", vault.page("people/mara-quill.md"))
        self.assertIn("redirect_to", vault.page("people/mara.md"))


class FoldOrphanSafety(unittest.TestCase):

    def test_a_folded_records_page_goes_and_no_live_records_page_does(self):
        people = [
            person("Mara Quill", "mara-quill", aliases=["Mara Ann Voss"], focus="mara"),
            person("Mari", "mari", page_eligible=True, folded_into="mara-quill"),
            person("Ned Orr", "ned-orr", page_eligible=True),
            person("Pia Lund", "pia-lund", page_eligible=True),
        ]
        vault = mara_vault(self, people=people, answers={
            "K1": "Mara Ann Voss laughed.", "A1": "Ned Orr fixed the porch."})
        pages = vault.root / "wiki" / "people"
        pages.mkdir(parents=True)
        for slug in ("mari", "ned-orr", "pia-lund"):
            (pages / f"{slug}.md").write_text(
                f'---\ntitle: "{slug}"\ntype: person\norigin: mention\nsynthesized: false\n'
                "---\n\n# x\n", encoding="utf-8")
        vault.compile()
        self.assertFalse((pages / "mari.md").exists())      # the folded pointer's page
        self.assertTrue((pages / "ned-orr.md").exists())    # planned this run
        self.assertTrue((pages / "pia-lund.md").exists())   # live, eligible, unmentioned: kept
        self.assertTrue((pages / "mara-quill.md").exists())
        self.assertTrue((pages / "mara.md").exists())       # the stub is not an orphan

    def test_links_to_a_folded_or_moved_page_follow_the_pointer(self):
        roster = {"entities": [person("Mari", "mari", folded_into="mara-quill"),
                               person("Mara Quill", "mara-quill")]}
        moves = wiki_compile.fold_repoints([roster], {"mara-quill", "me"})
        self.assertEqual(moves, {"mari": "mara-quill"})
        descs = [
            {"slug": "mara-quill", "legacy_slug": "mara", "sources": ["a"], "seed_related": []},
            {"slug": "me", "legacy_slug": "", "sources": ["b"], "seed_related": []},
        ]
        synths = {"mara-quill": {"related": []}, "me": {"related": ["mara", "mari"]}}
        related, backlinks = wiki_compile.compute_crosslinks(descs, synths, moves)
        self.assertEqual(related["me"], ["mara-quill"])
        self.assertEqual(backlinks["mara-quill"], ["me"])  # the re-pointed link is her backlink

    def test_a_stale_stub_goes_when_the_focus_leaves_the_record(self):
        vault = mara_vault(self)
        vault.compile()
        roster = vault.root / "state/entity_rosters/person.json"
        data = json.loads(roster.read_text())
        data["entities"][0]["focus"] = None
        data["entities"][0]["page_eligible"] = True
        roster.write_text(json.dumps(data))
        vault.compile()
        self.assertNotIn("origin: redirect", vault.page("people/mara.md"))


class OtherTypes(unittest.TestCase):

    def test_place_pages_carry_record_ref_and_keep_their_contained_list(self):
        def place(name, slug, parent=None):
            row = {"name": name, "slug": slug, "aliases": [], "qualifies": True,
                   "place_kind": "city", "page_eligible": True, "score": 0.0,
                   "unique_answers": 2}
            if parent:
                row["located_in"] = f"place/{parent}"
            return row
        vault = mara_vault(self, place=[place("California", "california"),
                                        place("Yucaipa", "yucaipa", "california")],
                           answers={"K1": "Mara Ann Voss laughed.",
                                    "A1": "We left California.",
                                    "A2": "California again."})
        vault.compile()
        page = vault.page("places/california.md")
        self.assertIn('record_ref: "place/california"', page)
        self.assertIn('handle: "@california"', page)
        self.assertNotIn("person_ref", page)
        self.assertIn("## Places Within\n- Yucaipa", page)


class Viewer(unittest.TestCase):

    def test_the_person_page_shows_the_records_identity_header(self):
        vault = mara_vault(self)
        vault.compile()
        text = vault.page("people/mara-quill.md")
        out = vault.serve(f"print(sw.identity_header_html({text!r}))")
        for needle in ("Mara Quill", "@mara-quill", "Mara Ann Voss", "spouse", "3 answers",
                       "Focus: Mara", "Add name", 'name="retract_alias"'):
            self.assertIn(needle, out)
        self.assertNotIn("%", out)

    def test_the_header_reads_the_record_not_the_prose(self):
        vault = mara_vault(self)
        vault.compile()
        roster = vault.root / "state/entity_rosters/person.json"
        data = json.loads(roster.read_text())
        data["entities"][0]["aliases"].append("Marabelle")
        roster.write_text(json.dumps(data))
        text = vault.page("people/mara-quill.md")  # compiled BEFORE the alias
        self.assertIn("Marabelle", vault.serve(f"print(sw.identity_header_html({text!r}))"))

    def test_the_people_index_lists_records_without_a_page(self):
        people = [
            person("Mara Quill", "mara-quill", focus="mara"),
            person("Pia Lund", "pia-lund", aliases=["Piapia"], unique_answers=4),
            person("Mari", "mari", folded_into="mara-quill"),
        ]
        vault = mara_vault(self, people=people)
        vault.compile()
        out = vault.serve("print(sw._index_with_known_people("
                          "'<h2>People</h2><ul><li>x</li></ul><h2>Themes</h2>'))")
        self.assertIn("Known, no page yet", out)
        self.assertIn("Pia Lund", out)
        self.assertIn("Piapia", out)
        self.assertIn("4 answers", out)
        self.assertNotIn("Mara Quill", out)   # has a page
        self.assertNotIn(">Mari<", out)       # a pointer, not a record
        self.assertLess(out.index("Known, no page yet"), out.index("<h2>Themes</h2>"))

    def test_wiki_pages_hides_the_stub_and_the_old_path_redirects(self):
        vault = mara_vault(self)
        vault.compile()
        names = vault.serve("print([p.name for p in sw.wiki_pages()])")
        self.assertIn("mara-quill.md", names)
        self.assertNotIn("'mara.md'", names)

    def test_review_row_offers_alias_and_fold(self):
        people = [person("Pia Lund", "pia-lund"), person("Mara Quill", "mara-quill")]
        vault = mara_vault(self, people=people)
        out = vault.serve("print(sw._entities_section_html())")
        self.assertIn('name="alias"', out)
        self.assertIn('name="fold_into"', out)
        self.assertIn("This is that record", out)

    def test_a_graduate_verdict_survives_an_alias_edit(self):
        vault = mara_vault(self)
        out = vault.serve("print(sw._verdict_keeping({'owner_verdict': 'graduate'}), "
                          "sw._verdict_keeping({'owner_verdict': 'never'}), sw._verdict_keeping({}))")
        self.assertEqual(out.split(), ["graduate", "never", "clear"])


class Jobs(unittest.TestCase):

    def test_the_verdict_job_speaks_the_new_flags(self):
        (invocation,) = jobs._build_entity_verdict({
            "type": "person", "slug": "pia-lund", "verdict": "clear",
            "aliases": ["Piapia"], "fold_into": "mara-quill",
            "retract_aliases": ["Pi"]})
        argv = list(invocation.arguments)
        for flag in ("--alias", "Piapia", "--fold-into", "mara-quill", "--retract-alias=Pi"):
            self.assertIn(flag, argv)

    def test_a_bad_fold_target_is_refused_before_argv(self):
        with self.assertRaises(ValueError):
            jobs._build_entity_verdict({"type": "person", "slug": "a", "verdict": "clear",
                                        "fold_into": "../x"})


if __name__ == "__main__":
    unittest.main()
