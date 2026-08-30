"""I0-C4 — merge and split downstream rules, proved row by row.

Contract: `docs/contracts/event-identity-i0-fold.md`; design
lifehug-platform `docs/design/event-identity.md` (v4) §5.5, §5.6 and the §5.8
lifecycle matrix rows 8, 9, 11 and 12.

The audit's B1 finding is the reason this file exists: "a split restores the
prior drawing byte-identically" is true only before the person has labelled,
dragged, answered or opened anything. After that, a split has to route each
reference somewhere, and the contract is the table — one test per row, plus
the rule that governs every row it does not contain: **no post-merge decision
is ever copied to both sides.**

Every negative is proven to fire: run against the state where the guard
should trip, seen tripping, then run against the neighbouring state where it
must not.

Synthetic data only; NEVER references ~/Workspace/dave.
"""

from __future__ import annotations

import copy
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "system"))

import episode_fold_contract as efc  # noqa: E402
import episode_routing_contract as erc  # noqa: E402
import temporal_claims as tc  # noqa: E402
import temporal_work_items as twi  # noqa: E402

FIXTURE = json.loads(
    (ROOT / "tests" / "goldens" / "event_identity_i0_routing.json").read_text("utf-8")
)
SPLIT = FIXTURE["split"]
MERGE = FIXTURE["merge"]
REAUDIT = FIXTURE["reaudit"]
SURVIVOR = SPLIT["envelope"]["episode_id"]


def split_plan(references: object) -> erc.RoutingPlan:
    return erc.split_routing(
        envelope=copy.deepcopy(SPLIT["envelope"]),
        references=copy.deepcopy(references),
        telling_node_ids=SPLIT["telling_node_ids"],
    )


class SplitReferenceTable(unittest.TestCase):
    """§5.5 — one test per row of the table, driven by the fixture."""

    def test_every_row_routes_where_the_table_says(self):
        for row in SPLIT["rows"]:
            with self.subTest(design=row["design"],
                              kind=row["reference"]["reference_kind"],
                              reference=row["reference"]["reference_id"]):
                plan = split_plan([row["reference"]])
                destinations = plan.destinations_for(row["reference"]["reference_id"])
                self.assertEqual(destinations, (row["expect_destination"],))

    def test_the_table_covers_every_enumerated_reference_kind(self):
        named = tuple(rule["reference_kind"] for rule in erc.SPLIT_REFERENCE_RULES)
        self.assertEqual(named, erc.SPLIT_REFERENCE_KINDS)
        exercised = {row["reference"]["reference_kind"] for row in SPLIT["rows"]}
        missing = set(erc.SPLIT_REFERENCE_KINDS) - exercised
        self.assertEqual(missing, set(), "a table row no fixture exercises is a rule "
                                         "nobody proved")

    def test_no_reference_ever_reaches_two_destinations(self):
        """§5.5's governing clause, over the WHOLE table at once — the case a
        per-row test cannot see."""
        references = [row["reference"] for row in SPLIT["rows"]]
        plan = split_plan(references)
        for reference in references:
            with self.subTest(reference=reference["reference_id"]):
                self.assertEqual(len(plan.destinations_for(reference["reference_id"])), 1)
        self.assertEqual(
            len(plan.routes) + len(plan.mirror_judgments), len(references))

    def test_an_unattributable_decision_is_one_mirror_row_naming_both_sides(self):
        plan = split_plan([{"reference_kind": "ordering_constraint",
                            "reference_id": "oc:3"}])
        self.assertEqual(len(plan.mirror_judgments), 1)
        row = plan.mirror_judgments[0]
        self.assertEqual(row["kind"], erc.MIRROR_JUDGMENT_KIND)
        self.assertEqual(row["candidates"],
                         sorted({SURVIVOR, "episode:0000000000000000000000e9"}))
        # Proven not to fire: give the same constraint an anchor and it routes.
        anchored = split_plan([{"reference_kind": "ordering_constraint",
                                "reference_id": "oc:3",
                                "anchor_telling_ref": "landmark:lm-7"}])
        self.assertEqual(anchored.mirror_judgments, ())

    def test_an_unenumerated_reference_kind_is_never_routed_by_default(self):
        plan = split_plan([{"reference_kind": "pinned_photo", "reference_id": "pin:1"}])
        self.assertEqual(plan.routes, ())
        self.assertEqual(plan.mirror_judgments[0]["destination"], "mirror_judgment")

    def test_the_departing_telling_reverts_with_no_memberships(self):
        """§5.5: memberships stay with the survivor. The departing side gets
        NONE — not a copy, not a share."""
        plan = split_plan([{"reference_kind": "era_membership",
                            "reference_id": "membership:1"}])
        self.assertEqual([route.destination for route in plan.routes], [SURVIVOR])
        self.assertNotIn("episode:0000000000000000000000e9",
                         [route.destination for route in plan.routes])

    def test_a_departure_to_standalone_lands_on_its_own_node(self):
        envelope = copy.deepcopy(SPLIT["envelope"])
        envelope["destinations"] = {"landmark:lm-7": erc.SPLIT_DESTINATION_STANDALONE}
        plan = erc.split_routing(
            envelope=envelope,
            references=[{"reference_kind": "open_session", "reference_id": "session:1",
                         "telling_ref": "landmark:lm-7",
                         "node_id": "node:00000000000000000000cc01"}],
            telling_node_ids=SPLIT["telling_node_ids"],
        )
        self.assertEqual(plan.routes[0].destination, "node:00000000000000000000dd07")
        self.assertEqual(plan.node_aliases,
                         {"node:00000000000000000000cc01": "node:00000000000000000000dd07"})

    def test_the_survivor_keeps_the_episode_id(self):
        plan = split_plan([{"reference_kind": "episode_label", "reference_id": "label:1"}])
        self.assertEqual(plan.routes[0].destination, SURVIVOR)
        self.assertEqual(plan.episode_aliases, {}, "a split aliases nothing away")

    def test_a_split_with_no_destinations_is_refused(self):
        envelope = copy.deepcopy(SPLIT["envelope"])
        envelope["destinations"] = {}
        with self.assertRaises(tc.TemporalContractError) as caught:
            erc.split_routing(envelope=envelope, references=[])
        self.assertEqual(caught.exception.code, "split_needs_destinations")
        envelope["destinations"] = {"landmark:lm-7": "standalone"}
        self.assertIsInstance(erc.split_routing(envelope=envelope, references=[]),
                              erc.RoutingPlan)

    def test_a_split_without_a_surviving_episode_is_refused(self):
        envelope = copy.deepcopy(SPLIT["envelope"])
        envelope["episode_id"] = ""
        with self.assertRaises(tc.TemporalContractError) as caught:
            erc.split_routing(envelope=envelope, references=[])
        self.assertEqual(caught.exception.code, "split_needs_surviving_episode")

    def test_a_merge_envelope_is_refused_by_the_split_router(self):
        with self.assertRaises(tc.TemporalContractError) as caught:
            erc.split_routing(envelope=copy.deepcopy(MERGE["envelope"]), references=[])
        self.assertEqual(caught.exception.code, "split_routing_wrong_op")

    def test_the_superseded_bindings_ride_the_plan(self):
        plan = split_plan([])
        self.assertEqual(plan.superseded_binding_ids, ("eid:0002",))


class MergeContract(unittest.TestCase):
    """§5.8 matrix row 8 — one receipt moves every member, forever aliased."""

    def plan(self, **overrides) -> erc.RoutingPlan:
        envelope = copy.deepcopy(MERGE["envelope"])
        envelope.update(overrides)
        return erc.merge_routing(
            envelope=envelope, references=copy.deepcopy(MERGE["references"]),
            bindings=copy.deepcopy(MERGE["bindings"]),
        )

    def test_the_absorbed_id_aliases_to_the_survivor(self):
        plan = self.plan()
        self.assertEqual(plan.episode_aliases,
                         {MERGE["envelope"]["absorbed_episode_id"]:
                          MERGE["envelope"]["episode_id"]})

    def test_a_membership_left_live_is_refused(self):
        with self.assertRaises(tc.TemporalContractError) as caught:
            erc.merge_routing(
                envelope=copy.deepcopy(MERGE["envelope"]),
                references=[],
                bindings=copy.deepcopy(MERGE["bindings"]) + [MERGE["left_behind_binding"]],
            )
        self.assertEqual(caught.exception.code, erc.REFUSAL_MERGE_INCOMPLETE)
        self.assertIn("eid:0081", caught.exception.detail["binding_ids"])
        # Proven not to fire once the envelope names it too.
        envelope = copy.deepcopy(MERGE["envelope"])
        envelope["supersedes_binding_ids"] = ["eid:0080", "eid:0081"]
        self.assertIsInstance(
            erc.merge_routing(envelope=envelope, references=[],
                              bindings=copy.deepcopy(MERGE["bindings"]) +
                              [MERGE["left_behind_binding"]]),
            erc.RoutingPlan)

    def test_a_merge_that_forgets_the_alias_is_refused(self):
        with self.assertRaises(tc.TemporalContractError) as caught:
            self.plan(aliases_created=[])
        self.assertEqual(caught.exception.code, erc.REFUSAL_MERGE_INCOMPLETE)

    def test_a_merge_needs_both_episodes(self):
        with self.assertRaises(tc.TemporalContractError) as caught:
            self.plan(absorbed_episode_id="")
        self.assertEqual(caught.exception.code, "merge_needs_two_episodes")

    def test_open_work_items_re_key_through_the_alias_table(self):
        plan = self.plan()
        self.assertEqual(plan.work_item_aliases, {"work:pair-e2": "work:pair-e1"})
        self.assertEqual(twi.resolve_work_item_id("work:pair-e2",
                                                  aliases=plan.work_item_aliases),
                         "work:pair-e1")

    def test_an_open_session_keeps_its_target_through_node_aliases(self):
        plan = self.plan()
        self.assertEqual(plan.node_aliases,
                         {"node:00000000000000000000cc02": "node:00000000000000000000cc01"})

    def test_everything_else_points_at_the_survivor(self):
        plan = self.plan()
        label = [route for route in plan.routes if route.reference_kind == "episode_label"]
        self.assertEqual([route.destination for route in label],
                         [MERGE["envelope"]["episode_id"]])

    def test_nothing_a_merge_touches_becomes_a_mirror_judgment(self):
        """A merge unions (Law 4); there is no ambiguity to hand back."""
        self.assertEqual(self.plan().mirror_judgments, ())


class AliasResolution(unittest.TestCase):
    """§5.8 matrix row 12 — an absorbed id resolves, purely."""

    def test_an_absorbed_id_resolves_to_the_survivor(self):
        self.assertEqual(
            erc.resolve_episode_alias("episode:A", {"episode:A": "episode:B"}),
            "episode:B")

    def test_a_chain_resolves_all_the_way(self):
        table = {"episode:A": "episode:B", "episode:B": "episode:C"}
        self.assertEqual(erc.resolve_episode_alias("episode:A", table), "episode:C")

    def test_a_cycle_terminates_instead_of_hanging(self):
        table = {"episode:A": "episode:B", "episode:B": "episode:A"}
        self.assertIn(erc.resolve_episode_alias("episode:A", table),
                      ("episode:A", "episode:B"))

    def test_an_unknown_id_comes_back_unchanged(self):
        self.assertEqual(erc.resolve_episode_alias("episode:Z", {}), "episode:Z")
        self.assertEqual(erc.resolve_episode_alias("", {}), "")

    def test_the_pair_key_is_sorted_and_needs_both_sides(self):
        forward = erc.pair_event_key("classification:x#1", "episode:E")
        backward = erc.pair_event_key("episode:E", "classification:x#1")
        self.assertEqual(forward, backward)
        self.assertEqual(forward.count(erc.PAIR_KEY_SEPARATOR), 1)
        with self.assertRaises(tc.TemporalContractError) as caught:
            erc.pair_event_key("classification:x#1", "")
        self.assertEqual(caught.exception.code, "pair_key_needs_both_sides")

    def test_resolving_a_pair_resolves_both_halves(self):
        resolved = erc.resolve_pair(
            "classification:x#1", "episode:A",
            episode_aliases={"episode:A": "episode:B"},
            work_item_aliases={},
        )
        self.assertEqual(resolved["candidate_episode_id"], "episode:B")
        self.assertIn("episode:B", resolved["event_key"])


class DelayedPairAnswer(unittest.TestCase):
    """§5.8 matrix row 12's last clause — never misfiled."""

    def test_an_ordinary_answer_files_unchanged(self):
        verdict = erc.route_delayed_pair_answer(
            telling_ref="classification:x#1", candidate_episode_id="episode:E")
        self.assertEqual(verdict["outcome"], "filed")

    def test_an_answer_whose_episode_merged_files_against_the_survivor(self):
        verdict = erc.route_delayed_pair_answer(
            telling_ref="classification:x#1",
            candidate_episode_id="episode:0000000000000000000000e2",
            episode_aliases=FIXTURE["delayed_answer"]["episode_aliases"])
        self.assertEqual(verdict["outcome"], "filed_rekeyed")
        self.assertEqual(verdict["candidate_episode_id"],
                         "episode:0000000000000000000000e1")

    def test_an_answer_whose_telling_re_keyed_away_is_acknowledged_and_dropped(self):
        row = FIXTURE["delayed_answer"]
        verdict = erc.route_delayed_pair_answer(
            telling_ref=row["retired_tellings"][0],
            candidate_episode_id="episode:0000000000000000000000e2",
            episode_aliases=row["episode_aliases"],
            retired_tellings=row["retired_tellings"])
        self.assertEqual(verdict["outcome"], "acknowledged_and_dropped")
        self.assertIn("acknowledged", verdict["note"])
        self.assertNotIn("work_item_id", verdict,
                         "an acknowledged answer is filed NOWHERE, not filed quietly")
        # Proven not to fire: the same answer with the telling still live files.
        alive = erc.route_delayed_pair_answer(
            telling_ref=row["retired_tellings"][0],
            candidate_episode_id="episode:0000000000000000000000e2",
            episode_aliases=row["episode_aliases"], retired_tellings=[])
        self.assertEqual(alive["outcome"], "filed_rekeyed")

    def test_the_outcome_vocabulary_is_closed(self):
        self.assertEqual(len(set(erc.DELAYED_ANSWER_OUTCOMES)), 3)


class ReauditContract(unittest.TestCase):
    """§5.6 after audit G3 — one action, never a verdict."""

    def call(self, trigger: str, **overrides) -> dict:
        kwargs = {
            "trigger": trigger,
            "telling_ref": REAUDIT["telling_ref"],
            "bound_episode_id": REAUDIT["bound_episode_id"],
            "candidate_episode_id": REAUDIT["candidate_episode_id"],
        }
        kwargs.update(overrides)
        return erc.reaudit(**kwargs)

    def test_every_enumerated_trigger_mints_and_only_mints(self):
        for row in REAUDIT["triggers"]:
            with self.subTest(trigger=row["trigger"], why=row["why"]):
                verdict = self.call(row["trigger"])
                self.assertEqual(verdict["action"], erc.REAUDIT_MINT)
                self.assertEqual(verdict["kind"], erc.POSSIBLE_OVERMERGE_KIND)
                self.assertEqual(verdict["existing_bind"], REAUDIT["bound_episode_id"])
                self.assertEqual(verdict["new_candidate"],
                                 REAUDIT["candidate_episode_id"])
                self.assertNotIn(verdict["action"], erc.FORBIDDEN_REAUDIT_ACTIONS)

    def test_the_trigger_list_is_the_designs_own_list(self):
        self.assertEqual(
            erc.REAUDIT_TRIGGERS,
            ("new_telling", "new_date_evidence", "new_place_evidence",
             "new_participant_evidence", "entity_resolution_change", "telling_rekey",
             "rule_version_change", "episode_merge", "maintenance_sweep"))
        self.assertEqual(sorted(row["trigger"] for row in REAUDIT["triggers"]),
                         sorted(erc.REAUDIT_TRIGGERS),
                         "every enumerated trigger has a fixture")

    def test_an_unknown_trigger_is_refused(self):
        with self.assertRaises(tc.TemporalContractError) as caught:
            self.call("somebody_felt_like_it")
        self.assertEqual(caught.exception.code, "reaudit_unknown_trigger")

    def test_re_triggering_dedupes_on_the_pair(self):
        first = self.call("new_telling")
        second = self.call("maintenance_sweep", open_items=[first["item_id"]])
        self.assertEqual(second["action"], erc.REAUDIT_NO_ACTION)
        self.assertEqual(second["item_id"], first["item_id"])
        # …and the id does not depend on which trigger noticed.
        self.assertEqual(self.call("episode_merge")["item_id"], first["item_id"])

    def test_an_answered_pair_is_never_asked_again(self):
        verdict = self.call("new_telling", answered_pairs=[{
            "telling_ref": REAUDIT["telling_ref"],
            "candidate_episode_id": REAUDIT["candidate_episode_id"]}])
        self.assertEqual(verdict["action"], erc.REAUDIT_NO_ACTION)
        # Proven not to fire: a DIFFERENT pair on the same telling still mints.
        other = self.call("new_telling",
                          candidate_episode_id="episode:0000000000000000000000e3",
                          answered_pairs=[{
                              "telling_ref": REAUDIT["telling_ref"],
                              "candidate_episode_id": REAUDIT["candidate_episode_id"]}])
        self.assertEqual(other["action"], erc.REAUDIT_MINT)

    def test_a_stated_negative_closes_the_pair(self):
        bindings = [{"identity_id": "eid:n", "telling_ref": REAUDIT["telling_ref"],
                     "episode_id": REAUDIT["candidate_episode_id"],
                     "relation": "not_same", "origin": "confirmed"}]
        self.assertEqual(self.call("new_telling", bindings=bindings)["action"],
                         erc.REAUDIT_NO_ACTION)

    def test_the_candidate_being_the_bind_is_not_an_ambiguity(self):
        verdict = self.call("new_telling",
                            candidate_episode_id=REAUDIT["bound_episode_id"])
        self.assertEqual(verdict["action"], erc.REAUDIT_NO_ACTION)

    def test_a_re_audit_needs_a_whole_pair(self):
        with self.assertRaises(tc.TemporalContractError) as caught:
            self.call("new_telling", candidate_episode_id="")
        self.assertEqual(caught.exception.code, "reaudit_needs_a_pair")

    def test_no_forbidden_action_is_reachable_from_any_input(self):
        """The G3 promise, as a sweep: across every trigger and every
        neighbouring state this file constructs, the only two actions that
        ever come back are mint and nothing."""
        seen = set()
        for row in REAUDIT["triggers"]:
            seen.add(self.call(row["trigger"])["action"])
            seen.add(self.call(row["trigger"],
                               candidate_episode_id=REAUDIT["bound_episode_id"])["action"])
            seen.add(self.call(row["trigger"], answered_pairs=[{
                "telling_ref": REAUDIT["telling_ref"],
                "candidate_episode_id": REAUDIT["candidate_episode_id"]}])["action"])
        self.assertEqual(seen, {erc.REAUDIT_MINT, erc.REAUDIT_NO_ACTION})
        self.assertEqual(set(erc.FORBIDDEN_REAUDIT_ACTIONS) & seen, set())

    def test_the_item_carries_the_identity_rule_version(self):
        self.assertEqual(self.call("new_telling")["identity_rule_version"],
                         efc.IDENTITY_RULE_VERSION)


if __name__ == "__main__":
    unittest.main()
