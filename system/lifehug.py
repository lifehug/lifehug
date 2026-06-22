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


def cmd_planner_report(_args: argparse.Namespace) -> int:
    return run_python("question_planner.py", ["--report"])


def cmd_planner_queue(args: argparse.Namespace) -> int:
    flags = ["--write-queue", "--limit", str(args.limit), "--arc-max", str(args.arc_max)]
    return run_python("question_planner.py", flags)


def cmd_planner_clear(_args: argparse.Namespace) -> int:
    return run_python("question_planner.py", ["--clear-queue"])


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

    p = sub.add_parser("planner-report", help="Show planner balance and candidates")
    p.set_defaults(func=cmd_planner_report)

    p = sub.add_parser("planner-queue", help="Write an opt-in planned daily queue")
    p.add_argument("--limit", type=int, default=14)
    p.add_argument("--arc-max", type=int, default=2)
    p.set_defaults(func=cmd_planner_queue)

    p = sub.add_parser("planner-clear", help="Clear the planned daily queue")
    p.set_defaults(func=cmd_planner_clear)

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
