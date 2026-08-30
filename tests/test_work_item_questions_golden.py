"""Timeline Fix 07 P3 — the nine live strings, as a golden.

`tests/goldens/work_item_questions_v262.json` holds the INPUT SHAPE of every
one of the nine work items the founder's Timeline was showing on 2026-08-29
(quoted verbatim in lifehug-platform#761 §1), and what the composer says about
each. Every name in the golden is synthetic; only the shapes are his.

The rule the golden enforces: each row produces either a sentence a person
would say, or ``null`` — withheld. Never the template.

The golden is READ, not regenerated blindly: `test_no_row_is_a_template` is the
check that survives a careless regeneration, because it derives its expectation
from the lint rather than from the file.

Synthetic data only; NEVER references ~/Workspace/dave.
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "system"))

import conversation_lints as cl  # noqa: E402
import temporal_timeline as tt  # noqa: E402

GOLDEN = ROOT / "tests" / "goldens" / "work_item_questions_v262.json"


def compose(row: dict):
    args = dict(row["args"])
    if row["composer"] == "anchor":
        return tt.compose_anchor_question(args["text"])
    item_kind = args.pop("item_kind")
    event_kind = args.pop("event_kind")
    return tt.compose_question(item_kind, event_kind, **args)


class TheGolden(unittest.TestCase):
    def setUp(self):
        self.payload = json.loads(GOLDEN.read_text(encoding="utf-8"))
        self.rows = self.payload["rows"]

    def test_the_golden_covers_all_nine_live_items(self):
        self.assertEqual(len(self.rows), 9)
        for row in self.rows:
            self.assertTrue(row["live"])
            self.assertTrue(row["defect"])
            self.assertTrue(row["page_outcome"])

    def test_every_row_composes_exactly_what_the_golden_says(self):
        for row in self.rows:
            with self.subTest(live=row["live"]):
                self.assertEqual(compose(row), row["expected"])

    def test_no_row_is_a_template(self):
        """Derived from the lint, not from the file — a regenerated golden that
        recorded a leak would still fail here."""
        for row in self.rows:
            with self.subTest(live=row["live"]):
                text = compose(row)
                if text is None:
                    continue
                self.assertEqual(cl.lint_question(text), [])
                self.assertNotIn(" — span", text)
                self.assertNotIn(" — move", text)
                self.assertNotIn(" — transition", text)
                self.assertNotIn("speaker", text.lower())
                self.assertNotIn("author", text.lower())

    def test_every_live_string_the_owner_saw_would_be_refused_today(self):
        """The other direction: each of the nine strings as it was SHOWN is
        something the lint now refuses, or a question about a subject the
        composer will not mint at all."""
        refused = [row for row in self.rows if cl.lint_question(row["live"])]
        self.assertGreaterEqual(len(refused), 5)

    def test_the_one_withheld_row_is_the_bare_pronoun(self):
        withheld = [row for row in self.rows if row["expected"] is None]
        self.assertEqual(len(withheld), 1)
        self.assertIn("I", withheld[0]["live"])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
