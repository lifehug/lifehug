"""v158 / issue #120 — the Conversation Interaction eval harness.

Four layers over `interactions/conversation/evals/`: (1) deterministic
lints (`conversation_lints`, extended here with the `presupposing` grammar
class + seam_ok exemption), (2) router fixtures + scorer, (3)
golden-transcript property assertions, (4) judge rubrics + personas
(model-backed, keyless-skippable). No network in this file, ever — every
model-backed path is exercised with a fake `ai_call`/`status_resolver`,
never the real `ai_provider.call_ai`.

Synthetic data only; NEVER references ~/Workspace/dave.
"""

from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SYSTEM = ROOT / "system"
sys.path.insert(0, str(SYSTEM))
sys.path.insert(0, str(ROOT / "tests"))

from tempdirs import root_parent_tmp  # noqa: E402
import conversation_lints  # noqa: E402
import interaction_evals as ie  # noqa: E402
from ai_provider import ProviderStatus  # noqa: E402

READY = lambda *a, **k: ProviderStatus("test", "test-model", True, "forced ready for tests")  # noqa: E731
NOT_READY = lambda *a, **k: ProviderStatus("agent-task", "test-model", False, "forced offline for tests")  # noqa: E731


def _fake_router_ai_call(intent: str):
    def _call(prompt: str, model: str) -> str:
        return json.dumps({"intent": intent, "confidence": 0.95})
    return _call


def _fake_judge_ai_call(all_pass: bool = True):
    def _call(prompt: str, model: str) -> str:
        clauses = [line.split(".", 1)[0] for line in prompt.splitlines() if line.strip() and line.strip()[0].isdigit()]
        verdicts = {c: all_pass for c in clauses[:13]}
        return json.dumps({"verdicts": verdicts})
    return _call


# --------------------------------------------------------------------------
# Layer 1 — the presupposing grammar class + seam_ok (issue #120 extension)
# --------------------------------------------------------------------------


class PresupposingLintTests(unittest.TestCase):
    def test_presupposing_lead_in_is_flagged(self):
        findings = conversation_lints.lint_turn("What made you decide to leave the company?")
        self.assertTrue(any(
            f["lint"] == "question_grammar_audit" and "presupposing" in f["detail"] for f in findings
        ))

    def test_why_did_you_decide_is_flagged(self):
        findings = conversation_lints.lint_turn("Why did you decide to move that year?")
        self.assertTrue(any(
            f["lint"] == "question_grammar_audit" and "presupposing" in f["detail"] for f in findings
        ))

    def test_a_ted_question_is_not_presupposing(self):
        findings = conversation_lints.lint_turn("Tell me what happened next.")
        self.assertFalse(any(f["lint"] == "question_grammar_audit" for f in findings))

    def test_seam_ok_suppresses_closed_question_finding(self):
        findings = conversation_lints.lint_turn("Did you like it?", seam_ok=True)
        self.assertFalse(any(f["lint"] == "question_grammar_audit" for f in findings))

    def test_seam_ok_suppresses_presupposing_finding(self):
        findings = conversation_lints.lint_turn(
            "What made you decide to leave the company?", seam_ok=True
        )
        self.assertFalse(any(f["lint"] == "question_grammar_audit" for f in findings))

    def test_seam_ok_does_not_suppress_other_lints(self):
        findings = conversation_lints.lint_turn(
            "That must have been so hard. Did you like it?", seam_ok=True
        )
        self.assertTrue(any(f["lint"] == "banned_phrases" for f in findings))
        self.assertFalse(any(f["lint"] == "question_grammar_audit" for f in findings))

    def test_default_seam_ok_is_false_unchanged_runtime_behavior(self):
        findings = conversation_lints.lint_turn("Did you like it?")
        self.assertTrue(any(f["lint"] == "question_grammar_audit" for f in findings))

    def test_lint_transcript_reads_seam_ok_from_turn_annotations(self):
        turns = [
            {"role": "user", "text": "It was a long story about the farm that day, honestly."},
            {"role": "lifehug", "text": "Did you like it?",
             "annotations": {"seam_ok": True}},
        ]
        findings = conversation_lints.lint_transcript(turns)
        self.assertFalse(any(f["lint"] == "question_grammar_audit" for f in findings))

    def test_lint_transcript_defaults_seam_ok_false_without_annotations(self):
        turns = [
            {"role": "user", "text": "It was a long story about the farm that day, honestly."},
            {"role": "lifehug", "text": "Did you like it?"},
        ]
        findings = conversation_lints.lint_transcript(turns)
        self.assertTrue(any(f["lint"] == "question_grammar_audit" for f in findings))


# --------------------------------------------------------------------------
# lints.yaml loader subset — router_gates.* flat dotted keys
# --------------------------------------------------------------------------


class LintsYamlLoaderTests(unittest.TestCase):
    def test_router_gates_are_flat_dotted_keys_never_nested(self):
        text = (ROOT / "interactions/conversation/evals/lints.yaml").read_text(encoding="utf-8")
        active_lines = [line for line in text.splitlines() if line.strip() and not line.strip().startswith("#")]
        self.assertFalse(any(line.strip() == "router_gates:" for line in active_lines))
        self.assertIn("router_gates.answer.precision: 0.85", text)

    def test_load_router_gates_casts_to_float_by_class(self):
        gates = ie.load_router_gates()
        self.assertIn("answer", gates)
        self.assertIsInstance(gates["answer"]["precision"], float)
        self.assertIsInstance(gates["answer"]["recall"], float)
        for intent in ie.VALID_ROUTER_INTENTS:
            self.assertIn(intent, gates)

    def test_load_router_gates_ignores_malformed_dotted_keys(self):
        gates = ie.load_router_gates({"router_gates.answer": "0.9", "router_gates.answer.precision": "0.9"})
        self.assertEqual(gates, {"answer": {"precision": 0.9}})

    def test_load_router_gates_picks_up_binding_accuracy(self):
        """issue #169 / ADR 0017 — accuracy is a NEW recognized metric
        (alongside precision/recall), needed for router_gates.binding.*."""
        gates = ie.load_router_gates({"router_gates.binding.accuracy": "0.85"})
        self.assertEqual(gates, {"binding": {"accuracy": 0.85}})

    def test_committed_lints_yaml_declares_binding_accuracy_gate(self):
        gates = ie.load_router_gates()
        self.assertIn("binding", gates)
        self.assertIn("accuracy", gates["binding"])


# --------------------------------------------------------------------------
# Layer 2 — router fixtures: schema + scorer + gates
# --------------------------------------------------------------------------


class RouterFixtureSchemaTests(unittest.TestCase):
    def test_committed_fixtures_validate_clean(self):
        fixtures = ie.load_router_fixtures()
        self.assertGreaterEqual(len(fixtures), 5)
        self.assertEqual(ie.validate_router_fixtures(fixtures), [])

    def test_all_five_intents_are_represented(self):
        fixtures = ie.load_router_fixtures()
        seen = {f["intent"] for f in fixtures}
        self.assertEqual(seen, ie.VALID_ROUTER_INTENTS)

    def test_missing_field_is_flagged(self):
        errors = ie.validate_router_fixture({"text": "hi", "session_open": True})
        self.assertTrue(any("intent" in e for e in errors))

    def test_bad_intent_is_flagged(self):
        errors = ie.validate_router_fixture({"text": "hi", "session_open": True, "intent": "maybe"})
        self.assertTrue(any("intent" in e for e in errors))

    def test_non_bool_session_open_is_flagged(self):
        errors = ie.validate_router_fixture({"text": "hi", "session_open": "yes", "intent": "answer"})
        self.assertTrue(any("session_open" in e for e in errors))

    def test_empty_list_is_flagged(self):
        self.assertTrue(ie.validate_router_fixtures([]))

    def test_non_list_is_flagged(self):
        self.assertTrue(ie.validate_router_fixtures({"not": "a list"}))


class RouterFixtureRosterSchemaTests(unittest.TestCase):
    """issue #169 / ADR 0017 (the thread binder) — the additive
    threads/target pair on router_fixtures.json entries."""

    VALID = {
        "text": "It was my uncle who built it.",
        "session_open": True,
        "intent": "answer",
        "threads": [
            {"id": "t1", "question": "Who built it?", "last_exchange": "user: no idea", "awaiting_ask": True},
            {"id": "t2", "question": "What was the trip like?", "last_exchange": "user: long", "awaiting_ask": False},
        ],
        "target": "t1",
    }

    def test_threads_bearing_fixture_validates_clean(self):
        self.assertEqual(ie.validate_router_fixture(self.VALID), [])

    def test_target_new_is_valid(self):
        entry = dict(self.VALID, target="new")
        self.assertEqual(ie.validate_router_fixture(entry), [])

    def test_target_not_in_roster_is_flagged(self):
        entry = dict(self.VALID, target="not-a-thread")
        errors = ie.validate_router_fixture(entry)
        self.assertTrue(any("target" in e for e in errors))

    def test_target_without_threads_is_flagged(self):
        entry = {"text": "hi", "session_open": True, "intent": "answer", "target": "t1"}
        errors = ie.validate_router_fixture(entry)
        self.assertTrue(any("target" in e for e in errors))

    def test_threads_present_but_target_missing_is_flagged(self):
        entry = {k: v for k, v in self.VALID.items() if k != "target"}
        errors = ie.validate_router_fixture(entry)
        self.assertTrue(any("target" in e for e in errors))

    def test_empty_threads_list_is_flagged(self):
        entry = dict(self.VALID, threads=[])
        errors = ie.validate_router_fixture(entry)
        self.assertTrue(any("threads" in e for e in errors))

    def test_thread_candidate_missing_id_is_flagged(self):
        entry = dict(self.VALID, threads=[{"question": "q", "last_exchange": "x", "awaiting_ask": False}])
        errors = ie.validate_router_fixture(entry)
        self.assertTrue(any("id" in e for e in errors))

    def test_no_threads_no_target_is_still_the_pre_169_shape(self):
        """The back-compat guarantee: fixtures with neither key validate
        exactly as they did before issue #169."""
        entry = {"text": "Sounds good, let's keep going.", "session_open": True, "intent": "continue_session"}
        self.assertEqual(ie.validate_router_fixture(entry), [])

    def test_all_committed_fixtures_still_validate_clean(self):
        fixtures = ie.load_router_fixtures()
        self.assertEqual(ie.validate_router_fixtures(fixtures), [])

    def test_at_least_one_committed_fixture_carries_a_roster(self):
        fixtures = ie.load_router_fixtures()
        self.assertTrue(any(f.get("threads") for f in fixtures))


class RouterScorerTests(unittest.TestCase):
    FIXTURES = [
        {"text": "a", "session_open": True, "intent": "answer"},
        {"text": "b", "session_open": True, "intent": "answer"},
        {"text": "c", "session_open": False, "intent": "new_story"},
        {"text": "d", "session_open": True, "intent": "continue_session"},
    ]

    def test_perfect_predictions_score_1_0(self):
        predictions = [{"text": f["text"], "predicted": f["intent"]} for f in self.FIXTURES]
        scores = ie.score_predictions(self.FIXTURES, predictions)
        self.assertEqual(scores["answer"]["precision"], 1.0)
        self.assertEqual(scores["answer"]["recall"], 1.0)
        self.assertEqual(scores["answer"]["tp"], 2)

    def test_false_positive_lowers_precision_of_the_predicted_class(self):
        predictions = [
            {"text": "a", "predicted": "answer"},
            {"text": "b", "predicted": "continue_session"},  # wrong: true is "answer"
            {"text": "c", "predicted": "new_story"},
            {"text": "d", "predicted": "continue_session"},
        ]
        scores = ie.score_predictions(self.FIXTURES, predictions)
        self.assertEqual(scores["answer"]["recall"], 0.5)
        # continue_session got 1 correct (d) + 1 false positive (b)
        self.assertEqual(scores["continue_session"]["precision"], 0.5)

    def test_missing_prediction_counts_as_a_false_negative(self):
        predictions = [{"text": "a", "predicted": "answer"}]
        scores = ie.score_predictions(self.FIXTURES, predictions)
        self.assertEqual(scores["answer"]["fn"], 1)  # "b" never predicted

    def test_none_precision_recall_when_class_never_appears(self):
        scores = ie.score_predictions(self.FIXTURES, [])
        self.assertIsNone(scores["out_of_scope"]["precision"])
        self.assertIsNone(scores["out_of_scope"]["recall"])

    def test_unmatched_predictions_are_reported_not_dropped(self):
        predictions = [{"text": "not-a-fixture", "predicted": "answer"}]
        scores = ie.score_predictions(self.FIXTURES, predictions)
        self.assertIn("not-a-fixture", scores["_unmatched"])

    def test_check_router_gates_passes_when_scores_clear_thresholds(self):
        predictions = [{"text": f["text"], "predicted": f["intent"]} for f in self.FIXTURES]
        scores = ie.score_predictions(self.FIXTURES, predictions)
        gates = {"answer": {"precision": 0.9, "recall": 0.9}}
        self.assertEqual(ie.check_router_gates(scores, gates), [])

    def test_check_router_gates_fails_when_below_threshold(self):
        predictions = [
            {"text": "a", "predicted": "answer"},
            {"text": "b", "predicted": "continue_session"},
            {"text": "c", "predicted": "new_story"},
            {"text": "d", "predicted": "continue_session"},
        ]
        scores = ie.score_predictions(self.FIXTURES, predictions)
        gates = {"answer": {"recall": 0.85}}
        failures = ie.check_router_gates(scores, gates)
        self.assertEqual(len(failures), 1)
        self.assertIn("router_gates.answer.recall", failures[0])

    def test_check_router_gates_ignores_unconfigured_classes(self):
        scores = ie.score_predictions(self.FIXTURES, [])
        self.assertEqual(ie.check_router_gates(scores, {}), [])

    def test_gate_fails_when_class_has_no_predictions_at_all(self):
        scores = ie.score_predictions(self.FIXTURES, [])
        failures = ie.check_router_gates(scores, {"answer": {"recall": 0.5}})
        self.assertTrue(failures)


class BindingScorerTests(unittest.TestCase):
    """issue #169 / ADR 0017 (the thread binder) — score_binding_predictions."""

    FIXTURES = [
        {"text": "a", "session_open": True, "intent": "answer",
         "threads": [{"id": "t1", "question": "q1", "last_exchange": "x", "awaiting_ask": True}],
         "target": "t1"},
        {"text": "b", "session_open": True, "intent": "answer",
         "threads": [{"id": "t2", "question": "q2", "last_exchange": "y", "awaiting_ask": False}],
         "target": "new"},
        {"text": "c", "session_open": False, "intent": "new_story"},  # no roster — excluded from binding
    ]

    def test_perfect_binding_scores_1_0(self):
        predictions = [
            {"text": "a", "predicted": "answer", "predicted_target": "t1"},
            {"text": "b", "predicted": "answer", "predicted_target": "new"},
            {"text": "c", "predicted": "new_story"},
        ]
        scores = ie.score_binding_predictions(self.FIXTURES, predictions)
        self.assertEqual(scores["binding"]["total"], 2)
        self.assertEqual(scores["binding"]["correct"], 2)
        self.assertEqual(scores["binding"]["accuracy"], 1.0)

    def test_no_roster_fixture_never_counted(self):
        predictions = [{"text": "c", "predicted": "new_story", "predicted_target": "some-hallucinated-id"}]
        scores = ie.score_binding_predictions(self.FIXTURES, predictions)
        self.assertEqual(scores["binding"]["total"], 0)

    def test_wrong_target_lowers_accuracy(self):
        predictions = [
            {"text": "a", "predicted": "answer", "predicted_target": "wrong-id"},
            {"text": "b", "predicted": "answer", "predicted_target": "new"},
        ]
        scores = ie.score_binding_predictions(self.FIXTURES, predictions)
        self.assertEqual(scores["binding"]["accuracy"], 0.5)

    def test_no_predictions_at_all_is_none_accuracy(self):
        scores = ie.score_binding_predictions(self.FIXTURES, [])
        self.assertIsNone(scores["binding"]["accuracy"])
        self.assertEqual(scores["binding"]["total"], 0)
        # both threads-bearing fixtures went unmatched — never silently dropped.
        self.assertEqual(set(scores["binding"]["_unmatched"]), {"a", "b"})

    def test_check_router_gates_enforces_binding_accuracy_generically(self):
        """The whole point of reusing check_router_gates: no second gate
        checker exists for binding."""
        predictions = [
            {"text": "a", "predicted": "answer", "predicted_target": "wrong-id"},
            {"text": "b", "predicted": "answer", "predicted_target": "new"},
        ]
        scores = ie.score_binding_predictions(self.FIXTURES, predictions)
        failures = ie.check_router_gates(scores, {"binding": {"accuracy": 0.85}})
        self.assertEqual(len(failures), 1)
        self.assertIn("router_gates.binding.accuracy", failures[0])


class CommittedSamplePredictionsProveGateMathTests(unittest.TestCase):
    """The contract's own words: 'the scorer + a committed sample predictions
    fixture prove the gate math deterministically' — until a live provider
    exists. This is the keyless, always-run proof."""

    def test_committed_sample_predictions_clear_every_configured_gate(self):
        fixtures = ie.load_router_fixtures()
        predictions = ie.load_router_sample_predictions()
        gates = ie.load_router_gates()
        scores = ie.score_predictions(fixtures, predictions)
        scores.update(ie.score_binding_predictions(fixtures, predictions))
        self.assertEqual(ie.check_router_gates(scores, gates), [])

    def test_corrupting_one_class_trips_the_gate(self):
        fixtures = ie.load_router_fixtures()
        predictions = [dict(p) for p in ie.load_router_sample_predictions()]
        flipped = 0
        for p in predictions:
            if p["predicted"] == "answer" and flipped < 3:
                p["predicted"] = "continue_session"
                flipped += 1
        gates = ie.load_router_gates()
        scores = ie.score_predictions(fixtures, predictions)
        scores.update(ie.score_binding_predictions(fixtures, predictions))
        failures = ie.check_router_gates(scores, gates)
        self.assertTrue(any("router_gates.answer" in f for f in failures))

    def test_corrupting_binding_trips_the_binding_gate(self):
        """issue #169 / ADR 0017 — the thread binder's own gate math proof,
        same idiom as test_corrupting_one_class_trips_the_gate above."""
        fixtures = ie.load_router_fixtures()
        predictions = [dict(p) for p in ie.load_router_sample_predictions()]
        flipped = 0
        for p in predictions:
            if p.get("predicted_target") and flipped < 3:
                p["predicted_target"] = "not-a-real-thread-id"
                flipped += 1
        self.assertEqual(flipped, 3, "fixture drift: expected >=3 threads-bearing sample predictions")
        gates = ie.load_router_gates()
        scores = ie.score_predictions(fixtures, predictions)
        scores.update(ie.score_binding_predictions(fixtures, predictions))
        failures = ie.check_router_gates(scores, gates)
        self.assertTrue(any("router_gates.binding" in f for f in failures))


class DeterministicSafeDefaultTests(unittest.TestCase):
    """Layer 2's always-on, keyless offline evaluation: router.md's own
    safe-default rule, proven directly rather than gated against
    router_gates.* (which targets a real classifier — see the module
    docstring for why)."""

    def test_open_session_fixtures_predict_continue_session(self):
        fixtures = [{"text": "x", "session_open": True, "intent": "answer"}]
        predictions = ie.deterministic_router_predictions(fixtures)
        self.assertEqual(predictions[0]["predicted"], "continue_session")

    def test_closed_session_fixtures_predict_new_story_terminal_fallback(self):
        fixtures = [{"text": "x", "session_open": False, "intent": "out_of_scope"}]
        predictions = ie.deterministic_router_predictions(fixtures)
        self.assertEqual(predictions[0]["predicted"], "new_story")

    def test_check_deterministic_safe_default_passes_on_committed_fixtures(self):
        fixtures = ie.load_router_fixtures()
        predictions = ie.deterministic_router_predictions(fixtures)
        self.assertEqual(ie.check_deterministic_safe_default(fixtures, predictions), [])

    def test_check_deterministic_safe_default_flags_a_regression(self):
        fixtures = [{"text": "x", "session_open": True, "intent": "answer"}]
        bad_predictions = [{"text": "x", "predicted": "new_story"}]
        errors = ie.check_deterministic_safe_default(fixtures, bad_predictions)
        self.assertTrue(errors)

    def test_deterministic_predictions_never_call_the_network(self):
        # No ai_call is passed at all — a network call here would raise
        # (no keys configured in the test environment) rather than degrade.
        fixtures = ie.load_router_fixtures()
        predictions = ie.deterministic_router_predictions(fixtures)
        self.assertEqual(len(predictions), len(fixtures))


# --------------------------------------------------------------------------
# Layer 3 — golden transcripts: schema + Layer-1 lints + properties
# --------------------------------------------------------------------------


class GoldenSchemaTests(unittest.TestCase):
    def test_all_committed_goldens_load(self):
        goldens = ie.load_goldens()
        self.assertGreaterEqual(len(goldens), 3)

    def test_router_fixture_files_are_excluded_from_goldens(self):
        ids = {g.get("golden_id") for g in ie.load_goldens()}
        self.assertNotIn(None, ids)

    def test_missing_golden_id_is_flagged(self):
        errors = ie.validate_golden_schema({"mode": "chat", "register": "neutral",
                                             "arc": {"question_id": "A1", "intents": []},
                                             "turns": [{"role": "user", "text": "hi"}]})
        self.assertTrue(any("golden_id" in e for e in errors))

    def test_bad_mode_is_flagged(self):
        errors = ie.validate_golden_schema({"golden_id": "x", "mode": "sms", "register": "neutral",
                                             "arc": {"question_id": "A1", "intents": []},
                                             "turns": [{"role": "user", "text": "hi"}]})
        self.assertTrue(any("mode" in e for e in errors))

    def test_lifehug_turn_without_annotations_is_flagged(self):
        errors = ie.validate_golden_schema({
            "golden_id": "x", "mode": "chat", "register": "neutral",
            "arc": {"question_id": "A1", "intents": []},
            "turns": [{"role": "lifehug", "text": "hi"}],
        })
        self.assertTrue(any("annotations" in e for e in errors))

    def test_no_new_topic_mid_arc_requires_arc_topics(self):
        errors = ie.validate_golden_schema({
            "golden_id": "x", "mode": "chat", "register": "neutral",
            "arc": {"question_id": "A1", "intents": []},
            "turns": [{"role": "lifehug", "text": "hi?",
                       "annotations": {"kind": "opener", "properties": ["no_new_topic_mid_arc"]}}],
        })
        self.assertTrue(any("arc.topics" in e for e in errors))


class CommittedGoldensPassEveryDeclaredPropertyTests(unittest.TestCase):
    """Positive fixtures: every committed golden is a CORRECT reference
    transcript. Negative (deliberately-broken) fixtures for each checker
    live inline below, per the repo's own "passing + failing fixtures"
    convention (mirrors LintTests in test_v150_conversation_store.py)."""

    def test_every_committed_golden_passes_schema_lints_and_properties(self):
        for golden in ie.load_goldens():
            with self.subTest(golden_id=golden.get("golden_id")):
                self.assertEqual(ie.check_golden(golden), [])

    def test_all_properties_are_exercised_across_the_corpus(self):
        goldens = ie.load_goldens()
        covered = {
            p for g in goldens for _, t in ie._lifehug_turns(g)
            for p in ((t.get("annotations") or {}).get("properties") or [])
        }
        self.assertEqual(covered, ie.PROPERTY_IDS)


def _base_golden(turns, *, topics=None):
    arc = {"question_id": "Z1", "opening": None, "intents": []}
    if topics is not None:
        arc["topics"] = topics
    return {"golden_id": "synthetic", "mode": "chat", "register": "neutral", "arc": arc, "turns": turns}


class PropertyCheckerNegativeFixtureTests(unittest.TestCase):
    """Each property checker, proven to actually catch a violation."""

    def test_receipt_quotes_user_flags_a_paraphrased_receipt(self):
        golden = _base_golden([
            {"role": "user", "text": "Diesel and cut hay, mostly."},
            {"role": "lifehug", "text": "The smell of the tractor really landed for me.",
             "annotations": {"kind": "receipt", "quoted_span": "diesel fumes",
                              "properties": ["receipt_quotes_user"]}},
        ])
        errors = ie.check_golden_properties(golden)
        self.assertTrue(any("receipt_quotes_user" in "".join(errors) or "quoted_span" in e for e in errors))

    def test_no_new_topic_mid_arc_flags_an_out_of_set_topic(self):
        golden = _base_golden([
            {"role": "lifehug", "text": "Thanks for sharing.",
             "annotations": {"kind": "opener", "topic": "boat", "properties": ["no_new_topic_mid_arc"]}},
            {"role": "user", "text": "sure"},
            {"role": "lifehug", "text": "Let's talk about something else entirely.",
             "annotations": {"kind": "receipt", "topic": "unrelated_topic", "properties": []}},
        ], topics=["boat"])
        errors = ie._check_no_new_topic_mid_arc(golden)
        self.assertTrue(errors)

    def test_closing_has_takeaway_and_hook_flags_a_trailing_question(self):
        golden = _base_golden([
            {"role": "lifehug", "text": "That was a wonderful story. What else happened that day?",
             "annotations": {"kind": "closing", "takeaway": "x", "hook": "y",
                              "properties": ["closing_has_takeaway_and_hook"]}},
        ])
        errors = ie._check_closing_has_takeaway_and_hook(golden)
        self.assertTrue(any("trailing question" in e for e in errors))

    def test_closing_has_takeaway_and_hook_flags_missing_hook(self):
        golden = _base_golden([
            {"role": "lifehug", "text": "That was a wonderful story.",
             "annotations": {"kind": "closing", "takeaway": "x", "hook": "",
                              "properties": ["closing_has_takeaway_and_hook"]}},
        ])
        errors = ie._check_closing_has_takeaway_and_hook(golden)
        self.assertTrue(any("hook" in e for e in errors))

    def test_deflects_off_scope_flags_a_missing_off_scope_flag(self):
        golden = _base_golden([
            {"role": "user", "text": "What's the capital of Peru?"},
            {"role": "lifehug", "text": "That's outside what I do — I'm here for your story.",
             "annotations": {"kind": "deflection", "properties": ["deflects_off_scope"]}},
        ])
        errors = ie._check_deflects_off_scope(golden)
        self.assertTrue(errors)

    def test_deflects_off_scope_flags_wrong_kind(self):
        golden = _base_golden([
            {"role": "user", "text": "What's the capital of Peru?", "off_scope": True},
            {"role": "lifehug", "text": "The capital of Peru is Lima.",
             "annotations": {"kind": "receipt", "properties": ["deflects_off_scope"]}},
        ])
        errors = ie._check_deflects_off_scope(golden)
        self.assertTrue(errors)

    def test_demonstrated_knowledge_opener_shape_flags_two_questions(self):
        golden = _base_golden([
            {"role": "lifehug", "text": "You mentioned the farm before. What do you remember? Was it hard?",
             "annotations": {"kind": "opener", "properties": ["demonstrated_knowledge_opener_shape"]}},
        ])
        errors = ie._check_demonstrated_knowledge_opener_shape(golden)
        self.assertTrue(errors)

    def test_demonstrated_knowledge_opener_shape_flags_question_first(self):
        golden = _base_golden([
            {"role": "lifehug", "text": "What do you remember? You mentioned the farm before.",
             "annotations": {"kind": "opener", "properties": ["demonstrated_knowledge_opener_shape"]}},
        ])
        errors = ie._check_demonstrated_knowledge_opener_shape(golden)
        self.assertTrue(errors)

    def test_layer_1_lint_violation_in_a_golden_is_caught(self):
        golden = _base_golden([
            {"role": "lifehug", "text": "Did you like it? What year was that?",
             "annotations": {"kind": "opener", "properties": []}},
        ])
        errors = ie.check_golden(golden)
        self.assertTrue(errors)

    def test_seam_ok_true_lets_a_closed_seam_question_through(self):
        golden = _base_golden([
            {"role": "lifehug", "text": "Is there anything else on your mind today?",
             "annotations": {"kind": "deflection", "seam_ok": True, "properties": []}},
        ])
        self.assertEqual(ie.check_golden_lints(golden), [])

    def test_unknown_property_id_is_flagged(self):
        golden = _base_golden([
            {"role": "lifehug", "text": "Thanks for sharing.",
             "annotations": {"kind": "opener", "properties": ["not_a_real_property"]}},
        ])
        errors = ie.check_golden_properties(golden)
        self.assertTrue(any("unknown property" in e for e in errors))


# --------------------------------------------------------------------------
# Layer 4 — judge + personas: pure builders/parsers, keyless-skip semantics
# --------------------------------------------------------------------------


class JudgeBuilderTests(unittest.TestCase):
    def test_load_rubric_clauses_finds_all_thirteen(self):
        clauses = ie.load_rubric_clauses()
        self.assertEqual(len(clauses), ie.RUBRIC_CLAUSE_COUNT)
        self.assertEqual(clauses[0]["number"], 1)
        self.assertIn("question", clauses[0]["title"].lower())

    def test_build_judge_prompt_embeds_transcript_and_clauses(self):
        clauses = ie.load_rubric_clauses()[:2]
        prompt = ie.build_judge_prompt({
            "turns": [{"role": "user", "text": "hello there"}],
            "clause_order": clauses,
        })
        self.assertIn("hello there", prompt)
        self.assertIn(clauses[0]["title"], prompt)

    def test_parse_judge_response_valid(self):
        raw = json.dumps({"verdicts": {"1": True, "2": False}})
        self.assertEqual(ie.parse_judge_response(raw), {"1": True, "2": False})

    def test_parse_judge_response_strips_code_fence(self):
        raw = "```json\n" + json.dumps({"verdicts": {"1": True}}) + "\n```"
        self.assertEqual(ie.parse_judge_response(raw), {"1": True})

    def test_parse_judge_response_malformed_returns_none(self):
        self.assertIsNone(ie.parse_judge_response("not json"))
        self.assertIsNone(ie.parse_judge_response(json.dumps({"no_verdicts_key": 1})))
        self.assertIsNone(ie.parse_judge_response(123))


class PersonaBuilderTests(unittest.TestCase):
    def test_build_persona_prompt_embeds_persona_description(self):
        prompt = ie.build_persona_prompt("terse", "A terse persona description.")
        self.assertIn("A terse persona description.", prompt)
        self.assertIn("terse", prompt)

    def test_parse_persona_response_valid(self):
        raw = json.dumps({"turns": [{"role": "user", "text": "hi"}, {"role": "lifehug", "text": "hello"}]})
        turns = ie.parse_persona_response(raw)
        self.assertEqual(len(turns), 2)

    def test_parse_persona_response_drops_malformed_turns_keeps_good_ones(self):
        raw = json.dumps({"turns": [{"role": "user", "text": "hi"}, {"role": "bad"}, "not a dict"]})
        turns = ie.parse_persona_response(raw)
        self.assertEqual(turns, [{"role": "user", "text": "hi"}])

    def test_parse_persona_response_malformed_returns_none(self):
        self.assertIsNone(ie.parse_persona_response("not json"))
        self.assertIsNone(ie.parse_persona_response(json.dumps({"turns": []})))


class ObservationCheckerTests(unittest.TestCase):
    def test_deferral_passes_when_first_reply_is_question_free(self):
        turns = [{"role": "user", "text": "my mom passed last month"},
                 {"role": "lifehug", "text": "I'm holding that with you. No rush at all."}]
        self.assertEqual(ie._check_deferral(turns), [])

    def test_deferral_fails_when_first_reply_asks_a_question(self):
        turns = [{"role": "user", "text": "my mom passed last month"},
                 {"role": "lifehug", "text": "I'm so sorry. What was she like?"}]
        self.assertTrue(ie._check_deferral(turns))

    def test_back_off_passes_when_a_later_turn_is_question_free(self):
        turns = [
            {"role": "lifehug", "text": "Tell me more?"},
            {"role": "user", "text": "still stuck on the same thing"},
            {"role": "lifehug", "text": "What else about it?"},
            {"role": "user", "text": "still the same thing again"},
            {"role": "lifehug", "text": "Let's set that down for now. We can pick it back up whenever you're ready."},
        ]
        self.assertEqual(ie._check_back_off(turns), [])

    def test_back_off_fails_when_every_later_turn_keeps_probing(self):
        turns = [
            {"role": "lifehug", "text": "Tell me more?"},
            {"role": "user", "text": "still stuck"},
            {"role": "lifehug", "text": "What else?"},
            {"role": "user", "text": "still stuck again"},
            {"role": "lifehug", "text": "But what caused it?"},
        ]
        self.assertTrue(ie._check_back_off(turns))

    def test_no_hard_stop_passes_when_session_exceeds_target(self):
        turns = [{"role": "user", "text": f"msg {i}"} for i in range(5)]
        self.assertEqual(ie._check_no_hard_stop(turns), [])

    def test_no_hard_stop_fails_when_session_stops_at_target(self):
        turns = [{"role": "user", "text": f"msg {i}"} for i in range(3)]
        self.assertTrue(ie._check_no_hard_stop(turns))


class KeylessSkipSemanticsTests(unittest.TestCase):
    """No network in this test class, ever — fake providers per repo convention."""

    def test_run_router_live_skips_without_a_ready_provider(self):
        result = ie.run_router_live(ie.load_router_fixtures(), status_resolver=lambda *a, **k: NOT_READY())
        self.assertEqual(result["status"], "skipped")

    def test_run_router_live_runs_with_a_forced_ready_provider_and_fake_ai_call(self):
        fixtures = [{"text": "x", "session_open": True, "intent": "continue_session"}]
        result = ie.run_router_live(
            fixtures, ai_call=_fake_router_ai_call("continue_session"), status_resolver=lambda *a, **k: READY()
        )
        self.assertEqual(result["status"], "ran")
        self.assertIn("model", result)

    def test_run_judge_skips_without_a_ready_provider(self):
        result = ie.run_judge(ie.load_goldens(), status_resolver=lambda *a, **k: NOT_READY())
        self.assertEqual(result["status"], "skipped")

    def test_run_judge_runs_with_fake_ai_call(self):
        result = ie.run_judge(
            ie.load_goldens()[:1], ai_call=_fake_judge_ai_call(True), status_resolver=lambda *a, **k: READY()
        )
        self.assertEqual(result["status"], "ran")
        self.assertEqual(len(result["results"]), 1)
        self.assertEqual(result["results"][0]["failed_clauses"], [])

    def test_run_judge_records_failed_clauses(self):
        result = ie.run_judge(
            ie.load_goldens()[:1], ai_call=_fake_judge_ai_call(False), status_resolver=lambda *a, **k: READY()
        )
        self.assertTrue(result["results"][0]["failed_clauses"])

    def test_run_persona_skips_without_a_ready_provider(self):
        result = ie.run_persona("terse", status_resolver=lambda *a, **k: NOT_READY())
        self.assertEqual(result["status"], "skipped")

    def test_run_persona_runs_with_fake_ai_call(self):
        def fake_call(prompt, model):
            return json.dumps({"turns": [
                {"role": "lifehug", "text": "Thanks for telling me that."},
                {"role": "user", "text": "sure"},
            ]})
        result = ie.run_persona("terse", ai_call=fake_call, status_resolver=lambda *a, **k: READY())
        self.assertEqual(result["status"], "ran")
        self.assertIn("lint_findings", result)

    def test_run_persona_malformed_generation_is_reported_not_raised(self):
        result = ie.run_persona(
            "terse", ai_call=lambda p, m: "not json", status_resolver=lambda *a, **k: READY()
        )
        self.assertEqual(result.get("error"), "malformed_generation")

    def test_grief_fresh_has_deferral_observation(self):
        self.assertEqual(ie.NAMED_OBSERVATIONS["grief-fresh"], "deferral")

    def test_ruminator_has_back_off_observation(self):
        self.assertEqual(ie.NAMED_OBSERVATIONS["ruminator"], "back_off")

    def test_enthusiast_has_no_hard_stop_observation(self):
        self.assertEqual(ie.NAMED_OBSERVATIONS["enthusiast"], "no_hard_stop")

    def test_all_seven_personas_have_a_description_file(self):
        for persona in ie.PERSONAS:
            path = ROOT / "interactions/conversation/evals/personas" / f"{persona}.md"
            self.assertTrue(path.exists(), persona)


# --------------------------------------------------------------------------
# The orchestrator + emit-tasks
# --------------------------------------------------------------------------


class RunOrchestratorTests(unittest.TestCase):
    def test_run_is_keyless_green(self):
        code, report = ie.run()
        self.assertEqual(code, 0)
        joined = "\n".join(report)
        self.assertIn("Layer 1", joined)
        self.assertIn("Layer 2", joined)
        self.assertIn("Layer 3", joined)
        self.assertIn("Layer 4", joined)
        self.assertIn("SKIPPED", joined)
        self.assertNotIn("Traceback", joined)

    def test_run_reports_all_passed_and_all_skipped_distinctly(self):
        code, report = ie.run()
        joined = "\n".join(report)
        self.assertIn("PASSED", joined)
        self.assertIn("SUMMARY: PASSED", joined)


class EmitTasksTests(unittest.TestCase):
    def test_emit_tasks_writes_a_prompt_per_golden_and_per_persona(self):
        tmp = root_parent_tmp(self, ROOT, prefix="lifehug-evals-emit-")
        out_dir = tmp / "evals"
        manifest_path = ie.emit_tasks(out_dir)
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        judge_items = [i for i in manifest["items"] if i["task"] == "judge"]
        persona_items = [i for i in manifest["items"] if i["task"] == "persona"]
        self.assertEqual(len(judge_items), len(ie.load_goldens()))
        self.assertEqual(len(persona_items), len(ie.PERSONAS))
        for item in judge_items + persona_items:
            self.assertTrue((out_dir / item["prompt"]).exists())

    def test_run_with_emit_tasks_flag_writes_the_manifest(self):
        tmp = root_parent_tmp(self, ROOT, prefix="lifehug-evals-run-emit-")
        import unittest.mock as mock
        with mock.patch.object(ie, "AGENT_TASKS_DIR", tmp):
            code, report = ie.run(emit_tasks_flag=True)
        self.assertEqual(code, 0)
        self.assertTrue(any("Emitted judge/persona agent tasks" in line for line in report))
        self.assertTrue((tmp / "evals" / "manifest.json").exists())


# --------------------------------------------------------------------------
# CLI wiring — `lifehug.py conversation-evals`
# --------------------------------------------------------------------------


class CLITests(unittest.TestCase):
    def test_conversation_evals_help_lists_emit_tasks_flag(self):
        result = subprocess.run(
            [sys.executable, str(SYSTEM / "lifehug.py"), "conversation-evals", "--help"],
            capture_output=True, text=True, cwd=ROOT,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("--emit-tasks", result.stdout)

    def test_conversation_evals_runs_keyless_and_exits_0(self):
        result = subprocess.run(
            [sys.executable, str(SYSTEM / "lifehug.py"), "conversation-evals"],
            capture_output=True, text=True, cwd=ROOT,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("SUMMARY: PASSED", result.stdout)
        self.assertIn("SKIPPED", result.stdout)

    def test_interaction_evals_cli_runs_directly_too(self):
        result = subprocess.run(
            [sys.executable, str(SYSTEM / "interaction_evals.py")],
            capture_output=True, text=True, cwd=ROOT,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_command_is_classified_exactly_once(self):
        import lifehug
        self.assertIn("conversation-evals", lifehug.DIRECT_MUTATION_COMMANDS)
        self.assertNotIn("conversation-evals", lifehug.READ_ONLY_COMMANDS)
        self.assertNotIn("conversation-evals", lifehug.QUEUED_MUTATION_COMMANDS)


if __name__ == "__main__":
    unittest.main()
