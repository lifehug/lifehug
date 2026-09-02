"""Timeline Fix 07 D4 — one node, one question.

The founder's page asked both of these about the same node:

    When did San Diego begin?              (missing_anchor, start_date)
    When did San Diego — span — happen?    (precision_gap, date)

`_mint_work_item` merged only on an IDENTICAL work-item id, and the id is a
function of (kind, subject, event, requested_field) — so two derivation paths
reaching one node produced two rows competing with each other for the same
answer. The precedence table is an argument, not a preference: you cannot
refine a date you do not have, and you cannot date a person you cannot
identify.

Every test below FAILS on v261.

Synthetic data only; NEVER references ~/Workspace/dave.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "system"))
sys.path.insert(0, str(ROOT / "tests"))

import temporal_timeline as tt  # noqa: E402
import temporal_work_items as twi  # noqa: E402
from test_temporal_timeline import NOW, claim, index_of  # noqa: E402

BIRTH_ORIGIN_ID = twi.birth_origin_work_item_id()
PLACES = {"type": "place", "entities": [{"name": "San Diego", "slug": "san-diego"}]}


def duration_only():
    """"We were in San Diego four years" — a length with no start. It is both
    the node's missing anchor and its precision gap."""
    return claim(claim_type="duration", subject_mention="San Diego",
                 event_kind="span", temporal_value={"low": 4, "high": 4,
                                                    "unit": "years"},
                 quote="we were in San Diego four years", seed="sd")


def real_items(result):
    return [row for row in result.work_items
            if row["work_item_id"] != BIRTH_ORIGIN_ID]


class OneItemPerNode(unittest.TestCase):
    def test_precision_gap_yields_to_missing_anchor(self):
        result = tt.derive_calculated_timeline(index_of(duration_only()), now=NOW)
        rows = real_items(result)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["kind"], "missing_anchor")
        self.assertEqual(rows[0]["superseded_kinds"], ["precision_gap"])

    def test_the_survivor_absorbs_the_loser_s_evidence(self):
        result = tt.derive_calculated_timeline(index_of(duration_only()), now=NOW)
        row = real_items(result)[0]
        self.assertIn(duration_only()["claim_id"], row["claim_refs"])

    def test_the_one_question_is_a_sentence(self):
        result = tt.derive_calculated_timeline(
            index_of(duration_only()), roster_snapshot=PLACES, now=NOW)
        self.assertEqual(real_items(result)[0]["prompt_intent"],
                         "When did you move to San Diego?")

    def test_the_precedence_table_is_ordered_by_what_answers_what(self):
        """`place_ambiguous` (`timeline-rules:4`, Timeline Fix 05 §8.3) sits
        ABOVE `missing_anchor`: "which time in San Diego was this?" is strictly
        more answerable than "when did this happen?" about the same node, and
        answering it answers both — which is what this table means.

        Event identity I3 seats `possible_overmerge`/`same_event` just below
        `contradiction`: both are the substrate's own grouping guess meeting
        a disagreement, and an over-merge audit (an EXISTING bind) outranks a
        same-event pair (still a proposal nothing has committed to).

        E-L2a seats `tenure_ambiguous` immediately after `place_ambiguous`:
        it is the same question about an employer or a school rather than a
        place, so it answers exactly what its sibling answers and belongs at
        the same rung, one step down only so the order is total."""
        self.assertEqual(
            tt.WORK_ITEM_PRECEDENCE,
            ("identity_uncertain", "contradiction", "possible_overmerge",
             "same_event", "place_ambiguous", "tenure_ambiguous",
             "missing_anchor", "precision_gap"),
        )
        ranks = [tt._precedence(kind) for kind in tt.WORK_ITEM_PRECEDENCE]  # noqa: SLF001
        self.assertEqual(ranks, sorted(ranks))
        self.assertGreater(tt._precedence("something_new"),  # noqa: SLF001
                           tt._precedence("precision_gap"))  # noqa: SLF001


class TheSinkItself(unittest.TestCase):
    """Driven directly, because the derivation reaches only some orderings and
    the rule has to hold whichever kind arrives first."""

    def mint(self, sink, components, by_node, kind, *, field, intent):
        return tt._mint_work_item(  # noqa: SLF001
            sink, components, kind=kind, event_ref="node:sd", node_ref="node:sd",
            event_kind="span", subject_ref="place/san-diego", requested_field=field,
            prompt_intent=intent, claim_refs=[f"claim:{kind}"],
            by_node=by_node, diagnostics=[], now=NOW,
        )

    def test_a_lower_kind_arriving_second_is_absorbed(self):
        sink, components, by_node = {}, {}, {}
        first = self.mint(sink, components, by_node, "missing_anchor",
                          field="start_date", intent="When did you move to San Diego?")
        second = self.mint(sink, components, by_node, "precision_gap",
                           field="date", intent="When were you in San Diego?")
        self.assertEqual(first, second)
        self.assertEqual(list(sink), [first])
        self.assertEqual(sink[first]["superseded_kinds"], ["precision_gap"])
        self.assertEqual(sorted(sink[first]["claim_refs"]),
                         ["claim:missing_anchor", "claim:precision_gap"])

    def test_a_higher_kind_arriving_second_takes_the_seat(self):
        sink, components, by_node = {}, {}, {}
        first = self.mint(sink, components, by_node, "precision_gap",
                          field="date", intent="When were you in San Diego?")
        second = self.mint(sink, components, by_node, "missing_anchor",
                           field="start_date", intent="When did you move to San Diego?")
        self.assertNotEqual(first, second)
        self.assertEqual(list(sink), [second])
        self.assertEqual(sink[second]["kind"], "missing_anchor")
        self.assertEqual(sink[second]["superseded_kinds"], ["precision_gap"])
        self.assertEqual(sorted(sink[second]["claim_refs"]),
                         ["claim:missing_anchor", "claim:precision_gap"])

    def test_two_different_nodes_are_still_two_items(self):
        sink, components, by_node = {}, {}, {}
        self.mint(sink, components, by_node, "missing_anchor",
                  field="start_date", intent="When did you move to San Diego?")
        tt._mint_work_item(  # noqa: SLF001
            sink, components, kind="precision_gap", event_ref="node:mesa",
            node_ref="node:mesa", event_kind="span", subject_ref="place/mesa",
            requested_field="date", prompt_intent="When were you in Mesa?",
            by_node=by_node, diagnostics=[], now=NOW,
        )
        self.assertEqual(len(sink), 2)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
