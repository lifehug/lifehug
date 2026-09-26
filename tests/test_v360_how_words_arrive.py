"""The one shared "how the person's words arrive" block (owner, 2026-09-25).

"most of this information comes from free-flowing discussion too, unless it's
specifically added as a landmark or a very precise date. Also, for most of
this, I'm speaking voice-to-text, so often things are misspelled or maybe
translated wrong. That needs to be taken into account."

The live example from that conversation: "19 to 21" (an age range) arrived as
"1921", which reads as a year. The fix is one framework file,
``interactions/how-words-arrive.md``, stated once and read by every builder
that puts the person's words in front of a model. These tests list every
reader: a builder added later that interprets the person's words belongs here.
"""

from __future__ import annotations

import json
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "system"))
sys.path.insert(0, str(ROOT / "tests"))

import classify_story  # noqa: E402
import conversation  # noqa: E402
import general_listener as gl  # noqa: E402
import landmark_reading  # noqa: E402
import landmark_recorder as lr  # noqa: E402
import lifehug_core  # noqa: E402
import resolver  # noqa: E402
import timeline_interaction as ti  # noqa: E402
from test_classify_pasted_records import JAMES_RECORD, PastedRecordCase  # noqa: E402

BLOCK = lifehug_core.load_how_words_arrive()


class TheBlockItselfTests(unittest.TestCase):
    def test_it_exists_ships_and_says_the_three_things(self):
        self.assertTrue(BLOCK, "interactions/how-words-arrive.md is missing or empty")
        manifest = json.loads((ROOT / "system" / "version.json").read_text(encoding="utf-8"))
        self.assertIn("interactions/how-words-arrive.md", manifest["framework_files"])
        text = " ".join(BLOCK.split())
        self.assertIn(lifehug_core.HOW_WORDS_ARRIVE_HEADING, text)
        # conversational, not testimony; landmarks are the exception
        self.assertIn("not careful testimony", text)
        self.assertIn("landmark", text)
        # voice-to-text, with the live example
        self.assertIn("voice-to-text", text)
        self.assertIn('"19 to 21" arrives as "1921"', text)
        # a contradiction is a question
        self.assertIn("a question to ask them, never a correction", text)

    def test_it_is_brace_free_so_every_builder_can_carry_it(self):
        # resolver.PROMPT is a str.format template and the leaves substitute
        # `{token}`s; a brace in the block would break the one or leak into
        # the other's unfilled-token checks.
        self.assertNotIn("{", BLOCK)
        self.assertNotIn("}", BLOCK)

    def test_it_is_short(self):
        # Examples beat adjectives; this rides the cached prefix of every turn.
        self.assertLess(len(BLOCK), 1600)
        manifest = conversation._safe_manifest()  # noqa: SLF001
        budget = manifest.get("budget.how_words_arrive")
        self.assertIsInstance(budget, int)
        self.assertLessEqual(len(BLOCK), budget * conversation.CHARS_PER_TOKEN)


class ConversationReadsItTests(unittest.TestCase):
    """The parent context — and so every child's turn, which rides it."""

    def test_the_turn_context_carries_it_once_after_examples(self):
        context = conversation.assemble_context(
            {"mode": "chat", "turns": [{"role": "user", "text": "Dad served his mission at 1921"}]},
            blocks={"profile": "", "record": "", "asking_supply": ""},
        )
        self.assertEqual(context.count("## HOW_WORDS_ARRIVE"), 1)
        self.assertIn(BLOCK, context)
        self.assertLess(context.index("## EXAMPLES"), context.index("## HOW_WORDS_ARRIVE"))
        self.assertLess(context.index("## HOW_WORDS_ARRIVE"), context.index("## PROFILE"))

    def test_the_turn_prompt_carries_it(self):
        prompt = conversation.build_turn_prompt({
            "session": {"mode": "chat", "turns": []},
            "blocks": {"profile": "", "record": "", "asking_supply": ""},
        })
        self.assertIn(BLOCK, prompt)

    def test_the_manifest_load_order_names_it(self):
        manifest = conversation._safe_manifest()  # noqa: SLF001
        self.assertIn("|examples|how_words_arrive|profile|", manifest["load_order"])


class ExtractionLeavesReadItTests(unittest.TestCase):
    def assert_carried(self, prompt: str) -> None:
        self.assertIn(BLOCK, prompt)
        self.assertNotIn(lifehug_core.HOW_WORDS_ARRIVE_TOKEN, prompt)

    def test_the_landmark_recorder(self):
        self.assert_carried(lr.build_recorder_prompt(
            domain="work", question_asked="What work have you done?", answer="x", reply="y"))

    def test_the_general_listener(self):
        self.assert_carried(gl.build_listener_prompt(answer="x", reply="y"))

    def test_the_landmark_reading(self):
        self.assert_carried(landmark_reading.build_reading_prompt("We lived in Mesa 1990 to 1992."))

    def test_the_timeline_era_recorder(self):
        self.assert_carried(ti.build_era_recorder_prompt(
            target={"era_ref": "era:college", "label": "College Years", "era_kind": "school"},
            question_asked="q", answer="a"))

    def test_the_leaf_files_carry_the_token_and_not_the_text(self):
        # Stated ONCE: the leaves carry a token, never a pasted copy.
        for leaf in ("landmarks/prompt/recorder.md", "landmarks/prompt/listener.md",
                     "landmarks/prompt/reading.md", "timeline/prompt/recorder.md"):
            with self.subTest(leaf=leaf):
                raw = (ROOT / "interactions" / leaf).read_text(encoding="utf-8")
                self.assertEqual(raw.count(lifehug_core.HOW_WORDS_ARRIVE_TOKEN), 1)
                self.assertNotIn("voice-to-text", raw)


class ResolverReadsItTests(unittest.TestCase):
    def test_the_resolver_prompt_carries_it(self):
        sp = {"owner_name": "Dave", "birth": "1976-01-01", "stays": [], "tenures": [],
              "points": [], "people": [], "ages": []}
        prompt = resolver.build_prompt(source_path="answers/x.md", story="Dad served his mission at 1921",
                                       rows=[], sp=sp, passages=[])
        self.assertIn(BLOCK, prompt)
        self.assertLess(prompt.index(BLOCK), prompt.index("## The owner"))


class ClassifierReadsItTests(PastedRecordCase):
    def test_both_classification_modes_carry_it(self):
        full = classify_story.build_prompt(self.source, {}, JAMES_RECORD, context_snapshot=self.snapshot())
        self.assertIn(BLOCK, full)
        self.assertLess(full.index(BLOCK), full.index("## Story Text"))
        text = " ".join(full.split())
        self.assertIn('"at 1921" about a mission is `age: "19 to 21"`', text)
        timeline = classify_story.build_prompt(
            self.source, {}, JAMES_RECORD, context_snapshot=self.snapshot(), mode="timeline")
        self.assertIn(BLOCK, timeline)


class NoPastedCopiesTests(unittest.TestCase):
    def test_no_prompt_file_pastes_the_block(self):
        # A second copy is how N prompts drift; the token or the builder is
        # the only way in.
        pattern = re.compile(r"voice-to-text", re.IGNORECASE)
        for path in sorted((ROOT / "interactions").rglob("*.md")):
            if path.name == lifehug_core.HOW_WORDS_ARRIVE_FILE_NAME or path.name == "README.md":
                continue
            if "context" in path.parts:
                continue
            with self.subTest(path=str(path.relative_to(ROOT))):
                self.assertIsNone(pattern.search(path.read_text(encoding="utf-8")))


if __name__ == "__main__":
    unittest.main()
