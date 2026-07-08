#!/usr/bin/env python3
"""Script-first Lifehug workflow wrapper.

This is a thin dispatcher over the canonical scripts in system/. It exists so
humans, skills, and cron jobs can share one stable entrypoint without copying
workflow logic.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

from lifehug_core import (
    ANSWERS_DIR,
    CONFIG_FILE,
    COVERAGE_FILE,
    QUESTIONS_FILE,
    REPO_DIR,
    ROTATION_FILE,
    STATE_DIR,
    WIKI_DIR,
    format_learning_failure,
    load_config,
    parse_categories,
    parse_questions,
    read_json,
    read_learning_failures,
    send_telegram,
)
from question_candidates import VALID_STATUSES
from question_planner import DEFAULT_DELIVERY_QUEUE_LIMIT
from recommend_focuses import FOCUS_RECOMMENDATION_TYPES
from research_expand import VALID_OUTPUT_TYPES, VALID_TOPIC_TYPES

SYSTEM_DIR = Path(__file__).resolve().parent
CANDIDATE_STATUS_CHOICES = sorted(VALID_STATUSES)


def script(name: str) -> Path:
    return SYSTEM_DIR / name


def run(args: list[str], *, env: dict[str, str] | None = None) -> int:
    return subprocess.run(args, cwd=REPO_DIR, env=env).returncode


def run_python(script_name: str, args: list[str]) -> int:
    return run([sys.executable, str(script(script_name)), *args])


def has_telegram_target(config: dict[str, str]) -> bool:
    return bool(
        os.environ.get("TELEGRAM_CHAT_ID")
        or config.get("telegram_chat_id")
        or config.get("group_chat_id")
    )


def has_telegram_token() -> bool:
    if os.environ.get("TELEGRAM_BOT_TOKEN"):
        return True
    openclaw = Path.home() / ".openclaw" / "openclaw.json"
    return openclaw.exists()


def git_dirty() -> bool | None:
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=REPO_DIR,
            check=True,
            capture_output=True,
            text=True,
        )
    except (FileNotFoundError, subprocess.CalledProcessError):
        return None
    return bool(result.stdout.strip())


def check(label: str, ok: bool, detail: str = "") -> bool:
    status = "ok" if ok else "fail"
    suffix = f" - {detail}" if detail else ""
    print(f"{status}: {label}{suffix}")
    return ok


def warn(label: str, detail: str = "") -> None:
    suffix = f" - {detail}" if detail else ""
    print(f"warn: {label}{suffix}")


def cmd_status(_args: argparse.Namespace) -> int:
    return run_python("ask.py", ["--status"])


def cmd_ai_status(_args: argparse.Namespace) -> int:
    from research_expand import ai_available  # noqa: PLC0415

    route = ai_available()
    if route:
        print(f"AI route: {route}")
        return 0
    print("keyless — agent mode required (see skills/maintenance)")
    return 1


def cmd_next(_args: argparse.Namespace) -> int:
    return run_python("ask.py", ["--dry-run"])


def cmd_compile(args: argparse.Namespace) -> int:
    flags = []
    if args.dry_run:
        flags.append("--dry-run")
    if args.no_ai:
        flags.append("--no-ai")
    if args.model:
        flags.extend(["--model", args.model])
    if getattr(args, "emit_tasks", None):
        flags.extend(["--emit-tasks", args.emit_tasks])
    return run_python("wiki_compile.py", flags)


def cmd_source_scan(args: argparse.Namespace) -> int:
    flags = ["scan"]
    if args.json:
        flags.append("--json")
    return run_python("source_integrity.py", flags)


def cmd_source_manifest(args: argparse.Namespace) -> int:
    flags = ["manifest"]
    if args.rebuild:
        flags.append("--rebuild")
    if args.json:
        flags.append("--json")
    return run_python("source_integrity.py", flags)


def cmd_source_lint(args: argparse.Namespace) -> int:
    flags = ["lint"]
    if args.fix:
        flags.append("--fix")
    if args.strict:
        flags.append("--strict")
    if args.json:
        flags.append("--json")
    if args.no_write_findings:
        flags.append("--no-write-findings")
    if args.limit is not None:
        flags.extend(["--limit", str(args.limit)])
    return run_python("source_integrity.py", flags)


def cmd_source_findings(args: argparse.Namespace) -> int:
    flags = ["findings"]
    if args.status:
        flags.extend(["--status", args.status])
    if args.json:
        flags.append("--json")
    if args.limit is not None:
        flags.extend(["--limit", str(args.limit)])
    return run_python("source_integrity.py", flags)


def cmd_correct_source(args: argparse.Namespace) -> int:
    flags = ["correct", args.target, "--kind", args.kind, "--source", args.source]
    if args.title:
        flags.extend(["--title", args.title])
    return run_python("source_integrity.py", flags)


def cmd_reflect_source(args: argparse.Namespace) -> int:
    flags = ["reflect", args.target, "--source", args.source]
    if args.title:
        flags.extend(["--title", args.title])
    return run_python("source_integrity.py", flags)


def cmd_ingest_story(args: argparse.Namespace) -> int:
    flags = ["--source", args.source]
    if args.title:
        flags.extend(["--title", args.title])
    if args.captured_at:
        flags.extend(["--captured-at", args.captured_at])
    if getattr(args, "witness", None):
        flags.extend(["--witness", args.witness])
    if getattr(args, "sensitivity", None):
        flags.extend(["--sensitivity", args.sensitivity])
    if getattr(args, "kind", None) and args.kind != "story":
        flags.extend(["--kind", args.kind])
    if args.no_candidates:
        flags.append("--no-candidates")
    if args.dry_run:
        flags.append("--dry-run")
    return run_python("ingest_story.py", flags)


def cmd_candidates_list(args: argparse.Namespace) -> int:
    flags = ["list", "--limit", str(args.limit)]
    if args.status:
        flags.extend(["--status", args.status])
    if args.kind:
        flags.extend(["--kind", args.kind])
    if args.source:
        flags.extend(["--source", args.source])
    if args.target_page:
        flags.extend(["--target-page", args.target_page])
    if args.min_priority is not None:
        flags.extend(["--min-priority", str(args.min_priority)])
    if args.detail:
        flags.append("--detail")
    if args.json:
        flags.append("--json")
    return run_python("question_candidates.py", flags)


def cmd_candidates_review(args: argparse.Namespace) -> int:
    flags = ["review", "--limit", str(args.limit)]
    if args.status:
        flags.extend(["--status", args.status])
    if args.kind:
        flags.extend(["--kind", args.kind])
    if args.source:
        flags.extend(["--source", args.source])
    if args.target_page:
        flags.extend(["--target-page", args.target_page])
    if args.min_priority is not None:
        flags.extend(["--min-priority", str(args.min_priority)])
    return run_python("question_candidates.py", flags)


def cmd_candidates_update(args: argparse.Namespace) -> int:
    flags = ["update", args.candidate_id]
    if args.status:
        flags.extend(["--status", args.status])
    if args.target_page is not None:
        flags.extend(["--target-page", args.target_page])
    if args.target_category is not None:
        flags.extend(["--target-category", args.target_category])
    if args.priority is not None:
        flags.extend(["--priority", str(args.priority)])
    if args.reason is not None:
        flags.extend(["--reason", args.reason])
    return run_python("question_candidates.py", flags)


def cmd_candidates_promote(args: argparse.Namespace) -> int:
    return run_python("question_candidates.py", ["promote", args.candidate_id, "--category", args.category])


def cmd_candidates_promote_neighborhood(args: argparse.Namespace) -> int:
    return run_python("question_candidates.py",
                      ["promote-neighborhood", "--neighborhood", args.neighborhood, "--category", args.category])


def cmd_planner_report(args: argparse.Namespace) -> int:
    flags = ["--report", "--limit", str(args.limit)]
    return run_python("question_planner.py", flags)


def cmd_planner_queue(args: argparse.Namespace) -> int:
    flags = [
        "--write-queue",
        "--limit",
        str(args.limit),
        "--arc-max",
        str(args.arc_max),
        "--expires-days",
        str(args.expires_days),
    ]
    return run_python("question_planner.py", flags)


def cmd_planner_clear(_args: argparse.Namespace) -> int:
    return run_python("question_planner.py", ["--clear-queue"])


def cmd_planner_state(args: argparse.Namespace) -> int:
    flags = ["--state"]
    if args.init:
        flags.append("--init-state")
    return run_python("question_planner.py", flags)


def cmd_planner_objective_add(args: argparse.Namespace) -> int:
    flags = ["--objective-add", args.label]
    for category in args.category or []:
        flags.extend(["--objective-category", category])
    for keyword in args.keyword or []:
        flags.extend(["--objective-keyword", keyword])
    if args.max_questions is not None:
        flags.extend(["--objective-max-questions", str(args.max_questions)])
    return run_python("question_planner.py", flags)


def cmd_planner_objective_clear(_args: argparse.Namespace) -> int:
    return run_python("question_planner.py", ["--objective-clear"])


def cmd_progress(_args: argparse.Namespace) -> int:
    return run_python("progress.py", [])


def cmd_book_status(_args: argparse.Namespace) -> int:
    import book  # noqa: PLC0415
    return book.print_book_status()


def cmd_book_chapter(args: argparse.Namespace) -> int:
    import book  # noqa: PLC0415
    return book.print_book_chapter(args.book, args.chapter)


def cmd_book_offers(args: argparse.Namespace) -> int:
    import book  # noqa: PLC0415
    return book.print_book_offers(dry_run=not args.send)


def cmd_quality_stats(_args: argparse.Namespace) -> int:
    return run_python("quality_profile.py", ["--show"])


def cmd_quality_update(_args: argparse.Namespace) -> int:
    return run_python("quality_profile.py", ["--update"])


def cmd_second_voice_ack(args: argparse.Namespace) -> int:
    from question_planner import acknowledge_second_voice_offer  # noqa: PLC0415
    if acknowledge_second_voice_offer(args.key):
        print(f"✓ Acknowledged second-voice offer: {args.key}")
        return 0
    print(f"No pending offer with key: {args.key}", file=sys.stderr)
    return 1


def cmd_mirror_compile(args: argparse.Namespace) -> int:
    flags: list[str] = []
    if getattr(args, "model", None):
        flags.extend(["--model", args.model])
    if getattr(args, "dry_run", False):
        flags.append("--dry-run")
    if getattr(args, "emit_task", None):
        flags.extend(["--emit-task", args.emit_task])
    if getattr(args, "from_response", None):
        flags.extend(["--from-response", args.from_response])
    return run_python("mirror.py", flags)


def cmd_artifact(args: argparse.Namespace) -> int:
    artifact_args = ["--help"] if getattr(args, "artifact_help", False) else (args.artifact_args or ["--help"])
    return run_python("artifact.py", artifact_args)


def cmd_roadmap(_args: argparse.Namespace) -> int:
    return run_python("roadmap.py", ["show"])


def cmd_roadmap_rebuild(_args: argparse.Namespace) -> int:
    return run_python("roadmap.py", ["rebuild"])


def cmd_focus_add(args: argparse.Namespace) -> int:
    flags = ["add", args.label, "--type", args.type, "--tier", args.tier,
             "--deliverable", args.deliverable]
    if args.objective:
        flags.extend(["--objective", args.objective])
    if args.target is not None:
        flags.extend(["--target", str(args.target)])
    for c in args.category or []:
        flags.extend(["--category", c])
    return run_python("roadmap.py", flags)


def cmd_focus_set(args: argparse.Namespace) -> int:
    flags = ["set", args.focus_id]
    for name in ("tier", "phase", "objective", "deliverable"):
        val = getattr(args, name)
        if val is not None:
            flags.extend([f"--{name}", val])
    if args.target is not None:
        flags.extend(["--target", str(args.target)])
    if args.cap is not None:
        flags.extend(["--cap", str(args.cap)])
    for c in args.category or []:
        flags.extend(["--category", c])
    return run_python("roadmap.py", flags)


def cmd_focus_finish(args: argparse.Namespace) -> int:
    return run_python("roadmap.py", ["finish", args.focus_id])


def cmd_focus_new(args: argparse.Namespace) -> int:
    flags = ["new", args.label, "--type", args.type, "--tier", args.tier,
             "--deliverable", args.deliverable]
    if args.objective:
        flags.extend(["--objective", args.objective])
    if args.no_generate:
        flags.append("--no-generate")
    return run_python("roadmap.py", flags)


def cmd_serve(args: argparse.Namespace) -> int:
    return run_python("serve_wiki.py", ["--host", args.host, "--port", str(args.port)])


def cmd_rebuild(_args: argparse.Namespace) -> int:
    return run_python("rebuild_state.py", ["--fix-rotation", "--readme"])


def cmd_process_answer(args: argparse.Namespace) -> int:
    flags: list[str] = []
    if args.source:
        flags.extend(["--source", args.source])
    if args.answered_date:
        flags.extend(["--answered-date", args.answered_date])
    if args.asked_date:
        flags.extend(["--asked-date", args.asked_date])
    if args.force:
        flags.append("--force")
    if args.commit:
        flags.append("--commit")
    if args.push:
        flags.append("--push")
    if args.no_compile_wiki:
        flags.append("--no-compile-wiki")
    if getattr(args, "sensitivity", None):
        flags.extend(["--sensitivity", args.sensitivity])
    if args.summary:
        flags.extend(["--summary", args.summary])
    for followup in args.followup or []:
        flags.extend(["--followup", followup])
    question_id = [] if args.question_id is None else [args.question_id]
    return run_python("process_answer.py", [*question_id, *flags])


def cmd_daily_dry_run(_args: argparse.Namespace) -> int:
    env = os.environ.copy()
    env["LIFEHUG_DAILY_DRY_RUN"] = "1"
    return run(["bash", str(script("daily_question.sh"))], env=env)


def cmd_weekly_maintenance(args: argparse.Namespace) -> int:
    env = os.environ.copy()
    if args.dry_run:
        env["LIFEHUG_WEEKLY_DRY_RUN"] = "1"
    return run(["bash", str(script("weekly_maintenance.sh"))], env=env)


def cmd_weekly_summary(args: argparse.Namespace) -> int:
    cmd = [sys.executable, str(script("weekly_report.py")), "--since", args.since,
           "--kind", args.kind]
    if args.report_path:
        cmd += ["--report-path", args.report_path]
    if args.doctor_file:
        cmd += ["--doctor-file", args.doctor_file]
    return run(cmd)


def cmd_monthly_research(args: argparse.Namespace) -> int:
    env = os.environ.copy()
    if args.dry_run:
        env["LIFEHUG_MONTHLY_DRY_RUN"] = "1"
    if args.gap_limit is not None:
        env["LIFEHUG_MONTHLY_GAP_LIMIT"] = str(args.gap_limit)
    if args.self_topic:
        env["LIFEHUG_MONTHLY_SELF_TOPIC"] = args.self_topic
    if args.focus_min_score is not None:
        env["LIFEHUG_MONTHLY_FOCUS_MIN_SCORE"] = str(args.focus_min_score)
    return run(["bash", str(script("monthly_research.sh"))], env=env)


def cmd_classify_story(args: argparse.Namespace) -> int:
    flags: list[str] = []
    if args.prompt:
        flags.append("--prompt")
        flags.append(args.prompt)
    elif args.from_response:
        flags.extend(["--from-response", args.from_response])
        if args.source:
            flags.extend(["--source", args.source])
    elif args.classify:
        flags.append("--classify")
        flags.append(args.classify)
    elif args.classify_all:
        flags.append("--classify-all")
        if args.unclassified:
            flags.append("--unclassified")
        if getattr(args, "emit_prompts", None):
            flags.extend(["--emit-prompts", args.emit_prompts])
    if args.model:
        flags.extend(["--model", args.model])
    if args.verbose:
        flags.append("--verbose")
    if args.limit is not None:
        flags.extend(["--limit", str(args.limit)])
    if args.dry_run:
        flags.append("--dry-run")
    return run_python("classify_story.py", flags)


def cmd_research_expand(args: argparse.Namespace) -> int:
    flags: list[str] = []
    if args.expand:
        flags.extend(["--expand", args.expand])
    elif args.topic:
        flags.extend(["--topic", args.topic])
        if args.type:
            flags.extend(["--type", args.type])
    elif args.gaps:
        flags.append("--gaps")
    if args.prompt_only:
        flags.append("--prompt")
    if args.output:
        flags.extend(["--output", args.output])
    if args.model:
        flags.extend(["--model", args.model])
    if args.from_response:
        flags.extend(["--from-response", args.from_response])
    if args.dry_run:
        flags.append("--dry-run")
    if args.force:
        flags.append("--force")
    return run_python("research_expand.py", flags)


def cmd_recommend_focuses(args: argparse.Namespace) -> int:
    flags = ["--recommend"]
    if args.min_score is not None:
        flags.extend(["--min-score", str(args.min_score)])
    if args.type:
        flags.extend(["--type", args.type])
    if args.include_dismissed:
        flags.append("--include-dismissed")
    if args.json:
        flags.append("--json")
    return run_python("recommend_focuses.py", flags)


def cmd_entity_roster(args: argparse.Namespace) -> int:
    flags = ["--type", args.type]
    if args.emit_task:
        flags.extend(["--emit-task", args.emit_task])
    elif args.from_response:
        flags.extend(["--from-response", args.from_response])
    elif args.show:
        flags.append("--show")
    else:
        flags.append("--resolve")
    if args.min_score is not None:
        flags.extend(["--min-score", str(args.min_score)])
    if args.min_answers is not None:
        flags.extend(["--min-answers", str(args.min_answers)])
    if args.model:
        flags.extend(["--model", args.model])
    if args.force_empty:
        flags.append("--force-empty")
    return run_python("entity_roster.py", flags)


def cmd_focus_action(args: argparse.Namespace) -> int:
    if args.approve:
        return run_python("recommend_focuses.py", ["--approve", args.approve])
    if args.dismiss:
        flags = ["--dismiss", args.dismiss]
        if args.reason:
            flags.extend(["--reason", args.reason])
        return run_python("recommend_focuses.py", flags)
    return 1


def cmd_ingest(args: argparse.Namespace) -> int:
    flags: list[str] = []
    if args.list_sources:
        flags.append("--list-sources")
    else:
        flags.extend(["--source", args.source])
    if args.limit:
        flags.extend(["--limit", str(args.limit)])
    if args.path:
        flags.extend(["--path", args.path])
    if args.export_path:
        flags.extend(["--export-path", args.export_path])
    if args.query:
        flags.extend(["--query", args.query])
    if args.since:
        flags.extend(["--since", args.since])
    if args.username:
        flags.extend(["--username", args.username])
    if args.no_candidates:
        flags.append("--no-candidates")
    if args.dry_run:
        flags.append("--dry-run")
    return run_python("ingest.py", flags)


def cmd_candidates_stats(_args: argparse.Namespace) -> int:
    return run_python("question_candidates.py", ["stats"])


def cmd_candidates_auto_promote(args: argparse.Namespace) -> int:
    flags = ["auto-promote"]
    if getattr(args, "dry_run", False):
        flags.append("--dry-run")
    return run_python("question_candidates.py", flags)


def cmd_followups_status(_args: argparse.Namespace) -> int:
    return run_python("gen_followups.py", ["--status"])


def cmd_followups_prompt(_args: argparse.Namespace) -> int:
    return run_python("gen_followups.py", ["--prompt"])


def cmd_perennial_add(args: argparse.Namespace) -> int:
    from question_candidates import add_perennial
    entry = add_perennial(args.question_id)
    print(f"✓ {args.question_id} marked perennial (re-asked yearly with last year's answer attached)")
    if entry.get("reasks"):
        print(f"  prior re-asks: {', '.join(r['question_id'] for r in entry['reasks'])}")
    return 0


def cmd_perennials(args: argparse.Namespace) -> int:
    from question_candidates import generate_due_perennials, load_perennials
    if args.generate_due:
        created = generate_due_perennials(dry_run=args.dry_run)
        prefix = "[DRY RUN] " if args.dry_run else ""
        if created:
            for new_id, source_id in created:
                print(f"{prefix}✓ Perennial re-ask created: {new_id} (from {source_id}, with last year's answer attached)")
        else:
            print(f"{prefix}No perennials due (≥350 days since last answer).")
        return 0
    data = load_perennials()
    if not data["perennials"]:
        print("No perennial questions yet. Mark one: lifehug.py perennial-add <question-id>")
        print("Good perennials: definition of success, biggest fear, state of the marriage, faith.")
        return 0
    print("Perennial questions (re-asked yearly with last year's answer attached):")
    for p_entry in data["perennials"]:
        reasks = ", ".join(r["question_id"] for r in p_entry.get("reasks", [])) or "none yet"
        print(f"  - {p_entry['question_id']} (re-asks: {reasks})")
    return 0


CHAPTERS_EXERCISE = """📖 Life Chapters exercise (McAdams) — do this once a year.

Think about your life as if it were a book. Divide it into its chapters —
most people land between 2 and 7. For each chapter:

  1. Give it a TITLE (your words, not a date range)
  2. Say briefly what it contains
  3. Say how we get from that chapter to the next — what ENDED, and what began

Don't overthink; the titles you reach for first are the real ones.

Answer by voice or text, then save it as a story:

  printf '%s' "$YOUR_ANSWER" | python3 system/lifehug.py ingest-story \\
    --source "chapters exercise" --title "Life Chapters $(date +%Y)"

Re-run this yearly — how the chapter boundaries MOVE between years is itself
part of your story. The classifier extracts the periods automatically."""


def cmd_chapters_exercise(_args: argparse.Namespace) -> int:
    print(CHAPTERS_EXERCISE)
    return 0


def cmd_retract_source(args: argparse.Namespace) -> int:
    flags = ["retract", args.target]
    if args.reason:
        flags.extend(["--reason", args.reason])
    for slug in args.from_page or []:
        flags.extend(["--from-page", slug])
    if args.title:
        flags.extend(["--title", args.title])
    return run_python("source_integrity.py", flags)


def cmd_unretract(args: argparse.Namespace) -> int:
    flags = ["unretract", args.retraction]
    if args.reason:
        flags.extend(["--reason", args.reason])
    return run_python("source_integrity.py", flags)


def cmd_fix(args: argparse.Namespace) -> int:
    """One-line fact repair, phone-friendly (issue #24). Two modes:
    --right (with optional --wrong) files a CORRECTION that overrides the
    original claim at compile time; --retract files a RETRACTION so the
    compiler stops asserting the source (optionally only on given pages).
    Raw sources are never touched either way."""
    if bool(args.retract) == bool(args.right):
        print("Error: use exactly one of --right \"the true fact\" or --retract", file=sys.stderr)
        return 1
    if args.retract:
        flags = ["retract", args.target, "--reason", args.reason or "retracted via fix"]
        for slug in args.from_page or []:
            flags.extend(["--from-page", slug])
        return run_python("source_integrity.py", flags)
    body = args.right
    if args.wrong:
        body = f"The original says: {args.wrong}\nThe truth is: {args.right}"
    result = subprocess.run(
        [sys.executable, str(script("source_integrity.py")), "correct", args.target,
         "--kind", args.kind, "--source", "fix"],
        input=body, text=True, cwd=REPO_DIR)
    if result.returncode == 0:
        print("  The next compile will assert the corrected fact (cache re-keys automatically).")
    return result.returncode


def cmd_interview_pack(args: argparse.Namespace) -> int:
    """Tier 3 second voice: on-demand question pack for a real conversation.
    Never scheduled — only generated when the owner asks."""
    from research_expand import INTERVIEW_BANKS, build_interview_pack
    relationship = args.relationship
    if relationship not in INTERVIEW_BANKS:
        print(f"Unknown relationship type '{relationship}'. Choose one of: {', '.join(sorted(INTERVIEW_BANKS))}",
              file=sys.stderr)
        return 1
    print(build_interview_pack(args.person, relationship))
    return 0


def cmd_notify(_args: argparse.Namespace) -> int:
    """Read a message from stdin and send it to Telegram, chunked. Always exits
    0 — notification must never break the flow that called it."""
    text = sys.stdin.read()
    if not text.strip():
        return 0
    if not send_telegram(text):
        print("warn: telegram notify incomplete (missing credentials or send failure)", file=sys.stderr)
    return 0


def _parse_iso_utc(raw: str):
    from datetime import datetime, timezone
    raw = str(raw or "")
    if not raw:
        return None
    try:
        if raw.endswith("Z"):
            value = datetime.fromisoformat(raw[:-1] + "+00:00")
        else:
            value = datetime.fromisoformat(raw)
            if value.tzinfo is None:
                value = value.replace(tzinfo=timezone.utc)
        return value
    except ValueError:
        return None


def _days_since(raw: str) -> float | None:
    from datetime import datetime, timezone
    value = _parse_iso_utc(raw)
    if value is None:
        return None
    return (datetime.now(timezone.utc) - value).total_seconds() / 86400


def loop_health_checks() -> int:
    """Checks for the rot that killed the Loop silently before: expired queues,
    aging candidate backlogs, stalled weekly/monthly cadence, zombie Focuses,
    missing classifications, wiped rosters. Returns the number of hard failures
    (most of these are warnings — visible but non-fatal)."""
    failures = 0
    print()

    # Queue health — an expired queue silently reverts the daily pick to the
    # legacy coverage algorithm.
    queue_data = read_json(STATE_DIR / "question_queue.json", default=None)
    if not queue_data:
        warn("planner queue missing", "daily pick is using legacy coverage rotation; run planner-queue")
    else:
        expires_days = _days_since(queue_data.get("expires_at", ""))
        remaining = sum(1 for item in queue_data.get("queue", [])
                        if item.get("status", "queued") == "queued")
        if expires_days is not None and expires_days > 0:
            warn("planner queue EXPIRED", f"{expires_days:.0f} days ago — daily pick silently reverted to legacy rotation")
        elif expires_days is not None and expires_days > -2:
            warn("planner queue expiring soon", f"within 2 days; remaining items: {remaining}")
        elif remaining == 0:
            warn("planner queue exhausted", "no queued items left; daily pick falls back to legacy rotation")
        else:
            check("planner queue valid", True, f"{remaining} item(s) remaining")

    # Candidate backlog — inflow must not permanently exceed outflow.
    cand_data = read_json(STATE_DIR / "question_candidates.json", default=None) or {}
    promotable = [c for c in cand_data.get("candidates", [])
                  if c.get("status") in ("candidate", "accepted", "deferred", "needs_review")]
    if promotable:
        ages = [a for a in (_days_since(c.get("created_at", "")) for c in promotable) if a is not None]
        oldest = max(ages) if ages else 0
        if len(promotable) > 40:
            warn("candidate backlog large", f"{len(promotable)} unresolved (oldest {oldest:.0f}d) — check auto-promote cadence")
        elif oldest > 30:
            warn("candidate backlog aging", f"oldest unresolved candidate is {oldest:.0f} days old")
        else:
            check("candidate backlog healthy", True, f"{len(promotable)} unresolved, oldest {oldest:.0f}d")
    else:
        check("candidate backlog healthy", True, "no unresolved candidates")

    # Cadence — has the weekly/monthly actually run?
    profile = read_json(STATE_DIR / "quality_profile.json", default=None) or {}
    weekly_age = _days_since(profile.get("computed_at") or profile.get("last_updated") or profile.get("updated_at") or "")
    if weekly_age is None:
        warn("weekly cadence unknown", "quality profile has never been updated — has weekly_maintenance.sh ever run?")
    elif weekly_age > 9:
        warn("weekly cadence stalled", f"quality profile last updated {weekly_age:.0f} days ago (expected ~7)")
    else:
        check("weekly cadence", True, f"quality profile updated {weekly_age:.0f}d ago")

    roster = read_json(STATE_DIR / "entity_rosters" / "person.json", default=None) or {}
    monthly_age = _days_since(roster.get("resolved_at", ""))
    if monthly_age is not None and monthly_age > 35:
        warn("monthly cadence stalled", f"person roster last resolved {monthly_age:.0f} days ago (expected ~30)")
    elif monthly_age is not None:
        check("monthly cadence", True, f"person roster resolved {monthly_age:.0f}d ago")

    # Roster continuity — an empty roster is how the Jul-2026 regression looked.
    for etype in ("person", "place", "period", "object", "theme"):
        data = read_json(STATE_DIR / "entity_rosters" / f"{etype}.json", default=None)
        if data is not None and not (data.get("entities") or []):
            warn(f"{etype} roster is EMPTY", "a refresh may have wiped it — restore from git and re-resolve")

    # Zombie Focuses — the planner can never ask about a category-less Focus.
    try:
        from question_planner import resolve_roadmap, zombie_focuses  # noqa: PLC0415
        zombies = zombie_focuses(resolve_roadmap().get("focuses", []))
        if zombies:
            labels = ", ".join(str(f.get("label", f.get("id"))) for f in zombies[:5])
            warn("zombie Focuses (no question categories)", labels)
        else:
            check("no zombie Focuses", True)
    except Exception as exc:  # noqa: BLE001
        warn("zombie-focus check unavailable", str(exc)[:80])

    # Classification coverage — the learning loop starves without it.
    classifications_dir = STATE_DIR / "classifications"
    classified = len(list(classifications_dir.glob("*.json"))) if classifications_dir.exists() else 0
    answers = len(list(ANSWERS_DIR.glob("*.md"))) if ANSWERS_DIR.exists() else 0
    if answers and not classified:
        warn("no sources classified", f"{answers} answers, 0 classifications — the learning loop has never run")
    elif answers:
        check("classification coverage", True, f"{classified}/{answers} sources classified")

    return failures


def cmd_doctor(args: argparse.Namespace) -> int:
    failures = 0
    config = load_config(CONFIG_FILE)

    failures += not check("question bank exists", QUESTIONS_FILE.exists(), str(QUESTIONS_FILE.relative_to(REPO_DIR)))
    failures += not check("rotation state exists", ROTATION_FILE.exists(), str(ROTATION_FILE.relative_to(REPO_DIR)))
    failures += not check("coverage state exists", COVERAGE_FILE.exists(), str(COVERAGE_FILE.relative_to(REPO_DIR)))
    failures += not check("answers directory exists", ANSWERS_DIR.exists(), str(ANSWERS_DIR.relative_to(REPO_DIR)))
    failures += not check("wiki directory exists", WIKI_DIR.exists(), str(WIKI_DIR.relative_to(REPO_DIR)))

    if QUESTIONS_FILE.exists():
        text = QUESTIONS_FILE.read_text(encoding="utf-8")
        questions = parse_questions(text)
        categories = parse_categories(text)
        failures += not check("question bank parses", bool(questions), f"{len(questions)} questions")
        failures += not check("categories parse", bool(categories), f"{len(categories)} categories")

    if CONFIG_FILE.exists():
        check("config exists", True, str(CONFIG_FILE.relative_to(REPO_DIR)))
    else:
        warn("config missing", "create config.yaml before scheduled delivery")

    if has_telegram_target(config):
        check("telegram target configured", True)
    else:
        warn("telegram target missing", "set TELEGRAM_CHAT_ID, telegram_chat_id, or group_chat_id")

    if has_telegram_token():
        check("telegram token source available", True)
    else:
        warn("telegram token missing", "set TELEGRAM_BOT_TOKEN or configure ~/.openclaw/openclaw.json")

    learning_rows = read_learning_failures(limit=5, since_days=14)
    if learning_rows:
        warn("recent learning-loop failures", f"{len(learning_rows)} recorded in the last 14 days")
        for row in learning_rows[:3]:
            print(f"  - {format_learning_failure(row)}")
    else:
        check("recent learning-loop failures", True, "none recorded")

    failures += loop_health_checks()

    print()
    print("checking next question...", flush=True)
    if run_python("ask.py", ["--dry-run"]) != 0:
        failures += 1

    print()
    print("checking wiki compile...", flush=True)
    if run_python("wiki_compile.py", ["--dry-run"]) != 0:
        failures += 1

    if args.daily:
        print()
        print("checking daily delivery dry-run...", flush=True)
        if cmd_daily_dry_run(args) != 0:
            failures += 1

    dirty = git_dirty()
    if dirty is None:
        warn("git status unavailable")
    elif dirty:
        warn("git worktree has uncommitted changes")
    else:
        check("git worktree clean", True)

    print()
    if failures:
        print(f"doctor: {failures} failing check(s)")
        return 1
    print("doctor: ok")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Lifehug script-first workflow wrapper")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("status", help="Show coverage and pass status")
    p.set_defaults(func=cmd_status)

    p = sub.add_parser("ai-status",
                       help="Report the AI route (gateway/sdk-key); exit 1 when keyless (agent mode required)")
    p.set_defaults(func=cmd_ai_status)

    p = sub.add_parser("next", help="Preview the next question without mutating state")
    p.set_defaults(func=cmd_next)

    p = sub.add_parser("compile", help="Compile the private wiki")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--no-ai", action="store_true", help="Skip LLM synthesis; deterministic excerpts only")
    p.add_argument("--model", help="Override the wiki synthesis model")
    p.add_argument("--emit-tasks", metavar="PATH",
                   help="Write per-page synthesis tasks to PATH and exit (keyless agent path)")
    p.set_defaults(func=cmd_compile)

    p = sub.add_parser("source-scan", help="Summarize raw source files")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_source_scan)

    p = sub.add_parser("source-manifest", help="Show or rebuild the raw source manifest")
    p.add_argument("--rebuild", action="store_true")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_source_manifest)

    p = sub.add_parser("source-lint", help="Lint raw source integrity and queue repair findings")
    p.add_argument("--fix", action="store_true", help="Apply safe metadata/manifest repairs")
    p.add_argument("--strict", action="store_true", help="Also report uncited sources")
    p.add_argument("--json", action="store_true")
    p.add_argument("--limit", type=int)
    p.add_argument("--no-write-findings", action="store_true")
    p.set_defaults(func=cmd_source_lint)

    p = sub.add_parser("source-findings", help="List persisted source lint findings")
    p.add_argument("--status", default="open")
    p.add_argument("--json", action="store_true")
    p.add_argument("--limit", type=int)
    p.set_defaults(func=cmd_source_findings)

    p = sub.add_parser("correct-source", help="Create an additive correction source from stdin")
    p.add_argument("target", help="Source path or source_id to correct")
    p.add_argument("--kind", default="other", choices=["factual", "date", "name", "emotional", "perspective", "omission", "relationship", "other"])
    p.add_argument("--source", default="manual")
    p.add_argument("--title")
    p.set_defaults(func=cmd_correct_source)

    p = sub.add_parser("reflect-source", help="Create an additive reflection source from stdin")
    p.add_argument("target", help="Source path or source_id to reflect on")
    p.add_argument("--source", default="manual")
    p.add_argument("--title")
    p.set_defaults(func=cmd_reflect_source)

    p = sub.add_parser("ingest-story", help="Save an unprompted story source from stdin")
    p.add_argument("--source", default="manual")
    p.add_argument("--title", default=None)
    p.add_argument("--captured-at", default=None)
    p.add_argument("--no-candidates", action="store_true")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--witness", default=None, metavar="PERSON", help="This is another person's account (second voice), e.g. --witness Mom")
    p.add_argument("--sensitivity", default=None, choices=["private", "family", "friends", "public"])
    p.add_argument("--kind", default="story", choices=["story", "opinion"],
                   help="Content kind: opinion = the author's stated position/lens; gets Socratic follow-ups and can seed an essay artifact")
    p.set_defaults(func=cmd_ingest_story)

    def add_candidate_filters(candidate_parser: argparse.ArgumentParser) -> None:
        candidate_parser.add_argument("--status", choices=CANDIDATE_STATUS_CHOICES)
        candidate_parser.add_argument("--kind")
        candidate_parser.add_argument("--source")
        candidate_parser.add_argument("--target-page")
        candidate_parser.add_argument("--min-priority", type=float)
        candidate_parser.add_argument("--limit", type=int, default=25)

    p = sub.add_parser("candidates-list", help="List question candidates")
    add_candidate_filters(p)
    p.add_argument("--detail", action="store_true")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_candidates_list)

    p = sub.add_parser("candidates-review", help="Review candidate questions with detail")
    add_candidate_filters(p)
    p.set_defaults(func=cmd_candidates_review)

    p = sub.add_parser("candidates-update", help="Update candidate metadata or status")
    p.add_argument("candidate_id")
    p.add_argument("--status", choices=CANDIDATE_STATUS_CHOICES)
    p.add_argument("--target-page")
    p.add_argument("--target-category")
    p.add_argument("--priority", type=float)
    p.add_argument("--reason")
    p.set_defaults(func=cmd_candidates_update)

    p = sub.add_parser("candidates-promote", help="Promote a candidate into the question bank")
    p.add_argument("candidate_id")
    p.add_argument("--category", required=True)
    p.set_defaults(func=cmd_candidates_promote)

    p = sub.add_parser("candidates-promote-neighborhood", help="Promote all of a neighborhood's candidates into one category")
    p.add_argument("--neighborhood", required=True)
    p.add_argument("--category", required=True)
    p.set_defaults(func=cmd_candidates_promote_neighborhood)

    p = sub.add_parser("planner-report", help="Show planner balance and candidates")
    p.add_argument("--limit", type=int, default=10)
    p.set_defaults(func=cmd_planner_report)

    p = sub.add_parser("planner-queue", help="Write the roadmap-driven weekly queue")
    p.add_argument("--limit", type=int, default=DEFAULT_DELIVERY_QUEUE_LIMIT)
    p.add_argument("--arc-max", type=int, default=2)
    p.add_argument("--expires-days", type=int, default=8)
    p.set_defaults(func=cmd_planner_queue)

    p = sub.add_parser("planner-clear", help="Clear the planned daily queue")
    p.set_defaults(func=cmd_planner_clear)

    p = sub.add_parser("planner-state", help="Show or initialize planner state")
    p.add_argument("--init", action="store_true")
    p.set_defaults(func=cmd_planner_state)

    p = sub.add_parser("planner-objective-add", help="Add an active planner objective")
    p.add_argument("label")
    p.add_argument("--category", action="append", default=[])
    p.add_argument("--keyword", action="append", default=[])
    p.add_argument("--max-questions", type=int)
    p.set_defaults(func=cmd_planner_objective_add)

    p = sub.add_parser("planner-objective-clear", help="Clear active planner objectives")
    p.set_defaults(func=cmd_planner_objective_clear)

    # --- AI Classification ---
    p = sub.add_parser("classify-story", help="Classify a source file with AI")
    p.add_argument("--classify", metavar="PATH", help="Source file to classify")
    p.add_argument("--prompt", metavar="PATH", help="Output AI prompt only")
    p.add_argument("--from-response", metavar="PATH",
                   help="Ingest an agent-written classification JSON (keyless agent path)")
    p.add_argument("--source", metavar="PATH", help="With --from-response: the source file it classifies")
    p.add_argument("--classify-all", action="store_true")
    p.add_argument("--unclassified", action="store_true")
    p.add_argument("--emit-prompts", metavar="DIR",
                   help="With --classify-all: write prompts + manifest for agent completion instead of calling AI")
    p.add_argument("--limit", type=int, help="With --classify-all: maximum files to classify")
    p.add_argument("--model", help="Override AI model")
    p.add_argument("--verbose", "-v", action="store_true")
    p.add_argument("--dry-run", action="store_true")
    p.set_defaults(func=cmd_classify_story)

    # --- Research Neighborhoods ---
    p = sub.add_parser("research-expand", help="Generate question neighborhoods")
    p.add_argument("--expand", metavar="PATH", help="Expand from a file")
    p.add_argument("--topic", help="Named topic to expand")
    p.add_argument("--type", choices=VALID_TOPIC_TYPES)
    p.add_argument("--gaps", action="store_true", help="Auto-detect thin areas")
    p.add_argument("--prompt-only", action="store_true", help="Output AI prompt only")
    p.add_argument("--output", choices=VALID_OUTPUT_TYPES, default="chapter")
    p.add_argument("--from-response", metavar="PATH",
                   help="Deposit an agent-written questions JSON instead of calling a model")
    p.add_argument("--model", help="Override AI model")
    p.add_argument("--force", action="store_true")
    p.add_argument("--dry-run", action="store_true")
    p.set_defaults(func=cmd_research_expand)

    # --- Focus Recommendations ---
    p = sub.add_parser("recommend-focuses", help="Recommend new Focuses from accumulated stories")
    p.add_argument("--min-score", type=float)
    p.add_argument("--type", choices=FOCUS_RECOMMENDATION_TYPES)
    p.add_argument("--include-dismissed", action="store_true")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_recommend_focuses)

    p = sub.add_parser("entity-roster",
                       help="Resolve mentioned entities (person/place/period/object/theme) into a canonical roster")
    p.add_argument("--type", choices=["person", "place", "period", "object", "theme"], default="person")
    p.add_argument("--emit-task", metavar="PATH", help="Write resolution prompt + candidates (keyless agent path)")
    p.add_argument("--from-response", metavar="PATH", help="Ingest an agent-written roster JSON")
    p.add_argument("--show", action="store_true", help="Print the current roster")
    p.add_argument("--min-score", type=float, help="Page score threshold (type default)")
    p.add_argument("--min-answers", type=int, help="Page answer threshold (type default)")
    p.add_argument("--model", help="Override AI model")
    p.add_argument("--force-empty", action="store_true",
                   help="Allow an empty object roster to overwrite an existing one")
    p.set_defaults(func=cmd_entity_roster)

    p = sub.add_parser("focus-approve", help="Approve a Focus recommendation")
    p.add_argument("approve", metavar="REC_ID")
    p.set_defaults(func=cmd_focus_action, dismiss=None, reason=None)

    p = sub.add_parser("focus-dismiss", help="Dismiss a Focus recommendation")
    p.add_argument("dismiss", metavar="REC_ID")
    p.add_argument("--reason", default="")
    p.set_defaults(func=cmd_focus_action, approve=None)

    # --- Unified Ingest ---
    p = sub.add_parser("ingest", help="Import from external sources (x, email, instagram, file)")
    p.add_argument("--source", help="Connector name")
    p.add_argument("--list-sources", action="store_true")
    p.add_argument("--limit", type=int)
    p.add_argument("--path", help="File path (file connector)")
    p.add_argument("--export-path", help="Export file/dir path")
    p.add_argument("--query", help="Search query (email connector)")
    p.add_argument("--since", help="Date filter YYYY-MM-DD")
    p.add_argument("--username", help="Username (X connector)")
    p.add_argument("--no-candidates", action="store_true")
    p.add_argument("--dry-run", action="store_true")
    p.set_defaults(func=cmd_ingest)

    # --- Candidate Stats ---
    p = sub.add_parser("candidates-stats", help="Show candidate question statistics")
    p.set_defaults(func=cmd_candidates_stats)

    p = sub.add_parser("candidates-auto-promote", help="Auto-promote top candidates into the question bank")
    p.add_argument("--dry-run", action="store_true", help="Preview without writing")
    p.set_defaults(func=cmd_candidates_auto_promote)

    # --- Roadmap / Focus ---
    p = sub.add_parser("progress", help="Show progress toward deliverables (readiness dashboard)")
    p.set_defaults(func=cmd_progress)

    p = sub.add_parser("book-status", help="Show book assembly: chapter list + readiness per book-project Focus")
    p.set_defaults(func=cmd_book_status)

    p = sub.add_parser("book-chapter", help="Show one chapter's readiness and top gap questions")
    p.add_argument("book", help="Book id or slug (e.g. 'my-life' or 'etherfuse')")
    p.add_argument("chapter", help="Chapter category id (e.g. 'A') or slug (e.g. 'origins')")
    p.set_defaults(func=cmd_book_chapter)

    p = sub.add_parser("book-offers", help="Preview (default) or fire chapter-ready Telegram offers")
    p.add_argument("--send", action="store_true", help="Actually send + mark as offered (default is preview only)")
    p.set_defaults(func=cmd_book_offers)

    p = sub.add_parser("quality-stats", help="Show answer quality profile")
    p.set_defaults(func=cmd_quality_stats)

    p = sub.add_parser("quality-update", help="Recompute quality profile from answer scores")
    p.set_defaults(func=cmd_quality_update)

    p = sub.add_parser("second-voice-ack", help="Acknowledge a second-voice offer (hides the home card)")
    p.add_argument("key", help="The offer key from state/second_voice_offers.json")
    p.set_defaults(func=cmd_second_voice_ack)

    p = sub.add_parser("mirror-compile",
                       help="Synthesize wiki/self/mirror.md from classifier contradictions/insights/positions")
    p.add_argument("--model", help="AI model override")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--emit-task", metavar="DIR",
                   help="Keyless: emit the synthesis prompt for agent completion")
    p.add_argument("--from-response", metavar="PATH",
                   help="Ingest an agent-written markdown body and write the page")
    p.set_defaults(func=cmd_mirror_compile)

    p = sub.add_parser("artifact", help="Create occasion artifacts and promote final works as sources", add_help=False)
    p.add_argument("-h", "--help", dest="artifact_help", action="store_true")
    p.add_argument("artifact_args", nargs=argparse.REMAINDER)
    p.set_defaults(func=cmd_artifact)

    p = sub.add_parser("roadmap", help="Show the roadmap of Focuses with live fill")
    p.set_defaults(func=cmd_roadmap)

    p = sub.add_parser("roadmap-rebuild", help="Derive/refresh the roadmap from the question bank")
    p.set_defaults(func=cmd_roadmap_rebuild)

    p = sub.add_parser("focus-new", help="Create a Focus end-to-end: scaffold category, register, seed questions")
    p.add_argument("label")
    p.add_argument("--type", default="theme",
                   choices=["person", "place", "period", "project", "theme", "event", "lifes_work", "self", "relationship"])
    p.add_argument("--tier", default="standard", choices=["basic", "standard", "extreme"])
    p.add_argument("--objective", default="")
    p.add_argument("--deliverable", default="chapter")
    p.add_argument("--no-generate", action="store_true")
    p.set_defaults(func=cmd_focus_new)

    p = sub.add_parser("focus-add", help="Add a Focus (objective + tier)")
    p.add_argument("label")
    p.add_argument("--type", default="project",
                   choices=["person", "place", "period", "project", "theme", "event", "lifes_work", "self", "life_story"])
    p.add_argument("--tier", default="standard", choices=["basic", "standard", "extreme"])
    p.add_argument("--objective", default="")
    p.add_argument("--deliverable", default="chapter")
    p.add_argument("--target", type=int)
    p.add_argument("--category", action="append", default=[])
    p.set_defaults(func=cmd_focus_add)

    p = sub.add_parser("focus-set", help="Update a Focus (tier/target/cap/phase/objective)")
    p.add_argument("focus_id")
    p.add_argument("--tier", choices=["basic", "standard", "extreme"])
    p.add_argument("--target", type=int)
    p.add_argument("--cap", type=float)
    p.add_argument("--phase", choices=["active", "finishing", "maintenance"])
    p.add_argument("--objective")
    p.add_argument("--deliverable")
    p.add_argument("--category", action="append", default=[])
    p.set_defaults(func=cmd_focus_set)

    p = sub.add_parser("focus-finish", help="Flag a Focus as finishing (lifts its variety cap)")
    p.add_argument("focus_id")
    p.set_defaults(func=cmd_focus_finish)

    p = sub.add_parser("serve", help="Serve the local owner-only wiki")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8765)
    p.set_defaults(func=cmd_serve)

    p = sub.add_parser("rebuild", help="Rebuild derived state and README progress")
    p.set_defaults(func=cmd_rebuild)

    p = sub.add_parser("process-answer", help="Save an answer from stdin and update state")
    p.add_argument("question_id", nargs="?")
    p.add_argument("--source", default=None)
    p.add_argument("--answered-date", default=None)
    p.add_argument("--asked-date", default=None)
    p.add_argument("--followup", action="append", default=[])
    p.add_argument("--force", action="store_true")
    p.add_argument("--commit", action="store_true")
    p.add_argument("--push", action="store_true")
    p.add_argument("--summary")
    p.add_argument("--no-compile-wiki", action="store_true")
    p.add_argument("--sensitivity", default=None, choices=["private", "family", "friends", "public"])
    p.set_defaults(func=cmd_process_answer)

    p = sub.add_parser("daily-dry-run", help="Validate daily delivery config without sending")
    p.set_defaults(func=cmd_daily_dry_run)

    p = sub.add_parser("weekly-maintenance", help="Run weekly lint/fix, quality, planner, and progress flow")
    p.add_argument("--dry-run", action="store_true")
    p.set_defaults(func=cmd_weekly_maintenance)

    p = sub.add_parser("weekly-summary", help="Build the short counts-first maintenance summary from state (issue #35)")
    p.add_argument("--since", required=True, help="ISO timestamp — count activity at/after this moment")
    p.add_argument("--kind", choices=("weekly", "monthly"), default="weekly")
    p.add_argument("--report-path", help="Persisted full-report path shown as a pointer")
    p.add_argument("--doctor-file", help="Doctor output file ('-' = stdin); omitted runs checks in-process")
    p.set_defaults(func=cmd_weekly_summary)

    p = sub.add_parser("monthly-research", help="Run monthly neighborhood growth and Focus recommendations")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--gap-limit", type=int, help="Maximum new gap neighborhoods to attempt")
    p.add_argument("--self-topic", help="Self-knowledge topic to seed when missing")
    p.add_argument("--focus-min-score", type=float, help="Minimum Focus recommendation score")
    p.set_defaults(func=cmd_monthly_research)

    p = sub.add_parser("followups-status", help="Show pass-transition follow-up state")
    p.set_defaults(func=cmd_followups_status)

    p = sub.add_parser("followups-prompt", help="Print pass-transition prompt context")
    p.set_defaults(func=cmd_followups_prompt)

    p = sub.add_parser("doctor", help="Run local health checks")
    p.add_argument("--daily", action="store_true", help="Also run daily delivery dry-run")
    p.set_defaults(func=cmd_doctor)

    p = sub.add_parser("perennial-add", help="Mark a question as perennial (re-asked yearly with last year's answer)")
    p.add_argument("question_id")
    p.set_defaults(func=cmd_perennial_add)

    p = sub.add_parser("perennials", help="List perennial questions; --generate-due inserts due yearly re-asks")
    p.add_argument("--generate-due", action="store_true")
    p.add_argument("--dry-run", action="store_true")
    p.set_defaults(func=cmd_perennials)

    p = sub.add_parser("chapters-exercise", help="Print the annual McAdams life-chapters exercise")
    p.set_defaults(func=cmd_chapters_exercise)

    p = sub.add_parser("retract-source", help="Stop the compiler asserting a source (raw file untouched)")
    p.add_argument("target")
    p.add_argument("--reason", default=None)
    p.add_argument("--from-page", action="append", default=[], metavar="SLUG")
    p.add_argument("--title", default=None)
    p.set_defaults(func=cmd_retract_source)

    p = sub.add_parser("unretract", help="Void a wrong retraction so the source is asserted again (v88)")
    p.add_argument("retraction", help="Retraction file under sources/corrections/ (or its source id)")
    p.add_argument("--reason", default=None, help="Why the retraction was wrong")
    p.set_defaults(func=cmd_unretract)

    p = sub.add_parser("fix", help="One-line fact repair: --right files a correction, --retract suppresses the source")
    p.add_argument("target", help="source id or path, e.g. answers/A7.md or answer:A7")
    p.add_argument("--right", default=None, help="The true fact (files a correction)")
    p.add_argument("--wrong", default=None, help="What the source wrongly says (optional context)")
    p.add_argument("--retract", action="store_true", help="Suppress the source instead of correcting it")
    p.add_argument("--reason", default=None, help="Why (for --retract)")
    p.add_argument("--from-page", action="append", default=[], metavar="SLUG",
                   help="With --retract: only suppress on these page slugs")
    p.add_argument("--kind", default="factual", help="Correction kind (factual, date, name, ...)")
    p.set_defaults(func=cmd_fix)

    p = sub.add_parser("interview-pack", help="On-demand question pack for interviewing someone (second voice, Tier 3)")
    p.add_argument("person", help="Who you'll be talking with, e.g. Mom")
    p.add_argument("--relationship", default="parent",
                   help="parent, grandparent, spouse, child, sibling, mentor, cofounder, friend, or remembering (a shared loved one)")
    p.set_defaults(func=cmd_interview_pack)

    p = sub.add_parser("notify", help="Send stdin to the configured Telegram target, chunked under the 4096-char limit")
    p.set_defaults(func=cmd_notify)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
