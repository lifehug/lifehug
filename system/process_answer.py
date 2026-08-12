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
    load_config,
    mark_answered_in_bank,
    parse_categories,
    parse_questions,
    question_by_id,
    read_json,
    record_learning_failure,
    rebuild_coverage,
    send_telegram,
    split_frontmatter,
    write_json,
    write_text,
)
from source_integrity import (
    SCHEMA_VERSION,
    format_frontmatter,
    normalize_payload,
    payload_sha256,
    register_source,
)
from update_readme import update_readme
from vault_paths import vault_relative_path

FOLLOWUP_HEADER = "📖 Lifehug — since you're on a roll"
FOLLOWUP_FOOTER = "(Totally optional — tomorrow's question comes either way)"
FOLLOWUP_SECTION_TITLE = "## Follow-up Questions Generated"
FOLLOWUP_SECTION_MARKER = f"\n---\n\n{FOLLOWUP_SECTION_TITLE}\n"
ADDITIONAL_ANSWER_RE = re.compile(
    r"^## Additional Answer (?P<number>\d+)\n\n"
    r"(?:\*\*Asked:\*\* .+\n)?"
    r"(?:\*\*Answered:\*\* .+\n)?"
    r"(?:\*\*Source:\*\* .+\n)?"
    r"(?:\*\*Captured:\*\* .+\n)?"
    r"\n(?P<body>.*?)(?=\n## Additional Answer \d+\n\n|\Z)",
    re.MULTILINE | re.DOTALL,
)
_FOLLOWUP_UNSET = object()


def _asked_date_from(rotation: dict) -> str:
    """Return rotation's asked date as ``YYYY-MM-DD``, or "" when unrecorded.

    ``last_asked_at`` is ``string|null`` in the vault contract — v120 made the
    key REQUIRED-but-nullable, so ``rotation.get("last_asked_at", "")`` started
    returning ``None`` instead of the pre-v120 missing-key ``""``. Stringifying
    that produced the literal ``"None"``, which sailed through the ``or``
    fallback (a non-empty string) and landed in ``asked_at`` frontmatter, where
    downstream date validation rejects it. Only a real date string survives
    here; everything else falls back exactly as a pre-v120 absent key did.
    """
    raw = rotation.get("last_asked_at")
    if not isinstance(raw, str):
        return ""
    return raw.strip()[:10]


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


def format_followup_section(followups_added: list[tuple[str, str]]) -> str:
    if not followups_added:
        return ""
    lines = [FOLLOWUP_SECTION_MARKER.rstrip("\n")]
    lines.extend(f"- {qid}: \"{text}\"" for qid, text in followups_added)
    return "\n".join(lines) + "\n"


def _split_followup_section(body: str) -> tuple[str, str]:
    index = body.find(FOLLOWUP_SECTION_MARKER)
    if index == -1:
        return body.rstrip(), ""
    return body[:index].rstrip(), body[index:]


def _without_question_heading(answer_part: str) -> str:
    return re.sub(r"^# Question [^\n]+\n\n", "", answer_part, count=1).strip()


def answer_text_segments(answer_part: str) -> list[str]:
    text = _without_question_heading(answer_part)
    matches = list(ADDITIONAL_ANSWER_RE.finditer(text))
    if not matches:
        return [text] if text else []

    segments = []
    primary = text[:matches[0].start()].strip()
    if primary:
        segments.append(primary)
    segments.extend(match.group("body").strip() for match in matches if match.group("body").strip())
    return segments


def answer_already_captured(existing_content: str, answer_text: str) -> bool:
    _metadata, body = split_frontmatter(existing_content)
    answer_part, _followups = _split_followup_section(body)
    candidate = normalize_payload(answer_text)
    return any(normalize_payload(segment) == candidate for segment in answer_text_segments(answer_part))


def _one_line(value: str | None) -> str:
    return " ".join(str(value or "").split())


def append_answer_addendum(
    existing_content: str,
    answer_text: str,
    *,
    source: str,
    asked_date: str,
    answered_date: str,
    captured_at: str,
    followups_added: list[tuple[str, str]],
) -> str:
    metadata, body = split_frontmatter(existing_content)
    answer_part, followup_suffix = _split_followup_section(body)
    existing_segments = answer_text_segments(answer_part)
    next_number = len(existing_segments) + 1
    addendum = (
        f"\n\n## Additional Answer {next_number}\n\n"
        f"**Asked:** {_one_line(asked_date)}\n"
        f"**Answered:** {_one_line(answered_date)}\n"
        f"**Source:** {_one_line(source)}\n"
        f"**Captured:** {_one_line(captured_at)}\n"
        "\n"
        f"{answer_text.strip()}\n"
    )
    merged_followups = followup_suffix
    if followups_added:
        lines = [f"- {qid}: \"{text}\"" for qid, text in followups_added]
        if merged_followups:
            merged_followups = merged_followups.rstrip() + "\n" + "\n".join(lines) + "\n"
        else:
            merged_followups = format_followup_section(followups_added)

    payload = answer_part.rstrip() + addendum + merged_followups
    if not payload.endswith("\n"):
        payload += "\n"
    metadata = dict(metadata)
    metadata["answer_count"] = next_number
    metadata["latest_answered_date"] = answered_date
    metadata["latest_source_medium"] = source
    metadata["latest_captured_at"] = captured_at
    metadata["content_sha256"] = payload_sha256(payload)
    return f"{format_frontmatter(metadata)}\n\n{payload}"


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


def plan_adaptive_followup(answered_question_id: str):
    """Choose the optional follow-up without sending or mutating state."""
    from datetime import datetime as _dt

    from lifehug_core import load_config, read_json as _read_json  # noqa: PLC0415


    config = load_config()
    if str(config.get("adaptive_cadence", "true")).strip().lower() in ("false", "0", "no", "off"):
        return None
    if _dt.now().hour >= 20:
        return None  # don't start a new thread late at night

    import ask  # noqa: PLC0415

    rotation = read_json(ROTATION_FILE, default={}) or {}
    if rotation.get("awaiting_pass_transition"):
        return None
    if ask.sends_today(rotation) >= ask.max_sends_per_day():
        return None

    md_text = QUESTIONS_FILE.read_text()
    questions = parse_questions(md_text)
    categories = parse_categories(md_text)
    question = ask.pick_next_question(questions, categories, rotation)
    if not question or question["id"] == answered_question_id:
        return None
    return question


def maybe_send_followup_question(answered_question_id: str, planned_question=_FOLLOWUP_UNSET) -> None:
    """Adaptive cadence: send the already-planned optional follow-up.

    Planning is separated so the acknowledgment prompt can honestly say
    whether a follow-up is pending, while the actual send remains strictly
    after the acknowledgment attempt.  A direct caller may omit the plan and
    retain the historical choose-and-send behavior.
    """
    from lifehug_core import read_json as _read_json, send_telegram  # noqa: PLC0415

    import ask  # noqa: PLC0415

    question = (
        plan_adaptive_followup(answered_question_id)
        if planned_question is _FOLLOWUP_UNSET
        else planned_question
    )
    if question is None:
        return
    categories = parse_categories(QUESTIONS_FILE.read_text())

    text = (f"{FOLLOWUP_HEADER}\n\n"
            f"{ask.format_question(question, categories)}\n\n"
            f"{FOLLOWUP_FOOTER}")
    if send_telegram(text):
        rotation = _read_json(ROTATION_FILE, default={}) or {}
        ask.mark_question_sent(rotation, question["id"])
        rebuild_coverage()
        print(f"✓ Adaptive follow-up question sent: {question['id']}")
    else:
        print("  (adaptive follow-up skipped: no telegram credentials on this machine)")


def run_post_answer_delivery(
    *,
    source_id: str,
    question_id: str,
    question_text: str,
    question_category: str,
    answer_text: str,
):
    """After durability: ONE conversation turn, or today's ack + follow-up.

    v153 (issue #116): the acknowledgment-then-separate-follow-up pair became
    a single conversation turn — receipt, payout, and a cued follow-up in one
    message, per ``interactions/conversation/prompt/behavior.md``. The
    planning step is unchanged and still runs FIRST, because the turn engine
    needs the cadence gates' verdict (curfew, 3/day cap, pass transition):
    when planning returns None our question initiative is spent, and the turn
    is question-free rather than skipped.

    The engine degrades to today's exact behavior — ``acknowledge_answer``
    then ``maybe_send_followup_question`` — on any definitive failure, so
    this path is never silent and never worse than before. Every failure is
    swallowed relative to answer durability, and no diagnostic receives
    answer, prompt, or generated message text.
    """
    planned_question = None
    try:
        planned_question = plan_adaptive_followup(question_id)
    except Exception as exc:  # noqa: BLE001
        record_learning_failure(
            "process_answer",
            "adaptive_followup_plan",
            type(exc).__name__,
            context={"source_id": source_id},
        )

    outcome = None
    try:
        from conversation_delivery import run_post_answer_turn  # noqa: PLC0415

        outcome = run_post_answer_turn(
            source_id=source_id,
            question_id=question_id,
            question_text=question_text,
            question_category=question_category,
            answer_text=answer_text,
            planned_question=planned_question,
        )
        print(
            f"✓ Conversation turn: {outcome.status} "
            f"({outcome.reason}; {source_id})"
        )
    except Exception as exc:  # noqa: BLE001 — the turn is never capture
        record_learning_failure(
            "process_answer",
            "conversation_turn",
            type(exc).__name__,
            context={"source_id": source_id},
        )
        print(f"  (conversation turn skipped: internal_error; {source_id})")
        # The engine owns its own fallback; an exception BEFORE it could run
        # leaves the user with nothing, so run today's behavior here.
        _run_legacy_post_answer_delivery(
            source_id=source_id,
            question_id=question_id,
            question_text=question_text,
            question_category=question_category,
            answer_text=answer_text,
            planned_question=planned_question,
        )
    return outcome


def _run_legacy_post_answer_delivery(
    *,
    source_id: str,
    question_id: str,
    question_text: str,
    question_category: str,
    answer_text: str,
    planned_question,
):
    """Pre-v153 behavior: warm acknowledgment, then the separate follow-up.

    Kept as a named function (not dead code): it is the last-resort path when
    the turn engine cannot even be imported or raises before its own fallback
    fires. ``answer_ack``'s "No questions back" rule is correct HERE — this
    message is an acknowledgment, and the follow-up is a separate message.
    """
    outcome = None
    try:
        from answer_ack_delivery import acknowledge_answer  # noqa: PLC0415

        outcome = acknowledge_answer(
            source_id=source_id,
            question_id=question_id,
            question_text=question_text,
            question_category=question_category,
            answer_text=answer_text,
            followup_pending=planned_question is not None,
        )
        print(
            f"✓ Answer acknowledgment: {outcome.status} "
            f"({outcome.reason}; {source_id})"
        )
    except Exception as exc:  # noqa: BLE001 — acknowledgment is never capture
        record_learning_failure(
            "process_answer",
            "answer_acknowledgment",
            type(exc).__name__,
            context={"source_id": source_id},
        )
        print(f"  (answer acknowledgment skipped: internal_error; {source_id})")

    try:
        maybe_send_followup_question(question_id, planned_question)
    except Exception as exc:  # noqa: BLE001
        record_learning_failure(
            "process_answer",
            "adaptive_followup",
            type(exc).__name__,
            context={"source_id": source_id},
        )
    return outcome


def finalize_answer_delivery(
    *,
    source_id: str,
    question_id: str,
    question_text: str,
    question_category: str,
    answer_text: str,
    commit_requested: bool,
    push_requested: bool,
    summary: str,
) -> None:
    """Cross the durability boundary, then run ordered conversational effects."""
    if commit_requested:
        git_commit(f"Answer {question_id}: {summary}", False)
    run_post_answer_delivery(
        source_id=source_id,
        question_id=question_id,
        question_text=question_text,
        question_category=question_category,
        answer_text=answer_text,
    )
    maybe_send_chapter_ready_offer(question_id)
    if commit_requested:
        git_commit(f"Record answer {question_id} delivery metadata", push_requested)


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

    cat = str(question["category"])
    cat_name = categories.get(cat, {}).get("name", cat)
    asked = args.asked_date or _asked_date_from(rotation) or args.answered_date
    pass_number = rotation.get("current_pass", 1)
    captured_at = datetime.now().isoformat(timespec="seconds")

    out_file = ANSWERS_DIR / f"{question_id}.md"
    answer_action = "Saved"
    if out_file.exists() and not args.force:
        existing = out_file.read_text(encoding="utf-8", errors="replace")
        if answer_already_captured(existing, answer_text):
            print(f"✓ Answer {question_id} already captured; no changes needed")
            return
        followups_added = append_followups(question_id, args.followup)
        content = append_answer_addendum(
            existing,
            answer_text,
            source=args.source,
            asked_date=asked,
            answered_date=args.answered_date,
            captured_at=captured_at,
            followups_added=followups_added,
        )
        answer_action = "Appended"
        # finalize_answer_delivery (v121) needs metadata["source_id"] on every
        # path, including this append/retry one that predates it and only
        # produces a formatted content string. Parse it back out rather than
        # changing append_answer_addendum's contract — the same pattern
        # answer_ack_delivery._durable_answer_context already uses to
        # reconstruct context from a durable answer file.
        metadata, _ = split_frontmatter(content)
    else:
        followups_added = append_followups(question_id, args.followup)
        body = (
            f"# Question {question_id}: {question['text']}\n"
            "\n"
            f"{answer_text}\n"
            f"{format_followup_section(followups_added)}"
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
            "captured_at": captured_at,
            "answer_count": 1,
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

    # Durability is the hard boundary.  When the caller requested a commit,
    # land it locally BEFORE either outbound conversational effect.  The later
    # bookkeeping commit records acknowledgment/follow-up metadata and pushes
    # both commits together when --push was requested.
    summary = args.summary or str(question["text"])[:64]
    # Contractual order: durable answer first, warm acknowledgment attempt
    # second, adaptive follow-up third.  The acknowledgment layer swallows
    # provider/generation/Telegram failures and carries metadata only.
    finalize_answer_delivery(
        source_id=str(metadata["source_id"]),
        question_id=question_id,
        question_text=str(question["text"]),
        question_category=cat,
        answer_text=answer_text,
        commit_requested=bool(args.commit or args.push),
        push_requested=bool(args.push),
        summary=summary,
    )

    print(f"✓ {answer_action} answer {question_id} to {out_file.relative_to(REPO_DIR)}")
    print(f"✓ Coverage: {answered_count}/{sum(c['total'] for c in coverage['categories'].values())}")
    if not args.no_compile_wiki:
        print("✓ Compiled wiki")
    if followups_added:
        print(f"✓ Added follow-ups: {', '.join(qid for qid, _ in followups_added)}")


if __name__ == "__main__":
    main()
