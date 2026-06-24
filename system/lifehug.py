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
    WIKI_DIR,
    load_config,
    parse_categories,
    parse_questions,
)

SYSTEM_DIR = Path(__file__).resolve().parent


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


def cmd_next(_args: argparse.Namespace) -> int:
    return run_python("ask.py", ["--dry-run"])


def cmd_compile(args: argparse.Namespace) -> int:
    flags = ["--dry-run"] if args.dry_run else []
    return run_python("wiki_compile.py", flags)


def cmd_ingest_story(args: argparse.Namespace) -> int:
    flags = ["--source", args.source]
    if args.title:
        flags.extend(["--title", args.title])
    if args.captured_at:
        flags.extend(["--captured-at", args.captured_at])
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
    if args.force:
        flags.append("--force")
    if args.commit:
        flags.append("--commit")
    if args.push:
        flags.append("--push")
    if args.no_compile_wiki:
        flags.append("--no-compile-wiki")
    for followup in args.followup or []:
        flags.extend(["--followup", followup])
    question_id = [] if args.question_id is None else [args.question_id]
    return run_python("process_answer.py", [*question_id, *flags])


def cmd_daily_dry_run(_args: argparse.Namespace) -> int:
    env = os.environ.copy()
    env["LIFEHUG_DAILY_DRY_RUN"] = "1"
    return run(["bash", str(script("daily_question.sh"))], env=env)


def cmd_classify_story(args: argparse.Namespace) -> int:
    flags: list[str] = []
    if args.prompt:
        flags.append("--prompt")
        flags.append(args.prompt)
    elif args.classify:
        flags.append("--classify")
        flags.append(args.classify)
    elif args.classify_all:
        flags.append("--classify-all")
        if args.unclassified:
            flags.append("--unclassified")
    if args.model:
        flags.extend(["--model", args.model])
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
    if args.dry_run:
        flags.append("--dry-run")
    if args.force:
        flags.append("--force")
    return run_python("research_expand.py", flags)


def cmd_recommend_spotlights(args: argparse.Namespace) -> int:
    flags = ["--recommend"]
    if args.min_score is not None:
        flags.extend(["--min-score", str(args.min_score)])
    if args.type:
        flags.extend(["--type", args.type])
    if args.include_dismissed:
        flags.append("--include-dismissed")
    if args.json:
        flags.append("--json")
    return run_python("recommend_spotlights.py", flags)


def cmd_spotlight_action(args: argparse.Namespace) -> int:
    if args.approve:
        return run_python("recommend_spotlights.py", ["--approve", args.approve])
    if args.dismiss:
        flags = ["--dismiss", args.dismiss]
        if args.reason:
            flags.extend(["--reason", args.reason])
        return run_python("recommend_spotlights.py", flags)
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


def cmd_followups_status(_args: argparse.Namespace) -> int:
    return run_python("gen_followups.py", ["--status"])


def cmd_followups_prompt(_args: argparse.Namespace) -> int:
    return run_python("gen_followups.py", ["--prompt"])


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

    p = sub.add_parser("next", help="Preview the next question without mutating state")
    p.set_defaults(func=cmd_next)

    p = sub.add_parser("compile", help="Compile the private wiki")
    p.add_argument("--dry-run", action="store_true")
    p.set_defaults(func=cmd_compile)

    p = sub.add_parser("ingest-story", help="Save an unprompted story source from stdin")
    p.add_argument("--source", default="manual")
    p.add_argument("--title", default=None)
    p.add_argument("--captured-at", default=None)
    p.add_argument("--no-candidates", action="store_true")
    p.add_argument("--dry-run", action="store_true")
    p.set_defaults(func=cmd_ingest_story)

    def add_candidate_filters(candidate_parser: argparse.ArgumentParser) -> None:
        candidate_parser.add_argument("--status", choices=["accepted", "candidate", "deferred", "promoted", "rejected"])
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
    p.add_argument("--status", choices=["accepted", "candidate", "deferred", "promoted", "rejected"])
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
    p.add_argument("--limit", type=int, default=12)
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
    p.add_argument("--classify-all", action="store_true")
    p.add_argument("--unclassified", action="store_true")
    p.add_argument("--model", help="Override AI model")
    p.add_argument("--dry-run", action="store_true")
    p.set_defaults(func=cmd_classify_story)

    # --- Research Neighborhoods ---
    p = sub.add_parser("research-expand", help="Generate question neighborhoods")
    p.add_argument("--expand", metavar="PATH", help="Expand from a file")
    p.add_argument("--topic", help="Named topic to expand")
    p.add_argument("--type", choices=["person", "place", "time_period", "project", "theme", "event", "self", "relationship"])
    p.add_argument("--gaps", action="store_true", help="Auto-detect thin areas")
    p.add_argument("--prompt-only", action="store_true", help="Output AI prompt only")
    p.add_argument("--output", choices=["chapter", "letter", "essay", "post", "profile"], default="chapter")
    p.add_argument("--model", help="Override AI model")
    p.add_argument("--force", action="store_true")
    p.add_argument("--dry-run", action="store_true")
    p.set_defaults(func=cmd_research_expand)

    # --- Spotlight Recommendations ---
    p = sub.add_parser("recommend-spotlights", help="Recommend new spotlights from accumulated stories")
    p.add_argument("--min-score", type=float)
    p.add_argument("--type", choices=["person", "place", "time_period", "project", "theme"])
    p.add_argument("--include-dismissed", action="store_true")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_recommend_spotlights)

    p = sub.add_parser("spotlight-approve", help="Approve a spotlight recommendation")
    p.add_argument("approve", metavar="REC_ID")
    p.set_defaults(func=cmd_spotlight_action, dismiss=None, reason=None)

    p = sub.add_parser("spotlight-dismiss", help="Dismiss a spotlight recommendation")
    p.add_argument("dismiss", metavar="REC_ID")
    p.add_argument("--reason", default="")
    p.set_defaults(func=cmd_spotlight_action, approve=None)

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

    # --- Roadmap / Focus ---
    p = sub.add_parser("progress", help="Show progress toward deliverables (readiness dashboard)")
    p.set_defaults(func=cmd_progress)

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
    p.add_argument("--followup", action="append", default=[])
    p.add_argument("--force", action="store_true")
    p.add_argument("--commit", action="store_true")
    p.add_argument("--push", action="store_true")
    p.add_argument("--no-compile-wiki", action="store_true")
    p.set_defaults(func=cmd_process_answer)

    p = sub.add_parser("daily-dry-run", help="Validate daily delivery config without sending")
    p.set_defaults(func=cmd_daily_dry_run)

    p = sub.add_parser("followups-status", help="Show pass-transition follow-up state")
    p.set_defaults(func=cmd_followups_status)

    p = sub.add_parser("followups-prompt", help="Print pass-transition prompt context")
    p.set_defaults(func=cmd_followups_prompt)

    p = sub.add_parser("doctor", help="Run local health checks")
    p.add_argument("--daily", action="store_true", help="Also run daily delivery dry-run")
    p.set_defaults(func=cmd_doctor)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
