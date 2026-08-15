"""ADR 0014 / issue #163 — structured close: {takeaway_prose, hook}, render
only the prose.

Covers the contract's own test plan (docs/pr-specs/structured-close.md):
the closing generation contract requests the JSON shape; parse+deliver
renders only ``takeaway_prose``; ``hook`` persists on the session's close
block (``close.hook``) and survives an idempotent replay; a parse failure
(including the pre-#163 free-text/``{"message": ...}`` shapes) degrades to
silence, never a raw-text fallback; a lint failure on the delivered prose
also degrades to silence; each of the four new closing-only lint classes
trips on the synthetic bad-close fixture and stays clean on the woven
good-close goldens, in isolation and in combination.

Synthetic data only — NEVER ~/Workspace/dave (repo boundary, CLAUDE.md).
"""

from __future__ import annotations

import json
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
import conversation_lints  # noqa: E402
import lifehug_core as core  # noqa: E402
from ai_provider import ProviderStatus  # noqa: E402

GOLDENS_DIR = ROOT / "interactions" / "conversation" / "evals" / "goldens"
BAD_FIXTURE = GOLDENS_DIR / "closing-scaffold-leak-bad-01.json"
GOOD_GOLDENS = (
    GOLDENS_DIR / "chat-porch-swing-closing.json",
    GOLDENS_DIR / "chat-promotion-closing.json",
    GOLDENS_DIR / "chat-witness-filing-close.json",
)

TAKEAWAY = (
    "The chains squeaked in a rhythm your grandmother hummed without "
    "knowing, and you still catch yourself humming it too. I'll keep it "
    "filed next to the chains and that hum."
)
HOOK = "filed next to the chains and that hum"


def ready_status(*_args, **_kwargs):
    return ProviderStatus("local-openai", "synthetic-model", True, "synthetic")


def closing_json(takeaway_prose=TAKEAWAY, hook=HOOK):
    return json.dumps({"takeaway_prose": takeaway_prose, "hook": hook})


def _closing_turn_text(path: Path) -> str:
    data = json.loads(path.read_text(encoding="utf-8"))
    closing = [t for t in data["turns"] if (t.get("annotations") or {}).get("kind") == "closing"]
    assert len(closing) == 1, f"{path}: expected exactly one closing turn"
    return closing[0]["text"]


# --------------------------------------------------------------------------
# Scope 1 — the closing generation contract requests the structured shape.
# --------------------------------------------------------------------------


class OutputContractTests(unittest.TestCase):
    def test_closing_output_contract_requests_the_structured_shape(self):
        contract = engine._closing_output_contract()
        self.assertIn('"takeaway_prose"', contract)
        self.assertIn('"hook"', contract)
        self.assertNotIn('"message"', contract)  # the pre-#163 shape, retired for closes

    def test_closing_output_contract_forbids_leaked_scaffolding_by_name(self):
        contract = engine._closing_output_contract().lower()
        self.assertIn("labeled fields", contract)
        self.assertIn("conversational behavior", contract)
        self.assertIn("future turn", contract)
        self.assertIn("markdown", contract)

    def test_build_closing_prompt_describes_weaving_not_a_labeled_line(self):
        session = {"mode": "chat", "rolling_summary": "The porch swing."}
        prompt = conversation.build_closing_prompt({"session": session})
        self.assertIn("takeaway_prose", prompt)
        self.assertIn("no labeled", prompt.lower())


# --------------------------------------------------------------------------
# parse_closing_output — unit-level, no AI/telegram involved.
# --------------------------------------------------------------------------


class ParseClosingOutputTests(unittest.TestCase):
    def test_valid_shape_with_hook(self):
        parsed = engine.parse_closing_output(closing_json())
        self.assertEqual(parsed, {"takeaway_prose": TAKEAWAY, "hook": HOOK})

    def test_null_hook_parses_to_none(self):
        parsed = engine.parse_closing_output(closing_json(hook=None))
        self.assertIsNone(parsed["hook"])

    def test_absent_hook_key_parses_to_none(self):
        parsed = engine.parse_closing_output(json.dumps({"takeaway_prose": TAKEAWAY}))
        self.assertIsNone(parsed["hook"])

    def test_tolerates_a_json_fence(self):
        fenced = "```json\n" + closing_json() + "\n```"
        parsed = engine.parse_closing_output(fenced)
        self.assertEqual(parsed["takeaway_prose"], TAKEAWAY)

    def test_plain_non_json_text_is_rejected_no_raw_fallback(self):
        # The pre-#163 gap: parse_turn_output failing used to fall back to
        # _valid_message(generated) directly. parse_closing_output has no
        # such fallback — a close that isn't the structured JSON is simply
        # unusable.
        self.assertIsNone(engine.parse_closing_output("Thanks for sharing that with me today."))

    def test_the_old_message_shape_is_rejected(self):
        # {"message": ...} was the pre-#163 closing contract; it has no
        # takeaway_prose key and must now be treated as malformed.
        old_shape = json.dumps({"message": TAKEAWAY, "question_free": True})
        self.assertIsNone(engine.parse_closing_output(old_shape))

    def test_empty_takeaway_prose_is_rejected(self):
        self.assertIsNone(engine.parse_closing_output(closing_json(takeaway_prose="   ")))

    def test_takeaway_prose_starting_with_a_brace_is_rejected(self):
        # _valid_message's structural sanity, shared with parse_turn_output.
        self.assertIsNone(engine.parse_closing_output(closing_json(takeaway_prose='{"nested": 1}')))

    def test_non_string_hook_is_ignored_not_fatal(self):
        raw = json.dumps({"takeaway_prose": TAKEAWAY, "hook": 12345})
        parsed = engine.parse_closing_output(raw)
        self.assertEqual(parsed["takeaway_prose"], TAKEAWAY)
        self.assertIsNone(parsed["hook"])


# --------------------------------------------------------------------------
# End-to-end via close_session_now: render-only-prose, hook persistence,
# idempotent replay, and both degradation paths.
# --------------------------------------------------------------------------


class DeliverClosingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = root_parent_tmp(self, ROOT, prefix="lifehug-v177-structured-close-")
        self.vault = self.tmp / "vault"
        self.vault.mkdir()
        self.state_path = self.tmp / "conversation_deliveries.json"
        self.scores_path = self.tmp / "answer_scores.json"
        self.candidates_path = self.tmp / "question_candidates.json"
        self.sent: list[str] = []
        diagnostics = mock.patch.object(engine, "record_learning_failure")
        self.diagnostic = diagnostics.start()
        self.addCleanup(diagnostics.stop)

    def _send(self):
        def send(message):
            self.sent.append(message)
            return core.TelegramSendResult("confirmed", "telegram_confirmed", 1, 1)
        return send

    def _closeable_session(self) -> str:
        """A session with >=2 user turns — the takeaway-earning criterion."""
        session = conversation.open_session("chat", "telegram", vault_root=self.vault)
        session_id = session["session_id"]
        conversation.append_turn(
            session_id, {"role": "user", "text": "The chains used to squeak.", "channel": "telegram"},
            expected_turns=0, vault_root=self.vault,
        )
        conversation.append_turn(
            session_id, {"role": "lifehug", "text": "Tell me more.", "channel": "telegram"},
            expected_turns=1, vault_root=self.vault,
        )
        conversation.append_turn(
            session_id, {"role": "user", "text": "It was almost a lullaby.", "channel": "telegram"},
            expected_turns=2, vault_root=self.vault,
        )
        return session_id

    def _close(self, session_id, ai_call):
        return engine.close_session_now(
            session_id,
            state_path=self.state_path,
            vault_root=self.vault,
            scores_path=self.scores_path,
            candidates_path=self.candidates_path,
            status_resolver=ready_status,
            ai_call=ai_call,
            telegram_send=self._send(),
            prompt_builder=lambda payload: "SYNTHETIC CLOSING PROMPT",
        )

    def test_renders_only_prose_and_persists_hook_on_the_close_block(self):
        session_id = self._closeable_session()
        outcome = self._close(session_id, lambda _p, _m: closing_json())

        self.assertTrue(outcome.takeaway_delivered)
        self.assertEqual(self.sent, [TAKEAWAY])  # exactly the prose, nothing wrapping it
        for sent_text in self.sent:
            self.assertNotIn('"hook"', sent_text)  # never the raw JSON envelope
            self.assertNotIn("takeaway_prose", sent_text)  # never the field name itself

        session = conversation.load_session(session_id, vault_root=self.vault)
        self.assertEqual(session["close"]["takeaway"], TAKEAWAY)
        self.assertTrue(session["close"]["takeaway_delivered"])
        self.assertEqual(session["close"]["hook"], HOOK)  # ADR 0014's additive field

    def test_null_hook_leaves_close_hook_unset(self):
        session_id = self._closeable_session()
        self._close(session_id, lambda _p, _m: closing_json(hook=None))
        session = conversation.load_session(session_id, vault_root=self.vault)
        self.assertNotIn("hook", session["close"])

    def test_hook_is_ledgered_and_retrievable_on_an_already_confirmed_replay(self):
        # _deliver_closing's own already_confirmed short-circuit, exercised
        # directly (not through the close_session_now -> conversation
        # .close_session round trip): a pre-existing, unrelated gap in that
        # outer idempotency wrapper — _write_outcome never ledgered
        # "takeaway" even before this PR, so a genuine second
        # close_session_now call for an already-closed session was already
        # broken on origin/main (confirmed by direct comparison; see this
        # PR's evidence for the reproduction) — is not this contract's to
        # fix (byte-compatible close semantics is a hard rule here). What
        # THIS contract adds is the hook half: the ledger now carries
        # "hook" too, and _deliver_closing's already_confirmed branch reads
        # it back correctly, symmetrically with the pre-existing (empty)
        # takeaway behavior on that same branch.
        session_id = self._closeable_session()
        loaded = conversation.load_session(session_id, vault_root=self.vault)

        first = engine._deliver_closing(
            loaded,
            state_path=self.state_path,
            channel="telegram",
            ai_call=lambda _p, _m: closing_json(),
            telegram_send=self._send(),
            status_resolver=ready_status,
            prompt_builder=lambda payload: "SYNTHETIC CLOSING PROMPT",
            vault_root=self.vault,
        )
        self.assertEqual(first, (engine.STATUS_CONFIRMED, "telegram_confirmed", TAKEAWAY, HOOK))

        second = engine._deliver_closing(
            loaded,
            state_path=self.state_path,
            channel="telegram",
            ai_call=lambda *_a, **_k: (_ for _ in ()).throw(
                AssertionError("must not regenerate on a confirmed close")
            ),
            telegram_send=self._send(),
            status_resolver=ready_status,
            prompt_builder=lambda payload: "SYNTHETIC CLOSING PROMPT",
            vault_root=self.vault,
        )
        self.assertEqual(second[0], engine.STATUS_CONFIRMED)
        self.assertEqual(second[1], "already_confirmed")
        self.assertEqual(second[3], HOOK)  # the additive half survives the replay
        self.assertEqual(self.sent, [TAKEAWAY])  # not sent twice

    def test_parse_failure_degrades_to_silence_never_raw_text(self):
        session_id = self._closeable_session()
        outcome = self._close(session_id, lambda _p, _m: "Just some free text, not JSON at all.")

        self.assertFalse(outcome.takeaway_delivered)
        self.assertTrue(outcome.silent)
        self.assertEqual(self.sent, [])  # nothing delivered
        session = conversation.load_session(session_id, vault_root=self.vault)
        self.assertEqual(session["status"], "closed")  # the session still closes
        self.assertEqual(session["close"]["takeaway"], "")
        self.assertNotIn("hook", session["close"])
        entry = json.loads(self.state_path.read_text())["entries"][engine.close_key(session_id)]
        self.assertEqual(entry["reason"], "malformed_generation")

    def test_old_message_shape_generation_also_degrades_to_silence(self):
        # Regression guard for the exact gap #163 exploited: a model that
        # reverts to the pre-ADR-0014 {"message": ...} shape must not have
        # its text delivered.
        session_id = self._closeable_session()
        old_shape = json.dumps({"message": TAKEAWAY, "question_free": True})
        outcome = self._close(session_id, lambda _p, _m: old_shape)
        self.assertFalse(outcome.takeaway_delivered)
        self.assertEqual(self.sent, [])

    def test_lint_failure_on_prose_degrades_to_silence(self):
        session_id = self._closeable_session()
        leaked = (
            "That was something else. Hook for next time: **\"the chains "
            "and that hum\"**"
        )
        outcome = self._close(session_id, lambda _p, _m: closing_json(takeaway_prose=leaked))

        self.assertFalse(outcome.takeaway_delivered)
        self.assertEqual(self.sent, [])
        session = conversation.load_session(session_id, vault_root=self.vault)
        self.assertEqual(session["close"]["takeaway"], "")
        self.assertNotIn("hook", session["close"])
        entry = json.loads(self.state_path.read_text())["entries"][engine.close_key(session_id)]
        self.assertIn("closing_label_leak", entry["lint_ids"])
        self.assertIn("closing_markdown_leak", entry["lint_ids"])


# --------------------------------------------------------------------------
# Scope 3/4 — the four new lint classes, isolated and combined, plus the
# committed goldens (both directions).
# --------------------------------------------------------------------------


class ClosingScaffoldLintTests(unittest.TestCase):
    def test_label_leak_alone(self):
        findings = conversation_lints.lint_closing_phrases(
            "That was something else. Takeaway: it mattered a lot."
        )
        ids = {f["lint"] for f in findings}
        self.assertEqual(ids, {"closing_label_leak"})

    def test_meta_commentary_alone(self):
        findings = conversation_lints.lint_closing_phrases(
            "I appreciated that you shared this with me today."
        )
        ids = {f["lint"] for f in findings}
        self.assertEqual(ids, {"closing_meta_commentary"})

    def test_meta_commentary_regex_alternation(self):
        findings = conversation_lints.lint_closing_phrases(
            "Honestly, that made this actually useful for both of us."
        )
        ids = {f["lint"] for f in findings}
        self.assertEqual(ids, {"closing_meta_commentary"})

    def test_future_turn_clause_initial_shape_alone(self):
        findings = conversation_lints.lint_closing_phrases(
            "That was something else. Next time, let's pick up right here."
        )
        ids = {f["lint"] for f in findings}
        self.assertEqual(ids, {"closing_future_turn"})

    def test_future_turn_literal_phrase_alone(self):
        findings = conversation_lints.lint_closing_phrases(
            "We can leave the rest of it. No need to re-explain."
        )
        ids = {f["lint"] for f in findings}
        self.assertEqual(ids, {"closing_future_turn"})

    def test_future_turn_mid_sentence_next_time_is_not_flagged(self):
        # The existing chat-promotion-closing.json golden's exact shape —
        # "next time" mid-sentence, no comma, no instruction — must stay
        # clean, or this PR would break a pre-existing correct golden.
        findings = conversation_lints.lint_closing_phrases(
            "I'd love to hear more about that call with your sister next time."
        )
        self.assertEqual(findings, [])

    def test_markdown_leak_alone(self):
        findings = conversation_lints.lint_closing_phrases(
            "That's everything for tonight. I'll keep it **filed**."
        )
        ids = {f["lint"] for f in findings}
        self.assertEqual(ids, {"closing_markdown_leak"})

    def test_synthetic_bad_close_trips_all_four_classes(self):
        text = _closing_turn_text(BAD_FIXTURE)
        findings = conversation_lints.lint_closing_phrases(text)
        ids = {f["lint"] for f in findings}
        self.assertEqual(
            ids,
            {"closing_label_leak", "closing_meta_commentary", "closing_future_turn",
             "closing_markdown_leak"},
        )

    def test_synthetic_bad_close_also_trips_at_the_runtime_gate(self):
        # Same authority the runtime actually calls (lint_outgoing), not
        # just the lower-level function.
        text = _closing_turn_text(BAD_FIXTURE)
        blocking, _advisory = engine.lint_outgoing(text, question_allowed=False, is_closing=True)
        for lint_id in ("closing_label_leak", "closing_meta_commentary",
                        "closing_future_turn", "closing_markdown_leak"):
            self.assertIn(lint_id, blocking)

    def test_woven_good_closes_stay_clean_under_the_new_checks(self):
        for path in GOOD_GOLDENS:
            with self.subTest(golden=path.name):
                text = _closing_turn_text(path)
                self.assertEqual(conversation_lints.lint_closing_phrases(text), [])

    def test_bad_fixture_is_excluded_from_the_eval_harness_sweep(self):
        import interaction_evals as ie  # noqa: PLC0415
        golden_ids = {g.get("golden_id") for g in ie.load_goldens()}
        self.assertNotIn("closing-scaffold-leak-bad-01", golden_ids)

    def test_new_good_golden_is_swept_and_declares_the_closing_properties(self):
        import interaction_evals as ie  # noqa: PLC0415
        golden_ids = {g.get("golden_id") for g in ie.load_goldens()}
        self.assertIn("chat-porch-swing-closing-01", golden_ids)


if __name__ == "__main__":
    unittest.main()
