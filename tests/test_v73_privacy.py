"""v73 phase 0 — privacy: sensitivity vocabulary, floors, synthesis unlock."""

import importlib.util
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SYSTEM = ROOT / "system"
sys.path.insert(0, str(SYSTEM))


def load(name):
    """Load a private copy of system/<name>.py WITHOUT clobbering the shared
    sys.modules entry — other test modules bind the canonical module at import
    time, and replacing it mid-suite splits state across two module objects."""
    spec = importlib.util.spec_from_file_location(name, SYSTEM / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    orig = sys.modules.get(name)
    sys.modules[name] = mod
    try:
        spec.loader.exec_module(mod)
    finally:
        if orig is not None:
            sys.modules[name] = orig
        else:
            sys.modules.pop(name, None)
    return mod


core = load("lifehug_core")
wc = load("wiki_compile")
cls = load("classify_story")


class VocabularyTests(unittest.TestCase):
    def test_rank_ordering(self):
        self.assertLess(core.sensitivity_rank("public"), core.sensitivity_rank("friends"))
        self.assertLess(core.sensitivity_rank("friends"), core.sensitivity_rank("family"))
        self.assertLess(core.sensitivity_rank("family"), core.sensitivity_rank("private"))

    def test_unknown_and_legacy_default_private(self):
        for value in (None, "", "personal", "banana"):
            self.assertEqual(core.sensitivity_rank(value), core.sensitivity_rank("private"), value)

    def test_floor_is_most_closed(self):
        self.assertEqual(core.sensitivity_floor(["public", "friends"]), "friends")
        self.assertEqual(core.sensitivity_floor(["public", "private", "family"]), "private")
        self.assertEqual(core.sensitivity_floor([]), "public")

    def test_visibility(self):
        # A friends-level page: visible to friends and family builds, not public.
        self.assertTrue(core.sensitivity_visible("friends", "friends"))
        self.assertTrue(core.sensitivity_visible("friends", "family"))
        self.assertFalse(core.sensitivity_visible("friends", "public"))
        # Private content: owner only.
        self.assertFalse(core.sensitivity_visible("private", "family"))
        self.assertTrue(core.sensitivity_visible("private", "owner"))
        # Public content: everyone.
        self.assertTrue(core.sensitivity_visible("public", "public"))


class PageFloorTests(unittest.TestCase):
    def _desc(self, sensitivities):
        return {
            "type": "person", "title": "T", "slug": "t",
            "sources": ["s"], "summary": "s", "open_questions": [],
            "open_questions_header": "Open Questions",
            "cited_items": [
                {"id": f"a{i}", "source": f"answers/A{i}.md", "body": "b", "sensitivity": s}
                for i, s in enumerate(sensitivities)
            ],
            "supporting_items": [],
        }

    def test_page_frontmatter_carries_floor(self):
        synth = {"narrative": "prose", "related": [], "synthesized": True}
        text = wc.render_page(self._desc(["public", "friends"]), synth, [], [], {})
        self.assertIn("sensitivity: friends", text)
        text = wc.render_page(self._desc(["family", "public"]), synth, [], [], {})
        self.assertIn("sensitivity: family", text)

    def test_unlabeled_sources_floor_private(self):
        desc = self._desc(["public"])
        desc["cited_items"].append({"id": "x", "source": "answers/X.md", "body": "b"})  # no label
        synth = {"narrative": "prose", "related": [], "synthesized": True}
        text = wc.render_page(desc, synth, [], [], {})
        self.assertIn("sensitivity: private", text)


class SynthesisUnlockTests(unittest.TestCase):
    def test_honesty_contract_in_prompt(self):
        desc = {
            "type": "relationship", "title": "Dave & Katie", "slug": "dave-and-katie",
            "cited_items": [{"id": "a", "source": "answers/D15.md", "body": "hard material"}],
            "supporting_items": [],
        }
        prompt = wc.build_synthesis_prompt(desc, [], "")
        self.assertIn("PRIVACY CONTRACT", prompt)
        self.assertIn("Do NOT sanitize", prompt)
        self.assertIn("PERMANENTLY PRIVATE", prompt)

    def test_cache_version_bumped_for_recontract(self):
        self.assertEqual(wc.CACHE_VERSION, "v3")


class ClassifierSuggestionTests(unittest.TestCase):
    def test_prompt_carries_taxonomy(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "story.md"
            src.write_text("body", encoding="utf-8")
            prompt = cls.build_prompt(src, {"title": "t"}, "Story.")
        self.assertIn("suggested_sensitivity", prompt)
        self.assertIn("minor child", prompt)          # kids' hard cap in taxonomy
        self.assertIn("default private when in doubt", prompt)

    def test_classification_stores_suggestion(self):
        record = cls.build_classification(
            Path("answers/A1.md"), {}, {
                "suggested_sensitivity": "friends",
                "sensitivity_reason": "embarrassing but harmless",
            }, "model", "now", [])
        self.assertEqual(record["suggested_sensitivity"], "friends")
        self.assertEqual(record["sensitivity_reason"], "embarrassing but harmless")

    def test_suggestion_defaults_private(self):
        record = cls.build_classification(Path("answers/A1.md"), {}, {}, "m", "now", [])
        self.assertEqual(record["suggested_sensitivity"], "private")


if __name__ == "__main__":
    unittest.main()
