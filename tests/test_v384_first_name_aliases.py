"""v384 — a unique first name is an alias (ADR 0041 amendment, D4).

Promises: the founder's `Katie Taylor` (answers say "Katie") gains the alias
`Katie`; a first token two rows share (the Jameses) is never added and the
collision is reported; one-token rows are untouched; a second run is
byte-identical; a recount moves the answers onto the row; no model is called.
Synthetic throughout.
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

from tempdirs import root_parent_tmp  # noqa: E402

import entity_roster  # noqa: E402
import landmark_projection  # noqa: E402
import temporal_publication  # noqa: E402,F401
import temporal_store  # noqa: E402,F401


def _row(name: str, *, aliases=(), **extra) -> dict:
    out = {"name": name, "slug": entity_roster.slugify(name), "aliases": list(aliases),
           "qualifies": True, "maps_to_focus": None, "score": 0.0, "unique_answers": 0,
           "page_eligible": False}
    out.update(extra)
    return out


def _founder_shaped() -> list[dict]:
    return [
        _row("Katie Taylor", aliases=["wife", "my wife", "Katie Ann Merrill"], qualifies=False),
        _row("Charlee Joy Taylor"),
        _row("Dottie Ovelle Taylor"),
        _row("Harvey"),
        _row("Daughter"),
        _row("James Taylor"),
        _row("James Everett Taylor"),
        _row("Anthon James Taylor", aliases=["James"]),
    ]


class FirstNameAliases(unittest.TestCase):

    def setUp(self) -> None:
        import lifehug_core  # noqa: PLC0415

        self.root = root_parent_tmp(self, ROOT, prefix="lifehug-v384-")
        (self.root / "system").mkdir(parents=True, exist_ok=True)
        self.dir = self.root / "state" / "entity_rosters"
        self.dir.mkdir(parents=True, exist_ok=True)
        (self.root / "answers").mkdir()
        (self.root / "profile.yaml").write_text("name: Dave\n", encoding="utf-8")
        self.path = self.dir / "person.json"
        for module, name, value in ((lifehug_core, "REPO_DIR", self.root),
                                    (entity_roster, "ENTITY_DIR", self.dir)):
            saved = getattr(module, name)
            setattr(module, name, value)
            self.addCleanup(setattr, module, name, saved)

    def _run(self, rows, *, stats=None) -> dict:
        self.path.write_text(json.dumps({"version": 1, "type": "person", "entities": rows}),
                             encoding="utf-8")
        with mock.patch.object(landmark_projection, "load_landmark_sources", return_value=[]), \
                mock.patch.object(entity_roster, "recount_stats",
                                  return_value=stats if stats is not None else {}):
            result = entity_roster.ensure_introduced_relatives()
        result["roster"] = {e["slug"]: e for e in json.loads(self.path.read_text())["entities"]}
        return result

    def test_unique_first_names_become_aliases_and_the_jameses_do_not(self) -> None:
        result = self._run(_founder_shaped())
        rows = result["roster"]
        self.assertIn("Katie", rows["katie-taylor"]["aliases"])
        self.assertIn("Charlee", rows["charlee-joy-taylor"]["aliases"])
        self.assertIn("Dottie", rows["dottie-ovelle-taylor"]["aliases"])
        self.assertEqual(rows["harvey"]["aliases"], [])
        # v386 (ADR 0043, D6): "Daughter" is a relation query, not a record.
        self.assertNotIn("daughter", rows)
        self.assertNotIn("James", rows["james-taylor"]["aliases"])
        self.assertNotIn("James", rows["james-everett-taylor"]["aliases"])
        self.assertEqual(rows["anthon-james-taylor"]["aliases"].count("James"), 1)
        collided = {c["slug"] for c in result["first_name_collisions"]}
        self.assertEqual(collided, {"james-taylor", "james-everett-taylor"})
        self.assertTrue(all(c["alias"] == "James" for c in result["first_name_collisions"]))

    def test_a_role_word_first_token_is_not_a_name(self) -> None:
        result = self._run([_row("Grandma Betty Jo")])
        self.assertEqual(result["roster"]["grandma-betty-jo"]["aliases"], [])

    def test_second_run_is_byte_identical(self) -> None:
        first = self._run(_founder_shaped())
        once = self.path.read_bytes()
        with mock.patch.object(landmark_projection, "load_landmark_sources", return_value=[]), \
                mock.patch.object(entity_roster, "recount_stats", return_value={}):
            second = entity_roster.ensure_introduced_relatives()
        self.assertEqual(second["first_names"], [])
        self.assertEqual(self.path.read_bytes(), once)

    def test_the_recount_counts_the_first_name(self) -> None:
        import recommend_focuses as rf  # noqa: PLC0415

        answers = self.root / "answers"
        (answers / "L1.md").write_text("My wife Katie made dinner.\n", encoding="utf-8")
        (answers / "L2.md").write_text("Katie and I went hiking.\n", encoding="utf-8")
        for name, value in (("ANSWERS_DIR", answers),
                            ("MANUAL_SOURCES_DIR", self.root / "sources" / "manual"),
                            ("CLASSIFICATIONS_DIR", self.root / "state" / "classifications")):
            saved = getattr(rf, name)
            setattr(rf, name, value)
            self.addCleanup(setattr, rf, name, saved)
        self.path.write_text(json.dumps({"version": 1, "type": "person", "entities": [
            _row("Katie Taylor", aliases=["wife", "my wife"], qualifies=False)]}), encoding="utf-8")
        with mock.patch.object(landmark_projection, "load_landmark_sources", return_value=[]):
            entity_roster.ensure_introduced_relatives()
        row = json.loads(self.path.read_text())["entities"][0]
        self.assertIn("Katie", row["aliases"])
        self.assertGreaterEqual(row["unique_answers"], 1)

    def test_no_model_call(self) -> None:
        import ai_provider  # noqa: PLC0415

        with mock.patch.object(ai_provider, "call_ai",
                               side_effect=AssertionError("no model on this path")):
            self._run(_founder_shaped())


if __name__ == "__main__":
    unittest.main()
