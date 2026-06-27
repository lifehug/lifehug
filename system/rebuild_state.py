#!/usr/bin/env python3
"""Rebuild derived Lifehug state from source files."""

from __future__ import annotations

import argparse
from datetime import datetime

from lifehug_core import ANSWERS_DIR, QUESTIONS_FILE, ROTATION_FILE, parse_questions, read_json, rebuild_coverage, write_json
from source_integrity import scan_sources, sync_manifest
from update_readme import update_readme


def answer_timestamp(question_id: str) -> str | None:
    answer_file = ANSWERS_DIR / f"{question_id}.md"
    if not answer_file.exists():
        return None
    return datetime.fromtimestamp(answer_file.stat().st_mtime).isoformat()


def main():
    parser = argparse.ArgumentParser(description="Rebuild Lifehug derived state")
    parser.add_argument("--fix-rotation", action="store_true", help="Refresh answer counters and clear stale pending IDs")
    parser.add_argument("--readme", action="store_true", help="Update README.md")
    args = parser.parse_args()

    coverage = rebuild_coverage()
    questions = parse_questions(QUESTIONS_FILE.read_text())
    answered_ids = {str(q["id"]) for q in questions if q["answered"]}

    if args.fix_rotation:
        rotation = read_json(ROTATION_FILE, default={}) or {}
        rotation["questions_answered"] = len(answered_ids)
        if rotation.get("last_question_id") in answered_ids:
            last_id = rotation.get("last_question_id")
            id_changed = rotation.get("last_answered_id") != last_id
            rotation["last_answered_id"] = last_id
            ts = answer_timestamp(last_id)
            if ts:
                rotation["last_answered_at"] = ts
            elif id_changed or not rotation.get("last_answered_at"):
                rotation["last_answered_at"] = datetime.now().isoformat()
        if rotation.get("pending_answer_question_id") in answered_ids:
            rotation.pop("pending_answer_question_id", None)
        write_json(ROTATION_FILE, rotation)

    if args.readme:
        update_readme()

    manifest = sync_manifest(scan_sources(), write=True, prune_missing=True)

    total = sum(data["total"] for data in coverage["categories"].values())
    answered = sum(data["answered"] for data in coverage["categories"].values())
    print(f"✓ Rebuilt coverage: {answered}/{total}")
    print(f"✓ Refreshed source manifest: {len(manifest.get('sources', {}))} source(s)")
    if args.fix_rotation:
        print("✓ Refreshed rotation counters")
    if args.readme:
        print("✓ Refreshed README")


if __name__ == "__main__":
    main()
