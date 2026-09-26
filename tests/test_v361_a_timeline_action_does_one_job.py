"""v361 — a conversation opened from a Timeline action knows its context and
does one job.

THE INCIDENT (owner, staging, 2026-09-26 15:03Z). He pressed ▸ on
"About Charlee · What year did Charlee switch from flag football to track?"
and typed *"Charlee switched from football to track her freshmen year January
2026"*. The reply: *"Football to track, freshman year, January 2026 — noted.
What pulled you toward track?"* — a story beat, asked of the wrong person. He
typed *"This is Charlee not me"* and got *"…So, what pulled Charlee toward
track that January?"*. A second card the same morning ("this was during
etherfuse") got *"Tell me what happened there."* And after a move on the
Timeline, the conversation that opened asked him why he had made the move.

His words: "when I actually make an edit on the timeline, it doesn't have
context… when we're answering questions it is aware of all the context and
it's specifically trying to answer the timely question."

THE RULE (`timeline_interaction.A_TIMELINE_ACTION_CONVERSATION_DOES_ONE_JOB`),
one definition for every host (owner ruling 2026-09-25, "Platform and OSS
behave the same"): the conversation carries its target, the person it is
about, where it stands and what the action changed; its reply confirms in one
line and stops, or asks ONE related question grounded in a real open item,
about the right person; never a story beat, never why.

Every negative below was run against a build with its guard removed and SEEN
failing first.
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "system"))
sys.path.insert(0, str(ROOT / "tests"))

import answer_placement as ap  # noqa: E402
import conversation_delivery as cd  # noqa: E402
import temporal_publication as pub  # noqa: E402
import temporal_store as ts  # noqa: E402
import timeline_evals as te  # noqa: E402
import timeline_interaction as ti  # noqa: E402
from test_conversation_delivery import EngineTestCase, turn_json  # noqa: E402
from test_v352_answering_a_card_places_its_moment import VaultFixture  # noqa: E402

GOLDENS = ROOT / "interactions" / "timeline" / "evals" / "goldens"
BAD_FIXTURE = GOLDENS / "timeline-action-story-beat-bad-01.json"

# --------------------------------------------------------------------------
# The owner's card, as staging published it at generation 198
# --------------------------------------------------------------------------

CHARLEE_ANSWER = "Charlee switched from football to track her freshmen year January 2026"
CHARLEE_ITEM = {
    "kind": "precision_gap",
    "work_item_id": "work:5926ea22785ec451f327a1ee",
    "node_ref": "node:2457fc165fcb61619b2bb15b",
    "event_ref": "node:2457fc165fcb61619b2bb15b",
    "subject_ref": "Charlee",
    "prompt_intent": "What year did Charlee switch from flag football to track?",
    "requested_field": "date",
    "state": "open",
    "resolves": [],
    "probable_window": {"earliest": "2019", "latest": "2021-10", "source": "resolver"},
}
CHARLEE_NODE = {"node_id": "node:2457fc165fcb61619b2bb15b",
                "label": "Charlee moved from football to track",
                "subject_refs": ["Charlee"], "best_temporal_value": None,
                "usable_placement": False}
#: `cornerstones_view` at generation 198: Charlee had no roster row, so no
#: relation word was published — only the Cornerstones row (child, born).
CHARLEE_PEOPLE = {"groups": [{"group": "children", "people": [
    {"display_name": "Charlee", "name": "Charlee Joy Taylor", "relationship": "child",
     "relation_word": None, "person_ref": "landmark:charlee joy taylor",
     "born": {"display": "21 December 2010", "value": "2010-12-21"}}]}]}
HARVEY_WORD = {"name": "Harvey", "word": "son", "relation_gender": "male",
               "relationship": "child", "subject_ref": "person/harvey",
               "spellings": ["harvey"]}

REAL_BAD_REPLIES = (
    "Football to track, freshman year, January 2026 — noted. What pulled you toward track?",
    "Got it — this is Charlee's story, not yours. Thanks for the clarification, that "
    "matters. So, what pulled Charlee toward track that January?",
    "Etherfuse — good to have that as the backdrop. Tell me what happened there.",
)


def charlee_card(**overrides) -> dict:
    item = dict(CHARLEE_ITEM, **overrides)
    return ti.card_view(item, nodes=[CHARLEE_NODE], people=CHARLEE_PEOPLE)


def turns(*rows) -> dict:
    return {"turns": [dict(role=role, text=text, **extra) for role, text, extra in rows]}


# --------------------------------------------------------------------------
# 1. WHO — the subject is named, related, aged, and spoken of in the third person
# --------------------------------------------------------------------------

class WhoItIsAboutTests(unittest.TestCase):
    def test_the_owners_daughter_is_named_with_her_relation_and_birth(self):
        """Generation 198 carried no relation word for Charlee; the Cornerstones
        view did. The model is told "your child Charlee", born 21 December 2010
        — not the person typing."""
        who = ti.subject_view("Charlee", people=CHARLEE_PEOPLE)
        self.assertFalse(who["is_owner"])
        self.assertEqual(who["name"], "Charlee")
        self.assertEqual(who["phrase"], "your child Charlee")
        self.assertEqual(who["born"], "21 December 2010")

    def test_a_published_gendered_word_wins_and_gives_a_pronoun(self):
        """Owner ruling 2026-09-25: when one word can be shown, the gendered one."""
        who = ti.subject_view("Harvey", relation_words=[HARVEY_WORD])
        self.assertEqual(who["phrase"], "your son Harvey")
        self.assertEqual(who["pronoun"], "he")

    def test_a_kinship_name_is_not_said_twice(self):
        who = ti.subject_view(
            "James Taylor",
            relation_words=[{"name": "James Taylor", "word": "father",
                             "relation_gender": "male", "spellings": ["james taylor"]}],
            people=[{"display_name": "Dad", "name": "James Taylor",
                     "relationship": "parent", "relation_word": "Father"}])
        self.assertEqual(who["phrase"], "Dad (your father)")

    def test_the_owner_is_the_owner(self):
        for ref in ("self", "", "me", None):
            with self.subTest(ref=ref):
                self.assertTrue(ti.subject_view(ref)["is_owner"])

    def test_an_unresolved_handle_is_not_a_person(self):
        self.assertEqual(ti.subject_view("unresolved:James"), {})


# --------------------------------------------------------------------------
# 2. WHAT — the card: question, moment, where it stands, grounded related moments
# --------------------------------------------------------------------------

class TheCardTests(unittest.TestCase):
    def test_the_owners_card_carries_its_whole_context(self):
        card = charlee_card()
        self.assertEqual(card["question"], CHARLEE_ITEM["prompt_intent"])
        self.assertEqual(card["label"], "Charlee moved from football to track")
        self.assertEqual(card["subject"]["phrase"], "your child Charlee")
        self.assertEqual(card["related"], ())
        # The system's guess is shown as a guess his answer replaces — never a
        # reading to argue with (a system inference never overrides him).
        self.assertIn("not placed yet", card["placement"])
        self.assertIn("2019", card["placement"])
        self.assertIn("replaces that guess", card["placement"])

    def test_a_placed_moment_says_where_it_is(self):
        node = dict(CHARLEE_NODE, usable_placement=True, best_temporal_value={
            "best": "2026-01", "earliest": "2026-01", "latest": "2026-01",
            "granularity": "month", "confidence": "certain", "basis": "stated"})
        card = ti.card_view(CHARLEE_ITEM, nodes=[node])
        self.assertEqual(card["placement"], "placed at January 2026")

    def test_related_moments_are_grounded_never_invented(self):
        """`resolves` labelled off the published nodes: unlabelled and
        unpublished ids are skipped, duplicates collapse, and a former id
        resolves through the alias map — each with who it is about."""
        item = dict(CHARLEE_ITEM, resolves=["node:old-meet", "node:first-meet",
                                            "node:unlabelled", "node:never-published"])
        nodes = [CHARLEE_NODE,
                 {"node_id": "node:first-meet", "label": "Charlee's first track meet",
                  "subject_refs": ["Charlee"]},
                 {"node_id": "node:unlabelled", "label": ""}]
        card = ti.card_view(item, nodes=nodes, node_aliases={"node:old-meet": "node:first-meet"},
                            people=CHARLEE_PEOPLE)
        self.assertEqual(card["related"], (
            {"node_id": "node:first-meet", "label": "Charlee's first track meet",
             "about": "Charlee"},))


# --------------------------------------------------------------------------
# 3. WHEN IT IS DONE — the transcript rule, and the question gate
# --------------------------------------------------------------------------

class WhenTheCardIsDoneTests(unittest.TestCase):
    ANSWER = ("user", CHARLEE_ANSWER, {})

    def test_nobody_has_answered_yet(self):
        self.assertFalse(ti.card_is_done(turns(), related=0))

    def test_the_owners_card_is_done_on_its_first_reply(self):
        """No related moments -> the first reply is the last: `close`."""
        self.assertEqual(ti.card_stage_for_session(turns(self.ANSWER), related=()), "close")

    def test_one_related_moment_leaves_room_for_one_question(self):
        self.assertEqual(ti.card_stage_for_session(turns(self.ANSWER), related=1),
                         ti.WORK_ITEM_STAGE)

    def test_a_reply_that_asked_nothing_ends_it(self):
        done = turns(self.ANSWER, ("lifehug", "Noted.", {}), ("user", "ok", {}))
        self.assertTrue(ti.card_is_done(done, related=5))

    def test_an_answer_that_fed_no_placement_ends_it(self):
        asked = turns(self.ANSWER, ("lifehug", "Noted. When was the first meet?", {}),
                      ("user", "no idea", {}))
        self.assertTrue(ti.card_is_done(asked, related=5))

    def test_there_is_no_hard_cap_but_the_related_moments(self):
        """Owner amendment 2026-09-22: while each answer places something and a
        related moment remains, the conversation may continue — MAX_PROBES is
        not this rule."""
        rows = [self.ANSWER]
        for n in range(ti.MAX_PROBES + 1):
            rows += [("lifehug", f"Noted. And the next one {n}?", {"placed": {"best": "2026"}}),
                     ("user", "2026", {})]
        self.assertFalse(ti.card_is_done(turns(*rows), related=ti.MAX_PROBES + 5))

    def test_a_closing_reply_and_a_move_reply_may_not_carry_a_question(self):
        self.assertFalse(ti.action_question_allowed("close"))
        self.assertFalse(ti.action_question_allowed(ti.MOVE_STAGE))
        self.assertTrue(ti.action_question_allowed(ti.WORK_ITEM_STAGE))

    def test_his_own_years_are_years_the_reply_may_say(self):
        """"January 2026" is his: confirming it invents nothing."""
        self.assertIn("2026", ti.card_known_years(ti.work_item_target(CHARLEE_ITEM),
                                                  turns(self.ANSWER)))


# --------------------------------------------------------------------------
# 4. WHAT THE MODEL READS — the card block
# --------------------------------------------------------------------------

class TheCardBlockTests(unittest.TestCase):
    def test_the_owners_card_block_names_charlee_and_asks_nothing(self):
        block = ti.render_card_context(charlee_card(), answered=True, closing=True)
        self.assertTrue(block.startswith(ti.CARD_HEADING))
        self.assertIn("«What year did Charlee switch from flag football to track?»", block)
        self.assertIn("The moment: Charlee moved from football to track", block)
        self.assertIn("about your child Charlee, not about the person you are talking",
                      block)
        self.assertIn("Charlee was born 21 December 2010", block)
        self.assertIn("third person", block)
        self.assertIn("a question about why", block)
        self.assertIn("**Ask nothing.**", block)
        self.assertNotIn("ONLY if it follows", block)

    def test_a_card_about_the_owner_carries_no_subject_lines(self):
        block = ti.render_card_context(charlee_card(subject_ref="self"),
                                       answered=True, closing=True)
        self.assertNotIn("not about the person you are talking", block)

    def test_the_related_list_appears_only_while_one_may_be_asked(self):
        item = dict(CHARLEE_ITEM, resolves=["node:first-meet"])
        card = ti.card_view(item, nodes=[CHARLEE_NODE, {
            "node_id": "node:first-meet", "label": "Charlee's first track meet",
            "subject_refs": ["Charlee"]}], people=CHARLEE_PEOPLE)
        open_block = ti.render_card_context(card, answered=True, closing=False)
        self.assertIn("- Charlee's first track meet (about Charlee)", open_block)
        self.assertNotIn("**Ask nothing.**", open_block)
        closing_block = ti.render_card_context(card, answered=True, closing=True)
        self.assertNotIn("Charlee's first track meet", closing_block)

    def test_before_the_answer_the_block_asks_the_cards_question_only(self):
        block = ti.render_card_context(charlee_card(), answered=False, closing=False)
        self.assertIn("They have not answered yet", block)
        self.assertNotIn("Confirm in ONE line", block)


# --------------------------------------------------------------------------
# 5. A MOVE — confirm what moved and where, take a correction, never ask why
# --------------------------------------------------------------------------

class TheMoveTests(unittest.TestCase):
    MOVE = {"node_id": "node:robotech", "label": "Robotech nights at the Larsons'",
            "relation": "within", "anchors": ["the Horsepools house"],
            "range": "June 1990–June 1991"}

    def test_the_confirmation_line_says_what_moved_and_where_it_landed(self):
        self.assertEqual(
            ti.move_confirmation(self.MOVE),
            "Moved “Robotech nights at the Larsons'” to June 1990–June 1991, inside "
            "the Horsepools house. Right?")

    def test_the_line_says_only_what_the_host_knows(self):
        self.assertEqual(ti.move_confirmation({"node_id": "node:a", "label": "A",
                                               "relation": "before", "anchors": ["B"]}),
                         "Moved “A” — now before “B”. Right?")
        self.assertEqual(ti.move_confirmation({"node_id": "node:a", "label": "A"}),
                         "Moved “A”. Right?")

    def test_a_machine_spelling_is_never_a_line(self):
        self.assertIsNone(ti.move_target({"node_id": "node:a"}))
        self.assertIsNone(ti.move_target({"node_id": "node:a", "label": "node:a"}))
        self.assertEqual(ti.move_confirmation({"node_id": "node:a"}), "")

    def test_the_move_block_forbids_why_and_asks_nothing(self):
        block = ti.render_move_context(self.MOVE)
        self.assertTrue(block.startswith(ti.MOVE_HEADING))
        self.assertIn(ti.move_confirmation(self.MOVE), block)
        self.assertIn("NEVER ask why they moved it", block)
        self.assertIn("the correction IS", block)
        self.assertIn("**Ask nothing.**", block)

    def test_a_move_conversation_is_done_once_he_replies(self):
        self.assertFalse(ti.move_is_done(turns()))
        self.assertTrue(ti.move_is_done(turns(("user", "Yes", {}))))
        self.assertEqual(ti.move_stage_for_session(turns()), ti.MOVE_STAGE)
        self.assertIn(ti.MOVE_STAGE, ti.VALID_TIMELINE_STAGES)


# --------------------------------------------------------------------------
# 6. THE LINTS — the owner's real replies fail; the right ones pass
# --------------------------------------------------------------------------

class TheLintTests(unittest.TestCase):
    SUBJECT = ti.subject_view("Charlee", people=CHARLEE_PEOPLE)

    def lints(self, reply, *, stage="close", action="card", subject=None):
        return {row["lint"] for row in ti.lint_timeline_reply(
            reply, stage=stage, known_years=("2026",), action=action,
            subject=self.SUBJECT if subject is None else subject)}

    def test_every_case_in_the_broken_golden_fires_its_classes(self):
        broken = json.loads(BAD_FIXTURE.read_text(encoding="utf-8"))
        self.assertEqual(len(broken["cases"]), 5)
        for case in broken["cases"]:
            with self.subTest(case=case["case_id"]):
                found = self.lints(case["reply"], stage=case["stage"],
                                   action=case["action"], subject=broken["subject"])
                for lint in case["expected_lints"]:
                    self.assertIn(lint, found)

    def test_the_owners_three_real_replies_are_the_first_three_cases(self):
        broken = json.loads(BAD_FIXTURE.read_text(encoding="utf-8"))
        self.assertEqual(tuple(case["reply"] for case in broken["cases"][:3]),
                         REAL_BAD_REPLIES)

    def test_the_right_confirmation_is_clean(self):
        for reply in ("Noted — Charlee switched from flag football to track in January "
                      "2026, her freshman year.",
                      "Noted — your child Charlee switched to track in January 2026."):
            with self.subTest(reply=reply):
                self.assertEqual(self.lints(reply), set())

    def test_a_grounded_related_question_about_charlee_is_clean(self):
        self.assertEqual(self.lints("Noted — January 2026. When did Charlee run her "
                                    "first track meet?", stage=ti.WORK_ITEM_STAGE), set())

    def test_a_related_question_asked_of_the_wrong_person_is_not(self):
        self.assertIn("timeline_gates.right_person",
                      self.lints("Noted. What pulled you to it?", stage=ti.WORK_ITEM_STAGE))

    def test_no_action_no_subject_no_new_findings(self):
        """Every caller that names neither sees exactly what it saw before."""
        self.assertEqual(ti.lint_timeline_reply(REAL_BAD_REPLIES[0], stage="place",
                                                known_years=("2026",)), [])

    def test_the_owners_own_card_may_say_you(self):
        self.assertNotIn("timeline_gates.right_person",
                         self.lints("Noted. When did you move?", stage=ti.WORK_ITEM_STAGE,
                                    subject={"is_owner": True}))


class TheGoldensTests(unittest.TestCase):
    def test_the_action_goldens_are_present_and_pass_every_gate(self):
        fixtures = te.load_fixtures()
        ids = {row["fixture_id"] for row in fixtures}
        for fixture_id in ("timeline-card-answer-ends-at-noted",
                           "timeline-card-related-question-is-about-the-subject",
                           "timeline-card-subject-is-someone-else",
                           "timeline-move-confirmed-is-noted",
                           "timeline-move-correction-is-the-move"):
            self.assertIn(fixture_id, ids)
        self.assertEqual(te.validate_fixtures(fixtures), [])
        scores = te.score_goldens(fixtures, te.load_sample_predictions())
        self.assertEqual(te.check_gates(scores, te.load_gates()), [])
        self.assertEqual(scores["_action_stage_accuracy"], 1.0)
        self.assertEqual(scores["_placed_accuracy"], 1.0)

    def test_the_owners_real_reply_fails_the_gold_seat(self):
        """Seat the owner's actual reply in place of the reference one and the
        one_job gate drops below 1.0 — the golden catches the incident."""
        predictions = te.load_sample_predictions()
        for row in predictions:
            if row["fixture_id"] == "timeline-card-answer-ends-at-noted":
                row["turns"][0]["message"] = REAL_BAD_REPLIES[0]
        scores = te.score_goldens(te.load_fixtures(), predictions)
        self.assertLess(scores["one_job.compliance"], 1.0)
        self.assertLess(scores["right_person.compliance"], 1.0)

    def test_a_stage_the_rule_does_not_give_fails_the_stage_score(self):
        fixtures = te.load_fixtures()
        for row in fixtures:
            if row["fixture_id"] == "timeline-card-answer-ends-at-noted":
                row["turns"][0]["stage"] = ti.WORK_ITEM_STAGE
        scores = te.score_goldens(fixtures, te.load_sample_predictions())
        self.assertLess(scores["_action_stage_accuracy"], 1.0)


# --------------------------------------------------------------------------
# 7. FILING — a placement card's answer files now; a move's correction is the move
# --------------------------------------------------------------------------

class ThePlacementCardFilesNowTests(unittest.TestCase):
    PLACED = {"best": "2026-01", "earliest": "2026-01", "latest": "2026-01",
              "granularity": "month", "confidence": "certain", "basis": "stated",
              "anchors": []}

    def test_a_dated_answer_to_a_card_with_nothing_to_retire_is_placed(self):
        kwargs = ti.work_item_resolution(ti.work_item_target(CHARLEE_ITEM), self.PLACED,
                                         resolution_text=CHARLEE_ANSWER)
        self.assertEqual(kwargs["correction_kind"], ti.CORRECTION_KIND_PLACE)
        self.assertEqual(kwargs["retire_claim_ids"], [])
        self.assertEqual(kwargs["work_item_id"], CHARLEE_ITEM["work_item_id"])

    def test_an_undated_answer_still_files_nothing_on_the_turn(self):
        self.assertIsNone(ti.work_item_resolution(
            ti.work_item_target(CHARLEE_ITEM), None, resolution_text="no idea"))


class TheMoveSessionTests(unittest.TestCase):
    def test_a_move_session_names_its_node(self):
        self.assertEqual(ap.node_of_move_session(
            "conversation:cand:timeline:moved:node:abc123:2026-09-26"), "node:abc123")
        self.assertEqual(ap.node_of_move_session("conversation:cand:work_item:work:x"), "")
        self.assertTrue(ap.answers_a_card("conversation:cand:timeline:moved:node:abc"))

    def test_agreement_is_not_a_correction(self):
        for text in ("Yes", "yes, right", "Correct, thanks", "ok"):
            with self.subTest(text=text):
                self.assertTrue(ap.is_bare_confirmation(text))
        for text in ("No, it was spring 1991", "Yes but it was 1991", ""):
            with self.subTest(text=text):
                self.assertFalse(ap.is_bare_confirmation(text))


class FilingOnAVaultTests(unittest.TestCase):
    def setUp(self):
        self.vault = VaultFixture(self)

    def node_ref(self, label: str) -> str:
        return self.vault.nodes()[label]["node_id"]

    def test_a_correction_after_a_move_is_filed_on_the_moved_node(self):
        node = self.node_ref("The dog got out")
        session = f"conversation:cand:timeline:moved:{node}"
        ts.promote_conversational_source(self.vault.root, "No, it was March 1995", {
            "session_ref": session, "turn_ref": "0", "speaker": "person",
            "occurred_at": "2026-09-26T15:30:00Z"})
        report = ap.place_answers(self.vault.root)
        filed = [row for row in report["filed"] if row["node_ref"] == node]
        self.assertEqual(len(filed), 1, report)
        self.assertEqual(filed[0]["work_item_id"], "")

    def test_a_yes_after_a_move_files_nothing(self):
        node = self.node_ref("The dog got out")
        ts.promote_conversational_source(self.vault.root, "Yes", {
            "session_ref": f"conversation:cand:timeline:moved:{node}", "turn_ref": "0",
            "speaker": "person", "occurred_at": "2026-09-26T15:30:00Z"})
        report = ap.place_answers(self.vault.root)
        self.assertEqual(report["filed"], [])
        self.assertEqual(report["refused"][ap.REFUSED_MOVE_CONFIRMED], 1)

    def test_the_on_change_seat_reuses_the_reply_already_promoted(self):
        """The host promoted the reply when it arrived; placing it now must not
        mint a second source the daily sweep would file again."""
        session = self.vault.session_for("cussing")
        self.vault.answer("cussing", "It was August 2026", "2026-09-24T01:09:30Z")
        before = sorted((self.vault.root / "sources/conversations").glob("*.md"))
        placed = ap.place_card_answer(self.vault.root, session_ref=session,
                                      text="It was August 2026")
        after = sorted((self.vault.root / "sources/conversations").glob("*.md"))
        self.assertEqual(before, after)
        self.assertEqual(len(placed["report"]["filed"]), 1)
        self.assertIsNotNone(placed["card"])
        again = ap.place_answers(self.vault.root)
        self.assertEqual(len({row["claim_id"] for row in again["filed"]}), 1)

    def test_the_on_change_seat_names_what_it_could_not_find(self):
        placed = ap.place_card_answer(self.vault.root,
                                      session_ref="conversation:cand:work_item:work:nope",
                                      text="1999")
        self.assertIsNone(placed["card"])
        self.assertEqual(placed["refused"], ap.REFUSED_CARD_NOT_PUBLISHED)
        self.assertIsNotNone(pub.read_work_items(self.vault.root))


# --------------------------------------------------------------------------
# 8. THE OSS HOST — the same four calls, on the real engine path
# --------------------------------------------------------------------------

class TheOssHostTests(EngineTestCase):
    CARD = ti.card_view(CHARLEE_ITEM, nodes=[CHARLEE_NODE], people=CHARLEE_PEOPLE)

    def test_the_card_turn_carries_the_card_block(self):
        self.run_turn(work_item=CHARLEE_ITEM, card=self.CARD)
        prompt = self.prompts[-1]
        self.assertIn(ti.CARD_HEADING, prompt)
        self.assertIn("about your child Charlee", prompt)
        self.assertIn("**Ask nothing.**", prompt)

    def test_a_closing_card_reply_that_asks_anything_is_blocked(self):
        """The gate, not the model's good behaviour: the question the owner got
        cannot be delivered from a card's closing reply."""
        outcome = self.run_turn(work_item=CHARLEE_ITEM, card=self.CARD,
                                ai_call=self._ai(turn_json(message=REAL_BAD_REPLIES[0],
                                                           followup=None)))
        self.assertEqual(outcome.reason, "malformed_generation")

    def test_the_session_closes_after_the_cards_last_reply(self):
        self.run_turn(work_item=CHARLEE_ITEM, card=self.CARD,
                      ai_call=self._ai(turn_json(
                          message="Noted — Charlee switched to track in January 2026.",
                          followup=None)))
        self.assertEqual(self.only_session()["status"], "closed")

    def test_an_ordinary_turn_carries_no_card_block(self):
        self.run_turn()
        self.assertNotIn(ti.CARD_HEADING, self.prompts[-1])


if __name__ == "__main__":
    unittest.main()
