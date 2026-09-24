"""v347 — an introduction names one person in one clause.

v346's item 19 shipped and was run against the owner's vault the same day.
`entity-roster --ensure-introduced --dry-run` proposed four people, and one of
them was his paternal GRANDFATHER filed as a second father::

    desiree-taylor:        Desiree Taylor — parent (from "mom", born 1955-06-19)
    james-edwin-taylor-sr: James Edwin Taylor Sr. — parent (from "dad")
    james-taylor:          James Taylor — parent (from "dad")
    katie-taylor:          Katie Taylor — spouse (from "wife", born 1987-05-15)

The resolver had filed `claim:e18ea8f6edc28fd649a133c3`, whose evidence quote
reads *"story: my grandpa James Edwin Taylor Sr., my dad's dad, died of a heart
attack"*. v346's appositive shape — ``<Name>, <possessive> <word>`` — matched
the name against the "dad" of *my dad's* dad: a relationship word that
POSSESSES the next noun, read as though it were the name's own relation. Then
v346's own shared-alias rule made it worse in exactly the way it was designed
to prevent a different harm: two people claimed "dad", so dad / my dad / father
/ my father were dropped from BOTH rows, and the owner's real father — James
Edwin Taylor, d. 2019, *"the biggest loss of my life so far is my dad, James
Edwin Taylor"* — ended up with no relationship word at all.

The vault had already said who Sr was, twice, and neither statement was asked:
`correction:temporal-4eb9abe8c4ca47089ae83a56` (*"these are the owner's
grandfathers' births, not his: … James Edwin Taylor Sr (born 1930-10-17) and
Darvin Burrows Beauchamp (born 1929-09-30)"*), and the last token of the man's
own name.

Four rules ship here, all of them NARROWING v346 rather than widening it:

* `roster_relations.AN_INTRODUCTION_NAMES_ONE_PERSON_IN_ONE_CLAUSE` — the
  phrase and the name sit in ONE clause (:func:`introduction_clauses`), the
  word may not be a possessor, a clause that says two relations says neither,
  the in-law reading is clause-local, and a name a pasted vital record merely
  lists (`landmark_projection.BIRTH_NAME_LINE_RE`) is introduced by nothing;
* `roster_relations.A_RECORDED_RELATION_OUTRANKS_AN_INTRODUCED_ONE` — a
  correction, a `family` landmark entry's `relation` or a roster row's
  `relationship` is asked first, and a contradiction is refused out loud;
* `roster_relations.GENERATIONAL_SUFFIX_STEPS` — ``Sr.`` is one generation up
  from the ``<Name>`` the vault has placed and ``Jr.`` one down;
* and a birthday said with the WORD the introduction licensed is that person's
  birthday, so the father's row carries his 1954-06-04.

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

import axis_membership as axm  # noqa: E402
import landmark_projection as lp  # noqa: E402
import roster_relations as rr  # noqa: E402
from focus_candidate import FOCUS_RELATIONSHIPS  # noqa: E402
from tempdirs import root_parent_tmp  # noqa: E402
from test_v340_apply_keeps_placements import claim, value, write_vault  # noqa: E402

OWNER_NAMES = ("Dave", "David James Taylor")

# --------------------------------------------------------------------------
# The owner's own words, in the shapes his vault filed them
# --------------------------------------------------------------------------

#: `claim:e18ea8f6edc28fd649a133c3`'s evidence quote, verbatim. The defect in
#: one string: a grandfather, an apposition, and a possessive chain.
GRANDPA_QUOTE = (
    "story: my grandpa James Edwin Taylor Sr., my dad's dad, died of a heart "
    "attack | fact:node:a76cce066871cc36912485c3: James Edwin Taylor Sr's "
    "death — 4 April 1996 (stated, certain) | "
    "sources/conversations/msg-e3364a0ea1025bf627f61728.md#p6: 4 April 1996"
)

#: `sources/conversations/msg-e3364a0ea1025bf627f61728.md`, the genealogy-app
#: vital record the owner pasted into a card conversation about his father's
#: mission. The record is the GRANDFATHER'S; the "him" of the owner's own
#: sentence is his father.
PASTED_RECORD = (
    "Actually, I just looked up on an app. This is information about him and "
    "when he died.\n\n\nName • 8 Sources\nJames Edwin Taylor Sr\n\n\n"
    "Sex • 6 Sources\nMale\n\n\nBirth • 6 Sources\n17 October 1930\n"
    "Corpus Christi, Nueces, Texas, United States\n\n\n"
    "Death • 3 Sources\n4 April 1996\n"
    "Apple Valley, San Bernardino, California, United States"
)

#: `correction:temporal-4eb9abe8c4ca47089ae83a56`, verbatim.
GRANDFATHERS_CORRECTION = (
    "these are the owner's grandfathers' births, not his: "
    "landmark:entry-35a59936fc440531af66b360 is James Edwin Taylor Sr (born "
    "1930-10-17) and landmark:entry-9c618f4b4d540072b4ec2103 is Darvin Burrows "
    "Beauchamp (born 1929-09-30), both read off vital records the owner pasted "
    "on 2026-09-21 and filed against the owner's own `birth` landmark, whose "
    "stated date is 1981-07-11 (v339, birth_landmark_not_owner)"
)

#: `correction:temporal-f1a7509bee6990e880145153` — a correction that names two
#: relations and therefore states neither.
MIXED_CORRECTION = (
    "1990-03-20 is AJ's birthday, not James's. Both claims were extracted from "
    "conversation:msg-11d9436b14395f6d5a2fb69b with subject_mention \"James\" — "
    "the owner's brother Anthon James \"AJ\" Taylor, named there by his legal "
    "first name. James Taylor, the owner's dad, is a different man."
)

SR_SOURCE = "resolver:59031241b7130db1fa6a6696"
FATHER_SOURCE = "classification:sources-conversations-msg-455ccf0c#1de1825b38f6"
MOTHER_SOURCE = "classification:sources-manual-desiree-birthday#8c614ea83083"
WIFE_SOURCE = "classification:sources-manual-family-birthdays#702f311df153"
RECORD_SOURCE = "classification:sources-conversations-msg-e3364a0e#624fdf2f1e95"


def grandfather_claim() -> dict:
    return claim(claim_type="date", subject_mention="James Edwin Taylor Sr.",
                 event_kind="moment", source=SR_SOURCE,
                 temporal_value=value("1996-04-04"),
                 event_mention="Grandpa James Edwin Taylor Sr.'s death",
                 quote=GRANDPA_QUOTE)


def father_claim() -> dict:
    """`claim:5aeda702bfb70b607c1b12cd` — the owner typed *"James Taylor my dad
    was born on June 4th 1954"* and the extractor filed the event with the WORD
    rather than with the name."""
    return claim(claim_type="date", subject_mention="James Taylor (Dad)",
                 event_kind="moment", source=FATHER_SOURCE,
                 temporal_value=value("1954-06-04"),
                 event_mention="Dad's birthdate recorded",
                 quote="The author states their father James Taylor's birthday "
                       "as June 4th, 1954")


def mother_claim() -> dict:
    return claim(claim_type="date", subject_mention="Desiree Taylor (Desi)",
                 event_kind="moment", source=MOTHER_SOURCE,
                 temporal_value=value("1955-06-19"),
                 event_mention="Desiree Taylor's birthday",
                 quote="Desiree Taylor (Dave's mom, also called Desi) — "
                       "birthday June 19, 1955.")


def wife_claim() -> dict:
    return claim(claim_type="date", subject_mention="Katie Taylor",
                 event_kind="moment", source=WIFE_SOURCE,
                 temporal_value=value("1987-05-15"),
                 event_mention="Katie Taylor's birthday",
                 quote="- Katie Taylor (wife) — May 15, 1987")


def record_claim() -> dict:
    """The pasted record's own claim, with the relationship word the owner used
    about his FATHER in the same source."""
    return claim(claim_type="date", subject_mention="James Edwin Taylor Sr",
                 event_kind="moment", source=RECORD_SOURCE,
                 temporal_value=value("1930-10-17"),
                 event_mention="James Edwin Taylor Sr's birth",
                 quote=PASTED_RECORD + "\n\nI looked my dad up on the app.")


def roster(*rows) -> dict:
    return {"version": 1, "type": "person", "entities": [dict(row) for row in rows]}


def family_entry(who: str, relation: str) -> dict:
    """One `landmark_projection.load_landmark_sources` row, in its own shape."""
    return {"source_id": f"landmark:entry-{who}", "domain": "family",
            "entry_key": who, "ordinal": 1,
            "record": {"domain": "family", "who": who, "label": who,
                       "relation": relation}}


def batch(claims, **kwargs):
    kwargs.setdefault("owner_names", OWNER_NAMES)
    return rr.relationship_introduction_batch(claims, **kwargs)


# --------------------------------------------------------------------------
# 1. One clause
# --------------------------------------------------------------------------


class OneClauseTests(unittest.TestCase):

    def test_the_quote_that_made_a_grandfather_a_father(self) -> None:
        """The whole defect, and the whole fix, in one string."""
        found = rr.relationship_phrase_match(
            "James Edwin Taylor Sr.", [GRANDPA_QUOTE], owner_names=OWNER_NAMES)
        self.assertEqual(found["word"], "grandpa")
        self.assertEqual(
            found["clause"],
            "my grandpa James Edwin Taylor Sr., my dad's dad, "
            "died of a heart attack")
        row = rr.relationship_introduction(
            "James Edwin Taylor Sr.", [GRANDPA_QUOTE], owner_names=OWNER_NAMES)
        self.assertEqual(row["relationship"], "grandparent")
        self.assertNotEqual(row["relationship"], "parent")

    def test_a_relationship_word_that_possesses_is_not_the_names_relation(self) -> None:
        """*"my dad's dad"* says dad's DAD. The control — the same sentence
        without the possessive — still reads "dad", so this narrows one shape
        and not the rule."""
        self.assertEqual(
            rr.relationship_phrase("Jim Rowe", ["Jim Rowe, my dad's dad, died"],
                                   owner_names=OWNER_NAMES),
            "")
        self.assertEqual(
            rr.relationship_phrase("Jim Rowe", ["Jim Rowe, my dad, died"],
                                   owner_names=OWNER_NAMES),
            "dad")
        self.assertEqual(
            rr.relationship_phrase("Jim Rowe", ["my dad's dad Jim Rowe died"],
                                   owner_names=OWNER_NAMES),
            "")

    def test_a_phrase_may_not_reach_across_a_clause(self) -> None:
        for text in (
            "James Taylor bought a truck. My dad called that week.",
            "James Taylor bought a truck | my dad called that week",
            "James Taylor bought a truck; my dad called that week",
            "James Taylor bought a truck\nmy dad called that week",
        ):
            with self.subTest(text):
                self.assertEqual(
                    rr.relationship_phrase("James Taylor", [text],
                                           owner_names=OWNER_NAMES), "")

    def test_a_name_is_not_two_clauses(self) -> None:
        """A full stop ends a clause only when a sentence plainly starts after
        it — "James Edwin Taylor Sr." and "A.J." carry their own."""
        self.assertEqual(
            rr.introduction_clauses("my grandpa James Edwin Taylor Sr. died"),
            ("my grandpa James Edwin Taylor Sr. died",))
        self.assertEqual(rr.introduction_clauses("A.J. (brother) plays guitar"),
                         ("A.J. (brother) plays guitar",))
        self.assertEqual(
            rr.introduction_clauses("He moved away. Then my dad called."),
            ("He moved away", "Then my dad called."))
        self.assertEqual(rr.relationship_phrase("A.J.", ["A.J. (brother) plays guitar"],
                                                owner_names=OWNER_NAMES), "brother")

    def test_one_clause_that_says_two_relations_says_neither(self) -> None:
        self.assertEqual(
            rr.relationship_phrase("Pat Rowe",
                                   ["my mother Pat Rowe, my sister, called"],
                                   owner_names=OWNER_NAMES),
            "")

    def test_the_in_law_reading_is_clause_local(self) -> None:
        """"in-law" somewhere else in a source says nothing about this name.
        v346 read `axis_membership.IN_LAW_RE` over every text of the source."""
        row = rr.relationship_introduction(
            "Ruth Alder",
            ["my mother-in-law Ruth Alder retired"], owner_names=OWNER_NAMES)
        self.assertEqual(row["relationship"], "other")
        self.assertNotIn(row["relationship"], axm.IMMEDIATE_FAMILY_RELATIONSHIPS)
        kept = rr.relationship_introduction(
            "Desiree Taylor",
            ["my mother Desiree Taylor called",
             "Katie's mother-in-law lives nearby"], owner_names=OWNER_NAMES)
        self.assertEqual(kept["relationship"], "parent")

    def test_every_shape_v344_read_is_still_read(self) -> None:
        """This release NARROWS v346. Each of its own shapes, unchanged."""
        for text, name, relationship in (
            ("Desiree Taylor (Dave's mom, also called Desi) — birthday June 19, 1955.",
             "Desiree Taylor", "parent"),
            ("- Katie Taylor (wife) — May 15, 1987", "Katie Taylor", "spouse"),
            ("A.J. (brother) plays guitar", "A.J.", "sibling"),
            ("Desiree Taylor, my mother, got married at 21", "Desiree Taylor", "parent"),
            ("my mother Desiree Taylor got married at 21", "Desiree Taylor", "parent"),
            ("Dave's dad James Taylor started a pool company", "James Taylor", "parent"),
        ):
            with self.subTest(text):
                row = rr.relationship_introduction(name, [text],
                                                   owner_names=OWNER_NAMES)
                self.assertIsNotNone(row, text)
                self.assertEqual(row["relationship"], relationship)

    def test_somebody_elses_relative_is_still_not_the_owners(self) -> None:
        self.assertIsNone(rr.relationship_introduction(
            "Desiree Taylor", ["Katie's mom Desiree Taylor"],
            owner_names=OWNER_NAMES))


# --------------------------------------------------------------------------
# 2. A pasted record introduces nobody
# --------------------------------------------------------------------------


class PastedRecordTests(unittest.TestCase):

    def test_the_owners_own_paste_names_the_man_on_the_next_line(self) -> None:
        self.assertEqual(rr.pasted_record_names([PASTED_RECORD]),
                         ("James Edwin Taylor Sr",))
        self.assertIsNotNone(lp.BIRTH_NAME_LINE_RE.search(PASTED_RECORD))

    def test_a_relationship_word_may_not_reach_into_a_pasted_record(self) -> None:
        """The record is the GRANDFATHER'S; the "him" of the owner's sentence is
        his father. A name only the record lists is introduced by nothing."""
        texts = [PASTED_RECORD, "I looked my dad up on the app."]
        self.assertTrue(
            rr.introduces_only_a_pasted_record("James Edwin Taylor Sr", texts))
        self.assertIsNone(rr.relationship_introduction(
            "James Edwin Taylor Sr", texts, owner_names=OWNER_NAMES))

    def test_a_name_the_owner_also_says_himself_is_still_introduced(self) -> None:
        """The refusal is about a name that appears ONLY in the record."""
        texts = [PASTED_RECORD, "my grandpa James Edwin Taylor Sr died in 1996"]
        self.assertFalse(
            rr.introduces_only_a_pasted_record("James Edwin Taylor Sr", texts))
        row = rr.relationship_introduction("James Edwin Taylor Sr", texts,
                                           owner_names=OWNER_NAMES)
        self.assertEqual(row["relationship"], "grandparent")

    def test_the_pasted_record_source_files_nobody(self) -> None:
        rows = batch([record_claim()])["rows"]
        self.assertEqual(rows, ())


# --------------------------------------------------------------------------
# 3. A recorded relation wins
# --------------------------------------------------------------------------


class RecordedRelationTests(unittest.TestCase):

    def test_the_correction_the_vault_already_held(self) -> None:
        self.assertEqual(
            rr.stated_relation([GRANDFATHERS_CORRECTION], "James Edwin Taylor Sr"),
            "grandparent")
        self.assertEqual(
            rr.stated_relation([GRANDFATHERS_CORRECTION], "Darvin Burrows Beauchamp"),
            "grandparent")
        found = rr.recorded_relation("James Edwin Taylor Sr.",
                                     correction_texts=[GRANDFATHERS_CORRECTION])
        self.assertEqual(found["relationship"], "grandparent")
        self.assertEqual(found["tier"], "correction")

    def test_a_correction_that_names_two_relations_states_neither(self) -> None:
        self.assertEqual(rr.stated_relation([MIXED_CORRECTION], "James Taylor"), "")
        self.assertIsNone(rr.recorded_relation(
            "James Taylor", correction_texts=[MIXED_CORRECTION]))

    def test_a_correction_that_does_not_name_the_person_says_nothing(self) -> None:
        self.assertEqual(
            rr.stated_relation([GRANDFATHERS_CORRECTION], "Desiree Taylor"), "")

    def test_every_tier_answers_and_the_order_is_the_constant(self) -> None:
        self.assertEqual(rr.RECORDED_RELATION_TIERS,
                         ("correction", "landmark:family", "roster"))
        self.assertEqual(
            rr.recorded_relation("Pat Rowe",
                                 landmark_entries=[family_entry("Pat Rowe", "sibling")]),
            {"relationship": "sibling", "tier": "landmark:family", "stated": "Pat Rowe"})
        self.assertEqual(
            rr.recorded_relation("Pat Rowe", roster=roster(
                {"name": "Pat Rowe", "slug": "pat-rowe", "relationship": "child"}))
            ["tier"], "roster")
        self.assertEqual(
            rr.recorded_relation("Pat Rowe",
                                 correction_texts=["Pat Rowe is my sister"],
                                 landmark_entries=[family_entry("Pat Rowe", "child")])
            ["relationship"], "sibling")

    def test_an_introduction_that_contradicts_a_record_is_refused_out_loud(self) -> None:
        """A vault that has already placed somebody is not corrected by a
        sentence that reads them differently — and the refusal names both."""
        result = batch([claim(claim_type="occurrence", subject_mention="Pat Rowe",
                              event_kind="moment", source="classification:s#1",
                              event_mention="a visit",
                              quote="my mom Pat Rowe came over")],
                       landmark_entries=[family_entry("Pat Rowe", "sibling")])
        self.assertEqual(result["rows"], ())
        finding, = result["findings"]
        self.assertEqual(finding["name"], "Pat Rowe")
        self.assertEqual(finding["introduced"], "parent")
        self.assertEqual(finding["recorded"], "sibling")
        self.assertEqual(finding["tier"], "landmark:family")

    def test_a_record_that_agrees_confirms_the_row(self) -> None:
        result = batch([grandfather_claim()],
                       correction_texts=[GRANDFATHERS_CORRECTION])
        row, = result["rows"]
        self.assertEqual(row["relationship"], "grandparent")
        self.assertEqual(row["relationship_basis"], "recorded")
        self.assertEqual(result["findings"], ())


# --------------------------------------------------------------------------
# 4. A generational suffix is a generation
# --------------------------------------------------------------------------


class GenerationalSuffixTests(unittest.TestCase):

    def test_the_suffix_and_its_step(self) -> None:
        self.assertEqual(rr.generational_suffix("James Edwin Taylor Sr."),
                         ("James Edwin Taylor", 1))
        self.assertEqual(rr.generational_suffix("James Taylor Sr"),
                         ("James Taylor", 1))
        self.assertEqual(rr.generational_suffix("James Taylor Senior"),
                         ("James Taylor", 1))
        self.assertEqual(rr.generational_suffix("James Taylor Jr."),
                         ("James Taylor", -1))
        self.assertEqual(rr.generational_suffix("James Taylor"), ("", 0))
        self.assertEqual(rr.generational_suffix("Sr."), ("", 0))

    def test_one_generation_up_and_one_down(self) -> None:
        placed = {"james taylor": "parent"}
        self.assertEqual(rr.suffixed_generation("James Taylor Sr.", placed=placed),
                         "grandparent")
        self.assertEqual(rr.suffixed_generation("James Taylor Jr.", placed=placed),
                         "sibling")

    def test_a_step_off_the_ladder_refuses_rather_than_inventing_a_seat(self) -> None:
        """`focus_candidate.FOCUS_RELATIONSHIPS` is the gate: there is no
        great-grandparent and no grandchild seat on this roster."""
        self.assertEqual(rr.generation_shifted("grandparent", 1), "")
        self.assertEqual(rr.generation_shifted("child", -1), "")
        self.assertNotIn("grandchild", FOCUS_RELATIONSHIPS)
        for tier in rr.GENERATION_TIERS:
            for step in (-1, 1):
                shifted = rr.generation_shifted(tier, step)
                if shifted:
                    self.assertIn(shifted, FOCUS_RELATIONSHIPS)

    def test_the_middle_name_is_not_collapsed(self) -> None:
        """Four people on the owner's roster bear the token *James*, so the base
        name is compared WHOLE: "James Edwin Taylor Sr." is not "James Taylor"
        one generation up."""
        self.assertEqual(
            rr.suffixed_generation("James Edwin Taylor Sr.",
                                   placed={"james taylor": "parent"}), "")

    def test_a_shifted_row_drops_the_word_of_the_wrong_generation(self) -> None:
        rows = batch(
            [claim(claim_type="occurrence", subject_mention="James Taylor",
                   event_kind="moment", source="classification:s#1",
                   event_mention="a visit", quote="my dad James Taylor came over"),
             claim(claim_type="occurrence", subject_mention="James Taylor Sr.",
                   event_kind="moment", source="classification:s#2",
                   event_mention="a shop", quote="my dad James Taylor Sr. ran the shop")],
        )["rows"]
        by_slug = {row["slug"]: row for row in rows}
        self.assertEqual(by_slug["james-taylor"]["relationship"], "parent")
        self.assertEqual(by_slug["james-taylor-sr"]["relationship"], "grandparent")
        self.assertEqual(by_slug["james-taylor-sr"]["relationship_basis"],
                         "generational_suffix")
        # The alias that decided nothing under v346 now binds to the one parent.
        self.assertIn("dad", by_slug["james-taylor"]["aliases"])
        self.assertNotIn("dad", by_slug["james-taylor-sr"]["aliases"])

    def test_a_source_that_says_otherwise_outranks_the_suffix(self) -> None:
        rows = batch(
            [claim(claim_type="occurrence", subject_mention="James Taylor",
                   event_kind="moment", source="classification:s#1",
                   event_mention="a visit", quote="my dad James Taylor came over"),
             claim(claim_type="occurrence", subject_mention="James Taylor Sr.",
                   event_kind="moment", source="classification:s#2",
                   event_mention="a shop",
                   quote="my brother James Taylor Sr. ran the shop")],
            correction_texts=["James Taylor Sr. is my brother"],
        )["rows"]
        by_slug = {row["slug"]: row for row in rows}
        self.assertEqual(by_slug["james-taylor-sr"]["relationship"], "sibling")
        self.assertEqual(by_slug["james-taylor-sr"]["relationship_basis"], "recorded")


# --------------------------------------------------------------------------
# 5. The aliases bind to the surviving parent
# --------------------------------------------------------------------------


class AliasBindingTests(unittest.TestCase):

    def setUp(self) -> None:
        self.result = batch(
            [mother_claim(), father_claim(), grandfather_claim(), wife_claim()],
            correction_texts=[GRANDFATHERS_CORRECTION, MIXED_CORRECTION],
        )
        self.by_slug = {row["slug"]: row for row in self.result["rows"]}

    def test_the_owners_four_people(self) -> None:
        self.assertEqual(sorted(self.by_slug),
                         ["desiree-taylor", "james-edwin-taylor-sr",
                          "james-taylor", "katie-taylor"])
        self.assertEqual(self.by_slug["desiree-taylor"]["relationship"], "parent")
        self.assertEqual(self.by_slug["james-taylor"]["relationship"], "parent")
        self.assertEqual(self.by_slug["katie-taylor"]["relationship"], "spouse")
        self.assertEqual(
            self.by_slug["james-edwin-taylor-sr"]["relationship"], "grandparent")

    def test_dad_binds_to_the_father(self) -> None:
        father = self.by_slug["james-taylor"]
        for alias in ("dad", "my dad", "father", "my father"):
            with self.subTest(alias):
                self.assertIn(alias, father["aliases"])
        self.assertEqual(father.get("contested_aliases"), None)
        for alias in ("dad", "my dad", "father", "my father"):
            self.assertNotIn(alias,
                             self.by_slug["james-edwin-taylor-sr"]["aliases"])

    def test_the_father_gets_his_birthday_from_the_word(self) -> None:
        """*"James Taylor my dad was born on June 4th 1954"*, filed by the
        extractor as *"Dad's birthdate recorded"*: one clause, one person, and
        the word is the name."""
        self.assertEqual(self.by_slug["james-taylor"]["born"], "1954-06-04")
        self.assertEqual(self.by_slug["desiree-taylor"]["born"], "1955-06-19")
        self.assertEqual(self.by_slug["katie-taylor"]["born"], "1987-05-15")

    def test_the_grandfathers_pasted_birthday_does_not_ride_along(self) -> None:
        """His birth is in a DIFFERENT source — the pasted record — and this
        rule reads one source at a time."""
        self.assertNotIn("born", self.by_slug["james-edwin-taylor-sr"])

    def test_two_genuine_claimants_still_bind_to_neither(self) -> None:
        """v346's rule is kept exactly for a real tie."""
        rows = batch([
            claim(claim_type="occurrence", subject_mention="Pat Rowe",
                  event_kind="moment", source="classification:s#1",
                  event_mention="a visit", quote="my mom Pat Rowe came over"),
            claim(claim_type="occurrence", subject_mention="Dee Rowe",
                  event_kind="moment", source="classification:s#2",
                  event_mention="a call", quote="my mom Dee Rowe called"),
        ])["rows"]
        for row in rows:
            with self.subTest(row["slug"]):
                self.assertNotIn("mom", row["aliases"])
                self.assertIn("mom", row["contested_aliases"])


# --------------------------------------------------------------------------
# 6. The writer seat, on a vault
# --------------------------------------------------------------------------


class TheWriterSeatTests(unittest.TestCase):
    """`entity_roster.ensure_introduced_relatives` reads what the vault already
    records — through the production correction reader — and the CLI reports a
    refusal rather than swallowing it."""

    def setUp(self) -> None:
        self.root = root_parent_tmp(self, ROOT, prefix="lifehug-v347-roster-")
        (self.root / "system").mkdir(parents=True, exist_ok=True)
        (self.root / "state" / "entity_rosters").mkdir(parents=True, exist_ok=True)
        (self.root / "profile.yaml").write_text("name: Dave\n", encoding="utf-8")
        write_vault(self.root, [mother_claim(), father_claim(),
                                grandfather_claim(), wife_claim()])

    def _run(self, *, dry_run=False) -> dict:
        import entity_roster  # noqa: PLC0415
        import lifehug_core  # noqa: PLC0415

        path = self.root / "state" / "entity_rosters" / "person.json"
        path.write_text(json.dumps(roster()), encoding="utf-8")
        original_repo = lifehug_core.REPO_DIR
        original_entity = entity_roster.ENTITY_DIR
        lifehug_core.REPO_DIR = self.root
        entity_roster.ENTITY_DIR = path.parent
        try:
            result = entity_roster.ensure_introduced_relatives(dry_run=dry_run)
        finally:
            lifehug_core.REPO_DIR = original_repo
            entity_roster.ENTITY_DIR = original_entity
        result["roster"] = json.loads(path.read_text(encoding="utf-8"))
        return result

    def _file_correction(self, reason: str) -> None:
        import temporal_store as store  # noqa: PLC0415

        store.file_temporal_correction(
            self.root, kind="dispute", claim_ids=["claim:" + "a" * 24],
            reason=reason, title="A correction the owner wrote")

    def test_the_father_is_filed_with_his_words_and_his_birthday(self) -> None:
        result = self._run()
        rows = {row["slug"]: row for row in result["roster"]["entities"]}
        self.assertEqual(rows["james-taylor"]["relationship"], "parent")
        self.assertEqual(rows["james-taylor"]["born"]["best"], "1954-06-04")
        self.assertEqual(rows["james-taylor"]["source"], "landmark:family")
        for alias in ("dad", "my dad", "father", "my father"):
            self.assertIn(alias, rows["james-taylor"]["aliases"])
        self.assertEqual(rows["james-edwin-taylor-sr"]["relationship"], "grandparent")

    def test_the_vaults_own_correction_reaches_the_rule(self) -> None:
        """Filed through the production writer and read back through
        `temporal_store.load_temporal_corrections` — no second reader."""
        self._file_correction(GRANDFATHERS_CORRECTION)
        result = self._run(dry_run=True)
        rows = {row["slug"]: row for row in result["introduced"]}
        self.assertEqual(rows["james-edwin-taylor-sr"]["relationship"], "grandparent")
        self.assertEqual(rows["james-edwin-taylor-sr"]["relationship_basis"],
                         "recorded")
        self.assertEqual(result["findings"], [])

    def test_a_contradicted_introduction_is_reported_and_not_written(self) -> None:
        # One relation, so the correction states one thing (a text that said
        # "my sister, not my wife" would state neither, which is the refusal
        # `test_a_correction_that_names_two_relations_states_neither` pins).
        self._file_correction("Katie Taylor is my sister")
        result = self._run()
        rows = {row["slug"]: row for row in result["roster"]["entities"]}
        self.assertNotIn("katie-taylor", rows)
        finding, = [row for row in result["findings"]
                    if row["slug"] == "katie-taylor"]
        self.assertEqual(finding["introduced"], "spouse")
        self.assertEqual(finding["recorded"], "sibling")

    def test_a_dry_run_writes_nothing_and_a_second_run_converges(self) -> None:
        self.assertEqual(self._run(dry_run=True)["roster"]["entities"], [])
        first = self._run()
        self.assertEqual(first["filed"], 4)
        again = self._run()
        self.assertEqual(
            sorted(row["slug"] for row in again["roster"]["entities"]),
            sorted(row["slug"] for row in first["roster"]["entities"]))


# --------------------------------------------------------------------------
# 7. The rule is stated once
# --------------------------------------------------------------------------


class TheRuleIsStatedOnceTests(unittest.TestCase):

    def test_the_statements_exist_and_say_what_they_do(self) -> None:
        for name in ("AN_INTRODUCTION_NAMES_ONE_PERSON_IN_ONE_CLAUSE",
                     "A_RECORDED_RELATION_OUTRANKS_AN_INTRODUCED_ONE",
                     "A_RELATIONSHIP_PHRASE_INTRODUCES_A_PERSON"):
            with self.subTest(name):
                self.assertGreater(len(getattr(rr, name)), 80)

    def test_the_generation_ladder_is_the_roster_vocabulary(self) -> None:
        """No second list of relationships: every seat the ladder can land on is
        one `focus_candidate.FOCUS_RELATIONSHIPS` holds."""
        landable = {tier for tier in rr.GENERATION_TIERS
                    if tier in FOCUS_RELATIONSHIPS}
        self.assertEqual(landable, {"child", "sibling", "parent", "grandparent"})
        self.assertEqual(set(rr.GENERATIONAL_SUFFIX_STEPS.values()), {1, -1})

    def test_the_relationship_basis_is_a_closed_vocabulary(self) -> None:
        rows = batch([mother_claim(), grandfather_claim()],
                     correction_texts=[GRANDFATHERS_CORRECTION])["rows"]
        for row in rows:
            with self.subTest(row["slug"]):
                self.assertIn(row["relationship_basis"], rr.RELATIONSHIP_BASES)


if __name__ == "__main__":
    unittest.main()
