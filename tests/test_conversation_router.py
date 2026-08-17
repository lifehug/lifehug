"""v155 / issue #117 — the inbound router (`lifehug.py route`).

Wave 2 PR 4 of the Conversation Interaction build, Part B. Classifies one
inbound message into the five-intent contract
(`interactions/conversation/router/router.md`) via the cheap router model,
falling back to a deterministic default on a not-ready provider, a
below-threshold classification, or malformed model output. Read-only:
`route_message` never mutates rotation, session, or candidate state.

Every collaborator is injected (`ai_call` / `status_resolver` /
`prompt_builder` / `rotation` / `open_session`); the file-mutation guard
test points `vault_root` at a synthetic temp tree built through
tests/tempdirs.py. Synthetic data only — NEVER ~/Workspace/dave.

Subtest names are the contract's own list (state-machine-shaped change ->
named explicitly, v130/v131 precedent).
"""

from __future__ import annotations

import json
import os
import re
import subprocess
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
from ai_provider import ProviderStatus  # noqa: E402

OPEN_SESSION = {
    "session_id": "conv-20260811-090000-abcdef",
    "mode": "conversation",
    "channel": "telegram",
    "status": "open",
    "turns": [],
}


def ready_status(*_args, **_kwargs):
    return ProviderStatus("local-openai", "synthetic-model", True, "synthetic")


def keyless_status(*_args, **_kwargs):
    return ProviderStatus("agent-task", "synthetic-model", False, "synthetic")


def router_json(intent, confidence):
    return json.dumps({"intent": intent, "confidence": confidence})


class FiveIntentTests(unittest.TestCase):
    """test_route_five_intents_from_model."""

    def _ai(self, intent, confidence, calls=None):
        def call(prompt, _model):
            if calls is not None:
                calls.append(prompt)
            return router_json(intent, confidence)

        return call

    def test_route_five_intents_from_model(self):
        cases = [
            ("Yeah, that was back in 2003, right after we moved to the coast.",
             "answer", "file_answer", {"last_question_id": "A14"}, None),
            ("Random memory just hit me — my grandmother's kitchen smell.",
             "new_story", "ingest_story", {}, None),
            ("show coverage", "command", "handle_command", {}, None),
            ("Oh also, I forgot to mention —",
             "continue_session", "continue_session", {}, OPEN_SESSION),
            ("what's the capital of Peru?", "out_of_scope", "deflect", {}, None),
        ]
        for text, intent, action, rotation, session in cases:
            with self.subTest(intent=intent):
                result = engine.route_message(
                    text,
                    channel="telegram",
                    ai_call=self._ai(intent, 0.95),
                    status_resolver=ready_status,
                    rotation=rotation,
                    open_session=session,
                )
                self.assertEqual(result["intent"], intent)
                self.assertEqual(result["action"], action)
                self.assertEqual(result["source"], "model")
                self.assertAlmostEqual(result["confidence"], 0.95)
                self.assertEqual(
                    result["pending_question_id"], rotation.get("last_question_id")
                )
                self.assertEqual(
                    result["open_session_id"],
                    session["session_id"] if session else None,
                )

    def test_action_mapping_is_fixed_per_intent(self):
        expected = {
            "answer": "file_answer",
            "new_story": "ingest_story",
            "command": "handle_command",
            "continue_session": "continue_session",
            "out_of_scope": "deflect",
        }
        for intent, action in expected.items():
            with self.subTest(intent=intent):
                result = engine.route_message(
                    "irrelevant text",
                    ai_call=self._ai(intent, 0.99),
                    status_resolver=ready_status,
                    rotation={},
                    open_session=None,
                )
                self.assertEqual(result["action"], action)


class ThresholdAndDefaultTests(unittest.TestCase):
    def test_route_threshold_falls_to_default(self):
        # Low confidence, but a pending question exists — the default rule
        # wins over the model's (unreliable) classification.
        result = engine.route_message(
            "hmm not sure what this is",
            ai_call=lambda *_a, **_k: router_json("out_of_scope", 0.4),
            status_resolver=ready_status,
            rotation={"last_question_id": "A14"},
            open_session=None,
        )
        self.assertEqual(result["source"], "default")
        self.assertEqual(result["intent"], "answer")
        self.assertEqual(result["action"], "file_answer")
        self.assertEqual(result["pending_question_id"], "A14")

    def test_route_keyless_deterministic_default(self):
        ai = mock.Mock(side_effect=AssertionError("keyless must never call the model"))

        # Pending question -> answer.
        pending = engine.route_message(
            "some reply", ai_call=ai, status_resolver=keyless_status,
            rotation={"last_question_id": "A14"}, open_session=None,
        )
        self.assertEqual((pending["source"], pending["intent"], pending["action"]),
                         ("default", "answer", "file_answer"))

        # No pending question, but a session is open -> continue_session.
        continuing = engine.route_message(
            "one more thing", ai_call=ai, status_resolver=keyless_status,
            rotation={}, open_session=OPEN_SESSION,
        )
        self.assertEqual((continuing["source"], continuing["intent"], continuing["action"]),
                         ("default", "continue_session", "continue_session"))

        # Neither -> ask_user (never blindly guessed as one of the five).
        neither = engine.route_message(
            "hello there", ai_call=ai, status_resolver=keyless_status,
            rotation={}, open_session=None,
        )
        self.assertEqual((neither["source"], neither["intent"], neither["action"]),
                         ("default", "new_story", "ask_user"))
        ai.assert_not_called()

    def test_route_malformed_model_output_defaults(self):
        diagnostics = []
        with mock.patch.object(
            engine, "record_learning_failure",
            side_effect=lambda *a, **k: diagnostics.append((a, k)),
        ):
            result = engine.route_message(
                "a private message the diagnostic must never echo",
                ai_call=lambda *_a, **_k: "I am not JSON at all.",
                status_resolver=ready_status,
                rotation={}, open_session=None,
            )
        self.assertEqual(result["source"], "default")
        self.assertEqual(result["action"], "ask_user")
        self.assertTrue(diagnostics)
        serialized = json.dumps(diagnostics)
        self.assertNotIn("a private message the diagnostic must never echo", serialized)
        self.assertNotIn("I am not JSON at all.", serialized)


class MutatesNothingTests(unittest.TestCase):
    def test_route_mutates_nothing(self):
        tmp = root_parent_tmp(self, ROOT, prefix="lifehug-v155-router-")
        vault = tmp / "vault"
        vault.mkdir()
        state_dir = vault / "state"
        state_dir.mkdir()
        rotation_path = state_dir / "rotation.json"
        rotation_path.write_text(
            json.dumps({"last_question_id": "A14", "awaiting_pass_transition": False}),
            encoding="utf-8",
        )
        candidates_path = state_dir / "question_candidates.json"
        candidates_path.write_text(json.dumps({"version": 1, "candidates": []}), encoding="utf-8")
        session = conversation.open_session("conversation", "telegram", vault_root=vault)

        before = {
            path.name: path.read_bytes()
            for path in (rotation_path, candidates_path)
        }
        before_sessions = conversation.list_sessions(vault_root=vault)

        engine.route_message(
            "here's a story about my grandfather's truck",
            channel="telegram",
            vault_root=vault,
            ai_call=lambda *_a, **_k: router_json("new_story", 0.9),
            status_resolver=ready_status,
        )

        after = {
            path.name: path.read_bytes()
            for path in (rotation_path, candidates_path)
        }
        self.assertEqual(before, after)
        self.assertEqual(before_sessions, conversation.list_sessions(vault_root=vault))
        # The session opened above is untouched (still zero turns, still open).
        reloaded = conversation.load_session(session["session_id"], vault_root=vault)
        self.assertEqual(reloaded["turns"], [])
        self.assertEqual(reloaded["status"], "open")


class ReplyAfterCloseTests(unittest.TestCase):
    """Issue #139, pure-chat wave, design K item 6: a reply arriving with
    no open session, on a channel whose last session closed, resumes that
    subject rather than guessing new_story. Synthetic vault, NEVER
    ~/Workspace/dave."""

    def _closed_session(self, tmp, *, last_activity):
        vault = tmp / "vault"
        vault.mkdir(exist_ok=True)
        session = conversation.open_session("chat", "telegram", vault_root=vault)
        session_id = session["session_id"]
        session = conversation.append_turn(
            session_id,
            {"role": "user", "text": "It was a whole summer of driving out to the lake.",
             "channel": "telegram"},
            expected_turns=0, vault_root=vault,
        )
        session = conversation.append_turn(
            session_id,
            {"role": "lifehug", "text": "That parking-lot steering wheel moment.",
             "channel": "telegram"},
            expected_turns=1, vault_root=vault,
        )
        session = conversation.append_turn(
            session_id,
            {"role": "user", "text": "Yeah, every Sunday.", "channel": "telegram",
             "ts": last_activity.strftime("%Y-%m-%dT%H:%M:%SZ")},
            expected_turns=2, vault_root=vault,
        )
        conversation.close_session(
            session_id,
            {"reason": "done", "takeaway": "The lake Sundays.", "takeaway_delivered": True,
             "insight_receipts_count": 1, "filed": []},
            vault_root=vault,
        )
        return vault, session_id

    def test_same_day_reply_overrides_confident_new_story_model_call(self):
        tmp = root_parent_tmp(self, ROOT, prefix="lifehug-v161-reply-after-close-")
        closed_at = datetime(2026, 8, 12, 9, 0, tzinfo=timezone.utc)
        vault, session_id = self._closed_session(tmp, last_activity=closed_at)
        same_day_later = closed_at + timedelta(hours=6)

        result = engine.route_message(
            "Actually there's more to that lake story.",
            channel="telegram",
            vault_root=vault,
            now=same_day_later,
            ai_call=lambda *_a, **_k: router_json("new_story", 0.97),
            status_resolver=ready_status,
            rotation={},
            open_session=None,
        )
        self.assertEqual(result["intent"], "continue_session")
        self.assertEqual(result["action"], "continue_session")
        self.assertEqual(result["reopen_session_id"], session_id)
        self.assertIsNone(result["open_session_id"])

    def test_later_reply_with_no_provider_resolves_to_continue_not_new_story(self):
        tmp = root_parent_tmp(self, ROOT, prefix="lifehug-v161-reply-after-close-")
        closed_at = datetime(2026, 6, 1, 9, 0, tzinfo=timezone.utc)
        vault, session_id = self._closed_session(tmp, last_activity=closed_at)
        much_later = closed_at + timedelta(days=40)
        ai = mock.Mock(side_effect=AssertionError("keyless must never call the model"))

        result = engine.route_message(
            "Actually there's more to that lake story.",
            channel="telegram",
            vault_root=vault,
            now=much_later,
            ai_call=ai,
            status_resolver=keyless_status,
            rotation={},
            open_session=None,
        )
        self.assertEqual((result["source"], result["intent"], result["action"]),
                         ("default", "continue_session", "continue_session"))
        self.assertEqual(result["reopen_session_id"], session_id)
        ai.assert_not_called()

    def test_recently_closed_does_not_override_out_of_scope_or_command(self):
        tmp = root_parent_tmp(self, ROOT, prefix="lifehug-v161-reply-after-close-")
        closed_at = datetime(2026, 8, 12, 9, 0, tzinfo=timezone.utc)
        vault, _session_id = self._closed_session(tmp, last_activity=closed_at)
        same_day_later = closed_at + timedelta(hours=1)

        for intent in ("out_of_scope", "command"):
            with self.subTest(intent=intent):
                result = engine.route_message(
                    "irrelevant text",
                    channel="telegram",
                    vault_root=vault,
                    now=same_day_later,
                    ai_call=lambda *_a, **_k: router_json(intent, 0.9),
                    status_resolver=ready_status,
                    rotation={},
                    open_session=None,
                )
                self.assertEqual(result["intent"], intent)

    def test_no_closed_session_leaves_terminal_fallback_unchanged(self):
        tmp = root_parent_tmp(self, ROOT, prefix="lifehug-v161-reply-after-close-")
        vault = tmp / "vault"
        vault.mkdir()
        ai = mock.Mock(side_effect=AssertionError("keyless must never call the model"))
        result = engine.route_message(
            "hello there", channel="telegram", vault_root=vault,
            ai_call=ai, status_resolver=keyless_status, rotation={}, open_session=None,
        )
        self.assertEqual((result["source"], result["intent"], result["action"]),
                         ("default", "new_story", "ask_user"))
        self.assertIsNone(result["reopen_session_id"])

    def test_reopen_then_close_again(self):
        """Integration scenario (issue #139 evals item): a subject closes,
        a same-day reply resumes it in a fresh seeded session (never
        appending to the closed doc — the store forbids that by design),
        and that new session closes again with its own declarative
        takeaway. Both closes pass the closing-declarative lint."""
        tmp = root_parent_tmp(self, ROOT, prefix="lifehug-v161-reopen-close-again-")
        closed_at = datetime(2026, 8, 12, 9, 0, tzinfo=timezone.utc)
        vault, first_session_id = self._closed_session(tmp, last_activity=closed_at)
        same_day_later = closed_at + timedelta(hours=3)

        routed = engine.route_message(
            "One more thing about that lake — I forgot the ducks.",
            channel="telegram",
            vault_root=vault,
            now=same_day_later,
            ai_call=lambda *_a, **_k: router_json("new_story", 0.9),
            status_resolver=ready_status,
            rotation={},
            open_session=None,
        )
        self.assertEqual(routed["action"], "continue_session")
        self.assertEqual(routed["reopen_session_id"], first_session_id)

        # The caller opens a FRESH session seeded from the closed subject
        # (never appends to first_session_id — SessionClosedError by design).
        second = conversation.open_session("chat", "telegram", vault_root=vault)
        second_id = second["session_id"]
        second = conversation.append_turn(
            second_id,
            {"role": "user", "text": "One more thing about that lake — I forgot the ducks.",
             "channel": "telegram"},
            expected_turns=0, vault_root=vault,
        )
        second = conversation.append_turn(
            second_id,
            {"role": "lifehug", "text": "The ducks that used to follow the dock.",
             "channel": "telegram"},
            expected_turns=1, vault_root=vault,
        )
        conversation.append_turn(
            second_id,
            {"role": "user", "text": "Every single Sunday, without fail.", "channel": "telegram"},
            expected_turns=2, vault_root=vault,
        )

        state_path = tmp / "conversation_deliveries.json"
        scores_path = tmp / "answer_scores.json"
        candidates_path = tmp / "question_candidates.json"
        sent: list[str] = []
        second_takeaway = "I'll keep this filed right next to the dock story and the ducks."

        def telegram_send(message):
            sent.append(message)
            return core.TelegramSendResult("confirmed", "telegram_confirmed", 1, 1)

        outcome = engine.close_session_now(
            second_id,
            state_path=state_path,
            vault_root=vault,
            scores_path=scores_path,
            candidates_path=candidates_path,
            status_resolver=ready_status,
            # ADR 0014 (issue #163): the closing model's structured shape.
            ai_call=lambda _p, _m: json.dumps(
                {"takeaway_prose": second_takeaway, "hook": "the ducks"}
            ),
            telegram_send=telegram_send,
            prompt_builder=lambda payload: "SYNTHETIC CLOSING PROMPT",
        )
        # Both closes (the original and this reopened-then-closed-again
        # one) are declarative — no trailing question, no banned meta-phrase.
        self.assertTrue(outcome.takeaway_delivered)
        self.assertEqual(sent, [second_takeaway])
        blocking, _advisory = engine.lint_outgoing(
            second_takeaway, question_allowed=False, is_closing=True,
        )
        self.assertEqual(blocking, [])
        first_close_blocking, _ = engine.lint_outgoing(
            "The lake Sundays.", question_allowed=False, is_closing=True,
        )
        self.assertEqual(first_close_blocking, [])

        first = conversation.load_session(first_session_id, vault_root=vault)
        self.assertEqual(first["close"]["reason"], "done")
        second_doc = conversation.load_session(second_id, vault_root=vault)
        self.assertEqual(second_doc["status"], "closed")
        self.assertNotEqual(first_session_id, second_id)


def router_json_with_target(intent, confidence, target):
    return json.dumps({"intent": intent, "confidence": confidence, "target": target})


ROSTER = [
    {"id": "thread-a", "question": "Who built it?", "last_exchange": "user: no idea", "awaiting_ask": True},
    {"id": "thread-b", "question": "What was the trip like?", "last_exchange": "user: long", "awaiting_ask": False},
]


class ThreadBinderTests(unittest.TestCase):
    """issue #169 / ADR 0017 — the thread binder: additive `threads` in,
    `target` out. OSS's single-open-session model has nothing to bind
    multiple candidates INTO yet, so this is a pass-through: `target` is
    reported, never consumed to redirect routing (ADR 0017)."""

    def test_no_threads_target_is_always_none(self):
        result = engine.route_message(
            "irrelevant text",
            ai_call=lambda *_a, **_k: router_json("answer", 0.95),
            status_resolver=ready_status,
            rotation={"last_question_id": "A14"},
            open_session=None,
        )
        self.assertIsNone(result["target"])

    def test_threads_present_model_target_passes_through(self):
        result = engine.route_message(
            "It was my uncle who built it.",
            ai_call=lambda *_a, **_k: router_json_with_target("answer", 0.95, "thread-a"),
            status_resolver=ready_status,
            rotation={"last_question_id": "A14"},
            open_session=None,
            threads=ROSTER,
        )
        self.assertEqual(result["target"], "thread-a")
        self.assertEqual(result["intent"], "answer")

    def test_target_new_passes_through(self):
        result = engine.route_message(
            "Something totally different happened today.",
            ai_call=lambda *_a, **_k: router_json_with_target("new_story", 0.95, "new"),
            status_resolver=ready_status,
            rotation={},
            open_session=None,
            threads=ROSTER,
        )
        self.assertEqual(result["target"], "new")

    def test_out_of_roster_target_becomes_none_intent_kept(self):
        result = engine.route_message(
            "It was my uncle who built it.",
            ai_call=lambda *_a, **_k: router_json_with_target("answer", 0.95, "hallucinated-id"),
            status_resolver=ready_status,
            rotation={"last_question_id": "A14"},
            open_session=None,
            threads=ROSTER,
        )
        self.assertIsNone(result["target"])
        self.assertEqual(result["intent"], "answer")  # never discarded for an invalid target

    def test_target_present_but_no_threads_given_is_ignored(self):
        """A model hallucinating a target with no roster in the prompt at
        all — there was nothing to bind against, so target is null
        regardless of what the (malformed, off-contract) reply says."""
        result = engine.route_message(
            "irrelevant text",
            ai_call=lambda *_a, **_k: router_json_with_target("answer", 0.95, "thread-a"),
            status_resolver=ready_status,
            rotation={"last_question_id": "A14"},
            open_session=None,
        )
        self.assertIsNone(result["target"])

    def test_below_threshold_fallback_target_is_none_even_with_threads(self):
        result = engine.route_message(
            "hmm not sure what this is",
            ai_call=lambda *_a, **_k: router_json_with_target("out_of_scope", 0.4, "thread-a"),
            status_resolver=ready_status,
            rotation={"last_question_id": "A14"},
            open_session=None,
            threads=ROSTER,
        )
        self.assertEqual(result["source"], "default")
        self.assertIsNone(result["target"])

    def test_keyless_default_path_never_calls_model_target_is_none(self):
        ai = mock.Mock(side_effect=AssertionError("keyless must never call the model"))
        result = engine.route_message(
            "some reply", ai_call=ai, status_resolver=keyless_status,
            rotation={"last_question_id": "A14"}, open_session=None, threads=ROSTER,
        )
        self.assertIsNone(result["target"])
        ai.assert_not_called()

    def test_threads_reach_the_prompt_builder(self):
        captured = {}

        def capturing_builder(payload):
            captured.update(payload)
            return "SYNTHETIC PROMPT"

        engine.route_message(
            "It was my uncle who built it.",
            ai_call=lambda *_a, **_k: router_json_with_target("answer", 0.95, "thread-a"),
            status_resolver=ready_status,
            prompt_builder=capturing_builder,
            rotation={"last_question_id": "A14"},
            open_session=None,
            threads=ROSTER,
        )
        self.assertEqual(captured.get("threads"), ROSTER)

    def test_absent_threads_never_added_to_prompt_payload(self):
        """Contract, Scope 1: absent/empty threads keeps the payload the
        prompt builder sees exactly as it was pre-#169."""
        captured = {}

        def capturing_builder(payload):
            captured.update(payload)
            return "SYNTHETIC PROMPT"

        engine.route_message(
            "irrelevant text",
            ai_call=lambda *_a, **_k: router_json("answer", 0.95),
            status_resolver=ready_status,
            prompt_builder=capturing_builder,
            rotation={"last_question_id": "A14"},
            open_session=None,
        )
        self.assertNotIn("threads", captured)


class ParseRouterOutputTests(unittest.TestCase):
    """issue #169 / ADR 0017 — _parse_router_output's target strictness."""

    def test_target_absent_defaults_to_none(self):
        parsed = engine._parse_router_output(
            router_json("answer", 0.9), valid_targets=frozenset({"thread-a"})
        )
        self.assertEqual(parsed, ("answer", 0.9, None))

    def test_valid_target_kept(self):
        parsed = engine._parse_router_output(
            router_json_with_target("answer", 0.9, "thread-a"),
            valid_targets=frozenset({"thread-a", "thread-b"}),
        )
        self.assertEqual(parsed, ("answer", 0.9, "thread-a"))

    def test_literal_new_always_valid(self):
        parsed = engine._parse_router_output(
            router_json_with_target("new_story", 0.9, "new"),
            valid_targets=frozenset({"thread-a"}),
        )
        self.assertEqual(parsed, ("new_story", 0.9, "new"))

    def test_out_of_roster_target_becomes_none(self):
        parsed = engine._parse_router_output(
            router_json_with_target("answer", 0.9, "not-in-roster"),
            valid_targets=frozenset({"thread-a"}),
        )
        self.assertEqual(parsed, ("answer", 0.9, None))

    def test_non_string_target_becomes_none(self):
        parsed = engine._parse_router_output(
            router_json_with_target("answer", 0.9, 7),
            valid_targets=frozenset({"thread-a"}),
        )
        self.assertEqual(parsed, ("answer", 0.9, None))

    def test_no_valid_targets_forces_none_even_if_model_returns_one(self):
        parsed = engine._parse_router_output(
            router_json_with_target("answer", 0.9, "thread-a"), valid_targets=None
        )
        self.assertEqual(parsed, ("answer", 0.9, None))

    def test_invalid_target_never_discards_the_intent(self):
        parsed = engine._parse_router_output(
            router_json_with_target("command", 0.88, "nonsense"),
            valid_targets=frozenset({"thread-a"}),
        )
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed[0], "command")


QUESTION_BANK = """# Synthetic Lifehug questions

## A: Origins
- [ ] A1: What is your earliest synthetic memory?
"""


def _make_minimal_vault(root: Path) -> Path:
    """Minimal on-disk vault (question bank + rotation/coverage state) —
    matches tests/test_conversation_close.py's own ``make_vault`` shape,
    the established precedent for driving ``lifehug.py`` via subprocess
    against a synthetic ``LIFEHUG_VAULT_ROOT``."""
    root.mkdir(parents=True)
    state = root / "state"
    state.mkdir()
    (root / "question-bank.md").write_text(QUESTION_BANK, encoding="utf-8")
    (state / "rotation.json").write_text(json.dumps({
        "version": 1,
        "current_pass": 1,
        "pass_names": ["skeleton"],
        "last_question_id": None,
        "last_asked_at": None,
        "questions_asked": 0,
        "questions_answered": 0,
        "next_question_id": None,
        "focus_frequency": 4,
    }, indent=2) + "\n", encoding="utf-8")
    (state / "coverage.json").write_text(json.dumps({
        "version": 1,
        "last_updated": None,
        "categories": {"A": {"total": 1, "answered": 0, "status": "red"}},
    }, indent=2) + "\n", encoding="utf-8")
    return root


class CmdRouteCliThreadsTests(unittest.TestCase):
    """issue #169 / ADR 0017 — `lifehug.py route`'s stdin JSON accepts an
    optional `threads` array and forwards it (CLI-level smoke test, no
    provider configured in this environment so it always resolves through
    the deterministic default — the point here is that the extra key
    parses and the `target` field is always present in the reply)."""

    def _run_route(self, tmp, stdin_payload: str):
        full_env = {**os.environ, "LIFEHUG_VAULT_ROOT": str(tmp)}
        return subprocess.run(
            [sys.executable, str(SYSTEM / "lifehug.py"), "route"],
            input=stdin_payload,
            capture_output=True,
            text=True,
            env=full_env,
        )

    def test_plain_text_stdin_still_works(self):
        tmp = root_parent_tmp(self, ROOT, prefix="lifehug-v169-route-cli-")
        vault = _make_minimal_vault(tmp / "vault")
        result = self._run_route(vault, "hello there")
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertIn("target", payload)
        self.assertIsNone(payload["target"])

    def test_json_stdin_with_threads_parses_and_target_key_present(self):
        tmp = root_parent_tmp(self, ROOT, prefix="lifehug-v169-route-cli-")
        vault = _make_minimal_vault(tmp / "vault")
        stdin_payload = json.dumps({
            "text": "It was my uncle who built it.",
            "channel": "cli",
            "threads": [
                {"id": "thread-a", "question": "Who built it?", "last_exchange": "x", "awaiting_ask": True},
            ],
        })
        result = self._run_route(vault, stdin_payload)
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertIn("target", payload)

    def test_empty_threads_list_is_treated_as_absent(self):
        tmp = root_parent_tmp(self, ROOT, prefix="lifehug-v169-route-cli-")
        vault = _make_minimal_vault(tmp / "vault")
        stdin_payload = json.dumps({"text": "hello there", "channel": "cli", "threads": []})
        result = self._run_route(vault, stdin_payload)
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertIsNone(payload["target"])


class ProseContractGuardTests(unittest.TestCase):
    """test_prose_contracts_name_five_intents — cheap drift tripwire."""

    INTENTS = ("answer", "new_story", "command", "continue_session", "out_of_scope")

    def test_prose_contracts_name_five_intents(self):
        for relative in ("CLAUDE.md", "AGENTS.md", "skill/SKILL.md"):
            path = ROOT / relative
            text = path.read_text(encoding="utf-8")
            with self.subTest(file=relative):
                for intent in self.INTENTS:
                    self.assertIn(intent, text, f"{relative} is missing intent {intent!r}")
                self.assertIn("lifehug.py route", text, f"{relative} is missing the route delegation")

    def test_deflection_rule_named_in_all_three(self):
        for relative in ("CLAUDE.md", "AGENTS.md", "skill/SKILL.md"):
            path = ROOT / relative
            text = path.read_text(encoding="utf-8")
            with self.subTest(file=relative):
                self.assertRegex(
                    text, re.compile(r"deflect", re.IGNORECASE),
                    f"{relative} is missing the deflection rule",
                )


if __name__ == "__main__":
    unittest.main()
