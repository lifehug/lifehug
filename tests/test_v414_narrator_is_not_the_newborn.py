"""v414 (owner, 2026-10-10): the narrator is not the newborn.

`identity_resolution.THE_NARRATOR_IS_NOT_THE_NEWBORN`, the sibling of v411's
`THE_NARRATOR_IS_NOT_THE_DECEASED`. A birth node of the owner's son carried
subject_refs ['<son> Rex', 'person/<son>', 'self'] because three tellings
("<Son>'s birth as turning point", "<Son>'s birth during COVID isolation") were
filed under ``subject_mention: "self"``. A birth telling filed under the owner
whose own title names who was born is about that person; the owner's relation
to his child's birth is the `child_born` kind and the family axis, never
``self`` among the subjects. "I was born in Redlands" stays his own.

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
SON_BORN = "2021-10-11"

ROSTER = {"version": 1, "type": "person", "entities": [
    {"name": "Otis Hale", "slug": "otis", "relationship": "child",
     "aliases": ["Otis", "Otis Rex", "my son"]},
    {"name": "Walter Hale", "slug": "walter-hale", "relationship": "parent",
     "aliases": ["dad", "father"]},
]}


def _date(text: str) -> dict:
    return chrono.parse_stated_date(text).to_dict()


def _texts(projection: dict, cards: list) -> list[str]:
    return ([str(n.get("label") or "") for n in projection["nodes"]]
            + [str(c.get("prompt_intent") or "") for c in cards])


class NewbornNamedInTests(unittest.TestCase):

    def test_the_titles_name_the_newborn(self):
        for title, whose in (("Otis's birth as turning point", "Otis"),
                             ("Otis's birth during COVID isolation", "Otis"),
                             ("Otis Rex born", "Otis Rex"),
                             ("The birth of Otis Hale", "Otis Hale"),
                             ("My son's birth", "son")):
            with self.subTest(title=title):
                self.assertEqual(ir.newborn_named_in(title, owner_names=["Sam Hale", "Sam"]),
                                 whose)

    def test_his_own_birth_names_nobody_else(self):
        for title in ("I was born in Redlands", "Born in Redlands", "My birth",
                      "Sam's birth", "Otis's birthday party", "Birthday dinner"):
            with self.subTest(title=title):
                self.assertEqual(ir.newborn_named_in(title, owner_names=["Sam Hale", "Sam"]), "")


def _son_birth(vault: lba.Vault) -> dict:
    """The son's birth on one node: one telling under his name, two of the
    turning-point shape filed under the narrator."""
    first = vault.claim("b1", f"Otis Rex was born {SON_BORN}.", label="Otis's birth",
                        claim_type="date", subject="Otis Rex", event_kind="birth",
                        value=_date(SON_BORN))
    for stem, label in (("q3", "Otis's birth as turning point"),
                        ("q4", "Otis's birth during COVID isolation")):
        vault.claim(stem, f"{label}.", label=label, claim_type="date", subject="self",
                    event_kind="birth", value=_date("2021-10"), event_ref=first["event_ref"])
    return first


class TheNarratorIsNotTheNewbornTests(unittest.TestCase):

    def setUp(self):
        self.vault = lba.Vault(self)
        self.vault.roster(ROSTER)
        self.vault.owner_birth()
        self.son = _son_birth(self.vault)
        self.vault.publish()
        self.projection = pub.read_projection(self.vault.root)

    def node(self, node_id):
        return next(n for n in self.projection["nodes"] if n["node_id"] == node_id)

    def test_the_owner_is_not_a_subject_of_his_sons_birth(self):
        refs = self.node(self.son["event_ref"])["subject_refs"]
        self.assertIn("person/otis", refs)
        for owner in ("self", tt.DEFAULT_OWNER_REF):
            self.assertNotIn(owner, refs)

    def test_the_owner_is_a_subject_of_exactly_one_birth(self):
        births = [n for n in self.projection["nodes"]
                  if n.get("event_kind") in ("birth", "child_born")
                  and any(ref in ("self", tt.DEFAULT_OWNER_REF) for ref in n["subject_refs"])]
        self.assertEqual(len(births), 1, [n["label"] for n in births])

    def test_the_title_is_the_sons_and_never_yours(self):
        node = self.node(self.son["event_ref"])
        self.assertNotIn("your", node["label"].lower())
        for text in _texts(self.projection, self.vault.cards()):
            self.assertNotIn("your birth", text.lower().replace("your birthday", ""), text) \
                if "Otis" in text else None

    def test_the_diagnostics_explain_the_re_subjecting(self):
        rows = [r for r in self.projection["diagnostics"]["findings"]
                if r.get("finding") == tt.DIAGNOSTIC_BIRTH_RESUBJECTED]
        self.assertEqual(len(rows), 2, rows)
        self.assertEqual({r["now"] for r in rows}, {"person/otis"})
        self.assertEqual({r["rule"] for r in rows}, {ir.THE_NARRATOR_IS_NOT_THE_NEWBORN})


class HisOwnBirthStaysHisTests(unittest.TestCase):

    def test_i_was_born_in_redlands_keeps_its_subject(self):
        vault = lba.Vault(self)
        vault.roster(ROSTER)
        vault.owner_birth()
        own = vault.claim("r1", "I was born in Redlands.", label="I was born in Redlands",
                          subject="self", event_kind="birth")
        vault.publish()
        projection = pub.read_projection(vault.root)
        self.assertFalse(any(r.get("finding") == tt.DIAGNOSTIC_BIRTH_RESUBJECTED
                             for r in projection["diagnostics"]["findings"]))
        ids = {n["node_id"] for n in projection["nodes"]}
        aliases = (projection.get("node_aliases") or {})
        node_id = own["event_ref"] if own["event_ref"] in ids else aliases.get(own["event_ref"])
        node = next(n for n in projection["nodes"] if n["node_id"] == node_id)
        self.assertTrue(any(ref in ("self", tt.DEFAULT_OWNER_REF) for ref in node["subject_refs"]))


class AnUnresolvedNewbornTests(unittest.TestCase):

    def test_the_words_are_the_subject_and_the_owner_is_dropped(self):
        vault = lba.Vault(self)
        vault.owner_birth()
        birth = vault.claim("u1", "Juniper's birth changed everything.",
                            label="Juniper's birth as turning point", claim_type="date",
                            subject="self", event_kind="birth", value=_date("2019-04"))
        vault.publish()
        projection = pub.read_projection(vault.root)
        node = next(n for n in projection["nodes"] if n["node_id"] == birth["event_ref"])
        self.assertEqual(node["subject_refs"], ["Juniper"])
        rows = [r for r in projection["diagnostics"]["findings"]
                if r.get("finding") == tt.DIAGNOSTIC_BIRTH_RESUBJECTED]
        self.assertEqual([r["resolved"] for r in rows], [False])


def _claim(stem, label, *, subject, event_kind="birth", value=None):
    node_id = tp.derive_node_id(node_kind="event", event_kind=event_kind,
                                subject_refs=[subject], discriminator=f"{stem}-{label}")
    row = {"source_kind": "import", "claim_type": "date" if value else "occurrence",
           "subject_mention": subject, "event_kind": event_kind, "event_ref": node_id,
           "event_mention": label, "evidence": [{"quote": label}], "basis": "explicit",
           "confidence": 0.8, "extractor_version": "classifier-claims/rule:5",
           "source_ref": {"source_id": f"classification:answers-{stem}#{stem}",
                          "revision": "sha256:" + "0" * 64, "source_path": f"answers/{stem}.md"}}
    if value is not None:
        row["temporal_value"] = value
    return tc.validate_temporal_claim(row, now=NOW)


class TheBinderReadsTheNewbornTests(unittest.TestCase):

    def test_the_turning_point_is_about_the_son_in_the_binder(self):
        claims = [_claim("q3", "Otis's birth as turning point", subject="self",
                         value=_date("2021-10")),
                  _claim("b1", "Otis's birth", subject="Otis Rex", value=_date(SON_BORN))]
        views = eb.telling_views(claims, entity_index=ec.entity_index({"person": ROSTER}))
        view = views["classification:answers-q3#q3"]
        self.assertEqual(view.narrator_resubjected, "Otis")
        self.assertIn("person/otis", view.subject_entities)

    def test_his_own_birth_is_left_alone_in_the_binder(self):
        claims = [_claim("r1", "I was born in Redlands", subject="self")]
        view = next(iter(eb.telling_views(claims).values()))
        self.assertEqual(view.narrator_resubjected, "")


# --------------------------------------------------------------------------
# The two R2e gaps seen on the owner's vault after the v411 bindings, and
# the possible_overmerge that named nothing
# --------------------------------------------------------------------------

import temporal_store as ts  # noqa: E402

#: The father's roster row WITHOUT a "father"/"dad" alias: the shape where a
#: bare relation word resolves nothing on its own.
BARE_ROSTER = {"version": 1, "type": "person", "entities": [
    {"name": "Walter Hale", "slug": "walter-hale", "relationship": "parent",
     "aliases": ["Walter"]},
]}


def _gclaim(stem, label, *, subject, kind, when, source_id="", subject_ref=""):
    node_id = tp.derive_node_id(node_kind="event", event_kind=kind,
                                subject_refs=[subject_ref or subject], discriminator=label)
    row = {"source_kind": "import", "claim_type": "date" if when else "occurrence",
           "subject_mention": subject, "event_kind": kind, "event_ref": node_id,
           "event_mention": label, "evidence": [{"quote": label}], "basis": "explicit",
           "confidence": 0.8, "extractor_version": "classifier-claims/rule:5",
           "source_ref": {"source_id": source_id or f"classification:answers-{stem}#{stem}",
                          "revision": "sha256:" + "0" * 64, "source_path": f"answers/{stem}.md"}}
    if subject_ref:
        row["subject_ref"] = subject_ref
    if when:
        row["temporal_value"] = _date(when)
    return tc.validate_temporal_claim(row, now=NOW)


def _gref(stem):
    return f"classification:answers-{stem}#{stem}"


class AGluedTellingUnderAFamilyHandleTests(unittest.TestCase):
    """Gap 2: "Dad graduated, got San Diego job" filed under "narrator's
    family", its kind the job's. The graduation CLAUSE names Dad; the roster
    knows him by the subject of another telling of the same graduation."""

    def setUp(self):
        self.claims = [
            _gclaim("a", "Dad's graduation", subject="Walter Hale", kind="moment", when="1987"),
            _gclaim("b", "Dad graduated", subject="Walter Hale", kind="graduation", when="1987"),
            _gclaim("d", "Dad graduated, got San Diego job", subject="narrator's family",
                    kind="job", when="1987/1988"),
        ]
        self.index = ec.entity_index({"person": BARE_ROSTER})
        self.views = eb.telling_views(self.claims, entity_index=self.index)

    def test_the_glued_telling_is_read_by_its_graduation_clause(self):
        readings = eb.graduation_readings(self.views, self.index)
        self.assertEqual({ref: row[0] for ref, row in readings.items()},
                         {_gref(stem): "person/walter-hale" for stem in "abd"})

    def test_it_folds_but_never_supplies_the_year(self):
        links = eb.graduation_links(self.views, index=self.index)
        self.assertEqual({ref for link in links for ref in link.members},
                         {_gref(stem) for stem in "abd"})
        self.assertEqual({link.key for link in links},
                         {"graduation:person/walter-hale:1987"})


def _episode(claims, members):
    views = eb.telling_views(claims, entity_index=ec.entity_index({"person": ROSTER_DAD}))
    envelope = eb.group_envelope({"members": tuple(sorted(members)), "rule_ids": ("R2e",)},
                                 views=views, active={}, now=NOW)
    return {"operations": [envelope["operation"]], "bindings": envelope["bindings"]}


ROSTER_DAD = {"version": 1, "type": "person", "entities": [
    {"name": "Walter Hale", "slug": "walter-hale", "relationship": "parent",
     "aliases": ["dad", "father", "Walter"]},
    {"name": "Brittney Hale", "slug": "brittney-hale", "relationship": "sibling",
     "aliases": ["Brittney"]},
]}


class AWholeMessageTellingOfTheGraduationJoinsItsRowTests(unittest.TestCase):
    """Gap 1: the residence summary "Events: Brittney born, Kristine 10, Dad
    graduated (1987)" is ONE whole-message telling holding three events, so the
    binder can never bind it to the graduation (its kind reads as the birth and
    binding it would drag the other two along). Its graduation claim — kind
    graduation, Dad, 1987 — joins the folded row when subject, year and kind
    agree."""

    def setUp(self):
        whole = "conversation:msg-0f0f0f0f"
        self.claims = [
            _gclaim("a", "Dad's graduation", subject="Dad", kind="moment", when="1987"),
            _gclaim("b", "Dad graduates college", subject="Dad", kind="graduation",
                    when="1987"),
            _gclaim("w1", "Brittney born", subject="Brittney", kind="birth",
                    when="1987-12-17", source_id=whole),
            _gclaim("w2", "Kristine 10", subject="Kristine", kind="moment", when="1987",
                    source_id=whole),
            _gclaim("w3", "Dad graduated", subject="Dad", kind="graduation", when="1987",
                    source_id=whole, subject_ref="person/walter-hale"),
        ]
        self.loose = self.claims[-1]["event_ref"]
        self.result = tt.derive_calculated_timeline(
            {"version": ts.INDEX_VERSION, "claims": list(self.claims)},
            episode_records=_episode(self.claims, (_gref("a"), _gref("b"))),
            roster_snapshot=ROSTER_DAD, now=NOW)

    def test_the_binder_cannot_bind_the_whole_message(self):
        views = eb.telling_views(self.claims, entity_index=ec.entity_index({"person": ROSTER_DAD}))
        self.assertNotIn("conversation:msg-0f0f0f0f",
                         eb.graduation_readings(views, ec.entity_index({"person": ROSTER_DAD})))

    def test_its_graduation_claim_joins_the_folded_row(self):
        graduations = [n for n in self.result.nodes if "graduat" in str(n.get("label")).lower()]
        self.assertEqual(len(graduations), 1, [n["label"] for n in graduations])
        self.assertIn(self.loose, self.result.node_aliases)
        self.assertIn(tt.DIAGNOSTIC_GRADUATION_TELLING_FOLDED,
                      {r.get("finding") for r in self.result.diagnostics["findings"]})

    def test_the_messages_other_events_stay_where_they_are(self):
        labels = {n["label"] for n in self.result.nodes}
        self.assertTrue(any("Brittney" in label for label in labels), labels)
        self.assertTrue(any("Kristine" in label for label in labels), labels)

    def test_a_contradicting_year_does_not_join(self):
        claims = list(self.claims[:-1]) + [
            _gclaim("w3", "Dad graduated", subject="Dad", kind="graduation", when="1972",
                    source_id="conversation:msg-0f0f0f0f", subject_ref="person/walter-hale")]
        result = tt.derive_calculated_timeline(
            {"version": ts.INDEX_VERSION, "claims": claims},
            episode_records=_episode(claims, (_gref("a"), _gref("b"))),
            roster_snapshot=ROSTER_DAD, now=NOW)
        graduations = [n for n in result.nodes if "graduat" in str(n.get("label")).lower()]
        self.assertEqual(len(graduations), 2)


class APossibleOvermergeNamesItselfTests(unittest.TestCase):

    def test_the_row_names_its_episode_and_the_two_dates(self):
        claims = [_gclaim("x", "Dad graduated", subject="Dad", kind="graduation", when="1972"),
                  _gclaim("y", "Dad graduated", subject="Dad", kind="graduation", when="1987")]
        records = _episode(claims, (_gref("x"), _gref("y")))
        result = eb.plan(claims, episode_records=[*records["operations"], *records["bindings"]],
                         entity_index=ec.entity_index({"person": ROSTER_DAD}), now=NOW)
        self.assertEqual(len(result.overmerges), 1)
        row = result.overmerges[0]
        self.assertEqual(row["episode_label"], "Dad graduated")
        self.assertEqual(sorted(d["date"] for d in row["dates"]), ["1972", "1987"])
        line = next(line for line in eb.describe(result) if "⚠ possible_overmerge" in line)
        self.assertIn("Dad graduated", line)
        self.assertIn("1972", line)
        self.assertIn("1987", line)
        receipt = eb.overmerge_receipt_rows(result)
        self.assertEqual(receipt[0]["episode_label"], "Dad graduated")
        self.assertEqual(sorted(d["date"] for d in receipt[0]["dates"]), ["1972", "1987"])


if __name__ == "__main__":
    unittest.main()
