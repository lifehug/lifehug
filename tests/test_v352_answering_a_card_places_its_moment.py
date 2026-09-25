"""v352 — answering a card places its moment.

ONE defect, three times in two days, on the owner's own vault: **an answer to a
"when did X happen?" card does not place X when the reply is a bare time
expression**, and each time the card stayed open as if he had never answered.

1. ``sources/conversations/msg-a2a65da9bda477a98f67f20c.md`` — *"This was mostly
   last month and he's stopped mostly now"*, captured 2026-09-24T01:09:30Z,
   ``session_ref: conversation:cand:work_item:work:577ecc4639edf0f8ead752ca``,
   answering **"When did Harvey's love of cussing happen?"**
   (``node:3380558928426602253447c7``, subject ``person/harvey``). Its
   classification holds ``time_periods: [{era: "last month", approximate_dates:
   "2026-08"}]`` and ``events: []`` — the time was read and no event was, so
   `classifier_claims` had nothing to hang it on, the listener heard nothing, and
   the card was open that night with the node unplaced.
   (:class:`TheOwnersThreeAnswersPlaceTests`,
   :class:`RecencyIsReadAgainstTheCardsOwnQuestionTests`.)
2. ``msg-fc9845c47f8dc2b5099724a5.md`` — *"19-21 years old"*, answering the card
   about his father's mission. The listener filed
   ``claim:65573521952535272873944a``: ``claim_type: age``, 19–21,
   ``subject_mention: "they"``, ``event_kind: span``, **no ``event_mention``**,
   ``confidence: 0.0`` — which minted a node labelled *they* and a card *"When
   was they?"*. v343 suppresses that node; the ANSWER still never reached the
   moment it was about. (:class:`AimingADraftAtItsCardTests`,
   :class:`ThePronounDraftLandsOnTheCardTests`.)
3. ``msg-57c728860e184aaf2146b021.md`` — *"He only really started talking when he
   was 4"*. Receipt ``claim:bf9f8a7a0faeb8bbb1ab77f1``: ``claim_type: age``, 4,
   ``subject_mention: "he"``, ``event_mention: null``. The same shape — a time
   with no event. (:class:`TheOwnersThreeAnswersPlaceTests`.)

THE RULE (`answer_placement.ANSWERING_A_CARD_PLACES_ITS_MOMENT`): the reply
carries the WHEN, the card carries the WHAT, and
``session_ref: conversation:cand:work_item:<id>`` is the join that was on every
promoted message the whole time. The time the reply carries becomes a claim on
the node the card is about, with the reply as its source and the record's basis
``stated``; the subject comes from the NODE and never from a pronoun in the
reply; and a reply with no time at all still files as a TELLING of that node, so
the card stays open with the owner's words visible and never silently nothing.

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
import chronology as chrono  # noqa: E402
import classifier_claims as ccl  # noqa: E402
import event_identity as ei  # noqa: E402
import general_listener as gl  # noqa: E402
import landmark_recorder as lr  # noqa: E402
import temporal_claims as tc  # noqa: E402
import temporal_publication as pub  # noqa: E402
import temporal_store as ts  # noqa: E402
import temporal_timeline as tt  # noqa: E402

# The v340 fixtures, reused rather than re-derived, for the reason v342, v345
# and v350 reused them: a second spelling of "the shape a vault's receipts
# actually have" is how two tests come to disagree about what a vault is.
from tempdirs import root_parent_tmp  # noqa: E402
from test_v340_apply_keeps_placements import (  # noqa: E402
    NOW,
    claim,
    index_of,
    write_vault,
)
from test_v345_a_telling_of_a_landmark_folds_onto_it import (  # noqa: E402
    placement_audit,
)

OWNER = tt.DEFAULT_OWNER_REF

# --------------------------------------------------------------------------
# The owner's own words, verbatim — the three replies and the capture dates
# --------------------------------------------------------------------------

CUSSING_REPLY = "This was mostly last month and he’s stopped mostly now"
CUSSING_CAPTURED = "2026-09-24T01:09:30Z"
MISSION_REPLY = "19-21 years old"
MISSION_CAPTURED = "2026-09-23T02:36:54Z"
TALKING_REPLY = "He only really started talking when he was 4"
TALKING_CAPTURED = "2026-09-24T01:22:11Z"

#: The three dates the owner's roster and vault hold, which is what makes the
#: two age answers arithmetic rather than a guess: Harvey's birth (v344's
#: contested node, read at its best-supported value), his father's birth (the
#: roster row v350's sweep introduced) and the owner's own.
OWNER_BIRTH = "1981-07-11"
HARVEY_BIRTH = "2021-10-11"
FATHER_BIRTH = "1954-06-04"


def day(token: str) -> dict:
    return {"best": token, "earliest": token, "latest": token,
            "granularity": "day", "basis": "stated", "confidence": "certain"}


def birth(source: str, subject: str, token: str, label: str) -> dict:
    return claim(source=source, claim_type="date", subject_mention=subject,
                 event_kind="birth", temporal_value=day(token),
                 event_mention=label)


def undated(source: str, subject: str, label: str, *, kind: str = "moment") -> dict:
    """A moment the person narrated and never dated — the shape that carries a
    "when did this happen?" card, and the shape all three of the owner's cards
    are (`classifier_claims`' ``occurrence`` rung)."""
    return claim(source=source, claim_type=tc.OCCURRENCE_CLAIM_TYPE,
                 subject_mention=subject, event_kind=kind, event_mention=label)


def owners_vault_claims() -> list:
    """The owner's three cards and the three births that date two of them."""
    return [
        birth("classification:sources-birth#aaaaaaaaaaaa", OWNER, OWNER_BIRTH,
              "My birth"),
        birth("classification:sources-harvey#bbbbbbbbbbbb", "person/harvey",
              HARVEY_BIRTH, "Harvey's birth"),
        birth("classification:sources-dad#cccccccccccc", "person/james-taylor",
              FATHER_BIRTH, "Dad's birth"),
        undated("classification:answers-q9#dddddddddddd", "person/harvey",
                "Harvey's love of cussing"),
        # ``started`` rather than ``moment``: two undated ``moment`` tellings
        # about one person fold into ONE node (the binder's per-person bucket),
        # and on the owner's vault these are two moments with two cards.
        undated("classification:answers-q4#eeeeeeeeeeee", "person/harvey",
                "Harvey started talking", kind="started"),
        undated("classification:answers-q7#ffffffffffff", "person/james-taylor",
                "Dad's mission", kind="span"),
        undated("classification:answers-q2#a1a1a1a1a1a1", OWNER,
                "The dog got out"),
    ]


class VaultFixture:
    """A synthetic vault with cards on it, built and published like a real one.

    Nothing here is the owner's vault: the claims are the SHAPES his are and the
    words are the words he typed, on a temp directory built from scratch. The
    publish is `temporal_publication.publish`, so the work items and their
    ``prompt_intent``s are the real minter's and not a hand-written fixture —
    which is the whole point, because the card is what the answer has to find.
    """

    def __init__(self, test: unittest.TestCase, claims=None):
        self.root = root_parent_tmp(test, ROOT, prefix="lifehug-v352-")
        for folder in ("state/temporal_claims", "sources/conversations"):
            (self.root / folder).mkdir(parents=True, exist_ok=True)
        write_vault(self.root, claims if claims is not None else owners_vault_claims())
        self.publish()

    def publish(self) -> None:
        ts.rebuild_active_index(self.root)
        ei.rebuild_telling_manifest(self.root)
        pub.publish(self.root, now=NOW)

    def work_items(self) -> list[dict]:
        payload = pub.read_work_items(self.root) or {}
        return [row for row in payload.get("work_items") or () if isinstance(row, dict)]

    def card_asking_about(self, words: str) -> dict:
        rows = [row for row in self.work_items()
                if words.lower() in (row.get("prompt_intent") or "").lower()]
        assert len(rows) == 1, f"{words!r} names {len(rows)} cards"
        return rows[0]

    def session_for(self, words: str) -> str:
        return f"conversation:cand:work_item:{self.card_asking_about(words)['work_item_id']}"

    def answer(self, words: str, reply: str, captured: str, *, turn: str = "0"):
        """Promote a reply exactly as the platform's promote-message driver does."""
        return ts.promote_conversational_source(self.root, reply, {
            "session_ref": self.session_for(words), "turn_ref": turn,
            "speaker": "person", "occurred_at": captured})

    def nodes(self) -> dict[str, dict]:
        payload = pub.read_projection(self.root) or {}
        return {row["label"]: row for row in payload.get("nodes") or ()
                if isinstance(row, dict) and row.get("label")}

    def placed(self, label: str) -> tuple:
        row = self.best(label)
        return row.get("best"), row.get("basis")

    def best(self, label: str) -> dict:
        return (self.nodes().get(label) or {}).get("best_temporal_value") or {}

    def cards_by_kind(self) -> dict[str, int]:
        found: dict[str, int] = {}
        for row in self.work_items():
            found[row.get("kind") or "?"] = found.get(row.get("kind") or "?", 0) + 1
        return found

    def derived(self) -> object:
        return tt.derive_calculated_timeline(ts.fold_active_index(self.root), now=NOW)


# --------------------------------------------------------------------------
# 1. The join — a session names a work item; a work item names a node
# --------------------------------------------------------------------------

class TheJoinIsOnEveryPromotedMessageTests(unittest.TestCase):
    """`session_ref` was the join the whole time, and reading it is one line."""

    def test_the_owners_own_session_names_its_work_item(self):
        self.assertEqual(
            ap.work_item_of_session(
                "conversation:cand:work_item:work:577ecc4639edf0f8ead752ca"),
            "work:577ecc4639edf0f8ead752ca")

    def test_a_day_scoped_session_names_the_same_card(self):
        """The platform opens ``…:work:<hex>:<YYYY-MM-DD>`` when the plain session
        for a card has already closed. A second conversation about one question
        is not a second question, so the suffix is stripped."""
        self.assertEqual(
            ap.work_item_of_session(
                "conversation:cand:work_item:work:577ecc4639edf0f8ead752ca:2026-09-24"),
            "work:577ecc4639edf0f8ead752ca")

    def test_a_session_that_names_no_card_names_no_card(self):
        for session in ("conversation:local-rig", "conversation:cand:question:A7",
                        "", None, "landmark-offer:abc"):
            with self.subTest(session=session):
                self.assertEqual(ap.work_item_of_session(session), "")

    def test_the_resolver_reads_the_same_parse(self):
        """v325's revisit rung and this rule must agree about which card a
        session names, or one re-opens a question the other just answered."""
        import resolver  # noqa: PLC0415

        session = "conversation:cand:work_item:work:577ecc4639edf0f8ead752ca:2026-09-24"
        self.assertEqual(resolver._work_item_of_session(session),
                         ap.work_item_of_session(session))


class TheCardAnAnswerFindsTests(unittest.TestCase):
    """What the card hands the answer, and the four ways it refuses to."""

    def setUp(self):
        self.vault = VaultFixture(self)
        self.published = pub.read_work_items(self.vault.root) or {}
        self.projection = pub.read_projection(self.vault.root) or {}

    def test_the_cussing_card_is_the_owners_own_card(self):
        """The synthetic vault mints the owner's card, from the real minter: the
        question, the node and the subject are all the ones on his vault."""
        card = self.vault.card_asking_about("cussing")
        self.assertEqual(card["prompt_intent"], "When was Harvey's love of cussing?")
        self.assertEqual(card["subject_ref"], "person/harvey")
        self.assertEqual(card["state"], "open")
        self.assertEqual(card["requested_field"], "date")

    def test_the_card_carries_the_node_its_subject_and_its_question(self):
        card, refusal = ap.card_for_answer(
            self.vault.root, self.vault.session_for("cussing"))
        self.assertEqual(refusal, "")
        self.assertEqual(card["subject_ref"], "person/harvey")
        self.assertEqual(card["question"], "When was Harvey's love of cussing?")
        self.assertEqual(card["label"], "Harvey's love of cussing")
        self.assertEqual(card["event_kind"], "moment")
        self.assertTrue(card["node_ref"].startswith("node:"))

    def test_a_card_nobody_published_is_a_named_refusal(self):
        card, refusal = ap.card_for_answer(
            self.vault.root, "conversation:cand:work_item:work:" + "0" * 24)
        self.assertIsNone(card)
        self.assertEqual(refusal, ap.REFUSED_CARD_NOT_PUBLISHED)

    def test_a_card_that_is_not_open_is_a_named_refusal(self):
        """An answer to a card something else already settled files nothing."""
        rows = [{**row, "state": "resolved"} for row in self.vault.work_items()]
        card, refusal = ap.card_for_work_item(
            rows[0]["work_item_id"],
            work_items={"work_items": rows}, projection=self.projection)
        self.assertIsNone(card)
        self.assertEqual(refusal, ap.REFUSED_CARD_NOT_OPEN)

    def test_a_node_nobody_drew_is_a_named_refusal(self):
        rows = [{**row, "node_ref": "node:" + "1" * 24, "event_ref": "node:" + "1" * 24}
                for row in self.vault.work_items()]
        card, refusal = ap.card_for_work_item(
            rows[0]["work_item_id"],
            work_items={"work_items": rows}, projection=self.projection)
        self.assertIsNone(card)
        self.assertEqual(refusal, ap.REFUSED_NODE_NOT_DRAWN)

    def test_a_card_whose_subject_nobody_resolved_is_a_named_refusal(self):
        """Timeline Fix 01 P0b, this side of the seam: when nobody knows WHICH
        James the row is about, no sentence can be filed as settling it."""
        rows = [{**row, "subject_ref": "unresolved:james"}
                for row in self.vault.work_items()]
        naked = {"nodes": [{**node, "subject_refs": ["unresolved:james", "self"]}
                           for node in self.projection.get("nodes") or ()]}
        card, refusal = ap.card_for_work_item(
            rows[0]["work_item_id"], work_items={"work_items": rows}, projection=naked)
        self.assertIsNone(card)
        self.assertEqual(refusal, ap.REFUSED_SUBJECT_UNRESOLVED)

    def test_an_id_from_an_older_generation_still_opens_its_card(self):
        """O-E6's whole promise, applied to an answer: an id minted last month
        keeps naming its own question."""
        rows = self.vault.work_items()
        legacy = "work:" + "9" * 24
        card, refusal = ap.card_for_work_item(
            legacy,
            work_items={"work_items": rows,
                        "work_item_aliases": {legacy: rows[0]["work_item_id"]}},
            projection=self.projection)
        self.assertEqual(refusal, "")
        self.assertEqual(card["work_item_id"], rows[0]["work_item_id"])


# --------------------------------------------------------------------------
# 2. The reading — what time a reply carries, and what it refuses to read
# --------------------------------------------------------------------------

class TheReadingLadderTests(unittest.TestCase):
    """`chronology`'s own rungs, in `classifier_claims.temporal_reading`'s own
    order, over the words the owner actually typed."""

    def test_a_bare_age_band_is_an_age(self):
        reading = ap.answer_reading(MISSION_REPLY, captured=MISSION_CAPTURED)
        self.assertEqual(reading["claim_type"], "age")
        self.assertEqual(reading["temporal_value"], "19-21")
        self.assertEqual(reading["reading"], ap.READING_AGE)
        self.assertEqual(reading["confidence"], ccl.AGE_CLAIM_CONFIDENCE)

    def test_an_age_inside_a_sentence_is_an_age(self):
        reading = ap.answer_reading(TALKING_REPLY, captured=TALKING_CAPTURED)
        self.assertEqual((reading["claim_type"], reading["temporal_value"]),
                         ("age", "4"))

    def test_a_recency_cue_and_the_capture_date_are_a_stated_range(self):
        reading = ap.answer_reading(CUSSING_REPLY, captured=CUSSING_CAPTURED)
        self.assertEqual(reading["claim_type"], "date")
        self.assertEqual(reading["reading"], ap.READING_RECENCY)
        value = reading["temporal_value"]
        # v336's ruling: a stated range from the cue back to the capture date.
        self.assertEqual((value["earliest"], value["latest"]),
                         ("2026-07-24", "2026-09-24"))
        self.assertEqual(value["basis"], "stated")
        self.assertEqual(value["confidence"], "approximate")
        self.assertEqual(reading["confidence"], ccl.RECENCY_CLAIM_CONFIDENCE)

    def test_a_recency_cue_with_no_capture_date_bounds_nothing(self):
        """Without the day they said it, "last month" bounds nothing, and the
        honest reading is the one the substrate already had."""
        self.assertIsNone(ap.answer_reading(CUSSING_REPLY, captured=None))

    def test_a_date_they_typed_is_a_date(self):
        for reply, best in (("March 1998", "1998-03"), ("1998-2001", "1998/2001"),
                            ("around 2005", "2005~"), ("11 July 1981", "1981-07-11")):
            with self.subTest(reply=reply):
                reading = ap.answer_reading(reply, captured=NOW)
                self.assertEqual(reading["reading"], ap.READING_DATE)
                self.assertEqual(reading["temporal_value"]["best"], best)

    def test_a_reply_with_no_time_reads_as_none(self):
        for reply in ("I honestly have no idea", "It was chaos", "Dad was there",
                      "", "   "):
            with self.subTest(reply=reply):
                self.assertIsNone(ap.answer_reading(reply, captured=NOW))

    def test_the_year_trap_is_closed(self):
        """`chronology.parse_age` is a FIELD parser: over prose it reads *"March
        1998"* as age 8 and *"1985"* as age 5. A text naming a four-digit year
        DATES ITSELF, so no age is ever read out of one."""
        self.assertEqual(chrono.parse_age("March 1998"), (8, 8, False))
        self.assertEqual(ap.age_phrase("March 1998"), "")
        self.assertEqual(ap.age_phrase("We moved in 1985 when he was 4"), "")
        self.assertEqual(ap.answer_reading("March 1998", captured=NOW)["claim_type"],
                         "date")

    def test_a_number_behind_at_is_not_an_age(self):
        """ADR 0026 ranks a miss above a wrong join: a bare number behind "at"
        is as often a street number as an age."""
        self.assertEqual(ap.age_phrase("We moved at 30 Elm Street"), "")
        self.assertEqual(ap.age_phrase("at about 4 years"), "4")

    def test_the_whole_reply_as_a_bare_number_is_an_age(self):
        self.assertEqual(ap.age_phrase("4"), "4")
        self.assertEqual(ap.age_phrase("19-21"), "19-21")

    def test_every_age_phrasing_the_vocabulary_holds(self):
        for reply, age in (("when he was 4", "4"), ("while they were 19-21", "19-21"),
                           ("19-21 years old", "19-21"), ("4 yrs old", "4"),
                           ("aged 19", "19"), ("age 4", "4"),
                           ("the age of 4", "4"), ("at around 19 years", "19")):
            with self.subTest(reply=reply):
                self.assertEqual(ap.age_phrase(reply), age)

    def test_a_reply_with_no_time_is_a_telling_and_not_a_date(self):
        reading = ap.telling_reading()
        self.assertEqual(reading["claim_type"], tc.OCCURRENCE_CLAIM_TYPE)
        self.assertIsNone(reading["temporal_value"])
        self.assertEqual(reading["reading"], ap.READING_TELLING)


class RecencyIsReadAgainstTheCardsOwnQuestionTests(unittest.TestCase):
    """v336's ruling said "the story OR the question that prompted the answer",
    and for a card the prompting question is the CARD's."""

    def test_the_cards_question_is_a_haystack(self):
        reading = ap.answer_reading(
            "That was it, nothing else to say", captured="2026-09-24T01:00:00Z",
            question="Was there a recent moment that changed how you saw him?")
        self.assertIsNotNone(reading)
        self.assertEqual(reading["reading"], ap.READING_RECENCY)
        self.assertEqual(reading["temporal_value"]["earliest"], "2026-03-24")

    def test_without_the_question_the_same_reply_carries_no_time(self):
        self.assertIsNone(ap.answer_reading(
            "That was it, nothing else to say", captured="2026-09-24T01:00:00Z"))


# --------------------------------------------------------------------------
# 3. The owner's three answers, each one placing
# --------------------------------------------------------------------------

class TheOwnersThreeAnswersPlaceTests(unittest.TestCase):
    """The defect and its fix, on the three shapes, end to end."""

    def setUp(self):
        self.vault = VaultFixture(self)
        self.before = self.vault.derived()
        self.vault.answer("cussing", CUSSING_REPLY, CUSSING_CAPTURED)
        self.vault.answer("talking", TALKING_REPLY, TALKING_CAPTURED)
        self.vault.answer("mission", MISSION_REPLY, MISSION_CAPTURED)

    def test_before_the_rule_all_three_moments_are_unplaced(self):
        """The defect itself: three promoted answers in the vault and three cards
        still asking, because nothing joined the reply to the card."""
        self.vault.publish()
        for label in ("Harvey's love of cussing", "Harvey started talking",
                      "Dad's mission"):
            with self.subTest(label=label):
                self.assertEqual(self.vault.placed(label), (None, None))
        asking = {row["prompt_intent"] for row in self.vault.work_items()}
        self.assertEqual(asking, {"When was Harvey's love of cussing?",
                                  "When did Harvey started talking start?",
                                  "When was Dad's mission?",
                                  "When did The dog got out happen?"})

    def test_all_three_place_when_the_answers_are_read_as_answers(self):
        report = ap.place_answers(self.vault.root, now=NOW)
        self.vault.publish()
        self.assertEqual(report["answers"], 3)
        self.assertEqual(report["placed"], 3)
        self.assertEqual(report["tellings"], 0)
        self.assertEqual(report["errors"], [])
        self.assertEqual(report["by_reading"][ap.READING_RECENCY], 1)
        self.assertEqual(report["by_reading"][ap.READING_AGE], 2)

        # 1. "last month" told on 2026-09-24 — a STATED range, placed by him.
        best, basis = self.vault.placed("Harvey's love of cussing")
        self.assertEqual(best, "2026-07-24/2026-09-24")
        self.assertEqual(basis, "stated")
        # 2. age 4 measured from HARVEY's birth, not the owner's (v346's
        #    AN_AGE_IS_MEASURED_FROM_ITS_OWN_SUBJECT): 2021-10-11 + 4.
        record = self.vault.best("Harvey started talking")
        self.assertEqual(record["basis"], "age")
        self.assertEqual(record["earliest"][:4], "2025")
        self.assertEqual(chrono.year_of(record), 2025)
        # 3. 19-21 measured from his FATHER's 1954-06-04 birth, which the roster
        #    holds: nineteen to twenty-one years after it and not a year later.
        record = self.vault.best("Dad's mission")
        self.assertEqual(record["basis"], "age")
        self.assertEqual((record["earliest"][:4], record["latest"][:4]),
                         ("1973", "1976"))

    def test_the_three_cards_close(self):
        before = {row["prompt_intent"] for row in self.vault.work_items()}
        ap.place_answers(self.vault.root, now=NOW)
        self.vault.publish()
        after = {row["prompt_intent"] for row in self.vault.work_items()}
        for question in ("When was Harvey's love of cussing?",
                         "When did Harvey started talking start?",
                         "When was Dad's mission?"):
            with self.subTest(question=question):
                self.assertIn(question, before)
                self.assertNotIn(question, after)

    def test_the_subject_comes_from_the_node_and_never_from_the_pronoun(self):
        """*"He only really started talking"* — the subject of the claim this
        files is `person/harvey`, which is the card's, and never ``he``."""
        ap.place_answers(self.vault.root, now=NOW)
        index = ts.fold_active_index(self.vault.root)
        ours = [row for row in index["claims"]
                if row.get("extractor_version") == ap.EXTRACTOR_VERSION]
        self.assertEqual(len(ours), 3)
        self.assertEqual({row["subject_mention"] for row in ours},
                         {"person/harvey", "person/james-taylor"})
        for row in ours:
            with self.subTest(claim=row["claim_id"]):
                self.assertFalse(ap.is_pronoun_subject(row["subject_mention"]))
                self.assertTrue(row["event_ref"].startswith("node:"))
                self.assertTrue(row["event_mention"])
                self.assertEqual(row["source_kind"], "conversation")
                self.assertTrue(row["source_ref"]["source_path"].startswith(
                    "sources/conversations/"))

    def test_the_reply_is_the_claims_own_source(self):
        """"With the reply as its source": every claim cites the promoted message
        the person typed, at that message's own content revision."""
        ap.place_answers(self.vault.root, now=NOW)
        index = ts.fold_active_index(self.vault.root)
        ours = [row for row in index["claims"]
                if row.get("extractor_version") == ap.EXTRACTOR_VERSION]
        self.assertEqual(len(ours), 3)
        for row in ours:
            relative = row["source_ref"]["source_path"]
            with self.subTest(source=relative):
                declared = ts.read_source_ref(self.vault.root, relative)
                self.assertEqual(row["source_ref"]["revision"], declared.revision)
                self.assertEqual(row["source_ref"]["source_id"], declared.source_id)
                body = (self.vault.root / relative).read_text(encoding="utf-8")
                self.assertIn(row["evidence"][0]["quote"][:20], body)

    def test_no_bogus_node_is_minted_for_a_pronoun(self):
        ap.place_answers(self.vault.root, now=NOW)
        self.vault.publish()
        labels = set(self.vault.nodes())
        for pronoun in ("they", "he", "him", "them"):
            with self.subTest(pronoun=pronoun):
                self.assertNotIn(pronoun, {label.lower() for label in labels})

    def test_the_placement_loses_nothing(self):
        """The v340/v342 audit over the whole act: nothing placed before is lost,
        moved to an incompatible date, or drawn at a redirected id."""
        ap.place_answers(self.vault.root, now=NOW)
        ts.rebuild_active_index(self.vault.root)
        audit = placement_audit(self.before, self.vault.derived())
        self.assertEqual(audit, {"lost": [], "drawn_at_an_alias": [], "moved": []})

    def test_filing_twice_files_nothing_twice(self):
        first = ap.place_answers(self.vault.root, now=NOW)
        receipts = sorted(ts.receipt_relative_paths(self.vault.root))
        second = ap.place_answers(self.vault.root, now="2026-10-01T00:00:00Z")
        self.assertEqual(sorted(ts.receipt_relative_paths(self.vault.root)), receipts)
        self.assertEqual([row["claim_id"] for row in first["filed"]],
                         [row["claim_id"] for row in second["filed"]])

    def test_a_dry_run_writes_nothing(self):
        before = sorted(ts.receipt_relative_paths(self.vault.root))
        report = ap.place_answers(self.vault.root, dry_run=True, now=NOW)
        self.assertEqual(report["placed"], 3)
        self.assertTrue(report["dry_run"])
        self.assertEqual(sorted(ts.receipt_relative_paths(self.vault.root)), before)

    def test_the_run_is_deterministic_whatever_order_the_answers_arrive_in(self):
        one = ap.place_answers(self.vault.root, dry_run=True, now=NOW)
        two = ap.place_answers(self.vault.root, dry_run=True, now=NOW)
        self.assertEqual(one["filed"], two["filed"])

    def test_restricting_the_run_to_one_answer_places_only_that_one(self):
        every = ap.place_answers(self.vault.root, dry_run=True, now=NOW)["filed"]
        one = every[0]
        report = ap.place_answers(self.vault.root, sources=[one["source_path"]],
                                  dry_run=True, now=NOW)
        self.assertEqual(report["answers"], 1)
        self.assertEqual([row["source_path"] for row in report["filed"]],
                         [one["source_path"]])


class AnAnswerWithNoTimeIsStillATellingTests(unittest.TestCase):
    """"Never silently nothing": the reply is on the node, and the card stays."""

    def setUp(self):
        self.vault = VaultFixture(self)
        self.vault.answer("dog", "I honestly have no idea, it was chaos",
                          "2026-09-24T03:00:00Z")
        self.report = ap.place_answers(self.vault.root, now=NOW)
        self.vault.publish()

    def test_it_files_a_telling_and_not_a_date(self):
        self.assertEqual((self.report["placed"], self.report["tellings"]), (0, 1))
        self.assertEqual(self.report["by_reading"][ap.READING_TELLING], 1)

    def test_the_node_stays_unplaced_and_the_card_stays_open(self):
        self.assertEqual(self.vault.placed("The dog got out"), (None, None))
        self.assertIn("When did The dog got out happen?",
                      {row["prompt_intent"] for row in self.vault.work_items()})

    def test_the_owners_words_are_on_the_node(self):
        """The card stays open WITH THE ANSWER VISIBLE: the claim is an
        occurrence on the card's own node, carrying his sentence as evidence and
        citing the message he typed."""
        index = ts.fold_active_index(self.vault.root)
        ours = [row for row in index["claims"]
                if row.get("extractor_version") == ap.EXTRACTOR_VERSION]
        self.assertEqual(len(ours), 1)
        self.assertEqual(ours[0]["claim_type"], tc.OCCURRENCE_CLAIM_TYPE)
        self.assertIn("no idea", ours[0]["evidence"][0]["quote"])
        node = self.vault.nodes()["The dog got out"]
        self.assertIn(ours[0]["claim_id"], node["input_claim_refs"])

    def test_a_promoted_message_that_answers_no_card_files_nothing(self):
        ts.promote_conversational_source(
            self.vault.root, "Just thinking out loud about the shop",
            {"session_ref": "conversation:local-rig", "turn_ref": "0",
             "speaker": "person"})
        report = ap.place_answers(self.vault.root, now=NOW)
        self.assertEqual(report["answers"], 1)  # the dog answer, and only it


# --------------------------------------------------------------------------
# 4. Aiming a draft somebody else heard
# --------------------------------------------------------------------------

#: The card case 2's reply was answering, as `answer_placement.card_for_answer`
#: hands it over: the work item, the node, the node's own subject and its label.
MISSION_CARD = {
    "work_item_id": "work:" + "a" * 24, "node_ref": "node:" + "b" * 24,
    "subject_ref": "person/james-taylor", "event_kind": "span",
    "label": "Dad's mission", "question": "When was Dad's mission?",
}


class AimingADraftAtItsCardTests(unittest.TestCase):
    """Case 2's draft, verbatim: a time, a pronoun, and no event at all."""

    def owners_draft(self) -> dict:
        draft, finding = gl.validate_claim_draft({
            "claim_type": "age", "subject_mention": "they", "event_kind": "span",
            "temporal_value": "19-21", "evidence": [{"quote": MISSION_REPLY}],
            "basis": "explicit"})
        self.assertEqual(finding, "")
        return draft

    def test_the_pronoun_becomes_the_nodes_own_subject(self):
        aimed = ap.aim_at_card(self.owners_draft(), MISSION_CARD)
        self.assertEqual(aimed["subject_mention"], "person/james-taylor")

    def test_the_draft_gains_the_cards_node_and_label(self):
        aimed = ap.aim_at_card(self.owners_draft(), MISSION_CARD)
        self.assertEqual(aimed["event_ref"], MISSION_CARD["node_ref"])
        self.assertEqual(aimed["event_mention"], "Dad's mission")

    def test_a_name_the_person_used_is_never_overwritten(self):
        draft = {**self.owners_draft(), "subject_mention": "my brother Ben"}
        self.assertEqual(ap.aim_at_card(draft, MISSION_CARD)["subject_mention"],
                         "my brother Ben")

    def test_an_event_the_person_named_is_never_overwritten(self):
        draft = {**self.owners_draft(), "event_mention": "the mission to Chile"}
        self.assertEqual(ap.aim_at_card(draft, MISSION_CARD)["event_mention"],
                         "the mission to Chile")

    def test_the_event_kind_is_left_exactly_as_it_was_heard(self):
        draft = {**self.owners_draft(), "event_kind": "job"}
        self.assertEqual(ap.aim_at_card(draft, MISSION_CARD)["event_kind"], "job")

    def test_every_pronoun_the_owners_answers_filed_is_nobody(self):
        for mention in ("he", "He", "they", "Them", "his", "it"):
            with self.subTest(mention=mention):
                self.assertTrue(ap.is_pronoun_subject(mention))

    def test_the_owners_own_first_person_is_never_rewritten(self):
        """*"I was 19"* answering a card about somebody else's mission is the
        owner talking about himself, and rewriting that would invent a fact."""
        for mention in ("I", "me", "self", "narrator", "we"):
            with self.subTest(mention=mention):
                self.assertFalse(ap.is_pronoun_subject(mention))

    def test_no_card_means_no_aiming(self):
        draft = self.owners_draft()
        self.assertEqual(ap.aim_drafts([draft], None), (draft,))
        self.assertEqual(ap.aim_drafts([draft], {}), (draft,))

    def test_what_counts_as_already_carrying_a_time(self):
        self.assertTrue(ap.drafts_carry_time([self.owners_draft()]))
        self.assertFalse(ap.drafts_carry_time([]))
        self.assertFalse(ap.drafts_carry_time(
            [{"claim_type": tc.OCCURRENCE_CLAIM_TYPE}, {"claim_type": "identity"}]))


class ThePronounDraftLandsOnTheCardTests(unittest.TestCase):
    """The turn's own seat: `landmark_recorder.file_claims`, which already had
    the `session_ref` and never read it."""

    def setUp(self):
        self.vault = VaultFixture(self)
        self.card = self.vault.card_asking_about("mission")

    def file(self, drafts, reply, **kwargs):
        return lr.file_claims(
            self.vault.root, drafts, message_text=reply,
            extractor_version="listener:1",
            session_ref=f"conversation:cand:work_item:{self.card['work_item_id']}",
            turn_ref="0", speaker="person", occurred_at=MISSION_CAPTURED,
            now=NOW, **kwargs)

    def owners_draft(self) -> dict:
        draft, _finding = gl.validate_claim_draft({
            "claim_type": "age", "subject_mention": "they", "event_kind": "span",
            "temporal_value": "19-21", "evidence": [{"quote": MISSION_REPLY}],
            "basis": "explicit"})
        return draft

    def test_the_age_the_listener_heard_places_the_card(self):
        self.assertIsNotNone(self.file([self.owners_draft()], MISSION_REPLY))
        record = self.vault.best("Dad's mission")
        self.assertEqual(record["basis"], "age")
        self.assertEqual((record["earliest"][:4], record["latest"][:4]),
                         ("1973", "1976"))

    def test_it_mints_no_node_labelled_they(self):
        self.file([self.owners_draft()], MISSION_REPLY)
        self.assertNotIn("they", {label.lower() for label in self.vault.nodes()})

    def test_a_message_whose_drafts_carry_no_time_files_the_reading_itself(self):
        """Case 1's shape at this seat: the listener heard nothing, and the reply
        still places the card it answers."""
        cussing = self.vault.card_asking_about("cussing")
        filed = lr.file_claims(
            self.vault.root, [], message_text=CUSSING_REPLY,
            extractor_version="listener:1",
            session_ref=f"conversation:cand:work_item:{cussing['work_item_id']}",
            turn_ref="0", speaker="person", occurred_at=CUSSING_CAPTURED, now=NOW)
        self.assertIsNotNone(filed)
        self.assertEqual(self.vault.placed("Harvey's love of cussing"),
                         ("2026-07-24/2026-09-24", "stated"))

    def test_a_message_with_no_drafts_and_no_card_still_files_nothing(self):
        """The amendment's own rule, unchanged: a message that produced nothing
        and answers nothing files NOTHING."""
        before = sorted(ts.receipt_relative_paths(self.vault.root))
        self.assertIsNone(lr.file_claims(
            self.vault.root, [], message_text="Just thinking out loud",
            extractor_version="listener:1", session_ref="conversation:local-rig",
            turn_ref="0", speaker="person", now=NOW))
        self.assertEqual(sorted(ts.receipt_relative_paths(self.vault.root)), before)

    def test_one_utterance_is_one_promoted_source(self):
        """The reading needs the reply to be a vault source and the listener's
        claims need the same one. `promote_conversational_source` re-reads an
        occupied path, so this is one source and two readings of it."""
        cussing = self.vault.card_asking_about("cussing")
        for _ in range(2):
            lr.file_claims(
                self.vault.root, [], message_text=CUSSING_REPLY,
                extractor_version="listener:1",
                session_ref=f"conversation:cand:work_item:{cussing['work_item_id']}",
                turn_ref="0", speaker="person", occurred_at=CUSSING_CAPTURED, now=NOW)
        promoted = sorted((self.vault.root / "sources" / "conversations").glob("*.md"))
        self.assertEqual(len(promoted), 1)


# --------------------------------------------------------------------------
# 5. The sweep that carries it, and the receipt it writes
# --------------------------------------------------------------------------

class TheSweepCarriesTheRuleTests(unittest.TestCase):
    """`migrate-classifier-moments` is the vault's one deterministic
    claim-filing sweep, and v352 is its second rung."""

    def setUp(self):
        self.vault = VaultFixture(self)
        self.vault.answer("cussing", CUSSING_REPLY, CUSSING_CAPTURED)

    def test_the_migration_places_the_answer_and_reports_it_apart(self):
        report = ccl.migrate_classifier_moments(self.vault.root, dry_run=False, now=NOW)
        self.assertEqual(report["answers"]["placed"], 1)
        self.assertEqual(report["answers"]["extractor_version"], ap.EXTRACTOR_VERSION)
        self.assertEqual(self.vault.placed("Harvey's love of cussing"),
                         ("2026-07-24/2026-09-24", "stated"))

    def test_a_dry_migration_writes_nothing_and_still_counts_the_answer(self):
        before = sorted(ts.receipt_relative_paths(self.vault.root))
        report = ccl.migrate_classifier_moments(self.vault.root, dry_run=True, now=NOW)
        self.assertEqual(report["answers"]["placed"], 1)
        self.assertTrue(report["answers"]["dry_run"])
        self.assertEqual(sorted(ts.receipt_relative_paths(self.vault.root)), before)

    def test_the_two_rungs_are_described_apart(self):
        report = ccl.migrate_classifier_moments(self.vault.root, dry_run=True, now=NOW)
        lines = "\n".join(ccl.describe_migration(report))
        self.assertIn("Answers to cards", lines)
        self.assertIn("placed: 1", lines)

    def test_the_receipt_declares_the_answers_own_telling(self):
        """v337's unit: a reply is a message and the card is ONE fact inside it,
        so the telling ref is ``<promoted source id>#<node hex>`` and two answers
        to one card are two tellings of the SAME fact."""
        filed = ap.place_answers(self.vault.root, now=NOW)["filed"][0]
        receipt = json.loads(
            Path(filed["receipt_path"]).read_text(encoding="utf-8"))
        declared = receipt["extractor"][ei.TELLING_KEYS_FIELD]
        ref = declared[filed["claim_id"]]
        self.assertEqual(ei.telling_source_kind(ref), "conversation")
        self.assertTrue(ref.endswith("#" + filed["node_ref"].split(":")[-1]))
        self.assertEqual(receipt["extractor"]["work_item_id"], filed["work_item_id"])
        self.assertIs(receipt["extractor"]["deterministic"], True)

    def test_the_answers_reading_is_its_own_extractor_and_not_the_listeners(self):
        """Two readings of one message are two interpretations, and a shared
        extractor version would make them one claim that overwrote itself."""
        self.assertNotIn(ap.EXTRACTOR_VERSION,
                         {ccl.CLASSIFIER_EXTRACTOR, "listener:1"})
        self.assertTrue(ap.EXTRACTOR_VERSION.startswith("answer-placement/"))


# --------------------------------------------------------------------------
# 6. Cards before and after, and the release
# --------------------------------------------------------------------------

class CardsBeforeAndAfterTests(unittest.TestCase):
    """What the owner sees: four cards asking, three answered, one still open
    because he said he did not know."""

    def test_cards_by_kind_before_and_after(self):
        vault = VaultFixture(self)
        self.assertEqual(vault.cards_by_kind(), {"precision_gap": 4})
        vault.answer("cussing", CUSSING_REPLY, CUSSING_CAPTURED)
        vault.answer("talking", TALKING_REPLY, TALKING_CAPTURED)
        vault.answer("mission", MISSION_REPLY, MISSION_CAPTURED)
        vault.answer("dog", "No idea at all", "2026-09-24T03:00:00Z")
        report = ap.place_answers(vault.root, now=NOW)
        vault.publish()
        self.assertEqual((report["placed"], report["tellings"]), (3, 1))
        self.assertEqual(vault.cards_by_kind(), {"precision_gap": 1})
        self.assertEqual({row["prompt_intent"] for row in vault.work_items()},
                         {"When did The dog got out happen?"})


class TheReleaseTests(unittest.TestCase):
    """The release ships, and the new files ship with it."""

    def manifest(self) -> dict:
        return json.loads((ROOT / "system" / "version.json").read_text(encoding="utf-8"))

    def test_the_release_has_shipped(self):
        self.assertGreaterEqual(self.manifest()["version"], 352)

    def test_the_new_files_ship_in_framework_files(self):
        shipped = self.manifest()["framework_files"]
        for name in ("system/answer_placement.py",
                     "tests/test_v352_answering_a_card_places_its_moment.py"):
            with self.subTest(name=name):
                self.assertIn(name, shipped)

    def test_the_rule_is_stated_once(self):
        self.assertIn("session_ref", ap.ANSWERING_A_CARD_PLACES_ITS_MOMENT)
        self.assertIn("node the card is about", ap.ANSWERING_A_CARD_PLACES_ITS_MOMENT)

    def test_every_refusal_is_named(self):
        report = ap.empty_report()
        self.assertEqual(sorted(report["refused"]), sorted(ap.REFUSALS))
        self.assertEqual(sorted(report["by_reading"]), sorted(ap.READINGS))

    def test_the_fold_rule_version_does_not_move(self):
        """This release adds CLAIMS; it changes no derivation. A vault nobody
        answered draws exactly what it drew, so the goldens do not move."""
        index = index_of([])
        self.assertEqual(
            tt.derive_calculated_timeline(index, now=NOW).calculation_rule_version,
            tt.CALCULATION_RULE_VERSION)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
