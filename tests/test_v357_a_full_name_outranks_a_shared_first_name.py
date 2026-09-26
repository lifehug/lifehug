"""v357 — a full name outranks a shared first name.

The incident, on the owner's own vault (a scratch clone at framework v355):
*"Father's mission to New Zealand"* (`node:80f419115b858c37a7b051f3`) carries
the subject mention ``"James Edwin Taylor"`` — his father's full name — and that
mention bound NOBODY. No roster key spells it (the roster knows his father as
``James Taylor``), and the only rungs that read inside a name were v335's
bare-given-name census, which is about ONE word. So the node's subject stayed
the raw mention, the father's 1954-06-04 birth could not reach it, and every
age said about it was ``age_without_birth_anchor``. Five of his father's nodes
were in that state; one of them, *"Father's four years bedridden"*, carried
exactly that finding.

The roster holds five rows bearing *James* — the five rows below, verbatim in
every field this rule reads:

========================  ============  ==========  ============================
slug                      relationship  born        note
========================  ============  ==========  ============================
``james-taylor``          parent        1954-06-04  his father — the answer
``james-edwin-taylor-sr`` grandparent   1930-10-17  his father's father
``james-everett-taylor``  child         2013-05-10  his son
``anthon-james-taylor``   sibling       1990-03-20  his brother, alias ``James``
``james``                 sibling       1990-03-20  an ALIAS ROW (maps_to_focus)
========================  ============  ==========  ============================

Three rules, each guarded here and each SEEN failing with its guard removed:

1. `identity_resolution.A_FULL_NAME_OUTRANKS_A_SHARED_FIRST_NAME` — a mention
   carrying one person's own full spelling, given name through surname, in
   order, binds that person however many others share the first word.
2. `identity_resolution.A_GENERATIONAL_SUFFIX_IS_ONE_GENERATION` — ``Sr.`` is
   a different person, never a tie, read off the ONE suffix table v347 wrote
   (now `identity_resolution.GENERATIONAL_SUFFIX_STEPS`, re-exported by
   `roster_relations`).
3. `identity_resolution.AN_ALIAS_ROW_IS_NEVER_A_CANDIDATE` — the ``james`` row
   is a pointer, out of the binding path's indexes as v343 already took it out
   of the card path's.

And v335's protection is unmoved: a bare *James* still binds nobody and still
asks — and it may not start borrowing the brother's birthday now that the alias
row no longer happens to stand beside him.

AMENDED (v360, owner 2026-09-25, `timeline-rules:22`): *"When I talk about
James, I'm talking about my son. My dad's name was James too, and so was his
dad. I call my dad Dad and his dad Grandpa, so when I'm talking about James,
I'm talking about my son."* His brother Anthon James goes by AJ. Where the
fold has read what he calls each person (`roster_relations.with_called_by`),
a bare *James* is his son (`identity_resolution
.WHAT_HE_CALLS_THEM_DECIDES_A_BARE_NAME`); the ask below still stands for a
roster whose census was never read, and for tellings that call none of them
anything else.
"""

from __future__ import annotations

import ast
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "system"))
sys.path.insert(0, str(ROOT / "tests"))

import axis_membership as axm  # noqa: E402
import chronology as chrono  # noqa: E402
import identity_resolution as ir  # noqa: E402
import roster_relations as rr  # noqa: E402
import temporal_timeline as tt  # noqa: E402

from test_v340_apply_keeps_placements import NOW, claim, index_of, value  # noqa: E402


def born(day: str) -> dict:
    return chrono.normalized_date(value(day))


# --------------------------------------------------------------------------
# The owner's five roster rows
# --------------------------------------------------------------------------

FATHER = {
    "name": "James Taylor", "slug": "james-taylor",
    "aliases": ["James Taylor (Dad)", "dad", "my dad", "father", "my father"],
    "relationship": "parent", "source": "landmark:family", "qualifies": False,
    "maps_to_focus": None, "born": born("1954-06-04"),
}
GRANDFATHER = {
    "name": "James Edwin Taylor Sr.", "slug": "james-edwin-taylor-sr",
    "aliases": ["grandfather", "my grandfather", "grandpa", "my grandpa"],
    "relationship": "grandparent", "source": "landmark:family", "qualifies": False,
    "maps_to_focus": None, "born": born("1930-10-17"),
}
SON = {
    "name": "James Everett Taylor", "slug": "james-everett-taylor", "aliases": [],
    "relationship": "child", "source": "landmark:family", "qualifies": False,
    "maps_to_focus": None, "born": born("2013-05-10"),
}
BROTHER = {
    "name": "Anthon James Taylor", "slug": "anthon-james-taylor",
    "aliases": ["AJ", "AJ Taylor", "A.J. (brother)", "James"],
    "relationship": "sibling", "source": "landmark:family", "qualifies": False,
    "maps_to_focus": None, "born": born("1990-03-20"),
}
ALIAS_ROW = {
    "name": "James", "slug": "james", "aliases": [],
    "relationship": "sibling", "source": "landmark:family", "qualifies": False,
    "maps_to_focus": "anthon-james-taylor", "born": born("1990-03-20"),
}

FATHER_REF = "person/james-taylor"
GRANDFATHER_REF = "person/james-edwin-taylor-sr"
SON_REF = "person/james-everett-taylor"
BROTHER_REF = "person/anthon-james-taylor"
ALIAS_REF = "person/james"

MISSION_SOURCE = "classification:answers-m1#f8420cca539a"
BEDRIDDEN_SOURCE = "classification:answers-m1#8a20e7d27020"
DUCKS_SOURCE = "classification:answers-a14bc#aa48ea1051ff"


def roster(*rows) -> dict:
    return {"version": 1, "type": "person", "entities": [dict(row) for row in rows]}


def the_roster() -> dict:
    return roster(ALIAS_ROW, BROTHER, SON, GRANDFATHER, FATHER)


def resolve(mention: str, snapshot: object = None) -> ir.ResolutionRecord:
    return ir.resolve_mention(
        mention, roster=the_roster() if snapshot is None else snapshot,
        evidence_ref="classification:answers-m1#f8420cca539a", now=NOW,
    )


def refs_of(record: ir.ResolutionRecord) -> list[str]:
    return [candidate["ref"] for candidate in record.candidates]


def mission_age() -> dict:
    """The owner's "19-21 years old", aimed at the mission's node by v352's
    answer placement — its subject is the NODE's, which is the raw mention."""
    return claim(claim_type="age", subject_mention="James Edwin Taylor",
                 event_kind="moment", source=MISSION_SOURCE, temporal_value="19-21",
                 event_mention="Father's mission to New Zealand",
                 quote="19-21 years old")


def ducks_age() -> dict:
    """`claim:c5cc2a457176bcf12ccbc94e` — a bare *James*, age two, which the
    identity card is still asking about."""
    return claim(claim_type="age", subject_mention="James", event_kind="moment",
                 source=DUCKS_SOURCE, temporal_value="2",
                 event_mention="James's duck-chasing rowboat antics",
                 quote="James, at two, chasing ducks from the rowboat")


def derive(claims, snapshot=None):
    return tt.derive_calculated_timeline(
        index_of(claims), roster_snapshot=the_roster() if snapshot is None else snapshot,
        now=NOW,
    )


def node_labelled(result, label: str) -> dict:
    rows = [node for node in result.nodes if node.get("label") == label]
    assert len(rows) == 1, f"{label!r} names {len(rows)} nodes"
    return rows[0]


def age_findings(result) -> list[str]:
    return [row.get("claim_id") for row in result.diagnostics.get("findings") or ()
            if row.get("finding") == "age_without_birth_anchor"]


# --------------------------------------------------------------------------
# Rule 1 — a full name outranks a shared first name
# --------------------------------------------------------------------------


class AFullNameBindsItsPersonTests(unittest.TestCase):

    def test_his_fathers_full_name_is_his_father(self):
        record = resolve("James Edwin Taylor")
        self.assertEqual(record.resolution, "same")
        self.assertEqual(record.resolved_ref, FATHER_REF)
        self.assertEqual(record.reason, ir.FULL_NAME_REASON)

    def test_without_the_rung_the_full_name_binds_nobody(self):
        """The defect, reproduced: the rule removed, the mention is
        `no_candidate` on a roster where its person is sitting right there."""
        original = ir.full_name_candidates
        ir.full_name_candidates = lambda *args, **kwargs: ()
        try:
            record = resolve("James Edwin Taylor")
        finally:
            ir.full_name_candidates = original
        self.assertEqual(record.resolution, "uncertain")
        self.assertEqual(record.reason, "no_candidate")

    def test_a_relationship_word_beside_the_full_name_agrees_or_vetoes(self):
        self.assertEqual(resolve("my dad James Edwin Taylor").resolved_ref, FATHER_REF)
        vetoed = resolve("my son James Edwin Taylor")
        self.assertEqual(vetoed.resolution, "uncertain")
        self.assertNotIn(FATHER_REF, refs_of(vetoed))

    def test_the_roster_spelling_is_inside_the_mention_never_the_reverse(self):
        """"James Taylor" carries only part of "James Everett Taylor": without
        the father's own row it binds nobody rather than reaching into the
        son's longer name."""
        record = resolve("James Taylor", roster(SON, GRANDFATHER, BROTHER))
        self.assertEqual(record.resolution, "uncertain")
        self.assertEqual(record.candidates, ())

    def test_the_given_name_and_the_surname_are_both_anchored(self):
        self.assertEqual(resolve("Edwin Taylor").candidates, ())
        self.assertEqual(resolve("James Edwin").candidates, ())
        self.assertEqual(resolve("Everett Taylor").candidates, ())

    def test_two_people_carrying_the_same_full_spelling_are_a_standoff(self):
        cousin = dict(FATHER, slug="james-taylor-2", aliases=[], relationship="cousin",
                      name="James Taylor")
        record = resolve("James Edwin Taylor", roster(FATHER, cousin))
        self.assertEqual(record.resolution, "uncertain")
        self.assertEqual(sorted(refs_of(record)), [FATHER_REF, "person/james-taylor-2"])

    def test_the_census_of_names_the_rule_reads_is_the_rosters_own(self):
        index = ir.roster_index(the_roster())
        self.assertIn((("james", "taylor"), 0), index.full_names[FATHER_REF])
        self.assertIn((("james", "edwin", "taylor"), 1), index.full_names[GRANDFATHER_REF])
        # "James" and "AJ" are no full names at all; "AJ Taylor" is one.
        self.assertEqual(index.full_names[BROTHER_REF],
                         ((("anthon", "james", "taylor"), 0), (("aj", "taylor"), 0)))

    def test_full_name_is_a_named_deterministic_reason(self):
        self.assertIn(ir.FULL_NAME_REASON, ir.DETERMINISTIC_REASONS)
        self.assertIn(ir.FULL_NAME_REASON, ir.RESOLUTION_REASONS)
        self.assertNotIn(ir.FULL_NAME_REASON, ir.UNCERTAIN_REASONS)
        for name in ("A_FULL_NAME_OUTRANKS_A_SHARED_FIRST_NAME",
                     "A_GENERATIONAL_SUFFIX_IS_ONE_GENERATION",
                     "AN_ALIAS_ROW_IS_NEVER_A_CANDIDATE"):
            with self.subTest(name):
                self.assertGreater(len(getattr(ir, name)), 80)
                self.assertIn(name, ir.__all__)


# --------------------------------------------------------------------------
# Rule 2 — a generational suffix is one generation, not a tie
# --------------------------------------------------------------------------


class AGenerationalSuffixIsOneGenerationTests(unittest.TestCase):

    def test_every_spelling_of_senior_is_the_grandfather(self):
        for mention in ("James Edwin Taylor Sr.", "James Edwin Taylor Sr",
                        "James Edwin Taylor Snr", "James Edwin Taylor Senior",
                        "James Edwin Taylor I"):
            with self.subTest(mention):
                self.assertEqual(resolve(mention).resolved_ref, GRANDFATHER_REF)

    def test_the_unsuffixed_mention_is_never_the_suffixed_person(self):
        """Take the father's row away and "James Edwin Taylor" must NOT fall
        to his father: a suffix is part of the name, not decoration."""
        record = resolve("James Edwin Taylor", roster(GRANDFATHER, SON, BROTHER))
        self.assertEqual(record.resolution, "uncertain")
        self.assertNotIn(GRANDFATHER_REF, refs_of(record))

    def test_the_junior_direction_is_a_different_person_too(self):
        for mention in ("James Edwin Taylor Jr.", "James Edwin Taylor II",
                        "James Edwin Taylor III", "James Taylor Jnr"):
            with self.subTest(mention):
                record = resolve(mention)
                self.assertNotEqual(record.resolution, "same")
                self.assertNotIn(FATHER_REF, refs_of(record))
                self.assertNotIn(GRANDFATHER_REF, refs_of(record))

    def test_one_suffix_table_for_the_introducer_and_the_resolver(self):
        """v347's table, moved rather than copied: the same OBJECT."""
        self.assertIs(rr.GENERATIONAL_SUFFIX_STEPS, ir.GENERATIONAL_SUFFIX_STEPS)
        self.assertIs(rr.generational_suffix, ir.generational_suffix)
        for word in ("sr", "snr", "senior", "i", "jr", "jnr", "junior", "ii", "iii"):
            with self.subTest(word):
                self.assertIn(word, ir.GENERATIONAL_SUFFIX_STEPS)
        self.assertEqual(ir.generational_suffix("James Edwin Taylor Sr."),
                         ("James Edwin Taylor", 1))
        self.assertEqual(ir.generation_of_tokens(("james", "taylor", "iii")),
                         (("james", "taylor"), -2))

    def test_no_module_writes_a_second_suffix_table(self):
        """The recurring-defect guard: a dict literal mapping ``sr`` to a step
        anywhere in `system/` other than the one definition fails the build."""
        offenders = []
        for path in sorted((ROOT / "system").glob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if not isinstance(node, ast.Dict):
                    continue
                keys = {key.value for key in node.keys
                        if isinstance(key, ast.Constant) and isinstance(key.value, str)}
                if {"sr", "jr"} <= keys:
                    offenders.append(f"{path.name}:{node.lineno}")
        self.assertEqual(offenders, [f"identity_resolution.py:{self._table_line()}"])

    @staticmethod
    def _table_line() -> int:
        source = (ROOT / "system" / "identity_resolution.py").read_text(encoding="utf-8")
        for number, line in enumerate(source.splitlines(), start=1):
            if line.startswith("GENERATIONAL_SUFFIX_STEPS = {"):
                return number
        raise AssertionError("the one suffix table is missing")


# --------------------------------------------------------------------------
# Rule 3 — an alias row is never a candidate anywhere
# --------------------------------------------------------------------------


class AnAliasRowIsNeverACandidateTests(unittest.TestCase):

    def test_the_predicate(self):
        self.assertTrue(ir.is_alias_row(ALIAS_ROW))
        for row in (FATHER, GRANDFATHER, SON, BROTHER, {"name": "x", "maps_to_focus": ""}):
            with self.subTest(row["name"]):
                self.assertFalse(ir.is_alias_row(row))

    def test_the_card_path_never_offers_it(self):
        record = resolve("James")
        self.assertNotIn(ALIAS_REF, refs_of(record))
        self.assertFalse(ir.roster_index(the_roster()).has_ref(ALIAS_REF))

    def test_the_binding_path_never_reads_it_as_a_person(self):
        slugs = [row["slug"] for row in axm.roster_person_rows(the_roster())]
        self.assertNotIn("james", slugs)
        self.assertEqual(len(slugs), 4)
        # All three roster shapes a seat may pass.
        self.assertEqual(len(axm.roster_person_rows([the_roster()])), 4)
        self.assertEqual(len(axm.roster_person_rows(the_roster()["entities"])), 4)
        key_index, _ = tt._person_key_index(the_roster())
        self.assertNotIn(ALIAS_REF, key_index)
        self.assertNotIn(ALIAS_REF, axm.family_tier_index(the_roster()))

    def test_a_pointer_row_holds_no_birthday_of_its_own(self):
        births = tt._births_by_subject({}, roster_snapshot=the_roster(),
                                       landmark_entries=(), owner="self")
        self.assertNotIn(ALIAS_REF, births)
        self.assertEqual(births[FATHER_REF].earliest, "1954-06-04")


# --------------------------------------------------------------------------
# Rule 4 — v335's protection, beside the positive case
# --------------------------------------------------------------------------


#: What his own tellings say about the four Jameses, verbatim in shape: he
#: calls his father Dad, his grandfather Grandpa and his brother AJ.
HIS_TELLINGS = ("My dad drove us to the lake.", "Grandpa taught me to fish.",
                "AJ and I built the ramps.", "my son James loves baseball")


def with_his_words(snapshot: dict) -> dict:
    return rr.with_called_by(snapshot, HIS_TELLINGS)


class ABareFirstNameStillBindsNobodyTests(unittest.TestCase):
    """v335's census, as amended by the owner's ruling of 2026-09-25 — *"when
    I'm talking about James, I'm talking about my son"*. The asks pinned here
    are the rosters whose census of what he calls people was never read."""

    def test_bare_james_is_his_son_by_what_he_calls_the_others(self):
        """The ruling itself: "I call my dad Dad and his dad Grandpa", and his
        brother goes by AJ — so of the four who answer to James, only the son
        is somebody he calls James."""
        record = resolve("James", with_his_words(the_roster()))
        self.assertEqual(record.resolution, "same")
        self.assertEqual(record.resolved_ref, SON_REF)
        self.assertEqual(record.reason, ir.WHAT_HE_CALLS_THEM_REASON)

    def test_the_census_is_read_from_his_words_not_the_roster_alone(self):
        census = rr.called_by_census(the_roster(), HIS_TELLINGS)
        self.assertEqual(census[FATHER_REF], ("dad", "my dad"))
        self.assertEqual(census[GRANDFATHER_REF], ("grandpa",))
        self.assertEqual(census[BROTHER_REF], ("AJ",))
        self.assertEqual(census[SON_REF], ())
        # Words he never used decide nothing: the rule stands aside.
        silent = resolve("James", rr.with_called_by(the_roster(), ("James went fishing.",)))
        self.assertEqual(silent.reason, ir.SHARED_NAME_TOKEN_REASON)

    def test_two_people_he_genuinely_calls_james_still_ask(self):
        """"A bare name still asks only when two people he genuinely calls by
        that name both fit": call the brother nothing else, and the question is
        between the brother and the son — never the father or grandfather."""
        record = resolve("James", rr.with_called_by(
            the_roster(), ("My dad drove us.", "Grandpa taught me.")))
        self.assertEqual(record.resolution, "uncertain")
        self.assertEqual(record.reason, ir.SHARED_NAME_TOKEN_REASON)
        self.assertEqual(sorted(refs_of(record)), sorted([BROTHER_REF, SON_REF]))

    def test_bare_james_asks_about_the_four_real_people_and_never_the_pointer(self):
        # A roster with no census read: v335's ask, unchanged.
        record = resolve("James")
        self.assertEqual(record.resolution, "uncertain")
        self.assertEqual(record.reason, ir.SHARED_NAME_TOKEN_REASON)
        self.assertEqual(sorted(refs_of(record)),
                         sorted([BROTHER_REF, SON_REF, GRANDFATHER_REF, FATHER_REF]))

    def test_with_his_son_and_brother_plausible_it_asks_between_those_two(self):
        """v343's card, on the rows that make the question genuinely two-way:
        the son, the brother who answers to "James", and the pointer row that
        must not make it three."""
        record = resolve("James", roster(ALIAS_ROW, BROTHER, SON))
        self.assertEqual(record.resolution, "uncertain")
        self.assertEqual(record.reason, ir.SHARED_NAME_TOKEN_REASON)
        self.assertEqual(refs_of(record), [BROTHER_REF, SON_REF])
        card = ir.identity_work_item(record, claim_refs=["claim:x"], now=NOW)
        self.assertEqual(card["prompt_intent"],
                         "Which Anthon James Taylor or James Everett Taylor is 'James' here?")

    def test_a_bare_james_does_not_borrow_the_brothers_birthday(self):
        """Once the pointer row stopped standing beside him, the brother alone
        held the key "james" — and a story the card is still asking about took
        his 1990 birth. The census is what keeps that key ambiguous — on a
        vault whose tellings call none of the Jameses anything else."""
        _, ambiguous = tt._person_key_index(the_roster())
        self.assertIn("james", ambiguous)
        result = derive([ducks_age()])
        node = node_labelled(result, "James's duck-chasing rowboat antics")
        self.assertIsNone(node.get("best_temporal_value"))
        self.assertIn(ducks_age()["claim_id"], age_findings(result))

    def test_with_his_words_the_ducks_are_his_sons_at_two(self):
        """The owner's ruling in the fold: his tellings call the father Dad,
        the grandfather Grandpa and the brother AJ, so the bare "James" of the
        rowboat is his son — measured from the son's 2013-05-10, never the
        brother's 1990 birth."""
        words = [claim(claim_type="occurrence", subject_mention="self", event_kind="moment",
                       source=f"classification:answers-z{n}#{n:012x}", event_mention=f"telling {n}",
                       quote=text)
                 for n, text in enumerate(HIS_TELLINGS[:3], start=1)]
        key_index, ambiguous = tt._person_key_index(with_his_words(the_roster()))
        self.assertNotIn("james", ambiguous)
        self.assertIn("james", key_index)
        self.assertIn(SON_REF, key_index["james"])
        result = derive([ducks_age(), *words])
        node = node_labelled(result, "James's duck-chasing rowboat antics")
        self.assertEqual(node["subject_refs"], [SON_REF])
        best = node["best_temporal_value"]
        self.assertEqual((best["earliest"], best["latest"], best["basis"]),
                         ("2015-05", "2016-05", "age"))

    def test_a_name_only_one_person_answers_to_still_anchors(self):
        _, ambiguous = tt._person_key_index(the_roster())
        for key in ("aj", "aj taylor", "james taylor", FATHER_REF):
            with self.subTest(key):
                self.assertNotIn(key, ambiguous)


# --------------------------------------------------------------------------
# The fold, on the owner's own shapes
# --------------------------------------------------------------------------


class TheMissionIsMeasuredFromHisFathersBirthTests(unittest.TestCase):

    def setUp(self):
        self.result = derive([mission_age()])
        self.node = node_labelled(self.result, "Father's mission to New Zealand")

    def test_the_subject_is_his_father(self):
        self.assertEqual(self.node["subject_refs"], [FATHER_REF])

    def test_the_age_band_is_measured_from_1954_06_04(self):
        best = self.node["best_temporal_value"]
        self.assertEqual((best["earliest"], best["latest"], best["basis"]),
                         # timeline-rules:19: at the grain he said it — the month.
                         ("1973-06", "1976-06", "age"))
        self.assertEqual(age_findings(self.result), [])

    def test_before_this_release_the_same_claim_had_no_anchor(self):
        original = ir.full_name_candidates
        ir.full_name_candidates = lambda *args, **kwargs: ()
        try:
            result = derive([mission_age()])
        finally:
            ir.full_name_candidates = original
        node = node_labelled(result, "Father's mission to New Zealand")
        self.assertEqual(node["subject_refs"], ["James Edwin Taylor"])
        self.assertIn(mission_age()["claim_id"], age_findings(result))

    def test_it_is_before_the_owners_birth_so_it_is_family_history(self):
        """v344's rule 4 outranks the immediate-family tier: a moment wholly
        before the owner was born is ``pre_birth`` whoever it is about."""
        owner = claim(claim_type="date", subject_mention="birth", event_kind="birth",
                      source="landmark:entry-birth", temporal_value=value("1981-07-11"),
                      quote="I was born on 11 July 1981.")
        node = node_labelled(derive([owner, mission_age()]),
                             "Father's mission to New Zealand")
        self.assertEqual((node["axis_membership"], node["axis_membership_reason"]),
                         ("none", "pre_birth"))
        without_owner = self.node
        self.assertEqual((without_owner["axis_membership"],
                          without_owner["axis_membership_reason"]),
                         ("family", "immediate_family_in_lifetime"))


class TheRuleVersionMovesTests(unittest.TestCase):

    def test_calculation_rule_version(self):
        self.assertEqual(tt.CALCULATION_RULE_VERSION, "timeline-rules:25")


if __name__ == "__main__":
    unittest.main()
