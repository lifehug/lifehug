import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SYSTEM = ROOT / "system"
sys.path.insert(0, str(SYSTEM))
sys.path.insert(0, str(ROOT / "tests"))

from tempdirs import root_parent_tmp  # noqa: E402


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


class AnswerAcknowledgmentDeliveryTests(unittest.TestCase):
    """Ported guarantees from the retired inline #107 LocalAckSendTests.

    #107's ``maybe_send_answer_ack``/``generate_answer_ack_text``/
    ``build_answer_ack_payload`` (in ``process_answer.py``) are superseded by
    #67's ``answer_ack_delivery.acknowledge_answer`` — an independently
    converged, more complete implementation (durable idempotent state,
    confirmed/ambiguous retry, dual-commit delivery boundary). See the
    superseding commit message for the full rationale and exactly which
    #107 assertions were purely implementation-specific and dropped versus
    ported here. This class exercises the surviving implementation directly
    through plain imports (matching how ``process_answer.py``'s
    ``from answer_ack_delivery import acknowledge_answer`` resolves), not the
    ``load_process_answer()``/``load_answer_ack()`` fresh-module helpers used
    above — those helpers create module instances outside ``sys.modules``,
    which would make ``mock.patch.object`` here invisible to the real
    call sites under test.
    """

    def setUp(self):
        import answer_ack_delivery
        import conversation_delivery
        import process_answer

        self.delivery = answer_ack_delivery
        self.process_answer = process_answer
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.state_path = Path(tmp.name) / "answer_acknowledgments.json"
        # v153: run_post_answer_delivery now runs a conversation turn first
        # (which falls back to the ack pair asserted below). Point the engine
        # at a synthetic vault — ROOT.parent, because vault_paths refuses to
        # traverse macOS's /var symlink — so these tests never write session
        # documents or a delivery ledger into the real vault.
        vault = root_parent_tmp(self, ROOT, prefix="lifehug-v153-ack-") / "vault"
        vault.mkdir()
        for patch in (
            mock.patch.object(conversation_delivery, "VAULT_ROOT", vault),
            mock.patch.object(
                conversation_delivery,
                "DELIVERY_STATE_FILE",
                vault / "state" / "conversation_deliveries.json",
            ),
            mock.patch.object(conversation_delivery, "record_learning_failure"),
        ):
            patch.start()
            self.addCleanup(patch.stop)

    def test_ack_is_best_effort_and_never_confirmed_without_a_telegram_target(self):
        """Ported from test_ack_skips_model_call_without_telegram_target.

        #107 checked ``resolve_telegram_target()`` before generating, so a
        missing telegram target skipped the model call entirely. #67 checks
        AI-provider readiness first instead (the more central real-world
        gate — keyless/agent-task mode — and, since #61, generation may
        route through a free local provider, so the cost concern behind
        #107's ordering is much smaller). The model CAN now be called before
        the missing-telegram-target is discovered; that is an intentional,
        disclosed change, not a silent regression (see the superseding
        commit message). The guarantee that matters and does survive: the
        answer is never blocked and the outcome is honestly reported as not
        delivered — exercised here through the same ``telegram_send`` hook
        ``lifehug_core.send_telegram_result`` itself uses to report a
        missing target, so the assertion reflects the real "no telegram
        configured" outcome rather than a synthetic stand-in.
        """
        missing_target = self.delivery.TelegramSendResult(
            "not_attempted", "telegram_credentials_missing", 0, 1
        )
        outcome = self.delivery.acknowledge_answer(
            source_id="answer:A3",
            question_id="A3",
            question_text=PAYLOAD["question_text"],
            question_category="A",
            answer_text=PAYLOAD["answer_text"],
            followup_pending=False,
            state_path=self.state_path,
            status_resolver=lambda *_a, **_k: mock.Mock(ready=True, provider="local-openai"),
            ai_call=lambda _prompt, _model: "Warm acknowledgment.",
            telegram_send=lambda _message: missing_target,
        )

        self.assertNotEqual(outcome.status, self.delivery.STATUS_CONFIRMED)
        self.assertEqual(outcome.reason, "telegram_credentials_missing")

    def test_ack_generates_and_sends_using_the_canonical_payload(self):
        """Ported from test_ack_generates_and_sends_before_followup_surface.

        Same guarantee (correct payload fields reach generation; a
        successful send is reported as delivered), rewritten against
        ``acknowledge_answer``'s dependency-injected hooks instead of
        ``process_answer``'s now-retired module-level mocks.
        """
        seen: dict = {}

        def ai_call(prompt, model):
            seen["prompt"] = prompt
            seen["model"] = model
            return "Warm acknowledgment."

        with mock.patch.object(
            self.delivery, "load_config", return_value={"answer_ack_model": "ack-model"}
        ):
            outcome = self.delivery.acknowledge_answer(
                source_id="answer:A3",
                question_id="A3",
                question_text=PAYLOAD["question_text"],
                question_category="A",
                answer_text=PAYLOAD["answer_text"],
                followup_pending=True,
                state_path=self.state_path,
                status_resolver=lambda *_a, **_k: mock.Mock(ready=True, provider="local-openai"),
                ai_call=ai_call,
                telegram_send=lambda _message: self.delivery.TelegramSendResult(
                    "confirmed", "telegram_confirmed", 1, 1
                ),
            )

        self.assertEqual(outcome.status, self.delivery.STATUS_CONFIRMED)
        self.assertEqual(seen["model"], "ack-model")
        expected_prompt = self.delivery.build_prompt({
            "question_id": "A3",
            "question_text": PAYLOAD["question_text"],
            "question_category": "A",
            "answer_text": PAYLOAD["answer_text"],
            "followup_pending": True,
        })
        self.assertEqual(seen["prompt"], expected_prompt)

    def test_process_answer_calls_ack_before_adaptive_followup(self):
        """Ported from the same-named #107 test.

        #107 asserted call order via a literal source-text index
        (``script.index("maybe_send_answer_ack(...")``) — purely
        implementation-specific and dropped, since neither that function
        name nor that literal call-site text exists after the swap. The
        ORDERING GUARANTEE itself (ack attempted, then follow-up sent) is
        ported here as a real behavioral assertion against
        ``run_post_answer_delivery``, and is also covered end-to-end by
        tests/test_v121_answer_ack_delivery.py's OrderingTests.
        """
        events = []
        with (
            mock.patch.object(self.process_answer, "plan_adaptive_followup",
                               return_value={"id": "B1", "category": "B", "text": "next?"}),
            mock.patch.object(self.delivery, "acknowledge_answer",
                               side_effect=lambda **_k: (
                                   events.append("ack"),
                                   self.delivery.AcknowledgmentOutcome(
                                       "answer:A3", "confirmed", "telegram_confirmed", True
                                   ),
                               )[1]),
            mock.patch.object(self.process_answer, "maybe_send_followup_question",
                               side_effect=lambda *_a: events.append("followup")),
        ):
            self.process_answer.run_post_answer_delivery(
                source_id="answer:A3",
                question_id="A3",
                question_text=PAYLOAD["question_text"],
                question_category="A",
                answer_text=PAYLOAD["answer_text"],
            )

        self.assertEqual(events, ["ack", "followup"])


if __name__ == "__main__":
    unittest.main()
