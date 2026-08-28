"""E-BO — the calculated birth origin.

Contract: `docs/pr-specs/eras-o-bo-birth-origin.md`. Controlling design §3.2
(calculated origin), §3.3 (grain), §9.1 (`T-BO-02…10`); platform
`docs/design/eras.md` §13.1 promises tagged (E-BO); the alternative auditor's
handoff §5.1 and §11.1.

Every negative test here was run against this branch's base
(`origin/feat/eras-o-e1-age-frames`) first and SEEN failing; the evidence is
in the PR body.

Synthetic data only. NEVER references ~/Workspace/dave.
"""

from __future__ import annotations

import hashlib
import random
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "system"))

import birth_origin as bo  # noqa: E402
import chronology as chrono  # noqa: E402
import mirror_work as mw  # noqa: E402
import temporal_claims as tc  # noqa: E402
import temporal_projection as tp  # noqa: E402
import temporal_timeline as tt  # noqa: E402

NOW = "2026-08-27T12:00:00Z"


# ---------------------------------------------------------------------------
# Fixtures — every date, name and quote below is invented
# ---------------------------------------------------------------------------


def revision(seed: str) -> str:
    return "sha256:" + hashlib.sha256(seed.encode("utf-8")).hexdigest()


def claim(**overrides) -> dict:
    source = overrides.pop("source", "src-1")
    payload = {
        "source_kind": "conversation",
        "source_ref": {"source_id": source, "revision": revision(source)},
        "evidence": [{"quote": overrides.pop("quote", "a sentence from the conversation")}],
        "extractor_version": "listener:1",
        "created_at": "2026-08-27T00:00:00Z",
        "basis": "explicit",
        "confidence": 0.9,
        "status": "active",
    }
    payload.update(overrides)
    return tc.validate_temporal_claim(payload)


def dated(*, subject: str, event_kind: str, best: str, granularity: str,
          source: str) -> dict:
    return claim(
        claim_type="date",
        subject_mention=subject,
        event_kind=event_kind,
        event_ref=f"node:{event_kind}-{source}",
        temporal_value=chrono.DateRecord(
            best=best, earliest=best, latest=best, granularity=granularity,
            confidence="certain", basis="stated",
        ).to_dict(),
        source=source,
    )


def aged(*, subject: str, event_kind: str, age: object, source: str,
         quote: str = "a sentence from the conversation") -> dict:
    return claim(
        claim_type="age",
        subject_mention=subject,
        event_kind=event_kind,
        event_ref=f"node:{event_kind}-{source}",
        temporal_value=age,
        source=source,
        quote=quote,
    )


def quantity(low: int, high: int | None = None, *, approximate: bool = False,
             text: str | None = None) -> dict:
    return tc.TemporalQuantity(
        kind="age", low=float(low), high=float(high if high is not None else low),
        unit="years", approximate=approximate, text=text,
    ).to_dict()


def fold(claims, **kwargs):
    return tt.derive_calculated_timeline(list(claims), now=NOW, **kwargs)


def nodes_by_kind(result, event_kind: str) -> list[dict]:
    return [row for row in result.nodes if row.get("event_kind") == event_kind]


def birth_node(result) -> dict | None:
    rows = nodes_by_kind(result, "birth")
    return rows[0] if rows else None


def work_items(result, kind: str, **match) -> list[dict]:
    out = []
    for row in result.work_items:
        if row.get("kind") != kind:
            continue
        if all(row.get(key) == value for key, value in match.items()):
            out.append(row)
    return out


def span_days(record: chrono.DateRecord) -> int:
    low = chrono._ordinal(record.earliest, end=False)  # noqa: SLF001
    high = chrono._ordinal(record.latest, end=True)  # noqa: SLF001
    from datetime import date
    return (date(*high) - date(*low)).days


# ---------------------------------------------------------------------------
# O-BO-a — the pure arithmetic
# ---------------------------------------------------------------------------


class BirthOriginArithmeticTests(unittest.TestCase):
    """T-BO-02, T-BO-03, T-BO-09 — `chronology.birth_origin_from_age`."""

    def test_t_bo_02_exact_age_at_a_day_grain_event(self):
        """Age 30 on 2011-06-15 → birth in (1980-06-15, 1981-06-15]."""
        record = chrono.birth_origin_from_age(
            chrono.parse_edtf("2011-06-15"), quantity(30, text="I was 30")
        )
        self.assertIsNotNone(record)
        self.assertEqual(record.earliest, "1980-06-16")
        self.assertEqual(record.latest, "1981-06-15")
        self.assertEqual(record.best, "1980-06-16/1981-06-15")
        self.assertEqual(record.granularity, "range")
        # basis `age` is what makes a frame publish origin_basis: calculated.
        self.assertEqual(record.basis, "age")
        self.assertEqual(tc.CLAIM_BASIS_BY_DATE_BASIS[record.basis], "calculated")
        # "confidence <= inferred" even though the event was stated as certain.
        self.assertEqual(record.confidence, "inferred")
        self.assertEqual(
            record.confidence, chrono.at_most(record.confidence, "inferred")
        )
        self.assertIn(
            chrono.BIRTH_ORIGIN_RULE, [p.get("source") for p in record.provenance]
        )
        self.assertIn("I was 30", [p.get("claim") for p in record.provenance])

    def test_t_bo_02b_the_interval_is_the_inverse_of_from_age_band(self):
        """Every day in the interval really does give that age at that event."""
        record = chrono.birth_origin_from_age(
            chrono.parse_edtf("2011-06-15"), quantity(30)
        )
        for candidate in (record.earliest, record.latest):
            forward = chrono.from_age_band(chrono.parse_edtf(candidate), 30, 30)
            self.assertIsNotNone(forward)
            # 2011 is inside the interval `age 30` puts on a birthday of
            # either endpoint — the forward and backward rules agree.
            self.assertLessEqual(chrono.year_of(forward), 2011)
            self.assertGreaterEqual(chrono.year_of(forward, end=True), 2011)

    def test_t_bo_03_a_coarser_event_gives_coarser_edges(self):
        """A year-grain event bounds a birth to years, a month to months."""
        by_year = chrono.birth_origin_from_age(chrono.parse_edtf("2011"), quantity(30))
        self.assertEqual((by_year.earliest, by_year.latest), ("1980", "1981"))
        self.assertEqual(by_year.best, "1980/1981")
        self.assertEqual(chrono.display_date(by_year, with_basis=False), "1980–1981")

        by_month = chrono.birth_origin_from_age(
            chrono.parse_edtf("2011-06"), quantity(30)
        )
        self.assertEqual((by_month.earliest, by_month.latest), ("1980-06", "1981-06"))

        # Coarser is WIDER, never narrower — the whole point of rounding out.
        by_day = chrono.birth_origin_from_age(
            chrono.parse_edtf("2011-06-15"), quantity(30)
        )
        self.assertGreater(span_days(by_year), span_days(by_month))
        self.assertGreater(span_days(by_month), span_days(by_day))

    def test_t_bo_03b_approximate_widens_by_a_year_each_side(self):
        exact = chrono.birth_origin_from_age(
            chrono.parse_edtf("2011-06-15"), quantity(30)
        )
        hedged = chrono.birth_origin_from_age(
            chrono.parse_edtf("2011-06-15"), quantity(30, approximate=True)
        )
        self.assertEqual(hedged.earliest, "1979-06-16")
        self.assertEqual(hedged.latest, "1982-06-15")
        self.assertGreater(span_days(hedged), span_days(exact))
        # The same widening `chronology.parse_age` applies to a hedged phrase.
        self.assertEqual(chrono.parse_age("about 30"), (30, 30, True))

    def test_t_bo_03c_an_unusable_input_is_none_never_an_invention(self):
        event = chrono.parse_edtf("2011-06-15")
        self.assertIsNone(  # a duration-shaped unit is not an age in years
            chrono.birth_origin_from_age(event, {"low": 8, "high": 8, "unit": "months"})
        )
        self.assertIsNone(  # outside parse_age's own domain
            chrono.birth_origin_from_age(event, {"low": 0, "high": 400})
        )
        self.assertIsNone(chrono.birth_origin_from_age(event, {"low": 12.5, "high": 12.5}))
        self.assertIsNone(chrono.birth_origin_from_age(event, "thirty"))
        self.assertIsNone(chrono.birth_origin_from_age(None, quantity(30)))
        self.assertIsNone(chrono.birth_origin_from_age("not a date", quantity(30)))

    def test_t_bo_03d_a_band_spanning_two_ages(self):
        """"I was 12 or 13" bounds the birth by the WIDER of the two."""
        record = chrono.birth_origin_from_age(
            chrono.parse_edtf("2011-06-15"), quantity(12, 13, text="12 or 13")
        )
        self.assertEqual(record.earliest, "1997-06-16")
        self.assertEqual(record.latest, "1999-06-15")

    def test_t_bo_09_leap_day_edges_widen_and_say_so(self):
        """Rule `birth-origin:leap-day` — 29 February is never guessed away."""
        # The EVENT is 29 February: both shifts clamp to the 28th.
        on_leap_day = chrono.birth_origin_from_age(
            chrono.parse_edtf("2012-02-29"), quantity(10)
        )
        self.assertEqual((on_leap_day.earliest, on_leap_day.latest),
                         ("2001-02-28", "2002-02-28"))
        self.assertIn(chrono.BIRTH_ORIGIN_LEAP_RULE,
                      [p.get("source") for p in on_leap_day.provenance])

        # The UPPER bound lands on 28 February of a leap year: a birthday on
        # the 29th of that year is a candidate, so the bound reaches it.
        into_leap_year = chrono.birth_origin_from_age(
            chrono.parse_edtf("2012-02-28"), quantity(12)
        )
        self.assertEqual(into_leap_year.latest, "2000-02-29")
        self.assertIn(chrono.BIRTH_ORIGIN_LEAP_RULE,
                      [p.get("source") for p in into_leap_year.provenance])

        # An ordinary March event carries no leap rule at all.
        ordinary = chrono.birth_origin_from_age(
            chrono.parse_edtf("2012-03-01"), quantity(12)
        )
        self.assertNotIn(chrono.BIRTH_ORIGIN_LEAP_RULE,
                         [p.get("source") for p in ordinary.provenance])

    def test_day_after_is_the_mirror_of_day_before(self):
        self.assertEqual(chrono.day_after("2001-07-11"), "2001-07-12")
        self.assertEqual(chrono.day_after("2000-02-28"), "2000-02-29")
        self.assertEqual(chrono.day_after("2001-12-31"), "2002-01-01")
        self.assertEqual(chrono.day_before(chrono.day_after("2001-07-11")), "2001-07-11")
        self.assertIsNone(chrono.day_after("2001-07"))
        self.assertIsNone(chrono.day_after(None))


class IntersectionTests(unittest.TestCase):
    """T-BO-04 — compatible constraints TIGHTEN; nothing is averaged."""

    def test_t_bo_04_two_compatible_constraints_intersect(self):
        """Two statements, two different events, ONE smaller window."""
        thirty = chrono.birth_origin_from_age(
            chrono.parse_edtf("2011-06-15"), quantity(30)
        )
        forty_five = chrono.birth_origin_from_age(
            chrono.parse_edtf("2026-01-10"), quantity(45)
        )
        self.assertEqual((thirty.earliest, thirty.latest), ("1980-06-16", "1981-06-15"))
        self.assertEqual(
            (forty_five.earliest, forty_five.latest), ("1980-01-11", "1981-01-10")
        )
        combined = chrono.intersect(thirty, forty_five)
        self.assertIsNotNone(combined)
        self.assertEqual((combined.earliest, combined.latest),
                         ("1980-06-16", "1981-01-10"))
        # Strictly tighter than EITHER input — the low end from one statement,
        # the high end from the other.
        self.assertLess(span_days(combined), span_days(thirty))
        self.assertLess(span_days(combined), span_days(forty_five))
        # And nothing was averaged: both endpoints are endpoints somebody's
        # statement actually put there, not a point between them.
        self.assertIn(combined.earliest, (thirty.earliest, forty_five.earliest))
        self.assertIn(combined.latest, (thirty.latest, forty_five.latest))

    def test_t_bo_04b_disjoint_constraints_intersect_to_none_not_a_midpoint(self):
        first = chrono.birth_origin_from_age(chrono.parse_edtf("2011"), quantity(30))
        second = chrono.birth_origin_from_age(chrono.parse_edtf("2011"), quantity(20))
        self.assertEqual((second.earliest, second.latest), ("1990", "1991"))
        self.assertIsNone(chrono.intersect(first, second))


# ---------------------------------------------------------------------------
# O-BO-b / O-BO-d — the provisional origin inside the fold
# ---------------------------------------------------------------------------


class ProvisionalOriginTests(unittest.TestCase):
    """T-BO-04, T-BO-05, T-BO-06, T-BO-07, T-BO-08, T-BO-10."""

    def one_statement(self) -> list[dict]:
        """*"I was 30 when I started there"* — 2011-06-15, and no birthday."""
        return [
            dated(subject="self", event_kind="job", best="2011-06-15",
                  granularity="day", source="s-job"),
            aged(subject="self", event_kind="job",
                 age=quantity(30, text="I was 30"), source="s-job",
                 quote="I was 30 when I started there"),
        ]

    def two_agreeing_statements(self) -> list[dict]:
        return self.one_statement() + [
            dated(subject="self", event_kind="graduation", best="2026-01-10",
                  granularity="day", source="s-grad"),
            aged(subject="self", event_kind="graduation",
                 age=quantity(45, text="I was 45"), source="s-grad",
                 quote="I was 45 when I went back and finished"),
        ]

    def two_disagreeing_statements(self) -> list[dict]:
        return [
            dated(subject="self", event_kind="job", best="2011",
                  granularity="year", source="s-job"),
            aged(subject="self", event_kind="job", age=quantity(30, text="I was 30"),
                 source="s-job", quote="I was 30 when I started there"),
            dated(subject="self", event_kind="graduation", best="2011",
                  granularity="year", source="s-grad"),
            aged(subject="self", event_kind="graduation",
                 age=quantity(20, text="I was 20"), source="s-grad",
                 quote="I was 20 when I graduated"),
        ]

    # -- the scaffold appears --------------------------------------------

    def test_t_bo_04c_one_statement_seeds_a_provisional_scaffold(self):
        result = fold(self.one_statement())
        node = birth_node(result)
        self.assertIsNotNone(node, "no provisional birth origin was seeded")
        self.assertEqual(node["origin_basis"], "calculated")
        self.assertEqual(node["basis"], "calculated")
        self.assertEqual(node["temporal_state"], "partial")
        self.assertEqual(node["conflict_state"], "none")
        self.assertEqual(node["best_temporal_value"]["earliest"], "1980-06-16")
        self.assertEqual(node["best_temporal_value"]["latest"], "1981-06-15")
        self.assertIn("Calculated from", node["provenance_summary"])
        self.assertIn("I was 30", node["provenance_summary"])
        self.assertIn("no birthday on file yet", node["provenance_summary"])
        # A node is calculated, not asserted: it cites the claims it came from.
        self.assertEqual(len(node["input_claim_refs"]), 2)

        # …and the frames are drawn on it, saying so.
        frames = nodes_by_kind(result, "age_frame")
        self.assertTrue(frames)
        for frame in frames:
            self.assertEqual(frame["origin_basis"], "calculated")
            self.assertEqual(frame["provenance_summary"],
                             bo.CALCULATED_ORIGIN_PROVENANCE)
            self.assertNotEqual(frame["provenance_summary"], "from your birthday")
        bands = {frame["node_id"] for frame in frames}
        self.assertIn(tp.age_frame_node_id("childhood"), bands)
        self.assertIn(tp.age_frame_node_id("30s"), bands)

    def test_t_bo_04d_a_second_agreeing_statement_tightens_the_origin(self):
        one = birth_node(fold(self.one_statement()))["best_temporal_value"]
        two = birth_node(fold(self.two_agreeing_statements()))["best_temporal_value"]
        self.assertEqual((two["earliest"], two["latest"]), ("1980-06-16", "1981-01-10"))
        self.assertLess(
            span_days(chrono.from_dict(two)), span_days(chrono.from_dict(one))
        )
        # Tightened by INTERSECTION: each endpoint is an endpoint some
        # statement put there. Nothing between them was invented.
        self.assertEqual(two["earliest"], one["earliest"])
        self.assertNotEqual(two["latest"], one["latest"])

    # -- the scaffold is withheld ----------------------------------------

    def test_t_bo_05_disjoint_evidence_withholds_the_frames(self):
        result = fold(self.two_disagreeing_statements())
        node = birth_node(result)
        self.assertIsNotNone(node)
        # No winner is selected, and no midpoint is invented.
        self.assertIsNone(node["best_temporal_value"])
        self.assertEqual(node["conflict_state"], "contradicted")
        self.assertEqual(node["temporal_state"], "contradictory")
        readings = {
            (row["earliest"], row["latest"]) for row in node["alternate_values"]
        }
        self.assertEqual(readings, {("1980", "1981"), ("1990", "1991")})
        # The frames are WITHHELD — an axis is not drawn on a disagreement.
        self.assertEqual(nodes_by_kind(result, "age_frame"), [])

    def test_t_bo_05b_disjoint_evidence_mints_a_material_mirror_row(self):
        claims = self.two_disagreeing_statements()
        result = fold(claims)
        items = work_items(result, "contradiction", requested_field="birth_date")
        self.assertEqual(len(items), 1)
        item = items[0]
        self.assertIn("mirror", item["allowed_surfaces"])
        # It cites the statements that disagree — the AGE claims, which are
        # quantities and therefore undated, which is what keeps the row open.
        self.assertEqual(len(item["claim_refs"]), 2)
        row = mw.row_for(item, {"claims": claims})
        self.assertIsNotNone(row)
        self.assertEqual(row.state, "open")
        self.assertEqual(row.headline, "A disagreement about your birthday")
        self.assertIn("can't both be true", row.description)
        self.assertIn("your birthday", row.description)
        self.assertGreater(row.severity, 0.0)

    def test_t_bo_05c_a_third_agreeing_statement_does_not_hide_the_split(self):
        """Two readings stay two readings; the third joins one of them."""
        claims = self.two_disagreeing_statements() + [
            dated(subject="self", event_kind="move", best="2001",
                  granularity="year", source="s-move"),
            aged(subject="self", event_kind="move", age=quantity(20, text="I was 20"),
                 source="s-move", quote="I was 20 when we moved"),
        ]
        node = birth_node(fold(claims))
        readings = {
            (row["earliest"], row["latest"]) for row in node["alternate_values"]
        }
        self.assertEqual(readings, {("1980", "1981"), ("1990", "1991")})
        self.assertIsNone(node["best_temporal_value"])

    # -- whose age is it -------------------------------------------------

    def test_t_bo_06_someone_elses_age_never_seeds_the_owner(self):
        """"Grandma was 30 in 1951" — neither by subject nor by phrasing."""
        by_subject = [
            dated(subject="Grandma", event_kind="move", best="1951",
                  granularity="year", source="s-gran"),
            aged(subject="Grandma", event_kind="move", age=quantity(30),
                 source="s-gran", quote="Grandma was 30 when they moved"),
        ]
        result = fold(by_subject)
        self.assertIsNone(birth_node(result))
        self.assertEqual(nodes_by_kind(result, "age_frame"), [])

        # And the deterministic veto holds even when the claim was FILED
        # against the owner: the phrase is still about somebody else.
        misfiled = [
            dated(subject="self", event_kind="move", best="1951",
                  granularity="year", source="s-gran"),
            aged(subject="self", event_kind="move",
                 age=quantity(30, text="Grandma was 30"), source="s-gran",
                 quote="Grandma was 30 when they moved"),
        ]
        self.assertIsNone(birth_node(fold(misfiled)))

    def test_t_bo_06b_the_owners_own_first_person_phrase_still_seeds(self):
        """The veto is a veto, not a blanket refusal of every age phrase."""
        claims = [
            dated(subject="self", event_kind="move", best="1994",
                  granularity="year", source="s-move"),
            aged(subject="self", event_kind="move",
                 age=quantity(12, text="when I was 12"), source="s-move",
                 quote="when I was 12 we moved to the coast"),
        ]
        self.assertIsNotNone(birth_node(fold(claims)))

    def test_t_bo_06c_an_undated_event_bounds_nothing(self):
        """An age with no dated event to measure it at seeds nothing."""
        claims = [
            aged(subject="self", event_kind="move", age=quantity(12, text="I was 12"),
                 source="s-move", quote="I was 12 when we moved"),
        ]
        result = fold(claims)
        self.assertIsNone(birth_node(result))
        self.assertEqual(nodes_by_kind(result, "age_frame"), [])

    # -- the explicit birthday -------------------------------------------

    def test_t_bo_07_the_birthday_question_stays_open(self):
        """A provisional origin is a scaffold, never an answer."""
        result = fold(self.one_statement())
        items = work_items(result, "missing_anchor", requested_field="birth_date")
        self.assertEqual(len(items), 1, "the explicit-birthday question was closed")
        self.assertEqual(items[0]["state"], "open")
        self.assertIn("What is your date of birth?", items[0]["prompt_intent"])
        # It is still open on the surfaces that can ask it.
        self.assertIn("daily_question", items[0]["allowed_surfaces"])

    def test_t_bo_07b_an_explicit_birthday_closes_it(self):
        stated = claim(
            claim_type="date", subject_mention="self", event_kind="birth",
            temporal_value=chrono.DateRecord(
                best="1981-07-11", earliest="1981-07-11", latest="1981-07-11",
                granularity="day", confidence="certain", basis="stated",
            ).to_dict(), source="s-birth",
        )
        result = fold(self.one_statement() + [stated])
        self.assertEqual(
            work_items(result, "missing_anchor", requested_field="birth_date"), []
        )

    def test_t_bo_08_an_explicit_birthday_replaces_the_provisional_view(self):
        stated = claim(
            claim_type="date", subject_mention="self", event_kind="birth",
            temporal_value=chrono.DateRecord(
                best="1981-07-11", earliest="1981-07-11", latest="1981-07-11",
                granularity="day", confidence="certain", basis="stated",
            ).to_dict(), source="s-birth",
        )
        provisional = fold(self.one_statement())
        explicit = fold(self.one_statement() + [stated])

        # ONE identity across both: the birthday tightens the view rather than
        # competing with a second node for the axis.
        self.assertEqual(birth_node(explicit)["node_id"],
                         birth_node(provisional)["node_id"])
        self.assertEqual(birth_node(explicit)["best_temporal_value"]["best"],
                         "1981-07-11")
        self.assertEqual(birth_node(explicit)["origin_basis"], "explicit")
        for frame in nodes_by_kind(explicit, "age_frame"):
            self.assertEqual(frame["origin_basis"], "explicit")
            self.assertEqual(frame["provenance_summary"], "from your birthday")

        # …and the calculated evidence STAYS: the age claim is still active and
        # still cited on its own event. `_record_for_age_claim` stays
        # year-grain (binding fact 3 — `from_age_band` reads only
        # `year_of(birth)`; sharpening it to a birthday-derived DAY is what
        # `test_about_twelve_is_a_fuzzy_interval_not_a_birthday_derived_day`
        # pins against), so the job's own exact stated date is untouched —
        # what changes is that the age claim is no longer withheld for want
        # of a birth anchor, and both claims still cite the node.
        job = [row for row in explicit.nodes if row.get("event_kind") == "job"][0]
        self.assertEqual(job["best_temporal_value"]["best"], "2011-06-15")
        self.assertGreaterEqual(len(job["input_claim_refs"]), 2)

    # -- purity ------------------------------------------------------------

    def test_t_bo_10_the_projection_is_order_independent(self):
        claims = self.two_agreeing_statements()
        first = tt.structural_signature(fold(claims))
        shuffled = list(claims)
        random.Random(20260827).shuffle(shuffled)
        self.assertNotEqual(shuffled, claims)
        self.assertEqual(tt.structural_signature(fold(shuffled)), first)

        # …and so is the contradicted one, alternates included.
        disagreeing = self.two_disagreeing_statements()
        baseline = tt.structural_signature(fold(disagreeing))
        random.Random(11).shuffle(disagreeing)
        self.assertEqual(tt.structural_signature(fold(disagreeing)), baseline)


class TemporalStateContractTests(unittest.TestCase):
    """The additive `temporal_state` field (O-BO-c)."""

    def base(self, **overrides) -> dict:
        payload = {
            "node_id": "node:test",
            "node_kind": "event",
            "event_kind": "birth",
            "input_claim_refs": ["claim:1"],
            "calculation_rule_version": "timeline-rules:2",
        }
        payload.update(overrides)
        return payload

    def test_a_known_state_survives_the_round_trip(self):
        for state in tp.TEMPORAL_STATES:
            row = tp.validate_calculated_timeline_node(
                self.base(temporal_state=state)
            )
            self.assertEqual(row["temporal_state"], state)
            self.assertEqual(tp.node_from_dict(row).temporal_state, state)

    def test_an_unknown_state_is_refused_by_name(self):
        with self.assertRaises(tp.TimelineNodeError) as caught:
            tp.validate_calculated_timeline_node(self.base(temporal_state="maybe"))
        self.assertEqual(caught.exception.code, "unknown_temporal_state")
        self.assertIn("unknown_temporal_state", tp.ERROR_CODES)

    def test_absent_means_unchanged(self):
        row = tp.validate_calculated_timeline_node(self.base())
        self.assertNotIn("temporal_state", row)
        self.assertIsNone(tp.node_from_dict(row).temporal_state)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
