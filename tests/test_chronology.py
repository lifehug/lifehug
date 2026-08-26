"""v195 / ADR 0024 — the date record and its arithmetic.

Every rule in `system/chronology.py` gets a test: the EDTF table round-trips,
the human forms normalize, the arithmetic is the arithmetic the owner ruled
("the system does the arithmetic"), and `reconcile` never drops a claim.

Synthetic data only; NEVER references ~/Workspace/dave.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "system"))

import chronology as ch  # noqa: E402


CANONICAL = [
    # (edtf, granularity, confidence, earliest, latest)
    ("1984", "year", "certain", "1984", "1984"),
    ("1984~", "year", "approximate", "1984", "1984"),
    ("1984?", "year", "conjectural", "1984", "1984"),
    ("1984%", "year", "conjectural", "1984", "1984"),
    ("198X", "era", "approximate", "1980", "1989"),
    ("1998-06", "month", "certain", "1998-06", "1998-06"),
    ("1998-06-12", "day", "certain", "1998-06-12", "1998-06-12"),
    ("2001-21", "season", "certain", "2001-03", "2001-05"),
    ("1984/1990", "range", "certain", "1984", "1990"),
    ("1984/..", "range", "inferred", "1984", None),
    ("../1984", "range", "inferred", None, "1984"),
]


class VocabularyTests(unittest.TestCase):
    def test_the_three_vocabularies_are_closed_and_ordered(self):
        self.assertEqual(ch.GRANULARITIES,
                         ("day", "month", "season", "year", "range", "era"))
        self.assertEqual(ch.CONFIDENCES,
                         ("certain", "approximate", "inferred", "conjectural"))
        self.assertEqual(ch.BASES, ("stated", "age", "anchor", "order",
                                    "public_event", "connector",
                                    "document", "photo", "relative"))
        # v204 (the Reading Room): the three evidence bases are the tail of
        # BASES and their own tuple, and every one of them is weighted.
        self.assertEqual(ch.EVIDENCE_BASES, ("document", "photo", "relative"))
        self.assertEqual(ch.BASES[-3:], ch.EVIDENCE_BASES)
        self.assertEqual(set(ch.BASIS_WEIGHT), set(ch.BASES))

    def test_off_vocabulary_values_are_rejected_at_construction(self):
        for kwargs in ({"granularity": "epoch"}, {"confidence": "sure"},
                       {"basis": "vibes"}):
            with self.subTest(**kwargs):
                with self.assertRaises(ch.ChronologyError):
                    ch.DateRecord(best="1984", earliest="1984", latest="1984", **kwargs)

    def test_a_record_with_no_bound_at_all_is_rejected(self):
        with self.assertRaises(ch.ChronologyError):
            ch.DateRecord()


class EdtfRoundTripTests(unittest.TestCase):
    def test_every_canonical_form_round_trips(self):
        for text, granularity, confidence, earliest, latest in CANONICAL:
            with self.subTest(edtf=text):
                record = ch.parse_edtf(text)
                self.assertIsNotNone(record)
                self.assertEqual(ch.to_edtf(record), text)
                self.assertEqual(record.granularity, granularity)
                self.assertEqual(record.confidence, confidence)
                self.assertEqual(record.earliest, earliest)
                self.assertEqual(record.latest, latest)

    def test_2001_21_is_spring_not_a_compact_range(self):
        # ISO 8601-2 sub-year codes 21..24 are the seasons; a 2001-2021
        # INTERVAL is written `2001/2021`. (Deviation 1 in the contract.)
        season = ch.parse_edtf("2001-21")
        self.assertEqual(season.granularity, "season")
        self.assertEqual(ch.display_date(season), "spring 2001")
        interval = ch.parse_edtf("2001/2021")
        self.assertEqual((interval.earliest, interval.latest), ("2001", "2021"))

    def test_human_forms_normalize_onto_canonical_edtf(self):
        cases = {
            "2001–2021": "2001/2021",
            "2001-2021": "2001/2021",
            "spring 1998": "1998-21",
            "1998 winter": "1998-24",
            "1970s": "197X",
            "the 1970s": "197X",
            "about 1984": "1984~",
            "circa 1984": "1984~",
            "before 1984": "../1984",
            "after 1984": "1984/..",
        }
        for text, expected in cases.items():
            with self.subTest(text=text):
                self.assertEqual(ch.to_edtf(ch.parse_edtf(text)), expected)

    def test_unparseable_text_is_none_and_never_raises(self):
        for text in ("", "   ", "sometime", "when we lived in Mesa", None, 5,
                     "1998-13", "199", "//", "../.."):
            with self.subTest(text=text):
                self.assertIsNone(ch.parse_edtf(text))

    def test_dict_round_trip_and_tolerant_from_dict(self):
        record = ch.parse_edtf("1998-06")
        self.assertEqual(ch.from_dict(record.to_dict()), record)
        self.assertIsNone(ch.from_dict({"granularity": "nope"}))
        self.assertIsNone(ch.from_dict(["1984"]))
        self.assertEqual(ch.from_dict("1984"), ch.parse_edtf("1984"))


class DisplayTests(unittest.TestCase):
    def test_each_granularity_renders_the_way_a_person_would_say_it(self):
        cases = {
            "1984": "1984",
            "1984~": "around 1984",
            "198X": "sometime in the 1980s",
            "1998-06": "June 1998",
            "1998-06-12": "12 June 1998",
            "2001-21": "spring 2001",
            "1984/1990": "1984–1990",
            "1984/..": "after 1984",
            "../1984": "before 1984",
        }
        for text, expected in cases.items():
            with self.subTest(text=text):
                self.assertEqual(ch.display_date(ch.parse_edtf(text)), expected)

    def test_the_basis_clause_quotes_the_person_back(self):
        record = ch.from_age("1979", "about 5")
        self.assertEqual(ch.display_date(record),
                         "around 1984 — you said you were about 5")
        self.assertEqual(ch.display_date(record, with_basis=False), "around 1984")

    def test_a_record_with_no_claim_has_no_basis_clause(self):
        self.assertEqual(ch.display_date(ch.parse_edtf("1984")), "1984")

    def test_display_of_nothing_is_empty_never_an_error(self):
        self.assertEqual(ch.display_date(None), "")
        self.assertEqual(ch.display_date("not a date"), "")


class AgeArithmeticTests(unittest.TestCase):
    def test_the_owners_own_example(self):
        # birthday + "about 5" -> ~1984, basis age (owner ruling 1).
        record = ch.from_age("1979", "about 5")
        self.assertEqual(record.best, "1984~")
        self.assertEqual(record.basis, "age")
        self.assertEqual(record.confidence, "approximate")
        self.assertEqual(record.anchors, ("birth",))
        self.assertEqual((record.earliest, record.latest), ("1983", "1986"))

    def test_a_bare_age_is_inferred_not_approximate_and_keeps_the_tight_window(self):
        record = ch.from_age("1979", "5")
        self.assertEqual((record.earliest, record.latest), ("1984", "1985"))
        self.assertEqual(record.confidence, "inferred")

    def test_two_ages_take_the_union_before_the_hedge(self):
        self.assertEqual(
            (ch.from_age("1979", "5 or 6").earliest, ch.from_age("1979", "5 or 6").latest),
            ("1984", "1986"),
        )
        hedged = ch.from_age("1979", "about 5 or 6")
        self.assertEqual((hedged.earliest, hedged.latest), ("1983", "1987"))

    def test_number_words_and_hedge_vocabulary(self):
        self.assertEqual(ch.parse_age("about five"), (5, 5, True))
        self.assertEqual(ch.parse_age("twelve"), (12, 12, False))
        self.assertEqual(ch.parse_age("roughly 12"), (12, 12, True))
        self.assertEqual(ch.parse_age("12"), (12, 12, False))
        self.assertIsNone(ch.parse_age("no idea"))
        self.assertIsNone(ch.parse_age(None))

    def test_no_birthday_or_no_age_is_none(self):
        self.assertIsNone(ch.from_age(None, "about 5"))
        self.assertIsNone(ch.from_age("1979", "no idea"))
        self.assertIsNone(ch.from_age("not a date", "5"))


class AnchorArithmeticTests(unittest.TestCase):
    def setUp(self):
        self.mesa = ch.parse_edtf("1984/1990")

    def test_before_is_a_terminus_ante_quem(self):
        record = ch.from_anchor(self.mesa, "before", key="mesa")
        self.assertEqual(record.best, "../1984")
        self.assertIsNone(record.earliest)
        self.assertEqual(record.latest, "1984")
        self.assertEqual(record.basis, "anchor")
        self.assertEqual(record.anchors, ("mesa",))

    def test_after_is_a_terminus_post_quem(self):
        record = ch.from_anchor(self.mesa, "after", key="mesa")
        self.assertEqual(record.best, "1990/..")
        self.assertEqual(record.earliest, "1990")
        self.assertIsNone(record.latest)

    def test_during_takes_the_anchors_own_span_and_never_claims_certainty(self):
        record = ch.from_anchor(self.mesa, "during", key="mesa")
        self.assertEqual((record.earliest, record.latest), ("1984", "1990"))
        self.assertEqual(record.confidence, "inferred")

    def test_an_unknown_relation_or_missing_anchor_is_none(self):
        self.assertIsNone(ch.from_anchor(self.mesa, "roughly-when"))
        self.assertIsNone(ch.from_anchor(None, "before"))
        # an anchor with no earliest bound cannot yield a terminus ante quem
        self.assertIsNone(ch.from_anchor(ch.parse_edtf("../1984"), "before"))
        self.assertIsNone(ch.from_anchor(ch.parse_edtf("1984/.."), "after"))


class IntersectTests(unittest.TestCase):
    def test_two_open_bounds_become_one_closed_interval(self):
        record = ch.intersect(ch.parse_edtf("1984/.."), ch.parse_edtf("../1990"))
        self.assertEqual((record.earliest, record.latest), ("1984", "1990"))
        self.assertEqual(record.best, "1984/1990")

    def test_the_tightest_bound_wins_on_each_side(self):
        record = ch.intersect(ch.parse_edtf("1980/1995"), ch.parse_edtf("1984/1990"))
        self.assertEqual((record.earliest, record.latest), ("1984", "1990"))

    def test_disjoint_inputs_are_none_because_that_is_reconciles_job(self):
        self.assertIsNone(ch.intersect(ch.parse_edtf("1990/.."), ch.parse_edtf("../1984")))

    def test_combining_never_claims_more_confidence_than_inferred(self):
        record = ch.intersect(ch.parse_edtf("1984"), ch.parse_edtf("1984"))
        self.assertEqual(record.confidence, "inferred")

    def test_one_input_passes_through_and_zero_inputs_are_none(self):
        only = ch.parse_edtf("1984")
        self.assertEqual(ch.intersect(only), only)
        self.assertIsNone(ch.intersect())
        self.assertIsNone(ch.intersect(None, "nonsense"))

    def test_anchors_and_provenance_survive_the_combination(self):
        left = ch.from_age("1979", "about 5")
        right = ch.from_anchor(ch.parse_edtf("1980/1990"), "during", key="mesa")
        record = ch.intersect(left, right)
        self.assertIn("birth", record.anchors)
        self.assertIn("mesa", record.anchors)
        self.assertTrue(record.provenance)


class ElapsedWideningTests(unittest.TestCase):
    def test_a_stated_certain_date_never_decays(self):
        record = ch.parse_edtf("1984")
        self.assertEqual(ch.widen_for_elapsed(record, as_of=2044), record)

    def test_half_a_year_per_decade_rounded_up(self):
        widened = ch.widen_for_elapsed(ch.parse_edtf("1984~"), as_of=2024)
        # 40 years elapsed -> 40/10 * 0.5 = 2.0 -> two years each side
        self.assertEqual((widened.earliest, widened.latest), ("1982", "1986"))

    def test_the_granularity_coarsens_one_rung_when_the_widening_bites(self):
        widened = ch.widen_for_elapsed(ch.parse_edtf("1998-06~"), as_of=2024)
        self.assertEqual(widened.granularity, "season")

    def test_confidence_drops_at_most_one_rung_and_never_past_inferred(self):
        self.assertEqual(
            ch.widen_for_elapsed(ch.parse_edtf("1984~"), as_of=2024).confidence, "inferred")
        record = ch.DateRecord(best="1984", earliest="1984", latest="1984",
                               confidence="conjectural", basis="order")
        self.assertEqual(ch.widen_for_elapsed(record, as_of=2024).confidence, "conjectural")

    def test_no_elapsed_time_leaves_the_record_alone(self):
        record = ch.parse_edtf("1984~")
        self.assertEqual(ch.widen_for_elapsed(record, as_of=1984), record)
        self.assertIsNone(ch.widen_for_elapsed(None, as_of=2024))


class ReconcileTests(unittest.TestCase):
    def setUp(self):
        self.stated = ch.DateRecord(best="1985", earliest="1985", latest="1985",
                                    basis="stated", confidence="certain")
        self.connector = ch.DateRecord(best="1987", earliest="1987", latest="1987",
                                       basis="connector", confidence="certain")
        self.order = ch.DateRecord(best="1990", earliest="1990", latest="1990",
                                   basis="order", confidence="inferred")

    def test_a_stated_claim_outranks_institutional_evidence(self):
        result = ch.reconcile([self.connector, self.stated])
        self.assertEqual(result["best_supported"], self.stated)
        self.assertEqual(result["alternates"], [self.connector, ])

    def test_never_drops_a_claim(self):
        claims = [self.connector, self.stated, self.order]
        result = ch.reconcile(claims)
        self.assertEqual(1 + len(result["alternates"]), len(claims))
        self.assertEqual(
            sorted(ch.to_edtf(r) for r in [result["best_supported"]] + result["alternates"]),
            sorted(ch.to_edtf(r) for r in claims),
        )

    def test_consilience_lifts_a_corroborated_claim(self):
        corroborated = ch.DateRecord(
            best="1987", earliest="1987", latest="1987", basis="connector",
            confidence="certain",
            provenance=({"source": "a"}, {"source": "b"}, {"source": "c"}),
        )
        self.assertGreater(ch.claim_score(corroborated), ch.claim_score(self.connector))

    def test_ties_break_deterministically(self):
        twin = ch.DateRecord(best="1983", earliest="1983", latest="1983",
                             basis="stated", confidence="certain")
        first = ch.reconcile([self.stated, twin])
        second = ch.reconcile([twin, self.stated])
        self.assertEqual(ch.to_edtf(first["best_supported"]),
                         ch.to_edtf(second["best_supported"]))
        self.assertEqual(ch.to_edtf(first["best_supported"]), "1983")

    def test_empty_and_unusable_inputs(self):
        empty = {"best_supported": None, "alternates": [], "conflict": 0.0}
        self.assertEqual(ch.reconcile([]), empty)
        self.assertEqual(ch.reconcile(None), empty)
        self.assertIsNone(ch.reconcile(["nonsense"])["best_supported"])


class ClaimTests(unittest.TestCase):
    def test_possible_date_claim_keeps_only_the_four_keys(self):
        claim = ch.possible_date_claim({
            "stated": " 1984 ", "age": "about 5", "anchor_ref": "the move to Mesa",
            "relation": "AFTER", "extra": "ignored",
        })
        self.assertEqual(claim, {"stated": "1984", "age": "about 5",
                                 "anchor_ref": "the move to Mesa", "relation": "after"})

    def test_a_malformed_claim_is_none_never_an_error(self):
        for value in (None, "1984", [], {}, {"relation": "sideways"}, {"age": "  "}):
            with self.subTest(value=value):
                self.assertIsNone(ch.possible_date_claim(value))

    def test_record_from_claim_does_the_age_arithmetic(self):
        record = ch.record_from_claim({"age": "about 5"}, birth_date="1979")
        self.assertEqual(record.best, "1984~")
        self.assertEqual(record.basis, "age")

    def test_record_from_claim_resolves_an_anchor_by_key_or_label(self):
        anchors = {"mesa": {"label": "the move to Mesa", "date": "1984/1990"}}
        by_key = ch.record_from_claim({"anchor_ref": "mesa", "relation": "after"},
                                      anchors=anchors)
        by_label = ch.record_from_claim(
            {"anchor_ref": "the move to Mesa", "relation": "after"}, anchors=anchors)
        self.assertEqual(by_key.best, "1990/..")
        self.assertEqual(by_label.best, "1990/..")
        self.assertEqual(by_key.anchors, ("mesa",))

    def test_several_claims_intersect_into_one_interval(self):
        record = ch.record_from_claim(
            {"age": "about 5", "anchor_ref": "mesa", "relation": "during"},
            birth_date="1979",
            anchors={"mesa": "1984/1990"},
        )
        self.assertEqual((record.earliest, record.latest), ("1984", "1986"))

    def test_disjoint_claims_fall_back_to_the_best_supported_and_never_error(self):
        record = ch.record_from_claim(
            {"stated": "1984", "anchor_ref": "mesa", "relation": "after"},
            anchors={"mesa": "1995/1999"},
        )
        self.assertEqual(record.best, "1984")

    def test_a_claim_the_system_cannot_resolve_is_none(self):
        self.assertIsNone(ch.record_from_claim({"age": "about 5"}))  # no birthday
        self.assertIsNone(ch.record_from_claim({"anchor_ref": "mesa"}, anchors={}))
        self.assertIsNone(ch.record_from_claim(None))


class YearHelperTests(unittest.TestCase):
    def test_year_of_reads_either_bound(self):
        record = ch.parse_edtf("1984/1990")
        self.assertEqual(ch.year_of(record), 1984)
        self.assertEqual(ch.year_of(record, end=True), 1990)
        self.assertEqual(ch.year_of("1998-06-12"), 1998)
        self.assertIsNone(ch.year_of(None))


class CarriageTests(unittest.TestCase):
    """B4: a record survives an argv WHOLE, or the trip fails loudly.

    Until v221 `landmark_invocation` serialized the EDTF expression alone and
    `lifehug.py landmark-record` rebuilt it with ``basis="stated"`` — so a
    date the system CALCULATED from an age was filed as one the person had
    STATED. These pin the two halves as exact inverses.
    """

    def setUp(self):
        self.calculated = ch.DateRecord(
            best="1984", earliest="1984", latest="1984", granularity="year",
            confidence="approximate", basis="age", anchors=("birth",),
            provenance=({"claim": "about five", "basis": "age", "source": "A12"},),
        )

    def _round_trip(self, record, *, meta_prefix=""):
        argv = ch.date_argv(record, value_flag="--date", meta_prefix=meta_prefix)
        names = ch.date_flag_names(meta_prefix)
        single = {name: argv[argv.index(names[name]) + 1]
                  for name in ("basis", "granularity", "confidence")
                  if names[name] in argv}
        repeated = {name: [argv[i + 1] for i, token in enumerate(argv)
                           if token == names[name]]
                    for name in ("anchor", "provenance")}
        return ch.date_from_argv(argv[argv.index("--date") + 1],
                                 anchors=repeated["anchor"],
                                 provenance=repeated["provenance"], **single)

    def test_a_calculated_date_survives_the_argv_byte_faithfully(self):
        self.assertEqual(self._round_trip(self.calculated).to_dict(),
                         self.calculated.to_dict())

    def test_every_warrant_field_is_carried(self):
        """The EDTF expression cannot say any of these; the flags must."""
        argv = ch.date_argv(self.calculated, value_flag="--date")
        bare = ch.parse_edtf(argv[argv.index("--date") + 1])
        carried = self._round_trip(self.calculated)
        for name in ch.WARRANT_FIELDS:
            with self.subTest(name):
                self.assertEqual(getattr(carried, name),
                                 getattr(self.calculated, name))
        # Everything the bare expression gets WRONG on its own — the exact
        # loss `landmark-record` used to file: basis, confidence, and the two
        # evidence lists.
        for name in ("basis", "confidence", "anchors", "provenance"):
            with self.subTest(f"lost without carriage: {name}"):
                self.assertNotEqual(getattr(bare, name),
                                    getattr(self.calculated, name))

    def test_the_two_ends_of_a_span_keep_separate_warrants(self):
        start = ch.date_argv(self.calculated, value_flag="--start",
                             meta_prefix="start-")
        end = ch.date_argv(ch.parse_edtf("1991", basis="stated"),
                           value_flag="--end", meta_prefix="end-")
        self.assertIn("--start-basis", start)
        self.assertIn("--end-basis", end)
        flags = {token for token in start if token.startswith("--")}
        self.assertEqual(flags & {token for token in end if token.startswith("--")},
                         set())
        self.assertEqual(self._round_trip(self.calculated,
                                          meta_prefix="start-").to_dict(),
                         self.calculated.to_dict())

    def test_a_record_with_no_readable_date_carries_nothing(self):
        self.assertEqual(ch.date_argv(None, value_flag="--date"), [])
        self.assertEqual(ch.date_argv("not a date", value_flag="--date"), [])
        self.assertIsNone(ch.date_from_argv(""))
        self.assertIsNone(ch.date_from_argv(None))

    def test_an_undeclared_warrant_is_only_ever_the_terminal_default(self):
        """`stated` is honest for a person typing a date; nothing else."""
        typed = ch.date_from_argv("1984")
        self.assertEqual(typed.basis, "stated")
        self.assertEqual(ch.date_from_argv("1984", basis="age").basis, "age")
        # And the machine path always declares, so it never sees the default.
        argv = ch.date_argv(self.calculated, value_flag="--date")
        self.assertIn("--basis", argv)

    def test_an_unusable_warrant_fails_loudly_rather_than_going_missing(self):
        for kwargs in ({"basis": "guessed"}, {"granularity": "fortnight"},
                       {"confidence": "pretty sure"},
                       {"provenance": ["not json"]},
                       {"provenance": ["[1, 2]"]}, {"provenance": [""]}):
            with self.subTest(**kwargs), self.assertRaises(ch.ChronologyError):
                ch.date_from_argv("1984", **kwargs)
        with self.assertRaises(ch.ChronologyError):
            ch.date_from_argv("the year I turned five")

    def test_provenance_survives_as_compact_json(self):
        entry = {"claim": "about five", "basis": "age"}
        self.assertEqual(ch.parse_provenance_arg(ch.provenance_arg(entry)), entry)
        self.assertIsNone(ch.provenance_arg({}))
        self.assertIsNone(ch.provenance_arg("not an object"))


class ClaimFoldTests(unittest.TestCase):
    """B4: repeat tellings corroborate; rivals stay rivals; refinements win."""

    def test_the_same_claim_told_twice_folds_and_keeps_both_sources(self):
        first = ch.DateRecord(best="1984", earliest="1984", latest="1984",
                              basis="stated", confidence="certain",
                              anchors=("birth",),
                              provenance=({"source": "A1"},))
        again = ch.DateRecord(best="1984", earliest="1984", latest="1984",
                              basis="stated", confidence="certain",
                              anchors=("move",), provenance=({"source": "A2"},))
        folded = ch.merge_claims([first, again])
        self.assertEqual(len(folded), 1)
        self.assertEqual(folded[0].anchors, ("birth", "move"))
        self.assertEqual([p["source"] for p in folded[0].provenance], ["A1", "A2"])
        self.assertGreater(ch.claim_score(folded[0]), ch.claim_score(first))

    def test_refiling_the_identical_record_is_a_no_op(self):
        record = ch.DateRecord(best="1984", earliest="1984", latest="1984",
                               basis="stated", provenance=({"source": "A1"},))
        self.assertEqual(ch.merge_claims([record, record, record]), [record])

    def test_the_same_interval_on_a_different_basis_is_a_different_claim(self):
        said = ch.DateRecord(best="1984", earliest="1984", latest="1984",
                             basis="stated")
        worked_out = ch.DateRecord(best="1984", earliest="1984", latest="1984",
                                   basis="age")
        self.assertEqual(len(ch.merge_claims([said, worked_out])), 2)

    def test_a_refinement_outranks_the_coarser_claim_it_refines(self):
        coarse = ch.DateRecord(best="2001", earliest="2001", latest="2001",
                               granularity="year", basis="stated",
                               confidence="certain")
        fine = ch.DateRecord(best="2001-06-14", earliest="2001-06-14",
                             latest="2001-06-14", granularity="day",
                             basis="stated", confidence="certain")
        result = ch.reconcile([coarse, fine])
        self.assertEqual(result["best_supported"], fine)
        self.assertEqual(result["alternates"], [coarse])
        self.assertEqual(result["conflict"], 0.0)

    def test_better_support_still_beats_a_finer_grain(self):
        printed = ch.DateRecord(best="1984", earliest="1984", latest="1984",
                                granularity="year", basis="document",
                                confidence="certain")
        guessed = ch.DateRecord(best="1984-06-12", earliest="1984-06-12",
                                latest="1984-06-12", granularity="day",
                                basis="order", confidence="conjectural")
        self.assertEqual(ch.reconcile([guessed, printed])["best_supported"], printed)


class ConflictStrengthTests(unittest.TestCase):
    def test_claims_that_can_both_be_true_are_not_in_conflict(self):
        year = ch.DateRecord(best="1984", earliest="1984", latest="1984",
                             basis="stated", confidence="certain")
        month = ch.DateRecord(best="1984-06", earliest="1984-06", latest="1984-06",
                              granularity="month", basis="stated",
                              confidence="certain")
        self.assertEqual(ch.reconcile([year, month])["conflict"], 0.0)

    def test_a_dead_tie_between_contradictory_claims_is_total_conflict(self):
        one = ch.DateRecord(best="1984", earliest="1984", latest="1984",
                            basis="stated", confidence="certain")
        other = ch.DateRecord(best="1987", earliest="1987", latest="1987",
                              basis="stated", confidence="certain")
        self.assertEqual(ch.reconcile([one, other])["conflict"], 1.0)

    def test_a_weakly_supported_rival_is_a_weak_conflict(self):
        stated = ch.DateRecord(best="1984", earliest="1984", latest="1984",
                               basis="stated", confidence="certain")
        guessed = ch.DateRecord(best="1990", earliest="1990", latest="1990",
                                basis="order", confidence="conjectural")
        result = ch.reconcile([stated, guessed])
        self.assertEqual(result["best_supported"], stated)
        self.assertGreater(result["conflict"], 0.0)
        self.assertLess(result["conflict"], 1.0)

    def test_a_lone_claim_conflicts_with_nothing(self):
        lone = ch.DateRecord(best="1984", earliest="1984", latest="1984")
        self.assertEqual(ch.reconcile([lone])["conflict"], 0.0)
        self.assertEqual(ch.conflict_strength(None, [lone]), 0.0)


if __name__ == "__main__":
    unittest.main()
