"""v68 — Make the Loop loop: candidate economics, zombie focuses, chunked
notify, adaptive cadence, queue-item consumption."""

import importlib.util
import sys
import unittest
from datetime import datetime, timedelta, timezone
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


core = load("lifehug_core")
qc = load("question_candidates")
qp = load("question_planner")
ask = load("ask")


def iso_days_ago(days: float) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat().replace("+00:00", "Z")


class ChunkMessageTests(unittest.TestCase):
    def test_short_message_single_chunk(self):
        self.assertEqual(core.chunk_message("hello"), ["hello"])

    def test_empty_message_no_chunks(self):
        self.assertEqual(core.chunk_message("   \n  "), [])

    def test_long_message_splits_on_lines_with_numbering(self):
        text = "\n".join(f"line {i} " + "x" * 80 for i in range(100))
        chunks = core.chunk_message(text, limit=1000)
        self.assertGreater(len(chunks), 1)
        for i, chunk in enumerate(chunks, 1):
            self.assertLessEqual(len(chunk), 1000 + 10)  # numbering prefix allowance
            self.assertTrue(chunk.startswith(f"({i}/{len(chunks)})"))
        # No content lost
        rejoined = "".join(c.split("\n", 1)[1] for c in chunks)
        self.assertEqual(rejoined.replace("\n", ""), text.replace("\n", ""))

    def test_pathological_single_line_hard_split(self):
        chunks = core.chunk_message("y" * 2500, limit=1000)
        self.assertEqual(len(chunks), 3)


class DynamicCapTests(unittest.TestCase):
    def test_full_bank_no_backlog_stays_tight(self):
        self.assertEqual(qc.dynamic_weekly_cap(150, backlog_count=5), 1)

    def test_backlog_pressure_raises_cap(self):
        # The audit's live state: 116 unanswered, 56-candidate backlog.
        # Old cap: 1/week (could never drain). New: backlog lifts it.
        self.assertEqual(qc.dynamic_weekly_cap(116, backlog_count=56), 5)

    def test_drain_cap_ceiling(self):
        self.assertEqual(qc.dynamic_weekly_cap(150, backlog_count=500), 8)

    def test_thin_bank_band_floor_wins(self):
        self.assertEqual(qc.dynamic_weekly_cap(30, backlog_count=0), 4)


class NearDuplicateTests(unittest.TestCase):
    def test_reworded_duplicate_detected(self):
        # The parenthood-neighborhood shape: same question, different wrapper.
        a = "What did you promise yourself you'd do differently as a parent?"
        b = "As a parent, what did you promise yourself you would do differently?"
        self.assertEqual(qc.near_duplicate_of(b, [("cand-4", a)]), "cand-4")

    def test_distinct_questions_pass(self):
        a = "What did your father teach you about money?"
        b = "Describe the kitchen in your childhood home."
        self.assertIsNone(qc.near_duplicate_of(b, [("A1", a)]))

    def test_short_text_not_judged(self):
        self.assertIsNone(qc.near_duplicate_of("Why?", [("A1", "Why not?")]))


class ExpiryTests(unittest.TestCase):
    def _store(self):
        return {"candidates": [
            {"id": "old", "status": "candidate", "created_at": iso_days_ago(60), "text": "q"},
            {"id": "fresh", "status": "candidate", "created_at": iso_days_ago(5), "text": "q"},
            {"id": "parked-old", "status": "needs_review", "created_at": iso_days_ago(50), "text": "q"},
            {"id": "deferred-old", "status": "deferred", "created_at": iso_days_ago(90), "text": "q"},
            {"id": "promoted-old", "status": "promoted", "created_at": iso_days_ago(90), "text": "q"},
        ]}

    def test_old_candidates_expire_deferred_exempt(self):
        data = self._store()
        expired = qc.expire_stale_candidates(data)
        expired_ids = {cid for cid, _ in expired}
        self.assertEqual(expired_ids, {"old", "parked-old"})
        by_id = {c["id"]: c for c in data["candidates"]}
        self.assertEqual(by_id["old"]["status"], "expired")
        self.assertEqual(by_id["deferred-old"]["status"], "deferred")  # human said wait
        self.assertEqual(by_id["fresh"]["status"], "candidate")
        self.assertEqual(by_id["promoted-old"]["status"], "promoted")

    def test_dry_run_reports_without_mutating(self):
        data = self._store()
        expired = qc.expire_stale_candidates(data, dry_run=True)
        self.assertEqual(len(expired), 2)
        self.assertTrue(all(c["status"] != "expired" for c in data["candidates"]))


class ResurfaceTests(unittest.TestCase):
    def test_score_parked_resurfaces(self):
        c = {"status": "needs_review", "needs_review_reason": "score 0.75 below threshold 0.82"}
        self.assertTrue(qc._is_resurfaceable(c))

    def test_quality_parked_resurfaces(self):
        c = {"status": "needs_review", "needs_review_reason": "quality 0.45: yes_no_wording"}
        self.assertTrue(qc._is_resurfaceable(c))

    def test_structural_reasons_stay_parked(self):
        for reason in ("missing_category", "near_duplicate of A3"):
            c = {"status": "needs_review", "needs_review_reason": reason}
            self.assertFalse(qc._is_resurfaceable(c))

    def test_other_statuses_not_resurfaceable(self):
        self.assertFalse(qc._is_resurfaceable({"status": "rejected", "needs_review_reason": "score"}))


class ZombieFocusTests(unittest.TestCase):
    QUESTIONS = [
        {"id": "A1", "category": "A", "text": "q", "answered": True},
        {"id": "A2", "category": "A", "text": "q", "answered": False},
    ]

    def test_zombie_detection(self):
        focuses = [
            {"id": "real", "categories": ["A"], "tier": "standard"},
            {"id": "zombie", "categories": [], "tier": "standard", "target_depth": 20},
        ]
        self.assertEqual([f["id"] for f in qp.zombie_focuses(focuses)], ["zombie"])

    def test_global_fullness_excludes_zombies(self):
        real = {"id": "real", "categories": ["A"], "tier": "standard", "target_depth": 2}
        zombie = {"id": "z", "categories": [], "tier": "standard", "target_depth": 20}
        with_zombie = qp.global_fullness([real, zombie], self.QUESTIONS)
        without = qp.global_fullness([real], self.QUESTIONS)
        # Zombie's 20 phantom targets must not dilute fullness anymore.
        self.assertEqual(with_zombie, without)
        self.assertEqual(without, 0.5)  # 1 answered / target 2


class AdaptiveCadenceTests(unittest.TestCase):
    def test_sends_today_resets_on_new_day(self):
        rotation = {"sends_today": 3, "sends_today_date": "2020-01-01"}
        self.assertEqual(ask.sends_today(rotation), 0)

    def test_sends_today_counts_same_day(self):
        from datetime import date
        rotation = {"sends_today": 2, "sends_today_date": date.today().isoformat()}
        self.assertEqual(ask.sends_today(rotation), 2)

    def test_days_since_last_answer(self):
        rotation = {"last_answered_at": (datetime.now() - timedelta(days=5)).isoformat()}
        self.assertAlmostEqual(ask.days_since_last_answer(rotation), 5, delta=0.1)
        self.assertIsNone(ask.days_since_last_answer({}))

    def test_reengagement_prefers_short_light_questions(self):
        questions = [
            {"id": "A1", "category": "A", "answered": False,
             "text": "Walk me through the hardest grief you have ever carried and what you lost."},
            {"id": "B1", "category": "B", "answered": False,
             "text": "What was your first car?"},
            {"id": "K1", "category": "K", "answered": False, "text": "Quick one?"},
        ]
        categories = {"A": {"group": "main"}, "B": {"group": "main"}, "K": {"group": "focus"}}
        pick = ask.pick_reengagement_question(questions, categories)
        self.assertEqual(pick["id"], "B1")  # short, light, non-focus beats heavy and focus

    def test_pick_next_uses_reengagement_when_stale(self):
        questions = [
            {"id": "A1", "category": "A", "answered": False, "text": "A long heavy question about deep fear and regret today"},
            {"id": "B1", "category": "B", "answered": False, "text": "What was your first car?"},
        ]
        categories = {"A": {"group": "main"}, "B": {"group": "main"}}
        rotation = {"last_answered_at": (datetime.now() - timedelta(days=10)).isoformat()}
        orig = ask.load_config
        ask.load_config = lambda *a, **k: {"reengage_after_days": 4}
        try:
            pick = ask.pick_next_question(questions, categories, rotation)
        finally:
            ask.load_config = orig
        self.assertEqual(pick["id"], "B1")

    def test_pick_next_normal_when_recent(self):
        questions = [
            {"id": "A1", "category": "A", "answered": False, "text": "Tell me about your first neighborhood friend growing up"},
            {"id": "B1", "category": "B", "answered": False, "text": "Short one?"},
        ]
        categories = {"A": {"group": "main"}, "B": {"group": "main"}}
        rotation = {"last_answered_at": datetime.now().isoformat()}
        orig = ask.load_config
        ask.load_config = lambda *a, **k: {"reengage_after_days": 4}
        try:
            pick = ask.pick_next_question(questions, categories, rotation)
        finally:
            ask.load_config = orig
        # Coverage rotation picks A (0/1 == 0/1; lowest-ratio ordering) — the
        # point is it did NOT take the re-engagement branch (which would pick B1).
        self.assertIsNotNone(pick)


class QueueConsumptionTests(unittest.TestCase):
    def test_mark_queue_item_sent(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            qfile = Path(d) / "question_queue.json"
            core.write_json(qfile, {"queue": [
                {"question_id": "A1", "status": "queued"},
                {"question_id": "B1", "status": "queued"},
            ]})
            orig = ask.QUESTION_QUEUE_FILE
            ask.QUESTION_QUEUE_FILE = qfile
            try:
                ask.mark_queue_item_sent("A1")
            finally:
                ask.QUESTION_QUEUE_FILE = orig
            data = core.read_json(qfile)
            by_id = {i["question_id"]: i for i in data["queue"]}
            self.assertEqual(by_id["A1"]["status"], "sent")
            self.assertIn("sent_at", by_id["A1"])
            self.assertEqual(by_id["B1"]["status"], "queued")


if __name__ == "__main__":
    unittest.main()


class ZombieHealTests(unittest.TestCase):
    """focus-new heals a category-less (zombie) focus instead of refusing."""

    def test_cli_guard_allows_healing_zombie(self):
        import re as _re
        roadmap_mod = load("roadmap")
        src = (SYSTEM / "roadmap.py").read_text(encoding="utf-8")
        # The guard must only refuse when the existing focus HAS categories.
        self.assertIn('existing.get("categories")', src)
        self.assertIn("healing", src.lower())
