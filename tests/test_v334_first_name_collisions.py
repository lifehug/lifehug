"""v335 — a bare first name binds nobody when the roster holds two of them.

The owner's roster holds four people named James: his son James Everett Taylor,
his brother Anthon James "AJ" Taylor (whose family-landmark roster entry is
spelled with nothing but ``James``), his father James Edwin Taylor, and his
grandfather James Edwin Taylor Sr. His inbox holds two more — college
classmates James Cotter and James Huffman, who will never be roster entities.

Two symptoms this file makes executable:

1. ``resolve_mention`` bound every bare ``"James"`` to the one roster entry
   whose whole key happened to be that word, because the uniqueness gate was
   over exact KEYS and not over name TOKENS. That is how AJ's birthday
   (1990-03-20) came to date the son's birth.
2. ``wiki_compile`` derived the alias ``"James"`` from the Focus title "James
   Everett Taylor" and matched it, word-boundary, against every source body —
   so a seven-year-old's page listed a 2012 CSE494 forensics thread from James
   Cotter as a "Supporting Story Source".

The rule: a bare given name several people bear resolves to nobody. A
distinguishing token — a surname, a curated alias like "AJ", or a relationship
word the roster corroborates ("my son James", "Dad") — is what makes the name
answerable. Without one the mention stays unresolved and becomes a question.

Synthetic data only; NEVER references ~/Workspace/dave.
"""

from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SYSTEM = ROOT / "system"
sys.path.insert(0, str(SYSTEM))

import identity_resolution as ir


def load(name):
    """A private copy of system/<name>.py that does not clobber sys.modules."""
    spec = importlib.util.spec_from_file_location(name, SYSTEM / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    orig = sys.modules.get(name)
    sys.modules[name] = mod
    try:
        spec.loader.exec_module(mod)
    finally:
        if orig is not None:
            sys.modules[name] = orig
        else:
            sys.modules.pop(name, None)
    return mod


wc = load("wiki_compile")

NOW = "2026-09-23T00:00:00Z"
EVIDENCE = "claim:" + "d" * 24


def person(name, *, slug=None, aliases=(), **extra) -> dict:
    entry = {
        "name": name,
        "slug": slug or name.strip().lower().replace(" ", "-").replace(".", ""),
        "aliases": list(aliases),
        "qualifies": True,
    }
    entry.update(extra)
    return entry


def roster(*entities) -> dict:
    return {"version": 1, "type": "person", "entities": list(entities)}


#: The four Jameses, in the shape the owner's vault actually holds them: the
#: brother's entry was minted by the family landmark recorder under his legal
#: first name, so its whole key is the bare word every other James also answers
#: to. That is the shape the old uniqueness gate read as unambiguous.
FOUR_JAMESES = roster(
    person("James", relationship="sibling", aliases=["AJ", "A.J.", "Anthon James Taylor"]),
    person("James Everett Taylor", relationship="child"),
    person("James Edwin Taylor", relationship="parent", aliases=["Dad"]),
    person("James Edwin Taylor Sr", relationship="grandparent"),
    person("Katie", relationship="spouse"),
)

SON = "person/james-everett-taylor"
BROTHER = "person/james"
FATHER = "person/james-edwin-taylor"
GRANDFATHER = "person/james-edwin-taylor-sr"


def resolved(mention, snapshot=FOUR_JAMESES):
    return ir.resolve_mention(mention, roster=snapshot, evidence_ref=EVIDENCE, now=NOW)


# --------------------------------------------------------------------------
# Symptom 1 — the mention
# --------------------------------------------------------------------------


class BareFirstNameBindsNobodyTests(unittest.TestCase):
    def test_a_bare_james_resolves_to_nobody(self):
        record = resolved("James")
        self.assertEqual(record.resolution, "uncertain")
        self.assertEqual(record.reason, ir.SHARED_NAME_TOKEN_REASON)
        self.assertIsNone(record.resolved_ref)
        self.assertFalse(record.is_resolved())

    def test_the_guard_holds_for_any_vault_with_two_of_the_same_first_name(self):
        # The narrowest possible collision: two entries, one word each.
        two = roster(person("James", slug="james-one"), person("James", slug="james-two"))
        self.assertEqual(resolved("James", two).resolution, "uncertain")
        # And the same word inside two longer names, neither spelled bare.
        inside = roster(person("James Everett Taylor"), person("James Edwin Taylor"))
        self.assertEqual(resolved("James", inside).resolution, "uncertain")
        self.assertEqual(resolved("James", inside).reason, ir.SHARED_NAME_TOKEN_REASON)

    def test_the_whole_running_travels_with_the_unresolved_mention(self):
        # §2.5: uncertain surfaces, never drops — and the row must be answerable,
        # which means naming who it could be.
        record = resolved("James")
        refs = {c["ref"] for c in record.candidates}
        self.assertEqual(refs, {BROTHER, SON, FATHER, GRANDFATHER})

    def test_an_unresolved_bare_name_becomes_a_question(self):
        record = resolved("James")
        item = ir.identity_work_item(record, claim_refs=[EVIDENCE], now=NOW)
        self.assertIsNotNone(item)
        self.assertEqual(item["kind"], "identity_uncertain")
        self.assertEqual(item["subject_ref"], "unresolved:james")
        self.assertIn("James", item["prompt_intent"])

    def test_the_mention_key_is_the_one_handle_for_every_sighting(self):
        # §5.4 answer-once: one Mirror row for "which James?", not one per claim.
        self.assertEqual(
            ir.unresolved_subject_ref("James"), ir.unresolved_subject_ref("james.")
        )

    def test_a_single_james_vault_still_resolves_on_sight(self):
        # The rule fires on collision, not on first names.
        one = roster(person("James Everett Taylor"), person("Katie"))
        record = resolved("James", one)
        self.assertEqual(record.resolution, "uncertain", "no exact key answers 'James'")
        self.assertEqual(record.reason, "no_candidate")
        lone = roster(person("James", relationship="child"), person("Katie"))
        self.assertEqual(resolved("James", lone).resolved_ref, "person/james")


class DistinguishingTokenTests(unittest.TestCase):
    def test_a_curated_alias_is_a_distinguishing_token(self):
        for mention in ("AJ", "aj", "A.J."):
            with self.subTest(mention=mention):
                record = resolved(mention)
                self.assertEqual(record.resolved_ref, BROTHER)
                self.assertEqual(record.reason, "roster_alias")

    def test_my_son_james_is_the_son(self):
        record = resolved("my son James")
        self.assertEqual(record.resolved_ref, SON)
        self.assertEqual(record.reason, ir.RELATIONSHIP_QUALIFIED_REASON)

    def test_dad_and_my_father_james_are_the_father(self):
        self.assertEqual(resolved("Dad").resolved_ref, FATHER)
        self.assertEqual(resolved("my father James").resolved_ref, FATHER)

    def test_my_brother_james_is_the_brother(self):
        self.assertEqual(resolved("my brother James").resolved_ref, BROTHER)

    def test_a_surname_and_a_suffix_are_distinguishing_tokens(self):
        self.assertEqual(resolved("James Edwin Taylor Sr").resolved_ref, GRANDFATHER)
        self.assertEqual(resolved("James Edwin Taylor Sr").reason, "unique_name")
        self.assertEqual(resolved("James Everett Taylor").resolved_ref, SON)

    def test_a_relationship_word_the_roster_does_not_corroborate_binds_nothing(self):
        # No James on this roster is an uncle; the word narrows to nobody.
        record = resolved("my uncle James")
        self.assertEqual(record.resolution, "uncertain")
        self.assertIsNone(record.resolved_ref)

    def test_two_people_in_one_relationship_stay_uncertain(self):
        twins = roster(
            person("James Everett Taylor", relationship="child"),
            person("James Arthur Taylor", relationship="child"),
        )
        record = resolved("my son James", twins)
        self.assertEqual(record.resolution, "uncertain")
        self.assertEqual(record.reason, "ambiguous_candidates")
        self.assertEqual(len(record.candidates), 2)

    def test_the_new_rung_introduces_no_containment_folding(self):
        # The audit's rule, unchanged: "Jim" must never absorb "Jimmy", with or
        # without a relationship word in the mention.
        near = roster(person("Jimmy Carter", relationship="parent"), person("Jim Beam"))
        self.assertIsNone(resolved("Jim", near).resolved_ref)
        self.assertIsNone(resolved("my father Jim", near).resolved_ref)
        self.assertEqual(resolved("Jim", near).candidates, ())

    def test_an_exact_ref_is_never_second_guessed(self):
        record = resolved(BROTHER)
        self.assertEqual(record.resolved_ref, BROTHER)
        self.assertEqual(record.reason, "exact_ref")


class MentionVocabularyTests(unittest.TestCase):
    def test_a_mention_splits_into_names_and_relationship_words(self):
        self.assertEqual(ir.mention_tokens("my son James"), (("james",), ("son",)))
        self.assertEqual(ir.mention_tokens("our Son  James."), (("james",), ("son",)))
        self.assertEqual(
            ir.mention_tokens("James Edwin Taylor Sr"),
            (("james", "edwin", "taylor", "sr"), ()),
        )
        self.assertEqual(ir.mention_tokens("Dad"), ((), ("dad",)))

    def test_the_census_is_over_refs_so_five_spellings_are_one_person(self):
        index = ir.roster_index(FOUR_JAMESES)
        self.assertEqual(index.refs_named("katie"), ("person/katie",))
        self.assertEqual(len(index.refs_named("james")), 4)

    def test_a_middle_name_is_not_a_name_anybody_answers_to(self):
        # `by_name_token` narrows a qualified mention; `by_given_name` is the
        # census. A surname sits in the first and not in the second, which is
        # what keeps a stranger named Quincy resolvable beside an owner spelled
        # "Pat Quincy Example" (tests/test_owner_identity_inputs.py).
        index = ir.roster_index(FOUR_JAMESES)
        self.assertEqual(len(index.refs_bearing("taylor")), 4)
        self.assertEqual(index.refs_named("taylor"), ())
        middle = roster(
            person("Pat", aliases=["Pat Quincy Example"]), person("Quincy")
        )
        self.assertEqual(resolved("Quincy", middle).resolved_ref, "person/quincy")

    def test_shared_name_token_refs_is_empty_for_anything_but_a_bare_name(self):
        self.assertEqual(ir.shared_name_token_refs("my son James", FOUR_JAMESES), ())
        self.assertEqual(ir.shared_name_token_refs("James Everett Taylor", FOUR_JAMESES), ())
        self.assertEqual(ir.shared_name_token_refs("Katie", FOUR_JAMESES), ())
        self.assertEqual(len(ir.shared_name_token_refs("James", FOUR_JAMESES)), 4)

    def test_an_unresolved_bare_name_is_a_mirror_reason(self):
        self.assertIn(ir.SHARED_NAME_TOKEN_REASON, ir.UNCERTAIN_REASONS)
        self.assertIn(ir.SHARED_NAME_TOKEN_REASON, ir.RESOLUTION_REASONS)
        self.assertIn(ir.RELATIONSHIP_QUALIFIED_REASON, ir.DETERMINISTIC_REASONS)


class ClaimAttachmentTests(unittest.TestCase):
    """The claim keeps its evidence whatever identity does or does not land."""

    def claim(self, mention):
        return {
            "source_ref": {
                "source_id": "sources/conversations/msg-synthetic.md",
                "revision": "sha256:" + "3" * 64,
            },
            "source_kind": "conversation",
            "claim_type": "date",
            "subject_mention": mention,
            "event_kind": "birth",
            "temporal_value": "1990-03-20",
            "evidence": [{"quote": "He was born 03/20/1990"}],
            "basis": "explicit",
            "confidence": 0.9,
            "extractor_version": "listener/schema:1/prompt:beadfeed/model:test-model",
            "created_at": NOW,
        }

    def test_a_bare_name_claim_keeps_its_quote_and_carries_no_subject_ref(self):
        record = resolved("James")
        after = ir.apply_resolution(self.claim("James"), record, now=NOW)
        self.assertEqual(after["subject_mention"], "James")
        self.assertNotIn("subject_ref", after)
        self.assertEqual(
            after["subject_resolution"]["reason"], ir.SHARED_NAME_TOKEN_REASON
        )
        self.assertEqual(after["evidence"][0]["quote"], "He was born 03/20/1990")

    def test_the_same_claim_resolves_the_moment_the_mention_distinguishes(self):
        record = resolved("my brother James")
        after = ir.apply_resolution(self.claim("my brother James"), record, now=NOW)
        self.assertEqual(after["subject_ref"], BROTHER)


class ClassifierBindingTests(unittest.TestCase):
    """The classifier's own roster lookup obeys the same census."""

    def setUp(self):
        self.cc = load("classifier_context")
        self.rosters = {"person": ir.roster_index(FOUR_JAMESES)}

    def test_a_bare_first_name_is_reported_as_ambiguous_not_bound(self):
        refs, unresolved, ambiguities = self.cc._resolved_subject_refs(
            ["James"], rosters=self.rosters
        )
        self.assertEqual(refs, [])
        self.assertEqual([a["mention"] for a in ambiguities], ["James"])
        self.assertEqual(len(ambiguities[0]["candidate_refs"]), 4)

    def test_a_distinguished_name_still_binds(self):
        refs, _unresolved, ambiguities = self.cc._resolved_subject_refs(
            ["James Everett Taylor", "AJ"], rosters=self.rosters
        )
        self.assertEqual(refs, sorted([SON, BROTHER]))
        self.assertEqual(ambiguities, [])


# --------------------------------------------------------------------------
# Symptom 2 — the wiki page's supporting sources
# --------------------------------------------------------------------------


CATEGORIES = {
    "F1": {"group": "focus", "name": "James Everett Taylor"},
    "F2": {"group": "focus", "name": "Anthon James Taylor"},
    "F3": {"group": "focus", "name": "Dad"},
    "F4": {"group": "focus", "name": "Charlee Joy Taylor"},
}

WIKI_ROSTER = roster(
    person("James", relationship="sibling"),
    person("Charlee", relationship="child"),
)


def record(source, author, body, authority="third_party_record"):
    return {
        "id": f"gmail:{source}",
        "source": f"sources/gmail/{source}.md",
        "path": Path(f"sources/gmail/{source}.md"),
        "title": source.replace("-", " "),
        "body": f"**2012-02-01** — **{author}** · {source}\n\n{body}",
        "kind": "external_record",
        "witness": "",
        "witness_slug": "",
        "content_sha256": "f" * 64,
        "sensitivity": "private",
        "authority": authority,
        "source_trust": "external_record",
        "candidate_kind": "",
        "subject_type": "",
        "subject_label": "",
        "subject_slug": "",
        "subject_aliases": [],
    }


COTTER = record(
    "2012-02-01-cse494-forensics-group-project",
    "James Cotter",
    "Hey guys, when are you available to meet? Best Regards, James Cotter",
)
HUFFMAN = record(
    "2012-09-14-sw-engineering-concentration",
    "James Huffman",
    "Hey man here is what the advisor gave me for ya. — James",
)
CHARLEE_NOTE = record(
    "2015-04-20-flight-reservation",
    "Katie Taylor",
    "Charlee wants the window seat again.",
)
SOURCES = {s["id"]: s for s in (COTTER, HUFFMAN, CHARLEE_NOTE)}


class SupportingSourceTests(unittest.TestCase):
    def setUp(self):
        wc._RETRACTIONS = []
        self.known = wc.known_person_names(
            CATEGORIES, WIKI_ROSTER, SOURCES, "David James Taylor"
        )

    def focus(self, title, known_people):
        descs = wc.plan_focuses(CATEGORIES, [], {}, SOURCES, WIKI_ROSTER, known_people)
        return next(d for d in descs if d["title"] == title)

    def test_a_strangers_thread_attaches_to_no_family_page(self):
        for title in ("James Everett Taylor", "Anthon James Taylor", "Dad"):
            with self.subTest(title=title):
                desc = self.focus(title, self.known)
                self.assertNotIn(COTTER["source"], desc["sources"])
                self.assertNotIn(HUFFMAN["source"], desc["sources"])

    def test_without_the_census_the_bare_first_name_pulled_them_in(self):
        # The regression itself, kept executable so the fix cannot quietly rot.
        desc = self.focus("James Everett Taylor", ())
        self.assertIn(COTTER["source"], desc["sources"])
        self.assertIn(HUFFMAN["source"], desc["sources"])

    def test_an_unshared_first_name_still_widens_its_page(self):
        # Nobody else in this vault answers to "Charlee", so her Focus keeps the
        # derived alias and the thread that only says her first name.
        desc = self.focus("Charlee Joy Taylor", self.known)
        self.assertIn(CHARLEE_NOTE["source"], desc["sources"])

    def test_the_census_counts_people_not_spellings(self):
        self.assertEqual(wc._first_name_alias("Charlee Joy Taylor", self.known), "Charlee")
        self.assertEqual(wc._first_name_alias("James Everett Taylor", self.known), "")
        # Unchanged with no census to consult (the pre-v335 signature).
        self.assertEqual(wc._first_name_alias("Charlee Joy Taylor"), "Charlee")

    def test_a_third_party_records_author_is_a_person_in_the_census(self):
        self.assertEqual(wc._record_author_names(COTTER), ["James Cotter"])
        self.assertEqual(wc._record_author_names(dict(COTTER, authority="")), [])
        self.assertIn((frozenset({"james"}), frozenset({"james", "cotter"})), self.known)
        # The owner's MIDDLE name is not a name he answers to, so it never makes
        # somebody else's first name ambiguous (parity with
        # `temporal_publication.owner_names_from_profile`).
        self.assertIn(
            (frozenset({"david"}), frozenset({"david", "james", "taylor"})), self.known
        )

    def test_a_multi_word_name_is_never_dropped(self):
        kept = wc.unambiguous_names(
            ["James Everett Taylor", "James", "Jamie"], self.known
        )
        self.assertEqual(kept, ["James Everett Taylor", "Jamie"])

    def test_a_roster_entity_spelled_with_a_shared_first_name_graduates_no_page(self):
        taken: set = set()
        descs = wc.plan_entities(
            "person",
            {},
            SOURCES,
            roster(person("James", page_eligible=True, relationship="sibling")),
            taken,
            self.known,
        )
        self.assertEqual(descs, [])
        self.assertEqual(taken, set())


if __name__ == "__main__":
    unittest.main()
