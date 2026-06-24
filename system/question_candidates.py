#!/usr/bin/env python3
"""Review, update, and promote Lifehug question candidates."""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

from lifehug_core import (
    QUESTION_CANDIDATES_FILE,
    QUESTIONS_FILE,
    now_utc,
    parse_categories,
    parse_questions,
    read_json,
    write_json,
    write_text,
)

from lifehug_core import STORY_FUNCTIONS

VALID_STATUSES = {"candidate", "accepted", "rejected", "deferred", "promoted"}
PROMOTABLE_STATUSES = {"candidate", "accepted", "deferred"}

# ---------------------------------------------------------------------------
# Quality checker — operationalizes system/research.md
# ---------------------------------------------------------------------------

YES_NO_PATTERNS = re.compile(
    r"^(did you|do you|have you|were you|was it|is it|are you|can you|could you|would you|should you)\b",
    re.IGNORECASE,
)

TOO_BROAD_PATTERNS = [
    re.compile(r"^tell me about \.+\.$", re.IGNORECASE),
    re.compile(r"^what (do you think|are your thoughts) about", re.IGNORECASE),
    re.compile(r"^how do you feel about .+\?$", re.IGNORECASE),
]

SCENE_MARKERS = [
    "walk me through", "describe the moment", "what did it look like",
    "what did it feel like", "what did you see", "what did you hear",
    "specific day", "specific moment", "what was the room",
    "what were you wearing", "what did they say",
]

EMOTION_MARKERS = [
    "scared", "proud", "angry", "sad", "happy", "afraid",
    "excited", "ashamed", "grateful", "hurt", "loved",
    "stake", "risk", "fear", "hope", "tension", "conflict",
]


def check_quality(text: str, *, source_path: str | None = None, existing_questions: list[dict] | None = None) -> dict:
    """Score a candidate question for quality. Returns {score, flags, notes}.

    Score: 0.0 (terrible) to 1.0 (excellent).
    Flags: list of issue strings.
    Notes: human-readable quality summary.
    """
    flags: list[str] = []
    score = 1.0
    text_lower = text.strip().lower()

    # Check yes/no wording
    if YES_NO_PATTERNS.match(text.strip()):
        flags.append("yes_no_wording")
        score -= 0.25

    # Check too broad/generic
    for pattern in TOO_BROAD_PATTERNS:
        if pattern.match(text.strip()):
            flags.append("too_broad")
            score -= 0.20
            break

    # Check for scene or emotional path
    has_scene = any(marker in text_lower for marker in SCENE_MARKERS)
    has_emotion = any(marker in text_lower for marker in EMOTION_MARKERS)
    if not has_scene and not has_emotion:
        if not any(kw in text_lower for kw in ["who", "when", "where", "why", "how", "what"]):
            flags.append("no_scene_or_stakes_path")
            score -= 0.15

    # Check missing source
    if not source_path:
        flags.append("no_source_citation")
        score -= 0.10

    # Check for short/vague questions
    word_count = len(text.split())
    if word_count < 5:
        flags.append("too_short")
        score -= 0.15
    elif word_count < 8:
        flags.append("possibly_vague")
        score -= 0.05

    # Check duplicate against existing questions
    if existing_questions:
        wanted = normalize_question(text)
        for q in existing_questions:
            if normalize_question(str(q.get("text", ""))) == wanted:
                flags.append(f"duplicate_of_{q.get('id', 'unknown')}")
                score -= 0.50
                break

    score = max(0.0, min(1.0, score))
    notes = ", ".join(flags) if flags else "good quality"
    return {"score": round(score, 2), "flags": flags, "notes": notes}


def validate_story_function(value: str | None) -> str | None:
    """Return value if it's a valid story function, else None."""
    if value and value in STORY_FUNCTIONS:
        return value
    return None


def load_store(path: Path = QUESTION_CANDIDATES_FILE) -> dict:
    data = read_json(path, default=None)
    if not isinstance(data, dict):
        return {"version": 1, "candidates": []}
    data.setdefault("version", 1)
    data.setdefault("candidates", [])
    return data


def save_store(data: dict, path: Path = QUESTION_CANDIDATES_FILE) -> None:
    data["last_updated"] = now_utc()
    write_json(path, data)


def find_candidate(data: dict, candidate_id: str) -> dict:
    for candidate in data.get("candidates", []):
        if candidate.get("id") == candidate_id:
            return candidate
    raise ValueError(f"candidate not found: {candidate_id}")


def normalize_question(text: str) -> str:
    text = text.strip().lower()
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def next_question_id(question_bank_text: str, category: str) -> str:
    category = category.upper()
    questions = parse_questions(question_bank_text)
    numbers = []
    for question in questions:
        qid = str(question["id"])
        match = re.match(rf"^{re.escape(category)}(\d+)", qid)
        if match:
            numbers.append(int(match.group(1)))
    if not numbers:
        return f"{category}1"
    return f"{category}{max(numbers) + 1}"


def ensure_category_exists(question_bank_text: str, category: str) -> None:
    categories = parse_categories(question_bank_text)
    if category.upper() not in categories:
        raise ValueError(f"category not found in question bank: {category.upper()}")


def ensure_not_duplicate(question_bank_text: str, text: str) -> None:
    wanted = normalize_question(text)
    for question in parse_questions(question_bank_text):
        if normalize_question(str(question["text"])) == wanted:
            raise ValueError(f"duplicate question text already exists: {question['id']}")


def insert_question(
    question_bank_text: str,
    category: str,
    question_id: str,
    question_text: str,
    candidate: dict,
    promoted_at: str,
) -> str:
    category = category.upper()
    ensure_category_exists(question_bank_text, category)

    pattern = re.compile(
        rf"^(## {re.escape(category)}:.+?)(?=\n## |\Z)",
        re.MULTILINE | re.DOTALL,
    )
    match = pattern.search(question_bank_text)
    if not match:
        raise ValueError(f"category section not found: {category}")

    source = candidate.get("source_path") or "unknown"
    provenance = (
        f"  <!-- candidate: {candidate.get('id')}; "
        f"source: {source}; promoted: {promoted_at} -->"
    )
    line = f"- [ ] {question_id}: {question_text.strip()}\n{provenance}"
    section = match.group(1).rstrip() + "\n" + line + "\n"
    return question_bank_text[:match.start()] + section + question_bank_text[match.end():]


def promote_candidate_record(data: dict, question_bank_text: str, candidate_id: str, category: str) -> tuple[str, str]:
    candidate = find_candidate(data, candidate_id)
    status = candidate.get("status", "candidate")
    if status not in PROMOTABLE_STATUSES:
        raise ValueError(f"candidate {candidate_id} cannot be promoted from status '{status}'")

    text = str(candidate.get("text", "")).strip()
    if not text:
        raise ValueError(f"candidate has no text: {candidate_id}")

    category = category.upper()
    ensure_category_exists(question_bank_text, category)
    ensure_not_duplicate(question_bank_text, text)
    question_id = next_question_id(question_bank_text, category)
    promoted_at = now_utc()
    updated_bank = insert_question(question_bank_text, category, question_id, text, candidate, promoted_at)

    candidate["status"] = "promoted"
    candidate["target_category"] = category
    candidate["promoted_question_id"] = question_id
    candidate["promoted_at"] = promoted_at
    candidate["updated_at"] = promoted_at
    return updated_bank, question_id


def update_candidate(
    data: dict,
    candidate_id: str,
    *,
    status: str | None = None,
    target_page: str | None = None,
    target_category: str | None = None,
    priority: float | None = None,
    reason: str | None = None,
) -> dict:
    candidate = find_candidate(data, candidate_id)
    if status:
        if status not in VALID_STATUSES:
            raise ValueError(f"invalid status: {status}")
        if candidate.get("status") == "promoted" and status != "promoted":
            raise ValueError("promoted candidates cannot be moved back to another status")
        candidate["status"] = status
    if target_page is not None:
        candidate["target_page"] = target_page or None
    if target_category is not None:
        candidate["target_category"] = target_category.upper() if target_category else None
    if priority is not None:
        candidate["priority"] = priority
    if reason is not None:
        candidate["reason"] = reason
    candidate["updated_at"] = now_utc()
    return candidate


def filter_candidates(candidates: list[dict], args: argparse.Namespace) -> list[dict]:
    rows = candidates
    if args.status:
        rows = [c for c in rows if c.get("status", "candidate") == args.status]
    if args.kind:
        rows = [c for c in rows if c.get("kind") == args.kind]
    if args.source:
        rows = [c for c in rows if args.source in str(c.get("source_path", ""))]
    if args.target_page:
        rows = [c for c in rows if args.target_page in str(c.get("target_page", ""))]
    if args.min_priority is not None:
        rows = [c for c in rows if float(c.get("priority", 0) or 0) >= args.min_priority]
    rows.sort(key=lambda c: (c.get("status", "candidate") != "candidate", -float(c.get("priority", 0) or 0), c.get("created_at", "")))
    return rows[: args.limit]


def print_candidate(candidate: dict, *, detail: bool = False) -> None:
    status = candidate.get("status", "candidate")
    priority = candidate.get("priority", 0)
    source = candidate.get("source_path") or "no-source"
    print(f"- {candidate.get('id')} [{status}, {priority}]: {candidate.get('text')}")
    if detail:
        print(f"  source: {source}")
        if candidate.get("kind"):
            print(f"  kind: {candidate.get('kind')}")
        if candidate.get("target_category"):
            print(f"  target_category: {candidate.get('target_category')}")
        if candidate.get("target_page"):
            print(f"  target_page: {candidate.get('target_page')}")
        if candidate.get("reason"):
            print(f"  reason: {candidate.get('reason')}")
        if candidate.get("promoted_question_id"):
            print(f"  promoted_question_id: {candidate.get('promoted_question_id')}")


def cmd_list(args: argparse.Namespace) -> int:
    data = load_store()
    rows = filter_candidates(list(data.get("candidates", [])), args)
    if args.json:
        print(json.dumps(rows, indent=2))
        return 0

    counts = Counter(c.get("status", "candidate") for c in data.get("candidates", []))
    print("Question Candidates")
    if counts:
        print("Statuses: " + ", ".join(f"{status}={counts[status]}" for status in sorted(counts)))
    else:
        print("Statuses: none")
    print()
    for candidate in rows:
        print_candidate(candidate, detail=args.detail)
    if not rows:
        print("No matching candidates.")
    return 0


def cmd_stats(_args: argparse.Namespace) -> int:
    data = load_store()
    candidates = data.get("candidates", [])
    if not candidates:
        print("No candidates.")
        return 0

    print("Candidate Statistics")
    print()

    # By status
    status_counts = Counter(c.get("status", "candidate") for c in candidates)
    print("By status:")
    for status in sorted(status_counts):
        print(f"  {status}: {status_counts[status]}")

    # By source type
    source_counts: Counter = Counter()
    for c in candidates:
        sp = str(c.get("source_path", ""))
        if "sources/x/" in sp:
            source_counts["x"] += 1
        elif "sources/email/" in sp:
            source_counts["email"] += 1
        elif "sources/instagram/" in sp:
            source_counts["instagram"] += 1
        elif "sources/manual/" in sp:
            source_counts["manual"] += 1
        elif "answers/" in sp:
            source_counts["answer"] += 1
        else:
            source_counts["other"] += 1
    print("\nBy source:")
    for source in sorted(source_counts):
        print(f"  {source}: {source_counts[source]}")

    # By category
    cat_counts = Counter(c.get("target_category", "unassigned") or "unassigned" for c in candidates)
    print("\nBy target category:")
    for cat in sorted(cat_counts):
        print(f"  {cat}: {cat_counts[cat]}")

    # Quality summary (sample first 50)
    sample = candidates[:50]
    quality_scores = [check_quality(str(c.get("text", "")), source_path=c.get("source_path")).get("score", 0) for c in sample]
    if quality_scores:
        avg = sum(quality_scores) / len(quality_scores)
        weak = sum(1 for s in quality_scores if s < 0.6)
        print(f"\nQuality (sampled {len(sample)}):")
        print(f"  avg score: {avg:.2f}")
        print(f"  weak (<0.6): {weak}")

    return 0


def cmd_review(args: argparse.Namespace) -> int:
    args.status = args.status or "candidate"
    args.detail = True
    args.json = False
    # Add quality info during review
    data = load_store()
    rows = filter_candidates(list(data.get("candidates", [])), args)
    if not rows:
        print("No matching candidates.")
        return 0
    # Load existing questions for dupe check
    try:
        existing = parse_questions(QUESTIONS_FILE.read_text(encoding="utf-8"))
    except FileNotFoundError:
        existing = []
    for candidate in rows:
        print_candidate(candidate, detail=True)
        quality = check_quality(
            str(candidate.get("text", "")),
            source_path=candidate.get("source_path"),
            existing_questions=existing,
        )
        if quality["flags"]:
            print(f"  quality: {quality['score']:.2f} — {quality['notes']}")
        else:
            print(f"  quality: {quality['score']:.2f} ✓")
    return 0


def cmd_update(args: argparse.Namespace) -> int:
    data = load_store()
    candidate = update_candidate(
        data,
        args.candidate_id,
        status=args.status,
        target_page=args.target_page,
        target_category=args.target_category,
        priority=args.priority,
        reason=args.reason,
    )
    save_store(data)
    print(f"✓ Updated {candidate['id']} [{candidate.get('status', 'candidate')}]")
    return 0


def cmd_promote(args: argparse.Namespace) -> int:
    data = load_store()
    question_bank_text = QUESTIONS_FILE.read_text(encoding="utf-8")
    updated_bank, question_id = promote_candidate_record(data, question_bank_text, args.candidate_id, args.category)
    write_text(QUESTIONS_FILE, updated_bank)
    save_store(data)
    print(f"✓ Promoted {args.candidate_id} to {question_id}")
    return 0


def add_filters(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--status", choices=sorted(VALID_STATUSES))
    parser.add_argument("--kind")
    parser.add_argument("--source")
    parser.add_argument("--target-page")
    parser.add_argument("--min-priority", type=float)
    parser.add_argument("--limit", type=int, default=25)
    parser.add_argument("--detail", action="store_true")
    parser.add_argument("--json", action="store_true")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Lifehug question candidate manager")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("list", help="List candidate questions")
    add_filters(p)
    p.set_defaults(func=cmd_list)

    p = sub.add_parser("review", help="Show detailed candidate questions")
    add_filters(p)
    p.set_defaults(func=cmd_review)

    p = sub.add_parser("update", help="Update candidate metadata or status")
    p.add_argument("candidate_id")
    p.add_argument("--status", choices=sorted(VALID_STATUSES))
    p.add_argument("--target-page")
    p.add_argument("--target-category")
    p.add_argument("--priority", type=float)
    p.add_argument("--reason")
    p.set_defaults(func=cmd_update)

    p = sub.add_parser("promote", help="Promote a candidate into question-bank.md")
    p.add_argument("candidate_id")
    p.add_argument("--category", required=True)
    p.set_defaults(func=cmd_promote)

    p = sub.add_parser("stats", help="Show candidate statistics")
    p.set_defaults(func=cmd_stats)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        return args.func(args)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
