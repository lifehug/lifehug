"""Tests for v134 — issue #79: the focus-recommendation completion gate,
ready_to_start eligibility, and pending-recommendation rot control.

The owner's rule: starting a new Focus (auto-created or elevated to "ready
to start") spends the same weekly question budget the author's *unfinished*
focuses need, so the gate stays closed while any active non-primary focus
is still short of READY/SATURATED. Everything here is synthetic — a
throwaway vault per test, never the founder vault.
"""

from __future__ import annotations

import json
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SYSTEM = ROOT / "system"
sys.path.insert(0, str(SYSTEM))
sys.path.insert(0, str(ROOT / "tests"))

from tempdirs import root_parent_tmp  # noqa: E402
import entity_roster  # noqa: E402
import recommend_focuses  # noqa: E402
import roadmap  # noqa: E402

PRIMARY = {
    "id": "my-life", "label": "My Life", "type": "life_story", "primary": True,
    "tier": "extreme", "objective": "story", "deliverable": "book",
    "categories": ["A"], "target_depth": 4, "phase": "active", "wiki_node": None,
}

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


class GateTestBase(unittest.TestCase):
    """Shared fixture plumbing, following tests/test_wiki_views.py's
    real-path-tmp-dir + monkeypatched-module-attribute convention."""

    def setUp(self):
        self.tmp = root_parent_tmp(self, ROOT)
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
        }
        qbank = self._write("question-bank.md", QUESTION_BANK)
        roadmap.QUESTIONS_FILE = qbank
        recommend_focuses.QUESTIONS_FILE = qbank
        recommend_focuses.ANSWERS_DIR = self.tmp / "answers"
        recommend_focuses.MANUAL_SOURCES_DIR = self.tmp / "sources"
        recommend_focuses.CLASSIFICATIONS_DIR = self.tmp / "classifications"
        recommend_focuses.WIKI_DIR = self.tmp / "wiki"
        recommend_focuses.FOCUS_RECS_FILE = self.tmp / "focus_recommendations.json"
        recommend_focuses.LEGACY_FOCUS_RECS_FILE = self.tmp / "legacy_focus_recommendations.json"
        entity_roster.ENTITY_DIR = self.tmp / "no-rosters"

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


class FocusStartGateTests(GateTestBase):
    def test_all_ready_or_saturated_opens_gate(self):
        # F: 3/4 answered -> saturation 0.75 -> READY (not saturated).
        non_primary = {
            "id": "etherfuse", "label": "Etherfuse", "type": "project",
            "tier": "standard", "objective": "founding", "deliverable": "book",
            "categories": ["F"], "target_depth": 4, "phase": "active", "wiki_node": None,
        }
        self._set_roadmap([PRIMARY, non_primary])
        gate = recommend_focuses.focus_start_gate()
        self.assertTrue(gate["open"])
        self.assertEqual(gate["blocking"], [])

    def test_one_developing_non_primary_closes_gate_and_names_it(self):
        # G: 2/4 answered -> saturation 0.5 -> DEVELOPING (below READY 0.70).
        developing = {
            "id": "second-thing", "label": "Second Thing", "type": "theme",
            "tier": "standard", "objective": "explore", "deliverable": "essay",
            "categories": ["G"], "target_depth": 4, "phase": "active", "wiki_node": None,
        }
        self._set_roadmap([PRIMARY, developing])
        gate = recommend_focuses.focus_start_gate()
        self.assertFalse(gate["open"])
        self.assertEqual(len(gate["blocking"]), 1)
        block = gate["blocking"][0]
        self.assertEqual(block["focus_id"], "second-thing")
        self.assertEqual(block["label"], "Second Thing")
        self.assertEqual(block["verdict"], "DEVELOPING")
        self.assertIn("Second Thing", gate["reason"])

    def test_primary_only_vault_opens_gate(self):
        self._set_roadmap([PRIMARY])
        gate = recommend_focuses.focus_start_gate()
        self.assertTrue(gate["open"])
        self.assertEqual(gate["blocking"], [])

    def test_primary_focus_exempt_even_if_early(self):
        # The primary's own saturation (0.25 here) must never gate anything.
        early_primary = dict(PRIMARY, target_depth=100)
        self._set_roadmap([early_primary])
        gate = recommend_focuses.focus_start_gate()
        self.assertTrue(gate["open"])

    def test_maintenance_phase_focus_excluded_from_gate(self):
        # A focus the owner explicitly parked in "maintenance" is not "open"
        # work — it should not block new starts even if under-saturated.
        maintenance = {
            "id": "second-thing", "label": "Second Thing", "type": "theme",
            "tier": "standard", "objective": "explore", "deliverable": "essay",
            "categories": ["G"], "target_depth": 4, "phase": "maintenance", "wiki_node": None,
        }
        self._set_roadmap([PRIMARY, maintenance])
        gate = recommend_focuses.focus_start_gate()
        self.assertTrue(gate["open"])

    def test_saturated_non_primary_opens_gate(self):
        # A: 1/2 answered against a target of 1 -> saturation >= 1.0 -> SATURATED.
        saturated = {
            "id": "origins", "label": "Origins Focus", "type": "theme",
            "tier": "standard", "objective": "x", "deliverable": "essay",
            "categories": ["A"], "target_depth": 1, "phase": "finishing", "wiki_node": None,
        }
        self._set_roadmap([PRIMARY, saturated])
        gate = recommend_focuses.focus_start_gate()
        self.assertTrue(gate["open"])

    def test_exhausted_focus_with_zero_pending_does_not_block(self):
        # H: 5/5 answered against a target of 20 -> saturation 0.25 (EARLY by
        # the raw ratio) but pending == 0 — nothing left to answer. The
        # owner's rule is about unanswered material, so a focus you cannot
        # advance by answering more questions must not block the gate just
        # because its target_depth was set stale/high.
        exhausted = {
            "id": "exhausted", "label": "Exhausted Focus", "type": "theme",
            "tier": "standard", "objective": "x", "deliverable": "essay",
            "categories": ["H"], "target_depth": 20, "phase": "active", "wiki_node": None,
        }
        self._set_roadmap([PRIMARY, exhausted])
        gate = recommend_focuses.focus_start_gate()
        self.assertTrue(gate["open"])
        self.assertEqual(gate["blocking"], [])

    def test_exhausted_focus_does_not_mask_a_real_blocker(self):
        # A zero-pending focus is exempt, but a genuinely unfinished one
        # alongside it must still block — the exemption isn't a blanket
        # "any non-primary focus present opens the gate".
        exhausted = {
            "id": "exhausted", "label": "Exhausted Focus", "type": "theme",
            "tier": "standard", "objective": "x", "deliverable": "essay",
            "categories": ["H"], "target_depth": 20, "phase": "active", "wiki_node": None,
        }
        developing = {
            "id": "second-thing", "label": "Second Thing", "type": "theme",
            "tier": "standard", "objective": "explore", "deliverable": "essay",
            "categories": ["G"], "target_depth": 4, "phase": "active", "wiki_node": None,
        }
        self._set_roadmap([PRIMARY, exhausted, developing])
        gate = recommend_focuses.focus_start_gate()
        self.assertFalse(gate["open"])
        self.assertEqual([b["focus_id"] for b in gate["blocking"]], ["second-thing"])


class RecommendationExpiryTests(GateTestBase):
    """apply_recommendation_expiry() — rot control (issue #79)."""

    def _rec(self, rec_id, score, created_at, status="pending"):
        return {
            "id": rec_id, "entity": rec_id, "type": "theme", "score": score,
            "evidence_strength": "weak", "mention_count": 1, "unique_answers": 1,
            "cross_categories": ["Z"], "emotional_weight": 0.0, "evidence": [],
            "reason": "x", "status": status, "created_at": created_at,
        }

    def test_old_low_score_pending_expires(self):
        now = datetime(2026, 8, 9, tzinfo=timezone.utc)
        old = _iso(now - timedelta(weeks=recommend_focuses.FOCUS_RECOMMENDATION_EXPIRY_WEEKS + 1))
        recs = [self._rec("rec-old-weak", 5.0, old)]
        kept, expired = recommend_focuses.apply_recommendation_expiry(recs, now=_iso(now))
        self.assertEqual(kept, [])
        self.assertEqual(len(expired), 1)
        self.assertEqual(expired[0]["status"], "expired")
        self.assertEqual(
            expired[0]["dismiss_reason"],
            f"expired: below threshold for {recommend_focuses.FOCUS_RECOMMENDATION_EXPIRY_WEEKS} weeks",
        )
        self.assertIn("dismissed_at", expired[0])

    def test_recent_low_score_pending_kept(self):
        now = datetime(2026, 8, 9, tzinfo=timezone.utc)
        recent = _iso(now - timedelta(weeks=1))
        recs = [self._rec("rec-recent-weak", 5.0, recent)]
        kept, expired = recommend_focuses.apply_recommendation_expiry(recs, now=_iso(now))
        self.assertEqual(len(kept), 1)
        self.assertEqual(kept[0]["id"], "rec-recent-weak")
        self.assertEqual(expired, [])

    def test_high_score_pending_kept_regardless_of_age(self):
        now = datetime(2026, 8, 9, tzinfo=timezone.utc)
        ancient = _iso(now - timedelta(weeks=52))
        recs = [self._rec("rec-old-strong", recommend_focuses.FOCUS_READY_SCORE_FLOOR, ancient)]
        kept, expired = recommend_focuses.apply_recommendation_expiry(recs, now=_iso(now))
        self.assertEqual(len(kept), 1)
        self.assertEqual(expired, [])

    def test_non_pending_status_never_expires(self):
        now = datetime(2026, 8, 9, tzinfo=timezone.utc)
        ancient = _iso(now - timedelta(weeks=52))
        recs = [self._rec("rec-approved-weak", 2.0, ancient, status="approved")]
        kept, expired = recommend_focuses.apply_recommendation_expiry(recs, now=_iso(now))
        self.assertEqual(len(kept), 1)
        self.assertEqual(expired, [])


class RecommendationRefreshTests(GateTestBase):
    """recommend() end to end: ready_to_start computation and the
    expiry-exempt-from-blocklist behavior, wired through save_recommendations()."""

    def _classify(self, name, entity, entity_type, strength, qid, category):
        self._write(f"classifications/{name}.json", {
            "question_id": qid,
            "focus_opportunities": [
                {"entity": entity, "type": entity_type, "evidence_strength": strength,
                 "reason": f"seen in {qid}"},
            ],
        })

    def test_ready_to_start_true_only_above_floor_when_gate_open(self):
        self._set_roadmap([PRIMARY])  # primary-only -> gate open
        # "strong" -> boost 3.0 -> score well above FOCUS_READY_SCORE_FLOOR.
        self._classify("c1", "Alpha", "theme", "strong", "Z1", "Z")
        # "weak" -> boost 0.5 -> score well below the floor.
        self._classify("c2", "Beta", "theme", "weak", "Z2", "Z")
        recs = {r["entity"]: r for r in recommend_focuses.recommend(min_score=3.0)}
        self.assertGreaterEqual(recs["Alpha"]["score"], recommend_focuses.FOCUS_READY_SCORE_FLOOR)
        self.assertLess(recs["Beta"]["score"], recommend_focuses.FOCUS_READY_SCORE_FLOOR)
        self.assertTrue(recs["Alpha"]["ready_to_start"])
        self.assertFalse(recs["Beta"]["ready_to_start"])

    def test_ready_to_start_false_when_gate_closed_even_above_floor(self):
        developing = {
            "id": "second-thing", "label": "Second Thing", "type": "theme",
            "tier": "standard", "objective": "x", "deliverable": "essay",
            "categories": ["G"], "target_depth": 4, "phase": "active", "wiki_node": None,
        }
        self._set_roadmap([PRIMARY, developing])  # gate closed
        self._classify("c1", "Alpha", "theme", "strong", "Z1", "Z")
        recs = {r["entity"]: r for r in recommend_focuses.recommend(min_score=3.0)}
        self.assertGreaterEqual(recs["Alpha"]["score"], recommend_focuses.FOCUS_READY_SCORE_FLOOR)
        self.assertFalse(recs["Alpha"]["ready_to_start"])

    def test_expiry_dismissal_does_not_block_repropose_once_score_clears_floor(self):
        # Structured dismissed_by="expiry" marker, AND the re-detected score
        # (strong -> well above the floor) is what lets it back in.
        self._set_roadmap([PRIMARY])
        recommend_focuses.write_json(recommend_focuses.FOCUS_RECS_FILE, {
            "version": 1, "recommendations": [],
            "dismissed": [{"id": "rec-alpha", "entity": "Alpha",
                           "dismissed_by": recommend_focuses.EXPIRY_DISMISSED_BY,
                           "dismiss_reason": "expired: below threshold for 6 weeks"}],
        })
        self._classify("c1", "Alpha", "theme", "strong", "Z1", "Z")
        recs = recommend_focuses.recommend(min_score=3.0)
        self.assertTrue(any(r["id"] == "rec-alpha" for r in recs))

    def test_expiry_dismissal_stays_blocked_while_still_weak(self):
        # Re-detection alone isn't enough — the score must actually clear
        # the floor. A still-weak re-appearance stays suppressed (otherwise
        # it would re-enter "recommendations" with a reset created_at clock
        # and never genuinely expire again).
        self._set_roadmap([PRIMARY])
        recommend_focuses.write_json(recommend_focuses.FOCUS_RECS_FILE, {
            "version": 1, "recommendations": [],
            "dismissed": [{"id": "rec-alpha", "entity": "Alpha",
                           "dismissed_by": recommend_focuses.EXPIRY_DISMISSED_BY,
                           "dismiss_reason": "expired: below threshold for 6 weeks"}],
        })
        self._classify("c1", "Alpha", "theme", "weak", "Z1", "Z")
        recs = recommend_focuses.recommend(min_score=3.0)
        self.assertFalse(any(r["id"] == "rec-alpha" for r in recs))
        # --include-dismissed still surfaces it explicitly, unchanged.
        recs_incl = recommend_focuses.recommend(min_score=3.0, include_dismissed=True)
        self.assertTrue(any(r["id"] == "rec-alpha" for r in recs_incl))

    def test_owner_dismissal_still_blocks_repropose(self):
        self._set_roadmap([PRIMARY])
        recommend_focuses.write_json(recommend_focuses.FOCUS_RECS_FILE, {
            "version": 1, "recommendations": [],
            "dismissed": [{"id": "rec-alpha", "entity": "Alpha",
                           "dismiss_reason": "already covered elsewhere"}],
        })
        self._classify("c1", "Alpha", "theme", "strong", "Z1", "Z")
        recs = recommend_focuses.recommend(min_score=3.0)
        self.assertFalse(any(r["id"] == "rec-alpha" for r in recs))
        # ...but --include-dismissed still surfaces it, unchanged behavior.
        recs_incl = recommend_focuses.recommend(min_score=3.0, include_dismissed=True)
        self.assertTrue(any(r["id"] == "rec-alpha" for r in recs_incl))

    def test_manual_dismissal_with_expired_looking_text_still_blocks(self):
        # dismissed_by (structured), never dismiss_reason text, decides
        # expiry-origin — an owner's free-text reason that happens to start
        # with "expired:" must not accidentally self-un-blocklist.
        self._set_roadmap([PRIMARY])
        recommend_focuses.write_json(recommend_focuses.FOCUS_RECS_FILE, {
            "version": 1, "recommendations": [],
            "dismissed": [{"id": "rec-alpha", "entity": "Alpha",
                           "dismiss_reason": "expired: I just don't like it"}],
        })
        self._classify("c1", "Alpha", "theme", "strong", "Z1", "Z")
        recs = recommend_focuses.recommend(min_score=3.0)
        self.assertFalse(any(r["id"] == "rec-alpha" for r in recs))

    def test_save_recommendations_expires_stale_entries_on_refresh(self):
        # The monthly entry point (`lifehug.py recommend-focuses`) calls
        # recommend() then save_recommendations() — this is where rot
        # control actually runs against the persisted state.
        self._set_roadmap([PRIMARY])
        fixed_now = _iso(datetime(2026, 8, 9, tzinfo=timezone.utc))
        old = _iso(datetime(2026, 8, 9, tzinfo=timezone.utc) - timedelta(
            weeks=recommend_focuses.FOCUS_RECOMMENDATION_EXPIRY_WEEKS + 1))
        stale_pending = {
            "id": "rec-old", "entity": "Old", "type": "theme", "score": 4.0,
            "evidence_strength": "weak", "mention_count": 1, "unique_answers": 1,
            "cross_categories": ["Z"], "emotional_weight": 0.0, "evidence": [],
            "reason": "x", "status": "pending", "created_at": old,
        }
        recommend_focuses.save_recommendations([stale_pending], now=fixed_now)
        data = recommend_focuses.load_recommendation_state()
        self.assertEqual(data["recommendations"], [])
        self.assertEqual(len(data["dismissed"]), 1)
        self.assertEqual(data["dismissed"][0]["id"], "rec-old")
        self.assertEqual(data["dismissed"][0]["dismissed_by"], recommend_focuses.EXPIRY_DISMISSED_BY)
        self.assertTrue(data["dismissed"][0]["dismiss_reason"].startswith("expired:"))
        # dismissed_at honors the injected "now", not the real wall clock.
        self.assertEqual(data["dismissed"][0]["dismissed_at"], fixed_now)

    def test_save_recommendations_dedupes_repeat_expiry_by_id(self):
        # Defensive dedup: even called directly (bypassing recommend()'s own
        # score-gated re-entry guard) with the same still-pending, still-old
        # rec twice, the dismissed list holds exactly one entry for that id —
        # a second expiry REPLACES the first, never appends a duplicate.
        self._set_roadmap([PRIMARY])
        old = _iso(datetime(2026, 1, 1, tzinfo=timezone.utc))

        def stale():
            return {
                "id": "rec-old", "entity": "Old", "type": "theme", "score": 4.0,
                "evidence_strength": "weak", "mention_count": 1, "unique_answers": 1,
                "cross_categories": ["Z"], "emotional_weight": 0.0, "evidence": [],
                "reason": "x", "status": "pending", "created_at": old,
            }

        recommend_focuses.save_recommendations(
            [stale()], now=_iso(datetime(2026, 3, 1, tzinfo=timezone.utc)))
        state = recommend_focuses.load_recommendation_state()
        self.assertEqual(len(state["dismissed"]), 1)
        first_dismissed_at = state["dismissed"][0]["dismissed_at"]

        recommend_focuses.save_recommendations(
            [stale()], now=_iso(datetime(2026, 5, 1, tzinfo=timezone.utc)))
        state = recommend_focuses.load_recommendation_state()
        self.assertEqual(len(state["dismissed"]), 1)
        self.assertEqual(state["dismissed"][0]["id"], "rec-old")
        self.assertNotEqual(state["dismissed"][0]["dismissed_at"], first_dismissed_at)


class MultiRefreshRotControlRegressionTests(GateTestBase):
    """Reproduces the merge-gate finding directly: run recommend() +
    save_recommendations() across several simulated monthly refreshes and
    prove (1) a weak rec expires exactly once, (2) it stays gone — not
    re-proposed with a reset clock — on every subsequent refresh while still
    weak, (3) the dismissed list never accumulates duplicate entries for the
    same entity, and (4) a later refresh where fresh evidence pushes the
    score past the floor DOES bring it back."""

    def _classify_weak(self):
        self._write("classifications/c1.json", {
            "question_id": "Z1",
            "focus_opportunities": [
                {"entity": "Weak", "type": "theme", "evidence_strength": "weak",
                 "reason": "seen in Z1"},
            ],
        })

    def _classify_strong(self):
        self._write("classifications/c1.json", {
            "question_id": "Z1",
            "focus_opportunities": [
                {"entity": "Weak", "type": "theme", "evidence_strength": "strong",
                 "reason": "fresh strong evidence in Z1"},
            ],
        })

    def _refresh(self, now: datetime):
        # recommend() stamps a NEW rec's created_at with now_utc() (the real
        # wall clock) — to simulate several monthly refreshes at controlled
        # points in time, the clock itself has to move, not just the
        # save_recommendations() "now" override (which only controls the
        # expiry-age comparison, not creation timestamps).
        now_str = _iso(now)
        orig_now_utc = recommend_focuses.now_utc
        recommend_focuses.now_utc = lambda: now_str
        try:
            recs = recommend_focuses.recommend(min_score=3.0)
            recommend_focuses.save_recommendations(recs, now=now_str)
        finally:
            recommend_focuses.now_utc = orig_now_utc
        return recs

    def test_weak_rec_expires_once_and_stays_gone_then_returns_when_strong(self):
        self._set_roadmap([PRIMARY])
        self._classify_weak()
        t0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
        weeks = recommend_focuses.FOCUS_RECOMMENDATION_EXPIRY_WEEKS

        # Run 1 (t0): first appearance, pending, not yet old enough to expire.
        self._refresh(t0)
        state = recommend_focuses.load_recommendation_state()
        self.assertEqual(len(state["recommendations"]), 1)
        self.assertEqual(state["recommendations"][0]["status"], "pending")
        self.assertEqual(state["dismissed"], [])

        # Run 2 (t0 + weeks-1): still under the expiry age -> still pending.
        self._refresh(t0 + timedelta(weeks=weeks - 1))
        state = recommend_focuses.load_recommendation_state()
        self.assertEqual(len(state["recommendations"]), 1)
        self.assertEqual(state["dismissed"], [])

        # Run 3 (t0 + weeks+1): now old enough -> expires this refresh.
        self._refresh(t0 + timedelta(weeks=weeks + 1))
        state = recommend_focuses.load_recommendation_state()
        self.assertEqual(state["recommendations"], [])
        self.assertEqual(len(state["dismissed"]), 1)
        self.assertEqual(state["dismissed"][0]["dismissed_by"], recommend_focuses.EXPIRY_DISMISSED_BY)

        # Run 4 (t0 + weeks+5): still weak on re-detection -> stays gone,
        # NOT re-added-then-re-expired — dismissed still holds exactly one
        # entry (no duplicate accumulation, no clock reset).
        self._refresh(t0 + timedelta(weeks=weeks + 5))
        state = recommend_focuses.load_recommendation_state()
        self.assertEqual(state["recommendations"], [])
        self.assertEqual(len(state["dismissed"]), 1)

        # Run 5 (t0 + weeks+6): fresh strong evidence clears the floor ->
        # comes back as a pending recommendation.
        self._classify_strong()
        self._refresh(t0 + timedelta(weeks=weeks + 6))
        state = recommend_focuses.load_recommendation_state()
        self.assertEqual(len(state["recommendations"]), 1)
        self.assertEqual(state["recommendations"][0]["status"], "pending")
        self.assertGreaterEqual(state["recommendations"][0]["score"],
                                recommend_focuses.FOCUS_READY_SCORE_FLOOR)
        # No duplicate dismissed entry accumulated for the same entity.
        self.assertEqual(len(state["dismissed"]), 1)


if __name__ == "__main__":
    unittest.main()
