"""Timeline Fix 07 D2 — no date question for a fact already answered.

The founder's page showed, at the same time:

    When was James's birth?          NO DATE YET
    20 March 1990 · James — birth · two claims disagree

Two items, two subjects — ``subject_ref: "James"`` (resolved, dated) and
``subject_ref: "unresolved:james s birth"`` (an anchor handle the binder never
looked up). To him that was one question asked twice, and the second copy was
false. Every ``anchor_unresolved`` handle now goes through the roster before it
is allowed to become a date question.

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

import identity_resolution as ident  # noqa: E402
import temporal_timeline as tt  # noqa: E402
import temporal_work_items as twi  # noqa: E402
from test_temporal_timeline import NOW, claim, index_of  # noqa: E402

ONE_JAMES = {"type": "person", "entities": [
    {"name": "James Taylor", "slug": "james-taylor", "aliases": ["James"]},
]}
TWO_JAMESES = {"type": "person", "entities": [
    {"name": "James Taylor", "slug": "james-taylor", "aliases": ["James"]},
    {"name": "James Rowe", "slug": "james-rowe", "aliases": ["James"]},
]}
BIRTH_ORIGIN_ID = twi.birth_origin_work_item_id()


def james_birth():
    return claim(claim_type="date", subject_mention="James", event_kind="birth",
                 temporal_value="1990-03-20", quote="James was born 20 March 1990",
                 seed="jb")


def something_after_it():
    return claim(claim_type="relative_order", subject_mention="the reunion",
                 event_kind="transition",
                 temporal_value={"relation": "after", "anchors": ["James's birth"]},
                 seed="rel")


def items(result, kind):
    return [row for row in result.work_items
            if row["kind"] == kind and row["work_item_id"] != BIRTH_ORIGIN_ID]


class TheHandleIsLookedUp(unittest.TestCase):
    def test_anchor_handle_resolving_to_a_dated_node_mints_nothing(self):
        result = tt.derive_calculated_timeline(
            index_of(james_birth(), something_after_it()),
            roster_snapshot=ONE_JAMES, now=NOW)
        self.assertEqual(items(result, "missing_anchor"), [])
        # v360 follow-up (owner, 2026-09-25) (`timeline-rules:23`,
        # `temporal_timeline.A_HANDLE_NAMING_A_CORNERSTONE_BINDS_TO_IT`): a
        # handle titled as a milestone of one roster person now binds while the
        # edges are built — earlier than the late lookup this test was written
        # for — so the reunion is PLACED after the birth rather than only
        # spared its card. Either way no date card, and the handle names him.
        rows = [row for row in result.diagnostics["findings"]
                if row.get("finding") == "anchor_resolved_late"]
        reunion = next(node for node in result.nodes
                       if node.get("event_kind") == "transition")
        if rows:
            self.assertEqual(rows[0]["anchor"], "James's birth")
            self.assertEqual(rows[0]["subject_ref"], "person/james-taylor")
        else:
            self.assertEqual(reunion["best_temporal_value"]["earliest"], "1990-03-20")

    def test_two_candidates_mint_identity_not_date(self):
        result = tt.derive_calculated_timeline(
            index_of(something_after_it()), roster_snapshot=TWO_JAMESES, now=NOW)
        self.assertEqual(items(result, "missing_anchor"), [])
        identity = items(result, "identity_uncertain")
        self.assertEqual(len(identity), 1)
        # v360 (owner, 2026-09-25): the identity card reads in the
        # owner's own terms now — see `compose_identity_uncertain_question`.
        # Neither candidate here has a roster `relationship`, so the reword
        # falls back to their plain names, sentence-cased mention, and a
        # trailing "someone else" option.
        self.assertEqual(identity[0]["prompt_intent"],
                         'Who is "James" here — James Taylor or James Rowe, '
                         'or someone else?')
        self.assertTrue(ident.is_unresolved_ref(identity[0]["subject_ref"]))

    def test_a_name_nobody_knows_still_asks_for_a_date(self):
        """The exclusion is "already answered", not "never ask" — a person we
        have not met yet is a real gap."""
        result = tt.derive_calculated_timeline(
            index_of(something_after_it()), roster_snapshot=(), now=NOW)
        anchors = items(result, "missing_anchor")
        self.assertEqual(len(anchors), 1)
        self.assertEqual(anchors[0]["prompt_intent"], "When was James's birth?")

    def test_an_undated_james_node_does_not_suppress_the_question(self):
        """The lookup requires a DATED node. A James on the roster with no
        birthday answers nothing, so the question survives."""
        undated = claim(claim_type="relative_order", subject_mention="James",
                        event_kind="birth",
                        temporal_value={"relation": "after", "anchors": ["the flood"]},
                        seed="ju")
        result = tt.derive_calculated_timeline(
            index_of(undated, something_after_it()),
            roster_snapshot=ONE_JAMES, now=NOW)
        self.assertTrue(items(result, "missing_anchor"))


class TheHandleParser(unittest.TestCase):
    def test_a_possessive_event_noun_is_stripped_to_the_name(self):
        self.assertEqual(tt._anchor_handle_subject("James's birth"),  # noqa: SLF001
                         ("James", "birth"))
        self.assertEqual(tt._anchor_handle_subject("my dad's graduation"),  # noqa: SLF001
                         ("my dad", "graduation"))
        self.assertEqual(tt._anchor_handle_subject("Grandma Rowe's funeral"),  # noqa: SLF001
                         ("Grandma Rowe", "death"))

    def test_a_bare_name_keeps_itself_and_names_no_event(self):
        self.assertEqual(tt._anchor_handle_subject("James"), ("James", ""))  # noqa: SLF001

    def test_a_clause_is_not_mistaken_for_a_name(self):
        subject, event = tt._anchor_handle_subject(  # noqa: SLF001
            "my dad graduated from college")
        self.assertEqual(subject, "my dad graduated from college")
        self.assertEqual(event, "")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
