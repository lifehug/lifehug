"""Tests for the entity-owner-verdicts contract (ADR 0013).

`owner_verdict` is the settled-decision accelerator/veto over the fully
automatic entity-graduation floor (ADR 0006, the Convergence Principle):
`graduate` fast-forwards an entity the owner already knows matters past the
automatic score/mention bar; `never` is a permanent veto for the junk class
the AI keeps re-considering. The property that makes both worth having —
and the one these tests exist to pin — is that a verdict SURVIVES ANY
subsequent AI/deterministic refresh, including one whose raw output
actively contradicts it or omits the entity from its candidate list
entirely. The verdict lives ON the roster record; there is no parallel
store.

Layers covered, mirroring the contract's Test plan:
  - `entity_roster.normalize()` — the per-entry eligibility override.
  - `entity_roster.apply_previous_decisions()` — the settled-fact carry-
    forward, including the two edge cases that make it a REAL guarantee
    (a contradicting raw response; an empty/omitting refresh).
  - `entity_verdict.py` — the verb: refusals, atomic roster mutation, the
    `clear` recompute path, and the CLI surface.
  - `wiki_compile.plan_entities` — the >= 1 real-mention exception for
    owner-graduated entities (never a zero-mention page).
  - `wiki_compile.cleanup_orphan_entity_pages` — never removes an owner-
    graduated page while the verdict stands (a regression pin on existing
    behavior this contract depends on, not new code).
  - `serve_wiki.py` — the candidates lane excludes vetoed entities, the
    Owner-decided roster-browser table renders the `owner` tag, and the
    `/actions/entity-verdict` handler + registered route.

Everything here is synthetic — a throwaway roster/vault per test, never the
founder vault (AGENTS.md's boundary rule).
"""

from __future__ import annotations

import contextlib
import importlib.util
import io
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SYSTEM = ROOT / "system"
sys.path.insert(0, str(SYSTEM))
sys.path.insert(0, str(ROOT / "tests"))

from tempdirs import root_parent_tmp  # noqa: E402

import entity_roster  # noqa: E402
import entity_verdict  # noqa: E402
import jobs  # noqa: E402
import lifehug  # noqa: E402
import serve_wiki  # noqa: E402


def load(name):
    """Load a private copy of system/<name>.py WITHOUT clobbering the shared
    sys.modules entry (test_wiki_compile.py's convention) — needed only for
    the wiki_compile tests below, which monkeypatch module globals."""
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


def _ans(qid, body):
    return {"id": qid, "source": f"answers/{qid}.md", "body": body}


# ---------------------------------------------------------------------------
# entity_roster.normalize(): the eligibility override (Scope 1)
# ---------------------------------------------------------------------------


class NormalizeOwnerVerdictTests(unittest.TestCase):
    def test_graduate_forces_eligibility_below_thresholds(self):
        raw = [{"name": "Trevor", "aliases": [], "qualifies": False,
                "maps_to_focus": None, "owner_verdict": "graduate"}]
        out = entity_roster.normalize("person", raw, [], {}, min_score=8.0, min_answers=2)
        self.assertTrue(out[0]["page_eligible"])
        self.assertEqual(out[0]["owner_verdict"], "graduate")
        self.assertFalse(out[0]["qualifies"])  # the AI's own judgment is left as-is

    def test_never_forces_ineligibility_above_thresholds(self):
        candidates = [{"entity": "Trevor", "score": 46.0, "unique_answers": 8,
                       "cross_categories": [], "evidence": []}]
        raw = [{"name": "Trevor", "aliases": [], "qualifies": True,
                "maps_to_focus": None, "owner_verdict": "never"}]
        out = entity_roster.normalize("person", raw, candidates, {}, min_score=8.0, min_answers=2)
        self.assertFalse(out[0]["page_eligible"])
        self.assertEqual(out[0]["owner_verdict"], "never")
        self.assertEqual(out[0]["score"], 46.0)  # only page_eligible is vetoed, not the record

    def test_mapped_entity_wins_over_graduate(self):
        # maps_to_focus always wins — entity_verdict.py refuses to SET
        # graduate on a mapped entity, and normalize() holds the same guard
        # continuously (e.g. a later refresh maps an already-graduated one).
        raw = [{"name": "Wife", "aliases": [], "qualifies": True,
                "maps_to_focus": "katie", "owner_verdict": "graduate"}]
        out = entity_roster.normalize("person", raw, [], {"katie": "Katie"},
                                      min_score=8.0, min_answers=2)
        self.assertFalse(out[0]["page_eligible"])
        self.assertEqual(out[0]["owner_verdict"], "graduate")  # the field itself is untouched

    def test_no_verdict_is_unaffected(self):
        raw = [{"name": "Trevor", "aliases": [], "qualifies": False, "maps_to_focus": None}]
        out = entity_roster.normalize("person", raw, [], {}, min_score=8.0, min_answers=2)
        self.assertFalse(out[0]["page_eligible"])
        self.assertNotIn("owner_verdict", out[0])

    def test_unrecognized_verdict_value_is_ignored(self):
        raw = [{"name": "Trevor", "aliases": [], "qualifies": True, "maps_to_focus": None,
                "owner_verdict": "maybe-later"}]
        out = entity_roster.normalize("person", raw, [], {}, min_score=8.0, min_answers=2)
        self.assertNotIn("owner_verdict", out[0])


# ---------------------------------------------------------------------------
# entity_roster.apply_previous_decisions(): the settled fact survives ANY
# subsequent AI/deterministic refresh (the contract's headline property)
# ---------------------------------------------------------------------------

PREV_GRADUATED = {"entities": [
    {"name": "Trevor", "slug": "trevor", "aliases": [], "qualifies": False,
     "maps_to_focus": None, "score": 0.0, "unique_answers": 0,
     "page_eligible": True, "owner_verdict": "graduate"},
]}

PREV_VETOED = {"entities": [
    {"name": "Some Junk", "slug": "some-junk", "aliases": [], "qualifies": True,
     "maps_to_focus": None, "score": 46.0, "unique_answers": 8,
     "page_eligible": False, "owner_verdict": "never"},
]}


class ApplyPreviousDecisionsOwnerVerdictTests(unittest.TestCase):
    def test_graduate_survives_a_contradicting_raw_response(self):
        # The AI's fresh raw output actively tries to unqualify Trevor —
        # the settled graduate verdict must still win. (`forced` tracks
        # re-splits/renames/mapping-restores, not verdict-carrying alone,
        # so it is not asserted here — the field and the eligibility it
        # drives are the properties that matter.)
        raw, _forced = entity_roster.apply_previous_decisions(
            [{"name": "Trevor", "aliases": [], "qualifies": False, "maps_to_focus": None}],
            PREV_GRADUATED)
        self.assertEqual(raw[0]["owner_verdict"], "graduate")
        normalized = entity_roster.normalize("person", raw, [], {}, min_score=8.0, min_answers=2)
        self.assertTrue(normalized[0]["page_eligible"])

    def test_never_survives_a_contradicting_raw_response(self):
        # The AI's fresh raw output tries to requalify the vetoed junk
        # entity with a strong score — the settled never verdict must win.
        candidates = [{"entity": "Some Junk", "score": 46.0, "unique_answers": 8,
                       "cross_categories": [], "evidence": []}]
        raw, forced = entity_roster.apply_previous_decisions(
            [{"name": "Some Junk", "aliases": [], "qualifies": True, "maps_to_focus": None}],
            PREV_VETOED)
        self.assertEqual(raw[0]["owner_verdict"], "never")
        normalized = entity_roster.normalize("person", raw, candidates, {}, min_score=8.0, min_answers=2)
        self.assertFalse(normalized[0]["page_eligible"])

    def test_verdict_survives_when_raw_output_omits_the_entity_entirely(self):
        # A low/zero-score owner-graduated entity may not even reach the
        # AI's candidate list on a given refresh — its verdict is not
        # contingent on this run's raw output naming it at all.
        raw, forced = entity_roster.apply_previous_decisions(
            [{"name": "Someone Else", "aliases": [], "qualifies": True, "maps_to_focus": None}],
            PREV_GRADUATED)
        trevor = next((e for e in raw if e["name"] == "Trevor"), None)
        self.assertIsNotNone(trevor)
        self.assertEqual(trevor["owner_verdict"], "graduate")
        self.assertGreaterEqual(forced, 1)

    def test_verdict_survives_an_empty_refresh(self):
        raw, forced = entity_roster.apply_previous_decisions([], PREV_GRADUATED)
        self.assertEqual(len(raw), 1)
        self.assertEqual(raw[0]["owner_verdict"], "graduate")
        self.assertEqual(forced, 1)

    def test_unverdicted_entity_is_still_dropped_by_an_empty_refresh(self):
        # Regression guard: an entity with NO owner_verdict keeps the
        # pre-existing behavior (contingent on this refresh's raw output) —
        # only a SETTLED verdict is exempt from that.
        prev = {"entities": [{"name": "Nobody Special", "slug": "nobody-special",
                              "aliases": [], "qualifies": True, "maps_to_focus": None,
                              "score": 10.0, "unique_answers": 3, "page_eligible": True}]}
        raw, forced = entity_roster.apply_previous_decisions([], prev)
        self.assertEqual(raw, [])
        self.assertEqual(forced, 0)

    def test_no_previous_roster_is_identity_regardless_of_verdict_fields(self):
        entries = [{"name": "Grandma", "aliases": [], "qualifies": True, "maps_to_focus": None}]
        raw, forced = entity_roster.apply_previous_decisions(entries, None)
        self.assertEqual(raw, entries)
        self.assertEqual(forced, 0)


# ---------------------------------------------------------------------------
# entity_verdict.py: the verb — refusals, atomic mutation, clear, CLI
# ---------------------------------------------------------------------------


class EntityVerdictCLITests(unittest.TestCase):
    def setUp(self):
        self.tmp = root_parent_tmp(self, ROOT, prefix="lifehug-entity-verdict-")
        self._saved_dir = entity_roster.ENTITY_DIR
        entity_roster.ENTITY_DIR = self.tmp / "state" / "entity_rosters"
        entity_verdict.roster_file = entity_roster.roster_file

    def tearDown(self):
        entity_roster.ENTITY_DIR = self._saved_dir

    def _seed(self, entity_type, entities):
        entity_roster.write_roster(entity_type, entities)

    def test_graduate_forces_eligibility_below_threshold(self):
        self._seed("person", [{"name": "Trevor", "slug": "trevor", "aliases": [],
                               "qualifies": False, "maps_to_focus": None,
                               "score": 1.0, "unique_answers": 0, "page_eligible": False}])
        entity = entity_verdict.apply_verdict("person", "trevor", "graduate")
        self.assertTrue(entity["page_eligible"])
        self.assertEqual(entity["owner_verdict"], "graduate")
        on_disk = entity_roster.load_roster("person")["entities"][0]
        self.assertTrue(on_disk["page_eligible"])
        self.assertEqual(on_disk["owner_verdict"], "graduate")

    def test_never_forces_ineligibility_above_threshold(self):
        self._seed("person", [{"name": "Trevor", "slug": "trevor", "aliases": [],
                               "qualifies": True, "maps_to_focus": None,
                               "score": 46.0, "unique_answers": 8, "page_eligible": True}])
        entity = entity_verdict.apply_verdict("person", "trevor", "never")
        self.assertFalse(entity["page_eligible"])
        self.assertEqual(entity["owner_verdict"], "never")

    def test_clear_restores_automatic_eligibility(self):
        self._seed("person", [{"name": "Trevor", "slug": "trevor", "aliases": [],
                               "qualifies": True, "maps_to_focus": None,
                               "score": 46.0, "unique_answers": 8, "page_eligible": False,
                               "owner_verdict": "never"}])
        entity = entity_verdict.apply_verdict("person", "trevor", "clear")
        self.assertNotIn("owner_verdict", entity)
        self.assertTrue(entity["page_eligible"])  # qualifies + score/answers clear the person bar

    def test_clear_on_an_entity_without_a_verdict_is_a_harmless_recompute(self):
        self._seed("person", [{"name": "Trevor", "slug": "trevor", "aliases": [],
                               "qualifies": False, "maps_to_focus": None,
                               "score": 1.0, "unique_answers": 0, "page_eligible": False}])
        entity = entity_verdict.apply_verdict("person", "trevor", "clear")
        self.assertNotIn("owner_verdict", entity)
        self.assertFalse(entity["page_eligible"])

    def test_graduate_refused_on_mapped_entity(self):
        self._seed("person", [{"name": "Wife", "slug": "wife", "aliases": [],
                               "qualifies": True, "maps_to_focus": "katie",
                               "score": 41.0, "unique_answers": 6, "page_eligible": False}])
        with self.assertRaises(entity_verdict.EntityVerdictError):
            entity_verdict.apply_verdict("person", "wife", "graduate")
        on_disk = entity_roster.load_roster("person")["entities"][0]
        self.assertNotIn("owner_verdict", on_disk)  # refused — roster unchanged

    def test_never_is_allowed_on_a_mapped_entity(self):
        # The mapped-entity refusal is graduate-specific (Scope 1/2) — never
        # is a suppression, not a "give this entity a page" claim.
        self._seed("person", [{"name": "Wife", "slug": "wife", "aliases": [],
                               "qualifies": True, "maps_to_focus": "katie",
                               "score": 41.0, "unique_answers": 6, "page_eligible": False}])
        entity = entity_verdict.apply_verdict("person", "wife", "never")
        self.assertEqual(entity["owner_verdict"], "never")
        self.assertFalse(entity["page_eligible"])

    def test_unknown_slug_refused(self):
        self._seed("person", [])
        with self.assertRaises(entity_verdict.EntityVerdictError):
            entity_verdict.apply_verdict("person", "nobody", "graduate")

    def test_unknown_type_refused(self):
        with self.assertRaises(entity_verdict.EntityVerdictError):
            entity_verdict.apply_verdict("alien", "x", "graduate")

    def test_unknown_verdict_refused(self):
        self._seed("person", [{"name": "Trevor", "slug": "trevor", "aliases": [],
                               "qualifies": True, "maps_to_focus": None,
                               "score": 1.0, "unique_answers": 0, "page_eligible": False}])
        with self.assertRaises(entity_verdict.EntityVerdictError):
            entity_verdict.apply_verdict("person", "trevor", "maybe")

    def test_no_roster_on_disk_refused(self):
        with self.assertRaises(entity_verdict.EntityVerdictError):
            entity_verdict.apply_verdict("place", "old-house", "graduate")

    def test_cli_main_prints_eligibility_and_succeeds(self):
        self._seed("person", [{"name": "Trevor", "slug": "trevor", "aliases": [],
                               "qualifies": False, "maps_to_focus": None,
                               "score": 1.0, "unique_answers": 0, "page_eligible": False}])
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = entity_verdict.main(["person", "trevor", "graduate"])
        self.assertEqual(code, 0)
        self.assertIn("page_eligible: eligible", out.getvalue())

    def test_cli_main_never_prints_not_eligible(self):
        self._seed("person", [{"name": "Trevor", "slug": "trevor", "aliases": [],
                               "qualifies": True, "maps_to_focus": None,
                               "score": 46.0, "unique_answers": 8, "page_eligible": True}])
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = entity_verdict.main(["person", "trevor", "never"])
        self.assertEqual(code, 0)
        self.assertIn("page_eligible: not eligible", out.getvalue())

    def test_cli_main_refusal_exits_nonzero_and_writes_stderr(self):
        self._seed("person", [])
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            code = entity_verdict.main(["person", "nobody", "graduate"])
        self.assertEqual(code, 1)
        self.assertIn("no such person", err.getvalue())

    def test_cli_main_json_output(self):
        self._seed("person", [{"name": "Trevor", "slug": "trevor", "aliases": [],
                               "qualifies": True, "maps_to_focus": None,
                               "score": 1.0, "unique_answers": 0, "page_eligible": False}])
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = entity_verdict.main(["person", "trevor", "graduate", "--json"])
        self.assertEqual(code, 0)
        import json as _json
        payload = _json.loads(out.getvalue())
        self.assertEqual(payload["owner_verdict"], "graduate")


# ---------------------------------------------------------------------------
# lifehug.py wrapper + jobs.py queue envelope
# ---------------------------------------------------------------------------


class WrapperAndQueueTests(unittest.TestCase):
    def test_entity_verdict_is_a_direct_mutation_command(self):
        self.assertIn("entity-verdict", lifehug.DIRECT_MUTATION_COMMANDS)

    def test_entity_verdict_is_a_registered_queue_command(self):
        self.assertIn("entity-verdict", jobs.COMMANDS)

    def test_builder_shapes_a_valid_cli_invocation(self):
        invocations = jobs._build_entity_verdict(  # noqa: SLF001
            {"type": "person", "slug": "trevor", "verdict": "graduate"})
        self.assertEqual(len(invocations), 1)
        self.assertEqual(invocations[0].arguments, ("entity-verdict", "person", "trevor", "graduate"))

    def test_builder_rejects_unknown_type(self):
        with self.assertRaises(ValueError):
            jobs._build_entity_verdict(  # noqa: SLF001
                {"type": "alien", "slug": "trevor", "verdict": "graduate"})

    def test_builder_rejects_unknown_verdict(self):
        with self.assertRaises(ValueError):
            jobs._build_entity_verdict(  # noqa: SLF001
                {"type": "person", "slug": "trevor", "verdict": "maybe"})

    def test_builder_rejects_extra_payload_keys(self):
        with self.assertRaises(ValueError):
            jobs._build_entity_verdict(  # noqa: SLF001
                {"type": "person", "slug": "trevor", "verdict": "graduate", "reason": "x"})


# ---------------------------------------------------------------------------
# wiki_compile: the >= 1 mention-bar exception for owner-graduated entities
# ---------------------------------------------------------------------------


class CompileMentionBarTests(unittest.TestCase):
    def setUp(self):
        self.wc = load("wiki_compile")

    def test_owner_graduated_place_needs_only_one_real_mention(self):
        # A place normally needs >= 2 real mentions (_ENTITY_MIN_MENTIONS);
        # an owner-graduated place needs only 1.
        answers = {"A1": _ans("A1", "We passed through Reno once")}
        roster = {"entities": [{"name": "Reno", "slug": "reno", "aliases": [],
                                "maps_to_focus": None, "page_eligible": True,
                                "owner_verdict": "graduate"}]}
        descs = self.wc.plan_entities("place", answers, {}, roster, set())
        self.assertEqual(len(descs), 1)
        self.assertEqual(descs[0]["slug"], "reno")

    def test_owner_graduated_place_still_needs_at_least_one_real_mention(self):
        # Never a zero-mention page, even for an owner-graduated entity.
        answers = {"A1": _ans("A1", "unrelated content entirely")}
        roster = {"entities": [{"name": "Reno", "slug": "reno", "aliases": [],
                                "maps_to_focus": None, "page_eligible": True,
                                "owner_verdict": "graduate"}]}
        self.assertEqual(self.wc.plan_entities("place", answers, {}, roster, set()), [])

    def test_ordinary_place_without_verdict_still_needs_two_mentions(self):
        answers = {"A1": _ans("A1", "We passed through Reno once")}
        roster = {"entities": [{"name": "Reno", "slug": "reno", "aliases": [],
                                "maps_to_focus": None, "page_eligible": True}]}
        self.assertEqual(self.wc.plan_entities("place", answers, {}, roster, set()), [])

    def test_owner_vetoed_entity_never_gets_a_page_even_with_mentions(self):
        answers = {"A1": _ans("A1", "Reno again and again"), "A2": _ans("A2", "Reno once more")}
        roster = {"entities": [{"name": "Reno", "slug": "reno", "aliases": [],
                                "maps_to_focus": None, "page_eligible": False,
                                "owner_verdict": "never"}]}
        self.assertEqual(self.wc.plan_entities("place", answers, {}, roster, set()), [])


class CleanupNeverRemovesOwnerGraduatedTests(unittest.TestCase):
    """cleanup_orphan_entity_pages: a regression pin, not new code — an
    owner-graduated entity's page_eligible is forced True, so it already
    lands in the existing "eligible and unmapped" keep set."""

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

    def test_owner_graduated_page_survives_cleanup(self):
        self.rosters["person"]["entities"].append({
            "name": "Trevor", "slug": "trevor", "aliases": [], "qualifies": False,
            "maps_to_focus": None, "page_eligible": True, "owner_verdict": "graduate",
        })
        page = self.page("trevor")
        removed = self.wc.cleanup_orphan_entity_pages(set())
        self.assertEqual(removed, [])
        self.assertTrue(page.exists())

    def test_owner_vetoed_page_is_removed_like_any_other_demotion(self):
        # `never` suppresses the page like any other ineligible entity —
        # the entity itself stays on the roster (asserted separately in
        # NormalizeOwnerVerdictTests); only the standalone page goes.
        self.rosters["person"]["entities"].append({
            "name": "Trevor", "slug": "trevor", "aliases": [], "qualifies": True,
            "maps_to_focus": None, "page_eligible": False, "owner_verdict": "never",
        })
        page = self.page("trevor")
        removed = self.wc.cleanup_orphan_entity_pages(set())
        self.assertEqual([p.name for p in removed], ["trevor.md"])
        self.assertFalse(page.exists())


# ---------------------------------------------------------------------------
# serve_wiki.py: the candidates lane, the Owner-decided table, the route
# ---------------------------------------------------------------------------


class ViewerLaneTests(unittest.TestCase):
    def setUp(self):
        self.tmp = root_parent_tmp(self, ROOT, prefix="lifehug-entity-verdict-lane-")
        self._saved_dir = entity_roster.ENTITY_DIR
        entity_roster.ENTITY_DIR = self.tmp / "rosters"

    def tearDown(self):
        entity_roster.ENTITY_DIR = self._saved_dir

    def _seed(self, entity_type, entities):
        entity_roster.write_roster(entity_type, entities)

    def test_route_is_registered(self):
        self.assertIn("/actions/entity-verdict", serve_wiki.ACTIONS)

    def test_suppressed_entity_vanishes_from_the_lane_entirely(self):
        # A `never` verdict has no further viewer affordance (Scope 3):
        # it disappears from the candidates table AND from the
        # Owner-decided roster browser (which is graduate-only) — the CLI
        # `clear` is the only way back for a vetoed entity.
        self._seed("person", [
            {"name": "Sarah", "slug": "sarah", "aliases": [], "qualifies": False,
             "maps_to_focus": None, "score": 4, "unique_answers": 1, "page_eligible": False},
            {"name": "Junk Guy", "slug": "junk-guy", "aliases": [], "qualifies": True,
             "maps_to_focus": None, "score": 46, "unique_answers": 8,
             "page_eligible": False, "owner_verdict": "never"},
        ])
        body = serve_wiki._entities_section_html()  # noqa: SLF001
        self.assertIn("Sarah", body)
        self.assertNotIn("Junk Guy", body)  # vetoed — excluded from the whole lane
        self.assertIn("<h3>Person (1)</h3>", body)  # count reflects Sarah only

    def test_owner_decided_table_shows_the_owner_tag_and_clear_action(self):
        self._seed("person", [
            {"name": "Trevor", "slug": "trevor", "aliases": [], "qualifies": False,
             "maps_to_focus": None, "score": 0.0, "unique_answers": 0,
             "page_eligible": True, "owner_verdict": "graduate"},
        ])
        body = serve_wiki._entities_section_html()  # noqa: SLF001
        self.assertIn("Owner-decided", body)
        self.assertIn("Trevor", body)
        self.assertIn("badge", body)  # the small owner tag reuses the badge idiom
        self.assertIn('name="verdict" value="clear"', body)

    def test_candidate_rows_carry_graduate_and_veto_actions(self):
        self._seed("person", [
            {"name": "Sarah", "slug": "sarah", "aliases": [], "qualifies": False,
             "maps_to_focus": None, "score": 4, "unique_answers": 1, "page_eligible": False},
        ])
        body = serve_wiki._entities_section_html()  # noqa: SLF001
        self.assertIn('action="/actions/entity-verdict"', body)
        self.assertIn('name="verdict" value="graduate"', body)
        self.assertIn('name="verdict" value="never"', body)
        self.assertIn('name="slug" value="sarah"', body)
        self.assertIn('name="type" value="person"', body)

    def test_act_entity_verdict_enqueues_a_job(self):
        # Mirrors test_focus_merge.py's ViewerCombineTests convention:
        # monkeypatch _start_job so the handler's enqueue call is observed
        # without touching a real jobs queue / worker.
        enqueued: list[tuple[str, dict]] = []
        saved = serve_wiki._start_job  # noqa: SLF001
        serve_wiki._start_job = lambda kind, payload: (  # noqa: SLF001
            enqueued.append((kind, payload)) or {"id": "job-1"})
        try:
            redirect, message, job_id = serve_wiki.act_entity_verdict({
                "type": ["person"], "slug": ["sarah"], "verdict": ["graduate"],
            })
        finally:
            serve_wiki._start_job = saved  # noqa: SLF001
        self.assertEqual(redirect, "/views/review")
        self.assertIn("graduate now", message)
        self.assertEqual(job_id, "job-1")
        self.assertEqual(enqueued, [("entity-verdict",
                                     {"type": "person", "slug": "sarah", "verdict": "graduate"})])

    def test_act_entity_verdict_rejects_unknown_type(self):
        redirect, message, job_id = serve_wiki.act_entity_verdict({
            "type": ["alien"], "slug": ["sarah"], "verdict": ["graduate"],
        })
        self.assertIsNone(job_id)
        self.assertIn("✗", message)

    def test_act_entity_verdict_rejects_bad_slug(self):
        redirect, message, job_id = serve_wiki.act_entity_verdict({
            "type": ["person"], "slug": ["../etc/passwd"], "verdict": ["graduate"],
        })
        self.assertIsNone(job_id)
        self.assertIn("✗", message)

    def test_act_entity_verdict_rejects_unknown_verdict(self):
        redirect, message, job_id = serve_wiki.act_entity_verdict({
            "type": ["person"], "slug": ["sarah"], "verdict": ["maybe"],
        })
        self.assertIsNone(job_id)
        self.assertIn("✗", message)


if __name__ == "__main__":
    unittest.main()
