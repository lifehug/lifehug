"""v422 (ADR 0045): a question anywhere is a question; the owner's keep is the
owner's pass; a rewrite is the same question resaid.

The seven positive texts are the owner's own bank rows that the Foundation
"Needs attention" list (platform #984) showed as craft FAILs; everything else
is synthetic. NEVER reads a real vault.
"""
from __future__ import annotations

import contextlib
import io
import json
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SYSTEM = ROOT / "system"
sys.path.insert(0, str(SYSTEM))
sys.path.insert(0, str(ROOT / "tests"))

import candidate_promotion as promotion  # noqa: E402
import lifehug  # noqa: E402
import lifehug_core as core  # noqa: E402
import question_bank as qb  # noqa: E402
import question_craft as craft  # noqa: E402
import question_planner as qp  # noqa: E402
from tempdirs import root_parent_tmp  # noqa: E402
from test_candidate_promotion import PromotionCase  # noqa: E402
from test_question_craft import POSITIVES  # noqa: E402

SEVEN = POSITIVES[-7:]
T23 = "When did you graduate from high school graduation?"
ILLINOIS = ("You received 435 emails from illinois between 2014 and 2026, with no matching "
            "period or place in your wiki — what was your connection to it?")
GOOD = "What did the kitchen in your first apartment look like?"

BANK = (
    "# Questions\n\n"
    "## A: Origins (Childhood)\n\n"
    "- [ ] A1: What is your earliest memory of the house on Larkspur Lane?\n"
    "- [x] A2: Who taught you how to ride a bicycle as a kid? *(2026-07-02)*\n"
    "- [-] A3: update *(retired 2026-10-04: too_short, not_a_question)*\n"
    "- [ ] A4: A quiet afternoon at the lake with your uncle.\n"
    "  <!-- candidate: cand-7 -->\n"
    "  <!-- craft: review: no_concrete_noun -->\n"
    "\n"
    "## B: Family\n\n"
    "- [ ] B1: What did your grandmother's kitchen smell like on Sundays?\n"
)


def verdict(text, **context):
    return craft.evaluate(text, context=context or None, with_score=False)


def reasons_of(text, **context):
    return [r.split(":")[0] for r in verdict(text, **context)["reasons"]]


class AQuestionAnywhereTests(unittest.TestCase):
    def test_the_rule_names_exist(self):
        self.assertTrue(craft.A_QUESTION_ANYWHERE_IS_A_QUESTION)
        self.assertTrue(craft.A_PLURAL_IS_NOT_A_NOMINALIZATION)
        self.assertTrue(craft.A_KEPT_QUESTION_IS_THE_OWNERS_PASS)
        self.assertTrue(qb.THE_OWNERS_KEEP_IS_ON_THE_ROW)
        self.assertTrue(qb.A_REWRITE_IS_THE_SAME_QUESTION_RESAID)

    def test_the_seven_held_back_questions_pass(self):
        self.assertEqual(len(SEVEN), 7)
        for text in SEVEN:
            with self.subTest(text=text[:40]):
                self.assertEqual(verdict(text), {"verdict": "pass", "reasons": [], "score": 0.0})

    def test_a_statement_then_a_question(self):
        self.assertNotIn("not_a_question",
                         reasons_of("You built a boat with your father. Where did you build it?"))

    def test_an_imperative_after_a_dash_colon_or_semicolon(self):
        for text in ("You said 'home is a kitchen' — tell me about the kitchen you meant.",
                     "You said 'home is a kitchen' - tell me about the kitchen you meant.",
                     "One thing first: describe the kitchen you grew up in.",
                     "You grew up on a farm; walk me through one harvest morning.",
                     "You grew up on a farm.  \"Tell me about one harvest morning.\""):
            with self.subTest(text=text):
                self.assertNotIn("not_a_question", reasons_of(text))

    def test_a_statement_is_still_not_a_question(self):
        self.assertIn("not_a_question",
                      reasons_of("A specific childhood afternoon spent alone at the lake."))
        self.assertIn("not_a_question",
                      reasons_of("You grew up on a farm. The harvest was in October."))
        # an opener word mid-clause is not a clause opening
        self.assertIn("not_a_question",
                      reasons_of("You would always share the harvest with your neighbors."))

    def test_narrating_the_records_still_fails(self):
        result = verdict(ILLINOIS)
        self.assertEqual(result["verdict"], "fail")
        self.assertIn("narrates_records", result["reasons"])


class APluralIsNotANominalizationTests(unittest.TestCase):
    def test_t23_still_fails(self):
        self.assertIn("garbled_repeat", reasons_of(T23))

    def test_a_word_and_its_plural_is_not_a_pair(self):
        for text in ("Which moments with your grandmother come back, and which single moment "
                     "matters most?",
                     "What decisions did you make that year, and which decision still stings?"):
            with self.subTest(text=text[:30]):
                self.assertNotIn("garbled_repeat", reasons_of(text))

    def test_the_suffix_must_be_on_the_longer_word(self):
        self.assertIn("garbled_repeat",
                      reasons_of("When did you settle into the settlement by the river?"))
        self.assertIn("garbled_repeat",
                      reasons_of("How did you celebrate your college celebrations?"))


class KeptIsTheOwnersPassTests(unittest.TestCase):
    def test_a_kept_fail_passes_with_its_reasons_overridden(self):
        result = verdict(T23, kept=True)
        self.assertEqual(result["verdict"], "pass")
        self.assertEqual(result["reasons"], [])
        self.assertEqual(result["overridden"], ["garbled_repeat"])

    def test_a_kept_review_is_overridden_too(self):
        result = verdict("Can you tell me more about that?", kept=True)
        self.assertEqual((result["verdict"], result["overridden"]), ("pass", ["no_concrete_noun"]))

    def test_a_kept_pass_has_an_empty_override_and_its_score(self):
        result = craft.evaluate(GOOD, context={"kept": True})
        self.assertEqual(result["overridden"], [])
        self.assertEqual(result["score"], craft.evaluate(GOOD)["score"])
        self.assertGreater(result["score"], 0.0)

    def test_the_key_is_absent_unless_kept(self):
        self.assertNotIn("overridden", verdict(T23))
        self.assertNotIn("overridden", verdict(T23, kept=False))

    def test_fail_reasons_stay_pure(self):
        self.assertEqual(craft.fail_reasons(T23, {"kept": True}), ["garbled_repeat"])


class KeepTests(unittest.TestCase):
    def test_keep_an_open_row(self):
        text, receipt = qb.keep_question(BANK, "B1", reason="my question", kept_on="2026-10-15")
        self.assertIn("- [ ] B1: What did your grandmother's kitchen smell like on Sundays?\n"
                      "  <!-- craft: kept 2026-10-15: my question -->\n", text)
        self.assertEqual(qb.craft_kept_index(text),
                         {"B1": {"date": "2026-10-15", "reason": "my question"}})
        self.assertEqual(receipt["id"], "B1")
        self.assertFalse(receipt["rekept"])
        rows = {r["id"]: r for r in qb.bank_rows(text)}
        self.assertTrue(rows["B1"]["kept"])
        self.assertFalse(rows["A1"]["kept"])

    def test_the_default_reason(self):
        text, receipt = qb.keep_question(BANK, "A1", kept_on="2026-10-15")
        self.assertIn("  <!-- craft: kept 2026-10-15: kept by the owner -->", text)
        self.assertEqual(receipt["reason"], "kept by the owner")

    def test_keep_drops_the_review_comment_and_keeps_provenance(self):
        text, receipt = qb.keep_question(BANK, "A4", reason="mine", kept_on="2026-10-15")
        self.assertIn("- [ ] A4: A quiet afternoon at the lake with your uncle.\n"
                      "  <!-- candidate: cand-7 -->\n"
                      "  <!-- craft: kept 2026-10-15: mine -->\n\n## B", text)
        self.assertNotIn("craft: review:", text)
        self.assertTrue(receipt["dropped_review"])
        self.assertEqual(receipt["overridden"], ["not_a_question"])

    def test_rekeeping_replaces_the_reason(self):
        text, _ = qb.keep_question(BANK, "B1", reason="first", kept_on="2026-10-14")
        text, receipt = qb.keep_question(text, "B1", reason="second", kept_on="2026-10-15")
        self.assertEqual(text.count("craft: kept"), 1)
        self.assertEqual(qb.craft_kept_index(text)["B1"],
                         {"date": "2026-10-15", "reason": "second"})
        self.assertTrue(receipt["rekept"])

    def test_only_an_open_row(self):
        for qid in ("A2", "A3", "Z9"):
            with self.subTest(qid=qid), self.assertRaises(ValueError):
                qb.keep_question(BANK, qid)

    def test_a_reason_cannot_close_the_comment(self):
        text, _ = qb.keep_question(BANK, "B1", reason="a --> b\nc", kept_on="2026-10-15")
        self.assertIn("  <!-- craft: kept 2026-10-15: a -- > b c -->", text)

    def test_a_kept_row_lints_as_a_pass_with_overridden(self):
        text, _ = qb.keep_question(BANK, "A4", kept_on="2026-10-15")
        entries = {e["id"]: e for e in qb.lint_bank(text)}
        self.assertEqual(entries["A4"]["verdict"], "pass")
        self.assertEqual(entries["A4"]["reasons"], [])
        self.assertTrue(entries["A4"]["kept"])
        self.assertEqual(entries["A4"]["overridden"], ["not_a_question"])
        self.assertEqual((entries["A1"]["kept"], entries["A1"]["overridden"]), (False, []))
        before = {e["id"]: e for e in qb.lint_bank(BANK)}
        self.assertEqual(before["A4"]["verdict"], "fail")


class RewriteTests(unittest.TestCase):
    def test_a_pass_is_written_clean_in_place(self):
        text, receipt = qb.rewrite_question(BANK, "A4", GOOD, rewritten_on="2026-10-15")
        self.assertIn(f"- [ ] A4: {GOOD}\n"
                      "  <!-- candidate: cand-7 -->\n"
                      '  <!-- craft: rewritten 2026-10-15: was "A quiet afternoon at the lake '
                      'with your uncle." -->\n\n## B', text)
        self.assertNotIn("craft: review:", text)
        self.assertEqual(receipt["verdict"], "pass")
        self.assertEqual(receipt["was"], "A quiet afternoon at the lake with your uncle.")
        self.assertEqual([r["id"] for r in qb.bank_rows(text)],
                         [r["id"] for r in qb.bank_rows(BANK)])

    def test_a_review_is_written_with_a_fresh_review_comment(self):
        text, receipt = qb.rewrite_question(
            BANK, "B1", "What is your earliest memory of the house on Larkspur Lane?",
            rewritten_on="2026-10-15")
        self.assertEqual(receipt["verdict"], "review")
        self.assertEqual(qb.craft_review_index(text)["B1"], ["duplicate_of:A1"])

    def test_a_fail_is_refused_and_nothing_is_written(self):
        with self.assertRaises(qb.CraftRefused) as caught:
            qb.rewrite_question(BANK, "B1", "gist")
        self.assertIn("too_short", caught.exception.reasons)
        self.assertIsInstance(caught.exception, ValueError)

    def test_prior_kept_and_review_comments_are_dropped(self):
        kept, _ = qb.keep_question(BANK, "A4", kept_on="2026-10-14")
        text, receipt = qb.rewrite_question(kept, "A4", GOOD, reason="clearer",
                                            rewritten_on="2026-10-15")
        self.assertNotIn("craft: kept", text)
        self.assertNotIn("craft: review:", text)
        self.assertIn("; clearer -->", text)
        self.assertEqual(receipt["dropped"], ["<!-- craft: kept 2026-10-14: kept by the owner -->"])

    def test_old_text_is_made_safe(self):
        bank = BANK.replace("- [ ] B1: What did your grandmother's kitchen smell like on Sundays?",
                            '- [ ] B1: What did "home" --> mean to you as a kid back then?')
        text, _ = qb.rewrite_question(bank, "B1", GOOD, rewritten_on="2026-10-15")
        self.assertIn("""was "What did 'home' -- > mean to you as a kid back then?" -->""", text)

    def test_only_an_open_row(self):
        for qid in ("A2", "A3", "Z9"):
            with self.subTest(qid=qid), self.assertRaises(ValueError):
                qb.rewrite_question(BANK, qid, GOOD)

    def test_a_multiline_rewrite_is_refused(self):
        with self.assertRaises(qb.CraftRefused):
            qb.rewrite_question(BANK, "B1", GOOD + "\nWhat else?")


class PromotedRowTests(PromotionCase):
    def test_a_rewritten_promoted_row_keeps_its_marker_verifying(self):
        receipt = promotion.resolve_candidate_promotion(self.request(), vault_root=self.tmp,
                                                        push=False)
        qid = receipt["question_id"]
        bank = (self.tmp / "question-bank.md").read_text(encoding="utf-8")
        [before] = promotion._marker_records(bank)
        kept, _ = qb.keep_question(bank, qid, kept_on="2026-10-15")
        self.assertEqual(len(promotion._marker_records(kept)), 1)
        text, _ = qb.rewrite_question(kept, qid, GOOD, rewritten_on="2026-10-15")
        [after] = promotion._marker_records(text)
        self.assertEqual(after[2], GOOD)
        self.assertEqual(after[0]["candidate_id"], before[0]["candidate_id"])
        self.assertEqual(after[0]["promoted_at"], before[0]["promoted_at"])
        self.assertNotEqual(after[0]["question_revision"], before[0]["question_revision"])


class PlannerKeepsAKeptFailTests(unittest.TestCase):
    def test_drop_craft_fails_keeps_a_kept_fail(self):
        pending = [{"id": "A1", "text": GOOD}, {"id": "A2", "text": T23},
                   {"id": "A3", "text": "update"}]
        kept, skipped = qp.drop_craft_fails(pending, kept_ids={"A2"})
        self.assertEqual([q["id"] for q in kept], ["A1", "A2"])
        self.assertEqual([s["id"] for s in skipped], ["A3"])
        kept, _ = qp.drop_craft_fails([{"id": "A2", "text": T23, "kept": True}])
        self.assertEqual([q["id"] for q in kept], ["A2"])

    def test_kept_ids_are_read_from_the_bank(self):
        text, _ = qb.keep_question(BANK, "A4", kept_on="2026-10-15")
        self.assertEqual(qp.kept_question_ids(text), {"A4"})
        self.assertEqual(qp.kept_question_ids(BANK), set())

    def test_build_queue_queues_a_kept_fail(self):
        bank, _ = qb.keep_question(BANK, "A4", kept_on="2026-10-15")
        questions = core.parse_questions(bank)
        categories = core.parse_categories(bank)
        with mock.patch.object(qp, "load_question_state",
                               return_value=(questions, categories, {"categories": {}})), \
                mock.patch.object(qp, "load_candidates", return_value=[]), \
                mock.patch.object(qp, "kept_question_ids", return_value={"A4"}), \
                mock.patch.object(qp, "resolve_roadmap", return_value={"focuses": []}):
            data = qp.build_queue(limit=7, arc_max=0, planner_state=qp.default_planner_state(),
                                  seed=1)
        self.assertEqual(data["skipped_craft_fail"], [])


class CliTests(unittest.TestCase):
    def setUp(self):
        self.tmp = root_parent_tmp(self, ROOT, prefix="lifehug-v422-cli-")
        self.bank = self.tmp / "question-bank.md"
        self.bank.write_text(BANK + "- [ ] B2: gist\n", encoding="utf-8")

    def _run(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.object(core, "QUESTIONS_FILE", self.bank), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = qb.main(list(argv))
        return code, out.getvalue() + err.getvalue()

    def test_keep_then_lint_fail_excludes_it(self):
        code, out = self._run("keep", "B2", "--reason", "mine")
        self.assertEqual(code, 0)
        self.assertIn("Kept B2", out)
        self.assertRegex(self.bank.read_text(encoding="utf-8"),
                         r"- \[ \] B2: gist\n  <!-- craft: kept \d{4}-\d{2}-\d{2}: mine -->")
        _code, table = self._run("lint", "--verdict", "fail")
        self.assertNotIn("B2", table)
        self.assertIn("A4", table)
        _code, out = self._run("lint", "--json")
        entry = {e["id"]: e for e in json.loads(out)["entries"]}["B2"]
        self.assertEqual((entry["verdict"], entry["kept"]), ("pass", True))
        self.assertIn("too_short", entry["overridden"])
        _code, table = self._run("lint")
        self.assertRegex(table, r"B2\s+open\s+pass\s+kept\s+overridden: too_short")
        self.assertEqual(self._run("keep", "A2")[0], 1)

    def test_rewrite_and_refuse(self):
        code, out = self._run("rewrite", "B2", "--text", "gist again", "--json")
        self.assertEqual(code, 1)
        payload = json.loads(out)
        self.assertTrue(payload["refused"])
        self.assertIn("too_short", payload["reasons"])
        self.assertIn("- [ ] B2: gist\n", self.bank.read_text(encoding="utf-8"))
        code, out = self._run("rewrite", "B2", "--text", GOOD_2, "--json")
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["verdict"], "pass")
        self.assertIn(f"- [ ] B2: {GOOD_2}\n  <!-- craft: rewritten ",
                      self.bank.read_text(encoding="utf-8"))

    def test_front_door_verbs_are_registered_and_classified(self):
        parser = lifehug.build_parser()
        args = parser.parse_args(["question-keep", "A57", "--reason", "mine", "--json"])
        self.assertIs(args.func, lifehug.cmd_question_keep)
        args2 = parser.parse_args(["question-rewrite", "M13", "--text", GOOD])
        self.assertIs(args2.func, lifehug.cmd_question_rewrite)
        self.assertIn("question-keep", lifehug.DIRECT_MUTATION_COMMANDS)
        self.assertIn("question-rewrite", lifehug.DIRECT_MUTATION_COMMANDS)
        with mock.patch.object(lifehug, "run_python", return_value=0) as run:
            lifehug.cmd_question_keep(args)
            lifehug.cmd_question_rewrite(args2)
        self.assertEqual(run.call_args_list[0].args,
                         ("question_bank.py", ["keep", "A57", "--reason", "mine", "--json"]))
        self.assertEqual(run.call_args_list[1].args,
                         ("question_bank.py", ["rewrite", "M13", "--text", GOOD]))


GOOD_2 = "Who was the first neighbor you got to know on Larkspur Lane?"


if __name__ == "__main__":
    unittest.main()
