"""v224 — the calculated timeline (audited timeline build plan §6.4, §6.5, §7, §10).

Wave D's exit gate is *"a clean rebuild is correct, deterministic, explainable,
and within the initial scale budget"*, so these tests are organized around those
four words rather than around the module's functions.

The §10 acceptance scenarios appear here verbatim in name: "the summer after we
moved" tightening when the move date arrives, "about 12" as a fuzzy interval
rather than a birthday-derived day, two incompatible explicit dates both
preserved with the conflict surfaced, a new anchor changing only calculated
outputs, and an unresolved contradiction blocking nothing else.

Synthetic data only; NEVER references ~/Workspace/dave.
"""

from __future__ import annotations

import ast
import hashlib
import random
import sys
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "system"))

import chronology as chrono  # noqa: E402
import identity_resolution as ident  # noqa: E402
import temporal_claims as tc  # noqa: E402
import temporal_projection as tp  # noqa: E402
import temporal_store as ts  # noqa: E402
import temporal_timeline as tt  # noqa: E402
import temporal_work_items as twi  # noqa: E402


def revision(seed: str) -> str:
    return "sha256:" + hashlib.sha256(seed.encode("utf-8")).hexdigest()


def claim(**overrides) -> dict:
    """One validated claim. Every field the door requires, nothing decorative."""
    source = overrides.pop("source", "src-conversation-1")
    seed = overrides.pop("seed", source)
    payload = {
        "source_kind": "conversation",
        "source_ref": {"source_id": source, "revision": revision(seed)},
        "evidence": [{"quote": overrides.pop("quote", "a sentence from the conversation")}],
        "extractor_version": "listener:1",
        "created_at": "2026-08-26T00:00:00Z",
        "basis": "explicit",
        "confidence": 0.9,
        "status": "active",
    }
    payload.update(overrides)
    return tc.validate_temporal_claim(payload)


def index_of(*claims) -> dict:
    """The shape ``temporal_store.fold_active_index`` publishes, minimally."""
    return {"version": ts.INDEX_VERSION, "claims": [dict(row) for row in claims]}


NOW = "2026-08-26T12:00:00Z"


def derive(*claims, **kwargs):
    kwargs.setdefault("now", NOW)
    return tt.derive_calculated_timeline(index_of(*claims), **kwargs)


def node_for(result, event_kind: str, subject: str | None = None) -> dict | None:
    for row in result.nodes:
        if row.get("event_kind") != event_kind:
            continue
        if subject is None or subject in row.get("subject_refs", ()):
            return row
    return None


#: O-E6: the birth origin is a work item of EVERY vault that has not stated a
#: birthday, because it is the coordinate system every age frame is derived
#: from (`eras.md` §3, §7) rather than one gap among others. It is therefore a
#: constant of these fixtures and not the subject of tests about other gaps —
#: which is exactly why it is excluded by name here and asserted on its own in
#: :class:`TheBirthOrigin` below.
BIRTH_ORIGIN_ID = twi.birth_origin_work_item_id()


def items_of(result, kind: str, *, include_birth_origin: bool = False) -> list[dict]:
    rows = [row for row in result.work_items if row["kind"] == kind]
    if include_birth_origin:
        return rows
    return [row for row in rows if row["work_item_id"] != BIRTH_ORIGIN_ID]


# --------------------------------------------------------------------------
# Correct — the §10 acceptance scenarios
# --------------------------------------------------------------------------


class RelativeAndInferredTime(unittest.TestCase):
    """§10 "Relative and inferred time", clause by clause."""

    MOVE_ANCHOR = "the move"

    def cabin(self):
        return claim(
            claim_type="relative_order",
            subject_mention="the cabin summer",
            event_kind="span",
            temporal_value={"relation": "after", "anchors": [self.MOVE_ANCHOR]},
            quote="it was the summer after we moved",
            seed="cabin",
        )

    def move(self, value="1994-07"):
        return claim(
            claim_type="date",
            subject_mention=self.MOVE_ANCHOR,
            event_kind="move",
            temporal_value=value,
            quote="we moved in July 1994",
            seed="move",
        )

    def test_relative_claim_is_retained_unplaced_with_its_relation_visible(self):
        """"The summer after we moved" survives an unknown anchor (§6.4)."""
        result = derive(self.cabin())
        cabin = node_for(result, "span")
        self.assertIsNotNone(cabin)
        self.assertIsNone(cabin["best_temporal_value"])
        self.assertIn("after", cabin["provenance_summary"])
        self.assertIn(self.MOVE_ANCHOR, cabin["provenance_summary"])
        self.assertEqual(
            [row["finding"] for row in result.diagnostics["findings"]], ["anchor_unresolved"]
        )

    def test_the_missing_anchor_becomes_a_work_item_carrying_its_reach(self):
        result = derive(self.cabin())
        anchors = items_of(result, "missing_anchor")
        self.assertEqual(len(anchors), 1)
        item = anchors[0]
        self.assertEqual(item["requested_field"], "date")
        self.assertTrue(ident.is_unresolved_ref(item["subject_ref"]))
        self.assertEqual(result.reach[item["work_item_id"]], 1)
        self.assertAlmostEqual(item["system_value"], 1 / tt.REACH_SATURATION)

    def test_it_tightens_when_the_move_date_arrives(self):
        """The plan's own sentence: a new anchor tightens affected intervals."""
        before = derive(self.cabin())
        after = derive(self.cabin(), self.move())

        cabin_before = node_for(before, "span")
        cabin_after = node_for(after, "span")
        self.assertIsNone(cabin_before["best_temporal_value"])
        self.assertIsNotNone(cabin_after["best_temporal_value"])
        self.assertEqual(cabin_after["best_temporal_value"]["earliest"], "1994-07")
        self.assertEqual(cabin_after["basis"], "calculated")
        # The narrowed node now cites the evidence that placed it, so its
        # fingerprint moves when the anchor does.
        self.assertNotEqual(
            cabin_before["input_fingerprint"], cabin_after["input_fingerprint"]
        )
        self.assertIn(
            self.move()["claim_id"], cabin_after["input_claim_refs"]
        )
        self.assertEqual(items_of(after, "missing_anchor"), [])

    def test_adding_an_anchor_changes_only_calculated_outputs(self):
        """§10: the original source claims are untouched by a new anchor."""
        anniversary = claim(
            claim_type="date",
            subject_mention="Rosa",
            event_kind="married",
            temporal_value="1991-05-04",
            seed="rosa",
        )
        before = derive(self.cabin(), anniversary)
        after = derive(self.cabin(), anniversary, self.move())

        wedding_before = node_for(before, "married")
        wedding_after = node_for(after, "married")
        self.assertEqual(
            wedding_before["best_temporal_value"], wedding_after["best_temporal_value"]
        )
        self.assertEqual(wedding_before["basis"], wedding_after["basis"])
        self.assertEqual(
            wedding_before["input_fingerprint"], wedding_after["input_fingerprint"]
        )
        self.assertEqual(wedding_before["node_id"], wedding_after["node_id"])

    def test_about_twelve_is_a_fuzzy_interval_not_a_birthday_derived_day(self):
        """§10 verbatim: a calibrated basis and a band, never an exact date."""
        birth = claim(
            claim_type="date",
            subject_mention="self",
            event_kind="birth",
            temporal_value="1972-03-08",
            seed="birth",
        )
        fair = claim(
            claim_type="age",
            subject_mention="the state fair",
            event_kind="transition",
            temporal_value="about 12",
            quote="I was about 12",
            seed="fair",
        )
        result = derive(birth, fair, owner_ref="self")
        node = node_for(result, "transition")
        value = node["best_temporal_value"]
        self.assertEqual(node["basis"], "calculated")
        self.assertEqual(value["basis"], "age")
        self.assertEqual(value["confidence"], "approximate")
        # A band, and a wide one: the hedge earns a year on each side.
        # v255: the birthday here (1972-03-08) is day-precise, so the band's
        # BOUNDS are now the exact calendar span around it rather than the
        # old bare-year "1983".."1986" — that year-only pair could straddle
        # a later frame boundary a day-precise birthday never needs to
        # straddle. The test's own point survives unweakened: `best` still
        # stays a fuzzy `~` YEAR, never a derived day (the assertion right
        # below), which is what "never a birthday-derived day" means here.
        self.assertEqual((value["earliest"], value["latest"]),
                         ("1983-03-08", "1986-03-07"))
        self.assertNotRegex(value["best"] or "", r"^\d{4}-\d{2}-\d{2}$")

    def test_an_age_without_a_birthday_stays_unplaced_and_asks_for_the_anchor(self):
        fair = claim(
            claim_type="age",
            subject_mention="the state fair",
            event_kind="transition",
            temporal_value="about 12",
            seed="fair",
        )
        result = derive(fair, owner_ref="self")
        self.assertIsNone(node_for(result, "transition")["best_temporal_value"])
        self.assertIn(
            "age_without_birth_anchor",
            [row["finding"] for row in result.diagnostics["findings"]],
        )
        asks = [
            i
            for i in items_of(result, "missing_anchor", include_birth_origin=True)
            if i["requested_field"] == "birth_date"
        ]
        self.assertEqual(len(asks), 1)
        self.assertEqual(asks[0]["work_item_id"], BIRTH_ORIGIN_ID)
        self.assertEqual(asks[0]["claim_refs"], [fair["claim_id"]])

    def test_a_duration_places_nothing_until_it_has_a_start(self):
        lived = claim(
            claim_type="duration",
            subject_mention="the Mesa house",
            event_kind="span",
            temporal_value={"low": 3, "high": 3, "unit": "years"},
            quote="we lived there three years",
            seed="mesa-duration",
        )
        alone = derive(lived)
        self.assertIsNone(node_for(alone, "span")["best_temporal_value"])
        self.assertIn(
            "duration_without_start",
            [row["finding"] for row in alone.diagnostics["findings"]],
        )

        started = claim(
            claim_type="date",
            subject_mention="the Mesa house",
            event_kind="span",
            temporal_value="1988",
            seed="mesa-start",
        )
        placed = derive(lived, started)
        value = node_for(placed, "span")["best_temporal_value"]
        self.assertEqual((value["earliest"], value["latest"]), ("1988", "1991"))
        self.assertEqual(value["granularity"], "range")


class ContradictionsAndMirror(unittest.TestCase):
    """§10 "Contradictions and Mirror" — nothing is silently resolved."""

    def disagreeing(self):
        return (
            claim(
                claim_type="date",
                subject_mention="Katie",
                event_kind="married",
                temporal_value="1998-06-20",
                source="src-a",
                seed="a",
            ),
            claim(
                claim_type="date",
                subject_mention="Katie",
                event_kind="married",
                temporal_value="1999-06-20",
                source="src-b",
                seed="b",
            ),
        )

    def test_both_dates_are_preserved_and_the_conflict_is_signalled(self):
        result = derive(*self.disagreeing())
        node = node_for(result, "married")
        self.assertEqual(node["conflict_state"], "contradicted")
        self.assertEqual(len(node["alternate_values"]), 1)
        shown = {node["best_temporal_value"]["best"]}
        kept = {value["best"] for value in node["alternate_values"]}
        self.assertEqual(shown | kept, {"1998-06-20", "1999-06-20"})

    def test_the_contradiction_mints_one_mirror_row_citing_both_claims(self):
        first, second = self.disagreeing()
        result = derive(first, second)
        rows = items_of(result, "contradiction")
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(sorted(row["claim_refs"]), sorted([first["claim_id"], second["claim_id"]]))
        self.assertIn("mirror", row["allowed_surfaces"])
        self.assertEqual(row["state"], "open")
        self.assertGreaterEqual(row["system_value"], tt.MATERIAL_CONFLICT)

    def test_a_looser_alternate_is_corroboration_and_not_a_contradiction(self):
        """A coarser reading that INTERSECTS is the same claim said less well."""
        exact = claim(
            claim_type="date",
            subject_mention="Katie",
            event_kind="married",
            temporal_value="1998-06-20",
            source="src-a",
            seed="a",
        )
        coarse = claim(
            claim_type="date",
            subject_mention="Katie",
            event_kind="married",
            temporal_value="1998",
            source="src-b",
            seed="b",
        )
        result = derive(exact, coarse)
        node = node_for(result, "married")
        self.assertEqual(node["conflict_state"], "alternatives")
        self.assertEqual(items_of(result, "contradiction"), [])

    def test_an_unresolved_contradiction_blocks_nothing_else(self):
        """§10: unrelated nodes and queue work are calculated exactly as before."""
        first, second = self.disagreeing()
        other = claim(
            claim_type="date",
            subject_mention="Ivo",
            event_kind="birth",
            temporal_value="1979-11-02",
            seed="ivo",
        )
        without = derive(other)
        with_conflict = derive(first, second, other)

        clean_before = node_for(without, "birth")
        clean_after = node_for(with_conflict, "birth")
        self.assertEqual(clean_before, clean_after)
        self.assertEqual(node_for(with_conflict, "married")["conflict_state"], "contradicted")

    def test_a_drag_against_an_explicit_date_keeps_both_and_opens_a_row(self):
        """§2.6/§10: the move is preserved, the explicit date keeps the display."""
        early = claim(
            claim_type="date",
            subject_mention="high school",
            event_kind="school",
            temporal_value="1986/1990",
            seed="hs",
        )
        college = claim(
            claim_type="date",
            subject_mention="college",
            event_kind="school",
            temporal_value="1990/1994",
            seed="college",
        )
        result = derive(early, college)
        college_node = [n for n in result.nodes if "college" in n["subject_refs"]][0]
        high_school = [n for n in result.nodes if "high school" in n["subject_refs"]][0]

        drag = tc.validate_ordering_constraint(
            {
                "relation": "before",
                "subject_node_id": college_node["node_id"],
                "anchor_node_ids": [high_school["node_id"]],
                "source_ref": {"source_id": "sources/corrections/drag", "revision": revision("drag")},
                "created_at": NOW,
            }
        )
        moved = derive(early, college, constraints=[drag])
        node = [n for n in moved.nodes if "college" in n["subject_refs"]][0]
        self.assertEqual(node["best_temporal_value"]["earliest"], "1990")
        self.assertEqual(node["conflict_state"], "contradicted")
        self.assertTrue(node["alternate_values"])
        self.assertIn(drag["constraint_id"], node["input_constraint_refs"])
        rows = items_of(moved, "contradiction")
        self.assertTrue(any(drag["constraint_id"] in row["claim_refs"] for row in rows))

    def test_an_order_cycle_is_a_contradiction_and_never_a_hang(self):
        first = claim(
            claim_type="date",
            subject_mention="the wedding",
            event_kind="married",
            temporal_value="2001",
            seed="w",
        )
        second = claim(
            claim_type="date",
            subject_mention="the reception",
            event_kind="transition",
            temporal_value="2001",
            seed="r",
        )
        after = claim(
            claim_type="relative_order",
            subject_mention="the wedding",
            event_kind="married",
            temporal_value={"relation": "after", "anchors": ["the reception"]},
            seed="w-after",
        )
        before = claim(
            claim_type="relative_order",
            subject_mention="the reception",
            event_kind="transition",
            temporal_value={"relation": "after", "anchors": ["the wedding"]},
            seed="r-after",
        )
        started = time.perf_counter()
        result = derive(first, second, after, before)
        self.assertLess(time.perf_counter() - started, 1.0)
        self.assertIn(
            "order_cycle", [row["finding"] for row in result.diagnostics["findings"]]
        )
        cycles = [row for row in items_of(result, "contradiction") if row["requested_field"] == "order"]
        self.assertEqual(len(cycles), 1)
        self.assertGreaterEqual(len(cycles[0]["claim_refs"]), 2)


class IdentityAndEpisodes(unittest.TestCase):
    """§6.3 — an ambiguous mention is kept and becomes a Mirror item."""

    ROSTER = {
        "type": "person",
        "entities": [
            {"name": "AJ Moreno", "slug": "aj-moreno", "aliases": ["AJ"]},
            {"name": "Katie", "slug": "katie"},
        ],
    }

    AMBIGUOUS = {
        "type": "person",
        "entities": [
            {"name": "AJ Moreno", "slug": "aj-moreno", "aliases": ["AJ"]},
            {"name": "AJ Prince", "slug": "aj-prince", "aliases": ["AJ"]},
        ],
    }

    def aj(self):
        return claim(
            claim_type="date",
            subject_mention="AJ",
            event_kind="birth",
            temporal_value="1984",
            seed="aj",
        )

    def test_a_unique_alias_resolves_and_the_node_carries_the_entity_ref(self):
        result = derive(self.aj(), roster_snapshot=self.ROSTER)
        node = node_for(result, "birth")
        self.assertEqual(node["subject_refs"], ["person/aj-moreno"])
        self.assertEqual(items_of(result, "identity_uncertain"), [])

    def test_an_ambiguous_mention_keeps_its_claim_and_opens_a_mirror_row(self):
        result = derive(self.aj(), roster_snapshot=self.AMBIGUOUS)
        node = node_for(result, "birth")
        self.assertEqual(node["subject_refs"], ["AJ"])
        self.assertEqual(node["best_temporal_value"]["best"], "1984")
        rows = items_of(result, "identity_uncertain")
        self.assertEqual(len(rows), 1)
        self.assertEqual(
            sorted(rows[0]["allowed_surfaces"]), sorted(ident.IDENTITY_WORK_SURFACES)
        )
        self.assertEqual(rows[0]["claim_refs"], [self.aj()["claim_id"]])

    def test_a_relationship_transition_gets_the_edge_episode_id(self):
        married = claim(
            claim_type="date",
            subject_mention="Katie",
            event_kind="married",
            temporal_value="1998",
            seed="m",
        )
        result = derive(married, roster_snapshot=self.ROSTER, owner_ref="person/self")
        node = node_for(result, "married")
        self.assertEqual(node["node_kind"], "episode")
        self.assertEqual(
            node["node_id"],
            ident.derive_episode_ref(
                event_kind="married",
                subject_ref="person/katie",
                counterpart_ref="person/self",
            ),
        )

    def test_the_recorders_event_ref_wins_and_splits_two_stints(self):
        """Episode splitting is the recorder's; the fold honours it exactly."""
        first_ref = ident.derive_episode_ref(
            event_kind="job", subject_ref="Boeing", discriminator="1"
        )
        second_ref = ident.derive_episode_ref(
            event_kind="job", subject_ref="Boeing", discriminator="2"
        )
        first = claim(
            claim_type="date",
            subject_mention="Boeing",
            event_kind="job",
            event_ref=first_ref,
            temporal_value="1998",
            seed="b1",
        )
        second = claim(
            claim_type="date",
            subject_mention="Boeing",
            event_kind="job",
            event_ref=second_ref,
            temporal_value="2006",
            seed="b2",
        )
        result = derive(first, second)
        self.assertEqual(len(result.nodes), 2)
        self.assertEqual({n["node_id"] for n in result.nodes}, {first_ref, second_ref})
        self.assertEqual(items_of(result, "contradiction"), [])

    def test_without_an_event_ref_undistinguished_repeats_are_one_visible_conflict(self):
        first = claim(
            claim_type="date",
            subject_mention="Boeing",
            event_kind="job",
            temporal_value="1998",
            source="src-a",
            seed="b1",
        )
        second = claim(
            claim_type="date",
            subject_mention="Boeing",
            event_kind="job",
            temporal_value="2006",
            source="src-b",
            seed="b2",
        )
        result = derive(first, second)
        self.assertEqual(len(result.nodes), 1)
        self.assertEqual(result.nodes[0]["conflict_state"], "contradicted")
        self.assertEqual(len(items_of(result, "contradiction")), 1)


# --------------------------------------------------------------------------
# Explainable — work items, surfaces, and the loss rule
# --------------------------------------------------------------------------


class WorkItems(unittest.TestCase):
    def test_a_precise_gap_is_asked_at_the_precision_the_event_deserves(self):
        """§2.2 — a year is enough for a move; a wedding is worth the day."""
        move = claim(
            claim_type="date",
            subject_mention="Mesa",
            event_kind="move",
            temporal_value="1992",
            seed="mesa",
        )
        wedding = claim(
            claim_type="date",
            subject_mention="Katie",
            event_kind="married",
            temporal_value="1998",
            seed="katie",
        )
        result = derive(move, wedding)
        asked = {row["event_ref"]: row for row in items_of(result, "precision_gap")}
        self.assertNotIn(node_for(result, "move")["node_id"], asked)
        self.assertIn(node_for(result, "married")["node_id"], asked)

    def test_a_generic_loss_question_never_reaches_the_daily_queue(self):
        """§2.4 — loss discovery is offer-only."""
        loss = claim(
            claim_type="relative_order",
            subject_mention="somebody I lost",
            event_kind="loss",
            temporal_value={"relation": "before", "anchors": ["the move"]},
            seed="loss",
        )
        result = derive(loss)
        gaps = [row for row in result.work_items if row.get("event_ref")]
        self.assertTrue(gaps)
        for row in gaps:
            self.assertEqual(tuple(row["allowed_surfaces"]), tt.LOSS_DISCOVERY_SURFACES)
            self.assertNotIn("daily_question", row["allowed_surfaces"])
            self.assertNotIn("whisper", row["allowed_surfaces"])

    def test_a_named_loss_participates_in_ordinary_questions(self):
        """§2.4 — once the person is named, the ordinary surfaces apply."""
        roster = {"type": "person", "entities": [{"name": "Aunt Della", "slug": "aunt-della"}]}
        death = claim(
            claim_type="date",
            subject_mention="Aunt Della",
            event_kind="death",
            temporal_value="2011",
            seed="della",
        )
        result = derive(death, roster_snapshot=roster)
        gaps = items_of(result, "precision_gap")
        self.assertEqual(len(gaps), 1)
        self.assertIn("daily_question", gaps[0]["allowed_surfaces"])
        self.assertGreaterEqual(gaps[0]["sensitivity"], 0.8)

    def test_one_work_item_id_is_the_same_question_across_rebuilds(self):
        """§5.4 — answer once, update everywhere, needs one stable identity."""
        wedding = claim(
            claim_type="date",
            subject_mention="Katie",
            event_kind="married",
            temporal_value="1998",
            seed="katie",
        )
        first = derive(wedding)
        second = derive(wedding, claim(
            claim_type="date",
            subject_mention="Ivo",
            event_kind="birth",
            temporal_value="1979",
            seed="ivo",
        ))
        self.assertEqual(
            items_of(first, "precision_gap")[0]["work_item_id"],
            [row for row in items_of(second, "precision_gap")
             if row["event_ref"] == items_of(first, "precision_gap")[0]["event_ref"]][0]["work_item_id"],
        )

    def test_no_work_item_competes_with_itself(self):
        """§2.3 — the same id twice in one projection is the defect to detect."""
        result = derive(*_scale_claims(40))
        self.assertEqual(tp.surfaces_conflict(result.work_items), ())

    def test_every_item_names_a_surface_and_a_score(self):
        result = derive(*_scale_claims(20))
        self.assertTrue(result.work_items)
        for row in result.work_items:
            self.assertTrue(row["allowed_surfaces"])
            for name in tp.WORK_ITEM_SCORE_FIELDS:
                self.assertIn(name, row)
                self.assertGreaterEqual(row[name], 0.0)
                self.assertLessEqual(row[name], 1.0)
            self.assertIn(row["work_item_id"], result.score_components)

    def test_reach_counts_the_unplaced_nodes_an_anchor_would_place(self):
        anchor_name = "the fire"
        waiting = [
            claim(
                claim_type="relative_order",
                subject_mention=f"story {index}",
                event_kind="transition",
                temporal_value={"relation": "after", "anchors": [anchor_name]},
                seed=f"s{index}",
            )
            for index in range(3)
        ]
        result = derive(*waiting)
        item = items_of(result, "missing_anchor")[0]
        self.assertEqual(result.reach[item["work_item_id"]], 3)
        self.assertAlmostEqual(item["system_value"], 3 / tt.REACH_SATURATION)


# --------------------------------------------------------------------------
# Deterministic — the rebuild oracle
# --------------------------------------------------------------------------


def _scale_claims(subjects: int, *, relatives: bool = True) -> list[dict]:
    """A synthetic vault: dated subjects, disagreements, relatives, ages."""
    rows: list[dict] = []
    rows.append(
        claim(
            claim_type="date",
            subject_mention="self",
            event_kind="birth",
            temporal_value="1970-01-15",
            seed="self-birth",
        )
    )
    for index in range(subjects):
        name = f"person {index}"
        rows.append(
            claim(
                claim_type="date",
                subject_mention=name,
                event_kind="birth",
                temporal_value=f"{1940 + (index % 60)}",
                seed=f"birth-{index}",
            )
        )
        if index % 5 == 0:
            rows.append(
                claim(
                    claim_type="date",
                    subject_mention=name,
                    event_kind="birth",
                    temporal_value=f"{1941 + (index % 60)}",
                    source="src-second-teller",
                    seed=f"birth-alt-{index}",
                )
            )
        if index % 3 == 0:
            rows.append(
                claim(
                    claim_type="age",
                    subject_mention=f"trip {index}",
                    event_kind="transition",
                    temporal_value=f"about {8 + (index % 30)}",
                    seed=f"age-{index}",
                )
            )
        if relatives and index % 4 == 0:
            rows.append(
                claim(
                    claim_type="relative_order",
                    subject_mention=f"scene {index}",
                    event_kind="transition",
                    temporal_value={"relation": "after", "anchors": [f"person {index} — birth"]},
                    seed=f"rel-{index}",
                )
            )
    return rows


class RebuildIsTheOracle(unittest.TestCase):
    """§7 — twice from identical inputs, structurally identical output."""

    def test_rebuilding_twice_is_structurally_identical(self):
        rows = _scale_claims(30)
        first = derive(*rows)
        second = derive(*rows)
        self.assertEqual(tt.structural_signature(first), tt.structural_signature(second))

    def test_the_answer_does_not_depend_on_the_order_claims_arrived_in(self):
        rows = _scale_claims(25)
        baseline = tt.structural_signature(derive(*rows))
        rng = random.Random(1789)
        for _ in range(5):
            shuffled = list(rows)
            rng.shuffle(shuffled)
            self.assertEqual(tt.structural_signature(derive(*shuffled)), baseline)

    def test_structural_signature_excludes_the_runtime_metadata(self):
        rows = _scale_claims(5)
        result = derive(*rows, now="2026-01-01T00:00:00Z")
        later = derive(*rows, now="2027-12-31T23:59:59Z")
        self.assertNotEqual(result.work_items, later.work_items)
        self.assertEqual(tt.structural_signature(result), tt.structural_signature(later))
        signature = tt.structural_signature(result)
        self.assertNotIn("timings", signature)
        for row in signature["work_items"]:
            self.assertNotIn("created_at", row)
            self.assertNotIn("updated_at", row)

    def test_the_result_unpacks_as_nodes_and_work_items(self):
        nodes, work_items = derive(*_scale_claims(3))
        self.assertTrue(nodes)
        self.assertIsInstance(nodes, tuple)
        self.assertIsInstance(work_items, tuple)


class PhaseLatency(unittest.TestCase):
    """§7.1 — instrument the phases separately, from the first day."""

    def test_every_named_phase_is_reported(self):
        result = derive(*_scale_claims(10))
        self.assertEqual(sorted(result.timings), sorted(tt.TIMING_PHASES))
        for phase in tt.TIMING_PHASES:
            self.assertIsInstance(result.timings[phase], float)
            self.assertGreaterEqual(result.timings[phase], 0.0)
        parts = sum(result.timings[p] for p in tt.TIMING_PHASES if p != "total")
        self.assertLessEqual(parts, result.timings["total"] + 0.05)

    def test_a_maximum_scale_vault_derives_inside_the_wave_h_gate(self):
        """§7.1's gate is p95 > 2s; measure it now so wave H has a baseline."""
        rows = _scale_claims(200)
        self.assertGreater(len(rows), 300)
        started = time.perf_counter()
        result = derive(*rows)
        elapsed = time.perf_counter() - started
        self.assertLess(
            elapsed,
            2.0,
            f"derive took {elapsed:.3f}s over {len(rows)} claims — §7.1's gate is 2s",
        )
        self.assertGreater(len(result.nodes), 200)


# --------------------------------------------------------------------------
# One definition, many readers
# --------------------------------------------------------------------------


class OneDefinition(unittest.TestCase):
    def test_active_selection_matches_the_stores_own_predicate(self):
        """The recurring-defect doctrine's parity test, not a coincidence."""
        rows = [dict(row) for row in _scale_claims(6)]
        rows[0]["status"] = "superseded"
        rows[1]["status"] = "retracted"
        index = {"claims": rows}
        self.assertEqual(
            [row["claim_id"] for row in tt.active_claim_rows(index)],
            sorted(row["claim_id"] for row in ts.active_claims(index)),
        )

    def test_node_ids_come_from_the_substrates_one_minter(self):
        birth = claim(
            claim_type="date",
            subject_mention="Ivo",
            event_kind="birth",
            temporal_value="1979",
            seed="ivo",
        )
        node = node_for(derive(birth), "birth")
        self.assertEqual(
            node["node_id"],
            tp.derive_node_id(node_kind="event", event_kind="birth", subject_refs=["Ivo"]),
        )

    def test_granularity_ranking_is_read_from_chronology(self):
        self.assertEqual(
            [name for name, _ in sorted(tt._GRANULARITY_RANK.items(), key=lambda p: p[1])],
            list(chrono.GRANULARITIES),
        )

    def test_the_confidence_normalizer_tracks_chronologys_own_weights(self):
        best = chrono.DateRecord(
            best="1990", earliest="1990", latest="1990",
            granularity="year", confidence="certain", basis="document",
            provenance=tuple({"source": f"s{i}"} for i in range(9)),
        )
        self.assertLessEqual(chrono.claim_score(best), tt.MAX_CLAIM_SCORE)
        self.assertAlmostEqual(tt._node_confidence(best, 0.0), 1.0)

    def test_age_phrases_round_trip_through_the_one_age_parser(self):
        for low, high, hedged in ((12, 12, True), (12, 12, False), (5, 6, False), (5, 6, True)):
            text = tt.age_text_for_band(low, high, hedged)
            self.assertIsNotNone(text, (low, high, hedged))
            self.assertEqual(chrono.parse_age(text), (low, high, hedged))
        self.assertIsNone(tt.age_text_for_band(12.5, 12.5, False))
        self.assertIsNone(tt.age_text_for_band(200, 200, False))

    def test_the_band_door_and_the_phrase_door_agree(self):
        """The pin between the path this module took and the path it takes.

        Until v230 a stored age band became an interval by rebuilding a phrase
        (:func:`temporal_timeline.age_text_for_band`), verifying it re-parsed,
        and handing it to ``chronology.from_age``. It now goes straight in
        through ``chronology.from_age_band``. Both paths still exist, so this
        sweeps EVERY band the old one could express and demands the two agree
        record-for-record — the guarantee that promoting the arithmetic into
        ``chronology`` moved it rather than changed it.
        """
        birth = "1979"
        covered = 0
        for approximate in (False, True):
            for low in range(121):
                for high in range(low, 121):
                    text = tt.age_text_for_band(low, high, approximate)
                    if text is None:
                        self.assertIsNone(
                            chrono.from_age_band(
                                birth, low, high, approximate=approximate
                            ),
                            (low, high, approximate),
                        )
                        continue
                    covered += 1
                    self.assertEqual(chrono.parse_age(text), (low, high, approximate))
                    self.assertEqual(
                        chrono.from_age(birth, text),
                        chrono.from_age_band(
                            birth, low, high, approximate=approximate, claim=text
                        ),
                        (low, high, approximate),
                    )
        self.assertGreater(covered, 1000)

    def test_a_band_outside_the_age_parsers_domain_is_reported_never_invented(self):
        """The two doors also refuse the same bands, so the finding is unchanged."""
        for low, high in ((12.5, 12.5), (200, 200), (6, 5)):
            self.assertIsNone(tt.age_text_for_band(low, high, False))
            self.assertIsNone(chrono.from_age_band("1979", low, high))

    def test_durations_round_outward_in_every_unit(self):
        """The conversion moved to ``chronology`` — one home for date arithmetic."""
        self.assertEqual(chrono.duration_years_band({"low": 3, "high": 3, "unit": "years"}), (3, 3))
        self.assertEqual(chrono.duration_years_band({"low": 8, "high": 8, "unit": "months"}), (0, 1))
        self.assertEqual(chrono.duration_years_band({"low": 30, "high": 30, "unit": "days"}), (0, 1))
        self.assertIsNone(chrono.duration_years_band({"low": 1, "high": 1, "unit": "fortnights"}))
        self.assertFalse(hasattr(tt, "duration_years_band"))

    def test_every_declared_finding_is_one_the_module_can_report(self):
        """The sibling modules' AST pin: a vocabulary nobody emits is a lie."""
        source = (ROOT / "system" / "temporal_timeline.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        emitted: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                emitted.add(node.value)
        for code in tt.ERROR_CODES:
            self.assertIn(code, emitted, f"{code} is declared but never reported")


class TheBirthOrigin(unittest.TestCase):
    """O-E6 / T-Q-01, T-Q-02, T-Q-05 — `eras.md` §3.1, §3.2, §7.

    The birth origin is not one gap among others: every age frame is
    calculated from it, so the question that asks for it exists whenever the
    answer does not, and it is worth something before any other evidence has
    arrived. Both halves used to be false — the item was minted only when an
    age claim had already tripped over its absence, and its whole worth was
    that reach.
    """

    def birth(self, value="1981-07-11", *, subject="self", basis="explicit",
              claim_type="date", seed="birth"):
        return claim(
            claim_type=claim_type,
            subject_mention=subject,
            event_kind="birth",
            temporal_value=value,
            quote="I was born in July 1981",
            basis=basis,
            seed=seed,
        )

    def a_dated_thing(self):
        return claim(
            claim_type="date",
            subject_mention="the move",
            event_kind="move",
            temporal_value="1999",
            seed="move-only",
        )

    def item(self, result):
        rows = [
            row for row in result.work_items if row["work_item_id"] == BIRTH_ORIGIN_ID
        ]
        return rows[0] if rows else None

    # -- T-Q-01 --------------------------------------------------------------

    def test_a_birthless_vault_asks_for_the_birthday_with_no_age_claims_at_all(self):
        """T-Q-01. Nothing has tripped over the absence; the ask exists anyway."""
        result = derive(self.a_dated_thing(), owner_ref="self")
        self.assertNotIn(
            "age_without_birth_anchor",
            [row["finding"] for row in result.diagnostics["findings"]],
        )
        item = self.item(result)
        self.assertIsNotNone(item, "the birth origin has no question")
        self.assertEqual(item["kind"], "missing_anchor")
        self.assertEqual(item["subject_ref"], "self")
        self.assertEqual(item["requested_field"], "birth_date")
        self.assertEqual(item["claim_refs"], [])
        # No invented count in the prompt when nothing is waiting on it.
        self.assertEqual(item["prompt_intent"], "What is your date of birth?")

    def test_it_clears_the_queue_threshold_that_reach_alone_could_not(self):
        """T-Q-01, the half that matters: it is askable, not merely present.

        The old formula stated its worth as `reach / REACH_SATURATION`, which
        is ZERO on a vault with no age claims — so the one item that unlocks
        the coordinate system scored below the queue threshold on exactly the
        vault that needed it. Both numbers are computed here from the shipped
        scorer rather than quoted, so a weight change moves the assertion.
        """
        import question_planner as qp  # noqa: PLC0415

        threshold = float(qp.DEFAULT_LANE_POLICY["work_item_queue_threshold"])
        item = self.item(derive(self.a_dated_thing(), owner_ref="self"))
        self.assertGreaterEqual(
            qp.score_work_item(item)["combined_score"], threshold
        )
        reach_only = {**item, "system_value": 0.0}
        self.assertLess(
            qp.score_work_item(reach_only)["combined_score"],
            threshold,
            "the pre-O-E6 statement of its worth would still reach the queue — "
            "this test is no longer proving anything",
        )

    def test_no_priority_class_anywhere_bought_the_slot(self):
        """T-Q-01: it wins on a stated term in one formula, not on its type."""
        item = self.item(derive(self.a_dated_thing(), owner_ref="self"))
        self.assertNotIn("birth", str(tt.WORK_ITEM_VALUE_DEFAULTS))
        self.assertEqual(
            item["allowed_surfaces"], list(tt.SURFACES_BY_KIND["missing_anchor"])
        )

    # -- T-Q-02 --------------------------------------------------------------

    def test_the_value_is_the_scaffold_plus_bounded_reach(self):
        """T-Q-02: `clamp(0.6 + min(0.4, age_claims / REACH_SATURATION), 0, 1)`."""
        self.assertAlmostEqual(twi.birth_origin_system_value(0), 0.6)
        self.assertAlmostEqual(twi.birth_origin_system_value(1), 0.8)
        self.assertAlmostEqual(twi.birth_origin_system_value(2), 1.0)
        # Saturated, never above one, however many things are waiting.
        self.assertAlmostEqual(twi.birth_origin_system_value(500), 1.0)

    def test_the_fold_states_the_rule_that_minted_the_number(self):
        """T-Q-02: `temporal-score:2` on the item AND on the envelope."""
        result = derive(self.a_dated_thing(), owner_ref="self")
        self.assertEqual(self.item(result)["score_rule"], "temporal-score:2")
        self.assertEqual(result.score_formula_version, "temporal-score:2")
        self.assertEqual(tt.SCORE_FORMULA_VERSION, twi.BIRTH_ORIGIN_SCORE_RULE)

    def test_the_raw_count_still_travels_beside_the_normalized_one(self):
        fair = claim(
            claim_type="age",
            subject_mention="the state fair",
            event_kind="transition",
            temporal_value="about 12",
            seed="fair-reach",
        )
        result = derive(fair, owner_ref="self")
        item = self.item(result)
        self.assertEqual(result.reach[BIRTH_ORIGIN_ID], 1)
        self.assertAlmostEqual(item["system_value"], 0.8)
        self.assertIn("1 thing you dated by age", item["prompt_intent"])

    # -- T-Q-05 --------------------------------------------------------------

    def test_an_explicit_birthday_closes_it(self):
        """T-Q-05, the positive half."""
        result = derive(self.birth(), owner_ref="self")
        self.assertIsNone(self.item(result), "a stated birthday leaves the ask open")

    def test_the_legacy_domain_word_subject_closes_it_too(self):
        """§3.1: a pre-O-E0b receipt mentions `birth`, not `self`.

        The fold must read that as the owner's own birth, or the E0b extraction
        change would open a question against a vault that has the birthday.
        """
        result = derive(self.birth(subject="birth", seed="legacy-birth"),
                        owner_ref="self")
        self.assertIsNone(self.item(result))

    def test_a_calculated_origin_does_not_close_it(self):
        """T-Q-05, the half `eras.md` §3.2 is explicit about.

        A provisional origin worked out from age statements is a VIEW, not a
        birthday: *"the explicit-birthday work item stays open"*. The predicate
        is the published class, so E-BO's provisional node needs no new flag —
        it arrives `calculated` and this keeps holding.
        """
        stated = chrono.DateRecord(
            earliest="1981-07-11", latest="1981-07-11", best="1981-07-11",
            granularity="day", confidence="certain", basis="stated",
        )
        # Exactly the shape §3.2 describes: an interval worked out from age
        # statements, wide, approximate, `basis: age` -> class `calculated`.
        provisional = chrono.DateRecord(
            earliest="1980", latest="1982", best="1981",
            granularity="year", confidence="approximate", basis="age",
        )
        self.assertTrue(twi.is_explicit_origin(stated))
        for record in (provisional, provisional.to_dict(), None):
            self.assertFalse(twi.is_explicit_origin(record))

        # And the fold's own predicate, on a real owner birth group. E-BO owns
        # the provisional NODE; what this pins is that when it arrives it will
        # not close the ask, with no new flag required of it.
        groups = {"node:x": {"event_kind": "birth", "subject": "self"}}
        self.assertTrue(
            tt._has_explicit_owner_birth(groups, {"node:x": stated}, "self")
        )
        self.assertFalse(
            tt._has_explicit_owner_birth(groups, {"node:x": provisional}, "self")
        )
        self.assertFalse(
            tt._has_explicit_owner_birth(groups, {"node:x": None}, "self")
        )

    def test_the_identity_is_one_string_however_it_is_derived(self):
        """The id the platform, the bank and the keystone lane all resolve to."""
        self.assertEqual(
            BIRTH_ORIGIN_ID,
            tp.derive_work_item_id(
                kind="missing_anchor", subject_ref="self",
                event_ref=None, requested_field="birth_date",
            ),
        )


class ProjectionContract(unittest.TestCase):
    """Every node this module emits survives §5.3's own door."""

    def test_all_nodes_and_items_revalidate(self):
        result = derive(*_scale_claims(15))
        for row in result.nodes:
            self.assertEqual(tp.validate_calculated_timeline_node(row)["node_id"], row["node_id"])
            self.assertTrue(row["input_claim_refs"])
            self.assertEqual(row["calculation_rule_version"], tt.CALCULATION_RULE_VERSION)
            if row["alternate_values"]:
                self.assertNotEqual(row["conflict_state"], "none")
        for row in result.work_items:
            self.assertEqual(
                tp.validate_temporal_work_item(row)["work_item_id"], row["work_item_id"]
            )

    def test_nodes_come_back_in_best_supported_order(self):
        result = derive(*_scale_claims(12))
        placed = [
            row["best_temporal_value"]["earliest"]
            for row in result.nodes
            if row["best_temporal_value"] and row["best_temporal_value"].get("earliest")
        ]
        self.assertEqual(placed, sorted(placed))
        seen_unplaced = False
        for row in result.nodes:
            if row["best_temporal_value"] is None:
                seen_unplaced = True
            elif seen_unplaced:
                self.fail("an unplaced node sorted before a placed one")

    def test_the_generation_is_stamped_on_every_node(self):
        result = derive(*_scale_claims(3), projection_generation=7)
        self.assertTrue(all(row["projection_generation"] == 7 for row in result.nodes))
        self.assertEqual(result.projection_generation, 7)

    def test_an_empty_substrate_derives_no_nodes_and_one_question(self):
        """O-E6: no claims means no nodes — and one thing worth asking.

        Before O-E6 an empty substrate published literally nothing, which read
        as tidy and was a hole: a vault that has said nothing has no birthday
        either, and the birthday is what every age frame is calculated from
        (`eras.md` §3). The projection now states that absence as the one work
        item it is, and nothing else.
        """
        result = tt.derive_calculated_timeline({"claims": []}, now=NOW)
        self.assertEqual(result.nodes, ())
        self.assertEqual(
            [row["work_item_id"] for row in result.work_items], [BIRTH_ORIGIN_ID]
        )
        self.assertEqual(result.diagnostics["claims"], 0)

    def test_an_unreadable_index_is_named_rather_than_guessed(self):
        with self.assertRaises(tt.TemporalTimelineError) as caught:
            tt.derive_calculated_timeline("not an index")
        self.assertEqual(caught.exception.code, "active_index_unusable")

    def test_identity_claims_assert_who_and_build_no_row(self):
        who = claim(
            claim_type="identity",
            subject_mention="AJ",
            temporal_value=None,
            seed="who",
        )
        result = derive(who)
        self.assertEqual(result.nodes, ())


if __name__ == "__main__":
    unittest.main()
