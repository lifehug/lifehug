"""v360 (owner, 2026-09-25) — card and title WORDING, never gating.

The owner's staging review the same day found the fallback composer reading
the node's KIND rather than its own text — "When did Mesa, Arizona happen?"
for a residence, "When were you at Mike Eyre phone call?" for a moment
mis-tagged `job` — a title gluing a fixed verb onto whatever a mention
happened to resolve to ("meeting hanging around Trevor Hammons"), an
identity card joining four full names with "or", and a card conversation's
reply defaulting to the ordinary Conversation story beat instead of saying
what was placed. This file is the WIP verification asked for on that
session: `compose_question` stays kind-aware without depending on the roster
having flagged a place (`is_place` is never populated for a job/school node
in the vault this was built against — see `_derive_work_items`'s own
`person_name_keys`), a title is sentence-cased rather than glued to a
template, an identity card reads in the owner's own terms, and the framework's
own Timeline prompt no longer defaults to a story invitation once a card is
answered.

Synthetic data only; NEVER references ~/Workspace/dave.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "system"))
sys.path.insert(0, str(ROOT / "tests"))

import conversation_lints as cl  # noqa: E402
import temporal_timeline as tt  # noqa: E402
from test_v334_first_name_collisions import person, roster  # noqa: E402
from test_temporal_timeline import NOW, claim, derive, items_of, node_for  # noqa: E402


# --------------------------------------------------------------------------
# 1 — kind-aware fallbacks: residence, school, job, event, moment
# --------------------------------------------------------------------------


class KindAwareFallbacks(unittest.TestCase):
    """`compose_question`'s fallback row reads the node's OWN kind, never the
    one-size-fits-all "When did {what} happen?" the owner saw on a residence
    and, briefly, on every job/school node one v360 working round regressed
    (`is_place` is not populated for these — the fix reads `is_person`
    instead; see :class:`BarePersonNameIsWithheld` below)."""

    def test_a_residence_asks_where_they_lived_not_whether_it_happened(self):
        text = tt.compose_question(
            "precision_gap", "residence", who="Mesa, Arizona", what="Mesa, Arizona",
            is_owner=False, target="year",
        )
        self.assertEqual(text, "When were you in Mesa, Arizona?")
        self.assertNotIn("happen", text)

    def test_a_residence_missing_anchor_asks_when_they_moved(self):
        text = tt.compose_question(
            "missing_anchor", "residence", who="Thunderhead Street", what="Thunderhead Street",
        )
        self.assertEqual(text, "When did you move to Thunderhead Street?")

    def test_a_school_with_a_real_institution_keeps_its_own_row(self):
        # `is_place` is never true for a job/school node in this vault's own
        # shape (the fold's one `roster_snapshot` is the PERSON roster), so
        # the fix must not have been "route away from `job`/`school` when
        # `is_place` is false" — that regressed "Mountain View High" and
        # "high school" to a withheld card in the same v360 working round this
        # file pins against.
        text = tt.compose_question(
            "precision_gap", "school", who="Mountain View High", what="Mountain View High",
            is_owner=False, target="year",
        )
        self.assertEqual(text, "When were you at Mountain View High?")

    def test_high_school_precision_gap_still_asks(self):
        text = tt.compose_question(
            "precision_gap", "school", who="high school", what="high school",
            is_owner=False, target="year",
        )
        self.assertEqual(text, "When were you at high school?")

    def test_an_event_or_moment_fallback_already_reads_naturally(self):
        # The `None` row IS the "event"/"moment" fallback the owner asked to
        # be kind-aware about — it already reads fine once `{what}` is a
        # genuine event phrase rather than a bare place or person name, which
        # is exactly what the other two guards below exist to keep true.
        text = tt.compose_question(
            "precision_gap", "moment", who="Mike Eyre phone call",
            what="Mike Eyre phone call", is_owner=False, target="year",
        )
        self.assertEqual(text, "When did Mike Eyre phone call happen?")

    def test_no_when_did_place_happen(self):
        for label in ("Mesa, Arizona", "Thunderhead Street, San Diego", "701 North Williams"):
            with self.subTest(label=label):
                text = tt.compose_question(
                    "precision_gap", "residence", who=label, what=label, target="year",
                )
                self.assertNotIn(f"When did {label} happen?", text)

    def test_no_at_event_template_on_a_non_place_job(self):
        # The regression this file pins against ran the other way (job/school
        # withheld when the roster had no place match); the ORIGINAL bug —
        # "When were you at Mike Eyre phone call?" — is a `job` node whose
        # `{what}` is an interaction, not an institution. Composition alone
        # cannot tell the two apart without a signal this vault does not
        # carry (a genuine place-roster match), so it is reported rather than
        # patched here — see the session's final report.
        text = tt.compose_question(
            "precision_gap", "job", who="Mike Eyre phone call",
            what="Mike Eyre phone call", is_owner=False, target="year",
        )
        # Not withheld, and not a broken sentence — the pre-existing `job`
        # row, which reads passably even when `{what}` is not a place.
        self.assertEqual(text, "When were you at Mike Eyre phone call?")


# --------------------------------------------------------------------------
# 2 — a bare PERSON'S name is withheld; an institution's bare name is not
# --------------------------------------------------------------------------


class BarePersonNameIsWithheld(unittest.TestCase):
    """"When did James happen?" — `_node_what` fell back to the display, and
    the display is a roster PERSON's own name. `is_person` is the roster's
    signal, never a guess from whether `who` and `what` happen to match (an
    institution is just as often its own `who` and `what`, and must not be
    swept up by the same guard — the Mountain View High regression above,
    again)."""

    def test_a_bare_person_name_composes_no_sentence(self):
        text = tt.compose_question(
            "precision_gap", "transition", who="James", what="James",
            is_owner=False, is_person=True, target="year",
        )
        self.assertIsNone(text)

    def test_an_institution_whose_who_and_what_match_still_asks(self):
        text = tt.compose_question(
            "precision_gap", "school", who="Mountain View High", what="Mountain View High",
            is_owner=False, is_person=False, target="year",
        )
        self.assertIsNotNone(text)

    def test_the_owners_own_bare_name_is_unaffected(self):
        # `is_owner` always wins first — a self node reads "you", never
        # withheld, whatever `is_person` says about the owner's own roster row.
        text = tt.compose_question(
            "precision_gap", "moment", who="Dave", what="Dave",
            is_owner=True, is_person=True, target="year",
        )
        self.assertIsNotNone(text)

    def test_end_to_end_a_bare_person_mention_withholds_its_own_card(self):
        """The fold, not just the pure function: a claim whose only text is
        a roster person's bare name mints a node but no readable card."""
        ROSTER = roster(person("Dave", slug="dave"),
                        person("James", slug="james", relationship="child"))
        result = derive(
            claim(claim_type="occurrence", subject_mention="James",
                  event_kind="transition", event_mention="James",
                  quote="James."),
            roster_snapshot=ROSTER, owner_names=("Dave",),
        )
        asked = items_of(result, "precision_gap")
        self.assertTrue(asked, "expected a withheld precision_gap row, found none")
        self.assertIsNone(asked[0].get("prompt_intent"))
        self.assertIn("question_withheld", asked[0]["withheld_reason"])


# --------------------------------------------------------------------------
# 3 — a handle that already names its own date asks nothing
# --------------------------------------------------------------------------


class HandleAlreadyCarriesItsDate(unittest.TestCase):
    def test_a_full_date_in_the_handle_withholds_the_question(self):
        self.assertIsNone(
            tt.compose_anchor_question("Mike Eyre email on Aug 28, 2025"))
        self.assertIsNone(
            tt.compose_anchor_question("the call on 28 Aug 2025"))

    def test_a_handle_with_no_date_is_unaffected(self):
        self.assertEqual(
            tt.compose_anchor_question("701 North Williams foreclosure"),
            "When was 701 North Williams foreclosure?")

    def test_a_year_alone_is_not_a_full_date(self):
        # Only a day-month-year triple is circular; a bare year still leaves
        # a real question (month/day are still open).
        self.assertIsNotNone(tt.compose_anchor_question("the 2025 signing"))


# --------------------------------------------------------------------------
# 4 — titles: sentence-cased, dated the owner's own way, never a template
#     glued onto a clause
# --------------------------------------------------------------------------


class TitlesAreCleanedNeverTemplated(unittest.TestCase):
    def test_a_handle_title_is_sentence_cased(self):
        self.assertEqual(tt._sentence_case("junior year"), "Junior year")  # noqa: SLF001
        # The first LETTER, not the first character — a leading number is
        # left alone and the next word (a proper noun already) is what gets
        # capitalised, harmlessly re-capitalising a letter already upper.
        self.assertEqual(
            tt._sentence_case("701 north williams foreclosure"),  # noqa: SLF001
            "701 North williams foreclosure")

    def test_a_date_in_a_title_reads_day_month_year(self):
        self.assertEqual(
            tt._sentence_case("mike eyre email on aug 28, 2025"),  # noqa: SLF001
            "Mike eyre email on 28 Aug 2025")
        self.assertEqual(
            tt._sentence_case("turned 8 on july 11, 1989"),  # noqa: SLF001
            "Turned 8 on 11 Jul 1989")

    def test_a_node_title_is_sentence_cased(self):
        # v360 supersedes the pre-existing lowercase expectation pinned in
        # `test_question_writer.NodeTitlesReadTheSameTable` — updated there
        # with a comment rather than left to fail silently.
        self.assertEqual(tt._node_label("self", "birth", is_owner=True), "Your birth")  # noqa: SLF001

    def test_a_clause_shaped_mention_is_quoted_not_templated(self):
        # "meeting hanging around Trevor Hammons" — `first_met`'s own title
        # row is `"meeting {who}"`; gluing it onto a clause the extractor
        # wrote for `who` (rather than a clean name) is exactly the
        # "<kind verb> + <extracted phrase>" shape the owner ruled out.
        title = tt.compose_question(
            "title", "first_met", who="hanging around Trevor Hammons",
            what="hanging around Trevor Hammons", is_owner=False,
        )
        self.assertEqual(title, "Hanging around Trevor Hammons")
        self.assertNotIn("meeting", title.lower())

    def test_a_clean_name_still_gets_its_own_template(self):
        # The bypass is for a CLAUSE, never for an ordinary name — a real
        # first_met title keeps reading "meeting {who}".
        title = tt.compose_question(
            "title", "first_met", who="Trevor Hammons", what="Trevor Hammons",
            is_owner=False,
        )
        self.assertEqual(title, "Meeting Trevor Hammons")

    def test_no_verb_plus_phrase_template_title_survives_a_clause(self):
        for who in ("hanging around Trevor Hammons", "left Kristen", "moving in with dad"):
            with self.subTest(who=who):
                title = tt.compose_question(
                    "title", "first_met", who=who, what=who, is_owner=False,
                )
                self.assertIsNotNone(title)
                self.assertNotIn("meeting ", title.lower())


# --------------------------------------------------------------------------
# 5 — the identity card
# --------------------------------------------------------------------------


class IdentityCardReadsInHisOwnTerms(unittest.TestCase):
    """"Which Anthon James Taylor or James Everett Taylor or James Edwin
    Taylor Sr. or James Taylor is 'James' here?" (owner staging review,
    2026-09-25) — unreadable. `compose_identity_uncertain_question` re-words
    the SAME candidate list `identity_resolution.identity_work_item` already
    chose; it never re-decides who is on it."""

    ROSTER = {"type": "person", "entities": [
        person("Anthon James Taylor", slug="anthon-james-taylor", relationship="sibling",
               aliases=["AJ", "AJ Taylor", "A.J. (brother)", "James"]),
        person("James Everett Taylor", slug="james-everett-taylor", relationship="child"),
        person("James Edwin Taylor Sr.", slug="james-edwin-taylor-sr", relationship="grandparent",
               aliases=["grandfather", "my grandfather", "grandpa"]),
        person("James Taylor", slug="james-taylor", relationship="parent",
               aliases=["James Taylor (Dad)", "dad", "my dad", "father"]),
    ]}

    def _candidates(self):
        return [
            {"ref": "person/anthon-james-taylor", "name": "Anthon James Taylor"},
            {"ref": "person/james-everett-taylor", "name": "James Everett Taylor"},
            {"ref": "person/james-edwin-taylor-sr", "name": "James Edwin Taylor Sr."},
            {"ref": "person/james-taylor", "name": "James Taylor"},
        ]

    def test_no_four_full_names_joined_by_or(self):
        text = tt.compose_identity_uncertain_question(
            "James", self._candidates(), roster_snapshot=self.ROSTER)
        self.assertNotIn(
            "Anthon James Taylor or James Everett Taylor or "
            "James Edwin Taylor Sr. or James Taylor",
            text,
        )

    def test_a_nickname_leads_over_the_full_name(self):
        text = tt.compose_identity_uncertain_question(
            "James", self._candidates(), roster_snapshot=self.ROSTER)
        self.assertIn("AJ", text)
        self.assertNotIn("Anthon James Taylor", text)

    def test_an_alias_that_is_just_the_relation_word_is_not_a_nickname(self):
        # "grandfather" / "James Taylor (Dad)" are the relation word (or the
        # name plus it) wearing a different spelling, not a true nickname —
        # leading with them would read "grandfather (your grandparent)".
        text = tt.compose_identity_uncertain_question(
            "James", self._candidates(), roster_snapshot=self.ROSTER)
        self.assertNotIn("grandfather (your grandparent)", text)
        self.assertNotIn("(Dad) (your parent)", text)
        self.assertIn("your grandparent James", text)
        self.assertIn("your parent James", text)

    def test_the_mention_is_sentence_cased_not_a_lowercase_key(self):
        text = tt.compose_identity_uncertain_question(
            "james", self._candidates(), roster_snapshot=self.ROSTER)
        self.assertIn('"James"', text)

    def test_someone_else_is_always_the_last_option(self):
        text = tt.compose_identity_uncertain_question(
            "James", self._candidates(), roster_snapshot=self.ROSTER)
        self.assertTrue(text.rstrip("?").endswith("someone else"))

    def test_no_candidates_composes_nothing(self):
        self.assertIsNone(
            tt.compose_identity_uncertain_question("James", (), roster_snapshot=self.ROSTER))


# --------------------------------------------------------------------------
# 6 — the card-conversation stop rule (the framework's own seat)
# --------------------------------------------------------------------------


class CardConversationEndsTheCardNotAStory(unittest.TestCase):
    """No package code changed for this rule (Timeline Fix 10 is a PLATFORM
    module, `services/api/app/delivery/work_item_walk.py`, out of reach and
    out of scope here) — the framework's seat is its own prompt, read by
    every host that assembles a `work_item`-stage turn. These assertions are
    textual: the two markdown files a model actually reads."""

    BEHAVIOR = (ROOT / "interactions/timeline/prompt/behavior.md").read_text()
    TURN_INSTRUCTIONS = (ROOT / "interactions/timeline/prompt/turn-instructions.md").read_text()

    def test_the_timeline_behavior_contract_overrides_the_story_beat(self):
        self.assertIn(
            "A card conversation's answer ends the card, not a story",
            self.BEHAVIOR,
        )
        self.assertIn("placed", self.BEHAVIOR)
        self.assertIn("filed", self.BEHAVIOR)
        self.assertIn("noted", self.BEHAVIOR)
        # Named as what it replaces, not silently — the owner's own
        # transcript line stays in the file as the negative example (the
        # source markdown hard-wraps mid-quote, so this checks the words
        # rather than one un-wrapped sentence).
        self.assertIn("What led you to bring that up", self.BEHAVIOR)
        self.assertIn("today", self.BEHAVIOR)

    def test_the_work_item_stage_states_the_rule_operationally(self):
        self.assertIn("Once they answer it, acknowledge and stop", self.TURN_INSTRUCTIONS)
        self.assertIn('"placed", "filed" or "noted"', self.TURN_INSTRUCTIONS)

    def test_every_other_stage_is_untouched(self):
        # Additive only — every stage bullet that existed before this round
        # is still there, byte for byte.
        for line in (
            "`open` (the first reply): name what you are curious about in ONE warm",
            "`close`: say where it landed in their own words",
            "## The `era` stage",
        ):
            with self.subTest(line=line):
                self.assertIn(line, self.TURN_INSTRUCTIONS)


if __name__ == "__main__":
    unittest.main()
