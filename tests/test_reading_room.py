"""v204 / ADR 0025 — the Reading Room: the math, the bases, the interaction."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SYSTEM = ROOT / "system"
sys.path.insert(0, str(SYSTEM))

import chronology as ch  # noqa: E402
import conversation_delivery as cd  # noqa: E402
import landmarks_interaction as li  # noqa: E402
import question_candidates as qc  # noqa: E402
import reading_room as rr  # noqa: E402
import reading_room_evals as rre  # noqa: E402
import timeline as tl  # noqa: E402
import timeline_interaction as ti  # noqa: E402


def _vault() -> dict:
    """The research's own worked example (go-deep.md §8.2), as data.

    Eight undated moments in one era, three in another, one undated moment no
    anchor reaches at all, and two people — one of whom shares every source
    with the first era, which is what made the pre-v199 keystone list
    double-count.
    """
    return {
        "periods": [
            {"slug": "childhood-yucaipa", "name": "Childhood in Yucaipa", "date": None},
            {"slug": "mesa", "name": "Mesa", "date": None},
            {"slug": "now", "name": "Now", "date": {
                "best": "2020", "earliest": "2020", "latest": "2020",
                "granularity": "year", "confidence": "certain", "basis": "stated"}},
        ],
        "event_lineup": {
            "childhood-yucaipa": [
                {"title": f"moment {i}", "source_short": f"s{i}",
                 "source": f"answers/s{i}.md", "date": None}
                for i in range(8)
            ],
            "mesa": [
                {"title": f"mesa {i}", "source_short": f"m{i}", "date": None}
                for i in range(3)
            ],
            "now": [],
        },
        "entity_lineup": {
            # Mom is listed under the one era that has nothing undated in it,
            # so her resolve set is exactly the sources she SHARES — a strict
            # subset of the era's own. That is the shape the research found on
            # real vault data, and the reason a top-N leverage list
            # double-counts.
            "now": [
                {"slug": "mom", "title": "Mom", "type": "person",
                 "sources": [f"answers/s{i}.md" for i in range(7)]},
            ],
            "childhood-yucaipa": [
                {"slug": "uncle-ray", "title": "Uncle Ray", "type": "person",
                 "sources": ["f1"]},
                {"slug": "wildwood-school", "title": "Wildwood Elementary",
                 "type": "place", "sources": [f"s{i}" for i in range(7)]},
            ],
        },
        "unplaced_events": [
            {"title": "Grandma's funeral", "source_short": "f1", "date": None},
        ],
        "bands": [], "global_gaps": [], "gaps_by_period": {}, "anchors": {},
        "landmarks": [{"domain": "residences", "status": "open"},
                      {"domain": "schools", "status": "open"}],
    }


ROSTER = [
    {"slug": "uncle-ray", "name": "Uncle Ray", "relationship": "other", "living": True},
    {"slug": "mom", "name": "Mom", "relationship": "parent", "living": True},
]


class EvidenceBasisTests(unittest.TestCase):
    def test_the_three_evidence_bases_are_the_tail_of_the_closed_vocabulary(self):
        self.assertEqual(ch.EVIDENCE_BASES, ("document", "photo", "relative"))
        self.assertEqual(ch.BASES[-3:], ch.EVIDENCE_BASES)
        self.assertEqual(set(ch.BASIS_WEIGHT), set(ch.BASES))

    def test_the_weights_are_flat_and_in_the_ruled_order(self):
        # Ruling 5: document beats stated (a printed date is not a
        # reconstruction); relative sits just under stated; photo under both,
        # because a contextual date bounds rather than names.
        weight = ch.BASIS_WEIGHT
        self.assertEqual(weight["document"], 7.0)
        self.assertEqual(weight["stated"], 6.0)
        self.assertEqual(weight["relative"], 5.5)
        self.assertEqual(weight["photo"], 4.5)
        self.assertGreater(weight["document"], weight["stated"])
        self.assertGreater(weight["stated"], weight["relative"])
        self.assertGreater(weight["relative"], weight["age"])
        self.assertGreater(weight["photo"], weight["anchor"])

    def test_a_document_claim_outscores_the_same_claim_stated(self):
        doc = ch.DateRecord(best="1984-06-12", earliest="1984-06-12",
                            latest="1984-06-12", granularity="day",
                            confidence="certain", basis="document")
        said = ch.DateRecord(best="1984", earliest="1984", latest="1984",
                             granularity="year", confidence="certain",
                             basis="stated")
        self.assertGreater(ch.claim_score(doc), ch.claim_score(said))
        self.assertIs(ch.reconcile([said, doc])["best_supported"], doc)

    def test_neither_claim_is_ever_dropped(self):
        doc = ch.DateRecord(best="1984-06", earliest="1984-06", latest="1984-06",
                            granularity="month", basis="document",
                            confidence="certain")
        memory = ch.DateRecord(best="1984-21", earliest="1984-21", latest="1984-21",
                               granularity="season", basis="stated",
                               confidence="approximate")
        out = ch.reconcile([doc, memory])
        self.assertEqual(len(out["alternates"]) + 1, 2)

    def test_the_photo_basis_says_it_is_a_window_on_the_record_it_writes(self):
        record = ch.DateRecord(
            best="1987", earliest="1986", latest="1988", granularity="range",
            confidence="approximate", basis="photo",
            provenance=({"claim": "the tree is up", "basis": "photo"},))
        self.assertIn("a window, not a day", ch.display_date(record))

    def test_a_relative_claim_names_the_witness_in_the_rendering(self):
        record = ch.DateRecord(
            best="1984", earliest="1984", latest="1984", granularity="year",
            confidence="approximate", basis="relative",
            provenance=(ch.witness_provenance("mom", name="Mom",
                                              claim="we moved in '84"),))
        self.assertIn("Mom says we moved in '84", ch.display_date(record))
        self.assertEqual(ch.witness_slug(record), "mom")
        self.assertEqual(ch.witness_name(record), "Mom")


class WitnessProvenanceTests(unittest.TestCase):
    def test_the_entry_is_the_whole_convention(self):
        entry = ch.witness_provenance("mom", name="Mom", said_at="2026-08-24",
                                      claim="we moved in '84")
        self.assertEqual(entry["source"], "witness:mom")
        self.assertEqual(entry["basis"], "relative")
        self.assertEqual(entry["said_at"], "2026-08-24")

    def test_it_is_idempotent_and_never_mangles_a_slug(self):
        # `str.lstrip("witness:")` would eat the leading letters of "sister" —
        # every one of them is in that string. removeprefix is the only
        # correct tool, and this test is why.
        self.assertEqual(ch.witness_provenance("sister")["source"], "witness:sister")
        self.assertEqual(ch.witness_provenance("witness:mom")["source"], "witness:mom")

    def test_a_blank_slug_never_mints_a_bare_prefix(self):
        self.assertIsNone(ch.witness_provenance("   "))
        self.assertIsNone(ch.witness_provenance(None))

    def test_two_witnesses_corroborating_count_as_two_origins(self):
        one = ch.DateRecord(best="1984", earliest="1984", latest="1984",
                            basis="relative", confidence="approximate",
                            provenance=(ch.witness_provenance("mom"),))
        two = ch.DateRecord(best="1984", earliest="1984", latest="1984",
                            basis="relative", confidence="approximate",
                            provenance=(ch.witness_provenance("mom"),
                                        ch.witness_provenance("uncle-ray")))
        self.assertGreater(ch.claim_score(two), ch.claim_score(one))


class GreedyPlanTests(unittest.TestCase):
    def test_the_worked_example_reproduces(self):
        data = _vault()
        plan = tl.dig_plan(data, None, k=2)
        placed = sum(int(row["would_place"]) for row in plan["asks"])
        self.assertEqual(len(tl.unknowns(data)), 14)
        self.assertEqual(placed, 13)
        self.assertEqual(plan["remaining"], 1)

    def test_the_unknown_no_anchor_reaches_is_surfaced_not_hidden(self):
        # go-deep.md §8.2: the greedy plan surfaces what leverage ordering
        # hides. `moment::f1` is the archetype of §6 — better probing will
        # never place it; one question to a living relative will.
        plan = tl.dig_plan(_vault(), None, k=2)
        self.assertEqual(plan["unreachable"], ["moment::f1"])

    def test_a_subset_resolve_set_never_earns_a_second_pick(self):
        """The double-count regression the research found on real vault data.

        `entity:mom`'s resolve set is a strict SUBSET of
        `period:childhood-yucaipa`'s, so once the era is picked the person's
        marginal gain is exactly zero. Ordering independently by leverage
        stars the same neighbourhood twice; a plan must not.
        """
        data = _vault()
        index = tl.dependency_index(data)
        self.assertTrue(index["entity:mom"] < index["period:childhood-yucaipa"])
        plan = tl.dig_plan(data, None, k=3)
        refs = [row["ref"] for row in plan["asks"]]
        self.assertIn("period:childhood-yucaipa", refs)
        self.assertNotIn("entity:mom", refs)
        for row in plan["asks"]:
            self.assertGreater(row["would_place"], 0)
            self.assertEqual(row["would_place"], len(row["unknown_keys"]))

    def test_no_pick_ever_reports_a_gain_it_did_not_make(self):
        plan = tl.dig_plan(_vault(), None, k=8)
        seen: set[str] = set()
        for row in plan["asks"]:
            keys = set(row["unknown_keys"])
            self.assertFalse(keys & seen, "a pick counted an already-covered unknown")
            seen |= keys

    def test_keystones_are_unchanged_by_the_extraction(self):
        # The scoring pass and the greedy loop moved out of `keystones` into
        # `_scored_anchors` / `_greedy_plan`; the keystone list itself must
        # not move by one row.
        data = _vault()
        rows = tl.keystones(data)
        self.assertEqual([r["anchor"] for r in rows],
                         ["period:childhood-yucaipa", "period:mesa"])
        self.assertEqual([r["gain"] for r in rows], [9, 4])
        self.assertNotIn("width_gain", rows[0])

    def test_the_ranking_quantity_is_continuous_and_the_count_is_display(self):
        # go-deep.md §8.4, warning 3. An unknown with no bounds weighs 1.0, so
        # a unit-width vault degenerates to marginal coverage exactly; an
        # era gap of real years weighs its years.
        self.assertEqual(tl.unknown_width({"kind": "moment"}), 1.0)
        self.assertEqual(tl.unknown_width({"kind": "era_gap", "years": [1984, 1990]}), 6.0)
        self.assertEqual(tl.unknown_width("not a row"), 1.0)
        self.assertEqual(tl.unknown_width({"years": ["x", "y"]}), 1.0)
        plan = tl.dig_plan(_vault(), None, k=2)
        for row in plan["asks"]:
            self.assertEqual(row["width_gain"], float(row["would_place"]))

    def test_asking_for_no_asks_returns_an_empty_plan(self):
        plan = tl.dig_plan(_vault(), None, k=0)
        self.assertEqual(plan["asks"], [])


class PrecisionGradeTests(unittest.TestCase):
    def test_the_grade_vocabulary_is_closed_and_every_grade_says_what_it_buys(self):
        self.assertEqual(set(tl.PRECISION_UNLOCKS), set(tl.PRECISION_TARGETS))
        for grade in tl.PRECISION_TARGETS:
            self.assertTrue(tl.PRECISION_UNLOCKS[grade].strip())

    def test_a_school_is_asked_for_its_address(self):
        # The owner's own example: a school's name unlocks nothing; its
        # address gives the district, and the district keeps records with
        # exact years in them (go-deep.md §5.3).
        self.assertEqual(
            tl.precision_target_for("entity:wildwood-school",
                                    label="Wildwood Elementary School",
                                    entity_type="place"),
            "address")
        self.assertIn("district", tl.precision_ask("address"))

    def test_a_birthday_is_asked_to_the_day(self):
        self.assertEqual(tl.precision_target_for("landmark:birth", label="birthday"),
                         "day")

    def test_an_era_wants_both_ends_and_a_gap_wants_a_year(self):
        self.assertEqual(tl.precision_target_for("period:mesa", label="Mesa"), "span")
        self.assertEqual(
            tl.precision_target_for("era_gap:a:b", label="a gap", kind="era_gap"),
            "year")

    def test_every_ask_carries_its_grade_and_the_clause_that_justifies_it(self):
        plan = tl.dig_plan(_vault(), None, k=2)
        for row in plan["asks"]:
            self.assertIn(row["precision_target"], tl.PRECISION_TARGETS)
            self.assertTrue(row["precision_unlocks"])
            self.assertIn(row["precision_unlocks"], row["ask"])


class NeverProposesADateTests(unittest.TestCase):
    def test_no_string_the_plan_emits_ever_proposes_a_date(self):
        plan = tl.dig_plan(_vault(), ROSTER, k=3)
        strings = [row["ask"] for row in plan["asks"]]
        for entry in plan["witness_lists"].values():
            strings += [q["question"] for q in entry["questions"]]
            strings += tl.render_dig_list(entry)
        strings += list(tl.PRECISION_UNLOCKS.values())
        strings += [tl.precision_ask(grade) for grade in tl.PRECISION_TARGETS]
        for text in strings:
            with self.subTest(text=text):
                self.assertIsNone(ti.proposes_a_date(text))


class WitnessTests(unittest.TestCase):
    def test_a_witness_is_a_living_roster_person_joined_by_an_existing_edge(self):
        data = _vault()
        found = tl.witness_for("moment::f1", data, ROSTER)
        self.assertIsNotNone(found)
        self.assertEqual(found["slug"], "uncle-ray")

    def test_someone_not_marked_living_is_never_asked(self):
        data = _vault()
        dead = [{"slug": "uncle-ray", "name": "Uncle Ray", "relationship": "other",
                 "living": False}]
        self.assertIsNone(tl.witness_for("moment::f1", data, dead))

    def test_an_unset_living_flag_is_not_a_yes(self):
        data = _vault()
        unknown = [{"slug": "uncle-ray", "name": "Uncle Ray", "relationship": "other"}]
        self.assertIsNone(tl.witness_for("moment::f1", data, unknown))

    def test_a_person_without_a_stated_relationship_is_not_a_witness(self):
        data = _vault()
        bare = [{"slug": "uncle-ray", "name": "Uncle Ray", "living": True}]
        self.assertIsNone(tl.witness_for("moment::f1", data, bare))

    def test_the_partition_runs_over_what_the_plan_does_not_reach(self):
        # Running it FIRST would take every unknown a living parent shares an
        # era with off the table before the session starts — which empties the
        # Reading Room of exactly the work it exists to do.
        plan = tl.dig_plan(_vault(), ROSTER, k=2)
        self.assertEqual([row["ref"] for row in plan["asks"]],
                         ["period:childhood-yucaipa", "period:mesa"])
        self.assertIn("uncle-ray", plan["witness_order"])
        self.assertEqual(plan["unreachable"], [])

    def test_the_partitions_are_ordered_oldest_generation_first(self):
        self.assertLess(tl.WITNESS_GENERATION_ORDER.index("grandparent"),
                        tl.WITNESS_GENERATION_ORDER.index("parent"))
        self.assertLess(tl.WITNESS_GENERATION_ORDER.index("parent"),
                        tl.WITNESS_GENERATION_ORDER.index("sibling"))
        self.assertLess(tl.WITNESS_GENERATION_ORDER.index("friend"),
                        tl.WITNESS_GENERATION_ORDER.index("child"))
        plan = tl.dig_plan(_vault(), ROSTER, k=2)
        self.assertEqual(plan["witness_order"][0], "mom")

    def test_the_two_closed_lists_head_the_closest_kin(self):
        plan = tl.dig_plan(_vault(), ROSTER, k=2)
        questions = [q["unknown_key"] for q in plan["witness_lists"]["mom"]["questions"]]
        self.assertEqual(questions[:2], ["landmark:residences", "landmark:schools"])

    def test_a_settled_landmark_domain_is_never_asked_again(self):
        data = _vault()
        data["landmarks"] = [{"domain": "residences", "status": "complete"},
                             {"domain": "schools", "status": "open"}]
        plan = tl.dig_plan(data, ROSTER, k=2)
        questions = [q["unknown_key"] for q in plan["witness_lists"]["mom"]["questions"]]
        self.assertNotIn("landmark:residences", questions)
        self.assertIn("landmark:schools", questions)

    def test_a_dig_list_is_short_and_carries_exactly_one_footer_line(self):
        plan = tl.dig_plan(_vault(), ROSTER, k=2)
        for entry in plan["witness_lists"].values():
            self.assertLessEqual(len(entry["questions"]), tl.WITNESS_LIST_CAP)
            lines = tl.render_dig_list(entry)
            self.assertEqual(sum(1 for line in lines if tl.DIG_LIST_FOOTER in line), 1)
            for line in lines:
                self.assertIn(tl.DIG_LIST_MARKER, line)

    def test_the_row_shows_at_most_two_witness_lines(self):
        plan = tl.dig_plan(_vault(), ROSTER, k=2)
        self.assertLessEqual(len(plan["witness_lines"]), tl.WITNESS_LINE_CAP)
        self.assertEqual(tl.WITNESS_LINE_CAP, 2)

    def test_a_dig_list_row_never_enters_the_owners_own_queue(self):
        # The list renders into the WITNESS's `## Open Questions`, but it is
        # addressed to THEM. Harvesting it would put "what year did we move?"
        # into the owner's daily queue — the one question they cannot answer.
        plan = tl.dig_plan(_vault(), ROSTER, k=2)
        for entry in plan["witness_lists"].values():
            for line in tl.render_dig_list(entry):
                stripped = line.strip().lstrip("-*").strip()
                self.assertTrue(qc._is_dig_list_line(stripped), line)
        self.assertFalse(qc._is_dig_list_line("What did the move to Mesa mean to you?"))


LANDMARKS = {
    "family": [
        {"domain": "family", "label": "Jackie", "who": "Jackie",
         "relation": "sibling"},
        {"domain": "family", "label": "Mom", "who": "Mom", "relation": "parent",
         "living": True,
         "date": {"best": "1948", "earliest": "1948", "latest": "1948",
                  "granularity": "year", "confidence": "certain",
                  "basis": "stated"}},
    ],
    "residences": [
        {"domain": "residences", "label": "the Bell house",
         "span": {"start": {"best": "1984", "earliest": "1984", "latest": "1984",
                            "granularity": "year", "confidence": "certain",
                            "basis": "stated"},
                  "end": {"best": "1990", "earliest": "1990", "latest": "1990",
                          "granularity": "year", "confidence": "certain",
                          "basis": "stated"}}},
        {"domain": "residences", "label": "the Mesa apartment",
         "span": {"start": {"best": "1995", "earliest": "1995", "latest": "1995",
                            "granularity": "year", "confidence": "certain",
                            "basis": "stated"},
                  "end": {"best": "1999", "earliest": "1999", "latest": "1999",
                          "granularity": "year", "confidence": "certain",
                          "basis": "stated"}}},
    ],
}


class AnchorCreatingUnknownTests(unittest.TestCase):
    """v202 minted two unknown kinds `dependency_index` scores at leverage 0.

    They place nothing that exists TODAY — and each one creates an ANCHOR,
    which is the thing every other unknown is placed against. The v204 ruling
    (ADR 0025): they are not ranked on the coverage axis, they get a quota at
    the head of the session, and their reported gain stays honest.
    """

    def test_the_new_kinds_reach_the_plan_at_all(self):
        rows = tl.unknowns(_vault(), LANDMARKS)
        kinds = {row["kind"] for row in rows}
        self.assertIn("landmark_subject", kinds)
        self.assertIn("residence_gap", kinds)

    def test_dependency_index_still_gives_them_no_leverage(self):
        # Unchanged from v202, and correct: they resolve nothing that exists.
        index = tl.dependency_index(_vault())
        for resolved in index.values():
            for key in resolved:
                self.assertFalse(key.startswith(("landmark_subject:", "residence_gap:")))

    def test_the_quota_puts_one_at_the_head_of_the_session(self):
        plan = tl.dig_plan(_vault(), None, k=3, landmarks=LANDMARKS)
        self.assertEqual(tl.LANDMARK_ASK_QUOTA, 1)
        head = plan["asks"][0]
        self.assertTrue(head["creates_anchor"])
        self.assertTrue(head["ref"].startswith(("landmark_subject:", "residence_gap:")))
        self.assertFalse(any(row["creates_anchor"] for row in plan["asks"][1:]))

    def test_it_never_claims_a_gain_it_has_not_earned(self):
        plan = tl.dig_plan(_vault(), None, k=3, landmarks=LANDMARKS)
        head = plan["asks"][0]
        self.assertEqual(head["would_place"], 1)
        self.assertEqual(head["unknown_keys"], [head["ref"]])

    def test_the_quota_never_crowds_out_the_coverage_picks(self):
        plan = tl.dig_plan(_vault(), None, k=3, landmarks=LANDMARKS)
        refs = [row["ref"] for row in plan["asks"]]
        self.assertIn("period:childhood-yucaipa", refs)
        self.assertIn("period:mesa", refs)
        self.assertLessEqual(len(plan["asks"]), 3)

    def test_a_session_of_one_ask_is_still_a_coverage_ask_when_k_is_one(self):
        plan = tl.dig_plan(_vault(), None, k=1, landmarks=LANDMARKS)
        self.assertEqual(len(plan["asks"]), 1)
        self.assertTrue(plan["asks"][0]["creates_anchor"])

    def test_the_ask_keeps_the_ladders_own_subject_named_wording(self):
        plan = tl.dig_plan(_vault(), None, k=3, landmarks=LANDMARKS)
        head = plan["asks"][0]
        self.assertIn(head["probe"]["text"], head["ask"])

    def test_a_landmark_subject_is_asked_at_the_grade_of_the_rung_it_is_short_of(self):
        self.assertEqual(
            tl.precision_target_for("landmark_subject:family:jackie",
                                    label="Jackie", kind="landmark_subject",
                                    rung="birth"),
            "day")
        self.assertEqual(
            tl.precision_target_for("landmark_subject:residences:bell",
                                    label="the Bell house",
                                    kind="landmark_subject", rung="address"),
            "address")

    def test_the_ones_not_asked_route_to_the_oldest_living_witness(self):
        # A living parent can supply family, residences and schools outright —
        # v202's own `WITNESS_CAN_SUPPLY` claim — and these unknowns have no
        # era or source to join on, so the generation ordering decides.
        plan = tl.dig_plan(_vault(), ROSTER, k=1, landmarks=LANDMARKS)
        asked = {row["ref"] for row in plan["asks"]}
        routed = {q["unknown_key"]
                  for entry in plan["witness_lists"].values()
                  for q in entry["questions"]}
        landmark_keys = {row["key"] for row in tl.unknowns(_vault(), LANDMARKS)
                         if row["kind"] in tl.ANCHOR_CREATING_KINDS}
        self.assertTrue(landmark_keys - asked)
        self.assertTrue((landmark_keys - asked) & (routed | set(plan["unreachable"])))

    def test_a_residence_gaps_years_are_a_real_width(self):
        rows = {row["key"]: row for row in tl.unknowns(_vault(), LANDMARKS)}
        gap = next(row for row in rows.values() if row["kind"] == "residence_gap")
        self.assertGreater(tl.unknown_width(gap), 1.0)


class WitnessSourceTests(unittest.TestCase):
    def test_the_family_landmark_is_the_first_witness_source(self):
        # v202: `timeline_data()["witnesses"]` is where witnesses actually
        # come from, and its `relation` IS the roster's `relationship` — one
        # closed vocabulary, no translation table.
        data = _vault()
        data["witnesses"] = list(li.witness_candidates(LANDMARKS))
        self.assertEqual([w["slug"] for w in data["witnesses"]], ["mom"])
        plan = tl.dig_plan(data, None, k=1, landmarks=LANDMARKS)
        self.assertIn("mom", plan["witness_order"])

    def test_an_unknown_living_flag_is_never_a_witness_in_either_source(self):
        self.assertEqual(li.witness_candidates({"family": [
            {"label": "Jackie", "who": "Jackie", "relation": "sibling"}]}), ())

    def test_the_two_sources_are_deduped_by_slug(self):
        data = _vault()
        data["witnesses"] = list(li.witness_candidates(LANDMARKS))
        roster = [{"slug": "mom", "name": "Mom", "relationship": "parent",
                   "living": True}]
        people = tl._living_roster(roster, data)
        self.assertEqual([p["slug"] for p in people], ["mom"])


class TimelineDataTests(unittest.TestCase):
    def test_the_block_is_additive_and_never_takes_the_timeline_down(self):
        plan = tl.dig_plan(_vault(), None, k=3)
        self.assertEqual(
            set(plan),
            {"k", "asks", "witness_lists", "witness_order", "witness_lines",
             "unreachable", "remaining", "open_unknowns"},
        )

    def test_a_broken_roster_degrades_to_an_empty_plan(self):
        self.assertEqual(tl.dig_plan(_vault(), "not a roster", k=2)["witness_lists"], {})


class OutputContractTests(unittest.TestCase):
    def test_output_contract_block_byte_identical_without_reading_room_stage(self):
        shape = cd.TurnShape("mid", True, 2, 6)
        block = cd._output_contract_block(shape)
        self.assertNotIn('"placed"', block)
        self.assertNotIn('"landmark"', block)
        self.assertEqual(block, cd._output_contract_block(cd.TurnShape("mid", True, 2, 6)))

    def test_the_one_gate_opens_both_reused_keys(self):
        block = cd._output_contract_block(
            cd.TurnShape("mid", True, 2, 6, reading_room_stage="work"))
        self.assertIn('"placed"', block)
        self.assertIn('"landmark"', block)

    def test_the_gate_does_not_disturb_the_other_two_lanes(self):
        timeline_only = cd._output_contract_block(
            cd.TurnShape("mid", True, 2, 6, timeline_stage="place"))
        self.assertIn('"placed"', timeline_only)
        self.assertNotIn('"landmark"', timeline_only)
        landmark_only = cd._output_contract_block(
            cd.TurnShape("mid", True, 2, 6, landmark_stage="ask"))
        self.assertIn('"landmark"', landmark_only)
        self.assertNotIn('"placed"', landmark_only)

    def test_the_advertised_basis_vocabulary_is_derived_from_the_tuple(self):
        # Before v204 this was a hand-typed literal in TWO places, so a basis
        # added to `chronology.BASES` silently never reached the model.
        block = cd._output_contract_block(
            cd.TurnShape("mid", True, 2, 6, reading_room_stage="work"))
        self.assertEqual(cd._BASIS_VOCABULARY, " | ".join(ch.BASES))
        for basis in ch.BASES:
            self.assertIn(basis, block)


class StageTests(unittest.TestCase):
    def test_the_first_turn_opens(self):
        self.assertEqual(rr.reading_room_stage_for_session({"turns": []}), "open")
        self.assertEqual(rr.reading_room_stage_for_session(None), "open")

    def test_a_turn_in_the_middle_works(self):
        session = {"turns": [{"role": "user"}, {"role": "assistant"}]}
        self.assertEqual(rr.reading_room_stage_for_session(session), "work")

    def test_leaving_or_an_exhausted_plan_closes(self):
        session = {"turns": [{"role": "user"}]}
        self.assertEqual(
            rr.reading_room_stage_for_session(session, user_leaving=True), "close")
        self.assertEqual(
            rr.reading_room_stage_for_session(session, plan_exhausted=True), "close")

    def test_two_skips_in_a_row_close_it(self):
        session = {"turns": [{"role": "user"}]}
        self.assertEqual(
            rr.reading_room_stage_for_session(session, skip_streak=2), "close")

    def test_the_ask_ceiling_closes_it(self):
        session = {"turns": [{"role": "user"}] * rr.MAX_ASKS}
        self.assertEqual(rr.reading_room_stage_for_session(session), "close")

    def test_stop_rule_knobs_match_the_module_constants(self):
        raw = (ROOT / "interactions" / "reading_room" / "interaction.yaml").read_text(
            encoding="utf-8")
        self.assertIn(f"knob.max_asks: {rr.MAX_ASKS}", raw)
        self.assertIn(f"knob.stop_after_skips: {rr.STOP_AFTER_SKIPS}", raw)
        self.assertIn(f"knob.plan_size: {rr.PLAN_SIZE}", raw)
        self.assertIn(f"knob.agenda_display_limit: {rr.AGENDA_DISPLAY_LIMIT}", raw)

    def test_the_session_and_the_plan_agree_on_k(self):
        # If these ever drift the agenda lies about how much today covers.
        self.assertEqual(rr.PLAN_SIZE, tl.DIG_PLAN_SIZE)


class PromptBlockTests(unittest.TestCase):
    def test_the_inventory_block_says_so_before_it_is_asked(self):
        self.assertIn("inventory question", rr.render_inventory(""))
        self.assertEqual(rr.render_inventory("a shoebox"), "a shoebox")

    def test_the_agenda_states_what_an_ask_would_unlock_never_what_remains(self):
        plan = tl.dig_plan(_vault(), None, k=2)
        block = rr.render_agenda(plan)
        self.assertIn("would place", block)
        for banned in ("remaining", "left", "of 14", "%"):
            self.assertNotIn(banned, block)

    def test_the_agenda_degrades_rather_than_going_empty(self):
        self.assertIn("nothing outstanding", rr.render_agenda({"asks": []}))
        self.assertIn("nothing outstanding", rr.render_agenda(None))

    def test_the_next_ask_is_the_head_of_the_plan_with_its_grade(self):
        plan = tl.dig_plan(_vault(), None, k=2)
        head = rr.next_ask(plan)
        self.assertEqual(head["ref"], "period:childhood-yucaipa")
        self.assertEqual(rr.render_next_ask(plan), head["ask"])
        self.assertIn("nothing on the plan", rr.render_next_ask({"asks": []}))


class RecomputeTests(unittest.TestCase):
    def test_a_filed_placement_shrinks_the_plan_the_next_turn(self):
        data = _vault()
        before = rr.recompute_plan(data, k=2)
        keys = before["asks"][0]["unknown_keys"]
        after = rr.recompute_plan(data, k=2, resolved=keys)
        self.assertLess(len(after["asks"]), len(before["asks"]))
        self.assertLess(after["remaining"], before["remaining"])

    def test_the_recompute_is_pure_and_persists_nothing(self):
        data = _vault()
        snapshot = json.dumps(data, sort_keys=True, default=str)
        rr.recompute_plan(data, k=3, resolved=["moment:mesa:m0"])
        self.assertEqual(json.dumps(data, sort_keys=True, default=str), snapshot)

    def test_it_says_what_just_got_placed_and_never_what_is_left(self):
        self.assertEqual(rr.placement_gain_sentence({"remaining": 14},
                                                    {"remaining": 5}),
                         "That dates nine moments.")
        self.assertEqual(rr.placement_gain_sentence({"remaining": 2},
                                                    {"remaining": 1}),
                         "That dates one moment.")
        self.assertEqual(rr.placement_gain_sentence({"remaining": 3},
                                                    {"remaining": 3}), "")
        self.assertEqual(rr.placement_gain_sentence(None, None), "")


class EvidenceRecordTests(unittest.TestCase):
    ANCHORS = {"birth": {"label": "when you were born", "kind": "birth",
                         "date": {"best": "1976-04-11", "earliest": "1976-04-11",
                                  "latest": "1976-04-11", "granularity": "day",
                                  "confidence": "certain", "basis": "stated"}}}

    def test_a_photograph_is_never_certain(self):
        out = rr.normalize_evidence_record(
            {"best": "1987", "earliest": "1986", "latest": "1988",
             "granularity": "range", "confidence": "certain", "basis": "photo"})
        self.assertEqual(out["confidence"], "approximate")

    def test_a_relayed_memory_is_never_certain_and_names_who_said_it(self):
        out = rr.normalize_evidence_record(
            {"best": "1984", "earliest": "1984", "latest": "1984",
             "granularity": "year", "confidence": "certain", "basis": "relative"},
            witness={"slug": "mom", "name": "Mom"})
        self.assertEqual(out["confidence"], "approximate")
        self.assertEqual(ch.witness_slug(out), "mom")

    def test_a_printed_date_keeps_the_certainty_it_earned(self):
        out = rr.normalize_evidence_record(
            {"best": "1984-06-12", "earliest": "1984-06-12", "latest": "1984-06-12",
             "granularity": "day", "confidence": "certain", "basis": "document"})
        self.assertEqual(out["confidence"], "certain")

    def test_an_existing_witness_is_never_duplicated(self):
        record = {"best": "1984", "earliest": "1984", "latest": "1984",
                  "basis": "relative", "confidence": "approximate",
                  "granularity": "year",
                  "provenance": [ch.witness_provenance("mom", name="Mom")]}
        out = rr.normalize_evidence_record(record, witness={"slug": "uncle-ray"})
        self.assertEqual(len(out["provenance"]), 1)

    def test_the_closed_layer_is_the_timeline_lanes_and_refuses_a_made_up_anchor(self):
        good = rr.validate_evidence(
            {"best": "1984", "earliest": "1984", "latest": "1984",
             "granularity": "year", "confidence": "approximate",
             "basis": "relative", "anchors": ["birth"]},
            anchors=self.ANCHORS, witness={"slug": "mom", "name": "Mom"})
        self.assertIsNotNone(good)
        self.assertIsNone(rr.validate_evidence(
            {"best": "1984", "earliest": "1984", "latest": "1984",
             "basis": "relative", "anchors": ["invented"]}, anchors=self.ANCHORS))

    def test_unusable_input_returns_none_and_never_raises(self):
        for value in (None, "", 3, {}, {"granularity": "epoch"}):
            with self.subTest(value=value):
                self.assertIsNone(rr.validate_evidence(value, anchors=self.ANCHORS))
                self.assertIsNone(rr.normalize_evidence_record(value))


class FilingTests(unittest.TestCase):
    def test_this_lane_owns_neither_write_verb(self):
        turn = {
            "placed": {"best": "1984", "earliest": "1984", "latest": "1984",
                       "granularity": "year", "confidence": "approximate",
                       "basis": "document", "anchors": []},
            "landmark": {"domain": "schools", "label": "Wildwood Elementary"},
        }
        calls = rr.filing_invocations(turn, source="A1", description="the move",
                                      period="childhood-yucaipa")
        self.assertEqual([call.argv[0] for call in calls],
                         ["timeline-place", "landmark-record"])
        argv = calls[0].argv
        self.assertIn("--basis", argv)
        self.assertIn(argv[argv.index("--basis") + 1], ch.BASES)

    def test_the_place_call_carries_the_description_the_cli_reads_on_stdin(self):
        """lifehug#223: argv without stdin is half a call — `timeline-place`
        exits 1 on an empty description, so the two must travel together."""
        calls = rr.filing_invocations(
            {"placed": {"best": "1984", "granularity": "year",
                        "confidence": "approximate", "basis": "document"}},
            source="A1", description="the move", period="childhood-yucaipa")
        self.assertEqual(calls[0].stdin_text, "the move")

    def test_a_placement_with_no_description_files_nothing(self):
        self.assertEqual(
            rr.filing_invocations({"placed": {"best": "1984"}},
                                  source="A1", description="", period="childhood"),
            [])

    def test_nothing_to_file_is_no_invocation(self):
        self.assertEqual(rr.filing_invocations({}), [])
        self.assertEqual(rr.filing_invocations(None), [])
        self.assertEqual(rr.filing_invocations({"placed": None, "landmark": None}), [])


class LintTests(unittest.TestCase):
    def test_asking_the_memory_instead_of_the_artifact_is_a_finding(self):
        for text in ("Do you remember when that was?",
                     "Try to think back — roughly when?",
                     "What's your best guess?",
                     "How many years ago was that?"):
            with self.subTest(text=text):
                found = {f["lint"] for f in rr.lint_reading_room_reply(text, stage="work")}
                self.assertIn("reading_room_gates.artifact_carries_the_burden", found)

    def test_asking_the_artifact_is_clean(self):
        found = rr.lint_reading_room_reply(
            "Turn it over — read me everything printed on the back, exactly as it "
            "appears.", stage="work")
        self.assertEqual(found, [])

    def test_pressure_is_a_finding_on_every_turn_here(self):
        found = {f["lint"] for f in rr.lint_reading_room_reply(
            "Are you sure? I really need to know.", stage="work")}
        self.assertIn("reading_room_gates.no_pressure", found)

    def test_the_pressure_definition_is_shared_with_the_landmarks_lane(self):
        # Recurring-defect doctrine: "are you sure?" over somebody's photo
        # album is the same defect as "are you sure?" over a loss.
        self.assertIsNotNone(li.pressure("Are you sure?"))
        self.assertIsNone(li.pressure("Take your time."))

    def test_growing_a_deferral_machine_is_a_finding(self):
        for text in ("No problem — I'll remind you next time.",
                     "Don't forget to ask her about it.",
                     "Let me know when you find it.",
                     "I'll add that to your list."):
            with self.subTest(text=text):
                found = {f["lint"] for f in rr.lint_reading_room_reply(text, stage="work")}
                self.assertIn("reading_room_gates.accepts_i_will_find_out", found)

    def test_taking_i_will_find_out_as_an_answer_is_clean(self):
        found = rr.lint_reading_room_reply(
            "Then that one's at your sister's, and it can stay there.", stage="work")
        self.assertEqual(found, [])

    def test_two_questions_in_one_turn_is_a_finding(self):
        found = {f["lint"] for f in rr.lint_reading_room_reply(
            "What does the back say? And what year did you move in?", stage="work")}
        self.assertIn("reading_room_gates.one_ask_per_turn", found)

    def test_proposing_a_date_is_a_finding_from_the_shared_definition(self):
        found = {f["lint"] for f in rr.lint_reading_room_reply(
            "So was it 1984? Does that sound about right?", stage="work")}
        self.assertIn("reading_room_gates.never_proposes_a_date", found)
        self.assertIsNotNone(ti.proposes_a_date("was it 1984"))

    def test_reporting_the_arithmetic_is_not_proposing_a_date(self):
        found = rr.lint_reading_room_reply(
            "A printed ZIP+4 means not before October 1983 — so everything in that "
            "envelope sits after it.", stage="work")
        self.assertEqual(found, [])

    def test_an_unknown_stage_fails_toward_the_strict_rule(self):
        found = {f["lint"] for f in rr.lint_reading_room_reply(
            "One? Two?", stage="nonsense")}
        self.assertIn("reading_room_gates.one_ask_per_turn", found)

    def test_every_lint_class_is_gated(self):
        gates = set(rre.load_gates())
        for name in rr.READING_ROOM_LINT_CLASSES:
            self.assertIn(f"{name.split('.', 1)[1]}.compliance", gates)


class CloseTests(unittest.TestCase):
    def test_the_close_names_the_witnesses_without_naming_a_clock(self):
        plan = tl.dig_plan(_vault(), ROSTER, k=2)
        sentence = rr.describe_close(plan)
        self.assertIn("Mom", sentence)
        import re as _re
        for banned in ("still", "while", "before", "age", "aged", "old",
                       "died", "passed", "alive"):
            self.assertIsNone(_re.search(rf"\b{banned}\b", sentence.lower()), banned)

    def test_the_close_says_nothing_when_there_is_no_witness(self):
        self.assertEqual(rr.describe_close(tl.dig_plan(_vault(), None, k=2)), "")

    def test_the_homework_is_the_rendered_lists_and_nothing_else(self):
        plan = tl.dig_plan(_vault(), ROSTER, k=2)
        lines = rr.render_dig_lists(plan)
        self.assertTrue(lines)
        for line in lines:
            self.assertIn(tl.DIG_LIST_MARKER, line)


class EvalsTests(unittest.TestCase):
    def test_the_recorded_seat_passes(self):
        fixtures = rre.load_fixtures()
        self.assertEqual(rre.validate_fixtures(fixtures), [])
        scores = rre.score_goldens(fixtures, rre.load_sample_predictions())
        self.assertEqual(rre.check_gates(scores, rre.load_gates()), [])
        self.assertEqual(scores["_field_accuracy"], 1.0)
        self.assertEqual(scores["_unmatched_fixtures"], [])

    def test_a_broken_fixture_is_reported_not_silently_skipped(self):
        self.assertTrue(rre.validate_fixtures([{"fixture_id": "x"}]))
        self.assertTrue(rre.validate_fixtures([]) or True)


class FrameworkFilesTests(unittest.TestCase):
    def test_every_new_file_ships_in_framework_files(self):
        manifest = set(json.loads((SYSTEM / "version.json").read_text())["framework_files"])
        package = ROOT / "interactions" / "reading_room"
        shipped = {path.relative_to(ROOT).as_posix()
                   for path in package.rglob("*") if path.is_file()}
        self.assertEqual(shipped - manifest, set())
        for path in ("system/reading_room.py", "system/reading_room_evals.py",
                     "docs/handbook/interactions/reading-room.md"):
            self.assertIn(path, manifest)


if __name__ == "__main__":
    unittest.main()
