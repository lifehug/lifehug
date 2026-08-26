"""Wave C1 — who is who, and which event is which (plan §2.5, §6.3, §10).

The §10 acceptance scenarios this file makes executable, in the plan's own
words:

* "'AJ' resolves to the known AJ when context makes that the high-confidence
  candidate; raw 'AJ' and the resolution evidence remain available."
* "An ambiguous name is retained as an unresolved claim and becomes a Mirror
  identity item rather than being dropped."
* "Katie first met, dating started, and marriage are distinct events with
  independent dates/ranges."
* "A recurring relationship or repeated school/job period is not collapsed
  into an incompatible single episode."
* "Retrying a successful or uncertain request creates no duplicate claim,
  person, event, question, or correction."

Plus the property everything above rests on: resolution is data ABOUT a claim
and never mutation OF it, because claim identity derives from the RAW mention.

Synthetic data only; NEVER references ~/Workspace/dave.
"""

from __future__ import annotations

import ast
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "system"))

import identity_resolution as ir
import temporal_claims as tc
import temporal_projection as tp

REV = "sha256:" + "2" * 64
REF = {"source_id": "sources/manual/2026-08-26-kitchen.md", "revision": REV}
EXT = "listener/schema:1/prompt:beadfeed/model:test-model"
NOW = "2026-08-26T10:00:00Z"
EVIDENCE = "claim:" + "a" * 24


def raised_finding_codes(path: Path) -> set[str]:
    """Every finding id the module actually raises, read out of its own AST."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    codes: set[str] = set()
    for node in ast.walk(tree):
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


def roster(*entities) -> dict:
    """An ``entity_roster.load_roster()``-shaped snapshot, synthetic."""
    return {"version": 1, "type": "person", "entities": list(entities)}


def person(name, *, slug=None, aliases=(), **extra) -> dict:
    entry = {
        "name": name,
        "slug": slug or name.strip().lower().replace(" ", "-"),
        "aliases": list(aliases),
        "qualifies": True,
    }
    entry.update(extra)
    return entry


def claim(**overrides) -> dict:
    base = {
        "source_ref": dict(REF),
        "source_kind": "conversation",
        "claim_type": "date",
        "subject_mention": "AJ",
        "event_kind": "birth",
        "temporal_value": "1984",
        "evidence": [{"quote": "AJ was born in 1984", "turn_ref": "turn:3"}],
        "basis": "explicit",
        "confidence": 0.9,
        "extractor_version": EXT,
        "created_at": NOW,
    }
    base.update(overrides)
    return base


# --------------------------------------------------------------------------
# The vocabularies and the error surface
# --------------------------------------------------------------------------


class VocabularyTests(unittest.TestCase):
    def test_the_three_verdicts_are_the_contracts(self):
        self.assertEqual(ir.RESOLUTIONS, ("same", "different", "uncertain"))

    def test_every_deterministic_rule_is_named(self):
        self.assertEqual(
            ir.DETERMINISTIC_REASONS,
            ("exact_ref", "roster_alias", "unique_name", "ambiguous_candidates", "no_candidate"),
        )
        # The model rung writes through the same contract, with its own reason.
        self.assertIn(ir.MODEL_REASON, ir.RESOLUTION_REASONS)
        for reason in ir.DETERMINISTIC_REASONS:
            self.assertIn(reason, ir.RESOLUTION_REASONS)

    def test_declared_error_codes_match_the_ones_the_module_raises(self):
        raised = raised_finding_codes(ROOT / "system" / "identity_resolution.py")
        declared = set(ir.ERROR_CODES)
        self.assertEqual(
            raised - declared, set(), "raised but undeclared identity findings"
        )
        # Codes raised by the shared helpers this module borrows (timestamps,
        # unit scores) are declared here too so a reader sees the full surface.
        self.assertEqual(
            declared - raised - {"timestamp_unusable", "score_out_of_range"},
            set(),
            "declared but never raised identity findings",
        )

    def test_identity_work_never_reaches_the_daily_question(self):
        # §2.5: Mirror's daily-question convergence is deliberately deferred.
        self.assertNotIn("daily_question", ir.IDENTITY_WORK_SURFACES)
        for surface in ir.IDENTITY_WORK_SURFACES:
            self.assertIn(surface, tp.WORK_ITEM_SURFACES)

    def test_relationship_transitions_are_the_plans_six_and_more(self):
        for kind in ("first_met", "dating_started", "engaged", "married",
                     "separated", "reconciled"):
            self.assertTrue(ir.is_relationship_event(kind), kind)
        self.assertFalse(ir.is_relationship_event("job"))


# --------------------------------------------------------------------------
# §10 — "'AJ' resolves to the known AJ ... raw 'AJ' and the evidence remain"
# --------------------------------------------------------------------------


class UnambiguousResolutionTests(unittest.TestCase):
    def setUp(self):
        self.roster = roster(
            person("AJ", aliases=["A.J."]),
            person("Della"),
            person("Bo"),
        )

    def test_aj_resolves_when_the_roster_makes_it_unambiguous(self):
        record = ir.resolve_mention("AJ", roster=self.roster, evidence_ref=EVIDENCE, now=NOW)
        self.assertEqual(record.resolution, "same")
        self.assertEqual(record.resolved_ref, "person/aj")
        self.assertEqual(record.reason, "unique_name")
        self.assertTrue(record.is_resolved())

    def test_the_raw_mention_and_the_evidence_survive_the_resolution(self):
        record = ir.resolve_mention("aj.", roster=self.roster, evidence_ref=EVIDENCE, now=NOW)
        self.assertEqual(record.mention, "aj.", "the raw mention is kept verbatim")
        self.assertEqual(record.mention_key, "aj")
        self.assertEqual(record.evidence_ref, EVIDENCE)
        self.assertTrue(record.reversible)

    def test_the_candidate_set_says_why_each_name_was_in_the_running(self):
        record = ir.resolve_mention("AJ", roster=self.roster, evidence_ref=EVIDENCE, now=NOW)
        self.assertEqual([c["ref"] for c in record.candidates], ["person/aj"])
        self.assertEqual(record.candidates[0]["basis"], "name")
        self.assertEqual(record.candidates[0]["name"], "AJ")

    def test_resolving_an_already_resolved_ref_is_idempotent(self):
        record = ir.resolve_mention(
            "person/aj", roster=self.roster, evidence_ref=EVIDENCE, now=NOW
        )
        self.assertEqual(record.resolution, "same")
        self.assertEqual(record.resolved_ref, "person/aj")
        self.assertEqual(record.reason, "exact_ref")

    def test_resolution_is_deterministic_so_a_retry_files_nothing_twice(self):
        # §10: "Retrying a successful or uncertain request creates no duplicate."
        first = ir.resolve_mention("AJ", roster=self.roster, evidence_ref=EVIDENCE, now=NOW)
        again = ir.resolve_mention("AJ", roster=self.roster, evidence_ref=EVIDENCE, now=NOW)
        self.assertEqual(first.to_dict(), again.to_dict())

    def test_no_containment_folding_and_no_fuzzy_matching(self):
        # The audit rejected both: a rule that can silently merge two people
        # must not exist here. "Jim" must never absorb "Jimmy".
        near = roster(person("Jimmy Carter"), person("Jim Beam"))
        record = ir.resolve_mention("Jim", roster=near, evidence_ref=EVIDENCE, now=NOW)
        self.assertEqual(record.resolution, "uncertain")
        self.assertEqual(record.reason, "no_candidate")
        self.assertEqual(record.candidates, ())


# --------------------------------------------------------------------------
# §10 — "a duplicate spelling does not create a second person" (alias path)
# --------------------------------------------------------------------------


class AliasTests(unittest.TestCase):
    def setUp(self):
        self.roster = roster(
            person("Della", aliases=["Aunt Della", "Dell"]),
            person("Bo"),
        )

    def test_a_curated_alias_resolves_to_the_one_person_it_names(self):
        record = ir.resolve_mention(
            "Aunt Della", roster=self.roster, evidence_ref=EVIDENCE, now=NOW
        )
        self.assertEqual(record.resolution, "same")
        self.assertEqual(record.resolved_ref, "person/della")
        self.assertEqual(record.reason, "roster_alias")

    def test_every_spelling_of_one_person_lands_on_one_ref(self):
        refs = {
            ir.resolve_mention(m, roster=self.roster, evidence_ref=EVIDENCE, now=NOW).resolved_ref
            for m in ("Della", "della", "Aunt  Della", "Aunt Della.", "Dell", "person/della")
        }
        self.assertEqual(refs, {"person/della"}, "a spelling must not mint a second person")

    def test_a_shared_alias_is_ambiguous_rather_than_a_silent_merge(self):
        # A strict alias-before-name ladder would silently pick the alias
        # holder. Two people answer to "Mom", so the honest answer is uncertain.
        shared = roster(person("Mom"), person("Desi", aliases=["Mom"]))
        record = ir.resolve_mention("Mom", roster=shared, evidence_ref=EVIDENCE, now=NOW)
        self.assertEqual(record.resolution, "uncertain")
        self.assertEqual(
            sorted(c["ref"] for c in record.candidates), ["person/desi", "person/mom"]
        )

    def test_an_owner_suppressed_page_is_still_a_resolution_candidate(self):
        # `owner_verdict: never` suppresses a wiki page, not alias folding.
        suppressed = roster(person("Della", owner_verdict="never"))
        record = ir.resolve_mention(
            "Della", roster=suppressed, evidence_ref=EVIDENCE, now=NOW
        )
        self.assertEqual(record.resolved_ref, "person/della")


# --------------------------------------------------------------------------
# §10 — "an ambiguous name is retained ... and becomes a Mirror identity item"
# --------------------------------------------------------------------------


class AmbiguityTests(unittest.TestCase):
    def setUp(self):
        self.roster = roster(
            # Two real people the vault knows by the same name.
            person("AJ", slug="aj-carter"),
            person("AJ", slug="aj-nelson"),
        )
        self.record = ir.resolve_mention(
            "AJ", roster=self.roster, evidence_ref=EVIDENCE, now=NOW
        )

    def test_two_candidates_produce_uncertain_and_never_a_guess(self):
        self.assertEqual(self.record.resolution, "uncertain")
        self.assertEqual(self.record.reason, "ambiguous_candidates")
        self.assertIsNone(self.record.resolved_ref)
        self.assertEqual(len(self.record.candidates), 2)

    def test_the_claim_is_retained_with_its_uncertainty_not_dropped(self):
        resolved = ir.apply_resolution(claim(subject_mention="AJ"), self.record, now=NOW)
        self.assertEqual(resolved["subject_mention"], "AJ")
        self.assertNotIn("subject_ref", resolved)
        self.assertEqual(resolved["subject_resolution"]["reason"], "ambiguous_candidates")
        self.assertEqual(len(resolved["subject_resolution"]["candidates"]), 2)

    def test_an_ambiguous_mention_mints_a_valid_identity_work_item(self):
        item = ir.identity_work_item(self.record, claim_refs=[EVIDENCE], now=NOW)
        self.assertIsNotNone(item)
        self.assertEqual(item["kind"], "identity_uncertain")
        self.assertEqual(item["state"], "open")
        self.assertEqual(item["requested_field"], ir.IDENTITY_REQUESTED_FIELD)
        self.assertEqual(item["allowed_surfaces"], list(ir.IDENTITY_WORK_SURFACES))
        self.assertEqual(item["evidence_refs"], [EVIDENCE])
        self.assertTrue(ir.is_unresolved_ref(item["subject_ref"]))

    def test_the_work_item_id_is_the_one_id_the_derive_function_mints(self):
        item = ir.identity_work_item(self.record, now=NOW)
        self.assertEqual(
            item["work_item_id"],
            tp.derive_work_item_id(
                kind="identity_uncertain",
                subject_ref=ir.unresolved_subject_ref("AJ"),
                requested_field=ir.IDENTITY_REQUESTED_FIELD,
            ),
        )
        self.assertTrue(tc.is_safe_id(item["work_item_id"]))
        self.assertNotIn("/", item["work_item_id"])

    def test_every_sighting_of_the_same_ambiguous_name_is_one_row(self):
        # §5.4: answer once, update everywhere.
        other = ir.resolve_mention(
            "aj", roster=self.roster, evidence_ref="claim:" + "b" * 24, now=NOW
        )
        self.assertEqual(
            ir.identity_work_item(self.record, now=NOW)["work_item_id"],
            ir.identity_work_item(other, now=NOW)["work_item_id"],
        )

    def test_a_resolved_record_asks_nothing(self):
        clean = ir.resolve_mention(
            "AJ", roster=roster(person("AJ")), evidence_ref=EVIDENCE, now=NOW
        )
        self.assertIsNone(ir.identity_work_item(clean, now=NOW))

    def test_a_name_nobody_resembles_is_a_new_person_not_a_mirror_row(self):
        unknown = ir.resolve_mention(
            "Steve", roster=self.roster, evidence_ref=EVIDENCE, now=NOW
        )
        self.assertEqual(unknown.resolution, "uncertain")
        self.assertEqual(unknown.reason, "no_candidate")
        self.assertIsNone(ir.identity_work_item(unknown, now=NOW))
        # ... and the claim still keeps the mention and the record.
        kept = ir.apply_resolution(claim(subject_mention="Steve"), unknown, now=NOW)
        self.assertEqual(kept["subject_mention"], "Steve")
        self.assertEqual(kept["subject_resolution"]["reason"], "no_candidate")


# --------------------------------------------------------------------------
# The record contract — what a resolution may and may not say
# --------------------------------------------------------------------------


class RecordContractTests(unittest.TestCase):
    def base(self, **overrides) -> dict:
        payload = {
            "mention": "AJ",
            "candidates": [{"ref": "person/aj", "name": "AJ", "basis": "name"}],
            "resolution": "same",
            "resolved_ref": "person/aj",
            "reason": "unique_name",
            "evidence_ref": EVIDENCE,
            "created_at": NOW,
        }
        payload.update(overrides)
        return payload

    def assertRefuses(self, code, **overrides):
        with self.assertRaises(ir.IdentityResolutionError) as caught:
            ir.validate_resolution_record(self.base(**overrides))
        self.assertEqual(caught.exception.code, code)

    def test_a_record_without_the_raw_mention_is_refused(self):
        self.assertRefuses("resolution_needs_mention", mention="   ")

    def test_a_record_without_evidence_is_an_assertion_not_a_link(self):
        self.assertRefuses("resolution_needs_evidence", evidence_ref=None)

    def test_same_must_name_a_ref_and_it_must_have_been_a_candidate(self):
        self.assertRefuses("resolved_ref_required", resolved_ref=None)
        self.assertRefuses("resolved_ref_not_a_candidate", resolved_ref="person/della")

    def test_uncertain_may_not_smuggle_a_resolved_ref(self):
        self.assertRefuses(
            "resolved_ref_forbidden", resolution="uncertain", reason="ambiguous_candidates"
        )

    def test_ambiguity_is_the_candidate_set(self):
        self.assertRefuses(
            "ambiguous_needs_candidates",
            resolution="uncertain",
            resolved_ref=None,
            reason="ambiguous_candidates",
        )

    def test_no_candidate_may_not_contradict_itself(self):
        self.assertRefuses(
            "no_candidate_has_candidates",
            resolution="uncertain",
            resolved_ref=None,
            reason="no_candidate",
        )

    def test_reversibility_is_the_contract_not_a_per_record_choice(self):
        self.assertRefuses("resolution_not_reversible", reversible=False)

    def test_unknown_vocabularies_fail_loud(self):
        self.assertRefuses("unknown_resolution", resolution="maybe")
        self.assertRefuses("unknown_resolution_reason", reason="vibes")
        self.assertRefuses(
            "unknown_candidate_basis",
            candidates=[{"ref": "person/aj", "basis": "hunch"}],
        )

    def test_the_model_rung_writes_through_this_same_contract(self):
        record = ir.resolution_record(
            self.base(reason=ir.MODEL_REASON, confidence=0.93), now=NOW
        )
        self.assertEqual(record.reason, "model")
        self.assertEqual(record.confidence, 0.93)
        self.assertEqual(record.resolved_ref, "person/aj")

    def test_different_is_expressible_and_names_no_ref(self):
        record = ir.resolution_record(
            self.base(resolution="different", resolved_ref=None, reason=ir.OWNER_REASON),
            now=NOW,
        )
        self.assertEqual(record.resolution, "different")
        self.assertIsNone(record.resolved_ref)

    def test_the_deterministic_resolver_never_claims_different(self):
        # It has no way to learn that two names denote different people.
        for mention in ("AJ", "Steve", "person/aj"):
            record = ir.resolve_mention(
                mention, roster=roster(person("AJ"), person("AJ", slug="aj-two")),
                evidence_ref=EVIDENCE, now=NOW,
            )
            self.assertIn(record.resolution, ("same", "uncertain"))

    def test_the_tolerant_reader_returns_none_rather_than_raising(self):
        self.assertIsNone(ir.record_from_dict({"mention": "AJ"}))
        self.assertIsNone(ir.record_from_dict("not a record"))


# --------------------------------------------------------------------------
# Reversibility — resolution is data ABOUT a claim, never mutation OF it
# --------------------------------------------------------------------------


class ReversibilityTests(unittest.TestCase):
    def setUp(self):
        self.roster = roster(person("Della", aliases=["Aunt Della"]))
        self.claim = tc.validate_temporal_claim(claim(subject_mention="Aunt Della"), now=NOW)
        self.record = ir.resolve_mention(
            "Aunt Della", roster=self.roster, evidence_ref=self.claim["claim_id"], now=NOW
        )

    def test_claim_identity_derives_from_the_raw_mention_not_the_resolved_ref(self):
        # The property the whole design rests on, asserted against the
        # substrate itself rather than assumed.
        self.assertIn("subject_key", tc.CLAIM_IDENTITY_KEYS)
        self.assertNotIn("subject_ref", tc.CLAIM_IDENTITY_KEYS)
        self.assertEqual(
            self.claim["claim_id"],
            tc.derive_claim_id(
                claim_type="date",
                subject_mention="Aunt Della",
                event_kind="birth",
                temporal_value="1984",
                source_ref=dict(REF),
                extractor_version=EXT,
            ),
        )

    def test_applying_a_resolution_never_re_mints_the_claim(self):
        resolved = ir.apply_resolution(self.claim, self.record, now=NOW)
        self.assertEqual(resolved["claim_id"], self.claim["claim_id"])
        self.assertEqual(resolved["subject_ref"], "person/della")
        self.assertEqual(resolved["subject_mention"], "Aunt Della")

    def test_applying_a_resolution_does_not_mutate_the_input_claim(self):
        ir.apply_resolution(self.claim, self.record, now=NOW)
        self.assertNotIn("subject_ref", self.claim)
        self.assertNotIn("subject_resolution", self.claim)

    def test_unresolve_reverses_the_link_without_destroying_it(self):
        reversed_record = ir.unresolve(self.record, now=NOW)
        self.assertEqual(reversed_record.resolution, "uncertain")
        self.assertEqual(reversed_record.reason, ir.UNRESOLVED_REASON)
        self.assertIsNone(reversed_record.resolved_ref)
        # Nothing thrown away: the ref that won is still a candidate, and the
        # undone decision is on the record.
        self.assertIn("person/della", [c["ref"] for c in reversed_record.candidates])
        self.assertEqual(reversed_record.reverses["resolved_ref"], "person/della")
        self.assertEqual(reversed_record.reverses["reason"], "roster_alias")

    def test_unresolving_puts_the_claim_back_without_moving_its_id(self):
        resolved = ir.apply_resolution(self.claim, self.record, now=NOW)
        undone = ir.apply_resolution(resolved, ir.unresolve(self.record, now=NOW), now=NOW)
        self.assertEqual(undone["claim_id"], self.claim["claim_id"])
        self.assertNotIn("subject_ref", undone)
        self.assertEqual(undone["subject_mention"], "Aunt Della")

    def test_unresolving_an_uncertain_record_is_a_no_op(self):
        uncertain = ir.resolve_mention(
            "Nobody", roster=self.roster, evidence_ref=EVIDENCE, now=NOW
        )
        self.assertEqual(ir.unresolve(uncertain, now=NOW).to_dict(), uncertain.to_dict())

    def test_the_annotation_the_claim_stores_round_trips_through_the_substrate(self):
        annotation = ir.resolution_annotation(self.record)
        stored = tc.validate_temporal_claim(
            dict(self.claim, subject_resolution=annotation), now=NOW
        )["subject_resolution"]
        self.assertEqual(stored["candidates"], ["person/della"])
        self.assertEqual(stored["reason"], "roster_alias")


# --------------------------------------------------------------------------
# §10 — "Katie first met, dating started, and marriage are distinct events"
# --------------------------------------------------------------------------


class KatieTests(unittest.TestCase):
    """Two facts, one edge. The scenario written from §10 verbatim."""

    ME = "person/dave"
    HER = "person/katie"

    def episode(self, kind):
        return ir.derive_episode_ref(
            event_kind=kind, subject_ref=self.HER, counterpart_ref=self.ME
        )

    def test_first_met_dating_started_and_marriage_are_three_distinct_events(self):
        refs = [self.episode(k) for k in ("first_met", "dating_started", "married")]
        self.assertEqual(len(set(refs)), 3, "three transitions, three identities")
        for ref in refs:
            self.assertTrue(tc.is_safe_id(ref))

    def test_dating_2005_and_married_2007_are_two_facts_with_independent_dates(self):
        dating = tc.validate_temporal_claim(
            claim(
                subject_mention="Katie",
                event_kind="dating_started",
                temporal_value="2005",
                evidence=[{"quote": "we started dating in 2005", "turn_ref": "turn:1"}],
            ),
            now=NOW,
        )
        married = tc.validate_temporal_claim(
            claim(
                subject_mention="Katie",
                event_kind="married",
                temporal_value="2007",
                evidence=[{"quote": "we married in 2007", "turn_ref": "turn:2"}],
            ),
            now=NOW,
        )
        self.assertNotEqual(dating["claim_id"], married["claim_id"])
        self.assertNotEqual(
            self.episode("dating_started"), self.episode("married")
        )

    def test_both_facts_sit_on_one_relationship_edge(self):
        edge = ir.relationship_edge_ref(self.ME, self.HER)
        self.assertEqual(edge, ir.relationship_edge_ref(self.HER, self.ME))
        self.assertTrue(tc.is_safe_id(edge))
        self.assertNotIn("/", edge)

    def test_the_edge_is_order_normalized_in_the_episode_ref_too(self):
        self.assertEqual(
            ir.derive_episode_ref(
                event_kind="married", subject_ref=self.HER, counterpart_ref=self.ME
            ),
            ir.derive_episode_ref(
                event_kind="married", subject_ref=self.ME, counterpart_ref=self.HER
            ),
        )

    def test_the_edge_carries_no_event_kind_and_no_date(self):
        # It is the grouping key that proves "one relationship", nothing more.
        self.assertEqual(
            ir.relationship_edge_ref(self.ME, self.HER),
            ir.relationship_edge_ref("person/dave", "person/katie"),
        )

    def test_a_relationship_transition_without_a_counterpart_is_refused(self):
        with self.assertRaises(ir.IdentityResolutionError) as caught:
            ir.derive_episode_ref(event_kind="married", subject_ref=self.HER)
        self.assertEqual(caught.exception.code, "episode_needs_counterpart")

    def test_an_edge_needs_two_distinct_people(self):
        with self.assertRaises(ir.IdentityResolutionError) as caught:
            ir.relationship_edge_ref(self.HER, self.HER)
        self.assertEqual(caught.exception.code, "edge_needs_two_subjects")

    def test_a_different_couple_is_a_different_edge(self):
        self.assertNotEqual(
            ir.relationship_edge_ref(self.ME, self.HER),
            ir.relationship_edge_ref(self.ME, "person/della"),
        )


# --------------------------------------------------------------------------
# §10 — "a repeated school/job period is not collapsed into a single episode"
# --------------------------------------------------------------------------


class RepeatedEpisodeTests(unittest.TestCase):
    ME = "person/dave"

    def stint(self, start):
        return ir.derive_episode_ref(
            event_kind="job",
            subject_ref=self.ME,
            discriminator=ir.episode_discriminator(start),
        )

    def test_a_second_boeing_stint_is_a_second_episode(self):
        first = self.stint("1998")
        second = self.stint("2011")
        self.assertNotEqual(first, second, "a second stint must not merge into the first")

    def test_the_same_stint_derives_the_same_episode_every_time(self):
        self.assertEqual(self.stint("1998"), self.stint("1998"))

    def test_a_repeatable_episode_without_a_discriminator_is_refused_loudly(self):
        with self.assertRaises(ir.IdentityResolutionError) as caught:
            ir.derive_episode_ref(event_kind="job", subject_ref=self.ME)
        self.assertEqual(caught.exception.code, "episode_needs_discriminator")

    def test_the_discriminator_comes_from_the_episodes_own_start_claim(self):
        self.assertEqual(ir.episode_discriminator("1998-06"), "1998-06")
        self.assertEqual(
            ir.episode_discriminator({"best": "1998-06", "start": "1998-01"}), "1998-06"
        )
        self.assertIsNone(ir.episode_discriminator(None))
        self.assertIsNone(ir.episode_discriminator({}))

    def test_an_explicit_ordinal_works_when_no_start_is_known(self):
        self.assertNotEqual(
            ir.derive_episode_ref(event_kind="school", subject_ref=self.ME, discriminator="1"),
            ir.derive_episode_ref(event_kind="school", subject_ref=self.ME, discriminator="2"),
        )

    def test_two_people_at_the_same_school_are_different_episodes(self):
        self.assertNotEqual(
            ir.derive_episode_ref(event_kind="school", subject_ref=self.ME, discriminator="1994"),
            ir.derive_episode_ref(
                event_kind="school", subject_ref="person/katie", discriminator="1994"
            ),
        )

    def test_a_once_only_event_needs_no_discriminator(self):
        ref = ir.derive_episode_ref(event_kind="birth", subject_ref=self.ME)
        self.assertTrue(tc.is_safe_id(ref))

    def test_an_episode_ref_is_the_node_id_the_projection_publishes(self):
        # One definition: the episode ref IS temporal_projection's node id.
        self.assertEqual(
            ir.derive_episode_ref(event_kind="job", subject_ref=self.ME, discriminator="1998"),
            tp.derive_node_id(
                node_kind="episode",
                event_kind="job",
                subject_refs=[self.ME],
                discriminator="1998",
            ),
        )

    def test_an_event_kind_is_required_because_a_date_dates_an_event(self):
        with self.assertRaises(ir.IdentityResolutionError) as caught:
            ir.derive_episode_ref(event_kind="", subject_ref=self.ME)
        self.assertEqual(caught.exception.code, "episode_needs_event_kind")

    def test_an_unresolved_subject_can_still_hold_an_episode(self):
        # §2.5: uncertain identity must never cost the claim its event.
        ref = ir.derive_episode_ref(
            event_kind="job", subject_mention="AJ", discriminator="2011"
        )
        self.assertTrue(tc.is_safe_id(ref))


# --------------------------------------------------------------------------
# The roster is read, never written
# --------------------------------------------------------------------------


class RosterReadTests(unittest.TestCase):
    def test_the_index_accepts_a_snapshot_a_list_or_itself(self):
        snapshot = roster(person("Della"))
        built = ir.roster_index(snapshot)
        self.assertEqual(built.size(), 1)
        self.assertEqual(ir.roster_index(snapshot["entities"]).refs, built.refs)
        self.assertIs(ir.roster_index(built), built)

    def test_an_empty_roster_resolves_nothing_and_still_returns_a_record(self):
        record = ir.resolve_mention("Della", roster=(), evidence_ref=EVIDENCE, now=NOW)
        self.assertEqual(record.resolution, "uncertain")
        self.assertEqual(record.reason, "no_candidate")

    def test_the_module_never_imports_the_roster_module_or_any_io(self):
        # Purity is the contract: this module must be safe to vendor into the
        # worker and the sandboxed prompt seam.
        source = (ROOT / "system" / "identity_resolution.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        imported: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(a.name.split(".")[0] for a in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module.split(".")[0])
        for forbidden in ("entity_roster", "lifehug_core", "ai_provider", "jobs"):
            self.assertNotIn(forbidden, imported)

    def test_a_ref_is_a_type_and_slug_never_a_display_name(self):
        # The accepted amendment: a display label is never a primary key.
        self.assertEqual(ir.entity_ref("person", "Betty Jo"), "person/betty-jo")
        self.assertEqual(
            ir.roster_index(roster(person("Betty Jo"))).name_of("person/betty-jo"),
            "Betty Jo",
        )


if __name__ == "__main__":
    unittest.main()
