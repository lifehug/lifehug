"""Timeline Fix 07 D3/D5 — the question writer (lifehug-platform#761).

The owner read his own Timeline on 2026-08-29 and found these:

    When did speaker's mission — transition — happen?
    When did San Diego — span — happen?
    Do you know the year for I — span?
    When did Childhood end — before or after First big paycheck arrives by mail?

Three composers were printing ``{node.label} — {event_kind}`` into a sentence.
``label`` is whatever the extractor wrote — its third-person handle for the
OWNER, or a bare subject string — and ``event_kind`` is an internal node kind.
The owner's ruling: *"whatever's writing these questions needs to be fixed."*

Every test below FAILS on v261 (the outputs are quoted in the PR body).

Synthetic data only; NEVER references ~/Workspace/dave.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "system"))

import conversation_lints as cl  # noqa: E402
import temporal_projection as tp  # noqa: E402
import temporal_timeline as tt  # noqa: E402
import timeline as tl  # noqa: E402

#: The five shapes the founder's own nine work items had, as inputs. Names are
#: synthetic; only the SHAPE is the founder's.
LIVE_SHAPES = (
    ("precision_gap", "transition", "speaker's mission"),
    ("precision_gap", "span", "San Diego"),
    ("precision_gap", "span", "I"),
    ("precision_gap", "move", "move to San Diego"),
    ("precision_gap_coarse", "transition", "Big Brother dynamic flip"),
    ("missing_anchor", "span", "San Diego"),
    ("missing_anchor", "birth", "James Taylor"),
    ("contradiction", "birth", "James Taylor"),
)


class EventKindNeverPrinted(unittest.TestCase):
    """D3, the rule that makes the whole class impossible."""

    def test_event_kind_never_printed(self):
        for item_kind, event_kind, what in LIVE_SHAPES:
            with self.subTest(shape=(item_kind, event_kind, what)):
                text = tt.compose_question(
                    item_kind, event_kind, who=what, what=what,
                    target="year", readings="1984 and 1986",
                )
                if text is None:
                    continue
                self.assertNotIn(f" — {tt._event_words(event_kind)}", text)  # noqa: SLF001
                self.assertNotRegex(text, r" — \w+ — happen\?")
                self.assertEqual(cl.lint_question(text), [])

    def test_every_kind_row_in_the_table_composes_a_sentence(self):
        """A row that formats to nothing is a silent template leak waiting for
        the one event kind nobody tested."""
        for event_kind in list(tt.KIND_SENTENCES) + ["job", "military", "loss"]:
            if event_kind in tt.UNASKABLE_EVENT_KINDS:
                continue
            for item_kind in ("missing_anchor", "precision_gap",
                              "precision_gap_coarse", "contradiction"):
                with self.subTest(event_kind=event_kind, item_kind=item_kind):
                    text = tt.compose_question(
                        item_kind, event_kind, who="Jackie Rowe", what="the farmhouse",
                        target="year", readings="1984 and 1986",
                    )
                    self.assertIsNotNone(text)
                    self.assertEqual(cl.lint_question(text), [])


class OwnerReferences(unittest.TestCase):
    """D3 — the extractor writes about the owner in the third person."""

    def test_owner_references_are_second_person(self):
        self.assertEqual(
            tt.compose_question("precision_gap", "transition", what="speaker's mission"),
            "When did your mission happen?",
        )
        self.assertEqual(tt.owner_rewrite("Author's birth"), "your birth")
        self.assertEqual(tt.owner_rewrite("my dad graduated"), "your dad graduated")
        self.assertEqual(tt.owner_rewrite("I"), "you")

    def test_a_bare_pronoun_subject_is_withheld_not_rephrased(self):
        """"When did you happen?" is not a question. The node has no human
        text yet, and saying so is the honest outcome."""
        self.assertIsNone(tt.compose_question("precision_gap", "span", what="I"))
        self.assertIsNone(
            tt.compose_question("precision_gap_coarse", "span", what="the speaker",
                                target="year"))

    def test_the_rewrite_never_eats_an_ordinary_word(self):
        for text in ("Iris", "Imelda's wedding", "the Author Society",
                     "my Mystic Lake summer"):
            with self.subTest(text=text):
                rewritten = tt.owner_rewrite(text)
                self.assertNotIn("you Ris", rewritten)
        self.assertEqual(tt.owner_rewrite("Iris"), "Iris")
        self.assertEqual(tt.owner_rewrite("Imelda's wedding"), "Imelda's wedding")


class TheRefusingLint(unittest.TestCase):
    """D3's backstop. Prompt prose is not certifiable; a deterministic refusal
    is (ADR 0028's audit finding, applied to a deterministic writer)."""

    def test_lint_question_refuses_template_leak(self):
        for text in ("When did I — span — happen?",
                     "When did San Diego — span — happen?",
                     "Do you know the year for Big Brother dynamic flip — transition?",
                     "When was speaker's mission?",
                     "Two dates are claimed for James — birth. Which is right?"):
            with self.subTest(text=text):
                findings = cl.lint_question(text)
                self.assertTrue(findings)
                self.assertEqual(findings[0]["lint"], cl.QUESTION_TEMPLATE_LEAK)
                self.assertTrue(findings[0]["detail"])
                self.assertEqual(len(findings[0]["span"]), 2)

    def test_lint_question_passes_a_sentence_a_person_would_say(self):
        for text in ("When did you move to San Diego?",
                     "When were you in San Diego?",
                     "When did your mission happen?",
                     "You mentioned your dad graduated from college — when was that?",
                     "Two dates are claimed for James Taylor's birth — 20 March 1990 "
                     "and 10 May 2013. Which is right?",
                     "These cannot all be in the order they were given: the move, "
                     "the wedding"):
            with self.subTest(text=text):
                self.assertEqual(cl.lint_question(text), [])


class WithheldIsARecord(unittest.TestCase):
    """A question that cannot be phrased is a diagnostic, never a template."""

    def test_withheld_item_has_no_prompt_intent_and_a_diagnostic(self):
        items, components, diagnostics = {}, {}, []
        key = tt._mint_work_item(  # noqa: SLF001
            items, components,
            kind="precision_gap",
            event_ref="node:x", node_ref="node:x", event_kind="span",
            subject_ref="self", requested_field="date",
            prompt_intent=None,
            by_node={}, diagnostics=diagnostics, now="2026-08-29T00:00:00Z",
        )
        self.assertTrue(key)
        self.assertIsNone(items[key].get("prompt_intent"))
        self.assertIn("question_withheld", items[key]["withheld_reason"])
        self.assertEqual([row["finding"] for row in diagnostics], ["question_withheld"])
        self.assertEqual(diagnostics[0]["work_item_id"], key)

    def test_a_hand_written_intent_that_leaks_is_refused_too(self):
        items, components, diagnostics = {}, {}, []
        key = tt._mint_work_item(  # noqa: SLF001
            items, components,
            kind="precision_gap",
            event_ref="node:y", node_ref="node:y", event_kind="span",
            subject_ref="self", requested_field="date",
            prompt_intent="When did San Diego — span — happen?",
            by_node={}, diagnostics=diagnostics, now="2026-08-29T00:00:00Z",
        )
        self.assertIsNone(items[key].get("prompt_intent"))
        self.assertIn(cl.QUESTION_TEMPLATE_LEAK, items[key]["withheld_reason"])
        self.assertEqual([row["finding"] for row in diagnostics], ["question_withheld"])


class NodeTitlesReadTheSameTable(unittest.TestCase):
    """`_node_label` was `f"{display} — {kind}"` — "I — span", "birth — birth"
    on the founder's own page. Title and question are now one table, so they
    cannot describe one node two ways."""

    def test_a_node_title_never_carries_the_kind(self):
        self.assertEqual(tt._node_label("San Diego", "span"), "San Diego")  # noqa: SLF001
        self.assertEqual(
            tt._node_label("James Taylor", "birth"), "James Taylor's birth")  # noqa: SLF001
        self.assertEqual(tt._node_label("self", "birth", is_owner=True),  # noqa: SLF001
                         "your birth")
        self.assertNotIn(" — ", tt._node_label("I", "span"))  # noqa: SLF001


class AgeFramesAreNeverAsked(unittest.TestCase):
    """D5 — the owner's 14:21 staging screenshot. An age frame's bounds are
    arithmetic off the birth origin (ADR 0030): the frames ARE the coordinate
    system, and a coordinate system is not asked about itself."""

    def test_no_question_is_ever_composed_about_an_age_frame(self):
        for item_kind in ("missing_anchor", "precision_gap",
                          "precision_gap_coarse", "contradiction", "title"):
            with self.subTest(item_kind=item_kind):
                self.assertIsNone(tt.compose_question(
                    item_kind, tp.AGE_FRAME_EVENT_KIND, what="Childhood",
                    who="Childhood", target="year", readings="1981 and 1994"))

    def test_the_unaskable_set_is_the_frame_kind(self):
        self.assertIn(tp.AGE_FRAME_EVENT_KIND, tt.UNASKABLE_EVENT_KINDS)
        self.assertNotIn(tp.NAMED_ERA_EVENT_KIND, tt.UNASKABLE_EVENT_KINDS)


class AnchorHandleSentences(unittest.TestCase):
    """Free text nobody has resolved yet still has to read as a question."""

    def test_a_clause_is_quoted_back_never_conjugated(self):
        self.assertEqual(
            tt.compose_anchor_question("my dad graduated from college"),
            "You mentioned your dad graduated from college — when was that?",
        )

    def test_a_noun_phrase_is_asked_directly(self):
        self.assertEqual(tt.compose_anchor_question("the Switzerland mission"),
                         "When was the Switzerland mission?")

    def test_a_handle_with_no_subject_in_it_is_withheld(self):
        for text in ("", "I", "the speaker", "span"):
            with self.subTest(text=text):
                self.assertIsNone(tt.compose_anchor_question(text))



class TheLegacyUnknownsList(unittest.TestCase):
    """D5 on the surface the owner actually photographed at 14:21 on
    2026-08-29: `timeline.unknowns`' band-order list. The legacy
    `state/entity_rosters/period.json` still names the age frames as ordinary
    periods, which is exactly how "When did Childhood end — before or after
    First big paycheck arrives by mail? could be 1981-2026" was minted."""

    BIRTH = {"best": "1981-07-11", "earliest": "1981-07-11", "latest": "1981-07-11",
             "granularity": "day", "confidence": "certain", "basis": "stated"}

    def data(self):
        return {
            "anchors": {"birth": {"label": "when you were born", "kind": "birth",
                                  "date": self.BIRTH}},
            "periods": [
                {"slug": "childhood", "name": "Childhood", "date": None},
                {"slug": "my-20s", "name": "My 20s", "date": None},
                {"slug": "the-mission", "name": "the Mission", "date": None},
            ],
            "event_lineup": {}, "unplaced_events": [], "bands": [],
            "global_gaps": [], "gaps_by_period": {},
        }

    def rows(self):
        return {row["key"]: row for row in tl.unknowns(self.data(), {})}

    def test_no_age_frame_boundary_is_ever_asked_about(self):
        rows = self.rows()
        self.assertNotIn("period_bound:childhood", rows)
        self.assertNotIn("period_bound:my-20s", rows)

    def test_a_named_era_still_is(self):
        """The exclusion is frames, not eras. "the Mission" is somebody's own
        interpretation and its bounds are theirs to give."""
        self.assertIn("period_bound:the-mission", self.rows())

    def test_a_whole_life_range_reads_undated(self):
        """"could be 1981-2026" is the life span — it says only "sometime
        while you were alive", which is what undated already means."""
        row = self.rows()["period_bound:the-mission"]
        self.assertEqual(row["years"], [1981, tl._now_year()])  # noqa: SLF001
        self.assertTrue(row["undated_range"])

    def test_a_real_range_is_not_stamped_undated(self):
        payload = self.data()
        payload["periods"].append(
            {"slug": "the-yucaipa-years", "name": "the Yucaipa years", "date": None})
        payload["bands"] = [{"ref": "the-yucaipa-years", "periods": ["the-yucaipa-years"],
                             "date": {"best": "1995/2001", "earliest": "1995",
                                      "latest": "2001", "granularity": "range",
                                      "confidence": "certain", "basis": "stated"},
                             "places": []}]
        rows = {row["key"]: row for row in tl.unknowns(payload, {})}
        row = rows["period_bound:the-yucaipa-years"]
        self.assertEqual(row["years"], [1995, 2001])
        self.assertNotIn("undated_range", row)

    def test_range_is_whole_life_is_one_definition(self):
        self.assertTrue(tl.range_is_whole_life([1981, 2026], (1981, 2026)))
        self.assertFalse(tl.range_is_whole_life([1981, 2000], (1981, 2026)))
        self.assertFalse(tl.range_is_whole_life([1981, 2026], None))
        self.assertFalse(tl.range_is_whole_life(None, (1981, 2026)))

if __name__ == "__main__":  # pragma: no cover
    unittest.main()
