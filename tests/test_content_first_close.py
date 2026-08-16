"""ADR 0015 / issue #167 — content-first close: the builder reads the
conversation; starved closes refuse.

Root cause (docs/pr-specs/content-first-close.md): ``build_closing_prompt``
read only ``mode`` + ``rolling_summary`` — never the conversation itself.
Two live incidents in two days: a confabulated close (#163) and, after
#163's format fix, an honest-but-empty close delivered to a person who had
just written a long message. This module covers the contract's own test
plan: the builder includes the FINAL USER TURN verbatim, never truncated,
regardless of length or budget; earlier turns respect
``budget.closing_transcript``, oldest dropped first; ``rolling_summary`` is
included when non-empty; a starved builder (no user turns, no non-empty
summary) RAISES; the engine's degradation table holds for both call
classes (a live/budget-reached closing beat falls back to an ordinary
turn; a sweep/idle/day close degrades to silence); the new
``closing_engages_final_message`` golden property checker; the
respond-first instruction is present in the prompt.

Synthetic data only — NEVER ~/Workspace/dave (repo boundary, CLAUDE.md).
"""

from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SYSTEM = ROOT / "system"
sys.path.insert(0, str(SYSTEM))
sys.path.insert(0, str(ROOT / "tests"))

from tempdirs import root_parent_tmp  # noqa: E402
import conversation  # noqa: E402
import conversation_delivery as engine  # noqa: E402
import interaction_evals as ie  # noqa: E402
import lifehug_core as core  # noqa: E402
from ai_provider import ProviderStatus  # noqa: E402

GOLDENS_DIR = ROOT / "interactions" / "conversation" / "evals" / "goldens"
SEATTLE_GOLDEN = GOLDENS_DIR / "chat-seattle-ferry-closing.json"


def ready_status(*_args, **_kwargs):
    return ProviderStatus("local-openai", "synthetic-model", True, "synthetic")


def _turn(role: str, text: str) -> dict:
    return {"role": role, "text": text, "channel": "telegram"}


def _turn_json(message: str) -> str:
    return json.dumps({
        "message": message,
        "followup_question": None,
        "question_free": True,
        "rolling_summary": "",
        "insight_receipts": 0,
        "extracted": {"facts": [], "entities": [], "candidate_ideas": [], "mirror_responses": []},
    })


def _closing_json(takeaway_prose: str, hook: str | None = None) -> str:
    return json.dumps({"takeaway_prose": takeaway_prose, "hook": hook})


# --------------------------------------------------------------------------
# Scope 1 — the builder reads the conversation.
# --------------------------------------------------------------------------


class BuildClosingPromptTranscriptTests(unittest.TestCase):
    def test_final_user_turn_is_verbatim_and_never_truncated(self):
        long_message = "This is a very long final message. " * 200  # ~7400 chars
        session = {
            "mode": "chat",
            "rolling_summary": "",
            "turns": [_turn("user", long_message)],
        }
        # A tiny budget — if the final turn were subject to it, it would be
        # truncated away entirely.
        manifest = {"budget.closing_transcript": 10}
        with mock.patch.object(conversation, "_safe_manifest", return_value=manifest):
            prompt = conversation.build_closing_prompt({"session": session})
        self.assertIn(long_message, prompt)

    def test_respects_budget_closing_transcript_oldest_dropped_first(self):
        turns = [
            _turn("lifehug", "OPENER_LINE_ONE that is reasonably long on its own."),
            _turn("user", "OLDEST_USER_LINE from the very start of this session."),
            _turn("lifehug", "MIDDLE_LIFEHUG_LINE responding to that opening message."),
            _turn("user", "NEWEST_PRECEDING_LINE right before the final message."),
            _turn("user", "FINAL_MESSAGE — the reason a reply is owed."),
        ]
        session = {"mode": "chat", "rolling_summary": "", "turns": turns}
        # A budget wide enough for exactly one preceding line (~60 chars ->
        # ~15 tokens at CHARS_PER_TOKEN=4), not all three.
        manifest = {"budget.closing_transcript": 15}
        with mock.patch.object(conversation, "_safe_manifest", return_value=manifest):
            prompt = conversation.build_closing_prompt({"session": session})
        self.assertIn("FINAL_MESSAGE", prompt)  # never dropped
        self.assertIn("NEWEST_PRECEDING_LINE", prompt)  # most recent preceding turn survives
        self.assertNotIn("OLDEST_USER_LINE", prompt)  # oldest yields first
        self.assertNotIn("OPENER_LINE_ONE", prompt)  # oldest yields first

    def test_default_budget_used_when_manifest_key_absent(self):
        session = {
            "mode": "chat",
            "rolling_summary": "",
            "turns": [
                _turn("user", "An earlier turn."),
                _turn("user", "The final turn."),
            ],
        }
        with mock.patch.object(conversation, "_safe_manifest", return_value={}):
            prompt = conversation.build_closing_prompt({"session": session})
        self.assertIn("An earlier turn.", prompt)
        self.assertIn("The final turn.", prompt)

    def test_includes_rolling_summary_when_present(self):
        session = {
            "mode": "chat",
            "rolling_summary": "Earlier context the recent window dropped.",
            "turns": [_turn("user", "The final message.")],
        }
        prompt = conversation.build_closing_prompt({"session": session})
        self.assertIn("Earlier context the recent window dropped.", prompt)

    def test_omits_rolling_summary_line_when_absent(self):
        session = {"mode": "chat", "rolling_summary": "", "turns": [_turn("user", "Hi.")]}
        prompt = conversation.build_closing_prompt({"session": session})
        self.assertNotIn("Rolling summary", prompt)

    def test_prompt_contains_the_respond_first_clause(self):
        session = {"mode": "chat", "rolling_summary": "", "turns": [_turn("user", "Hi there.")]}
        prompt = conversation.build_closing_prompt({"session": session})
        lowered = prompt.lower()
        self.assertIn("respond to the final message first", lowered)
        self.assertIn("defect", lowered)

    def test_final_message_appears_even_when_it_is_not_the_last_turn_role(self):
        # A trailing lifehug turn after the final user turn (rare, but the
        # index-search must find the LAST user-role turn, not just turns[-1]).
        turns = [
            _turn("user", "First user turn."),
            _turn("lifehug", "A reply."),
            _turn("user", "THE_ACTUAL_FINAL_USER_TURN."),
        ]
        session = {"mode": "chat", "rolling_summary": "", "turns": turns}
        prompt = conversation.build_closing_prompt({"session": session})
        self.assertIn("THE_ACTUAL_FINAL_USER_TURN.", prompt)


class BuildClosingPromptStarvationTests(unittest.TestCase):
    def test_raises_on_no_user_turns_and_no_summary(self):
        session = {"mode": "chat", "rolling_summary": "", "turns": []}
        with self.assertRaises(conversation.ConversationPromptError):
            conversation.build_closing_prompt({"session": session})

    def test_raises_when_turns_key_is_entirely_absent(self):
        session = {"mode": "chat", "rolling_summary": ""}
        with self.assertRaises(conversation.ConversationPromptError):
            conversation.build_closing_prompt({"session": session})

    def test_raises_when_only_lifehug_turns_exist(self):
        session = {
            "mode": "chat",
            "rolling_summary": "",
            "turns": [_turn("lifehug", "A lifehug-only turn, no user turn at all.")],
        }
        with self.assertRaises(conversation.ConversationPromptError):
            conversation.build_closing_prompt({"session": session})

    def test_does_not_raise_when_rolling_summary_alone_is_present(self):
        session = {"mode": "chat", "rolling_summary": "Some earlier context.", "turns": []}
        prompt = conversation.build_closing_prompt({"session": session})
        self.assertIn("takeaway_prose", prompt)

    def test_does_not_raise_when_a_user_turn_alone_is_present(self):
        session = {"mode": "chat", "rolling_summary": "", "turns": [_turn("user", "Hi.")]}
        prompt = conversation.build_closing_prompt({"session": session})
        self.assertIn("takeaway_prose", prompt)

    def test_error_is_a_conversation_error_family_member(self):
        self.assertTrue(issubclass(conversation.ConversationPromptError, conversation.ConversationError))

    def test_closing_prompt_cli_refuses_cleanly_on_an_empty_session(self):
        payload = {"session": {"mode": "chat", "rolling_summary": "", "turns": []}}
        result = subprocess.run(
            [sys.executable, str(SYSTEM / "conversation.py"), "closing-prompt"],
            input=json.dumps(payload),
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout, "")
        self.assertEqual(len(result.stderr.strip().splitlines()), 1)
        self.assertIn("Error:", result.stderr)


# --------------------------------------------------------------------------
# Scope 2 — the starvation guard's engine degradation, both call classes.
# --------------------------------------------------------------------------


class EngineDegradationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = root_parent_tmp(self, ROOT, prefix="lifehug-v178-content-first-close-")
        self.vault = self.tmp / "vault"
        self.vault.mkdir()
        self.state_path = self.tmp / "conversation_deliveries.json"
        self.sent: list[str] = []
        diagnostics = mock.patch.object(engine, "record_learning_failure")
        self.diagnostic = diagnostics.start()
        self.addCleanup(diagnostics.stop)

    def _send(self):
        def send(message):
            self.sent.append(message)
            return core.TelegramSendResult("confirmed", "telegram_confirmed", 1, 1)
        return send

    def _starved_session(self) -> dict:
        """A genuinely empty session: no user turns, no rolling summary —
        exactly the starvation guard's own criterion."""
        return conversation.open_session("chat", "telegram", vault_root=self.vault)

    def test_budget_beat_degradation_falls_back_to_an_ordinary_turn(self):
        session = self._starved_session()
        session_id = session["session_id"]
        fallback_message = "Whatever's on your mind, I'm here for it."

        status, detail, takeaway, hook = engine._deliver_closing(
            session,
            state_path=self.state_path,
            channel="telegram",
            ai_call=lambda _p, _m: _turn_json(fallback_message),
            telegram_send=self._send(),
            status_resolver=ready_status,
            prompt_builder=None,  # the REAL conversation.build_closing_prompt
            vault_root=self.vault,
            close_reason="done",  # a live, budget-reached closing beat
        )

        self.assertEqual(status, engine.STATUS_SKIPPED)
        self.assertEqual(detail, "starved_fallback_turn")
        self.assertEqual(takeaway, "")
        self.assertIsNone(hook)
        # The person gets a REAL reply — never silence on a present person.
        self.assertEqual(self.sent, [fallback_message])
        reloaded = conversation.load_session(session_id, vault_root=self.vault)
        self.assertEqual(len(reloaded["turns"]), 1)
        self.assertEqual(reloaded["turns"][0]["role"], "lifehug")
        self.assertEqual(reloaded["turns"][0]["text"], fallback_message)
        # The close itself never happened — "the thread lands another day."
        self.assertEqual(reloaded["status"], "open")

    def test_budget_beat_class_covers_exit_taken_too(self):
        session = self._starved_session()
        status, detail, _takeaway, _hook = engine._deliver_closing(
            session,
            state_path=self.state_path,
            channel="telegram",
            ai_call=lambda _p, _m: _turn_json("A gentle, question-free reply."),
            telegram_send=self._send(),
            status_resolver=ready_status,
            prompt_builder=None,
            vault_root=self.vault,
            close_reason="exit_taken",
        )
        self.assertEqual((status, detail), (engine.STATUS_SKIPPED, "starved_fallback_turn"))

    def test_sweep_close_degradation_is_silence(self):
        session = self._starved_session()
        session_id = session["session_id"]
        ai_call = mock.Mock(side_effect=AssertionError("no generation on a starved sweep close"))
        telegram = mock.Mock(side_effect=AssertionError("no-nag: nothing may be sent"))

        status, detail, takeaway, hook = engine._deliver_closing(
            session,
            state_path=self.state_path,
            channel="telegram",
            ai_call=ai_call,
            telegram_send=telegram,
            status_resolver=ready_status,
            prompt_builder=None,
            vault_root=self.vault,
            close_reason="idle_timeout",  # a sweep close
        )

        self.assertEqual(status, engine.STATUS_FAILED)
        self.assertEqual(detail, "starved_no_content")
        self.assertEqual(takeaway, "")
        self.assertIsNone(hook)
        self.assertEqual(self.sent, [])
        telegram.assert_not_called()
        reloaded = conversation.load_session(session_id, vault_root=self.vault)
        self.assertEqual(reloaded["status"], "open")  # _deliver_closing never closes; the caller does

    def test_day_rollover_is_also_a_sweep_class_reason(self):
        session = self._starved_session()
        status, detail, _takeaway, _hook = engine._deliver_closing(
            session,
            state_path=self.state_path,
            channel="telegram",
            ai_call=mock.Mock(side_effect=AssertionError("no generation")),
            telegram_send=mock.Mock(side_effect=AssertionError("no send")),
            status_resolver=ready_status,
            prompt_builder=None,
            vault_root=self.vault,
            close_reason="day_rollover",
        )
        self.assertEqual((status, detail), (engine.STATUS_FAILED, "starved_no_content"))

    def test_close_session_now_leaves_the_session_open_on_a_starved_fallback_turn(self):
        # close_session_now's own >= 2 user-turns gate means a genuinely
        # starved session can never reach _deliver_closing through it in
        # practice — this proves the WIRING close_session_now added on top
        # of _deliver_closing's return value: when a fallback-turn
        # degradation happens, the close is deferred, not forced through.
        session = conversation.open_session("chat", "telegram", vault_root=self.vault)
        session_id = session["session_id"]
        conversation.append_turn(
            session_id, _turn("user", "First answer."), expected_turns=0, vault_root=self.vault,
        )
        conversation.append_turn(
            session_id, _turn("user", "Second answer."), expected_turns=1, vault_root=self.vault,
        )

        with mock.patch.object(
            engine, "_deliver_closing",
            return_value=(engine.STATUS_SKIPPED, "starved_fallback_turn", "", None),
        ):
            outcome = engine.close_session_now(
                session_id,
                reason="done",
                state_path=self.state_path,
                vault_root=self.vault,
                status_resolver=ready_status,
                telegram_send=self._send(),
            )

        self.assertFalse(outcome.takeaway_delivered)
        self.assertFalse(outcome.silent)  # not a silent no-nag either — a real reply went out
        self.assertEqual(outcome.detail, "starved_fallback_turn")
        reloaded = conversation.load_session(session_id, vault_root=self.vault)
        self.assertEqual(reloaded["status"], "open")
        self.assertNotIn("close", reloaded)


# --------------------------------------------------------------------------
# Scope 4 — the closing_engages_final_message golden property.
# --------------------------------------------------------------------------


def _minimal_golden(final_user_text: str, closing_text: str) -> dict:
    return {
        "golden_id": "synthetic-engages-final-message-test",
        "mode": "chat",
        "register": "neutral",
        "arc": {"question_id": "Z1", "opening": "opening", "intents": []},
        "turns": [
            {"role": "user", "text": final_user_text},
            {
                "role": "lifehug",
                "text": closing_text,
                "annotations": {
                    "kind": "closing",
                    "properties": ["closing_engages_final_message"],
                },
            },
        ],
    }


class ClosingEngagesFinalMessagePropertyTests(unittest.TestCase):
    def test_property_id_is_in_the_closed_vocabulary(self):
        self.assertIn("closing_engages_final_message", ie.PROPERTY_IDS)

    def test_passes_when_the_closing_turn_shares_a_distinctive_token(self):
        golden = _minimal_golden(
            "We drove up to the lighthouse at Fairweather Point every August.",
            "That drive up to the lighthouse at Fairweather Point sounds like a real tradition.",
        )
        self.assertEqual(ie._check_closing_engages_final_message(golden), [])

    def test_fails_when_the_closing_turn_shares_no_distinctive_token(self):
        golden = _minimal_golden(
            "We drove up to the lighthouse at Fairweather Point every August.",
            "Thanks so much for sharing that with me today.",
        )
        errors = ie._check_closing_engages_final_message(golden)
        self.assertTrue(errors)
        self.assertIn("shares no distinctive content token", errors[0])

    def test_fails_when_declared_on_a_non_closing_turn(self):
        golden = _minimal_golden(
            "We drove up to the lighthouse at Fairweather Point every August.",
            "That lighthouse sounds lovely.",
        )
        golden["turns"][1]["annotations"]["kind"] = "receipt"
        errors = ie._check_closing_engages_final_message(golden)
        self.assertTrue(any("requires kind == 'closing'" in e for e in errors))

    def test_the_committed_seattle_golden_passes_full_check_golden(self):
        data = json.loads(SEATTLE_GOLDEN.read_text(encoding="utf-8"))
        self.assertEqual(ie.check_golden(data), [])

    def test_the_committed_seattle_golden_is_swept_and_declares_the_property(self):
        golden_ids = {g.get("golden_id") for g in ie.load_goldens()}
        self.assertIn("chat-seattle-ferry-closing-01", golden_ids)
        data = json.loads(SEATTLE_GOLDEN.read_text(encoding="utf-8"))
        closing = [
            t for t in data["turns"]
            if (t.get("annotations") or {}).get("kind") == "closing"
        ]
        self.assertEqual(len(closing), 1)
        self.assertIn("closing_engages_final_message", closing[0]["annotations"]["properties"])
        # The reproduced-incident shape: a long final user message.
        final_user = [t for t in data["turns"] if t["role"] == "user"][-1]
        self.assertGreater(len(final_user["text"]), 900)


if __name__ == "__main__":
    unittest.main()
