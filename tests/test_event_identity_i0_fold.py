"""I0-C3 — the fold-semantics contract, proved against its fixtures.

Contract: `docs/contracts/event-identity-i0-fold.md`; design
lifehug-platform `docs/design/event-identity.md` (v4) §3.5, §5.1–§5.4, §5.6.

Nothing here touches `temporal_timeline`. I0's whole job is to make the
decisions the fold WILL make executable before they are wired, so that I1
lands an already-proven contract instead of deciding grouping, ids,
entailment and containment inside a 4 000-line module.

Every negative test is written the way the program requires: the guard is run
against the state where it SHOULD fire, seen firing, and run again against
the neighbouring state where it must NOT fire. A guard proven only in the
direction that passes is not a guard.

Synthetic data only; NEVER references ~/Workspace/dave.
"""

from __future__ import annotations

import ast
import copy
import itertools
import json
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "system"))

import chronology as chrono  # noqa: E402
import episode_fold_contract as efc  # noqa: E402
import episode_routing_contract as erc  # noqa: E402
import temporal_claims as tc  # noqa: E402
import temporal_projection as tp  # noqa: E402

FIXTURE = json.loads(
    (ROOT / "tests" / "goldens" / "event_identity_i0_fold.json").read_text("utf-8")
)
EPISODES = FIXTURE["episodes"]
CASES = {case["name"]: case for case in FIXTURE["cases"]}

NODE_OF = "@node_of:"


def node_of(episode_id: str) -> str:
    """The published node id of one fixture episode, through the contract."""
    row = EPISODES[episode_id]
    return efc.episode_node_id(
        canonical_event_kind=row["canonical_event_kind"],
        subject_keys=row["subject_keys"],
        episode_id=episode_id,
    )


def resolve(value: object) -> object:
    """`@node_of:<episode_id>` → the node id. No digest is hand-copied."""
    if isinstance(value, str) and value.startswith(NODE_OF):
        return node_of(value[len(NODE_OF):])
    if isinstance(value, list):
        return [resolve(item) for item in value]
    if isinstance(value, dict):
        return {key: resolve(item) for key, item in value.items()}
    return value


def case_inputs(name: str) -> tuple:
    case = copy.deepcopy(CASES[name])
    claims = [resolve(claim) for claim in case["claims"]]
    manifest = {"tellings": case["manifest"]}
    bindings = case["bindings"]
    return claims, manifest, bindings, case


class GroupingContract(unittest.TestCase):
    """§5.1 — what groups with what, one fixture per clause of the rule."""

    def assert_case(self, name: str) -> tuple:
        claims, manifest, bindings, case = case_inputs(name)
        index = efc.manifest_claim_index(manifest)
        active = efc.active_binding_index(bindings)
        for claim in claims:
            expected = resolve(case["expect"][claim["claim_id"]])
            decision = efc.grouping_key(claim, index, active)
            self.assertEqual(decision.kind, expected["kind"], f"{name}/kind")
            self.assertEqual(decision.reason, expected["reason"], f"{name}/reason")
            self.assertEqual(decision.key, expected["key"], f"{name}/key")
            if "aliased_from" in expected:
                self.assertEqual(list(decision.aliased_from), expected["aliased_from"])
        found = sorted({row["code"] for row in
                        efc.fold_diagnostics(claims, manifest, bindings)})
        self.assertEqual(found, sorted(case["expect_diagnostics"]), f"{name}/diagnostics")
        return claims, manifest, bindings, case

    def test_bound_telling_groups_under_the_episode_node(self):
        claims, manifest, bindings, _ = self.assert_case(
            "bound_telling_groups_under_the_episode_node")
        grouping = efc.fold_grouping(claims, manifest, bindings)
        self.assertEqual(len(grouping), 1, "two tellings, one episode, one group")

    def test_unbound_telling_keeps_the_existing_key(self):
        self.assert_case("unbound_telling_keeps_the_existing_key")

    def test_claim_with_no_manifest_row_keeps_the_existing_key(self):
        self.assert_case("claim_with_no_manifest_row_keeps_the_existing_key")

    def test_a_proposed_binding_groups_nothing(self):
        self.assert_case("a_proposed_binding_groups_nothing")

    def test_a_telling_about_the_era_itself_is_refused_as_a_binding_target(self):
        self.assert_case("a_telling_about_the_era_itself_is_refused_as_a_binding_target")

    def test_a_telling_about_an_event_within_an_era_keeps_full_eligibility(self):
        """The F-pin, both directions: the era case above refuses, this one binds.

        Same era, same binding origin family, one difference — whether the
        claim's own `event_ref` names the era. That difference is the whole
        contract, so the two cases are asserted beside each other.
        """
        self.assert_case("a_telling_about_an_event_within_an_era_keeps_full_eligibility")
        refused, _, _, _ = case_inputs(
            "a_telling_about_the_era_itself_is_refused_as_a_binding_target")
        allowed, _, _, _ = case_inputs(
            "a_telling_about_an_event_within_an_era_keeps_full_eligibility")
        self.assertEqual(efc.telling_era_role(refused), "about_the_era")
        self.assertEqual(efc.telling_era_role(allowed), "within_an_era")

    def test_a_recorder_episode_ref_and_a_binding_compose(self):
        self.assert_case("a_recorder_episode_ref_and_a_binding_compose")

    def test_the_binding_wins_over_a_different_recorder_ref_and_aliases_it(self):
        claims, manifest, bindings, _ = self.assert_case(
            "the_binding_wins_over_a_different_recorder_ref_and_aliases_it")
        index = efc.manifest_claim_index(manifest)
        active = efc.active_binding_index(bindings)
        decisions = [efc.grouping_key(claim, index, active) for claim in claims]
        table = efc.node_aliases(decisions)
        self.assertEqual(
            table,
            {"node:00000000000000000000ab01": node_of("episode:0000000000000000000000e1")},
        )

    def test_a_dormant_binding_is_reported_and_ignored(self):
        claims, manifest, bindings, _ = self.assert_case(
            "a_dormant_binding_is_reported_and_ignored")
        # …and it is not an error: the fold completes and groups the live claim.
        self.assertEqual(len(efc.fold_grouping(claims, manifest, bindings)), 1)

    def test_a_mixed_telling_is_a_refusal_never_a_partial_bind(self):
        row = copy.deepcopy(FIXTURE["mixed_telling"])
        manifest = {"tellings": row["manifest"]}
        with self.assertRaises(tc.TemporalContractError) as caught:
            efc.fold_diagnostics(row["claims"], manifest, row["bindings"])
        self.assertEqual(caught.exception.code, efc.REFUSAL_TELLING_MIXES_IDENTITIES)
        # Proven to fire, and proven NOT to: drop the era-bound claim and the
        # very same telling binds cleanly.
        clean = [claim for claim in row["claims"] if not claim["event_ref"]]
        manifest["tellings"][0]["claim_ids"] = [claim["claim_id"] for claim in clean]
        self.assertEqual(efc.fold_diagnostics(clean, manifest, row["bindings"]), ())

    def test_one_claim_in_two_active_tellings_is_refused(self):
        manifest = {"tellings": [
            {"telling_ref": "telling:a", "claim_ids": ["claim:x"]},
            {"telling_ref": "telling:b", "claim_ids": ["claim:x"]},
        ]}
        with self.assertRaises(tc.TemporalContractError) as caught:
            efc.manifest_claim_index(manifest)
        self.assertEqual(caught.exception.code, efc.REFUSAL_TELLING_MIXES_IDENTITIES)
        manifest["tellings"][1]["status"] = "retired"
        self.assertEqual(efc.manifest_claim_index(manifest), {"claim:x": "telling:a"})

    def test_every_grouping_reason_is_reachable_and_the_set_is_closed(self):
        seen = set()
        for name in CASES:
            claims, manifest, bindings, _ = case_inputs(name)
            index = efc.manifest_claim_index(manifest)
            active = efc.active_binding_index(bindings)
            for claim in claims:
                seen.add(efc.grouping_key(claim, index, active).reason)
        self.assertTrue(seen <= set(efc.GROUPING_REASONS), sorted(seen))
        self.assertEqual(sorted(seen), sorted(efc.GROUPING_REASONS),
                         "a reason no fixture reaches is a rule nobody proved")


class EpisodeIdentity(unittest.TestCase):
    """§3.5 — two identifiers, one durable published mapping."""

    def test_episode_node_id_is_the_frozen_minter_unchanged(self):
        direct = tp.derive_node_id(
            node_kind="episode", event_kind="job", subject_refs=["org/larkspur"],
            discriminator="episode:0000000000000000000000e1",
        )
        self.assertEqual(node_of("episode:0000000000000000000000e1"), direct)

    def test_the_digest_input_is_exactly_node_identity_keys(self):
        identity = efc.episode_node_identity(
            canonical_event_kind="job", subject_keys=["org/larkspur"],
            episode_id="episode:0000000000000000000000e1",
        )
        self.assertEqual(tuple(identity), tp.NODE_IDENTITY_KEYS)
        self.assertEqual(identity["node_kind"], "episode")
        self.assertIn("episode", tp.NODE_KINDS)
        self.assertEqual(identity["discriminator"], "episode:0000000000000000000000e1")

    def test_two_episodes_of_one_kind_and_subject_do_not_collide(self):
        first = node_of("episode:0000000000000000000000e1")
        second = node_of("episode:0000000000000000000000e2")
        self.assertNotEqual(first, second,
                            "the episode id IS the discriminator; that is what it is for")

    def test_a_node_id_without_an_episode_id_is_refused(self):
        with self.assertRaises(tc.TemporalContractError) as caught:
            efc.episode_node_id(canonical_event_kind="job",
                                subject_keys=["org/larkspur"], episode_id="")
        self.assertEqual(caught.exception.code, "episode_node_needs_episode_id")
        self.assertTrue(efc.episode_node_id(canonical_event_kind="job",
                                            subject_keys=["org/larkspur"],
                                            episode_id="episode:x"))

    def test_identity_mapping_publishes_both_directions(self):
        rows = [dict(row, episode_id=key) for key, row in EPISODES.items()]
        mapping = efc.identity_mapping(rows)
        self.assertEqual(mapping["identity_rule_version"], efc.IDENTITY_RULE_VERSION)
        for episode_id in EPISODES:
            node_id = mapping["episode_node_ids"][episode_id]
            self.assertEqual(node_id, node_of(episode_id))
            self.assertEqual(mapping["node_episode_ids"][node_id], episode_id)

    def test_episode_aliases_come_from_the_operations_own_receipt(self):
        operations = [{
            "op": "merge", "episode_id": "episode:0000000000000000000000e1",
            "absorbed_episode_id": "episode:0000000000000000000000e2",
            "aliases_created": ["episode:0000000000000000000000e2"], "status": "active",
        }]
        self.assertEqual(efc.episode_aliases(operations), {
            "episode:0000000000000000000000e2": "episode:0000000000000000000000e1"})
        operations[0]["status"] = "superseded"
        self.assertEqual(efc.episode_aliases(operations), {},
                         "a superseded envelope publishes no alias")


class ActiveBindingsAndRefusals(unittest.TestCase):
    """§5.4 — loud where it must be, quiet where it must be."""

    def base(self) -> list:
        return [
            {"identity_id": "eid:a", "telling_ref": "telling:1",
             "episode_id": "episode:0000000000000000000000e1", "relation": "same",
             "origin": "deterministic", "canonical_event_kind": "job",
             "subject_keys": ["org/larkspur"]},
        ]

    def test_supersession_is_followed_not_recency(self):
        rows = self.base() + [{
            "identity_id": "eid:b", "telling_ref": "telling:1",
            "episode_id": "episode:0000000000000000000000e2", "relation": "same",
            "origin": "confirmed", "supersedes": "eid:a",
            "canonical_event_kind": "job", "subject_keys": ["org/larkspur"]}]
        active = efc.active_binding_index(rows)
        self.assertEqual([row["identity_id"] for row in active["telling:1"]], ["eid:b"])

    def test_two_active_same_bindings_raise_identity_conflict(self):
        rows = self.base() + [{
            "identity_id": "eid:b", "telling_ref": "telling:1",
            "episode_id": "episode:0000000000000000000000e2", "relation": "same",
            "origin": "confirmed", "canonical_event_kind": "job",
            "subject_keys": ["org/larkspur"]}]
        with self.assertRaises(tc.TemporalContractError) as caught:
            efc.active_binding_index(rows)
        self.assertEqual(caught.exception.code, efc.REFUSAL_IDENTITY_CONFLICT)
        # Proven not to fire the moment one supersedes the other.
        rows[1]["supersedes"] = "eid:a"
        self.assertIn("telling:1", efc.active_binding_index(rows))

    def test_one_pair_decided_twice_raises(self):
        rows = self.base() + [{
            "identity_id": "eid:b", "telling_ref": "telling:1",
            "episode_id": "episode:0000000000000000000000e1", "relation": "part_of",
            "origin": "confirmed", "canonical_event_kind": "job",
            "subject_keys": ["org/larkspur"]}]
        with self.assertRaises(tc.TemporalContractError) as caught:
            efc.active_binding_index(rows)
        self.assertEqual(caught.exception.code, efc.REFUSAL_IDENTITY_CONFLICT)

    def test_same_plus_negatives_on_other_episodes_is_legal(self):
        """§5.4's literal wording would refuse the five-answer model; the
        contract pins the narrower reading and this is the case that proves
        the narrower reading is the necessary one."""
        rows = self.base() + [
            {"identity_id": "eid:n1", "telling_ref": "telling:1",
             "episode_id": "episode:0000000000000000000000e2", "relation": "not_same",
             "origin": "confirmed"},
            {"identity_id": "eid:n2", "telling_ref": "telling:1",
             "episode_id": "episode:0000000000000000000000e3", "relation": "related",
             "origin": "confirmed"},
        ]
        active = efc.active_binding_index(rows)
        self.assertEqual(len(active["telling:1"]), 3)
        self.assertEqual(efc.grouping_binding("telling:1", active)["identity_id"], "eid:a")

    def test_the_finding_vocabulary_is_closed(self):
        codes = set()
        for name in CASES:
            claims, manifest, bindings, _ = case_inputs(name)
            codes |= {row["code"] for row in
                      efc.fold_diagnostics(claims, manifest, bindings)}
        self.assertTrue(codes <= set(efc.FOLD_FINDINGS), sorted(codes))
        self.assertEqual(len(set(efc.FOLD_FINDINGS)), len(efc.FOLD_FINDINGS))


class Entailment(unittest.TestCase):
    """§2.2 — computed at fold time, never stored expanded."""

    def rows(self) -> list:
        return [
            {"identity_id": "eid:a", "telling_ref": "telling:A", "relation": "same",
             "origin": "deterministic", "episode_id": "episode:E"},
            {"identity_id": "eid:b", "telling_ref": "telling:B", "relation": "not_same",
             "origin": "confirmed", "episode_id": "episode:E"},
        ]

    def test_same_and_not_same_entail_the_pair(self):
        self.assertEqual(efc.entailed_not_same(self.rows()),
                         (("telling:A", "telling:B"),))
        self.assertTrue(efc.is_not_same("telling:B", "telling:A", self.rows()))

    def test_the_entailment_is_symmetric_and_never_self_referential(self):
        pairs = efc.entailed_not_same(self.rows())
        self.assertEqual(pairs, tuple(tuple(sorted(pair)) for pair in pairs))
        self.assertFalse(efc.is_not_same("telling:A", "telling:A", self.rows()))

    def test_retracting_a_premise_removes_the_entailed_pair(self):
        """Why it is never stored: the closure has to disappear with its
        premise, and the only way to guarantee that is to not have it."""
        rows = self.rows()
        rows[1]["status"] = "retracted"
        self.assertEqual(efc.entailed_not_same(rows), ())

    def test_computing_the_closure_mutates_nothing(self):
        rows = self.rows()
        before = json.dumps(rows, sort_keys=True)
        efc.entailed_not_same(rows)
        efc.is_not_same("telling:A", "telling:B", rows)
        self.assertEqual(json.dumps(rows, sort_keys=True), before)

    def test_a_proposal_entails_nothing(self):
        rows = self.rows()
        rows[0]["origin"] = "proposed"
        self.assertEqual(efc.entailed_not_same(rows), ())


class Containment(unittest.TestCase):
    """§5.3 — the possible outer range, every promise structural."""

    def span(self):
        """The episode's own span — WITH an anchor, deliberately.

        A containment that inherited its episode's anchors would let
        cross-dating treat "sometime during Larkspur" as something the person
        said, which is the one thing §5.3 forbids. An anchorless fixture could
        never catch that, so this one is not anchorless.
        """
        record = chrono.parse_edtf("2022-05/2026", basis="stated")
        return chrono.DateRecord(
            best=record.best, earliest=record.earliest, latest=record.latest,
            granularity=record.granularity, confidence=record.confidence,
            basis=record.basis, anchors=("landmark:the-move",),
            provenance=({"basis": "stated", "claim": "you started in May 2022"},),
        )

    def test_a_valueless_member_gets_the_episodes_own_span(self):
        record = efc.possible_outer_range(None, self.span(), episode_id="episode:E",
                                          episode_label="Larkspur")
        self.assertEqual(record.best, self.span().best)
        self.assertEqual(record.earliest, self.span().earliest)
        self.assertEqual(record.latest, self.span().latest)

    def test_it_never_narrows(self):
        record = efc.possible_outer_range(None, self.span(), episode_id="episode:E")
        self.assertLessEqual(str(record.earliest or ""), str(self.span().earliest or ""))
        self.assertGreaterEqual(str(record.latest or ""), str(self.span().latest or ""))

    def test_it_never_overrides_a_value(self):
        stated = chrono.parse_edtf("2023-07-04", basis="stated")
        self.assertIsNone(efc.possible_outer_range(stated, self.span(),
                                                   episode_id="episode:E"))
        self.assertIsNotNone(efc.possible_outer_range(None, self.span(),
                                                      episode_id="episode:E"))

    def test_it_is_never_an_anchor(self):
        self.assertEqual(self.span().anchors, ("landmark:the-move",),
                         "the fixture must carry one, or this proves nothing")
        record = efc.possible_outer_range(None, self.span(), episode_id="episode:E")
        self.assertEqual(record.anchors, ())

    def test_it_never_carries_the_episodes_provenance_across(self):
        """The episode's sources dated the EPISODE. Carrying them onto the
        member would attribute to the person a sentence they never said about
        this thing — the defect class the whole substrate exists to prevent."""
        record = efc.possible_outer_range(None, self.span(), episode_id="episode:E")
        self.assertEqual(len(record.provenance), 1)
        self.assertNotIn("you started in May 2022",
                         json.dumps(list(record.provenance)))

    def test_it_renders_as_inferred_and_mints_no_new_basis(self):
        record = efc.possible_outer_range(None, self.span(), episode_id="episode:E")
        self.assertEqual(record.basis, efc.CONTAINMENT_DATE_BASIS)
        self.assertIn(efc.CONTAINMENT_DATE_BASIS, chrono.BASES)
        self.assertEqual(tc.CLAIM_BASIS_BY_DATE_BASIS[record.basis], "inferred")
        self.assertEqual(record.confidence, "inferred")

    def test_the_provenance_names_the_episode_and_not_the_person(self):
        record = efc.possible_outer_range(None, self.span(), episode_id="episode:E",
                                          episode_label="Larkspur")
        clause = record.provenance[0]
        self.assertEqual(clause["basis"], chrono.INFERRED_PROVENANCE_BASIS)
        self.assertEqual(clause["rule"], efc.CONTAINMENT_RULE_ID)
        self.assertIn("Larkspur", clause["claim"])
        self.assertNotIn("you said", clause["claim"])

    def test_the_precision_question_survives(self):
        probe = efc.containment_probe("Larkspur")
        self.assertIn("Larkspur", probe)
        self.assertTrue(probe.endswith("?"))

    def test_an_undated_episode_infers_nothing(self):
        self.assertIsNone(efc.possible_outer_range(None, None, episode_id="episode:E"))


class Determinism(unittest.TestCase):
    """§5.6 — the two properties, restated honestly (audit F4, then G3)."""

    def test_fixed_receipts_fold_identically_under_permuted_orders(self):
        claims, manifest, bindings, _ = case_inputs(
            "bound_telling_groups_under_the_episode_node")
        expected = efc.grouping_fingerprint(efc.fold_grouping(claims, manifest, bindings))
        seen = set()
        for claim_order in itertools.permutations(claims):
            for binding_order in itertools.permutations(bindings):
                for row_order in itertools.permutations(manifest["tellings"]):
                    grouping = efc.fold_grouping(
                        list(claim_order), {"tellings": list(row_order)},
                        list(binding_order),
                    )
                    seen.add(efc.grouping_fingerprint(grouping))
        self.assertEqual(seen, {expected}, "one fingerprint, every order")

    def test_arrival_order_divergence_is_surfaced_not_resolved(self):
        """Audit G3's own case, executed.

        Order one: E1 is the sole candidate and the telling binds to it.
        Order two: E2 already exists, two candidates survive, R1 declines.
        The partitions differ. The contract does not pretend otherwise — it
        promises the divergence is NAMED, and this is where that is proved.
        """
        row = FIXTURE["arrival_order_divergence"]
        verdict = erc.reaudit(
            trigger="new_telling",
            telling_ref=row["telling_ref"],
            bound_episode_id=row["bound_episode_id"],
            candidate_episode_id=row["late_candidate_episode_id"],
        )
        self.assertEqual(verdict["action"], erc.REAUDIT_MINT)
        self.assertEqual(verdict["existing_bind"], row["bound_episode_id"])
        self.assertEqual(verdict["new_candidate"], row["late_candidate_episode_id"])
        self.assertNotIn(verdict["action"], erc.FORBIDDEN_REAUDIT_ACTIONS)

    def test_the_bind_is_untouched_while_the_ambiguity_is_open(self):
        """Matrix row 11: the fold does not move until the person answers."""
        row = FIXTURE["arrival_order_divergence"]
        bindings = [{
            "identity_id": "eid:z", "telling_ref": row["telling_ref"],
            "episode_id": row["bound_episode_id"], "relation": "same",
            "origin": "deterministic", "canonical_event_kind": "job",
            "subject_keys": ["org/larkspur"]}]
        claims = [{"claim_id": "claim:z", "event_kind": "job", "event_ref": ""}]
        manifest = {"tellings": [{"telling_ref": row["telling_ref"],
                                  "claim_ids": ["claim:z"]}]}
        before = efc.fold_grouping(claims, manifest, bindings)
        erc.reaudit(trigger="new_telling", telling_ref=row["telling_ref"],
                    bound_episode_id=row["bound_episode_id"],
                    candidate_episode_id=row["late_candidate_episode_id"])
        self.assertEqual(efc.fold_grouping(claims, manifest, bindings), before)

    def test_two_arrival_orders_can_produce_different_partitions(self):
        """The honest contract, demonstrated rather than asserted.

        There is deliberately NO partition-equality test in this file. v2
        promised it, audit F4 showed the incremental binder cannot deliver it,
        and v4 deleted the promise; a test asserting it would be a test
        asserting something the algorithm does not do.
        """
        row = FIXTURE["arrival_order_divergence"]
        claims = [{"claim_id": "claim:z", "event_kind": "job", "event_ref": ""}]
        manifest = {"tellings": [{"telling_ref": row["telling_ref"],
                                  "claim_ids": ["claim:z"]}]}
        bound = efc.fold_grouping(claims, manifest, [{
            "identity_id": "eid:z", "telling_ref": row["telling_ref"],
            "episode_id": row["bound_episode_id"], "relation": "same",
            "origin": "deterministic", "canonical_event_kind": "job",
            "subject_keys": ["org/larkspur"]}])
        declined = efc.fold_grouping(claims, manifest, [])
        self.assertNotEqual(bound, declined)
        self.assertEqual(list(declined), [""], "the declined order leaves v264's key")


class OneDefinitionManyHosts(unittest.TestCase):
    """ADR 0021 applied to this program's own vocabulary."""

    def test_identity_rule_version_is_defined_exactly_once(self):
        pattern = re.compile(r"^IDENTITY_RULE_VERSION\s*=", re.MULTILINE)
        homes = sorted(
            path.name for path in (ROOT / "system").glob("*.py")
            if pattern.search(path.read_text("utf-8"))
        )
        self.assertEqual(homes, ["episode_fold_contract.py"],
                         "IDENTITY_RULE_VERSION has one home; every other module "
                         "imports it from episode_fold_contract")
        self.assertEqual(efc.IDENTITY_RULE_VERSION, "event-identity:1")

    def test_the_contract_modules_do_no_io(self):
        """The fold is pure (Law 1). A contract that could write is a contract
        that could be tested against something it wrote."""
        forbidden = {"open", "write_text", "read_text", "mkdir", "unlink", "dump",
                     "dumps_to", "run", "system", "popen"}
        for name in ("episode_fold_contract.py", "episode_routing_contract.py"):
            tree = ast.parse((ROOT / "system" / name).read_text("utf-8"))
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                func = node.func
                called = getattr(func, "attr", None) or getattr(func, "id", None)
                self.assertNotIn(called, forbidden, f"{name} calls {called}()")

    def test_the_calculation_rule_version_did_not_move_in_i0(self):
        """I0 is docs and tests. `timeline-rules:5` belongs to I1, where
        grouping actually changes and every fingerprint moves with it."""
        import temporal_timeline as tt  # noqa: PLC0415

        self.assertEqual(tt.CALCULATION_RULE_VERSION, "timeline-rules:4")


if __name__ == "__main__":
    unittest.main()
