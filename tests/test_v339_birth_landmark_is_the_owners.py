"""v339 — the `birth` landmark is the OWNER's, and a pasted relative's record
never merges into it.

THE INCIDENT (owner's vault, staging, 2026-09-23 20:34 UTC, commit b6982658
"Landmark: birth"). On 2026-09-21 the owner pasted two of his grandfathers'
vital records into a Timeline card conversation — the genealogy-app shape,

    Name • 8 Sources
    James Edwin Taylor Sr
    ...
    Birth • 6 Sources
    17 October 1930
    ...
    Death • 3 Sources
    4 April 1996

— and a `landmark-record` filing (`maintenance:reflect:…:landmark-record`)
turned both men's births into `birth` landmark records:
`landmark:entry-35a59936fc440531af66b360` (1930-10-17, basis `anchor`, James
Edwin Taylor Sr) and `landmark:entry-9c618f4b4d540072b4ec2103` (1929-09-30,
basis `anchor`, Darvin Burrows Beauchamp, carrying the raw grains `day: "30"`,
`month: "September"`, `year: "1929"`).

`birth` has no identity rung — `questions.yaml` declares
`birth.identity_kind:` empty and `birth.collection: singleton`, because a
birth landmark is the owner's OWN birthday — so all three records keyed on the
same empty `entry_key` and folded into ONE entry. The owner's own entry, whose
stated birth is 1981-07-11, came out reading:

    {"day": "30", "month": "September", "year": "1929",
     "date": {"best": "1981-07-11", "basis": "stated"},
     "date_alternates": [{"best": "1929-09-30", "basis": "anchor"},
                         {"best": "1930-10-17", "basis": "anchor"}]}

and, because `landmark_projection.entry_subject_mention` mints
`OWNER_BIRTH_MENTION` for this domain unconditionally, the fold filed three
`self` birth claims and minted the Mirror contradiction *"Two dates are
claimed for your birth — 11 July 1981 and 30 September 1929. Which is
right?"*.

WHAT THIS FILE PINS, in the order the rule runs:

1. the rule itself (`landmark_projection.birth_landmark_not_owner`) — a named
   subject, a pasted `Name` header, a bare relation word, and a year a
   lifetime from the owner's STATED birth year;
2. the WRITE seat (`timeline.save_landmark`) — a named relative's birth is
   ROUTED to `family`, an unnamed one is REFUSED by name, and neither touches
   the owner's entry;
3. the DRAW seat (`landmark_projection.project_landmark_entries`) — a vault
   that already holds the bad records heals on its next redraw;
4. the MERGE rule (`landmarks_interaction.merge_landmark_entry`) — a
   weaker-basis claim never respells the winner's raw day/month/year;
5. and that an ORDINARY correction of the owner's own birthday still lands
   exactly as it did before v339.

Synthetic data only; NEVER references ~/Workspace/dave.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "system"))
sys.path.insert(0, str(ROOT / "tests"))

import landmark_projection as lp  # noqa: E402
import landmarks_interaction as li  # noqa: E402
import temporal_store as ts  # noqa: E402
from tempdirs import root_parent_tmp  # noqa: E402

NOW = "2026-09-23T20:34:23Z"


def date_claim(best: str, basis: str = "stated", *, granularity: str = "day",
               confidence: str = "certain") -> dict:
    """One `chronology` date record, spelled the way the vault spells it."""
    return {"best": best, "earliest": best, "latest": best,
            "granularity": granularity, "confidence": confidence,
            "basis": basis, "anchors": [], "provenance": []}


#: The owner's own birthday, as he stated it.
OWNER_STATED = date_claim("1981-07-11")

#: The owner's `birth` record, as the ladder files it: the claim plus the same
#: date in the ladder's own words.
OWNER_BIRTH_RECORD = {"domain": "birth", "day": "11", "month": "July",
                      "year": "1981", "date": OWNER_STATED}

#: `landmark:entry-9c618f4b4d540072b4ec2103`, byte-for-byte the record the
#: real filing wrote — the maternal grandfather's birth, with the raw grains
#: that overwrote the owner's.
GRANDFATHER_RECORD = {"domain": "birth", "day": "30", "month": "September",
                      "year": "1929", "date": date_claim("1929-09-30", "anchor")}

#: `landmark:entry-35a59936fc440531af66b360` — the paternal grandfather's,
#: which carried the date alone.
OTHER_GRANDFATHER_RECORD = {"domain": "birth",
                            "date": date_claim("1930-10-17", "anchor")}

#: The prose the owner actually pasted, which is where a NAME is readable.
PASTED_VITAL_RECORD = (
    "Name • 8 Sources\n"
    "James Edwin Taylor Sr\n"
    "\n"
    "Sex • 6 Sources\n"
    "Male\n"
    "\n"
    "Birth • 6 Sources\n"
    "17 October 1930\n"
    "Corpus Christi, Nueces, Texas, United States\n"
    "\n"
    "Death • 3 Sources\n"
    "4 April 1996\n"
)


# --------------------------------------------------------------------------
# 1. The rule
# --------------------------------------------------------------------------


class BirthLandmarkNotOwnerRuleTest(unittest.TestCase):
    """`lp.birth_landmark_not_owner` — two reasons, either one enough."""

    def test_the_grandfathers_birth_is_a_lifetime_from_the_owners(self) -> None:
        """THE DEFECT, at the rule. 1929 against a stated 1981 is 52 years."""
        self.assertEqual(
            lp.birth_landmark_not_owner(GRANDFATHER_RECORD, owner_birth=OWNER_STATED),
            lp.BIRTH_LANDMARK_NOT_OWNER)
        self.assertEqual(
            lp.birth_landmark_not_owner(OTHER_GRANDFATHER_RECORD,
                                        owner_birth=OWNER_STATED),
            lp.BIRTH_LANDMARK_NOT_OWNER)

    def test_a_record_that_names_another_man_is_not_the_owners(self) -> None:
        record = {"domain": "birth", "label": "James Edwin Taylor Sr",
                  "date": date_claim("1930-10-17", "anchor")}
        self.assertEqual(lp.birth_landmark_not_owner(record),
                         lp.BIRTH_LANDMARK_NOT_OWNER)
        self.assertEqual(lp.third_party_birth_subject(record),
                         "James Edwin Taylor Sr")

    def test_the_pasted_vital_records_name_line_is_read(self) -> None:
        """`Name • 8 Sources` on one line, the man on the next."""
        record = {"domain": "birth", "what": PASTED_VITAL_RECORD,
                  "date": date_claim("1930-10-17", "anchor")}
        self.assertEqual(lp.third_party_birth_subject(record),
                         "James Edwin Taylor Sr")
        self.assertEqual(lp.birth_landmark_not_owner(record),
                         lp.BIRTH_LANDMARK_NOT_OWNER)

    def test_a_bare_relation_word_refuses_and_names_nobody(self) -> None:
        """"my grandfather" says whose birth it is and says *not mine* — and
        there is no ``who`` to file a `family` entry under, so the rule
        refuses rather than minting an unnamed relative."""
        record = {"domain": "birth", "what": "my grandfather's birth",
                  "date": date_claim("1929-09-30", "anchor")}
        self.assertEqual(lp.birth_landmark_not_owner(record),
                         lp.BIRTH_LANDMARK_NOT_OWNER)
        self.assertIsNone(lp.third_party_birth_subject(record))

    def test_the_owners_own_stated_record_is_his(self) -> None:
        self.assertIsNone(lp.birth_landmark_not_owner(OWNER_BIRTH_RECORD,
                                                      owner_birth=OWNER_STATED))

    def test_an_ordinary_correction_of_the_owners_birthday_is_his(self) -> None:
        """"actually I was born on the 12th" — one day, not a lifetime."""
        record = {"domain": "birth", "day": "12", "month": "July",
                  "year": "1981", "date": date_claim("1981-07-12")}
        self.assertIsNone(lp.birth_landmark_not_owner(record,
                                                      owner_birth=OWNER_STATED))

    def test_a_year_bound_needs_a_stated_birth_to_measure_against(self) -> None:
        """With nothing stated, only a NAME refuses — a vault whose owner has
        not said when he was born must still be able to record it."""
        self.assertIsNone(lp.birth_landmark_not_owner(GRANDFATHER_RECORD))
        self.assertIsNone(lp.birth_landmark_not_owner(GRANDFATHER_RECORD,
                                                      owner_birth=None))

    def test_the_bound_is_fifteen_years_and_the_edge_is_not_refused(self) -> None:
        self.assertEqual(lp.OWNER_BIRTH_YEAR_TOLERANCE, 15)
        inside = {"domain": "birth", "date": date_claim("1995-07-11", "anchor")}
        outside = {"domain": "birth", "date": date_claim("1996-07-11", "anchor")}
        self.assertIsNone(lp.birth_landmark_not_owner(inside,
                                                      owner_birth=OWNER_STATED))
        self.assertEqual(
            lp.birth_landmark_not_owner(outside, owner_birth=OWNER_STATED),
            lp.BIRTH_LANDMARK_NOT_OWNER)

    def test_the_owners_own_name_on_his_own_birth_is_not_a_third_party(self) -> None:
        record = {"domain": "birth", "label": "Dana Example",
                  "date": date_claim("1981-07-11")}
        self.assertIsNone(lp.birth_landmark_not_owner(
            record, owner_birth=OWNER_STATED, owner_names=("Dana Example",)))
        self.assertIsNone(lp.third_party_birth_subject(
            record, owner_names=("Dana Example",)))

    def test_a_none_terminal_and_a_skip_are_answers_not_third_parties(self) -> None:
        self.assertIsNone(lp.birth_landmark_not_owner({"domain": "birth",
                                                       "skipped": True}))
        self.assertEqual(lp.not_a_landmark("birth", {"domain": "birth",
                                                     "skipped": True}),
                         lp.SKIPPED_ANSWER)

    def test_the_reason_is_in_the_closed_vocabulary(self) -> None:
        self.assertIn(lp.BIRTH_LANDMARK_NOT_OWNER, lp.NOT_A_LANDMARK_REASONS)
        self.assertEqual(
            lp.not_a_landmark("birth", GRANDFATHER_RECORD,
                              owner_birth=OWNER_STATED),
            lp.BIRTH_LANDMARK_NOT_OWNER)

    def test_not_a_landmark_without_vault_context_keeps_its_old_answers(self) -> None:
        """The two keywords are ADDITIVE: a caller that knows nothing about
        the owner gets exactly the three pre-v339 reasons."""
        self.assertIsNone(lp.not_a_landmark("birth", GRANDFATHER_RECORD))
        self.assertEqual(lp.not_a_landmark("work", {"domain": "work",
                                                    "what": "SEO work"}),
                         lp.UNNAMED_ORGANIZATION)

    def test_owner_stated_birth_reads_the_stated_claim_and_not_an_anchor(self) -> None:
        sources = [
            {"domain": "birth", "record": OTHER_GRANDFATHER_RECORD},
            {"domain": "birth", "record": OWNER_BIRTH_RECORD},
            {"domain": "birth", "record": GRANDFATHER_RECORD},
        ]
        self.assertEqual(lp.owner_stated_birth(sources), OWNER_STATED)
        self.assertIsNone(lp.owner_stated_birth(
            [{"domain": "birth", "record": GRANDFATHER_RECORD}]))

    def test_a_relative_record_keeps_the_date_and_drops_births_grains(self) -> None:
        """`family` has a `who` rung for exactly this. The raw grains belong
        to `birth`'s ladder, not `family`'s, so they must not ride along."""
        rerouted = lp.relative_birth_record(GRANDFATHER_RECORD,
                                            "Darvin Burrows Beauchamp")
        self.assertEqual(rerouted["domain"], "family")
        self.assertEqual(rerouted["who"], "Darvin Burrows Beauchamp")
        self.assertEqual(rerouted["date"]["best"], "1929-09-30")
        for grain in ("day", "month", "year"):
            self.assertNotIn(grain, rerouted)


# --------------------------------------------------------------------------
# 2. The write seat — refused at FILING so nothing new lands
# --------------------------------------------------------------------------


class ThePastedRecordNeverLandsOnTheOwnersBirthTest(unittest.TestCase):
    """`timeline.save_landmark`, the one writer every landmark write reaches."""

    def setUp(self) -> None:
        import timeline  # noqa: PLC0415

        self.timeline = timeline
        tmp = root_parent_tmp(self, ROOT, prefix="lifehug-v339-")
        (tmp / "state").mkdir(parents=True, exist_ok=True)
        patcher = mock.patch.object(timeline, "LANDMARKS_STORE",
                                    tmp / "state" / "landmarks.json")
        patcher.start()
        self.addCleanup(patcher.stop)
        self.root = tmp
        # The owner states his own birthday first, exactly as onboarding does.
        timeline.save_landmark("birth", dict(OWNER_BIRTH_RECORD))

    def owner_birth_entry(self) -> dict:
        entries = self.timeline.load_landmarks().get("birth") or []
        self.assertEqual(len(entries), 1, entries)
        return entries[0]

    def test_the_owners_entry_starts_out_his(self) -> None:
        entry = self.owner_birth_entry()
        self.assertEqual(entry["date"]["best"], "1981-07-11")
        self.assertEqual((entry["day"], entry["month"], entry["year"]),
                         ("11", "July", "1981"))
        self.assertNotIn(li.DATE_ALTERNATES_KEY, entry)

    def test_an_unnamed_grandfathers_birth_is_refused_by_name(self) -> None:
        """THE DEFECT, at the write seat. The record that actually landed
        carried no name at all — only a date 52 years out — so there is
        nobody to file it under, and a typed refusal is the only honest
        outcome: it becomes the question *"whose birth is that?"* instead of
        a silent merge."""
        with self.assertRaises(self.timeline.BirthLandmarkNotOwner) as caught:
            self.timeline.save_landmark("birth", dict(GRANDFATHER_RECORD))
        self.assertEqual(caught.exception.reason, lp.BIRTH_LANDMARK_NOT_OWNER)
        self.test_the_owners_entry_starts_out_his()

    def test_a_named_relatives_birth_is_routed_to_family(self) -> None:
        record = dict(GRANDFATHER_RECORD, label="Darvin Burrows Beauchamp")
        saved = self.timeline.save_landmark("birth", record)
        self.assertEqual(saved["domain"], "family")
        self.assertEqual(saved["who"], "Darvin Burrows Beauchamp")
        self.assertEqual(saved["date"]["best"], "1929-09-30")
        filed = self.timeline.load_landmarks()
        self.assertEqual([entry.get("who") for entry in filed.get("family") or []],
                         ["Darvin Burrows Beauchamp"])
        self.test_the_owners_entry_starts_out_his()

    def test_the_pasted_vital_record_is_routed_under_the_man_it_names(self) -> None:
        saved = self.timeline.save_landmark("birth", {
            "domain": "birth", "what": PASTED_VITAL_RECORD,
            "date": date_claim("1930-10-17", "anchor"),
        })
        self.assertEqual(saved["domain"], "family")
        self.assertEqual(saved["who"], "James Edwin Taylor Sr")
        self.test_the_owners_entry_starts_out_his()

    def test_an_ordinary_correction_still_updates_the_owners_entry(self) -> None:
        """"Actually I was born on the 12th." Unchanged by v339."""
        self.timeline.save_landmark("birth", {
            "domain": "birth", "day": "12", "month": "July", "year": "1981",
            "date": date_claim("1981-07-12"),
        })
        entry = self.owner_birth_entry()
        self.assertEqual(entry["day"], "12")
        self.assertIn(entry["date"]["best"], ("1981-07-11", "1981-07-12"))
        self.assertEqual(
            {alternate["best"] for alternate in entry.get(li.DATE_ALTERNATES_KEY) or ()}
            | {entry["date"]["best"]},
            {"1981-07-11", "1981-07-12"})

    def test_a_bare_day_rung_correction_still_lands(self) -> None:
        """The rung with no date claim beside it — the ladder's ordinary
        shape — reaches the entry as it always did."""
        self.timeline.save_landmark("birth", {"domain": "birth", "day": "12"})
        self.assertEqual(self.owner_birth_entry()["day"], "12")


# --------------------------------------------------------------------------
# 3. The draw seat — skipped at DRAW so what already landed heals
# --------------------------------------------------------------------------


class AVaultThatAlreadyHoldsThemHealsOnRedrawTest(unittest.TestCase):
    """The owner's vault as it stood at b6982658, redrawn under v339.

    Filed through `lp.file_landmark_record` directly, which is what the
    pre-v339 writer did: the records and their claims are IN the substrate
    and nothing here retracts them. The drawing is what heals — the owner's
    raw grains stay his and neither grandfather's date becomes one of his
    `date_alternates`.
    """

    ENTRIES = (
        ("birth", OWNER_BIRTH_RECORD),
        ("birth", OTHER_GRANDFATHER_RECORD),
        ("birth", GRANDFATHER_RECORD),
    )

    def setUp(self) -> None:
        self.root = root_parent_tmp(self, ROOT, prefix="lifehug-v339-draw-")
        (self.root / "state").mkdir(parents=True, exist_ok=True)
        for ordinal, (domain, record) in enumerate(self.ENTRIES, start=1):
            lp.file_landmark_record(self.root, domain, dict(record),
                                    ordinal=ordinal, now=NOW)
        ts.rebuild_active_index(self.root)
        self.sources = lp.load_landmark_sources(self.root)
        self.drawn = lp.project_landmark_entries(
            ts.fold_active_index(self.root), sources=self.sources)

    def birth_entries(self) -> list:
        return list((self.drawn.get("domains") or {}).get("birth") or [])

    def test_the_owners_birth_is_one_entry_and_it_is_his(self) -> None:
        entries = self.birth_entries()
        self.assertEqual(len(entries), 1, entries)
        self.assertEqual(entries[0]["date"]["best"], "1981-07-11")
        self.assertEqual(entries[0]["date"]["basis"], "stated")

    def test_the_raw_grains_are_still_the_eleventh_of_july_1981(self) -> None:
        """The exact defect: the drawing read `30 September 1929`."""
        entry = self.birth_entries()[0]
        self.assertEqual((entry["day"], entry["month"], entry["year"]),
                         ("11", "July", "1981"))

    def test_neither_grandfathers_date_is_one_of_the_owners_alternates(self) -> None:
        entry = self.birth_entries()[0]
        alternates = {row["best"] for row in entry.get(li.DATE_ALTERNATES_KEY) or ()}
        self.assertEqual(alternates, set())
        self.assertNotIn(li.DATE_ALTERNATES_KEY, entry)

    def test_the_records_are_still_in_the_substrate(self) -> None:
        """Un-drawing a record is not retracting it. All three are filed, and
        the two refused ones are still readable — which is what lets the
        vault-side repair supersede their claims deliberately."""
        self.assertEqual(len(self.sources), 3)
        dates = {source["record"].get("date", {}).get("best")
                 for source in self.sources}
        self.assertEqual(dates, {"1981-07-11", "1929-09-30", "1930-10-17"})

    def test_an_owner_only_vault_draws_exactly_as_it_did_before(self) -> None:
        root = root_parent_tmp(self, ROOT, prefix="lifehug-v339-clean-")
        (root / "state").mkdir(parents=True, exist_ok=True)
        lp.file_landmark_record(root, "birth", dict(OWNER_BIRTH_RECORD),
                                ordinal=1, now=NOW)
        ts.rebuild_active_index(root)
        drawn = lp.project_landmark_entries(
            ts.fold_active_index(root), sources=lp.load_landmark_sources(root))
        entries = (drawn.get("domains") or {}).get("birth") or []
        self.assertEqual(len(entries), 1)
        self.assertEqual((entries[0]["day"], entries[0]["month"],
                          entries[0]["year"]), ("11", "July", "1981"))


# --------------------------------------------------------------------------
# 4. The merge rule — stated beats anchor on the raw grains too
# --------------------------------------------------------------------------


class TheMergeRuleKeepsTheStatedGrainsTest(unittest.TestCase):
    """`li.merge_landmark_entry` — the second half of the drawing's defect.

    This is the rule that has to hold for any domain and any pair of claims,
    independently of whose birth it is: the raw date grains are the entry's
    date in the ladder's own words, so a claim that lost on BASIS does not
    get to respell them.
    """

    def test_an_anchor_basis_record_does_not_respell_a_stated_entry(self) -> None:
        merged = li.merge_landmark_entry(dict(OWNER_BIRTH_RECORD),
                                         dict(GRANDFATHER_RECORD))
        self.assertEqual((merged["day"], merged["month"], merged["year"]),
                         ("11", "July", "1981"))
        self.assertEqual(merged["date"]["best"], "1981-07-11")

    def test_the_losing_claim_is_still_kept_as_an_alternate(self) -> None:
        """v222's rule is untouched: the loser still EXISTS to be asked about.
        What v339 stops is the loser rewriting the winner's words."""
        merged = li.merge_landmark_entry(dict(OWNER_BIRTH_RECORD),
                                         dict(GRANDFATHER_RECORD))
        self.assertEqual([row["best"] for row in merged[li.DATE_ALTERNATES_KEY]],
                         ["1929-09-30"])

    def test_two_stated_claims_merge_exactly_as_they_did_before(self) -> None:
        """Equal basis, so nothing is held off: "the 12th" moves the grain
        even though `chronology.reconcile` breaks the tie on EDTF text and
        keeps the 11th as the entry's date."""
        merged = li.merge_landmark_entry(
            dict(OWNER_BIRTH_RECORD),
            {"domain": "birth", "day": "12", "month": "July", "year": "1981",
             "date": date_claim("1981-07-12")})
        self.assertEqual(merged["day"], "12")

    def test_a_better_supported_claim_does_respell_the_grains(self) -> None:
        """A birth certificate (`document`, 7.0) beats a stated claim (6.0),
        wins the reconciliation, and its grains are the entry's."""
        merged = li.merge_landmark_entry(
            dict(OWNER_BIRTH_RECORD),
            {"domain": "birth", "day": "12", "month": "July", "year": "1981",
             "date": date_claim("1981-07-12", "document")})
        self.assertEqual(merged["date"]["best"], "1981-07-12")
        self.assertEqual(merged["day"], "12")

    def test_a_record_with_no_date_at_all_merges_its_rungs(self) -> None:
        """Silence about the date is not a correction of it, and a bare rung
        is still a rung."""
        merged = li.merge_landmark_entry(
            dict(OWNER_BIRTH_RECORD),
            {"domain": "birth", "day": "12"})
        self.assertEqual(merged["day"], "12")
        self.assertEqual(merged["date"]["best"], "1981-07-11")

    def test_a_weaker_claim_does_not_invent_grains_the_entry_never_had(self) -> None:
        prior = {"domain": "birth", "year": "1981", "date": OWNER_STATED}
        merged = li.merge_landmark_entry(prior, dict(GRANDFATHER_RECORD))
        self.assertEqual(merged["year"], "1981")
        self.assertNotIn("day", merged)
        self.assertNotIn("month", merged)

    def test_a_span_domain_is_untouched_by_the_grain_rule(self) -> None:
        """The rule reads `_DATE_GRAIN_RUNGS` only; a city and an address are
        a fuller answer to the same question and still merge last-writer."""
        merged = li.merge_landmark_entry(
            {"domain": "residences", "label": "Bell Avenue", "city": "Dayton"},
            {"domain": "residences", "label": "Bell Avenue",
             "address": "11 Bell Ave"})
        self.assertEqual(merged["city"], "Dayton")
        self.assertEqual(merged["address"], "11 Bell Ave")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
