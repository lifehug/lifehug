"""Tests for v127 Studio compute (system/studio.py).

Covers compute_works (outputs/ pieces + book.compute_books() projects grouped
by Focus, with __thoughts__/__unfiled__ trailing groups), assemble_book (the
one mutation: composing a book-project Focus's drafted chapters into a
versioned manuscript artifact), and the jobs.py "artifact-assemble" builder.
Conventions follow tests/test_wiki_views.py: synthetic fixtures under a real
temp dir (never /var/folders — the no-follow vault I/O authority rejects
its symlinked prefix on macOS), module attributes monkeypatched directly.
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SYSTEM = ROOT / "system"
sys.path.insert(0, str(SYSTEM))

import artifact  # noqa: E402
import book  # noqa: E402
import jobs  # noqa: E402
import roadmap  # noqa: E402
import studio  # noqa: E402


LIFE_FOCUS = {
    "id": "life", "label": "My Life", "type": "life_story", "primary": True,
    "tier": "standard", "objective": "story", "deliverable": "book",
    "categories": ["A", "B"], "target_depth": 4, "phase": "active", "wiki_node": None,
}
MOM_FOCUS = {
    "id": "mom", "label": "Mom", "type": "person", "tier": "standard",
    "objective": "story of mom", "deliverable": "letter", "categories": ["K"],
    "target_depth": 10, "phase": "active", "wiki_node": None,
}
QUESTION_BANK = (
    "## A: Origins\n- [x] A1: Earliest? *(2026-01-01)*\n- [ ] A2: Where?\n"
    "## B: Becoming\n- [ ] B1: What changed?\n"
)


class StudioTestBase(unittest.TestCase):
    """Shared fixture plumbing: a real-path tmp dir + module attribute saves."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(dir=ROOT.parent))
        self._saved = {
            (studio, "OUTPUTS_DIR"): studio.OUTPUTS_DIR,
            (studio, "QUESTIONS_FILE"): studio.QUESTIONS_FILE,
            (book, "OUTPUTS_DIR"): book.OUTPUTS_DIR,
            (book, "QUESTIONS_FILE"): book.QUESTIONS_FILE,
            (book, "CLASSIFICATIONS_DIR"): book.CLASSIFICATIONS_DIR,
            (book, "WIKI_DIR"): book.WIKI_DIR,
            (roadmap, "ROADMAP_FILE"): roadmap.ROADMAP_FILE,
            (roadmap, "QUESTIONS_FILE"): roadmap.QUESTIONS_FILE,
            (artifact, "OUTPUTS_DIR"): artifact.OUTPUTS_DIR,
            (artifact, "REPO_DIR"): artifact.REPO_DIR,
        }
        outputs = self.tmp / "outputs"
        outputs.mkdir(parents=True, exist_ok=True)
        qbank = self._write("question-bank.md", QUESTION_BANK)
        for mod in (studio, book, roadmap):
            mod.QUESTIONS_FILE = qbank
        for mod in (studio, book, artifact):
            mod.OUTPUTS_DIR = outputs
        book.CLASSIFICATIONS_DIR = self.tmp / "no-classifications"
        book.WIKI_DIR = self.tmp / "no-wiki"
        artifact.REPO_DIR = self.tmp
        roadmap.ROADMAP_FILE = self._write("roadmap.json", {
            "version": 1, "focuses": [LIFE_FOCUS, MOM_FOCUS],
        })

    def tearDown(self):
        for (mod, name), val in self._saved.items():
            setattr(mod, name, val)

    def _write(self, name, data):
        p = self.tmp / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(data if isinstance(data, str) else json.dumps(data))
        return p

    def _write_chapter_a(self, body: str, *, version: int = 1) -> None:
        self._write("outputs/chapter-a/meta.yaml",
                    "title: chapter-a\nformat: chapter\nsubject: Origins\n"
                    "categories: [A]\ncreated: 2026-02-01\n")
        self._write(f"outputs/chapter-a/v{version}.md", body)


class ComputeWorksTests(StudioTestBase):
    def _populate_pieces(self):
        self._write_chapter_a("Chapter A body one.\n")
        self._write("outputs/letter-mom/meta.yaml",
                    "title: letter-mom\nformat: letter\nsubject: Mom\n"
                    "categories: [K]\ncreated: 2026-03-01\n")
        self._write("outputs/letter-mom/v1.md", "Dear Mom, thank you.\n")
        self._write("outputs/my-essay/meta.yaml",
                    "title: my-essay\nformat: essay\nsubject: ''\ncreated: 2026-04-01\n")
        self._write("outputs/my-essay/v1.md", "# Essay\n\nSome thoughts.\n")
        self._write("outputs/orphan-piece/v1.md", "No metadata here.\n")

    def test_groups_pieces_and_projects_by_focus_in_roadmap_order(self):
        self._populate_pieces()
        groups = studio.compute_works()
        self.assertEqual(len(groups), 4)

        life_group, mom_group, thoughts_group, unfiled_group = groups

        self.assertEqual(life_group["focus"]["id"], "life")
        self.assertEqual(len(life_group["projects"]), 1)
        self.assertEqual(life_group["projects"][0]["kind"], "project")
        self.assertEqual(life_group["projects"][0]["format"], "book")
        self.assertEqual(life_group["projects"][0]["focus_id"], "life")
        self.assertEqual(life_group["projects"][0]["book"]["id"], "life")
        self.assertEqual([p["slug"] for p in life_group["pieces"]], ["chapter-a"])
        self.assertEqual(life_group["readiness"], [])  # format_readiness not yet available

        self.assertEqual(mom_group["focus"]["id"], "mom")
        self.assertEqual(mom_group["projects"], [])  # letter isn't a book deliverable
        self.assertEqual([p["slug"] for p in mom_group["pieces"]], ["letter-mom"])

        self.assertIsNone(thoughts_group["focus"])
        self.assertEqual(thoughts_group["key"], "__thoughts__")
        self.assertEqual([p["slug"] for p in thoughts_group["pieces"]], ["my-essay"])

        self.assertIsNone(unfiled_group["focus"])
        self.assertEqual(unfiled_group["key"], "__unfiled__")
        self.assertEqual([p["slug"] for p in unfiled_group["pieces"]], ["orphan-piece"])

    def test_pieces_sorted_created_slug_descending_within_group(self):
        self._write("outputs/letter-mom-older/meta.yaml",
                    "title: letter-mom-older\nformat: letter\nsubject: Mom\n"
                    "categories: [K]\ncreated: 2026-01-01\n")
        self._write("outputs/letter-mom-older/v1.md", "Older letter.\n")
        self._write("outputs/letter-mom-newer/meta.yaml",
                    "title: letter-mom-newer\nformat: letter\nsubject: Mom\n"
                    "categories: [K]\ncreated: 2026-05-01\n")
        self._write("outputs/letter-mom-newer/v1.md", "Newer letter.\n")
        groups = studio.compute_works()
        mom_group = next(g for g in groups if g["focus"] and g["focus"]["id"] == "mom")
        self.assertEqual([p["slug"] for p in mom_group["pieces"]],
                         ["letter-mom-newer", "letter-mom-older"])

    def test_no_pieces_and_no_book_focuses_returns_no_groups(self):
        # "mom" is a letter (non-book) deliverable with no pieces filed under
        # it, and no book-deliverable focus exists in this roadmap -> nothing
        # to show. (A book-deliverable focus always yields a project group
        # via book.compute_books(), even with zero drafted pieces — that's
        # covered by test_groups_pieces_and_projects_by_focus_in_roadmap_order.)
        roadmap.ROADMAP_FILE = self._write("roadmap-no-book.json", {
            "version": 1, "focuses": [MOM_FOCUS],
        })
        self.assertEqual(studio.compute_works(), [])

    def test_book_focus_without_any_pieces_still_yields_a_project_group(self):
        roadmap.ROADMAP_FILE = self._write("roadmap-life-only.json", {
            "version": 1, "focuses": [LIFE_FOCUS],
        })
        groups = studio.compute_works()
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0]["focus"]["id"], "life")
        self.assertEqual(groups[0]["pieces"], [])
        self.assertEqual(len(groups[0]["projects"]), 1)

    def test_accepts_explicit_questions_without_reading_the_bank(self):
        self._populate_pieces()
        # Poison the on-disk bank; an explicit questions=[] must still work
        # (compute_works must not silently re-read the file when given a list).
        studio.QUESTIONS_FILE = self.tmp / "missing-bank.md"
        groups = studio.compute_works(questions=[])
        self.assertTrue(any(g["focus"] and g["focus"]["id"] == "life" for g in groups))


class AssembleBookTests(StudioTestBase):
    def test_unknown_focus_raises(self):
        with self.assertRaises(ValueError):
            studio.assemble_book("does-not-exist")

    def test_non_book_deliverable_focus_raises(self):
        with self.assertRaises(ValueError):
            studio.assemble_book("mom")  # deliverable=letter, not a book

    def test_book_focus_without_any_drafted_chapter_raises(self):
        with self.assertRaises(ValueError):
            studio.assemble_book("life")

    def test_composes_manuscript_with_placeholder_for_undrafted_chapter(self):
        self._write_chapter_a("Chapter A body one.\n")
        result = studio.assemble_book("life")

        self.assertEqual(result["version"], 1)
        self.assertEqual(result["chapters_included"], 1)
        self.assertEqual(result["chapters_placeholder"], 1)
        self.assertEqual(result["slug"], "my-life-book")
        self.assertEqual(result["path"], "outputs/my-life-book/v1.md")

        out_path = self.tmp / "outputs" / "my-life-book" / "v1.md"
        self.assertTrue(out_path.exists())
        content = out_path.read_text()
        self.assertIn("# My Life", content)
        self.assertIn("## Origins", content)
        self.assertIn("Chapter A body one.", content)
        self.assertIn("## Becoming", content)
        self.assertIn("_(not yet drafted)_", content)
        # Chapter order follows the focus's own category order (A then B).
        self.assertLess(content.index("## Origins"), content.index("## Becoming"))

        meta = json.loads((self.tmp / "outputs" / "my-life-book" / "artifact.json").read_text())
        self.assertEqual(meta["format"], "book")
        # Deliberately empty (see studio.assemble_book) -- otherwise the
        # manuscript would recount itself as chapter-draft material on the
        # next assemble. Focus filing works via the subject-label match.
        self.assertEqual(meta["categories"], [])
        self.assertEqual(meta["subject"], "My Life")

    def test_composed_manuscript_is_never_recounted_as_a_chapter_draft(self):
        # Regression: an earlier version tagged the manuscript with the
        # focus's full category list, which made book.py's chapter-draft
        # scanner treat the manuscript as its own source material -> each
        # re-assemble duplicated the whole prior manuscript inside itself.
        self._write_chapter_a("Chapter A body one.\n")
        studio.assemble_book("life")
        drafts_by_cat = book._load_drafts_by_category()
        drafted_slugs = {slug for entries in drafts_by_cat.values() for slug, _w in entries}
        self.assertNotIn("my-life-book", drafted_slugs)

    def test_assembled_manuscript_files_under_its_focus_via_subject_fallback(self):
        # Its own `categories` is deliberately empty (see assemble_book), so
        # it must still land in the right compute_works() group by matching
        # its `subject` (the focus label) against label_to_focus.
        self._write_chapter_a("Chapter A body one.\n")
        studio.assemble_book("life")
        groups = studio.compute_works()
        life_group = next(g for g in groups if g["focus"] and g["focus"]["id"] == "life")
        slugs = {p["slug"] for p in life_group["pieces"]}
        self.assertIn("my-life-book", slugs)
        self.assertIn("chapter-a", slugs)

    def test_reassemble_is_a_noop_until_a_draft_changes_then_bumps_version(self):
        self._write_chapter_a("Chapter A body one.\n")
        first = studio.assemble_book("life")
        self.assertEqual(first["version"], 1)

        # No change to any draft: re-assembling must not create a redundant v2.
        again = studio.assemble_book("life")
        self.assertEqual(again["version"], 1)
        self.assertEqual(again["path"], first["path"])
        self.assertFalse((self.tmp / "outputs" / "my-life-book" / "v2.md").exists())

        # Chapter A gets a new draft version: content changes -> new manuscript version.
        self._write_chapter_a("Chapter A body TWO, changed.\n", version=2)
        second = studio.assemble_book("life")
        self.assertEqual(second["version"], 2)
        v2_text = (self.tmp / "outputs" / "my-life-book" / "v2.md").read_text()
        self.assertIn("Chapter A body TWO, changed.", v2_text)

        # Unchanged again: still a no-op at v2.
        third = studio.assemble_book("life")
        self.assertEqual(third["version"], 2)

        # force=True writes a new version even without any underlying change.
        forced = studio.assemble_book("life", force=True)
        self.assertEqual(forced["version"], 3)


class ArtifactAssembleBuilderTests(unittest.TestCase):
    def test_registered_never_retryable(self):
        self.assertIn("artifact-assemble", jobs.COMMANDS)
        self.assertEqual(jobs.COMMANDS["artifact-assemble"].retry_safety, "never")

    def test_builds_cli_invocation_for_minimal_payload(self):
        invocations = jobs._build_artifact_assemble({"focus": "life"})
        self.assertEqual(len(invocations), 1)
        inv = invocations[0]
        self.assertEqual(inv.kind, "lifehug-cli")
        self.assertEqual(inv.arguments, ("book-assemble", "--focus", "life"))

    def test_force_flag_appends_force_argument(self):
        invocations = jobs._build_artifact_assemble({"focus": "life", "force": True})
        self.assertEqual(invocations[0].arguments, ("book-assemble", "--focus", "life", "--force"))

    def test_force_false_omits_flag(self):
        invocations = jobs._build_artifact_assemble({"focus": "life", "force": False})
        self.assertEqual(invocations[0].arguments, ("book-assemble", "--focus", "life"))

    def test_missing_focus_rejected(self):
        with self.assertRaises(ValueError):
            jobs._build_artifact_assemble({})

    def test_invalid_focus_characters_rejected(self):
        for bad in ("../escape", "life/../../etc", "has spaces", "a" * 65):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    jobs._build_artifact_assemble({"focus": bad})

    def test_non_bool_force_rejected(self):
        with self.assertRaises(ValueError):
            jobs._build_artifact_assemble({"focus": "life", "force": "yes"})

    def test_unexpected_field_rejected(self):
        with self.assertRaises(ValueError):
            jobs._build_artifact_assemble({"focus": "life", "unexpected": "x"})


if __name__ == "__main__":
    unittest.main()
