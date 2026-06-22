#!/usr/bin/env python3
"""Lifehug — Pass Transition: Follow-up Question Generator

At the end of each pass, this script manages generating AI-driven depth questions
from accumulated answers. It does NOT call the AI itself — it prepares context
for the AI, then handles appending the AI's output to the question bank.

Flow:
  1. pass completes → ask.py sets `awaiting_pass_transition: true` in rotation.json
  2. AI (via cron or direct session) runs:
       python3 system/gen_followups.py --prompt  → prints full context for AI
  3. AI generates questions in JSON format
  4. AI runs:
       python3 system/gen_followups.py --append questions.json [--model <model>]
  5. Questions are appended to question-bank.md, pass advances

Usage:
    python3 system/gen_followups.py --status              # Show transition state
    python3 system/gen_followups.py --prompt              # Output AI prompt (pipe to AI)
    python3 system/gen_followups.py --append FILE         # Append AI-generated questions
    python3 system/gen_followups.py --append FILE --model claude-opus-4-6  # Record model used
    python3 system/gen_followups.py --append FILE --dry-run  # Preview without writing
"""

import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path

from lifehug_core import (
    ANSWERS_DIR,
    CONFIG_FILE,
    COVERAGE_FILE,
    QUESTIONS_FILE,
    ROTATION_FILE,
    QUESTION_ID_RE,
    answer_body,
    answer_id_from_filename,
    parse_categories as core_parse_categories,
    parse_questions as core_parse_questions,
    rebuild_coverage,
    write_text,
    write_json,
)

SYSTEM_DIR = Path(__file__).parent
REPO_DIR = SYSTEM_DIR.parent


def load_json(path):
    with open(path) as f:
        return json.load(f)


def save_json(path, data):
    write_json(path, data)


def load_config():
    """Load config.yaml as a simple key:value dict (no yaml library needed)."""
    config = {}
    if not CONFIG_FILE.exists():
        return config
    for line in CONFIG_FILE.read_text().splitlines():
        line = line.strip()
        if line.startswith("#") or ":" not in line:
            continue
        key, _, val = line.partition(":")
        config[key.strip()] = val.strip().strip('"').strip("'")
    return config


def get_default_model():
    """Get the configured followup model, or fall back to opus."""
    config = load_config()
    return config.get("followup_model", "anthropic/claude-opus-4-6")


def parse_questions(md_text):
    """Parse all questions from question-bank.md."""
    return core_parse_questions(md_text)


def get_next_id_for_category(md_text, category):
    """Find the next available question ID for a category (e.g. A11, B8)."""
    pattern = re.compile(rf'^- \[[ xX]\] ({re.escape(category)}\d+):', re.MULTILINE)
    existing = [m.group(1) for m in pattern.finditer(md_text)]
    if not existing:
        return f"{category}1"
    max_num = max(int(re.search(r'\d+', qid).group()) for qid in existing)
    return f"{category}{max_num + 1}"


def read_answer_files():
    """Read all answer files, return list of {question_id, content}."""
    answers = []
    if not ANSWERS_DIR.exists():
        return answers
    for f in sorted(ANSWERS_DIR.glob("*.md")):
        try:
            content = f.read_text().strip()
            qid = answer_id_from_filename(f) or f.stem
            answers.append({"id": qid, "file": f.name, "content": content})
        except Exception:
            continue
    return answers


def cmd_status(args):
    """Show current transition state."""
    rotation = load_json(ROTATION_FILE)
    current_pass = rotation.get("current_pass", 1)
    pass_names = rotation.get("pass_names", ["skeleton", "depth", "connections", "polish"])
    pass_name = pass_names[current_pass - 1] if current_pass <= len(pass_names) else f"pass-{current_pass}"
    awaiting = rotation.get("awaiting_pass_transition", False)

    print(f"Current pass: {current_pass} ({pass_name})")
    print(f"Awaiting transition: {awaiting}")

    answers = read_answer_files()
    print(f"Answer files: {len(answers)}")

    md_text = QUESTIONS_FILE.read_text()
    questions = parse_questions(md_text)
    answered = sum(1 for q in questions if q["answered"])
    total = len(questions)
    print(f"Questions: {answered}/{total} answered")

    default_model = get_default_model()
    print(f"Default model: {default_model}")

    if awaiting:
        print()
        print("Ready to generate follow-up questions.")
        print(f"Run: python3 system/gen_followups.py --prompt | <your-ai> | python3 system/gen_followups.py --append -")


def cmd_prompt(args):
    """Output the full AI prompt for generating follow-up questions."""
    rotation = load_json(ROTATION_FILE)
    current_pass = rotation.get("current_pass", 1)
    pass_names = rotation.get("pass_names", ["skeleton", "depth", "connections", "polish"])

    completed_pass = rotation.get("completed_pass", current_pass)
    target_pass = rotation.get("target_pass", completed_pass + 1)
    prev_name = pass_names[completed_pass - 1] if completed_pass <= len(pass_names) else f"pass-{completed_pass}"
    next_name = pass_names[target_pass - 1] if target_pass <= len(pass_names) else f"pass-{target_pass}"

    answers = read_answer_files()
    md_text = QUESTIONS_FILE.read_text()
    questions = parse_questions(md_text)

    # Build question lookup
    q_lookup = {q["id"]: q["text"] for q in questions}

    config = load_config()
    author_name = config.get("name", "the author")

    # Build the prompt
    lines = []
    lines.append("=" * 70)
    lines.append("LIFEHUG — PASS TRANSITION: GENERATE DEPTH QUESTIONS")
    lines.append("=" * 70)
    lines.append("")
    lines.append(f"Author: {author_name}")
    lines.append(f"Completed: Pass {completed_pass} ({prev_name})")
    lines.append(f"Generating for: Pass {target_pass} ({next_name})")
    lines.append(f"Answers available: {len(answers)}")
    lines.append("")
    lines.append("-" * 70)
    lines.append("YOUR TASK")
    lines.append("-" * 70)
    lines.append("")
    lines.append(f"You are generating Pass {target_pass} ({next_name}) questions for {author_name}'s")
    lines.append("Lifehug storytelling project.")
    lines.append("")
    lines.append(f"Pass {completed_pass} ({prev_name}) captured the broad strokes — raw answers across all")
    lines.append(f"categories. Pass {target_pass} ({next_name}) goes deeper: specific scenes, sensory")
    lines.append("detail, dialogue, emotion, and the threads worth pulling harder.")
    lines.append("")
    lines.append("For each answer below:")
    lines.append("  - Read what the author shared")
    lines.append("  - Identify 1-3 moments, people, or details worth going deeper on")
    lines.append("  - Write a targeted follow-up question for each")
    lines.append("")
    lines.append("Question design principles:")
    lines.append("  1. Specific, not general — 'Tell me more about the blue Toyota' not 'Tell me about cars'")
    lines.append("  2. Sensory — 'What did that place look like? Sound like? Smell like?'")
    lines.append("  3. Emotional — 'What were you feeling in that moment?'")
    lines.append("  4. Dialogue — 'What did she say? What did you say back?'")
    lines.append("  5. Before/after — 'What changed after that?'")
    lines.append("  6. Contrast — 'How was that different from what you expected?'")
    lines.append("  7. Never yes/no — always open-ended")
    lines.append("")
    lines.append("Skip an answer if it's already exhaustively detailed or if no meaningful")
    lines.append("follow-up is possible.")
    lines.append("")
    lines.append("-" * 70)
    lines.append("OUTPUT FORMAT")
    lines.append("-" * 70)
    lines.append("")
    lines.append("Return ONLY valid JSON in this exact format — no explanation, no markdown:")
    lines.append("")
    lines.append('{')
    lines.append('  "questions": [')
    lines.append('    {"category": "A", "source_id": "A1", "text": "You mentioned the blue Toyota..."},')
    lines.append('    {"category": "A", "source_id": "A1", "text": "What was your relationship with your dad like..."},')
    lines.append('    {"category": "B", "source_id": "B2", "text": "You said your first job taught you..."}')
    lines.append('  ]')
    lines.append('}')
    lines.append("")
    lines.append("Use the category letter from the source answer's ID (A1 → category A).")
    lines.append("source_id is the question ID the follow-up is based on.")
    lines.append("")
    lines.append("-" * 70)
    lines.append("ANSWERS FROM PASS 1")
    lines.append("-" * 70)
    lines.append("")

    for ans in answers:
        qid = ans["id"]
        q_text = q_lookup.get(qid, "(question text not found)")
        lines.append(f"### [{qid}] {q_text}")
        lines.append("")
        # Include the full answer but trim very long ones
        content = ans["content"]
        # Remove the header block to save tokens (keep just the answer body)
        body = answer_body(content)
        # Trim to ~800 chars if very long
        if len(body) > 800:
            body = body[:800] + "... [truncated]"
        lines.append(body)
        lines.append("")

    lines.append("=" * 70)
    lines.append("END OF CONTEXT — Output JSON only")
    lines.append("=" * 70)

    print("\n".join(lines))


def cmd_append(args):
    """Append AI-generated questions to question-bank.md."""
    # Read input
    if args.file == "-":
        raw = sys.stdin.read()
    else:
        raw = Path(args.file).read_text()

    # Parse JSON — handle if wrapped in markdown code block
    raw = raw.strip()
    if raw.startswith("```"):
        lines = raw.splitlines()
        raw = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        print(f"Error: Invalid JSON: {e}", file=sys.stderr)
        sys.exit(1)

    questions = data.get("questions", [])
    if not questions:
        print("Error: No questions found in input.", file=sys.stderr)
        sys.exit(1)

    model = args.model or data.get("model") or get_default_model()

    rotation = load_json(ROTATION_FILE)
    current_pass = rotation.get("current_pass", 2)
    target_pass = rotation.get("target_pass", current_pass + 1)

    md_text = QUESTIONS_FILE.read_text()

    # Group questions by category
    by_cat = {}
    for q in questions:
        cat = q.get("category", "").upper()
        if not cat or not re.match(r'^[A-Z]$', cat):
            print(f"Warning: skipping question with invalid category: {q}", file=sys.stderr)
            continue
        by_cat.setdefault(cat, []).append(q)

    # Build additions per category
    additions = []  # list of (cat, new_id, text, source_id)
    current_md = md_text
    for cat in sorted(by_cat.keys()):
        for q in by_cat[cat]:
            new_id = get_next_id_for_category(current_md, cat)
            text = q.get("text", "").strip()
            source_id = q.get("source_id", "")
            if not text:
                continue
            additions.append((cat, new_id, text, source_id))
            # Update current_md so next ID is correct
            # Fake-add the ID so get_next_id_for_category increments
            current_md += f"\n- [ ] {new_id}: {text}"

    if not additions:
        print("No valid questions to add.", file=sys.stderr)
        sys.exit(1)

    if args.dry_run:
        print(f"DRY RUN — would add {len(additions)} questions using model: {model}")
        print()
        for cat, new_id, text, source_id in additions:
            src = f" (from {source_id})" if source_id else ""
            print(f"  [{new_id}]{src}: {text}")
        return

    # Re-read question bank fresh before appending
    md_text = QUESTIONS_FILE.read_text()

    # Append new questions to each category section
    for cat, new_id, text, source_id in additions:
        new_line = f"- [ ] {new_id}: {text}"

        # Find the category section and append before the next section or EOF
        cat_pattern = re.compile(
            rf'^(## {re.escape(cat)}:.+?(?=\n## |\Z))',
            re.MULTILINE | re.DOTALL,
        )
        match = cat_pattern.search(md_text)
        if match:
            section = match.group(1)
            # Append to end of section (before the trailing newlines)
            new_section = section.rstrip() + "\n" + new_line + "\n"
            md_text = md_text[:match.start()] + new_section + md_text[match.end():]
        else:
            # Category not found — append to end of file
            md_text = md_text.rstrip() + f"\n\n## {cat}: (generated)\n{new_line}\n"

    write_text(QUESTIONS_FILE, md_text)

    # Update rotation: mark transition complete, record model
    rotation["current_pass"] = target_pass
    rotation["awaiting_pass_transition"] = False
    rotation.pop("completed_pass", None)
    rotation.pop("target_pass", None)
    rotation.pop("pass_completed_at", None)
    rotation["last_transition_model"] = model
    rotation["last_transition_at"] = datetime.now().isoformat()
    rotation["questions_asked"] = 0
    rotation["last_question_id"] = None
    save_json(ROTATION_FILE, rotation)

    # Rebuild coverage
    rebuild_coverage()

    print(f"✓ Added {len(additions)} questions for Pass {target_pass} (model: {model})")
    print()
    for cat, new_id, text, source_id in additions:
        src = f" ← {source_id}" if source_id else ""
        print(f"  [{new_id}]{src}: {text[:70]}{'...' if len(text) > 70 else ''}")


def main():
    parser = argparse.ArgumentParser(description="Lifehug pass transition — follow-up question generator")
    subparsers = parser.add_subparsers(dest="command")

    # --status
    parser.add_argument("--status", action="store_true", help="Show transition state")

    # --prompt
    parser.add_argument("--prompt", action="store_true", help="Output AI prompt context")

    # --append
    parser.add_argument("--append", metavar="FILE", help="Append questions from JSON file (use - for stdin)")
    parser.add_argument("--model", metavar="MODEL", help="Model used to generate questions (for record-keeping)")
    parser.add_argument("--dry-run", action="store_true", help="Preview without writing")

    args = parser.parse_args()

    if args.status:
        cmd_status(args)
    elif args.prompt:
        cmd_prompt(args)
    elif args.append:
        cmd_append(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
