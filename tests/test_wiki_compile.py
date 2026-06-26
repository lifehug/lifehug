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


def make_desc(slug, sources, cited_items=None, supporting_items=None,
              seed_related=None, page_type="person", title=None):
    return {
        "type": page_type,
        "title": title or slug.title(),
        "slug": slug,
        "path": Path(f"/tmp/{slug}.md"),
        "sources": sources,
        "cited_items": cited_items or [],
        "supporting_items": supporting_items or [],
        "summary": f"summary of {slug}",
        "open_questions": [],
        "open_questions_header": "Open Questions",
        "seed_related": seed_related or [],
    }


# ---------------------------------------------------------------------------
# Viewer: [[wikilink]] resolution
# ---------------------------------------------------------------------------


class LinkifyTests(unittest.TestCase):
    def setUp(self):
        self.sw = load("serve_wiki")

    def test_known_slug_links_to_page(self):
        out = self.sw.linkify("see [[katie]]", {"katie": "wiki/people/katie.md"})
        self.assertIn('href="/page/wiki/people/katie.md"', out)

    def test_unknown_slug_falls_back_to_search(self):
        out = self.sw.linkify("see [[ghost]]", {"katie": "wiki/people/katie.md"})
        self.assertIn("/search?q=ghost", out)

    def test_label_with_spaces_slugified(self):
        out = self.sw.linkify("see [[The Storm]]", {"the-storm": "wiki/projects/the-storm.md"})
        self.assertIn('href="/page/wiki/projects/the-storm.md"', out)

    def test_page_index_type_priority_on_collision(self):
        fake = [
            self.sw.WIKI_DIR / "themes" / "family.md",
            self.sw.WIKI_DIR / "people" / "family.md",
        ]
        self.sw.wiki_pages = lambda: fake
        idx = self.sw.page_index()
        # person outranks theme for the shared "family" slug
        self.assertEqual(idx["family"], "wiki/people/family.md")


# ---------------------------------------------------------------------------
# Compiler: cross-links (deterministic, no LLM)
# ---------------------------------------------------------------------------


class CrosslinkTests(unittest.TestCase):
    def setUp(self):
        self.wc = load("wiki_compile")

    def test_shared_source_creates_reciprocal_related(self):
        descs = [make_desc("a", ["s1"]), make_desc("b", ["s1"]), make_desc("c", ["s2"])]
        synths = {"a": {"related": []}, "b": {"related": []}, "c": {"related": []}}
        related, _ = self.wc.compute_crosslinks(descs, synths)
        self.assertIn("b", related["a"])
        self.assertIn("a", related["b"])
        self.assertNotIn("c", related["a"])  # different source, no edge

    def test_backlinks_are_reverse_of_related(self):
        descs = [make_desc("a", ["s2"]), make_desc("b", ["s3"]), make_desc("c", ["s4"], seed_related=["a"])]
        synths = {"a": {"related": []}, "b": {"related": []}, "c": {"related": []}}
        related, backlinks = self.wc.compute_crosslinks(descs, synths)
        self.assertIn("a", related["c"])      # seed edge c -> a
        self.assertIn("c", backlinks["a"])    # reverse shows as backlink on a

    def test_dangling_related_dropped(self):
        descs = [make_desc("a", ["s2"])]
        synths = {"a": {"related": ["nonexistent"]}}
        related, _ = self.wc.compute_crosslinks(descs, synths)
        self.assertEqual(related["a"], [])

    def test_related_excluded_from_backlinks(self):
        # Mutual link should appear under related, not duplicated under backlinks.
        descs = [make_desc("a", ["s1"]), make_desc("b", ["s1"])]
        synths = {"a": {"related": []}, "b": {"related": []}}
        related, backlinks = self.wc.compute_crosslinks(descs, synths)
        self.assertIn("b", related["a"])
        self.assertNotIn("b", backlinks["a"])


# ---------------------------------------------------------------------------
# Compiler: synthesis (offline fallback, cache, mocked LLM)
# ---------------------------------------------------------------------------


class SynthesisTests(unittest.TestCase):
    def setUp(self):
        self.wc = load("wiki_compile")
        self.desc = make_desc(
            "a", ["answers/A1.md"],
            cited_items=[{"id": "A1", "body": "hello world", "source": "answers/A1.md"}],
        )

    def test_offline_fallback_uses_excerpts(self):
        synth = self.wc.synthesize(self.desc, [], "m", {}, "", use_ai=False, dry_run=False)
        self.assertFalse(synth["synthesized"])
        self.assertIn("A1", synth["narrative"])

    def test_cache_short_circuits_ai(self):
        def boom(*a, **k):
            raise AssertionError("call_ai must not run on a cache hit")
        self.wc.call_ai = boom
        key = self.wc.cache_key(self.desc)
        cache = {key: {"narrative": "cached prose", "related": ["b"]}}
        synth = self.wc.synthesize(self.desc, [], "m", cache, "", use_ai=True, dry_run=False)
        self.assertTrue(synth["synthesized"])
        self.assertEqual(synth["narrative"], "cached prose")
        self.assertEqual(synth["related"], ["b"])

    def test_ai_result_parsed_and_cached(self):
        self.wc.call_ai = lambda prompt, model: '{"narrative": "P", "related": ["b"]}'
        cache = {}
        roster = [{"slug": "b", "title": "B", "type": "person"}]
        synth = self.wc.synthesize(self.desc, roster, "m", cache, "", use_ai=True, dry_run=False)
        self.assertTrue(synth["synthesized"])
        self.assertEqual(synth["narrative"], "P")
        self.assertEqual(synth["related"], ["b"])
        self.assertIn(self.wc.cache_key(self.desc), cache)

    def test_ai_failure_falls_back(self):
        def boom(prompt, model):
            raise RuntimeError("no api key")
        self.wc.call_ai = boom
        synth = self.wc.synthesize(self.desc, [], "m", {}, "", use_ai=True, dry_run=False)
        self.assertFalse(synth["synthesized"])
        self.assertIn("A1", synth["narrative"])


# ---------------------------------------------------------------------------
# Compiler: rendering
# ---------------------------------------------------------------------------


class RenderTests(unittest.TestCase):
    def setUp(self):
        self.wc = load("wiki_compile")
        self.desc = make_desc(
            "a", ["answers/A1.md"],
            cited_items=[{"id": "A1", "body": "hello", "source": "answers/A1.md"}],
        )

    def test_synthesized_page_has_graph_sections(self):
        synth = {"narrative": "Prose here.", "related": ["b"], "synthesized": True}
        out = self.wc.render_page(self.desc, synth, ["b"], ["c"], {"b": "B", "c": "C"})
        self.assertIn("Prose here.", out)
        self.assertIn("## Sources", out)
        self.assertIn("## Related Pages", out)
        self.assertIn("- [[b]] — B", out)
        self.assertIn("## Backlinks", out)
        self.assertIn("- [[c]] — C", out)

    def test_fallback_page_uses_what_we_know(self):
        synth = {"narrative": "ignored", "related": [], "synthesized": False}
        out = self.wc.render_page(self.desc, synth, [], [], {})
        self.assertIn("## What We Know", out)
        self.assertIn("No related pages identified yet.", out)


if __name__ == "__main__":
    unittest.main()
