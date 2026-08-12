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
import re
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
