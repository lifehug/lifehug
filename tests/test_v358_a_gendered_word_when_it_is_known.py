"""v358 — a gendered word when it is known, the neutral word when it is not.

THE OWNER'S RULING (2026-09-25):

    "we can use both child and son, I in life have four children all who are
    my child or children and I have 2 sons and 2 daughters so both"

    "son is more detailed than child and gives more information, so if you
    have to pick one i'd pick the gendered one daughter and son"

and its scope, the same day: every relation whose word has a gendered pair,
and a card ONLY for those — never a friend, a colleague, a bishop, a
neighbour.

The fixtures are the SHAPES of the owner's roster (a `landmark:family` row per
relative, a `maps_to_focus` alias row, collective and role rows, his own row)
and the words of his own tellings (the v347 grandfather quote, his "my mom",
"my dad", "my wife", "A.J. (brother)"), on a synthetic vault built from
scratch. Nothing here reads a real vault.
"""

from __future__ import annotations

import copy
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "system"))
sys.path.insert(0, str(ROOT / "tests"))

import answer_placement as ap  # noqa: E402
import entity_roster  # noqa: E402
import event_identity as ei  # noqa: E402
import landmark_recorder as lr  # noqa: E402
import question_planner as qp  # noqa: E402
import relation_words as rw  # noqa: E402
import temporal_projection as tp  # noqa: E402
import temporal_publication as pub  # noqa: E402
import temporal_store as ts  # noqa: E402
import temporal_timeline as tt  # noqa: E402
import temporal_work_items as twi  # noqa: E402
import timeline_interaction as ti  # noqa: E402
from tempdirs import root_parent_tmp  # noqa: E402
from test_v340_apply_keeps_placements import NOW, claim, write_vault  # noqa: E402

OWNER_NAMES = ("Dave", "David James Taylor")


def row(name, slug, relationship=None, *, aliases=(), maps_to=None, **extra):
    """A roster row in the shape `entity_verdict.apply_verdict(ensure=True)` files."""
    out = {"name": name, "slug": slug, "aliases": list(aliases), "qualifies": False,
           "maps_to_focus": maps_to, "score": 0.0, "unique_answers": 0,
           "page_eligible": False}
    if relationship is not None:
        out["relationship"] = relationship
        out["source"] = "landmark:family"
    out.update(extra)
    return out


def owners_roster() -> dict:
    """The owner's roster, by shape: seven relatives, an alias row, a
    collective row, a role row, a friend and the owner himself."""
    return {"version": 1, "type": "person", "entities": [
        row("Dave", "dave", aliases=["David Taylor", "David James Taylor"]),
        row("Kids", "kids", "child", aliases=["the kids", "Dave's kids"]),
        row("Son", "son", "child"),
        row("Friend", "friend", "friend"),
        row("James", "james", "sibling", maps_to="anthon-james-taylor"),
        row("Harvey", "harvey", "child"),
        row("James Everett Taylor", "james-everett-taylor", "child"),
        row("Anthon James Taylor", "anthon-james-taylor", "sibling",
            aliases=["AJ", "AJ Taylor", "A.J. (brother)", "James"]),
        row("Desiree Taylor", "desiree-taylor", "parent",
            aliases=["Desiree Taylor (Desi)", "Desi", "mom", "my mom", "mother",
                     "my mother"]),
        row("James Taylor", "james-taylor", "parent",
            aliases=["James Taylor (Dad)", "dad", "my dad", "father", "my father"]),
        row("James Edwin Taylor Sr.", "james-edwin-taylor-sr", "grandparent"),
        row("Katie Taylor", "katie-taylor", "spouse"),
        row("Brother Jensen", "brother-jensen", "other"),
    ]}


GRANDFATHER_QUOTE = ("story: my grandpa James Edwin Taylor Sr., my dad's dad, "
                     "died of a heart attack")


def owners_claims() -> list[dict]:
    """His own tellings: the v347 grandfather quote, and his wife by name."""
    return [
        claim(source="classification:answers-c9#aaaaaaaaaaaa", claim_type="occurrence",
              subject_mention="James Edwin Taylor Sr.", event_kind="death",
              event_mention="Grandpa's heart attack", quote=GRANDFATHER_QUOTE),
        claim(source="classification:sources-manual-birthdays#bbbbbbbbbbbb",
              claim_type="occurrence", subject_mention="Katie Taylor",
              event_kind="moment", event_mention="Katie's birthday dinner",
              quote="Katie Taylor, my wife, turned 39 and we went out"),
        claim(source="classification:answers-c20#cccccccccccc", claim_type="occurrence",
              subject_mention="James", event_kind="moment",
              event_mention="Baseball tryouts",
              quote="my son James made the team this spring"),
    ]


def rows_by_ref(roster=None, claims=None, **kwargs) -> dict[str, dict]:
    rows = rw.relation_word_rows(
        roster if roster is not None else owners_roster(),
        claims=claims if claims is not None else owners_claims(),
        owner_names=OWNER_NAMES, **kwargs)
    return {r["subject_ref"]: r for r in rows}


def cards_by_ref(roster=None, claims=None) -> dict[str, dict]:
    rows = rw.relation_word_rows(
        roster if roster is not None else owners_roster(),
        claims=claims if claims is not None else owners_claims(),
        owner_names=OWNER_NAMES)
    return {c["subject_ref"]: c for c in rw.relation_word_cards(rows, now=NOW)}


# --------------------------------------------------------------------------
# 1. The vocabulary is derived, never re-typed
# --------------------------------------------------------------------------


class TheVocabularyIsDerivedTests(unittest.TestCase):
    """The pairs come out of `RELATIONSHIP_MENTION_WORDS`, never a second list."""

    def test_every_gendered_pair_comes_out_of_the_one_vocabulary(self):
        self.assertEqual(rw.gendered_pair("child"), ("son", "daughter"))
        self.assertEqual(rw.gendered_pair("parent"), ("father", "mother"))
        self.assertEqual(rw.gendered_pair("sibling"), ("brother", "sister"))
        self.assertEqual(rw.gendered_pair("spouse"), ("husband", "wife"))
        self.assertEqual(rw.gendered_pair("grandparent"), ("grandfather", "grandmother"))

    def test_a_relation_with_no_gendered_form_has_no_pair(self):
        for relationship in ("friend", "colleague", "mentor", "other", "partner", "",
                             "bishop", "neighbor"):
            with self.subTest(relationship=relationship):
                self.assertIsNone(rw.gendered_pair(relationship))

    def test_the_one_declaration_is_exactly_the_derived_words(self):
        """WORD_GENDER declares only which canonical word is which form, and
        names exactly the words the vocabulary derives — no second list."""
        derived = {word for rel in rw.gendered_relationships()
                   for word in rw.gendered_pair(rel)}
        self.assertEqual(set(rw.WORD_GENDER), derived)
        self.assertEqual(rw.gendered_relationships(),
                         ("parent", "grandparent", "child", "sibling", "spouse"))

    def test_the_spoken_words_name_their_canonical_form(self):
        cases = {"dad": "father", "Mom": "mother", "grandpa": "grandfather",
                 "grandma": "grandmother", "wife": "wife", "brother": "brother",
                 "kid": "", "child": "", "uncle": "", "parent": ""}
        for word, canonical in cases.items():
            with self.subTest(word=word):
                self.assertEqual(rw.canonical_gendered_word(word), canonical)


# --------------------------------------------------------------------------
# 2. Rendering — both words, gendered preferred
# --------------------------------------------------------------------------


class BothWordsGenderedPreferredTests(unittest.TestCase):
    """The gendered word when known, the neutral word when not, the plural always neutral."""

    def test_a_known_gendered_word_is_son(self):
        self.assertEqual(rw.relation_label("child", rw.MALE), "Son")
        self.assertEqual(rw.relation_label("child", rw.FEMALE), "Daughter")
        self.assertEqual(rw.relation_label("parent", rw.FEMALE), "Mother")
        self.assertEqual(rw.relation_label("spouse", rw.MALE), "Husband")

    def test_an_unknown_word_is_child(self):
        self.assertEqual(rw.relation_label("child"), "Child")
        self.assertEqual(rw.relation_label("child", None), "Child")
        self.assertEqual(rw.relation_label("child", rw.NEUTRAL), "Child")

    def test_the_plural_is_always_children(self):
        """All four are his children AND two are sons: a group is his children."""
        for gender in (None, rw.MALE, rw.FEMALE, rw.NEUTRAL):
            with self.subTest(gender=gender):
                self.assertEqual(rw.relation_word("child", gender, plural=True), "children")
        self.assertEqual(rw.relation_word("parent", rw.MALE, plural=True), "parents")

    def test_a_relation_with_no_pair_keeps_its_own_word(self):
        self.assertEqual(rw.relation_label("friend", rw.MALE), "Friend")

    def test_the_collective_row_is_spoken_of_in_the_neutral_plural(self):
        rows = rows_by_ref()
        self.assertEqual(rows["person/kids"]["label"], "Children")
        self.assertTrue(rows["person/kids"]["collective"])
        self.assertEqual(rows["person/harvey"]["plural_label"], "Children")


# --------------------------------------------------------------------------
# 3. The field comes only from his own words
# --------------------------------------------------------------------------


class HisOwnWordsFillTheFieldTests(unittest.TestCase):
    """The field comes only from his own words, and never from a first name."""

    def setUp(self):
        self.rows = rows_by_ref()

    def test_his_own_gendered_spellings_decide_without_a_card(self):
        expected = {
            "person/desiree-taylor": (rw.FEMALE, "Mother"),
            "person/james-taylor": (rw.MALE, "Father"),
            "person/anthon-james-taylor": (rw.MALE, "Brother"),
            "person/katie-taylor": (rw.FEMALE, "Wife"),
            "person/james-edwin-taylor-sr": (rw.MALE, "Grandfather"),
        }
        for ref, (gender, label) in expected.items():
            with self.subTest(ref=ref):
                self.assertEqual(self.rows[ref][rw.RELATION_GENDER_FIELD], gender)
                self.assertEqual(self.rows[ref][rw.RELATION_GENDER_BASIS_FIELD],
                                 rw.BASIS_STATED)
                self.assertEqual(self.rows[ref]["label"], label)
                self.assertFalse(self.rows[ref]["askable"])

    def test_nothing_said_about_his_children_leaves_them_child(self):
        for ref in ("person/harvey", "person/james-everett-taylor"):
            with self.subTest(ref=ref):
                self.assertIsNone(self.rows[ref][rw.RELATION_GENDER_FIELD])
                self.assertEqual(self.rows[ref]["label"], "Child")
                self.assertTrue(self.rows[ref]["askable"])

    def test_my_dads_dad_does_not_make_the_grandfather_a_father(self):
        """v347's quote. The word possessing the next noun is not his relation."""
        entity = row("James Edwin Taylor Sr.", "james-edwin-taylor-sr", "grandparent")
        possessor_only = [claim(
            source="classification:answers-c9#dddddddddddd", claim_type="occurrence",
            subject_mention="James Edwin Taylor Sr.", event_kind="death",
            event_mention="A heart attack",
            quote="James Edwin Taylor Sr., my dad's dad, died of a heart attack")]
        texts = rw.texts_by_source(possessor_only)
        self.assertEqual(rw.stated_words(entity, texts_by_source=texts,
                                         owner_names=OWNER_NAMES), ())
        rows = rows_by_ref({"entities": [entity]}, possessor_only)
        self.assertEqual(rows["person/james-edwin-taylor-sr"]["label"], "Grandparent")
        self.assertNotIn("father", json.dumps(rows).casefold().replace("grandfather", ""))
        # and with his own "my grandpa" in the same clause, the word is his:
        texts = rw.texts_by_source(owners_claims())
        words = rw.stated_words(entity, texts_by_source=texts, owner_names=OWNER_NAMES)
        self.assertEqual({w["word"] for w in words}, {"grandpa"})

    def test_mother_in_law_does_not_set_mother(self):
        """A compound is never the word inside it — even on a row wrongly
        filed ``parent``, and even through a roster spelling."""
        entity = row("Ruth Allen", "ruth-allen", "parent",
                     aliases=["my mother-in-law", "mother-in-law"])
        in_law = [claim(source="classification:answers-k2#eeeeeeeeeeee",
                        claim_type="occurrence", subject_mention="Ruth Allen",
                        event_kind="moment", event_mention="Reception in the backyard",
                        quote="the reception was at my mother-in-law Ruth Allen's house")]
        in_law_appositive = [claim(source="classification:answers-k3#ffffffffffff",
                                   claim_type="occurrence", subject_mention="Ruth Allen",
                                   event_kind="moment", event_mention="Sunday dinner",
                                   quote="Ruth Allen, my mother-in-law, made dinner")]
        for claims in (in_law, in_law_appositive):
            with self.subTest(quote=claims[0]["evidence"][0]["quote"]):
                texts = rw.texts_by_source(claims)
                self.assertEqual(rw.stated_words(entity, texts_by_source=texts,
                                                 owner_names=OWNER_NAMES), ())
                rows = rows_by_ref({"entities": [entity]}, claims)
                self.assertEqual(rows["person/ruth-allen"]["label"], "Parent")
        self.assertEqual(rw.bare_relation_word("my mother-in-law"), "")
        self.assertEqual(rw.bare_relation_word("step-mother"), "")
        self.assertEqual(rw.bare_relation_word("my mom"), "mom")

    def test_a_word_about_a_shared_first_name_decides_nobody(self):
        """"my son James" names one of four Jameses; the brother whose alias
        is "James" is not made a son, nor anything else, by it."""
        words = rw.stated_words(
            owners_roster()["entities"][7],
            texts_by_source=rw.texts_by_source(owners_claims()),
            owner_names=OWNER_NAMES,
            shared_keys=rw._shared_spelling_keys(owners_roster()))  # noqa: SLF001
        self.assertTrue(words)
        self.assertEqual({w["word"] for w in words}, {"brother"})
        self.assertEqual(self.rows["person/anthon-james-taylor"]["label"], "Brother")

    def test_a_first_name_is_never_a_gender(self):
        """Charlee, Dottie: a name that "sounds" like anything decides nothing."""
        roster = {"entities": [row("Charlee Joy Taylor", "charlee-joy-taylor", "child"),
                               row("Dottie Ovelle Taylor", "dottie-ovelle-taylor", "child")]}
        rows = rows_by_ref(roster, [])
        for ref in ("person/charlee-joy-taylor", "person/dottie-ovelle-taylor"):
            with self.subTest(ref=ref):
                self.assertIsNone(rows[ref][rw.RELATION_GENDER_FIELD])
                self.assertTrue(rows[ref]["askable"])

    def test_two_words_that_disagree_decide_nothing(self):
        claims = [
            claim(source="classification:answers-a1#aaaaaaaaaaab", claim_type="occurrence",
                  subject_mention="Harvey", event_kind="moment",
                  event_mention="First steps", quote="my son Harvey took his first steps"),
            claim(source="classification:answers-a2#aaaaaaaaaaac", claim_type="occurrence",
                  subject_mention="Harvey", event_kind="moment",
                  event_mention="Recital", quote="my daughter Harvey sang"),
        ]
        rows = rows_by_ref({"entities": [row("Harvey", "harvey", "child")]}, claims)
        self.assertIsNone(rows["person/harvey"][rw.RELATION_GENDER_FIELD])
        one = rows_by_ref({"entities": [row("Harvey", "harvey", "child")]}, claims[:1])
        self.assertEqual(one["person/harvey"]["label"], "Son")

    def test_a_word_of_another_relation_is_not_this_persons_word(self):
        """"my brother Harvey" about a row the vault holds as a CHILD decides
        nothing: the word must belong to the row's own relationship."""
        claims = [claim(source="classification:answers-a3#aaaaaaaaaaad",
                        claim_type="occurrence", subject_mention="Harvey",
                        event_kind="moment", event_mention="Camping",
                        quote="my brother Harvey came camping")]
        rows = rows_by_ref({"entities": [row("Harvey", "harvey", "child")]}, claims)
        self.assertIsNone(rows["person/harvey"][rw.RELATION_GENDER_FIELD])
        self.assertEqual(rows["person/harvey"]["label"], "Child")

    def test_a_spelling_two_people_share_anchors_nobody(self):
        """Two sons both called Sam: "my son Sam" says which word, but not whose."""
        roster = {"entities": [row("Sam Allen", "sam-allen", "child", aliases=["Sam"]),
                               row("Sam Baker", "sam-baker", "child", aliases=["Sam"])]}
        claims = [claim(source="classification:answers-a4#aaaaaaaaaaae",
                        claim_type="occurrence", subject_mention="Sam",
                        event_kind="moment", event_mention="Graduation",
                        quote="my son Sam graduated")]
        rows = rows_by_ref(roster, claims)
        for ref in ("person/sam-allen", "person/sam-baker"):
            with self.subTest(ref=ref):
                self.assertIsNone(rows[ref][rw.RELATION_GENDER_FIELD])

    def test_an_alias_rows_spelling_is_its_targets_own(self):
        """The `maps_to_focus` row "James" is AJ by curation, so "my brother
        James" is AJ's word and the spelling is not shared with a stranger."""
        roster = {"entities": [
            row("James", "james", "sibling", maps_to="anthon-james-taylor"),
            row("Anthon James Taylor", "anthon-james-taylor", "sibling",
                aliases=["James"])]}
        claims = [claim(source="classification:answers-a5#aaaaaaaaaaaf",
                        claim_type="occurrence", subject_mention="James",
                        event_kind="moment", event_mention="Mission farewell",
                        quote="my brother James left on his mission")]
        rows = rows_by_ref(roster, claims)
        self.assertEqual(rows["person/anthon-james-taylor"]["label"], "Brother")

    def test_a_family_landmark_record_with_a_gendered_relation_counts(self):
        entries = [{"domain": "family",
                    "record": {"who": "Harvey", "label": "Harvey", "relation": "son"}}]
        rows = rows_by_ref({"entities": [row("Harvey", "harvey", "child")]}, [],
                           landmark_entries=entries)
        self.assertEqual(rows["person/harvey"]["label"], "Son")

    def test_the_answered_field_outranks_his_tellings(self):
        roster = owners_roster()
        for entity in roster["entities"]:
            if entity["slug"] == "katie-taylor":
                entity[rw.RELATION_GENDER_FIELD] = rw.NEUTRAL
                entity[rw.RELATION_GENDER_BASIS_FIELD] = rw.BASIS_ANSWER
        rows = rows_by_ref(roster)
        self.assertEqual(rows["person/katie-taylor"]["label"], "Spouse")
        self.assertEqual(rows["person/katie-taylor"][rw.RELATION_GENDER_BASIS_FIELD],
                         rw.BASIS_ANSWER)


# --------------------------------------------------------------------------
# 4. The card — one per person, only where the word has a pair
# --------------------------------------------------------------------------


class OneCardWhereTheWordHasAPairTests(unittest.TestCase):
    """At most one card per person, only where the word has a gendered pair."""

    def setUp(self):
        self.cards = cards_by_ref()

    def test_exactly_his_two_undecided_children_are_asked(self):
        self.assertEqual(sorted(self.cards),
                         ["person/harvey", "person/james-everett-taylor"])

    def test_the_card_as_built(self):
        card = self.cards["person/harvey"]
        self.assertEqual(card["kind"], rw.RELATION_WORD_KIND)
        self.assertEqual(card["prompt_intent"],
                         "Is Harvey your son or your daughter — or would you "
                         "rather keep “child”?")
        self.assertEqual(card["requested_field"], rw.RELATION_GENDER_FIELD)
        self.assertEqual(card["subject_ref"], "person/harvey")
        self.assertEqual(card["allowed_surfaces"], ["timeline"])
        self.assertNotIn("node_ref", card)
        self.assertNotIn("leverage", card)
        self.assertEqual([c["ref"] for c in card["candidates"]],
                         [rw.MALE, rw.FEMALE, rw.NEUTRAL])
        self.assertEqual([c["name"] for c in card["candidates"]],
                         ["son", "daughter", "just “child”"])
        self.assertEqual(card["work_item_id"], tp.derive_work_item_id(
            kind=rw.RELATION_WORD_KIND, subject_ref="person/harvey",
            requested_field=rw.RELATION_GENDER_FIELD))
        self.assertEqual(twi.REQUESTED_FIELD_RELATION_GENDER, rw.RELATION_GENDER_FIELD)
        self.assertEqual(twi.canonical_requested_field(rw.RELATION_GENDER_FIELD),
                         rw.RELATION_GENDER_FIELD)

    def test_a_friend_whose_word_is_unknown_gets_no_card(self):
        """The coordinator's scope rule, as a test: no gendered form, no card."""
        roster = {"entities": [row("Mike Eyre", "mike-eyre", "friend"),
                               row("Brother Jensen", "brother-jensen", "other"),
                               row("Sam Lee", "sam-lee", "colleague"),
                               row("Pat Moore", "pat-moore", "mentor"),
                               row("Jo Park", "jo-park", "partner")]}
        self.assertEqual(cards_by_ref(roster, []), {})
        rows = rows_by_ref(roster, [])
        self.assertEqual(rows["person/mike-eyre"]["label"], "Friend")
        self.assertFalse(any(r["askable"] for r in rows.values()))

    def test_an_alias_row_never_gets_a_card(self):
        self.assertNotIn("person/james", self.cards)
        self.assertNotIn("person/james", rows_by_ref())
        alias_only = {"entities": [row("James", "james", "child",
                                       maps_to="james-everett-taylor")]}
        self.assertEqual(cards_by_ref(alias_only, []), {})

    def test_a_collective_a_role_row_and_the_owner_get_no_card(self):
        for ref in ("person/kids", "person/son", "person/dave", "person/friend"):
            with self.subTest(ref=ref):
                self.assertNotIn(ref, self.cards)
        owner_as_child = {"entities": [row("Dave", "dave", "child")]}
        self.assertEqual(cards_by_ref(owner_as_child, []), {})

    def test_a_row_named_by_a_bare_role_word_gets_no_card(self):
        """"Kid", "Parent": a placeholder, not a named person (v343's law)."""
        roster = {"entities": [row("Kid", "kid", "child"),
                               row("Parent", "parent", "parent"),
                               row("Sibling", "sibling", "sibling")]}
        self.assertEqual(cards_by_ref(roster, []), {})

    def test_the_card_ranks_below_every_dating_card(self):
        """Priced from the fold's own defaults, below the cheapest date ask the
        fold can mint (a zero-reach missing anchor)."""
        mine = self.cards["person/harvey"]["combined_score"]
        for kind in tt.WORK_ITEM_VALUE_DEFAULTS:
            if kind == rw.RELATION_WORD_KIND:
                continue
            floor = tt._score_components(  # noqa: SLF001
                kind, system_value=0.0, event_kind=None, subject_ref="x",
                resolved=True)["combined_score"]
            with self.subTest(kind=kind):
                self.assertLess(mine, floor)

    def test_the_kind_is_registered_everywhere_a_kind_must_be(self):
        kind = rw.RELATION_WORD_KIND
        self.assertIn(kind, tp.WORK_ITEM_KINDS)
        self.assertIn(kind, ti.WORK_ITEM_KINDS)
        self.assertIn(kind, ti.WORK_ITEM_PROBES)
        self.assertIn(kind, qp.WORK_ITEM_PLACEMENT_GAIN)
        self.assertEqual(tt.SURFACES_BY_KIND[kind], ("timeline",))
        self.assertIn(kind, tt.WORK_ITEM_VALUE_DEFAULTS)
        import mirror_work  # noqa: PLC0415

        self.assertNotIn(kind, mirror_work.MIRROR_WORK_ITEM_KINDS)

    def test_the_play_probe_names_the_person_and_the_three_words(self):
        """v343's card-shape law: no raw id, no bare pronoun, a named person."""
        probe = ti.work_item_probe(self.cards["person/harvey"])
        self.assertEqual(probe["text"],
                         "When you talk about Harvey, which word is right — son "
                         "or daughter or just “child”?")
        self.assertNotIn("work:", probe["text"])


# --------------------------------------------------------------------------
# 5. The answer — through the card answer path, once
# --------------------------------------------------------------------------


class TheAnswerIsReadTests(unittest.TestCase):
    """What a reply to the card says, through the one vocabulary."""

    def test_the_gendered_word_answers(self):
        cases = {"Son": rw.MALE, "He's my son": rw.MALE, "daughter!": rw.FEMALE,
                 "my boy, my son": rw.MALE, "child": rw.NEUTRAL,
                 "just keep child": rw.NEUTRAL, "neutral please": rw.NEUTRAL,
                 "kid is fine": rw.NEUTRAL, "yes": "", "": "",
                 "sons and daughters": "", "my step-son": "",
                 "my son's wife": ""}
        for text, gender in cases.items():
            with self.subTest(text=text):
                self.assertEqual(rw.read_relation_answer(text, "child"), gender)

    def test_a_word_of_another_relation_is_not_this_answer(self):
        self.assertEqual(rw.read_relation_answer("my dad", "child"), "")
        self.assertEqual(rw.read_relation_answer("my mother-in-law", "parent"), "")
        self.assertEqual(rw.read_relation_answer("she's my wife", "spouse"), rw.FEMALE)
        self.assertEqual(rw.read_relation_answer("son", "friend"), "")


class VaultFixture:
    """A synthetic vault with the owner's roster shape, published for real."""

    def __init__(self, test: unittest.TestCase, roster=None, claims=None):
        self.root = root_parent_tmp(test, ROOT, prefix="lifehug-v358-")
        for folder in ("state/temporal_claims", "state/entity_rosters",
                       "sources/conversations"):
            (self.root / folder).mkdir(parents=True, exist_ok=True)
        self.write_roster(roster if roster is not None else owners_roster())
        write_vault(self.root, claims if claims is not None else owners_claims())
        (self.root / "profile.yaml").write_text("name: Dave\nfull_name: David James Taylor\n",
                                                encoding="utf-8")
        self.publish()

    def write_roster(self, roster: dict) -> None:
        (self.root / "state/entity_rosters/person.json").write_text(
            json.dumps(roster, indent=2) + "\n", encoding="utf-8")

    def roster(self) -> dict:
        return json.loads((self.root / "state/entity_rosters/person.json").read_text())

    def entity(self, slug: str) -> dict:
        return next(e for e in self.roster()["entities"] if e["slug"] == slug)

    def publish(self) -> None:
        ts.rebuild_active_index(self.root)
        ei.rebuild_telling_manifest(self.root)
        pub.publish(self.root, now=NOW)

    def cards(self) -> dict[str, dict]:
        payload = pub.read_work_items(self.root) or {}
        return {r["subject_ref"]: r for r in payload.get("work_items") or ()
                if r.get("kind") == rw.RELATION_WORD_KIND}

    def labels(self) -> dict[str, str]:
        payload = pub.read_projection(self.root) or {}
        return {r["subject_ref"]: r["label"] for r in payload.get("relation_words") or ()}

    def answer(self, ref: str, reply: str, *, turn: str = "0"):
        session = f"conversation:cand:work_item:{self.cards()[ref]['work_item_id']}"
        ts.promote_conversational_source(self.root, reply, {
            "session_ref": session, "turn_ref": turn, "speaker": "person",
            "occurred_at": NOW})
        return session


class ThePublishedProjectionTests(unittest.TestCase):
    """The words ride the published projection; the view serves them."""

    def setUp(self):
        self.vault = VaultFixture(self)

    def test_the_projection_carries_the_words_and_the_view_serves_them(self):
        labels = self.vault.labels()
        self.assertEqual(labels["person/harvey"], "Child")
        self.assertEqual(labels["person/desiree-taylor"], "Mother")
        self.assertEqual(labels["person/katie-taylor"], "Wife")
        view = pub.calculated_view(self.vault.root)
        self.assertEqual({r["subject_ref"] for r in view["relation_words"]}, set(labels))
        self.assertIn("relation_words", pub.view_block_keys())

    def test_both_files_carry_the_same_cards(self):
        projection = [r["work_item_id"] for r in pub.read_projection(self.vault.root)
                      ["work_items"] if r["kind"] == rw.RELATION_WORD_KIND]
        self.assertEqual(sorted(projection),
                         sorted(r["work_item_id"] for r in self.vault.cards().values()))
        self.assertEqual(len(projection), 2)

    def test_the_rebuild_oracle_reproduces_it(self):
        self.assertTrue(pub.verify(self.vault.root, now=NOW)["identical"])

    def test_a_vault_with_no_relationships_publishes_no_key(self):
        bare = VaultFixture(self, roster={"version": 1, "type": "person",
                                          "entities": [row("Friend", "friend")]})
        self.assertNotIn("relation_words", pub.read_projection(bare.root))
        self.assertEqual(bare.cards(), {})


class AnsweringTheCardTests(unittest.TestCase):
    """Answering files through the card answer path, once."""

    def setUp(self):
        self.vault = VaultFixture(self)

    def sweep(self):
        report = ap.place_answers(self.vault.root, now=NOW)
        self.vault.publish()
        return report

    def test_son_is_filed_and_the_card_leaves(self):
        self.vault.answer("person/harvey", "He's my son")
        report = self.sweep()
        self.assertEqual([r["relation_gender"] for r in report["relation_words"]],
                         [rw.MALE])
        self.assertEqual(report["placed"], 0)
        entity = self.vault.entity("harvey")
        self.assertEqual(entity[rw.RELATION_GENDER_FIELD], rw.MALE)
        self.assertEqual(entity[rw.RELATION_GENDER_BASIS_FIELD], rw.BASIS_ANSWER)
        self.assertEqual(self.vault.labels()["person/harvey"], "Son")
        self.assertNotIn("person/harvey", self.vault.cards())
        self.assertIn("person/james-everett-taylor", self.vault.cards())

    def test_an_answered_card_never_re_mints(self):
        session = self.vault.answer("person/harvey", "son")
        self.sweep()
        for _ in range(2):
            self.vault.publish()
            self.assertNotIn("person/harvey", self.vault.cards())
        # a later reply in the same conversation does not re-decide it
        ts.promote_conversational_source(self.vault.root, "actually daughter", {
            "session_ref": session, "turn_ref": "1", "speaker": "person",
            "occurred_at": NOW})
        self.sweep()
        self.assertEqual(self.vault.entity("harvey")[rw.RELATION_GENDER_FIELD], rw.MALE)

    def test_a_stale_card_never_re_decides_an_answer(self):
        """Even handed the generation that still published the card, a second
        reply does not overwrite the owner's first answer."""
        session = self.vault.answer("person/harvey", "son")
        stale = pub.read_work_items(self.vault.root)
        self.sweep()
        report = rw.file_relation_answer(self.vault.root, session_ref=session,
                                         text="actually daughter", work_items=stale)
        self.assertEqual(report["refused"], rw.REFUSED_ALREADY_KNOWN)
        self.assertEqual(self.vault.entity("harvey")[rw.RELATION_GENDER_FIELD], rw.MALE)

    def test_keeping_the_neutral_word_is_an_answer(self):
        self.vault.answer("person/james-everett-taylor", "just child")
        self.sweep()
        self.assertEqual(self.vault.entity("james-everett-taylor")[rw.RELATION_GENDER_FIELD],
                         rw.NEUTRAL)
        self.assertEqual(self.vault.labels()["person/james-everett-taylor"], "Child")
        self.assertNotIn("person/james-everett-taylor", self.vault.cards())

    def test_an_unreadable_reply_leaves_the_card_open(self):
        self.vault.answer("person/harvey", "yes")
        report = self.sweep()
        self.assertEqual(report["relation_words"][0]["refused"],
                         rw.REFUSED_ANSWER_UNREADABLE)
        self.assertNotIn(rw.RELATION_GENDER_FIELD, self.vault.entity("harvey"))
        self.assertIn("person/harvey", self.vault.cards())

    def test_the_live_filing_seat_writes_it_and_republishes(self):
        """`landmark_recorder.file_claims` with no drafts — the reply "Daughter"
        carries no time — still files the word and takes the card off."""
        card = self.vault.cards()["person/harvey"]
        session = f"conversation:cand:work_item:{card['work_item_id']}"
        lr.file_claims(self.vault.root, (), message_text="Daughter",
                       extractor_version="general_listener/schema:1", session_ref=session,
                       turn_ref="0", speaker="person", now=NOW)
        self.assertEqual(self.vault.entity("harvey")[rw.RELATION_GENDER_FIELD], rw.FEMALE)
        self.assertEqual(self.vault.labels()["person/harvey"], "Daughter")
        self.assertNotIn("person/harvey", self.vault.cards())

    def test_the_answer_survives_a_roster_refresh(self):
        """A settled identity field: an AI refresh that drops it cannot lose it."""
        self.vault.answer("person/harvey", "son")
        self.sweep()
        previous = self.vault.roster()
        raw = [{"name": "Harvey", "aliases": [], "qualifies": True,
                "maps_to_focus": None}]
        folded, _forced = entity_roster.apply_previous_decisions(
            copy.deepcopy(raw), previous)
        harvey = next(e for e in folded if e["name"] == "Harvey")
        self.assertEqual(harvey[rw.RELATION_GENDER_FIELD], rw.MALE)
        self.assertEqual(harvey[rw.RELATION_GENDER_BASIS_FIELD], rw.BASIS_ANSWER)

    def test_the_writer_refuses_what_it_cannot_write(self):
        with self.assertRaises(ValueError):
            rw.record_relation_gender(self.vault.root, "harvey", "boy")
        with self.assertRaises(ValueError):
            rw.record_relation_gender(self.vault.root, "nobody", rw.MALE)
        with self.assertRaises(ValueError):
            rw.record_relation_gender(self.vault.root, "harvey", rw.MALE, basis="guess")
        self.assertNotIn(rw.RELATION_GENDER_FIELD, self.vault.entity("harvey"))


if __name__ == "__main__":
    unittest.main()
