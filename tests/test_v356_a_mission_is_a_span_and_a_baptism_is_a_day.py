"""v356 — a mission is a span, a baptism is a day, and neither is asked unmentioned.

THE RULING (owner, 2026-09-25), verbatim:

    "a mission is a span like military service look up lds or mormon mission
    for context; a baptism is a discreet event on a date; both should not get
    default landmark questions but if mentioned should enable landmark
    questions"

An LDS mission is full-time proselytising service — conventionally about two
years for young men and eighteen months for young women, begun between 18 and
25 — with a departure, training at a Missionary Training Center, one or more
assigned areas with transfers between them, and a return. A baptism in that
tradition is one dated ordinance, conventionally at eight or at conversion.

The fixtures are the SHAPES the owner's own vault carries (labels quoted from
his tellings and his landmark store), on a synthetic vault: nothing here reads
a real one.

GUARDS.
1. The two kinds: `mission` a SPAN (the `missions` ladder's participation
   episode, drawn where `military` is), `baptism` a POINT (the `baptism`
   ladder's own date semantic, the owner's as `birth` is).
2. No default question: a vault that never mentioned either has no row, no
   plan item and a `not_mentioned` sufficiency verdict.
3. A mention opens the ladder — his own phrasings do; a company's mission
   statement does not.
4. Both are life events, so a loose placement keeps its date card.
5. A mission entry OPENS A SPAN, which is the one thing the existing
   containment rung asks of a container.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "system"))

import chronology as chrono
import episode_binder as eb
import episode_containers as ec
import landmark_opportunities as lo
import landmark_projection as lp
import landmarks_interaction as li
import temporal_claims as tc
import temporal_projection as tp
import temporal_timeline as tt
import temporal_work_items as twi

#: The owner's own mission tellings, as his vault labels them.
OWNER_MISSION_SHAPES = (
    "Departed on church mission at 19",
    "Served two-year Mormon mission",
    "Mission to Switzerland at 19",
    "Residence at the MTC",
    "Mission assignment to Solothurn",
    "LDS mission service begins",
    "Returned home from mission",
    "Preparing to leave on mission at 18",
    "Bishop Ellsworth guides mission preparation",
)

#: The one shape whose only mission words are "mission to".
BARE_MISSION_TO = "Mission to Switzerland at 19"

#: And the one baptism it mentions, which is his daughter's.
OWNER_BAPTISM_SHAPE = (
    "I just flew my mom out for my daughter's baptism, and when she left, "
    "I walked her to the gate"
)

#: Sentences from the same vault that say "mission" and mean none.
NOT_A_MISSION = (
    "So Joy Labs had the wrong mission statement to achieve the right outcome",
    "it's the wrong mission to get the correct outcome",
    "if your mission is to be happy and comfortable",
    "We went to the Baptist church on Main Street",
)


def stated(best: str, granularity: str) -> dict:
    return {"best": best, "granularity": granularity,
            "confidence": "certain", "basis": "stated"}


#: His mission, dated the way his own stays date it: left for the MTC in
#: August 2000, flew home to Mesa on 6 June 2002.
MISSION_ENTRY = {
    "domain": "missions",
    "label": "Switzerland Zurich Mission",
    "where": "Switzerland Zurich Mission",
    "span": {"start": stated("2000-08", "month"),
             "end": stated("2002-06-06", "day")},
}

#: The stays inside it, from his residence chain.
STAYS_INSIDE = (
    ("MTC", "2000-08", "2000-10"),
    ("Solothurn, Switzerland", "2000-10", "2000-12"),
    ("Friedrichshafen, Germany", "2000-12", "2001-03"),
    ("Luzern, Switzerland", "2001-04", "2001-06"),
)
#: And one that is not: Berna St in Mesa, 2015.
STAY_OUTSIDE = ("Berna", "2015-07", "2016-08")


class TheTwoKindsTests(unittest.TestCase):

    def test_mission_is_a_seeded_span_kind_beside_military(self):
        self.assertIn("mission", tc.EVENT_KINDS)
        self.assertEqual(lp.PARTICIPATION_EPISODE_KINDS["missions"], "mission")
        self.assertEqual(tp.LANES_BY_EVENT_KIND["mission"],
                         tp.LANES_BY_EVENT_KIND["military"])
        row = li.domain_row("missions")
        self.assertEqual(row["date_semantics"], li.domain_row("military")["date_semantics"])
        self.assertEqual(row["ladder"], ("happened", "where", "span"))
        self.assertIn(("service", ("military", "mission")), eb.KIND_FAMILIES)

    def test_baptism_is_a_point_the_owner_holds(self):
        self.assertIn("baptism", tc.LANDMARK_DATE_SEMANTICS)
        self.assertIn("baptism", tc.EVENT_KINDS)
        row = li.domain_row("baptism")
        self.assertEqual(row["collection"], "singleton")
        self.assertTrue(li.dates_each_entry(row))
        self.assertEqual(lp.date_event_kind(row), "baptism")
        claims = lp.entry_claims("baptism", {"domain": "baptism",
                                             "date": stated("1989-06", "month")},
                                 source_ref={"source_id": "landmark:entry-test",
                                             "revision": "sha256:" + "0" * 64,
                                             "source_path": "sources/landmarks/x.md"})
        dated = [c for c in claims if c.get("temporal_value")]
        self.assertEqual({c["event_kind"] for c in dated}, {"baptism"})
        self.assertEqual({c["subject_mention"] for c in claims}, {"self"})

    def test_both_join_the_life_event_kinds(self):
        self.assertIn("mission", twi.LIFE_EVENT_KINDS)
        self.assertIn("baptism", twi.LIFE_EVENT_KINDS)

    def test_both_are_asked_as_what_they_are(self):
        self.assertEqual(
            tt.compose_question("missing_anchor", "mission",
                                what="Switzerland Zurich Mission", is_owner=True),
            "When did you leave for Switzerland Zurich Mission?")
        self.assertEqual(
            tt.compose_question("precision_gap", "baptism", is_owner=True),
            "When were you baptized?")


class NoDefaultQuestionTests(unittest.TestCase):

    def test_a_vault_that_never_mentioned_either_has_no_row(self):
        domains = {row["domain"] for row in li.landmark_rows({})}
        self.assertNotIn("missions", domains)
        self.assertNotIn("baptism", domains)
        self.assertIn("military", domains)  # every other domain is unchanged
        plan = li.build_landmarks_plan({}, limit=99)
        self.assertFalse({i["domain"] for i in plan["items"]} & {"missions", "baptism"})
        self.assertNotIn("missions", li.onboarding_domains())
        self.assertNotIn("baptism", li.onboarding_domains())

    def test_sufficiency_names_why(self):
        report = lo.sufficiency([], {})
        self.assertEqual(report["missions"]["reason"], lo.REASON_NOT_MENTIONED)
        self.assertEqual(report["baptism"]["reason"], lo.REASON_NOT_MENTIONED)
        self.assertTrue(report["missions"]["sufficient"])

    def test_the_loader_refuses_an_on_mention_domain_with_no_phrases(self):
        row = {"domain": "x", "offered": li.OFFERED_ON_MENTION, "mentioned_by": ()}
        with self.assertRaises(li.LandmarkInteractionError):
            li._validate_offered(row)
        with self.assertRaises(li.LandmarkInteractionError):
            li._validate_offered({"domain": "y", "offered": "always",
                                  "mentioned_by": ("x",)})


class AMentionOpensTheLadderTests(unittest.TestCase):

    def test_every_one_of_his_mission_shapes_is_a_mention(self):
        for text in OWNER_MISSION_SHAPES:
            if text == BARE_MISSION_TO:
                continue
            with self.subTest(text=text):
                self.assertIn("missions", li.mentioned_domains([text]))

    def test_mission_to_alone_is_not_a_phrase_and_the_vault_still_opens(self):
        """The one shape that does not open the ladder ON ITS OWN, and why:
        "mission to" is also "the wrong mission to get the correct outcome",
        a sentence from the same vault. A vault holding the shape holds the
        others beside it, so the ladder opens all the same."""
        self.assertEqual(li.mentioned_domains([BARE_MISSION_TO]), frozenset())
        self.assertIn("missions", li.mentioned_domains(OWNER_MISSION_SHAPES))

    def test_his_daughters_baptism_is_a_mention(self):
        self.assertEqual(li.mentioned_domains([OWNER_BAPTISM_SHAPE]),
                         frozenset({"baptism"}))

    def test_a_mission_statement_is_not_a_mission(self):
        for text in NOT_A_MISSION:
            with self.subTest(text=text):
                self.assertEqual(li.mentioned_domains([text]), frozenset())

    def test_a_mentioned_vault_is_offered_the_ladder_exactly_as_if_raised(self):
        mentioned = li.mentioned_domains(OWNER_MISSION_SHAPES + (OWNER_BAPTISM_SHAPE,))
        rows = {row["domain"]: row for row in li.landmark_rows({}, mentioned=mentioned)}
        self.assertEqual(rows["missions"]["next"]["text"], "Did you serve a mission?")
        self.assertEqual(rows["baptism"]["next"]["text"], "Were you baptized?")
        report = lo.sufficiency([], {}, mentioned=mentioned)
        self.assertEqual(report["missions"]["reason"], lo.REASON_NOTHING_REMAINING)

    def test_a_filed_entry_is_a_mention_and_a_none_finishes_it(self):
        rows = {row["domain"]: row for row in li.landmark_rows(
            {"missions": [{"domain": "missions", "none": True}]})}
        self.assertEqual(rows["missions"]["status"], "complete")

    def test_a_node_of_the_kind_on_the_graph_is_a_mention(self):
        graph = {"nodes": [{"node_id": "node:m", "event_kind": "mission",
                            "label": "Switzerland Zurich Mission"}]}
        self.assertEqual(lo.graph_mentioned_domains(graph), frozenset({"missions"}))

    def test_the_fold_reads_mentions_off_its_own_claims(self):
        claims = [{"event_mention": "Flew his mom out for his daughter's",
                   "subject_mention": "self",
                   "evidence": [{"quote": OWNER_BAPTISM_SHAPE}]}]
        nodes = [{"label": "Returned home from mission"}]
        self.assertEqual(tt.mentioned_landmark_domains(claims, nodes),
                         frozenset({"missions", "baptism"}))


class ALooseLifeEventKeepsItsCardTests(unittest.TestCase):

    def test_a_mission_and_a_baptism_inside_a_year_keep_their_card(self):
        for kind in ("mission", "baptism"):
            with self.subTest(kind=kind):
                self.assertTrue(twi.date_card_changes_something(
                    {"kind": "precision_gap", "event_kind": kind}, window=6))
        # ...and the freestanding anecdote still does not.
        self.assertFalse(twi.date_card_changes_something(
            {"kind": "precision_gap", "event_kind": "moment"}, window=6))


class AMissionIsAContainerTests(unittest.TestCase):
    """The containment rung asks one thing of a container's DATE: that its
    telling opens a span in the person's own words. A mission entry does."""

    def test_the_mission_entry_opens_a_stated_span(self):
        claims = lp.entry_claims("missions", li.validate_landmark(MISSION_ENTRY),
                                 source_ref={"source_id": "landmark:entry-mission",
                                             "revision": "sha256:" + "1" * 64,
                                             "source_path": "sources/landmarks/m.md"})
        span, open_ended = ec.span_from_claims(claims)
        self.assertIsNotNone(span)
        self.assertFalse(open_ended)
        self.assertEqual((span.earliest, span.latest), ("2000-08", "2002-06-06"))
        for label, start, end in STAYS_INSIDE:
            with self.subTest(stay=label):
                stay = chrono.from_dict({"best": f"{start}/{end}", "earliest": start,
                                         "latest": end, "granularity": "range"})
                self.assertTrue(ec.date_inside_span(stay, span))
        label, start, end = STAY_OUTSIDE
        berna = chrono.from_dict({"best": f"{start}/{end}", "earliest": start,
                                  "latest": end, "granularity": "range"})
        self.assertFalse(ec.date_inside_span(berna, span))


if __name__ == "__main__":
    unittest.main()
