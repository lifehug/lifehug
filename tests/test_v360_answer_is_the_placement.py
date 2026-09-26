"""v360 (owner, 2026-09-25) — an answer IS the placement, at the grain it was given.

(Renamed ``test_vNNN_*`` when the session's changes are released together.)

THE RULING, the owner's words (2026-09-25):

    "if I say 19 to 21 here, that is a placement because I set it" … "there
    would be answers that come later and that are more specific"

    "If I say 19-21 you can say the start of his birth month to the end range
    of his birth month … I don't care that much about days. … If I give an
    exact date then I care about it."

    "if I say it and get precision, any level of precision, that means I want
    it placed, given the precision I've given you. And later information that
    contradicts it is a question."

WHERE IT WAS SEEN: v359 placed his *"19-21 years old"* on
``node:80f419115b858c37a7b051f3`` "Father's mission to New Zealand" — and the
drawn window stayed the RESOLVER's 1973-06/1976-06, basis ``anchor``, because
v345 (`temporal_timeline.AN_AGE_AND_A_DATE_CORROBORATE`) read an agreeing age as
evidence on a date the resolver had inferred. Measured alone, the answer was
day-exact, 1973-06-04/1976-06-03.

THE RULES (`temporal_timeline.AN_ANSWER_IS_THE_PLACEMENT`,
`chronology.age_statement_record`):

1. What the person said places the moment. The resolver's inference, a
   classifier estimate, a coarser statement: every reading that FITS is
   supporting evidence on it, never a rival, and nothing inferred narrows it.
2. At the grain it was said: an age from a day-precise birth is held at the
   birthday's MONTH, and a band reads as the stretch it names.
3. A later statement of theirs that fits inside and is finer narrows it; one
   that does not fit is a rival, and the contradiction card names both.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "system"))
sys.path.insert(0, str(ROOT / "tests"))

import answer_placement as ap  # noqa: E402
import chronology as chrono  # noqa: E402
import temporal_publication as pub  # noqa: E402
import temporal_timeline as tt  # noqa: E402
from test_v340_apply_keeps_placements import NOW, claim, write_vault  # noqa: E402
from test_v345_a_telling_of_a_landmark_folds_onto_it import (  # noqa: E402
    placement_audit,
)
from test_v352_answering_a_card_places_its_moment import (  # noqa: E402
    FATHER_BIRTH,
    MISSION_CAPTURED,
    MISSION_REPLY,
)
from test_v359_an_answer_outlives_its_card import (  # noqa: E402
    RESOLVER_WINDOW,
    Vault,
)

#: The owner's answer, at the grain he gave it: his father's birth MONTH at 19
#: to his birth month at the end of 21.
MISSION_PLACED = ("1973-06/1976-06", "1973-06", "1976-06")

NODE = "node:" + "a" * 24


def group(*claims) -> dict:
    return {"node_id": NODE, "event_kind": "moment", "claims": list(claims)}


def age(low: int, high: int, *, source: str = "conversation:msg-answer",
        text: str = "") -> dict:
    return claim(source=source, claim_type="age",
                 subject_mention="person/james-taylor", event_kind="moment",
                 temporal_value={"kind": "age", "unit": "years", "low": low,
                                 "high": high, "approximate": False,
                                 "text": text or f"{low}-{high}"},
                 confidence=0.7)


def stated(token: str, *, source: str = "conversation:msg-later") -> dict:
    grain = {4: "year", 7: "month", 10: "day"}[len(token)]
    return claim(source=source, claim_type="date",
                 subject_mention="person/james-taylor", event_kind="moment",
                 temporal_value={"best": token, "earliest": token, "latest": token,
                                 "granularity": grain, "basis": "stated",
                                 "confidence": "certain"})


def inferred(value: dict, *, source: str = "resolver:aaaaaaaaaaaaaaaaaaaaaaaa") -> dict:
    return claim(source=source, source_kind="system_derived", claim_type="date",
                 subject_mention="person/james-taylor", event_kind="moment",
                 temporal_value=value, basis="inferred", confidence=0.8,
                 extractor_version="resolver/rule:3")


def reconcile(*claims) -> tuple[dict, list]:
    diagnostics: list = []
    out = tt._reconcile_group(group(*claims), birth=FATHER_BIRTH,
                              diagnostics=diagnostics)
    return out, diagnostics


def window(record) -> tuple:
    return (chrono.to_edtf(record), record.earliest, record.latest)


# --------------------------------------------------------------------------
# 1. The grain an age is said at
# --------------------------------------------------------------------------

class AnAgeIsHeldAtTheGrainItWasSaidTests(unittest.TestCase):

    def test_19_to_21_from_his_fathers_birth_is_month_grained(self):
        record = chrono.age_statement_record(FATHER_BIRTH, 19, 21, claim="19-21")
        self.assertEqual(window(record), MISSION_PLACED)
        self.assertEqual((record.granularity, record.basis), ("range", "age"))

    def test_the_arithmetic_is_still_from_age_bands_and_only_widens(self):
        exact = chrono.from_age_band(FATHER_BIRTH, 19, 21)
        self.assertEqual((exact.earliest, exact.latest), ("1973-06-04", "1976-06-03"))
        held = chrono.age_statement_record(FATHER_BIRTH, 19, 21)
        self.assertEqual(chrono.intersect(exact, held).earliest, exact.earliest)
        self.assertEqual(chrono.intersect(exact, held).latest, exact.latest)

    def test_a_single_age_keeps_its_hedged_point(self):
        record = chrono.age_statement_record(FATHER_BIRTH, 21, 21)
        self.assertEqual(window(record), ("1975~", "1975-06", "1976-06"))

    def test_a_hedged_age_keeps_the_owners_own_example(self):
        """*"about 5"* reads *around* a year — the hedge is the reading."""
        record = chrono.age_statement_record("1979-03-02", 5, 5, approximate=True)
        self.assertEqual(chrono.to_edtf(record), "1984~")
        self.assertEqual((record.earliest, record.latest), ("1983-03", "1986-03"))

    def test_a_year_birth_gives_a_year_window(self):
        record = chrono.age_statement_record("1954", 19, 21)
        self.assertEqual(window(record), ("1973/1976", "1973", "1976"))

    def test_at_grain_leaves_a_coarser_record_alone(self):
        record = chrono.parse_edtf("1973-06/1976-06")
        self.assertIs(chrono.at_grain(record, "month"), record)


# --------------------------------------------------------------------------
# 2. The rule, one node at a time
# --------------------------------------------------------------------------

class WhatTheySaidPlacesTheMomentTests(unittest.TestCase):

    def test_the_answer_places_and_the_agreeing_inference_supports(self):
        answer, resolver = age(19, 21), inferred(RESOLVER_WINDOW)
        out, diagnostics = reconcile(answer, resolver)
        self.assertEqual(window(out["best"]), MISSION_PLACED)
        self.assertEqual(out["best"].basis, "age")
        ids = [row.get("claim_id") for row in out["best"].provenance]
        self.assertEqual(ids[-2:], [answer["claim_id"], resolver["claim_id"]])
        self.assertEqual((out["alternates"], out["conflict"]), ([], 0.0))
        [finding] = [row for row in diagnostics
                     if row["finding"] == tt.DIAGNOSTIC_ANSWER_IS_THE_PLACEMENT]
        self.assertEqual((finding["placed_basis"], finding["stood_aside"],
                          finding["stood_aside_basis"], finding["fits"]),
                         ("age", "1973-06/1976-06", "anchor", True))

    def test_without_the_rule_the_resolver_placed_it(self):
        """The defect, reproduced by switching the rule off."""
        out = tt._reconcile_group(group(age(19, 21), inferred(RESOLVER_WINDOW)),
                                  birth=FATHER_BIRTH, diagnostics=[],
                                  what_they_said_places=False)
        self.assertEqual(out["best"].basis, "anchor")

    def test_a_finer_inference_inside_never_narrows_it(self):
        out, _ = reconcile(age(19, 21), inferred(
            {"best": "1974-03", "earliest": "1974-03", "latest": "1974-03",
             "granularity": "month", "basis": "anchor", "confidence": "inferred"}))
        self.assertEqual(window(out["best"]), MISSION_PLACED)
        self.assertEqual(out["alternates"], [])

    def test_a_later_finer_statement_inside_narrows_it(self):
        answer = age(19, 21)
        out, _ = reconcile(answer, stated("1974-02"), inferred(RESOLVER_WINDOW))
        self.assertEqual(window(out["best"]), ("1974-02", "1974-02", "1974-02"))
        ids = {row.get("claim_id") for row in out["best"].provenance}
        self.assertIn(answer["claim_id"], ids)   # the outer bound, kept as support
        self.assertEqual(out["alternates"], [])

    def test_a_coarser_statement_that_contains_it_is_not_a_card(self):
        """Their own coarser date is "the same claim said less well": the
        alternate it always was, at conflict 0 — never a card."""
        coarse = claim(source="conversation:msg-seventies", claim_type="date",
                       subject_mention="person/james-taylor", event_kind="moment",
                       temporal_value={"best": "197X", "earliest": "1970",
                                       "latest": "1979", "granularity": "era",
                                       "basis": "stated", "confidence": "certain"})
        out, _ = reconcile(coarse, age(19, 21))
        self.assertEqual(window(out["best"]), MISSION_PLACED)
        self.assertEqual([chrono.to_edtf(r) for r in out["alternates"]], ["197X"])
        self.assertEqual(out["conflict"], 0.0)

    def test_a_statement_that_does_not_fit_is_a_rival_and_a_contradiction(self):
        out, _ = reconcile(age(19, 21), stated("1980"))
        self.assertEqual(len(out["alternates"]), 1)
        self.assertGreaterEqual(out["conflict"], tt.MATERIAL_CONFLICT)

    def test_an_inference_that_does_not_fit_is_a_rival_and_a_contradiction(self):
        out, _ = reconcile(age(19, 21), inferred(
            {"best": "1990", "earliest": "1990", "latest": "1990",
             "granularity": "year", "basis": "stated", "confidence": "certain"}))
        self.assertEqual(out["best"].basis, "age")
        self.assertEqual([chrono.to_edtf(r) for r in out["alternates"]], ["1990"])
        self.assertGreaterEqual(out["conflict"], tt.MATERIAL_CONFLICT)

    def test_a_resolver_carrying_their_stated_date_is_their_words(self):
        """``explicit`` + ``stated`` from the resolver is the person's own date
        carried onto the moment (the owner's "Father dies of COVID — March
        2020–June 2020"), so a mis-attributed age cannot outrank it."""
        carried = claim(source="resolver:bbbbbbbbbbbbbbbbbbbbbbbb",
                        source_kind="system_derived", claim_type="date",
                        subject_mention="person/james-taylor", event_kind="moment",
                        temporal_value={"best": "2020-03/2020-06",
                                        "earliest": "2020-03", "latest": "2020-06",
                                        "granularity": "range", "basis": "stated",
                                        "confidence": "certain"},
                        extractor_version="resolver/rule:3")
        out, _ = reconcile(age(21, 21, source="classification:answers-m5#aaaaaaaaaaaa"),
                           carried)
        self.assertEqual(chrono.to_edtf(out["best"]), "2020-03/2020-06")

    def test_a_node_nobody_dated_in_their_own_words_is_unchanged(self):
        diagnostics: list = []
        out = tt._reconcile_group(group(inferred(RESOLVER_WINDOW)),
                                  birth=FATHER_BIRTH, diagnostics=diagnostics)
        self.assertEqual((chrono.to_edtf(out["best"]), out["best"].basis),
                         ("1973-06/1976-06", "anchor"))
        self.assertEqual(diagnostics, [])

    def test_the_calculation_rule_moved(self):
        self.assertEqual(tt.CALCULATION_RULE_VERSION, "timeline-rules:25")


# --------------------------------------------------------------------------
# 3. End to end, in the incident's order
# --------------------------------------------------------------------------

class HisAnswerPlacesHisFathersMissionTests(unittest.TestCase):
    """Card shown, the resolver dates the node, the card leaves, the answer
    arrives — v359's order — and now the answer is what is drawn."""

    def setUp(self):
        self.vault = Vault(self)
        card = self.vault.card("mission")
        self.work_item, self.node = card["work_item_id"], card["node_ref"]
        self.vault.close_by_resolver(self.node)
        self.before = self.vault.derived()
        self.promoted = self.vault.answer_card(self.work_item, MISSION_REPLY,
                                               MISSION_CAPTURED)
        ap.place_answers(self.vault.root, now=NOW)
        self.vault.publish()

    def node_row(self) -> dict:
        return self.vault.nodes()["Dad's mission"]

    def test_the_mission_is_drawn_at_his_answer_month_grained(self):
        record = self.vault.best("Dad's mission")
        self.assertEqual((record["best"], record["earliest"], record["latest"]),
                         MISSION_PLACED)
        self.assertEqual(record["basis"], "age")
        answer = self.vault.claims_from(self.promoted.source_path)[0]["claim_id"]
        # His answer (after the father's birth it was measured from), THEN the
        # resolver's reading as the support it now is.
        sources = [(row.get("claim_id"), row.get("source", "").split(":")[0])
                   for row in record["provenance"] if row.get("claim_id")]
        self.assertEqual([kind for _, kind in sources],
                         ["classification", "conversation", "resolver"])
        self.assertEqual(sources[1][0], answer)
        self.assertEqual(self.node_row()["alternate_values"], [])
        self.assertEqual(self.node_row()["conflict_state"], "none")

    def test_the_placement_loses_nothing(self):
        self.assertEqual(placement_audit(self.before, self.vault.derived()),
                         {"lost": [], "drawn_at_an_alias": [], "moved": []})

    def test_a_later_finer_answer_narrows_it(self):
        self.vault.answer_card(self.work_item, "February 1974", "2026-09-25T18:00:00Z")
        ap.place_answers(self.vault.root, now=NOW)
        self.vault.publish()
        record = self.vault.best("Dad's mission")
        self.assertEqual((record["best"], record["basis"]), ("1974-02", "stated"))
        self.assertEqual(self.node_row()["alternate_values"], [])

    def test_a_later_answer_that_does_not_fit_is_a_question(self):
        self.vault.answer_card(self.work_item, "1980", "2026-09-25T18:00:00Z")
        ap.place_answers(self.vault.root, now=NOW)
        self.vault.publish()
        self.assertEqual(self.node_row()["conflict_state"], "contradicted")
        cards = [row for row in self.vault.work_items()
                 if row.get("kind") == "contradiction"
                 and row.get("node_ref") == self.node]
        self.assertEqual(len(cards), 1)


if __name__ == "__main__":
    unittest.main()
