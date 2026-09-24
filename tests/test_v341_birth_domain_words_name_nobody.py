"""v341 — a `birth` record's OWN domain words name nobody.

THE DEFECT, seen by the hosted platform's CI against the pinned v339/v340
package (2026-09-23). v339 (lifehug#394) reads every subject field of a `birth`
landmark record (`landmark_projection.BIRTH_SUBJECT_FIELDS`) and treats any body
that is not a placeholder, not the literal domain word ``"birth"``, and not an
owner spelling as the name of a THIRD PARTY — which makes
`birth_landmark_not_owner` return `birth_landmark_not_owner` and
`timeline`'s draw seat drop the entry.

But the platform — and every older package seat — files the owner's OWN birth
record under the domain's natural display label:

    {"domain": "birth", "label": "Born", "date": {"best": "1979"}}

"Born" is not a person. v339 read it as one, so an unnamed self-birth labelled
"Born" was silently dropped from the timeline. Four platform tests said so on
the pin, all with that record shape:

* `tests/reflect/test_landmark_record.py::test_a_birth_date_files_as_an_edtf_
  date_and_the_timeline_reads_it_back`
* `tests/reflect/test_landmark_flip_invisibility.py` (two tests)
* `tests/vault_mutation/test_landmark_flip_containment.py::test_a_parked_entry_
  keeps_its_exact_value_in_the_drawing`, which asserts the literal ``['Born']``
  survives the drawing.

(The owner's REAL vault birth record carries no label at all, so it was never
the shape that broke — this is the platform-filed shape.)

THE RULE. A `birth` record whose subject-field text is the birth domain's OWN
vocabulary names NOBODY: it says which domain this is, not whose birth it is.
`landmark_projection.BIRTH_DOMAIN_WORDS` / `is_birth_domain_word` is the ONE
definition, compared WHOLE and casefolded so a real name that merely CONTAINS
one of the words ("Mary Born", "Bornstein") still refuses; and BOTH seats that
ask the question read it — the landmark
(`landmark_projection.third_party_birth_subject`) and the projection's age
anchor (`temporal_timeline._birth_names_only_the_owner`, which until this
release kept its own single-word list through
`identity_resolution.is_owner_birth_domain_word`).

WHAT THIS FILE PINS:

1. the vocabulary itself — whole-text, casefolded, collapsed, never a substring;
2. the rule (`third_party_birth_subject`, `birth_landmark_not_owner`,
   `not_a_landmark`) on the platform's record, with and without `owner_names`;
3. that the pasted-vital-record `Name` header pass is NOT tripped by a one-word
   label, because that regex requires a newline;
4. the WRITE seat (`timeline.save_landmark`) and the DRAW seat
   (`project_landmark_entries`) — the entry lands and survives with its exact
   value, the platform's own assertion;
5. the PROJECTION seat — the same widening keeps the owner's age anchor, with
   the v340 narrowing restored for one call so the loss is SEEN;
6. that v339's refusals all still refuse: the grandfathers, a bare relation
   label, a pasted `Name` header, and the fifteen-year bound;
7. and that there is ONE definition, not two.

Every negative below was run against a build with its guard removed and seen
failing first. Synthetic data only; NEVER references ~/Workspace/dave.
"""

from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "system"))
sys.path.insert(0, str(ROOT / "tests"))

import identity_resolution as ident  # noqa: E402
import landmark_projection as lp  # noqa: E402
import landmarks_interaction as li  # noqa: E402
import temporal_store as ts  # noqa: E402
import temporal_timeline as tt  # noqa: E402
from tempdirs import root_parent_tmp  # noqa: E402

NOW = "2026-09-23T12:00:00Z"


def date_claim(best: str, basis: str = "stated", *, granularity: str = "day") -> dict:
    """One `chronology` date record, spelled the way the vault spells it."""
    return {"best": best, "earliest": best, "latest": best,
            "granularity": granularity, "confidence": "certain",
            "basis": basis, "anchors": [], "provenance": []}


#: THE PLATFORM'S RECORD, byte-for-byte the shape its four failing tests file:
#: the owner's own birth, labelled with the domain's display word, naming
#: nobody, dated to the year.
PLATFORM_BORN_RECORD = {"domain": "birth", "label": "Born",
                        "date": date_claim("1979", granularity="year")}

#: The same record with the label the way a lower-cased host writes it.
LOWERCASE_BORN_RECORD = {"domain": "birth", "label": "born",
                         "date": date_claim("1979", granularity="year")}

#: The owner's own stated birthday, for the year bound to measure against.
OWNER_STATED = date_claim("1981-07-11")

#: v339's own records, kept here so this release cannot quietly undo that one.
GRANDFATHER_RECORD = {"domain": "birth", "day": "30", "month": "September",
                      "year": "1929", "date": date_claim("1929-09-30", "anchor")}

PASTED_VITAL_RECORD = (
    "Name • 8 Sources\n"
    "James Edwin Taylor Sr\n"
    "\n"
    "Birth • 6 Sources\n"
    "17 October 1930\n"
)


# --------------------------------------------------------------------------
# 1. The vocabulary
# --------------------------------------------------------------------------


class TheBirthDomainsOwnVocabularyTest(unittest.TestCase):
    """`lp.BIRTH_DOMAIN_WORDS` and `lp.is_birth_domain_word`, as a unit."""

    REQUIRED = ("birth", "born", "birthday", "birthdate", "birth date",
                "date of birth", "my birth", "your birth", "owner's birth",
                "i was born")

    def test_every_required_spelling_is_a_member(self) -> None:
        for word in self.REQUIRED:
            with self.subTest(word=word):
                self.assertIn(word, lp.BIRTH_DOMAIN_WORDS)
                self.assertTrue(lp.is_birth_domain_word(word))

    def test_the_comparison_is_casefolded_and_whitespace_collapsed(self) -> None:
        for spelling in ("Born", "BORN", "  Born  ", "Date  Of\tBirth",
                         "My Birthday", "I Was Born"):
            with self.subTest(spelling=spelling):
                self.assertTrue(lp.is_birth_domain_word(spelling))

    def test_a_curly_apostrophe_is_not_a_different_word(self) -> None:
        self.assertTrue(lp.is_birth_domain_word("Owner’s birth"))
        self.assertTrue(lp.is_birth_domain_word("owner's birth"))

    def test_it_is_never_a_substring_test(self) -> None:
        """THE REASON this is set membership rather than a regex: a real name
        may CONTAIN one of these words and is still a real name."""
        for name in ("Mary Born", "Bornstein", "Born in Utah", "Osborn",
                     "Birthday Bill", "my grandfather's birth",
                     "James Edwin Taylor Sr"):
            with self.subTest(name=name):
                self.assertFalse(lp.is_birth_domain_word(name))

    def test_nothing_is_not_a_domain_word(self) -> None:
        for empty in ("", "   ", None, {}, [], 7):
            with self.subTest(empty=empty):
                self.assertFalse(lp.is_birth_domain_word(empty))

    def test_the_literal_domain_word_is_still_the_domain_word(self) -> None:
        """v339 compared against `lp.OWNER_BIRTH_DOMAIN` alone; the set
        SUPERSEDES that comparison rather than sitting beside it."""
        self.assertIn(lp.OWNER_BIRTH_DOMAIN, lp.BIRTH_DOMAIN_WORDS)


# --------------------------------------------------------------------------
# 2. The rule
# --------------------------------------------------------------------------


class ABirthLabelledWithItsOwnDomainWordIsTheOwnersTest(unittest.TestCase):
    """THE DEFECT, at the rule. `lp.birth_landmark_not_owner` must say `None`."""

    RECORDS = (("Born", PLATFORM_BORN_RECORD), ("born", LOWERCASE_BORN_RECORD))

    def test_the_platform_record_names_no_third_party(self) -> None:
        for label, record in self.RECORDS:
            with self.subTest(label=label):
                self.assertIsNone(lp.third_party_birth_subject(record))
                self.assertIsNone(lp.third_party_birth_subject(
                    record, owner_names=("Dana Example",)))

    def test_the_platform_record_is_never_refused(self) -> None:
        for label, record in self.RECORDS:
            with self.subTest(label=label):
                self.assertIsNone(lp.birth_landmark_not_owner(record))
                self.assertIsNone(lp.birth_landmark_not_owner(
                    record, owner_names=("Dana Example",)))
                self.assertIsNone(lp.birth_landmark_not_owner(
                    record, owner_birth=None, owner_names=()))

    def test_the_closed_reason_vocabulary_agrees(self) -> None:
        """`not_a_landmark` is the seat both writers reach, so it must agree."""
        for label, record in self.RECORDS:
            with self.subTest(label=label):
                self.assertIsNone(lp.not_a_landmark("birth", record))
                self.assertIsNone(lp.not_a_landmark(
                    "birth", record, owner_names=("Dana Example",)))

    def test_every_subject_field_is_read_the_same_way(self) -> None:
        """`label` is what the platform writes; `name`, `subject` and `who` are
        the other three doors into the same pass, and one rule serves all."""
        for field in lp.BIRTH_SUBJECT_FIELDS:
            for word in ("Born", "Birthday", "date of birth", "my birth"):
                record = {"domain": "birth", field: word,
                          "date": date_claim("1979", granularity="year")}
                with self.subTest(field=field, word=word):
                    self.assertIsNone(lp.third_party_birth_subject(record))
                    self.assertIsNone(lp.birth_landmark_not_owner(record))

    def test_a_named_person_in_the_same_field_still_refuses(self) -> None:
        for word in ("Mary Born", "Bornstein", "James Edwin Taylor Sr"):
            record = {"domain": "birth", "label": word,
                      "date": date_claim("1979", granularity="year")}
            with self.subTest(word=word):
                self.assertEqual(lp.third_party_birth_subject(record), word)
                self.assertEqual(lp.birth_landmark_not_owner(record),
                                 lp.BIRTH_LANDMARK_NOT_OWNER)

    def test_the_year_bound_still_measures_a_domain_worded_record(self) -> None:
        """The two reasons stay INDEPENDENT. Naming nobody is not a licence to
        be 52 years from the owner's stated birthday."""
        far = dict(GRANDFATHER_RECORD, label="Born")
        self.assertIsNone(lp.third_party_birth_subject(far))
        self.assertEqual(lp.birth_landmark_not_owner(far, owner_birth=OWNER_STATED),
                         lp.BIRTH_LANDMARK_NOT_OWNER)
        self.assertIsNone(lp.birth_landmark_not_owner(
            dict(PLATFORM_BORN_RECORD, date=OWNER_STATED),
            owner_birth=OWNER_STATED))


class ThePastedNameHeaderPassIsUntouchedTest(unittest.TestCase):
    """The second pass (`lp.BIRTH_NAME_LINE_RE` over `lp.BIRTH_TEXT_FIELDS`).

    It requires a NEWLINE — the header is on one line and the man on the next —
    so a one-word label can never reach it. That was already true; it is
    asserted here because `label` is a member of `BIRTH_TEXT_FIELDS` too, and
    a future widening of the regex must fail this file rather than production.
    """

    def test_a_one_line_label_never_matches_the_name_header(self) -> None:
        for word in ("Born", "Name", "name", "Name • 8 Sources", "Named"):
            with self.subTest(word=word):
                self.assertIsNone(lp.BIRTH_NAME_LINE_RE.search(word))

    def test_a_born_label_beside_a_pasted_record_still_finds_the_man(self) -> None:
        """Naming nobody in `label` does not blind the second pass: the pasted
        grandfather is still read out of `what` and still refuses."""
        record = {"domain": "birth", "label": "Born", "what": PASTED_VITAL_RECORD,
                  "date": date_claim("1930-10-17", "anchor")}
        self.assertEqual(lp.third_party_birth_subject(record),
                         "James Edwin Taylor Sr")
        self.assertEqual(lp.birth_landmark_not_owner(record),
                         lp.BIRTH_LANDMARK_NOT_OWNER)

    def test_the_bare_pasted_record_is_read_exactly_as_it_was(self) -> None:
        record = {"domain": "birth", "what": PASTED_VITAL_RECORD,
                  "date": date_claim("1930-10-17", "anchor")}
        self.assertEqual(lp.third_party_birth_subject(record),
                         "James Edwin Taylor Sr")


class V339sRefusalsAllStillRefuseTest(unittest.TestCase):
    """This release widens what names NOBODY. It narrows nothing."""

    def test_an_unnamed_grandfather_a_lifetime_out_still_refuses(self) -> None:
        self.assertEqual(
            lp.birth_landmark_not_owner(GRANDFATHER_RECORD, owner_birth=OWNER_STATED),
            lp.BIRTH_LANDMARK_NOT_OWNER)

    def test_a_bare_relation_label_still_refuses(self) -> None:
        """"my grandfather" says whose birth it is and says *not mine*."""
        for record in ({"domain": "birth", "label": "my grandfather",
                        "date": date_claim("1929-09-30", "anchor")},
                       {"domain": "birth", "what": "my grandfather's birth",
                        "date": date_claim("1929-09-30", "anchor")}):
            with self.subTest(record=sorted(record)):
                self.assertEqual(lp.birth_landmark_not_owner(record),
                                 lp.BIRTH_LANDMARK_NOT_OWNER)

    def test_the_owners_own_name_is_still_his_own(self) -> None:
        record = {"domain": "birth", "label": "Dana Example",
                  "date": OWNER_STATED}
        self.assertIsNone(lp.birth_landmark_not_owner(
            record, owner_birth=OWNER_STATED, owner_names=("Dana Example",)))

    def test_the_fifteen_year_bound_is_unmoved(self) -> None:
        self.assertEqual(lp.OWNER_BIRTH_YEAR_TOLERANCE, 15)
        outside = {"domain": "birth", "date": date_claim("1996-07-11", "anchor")}
        self.assertEqual(
            lp.birth_landmark_not_owner(outside, owner_birth=OWNER_STATED),
            lp.BIRTH_LANDMARK_NOT_OWNER)


# --------------------------------------------------------------------------
# 3 + 4. The write seat and the draw seat
# --------------------------------------------------------------------------


class ABornLabelledBirthLandsAndSurvivesTheDrawingTest(unittest.TestCase):
    """The two seats the rule is read at, on the platform's own record."""

    def setUp(self) -> None:
        import timeline  # noqa: PLC0415

        self.timeline = timeline
        self.root = root_parent_tmp(self, ROOT, prefix="lifehug-v341-")
        (self.root / "state").mkdir(parents=True, exist_ok=True)
        patcher = mock.patch.object(timeline, "LANDMARKS_STORE",
                                    self.root / "state" / "landmarks.json")
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_the_write_seat_files_it_instead_of_refusing_it(self) -> None:
        """THE DEFECT, at the write seat: this raised
        `timeline.BirthLandmarkNotOwner` on the pin."""
        saved = self.timeline.save_landmark("birth", dict(PLATFORM_BORN_RECORD))
        self.assertEqual(saved["domain"], "birth")
        entries = self.timeline.load_landmarks().get("birth") or []
        self.assertEqual(len(entries), 1, entries)
        self.assertEqual(entries[0]["label"], "Born")
        self.assertEqual(entries[0]["date"]["best"], "1979")
        self.assertEqual(self.timeline.load_landmarks().get("family") or [], [])

    def test_it_is_not_rerouted_to_family_under_a_person_called_born(self) -> None:
        """The other half of the defect the platform would have seen next: a
        record that names nobody must not become a `family` entry whose `who`
        is the word "Born"."""
        saved = self.timeline.save_landmark("birth", dict(LOWERCASE_BORN_RECORD))
        self.assertEqual(saved["domain"], "birth")
        self.assertNotIn("who", saved)

    def test_the_drawing_keeps_the_parked_entrys_exact_value(self) -> None:
        """The platform's `test_a_parked_entry_keeps_its_exact_value_in_the_
        drawing`, as a fold test here: the drawn labels are exactly `['Born']`."""
        lp.file_landmark_record(self.root, "birth", dict(PLATFORM_BORN_RECORD),
                                ordinal=1, now=NOW)
        ts.rebuild_active_index(self.root)
        drawn = lp.project_landmark_entries(
            ts.fold_active_index(self.root),
            sources=lp.load_landmark_sources(self.root))
        entries = list((drawn.get("domains") or {}).get("birth") or [])
        self.assertEqual([entry.get("label") for entry in entries], ["Born"])
        self.assertEqual(entries[0]["date"]["best"], "1979")
        self.assertNotIn(li.DATE_ALTERNATES_KEY, entries[0])

    def test_a_grandfathers_record_is_still_undrawn(self) -> None:
        """v339's draw seat, on the same vault: naming nobody heals, naming
        somebody else does not."""
        lp.file_landmark_record(self.root, "birth", dict(PLATFORM_BORN_RECORD),
                                ordinal=1, now=NOW)
        lp.file_landmark_record(self.root, "birth",
                                dict(GRANDFATHER_RECORD, label="Darvin Beauchamp"),
                                ordinal=2, now=NOW)
        ts.rebuild_active_index(self.root)
        drawn = lp.project_landmark_entries(
            ts.fold_active_index(self.root),
            sources=lp.load_landmark_sources(self.root))
        entries = list((drawn.get("domains") or {}).get("birth") or [])
        self.assertEqual([entry.get("label") for entry in entries], ["Born"])
        self.assertEqual(entries[0]["date"]["best"], "1979")


# --------------------------------------------------------------------------
# 5. The projection seat — the same words, the owner's age anchor
# --------------------------------------------------------------------------


def _v340_narrowing():
    """The v340 reading of the birth domain's vocabulary — the single legacy
    word — restored for one call, so the loss this release fixes is SEEN."""
    return mock.patch.object(
        lp, "is_birth_domain_word",
        lambda text: lp.collapsed_text(text).casefold() == lp.OWNER_BIRTH_DOMAIN)


class TheAgeAnchorReadsTheSameVocabularyTest(unittest.TestCase):
    """`tt._birth_names_only_the_owner` — v340's own seat, now on one list.

    v340 asked `identity_resolution.is_owner_birth_domain_word`, which knows
    ``"birth"`` and nothing else, so a birth group whose mention was the
    DISPLAY word read as somebody else's birth and cost the owner his age
    anchor — the projection-side twin of the landmark defect.
    """

    def group(self, mention: str, *, ref: str = "self") -> dict:
        return {"claims": [
            {"subject_mention": "birth", "event_kind": "birth", "subject_ref": "self"},
            {"subject_mention": mention, "event_kind": "birth", "subject_ref": ref},
        ]}

    def test_the_domain_words_name_only_the_owner(self) -> None:
        for mention in ("Born", "born", "birthday", "date of birth", "my birth",
                        "your birth", "I was born"):
            with self.subTest(mention=mention):
                self.assertTrue(
                    tt._birth_names_only_the_owner(self.group(mention), "self"))

    def test_v340_read_the_display_word_as_somebody_else(self) -> None:
        with _v340_narrowing():
            self.assertFalse(
                tt._birth_names_only_the_owner(self.group("Born"), "self"))

    def test_a_named_person_still_names_somebody_else(self) -> None:
        self.assertFalse(tt._birth_names_only_the_owner(
            self.group("Wren Ashgrove", ref="person/wren"), "self"))
        self.assertFalse(tt._birth_names_only_the_owner(
            self.group("Mary Born"), "self"))

    def test_v340s_own_unit_case_is_unchanged(self) -> None:
        """`tests/test_v340_apply_keeps_placements.py`'s pair, verbatim."""
        owner_only = {"claims": [
            {"subject_mention": "birth", "event_kind": "birth", "subject_ref": "self"},
            {"subject_mention": "self", "event_kind": "birth", "subject_ref": None},
        ]}
        also_the_son = {"claims": [
            {"subject_mention": "self", "event_kind": "moment", "subject_ref": None},
            {"subject_mention": "Wren", "event_kind": "birth",
             "subject_ref": "person/wren"},
        ]}
        self.assertTrue(tt._birth_names_only_the_owner(owner_only, "self"))
        self.assertFalse(tt._birth_names_only_the_owner(also_the_son, "self"))


class OneDefinitionNotTwoTest(unittest.TestCase):
    """The recurring-defect doctrine: ONE importable definition, every seat."""

    def test_the_projection_seat_reads_the_landmarks_set_and_not_a_copy(self) -> None:
        """Widen the one set and the projection widens with it. A module
        keeping its own list would fail this."""
        widened = frozenset(lp.BIRTH_DOMAIN_WORDS | {"kumquat"})
        group = {"claims": [{"subject_mention": "kumquat", "event_kind": "birth",
                             "subject_ref": "self"}]}
        self.assertFalse(tt._birth_names_only_the_owner(group, "self"))
        with mock.patch.object(lp, "BIRTH_DOMAIN_WORDS", widened):
            self.assertTrue(tt._birth_names_only_the_owner(group, "self"))

    def test_the_landmark_seat_reads_it_too(self) -> None:
        record = {"domain": "birth", "label": "kumquat"}
        self.assertEqual(lp.third_party_birth_subject(record), "kumquat")
        with mock.patch.object(lp, "BIRTH_DOMAIN_WORDS",
                               frozenset(lp.BIRTH_DOMAIN_WORDS | {"kumquat"})):
            self.assertIsNone(lp.third_party_birth_subject(record))

    def test_the_legacy_resolver_word_is_a_member_of_the_one_set(self) -> None:
        """`identity_resolution.LEGACY_OWNER_BIRTH_MENTION` is the spelling the
        fold-time resolution rule answers to. It is deliberately narrower — it
        rewrites a receipt's subject to the owner's handle — but it may never
        drift OUT of the domain's vocabulary."""
        self.assertIn(ident.LEGACY_OWNER_BIRTH_MENTION, lp.BIRTH_DOMAIN_WORDS)
        self.assertTrue(lp.is_birth_domain_word(ident.LEGACY_OWNER_BIRTH_MENTION))


class TheOwnersAgeAnchorSurvivesADisplayWordedBirthTest(unittest.TestCase):
    """The projection, end to end, on the v340 incident's own vault.

    The owner's birth group carries a second telling whose subject mention is
    the landmark's DISPLAY label ("Born") on the owner's own handle, and the
    binder has folded his son's two birth tellings into a second group that
    also reads as the owner's. Exactly one group is about the owner ALONE — and
    that is only true if the display word names nobody.
    """

    def setUp(self) -> None:
        spec = importlib.util.spec_from_file_location(
            "lifehug_v340_fixture",
            ROOT / "tests" / "test_v340_apply_keeps_placements.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        self.fixture = module
        self.claims = [
            *module.age_vault_claims(),
            module.claim(claim_type="occurrence", subject_mention="Born",
                         subject_ref="self", event_kind="birth",
                         source="landmark:entry-birth-label",
                         event_mention="Born", quote="Born"),
        ]
        self.bind = module.the_bind(self.claims)

    def findings(self, result) -> dict:
        return self.fixture.findings(result)

    def test_the_age_placement_still_stands(self) -> None:
        result = self.fixture.derive(self.claims, episode_records=self.bind)
        self.assertEqual(
            self.fixture.best_of(self.fixture.node_named(result,
                                                         "Went bankrupt at 26")),
            ("2007~", "age"))
        found = self.findings(result)
        self.assertNotIn("owner_birth_anchor_ambiguous", found)
        self.assertNotIn("age_without_birth_anchor", found)

    def test_under_v340s_narrowing_the_anchor_is_lost(self) -> None:
        """THE LOSS, seen. With the single-word reading restored the owner's
        two birth groups are indistinguishable, the anchor is refused, and the
        age placement falls to unplaced — out loud, which is v340's own gain."""
        with _v340_narrowing():
            result = self.fixture.derive(self.claims, episode_records=self.bind)
        self.assertEqual(
            self.fixture.best_of(self.fixture.node_named(result,
                                                         "Went bankrupt at 26")),
            (None, None))
        found = self.findings(result)
        self.assertIn("owner_birth_anchor_ambiguous", found)
        self.assertIn("age_without_birth_anchor", found)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
