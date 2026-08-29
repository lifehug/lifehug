"""Timeline Fix 09 (lifehug-platform#767) — the moment opener asks WHEN.

`KIND_OPENERS["moment"]`'s unanchored opener used to be content-first
("Tell me about {label} — just the moment itself, however it comes."),
following the v196 rule that dating is reconstructive inference and content
comes first. The owner overruled that for the one path where content is
already known — a person presses Play on a moment they can already see on
the page, and the only thing missing is WHEN. This test pins the new
shape: seen FAILING on v260 (the opener still asked to be told about the
moment, never asked when).

Synthetic data only; NEVER references ~/Workspace/dave.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SYSTEM = ROOT / "system"
sys.path.insert(0, str(SYSTEM))

import timeline_interaction as ti  # noqa: E402


class MomentOpenerAsksWhenTests(unittest.TestCase):
    def test_the_unanchored_moment_opener_names_the_moment_and_asks_when(self):
        moment = {"kind": "moment", "label": "feeling comfortable at Grandma Betty's house"}
        probe = ti.choose_probe(moment)
        text = probe["text"]
        # Names the moment via {label} — never the raw event_kind/dict shape.
        self.assertIn("feeling comfortable at Grandma Betty's house", text)
        self.assertNotIn("event_kind", text)
        # Asks WHEN, not "tell me about" — the content-first opener is gone.
        self.assertTrue(text.startswith("About when was "), text)
        self.assertNotIn("Tell me about", text)
        self.assertNotIn("just the moment itself", text)
        # The ladder step/cost for the unanchored rung are unchanged.
        self.assertEqual(probe["step"], "content")
        self.assertEqual(probe["cost"], 1)

    def test_the_anchored_moment_opener_is_unchanged(self):
        """The anchored variant already asks WHEN (before/after) — Timeline
        Fix 09 only touches the unanchored rung."""
        moment = {"kind": "moment", "label": "the dog that followed you home"}
        anchor = {"key": "mesa", "label": "the Mesa house", "kind": "residence",
                  "date": "1984/1990"}
        probe = ti.choose_probe(moment, anchors=[anchor])
        self.assertEqual(probe["step"], "sequence")
        self.assertIn("the dog that followed you home", probe["text"])
        self.assertIn("the Mesa house", probe["text"])
        self.assertIn("before or after", probe["text"])


if __name__ == "__main__":
    unittest.main()
