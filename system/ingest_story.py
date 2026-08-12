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
    record_learning_failure,
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


def generate_witness_candidates(witness: str, title: str, source_path: str, created_at: str) -> list[dict]:
    """Follow-ups for a second-voice account — aimed at the AUTHOR, about the
    gap between the two tellings. Conflicting accounts are data, not errors."""
    subject = title.strip() or "this account"
    templates = [
        ("contradiction",
         f"Where does {witness}'s telling differ from how you remember it — and what does the gap itself tell you?",
         0.65,
         "Perspective gaps between accounts are signal to preserve, not resolve."),
        ("meaning",
         f"What did {witness} notice or feel in {subject} that you had missed entirely?",
         0.6,
         "The second voice reveals what the author's own account couldn't see."),
        ("relationship",
         f"Hearing {witness} tell it — what does their version show you about what this meant to THEM?",
         0.55,
         "Dyadic understanding: the same event carries different weight on each side."),
    ]
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
            "story_function": kind,
            "created_at": created_at,
        })
    return candidates


def generate_opinion_candidates(title: str, source_path: str, created_at: str) -> list[dict]:
    """Socratic follow-ups for a stated OPINION — deepen and test the position
    instead of reframing it into narrative scenes. Each carries a planner
    SELF_FUNCTIONS story_function so the weekly self-knowledge slot can draw
    from these without any planner changes."""
    subject = title.strip() or "this position"
    templates = [
        ("origin",
         f"Where did this belief — {subject} — come from? Who taught it to you, or what moment forged it?",
         "value", 0.62,
         "A position becomes story when it finds its origin."),
        ("counterexample",
         f"What's the strongest counterexample you've lived — a time the lens of {subject} failed you?",
         "contradiction", 0.6,
         "Testing a position against lived experience deepens it honestly."),
        ("evolution",
         f"How has this position changed — what did you believe about {subject} ten years ago?",
         "growth_edge", 0.55,
         "A belief's trajectory is self-knowledge signal."),
        ("dissent",
         f"Who would disagree with you most about {subject}, and what do they see that you might not?",
         "perception_by_others", 0.5,
         "Steelmanning dissent reveals the position's real edges."),
        ("stakes",
         f"What does holding this belief about {subject} cost you — or protect you from?",
         "fear", 0.48,
         "The function a belief serves is part of who the author is."),
    ]
    candidates = []
    for index, (kind, question, story_function, priority, reason) in enumerate(templates, start=1):
        candidates.append({
            "id": candidate_id(source_path, index),
            "text": question,
            "source_path": source_path,
            "target_page": None,
            "kind": kind,
            "priority": priority,
            "reason": reason,
            "status": "candidate",
            "story_function": story_function,
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


def content_source_type(args: argparse.Namespace) -> str:
    """The raw-source content kind for this ingest — shared by the frontmatter
    and the Conversation turn prompt (issue #117) so the register can match
    it (a witness account is another person's words; an opinion gets
    Socratic energy rather than narrative-scene probing).

    A witness account is ANOTHER PERSON's words about shared events — a
    second voice. It is never merged with the author's account; when the
    two disagree, the wiki preserves both ("perspectives differ" is data,
    not an error to resolve). An opinion is the author's STATED POSITION —
    a lens on life rather than an event account. Same raw-source contract;
    different content kind.
    """
    if getattr(args, "witness", None):
        return "witness_account"
    if getattr(args, "kind", "story") == "opinion":
        return "opinion"
    return "unprompted_story"


def conversation_channel_for_source(source_label: str) -> str:
    """Map ``--source`` to a Conversation ``channel`` (issue #117).

    ``conversation.VALID_CHANNELS`` is exactly ``{telegram, web, cli}`` —
    every other source label (the default ``manual``, ``voice``, ``email``,
    ...) reads as an operator/CLI-mediated ingest, so it maps to ``cli``.
    """
    label = (source_label or "").strip().lower()
    if label in ("telegram", "web"):
        return label
    return "cli"


def run_story_conversation_hook(
    *, args: argparse.Namespace, relative_source: str, story_text: str, source_type: str,
) -> None:
    """Best-effort: open/continue a Conversation and send ONE immediate turn.

    Never blocks, delays, or fails the ingest itself — the same
    swallow-everything posture as ``process_answer.run_post_answer_delivery``.
    ``run_story_conversation_turn`` already degrades internally on a
    not-ready provider or a definitive generation/lint/send failure (the
    no-session fallback, contract #117 Part A #3); this wrapper only guards
    against a genuinely unexpected internal error reaching the ingest path.
    """
    try:
        from conversation_delivery import run_story_conversation_turn  # noqa: PLC0415

        outcome = run_story_conversation_turn(
            source_id=f"story:{relative_source}",
            source_path=relative_source,
            title=args.title,
            story_text=story_text,
            source_type=source_type,
            channel=conversation_channel_for_source(args.source),
        )
        if outcome.status == "confirmed":
            print(f"✓ Conversation turn: confirmed ({relative_source})")
    except Exception:  # noqa: BLE001 — the ingest itself must never fail here
        record_learning_failure(
            "ingest_story", "conversation_turn", "internal_error",
            context={"source_id": f"story:{relative_source}"},
        )


def frontmatter(args: argparse.Namespace, source_path: str, candidate_ids: list[str], payload: str) -> str:
    source_type = content_source_type(args)
    witness = getattr(args, "witness", None)
    values = {
        "title": args.title,
        "type": source_type,
        "source_id": f"manual:{Path(source_path).stem}",
        "source_medium": args.source,
        "source": args.source,
        "captured_at": args.captured_at,
        "visibility": "owner_only",
        "sensitivity": getattr(args, "sensitivity", "private"),
        "status": "raw",
        "immutable": True,
        "schema_version": SCHEMA_VERSION,
        "source_path": source_path,
        "content_sha256": payload_sha256(payload),
        "related_pages": [],
        "candidate_questions": candidate_ids,
    }
    if witness:
        values["witness"] = witness
        values["witness_slug"] = slugify(witness)
    return format_frontmatter(values)


def main() -> int:
    parser = argparse.ArgumentParser(description="Ingest an unprompted Lifehug story")
    parser.add_argument("--source", default="manual", help="Source label, e.g. telegram, voice, email, manual")
    parser.add_argument("--title", default=None)
    parser.add_argument("--captured-at", default=now_utc())
    parser.add_argument("--witness", default=None, metavar="PERSON",
                        help="This is ANOTHER PERSON's account (a second voice), e.g. --witness Mom. "
                             "Stored as a witness_account source, attributed to them, never merged "
                             "with the author's version of events.")
    parser.add_argument("--sensitivity", default="private",
                        choices=["private", "family", "friends", "public"],
                        help="Sensitivity tier for future audience builds (default private)")
    parser.add_argument("--kind", default="story", choices=["story", "opinion"],
                        help="Content kind: story (default) or opinion — the author's stated "
                             "position/lens on life. Opinions get Socratic follow-ups instead "
                             "of narrative scene prompts, and can seed essay artifacts.")
    parser.add_argument("--no-candidates", action="store_true", help="Save source without generating candidate questions")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    story = sys.stdin.read().strip()
    if not story:
        print("Error: story text must be provided on stdin", file=sys.stderr)
        return 1

    if args.witness and args.kind == "opinion":
        print("Error: --kind opinion cannot be combined with --witness "
              "(a witness account is someone else's words; an opinion is the author's)",
              file=sys.stderr)
        return 1

    if args.witness:
        default_title = f"{args.witness}'s account — {title_from_text(story)}"
        args.title = args.title or default_title
    args.title = args.title or title_from_text(story)
    source_path = unique_source_path(args.title, args.captured_at)
    relative_source = source_path.relative_to(REPO_DIR).as_posix()
    created_at = now_utc()
    if args.no_candidates:
        candidates = []
    elif args.witness:
        candidates = generate_witness_candidates(args.witness, args.title, relative_source, created_at)
    elif args.kind == "opinion":
        candidates = generate_opinion_candidates(args.title, relative_source, created_at)
    else:
        candidates = generate_candidates(args.title, story, relative_source, created_at)

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

    # Issue #117: an unprompted story now opens or continues a Conversation
    # and gets an immediate turn — best-effort, never blocking the ingest.
    # Filed template candidates above are the immediate-value floor either
    # way (contract, "Template candidates are generated at ingest time in
    # BOTH cases").
    run_story_conversation_hook(
        args=args,
        relative_source=relative_source,
        story_text=story,
        source_type=content_source_type(args),
    )

    if args.witness:
        print(f"✓ Ingested witness account from {args.witness}: {relative_source}")
        print(f"  Their words, kept separate from yours — the wiki renders both accounts side by side.")
    elif args.kind == "opinion":
        print(f"✓ Ingested opinion: {relative_source}")
    else:
        print(f"✓ Ingested story: {relative_source}")
    if candidates:
        print(f"✓ Added candidates: {', '.join(c['id'] for c in candidates)}")
    if args.kind == "opinion":
        print(f"Next: python3 system/lifehug.py artifact new --format essay --seed {relative_source}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
