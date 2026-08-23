"""v150 / issue #115 — conversation session store + pure prompt/context builders.

Conversation Interaction build, Wave 1 PR 2 of 2. Registers state/arc_cards,
state/conversations/, and state/mirror_responses in the vault contract
(v2), then exercises system/conversation.py's session CRUD + assembly +
prompt builders and system/conversation_lints.py's deterministic lint
engine. Infrastructure only — subtest 6 proves no live flow imports either
new module.

Synthetic data only; NEVER references ~/Workspace/dave.
"""

from __future__ import annotations

import json
import re
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
import conversation_lints  # noqa: E402
import vault_paths  # noqa: E402

EXPECTED_NEW_DATA_PATHS = {"arc_cards", "conversations", "mirror_responses"}


class RegistrationTests(unittest.TestCase):
    """Subtest 1: contract imports green; the three new entries' shapes."""

    def test_new_data_paths_registered_with_contract_shapes(self):
        exported = vault_paths.exported_contract()
        data_paths = exported["data_paths"]
        self.assertTrue(EXPECTED_NEW_DATA_PATHS.issubset(set(data_paths)))

        arc_cards = data_paths["arc_cards"]
        self.assertEqual(arc_cards["external_path"], "state/arc_cards.json")
        self.assertEqual(arc_cards["classification"], "durable_data")
        self.assertFalse(arc_cards.get("required", False))

        conversations = data_paths["conversations"]
        self.assertEqual(conversations["external_path"], "state/conversations")
        self.assertEqual(conversations["classification"], "durable_data")

        mirror_responses = data_paths["mirror_responses"]
        self.assertEqual(mirror_responses["external_path"], "state/mirror_responses.json")
        self.assertEqual(mirror_responses["classification"], "durable_data")

        # kind is derivable from vault_paths.VAULT_DATA_PATHS (pre-normalization
        # entries keep "kind" verbatim from the raw contract).
        self.assertEqual(vault_paths.VAULT_DATA_PATHS["arc_cards"]["kind"], "file")
        self.assertEqual(vault_paths.VAULT_DATA_PATHS["conversations"]["kind"], "directory")
        self.assertEqual(vault_paths.VAULT_DATA_PATHS["mirror_responses"]["kind"], "file")
        for name in EXPECTED_NEW_DATA_PATHS:
            self.assertTrue(vault_paths.VAULT_DATA_PATHS[name]["tracked"])

    def test_interactions_framework_path_is_a_directory(self):
        self.assertEqual(
            vault_paths.FRAMEWORK_PATHS["interactions"],
            {"path": "interactions", "kind": "directory", "classification": "framework"},
        )

    def test_digest_is_self_consistent(self):
        self.assertEqual(
            vault_paths.VAULT_CONTRACT["identity"]["content_digest"],
            vault_paths._contract_digest(vault_paths.VAULT_CONTRACT),
        )

    def test_lifehug_core_gained_exactly_one_data_accessor_per_new_name(self):
        core = (SYSTEM / "lifehug_core.py").read_text(encoding="utf-8")
        found = re.findall(r'_data\("([^"]+)"\)', core)
        for name in EXPECTED_NEW_DATA_PATHS:
            self.assertEqual(found.count(name), 1, name)


class ConversationStoreTests(unittest.TestCase):
    """Subtest 2: session lifecycle (open/append CAS/close, cold-vault degradation)."""

    def setUp(self):
        self.tmp = root_parent_tmp(self, ROOT, prefix="lifehug-v150-conversation-")
        self.vault = self.tmp / "vault"
        self.vault.mkdir()

    def test_cold_vault_degrades_to_empty_not_an_error(self):
        self.assertEqual(conversation.list_sessions(vault_root=self.vault), [])
        self.assertIsNone(conversation.load_arc_card("A14b", vault_root=self.vault))

    def test_open_creates_the_document_with_the_exact_schema_shape(self):
        arc = {
            "question_id": "A14b",
            "opening": "Last time you mentioned the diesel smell on the farm.",
            "intents": [{"kind": "scene_slot", "focus": "kitchen"}],
        }
        doc = conversation.open_session("chat", "cli", arc=arc, vault_root=self.vault)

        self.assertRegex(doc["session_id"], r"^conv-\d{8}-\d{6}-[0-9a-f]{6}$")
        path = self.vault / "state" / "conversations" / f"{doc['session_id']}.json"
        self.assertTrue(path.is_file())
        on_disk = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(on_disk, doc)

        self.assertEqual(doc["session_version"], 1)
        self.assertEqual(doc["mode"], "chat")
        self.assertEqual(doc["channel"], "cli")
        self.assertIn("interaction_version", doc)
        self.assertEqual(doc["status"], "open")
        self.assertEqual(doc["arc"], arc)
        self.assertEqual(doc["turns"], [])
        self.assertEqual(doc["rolling_summary"], "")
        self.assertEqual(
            doc["extracted"],
            {"facts": [], "entities": [], "candidate_ideas": [], "mirror_responses": []},
        )
        self.assertNotIn("close", doc)

    def test_append_turn_cas_and_stale_expected_turns_fails_typed(self):
        doc = conversation.open_session("conversation", "cli", vault_root=self.vault)
        sid = doc["session_id"]

        appended = conversation.append_turn(
            sid,
            {"role": "user", "text": "The diesel smell, mostly.", "channel": "cli"},
            expected_turns=0,
            vault_root=self.vault,
        )
        self.assertEqual(len(appended["turns"]), 1)
        self.assertEqual(appended["turns"][0]["role"], "user")
        self.assertEqual(appended["turns"][0]["channel"], "cli")
        self.assertIn("ts", appended["turns"][0])

        with self.assertRaises(conversation.TurnConflictError):
            conversation.append_turn(
                sid,
                {"role": "lifehug", "text": "Tell me more.", "channel": "cli"},
                expected_turns=0,  # stale — one turn already landed
                vault_root=self.vault,
            )
        reloaded = conversation.load_session(sid, vault_root=self.vault)
        self.assertEqual(len(reloaded["turns"]), 1, "the failed CAS must not have written")

    def test_close_idempotent_mismatch_and_append_after_close(self):
        doc = conversation.open_session("chat", "cli", vault_root=self.vault)
        sid = doc["session_id"]

        closed = conversation.close_session(sid, {"reason": "done"}, vault_root=self.vault)
        self.assertEqual(closed["status"], "closed")
        self.assertEqual(closed["close"], {"reason": "done"})

        # idempotent: identical payload, no-op
        again = conversation.close_session(sid, {"reason": "done"}, vault_root=self.vault)
        self.assertEqual(again, closed)

        # different payload against an already-closed session: typed error
        with self.assertRaises(conversation.InvalidCloseError):
            conversation.close_session(sid, {"reason": "idle_timeout"}, vault_root=self.vault)

        # append after close: typed error
        with self.assertRaises(conversation.SessionClosedError):
            conversation.append_turn(
                sid,
                {"role": "user", "text": "one more thing", "channel": "cli"},
                expected_turns=0,
                vault_root=self.vault,
            )

    def test_list_sessions_metadata_only_and_status_filter(self):
        open_doc = conversation.open_session("chat", "telegram", vault_root=self.vault)
        conversation.append_turn(
            open_doc["session_id"],
            {"role": "user", "text": "hi there", "channel": "telegram"},
            expected_turns=0,
            vault_root=self.vault,
        )
        closed_doc = conversation.open_session("conversation", "web", vault_root=self.vault)
        conversation.close_session(closed_doc["session_id"], {"reason": "done"}, vault_root=self.vault)

        all_sessions = {s["session_id"]: s for s in conversation.list_sessions(vault_root=self.vault)}
        self.assertEqual(set(all_sessions), {open_doc["session_id"], closed_doc["session_id"]})
        self.assertEqual(all_sessions[open_doc["session_id"]]["turn_count"], 1)
        self.assertEqual(all_sessions[open_doc["session_id"]]["status"], "open")
        self.assertEqual(all_sessions[open_doc["session_id"]]["channel"], "telegram")
        self.assertIsNotNone(all_sessions[open_doc["session_id"]]["opened"])
        self.assertIsNone(all_sessions[closed_doc["session_id"]]["opened"])  # zero turns

        closed_only = conversation.list_sessions(status="closed", vault_root=self.vault)
        self.assertEqual([s["session_id"] for s in closed_only], [closed_doc["session_id"]])

    def test_invalid_mode_channel_and_role_raise(self):
        with self.assertRaises(ValueError):
            conversation.open_session("bogus", "cli", vault_root=self.vault)
        with self.assertRaises(ValueError):
            conversation.open_session("chat", "bogus", vault_root=self.vault)
        doc = conversation.open_session("chat", "cli", vault_root=self.vault)
        with self.assertRaises(ValueError):
            conversation.append_turn(
                doc["session_id"],
                {"role": "bogus", "text": "x", "channel": "cli"},
                expected_turns=0,
                vault_root=self.vault,
            )


class ArcCardStoreTests(unittest.TestCase):
    """Arc-card storage per mid-flight audit amendment M1: cards is a LIST,
    not dict-keyed by question_id; the container carries generation-run
    bookkeeping this PR does not interpret (that's #118 / platform PR #124).
    """

    def setUp(self):
        self.tmp = root_parent_tmp(self, ROOT, prefix="lifehug-v150-arc-cards-")
        self.vault = self.tmp / "vault"
        self.vault.mkdir()

    def test_save_then_load_round_trips_and_cards_is_a_list(self):
        card = {
            "question_id": "A14b",
            "opening": "Last time...",
            "intents": [{"kind": "timeline_gap"}, {"kind": "sit_with"}],
        }
        conversation.save_arc_card(card, vault_root=self.vault)
        on_disk = json.loads(
            (self.vault / "state" / "arc_cards.json").read_text(encoding="utf-8")
        )
        self.assertIsInstance(on_disk["cards"], list)
        self.assertIn("generated_at", on_disk)
        self.assertIn("queue_generated_at", on_disk)
        self.assertIn("expires_at", on_disk)
        self.assertIn("source", on_disk)
        self.assertIn("thread_offers", on_disk)

        loaded = conversation.load_arc_card("A14b", vault_root=self.vault)
        self.assertEqual(loaded, card)
        self.assertIsNone(conversation.load_arc_card("nonexistent", vault_root=self.vault))

    def test_save_upserts_by_question_id_without_duplicating(self):
        conversation.save_arc_card({"question_id": "A1", "intents": []}, vault_root=self.vault)
        conversation.save_arc_card({"question_id": "A2", "intents": []}, vault_root=self.vault)
        conversation.save_arc_card(
            {"question_id": "A1", "intents": [{"kind": "studio_slot"}]}, vault_root=self.vault
        )
        on_disk = json.loads(
            (self.vault / "state" / "arc_cards.json").read_text(encoding="utf-8")
        )
        self.assertEqual(len(on_disk["cards"]), 2)
        updated = conversation.load_arc_card("A1", vault_root=self.vault)
        self.assertEqual(updated["intents"], [{"kind": "studio_slot"}])

    def test_no_append_mirror_response_function_exists(self):
        """M14: #119 ships the single mirror writer; this PR only registers
        the vault-contract path."""
        self.assertFalse(hasattr(conversation, "append_mirror_response"))


class AssemblyDeterminismTests(unittest.TestCase):
    """Subtest 3: same session + same blocks -> byte-identical context twice;
    block order matches interaction.yaml's load_order; budgets truncate.
    """

    def _sample_session(self) -> dict:
        return {
            "session_version": 1,
            "session_id": "conv-20260811-090000-abc123",
            "mode": "chat",
            "channel": "cli",
            "interaction_version": "1.0.0",
            "status": "open",
            "arc": {
                "question_id": "A14b",
                "opening": "Last time you mentioned the diesel smell.",
                "intents": [{"kind": "scene_slot"}, {"kind": "demonstrated_knowledge_summary"}],
            },
            "turns": [
                {"role": "user", "text": "It was the tractor, mostly.", "ts": "2026-08-11T09:00:00Z", "channel": "cli"},
            ],
            "rolling_summary": "The user has been describing the family farm.",
            "extracted": {"facts": [], "entities": [], "candidate_ideas": [], "mirror_responses": []},
        }

    def test_assembly_is_byte_identical_across_two_calls(self):
        session = self._sample_session()
        blocks = {"profile": "Name: Dave.", "record": "[A9, 2026-01-01] The tractor story."}
        first = conversation.assemble_context(session, blocks=blocks)
        second = conversation.assemble_context(session, blocks=blocks)
        self.assertEqual(first, second)
        self.assertIn("Name: Dave.", first)
        self.assertIn("The tractor story.", first)

    def test_block_order_matches_interaction_yaml_load_order(self):
        manifest = conversation.load_interaction_manifest()
        load_order = manifest["load_order"].split("|")
        self.assertEqual(load_order, [*conversation.ASSEMBLE_CONTEXT_BLOCK_ORDER, "turn_instructions"])

    def test_oversized_block_is_elided_within_its_budget(self):
        """v201 (lifehug#206): a block over budget is still shortened to fit,
        but it is shortened at a boundary and MARKED as shortened — never a
        bare character cut. The old assertion pinned exactly `budget_chars`
        of the payload, which is the same thing as pinning a mid-word cut."""
        session = self._sample_session()
        oversized = "x" * 50_000
        blocks = {"profile": oversized, "record": ""}
        context = conversation.assemble_context(session, blocks=blocks)
        self.assertNotIn(oversized, context)
        manifest = conversation.load_interaction_manifest()
        budget_chars = manifest["budget.profile"] * conversation.CHARS_PER_TOKEN
        profile = context.split("## PROFILE\n\n", 1)[1].split("\n\n## ", 1)[0]
        self.assertLessEqual(len(profile), budget_chars)
        self.assertTrue(profile.endswith(conversation.ELISION_MARKER))
        self.assertGreater(profile.count("x"), budget_chars // 2)


class BuilderTests(unittest.TestCase):
    """Subtest 4: each of the four builders on a fixture payload, plus CLI paths."""

    def _sample_session(self) -> dict:
        return {
            "session_version": 1,
            "session_id": "conv-20260811-090000-abc123",
            "mode": "chat",
            "channel": "cli",
            "interaction_version": "1.0.0",
            "status": "open",
            "arc": {
                "question_id": "A14b",
                "opening": "Last time you mentioned the diesel smell.",
                "intents": [{"kind": "scene_slot"}],
            },
            "turns": [
                {"role": "user", "text": "It was the tractor, mostly.", "ts": "2026-08-11T09:00:00Z", "channel": "cli"},
            ],
            "rolling_summary": "",
            "extracted": {"facts": [], "entities": [], "candidate_ideas": [], "mirror_responses": []},
        }

    def test_build_turn_prompt_fills_placeholders(self):
        session = self._sample_session()
        prompt = conversation.build_turn_prompt({"session": session, "blocks": {"profile": "", "record": ""}})
        self.assertIn("chat", prompt)
        self.assertIn("scene_slot", prompt)
        self.assertIn("It was the tractor, mostly.", prompt)
        self.assertNotIn("{mode}", prompt)
        self.assertNotIn("{arc_intent}", prompt)
        self.assertNotIn("{turn_position}", prompt)
        self.assertNotIn("{previous_turn}", prompt)
        self.assertNotIn("{length_cap}", prompt)

    def test_build_router_prompt_contains_message_and_all_five_intents(self):
        prompt = conversation.build_router_prompt({
            "message": "what's the weather tomorrow?",
            "session_open": False,
            "pending_question_id": None,
        })
        self.assertIn("what's the weather tomorrow?", prompt)
        for intent in ("answer", "new_story", "command", "continue_session", "out_of_scope"):
            self.assertIn(intent, prompt)

    # ---- issue #169 / ADR 0017 — the thread binder: roster in the prompt ----

    BASE_PAYLOAD = {
        "message": "It was my uncle who built it.",
        "session_open": True,
        "pending_question_id": "A14",
        "recently_closed": False,
    }

    def test_absent_threads_is_byte_identical_to_no_threads_key_at_all(self):
        without_key = conversation.build_router_prompt(dict(self.BASE_PAYLOAD))
        with_none = conversation.build_router_prompt(dict(self.BASE_PAYLOAD, threads=None))
        with_empty = conversation.build_router_prompt(dict(self.BASE_PAYLOAD, threads=[]))
        self.assertEqual(without_key, with_none)
        self.assertEqual(without_key, with_empty)

    def test_absent_threads_never_renders_a_roster_block(self):
        prompt = conversation.build_router_prompt(dict(self.BASE_PAYLOAD))
        # router.md's own prose mentions "ROSTER" (the doctrine section) —
        # only the runtime INPUT block (after the marker) must never
        # render one when no threads were given.
        input_block = prompt.split("## INPUT (assembled at runtime", 1)[1]
        self.assertNotIn("ROSTER", input_block)

    def test_present_threads_renders_roster_block_with_candidate_fields(self):
        payload = dict(self.BASE_PAYLOAD, threads=[
            {"id": "thread-a", "question": "Who built it?", "last_exchange": "user: no idea",
             "awaiting_ask": True},
        ])
        prompt = conversation.build_router_prompt(payload)
        self.assertIn("ROSTER", prompt)
        self.assertIn("id=thread-a", prompt)
        self.assertIn("awaiting_ask=true", prompt)
        self.assertIn("Who built it?", prompt)
        # the roster block sits before MESSAGE, never after (input order).
        self.assertLess(prompt.index("ROSTER"), prompt.index("MESSAGE:"))

    def test_roster_is_bounded_by_router_roster_max_knob(self):
        threads = [
            {"id": f"t{i}", "question": f"Q{i}?", "last_exchange": "x", "awaiting_ask": False}
            for i in range(10)
        ]
        small_manifest = dict(conversation.load_interaction_manifest())
        small_manifest["knob.router_roster_max"] = 2
        with mock.patch.object(conversation, "load_interaction_manifest", return_value=small_manifest):
            prompt = conversation.build_router_prompt(dict(self.BASE_PAYLOAD, threads=threads))
        self.assertIn("id=t0", prompt)
        self.assertIn("id=t1", prompt)
        self.assertNotIn("id=t2", prompt)

    def test_roster_defaults_to_six_when_knob_absent(self):
        threads = [
            {"id": f"t{i}", "question": f"Q{i}?", "last_exchange": "x", "awaiting_ask": False}
            for i in range(10)
        ]
        with mock.patch.object(conversation, "load_interaction_manifest", return_value={}):
            prompt = conversation.build_router_prompt(dict(self.BASE_PAYLOAD, threads=threads))
        for i in range(6):
            self.assertIn(f"id=t{i}", prompt)
        self.assertNotIn("id=t6", prompt)

    def test_build_arc_prompt_embeds_question_and_gap_inputs(self):
        prompt = conversation.build_arc_prompt({
            "question": {"id": "A22", "text": "Who taught you to drive?", "category": "A", "focus": "Family"},
            "record_summary": "Previously discussed the farm truck.",
            "gap_inputs": ["timeline gap: 1985-1987", "sibling: A21"],
        })
        self.assertIn("A22", prompt)
        self.assertIn("Who taught you to drive?", prompt)
        self.assertIn("Previously discussed the farm truck.", prompt)
        self.assertIn("timeline gap: 1985-1987", prompt)

    def test_build_closing_prompt_reflects_deposit_framing_off_by_default(self):
        session = self._sample_session()
        prompt = conversation.build_closing_prompt({"session": session})
        self.assertIn("OFF", prompt)
        self.assertIn("takeaway", prompt.lower())

    def test_build_closing_prompt_reflects_deposit_framing_when_on(self):
        session = self._sample_session()
        on_manifest = dict(conversation.load_interaction_manifest())
        on_manifest["knob.deposit_framing"] = "on"
        with mock.patch.object(conversation, "load_interaction_manifest", return_value=on_manifest):
            prompt = conversation.build_closing_prompt({"session": session})
        self.assertIn("ON", prompt)

    # ---- CLI paths (subprocess, same style as tests/test_answer_ack.py) ----

    def _run_cli(self, subcommand: str, stdin_text: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(SYSTEM / "conversation.py"), subcommand],
            input=stdin_text,
            capture_output=True,
            text=True,
        )

    def test_turn_prompt_cli_valid_payload_exits_0(self):
        payload = {"session": self._sample_session()}
        result = self._run_cli("turn-prompt", json.dumps(payload))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, "")
        self.assertIn("chat", result.stdout)

    def test_turn_prompt_cli_empty_stdin_exits_1_one_line_stderr(self):
        result = self._run_cli("turn-prompt", "")
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout, "")
        self.assertEqual(len(result.stderr.strip().splitlines()), 1)

    def test_router_prompt_cli_missing_field_exits_1(self):
        result = self._run_cli("router-prompt", json.dumps({"message": "hi"}))
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout, "")

    def test_arc_prompt_cli_invalid_json_exits_1(self):
        result = self._run_cli("arc-prompt", "{not json")
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout, "")

    def test_closing_prompt_cli_valid_payload_exits_0(self):
        payload = {"session": self._sample_session()}
        result = self._run_cli("closing-prompt", json.dumps(payload))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("takeaway", result.stdout.lower())


class LintTests(unittest.TestCase):
    """Subtest 5: per lint id, at least one flagged and one clean fixture."""

    def test_one_question_per_turn_flags_two_questions(self):
        findings = conversation_lints.lint_turn("Did you like it? What year was that?")
        self.assertTrue(any(f["lint"] == "one_question_per_turn" for f in findings))

    def test_one_question_per_turn_clean_on_a_single_question(self):
        findings = conversation_lints.lint_turn("What comes to mind first?")
        self.assertFalse(any(f["lint"] == "one_question_per_turn" for f in findings))

    def test_banned_phrases_flags_configured_phrase(self):
        findings = conversation_lints.lint_turn("That must have been so hard.")
        self.assertTrue(any(f["lint"] == "banned_phrases" for f in findings))

    def test_banned_phrases_clean_without_any_phrase(self):
        findings = conversation_lints.lint_turn("Thank you for telling me that.")
        self.assertFalse(any(f["lint"] == "banned_phrases" for f in findings))

    def test_question_grammar_audit_flags_closed_question(self):
        findings = conversation_lints.lint_turn("Did you like it?")
        self.assertTrue(any(
            f["lint"] == "question_grammar_audit" and "closed" in f["detail"] for f in findings
        ))

    def test_question_grammar_audit_flags_option_posing(self):
        findings = conversation_lints.lint_turn("Was it the red one or the blue one?")
        self.assertTrue(any(
            f["lint"] == "question_grammar_audit" and "option" in f["detail"] for f in findings
        ))

    def test_question_grammar_audit_clean_on_a_ted_question(self):
        findings = conversation_lints.lint_turn("Tell me what happened next.")
        self.assertFalse(any(f["lint"] == "question_grammar_audit" for f in findings))

    def test_length_caps_flags_an_oversized_turn(self):
        findings = conversation_lints.lint_turn("x" * 2000)
        self.assertTrue(any(f["lint"] == "length_caps" for f in findings))

    def test_length_caps_clean_under_the_cap(self):
        findings = conversation_lints.lint_turn("A short warm reply.")
        self.assertFalse(any(f["lint"] == "length_caps" for f in findings))

    def test_receipt_before_question_flags_opening_with_a_question(self):
        findings = conversation_lints.lint_turn(
            "What happened next?", is_reply_to_substantive=True
        )
        self.assertTrue(any(f["lint"] == "receipt_before_question" for f in findings))

    def test_receipt_before_question_clean_when_receipt_precedes(self):
        findings = conversation_lints.lint_turn(
            "That tractor story really landed. What happened next?",
            is_reply_to_substantive=True,
        )
        self.assertFalse(any(f["lint"] == "receipt_before_question" for f in findings))

    def test_receipt_before_question_not_checked_when_not_substantive_reply(self):
        findings = conversation_lints.lint_turn(
            "What happened next?", is_reply_to_substantive=False
        )
        self.assertFalse(any(f["lint"] == "receipt_before_question" for f in findings))

    def test_year_question_detector_flags_what_year(self):
        findings = conversation_lints.lint_turn("What year did you move?")
        self.assertTrue(any(f["lint"] == "year_question_detector" for f in findings))

    def test_year_question_detector_clean_without_year_phrasing(self):
        findings = conversation_lints.lint_turn("When did you move?")
        self.assertFalse(any(f["lint"] == "year_question_detector" for f in findings))

    def test_correct_payout_turn_has_zero_findings(self):
        text = 'The smell of diesel really landed for me. What do you remember about "the old farmhouse" now?'
        findings = conversation_lints.lint_turn(text, is_reply_to_substantive=True)
        self.assertEqual(findings, [])

    def test_echoed_quoted_question_does_not_count_toward_one_question_per_turn(self):
        text = 'You once asked me, "was it hard?", and I never really answered. What comes to mind now?'
        findings = conversation_lints.lint_turn(text, is_reply_to_substantive=True)
        self.assertFalse(any(f["lint"] == "one_question_per_turn" for f in findings))

    def test_lint_transcript_maps_over_lifehug_turns_only(self):
        turns = [
            {"role": "user", "text": "It was a long story about the farm and the diesel smell that day."},
            {"role": "lifehug", "text": "Did you like it?"},
            {"role": "user", "text": "no"},
            {"role": "lifehug", "text": "Thanks for sharing that."},
        ]
        findings = conversation_lints.lint_transcript(turns)
        self.assertTrue(any(f["turn_index"] == 1 and f["lint"] == "question_grammar_audit" for f in findings))
        self.assertFalse(any(f["turn_index"] == 3 for f in findings))

    def test_lints_config_loads_the_pinned_cap(self):
        config = conversation_lints.load_lints_config()
        self.assertEqual(config["cap.turn_chars"], 1200)
        self.assertIn("that must have been", config["banned_phrases"])

    # ---- CLI path ----

    def test_lint_cli_prints_json_lines_and_always_exits_0(self):
        result = subprocess.run(
            [sys.executable, str(SYSTEM / "conversation_lints.py"), "--reply-to-substantive"],
            input="That must have been so hard. What year was that? Or was it later?",
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        lines = [line for line in result.stdout.splitlines() if line.strip()]
        self.assertTrue(lines)
        findings = [json.loads(line) for line in lines]
        lint_ids = {f["lint"] for f in findings}
        self.assertIn("banned_phrases", lint_ids)
        self.assertIn("year_question_detector", lint_ids)

    def test_lint_cli_empty_stdin_exits_0_with_no_findings(self):
        result = subprocess.run(
            [sys.executable, str(SYSTEM / "conversation_lints.py")],
            input="",
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")


class NoBehaviorChangeGuardTests(unittest.TestCase):
    """Subtest 6: the conversation store/lints have exactly ONE live consumer.

    v150 (issue #115) shipped this module pair as infrastructure with no
    consumer at all. v153 (issue #116) gave it exactly one:
    ``conversation_delivery`` — the turn engine — which ``process_answer``
    reaches lazily. The guard's purpose is unchanged: keep the store and the
    lint engine from acquiring ad-hoc callers that would fork the assembly
    order or the lint list. Any NEW name appearing here is a review question,
    not a test to relax.
    """

    def test_no_other_module_imports_conversation_or_conversation_lints(self):
        pattern = re.compile(r'^\s*(?:from|import)\s+conversation(?:_lints)?\b', re.MULTILINE)
        # conversation_delivery.py (v153) is the sanctioned runtime consumer;
        # arc_planner.py (issue #118, Wave 2) is the planning consumer: it reads
        # the arc-card container and the interaction definition through this
        # module's helpers rather than re-deriving either. The guard's point
        # stands — no OTHER module may reach into the store.
        exempt = {
            "lifehug.py",
            "conversation.py",
            "conversation_lints.py",
            "conversation_delivery.py",
            "arc_planner.py",
            # issue #120 (eval harness): the contract's own sanctioned
            # consumer — imports conversation_lints (Layer 1 authority) and
            # conversation (framework text/prompt readers) for the goldens/
            # router-fixture/judge/persona runner. Never re-derives lint
            # logic (recurring-defect doctrine).
            "interaction_evals.py",
            # ADR 0018: the independently registered Question Candidate child
            # composes Conversation behavior and imports its canonical lint
            # engine. No Conversation definition/session/delivery code is
            # copied into the child.
            "question_candidate.py",
            # ADR 0021: Focus Candidate is another independently registered
            # Conversation child and imports only the canonical lint engine.
            "focus_candidate.py",
            # ADR 0022: Entity Candidate is the typed entity-roster child;
            # runtime alone consumes the inherited lint authority.
            "entity_candidate.py",
            # ADR 0023: Arc Walk is the arc-walking child. It imports
            # conversation ONLY for the closed ARC_INTENT_KINDS vocabulary and
            # the arc-card container reader — the same "read the definition
            # through this module's helpers rather than re-deriving it"
            # rationale arc_planner.py carries above. No session, delivery, or
            # lint logic is copied into the child.
            "arc_walk.py",
            # v196 (ruling 6, arc learning): the weekly judgment step reads
            # SESSION DOCUMENTS to compute what each arc-card intent kind
            # yielded — through this module's own list_sessions/load_session
            # helpers rather than re-deriving the store, the same rationale
            # arc_planner.py carries above. It writes nothing here.
            "question_judgment.py",
        }
        offenders = []
        for path in sorted(SYSTEM.glob("*.py")):
            if path.name in exempt:
                continue
            text = path.read_text(encoding="utf-8")
            if pattern.search(text):
                offenders.append(path.name)
        self.assertEqual(offenders, [])

    def test_lifehug_py_only_references_the_new_modules_as_dispatch_strings(self):
        text = (SYSTEM / "lifehug.py").read_text(encoding="utf-8")
        self.assertNotRegex(text, r'^\s*(?:from|import)\s+conversation(?:_lints)?\b')
        self.assertIn('"conversation.py"', text)
        self.assertIn('"conversation_lints.py"', text)




class BuilderSlotRegressionTests(unittest.TestCase):
    """No builder may emit an unfilled {slot} from a definition file (the
    fixture-vs-real-file seam defect caught at the #126/#127 rebase)."""

    def test_turn_prompt_has_no_unfilled_slots(self):
        import re
        session = BuilderTests()._sample_session()
        session["turns"] = [{"role": "user", "text": "we drove the blue truck", "ts": "2026-08-11T00:00:00Z", "channel": "telegram"}]
        prompt = conversation.build_turn_prompt({"session": session})
        leftovers = re.findall(r"\{[a-z_]+\}", prompt)
        allowed = {"{placeholder}"}  # the file's own meta-sentence about slots
        self.assertFalse([m for m in leftovers if m not in allowed], leftovers)

    def test_router_and_arc_prompts_embed_inputs(self):
        rp = conversation.build_router_prompt({"message": "slot-guard probe", "session_open": True})
        self.assertIn("slot-guard probe", rp)
        ap = conversation.build_arc_prompt({"question": {"id": "Z9", "text": "probe?", "category": "A", "focus": "my-life"}, "record_summary": "rs", "gap_inputs": []})
        self.assertIn("Z9", ap)


if __name__ == "__main__":
    unittest.main()
