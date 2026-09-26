"""v360 (owner, 2026-09-25): an age belongs to whoever it was said of (lifehug#415,
the classifier seat), and `chronology.parse_age` reads number words.

THE DEFECT, on the owner's own vault. v359 fixed the card-answer seat
(`answer_placement.NARRATOR_AGE_RE`): a first-person age in an answer is the
narrator's. The CLASSIFIER seat still filed the owner's own age under whoever
the event was about, and the fold measures an age from its subject's birth
(v346), so three of his moments were drawn from the wrong birth:

* *"Father's four years bedridden"* (``answers-m1#8a20e7d27020``): ``when I
  was just off my mission, so like 22, 23`` filed as his FATHER's 22-23 and
  drawn 1976-06/1978-06 from the father's 1954-06-04 birth — it is his own
  22-23, 2003-07/2005-07, which is also what the resolver read;
* *"Dad wins pet snake at fair"* (``answers-m4#3d327cf4fe86``): ``I must have
  been like four or five years old`` filed as Dad's (1958-06/1960-06);
* *"Charlee currently 15 and a half"* (``answers-n11#57c96d5f330f``): subject
  *"Narrator and Charlee"* fell back to the owner, so *"Charlee is 15 and a
  half right now"* was measured from HIS birth, 1986-07/1997-07 (``"15.5"``
  also parsed as 5-15). It is Charlee's age, held on the day he said it:
  the moment is the telling's month, 2026-08.

And `parse_age("nineteen to twenty-one")` answered ``(1, 20)``.

Synthetic data only, in the shapes and words of his vault. NEVER references
~/Workspace/dave.
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "system"))
sys.path.insert(0, str(ROOT / "tests"))

import answer_placement as ap  # noqa: E402
import chronology as chrono  # noqa: E402
import classifier_claims as cc  # noqa: E402
import temporal_claims as tc  # noqa: E402
import temporal_store as ts  # noqa: E402
import temporal_timeline as tt  # noqa: E402
from tempdirs import root_parent_tmp  # noqa: E402
from test_v340_apply_keeps_placements import claim, write_vault  # noqa: E402

NOW = "2026-09-25T12:00:00Z"
OWNER = tt.DEFAULT_OWNER_REF
OWNER_BIRTH = "1981-07-11"
FATHER = "person/james-taylor"
FATHER_BIRTH = "1954-06-04"


def _day(token: str) -> dict:
    return {"best": token, "earliest": token, "latest": token,
            "granularity": "day", "basis": "stated", "confidence": "certain"}


def _birth(source: str, subject: str, token: str, label: str) -> dict:
    return claim(source=source, claim_type="date", subject_mention=subject,
                 event_kind="birth", temporal_value=_day(token),
                 event_mention=label)


def _date(age: object = None, anchor_ref: object = None, relation: object = None) -> dict:
    return {"stated": None, "age": age, "anchor_ref": anchor_ref, "relation": relation}


#: The three events, field for field as his classifications carry them.
BEDRIDDEN = {
    "title": "Father's four years bedridden",
    "subject": FATHER,
    "date": _date("22, 23", "author's return from mission", "within"),
    "when_hint": "when I was just off my mission, so like 22, 23",
    "description": ("James became sick and was bedridden for four years, during "
                    "which he became addicted to painkillers and later got off them"),
}
SNAKE = {
    "title": "Dad wins pet snake at fair",
    "subject": FATHER,
    "date": _date("four or five years old"),
    "when_hint": ("The snake was like five times my size so I must have been "
                  "like four or five years old then"),
    "description": ("Dad won a giant pet snake at a fair while on a date with mom "
                    "and brought it home"),
}
CHARLEE = {
    "title": "Charlee currently 15 and a half",
    "subject": "Narrator and Charlee",
    "date": _date("15.5"),
    "when_hint": "Charlee is 15 and a half right now",
    "description": ("Reflection on the current low-conflict relationship with "
                    "Charlee at age 15.5"),
}
CAPTURED = {"answers-m1": "2026-07-19T12:24:32",
            "answers-m4": "2026-07-08T13:40:23",
            "answers-n11": "2026-08-30T14:09:48"}
EVENTS = {"answers-m1": BEDRIDDEN, "answers-m4": SNAKE, "answers-n11": CHARLEE}


# --------------------------------------------------------------------------
# 1. parse_age reads number words
# --------------------------------------------------------------------------


class ParseAgeReadsNumberWordsTests(unittest.TestCase):

    def test_number_words(self):
        for text, expected in (
            ("nineteen to twenty-one", (19, 21, False)),
            ("twenty-two", (22, 22, False)),
            ("twenty two", (22, 22, False)),
            ("four or five", (4, 5, False)),
            ("four or five years old", (4, 5, False)),
            ("thirty-one", (31, 31, False)),
            ("about twenty-one", (21, 21, True)),
            ("twenty or thirty", (20, 30, False)),
            ("ninety", (90, 90, False)),
        ):
            with self.subTest(text=text):
                self.assertEqual(chrono.parse_age(text), expected)

    def test_a_half_is_the_year_the_person_is_in(self):
        for text, expected in (
            ("15.5", (15, 15, False)),
            ("15 and a half", (15, 15, False)),
            ("fifteen and a half", (15, 15, False)),
            ("15 1/2", (15, 15, False)),
            ("probably around 16 maybe 15 1/2", (15, 16, True)),
        ):
            with self.subTest(text=text):
                self.assertEqual(chrono.parse_age(text), expected)

    def test_what_it_read_before_is_read_the_same(self):
        for text, expected in (
            ("about 5", (5, 5, True)), ("5 or 6", (5, 6, False)),
            ("19-21", (19, 21, False)), ("22, 23", (22, 23, False)),
            ("in my twenties", (20, 29, False)), ("20s", (20, 29, False)),
            ("44, almost 45", (44, 45, False)), ("", None), ("never", None),
        ):
            with self.subTest(text=text):
                self.assertEqual(chrono.parse_age(text), expected)

    def test_the_stored_band_follows(self):
        quantity = tc.validate_temporal_quantity("nineteen to twenty-one",
                                                 claim_type="age")
        self.assertEqual((quantity["low"], quantity["high"]), (19.0, 21.0))


# --------------------------------------------------------------------------
# 2. Whose age it is — the one vocabulary
# --------------------------------------------------------------------------


class WhoseAgeTests(unittest.TestCase):

    def test_one_definition_serves_both_seats(self):
        self.assertIs(ap.NARRATOR_AGE_RE, chrono.NARRATOR_AGE_RE)

    def test_first_person(self):
        for text, age in (
            ("when I was just off my mission, so like 22, 23", "22, 23"),
            ("I must have been like four or five years old then", "four or five years old"),
            ("probably when I was 4 or 5", "4"),
            ("I was 19 years old", "19"),
            ("until now, when I'm 45", "45"),
            ("I was seven or nine years old, about that range", "seven or nine"),
        ):
            with self.subTest(text=text):
                self.assertTrue(chrono.age_is_first_person(text, age))
                self.assertEqual(chrono.age_statement_of(text, age)["speaker"], "narrator")

    def test_said_of_someone_else(self):
        for text, age, who, present in (
            ("Charlee is 15 and a half right now", "15.5", "Charlee", True),
            ("she's 15 and a half now", "15 and a half", "she", True),
            ("when AJ was around nine years old", "nine", "AJ", False),
            ("I was there when Dad was 19", "19", "Dad", False),
            ("when my dad was 21", "21", "my dad", False),
        ):
            with self.subTest(text=text):
                self.assertFalse(chrono.age_is_first_person(text, age))
                found = chrono.age_statement_of(text, age)
                self.assertEqual((found["who"], found["present"]), (who, present))

    def test_what_is_nobodys_statement(self):
        # Words between "James was" and the age: never James's 31.
        self.assertIsNone(chrono.age_statement_of(
            "two weeks after James was born, age 31", "31"))
        # A field WIDER than what was said of AJ is not AJ's age.
        self.assertIsNone(chrono.age_statement_of(
            "when AJ was around nine years old", "19 or 20 (author); AJ about 9"))
        self.assertIsNone(chrono.age_statement_of("", "4"))

    def test_now_dates_the_telling_month(self):
        record = chrono.from_present_age("2026-08-30T14:09:48")
        self.assertEqual((record.best, record.granularity, record.basis),
                         ("2026-08", "month", "stated"))
        self.assertIsNone(chrono.from_present_age(None))


# --------------------------------------------------------------------------
# 3. The classifier seat reads the three real shapes
# --------------------------------------------------------------------------


class TheClassifierSeatTests(unittest.TestCase):

    def reading(self, event: dict, captured: str) -> dict:
        return cc.temporal_reading(event, {"captured": captured})

    def test_bedridden_is_the_owners_age(self):
        reading = self.reading(BEDRIDDEN, CAPTURED["answers-m1"])
        self.assertEqual((reading["claim_type"], reading["temporal_value"],
                          reading["subject_mention"]), ("age", "22, 23", OWNER))

    def test_the_snake_is_the_owners_age(self):
        reading = self.reading(SNAKE, CAPTURED["answers-m4"])
        self.assertEqual((reading["claim_type"], reading["subject_mention"]),
                         ("age", OWNER))

    def test_charlee_now_is_the_telling(self):
        reading = self.reading(CHARLEE, CAPTURED["answers-n11"])
        self.assertEqual(reading["claim_type"], "date")
        self.assertEqual(reading["temporal_value"]["best"], "2026-08")
        self.assertEqual(reading["subject_mention"], "Charlee")

    def test_an_age_of_the_events_own_subject_is_unchanged(self):
        event = {"title": "Harvey starts talking", "subject": "Harvey",
                 "date": _date("4"), "when_hint": "when he was 4",
                 "description": "Harvey started talking"}
        reading = self.reading(event, "2026-09-24T01:22:11")
        self.assertNotIn("subject_mention", reading)
        self.assertEqual(reading["claim_type"], "age")

    def test_the_owners_own_event_is_unchanged(self):
        event = {"title": "Went bankrupt", "subject": "Narrator",
                 "date": _date("26"), "when_hint": "when I was 26",
                 "description": "Narrator went bankrupt"}
        self.assertNotIn("subject_mention", self.reading(event, "2026-07-01"))

    def test_the_moment_keeps_its_own_subject(self):
        claims = cc.event_claims(stem="answers-m4", event=SNAKE,
                                 revision="sha256:" + "1" * 64,
                                 source_path="answers/M4.md", now=NOW)
        subjects = sorted((row["claim_type"], row["subject_mention"]) for row in claims)
        self.assertEqual(subjects, [("age", OWNER), (tc.OCCURRENCE_CLAIM_TYPE, FATHER)])
        self.assertEqual(len({row["event_ref"] for row in claims}), 1,
                         "the age stays on the SAME moment")


# --------------------------------------------------------------------------
# 4. End to end on a synthetic vault, and the re-derivation
# --------------------------------------------------------------------------


def _vault(case: unittest.TestCase) -> Path:
    root = root_parent_tmp(case, ROOT, prefix="lifehug-narrator-age-")
    for folder in ("state/classifications", "answers", "state/temporal_claims"):
        (root / folder).mkdir(parents=True, exist_ok=True)
    write_vault(root, [
        _birth("landmark:entry-birth", OWNER, OWNER_BIRTH, "My birth"),
        _birth("classification:sources-dad#cccccccccccc", FATHER, FATHER_BIRTH,
               "Dad's birth"),
    ])
    for stem, event in EVENTS.items():
        relative = f"answers/{stem.split('-')[1].upper()}.md"
        (root / relative).write_text("\n".join([
            "---", 'type: "prompted_answer"',
            f'captured_at: "{CAPTURED[stem]}"', f'source_path: "{relative}"',
            "---", "", event["when_hint"], ""]), encoding="utf-8")
        (root / "state" / "classifications" / f"{stem}.json").write_text(json.dumps({
            "source_path": relative, "source_type": "prompted_answer",
            "people": [], "places": [], "time_periods": [], "themes": [],
            "events": [event]}), encoding="utf-8")
    return root


def _run(root: Path) -> dict:
    return cc.migrate_classifier_moments(
        root, classifications_dir=root / "state" / "classifications",
        dry_run=False, publish=False, now=NOW)


def _nodes(root: Path) -> dict[str, dict]:
    result = tt.derive_calculated_timeline(ts.fold_active_index(root), now=NOW)
    return {row["label"]: row for row in result.nodes if row.get("label")}


def _window(node: dict) -> tuple:
    value = node.get("best_temporal_value") or {}
    return value.get("earliest"), value.get("latest"), value.get("basis")


def _the_old_reading(event: object, age: object) -> dict:
    return {"subject_mention": "", "present": False}


class EndToEndTests(unittest.TestCase):

    def test_each_is_measured_from_the_right_birth(self):
        root = _vault(self)
        _run(root)
        nodes = _nodes(root)
        self.assertEqual(_window(nodes["Father's four years bedridden"]),
                         ("2003-07", "2005-07", "age"))
        self.assertEqual(_window(nodes["Dad wins pet snake at fair"]),
                         ("1985-07", "1987-07", "age"))
        self.assertEqual(_window(nodes["Charlee currently 15 and a half"]),
                         ("2026-08", "2026-08", "stated"))
        self.assertIn(FATHER, nodes["Dad wins pet snake at fair"]["subject_refs"])

    def test_without_the_rule_it_is_the_defect(self):
        root = _vault(self)
        with mock.patch.object(cc, "age_subject", _the_old_reading):
            _run(root)
        nodes = _nodes(root)
        self.assertEqual(_window(nodes["Father's four years bedridden"]),
                         ("1976-06", "1978-06", "age"))
        self.assertEqual(_window(nodes["Dad wins pet snake at fair"]),
                         ("1958-06", "1960-06", "age"))

    def test_a_vault_already_migrated_is_repaired_by_re_reading(self):
        """The old claims are never edited: the same event is re-read, the new
        claim files beside the old, and the old one is superseded by the
        re-classification correction — on the SAME node id."""
        root = _vault(self)
        with mock.patch.object(cc, "age_subject", _the_old_reading):
            _run(root)
        before = {row["label"]: row["node_id"] for row in _nodes(root).values()}
        old = {row["claim_id"] for row in ts.active_claims(ts.fold_active_index(root))
               if row.get("claim_type") == "age"}
        report = _run(root)
        self.assertGreaterEqual(report["superseded_claims"], 3)
        index = ts.fold_active_index(root)
        active = {row["claim_id"] for row in ts.active_claims(index)}
        self.assertFalse(old & active, "every misattributed age is retired")
        scopes = {row.get("scope") for row in index["corrections"]}
        self.assertIn(cc.SUPERSEDE_SCOPE, scopes)
        after = {row["label"]: row["node_id"] for row in _nodes(root).values()}
        self.assertEqual(before, after, "no node re-keys")
        self.assertEqual(_window(_nodes(root)["Father's four years bedridden"]),
                         ("2003-07", "2005-07", "age"))
        again = _run(root)
        self.assertEqual((again["superseded_claims"], again["receipts_written"]), (0, 0),
                         "idempotent")


if __name__ == "__main__":
    unittest.main()
