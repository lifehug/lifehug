"""ADR 0042: the one door into the question bank, and the retired grammar.

Synthetic data only; NEVER references any real vault.
"""
from __future__ import annotations

import ast
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
import gen_followups  # noqa: E402
import lifehug  # noqa: E402
import lifehug_core as core  # noqa: E402
import process_answer  # noqa: E402
import question_bank as qb  # noqa: E402
import question_candidates as qc  # noqa: E402
import question_craft as craft  # noqa: E402
import question_planner as qp  # noqa: E402
import timeline_interaction as ti  # noqa: E402
from tempdirs import root_parent_tmp  # noqa: E402
from test_candidate_promotion import PromotionCase  # noqa: E402

GOOD = "What did the kitchen in your first apartment look like?"
GOOD_2 = "Who was the first neighbor you got to know on Larkspur Lane?"

BANK = (
    "# Questions\n\n"
    "## A: Origins (Childhood)\n\n"
    "- [ ] A1: What is your earliest memory of the house on Larkspur Lane?\n"
    "- [x] A2: Who taught you how to ride a bicycle as a kid? *(2026-07-02)*\n"
    "- [-] A3: update *(retired 2026-10-04: too_short, not_a_question)*\n"
    "\n"
    "## B: Family\n\n"
    "- [ ] B1: What did your grandmother's kitchen smell like on Sundays?\n"
)


class DoorTests(unittest.TestCase):
    def test_a_pass_is_filed_in_its_section(self):
        text, filed, refused = qb.append_questions(BANK, [{"id": "A4", "text": GOOD}])
        self.assertEqual(refused, [])
        self.assertEqual([(r["id"], r["verdict"]) for r in filed], [("A4", "pass")])
        self.assertIn(f"- [ ] A4: {GOOD}\n\n## B: Family", text)

    def test_a_fail_is_refused_with_its_reasons_and_never_written(self):
        text, filed, refused = qb.append_questions(BANK, [{"id": "A4", "text": "gist"}])
        self.assertEqual(text, BANK)
        self.assertEqual(filed, [])
        self.assertEqual(refused[0]["verdict"], "fail")
        self.assertIn("too_short", refused[0]["reasons"])

    def test_a_review_is_written_with_its_provenance_comment(self):
        text, filed, _ = qb.append_questions(BANK, [{
            "id": "B2", "text": "Can you tell me more about that?",
            "provenance": "  <!-- candidate: cand-1 -->"}])
        self.assertEqual(filed[0]["verdict"], "review")
        self.assertIn("- [ ] B2: Can you tell me more about that?\n"
                      "  <!-- candidate: cand-1 -->\n"
                      "  <!-- craft: review: no_concrete_noun -->", text)
        self.assertEqual(qb.craft_review_index(text), {"B2": ["no_concrete_noun"]})

    def test_rows_are_judged_against_the_bank_as_filed_so_far(self):
        _text, filed, _ = qb.append_questions(BANK, [
            {"id": "A4", "text": GOOD}, {"id": "A5", "text": GOOD}])
        self.assertEqual([r["verdict"] for r in filed], ["pass", "review"])
        self.assertEqual(filed[1]["reasons"], ["duplicate_of:A4"])

    def test_an_id_is_allocated_past_retired_rows(self):
        _text, filed, _ = qb.append_questions(BANK, [{"category": "A", "text": GOOD}])
        self.assertEqual(filed[0]["id"], "A4")

    def test_a_missing_section_is_created_only_when_asked(self):
        with self.assertRaises(ValueError):
            qb.append_questions(BANK, [{"id": "C1", "text": GOOD}])
        text, _filed, _ = qb.append_questions(
            BANK, [{"id": "C1", "text": GOOD, "new_section": "\n\n## C: Generated\n"}])
        self.assertTrue(text.endswith(f"## C: Generated\n- [ ] C1: {GOOD}\n"))

    def test_multiline_text_is_refused(self):
        _text, filed, refused = qb.append_questions(BANK, [{"id": "A4", "text": "One?\nTwo?"}])
        self.assertEqual((filed, refused[0]["reasons"]), ([], ["multiline"]))


class OneDoorGuardTests(unittest.TestCase):
    """No module but question_bank.py builds an open bank line."""

    OPEN_LINE = "- [ ] "

    def _string_constants(self, tree: ast.AST):
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                yield node
            elif isinstance(node, ast.JoinedStr):
                for part in node.values:
                    if isinstance(part, ast.Constant) and isinstance(part.value, str):
                        yield part

    def test_only_the_door_builds_a_bank_line(self):
        offenders = []
        for path in sorted(SYSTEM.glob("*.py")):
            if path.name == "question_bank.py":
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"))
            docstrings = {
                id(node.body[0].value) for node in ast.walk(tree)
                if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef,
                                     ast.ClassDef))
                and node.body and isinstance(node.body[0], ast.Expr)
                and isinstance(node.body[0].value, ast.Constant)
            }
            for node in self._string_constants(tree):
                if id(node) in docstrings:
                    continue
                if node.value.lstrip("\n").startswith(self.OPEN_LINE):
                    offenders.append(f"{path.name}:{node.lineno}")
        self.assertEqual(offenders, [])

    def test_the_guard_fires_on_an_offender(self):
        tree = ast.parse('line = f"- [ ] {qid}: {text}"')
        self.assertTrue(any(n.value.startswith(self.OPEN_LINE)
                            for n in self._string_constants(tree)))


class RetireTests(unittest.TestCase):
    def test_an_open_row_is_retired_in_place(self):
        text, receipt = qb.retire_question(BANK, "A1", reason="asked twice",
                                           retired_on="2026-10-04")
        self.assertIn("- [-] A1: What is your earliest memory of the house on Larkspur Lane? "
                      "*(retired 2026-10-04: asked twice)*", text)
        self.assertEqual(receipt["was"], "open")
        self.assertEqual(len(text.splitlines()), len(BANK.splitlines()))

    def test_an_answered_row_keeps_its_answer_date(self):
        text, receipt = qb.retire_question(BANK, "A2", reason="r", retired_on="2026-10-04")
        self.assertIn("*(retired 2026-10-04: r; answered 2026-07-02)*", text)
        self.assertEqual(receipt["was"], "answered")

    def test_the_default_reason_is_the_fail_verdict(self):
        bank = BANK.replace("- [ ] B1: What did your grandmother's kitchen smell like on Sundays?",
                            "- [ ] B1: gist")
        text, _ = qb.retire_question(bank, "B1", retired_on="2026-10-04")
        self.assertIn("- [-] B1: gist *(retired 2026-10-04: too_short, not_a_question)*", text)

    def test_unknown_or_retired_ids_are_refused(self):
        with self.assertRaises(ValueError):
            qb.retire_question(BANK, "Z9")
        with self.assertRaises(ValueError):
            qb.retire_question(BANK, "A3")

    def test_a_reason_cannot_break_the_grammar(self):
        text, _ = qb.retire_question(BANK, "A1", reason="bad *(nested)* note",
                                     retired_on="2026-10-04")
        [row] = [r for r in qb.bank_rows(text) if r["id"] == "A1"]
        self.assertEqual(row["status"], "retired")


class RetiredReadersTests(unittest.TestCase):
    """`[-]` is neither open nor answered, for every reader."""

    def test_parse_questions_never_sees_it(self):
        ids = [q["id"] for q in core.parse_questions(BANK)]
        self.assertEqual(ids, ["A1", "A2", "B1"])

    def test_coverage_never_counts_it(self):
        coverage = core.compute_coverage(core.parse_questions(BANK), core.parse_categories(BANK))
        self.assertEqual(coverage["categories"]["A"]["total"], 2)

    def test_every_allocator_counts_it(self):
        self.assertEqual(qc.next_question_id(BANK, "A"), "A4")
        self.assertEqual(promotion._next_question_id(BANK, "A"), "A4")
        self.assertEqual(gen_followups.get_next_id_for_category(BANK, "A"), "A4")
        bank = BANK + "- [-] B1a: gist *(retired 2026-10-04: x)*\n"
        self.assertEqual(process_answer.next_followup_id(bank, "B1"), "B1b")

    def test_the_planner_never_sees_it(self):
        pending = qp.enriched_pending_questions(core.parse_questions(BANK),
                                                core.parse_categories(BANK), {"categories": {}}, [])
        self.assertNotIn("A3", [q["id"] for q in pending])

    def test_the_timeline_probe_index_never_offers_it(self):
        bank = ("## T: Timeline\n\n- [-] T1: When was wedding? *(retired 2026-10-04: x)*\n"
                "  <!-- timeline_probe: tl:wedding; anchor: event:wedding; leverage: 4; "
                "minted: 2026-09-20T00:00:00Z -->\n")
        self.assertEqual(ti.timeline_probe_index(bank), {})
        # …but its work item is never minted again: it reads as dismissed.
        states = qp.work_item_states_from_bank(bank)
        self.assertEqual(list(states.values()), ["dismissed"])

    def test_the_lint_lists_it_as_retired(self):
        rows = {r["id"]: r for r in qb.lint_bank(BANK)}
        self.assertEqual(rows["A3"]["status"], "retired")
        self.assertEqual(rows["A3"]["verdict"], "fail")
        self.assertEqual(rows["A1"]["verdict"], "pass")
        self.assertEqual(rows["A2"]["status"], "answered")


class WriterTests(unittest.TestCase):
    def setUp(self):
        self.tmp = root_parent_tmp(self, ROOT, prefix="lifehug-question-bank-")
        self.bank = self.tmp / "question-bank.md"
        self.bank.write_text(BANK, encoding="utf-8")

    def test_followups_refuse_a_fail_and_do_not_spend_its_id(self):
        with mock.patch.object(process_answer, "QUESTIONS_FILE", self.bank), \
                contextlib.redirect_stderr(io.StringIO()) as err:
            added = process_answer.append_followups("A1", ["update", GOOD, "gist"])
        self.assertEqual(added, [("A1a", GOOD)])
        self.assertIn("'update'", err.getvalue())
        text = self.bank.read_text(encoding="utf-8")
        self.assertNotIn("update\n", text.split("## B")[0].replace("A3: update", ""))
        self.assertIn(f"- [ ] A1a: {GOOD}", text)

    def test_followups_write_nothing_when_every_one_fails(self):
        with mock.patch.object(process_answer, "QUESTIONS_FILE", self.bank), \
                contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(process_answer.append_followups("A1", ["update"]), [])
        self.assertEqual(self.bank.read_text(encoding="utf-8"), BANK)

    def test_insert_question_refuses_a_fail(self):
        with self.assertRaises(ValueError):
            qc.insert_question(BANK, "A", "A4", "When was wedding?", {"id": "c"},
                               "2026-10-04T00:00:00Z")
        text = qc.insert_question(BANK, "A", "A4", GOOD, {"id": "c"}, "2026-10-04T00:00:00Z")
        self.assertIn(f"- [ ] A4: {GOOD}\n  <!-- candidate: c;", text)

    def test_gen_followups_refuses_a_fail(self):
        payload = self.tmp / "q.json"
        payload.write_text(json.dumps({"questions": [
            {"category": "B", "text": "gist"}, {"category": "B", "text": GOOD_2}]}))
        rotation = self.tmp / "rotation.json"
        rotation.write_text(json.dumps({"current_pass": 2}))
        args = mock.Mock(file=str(payload), model="m", dry_run=False)
        with mock.patch.object(gen_followups, "QUESTIONS_FILE", self.bank), \
                mock.patch.object(gen_followups, "ROTATION_FILE", rotation), \
                mock.patch.object(gen_followups, "rebuild_coverage"), \
                contextlib.redirect_stderr(io.StringIO()), contextlib.redirect_stdout(io.StringIO()):
            gen_followups.cmd_append(args)
        text = self.bank.read_text(encoding="utf-8")
        self.assertIn(f"- [ ] B2: {GOOD_2}", text)
        self.assertNotIn("gist", text)


class KeystoneTests(unittest.TestCase):
    def _keystone(self, text, **extra):
        return {"anchor": "event:x", "label": extra.pop("label", ""), "leverage": 4,
                "probe": {"text": text}, **extra}

    def test_a_good_probe_is_kept_verbatim(self):
        row = ti.mint_keystone_question(self._keystone("When did the harbor fire happen?"),
                                        next_question_id="T1", minted_at="2026-10-04T00:00:00Z")
        self.assertEqual(row["text"], "When did the harbor fire happen?")

    def test_a_label_template_is_said_in_the_domains_words(self):
        cases = {
            ("When was wedding?", "wedding"): "When did you get married?",
            ("When was move to Springfield?", "move to Springfield"):
                "When did you move to Springfield?",
            ("When was high school graduation?", "high school graduation"):
                "When did you graduate from high school?",
        }
        for (probe, label), expected in cases.items():
            with self.subTest(probe=probe):
                row = ti.mint_keystone_question(self._keystone(probe, label=label),
                                                next_question_id="T1")
                self.assertEqual(row["text"], expected)

    def test_a_landmark_domain_uses_the_landmark_table(self):
        row = ti.mint_keystone_question(
            self._keystone("When was Brightwater Labs?", label="Brightwater Labs", domain="work"),
            next_question_id="T1")
        self.assertEqual(row["text"], "When did you start at Brightwater Labs?")

    def test_a_label_that_cannot_be_phrased_is_refused_never_templated(self):
        self.assertIsNone(ti.mint_keystone_question(
            self._keystone("When was MIT?", label="MIT"), next_question_id="T1"))

    def test_insert_refuses_a_fail_and_files_a_pass(self):
        bad = {"id": "T1", "text": "When was wedding?",
               "line": "- [ ] T1: When was wedding?\n  <!-- timeline_probe: tl:w; anchor: e:w; "
                       "leverage: 4; minted: 2026-10-04T00:00:00Z -->"}
        self.assertEqual(ti.insert_keystone_question(BANK, bad), BANK)
        good = {**bad, "text": "When did you get married?",
                "line": bad["line"].replace("When was wedding?", "When did you get married?")}
        text = ti.insert_keystone_question(BANK, good)
        self.assertIn("## Timeline\n\n## T: Timeline", text)
        self.assertEqual(list(ti.timeline_probe_index(text)), ["T1"])


class PromotionDoorTests(PromotionCase):
    def test_a_failing_candidate_is_refused_by_the_door(self):
        self.candidate["text"] = "update"
        self._write_store([self.candidate])
        with self.assertRaises(promotion.CandidatePromotionError) as caught:
            promotion.resolve_candidate_promotion(self.request(), vault_root=self.tmp, push=False)
        self.assertIn("ADR 0042", str(caught.exception))

    def test_a_retired_promoted_row_keeps_its_marker_readable(self):
        receipt = promotion.resolve_candidate_promotion(self.request(), vault_root=self.tmp,
                                                        push=False)
        bank = (self.tmp / "question-bank.md").read_text(encoding="utf-8")
        retired, _ = qb.retire_question(bank, receipt["question_id"], reason="owner",
                                        retired_on="2026-10-04")
        [record] = promotion._marker_records(retired)
        self.assertEqual(record[0]["question_id"], receipt["question_id"])


class AutoPromoteTests(unittest.TestCase):
    def setUp(self):
        self.tmp = root_parent_tmp(self, ROOT, prefix="lifehug-question-bank-auto-")
        self.bank = self.tmp / "question-bank.md"
        self.bank.write_text(BANK, encoding="utf-8")
        self.store = self.tmp / "question_candidates.json"
        self.store.write_text(json.dumps({"version": 1, "candidates": [
            {"id": "c-fail", "status": "candidate", "priority": 0.99, "text": "update",
             "target_category": "A", "source_path": "answers/A1.md",
             "created_at": "2026-10-01T00:00:00Z"},
            {"id": "c-review", "status": "candidate", "priority": 0.99,
             "text": "Can you tell me more about that?", "target_category": "A",
             "source_path": "answers/A1.md", "created_at": "2026-10-01T00:00:00Z"},
        ]}))

    def test_a_fail_never_promotes_and_a_review_parks(self):
        with mock.patch.object(qc, "QUESTIONS_FILE", self.bank), \
                mock.patch.object(qc, "load_store",
                                  side_effect=lambda *_a, **_k: json.loads(self.store.read_text())), \
                mock.patch.object(qc, "_load_quality_profile_safely", return_value=None):
            result = qc.auto_promote_candidates(dry_run=True)
        self.assertEqual(result["promoted"], [])
        skipped = dict(result["skipped"])
        self.assertTrue(skipped["c-fail"].startswith("craft_fail: too_short"))
        review = {r[0]: r[2] for r in result["needs_review"]}
        self.assertEqual(review["c-review"], "craft_review: no_concrete_noun")


class PlannerTests(unittest.TestCase):
    def test_a_fail_is_skipped_and_reported(self):
        kept, skipped = qp.drop_craft_fails([
            {"id": "A1", "text": GOOD}, {"id": "A2", "text": "update"},
            {"id": "A3", "text": "Can you tell me more about that?"}])
        self.assertEqual([q["id"] for q in kept], ["A1", "A3"])
        self.assertEqual(skipped, [{"id": "A2", "reasons": ["too_short", "not_a_question"]}])

    def test_build_queue_reports_skipped_craft_fail(self):
        bank = BANK + "- [ ] B2: gist\n"
        questions = core.parse_questions(bank)
        categories = core.parse_categories(bank)
        with mock.patch.object(qp, "load_question_state",
                               return_value=(questions, categories, {"categories": {}})), \
                mock.patch.object(qp, "load_candidates", return_value=[]), \
                mock.patch.object(qp, "resolve_roadmap", return_value={"focuses": []}):
            data = qp.build_queue(limit=7, arc_max=0, planner_state=qp.default_planner_state(),
                                  seed=1)
        self.assertEqual(data["skipped_craft_fail"],
                         [{"id": "B2", "reasons": ["too_short", "not_a_question"]}])
        self.assertNotIn("B2", [item.get("question_id") for item in data["queue"]])


class CliTests(unittest.TestCase):
    def setUp(self):
        self.tmp = root_parent_tmp(self, ROOT, prefix="lifehug-question-bank-cli-")
        self.bank = self.tmp / "question-bank.md"
        self.bank.write_text(BANK + "- [ ] B2: gist\n", encoding="utf-8")

    def _run(self, *argv):
        out = io.StringIO()
        with mock.patch.object(core, "QUESTIONS_FILE", self.bank), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            code = qb.main(list(argv))
        return code, out.getvalue()

    def test_lint_is_read_only_and_lists_every_entry(self):
        before = self.bank.read_text(encoding="utf-8")
        code, out = self._run("lint", "--json")
        self.assertEqual(code, 0)
        entries = {e["id"]: e for e in json.loads(out)["entries"]}
        self.assertEqual(set(entries), {"A1", "A2", "A3", "B1", "B2"})
        self.assertEqual(entries["B2"]["verdict"], "fail")
        self.assertEqual(self.bank.read_text(encoding="utf-8"), before)
        code, table = self._run("lint", "--verdict", "fail")
        self.assertIn("B2", table)
        self.assertNotIn("A1 ", table)

    def test_retire_rewrites_one_line(self):
        code, out = self._run("retire", "B2", "--reason", "one word")
        self.assertEqual(code, 0)
        self.assertIn("Retired B2", out)
        self.assertRegex(self.bank.read_text(encoding="utf-8"),
                         r"- \[-\] B2: gist \*\(retired \d{4}-\d{2}-\d{2}: one word\)\*")
        self.assertEqual(self._run("retire", "B2")[0], 1)

    def test_both_verbs_are_registered_and_classified(self):
        parser = lifehug.build_parser()
        self.assertIs(parser.parse_args(["question-bank-lint"]).func,
                      lifehug.cmd_question_bank_lint)
        self.assertIs(parser.parse_args(["question-retire", "A1"]).func,
                      lifehug.cmd_question_retire)
        self.assertIn("question-bank-lint", lifehug.READ_ONLY_COMMANDS)
        self.assertIn("question-retire", lifehug.DIRECT_MUTATION_COMMANDS)


class VerdictConstantsTests(unittest.TestCase):
    def test_the_door_reads_the_one_evaluation(self):
        self.assertIs(qb.evaluate, craft.evaluate)


if __name__ == "__main__":
    unittest.main()
