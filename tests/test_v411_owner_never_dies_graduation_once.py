"""v411 (owner, 2026-10-10): two binder/label rules.

1. `identity_resolution.THE_NARRATOR_IS_NOT_THE_DECEASED` — the owner never
   dies on his own timeline. Nine tellings of his FATHER's death, one of them
   ("Father died of COVID in Mesa") filed under ``subject_mention: "self"``,
   were drawn as "Your death" and raised a "your death" contradiction card.
2. `episode_binder.ONE_GRADUATION_TOLD_MANY_WAYS_IS_ONE_ROW` (rung R2e) and
   `episode_binder.A_GLUED_TELLING_LENDS_NO_YEAR` — his father's graduation,
   told six ways, is one row; a telling that glues the graduation to a job
   never carries the graduation's year to anything else.

Synthetic data only (the Hale family); NEVER references any real vault.
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
import episode_containers as ec  # noqa: E402
import identity_resolution as ir  # noqa: E402
import temporal_claims as tc  # noqa: E402
import temporal_projection as tp  # noqa: E402
import temporal_publication as pub  # noqa: E402
import temporal_timeline as tt  # noqa: E402

import test_v360_look_before_asking as lba  # noqa: E402

NOW = "2026-10-10T12:00:00Z"

#: The narrator is Sam Hale. His father Walter, whom he calls Dad, died of
#: COVID on 18 January 2021; Walter graduated college in 1987.
ROSTER = {"version": 1, "type": "person", "entities": [
    {"name": "Walter Hale", "slug": "walter-hale", "relationship": "parent",
     "aliases": ["Walter Hale (Dad)", "dad", "my dad", "father", "my father"]},
    {"name": "Irene Hale", "slug": "irene-hale", "relationship": "parent",
     "aliases": ["mom", "my mom", "mother", "my mother"]},
    {"name": "Nora Hale", "slug": "nora-hale", "relationship": "spouse",
     "aliases": ["Nora", "wife"]},
]}

DEATH_DAY = "2021-01-18"


def _date(text: str) -> dict:
    return chrono.parse_stated_date(text).to_dict()


def _all_text(projection: dict, cards: list) -> list[str]:
    texts = [str(node.get("label") or "") for node in projection["nodes"]]
    texts += [str(row.get("prompt_intent") or "") for row in cards]
    return texts


# --------------------------------------------------------------------------
# Rule 1 — the narrator is not the deceased
# --------------------------------------------------------------------------


class DeceasedNamedInTests(unittest.TestCase):

    def test_the_nine_titles_name_the_father(self):
        for title, whose in (
                ("Father died of COVID in Mesa", "Father"),
                ("Father's death", "Father"),
                ("Father dies of COVID", "Father"),
                ("Walter Hale's death", "Walter Hale"),
                ("Father's near-death and death", "Father"),
                ("Father's death on January 18, 2021", "Father"),
                ("My dad's death", "dad"),
                ("Sam's father's death", "father"),
                ("The death of Walter Hale", "Walter Hale")):
            with self.subTest(title=title):
                self.assertEqual(ir.deceased_named_in(title, owner_names=["Sam Hale", "Sam"]),
                                 whose)

    def test_the_narrator_and_non_names_name_nobody(self):
        for title in ("Nearly died in the crash", "I nearly died", "My death",
                      "Begins processing father's death years later", "Sam's death",
                      "Graduation from ASU", ""):
            with self.subTest(title=title):
                self.assertEqual(ir.deceased_named_in(title, owner_names=["Sam Hale", "Sam"]), "")

    def test_his_surname_is_not_him(self):
        """The father shares the narrator's surname; "Hale" is not the owner."""
        self.assertEqual(ir.deceased_named_in("Walter Hale's death", owner_names=["Sam Hale"]),
                         "Walter Hale")

    def test_the_roster_says_who_the_relation_word_is(self):
        self.assertEqual(ir.deceased_ref("Father", ROSTER), "person/walter-hale")
        self.assertEqual(ir.deceased_ref("Walter Hale", ROSTER), "person/walter-hale")
        bare = {"version": 1, "type": "person", "entities": [
            {"name": "Walter Hale", "slug": "walter-hale", "relationship": "father"},
            {"name": "Irene Hale", "slug": "irene-hale", "relationship": "mother"}]}
        self.assertEqual(ir.deceased_ref("Father", bare), "person/walter-hale")
        two_parents = {"version": 1, "type": "person", "entities": [
            {"name": "Walter Hale", "slug": "walter-hale", "relationship": "parent"},
            {"name": "Irene Hale", "slug": "irene-hale", "relationship": "parent"}]}
        self.assertEqual(ir.deceased_ref("Father", two_parents), "")
        self.assertEqual(ir.deceased_ref("Uncle Bert", ROSTER), "")


def _nine_tellings(vault: lba.Vault) -> dict:
    """The nine tellings of Walter's death, on one node, modelled on the shapes
    the owner's episode held — one of them filed under the narrator."""
    first = vault.claim("m1", "Dad died on January 18, 2021.", label="Father's death",
                        claim_type="date", subject="narrator's father", event_kind="death",
                        value=_date(DEATH_DAY))
    ref = first["event_ref"]
    rows = [
        ("m2", "My dad died of COVID.", "Father dies of COVID", "narrator's father", None),
        ("m3", "Walter Hale died in January 2021.", "Walter Hale's death", "Walter Hale",
         _date("2021-01")),
        ("m4", "He died of COVID in Mesa when I was 39.", "Father died of COVID in Mesa",
         "self", _date("2021")),
        ("m6", "His near-death in 2020 and then his death.", "Father's near-death and death",
         "Sam's father", None),
        ("m7", "Dad passed on January 18, 2021.", "Father's death on January 18, 2021",
         "father", _date(DEATH_DAY)),
        ("m8", "When my father died.", "Father's death", "my father", None),
        ("m9", "Dad dying of COVID changed everything.", "Father dies of COVID", "dad", None),
        ("m10", "Walter's death hit us hard.", "Walter Hale's death", "Walter Hale", None),
    ]
    for stem, body, label, subject, value in rows:
        vault.claim(stem, body, label=label, claim_type="date" if value else "occurrence",
                    subject=subject, event_kind="death", value=value, event_ref=ref)
    return first


class TheOwnerNeverDiesOnHisTimelineTests(unittest.TestCase):

    def setUp(self):
        self.vault = lba.Vault(self)
        self.vault.roster(ROSTER)
        self.vault.owner_birth()
        self.death = _nine_tellings(self.vault)
        self.vault.publish()
        self.projection = pub.read_projection(self.vault.root)
        self.cards = self.vault.cards()

    def node(self) -> dict:
        return next(n for n in self.projection["nodes"]
                    if n["node_id"] == self.death["event_ref"])

    def test_the_label_is_the_deceased_not_your_death(self):
        self.assertEqual(self.node()["label"], "Walter Hale's death")

    def test_no_your_death_anywhere(self):
        for text in _all_text(self.projection, self.cards):
            self.assertNotIn("your death", text.lower(), text)
            self.assertNotIn("did you die", text.lower(), text)

    def test_the_owner_is_not_among_the_subjects(self):
        refs = self.node()["subject_refs"]
        self.assertIn("person/walter-hale", refs)
        for owner in ("self", tt.DEFAULT_OWNER_REF):
            self.assertNotIn(owner, refs)

    def test_the_diagnostics_explain_the_re_subjecting(self):
        findings = [row for row in self.projection["diagnostics"]["findings"]
                    if row.get("finding") == tt.DIAGNOSTIC_DEATH_RESUBJECTED]
        self.assertEqual(len(findings), 1, findings)
        row = findings[0]
        self.assertEqual(row["event_mention"], "Father died of COVID in Mesa")
        self.assertEqual(row["now"], "person/walter-hale")
        self.assertEqual(row["deceased_mention"], "Father")
        self.assertTrue(row["resolved"])
        self.assertEqual(row["rule"], ir.THE_NARRATOR_IS_NOT_THE_DECEASED)


class HisOwnAgeOnHisFathersDeathStaysHisTests(unittest.TestCase):
    """"When I was like 21": an AGE filed under the narrator is his own age —
    the evidence he lived the death — and is never re-subjected to the dead
    man, while the node is still titled from the deceased."""

    def test_the_age_keeps_the_narrator_and_the_title_keeps_the_deceased(self):
        vault = lba.Vault(self)
        vault.roster(ROSTER)
        vault.owner_birth()
        death = vault.claim("d1", "Dad died on January 18, 2021.", label="Father's death",
                            claim_type="date", subject="narrator's father",
                            event_kind="death", value=_date(DEATH_DAY))
        vault.claim("d2", "What got him sick when I was like 21.",
                    label="Father died of COVID in Mesa", claim_type="age", subject="self",
                    event_kind="death", value="21", event_ref=death["event_ref"])
        vault.publish()
        projection = pub.read_projection(vault.root)
        node = next(n for n in projection["nodes"] if n["node_id"] == death["event_ref"])
        self.assertEqual(node["label"], "Walter Hale's death")
        self.assertNotIn("self", node["subject_refs"])
        self.assertFalse(any(row.get("finding") == tt.DIAGNOSTIC_DEATH_RESUBJECTED
                             for row in projection["diagnostics"]["findings"]))


class AnUnresolvedDeceasedStillDropsTheOwnerTests(unittest.TestCase):
    """No roster: "Father" names nobody the vault knows, and the owner is still
    dropped rather than kept."""

    def setUp(self):
        self.vault = lba.Vault(self)
        self.vault.owner_birth()
        self.death = self.vault.claim(
            "u1", "He died of COVID in Mesa.", label="Father died of COVID in Mesa",
            claim_type="date", subject="self", event_kind="death", value=_date(DEATH_DAY))
        self.vault.claim("u2", "Dad died in 2021.", label="Father's death", claim_type="date",
                         subject="self", event_kind="death", value=_date("2021"),
                         event_ref=self.death["event_ref"])
        self.vault.publish()
        self.projection = pub.read_projection(self.vault.root)

    def test_the_owner_is_dropped_and_the_words_are_the_subject(self):
        node = next(n for n in self.projection["nodes"]
                    if n["node_id"] == self.death["event_ref"])
        self.assertEqual(node["subject_refs"], ["Father"])
        self.assertEqual(node["label"], "Father's death")
        for text in _all_text(self.projection, self.vault.cards()):
            self.assertNotIn("your death", text.lower(), text)
        findings = [row for row in self.projection["diagnostics"]["findings"]
                    if row.get("finding") == tt.DIAGNOSTIC_DEATH_RESUBJECTED]
        self.assertEqual({row["resolved"] for row in findings}, {False})


class ADeathNamingOnlyTheNarratorTests(unittest.TestCase):

    def test_it_is_titled_and_asked_in_its_own_words(self):
        vault = lba.Vault(self)
        vault.owner_birth()
        crash = vault.claim("c1", "I nearly died in the crash.", label="Nearly died in the crash",
                            subject="self", event_kind="death")
        vault.publish()
        projection = pub.read_projection(vault.root)
        node = next(n for n in projection["nodes"] if n["node_id"] == crash["event_ref"])
        self.assertEqual(node["label"], "Nearly died in the crash")
        for text in _all_text(projection, vault.cards()):
            self.assertNotIn("your death", text.lower(), text)
            self.assertNotIn("did you die", text.lower(), text)
        self.assertIn(tt.DIAGNOSTIC_NARRATOR_DEATH_IN_ITS_OWN_WORDS,
                      {row.get("finding") for row in projection["diagnostics"]["findings"]})


def _claim(stem: str, label: str, *, subject: str, event_kind: str = "moment",
           value: object = None, source_id: str = "", claim_type: str = "") -> dict:
    node_id = tp.derive_node_id(node_kind="event", event_kind=event_kind,
                                subject_refs=[subject], discriminator=f"{stem}-{label}")
    row = {
        "source_kind": "import", "claim_type": claim_type or ("date" if value else "occurrence"),
        "subject_mention": subject, "event_kind": event_kind, "event_ref": node_id,
        "event_mention": label, "evidence": [{"quote": label}], "basis": "explicit",
        "confidence": 0.8, "extractor_version": "classifier-claims/rule:5",
        "source_ref": {"source_id": source_id or f"classification:answers-{stem}#{stem}",
                       "revision": "sha256:" + "0" * 64, "source_path": f"answers/{stem}.md"},
    }
    if value is not None:
        row["temporal_value"] = value
    return tc.validate_temporal_claim(row, now=NOW)


def _index() -> ec.EntityIndex:
    return ec.entity_index({"person": ROSTER})


class TheBinderReadsTheDeceasedTests(unittest.TestCase):

    def test_the_narrators_telling_is_about_his_father_in_the_binder(self):
        claims = [
            _claim("m4", "Father died of COVID in Mesa", subject="self", event_kind="death",
                   value=_date("2021")),
            _claim("m1", "Father's death", subject="narrator's father", event_kind="death",
                   value=_date(DEATH_DAY)),
        ]
        views = eb.telling_views(claims, entity_index=_index())
        mesa = views["classification:answers-m4#m4"]
        self.assertEqual(mesa.narrator_resubjected, "Father")
        self.assertEqual(mesa.subject_mentions, ("Father",))
        self.assertIn("person/walter-hale", mesa.subject_entities)
        links = eb.milestone_links(views)
        self.assertEqual({link.members for link in links},
                         {tuple(sorted(views))})

    def test_a_telling_about_the_narrator_is_left_alone(self):
        claims = [_claim("c1", "Nearly died in the crash", subject="self", event_kind="death")]
        view = next(iter(eb.telling_views(claims, entity_index=_index()).values()))
        self.assertEqual(view.narrator_resubjected, "")
        self.assertEqual(view.subject_mentions, ("self",))


# --------------------------------------------------------------------------
# Rule 2 — one person's graduation told six ways is one row
# --------------------------------------------------------------------------

#: The six tellings of Walter's 1987 college graduation, in the shapes the
#: owner's vault held, plus two of the narrator's own graduations.
SIX = (
    ("a", "Dad's graduation", "Dad", "moment", "1987"),
    ("b", "Dad graduated", "Dad", "graduation", "1987"),
    ("c", "Dad graduates college", "Dad", "moment", "1987"),
    ("d", "Dad graduated, got San Diego job", "narrator's family", "moment", "1987/1988"),
    ("e", "Father graduated and got San Diego job", "Father", "moment", "1987/1988-06"),
    ("f", "Father graduated and got a job", "Father", "moment", "1989-06/1990-06"),
    ("asu", "Graduation from ASU", "self", "graduation", "2013"),
    ("mit", "Graduation from MIT", "self", "graduation", "2015"),
)


def _ref(stem: str) -> str:
    return f"classification:answers-{stem}#{stem}"


def _six(rows=SIX) -> list:
    return [_claim(stem, label, subject=subject, event_kind=kind, value=_date(when))
            for stem, label, subject, kind, when in rows]


class GraduationClauseTests(unittest.TestCase):

    def test_glued_titles_are_read_as_glued(self):
        self.assertFalse(eb.graduation_clause("Dad graduated").glued)
        self.assertFalse(eb.graduation_clause("Dad's graduation").glued)
        self.assertTrue(eb.graduation_clause("Dad graduated, got San Diego job").glued)
        self.assertTrue(eb.graduation_clause("Father graduated and got a job").glued)
        self.assertFalse(eb.graduation_clause("Graduation from ASU and MIT").glued)

    def test_a_title_about_something_near_it_is_no_graduation(self):
        self.assertIsNone(eb.graduation_clause("Party after Dad's graduation"))
        self.assertIsNone(eb.graduation_clause("Started at Ridgeline"))

    def test_graduation_stays_out_of_the_once_per_subject_kinds(self):
        self.assertNotIn("graduation", ir.ONCE_PER_SUBJECT_EVENT_KINDS)
        self.assertIn(eb.RULE_ID_GRADUATION, eb.EXACT_IDENTITY_RULE_IDS)


class OneGraduationIsOneRowTests(unittest.TestCase):

    def setUp(self):
        self.views = eb.telling_views(_six(), entity_index=_index())

    def test_dad_father_and_the_roster_ref_are_one_subject(self):
        readings = eb.graduation_readings(self.views, _index())
        for stem in "abcdef":
            self.assertEqual(readings[_ref(stem)][0], "person/walter-hale", stem)
        self.assertNotIn(_ref("asu"), readings)
        self.assertNotIn(_ref("mit"), readings)

    def test_the_tellings_that_fit_1987_are_linked_pairwise(self):
        links = eb.graduation_links(self.views, index=_index())
        members = {ref for link in links for ref in link.members}
        self.assertEqual(members, {_ref(stem) for stem in "abcde"})
        self.assertEqual(len(links), 10)  # every pair of five: a clique
        self.assertEqual({link.key for link in links},
                         {"graduation:person/walter-hale:1987"})

    def test_the_plan_folds_them_into_one_group(self):
        result = eb.plan(_six(), entity_index=_index(), now=NOW)
        groups = [g for g in result.exact_groups if eb.RULE_ID_GRADUATION in g["rule_ids"]]
        self.assertEqual(len(groups), 1)
        self.assertEqual(set(groups[0]["members"]), {_ref(stem) for stem in "abcde"})

    def test_a_contradicting_year_stays_apart(self):
        """F (June 1989-June 1990) contradicts the stated 1987 and is not folded."""
        links = eb.graduation_links(self.views, index=_index())
        self.assertFalse(any(_ref("f") in link.members for link in links))

    def test_the_owners_own_graduations_are_never_folded(self):
        rows = SIX + (("asu2", "Graduation from ASU", "self", "graduation", "2013"),)
        views = eb.telling_views(_six(rows), entity_index=_index())
        links = eb.graduation_links(views, index=_index())
        for stem in ("asu", "asu2", "mit"):
            self.assertFalse(any(_ref(stem) in link.members for link in links), stem)

    def test_two_schools_in_one_year_stay_apart(self):
        rows = (("hs", "Dad graduated high school", "Dad", "graduation", "1987"),
                ("col", "Dad graduates college", "Dad", "graduation", "1987"))
        views = eb.telling_views(_six(rows), entity_index=_index())
        self.assertEqual(eb.graduation_links(views, index=_index()), [])

    def test_two_stated_years_are_two_graduations(self):
        rows = (("hs", "Dad's graduation", "Dad", "graduation", "1972"),
                ("col", "Dad graduated", "Dad", "graduation", "1987"),
                ("col2", "Dad's graduation", "Dad", "moment", "1987"))
        views = eb.telling_views(_six(rows), entity_index=_index())
        links = eb.graduation_links(views, index=_index())
        self.assertEqual({link.members for link in links},
                         {tuple(sorted((_ref("col"), _ref("col2"))))})


class AGluedTellingLendsNoYearTests(unittest.TestCase):

    def test_a_glued_telling_never_supplies_the_year(self):
        """The glued telling's single year (1988, the job's) is not the
        graduation's: with no unglued telling stating one, the rung keys by
        overlap and never by 1988."""
        rows = (("u", "Dad graduated", "Dad", "graduation", "1987/1988"),
                ("g", "Dad graduated, got San Diego job", "Dad", "moment", "1988"))
        views = eb.telling_views(_six(rows), entity_index=_index())
        links = eb.graduation_links(views, index=_index())
        self.assertEqual(len(links), 1)
        self.assertTrue(links[0].key.endswith(":overlap"), links[0].key)

    def test_a_folded_glued_telling_links_to_nothing_but_graduations(self):
        glued = frozenset({_ref("d")})
        graduations = {_ref("d"): None, _ref("b"): None}
        job = eb.ExactLink(rule_id=eb.RULE_ID_RESTATEMENT, left=_ref("d"), right=_ref("job"),
                           key="diego+job+walter", reason="x")
        same = eb.ExactLink(rule_id=eb.RULE_ID_SAME_LABEL, left=_ref("d"), right=_ref("b"),
                            key="x", reason="x")
        reading = eb.ExactLink(rule_id=eb.RULE_ID_DERIVED_READING, left=_ref("d"),
                               right=_ref("job"), key="node", reason="x")
        self.assertTrue(eb._lends_a_glued_year(job, glued, graduations))
        self.assertFalse(eb._lends_a_glued_year(same, glued, graduations))
        self.assertFalse(eb._lends_a_glued_year(reading, glued, graduations))


class TheFoldedRowIsTitledByItsCleanestTellingTests(unittest.TestCase):

    def test_dad_graduated_titles_the_row(self):
        vault = lba.Vault(self)
        vault.roster(ROSTER)
        vault.owner_birth()
        first = None
        for stem, label, subject, kind, when in SIX[:5]:
            claim = vault.claim(stem, f"{label}.", label=label, claim_type="date",
                                subject=subject, event_kind=kind, value=_date(when),
                                event_ref=first["event_ref"] if first else "")
            first = first or claim
        vault.publish()
        projection = pub.read_projection(vault.root)
        node = next(n for n in projection["nodes"] if n["node_id"] == first["event_ref"])
        self.assertEqual(node["label"], "Dad graduated")
        self.assertTrue(node["best_temporal_value"]["earliest"].startswith("1987"))


if __name__ == "__main__":
    unittest.main()
