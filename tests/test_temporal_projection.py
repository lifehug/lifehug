"""v220 — the calculated side (audited timeline build plan §5.3, §5.4, §7).

The projection is a materialized view: it can be deleted and rebuilt, it is
never edited as truth, and it may not quietly erase disagreement. These tests
pin the two refusals that carry that weight (a node with no inputs, a node
hiding its alternatives), the stable identities that make "answer once, update
everywhere" mechanical, and the input fingerprint that keeps incremental
recomputation an option without building the scheduler.

Synthetic data only; NEVER references ~/Workspace/dave.
"""

from __future__ import annotations

import ast
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "system"))

import temporal_claims as tc  # noqa: E402
import temporal_projection as tp  # noqa: E402

RULES = "timeline-rules:1"


def raised_finding_codes(path: Path) -> set[str]:
    """Every finding id the module actually raises, read out of its own AST."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    codes: set[str] = set()
    for node in ast.walk(tree):
        # Every construction of an error class counts, not only `raise` — a
        # module may build the error in a helper and raise it at the call site.
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", "")
        if not (name.endswith("Error") or name == "error"):
            continue
        if node.args and isinstance(node.args[0], ast.Constant):
            value = node.args[0].value
            if isinstance(value, str):
                codes.add(value)
    return codes


def node(**overrides) -> dict:
    base = {
        "node_id": tp.derive_node_id(
            node_kind="event", event_kind="married", subject_refs=["person/katie"]
        ),
        "node_kind": "event",
        "subject_refs": ["person/katie"],
        "event_kind": "married",
        "label": "Married Katie",
        "best_temporal_value": "1998-06",
        "input_claim_refs": ["claim:" + "a" * 24],
        "calculation_rule_version": RULES,
        "basis": "explicit",
        "confidence": 0.9,
    }
    base.update(overrides)
    return base


def work_item(**overrides) -> dict:
    base = {
        "kind": "precision_gap",
        "subject_ref": "person/katie",
        "event_ref": "node:married",
        "requested_field": "date",
        "prompt_intent": "narrow the marriage year to a month",
        "allowed_surfaces": ["timeline", "daily_question"],
        "person_value": 0.6,
        "system_value": 0.7,
        "created_at": "2026-08-26T10:00:00Z",
    }
    base.update(overrides)
    return base


class VocabularyTests(unittest.TestCase):
    def test_the_closed_vocabularies_are_the_plans(self):
        self.assertEqual(tp.NODE_KINDS, ("event", "period", "episode"))
        self.assertEqual(tp.CONFLICT_STATES, ("none", "alternatives", "contradicted"))
        self.assertEqual(
            tp.WORK_ITEM_KINDS,
            ("missing_anchor", "precision_gap", "contradiction", "identity_uncertain",
             "place_ambiguous", "tenure_ambiguous", "residence_overlap", "chain_gap",
             "same_event", "possible_overmerge"),
        )
        self.assertEqual(
            tp.WORK_ITEM_STATES,
            ("open", "offered", "answered", "resolved", "dismissed", "obsolete"),
        )
        self.assertEqual(
            tp.WORK_ITEM_SURFACES, ("timeline", "mirror", "whisper", "daily_question")
        )

    def test_a_node_renders_the_same_three_bases_the_claims_do(self):
        # Timeline shows exact vs calculated vs inferred (plan §8.1), and it is
        # the SAME vocabulary the claim carries — not a parallel one.
        self.assertEqual(tp.CLAIM_BASES, tc.CLAIM_BASES)

    def test_the_projection_has_one_named_path(self):
        self.assertTrue(tp.PROJECTION_FILE.startswith(tc.TEMPORAL_STATE_DIR + "/"))
        self.assertTrue(tp.WORK_ITEMS_FILE.startswith(tc.TEMPORAL_STATE_DIR + "/"))
        self.assertNotEqual(tp.PROJECTION_FILE, tp.WORK_ITEMS_FILE)


class NodeIdentityTests(unittest.TestCase):
    GOLDEN_NODE = "node:02b9c60c0aa6154990165d4f"
    GOLDEN_EPISODE = "node:b86ae5597406010c2363be9f"

    def test_the_golden_node_ids_hold(self):
        self.assertEqual(
            tp.derive_node_id(
                node_kind="event",
                event_kind="married",
                subject_refs=["person/katie", "person/self"],
            ),
            self.GOLDEN_NODE,
        )
        self.assertEqual(
            tp.derive_node_id(
                node_kind="episode",
                event_kind="job",
                subject_refs=["org/acme"],
                discriminator="2",
            ),
            self.GOLDEN_EPISODE,
        )

    def test_subject_order_does_not_change_the_node(self):
        self.assertEqual(
            tp.derive_node_id(
                node_kind="event", event_kind="married",
                subject_refs=["person/self", "person/katie"],
            ),
            self.GOLDEN_NODE,
        )

    def test_a_repeated_period_is_a_second_episode_not_the_same_one(self):
        # Plan §6.3: a repeated school or job period must not be collapsed into
        # one incompatible span.
        first = tp.derive_node_id(
            node_kind="episode", event_kind="job", subject_refs=["org/acme"],
            discriminator="1",
        )
        self.assertNotEqual(first, self.GOLDEN_EPISODE)

    def test_a_node_id_is_document_id_safe(self):
        identifier = tp.derive_node_id(
            node_kind="event", event_kind="met", subject_refs=["person/friend"]
        )
        self.assertNotIn("/", identifier)
        self.assertTrue(tc.is_safe_id(identifier))

    def test_the_identity_key_list_is_frozen(self):
        self.assertEqual(
            tp.NODE_IDENTITY_KEYS,
            ("node_kind", "event_kind", "subject_keys", "discriminator"),
        )


class NodeValidationTests(unittest.TestCase):
    def test_a_node_with_no_inputs_is_a_fabrication(self):
        with self.assertRaises(tp.TimelineNodeError) as caught:
            tp.validate_calculated_timeline_node(node(input_claim_refs=[]))
        self.assertEqual(caught.exception.code, "node_without_inputs")

    def test_a_node_may_not_hide_its_alternatives(self):
        # Plan §2.5: strong contradictions are preserved, never silently
        # resolved. A node holding alternates cannot declare itself settled.
        with self.assertRaises(tp.TimelineNodeError) as caught:
            tp.validate_calculated_timeline_node(
                node(alternate_values=["1999"], conflict_state="none")
            )
        self.assertEqual(caught.exception.code, "node_hides_alternatives")

    def test_alternatives_are_kept_when_the_conflict_is_declared(self):
        normalized = tp.validate_calculated_timeline_node(
            node(alternate_values=["1999", "1997"], conflict_state="contradicted")
        )
        self.assertEqual(len(normalized["alternate_values"]), 2)
        self.assertEqual(normalized["best_temporal_value"]["best"], "1998-06")
        self.assertEqual(normalized["conflict_state"], "contradicted")

    def test_a_node_names_the_rule_version_that_calculated_it(self):
        with self.assertRaises(tp.TimelineNodeError) as caught:
            tp.validate_calculated_timeline_node(node(calculation_rule_version=""))
        self.assertEqual(caught.exception.code, "node_needs_rule_version")

    def test_dates_go_through_chronology_and_nowhere_else(self):
        normalized = tp.validate_calculated_timeline_node(
            node(best_temporal_value="1984/1990")
        )
        value = normalized["best_temporal_value"]
        self.assertEqual((value["earliest"], value["latest"]), ("1984", "1990"))
        self.assertEqual(value["granularity"], "range")

    def test_an_unplaced_node_is_allowed_and_an_unusable_value_is_not(self):
        normalized = tp.validate_calculated_timeline_node(
            node(best_temporal_value=None)
        )
        self.assertIsNone(normalized["best_temporal_value"])
        with self.assertRaises(tp.TimelineNodeError) as caught:
            tp.validate_calculated_timeline_node(node(best_temporal_value="sometime"))
        self.assertEqual(caught.exception.code, "node_value_unusable")

    def test_the_fingerprint_is_filled_in_when_it_is_missing(self):
        normalized = tp.validate_calculated_timeline_node(node())
        self.assertEqual(
            normalized["input_fingerprint"],
            tp.derive_input_fingerprint(
                claim_ids=["claim:" + "a" * 24], calculation_rule_version=RULES
            ),
        )

    def test_the_round_trip_is_lossless(self):
        normalized = tp.validate_calculated_timeline_node(
            node(
                alternate_values=["1999"],
                conflict_state="alternatives",
                provenance_summary="one stated year, one witness year",
                model_version="test-model",
                input_constraint_refs=["constraint:" + "b" * 24],
                projection_generation=7,
            )
        )
        obj = tp.node_from_dict(normalized)
        self.assertEqual(tp.validate_calculated_timeline_node(obj.to_dict()), normalized)

    def test_the_tolerant_reader_never_raises(self):
        self.assertIsNone(tp.node_from_dict(None))
        self.assertIsNone(tp.node_from_dict({"node_kind": "event"}))


class FingerprintTests(unittest.TestCase):
    GOLDEN = "fp:5f374b6c0197b0c9a58791c9"

    def test_the_golden_fingerprint_holds(self):
        self.assertEqual(
            tp.derive_input_fingerprint(
                claim_ids=["claim:a", "claim:b"],
                constraint_ids=["constraint:c"],
                calculation_rule_version=RULES,
            ),
            self.GOLDEN,
        )

    def test_two_rebuilds_from_the_same_inputs_agree(self):
        # Plan §7: rebuilding twice from identical receipts, corrections, rules
        # and versions produces structurally identical output.
        self.assertEqual(
            tp.derive_input_fingerprint(
                claim_ids=["claim:b", "claim:a"],
                constraint_ids=["constraint:c"],
                calculation_rule_version=RULES,
            ),
            self.GOLDEN,
        )

    def test_a_changed_input_changes_the_fingerprint(self):
        self.assertNotEqual(
            tp.derive_input_fingerprint(
                claim_ids=["claim:a", "claim:b", "claim:c"],
                constraint_ids=["constraint:c"],
                calculation_rule_version=RULES,
            ),
            self.GOLDEN,
        )

    def test_a_changed_rule_version_changes_the_fingerprint(self):
        self.assertNotEqual(
            tp.derive_input_fingerprint(
                claim_ids=["claim:a", "claim:b"],
                constraint_ids=["constraint:c"],
                calculation_rule_version="timeline-rules:2",
            ),
            self.GOLDEN,
        )

    def test_a_constraint_is_part_of_what_a_node_was_calculated_from(self):
        self.assertNotEqual(
            tp.derive_input_fingerprint(
                claim_ids=["claim:a", "claim:b"], calculation_rule_version=RULES
            ),
            self.GOLDEN,
        )


class WorkItemTests(unittest.TestCase):
    GOLDEN = "work:8bf374db98a89911b4bb0722"

    def test_the_golden_work_item_id_holds(self):
        self.assertEqual(
            tp.derive_work_item_id(
                kind="precision_gap",
                subject_ref="person/katie",
                event_ref="node:married",
                requested_field="date",
            ),
            self.GOLDEN,
        )

    def test_one_identity_across_every_surface(self):
        # Plan §2.3, §5.4, §10: answering on Timeline closes the queue
        # candidate and vice versa, and the same item never competes with
        # itself as both main question and whisper.
        on_timeline = tp.validate_temporal_work_item(
            work_item(allowed_surfaces=["timeline"])
        )
        in_queue = tp.validate_temporal_work_item(
            work_item(allowed_surfaces=["daily_question"], state="offered",
                      combined_score=0.81)
        )
        self.assertEqual(on_timeline["work_item_id"], in_queue["work_item_id"])
        self.assertEqual(
            tp.surfaces_conflict([on_timeline, in_queue]), (self.GOLDEN,)
        )

    def test_rescoring_does_not_re_mint_the_item(self):
        first = tp.validate_temporal_work_item(work_item(person_value=0.2))
        rescored = tp.validate_temporal_work_item(
            work_item(person_value=0.9, context_fit=0.4, state="answered")
        )
        self.assertEqual(first["work_item_id"], rescored["work_item_id"])

    def test_a_gap_names_the_field_it_is_missing(self):
        for kind in ("missing_anchor", "precision_gap"):
            with self.subTest(kind=kind):
                with self.assertRaises(tp.TemporalWorkItemError) as caught:
                    tp.validate_temporal_work_item(
                        work_item(kind=kind, requested_field=None)
                    )
                self.assertEqual(
                    caught.exception.code, "work_item_needs_requested_field"
                )

    def test_a_contradiction_cites_the_claims_that_disagree(self):
        with self.assertRaises(tp.TemporalWorkItemError) as caught:
            tp.validate_temporal_work_item(
                work_item(kind="contradiction", requested_field=None,
                          claim_refs=["claim:" + "a" * 24])
            )
        self.assertEqual(caught.exception.code, "contradiction_needs_two_claims")
        normalized = tp.validate_temporal_work_item(
            work_item(
                kind="contradiction",
                requested_field=None,
                claim_refs=["claim:" + "a" * 24, "claim:" + "b" * 24],
                allowed_surfaces=["mirror"],
            )
        )
        self.assertEqual(len(normalized["claim_refs"]), 2)

    def test_a_contradiction_is_not_a_gap_wearing_the_wrong_type(self):
        # Plan §5.4: do not force contradictions into an API named only for
        # "gaps" — they are typed instances of one shape.
        self.assertIn("contradiction", tp.WORK_ITEM_KINDS)
        self.assertNotEqual(
            tp.derive_work_item_id(kind="contradiction", subject_ref="person/katie"),
            tp.derive_work_item_id(kind="precision_gap", subject_ref="person/katie"),
        )

    def test_an_item_about_nothing_is_not_a_question(self):
        with self.assertRaises(tp.TemporalWorkItemError) as caught:
            tp.validate_temporal_work_item(
                work_item(subject_ref=None, event_ref=None)
            )
        self.assertEqual(caught.exception.code, "work_item_needs_subject_or_event")

    def test_an_item_allowed_nowhere_is_invisible_work(self):
        with self.assertRaises(tp.TemporalWorkItemError) as caught:
            tp.validate_temporal_work_item(work_item(allowed_surfaces=[]))
        self.assertEqual(caught.exception.code, "work_item_needs_surface")
        with self.assertRaises(tp.TemporalWorkItemError) as caught:
            tp.validate_temporal_work_item(work_item(allowed_surfaces=["telegram"]))
        self.assertEqual(caught.exception.code, "unknown_work_item_surface")

    def test_loss_discovery_can_be_kept_out_of_the_daily_queue(self):
        # Plan §2.4: loss discovery is offer-only. The mechanism is the surface
        # list — the item simply does not name daily_question.
        normalized = tp.validate_temporal_work_item(
            work_item(
                kind="missing_anchor",
                subject_ref="area/losses",
                event_ref=None,
                requested_field="loss_discovery",
                allowed_surfaces=["timeline"],
                sensitivity=1.0,
            )
        )
        self.assertNotIn("daily_question", normalized["allowed_surfaces"])
        self.assertEqual(normalized["sensitivity"], 1.0)

    def test_scores_are_normalized_and_out_of_range_is_refused(self):
        normalized = tp.validate_temporal_work_item(work_item(combined_score=0.5))
        self.assertEqual(normalized["combined_score"], 0.5)
        with self.assertRaises(tp.TemporalWorkItemError) as caught:
            tp.validate_temporal_work_item(work_item(system_value=12))
        self.assertEqual(caught.exception.code, "score_out_of_range")

    def test_states_include_answered_resolved_and_obsolete(self):
        for state in ("offered", "answered", "resolved", "dismissed", "obsolete"):
            with self.subTest(state=state):
                self.assertEqual(
                    tp.validate_temporal_work_item(work_item(state=state))["state"],
                    state,
                )
        with self.assertRaises(tp.TemporalWorkItemError) as caught:
            tp.validate_temporal_work_item(work_item(state="overdue"))
        self.assertEqual(caught.exception.code, "unknown_work_item_state")

    def test_nothing_in_the_shape_records_a_due_date(self):
        # Plan §2.3, §8.1: open items are an invitation, never a debt.
        normalized = tp.validate_temporal_work_item(work_item())
        self.assertEqual(
            {k for k in normalized if "due" in k or "overdue" in k}, set()
        )

    def test_the_round_trip_is_lossless(self):
        normalized = tp.validate_temporal_work_item(
            work_item(node_ref="node:married", evidence_refs=["turn:4"],
                      combined_score=0.42)
        )
        obj = tp.work_item_from_dict(normalized)
        self.assertEqual(tp.validate_temporal_work_item(obj.to_dict()), normalized)
        self.assertEqual(obj.scores["combined_score"], 0.42)

    def test_the_tolerant_reader_never_raises(self):
        self.assertIsNone(tp.work_item_from_dict(None))
        self.assertIsNone(tp.work_item_from_dict({"kind": "nonsense"}))

    def test_the_identity_key_list_is_frozen(self):
        self.assertEqual(
            tp.WORK_ITEM_IDENTITY_KEYS,
            ("kind", "subject_key", "event_key", "requested_field"),
        )


class FindingIdTests(unittest.TestCase):
    def test_every_raised_finding_id_is_declared(self):
        raised = raised_finding_codes(ROOT / "system" / "temporal_projection.py")
        self.assertTrue(raised)
        self.assertEqual(raised - set(tp.ERROR_CODES), set())

    def test_no_declared_finding_id_is_dead(self):
        raised = raised_finding_codes(ROOT / "system" / "temporal_projection.py")
        inherited = {"confidence_out_of_range", "timestamp_unusable"}
        self.assertEqual(set(tp.ERROR_CODES) - raised - inherited, set())

    def test_the_public_surface_is_exported(self):
        for name in (
            "CalculatedTimelineNode",
            "TemporalWorkItem",
            "derive_node_id",
            "derive_work_item_id",
            "derive_input_fingerprint",
            "validate_calculated_timeline_node",
            "validate_temporal_work_item",
        ):
            with self.subTest(name=name):
                self.assertIn(name, tp.__all__)
                self.assertTrue(hasattr(tp, name))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
