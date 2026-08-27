#!/usr/bin/env python3
"""Lifehug — scannable maintenance summary (v86, issue #35).

The weekly/monthly Telegram message used to be the raw concatenated stdout of
every maintenance step — a wall of text. This module builds the short,
counts-first summary that replaces it. Counts are derived from STATE FILES
(classifications, candidates, queue, coverage, learning failures, focus
recommendations), never by parsing step output; the full raw report is
persisted separately under state/reports/ by the shell orchestrators.

CLI:
    python3 system/weekly_report.py --since 2026-07-05T09:00:00Z \
        [--kind weekly|monthly] [--report-path state/reports/weekly-....md] \
        [--doctor-file -]        # doctor output on stdin (or a path);
                                 # omitted → run the doctor checks in-process
"""

from __future__ import annotations

import argparse
import contextlib
import io
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

_SYSTEM_DIR = Path(__file__).resolve().parent
if str(_SYSTEM_DIR) not in sys.path:
    sys.path.insert(0, str(_SYSTEM_DIR))

from lifehug_core import (
    CLASSIFICATIONS_DIR,
    COVERAGE_FILE,
    FOCUS_RECS_FILE,
    QUESTION_CANDIDATES_FILE,
    QUESTION_QUEUE_FILE,
    read_json,
    read_learning_failures,
)

MAX_ERROR_CHARS = 90
MAX_DOCTOR_LINES = 6

_HEADERS = {
    "weekly": "📋 Lifehug Weekly",
    "monthly": "🔬 Lifehug Monthly Research",
}


def _parse_iso(raw: object) -> datetime | None:
    if not raw or not isinstance(raw, str):
        return None
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _one_line(text: str, limit: int = MAX_ERROR_CHARS) -> str:
    line = " ".join(str(text).split())
    return line if len(line) <= limit else line[: limit - 1] + "…"


def _failure_label(row: dict) -> str:
    """`answers/A1.md: Error ...` → `A1 — ...` (short, phone-sized).

    The recorded error is often the step's ENTIRE captured output, including
    retry noise — pick the single most informative line instead of squashing
    everything together."""
    error = str(row.get("error", ""))
    m = re.search(r"([\w-]+)\.md", error)
    subject = m.group(1).upper() if m else str(row.get("operation", "step"))
    lines = [line.strip() for line in error.splitlines() if line.strip()]
    marked = [line for line in lines if "Error" in line or "error:" in line.lower()]
    line = marked[0] if marked else (lines[0] if lines else "")
    reason = re.sub(r"^.*?Error:\s*", "", line)
    reason = re.sub(r"AI classification failed for \S+:\s*", "", reason)
    return f"{subject} — {_one_line(reason or line)}"


def classification_section(since: datetime) -> list[str]:
    import classify_story  # noqa: PLC0415

    classified = 0
    for _path, data in classify_story.current_classification_files(CLASSIFICATIONS_DIR):
        at = _parse_iso(data.get("classified_at"))
        if at and at >= since:
            classified += 1
    # v237: a stale classification is withheld from every reader, so counting
    # it as a week's success would report work the product cannot use. It is
    # named separately instead — the number the owner reads names the hole.
    stale = len(classify_story.stale_classification_files(CLASSIFICATIONS_DIR))
    failures = [
        row for row in read_learning_failures(limit=50, since_days=None)
        if "classify" in str(row.get("operation", ""))
        and (_parse_iso(row.get("recorded_at")) or since) >= since
    ]
    if not classified and not failures and not stale:
        return []
    line = f"Classification: {classified} ✅"
    if stale:
        line += f" {stale} stale (reclassification pending)"
    if failures:
        line += f" {len(failures)} ❌"
    lines = [line]
    lines.extend(f"  ✗ {_failure_label(row)}" for row in failures[:5])
    return lines


def candidates_section(since: datetime) -> list[str]:
    data = read_json(QUESTION_CANDIDATES_FILE, default={}) or {}
    cands = data.get("candidates", [])
    if not cands:
        return []
    new = sum(1 for c in cands
              if (_parse_iso(c.get("created_at")) or datetime.min.replace(tzinfo=timezone.utc)) >= since)
    promoted = sum(1 for c in cands
                   if c.get("status") in ("promoted", "auto_promoted")
                   and (_parse_iso(c.get("promoted_at") or c.get("updated_at"))
                        or datetime.min.replace(tzinfo=timezone.utc)) >= since)
    backlog = sum(1 for c in cands
                  if c.get("status") in ("candidate", "needs_review", "accepted", "deferred"))
    bits = []
    if new:
        bits.append(f"{new} new")
    if promoted:
        bits.append(f"{promoted} promoted")
    bits.append(f"backlog {backlog}")
    return [f"Candidates: {' · '.join(bits)}"]


def queue_section() -> list[str]:
    queue = read_json(QUESTION_QUEUE_FILE, default={}) or {}
    items = queue.get("queue", [])
    if not items:
        return []
    expires = str(queue.get("expires_at", ""))[:10]
    suffix = f" through {expires}" if expires else ""
    return [f"Queue: {len(items)} questions{suffix}"]


def coverage_section() -> list[str]:
    cov = (read_json(COVERAGE_FILE, default={}) or {}).get("categories", {})
    if not cov:
        return []
    total = sum(c.get("total", 0) for c in cov.values())
    answered = sum(c.get("answered", 0) for c in cov.values())
    greens = sum(1 for c in cov.values() if c.get("status") == "green")
    return [f"Coverage: {answered}/{total} answered · {greens} GREEN"]


def other_failures_section(since: datetime) -> list[str]:
    rows = [
        row for row in read_learning_failures(limit=50, since_days=None)
        if "classify" not in str(row.get("operation", ""))
        and (_parse_iso(row.get("recorded_at")) or since) >= since
    ]
    if not rows:
        return []
    lines = [f"Failures: {len(rows)} (details in state/learning_failures.jsonl)"]
    lines.extend(f"  ✗ {row.get('operation', '?')} — {_one_line(str(row.get('error', '')))}"
                 for row in rows[:3])
    return lines


def focus_recs_section() -> list[str]:
    recs = (read_json(FOCUS_RECS_FILE, default={}) or {}).get("recommendations", [])
    pending = [r for r in recs if r.get("status", "pending") == "pending"]
    if not pending:
        return []
    top = ", ".join(str(r.get("entity", "?")) for r in pending[:3])
    return [f"Focus recs: {len(pending)} pending — {top}",
            "  approve: lifehug.py recommend-focuses --approve <rec-id>"]


def doctor_section(doctor_text: str | None) -> list[str]:
    if doctor_text is None:
        doctor_text = _run_doctor()
    warnings = [line.strip() for line in doctor_text.splitlines()
                if line.strip().startswith(("warn:", "fail:"))]
    if not warnings:
        return ["Doctor: ✅ all checks ok"]
    lines = [f"Doctor: ⚠️ {len(warnings)} warning(s)"]
    lines.extend(f"  {_one_line(w, 100)}" for w in warnings[:MAX_DOCTOR_LINES])
    if len(warnings) > MAX_DOCTOR_LINES:
        lines.append(f"  … {len(warnings) - MAX_DOCTOR_LINES} more")
    return lines


def _run_doctor() -> str:
    """In-process doctor for standalone runs; the weekly cron pipes its own."""
    try:
        import lifehug  # noqa: PLC0415
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            lifehug.loop_health_checks()
        return buf.getvalue()
    except Exception as exc:  # noqa: BLE001
        return f"warn: doctor checks unavailable ({exc})"


def build_summary(since: datetime, *, kind: str = "weekly",
                  doctor_text: str | None = None,
                  report_path: str | None = None) -> str:
    header = f"{_HEADERS.get(kind, _HEADERS['weekly'])} — {datetime.now(timezone.utc).strftime('%b %-d')}"
    body: list[str] = []
    body.extend(classification_section(since))
    body.extend(candidates_section(since))
    body.extend(queue_section())
    body.extend(coverage_section())
    body.extend(other_failures_section(since))
    body.extend(focus_recs_section())
    body.extend(doctor_section(doctor_text))
    parts = [header, ""]
    parts.extend(body)
    if report_path:
        parts.extend(["", f"📄 Full report: {report_path}"])
    return "\n".join(parts)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build the scannable maintenance summary")
    parser.add_argument("--since", required=True,
                        help="ISO timestamp — count activity at/after this moment")
    parser.add_argument("--kind", choices=("weekly", "monthly"), default="weekly")
    parser.add_argument("--report-path", default=None,
                        help="Path of the persisted full report, shown as a pointer")
    parser.add_argument("--doctor-file", default=None,
                        help="File with doctor output ('-' = stdin); omitted → run checks in-process")
    args = parser.parse_args(argv)

    since = _parse_iso(args.since)
    if since is None:
        print(f"Error: --since is not a valid ISO timestamp: {args.since}", file=sys.stderr)
        return 1

    doctor_text: str | None = None
    if args.doctor_file == "-":
        doctor_text = sys.stdin.read()
    elif args.doctor_file:
        try:
            doctor_text = Path(args.doctor_file).read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            doctor_text = f"warn: doctor output unreadable ({exc})"

    print(build_summary(since, kind=args.kind, doctor_text=doctor_text,
                        report_path=args.report_path))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
