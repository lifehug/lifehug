#!/usr/bin/env python3
"""Review, update, and promote Lifehug question candidates."""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from lifehug_core import (
    QUESTION_CANDIDATES_FILE,
    QUESTIONS_FILE,
    now_utc,
    parse_categories,
    parse_questions,
    read_json,
    record_learning_failure,
    write_json,
    write_text,
)

from lifehug_core import STORY_FUNCTIONS

VALID_STATUSES = {"candidate", "accepted", "rejected", "deferred", "promoted", "auto_promoted", "needs_review", "expired"}
PROMOTABLE_STATUSES = {"candidate", "accepted", "deferred"}
# needs_review candidates are re-scored every auto-promote run (the quality
# profile shifts weekly), so a near-miss can graduate later instead of dying
# in a one-way graveyard. Score-based reasons resurface; structural reasons
# (missing category, near-duplicate) stay parked for a human.
RESURFACEABLE_REVIEW_REASONS = ("score", "quality")

# ---------------------------------------------------------------------------
# Auto-promotion constants
# ---------------------------------------------------------------------------

# Quality threshold to auto-promote (priority × story_function_multiplier).
AUTO_PROMOTE_THRESHOLD = 0.82

# Below this score but above NEEDS_REVIEW_THRESHOLD → needs_review.
NEEDS_REVIEW_THRESHOLD = 0.70

# check_quality() score below which a candidate is parked for review even if
# its promotion score clears the threshold (yes/no wording, near-dupes, vague).
QUALITY_GATE_MIN = 0.60

# Candidates older than this that were never promoted expire (kept for audit).
# Deferred candidates are exempt — a human explicitly said "wait".
CANDIDATE_MAX_AGE_DAYS = 45

# Two questions whose normalized token sets overlap at/above this Jaccard
# ratio are treated as the same question (semantic dedup, no AI needed).
NEAR_DUPLICATE_JACCARD = 0.75

# Max auto-promotions per week: the bank band sets a floor, but a large
# promotable backlog raises the cap so inflow (~20/month from research +
# classification) can actually drain instead of accumulating forever.
def dynamic_weekly_cap(unanswered_count: int, backlog_count: int = 0) -> int:
    if unanswered_count > 120:
        band_cap = 1
    elif unanswered_count >= 80:
        band_cap = 2
    elif unanswered_count >= 40:
        band_cap = 3
    else:
        band_cap = 4
    drain_cap = min(8, backlog_count // 10)
    return max(band_cap, drain_cap)

# Max candidates from the same neighborhood/source promoted in one week.
# Doubles under backlog pressure so one prolific neighborhood can't stall a drain.
PER_NEIGHBORHOOD_CAP = 1
PER_NEIGHBORHOOD_CAP_BACKLOG = 2
BACKLOG_PRESSURE_THRESHOLD = 40

# Infer a default bank category from neighborhood topic_type.
TOPIC_TYPE_CATEGORY: dict[str, str] = {
    "self":        "E",
    "theme":       "E",
    "project":     "D",
    "event":       "B",
    "place":       "A",
    "time_period": "A",
    "person":      "C",
    "relationship": "C",
}

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


def refresh_neighborhood_readiness_safely() -> None:
    """Refresh derived neighborhood lifecycle fields without blocking promotion."""
    try:
        from neighborhoods import refresh_all_neighborhood_readiness  # noqa: PLC0415
        refresh_all_neighborhood_readiness(write=True)
    except Exception as exc:  # noqa: BLE001
        record_learning_failure(
            "question_candidates",
            "refresh_neighborhood_readiness",
            exc,
        )


def find_candidate(data: dict, candidate_id: str) -> dict:
    for candidate in data.get("candidates", []):
        if candidate.get("id") == candidate_id:
            return candidate
    raise ValueError(f"candidate not found: {candidate_id}")


def normalize_question(text: str) -> str:
    text = text.strip().lower()
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


_DEDUP_STOPWORDS = {
    "a", "an", "the", "you", "your", "yours", "me", "my", "i", "we", "us",
    "of", "in", "on", "at", "to", "for", "and", "or", "is", "are", "was",
    "were", "do", "did", "does", "what", "when", "where", "how", "that",
    "this", "it", "about", "with", "have", "has", "had", "be", "been",
    "as", "would", "could", "should", "will", "can",
    # contraction fragments left by normalization ("you'd" → "you d")
    "d", "s", "ll", "re", "ve", "t", "m",
}


def _question_tokens(text: str) -> set[str]:
    return {t for t in normalize_question(text).split()
            if len(t) > 1 and t not in _DEDUP_STOPWORDS}


def near_duplicate_of(text: str, other_texts: list[tuple[str, str]],
                      threshold: float = NEAR_DUPLICATE_JACCARD) -> str | None:
    """Return the label of the first near-duplicate of `text` among
    (label, text) pairs, judged by content-token Jaccard overlap. Catches
    reworded duplicates that exact normalization misses (e.g. three
    'what did you promise yourself you'd do differently' variants)."""
    tokens = _question_tokens(text)
    if len(tokens) < 3:
        return None  # too short to judge similarity meaningfully
    for label, other in other_texts:
        other_tokens = _question_tokens(other)
        if len(other_tokens) < 3:
            continue
        union = tokens | other_tokens
        if union and len(tokens & other_tokens) / len(union) >= threshold:
            return label
    return None


def _candidate_age_days(candidate: dict) -> float | None:
    raw = str(candidate.get("created_at") or "")
    if not raw:
        return None
    try:
        if raw.endswith("Z"):
            created = datetime.fromisoformat(raw[:-1] + "+00:00")
        else:
            created = datetime.fromisoformat(raw)
            if created.tzinfo is None:
                created = created.replace(tzinfo=timezone.utc)
    except ValueError:
        return None
    return (datetime.now(timezone.utc) - created).total_seconds() / 86400


def expire_stale_candidates(data: dict, *, max_age_days: float = CANDIDATE_MAX_AGE_DAYS,
                            dry_run: bool = False) -> list[tuple[str, float]]:
    """Expire candidates that sat unpromoted past max_age_days. Deferred
    candidates are exempt (a human said wait). Expired records are kept in the
    store for audit; they simply stop competing."""
    expired: list[tuple[str, float]] = []
    for candidate in data.get("candidates", []):
        if candidate.get("status") not in ("candidate", "accepted", "needs_review"):
            continue
        age = _candidate_age_days(candidate)
        if age is None or age <= max_age_days:
            continue
        expired.append((candidate["id"], round(age, 1)))
        if not dry_run:
            candidate["status"] = "expired"
            candidate["expired_at"] = now_utc()
            candidate["expired_reason"] = f"unpromoted after {age:.0f} days"
            candidate["updated_at"] = now_utc()
    return expired


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


def promote_neighborhood(data: dict, question_bank_text: str, neighborhood_id: str, category: str) -> tuple[str, list[str]]:
    """Promote every promotable candidate from a neighborhood into one category.

    Skips candidates that are non-promotable or duplicate text (so a partial
    re-run is safe). Returns the updated bank text and the list of new question
    IDs created.
    """
    category = category.upper()
    ensure_category_exists(question_bank_text, category)
    rows = [c for c in data.get("candidates", [])
            if c.get("neighborhood_id") == neighborhood_id
            and c.get("status") in PROMOTABLE_STATUSES]
    rows.sort(key=lambda c: (-float(c.get("priority", 0) or 0), c.get("created_at", "")))
    new_ids: list[str] = []
    for candidate in rows:
        text = str(candidate.get("text", "")).strip()
        if not text:
            continue
        try:
            ensure_not_duplicate(question_bank_text, text)
        except ValueError:
            continue  # already in the bank — skip, keep going
        question_id = next_question_id(question_bank_text, category)
        promoted_at = now_utc()
        question_bank_text = insert_question(
            question_bank_text, category, question_id, text, candidate, promoted_at)
        candidate["status"] = "promoted"
        candidate["target_category"] = category
        candidate["promoted_question_id"] = question_id
        candidate["promoted_at"] = promoted_at
        candidate["updated_at"] = promoted_at
        new_ids.append(question_id)
    return question_bank_text, new_ids


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
    refresh_neighborhood_readiness_safely()
    print(f"✓ Promoted {args.candidate_id} to {question_id}")
    return 0


# ---------------------------------------------------------------------------
# Auto-promotion engine
# ---------------------------------------------------------------------------

def _count_unanswered(question_bank_text: str) -> int:
    return len(re.findall(r"^- \[ \]", question_bank_text, re.MULTILINE))


def _infer_category(candidate: dict, neighborhoods: dict) -> str | None:
    """Best-effort category inference from candidate metadata."""
    # Explicit target already set
    if candidate.get("target_category"):
        return str(candidate["target_category"]).upper()
    # Look up neighborhood topic_type
    nbhd_id = candidate.get("neighborhood_id", "")
    for nbhd in neighborhoods.get("neighborhoods", []):
        if nbhd.get("id") == nbhd_id:
            return TOPIC_TYPE_CATEGORY.get(nbhd.get("type", "") or nbhd.get("topic_type", ""), None)
    return None


def score_candidate_for_promotion(candidate: dict, quality_profile: dict | None = None) -> float:
    """Score a candidate for auto-promotion.

    Score = priority × story_function_multiplier (from quality profile).
    Falls back to priority alone when the profile is inactive.
    """
    priority = float(candidate.get("priority", 0.5) or 0.5)
    multiplier = 1.0
    if quality_profile and quality_profile.get("active"):
        sf = candidate.get("story_function", "")
        fn_data = quality_profile.get("by_story_function", {}).get(sf, {})
        multiplier = float(fn_data.get("multiplier", 1.0))
    return round(priority * multiplier, 4)


def _is_resurfaceable(candidate: dict) -> bool:
    """needs_review candidates whose parking reason was score/quality-based get
    re-scored every run (the quality profile moves weekly). Structural reasons
    (missing_category, near_duplicate) wait for a human."""
    if candidate.get("status") != "needs_review":
        return False
    reason = str(candidate.get("needs_review_reason", ""))
    return any(key in reason for key in RESURFACEABLE_REVIEW_REASONS)


def auto_promote_candidates(
    dry_run: bool = False,
) -> dict:
    """Score all eligible candidates, auto-promote the best ones.

    Returns a summary dict:
    {
        "promoted": [(candidate_id, question_id, score), ...],
        "needs_review": [(candidate_id, score, reason), ...],
        "skipped": [(candidate_id, reason), ...],
        "expired": [(candidate_id, age_days), ...],
        "cap": int,
        "unanswered": int,
        "backlog": int,
    }
    """
    data = load_store()
    question_bank_text = QUESTIONS_FILE.read_text(encoding="utf-8")
    unanswered = _count_unanswered(question_bank_text)

    # Age out stale candidates first so they stop inflating the backlog.
    expired = expire_stale_candidates(data, dry_run=dry_run)

    # Load quality profile (optional)
    quality_profile: dict | None = None
    try:
        from quality_profile import load_profile  # noqa: PLC0415
        quality_profile = load_profile()
    except Exception as exc:  # noqa: BLE001
        record_learning_failure(
            "question_candidates",
            "load_quality_profile",
            exc,
        )

    # Load neighborhoods for category inference
    try:
        from lifehug_core import NEIGHBORHOODS_FILE  # noqa: PLC0415
        neighborhoods = read_json(NEIGHBORHOODS_FILE) if NEIGHBORHOODS_FILE.exists() else {}
    except Exception as exc:  # noqa: BLE001
        record_learning_failure(
            "question_candidates",
            "load_neighborhoods",
            exc,
        )
        neighborhoods = {}

    # Collect promotable candidates (plus resurfaceable needs_review) with scores
    eligible = []
    for c in data.get("candidates", []):
        if c.get("status") not in PROMOTABLE_STATUSES and not _is_resurfaceable(c):
            continue
        text = str(c.get("text", "")).strip()
        if not text:
            continue
        score = score_candidate_for_promotion(c, quality_profile)
        eligible.append((score, c))

    backlog = len(eligible)
    weekly_cap = dynamic_weekly_cap(unanswered, backlog)
    neighborhood_cap = (PER_NEIGHBORHOOD_CAP_BACKLOG
                        if backlog >= BACKLOG_PRESSURE_THRESHOLD else PER_NEIGHBORHOOD_CAP)

    # Sort best-first
    eligible.sort(key=lambda x: -x[0])

    # Existing bank questions for the quality checker's exact-dup flag and the
    # near-duplicate (semantic) check.
    existing_questions = parse_questions(question_bank_text)
    bank_texts: list[tuple[str, str]] = [
        (str(q.get("id", "?")), str(q.get("text", ""))) for q in existing_questions
    ]

    promoted: list[tuple[str, str, float]] = []
    needs_review: list[tuple[str, float, str]] = []
    skipped: list[tuple[str, str]] = []
    per_neighborhood: Counter = Counter()

    updated_bank = question_bank_text

    def park(candidate: dict, score: float, reason: str) -> None:
        needs_review.append((candidate["id"], score, reason))
        if not dry_run:
            candidate["status"] = "needs_review"
            candidate["needs_review_reason"] = reason
            candidate["updated_at"] = now_utc()

    for score, candidate in eligible:
        cid = candidate["id"]
        nbhd = candidate.get("neighborhood_id", "_none")
        text = str(candidate["text"]).strip()

        # Exact duplicate check
        try:
            ensure_not_duplicate(updated_bank, text)
        except ValueError:
            skipped.append((cid, "duplicate"))
            continue

        # Near-duplicate (semantic) check — against the bank AND anything
        # promoted earlier this run.
        dup_of = near_duplicate_of(text, bank_texts)
        if dup_of:
            park(candidate, score, f"near_duplicate of {dup_of}")
            continue

        # Craft-quality gate (yes/no wording, vagueness, too-short — the
        # research.md heuristics, previously display-only).
        quality = check_quality(text, source_path=candidate.get("source_path"),
                                existing_questions=existing_questions)
        if quality["score"] < QUALITY_GATE_MIN:
            park(candidate, score, f"quality {quality['score']:.2f}: {quality['notes']}")
            continue

        # Category inference
        category = _infer_category(candidate, neighborhoods)
        if not category:
            park(candidate, score, "missing_category")
            continue

        # Promotion-score gate
        if score < AUTO_PROMOTE_THRESHOLD:
            if score >= NEEDS_REVIEW_THRESHOLD:
                park(candidate, score, f"score {score:.2f} below threshold {AUTO_PROMOTE_THRESHOLD}")
            else:
                skipped.append((cid, f"score {score:.2f} too low"))
            continue

        # Weekly cap
        if len(promoted) >= weekly_cap:
            skipped.append((cid, "weekly_cap_reached"))
            continue

        # Per-neighborhood cap
        if per_neighborhood[nbhd] >= neighborhood_cap:
            skipped.append((cid, f"neighborhood_cap ({nbhd})"))
            continue

        # Promote
        try:
            ensure_category_exists(updated_bank, category)
            question_id = next_question_id(updated_bank, category)
            promoted_at = now_utc()
            updated_bank = insert_question(
                updated_bank, category, question_id,
                text, candidate, promoted_at,
            )
            # Augment provenance with auto-promotion metadata
            # (insert_question writes the comment; we update candidate record)
            if not dry_run:
                candidate["status"] = "auto_promoted"
                candidate["target_category"] = category
                candidate["promoted_question_id"] = question_id
                candidate["promoted_at"] = promoted_at
                candidate["promoted_by"] = "auto"
                candidate["promotion_score"] = score
                candidate["promotion_reason"] = f"auto: score {score:.2f} ≥ {AUTO_PROMOTE_THRESHOLD}"
                candidate["updated_at"] = promoted_at
            promoted.append((cid, question_id, score))
            per_neighborhood[nbhd] += 1
            bank_texts.append((question_id, text))  # near-dup guard for the rest of this run
        except ValueError as exc:
            skipped.append((cid, str(exc)))

    if not dry_run and (promoted or needs_review or expired):
        write_text(QUESTIONS_FILE, updated_bank)
        save_store(data)

    return {
        "promoted": promoted,
        "needs_review": needs_review,
        "skipped": skipped,
        "expired": expired,
        "cap": weekly_cap,
        "unanswered": unanswered,
        "backlog": backlog,
        "dry_run": dry_run,
    }


def cmd_promote_neighborhood(args: argparse.Namespace) -> int:
    data = load_store()
    question_bank_text = QUESTIONS_FILE.read_text(encoding="utf-8")
    updated_bank, new_ids = promote_neighborhood(data, question_bank_text, args.neighborhood, args.category)
    if new_ids:
        write_text(QUESTIONS_FILE, updated_bank)
        save_store(data)
        refresh_neighborhood_readiness_safely()
    print(f"✓ Promoted {len(new_ids)} question(s) from {args.neighborhood} → {args.category.upper()}: {', '.join(new_ids) or 'none'}")
    return 0


def cmd_auto_promote(args: argparse.Namespace) -> int:
    result = auto_promote_candidates(dry_run=args.dry_run)
    cap = result["cap"]
    unanswered = result["unanswered"]
    promoted = result["promoted"]
    needs_review = result["needs_review"]
    skipped = result["skipped"]
    expired = result.get("expired", [])
    prefix = "[DRY RUN] " if args.dry_run else ""

    print(f"{prefix}Auto-promotion — bank: {unanswered} unanswered, "
          f"backlog: {result.get('backlog', '?')} promotable, weekly cap: {cap}")
    print()
    if expired:
        print(f"  ⌛ Expired ({len(expired)}):")
        for cid, age in expired[:5]:
            print(f"    {cid} — {age:.0f} days old")
        if len(expired) > 5:
            print(f"    ... and {len(expired) - 5} more")
    if promoted:
        print(f"  ✅ Promoted ({len(promoted)}):")
        for cid, qid, score in promoted:
            print(f"    {qid} ← {cid} (score {score:.2f})")
        if not args.dry_run:
            refresh_neighborhood_readiness_safely()
    else:
        print("  Promoted: none")
    if needs_review:
        print(f"  ⚠️  Needs review ({len(needs_review)}):")
        for cid, score, reason in needs_review:
            print(f"    {cid} (score {score:.2f}) — {reason}")
    if skipped:
        print(f"  ⏭️  Skipped ({len(skipped)}):")
        for cid, reason in skipped[:5]:
            print(f"    {cid} — {reason}")
        if len(skipped) > 5:
            print(f"    ... and {len(skipped) - 5} more")
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

    p = sub.add_parser("promote-neighborhood", help="Promote all of a neighborhood's candidates into one category")
    p.add_argument("--neighborhood", required=True)
    p.add_argument("--category", required=True)
    p.set_defaults(func=cmd_promote_neighborhood)

    p = sub.add_parser("stats", help="Show candidate statistics")
    p.set_defaults(func=cmd_stats)

    p = sub.add_parser("auto-promote", help="Auto-promote top candidates into question-bank.md")
    p.add_argument("--dry-run", action="store_true", help="Preview without writing")
    p.set_defaults(func=cmd_auto_promote)

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
