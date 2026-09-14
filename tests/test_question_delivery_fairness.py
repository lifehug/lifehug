"""Delivery history changes selection without inventing answers (issue #331)."""

import copy
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import unittest
from itertools import pairwise
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SYSTEM = ROOT / "system"
sys.path.insert(0, str(SYSTEM))
sys.path.insert(0, str(ROOT / "tests"))

from tempdirs import root_parent_tmp

spec = importlib.util.spec_from_file_location("ask_fairness", SYSTEM / "ask.py")
ask = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ask)


def question(qid, text="Tell me about that place.", *, answered=False):
    return {"id": qid, "category": qid[0], "text": text, "answered": answered}


class DeliveryFairnessTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(mock.patch.object(ask, "load_config", return_value={}))
        self.queue = self.enterContext(mock.patch.object(ask, "read_json", return_value={}))
        self.categories = {"A": {"group": "main"}, "B": {"group": "main"}}

    def test_reengagement_uses_counts_before_length(self):
        questions = [question("A7a", "update"), question("B1", "What felt like home?")]
        rotation = {"delivery_counts": {"A7a": 8}}
        self.assertEqual(
            ask.pick_reengagement_question(questions, self.categories, rotation)["id"], "B1"
        )

    def test_reengagement_still_prefers_light_non_focus_questions(self):
        questions = [
            question("A1", "What was your deepest fear?"),
            question("B1", "Which place felt most like home?"),
            question("K1", "Who helped?"),
        ]
        categories = {**self.categories, "K": {"group": "focus"}}
        rotation = {"delivery_counts": {"B1": 8}, "last_question_id": "B1"}
        self.assertEqual(ask.pick_reengagement_question(questions, categories, rotation)["id"], "B1")

    def test_existing_two_argument_reengagement_call_still_works(self):
        questions = [question("A1", "Tell me about that place."), question("B1", "Who helped?")]
        self.assertEqual(ask.pick_reengagement_question(questions, self.categories)["id"], "B1")

    def test_fallback_fairness_crosses_category_coverage(self):
        questions = [
            question("A7a", "update"),
            question("B1", answered=True),
            question("B2", answered=True),
            question("B3", "Which place felt like home?"),
        ]
        rotation = {"delivery_counts": {"A7a": 8}}
        self.assertEqual(ask.pick_next_question(questions, self.categories, rotation)["id"], "B3")

    def test_equal_counts_avoid_last_question_in_both_selectors(self):
        questions = [question("A1", "Who helped?"), question("A2")]
        rotation = {"delivery_counts": {"A1": 2, "A2": 2}, "last_question_id": "A1"}
        for picker in (ask.pick_next_question, ask.pick_reengagement_question):
            with self.subTest(picker=picker.__name__):
                self.assertEqual(picker(questions, self.categories, rotation)["id"], "A2")

    def test_uneven_history_does_not_create_a_consecutive_repeat_streak(self):
        questions = [question("A1", "Who helped?"), question("A2")]
        rotation = {"delivery_counts": {"A1": 1, "A2": 100}, "last_question_id": "A1"}
        for picker in (ask.pick_next_question, ask.pick_reengagement_question):
            with self.subTest(picker=picker.__name__):
                self.assertEqual(picker(questions, self.categories, rotation)["id"], "A2")

    def test_missing_history_keeps_existing_deterministic_ties(self):
        questions = [question("A2"), question("A1")]
        for picker in (ask.pick_next_question, ask.pick_reengagement_question):
            with self.subTest(picker=picker.__name__):
                self.assertEqual(picker(questions, self.categories, {})["id"], "A2")

    def test_count_defaults_and_legacy_integer_strings(self):
        questions = [question("A1"), question("A2")]
        rotations = [
            {}, {"delivery_counts": None}, {"delivery_counts": []},
            {"delivery_counts": "bad"},
            *({"delivery_counts": {"A1": value, "A2": 1}}
              for value in (None, "bad", [], {}, True, -5, "-5", 0.5)),
        ]
        for picker in (ask.pick_next_question, ask.pick_reengagement_question):
            for rotation in rotations:
                with self.subTest(rotation=rotation, picker=picker.__name__):
                    self.assertEqual(picker(questions, self.categories, rotation)["id"], "A1")
            self.assertEqual(
                picker(questions, self.categories, {"delivery_counts": {"A1": "8"}})["id"], "A2"
            )

    def test_healthy_queue_keeps_priority_despite_previous_deliveries(self):
        questions = [question("A1"), question("B1")]
        self.queue.return_value = {
            "queue": [{"question_id": "A1", "status": "queued"}],
            "expires_at": "2099-01-01T00:00:00Z",
        }
        rotation = {"delivery_counts": {"A1": 8}, "last_question_id": "A1"}
        self.assertEqual(ask.pick_next_question(questions, self.categories, rotation)["id"], "A1")

    def test_expired_queue_cannot_override_fairness(self):
        questions = [question("A7a", "update"), question("A8")]
        self.queue.return_value = {
            "queue": [{"question_id": "A7a", "status": "queued"}],
            "expires_at": "2000-01-01T00:00:00Z",
        }
        self.assertEqual(
            ask.pick_next_question(questions, self.categories, {"delivery_counts": {"A7a": 8}})["id"],
            "A8",
        )

    def test_silence_still_overrides_a_healthy_queue_using_delivery_history(self):
        questions = [question("A7a", "update"), question("A8")]
        self.queue.return_value = {
            "queue": [{"question_id": "A7a", "status": "queued"}],
            "expires_at": "2099-01-01T00:00:00Z",
        }
        rotation = {
            "last_answered_at": "2000-01-01T00:00:00Z", "delivery_counts": {"A7a": 8},
        }
        self.assertEqual(ask.pick_next_question(questions, self.categories, rotation)["id"], "A8")

    def test_one_remaining_short_or_declarative_question_is_never_exhausted_by_delivery(self):
        for text in ("Who helped?", "Tell me more."):
            for picker in (ask.pick_next_question, ask.pick_reengagement_question):
                with self.subTest(text=text, picker=picker.__name__):
                    questions = [question("A1", answered=True), question("A2", text)]
                    rotation = {"delivery_counts": {"A2": 100}, "last_question_id": "A2"}
                    self.assertEqual(picker(questions, self.categories, rotation)["id"], "A2")

    def test_previously_delivered_question_returns_after_an_alternative(self):
        questions = [question("A7a", "update"), question("A8")]
        rotation = {"delivery_counts": {"A7a": 8, "A8": 1}, "last_question_id": "A8"}
        for picker in (ask.pick_next_question, ask.pick_reengagement_question):
            with self.subTest(picker=picker.__name__):
                self.assertEqual(picker(questions, self.categories, rotation)["id"], "A7a")

    def test_empty_and_all_answered_banks_still_complete(self):
        for questions in ([], [question("A1", answered=True)]):
            for picker in (ask.pick_next_question, ask.pick_reengagement_question):
                with self.subTest(questions=questions, picker=picker.__name__):
                    self.assertIsNone(picker(questions, self.categories, {}))

    def test_coverage_and_focus_interleaving_survive_within_equal_count_cohort(self):
        questions = [question("A1", answered=True), question("A2"), question("B1"), question("K1")]
        categories = {**self.categories, "K": {"group": "focus"}}
        self.assertEqual(ask.pick_next_question(questions, categories, {})["id"], "B1")
        self.assertEqual(
            ask.pick_next_question(questions, categories, {"questions_asked": 4})["id"], "K1"
        )

    def test_selection_never_mutates_inputs(self):
        questions = [question("A1"), question("A2")]
        rotation = {"delivery_counts": {"A1": 2}, "last_question_id": "A1"}
        before = copy.deepcopy((questions, rotation))
        for picker in (ask.pick_next_question, ask.pick_reengagement_question):
            picker(questions, self.categories, rotation)
        self.assertEqual((questions, rotation), before)


class ConfirmedDeliverySequenceTests(unittest.TestCase):
    def setUp(self):
        self.vault = root_parent_tmp(self, ROOT, prefix="question-fairness-")
        self.system = self.vault / "system"
        self.system.mkdir()
        self.state = self.vault / "state"
        self.state.mkdir()
        for name in ("ask.py", "lifehug_core.py", "vault_paths.py", "vault_contract.json", "update.py"):
            shutil.copyfile(SYSTEM / name, self.system / name)
        self.bank = self.system / "question-bank.md"
        self.bank.write_text(
            "## A: Origins\n"
            "- [x] A7: An answered synthetic question?\n"
            "- [ ] A7a: update\n"
            "- [ ] A8: Which place felt like home?\n"
            "## B: Becoming\n"
            "- [ ] B1: Who helped you feel welcome there?\n", encoding="utf-8",
        )
        self.rotation_path = self.system / "rotation.json"
        self.rotation_path.write_text(json.dumps({
            "version": 1, "current_pass": 1, "questions_asked": 8,
            "delivery_counts": {"A7a": 8}, "last_question_id": "A7a",
        }), encoding="utf-8")
        self.env = {
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            "HOME": str(self.vault), "PYTHONDONTWRITEBYTECODE": "1",
        }
        subprocess.run(
            [sys.executable, str(self.system / "update.py"), "--migrate-vault", "--vault-root", str(self.vault)],
            cwd=self.vault, env=self.env, check=True, capture_output=True, text=True, timeout=20,
        )

    def cli(self, *args):
        result = subprocess.run(
            [sys.executable, str(self.system / "ask.py"), *args],
            cwd=self.vault, env=self.env, check=False, capture_output=True, text=True, timeout=20,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout

    def pick(self):
        before = self.rotation_path.read_bytes()
        output = self.cli("--dry-run")
        self.assertEqual(self.rotation_path.read_bytes(), before)
        return re.search(r"\[([A-Z]\d+[a-z]*)\]", output).group(1)

    def test_repeated_confirmed_picks_spread_across_unanswered_alternatives(self):
        for silent in (False, True):
            with self.subTest(silent=silent):
                rotation = json.loads(self.rotation_path.read_text(encoding="utf-8"))
                rotation.update(
                    delivery_counts={"A7a": 8}, questions_asked=8, last_question_id="A7a",
                    last_answered_at="2000-01-01T00:00:00Z" if silent else None,
                )
                self.rotation_path.write_text(json.dumps(rotation), encoding="utf-8")
                (self.state / "question_queue.json").write_text(json.dumps({
                    "queue": [{"question_id": "A7a", "status": "queued"}],
                    "expires_at": "2000-01-01T00:00:00Z",
                }), encoding="utf-8")
                bank_before = self.bank.read_bytes()
                picks = []
                for _ in range(8):
                    qid = self.pick()
                    self.assertEqual(self.pick(), qid)  # unconfirmed attempts are not deliveries
                    picks.append(qid)
                    self.cli("--confirm-sent", qid)
                    self.assertEqual(self.bank.read_bytes(), bank_before)
                self.assertEqual(picks.count("A8"), 4)
                self.assertEqual(picks.count("B1"), 4)
                self.assertTrue(all(left != right for left, right in pairwise(picks)))
                counts = json.loads(self.rotation_path.read_text(encoding="utf-8"))["delivery_counts"]
                self.assertEqual(counts, {"A7a": 8, "A8": 4, "B1": 4})

    def test_healthy_queue_advances_only_after_confirmation(self):
        (self.state / "question_queue.json").write_text(json.dumps({
            "queue": [{"question_id": qid, "status": "queued"} for qid in ("A7a", "B1")],
            "expires_at": "2099-01-01T00:00:00Z",
        }), encoding="utf-8")
        self.assertEqual(self.pick(), "A7a")
        self.assertEqual(self.pick(), "A7a")
        self.cli("--confirm-sent", "A7a")
        self.assertEqual(self.pick(), "B1")

    def test_single_valid_question_stays_unanswered_across_confirmations_from_no_history(self):
        self.bank.write_text(
            "## A: Origins\n- [x] A1: An answered question?\n- [ ] A2: Who helped?\n",
            encoding="utf-8",
        )
        rotation = json.loads(self.rotation_path.read_text(encoding="utf-8"))
        rotation.pop("delivery_counts", None)
        rotation["last_question_id"] = None
        rotation["questions_asked"] = 0
        self.rotation_path.write_text(json.dumps(rotation), encoding="utf-8")
        bank_before = self.bank.read_bytes()
        for expected_count in range(1, 4):
            self.assertEqual(self.pick(), "A2")
            self.cli("--confirm-sent", "A2")
            rotation = json.loads(self.rotation_path.read_text(encoding="utf-8"))
            self.assertEqual(rotation["delivery_counts"], {"A2": expected_count})
            self.assertFalse(rotation.get("awaiting_pass_transition"))
            self.assertEqual(self.bank.read_bytes(), bank_before)

    def test_all_answered_bank_keeps_dry_run_and_pass_completion_contract(self):
        self.bank.write_text("## A: Origins\n- [x] A1: An answered question?\n", encoding="utf-8")
        before = self.rotation_path.read_bytes()
        self.assertIn("Pass 1 complete. Would generate Pass 2 (depth) questions.", self.cli("--dry-run"))
        self.assertEqual(self.rotation_path.read_bytes(), before)
        self.assertTrue(self.cli("--mark-pass-complete").startswith("PASS_COMPLETE:1:"))
        rotation = json.loads(self.rotation_path.read_text(encoding="utf-8"))
        self.assertTrue(rotation["awaiting_pass_transition"])
        self.assertEqual(rotation["target_pass"], 2)


if __name__ == "__main__":
    unittest.main()
