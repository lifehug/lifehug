"""Tests for the focus-duplicate-curation contract (v167, ADR 0010).

Three layers: door guards (deterministic), the roster fold (deterministic),
and the focus_curation interaction (AI, first-encounter near-name pairs
only, no deterministic merge fallback) — plus the read-only `focus-dupes
--report` damage list. Everything here is synthetic — a throwaway vault per
test, never the founder vault (see AGENTS.md's boundary rule).
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SYSTEM = ROOT / "system"
sys.path.insert(0, str(SYSTEM))
sys.path.insert(0, str(ROOT / "tests"))

from tempdirs import root_parent_tmp  # noqa: E402

import entity_roster  # noqa: E402
import focus_curation  # noqa: E402
import focus_dupes  # noqa: E402
import lifehug_core  # noqa: E402
import recommend_focuses  # noqa: E402
import roadmap  # noqa: E402
from lifehug_core import normalized_focus_key  # noqa: E402

PRIMARY = {
    "id": "my-life", "label": "My Life", "type": "life_story", "primary": True,
    "tier": "extreme", "objective": "story", "deliverable": "book",
    "categories": ["A"], "target_depth": 8, "phase": "active", "wiki_node": None,
    "neighborhoods": [],
}


def _focus(fid: str, label: str, categories: list[str], target_depth: int = 20) -> dict:
    return {
        "id": fid, "label": label, "primary": False, "type": "theme", "tier": "standard",
        "objective": f"explore {label}", "deliverable": "essay", "categories": categories,
        "target_depth": target_depth, "cap": 0.3, "phase": "active", "wiki_node": None,
        "neighborhoods": [],
    }


def _rec(rec_id: str, entity: str, *, rec_type: str = "person", score: float = 6.0,
         mention_count: int = 2, unique_answers: int = 2, categories=("K",),
         emotional_weight: float = 1.0, evidence=None, status: str = "pending") -> dict:
    return {
        "id": rec_id, "entity": entity, "type": rec_type, "score": score,
        "evidence_strength": "moderate", "mention_count": mention_count,
        "unique_answers": unique_answers, "cross_categories": list(categories),
        "emotional_weight": emotional_weight,
        "evidence": list(evidence) if evidence else [f"Mentioned in {categories[0]}1 (relationship context)"],
        "reason": f"{entity} appears in {unique_answers} answer(s)", "status": status,
        "created_at": "2026-08-01T00:00:00Z", "ready_to_start": False,
    }


class FixtureBase(unittest.TestCase):
    """Shared fixture plumbing, following tests/test_v134_focus_gate.py's
    real-path-tmp-dir + monkeypatched-module-attribute convention."""

    def setUp(self):
        self.tmp = root_parent_tmp(self, ROOT, prefix="lifehug-focus-dupes-")
        self._saved = {
            (roadmap, "ROADMAP_FILE"): roadmap.ROADMAP_FILE,
            (roadmap, "QUESTIONS_FILE"): roadmap.QUESTIONS_FILE,
            (recommend_focuses, "QUESTIONS_FILE"): recommend_focuses.QUESTIONS_FILE,
            (recommend_focuses, "ANSWERS_DIR"): recommend_focuses.ANSWERS_DIR,
            (recommend_focuses, "MANUAL_SOURCES_DIR"): recommend_focuses.MANUAL_SOURCES_DIR,
            (recommend_focuses, "CLASSIFICATIONS_DIR"): recommend_focuses.CLASSIFICATIONS_DIR,
            (recommend_focuses, "WIKI_DIR"): recommend_focuses.WIKI_DIR,
            (recommend_focuses, "FOCUS_RECS_FILE"): recommend_focuses.FOCUS_RECS_FILE,
            (recommend_focuses, "LEGACY_FOCUS_RECS_FILE"): recommend_focuses.LEGACY_FOCUS_RECS_FILE,
            (entity_roster, "ENTITY_DIR"): entity_roster.ENTITY_DIR,
            (focus_curation, "SETTLED_FILE"): focus_curation.SETTLED_FILE,
            # roadmap.focus_new() calls lifehug_core.rebuild_coverage() (a
            # function DEFINED in lifehug_core.py, so it resolves
            # QUESTIONS_FILE/COVERAGE_FILE via lifehug_core's OWN module
            # globals, not roadmap's rebound copy) — patch these too or a
            # focus_new() call in a test writes the real repo's coverage.json.
            (lifehug_core, "QUESTIONS_FILE"): lifehug_core.QUESTIONS_FILE,
            (lifehug_core, "COVERAGE_FILE"): lifehug_core.COVERAGE_FILE,
        }
        qbank = self._write("question-bank.md", "## A: Origins\n- [x] A1: Earliest? *(2026-01-01)*\n")
        roadmap.QUESTIONS_FILE = qbank
        recommend_focuses.QUESTIONS_FILE = qbank
        lifehug_core.QUESTIONS_FILE = qbank
        lifehug_core.COVERAGE_FILE = self.tmp / "coverage.json"
        recommend_focuses.ANSWERS_DIR = self.tmp / "answers"
        recommend_focuses.MANUAL_SOURCES_DIR = self.tmp / "sources"
        recommend_focuses.CLASSIFICATIONS_DIR = self.tmp / "classifications"
        recommend_focuses.WIKI_DIR = self.tmp / "wiki"
        recommend_focuses.FOCUS_RECS_FILE = self.tmp / "focus_recommendations.json"
        recommend_focuses.LEGACY_FOCUS_RECS_FILE = self.tmp / "legacy_focus_recommendations.json"
        entity_roster.ENTITY_DIR = self.tmp / "entity_rosters"
        focus_curation.SETTLED_FILE = self.tmp / "focus_curation" / "settled.json"
        roadmap.ROADMAP_FILE = self.tmp / "roadmap.json"

    def tearDown(self):
        for (mod, name), val in self._saved.items():
            setattr(mod, name, val)

    def _write(self, name, data):
        p = self.tmp / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(data if isinstance(data, str) else json.dumps(data))
        return p

    def _set_roadmap(self, focuses: list[dict]) -> None:
        roadmap.ROADMAP_FILE = self._write("roadmap.json", {"version": 1, "focuses": focuses})

    def _set_recs(self, recommendations: list[dict], dismissed: list[dict] | None = None) -> None:
        recommend_focuses.FOCUS_RECS_FILE = self._write("focus_recommendations.json", {
            "version": 1, "generated_at": "2026-08-01T00:00:00Z",
            "recommendations": recommendations, "dismissed": dismissed or [],
        })

    def _set_roster(self, entity_type: str, entities: list[dict]) -> None:
        path = entity_roster.ENTITY_DIR / f"{entity_type}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({
            "version": 1, "type": entity_type, "resolved_at": "2026-08-01T00:00:00Z",
            "entities": entities,
        }))


# ---------------------------------------------------------------------------
# normalized_focus_key — the shared definition
# ---------------------------------------------------------------------------

class NormalizedFocusKeyTests(unittest.TestCase):
    def test_case_variants_collide(self):
        self.assertEqual(normalized_focus_key("Fear"), normalized_focus_key("fear"))
        self.assertEqual(normalized_focus_key("FEAR"), normalized_focus_key("fear"))

    def test_the_prefix_collides_with_bare_form(self):
        self.assertEqual(normalized_focus_key("The Outside"), normalized_focus_key("Outside"))
        self.assertEqual(normalized_focus_key("the outside"), normalized_focus_key("Outside"))

    def test_slug_variants_collide(self):
        self.assertEqual(normalized_focus_key("Betty-Jo"), normalized_focus_key("Betty Jo"))

    def test_distinct_names_do_not_collide(self):
        self.assertNotEqual(normalized_focus_key("Fear"), normalized_focus_key("Joy"))
        self.assertNotEqual(normalized_focus_key("Betty Jo"), normalized_focus_key("Betty Jo Taylor"))

    def test_entity_keys_shares_the_definition_not_a_copy(self):
        # entity_roster._entity_keys must include normalized_focus_key's exact
        # output among its match-key variants (recurring-defect doctrine —
        # shared, never re-derived).
        keys = entity_roster._entity_keys({"name": "The Outside", "aliases": []})
        self.assertIn(normalized_focus_key("The Outside"), keys)


# ---------------------------------------------------------------------------
# Scope 1 — creation-door guards
# ---------------------------------------------------------------------------

class DoorGuardTests(FixtureBase):
    def test_focus_new_refuses_on_case_variant_collision(self):
        # A DIFFERENT id ("the-fear") that still normalizes to the same key
        # ("fear") as the existing focus — the genuine duplicate case this
        # guard exists for. A label that slugifies to the SAME id as an
        # existing focus is the pre-existing "zombie focus" healing case
        # (see test_focus_new_zombie_healing_still_works), not a collision.
        self._set_roadmap([PRIMARY, _focus("fear", "Fear", ["K"])])
        with self.assertRaises(roadmap.FocusKeyCollisionError) as ctx:
            roadmap.focus_new("The Fear", "theme", "standard", generate=False)
        self.assertIn("Fear", str(ctx.exception))
        self.assertEqual(ctx.exception.existing["id"], "fear")

    def test_focus_new_refuses_on_the_prefix_collision(self):
        self._set_roadmap([PRIMARY, _focus("outside", "Outside", ["K"])])
        with self.assertRaises(roadmap.FocusKeyCollisionError):
            roadmap.focus_new("The Outside", "theme", "standard", generate=False)

    def test_focus_new_allows_distinct_label(self):
        self._set_roadmap([PRIMARY, _focus("fear", "Fear", ["K"])])
        result = roadmap.focus_new("Joy", "theme", "standard", generate=False)
        self.assertEqual(result["focus_id"], "joy")
        joy = roadmap.find_focus(roadmap.load_roadmap(), "joy")
        self.assertIsNotNone(joy)

    def test_focus_new_zombie_healing_still_works(self):
        # A registered-but-uncategorized focus (same id) is healed, not
        # refused — this is the pre-existing "zombie focus" case, distinct
        # from a duplicate-key collision (contract Scope 1's carve-out).
        zombie = _focus("joy", "Joy", [])
        self._set_roadmap([PRIMARY, zombie])
        result = roadmap.focus_new("Joy", "theme", "standard", generate=False)
        self.assertEqual(result["focus_id"], "joy")

    def test_find_focus_by_key_matches_on_id_too(self):
        self._set_roadmap([PRIMARY, _focus("fear", "Fear", ["K"])])
        rm = roadmap.load_roadmap()
        self.assertIsNotNone(roadmap.find_focus_by_key(rm, "fear"))
        self.assertIsNone(roadmap.find_focus_by_key(rm, "joy"))

    def test_cli_focus_add_refuses_on_collision(self):
        self._set_roadmap([PRIMARY, _focus("fear", "Fear", ["K"])])
        exit_code = roadmap.cli(["add", "fear", "--type", "theme"])
        self.assertEqual(exit_code, 1)
        rm = roadmap.load_roadmap()
        self.assertEqual(len([f for f in rm["focuses"] if normalized_focus_key(f["label"]) == "fear"]), 1)

    def test_cli_focus_add_allows_distinct_label(self):
        self._set_roadmap([PRIMARY, _focus("fear", "Fear", ["K"])])
        exit_code = roadmap.cli(["add", "Joy", "--type", "theme"])
        self.assertEqual(exit_code, 0)
        rm = roadmap.load_roadmap()
        self.assertIsNotNone(roadmap.find_focus(rm, "joy"))

    def test_derive_focuses_folds_case_variant_categories(self):
        md = (
            "## A: Origins\n- [x] A1: Earliest? *(2026-01-01)*\n\n"
            "## Focuses\n\n"
            "## K: Focus — Fear\n- [ ] K1: What scares you?\n\n"
            "## L: Focus — fear\n- [ ] L1: When were you scared?\n"
        )
        focuses = roadmap.derive_focuses(md)
        non_primary = [f for f in focuses if not f.get("primary")]
        self.assertEqual(len(non_primary), 1)
        self.assertEqual(non_primary[0]["label"], "Fear")
        self.assertEqual(sorted(non_primary[0]["categories"]), ["K", "L"])

    def test_derive_focuses_leaves_distinct_categories_apart(self):
        md = (
            "## A: Origins\n- [x] A1: Earliest? *(2026-01-01)*\n\n"
            "## Focuses\n\n"
            "## K: Focus — Fear\n- [ ] K1: What scares you?\n\n"
            "## L: Focus — Joy\n- [ ] L1: What brings you joy?\n"
        )
        focuses = roadmap.derive_focuses(md)
        non_primary = {f["label"] for f in focuses if not f.get("primary")}
        self.assertEqual(non_primary, {"Fear", "Joy"})

    def test_approve_recommendation_refuses_on_collision(self):
        self._set_roadmap([PRIMARY, _focus("fear", "Fear", ["K"])])
        self._set_recs([_rec("rec-the-fear", "The Fear", rec_type="theme")])
        ok = recommend_focuses.approve_recommendation("rec-the-fear")
        self.assertFalse(ok)
        rm = roadmap.load_roadmap()
        self.assertEqual(len([f for f in rm["focuses"] if normalized_focus_key(f["label"]) == "fear"]), 1)


# ---------------------------------------------------------------------------
# Scope 2 — roster fold at recommend-time
# ---------------------------------------------------------------------------

class RosterFoldTests(FixtureBase):
    def test_settled_roster_alias_merges_pending_stats(self):
        self._set_roster("person", [
            {"name": "Betty Jo Taylor", "slug": "betty-jo-taylor", "aliases": ["Betty Jo"],
             "qualifies": True, "maps_to_focus": None},
        ])
        stats = {
            ("person", "Betty Jo"): {
                "mention_count": 2, "answers": {"K3"}, "categories": {"K"},
                "emotional_weight": 1.0, "evidence": ["ev-a"],
            },
            ("person", "Betty Jo Taylor"): {
                "mention_count": 3, "answers": {"K5", "K6"}, "categories": {"K"},
                "emotional_weight": 2.0, "evidence": ["ev-b"],
            },
        }
        folded = recommend_focuses._fold_stats_through_roster(stats)
        self.assertEqual(len(folded), 1)
        (etype, name), merged = next(iter(folded.items()))
        self.assertEqual(etype, "person")
        self.assertEqual(name, "Betty Jo Taylor")
        self.assertEqual(merged["mention_count"], 5)
        self.assertEqual(merged["answers"], {"K3", "K5", "K6"})
        self.assertEqual(sorted(merged["evidence"]), ["ev-a", "ev-b"])

    def test_unsettled_pair_left_apart(self):
        # No roster entry ties these together -> both survive as distinct keys.
        stats = {
            ("person", "Betty Jo"): {
                "mention_count": 2, "answers": {"K3"}, "categories": {"K"},
                "emotional_weight": 1.0, "evidence": ["ev-a"],
            },
            ("person", "Betty Jo Taylor"): {
                "mention_count": 3, "answers": {"K5"}, "categories": {"K"},
                "emotional_weight": 2.0, "evidence": ["ev-b"],
            },
        }
        folded = recommend_focuses._fold_stats_through_roster(stats)
        self.assertEqual(len(folded), 2)

    def test_recommend_end_to_end_emits_one_folded_recommendation(self):
        self._set_roster("person", [
            {"name": "Betty Jo Taylor", "slug": "betty-jo-taylor", "aliases": ["Betty Jo"],
             "qualifies": True, "maps_to_focus": None},
        ])
        answers_dir = recommend_focuses.ANSWERS_DIR
        answers_dir.mkdir(parents=True, exist_ok=True)
        (answers_dir / "K3.md").write_text(
            "---\nquestion_id: K3\n---\nMy grandma Betty Jo always kept the porch light on.\n",
        )
        (answers_dir / "K5.md").write_text(
            "---\nquestion_id: K5\n---\nBetty Jo Taylor taught me to bake bread every Sunday morning.\n",
        )
        recs = recommend_focuses.recommend(min_score=0.0, filter_type="person")
        names = {r["entity"] for r in recs}
        self.assertNotIn("Betty Jo", names - {"Betty Jo Taylor"})
        matching = [r for r in recs if r["entity"] == "Betty Jo Taylor"]
        self.assertEqual(len(matching), 1)


# ---------------------------------------------------------------------------
# Scope 3 — focus-dupes --report
# ---------------------------------------------------------------------------

class FocusDupesReportTests(FixtureBase):
    def test_report_pins_all_three_sections(self):
        self._set_roadmap([
            PRIMARY,
            _focus("fear", "Fear", ["K"]),
            _focus("fear-2", "fear", ["L"]),
        ])
        self._set_recs([
            _rec("rec-betty-jo", "Betty Jo", mention_count=2, unique_answers=2),
            _rec("rec-betty-jo-taylor", "Betty Jo Taylor", mention_count=3, unique_answers=3),
        ])
        data = focus_dupes.report()

        certain = data["certain_focus_duplicates"]
        self.assertEqual(len(certain), 1)
        self.assertEqual(certain[0]["key"], "fear")
        self.assertEqual({f["id"] for f in certain[0]["focuses"]}, {"fear", "fear-2"})

        near = data["near_name_pairs"]
        self.assertEqual(len(near), 1)
        pair = near[0]
        self.assertEqual({pair["shorter_id"], pair["longer_id"]},
                         {"idea:rec-betty-jo", "idea:rec-betty-jo-taylor"})
        self.assertEqual(pair["shorter_label"], "Betty Jo")
        self.assertEqual(pair["longer_label"], "Betty Jo Taylor")

        # No pending idea folds into an existing focus or another idea here
        # (both are the near-name shape, not an exact-key collision).
        self.assertEqual(data["pending_idea_duplicates"], [])

    def test_pending_idea_folds_into_existing_focus(self):
        self._set_roadmap([PRIMARY, _focus("fear", "Fear", ["K"])])
        self._set_recs([_rec("rec-fear", "fear", rec_type="theme")])
        data = focus_dupes.report()
        self.assertEqual(len(data["pending_idea_duplicates"]), 1)
        self.assertEqual(data["pending_idea_duplicates"][0]["kind"], "folds_into_existing_focus")

    def test_pending_ideas_fold_into_each_other(self):
        self._set_roadmap([PRIMARY])
        self._set_recs([
            _rec("rec-fear-a", "Fear", rec_type="theme"),
            _rec("rec-fear-b", "fear", rec_type="theme"),
        ])
        data = focus_dupes.report()
        certain = [d for d in data["pending_idea_duplicates"] if d["kind"] == "folds_into_each_other"]
        self.assertEqual(len(certain), 1)
        self.assertEqual({i["id"] for i in certain[0]["ideas"]}, {"rec-fear-a", "rec-fear-b"})

    def test_report_is_read_only(self):
        self._set_roadmap([PRIMARY, _focus("fear", "Fear", ["K"]), _focus("fear-2", "fear", ["L"])])
        self._set_recs([_rec("rec-betty-jo", "Betty Jo"), _rec("rec-betty-jo-taylor", "Betty Jo Taylor")])
        before_roadmap = roadmap.ROADMAP_FILE.read_text()
        before_recs = recommend_focuses.FOCUS_RECS_FILE.read_text()
        focus_dupes.report()
        self.assertEqual(roadmap.ROADMAP_FILE.read_text(), before_roadmap)
        self.assertEqual(recommend_focuses.FOCUS_RECS_FILE.read_text(), before_recs)


# ---------------------------------------------------------------------------
# Scope 4 — the Focus-Curation interaction
# ---------------------------------------------------------------------------

class FocusCurationVerdictTests(FixtureBase):
    def _seed_betty_jo(self):
        self._set_roadmap([PRIMARY])
        self._set_recs([
            _rec("rec-betty-jo", "Betty Jo", mention_count=2, unique_answers=2,
                 emotional_weight=1.0, evidence=["ev-a"]),
            _rec("rec-betty-jo-taylor", "Betty Jo Taylor", mention_count=3, unique_answers=3,
                 emotional_weight=2.0, evidence=["ev-b"]),
        ])

    def test_merge_verdict_dismisses_variant_and_sums_canonical(self):
        self._seed_betty_jo()
        pending_ideas = [{"id": "rec-betty-jo"}, {"id": "rec-betty-jo-taylor"}]
        verdict = {"merge": [["rec-betty-jo-taylor", "rec-betty-jo"]], "map_to_focus": {}, "keep": []}
        result = focus_curation.apply_verdicts(verdict, pending_ideas)
        self.assertEqual(result["status"], "applied")
        self.assertEqual(result["merged_groups"], 1)

        state = recommend_focuses.load_recommendation_state()
        ids = {r["id"] for r in state["recommendations"]}
        self.assertEqual(ids, {"rec-betty-jo-taylor"})
        canonical = state["recommendations"][0]
        self.assertEqual(canonical["mention_count"], 5)
        self.assertEqual(canonical["emotional_weight"], 3.0)
        self.assertEqual(sorted(canonical["evidence"]), ["ev-a", "ev-b"])

        dismissed = state["dismissed"]
        self.assertEqual(len(dismissed), 1)
        self.assertEqual(dismissed[0]["id"], "rec-betty-jo")
        self.assertEqual(dismissed[0]["dismissed_by"], "curation")
        self.assertEqual(dismissed[0]["dismiss_reason"], "")  # no reason capture

    def test_map_to_focus_verdict_dismisses_with_structured_fact(self):
        self._set_roadmap([PRIMARY, _focus("karen", "Karen", ["K"])])
        self._set_recs([_rec("rec-mom", "Mom", rec_type="person")])
        pending_ideas = [{"id": "rec-mom"}]
        verdict = {"merge": [], "map_to_focus": {"rec-mom": "karen"}, "keep": []}
        result = focus_curation.apply_verdicts(verdict, pending_ideas)
        self.assertEqual(result["status"], "applied")
        self.assertEqual(result["mapped"], 1)

        state = recommend_focuses.load_recommendation_state()
        self.assertEqual(state["recommendations"], [])
        self.assertEqual(state["dismissed"][0]["mapped_to_focus"], "karen")
        self.assertEqual(state["dismissed"][0]["dismiss_reason"], "")

    def test_keep_verdict_is_a_no_op(self):
        self._seed_betty_jo()
        pending_ideas = [{"id": "rec-betty-jo"}, {"id": "rec-betty-jo-taylor"}]
        verdict = {"merge": [], "map_to_focus": {}, "keep": ["rec-betty-jo", "rec-betty-jo-taylor"]}
        result = focus_curation.apply_verdicts(verdict, pending_ideas)
        self.assertEqual(result["status"], "applied")
        state = recommend_focuses.load_recommendation_state()
        self.assertEqual({r["id"] for r in state["recommendations"]},
                         {"rec-betty-jo", "rec-betty-jo-taylor"})
        self.assertEqual(state["dismissed"], [])

    def test_malformed_verdict_dropped_id_is_a_no_op(self):
        self._seed_betty_jo()
        pending_ideas = [{"id": "rec-betty-jo"}, {"id": "rec-betty-jo-taylor"}]
        verdict = {"merge": [], "map_to_focus": {}, "keep": ["rec-betty-jo"]}  # drops the taylor id
        result = focus_curation.apply_verdicts(verdict, pending_ideas)
        self.assertEqual(result["status"], "invalid")
        state = recommend_focuses.load_recommendation_state()
        self.assertEqual({r["id"] for r in state["recommendations"]},
                         {"rec-betty-jo", "rec-betty-jo-taylor"})  # untouched

    def test_malformed_verdict_invented_id_is_a_no_op(self):
        self._seed_betty_jo()
        pending_ideas = [{"id": "rec-betty-jo"}, {"id": "rec-betty-jo-taylor"}]
        verdict = {"merge": [], "map_to_focus": {}, "keep": ["rec-betty-jo", "rec-betty-jo-taylor", "rec-invented"]}
        result = focus_curation.apply_verdicts(verdict, pending_ideas)
        self.assertEqual(result["status"], "invalid")

    def test_malformed_verdict_undersized_merge_group_is_a_no_op(self):
        self._seed_betty_jo()
        pending_ideas = [{"id": "rec-betty-jo"}, {"id": "rec-betty-jo-taylor"}]
        verdict = {"merge": [["rec-betty-jo"]], "map_to_focus": {}, "keep": ["rec-betty-jo-taylor"]}
        result = focus_curation.apply_verdicts(verdict, pending_ideas)
        self.assertEqual(result["status"], "invalid")

    def test_malformed_verdict_extra_key_is_a_no_op(self):
        self._seed_betty_jo()
        pending_ideas = [{"id": "rec-betty-jo"}, {"id": "rec-betty-jo-taylor"}]
        verdict = {"merge": [], "map_to_focus": {}, "keep": ["rec-betty-jo", "rec-betty-jo-taylor"],
                  "reason": "no evidence either way"}
        result = focus_curation.apply_verdicts(verdict, pending_ideas)
        self.assertEqual(result["status"], "invalid")

    def test_malformed_verdict_invented_slug_is_a_no_op(self):
        self._set_roadmap([PRIMARY, _focus("karen", "Karen", ["K"])])
        self._set_recs([_rec("rec-mom", "Mom", rec_type="person")])
        pending_ideas = [{"id": "rec-mom"}]
        verdict = {"merge": [], "map_to_focus": {"rec-mom": "mother-figure"}, "keep": []}
        result = focus_curation.apply_verdicts(verdict, pending_ideas)
        self.assertEqual(result["status"], "invalid")
        state = recommend_focuses.load_recommendation_state()
        self.assertEqual(len(state["recommendations"]), 1)

    def test_settled_ledger_excludes_already_curated_ids_from_next_build(self):
        self._seed_betty_jo()
        rm = roadmap.load_roadmap()
        pending = recommend_focuses.load_recommendation_state()["recommendations"]
        ideas_before = focus_curation.build_pending_idea_list(roadmap=rm, pending=pending)
        self.assertEqual({i["id"] for i in ideas_before}, {"rec-betty-jo", "rec-betty-jo-taylor"})

        verdict = {"merge": [], "map_to_focus": {}, "keep": ["rec-betty-jo", "rec-betty-jo-taylor"]}
        focus_curation.apply_verdicts(verdict, ideas_before)

        pending_after = recommend_focuses.load_recommendation_state()["recommendations"]
        ideas_after = focus_curation.build_pending_idea_list(roadmap=rm, pending=pending_after)
        self.assertEqual(ideas_after, [])


class FocusCurationKeylessTests(FixtureBase):
    def test_emit_task_writes_expected_shape(self):
        self._set_roadmap([PRIMARY])
        self._set_recs([
            _rec("rec-betty-jo", "Betty Jo"),
            _rec("rec-betty-jo-taylor", "Betty Jo Taylor"),
        ])
        task_path = self.tmp / "task.json"
        result = focus_curation.run_curation(emit_task=str(task_path))
        self.assertEqual(result["status"], "emitted_task")
        payload = json.loads(task_path.read_text())
        self.assertEqual(payload["type"], "focus_curation")
        self.assertIn("prompt", payload)
        self.assertEqual(payload["response_format"], {"merge": [], "map_to_focus": {}, "keep": []})
        ids = {i["id"] for i in payload["pending_ideas"]}
        self.assertEqual(ids, {"rec-betty-jo", "rec-betty-jo-taylor"})

    def test_from_response_applies_without_an_ai_call(self):
        self._set_roadmap([PRIMARY])
        self._set_recs([
            _rec("rec-betty-jo", "Betty Jo"),
            _rec("rec-betty-jo-taylor", "Betty Jo Taylor"),
        ])
        response_path = self.tmp / "response.json"
        response_path.write_text(json.dumps({
            "merge": [["rec-betty-jo-taylor", "rec-betty-jo"]], "map_to_focus": {}, "keep": [],
        }))
        result = focus_curation.run_curation(from_response=str(response_path))
        self.assertEqual(result["status"], "applied")
        state = recommend_focuses.load_recommendation_state()
        self.assertEqual({r["id"] for r in state["recommendations"]}, {"rec-betty-jo-taylor"})

    def test_no_pending_ideas_is_a_clean_no_change(self):
        self._set_roadmap([PRIMARY])
        self._set_recs([])
        result = focus_curation.run_curation(dry_run=True)
        self.assertEqual(result["status"], "no_change")


if __name__ == "__main__":
    unittest.main()
