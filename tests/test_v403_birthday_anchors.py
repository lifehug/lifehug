"""v403 — a birthday anniversary is not a birth; one owner birth; siblings
introduce themselves; a title says where and how old; a stay is drawn at its
entry's best.

The owner's vault, projection generation 273 (2026-10-10):

1. His text "Happy birthday mom" of 19 June 2026 was classified as "Mom's
   birthday", and v344's `A_DATED_BIRTHDAY_IS_A_BIRTH` read it as his mother's
   BIRTH, so every age about her was measured from 2026 ("Mom married dad at
   21" drew at 2047). The same defect gave his father a 2018 birth and his
   daughter a 2026 one. `temporal_timeline.A_BIRTHDAY_ANNIVERSARY_IS_NOT_A_BIRTH`.
2. He had eleven birth rows — nine of them `moment`s dated 1981-07-11 about
   "narrator", "author", "self". `temporal_timeline.ONE_OWNER_BIRTH`.
3. His sisters, told as "Sister Kristine (Kris) Thompson + household:" over
   "- Kris Thompson — November 20, 1977", never reached the roster.
   `roster_relations.A_RELATIVE_TOLD_WITH_A_BIRTHDAY_JOINS_THE_ROSTER`, and
   with it `temporal_timeline.A_TITLE_THAT_IS_AN_AGE_IS_AN_AGE`.
4. "Father laid off in San Diego" was drawn across his Mesa stays.
   `landmark_identity.A_TITLE_THAT_SAYS_WHERE_NAMES_ITS_PLACE`.
5. "Avenue F" was drawn at its alternate end (July 1982) while its landmark
   says June. `temporal_timeline.A_STAY_IS_DRAWN_AT_ITS_ENTRYS_BEST`.

Every test below was run against v402 bytes (main before this release) and SEEN failing first.
Synthetic names only where the owner's own shapes are not needed; NEVER reads
any real vault.
"""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "system"))
sys.path.insert(0, str(ROOT / "tests"))

import chronology as chrono  # noqa: E402
import entity_roster  # noqa: E402
import landmark_identity as lid  # noqa: E402
import roster_relations as rr  # noqa: E402
import temporal_claims as tc  # noqa: E402
import temporal_store as ts  # noqa: E402
import temporal_timeline as tt  # noqa: E402
import timeline  # noqa: E402
from tempdirs import root_parent_tmp  # noqa: E402

from test_v340_apply_keeps_placements import (  # noqa: E402
    NOW,
    claim,
    findings,
    index_of,
    revision,
    value,
    write_vault,
)
import test_v360_followups as fu  # noqa: E402

OWNER = tt.DEFAULT_OWNER_REF
OWNER_BIRTH = "1981-07-11"
OWNER_NAMES = ("Dave", "David James Taylor")


def row(name, slug, relationship, *, born=None, aliases=()):
    entity = {"name": name, "slug": slug, "aliases": list(aliases),
              "relationship": relationship, "source": "landmark:family",
              "qualifies": False, "page_eligible": False}
    if born:
        entity["born"] = chrono.normalized_date(value(born))
    return entity


def roster(*rows):
    return {"version": 1, "type": "person", "entities": list(rows)}


MOTHER = row("Desiree Taylor", "desiree-taylor", "parent", born="1955-06-19",
             aliases=["Desi", "mom", "my mom", "mother", "my mother"])
FATHER_NO_BORN = row("James Taylor", "james-taylor", "parent",
                     aliases=["dad", "my dad", "father"])
DAUGHTER = row("Charlee Joy Taylor", "charlee-joy-taylor", "child",
               born="2010-12-21", aliases=["Charlee"])
SISTER = row("Kristine Thompson", "kristine-thompson", "sibling",
             born="1977-11-20", aliases=["Kris", "Kris Thompson", "Kristine"])


def derive(claims, *, roster_snapshot=(), birth_date=None, landmark_entries=()):
    return tt.derive_calculated_timeline(
        index_of(claims), roster_snapshot=roster_snapshot, birth_date=birth_date,
        landmark_entries=landmark_entries, owner_names=OWNER_NAMES, now=NOW)


def nodes_with(result, claim_id):
    return [node for node in result.nodes if claim_id in node["input_claim_refs"]]


def only_node_of(result, claim_id):
    rows = [node for node in nodes_with(result, claim_id)
            if node.get("event_kind") != "age_frame"]
    assert len(rows) == 1, (claim_id, [n["label"] for n in rows])
    return rows[0]


def best(node):
    return (node.get("best_temporal_value") or {}).get("best")


def finding_rows(result, name):
    return [row for row in result.diagnostics.get("findings") or ()
            if row.get("finding") == name]


def owner_birth_entry():
    """His stated `birth` landmark, as `load_landmark_sources` hands it over."""
    return {"domain": "birth", "source_id": "landmark:entry-birth",
            "record": {"domain": "birth", "label": "birth",
                       "date": {**value(OWNER_BIRTH)}}}


# --------------------------------------------------------------------------
# 1. A birthday anniversary is not a birth
# --------------------------------------------------------------------------


def moms_birthday_text():
    return claim(claim_type="date", subject_mention="Desiree Taylor",
                 event_kind="moment", event_mention="Mom's birthday",
                 source="classification:sources-manual-texts-with-mom#a1",
                 temporal_value=value("2026-06-19"), quote="Happy birthday mom")


def mom_married_at_21():
    return claim(claim_type="age", subject_mention="mother", event_kind="married",
                 event_mention="Mom married dad at 21",
                 source="classification:answers-k14#b2",
                 temporal_value={"low": 21, "high": 21, "approximate": False,
                                 "text": "21"},
                 quote="Mom married dad when she was 21.")


class AnAnniversaryIsNotABirthTests(unittest.TestCase):

    def test_moms_birthday_text_stays_a_moment(self):
        result = derive([moms_birthday_text(), mom_married_at_21()],
                        roster_snapshot=roster(MOTHER))
        node = only_node_of(result, moms_birthday_text()["claim_id"])
        self.assertEqual(node["event_kind"], "moment")
        self.assertEqual(best(node), "2026-06-19")
        refused = finding_rows(result, tt.DIAGNOSTIC_BIRTHDAY_READ_AS_ANNIVERSARY)
        self.assertEqual(len(refused), 1)
        self.assertEqual(refused[0]["node_id"], node["node_id"])
        self.assertEqual(refused[0]["known_birth"], "1955-06-19")
        self.assertEqual(refused[0]["known_from"], "roster_born")

    def test_her_age_is_measured_from_1955_not_2026(self):
        result = derive([moms_birthday_text(), mom_married_at_21()],
                        roster_snapshot=roster(MOTHER))
        married = only_node_of(result, mom_married_at_21()["claim_id"])
        self.assertTrue(best(married).startswith("1976"), best(married))

    def test_a_parents_birthday_inside_his_lifetime_is_refused_without_a_born(self):
        dads = claim(claim_type="date", subject_mention="James Taylor",
                     event_kind="moment", event_mention="Dad's birthday",
                     source="classification:sources-manual-texts-with-dad#c3",
                     temporal_value=value("2018-07-12"), quote="Happy birthday Dad")
        result = derive([dads], roster_snapshot=roster(FATHER_NO_BORN),
                        landmark_entries=[owner_birth_entry()])
        node = only_node_of(result, dads["claim_id"])
        self.assertEqual(node["event_kind"], "moment")
        refused = finding_rows(result, tt.DIAGNOSTIC_BIRTHDAY_READ_AS_ANNIVERSARY)
        self.assertEqual([r["known_from"] for r in refused], ["elder_inside_owner_lifetime"])

    def test_a_worked_out_birth_that_disagrees_with_a_stated_one_is_refused(self):
        stray = claim(claim_type="date", subject_mention="Charlee Joy Taylor",
                      event_kind="birth", source="landmark:entry-charlee-anchor",
                      temporal_value={**value("2026-01"), "basis": "anchor"},
                      quote="children: Charlee Joy Taylor")
        result = derive([stray], roster_snapshot=roster(DAUGHTER))
        node = only_node_of(result, stray["claim_id"])
        self.assertEqual(node["event_kind"], "moment")
        # Its old birth id is published as a redirect, never lost.
        self.assertIn(node["node_id"], result.node_aliases.values())
        self.assertTrue(finding_rows(result, tt.DIAGNOSTIC_ANNIVERSARY_REKEYED))

    def test_a_birthday_that_agrees_with_the_known_birth_is_still_a_birth(self):
        """v344's own case stands: the birthday filed AS the birth."""
        stated = claim(claim_type="date", subject_mention="Desiree Taylor",
                       event_kind="moment", event_mention="Desiree Taylor's birthday",
                       source="classification:sources-manual-desiree#d4",
                       temporal_value=value("1955-06-19"), quote="born June 19, 1955")
        result = derive([stated], roster_snapshot=roster(MOTHER))
        self.assertEqual(only_node_of(result, stated["claim_id"])["event_kind"], "birth")
        self.assertEqual(finding_rows(result, tt.DIAGNOSTIC_BIRTHDAY_READ_AS_ANNIVERSARY), [])

    def test_with_nothing_known_the_v344_reading_is_unchanged(self):
        """No roster birth, no elder relationship: a birthday is a birth."""
        harvey = claim(claim_type="date", subject_mention="Harvey",
                       event_kind="moment", event_mention="Harvey's birthday",
                       source="classification:sources-manual-harvey#e5",
                       temporal_value=value("2021-10-11"), quote="Harvey's birthday")
        result = derive([harvey])
        self.assertEqual(only_node_of(result, harvey["claim_id"])["event_kind"], "birth")


# --------------------------------------------------------------------------
# 2. One owner birth
# --------------------------------------------------------------------------


def owner_tellings():
    """The shapes his vault filed his own birth in (gen 273)."""
    born = value(OWNER_BIRTH)

    def told(mention, subject, source, *, kind="moment", claim_type="date", tv=born,
             event_ref=None):
        payload = dict(claim_type=claim_type, subject_mention=subject, event_kind=kind,
                       event_mention=mention, source=source,
                       quote=mention or "I was born on 11 July 1981.")
        if claim_type == "date":
            payload["temporal_value"] = tv
        if kind == "moment":
            # The per-moment ``event_ref`` the classifier files.
            payload["event_ref"] = event_ref or fu.tp.derive_node_id(
                node_kind="event", event_kind="moment", subject_refs=[subject],
                discriminator=source)
        return claim(**payload)

    shared = fu.tp.derive_node_id(node_kind="event", event_kind="moment",
                                  subject_refs=["narrator"], discriminator="redlands")
    return {
        "anchor": told(None, "self", "landmark:entry-birth", kind="birth"),
        "birth_on": told("Birth on July 11, 1981", "the narrator", "classification:t2#1"),
        "born_ca": told("Born in Redlands, California", "narrator",
                        "classification:little#2", event_ref=shared),
        "born_ca_undated": told("Born in Redlands, California", "narrator",
                                "classification:little#2b", claim_type="occurrence",
                                event_ref=shared),
        "birth_in": told("Birth in Redlands", "author", "classification:msg70#3"),
        "authors": told("Author's birth", "self", "classification:entry-0a24#4"),
        "named": told("Dave Taylor's birth", "Dave Taylor", "classification:roster#5",
                      kind="birth"),
        # Never folded: a title that names no birth, and his son's birth as HIS
        # turning point (v340), and a range that is not his birthday.
        "marker": told("Date marker July 11th 1981", "narrator", "classification:marker#6"),
        "turning": told("Harvey's birth as turning point", "self", "classification:q3#7",
                        tv=value("2021-10-11")),
        "late": told("Born in Redlands", "self", "classification:late#8",
                     tv={"best": "2012-04/2013-06", "earliest": "2012-04",
                         "latest": "2013-06", "granularity": "range",
                         "basis": "anchor", "confidence": "inferred"}),
    }


class OneOwnerBirthTests(unittest.TestCase):

    def setUp(self):
        self.claims = owner_tellings()
        self.result = derive(list(self.claims.values()),
                             landmark_entries=[owner_birth_entry()])

    def owner_birth_nodes(self):
        return [node for node in self.result.nodes
                if node.get("event_kind") == "birth" and best(node) == OWNER_BIRTH]

    def test_exactly_one_owner_birth_node_holds_every_telling(self):
        births = self.owner_birth_nodes()
        self.assertEqual(len(births), 1, [n["label"] for n in births])
        held = set(births[0]["input_claim_refs"])
        for key in ("anchor", "birth_on", "born_ca", "born_ca_undated", "birth_in",
                    "authors", "named"):
            self.assertIn(self.claims[key]["claim_id"], held, key)

    def test_the_old_ids_are_redirects(self):
        target = self.owner_birth_nodes()[0]["node_id"]
        folded = finding_rows(self.result, tt.DIAGNOSTIC_OWNER_BIRTH_TELLING_FOLDED)
        self.assertGreaterEqual(len(folded), 5)
        for row in folded:
            self.assertEqual(self.result.node_aliases.get(row["was_node_id"]), target)

    def test_what_is_not_his_birthday_stays_where_it_is(self):
        target = self.owner_birth_nodes()[0]["node_id"]
        for key in ("marker", "turning", "late"):
            node = only_node_of(self.result, self.claims[key]["claim_id"])
            self.assertNotEqual(node["node_id"], target, key)

    def test_with_no_owner_birth_node_nothing_is_re_keyed(self):
        claims = [c for k, c in self.claims.items() if k not in ("anchor",)]
        result = derive(claims, landmark_entries=[owner_birth_entry()])
        self.assertEqual(finding_rows(result, tt.DIAGNOSTIC_OWNER_BIRTH_TELLING_FOLDED), [])


# --------------------------------------------------------------------------
# 3. A relative told with a birthday joins the roster
# --------------------------------------------------------------------------

ROSTER_NOTE = "sources/manual/2026-09-14-family-birthdays.md"
ROSTER_NOTE_LINES = [
    "Sister Kristine (Kris) Thompson + household:",
    "- Kris Thompson — November 20, 1977",
    "- Doug Thompson — December 25, 1974",
    "Sister Jacque Cook (mixed family: first married Brett, now Lorin Cook):",
    "- Jacque Cook — July 24, 1979",
    "Brother AJ (Anthon James) Taylor + household:",
    "- AJ Taylor — March 20, 1990",
]


def roster_birth(name, day, *, path=ROSTER_NOTE, source="manual:2026-09-14-family-birthdays"):
    payload = claim(claim_type="date", subject_mention=name, event_kind="birth",
                    event_mention=f"{name}'s birth", source=source,
                    temporal_value=value(day), quote=f"{name} — {day}")
    payload = dict(payload)
    payload["source_ref"] = {**payload["source_ref"], "source_path": path}
    return tc.validate_temporal_claim(payload)


AJ = row("Anthon James Taylor", "anthon-james-taylor", "sibling", born="1990-03-20",
         aliases=["AJ", "AJ Taylor"])


class ARelativeToldWithABirthdayTests(unittest.TestCase):

    def plan(self, claims, texts, roster_snapshot=None):
        return rr.relative_birth_introductions(
            claims, roster=roster_snapshot or roster(AJ),
            telling_texts={ROSTER_NOTE: texts}, owner_names=OWNER_NAMES)

    def test_both_sisters_are_introduced_with_their_birthdays(self):
        claims = [roster_birth("Kris Thompson", "1977-11-20"),
                  roster_birth("Doug Thompson", "1974-12-25"),
                  roster_birth("Jacque Cook", "1979-07-24"),
                  roster_birth("AJ Taylor", "1990-03-20")]
        rows = {r["slug"]: r for r in self.plan(claims, ROSTER_NOTE_LINES)["rows"]}
        self.assertEqual(set(rows), {"kristine-thompson", "jacque-cook"})
        kris = rows["kristine-thompson"]
        self.assertEqual((kris["name"], kris["relationship"], kris["born"]),
                         ("Kristine Thompson", "sibling", "1977-11-20"))
        self.assertEqual(set(kris["aliases"]), {"Kris Thompson", "Kris"})
        self.assertEqual(rows["jacque-cook"]["born"], "1979-07-24")
        # A relationship WORD is never an alias: he has two sisters.
        self.assertNotIn("sister", [a.lower() for a in kris["aliases"]])

    def test_a_birth_with_no_relation_on_his_line_introduces_nobody(self):
        rows = self.plan([roster_birth("Doug Thompson", "1974-12-25")], ROSTER_NOTE_LINES)
        self.assertEqual(rows["rows"], ())

    def test_a_distant_relation_word_introduces_nobody(self):
        rows = self.plan([roster_birth("Ruth Holt", "1950-01-01")],
                         ["My aunt Ruth Holt + household:", "- Ruth Holt — Jan 1, 1950"])
        self.assertEqual(rows["rows"], ())


class TheIntroducerIsTheLoopsOwnStepTests(unittest.TestCase):
    """`entity-roster --ensure-introduced` — the daily `roster_introductions`
    step's own door — files them, converges, and picks up a new telling on the
    next ordinary pass."""

    def setUp(self):
        import lifehug_core  # noqa: PLC0415

        self.root = root_parent_tmp(self, ROOT, prefix="lifehug-v403-roster-")
        (self.root / "system").mkdir(parents=True, exist_ok=True)
        (self.root / "state" / "entity_rosters").mkdir(parents=True, exist_ok=True)
        (self.root / "profile.yaml").write_text("name: Dave\n", encoding="utf-8")
        self.path = self.root / "state" / "entity_rosters" / "person.json"
        self.path.write_text(json.dumps(roster(AJ)), encoding="utf-8")
        for module, name, value_ in ((lifehug_core, "REPO_DIR", self.root),
                                     (entity_roster, "ENTITY_DIR", self.path.parent)):
            saved = getattr(module, name)
            setattr(module, name, value_)
            self.addCleanup(setattr, module, name, saved)
        self.claims = [roster_birth("Kris Thompson", "1977-11-20"),
                       roster_birth("Jacque Cook", "1979-07-24")]
        self.note(ROSTER_NOTE, ROSTER_NOTE_LINES)

    def note(self, relative, lines):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("---\ntype: \"unprompted_story\"\n---\n\n" + "\n".join(lines) + "\n",
                        encoding="utf-8")

    def run_pass(self):
        write_vault(self.root, self.claims)
        with mock.patch.object(entity_roster, "recount_stats", return_value={}):
            result = entity_roster.ensure_introduced_relatives()
        result["roster"] = json.loads(self.path.read_text(encoding="utf-8"))
        return result

    def test_the_sisters_get_rows_and_a_second_pass_converges(self):
        first = self.run_pass()
        rows = {r["slug"]: r for r in first["roster"]["entities"]}
        self.assertEqual(rows["kristine-thompson"]["relationship"], "sibling")
        self.assertEqual(rows["kristine-thompson"]["born"]["best"], "1977-11-20")
        self.assertIn("Kris", rows["kristine-thompson"]["aliases"])
        self.assertEqual(rows["jacque-cook"]["born"]["best"], "1979-07-24")
        second = self.run_pass()
        self.assertEqual(second["filed"], 0)
        # v402's retire rule: her birth claim still introduces her, so the
        # daily pass never retires the row it filed.
        self.assertEqual(second.get("retired", []), [])
        self.assertEqual(second["roster"], first["roster"])

    def test_a_new_telling_introduces_on_the_next_ordinary_pass(self):
        self.run_pass()
        later = "sources/manual/2026-11-01-my-brother.md"
        self.note(later, ["My brother Sam Taylor was born May 2, 1993."])
        self.claims.append(roster_birth("Sam Taylor", "1993-05-02", path=later,
                                        source="manual:2026-11-01-my-brother"))
        result = self.run_pass()
        rows = {r["slug"]: r for r in result["roster"]["entities"]}
        self.assertEqual(rows["sam-taylor"]["relationship"], "sibling")
        self.assertEqual(rows["sam-taylor"]["born"]["best"], "1993-05-02")

    def test_a_row_it_introduced_survives_a_roster_refresh(self):
        """`apply_previous_decisions`: relationship and born are settled
        identity facts, kept by a refresh that does not mention her."""
        previous = self.run_pass()["roster"]
        kept, _ = entity_roster.apply_previous_decisions(
            [{"name": "Somebody Else", "aliases": []}], previous)
        self.assertIn("Kristine Thompson", [r.get("name") for r in kept])


class ATitleThatIsAnAgeTests(unittest.TestCase):

    def told(self, mention, tv):
        return claim(claim_type="date", subject_mention="Kristine", event_kind="moment",
                     event_mention=mention, source=f"classification:fisches#{len(mention)}",
                     event_ref=fu.tp.derive_node_id(
                         node_kind="event", event_kind="moment",
                         subject_refs=["Kristine"], discriminator=mention),
                     temporal_value=tv, quote=mention)

    def test_kristine_turns_10_is_her_tenth_birthday(self):
        window = {"best": "1986-06/1988-06", "earliest": "1986-06", "latest": "1988-06",
                  "granularity": "range", "basis": "anchor", "confidence": "inferred"}
        turns = self.told("Kristine turns 10", window)
        bare = self.told("Kristine 10", window)
        result = derive([turns, bare], roster_snapshot=roster(SISTER))
        self.assertEqual(best(only_node_of(result, turns["claim_id"])), "1987-11-20")
        self.assertEqual(best(only_node_of(result, bare["claim_id"])), "1987-11-20/1988-06")

    def test_a_stated_date_is_never_moved_by_a_title(self):
        stated = self.told("Kristine turns 10", value("1987"))
        result = derive([stated], roster_snapshot=roster(SISTER))
        self.assertEqual(best(only_node_of(result, stated["claim_id"])), "1987")

    def test_without_her_birthday_nothing_changes(self):
        window = {"best": "1986-06/1988-06", "earliest": "1986-06", "latest": "1988-06",
                  "granularity": "range", "basis": "anchor", "confidence": "inferred"}
        turns = self.told("Kristine turns 10", window)
        self.assertEqual(best(only_node_of(derive([turns]), turns["claim_id"])),
                         "1986-06/1988-06")


# --------------------------------------------------------------------------
# 4. A title that says where names its place
# --------------------------------------------------------------------------


class ATitleThatSaysWhereTests(fu.PlaceVault):

    INFERRED = {"best": "1987/1990-06", "earliest": "1987", "latest": "1990-06",
                "granularity": "range", "basis": "anchor", "confidence": "inferred"}

    def test_the_phrases(self):
        self.assertEqual(lid.title_place_phrase("Father laid off in San Diego"),
                         ("during", "San Diego"))
        self.assertEqual(lid.title_place_phrase("Family lived in San Diego a few"),
                         ("during", "San Diego"))
        self.assertIsNone(lid.title_place_phrase("Dad graduated, got San Diego job"))

    def test_laid_off_in_san_diego_is_clipped_to_his_san_diego_stay(self):
        self.tell("My dad got laid off from his job in San Diego as an architect",
                  claim_type="date", temporal_value=self.INFERRED,
                  mention="Father laid off in San Diego")
        self.assertEqual(self.window(self.projection(), "Father laid off in San Diego"),
                         ("1989-06", "1990-06"))

    def test_a_stated_date_is_never_second_guessed(self):
        self.tell("My dad got laid off in San Diego in 1987", claim_type="date",
                  temporal_value=value("1987"), mention="Father laid off in San Diego")
        self.assertEqual(self.window(self.projection(), "Father laid off in San Diego"),
                         ("1987", "1987"))


# --------------------------------------------------------------------------
# 5. A stay is drawn at its entry's best
# --------------------------------------------------------------------------


class AStayIsDrawnAtItsEntrysBestTests(fu.PlaceVault):

    def test_the_stay_node_reads_the_landmarks_best_end(self):
        entry = {"domain": "residences", "label": "Thunderhead",
                 "address": "13353 Thunderhead St, San Diego, CA 92129",
                 "city": "San Diego, California",
                 "span": {"end": {**fu.opl.when("1990-05"), "basis": "document",
                                  "confidence": "certain"}}}
        timeline.save_landmark("residences", entry)
        drawn = next(e for e in timeline.load_landmarks()["residences"]
                     if e.get("label") == "Thunderhead")
        self.assertEqual(drawn["span"]["end"]["best"], "1990-05")
        self.assertTrue(drawn.get("span_alternates", {}).get("end"))
        projection = self.projection()
        self.assertEqual(self.window(projection, "Thunderhead")[1], "1990-05")


class TheRulesAreNamedTests(unittest.TestCase):

    def test_every_rule_is_a_named_sentence(self):
        for rule in (tt.A_BIRTHDAY_ANNIVERSARY_IS_NOT_A_BIRTH, tt.ONE_OWNER_BIRTH,
                     tt.A_TITLE_THAT_IS_AN_AGE_IS_AN_AGE,
                     tt.A_STAY_IS_DRAWN_AT_ITS_ENTRYS_BEST,
                     lid.A_TITLE_THAT_SAYS_WHERE_NAMES_ITS_PLACE,
                     rr.A_RELATIVE_TOLD_WITH_A_BIRTHDAY_JOINS_THE_ROSTER):
            self.assertIsInstance(rule, str)
            self.assertGreater(len(rule), 40)

    def test_the_rule_version_moved(self):
        self.assertEqual(tt.CALCULATION_RULE_VERSION, "timeline-rules:29")


if __name__ == "__main__":
    unittest.main()
