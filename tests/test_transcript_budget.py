"""v201 / lifehug#206 — the turn prompt never cuts a person off mid-sentence.

THE INCIDENT (lifehug-platform staging, 2026-08-23): a Foundation → Play
arc walk on a chapter called "Becoming". After roughly three exchanges the
assistant looped — it re-summarised the same thread and re-asked the same
question three turns running, the third time directly after the person
typed "You're repeating".

THE CAUSE, reproduced by `TranscriptFreeze` below: `assemble_context`
rendered EVERY turn into one SESSION block and then cut the joined string
at `budget.session` (1200 tokens x 4 = 4800 characters). Turns are
append-only, so the moment a session crossed 4800 characters:

  * the cut landed inside whatever the person happened to be saying —
    the model read a budget as a speaker who trailed off; and
  * the visible prefix FROZE. Every later turn, including the complaint,
    landed past the cut and never reached the model at all, so it saw the
    same mid-sentence transcript on every subsequent turn and loyally
    answered it again.

Two more findings from the same one-line cut, both covered here:
`{previous_turn_summary}` was `turns[-1]["text"][:200]`, a second mid-word
cut of the person's newest message; and `budget.behavior` (4800 chars)
was smaller than behavior.md (12,965 chars), so rules 8-13 — INCLUDING
rule 13, mid-thread back-off, the rule that exists to stop this exact loop
— had never reached the model at all.

Synthetic data only — NEVER ~/Workspace/dave (repo boundary, CLAUDE.md).
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "system"))

import conversation  # noqa: E402
import conversation_delivery as engine  # noqa: E402
import conversation_lints as lints  # noqa: E402
import interaction_evals as ie  # noqa: E402

GOLDENS_DIR = ROOT / "interactions" / "conversation" / "evals" / "goldens"
PROMPT_DIR = ROOT / "interactions" / "conversation" / "prompt"

# The live shape: an assistant turn sits just under cap.turn_chars (1200)
# and a person's answer runs a few hundred characters.
_FILLER = (
    "A bankruptcy is never one moment; it is a corridor you walk down for "
    "months before anyone else knows you are in it. You said the filing "
    "itself felt almost anticlimactic next to everything that led up to it, "
    "and I believe you. I want to stay in the part before the filing, "
    "because that is usually where the story actually lives. "
)


def _assistant(seed: str) -> str:
    return (seed + _FILLER * 5)[:1195]


_FINAL_USER = (
    "My marriage, when I think about it now — I think I was saying, simply "
    "the strength of my marriage today was and is in part directly related "
    "to Rae and I overcoming bad and unhealthy moments like that one together."
)


def _incident_turns() -> list[dict]:
    return [
        {"role": "lifehug", "text": _assistant("Bankruptcy, then. ")},
        {"role": "user", "text": (
            "It was about eighteen months of knowing and not saying. I would "
            "open the mail out in the driveway with the engine still running "
            "so nobody in the house would see my face when I read it. Rae "
            "knew something was wrong, but I had not given her the actual "
            "numbers, and the numbers were the whole thing.")},
        {"role": "lifehug", "text": _assistant("Opening the mail in the driveway is the detail. ")},
        {"role": "user", "text": (
            "I finally told her at the kitchen table after the kids had gone "
            "to bed. I printed the spreadsheet because I could not say the "
            "number out loud. She read the whole page without saying "
            "anything, and then she folded it in half and asked me what we "
            "do first. Not how did this happen. What do we do first.")},
        {"role": "lifehug", "text": _assistant("'What do we do first.' ")},
        {"role": "user", "text": (
            "We sold the truck that week and she picked up shifts and I "
            "stopped pretending. The bankruptcy took another nine months and "
            "by the end of it we were something different than we had been "
            "going in. I do not think I understood that until years later.")},
        {"role": "lifehug", "text": _assistant("Something different than you had been going in. ")},
        {"role": "user", "text": _FINAL_USER},
    ]


def _session(turns: list[dict]) -> dict:
    return {
        "session_id": "arc:chapter:B",
        "mode": "chat",
        "status": "open",
        "arc": {"question_id": "B3", "opening": "Chapter B: Becoming", "intents": []},
        "turns": turns,
    }


def _budget_chars(name: str) -> int:
    manifest = conversation.load_interaction_manifest()
    return int(manifest[f"budget.{name}"]) * conversation.CHARS_PER_TOKEN


class TranscriptFreeze(unittest.TestCase):
    """The incident itself, as a regression."""

    def setUp(self):
        self.turns = _incident_turns()
        self.budget = _budget_chars("session")

    def test_the_transcript_that_reproduced_the_loop_is_over_budget(self):
        """Without a fix this session is past `budget.session` — which is the
        precondition for everything below. If this stops holding, the
        reproduction has drifted and the rest of the class proves nothing."""
        naive = "\n".join(f"{t['role']}: {t['text']}" for t in self.turns)
        self.assertGreater(len(naive), self.budget)

    def test_the_final_user_turn_survives_verbatim(self):
        block = conversation._assemble_session_block(  # noqa: SLF001
            _session(self.turns), char_budget=self.budget
        )
        self.assertIn(_FINAL_USER, block)
        self.assertTrue(block.rstrip().endswith(_FINAL_USER))

    def test_no_turn_is_ever_cut_in_half(self):
        block = conversation._assemble_session_block(  # noqa: SLF001
            _session(self.turns), char_budget=self.budget
        )
        rendered = [
            line for line in block.split("\n")
            if line != conversation.TRANSCRIPT_ELISION_LINE
            and not line.startswith("Arc card:")
        ]
        for line in rendered:
            role, _, text = line.partition(": ")
            self.assertIn(
                text, [t["text"] for t in self.turns],
                msg=f"a {role} turn was rendered as a fragment, not whole",
            )

    def test_dropped_turns_are_announced_as_elision(self):
        block = conversation._assemble_session_block(  # noqa: SLF001
            _session(self.turns), char_budget=self.budget
        )
        self.assertIn(conversation.TRANSCRIPT_ELISION_LINE, block)

    def test_oldest_turns_yield_first(self):
        block = conversation._assemble_session_block(  # noqa: SLF001
            _session(self.turns), char_budget=self.budget
        )
        self.assertNotIn(self.turns[0]["text"], block)
        self.assertIn(self.turns[-2]["text"], block)

    def test_the_view_is_not_frozen_when_the_conversation_continues(self):
        """The loop's actual engine. Under the old joined-string cut, every
        turn appended past character 4800 was invisible, so the model's view
        of the conversation was byte-identical on every subsequent turn — it
        could not see its own repeats, and it could not see the person
        saying "You're repeating"."""
        first = conversation._assemble_session_block(  # noqa: SLF001
            _session(self.turns), char_budget=self.budget
        )
        later = self.turns + [
            {"role": "lifehug", "text": "You started to say \"My marriage, wh\" and got cut off. What were you about to say?"},
            {"role": "user", "text": "You're repeating"},
        ]
        second = conversation._assemble_session_block(  # noqa: SLF001
            _session(later), char_budget=self.budget
        )
        self.assertNotEqual(first, second)
        self.assertIn("You're repeating", second)


class PreviousTurnSummary(unittest.TestCase):
    """The prompt's second mid-word cut."""

    def test_a_long_message_is_elided_at_a_boundary_not_mid_word(self):
        summary = conversation._previous_turn_summary(  # noqa: SLF001
            [{"role": "user", "text": _FINAL_USER}]
        )
        self.assertTrue(summary.endswith(conversation.ELISION_MARKER))
        body = summary[: -len(conversation.ELISION_MARKER)].strip()
        self.assertTrue(_FINAL_USER.startswith(body))
        self.assertTrue(
            _FINAL_USER[len(body):].startswith((" ", "")),
            msg="the summary stopped inside a word",
        )

    def test_a_short_message_is_untouched(self):
        self.assertEqual(
            conversation._previous_turn_summary([{"role": "user", "text": "You're repeating"}]),  # noqa: SLF001
            "You're repeating",
        )

    def test_no_turns_is_the_opening(self):
        self.assertEqual(
            conversation._previous_turn_summary([]),  # noqa: SLF001
            "(none — this is the opening)",
        )


class ElisionIsNeverMidWord(unittest.TestCase):
    def test_under_budget_text_is_returned_unchanged(self):
        self.assertEqual(conversation._elide("short enough", 100), "short enough")  # noqa: SLF001

    def test_a_non_int_budget_is_no_budget(self):
        self.assertEqual(conversation._elide("anything", None), "anything")  # noqa: SLF001

    def test_the_cut_lands_on_a_boundary_and_says_so(self):
        text = " ".join(f"sentence number {n} here." for n in range(200))
        out = conversation._elide(text, 25)  # noqa: SLF001
        self.assertLessEqual(len(out), 25 * conversation.CHARS_PER_TOKEN)
        self.assertTrue(out.endswith(conversation.ELISION_MARKER))
        body = out[: -len(conversation.ELISION_MARKER)].strip()
        self.assertTrue(text.startswith(body))
        self.assertIn(text[len(body): len(body) + 1], (" ", ""))

    def test_text_with_no_whitespace_at_all_is_still_shortened(self):
        out = conversation._elide("x" * 5000, 100)  # noqa: SLF001
        self.assertLessEqual(len(out), 400)


class AuthorityBlocksFitTheirBudget(unittest.TestCase):
    """A budget smaller than the file it governs is silent data loss.

    Measured at the time of the incident: behavior.md was 12,965 characters
    against a 4,800-character allowance, so the model received it cut off
    inside the heading of rule 8 — rules 8 through 13 never reached it, in
    any conversation, on any medium. Rule 13 is mid-thread back-off.
    """

    def test_every_framework_prompt_block_fits_whole(self):
        manifest = conversation.load_interaction_manifest()
        for name in ("identity", "behavior", "examples"):
            with self.subTest(block=name):
                text = (PROMPT_DIR / f"{name}.md").read_text(encoding="utf-8")
                limit = int(manifest[f"budget.{name}"]) * conversation.CHARS_PER_TOKEN
                self.assertLessEqual(
                    len(text), limit,
                    msg=(f"{name}.md is {len(text)} chars against a {limit}-char "
                         f"budget: the model would silently lose the tail. Raise "
                         f"budget.{name} deliberately, or shorten the file."),
                )
                self.assertEqual(conversation._elide(text, manifest[f"budget.{name}"]), text)  # noqa: SLF001

    def test_every_behavior_rule_reaches_the_model(self):
        import re
        text = (PROMPT_DIR / "behavior.md").read_text(encoding="utf-8")
        manifest = conversation.load_interaction_manifest()
        delivered = conversation._elide(text, manifest["budget.behavior"])  # noqa: SLF001
        numbers = [int(m.group(1)) for m in re.finditer(r"^\*\*(\d+)\.", delivered, re.M)]
        self.assertEqual(numbers, list(range(1, ie.RUBRIC_CLAUSE_COUNT + 1)))


class NoRepetitionLint(unittest.TestCase):
    """behavior.md rule 13's structural floor."""

    def setUp(self):
        self.config = lints.load_lints_config()

    def test_the_incident_golden_trips_the_lint(self):
        golden = json.loads(
            (GOLDENS_DIR / ie.REPETITION_LOOP_FIXTURE_FILE).read_text(encoding="utf-8")
        )
        findings = lints.lint_transcript(golden["turns"], config=self.config)
        repeats = [f for f in findings if f["lint"] == "no_repetition"]
        self.assertEqual(
            [f["turn_index"] for f in repeats], [3, 5],
            msg="both re-asks in the incident transcript must be flagged",
        )

    def test_a_genuinely_new_question_is_not_flagged(self):
        golden = json.loads(
            (GOLDENS_DIR / "chat-garden-deflection.json").read_text(encoding="utf-8")
        )
        findings = lints.lint_transcript(golden["turns"], config=self.config)
        self.assertEqual([f for f in findings if f["lint"] == "no_repetition"], [])

    def test_every_committed_reference_golden_stays_clean(self):
        for golden in ie.load_goldens():
            with self.subTest(golden=golden.get("golden_id")):
                findings = lints.lint_transcript(golden["turns"], config=self.config)
                self.assertEqual(
                    [f for f in findings if f["lint"] == "no_repetition"], [],
                    msg="the repetition lint must be false-positive-strict",
                )

    def test_an_echoed_user_question_is_not_a_repeat(self):
        prior = [lints.asks_in("What did she say when you told her?")]
        text = 'You once asked me, "what did she say when you told her?", and I never answered.'
        self.assertEqual(lints.lint_repetition(text, prior, config=self.config), [])

    def test_lookback_is_bounded_so_a_late_callback_is_allowed(self):
        ask = "what were you about to say"
        prior = [[ask], [], [], []]
        self.assertEqual(
            lints.lint_repetition("What were you about to say?", prior, config=self.config),
            [],
            msg="only the last repetition.lookback ASKING turns are compared",
        )

    def test_the_lint_can_be_switched_off(self):
        off = dict(self.config, **{"lint.no_repetition": False})
        prior = [lints.asks_in("What were you about to say?")]
        self.assertEqual(lints.lint_repetition("What were you about to say?", prior, config=off), [])


class RepetitionBlocksTheSend(unittest.TestCase):
    def test_lint_outgoing_blocks_a_repeat(self):
        session = _session([
            {"role": "user", "text": "It was a hard few years."},
            {"role": "lifehug", "text": "That lands. What were you about to say?"},
            {"role": "user", "text": "I already told you."},
        ])
        blocking, _ = engine.lint_outgoing(
            "I hear you. So what were you about to say?",
            question_allowed=True,
            prior_asks=engine.session_prior_asks(session),
        )
        self.assertIn("no_repetition", blocking)
        self.assertIn("no_repetition", engine.RUNTIME_BLOCKING_LINTS)

    def test_without_prior_asks_the_call_is_byte_identical_to_pre_v201(self):
        message = "That lands. What were you about to say?"
        self.assertEqual(
            engine.lint_outgoing(message, question_allowed=True),
            engine.lint_outgoing(message, question_allowed=True, prior_asks=()),
        )

    def test_session_prior_asks_reads_only_lifehug_turns(self):
        session = _session([
            {"role": "user", "text": "Why do you keep asking that?"},
            {"role": "lifehug", "text": "Fair. What happened next?"},
        ])
        self.assertEqual(engine.session_prior_asks(session), [["what happened next"]])


if __name__ == "__main__":
    unittest.main()
