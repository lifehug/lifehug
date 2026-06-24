#!/usr/bin/env python3
"""Lifehug daily question picker."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone

from lifehug_core import (
    COVERAGE_FILE,
    QUESTION_QUEUE_FILE,
    QUESTIONS_FILE,
    ROTATION_FILE,
    compute_coverage,
    mark_answered_in_bank,
    parse_categories,
    parse_questions,
    question_by_id,
    read_json,
    rebuild_coverage,
    write_json,
)


def pick_planned_question(questions):
    """Return the first valid unanswered question from state/question_queue.json."""
    queue_data = read_json(QUESTION_QUEUE_FILE, default={}) or {}
    if planned_queue_expired(queue_data):
        return None
    queue = queue_data.get("queue", [])
    if not isinstance(queue, list):
        return None
    for item in queue:
        if item.get("status", "queued") != "queued":
            continue
        question_id = item.get("question_id")
        question = question_by_id(questions, question_id) if question_id else None
        if question and not question["answered"]:
            return question
    return None


def planned_queue_expired(queue_data):
    expires_at = queue_data.get("expires_at")
    if not expires_at:
        return False
    try:
        raw = str(expires_at)
        if raw.endswith("Z"):
            expires = datetime.fromisoformat(raw[:-1] + "+00:00")
        else:
            expires = datetime.fromisoformat(raw)
            if expires.tzinfo is None:
                expires = expires.replace(tzinfo=timezone.utc)
    except ValueError:
        return True
    return expires <= datetime.now(timezone.utc)


def pick_next_question(questions, categories, rotation):
    """Pick the next unanswered question using coverage + rotation logic."""
    planned = pick_planned_question(questions)
    if planned:
        return planned

    pending = [q for q in questions if not q["answered"]]
    if not pending:
        return None

    spotlight_freq = rotation.get("spotlight_frequency", 4)
    questions_asked = rotation.get("questions_asked", 0)
    spotlight_turn = (
        spotlight_freq > 0
        and questions_asked > 0
        and questions_asked % spotlight_freq == 0
    )

    answered_per_cat = {}
    total_per_cat = {}
    for q in questions:
        cat = q["category"]
        total_per_cat[cat] = total_per_cat.get(cat, 0) + 1
        if q["answered"]:
            answered_per_cat[cat] = answered_per_cat.get(cat, 0) + 1

    pending_cats = {q["category"] for q in pending}
    cat_scores = []
    for cat in pending_cats:
        ratio = answered_per_cat.get(cat, 0) / total_per_cat.get(cat, 1)
        cat_scores.append((ratio, cat))
    cat_scores.sort()

    spotlight_cats = [
        (r, c) for r, c in cat_scores
        if categories.get(c, {}).get("group") == "spotlight"
    ]
    main_cats = [
        (r, c) for r, c in cat_scores
        if categories.get(c, {}).get("group") != "spotlight"
    ]

    if spotlight_turn and spotlight_cats:
        chosen_cat = spotlight_cats[0][1]
    elif main_cats:
        last_id = rotation.get("last_question_id")
        last_group = None
        if last_id:
            last_group = categories.get(str(last_id)[0], {}).get("group")

        preferred_group = None
        if last_group == "main":
            preferred_group = "project"
        elif last_group == "project":
            preferred_group = "main"

        chosen_cat = None
        if preferred_group:
            for _, cat in main_cats:
                if categories.get(cat, {}).get("group") == preferred_group:
                    chosen_cat = cat
                    break
        if not chosen_cat:
            chosen_cat = main_cats[0][1]
    else:
        chosen_cat = cat_scores[0][1]

    for q in pending:
        if q["category"] == chosen_cat:
            return q
    return pending[0]


def format_question(question, categories, pass_prefix=None):
    cat_info = categories.get(question["category"], {})
    group = cat_info.get("group", "main")
    if group == "spotlight":
        emoji = "✨"
    elif group == "project":
        emoji = "💼"
    else:
        emoji = "📖"

    cat_name = cat_info.get("name", "")
    if cat_name:
        q_line = f"{emoji} [{question['id']}] {cat_name}\n{question['text']}"
    else:
        q_line = f"{emoji} [{question['id']}] {question['text']}"
    return f"{pass_prefix}\n\n{q_line}" if pass_prefix else q_line


def get_followup_model():
    from lifehug_core import CONFIG_FILE, load_config

    return load_config(CONFIG_FILE).get("followup_model", "anthropic/claude-opus-4-6")


def load_state():
    md_text = QUESTIONS_FILE.read_text()
    questions = parse_questions(md_text)
    categories = parse_categories(md_text)
    rotation = read_json(ROTATION_FILE, default={}) or {}
    return questions, categories, rotation


def print_status(questions, categories, rotation):
    coverage = compute_coverage(questions, categories)
    for cat_id in sorted(coverage["categories"]):
        data = coverage["categories"][cat_id]
        total = data["total"]
        answered = data["answered"]
        ratio = answered / total if total else 0
        if ratio >= 0.7:
            emoji = "🟢"
        elif ratio >= 0.3:
            emoji = "🟡"
        else:
            emoji = "🔴"
        cat_info = categories.get(cat_id, {"name": cat_id, "group": "main"})
        group_tag = f" [{cat_info['group']}]" if cat_info["group"] != "main" else ""
        print(f"  {emoji} {cat_id} ({cat_info['name']}){group_tag}: {answered}/{total}")

    total = len(questions)
    answered = sum(1 for q in questions if q["answered"])
    print(f"\n  Total: {answered}/{total}")

    current_pass = rotation.get("current_pass", 1)
    pass_names = rotation.get("pass_names", ["skeleton", "depth", "connections", "polish"])
    pass_name = pass_names[current_pass - 1] if current_pass <= len(pass_names) else f"pass-{current_pass}"
    print(f"\n  Pass: {current_pass} ({pass_name})")


def mark_question_sent(rotation, question_id):
    rotation["last_question_id"] = question_id
    rotation["last_asked_at"] = datetime.now().isoformat()
    rotation["questions_asked"] = rotation.get("questions_asked", 0) + 1
    rotation.pop("pending_delivery_question_id", None)
    rotation.pop("pending_delivery_at", None)
    write_json(ROTATION_FILE, rotation)


def set_pass_transition(rotation):
    current_pass = rotation.get("current_pass", 1)
    if not rotation.get("awaiting_pass_transition"):
        rotation["awaiting_pass_transition"] = True
        rotation["completed_pass"] = current_pass
        rotation["target_pass"] = current_pass + 1
        rotation["pass_completed_at"] = datetime.now().isoformat()
        write_json(ROTATION_FILE, rotation)
    return current_pass


def main():
    parser = argparse.ArgumentParser(description="Lifehug daily question picker")
    parser.add_argument("--dry-run", action="store_true", help="Pick but do not update state")
    parser.add_argument("--status", action="store_true", help="Show coverage report")
    parser.add_argument("--mark-answered", metavar="ID", help="Mark a question as answered")
    parser.add_argument("--confirm-sent", metavar="ID", help="Mark a dry-run question as delivered")
    parser.add_argument("--mark-pass-complete", action="store_true", help="Set pass-transition state")
    parser.add_argument("--rebuild-coverage", action="store_true", help="Rebuild coverage.json")
    args = parser.parse_args()

    questions, categories, rotation = load_state()

    if args.status:
        print_status(questions, categories, rotation)
        return

    if args.rebuild_coverage:
        coverage = rebuild_coverage()
        write_json(COVERAGE_FILE, coverage)
        print("✓ Rebuilt coverage.json")
        return

    if args.mark_answered:
        if mark_answered_in_bank(args.mark_answered):
            questions, categories, rotation = load_state()
            rebuild_coverage()
            rotation["last_answered_id"] = args.mark_answered
            rotation["last_answered_at"] = datetime.now().isoformat()
            rotation["questions_answered"] = sum(1 for q in questions if q["answered"])
            write_json(ROTATION_FILE, rotation)
            print(f"✓ Marked {args.mark_answered} as answered")
        else:
            print(f"✗ Question {args.mark_answered} not found or already answered")
        return

    if args.confirm_sent:
        if not question_by_id(questions, args.confirm_sent):
            print(f"✗ Question {args.confirm_sent} not found")
            raise SystemExit(1)
        mark_question_sent(rotation, args.confirm_sent)
        rebuild_coverage()
        print(f"✓ Marked {args.confirm_sent} as sent")
        return

    if args.mark_pass_complete:
        current_pass = set_pass_transition(rotation)
        print(f"PASS_COMPLETE:{current_pass}:{get_followup_model()}")
        return

    question = pick_next_question(questions, categories, rotation)
    if not question:
        current_pass = rotation.get("current_pass", 1)
        if args.dry_run:
            pass_names = rotation.get("pass_names", ["skeleton", "depth", "connections", "polish"])
            next_pass = current_pass + 1
            next_name = pass_names[next_pass - 1] if next_pass <= len(pass_names) else f"pass-{next_pass}"
            print(f"Pass {current_pass} complete. Would generate Pass {next_pass} ({next_name}) questions.")
            return
        current_pass = set_pass_transition(rotation)
        print(f"PASS_COMPLETE:{current_pass}:{get_followup_model()}")
        return

    print(format_question(question, categories))

    if not args.dry_run:
        mark_question_sent(rotation, question["id"])
        rebuild_coverage()


if __name__ == "__main__":
    main()
