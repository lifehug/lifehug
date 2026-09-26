"""v360 (owner, 2026-09-25) — cornerstones.

(Renamed ``test_vNNN_*`` when the session's changes are released together.)

THE RULING, the owner's words (2026-09-25):

    "I think the precision I give you is enough to make a placement. If the
    system realizes that higher precision for a certain card or question would
    place a lot of other things, that should raise its likelihood of being
    asked. We almost never need more than month precision except for extremely
    important dates like birth, death, wedding, divorce."

    "I like Cornerstones … I agree with that set. If I happen to mention a
    cornerstone for someone else in a discussion, I think it's worth a
    question. For example, 'When did your sister get divorced?' You accept the
    precision I give you, which is probably not a date but more like a month or
    a year. And yes marriages should become spans and stay open while you're
    married." ("I'm still married to Katie and will be till I die.")

THE RULES:

* `cornerstones.CORNERSTONES` — the set, over `temporal_claims.EVENT_KINDS` and
  the roster's relationship words;
* `temporal_work_items.A_DAY_IS_ASKED_ONLY_OF_A_CORNERSTONE` — a cornerstone is
  asked to the day (missing, or placed coarser than a day); a cornerstone-type
  event outside the set is asked ONCE, at any grain; nothing else below a month;
* `chronology.A_WORKED_OUT_DAY_IS_SHOWN_AS_ITS_MONTH` — display only;
* `temporal_timeline.A_MARRIAGE_IS_A_SPAN` (`timeline-rules:20`);
* `episode_binder.A_TELLING_OF_HIS_WEDDING_IS_THE_CORNERSTONE`.

Synthetic data only.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "system"))
sys.path.insert(0, str(ROOT / "tests"))

import axis_membership as axm  # noqa: E402
import chronology as chrono  # noqa: E402
import cornerstones as cs  # noqa: E402
import episode_binder as eb  # noqa: E402
import identity_resolution as ident  # noqa: E402
import temporal_claims as tc  # noqa: E402
import temporal_timeline as tt  # noqa: E402
import temporal_work_items as twi  # noqa: E402
from test_v340_apply_keeps_placements import NOW, claim, index_of, value  # noqa: E402

ROSTER = {"version": 1, "type": "person", "entities": [
    {"name": "Harvey Rex Taylor", "slug": "harvey-rex-taylor", "relationship": "child",
     "aliases": ["Harvey"]},
    {"name": "Katie Ann Merrill", "slug": "katie-ann-merrill", "relationship": "spouse",
     "aliases": ["Katie", "my wife"]},
    {"name": "Jacque Cook", "slug": "jacque-cook", "relationship": "sibling",
     "aliases": ["Jacque", "my sister"]},
    {"name": "James Taylor", "slug": "james-taylor", "relationship": "parent",
     "aliases": ["dad", "father"]},
    {"name": "Sam Friend", "slug": "sam-friend", "relationship": "friend"},
]}


def owner_birth() -> dict:
    return claim(source="classification:answers-a1#aaaaaaaaaaa1", claim_type="date",
                 subject_mention="self", event_kind="birth",
                 temporal_value=value("1981-07-11"), event_mention="my birth")


def undated(mention: str, subject: str, kind: str, source: str) -> dict:
    return claim(source=source, claim_type="occurrence", subject_mention=subject,
                 event_kind=kind, event_mention=mention)


def dated(mention: str, subject: str, kind: str, token: str, source: str, *,
          basis: str = "stated") -> dict:
    record = value(token)
    record["basis"] = basis
    return claim(source=source, claim_type="date", subject_mention=subject,
                 event_kind=kind, event_mention=mention, temporal_value=record)


def derive(*claims):
    return tt.derive_calculated_timeline(index_of([owner_birth(), *claims]),
                                         roster_snapshot=ROSTER, now=NOW)


def node_labelled(result, label: str) -> dict:
    rows = [node for node in result.nodes if node.get("label") == label]
    assert len(rows) == 1, (label, [node.get("label") for node in result.nodes])
    return rows[0]


def cards_on(result, node: dict) -> list[dict]:
    return [row for row in result.work_items if row.get("node_ref") == node["node_id"]]


HARVEY = ("Harvey's birth", "Harvey Rex Taylor", "birth",
          "classification:answers-b2#bbbbbbbbbbb2")
SISTERS_DIVORCE = ("Jacque's divorce", "Jacque Cook", "divorced",
                   "classification:answers-c3#ccccccccccc3")


# --------------------------------------------------------------------------
# 1. The term and the set
# --------------------------------------------------------------------------


class TheSetIsWrittenOverTheVocabularyThatExistsTests(unittest.TestCase):

    def test_every_cornerstone_kind_is_a_seeded_event_kind(self):
        self.assertLessEqual(set(cs.MILESTONE_OF_EVENT_KIND), set(tc.EVENT_KINDS))

    def test_every_relationship_is_the_rosters_own_word(self):
        words = {word for _, whose in cs.CORNERSTONES for word in whose} - {cs.SELF}
        self.assertLessEqual(words, set(axm.IMMEDIATE_FAMILY_RELATIONSHIPS))

    def test_the_set_is_the_owners(self):
        self.assertEqual(cs.WHOSE["birth"],
                         {"self", "child", "parent", "sibling", "spouse"})
        self.assertEqual(cs.WHOSE["death"],
                         {"parent", "spouse", "sibling", "child", "grandparent"})
        self.assertEqual(cs.WHOSE["wedding"], {"self", "spouse"})
        self.assertEqual(cs.WHOSE["divorce"], {"self", "spouse"})
        self.assertEqual(cs.WHOSE["baptism"], {"self"})

    def test_whose_a_node_is(self):
        relations = cs.Relations(ROSTER)
        cases = {
            ("birth", "Harvey's birth", ("Harvey Rex Taylor",)): cs.CORNERSTONE,
            ("moment", "Father dies of COVID", ("narrator's father",)): cs.CORNERSTONE,
            ("moment", "Father's death", ("self",)): cs.CORNERSTONE,
            ("divorced", "Jacque's divorce", ("Jacque Cook",)): cs.OUTSIDE_THE_SET,
            ("married", "Sam's wedding", ("Sam Friend",)): cs.OUTSIDE_THE_SET,
            ("married", "Married Katie", ("self",)): cs.CORNERSTONE,
            ("moment", "Dad's words of pride before death", ("self",)):
                cs.NOT_A_CORNERSTONE,
            ("moment", "Begins processing father's death", ("self",)):
                cs.NOT_A_CORNERSTONE,
        }
        for (kind, label, subjects), want in cases.items():
            with self.subTest(label=label):
                node = {"event_kind": kind, "label": label, "node_kind": "event",
                        "subject_refs": list(subjects)}
                self.assertEqual(cs.node_status(node, relations)[0], want)


# --------------------------------------------------------------------------
# 2. Asking
# --------------------------------------------------------------------------


class ACornerstoneIsAskedToTheDayTests(unittest.TestCase):

    def test_a_missing_child_birth_is_a_day_card(self):
        result = derive(undated(*HARVEY))
        cards = cards_on(result, node_labelled(result, "Harvey Rex Taylor's birth"))
        self.assertEqual([row["kind"] for row in cards], ["precision_gap"])
        self.assertEqual(cards[0][twi.REQUESTED_GRAIN_KEY], "day")

    def test_a_child_birth_held_to_a_year_is_asked_for_its_day(self):
        result = derive(dated(*HARVEY[:3], "2021", HARVEY[3]))
        node = node_labelled(result, "Harvey Rex Taylor's birth")
        self.assertTrue(node["usable_placement"] if "usable_placement" in node else True)
        cards = cards_on(result, node)
        self.assertEqual(len(cards), 1)
        self.assertEqual(cards[0][twi.REQUESTED_GRAIN_KEY], "day")
        self.assertIn("day", cards[0]["prompt_intent"])

    def test_a_parents_death_held_to_a_stretch_keeps_its_card(self):
        """The ~12-month stakes gate would drop a `moment` held to three months
        with nothing waiting on it; this is his father's death."""
        stretch = {"best": "2020-03/2020-06", "earliest": "2020-03", "latest": "2020-06",
                   "granularity": "range", "basis": "stated", "confidence": "certain"}
        death = claim(source="classification:answers-d4#ddddddddddd4", claim_type="range",
                      subject_mention="narrator's father", event_kind="moment",
                      event_mention="Father dies of COVID", temporal_value=stretch)
        result = derive(death)
        cards = cards_on(result, node_labelled(result, "Father dies of COVID"))
        self.assertEqual(len(cards), 1, cards)
        self.assertEqual(cards[0][twi.REQUESTED_GRAIN_KEY], "day")

    def test_a_cornerstone_held_to_the_day_is_never_asked(self):
        result = derive(dated(*HARVEY[:3], "2021-10-11", HARVEY[3]))
        self.assertEqual(cards_on(result, node_labelled(result, "Harvey Rex Taylor's birth")), [])

    def test_the_owners_birth_origin_asks_for_the_day(self):
        result = tt.derive_calculated_timeline(index_of([undated(*HARVEY)]),
                                               roster_snapshot=ROSTER, now=NOW)
        origin = [row for row in result.work_items
                  if row.get("requested_field") == twi.REQUESTED_FIELD_BIRTH_DATE]
        for row in origin:
            self.assertEqual(row[twi.REQUESTED_GRAIN_KEY], "day")


class NothingElseIsAskedBelowAMonthTests(unittest.TestCase):

    def test_a_residence_at_month_grain_gets_no_card(self):
        move = dated("Moved to Mesa", "self", "move", "1995-06",
                     "classification:answers-e5#eeeeeeeeeee5")
        result = derive(move)
        self.assertEqual(cards_on(result, node_labelled(result, "Moved to Mesa")), [])

    def test_an_undated_anecdote_is_never_asked_for_a_day(self):
        story = undated("Camping at the lake", "self", "moment",
                        "classification:answers-f6#fffffffffff6")
        result = derive(story)
        for row in cards_on(result, node_labelled(result, "Camping at the lake")):
            self.assertNotEqual(row[twi.REQUESTED_GRAIN_KEY], "day")
            self.assertIn(row[twi.REQUESTED_GRAIN_KEY], ("month", "year"))

    def test_leverage_ranks_a_card_and_never_changes_its_grain(self):
        for status, want in ((cs.NOT_A_CORNERSTONE, "month"),
                             (cs.OUTSIDE_THE_SET, "year"),
                             (cs.CORNERSTONE, "day")):
            with self.subTest(status=status):
                # The day-grained table target (a birth) never leaks into a
                # non-cornerstone's grain: a month is the finest it gets.
                self.assertEqual(twi.precision_card_grain(status=status, target="day"), want)
        self.assertEqual(twi.precision_card_grain(status="", target="year"), "year")
        self.assertFalse(twi.a_cornerstone_keeps_its_card(
            {"kind": "precision_gap", twi.REQUESTED_GRAIN_KEY: "month", "resolves": ["x"]}))


class ACornerstoneOutsideTheSetIsAskedOnceTests(unittest.TestCase):

    def test_the_sisters_divorce_is_one_card_accepted_at_a_year(self):
        result = derive(undated(*SISTERS_DIVORCE))
        node = node_labelled(result, "Jacque's divorce")
        cards = cards_on(result, node)
        self.assertEqual(len(cards), 1)
        self.assertEqual(cards[0][twi.REQUESTED_GRAIN_KEY], "year")
        # He answers with a year. It is placed, and never asked again.
        answer = dated(*SISTERS_DIVORCE[:3], "2012",
                       "conversation:msg-divorce-answer")
        after = derive(undated(*SISTERS_DIVORCE), answer)
        placed = node_labelled(after, "Jacque's divorce")
        self.assertEqual(placed["best_temporal_value"]["best"], "2012")
        self.assertEqual(cards_on(after, placed), [])

    def test_a_friends_wedding_off_his_axis_still_gets_its_one_card(self):
        wedding = undated("Sam's wedding", "Sam Friend", "married",
                          "classification:answers-g7#ggggggggggg7")
        result = derive(wedding)
        cards = cards_on(result, node_labelled(result, "Sam's wedding"))
        self.assertEqual(len(cards), 1)
        self.assertEqual(cards[0][twi.REQUESTED_GRAIN_KEY], "year")


# --------------------------------------------------------------------------
# 3. Display grain
# --------------------------------------------------------------------------


class AWorkedOutDayIsShownAsItsMonthTests(unittest.TestCase):

    def test_a_derived_day_displays_as_a_month(self):
        record = {"best": "1989-06-14", "earliest": "1989-06-14", "latest": "1989-06-14",
                  "granularity": "day", "basis": "anchor", "confidence": "inferred"}
        self.assertEqual(chrono.display_date(record, with_basis=False), "around June 1989")
        frame = {"best": "1981-07-11/1994-07-10", "earliest": "1981-07-11",
                 "latest": "1994-07-10", "granularity": "range", "basis": "anchor",
                 "confidence": "certain"}
        self.assertEqual(chrono.display_date(frame, with_basis=False), "July 1981–July 1994")

    def test_a_stated_day_displays_as_a_day(self):
        self.assertEqual(chrono.display_date(value("2007-01-11"), with_basis=False),
                         "11 January 2007")

    def test_a_definitional_day_is_the_landmarks_own_and_displays_as_a_day(self):
        record = {"best": "1976-06-25", "earliest": "1976-06-25", "latest": "1976-06-25",
                  "granularity": "day", "basis": "anchor", "confidence": "certain"}
        self.assertEqual(chrono.display_date(record, with_basis=False), "25 June 1976")

    def test_the_stored_interval_keeps_its_day(self):
        record = chrono.from_dict({"best": "1989-06-14", "earliest": "1989-06-14",
                                   "latest": "1989-06-14", "granularity": "day",
                                   "basis": "anchor", "confidence": "inferred"})
        chrono.display_date(record)
        self.assertEqual(record.earliest, "1989-06-14")

    def test_the_age_frames_the_fold_draws_display_at_months(self):
        result = derive()
        frame = next(node for node in result.nodes
                     if node.get("event_kind") == "age_frame")
        self.assertNotRegex(chrono.display_date(frame["best_temporal_value"],
                                                with_basis=False), r"^\d+ ")


# --------------------------------------------------------------------------
# 4. Marriages are spans
# --------------------------------------------------------------------------


WEDDING = ("Married Katie", "self", "married", "2007-01-11",
           "classification:answers-h8#hhhhhhhhhhh8")


class AMarriageIsASpanTests(unittest.TestCase):

    def test_a_marriage_is_an_open_span_from_the_wedding(self):
        result = derive(dated(*WEDDING))
        span = node_labelled(result, "Marriage to Katie Ann Merrill")
        best = span["best_temporal_value"]
        self.assertEqual(best["earliest"], "2007-01-11")
        self.assertIsNone(best["latest"])
        self.assertEqual(best["best"], "2007-01-11/..")
        self.assertEqual(span["event_kind"], tt.MARRIAGE_SPAN_EVENT_KIND)
        self.assertEqual(span["axis_membership"], "owner")
        # The wedding itself stays a point cornerstone at the span's start.
        wedding = node_labelled(result, "Married Katie")
        self.assertEqual(wedding["best_temporal_value"]["best"], "2007-01-11")
        self.assertEqual(cards_on(result, wedding), [])
        self.assertEqual(cards_on(result, span), [])

    def test_a_divorce_closes_it(self):
        divorce = dated("Divorced Katie", "self", "divorced", "2015-03",
                        "classification:answers-i9#iiiiiiiiiii9")
        result = derive(dated(*WEDDING), divorce)
        best = node_labelled(result, "Marriage to Katie Ann Merrill")["best_temporal_value"]
        self.assertEqual((best["earliest"], best["latest"]), ("2007-01-11", "2015-03"))

    def test_no_wedding_no_span(self):
        result = derive(undated(*HARVEY))
        self.assertFalse([node for node in result.nodes
                          if node.get("event_kind") == tt.MARRIAGE_SPAN_EVENT_KIND])

    def test_the_rule_version_moved(self):
        self.assertEqual(tt.CALCULATION_RULE_VERSION, "timeline-rules:25")


# --------------------------------------------------------------------------
# 5. A telling of his wedding IS the cornerstone
# --------------------------------------------------------------------------


STATED_TELLING = "classification:sources-manual-married-katie#aaaaaaaaaaaa"
AGE_TELLING = "classification:answers-a15#bbbbbbbbbbbb"


def stated_wedding() -> dict:
    return claim(source=STATED_TELLING, claim_type="date", subject_mention="self",
                 event_kind="moment", event_mention="Married Katie",
                 temporal_value=value("2007-01-11"),
                 quote="Well, I married Katie on January 11, 2007")


def age_wedding() -> dict:
    return claim(source=AGE_TELLING, claim_type="age", subject_mention="self",
                 event_kind="moment", event_mention="Marriage to Katie",
                 temporal_value={"kind": "age", "unit": "years", "low": 20, "high": 26,
                                 "approximate": False, "text": "26 (Katie was 20)"},
                 quote="Author married Katie when he was 26 and she was 20.")


class ATellingOfHisWeddingFoldsOntoItTests(unittest.TestCase):

    def setUp(self):
        self.views = eb.telling_views([stated_wedding(), age_wedding()])

    def test_marriage_to_someone_is_the_wedding(self):
        self.assertEqual(eb.milestone_of(self.views[AGE_TELLING]), "married")
        self.assertEqual(eb.milestone_of(self.views[STATED_TELLING]), "married")

    def test_marriage_as_a_state_is_not(self):
        hard = claim(source="classification:answers-j1#jjjjjjjjjjj1", claim_type="occurrence",
                     subject_mention="self", event_kind="moment",
                     event_mention="Marriage became hard")
        view = next(iter(eb.telling_views([hard]).values()))
        self.assertEqual(eb.milestone_of(view), "")

    def test_the_owners_couple_buckets_tellings_that_name_no_second_person(self):
        for ref in (AGE_TELLING, STATED_TELLING):
            self.assertEqual(self.views[ref].people, frozenset())
            self.assertEqual(ident.couple_key(self.views[ref].subject_mentions),
                             "couple:spouse")
        pairs = {frozenset((link.left, link.right)): link.key
                 for link in eb.milestone_links(self.views)}
        self.assertEqual(pairs.get(frozenset((AGE_TELLING, STATED_TELLING))),
                         "married:couple:spouse")

    def test_the_folded_age_is_evidence_on_the_wedding_day(self):
        """Once one episode, the fold places it at the stated day and the age —
        whose window contains it — corroborates (`AN_ANSWER_IS_THE_PLACEMENT`)."""
        diagnostics: list = []
        group = {"node_id": "node:" + "c" * 24, "event_kind": "moment",
                 "claims": [stated_wedding(), age_wedding()]}
        out = tt._reconcile_group(  # noqa: SLF001
            group, birth=chrono.from_dict(value("1981-07-11")), diagnostics=diagnostics)
        self.assertEqual(chrono.to_edtf(out["best"]), "2007-01-11")
        self.assertEqual(out["alternates"], [])
        self.assertIn(tt.DIAGNOSTIC_AGE_CORROBORATES,
                      {row["finding"] for row in diagnostics})

    def test_the_rule_is_written_down(self):
        self.assertIn("marriage to", eb.A_TELLING_OF_HIS_WEDDING_IS_THE_CORNERSTONE)
        self.assertIn("DAY", twi.A_DAY_IS_ASKED_ONLY_OF_A_CORNERSTONE.upper())
        self.assertIn("month", chrono.A_WORKED_OUT_DAY_IS_SHOWN_AS_ITS_MONTH)


if __name__ == "__main__":
    unittest.main()
