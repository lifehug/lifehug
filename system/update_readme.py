#!/usr/bin/env python3
"""Lifehug — README Progress Updater

Refreshes the Coverage section in README.md with current progress from coverage.json.
Also updates project category indicators inline.

Usage:
    python3 system/update_readme.py           # Update README.md in place
    python3 system/update_readme.py --dry-run # Show what would change
"""

import argparse
import json
import re
from pathlib import Path

SYSTEM_DIR = Path(__file__).parent
REPO_DIR = SYSTEM_DIR.parent
README_FILE = REPO_DIR / "README.md"
COVERAGE_FILE = SYSTEM_DIR / "coverage.json"
QUESTION_BANK = SYSTEM_DIR / "question-bank.md"


def load_coverage():
    """Load coverage data from coverage.json."""
    if not COVERAGE_FILE.exists():
        return None
    with open(COVERAGE_FILE) as f:
        return json.load(f)


def parse_categories_from_bank():
    """Parse category metadata from question-bank.md."""
    if not QUESTION_BANK.exists():
        return {}

    md = QUESTION_BANK.read_text()
    categories = {}
    header_pattern = re.compile(r'^## ([A-Z]): (.+?)(?:\s*\(.*\))?\s*$', re.MULTILINE)

    group = "main"
    for line in md.splitlines():
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
            if cat_id >= "K":
                cat_group = "spotlight"
            elif cat_id >= "F":
                cat_group = "project"
            else:
                cat_group = "main"
            categories[cat_id] = {"name": name, "group": cat_group}

    return categories


def status_emoji(answered, total):
    """Return status emoji based on coverage ratio."""
    if total == 0:
        return "⚪"
    ratio = answered / total
    if ratio >= 0.7:
        return "🟢"
    elif ratio >= 0.3:
        return "🟡"
    else:
        return "🔴"


def build_coverage_line(coverage, categories):
    """Build the coverage summary line."""
    if not coverage or "categories" not in coverage:
        return None

    total_answered = 0
    total_questions = 0
    spotlight_count = 0

    for cat_id, data in coverage["categories"].items():
        total_answered += data.get("answered", 0)
        total_questions += data.get("total", 0)
        cat_info = categories.get(cat_id, {})
        if cat_info.get("group") == "spotlight":
            spotlight_count += 1

    parts = [f"📊 {total_answered}/{total_questions} questions answered"]
    if spotlight_count > 0:
        parts.append(f"{spotlight_count} spotlight{'s' if spotlight_count != 1 else ''} active")

    return " · ".join(parts)


def build_category_progress(coverage, categories):
    """Build per-category progress strings grouped by type."""
    if not coverage or "categories" not in coverage:
        return {}

    progress = {}
    for cat_id in sorted(coverage["categories"].keys()):
        data = coverage["categories"][cat_id]
        answered = data.get("answered", 0)
        total = data.get("total", 0)
        emoji = status_emoji(answered, total)
        cat_info = categories.get(cat_id, {})
        name = cat_info.get("name", cat_id)
        progress[cat_id] = f"{emoji} {name} ({answered}/{total})"

    return progress


def update_readme(dry_run=False):
    """Update the Coverage section in README.md."""
    if not README_FILE.exists():
        print("No README.md found. Nothing to update.")
        return False

    coverage = load_coverage()
    categories = parse_categories_from_bank()

    if not coverage:
        print("No coverage.json found. Run ask.py --status first.")
        return False

    readme = README_FILE.read_text()
    coverage_line = build_coverage_line(coverage, categories)

    if not coverage_line:
        print("No coverage data to update.")
        return False

    # Update or insert Coverage section
    # Look for existing ## Coverage section and replace its content
    coverage_pattern = re.compile(
        r'(## Coverage\n).*?(?=\n## |\n---|\Z)',
        re.DOTALL
    )

    new_coverage_section = f"## Coverage\n{coverage_line}\n"

    if coverage_pattern.search(readme):
        new_readme = coverage_pattern.sub(new_coverage_section, readme)
    else:
        # Insert before the final --- or at the end
        final_rule = readme.rfind("\n---\n")
        if final_rule >= 0:
            new_readme = readme[:final_rule] + f"\n{new_coverage_section}" + readme[final_rule:]
        else:
            new_readme = readme + f"\n{new_coverage_section}"

    if new_readme == readme:
        print("README.md already up to date.")
        return False

    if dry_run:
        print("Would update Coverage section to:")
        print(f"  {coverage_line}")
        return True

    README_FILE.write_text(new_readme)
    print(f"Updated README.md: {coverage_line}")
    return True


def main():
    parser = argparse.ArgumentParser(description="Update README.md with current Lifehug progress")
    parser.add_argument("--dry-run", action="store_true", help="Show changes without writing")
    args = parser.parse_args()

    update_readme(dry_run=args.dry_run)


if __name__ == "__main__":
    main()
