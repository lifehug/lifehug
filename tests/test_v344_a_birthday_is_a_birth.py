"""v344 — a birthday is a birth, and anyone's age is measured from their own birth.

The owner reviewed staging on 2026-09-24. He had filed his mother's birthday as
a manual source ten days earlier —
`sources/manual/2026-09-14-desiree-birthday-1955-06-19.md`, *"Desiree Taylor
(Dave's mom, also called Desi) — birthday June 19, 1955."* — and the classifier
read it perfectly: `claim:da4f59afb2d774e0b9ebef87`, `claim_type: "date"`,
1955-06-19 certain/stated, `event_mention: "Desiree Taylor's birthday"`,
`subject_mention: "Desiree Taylor (Desi)"`, `subject_ref: null`. Three things
then went wrong at once:

1. the node it drew, `node:8a3a570270bef180b1bb9eb7`, was `event_kind: "moment"`
   — a claim extractor cannot say what KIND of event a birthday is — so
   `births_by_subject`, which reads birth-kinded nodes, never saw it;
2. its subject resolved to nobody: the person roster's thirteen rows held a
   COLLECTIVE ``parents`` (``"Mom and Dad (parents)"``) and no mother, so
   "Desiree Taylor", "Desi", "Mom" and "mother" answered to no one;
3. and it published `axis_membership: owner / lived` — drawn on his own axis as
   something he lived, twenty-six years before his 1981-07-11 birth — because
   the zero-candidate fallback reads a name the roster cannot place as the
   ordinary shape of the owner's own life.

The cards he saw were the consequences. *"When did Mom married dad at 21
happen?"* (`claim:34c92ccbf218e122a181ca5f`, an ``age`` claim of 21 with
`subject_mention: "mother"`, from `answers/K14.md`) stayed
``age_without_birth_anchor`` although her birthday was in the same vault. And
*"When did Harvey explains rule about cussing happen?"*
(`claim:73bf36cabc03f2c4fd3b397e`, age 4, `subject_mention: "Harvey"`) could not
anchor either, because Harvey's own merged birth node
(`node:f617262f723b943266375d93`, 2021-10-11, eleven tellings) came out of the
v340 fold labelled *"your birth"* with the OWNER as its subject — two of those
tellings carry `subject_mention: "self"` because the owner is the subject of the
TURNING POINT and the birth is only what turned it — and so minted the card
*"Two dates are claimed for your birth — 11 October 2021 and 2020."*

Six rules ship here, one definition each:

* `landmark_projection.birth_event_subject` — the birth vocabulary read
  FORWARDS: which person's birth an event mention names;
* `temporal_timeline.A_DATED_BIRTHDAY_IS_A_BIRTH` — that mention plus a
  day/month/year date plus a named non-owner subject is a ``birth``, read at
  fold time so a vault heals on its next redraw;
* `roster_relations.A_RELATIONSHIP_PHRASE_INTRODUCES_A_PERSON` — a person a
  source introduces with a relationship phrase EXISTS, with that relationship,
  through the roster's own writer;
* `temporal_timeline.AN_AGE_IS_MEASURED_FROM_ITS_OWN_SUBJECT` — three tiers, in
  order, and ``age_without_birth_anchor`` only when none of them answers;
* `temporal_timeline.A_BIRTH_BELONGS_TO_THE_PERSON_BORN` — v339's rule read
  forwards: a birth group naming one non-owner person is that person's birth;
* and rule 4 of the axis ruling moved above the evidence relations, so a node
  wholly before the owner's birth is ``pre_birth`` whoever it turned out to be
  about.

Measured on a scratch clone of the owner's vault (rig, generation 152 → 153,
against v343 bytes): 0 placements lost, 0 dated moments moved, 3 new age
placements — *"Mom married dad at 21"* 1976-06-19/1977-06-18, *"Harvey explains
rule about cussing"* and *"Harvey's late talking start"* 2025-10-11/2026-10-10 —
cards 40 → 38, `age_without_birth_anchor` 16 → 13, the owner's five age frames
byte-identical, and the contradiction card now reading *"Two dates are claimed
for Harvey's birth"*. Every negative below was run against a build with its guard removed
and SEEN failing first.
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
import chronology as chrono  # noqa: E402
import landmark_projection as lp  # noqa: E402
import landmarks_interaction as li  # noqa: E402
import roster_relations as rr  # noqa: E402
import temporal_projection as tp  # noqa: E402
import temporal_timeline as tt  # noqa: E402
from tempdirs import root_parent_tmp  # noqa: E402

# One spelling of "the shape a vault's receipts actually have", reused rather
# than re-derived — the same reason v342 reuses it.
from test_v340_apply_keeps_placements import (  # noqa: E402
    NOW,
    claim,
    index_of,
    value,
    write_vault,
)

OWNER = tt.DEFAULT_OWNER_REF
BIRTH_DAY = "1981-07-11"

# --------------------------------------------------------------------------
# The owner's own fixtures, in the shapes his vault filed them
# --------------------------------------------------------------------------

#: The manual source, verbatim enough that the relationship phrase and the
#: nickname are both in it.
DESIREE_SOURCE = "classification:sources-manual-2026-09-14-desiree-birthday#8c614ea83083"
DESIREE_QUOTE = ("Desiree Taylor (Dave's mom) was born on June 19, 1955. "
                 "(when_hint: birthday June 19, 1955)")
K14 = "classification:answers-k14#0965c15bc3c2"
HARVEY_SHEET = "classification:sources-manual-birthdays#30ee8148d88d"
HARVEY_TURNING = "classification:answers-q3#cc4ecfa2c704"
HARVEY_CUSSING = "classification:sources-manual-2026-08-29-harvey#1229dbd0175b"

MOTHER_ROW = {
    "name": "Desiree Taylor", "slug": "desiree-taylor",
    "aliases": ["Desiree Taylor (Desi)", "Desi", "mom", "my mom", "mother", "my mother"],
    "relationship": "parent", "source": "landmark:family",
    "born": chrono.normalized_date(value("1955-06-19")),
}
HARVEY_ROW = {
    "name": "Harvey", "slug": "harvey", "aliases": [],
    "relationship": "child", "source": "landmark:family",
    "born": chrono.normalized_date(value("2020")),
}


def roster(*rows) -> dict:
    return {"version": 1, "type": "person", "entities": [dict(row) for row in rows]}


def owner_birth() -> dict:
    """The owner's birthday in the spelling his own vault files it in: the
    landmark DOMAIN word as the subject mention, which the fold resolves to him
    (v339/v340's own fixture)."""
    return claim(claim_type="date", subject_mention="birth", event_kind="birth",
                 source="landmark:entry-birth", temporal_value=value(BIRTH_DAY),
                 quote="I was born on 11 July 1981.")


def desiree_birthday() -> dict:
    """`claim:da4f59afb2d774e0b9ebef87`, in its own shape: a ``date`` claim, kind
    ``moment``, the birthday in the event mention and the relationship phrase in
    the evidence quote."""
    return claim(claim_type="date", subject_mention="Desiree Taylor (Desi)",
                 event_kind="moment", source=DESIREE_SOURCE,
                 temporal_value=value("1955-06-19"),
                 event_mention="Desiree Taylor's birthday", quote=DESIREE_QUOTE)


def mother_married_at_21() -> dict:
    """`claim:34c92ccbf218e122a181ca5f`."""
    return claim(claim_type="age", subject_mention="mother", event_kind="moment",
                 source=K14, temporal_value="21",
                 event_mention="Mom married dad at 21",
                 quote="Mom got married young, at age 21, and had kids right away")


#: The merged node the v340 fold produced on the owner's own vault. The three
#: tellings below all carry it as their ``event_ref``, which is what the binder's
#: `R2b` did for real: eleven tellings, one node.
HARVEY_BIRTH_NODE = "node:f617262f723b943266375d93"


def harvey_birth_tellings() -> list:
    """The merged birth: one telling that NAMES the child (resolved), and two
    that say ``self`` because the owner is the subject of the turning point."""
    return [
        claim(claim_type="date", subject_mention="Harvey Rex Taylor",
              subject_ref="person/harvey", event_kind="birth", source=HARVEY_SHEET,
              event_ref=HARVEY_BIRTH_NODE, temporal_value=value("2021-10-11"),
              event_mention="Harvey Rex Taylor's birth",
              quote="Harvey Rex Taylor — October 11, 2021"),
        claim(claim_type="occurrence", subject_mention="self", event_kind="moment",
              source=HARVEY_TURNING, event_ref=HARVEY_BIRTH_NODE,
              event_mention="Harvey's birth as turning point",
              quote="Harvey's birth was the turning point for me."),
        claim(claim_type="date", subject_mention="self", event_kind="birth",
              source=HARVEY_TURNING, event_ref=HARVEY_BIRTH_NODE,
              temporal_value=value("2020"),
              event_mention="Harvey's birth as turning point",
              quote="Harvey's birth was the turning point for me — 2020."),
    ]


def harvey_cussing() -> dict:
    """`claim:73bf36cabc03f2c4fd3b397e` — age 4, subject already resolved."""
    return claim(claim_type="age", subject_mention="Harvey",
                 subject_ref="person/harvey", event_kind="moment",
                 source=HARVEY_CUSSING, temporal_value="4",
                 event_mention="Harvey explains rule about cussing",
                 quote="Harvey boy is four years old. What day is it today August 29, 2026")


def derive(claims, *, roster_snapshot=(), landmark_entries=()):
    return tt.derive_calculated_timeline(
        index_of(claims), roster_snapshot=roster_snapshot,
        landmark_entries=landmark_entries, now=NOW,
    )


def node_labelled(result, label: str) -> dict:
    rows = [node for node in result.nodes if node.get("label") == label]
    assert len(rows) == 1, f"{label!r} names {len(rows)} nodes: " + \
        repr([n.get("label") for n in result.nodes])
    return rows[0]


def node_of_claim(result, claim_id_fragment: str) -> dict:
    rows = [node for node in result.nodes
            if any(claim_id_fragment in ref for ref in node.get("input_claim_refs") or ())]
    assert len(rows) == 1, f"{claim_id_fragment} names {len(rows)} nodes"
    return rows[0]


def findings(result) -> list:
    return [row.get("finding") for row in result.diagnostics.get("findings") or ()]


def window(node: dict) -> tuple:
    row = node.get("best_temporal_value") or {}
    return row.get("earliest"), row.get("latest"), row.get("basis")


# --------------------------------------------------------------------------
# 1. The vocabulary, read forwards
# --------------------------------------------------------------------------


class BirthEventSubjectTests(unittest.TestCase):
    """`landmark_projection.birth_event_subject` as a unit."""

    def test_the_nouns_are_a_subset_of_the_one_birth_vocabulary(self) -> None:
        """v341 established ONE definition of the birth domain's words. This is
        that set asked a different question, never a second list."""
        self.assertTrue(lp.BIRTH_EVENT_NOUNS <= lp.BIRTH_DOMAIN_WORDS)

    def test_the_owners_own_birthday_names_nobody(self) -> None:
        """Every possessive-owner spelling is deliberately absent from the
        nouns: the owner's birth is v339/v340's, not this rule's."""
        for text in ("my birthday", "your birth", "owner's birth", "i was born",
                     "birthday", "born", "date of birth"):
            with self.subTest(text):
                self.assertEqual(lp.birth_event_subject(text), "")

    def test_a_named_persons_birthday_names_them(self) -> None:
        for text, name in (
            ("Desiree Taylor's birthday", "Desiree Taylor"),
            ("Desiree Taylor’s birthday", "Desiree Taylor"),
            ("Harvey's birth date", "Harvey"),
            ("Harvey Rex Taylor's birth", "Harvey Rex Taylor"),
            ("my brother James's birthday", "my brother James"),
            ("Katie was born", "Katie"),
            ("Grandma Betty Jo's date of birth", "Grandma Betty Jo"),
        ):
            with self.subTest(text):
                self.assertEqual(lp.birth_event_subject(text), name)

    def test_v341s_own_refusals_still_refuse(self) -> None:
        """"Mary Born" is a person and "Bornstein" is a name — v341's ruling,
        and a whole-token rule is what keeps it true."""
        for text in ("Mary Born", "Bornstein", "Desiree's birthday cake",
                     "the birth's date", "Dad's death", "Katie's wedding", ""):
            with self.subTest(text):
                self.assertEqual(lp.birth_event_subject(text), "")

    def test_the_noun_must_be_the_whole_tail(self) -> None:
        """Never a substring search: one more word after the noun and the
        mention is prose about a scene, not a name for a birth."""
        self.assertEqual(lp.birth_event_subject("Harvey's birthday party"), "")


class BirthDateSemanticsParityTests(unittest.TestCase):
    """The fold cannot read `interactions/landmarks/questions.yaml`; this test
    can, so a ladder that changes its semantics fails the build."""

    def test_the_domains_match_the_ladder(self) -> None:
        rows = li.load_questions()
        declared = {
            row["domain"] for row in rows
            if lp.BIRTH_DATE_SEMANTICS in (row.get("date_semantics") or ())
            and row["domain"] != lp.OWNER_BIRTH_DOMAIN
        }
        self.assertEqual(set(lp.BIRTH_DATE_SEMANTICS_DOMAINS), declared)

    def test_the_owners_own_domain_is_not_one_of_them(self) -> None:
        self.assertNotIn(lp.OWNER_BIRTH_DOMAIN, lp.BIRTH_DATE_SEMANTICS_DOMAINS)


# --------------------------------------------------------------------------
# 2. A dated birthday is a birth
# --------------------------------------------------------------------------


class ADatedBirthdayIsABirthTests(unittest.TestCase):

    def test_the_owners_own_claim_reads_as_a_birth(self) -> None:
        self.assertTrue(tt.reads_as_a_birth(desiree_birthday(), owner_ref=OWNER))

    def test_an_owner_subject_is_never_read_this_way(self) -> None:
        """v339/v340 govern the owner's birth alone. Three spellings of "this is
        the owner" and every one of them refuses."""
        for overrides in (
            {"subject_ref": OWNER},
            {"subject_mention": "self"},
            {"subject_mention": "birthday"},
        ):
            with self.subTest(overrides):
                row = {**desiree_birthday(), **overrides}
                self.assertFalse(tt.reads_as_a_birth(row, owner_ref=OWNER))

    def test_a_recorded_kind_is_never_re_decided(self) -> None:
        """This rule fills a gap. A claim that says what it is keeps saying it."""
        for kind in ("death", "married", "graduation", "move"):
            with self.subTest(kind):
                row = {**desiree_birthday(), "event_kind": kind}
                self.assertFalse(tt.reads_as_a_birth(row, owner_ref=OWNER))
                self.assertEqual(tt._read_event_kind(row, owner_ref=OWNER), kind)

    def test_a_ranged_date_is_not_a_birthday(self) -> None:
        """"Born sometime in the seventies" is a window, and reading it as a
        birth would hand the age arithmetic an anchor nobody stated."""
        row = {**desiree_birthday(),
               "temporal_value": {"best": "1950/1959", "earliest": "1950",
                                  "latest": "1959", "granularity": "range",
                                  "basis": "stated", "confidence": "approximate"}}
        self.assertFalse(tt.reads_as_a_birth(row, owner_ref=OWNER))

    def test_every_grain_a_birthday_can_be_given(self) -> None:
        for text in ("1955-06-19", "1955-06", "1955"):
            with self.subTest(text):
                row = {**desiree_birthday(), "temporal_value": value(text)}
                self.assertTrue(tt.reads_as_a_birth(row, owner_ref=OWNER))

    def test_an_undated_claim_is_not_a_birthday(self) -> None:
        row = claim(claim_type="occurrence", subject_mention="Desiree Taylor",
                    event_kind="moment", source=DESIREE_SOURCE,
                    event_mention="Desiree Taylor's birthday", quote=DESIREE_QUOTE)
        self.assertFalse(tt.reads_as_a_birth(row, owner_ref=OWNER))

    def test_the_fold_draws_it_as_a_birth_and_keeps_the_receipt(self) -> None:
        """A READING over the substrate: the node is a birth and the claim on
        disk still says ``moment``."""
        claims = [owner_birth(), desiree_birthday()]
        result = derive(claims, roster_snapshot=roster(MOTHER_ROW))
        node = node_labelled(result, "Desiree Taylor's birth")
        self.assertEqual(node["event_kind"], "birth")
        self.assertEqual(node["subject_refs"], ["person/desiree-taylor"])
        self.assertEqual(node["best_temporal_value"]["best"], "1955-06-19")
        self.assertEqual(claims[1]["event_kind"], "moment")

    def test_the_node_id_does_not_move_when_the_claim_carries_one(self) -> None:
        """The reading changes what a node IS, never where it lives: a claim
        with its own ``event_ref`` keeps that key, so a vault that already
        points at the node heals rather than forking."""
        keyed = {**desiree_birthday(), "event_ref": "node:8a3a570270bef180b1bb9eb7"}
        result = derive([owner_birth(), keyed], roster_snapshot=roster(MOTHER_ROW))
        node = node_labelled(result, "Desiree Taylor's birth")
        self.assertEqual(node["node_id"], "node:8a3a570270bef180b1bb9eb7")


# --------------------------------------------------------------------------
# 3. The person a relationship phrase introduces
# --------------------------------------------------------------------------


class RelationshipIntroductionTests(unittest.TestCase):

    def test_the_owners_own_sentence(self) -> None:
        row = rr.relationship_introduction(
            "Desiree Taylor (Desi)",
            ["Desiree Taylor (Dave's mom, also called Desi) — birthday June 19, 1955."],
            owner_names=("Dave", "David James Taylor"),
        )
        self.assertEqual(row["name"], "Desiree Taylor")
        self.assertEqual(row["slug"], "desiree-taylor")
        self.assertEqual(row["relationship"], "parent")
        self.assertIn("Desi", row["aliases"])
        self.assertIn("mother", row["aliases"])
        self.assertIn("my mom", row["aliases"])

    def test_every_shape_the_owners_vault_writes(self) -> None:
        for text, name, relationship in (
            ("Katie Taylor (wife) — May 15, 1987", "Katie Taylor", "spouse"),
            ("A.J. (brother) plays guitar", "A.J.", "sibling"),
            ("Desiree Taylor, my mother, got married at 21", "Desiree Taylor", "parent"),
            ("my mother Desiree Taylor got married at 21", "Desiree Taylor", "parent"),
            ("Dave's dad James Taylor started a pool company", "James Taylor", "parent"),
        ):
            with self.subTest(text):
                row = rr.relationship_introduction(name, [text], owner_names=("Dave",))
                self.assertIsNotNone(row, text)
                self.assertEqual(row["relationship"], relationship)

    def test_somebody_elses_relative_is_not_the_owners(self) -> None:
        """The possessive has to be the OWNER's: "Katie's mom" is not his
        mother, and a relation word loose in the sentence names nobody."""
        for text in ("Katie's mom Desiree Taylor",
                     "Desiree Taylor was there and my mom made dinner"):
            with self.subTest(text):
                self.assertIsNone(rr.relationship_introduction(
                    "Desiree Taylor", [text], owner_names=("Dave",)))

    def test_a_mention_with_no_name_introduces_nobody(self) -> None:
        """"mother" is the thing an introduction is supposed to give a name to."""
        for mention in ("mother", "my mom", "self", "Mom"):
            with self.subTest(mention):
                self.assertIsNone(rr.relationship_introduction(
                    mention, ["my mom made dinner"], owner_names=("Dave",)))

    def test_an_in_law_is_never_immediate_family(self) -> None:
        """"mother-in-law" contains "mother" and is not the owner's mother —
        `axis_membership.IN_LAW_RE`, the one definition of that reading."""
        row = rr.relationship_introduction(
            "Ruth Alder", ["my mother-in-law Ruth Alder retired"], owner_names=("Dave",))
        self.assertEqual(row["relationship_word"], "mother")
        self.assertEqual(row["relationship"], "other")
        self.assertNotIn(row["relationship"], axm.IMMEDIATE_FAMILY_RELATIONSHIPS)
        self.assertIn(axm.relationship_tier(row["relationship"]), (axm.DISTANT_TIER,))
        self.assertEqual(row["aliases"], ())

    def test_the_relationship_lands_in_the_rulings_own_tier(self) -> None:
        """The owner asked for "mother/father -> parent tier". Derived from the
        two existing vocabularies, and asserted against the ruling's set."""
        for word in ("mom", "mother", "dad", "father", "brother", "sister",
                     "son", "daughter", "wife", "husband", "grandma", "grandpa"):
            with self.subTest(word):
                relationship = rr.roster_relationship_for(word)
                self.assertIn(relationship, axm.IMMEDIATE_FAMILY_RELATIONSHIPS)
                self.assertEqual(axm.relationship_tier(relationship),
                                 axm.IMMEDIATE_FAMILY_TIER)

    def test_a_relationship_word_never_brings_the_other_sex_along(self) -> None:
        """Set EQUALITY, not "maps to the same relationship": "mom" brings
        "mother" and must never bring "dad"."""
        self.assertEqual(rr.relationship_aliases("mom"),
                         ("mom", "my mom", "mother", "my mother"))
        self.assertNotIn("dad", rr.relationship_aliases("mom"))
        self.assertEqual(rr.relationship_aliases("wife"), ("wife", "my wife"))

    def test_the_owners_whole_substrate_introduces_four_people(self) -> None:
        """Over the claim set, keyed by source, and the contested alias dropped
        from BOTH rows — the owner's vault names his father twice."""
        claims = [
            desiree_birthday(),
            claim(claim_type="date", subject_mention="James Taylor (Dad)",
                  event_kind="moment", source="classification:sources-a#1de1825b38f6",
                  temporal_value=value("1955"),
                  event_mention="James Taylor (Dad)'s birthday",
                  quote="James Taylor (Dad) was born in 1955."),
            claim(claim_type="occurrence", subject_mention="James Edwin Taylor Sr.",
                  event_kind="moment", source="classification:sources-b#59031241b713",
                  event_mention="grandfather's record",
                  quote="My dad James Edwin Taylor Sr. ran the shop."),
        ]
        rows = rr.relationship_introductions(claims, roster=roster(),
                                            owner_names=("Dave",))
        by_slug = {row["slug"]: row for row in rows}
        self.assertEqual(sorted(by_slug), ["desiree-taylor", "james-edwin-taylor-sr",
                                           "james-taylor"])
        self.assertIn("mother", by_slug["desiree-taylor"]["aliases"])
        self.assertEqual(by_slug["desiree-taylor"]["born"], "1955-06-19")
        for slug in ("james-taylor", "james-edwin-taylor-sr"):
            with self.subTest(slug):
                self.assertNotIn("dad", by_slug[slug]["aliases"])
                self.assertIn("dad", by_slug[slug]["contested_aliases"])

    def test_a_name_the_roster_already_answers_to_is_not_an_introduction(self) -> None:
        """This rule writes the row nobody has written; it never re-decides
        one somebody has."""
        rows = rr.relationship_introductions(
            [desiree_birthday()], roster=roster(MOTHER_ROW), owner_names=("Dave",))
        self.assertEqual(rows, ())


class TheWriterSeatTests(unittest.TestCase):
    """`entity_roster.ensure_introduced_relatives` — one door, additive,
    idempotent, and it never steals an alias."""

    def setUp(self) -> None:
        self.root = root_parent_tmp(self, ROOT, prefix="lifehug-v344-roster-")
        (self.root / "system").mkdir(parents=True, exist_ok=True)
        (self.root / "state" / "entity_rosters").mkdir(parents=True, exist_ok=True)
        # The owner's spellings come from the VAULT being read
        # (`temporal_publication.owner_identity_inputs`), which is what makes
        # "Dave's mom" the owner's mother and "Katie's mom" somebody else's.
        (self.root / "profile.yaml").write_text("name: Dave\n", encoding="utf-8")
        write_vault(self.root, [owner_birth(), desiree_birthday()])

    def _run(self, *, existing=None, dry_run=False) -> dict:
        import entity_roster  # noqa: PLC0415
        import lifehug_core  # noqa: PLC0415

        path = self.root / "state" / "entity_rosters" / "person.json"
        path.write_text(json.dumps(existing if existing is not None else roster()),
                        encoding="utf-8")
        # `entity_verdict` imports `entity_roster.roster_file` itself, so
        # redirecting the one module attribute both of them read is enough — the
        # write really does go through the production door.
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

    def test_the_mother_gets_a_row_with_her_relationship_and_her_birthday(self) -> None:
        result = self._run()
        rows = {row["slug"]: row for row in result["roster"]["entities"]}
        self.assertIn("desiree-taylor", rows)
        row = rows["desiree-taylor"]
        self.assertEqual(row["relationship"], "parent")
        self.assertEqual(row["born"]["best"], "1955-06-19")
        self.assertEqual(row["source"], "landmark:family")
        self.assertFalse(row["page_eligible"])
        self.assertIn("mother", row["aliases"])

    def test_a_dry_run_writes_nothing(self) -> None:
        result = self._run(dry_run=True)
        self.assertEqual(result["roster"]["entities"], [])
        self.assertEqual(len(result["introduced"]), 1)

    def test_running_it_twice_converges(self) -> None:
        first = self._run()
        second = self._run(existing=first["roster"])
        self.assertEqual(second["filed"], 0)
        self.assertEqual(second["roster"], first["roster"])

    def test_an_alias_another_row_answers_to_is_left_alone(self) -> None:
        """The roster's own shared-alias refusal, read BEFORE the write."""
        squatter = {"name": "Mother Figure", "slug": "mother-figure",
                    "aliases": ["mother"], "qualifies": False,
                    "page_eligible": False, "maps_to_focus": None}
        result = self._run(existing=roster(squatter))
        rows = {row["slug"]: row for row in result["roster"]["entities"]}
        self.assertNotIn("mother", rows["desiree-taylor"]["aliases"])
        self.assertIn("mother", rows["mother-figure"]["aliases"])
        self.assertTrue(any(row["alias"] == "mother"
                            for row in result["skipped_aliases"]))


# --------------------------------------------------------------------------
# 4. Anyone's age anchors on their own birth
# --------------------------------------------------------------------------


class BirthsBySubjectTests(unittest.TestCase):
    """The three tiers, in order, as a unit."""

    def groups(self, claims, *, roster_snapshot=()):
        resolved, _records, _ = tt._resolve_subjects(
            claims, resolution_records=(), roster_snapshot=roster_snapshot,
            now=NOW, owner_ref=OWNER,
        )
        return tt._group_claims(resolved, owner_ref=OWNER)

    def index(self, claims, *, roster_snapshot=(), landmark_entries=()):
        return tt._births_by_subject(
            self.groups(claims, roster_snapshot=roster_snapshot),
            roster_snapshot=roster_snapshot, landmark_entries=landmark_entries,
            owner=OWNER,
        )

    def test_the_tiers_are_named_once(self) -> None:
        self.assertEqual(tt.BIRTH_ANCHOR_TIERS,
                         ("birth_node", "roster_born", "landmark_birth"))

    def test_tier_one_a_birth_node_of_their_own(self) -> None:
        index = self.index([owner_birth(), desiree_birthday()],
                           roster_snapshot=roster(MOTHER_ROW))
        self.assertEqual(index["person/desiree-taylor"].best, "1955-06-19")

    def test_tier_two_the_roster_born(self) -> None:
        """Nothing in the substrate says when she was born; the roster does."""
        index = self.index([owner_birth()], roster_snapshot=roster(MOTHER_ROW))
        self.assertEqual(index["person/desiree-taylor"].best, "1955-06-19")
        self.assertEqual(index["mother"].best, "1955-06-19")

    def test_tier_three_a_children_landmark_entry(self) -> None:
        entries = [{
            "source_id": "landmark:entry-kid", "domain": "children",
            "entry_key": "harvey-rex-taylor",
            "record": {"domain": "children", "who": "Harvey Rex Taylor",
                       "date": value("2021-10-11")},
        }]
        index = self.index([owner_birth()], roster_snapshot=roster(),
                           landmark_entries=entries)
        self.assertEqual(index["harvey rex taylor"].best, "2021-10-11")

    def test_a_birth_node_outranks_the_roster_and_the_landmark(self) -> None:
        """The whole point of the ordering, and the owner's own case: Harvey's
        roster row says 2020 and his birth node says 2021-10-11."""
        entries = [{
            "source_id": "landmark:entry-kid", "domain": "children",
            "entry_key": "harvey", "record": {"domain": "children", "who": "Harvey",
                                              "date": value("2019")},
        }]
        index = self.index([owner_birth(), *harvey_birth_tellings()],
                           roster_snapshot=roster(HARVEY_ROW),
                           landmark_entries=entries)
        for key in ("person/harvey", "harvey"):
            with self.subTest(key):
                self.assertEqual(index[key].best, "2021-10-11")

    def test_a_contested_birth_still_anchors_at_its_best_supported_reading(self) -> None:
        """v342 refused here and fell through to the roster's ``born`` — which
        is one side of the very contradiction, chosen silently and wrongly. The
        owner's own anchor has always been read this way; now everyone's is."""
        index = self.index([owner_birth(), *harvey_birth_tellings()],
                          roster_snapshot=roster(HARVEY_ROW))
        self.assertEqual(index["person/harvey"].best, "2021-10-11")

    def test_a_name_several_people_bear_anchors_nobody(self) -> None:
        """The v335 shared-name rule, kept: four people on the owner's roster
        bear the token *James*, so a bare "James" must go on naming none of
        them rather than taking the brother's birthday."""
        rows = roster(
            {"name": "James", "slug": "james", "aliases": [], "relationship": "sibling",
             "born": chrono.normalized_date(value("1990-03-20"))},
            {"name": "James Everett Taylor", "slug": "james-everett-taylor",
             "aliases": ["James"], "relationship": "child",
             "born": chrono.normalized_date(value("2013-05-10"))},
        )
        index = self.index([owner_birth()], roster_snapshot=rows)
        self.assertNotIn("james", index)
        self.assertEqual(index["person/james"].best, "1990-03-20")

    def test_two_birth_nodes_for_one_person_anchor_nothing(self) -> None:
        """Two groups answering to one subject is a standoff, not a birthday."""
        second = {**desiree_birthday(),
                  "event_ref": "node:1111111111111111111111aa",
                  "source_ref": {"source_id": "classification:sources-other#ffffffffffff",
                                 "revision": "sha256:" + "0" * 64},
                  "temporal_value": value("1956-06-19")}
        index = self.index([owner_birth(), desiree_birthday(), second],
                          roster_snapshot=roster(
                              {k: v for k, v in MOTHER_ROW.items() if k != "born"}))
        self.assertNotIn("person/desiree-taylor", index)

    def test_the_owners_own_birth_is_not_read_here(self) -> None:
        """`_owner_birth_readings` owns that question, and `birth_for_group`
        asks it first."""
        index = self.index([owner_birth()], roster_snapshot=roster())
        self.assertNotIn(OWNER, index)


class AnAgeIsMeasuredFromItsOwnSubjectTests(unittest.TestCase):

    def test_the_mothers_marriage_is_dated_from_the_mothers_birthday(self) -> None:
        """The owner's card, answered: age 21 from 1955-06-19."""
        result = derive([owner_birth(), desiree_birthday(), mother_married_at_21()],
                        roster_snapshot=roster(MOTHER_ROW))
        node = node_labelled(result, "Mom married dad at 21")
        self.assertEqual(window(node), ("1976-06-19", "1977-06-18", "age"))
        self.assertNotIn("age_without_birth_anchor", findings(result))

    def test_it_overlaps_the_parents_wedding_landmark(self) -> None:
        """Not asserted as arithmetic the fold does — it does not — but as the
        corroboration the owner will see: his parents' `family` landmark says
        1976-06-25, which is inside the window age 21 produces."""
        result = derive([owner_birth(), desiree_birthday(), mother_married_at_21()],
                        roster_snapshot=roster(MOTHER_ROW))
        node = node_labelled(result, "Mom married dad at 21")
        earliest, latest, _ = window(node)
        self.assertLessEqual(earliest, "1976-06-25")
        self.assertGreaterEqual(latest, "1976-06-25")

    def test_the_child_is_dated_from_the_childs_birth(self) -> None:
        """Age 4 from 2021-10-11, and the capture date (2026-08-29) sits inside
        the window the owner expects to see."""
        result = derive([owner_birth(), *harvey_birth_tellings(), harvey_cussing()],
                        roster_snapshot=roster(HARVEY_ROW))
        node = node_labelled(result, "Harvey explains rule about cussing")
        self.assertEqual(window(node), ("2025-10-11", "2026-10-10", "age"))

    def test_the_arithmetic_stayed_subject_agnostic(self) -> None:
        """`_record_for_age_claim` takes a birth and a band and knows nothing
        about whose they are — which is why only ONE thing changed."""
        record, finding = tt._record_for_age_claim(
            mother_married_at_21(), chrono.from_dict(value("1955-06-19")))
        self.assertEqual(finding, "")
        self.assertEqual((record.earliest, record.latest), ("1976-06-19", "1977-06-18"))

    def test_the_anchor_is_missing_only_when_all_three_tiers_are(self) -> None:
        result = derive([owner_birth(), mother_married_at_21()], roster_snapshot=roster())
        node = node_labelled(result, "Mom married dad at 21")
        self.assertIsNone(node["best_temporal_value"])
        self.assertIn("age_without_birth_anchor", findings(result))

    def test_the_roster_alone_is_enough(self) -> None:
        """Tier 2 on its own: no birthday claim in the substrate at all."""
        result = derive([owner_birth(), mother_married_at_21()],
                        roster_snapshot=roster(MOTHER_ROW))
        node = node_labelled(result, "Mom married dad at 21")
        self.assertEqual(window(node), ("1976-06-19", "1977-06-18", "age"))

    def test_the_owners_own_age_still_reads_his_own_anchor(self) -> None:
        owner_age = claim(claim_type="age", subject_mention="self",
                          event_kind="moment", source="classification:answers-a1#ccc",
                          temporal_value="26", event_mention="Went bankrupt at 26",
                          quote="I went bankrupt at 26.")
        result = derive([owner_birth(), owner_age, desiree_birthday(),
                         mother_married_at_21()], roster_snapshot=roster(MOTHER_ROW))
        node = node_labelled(result, "Went bankrupt at 26")
        self.assertEqual(window(node), ("2007-07-11", "2008-07-10", "age"))


# --------------------------------------------------------------------------
# 5. The merged birth carries the child's subject
# --------------------------------------------------------------------------


class ABirthBelongsToThePersonBornTests(unittest.TestCase):

    def group(self, claims, *, roster_snapshot=()) -> dict:
        resolved, _, _ = tt._resolve_subjects(
            claims, resolution_records=(), roster_snapshot=roster_snapshot,
            now=NOW, owner_ref=OWNER)
        groups = tt._group_claims(resolved, owner_ref=OWNER)
        births = [g for g in groups.values() if g["event_kind"] == "birth"
                  and any("person/harvey" in (c.get("subject_ref") or "")
                          for c in g["claims"])]
        assert len(births) == 1, f"{len(births)} harvey birth groups"
        return births[0]

    def test_the_group_resolves_to_the_child(self) -> None:
        group = self.group(harvey_birth_tellings(), roster_snapshot=roster(HARVEY_ROW))
        self.assertEqual(group["subject"], "person/harvey")
        self.assertIn("self", group["subjects"])

    def test_an_owner_only_mention_on_it_is_the_turning_point(self) -> None:
        group = self.group(harvey_birth_tellings(), roster_snapshot=roster(HARVEY_ROW))
        self.assertFalse(tt._is_owner_subject(group, OWNER))

    def test_two_named_people_on_one_birth_decide_nothing(self) -> None:
        """A standoff is left to v340's own diagnostic, never guessed here."""
        rows = [*harvey_birth_tellings(),
                claim(claim_type="date", subject_mention="Charlee",
                      subject_ref="person/charlee", event_kind="birth",
                      source=HARVEY_SHEET, event_ref=HARVEY_BIRTH_NODE,
                      temporal_value=value("2010-12-21"),
                      event_mention="Charlee's birth", quote="Charlee — 2010")]
        group = self.group(rows, roster_snapshot=roster(HARVEY_ROW))
        self.assertEqual(tt._birth_group_person(group, OWNER), "")

    def test_a_group_that_is_not_a_birth_is_untouched(self) -> None:
        group = {"event_kind": "moment",
                 "claims": [{"subject_ref": "person/harvey"}]}
        self.assertEqual(tt._birth_group_person(group, OWNER), "")

    def test_the_node_is_labelled_and_carded_for_the_child(self) -> None:
        """The owner's own card: *"Two dates are claimed for your birth"* now
        names Harvey."""
        result = derive([owner_birth(), *harvey_birth_tellings()],
                        roster_snapshot=roster(HARVEY_ROW))
        node = node_labelled(result, "Harvey's birth")
        self.assertEqual(node["event_kind"], "birth")
        self.assertEqual(node["conflict_state"], "contradicted")
        prompts = [row["prompt_intent"] for row in result.work_items
                   if row.get("node_ref") == node["node_id"]]
        self.assertTrue(any("Harvey's birth" in text for text in prompts), prompts)
        self.assertFalse(any("your birth" in text for text in prompts), prompts)

    def test_the_owners_own_anchor_stays_single(self) -> None:
        """v340's guarantee, restated: the child's birth is not a second
        birthday for the owner, and the frames still come out of 1981-07-11."""
        result = derive([owner_birth(), *harvey_birth_tellings()],
                        roster_snapshot=roster(HARVEY_ROW))
        self.assertNotIn("owner_birth_anchor_ambiguous", findings(result))
        self.assertNotIn("age_frames_ambiguous_birth", findings(result))
        frames = [n for n in result.nodes if n.get("node_kind") == "period"]
        self.assertTrue(frames)
        self.assertEqual(frames[0]["best_temporal_value"]["earliest"], BIRTH_DAY)

    def test_v340s_own_readings_are_unchanged(self) -> None:
        """`_owner_birth_readings` and `_birth_names_only_the_owner` keep their
        v340/v341 semantics — this release widens who a birth is ABOUT, never
        what counts as the owner's."""
        self.assertTrue(tt.OWNER_BIRTH_IS_ABOUT_NOBODY_ELSE)
        group = {"event_kind": "birth", "claims": [
            {"subject_mention": "birth"}, {"subject_mention": "self"}]}
        self.assertTrue(tt._birth_names_only_the_owner(group, OWNER))
        other = {"event_kind": "birth", "claims": [{"subject_mention": "Harvey"}]}
        self.assertFalse(tt._birth_names_only_the_owner(other, OWNER))


# --------------------------------------------------------------------------
# 6. Pre-birth is never lived
# --------------------------------------------------------------------------


class PreBirthIsNeverLivedTests(unittest.TestCase):

    def row(self, **kwargs) -> tuple:
        payload = {"occurrence_subject_scope": "other_person",
                   "owner_timeline_relation": "contextual_only",
                   "family_tier": axm.UNKNOWN_TIER, "before_owner_birth": False}
        payload.update(kwargs)
        out = axm.axis_membership(**payload)
        return out["axis_membership"], out["axis_membership_reason"]

    def test_pre_birth_outranks_an_evidence_relation(self) -> None:
        """THE DEFECT, at the rule: 1955-06-19 reached this with
        ``participated`` and came out on his axis as something he lived."""
        for relation in tp.AXIS_RELATIONS:
            for tier in axm.FAMILY_TIERS:
                with self.subTest(relation=relation, tier=tier):
                    self.assertEqual(
                        self.row(owner_timeline_relation=relation, family_tier=tier,
                                 before_owner_birth=True),
                        ("none", "pre_birth"))

    def test_pre_birth_outranks_an_unidentified_subject(self) -> None:
        """Nothing about a subject nobody has identified can make 1955 part of
        his life, so this clause does not wait for identity to land."""
        self.assertEqual(
            self.row(occurrence_subject_scope="unresolved",
                     owner_timeline_relation="unresolved", before_owner_birth=True),
            ("none", "pre_birth"))

    def test_an_owner_subject_before_his_birth_is_still_his_contradiction(self) -> None:
        """v334's exception, intact: Mirror owns that row (``life_view:
        contradictory``), and hiding it off the axis would delete the question."""
        self.assertEqual(
            self.row(occurrence_subject_scope="owner",
                     owner_timeline_relation="participated", before_owner_birth=True),
            ("owner", "lived"))

    def test_everything_else_reads_exactly_as_it_did(self) -> None:
        for relation in tp.AXIS_RELATIONS:
            with self.subTest(relation):
                self.assertEqual(self.row(owner_timeline_relation=relation),
                                 ("owner", "lived"))
        self.assertEqual(self.row(occurrence_subject_scope="unresolved",
                                  owner_timeline_relation="unresolved"),
                         ("none", "subject_unresolved"))
        self.assertEqual(self.row(family_tier=axm.IMMEDIATE_FAMILY_TIER),
                         ("family", "immediate_family_in_lifetime"))
        self.assertEqual(self.row(family_tier=axm.DISTANT_TIER), ("none", "not_family"))
        self.assertEqual(self.row(family_tier=axm.UNKNOWN_TIER),
                         ("none", "relationship_unknown"))

    def test_every_input_combination_still_lands_in_the_closed_lists(self) -> None:
        for scope in tp.OCCURRENCE_SUBJECT_SCOPES:
            for relation in tp.OWNER_TIMELINE_RELATIONS:
                for tier in axm.FAMILY_TIERS:
                    for before in (False, True):
                        membership, reason = self.row(
                            occurrence_subject_scope=scope,
                            owner_timeline_relation=relation,
                            family_tier=tier, before_owner_birth=before)
                        self.assertIn(membership, tp.AXIS_MEMBERSHIPS)
                        self.assertIn(reason, tp.AXIS_MEMBERSHIP_REASONS)

    def test_the_mothers_birthday_is_family_history_on_the_owners_vault(self) -> None:
        """End to end, through the fold, in the shapes his vault holds."""
        result = derive([owner_birth(), desiree_birthday()],
                        roster_snapshot=roster(MOTHER_ROW))
        node = node_labelled(result, "Desiree Taylor's birth")
        self.assertEqual(node["axis_membership"], "none")
        self.assertEqual(node["axis_membership_reason"], "pre_birth")
        self.assertFalse(axm.on_owner_axis(node))

    def test_a_nameless_pre_birth_mention_is_not_his_life_either(self) -> None:
        """The zero-candidate fallback, with no roster at all: 1955 is still not
        a shape his life has. (The label reads off the raw mention because
        nothing has a better name for her yet — that is the display layer, and
        `axis_membership` does not wait for it.)"""
        result = derive([owner_birth(), desiree_birthday()], roster_snapshot=roster())
        node = node_labelled(result, "Desiree Taylor (Desi)'s birth")
        self.assertNotEqual(node["occurrence_subject_scope"], "owner")
        self.assertEqual(node["axis_membership_reason"], "pre_birth")


# --------------------------------------------------------------------------
# 7. The whole incident, on one synthetic vault
# --------------------------------------------------------------------------


class TheOwnersReviewTests(unittest.TestCase):
    """Every card the owner filed on 2026-09-24, answered at once."""

    def setUp(self) -> None:
        self.result = derive(
            [owner_birth(), desiree_birthday(), mother_married_at_21(),
             *harvey_birth_tellings(), harvey_cussing()],
            roster_snapshot=roster(MOTHER_ROW, HARVEY_ROW),
        )

    def test_the_mothers_birthday_is_her_birth(self) -> None:
        node = node_labelled(self.result, "Desiree Taylor's birth")
        self.assertEqual(node["event_kind"], "birth")
        self.assertEqual(node["subject_refs"], ["person/desiree-taylor"])
        self.assertEqual(node["axis_membership_reason"], "pre_birth")

    def test_both_age_cards_are_placed(self) -> None:
        self.assertEqual(window(node_labelled(self.result, "Mom married dad at 21")),
                         ("1976-06-19", "1977-06-18", "age"))
        self.assertEqual(
            window(node_labelled(self.result, "Harvey explains rule about cussing")),
            ("2025-10-11", "2026-10-10", "age"))

    def test_no_card_asks_when_either_of_them_happened(self) -> None:
        asked = [row["prompt_intent"] for row in self.result.work_items]
        self.assertFalse([text for text in asked
                          if "Mom married dad at 21" in text
                          or "Harvey explains rule about cussing" in text], asked)

    def test_the_contradiction_is_harveys(self) -> None:
        prompts = [row["prompt_intent"] for row in self.result.work_items
                   if row["kind"] == "contradiction"]
        self.assertTrue(any("Harvey's birth" in text for text in prompts), prompts)

    def test_the_owner_still_has_exactly_one_birthday(self) -> None:
        self.assertNotIn("owner_birth_anchor_ambiguous", findings(self.result))
        frames = [n for n in self.result.nodes if n.get("node_kind") == "period"]
        self.assertEqual(frames[0]["best_temporal_value"]["earliest"], BIRTH_DAY)

    def test_the_rule_version_moved(self) -> None:
        self.assertEqual(tt.CALCULATION_RULE_VERSION, "timeline-rules:17")
        for node in self.result.nodes:
            self.assertEqual(node["calculation_rule_version"], "timeline-rules:17")


if __name__ == "__main__":
    unittest.main()
