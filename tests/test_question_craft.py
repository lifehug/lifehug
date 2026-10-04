"""ADR 0042: a question passes or it is not a question.

Golden shapes for `question_craft.evaluate`. Every fixture is SYNTHETIC — the
SHAPES are the ones lifehug-platform#984 found in a real bank (one-word
follow-ups, `When was {label}?` keystone templates, probes that narrate the
vault or the system), the names and details are invented.

Every rule has a test that fires and a near-miss that does not.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "system"))

import question_candidates as qc  # noqa: E402
import question_craft as craft  # noqa: E402

NEGATIVES = {
    "update": "too_short",
    "gist": "too_short",
    "When was wedding?": "label_template",
    "When was move to Springfield?": "label_template",
    "When was MIT?": "label_template",
    "When did you graduate from high school graduation?": "garbled_repeat",
    ("Roughly when was closing the Series A at Brightwater? Your answer places "
     "8 timeline moments at once."): "narrates_system",
    ("Pell Ardmore appears in your records only as a name under partnerships, "
     "with no story behind it yet — what do you remember about the day you met?"):
        "narrates_records",
    ("You received 435 emails from quillmail.example in 2011, but there is no "
     "matching period or place in your wiki — what were you doing then?"):
        "narrates_records",
}

POSITIVES = [
    "When did High School begin — before or after your first job?",
    "You mentioned the Lisbon meeting with Tomas Vell — when was that?",
    "Tell me about a failure that taught you something important.",
    "What does the day-to-day between you and your son look like right now?",
    # twenty ordinary bank-shaped questions
    "What is your earliest memory of the house you grew up in?",
    "Who was the first friend you made at a new school?",
    "What did your grandmother's kitchen smell like on a Sunday?",
    "Where were you living when you turned twenty-one?",
    "What was the hardest conversation you ever had with your father?",
    "How did you and your partner first meet?",
    "What did you want to be when you were ten years old?",
    "Describe the first place you lived on your own.",
    "Walk me through the day you started your first real job.",
    "What did you learn from the job you were fired from?",
    "Which teacher changed how you saw yourself, and how?",
    "What were you most afraid of as a child?",
    "Take me back to the night before you left home.",
    "What song takes you straight back to your teenage years?",
    "Who taught you how to drive, and what was that like?",
    "What tradition from your family do you still keep today?",
    "Think of a time you were proud of yourself — what happened?",
    "What did your mother always say when you left the house?",
    "When did you first feel like an adult?",
    "Pick one photo from your childhood and tell me what is in it.",
]


def verdict(text, **context):
    return craft.evaluate(text, context=context or None, with_score=False)


class GoldenShapesTests(unittest.TestCase):
    def test_every_negative_fails_for_its_reason(self):
        for text, reason in NEGATIVES.items():
            with self.subTest(text=text):
                result = verdict(text)
                self.assertEqual(result["verdict"], craft.FAIL)
                self.assertIn(reason, [r.split(":")[0] for r in result["reasons"]])

    def test_every_positive_passes(self):
        for text in POSITIVES:
            with self.subTest(text=text):
                self.assertEqual(verdict(text), {"verdict": craft.PASS, "reasons": [], "score": 0.0})

    def test_twenty_ordinary_bank_questions_are_in_the_positive_set(self):
        self.assertGreaterEqual(len(POSITIVES) - 4, 20)

    def test_only_a_pass_carries_a_score(self):
        passed = craft.evaluate(POSITIVES[4])
        self.assertGreater(passed["score"], 0.0)
        self.assertEqual(craft.evaluate("update")["score"], 0.0)

    def test_the_score_is_the_unified_quality_score(self):
        text = POSITIVES[4]
        expected = qc.unified_quality_score({"text": text, "priority": 0.9})["score"]
        self.assertEqual(
            craft.evaluate(text, context={"candidate": {"priority": 0.9}})["score"], expected)


class RuleTests(unittest.TestCase):
    """One fire and one near miss per rule."""

    def assertFails(self, text, reason, **context):
        result = verdict(text, **context)
        self.assertEqual(result["verdict"], craft.FAIL, result)
        self.assertIn(reason, [r.split(":")[0] for r in result["reasons"]])

    def assertNotFor(self, text, reason, **context):
        result = verdict(text, **context)
        self.assertNotIn(reason, [r.split(":")[0] for r in result["reasons"]], result)

    def test_too_short(self):
        self.assertFails("What scares you?", "too_short")
        self.assertNotFor("What scares you the most?", "too_short")

    def test_punctuation_is_not_a_word(self):
        self.assertFails("Why — and how?", "too_short")

    def test_not_a_question(self):
        self.assertFails("A specific childhood afternoon spent alone at the lake.", "not_a_question")
        self.assertNotFor("Describe a specific childhood afternoon spent alone.", "not_a_question")

    def test_every_imperative_opener_is_a_question(self):
        for opener in craft.IMPERATIVE_OPENERS:
            with self.subTest(opener=opener):
                text = f"{opener.capitalize()} the summer your family moved away."
                self.assertNotFor(text, "not_a_question")

    def test_a_question_with_one_line_of_guidance_is_a_question(self):
        self.assertNotFor("About when was the harbor fire? A year or your age is enough.",
                          "not_a_question")

    def test_label_template_was(self):
        self.assertFails("When was closing the Orchard Street deal?", "label_template")
        self.assertNotFor("When was the Orchard Street deal closed?", "label_template")
        self.assertNotFor("When was Juniper's first birthday party?", "label_template")
        self.assertNotFor("When were you living on Orchard Street?", "label_template")

    def test_label_template_did(self):
        self.assertFails("When did the big Calloway family wedding?", "label_template")
        self.assertFails("When did Orchard Street graduation?", "label_template")
        self.assertNotFor("When did the Calloway family move?", "label_template")
        self.assertNotFor("When did you move to Calloway Street?", "label_template")

    def test_a_person_subject_is_never_a_template(self):
        self.assertNotFor("When was your first apartment lease signed?", "label_template")

    def test_internal_node_id(self):
        self.assertFails("When was node:63099d24ba8c9fe2e6dd800a?", "internal_id")
        self.assertNotFor("When did you first visit the node station?", "internal_id")

    def test_slug_with_a_digit(self):
        self.assertFails("What do you remember about move-to-springfield-2009?", "internal_id")

    def test_hyphenated_words_are_not_slugs(self):
        for text in ("What does the day-to-day look like with your son?",
                     "Who handled things in a matter-of-fact way in your family?",
                     "Which hand-me-downs did you wear as a kid?"):
            with self.subTest(text=text):
                self.assertNotFor(text, "internal_id")

    def test_a_named_slug_from_context(self):
        text = "What do you remember about the harbor-fire-night afterwards?"
        self.assertFails(text, "internal_id", slugs=["harbor-fire-night"])
        self.assertNotFor(text, "internal_id")

    def test_a_bare_name_in_context_is_never_a_slug(self):
        self.assertNotFor("What was Juniper like as a little girl?", "internal_id",
                          roster=["juniper"])

    def test_snake_case_and_placeholders(self):
        self.assertFails("When did the period_bound start for you?", "internal_id")
        self.assertFails("When did {label} begin for you?", "internal_id")

    def test_empty_subject(self):
        self.assertFails("What was it like when you were about none?", "empty_subject")
        self.assertNotFor("What was it like when you had none of it?", "empty_subject")

    def test_garbled_repeat(self):
        self.assertFails("How did you celebrate your college celebration?", "garbled_repeat")
        self.assertNotFor("When did your career start and how has your career changed?",
                          "garbled_repeat")

    def test_narrates_records(self):
        self.assertFails("Nothing written about your uncle yet — who was he?", "narrates_records")
        self.assertNotFor("Who kept the family records when you were growing up?",
                          "narrates_records")

    def test_narrates_system(self):
        self.assertFails("What changed when you were thirty? This covers 40% of the gap.",
                         "narrates_system")
        self.assertFails("When did you leave Ohio? That would place 6 events.", "narrates_system")
        self.assertNotFor("What were the 3 places you lived before college?", "narrates_system")

    def test_bare_yes_no(self):
        self.assertFails("Did you enjoy your time in college?", "bare_yes_no")
        self.assertNotFor("Did you enjoy college, and what made it that way?", "bare_yes_no")
        self.assertNotFor("Did you enjoy college? What do you miss most?", "bare_yes_no")
        self.assertNotFor("Were you close to your brother — what did he teach you?", "bare_yes_no")

    def test_polite_imperatives_and_embedded_questions_are_not_bare(self):
        self.assertNotFor("Can you tell me about your first kitchen?", "bare_yes_no")
        self.assertNotFor("Do you know the year you got married?", "bare_yes_no")
        self.assertNotFor("Do you remember where you were that night?", "bare_yes_no")


class ReviewTests(unittest.TestCase):
    def test_short_with_no_concrete_noun_is_review(self):
        result = verdict("Can you tell me more about that?")
        self.assertEqual(result["verdict"], craft.REVIEW)
        self.assertEqual(result["reasons"], ["no_concrete_noun"])

    def test_short_with_a_concrete_noun_passes(self):
        self.assertEqual(verdict("What was your first car?")["verdict"], craft.PASS)

    def test_eight_words_is_never_held_for_concreteness(self):
        self.assertEqual(verdict("Can you tell me a little more about that?")["verdict"],
                         craft.PASS)

    def test_exact_duplicate_is_review(self):
        bank = [("A1", "What is your earliest memory of the house you grew up in?")]
        result = verdict("what is your earliest memory of the house you grew up in", bank=bank)
        # no question mark: still a FAIL first — verdicts are ordered
        self.assertEqual(result["verdict"], craft.FAIL)
        result = verdict("What is your earliest memory of the house you grew up in?", bank=bank)
        self.assertEqual(result, {"verdict": craft.REVIEW, "reasons": ["duplicate_of:A1"],
                                  "score": 0.0})

    def test_near_duplicate_is_review(self):
        bank = [{"id": "C4", "text": "As a parent, what did you promise yourself you'd do differently?"}]
        result = verdict("As a parent, what did you promise yourself you would do differently?",
                         bank=bank)
        self.assertEqual(result["verdict"], craft.REVIEW)
        self.assertEqual(result["reasons"], ["near_duplicate_of:C4"])

    def test_a_question_is_never_its_own_duplicate(self):
        text = "What is your earliest memory of the house you grew up in?"
        self.assertEqual(verdict(text, bank=[("A1", text)], self_id="A1")["verdict"], craft.PASS)

    def test_an_unrelated_bank_is_not_a_duplicate(self):
        bank = [("A1", "Who taught you how to swim at the lake?")]
        self.assertEqual(verdict(POSITIVES[4], bank=bank)["verdict"], craft.PASS)


class OneTableTests(unittest.TestCase):
    """v382's narrates-records table lives in one place and the score path reads it."""

    def test_question_candidates_reads_the_craft_tables(self):
        self.assertIs(qc.NARRATES_RECORDS_PHRASES, craft.NARRATES_RECORDS_PHRASES)
        self.assertIs(qc.NARRATES_RECORDS_PATTERN, craft.NARRATES_RECORDS_PATTERN)
        self.assertIs(qc.YES_NO_PATTERNS, craft.YES_NO_PATTERNS)

    def test_the_score_path_keeps_its_penalty(self):
        flags = qc.check_quality("Who is in your records only as a name?")["flags"]
        self.assertIn("narrates_records", flags)

    def test_the_table_is_defined_only_in_question_craft(self):
        for path in (ROOT / "system").glob("*.py"):
            if path.name == "question_craft.py":
                continue
            with self.subTest(path=path.name):
                self.assertNotIn('"in your records",', path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
