"""v383 — the roster is the identity ledger (ADR 0041).

Promises (lifehug-platform `docs/pr-specs/roster/00-roster-identity.md` §6):

  P1 `test_entity_verdict_fold_keeps_pointer` — a fold never deletes a row:
     after `--maps-to`, the loser exists with `maps_to_focus == survivor`.
  P2 `test_alias_collision_refuses_whole_verdict` — an alias claimed by two
     rows binds to neither; the verdict exits 2 naming both, roster untouched.
  P3 `test_partnership_name_folds_as_alias` — a `partnerships` name the roster
     already answers to by first token joins that row as an alias; nothing is
     minted. Two rows sharing the first token are contested, never guessed.
  P4 `test_recount_idempotent_and_model_free` — `--recount` is byte-identical
     when run twice and never reaches a model.

Everything here is synthetic — a throwaway roster/vault per test, never the
founder vault. The fixture SHAPES are the founder's (a `Katie Taylor` row with
`wife`/`my wife` aliases, source `landmark:family`; a one-line `partnerships`
entry naming her in full).
"""

from __future__ import annotations

import contextlib
import importlib
import io
import json
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "system"))
sys.path.insert(0, str(ROOT / "tests"))

from tempdirs import root_parent_tmp  # noqa: E402

import entity_roster  # noqa: E402
import entity_verdict  # noqa: E402
import landmark_projection  # noqa: E402
import temporal_publication  # noqa: E402,F401 — bound to the real vault before any test redirects it
import temporal_store  # noqa: E402,F401


def _row(name: str, *, slug: str | None = None, aliases=(), **extra) -> dict:
    out = {"name": name, "slug": slug or entity_roster.slugify(name), "aliases": list(aliases),
           "qualifies": True, "maps_to_focus": None, "score": 0.0, "unique_answers": 0,
           "page_eligible": False}
    out.update(extra)
    return out


def _katie(*, aliases=("wife", "my wife"), **extra) -> dict:
    return _row("Katie Taylor", aliases=aliases, qualifies=False,
                relationship="spouse", source="landmark:family", **extra)


def _partnership(who: str = "Katie Ann Merrill") -> dict:
    """One `landmark_projection.load_landmark_sources` row in the shape the
    founder's 2026-08-25 wedding entry promoted:
    `{"domain":"partnerships","label":"Katie Ann Merrill","who":"Katie Ann Merrill"}`
    — its date is the WEDDING, never a birthday."""
    return {"source_id": "landmark:entry-1b65b472b6fb39cba03de385", "domain": "partnerships",
            "entry_key": who.lower(), "ordinal": 7,
            "record": {"domain": "partnerships", "label": who, "who": who,
                       "date": {"best": "2007-01-11", "earliest": "2007-01-11",
                                "latest": "2007-01-11", "granularity": "day",
                                "basis": "stated", "confidence": "certain"}}}


class _RosterDir(unittest.TestCase):
    """A throwaway `state/entity_rosters/` the production writer really writes."""

    def setUp(self) -> None:
        self.tmp = root_parent_tmp(self, ROOT, prefix="lifehug-v383-roster-")
        saved_dir = entity_roster.ENTITY_DIR
        entity_roster.ENTITY_DIR = self.tmp / "state" / "entity_rosters"
        self.addCleanup(setattr, entity_roster, "ENTITY_DIR", saved_dir)
        # The CLI's post-verdict recount reads the vault's detectors; a test
        # roster has no vault behind it, so it counts nothing — hermetically.
        patcher = mock.patch.object(entity_roster, "recount_stats", return_value={})
        patcher.start()
        self.addCleanup(patcher.stop)

    def _seed(self, *rows: dict) -> None:
        entity_roster.write_roster("person", [dict(r) for r in rows])

    def _bytes(self) -> bytes:
        return entity_roster.roster_file("person").read_bytes()

    def _rows(self) -> dict[str, dict]:
        return {e["slug"]: e for e in entity_roster.load_roster("person")["entities"]}

    def _cli(self, *argv: str) -> tuple[int, str, str]:
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = entity_verdict.main(list(argv))
        return code, out.getvalue(), err.getvalue()


# --------------------------------------------------------------------------
# D1 — every alias entity-verdict writes is a decision under the collision rule
# --------------------------------------------------------------------------


class FoldKeepsThePointer(_RosterDir):

    def test_entity_verdict_fold_keeps_pointer(self) -> None:
        """P1: the loser keeps its row; `maps_to_focus` names the survivor; the
        survivor answers to the loser's name and aliases. Re-running the same
        fold is a byte-identical no-op."""
        self._seed(_row("James", aliases=["Jimmy"]), _row("Anthon James Taylor"))
        code, _, err = self._cli("person", "james", "clear", "--maps-to", "anthon-james-taylor")
        self.assertEqual(code, 0, err)
        rows = self._rows()
        self.assertIn("james", rows, "a fold never deletes the loser's row")
        # v386 (ADR 0043): the deprecated --maps-to naming a ROW is the fold.
        self.assertEqual(rows["james"]["folded_into"], "anthon-james-taylor")
        self.assertNotIn("maps_to_focus", rows["james"])
        self.assertEqual(rows["anthon-james-taylor"]["aliases"], ["James", "Jimmy"])
        self.assertIsNone(rows["anthon-james-taylor"].get("folded_into"))
        first = self._bytes()
        code, _, _ = self._cli("person", "james", "clear", "--maps-to", "anthon-james-taylor")
        self.assertEqual(code, 0)
        self.assertEqual(self._bytes(), first)

    def test_a_pointer_already_folded_into_the_target_is_not_a_rival(self) -> None:
        """A row already folded INTO the survivor answers to the same person —
        adding its spelling again is idempotent, never a collision."""
        self._seed(_row("Jim", maps_to_focus="jim-reynolds"),
                   _row("Jim Reynolds", aliases=["Jim"]))
        entity = entity_verdict.apply_verdict("person", "jim-reynolds", "clear", aliases=["Jim"])
        self.assertEqual(entity["aliases"], ["Jim"])


class AliasCollisionRefusesTheWholeVerdict(_RosterDir):

    def test_alias_collision_refuses_whole_verdict(self) -> None:
        """P2, proven to fire: a THIRD row already answers to "Jimmy". Folding
        `synthetic-jim` (alias Jimmy) into `synthetic-jim-reynolds` would hand
        "Jimmy" to a second entity — the whole verdict refuses, exit 2, both
        claimants named, and the roster file is byte-for-byte unchanged (no
        partial union of the loser's name, no pointer written)."""
        self._seed(_row("Synthetic Jim", aliases=["Jimmy"]),
                   _row("Synthetic Jim Reynolds"),
                   _row("James Ortega", aliases=["Jimmy"]))
        before = self._bytes()
        code, out, err = self._cli("person", "synthetic-jim", "clear",
                                   "--maps-to", "synthetic-jim-reynolds")
        self.assertEqual(code, entity_verdict.EXIT_IDENTITY_UNCERTAIN)
        self.assertEqual(code, 2)
        self.assertEqual(self._bytes(), before)
        result = json.loads(out)
        self.assertIs(result["applied"], False)
        self.assertEqual(result["reason"], "identity_uncertain")
        self.assertEqual(result["alias"], "Jimmy")
        self.assertEqual({c["ref"] for c in result["candidates"]},
                         {"person/synthetic-jim-reynolds", "person/james-ortega"})
        self.assertIn("contested", err)

    def test_a_direct_alias_collision_refuses_too(self) -> None:
        self._seed(_katie(), _row("Katie Ann Merrill"))
        before = self._bytes()
        code, out, _ = self._cli("person", "katie-taylor", "clear",
                                 "--alias", "Grandma K", "--alias", "Katie Ann Merrill")
        self.assertEqual(code, 2)
        self.assertEqual(self._bytes(), before, "no partial union — Grandma K is not written")
        self.assertEqual({c["ref"] for c in json.loads(out)["candidates"]},
                         {"person/katie-taylor", "person/katie-ann-merrill"})

    def test_the_library_raises_the_typed_refusal(self) -> None:
        self._seed(_katie(), _row("Katie Ann Merrill"))
        with self.assertRaises(entity_verdict.EntityAliasContested) as caught:
            entity_verdict.apply_verdict("person", "katie-taylor", "clear",
                                         aliases=["katie ann merrill."])
        self.assertEqual(caught.exception.result["reason"], "identity_uncertain")

    def test_an_idempotent_readd_stays_a_success(self) -> None:
        self._seed(_katie())
        code, _, err = self._cli("person", "katie-taylor", "clear", "--alias", "My Wife")
        self.assertEqual(code, 0, err)
        self.assertEqual(self._rows()["katie-taylor"]["aliases"], ["wife", "my wife"])

    def test_an_owner_verdict_rides_through_an_alias(self) -> None:
        self._seed(_katie(owner_verdict="graduate", page_eligible=True))
        entity_verdict.apply_verdict("person", "katie-taylor", "graduate",
                                     aliases=["Katie Ann Merrill"])
        row = self._rows()["katie-taylor"]
        self.assertEqual(row["owner_verdict"], "graduate")
        self.assertIn("Katie Ann Merrill", row["aliases"])


# --------------------------------------------------------------------------
# D2 — partnerships reach the roster; a known name folds as an alias
# --------------------------------------------------------------------------


class PartnershipsFoldAsAnAlias(unittest.TestCase):

    def test_the_plan_folds_rather_than_mints(self) -> None:
        roster = {"entities": [_katie()]}
        plan = entity_roster.landmark_introduction_plan([_partnership()], roster=roster)
        self.assertEqual(plan["mint"], [])
        self.assertEqual(plan["contested"], [])
        self.assertEqual(len(plan["fold"]), 1)
        fold = plan["fold"][0]
        self.assertEqual(fold["slug"], "katie-taylor")
        self.assertEqual(fold["aliases"], ["Katie Ann Merrill"])
        self.assertEqual(fold["match"], "first_token")
        self.assertEqual(
            entity_roster.landmark_relationship_introductions([_partnership()], roster=roster), ())

    def test_two_rows_sharing_the_first_token_are_contested(self) -> None:
        roster = {"entities": [_katie(), _row("Katie Rose Holt", relationship="friend")]}
        plan = entity_roster.landmark_introduction_plan([_partnership()], roster=roster)
        self.assertEqual(plan["fold"], [])
        self.assertEqual(plan["mint"], [])
        self.assertEqual(len(plan["contested"]), 1)
        self.assertEqual(plan["contested"][0]["reason"], "identity_uncertain")
        self.assertEqual({c["slug"] for c in plan["contested"][0]["candidates"]},
                         {"katie-taylor", "katie-rose-holt"})

    def test_a_row_stating_a_different_relationship_is_never_folded(self) -> None:
        """A father "James Taylor" is not the son "James Everett Taylor"."""
        roster = {"entities": [_row("James Everett Taylor", relationship="child")]}
        entry = {"source_id": "landmark:entry-dad", "domain": "family", "ordinal": 1,
                 "record": {"domain": "family", "who": "James Taylor", "label": "James Taylor",
                            "relation": "parent"}}
        plan = entity_roster.landmark_introduction_plan([entry], roster=roster)
        self.assertEqual((plan["fold"], plan["mint"]), ([], []))
        self.assertEqual(plan["contested"][0]["reason"], "relationship_differs")

    def test_a_new_partner_mints_a_spouse_row_never_born_on_the_wedding_day(self) -> None:
        rows = entity_roster.landmark_relationship_introductions(
            [_partnership("Robin Ann Hale")], roster={"entities": []})
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["relationship"], "spouse")
        self.assertNotIn("born", rows[0])


class PartnershipFoldsThroughTheDailyStep(unittest.TestCase):
    """`entity-roster --ensure-introduced` — the seat the platform's daily
    `roster_introductions` step already invokes."""

    def setUp(self) -> None:
        import lifehug_core  # noqa: PLC0415

        self.root = root_parent_tmp(self, ROOT, prefix="lifehug-v383-introduce-")
        (self.root / "system").mkdir(parents=True, exist_ok=True)
        (self.root / "state" / "entity_rosters").mkdir(parents=True, exist_ok=True)
        (self.root / "profile.yaml").write_text("name: Dave\n", encoding="utf-8")
        self.path = self.root / "state" / "entity_rosters" / "person.json"
        for module, name, value in ((lifehug_core, "REPO_DIR", self.root),
                                    (entity_roster, "ENTITY_DIR", self.path.parent)):
            saved = getattr(module, name)
            setattr(module, name, value)
            self.addCleanup(setattr, module, name, saved)

    def _run(self, roster_rows, entries, *, dry_run=False) -> dict:
        self.path.write_text(json.dumps({"version": 1, "type": "person",
                                         "entities": roster_rows}), encoding="utf-8")
        with mock.patch.object(landmark_projection, "load_landmark_sources",
                               return_value=list(entries)), \
                mock.patch.object(entity_roster, "recount_stats", return_value={}):
            result = entity_roster.ensure_introduced_relatives(dry_run=dry_run)
        result["roster"] = json.loads(self.path.read_text(encoding="utf-8"))
        return result

    def test_partnership_name_folds_as_alias(self) -> None:
        """P3, the founder's own shape: `Katie Taylor` (wife, my wife,
        landmark:family) + `partnerships: Katie Ann Merrill` → the row gains the
        alias, nothing is minted, and a second run converges."""
        result = self._run([_katie()], [_partnership()])
        rows = {r["slug"]: r for r in result["roster"]["entities"]}
        self.assertEqual(set(rows), {"katie-taylor"}, "nothing is minted")
        self.assertEqual(rows["katie-taylor"]["aliases"], ["wife", "my wife", "Katie Ann Merrill", "Katie"])  # v384 adds the unique first name
        self.assertEqual(rows["katie-taylor"]["source"], "landmark:family")
        self.assertEqual([f["slug"] for f in result["folded"]], ["katie-taylor"])
        self.assertEqual(result["filed"], 0)
        again = self._run(result["roster"]["entities"], [_partnership()])
        self.assertEqual(again["folded"], [])
        self.assertEqual(again["roster"]["entities"], result["roster"]["entities"])

    def test_the_collision_branch_writes_nothing_and_reports(self) -> None:
        rows = [_katie(), _row("Katie Rose Holt", relationship="friend")]
        result = self._run(rows, [_partnership()])
        self.assertEqual(result["folded"], [])
        self.assertEqual(result["filed"], 0)
        self.assertEqual(len(result["contested"]), 1)
        self.assertEqual(result["roster"]["entities"], rows)

    def test_a_dry_run_reports_the_fold_and_writes_nothing(self) -> None:
        result = self._run([_katie()], [_partnership()], dry_run=True)
        self.assertEqual(len(result["folded"]), 1)
        self.assertEqual(result["roster"]["entities"], [_katie()])


# --------------------------------------------------------------------------
# D3 — counts are a deterministic join
# --------------------------------------------------------------------------


class RecountIsADeterministicJoin(unittest.TestCase):

    def setUp(self) -> None:
        self.tmp = root_parent_tmp(self, ROOT, prefix="lifehug-v383-recount-")
        answers = self.tmp / "answers"
        answers.mkdir()
        (answers / "L1.md").write_text(
            "I married my wife Katie Taylor in 2007.\n", encoding="utf-8")
        (answers / "L2.md").write_text(
            "My wife Katie Ann and I married in 2007.\n", encoding="utf-8")
        (answers / "C3.md").write_text(
            "My friend James Ortega taught me to drive.\n", encoding="utf-8")
        # The module `entity_roster.recount_stats` will import at call time —
        # another suite may have reloaded it since this file was imported.
        rf = importlib.import_module("recommend_focuses")
        for module, name, value in (
                (rf, "ANSWERS_DIR", answers),
                (rf, "MANUAL_SOURCES_DIR", self.tmp / "sources" / "manual"),
                (rf, "CLASSIFICATIONS_DIR", self.tmp / "state" / "classifications"),
                (entity_roster, "ENTITY_DIR", self.tmp / "state" / "entity_rosters")):
            saved = getattr(module, name)
            setattr(module, name, value)
            self.addCleanup(setattr, module, name, saved)
        entity_roster.write_roster("person", [
            _katie(aliases=["wife", "my wife", "Katie Ann"]),
            _row("Katie Ann", maps_to_focus="katie-taylor", qualifies=False),
            _row("James Ortega"),
        ])

    def test_recount_idempotent_and_model_free(self) -> None:
        """P4: counts move off 0 through the roster's own aliases, a pointer
        row counts nothing of its own, a second run is byte-identical, and no
        model is ever reached."""
        import ai_provider  # noqa: PLC0415

        path = entity_roster.roster_file("person")
        with mock.patch.object(ai_provider, "call_ai",
                               side_effect=AssertionError("recount must never call a model")):
            first = entity_roster.recount("person")
            once = path.read_bytes()
            second = entity_roster.recount("person")
        self.assertTrue(first["changed"])
        self.assertFalse(second["changed"])
        self.assertEqual(path.read_bytes(), once)
        rows = {e["slug"]: e for e in json.loads(once)["entities"]}
        self.assertEqual(rows["katie-taylor"]["unique_answers"], 2,
                         "L1 by name and L2 by the folded spelling both count for Katie")
        self.assertGreater(rows["katie-taylor"]["score"], 0)
        self.assertEqual(rows["katie-ann"]["unique_answers"], 0,
                         "a pointer row's spellings count for its survivor")
        self.assertEqual(rows["james-ortega"]["unique_answers"], 1)

    def test_the_cli_runs_the_same_join(self) -> None:
        out = io.StringIO()
        with contextlib.redirect_stdout(out), \
                mock.patch.object(sys, "argv", ["entity_roster.py", "--type", "person",
                                                "--recount"]):
            self.assertEqual(entity_roster.main(), 0)
        self.assertIn("recounted", out.getvalue())
        rows = {e["slug"]: e for e in entity_roster.load_roster("person")["entities"]}
        self.assertEqual(rows["katie-taylor"]["unique_answers"], 2)

    def test_a_fold_recounts_on_the_next_read(self) -> None:
        """`entity-verdict --maps-to` runs the recount for the touched type."""
        entity_roster.write_roster("person", [
            _row("Ortega"), _row("James Ortega", aliases=[])])
        code = entity_verdict.main(["person", "ortega", "clear", "--maps-to", "james-ortega"])
        self.assertEqual(code, 0)
        rows = {e["slug"]: e for e in entity_roster.load_roster("person")["entities"]}
        self.assertEqual(rows["james-ortega"]["unique_answers"], 1)
        self.assertEqual(rows["ortega"]["folded_into"], "james-ortega")


if __name__ == "__main__":
    unittest.main()
