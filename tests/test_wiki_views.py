"""Tests for the wiki dashboard views + hamburger menu (serve_wiki.py)."""

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SYSTEM = ROOT / "system"
sys.path.insert(0, str(SYSTEM))

import serve_wiki  # noqa: E402
import roadmap  # noqa: E402
import entity_roster  # noqa: E402


class WikiViewsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        # Save originals so each test runs against an isolated fixture set.
        self._saved = {
            (serve_wiki, "QUESTIONS_FILE"): serve_wiki.QUESTIONS_FILE,
            (serve_wiki, "COVERAGE_FILE"): serve_wiki.COVERAGE_FILE,
            (serve_wiki, "QUESTION_CANDIDATES_FILE"): serve_wiki.QUESTION_CANDIDATES_FILE,
            (serve_wiki, "QUESTION_QUEUE_FILE"): serve_wiki.QUESTION_QUEUE_FILE,
            (serve_wiki, "SOURCE_MANIFEST_FILE"): serve_wiki.SOURCE_MANIFEST_FILE,
            (serve_wiki, "SOURCE_LINT_FINDINGS_FILE"): serve_wiki.SOURCE_LINT_FINDINGS_FILE,
            (serve_wiki, "FOCUS_RECS_FILE"): serve_wiki.FOCUS_RECS_FILE,
            (serve_wiki, "ROTATION_FILE"): serve_wiki.ROTATION_FILE,
            (serve_wiki, "WIKI_DIR"): serve_wiki.WIKI_DIR,
            (roadmap, "QUESTIONS_FILE"): roadmap.QUESTIONS_FILE,
            (roadmap, "ROADMAP_FILE"): roadmap.ROADMAP_FILE,
            (entity_roster, "ENTITY_DIR"): entity_roster.ENTITY_DIR,
        }

    def tearDown(self):
        for (mod, name), val in self._saved.items():
            setattr(mod, name, val)

    def _write(self, name, data):
        p = self.tmp / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(data if isinstance(data, str) else json.dumps(data))
        return p

    def _view(self, slug):
        return serve_wiki.VIEW_MAP[slug]()

    # --- infrastructure ---

    def test_menu_lists_every_view(self):
        menu = serve_wiki.menu_html()
        self.assertIn("menu-btn", menu)
        for slug, label, _ in serve_wiki.VIEWS:
            self.assertIn(f'/views/{slug}', menu)
            self.assertIn(label, menu)

    def test_layout_wide_flag_and_menu(self):
        out = serve_wiki.layout("T", "<h1>x</h1>", wide=True).decode()
        self.assertIn('main class="wide"', out)
        self.assertIn("menu-dropdown", out)

    def test_all_views_safe_on_empty_state(self):
        # Point every source at a non-existent file/dir; nothing should raise.
        for mod, name in [
            (serve_wiki, "QUESTIONS_FILE"), (serve_wiki, "COVERAGE_FILE"),
            (serve_wiki, "QUESTION_CANDIDATES_FILE"), (serve_wiki, "QUESTION_QUEUE_FILE"),
            (serve_wiki, "SOURCE_MANIFEST_FILE"), (serve_wiki, "SOURCE_LINT_FINDINGS_FILE"),
            (serve_wiki, "FOCUS_RECS_FILE"), (serve_wiki, "ROTATION_FILE"),
            (roadmap, "QUESTIONS_FILE"), (roadmap, "ROADMAP_FILE"),
        ]:
            setattr(mod, name, self.tmp / "missing.json")
        serve_wiki.WIKI_DIR = self.tmp / "no-wiki"
        entity_roster.ENTITY_DIR = self.tmp / "no-rosters"
        for slug, _, fn in serve_wiki.VIEWS:
            title, body, wide = fn()
            self.assertTrue(body, slug)

    # --- populated content ---

    def _populate(self):
        qbank = self._write("question-bank.md",
            "## A: Origins (Childhood)\n- [x] A1: Earliest? *(2026-01-01)*\n- [ ] A2: Where?\n"
            "## F: The Problem (Etherfuse Story)\n- [x] F1: What?\n- [x] F2: Why you?\n")
        serve_wiki.QUESTIONS_FILE = qbank
        roadmap.QUESTIONS_FILE = qbank
        serve_wiki.COVERAGE_FILE = self._write("coverage.json", {"categories": {
            "A": {"total": 2, "answered": 1, "status": "yellow"},
            "F": {"total": 2, "answered": 2, "status": "green"}}})
        roadmap.ROADMAP_FILE = self._write("roadmap.json", {"version": 1, "focuses": [
            {"id": "my-life", "label": "My Life", "type": "life_story", "primary": True,
             "tier": "extreme", "objective": "story", "deliverable": "book", "categories": ["A"],
             "target_depth": 4, "phase": "active", "wiki_node": "wiki/life/my-life.md"},
            {"id": "etherfuse", "label": "Etherfuse", "type": "project", "tier": "standard",
             "objective": "founding", "deliverable": "book", "categories": ["F"],
             "target_depth": 2, "phase": "finishing", "wiki_node": None}]})
        serve_wiki.QUESTION_CANDIDATES_FILE = self._write("cand.json", {"candidates": [
            {"id": "c1", "text": "First commit?", "status": "candidate", "priority": 0.82,
             "target_category": "F", "story_function": "turning_point", "source_path": "answers/F1.md",
             "quality": {"score": 0.88}},
            {"id": "c2", "text": "What scared you?", "status": "needs_review", "priority": 0.71}]})
        serve_wiki.QUESTION_QUEUE_FILE = self._write("queue.json", {"expires_at": "2026-07-07", "queue": [
            {"question_id": "A2", "category": "A", "text": "Where?", "story_function": "scene", "status": "queued"},
            {"question_id": "F1", "category": "F", "text": "What?", "delivered_at": "x", "status": "delivered"}]})
        serve_wiki.SOURCE_MANIFEST_FILE = self._write("man.json", {"sources": {
            "answers/A1.md": {"type": "prompted_answer", "title": "A1", "captured_at": "2026-01-01",
                              "source_medium": "voice", "changed_since_first_seen": False},
            "sources/manual/x.md": {"type": "manual_source", "title": "Arizona", "first_seen_at": "2026-02-01",
                                    "source_medium": "telegram", "changed_since_first_seen": True}}})
        serve_wiki.SOURCE_LINT_FINDINGS_FILE = self._write("lint.json", {"open_count": 1, "findings": [
            {"type": "missing_frontmatter", "severity": "error", "path": "sources/manual/x.md",
             "message": "missing source_id", "fixability": "automatic", "status": "open"}]})
        serve_wiki.FOCUS_RECS_FILE = self._write("recs.json", {"recommendations": [
            {"id": "r1", "entity": "Emma", "type": "person", "score": 7.5, "evidence_strength": "strong",
             "mention_count": 12, "cross_categories": ["B", "C"], "reason": "across chapters", "status": "pending"},
            {"id": "r2", "entity": "Bob", "type": "person", "score": 3, "status": "approved"}],
            "dismissed": [{"id": "r3", "entity": "Thing", "dismiss_reason": "too generic"}]})
        serve_wiki.ROTATION_FILE = self._write("rot.json",
            {"current_pass": 2, "pass_names": ["skeleton", "depth"], "questions_asked": 3})
        entity_roster.ENTITY_DIR = self.tmp / "rosters"
        self._write("rosters/person.json", {"type": "person", "entities": [
            {"name": "Emma", "aliases": ["Em"], "score": 7.5, "unique_answers": 4, "qualifies": True, "page_eligible": True},
            {"name": "Dad", "aliases": [], "score": 6, "unique_answers": 2, "qualifies": True, "maps_to_focus": "dad"}]})
        wiki = self.tmp / "wiki"
        serve_wiki.WIKI_DIR = wiki
        self._write("wiki/life/my-life.md",
            '---\ntitle: "My Life"\ntype: life\nsources:\n  - "answers/A1.md"\nsources_count: 3\nrelated:\n  - "[[emma]]"\n---\n# My Life\n')
        self._write("wiki/people/emma.md",
            '---\ntitle: "Emma"\ntype: person\nsources:\n  - "answers/A1.md"\nsources_count: 1\nrelated:\n  - "[[my-life]]"\n---\n# Emma\n')
        self._write("wiki/index.md", "# Index\n")

    def test_focuses_bars_and_wiki_link(self):
        self._populate()
        _, body, _ = self._view("focuses")
        self.assertIn("My Life", body)
        self.assertIn("Etherfuse", body)
        self.assertIn("bar-fill", body)
        self.assertIn("finishing", body)
        self.assertIn('href="/page/wiki/life/my-life.md"', body)

    def test_coverage_sorted_lowest_first(self):
        self._populate()
        _, body, _ = self._view("coverage")
        self.assertLess(body.index('cov-cat">A'), body.index('cov-cat">F'))

    def test_question_bank_markers(self):
        self._populate()
        _, body, _ = self._view("question-bank")
        self.assertIn("A: Origins", body)
        self.assertIn("✓", body)
        self.assertIn("○", body)

    def test_candidates_grouped_by_status(self):
        self._populate()
        _, body, _ = self._view("candidates")
        self.assertIn("candidate (1)", body)
        self.assertIn("needs_review (1)", body)
        self.assertIn("turning_point", body)

    def test_entities_graduation_flags(self):
        self._populate()
        _, body, _ = self._view("entities")
        self.assertIn("Emma", body)
        self.assertIn("✓ page", body)
        self.assertIn("→ dad", body)

    def test_status_dashboard(self):
        self._populate()
        _, body, _ = self._view("status")
        self.assertIn("2 · depth", body)
        self.assertIn("candidate: 1", body)

    def test_graph_nodes_edges_and_weight(self):
        self._populate()
        g = serve_wiki.graph_data()
        self.assertEqual(len(g["nodes"]), 2)
        self.assertEqual(len(g["edges"]), 1)
        self.assertEqual(g["edges"][0]["weight"], 2)  # shared answers/A1.md -> 1 + 1
        mylife = next(n for n in g["nodes"] if n["id"].endswith("my-life.md"))
        self.assertEqual(mylife["sources"], 3)
        self.assertIn("sat", mylife)


if __name__ == "__main__":
    unittest.main()
