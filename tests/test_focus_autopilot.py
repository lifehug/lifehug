"""Tests for focus_autopilot() and approve_recommendation()'s approved_by
provenance — ADR 0011, the Convergence Principle's floor (ADR 0006) applied
to focus creation. A passive user's system used to NEVER grow a new Focus;
this closes that gap while keeping owner approval as an accelerator, never
a dependency. All state is synthetic — a throwaway vault per test, never
the founder vault.
"""

from __future__ import annotations

import json
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SYSTEM = ROOT / "system"
sys.path.insert(0, str(SYSTEM))
sys.path.insert(0, str(ROOT / "tests"))

from tempdirs import root_parent_tmp  # noqa: E402
import entity_roster  # noqa: E402
import lifehug_core  # noqa: E402
import recommend_focuses  # noqa: E402
import roadmap  # noqa: E402

PRIMARY = {
    "id": "my-life", "label": "My Life", "type": "life_story", "primary": True,
    "tier": "extreme", "objective": "story", "deliverable": "book",
    "categories": ["A"], "target_depth": 4, "phase": "active", "wiki_node": None,
}

# Same fixture bank as tests/test_v134_focus_gate.py's GateTestBase — F is
# 3/4 answered (saturation 0.75, READY), G is 2/4 (0.5, DEVELOPING), H is
# 5/5 against a stale target of 20 (0.25, but zero pending — an "exhausted"
# gate exemption; see DevelopingSetTests for why the developing SET (unlike
# the completion gate) does not carry that exemption).
QUESTION_BANK = (
    "## A: Origins\n- [x] A1: Earliest? *(2026-01-01)*\n- [ ] A2: Where?\n"
    "## F: The Problem\n- [x] F1: What? *(2026-01-01)*\n- [x] F2: Why?\n"
    "- [x] F3: When? *(2026-01-01)*\n- [ ] F4: How?\n"
    "## G: Second Thing\n- [x] G1: A? *(2026-01-01)*\n- [x] G2: B?\n"
    "- [ ] G3: C?\n- [ ] G4: D?\n"
    "## H: Exhausted\n- [x] H1: a? *(2026-01-01)*\n- [x] H2: b?\n"
    "- [x] H3: c?\n- [x] H4: d?\n- [x] H5: e?\n"
)


def _iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _filler_focus(fid: str, label: str, category: str = "Z") -> dict:
    """A synthetic non-primary Focus whose category has zero matching
    questions in QUESTION_BANK -> saturation 0/target = 0.0, unambiguously
    "developing" regardless of the shared bank's real content."""
    return {
        "id": fid, "label": label, "type": "theme", "tier": "standard",
        "objective": "x", "deliverable": "essay", "categories": [category],
        "target_depth": 10, "phase": "active", "wiki_node": None,
    }


class AutopilotTestBase(unittest.TestCase):
    """Shared fixture plumbing, following tests/test_v134_focus_gate.py's
    real-path-tmp-dir + monkeypatched-module-attribute convention, extended
    to cover the extra modules a real approve_recommendation() -> focus_new()
    call touches (lifehug_core.QUESTIONS_FILE/COVERAGE_FILE) so nothing
    leaks a write to the real repo's own state files."""

    def setUp(self):
        self.tmp = root_parent_tmp(self, ROOT)
        self._saved = {
            (lifehug_core, "QUESTIONS_FILE"): lifehug_core.QUESTIONS_FILE,
            (lifehug_core, "COVERAGE_FILE"): lifehug_core.COVERAGE_FILE,
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
        }
        qbank = self._write("question-bank.md", QUESTION_BANK)
        lifehug_core.QUESTIONS_FILE = qbank
        lifehug_core.COVERAGE_FILE = self.tmp / "coverage.json"
        roadmap.QUESTIONS_FILE = qbank
        recommend_focuses.QUESTIONS_FILE = qbank
        recommend_focuses.ANSWERS_DIR = self.tmp / "answers"
        recommend_focuses.MANUAL_SOURCES_DIR = self.tmp / "sources"
        recommend_focuses.CLASSIFICATIONS_DIR = self.tmp / "classifications"
        recommend_focuses.WIKI_DIR = self.tmp / "wiki"
        recommend_focuses.FOCUS_RECS_FILE = self.tmp / "focus_recommendations.json"
        recommend_focuses.LEGACY_FOCUS_RECS_FILE = self.tmp / "legacy_focus_recommendations.json"
        entity_roster.ENTITY_DIR = self.tmp / "no-rosters"

        # Never spawn the real research_expand.py subprocess in a unit test
        # — same outcome a genuinely keyless machine gets (generation_ran
        # False, 0 promoted), just without the process overhead. This is
        # the ONLY thing patched inside focus_new()'s real call chain —
        # scaffold_category, rebuild_roadmap, and rebuild_coverage all run
        # for real, so a test proving "focus scaffolded" proves the real
        # code path.
        self._orig_generate = roadmap._generate_and_promote
        roadmap._generate_and_promote = lambda *a, **kw: (False, 0)

        # resolve_autopilot_target() must not pick up a stray local
        # config.yaml/profile.yaml key from the real environment.
        self._orig_load_config = recommend_focuses.load_config
        recommend_focuses.load_config = lambda *a, **kw: {}

    def tearDown(self):
        for (mod, name), val in self._saved.items():
            setattr(mod, name, val)
        roadmap._generate_and_promote = self._orig_generate
        recommend_focuses.load_config = self._orig_load_config

    def _write(self, name, data):
        p = self.tmp / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(data if isinstance(data, str) else json.dumps(data))
        return p

    def _set_roadmap(self, focuses: list[dict]) -> None:
        roadmap.ROADMAP_FILE = self._write("roadmap.json", {"version": 1, "focuses": focuses})

    def _set_recs(self, recommendations: list[dict], dismissed: list[dict] | None = None) -> None:
        recommend_focuses.write_json(recommend_focuses.FOCUS_RECS_FILE, {
            "version": 1,
            "generated_at": _iso(datetime(2026, 8, 1, tzinfo=timezone.utc)),
            "recommendations": recommendations,
            "dismissed": dismissed or [],
        })

    def _rec(self, rec_id: str, entity: str, score: float, status: str = "pending", **extra) -> dict:
        rec = {
            "id": rec_id, "entity": entity, "type": "theme", "score": score,
            "evidence_strength": "strong" if score >= 15 else "moderate",
            "mention_count": 3, "unique_answers": 2, "cross_categories": ["A"],
            "emotional_weight": 1.0, "evidence": [f"seen with {entity}"],
            "reason": f"{entity} is a strong candidate.",
            "status": status,
            "created_at": _iso(datetime(2026, 8, 1, tzinfo=timezone.utc)),
        }
        rec.update(extra)
        return rec

    def _questions(self):
        return recommend_focuses.parse_questions(QUESTION_BANK)


class DevelopingSetTests(AutopilotTestBase):
    """_is_developing / _developing_focuses — pure functions, no I/O."""

    def test_primary_focus_never_counts_as_developing(self):
        # PRIMARY's own saturation (1/4 answered against categories=["A"])
        # is 0.25 -- well below READY -- but primary is exempt regardless.
        self.assertFalse(recommend_focuses._is_developing(PRIMARY, self._questions()))
        self.assertEqual(
            recommend_focuses._developing_focuses({"focuses": [PRIMARY]}, self._questions()),
            [],
        )

    def test_saturated_or_ready_focus_does_not_count(self):
        # F: 3/4 answered -> saturation 0.75 -> READY, not developing.
        ready_focus = {
            "id": "f", "label": "F", "type": "theme", "tier": "standard",
            "objective": "x", "deliverable": "essay", "categories": ["F"],
            "target_depth": 4, "phase": "active", "wiki_node": None,
        }
        self.assertFalse(recommend_focuses._is_developing(ready_focus, self._questions()))

    def test_saturated_via_low_target_does_not_count(self):
        saturated_focus = {
            "id": "a2", "label": "A2", "type": "theme", "tier": "standard",
            "objective": "x", "deliverable": "essay", "categories": ["A"],
            "target_depth": 1, "phase": "active", "wiki_node": None,
        }
        self.assertFalse(recommend_focuses._is_developing(saturated_focus, self._questions()))

    def test_developing_focus_counts(self):
        # G: 2/4 answered -> saturation 0.5 -> DEVELOPING.
        developing_focus = {
            "id": "g", "label": "G", "type": "theme", "tier": "standard",
            "objective": "x", "deliverable": "essay", "categories": ["G"],
            "target_depth": 4, "phase": "active", "wiki_node": None,
        }
        self.assertTrue(recommend_focuses._is_developing(developing_focus, self._questions()))

    def test_maintenance_phase_never_counts(self):
        maintenance_focus = {
            "id": "g", "label": "G", "type": "theme", "tier": "standard",
            "objective": "x", "deliverable": "essay", "categories": ["G"],
            "target_depth": 4, "phase": "maintenance", "wiki_node": None,
        }
        self.assertFalse(recommend_focuses._is_developing(maintenance_focus, self._questions()))

    def test_developing_focuses_filters_a_mixed_roadmap(self):
        ready = {
            "id": "f", "label": "F", "type": "theme", "tier": "standard",
            "objective": "x", "deliverable": "essay", "categories": ["F"],
            "target_depth": 4, "phase": "active", "wiki_node": None,
        }
        developing = {
            "id": "g", "label": "G", "type": "theme", "tier": "standard",
            "objective": "x", "deliverable": "essay", "categories": ["G"],
            "target_depth": 4, "phase": "active", "wiki_node": None,
        }
        out = recommend_focuses._developing_focuses(
            {"focuses": [PRIMARY, ready, developing]}, self._questions())
        self.assertEqual([f["id"] for f in out], ["g"])


class AutopilotTargetTests(AutopilotTestBase):
    def test_default_target_is_the_module_constant(self):
        self.assertEqual(
            recommend_focuses.resolve_autopilot_target(),
            recommend_focuses.AUTOPILOT_TARGET_DEVELOPING,
        )

    def test_explicit_override_wins(self):
        self.assertEqual(recommend_focuses.resolve_autopilot_target(5), 5)

    def test_config_override_used_when_no_explicit_override(self):
        recommend_focuses.load_config = lambda *a, **kw: {"focus_autopilot_target": "7"}
        self.assertEqual(recommend_focuses.resolve_autopilot_target(), 7)

    def test_explicit_override_wins_over_config(self):
        recommend_focuses.load_config = lambda *a, **kw: {"focus_autopilot_target": "7"}
        self.assertEqual(recommend_focuses.resolve_autopilot_target(2), 2)

    def test_garbage_config_value_falls_back_to_default(self):
        recommend_focuses.load_config = lambda *a, **kw: {"focus_autopilot_target": "not-a-number"}
        self.assertEqual(
            recommend_focuses.resolve_autopilot_target(),
            recommend_focuses.AUTOPILOT_TARGET_DEVELOPING,
        )


class AutopilotApprovalTests(AutopilotTestBase):
    """focus_autopilot() end to end, through the real approve_recommendation()
    path (only the AI-generation subprocess is stubbed — see setUp)."""

    def test_below_target_worthy_idea_gets_one_real_approval(self):
        self._set_roadmap([PRIMARY])  # developing == 0, target == default 3
        self._set_recs([self._rec("rec-alpha", "Alpha", 15.0)])

        result = recommend_focuses.focus_autopilot()

        self.assertEqual(result["developing_count"], 0)
        self.assertEqual(result["target"], recommend_focuses.AUTOPILOT_TARGET_DEVELOPING)
        self.assertEqual([r["entity"] for r in result["approved"]], ["Alpha"])
        self.assertEqual(result["would_approve"], [])

        state = recommend_focuses.load_recommendation_state()
        rec = next(r for r in state["recommendations"] if r["id"] == "rec-alpha")
        self.assertEqual(rec["status"], "approved")
        self.assertEqual(rec["approved_by"], "auto")
        self.assertTrue(rec.get("focus_id"))
        self.assertTrue(rec.get("category"))

        # The real approve_recommendation() -> roadmap.focus_new() path ran:
        # a new non-primary Focus exists, and its category was scaffolded
        # into the (fixture) question bank — never a zombie.
        new_roadmap = roadmap.load_roadmap()
        new_focus = roadmap.find_focus(new_roadmap, rec["focus_id"])
        self.assertIsNotNone(new_focus)
        self.assertFalse(new_focus.get("primary"))
        self.assertEqual(new_focus["categories"], [rec["category"]])
        bank_text = roadmap.QUESTIONS_FILE.read_text(encoding="utf-8")
        self.assertIn(f"## {rec['category']}: Alpha", bank_text)

    def test_at_target_takes_no_action(self):
        developing = [_filler_focus(f"dev-{i}", f"Dev {i}") for i in range(3)]
        self._set_roadmap([PRIMARY, *developing])  # developing == 3 == target
        self._set_recs([self._rec("rec-alpha", "Alpha", 20.0)])

        result = recommend_focuses.focus_autopilot()

        self.assertEqual(result["developing_count"], 3)
        self.assertEqual(result["approved"], [])
        self.assertIn("at/above target", result["reason"])
        state = recommend_focuses.load_recommendation_state()
        self.assertEqual(state["recommendations"][0]["status"], "pending")

    def test_no_idea_clears_the_floor_takes_no_action(self):
        self._set_roadmap([PRIMARY])
        below_floor = recommend_focuses.FOCUS_READY_SCORE_FLOOR - 0.5
        self._set_recs([self._rec("rec-weak", "Weak", below_floor)])

        result = recommend_focuses.focus_autopilot()

        self.assertEqual(result["approved"], [])
        self.assertIn("no pending idea clears the floor", result["reason"])
        state = recommend_focuses.load_recommendation_state()
        self.assertEqual(state["recommendations"][0]["status"], "pending")

    def test_dismissed_ideas_are_never_chosen_even_if_higher_scoring(self):
        self._set_roadmap([PRIMARY])
        self._set_recs(
            [self._rec("rec-low", "Low", recommend_focuses.FOCUS_READY_SCORE_FLOOR)],
            dismissed=[self._rec("rec-high", "High", 20.0, status="dismissed",
                                  dismissed_by="owner", dismiss_reason="already covered")],
        )

        result = recommend_focuses.focus_autopilot()

        self.assertEqual([r["entity"] for r in result["approved"]], ["Low"])
        state = recommend_focuses.load_recommendation_state()
        self.assertTrue(any(r["id"] == "rec-high" and r.get("status") == "dismissed"
                             for r in state["dismissed"]))

    def test_per_run_cap_holds_even_with_two_slots_open(self):
        self._set_roadmap([PRIMARY])  # 3 slots open against default target 3
        self._set_recs([
            self._rec("rec-alpha", "Alpha", 20.0),
            self._rec("rec-beta", "Beta", 15.0),
        ])

        result = recommend_focuses.focus_autopilot()  # no catch_up -> cap 1

        self.assertEqual(result["cap"], recommend_focuses.AUTOPILOT_MAX_PER_RUN)
        self.assertEqual([r["entity"] for r in result["approved"]], ["Alpha"])
        state = recommend_focuses.load_recommendation_state()
        beta = next(r for r in state["recommendations"] if r["id"] == "rec-beta")
        self.assertEqual(beta["status"], "pending")

    def test_catch_up_fills_to_target_in_one_run(self):
        self._set_roadmap([PRIMARY])
        self._set_recs([
            self._rec("rec-alpha", "Alpha", 20.0),
            self._rec("rec-beta", "Beta", 18.0),
            self._rec("rec-gamma", "Gamma", 16.0),
            self._rec("rec-delta", "Delta", 14.0),
        ])

        result = recommend_focuses.focus_autopilot(catch_up=True)

        self.assertEqual(result["cap"], recommend_focuses.AUTOPILOT_TARGET_DEVELOPING)
        self.assertEqual(
            [r["entity"] for r in result["approved"]], ["Alpha", "Beta", "Gamma"])
        state = recommend_focuses.load_recommendation_state()
        delta = next(r for r in state["recommendations"] if r["id"] == "rec-delta")
        self.assertEqual(delta["status"], "pending")

    def test_dry_run_writes_nothing(self):
        self._set_roadmap([PRIMARY])
        self._set_recs([self._rec("rec-alpha", "Alpha", 20.0)])
        roadmap_before = json.loads(roadmap.ROADMAP_FILE.read_text())
        recs_before = recommend_focuses.load_recommendation_state()

        result = recommend_focuses.focus_autopilot(dry_run=True)

        self.assertEqual(result["approved"], [])
        self.assertEqual([r["entity"] for r in result["would_approve"]], ["Alpha"])
        self.assertEqual(json.loads(roadmap.ROADMAP_FILE.read_text()), roadmap_before)
        self.assertEqual(recommend_focuses.load_recommendation_state(), recs_before)

        # The identical idea is still there for a real run afterwards.
        real = recommend_focuses.focus_autopilot(dry_run=False)
        self.assertEqual([r["entity"] for r in real["approved"]], ["Alpha"])

    def test_idempotent_within_a_week_second_run_takes_no_further_action(self):
        self._set_roadmap([PRIMARY])
        self._set_recs([self._rec("rec-alpha", "Alpha", 20.0)])

        first = recommend_focuses.focus_autopilot()
        self.assertEqual([r["entity"] for r in first["approved"]], ["Alpha"])

        second = recommend_focuses.focus_autopilot()
        self.assertEqual(second["approved"], [])
        # The newly-approved Focus itself now counts as developing —
        # durable state, not a separate cursor file, is what makes the
        # second run a no-op.
        self.assertEqual(second["developing_count"], 1)

    def test_rec_folding_into_an_existing_focus_id_is_skipped(self):
        # The roadmap already grew a Focus with the same id the pending
        # recommendation would slugify to (e.g. added manually, or by a
        # refresh newer than the persisted recommendations file).
        existing = _filler_focus("alpha", "Alpha")
        self._set_roadmap([PRIMARY, existing])
        self._set_recs([self._rec("rec-alpha", "Alpha", 20.0)])

        result = recommend_focuses.focus_autopilot()

        self.assertEqual(result["approved"], [])
        self.assertEqual(result["considered"], [])


class ApprovedByProvenanceTests(AutopilotTestBase):
    def test_manual_approve_defaults_to_owner(self):
        self._set_roadmap([PRIMARY])
        self._set_recs([self._rec("rec-alpha", "Alpha", 15.0)])
        self.assertTrue(recommend_focuses.approve_recommendation("rec-alpha"))
        state = recommend_focuses.load_recommendation_state()
        rec = next(r for r in state["recommendations"] if r["id"] == "rec-alpha")
        self.assertEqual(rec["approved_by"], "owner")

    def test_autopilot_stamps_auto(self):
        self._set_roadmap([PRIMARY])
        self._set_recs([self._rec("rec-alpha", "Alpha", 15.0)])
        self.assertTrue(recommend_focuses.approve_recommendation(
            "rec-alpha", approved_by=recommend_focuses.AUTOPILOT_APPROVED_BY))
        state = recommend_focuses.load_recommendation_state()
        rec = next(r for r in state["recommendations"] if r["id"] == "rec-alpha")
        self.assertEqual(rec["approved_by"], "auto")

    def test_legacy_approved_record_lacks_the_field(self):
        # A record approved before this PR shipped simply has no
        # approved_by key — nothing backfills it retroactively.
        self._set_roadmap([PRIMARY])
        self._set_recs([self._rec("rec-old", "Old", 15.0, status="approved",
                                   approved_at=_iso(datetime(2026, 1, 1, tzinfo=timezone.utc)),
                                   focus_id="old", category="Z")])
        state = recommend_focuses.load_recommendation_state()
        rec = next(r for r in state["recommendations"] if r["id"] == "rec-old")
        self.assertNotIn("approved_by", rec)


class WiringTests(unittest.TestCase):
    """Scope 3/4/6/7: CLI registration, writer-lock classification, monthly
    wiring order, version bump, ADR presence."""

    def setUp(self):
        self.weekly = (SYSTEM / "weekly_maintenance.sh").read_text(encoding="utf-8")
        self.monthly = (SYSTEM / "monthly_research.sh").read_text(encoding="utf-8")

    def test_focus_autopilot_registered_as_a_direct_mutation_command(self):
        import lifehug
        self.assertIn("focus-autopilot", lifehug.DIRECT_MUTATION_COMMANDS)
        parser = lifehug.build_parser()
        subparsers = next(
            action for action in parser._actions  # noqa: SLF001
            if isinstance(action, __import__("argparse")._SubParsersAction)
        )
        self.assertIn("focus-autopilot", subparsers.choices)

    def test_monthly_research_wires_focus_autopilot_after_recommendations(self):
        # ADR 0011 amended 2026-08-15 (owner-ratified, issue #154): MONTHLY
        # cadence — approve from the freshest pending list (directly after
        # recommend-focuses) and before the roster refresh + recompile.
        recommend_idx = self.monthly.index('recommend-focuses --min-score')
        autopilot_idx = self.monthly.index('lifehug.py" focus-autopilot')
        # the REAL roster refresh loop, not the dry-run preview block
        roster_idx = self.monthly.index('ROSTER_OUT=""')
        self.assertLess(recommend_idx, autopilot_idx)
        self.assertLess(autopilot_idx, roster_idx)

    def test_weekly_maintenance_no_longer_runs_the_autopilot(self):
        self.assertNotIn("focus-autopilot", self.weekly)

    def test_version_bumped_with_adr_0011_changelog(self):
        # changelog is a single STRING holding only the most recent bump's
        # entry (not a cumulative log — confirmed convention, e.g. v164 ->
        # v166's changelog dropped all v164 text). A later PR's own bump
        # legitimately replaces this text with its own changelog, so this
        # assertion checks the durable invariants (a real string, version
        # only ever increasing) rather than this PR's own transient wording
        # — see docs/adr/0011-focus-autopilot.md for the durable record.
        data = json.loads((SYSTEM / "version.json").read_text(encoding="utf-8"))
        self.assertIsInstance(data["changelog"], str)
        self.assertTrue(data["changelog"].strip())
        self.assertGreaterEqual(data["version"], 167)

    def test_adr_0011_documents_the_binding_facts(self):
        adr_dir = ROOT / "docs" / "adr"
        matches = list(adr_dir.glob("0011-*.md"))
        self.assertEqual(len(matches), 1)
        text = matches[0].read_text(encoding="utf-8")
        self.assertIn(str(recommend_focuses.AUTOPILOT_TARGET_DEVELOPING), text)
        self.assertIn(str(recommend_focuses.AUTOPILOT_MAX_PER_RUN), text)
        self.assertIn(str(recommend_focuses.FOCUS_READY_SCORE_FLOOR), text)
        self.assertIn("approved_by", text)
        self.assertIn("catch-up", text.lower())
        self.assertIn("one-run lag", text.lower())
        self.assertIn("never created without you", text)


if __name__ == "__main__":
    unittest.main()
