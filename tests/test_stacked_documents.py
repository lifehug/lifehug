"""Issue #286 — follow-up to #282/#285 (v257).

Measured against the two REAL sources v257's fix was for, the restored
shape is not consecutive fenced blocks (v257's fix) — it is CONCATENATED
WHOLE DOCUMENTS: `frontmatter -> the writer's own "# Question ..." H1 ->
frontmatter -> H1 -> ... -> body`. `skip_leading_frontmatter_blocks` (v257)
only continues past a fence that is immediately followed by ANOTHER fence;
the real files have the writer's own heading sitting between them, so v257
stops at the first heading and `answer_body` still returns the SECOND
document's frontmatter keys as the body.

Real measured line shapes (lifehug#286), reproduced here with entirely
synthetic prose — NEVER the real files, NEVER ~/Workspace/dave:

    answers/C17.md (63 lines): 1 FENCE . 21 FENCE . 23 H1 . 25 FENCE .
        45 FENCE . 47 H1 . 48-63 body (a real ~555-word answer)
    answers/B11.md (77 lines): 1 FENCE . 21 FENCE . 23 H1 . 25 FENCE .
        45 FENCE . 47 H1 . 49 FENCE . 69 FENCE . 71 H1 . 72-77 body
        (B11 is NOT empty — a real ~216-word answer)

This file builds fixtures with that exact fence/H1 LINE shape (self-checked
below) and proves:

1. The reader treats "a fenced frontmatter block + the writer's own H1
   (whose text matches THAT block's own title)" as one preamble, and
   repeats — metadata from the first block, body = everything after the
   LAST preamble.
2. `stacked_frontmatter` lint detects this document-stacked shape too
   (block count = number of preambles).
3. `classify_story.py --emit-prompts` / `--prompt` produce REAL story text
   for both shapes instead of a YAML-only prompt.

Every test in `NegativeFirstAgainstV257Tests` reproduces the ask's
requirement that the negative be run against v257 and seen failing first —
see the PR evidence comment for the captured failing run.
"""

from __future__ import annotations

import io
import re
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


# ── fixture construction: exact fence/H1 line positions from lifehug#286 ──────

def _frontmatter_lines(title: str, source_id: str, question_id: str) -> list[str]:
    """Exactly 19 metadata lines between the fences — 21 lines total,
    matching the real files' `1 FENCE ... 21 FENCE` span."""
    return [
        "---",
        f'title: "{title}"',
        'type: "prompted_answer"',
        f'source_id: "{source_id}"',
        f'question_id: "{question_id}"',
        f'question_text: "{title.split(": ", 1)[1]}"',
        'category: "C"',
        'category_name: "Relationships"',
        "pass_number: 1",
        'source_medium: "voice"',
        'asked_at: "2026-01-01"',
        'answered_date: "2026-01-02"',
        'captured_at: "2026-01-02T10:00:00"',
        "answer_count: 1",
        'visibility: "owner_only"',
        'sensitivity: "private"',
        'status: "raw"',
        "immutable: true",
        "schema_version: 1",
        'content_sha256: "deadbeef"',
        "---",
    ]


def _preamble_lines(title: str, source_id: str, question_id: str) -> list[str]:
    """One "document preamble": a fence block, blank line, the writer's own
    `# <title>` heading (byte-identical to `process_answer.py`'s
    `f"# Question {question_id}: {question['text']}"` / `title` pairing),
    blank line — 24 lines total (21 fence + blank + H1 + blank)."""
    return [*_frontmatter_lines(title, source_id, question_id), "", f"# {title}", ""]


def _synthetic_prose(word_groups: list[str]) -> list[str]:
    """Plainly-synthetic filler prose lines — never real content."""
    return word_groups


C17_TITLE = "Question C17: What did the quiet room off the synthetic hallway hold?"
C17_BODY_LINES = [
    "The synthetic hallway light flickered every third evening that season, a detail",
    "invented purely for this fixture and matching nothing in any real vault.",
    "Placeholder sentence about a fictional workshop, a borrowed tool, and a",
    "conversation that never happened outside of this test file.",
    "",
    "A second placeholder paragraph describing an imagined porch, an imagined dog,",
    "and an imagined summer that exists only to give this fixture a realistic word",
    "count without ever referencing anything true.",
    "",
    "A third placeholder paragraph, again wholly invented, closes out the answer",
    "with a made-up detail about a synthetic garden shed and a synthetic bicycle",
    "leaning against it, useful only for exercising the reader under test.",
    "",
    "Closing filler line one.",
    "Closing filler line two.",
]


def _build_c17_fixture() -> str:
    """Two stacked document preambles (same duplicated title/question_id —
    a bad rebase duplicating ONE source's own header, not two different
    files), then the real body. Matches `1 FENCE . 21 FENCE . 23 H1 .
    25 FENCE . 45 FENCE . 47 H1 . 48-63 body`."""
    lines: list[str] = []
    lines.extend(_preamble_lines(C17_TITLE, "answer:C17", "C17"))
    lines.extend(_preamble_lines(C17_TITLE, "answer:C17", "C17"))
    lines.extend(_synthetic_prose(C17_BODY_LINES))
    return "\n".join(lines) + "\n"


B11_TITLE = "Question B11: What was kept in the synthetic drawer by the door?"
B11_BODY_LINES = [
    "A wholly invented placeholder answer about a synthetic key ring and a",
    "synthetic spare button jar, built only to exercise this fixture.",
    "",
    "A second invented sentence about a fictional receipt drawer, present only",
    "so this body has more than one paragraph of synthetic text.",
]


def _build_b11_fixture() -> str:
    """Three stacked document preambles, then the real (non-empty) body.
    Matches `1 FENCE . 21 FENCE . 23 H1 . 25 FENCE . 45 FENCE . 47 H1 .
    49 FENCE . 69 FENCE . 71 H1 . 72-77 body`."""
    lines: list[str] = []
    lines.extend(_preamble_lines(B11_TITLE, "answer:B11", "B11"))
    lines.extend(_preamble_lines(B11_TITLE, "answer:B11", "B11"))
    lines.extend(_preamble_lines(B11_TITLE, "answer:B11", "B11"))
    lines.extend(_synthetic_prose(B11_BODY_LINES))
    return "\n".join(lines) + "\n"


C17_FIXTURE = _build_c17_fixture()
B11_FIXTURE = _build_b11_fixture()


def _line_numbers(content: str, pattern: str) -> list[int]:
    lines = content.split("\n")
    return [i + 1 for i, line in enumerate(lines) if re.match(pattern, line)]


class FixtureShapeSelfCheckTests(unittest.TestCase):
    """The fixtures above must actually reproduce lifehug#286's measured
    line shape, not an approximation of it."""

    def test_c17_fence_and_heading_lines_match_the_real_file(self):
        fences = _line_numbers(C17_FIXTURE, r"^---$")
        headings = _line_numbers(C17_FIXTURE, r"^# ")
        self.assertEqual(fences, [1, 21, 25, 45])
        self.assertEqual(headings, [23, 47])

    def test_b11_fence_and_heading_lines_match_the_real_file(self):
        fences = _line_numbers(B11_FIXTURE, r"^---$")
        headings = _line_numbers(B11_FIXTURE, r"^# ")
        self.assertEqual(fences, [1, 21, 25, 45, 49, 69])
        self.assertEqual(headings, [23, 47, 71])


class DocumentStackedReaderTests(unittest.TestCase):
    """(1) skip_leading_frontmatter_blocks / answer_body treat a fence + the
    writer's own matching H1 as one preamble, repeated, with the real body
    after the LAST preamble."""

    def test_c17_shape_reaches_the_real_body(self):
        metadata, body, count = core.skip_leading_frontmatter_blocks(C17_FIXTURE)
        self.assertEqual(count, 2)
        self.assertEqual(metadata["source_id"], "answer:C17")
        self.assertIn("synthetic hallway light flickered", body)
        self.assertIn("Closing filler line two.", body)
        self.assertNotIn("content_sha256", body)
        # only the LAST document's own heading may remain (never stripped —
        # matches how every ordinary single-document answer already reads)
        self.assertEqual(body.count("Question C17:"), 1)

    def test_b11_shape_reaches_the_real_body_and_is_not_empty(self):
        metadata, body, count = core.skip_leading_frontmatter_blocks(B11_FIXTURE)
        self.assertEqual(count, 3)
        self.assertIn("synthetic key ring", body)
        self.assertIn("fictional receipt drawer", body)
        self.assertNotIn("content_sha256", body)
        self.assertEqual(body.count("Question B11:"), 1)

    def test_answer_body_c17_shape(self):
        body = core.answer_body(C17_FIXTURE)
        self.assertIn("synthetic hallway light flickered", body)
        self.assertIn("Closing filler line two.", body)
        self.assertNotIn("content_sha256", body)

    def test_answer_body_b11_shape_is_not_empty(self):
        body = core.answer_body(B11_FIXTURE)
        self.assertTrue(body.strip())
        self.assertIn("synthetic key ring", body)
        self.assertIn("fictional receipt drawer", body)
        self.assertNotIn("content_sha256", body)

    def test_ordinary_single_document_still_keeps_its_own_heading(self):
        """A normal, non-stacked answer (title == its own H1, the everyday
        case per process_answer.py) must NOT have its heading stripped —
        several other answer_body readers rely on it staying in the body."""
        single = "\n".join([
            *_frontmatter_lines("Question A1: An ordinary question", "answer:A1", "A1"),
            "",
            "# Question A1: An ordinary question",
            "",
            "An ordinary single-document answer body.",
        ]) + "\n"
        _metadata, body, count = core.skip_leading_frontmatter_blocks(single)
        self.assertEqual(count, 1)
        self.assertIn("# Question A1: An ordinary question", body)
        self.assertIn("An ordinary single-document answer body.", body)


class ClassifyStoryDocumentStackedTests(unittest.TestCase):
    """(3) --emit-prompts / --prompt produce real story text for both
    document-stacked shapes."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: __import__("shutil").rmtree(self.tmp, ignore_errors=True))
        self.answers = self.tmp / "answers"
        self.answers.mkdir(parents=True)
        self.c17 = self.answers / "C17.md"
        self.c17.write_text(C17_FIXTURE, encoding="utf-8")
        self.b11 = self.answers / "B11.md"
        self.b11.write_text(B11_FIXTURE, encoding="utf-8")

    def _patch(self):
        return mock.patch.object(cs, "ANSWERS_DIR", self.answers)

    def test_emit_prompts_carries_real_story_text_for_both(self):
        with self._patch():
            out_dir = self.tmp / "prompts"
            with redirect_stderr(io.StringIO()), redirect_stdout(io.StringIO()):
                rc = cs.emit_prompts([self.c17, self.b11], out_dir)
        self.assertEqual(rc, 0)
        c17_prompt = (out_dir / f"{cs.classify_stem(self.c17)}.prompt.md").read_text()
        b11_prompt = (out_dir / f"{cs.classify_stem(self.b11)}.prompt.md").read_text()
        self.assertIn("synthetic hallway light flickered", c17_prompt)
        self.assertNotIn("content_sha256", c17_prompt.split("## Story Text", 1)[1])
        self.assertIn("synthetic key ring", b11_prompt)
        self.assertNotIn("content_sha256", b11_prompt.split("## Story Text", 1)[1])

    def test_prompt_mode_carries_real_story_text_for_c17(self):
        with self._patch():
            out = io.StringIO()
            args = cs.build_parser().parse_args(["--prompt", str(self.c17)])
            with redirect_stdout(out):
                rc = cs.cmd_prompt(args)
        self.assertEqual(rc, 0)
        self.assertIn("synthetic hallway light flickered", out.getvalue())

    def test_prompt_mode_carries_real_story_text_for_b11(self):
        with self._patch():
            out = io.StringIO()
            args = cs.build_parser().parse_args(["--prompt", str(self.b11)])
            with redirect_stdout(out):
                rc = cs.cmd_prompt(args)
        self.assertEqual(rc, 0)
        self.assertIn("synthetic key ring", out.getvalue())
        self.assertIn("fictional receipt drawer", out.getvalue())


class SourceIntegrityDocumentStackedFindingTests(unittest.TestCase):
    """(2) stacked_frontmatter lint detects the document-stacked shape,
    with block count = number of preambles."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: __import__("shutil").rmtree(self.tmp, ignore_errors=True))
        self.answers = self.tmp / "answers"
        self.answers.mkdir(parents=True)

    def _patch(self):
        return mock.patch.object(si, "ANSWERS_DIR", self.answers)

    def test_c17_shape_flagged_with_two_preambles(self):
        path = self.answers / "C17.md"
        path.write_text(C17_FIXTURE, encoding="utf-8")
        with self._patch():
            record = si.source_record(path)
            findings = si.lint_records([record])
        stacked = next(f for f in findings if f["type"] == "stacked_frontmatter")
        self.assertIn("2", stacked["message"])

    def test_b11_shape_flagged_with_three_preambles(self):
        path = self.answers / "B11.md"
        path.write_text(B11_FIXTURE, encoding="utf-8")
        with self._patch():
            record = si.source_record(path)
            findings = si.lint_records([record])
        stacked = next(f for f in findings if f["type"] == "stacked_frontmatter")
        self.assertIn("3", stacked["message"])


if __name__ == "__main__":
    unittest.main()
