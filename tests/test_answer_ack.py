import importlib.util
import json
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SYSTEM = ROOT / "system"
sys.path.insert(0, str(SYSTEM))


def load_answer_ack():
    spec = importlib.util.spec_from_file_location("answer_ack", SYSTEM / "answer_ack.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def load_process_answer():
    spec = importlib.util.spec_from_file_location("process_answer", SYSTEM / "process_answer.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


PAYLOAD = {
    "question_id": "A3",
    "question_text": "What's a place from your childhood you still think about?",
    "question_category": "A",
    "answer_text": "My grandmother's kitchen in Oaxaca, the smell of cinnamon and the "
    "tile floor that was always cool under my bare feet in summer.",
    "followup_pending": True,
}


class BuildPromptTests(unittest.TestCase):
    def setUp(self):
        self.mod = load_answer_ack()

    def test_embeds_question_text_verbatim(self):
        prompt = self.mod.build_prompt(PAYLOAD)
        self.assertIn(PAYLOAD["question_text"], prompt)

    def test_embeds_answer_text_verbatim(self):
        prompt = self.mod.build_prompt(PAYLOAD)
        self.assertIn(PAYLOAD["answer_text"], prompt)

    def test_tone_contract_lines_present(self):
        prompt = self.mod.build_prompt(PAYLOAD)
        self.assertIn("2-4 sentences", prompt)
        self.assertIn("No advice", prompt)
        self.assertIn("No analysis", prompt)
        self.assertIn("No questions back", prompt)
        self.assertIn("warm but not sycophantic", prompt)


class FollowupBranchTests(unittest.TestCase):
    def setUp(self):
        self.mod = load_answer_ack()

    def test_followup_pending_true_mentions_optional_followup(self):
        prompt = self.mod.build_prompt({**PAYLOAD, "followup_pending": True})
        self.assertIn("while you're here", prompt)
        self.assertIn("totally optional", prompt)

    def test_followup_pending_false_omits_followup_language(self):
        prompt = self.mod.build_prompt({**PAYLOAD, "followup_pending": False})
        self.assertNotIn("while you're here", prompt)
        self.assertNotIn("totally optional", prompt)


class CliTests(unittest.TestCase):
    def _run(self, stdin_text):
        return subprocess.run(
            [sys.executable, str(SYSTEM / "answer_ack.py")],
            input=stdin_text,
            capture_output=True,
            text=True,
        )

    def test_valid_payload_prints_only_the_prompt(self):
        mod = load_answer_ack()
        result = self._run(json.dumps(PAYLOAD))
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stderr, "")
        self.assertEqual(result.stdout, mod.build_prompt(PAYLOAD) + "\n")

    def test_empty_stdin_exits_1_with_one_line_stderr(self):
        result = self._run("")
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout, "")
        self.assertEqual(len(result.stderr.strip().splitlines()), 1)

    def test_invalid_json_exits_1(self):
        result = self._run("{not json")
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout, "")

    def test_missing_field_exits_1(self):
        payload = dict(PAYLOAD)
        del payload["answer_text"]
        result = self._run(json.dumps(payload))
        self.assertEqual(result.returncode, 1)

    def test_mistyped_field_exits_1(self):
        payload = {**PAYLOAD, "followup_pending": "true"}
        result = self._run(json.dumps(payload))
        self.assertEqual(result.returncode, 1)


class FollowupFramingConstantsTests(unittest.TestCase):
    def test_constants_have_expected_values(self):
        spec = importlib.util.spec_from_file_location("process_answer", SYSTEM / "process_answer.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        self.assertEqual(mod.FOLLOWUP_HEADER, "📖 Lifehug — since you're on a roll")
        self.assertEqual(
            mod.FOLLOWUP_FOOTER,
            "(Totally optional — tomorrow's question comes either way)",
        )

    def test_maybe_send_followup_question_uses_constants(self):
        script = (SYSTEM / "process_answer.py").read_text(encoding="utf-8")
        self.assertNotIn('"📖 Lifehug — since you\'re on a roll\\n\\n"', script)
        self.assertIn("FOLLOWUP_HEADER", script)
        self.assertIn("FOLLOWUP_FOOTER", script)


class LocalAckSendTests(unittest.TestCase):
    def setUp(self):
        self.mod = load_process_answer()

    def test_ack_skips_model_call_without_telegram_target(self):
        question = {"id": "A3", "text": PAYLOAD["question_text"], "category": "A"}
        with (
            mock.patch.object(self.mod, "resolve_telegram_target", return_value=("", "")),
            mock.patch.object(self.mod, "generate_answer_ack_text") as generate,
        ):
            sent = self.mod.maybe_send_answer_ack(
                question,
                {"A": {"name": "Origins"}},
                PAYLOAD["answer_text"],
                followup_pending=False,
            )

        self.assertFalse(sent)
        generate.assert_not_called()

    def test_ack_generates_and_sends_before_followup_surface(self):
        question = {"id": "A3", "text": PAYLOAD["question_text"], "category": "A"}
        with (
            mock.patch.object(self.mod, "resolve_telegram_target", return_value=("token", "chat")),
            mock.patch.object(self.mod, "load_config", return_value={"answer_ack_model": "ack-model"}),
            mock.patch.object(
                self.mod,
                "generate_answer_ack_text",
                return_value="Warm acknowledgment.",
            ) as generate,
            mock.patch.object(self.mod, "send_telegram", return_value=True) as send,
        ):
            sent = self.mod.maybe_send_answer_ack(
                question,
                {"A": {"name": "Origins"}},
                PAYLOAD["answer_text"],
                followup_pending=True,
            )

        self.assertTrue(sent)
        payload, model = generate.call_args.args
        self.assertEqual(model, "ack-model")
        self.assertEqual(payload["question_id"], "A3")
        self.assertEqual(payload["answer_text"], PAYLOAD["answer_text"])
        self.assertTrue(payload["followup_pending"])
        send.assert_called_once_with("Warm acknowledgment.")

    def test_process_answer_calls_ack_before_adaptive_followup(self):
        script = (SYSTEM / "process_answer.py").read_text(encoding="utf-8")
        ack = script.index("maybe_send_answer_ack(\n            question")
        followup = script.index("maybe_send_followup_question(question_id, followup_plan=followup_plan)")
        self.assertLess(ack, followup)


if __name__ == "__main__":
    unittest.main()
