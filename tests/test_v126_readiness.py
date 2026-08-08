"""v126: format readiness engine (system/format_readiness.py).

Four suites:

* ``ReadinessMathTests`` — slot-fill math, gap questions, and verdict
  thresholds against SYNTHETIC framework dicts (compute_readiness takes the
  dict, so nothing touches disk).
* ``ThresholdParityTests`` — the shipped specs keep book.py's verdict scale.
* ``FocusAdapterTests`` — the Studio adapter (book focuses deferred to
  book.compute_books, everything else gets cards).
* ``RealLetterFrameworkTests`` / ``ReadinessCliTests`` — end-to-end against the
  real templates/letter.json and the CLI entry point.

Story-function reachability caveat (documented by
``test_relational_functions_unreachable_by_planner_but_covered_by_overlay``
below): the relational functions the letter framework leans on —
who_they_are, shared_history, what_i_see_in_them, what_i_want_them_to_know,
how_they_see_me — have no entries in
``question_planner.STORY_FUNCTION_KEYWORDS`` and no ``KIND_TO_STORY_FUNCTION``
route, so the planner alone can never classify a bank question into them.
format_readiness therefore carries a contained RELATIONAL_KEYWORDS overlay
(checked before the planner's classifier) calibrated against real vault
phrasing; the real-framework test proves a letter can reach READY through
it, and the coverage test fails loudly the day the planner learns the
relational arc (the signal to delete the overlay).
"""

from __future__ import annotations

import io
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SYSTEM = ROOT / "system"
sys.path.insert(0, str(SYSTEM))

import book  # noqa: E402
import format_frameworks  # noqa: E402
import format_readiness  # noqa: E402
import lifehug_core  # noqa: E402
import question_planner  # noqa: E402

VERDICTS = {"EARLY", "DEVELOPING", "READY"}

# Texts whose keyword inference is asserted before use (see _assert_functions).
SCENE_TEXT = "Walk me through that day. What did the room look like?"
SCENE_TEXT_2 = "Walk me through the drive home. Where were you sitting?"
MEANING_TEXT = "Why does that still matter to you?"
TENSION_TEXT = "What was the hardest part of that stretch?"
TURNING_TEXT = "What was the turning point for you?"


def q(qid: str, text: str, answered: bool, category: str | None = None) -> dict:
    """A bank question record in ``lifehug_core.parse_questions`` shape."""
    return {
        "id": qid,
        "category": category if category is not None else qid[0],
        "text": text,
        "answered": answered,
    }


def slot(sid: str, functions: list[str], min_answers: int = 1) -> dict:
    return {
        "id": sid,
        "label": sid.replace("_", " ").title(),
        "description": f"Description for {sid}.",
        "story_functions": functions,
        "min_answers": min_answers,
    }


def framework(*slots, fid: str = "mock_format", thresholds: dict | None = None) -> dict:
    return {
        "id": fid,
        "label": fid.replace("_", " ").title(),
        "slots": list(slots),
        "thresholds": thresholds or {"ready": book.READY, "developing": book.DEVELOPING},
        "ai_context": [],
    }


class StoryFunctionReachabilityTests(unittest.TestCase):
    """Guards on the classifier the readiness engine delegates to."""

    def test_crafted_texts_infer_the_intended_functions(self):
        for text, expected in (
            (SCENE_TEXT, "scene"),
            (SCENE_TEXT_2, "scene"),
            (MEANING_TEXT, "meaning"),
            (TENSION_TEXT, "tension"),
            (TURNING_TEXT, "turning_point"),
        ):
            with self.subTest(text=text):
                self.assertEqual(question_planner.infer_story_function(text), expected)

    def test_relational_functions_unreachable_by_planner_but_covered_by_overlay(self):
        """The planner still can't classify the relational arc; the overlay must.

        The relational functions are declared in lifehug_core.STORY_FUNCTIONS
        and used by the letter/legacy_letter/unsent_letter specs, but have no
        entries in question_planner's keyword tables. format_readiness carries
        a contained RELATIONAL_KEYWORDS overlay so readiness matching still
        reaches them. If the planner ever learns these functions, the first
        assertion fails loudly — that's the signal to delete the overlay.
        """
        relational = {"who_they_are", "shared_history", "what_i_see_in_them",
                      "what_i_want_them_to_know", "how_they_see_me"}
        for name in relational:
            self.assertIn(name, lifehug_core.STORY_FUNCTIONS)
        planner_reachable = set(question_planner.STORY_FUNCTION_KEYWORDS) | set(
            question_planner.KIND_TO_STORY_FUNCTION.values()) | {"foundation"}
        self.assertEqual(relational & planner_reachable, set())
        overlay_covered = {fn for fn, _ in format_readiness.RELATIONAL_KEYWORDS}
        self.assertEqual(relational, overlay_covered)
        for fn, phrases in format_readiness.RELATIONAL_KEYWORDS:
            self.assertIn(fn, lifehug_core.STORY_FUNCTIONS)
            self.assertTrue(phrases)


class ReadinessMathTests(unittest.TestCase):
    def test_slot_fills_only_on_enough_answered_matches(self):
        fw = framework(slot("opening", ["scene"], min_answers=2))
        questions = [
            q("K1", SCENE_TEXT, True),
            q("K2", SCENE_TEXT_2, True),
        ]
        result = format_readiness.compute_readiness(fw, ["K"], questions)
        row = result["slots"][0]
        self.assertTrue(row["filled"])
        self.assertEqual(row["matched"], ["K1", "K2"])
        self.assertEqual(row["needed"], 2)
        self.assertEqual(result["filled_slots"], 1)
        self.assertEqual(result["total_slots"], 1)
        self.assertEqual(result["format"], "mock_format")

    def test_one_short_does_not_fill(self):
        fw = framework(slot("opening", ["scene"], min_answers=2))
        result = format_readiness.compute_readiness(fw, ["K"], [q("K1", SCENE_TEXT, True)])
        self.assertFalse(result["slots"][0]["filled"])
        self.assertEqual(result["slots"][0]["matched"], ["K1"])

    def test_unanswered_questions_never_fill_a_slot(self):
        fw = framework(slot("opening", ["scene"], min_answers=1))
        result = format_readiness.compute_readiness(fw, ["K"], [q("K1", SCENE_TEXT, False)])
        self.assertFalse(result["slots"][0]["filled"])
        self.assertEqual(result["slots"][0]["matched"], [])

    def test_out_of_scope_categories_are_ignored(self):
        fw = framework(slot("opening", ["scene"], min_answers=1))
        questions = [q("Z1", SCENE_TEXT, True, category="Z")]
        result = format_readiness.compute_readiness(fw, ["K"], questions)
        self.assertFalse(result["slots"][0]["filled"])
        self.assertEqual(result["ratio"], 0.0)

    def test_gap_questions_are_unanswered_capped_and_id_sorted(self):
        fw = framework(slot("opening", ["scene"], min_answers=1))
        questions = [
            q("K5", SCENE_TEXT, False),
            q("K2", SCENE_TEXT_2, False),
            q("K4", SCENE_TEXT, False),
            q("K1", SCENE_TEXT_2, False),
            q("K3", SCENE_TEXT, True),   # answered → never a gap
            q("K6", MEANING_TEXT, False),  # wrong story function → not this slot's gap
        ]
        gaps = format_readiness.compute_readiness(fw, ["K"], questions)["slots"][0]
        self.assertEqual([g["id"] for g in gaps["gap_questions"]], ["K1", "K2", "K4"])
        self.assertEqual(gaps["gap_questions"][0]["text"], SCENE_TEXT_2)

    def test_gap_cap_matches_module_constant(self):
        self.assertEqual(format_readiness.MAX_GAP_QUESTIONS, 3)

    def _four_slot_result(self, filled: int) -> dict:
        """A 4-slot framework with ``filled`` slots satisfied → ratio filled/4."""
        fw = framework(
            slot("s_scene", ["scene"]),
            slot("s_meaning", ["meaning"]),
            slot("s_tension", ["tension"]),
            slot("s_turning", ["turning_point"]),
        )
        texts = [SCENE_TEXT, MEANING_TEXT, TENSION_TEXT, TURNING_TEXT]
        questions = [q(f"K{i + 1}", text, i < filled) for i, text in enumerate(texts)]
        return format_readiness.compute_readiness(fw, ["K"], questions)

    def test_verdict_ready_at_three_quarters(self):
        result = self._four_slot_result(3)
        self.assertEqual(result["ratio"], 0.75)
        self.assertEqual(result["verdict"], "READY")

    def test_verdict_developing_at_half(self):
        result = self._four_slot_result(2)
        self.assertEqual(result["ratio"], 0.5)
        self.assertEqual(result["verdict"], "DEVELOPING")

    def test_verdict_early_at_a_quarter(self):
        result = self._four_slot_result(1)
        self.assertEqual(result["ratio"], 0.25)
        self.assertEqual(result["verdict"], "EARLY")

    def test_verdict_vocabulary_is_closed(self):
        for filled in range(5):
            with self.subTest(filled=filled):
                self.assertIn(self._four_slot_result(filled)["verdict"], VERDICTS)

    def test_framework_thresholds_override_defaults(self):
        fw = framework(
            slot("s_scene", ["scene"]),
            slot("s_meaning", ["meaning"]),
            thresholds={"ready": 0.5, "developing": 0.25},
        )
        questions = [q("K1", SCENE_TEXT, True), q("K2", MEANING_TEXT, False)]
        # 1/2 filled would be DEVELOPING on book's scale; this spec calls it READY.
        self.assertEqual(format_readiness.compute_readiness(fw, ["K"], questions)["verdict"],
                         "READY")

    def test_degraded_none_framework_is_benign(self):
        result = format_readiness.compute_readiness(None, ["K"], [q("K1", SCENE_TEXT, True)])
        self.assertEqual(result["slots"], [])
        self.assertEqual(result["total_slots"], 0)
        self.assertEqual(result["ratio"], 0.0)
        self.assertEqual(result["verdict"], "EARLY")

    def test_degraded_empty_slots_is_benign(self):
        result = format_readiness.compute_readiness(
            {"id": "book", "slots": []}, ["K"], [q("K1", SCENE_TEXT, True)])
        self.assertEqual(result["format"], "book")
        self.assertEqual(result["total_slots"], 0)
        self.assertEqual(result["verdict"], "EARLY")

    def test_degraded_no_questions_and_no_categories(self):
        fw = framework(slot("opening", ["scene"]))
        result = format_readiness.compute_readiness(fw, [], [])
        self.assertEqual(result["filled_slots"], 0)
        self.assertEqual(result["total_slots"], 1)
        self.assertEqual(result["verdict"], "EARLY")


class ThresholdParityTests(unittest.TestCase):
    def test_letter_thresholds_match_book_module(self):
        letter = format_frameworks.get("letter")
        self.assertEqual(letter["thresholds"]["ready"], book.READY)
        self.assertEqual(letter["thresholds"]["developing"], book.DEVELOPING)

    def test_module_defaults_are_book_thresholds(self):
        self.assertEqual(format_readiness.DEFAULT_READY, book.READY)
        self.assertEqual(format_readiness.DEFAULT_DEVELOPING, book.DEVELOPING)

    def test_verdict_for_matches_book_verdict_vocabulary(self):
        self.assertEqual(format_readiness.verdict_for(book.READY), "READY")
        self.assertEqual(format_readiness.verdict_for(book.DEVELOPING), "DEVELOPING")
        self.assertEqual(format_readiness.verdict_for(book.DEVELOPING - 0.01), "EARLY")


class FocusAdapterTests(unittest.TestCase):
    def setUp(self):
        self.questions = [q("K1", SCENE_TEXT, True), q("K2", SCENE_TEXT_2, True)]

    def test_book_deliverables_come_from_the_book_framework(self):
        self.assertEqual(format_readiness.book_deliverables(),
                         frozenset({"book", "chapter", "memoir", "manuscript"}))

    def test_book_focus_returns_no_cards(self):
        for deliverable in sorted(format_readiness.book_deliverables()):
            with self.subTest(deliverable=deliverable):
                focus = {"id": "f-life", "type": "life_story",
                         "deliverable": deliverable, "categories": ["K"]}
                self.assertEqual(
                    format_readiness.readiness_for_focus(focus, self.questions), [])

    def test_person_focus_gets_a_letter_card_tagged_with_focus_id(self):
        focus = {"id": "f-mom", "label": "Mom", "type": "person",
                 "deliverable": "letter", "categories": ["K"]}
        cards = format_readiness.readiness_for_focus(focus, self.questions)
        self.assertEqual(len(cards), 1)
        self.assertEqual(cards[0]["format"], "letter")
        self.assertEqual(cards[0]["focus_id"], "f-mom")
        self.assertTrue(cards[0]["slots"])

    def test_person_focus_with_unmapped_deliverable_falls_back_to_letter(self):
        focus = {"id": "f-dad", "type": "person",
                 "deliverable": "keepsake", "categories": ["K"]}
        self.assertEqual(format_readiness.default_formats_for_focus(focus), ["letter"])
        cards = format_readiness.readiness_for_focus(focus, self.questions)
        self.assertEqual([c["format"] for c in cards], ["letter"])

    def test_non_person_focus_with_unmapped_deliverable_gets_nothing(self):
        focus = {"id": "f-theme", "type": "theme",
                 "deliverable": "keepsake", "categories": ["K"]}
        self.assertEqual(format_readiness.readiness_for_focus(focus, self.questions), [])

    def test_explicit_formats_are_honoured_and_unknown_ones_skipped(self):
        focus = {"id": "f-mom", "type": "person",
                 "deliverable": "letter", "categories": ["K"]}
        cards = format_readiness.readiness_for_focus(
            focus, self.questions, formats=["letter", "nonexistent_format", "book"])
        # "book" is composite with no slots; "nonexistent_format" has no spec.
        self.assertEqual([c["format"] for c in cards], ["letter"])


class RealLetterFrameworkTests(unittest.TestCase):
    """End-to-end against the shipped templates/letter.json."""

    def setUp(self):
        self.letter = format_frameworks.get("letter")

    def test_opening_moment_fills_from_two_scene_answers(self):
        questions = [
            q("K1", SCENE_TEXT, True),
            q("K2", SCENE_TEXT_2, True),
            q("K3", SCENE_TEXT, False),
        ]
        result = format_readiness.compute_readiness(self.letter, ["K"], questions)
        rows = {row["id"]: row for row in result["slots"]}
        self.assertEqual(set(rows), {"opening_moment", "who_they_are", "shared_history",
                                     "what_i_see_in_them", "what_i_want_them_to_know"})
        self.assertTrue(rows["opening_moment"]["filled"])
        self.assertEqual(rows["opening_moment"]["matched"], ["K1", "K2"])
        self.assertEqual([g["id"] for g in rows["opening_moment"]["gap_questions"]], ["K3"])

    def test_letter_reaches_ready_via_relational_overlay(self):
        """Real-vault question phrasing fills the relational slots.

        Texts mirror the live bank's Mom category (K1/K3/K3a/K5/K5c/K15
        phrasing) — the overlay exists precisely so these classify into the
        relational arc instead of all collapsing to scene/meaning.
        """
        questions = [
            q("K1", SCENE_TEXT, True),
            q("K2", SCENE_TEXT_2, True),
            q("K3", "What was she like as a person, beyond being a mother?", True),
            q("K4", "Describe a moment with your mom that you wish you could relive.", True),
            q("K5", "What did you two actually do together during that time?", True),
            q("K6", "Is there a moment where she felt seen and appreciated by you?", True),
            q("K7", "What would you want to say to her that you haven't said?", True),
            q("K8", "Is there anything you wish you had told your mom?", False),
        ]
        result = format_readiness.compute_readiness(self.letter, ["K"], questions)
        rows = {row["id"]: row for row in result["slots"]}
        self.assertTrue(rows["who_they_are"]["filled"])
        self.assertEqual(rows["who_they_are"]["matched"], ["K3"])
        self.assertTrue(rows["shared_history"]["filled"])  # K4 + K5, min 2
        self.assertEqual(rows["shared_history"]["matched"], ["K4", "K5"])
        self.assertTrue(rows["what_i_see_in_them"]["filled"])
        self.assertTrue(rows["what_i_want_them_to_know"]["filled"])
        self.assertEqual(
            [g["id"] for g in rows["what_i_want_them_to_know"]["gap_questions"]],
            ["K8"])
        self.assertEqual(result["filled_slots"], 5)
        self.assertEqual(result["verdict"], "READY")

    def test_chapter_framework_reaches_ready(self):
        """A reachable-function framework proves the engine can actually say READY."""
        chapter = format_frameworks.get("chapter")
        questions = [
            q("K1", "Tell me about the house you grew up in.", True),   # foundation
            q("K2", MEANING_TEXT, True),                                # meaning
            q("K3", SCENE_TEXT, True),                                  # scene
            q("K4", SCENE_TEXT_2, True),                                # scene
            q("K5", TURNING_TEXT, True),                                # turning_point
            q("K6", TENSION_TEXT, True),                                # tension
        ]
        result = format_readiness.compute_readiness(chapter, ["K"], questions)
        self.assertEqual(result["filled_slots"], result["total_slots"])
        self.assertEqual(result["verdict"], "READY")


class ArtifactPromptSectionTests(unittest.TestCase):
    """The additive FORMAT FRAMEWORK block in artifact.build_prompt."""

    def setUp(self):
        import artifact  # noqa: PLC0415
        self.artifact = artifact

    def test_section_is_added_for_a_slotted_format(self):
        prompt = self.artifact.build_prompt(
            {"title": "t", "format": "letter", "subject": "Mom", "categories": []}, "CTX")
        self.assertIn("FORMAT FRAMEWORK (researched structure", prompt)
        self.assertIn("1. Opening Moment:", prompt)
        # No categories → no coverage lines at all.
        self.assertNotIn("Covered by answers:", prompt)

    def test_categories_add_coverage_lines(self):
        prompt = self.artifact.build_prompt(
            {"title": "t", "format": "letter", "subject": "Mom", "categories": ["A"]}, "CTX")
        self.assertIn("Covered by answers:", prompt)

    def test_section_is_absent_for_a_slotless_format(self):
        section = self.artifact.build_framework_section({"format": "book", "categories": []})
        self.assertEqual(section, "")

    def test_ai_context_lines_are_appended(self):
        section = self.artifact.build_framework_section({"format": "letter", "categories": []})
        for note in format_frameworks.get("letter")["ai_context"]:
            self.assertIn(note, section)

    def test_prompt_spacing_regression_guard(self):
        prompt = self.artifact.build_prompt(
            {"title": "t", "format": "letter", "categories": []}, "CTX")
        self.assertIn("excerpts or Q&A.\n\nFORMAT INSTRUCTIONS", prompt)
        self.assertIn("\n\nARTIFACT DETAILS", prompt)


class ReadinessCliTests(unittest.TestCase):
    """CLI compute path, driven in-process (no subprocess)."""

    BANK = (
        "## K: Mom (person)\n\n"
        f"- [x] K1: {SCENE_TEXT}\n"
        f"- [x] K2: {SCENE_TEXT_2}\n"
        f"- [ ] K3: {MEANING_TEXT}\n"
    )

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.bank = self.tmp / "question-bank.md"
        self.bank.write_text(self.BANK, encoding="utf-8")

    def test_print_readiness_reads_the_bank_and_exits_zero(self):
        saved = format_readiness.QUESTIONS_FILE
        format_readiness.QUESTIONS_FILE = self.bank
        try:
            buf = io.StringIO()
            with redirect_stdout(buf):
                code = format_readiness.print_readiness("letter", ["K"])
        finally:
            format_readiness.QUESTIONS_FILE = saved
        out = buf.getvalue()
        self.assertEqual(code, 0)
        self.assertIn("Letter readiness — categories K", out)
        self.assertIn("[x] Opening Moment — matched 2/2", out)
        self.assertIn("[ ] Who They Are — matched 0/1", out)
        self.assertIn("EARLY — 1/5 slots", out)

    def test_print_readiness_on_a_slotless_format_is_a_message_not_an_error(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = format_readiness.print_readiness("book", ["K"], questions=[])
        self.assertEqual(code, 0)
        self.assertIn("No format framework with slots", buf.getvalue())

    def test_cmd_artifact_readiness_dispatches_read_only(self):
        import lifehug  # noqa: PLC0415

        saved = lifehug.QUESTIONS_FILE
        lifehug.QUESTIONS_FILE = self.bank
        try:
            buf = io.StringIO()
            with redirect_stdout(buf):
                code = lifehug.cmd_artifact_readiness(
                    ["--format", "letter", "--categories", "K"])
        finally:
            lifehug.QUESTIONS_FILE = saved
        out = buf.getvalue()
        self.assertEqual(code, 0)
        self.assertIn("[x] Opening Moment — matched 2/2", out)
        self.assertIn("EARLY — 1/5 slots", out)

    def test_cmd_artifact_readiness_without_scope_is_a_nudge(self):
        import lifehug  # noqa: PLC0415

        buf = io.StringIO()
        with redirect_stdout(buf):
            code = lifehug.cmd_artifact_readiness([])
        self.assertEqual(code, 0)
        self.assertIn("--subject", buf.getvalue())

    def test_readiness_never_enqueues_a_job(self):
        """cmd_artifact routes `readiness` in-process — no queue, no writer lock."""
        import argparse  # noqa: PLC0415

        import lifehug  # noqa: PLC0415

        calls: list = []
        saved_queue = lifehug._queue_and_wait
        saved_run = lifehug.run_python
        saved_bank = lifehug.QUESTIONS_FILE
        lifehug._queue_and_wait = lambda *a, **k: calls.append(("queue", a)) or 0
        lifehug.run_python = lambda *a, **k: calls.append(("run", a)) or 0
        lifehug.QUESTIONS_FILE = self.bank
        try:
            args = argparse.Namespace(
                artifact_help=False,
                artifact_args=["readiness", "--format", "letter", "--categories", "K"])
            buf = io.StringIO()
            with redirect_stdout(buf):
                code = lifehug.cmd_artifact(args)
        finally:
            lifehug._queue_and_wait = saved_queue
            lifehug.run_python = saved_run
            lifehug.QUESTIONS_FILE = saved_bank
        self.assertEqual(code, 0)
        self.assertEqual(calls, [])
        self.assertIn("EARLY — 1/5 slots", buf.getvalue())


if __name__ == "__main__":
    unittest.main()
