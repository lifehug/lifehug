"""v386 (ADR 0043) — one person, one record.

lifehug-platform `docs/design/identity.md` §8 promises P1, P2, P8–P13, each
by name. Every fixture here is SYNTHETIC: the SHAPES of the hard cases (three
people sharing a first name across three generations; two children sharing a
role; a state holding three cities; two names for one object; a grandmother and
an unrecorded friend sharing a nickname, and a house named after the friend)
with invented names. Nothing is copied from any real vault.
"""

from __future__ import annotations

import copy
import io
import json
import sys
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "system"))
sys.path.insert(0, str(ROOT / "tests"))

import entity_roster  # noqa: E402
import entity_verdict  # noqa: E402
import identity_resolution as ir  # noqa: E402
import recommend_focuses  # noqa: E402
import roster_relations as rr  # noqa: E402
import wiki_compile  # noqa: E402
from test_focus_duplicate_curation import FixtureBase  # noqa: E402


def born(year: int) -> dict:
    return {"best": str(year), "earliest": str(year), "latest": str(year), "basis": "stated"}


def person(name: str, slug: str, *, relationship: str | None = None, aliases=(),
           **extra) -> dict:
    row = {"name": name, "slug": slug, "aliases": list(aliases), "qualifies": True,
           "score": 0.0, "unique_answers": 0, "page_eligible": False}
    if relationship:
        row["relationship"] = relationship
    row.update(extra)
    return row


def pell_family() -> dict:
    """Three Walters across three generations, two sons, a mother, a wife."""
    return {"version": 1, "type": "person", "entities": [
        person("Walter Ames Pell Sr", "walter-ames-pell-sr", relationship="grandparent",
               aliases=["Grandpa Walt"], relation_gender="male", born=born(1931)),
        person("Walter Pell", "walter-pell", relationship="parent", aliases=["Dad"],
               born=born(1956)),
        person("Nora Pell", "nora-pell", relationship="parent", aliases=["Mom"]),
        person("Walter Finch Pell", "walter-finch-pell", relationship="child",
               relation_gender="male", born=born(2012)),
        person("Otto Lane Pell", "otto-lane-pell", relationship="child",
               relation_gender="male", born=born(2016)),
        person("Mara Quill", "mara-quill", relationship="spouse", aliases=["Mara"]),
    ]}


def legacy_founder_shaped() -> dict:
    """The pre-v386 shape: `maps_to_focus` meaning two things, placeholder
    rows, a set-valued role word as an alias of one child."""
    roster = copy.deepcopy(pell_family())
    for row in roster["entities"]:
        row["maps_to_focus"] = None
    rows = {r["slug"]: r for r in roster["entities"]}
    rows["walter-pell"]["maps_to_focus"] = "dad"            # a Focus
    rows["nora-pell"]["maps_to_focus"] = "mom"              # a Focus
    rows["walter-finch-pell"]["aliases"] = ["my son"]       # a set word on one child
    roster["entities"] += [
        person("Walt", "walt", relationship="parent", maps_to_focus="walter-pell"),  # a fold
        person("Son", "son", aliases=["my son", "my son Otto"], unique_answers=4,
               maps_to_focus=None),
        person("Kids", "kids", aliases=["the kids"], unique_answers=7, maps_to_focus=None),
    ]
    return roster


# --------------------------------------------------------------------------
# P1 — a record with a Focus is a person, and it is covered
# --------------------------------------------------------------------------


class FocusRefIsNotAnAliasRow(unittest.TestCase):

    def test_focus_ref_is_not_an_alias_row(self):
        roster = pell_family()
        roster["entities"][1]["focus"] = "dad"
        self.assertFalse(ir.is_alias_row(roster["entities"][1]))
        self.assertIn("person/walter-pell", ir.roster_index(roster).refs)
        self.assertTrue(ir.is_alias_row({"name": "Walt", "folded_into": "walter-pell"}))
        # The legacy overload is gone: a Focus-mapped legacy row stays a person.
        legacy = legacy_founder_shaped()
        index = ir.roster_index(legacy)
        self.assertIn("person/walter-pell", index.refs)
        self.assertIn("person/nora-pell", index.refs)
        self.assertNotIn("person/walt", index.refs)  # a fold is still a pointer

    def test_page_eligible_reads_focus_and_folded_into(self):
        for home in ({"focus": "dad"}, {"folded_into": "walter-pell"}):
            with self.subTest(home=home):
                self.assertFalse(entity_roster.base_page_eligible(
                    "person", True, ir.roster_home(home), 99.0, 9, 8.0, 2))
        self.assertTrue(entity_roster.base_page_eligible(
            "person", True, ir.roster_home({"focus": None, "folded_into": None}), 99.0, 9, 8.0, 2))


class RecommendResolvesFirst(FixtureBase):
    """P1 + P2 through the real `recommend()`."""

    def setUp(self):
        super().setUp()
        self._saved[(entity_roster, "QUESTIONS_FILE")] = entity_roster.QUESTIONS_FILE
        qbank = self._write("question-bank.md", (
            "## A: Origins\n- [x] A1: Earliest? *(2026-01-01)*\n\n"
            "## Focus Categories\n\n## K: Focus — Dad\n- [ ] K1: What did he teach you?\n"))
        for module in (recommend_focuses, entity_roster):
            module.QUESTIONS_FILE = qbank
        import lifehug_core  # noqa: PLC0415
        lifehug_core.QUESTIONS_FILE = qbank
        self._set_roster("person", pell_family()["entities"])

    def _recommend(self, stats: dict) -> list[dict]:
        with mock.patch.object(recommend_focuses, "_build_entity_stats", return_value=stats):
            return recommend_focuses.recommend(min_score=0.0, filter_type="person")

    @staticmethod
    def _stat(qids) -> dict:
        return {"mention_count": 6, "answers": set(qids), "categories": {"A"},
                "emotional_weight": 2.0, "evidence": ["ev"]}

    def test_recommend_skips_resolved_focus_person(self):
        recs = self._recommend({
            ("person", "Walter Pell"): self._stat({"A1", "A2", "A3"}),
            ("person", "Otto"): self._stat({"A4", "A5", "A6"}),
        })
        entities = {r["entity"] for r in recs}
        # Walter Pell has no `focus` on disk; the Focus "Dad" attaches to him by
        # his alias, so he is covered and never recommended.
        self.assertNotIn("Walter Pell", entities)
        otto = next(r for r in recs if r["entity"] == "Otto")
        self.assertEqual(otto["resolved_ref"], "person/otto-lane-pell")
        self.assertEqual(otto["resolved_name"], "Otto Lane Pell")

    def test_owner_possessive_resolves(self):
        found = ir.resolve_person("Author's father", pell_family())
        self.assertEqual((found.kind, found.ref), ("resolved", "person/walter-pell"))
        recs = self._recommend({("person", "Author's father"): self._stat({"A1", "A2", "A3"})})
        self.assertEqual([r["entity"] for r in recs], [])

    def test_approve_refuses_a_twin(self):
        self._set_recs([{"id": "rec-authors-father", "entity": "Author's father",
                         "type": "person", "score": 9.0, "status": "pending"}])
        with redirect_stderr(io.StringIO()) as err, redirect_stdout(io.StringIO()):
            self.assertFalse(recommend_focuses.approve_recommendation("rec-authors-father"))
        self.assertIn("refusing a twin", err.getvalue())


# --------------------------------------------------------------------------
# P8 — the converter is byte-stable and loses nothing
# --------------------------------------------------------------------------


class IdentityConverter(unittest.TestCase):

    def test_identity_converter_idempotent(self):
        legacy = legacy_founder_shaped()
        once, report = rr.convert_legacy_roster(copy.deepcopy(legacy))
        twice, again = rr.convert_legacy_roster(copy.deepcopy(once))
        self.assertTrue(report["changed"])
        self.assertFalse(again["changed"])
        self.assertEqual(json.dumps(once, sort_keys=True), json.dumps(twice, sort_keys=True))
        rows = {r["slug"]: r for r in once["entities"]}
        for row in once["entities"]:
            self.assertNotIn("maps_to_focus", row)
        # Every maps_to_focus value landed in exactly one of the two refs.
        self.assertEqual(rows["walter-pell"]["focus"], "dad")
        self.assertEqual(rows["nora-pell"]["focus"], "mom")
        self.assertEqual(rows["walt"]["folded_into"], "walter-pell")
        self.assertIsNone(rows["walt"]["focus"])
        # Retired rows are carried whole; a stripped alias is recorded.
        queries = {q["relationship"]: q for q in once[ir.RELATION_QUERIES_KEY]}
        self.assertEqual({r["slug"] for r in queries["child"]["former_rows"]}, {"son", "kids"})
        self.assertEqual(queries["child"]["mentions"], 11)
        self.assertIn({"slug": "walter-finch-pell", "alias": "my son"},
                      queries["child"]["stripped_from"])
        self.assertNotIn("my son", rows["walter-finch-pell"]["aliases"])

    def test_the_persisted_converter_writes_once(self):
        tmp = Path(self.enterContext(_tmpdir()))
        with mock.patch.object(entity_roster, "ENTITY_DIR", tmp):
            (tmp / "person.json").write_text(json.dumps(legacy_founder_shaped()), encoding="utf-8")
            first = entity_roster.convert_identity(focus_map={"dad": "Dad", "mom": "Mom"})
            once = (tmp / "person.json").read_bytes()
            second = entity_roster.convert_identity(focus_map={"dad": "Dad", "mom": "Mom"})
            self.assertTrue(first["person"]["changed"])
            self.assertFalse(second["person"]["changed"])
            self.assertEqual(once, (tmp / "person.json").read_bytes())


def _tmpdir():
    import tempfile  # noqa: PLC0415
    return tempfile.TemporaryDirectory()


# --------------------------------------------------------------------------
# P9 — three records named Walter
# --------------------------------------------------------------------------


class ThreeWalters(unittest.TestCase):
    """The design's three-Jameses case, with invented names."""

    def test_three_jameses(self):
        roster = pell_family()

        def resolve(text, **context):
            return ir.resolve_person(text, roster, context=context or None)

        self.assertEqual(resolve("my dad Walter").ref, "person/walter-pell")
        self.assertEqual(resolve("Walter Sr").ref, "person/walter-ames-pell-sr")
        self.assertEqual(resolve("my son Walter").ref, "person/walter-finch-pell")
        bare = resolve("Walter")
        self.assertEqual(bare.kind, "ambiguous")
        self.assertEqual({c["ref"] for c in bare.candidates},
                         {"person/walter-pell", "person/walter-ames-pell-sr",
                          "person/walter-finch-pell"})
        # Context splits the collision; it never picks without it.
        self.assertEqual(resolve("Walter", clause="my dad Walter drove").ref, "person/walter-pell")
        self.assertEqual(resolve("Walter", year=2012).ref, "person/walter-finch-pell")
        # No surface prints a bare "Walter …" for any of them.
        shown = {r["slug"]: ir.display_name(r, roster) for r in roster["entities"]}
        self.assertEqual(shown["walter-pell"], "Walter Pell (father)")
        self.assertEqual(shown["walter-finch-pell"], "Walter Finch Pell (son)")
        self.assertEqual(shown["walter-ames-pell-sr"], "Walter Ames Pell Sr (grandfather)")
        self.assertEqual(shown["mara-quill"], "Mara Quill")

    def test_focus_category_splits_a_collision(self):
        roster = pell_family()
        roster["entities"][1]["focus"] = "dad"
        found = ir.resolve_person("Walter", roster, context={"focus_category": "Dad"})
        self.assertEqual(found.ref, "person/walter-pell")


# --------------------------------------------------------------------------
# P10 — relations are sets
# --------------------------------------------------------------------------


class RelationSets(unittest.TestCase):

    def test_relation_sets(self):
        converted, report = rr.convert_legacy_roster(legacy_founder_shaped())
        names = {r["name"] for r in converted["entities"]}
        self.assertNotIn("Son", names)
        self.assertNotIn("Kids", names)
        son = ir.resolve_person("my son", converted)
        self.assertEqual(son.kind, "ambiguous")
        self.assertEqual({c["ref"] for c in son.candidates},
                         {"person/walter-finch-pell", "person/otto-lane-pell"})
        self.assertEqual(ir.resolve_person("my son Otto", converted).ref, "person/otto-lane-pell")
        # The placeholder's first-name-bearing spelling went to the record it names.
        self.assertIn({"alias": "my son Otto", "ref": "person/otto-lane-pell"}, report["reattributed"])
        self.assertTrue(ir.is_placeholder_name("Siblings"))
        self.assertTrue(ir.is_placeholder_name("Friend"))
        self.assertFalse(ir.is_placeholder_name("Mom"))
        self.assertEqual(ir.relation_cardinality("my wife"), 1)
        self.assertIsNone(ir.relation_cardinality("son"))
        self.assertEqual(ir.relation_cardinality("maternal grandmother"), 1)


# --------------------------------------------------------------------------
# P11 — places nest
# --------------------------------------------------------------------------


def places() -> dict:
    def place(name, slug, kind, parent=None, aliases=()):
        row = {"name": name, "slug": slug, "aliases": list(aliases), "qualifies": True,
               "place_kind": kind, "page_eligible": True, "score": 0.0, "unique_answers": 0}
        if parent:
            row["located_in"] = f"place/{parent}"
        return row
    return {"version": 1, "type": "place", "entities": [
        place("California", "california", "region", aliases=["CA"]),
        place("Yucaipa", "yucaipa", "city", "california"),
        place("Santa Clara", "santa-clara", "city", "california"),
        place("Irvine", "irvine", "city"),
        place("Ivy Lane house", "ivy-lane-house", "residence", "yucaipa"),
    ]}


class PlaceContainment(unittest.TestCase):

    def test_place_containment_join(self):
        tmp = Path(self.enterContext(_tmpdir()))
        with mock.patch.object(entity_roster, "ENTITY_DIR", tmp):
            (tmp / "place.json").write_text(json.dumps(places()), encoding="utf-8")
            with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                code = entity_verdict.main(["place", "irvine", "clear", "--located-in", "california"])
            self.assertEqual(code, 0)
            before = (tmp / "place.json").read_bytes()
            with self.assertRaises(entity_verdict.EntityVerdictError):
                entity_verdict.apply_verdict("place", "yucaipa", "clear", fold_into="california")
            self.assertEqual(before, (tmp / "place.json").read_bytes())
            roster = entity_roster.load_roster("place")
        self.assertEqual(ir.resolve_place("California", roster).ref, "place/california")
        self.assertEqual(ir.resolve_place("Yucaipa", roster).ref, "place/yucaipa")
        self.assertEqual(ir.resolve_place("Yucaipa, California", roster).ref, "place/yucaipa")
        self.assertEqual(ir.resolve_place("Riverside", roster).kind, "unknown")
        answers = {"A1": {"id": "A1", "source": "answers/A1.md", "body": "We left California"},
                   "A2": {"id": "A2", "source": "answers/A2.md", "body": "California again"}}
        descs = wiki_compile.plan_entities("place", answers, {}, roster, set())
        page = next(d for d in descs if d["slug"] == "california")
        self.assertEqual(page["contains"], ["- Yucaipa", "  - Ivy Lane house",
                                            "- Santa Clara", "- Irvine"])
        # A mention of the state never counts for the cities inside it.
        yucaipa = [d for d in descs if d["slug"] == "yucaipa"]
        self.assertEqual(yucaipa, [])


# --------------------------------------------------------------------------
# P12 — objects fold
# --------------------------------------------------------------------------


class ObjectFold(unittest.TestCase):

    def test_object_fold(self):
        tmp = Path(self.enterContext(_tmpdir()))
        objects = {"version": 1, "type": "object", "entities": [
            {"name": "The Orange Shorts", "slug": "the-orange-shorts", "aliases": [],
             "qualifies": True, "page_eligible": True},
            {"name": "One Pair Of Clothes", "slug": "one-pair-of-clothes", "aliases": [],
             "qualifies": True, "page_eligible": True},
        ]}
        with mock.patch.object(entity_roster, "ENTITY_DIR", tmp):
            (tmp / "object.json").write_text(json.dumps(objects), encoding="utf-8")
            entity_verdict.apply_verdict("object", "one-pair-of-clothes", "clear",
                                         fold_into="the-orange-shorts")
            roster = entity_roster.load_roster("object")
        rows = {r["slug"]: r for r in roster["entities"]}
        self.assertEqual(rows["one-pair-of-clothes"]["folded_into"], "the-orange-shorts")
        self.assertIn("One Pair Of Clothes", rows["the-orange-shorts"]["aliases"])
        answers = {"A1": {"id": "A1", "source": "answers/A1.md", "body": "the orange shorts"},
                   "A2": {"id": "A2", "source": "answers/A2.md", "body": "one pair of clothes"}}
        descs = wiki_compile.plan_entities("object", answers, {}, roster, set())
        self.assertEqual([d["slug"] for d in descs], ["the-orange-shorts"])
        self.assertEqual(set(descs[0]["sources"]), {"answers/A1.md", "answers/A2.md"})


# --------------------------------------------------------------------------
# P13 — a shared alias without a record; and the handle (§4.1.4b)
# --------------------------------------------------------------------------


def with_grandmother() -> dict:
    roster = pell_family()
    roster["entities"].append(person(
        "Ruthie Mae Pell", "ruthie-mae-pell", relationship="grandparent",
        aliases=["Grandma RM", "Ruthie Mae", "RM"], relation_gender="female"))
    return roster


class SharedAliasWithoutARecord(unittest.TestCase):

    def test_shared_alias_without_a_record(self):
        tmp = Path(self.enterContext(_tmpdir()))
        with mock.patch.object(entity_roster, "ENTITY_DIR", tmp):
            (tmp / "person.json").write_text(json.dumps(with_grandmother()), encoding="utf-8")
            with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                code = entity_verdict.main(["person", "ruthie-mae-pell", "clear",
                                            "--share-alias", "RM", "--with", "a friend (no record)"])
            self.assertEqual(code, 0)
            roster = entity_roster.load_roster("person")
        self.assertEqual(len(roster["entities"]), len(with_grandmother()["entities"]))
        self.assertEqual(ir.resolve_person("Grandma RM", roster).ref, "person/ruthie-mae-pell")
        bare = ir.resolve_person("RM", roster)
        self.assertEqual(bare.kind, "ambiguous")
        self.assertEqual(bare.reason, "shared_alias")
        house = ir.resolve_person("RM's house", roster)
        self.assertEqual((house.kind, house.reason), ("unknown", "place_mention"))
        # The claim path holds it too: never attributed.
        record = ir.resolve_mention("RM", roster=roster, evidence_ref="answer:A1")
        self.assertEqual(record.resolution, "uncertain")
        meta = ir.alias_meta_of(
            next(r for r in roster["entities"] if r["slug"] == "ruthie-mae-pell"), "RM")
        self.assertEqual(meta, {"exclusive": False, "shared_with": "a friend (no record)",
                                "handle": False})

    def test_a_handle_is_exclusive(self):
        roster = with_grandmother()
        filed = rr.alias_decision("person", "person/mara-quill", "mq", roster, handle=True)
        self.assertTrue(filed["applied"])
        mara = rr.find_by_ref("person", filed["snapshot"], "person/mara-quill")
        self.assertEqual(ir.record_view(mara, filed["snapshot"])["short_handle"], "@mq")
        self.assertEqual(ir.record_view(mara, filed["snapshot"])["handle"], "@mara-quill")
        self.assertEqual(ir.record_view(mara, filed["snapshot"])["display_name"], "Mara Quill")
        # Another record's alias, name or slug can never become a handle.
        for taken in ("RM", "Mara", "walter-pell"):
            with self.subTest(taken=taken):
                refused = rr.alias_decision("person", "person/otto-lane-pell", taken,
                                            filed["snapshot"], handle=True)
                self.assertFalse(refused["applied"])


class RetractAndDeprecation(unittest.TestCase):

    def test_retract_alias_and_maps_to_is_rewritten(self):
        tmp = Path(self.enterContext(_tmpdir()))
        roster = pell_family()
        roster["entities"].append(person("Walt", "walt"))
        with mock.patch.object(entity_roster, "ENTITY_DIR", tmp), \
                mock.patch.object(entity_verdict, "_focus_map", return_value={"dad": "Dad"}):
            (tmp / "person.json").write_text(json.dumps(roster), encoding="utf-8")
            entity_verdict.apply_verdict("person", "mara-quill", "clear", retract_aliases=["Mara"])
            err = io.StringIO()
            with redirect_stdout(io.StringIO()), redirect_stderr(err):
                code = entity_verdict.main(["person", "walt", "clear", "--maps-to", "walter-pell"])
            self.assertEqual(code, 0)
            self.assertIn("deprecated", err.getvalue())
            # A Focus another record already holds is a twin — refused.
            entity_verdict.apply_verdict("person", "walter-pell", "clear", focus="dad")
            with self.assertRaises(entity_verdict.EntityVerdictError):
                entity_verdict.apply_verdict("person", "otto-lane-pell", "clear", focus="dad")
            rows = {r["slug"]: r for r in entity_roster.load_roster("person")["entities"]}
        self.assertEqual(rows["mara-quill"]["aliases"], [])
        self.assertEqual(rows["walt"]["folded_into"], "walter-pell")
        self.assertEqual(rows["walter-pell"]["focus"], "dad")
        self.assertIn("person/walter-pell", ir.roster_index({"entities": list(rows.values())}).refs)


if __name__ == "__main__":
    unittest.main()
