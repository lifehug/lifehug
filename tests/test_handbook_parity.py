"""The handbook's honesty gate.

Handbook pages under docs/ annotate every quoted algorithm number:

    <!-- parity: module.CONSTANT = value -->

This suite finds every annotation, imports the named system/ module, and
asserts the live constant equals the quoted value — so a code change that
moves a number fails CI until the handbook page moves with it, exactly
like app-side parity tests keep served constants honest. A page with no
annotations costs nothing; a page quoting an unannotated number is a
review problem, not a test problem.
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


if __name__ == "__main__":
    unittest.main()
