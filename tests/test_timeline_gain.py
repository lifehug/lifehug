"""Cut 3a — ONE comparable gain for every Timeline-owned item (ADR 0027).

The defect this closes: Needs Placing ranked legacy unknowns by `leverage`
(`timeline.row_leverage`, v208) and calculated work items by `combined_score`,
two numbers on two scales, with a category order on top of both. `timeline_gain`
ports the legacy arithmetic — `resolves`, `leverage = 1 + len(resolves)`, and
the greedy keystone plan over the residual graph — onto the calculated
dependency graph. It is a PORT: no precision weighting, no uncertainty
estimate, no new metric (decision record 2026-09-03 §7 Cut 3; review §2.5).

The parity class is proved rather than asserted: `ParityTwinTests` builds ONE
set of facts twice — as a legacy `timeline_data()`-shaped payload and as
temporal claims — and checks that the two derivations reach the same number and
star the same thing.

Synthetic data only; NEVER references ~/Workspace/dave.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SYSTEM = ROOT / "system"
sys.path.insert(0, str(SYSTEM))

import temporal_claims as tc  # noqa: E402
import temporal_projection as tp  # noqa: E402
import temporal_publication as pub  # noqa: E402
import temporal_store as ts  # noqa: E402
import temporal_timeline as tt  # noqa: E402
import timeline_gain as tg  # noqa: E402
import timeline_interaction as ti  # noqa: E402

NOW = "2026-08-26T12:00:00Z"


def load(name):
    """`timeline` in its own module slot — `tests/test_timeline_unknowns.py`'s
    own door, so rebinding its vault constants cannot leak into a sibling."""
    spec = importlib.util.spec_from_file_location(name, SYSTEM / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    orig = sys.modules.get(name)
    sys.modules[name] = mod
    try:
        spec.loader.exec_module(mod)
    finally:
        if orig is not None:
            sys.modules[name] = orig
        else:
            sys.modules.pop(name, None)
    return mod


tl = load("timeline")


# --------------------------------------------------------------------------
# The two fixtures — ONE set of facts, told to both derivations
# --------------------------------------------------------------------------
#
# Five things sit inside one named stretch nobody has dated; one more thing
# happened and is attached to nothing. Dating the stretch places five; dating
# the loose thing places itself.

MOMENT_COUNT = 5


def revision(seed: str) -> str:
    return "sha256:" + hashlib.sha256(seed.encode("utf-8")).hexdigest()


def claim(**overrides) -> dict:
    source = overrides.pop("source", "src-conversation-1")
    seed = overrides.pop("seed", source)
    payload = {
        "source_kind": "conversation",
        "source_ref": {"source_id": source, "revision": revision(seed)},
        "evidence": [{"quote": "a sentence from the conversation"}],
        "extractor_version": "listener:1",
        "created_at": "2026-08-26T00:00:00Z",
        "basis": "explicit",
        "confidence": 0.9,
        "status": "active",
    }
    payload.update(overrides)
    return tc.validate_temporal_claim(payload)


def legacy_payload() -> dict:
    """The same facts as a legacy `timeline_data()` payload."""
    return {
        "periods": [{"slug": "the-lost-years", "name": "The Lost Years", "date": None}],
        "event_lineup": {
            "the-lost-years": [
                {"title": f"moment {n}", "description": f"Something, number {n}.",
                 "source": f"answers/L{n}.md", "source_short": f"L{n}", "date": None}
                for n in range(MOMENT_COUNT)
            ]
        },
        "entity_lineup": {},
        "unplaced_events": [
            {"title": "the barn dance", "description": "A dance in a barn.",
             "source": "answers/X1.md", "source_short": "X1", "date": None}
        ],
        "bands": [],
        "global_gaps": [],
        "gaps_by_period": {},
        "anchors": {},
    }


def calculated_claims() -> list[dict]:
    """The same facts as temporal claims.

    The stretch is a `named_era` somebody said lasted about five years and
    never dated — a node with no value; the five moments say they happened
    *within* it, which is the ordering edge D1 reads; the barn dance says only
    that it lasted a day, so it is attached to nothing.
    """
    rows = [
        claim(claim_type="duration", subject_mention="The Lost Years",
              event_kind="named_era", seed="era",
              temporal_value={"low": 5, "high": 5, "unit": "years",
                              "text": "about five years"}),
        claim(claim_type="duration", subject_mention="the barn dance",
              event_kind="moment", seed="barn",
              temporal_value={"low": 1, "high": 1, "unit": "days",
                              "text": "a day"}),
    ]
    rows.extend(
        claim(claim_type="relative_order", subject_mention=f"moment {n}",
              event_kind="moment", seed=f"moment-{n}",
              temporal_value={"relation": "within", "anchors": ["The Lost Years"]})
        for n in range(MOMENT_COUNT)
    )
    return rows


class CalculatedFixture(unittest.TestCase):
    """A throwaway vault per test, outside the repo and never ~/Workspace/dave."""

    claims = staticmethod(calculated_claims)

    def setUp(self) -> None:
        self.vault = Path(tempfile.mkdtemp(prefix="lifehug-timeline-gain-"))
        self.addCleanup(shutil.rmtree, self.vault, ignore_errors=True)
        (self.vault / "state").mkdir(parents=True, exist_ok=True)
        self.file_claims(self.claims())
        self.result = self.derive()

    def file_claims(self, claims) -> None:
        by_source: dict[tuple[str, str], list[dict]] = {}
        for row in claims:
            ref = row["source_ref"]
            by_source.setdefault((ref["source_id"], ref["revision"]), []).append(dict(row))
        for (source_id, rev), rows in by_source.items():
            ts.write_receipt(self.vault, {
                "source_ref": {"source_id": source_id, "revision": rev},
                "extractor_version": "listener:1",
                "claims": rows,
            })

    def derive(self, generation: int = 1):
        return tt.derive_calculated_timeline(
            ts.rebuild_active_index(self.vault),
            projection_generation=generation, now=NOW,
        )

    # -- readers ---------------------------------------------------------
    def node_for(self, label: str) -> str:
        for row in self.result.nodes:
            if row.get("label") == label:
                return row["node_id"]
        self.fail(f"no node labelled {label!r}")

    def item_for(self, node_id: str) -> dict:
        for row in self.result.work_items:
            if row.get("node_ref") == node_id:
                return row
        self.fail(f"no work item about {node_id}")

    def timeline_items(self) -> list[dict]:
        return [row for row in self.result.work_items if tg.is_timeline_owned(row)]


# --------------------------------------------------------------------------
# The arithmetic
# --------------------------------------------------------------------------


class GainArithmeticTests(CalculatedFixture):
    def test_a_structural_anchor_outranks_an_isolated_undated_event(self) -> None:
        """The point of the whole cut: one number, comparable across kinds."""
        era = self.item_for(self.node_for("The Lost Years"))
        loose = self.item_for(self.node_for("the barn dance"))
        self.assertEqual(era["leverage"], MOMENT_COUNT + 1)
        self.assertEqual(len(era["resolves"]), MOMENT_COUNT)
        self.assertEqual(loose["leverage"], 1)
        self.assertEqual(loose["resolves"], [])
        self.assertGreater(era["leverage"], loose["leverage"])

    def test_every_timeline_item_carries_a_leverage_of_at_least_one(self) -> None:
        """Self-inclusive: answering a row still places the row."""
        items = self.timeline_items()
        self.assertTrue(items)
        for row in items:
            with self.subTest(item=row["work_item_id"]):
                self.assertIn("leverage", row)
                self.assertIn("resolves", row)
                self.assertGreaterEqual(row["leverage"], 1)
                self.assertEqual(row["leverage"], 1 + len(row["resolves"]))

    def test_resolves_only_names_nodes_the_projection_actually_holds(self) -> None:
        """'Could place 18 stories' has to name eighteen real things."""
        known = {row["node_id"] for row in self.result.nodes}
        for row in self.timeline_items():
            for node_id in row["resolves"]:
                with self.subTest(item=row["work_item_id"], node=node_id):
                    self.assertIn(node_id, known)

    def test_an_item_never_resolves_itself(self) -> None:
        for row in self.timeline_items():
            with self.subTest(item=row["work_item_id"]):
                self.assertNotIn(row.get("node_ref"), row["resolves"])

    def test_a_mirror_owned_item_keeps_its_score_and_gets_no_leverage(self) -> None:
        """§3a scope: contradictions and identity questions are Mirror's, and
        ranking them by reach would answer a different question."""
        self.file_claims([
            claim(claim_type="date", subject_mention="Katie", event_kind="married",
                  temporal_value="1998-06-20", source="src-a", seed="a"),
            claim(claim_type="date", subject_mention="Katie", event_kind="married",
                  temporal_value="1999-06-20", source="src-b", seed="b"),
        ])
        result = self.derive(generation=2)
        mirror = [row for row in result.work_items
                  if row["kind"] in tg.MIRROR_OWNED_KINDS]
        self.assertTrue(mirror, "the fixture minted no Mirror-owned item")
        for row in mirror:
            with self.subTest(item=row["work_item_id"]):
                self.assertNotIn("leverage", row)
                self.assertNotIn("resolves", row)
                self.assertIn("combined_score", row)

    def test_the_published_gain_must_agree_with_the_ids_it_names(self) -> None:
        """The guard that makes 'could place N' uncheckable-by-accident
        impossible: the contract refuses the pair when they disagree."""
        item = dict(self.item_for(self.node_for("The Lost Years")))
        item["leverage"] = 99
        with self.assertRaises(tp.TemporalWorkItemError) as caught:
            tp.validate_temporal_work_item(item)
        self.assertEqual(caught.exception.code, "work_item_gain_inconsistent")

    def test_an_item_may_not_publish_itself_among_its_resolves(self) -> None:
        item = dict(self.item_for(self.node_for("The Lost Years")))
        item["resolves"] = [item["node_ref"]]
        item["leverage"] = 2
        with self.assertRaises(tp.TemporalWorkItemError) as caught:
            tp.validate_temporal_work_item(item)
        self.assertEqual(caught.exception.code, "work_item_gain_inconsistent")

    def test_the_gain_survives_a_round_trip_through_the_contract(self) -> None:
        item = self.item_for(self.node_for("The Lost Years"))
        back = tp.validate_temporal_work_item(
            tp.work_item_from_dict(item).to_dict()
        )
        self.assertEqual(back["resolves"], item["resolves"])
        self.assertEqual(back["leverage"], item["leverage"])


# --------------------------------------------------------------------------
# The dependency index — the five rules, each on its own
# --------------------------------------------------------------------------


class DependencyRuleTests(unittest.TestCase):
    def test_d1_an_ordering_anchor_claims_its_subject(self) -> None:
        index = tg.dependency_index(
            nodes=[{"node_id": "node:a"}, {"node_id": "node:b"}],
            ordering=[("node:b", ("node:a",))],
        )
        self.assertEqual(index, {"node:a": ["node:b"]})

    def test_d2_an_episode_claims_everything_it_contains(self) -> None:
        """A stay nobody has dated leaves five events holding a window."""
        nodes = [{"node_id": "node:stay"}] + [
            {"node_id": f"node:e{n}",
             "containments": [{"episode_node_id": "node:stay"}]}
            for n in range(5)
        ]
        index = tg.dependency_index(nodes=nodes)
        self.assertEqual(index["node:stay"], [f"node:e{n}" for n in range(5)])

    def test_d3_and_d4_arrive_as_anchors_with_no_node_of_their_own(self) -> None:
        index = tg.dependency_index(
            nodes=[{"node_id": "node:x"}, {"node_id": "node:y"}],
            anchors={tg.origin_anchor("self"): ["node:x"],
                     "unresolved:the big move": ["node:y"]},
        )
        self.assertEqual(index[tg.origin_anchor("self")], ["node:x"])
        self.assertEqual(index["unresolved:the big move"], ["node:y"])

    def test_d5_an_anchor_never_claims_something_already_placed(self) -> None:
        """Legacy filters its resolve sets to the live unknown keys; so does
        this. An anchor that would place a placed thing has earned nothing."""
        index = tg.dependency_index(
            nodes=[{"node_id": "node:a"}, {"node_id": "node:b"}, {"node_id": "node:c"}],
            ordering=[("node:b", ("node:a",)), ("node:c", ("node:a",))],
            universe={"node:b"},
        )
        self.assertEqual(index["node:a"], ["node:b"])

    def test_an_anchor_never_claims_itself(self) -> None:
        index = tg.dependency_index(
            nodes=[{"node_id": "node:a"}], ordering=[("node:a", ("node:a",))]
        )
        self.assertEqual(index, {})

    def test_a_membership_is_coverage_and_never_a_bound(self) -> None:
        """ADR 0030 / eras design §2.4, stated as a NON-rule: an era's members
        are coverage. Dating an era reaches its members through the `within`
        claim somebody made (D1) and through nothing else, so nothing here
        reads `memberships`."""
        source = (SYSTEM / "timeline_gain.py").read_text(encoding="utf-8")
        body = source.split('"""', 2)[-1]
        self.assertNotIn("memberships", body)

    def test_the_universe_is_the_unplaced_plus_what_an_item_is_about(self) -> None:
        items = [{"kind": "precision_gap", "node_ref": "node:coarse",
                  "allowed_surfaces": ["timeline"]},
                 {"kind": "contradiction", "node_ref": "node:mirror",
                  "allowed_surfaces": ["timeline", "mirror"]}]
        universe = tg.gain_universe(
            nodes=[{"node_id": "node:coarse"}, {"node_id": "node:blank"},
                   {"node_id": "node:mirror"}],
            items=items,
            unplaced=["node:blank"],
        )
        self.assertEqual(universe, {"node:coarse", "node:blank"})


class AnchorRefTests(unittest.TestCase):
    def test_a_node_shaped_item_is_looked_up_under_its_node(self) -> None:
        self.assertEqual(tg.anchor_ref({"node_ref": "node:a", "subject_ref": "self"}),
                         "node:a")

    def test_the_birth_origin_has_its_own_namespace(self) -> None:
        self.assertEqual(
            tg.anchor_ref({"subject_ref": "self", "requested_field": "birth_date"}),
            "origin:self",
        )

    def test_a_handle_is_looked_up_under_the_ref_its_item_was_minted_with(self) -> None:
        self.assertEqual(
            tg.anchor_ref({"subject_ref": "unresolved:the big move",
                           "requested_field": "date"}),
            "unresolved:the big move",
        )

    def test_an_item_that_becomes_no_anchor_scores_exactly_one(self) -> None:
        resolves, leverage = tg.item_gain({}, {"node:a": ["node:b"]})
        self.assertEqual((resolves, leverage), ([], 1))


class TimelineOwnershipTests(unittest.TestCase):
    def test_the_two_mirror_kinds_are_never_timeline_rows(self) -> None:
        for kind in tg.MIRROR_OWNED_KINDS:
            with self.subTest(kind=kind):
                self.assertFalse(tg.is_timeline_owned(
                    {"kind": kind, "allowed_surfaces": ["timeline", "mirror"]}))

    def test_an_item_off_the_timeline_surface_is_not_a_timeline_row(self) -> None:
        self.assertFalse(tg.is_timeline_owned(
            {"kind": "missing_anchor", "allowed_surfaces": ["whisper"]}))

    def test_every_other_registered_kind_on_the_surface_is_owned(self) -> None:
        for kind in tp.WORK_ITEM_KINDS:
            if kind in tg.MIRROR_OWNED_KINDS:
                continue
            with self.subTest(kind=kind):
                self.assertTrue(tg.is_timeline_owned(
                    {"kind": kind, "allowed_surfaces": ["timeline"]}))


# --------------------------------------------------------------------------
# The keystone plan
# --------------------------------------------------------------------------


class KeystonePlanTests(CalculatedFixture):
    def test_the_star_is_the_anchor_that_places_the_most(self) -> None:
        plan = self.result.keystones
        self.assertTrue(plan)
        self.assertEqual(plan[0]["node_ref"], self.node_for("The Lost Years"))
        self.assertEqual(plan[0]["gain"], MOMENT_COUNT)
        self.assertEqual(plan[0]["leverage"], MOMENT_COUNT + 1)

    def test_the_star_keeps_the_one_identity_it_is_asked_under(self) -> None:
        row = self.result.keystones[0]
        self.assertTrue(row["id"].startswith(ti.KEYSTONE_ID_PREFIX))
        self.assertEqual(row["id"], ti.keystone_question_id(row["anchor"]))
        self.assertNotIn("/", row["id"])

    def test_a_plan_that_runs_out_of_gain_stops_before_the_cap(self) -> None:
        """Nothing else in the fixture places anything else, so the honest
        plan is one row long even though two are allowed."""
        self.assertEqual(tg.KEYSTONE_CAP, 2)
        self.assertEqual(len(self.result.keystones), 1)

    def test_the_cap_is_the_legacy_cap(self) -> None:
        """The recurring-defect doctrine, as a pin: two copies of one number
        are allowed to exist only while a test proves they agree."""
        self.assertEqual(tg.KEYSTONE_CAP, tl.KEYSTONE_CAP)

    def test_asking_for_no_keystones_returns_none(self) -> None:
        self.assertEqual(tg.keystones(self.result.work_items,
                                      self.result.dependency_index, n=0), [])


class GreedyPlanTests(unittest.TestCase):
    """The residual rule, on a hand-built graph — v198's own finding: ordering
    independently by leverage double-counts, and on real vault data one star's
    resolve set was a strict SUBSET of the other's."""

    ITEMS = [
        {"work_item_id": "work:wide", "kind": "missing_anchor",
         "node_ref": "node:wide", "allowed_surfaces": ["timeline"],
         "interaction_cost": 0.3},
        {"work_item_id": "work:subset", "kind": "missing_anchor",
         "node_ref": "node:subset", "allowed_surfaces": ["timeline"],
         "interaction_cost": 0.3},
        {"work_item_id": "work:other", "kind": "missing_anchor",
         "node_ref": "node:other", "allowed_surfaces": ["timeline"],
         "interaction_cost": 0.3},
    ]
    INDEX = {
        "node:wide": ["node:a", "node:b", "node:c"],
        "node:subset": ["node:a", "node:b"],
        "node:other": ["node:d"],
    }

    def test_the_second_star_is_the_one_with_marginal_gain_not_leverage(self) -> None:
        plan = tg.keystones(self.ITEMS, self.INDEX)
        self.assertEqual([row["anchor"] for row in plan], ["node:wide", "node:other"])
        self.assertEqual([row["gain"] for row in plan], [3, 1])

    def test_an_anchor_whose_reach_is_already_covered_is_never_starred(self) -> None:
        plan = tg.keystones(
            [self.ITEMS[0], self.ITEMS[1]], self.INDEX, n=tg.KEYSTONE_CAP
        )
        self.assertEqual([row["anchor"] for row in plan], ["node:wide"])

    def test_a_row_keeps_its_total_reach_beside_its_marginal_gain(self) -> None:
        """`leverage` is what the person is shown; `gain` is what earned the
        star. They are different questions and the row answers both."""
        plan = tg.keystones(self.ITEMS, self.INDEX)
        for row in plan:
            with self.subTest(anchor=row["anchor"]):
                self.assertEqual(row["leverage"], 1 + len(row["resolves"]))
                self.assertLessEqual(row["gain"], len(row["resolves"]))

    def test_ties_break_on_the_cheaper_question_then_the_anchor(self) -> None:
        items = [
            {"work_item_id": "work:dear", "kind": "missing_anchor",
             "node_ref": "node:dear", "allowed_surfaces": ["timeline"],
             "interaction_cost": 0.9},
            {"work_item_id": "work:cheap", "kind": "missing_anchor",
             "node_ref": "node:cheap", "allowed_surfaces": ["timeline"],
             "interaction_cost": 0.1},
        ]
        index = {"node:dear": ["node:a"], "node:cheap": ["node:b"]}
        self.assertEqual([row["anchor"] for row in tg.keystones(items, index)],
                         ["node:cheap", "node:dear"])

    def test_a_mirror_owned_item_is_never_starred(self) -> None:
        items = [{"work_item_id": "work:m", "kind": "contradiction",
                  "node_ref": "node:wide", "allowed_surfaces": ["timeline", "mirror"]}]
        self.assertEqual(tg.keystones(items, self.INDEX), [])


# --------------------------------------------------------------------------
# Legacy and calculated agree
# --------------------------------------------------------------------------


class ParityTwinTests(CalculatedFixture):
    """ONE set of facts, told to both derivations (§3a test point 3).

    What agrees exactly: the ROW number. `timeline.row_leverage` gives the
    undated stretch `1 + 5`, and so does the calculated item about the same
    stretch; the loose event is `1` on both sides.

    What agrees in SUBSTANCE and cannot agree byte-for-byte: the star's
    identity. Both plans are `tl:<anchor-slug>`, but a legacy anchor is a
    readable slug (`tl:the-lost-years`) and a calculated one is a node digest,
    because a calculated node's identity is a digest — so the assertion is that
    both stars name THE SAME THING, checked through each side's own reference,
    rather than that two strings match. Nothing is invented to close that gap.
    """

    def setUp(self) -> None:
        super().setUp()
        self.legacy = legacy_payload()
        self.legacy_index = tl.dependency_index(self.legacy)
        self.legacy_rows = {row["key"]: row for row in tl.unknowns(self.legacy)}

    def test_the_stretch_scores_the_same_on_both_sides(self) -> None:
        legacy_resolves, legacy_leverage = tl.row_leverage(
            self.legacy_rows["period_bound:the-lost-years"], self.legacy_index
        )
        item = self.item_for(self.node_for("The Lost Years"))
        self.assertEqual(legacy_leverage, item["leverage"])
        self.assertEqual(len(legacy_resolves), len(item["resolves"]))
        self.assertEqual(legacy_leverage, MOMENT_COUNT + 1)

    def test_the_loose_event_scores_one_on_both_sides(self) -> None:
        _, legacy_leverage = tl.row_leverage(
            self.legacy_rows["moment::X1"], self.legacy_index
        )
        item = self.item_for(self.node_for("the barn dance"))
        self.assertEqual(legacy_leverage, 1)
        self.assertEqual(item["leverage"], 1)

    def test_both_plans_star_the_same_thing(self) -> None:
        legacy_star = tl.keystones(self.legacy)[0]
        calculated_star = self.result.keystones[0]
        self.assertEqual(legacy_star["anchor"], "period:the-lost-years")
        self.assertEqual(calculated_star["node_ref"], self.node_for("The Lost Years"))
        self.assertEqual(legacy_star["question_id"], "tl:the-lost-years")
        self.assertEqual(calculated_star["id"],
                         ti.keystone_question_id(calculated_star["anchor"]))

    def test_both_plans_reach_the_same_number_of_things(self) -> None:
        legacy_star = tl.keystones(self.legacy)[0]
        moments = [key for key in legacy_star["resolves"] if key.startswith("moment:")]
        self.assertEqual(len(moments), MOMENT_COUNT)
        self.assertEqual(len(self.result.keystones[0]["resolves"]), MOMENT_COUNT)


# --------------------------------------------------------------------------
# Determinism, publication, rebuild
# --------------------------------------------------------------------------


class DeterminismTests(CalculatedFixture):
    def test_the_gain_is_a_pure_function_of_the_substrate(self) -> None:
        first, second = self.derive(), self.derive()
        self.assertEqual(first.dependency_index, second.dependency_index)
        self.assertEqual(list(first.keystones), list(second.keystones))
        self.assertEqual(
            [(row["work_item_id"], row.get("leverage"), row.get("resolves"))
             for row in first.work_items],
            [(row["work_item_id"], row.get("leverage"), row.get("resolves"))
             for row in second.work_items],
        )

    def test_the_gain_is_inside_the_rebuild_signature(self) -> None:
        """§7's rebuild oracle, applied to the new keys: they are derived, so
        they belong in `structural_signature` and a drift is a diff rather
        than a number nobody can check."""
        signature = tt.structural_signature(self.derive())
        self.assertIn("dependency_index", signature)
        self.assertIn("keystones", signature)
        self.assertEqual(signature, tt.structural_signature(self.derive()))

    def test_a_full_rebuild_reproduces_the_published_gain(self) -> None:
        """Delete the derived state and fold the receipts again: §7's
        "deleting the index and rebuilding it changes nothing", asserted on
        the gain rather than only on the nodes."""
        pub.publish(self.vault, now=NOW)
        before = pub.read_projection(self.vault)
        (self.vault / "state" / "temporal" / "active-index.json").unlink(missing_ok=True)
        report = pub.verify(self.vault, now=NOW)
        self.assertTrue(report["identical"], report.get("differences"))
        after = pub.rebuild_signature(pub.read_projection(self.vault))
        self.assertEqual(after["keystones"], before["keystones"])
        self.assertEqual(after["dependency_index"], before["dependency_index"])


class PublicationTests(CalculatedFixture):
    def test_both_files_carry_the_plan_of_their_own_generation(self) -> None:
        pub.publish(self.vault, now=NOW)
        projection = pub.read_projection(self.vault)
        queue = pub.read_work_items(self.vault)
        self.assertEqual(projection["keystones"], queue["keystones"])
        self.assertEqual(projection["work_items"], queue["work_items"])
        self.assertTrue(projection["dependency_index"])

    def test_the_page_is_served_the_plan_and_the_per_item_gain(self) -> None:
        pub.publish(self.vault, now=NOW)
        view = pub.calculated_view(self.vault)
        self.assertIn("keystones", pub.view_block_keys())
        self.assertEqual(len(view["keystones"]), 1)
        served = {row["work_item_id"]: row for row in view["work_items"]}
        era_item = self.item_for(self.node_for("The Lost Years"))
        self.assertEqual(served[era_item["work_item_id"]]["leverage"],
                         MOMENT_COUNT + 1)

    def test_the_graph_the_numbers_came_from_is_accounted_for(self) -> None:
        """The O-E1b guard's own rule: a published top-level key is either
        served or named with a reason."""
        pub.publish(self.vault, now=NOW)
        payload = pub.read_projection(self.vault)
        self.assertIn("dependency_index", payload)
        self.assertEqual(set(payload) - set(pub.published_block_keys()), set())
        self.assertIn("dependency_index", pub.PUBLISHED_KEYS_NOT_SERVED)

    def test_a_projection_published_before_this_cut_reads_as_no_plan(self) -> None:
        """Tolerant by construction, like every additive key before it."""
        pub.publish(self.vault, now=NOW)
        path = pub.projection_path(self.vault)
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload.pop("keystones", None)
        path.write_text(json.dumps(payload) + "\n", encoding="utf-8")
        self.assertEqual(pub.calculated_view(self.vault)["keystones"], ())


class EmptyVaultTests(unittest.TestCase):
    def test_a_vault_with_nothing_in_it_publishes_an_empty_plan(self) -> None:
        vault = Path(tempfile.mkdtemp(prefix="lifehug-timeline-gain-empty-"))
        self.addCleanup(shutil.rmtree, vault, ignore_errors=True)
        pub.publish(vault, now=NOW)
        view = pub.calculated_view(vault)
        self.assertEqual(view["keystones"], ())


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
