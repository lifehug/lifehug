"""v153 / issue #116 — the conversation turn engine.

Wave 2 PR 3 of the Conversation Interaction build. The post-answer moment
becomes ONE conversation turn (receipt + payout + cued follow-up), with an
exactly-once delivery ledger and a non-negotiable fallback to today's
acknowledgment + separate-follow-up pair.

Every collaborator is injected (``ai_call`` / ``telegram_send`` /
``status_resolver`` / clock / ``state_path`` / ``vault_root`` /
``followup_minter`` / ``rotation_updater`` / ``fallback``); the vault is a
synthetic temp tree built through tests/tempdirs.py. Synthetic data only —
NEVER ~/Workspace/dave.

Subtest names are the contract's own list (state-machine-shaped change →
named explicitly, v130/v131 precedent).
"""

from __future__ import annotations

import json
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SYSTEM = ROOT / "system"
sys.path.insert(0, str(SYSTEM))
sys.path.insert(0, str(ROOT / "tests"))

from tempdirs import root_parent_tmp  # noqa: E402
import conversation  # noqa: E402
import conversation_delivery as engine  # noqa: E402
import lifehug_core as core  # noqa: E402
from ai_provider import AIUnavailableError, ProviderStatus  # noqa: E402

QUESTION_ID = "A14"
QUESTION = "What did the farm smell like?"
ANSWER = "Diesel and cut hay, mostly. My grandfather's hands always smelled like both."
SECOND_ANSWER = "The hay came from the north field, and he baled it himself every August."
THIRD_ANSWER = "He kept the baler running with parts he machined in the barn."
TURN_MESSAGE = (
    "Diesel and cut hay — and your grandfather's hands carrying both at once. "
    'Tell me about "the north field".'
)
FOLLOWUP_TEXT = 'Tell me about "the north field".'
CLOSING_MESSAGE = (
    "What stays with me is that his hands carried the work and the harvest at "
    "the same time. Thank you for putting me in that barn. Next time we can "
    "pick up the baler he kept alive."
)


def ready_status(*_args, **_kwargs):
    return ProviderStatus("local-openai", "synthetic-model", True, "synthetic")


def keyless_status(*_args, **_kwargs):
    return ProviderStatus("agent-task", "synthetic-model", False, "synthetic")


def down_status(*_args, **_kwargs):
    return ProviderStatus("anthropic", "synthetic-model", False, "synthetic")


def confirmed_send(_message):
    return core.TelegramSendResult("confirmed", "telegram_confirmed", 1, 1)


def ambiguous_send(_message):
    return core.TelegramSendResult("ambiguous", "telegram_transport_ambiguous", 0, 1)


def rejected_send(_message):
    return core.TelegramSendResult("rejected", "telegram_api_rejected", 0, 1)


def turn_json(message=TURN_MESSAGE, followup=FOLLOWUP_TEXT, **extra):
    payload = {
        "message": message,
        "followup_question": followup,
        "question_free": followup is None,
        "rolling_summary": "The farm's smells; grandfather's hands.",
        "insight_receipts": 1,
        "extracted": {
            "facts": ["the farm ran on diesel"],
            "entities": [{"name": "grandfather"}],
            "candidate_ideas": [{"text": "What did he machine in that barn?"}],
            "mirror_responses": [],
        },
    }
    payload.update(extra)
    return json.dumps(payload)


class EngineTestCase(unittest.TestCase):
    """Synthetic vault + injected collaborators shared by every subtest."""

    def setUp(self):
        self.tmp = root_parent_tmp(self, ROOT, prefix="lifehug-v153-turn-")
        self.vault = self.tmp / "vault"
        self.vault.mkdir()
        self.state_path = self.tmp / "conversation_deliveries.json"
        self.scores_path = self.tmp / "answer_scores.json"
        self.candidates_path = self.tmp / "question_candidates.json"
        self.sent: list[str] = []
        self.prompts: list[str] = []
        self.fallbacks: list[dict] = []
        self.minted: list[tuple[str, str]] = []
        self.rotation: list[str] = []
        diagnostics = mock.patch.object(engine, "record_learning_failure")
        self.diagnostic = diagnostics.start()
        self.addCleanup(diagnostics.stop)

    # -- injected collaborators -------------------------------------------

    def _ai(self, response=None, error=None):
        def call(prompt, _model):
            self.prompts.append(prompt)
            if error is not None:
                raise error
            return response if response is not None else turn_json()

        return call

    def _send(self, transport=confirmed_send):
        def send(message):
            self.sent.append(message)
            return transport(message)

        return send

    def _fallback(self, **kwargs):
        self.fallbacks.append(kwargs)

    def _minter(self, question_id, followups):
        new_id = f"{question_id}{chr(ord('a') + len(self.minted))}"
        self.minted.append((new_id, followups[0]))
        return [(new_id, followups[0])]

    def _rotation_updater(self, question_id):
        self.rotation.append(question_id)

    def run_turn(self, answer_text=ANSWER, question_id=QUESTION_ID, **overrides):
        kwargs = {
            "source_id": f"answer:{question_id}",
            "question_id": question_id,
            "question_text": QUESTION,
            "question_category": "A",
            "answer_text": answer_text,
            "planned_question": {"id": "B1", "category": "B", "text": "What came next?"},
            "state_path": self.state_path,
            "vault_root": self.vault,
            "sweep": False,
            "status_resolver": ready_status,
            "ai_call": self._ai(),
            "telegram_send": self._send(),
            "prompt_builder": lambda payload: "SYNTHETIC TURN PROMPT",
            "followup_minter": self._minter,
            "rotation_updater": self._rotation_updater,
            "fallback": self._fallback,
        }
        kwargs.update(overrides)
        return engine.run_post_answer_turn(**kwargs)

    def entries(self):
        return json.loads(self.state_path.read_text(encoding="utf-8"))["entries"]

    def only_session(self):
        sessions = conversation.list_sessions(vault_root=self.vault)
        self.assertEqual(len(sessions), 1, sessions)
        return conversation.load_session(sessions[0]["session_id"], vault_root=self.vault)

    def seed_score(self, question_id, richness=0.75):
        data = json.loads(self.scores_path.read_text(encoding="utf-8")) if self.scores_path.exists() \
            else {"version": 1, "scores": []}
        data["scores"].append({
            "question_id": question_id,
            "answered_at": "2026-08-11",
            "category": "A",
            "story_function": "scene",
            "focus": None,
            "signals": {"words": 42},
            "richness_score": richness,
        })
        self.scores_path.write_text(json.dumps(data), encoding="utf-8")


class ConfirmedTurnTests(EngineTestCase):
    def test_confirmed_turn_is_one_message(self):
        outcome = self.run_turn()

        self.assertEqual(self.sent, [TURN_MESSAGE])  # ONE message, not two
        self.assertEqual((outcome.status, outcome.reason), ("confirmed", "telegram_confirmed"))
        self.assertEqual(self.fallbacks, [])
        # Follow-up minted through the A14 -> A14a suffix chain, rotation retargeted.
        self.assertEqual(self.minted, [("A14a", FOLLOWUP_TEXT)])
        self.assertEqual(self.rotation, ["A14a"])
        self.assertEqual(outcome.followup_id, "A14a")

        session = self.only_session()
        roles = [turn["role"] for turn in session["turns"]]
        self.assertEqual(roles, ["user", "lifehug"])
        self.assertEqual(session["turns"][1]["question_id"], "A14a")
        self.assertEqual(session["extracted"]["candidate_ideas"],
                         [{"text": "What did he machine in that barn?"}])
        entry = self.entries()[engine.turn_key(session["session_id"], 1)]
        self.assertEqual((entry["status"], entry["reason"]), ("confirmed", "telegram_confirmed"))
        self.assertEqual(entry["attempts"], 1)

    def test_confirmed_replay_is_noop(self):
        first = self.run_turn()
        ai = mock.Mock(side_effect=AssertionError("duplicate generation"))
        telegram = mock.Mock(side_effect=AssertionError("duplicate send"))
        second = self.run_turn(ai_call=ai, telegram_send=telegram)

        self.assertEqual(first.status, "confirmed")
        self.assertEqual((second.status, second.reason, second.attempted),
                         ("confirmed", "already_confirmed", False))
        ai.assert_not_called()
        telegram.assert_not_called()
        self.assertEqual(len(self.only_session()["turns"]), 2)


class AmbiguousTests(EngineTestCase):
    def test_ambiguous_never_auto_retried_and_no_fallback_ack(self):
        first = self.run_turn(telegram_send=self._send(ambiguous_send))
        self.assertEqual(first.status, "ambiguous")
        # The turn may have reached Telegram — a fallback ack would risk a
        # duplicate voice, so nothing else goes out.
        self.assertEqual(self.fallbacks, [])
        self.assertEqual(self.minted, [])

        session = self.only_session()
        entry = self.entries()[engine.turn_key(session["session_id"], 1)]
        self.assertEqual(entry["operator_action"], "verify Telegram before retrying")

        ai = mock.Mock(side_effect=AssertionError("blind retry"))
        second = self.run_turn(ai_call=ai)
        self.assertEqual((second.status, second.reason, second.attempted),
                         ("ambiguous", "ambiguous_not_retried", False))
        ai.assert_not_called()
        self.assertEqual(self.fallbacks, [])

    def test_pre_send_ambiguous_position_is_written_before_the_send(self):
        observed = {}

        def send(message):
            observed["entries"] = json.loads(self.state_path.read_text())["entries"]
            return confirmed_send(message)

        self.run_turn(telegram_send=send)
        entry = next(iter(observed["entries"].values()))
        self.assertEqual((entry["status"], entry["reason"]), ("ambiguous", "send_in_progress"))


class FallbackTests(EngineTestCase):
    def test_provider_unavailable_falls_back_to_todays_behavior(self):
        telegram = mock.Mock(side_effect=AssertionError("no turn may be sent"))
        outcome = self.run_turn(status_resolver=down_status, telegram_send=telegram)

        self.assertEqual((outcome.status, outcome.reason), ("skipped", "provider_unavailable"))
        self.assertTrue(outcome.fallback_used)
        self.assertEqual(len(self.fallbacks), 1)
        # The ack is told honestly whether a follow-up is pending, and the
        # planned bank question is handed to the separate follow-up message.
        self.assertEqual(self.fallbacks[0]["planned_question"], {"id": "B1", "category": "B",
                                                                 "text": "What came next?"})
        self.assertEqual(self.fallbacks[0]["question_id"], QUESTION_ID)
        telegram.assert_not_called()

    def test_keyless_provider_reports_no_unattended_provider(self):
        outcome = self.run_turn(status_resolver=keyless_status)
        self.assertEqual((outcome.status, outcome.reason), ("skipped", "no_unattended_provider"))
        self.assertTrue(outcome.fallback_used)

    def test_provider_error_falls_back(self):
        outcome = self.run_turn(ai_call=self._ai(error=AIUnavailableError("synthetic")))
        self.assertEqual((outcome.status, outcome.reason), ("failed", "provider_unavailable"))
        self.assertEqual(len(self.fallbacks), 1)

    def test_definitive_send_rejection_falls_back(self):
        outcome = self.run_turn(telegram_send=self._send(rejected_send))
        self.assertEqual(outcome.status, "failed")
        self.assertTrue(outcome.fallback_used)
        self.assertEqual(len(self.fallbacks), 1)
        # No follow-up is minted for a message the user never received.
        self.assertEqual(self.minted, [])

    def test_lint_reject_falls_back(self):
        cases = {
            "two_questions": turn_json(
                message="Diesel and hay. What was the field like? And who baled it?"
            ),
            "overlong": turn_json(message="x" * 4000),
            "banned_phrase": turn_json(
                message='That must have been hard. Tell me about "the north field".'
            ),
            "unparseable": "I am not JSON at all.",
        }
        for label, generated in cases.items():
            with self.subTest(case=label):
                self.setUp()  # a fresh synthetic vault per case
                outcome = self.run_turn(ai_call=self._ai(response=generated))
                self.assertEqual((outcome.status, outcome.reason),
                                 ("failed", "malformed_generation"))
                self.assertEqual(self.sent, [])
                self.assertEqual(len(self.fallbacks), 1)


class TurnShapeTests(EngineTestCase):
    def _continue_session(self, answers):
        """Drive N sequential answers through the engine in one session."""
        outcomes = []
        for index, answer in enumerate(answers):
            outcomes.append(self.run_turn(answer_text=answer, question_id=QUESTION_ID))
        return outcomes

    def test_question_free_turn(self):
        outcome = self.run_turn(ai_call=self._ai(response=turn_json(
            message="Diesel and cut hay. I can smell that barn from here.",
            followup=None,
        )))
        self.assertEqual(outcome.status, "confirmed")
        self.assertTrue(outcome.question_free)
        self.assertEqual(self.minted, [])       # nothing minted
        self.assertEqual(self.rotation, [])     # rotation untouched

    def test_curfew_and_cap_gates_transfer(self):
        # plan_adaptive_followup returned None (curfew / 3-a-day cap / pass
        # transition): our initiative is spent, so the turn is question-free
        # and a model that asks anyway is rejected rather than sent.
        outcome = self.run_turn(
            planned_question=None,
            ai_call=self._ai(response=turn_json(
                message="Diesel and cut hay. What was the north field like?",
                followup="What was the north field like?",
            )),
        )
        self.assertEqual((outcome.status, outcome.reason), ("failed", "malformed_generation"))
        self.assertIn("question_not_permitted", outcome.lint_ids)
        self.assertEqual(self.sent, [])

        self.setUp()
        outcome = self.run_turn(
            planned_question=None,
            ai_call=self._ai(response=turn_json(message="Diesel and cut hay — I can smell it.",
                                                followup=None)),
        )
        self.assertEqual(outcome.status, "confirmed")
        self.assertEqual(self.minted, [])

    def test_third_exchange_exit_shape_and_cap(self):
        first = self.run_turn(answer_text=ANSWER)
        second = self.run_turn(answer_text=SECOND_ANSWER)
        self.assertEqual([o.status for o in (first, second)], ["confirmed", "confirmed"])
        self.assertEqual(len(self.minted), 2)  # exchanges 1 and 2 carry initiative

        # Exchange 3 is the exit-friendly door: it receives and pays out, but
        # asks nothing — stopping there has to feel like a good place to rest.
        # (The shape is decided with the incoming answer already recorded, so
        # it is keyed on the user-turn count including this exchange's.)
        manifest = engine._manifest()
        def shape_for(user_turns):
            return engine.decide_turn_shape(
                {"mode": "chat", "turns": [{"role": "user", "text": "x"}] * user_turns},
                manifest=manifest,
                planned_question={"id": "B1"},
            )

        self.assertEqual(shape_for(1).position, "opening")
        self.assertEqual(shape_for(2).position, "mid_arc")
        self.assertTrue(shape_for(2).question_allowed)
        self.assertEqual(shape_for(3).position, "third_exchange_exit_friendly")
        self.assertFalse(shape_for(3).question_allowed)
        self.assertEqual(shape_for(4).position, "past_target")
        self.assertFalse(shape_for(4).question_allowed)

        third = self.run_turn(
            answer_text=THIRD_ANSWER,
            ai_call=self._ai(response=turn_json(
                message="A baler kept alive with parts he made himself. That is a whole "
                        "portrait of him in one sentence.",
                followup=None,
            )),
        )
        self.assertEqual(third.status, "confirmed")
        self.assertEqual(len(self.minted), 2)  # no new initiative spent

        # And past the target the user keeps going: we keep receiving, never
        # hard-stopping, still without spending question initiative.
        fourth = self.run_turn(
            answer_text="He taught me to listen for when the belt slipped.",
            ai_call=self._ai(response=turn_json(
                message="Listening for the belt — that is the kind of knowing you only "
                        "get by standing next to someone.",
                followup=None,
            )),
        )
        self.assertEqual(fourth.status, "confirmed")
        self.assertEqual(len(self.only_session()["turns"]), 8)


class SingleFlightTests(EngineTestCase):
    def test_single_flight_mint(self):
        first = self.run_turn()
        session_id = self.only_session()["session_id"]

        # A concurrent second entry arrives with the same session already
        # advanced: the store's compare-and-set rejects it, and the loser
        # sends nothing at all (not even a fallback ack — the winner's turn
        # is the voice).
        original = conversation.append_turn

        def conflicting_append(*args, **kwargs):
            raise conversation.TurnConflictError("a concurrent writer won")

        with mock.patch.object(conversation, "append_turn", conflicting_append):
            second = self.run_turn(answer_text=SECOND_ANSWER)

        self.assertEqual(first.status, "confirmed")
        self.assertEqual((second.status, second.reason), ("skipped", "turn_already_minted"))
        self.assertFalse(second.fallback_used)
        self.assertEqual(self.fallbacks, [])
        self.assertEqual(self.sent, [TURN_MESSAGE])
        self.assertIs(conversation.append_turn, original)
        self.assertEqual(len(conversation.load_session(session_id,
                                                       vault_root=self.vault)["turns"]), 2)


class CloseTests(EngineTestCase):
    def _fixed_clock(self, moment):
        patch = mock.patch.object(engine, "_now", lambda: moment)
        patch.start()
        self.addCleanup(patch.stop)

    def test_idle_timeout_files_partial_chat_silently(self):
        self.seed_score(QUESTION_ID)
        self.run_turn()  # one answer, then the user walks away mid-chat
        session_id = self.only_session()["session_id"]
        telegram = mock.Mock(side_effect=AssertionError("no-nag: nothing may be sent"))
        ai = mock.Mock(side_effect=AssertionError("no closing generation"))

        # Design §D (2026-08-12): the sweep is a 36h-class janitor now, not
        # the old 120-minute chat knob — 5 hours idle must NOT trip it.
        soon = datetime.now(timezone.utc) + timedelta(hours=5)
        untouched = engine.close_expired_sessions(
            now=soon,
            vault_root=self.vault,
            state_path=self.state_path,
            scores_path=self.scores_path,
            candidates_path=self.candidates_path,
            ai_call=ai,
            telegram_send=telegram,
            status_resolver=ready_status,
        )
        self.assertEqual(untouched, [])
        self.assertEqual(
            conversation.load_session(session_id, vault_root=self.vault)["status"], "open",
        )

        later = datetime.now(timezone.utc) + timedelta(hours=37)
        outcomes = engine.close_expired_sessions(
            now=later,
            vault_root=self.vault,
            state_path=self.state_path,
            scores_path=self.scores_path,
            candidates_path=self.candidates_path,
            ai_call=ai,
            telegram_send=telegram,
            status_resolver=ready_status,
        )

        self.assertEqual([o.session_id for o in outcomes], [session_id])
        self.assertTrue(outcomes[0].silent)
        telegram.assert_not_called()
        ai.assert_not_called()

        session = conversation.load_session(session_id, vault_root=self.vault)
        self.assertEqual(session["status"], "closed")
        self.assertEqual(session["close"]["reason"], "idle_timeout")
        self.assertFalse(session["close"]["takeaway_delivered"])
        self.assertEqual(session["close"]["takeaway"], "")
        self.assertEqual(session["close"]["filed"], [QUESTION_ID])
        # The answer itself stays filed — durability is per turn, not per close.
        scores = json.loads(self.scores_path.read_text())["scores"]
        self.assertEqual(scores[0]["richness_score"], 0.75)

    def test_completed_chat_closing_takeaway(self):
        self.run_turn(answer_text=ANSWER)
        self.run_turn(answer_text=SECOND_ANSWER)
        session_id = self.only_session()["session_id"]

        outcome = engine.close_session_now(
            session_id,
            reason="done",
            state_path=self.state_path,
            vault_root=self.vault,
            scores_path=self.scores_path,
            candidates_path=self.candidates_path,
            status_resolver=ready_status,
            ai_call=lambda _prompt, _model: json.dumps({"message": CLOSING_MESSAGE}),
            telegram_send=self._send(),
            prompt_builder=lambda payload: "SYNTHETIC CLOSING PROMPT",
        )

        self.assertTrue(outcome.takeaway_delivered)
        self.assertEqual(self.sent[-1], CLOSING_MESSAGE)
        session = conversation.load_session(session_id, vault_root=self.vault)
        self.assertTrue(session["close"]["takeaway_delivered"])
        self.assertEqual(session["close"]["takeaway"], CLOSING_MESSAGE)
        self.assertEqual(session["close"]["insight_receipts_count"], 2)
        entry = self.entries()[engine.close_key(session_id)]
        self.assertEqual((entry["status"], entry["reason"]), ("confirmed", "telegram_confirmed"))

    def test_closing_with_a_trailing_question_is_never_sent(self):
        self.run_turn(answer_text=ANSWER)
        self.run_turn(answer_text=SECOND_ANSWER)
        session_id = self.only_session()["session_id"]
        before = len(self.sent)

        outcome = engine.close_session_now(
            session_id,
            state_path=self.state_path,
            vault_root=self.vault,
            scores_path=self.scores_path,
            candidates_path=self.candidates_path,
            status_resolver=ready_status,
            ai_call=lambda _p, _m: json.dumps(
                {"message": "Thank you for that. What should we talk about next time?"}
            ),
            telegram_send=self._send(),
            prompt_builder=lambda payload: "SYNTHETIC CLOSING PROMPT",
        )
        self.assertFalse(outcome.takeaway_delivered)
        self.assertEqual(len(self.sent), before)  # behavior rule 8: no trailing question

    def test_engagement_appended_to_answer_scores(self):
        self.seed_score(QUESTION_ID)
        self.seed_score("A14a")
        self.run_turn(answer_text=ANSWER)
        self.run_turn(answer_text=SECOND_ANSWER, question_id="A14a")
        session_id = self.only_session()["session_id"]

        engine.close_session_now(
            session_id,
            reason="done",
            state_path=self.state_path,
            vault_root=self.vault,
            scores_path=self.scores_path,
            candidates_path=self.candidates_path,
            status_resolver=ready_status,
            ai_call=lambda _p, _m: json.dumps({"message": CLOSING_MESSAGE}),
            telegram_send=self._send(),
            prompt_builder=lambda payload: "SYNTHETIC CLOSING PROMPT",
        )

        scores = {s["question_id"]: s for s in json.loads(self.scores_path.read_text())["scores"]}
        for question_id in (QUESTION_ID, "A14a"):
            engagement = scores[question_id]["engagement"]
            # #119's authoritative names for the shared fields.
            self.assertEqual(
                sorted(engagement),
                ["close_reason", "continuation_past_exit", "session_id", "session_turns",
                 "turn_length_trajectory"],
            )
            self.assertEqual(engagement["session_id"], session_id)
            self.assertEqual(engagement["close_reason"], "done")
            self.assertFalse(engagement["continuation_past_exit"])
            self.assertIn(engagement["turn_length_trajectory"],
                          {"expanding", "flat", "contracting"})
            # Richness is never overwritten.
            self.assertEqual(scores[question_id]["richness_score"], 0.75)
            self.assertEqual(scores[question_id]["signals"], {"words": 42})

    def test_candidate_ideas_filed_with_conversation_provenance(self):
        self.run_turn(answer_text=ANSWER)
        self.run_turn(answer_text=SECOND_ANSWER)
        session_id = self.only_session()["session_id"]
        engine.close_session_now(
            session_id,
            state_path=self.state_path,
            vault_root=self.vault,
            scores_path=self.scores_path,
            candidates_path=self.candidates_path,
            status_resolver=ready_status,
            ai_call=lambda _p, _m: json.dumps({"message": CLOSING_MESSAGE}),
            telegram_send=self._send(),
            prompt_builder=lambda payload: "SYNTHETIC CLOSING PROMPT",
        )
        candidates = json.loads(self.candidates_path.read_text())["candidates"]
        self.assertEqual(len(candidates), 1)  # de-duplicated across both turns
        self.assertEqual(candidates[0]["provenance"], "conversation")
        self.assertEqual(candidates[0]["text"], "What did he machine in that barn?")

    def test_zero_turn_session_closes_silently(self):
        session = conversation.open_session("chat", "telegram", vault_root=self.vault)
        telegram = mock.Mock(side_effect=AssertionError("no-nag"))
        outcome = engine.close_session_now(
            session["session_id"],
            reason="idle_timeout",
            state_path=self.state_path,
            vault_root=self.vault,
            scores_path=self.scores_path,
            candidates_path=self.candidates_path,
            status_resolver=ready_status,
            telegram_send=telegram,
        )
        self.assertTrue(outcome.silent)
        self.assertEqual(outcome.detail, "silent_no_nag")
        telegram.assert_not_called()

    def test_idle_timeout_knobs_come_from_interaction_yaml(self):
        # Design §D (2026-08-12): raised to day-scale (1440 min-class) —
        # day rollover + user transitions are the real lifecycle now, these
        # are only a generous "still counts as current" continuation
        # ceiling, not a UX trigger.
        manifest = engine._manifest()
        chat = {"mode": "chat", "session_id": "conv-20260811-120000-abcdef", "turns": []}
        talk = {"mode": "conversation", "session_id": "conv-20260811-120000-abcdef", "turns": []}
        self.assertEqual(engine.idle_timeout_minutes(chat, manifest), 1440)
        self.assertEqual(engine.idle_timeout_minutes(talk, manifest), 1440)
        opened = datetime(2026, 8, 11, 12, 0, 0, tzinfo=timezone.utc)
        self.assertFalse(engine.is_idle_expired(chat, manifest=manifest,
                                                now=opened + timedelta(minutes=1439)))
        self.assertTrue(engine.is_idle_expired(chat, manifest=manifest,
                                               now=opened + timedelta(minutes=1441)))

    def test_janitor_knob_comes_from_interaction_yaml(self):
        manifest = engine._manifest()
        self.assertEqual(manifest.get("knob.janitor_idle_hours"), 36)
        stale = {"mode": "chat", "session_id": "conv-20260811-120000-abcdef", "turns": []}
        opened = datetime(2026, 8, 11, 12, 0, 0, tzinfo=timezone.utc)
        self.assertFalse(engine.is_janitor_expired(stale, manifest=manifest,
                                                    now=opened + timedelta(hours=35)))
        self.assertTrue(engine.is_janitor_expired(stale, manifest=manifest,
                                                   now=opened + timedelta(hours=37)))


class DayRolloverTests(EngineTestCase):
    """Design §D (Chats-per-Focus, 2026-08-12): day rollover closes EVERY
    open session — no idle filter, the day owns the surface, not a timer."""

    def test_closes_every_open_session_regardless_of_idle_age(self):
        fresh_chat = conversation.open_session("chat", "telegram", vault_root=self.vault)
        fresh_talk = conversation.open_session("conversation", "telegram", vault_root=self.vault)
        already_closed = conversation.open_session(
            "chat", "telegram", session_id="conv-20200101-000000-bbbbbb",
            vault_root=self.vault,
        )
        conversation.close_session(already_closed["session_id"], {"reason": "done"},
                                    vault_root=self.vault)

        ids = engine.find_open_sessions(vault_root=self.vault)
        self.assertEqual(set(ids), {fresh_chat["session_id"], fresh_talk["session_id"]})

        telegram = mock.Mock(side_effect=AssertionError("no-nag: nothing may be sent"))
        outcomes = engine.close_all_open_sessions(
            vault_root=self.vault,
            state_path=self.state_path,
            scores_path=self.scores_path,
            candidates_path=self.candidates_path,
            ai_call=mock.Mock(side_effect=AssertionError("no closing generation")),
            telegram_send=telegram,
            status_resolver=ready_status,
        )

        self.assertEqual({o.session_id for o in outcomes},
                         {fresh_chat["session_id"], fresh_talk["session_id"]})
        for outcome in outcomes:
            self.assertEqual(outcome.reason, "day_rollover")
            self.assertTrue(outcome.silent)  # zero user turns -> silent, no nag
        for session_id in (fresh_chat["session_id"], fresh_talk["session_id"]):
            self.assertEqual(
                conversation.load_session(session_id, vault_root=self.vault)["status"],
                "closed",
            )
        telegram.assert_not_called()
        # The already-closed session is untouched (still closed with its
        # original reason).
        self.assertEqual(
            conversation.load_session(already_closed["session_id"],
                                      vault_root=self.vault)["close"]["reason"],
            "done",
        )

        # Idempotent: nothing left open, a second pass closes nothing.
        self.assertEqual(engine.find_open_sessions(vault_root=self.vault), [])
        self.assertEqual(
            engine.close_all_open_sessions(
                vault_root=self.vault, state_path=self.state_path,
                scores_path=self.scores_path, candidates_path=self.candidates_path,
            ),
            [],
        )

    def test_takeaway_rule_honored_two_plus_user_turns_earns_a_close_message(self):
        self.run_turn(answer_text=ANSWER)
        self.run_turn(answer_text=SECOND_ANSWER)
        session_id = self.only_session()["session_id"]

        outcomes = engine.close_all_open_sessions(
            vault_root=self.vault,
            state_path=self.state_path,
            scores_path=self.scores_path,
            candidates_path=self.candidates_path,
            status_resolver=ready_status,
            ai_call=lambda _p, _m: json.dumps({"message": CLOSING_MESSAGE}),
            telegram_send=self._send(),
            prompt_builder=lambda payload: "SYNTHETIC CLOSING PROMPT",
        )

        self.assertEqual(len(outcomes), 1)
        self.assertEqual(outcomes[0].reason, "day_rollover")
        self.assertTrue(outcomes[0].takeaway_delivered)
        self.assertEqual(self.sent[-1], CLOSING_MESSAGE)
        session = conversation.load_session(session_id, vault_root=self.vault)
        self.assertEqual(session["close"]["reason"], "day_rollover")
        self.assertEqual(session["close"]["takeaway"], CLOSING_MESSAGE)
        self.assertTrue(session["close"]["takeaway_delivered"])

    def test_below_the_takeaway_threshold_closes_silently(self):
        self.run_turn()  # one answer only
        session_id = self.only_session()["session_id"]
        telegram = mock.Mock(side_effect=AssertionError("no-nag"))

        outcomes = engine.close_all_open_sessions(
            vault_root=self.vault,
            state_path=self.state_path,
            scores_path=self.scores_path,
            candidates_path=self.candidates_path,
            status_resolver=ready_status,
            telegram_send=telegram,
        )

        self.assertEqual(len(outcomes), 1)
        self.assertTrue(outcomes[0].silent)
        self.assertFalse(outcomes[0].takeaway_delivered)
        telegram.assert_not_called()
        session = conversation.load_session(session_id, vault_root=self.vault)
        self.assertEqual(session["close"]["reason"], "day_rollover")
        self.assertEqual(session["close"]["takeaway"], "")


class PrivacyTests(EngineTestCase):
    def test_metadata_only_ledger_and_diagnostics(self):
        diagnostics = []
        self.diagnostic.side_effect = lambda *a, **k: diagnostics.append((a, k))
        self.run_turn(ai_call=self._ai(error=AIUnavailableError(ANSWER)))
        self.run_turn(answer_text=SECOND_ANSWER)

        serialized = json.dumps(diagnostics) + self.state_path.read_text(encoding="utf-8")
        for private in (ANSWER, SECOND_ANSWER, QUESTION, TURN_MESSAGE, FOLLOWUP_TEXT,
                        "SYNTHETIC TURN PROMPT"):
            self.assertNotIn(private, serialized)
        self.assertIn(QUESTION_ID, serialized)


class RuntimeLintSourceTests(EngineTestCase):
    def test_length_cap_is_sourced_from_lints_yaml_not_pinned_here(self):
        source = (SYSTEM / "conversation_delivery.py").read_text(encoding="utf-8")
        self.assertNotIn("1200", source)
        config = engine._lints_config()
        self.assertEqual(config["cap.turn_chars"], 1200)
        blocking, _ = engine.lint_outgoing("x" * 1201, question_allowed=False, config=config)
        self.assertIn("length_caps", blocking)

    def test_advisory_lints_do_not_block_the_send(self):
        # A closed (yes/no) question is a question_grammar_audit finding —
        # advisory, so the turn still goes out and the count is ledgered.
        outcome = self.run_turn(ai_call=self._ai(response=turn_json(
            message='Diesel and cut hay. Was "the north field" the one by the road?',
        )))
        self.assertEqual(outcome.status, "confirmed")
        entry = self.entries()[engine.turn_key(self.only_session()["session_id"], 1)]
        self.assertGreaterEqual(entry["advisory_lints"], 1)


class RetryTests(EngineTestCase):
    def test_turn_retry_requires_confirmation_for_ambiguous(self):
        self.run_turn(telegram_send=self._send(ambiguous_send))
        session_id = self.only_session()["session_id"]

        blocked = engine.retry_turn(
            session_id, 1,
            state_path=self.state_path, vault_root=self.vault,
            status_resolver=ready_status,
            ai_call=mock.Mock(side_effect=AssertionError("blind retry")),
            telegram_send=mock.Mock(side_effect=AssertionError("blind retry")),
        )
        self.assertEqual((blocked.status, blocked.reason), ("ambiguous", "ambiguous_not_retried"))

        retried = engine.retry_turn(
            session_id, 1,
            confirm_not_sent=True,
            state_path=self.state_path, vault_root=self.vault,
            status_resolver=ready_status,
            ai_call=self._ai(response=turn_json(message="Diesel and cut hay, still with me.",
                                                followup=None)),
            telegram_send=self._send(),
        )
        self.assertEqual(retried.status, "confirmed")
        self.assertEqual(self.fallbacks, [])  # an operator retry never sends an ack


if __name__ == "__main__":
    unittest.main()
