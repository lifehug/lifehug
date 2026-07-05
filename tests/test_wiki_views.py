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
            (serve_wiki, "NEIGHBORHOODS_FILE"): serve_wiki.NEIGHBORHOODS_FILE,
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

    def test_menu_order(self):
        # v75 inserts 'book' immediately after the system overview pair so the
        # manuscript surface is one of the first things visible in the menu.
        order = [slug for slug, _, _ in serve_wiki.VIEWS]
        self.assertEqual(order, [
            "status", "graph", "book", "focuses", "recommendations",
            "question-bank", "candidates", "queue",
            "coverage", "entities", "sources", "privacy",
        ])

    def test_layout_wide_flag_and_menu(self):
        out = serve_wiki.layout("T", "<h1>x</h1>", wide=True).decode()
        self.assertIn('main class="wide"', out)
        self.assertIn("menu-dropdown", out)

    def test_sidebar_groups_default_collapsed(self):
        self._populate()
        nav = serve_wiki.nav_html()
        # Every group renders collapsed; none is left in the open form.
        self.assertIn('class="sidebar-group collapsed"', nav)
        self.assertNotIn('class="sidebar-group"', nav)
        # Persistence tracks the groups the user *expands* (default = closed).
        out = serve_wiki.layout("T", "<h1>x</h1>").decode()
        self.assertIn("lifehug.expandedGroups", out)

    def test_all_views_safe_on_empty_state(self):
        # Point every source at a non-existent file/dir; nothing should raise.
        for mod, name in [
            (serve_wiki, "QUESTIONS_FILE"), (serve_wiki, "COVERAGE_FILE"),
            (serve_wiki, "QUESTION_CANDIDATES_FILE"), (serve_wiki, "QUESTION_QUEUE_FILE"),
            (serve_wiki, "SOURCE_MANIFEST_FILE"), (serve_wiki, "SOURCE_LINT_FINDINGS_FILE"),
            (serve_wiki, "FOCUS_RECS_FILE"), (serve_wiki, "ROTATION_FILE"),
            (serve_wiki, "NEIGHBORHOODS_FILE"),
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
            {"id": "c2", "text": "What scared you?", "status": "needs_review", "priority": 0.71},
            # No explicit target, but its neighborhood maps to a category.
            {"id": "c3", "text": "Who are you becoming?", "status": "candidate", "priority": 0.9,
             "neighborhood_id": "nbhd-self"}]})
        serve_wiki.NEIGHBORHOODS_FILE = self._write("neighborhoods.json", {"neighborhoods": [
            {"id": "nbhd-self", "type": "self"}]})
        serve_wiki.QUESTION_QUEUE_FILE = self._write("queue.json", {"expires_at": "2026-07-07", "queue": [
            # No inline text — the view must resolve it from the question bank by id.
            {"question_id": "A2", "category": "A", "story_function": "scene", "status": "queued"},
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
            {"name": "Dad", "aliases": [], "score": 6, "unique_answers": 2, "qualifies": True, "maps_to_focus": "dad"},
            {"name": "Sarah", "aliases": ["Sare"], "score": 4, "unique_answers": 1, "qualifies": False}]})
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

    def test_coverage_shows_category_names(self):
        self._populate()
        _, body, _ = self._view("coverage")
        # Each letter is annotated with its category title in parentheses.
        self.assertIn('cov-name">(Origins)', body)

    def test_candidates_menu_label(self):
        label = dict((slug, lbl) for slug, lbl, _ in serve_wiki.VIEWS)["candidates"]
        self.assertEqual(label, "Question Candidates")

    def test_every_view_has_a_description(self):
        for slug, _, _ in serve_wiki.VIEWS:
            self.assertIn(slug, serve_wiki.VIEW_DESCRIPTIONS,
                          f"view {slug} is missing a description")

    def test_description_injected_after_h1(self):
        body = serve_wiki._with_description("<h1>Coverage</h1><p>x</p>", "hello desc")
        self.assertEqual(body, '<h1>Coverage</h1><p class="view-desc">hello desc</p><p>x</p>')

    def test_question_bank_markers(self):
        self._populate()
        _, body, _ = self._view("question-bank")
        self.assertIn("A: Origins", body)
        self.assertIn("✓", body)
        self.assertIn("○", body)

    def test_question_bank_categories_collapsible_and_collapsed(self):
        self._populate()
        _, body, _ = self._view("question-bank")
        # Each category is a native <details> with a <summary> (overview) …
        self.assertIn('<details class="qb-cat">', body)
        self.assertIn("<summary>", body)
        # … and starts collapsed (no open attribute on any category).
        self.assertNotIn("<details class=\"qb-cat\" open", body)
        self.assertNotIn("<details open", body)

    def test_candidates_grouped_by_status(self):
        self._populate()
        _, body, _ = self._view("candidates")
        self.assertIn("candidate (2)", body)
        self.assertIn("needs_review (1)", body)
        self.assertIn("turning_point", body)

    def test_candidates_show_quality_and_category(self):
        self._populate()
        _, body, _ = self._view("candidates")
        # c1: explicit target category (with name) and stored quality score.
        self.assertIn("F (The Problem)", body)
        self.assertIn("0.88", body)
        # c2: no target and no neighborhood -> unassigned (only this one).
        self.assertEqual(body.count("unassigned"), 1)
        # c3: category inferred from its neighborhood's topic_type (self -> E),
        # so it is NOT unassigned.
        self.assertIn(">E<", body)

    def test_entities_shows_only_ungraduated_candidates(self):
        self._populate()
        _, body, _ = self._view("entities")
        # Sarah is still a candidate — she should appear.
        self.assertIn("Sarah", body)
        # Emma (page_eligible) and Dad (maps_to_focus) already have wiki pages,
        # so they are excluded — you can see them in the wiki itself.
        self.assertNotIn("Emma", body)
        self.assertNotIn("Dad", body)
        # The graduation column is gone now that only candidates are shown.
        self.assertNotIn("Graduates", body)

    def test_queue_resolves_text_and_category_name(self):
        self._populate()
        _, body, _ = self._view("queue")
        # Category letter is annotated with its English name.
        self.assertIn("A (Origins)", body)
        # Question text is resolved from the bank even when the queue item
        # carries no inline text.
        self.assertIn("Where?", body)
        # Header reads "Category", not the old cryptic "Cat".
        self.assertIn("<th>Category</th>", body)

    def test_queue_status_reflects_answered_state_from_bank(self):
        # Fixture: F1 is answered ([x]) in the bank AND present in the queue;
        # A2 is unanswered ([ ]) and queued. The view must read answered state
        # from the bank, not from the queue's own status field.
        self._populate()
        _, body, _ = self._view("queue")
        self.assertIn("answered", body)   # F1
        self.assertIn("queued", body)     # A2

    def test_queue_shows_progress_summary(self):
        # Fixture queue has 2 items (A2 unanswered, F1 answered) -> 1 of 2.
        self._populate()
        _, body, _ = self._view("queue")
        self.assertIn("1 of 2 answered · 1 remaining", body)

    def test_status_dashboard(self):
        self._populate()
        _, body, _ = self._view("status")
        self.assertIn("2 · depth", body)
        # Queue progress is answered-from-bank (F1 answered, A2 not) -> 1/2,
        # not the old delivered-flag count.
        self.assertIn("Queue answered", body)
        self.assertIn("1/2", body)
        # Candidate pipeline breakdown and detail-view links were removed.
        self.assertNotIn("Candidate pipeline", body)
        self.assertNotIn("Detail views", body)

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
