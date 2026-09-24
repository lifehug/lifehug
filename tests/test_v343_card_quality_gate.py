"""v343 — a card is asked only when a person could answer it.

The owner's staging review, 2026-09-24, found four real cards the timeline
work-item pipeline minted with no quality bar at all — the question-candidate
flow has ``question_judgment``; the timeline work-item flow never did:

* *"When was they?"* — a `general_listener` claim over the owner's one-line
  answer to a mission card ("19-21 years old"), ``subject_mention: "they"``,
  ``confidence: 0.0``, no ``event_mention``. It should never have minted a
  node, let alone a card.
* *"When did Harvey arriving happen?"* — a bare gerund phrase ("Harvey
  arriving") dropped into the fallback ``"When did {what} happen?"``
  template. Ungrammatical; the real fix (folding it onto Harvey's birth) is
  a different PR, so only the wording is fixed here.
* *"Which James or Anthon James Taylor is 'James' here?"* /
  *"Which Dave or Kids is 'Dave' here?"* — the roster held a `maps_to_focus`
  alias row (`james` -> `anthon-james-taylor`) as if it were a second person,
  and a collective/role row ("Kids") rode along as a candidate for the
  owner's own first name via an alias ("Dave's kids") that merely starts with
  it. The genuinely distinct second James — the owner's son, James Everett
  Taylor — was never even offered.

The rule, built in the smallest right places, ONE definition each:

1. **No node from an empty claim** (:func:`temporal_timeline._claim_is_empty`,
   read from ``_group_claims``). A claim whose only label is a pronoun or a
   placeholder (`landmarks_interaction.EMPTY_SUBJECT_LABELS` — this module's
   existing `PLACEHOLDER_LABELS` plus a new `PRONOUN_LABELS`) AND whose
   ``confidence`` is exactly ``0.0`` mints no node and no work item — both
   signals together, never either alone: ``confidence: 0.0`` is
   `temporal_claims.unit_score`'s own default for "never stated", not a
   marker reserved for "found nothing worth trusting", and gating on it
   alone refused a node to ordinary claims across the suite that simply
   never set it (`tests/test_eras_e3.py`'s own graduation claim among them —
   SEEN failing this way first). The claim itself is never dropped from the
   substrate — only refused a node.
2. **Prompt grammar** (:func:`temporal_timeline._is_gerund_phrase`, read from
   :func:`temporal_timeline.compose_question`). A bare SUBJECT + PARTICIPLE
   ``{what}`` reads ``"When was {what}?"`` instead of the fallback row's
   ``"When did {what} happen?"``. A real ``-ing`` event NOUN ("the wedding")
   is excluded by name and is unaffected.
3. **Identity candidates.** `identity_resolution.roster_index` drops a
   `maps_to_focus` row entirely (it is a duplicate, never a second identity)
   and excludes a collective/role row (`entity_roster.ROLE_WORDS`) from the
   given-name census — its own exact spelling still resolves. And
   `identity_resolution.identity_work_item` never offers the OWNER as a
   candidate for the owner's own given name (`owner_refs`); fewer than two
   real candidates after that mints nothing.
4. `temporal_timeline.CALCULATION_RULE_VERSION` moves (to ``timeline-rules:13``
   at v343; the assertion below pins whatever the LIVE value is, which later
   releases move on from)
   — the same claims now calculate to a different node set and a different
   work-item set for claims nobody edited, exactly what moves that number.
   v345 took ``:14`` and v346 ``:15`` on the same day; the number is a
   monotonic marker that the rules moved, never a name for one release.

Every negative below was run against a build with its guard removed and SEEN
failing first. Synthetic data only; NEVER references ~/Workspace/dave.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "system"))
sys.path.insert(0, str(ROOT / "tests"))

import conversation_lints as cl  # noqa: E402
import entity_roster as er  # noqa: E402
import identity_resolution as ir  # noqa: E402
import landmarks_interaction as li  # noqa: E402
import temporal_timeline as tt  # noqa: E402
from test_v334_first_name_collisions import person, roster  # noqa: E402
from test_v340_apply_keeps_placements import (  # noqa: E402
    NOW,
    claim,
    index_of,
    value,
)

EVIDENCE = "claim:" + "e" * 24


# --------------------------------------------------------------------------
# Rule 1 — no node from an empty claim
# --------------------------------------------------------------------------


class ClaimEmptinessTests(unittest.TestCase):
    """Direct tests of the one gate function, then the fold around it."""

    def test_confidence_zero_plus_a_pronoun_label_is_empty(self):
        # The owner's own incident, shape-for-shape: BOTH signals together.
        row = claim(claim_type="occurrence", subject_mention="they",
                    event_kind="span", confidence=0.0, source="conversation:msg-a")
        self.assertTrue(tt._claim_is_empty(row))

    def test_confidence_zero_plus_a_placeholder_label_is_empty(self):
        row = claim(claim_type="occurrence", subject_mention="someone",
                    event_kind="span", confidence=0.0, source="conversation:msg-c")
        self.assertTrue(tt._claim_is_empty(row))

    def test_confidence_zero_alone_with_a_real_label_is_not_empty(self):
        # REGRESSION GUARD. `confidence: 0.0` is `unit_score`'s own default
        # for "never stated" (`None` in, `0.0` out) — not a signal reserved
        # for "found nothing worth trusting". Era-membership claims built
        # with `subject_mention: "me"` and a real `temporal_value` carry no
        # `confidence` key at all and are exactly as real as one scored 0.9;
        # an OR here refused `tests/test_eras_e3.py`'s own graduation claim a
        # node (SEEN failing this way first — the earlier v343 draft used OR).
        row = claim(claim_type="occurrence", subject_mention="Harvey",
                    event_kind="span", event_mention="Harvey's visit",
                    confidence=0.0, source="conversation:msg-a2")
        self.assertFalse(tt._claim_is_empty(row))

    def test_a_bare_pronoun_label_alone_at_full_confidence_is_not_empty(self):
        # A pronoun label alone, at real confidence, is not enough either —
        # both signals together are what the owner's incident actually was.
        row = claim(claim_type="occurrence", subject_mention="they",
                    event_kind="span", confidence=0.9, source="conversation:msg-b")
        self.assertFalse(tt._claim_is_empty(row))

    def test_a_placeholder_label_alone_at_full_confidence_is_not_empty(self):
        row = claim(claim_type="occurrence", subject_mention="someone",
                    event_kind="span", confidence=0.9, source="conversation:msg-c2")
        self.assertFalse(tt._claim_is_empty(row))

    def test_a_pronoun_inside_a_real_sentence_is_not_a_bare_label(self):
        # "they built the shed" still names a real subject; only a BARE
        # pronoun/placeholder label is refused (whole-body casefold only).
        row = claim(claim_type="occurrence", subject_mention="they",
                    event_kind="span", event_mention="they built the shed",
                    confidence=0.9, source="conversation:msg-d")
        self.assertFalse(tt._claim_is_empty(row))

    def test_a_real_claim_is_not_empty(self):
        row = claim(claim_type="occurrence", subject_mention="Harvey",
                    event_kind="span", event_mention="Harvey's visit",
                    confidence=0.9, source="conversation:msg-e")
        self.assertFalse(tt._claim_is_empty(row))

    def test_you_is_not_a_pronoun_label(self):
        # "you" is the CORRECT composed subject of an owner-directed
        # question; it is deliberately absent from PRONOUN_LABELS.
        self.assertNotIn("you", li.PRONOUN_LABELS)

    def test_self_i_and_me_are_not_pronoun_labels(self):
        # These are the ORDINARY, correct way a raw claim's subject_mention
        # names the OWNER (`identity_resolution.OWNER_SUBJECT_MENTIONS`) —
        # "I went bankrupt at 26" is subject_mention "self" with no
        # event_mention, and a real claim, not an empty one.
        for word in ("self", "i", "me"):
            with self.subTest(word=word):
                self.assertNotIn(word, li.PRONOUN_LABELS)

    def test_a_bare_self_claim_with_no_event_mention_is_not_empty(self):
        row = claim(claim_type="occurrence", subject_mention="self",
                    event_kind="moment", confidence=0.9,
                    source="conversation:msg-self")
        self.assertFalse(tt._claim_is_empty(row))


class NoNodeFromAnEmptyClaimFoldTests(unittest.TestCase):
    """The owner's own incident, reproduced as a fold."""

    def derive(self, claims):
        return tt.derive_calculated_timeline(index_of(claims), now=NOW)

    def test_the_theys_claim_mints_no_node_or_card(self):
        # The owner's own claim, shape-for-shape: a general-listener claim
        # over his one-line mission answer, no event_mention, confidence 0.0.
        claims = [
            claim(claim_type="occurrence", subject_mention="they", event_kind="span",
                  confidence=0.0, source="conversation:msg-mission-answer",
                  extractor_version="general_listener/schema:1/model:x",
                  quote="19-21 years old"),
        ]
        result = self.derive(claims)
        self.assertEqual(result.nodes, ())
        self.assertFalse(
            [w for w in result.work_items if w.get("kind") == "precision_gap"]
        )

    def test_the_claim_itself_is_not_touched_only_refused_a_node(self):
        # This module never mutates or drops the claim — it is the caller's
        # own active_index, handed back unexamined by the fold.
        claims = [
            claim(claim_type="occurrence", subject_mention="they", event_kind="span",
                  confidence=0.0, source="conversation:msg-mission-answer",
                  quote="19-21 years old"),
        ]
        before = list(claims)
        self.derive(claims)
        self.assertEqual(claims, before)

    def test_an_empty_claim_does_not_suppress_the_same_nodes_other_claims(self):
        # Both claims resolved to the same subject ref so both reach the
        # SAME node's group; the first is empty on its own terms (a bare
        # pronoun label, confidence 0.0) and must not take the node's real
        # claim down with it.
        claims = [
            claim(claim_type="occurrence", subject_mention="they",
                  subject_ref="person/harvey", event_kind="span",
                  confidence=0.0, source="conversation:msg-harvey-empty",
                  quote="not sure"),
            claim(claim_type="date", subject_mention="Harvey",
                  subject_ref="person/harvey", event_kind="span",
                  event_mention="Harvey's visit", source="conversation:msg-harvey-real",
                  temporal_value=value("2019"), quote="Harvey visited in 2019."),
        ]
        result = self.derive(claims)
        self.assertEqual(len(result.nodes), 1)
        self.assertEqual(result.nodes[0]["best_temporal_value"]["best"], "2019")

    def test_a_participation_stays_own_identity_claim_is_exempt(self):
        # A landmark participation entry's identity claim asserts the stay
        # happened, not what to call it — a zero/absent confidence there is
        # by design (see `_claim_is_empty`'s own docstring) and must still
        # reach the group `_group_claims` seeded for it.
        row = {
            "claim_id": "claim:" + "f" * 24, "claim_type": "identity",
            "subject_mention": "Harvey", "confidence": 0.0,
        }

        class _StubParticipation:
            def node_for(self, claim_row):
                return "node:stay-harvey"

            def seed_groups(self):
                return {}

        groups = tt._group_claims([row], owner_ref="self",
                                  participation=_StubParticipation())
        self.assertIn("node:stay-harvey", groups)
        self.assertIn(row, groups["node:stay-harvey"]["claims"])


# --------------------------------------------------------------------------
# Rule 2 — prompt grammar: a gerund phrase is not a "happen?" template
# --------------------------------------------------------------------------


class GerundPhraseGrammarTests(unittest.TestCase):
    def test_harvey_arriving_reads_naturally(self):
        text = tt.compose_question("precision_gap", None, what="Harvey arriving")
        self.assertEqual(text, "When was Harvey arriving?")

    def test_the_missing_anchor_slot_reads_naturally_too(self):
        text = tt.compose_question("missing_anchor", None, what="Harvey arriving")
        self.assertEqual(text, "When was Harvey arriving?")

    def test_never_the_ungrammatical_happen_wording(self):
        text = tt.compose_question("precision_gap", None, what="Harvey arriving")
        self.assertNotIn("happen", text)

    def test_a_real_ing_event_noun_is_unaffected(self):
        text = tt.compose_question("precision_gap", None, what="the wedding")
        self.assertEqual(text, "When did the wedding happen?")

    def test_a_real_ing_event_noun_meeting_is_unaffected(self):
        text = tt.compose_question("precision_gap", None, what="the meeting")
        self.assertEqual(text, "When did the meeting happen?")

    def test_a_named_event_kind_row_is_unaffected(self):
        # "span"'s own row already reads "When was {what}?" — untouched.
        text = tt.compose_question("precision_gap", "span", what="a road trip")
        self.assertEqual(text, "When was a road trip?")

    def test_the_detector_itself_on_a_handful_of_phrases(self):
        self.assertTrue(tt._is_gerund_phrase("Harvey arriving"))
        self.assertTrue(tt._is_gerund_phrase("the kids leaving"))
        self.assertFalse(tt._is_gerund_phrase("the wedding"))
        self.assertFalse(tt._is_gerund_phrase("Arriving"))
        self.assertFalse(tt._is_gerund_phrase("the arriving"))
        self.assertFalse(tt._is_gerund_phrase("Harvey"))


class BarePronounQuestionLintTests(unittest.TestCase):
    """Rule 2's backstop: `conversation_lints.lint_question` catches a
    surviving bare pronoun subject beyond the original i/me/the subject/self."""

    def test_when_was_they_is_refused(self):
        findings = cl.lint_question("When was they?")
        self.assertTrue(findings)
        self.assertEqual(findings[0]["lint"], cl.QUESTION_TEMPLATE_LEAK)

    def test_when_did_they_happen_is_refused(self):
        self.assertTrue(cl.lint_question("When did they happen?"))

    def test_third_person_pronouns_are_refused(self):
        for pronoun in ("he", "she", "it", "we", "someone", "this", "that"):
            with self.subTest(pronoun=pronoun):
                self.assertTrue(cl.lint_question(f"When was {pronoun}?"))

    def test_you_is_never_refused(self):
        # "you" is the CORRECT composed subject of every owner-directed
        # question; extending the pronoun set must never catch it.
        self.assertFalse(cl.lint_question("When did you move to Indiana?"))
        self.assertFalse(cl.lint_question("When were you born?"))

    def test_a_real_subject_named_they_something_is_untouched(self):
        findings = cl.lint_question("When did the They Foundation start?")
        self.assertFalse(findings)


# --------------------------------------------------------------------------
# Rule 3 — identity candidates
# --------------------------------------------------------------------------


#: The owner's roster, shape-for-shape with the incident: a `maps_to_focus`
#: alias row duplicating the brother, the genuinely distinct son, and a
#: collective row whose alias merely starts with the owner's own first name.
JAMES_ROSTER = roster(
    person("Anthon James Taylor", slug="anthon-james-taylor", relationship="sibling",
           aliases=["AJ", "AJ Taylor", "A.J. (brother)", "James"]),
    person("James Everett Taylor", slug="james-everett-taylor", relationship="child"),
    person("James", slug="james", maps_to_focus="anthon-james-taylor",
           relationship="sibling", qualifies=False, score=0.0),
)

DAVE_KIDS_ROSTER = roster(
    person("Dave", slug="dave", aliases=["David Taylor", "David James Taylor"]),
    person("Kids", slug="kids", qualifies=False,
           aliases=["his kids", "Dave's kids", "the kids", "Kids (unnamed)"]),
)

SON = "person/james-everett-taylor"
BROTHER = "person/anthon-james-taylor"
ALIAS_ROW = "person/james"
OWNER = "person/dave"
KIDS = "person/kids"


class RosterAliasRowsAreNotCandidatesTests(unittest.TestCase):
    def test_a_maps_to_focus_row_mints_no_ref_of_its_own(self):
        index = ir.roster_index(JAMES_ROSTER)
        self.assertNotIn(ALIAS_ROW, index.refs)

    def test_a_bare_james_is_ambiguous_between_the_two_real_people_only(self):
        record = ir.resolve_mention("James", roster=JAMES_ROSTER,
                                    evidence_ref=EVIDENCE, now=NOW)
        self.assertEqual(record.resolution, "uncertain")
        refs = {c["ref"] for c in record.candidates}
        self.assertEqual(refs, {BROTHER, SON})
        self.assertNotIn(ALIAS_ROW, refs)

    def test_the_card_offers_the_son_and_the_brother(self):
        record = ir.resolve_mention("James", roster=JAMES_ROSTER,
                                    evidence_ref=EVIDENCE, now=NOW)
        item = ir.identity_work_item(record, claim_refs=[EVIDENCE], now=NOW)
        self.assertIsNotNone(item)
        self.assertIn("James Everett Taylor", item["prompt_intent"])
        self.assertIn("Anthon James Taylor", item["prompt_intent"])


class CollectiveRowsAreNotCandidatesTests(unittest.TestCase):
    def test_the_owners_own_name_resolves_on_sight(self):
        record = ir.resolve_mention("Dave", roster=DAVE_KIDS_ROSTER,
                                    evidence_ref=EVIDENCE, now=NOW)
        self.assertTrue(record.is_resolved())
        self.assertEqual(record.resolved_ref, OWNER)

    def test_no_dave_or_kids_card_mints(self):
        record = ir.resolve_mention("Dave", roster=DAVE_KIDS_ROSTER,
                                    evidence_ref=EVIDENCE, now=NOW)
        self.assertIsNone(ir.identity_work_item(record, claim_refs=[EVIDENCE], now=NOW))

    def test_kids_still_resolves_its_own_exact_alias(self):
        # The census exclusion never touches exact-key resolution — a
        # mention that actually SAYS "Dave's kids" still means them.
        record = ir.resolve_mention("Dave's kids", roster=DAVE_KIDS_ROSTER,
                                    evidence_ref=EVIDENCE, now=NOW)
        self.assertTrue(record.is_resolved())
        self.assertEqual(record.resolved_ref, KIDS)

    def test_the_existing_marker_is_entity_rosters_own(self):
        self.assertIn("kids", er.ROLE_WORDS)
        self.assertIn("parents", er.ROLE_WORDS)

    def test_identity_resolutions_duplicate_has_not_drifted(self):
        # identity_resolution.py may never IMPORT entity_roster (its own
        # purity contract — see `_COLLECTIVE_ROLE_WORDS`'s docstring), so it
        # keeps a deliberate duplicate. This test is what keeps it honest.
        self.assertEqual(ir._COLLECTIVE_ROLE_WORDS, er.ROLE_WORDS)


class OwnerExcludedFromOwnNameCandidatesTests(unittest.TestCase):
    """The owner never appears as a candidate for his own given name — a
    DIFFERENT mechanism from the collective-row census exclusion above: here
    two OTHER real people also happen to answer to "Dave"."""

    THREE_DAVES = roster(
        person("Dave", slug="dave"),
        person("Dave Junior", slug="dave-junior", aliases=["Dave"]),
        person("Dave Uncle", slug="dave-uncle", aliases=["Dave"]),
    )
    TWO_DAVES = roster(
        person("Dave", slug="dave"),
        person("Dave Junior", slug="dave-junior", aliases=["Dave"]),
    )

    def test_the_owner_is_in_the_raw_resolution(self):
        record = ir.resolve_mention("Dave", roster=self.THREE_DAVES,
                                    evidence_ref=EVIDENCE, now=NOW)
        self.assertEqual(record.resolution, "uncertain")
        self.assertIn(OWNER, {c["ref"] for c in record.candidates})

    def test_the_card_never_offers_the_owner(self):
        record = ir.resolve_mention("Dave", roster=self.THREE_DAVES,
                                    evidence_ref=EVIDENCE, now=NOW)
        item = ir.identity_work_item(record, claim_refs=[EVIDENCE], now=NOW,
                                     owner_refs=(OWNER,))
        self.assertIsNotNone(item)
        self.assertNotIn(OWNER, item["prompt_intent"])
        self.assertIn("Dave Junior", item["prompt_intent"])
        self.assertIn("Dave Uncle", item["prompt_intent"])

    def test_fewer_than_two_real_candidates_after_owner_exclusion_mints_nothing(self):
        record = ir.resolve_mention("Dave", roster=self.TWO_DAVES,
                                    evidence_ref=EVIDENCE, now=NOW)
        item = ir.identity_work_item(record, claim_refs=[EVIDENCE], now=NOW,
                                     owner_refs=(OWNER,))
        self.assertIsNone(item)

    def test_with_no_owner_refs_supplied_behaviour_is_unchanged(self):
        record = ir.resolve_mention("Dave", roster=self.THREE_DAVES,
                                    evidence_ref=EVIDENCE, now=NOW)
        item = ir.identity_work_item(record, claim_refs=[EVIDENCE], now=NOW)
        self.assertIsNotNone(item)
        self.assertIn("Dave", item["prompt_intent"])


class EndToEndIdentityCardsTests(unittest.TestCase):
    """The whole pipeline, owner's roster shape, owner's own name supplied."""

    ROSTER = roster(
        person("Dave", slug="dave", aliases=["David Taylor", "David James Taylor"]),
        person("Kids", slug="kids", qualifies=False,
               aliases=["his kids", "Dave's kids", "the kids", "Kids (unnamed)"]),
        person("Anthon James Taylor", slug="anthon-james-taylor", relationship="sibling",
               aliases=["AJ", "AJ Taylor", "A.J. (brother)", "James"]),
        person("James Everett Taylor", slug="james-everett-taylor", relationship="child"),
        person("James", slug="james", maps_to_focus="anthon-james-taylor",
               relationship="sibling", qualifies=False, score=0.0),
    )

    def derive(self, claims):
        return tt.derive_calculated_timeline(
            index_of(claims), roster_snapshot=self.ROSTER, owner_names=("Dave",), now=NOW,
        )

    def test_a_bare_dave_mention_mints_no_identity_card(self):
        claims = [claim(
            claim_type="occurrence", subject_mention="Dave", event_kind="moment",
            source="conversation:msg-dave", event_mention="Dave took the kids to the park",
            quote="Dave took the kids to the park.",
        )]
        result = self.derive(claims)
        self.assertFalse(
            [w for w in result.work_items if w.get("kind") == "identity_uncertain"]
        )

    def test_a_bare_james_mention_offers_the_two_real_jameses_only(self):
        claims = [claim(
            claim_type="occurrence", subject_mention="James", event_kind="moment",
            source="conversation:msg-james", event_mention="James came over",
            quote="James came over.",
        )]
        result = self.derive(claims)
        cards = [w for w in result.work_items if w.get("kind") == "identity_uncertain"]
        self.assertEqual(len(cards), 1)
        text = cards[0]["prompt_intent"]
        self.assertIn("James Everett Taylor", text)
        self.assertIn("Anthon James Taylor", text)
        self.assertNotIn("'James' is 'James'", text)


# --------------------------------------------------------------------------
# Rule 4 — the rule version
# --------------------------------------------------------------------------


class CalculationRuleVersionTests(unittest.TestCase):
    def test_the_rule_version_is_the_one_in_force(self):
        self.assertEqual(tt.CALCULATION_RULE_VERSION, "timeline-rules:16")


if __name__ == "__main__":
    unittest.main()
