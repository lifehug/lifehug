#!/usr/bin/env python3
"""Migrate protected Lifehug workspace files to Focus terminology."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

from lifehug_core import (
    FOCUS_RECS_FILE,
    LEGACY_FOCUS_RECS_FILE,
    PLANNER_STATE_FILE,
    QUESTION_QUEUE_FILE,
    QUESTIONS_FILE,
    README_FILE,
    ROTATION_FILE,
    write_json,
    write_text,
)


OLD_FOCUS_TERM = "Spot" "light"

TEXT_REPLACEMENTS = (
    (rf"\b{OLD_FOCUS_TERM}s\b", "Focuses"),
    (rf"\b{OLD_FOCUS_TERM}\b", "Focus"),
    (rf"\b{OLD_FOCUS_TERM.lower()}s\b", "focuses"),
    (rf"\b{OLD_FOCUS_TERM.lower()}\b", "focus"),
)


def focus_text(text: str) -> str:
    """Normalize current/generated text while preserving unrelated content."""
    for pattern, new in TEXT_REPLACEMENTS:
        text = re.sub(pattern, new, text)
    text = re.sub(r"(?m)^(##\s+[A-Z]:\s*)Focus\s*[—–-]\s*", r"\1Focus — ", text)
    return text


def focus_json(value: Any) -> Any:
    if isinstance(value, dict):
        out = {}
        for key, item in value.items():
            if key == OLD_FOCUS_TERM.lower() + "_frequency":
                new_key = "focus_frequency"
            elif key == OLD_FOCUS_TERM.lower():
                new_key = "focus"
            elif key == "un" + OLD_FOCUS_TERM.lower() + "ed_family":
                new_key = "unfocused_family"
            else:
                new_key = key
            out[new_key] = focus_json(item)
        return out
    if isinstance(value, list):
        return [focus_json(item) for item in value]
    if isinstance(value, str):
        return focus_text(value)
    return value


def migrate_text_file(path: Path, *, dry_run: bool) -> bool:
    if not path.exists():
        return False
    before = path.read_text(encoding="utf-8")
    after = focus_text(before)
    if after == before:
        return False
    if not dry_run:
        write_text(path, after)
    return True


def migrate_json_file(path: Path, *, dry_run: bool) -> bool:
    if not path.exists():
        return False
    data = json.loads(path.read_text(encoding="utf-8"))
    migrated = focus_json(data)
    if migrated == data:
        return False
    if not dry_run:
        write_json(path, migrated)
    return True


def migrate_recommendations(*, dry_run: bool) -> bool:
    if FOCUS_RECS_FILE.exists():
        return migrate_json_file(FOCUS_RECS_FILE, dry_run=dry_run)
    if not LEGACY_FOCUS_RECS_FILE.exists():
        return False
    data = json.loads(LEGACY_FOCUS_RECS_FILE.read_text(encoding="utf-8"))
    migrated = focus_json(data)
    if not dry_run:
        write_json(FOCUS_RECS_FILE, migrated)
        LEGACY_FOCUS_RECS_FILE.unlink()
    return True


def migrate_workspace(*, dry_run: bool = False) -> list[str]:
    changed: list[str] = []
    for path in (QUESTIONS_FILE, README_FILE):
        if migrate_text_file(path, dry_run=dry_run):
            changed.append(path.as_posix())

    for path in (ROTATION_FILE, PLANNER_STATE_FILE, QUESTION_QUEUE_FILE):
        if migrate_json_file(path, dry_run=dry_run):
            changed.append(path.as_posix())

    if migrate_recommendations(dry_run=dry_run):
        changed.append(FOCUS_RECS_FILE.as_posix())

    return changed


def main() -> None:
    parser = argparse.ArgumentParser(description="Migrate Lifehug workspace terminology to Focus.")
    parser.add_argument("--dry-run", action="store_true", help="Report files that would change")
    args = parser.parse_args()

    changed = migrate_workspace(dry_run=args.dry_run)
    if changed:
        action = "Would migrate" if args.dry_run else "Migrated"
        print(f"{action} {len(changed)} file(s):")
        for path in changed:
            print(f"- {path}")
    else:
        print("Focus terminology already migrated.")


if __name__ == "__main__":
    main()
