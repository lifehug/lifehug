"""issue #168 / ADR 0016 — asking-supply: conversations see and ask the
session focus's held bank questions.

Two seams under test:

* ``system/conversation.py``'s ``asking_supply`` block producer — the
  focus-derivation ladder, top-K trimming, REUSE of
  ``question_planner.enriched_pending_questions``'s own ranking gates
  (rumination cooldown, escalation), session-scoped decline exclusion, and
  the ``blocks`` override (platform seam).
* ``system/conversation_delivery.py``'s widened gate — the invitation
  hatch honored past target, an uninvited question still discarded exactly
  as before, held-question bookkeeping (a pick, never a mint), and the
  session-scoped decline-detection rule.

Synthetic data only — NEVER ~/Workspace/dave. ``question_planner``/
``roadmap`` bind to process-global path constants (not vault_root
parameterized); tests monkeypatch ``qp.QUESTIONS_FILE`` /
``roadmap.ROADMAP_FILE`` directly, the same idiom
``tests/test_conversation_close.py``'s ``PlannerTests`` and
``tests/test_v72_second_voice.py`` already establish.
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
import question_planner as qp  # noqa: E402
import roadmap  # noqa: E402
from ai_provider import ProviderStatus  # noqa: E402
import lifehug_core as core  # noqa: E402

#: A small synthetic bank: a main life-story category (A) plus one
#: standalone Focus category (K, "Cabin Project") with five questions —
#: one already answered (the chat's own arc anchor), four still open.
#: K3's text ("hardest") deliberately classifies as the "tension" story
#: function (question_planner.STORY_FUNCTION_KEYWORDS), which IS one of
#: LATE_RELATIONAL_FUNCTIONS — with only one K-answer on record
#: (< ESCALATION_MIN_ANSWERED == 2) this is real escalation-gate downweight
#: via the REAL code path, not a mock.
BANK = """# Test Bank

## A: Origins
- [x] A1: What's your earliest memory?

## Focuses

## K: Cabin Project
- [x] K1: When did you start the cabin project?
- [ ] K2: Who helped you build it?
- [ ] K3: What's the hardest part been?
- [ ] K4: What's a detail about the river you haven't mentioned?
- [ ] K5: Who else has stayed there with you?
"""

#: A variant where every K question is already answered — the focus
#: resolves, but there is nothing left to hold (empty-supply honesty).
BANK_FULLY_ANSWERED = """# Test Bank

## A: Origins
- [x] A1: What's your earliest memory?

## Focuses

## K: Cabin Project
- [x] K1: When did you start the cabin project?
"""


class AskingSupplyPlannerFixture(unittest.TestCase):
    """Shared question_planner/roadmap wiring — subclasses set self.bank_text."""

    bank_text = BANK

    def setUp(self):
        self.tmp = root_parent_tmp(self, ROOT, prefix="lifehug-asking-supply-")
        self.bank_path = self.tmp / "question-bank.md"
        self.bank_path.write_text(self.bank_text, encoding="utf-8")
        self._saved_questions_file = qp.QUESTIONS_FILE
        qp.QUESTIONS_FILE = self.bank_path
        self.addCleanup(setattr, qp, "QUESTIONS_FILE", self._saved_questions_file)
        # Cold roadmap.json -> resolve_roadmap derives on the fly from the
        # bank text above (question_planner.resolve_roadmap's own fallback).
        self._saved_roadmap_file = roadmap.ROADMAP_FILE
        roadmap.ROADMAP_FILE = self.tmp / "roadmap.json"
        self.addCleanup(setattr, roadmap, "ROADMAP_FILE", self._saved_roadmap_file)

    def _session(self, **overrides) -> dict:
        base = {
            "session_version": 1,
            "session_id": "conv-20260816-090000-abc123",
            "mode": "chat",
            "channel": "cli",
            "status": "open",
            "arc": {"question_id": "K1", "opening": "", "intents": []},
            "turns": [],
            "rolling_summary": "",
            "extracted": {"facts": [], "entities": [], "candidate_ideas": [], "mirror_responses": []},
        }
        base.update(overrides)
        return base


class FocusLadderTests(AskingSupplyPlannerFixture):
    def test_resolves_focus_from_arc_question_id(self):
        focus, candidates = conversation.asking_supply_selection(self._session())
        self.assertEqual(focus["id"], "cabin-project")
        self.assertEqual(focus["label"], "Cabin Project")
        ids = {row["id"] for row in candidates}
        self.assertTrue(ids)
        self.assertTrue(ids.issubset({"K2", "K3", "K4", "K5"}))

    def test_resolves_focus_from_a_turn_question_id_when_arc_absent(self):
        session = self._session(arc=None, turns=[
            {"role": "user", "text": "It started with my dad.", "question_id": "K1"},
        ])
        focus, _candidates = conversation.asking_supply_selection(session)
        self.assertEqual(focus["id"], "cabin-project")

    def test_story_session_with_no_question_id_resolves_nothing(self):
        session = self._session(arc=None, turns=[
            {"role": "user", "text": "Something happened today.", "source_path": "sources/manual/x.md"},
        ])
        focus, candidates = conversation.asking_supply_selection(session)
        self.assertIsNone(focus)
        self.assertEqual(candidates, [])
        self.assertEqual(conversation._assemble_asking_supply_block(session, self.tmp), "")

    def test_unmapped_category_resolves_nothing(self):
        session = self._session(arc={"question_id": "Z1", "opening": "", "intents": []})
        focus, candidates = conversation.asking_supply_selection(session)
        self.assertIsNone(focus)
        self.assertEqual(candidates, [])


class TopKAndGatesTests(AskingSupplyPlannerFixture):
    def test_top_k_default_three_and_escalation_gate_deprioritizes_k3(self):
        # 4 unanswered candidates, knob.asking_supply_top_k default 3: the
        # REAL question_planner.enriched_pending_questions escalation gate
        # (K3's "tension" story function, only 1 of 2 required K-answers on
        # record) pushes K3 to the bottom — it's the one left out.
        focus, selected = conversation.asking_supply_selection(self._session())
        self.assertEqual(focus["id"], "cabin-project")
        self.assertEqual(len(selected), 3)
        ids = [row["id"] for row in selected]
        self.assertNotIn("K3", ids)
        self.assertEqual(set(ids), {"K2", "K4", "K5"})

    def test_full_candidate_ranking_puts_the_escalation_held_question_last(self):
        _focus, candidates = conversation._resolve_session_focus_and_candidates(self._session())
        self.assertEqual(len(candidates), 4)
        by_id = {row["id"]: row for row in candidates}
        self.assertTrue(by_id["K3"]["escalation_hold"])
        self.assertEqual(candidates[-1]["id"], "K3")

    def test_rumination_cooldown_downweights_via_the_real_planner_hook(self):
        # question_planner.enriched_pending_questions applies the rumination
        # ×0.25 multiplier when quality_profile.load_profile reports the
        # category on cooldown — REUSED here, not re-derived. Compare the
        # same qid's weight with and without the mocked profile.
        _focus, baseline = conversation._resolve_session_focus_and_candidates(self._session())
        baseline_weight = next(r["weight"] for r in baseline if r["id"] == "K2")

        cooled_profile = {"active": True, "rumination_categories": ["K"], "by_story_function": {}}
        with mock.patch("quality_profile.load_profile", return_value=cooled_profile):
            _focus2, cooled = conversation._resolve_session_focus_and_candidates(self._session())
        cooled_weight = next(r["weight"] for r in cooled if r["id"] == "K2")

        self.assertLess(cooled_weight, baseline_weight)

    def test_declined_ids_are_excluded_from_selection(self):
        session = self._session(declined_question_ids=["K2"])
        _focus, selected = conversation.asking_supply_selection(session)
        ids = {row["id"] for row in selected}
        self.assertNotIn("K2", ids)


class EmptySupplyTests(AskingSupplyPlannerFixture):
    def test_focus_with_nothing_pending_renders_an_honest_empty_block(self):
        self.bank_path.write_text(BANK_FULLY_ANSWERED, encoding="utf-8")
        focus, selected = conversation.asking_supply_selection(self._session())
        self.assertEqual(focus["id"], "cabin-project")  # focus resolves...
        self.assertEqual(selected, [])                  # ...but nothing to hold
        block = conversation._assemble_asking_supply_block(self._session(), self.tmp)
        self.assertEqual(block, "")


class BlockRenderTests(AskingSupplyPlannerFixture):
    def test_header_and_lines_exact_format(self):
        block = conversation._assemble_asking_supply_block(self._session(), self.tmp)
        lines = block.splitlines()
        self.assertEqual(lines[0], "Focus: Cabin Project — 1 of 5 answered")
        for line in lines[1:]:
            self.assertRegex(line, r"^\[K\d\] .+")

    def test_assemble_context_calls_the_producer_when_no_override(self):
        context = conversation.assemble_context(self._session(), vault_root=self.tmp)
        self.assertIn("## ASKING_SUPPLY", context)
        self.assertIn("Focus: Cabin Project", context)

    def test_blocks_override_bypasses_the_vault_local_producer(self):
        # The platform seam (contract, Scope 1): a caller-supplied
        # "asking_supply" block wins outright — the vault-local
        # question_planker producer is never consulted.
        context = conversation.assemble_context(
            self._session(), vault_root=self.tmp,
            blocks={"asking_supply": "CUSTOM PLATFORM-RESOLVED BLOCK"},
        )
        self.assertIn("CUSTOM PLATFORM-RESOLVED BLOCK", context)
        self.assertNotIn("Focus: Cabin Project", context)

    def test_block_order_between_record_and_session(self):
        order = conversation.ASSEMBLE_CONTEXT_BLOCK_ORDER
        self.assertEqual(
            order[order.index("record"):order.index("session") + 1],
            ("record", "asking_supply", "session"),
        )
        manifest = conversation.load_interaction_manifest()
        load_order = manifest["load_order"].split("|")
        self.assertEqual(load_order, [*order, "turn_instructions"])


# ---------------------------------------------------------------------------
# The engine gate: conversation_delivery.run_post_answer_turn honoring the
# invitation hatch, discarding an uninvited question exactly as before, and
# the session-scoped decline-detection rule. asking_supply_question_ids is
# patched directly (module-level seam) so these tests exercise the GATE in
# isolation from question_planker/roadmap wiring.
# ---------------------------------------------------------------------------

QUESTION_ID = "A14"
QUESTION = "What did the farm smell like?"
ANSWER = "Diesel and cut hay, mostly."
SECOND_ANSWER = "The hay came from the north field."
HELD_QID = "K7"


def ready_status(*_args, **_kwargs):
    return ProviderStatus("local-openai", "synthetic-model", True, "synthetic")


def confirmed_send(_message):
    return core.TelegramSendResult("confirmed", "telegram_confirmed", 1, 1)


def held_turn_json(message, *, held_question_id=HELD_QID, user_invited_question=False, **extra):
    payload = {
        "message": message,
        "followup_question": "the held question's own text, verbatim",
        "question_free": False,
        "user_invited_question": user_invited_question,
        "held_question_id": held_question_id,
        "rolling_summary": "",
        "insight_receipts": 0,
        "extracted": {"facts": [], "entities": [], "candidate_ideas": [], "mirror_responses": []},
    }
    payload.update(extra)
    return json.dumps(payload)


def question_free_json(message):
    return json.dumps({
        "message": message,
        "followup_question": None,
        "question_free": True,
        "user_invited_question": False,
        "held_question_id": None,
        "rolling_summary": "",
        "insight_receipts": 0,
        "extracted": {"facts": [], "entities": [], "candidate_ideas": [], "mirror_responses": []},
    })


class GateEngineTestCase(unittest.TestCase):
    """Same collaborator-injection posture as tests/test_conversation_delivery.py."""

    def setUp(self):
        self.tmp = root_parent_tmp(self, ROOT, prefix="lifehug-asking-supply-gate-")
        self.vault = self.tmp / "vault"
        self.vault.mkdir()
        self.state_path = self.tmp / "conversation_deliveries.json"
        self.sent: list[str] = []
        self.fallbacks: list[dict] = []
        self.minted: list[tuple[str, str]] = []
        self.rotation: list[str] = []
        diagnostics = mock.patch.object(engine, "record_learning_failure")
        self.diagnostic = diagnostics.start()
        self.addCleanup(diagnostics.stop)
        # asking_supply_question_ids is the module seam both the block
        # producer and the gate share; patched here so the gate is tested
        # against a KNOWN supply set without needing question_planker/
        # roadmap wiring in this test class.
        supply_patch = mock.patch.object(
            conversation, "asking_supply_question_ids", return_value=frozenset({HELD_QID})
        )
        supply_patch.start()
        self.addCleanup(supply_patch.stop)

    def _ai(self, response):
        def call(_prompt, _model):
            return response
        return call

    def _send(self):
        def send(message):
            self.sent.append(message)
            return confirmed_send(message)
        return send

    def _fallback(self, **kwargs):
        self.fallbacks.append(kwargs)

    def _minter(self, question_id, followups):
        new_id = f"{question_id}{chr(ord('a') + len(self.minted))}"
        self.minted.append((new_id, followups[0]))
        return [(new_id, followups[0])]

    def _rotation_updater(self, question_id):
        self.rotation.append(question_id)

    def run_turn(self, *, answer_text=ANSWER, question_id=QUESTION_ID, response, **overrides):
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
            "ai_call": self._ai(response),
            "telegram_send": self._send(),
            "prompt_builder": lambda payload: "SYNTHETIC TURN PROMPT",
            "followup_minter": self._minter,
            "rotation_updater": self._rotation_updater,
            "fallback": self._fallback,
        }
        kwargs.update(overrides)
        return engine.run_post_answer_turn(**kwargs)

    def only_session(self):
        sessions = conversation.list_sessions(vault_root=self.vault)
        self.assertEqual(len(sessions), 1, sessions)
        return conversation.load_session(sessions[0]["session_id"], vault_root=self.vault)


class WithinTargetHeldPickTests(GateEngineTestCase):
    def test_a_held_question_within_target_is_a_pick_not_a_mint(self):
        outcome = self.run_turn(response=held_turn_json(
            "Diesel and cut hay. Something I've been holding: the held question's own text, verbatim.",
        ))
        self.assertEqual(outcome.status, "confirmed")
        self.assertEqual(self.minted, [])       # no mint — this is a PICK
        self.assertEqual(self.rotation, [])      # no rotation mutation either
        self.assertEqual(outcome.followup_id, HELD_QID)

        session = self.only_session()
        lifehug_turn = session["turns"][1]
        self.assertEqual(lifehug_turn["question_id"], HELD_QID)
        self.assertTrue(lifehug_turn["asked_from_supply"])

    def test_a_held_qid_not_actually_in_the_supply_falls_back_to_no_pick(self):
        outcome = self.run_turn(response=held_turn_json(
            "Diesel and cut hay. Something I've been holding: the held question's own text, verbatim.",
            held_question_id="NOT-A-REAL-QID",
        ))
        self.assertEqual(outcome.status, "confirmed")
        # followup_question was also set, so it's minted as an ordinary
        # improvised follow-up instead — never stamped as a fabricated pick.
        self.assertEqual(len(self.minted), 1)
        session = self.only_session()
        self.assertNotIn("asked_from_supply", session["turns"][1])


class InvitationHatchTests(GateEngineTestCase):
    def _drive_past_target(self):
        """Two ordinary question-free exchanges to reach the chat target
        (knob.chat_target_exchanges: 3), then a third turn probes the gate."""
        first = self.run_turn(response=question_free_json("Diesel and hay, noted."))
        second = self.run_turn(
            answer_text=SECOND_ANSWER, response=question_free_json("The north field, noted."),
        )
        self.assertEqual([first.status, second.status], ["confirmed", "confirmed"])

    def test_invited_past_target_asks_the_held_question(self):
        self._drive_past_target()
        outcome = self.run_turn(
            answer_text="That's really all I remember about it.",
            response=held_turn_json(
                "That's a full picture already. Since you're asking: the held "
                "question's own text, verbatim.",
                user_invited_question=True,
            ),
        )
        self.assertEqual(outcome.status, "confirmed")
        self.assertEqual(self.minted, [])
        session = self.only_session()
        self.assertEqual(session["turns"][-1]["question_id"], HELD_QID)
        self.assertTrue(session["turns"][-1]["asked_from_supply"])

    def test_uninvited_past_target_question_is_still_discarded(self):
        self._drive_past_target()
        sent_before = len(self.sent)
        outcome = self.run_turn(
            answer_text="Still telling the story here.",
            response=held_turn_json(
                "Mid-story, noted. The held question's own text, verbatim?",
                user_invited_question=False,   # not invited
            ),
        )
        self.assertEqual((outcome.status, outcome.reason), ("failed", "malformed_generation"))
        self.assertIn("question_not_permitted", outcome.lint_ids)
        self.assertEqual(len(self.sent), sent_before)  # nothing new sent — discarded
        self.assertEqual(len(self.fallbacks), 1)

    def test_invited_but_qid_not_in_supply_is_still_discarded(self):
        self._drive_past_target()
        outcome = self.run_turn(
            answer_text="Still telling the story here.",
            response=held_turn_json(
                "Mid-story, noted. The held question's own text, verbatim?",
                held_question_id="NOT-A-REAL-QID",
                user_invited_question=True,   # invited, but the qid is fabricated
            ),
        )
        self.assertEqual((outcome.status, outcome.reason), ("failed", "malformed_generation"))
        self.assertIn("question_not_permitted", outcome.lint_ids)


class DeclineDetectionTests(GateEngineTestCase):
    def test_a_different_next_answer_marks_the_held_question_declined(self):
        first = self.run_turn(response=held_turn_json(
            "Diesel and cut hay. Something I've been holding: the held question's own text, verbatim.",
        ))
        self.assertEqual(first.status, "confirmed")
        self.assertTrue(self.only_session()["turns"][1]["asked_from_supply"])

        # Pinned to the SAME session: a different-subject reply arriving in
        # an already-open chat, not a brand new question chain — the
        # decline rule is session-scoped, so this must land in the one
        # session the held question was actually offered in.
        second = self.run_turn(
            answer_text=SECOND_ANSWER, question_id="A15",
            pinned_session_id=first.session_id,
            response=question_free_json("The north field, noted."),
        )
        self.assertEqual(second.status, "confirmed")
        session = self.only_session()
        self.assertEqual(session.get("declined_question_ids"), [HELD_QID])

    def test_engaging_the_held_question_records_no_decline(self):
        first = self.run_turn(response=held_turn_json(
            "Diesel and cut hay. Something I've been holding: the held question's own text, verbatim.",
        ))
        self.assertEqual(first.status, "confirmed")

        second = self.run_turn(
            answer_text="Right, so about that —", question_id=HELD_QID,
            response=question_free_json("Noted, thank you."),
        )
        self.assertEqual(second.status, "confirmed")
        session = self.only_session()
        self.assertNotIn(HELD_QID, session.get("declined_question_ids") or [])


if __name__ == "__main__":
    unittest.main()
