"""Issue #282 — a source restored from a lost rebase can carry two or three
CONSECUTIVE YAML frontmatter blocks (`---` fences x4 or x6). The shared
story-text reader (`lifehug_core.answer_body`, and `classify_story.py`'s own
former hand-rolled `parse_frontmatter`) treated the SECOND `---` fence as the
start of the body and stopped at the next one, so the real answer after the
last block was never read — or, when there was no real body at all, a
non-empty "body" (the second block's own YAML keys) was returned instead of
an honest empty string.

Three things are pinned here, all synthetic fixtures — NEVER references
~/Workspace/dave:

1. `lifehug_core.skip_leading_frontmatter_blocks` / `answer_body` skip EVERY
   leading fenced frontmatter block, then read the real body. Metadata comes
   from the FIRST block only (the stacked blocks are near-duplicates from the
   restore, not independent facts).
2. `classify_story.py` (`--classify`, `--classify-all`, `--emit-prompts`,
   `--prompt`) names a source whose extracted story text is EMPTY up front —
   `no story text found: <path>` — rather than emitting a prompt the model
   cannot answer.
3. `source_integrity`'s lint pass flags stacked frontmatter as a named defect
   (`stacked_frontmatter`) so a restore like this is caught at commit time —
   without flagging a normal single-block source or a body that legitimately
   contains a `---` horizontal rule below real prose.
"""

from __future__ import annotations

import io
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SYSTEM = ROOT / "system"
sys.path.insert(0, str(SYSTEM))

import classify_story as cs  # noqa: E402
import lifehug_core as core  # noqa: E402
import source_integrity as si  # noqa: E402


def _block(title: str, source_id: str) -> str:
    """One complete frontmatter block, shaped like a real answers/*.md
    source: title/type/source_id/question_id/.../content_sha256."""
    return (
        "---\n"
        f'title: "{title}"\n'
        'type: "prompted_answer"\n'
        f'source_id: "{source_id}"\n'
        'question_id: "A1"\n'
        'content_sha256: "deadbeef"\n'
        "---"
    )


TWO_BLOCKS_WITH_BODY = (
    _block("Question A1", "answer:A1")
    + "\n"
    + _block("Question A1", "answer:A1")
    + "\n\n"
    + "# Question A1: First\n\nThe real ~2KB answer lives here.\n"
)

THREE_BLOCKS_WITH_BODY = (
    _block("Question A1", "answer:A1")
    + "\n"
    + _block("Question A1", "answer:A1")
    + "\n"
    + _block("Question A1", "answer:A1")
    + "\n\n"
    + "# Question A1: First\n\nThe real answer lives here, past all three blocks.\n"
)

STACKED_NO_BODY = (
    _block("Question B11", "answer:B11")
    + "\n"
    + _block("Question B11", "answer:B11")
    + "\n"
    + _block("Question B11", "answer:B11")
    + "\n"
)

SINGLE_BLOCK_NORMAL = (
    _block("Question A1", "answer:A1")
    + "\n\n"
    + "# Question A1: First\n\nAn ordinary single-block answer.\n"
)

SINGLE_BLOCK_WITH_HR_IN_BODY = (
    _block("Question A1", "answer:A1")
    + "\n\n"
    + "# Question A1: First\n\nSome real prose comes first.\n\n---\n\nMore prose after the rule.\n"
)


class SkipLeadingFrontmatterBlocksTests(unittest.TestCase):
    """(1) lifehug_core reads past every leading frontmatter block."""

    def test_single_block_unaffected(self):
        metadata, body, count = core.skip_leading_frontmatter_blocks(SINGLE_BLOCK_NORMAL)
        self.assertEqual(count, 1)
        self.assertEqual(metadata["source_id"], "answer:A1")
        self.assertIn("An ordinary single-block answer.", body)

    def test_two_stacked_blocks_reach_the_real_body(self):
        metadata, body, count = core.skip_leading_frontmatter_blocks(TWO_BLOCKS_WITH_BODY)
        self.assertEqual(count, 2)
        self.assertEqual(metadata["source_id"], "answer:A1")
        self.assertIn("The real ~2KB answer lives here.", body)
        # The second block's own YAML keys must not leak into the body.
        self.assertNotIn("content_sha256", body)
        self.assertNotIn("question_id", body)

    def test_three_stacked_blocks_reach_the_real_body(self):
        metadata, body, count = core.skip_leading_frontmatter_blocks(THREE_BLOCKS_WITH_BODY)
        self.assertEqual(count, 3)
        self.assertIn("past all three blocks", body)
        self.assertNotIn("content_sha256", body)

    def test_stacked_blocks_with_no_body_is_honestly_empty(self):
        _metadata, body, count = core.skip_leading_frontmatter_blocks(STACKED_NO_BODY)
        self.assertEqual(count, 3)
        self.assertEqual(body.strip(), "")

    def test_horizontal_rule_below_real_prose_is_not_a_block(self):
        _metadata, _body, count = core.skip_leading_frontmatter_blocks(
            SINGLE_BLOCK_WITH_HR_IN_BODY
        )
        self.assertEqual(count, 1)


class AnswerBodyStackedFrontmatterTests(unittest.TestCase):
    """(1) `answer_body` — the reader every downstream module shares —
    delegates to `skip_leading_frontmatter_blocks` and sees the real body."""

    def test_two_stacked_blocks(self):
        body = core.answer_body(TWO_BLOCKS_WITH_BODY)
        self.assertIn("The real ~2KB answer lives here.", body)
        self.assertNotIn("content_sha256", body)

    def test_three_stacked_blocks(self):
        body = core.answer_body(THREE_BLOCKS_WITH_BODY)
        self.assertIn("past all three blocks", body)
        self.assertNotIn("content_sha256", body)

    def test_stacked_blocks_no_body_is_empty(self):
        body = core.answer_body(STACKED_NO_BODY)
        self.assertEqual(body.strip(), "")

    def test_single_block_still_works(self):
        body = core.answer_body(SINGLE_BLOCK_NORMAL)
        self.assertIn("An ordinary single-block answer.", body)


class ClassifyStoryEmptyStoryTextTests(unittest.TestCase):
    """(2) classify_story.py names an empty extracted story text up front —
    across --classify, --classify-all, --emit-prompts and --prompt — rather
    than emitting a prompt the model cannot answer."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: __import__("shutil").rmtree(self.tmp, ignore_errors=True))
        self.answers = self.tmp / "answers"
        self.answers.mkdir(parents=True)
        self.with_body = self.answers / "A1.md"
        self.with_body.write_text(TWO_BLOCKS_WITH_BODY, encoding="utf-8")
        self.no_body = self.answers / "B11.md"
        self.no_body.write_text(STACKED_NO_BODY, encoding="utf-8")

    def _patch(self):
        return mock.patch.object(cs, "ANSWERS_DIR", self.answers)

    def test_classify_file_names_empty_story_text_up_front(self):
        with self._patch():
            buf = io.StringIO()
            with redirect_stderr(buf):
                rc = cs.classify_file(self.no_body, "irrelevant-model", dry_run=True)
        self.assertEqual(rc, 1)
        self.assertIn("no story text found", buf.getvalue())
        self.assertIn("B11.md", buf.getvalue())

    def test_classify_file_with_real_body_proceeds(self):
        with self._patch():
            buf = io.StringIO()
            with redirect_stderr(buf), redirect_stdout(io.StringIO()):
                rc = cs.classify_file(self.with_body, "irrelevant-model", dry_run=True)
        self.assertEqual(rc, 0)
        self.assertNotIn("no story text found", buf.getvalue())

    def test_emit_prompts_skips_empty_source_and_names_it(self):
        with self._patch():
            out_dir = self.tmp / "prompts"
            err = io.StringIO()
            with redirect_stderr(err), redirect_stdout(io.StringIO()):
                rc = cs.emit_prompts([self.with_body, self.no_body], out_dir)
        self.assertEqual(rc, 0)
        self.assertIn("no story text found", err.getvalue())
        self.assertIn("B11.md", err.getvalue())
        # exactly one prompt written — the empty source got none
        prompt_files = sorted(p.name for p in out_dir.glob("*.prompt.md"))
        self.assertEqual(len(prompt_files), 1)
        manifest = core.read_json(out_dir / "manifest.json")
        self.assertEqual(len(manifest["items"]), 1)
        self.assertTrue(manifest["items"][0]["source"].endswith("answers/A1.md"))

    def test_prompt_mode_refuses_empty_story_text(self):
        with self._patch():
            err = io.StringIO()
            out = io.StringIO()
            args = cs.build_parser().parse_args(["--prompt", str(self.no_body)])
            with redirect_stderr(err), redirect_stdout(out):
                rc = cs.cmd_prompt(args)
        self.assertEqual(rc, 1)
        self.assertIn("no story text found", err.getvalue())
        self.assertNotIn("## Story Text", out.getvalue())

    def test_prompt_mode_with_real_body_emits_it(self):
        with self._patch():
            out = io.StringIO()
            args = cs.build_parser().parse_args(["--prompt", str(self.with_body)])
            with redirect_stdout(out):
                rc = cs.cmd_prompt(args)
        self.assertEqual(rc, 0)
        self.assertIn("The real ~2KB answer lives here.", out.getvalue())


class SourceIntegrityStackedFrontmatterFindingTests(unittest.TestCase):
    """(3) source_integrity's lint pass flags stacked frontmatter as a named
    defect, and only that — never a normal source, never a legitimate `---`
    horizontal rule in the body."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: __import__("shutil").rmtree(self.tmp, ignore_errors=True))
        self.answers = self.tmp / "answers"
        self.answers.mkdir(parents=True)

    def _patch(self):
        return mock.patch.object(si, "ANSWERS_DIR", self.answers)

    def test_stacked_frontmatter_is_flagged(self):
        path = self.answers / "C17.md"
        path.write_text(TWO_BLOCKS_WITH_BODY, encoding="utf-8")
        with self._patch():
            record = si.source_record(path)
            findings = si.lint_records([record])
        types = [f["type"] for f in findings]
        self.assertIn("stacked_frontmatter", types)
        stacked = next(f for f in findings if f["type"] == "stacked_frontmatter")
        self.assertEqual(stacked["severity"], "error")
        self.assertIn("2", stacked["message"])
        self.assertIn("C17.md", stacked["path"])

    def test_three_stacked_blocks_reports_the_count(self):
        path = self.answers / "B11.md"
        path.write_text(STACKED_NO_BODY, encoding="utf-8")
        with self._patch():
            record = si.source_record(path)
            findings = si.lint_records([record])
        stacked = next(f for f in findings if f["type"] == "stacked_frontmatter")
        self.assertIn("3", stacked["message"])

    def test_normal_single_block_source_is_not_flagged(self):
        path = self.answers / "A1.md"
        path.write_text(SINGLE_BLOCK_NORMAL, encoding="utf-8")
        with self._patch():
            record = si.source_record(path)
            findings = si.lint_records([record])
        types = [f["type"] for f in findings]
        self.assertNotIn("stacked_frontmatter", types)

    def test_horizontal_rule_below_real_prose_is_not_flagged(self):
        path = self.answers / "A2.md"
        path.write_text(SINGLE_BLOCK_WITH_HR_IN_BODY, encoding="utf-8")
        with self._patch():
            record = si.source_record(path)
            findings = si.lint_records([record])
        types = [f["type"] for f in findings]
        self.assertNotIn("stacked_frontmatter", types)


if __name__ == "__main__":
    unittest.main()
