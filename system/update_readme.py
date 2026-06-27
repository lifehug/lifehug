#!/usr/bin/env python3
"""Lifehug — README Progress Updater

Refreshes per-category progress bullets and the Coverage summary in README.md
using current data from coverage.json and question-bank.md.

Usage:
    python3 system/update_readme.py           # Update README.md in place
    python3 system/update_readme.py --dry-run # Show what would change
"""

import argparse
import re

from lifehug_core import (
    README_FILE,
    QUESTIONS_FILE as QUESTION_BANK,
    compute_coverage,
    parse_categories,
    parse_questions,
    status_emoji,
    write_text,
)

OLD_FOCUS_TERM = "Spot" "light"


def parse_categories_from_bank():
    """Parse category metadata from question-bank.md."""
    if not QUESTION_BANK.exists():
        return {}

    return parse_categories(QUESTION_BANK.read_text())


def build_coverage_line(coverage, categories):
    """Build the coverage summary line."""
    if not coverage or "categories" not in coverage:
        return None

    total_answered = 0
    total_questions = 0
    focus_count = 0

    for cat_id, data in coverage["categories"].items():
        total_answered += data.get("answered", 0)
        total_questions += data.get("total", 0)
        cat_info = categories.get(cat_id, {})
        if cat_info.get("group") == "focus":
            focus_count += 1

    parts = [f"📊 {total_answered}/{total_questions} questions answered"]
    if focus_count > 0:
        parts.append(f"{focus_count} focus{'es' if focus_count != 1 else ''} active")

    return " · ".join(parts)


def update_category_bullets(readme, coverage, categories):
    """Update category progress bullets (e.g. '- 🔴 Origins (2/10)') in place.

    Matches lines like:
      - 🔴 Origins (2/10)
      - 🟡 The Problem (1/3)
      - 🟢 Becoming (5/7)

    Updates the emoji and counts based on current coverage data.
    """
    if not coverage or "categories" not in coverage:
        return readme

    # Build a lookup: category name → (emoji, answered, total)
    name_to_progress = {}
    for cat_id, data in coverage["categories"].items():
        cat_info = categories.get(cat_id, {})
        name = cat_info.get("name", cat_id)
        answered = data.get("answered", 0)
        total = data.get("total", 0)
        emoji = status_emoji(answered, total)
        name_to_progress[name] = (emoji, answered, total)
        if " & " in name:
            name_to_progress[name.split(" & ", 1)[0]] = (emoji, answered, total)
        # Also index without "Focus — " prefix for README matching
        for prefix in ("Focus — ", "Focus - ", "Focus: ", "Focus ", f"{OLD_FOCUS_TERM} — "):
            if name.startswith(prefix):
                short_name = name[len(prefix):]
                name_to_progress[short_name] = (emoji, answered, total)
                break

    # Match category bullets like: - 🔴 Origins (2/10)
    bullet_pattern = re.compile(
        r'^(- )[🔴🟡🟢⚪] (.+?) \(\d+/\d+\)(.*)$',
        re.MULTILINE
    )

    def replace_bullet(m):
        prefix = m.group(1)
        name = m.group(2)
        suffix = m.group(3)  # preserve trailing text (e.g. category descriptions)
        # Strip bold markers for lookup
        lookup = name.replace("**", "")
        if lookup in name_to_progress:
            emoji, answered, total = name_to_progress[lookup]
            return f"{prefix}{emoji} {name} ({answered}/{total}){suffix}"
        return m.group(0)

    return bullet_pattern.sub(replace_bullet, readme)


def focus_display_name(category_name):
    name = category_name
    for prefix in (
        "Focus — ", "Focus - ", "Focus: ", "Focus ",
        f"{OLD_FOCUS_TERM} — ", f"{OLD_FOCUS_TERM} - ",
        f"{OLD_FOCUS_TERM}: ", f"{OLD_FOCUS_TERM} ",
    ):
        if name.startswith(prefix):
            name = name[len(prefix):]
            break
    return re.sub(r"\s*\(.*?\)\s*$", "", name).strip()


def add_missing_focuses(readme, coverage, categories):
    if "## Focuses" not in readme:
        return readme

    existing = readme
    missing = []
    for cat_id, cat_info in sorted(categories.items()):
        if cat_info.get("group") != "focus":
            continue
        data = coverage["categories"].get(cat_id)
        if not data:
            continue
        display = focus_display_name(cat_info["name"])
        if f"**{display}**" in existing or re.search(rf"- [🔴🟡🟢⚪] {re.escape(display)} \(", existing):
            continue
        emoji = status_emoji(data["answered"], data["total"])
        missing.append(f"- {emoji} **{display}** ({data['answered']}/{data['total']})")

    if not missing:
        return readme

    pattern = re.compile(r"(## Focuses\n)(.*?)(?=\n## |\n---|\Z)", re.DOTALL)

    def replace(m):
        body = m.group(2).rstrip()
        addition = "\n".join(missing)
        if body:
            return f"{m.group(1)}{body}\n{addition}\n"
        return f"{m.group(1)}{addition}\n"

    return pattern.sub(replace, readme, count=1)


def update_coverage_section(readme, coverage_line):
    """Update or insert the ## Coverage section."""
    coverage_pattern = re.compile(
        r'(## Coverage\n).*?(?=\n## |\n---|\Z)',
        re.DOTALL
    )

    new_section = f"## Coverage\n{coverage_line}\n"

    if coverage_pattern.search(readme):
        return coverage_pattern.sub(new_section, readme)
    else:
        final_rule = readme.rfind("\n---\n")
        if final_rule >= 0:
            return readme[:final_rule] + f"\n{new_section}" + readme[final_rule:]
        else:
            return readme + f"\n{new_section}"


def update_readme(dry_run=False):
    """Update README.md with current progress."""
    if not README_FILE.exists():
        print("No README.md found. Nothing to update.")
        return False

    md_text = QUESTION_BANK.read_text()
    questions = parse_questions(md_text)
    categories = parse_categories(md_text)
    coverage = compute_coverage(questions, categories)

    readme = README_FILE.read_text()
    coverage_line = build_coverage_line(coverage, categories)

    if not coverage_line:
        print("No coverage data to update.")
        return False

    # Update per-category bullets
    new_readme = update_category_bullets(readme, coverage, categories)
    new_readme = add_missing_focuses(new_readme, coverage, categories)

    # Update coverage summary
    new_readme = update_coverage_section(new_readme, coverage_line)

    if new_readme == readme:
        print("README.md already up to date.")
        return False

    if dry_run:
        print("Changes:")
        # Show diff
        old_lines = readme.splitlines()
        new_lines = new_readme.splitlines()
        for i, (old, new) in enumerate(zip(old_lines, new_lines)):
            if old != new:
                print(f"  - {old}")
                print(f"  + {new}")
        print(f"\nCoverage: {coverage_line}")
        return True

    write_text(README_FILE, new_readme)
    print(f"Updated README.md: {coverage_line}")
    return True


def main():
    parser = argparse.ArgumentParser(description="Update README.md with current Lifehug progress")
    parser.add_argument("--dry-run", action="store_true", help="Show changes without writing")
    args = parser.parse_args()

    update_readme(dry_run=args.dry_run)


if __name__ == "__main__":
    main()
