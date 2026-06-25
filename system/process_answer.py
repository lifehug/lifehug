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
    mark_answered_in_bank,
    parse_categories,
    parse_questions,
    question_by_id,
    read_json,
    rebuild_coverage,
    write_json,
    write_text,
)
from update_readme import update_readme


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


def git_commit(message: str, push: bool) -> None:
    paths = [
        "README.md",
        "system/question-bank.md",
        "system/rotation.json",
        "system/coverage.json",
        "answers",
        "wiki",
    ]
    subprocess.run(["git", "-C", str(REPO_DIR), "add", "--", *paths], check=True)
    diff = subprocess.run(["git", "-C", str(REPO_DIR), "diff", "--cached", "--quiet"])
    if diff.returncode == 0:
        return
    subprocess.run(["git", "-C", str(REPO_DIR), "commit", "-m", message], check=True)
    if push:
        subprocess.run(["git", "-C", str(REPO_DIR), "push"], check=True)


def compile_wiki() -> None:
    subprocess.run(
        [sys.executable, str(REPO_DIR / "system" / "wiki_compile.py")],
        cwd=REPO_DIR,
        check=True,
    )


def _count_wiki_files() -> int:
    """Count .md files in wiki/ as a proxy for knowledge graph size."""
    wiki_dir = REPO_DIR / "wiki"
    if not wiki_dir.exists():
        return 0
    return sum(1 for _ in wiki_dir.rglob("*.md"))


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

    content = (
        f"# Question {question_id}: {question['text']}\n"
        f"**Category:** {cat} ({cat_name}) | **Pass:** {pass_number}\n"
        f"**Asked:** {asked} | **Answered:** {args.answered_date}\n"
        f"**Source:** {args.source}\n\n"
        "---\n\n"
        f"{answer_text}\n"
        f"{followup_section}"
    )
    if not content.endswith("\n"):
        content += "\n"
    write_text(out_file, content)

    mark_answered_in_bank(question_id, args.answered_date)
    coverage = rebuild_coverage()
    answered_count = sum(1 for q in parse_questions(QUESTIONS_FILE.read_text()) if q["answered"])
    rotation["last_answered_id"] = question_id
    rotation["last_answered_at"] = datetime.now().isoformat()
    rotation["questions_answered"] = answered_count
    rotation.pop("pending_answer_question_id", None)
    write_json(ROTATION_FILE, rotation)
    update_readme()
    wiki_count_before = _count_wiki_files()

    if not args.no_compile_wiki:
        compile_wiki()

    # Score this answer for the quality loop — runs silently, never fails.
    if not args.no_compile_wiki:
        try:
            from quality_profile import append_score, extract_signals, score_richness  # noqa: PLC0415
            wiki_nodes_added = _count_wiki_files() - wiki_count_before
            followup_count = len(followups_added)
            signals = extract_signals(answer_text, wiki_nodes_added, followup_count)
            richness = score_richness(signals)
            from question_planner import infer_story_function  # noqa: PLC0415
            story_fn = infer_story_function(str(question.get("text", "")))
            append_score(question_id, cat, story_fn, None, signals, richness)
        except Exception:  # noqa: BLE001
            pass  # quality scoring never breaks the answer save flow

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
