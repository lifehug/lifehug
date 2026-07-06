"""v97: theme graduation parity — the theme roster + roster-driven plan_themes."""

import importlib.util
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SYSTEM = ROOT / "system"
sys.path.insert(0, str(SYSTEM))


def load(name):
    spec = importlib.util.spec_from_file_location(name, SYSTEM / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


PARENTING_ROSTER = {
    "version": 1,
    "type": "theme",
    "entities": [
        {"name": "Parenting", "slug": "parenting", "aliases": ["fatherhood"],
         "qualifies": True, "maps_to_focus": None, "score": 7.0,
         "unique_answers": 3, "page_eligible": True,
         "keywords": ["parenting", "as a father", "my kids", "mantle of responsibility"]},
        {"name": "Faith", "slug": "faith", "aliases": [],
         "qualifies": True, "maps_to_focus": None, "score": 9.0,
         "unique_answers": 4, "page_eligible": True,
         "keywords": ["faith", "testimony"]},
        {"name": "Commuting", "slug": "commuting", "aliases": [],
         "qualifies": False, "maps_to_focus": None, "score": 1.0,
         "unique_answers": 1, "page_eligible": False,
         "keywords": ["commute"]},
    ],
}


class ThemeRosterTypeTests(unittest.TestCase):
    def setUp(self):
        self.roster = load("entity_roster")

    def test_theme_is_an_entity_type(self):
        self.assertIn("theme", self.roster.ENTITY_TYPES)
        self.assertIn("theme", self.roster.THRESHOLDS)
        self.assertIn("theme", self.roster.QUALIFY_RULE)

    def test_build_prompt_asks_for_keywords(self):
        prompt = self.roster.build_prompt("theme", [
            {"entity": "parenting", "score": 7.0, "unique_answers": 3,
             "cross_categories": [], "evidence": ["raising the kids"]},
        ], {})
        self.assertIn("keywords", prompt)
        self.assertIn('"keywords": ["phrase"]', prompt)

    def test_normalize_captures_keywords_and_prepends_name(self):
        ents = self.roster.normalize(
            "theme",
            [{"name": "Parenting", "aliases": ["fatherhood"], "qualifies": True,
              "maps_to_focus": None, "keywords": ["as a father", "My Kids "]}],
            [], {}, 6.0, 2)
        self.assertEqual(len(ents), 1)
        self.assertEqual(ents[0]["keywords"], ["parenting", "as a father", "my kids"])
        self.assertTrue(ents[0]["page_eligible"])

    def test_normalize_defaults_keywords_to_name(self):
        ents = self.roster.normalize(
            "theme",
            [{"name": "Parenting", "qualifies": True, "maps_to_focus": None}],
            [], {}, 6.0, 2)
        self.assertEqual(ents[0]["keywords"], ["parenting"])

    def test_deterministic_fallback_is_conservative(self):
        candidates = [
            {"entity": "parenting", "score": 7.0, "unique_answers": 3,
             "cross_categories": [], "evidence": []},
            {"entity": "quantum sailing", "score": 5.0, "unique_answers": 2,
             "cross_categories": [], "evidence": []},
        ]
        ents = self.roster.deterministic("theme", candidates, {}, 6.0, 2)
        by_name = {e["name"].lower(): e for e in ents}
        # parenting is in the classifier taxonomy → accepted
        self.assertTrue(by_name["parenting"]["qualifies"])
        # an unvouched-for name never qualifies without the AI path
        self.assertFalse(by_name["quantum sailing"]["qualifies"])

    def test_previous_decisions_carry_keywords_forward(self):
        previous = {"entities": [
            {"name": "Parenting", "slug": "parenting", "aliases": ["fatherhood"],
             "keywords": ["parenting", "as a father", "my kids"]},
        ]}
        raw = [{"name": "Parenting", "aliases": [], "qualifies": True,
                "maps_to_focus": None}]  # refresh response dropped keywords
        folded, _forced = self.roster.apply_previous_decisions(raw, previous)
        self.assertEqual(folded[0]["keywords"], ["parenting", "as a father", "my kids"])


class PlanThemesRosterTests(unittest.TestCase):
    def setUp(self):
        self.wiki = load("wiki_compile")

    def _answers(self):
        return {
            "A1": {"id": "A1", "source": "answers/A1.md",
                   "body": "As a father I learned patience raising the kids."},
            "A2": {"id": "A2", "source": "answers/A2.md",
                   "body": "The mission strengthened my faith in god."},
        }

    def _manual(self):
        return {
            "sources/manual/mantle.md": {
                "id": "mantle", "source": "sources/manual/mantle.md",
                "kind": "opinion",
                "body": "Parents wore a mantle of responsibility for us.",
            },
            "sources/artifacts/mantle-essay.md": {
                "id": "mantle-essay", "source": "sources/artifacts/mantle-essay.md",
                "kind": "authored_artifact",
                "body": "The essay develops the mantle of responsibility position.",
            },
        }

    def test_keyword_map_overlays_roster_over_static(self):
        merged = self.wiki.theme_keyword_map(PARENTING_ROSTER)
        # every static theme survives
        for slug in self.wiki.THEME_KEYWORDS:
            self.assertIn(slug, merged)
        # new roster theme added, origin mention
        self.assertIn("parenting", merged)
        self.assertEqual(merged["parenting"]["origin"], "mention")
        # roster wins on collision (faith keywords replaced) but stays origin focus
        self.assertEqual(merged["faith"]["keywords"], ["faith", "testimony"])
        self.assertEqual(merged["faith"]["origin"], "focus")
        # non-page-eligible roster entries never enter the map
        self.assertNotIn("commuting", merged)

    def test_no_roster_behavior_identical_to_static(self):
        merged = self.wiki.theme_keyword_map(None)
        self.assertEqual(
            {slug: spec["keywords"] for slug, spec in merged.items()},
            {slug: list(words) for slug, words in self.wiki.THEME_KEYWORDS.items()})
        self.assertTrue(all(spec["origin"] == "focus" for spec in merged.values()))

    def test_parenting_page_graduates_with_opinion_primary_essay_supporting(self):
        descs = self.wiki.plan_themes(self._answers(), self._manual(),
                                      PARENTING_ROSTER, "david-james-taylor")
        by_slug = {d["slug"]: d for d in descs}
        self.assertIn("parenting", by_slug)
        page = by_slug["parenting"]
        cited = {i["source"] for i in page["cited_items"]}
        supporting = {i["source"] for i in page["supporting_items"]}
        self.assertIn("answers/A1.md", cited)
        self.assertIn("sources/manual/mantle.md", cited)  # opinion = primary
        self.assertIn("sources/artifacts/mantle-essay.md", supporting)  # essay = supporting
        self.assertEqual(page["origin"], "mention")
        self.assertIn("david-james-taylor", page["seed_related"])

    def test_static_theme_pages_keep_slug_and_focus_origin(self):
        descs = self.wiki.plan_themes(self._answers(), self._manual(),
                                      PARENTING_ROSTER, "david-james-taylor")
        by_slug = {d["slug"]: d for d in descs}
        self.assertIn("faith", by_slug)
        self.assertEqual(by_slug["faith"]["origin"], "focus")

    def test_theme_in_mention_cleanup_types(self):
        self.assertIn("theme", self.wiki._MENTION_CLEANUP_TYPES)

    def test_taxonomy_gained_life_domains(self):
        classify = load("classify_story")
        for theme in ("parenting", "marriage", "aging"):
            self.assertIn(theme, classify.THEME_TAXONOMY)


if __name__ == "__main__":
    unittest.main()
