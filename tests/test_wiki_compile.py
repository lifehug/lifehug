import importlib.util
import sys
import tempfile
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


class CandidateResearchCompilerTests(unittest.TestCase):
    def setUp(self):
        self.wc = load("wiki_compile")
        self.wc._RETRACTIONS = []
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.wc.REPO_DIR = self.root
        self.wc.SOURCES_DIR = self.root / "sources"

    def tearDown(self):
        self.tmp.cleanup()

    def real_research_item(self, *, entity_type=None, name=None, slug=None):
        import candidate_research

        from tests.test_candidate_research import _entity_assessment, _focus_assessment

        if entity_type is None:
            subject, turns, assessment = _focus_assessment(confirmed=True)
        else:
            subject, turns, assessment = _entity_assessment(
                entity_type, candidate_research.ENTITY_MIN_EVIDENCE_SPANS[entity_type]
            )
            if name is not None or slug is not None:
                label = name or subject["subject_label"]
                identity_slug = slug or subject["subject_slug"]
                subject = candidate_research.build_entity_candidate_subject(
                    entity_type,
                    {
                        "name": label,
                        "slug": identity_slug,
                        "aliases": [],
                        "page_eligible": False,
                        "maps_to_focus": None,
                    },
                )
                assessment = candidate_research.build_research_assessment(
                    subject=subject,
                    evidence=assessment["evidence"],
                    dimension_evidence=assessment["dimension_evidence"],
                    seed_questions=[],
                    authoritative_turns=turns,
                )
            assessment = candidate_research.confirm_research_assessment(
                assessment,
                turn=turns[-1],
                start=0,
                end=len(turns[-1]["text"]),
                confirmed_at="2026-08-18T20:00:00Z",
                authoritative_turns=turns,
                current_subject=subject,
            )
        plan = candidate_research.build_candidate_research_source(
            assessment, authoritative_turns=turns, current_subject=subject
        )
        path = self.root / plan["source_path"]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(plan["source_bytes"])
        return next(iter(self.wc.read_manual_sources().values())), assessment, path

    @staticmethod
    def research_item(
        *, candidate_kind="focus_candidate", subject_type="place", slug="synthetic-harbor"
    ):
        return {
            "id": f"research:{candidate_kind}:{slug}",
            "source": f"sources/candidate-research/{candidate_kind}/synthetic.md",
            "title": "Candidate research",
            "body": "The literal user evidence does not need to repeat the subject label.",
            "kind": "candidate_research",
            "candidate_kind": candidate_kind,
            "candidate_id": f"candidate:{slug}",
            "subject_type": subject_type,
            "subject_label": slug.replace("-", " ").title(),
            "subject_slug": slug,
            "subject_aliases": [],
            "identity_revision": "sha256:" + "1" * 64,
            "subject_revision": "sha256:" + "2" * 64,
            "assessment_revision": "sha256:" + "3" * 64,
            "research_revision": "sha256:" + "4" * 64,
            "user_confirmed": True,
            "generated_seed_questions_evidence": False,
            "content_sha256": "5" * 64,
            "sensitivity": "private",
            "source_trust": "user_attested_primary",
            "authority": "first_person_memory",
        }

    def test_focus_research_prevents_empty_placeholder_and_is_cited(self):
        item, assessment, _path = self.real_research_item()
        descs = self.wc.plan_focuses(
            {"K": {"group": "focus", "name": "Focus — Synthetic Harbor"}},
            [],
            {},
            {item["id"]: item},
            {"entities": []},
        )
        self.assertEqual(len(descs), 1)
        self.assertIn(item, descs[0]["cited_items"])
        self.assertIn(item["source"], descs[0]["sources"])
        self.assertNotIn("no source material yet", descs[0]["summary"])
        self.assertIn("completed research", descs[0]["summary"])
        rendered = "\n".join(self.wc.cited_blocks(descs[0]["cited_items"]))
        self.assertIn(assessment["evidence"][0]["quote"], rendered)
        self.assertNotIn("lifehug:candidate-research", rendered)

    def test_wrong_kind_or_identity_does_not_fill_focus(self):
        item, _assessment, _path = self.real_research_item(entity_type="place")
        item["body"] += " Synthetic Place appears only as fuzzy body text."
        desc = self.wc.plan_focuses(
            {"K": {"group": "focus", "name": "Focus — Synthetic Place"}},
            [],
            {},
            {item["id"]: item},
            {"entities": []},
        )[0]
        self.assertEqual(desc["cited_items"], [])
        self.assertIn("no source material yet", desc["summary"])

    def test_retracted_focus_research_does_not_fill_placeholder(self):
        item = self.research_item()
        self.wc._RETRACTIONS = [
            {
                "id": "retraction",
                "retracts": item["id"],
                "retracts_path": "",
                "retracts_sha256": item["content_sha256"],
                "suppress_on": [],
                "voided": False,
            }
        ]
        desc = self.wc.plan_focuses(
            {"K": {"group": "focus", "name": "Focus — Synthetic Harbor"}},
            [],
            {},
            {item["id"]: item},
            {"entities": []},
        )[0]
        self.assertEqual(desc["cited_items"], [])
        self.assertIn("no source material yet", desc["summary"])

    def test_typed_research_supplies_citable_material_for_node_types(self):
        for entity_type in ("person", "place", "period", "object"):
            with self.subTest(entity_type=entity_type):
                slug = f"synthetic-{entity_type}"
                item = self.research_item(
                    candidate_kind="entity_candidate",
                    subject_type=entity_type,
                    slug=slug,
                )
                roster = {
                    "entities": [
                        {
                            "name": slug.replace("-", " ").title(),
                            "slug": slug,
                            "aliases": [],
                            "page_eligible": True,
                            "maps_to_focus": None,
                        }
                    ]
                }
                descs = self.wc.plan_entities(
                    entity_type, {}, {item["id"]: item}, roster, set()
                )
                self.assertEqual(len(descs), 1)
                self.assertIn(item, descs[0]["cited_items"])
                self.assertIn(item["source"], descs[0]["sources"])

    def test_typed_theme_research_is_cited_after_theme_eligibility(self):
        item, _assessment, _path = self.real_research_item(entity_type="theme")
        roster = {
            "entities": [
                {
                    "name": "Synthetic Theme",
                    "slug": "synthetic-theme",
                    "aliases": [],
                    "keywords": ["phrase-not-in-the-source-body"],
                    "page_eligible": True,
                    "maps_to_focus": None,
                }
            ]
        }
        descs = self.wc.plan_themes(
            {}, {item["id"]: item}, roster, author_slug="author"
        )
        desc = next(row for row in descs if row["slug"] == "synthetic-theme")
        self.assertIn(item, desc["cited_items"])

    def test_static_theme_cannot_consume_research_without_eligible_roster_row(self):
        item, _assessment, _path = self.real_research_item(
            entity_type="theme", name="Family", slug="family"
        )
        descs = self.wc.plan_themes(
            {}, {item["id"]: item}, {"entities": []}, author_slug="author"
        )
        self.assertFalse(any(row["slug"] == "family" for row in descs))

    def test_real_candidate_source_is_excluded_from_generic_project_keywords(self):
        item, _assessment, _path = self.real_research_item()
        desc = self.wc.plan_projects(
            {"P": {"group": "project", "name": "Synthetic Harbor"}},
            [],
            {},
            {item["id"]: item},
        )[0]
        self.assertEqual(desc["sources"], [])

    def test_malformed_utf8_candidate_source_is_not_loaded(self):
        _item, _assessment, path = self.real_research_item()
        path.write_bytes(path.read_bytes() + b"\xff")
        self.assertEqual(self.wc.read_manual_sources(), {})

    def test_research_never_changes_entity_eligibility(self):
        item = self.research_item(
            candidate_kind="entity_candidate",
            subject_type="place",
            slug="synthetic-place",
        )
        roster = {
            "entities": [
                {
                    "name": "Synthetic Place",
                    "slug": "synthetic-place",
                    "aliases": [],
                    "page_eligible": False,
                    "maps_to_focus": None,
                }
            ]
        }
        self.assertEqual(
            self.wc.plan_entities("place", {}, {item["id"]: item}, roster, set()),
            [],
        )

# ---------------------------------------------------------------------------
# Compiler: rendering
# ---------------------------------------------------------------------------


class AgentSynthesisTests(unittest.TestCase):
    """Keyless desktop path: agent writes prose to a drop file, compile consumes it."""

    def setUp(self):
        self.wc = load("wiki_compile")
        self.desc = make_desc(
            "katie", ["answers/L1.md"],
            cited_items=[{"id": "L1", "body": "drives the kids", "source": "answers/L1.md"}],
        )

    def test_parse_explicit_related_line(self):
        narrative, related = self.wc.parse_agent_narrative(
            "Related: Dave & Katie, family\n\nProse about [[belonging]] here.")
        self.assertEqual(related, ["dave-katie", "family"])
        self.assertTrue(narrative.startswith("Prose about"))
        self.assertNotIn("Related:", narrative)

    def test_related_inferred_from_wikilinks(self):
        narrative, related = self.wc.parse_agent_narrative(
            "She anchors [[dave-and-katie]] and shows up for [[family]].")
        self.assertEqual(related, ["dave-and-katie", "family"])

    def test_agent_file_consumed_and_cached(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.wc.SYNTH_DIR = Path(tmp)
            (Path(tmp) / "katie.md").write_text(
                "Related: family\n\nKatie is the anchor.", encoding="utf-8")
            cache = {}
            synth = self.wc.synthesize(self.desc, [], "m", cache, "", use_ai=False, dry_run=False)
            self.assertTrue(synth["synthesized"])
            self.assertEqual(synth["narrative"], "Katie is the anchor.")
            self.assertEqual(synth["related"], ["family"])
            self.assertIn(self.wc.cache_key(self.desc), cache)        # cached
            self.assertFalse((Path(tmp) / "katie.md").exists())        # consumed

    def test_agent_file_beats_call_ai(self):
        def boom(*a, **k):
            raise AssertionError("call_ai must not run when an agent draft exists")
        self.wc.call_ai = boom
        with tempfile.TemporaryDirectory() as tmp:
            self.wc.SYNTH_DIR = Path(tmp)
            (Path(tmp) / "katie.md").write_text("Agent prose.", encoding="utf-8")
            synth = self.wc.synthesize(self.desc, [], "m", {}, "", use_ai=True, dry_run=False)
            self.assertEqual(synth["narrative"], "Agent prose.")


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

    def test_synthesized_marker_in_frontmatter(self):
        synth_t = {"narrative": "Prose.", "related": [], "synthesized": True}
        synth_f = {"narrative": "x", "related": [], "synthesized": False}
        self.assertIn("synthesized: true", self.wc.render_page(self.desc, synth_t, [], [], {}))
        self.assertIn("synthesized: false", self.wc.render_page(self.desc, synth_f, [], [], {}))


# ---------------------------------------------------------------------------
# Compiler: non-destructive guard (never downgrade a synthesized page)
# ---------------------------------------------------------------------------


class PreserveGuardTests(unittest.TestCase):
    def setUp(self):
        self.wc = load("wiki_compile")

    def test_fallback_preserves_synthesized_page(self):
        existing = "---\ntitle: \"A\"\nsynthesized: true\n---\n\nGood prose."
        self.assertTrue(self.wc.should_preserve_existing(existing, new_synthesized=False))

    def test_fallback_overwrites_prior_excerpt_page(self):
        existing = "---\ntitle: \"A\"\nsynthesized: false\n---\n\n## What We Know"
        self.assertFalse(self.wc.should_preserve_existing(existing, new_synthesized=False))

    def test_fresh_synthesis_always_writes(self):
        existing = "---\ntitle: \"A\"\nsynthesized: true\n---\n\nGood prose."
        self.assertFalse(self.wc.should_preserve_existing(existing, new_synthesized=True))

    def test_unmarked_legacy_synthesized_page_preserved(self):
        # Pages compiled before the marker existed have no `synthesized:` field.
        # A synthesized legacy page (prose + ## Sources, no ## What We Know) must
        # still be protected on the first post-upgrade keyless compile.
        existing = "---\ntitle: \"A\"\n---\n\n# A\n\nGood prose.\n\n## Sources\n- A1"
        self.assertTrue(self.wc.should_preserve_existing(existing, new_synthesized=False))

    def test_unmarked_legacy_fallback_page_not_preserved(self):
        existing = "---\ntitle: \"A\"\n---\n\n# A\n\n## What We Know\n- A1"
        self.assertFalse(self.wc.should_preserve_existing(existing, new_synthesized=False))

    def test_page_is_synthesized_layout_inference(self):
        self.assertTrue(self.wc.page_is_synthesized("# A\n\nProse.\n\n## Sources\n- x"))
        self.assertFalse(self.wc.page_is_synthesized("# A\n\n## What We Know\n- x"))
        self.assertTrue(self.wc.page_is_synthesized("synthesized: true\n\n## What We Know"))   # marker wins
        self.assertFalse(self.wc.page_is_synthesized("synthesized: false\n\nProse.\n## Sources"))


# ---------------------------------------------------------------------------
# Compiler: mention-based people (auto pages + Focus enrichment)
# ---------------------------------------------------------------------------


def _ans(qid, body):
    return {"id": qid, "source": f"answers/{qid}.md", "body": body}


class MentionScanTests(unittest.TestCase):
    def setUp(self):
        self.wc = load("wiki_compile")

    def test_word_boundary_match(self):
        answers = {"A1": _ans("A1", "Trevor drove me home"), "A2": _ans("A2", "a retriever ran by")}
        a_hits, _ = self.wc.scan_mentions(["Trevor"], answers, {})
        ids = {h["id"] for h in a_hits}
        self.assertIn("A1", ids)
        self.assertNotIn("A2", ids)  # 'retriever' must not match 'Trevor'

    def test_two_char_names_now_matched(self):
        # 2-char names (initials like AJ/Ed) are matched via word boundaries;
        # only single-char names are skipped as noise.
        answers = {"A1": _ans("A1", "Ed was there")}
        a_hits, _ = self.wc.scan_mentions(["Ed"], answers, {})
        self.assertTrue(a_hits)
        self.assertEqual(self.wc.scan_mentions(["E"], answers, {})[0], [])  # single char → skipped

    def test_aliases_matched(self):
        answers = {"A1": _ans("A1", "Betty Jo baked bread"), "A2": _ans("A2", "nothing here")}
        a_hits, _ = self.wc.scan_mentions(["Grandma", "Betty Jo"], answers, {})
        self.assertEqual({h["id"] for h in a_hits}, {"A1"})


class PlanEntitiesTests(unittest.TestCase):
    def setUp(self):
        self.wc = load("wiki_compile")
        self.answers = {"D1": _ans("D1", "Trevor believed in me"), "D2": _ans("D2", "Trevor again")}

    def _roster(self, **over):
        p = {"name": "Trevor", "slug": "trevor", "aliases": [],
             "maps_to_focus": None, "page_eligible": True}
        p.update(over)
        return {"entities": [p]}

    def test_eligible_entity_gets_page(self):
        descs = self.wc.plan_entities("person", self.answers, {}, self._roster(), set())
        self.assertEqual(len(descs), 1)
        self.assertEqual(descs[0]["slug"], "trevor")
        self.assertEqual(descs[0]["origin"], "mention")
        self.assertEqual({c["id"] for c in descs[0]["cited_items"]}, {"D1", "D2"})

    def test_place_type_builds_place_page(self):
        answers = {"A1": _ans("A1", "We moved to Mesa when I was young"), "A2": _ans("A2", "Mesa again")}
        roster = {"entities": [{"name": "Mesa", "slug": "mesa", "aliases": [],
                                "maps_to_focus": None, "page_eligible": True}]}
        descs = self.wc.plan_entities("place", answers, {}, roster, set())
        self.assertEqual(descs[0]["type"], "place")
        self.assertEqual(descs[0]["slug"], "mesa")

    def test_place_needs_a_few_real_mentions(self):
        # A single real mention isn't enough for a place (min 2); a person needs only 1.
        one = {"A1": _ans("A1", "We passed through Reno once")}
        roster = {"entities": [{"name": "Reno", "slug": "reno", "aliases": [],
                                "maps_to_focus": None, "page_eligible": True}]}
        self.assertEqual(self.wc.plan_entities("place", one, {}, roster, set()), [])
        self.assertEqual(len(self.wc.plan_entities("person", one,
            {}, {"entities": [{"name": "Reno", "slug": "reno", "aliases": [], "page_eligible": True,
                               "maps_to_focus": None}]}, set())), 1)

    def test_not_eligible_no_page(self):
        descs = self.wc.plan_entities("person", self.answers, {}, self._roster(page_eligible=False), set())
        self.assertEqual(descs, [])

    def test_taken_slug_suppresses_duplicate(self):
        descs = self.wc.plan_entities("person", self.answers, {}, self._roster(), {"trevor"})
        self.assertEqual(descs, [])  # a Focus / prior page already owns this slug

    def test_no_mentions_no_page(self):
        descs = self.wc.plan_entities("person", {"A1": _ans("A1", "unrelated")}, {}, self._roster(), set())
        self.assertEqual(descs, [])


class FocusEnrichmentTests(unittest.TestCase):
    def setUp(self):
        self.wc = load("wiki_compile")

    def test_empty_focus_fills_from_mentions(self):
        categories = {"M": {"name": "Focus — Dad", "group": "focus"}}
        questions = []  # zero answered M questions
        answers = {"A6": _ans("A6", "my dad was an architect"),
                   "A9": _ans("A9", "my dad and I reconciled"),
                   "K2": _ans("K2", "mom was kind")}  # no dad mention
        roster = {"entities": [{"name": "Dad", "slug": "dad", "aliases": ["Father"],
                                "maps_to_focus": "dad", "page_eligible": False}]}
        descs = self.wc.plan_focuses(categories, questions, answers, {}, roster)
        dad = next(d for d in descs if d["slug"] == "dad")
        cited = {c["id"] for c in dad["cited_items"]}
        self.assertEqual(cited, {"A6", "A9"})        # dad mentions pulled in
        self.assertNotIn("K2", cited)                # non-mention excluded
        self.assertIn("mentions across the story", dad["summary"])

    def test_focus_with_category_answers_still_enriched(self):
        categories = {"K": {"name": "Focus — Mom", "group": "focus"}}
        questions = [{"id": "K1", "category": "K", "answered": True, "text": "Tell me about mom"}]
        answers = {"K1": _ans("K1", "mom taught me kindness"),
                   "A3": _ans("A3", "my mom moved us a lot")}
        descs = self.wc.plan_focuses(categories, questions, answers, {}, {"entities": []})
        mom = next(d for d in descs if d["slug"] == "mom")
        cited = {c["id"] for c in mom["cited_items"]}
        self.assertIn("K1", cited)   # category answer
        self.assertIn("A3", cited)   # cross-category mention enrichment

    def test_focus_alias_map_normalizes_focus_names(self):
        categories = {"M": {"name": "Focus — Dad", "group": "focus"}}
        answers = {"A1": _ans("A1", "Father taught me how to work")}
        roster = {"entities": [{"name": "James Taylor", "slug": "james-taylor",
                                "aliases": ["Father"], "maps_to_focus": "Focus — Dad",
                                "page_eligible": False}]}

        descs = self.wc.plan_focuses(categories, [], answers, {}, roster)

        dad = next(d for d in descs if d["slug"] == "dad")
        self.assertEqual({c["id"] for c in dad["cited_items"]}, {"A1"})


class RelationshipPlanningTests(unittest.TestCase):
    def setUp(self):
        self.wc = load("wiki_compile")

    def test_empty_focus_relationship_fills_from_mentions(self):
        categories = {"M": {"name": "Focus — Dad", "group": "focus"}}
        questions = []  # zero dedicated Dad answers
        answers = {
            "A6": _ans("A6", "my dad was an architect"),
            "A9": _ans("A9", "my father and I had a hard conversation"),
            "K2": _ans("K2", "mom was kind"),
        }
        roster = {"entities": [{"name": "Dad", "slug": "dad", "aliases": ["Father"],
                                "maps_to_focus": "dad", "page_eligible": False}]}

        descs = self.wc.plan_relationships(categories, questions, answers, {}, "Dave", roster)

        rel = next(d for d in descs if d["slug"] == "dave-and-dad")
        self.assertEqual(rel["type"], "relationship")
        self.assertEqual(rel["title"], "Dave & Dad")
        self.assertEqual({c["id"] for c in rel["cited_items"]}, {"A6", "A9"})
        self.assertNotIn("K2", {c["id"] for c in rel["cited_items"]})
        self.assertEqual(rel["seed_related"], ["dad"])
        self.assertIn("no dedicated Focus answers yet", rel["summary"])

    def test_relationship_needs_enough_mention_evidence_without_dedicated_answers(self):
        categories = {"M": {"name": "Focus — Dad", "group": "focus"}}
        answers = {"A6": _ans("A6", "my dad was an architect")}

        descs = self.wc.plan_relationships(categories, [], answers, {}, "Dave", {"entities": []})

        self.assertEqual(descs, [])

    def test_dedicated_relationship_answers_stay_primary(self):
        categories = {"K": {"name": "Focus — Mom", "group": "focus"}}
        questions = [{"id": "K1", "category": "K", "answered": True, "text": "Tell me about Mom"}]
        answers = {
            "K1": _ans("K1", "mom taught me kindness"),
            "A3": _ans("A3", "my mom moved us a lot"),
        }

        descs = self.wc.plan_relationships(categories, questions, answers, {}, "Dave", {"entities": []})

        rel = next(d for d in descs if d["slug"] == "dave-and-mom")
        self.assertEqual([c["id"] for c in rel["cited_items"]], ["K1"])
        self.assertEqual({s["id"] for s in rel["supporting_items"]}, {"A3"})
        self.assertIn("dedicated answered prompts plus 1 mentions", rel["summary"])


class ProjectGroupingTests(unittest.TestCase):
    def setUp(self):
        self.wc = load("wiki_compile")

    def test_project_label_strips_story(self):
        self.assertEqual(self.wc.project_label("Etherfuse Story"), "Etherfuse")
        self.assertEqual(self.wc.project_label("Memo"), "Memo")
        self.assertEqual(self.wc.project_label(""), "")

    def test_parse_categories_captures_qualifier(self):
        import lifehug_core
        cats = lifehug_core.parse_categories(
            "## Projects\n## F: The Problem (Etherfuse Story)\n- [ ] F1: q\n")
        self.assertEqual(cats["F"]["qualifier"], "Etherfuse Story")
        self.assertEqual(cats["F"]["name"], "The Problem")
        self.assertEqual(cats["F"]["group"], "project")

    def test_frontmatter_includes_section(self):
        fm = self.wc.frontmatter("The Problem", "project", [], [], section="Etherfuse")
        self.assertIn('section: "Etherfuse"', fm)
        # No section → field omitted.
        self.assertNotIn("section:", self.wc.frontmatter("Mom", "person", []))


class PrimaryFocusTests(unittest.TestCase):
    def setUp(self):
        self.rm = load("roadmap")
        self.qp = load("question_planner")

    def test_life_story_is_primary_with_elevated_cap(self):
        md = ("## A: Origins (Childhood)\n- [ ] A1: q\n"
              "## B: Becoming\n- [ ] B1: q\n"
              "## Projects\n## F: The Problem (Etherfuse Story)\n- [ ] F1: q\n")
        focuses = self.rm.derive_focuses(md)
        life = next(f for f in focuses if f["id"] == "my-life")
        self.assertTrue(life["primary"])
        self.assertEqual(life["cap"], self.rm.PRIMARY_CAP)
        self.assertEqual(life["tier"], "extreme")
        self.assertNotEqual(life["label"], "")
        # A sub-project is NOT primary.
        proj = next(f for f in focuses if f["type"] == "project")
        self.assertFalse(proj.get("primary", False))

    def test_rebuild_refreshes_primary_system_fields(self):
        # An old roadmap with a stale my-life (standard/0.3) must be promoted on rebuild.
        md = "## A: Origins\n- [ ] A1: q\n## B: Becoming\n- [ ] B1: q\n"
        stale = {"version": 1, "focuses": [
            {"id": "my-life", "label": "My Life", "type": "life_story",
             "tier": "standard", "cap": 0.3, "deliverable": "memoir", "categories": ["A"]}]}
        rm = self.rm.derive_roadmap(md, existing=stale)
        life = next(f for f in rm["focuses"] if f["id"] == "my-life")
        self.assertTrue(life["primary"])
        self.assertEqual(life["tier"], "extreme")   # refreshed, not the stale "standard"
        self.assertEqual(life["cap"], self.rm.PRIMARY_CAP)

    def test_primary_outweighs_extreme(self):
        fill = {"room": True, "saturation": 0.0}
        primary = self.qp.focus_weight({"primary": True, "tier": "standard"}, fill)
        extreme = self.qp.focus_weight({"tier": "extreme"}, fill)
        self.assertGreater(primary, extreme)  # the person beats any sub-focus

    def test_self_examination_classified_as_self_function(self):
        self.assertEqual(self.qp.infer_story_function("What do you value most in life?"), "value")
        self.assertEqual(self.qp.infer_story_function("Who are you when no one is watching?"), "self_image")
        # A plain event question stays outer-narrative.
        self.assertNotIn(self.qp.infer_story_function("Tell me about the house you grew up in"),
                         self.qp.SELF_FUNCTIONS)

    def test_self_functions_have_planner_caps(self):
        for fn in ("self_image", "value", "fear", "growth_edge"):
            self.assertIn(fn, self.qp.STORY_FUNCTION_CAPS)


class EntityRosterTests(unittest.TestCase):
    def setUp(self):
        self.er = load("entity_roster")

    def test_place_eligibility_is_ai_gated_not_score(self):
        # The noisy detector undercounts real places, so place eligibility is the
        # AI's judgment (qualifies), regardless of detector stats. The real
        # "a few mentions" bar is enforced at compile time (PlanEntitiesTests).
        cands = [{"entity": "Mesa", "score": 1.0, "unique_answers": 1, "evidence": []}]
        ok = self.er.normalize("place", [{"name": "Mesa", "qualifies": True, "maps_to_focus": None}],
                               cands, {}, min_score=6, min_answers=2)
        self.assertTrue(ok[0]["page_eligible"])           # low detector stats, still eligible
        no = self.er.normalize("place", [{"name": "Her", "qualifies": False, "maps_to_focus": None}],
                               [], {}, 6, 2)
        self.assertFalse(no[0]["page_eligible"])          # AI rejected → not eligible

    def test_object_is_symbolic_not_frequency(self):
        # No score/answers at all — a symbolic object still graduates.
        obj = self.er.normalize("object", [{"name": "The Cleats", "qualifies": True, "maps_to_focus": None}],
                                [], {}, min_score=0, min_answers=1)
        self.assertTrue(obj[0]["page_eligible"])
        # Not symbolic (qualifies false) → no page even if frequent.
        no = self.er.normalize("object", [{"name": "A Chair", "qualifies": False, "maps_to_focus": None}],
                               [], {}, 0, 1)
        self.assertFalse(no[0]["page_eligible"])

    def test_alias_merge_and_focus_dedup(self):
        people = self.er.normalize("period",
                                   [{"name": "My 20s", "aliases": ["Twenties", "20s"], "qualifies": True}],
                                   [{"entity": "20s", "score": 9.0, "unique_answers": 2}], {}, 6, 2)
        self.assertEqual(people[0]["unique_answers"], 2)  # picks up best-stats across aliases
        # Maps to an existing focus → never its own page.
        mapped = self.er.normalize("place", [{"name": "Etherfuse", "qualifies": True, "maps_to_focus": "etherfuse"}],
                                   [], {"etherfuse": "Etherfuse"}, 6, 2)
        self.assertFalse(mapped[0]["page_eligible"])


class ConfigMergeTests(unittest.TestCase):
    def setUp(self):
        import lifehug_core
        self.core = lifehug_core
        self._orig = (lifehug_core.PROFILE_FILE, lifehug_core.CONFIG_FILE)

    def tearDown(self):
        self.core.PROFILE_FILE, self.core.CONFIG_FILE = self._orig

    def test_profile_provides_identity_config_overrides(self):
        with tempfile.TemporaryDirectory() as d:
            prof = Path(d) / "profile.yaml"
            conf = Path(d) / "config.yaml"
            prof.write_text('name: "Dave"\nfull_name: "David James Taylor"\ntimezone: "America/Los_Angeles"\n')
            conf.write_text('anthropic_api_key: "sk-secret"\nname: "Davey"\n')  # local override + secret
            self.core.PROFILE_FILE, self.core.CONFIG_FILE = prof, conf
            cfg = self.core.load_config()
            self.assertEqual(cfg["full_name"], "David James Taylor")  # from committed profile
            self.assertEqual(cfg["timezone"], "America/Los_Angeles")
            self.assertEqual(cfg["name"], "Davey")                    # config.yaml wins on conflict
            self.assertEqual(cfg["anthropic_api_key"], "sk-secret")   # secret only in config.yaml

    def test_legacy_config_only_still_works(self):
        with tempfile.TemporaryDirectory() as d:
            conf = Path(d) / "config.yaml"
            conf.write_text('name: "Dave"\ntimezone: "UTC"\n')
            self.core.PROFILE_FILE = Path(d) / "profile.yaml"  # absent
            self.core.CONFIG_FILE = conf
            cfg = self.core.load_config()
            self.assertEqual(cfg["name"], "Dave")


class LifeStoryTests(unittest.TestCase):
    def setUp(self):
        self.wc = load("wiki_compile")

    def test_plan_life_story_builds_hub_and_arcs(self):
        categories = {"A": {"name": "Origins", "group": "main"},
                      "B": {"name": "Becoming", "group": "main"},
                      "K": {"name": "Mom", "group": "focus"}}
        questions = [{"id": "A1", "category": "A", "answered": True, "text": "q"},
                     {"id": "B1", "category": "B", "answered": True, "text": "q"}]
        answers = {"A1": _ans("A1", "origins body"), "B1": _ans("B1", "becoming body")}
        descs = self.wc.plan_life_story(categories, questions, answers, {}, "David James Taylor")
        by_origin = {d["origin"]: d for d in descs}
        self.assertIn("hub", by_origin)
        hub = by_origin["hub"]
        self.assertEqual(hub["title"], "David James Taylor")
        self.assertEqual(hub["slug"], "david-james-taylor")
        self.assertEqual(hub["type"], "life")
        arcs = [d for d in descs if d["origin"] == "arc"]
        self.assertEqual({d["title"] for d in arcs}, {"Origins", "Becoming"})  # main cats only, not Mom
        self.assertTrue(all(d["type"] == "life" for d in arcs))

    def test_hub_interleaves_across_arcs(self):
        # The hub's cited items should span categories (not all of A first).
        categories = {"A": {"name": "Origins", "group": "main"},
                      "E": {"name": "Reflection", "group": "main"}}
        questions = [{"id": "A1", "category": "A", "answered": True, "text": "q"},
                     {"id": "A2", "category": "A", "answered": True, "text": "q"},
                     {"id": "E1", "category": "E", "answered": True, "text": "q"}]
        answers = {k: _ans(k, k) for k in ("A1", "A2", "E1")}
        hub = next(d for d in self.wc.plan_life_story(categories, questions, answers, {}, "Me")
                   if d["origin"] == "hub")
        # First two cited items come from different categories (A1, E1), not A1,A2.
        self.assertEqual([c["id"] for c in hub["cited_items"][:2]], ["A1", "E1"])


class SidebarNavTests(unittest.TestCase):
    def setUp(self):
        self.sw = load("serve_wiki")

    def test_page_title_reads_frontmatter(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "dad.md"
            p.write_text('---\ntitle: "Dad"\ntype: person\n---\n# Dad\n', encoding="utf-8")
            self.assertEqual(self.sw.page_title(p), "Dad")

    def test_page_title_fallback_to_stem(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "grandma-betty-jo.md"
            p.write_text("no frontmatter here", encoding="utf-8")
            self.assertEqual(self.sw.page_title(p), "Grandma Betty Jo")

    def test_nav_groups_counts_and_active(self):
        wiki = self.sw.WIKI_DIR
        fake = [wiki / "index.md", wiki / "people" / "dad.md",
                wiki / "people" / "katie.md", wiki / "themes" / "grief.md"]
        self.sw.wiki_pages = lambda: fake
        self.sw.page_title = lambda p: p.stem.replace("-", " ").title()
        rel = str((wiki / "people" / "dad.md").relative_to(wiki.parent))
        out = self.sw.nav_html(active_rel=rel)
        self.assertIn('data-group="people"', out)
        self.assertIn(">People<", out)                 # friendly group label
        self.assertIn(">Themes<", out)
        self.assertIn('class="count">2<', out)          # People group has 2 items
        self.assertIn('class="sidebar-item active"', out)  # Dad is the active page
        self.assertIn('class="sidebar-top"', out)       # index.md as a top-level link

    def test_nav_log_excluded_and_meta_at_bottom(self):
        wiki = self.sw.WIKI_DIR
        self.sw.wiki_pages = lambda: [wiki / "index.md", wiki / "log.md",
                                      wiki / "SCHEMA.md", wiki / "people" / "dad.md"]
        self.sw.page_title = lambda p: {"SCHEMA": "Page Structure"}.get(p.stem, p.stem.title())
        out = self.sw.nav_html()
        self.assertNotIn("log.md", out)                       # compile log hidden
        self.assertIn("sidebar-meta", out)                    # meta block exists
        self.assertLess(out.index('data-group="people"'), out.index("sidebar-meta"))  # groups first
        self.assertIn(">Page Structure<", out)                # Schema relabeled

    def test_nav_projects_subgrouped_by_project(self):
        wiki = self.sw.WIKI_DIR
        self.sw.wiki_pages = lambda: [wiki / "projects" / "the-problem.md",
                                      wiki / "projects" / "building.md"]
        self.sw.page_title = lambda p: p.stem.replace("-", " ").title()
        self.sw.page_field = lambda p, key: "Etherfuse" if key == "section" else ""
        out = self.sw.nav_html()
        self.assertIn('class="sidebar-subgroup">Etherfuse<', out)   # sub-label rendered
        self.assertIn('class="sidebar-item sub"', out)              # items indented under it
        # The Projects group still wraps them.
        self.assertLess(out.index('data-group="projects"'), out.index("sidebar-subgroup"))

    def test_nav_life_section_first_with_hub_and_people_pointer(self):
        wiki = self.sw.WIKI_DIR
        self.sw.load_config = lambda *a, **k: {"name": "Dave", "full_name": "David James Taylor"}
        self.sw.wiki_pages = lambda: [wiki / "life" / "david-james-taylor.md",
                                      wiki / "life" / "origins.md",
                                      wiki / "people" / "mom.md"]
        self.sw.page_title = lambda p: p.stem.replace("-", " ").title()
        self.sw.page_field = lambda p, key: ""
        out = self.sw.nav_html()
        self.assertLess(out.index('data-group="life"'), out.index('data-group="people"'))  # life first
        self.assertIn(">David James Taylor<", out)        # section labeled with full name
        self.assertIn(">Who I am<", out)                  # hub surfaced as an item
        self.assertIn(">David James Taylor &rarr;<", out.replace("→", "&rarr;"))  # People pointer

    def test_nav_people_before_themes(self):
        wiki = self.sw.WIKI_DIR
        self.sw.wiki_pages = lambda: [wiki / "themes" / "grief.md", wiki / "people" / "dad.md"]
        self.sw.page_title = lambda p: p.stem.title()
        out = self.sw.nav_html()
        self.assertLess(out.index('data-group="people"'), out.index('data-group="themes"'))


class MentionRegexTests(unittest.TestCase):
    def setUp(self):
        self.wc = load("wiki_compile")

    def test_two_char_initials_name_matches(self):
        rx = self.wc._mention_regex(["AJ"])
        self.assertIsNotNone(rx)
        self.assertTrue(rx.search("and then AJ showed up"))
        # Word boundaries prevent substring hits inside other words.
        self.assertFalse(rx.search("the major leagues"))

    def test_single_char_name_still_skipped(self):
        self.assertIsNone(self.wc._mention_regex(["X"]))


class OrphanCleanupTests(unittest.TestCase):
    """cleanup_orphan_entity_pages: mention pages leave with their roster entry."""

    PAGE = "---\ntitle: \"{title}\"\ntype: person\norigin: {origin}\n---\n\nBody.\n"

    def setUp(self):
        self.wc = load("wiki_compile")
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.wc.REPO_DIR = root
        self.wc.WIKI_DIR = root / "wiki"
        self.wc.TYPE_DIRS = {"person": self.wc.WIKI_DIR / "people"}
        self.wc._MENTION_CLEANUP_TYPES = ("person",)
        self.wc.TYPE_DIRS["person"].mkdir(parents=True)
        self.rosters = {"person": {"entities": []}}
        self.wc.load_roster = lambda t="person": self.rosters.get(t, {"entities": []})

    def tearDown(self):
        self.tmp.cleanup()

    def page(self, slug, origin="mention"):
        path = self.wc.TYPE_DIRS["person"] / f"{slug}.md"
        path.write_text(self.PAGE.format(title=slug.title(), origin=origin), encoding="utf-8")
        return path

    def roster_entity(self, name, slug, eligible=True, maps_to=None):
        self.rosters["person"]["entities"].append({
            "name": name, "slug": slug, "aliases": [], "qualifies": True,
            "maps_to_focus": maps_to, "page_eligible": eligible,
        })

    def test_mention_orphan_removed(self):
        self.roster_entity("Grandma Betty Jo", "grandma-betty-jo")
        keep = self.page("grandma-betty-jo")
        orphan = self.page("betty-jo")  # split remnant, not in roster
        removed = self.wc.cleanup_orphan_entity_pages({"grandma-betty-jo"})
        self.assertEqual([p.name for p in removed], ["betty-jo.md"])
        self.assertTrue(keep.exists())
        self.assertFalse(orphan.exists())

    def test_focus_origin_page_never_touched(self):
        self.roster_entity("Trevor", "trevor")
        focus_page = self.page("katie", origin="focus")
        removed = self.wc.cleanup_orphan_entity_pages(set())
        self.assertEqual(removed, [])
        self.assertTrue(focus_page.exists())

    def test_empty_roster_deletes_nothing(self):
        orphan = self.page("betty-jo")
        removed = self.wc.cleanup_orphan_entity_pages(set())
        self.assertEqual(removed, [])
        self.assertTrue(orphan.exists())  # no roster signal → never delete

    def test_eligible_but_unplanned_entity_kept(self):
        # Entity still in roster/eligible but missed the mention threshold this run.
        self.roster_entity("Trevor", "trevor")
        page = self.page("trevor")
        removed = self.wc.cleanup_orphan_entity_pages(set())
        self.assertEqual(removed, [])
        self.assertTrue(page.exists())

    def test_maps_to_focus_page_removed(self):
        # Wife remapped to the katie Focus → its standalone page must go.
        self.roster_entity("Wife", "wife", eligible=False, maps_to="katie")
        page = self.page("wife")
        removed = self.wc.cleanup_orphan_entity_pages(set())
        self.assertEqual([p.name for p in removed], ["wife.md"])
        self.assertFalse(page.exists())

    def test_dry_run_reports_without_deleting(self):
        self.roster_entity("Trevor", "trevor")
        orphan = self.page("betty-jo")
        removed = self.wc.cleanup_orphan_entity_pages(set(), dry_run=True)
        self.assertEqual([p.name for p in removed], ["betty-jo.md"])
        self.assertTrue(orphan.exists())


if __name__ == "__main__":
    unittest.main()
