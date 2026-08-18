"""Contract tests for the unified quality score (docs/pr-specs/unified-quality-score.md,
ADR 0008): ONE published quality score — clamp(priority ×
story_function_multiplier − craft_penalty_total, 0, 1) — replacing the old
parallel promotion score / craft score / QUALITY_GATE_MIN craft gate."""

from __future__ import annotations

import argparse
import contextlib
import importlib.util
import io
import itertools
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SYSTEM = ROOT / "system"
sys.path.insert(0, str(SYSTEM))


def load(name):
    """Load a private copy of system/<name>.py WITHOUT clobbering the shared
    sys.modules entry — same pattern as tests/test_v68_loop.py: other test
    modules bind the canonical module at import time, and replacing it
    mid-suite would split state across two module objects."""
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


qc = load("question_candidates")


# A "clean" candidate: no yes/no wording, no self-directed why, not too
# broad, has a scene marker ("walk me through", "what did the room look
# like") plus an emotion marker ("afraid"), long enough to dodge
# too_short/possibly_vague. check_quality() should return zero flags for it.
CLEAN_TEXT = (
    "Walk me through the day you decided to leave — what did the room "
    "look like, and what were you most afraid of?"
)


class UnifiedScoreUnitTests(unittest.TestCase):
    """unified_quality_score() in isolation — no store, no auto-promote."""

    def test_clean_candidate_score_is_priority_times_multiplier(self):
        candidate = {"text": CLEAN_TEXT, "priority": 0.8, "source_path": "answers/A1.md"}
        unified = qc.unified_quality_score(candidate, None, None)
        self.assertEqual(unified["score"], 0.8)
        self.assertEqual(unified["components"]["priority"], 0.8)
        self.assertEqual(unified["components"]["story_function_multiplier"], 1.0)
        self.assertEqual(unified["components"]["craft_penalties"], [])
        self.assertEqual(unified["components"]["penalty_total"], 0.0)
        self.assertIn("computed_at", unified)

    def test_active_profile_applies_the_story_function_multiplier(self):
        candidate = {"text": CLEAN_TEXT, "priority": 0.7, "story_function": "turning_point",
                     "source_path": "answers/A1.md"}
        profile = {"active": True, "by_story_function": {"turning_point": {"multiplier": 1.3}}}
        unified = qc.unified_quality_score(candidate, profile, None)
        self.assertAlmostEqual(unified["score"], round(0.7 * 1.3, 4))
        self.assertEqual(unified["components"]["story_function_multiplier"], 1.3)

    def test_each_penalty_flag_drags_exactly_its_weight(self):
        # One isolated flag per case (verified independently against
        # check_quality before being pinned here) — the craft-penalty table
        # itself lives ONLY in check_quality; this proves unified_quality_score
        # consumes it faithfully rather than re-deriving weights.
        cases = [
            ("yes_no_wording", 0.25,
             {"text": "Did you enjoy what happened on your first day at the new job downtown?",
              "priority": 1.0, "source_path": "answers/A1.md"}),
            ("self_directed_why", 0.20,
             {"text": "Why do you always feel like an outsider at these events?",
              "priority": 1.0, "source_path": "answers/A1.md"}),
            ("too_broad", 0.20,
             {"text": "How do you feel about your career choices overall?",
              "priority": 1.0, "source_path": "answers/A1.md"}),
            ("no_scene_or_stakes_path", 0.15,
             {"text": "Tell me something important that happened during that period of your life.",
              "priority": 1.0, "source_path": "answers/A1.md"}),
            ("no_source_citation", 0.10,
             {"text": CLEAN_TEXT, "priority": 1.0}),
            ("too_short", 0.15,
             {"text": "Tell me why now?", "priority": 1.0, "source_path": "answers/A1.md"}),
            ("possibly_vague", 0.05,
             {"text": "What was your mother like then?", "priority": 1.0, "source_path": "answers/A1.md"}),
        ]
        for flag, weight, candidate in cases:
            with self.subTest(flag=flag):
                unified = qc.unified_quality_score(candidate, None, None)
                penalties = unified["components"]["craft_penalties"]
                self.assertEqual([p["flag"] for p in penalties], [flag], candidate["text"])
                self.assertEqual(penalties[0]["penalty"], weight)
                self.assertEqual(unified["components"]["penalty_total"], weight)
                self.assertAlmostEqual(unified["score"], round(1.0 - weight, 4))

    def test_duplicate_flag_drags_its_weight(self):
        candidate = {"text": "What is your favorite childhood memory of summer?",
                     "priority": 1.0, "source_path": "answers/A1.md"}
        existing = [{"id": "A1", "text": "What is your favorite childhood memory of summer?"}]
        unified = qc.unified_quality_score(candidate, None, existing)
        flags = [p["flag"] for p in unified["components"]["craft_penalties"]]
        self.assertEqual(flags, ["duplicate_of_A1"])
        self.assertEqual(unified["components"]["penalty_total"], 0.50)
        self.assertEqual(unified["score"], 0.50)

    def test_clamp_at_zero(self):
        candidate = {"text": "Did you?", "priority": 1.0, "source_path": "answers/A1.md"}
        existing = [{"id": "A1", "text": "Did you?"}]
        unified = qc.unified_quality_score(candidate, None, existing)
        self.assertEqual(unified["score"], 0.0)
        self.assertGreater(unified["components"]["penalty_total"], 1.0)

    def test_clamp_at_one(self):
        candidate = {"text": CLEAN_TEXT, "priority": 1.0, "story_function": "turning_point",
                     "source_path": "answers/A1.md"}
        profile = {"active": True, "by_story_function": {"turning_point": {"multiplier": 1.5}}}
        unified = qc.unified_quality_score(candidate, profile, None)
        self.assertEqual(unified["score"], 1.0)
        self.assertEqual(unified["components"]["story_function_multiplier"], 1.5)

    def test_score_candidate_for_promotion_delegates_and_ignores_craft(self):
        # score_candidate_for_promotion is promotion-component-only (no craft
        # penalties) — it delegates into unified_quality_score()'s components
        # so priority × multiplier has exactly one definition.
        candidate = {"text": "Did you?", "priority": 0.9}  # heavy craft flags, ignored here
        promotion_only = qc.score_candidate_for_promotion(candidate, None)
        self.assertEqual(promotion_only, 0.9)


class AutoPromoteLadderTests(unittest.TestCase):
    """Integration tests through auto_promote_candidates() — the ladder
    re-expressed over the unified score (contract §Scope item 2), stamping
    (§Scope item 3), and idempotence/resurfacing (§Implementation notes)."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="lifehug-uqs-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.bank_path = self.tmp / "question-bank.md"
        self.cand_path = self.tmp / "question_candidates.json"
        self.bank_path.write_text(
            "## A: Origins (Childhood)\n"
            "- [ ] A1: What did you promise yourself you'd do differently as a parent?\n",
            encoding="utf-8",
        )

        # QUESTIONS_FILE / QUESTION_CANDIDATES_FILE are plain module globals
        # read fresh at call time — a direct monkeypatch redirects them. But
        # load_store()/save_store()'s `path` parameter defaults were bound to
        # the ORIGINAL Path objects at function-definition time (Python
        # evaluates defaults once), so auto_promote_candidates()'s bare
        # load_store()/save_store(data) calls need those defaults patched
        # too — never the real system/question-bank.md or state store.
        self._orig_questions_file = qc.QUESTIONS_FILE
        self._orig_candidates_file = qc.QUESTION_CANDIDATES_FILE
        self._orig_load_defaults = qc.load_store.__defaults__
        self._orig_save_defaults = qc.save_store.__defaults__
        self._orig_profile_loader = qc._load_quality_profile_safely
        self._orig_promotion_resolver = qc.candidate_promotion.resolve_candidate_promotion
        qc.QUESTIONS_FILE = self.bank_path
        qc.QUESTION_CANDIDATES_FILE = self.cand_path
        qc.load_store.__defaults__ = (self.cand_path,)
        qc.save_store.__defaults__ = (self.cand_path,)
        qc._load_quality_profile_safely = lambda: None  # inactive profile: multiplier 1.0

        def resolve_fixture(request, **kwargs):
            data = qc.load_store()
            bank = qc.QUESTIONS_FILE.read_text(encoding="utf-8")
            updated, payload = qc.candidate_promotion.apply_candidate_promotion(
                data, bank, request,
                promotion_mode=kwargs.get("promotion_mode", "auto"),
                auto_score=kwargs.get("auto_score"))
            qc.write_text(qc.QUESTIONS_FILE, updated)
            qc.save_store(data)
            return {
                "candidate_id": payload["candidate_id"],
                "category_id": payload["category_id"],
                "question_id": payload["question_id"],
                "changed": True,
                "commit_sha": "0" * 40,
                "candidate_provenance": payload["candidate_provenance"],
            }

        qc.candidate_promotion.resolve_candidate_promotion = resolve_fixture

    def tearDown(self):
        qc.QUESTIONS_FILE = self._orig_questions_file
        qc.QUESTION_CANDIDATES_FILE = self._orig_candidates_file
        qc.load_store.__defaults__ = self._orig_load_defaults
        qc.save_store.__defaults__ = self._orig_save_defaults
        qc._load_quality_profile_safely = self._orig_profile_loader
        qc.candidate_promotion.resolve_candidate_promotion = self._orig_promotion_resolver

    def _write_store(self, candidates):
        self.cand_path.write_text(
            json.dumps({"version": 1, "candidates": candidates}), encoding="utf-8")

    def _reload_by_id(self):
        candidates = json.loads(self.cand_path.read_text(encoding="utf-8"))["candidates"]
        return {c["id"]: c for c in candidates}

    def test_penalty_free_candidate_auto_promotes_unchanged(self):
        # Behavior-preservation case (contract Test plan): the ≥0.82 band is
        # unaffected for a candidate with zero craft penalties.
        self._write_store([{
            "id": "cand-clean", "status": "candidate", "priority": 0.9,
            "text": CLEAN_TEXT, "target_category": "A", "source_path": "answers/B1.md",
            "created_at": "2026-08-01T00:00:00Z",
        }])
        result = qc.auto_promote_candidates(dry_run=False)
        self.assertIn("cand-clean", [p[0] for p in result["promoted"]])
        stored = self._reload_by_id()["cand-clean"]
        self.assertEqual(stored["status"], "auto_promoted")
        self.assertEqual(stored["promotion_score"], 0.9)
        self.assertEqual(stored["quality"]["score"], 0.9)
        self.assertEqual(stored["quality"]["components"]["craft_penalties"], [])

    def test_heavy_flag_candidate_falls_below_review_band_and_stays_candidate(self):
        self._write_store([{
            "id": "cand-heavy", "status": "candidate", "priority": 0.95,
            "text": "Did you?", "target_category": "A",
            "created_at": "2026-08-01T00:00:00Z",
        }])
        result = qc.auto_promote_candidates(dry_run=False)
        self.assertNotIn("cand-heavy", [p[0] for p in result["promoted"]])
        self.assertNotIn("cand-heavy", [r[0] for r in result["needs_review"]])
        self.assertIn("cand-heavy", [s[0] for s in result["skipped"]])
        stored = self._reload_by_id()["cand-heavy"]
        self.assertEqual(stored["status"], "candidate")  # unchanged — no park
        self.assertLess(stored["quality"]["score"], qc.NEEDS_REVIEW_THRESHOLD)

    def test_mid_flag_candidate_parks_with_flags_quoted_in_reason(self):
        self._write_store([{
            "id": "cand-mid", "status": "candidate", "priority": 0.95,
            "text": "Why do you always struggle with that decision?",
            "target_category": "A", "source_path": "answers/B2.md",
            "story_function": "turning_point",
            "created_at": "2026-08-01T00:00:00Z",
        }])
        result = qc.auto_promote_candidates(dry_run=False)
        review = {r[0]: r for r in result["needs_review"]}
        self.assertIn("cand-mid", review)
        _cid, score, reason = review["cand-mid"]
        self.assertAlmostEqual(score, 0.75)
        self.assertIn("self_directed_why", reason)
        self.assertIn("0.75", reason)
        stored = self._reload_by_id()["cand-mid"]
        self.assertEqual(stored["status"], "needs_review")
        self.assertIn("self_directed_why", stored["needs_review_reason"])

    def test_near_duplicate_parks_regardless_of_score(self):
        self._write_store([{
            "id": "cand-neardup", "status": "candidate", "priority": 0.99,
            "text": "As a parent, what did you promise yourself you would do differently?",
            "target_category": "A", "source_path": "answers/B3.md",
            "created_at": "2026-08-01T00:00:00Z",
        }])
        result = qc.auto_promote_candidates(dry_run=False)
        review = {r[0]: r for r in result["needs_review"]}
        self.assertIn("cand-neardup", review)
        self.assertIn("near_duplicate of A1", review["cand-neardup"][2])

    def test_missing_category_parks_regardless_of_score(self):
        # This candidate's unified score (~0.74) would itself land in the
        # needs_review band — the point is that the structural
        # missing_category park fires FIRST, before the score is even
        # consulted, and the reason names the structural cause, not a score.
        self._write_store([{
            "id": "cand-nocat", "status": "candidate", "priority": 0.99,
            "text": "A completely unique scene question about a specific childhood afternoon spent alone.",
            "created_at": "2026-08-01T00:00:00Z",
        }])
        result = qc.auto_promote_candidates(dry_run=False)
        review = {r[0]: r for r in result["needs_review"]}
        self.assertIn("cand-nocat", review)
        self.assertEqual(review["cand-nocat"][2], "missing_category")

    def test_stamping_is_idempotent_across_unchanged_replays(self):
        # now_utc() has one-second resolution, which could mask a false pass
        # in a fast test run — pin an always-unique fake clock in its place
        # (every call anywhere in this run gets a distinct value) so "did
        # computed_at actually advance" is unambiguous either way.
        ticks = itertools.count(1)
        original_now_utc = qc.now_utc
        self.addCleanup(setattr, qc, "now_utc", original_now_utc)
        qc.now_utc = lambda: f"2026-08-14T00:00:{next(ticks):03d}Z"

        self._write_store([{
            "id": "cand-mid", "status": "candidate", "priority": 0.95,
            "text": "Why do you always struggle with that decision?",
            "target_category": "A", "source_path": "answers/B2.md",
            "story_function": "turning_point",
            "created_at": "2026-08-01T00:00:00Z",
        }])
        qc.auto_promote_candidates(dry_run=False)
        first_quality = self._reload_by_id()["cand-mid"]["quality"]

        qc.auto_promote_candidates(dry_run=False)
        second_quality = self._reload_by_id()["cand-mid"]["quality"]

        self.assertEqual(first_quality["score"], second_quality["score"])
        self.assertEqual(first_quality["components"], second_quality["components"])
        # The second run definitely minted fresh (higher) ticks elsewhere in
        # the store — stamp_quality() must not consume one for THIS
        # candidate since its components are unchanged.
        self.assertEqual(first_quality["computed_at"], second_quality["computed_at"])

    def test_resurfaced_park_rescores_after_profile_change_and_can_now_promote(self):
        self._write_store([{
            "id": "cand-mid", "status": "candidate", "priority": 0.95,
            "text": "Why do you always struggle with that decision?",
            "target_category": "A", "source_path": "answers/B2.md",
            "story_function": "turning_point",
            "created_at": "2026-08-01T00:00:00Z",
        }])
        qc.auto_promote_candidates(dry_run=False)
        parked = self._reload_by_id()["cand-mid"]
        self.assertEqual(parked["status"], "needs_review")

        # Owner-set profile change: turning_point now carries a 1.2x
        # multiplier — the resurfaceable park must re-score against it.
        qc._load_quality_profile_safely = lambda: {
            "active": True, "by_story_function": {"turning_point": {"multiplier": 1.2}},
        }
        result = qc.auto_promote_candidates(dry_run=False)
        self.assertIn("cand-mid", [p[0] for p in result["promoted"]])
        promoted = self._reload_by_id()["cand-mid"]
        self.assertEqual(promoted["status"], "auto_promoted")
        self.assertGreater(promoted["quality"]["score"], parked["quality"]["score"])
        # The stamp genuinely re-derived from the new multiplier, not a stale
        # copy — components differ even though `computed_at` has only
        # second-resolution and can collide within a fast test run.
        self.assertNotEqual(
            promoted["quality"]["components"]["story_function_multiplier"],
            parked["quality"]["components"]["story_function_multiplier"],
        )

    def test_dry_run_does_not_stamp_or_mutate(self):
        self._write_store([{
            "id": "cand-clean", "status": "candidate", "priority": 0.9,
            "text": CLEAN_TEXT, "target_category": "A", "source_path": "answers/B1.md",
            "created_at": "2026-08-01T00:00:00Z",
        }])
        result = qc.auto_promote_candidates(dry_run=True)
        self.assertIn("cand-clean", [p[0] for p in result["promoted"]])
        stored = self._reload_by_id()["cand-clean"]
        self.assertEqual(stored["status"], "candidate")  # untouched
        self.assertNotIn("quality", stored)  # dry-run never stamps

    def test_dry_run_printer_shows_unified_score_and_flags(self):
        # Contract: "The dry-run path must print the unified score + flags
        # per candidate."
        self._write_store([{
            "id": "cand-clean", "status": "candidate", "priority": 0.9,
            "text": CLEAN_TEXT, "target_category": "A", "source_path": "answers/B1.md",
            "created_at": "2026-08-01T00:00:00Z",
        }])
        result = qc.auto_promote_candidates(dry_run=True)
        cid, qid, score, flags = result["promoted"][0]
        self.assertEqual(cid, "cand-clean")
        self.assertEqual(flags, [])

        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            qc.cmd_auto_promote(argparse.Namespace(dry_run=True))
        output = buf.getvalue()
        self.assertIn("score 0.90", output)
        self.assertIn("no craft flags", output)


if __name__ == "__main__":
    unittest.main()
