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


if __name__ == "__main__":
    unittest.main()
