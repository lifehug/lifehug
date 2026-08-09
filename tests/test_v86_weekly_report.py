"""v86 — scannable maintenance summary (issue #35).

The weekly/monthly Telegram message is now a short counts-first summary built
from state files; the full raw report is persisted under state/reports/.
These tests pin the summary builder's sections against fixture state, and the
shell orchestrators' contract (no more raw ${*_OUT} interpolation into the
Telegram send; report file written).
"""

import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

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


wr = load("weekly_report")
vault_paths = load("vault_paths")

NOW = datetime.now(timezone.utc)
SINCE = NOW - timedelta(hours=2)
FRESH = NOW.strftime("%Y-%m-%dT%H:%M:%SZ")
STALE = (NOW - timedelta(days=30)).strftime("%Y-%m-%dT%H:%M:%SZ")


class SummaryFixture(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: __import__("shutil").rmtree(self.tmp, ignore_errors=True))
        clf = self.tmp / "classifications"
        clf.mkdir()
        (clf / "a.json").write_text(json.dumps({"classified_at": FRESH}))
        (clf / "b.json").write_text(json.dumps({"classified_at": FRESH}))
        (clf / "old.json").write_text(json.dumps({"classified_at": STALE}))
        (self.tmp / "cands.json").write_text(json.dumps({"candidates": [
            {"status": "candidate", "created_at": FRESH},
            {"status": "candidate", "created_at": FRESH},
            {"status": "auto_promoted", "created_at": STALE, "promoted_at": FRESH},
            {"status": "needs_review", "created_at": STALE},
            {"status": "rejected", "created_at": STALE},
        ]}))
        (self.tmp / "queue.json").write_text(json.dumps({
            "expires_at": "2026-07-12T09:00:00Z",
            "queue": [{"question_id": f"A{i}"} for i in range(8)],
        }))
        (self.tmp / "coverage.json").write_text(json.dumps({"categories": {
            "A": {"total": 10, "answered": 9, "status": "green"},
            "B": {"total": 10, "answered": 2, "status": "red"},
        }}))
        (self.tmp / "recs.json").write_text(json.dumps({"recommendations": [
            {"entity": "AJ", "score": 12, "status": "pending"},
            {"entity": "Mesa", "score": 8, "status": "dismissed"},
        ]}))
        self.failures = [
            {"recorded_at": FRESH, "component": "weekly_maintenance",
             "operation": "classify_story",
             "error": "Error: AI classification failed for answers/C16.md: timed out after 600s"},
            {"recorded_at": FRESH, "component": "weekly_maintenance",
             "operation": "planner_queue", "error": "boom " * 100},
            {"recorded_at": STALE, "component": "weekly_maintenance",
             "operation": "classify_story", "error": "ancient failure, out of window"},
        ]
        patches = [
            mock.patch.object(wr, "CLASSIFICATIONS_DIR", clf),
            mock.patch.object(wr, "QUESTION_CANDIDATES_FILE", self.tmp / "cands.json"),
            mock.patch.object(wr, "QUESTION_QUEUE_FILE", self.tmp / "queue.json"),
            mock.patch.object(wr, "COVERAGE_FILE", self.tmp / "coverage.json"),
            mock.patch.object(wr, "FOCUS_RECS_FILE", self.tmp / "recs.json"),
            mock.patch.object(wr, "read_learning_failures",
                              lambda **kw: list(self.failures)),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)


class SummaryContentTests(SummaryFixture):
    def test_counts_first_summary(self):
        text = wr.build_summary(SINCE, doctor_text="warn: candidate backlog age 45d\nok: fine",
                                report_path="state/reports/weekly-2026-07-06.md")
        self.assertIn("Classification: 2 ✅ 1 ❌", text)
        self.assertIn("C16 — timed out after 600s", text)          # one-line error
        self.assertNotIn("Traceback", text)
        self.assertIn("Candidates: 2 new · 1 promoted · backlog 3", text)
        self.assertIn("Queue: 8 questions through 2026-07-12", text)
        self.assertIn("Coverage: 11/20 answered · 1 GREEN", text)
        self.assertIn("Failures: 1", text)                          # non-classify failure
        self.assertIn("Focus recs: 1 pending — AJ", text)
        self.assertIn("Doctor: ⚠️ 1 warning(s)", text)
        self.assertIn("warn: candidate backlog age 45d", text)
        self.assertIn("📄 Full report: state/reports/weekly-2026-07-06.md", text)
        # Old classification/failure outside the window is excluded.
        self.assertNotIn("ancient failure", text)

    def test_multiline_retry_noise_reduces_to_one_reason(self):
        self.failures.insert(0, {
            "recorded_at": FRESH, "component": "weekly_maintenance",
            "operation": "classify_story",
            "error": ("Classifying 5 source file(s)...\n[1/5] answers/G5C.md\n"
                      "Error: AI classification failed for answers/G5C.md: timed out\n"
                      "Error: timed out\nError: timed out\nretrying (2/3)..."),
        })
        text = wr.build_summary(SINCE, doctor_text="")
        self.assertIn("✗ G5C — timed out", text)
        self.assertNotIn("timed out Error: timed out", text)

    def test_errors_are_truncated_to_one_line(self):
        text = wr.build_summary(SINCE, doctor_text="")
        for line in text.splitlines():
            self.assertLessEqual(len(line), 120)

    def test_fits_in_one_telegram_chunk(self):
        text = wr.build_summary(SINCE, doctor_text="warn: x\n" * 40)
        self.assertLess(len(text), 4096)

    def test_doctor_ok_path(self):
        text = wr.build_summary(SINCE, doctor_text="ok: planner queue valid\n")
        self.assertIn("Doctor: ✅ all checks ok", text)

    def test_monthly_header(self):
        text = wr.build_summary(SINCE, kind="monthly", doctor_text="")
        self.assertIn("🔬 Lifehug Monthly Research —", text)


class EmptyStateTests(unittest.TestCase):
    def test_sections_omitted_when_empty(self):
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: __import__("shutil").rmtree(tmp, ignore_errors=True))
        with mock.patch.object(wr, "CLASSIFICATIONS_DIR", tmp / "clf"), \
                mock.patch.object(wr, "QUESTION_CANDIDATES_FILE", tmp / "c.json"), \
                mock.patch.object(wr, "QUESTION_QUEUE_FILE", tmp / "q.json"), \
                mock.patch.object(wr, "COVERAGE_FILE", tmp / "cov.json"), \
                mock.patch.object(wr, "FOCUS_RECS_FILE", tmp / "r.json"), \
                mock.patch.object(wr, "read_learning_failures", lambda **kw: []):
            text = wr.build_summary(SINCE, doctor_text="")
        self.assertNotIn("Classification:", text)
        self.assertNotIn("Candidates:", text)
        self.assertNotIn("Queue:", text)
        self.assertNotIn("Focus recs:", text)
        self.assertIn("Doctor: ✅ all checks ok", text)


class OrchestratorContractTests(unittest.TestCase):
    """The shell scripts must send the summary, not the raw step output."""

    def setUp(self):
        self.weekly = (SYSTEM / "weekly_maintenance.sh").read_text(encoding="utf-8")
        self.monthly = (SYSTEM / "monthly_research.sh").read_text(encoding="utf-8")

    def _notify_blocks(self, text):
        return text[text.index("telegram_notify \""):]

    def test_weekly_no_raw_dump_in_notify(self):
        tail = self._notify_blocks(self.weekly)
        for var in ("CLASSIFY_OUT", "PROMOTE_OUT", "QUEUE_OUT", "PROGRESS_OUT"):
            self.assertNotIn("${" + var + "}", tail)
        self.assertIn("${SUMMARY}", tail)

    def test_weekly_persists_report_and_calls_summary(self):
        # v120 (vault-only): the script no longer hardcodes `state/reports` —
        # it asks the vault contract where the reports directory lives, so the
        # contract is what pins the location and the script is checked against
        # it rather than against a literal that can silently drift.
        self.assertEqual(
            vault_paths.VAULT_DATA_PATHS["reports"]["external_path"], "state/reports")
        self.assertIn('vault_paths.py" data-path reports', self.weekly)
        self.assertIn('REPORT_FILE="$REPORT_DIR/weekly-$(date +%F).md"', self.weekly)
        self.assertIn('} > "$REPORT_FILE"', self.weekly)  # the full report is written
        self.assertIn("weekly-summary", self.weekly)
        self.assertIn('--report-path "$REPORT_FILE"', self.weekly)
        self.assertIn("--doctor-file -", self.weekly)

    def test_monthly_no_raw_dump_in_notify(self):
        tail = self._notify_blocks(self.monthly)
        for var in ("RESEARCH_OUT", "FOCUSES_OUT", "ROSTER_OUT"):
            self.assertNotIn("${" + var + "}", tail)
        self.assertIn("${SUMMARY}", tail)

    def test_scripts_are_valid_bash(self):
        for name in ("weekly_maintenance.sh", "monthly_research.sh"):
            result = subprocess.run(["bash", "-n", str(SYSTEM / name)],
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
