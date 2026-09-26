"""v345 — a telling of a landmark folds onto it, and a landmark is drawn as
what it is.

The owner read his own staging Timeline on 2026-09-24 and found three cards
asking when things happened that his vault already dates:

* *"When did Mom married dad at 21 happen?"* — `node:058637e49ae30122189fc6c8`,
  one `age` claim (`claim:34c92ccbf218e122a181ca5f`, age 21, subject `mother`,
  from `answers/K14.md`: *"Mom got married young, at age 21"*). The vault holds
  the wedding: `node:6ece5329bd87d55477f71a54` "Parents' wedding date",
  1976-06-25 stated, from `answers/Q4.md`.
* *"When did Harvey arriving happen?"* — `node:b99fbe3d9b3c9b999744df68`, one
  `occurrence` claim (`claim:7d1ff5938450a9b32cc42e3c`) whose evidence reads
  *"Birth of Harvey during the Etherfuse chapter"*. Harvey's birth is dated
  2021-10-11 on `node:f617262f723b943266375d93`, a ten-telling episode. `R2b`
  did not take it because the classifier typed it `moment`, not `birth`.
* and `node:9ca9a5b15cd988e30132eb98` **"Parents's birth", 1976-06-25** — the
  SAME 1976-06-25, drawn a third time, as a birth. `state/landmarks.json`'s one
  `family` entry is `{"label": "parents", "who": "parents", "relation":
  "parent", "date": 1976-06-25}` — his parents' WEDDING — and `family` declares
  `date_semantics: birth`, so `date_event_kind` read the couple's anniversary
  as a birthday. A couple is never born.

Three rungs, guarded here, each with the owner's own shape as its fixture:

1. `landmark_projection.A_LANDMARK_IS_DRAWN_AS_WHAT_IT_IS` — the ENTRY's own
   kind, read at filing AND at draw, so a vault that already holds the record
   heals on its next redraw and the id it used to be drawn at is REDIRECTED
   rather than lost (:class:`ALandmarkIsDrawnAsWhatItIsTests`,
   :class:`TheOldIdIsRedirectedRatherThanLostTests`).
2. `episode_binder.A_TELLING_OF_A_LANDMARK_FOLDS_ONTO_IT` — the milestone rung
   reads the kind the EVIDENCE names and keys a marriage on the COUPLE
   (:class:`TheEvidenceMayNameTheKindTests`,
   :class:`AMarriageIsOncePerCoupleTests`).
3. `temporal_timeline.AN_AGE_AND_A_DATE_CORROBORATE` — the owner's ruling, both
   ways: an age window that CONTAINS the date is agreeing evidence, one that
   excludes it is a contradiction card naming both
   (:class:`AnAgeAndADateCorroborateTests`).

And the invariant the owner's review is really about, over whole vaults rather
than over named nodes (:class:`NoPlacedNodeIsLostByARedrawTests`): every node
placed before is placed after, or aliased to a node at a compatible date, and no
node is ever drawn at an id `node_aliases` has redirected.

Every negative below was run against a build with its guard removed and SEEN
failing first.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "system"))
sys.path.insert(0, str(ROOT / "tests"))

import chronology as chrono  # noqa: E402
import episode_binder as eb  # noqa: E402
import identity_resolution as ident  # noqa: E402
import landmark_projection as lp  # noqa: E402
import temporal_store as ts  # noqa: E402
import temporal_timeline as tt  # noqa: E402
from tempdirs import root_parent_tmp  # noqa: E402

# The v340 fixtures, reused rather than re-derived, for the reason v342 reused
# them: a second spelling of "the shape a vault's receipts actually have" is how
# two tests come to disagree about what a vault is.
from test_v340_apply_keeps_placements import (  # noqa: E402
    NOW,
    best_of,
    claim,
    derive,
    findings,
    index_of,
    node_named,
    value,
)

# --------------------------------------------------------------------------
# The owner's own shapes
# --------------------------------------------------------------------------

#: `state/landmarks.json`'s one `family` entry, byte for byte minus its date
#: (which the projector derives from the claims — `lp.skeleton_of`'s rule).
PARENTS_ENTRY = {
    "domain": "family",
    "label": "parents",
    "relation": "parent",
    "who": "parents",
    "date": {"best": "1976-06-25", "earliest": "1976-06-25",
             "latest": "1976-06-25", "granularity": "day",
             "confidence": "certain", "basis": "anchor"},
}

#: A sibling entry from the same domain, so every assertion about the couple is
#: also an assertion that an ordinary `family` entry is untouched.
SIBLING_ENTRY = {
    "domain": "family",
    "label": "Kristine",
    "relation": "sibling",
    "who": "Kristine",
    "date": {"best": "1979-04-02", "earliest": "1979-04-02",
             "latest": "1979-04-02", "granularity": "day",
             "confidence": "certain", "basis": "stated"},
}

WEDDING_DAY = "1976-06-25"
MOTHERS_BIRTHDAY = "1955-06-19"

#: `answers/Q4.md` — the wedding, stated to the day.
WEDDING_TELLING = "classification:answers-q4#12f78de35a22"
#: `answers/K14.md` — the age, and no date at all.
AGE_TELLING = "classification:answers-k14#0965c15bc3c2"
#: `sources/manual/2026-09-14-family-birthdays-roster…` — the mother's birthday,
#: which v344 adds to the owner's own vault.
MOTHERS_BIRTH_TELLING = "classification:sources-manual-birthdays#ddddddddddd1"


def wedding_telling() -> dict:
    """*"The author's parents were married on June 25, 1976."*"""
    return claim(claim_type="date", subject_mention="Author's parents",
                 event_kind="moment", source=WEDDING_TELLING,
                 temporal_value=value(WEDDING_DAY),
                 event_mention="Parents' wedding date",
                 quote="The author's parents were married on June 25, 1976.")


def age_telling() -> dict:
    """*"Mom got married young, at age 21"* — an `age` claim about the MOTHER,
    on a node the vault never dated."""
    return claim(claim_type="age", subject_mention="mother",
                 event_kind="moment", source=AGE_TELLING,
                 temporal_value="21", event_mention="Mom married dad at 21",
                 quote="Mom got married young, at age 21, and had kids right away")


def mothers_birth(day: str = MOTHERS_BIRTHDAY) -> dict:
    """What v344 adds: the mother's own birthday, as her own birth node."""
    return claim(claim_type="date", subject_mention="mother", event_kind="birth",
                 source=MOTHERS_BIRTH_TELLING, temporal_value=value(day),
                 event_mention="mother's birth",
                 quote=f"Desiree. Born {day}.")


def file_family_entries(root: Path, entries, *, legacy: bool = False) -> list:
    """The records in the substrate, exactly as the recorder puts them there —
    source first, then receipt (`lp.file_landmark_record`).

    ``legacy=True`` files them as the PRE-v345 filer did, with the DOMAIN's
    declared kind on the receipt. That is the shape the owner's vault actually
    holds and the one the "heals on redraw" claim is about; the default is the
    shape a record filed from today forward has.
    """
    (root / "state").mkdir(parents=True, exist_ok=True)
    refine = lp.entry_date_event_kind
    if legacy:
        lp.entry_date_event_kind = (
            lambda domain, entry, *, row=None: lp.date_event_kind(
                row if isinstance(row, dict) else lp.domain_row_or_none(domain))
        )
    try:
        for ordinal, (domain, record) in enumerate(entries, start=1):
            lp.file_landmark_record(root, domain, dict(record), ordinal=ordinal, now=NOW)
    finally:
        lp.entry_date_event_kind = refine
    ts.rebuild_active_index(root)
    return lp.load_landmark_sources(root)


def view_of(*claims, landmark_entries=()) -> eb.TellingView:
    """One telling's view, through the binder's own one builder."""
    views = eb.telling_views(list(claims), landmark_entries=landmark_entries)
    assert len(views) == 1, sorted(views)
    return next(iter(views.values()))


# --------------------------------------------------------------------------
# 1. A landmark is drawn as WHAT IT IS
# --------------------------------------------------------------------------


class ALandmarkIsDrawnAsWhatItIsTests(unittest.TestCase):
    """`lp.entry_date_event_kind` — the ENTRY's kind, not only the domain's."""

    def test_the_couple_entry_dates_a_wedding(self):
        self.assertEqual(lp.entry_date_event_kind("family", PARENTS_ENTRY),
                         lp.MARRIAGE_EVENT_KIND)

    def test_the_sibling_entry_still_dates_a_birth(self):
        """The narrowness IS the rule: `family` holds siblings too, and every
        one of them legitimately dates a birth."""
        self.assertEqual(lp.entry_date_event_kind("family", SIBLING_ENTRY), "birth")

    def test_a_record_that_states_a_birth_outright_is_a_birth(self):
        """However collective its label reads — the record said so."""
        entry = {**PARENTS_ENTRY, "birth": "1950"}
        self.assertEqual(lp.entry_date_event_kind("family", entry), "birth")

    def test_the_entrys_own_words_may_name_the_marriage(self):
        entry = {"who": "Grandma Betty Jo", "relation": "grandparent",
                 "note": "their wedding anniversary"}
        self.assertEqual(lp.entry_date_event_kind("family", entry),
                         lp.MARRIAGE_EVENT_KIND)

    def test_a_collective_that_is_not_a_couple_says_it_does_not_know(self):
        """Three enumerated siblings share no one event, and guessing which is
        the false precision this whole module refuses. `grandparents` is the
        same refusal for the same reason `identity_resolution` keeps the word out
        of `COUPLE_OF_RELATION_WORD`: up to four people and two weddings."""
        for who in ("Ada, Bo and Cy", "grandparents", "siblings", "my family"):
            with self.subTest(who=who):
                self.assertEqual(
                    lp.entry_date_event_kind("family", {"who": who}),
                    lp.UNDISAMBIGUATED_EVENT_KIND)
        self.assertTrue(lp.is_collective_subject("grandparents"))
        self.assertFalse(lp.is_couple_subject("grandparents"))
        self.assertEqual(lp.COUPLE_SUBJECT_WORDS & lp.COLLECTIVE_SUBJECT_WORDS,
                         frozenset())
        for word in lp.COLLECTIVE_SUBJECT_WORDS:
            self.assertNotIn(word, ident.COUPLE_OF_RELATION_WORD)

    def test_every_other_domain_is_untouched(self):
        for domain, entry, expected in (
            ("children", {"label": "Harvey Rex Taylor"}, "birth"),
            ("losses", {"label": "Grandpa Jim"}, "death"),
            ("birth", {"label": "Born"}, "birth"),
            ("residences", {"label": "Yucaipa"}, lp.UNDISAMBIGUATED_EVENT_KIND),
        ):
            with self.subTest(domain=domain):
                self.assertEqual(lp.entry_date_event_kind(domain, entry), expected)

    def test_a_couple_is_named_whole_and_never_as_a_substring(self):
        """`Parenteau` is a man and `Parents` is a couple — the same rule
        `lp.is_birth_domain_word` is whole-text for."""
        self.assertTrue(lp.is_couple_subject("parents"))
        self.assertTrue(lp.is_couple_subject("Mom and Dad"))
        self.assertFalse(lp.is_couple_subject("Parenteau"))
        self.assertFalse(lp.is_couple_subject("my parents' house"))

    def test_the_entry_is_named_from_its_own_words(self):
        self.assertEqual(lp.wedding_mention_for("parents"), "Parents' wedding")
        self.assertEqual(lp.wedding_mention_for("Mom and Dad"),
                         "Mom and Dad's wedding")
        self.assertEqual(lp.wedding_mention_for(""), "")


class TheDrawingHealsOnRedrawTests(unittest.TestCase):
    """The owner's vault as it stands, redrawn. Nothing is retracted; the
    DRAWING is what changes, exactly as v339 item 10 and v341's amendment do."""

    def setUp(self):
        self.root = root_parent_tmp(self, ROOT, prefix="lifehug-v345-draw-")
        self.sources = file_family_entries(
            self.root, (("family", PARENTS_ENTRY), ("family", SIBLING_ENTRY)),
            legacy=True)
        self.index = ts.fold_active_index(self.root)
        self.drawn = lp.project_landmark_entries(self.index, sources=self.sources)

    def entry(self, who: str) -> dict:
        rows = [row for row in (self.drawn["domains"].get("family") or ())
                if row.get("who") == who]
        self.assertEqual(len(rows), 1, rows)
        return rows[0]

    def test_the_wedding_date_is_still_in_the_drawing(self):
        """The bucket moved with the reading. Read the claim as a wedding and
        leave `_attach_dates` bucketing on `birth`, and the date would simply
        FALL OUT of `state/landmarks.json` — a silent loss worse than the bug."""
        self.assertEqual(self.entry("parents")["date"]["best"], WEDDING_DAY)

    def test_the_sibling_entry_draws_exactly_as_it_did(self):
        self.assertEqual(self.entry("Kristine")["date"]["best"], "1979-04-02")

    def test_the_records_are_still_in_the_substrate(self):
        """Un-drawing a reading is not retracting a claim."""
        self.assertEqual(len(self.sources), 2)
        self.assertEqual(
            {source["record"].get("date", {}).get("best") for source in self.sources},
            {WEDDING_DAY, "1979-04-02"},
        )

    def test_the_claim_on_disk_still_says_what_the_importer_read(self):
        """A reading, never a migration. The receipts are the owner's vault's
        own — both dated claims filed at `birth`, the kind the domain declares —
        and the redraw above changed the DRAWING and not one byte of them."""
        kinds = {row.get("event_kind") for row in self.index["claims"]
                 if row.get("claim_type") == "date"}
        self.assertEqual(kinds, {"birth"})
        read = lp.read_landmark_dates(self.index["claims"], self.sources)
        self.assertEqual(
            {row.get("event_kind") for row in read
             if row.get("claim_type") == "date"},
            {"birth", lp.MARRIAGE_EVENT_KIND},
        )

    def test_a_newly_filed_record_says_it_on_its_own_receipt(self):
        """The other seat. The same rule read at filing, so a record filed from
        today forward needs no read-side repair at all."""
        claims = lp.entry_claims("family", PARENTS_ENTRY,
                                 source_ref={"source_id": "landmark:entry-x",
                                             "revision": "sha256:" + "0" * 64},
                                 now=NOW)
        dated = [row for row in claims if row["claim_type"] == "date"]
        self.assertEqual([row["event_kind"] for row in dated],
                         [lp.MARRIAGE_EVENT_KIND])

    def test_the_fold_draws_one_wedding_and_no_birth(self):
        result = tt.derive_calculated_timeline(
            self.index, landmark_entries=self.sources, now=NOW)
        labels = {node["label"] for node in result.nodes}
        self.assertIn("Parents' wedding", labels)
        self.assertNotIn("Parents's birth", labels)
        wedding = node_named(result, "Parents' wedding")
        self.assertEqual(wedding["event_kind"], lp.MARRIAGE_EVENT_KIND)
        self.assertEqual(best_of(wedding), (WEDDING_DAY, "anchor"))


class TheOldIdIsRedirectedRatherThanLostTests(unittest.TestCase):
    """The third way a node id moves, and the one neither a bind nor a mint can
    see: the DRAWING re-read the fact.

    v342 closed the other two (`episode_fold.AN_ALIAS_NEVER_NAMES_A_NODE_THE_
    DRAWING_PUBLISHES`). A node id is derived FROM its event kind, so an entry
    read as a wedding today is drawn at a different id than the birth it was
    drawn at yesterday — and every work item, session and URL still names the
    old one.
    """

    def setUp(self):
        self.root = root_parent_tmp(self, ROOT, prefix="lifehug-v345-alias-")
        self.sources = file_family_entries(self.root, (("family", PARENTS_ENTRY),),
                                           legacy=True)
        self.index = ts.fold_active_index(self.root)
        self.result = tt.derive_calculated_timeline(
            self.index, landmark_entries=self.sources, now=NOW)
        # Both ids through the substrate's OWN minter, from the subject the
        # entry's claims actually carry ("parents" — this vault has no roster to
        # resolve it with), so neither is pasted in as a literal.
        self.was = tt._mint_node_id(event_kind="birth", subject="parents",
                                    owner_ref=tt.DEFAULT_OWNER_REF)
        self.now_id = tt._mint_node_id(event_kind=lp.MARRIAGE_EVENT_KIND,
                                       subject="parents",
                                       owner_ref=tt.DEFAULT_OWNER_REF)

    def test_the_two_ids_really_are_different(self):
        """Without this the test would pass for the wrong reason."""
        self.assertNotEqual(self.was, self.now_id)

    def test_the_old_id_redirects_to_the_new_one(self):
        self.assertEqual(self.result.node_aliases.get(self.was), self.now_id)

    def test_the_drawing_publishes_no_node_at_the_old_id(self):
        """The v342 invariant, restated for the new alias source: no key of
        `node_aliases` is the id of a node the drawing publishes."""
        drawn = {node["node_id"] for node in self.result.nodes}
        self.assertNotIn(self.was, drawn)
        self.assertEqual(set(self.result.node_aliases) & drawn, set())

    def test_the_redirect_says_so_out_loud(self):
        rows = [row for row in self.result.diagnostics.get("findings") or ()
                if row.get("finding") == tt.DIAGNOSTIC_LANDMARK_DATE_REDRAWN]
        self.assertEqual(len(rows), 1, rows)
        self.assertEqual(rows[0]["was_node_id"], self.was)
        self.assertEqual(rows[0]["node_id"], self.now_id)
        self.assertIn(self.now_id, {node["node_id"] for node in self.result.nodes})
        self.assertEqual((rows[0]["was_event_kind"], rows[0]["event_kind"]),
                         ("birth", lp.MARRIAGE_EVENT_KIND))

    def test_a_vault_with_no_re_read_entry_mints_no_alias_at_all(self):
        root = root_parent_tmp(self, ROOT, prefix="lifehug-v345-clean-")
        sources = file_family_entries(root, (("family", SIBLING_ENTRY),), legacy=True)
        result = tt.derive_calculated_timeline(
            ts.fold_active_index(root), landmark_entries=sources, now=NOW)
        self.assertEqual(result.node_aliases, {})
        self.assertNotIn(tt.DIAGNOSTIC_LANDMARK_DATE_REDRAWN, findings(result))


# --------------------------------------------------------------------------
# 2. A telling of a landmark folds onto it
# --------------------------------------------------------------------------


class TheEvidenceMayNameTheKindTests(unittest.TestCase):
    """*"Harvey arriving"* is Harvey's birth because its own evidence says so."""

    def test_the_three_shapes_a_birth_is_said_in(self):
        for text, expected in (
            ("Birth of Harvey during the Etherfuse chapter", "Harvey"),
            ("Harvey Rex Taylor's birth", "Harvey Rex Taylor"),
            ("Harvey arriving", "Harvey"),
            ("Charlee Joy Taylor was born in Mesa", "Charlee Joy Taylor"),
            ("Dottie arrived that winter", "Dottie"),
        ):
            with self.subTest(text=text):
                self.assertEqual(lp.names_a_birth(text), expected)

    def test_a_sentence_that_is_not_a_birth_names_nobody(self):
        for text in ("Mom got married young, at age 21", "Parents' wedding date",
                     "Bornstein moved to town", "rebirth of the neighborhood",
                     "Harvey Rex Taylor", ""):
            with self.subTest(text=text):
                self.assertEqual(lp.names_a_birth(text), "")

    def test_a_birth_named_as_the_clock_is_not_the_tellings_own_event(self):
        """Both quotes the owner's vault taught this on, verbatim.

        The first run of this release had no adjunct guard and folded a FLIGHT
        dated 2013-06/2013-07 onto a birthday dated 2013-05-10; the second had
        no `when` in the list and read a four-year-old's declaration about her
        brother as his birth. A birth inside a temporal clause is the clock the
        sentence is read against, never the sentence's own event.
        """
        for text in (
            "Katie and James joined the author in Seattle once she was able to "
            "fly after childbirth (when_hint: shortly after James's birth; "
            "anchor: James's birth)",
            'story: I remember her, when James was born, saying, "I love him. I '
            'loved him." She was recognizing her brother was coming. | spine: '
            "James Everett Taylor's birth: 10 May 2013",
            "We moved shortly after the birth of James",
            "Arrived in Seattle with a newborn James (when_hint: James had just "
            "been born when we first moved there; anchor: the move to Seattle)",
        ):
            with self.subTest(text=text[:40]):
                self.assertEqual(lp.names_a_birth(text), "")

    def test_the_classifiers_own_when_metadata_is_cut_before_anything_is_read(self):
        """`when_hint:` / `anchor:` / `spine:` introduce a statement about WHEN,
        very often by naming another moment. Cut first, so the shapes never see
        them — and a real birth phrase in front of one still reads."""
        self.assertEqual(lp.BIRTH_PHRASE_WHEN_MARKERS,
                         ("when_hint:", "anchor:", "spine:"))
        self.assertEqual(
            lp.names_a_birth("Harvey arriving (anchor: Charlee's birth)"), "Harvey")

    def test_the_arrival_verbs_and_the_birth_words_have_one_home_each(self):
        """`BIRTH_PHRASE_WORDS` is DERIVED from `BIRTH_DOMAIN_WORDS` rather than
        re-listed, so a word added there reaches both readers."""
        self.assertLessEqual(lp.BIRTH_PHRASE_WORDS, lp.BIRTH_DOMAIN_WORDS)
        self.assertIn("birth", lp.BIRTH_PHRASE_WORDS)
        self.assertIn("born", lp.BIRTH_PHRASE_WORDS)
        self.assertNotIn("date of birth", lp.BIRTH_PHRASE_WORDS)

    def test_the_owners_telling_reads_as_a_birth(self):
        """The owner's own claim, whole: `occurrence`, kind `moment`, evidence
        *"Birth of Harvey during the Etherfuse chapter"*."""
        view = view_of(claim(
            claim_type="occurrence", subject_mention="Harvey", event_kind="moment",
            source="classification:sources-manual-life-chapters#a4f0669354e1",
            event_mention="Harvey arriving",
            quote="Birth of Harvey during the Etherfuse chapter (when_hint: Harvey.)"))
        self.assertEqual(view.event_kind, "moment")
        self.assertEqual(eb.milestone_of(view), "birth")

    def test_the_name_must_be_somebody_the_telling_is_already_about(self):
        """The half no word list can do. A quote that says a birth about
        somebody the telling does not name says nothing about this telling."""
        view = view_of(claim(
            claim_type="occurrence", subject_mention="Etherfuse",
            event_kind="moment", source="classification:answers-x#aaaaaaaaaaaa",
            event_mention="Founding the company",
            quote="Birth of Harvey during the Etherfuse chapter"))
        self.assertEqual(eb.milestone_of(view), "")

    def test_a_telling_that_names_nobody_reads_nothing(self):
        view = view_of(claim(
            claim_type="occurrence", subject_mention="self", event_kind="moment",
            source="classification:answers-y#bbbbbbbbbbbb",
            event_mention="The baby arriving", quote="The baby arriving changed us."))
        self.assertEqual(eb.milestone_of(view), "")

    def test_the_seattle_flight_is_not_a_birth_to_the_binder_either(self):
        """The regression this release's own first run produced, at the seat that
        produced it: `R2b` folded `node:78a1e615…` "Katie and James fly to
        Seattle" (2013-06/2013-07) into James's birth (2013-05-10)."""
        view = view_of(claim(
            claim_type="relative_order", subject_mention="self",
            event_kind="moment", source="classification:answers-o2#98fa86322fed",
            event_mention="Katie and James fly to Seattle",
            temporal_value={"relation": "after", "anchors": ["James's birth"]},
            quote="Katie and James joined the author in Seattle once she was "
                  "able to fly after childbirth (when_hint: shortly after "
                  "James's birth; anchor: James's birth)"))
        self.assertEqual(eb.milestone_of(view), "")

    def test_the_receipt_is_never_rewritten(self):
        """A reading, at fold and bind time only."""
        row = claim(claim_type="occurrence", subject_mention="Harvey",
                    event_kind="moment", source="classification:z#cccccccccccc",
                    event_mention="Harvey arriving", quote="Birth of Harvey")
        view_of(dict(row))
        self.assertEqual(row["event_kind"], "moment")

    def test_the_wedding_noun_is_read_and_the_state_words_are_not(self):
        """`wedding` is the day; `marriage` is a state a life spends years
        inside, and the owner's vault holds nine nodes that prove it."""
        self.assertEqual(eb.MILESTONE_OF_EVENT_NOUN, {"wedding": "married"})
        self.assertEqual(
            eb.milestone_of(view_of(claim(
                claim_type="date", subject_mention="Author's parents",
                event_kind="moment", source=WEDDING_TELLING,
                temporal_value=value(WEDDING_DAY),
                event_mention="Parents' wedding date",
                quote="married on June 25, 1976"))),
            "married")
        for mention in ("Marriage became hard", "Early marriage arguments",
                        "Marriage rough patch"):
            with self.subTest(mention=mention):
                self.assertEqual(
                    eb.milestone_of(view_of(claim(
                        claim_type="occurrence", subject_mention="self",
                        event_kind="moment", source="classification:m#dddddddddddd",
                        event_mention=mention, quote=mention))),
                    "")

    def test_a_noun_that_says_when_is_not_the_tellings_own_event(self):
        """*"Father fell ill after wedding"* is an illness. The preposition is
        the whole signal, and it is read whole-token."""
        view = view_of(claim(
            claim_type="date", subject_mention="Narrator's father",
            event_kind="moment", source="classification:n#eeeeeeeeeeee",
            temporal_value=value("2007-01-25"),
            event_mention="Father fell ill after wedding",
            quote="Father fell ill after wedding"))
        self.assertEqual(eb.milestone_of(view), "")


class AMarriageIsOncePerCoupleTests(unittest.TestCase):
    """`ident.couple_key` and the bucket `R2b` sweeps with it."""

    def test_the_people_who_are_one_couple(self):
        for people, expected in (
            ({"mother"}, "couple:parents"),
            ({"parents"}, "couple:parents"),
            ({"mom", "dad"}, "couple:parents"),
            ({"father"}, "couple:parents"),
            ({"wife"}, "couple:spouse"),
        ):
            with self.subTest(people=people):
                self.assertEqual(ident.couple_key(people), expected)

    def test_a_name_is_no_couple_and_neither_is_a_mixed_set(self):
        """*"Married Katie"* meets *"Getting married to Katie"* on the NAME,
        through the ordinary subject rung, which is the discriminator a vault
        holding two marriages actually has."""
        for people in ({"katie"}, {"mother", "katie"}, set(), {"grandparents"}):
            with self.subTest(people=people):
                self.assertEqual(ident.couple_key(people), "")

    def test_grandparents_are_deliberately_not_a_couple(self):
        """A person has up to four grandparents and two of their weddings, and
        the bare word discriminates neither — the same reason `graduation` is
        absent from `ONCE_PER_SUBJECT_EVENT_KINDS`."""
        self.assertNotIn("grandparents", ident.COUPLE_OF_RELATION_WORD)
        self.assertNotIn("grandmother", ident.COUPLE_OF_RELATION_WORD)

    def test_a_marriage_is_in_both_lists_and_a_birth_in_only_one(self):
        self.assertEqual(ident.ONCE_PER_COUPLE_EVENT_KINDS, ("married",))
        for kind in ident.ONCE_PER_COUPLE_EVENT_KINDS:
            self.assertIn(kind, ident.ONCE_PER_SUBJECT_EVENT_KINDS)
        self.assertNotIn("birth", ident.ONCE_PER_COUPLE_EVENT_KINDS)

    def test_the_age_telling_reaches_the_wedding_across_two_vocabularies(self):
        """The owner's own pair. *"Mom married dad at 21"* names `mother`;
        *"Parents' wedding date"* names `parents`; `_same_people` refuses them
        and the couple key is why they meet at all."""
        views = eb.telling_views([wedding_telling(), age_telling()])
        left, right = views[AGE_TELLING], views[WEDDING_TELLING]
        self.assertEqual((left.people, right.people),
                         (frozenset({"mother"}), frozenset({"parents"})))
        self.assertFalse(eb._same_people(left.people, right.people))
        links = eb.milestone_links(views)
        self.assertEqual([link.key for link in links], ["married:couple:parents"])
        self.assertEqual({links[0].left, links[0].right},
                         {AGE_TELLING, WEDDING_TELLING})

    def test_the_landmark_is_a_legitimate_target(self):
        """The whole of deliverable 2: the projection's own node for a `family`
        entry is something a telling may fold ONTO."""
        root = root_parent_tmp(self, ROOT, prefix="lifehug-v345-target-")
        sources = file_family_entries(root, (("family", PARENTS_ENTRY),))
        entry_ref = sources[0]["source_id"]
        claims = list(ts.fold_active_index(root)["claims"]) + [
            wedding_telling(), age_telling()]
        views = eb.telling_views(claims, landmark_entries=sources)
        self.assertEqual(eb.milestone_of(views[entry_ref]), "married")
        pairs = {frozenset((link.left, link.right))
                 for link in eb.milestone_links(views)}
        self.assertIn(frozenset((entry_ref, WEDDING_TELLING)), pairs)
        self.assertIn(frozenset((entry_ref, AGE_TELLING)), pairs)

    def test_two_dated_weddings_of_one_couple_still_refuse(self):
        """v340's own guard is not weakened by a wider key: a pair whose stated
        dates cannot both be true is never bound, couple or no couple."""
        other = claim(claim_type="date", subject_mention="mother",
                      event_kind="moment", source="classification:answers-w#ffffffffffff",
                      temporal_value=value("2004"),
                      event_mention="Mom's wedding", quote="Mom's wedding in 2004")
        views = eb.telling_views([wedding_telling(), other])
        self.assertEqual(eb.milestone_links(views), [])


# --------------------------------------------------------------------------
# 3. An age and a date corroborate
# --------------------------------------------------------------------------


class AnAgeAndADateCorroborateTests(unittest.TestCase):
    """*"There are two ways for you to have resolved this"* (owner, 2026-09-24).

    So both are recorded and neither is picked: 1976-06-25 is inside the window
    a 21-year-old born 1955-06-19 occupies (1976-06-19/1977-06-18), and the
    outcome is ONE node at the stated day with the age statement as agreeing
    evidence — never "placed by age", never "absorbed".
    """

    LABEL = "Parents' wedding date"

    def folded(self, *extra) -> tuple:
        """``(the whole result, the one folded node)``.

        The two tellings as ONE node, which is what the bind produces: the age
        claim declares the wedding telling's own node as its event, so the fold
        groups them exactly as an applied `R2b` bind leaves them.
        """
        wedding = dict(wedding_telling())
        node_id = tt._mint_node_id(event_kind="moment",
                                   subject="Author's parents",
                                   owner_ref=tt.DEFAULT_OWNER_REF)
        wedding["event_ref"] = node_id
        age = dict(age_telling())
        age["event_ref"] = node_id
        result = derive([wedding, age, *extra])
        return result, node_named(result, self.LABEL)

    def test_the_window_a_twenty_one_year_old_occupies(self):
        """The arithmetic, named: the package's one age rule, day-exact because
        the birth is."""
        window = chrono.from_age_band(chrono.parse_stated_date(MOTHERS_BIRTHDAY),
                                     21, 21)
        self.assertEqual((window.earliest, window.latest),
                         ("1976-06-19", "1977-06-18"))
        self.assertEqual(window.basis, "age")

    def test_the_age_agrees_and_is_recorded_as_agreeing_evidence(self):
        _result, node = self.folded(mothers_birth())
        self.assertEqual(best_of(node), (WEDDING_DAY, "stated"))
        self.assertEqual(node["conflict_state"], "none")
        self.assertEqual(node.get("alternate_values") or [], [])
        claims = {row.get("claim_id") or row.get("claim")
                  for row in node["best_temporal_value"]["provenance"]}
        self.assertIn("21", claims)

    def test_the_corroboration_names_both_routes(self):
        result, _node = self.folded(mothers_birth())
        rows = [row for row in result.diagnostics.get("findings") or ()
                if row.get("finding") == tt.DIAGNOSTIC_AGE_CORROBORATES]
        self.assertEqual(len(rows), 1, rows)
        self.assertEqual(rows[0]["placed"], WEDDING_DAY)
        # timeline-rules:19 (`chronology.AGE_STATEMENT_GRAIN`): an age is held
        # at the birthday's MONTH — the owner's "I don't care that much about days".
        self.assertEqual(rows[0]["age_window"], "1976-06/1977-06")
        self.assertNotIn(tt.DIAGNOSTIC_AGE_CONTRADICTS, findings(result))

    def test_the_age_never_places_a_moment_the_vault_already_dates(self):
        """"1976-06-25, and she was 21" and not "placed by age". An `age` basis
        outweighs an `anchor` one (`chronology.BASIS_WEIGHT`), so a window that
        competed could legitimately win — and a window is not an answer."""
        self.assertGreater(chrono.BASIS_WEIGHT["age"], chrono.BASIS_WEIGHT["anchor"])
        _result, node = self.folded(mothers_birth())
        self.assertEqual(node["best_temporal_value"]["basis"], "stated")

    def test_a_window_that_excludes_the_date_is_a_contradiction(self):
        """The other half, and it must never be silent. A mother born 1960
        could not have married at 21 in 1976."""
        result, node = self.folded(mothers_birth("1960-06-19"))
        self.assertEqual(best_of(node), (WEDDING_DAY, "stated"))
        self.assertEqual(node["conflict_state"], "contradicted")
        alternates = {row["best"] for row in node.get("alternate_values") or ()}
        self.assertTrue(alternates, "the rival window is kept, so the card can name it")
        rows = [row for row in result.diagnostics.get("findings") or ()
                if row.get("finding") == tt.DIAGNOSTIC_AGE_CONTRADICTS]
        self.assertEqual(len(rows), 1, rows)
        self.assertEqual(rows[0]["placed"], WEDDING_DAY)
        self.assertNotIn(tt.DIAGNOSTIC_AGE_CORROBORATES, findings(result))

    def test_a_contradiction_card_names_both(self):
        result, node = self.folded(mothers_birth("1960-06-19"))
        cards = [item for item in result.work_items
                 if item.get("node_ref") == node["node_id"]
                 and item.get("kind") == "contradiction"]
        self.assertEqual(len(cards), 1, result.work_items)
        prompt = cards[0]["prompt_intent"]
        self.assertIn("25 June 1976", prompt)
        self.assertIn("1981", prompt)

    def test_an_age_is_the_age_of_the_person_the_claim_is_about(self):
        """The group's subject is the couple; the age is the MOTHER's. Measuring
        her age against the node's own subject measures the wrong person."""
        result, node = self.folded()
        self.assertIn("age_without_birth_anchor", findings(result))
        self.assertEqual(best_of(node), (WEDDING_DAY, "stated"))

    def test_without_the_subjects_birth_it_binds_and_asserts_nothing(self):
        """v344 is what supplies her birthday. Until it does, the fold says
        which anchor is missing and places the moment by the stated day alone."""
        result, _node = self.folded()
        self.assertNotIn(tt.DIAGNOSTIC_AGE_CORROBORATES, findings(result))
        self.assertNotIn(tt.DIAGNOSTIC_AGE_CONTRADICTS, findings(result))
        births = [row for row in result.nodes if row.get("event_kind") == "birth"]
        self.assertEqual(births, [], "no birth is asserted for anybody")

    def test_the_owners_own_ages_are_read_exactly_as_they_were(self):
        """Nothing a vault held before this release is read against a different
        birth than it was."""
        from test_v340_apply_keeps_placements import owner_age, owner_birth

        result = derive([owner_birth(), owner_age()])
        self.assertEqual(best_of(node_named(result, "Went bankrupt at 26")),
                         ("2007~", "age"))


# --------------------------------------------------------------------------
# The invariant the review is really about
# --------------------------------------------------------------------------


def placement_audit(before: object, after: object) -> dict:
    """v340's promise, restated over WHOLE vaults (v342's own invariant shape).

    ``{"lost": [...], "drawn_at_an_alias": [...], "moved": [...]}`` — every node
    placed before is placed after at a compatible date, or aliased to a node
    that is; and no node is drawn at an id `node_aliases` has redirected.
    """
    def placed(result) -> dict:
        return {node["node_id"]: chrono.from_dict(node.get("best_temporal_value"))
                for node in result.nodes
                if node.get("best_temporal_value")}

    was, now = placed(before), placed(after)
    drawn = {node["node_id"] for node in after.nodes}
    aliases = dict(after.node_aliases or {})

    def follow(node_id: str) -> str:
        seen: set[str] = set()
        while node_id in aliases and node_id not in seen:
            seen.add(node_id)
            node_id = aliases[node_id]
        return node_id

    report: dict[str, list] = {"lost": [], "drawn_at_an_alias": [], "moved": []}
    for node_id, record in sorted(was.items()):
        target = follow(node_id)
        if target not in now:
            report["lost"].append(node_id)
        elif not chrono.dates_agree(record, now[target]):
            report["moved"].append((node_id, target))
    report["drawn_at_an_alias"] = sorted(set(aliases) & drawn)
    return report


class NoPlacedNodeIsLostByARedrawTests(unittest.TestCase):
    """The audit as an invariant, and its own arithmetic tested against a loss,
    a move and a ghost — because naming the nodes is what let the last two
    releases' defects through."""

    def setUp(self):
        self.root = root_parent_tmp(self, ROOT, prefix="lifehug-v345-audit-")
        self.sources = file_family_entries(
            self.root, (("family", PARENTS_ENTRY), ("family", SIBLING_ENTRY)),
            legacy=True)
        self.claims = list(ts.fold_active_index(self.root)["claims"]) + [
            wedding_telling(), age_telling(), mothers_birth()]
        # BEFORE: the same claims read as the domain declares, which is the
        # v342 drawing. AFTER: read as the entry dates.
        self.before = tt.derive_calculated_timeline(
            index_of(self.claims), landmark_entries=(), now=NOW)
        self.after = tt.derive_calculated_timeline(
            index_of(self.claims), landmark_entries=self.sources, now=NOW)

    def test_the_redraw_loses_no_placement_and_draws_at_no_alias(self):
        report = placement_audit(self.before, self.after)
        self.assertEqual(report["lost"], [])
        self.assertEqual(report["drawn_at_an_alias"], [])
        self.assertEqual(report["moved"], [])

    def test_the_wedding_became_one_node_where_there_were_two(self):
        labels = [node["label"] for node in self.after.nodes]
        self.assertNotIn("Parents's birth", labels)
        self.assertIn("Parents' wedding", labels)
        weddings = [node for node in self.after.nodes
                    if node.get("event_kind") == lp.MARRIAGE_EVENT_KIND]
        self.assertEqual(len(weddings), 1, labels)
        self.assertEqual(best_of(weddings[0]), (WEDDING_DAY, "anchor"))

    def test_the_audit_sees_a_placement_that_simply_vanished(self):
        class Fake:
            def __init__(self, nodes, aliases=None):
                self.nodes = nodes
                self.node_aliases = aliases or {}

        dated = {"node_id": "node:a", "best_temporal_value": value("1990")}
        self.assertEqual(
            placement_audit(Fake([dated]), Fake([]))["lost"], ["node:a"])

    def test_the_audit_sees_a_merge_that_moved_a_dated_moment(self):
        class Fake:
            def __init__(self, nodes, aliases=None):
                self.nodes = nodes
                self.node_aliases = aliases or {}

        before = Fake([{"node_id": "node:a", "best_temporal_value": value("1981")}])
        after = Fake([{"node_id": "node:b", "best_temporal_value": value("2013")}],
                     {"node:a": "node:b"})
        self.assertEqual(placement_audit(before, after)["moved"],
                         [("node:a", "node:b")])

    def test_the_audit_sees_a_node_drawn_at_an_aliased_id(self):
        class Fake:
            def __init__(self, nodes, aliases=None):
                self.nodes = nodes
                self.node_aliases = aliases or {}

        after = Fake([{"node_id": "node:a", "best_temporal_value": value("1990")},
                      {"node_id": "node:b", "best_temporal_value": value("1990")}],
                     {"node:a": "node:b"})
        self.assertEqual(placement_audit(Fake([]), after)["drawn_at_an_alias"],
                         ["node:a"])

    def test_an_alias_chain_is_followed(self):
        class Fake:
            def __init__(self, nodes, aliases=None):
                self.nodes = nodes
                self.node_aliases = aliases or {}

        before = Fake([{"node_id": "node:a", "best_temporal_value": value("1990")}])
        after = Fake([{"node_id": "node:c", "best_temporal_value": value("1990")}],
                     {"node:a": "node:b", "node:b": "node:c"})
        report = placement_audit(before, after)
        self.assertEqual((report["lost"], report["moved"]), ([], []))


# --------------------------------------------------------------------------
# The rules are named, and the names are the ones the docs quote
# --------------------------------------------------------------------------


class TheRulesAreNamedTests(unittest.TestCase):

    def test_each_deliverable_has_exactly_one_statement_of_itself(self):
        for text in (lp.A_LANDMARK_IS_DRAWN_AS_WHAT_IT_IS,
                     eb.A_TELLING_OF_A_LANDMARK_FOLDS_ONTO_IT,
                     tt.AN_AGE_AND_A_DATE_CORROBORATE):
            self.assertIsInstance(text, str)
            self.assertGreater(len(text), 80)

    def test_the_rule_version_moved(self):
        """The same claims calculate to a different node set, a different
        alternates set and a different work-item set. v345 took
        ``timeline-rules:14``; the assertion pins whatever the LIVE value is,
        because the number is a monotonic marker that the rules moved and later
        releases move it again — v346 took ``:15``, v347 ``:16`` the same day,
        v350 ``:17`` and v357 ``:18``."""
        self.assertEqual(tt.CALCULATION_RULE_VERSION, "timeline-rules:25")

    def test_the_binder_exports_its_new_tables(self):
        for name in ("A_TELLING_OF_A_LANDMARK_FOLDS_ONTO_IT",
                     "MILESTONE_OF_EVENT_NOUN",
                     "MILESTONE_NOUN_IS_AN_ADJUNCT_AFTER"):
            self.assertIn(name, eb.__all__)

    def test_the_guard_is_a_framework_file(self):
        import json

        version = json.loads((ROOT / "system" / "version.json").read_text("utf-8"))
        self.assertIn(
            "tests/test_v345_a_telling_of_a_landmark_folds_onto_it.py",
            version["framework_files"],
        )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
