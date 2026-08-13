"""v121 warm local answer acknowledgment: ordering, privacy, and replay."""

from __future__ import annotations

import io
import json
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SYSTEM = ROOT / "system"
sys.path.insert(0, str(SYSTEM))
sys.path.insert(0, str(ROOT / "tests"))

from tempdirs import symlink_free_tmp  # noqa: E402
import answer_ack  # noqa: E402
import conversation_delivery as turn_engine  # noqa: E402
import answer_ack_delivery as delivery  # noqa: E402
import lifehug_core as core  # noqa: E402
import process_answer  # noqa: E402
from ai_provider import AIResponseError, ProviderStatus  # noqa: E402

SOURCE_ID = "answer:A1"
QUESTION = "What's your earliest memory?"
ANSWER = "I remember the blue porch swing and my sister's red rain boots."
MESSAGE = "Thank you for sharing that. The blue porch swing and those red rain boots make the memory feel close."


def ready_status(*_args, **_kwargs):
    return ProviderStatus("local-openai", "synthetic-model", True, "synthetic")


def unavailable_status(*_args, **_kwargs):
    return ProviderStatus("agent-task", "synthetic-model", False, "synthetic")


class DeliveryContractTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.state_path = Path(tmp.name) / "answer_acknowledgments.json"

    def _attempt(self, **overrides):
        kwargs = {
            "source_id": SOURCE_ID,
            "question_id": "A1",
            "question_text": QUESTION,
            "question_category": "A",
            "answer_text": ANSWER,
            "followup_pending": True,
            "state_path": self.state_path,
            "status_resolver": ready_status,
            "ai_call": lambda _prompt, _model: MESSAGE,
            "telegram_send": lambda _message: core.TelegramSendResult(
                "confirmed", "telegram_confirmed", 1, 1
            ),
        }
        kwargs.update(overrides)
        with mock.patch.object(delivery, "record_learning_failure"):
            return delivery.acknowledge_answer(**kwargs)

    def test_uses_canonical_answer_ack_prompt_byte_for_byte(self):
        seen = {}

        def ai_call(prompt, _model):
            seen["prompt"] = prompt
            return MESSAGE

        outcome = self._attempt(ai_call=ai_call)
        expected = answer_ack.build_prompt(
            {
                "question_id": "A1",
                "question_text": QUESTION,
                "question_category": "A",
                "answer_text": ANSWER,
                "followup_pending": True,
            }
        )
        self.assertEqual(seen["prompt"], expected)
        self.assertEqual(outcome.status, "confirmed")

    def test_keyless_provider_skips_without_calling_model_or_telegram(self):
        ai_call = mock.Mock(side_effect=AssertionError("model must not run"))
        telegram = mock.Mock(side_effect=AssertionError("telegram must not run"))
        outcome = self._attempt(
            status_resolver=unavailable_status,
            ai_call=ai_call,
            telegram_send=telegram,
        )
        self.assertEqual((outcome.status, outcome.reason), ("skipped", "no_unattended_provider"))
        ai_call.assert_not_called()
        telegram.assert_not_called()

    def test_malformed_generation_is_never_sent(self):
        telegram = mock.Mock()
        outcome = self._attempt(ai_call=lambda *_: "```json\n{}\n```", telegram_send=telegram)
        self.assertEqual((outcome.status, outcome.reason), ("failed", "malformed_generation"))
        telegram.assert_not_called()

    def test_definitive_telegram_rejection_can_retry(self):
        rejected = core.TelegramSendResult("rejected", "telegram_api_rejected", 0, 1)
        first = self._attempt(telegram_send=lambda _message: rejected)
        second = self._attempt()
        state = json.loads(self.state_path.read_text())
        self.assertEqual(first.status, "failed")
        self.assertEqual(second.status, "confirmed")
        self.assertEqual(state["entries"][SOURCE_ID]["attempts"], 2)

    def test_confirmed_send_is_not_generated_or_sent_twice(self):
        first = self._attempt()
        ai_call = mock.Mock(side_effect=AssertionError("duplicate generation"))
        telegram = mock.Mock(side_effect=AssertionError("duplicate send"))
        second = self._attempt(ai_call=ai_call, telegram_send=telegram)
        self.assertEqual(first.status, "confirmed")
        self.assertEqual((second.status, second.reason, second.attempted),
                         ("confirmed", "already_confirmed", False))
        ai_call.assert_not_called()
        telegram.assert_not_called()

    def test_ambiguous_send_stays_visible_and_is_not_blindly_retried(self):
        ambiguous = core.TelegramSendResult(
            "ambiguous", "telegram_transport_ambiguous", 0, 1
        )
        first = self._attempt(telegram_send=lambda _message: ambiguous)
        ai_call = mock.Mock(side_effect=AssertionError("blind retry"))
        second = self._attempt(ai_call=ai_call)
        state = json.loads(self.state_path.read_text())["entries"][SOURCE_ID]
        self.assertEqual(first.status, "ambiguous")
        self.assertEqual((second.status, second.reason, second.attempted),
                         ("ambiguous", "ambiguous_not_retried", False))
        self.assertEqual(state["operator_action"], "verify Telegram before retrying")
        ai_call.assert_not_called()

    def test_ambiguous_retry_requires_explicit_confirmation(self):
        ambiguous = core.TelegramSendResult(
            "ambiguous", "telegram_transport_ambiguous", 0, 1
        )
        self._attempt(telegram_send=lambda _message: ambiguous)
        retried = self._attempt(allow_ambiguous_retry=True)
        self.assertEqual(retried.status, "confirmed")

    def test_diagnostics_and_state_are_metadata_only(self):
        diagnostics = []
        secret_response = "MODEL ECHOED PRIVATE ANSWER"
        with mock.patch.object(
            delivery,
            "record_learning_failure",
            side_effect=lambda *args, **kwargs: diagnostics.append((args, kwargs)),
        ):
            outcome = delivery.acknowledge_answer(
                source_id=SOURCE_ID,
                question_id="A1",
                question_text=QUESTION,
                question_category="A",
                answer_text=ANSWER,
                followup_pending=False,
                state_path=self.state_path,
                status_resolver=ready_status,
                ai_call=lambda *_: (_ for _ in ()).throw(AIResponseError(secret_response)),
                telegram_send=lambda _message: core.TelegramSendResult(
                    "confirmed", "telegram_confirmed", 1, 1
                ),
            )
        self.assertEqual(outcome.reason, "provider_malformed_response")
        serialized = json.dumps(diagnostics) + self.state_path.read_text()
        for private in (ANSWER, QUESTION, MESSAGE, secret_response, "LIFEHUG — ANSWER"):
            self.assertNotIn(private, serialized)
        self.assertIn(SOURCE_ID, serialized)


class OrderingTests(unittest.TestCase):
    """The post-answer ordering contract, now via the v153 turn engine.

    Issue #116 replaced the ack + separate-follow-up pair with ONE
    conversation turn that degrades to exactly this pair when no provider is
    seated — which is the case in these tests. The assertions below are
    therefore unchanged; only the isolation is new: the engine writes a
    session document and a delivery ledger, so both are pointed at a
    synthetic vault (never the developer's real one, never ~/Workspace/dave).
    """

    def setUp(self):
        # ROOT.parent, never tempfile's default: on macOS /var is a symlink
        # and vault_paths refuses to traverse symlinks (tests/tempdirs.py).
        vault = symlink_free_tmp(self, prefix="lifehug-v153-ordering-") / "vault"
        vault.mkdir()
        for patch in (
            mock.patch.object(turn_engine, "VAULT_ROOT", vault),
            mock.patch.object(
                turn_engine, "DELIVERY_STATE_FILE", vault / "state" / "conversation_deliveries.json"
            ),
            # The engine keeps its own diagnostic channel; without this the
            # synthetic failures below would append to the real vault's
            # learning-failures log.
            mock.patch.object(turn_engine, "record_learning_failure"),
        ):
            patch.start()
            self.addCleanup(patch.stop)

    def test_commit_then_ack_then_followup_exact_order(self):
        events = []
        followup = {"id": "B1", "category": "B", "text": "What came next?"}

        def fake_ack(**_kwargs):
            events.append("ack")
            return delivery.AcknowledgmentOutcome(SOURCE_ID, "confirmed", "telegram_confirmed", True)

        with mock.patch.object(process_answer, "git_commit",
                               side_effect=lambda message, push: events.append(("commit", push))), \
                mock.patch.object(process_answer, "plan_adaptive_followup",
                                  side_effect=lambda _qid: (events.append("plan"), followup)[1]), \
                mock.patch.object(delivery, "acknowledge_answer", side_effect=fake_ack), \
                mock.patch.object(process_answer, "maybe_send_followup_question",
                                  side_effect=lambda *_args: events.append("followup")), \
                mock.patch.object(process_answer, "maybe_send_chapter_ready_offer",
                                  side_effect=lambda _qid: events.append("chapter")):
            process_answer.finalize_answer_delivery(
                source_id=SOURCE_ID,
                question_id="A1",
                question_text=QUESTION,
                question_category="A",
                answer_text=ANSWER,
                commit_requested=True,
                push_requested=True,
                summary="synthetic answer",
            )

        self.assertEqual(
            events,
            [("commit", False), "plan", "ack", "followup", "chapter", ("commit", True)],
        )

    def test_ack_failure_never_suppresses_followup(self):
        events = []
        followup = {"id": "B1", "category": "B", "text": "What came next?"}
        with mock.patch.object(process_answer, "plan_adaptive_followup", return_value=followup), \
                mock.patch.object(delivery, "acknowledge_answer",
                                  side_effect=RuntimeError("synthetic")), \
                mock.patch.object(process_answer, "maybe_send_followup_question",
                                  side_effect=lambda *_args: events.append("followup")), \
                mock.patch.object(process_answer, "record_learning_failure") as diagnostic:
            process_answer.run_post_answer_delivery(
                source_id=SOURCE_ID,
                question_id="A1",
                question_text=QUESTION,
                question_category="A",
                answer_text=ANSWER,
            )
        self.assertEqual(events, ["followup"])
        self.assertNotIn(ANSWER, repr(diagnostic.call_args))

    def test_unexpected_telegram_exception_stays_ambiguous_and_followup_runs(self):
        events = []
        original_ack = delivery.acknowledge_answer
        followup = {"id": "B1", "category": "B", "text": "What came next?"}
        with tempfile.TemporaryDirectory() as tmp:
            state_path = Path(tmp) / "answer_acknowledgments.json"

            def crashing_ack(**kwargs):
                return original_ack(
                    **kwargs,
                    state_path=state_path,
                    status_resolver=ready_status,
                    ai_call=lambda *_: MESSAGE,
                    telegram_send=lambda _message: (_ for _ in ()).throw(
                        RuntimeError("transport crashed after request began")
                    ),
                )

            with mock.patch.object(process_answer, "plan_adaptive_followup", return_value=followup), \
                    mock.patch.object(delivery, "acknowledge_answer", side_effect=crashing_ack), \
                    mock.patch.object(process_answer, "maybe_send_followup_question",
                                      side_effect=lambda *_args: events.append("followup")), \
                    mock.patch.object(process_answer, "record_learning_failure") as diagnostic:
                process_answer.run_post_answer_delivery(
                    source_id=SOURCE_ID,
                    question_id="A1",
                    question_text=QUESTION,
                    question_category="A",
                    answer_text=ANSWER,
                )

            entry = json.loads(state_path.read_text())["entries"][SOURCE_ID]
        self.assertEqual(events, ["followup"])
        self.assertEqual((entry["status"], entry["reason"]), ("ambiguous", "send_in_progress"))
        self.assertEqual(entry["operator_action"], "verify Telegram before retrying")
        self.assertNotIn(ANSWER, repr(diagnostic.call_args))


class ProcessAnswerIntegrationTests(unittest.TestCase):
    def setUp(self):
        vault = symlink_free_tmp(self, prefix="lifehug-v153-integration-") / "vault"
        vault.mkdir()
        for patch in (
            mock.patch.object(turn_engine, "VAULT_ROOT", vault),
            mock.patch.object(
                turn_engine,
                "DELIVERY_STATE_FILE",
                vault / "state" / "conversation_deliveries.json",
            ),
            mock.patch.object(turn_engine, "record_learning_failure"),
        ):
            patch.start()
            self.addCleanup(patch.stop)

    def test_main_has_durable_file_and_first_commit_before_acknowledgment(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            system_dir = root / "system"
            answers_dir = root / "answers"
            system_dir.mkdir()
            answers_dir.mkdir()
            questions_file = system_dir / "question-bank.md"
            rotation_file = system_dir / "rotation.json"
            questions_file.write_text(
                "# Questions\n\n"
                "## A: Origins\n"
                f"- [ ] A1: {QUESTION}\n\n"
                "## B: Becoming\n"
                "- [ ] B1: What came next?\n",
                encoding="utf-8",
            )
            rotation_file.write_text(
                json.dumps({"current_pass": 1, "last_question_id": "A1"}),
                encoding="utf-8",
            )
            first_commit_made = False
            observations = []

            def fake_commit(message, push):
                nonlocal first_commit_made
                observations.append(("commit", message, push))
                if message.startswith("Answer A1:"):
                    first_commit_made = True

            def observe_ack(**_kwargs):
                answer_path = answers_dir / "A1.md"
                self.assertTrue(answer_path.exists())
                self.assertTrue(first_commit_made)
                self.assertIn(ANSWER, answer_path.read_text(encoding="utf-8"))
                observations.append(("ack",))
                return delivery.AcknowledgmentOutcome(
                    SOURCE_ID, "confirmed", "telegram_confirmed", True
                )

            fake_quality = types.ModuleType("quality_profile")
            fake_quality.extract_signals = lambda *_args: {}
            fake_quality.score_richness = lambda *_args: 0.0
            fake_quality.focus_for_category = lambda *_args: "life"
            # engagement=... (issue #119) is an optional kwarg on the real
            # append_score; this fake accepts and ignores it like the rest.
            fake_quality.append_score = lambda *_args, **_kwargs: None
            fake_planner = types.ModuleType("question_planner")
            fake_planner.infer_story_function = lambda *_args: "foundation"

            with mock.patch.object(process_answer, "REPO_DIR", root), \
                    mock.patch.object(process_answer, "QUESTIONS_FILE", questions_file), \
                    mock.patch.object(process_answer, "ROTATION_FILE", rotation_file), \
                    mock.patch.object(process_answer, "ANSWERS_DIR", answers_dir), \
                    mock.patch.object(process_answer, "register_source"), \
                    mock.patch.object(process_answer, "mark_answered_in_bank"), \
                    mock.patch.object(
                        process_answer,
                        "rebuild_coverage",
                        return_value={
                            "categories": {
                                "A": {"total": 1},
                                "B": {"total": 1},
                            }
                        },
                    ), \
                    mock.patch.object(process_answer, "refresh_neighborhood_readiness_safely"), \
                    mock.patch.object(process_answer, "update_readme"), \
                    mock.patch.object(process_answer, "git_commit", side_effect=fake_commit), \
                    mock.patch.object(process_answer, "plan_adaptive_followup", return_value=None), \
                    mock.patch.object(delivery, "acknowledge_answer", side_effect=observe_ack), \
                    mock.patch.object(process_answer, "maybe_send_followup_question"), \
                    mock.patch.object(process_answer, "maybe_send_chapter_ready_offer"), \
                    mock.patch.dict(
                        sys.modules,
                        {"quality_profile": fake_quality, "question_planner": fake_planner},
                    ), \
                    mock.patch.object(sys, "argv", [
                        "process_answer.py", "A1", "--no-compile-wiki", "--commit"
                    ]), \
                    mock.patch.object(sys, "stdin", io.StringIO(ANSWER)), \
                    mock.patch.object(sys, "stdout", io.StringIO()):
                process_answer.main()

        self.assertEqual(observations[0][0], "commit")
        self.assertEqual(observations[1], ("ack",))
        self.assertEqual(observations[2][0], "commit")


class RetryCommandTests(unittest.TestCase):
    def test_retry_rebuilds_context_from_durable_answer_without_logging_body(self):
        with tempfile.TemporaryDirectory() as tmp:
            answers = Path(tmp)
            (answers / "A1.md").write_text(
                "---\n"
                'source_id: "answer:A1"\n'
                'question_id: "A1"\n'
                f"question_text: {json.dumps(QUESTION)}\n"
                'category: "A"\n'
                "---\n\n"
                f"# Question A1: {QUESTION}\n\n{ANSWER}\n",
                encoding="utf-8",
            )
            captured = {}

            def fake_ack(**kwargs):
                captured.update(kwargs)
                return delivery.AcknowledgmentOutcome(
                    SOURCE_ID, "confirmed", "telegram_confirmed", True
                )

            with mock.patch.object(delivery, "ANSWERS_DIR", answers), \
                    mock.patch.object(delivery, "acknowledge_answer", side_effect=fake_ack):
                outcome = delivery.retry_durable_answer("A1")
        self.assertEqual(outcome.status, "confirmed")
        self.assertEqual(captured["source_id"], SOURCE_ID)
        self.assertEqual(captured["answer_text"], ANSWER)
        self.assertFalse(captured["followup_pending"])


class TelegramResultTests(unittest.TestCase):
    def test_transport_timeout_is_ambiguous(self):
        with mock.patch.object(core, "resolve_telegram_target", return_value=("token", "chat")), \
                mock.patch("urllib.request.urlopen", side_effect=TimeoutError):
            result = core.send_telegram_result(MESSAGE)
        self.assertEqual(
            (result.status, result.reason),
            ("ambiguous", "telegram_transport_ambiguous"),
        )

    def test_explicit_api_rejection_is_definitive(self):
        response = mock.MagicMock()
        response.__enter__.return_value.read.return_value = b'{"ok": false}'
        with mock.patch.object(core, "resolve_telegram_target", return_value=("token", "chat")), \
                mock.patch("urllib.request.urlopen", return_value=response):
            result = core.send_telegram_result(MESSAGE)
        self.assertEqual((result.status, result.reason), ("rejected", "telegram_api_rejected"))


if __name__ == "__main__":
    unittest.main()
