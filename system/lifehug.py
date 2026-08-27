#!/usr/bin/env python3
"""Script-first Lifehug workflow wrapper.

This is a thin dispatcher over the canonical scripts in system/. It exists so
humans, skills, and cron jobs can share one stable entrypoint without copying
workflow logic.
"""

from __future__ import annotations

import argparse
import json
import os
import runpy
import subprocess
import sys
from pathlib import Path

from vault_paths import bootstrap_cli_vault_root, normalize_cli_vault_args

# Global options must select the vault before lifehug_core and the command
# modules bind their path constants. The helper is the single precedence and
# validation authority; argparse below only exposes the public flag.
sys.argv[1:] = normalize_cli_vault_args(sys.argv[1:])
bootstrap_cli_vault_root(sys.argv[1:])

from lifehug_core import (
    ANSWERS_DIR,
    CLASSIFICATIONS_DIR,
    CONFIG_FILE,
    COVERAGE_FILE,
    ENTITY_ROSTERS_DIR,
    QUALITY_PROFILE_FILE,
    QUESTION_CANDIDATES_FILE,
    QUESTION_QUEUE_FILE,
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
from focus_candidate import FOCUS_RELATIONSHIPS
from roadmap import FOCUS_TYPES

SYSTEM_DIR = Path(__file__).resolve().parent
CANDIDATE_STATUS_CHOICES = sorted(VALID_STATUSES)

# Every canonical command is classified exactly once. Durable operations keep
# their existing typed queue route; every other possible vault mutator takes
# the same kernel writer lock directly. Read-only commands never block behind
# a long job.
QUEUED_MUTATION_COMMANDS = frozenset({
    "artifact", "book-assemble", "compile", "monthly-research", "process-answer",
    "weekly-maintenance",
})
READ_ONLY_COMMANDS = frozenset({
    "ai-status", "answer-ack-prompt", "answer-ack-status",
    # Issue #118: the daily attach is a PURE READ of state/arc_cards.json —
    # it must never take the writer lock, because daily_question.sh calls it
    # between picking and sending.
    "arc-card",
    # arc-walk-interaction (v193, Design §E): arc-plan-target recomputes an
    # episode plan from the bank and prints it — pure reads, no writer lock,
    # exactly like arc-card above.
    "arc-plan-target", "arc-walk-evals",
    # timeline-chronology (v195, Design §D/§E): both are pure reads —
    # the seat gate scores committed goldens, and the timeline plan
    # recomputes unknowns from the vault and prints them.
    "timeline-evals",
    # landmarks (v197, Design §E): both are pure reads — the seat gate
    # scores committed goldens, and the landmarks plan recomputes the
    # open landmark rows from the vault and prints them.
    "landmarks-evals",
    # E3 (eras §4.1): the era list is a pure read of sources/eras/.
    "era-list",
    # the Reading Room (v204, ADR 0025): both are pure reads — the seat gate
    # scores committed goldens, and the plan recomputes the dig plan and the
    # per-witness lists from the vault and prints them.
    "reading-room-evals", "reading-room-plan",
    "book-chapter", "book-status",
    "candidates-list", "candidates-review", "candidates-stats", "chapters-exercise",
    "connector-audit", "connector-report",
    "conversation-arc-prompt",
    "conversation-closing-prompt", "conversation-lint",
    "conversation-router-prompt", "conversation-status", "conversation-turn-prompt",
    "daily-dry-run", "doctor",
    # focus-duplicate-curation contract, Scope 3: the damage list is
    # deterministic, zero AI, zero writes — pure reads of roadmap.json and
    # focus_recommendations.json.
    "focus-dupes",
    "followups-prompt", "followups-status", "interview-pack", "next", "notify",
    "focus-candidate-evals", "focus-candidate-prompt", "entity-candidate-evals", "entity-candidate-prompt",
    "planner-report", "progress", "quality-stats", "question-candidate-evals",
    "question-candidate-prompt", "roadmap", "serve",
    "source-findings", "source-scan", "status", "weekly-summary",
    # Issue #117: routing reads rotation + session state and makes a model
    # call, but mutates nothing durable (test_route_mutates_nothing pins
    # this).
    "route",
})
DIRECT_MUTATION_COMMANDS = frozenset({
    "answer-ack-retry",
    # Issue #118 (Conversation Interaction, Wave 2): both write
    # state/arc_cards.json, so they take the writer lock like the rest of the
    # weekly/monthly learning-loop family.
    "arc-plan", "arc-thread-offers",
    "book-offers", "candidates-auto-promote", "candidates-promote",
    "candidates-promotion-receipt",
    "focus-candidate-complete", "entity-candidate-complete",
    "candidates-promote-neighborhood", "candidates-update", "classify-story",
    "connector-auth", "connector-calibrate", "connector-dossier", "connector-excavate",
    "connector-fetch",
    # New in issue #115 (Conversation Interaction, Wave 1 PR 2): the session
    # store's own three mutators. No jobs.py command kind yet (Wave 2) — they
    # take the writer lock directly like the rest of this family.
    "conversation-close", "conversation-open", "conversation-record-turn",
    # Issue #120 (eval harness): the default run is read-only, but
    # --emit-tasks writes state/agent_tasks/evals/ — classified with the
    # rest of the --emit-tasks family (arc-plan) rather than per-invocation.
    "conversation-evals",
    # New in issue #116 (Wave 2 PR 3): the operator retry door for a turn
    # whose send definitively failed. conversation-close is unchanged here —
    # it was already classified; #116 only upgraded what it does.
    "conversation-turn-retry",
    "correct-source", "entity-roster",
    # entity-verdict (ADR 0013): the owner's graduate-now/never-a-page/clear
    # accelerator over one roster entity — a single-file roster mutation,
    # same writer-lock family as entity-roster itself.
    "entity-verdict",
    "fix", "focus-add",
    "focus-approve",
    # ADR 0011 (the Convergence Principle's floor applied to focus
    # creation): auto-approval reuses approve_recommendation() verbatim, so
    # it's the same writer-lock family as focus-approve/recommend-focuses.
    # --dry-run writes nothing but the command is still classified by name.
    "focus-autopilot",
    # focus-duplicate-curation (ADR 0010): applying a CURATE verdict writes
    # state/focus_recommendations.json directly (--dry-run/--emit-task
    # never write) — same family as judgment-update.
    "focus-curate",
    "focus-dismiss", "focus-finish",
    # entity-identity-context (v190): the entity -> focus hand-off appends one
    # row to state/focus_recommendations.json — same single-file writer-lock
    # family as focus-dismiss/recommend-focuses. It creates no Focus.
    "focus-recommend-from-entity",
    # focus-merge (ADR 0012): the healing verb rewrites state/roadmap.json,
    # the question bank, entity rosters, the curation ledger and a wiki page
    # in ONE transaction — the widest single-command vault mutation in the
    # system, so it takes the writer lock unconditionally. --dry-run writes
    # nothing but the command is still classified by name (same convention
    # as focus-autopilot/focus-curate).
    "focus-merge",
    "focus-new", "focus-set",
    "ingest", "ingest-story",
    # decisions-feed-the-loop (ADR 0009): the weekly RUBRIC-EDIT runtime
    # writes state/question_judgment/learned.md and last_edit.json directly
    # (--dry-run/--emit-task never write) — same family as quality-update.
    "judgment-update",
    "mirror-compile", "perennial-add", "perennials",
    "planner-clear", "planner-objective-add", "planner-objective-clear", "planner-queue",
    "planner-state", "quality-update", "rebuild", "recommend-focuses", "reflect-source",
    "research-expand", "retract-source", "roadmap-rebuild", "second-voice-ack",
    # v123: renames correction/retraction sources on disk AND rewrites every
    # state index that points at them — a vault mutator, so it takes the
    # writer lock like the rest of the source-repair family.
    "source-filenames-repair",
    "landmark-record",
    "source-lint", "source-manifest", "timeline-place", "timeline-retire",
    # v232 (wave E, item E2): a drag files a durable correction source under
    # sources/corrections/ and republishes the calculated projection. Same
    # single-transaction vault mutation family as timeline-place.
    "timeline-move", "timeline-move-undo",
    # E3 (eras §4.4): the ATOMIC era writer. One payload creates the
    # identity, names it, decides its kind, files and binds its claims, files
    # a `within` and publishes — in one act, every step idempotent. Same
    # single-transaction vault mutation family as timeline-move; classified by
    # name, and `era-migrate --dry-run` writes nothing but is still classified
    # here for the same reason focus-autopilot is.
    "era-record", "era-migrate",
    "timeline-unplace", "unretract",
})


def script(name: str) -> Path:
    return SYSTEM_DIR / name


def run(args: list[str], *, env: dict[str, str] | None = None) -> int:
    return subprocess.run(args, cwd=REPO_DIR, env=env).returncode


def run_python(script_name: str, args: list[str]) -> int:
    if os.environ.get("LIFEHUG_JOB_IN_PROCESS") == "1":
        target = script(script_name)
        previous_argv = sys.argv
        sys.argv = [str(target), *args]
        try:
            runpy.run_path(str(target), run_name="__main__")
        except SystemExit as exc:
            return int(exc.code or 0) if isinstance(exc.code, int | type(None)) else 1
        finally:
            sys.argv = previous_argv
        return 0
    return run([sys.executable, str(script(script_name)), *args])


def _job_runner_active() -> bool:
    import jobs  # noqa: PLC0415

    return jobs.writer_token_is_live(
        os.environ.get("LIFEHUG_JOB_RUNNER_TOKEN"),
        vault_root=REPO_DIR,
    )


def _queue_and_wait(command: str, payload: dict, *, identity: str | None = None) -> int:
    """Run a mutation through the local durable worker and wait for truth.

    ``identity`` opts into stable dedup (issue #119's sweep, e.g.
    ``conversation-close:<session_id>``) — omitted, every call is a fresh
    request even when its payload happens to match (unchanged default).
    """
    import jobs  # noqa: PLC0415

    jobs.configure(REPO_DIR)
    try:
        record = jobs.enqueue(command, payload, identity=identity)
        print(f"Queued {command} job {record['id']}")
        record = jobs.wait_for_job_embedded_safe(record["id"])
    except (TimeoutError, ValueError) as exc:
        print(f"Error: local job could not complete ({exc})", file=sys.stderr)
        return 1
    if record["state"] == "succeeded":
        print(f"✓ {command} job succeeded")
        return 0
    print(
        f"Error: {command} job failed ({record.get('failure_code', 'command_failed')}); "
        f"payload retained locally: {str(record.get('payload_retained', False)).lower()}",
        file=sys.stderr,
    )
    return int(record.get("exit_code") or 1)


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


def _safe_autocommit(label: str = "Lifehug", *, message: str | None = None) -> None:
    """Commit and push vault-tracked paths. Non-fatal on failure.

    ``message`` overrides the default ``"{label} {date}"`` shape when a
    caller needs an exact commit message — issue #119's one-commit-per-close
    granularity uses ``"Conversation close <session_id>"`` verbatim, no date
    suffix (the session id already carries a timestamp). Any git failure is
    recorded to the learning-failure log (the compile_and_commit.sh idiom):
    the commit and the filed content are never lost, only the push.
    """
    try:
        from vault_paths import tracked_vault_paths
        # Fix (issue #119): this called a name — ``git_paths`` — that has
        # never existed in vault_paths.py; the ImportError was silently
        # swallowed by the bare except below, so EVERY caller of
        # ``_safe_autocommit`` (ingest-story's own autocommit, and now this
        # PR's one-commit-per-close) no-op'd instead of committing.
        # ``tracked_vault_paths`` is the real, contract-derived authority
        # (the same one ``vault_paths.py git-paths`` and
        # ``compile_and_commit.sh`` already use).
        paths = tracked_vault_paths(REPO_DIR)
    except Exception:
        return
    existing = [p for p in paths if Path(p).exists()]
    if not existing:
        return
    from datetime import date
    commit_message = message or f"{label} {date.today().isoformat()}"
    try:
        subprocess.run(["git", "add", "--"] + existing, cwd=REPO_DIR, check=True,
                       capture_output=True, text=True)
        diff = subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=REPO_DIR,
                              capture_output=True)
        if diff.returncode == 0:
            return  # nothing staged
        subprocess.run(["git", "commit", "-m", commit_message],
                       cwd=REPO_DIR, check=True, capture_output=True, text=True)
        subprocess.run(["git", "pull", "--rebase", "--autostash"],
                       cwd=REPO_DIR, check=True, capture_output=True, text=True)
        subprocess.run(["git", "push"], cwd=REPO_DIR, check=True,
                       capture_output=True, text=True)
    except (FileNotFoundError, subprocess.CalledProcessError) as exc:
        detail = (f"{exc.stdout or ''}{exc.stderr or ''}".strip()
                  if isinstance(exc, subprocess.CalledProcessError) else str(exc))
        print(f"warn: autocommit failed: {exc}", file=sys.stderr)
        from lifehug_core import record_learning_failure
        record_learning_failure("lifehug_autocommit", "git_commit", detail or str(exc),
                                 context={"label": label})


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
    from ai_provider import provider_status  # noqa: PLC0415

    status = provider_status(probe=True)
    print(f"AI provider: {status.provider}")
    print(f"AI model: {status.model}")
    readiness = "ready" if status.ready else "not ready"
    print(f"AI readiness: {readiness} — {status.detail}")
    if not status.ready:
        print("keyless — agent-task mode required (see skills/maintenance)")
    return 0 if status.ready else 1


def cmd_next(_args: argparse.Namespace) -> int:
    return run_python("ask.py", ["--dry-run"])


def cmd_compile(args: argparse.Namespace) -> int:
    if (not _job_runner_active() and not args.dry_run
            and not getattr(args, "emit_tasks", None)):
        payload = {"no_ai": bool(args.no_ai)}
        if args.model:
            payload["model"] = args.model
        return _queue_and_wait("compile", payload)
    flags = []
    if args.dry_run:
        flags.append("--dry-run")
    if args.no_ai:
        flags.append("--no-ai")
    if args.model:
        flags.extend(["--model", args.model])
    if getattr(args, "emit_tasks", None):
        flags.extend(["--emit-tasks", args.emit_tasks])
    if not _job_runner_active() and not args.dry_run:
        import jobs  # noqa: PLC0415

        with jobs.writer_session(REPO_DIR):
            return run_python("wiki_compile.py", flags)
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


def cmd_source_filenames_repair(args: argparse.Namespace) -> int:
    flags = ["repair-linked-filenames"]
    if args.dry_run:
        flags.append("--dry-run")
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
    rc = run_python("ingest_story.py", flags)
    if rc == 0 and not args.dry_run and getattr(args, "commit", False):
        _safe_autocommit("Ingest story")
    return rc


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


def cmd_candidates_promotion_receipt(args: argparse.Namespace) -> int:
    import candidate_promotion
    try:
        proposal = None
        decision = None
        if args.question_candidate_binding_stdin:
            raw = sys.stdin.read(1_000_001)
            proposal, decision = candidate_promotion.parse_question_candidate_bindings(
                raw
            )
        request = candidate_promotion.build_revision_bound_request(
            args.candidate_id, args.category,
            candidate_revision=args.candidate_revision,
            category_revision=args.category_revision,
            placement_revision=args.placement_revision,
            source_revision=args.source_revision,
            proposal_revision=args.proposal_revision,
            decision_revision=args.decision_revision,
            proposal=proposal,
            decision=decision,
            vault_root=REPO_DIR,
        )
        receipt = candidate_promotion.resolve_candidate_promotion(
            request,
            vault_root=REPO_DIR,
            promotion_mode="manual",
            push=True,
            proposal=proposal,
            decision=decision,
        )
    except candidate_promotion.CandidatePromotionError as exc:
        print(f"candidate-promotion: {exc}", file=sys.stderr)
        return 2
    print(candidate_promotion.canonical_receipt_json(receipt))
    return 0


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


def cmd_book_assemble(args: argparse.Namespace) -> int:
    """Compose a book-project Focus's drafted chapters into one manuscript
    artifact under outputs/. A mutation (writes/versions an artifact), so it
    goes through the durable job queue like other mutations (see
    cmd_artifact); when the worker re-invokes the CLI under its writer token
    (_job_runner_active / LIFEHUG_JOB_RUNNER_TOKEN) it calls
    studio.assemble_book directly instead of re-queueing."""
    if not _job_runner_active():
        payload: dict[str, object] = {"focus": args.focus}
        if args.force:
            payload["force"] = True
        return _queue_and_wait("artifact-assemble", payload)
    import studio  # noqa: PLC0415

    try:
        result = studio.assemble_book(args.focus, force=bool(args.force))
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    print(f"Assembled outputs/{result['slug']} v{result['version']} "
          f"({result['chapters_included']} chapter(s) drafted, "
          f"{result['chapters_placeholder']} placeholder(s), "
          f"{result['words']:,} words)")
    print(f"  {result['path']}")
    return 0


def cmd_quality_stats(_args: argparse.Namespace) -> int:
    return run_python("quality_profile.py", ["--show"])


def cmd_quality_update(_args: argparse.Namespace) -> int:
    return run_python("quality_profile.py", ["--update"])


def cmd_judgment_update(args: argparse.Namespace) -> int:
    flags: list[str] = []
    if getattr(args, "dry_run", False):
        flags.append("--dry-run")
    if getattr(args, "emit_task", None):
        flags.extend(["--emit-task", args.emit_task])
    if getattr(args, "from_response", None):
        flags.extend(["--from-response", args.from_response])
    if getattr(args, "recalibrate", False):
        flags.append("--recalibrate")
    if getattr(args, "model", None):
        flags.extend(["--model", args.model])
    return run_python("question_judgment.py", flags)


def cmd_focus_curate(args: argparse.Namespace) -> int:
    flags: list[str] = []
    if getattr(args, "dry_run", False):
        flags.append("--dry-run")
    if getattr(args, "emit_task", None):
        flags.extend(["--emit-task", args.emit_task])
    if getattr(args, "from_response", None):
        flags.extend(["--from-response", args.from_response])
    if getattr(args, "model", None):
        flags.extend(["--model", args.model])
    return run_python("focus_curation.py", flags)


def cmd_second_voice_ack(args: argparse.Namespace) -> int:
    from question_planner import acknowledge_second_voice_offer  # noqa: PLC0415
    if acknowledge_second_voice_offer(args.key):
        print(f"✓ Acknowledged second-voice offer: {args.key}")
        return 0
    print(f"No pending offer with key: {args.key}", file=sys.stderr)
    return 1


def cmd_timeline_retire(args: argparse.Namespace) -> int:
    import timeline  # noqa: PLC0415
    retired = timeline.retire_redundant_placements(dry_run=args.dry_run)
    if not retired:
        print("No caught-up pins to retire.")
        return 0
    verb = "would retire" if args.dry_run else "Retired"
    print(f"✓ {verb} {len(retired)} pin(s) — the loop caught up, they place themselves:")
    for pin in retired:
        line = f"  📌 {pin.get('description', '?')} → {pin.get('period', '?')}"
        if pin.get("correction"):
            line += f" (assertion remains: {pin['correction']})"
        print(line)
    return 0


def cmd_timeline_place(args: argparse.Namespace) -> int:
    """File the owner's date assertion, then persist its display placement."""
    import re as _re

    import chronology  # noqa: PLC0415
    import timeline  # noqa: PLC0415

    description = sys.stdin.read().strip()
    if not description:
        print("Error: timeline description must be provided on stdin", file=sys.stderr)
        return 1
    period_label = next(
        (period["name"] for period in timeline.load_periods() if period["slug"] == args.period),
        args.period.replace("-", " ").title(),
    )
    # v195 (ADR 0024): the placement can carry a real date record. The filed
    # correction — the DURABLE half; the pin is only display — says the date in
    # words, so the archive reads "happened around 1984 (you said you were about
    # five)" rather than only naming an era.
    record = None
    if getattr(args, "date", None):
        record = chronology.parse_edtf(args.date, basis=(args.basis or "stated"))
        if record is None:
            print(f"Error: --date is not a date I can read: {args.date!r}", file=sys.stderr)
            return 1
        basis = args.basis or record.basis
        if basis not in chronology.BASES:
            print(f"Error: --basis must be one of {', '.join(chronology.BASES)}",
                  file=sys.stderr)
            return 1
        from dataclasses import replace as _replace  # noqa: PLC0415

        record = _replace(record, basis=basis,
                          anchors=tuple(getattr(args, "anchor", None) or ()))
    assertion = f"“{description[:120]}” happened during {period_label}"
    if record is not None:
        assertion += f", {chronology.display_date(record, with_basis=False)}"
        if record.anchors:
            assertion += f" (anchored on {', '.join(record.anchors)})"
    if args.when_hint:
        assertion += f", {args.when_hint}"
    result = subprocess.run(
        [sys.executable, str(script("source_integrity.py")), "correct", args.source,
         "--kind", "date", "--source", "fix"],
        input=assertion,
        text=True,
        capture_output=True,
        cwd=REPO_DIR,
    )
    if result.returncode != 0:
        print("Error: timeline assertion could not be filed", file=sys.stderr)
        return result.returncode
    output = (result.stdout or "") + (result.stderr or "")
    match = _re.search(r"correction source: (\S+)", output)
    # v215 (lifehug#228): identity is MINTED where the moment is known and
    # travels whole. `--placement-key` is that key, stored verbatim, so a host
    # whose description is a title (a timeline unknown's label) still files
    # under the key `place_events` joins on. Absent the flag the key is derived
    # from source + description exactly as it always has been — the viewer's
    # placement form posts the event's real description and needs nothing else.
    key = str(getattr(args, "placement_key", "") or "").strip()
    if key and not _re.fullmatch(r"[0-9a-f]{12}", key):
        print(f"Error: --placement-key must be 12 hex characters: {key!r}", file=sys.stderr)
        return 1
    key = key or timeline.placement_key({"source": args.source, "description": description})
    timeline.save_placement(
        key,
        args.source,
        description,
        args.period,
        when_hint=args.when_hint or "",
        note=args.note or "",
        correction=match.group(1) if match else "",
        date=record,
    )
    dated = f" ({chronology.display_date(record, with_basis=False)})" if record is not None else ""
    print(f"✓ Placed {key} in {period_label}{dated}; durable assertion filed")
    return 0


def cmd_timeline_unplace(args: argparse.Namespace) -> int:
    import timeline  # noqa: PLC0415

    record = next(
        (row for row in timeline.load_placements()["placements"] if row.get("key") == args.key),
        None,
    )
    if not timeline.remove_placement(args.key):
        print("Error: no such placement", file=sys.stderr)
        return 1
    message = "✓ Placement removed; heuristics apply again"
    if record and record.get("correction"):
        message += f" (filed assertion remains: {record['correction']})"
    print(message)
    return 0


def cmd_timeline_move(args: argparse.Namespace) -> int:
    """Move a node: file the weakest truthful ordering constraint, then republish.

    The whole of the drag transaction that belongs to the vault (plan §8.4 steps
    4 and 7). What it deliberately does NOT do is invent a date: `after`,
    `before`, `between` and `within` are the only four things a move may say,
    and the explanation is optional prose on stdin — the move stands without it.
    """
    import temporal_store  # noqa: PLC0415
    import timeline  # noqa: PLC0415
    from temporal_claims import TemporalContractError  # noqa: PLC0415

    reason = "" if sys.stdin.isatty() else sys.stdin.read().strip()
    try:
        constraint = temporal_store.file_ordering_constraint(
            REPO_DIR,
            relation=args.relation,
            subject_node_id=args.node,
            anchor_node_ids=args.anchor,
            reason=reason or None,
            supersedes_constraint_id=args.supersedes,
            subject_label=args.label,
            anchor_labels=args.anchor_label,
            author=args.author,
        )
    except TemporalContractError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    summary = timeline.publish_calculated_timeline(REPO_DIR)
    print(f"✓ {constraint['reason']}")
    print(f"  constraint: {constraint['constraint_id']}")
    print(f"  source: {constraint['relative_path']}")
    print(f"  projection generation {summary['generation']}")
    return 0


def cmd_timeline_move_undo(args: argparse.Namespace) -> int:
    """Undo a move — mark it retracted, keep every byte of it, republish."""
    import temporal_store  # noqa: PLC0415
    import timeline  # noqa: PLC0415
    from temporal_claims import TemporalContractError  # noqa: PLC0415

    reason = "" if sys.stdin.isatty() else sys.stdin.read().strip()
    try:
        correction = temporal_store.retract_ordering_constraint(
            REPO_DIR,
            args.constraint_id,
            reason=reason or "Undone on the timeline.",
            author=args.author,
        )
    except TemporalContractError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    summary = timeline.publish_calculated_timeline(REPO_DIR)
    print(f"✓ Move {args.constraint_id} undone; its record remains")
    print(f"  correction: {correction.relative_path}")
    print(f"  projection generation {summary['generation']}")
    return 0


def cmd_era_record(args: argparse.Namespace) -> int:
    """`era-record` — one JSON payload on stdin, one act, one summary.

    Deliberately stdin rather than twenty flags: the payload is a nested
    document (a list of claim drafts, a list of memberships) and flattening it
    into an argv would invent a second serialization of shapes the substrate
    already has one of.
    """
    import json  # noqa: PLC0415

    import era_record  # noqa: PLC0415
    from temporal_claims import TemporalContractError  # noqa: PLC0415

    raw = "" if sys.stdin.isatty() else sys.stdin.read()
    try:
        payload = json.loads(raw or "{}")
    except ValueError as exc:
        print(f"Error: era-record reads one JSON payload on stdin ({exc})",
              file=sys.stderr)
        return 1
    try:
        summary = era_record.record_era(REPO_DIR, payload)
    except TemporalContractError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    if getattr(args, "json", False):
        print(json.dumps(summary, indent=2, sort_keys=True, default=str))
    else:
        print("\n".join(era_record.describe(summary)))
    return 0


def cmd_era_list(args: argparse.Namespace) -> int:
    """Every era this vault holds, folded from its own records."""
    import json  # noqa: PLC0415

    import era_identity  # noqa: PLC0415

    views = era_identity.era_views(REPO_DIR)
    if getattr(args, "json", False):
        print(json.dumps(views, indent=2, sort_keys=True, default=str))
        return 0
    if not views:
        print("No eras yet.")
        return 0
    for era_id, view in views.items():
        aliases = ", ".join(view.get("aliases") or ())
        print(f"{era_id}  {view.get('label') or '(unnamed)'}"
              f"  [{view.get('era_kind') or 'kind undecided'}]"
              f"{'  aka ' + aliases if aliases else ''}"
              f"{'  origin ' + view['origin'] if view.get('origin') else ''}")
    return 0


def cmd_era_migrate(args: argparse.Namespace) -> int:
    """Migrate the legacy roster periods to era identities (§4.1)."""
    import era_identity  # noqa: PLC0415
    from entity_roster import load_roster  # noqa: PLC0415

    report = era_identity.migrate_legacy_periods(
        REPO_DIR,
        roster_snapshot=[load_roster("period")],
        batch=args.batch or era_identity.DEFAULT_MIGRATION_BATCH,
        dry_run=not args.apply,
    )
    print("\n".join(era_identity.describe_migration(report)))
    return 0


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


def cmd_artifact_readiness(argv: list[str]) -> int:
    """`lifehug.py artifact readiness --format letter --subject Mom` (v126).

    READ-ONLY: it inspects the question bank against a format framework and
    prints, so it neither enqueues an artifact job nor takes the writer lock —
    it dispatches like `roadmap`/`progress`, in-process. Always exits 0; this
    is an informational view, and a missing subject is a nudge, not a failure.
    """
    import compose  # noqa: PLC0415
    import format_readiness  # noqa: PLC0415

    parser = argparse.ArgumentParser(
        prog="lifehug.py artifact readiness",
        description="Show how much material exists for a format before drafting it",
    )
    parser.add_argument("--format", default="letter",
                        help="Format framework to score against (default: letter)")
    parser.add_argument("--subject", help="Focus subject, e.g. Mom — resolved to its category")
    parser.add_argument("--categories", help="Explicit category letters, e.g. K or K,L")
    args = parser.parse_args(argv)

    if not args.subject and not args.categories:
        print("Nothing to score: pass --subject <focus> or --categories <letters>.")
        return 0

    try:
        categories, _resolved = compose.resolve_categories(args.subject, args.categories)
    except SystemExit:
        # resolve_categories already explained the problem on stderr; this
        # view stays exit-0 so a shell loop over focuses never aborts.
        return 0

    questions = parse_questions(QUESTIONS_FILE.read_text(encoding="utf-8")) \
        if QUESTIONS_FILE.exists() else []
    return format_readiness.print_readiness(args.format, categories, questions)


def cmd_artifact(args: argparse.Namespace) -> int:
    artifact_args = ["--help"] if getattr(args, "artifact_help", False) else (args.artifact_args or ["--help"])
    # Read-only artifact views run in-process: no job queue, no writer lock.
    if artifact_args[0] == "readiness":
        return cmd_artifact_readiness(artifact_args[1:])
    if not _job_runner_active() and artifact_args[0] in {
        "new", "save", "revise", "final", "promote-source", "delivered",
    }:
        import artifact as artifact_mod  # noqa: PLC0415

        parsed = artifact_mod.build_parser().parse_args(artifact_args)

        def ref(value: str) -> str:
            return value if value.startswith("outputs/") else f"outputs/{value}"

        if parsed.command == "new" and not parsed.print_prompt:
            payload = {"format": parsed.format, "force": bool(parsed.force)}
            for key in (
                "subject", "occasion", "date", "title", "audience", "privacy",
                "categories", "seed",
            ):
                value = getattr(parsed, key, None)
                if value:
                    payload[key] = value
            return _queue_and_wait("artifact-new", payload)
        if parsed.command == "save":
            return _queue_and_wait("artifact-save", {
                "ref": ref(parsed.output),
                "content": sys.stdin.read(),
                "model": parsed.model,
                "note": parsed.feedback,
                "final": bool(parsed.final),
            })
        if parsed.command == "revise":
            payload = {"ref": ref(parsed.output), "feedback": parsed.feedback}
            if parsed.model:
                payload["model"] = parsed.model
            return _queue_and_wait("artifact-revise", payload)
        if parsed.command == "final":
            return _queue_and_wait("artifact-final", {
                "ref": ref(parsed.output), "version": parsed.version,
            })
        if parsed.command == "promote-source":
            return _queue_and_wait("artifact-promote", {
                "ref": ref(parsed.output), "kind": parsed.kind,
                "version": parsed.version, "source": parsed.source,
            })
        if parsed.command == "delivered":
            payload = {"ref": ref(parsed.output)}
            for key in ("to", "note", "reaction"):
                value = getattr(parsed, key, None)
                if value:
                    payload[key] = value
            return _queue_and_wait("artifact-delivered", payload)
    if not _job_runner_active() and artifact_args[0] != "--help":
        import jobs  # noqa: PLC0415

        with jobs.writer_session(REPO_DIR):
            return run_python("artifact.py", artifact_args)
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
    for name in ("tier", "phase", "objective", "deliverable", "label", "relationship"):
        val = getattr(args, name, None)
        if val is not None:
            flags.extend([f"--{name}", val])
    # focus-onboarding-context (v189): --type is `focus_type` on this side to
    # avoid colliding with argparse's own `type=`; --living/--not-living is a
    # tri-state (None = leave it alone).
    if getattr(args, "focus_type", None):
        flags.extend(["--type", args.focus_type])
    if getattr(args, "living", None) is True:
        flags.append("--living")
    elif getattr(args, "living", None) is False:
        flags.append("--not-living")
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
    if getattr(args, "context_file", None):
        flags.extend(["--context-file", args.context_file])
    return run_python("roadmap.py", flags)


def cmd_serve(args: argparse.Namespace) -> int:
    return run_python("serve_wiki.py", ["--host", args.host, "--port", str(args.port)])


def cmd_rebuild(_args: argparse.Namespace) -> int:
    return run_python("rebuild_state.py", ["--fix-rotation", "--readme"])


def cmd_process_answer(args: argparse.Namespace) -> int:
    if not _job_runner_active():
        question_id = args.question_id or (read_json(ROTATION_FILE, default={}) or {}).get(
            "last_question_id", ""
        )
        payload: dict[str, object] = {
            "question_id": question_id,
            "answer": sys.stdin.read(),
            "followups": list(args.followup or []),
            "force": bool(args.force),
            "commit": bool(args.commit),
            "push": bool(args.push),
            "no_compile_wiki": bool(args.no_compile_wiki),
        }
        for key in ("source", "answered_date", "asked_date", "summary", "sensitivity"):
            value = getattr(args, key, None)
            if value:
                payload[key] = value
        return _queue_and_wait("process-answer", payload)
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


def cmd_answer_ack_prompt(_args: argparse.Namespace) -> int:
    return run_python("answer_ack.py", [])


def cmd_answer_ack_status(args: argparse.Namespace) -> int:
    flags = ["status"]
    if args.question_id:
        flags.append(args.question_id)
    return run_python("answer_ack_delivery.py", flags)


def cmd_answer_ack_retry(args: argparse.Namespace) -> int:
    flags = ["retry", args.question_id]
    if args.confirm_not_sent:
        flags.append("--confirm-not-sent")
    return run_python("answer_ack_delivery.py", flags)


def cmd_arc_plan(args: argparse.Namespace) -> int:
    flags = ["plan"]
    if args.limit is not None:
        flags += ["--limit", str(args.limit)]
    if args.gap_max is not None:
        flags += ["--gap-max", str(args.gap_max)]
    if getattr(args, "model", None):
        flags += ["--model", args.model]
    if getattr(args, "dry_run", False):
        flags.append("--dry-run")
    if getattr(args, "emit_tasks", None):
        flags += ["--emit-tasks", args.emit_tasks]
    if getattr(args, "from_response", None):
        flags += ["--from-response", args.from_response]
    if getattr(args, "force", False):
        flags.append("--force")
    return run_python("arc_planner.py", flags)


def cmd_arc_card(args: argparse.Namespace) -> int:
    flags = ["card", args.question_id]
    if getattr(args, "daily_text", False):
        flags.append("--daily-text")
    return run_python("arc_planner.py", flags)


def cmd_arc_thread_offers(args: argparse.Namespace) -> int:
    flags = ["thread-offers"]
    if args.limit is not None:
        flags += ["--limit", str(args.limit)]
    if getattr(args, "dry_run", False):
        flags.append("--dry-run")
    return run_python("arc_planner.py", flags)


def cmd_conversation_open(args: argparse.Namespace) -> int:
    flags = ["open", "--mode", args.mode, "--channel", args.channel]
    if args.question_id:
        flags += ["--question-id", args.question_id]
    return run_python("conversation.py", flags)


def cmd_conversation_status(args: argparse.Namespace) -> int:
    # v153 (issue #116): upgraded IN PLACE to the turn engine's status, which
    # prints the same session summary PLUS the delivery ledger (mirrors
    # answer-ack-status). conversation.py's own `status` stays available for
    # store-only inspection.
    flags = ["status"]
    if args.session_id:
        flags.append(args.session_id)
    if args.full:
        flags.append("--full")
    return run_python("conversation_delivery.py", flags)


def cmd_conversation_record_turn(args: argparse.Namespace) -> int:
    flags = [
        "record-turn", args.session_id,
        "--role", args.role,
        "--expected-turns", str(args.expected_turns),
    ]
    if args.channel:
        flags += ["--channel", args.channel]
    return run_python("conversation.py", flags)


def _file_mirror_responses(session: dict) -> None:
    """Session -> ``state/mirror_responses.json`` (issue #119, §4). Best
    effort — filing never blocks a close that has already delivered."""
    from lifehug_core import now_utc, record_learning_failure

    session_id = str(session.get("session_id") or "")
    try:
        import mirror  # noqa: PLC0415

        extracted = session.get("extracted") or {}
        raw = extracted.get("mirror_responses") if isinstance(extracted, dict) else None
        if not isinstance(raw, list) or not raw:
            return
        payload = []
        for item in raw:
            if isinstance(item, dict):
                text, tension_ref = item.get("text"), item.get("tension_ref")
            elif isinstance(item, str):
                text, tension_ref = item, None
            else:
                continue
            if not isinstance(text, str) or not text.strip():
                continue
            payload.append({
                "session_id": session_id,
                "text": text,
                "tension_ref": tension_ref if isinstance(tension_ref, str) else "",
                "responded_at": now_utc(),
            })
        if payload:
            mirror.append_mirror_responses(payload)
    except Exception as exc:  # noqa: BLE001 — filing is best-effort
        record_learning_failure("conversation_close", "mirror_filing", exc,
                                 context={"session_id": session_id})


def _file_engagement_timing(session: dict) -> None:
    """``unprompted_inbound`` (issue #119, §5) — the one engagement field
    that needs the session doc's own ``mode`` and so is filed at close, not
    at answer time (``time_to_answer_hours`` files at answer time in
    ``process_answer.py``, session or not). MERGES into whatever
    ``conversation_delivery.append_engagement`` already wrote for these
    question ids, via ``quality_profile.merge_engagement``."""
    from lifehug_core import record_learning_failure

    session_id = str(session.get("session_id") or "")
    filed = (session.get("close") or {}).get("filed") or []
    if not filed:
        return
    unprompted_inbound = session.get("mode") == "conversation"
    try:
        import quality_profile  # noqa: PLC0415

        for question_id in filed:
            quality_profile.merge_engagement(
                str(question_id), {"unprompted_inbound": unprompted_inbound}
            )
    except Exception as exc:  # noqa: BLE001 — instrumentation is best-effort
        record_learning_failure("conversation_close", "engagement_timing", exc,
                                 context={"session_id": session_id})


def _load_session_document(session_id: str) -> dict | None:
    """Read one session doc straight off disk (metadata-shaped, this
    module's own tracked-data-path idiom — the same one every other CLI
    handler here uses for ITS OWN files). Deliberately NOT
    ``conversation.load_session``: lifehug.py's command handlers stay
    dispatch-string callers of the store (tests/test_v150_conversation_store
    .py's NoBehaviorChangeGuardTests), never direct importers of its CRUD."""
    from vault_paths import vault_data_path

    path = vault_data_path("conversations", vault_root=REPO_DIR) / f"{session_id}.json"
    return read_json(path, default=None)


def _finish_conversation_close(session_id: str) -> int:
    """§2 steps b-d, after PR3's own close already ran: file the Mirror
    inbound + engagement timing this contract owns (candidate_ideas,
    entity_hints, and the session-turn engagement fields are already PR3's
    — pass-through, not re-implemented here), compile the wiki ONCE, then
    ONE git commit — the batch boundary #119 exists for."""
    from lifehug_core import record_learning_failure

    session = _load_session_document(session_id)
    if not isinstance(session, dict):
        # The close itself already succeeded (this runs only after it did);
        # a reload failure only costs the filing/compile/commit steps.
        record_learning_failure("conversation_close", "reload_after_close", "session unreadable",
                                 context={"session_id": session_id})
        return 0

    _file_mirror_responses(session)
    _file_engagement_timing(session)

    compile_rc = run_python("wiki_compile.py", [])
    if compile_rc != 0:
        record_learning_failure("conversation_close", "wiki_compile", f"exit {compile_rc}",
                                 context={"session_id": session_id})
        # Don't remove the sentinel — the next hourly compile retries, same
        # idiom as compile_and_commit.sh. State writes above still commit.
    else:
        from lifehug_core import COMPILE_NEEDED_FILE
        COMPILE_NEEDED_FILE.unlink(missing_ok=True)

    _safe_autocommit(message=f"Conversation close {session_id}")
    return 0


def _enqueue_expired_conversation_closes() -> int:
    """#116's deterministic idle-sweep discovery, upgraded (issue #119): find
    every open session past its idle timeout and ENQUEUE one durable
    ``conversation-close`` job per session (identity
    ``conversation-close:<session_id>`` dedupes retries) rather than closing
    synchronously in the calling — often cron — process. Discovery here is
    deterministic and AI-free; the actual close (which may call AI for the
    takeaway) runs on the job worker. Waits for each job so a vault whose
    only pending work is an expired session still closes it before this
    returns (the compile_and_commit.sh pre-step's contract).

    ``conversation_delivery`` is a sanctioned exception to the
    dispatch-string rule above: it is the store's OTHER exempt consumer
    (tests/test_v150_conversation_store.py), and its
    ``find_expired_open_sessions`` is the single authoritative idle-timeout
    calculation (mode-dependent knobs, last-activity math) — duplicating
    that here would be exactly the recurring-defect doctrine's "same
    defect twice" pattern this codebase has already paid for once.
    """
    import conversation_delivery  # noqa: PLC0415

    expired_ids = conversation_delivery.find_expired_open_sessions(vault_root=REPO_DIR)
    outcomes: list[tuple[str, bool]] = []
    for session_id in expired_ids:
        rc = _queue_and_wait(
            "conversation-close",
            {"session_id": session_id, "reason": "idle_timeout"},
            identity=f"conversation-close:{session_id}",
        )
        outcomes.append((session_id, rc == 0))
    if not outcomes:
        print("No expired conversation sessions.")
        return 0
    for session_id, ok in outcomes:
        print(f"{session_id}: {'closed' if ok else 'close job failed'}")
    return 0 if all(ok for _sid, ok in outcomes) else 1


def _enqueue_day_rollover_conversation_closes(*, dry_run: bool = False) -> int:
    """Day rollover (design §D, Chats-per-Focus, 2026-08-12): close EVERY
    open session, not just idle-expired ones — the day owns the surface, no
    timer. Same enqueue-durable-job discovery/wait shape as
    ``_enqueue_expired_conversation_closes`` above (deliberately mirrored:
    ``daily_question.sh`` calls this pre-question, exactly as
    ``compile_and_commit.sh`` calls the idle sweep pre-compile), reason
    ``day_rollover`` instead of ``idle_timeout``. Shares the SAME job
    identity (``conversation-close:<session_id>``) as the idle sweep — a
    session that is both janitor-expired and rolled over only ever gets one
    close job, deduped.

    ``--dry-run`` (the daily script's ``LIFEHUG_DAILY_DRY_RUN`` preview)
    lists what WOULD close without enqueuing or mutating anything —
    deterministic, AI-free, one line regardless of vault state.
    """
    import conversation_delivery  # noqa: PLC0415

    session_ids = conversation_delivery.find_open_sessions(vault_root=REPO_DIR)
    if not session_ids:
        print(
            "DRY RUN: no open conversation sessions for day rollover."
            if dry_run else
            "No open conversation sessions for day rollover."
        )
        return 0
    if dry_run:
        print(
            f"DRY RUN: day rollover would close {len(session_ids)} open "
            f"session(s): {', '.join(session_ids)}"
        )
        return 0
    outcomes: list[tuple[str, bool]] = []
    for session_id in session_ids:
        rc = _queue_and_wait(
            "conversation-close",
            {"session_id": session_id, "reason": "day_rollover"},
            identity=f"conversation-close:{session_id}",
        )
        outcomes.append((session_id, rc == 0))
    for session_id, ok in outcomes:
        print(f"{session_id}: {'closed' if ok else 'close job failed'}")
    return 0 if all(ok for _sid, ok in outcomes) else 1


def cmd_conversation_close(args: argparse.Namespace) -> int:
    # v153 (issue #116): the same subcommand now closes for real — closing
    # takeaway when the session earned one, silence when it did not.
    # v156 (issue #119): the single-session path is now the FULL close
    # orchestration — PR3's close, then this PR's filing (Mirror inbound,
    # engagement timing), one wiki compile, one commit. --expired stays
    # #116's idle-sweep entry point, upgraded to ENQUEUE a durable job per
    # session (deterministic, AI-free discovery) rather than closing inline.
    # --day-rollover (design §D, 2026-08-12): the daily flow's pre-question
    # step, same enqueue shape as --expired, no idle filter.
    if args.day_rollover:
        return _enqueue_day_rollover_conversation_closes(dry_run=args.dry_run)
    if args.expired:
        return _enqueue_expired_conversation_closes()
    flags = ["close", args.session_id, "--reason", args.reason]
    rc = run_python("conversation_delivery.py", flags)
    if rc != 0:
        return rc
    return _finish_conversation_close(args.session_id)


def cmd_conversation_turn_retry(args: argparse.Namespace) -> int:
    flags = ["turn-retry", args.session_id, str(args.turn_index)]
    if args.confirm_not_sent:
        flags.append("--confirm-not-sent")
    return run_python("conversation_delivery.py", flags)


def cmd_conversation_turn_prompt(_args: argparse.Namespace) -> int:
    return run_python("conversation.py", ["turn-prompt"])


def cmd_conversation_router_prompt(_args: argparse.Namespace) -> int:
    return run_python("conversation.py", ["router-prompt"])


def cmd_question_candidate_prompt(_args: argparse.Namespace) -> int:
    return run_python("question_candidate.py", ["prompt"])


def cmd_focus_candidate_prompt(args: argparse.Namespace) -> int:
    return run_python(
        "focus_candidate.py", ["prompt", "--candidate-id", args.candidate_id]
    )


def cmd_focus_candidate_complete(args: argparse.Namespace) -> int:
    flags = ["complete", "--candidate-id", args.candidate_id, "--json"]
    if args.no_push:
        flags.append("--no-push")
    return run_python("focus_candidate.py", flags)


def cmd_entity_candidate_prompt(args: argparse.Namespace) -> int:
    return run_python(
        "entity_candidate.py", ["prompt", "--candidate-id", args.candidate_id]
    )


def cmd_entity_candidate_complete(args: argparse.Namespace) -> int:
    flags = ["complete", "--candidate-id", args.candidate_id, "--json"]
    if args.no_push:
        flags.append("--no-push")
    return run_python("entity_candidate.py", flags)


def cmd_conversation_arc_prompt(_args: argparse.Namespace) -> int:
    return run_python("conversation.py", ["arc-prompt"])


def cmd_conversation_closing_prompt(_args: argparse.Namespace) -> int:
    return run_python("conversation.py", ["closing-prompt"])


def cmd_conversation_lint(args: argparse.Namespace) -> int:
    flags = ["--reply-to-substantive"] if args.reply_to_substantive else []
    return run_python("conversation_lints.py", flags)


def cmd_route(_args: argparse.Namespace) -> int:
    # Issue #117: a direct in-process call (not run_python), like
    # cmd_ai_status — the point of route_message's injectable ai_call is
    # testability, which a subprocess dispatch would throw away. Exit 0 on
    # any successful classification, including the deterministic default;
    # a non-zero exit is reserved for invalid (empty) stdin.
    #
    # Stdin accepts EITHER shape: the structured JSON object from the
    # contract ({"text": ..., "channel": ...}) when the caller needs to
    # pick a channel, or plain free text otherwise (the common case — most
    # inbound messages are not valid JSON, and the contract's own smoke
    # test pipes plain text). A JSON payload only takes effect when it
    # parses to an object with a string "text" field; anything else
    # (unparseable, a bare string/number, a dict without "text") is read as
    # the literal message text.
    raw = sys.stdin.read()
    if not raw.strip():
        print("Error: empty stdin — expected message text or a JSON payload", file=sys.stderr)
        return 1
    text = raw.strip()
    channel = "cli"
    threads = None
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        payload = None
    if isinstance(payload, dict) and isinstance(payload.get("text"), str):
        text = payload["text"]
        channel = payload.get("channel") or "cli"
        if channel not in ("telegram", "web", "cli"):
            print(f"Error: invalid channel: {channel!r}", file=sys.stderr)
            return 1
        # issue #169 / ADR 0017 (thread binder, additive): an optional
        # bounded roster of candidate threads, passed straight through to
        # route_message. Absent (the common case) leaves routing exactly
        # as it was pre-#169.
        raw_threads = payload.get("threads")
        if isinstance(raw_threads, list) and raw_threads:
            threads = raw_threads

    from conversation_delivery import route_message  # noqa: PLC0415

    result = route_message(text, channel=channel, threads=threads)
    print(json.dumps(result))
    return 0


def cmd_conversation_evals(args: argparse.Namespace) -> int:
    flags = ["--emit-tasks"] if getattr(args, "emit_tasks", False) else []
    return run_python("interaction_evals.py", flags)


def cmd_question_candidate_evals(_args: argparse.Namespace) -> int:
    return run_python("question_candidate_evals.py", [])


def cmd_focus_candidate_evals(args: argparse.Namespace) -> int:
    flags = ["--json"] if args.json else []
    if args.live:
        flags.append("--live")
    return run_python("focus_candidate_evals.py", flags)


def cmd_entity_candidate_evals(args: argparse.Namespace) -> int:
    flags = ["--json"] if args.json else []
    if args.live:
        flags.append("--live")
    return run_python("entity_candidate_evals.py", flags)


def cmd_arc_walk_evals(args: argparse.Namespace) -> int:
    flags = ["--json"] if args.json else []
    if args.live:
        flags.append("--live")
    return run_python("arc_walk_evals.py", flags)


def cmd_timeline_evals(args: argparse.Namespace) -> int:
    flags = ["--json"] if args.json else []
    if args.live:
        flags.append("--live")
    return run_python("timeline_evals.py", flags)


def cmd_landmarks_evals(args: argparse.Namespace) -> int:
    flags = ["--json"] if args.json else []
    if args.live:
        flags.append("--live")
    return run_python("landmarks_evals.py", flags)


def cmd_reading_room_evals(args: argparse.Namespace) -> int:
    flags = ["--json"] if args.json else []
    if args.live:
        flags.append("--live")
    return run_python("reading_room_evals.py", flags)


def cmd_reading_room_plan(args: argparse.Namespace) -> int:
    flags = ["--json"] if args.json else []
    if args.k:
        flags += ["--k", str(args.k)]
    return run_python("reading_room.py", flags)


def cmd_landmark_record(args: argparse.Namespace) -> int:
    """File one landmark answer (v197). The only writer for the landmark set."""
    import chronology as _chrono  # noqa: PLC0415
    import landmarks_interaction as _li  # noqa: PLC0415
    import timeline as _timeline  # noqa: PLC0415

    try:
        row = _li.domain_row(args.domain)
    except _li.LandmarkInteractionError as exc:
        print(f"error: {exc}")
        return 1
    record: dict = {"domain": row["domain"]}
    if args.label:
        record["label"] = args.label
    for field in ("place", "subject", "birth_order"):
        value = getattr(args, field, None)
        if value:
            record[field] = value
    for rung in row["ladder"]:
        value = getattr(args, rung.replace("-", "_"), None)
        if isinstance(value, bool) or value:
            record[rung] = value
    # v222 (B4): the date arrives WHOLE or not at all. Every one of these
    # three records used to be rebuilt with `basis="stated"` and an empty
    # provenance, so a date the system calculated from an age was filed as one
    # the person had stated — `chronology.claim_score` then paid it +2.0 it
    # had not earned. `chronology.date_from_argv` honors what the CALLER
    # declared on `--basis`/`--anchor`/`--provenance` and only falls back to
    # `stated` when nothing was declared at all, which is the one honest
    # reading of a person typing `--date 1984` at a terminal. Machine callers
    # go through `landmarks_interaction.landmark_invocation`, which always
    # declares.
    for bound, given, prefix in (("date", args.date, ""),
                                 ("start", args.start, "start_"),
                                 ("end", args.end, "end_")):
        try:
            parsed = _chrono.date_from_argv(
                given,
                basis=getattr(args, f"{prefix}basis", None),
                granularity=getattr(args, f"{prefix}granularity", None),
                confidence=getattr(args, f"{prefix}confidence", None),
                anchors=getattr(args, f"{prefix}anchor", None) or (),
                provenance=getattr(args, f"{prefix}provenance", None) or (),
            )
        except _chrono.ChronologyError as exc:
            print(f"error: --{bound}: {exc}")
            return 1
        if parsed is None:
            continue
        if bound == "date":
            record["date"] = parsed.to_dict()
        else:
            record.setdefault("span", {})[bound] = parsed.to_dict()
    if args.complete:
        record["chain_complete"] = True
    if getattr(args, "none", False):
        if not _li.domain_accepts_none(row):
            print(f"error: {row['domain']} cannot be answered 'none' — "
                  f"its ladder opens at {row['ladder'][0]!r}, not "
                  f"{_li.NONE_OPENER!r}")
            return 1
        record["none"] = True
    validated = _li.validate_landmark(record)
    if validated is None:
        print("error: nothing to record")
        return 1
    saved = _timeline.save_landmark(validated["domain"], validated)
    if saved.get("none"):
        print(f"recorded {validated['domain']}: none — the domain is complete")
        return 0
    print(f"recorded {validated['domain']}: "
          f"{saved.get('label') or _li.rung_reached(saved, row) or 'noted'}")
    return 0


def cmd_arc_plan_target(args: argparse.Namespace) -> int:
    # v195 (ADR 0024): `--timeline` plans over timeline UNKNOWNS, not bank
    # questions, so it dispatches to the timeline plan builder rather than
    # widening `arc_walk.ARC_TARGET_KINDS` (contract deviation 3).
    # v197 (landmarks): `--landmarks` walks the OPEN landmark rows as an
    # episode — the same dispatch shape `--timeline` uses.
    if getattr(args, "landmarks", False):
        flags = []
        if args.episode_size is not None:
            flags.extend(["--limit", str(args.episode_size)])
        if args.json:
            flags.append("--json")
        return run_python("landmarks_interaction.py", flags)
    if getattr(args, "timeline", False):
        flags = []
        if getattr(args, "era", None):
            flags.extend(["--era", str(args.era)])
        if args.episode_size is not None:
            flags.extend(["--limit", str(args.episode_size)])
        if args.json:
            flags.append("--json")
        return run_python("timeline_interaction.py", flags)
    flags: list[str] = []
    for name in ("focus", "category", "chapter", "book"):
        value = getattr(args, name, None)
        if value:
            flags.extend([f"--{name}", str(value)])
    if getattr(args, "queue", False):
        flags.append("--queue")
    if args.episode_size is not None:
        flags.extend(["--episode-size", str(args.episode_size)])
    if args.json:
        flags.append("--json")
    return run_python("arc_walk.py", flags)


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
    if getattr(args, "context_file", None):
        flags.extend(["--context-file", args.context_file])
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


def cmd_focus_autopilot(args: argparse.Namespace) -> int:
    flags = ["--autopilot"]
    if args.target is not None:
        flags.extend(["--target", str(args.target)])
    if args.catch_up:
        flags.append("--catch-up")
    if args.dry_run:
        flags.append("--dry-run")
    return run_python("recommend_focuses.py", flags)


def cmd_focus_dupes(args: argparse.Namespace) -> int:
    flags = ["--json"] if args.json else ["--report"]
    return run_python("focus_dupes.py", flags)


def cmd_focus_merge(args: argparse.Namespace) -> int:
    flags = [args.survivor, args.loser]
    if getattr(args, "dry_run", False):
        flags.append("--dry-run")
    if getattr(args, "adopt_target", False):
        flags.append("--adopt-target")
    if getattr(args, "json", False):
        flags.append("--json")
    return run_python("focus_merge.py", flags)


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


def cmd_entity_verdict(args: argparse.Namespace) -> int:
    flags = [args.type, args.slug, args.verdict]
    # entity-identity-context (v190): graduation and the identity the Play
    # conversation learned arrive in ONE call (Design §E).
    for alias in args.alias or []:
        flags.extend(["--alias", alias])
    if args.relationship:
        flags.extend(["--relationship", args.relationship])
    if args.living is True:
        flags.append("--living")
    elif args.living is False:
        flags.append("--not-living")
    # v217 (person dates): born/died ride the SAME single call — one writer
    # for one roster file stays one writer.
    for flag in ("born", "born_basis", "died", "died_basis"):
        value = getattr(args, flag, None)
        if value:
            flags.extend([f"--{flag.replace('_', '-')}", str(value)])
    if args.maps_to:
        flags.extend(["--maps-to", args.maps_to])
    # v202 (family-landmark §D): a person the FAMILY landmark set named may
    # have no roster row yet — `--ensure` creates one holding only the identity
    # facts (never page-eligible). `landmarks_interaction.
    # family_roster_invocations` mints exactly this vector.
    if getattr(args, "name", None):
        flags.extend(["--name", args.name])
    if getattr(args, "ensure", False):
        flags.append("--ensure")
    if args.json:
        flags.append("--json")
    return run_python("entity_verdict.py", flags)


def cmd_focus_recommend_from_entity(args: argparse.Namespace) -> int:
    """entity-identity-context (v190, Design §F): the ONLY entity -> focus
    hand-off seam. Appends one pending recommendation row; creates no Focus."""
    flags = ["--from-entity", args.type, args.slug]
    if args.json:
        flags.append("--json")
    return run_python("recommend_focuses.py", flags)


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


def cmd_connector_auth(args: argparse.Namespace) -> int:
    return run_python("connector.py", ["auth", args.connector])


def cmd_connector_fetch(args: argparse.Namespace) -> int:
    flags = ["fetch", args.connector]
    if args.probe:
        flags.append("--probe")
        flags.extend(["--per-window", str(args.per_window)])
    if args.limit is not None:
        flags.extend(["--limit", str(args.limit)])
    return run_python("connector.py", flags)


def cmd_connector_excavate(args: argparse.Namespace) -> int:
    flags = ["excavate", args.connector]
    if args.dry_run:
        flags.append("--dry-run")
    if args.cap is not None:
        flags.extend(["--cap", str(args.cap)])
    return run_python("connector.py", flags)


def cmd_connector_dossier(args: argparse.Namespace) -> int:
    flags = ["dossier", args.connector]
    if args.limit is not None:
        flags.extend(["--limit", str(args.limit)])
    if args.model:
        flags.extend(["--model", args.model])
    if args.redossier:
        flags.append("--redossier")
    if args.dry_run:
        flags.append("--dry-run")
    return run_python("connector.py", flags)


def cmd_connector_report(args: argparse.Namespace) -> int:
    return run_python("connector.py", ["report", args.connector])


def cmd_connector_audit(args: argparse.Namespace) -> int:
    return run_python("connector.py", ["audit", args.connector])


def cmd_connector_calibrate(args: argparse.Namespace) -> int:
    flags = ["calibrate", args.connector]
    if args.set_threshold is not None:
        flags.extend(["--set-threshold", str(args.set_threshold)])
    return run_python("connector.py", flags)


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
    queue_data = read_json(QUESTION_QUEUE_FILE, default=None)
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
    cand_data = read_json(QUESTION_CANDIDATES_FILE, default=None) or {}
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
    profile = read_json(QUALITY_PROFILE_FILE, default=None) or {}
    weekly_age = _days_since(profile.get("computed_at") or profile.get("last_updated") or profile.get("updated_at") or "")
    if weekly_age is None:
        warn("weekly cadence unknown", "quality profile has never been updated — has weekly_maintenance.sh ever run?")
    elif weekly_age > 9:
        warn("weekly cadence stalled", f"quality profile last updated {weekly_age:.0f} days ago (expected ~7)")
    else:
        check("weekly cadence", True, f"quality profile updated {weekly_age:.0f}d ago")

    roster = read_json(ENTITY_ROSTERS_DIR / "person.json", default=None) or {}
    monthly_age = _days_since(roster.get("resolved_at", ""))
    if monthly_age is not None and monthly_age > 35:
        warn("monthly cadence stalled", f"person roster last resolved {monthly_age:.0f} days ago (expected ~30)")
    elif monthly_age is not None:
        check("monthly cadence", True, f"person roster resolved {monthly_age:.0f}d ago")

    # Roster continuity — an empty roster is how the Jul-2026 regression looked.
    for etype in ("person", "place", "period", "object", "theme"):
        data = read_json(ENTITY_ROSTERS_DIR / f"{etype}.json", default=None)
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

    # Classification coverage — the learning loop starves without it. v237:
    # current / stale / unclassified are reported SEPARATELY, because a stale
    # classification is withheld from every derived reader and folding it into
    # one total hid exactly the hole the owner needed to see.
    import classify_story as _cs  # noqa: PLC0415

    counts = _cs.classification_counts()
    classified = counts["current"]
    answers = len(list(ANSWERS_DIR.glob("*.md"))) if ANSWERS_DIR.exists() else 0
    if answers and not classified:
        warn("no sources classified", f"{answers} answers, 0 current classifications — the learning loop has never run")
    elif answers:
        check("classification coverage", True,
              f"{classified} current / {counts['stale']} stale / "
              f"{counts['unclassified']} unclassified")
    if counts["stale"]:
        warn(f"{counts['stale']} classification(s) {_cs.WITHHELD_STALE_REASON}",
             "run: lifehug classify-story --classify-all --unclassified --stale-first")

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

    ack_state = read_json(STATE_DIR / "answer_acknowledgments.json", default={}) or {}
    ack_entries = ack_state.get("entries", {}) if isinstance(ack_state, dict) else {}
    ambiguous_acks = [
        source_id
        for source_id, entry in ack_entries.items()
        if isinstance(entry, dict) and entry.get("status") == "ambiguous"
    ]
    if ambiguous_acks:
        warn(
            "ambiguous answer acknowledgments",
            f"{len(ambiguous_acks)} need Telegram verification; run answer-ack-status",
        )
    else:
        check("ambiguous answer acknowledgments", True, "none")

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
    parser.add_argument(
        "--vault-root",
        type=Path,
        default=REPO_DIR,
        help="Data-only vault root (overrides LIFEHUG_VAULT_ROOT)",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("status", help="Show coverage and pass status")
    p.set_defaults(func=cmd_status)

    p = sub.add_parser(
        "ai-status",
        help="Report provider/model/readiness; exit 1 when agent-task mode is required",
    )
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

    p = sub.add_parser(
        "source-filenames-repair",
        help="Migrate legacy correction/retraction filenames and state references",
    )
    p.add_argument("--dry-run", action="store_true", help="Preview changes without writing")
    p.set_defaults(func=cmd_source_filenames_repair)

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
    p.add_argument("--commit", action="store_true", help="Git commit and push after ingesting")
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

    p = sub.add_parser("candidates-promotion-receipt",
                       help="Promote exact revisions and return a canonical JSON receipt")
    p.add_argument("candidate_id")
    p.add_argument("--category", required=True)
    p.add_argument("--candidate-revision", required=True)
    p.add_argument("--category-revision", required=True)
    p.add_argument("--placement-revision", required=True)
    p.add_argument("--source-revision")
    p.add_argument("--proposal-revision")
    p.add_argument("--decision-revision")
    p.add_argument("--question-candidate-binding-stdin", action="store_true")
    p.add_argument("--json", action="store_true", required=True)
    p.set_defaults(func=cmd_candidates_promotion_receipt)

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
    p.add_argument("--context-file", metavar="PATH",
                   help="Onboarding-context JSON to ground the generated questions (v189)")
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

    p = sub.add_parser("focus-dupes",
                       help="Report duplicate/near-duplicate Focuses and pending ideas "
                            "(deterministic, zero AI, zero writes)")
    p.add_argument("--report", action="store_true", help="Print the damage list (default)")
    p.add_argument("--json", action="store_true", help="Print the damage list as JSON")
    p.set_defaults(func=cmd_focus_dupes)

    p = sub.add_parser("focus-merge",
                       help="Merge one Focus into another — an auditable multi-file "
                            "transaction that heals a duplicate pair (ADR 0012)")
    p.add_argument("survivor", help="The Focus id that survives and absorbs")
    p.add_argument("loser", help="The Focus id that is absorbed and dropped")
    p.add_argument("--dry-run", action="store_true", help="Print the full plan and write nothing")
    p.add_argument("--adopt-target", action="store_true",
                   help="Raise the survivor's target_depth to max(survivor, loser)")
    p.add_argument("--json", action="store_true", help="Print the result as JSON")
    p.set_defaults(func=cmd_focus_merge)

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

    p = sub.add_parser("entity-verdict",
                       help="Owner override for one roster entity's graduation — "
                            "graduate now, never a page, or clear back to automatic (ADR 0013)")
    p.add_argument("type", choices=["person", "place", "period", "object", "theme"])
    p.add_argument("slug", help="The roster entity's slug (state/entity_rosters/<type>.json)")
    p.add_argument("verdict", choices=["graduate", "never", "clear"])
    p.add_argument("--alias", action="append", default=[], metavar="NAME",
                   help="Another name this entity goes by (repeatable)")
    p.add_argument("--relationship", metavar="R",
                   help="How this person is related to the author")
    _living = p.add_mutually_exclusive_group()
    _living.add_argument("--living", dest="living", action="store_true", default=None,
                         help="This person is still living")
    _living.add_argument("--not-living", dest="living", action="store_false",
                         help="This person is no longer living")
    # v217 (person dates): the two most common datable facts in a life story.
    p.add_argument("--born", metavar="EDTF",
                   help="When this person was born (EDTF or a human form)")
    p.add_argument("--born-basis", dest="born_basis", metavar="B",
                   help="How the birth date was arrived at (chronology.BASES; default stated)")
    p.add_argument("--died", metavar="EDTF",
                   help="When this person died (same date forms as --born)")
    p.add_argument("--died-basis", dest="died_basis", metavar="B",
                   help="How the death date was arrived at (chronology.BASES; default stated)")
    p.add_argument("--maps-to", dest="maps_to", metavar="SLUG",
                   help="This entity is really that existing page — wins over graduate")
    p.add_argument("--ensure", action="store_true",
                   help="Create the roster entry when the slug is unknown, rather "
                        "than refusing — for a person a LANDMARK named (v202). "
                        "Never page-eligible on creation.")
    p.add_argument("--name", metavar="NAME",
                   help="With --ensure: the person's name on the created entry")
    p.add_argument("--json", action="store_true", help="Print the result as JSON")
    p.set_defaults(func=cmd_entity_verdict)

    p = sub.add_parser("focus-recommend-from-entity",
                       help="Append ONE pending Focus recommendation for a graduated "
                            "roster entity — the entity -> focus hand-off. Creates no Focus.")
    p.add_argument("type", choices=["person", "place", "period", "object", "theme"])
    p.add_argument("slug", help="The roster entity's slug")
    p.add_argument("--json", action="store_true", help="Print the result as JSON")
    p.set_defaults(func=cmd_focus_recommend_from_entity)

    p = sub.add_parser("focus-approve", help="Approve a Focus recommendation")
    p.add_argument("approve", metavar="REC_ID")
    p.set_defaults(func=cmd_focus_action, dismiss=None, reason=None)

    p = sub.add_parser("focus-dismiss", help="Dismiss a Focus recommendation")
    p.add_argument("dismiss", metavar="REC_ID")
    p.add_argument("--reason", default="")
    p.set_defaults(func=cmd_focus_action, approve=None)

    p = sub.add_parser("focus-autopilot",
                       help="Convergence Principle floor (ADR 0011): auto-approve the top Focus "
                            "idea when the developing set is thinner than target")
    p.add_argument("--dry-run", action="store_true", help="Preview the decision; write nothing")
    p.add_argument("--target", type=int, default=None, help="Override the developing-set target")
    p.add_argument("--catch-up", action="store_true",
                   help="Fill to target in one run instead of the gentle 1/run cap")
    p.set_defaults(func=cmd_focus_autopilot)

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

    # --- Connectors (calibrated external-evidence ingestion, v106) ---
    p = sub.add_parser("connector-auth", help="One-time OAuth consent for a connector (gmail.readonly only)")
    p.add_argument("connector", choices=["gmail"])
    p.set_defaults(func=cmd_connector_auth)

    p = sub.add_parser("connector-fetch", help="Append new connector metadata to the permanent ledger")
    p.add_argument("connector", choices=["gmail"])
    p.add_argument("--probe", action="store_true",
                   help="Phase 0: stratified sample + probe report only (no ledger, no bodies)")
    p.add_argument("--per-window", type=int, default=50, help="Probe sample size per era window")
    p.add_argument("--limit", type=int, default=None, help="Max messages to list this fetch")
    p.set_defaults(func=cmd_connector_fetch)

    p = sub.add_parser("connector-excavate",
                       help="Re-score the whole ledger against the current wiki/rosters/sources and delta-promote")
    p.add_argument("connector", choices=["gmail"])
    p.add_argument("--dry-run", action="store_true", help="Report what would promote; write nothing")
    p.add_argument("--cap", type=int, default=None, help="Max threads promoted this run (default 25)")
    p.set_defaults(func=cmd_connector_excavate)

    p = sub.add_parser("connector-dossier",
                       help="AI correspondent dossiers (v108): classify top unclassified correspondents; "
                            "family-class verdicts auto-apply as VIPs during scoring")
    p.add_argument("connector", choices=["gmail"])
    p.add_argument("--limit", type=int, default=None, help="Max correspondents dossiered this run (default 30)")
    p.add_argument("--model", default=None, metavar="M", help="Model override (else config.yaml classify_model)")
    p.add_argument("--redossier", action="store_true", help="Re-classify even fresh dossiers")
    p.add_argument("--dry-run", action="store_true", help="Show who would be dossiered; no fetches or AI calls")
    p.set_defaults(func=cmd_connector_dossier)

    p = sub.add_parser("connector-report", help="Connector ledger summary: volume, span, bands, threshold")
    p.add_argument("connector", choices=["gmail"])
    p.set_defaults(func=cmd_connector_report)

    p = sub.add_parser("connector-audit", help="List auto-promoted connector sources with scores, newest first")
    p.add_argument("connector", choices=["gmail"])
    p.set_defaults(func=cmd_connector_audit)

    p = sub.add_parser("connector-calibrate",
                       help="Phase 2 shadow report: score distribution, bands at thresholds "
                            "0.5/0.6/0.7/0.8, examples with reasons, discovery preview")
    p.add_argument("connector", choices=["gmail"])
    p.add_argument("--set-threshold", type=float, default=None, metavar="X",
                   help="Record the chosen promote threshold in state/connectors/weights.json")
    p.set_defaults(func=cmd_connector_calibrate)

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

    p = sub.add_parser("book-assemble", help="Assemble a book-project Focus's drafted chapters into one manuscript artifact")
    p.add_argument("--focus", required=True, help="Book Focus id or slug (e.g. 'my-life' or 'etherfuse')")
    p.add_argument("--force", action="store_true", help="Write a new version even if the manuscript is unchanged")
    p.set_defaults(func=cmd_book_assemble)

    p = sub.add_parser("quality-stats", help="Show answer quality profile")
    p.set_defaults(func=cmd_quality_stats)

    p = sub.add_parser("quality-update", help="Recompute quality profile from answer scores")
    p.set_defaults(func=cmd_quality_update)

    p = sub.add_parser("judgment-update",
                       help="Weekly question-judgment RUBRIC-EDIT: owner decisions -> at most one bounded, "
                            "evidence-cited amendment to state/question_judgment/learned.md")
    p.add_argument("--dry-run", action="store_true", help="Preview the delta and prompt without writing")
    p.add_argument("--emit-task", metavar="PATH",
                   help="Keyless: emit the rubric-edit prompt for agent completion")
    p.add_argument("--from-response", metavar="PATH",
                   help="Apply an agent-written rubric-edit response (no model call)")
    p.add_argument("--recalibrate", action="store_true",
                   help="Full decision-ledger context instead of the weekly delta (quarterly, manual only)")
    p.add_argument("--model", help="AI model override for the rubric-edit call")
    p.set_defaults(func=cmd_judgment_update)

    p = sub.add_parser("focus-curate",
                       help="Curate first-encounter Focus/idea duplicate variants "
                            "(interactions/focus_curation/) — merges/maps pending ideas the "
                            "door guards and roster fold couldn't resolve deterministically")
    p.add_argument("--dry-run", action="store_true", help="Preview the pending ideas and prompt without writing")
    p.add_argument("--emit-task", metavar="PATH",
                   help="Keyless: emit the curation prompt for agent completion")
    p.add_argument("--from-response", metavar="PATH",
                   help="Apply an agent-written CURATE verdict (no model call)")
    p.add_argument("--model", help="AI model override for the CURATE call")
    p.set_defaults(func=cmd_focus_curate)

    p = sub.add_parser("second-voice-ack", help="Acknowledge a second-voice offer (hides the home card)")
    p.add_argument("key", help="The offer key from state/second_voice_offers.json")
    p.set_defaults(func=cmd_second_voice_ack)

    p = sub.add_parser("timeline-retire",
                       help="Retire manual timeline pins the loop has caught up with (classification now places them)")
    p.add_argument("--dry-run", action="store_true", help="Preview without writing")
    p.set_defaults(func=cmd_timeline_retire)

    p = sub.add_parser("timeline-place",
                       help="Place a timeline moment and file its date assertion (description on stdin)")
    p.add_argument("source", help="Raw source reference")
    p.add_argument("--period", required=True, help="Timeline period slug")
    p.add_argument("--when-hint")
    p.add_argument("--note")
    p.add_argument("--date", help="EDTF date for this moment (1984~, 198X, 2001-21, 1984/..)")
    p.add_argument("--basis", help="How the date was arrived at: "
                                   "stated|age|anchor|order|public_event|connector")
    p.add_argument("--anchor", action="append", default=[],
                   help="Landmark key the date leans on (repeatable)")
    p.add_argument("--placement-key", dest="placement_key",
                   help="The moment's own 12-hex placement key, when the caller "
                        "knows it (identity travels whole; derived otherwise)")
    p.set_defaults(func=cmd_timeline_place)

    p = sub.add_parser("timeline-unplace",
                       help="Remove a manual timeline placement (filed assertion remains)")
    p.add_argument("key", help="12-character content placement key")
    p.set_defaults(func=cmd_timeline_unplace)

    p = sub.add_parser("timeline-move",
                       help="Move a node in the calculated timeline (explanation optional, on stdin)")
    p.add_argument("node", help="The calculated node id being moved")
    p.add_argument("--relation", required=True, choices=["before", "after", "between", "within"],
                   help="The weakest truthful thing the gesture says")
    p.add_argument("--anchor", action="append", default=[], required=True,
                   help="Anchor node id (repeatable; two for --relation between)")
    p.add_argument("--label", help="Display name for the moved node (prose only)")
    p.add_argument("--anchor-label", dest="anchor_label", action="append", default=[],
                   help="Display name for an anchor, in --anchor order (prose only)")
    p.add_argument("--supersedes", help="Constraint id this move replaces (amendment or redo)")
    p.add_argument("--author", help="Who moved it (source_medium; default owner)")
    p.set_defaults(func=cmd_timeline_move)

    p = sub.add_parser("timeline-move-undo",
                       help="Undo a filed move; its record and evidence remain (reason on stdin)")
    p.add_argument("constraint_id", help="The constraint id the move returned")
    p.add_argument("--author", help="Who undid it (source_medium; default owner)")
    p.set_defaults(func=cmd_timeline_move_undo)

    p = sub.add_parser("era-record",
                       help="Create/name/date an era in ONE act (JSON payload on stdin)")
    p.add_argument("--json", action="store_true", help="Print the summary as JSON")
    p.set_defaults(func=cmd_era_record)

    p = sub.add_parser("era-list", help="List this vault's eras and their labels")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_era_list)

    p = sub.add_parser("era-migrate",
                       help="Migrate legacy roster periods to era identities "
                            "(dry run unless --apply)")
    p.add_argument("--batch", default=None,
                   help="Migration batch label; part of every migrated era's "
                        "identity, so re-running the SAME batch writes nothing")
    p.add_argument("--apply", action="store_true", help="Actually write")
    p.set_defaults(func=cmd_era_migrate)

    p = sub.add_parser("mirror-compile",
                       help="Synthesize wiki/self/mirror.md from classifier contradictions/insights/positions")
    p.add_argument("--model", help="AI model override")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--emit-task", metavar="DIR",
                   help="Keyless: emit the synthesis prompt for agent completion")
    p.add_argument("--from-response", metavar="PATH",
                   help="Ingest an agent-written markdown body and write the page")
    p.set_defaults(func=cmd_mirror_compile)

    p = sub.add_parser("artifact",
                       help="Create occasion artifacts, promote final works as sources, and "
                            "check format readiness (`artifact readiness --format letter --subject Mom`)",
                       add_help=False)
    p.add_argument("-h", "--help", dest="artifact_help", action="store_true")
    p.add_argument("artifact_args", nargs=argparse.REMAINDER)
    p.set_defaults(func=cmd_artifact)

    p = sub.add_parser("roadmap", help="Show the roadmap of Focuses with live fill")
    p.set_defaults(func=cmd_roadmap)

    p = sub.add_parser("roadmap-rebuild", help="Derive/refresh the roadmap from the question bank")
    p.set_defaults(func=cmd_roadmap_rebuild)

    p = sub.add_parser("focus-new", help="Create a Focus end-to-end: scaffold category, register, seed questions")
    p.add_argument("label")
    p.add_argument("--type", default="theme", choices=list(FOCUS_TYPES))
    p.add_argument("--tier", default="standard", choices=["basic", "standard", "extreme"])
    p.add_argument("--objective", default="")
    p.add_argument("--deliverable", default="chapter")
    p.add_argument("--no-generate", action="store_true")
    p.add_argument("--context-file", metavar="PATH",
                   help="Onboarding-context JSON to ground the seeded questions (v189)")
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
    # focus-onboarding-context (v189, Design §E.4): what the onboarding
    # conversation can change about a scaffolded focus.
    p.add_argument("--label")
    p.add_argument("--type", dest="focus_type", choices=list(FOCUS_TYPES))
    p.add_argument("--relationship", choices=list(FOCUS_RELATIONSHIPS))
    living = p.add_mutually_exclusive_group()
    living.add_argument("--living", dest="living", action="store_true", default=None)
    living.add_argument("--not-living", dest="living", action="store_false", default=None)
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

    p = sub.add_parser("answer-ack-prompt",
                       help="Print the warm answer-acknowledgment prompt (stdin: question/answer JSON)")
    p.set_defaults(func=cmd_answer_ack_prompt)

    p = sub.add_parser("answer-ack-status",
                       help="Show metadata-only acknowledgment delivery status")
    p.add_argument("question_id", nargs="?")
    p.set_defaults(func=cmd_answer_ack_status)

    p = sub.add_parser("answer-ack-retry",
                       help="Retry a definitively unsent answer acknowledgment")
    p.add_argument("question_id")
    p.add_argument(
        "--confirm-not-sent",
        action="store_true",
        help="Retry an ambiguous send only after checking that Telegram did not receive it",
    )
    p.set_defaults(func=cmd_answer_ack_retry)

    # Issue #118 (Wave 2): the weekly arc planner, the daily attach, and the
    # monthly conversation-thread offers.
    p = sub.add_parser("arc-plan", help="Plan one arc card per queued question (weekly)")
    p.add_argument("--limit", type=int, default=None, help="Plan at most N queued questions")
    p.add_argument("--gap-max", type=int, default=None,
                   help="Max gap intents (timeline_gap + place_no_stories, one budget) across the week (default 3)")
    p.add_argument("--model", help="AI model override (config arc_plan_model → classify_model)")
    p.add_argument("--dry-run", action="store_true", help="Print the plan; write nothing")
    p.add_argument("--emit-tasks", metavar="DIR",
                   help="Keyless: write deterministic cards and emit the prompt for agent completion")
    p.add_argument("--from-response", metavar="PATH",
                   help="Ingest an agent-written response; upgrades cards in place")
    p.add_argument("--force", action="store_true",
                   help="Replan model-planned cards for the same queue")
    p.set_defaults(func=cmd_arc_plan)

    p = sub.add_parser("arc-card", help="Read one live arc card (pure read; --daily-text for the daily attach)")
    p.add_argument("question_id")
    p.add_argument("--daily-text", action="store_true",
                   help="Print the assembled daily message for a live card, else nothing")
    p.set_defaults(func=cmd_arc_card)

    p = sub.add_parser("arc-thread-offers", help="Monthly conversation-thread offers for ready neighborhoods")
    p.add_argument("--limit", type=int, default=None, help="Max offers this month (default 1)")
    p.add_argument("--dry-run", action="store_true")
    p.set_defaults(func=cmd_arc_thread_offers)

    p = sub.add_parser("conversation-open", help="Open a new conversation session; prints its id and document path")
    p.add_argument("--mode", required=True, choices=["chat", "conversation"])
    p.add_argument("--channel", required=True, choices=["telegram", "web", "cli"])
    p.add_argument("--question-id", default=None, help="Attach the arc card for this question, if one exists")
    p.set_defaults(func=cmd_conversation_open)

    p = sub.add_parser("conversation-status", help="Metadata-only conversation session list/detail")
    p.add_argument("session_id", nargs="?")
    p.add_argument("--full", action="store_true", help="Also print turn text (private content)")
    p.set_defaults(func=cmd_conversation_status)

    p = sub.add_parser("conversation-record-turn", help="CAS-append one conversation turn; text on stdin")
    p.add_argument("session_id")
    p.add_argument("--role", required=True, choices=["user", "lifehug"])
    p.add_argument("--channel", default=None, choices=["telegram", "web", "cli"])
    p.add_argument("--expected-turns", required=True, type=int)
    p.set_defaults(func=cmd_conversation_record_turn)

    p = sub.add_parser("conversation-close",
                       help="Close one conversation session now, sweep the janitor, or roll over the day")
    p.add_argument("session_id", nargs="?")
    p.add_argument("--expired", action="store_true",
                   help="Close every session past the janitor threshold (36h-class safety net)")
    p.add_argument("--day-rollover", action="store_true",
                   help="Close every open session regardless of idle age (design §D day rollover)")
    p.add_argument("--dry-run", action="store_true",
                   help="With --day-rollover: list sessions that would close, without closing them")
    p.add_argument("--reason", default="done",
                   choices=["done", "idle_timeout", "exit_taken", "day_rollover"])
    p.set_defaults(func=cmd_conversation_close)

    p = sub.add_parser("conversation-turn-retry", help="Retry a definitively unsent conversation turn")
    p.add_argument("session_id")
    p.add_argument("turn_index", type=int)
    p.add_argument("--confirm-not-sent", action="store_true",
                   help="Retry an ambiguous send only after checking that Telegram did not receive it")
    p.set_defaults(func=cmd_conversation_turn_retry)

    p = sub.add_parser("conversation-turn-prompt", help="stdin JSON -> the conversation turn prompt")
    p.set_defaults(func=cmd_conversation_turn_prompt)

    p = sub.add_parser("conversation-router-prompt", help="stdin JSON -> the conversation router prompt")
    p.set_defaults(func=cmd_conversation_router_prompt)

    p = sub.add_parser(
        "question-candidate-prompt",
        help="stdin QuestionCandidateInput JSON -> the composed read-only prompt",
    )
    p.set_defaults(func=cmd_question_candidate_prompt)

    p = sub.add_parser(
        "focus-candidate-prompt",
        help="stdin research state -> the composed read-only Focus Candidate prompt",
    )
    p.add_argument("--candidate-id", required=True)
    p.set_defaults(func=cmd_focus_candidate_prompt)

    p = sub.add_parser(
        "focus-candidate-complete",
        help="complete confirmed Focus Candidate research; never approves",
    )
    p.add_argument("--candidate-id", required=True)
    p.add_argument("--no-push", action="store_true")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_focus_candidate_complete)

    p = sub.add_parser("entity-candidate-prompt", help="stdin research state -> Entity Candidate prompt")
    p.add_argument("--candidate-id", required=True)
    p.set_defaults(func=cmd_entity_candidate_prompt)

    p = sub.add_parser("entity-candidate-complete", help="complete confirmed Entity Candidate research; never graduates")
    p.add_argument("--candidate-id", required=True)
    p.add_argument("--no-push", action="store_true")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_entity_candidate_complete)

    p = sub.add_parser("conversation-arc-prompt", help="stdin JSON -> the arc-card planning prompt")
    p.set_defaults(func=cmd_conversation_arc_prompt)

    p = sub.add_parser("conversation-closing-prompt", help="stdin JSON -> the closing-takeaway prompt")
    p.set_defaults(func=cmd_conversation_closing_prompt)

    p = sub.add_parser("conversation-lint", help="Print deterministic lint findings for stdin turn text")
    p.add_argument("--reply-to-substantive", action="store_true")
    p.set_defaults(func=cmd_conversation_lint)

    p = sub.add_parser(
        "conversation-evals",
        help="Run the Conversation Interaction eval harness (issue #120): "
             "lints + router fixtures + golden properties + judge/persona (keyless-skippable)",
    )
    p.add_argument("--emit-tasks", action="store_true",
                   help="Also write judge/persona agent-task prompts to state/agent_tasks/evals/")
    p.set_defaults(func=cmd_conversation_evals)

    p = sub.add_parser(
        "question-candidate-evals",
        help="Run the independent Question Candidate Interaction eval harness",
    )
    p.set_defaults(func=cmd_question_candidate_evals)

    p = sub.add_parser(
        "focus-candidate-evals",
        help="Run the independent Focus Candidate Interaction eval harness",
    )
    p.add_argument("--live", action="store_true")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_focus_candidate_evals)

    p = sub.add_parser("entity-candidate-evals", help="Run Entity Candidate evals")
    p.add_argument("--live", action="store_true")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_entity_candidate_evals)

    p = sub.add_parser("arc-walk-evals", help="Run Arc Walk evals")
    p.add_argument("--live", action="store_true")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_arc_walk_evals)

    p = sub.add_parser("timeline-evals", help="Run Timeline Interaction evals")
    p.add_argument("--live", action="store_true")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_timeline_evals)

    p = sub.add_parser("landmarks-evals", help="Run Landmarks Interaction evals")
    p.add_argument("--live", action="store_true")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_landmarks_evals)

    p = sub.add_parser("reading-room-evals", help="Run Reading Room Interaction evals")
    p.add_argument("--live", action="store_true")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_reading_room_evals)

    p = sub.add_parser("reading-room-plan",
                       help="Print the Reading Room plan and the dig lists")
    p.add_argument("--json", action="store_true")
    p.add_argument("--k", type=int, default=0,
                   help="how many asks (default: the interaction's own k)")
    p.set_defaults(func=cmd_reading_room_plan)

    p = sub.add_parser("landmark-record",
                       help="File one landmark answer (the always-present dating set)")
    p.add_argument("domain", help="landmark domain (birth, residences, schools, …)")
    p.add_argument("--label", default="", help="what this landmark is called")
    p.add_argument("--place", default="")
    p.add_argument("--subject", default="")
    p.add_argument("--date", default="", help="EDTF date for a point landmark")
    p.add_argument("--start", default="", help="EDTF start of a span")
    p.add_argument("--end", default="", help="EDTF end of a span")
    # v222 (B4): a date without its warrant is a claim with no evidence, and
    # an undeclared basis used to be silently filed as `stated`. Each of the
    # three dates carries its own — the two ends of a span are two separate
    # claims and are rarely dated the same way.
    for value_flag, prefix in (("date", ""), ("start", "start-"), ("end", "end-")):
        dest = prefix.replace("-", "_")
        # No argparse `choices` on any of the three: `chronology.BASES`,
        # `GRANULARITIES` and `CONFIDENCES` are the ONE closed vocabularies and
        # `chronology.date_from_argv` is the ONE place that checks a value
        # against them — a copy of any list here is exactly the second
        # definition the recurring-defect doctrine forbids.
        p.add_argument(f"--{prefix}basis", dest=f"{dest}basis", default="",
                       help=f"how the --{value_flag} was arrived at, one of "
                            f"chronology.BASES (default: stated — a date you "
                            f"type here is one you are stating)")
        p.add_argument(f"--{prefix}granularity", dest=f"{dest}granularity", default="",
                       help=f"grain of the --{value_flag}, one of "
                            f"chronology.GRANULARITIES (default: read off the date)")
        p.add_argument(f"--{prefix}confidence", dest=f"{dest}confidence", default="",
                       help=f"how firmly the --{value_flag} is held, one of "
                            f"chronology.CONFIDENCES (default: read off the date)")
        p.add_argument(f"--{prefix}anchor", dest=f"{dest}anchor", action="append",
                       default=[], help=f"a landmark the --{value_flag} leaned on "
                                        f"(repeatable)")
        p.add_argument(f"--{prefix}provenance", dest=f"{dest}provenance",
                       action="append", default=[],
                       help=f"one JSON provenance object for the --{value_flag}, "
                            f'e.g. \'{{"claim":"about five","basis":"age"}}\' '
                            f"(repeatable)")
    p.add_argument("--complete", action="store_true",
                   help="the chain is finished — stop offering more of this domain")
    # v202 (family-landmark): birth order is a free-text FIELD, not a rung, so
    # an unstated one never blocks the ladder from reaching `birth`.
    p.add_argument("--birth-order", dest="birth_order", default="",
                   help="e.g. 'two years older', 'the middle of five'")
    # `living` is TRI-STATE: absent is UNKNOWN, and a stated False is a fact.
    living = p.add_mutually_exclusive_group()
    living.add_argument("--living", dest="living", action="store_true", default=None,
                        help="this family member is still with us")
    living.add_argument("--not-living", dest="living", action="store_false",
                        help="this family member has died")
    p.add_argument("--none", action="store_true",
                   help="this never happened (no service, no children) — a "
                        "TERMINAL answer that completes the domain")
    for rung in ("year", "month", "day", "city", "address", "household",
                 "name", "grades", "happened", "who", "what", "where", "branch",
                 "relation"):
        p.add_argument(f"--{rung}", default="", help=f"ladder rung: {rung}")
    p.set_defaults(func=cmd_landmark_record)

    p = sub.add_parser(
        "arc-plan-target",
        help="Plan an arc-walk episode for a Play target (read-only, no writes)",
    )
    group = p.add_mutually_exclusive_group(required=True)
    group.add_argument("--focus", help="focus id or label")
    group.add_argument("--category", help="bank category letter")
    group.add_argument("--chapter", help="bank category letter (a book chapter)")
    group.add_argument("--book", help="focus id or label of a book focus")
    group.add_argument("--queue", action="store_true", help="this week's queue")
    group.add_argument("--timeline", action="store_true",
                       help="this vault's timeline unknowns, by leverage")
    group.add_argument("--landmarks", action="store_true",
                       help="this vault's OPEN landmarks, by ladder cost")
    p.add_argument("--era", help="with --timeline: scope to one period slug")
    p.add_argument("--episode-size", type=int, default=None)
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_arc_plan_target)

    p = sub.add_parser(
        "route",
        help="Classify one inbound message (five-intent router); stdin JSON {text, channel}",
    )
    p.set_defaults(func=cmd_route)

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
    if args.command in DIRECT_MUTATION_COMMANDS and not _job_runner_active():
        import jobs  # noqa: PLC0415

        with jobs.writer_session(REPO_DIR):
            return args.func(args)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
