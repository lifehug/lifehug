"""v360 (owner, 2026-09-25) — v358's "stated" basis, extended to read the owner's own tellings.

THE PROBLEM (2026-09-25 session, v360):
v358 (`relation_words.py`) derived ``relation_gender`` only from roster
spellings, a `family` landmark record and the v346/v347 introduction reader
(`roster_relations.relationship_phrase_match`). It never read an ORDINARY
phrase in the owner's own telling ("I'm just sitting here with my boy
Harvey") or a classification summary's third-person shape ("Son Harvey born
…", "Birth of the author's son Harvey Rex Taylor"), so the vault kept
minting a `relation_word` card for a person he had already, in his own words,
called a son.

This file is v360's own synthetic-vault test, on top of
`test_v358_a_gendered_word_when_it_is_known.py`'s fixtures and conventions —
nothing here reads a real vault.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "system"))
sys.path.insert(0, str(ROOT / "tests"))

import relation_words as rw  # noqa: E402

OWNER_NAMES = ("Dave", "David James Taylor")


def entity(name, slug, relationship, **extra):
    out = {"name": name, "slug": slug, "relationship": relationship,
           "aliases": [], "qualifies": False, "maps_to_focus": None,
           "score": 0.0, "unique_answers": 0, "page_eligible": False}
    out.update(extra)
    return out


def texts(*quotes, source="classification:answers-c1#aaaaaaaaaaaa") -> dict:
    return {source: list(quotes)}


class MyBoyHarveyTests(unittest.TestCase):
    """"my boy Harvey" — the informal child word, in the owner's own voice."""

    def test_my_boy_harvey_is_male(self):
        harvey = entity("Harvey", "harvey", "child")
        found = rw.stated_relation_gender(
            harvey, texts_by_source=texts("I'm just sitting here with my boy Harvey"),
            owner_names=OWNER_NAMES)
        self.assertEqual(found["gender"], rw.MALE)
        self.assertEqual(found["word"], "boy")
        self.assertEqual(found["basis"], rw.BASIS_STATED)

    def test_my_girl_is_female(self):
        piper = entity("Piper", "piper", "child")
        found = rw.stated_relation_gender(
            piper, texts_by_source=texts("just me and my girl Piper at the park"),
            owner_names=OWNER_NAMES)
        self.assertEqual(found["gender"], rw.FEMALE)
        self.assertEqual(found["word"], "girl")

    def test_boy_and_girl_are_gendered_only_for_a_child_row(self):
        """"my boy" never makes a spouse a husband — the word has no seat
        outside `child`, whatever a phrase's shape."""
        katie = entity("Katie Taylor", "katie-taylor", "spouse")
        found = rw.stated_relation_gender(
            katie, texts_by_source=texts("my girl Katie Taylor came dancing with me"),
            owner_names=OWNER_NAMES)
        self.assertIsNone(found)


class TheAuthorsSonTests(unittest.TestCase):
    """"the author's son X", "Son X born …" — a classification summary's own
    third-person shape for the owner, and its bare, clause-opening form."""

    def test_the_authors_son_is_male(self):
        x = entity("X", "x", "child")
        found = rw.stated_relation_gender(
            x, texts_by_source=texts("Birth of the author's son X"),
            owner_names=OWNER_NAMES)
        self.assertEqual(found["gender"], rw.MALE)
        self.assertEqual(found["word"], "son")

    def test_a_bare_clause_opening_son_name_is_male(self):
        harvey = entity("Harvey", "harvey", "child")
        found = rw.stated_relation_gender(
            harvey, texts_by_source=texts(
                "Son Harvey born while author lived at Christamon residence"),
            owner_names=OWNER_NAMES)
        self.assertEqual(found["gender"], rw.MALE)
        self.assertEqual(found["word"], "son")

    def test_the_authors_daughter_is_female(self):
        piper = entity("Piper", "piper", "child")
        found = rw.stated_relation_gender(
            piper, texts_by_source=texts("Birth of the author's daughter Piper"),
            owner_names=OWNER_NAMES)
        self.assertEqual(found["gender"], rw.FEMALE)


class GuardTests(unittest.TestCase):
    """The same guards v358 already applies, read against the new shapes."""

    def test_my_dads_dad_does_not_set_father(self):
        """A word possessing the next noun is not the name's own relation —
        v347's rule, read the same way against the informal/author reading."""
        grandpa = entity("James Edwin Taylor Sr.", "james-edwin-taylor-sr",
                         "grandparent")
        found = rw.stated_relation_gender(
            grandpa, texts_by_source=texts(
                "my grandpa James Edwin Taylor Sr., my dad's dad, died of a heart attack"),
            owner_names=OWNER_NAMES)
        # "grandpa" is the clause's own word for him; "dad" possesses the
        # NEXT noun ("dad's dad") and is never read as his relation.
        self.assertEqual(found["gender"], rw.MALE)
        self.assertEqual(found["word"], "grandpa")
        self.assertNotIn("father", [row["word"] for row in found["evidence"]])

    def test_mother_in_law_does_not_set_mother(self):
        """A compound is never the word inside it, in either phrase shape."""
        ruth = entity("Ruth Allen", "ruth-allen", "parent",
                      aliases=["my mother-in-law", "mother-in-law"])
        for quote in ("Ruth Allen, my mother-in-law, made dinner",
                     "the reception was at my mother-in-law Ruth Allen's house"):
            with self.subTest(quote=quote):
                found = rw.stated_relation_gender(
                    ruth, texts_by_source=texts(quote), owner_names=OWNER_NAMES)
                self.assertIsNone(found)

    def test_a_boy_named_sam_sets_nothing(self):
        """No possessive, no owner — "a boy named Sam" is a stranger's
        description, not "my boy Sam", and decides nothing."""
        sam = entity("Sam", "sam", "child")
        found = rw.stated_relation_gender(
            sam, texts_by_source=texts("a boy named Sam played outside"),
            owner_names=OWNER_NAMES)
        self.assertIsNone(found)

    def test_a_blessing_baby_boy_sets_nothing(self):
        """A description with no possessive-owner shape at all, mid-clause —
        exactly the shape "boy"/"girl" are never read outside of."""
        harvey = entity("Harvey", "harvey", "child")
        found = rw.stated_relation_gender(
            harvey, texts_by_source=texts(
                "Harvey was born, described as a 'blessing baby boy'"),
            owner_names=OWNER_NAMES)
        self.assertIsNone(found)

    def test_conflicting_statements_set_nothing(self):
        """Two statements that disagree decide nobody's word — the card stays."""
        harvey = entity("Harvey", "harvey", "child")
        both = {
            "classification:answers-c1#aaaaaaaaaaaa": ["my son Harvey took his first steps"],
            "classification:answers-c2#bbbbbbbbbbbb": ["my daughter Harvey sang at the recital"],
        }
        found = rw.stated_relation_gender(harvey, texts_by_source=both, owner_names=OWNER_NAMES)
        self.assertIsNone(found)
        # each statement alone is unambiguous — the CONFLICT is what erases it.
        alone = rw.stated_relation_gender(
            harvey, texts_by_source=texts("my son Harvey took his first steps"),
            owner_names=OWNER_NAMES)
        self.assertEqual(alone["gender"], rw.MALE)


class TheRosterRowsPublishItTests(unittest.TestCase):
    """The full seam: `relation_word_rows` over real claims, as a publish reads."""

    def _claim(self, source, subject_mention, quote):
        return {
            "source_kind": "conversation",
            "source_ref": {"source_id": source, "revision": "sha256:" + "0" * 64},
            "subject_mention": subject_mention,
            "event_mention": "a telling",
            "claim_type": "occurrence",
            "event_kind": "moment",
            "evidence": [{"quote": quote}],
            "extractor_version": "classifier:1",
            "created_at": "2026-01-01T00:00:00Z",
            "basis": "explicit",
            "confidence": 0.9,
            "status": "active",
        }

    def test_harvey_and_the_authors_child_both_resolve_and_the_card_leaves(self):
        roster = {"entities": [
            entity("Harvey", "harvey", "child"),
            entity("James Everett Taylor", "james-everett-taylor", "child"),
        ]}
        claims = [
            self._claim("classification:answers-c9#aaaaaaaaaaaa", "Harvey",
                       "I'm just sitting here with my boy Harvey"),
            self._claim("classification:answers-c10#bbbbbbbbbbbb", "James Everett Taylor",
                       "Birth of the author's son James Everett Taylor"),
        ]
        rows = {row["subject_ref"]: row for row in rw.relation_word_rows(
            roster, claims=claims, owner_names=OWNER_NAMES)}
        self.assertEqual(rows["person/harvey"]["label"], "Son")
        self.assertEqual(rows["person/harvey"][rw.RELATION_GENDER_BASIS_FIELD],
                         rw.BASIS_STATED)
        self.assertFalse(rows["person/harvey"]["askable"])
        self.assertEqual(rows["person/james-everett-taylor"]["label"], "Son")
        self.assertFalse(rows["person/james-everett-taylor"]["askable"])
        cards = {c["subject_ref"] for c in rw.relation_word_cards(rows.values(), now="2026-09-25T00:00:00Z")}
        self.assertNotIn("person/harvey", cards)
        self.assertNotIn("person/james-everett-taylor", cards)


if __name__ == "__main__":
    unittest.main()
