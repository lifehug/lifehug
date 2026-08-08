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
import lifehug_core  # noqa: E402


class WikiViewsTests(unittest.TestCase):
    def setUp(self):
        # Keep the fixture under the real-path worktree parent. On macOS the
        # default /var/folders prefix traverses the /var symlink, which the
        # production no-follow vault I/O authority correctly rejects.
        self.tmp = Path(tempfile.mkdtemp(dir=ROOT.parent))
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
            (serve_wiki, "CLASSIFICATIONS_DIR"): serve_wiki.CLASSIFICATIONS_DIR,
            (serve_wiki, "ANSWERS_DIR"): serve_wiki.ANSWERS_DIR,
            (serve_wiki, "SECOND_VOICE_OFFERS_FILE"): serve_wiki.SECOND_VOICE_OFFERS_FILE,
            (roadmap, "QUESTIONS_FILE"): roadmap.QUESTIONS_FILE,
            (roadmap, "ROADMAP_FILE"): roadmap.ROADMAP_FILE,
            (entity_roster, "ENTITY_DIR"): entity_roster.ENTITY_DIR,
            (lifehug_core, "REPO_DIR"): lifehug_core.REPO_DIR,
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
        # v124 consolidates focuses/coverage/question-bank into foundation.
        order = [slug for slug, _, _ in serve_wiki.VIEWS]
        self.assertEqual(order, [
            "status", "mirror", "graph", "timeline", "book", "foundation",
            "recommendations", "candidates", "queue",
            "entities", "sources", "artifacts", "reports", "privacy",
        ])

    def test_legacy_view_slugs_redirect_to_foundation(self):
        # The absorbed views are gone from the registry but their URLs
        # permanently redirect, so old bookmarks and hub links keep working.
        for slug in ("focuses", "coverage", "question-bank"):
            self.assertNotIn(slug, serve_wiki.VIEW_MAP)
            self.assertEqual(serve_wiki.LEGACY_VIEW_REDIRECTS[slug], "foundation")

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
        lifehug_core.REPO_DIR = self.tmp / "no-repo"  # no outputs/ either
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

    def test_foundation_focus_level(self):
        # Focus rows keep everything the old Focuses view showed: label with
        # wiki link, tier/phase badges, saturation bar, objective→deliverable.
        self._populate()
        _, body, _ = self._view("foundation")
        self.assertIn("My Life", body)
        self.assertIn("Etherfuse", body)
        self.assertIn("bar-fill", body)
        self.assertIn("finishing", body)
        self.assertIn('href="/page/wiki/life/my-life.md"', body)
        self.assertIn('<details class="fnd-focus">', body)

    def test_foundation_categories_nested_with_live_status(self):
        # Category rows are computed live from the question bank (never the
        # cached coverage.json): A is 1/2 → yellow, F is 2/2 → green. Names
        # come from the bank's category headings.
        self._populate()
        # Poison the cache to prove the view doesn't read it.
        serve_wiki.COVERAGE_FILE = self._write("coverage.json", {"categories": {
            "A": {"total": 9, "answered": 0, "status": "red"}}})
        _, body, _ = self._view("foundation")
        self.assertIn("A: Origins", body)
        self.assertIn("F: The Problem", body)
        self.assertIn("1/2", body)
        self.assertIn("2/2", body)
        self.assertIn("yellow", body)
        self.assertIn("green", body)
        self.assertNotIn("0/9", body)

    def test_foundation_questions_nested(self):
        self._populate()
        _, body, _ = self._view("foundation")
        self.assertIn("✓", body)
        self.assertIn("○", body)
        self.assertIn("A1", body)
        self.assertIn("Earliest?", body)

    def test_foundation_starts_collapsed(self):
        self._populate()
        _, body, _ = self._view("foundation")
        self.assertNotIn("<details open", body)
        self.assertNotIn('<details class="fnd-focus" open', body)
        self.assertNotIn('<details class="qb-cat" open', body)

    def test_foundation_orphan_categories_listed(self):
        # A bank category no focus claims still shows, under its own heading.
        self._populate()
        qbank = self._write("question-bank.md",
            "## A: Origins (Childhood)\n- [x] A1: Earliest? *(2026-01-01)*\n- [ ] A2: Where?\n"
            "## F: The Problem (Etherfuse Story)\n- [x] F1: What?\n- [x] F2: Why you?\n"
            "## Z: Loose Ends\n- [ ] Z1: What else?\n")
        serve_wiki.QUESTIONS_FILE = qbank
        _, body, _ = self._view("foundation")
        self.assertIn("Not part of any focus", body)
        self.assertIn("Z: Loose Ends", body)

    def test_foundation_overall_footer(self):
        self._populate()
        _, body, _ = self._view("foundation")
        # my-life target 4 + etherfuse target 2 = 6; answered 1 + 2 = 3.
        self.assertIn("Overall: 3/6 answered", body)

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

    # --- artifacts view (v90: grouped by Focus) ---

    def _populate_artifacts(self):
        roadmap.ROADMAP_FILE = self._write("roadmap.json", {"version": 1, "focuses": [
            {"id": "mom", "label": "Mom", "type": "person", "tier": "standard",
             "objective": "story of Mom", "deliverable": "letter", "categories": ["K"],
             "target_depth": 22, "phase": "active", "wiki_node": "wiki/people/mom.md"},
            {"id": "katie", "label": "Katie", "type": "person", "tier": "standard",
             "objective": "story of Katie", "deliverable": "letter", "categories": ["L"],
             "target_depth": 21, "phase": "active", "wiki_node": None}]})
        out = self.tmp / "outputs"
        self._write("outputs/mothers-day-letter-desi/meta.yaml",
                    "title: mothers-day-letter-desi\nformat: letter\nsubject: desi\n"
                    "occasion: Mother's Day\ncategories: [K]\ncreated: 2026-05-08\n")
        self._write("outputs/mothers-day-letter-desi/v1.md", "Dear Mom, thank you.\n")
        self._write("outputs/my-katie/meta.yaml",
                    "title: my-katie\nformat: letter\nsubject: katie\n"
                    "categories: [L]\ncreated: 2026-06-25\n")
        self._write("outputs/my-katie/v1.md", "Katie, my love.\n")
        (out / "my-katie" / "v1.pdf").write_bytes(b"%PDF-1.4 fake")
        self._write("outputs/my-katie/artifact.json", {
            "delivered_at": "2026-06-26T00:00:00Z",
            "promoted_sources": [{"kind": "final", "path": "sources/artifacts/x.md"}]})
        self._write("outputs/orphan-piece/v1.md", "No metadata here.\n")
        lifehug_core.REPO_DIR = self.tmp
        return out

    def test_artifacts_grouped_by_focus(self):
        self._populate_artifacts()
        _, body, _ = self._view("artifacts")
        # Person groups: subject name appended when it differs from the label.
        self.assertIn("Mom (Desi)", body)
        self.assertIn('art-group-title">Katie</span>', body)
        # Focus with a wiki node links to it.
        self.assertIn('href="/page/wiki/people/mom.md"', body)
        # Katie's piece is newer (2026-06-25) -> her group comes first.
        self.assertLess(body.index('art-group-title">Katie'), body.index("Mom (Desi)"))
        # Humanized titles, not slugs, in the headings.
        self.assertIn("Mother&#x27;s Day letter", body)
        self.assertIn("<h3>My Katie", body)

    def test_artifacts_groups_collapsed_by_default(self):
        self._populate_artifacts()
        _, body, _ = self._view("artifacts")
        # Every group is a collapsible bar (Question Bank / Timeline idiom) …
        self.assertIn('<details class="art-group">', body)
        # … starting collapsed, with the piece count visible on the bar.
        self.assertNotIn('<details class="art-group" open', body)
        self.assertIn("1 piece(s) · person · → letter · categories K", body)  # Mom bar counts

    def test_artifacts_badges_and_assets(self):
        self._populate_artifacts()
        _, body, _ = self._view("artifacts")
        # Occasion is a badge, never a group.
        self.assertIn(">Mother&#x27;s Day</span>", body)
        self.assertNotIn('art-group-title">Mother', body)
        # delivered + promoted badges read the fields artifact.py actually
        # writes (promoted_sources — the old view read a never-written key).
        self.assertIn("delivered", body)
        self.assertIn("promoted to source", body)
        # The PDF sidecar is linked through the /artifact-file/ route.
        self.assertIn('href="/artifact-file/my-katie/v1.pdf"', body)

    def test_artifacts_unfiled_group_last_with_hint(self):
        self._populate_artifacts()
        _, body, _ = self._view("artifacts")
        unfiled = 'art-group-title">Unfiled</span>'
        self.assertIn(unfiled, body)
        self.assertIn("meta.yaml", body)  # repair hint
        self.assertLess(body.index('art-group-title">Katie'), body.index(unfiled))
        self.assertLess(body.index("Mom (Desi)"), body.index(unfiled))

    def test_artifacts_safe_without_roadmap(self):
        # Artifacts exist but roadmap.json is missing and the question bank is
        # empty -> everything lands in Unfiled, nothing raises.
        self._populate_artifacts()
        roadmap.ROADMAP_FILE = self.tmp / "missing-roadmap.json"
        roadmap.QUESTIONS_FILE = self.tmp / "missing-bank.md"
        _, body, _ = self._view("artifacts")
        self.assertIn('art-group-title">Unfiled</span>', body)
        self.assertIn("My Katie", body)

    def test_graph_nodes_edges_and_weight(self):
        self._populate()
        g = serve_wiki.graph_data()
        self.assertEqual(len(g["nodes"]), 2)
        self.assertEqual(len(g["edges"]), 1)
        self.assertEqual(g["edges"][0]["weight"], 2)  # shared answers/A1.md -> 1 + 1
        mylife = next(n for n in g["nodes"] if n["id"].endswith("my-life.md"))
        self.assertEqual(mylife["sources"], 3)
        self.assertIn("sat", mylife)


class RevisionFooterTests(unittest.TestCase):
    """v98: revision footer, /artifact-version + /artifact-diff helpers,
    Thoughts group for subjectless essays."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(dir=ROOT.parent))
        self._saved = {
            (roadmap, "ROADMAP_FILE"): roadmap.ROADMAP_FILE,
            (lifehug_core, "REPO_DIR"): lifehug_core.REPO_DIR,
        }
        roadmap.ROADMAP_FILE = self._write("roadmap.json", {"version": 1, "focuses": [
            {"id": "mom", "label": "Mom", "type": "person", "tier": "standard",
             "objective": "story of Mom", "deliverable": "letter", "categories": ["K"],
             "target_depth": 22, "phase": "active", "wiki_node": None}]})
        # A subjectless essay with two saved revisions (the opinion lane shape).
        self._write("outputs/mantle-essay/meta.yaml",
                    "title: mantle-essay\nformat: essay\nsubject: ''\ncreated: 2026-07-06\n")
        self._write("outputs/mantle-essay/v1.md",
                    "# Mantle\n\nParents wore a mantle of duty.\n")
        self._write("outputs/mantle-essay/v2.md",
                    "# Mantle\n\nParents wore a heavy mantle of responsibility.\n")
        self._write("outputs/mantle-essay/artifact.json", {
            "versions": [
                {"version": 1, "path": "outputs/mantle-essay/v1.md",
                 "created_at": "2026-07-06T01:00:00Z", "model": "test-model"},
                {"version": 2, "path": "outputs/mantle-essay/v2.md",
                 "created_at": "2026-07-06T02:00:00Z", "model": "test-model",
                 "feedback": "tighten the middle"},
            ],
            "final_version": 2})
        # A single-version letter filed under a Focus.
        self._write("outputs/mom-letter/meta.yaml",
                    "title: mom-letter\nformat: letter\nsubject: mom\n"
                    "categories: [K]\ncreated: 2026-07-01\n")
        self._write("outputs/mom-letter/v1.md", "Dear Mom.\n")
        lifehug_core.REPO_DIR = self.tmp

    def tearDown(self):
        for (mod, name), val in self._saved.items():
            setattr(mod, name, val)

    def _write(self, name, data):
        p = self.tmp / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(data if isinstance(data, str) else json.dumps(data))
        return p

    def _body(self):
        return serve_wiki.VIEW_MAP["artifacts"]()[1]

    def test_footer_links_every_version_with_final_star(self):
        body = self._body()
        self.assertIn('href="/artifact-version/mantle-essay/1"', body)
        self.assertIn('href="/artifact-version/mantle-essay/2"', body)
        self.assertIn(">2★</a>", body)
        self.assertIn('href="/artifact-diff/mantle-essay/1/2"', body)

    def test_single_version_artifact_has_no_diff_link(self):
        body = self._body()
        self.assertIn('href="/artifact-version/mom-letter/1"', body)
        self.assertNotIn("/artifact-diff/mom-letter", body)

    def test_footer_tooltip_carries_feedback_note(self):
        self.assertIn("tighten the middle", self._body())

    def test_subjectless_essay_groups_under_thoughts(self):
        body = self._body()
        self.assertIn('art-group-title">Thoughts</span>', body)
        self.assertNotIn('art-group-title">Unfiled</span>', body)
        # Thoughts renders after Focus groups.
        self.assertLess(body.index('art-group-title">Mom'),
                        body.index('art-group-title">Thoughts'))

    def test_version_page_renders_content_and_nav(self):
        result = serve_wiki.artifact_version_html("mantle-essay", "1")
        self.assertIsNotNone(result)
        title, body = result
        self.assertIn("v1", title)
        self.assertIn("mantle of duty", body)
        self.assertIn('href="/views/artifacts"', body)
        self.assertIn('href="/artifact-version/mantle-essay/2"', body)

    def test_final_version_page_marked(self):
        _, body = serve_wiki.artifact_version_html("mantle-essay", "2")
        self.assertIn("★ final", body)
        self.assertIn("Revision note: tighten the middle", body)

    def test_version_guards(self):
        for slug, n in (("../mantle-essay", "1"), ("/etc", "1"),
                        ("mantle-essay", "x"), ("nope", "1"),
                        ("mantle-essay", "9")):
            self.assertIsNone(serve_wiki.artifact_version_html(slug, n), (slug, n))

    def test_diff_marks_insertions_and_deletions(self):
        result = serve_wiki.artifact_diff_html("mantle-essay", "1", "2")
        self.assertIsNotNone(result)
        _, body = result
        self.assertIn("<ins>", body)
        self.assertIn("<del>", body)
        self.assertIn("responsibility.", body[body.index("<ins>"):])
        self.assertIn("duty.", body[body.index("<del>"):])
        self.assertIn("word(s) added", body)
        self.assertIn("Revision note for v2: tighten the middle", body)

    def test_diff_guards(self):
        for slug, a, b in (("../x", "1", "2"), ("mantle-essay", "1", "x"),
                           ("mantle-essay", "1", "9"), ("nope", "1", "2")):
            self.assertIsNone(serve_wiki.artifact_diff_html(slug, a, b), (slug, a, b))


class HomeHubTests(WikiViewsTests):
    """The home action hub (v99): invitations lead, stats strip below."""

    def _point_at_nothing(self):
        for name in ["QUESTIONS_FILE", "COVERAGE_FILE", "QUESTION_CANDIDATES_FILE",
                     "QUESTION_QUEUE_FILE", "SOURCE_MANIFEST_FILE",
                     "SOURCE_LINT_FINDINGS_FILE", "FOCUS_RECS_FILE", "ROTATION_FILE",
                     "SECOND_VOICE_OFFERS_FILE"]:
            setattr(serve_wiki, name, self.tmp / "missing.json")
        serve_wiki.CLASSIFICATIONS_DIR = self.tmp / "no-classifications"
        serve_wiki.ANSWERS_DIR = self.tmp / "no-answers"
        serve_wiki.WIKI_DIR = self.tmp / "no-wiki"
        roadmap.QUESTIONS_FILE = self.tmp / "missing.json"
        roadmap.ROADMAP_FILE = self.tmp / "missing.json"
        lifehug_core.REPO_DIR = self.tmp / "no-repo"

    def test_view_groups_cover_every_view(self):
        grouped = {s for _, slugs in serve_wiki.VIEW_GROUPS for s in slugs}
        registered = {slug for slug, _, _ in serve_wiki.VIEWS}
        # Every grouped slug that exists is registered; every registered slug
        # renders in the menu (grouped or via the System fallback).
        menu = serve_wiki.menu_html()
        for slug in registered:
            self.assertIn(f"/views/{slug}", menu)
        for title, _ in serve_wiki.VIEW_GROUPS:
            self.assertIn(title, menu)
        # Group slugs may reference future views (e.g. mirror before Phase 2),
        # but a registered view outside any group must land in System.
        self.assertTrue(registered - grouped == set() or "System" in menu)

    def test_home_empty_state_is_calm(self):
        self._point_at_nothing()
        title, body, wide = serve_wiki.view_home()
        self.assertEqual(title, "Today")
        self.assertFalse(wide)
        self.assertIn("The loop is fed", body)
        self.assertNotIn("hub-cta", body)  # the quiet card carries no verb

    def test_home_full_state_cards(self):
        self._populate()
        serve_wiki.CLASSIFICATIONS_DIR = self.tmp / "classifications"
        self._write("classifications/answers-a1.json", {
            "source_path": "answers/A1.md",
            "contradictions": ["He says X and also says Y — both feel true."],
            "self_understanding_insights": ["Core value: people over things."]})
        self._write("answers/A1.md",
                    "---\nanswered_date: \"2020-01-01\"\n---\n# Question A1: Earliest?\n\nThe old porch, the dog, the summer.\n")
        serve_wiki.ANSWERS_DIR = self.tmp / "answers"
        serve_wiki.SECOND_VOICE_OFFERS_FILE = self.tmp / "missing.json"
        data = serve_wiki.home_data()
        kinds = [c["kind"] for c in data["invitations"]]
        self.assertIn("sit_with", kinds)      # classification-backed pick
        self.assertIn("question", kinds)      # A2 is queued and unanswered
        self.assertIn("review", kinds)        # open candidates + pending rec
        self.assertIn("memory", kinds)        # 2020 answer resurfaces
        self.assertLessEqual(len(kinds), 5)
        self.assertEqual(kinds[-1], "memory")  # the standing last slot
        title, body, _ = serve_wiki.view_home()
        self.assertIn("statstrip", body)
        self.assertIn("hub-card", body)
        # No guilt mechanics on the front page.
        self.assertNotIn("overdue", body.lower())
        self.assertNotIn("streak", body.lower())

    def test_home_next_question_resolves_bank_text(self):
        self._populate()
        self._point_at_nothing_extras = None  # keep classifications/answers empty
        serve_wiki.CLASSIFICATIONS_DIR = self.tmp / "no-classifications"
        serve_wiki.ANSWERS_DIR = self.tmp / "no-answers"
        serve_wiki.SECOND_VOICE_OFFERS_FILE = self.tmp / "missing.json"
        card = serve_wiki._hub_card_next_question()
        self.assertIsNotNone(card)
        self.assertIn("A2", card["body"])
        self.assertIn("Where?", card["body"])

    def test_second_voice_card_this_month(self):
        self._populate()
        import datetime as _dt
        month = _dt.date.today().strftime("%Y-%m")
        serve_wiki.SECOND_VOICE_OFFERS_FILE = self._write("sv.json", {"offered": [
            {"key": "emma::what-do-you-remember-first", "person": "Emma", "month": month},
            {"key": "old::stale", "person": "Old", "month": "2020-01"}]})
        card = serve_wiki._hub_card_second_voice()
        self.assertIsNotNone(card)
        self.assertIn("Emma", card["title"])
        self.assertIn("what do you remember first", card["body"])
        # Emma has a wiki page in the fixture set, so the card links to it.
        self.assertIn("/page/wiki/people/emma.md", card["href"])

    def test_daily_pick_is_stable_within_a_day(self):
        self.assertEqual(serve_wiki._daily_pick(7), serve_wiki._daily_pick(7))
        self.assertEqual(serve_wiki._daily_pick(1), 0)


if __name__ == "__main__":
    unittest.main()
