#!/usr/bin/env python3
"""Ingest an unprompted Lifehug story as owner-only source material."""

from __future__ import annotations

import argparse
import re
import sys
from datetime import datetime
from pathlib import Path

from lifehug_core import (
    MANUAL_SOURCES_DIR,
    QUESTION_CANDIDATES_FILE,
    REPO_DIR,
    now_utc,
    read_json,
    slugify,
    write_json,
    write_text,
)
from source_integrity import SCHEMA_VERSION, format_frontmatter, payload_sha256, register_source


def title_from_text(text: str) -> str:
    words = re.findall(r"[A-Za-z0-9']+", text.strip())
    if not words:
        return "Untitled Story"
    return " ".join(words[:8]).strip().title()


def unique_source_path(title: str, captured_at: str) -> Path:
    day = captured_at[:10] if captured_at else datetime.now().date().isoformat()
    base = f"{day}-{slugify(title)}"
    path = MANUAL_SOURCES_DIR / f"{base}.md"
    if not path.exists():
        return path
    index = 2
    while True:
        candidate = MANUAL_SOURCES_DIR / f"{base}-{index}.md"
        if not candidate.exists():
            return candidate
        index += 1


def load_candidates() -> dict:
    data = read_json(QUESTION_CANDIDATES_FILE, default=None)
    if not isinstance(data, dict):
        return {"version": 1, "candidates": []}
    data.setdefault("version", 1)
    data.setdefault("candidates", [])
    return data


def candidate_id(source_path: str, index: int) -> str:
    stem = slugify(Path(source_path).stem)
    return f"cand-{stem}-{index}"


def generate_candidates(title: str, text: str, source_path: str, created_at: str) -> list[dict]:
    compact = re.sub(r"\s+", " ", text).strip()
    subject = title.strip() or "this story"
    templates = [
        (
            "foundation",
            f"What background would someone need before reading the story of {subject}?",
            0.55,
            "Establishes context before deeper narrative work.",
        ),
        (
            "scene",
            f"Can you walk through {subject} as a scene, moment by moment?",
            0.62,
            "Turns an unprompted memory into concrete story material.",
        ),
        (
            "relationships",
            f"Who else mattered in {subject}, and what did this reveal about the relationship?",
            0.5,
            "Looks for people or relationship threads introduced by the source.",
        ),
        (
            "meaning",
            f"What does {subject} help explain about who you became?",
            0.48,
            "Connects the source to the larger Lifehug story.",
        ),
    ]
    if len(compact) > 500:
        templates.append((
            "gap",
            f"What part of {subject} still feels missing or unresolved?",
            0.45,
            "Long sources often expose gaps worth turning into follow-up questions.",
        ))

    candidates = []
    for index, (kind, question, priority, reason) in enumerate(templates, start=1):
        candidates.append({
            "id": candidate_id(source_path, index),
            "text": question,
            "source_path": source_path,
            "target_page": None,
            "kind": kind,
            "priority": priority,
            "reason": reason,
            "status": "candidate",
            "created_at": created_at,
        })
    return candidates


def append_candidates(candidates: list[dict]) -> None:
    data = load_candidates()
    existing_ids = {item.get("id") for item in data["candidates"]}
    for candidate in candidates:
        if candidate["id"] not in existing_ids:
            data["candidates"].append(candidate)
    write_json(QUESTION_CANDIDATES_FILE, data)


def frontmatter(args: argparse.Namespace, source_path: str, candidate_ids: list[str], payload: str) -> str:
    values = {
        "title": args.title,
        "type": "unprompted_story",
        "source_id": f"manual:{Path(source_path).stem}",
        "source_medium": args.source,
        "source": args.source,
        "captured_at": args.captured_at,
        "visibility": "owner_only",
        "status": "raw",
        "immutable": True,
        "schema_version": SCHEMA_VERSION,
        "source_path": source_path,
        "content_sha256": payload_sha256(payload),
        "related_pages": [],
        "candidate_questions": candidate_ids,
    }
    return format_frontmatter(values)


def main() -> int:
    parser = argparse.ArgumentParser(description="Ingest an unprompted Lifehug story")
    parser.add_argument("--source", default="manual", help="Source label, e.g. telegram, voice, email, manual")
    parser.add_argument("--title", default=None)
    parser.add_argument("--captured-at", default=now_utc())
    parser.add_argument("--no-candidates", action="store_true", help="Save source without generating candidate questions")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    story = sys.stdin.read().strip()
    if not story:
        print("Error: story text must be provided on stdin", file=sys.stderr)
        return 1

    args.title = args.title or title_from_text(story)
    source_path = unique_source_path(args.title, args.captured_at)
    relative_source = source_path.relative_to(REPO_DIR).as_posix()
    created_at = now_utc()
    candidates = [] if args.no_candidates else generate_candidates(args.title, story, relative_source, created_at)

    payload = f"# {args.title}\n\n{story}\n"
    content = f"{frontmatter(args, relative_source, [c['id'] for c in candidates], payload)}\n\n{payload}"

    if args.dry_run:
        print(f"would write {relative_source}")
        print(f"would add {len(candidates)} question candidate(s)")
        return 0

    write_text(source_path, content)
    register_source(source_path)
    if candidates:
        append_candidates(candidates)

    print(f"✓ Ingested story: {relative_source}")
    if candidates:
        print(f"✓ Added candidates: {', '.join(c['id'] for c in candidates)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
