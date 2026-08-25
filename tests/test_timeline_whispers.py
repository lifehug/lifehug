"""v196 / timeline-whispers-and-keystones — the two ways a keystone is asked.

A WHISPER rides the week's arc card into an ordinary conversation; a KEYSTONE
QUESTION is minted into the bank and asked as the day's question. Both are
matched by the same identity, both file through `timeline-place`, and neither
leaves any side-state behind.

Synthetic data only; NEVER references ~/Workspace/dave.
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

import conversation  # noqa: E402
import conversation_delivery as engine  # noqa: E402
import question_judgment  # noqa: E402
import timeline_interaction as ti  # noqa: E402
from tempdirs import root_parent_tmp  # noqa: E402

WHISPER = {
    "kind": "timeline_gap",
    "anchor": "period:mesa",
    "question_id": "tl:mesa",
    "probe": "Where were you living when that happened?",
    "probe_step": "residence",
    "leverage": 11,
    "label": "the Mesa years",
    "unknown_keys": ["all_undated:mesa"],
    "anchors": [{"key": "birth", "label": "when you were born",
                 "kind": "birth", "date": "1979"},
                {"key": "mesa", "label": "the Mesa house",
                 "kind": "residence", "date": "1984/1990"}],
    "gap_kind": "all_undated",
    "period": "mesa",
    "note": "landmark-anchor phrasing — anchor this against a landmark",
}

BANK = (
    "# Questions\n\n## A: Origins\n\n- [ ] A1: Where does your story start?\n"
    "\n## Timeline\n\n## T: Timeline\n\n"
    "- [ ] T1: Where were you living when that happened?\n"
    "  <!-- timeline_probe: tl:mesa; anchor: period:mesa; leverage: 11; minted: x -->\n"
)


class ItemLookupTests(unittest.TestCase):
    """ONE definition of "this turn is carrying the timeline"."""

    def test_the_days_question_being_a_minted_keystone_is_an_item(self):
        item = ti.timeline_item_for_session(
            {"turns": []}, question_id="T1", probe_index=ti.timeline_probe_index(BANK))
        self.assertIsNotNone(item)
        self.assertEqual(item["question_id"], "tl:mesa")
        self.assertEqual(item["bank_question_id"], "T1")

    def test_an_ordinary_bank_question_with_an_arc_whisper_is_an_item(self):
        session = {"arc": {"intents": [{"kind": "scene_slot"}, WHISPER]}, "turns": []}
        item = ti.timeline_item_for_session(session, question_id="A1", probe_index={})
        self.assertEqual(item["probe"], WHISPER["probe"])

    def test_an_ordinary_turn_carries_nothing(self):
        self.assertIsNone(ti.timeline_item_for_session(
            {"arc": {"intents": [{"kind": "scene_slot"}]}, "turns": []},
            question_id="A1", probe_index={}))

    def test_one_ask_per_conversation_is_counted_off_the_session(self):
        session = {"turns": [{"role": "lifehug", "timeline_probe_id": "tl:mesa"}]}
        self.assertEqual(ti.timeline_asks_so_far(session), 1)
        self.assertEqual(ti.timeline_asks_so_far({"turns": []}), 0)


class PromptRenderingTests(unittest.TestCase):
    def test_a_whisper_renders_the_probe_and_their_own_landmarks(self):
        session = {"arc": {"opening": "You wrote: \"the diesel smell\"",
                           "intents": [{"kind": "scene_slot"}, WHISPER]}, "turns": []}
        block = conversation._assemble_session_block(session)  # noqa: SLF001
        self.assertIn("Timeline whisper:", block)
        self.assertIn(WHISPER["probe"], block)
        self.assertIn("the Mesa house", block)
        self.assertIn(str(WHISPER["leverage"]), block)
        self.assertIn(WHISPER["probe"],
                      conversation._current_intent_label(  # noqa: SLF001
                          session, session["arc"]["intents"]))

    def test_a_raised_whisper_is_not_offered_again(self):
        session = {"arc": {"opening": "o", "intents": [WHISPER]},
                   "turns": [{"role": "lifehug", "timeline_probe_id": "tl:mesa"}]}
        self.assertIsNone(conversation.timeline_whisper(session))
        self.assertNotIn("Timeline whisper:",
                         conversation._assemble_session_block(session))  # noqa: SLF001

    def test_every_other_intent_kind_renders_byte_for_byte_as_v195(self):
        """The golden: only the timeline item's rendering moved."""
        for kind in sorted(conversation.ARC_INTENT_KINDS - {"timeline_gap"}):
            with self.subTest(kind=kind):
                session = {"arc": {"opening": "o", "intents": [{"kind": kind}]},
                           "turns": []}
                self.assertEqual(
                    conversation._assemble_session_block(session),  # noqa: SLF001
                    f"Arc card: o (intents: {kind})")
                self.assertEqual(
                    conversation._current_intent_label(  # noqa: SLF001
                        session, session["arc"]["intents"]), kind)

    def test_a_v195_shaped_timeline_intent_still_renders_as_it_did(self):
        session = {"arc": {"opening": "o", "intents": [{"kind": "timeline_gap"}]},
                   "turns": []}
        self.assertEqual(
            conversation._assemble_session_block(session),  # noqa: SLF001
            "Arc card: o (intents: timeline_gap)")

    def test_the_direction_lives_with_the_slot_it_fills(self):
        text = " ".join((ROOT / "interactions" / "conversation" / "prompt"
                         / "turn-instructions.md").read_text(encoding="utf-8").split())
        self.assertIn("timeline whisper", text)
        self.assertIn("at most once in a conversation", text)
        self.assertIn("Accept any precision", text)
        self.assertIn("never ask it twice", text)


class AnswerRoutingTests(unittest.TestCase):
    def test_a_range_with_a_basis_is_validated_against_the_items_own_anchors(self):
        placed = ti.answer_timeline_probe(WHISPER, json.dumps({
            "message": "The Mesa house, then.",
            "placed": {"best": "1984/1990", "earliest": "1984", "latest": "1990",
                       "granularity": "range", "confidence": "inferred",
                       "basis": "anchor", "anchors": ["mesa"]},
        }))
        self.assertEqual(placed["granularity"], "range")
        self.assertEqual(placed["anchors"], ["mesa"])

    def test_an_invented_anchor_files_nothing(self):
        self.assertIsNone(ti.answer_timeline_probe(WHISPER, {
            "placed": {"best": "1984", "anchors": ["moon-landing"]}}))

    def test_ill_find_out_files_nothing_and_is_not_an_error(self):
        self.assertIsNone(ti.answer_timeline_probe(WHISPER, {"placed": None}))
        self.assertIsNone(ti.answer_timeline_probe(WHISPER, {"placed": {"deferred": True}}))

    def test_the_invocation_is_the_packages_own_verb(self):
        placed = ti.answer_timeline_probe(WHISPER, {
            "placed": {"best": "1984/1990", "granularity": "range",
                       "confidence": "inferred", "basis": "anchor",
                       "anchors": ["mesa"]}})
        call = ti.place_invocation(placed, source="answers/A1.md",
                                   description="the bike", period="mesa")
        self.assertEqual(call.argv[0], "timeline-place")
        self.assertIn("--basis", call.argv)
        self.assertEqual(call.stdin_text, "the bike")


class ArcYieldTests(unittest.TestCase):
    """Ruling 6: the loop learns about arcs from data the vault already has."""

    SESSIONS = [
        {"arc": {"intents": [{"kind": "timeline_gap"}, {"kind": "scene_slot"}]},
         "turns": [{"role": "lifehug", "question_id": "A1",
                    "placed": {"best": "1984"}}],
         "extracted": {"entities": [{"name": "Mesa"}]}},
        {"arc": {"intents": [{"kind": "scene_slot"}]},
         "turns": [{"role": "lifehug", "question_id": "A2"}],
         "extracted": {"entities": []}},
        {"arc": None, "turns": [], "extracted": {}},
    ]

    def test_every_kind_on_a_card_is_credited_with_that_sessions_yield(self):
        rows = question_judgment.arc_yield(sessions=self.SESSIONS)
        self.assertEqual(set(rows), {"timeline_gap", "scene_slot"})
        self.assertEqual(rows["timeline_gap"]["sessions"], 1)
        self.assertEqual(rows["scene_slot"]["sessions"], 2)
        self.assertEqual(rows["timeline_gap"]["placements"], 1)
        self.assertEqual(rows["timeline_gap"]["new_entities"], 1)
        self.assertEqual(rows["timeline_gap"]["yield_per_session"], 2.0)

    def test_a_vault_with_no_arc_cards_says_so_rather_than_inventing_a_number(self):
        self.assertEqual(question_judgment.arc_yield(sessions=[]), {})
        self.assertIn("nothing to learn about arcs",
                      question_judgment.format_arc_yield({}))

    def test_the_summary_is_deterministic_and_ordered_by_yield(self):
        text = question_judgment.format_arc_yield(
            question_judgment.arc_yield(sessions=self.SESSIONS))
        self.assertLess(text.index("timeline_gap"), text.index("scene_slot"))
        self.assertEqual(text, question_judgment.format_arc_yield(
            question_judgment.arc_yield(sessions=self.SESSIONS)))


class ArcAmendmentTests(unittest.TestCase):
    def setUp(self):
        self.tmp = root_parent_tmp(self, ROOT, prefix="lifehug-v196-arc-")
        self.path = self.tmp / "arc_learned.md"

    def _apply(self, payload):
        return question_judgment._apply_arc_amendment(  # noqa: SLF001
            payload, max_edit_chars=600, max_file_chars=8000,
            arc_learned_path=self.path)

    def test_an_evidence_cited_amendment_lands_dated(self):
        result = self._apply({"arc_amendment": "Lead with the timeline whisper "
                                               "in eras with no dated events.",
                              "arc_evidence": "timeline_gap: 2 sessions, 4 placements"})
        self.assertTrue(result["arc_amended"])
        body = self.path.read_text(encoding="utf-8")
        self.assertIn("Lead with the timeline whisper", body)
        self.assertIn("Evidence:", body)

    def test_declining_is_the_ordinary_week(self):
        self.assertFalse(self._apply({"arc_amendment": None})["arc_amended"])
        self.assertFalse(self.path.exists())

    def test_an_amendment_without_evidence_or_over_budget_is_refused(self):
        self.assertEqual(self._apply({"arc_amendment": "x"})["arc_status"], "invalid")
        self.assertEqual(
            self._apply({"arc_amendment": "y" * 601, "arc_evidence": "e"})["arc_status"],
            "invalid")
        self.assertFalse(self.path.exists())

    def test_the_learned_block_is_composed_not_written_into_the_framework_file(self):
        template = (ROOT / "interactions" / "conversation" / "plan"
                    / "arc-templates.md").read_text(encoding="utf-8")
        self.assertNotIn(question_judgment.ARC_SIGNALS_HEADING, template)
        self._apply({"arc_amendment": "A", "arc_evidence": "E"})
        with mock.patch.object(question_judgment, "ARC_LEARNED_FILE", self.path):
            block = question_judgment.load_arc_signals()
        self.assertTrue(block.startswith(question_judgment.ARC_SIGNALS_HEADING))


class DeferralRemnantTests(unittest.TestCase):
    """Ruling 4: the deferral machine is deleted, and stays deleted."""

    NAMES = ("timeline_deferred", "DEFERRED_QUIET_DAYS", "defer_unknown",
             "is_deferred", "load_deferred", "DEFERRED_FILE", "timeline-defer")
    SKIP = {"version.json", "test_timeline_whispers.py"}

    def test_no_runtime_module_or_definition_carries_the_deleted_names(self):
        roots = [SYSTEM, ROOT / "interactions", ROOT / "docs" / "handbook"]
        offenders = []
        for root in roots:
            for path in sorted(root.rglob("*")):
                if not path.is_file() or path.name in self.SKIP:
                    continue
                if path.suffix not in {".py", ".md", ".json", ".yaml", ".sh"}:
                    continue
                text = path.read_text(encoding="utf-8", errors="replace")
                for name in self.NAMES:
                    if name in text:
                        offenders.append(f"{path.relative_to(ROOT)}: {name}")
        self.assertEqual(offenders, [])

    def test_the_module_no_longer_exposes_the_api(self):
        import timeline  # noqa: PLC0415

        for name in ("defer_unknown", "is_deferred", "load_deferred",
                     "DEFERRED_FILE", "DEFERRED_QUIET_DAYS"):
            with self.subTest(name=name):
                self.assertFalse(hasattr(timeline, name))

    def test_the_vault_contract_has_no_deferred_file(self):
        contract = json.loads((SYSTEM / "vault_contract.json").read_text(encoding="utf-8"))
        self.assertNotIn("timeline_deferred", contract["data_paths"])


class DeliverySeamTests(unittest.TestCase):
    """The engine only opens the `placed` gate when a turn carries an item."""

    def setUp(self):
        self.tmp = root_parent_tmp(self, ROOT, prefix="lifehug-v196-seam-")
        self.vault = self.tmp / "vault"
        (self.vault / "state").mkdir(parents=True)

    def test_no_item_means_no_item(self):
        self.assertIsNone(engine.timeline_item_for_turn(
            {"turns": [], "arc": None}, "A1", vault_root=self.vault))

    def test_a_whisper_is_found_and_then_spent(self):
        session = {"arc": {"intents": [WHISPER]}, "turns": []}
        self.assertIsNotNone(engine.timeline_item_for_turn(
            session, "A1", vault_root=self.vault))
        session["turns"].append({"role": "lifehug", "timeline_probe_id": "tl:mesa"})
        self.assertIsNone(engine.timeline_item_for_turn(
            session, "A1", vault_root=self.vault))

    def test_a_broken_bank_never_costs_the_turn_its_item(self):
        with mock.patch.object(engine, "_question_bank_text", side_effect=OSError):
            self.assertIsNone(engine.timeline_item_for_turn(
                {"arc": {"intents": [WHISPER]}, "turns": []}, "A1",
                vault_root=self.vault))


if __name__ == "__main__":
    unittest.main()
