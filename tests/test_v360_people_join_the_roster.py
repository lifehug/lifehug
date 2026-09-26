"""v360 (owner, 2026-09-25) — how a person the owner talks about becomes a
roster PERSON row with a relationship.

THE DEFECT, on the owner's real vault. He has four children ("youngest of
four" -- his vault says so repeatedly). His roster had rows for Harvey and
James Everett Taylor only: `harvey` and `james-everett-taylor`, both
`relationship: "child"`, `source: "landmark:family"`. Charlee (Charlee Joy
Taylor) and Dottie (Dottie Ovelle Taylor) had NO roster row, despite two
`children` landmark entries each carrying a full name and an exact birth date
(`landmark:entry-833a695eba71f6699a79c091`, `landmark:entry-715892555a83352f2a
1e1ff9`, both filed 2026-08-27) -- because v344's `ensure_introduced_relatives`
only reads the CLAIM substrate for a relationship phrase inside one clause,
and no source in the vault happens to carry either name beside a relationship
WORD inside the one clause a claim's own source groups together. Separately,
`grandma-betty-jo` had a roster row (several aliases: "Grandma", "BJ", "Betty
Jo Taylor"...) but no `relationship` at all -- the roster already answered to
her by the time any relationship-introduction pass ran, so `known()` always
skipped her.

THE FIX, entirely in `entity_roster.py` (this seat's own file; nothing here
touches `roster_relations.py` or `identity_resolution.py`, only reads their
public functions):

* :func:`entity_roster.landmark_relationship_introductions` -- a `children`
  landmark entry earns "child" and a `family` landmark entry keeps its own
  `relation` field, both through the SAME writer v344 already uses
  (`entity_verdict.apply_verdict(..., ensure=True)`), guarded exactly as
  v202/v347 guard the claims path: never a first name alone, never a second
  row for somebody the roster already answers to (by spelling OR by a shared
  first token with an existing name/alias);
* :func:`entity_roster.relationship_from_own_name` -- a roster row with no
  `relationship`, whose own canonical NAME opens with a relation word, gets
  that relationship, through `entity_verdict.apply_verdict` on the EXISTING
  row (no `--ensure`);
* :func:`entity_roster.grandparent_side_rows` / `grandparent_side_cards` --
  ONE low-rank card, following the v358 `relation_words` card conventions
  (same `kind`, scored lowest, at most one per person), for a grandparent
  whose maternal/paternal side is not yet known.

Nothing here reads a real vault; every fixture is the SHAPE of the owner's
real rows and entries.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "system"))
sys.path.insert(0, str(ROOT / "tests"))

import entity_roster as er  # noqa: E402
import roster_relations as rr  # noqa: E402

OWNER_NAMES = ("Dave", "David James Taylor")
NOW = "2026-09-25T09:00:00Z"


def roster(*rows) -> dict:
    return {"version": 1, "type": "person", "entities": [dict(row) for row in rows]}


def row(name, slug, relationship=None, *, aliases=(), **extra):
    """A roster row in the shape `entity_verdict.apply_verdict(ensure=True)`
    files -- the same builder v358's own test uses."""
    out = {"name": name, "slug": slug, "aliases": list(aliases), "qualifies": False,
           "maps_to_focus": None, "score": 0.0, "unique_answers": 0,
           "page_eligible": False}
    if relationship is not None:
        out["relationship"] = relationship
        out["source"] = "landmark:family"
    out.update(extra)
    return out


def children_entry(who: str, *, ordinal: int, born: str | None = None,
                   source_id: str | None = None) -> dict:
    """One `landmark_projection.load_landmark_sources` row, `children` domain
    shape -- `{"label", "who", "date"}` exactly as the owner's vault files it."""
    record = {"domain": "children", "label": who, "who": who}
    if born:
        record["date"] = {"best": born, "earliest": born, "latest": born,
                          "granularity": "day", "basis": "stated", "confidence": "certain"}
    return {"source_id": source_id or f"landmark:entry-{who.lower().replace(' ', '-')}",
            "domain": "children", "entry_key": who.lower(), "ordinal": ordinal,
            "record": record}


def family_entry(who: str, relation: str, *, ordinal: int = 1) -> dict:
    return {"source_id": f"landmark:entry-{who.lower().replace(' ', '-')}", "domain": "family",
            "entry_key": who.lower(), "ordinal": ordinal,
            "record": {"domain": "family", "who": who, "label": who, "relation": relation}}


# --------------------------------------------------------------------------
# 1. "my daughter Charlee" -> a row with relationship child
# --------------------------------------------------------------------------


class OwnWordsIntroduceAChild(unittest.TestCase):

    def test_my_daughter_charlee_is_a_child_relationship(self) -> None:
        found = rr.relationship_introduction(
            "Charlee", ["my daughter Charlee is doing great at track"],
            owner_names=OWNER_NAMES)
        self.assertIsNotNone(found)
        self.assertEqual(found["relationship"], "child")
        self.assertEqual(found["name"], "Charlee")

    def test_the_batch_files_it_through_the_one_writer_shape(self) -> None:
        """The row `relationship_introduction_batch` proposes is exactly the
        shape `ensure_introduced_relatives` hands to
        `entity_verdict.apply_verdict(..., ensure=True)`."""
        from test_v340_apply_keeps_placements import claim, value  # noqa: PLC0415

        claims = [claim(
            claim_type="date", subject_mention="Charlee", event_kind="moment",
            source="classification:answers-x1#aaaaaaaaaaaa",
            temporal_value=value("2024-08"),
            event_mention="Charlee's track season",
            quote="my daughter Charlee had a great track season this year")]
        batch = rr.relationship_introduction_batch(claims, roster=roster(),
                                                    owner_names=OWNER_NAMES)
        self.assertEqual(len(batch["rows"]), 1)
        proposed = batch["rows"][0]
        self.assertEqual(proposed["slug"], "charlee")
        self.assertEqual(proposed["relationship"], "child")


# --------------------------------------------------------------------------
# 2. A `children` landmark entry -> a row
# --------------------------------------------------------------------------


class ChildrenLandmarkEntryIntroducesARow(unittest.TestCase):

    def test_charlee_and_dottie_get_rows_from_the_children_landmark(self) -> None:
        """The owner's real defect, reproduced: two full-name `children`
        entries, an empty roster, both come back as `child` rows with their
        stated birth dates."""
        entries = [
            children_entry("Charlee Joy Taylor", ordinal=21, born="2010-12-21"),
            children_entry("Dottie Ovelle Taylor", ordinal=23, born="2018-01-15"),
        ]
        rows = er.landmark_relationship_introductions(entries, roster=roster())
        by_slug = {r["slug"]: r for r in rows}
        self.assertEqual(set(by_slug), {"charlee-joy-taylor", "dottie-ovelle-taylor"})
        self.assertEqual(by_slug["charlee-joy-taylor"]["relationship"], "child")
        self.assertEqual(by_slug["charlee-joy-taylor"]["born"], "2010-12-21")
        self.assertEqual(by_slug["dottie-ovelle-taylor"]["born"], "2018-01-15")

    def test_an_empty_later_entry_never_erases_the_earlier_dated_one(self) -> None:
        """The owner's own vault: Charlee's `children` entry was refiled
        overnight (2026-09-25T08:20:58Z) with NO date. The dated entry still
        wins -- the row never regresses from dated to undated."""
        entries = [
            children_entry("Charlee Joy Taylor", ordinal=21, born="2010-12-21"),
            children_entry("Charlee Joy Taylor", ordinal=141),  # the empty refiling
        ]
        rows = er.landmark_relationship_introductions(entries, roster=roster())
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["born"], "2010-12-21")

    def test_a_family_domain_entry_keeps_its_own_relation_word(self) -> None:
        entries = [family_entry("Desiree Taylor", "parent")]
        rows = er.landmark_relationship_introductions(entries, roster=roster())
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["relationship"], "parent")

    def test_never_from_a_first_name_alone(self) -> None:
        """A bare "Harvey" `children` entry -- no last name -- proposes nothing
        by itself (v202/v347's own principle, applied to the landmark path)."""
        entries = [children_entry("Harvey", ordinal=34, born="2022")]
        rows = er.landmark_relationship_introductions(entries, roster=roster())
        self.assertEqual(rows, ())

    def test_never_a_duplicate_of_somebody_the_roster_already_answers_to(self) -> None:
        """`harvey` is already on the roster. A LATER, fuller-name `children`
        entry for the same child ("Harvey Rex Taylor") must not become a
        SECOND row -- it shares "harvey"'s first token, so it is read as the
        same person and left alone."""
        existing = roster(row("Harvey", "harvey", "child"))
        entries = [children_entry("Harvey Rex Taylor", ordinal=24, born="2021-10-11")]
        rows = er.landmark_relationship_introductions(entries, roster=existing)
        self.assertEqual(rows, (), "must not duplicate the existing Harvey row")

    def test_a_name_the_roster_already_knows_exactly_is_skipped(self) -> None:
        existing = roster(row("James Everett Taylor", "james-everett-taylor", "child"))
        entries = [children_entry("James Everett Taylor", ordinal=22, born="2013-05-10")]
        rows = er.landmark_relationship_introductions(entries, roster=existing)
        self.assertEqual(rows, ())


# --------------------------------------------------------------------------
# 3. "my dad's dad" doesn't create a father row
# --------------------------------------------------------------------------


class NoCompoundsNoPossessorConfusion(unittest.TestCase):

    def test_my_dads_dad_names_no_relation_at_all(self) -> None:
        """v347's own guard, unchanged by this build: a relationship word that
        POSSESSES the next noun is not the name's own relation, so the
        apposition names nothing -- never a "father" row for the grandfather,
        and never any row at all for this shape."""
        found = rr.relationship_phrase(
            "Jim Rowe", ["Jim Rowe, my dad's dad, died"], owner_names=OWNER_NAMES)
        self.assertEqual(found, "")
        introduced = rr.relationship_introduction(
            "Jim Rowe", ["Jim Rowe, my dad's dad, died"], owner_names=OWNER_NAMES)
        self.assertIsNone(introduced)

    def test_the_real_grandfather_quote_reads_grandparent_never_parent(self) -> None:
        quote = ("story: my grandpa James Edwin Taylor Sr., my dad's dad, "
                "died of a heart attack")
        introduced = rr.relationship_introduction(
            "James Edwin Taylor Sr.", [quote], owner_names=OWNER_NAMES)
        self.assertIsNotNone(introduced)
        self.assertEqual(introduced["relationship"], "grandparent")
        self.assertNotEqual(introduced["relationship"], "parent")


# --------------------------------------------------------------------------
# Betty Jo — a roster row that already answers to its own relation word
# --------------------------------------------------------------------------


class OwnNameStatesItsOwnRelation(unittest.TestCase):

    def test_grandma_betty_jo_gets_grandparent_from_her_own_name(self) -> None:
        existing = roster(
            row("Grandma Betty Jo", "grandma-betty-jo",
                aliases=["Grandma", "Betty Jo", "BJ", "Betty Jo Taylor"]))
        result = er.relationship_from_own_name(existing, dry_run=True)
        self.assertEqual(len(result["updated"]), 1)
        self.assertEqual(result["updated"][0]["slug"], "grandma-betty-jo")
        self.assertEqual(result["updated"][0]["relationship"], "grandparent")

    def test_a_collective_or_role_row_is_never_touched(self) -> None:
        existing = roster(
            row("Kids", "kids", aliases=["the kids"]),
            row("Son", "son"),
        )
        result = er.relationship_from_own_name(existing, dry_run=True)
        self.assertEqual(result["updated"], [])

    def test_a_personal_name_that_is_not_a_relation_word_is_left_alone(self) -> None:
        existing = roster(row("James Taylor", "james-taylor", "parent"))
        # already has a relationship -- never re-decided
        result = er.relationship_from_own_name(existing, dry_run=True)
        self.assertEqual(result["updated"], [])


# --------------------------------------------------------------------------
# 4. An ambiguous grandmother -> one card
# --------------------------------------------------------------------------


class AmbiguousGrandparentGetsOneCard(unittest.TestCase):

    def test_betty_jo_gets_exactly_one_side_card(self) -> None:
        existing = roster(
            row("Grandma Betty Jo", "grandma-betty-jo", "grandparent",
                aliases=["Grandma", "Betty Jo"]))
        rows = er.grandparent_side_rows(existing)
        self.assertEqual(len(rows), 1)
        cards = er.grandparent_side_cards(rows, now=NOW)
        self.assertEqual(len(cards), 1)
        card = cards[0]
        self.assertEqual(card["kind"], "relation_word")
        self.assertEqual(card["requested_field"], "grandparent_side")
        self.assertEqual(card["subject_ref"], "person/grandma-betty-jo")
        self.assertIn("mom's side", card["prompt_intent"])
        self.assertIn("dad's", card["prompt_intent"])
        self.assertNotIn("mother", card["prompt_intent"])
        refs = {c["ref"] for c in card["candidates"]}
        self.assertEqual(refs, {"maternal", "paternal", "unspecified"})

    def test_a_grandfather_gets_the_same_card_never_gendered_wrong(self) -> None:
        """James Edwin Taylor Sr. is a grandFATHER; the question must never
        say "mother" for him -- side-based wording, not gendered."""
        existing = roster(
            row("James Edwin Taylor Sr.", "james-edwin-taylor-sr", "grandparent"))
        rows = er.grandparent_side_rows(existing)
        cards = er.grandparent_side_cards(rows, now=NOW)
        self.assertEqual(len(cards), 1)
        self.assertNotIn("mother", cards[0]["prompt_intent"])

    def test_once_the_side_is_known_no_card_is_minted(self) -> None:
        existing = roster(
            row("Grandma Betty Jo", "grandma-betty-jo", "grandparent",
                grandparent_side="maternal"))
        rows = er.grandparent_side_rows(existing)
        self.assertEqual(rows, ())

    def test_never_a_collective_or_unrelated_relationship(self) -> None:
        existing = roster(
            row("Grandparents", "grandparents", "grandparent"),  # collective
            row("Katie Taylor", "katie-taylor", "spouse"),
        )
        rows = er.grandparent_side_rows(existing)
        self.assertEqual(rows, ())


if __name__ == "__main__":
    unittest.main()
