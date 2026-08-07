#!/usr/bin/env python3
"""Save a Lifehug answer and update derived state."""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from datetime import date, datetime

from lifehug_core import (
    ANSWERS_DIR,
    QUESTIONS_FILE,
    README_FILE,
    REPO_DIR,
    ROTATION_FILE,
    SYSTEM_DIR,
    mark_answered_in_bank,
    parse_categories,
    parse_questions,
    question_by_id,
    read_json,
    record_learning_failure,
    rebuild_coverage,
    write_json,
    write_text,
)
from source_integrity import SCHEMA_VERSION, format_frontmatter, payload_sha256, register_source
from update_readme import update_readme
from vault_paths import vault_relative_path

FOLLOWUP_HEADER = "📖 Lifehug — since you're on a roll"
FOLLOWUP_FOOTER = "(Totally optional — tomorrow's question comes either way)"


def refresh_neighborhood_readiness_safely() -> None:
    """Refresh derived neighborhood lifecycle fields without blocking answer save."""
    try:
        from neighborhoods import refresh_all_neighborhood_readiness  # noqa: PLC0415
        refresh_all_neighborhood_readiness(write=True)
    except Exception as exc:  # noqa: BLE001
        record_learning_failure(
            "process_answer",
            "refresh_neighborhood_readiness",
            exc,
        )


def next_followup_id(md_text: str, source_id: str) -> str:
    existing = re.findall(
        rf"^- \[[ xX]\] ({re.escape(source_id)}[a-z]+):",
        md_text,
        re.MULTILINE,
    )
    if not existing:
        return f"{source_id}a"
    suffixes = [qid[len(source_id):] for qid in existing]
    single_letters = [s for s in suffixes if len(s) == 1 and "a" <= s <= "z"]
    if not single_letters:
        return f"{source_id}a"
    next_ord = ord(max(single_letters)) + 1
    if next_ord > ord("z"):
        raise ValueError(f"too many follow-ups for {source_id}")
    return f"{source_id}{chr(next_ord)}"


def append_followups(question_id: str, followups: list[str]) -> list[tuple[str, str]]:
    if not followups:
        return []
    md = QUESTIONS_FILE.read_text()
    additions = []
    for text in followups:
        clean = text.strip().strip('"')
        if not clean:
            continue
        new_id = next_followup_id(md, question_id)
        additions.append((new_id, clean))
        md += f"\n- [ ] {new_id}: {clean}"

    if not additions:
        return []

    fresh = QUESTIONS_FILE.read_text()
    pattern = re.compile(
        rf"^(## {re.escape(question_id[0])}:.+?(?=\n## |\Z))",
        re.MULTILINE | re.DOTALL,
    )
    match = pattern.search(fresh)
    lines = [f"- [ ] {qid}: {text}" for qid, text in additions]
    if match:
        section = match.group(1).rstrip()
        new_section = section + "\n" + "\n".join(lines) + "\n"
        fresh = fresh[:match.start()] + new_section + fresh[match.end():]
    else:
        fresh = fresh.rstrip() + f"\n\n## {question_id[0]}: Generated\n" + "\n".join(lines) + "\n"
    write_text(QUESTIONS_FILE, fresh)
    return additions


PUSH_ATTEMPTS = 2


def _git(*args: str) -> subprocess.CompletedProcess:
    """Run a git command in the workspace and capture its output (never raises)."""
    return subprocess.run(
        ["git", "-C", str(REPO_DIR), *args],
        capture_output=True,
        text=True,
    )


def _git_output(result: subprocess.CompletedProcess) -> str:
    return f"{result.stdout or ''}{result.stderr or ''}".strip()


def _push_failed(operation: str, result: subprocess.CompletedProcess) -> None:
    """Report a push that never landed — honestly, and without losing the commit."""
    detail = _git_output(result)
    print(
        f"✗ Answer committed locally but NOT pushed ({operation} failed).\n"
        "  Nothing is lost: the commit exists in this workspace and the answer\n"
        "  file is on disk. Another operator pushed to the same vault while this\n"
        "  answer was being filed, and the retry could not replay on top of it.\n"
        "  Recover with:  git pull --rebase --autostash && git push\n"
        "  If rotation.json conflicts, see CLAUDE.md → 'Shared Vault: One Vault,\n"
        "  Many Machines' for the recovery procedure.",
        file=sys.stderr,
    )
    if detail:
        print(detail, file=sys.stderr)
    record_learning_failure(
        "process_answer",
        "git_push",
        detail or f"{operation} exited {result.returncode}",
        exit_code=result.returncode,
        context={"operation": operation},
    )
    raise SystemExit(1)


def git_commit(message: str, push: bool) -> None:
    paths = [
        vault_relative_path(name, vault_root=REPO_DIR, framework_system_dir=SYSTEM_DIR).as_posix()
        for name in (
            "readme",
            "question_bank",
            "rotation",
            "coverage",
            "answers",
            "source_manifest",
            "answer_scores",
            "wiki",
        )
    ]
    existing = [path for path in paths if (REPO_DIR / path).exists()]
    subprocess.run(["git", "-C", str(REPO_DIR), "add", "--", *existing], check=True)
    diff = subprocess.run(["git", "-C", str(REPO_DIR), "diff", "--cached", "--quiet"])
    if diff.returncode == 0:
        return
    subprocess.run(["git", "-C", str(REPO_DIR), "commit", "-m", message], check=True)
    if not push:
        return

    # Discipline 3 of the shared-vault contract: on push rejection, re-pull and
    # retry. The vault may have several writers (this machine, a dev box, a
    # hosted environment), so a non-fast-forward rejection is an ordinary event,
    # not a crash. Rebase onto whatever landed, then push; if the push is
    # rejected again, someone landed a commit inside our own race window, so
    # rebase once more and retry. Past that we stop and say plainly what state
    # the workspace is in — the commit is safe, only the push is missing.
    last: subprocess.CompletedProcess | None = None
    for _ in range(PUSH_ATTEMPTS):
        pull = _git("pull", "--rebase", "--autostash")
        if pull.returncode != 0:
            _push_failed("git pull --rebase --autostash", pull)
        last = _git("push")
        if last.returncode == 0:
            return
    _push_failed("git push", last)


def compile_wiki() -> None:
    subprocess.run(
        [sys.executable, str(SYSTEM_DIR / "wiki_compile.py")],
        cwd=REPO_DIR,
        check=True,
    )


def maybe_send_chapter_ready_offer(answered_question_id: str) -> None:
    """Phase 2: after an answer lands, if it just tipped a chapter into READY
    (and we haven't offered that chapter before, and it isn't already drafted),
    fire a one-time Telegram nudge with the artifact draft command inline.

    Silent no-op on any failure (no Telegram credentials, book module missing,
    schema surprise). This is delight, not infrastructure — never blocks capture.
    """
    try:
        import book  # noqa: PLC0415
    except Exception as exc:  # noqa: BLE001
        record_learning_failure(
            "process_answer", "chapter_ready_offer_import", exc,
            context={"question_id": answered_question_id},
        )
        return
    try:
        rows = book.send_ready_offers()
    except Exception as exc:  # noqa: BLE001
        record_learning_failure(
            "process_answer", "chapter_ready_offer", exc,
            context={"question_id": answered_question_id},
        )
        return
    for row in rows:
        if row.get("sent"):
            print(f"✓ Chapter-ready offer sent: {row['book_label']} → "
                  f"[{row['chapter_id']}] {row['chapter_name']}")


def maybe_send_followup_question(answered_question_id: str) -> None:
    """Adaptive cadence: after an answer lands, offer the next question the
    same day (up to max_questions_per_day, default 3). Conversation, not
    cadence — an immediate 'here's the next one while you're warm' is the
    listening move the daily-question genre is missing. No-ops gracefully:
    off by config, daily cap reached, late evening, pass transition pending,
    or no Telegram credentials on this machine."""
    from datetime import datetime as _dt

    from lifehug_core import load_config, read_json as _read_json, send_telegram  # noqa: PLC0415

    config = load_config()
    if str(config.get("adaptive_cadence", "true")).strip().lower() in ("false", "0", "no", "off"):
        return
    if _dt.now().hour >= 20:
        return  # don't start a new thread late at night

    import ask  # noqa: PLC0415

    rotation = _read_json(ROTATION_FILE, default={}) or {}
    if rotation.get("awaiting_pass_transition"):
        return
    if ask.sends_today(rotation) >= ask.max_sends_per_day():
        return

    md_text = QUESTIONS_FILE.read_text()
    questions = parse_questions(md_text)
    categories = parse_categories(md_text)
    question = ask.pick_next_question(questions, categories, rotation)
    if not question or question["id"] == answered_question_id:
        return

    text = (f"{FOLLOWUP_HEADER}\n\n"
            f"{ask.format_question(question, categories)}\n\n"
            f"{FOLLOWUP_FOOTER}")
    if send_telegram(text):
        ask.mark_question_sent(rotation, question["id"])
        rebuild_coverage()
        print(f"✓ Adaptive follow-up question sent: {question['id']}")
    else:
        print("  (adaptive follow-up skipped: no telegram credentials on this machine)")


def main():
    parser = argparse.ArgumentParser(description="Process a Lifehug answer")
    parser.add_argument("question_id", nargs="?", help="Question ID; defaults to rotation.last_question_id")
    parser.add_argument("--source", default="text", help="Answer source label, e.g. text or voice (transcribed)")
    parser.add_argument("--answered-date", default=date.today().isoformat())
    parser.add_argument("--asked-date", default=None)
    parser.add_argument("--followup", action="append", default=[], help="Follow-up question text to append")
    parser.add_argument("--force", action="store_true", help="Overwrite an existing answer file")
    parser.add_argument("--commit", action="store_true", help="Commit changed Lifehug files")
    parser.add_argument("--push", action="store_true", help="Push after committing")
    parser.add_argument("--summary", default=None, help="Commit summary")
    parser.add_argument("--sensitivity", default="private",
                        choices=["private", "family", "friends", "public"],
                        help="Sensitivity tier for future audience builds (default private — "
                             "nothing is ever shared without explicit owner review; the wiki "
                             "itself stays owner-only regardless)")
    parser.add_argument("--no-compile-wiki", action="store_true", help="Skip automatic wiki compile")
    args = parser.parse_args()

    rotation = read_json(ROTATION_FILE, default={}) or {}
    question_id = args.question_id or rotation.get("last_question_id")
    if not question_id:
        print("Error: no question ID supplied and rotation.last_question_id is empty", file=sys.stderr)
        raise SystemExit(1)

    md_text = QUESTIONS_FILE.read_text()
    questions = parse_questions(md_text)
    categories = parse_categories(md_text)
    question = question_by_id(questions, question_id)
    if not question:
        print(f"Error: question {question_id} not found", file=sys.stderr)
        raise SystemExit(1)

    answer_text = sys.stdin.read().strip()
    if not answer_text:
        print("Error: answer text must be provided on stdin", file=sys.stderr)
        raise SystemExit(1)

    out_file = ANSWERS_DIR / f"{question_id}.md"
    if out_file.exists() and not args.force:
        print(f"Error: {out_file} already exists; pass --force to overwrite", file=sys.stderr)
        raise SystemExit(1)

    cat = str(question["category"])
    cat_name = categories.get(cat, {}).get("name", cat)
    asked = args.asked_date or (str(rotation.get("last_asked_at", ""))[:10] or args.answered_date)
    pass_number = rotation.get("current_pass", 1)
    followups_added = append_followups(question_id, args.followup)

    followup_section = ""
    if followups_added:
        followup_section = "\n---\n\n## Follow-up Questions Generated\n"
        for qid, text in followups_added:
            followup_section += f"- {qid}: \"{text}\"\n"

    body = (
        f"# Question {question_id}: {question['text']}\n"
        "\n"
        f"{answer_text}\n"
        f"{followup_section}"
    )
    metadata = {
        "title": f"Question {question_id}: {question['text']}",
        "type": "prompted_answer",
        "source_id": f"answer:{question_id}",
        "question_id": question_id,
        "question_text": str(question["text"]),
        "category": cat,
        "category_name": cat_name,
        "pass_number": pass_number,
        "source_medium": args.source,
        "asked_at": asked,
        "answered_date": args.answered_date,
        "captured_at": datetime.now().isoformat(timespec="seconds"),
        "visibility": "owner_only",
        "sensitivity": args.sensitivity,
        "status": "raw",
        "immutable": True,
        "schema_version": SCHEMA_VERSION,
        "source_path": out_file.relative_to(REPO_DIR).as_posix(),
        "content_sha256": payload_sha256(body),
    }
    content = f"{format_frontmatter(metadata)}\n\n{body}"
    if not content.endswith("\n"):
        content += "\n"
    write_text(out_file, content)
    register_source(out_file)

    mark_answered_in_bank(question_id, args.answered_date)
    coverage = rebuild_coverage()
    refresh_neighborhood_readiness_safely()
    answered_count = sum(1 for q in parse_questions(QUESTIONS_FILE.read_text()) if q["answered"])
    rotation["last_answered_id"] = question_id
    rotation["last_answered_at"] = datetime.now().isoformat()
    rotation["questions_answered"] = answered_count
    rotation.pop("pending_answer_question_id", None)
    write_json(ROTATION_FILE, rotation)
    update_readme()

    if not args.no_compile_wiki:
        compile_wiki()

    # Score this answer for the quality loop — runs silently, never fails.
    # Decoupled from wiki compile: skipping compile no longer drops the score.
    try:
        from quality_profile import append_score, extract_signals, focus_for_category, score_richness  # noqa: PLC0415
        followup_count = len(followups_added)
        signals = extract_signals(answer_text, 0, followup_count)
        richness = score_richness(signals)
        from question_planner import infer_story_function  # noqa: PLC0415
        story_fn = infer_story_function(str(question.get("text", "")))
        append_score(question_id, cat, story_fn, focus_for_category(cat), signals, richness)
    except Exception as exc:  # noqa: BLE001
        record_learning_failure(
            "process_answer",
            "quality_scoring",
            exc,
            context={"question_id": question_id},
        )

    # Adaptive cadence: offer the next question while the author is warm.
    try:
        maybe_send_followup_question(question_id)
    except Exception as exc:  # noqa: BLE001
        record_learning_failure(
            "process_answer",
            "adaptive_followup",
            exc,
            context={"question_id": question_id},
        )

    # Phase 2 (v76): milestone chapter-ready offer. Fires at most once per
    # (book, chapter) pair; process_answer never breaks if the module or the
    # Telegram send fails — offers are delight, capture is infrastructure.
    maybe_send_chapter_ready_offer(question_id)

    if args.commit or args.push:
        summary = args.summary or str(question["text"])[:64]
        git_commit(f"Answer {question_id}: {summary}", args.push)

    print(f"✓ Saved answer {question_id} to {out_file.relative_to(REPO_DIR)}")
    print(f"✓ Coverage: {answered_count}/{sum(c['total'] for c in coverage['categories'].values())}")
    if not args.no_compile_wiki:
        print("✓ Compiled wiki")
    if followups_added:
        print(f"✓ Added follow-ups: {', '.join(qid for qid, _ in followups_added)}")


if __name__ == "__main__":
    main()
