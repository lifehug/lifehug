"""v387 — the classifier knows the people (identity design §4.1.3, P3).

The classifier prompt carries a "People You Already Know" block built from the
person roster, its output contract asks for the roster's names, and a
deterministic post-processor rewrites `people[].name` /
`focus_opportunities[].entity` to the roster name only when person resolution
is `resolved`. Synthetic names only; the owner's cases by SHAPE.

Regenerate the golden (after READING the diff) with
``LIFEHUG_REGENERATE_GOLDENS=1``.
"""

from __future__ import annotations

import copy
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "system"))

import classifier_context as cc
import classify_story

GOLDEN = ROOT / "tests" / "goldens" / "classifier_people_block_v387.txt"

ROSTER = {"version": 1, "type": "person", "entities": [
    {"name": "Rosalind Vane", "slug": "rosalind-vane", "aliases": ["Roz", "Rozzie"],
     "relationship": "spouse", "focus": "roz"},
    {"name": "Edwin Marsh", "slug": "edwin-marsh", "aliases": ["Dad", "my dad"],
     "relationship": "parent"},
    {"name": "Edwin Marsh Sr", "slug": "edwin-marsh-sr", "relationship": "grandparent"},
    {"name": "Edwin Marsh", "slug": "edwin-marsh-ii", "relationship": "child",
     "born": "2013-05-10"},
    {"name": "Tilly Hart", "slug": "tilly-hart", "relationship": "friend"},
    {"name": "Kids", "slug": "kids", "relationship": "child"},
    {"name": "Rozzy", "slug": "rozzy", "maps_to_focus": "rosalind-vane"},
]}

STORY = "Tilly drove up with Roz and me the summer the lake froze."


def _prompt(roster=ROSTER) -> str:
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "story.md"
        src.write_text(STORY, encoding="utf-8")
        with mock.patch.object(classify_story, "REPO_DIR", Path(tmp)):
            return classify_story.build_prompt(
                src, {"title": "Lake", "type": "unprompted_story"}, STORY,
                include_candidates=False, person_roster=roster)


def _block(prompt: str) -> str:
    start = prompt.index("## People You Already Know")
    return prompt[start:prompt.index("\n---\n", start)] + "\n"


class PeopleBlockTests(unittest.TestCase):

    def test_the_people_block_golden(self):
        block = _block(_prompt())
        if os.environ.get("LIFEHUG_REGENERATE_GOLDENS"):
            GOLDEN.write_text(block, encoding="utf-8")
        self.assertEqual(block, GOLDEN.read_text(encoding="utf-8"))

    def test_the_output_contract_asks_for_roster_names(self):
        prompt = _prompt()
        self.assertIn("write their listed name exactly as shown", prompt)
        self.assertIn("('unknown' when the story does not say)", prompt)
        self.assertIn('write `"unknown"` as their relationship', prompt)

    def test_named_first_then_family_and_collisions_disambiguated(self):
        lines = cc.render_known_people(ROSTER, story_text=STORY).splitlines()
        # Tilly and Roz are named by the story; then family in roster order.
        self.assertTrue(lines[0].startswith("- Rosalind Vane"))
        self.assertTrue(lines[1].startswith("- Tilly Hart"))
        # v388: the relation word comes from the record (its "Dad" alias).
        self.assertIn("- Edwin Marsh (father)", lines[2])
        self.assertIn("- Edwin Marsh (child, b. 2013)", "\n".join(lines))
        joined = "\n".join(lines)
        self.assertNotIn("Kids", joined)   # a collective row is not a person
        self.assertNotIn("Rozzy", joined)  # a fold pointer is not a person

    def test_the_cap_says_what_it_hid(self):
        roster = {"entities": [{"name": f"Person {chr(65 + i)}{chr(65 + j)}",
                                "slug": f"p-{i}-{j}"}
                               for i in range(6) for j in range(6)]}
        lines = cc.render_known_people(roster).splitlines()
        self.assertEqual(len(lines), cc.KNOWN_PEOPLE_LIMIT + 1)
        self.assertEqual(lines[-1], "- …and 6 more people on file")

    def test_an_empty_roster_says_so(self):
        self.assertIn("(no people on file yet)", _block(_prompt({"entities": []})))

    def test_the_block_is_not_part_of_the_snapshot(self):
        """Adding an alias must not re-classify every source: the prompt and
        extractor versions are untouched by this release."""
        self.assertEqual(cc.PROMPT_VERSION, "contextual-timeline:3")
        self.assertEqual(cc.EXTRACTOR_VERSION, "story-classifier:2")


class PostProcessorTests(unittest.TestCase):

    def test_the_owners_father_is_rewritten_to_the_roster_name(self):
        """P2/P3 shape: "<Owner>'s father" names the father's record."""
        roster = copy.deepcopy(ROSTER)
        result = {"people": [{"name": "Author's father", "relationship": "father"},
                             {"name": "the narrator's wife", "relationship": "wife"}],
                  "focus_opportunities": [{"entity": "Author's father",
                                           "type": "person"}]}
        out = cc.resolve_classification_people(result, roster)
        self.assertEqual(out["people"][0]["name"], "Edwin Marsh")
        self.assertEqual(out["people"][1]["name"], "Rosalind Vane")
        self.assertEqual(out["focus_opportunities"][0]["entity"], "Edwin Marsh")
        note = out[cc.IDENTITY_RESOLUTION_FIELD][0]
        self.assertEqual(note, {"field": "people", "index": 0,
                                "mention": "Author's father", "kind": "resolved",
                                "ref": "person/edwin-marsh", "name": "Edwin Marsh",
                                "rewritten": True})

    def test_a_shared_first_name_alone_never_rewrites(self):
        """v388: "Tilly Brooks" shares only a first name with Tilly Hart — the
        first-name rung resolves it, but the post-processor never rewrites a
        stranger onto a listed person on that alone."""
        out = cc.resolve_classification_people(
            {"people": [{"name": "Tilly Brooks", "relationship": "friend"}]}, ROSTER)
        self.assertEqual(out["people"][0]["name"], "Tilly Brooks")

    def test_ambiguous_and_unknown_are_left_alone(self):
        result = {"people": [{"name": "Edwin", "relationship": "unknown"},
                             {"name": "Arlo Finch", "relationship": "neighbor"}],
                  "focus_opportunities": [{"entity": "the lake house",
                                           "type": "place"}]}
        out = cc.resolve_classification_people(result, ROSTER)
        self.assertEqual([p["name"] for p in out["people"]], ["Edwin", "Arlo Finch"])
        kinds = [n["kind"] for n in out[cc.IDENTITY_RESOLUTION_FIELD]]
        self.assertEqual(kinds, ["ambiguous", "unknown"])
        self.assertTrue(out[cc.IDENTITY_RESOLUTION_FIELD][0]["candidates"])
        # A place opportunity is not a person mention.
        self.assertEqual(len(out[cc.IDENTITY_RESOLUTION_FIELD]), 2)

    def test_a_relationship_word_splits_a_shared_name(self):
        out = cc.resolve_classification_people(
            {"people": [{"name": "Edwin", "relationship": "son"}]}, ROSTER)
        self.assertEqual(out[cc.IDENTITY_RESOLUTION_FIELD][0]["ref"],
                         "person/edwin-marsh-ii")

    def test_no_roster_keeps_the_bytes(self):
        result = {"people": [{"name": "Edwin"}]}
        self.assertEqual(cc.resolve_classification_people(dict(result), {}), result)


if __name__ == "__main__":
    unittest.main()
