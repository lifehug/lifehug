"""v360 (owner, 2026-09-25): the right couple, the right person.

Three wrong contradiction cards on the owner's assembled rig, and the defects
under them, each guarded here on synthetic data with the real shapes:

1. *"Two dates are claimed for when you got married — 11 January 2007 and 25
   June 1976."* His PARENTS' wedding had been bound, before v350, beside his own
   reception; the cornerstones rule joined the reception to his wedding and the
   binder's expansion step carried the whole stale episode in.
   `episode_binder.A_GROUP_NEVER_TAKES_IN_ANOTHER_COUPLES_MILESTONE`.
2. *"Two dates are claimed for Anthon James Taylor's birth — 20 March 1990 and
   21 December 2010–10 May 2013."* The binder's roster index read a bare
   "James" as his brother (the roster alias ``James``), so "Charlee and James
   arrive" sat in AJ's birth episode.
   `episode_containers.A_BARE_NAME_IN_THE_BINDER_IS_WHO_HE_CALLS_BY_IT`,
   `episode_containers.A_RELATION_WORD_WITH_ANOTHER_NAME_IS_NOT_THEM`,
   `episode_binder.A_MILESTONE_OF_SEVERAL_PEOPLE_IS_NOBODYS_ALONE`,
   `episode_binder.A_BIRTH_DATED_ELSEWHERE_IS_NOT_THEIRS`.
3. *"Two dates are claimed for your father's death — March 2020–June 2020 and
   around 2002."* The 21 in "what got him sick … when I was like 21" dates the
   illness. `temporal_timeline.A_DEATH_IS_DATED_BY_ITS_DATE`, and
   `identity_resolution.AN_OWNERS_POSSESSIVE_IS_HIS_MY` for the raw subject
   "the narrator's father".

Plus the unplaced "High school (sophomore or junior year)":
`classifier_claims.A_RECORDED_RECORD_IS_CANONICAL_DATED_OR_NOT`.

Synthetic data only; NEVER references any real vault.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "system"))
sys.path.insert(0, str(ROOT / "tests"))

import chronology as chrono  # noqa: E402
import classifier_claims as cc  # noqa: E402
import episode_binder as eb  # noqa: E402
import episode_containers as ec  # noqa: E402
import episode_fold_contract as efc  # noqa: E402
import event_identity as ei  # noqa: E402
import identity_resolution as ident  # noqa: E402
import roster_relations as rr  # noqa: E402
import temporal_publication as pub  # noqa: E402
import temporal_timeline as tt  # noqa: E402

import test_v360_look_before_asking as lba  # noqa: E402
from test_v340_apply_keeps_placements import NOW, claim, index_of, value  # noqa: E402
from test_v350_one_couple_one_alias_one_label import (  # noqa: E402
    AGE_TELLING,
    PARENTS_TELLING,
    PARENTS_WEDDING_DAY,
    RECEPTION_DAY,
    RECEPTION_RESOLVER,
    RECEPTION_TELLING,
    age_telling,
    parents_wedding,
    reception_date,
    reception_occurrence,
)

#: The owner's roster rows that decide these tests: his parents, his
#: grandfather (who carries "grandpa"), his brother (whose row carries the alias
#: "James"), his son and his daughter, and his wife.
ROSTER = {"version": 1, "type": "person", "entities": [
    {"name": "James Taylor", "slug": "james-taylor", "relationship": "parent",
     "aliases": ["James Taylor (Dad)", "dad", "my dad", "father", "my father"],
     "born": {"best": "1954-06-04", "earliest": "1954-06-04", "latest": "1954-06-04",
              "granularity": "day", "confidence": "certain", "basis": "stated"}},
    {"name": "Desiree Taylor", "slug": "desiree-taylor", "relationship": "parent",
     "aliases": ["Desi", "mom", "my mom", "mother", "my mother"]},
    {"name": "James Edwin Taylor Sr.", "slug": "james-edwin-taylor-sr",
     "relationship": "grandparent", "aliases": ["grandfather", "grandpa", "my grandpa"]},
    {"name": "Anthon James Taylor", "slug": "anthon-james-taylor", "relationship": "sibling",
     "aliases": ["AJ", "AJ Taylor", "James"],
     "born": {"best": "1990-03-20", "earliest": "1990-03-20", "latest": "1990-03-20",
              "granularity": "day", "confidence": "certain", "basis": "stated"}},
    {"name": "James Everett Taylor", "slug": "james-everett-taylor", "relationship": "child",
     "aliases": [],
     "born": {"best": "2013-05-10", "earliest": "2013-05-10", "latest": "2013-05-10",
              "granularity": "day", "confidence": "certain", "basis": "stated"}},
    {"name": "Charlee Joy Taylor", "slug": "charlee-joy-taylor", "relationship": "child",
     "aliases": [],
     "born": {"best": "2010-12-21", "earliest": "2010-12-21", "latest": "2010-12-21",
              "granularity": "day", "confidence": "certain", "basis": "stated"}},
    {"name": "Katie Taylor", "slug": "katie-taylor", "relationship": "spouse",
     "aliases": ["Katie", "wife", "my wife"]},
]}

#: What he calls people, in his own words (the census `with_called_by` reads).
HIS_WORDS = ["My dad drove us to the lake.", "Grandpa taught me to fish.",
             "AJ and I built the ramps.", "My mom made dinner.", "My wife Katie."]


def index(roster=ROSTER, words=HIS_WORDS) -> ec.EntityIndex:
    return ec.entity_index({"person": rr.with_called_by(roster, words)})


def views_of(claims, roster=ROSTER, words=HIS_WORDS) -> dict:
    return eb.telling_views(claims, entity_index=index(roster, words))


def stale_episode(members, views) -> dict:
    """An existing deterministic `create` over ``members`` — the over-merge an
    earlier rule filed, in the binder's own record shape."""
    envelope = eb.group_envelope({"members": tuple(sorted(members)), "rule_ids": ("R2b",)},
                                 views=views, active={}, now=NOW)
    return {"operations": [envelope["operation"]], "bindings": envelope["bindings"]}


def records_plus(records, result) -> dict:
    ops = list(records["operations"])
    bindings = list(records["bindings"])
    for envelope in result.exact_envelopes:
        ops.append(envelope["operation"])
        bindings.extend(envelope["bindings"])
    return {"operations": ops, "bindings": bindings}


# --------------------------------------------------------------------------
# 1 — his wedding never absorbs his parents'
# --------------------------------------------------------------------------

MARRIED_KATIE = "classification:sources-manual-i-married-katie#e2e77ab0e09a"


def married_katie() -> dict:
    return claim(claim_type="date", subject_mention="self", event_kind="married",
                 source=MARRIED_KATIE, temporal_value=value(RECEPTION_DAY),
                 event_mention="Married Katie Ann Merrill",
                 quote="I married Katie Ann Merrill January 11th, 2007")


def the_weddings() -> list[dict]:
    return [married_katie(), reception_occurrence(), reception_date(),
            parents_wedding(), age_telling()]


class HisWeddingNeverAbsorbsHisParentsTests(unittest.TestCase):
    """The rig's shape: ONE stale deterministic episode holding his wedding,
    his reception, his parents' wedding and "Mom married dad at 21"."""

    def setUp(self):
        self.claims = the_weddings()
        self.views = views_of(self.claims)
        everyone = [MARRIED_KATIE, RECEPTION_TELLING, RECEPTION_RESOLVER,
                    PARENTS_TELLING, AGE_TELLING]
        self.records = stale_episode(everyone, self.views)
        self.stale_id = self.records["operations"][0]["episode_id"]
        self.result = eb.plan(self.claims, episode_records=self.records,
                              entity_index=index(), now=NOW)

    def test_the_parents_leave_as_their_own_create(self):
        groups = self.result.exact_groups
        parents = [g for g in groups if PARENTS_TELLING in g["members"]]
        self.assertEqual(len(parents), 1, groups)
        self.assertEqual(set(parents[0]["members"]), {PARENTS_TELLING, AGE_TELLING})
        self.assertEqual(parents[0]["keeps_episodes"], (self.stale_id,))
        self.assertFalse(any(MARRIED_KATIE in g["members"] and PARENTS_TELLING in g["members"]
                             for g in groups))

    def test_the_episode_it_left_is_never_redirected_at_it(self):
        for envelope in self.result.exact_envelopes:
            self.assertNotIn(self.stale_id, envelope["operation"]["aliases_created"])

    def test_two_weddings_two_dates_no_contradiction(self):
        derived = tt.derive_calculated_timeline(
            index_of(self.claims), episode_records=records_plus(self.records, self.result),
            now=NOW)
        by_best = {}
        for node in derived.nodes:
            best = (node.get("best_temporal_value") or {}).get("best")
            by_best.setdefault(best, []).append(node)
        self.assertIn(RECEPTION_DAY, by_best)
        self.assertIn(PARENTS_WEDDING_DAY, by_best)
        ours = [n for n in by_best[RECEPTION_DAY] if n.get("episode_id")]
        self.assertTrue(ours)
        for node in ours:
            alternates = {(row or {}).get("best") for row in node.get("alternate_values") or ()}
            self.assertNotIn(PARENTS_WEDDING_DAY, alternates)
        contradictions = [row for row in derived.work_items if row["kind"] == "contradiction"]
        self.assertEqual(contradictions, [])

    def test_a_carve_out_never_revives_an_absorbed_operation(self):
        """The rig's exact history: his parents' wedding had its OWN create
        once ({Q4, K14}), which a later create absorbed. The carve-out has the
        same members, and must not digest to that old operation — the store
        would keep the old record and its superseded bindings under the new
        name (`identity_envelope_incomplete`)."""
        first = stale_episode([PARENTS_TELLING, AGE_TELLING], self.views)
        active = efc.active_binding_index(first["bindings"])
        everyone = [MARRIED_KATIE, RECEPTION_TELLING, RECEPTION_RESOLVER,
                    PARENTS_TELLING, AGE_TELLING]
        second = eb.group_envelope({"members": tuple(sorted(everyone)), "rule_ids": ("R2b",)},
                                   views=self.views, active=active, now=NOW)
        records = {"operations": first["operations"] + [second["operation"]],
                   "bindings": first["bindings"] + second["bindings"]}
        result = eb.plan(self.claims, episode_records=records, entity_index=index(), now=NOW)
        carved = [e for e in result.exact_envelopes
                  if set(e["operation"]["members"]) == {PARENTS_TELLING, AGE_TELLING}]
        self.assertEqual(len(carved), 1)
        self.assertNotEqual(carved[0]["operation"]["operation_id"],
                            first["operations"][0]["operation_id"])
        self.assertEqual(carved[0]["operation"]["canonical_inputs"]["acted_on_episode_ids"],
                         [second["operation"]["episode_id"]])
        # ... and it FILES: the writer re-validates the normalized record, which
        # carries what it acted on only inside `canonical_inputs`.
        vault = lba.Vault(self)
        for envelope in (first, {"operations": [second["operation"]],
                                 "bindings": second["bindings"]}):
            ei.file_operation_envelope(vault.root, operation=envelope["operations"][0],
                                       bindings=envelope["bindings"])
        filed = eb.apply_plan(vault.root, result)
        self.assertIn(carved[0]["operation"]["operation_id"], filed["envelopes"])
        reread = ei.load_episode_operations(vault.root)
        self.assertIn(carved[0]["operation"]["operation_id"],
                      {row["operation_id"] for row in reread})

    def test_the_defect_reproduces_without_the_rule(self):
        """Seen failing first: with the member check disabled the expansion
        carries the parents back into his wedding's episode."""
        original = eb._another_couples_milestone  # noqa: SLF001
        eb._another_couples_milestone = lambda view, identity: False  # noqa: SLF001
        try:
            result = eb.plan(self.claims, episode_records=self.records,
                             entity_index=index(), now=NOW)
            self.assertFalse(any(g.get("keeps_episodes") for g in result.exact_groups))
            self.assertFalse(any(PARENTS_TELLING in g["members"] and
                                 set(g["members"]) == {PARENTS_TELLING, AGE_TELLING}
                                 for g in result.exact_groups))
        finally:
            eb._another_couples_milestone = original  # noqa: SLF001

    def test_a_fresh_vault_still_folds_each_couple(self):
        result = eb.plan(self.claims, entity_index=index(), now=NOW)
        for group in result.exact_groups:
            members = set(group["members"])
            self.assertFalse(members & {PARENTS_TELLING, AGE_TELLING}
                             and members & {MARRIED_KATIE, RECEPTION_TELLING}, group)


# --------------------------------------------------------------------------
# 2 — a bare "James" is his son; his children's births are not his brother's
# --------------------------------------------------------------------------

AJ_BIRTH = "classification:sources-manual-family-birthdays#5d0e3ee9630c"
KIDS_ARRIVE = "classification:sources-manual-life-chapters#0e9fa9f09566"
KIDS_RESOLVER = "resolver:d4b6dbc38bffaba009fa6458"
JAMES_BORN = "classification:answers-a15#a2ecc04a2d1c"
SON_BIRTH = "classification:sources-manual-family-birthdays#8393bbdb98c6"
AJ_BY_JAMES = "conversation:msg-11d9436b14395f6d5a2fb69b"


def the_births() -> list[dict]:
    return [
        claim(claim_type="date", subject_mention="AJ Taylor", event_kind="birth",
              source=AJ_BIRTH, temporal_value=value("1990-03-20"),
              event_mention="AJ Taylor's birth", quote="AJ Taylor - March 20, 1990"),
        claim(claim_type="occurrence", subject_mention="children", event_kind="moment",
              source=KIDS_ARRIVE, event_mention="Charlee and James arrive",
              quote="Birth of children Charlee and James during the Storm chapter"),
        claim(claim_type="date", subject_mention="children", event_kind="moment",
              source=KIDS_RESOLVER, event_mention="Charlee and James arrive",
              temporal_value={"best": "2010-12-21/2013-05-10", "earliest": "2010-12-21",
                              "latest": "2013-05-10", "granularity": "range",
                              "basis": "stated", "confidence": "certain"},
              quote="spine: Charlee Joy Taylor's birth: 21 December 2010 | "
                    "spine: James Everett Taylor's birth: 10 May 2013"),
        claim(claim_type="occurrence", subject_mention="James", event_kind="moment",
              source=JAMES_BORN, event_mention="James born", quote="James was born"),
        claim(claim_type="date", subject_mention="James Everett Taylor", event_kind="birth",
              source=SON_BIRTH, temporal_value=value("2013-05-10"),
              event_mention="James Everett Taylor's birth",
              quote="James Everett Taylor - May 10, 2013"),
        # His brother's birth, told by his son's name: "James, AJ, is nine years
        # younger than me ... He was born 03/20/1990".
        claim(claim_type="date", subject_mention="James", event_kind="birth",
              source=AJ_BY_JAMES, temporal_value=value("1990-03-20"),
              event_mention="EtherFuse", quote="He was born 03/20/1990"),
    ]


class ABareJamesIsHisSonTests(unittest.TestCase):

    def test_the_binder_index_reads_what_he_calls_them(self):
        ix = index()
        self.assertEqual(ec.resolve_entities("James born", ix),
                         frozenset({"person/james-everett-taylor"}))
        self.assertEqual(ec.resolve_entities("AJ Taylor", ix),
                         frozenset({"person/anthon-james-taylor"}))
        # A bare name is BARE: "James" inside a longer name is that name's word.
        self.assertEqual(ec.resolve_entities("James Edwin Taylor Sr's death", ix),
                         frozenset({"person/james-edwin-taylor-sr"}))

    def test_without_the_census_nothing_changes(self):
        ix = ec.entity_index({"person": ROSTER})
        self.assertEqual(ec.resolve_entities("James born", ix),
                         frozenset({"person/anthon-james-taylor"}))

    def test_a_relation_word_with_another_name_is_not_them(self):
        ix = index()
        self.assertEqual(ec.resolve_entities("Grandpa Beauchamp's death", ix), frozenset())
        self.assertEqual(ec.resolve_entity_set(
            ["Grandfather's death at 66", "Grandpa Beauchamp"], ix), frozenset())
        self.assertEqual(ec.resolve_entity_set(
            ["Grandpa died at 66", "narrator's maternal grandfather"], ix), frozenset())
        self.assertEqual(ec.resolve_entities("Grandpa died", ix),
                         frozenset({"person/james-edwin-taylor-sr"}))
        self.assertEqual(ec.resolve_entities("Grandpa James Edwin Taylor Sr.'s death", ix),
                         frozenset({"person/james-edwin-taylor-sr"}))
        # A title-cased verb is not a name.
        self.assertEqual(ec.resolve_entities("Father Dies Of COVID", ix),
                         frozenset({"person/james-taylor"}))

    def test_his_childrens_births_leave_his_brothers_episode(self):
        claims = the_births()
        views = views_of(claims)
        records = stale_episode([AJ_BIRTH, KIDS_ARRIVE, KIDS_RESOLVER, AJ_BY_JAMES], views)
        stale_id = records["operations"][0]["episode_id"]
        # His son's birth already has its episode, as on the rig.
        son = stale_episode([JAMES_BORN, SON_BIRTH], views)
        records = {"operations": records["operations"] + son["operations"],
                   "bindings": records["bindings"] + son["bindings"]}
        result = eb.plan(claims, episode_records=records, entity_index=index(), now=NOW)
        kids = [g for g in result.exact_groups if KIDS_ARRIVE in g["members"]]
        self.assertEqual(len(kids), 1, result.exact_groups)
        self.assertNotIn(AJ_BIRTH, kids[0]["members"])
        self.assertNotIn(AJ_BY_JAMES, kids[0]["members"])
        self.assertEqual(kids[0]["keeps_episodes"], (stale_id,))
        for envelope in result.exact_envelopes:
            self.assertNotIn(stale_id, envelope["operation"]["aliases_created"])
        derived = tt.derive_calculated_timeline(
            index_of(claims), episode_records=records_plus(records, result),
            roster_snapshot=ROSTER, now=NOW)
        aj = [n for n in derived.nodes
              if (n.get("best_temporal_value") or {}).get("best") == "1990-03-20"]
        self.assertTrue(aj)
        for node in aj:
            alternates = {(row or {}).get("best") for row in node.get("alternate_values") or ()}
            self.assertNotIn("2010-12-21/2013-05-10", alternates)

    def test_a_birth_dated_as_somebody_elses_is_not_theirs(self):
        views = views_of(the_births())
        self.assertEqual(eb.births_dated_elsewhere(views, index()), frozenset({AJ_BY_JAMES}))
        pairs = {frozenset((l.left, l.right)) for l in eb.milestone_links(
            views, not_theirs=eb.births_dated_elsewhere(views, index()))}
        self.assertNotIn(frozenset((JAMES_BORN, AJ_BY_JAMES)), pairs)

    def test_a_milestone_of_several_people_is_nobodys_alone(self):
        def view(ref, entities):
            return eb.TellingView(
                telling_ref=ref, event_kind="birth", label=ref, stem="", tokens=frozenset(),
                places=frozenset(), participants=frozenset(), eras=frozenset(),
                documents=frozenset(), people=frozenset({"james", "taylor"}),
                entities=frozenset(entities))
        dad = view("dad", {"person/james-taylor"})
        mixed = view("mixed", {"person/james-taylor", "person/anthon-james-taylor"})
        self.assertTrue(eb._two_roster_people(dad, mixed))  # noqa: SLF001
        self.assertFalse(eb._two_roster_people(dad, view("dad2", {"person/james-taylor"})))  # noqa: SLF001


# --------------------------------------------------------------------------
# 3 — a death is dated by its date; "the narrator's father" is his father
# --------------------------------------------------------------------------


class ADeathIsDatedByItsDateTests(unittest.TestCase):

    def setUp(self):
        self.vault = lba.Vault(self)
        self.vault.roster(ROSTER)
        self.vault.owner_birth()
        self.death = self.vault.claim(
            "d15", "My dad died of COVID in the early days of the pandemic.",
            label="Father dies of COVID", claim_type="date", subject="narrator's father",
            value=chrono.parse_stated_date("2020-03/2020-06").to_dict())
        # "what got him sick ... when I was like 21" — the classifier filed his
        # age on the death.
        self.vault.claim("m5", "What got him sick when I was like 21 led to him dying of COVID.",
                         label="Father died of COVID in Mesa", claim_type="age",
                         subject="self", value="21", event_ref=self.death["event_ref"])
        self.vault.publish()
        self.projection = pub.read_projection(self.vault.root)

    def node(self):
        return next(n for n in self.projection["nodes"] if n["node_id"] == self.death["event_ref"])

    def test_no_card_asks_the_illness_against_the_death(self):
        cards = [row for row in self.projection["work_items"]
                 if row.get("node_ref") == self.death["event_ref"] and row["kind"] == "contradiction"]
        self.assertEqual(cards, [])
        node = self.node()
        self.assertEqual(node["best_temporal_value"]["earliest"], "2020-03")
        self.assertEqual(node.get("alternate_values") or [], [])

    def test_the_age_is_a_finding_not_dropped_silently(self):
        findings = [row for row in self.projection["diagnostics"]["findings"]
                    if row.get("finding") == tt.DIAGNOSTIC_DEATH_RIVAL_IS_NOT_A_DATE]
        self.assertEqual(len(findings), 1, findings)
        self.assertEqual(findings[0]["basis"], "age")

    def test_the_raw_subject_is_his_father(self):
        self.assertIn("person/james-taylor", self.node()["subject_refs"])
        self.assertNotIn("narrator's father", self.node()["subject_refs"])

    def test_another_date_he_stated_is_still_asked(self):
        vault = lba.Vault(self)
        vault.roster(ROSTER)
        vault.owner_birth()
        death = vault.claim("d15", "My dad died of COVID.", label="Father dies of COVID",
                            claim_type="date", subject="narrator's father",
                            value=chrono.parse_stated_date("2020-03/2020-06").to_dict())
        vault.claim("d9", "Dad died in 2016.", label="Father's death", claim_type="date",
                    subject="my father", value=chrono.parse_stated_date("2016").to_dict(),
                    event_ref=death["event_ref"])
        vault.publish()
        cards = [row for row in vault.cards()
                 if row.get("node_ref") == death["event_ref"] and row["kind"] == "contradiction"]
        self.assertEqual(len(cards), 1)

    def test_the_owners_possessive_is_his_my(self):
        for mention in ("the narrator's father", "narrator's father", "author's father"):
            with self.subTest(mention=mention):
                self.assertEqual(ident.owner_possessive_as_my(mention), "my father")
                record = ident.resolve_mention(mention, roster=ROSTER, evidence_ref="x")
                self.assertEqual(record.resolution, "same")
                self.assertEqual(record.resolved_ref, "person/james-taylor")
        self.assertEqual(ident.owner_possessive_as_my("Katie's father"), "")


# --------------------------------------------------------------------------
# Dottie's birth: a place he was only near is not where it happened
# --------------------------------------------------------------------------


class APlaceHeWasOnlyNearTests(unittest.TestCase):

    def build(self, quote):
        vault = lba.Vault(self)
        vault.roster(ROSTER)
        vault.owner_birth()
        stay = vault.claim("cupertino", "We moved to Cupertino in June 2015.", label="Cupertino",
                           claim_type="date",
                           value=chrono.parse_stated_date("2015-06/2015-07").to_dict())
        birth = vault.claim("dottie", "Dottie was born January 15th, 2018.",
                            label="Dottie's birth", claim_type="date", subject="Dottie",
                            event_kind="birth",
                            value=chrono.parse_stated_date("2018-01-15").to_dict())
        vault.claim("p4", quote, label="Dottie's birth", claim_type="relative_order",
                    subject="Dottie", event_kind="birth", quote=quote,
                    value={"relation": "within", "anchors": [stay["event_ref"]]},
                    event_ref=birth["event_ref"])
        vault.publish()
        return vault, birth

    def test_by_cupertino_is_not_within_cupertino(self):
        vault, birth = self.build("We were living in the Bay Area at the time in, uh, "
                                  "Santa Clara, by Cupertino.")
        cards = [row for row in vault.cards() if row.get("node_ref") == birth["event_ref"]
                 and row["kind"] == "contradiction"]
        self.assertEqual(cards, [])
        findings = [row for row in pub.read_projection(vault.root)["diagnostics"]["findings"]
                    if row.get("finding") == "anchor_only_nearby"]
        self.assertEqual(len(findings), 1)

    def test_in_cupertino_still_asks(self):
        vault, birth = self.build("We were living in Cupertino at the time.")
        cards = [row for row in vault.cards() if row.get("node_ref") == birth["event_ref"]
                 and row["kind"] == "contradiction"]
        self.assertEqual(len(cards), 1)


# --------------------------------------------------------------------------
# The unplaced "High school (sophomore or junior year)"
# --------------------------------------------------------------------------


class ARecordedRecordIsCanonicalTests(unittest.TestCase):

    def test_an_undated_recorder_claim_still_marks_the_record(self):
        index_rows = {"version": 1, "claims": [
            {"claim_id": "claim:aaaa", "status": "active", "claim_type": "identity",
             "source_ref": {"source_id": "landmark:entry-ff0adc58aac06eb7e8369678",
                            "source_path": "sources/landmarks/entry-ff0adc58aac06eb7e8369678.md"}},
            {"claim_id": "claim:bbbb", "status": "active", "claim_type": "occurrence",
             "source_ref": {"source_id": "classification:sources-landmarks-entry-x#1",
                            "source_path": "sources/landmarks/entry-x.md"}},
        ]}
        paths = cc._recorder_source_paths(index_rows)  # noqa: SLF001
        self.assertEqual(paths, frozenset({"sources/landmarks/entry-ff0adc58aac06eb7e8369678.md"}))
        # ... and nothing dated was needed for the restatement to be dropped.
        self.assertEqual(cc._recorder_dates_by_source_path(index_rows), {})  # noqa: SLF001
        self.assertTrue(cc._restates_recorded_record(  # noqa: SLF001
            [{"claim_type": "occurrence"}], source_type="landmark_entry", recorded=True))


class TheRulesAreNamedTests(unittest.TestCase):

    def test_every_rule_is_a_named_sentence(self):
        for text in (eb.A_GROUP_NEVER_TAKES_IN_ANOTHER_COUPLES_MILESTONE,
                     eb.A_MILESTONE_OF_SEVERAL_PEOPLE_IS_NOBODYS_ALONE,
                     eb.A_BIRTH_DATED_ELSEWHERE_IS_NOT_THEIRS,
                     ec.A_BARE_NAME_IN_THE_BINDER_IS_WHO_HE_CALLS_BY_IT,
                     ec.A_RELATION_WORD_WITH_ANOTHER_NAME_IS_NOT_THEM,
                     tt.A_DEATH_IS_DATED_BY_ITS_DATE,
                     ident.AN_OWNERS_POSSESSIVE_IS_HIS_MY,
                     cc.A_RECORDED_RECORD_IS_CANONICAL_DATED_OR_NOT,
                     cc.A_CARD_ANSWER_IS_READ_ONCE,
                     tt.A_PLACE_HE_WAS_ONLY_NEAR_IS_NOT_WHERE_IT_HAPPENED):
            self.assertIsInstance(text, str)
            self.assertGreater(len(text), 40)

    def test_the_rule_version_moved(self):
        self.assertEqual(tt.CALCULATION_RULE_VERSION, "timeline-rules:25")


if __name__ == "__main__":
    unittest.main()
