#!/usr/bin/env python3
"""Life Hug — Daily Question Picker

Reads question-bank.md, picks the next question based on rotation logic,
updates state, and prints the question for sending.

Usage:
    python3 ask.py              # Pick next question, update state, print it
    python3 ask.py --dry-run    # Pick but don't update state
    python3 ask.py --status     # Show coverage report
    python3 ask.py --mark-answered A1  # Mark a question as answered
"""

import argparse
import json
import re
from datetime import datetime, date
from pathlib import Path

SYSTEM_DIR = Path(__file__).parent
QUESTIONS_FILE = SYSTEM_DIR / "question-bank.md"
ROTATION_FILE = SYSTEM_DIR / "rotation.json"
COVERAGE_FILE = SYSTEM_DIR / "coverage.json"


def load_json(path):
    with open(path) as f:
        return json.load(f)


def save_json(path, data):
    with open(path, "w") as f:
        json.dump(data, f, indent=2)
        f.write("\n")


def parse_categories(md_text):
    """Dynamically discover categories and their metadata from question-bank.md."""
    categories = {}
    # Match section headers like: ## A: Origins (Childhood & Family)
    header_pattern = re.compile(r'^## ([A-Z]): (.+?)(?:\s*\(.*\))?\s*$', re.MULTILINE)

    current_group = "main"
    for line in md_text.splitlines():
        if line.strip().lower().startswith("## spotlight"):
            current_group = "spotlight"
        elif line.strip().lower().startswith("## project"):
            current_group = "project"

    # Re-scan with context tracking
    group = "main"
    for line in md_text.splitlines():
        stripped = line.strip().lower()
        if stripped.startswith("## spotlight"):
            group = "spotlight"
            continue
        elif stripped.startswith("## project"):
            group = "project"
            continue

        match = header_pattern.match(line)
        if match:
            cat_id = match.group(1)
            name = match.group(2).strip()
            # A-E are generic, F-J are project, K+ are spotlight
            if cat_id >= "K":
                cat_group = "spotlight"
            elif cat_id >= "F":
                cat_group = "project"
            else:
                cat_group = "main"
            categories[cat_id] = {"name": name, "group": cat_group}

    return categories


def parse_questions(md_text):
    """Parse question-bank.md into a list of questions with status."""
    questions = []
    # Match: - [ ] A1: Question text
    # or:    - [x] A1: Question text *(2026-03-01)*
    pattern = re.compile(
        r'^- \[([ x])\] ([A-Z]\d+): (.+?)(?:\s*\*\(.+\)\*)?$',
        re.MULTILINE,
    )

    for match in pattern.finditer(md_text):
        checked = match.group(1) == "x"
        qid = match.group(2)
        text = match.group(3).strip()
        cat = qid[0]
        questions.append({
            "id": qid,
            "category": cat,
            "text": text,
            "answered": checked,
        })

    return questions


def mark_answered_in_md(question_id):
    """Check off a question in question-bank.md."""
    md = QUESTIONS_FILE.read_text()
    today = date.today().isoformat()

    pattern = re.compile(
        r"^(- \[) \] (" + re.escape(question_id) + r": .+?)$",
        re.MULTILINE,
    )

    def replacer(m):
        return f"{m.group(1)}x] {m.group(2)} *({today})*"

    new_md, count = pattern.subn(replacer, md)
    if count > 0:
        QUESTIONS_FILE.write_text(new_md)
    return count > 0


def pick_next_question(questions, categories, rotation):
    """Pick the next question using rotation logic."""
    pending = [q for q in questions if not q["answered"]]

    if not pending:
        return None

    spotlight_freq = rotation.get("spotlight_frequency", 4)
    questions_asked = rotation.get("questions_asked", 0)

    # Check if it's time for a spotlight question
    spotlight_turn = (
        spotlight_freq > 0
        and questions_asked > 0
        and questions_asked % spotlight_freq == 0
    )

    # Count answered per category
    answered_per_cat = {}
    total_per_cat = {}
    for q in questions:
        cat = q["category"]
        total_per_cat[cat] = total_per_cat.get(cat, 0) + 1
        if q["answered"]:
            answered_per_cat[cat] = answered_per_cat.get(cat, 0) + 1

    # Score: ratio of answered (lower = higher priority)
    pending_cats = set(q["category"] for q in pending)
    cat_scores = []
    for cat in pending_cats:
        ratio = answered_per_cat.get(cat, 0) / total_per_cat.get(cat, 1)
        cat_scores.append((ratio, cat))
    cat_scores.sort()

    # Separate spotlight and non-spotlight categories
    spotlight_cats = [
        (r, c) for r, c in cat_scores
        if categories.get(c, {}).get("group") == "spotlight"
    ]
    main_cats = [
        (r, c) for r, c in cat_scores
        if categories.get(c, {}).get("group") != "spotlight"
    ]

    # If spotlight turn and there are spotlight questions pending
    if spotlight_turn and spotlight_cats:
        chosen_cat = spotlight_cats[0][1]
    elif main_cats:
        # Alternate between groups based on last question
        last_id = rotation.get("last_question_id")
        last_group = None
        if last_id:
            last_cat = last_id[0]
            last_group = categories.get(last_cat, {}).get("group")

        # Try to alternate between main and project groups
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

    # Pick first pending in chosen category
    for q in pending:
        if q["category"] == chosen_cat:
            return q

    return pending[0]


def update_coverage(questions, categories):
    """Rebuild coverage.json from current question state."""
    coverage = {
        "version": 1,
        "last_updated": datetime.now().isoformat(),
        "categories": {},
    }

    for cat_id in sorted(categories.keys()):
        cat_qs = [q for q in questions if q["category"] == cat_id]
        total = len(cat_qs)
        answered = sum(1 for q in cat_qs if q["answered"])
        ratio = answered / total if total > 0 else 0

        if ratio >= 0.7:
            status = "green"
        elif ratio >= 0.3:
            status = "yellow"
        else:
            status = "red"

        coverage["categories"][cat_id] = {
            "total": total,
            "answered": answered,
            "status": status,
        }

    save_json(COVERAGE_FILE, coverage)
    return coverage


def show_status(questions, categories):
    """Print coverage report."""
    for cat_id in sorted(categories.keys()):
        cat_qs = [q for q in questions if q["category"] == cat_id]
        total = len(cat_qs)
        answered = sum(1 for q in cat_qs if q["answered"])
        ratio = answered / total if total > 0 else 0

        if ratio >= 0.7:
            emoji = "\U0001f7e2"  # green
        elif ratio >= 0.3:
            emoji = "\U0001f7e1"  # yellow
        else:
            emoji = "\U0001f534"  # red

        name = categories[cat_id]["name"]
        group = categories[cat_id]["group"]
        group_tag = f" [{group}]" if group != "main" else ""
        print(f"  {emoji} {cat_id} ({name}){group_tag}: {answered}/{total}")

    total = len(questions)
    answered = sum(1 for q in questions if q["answered"])
    print(f"\n  Total: {answered}/{total}")


def main():
    parser = argparse.ArgumentParser(description="Life Hug daily question picker")
    parser.add_argument("--dry-run", action="store_true", help="Pick but don't update state")
    parser.add_argument("--status", action="store_true", help="Show coverage report")
    parser.add_argument("--mark-answered", type=str, metavar="ID", help="Mark a question as answered")
    args = parser.parse_args()

    md_text = QUESTIONS_FILE.read_text()
    questions = parse_questions(md_text)
    categories = parse_categories(md_text)
    rotation = load_json(ROTATION_FILE)

    if args.status:
        show_status(questions, categories)
        return

    if args.mark_answered:
        if mark_answered_in_md(args.mark_answered):
            questions = parse_questions(QUESTIONS_FILE.read_text())
            update_coverage(questions, categories)
            print(f"\u2713 Marked {args.mark_answered} as answered")
        else:
            print(f"\u2717 Question {args.mark_answered} not found")
        return

    question = pick_next_question(questions, categories, rotation)

    if not question:
        print("All questions answered! Time for the next pass.")
        return

    cat_info = categories.get(question["category"], {})
    group = cat_info.get("group", "main")
    if group == "spotlight":
        emoji = "\u2728"
    elif group == "project":
        emoji = "\U0001f4bc"
    else:
        emoji = "\U0001f4d6"

    print(f"{emoji} [{question['id']}] {question['text']}")

    if not args.dry_run:
        rotation["last_question_id"] = question["id"]
        rotation["last_asked_at"] = datetime.now().isoformat()
        rotation["questions_asked"] = rotation.get("questions_asked", 0) + 1
        save_json(ROTATION_FILE, rotation)
        update_coverage(questions, categories)


if __name__ == "__main__":
    main()
