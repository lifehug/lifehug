"""The handbook's honesty gate.

Handbook pages under docs/ annotate every quoted algorithm number:

    <!-- parity: module.CONSTANT = value -->

This suite finds every annotation, imports the named system/ module, and
asserts the live constant equals the quoted value — so a code change that
moves a number fails CI until the handbook page moves with it, exactly
like app-side parity tests keep served constants honest. A page with no
annotations costs nothing; a page quoting an unannotated number is a
review problem, not a test problem.

A second, narrower gate lives in this file too: the three seated-
interaction pages under docs/handbook/interactions/ embed their
interaction's `prompt/behavior.md` verbatim, delimited by

    <!-- embed: interactions/<name>/prompt/behavior.md -->
    ...
    <!-- /embed -->

so that "the documentation is the prompt" (the Interaction pattern's own
doc-drift guarantee, interactions/README.md) extends one layer up into
this handbook. EmbedParityTests asserts each embed block byte-matches its
source file — a behavior.md edit that isn't mirrored into the handbook
page fails CI exactly like a drifted parity number would.
"""

from __future__ import annotations

import importlib
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"
SYSTEM = ROOT / "system"

_ANNOTATION = re.compile(
    r"<!--\s*parity:\s*([A-Za-z_][\w]*)\.([A-Za-z_][\w]*)\s*=\s*([^\s]+)\s*-->"
)


def _annotations() -> list[tuple[Path, str, str, str]]:
    found = []
    for page in sorted(DOCS.rglob("*.md")):
        text = page.read_text(encoding="utf-8", errors="replace")
        for match in _ANNOTATION.finditer(text):
            found.append((page, match.group(1), match.group(2), match.group(3)))
    return found


class HandbookParityTests(unittest.TestCase):
    def test_the_harness_sees_the_seed_annotations(self):
        # The scaffold ships with at least the two seed annotations on the
        # landing page; an empty scan means the annotation grammar broke.
        self.assertGreaterEqual(len(_annotations()), 2)

    def test_every_quoted_number_matches_the_live_constant(self):
        if str(SYSTEM) not in sys.path:
            sys.path.insert(0, str(SYSTEM))
        for page, module_name, const_name, quoted in _annotations():
            with self.subTest(page=page.name, constant=f"{module_name}.{const_name}"):
                module = importlib.import_module(module_name)
                live = getattr(module, const_name)
                try:
                    expected: object = type(live)(quoted)
                except (TypeError, ValueError):
                    expected = quoted
                self.assertEqual(
                    live,
                    expected,
                    f"{page} quotes {module_name}.{const_name} = {quoted} "
                    f"but the code says {live!r} — update the page (or the "
                    f"annotation) alongside the code change",
                )


HANDBOOK_INTERACTIONS = DOCS / "handbook" / "interactions"

_EMBED = re.compile(
    r"<!--\s*embed:\s*(\S+)\s*-->\n(.*?)<!--\s*/embed\s*-->",
    re.DOTALL,
)


def _embeds() -> list[tuple[Path, str, str]]:
    """[(handbook_page, source_relpath, embedded_body), ...] for every
    <!-- embed: ... --> ... <!-- /embed --> block under docs/handbook/
    (not just interactions/ — the mechanism isn't page-location-specific,
    even though the three seated-interaction pages are its only callers
    today)."""
    found = []
    for page in sorted((DOCS / "handbook").rglob("*.md")):
        text = page.read_text(encoding="utf-8", errors="replace")
        for match in _EMBED.finditer(text):
            found.append((page, match.group(1), match.group(2)))
    return found


class EmbedParityTests(unittest.TestCase):
    """Interaction pages embed their prompt/behavior.md verbatim — see the
    module docstring. A drifted embed (source file edited, page not) fails
    here exactly like a drifted parity number fails HandbookParityTests."""

    def test_the_harness_sees_the_four_interaction_embeds(self):
        # One embed per shipped interaction page (conversation,
        # question_judgment, focus_curation, question_candidate) — a short scan means
        # the embed grammar broke, or a page lost its embed block.
        self.assertGreaterEqual(len(_embeds()), 4)

    def test_every_embed_byte_matches_its_source_file(self):
        for page, source_relpath, body in _embeds():
            with self.subTest(page=page.name, source=source_relpath):
                source_path = ROOT / source_relpath
                self.assertTrue(
                    source_path.is_file(),
                    f"{page} embeds {source_relpath!r}, which doesn't exist "
                    f"under the repo root",
                )
                expected = source_path.read_text(encoding="utf-8")
                self.assertEqual(
                    body,
                    expected,
                    f"{page}'s embed of {source_relpath} has drifted from "
                    f"the source file — re-copy the file's current contents "
                    f"into the embed block",
                )

    def test_each_seated_interaction_page_embeds_its_own_behavior_md(self):
        # Belt-and-suspenders on top of the byte-match test above: the
        # pages this mechanism covers each carry exactly the
        # embed they're supposed to, not e.g. two pages both embedding the
        # same file by copy-paste mistake.
        expected = {
            HANDBOOK_INTERACTIONS / "conversation.md":
                "interactions/conversation/prompt/behavior.md",
            HANDBOOK_INTERACTIONS / "question-judgment.md":
                "interactions/question_judgment/prompt/behavior.md",
            HANDBOOK_INTERACTIONS / "focus-curation.md":
                "interactions/focus_curation/prompt/behavior.md",
            HANDBOOK_INTERACTIONS / "question-candidate.md":
                "interactions/question_candidate/prompt/behavior.md",
        }
        by_page: dict[Path, list[str]] = {}
        for page, source_relpath, _body in _embeds():
            by_page.setdefault(page, []).append(source_relpath)
        for page, source_relpath in expected.items():
            with self.subTest(page=page.name):
                self.assertIn(page, by_page, f"{page} has no embed block at all")
                self.assertEqual(
                    by_page[page],
                    [source_relpath],
                    f"{page} should embed exactly [{source_relpath}]",
                )


if __name__ == "__main__":
    unittest.main()
