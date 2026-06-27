import importlib.util
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SYSTEM = ROOT / "system"
sys.path.insert(0, str(SYSTEM))


def load(name):
    spec = importlib.util.spec_from_file_location(name, SYSTEM / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


BANK = """# Lifehug — Question Bank

## A: Origins
- [x] A1: earliest memory *(2026-01-01)*

## Project Categories

## F: The Problem (Etherfuse Story)
- [ ] F1: the problem

## Focuses

## K: Focus — Mom
- [x] K1: about mom *(2026-01-02)*
"""


class ScaffoldTests(unittest.TestCase):
    def setUp(self):
        self.rm = load("roadmap")

    def test_next_free_letter_skips_used(self):
        # A, F, K used → next free is B.
        self.assertEqual(self.rm.next_free_letter(BANK), "B")

    def test_theme_lands_under_focuses(self):
        new_md, letter = self.rm.scaffold_category(BANK, "Faith", "theme")
        # The new category header exists and sits after the Focuses section.
        self.assertIn(f"## {letter}: Faith", new_md)
        self.assertLess(new_md.index("## Focuses"), new_md.index(f"## {letter}: Faith"))
        # And it parses with the focus group.
        cats = self.rm.parse_categories(new_md)
        self.assertEqual(cats[letter]["group"], "focus")

    def test_project_lands_under_project_categories_with_tag(self):
        new_md, letter = self.rm.scaffold_category(BANK, "New Book", "project", tag="New Book")
        self.assertIn(f"## {letter}: New Book (New Book)", new_md)
        cats = self.rm.parse_categories(new_md)
        self.assertEqual(cats[letter]["group"], "project")
        # The project category must come before the Focuses section.
        self.assertLess(new_md.index(f"## {letter}: New Book"), new_md.index("## Focuses"))

    def test_scaffold_creates_missing_section(self):
        minimal = "# Bank\n\n## A: Origins\n- [ ] A1: q\n"
        new_md, letter = self.rm.scaffold_category(minimal, "Faith", "theme")
        self.assertIn("## Focuses", new_md)
        self.assertIn(f"## {letter}: Faith", new_md)


class BulkPromoteTests(unittest.TestCase):
    def setUp(self):
        self.qc = load("question_candidates")

    def test_promote_neighborhood_scopes_and_dedupes(self):
        bank = "# Bank\n\n## Focuses\n\n## N: Faith\n"
        data = {"version": 1, "candidates": [
            {"id": "c1", "text": "What is your earliest memory of faith?",
             "status": "candidate", "neighborhood_id": "nbhd-faith", "priority": 0.9},
            {"id": "c2", "text": "Describe a moment your belief was tested.",
             "status": "candidate", "neighborhood_id": "nbhd-faith", "priority": 0.8},
            {"id": "c3", "text": "unrelated question",
             "status": "candidate", "neighborhood_id": "nbhd-other", "priority": 0.5},
        ]}
        new_bank, ids = self.qc.promote_neighborhood(data, bank, "nbhd-faith", "N")
        self.assertEqual(ids, ["N1", "N2"])
        self.assertIn("N1:", new_bank)
        self.assertIn("N2:", new_bank)
        # Other-neighborhood candidate untouched.
        self.assertEqual(data["candidates"][2]["status"], "candidate")
        # Faith candidates marked promoted.
        self.assertTrue(all(c["status"] == "promoted" for c in data["candidates"][:2]))

    def test_promote_neighborhood_skips_duplicates(self):
        bank = "# Bank\n\n## Focuses\n\n## N: Faith\n- [ ] N1: Already here.\n"
        data = {"version": 1, "candidates": [
            {"id": "c1", "text": "Already here.", "status": "candidate",
             "neighborhood_id": "nbhd-faith", "priority": 0.9},
        ]}
        _, ids = self.qc.promote_neighborhood(data, bank, "nbhd-faith", "N")
        self.assertEqual(ids, [])
        self.assertEqual(data["candidates"][0]["status"], "candidate")


if __name__ == "__main__":
    unittest.main()
