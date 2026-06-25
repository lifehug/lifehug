#!/usr/bin/env python3
"""Lifehug — Answer Quality Profiler.

Scores each answer for richness (word count, entities, wiki delta, follow-ups)
and accumulates signal in state/answer_scores.json. A weekly aggregation step
derives state/quality_profile.json, which the planner and research expander
use to bias toward question types that historically open the author up.

No friction for the author — scoring happens automatically inside process_answer.py.

Usage:
    python3 system/quality_profile.py --update      # aggregate scores → profile
    python3 system/quality_profile.py --score-all   # retroactive score of existing answers
    python3 system/quality_profile.py --show        # print current profile
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

from lifehug_core import (
    ANSWERS_DIR,
    QUESTIONS_FILE,
    REPO_DIR,
    now_utc,
    parse_questions,
    read_json,
    write_json,
)

ANSWER_SCORES_FILE = REPO_DIR / "state" / "answer_scores.json"
QUALITY_PROFILE_FILE = REPO_DIR / "state" / "quality_profile.json"

# Minimum scored answers before the profile activates and influences anything.
ACTIVATION_THRESHOLD = 20

# Richness score weights for live scoring (wiki delta available).
WEIGHTS_LIVE = {"word_count": 0.30, "entity_count": 0.25, "wiki_nodes_added": 0.25, "followup_count": 0.20}
# Retroactive weights (no wiki delta signal).
WEIGHTS_RETRO = {"word_count": 0.40, "entity_count": 0.40, "wiki_nodes_added": 0.00, "followup_count": 0.20}

# Normalization targets (score of 1.0 at or above these values).
TARGETS = {"word_count": 300, "entity_count": 5, "wiki_nodes_added": 3, "followup_count": 3}

# Cap multipliers to avoid runaway amplification.
MULTIPLIER_CAP = 1.5
MULTIPLIER_FLOOR = 0.7


# ---------------------------------------------------------------------------
# Signal extraction
# ---------------------------------------------------------------------------

_ENTITY_RE = re.compile(r"\b[A-Z][a-z]{1,}\b")
_SKIP_WORDS = {
    "I", "It", "He", "She", "They", "We", "You", "My", "His", "Her", "Their",
    "The", "A", "An", "This", "That", "These", "Those", "There", "Here",
    "When", "Where", "What", "Who", "Why", "How", "So", "But", "And", "Or",
    "If", "In", "On", "At", "To", "Of", "For", "With", "By", "From",
    "Question", "Category", "Pass", "Asked", "Answered", "Source",
}


def extract_signals(
    answer_text: str,
    wiki_nodes_added: int = 0,
    followup_count: int = 0,
    *,
    retroactive: bool = False,
) -> dict:
    """Extract objective richness signals from an answer."""
    words = answer_text.split()
    word_count = len(words)

    # Simple proper-noun entity count: capitalized words not in skip list,
    # deduplicated so repeated names count once.
    raw_entities = _ENTITY_RE.findall(answer_text)
    entities = {e for e in raw_entities if e not in _SKIP_WORDS}
    entity_count = len(entities)

    return {
        "word_count": word_count,
        "entity_count": entity_count,
        "wiki_nodes_added": wiki_nodes_added,
        "followup_count": followup_count,
        "retroactive": retroactive,
    }


def score_richness(signals: dict) -> float:
    """Compute a 0-1 richness score from extracted signals."""
    retroactive = signals.get("retroactive", False)
    weights = WEIGHTS_RETRO if retroactive else WEIGHTS_LIVE
    score = 0.0
    for key, weight in weights.items():
        if weight == 0:
            continue
        raw = float(signals.get(key, 0))
        normalized = min(raw / TARGETS[key], 1.0)
        score += weight * normalized
    return round(score, 3)


# ---------------------------------------------------------------------------
# State I/O
# ---------------------------------------------------------------------------

def load_scores() -> dict:
    data = read_json(ANSWER_SCORES_FILE, default=None)
    if not isinstance(data, dict):
        return {"version": 1, "scores": []}
    data.setdefault("scores", [])
    return data


def save_scores(data: dict) -> None:
    data["last_updated"] = now_utc()
    ANSWER_SCORES_FILE.parent.mkdir(parents=True, exist_ok=True)
    write_json(ANSWER_SCORES_FILE, data)


def load_profile() -> dict:
    """Return quality profile, or a minimal inactive stub if not yet computed."""
    data = read_json(QUALITY_PROFILE_FILE, default=None)
    if not isinstance(data, dict):
        return {"active": False}
    return data


def save_profile(data: dict) -> None:
    QUALITY_PROFILE_FILE.parent.mkdir(parents=True, exist_ok=True)
    write_json(QUALITY_PROFILE_FILE, data)


# ---------------------------------------------------------------------------
# Score accumulation
# ---------------------------------------------------------------------------

def append_score(
    question_id: str,
    category: str,
    story_function: str,
    focus: str | None,
    signals: dict,
    richness_score: float,
) -> None:
    """Append a single answer score. Idempotent — skips if question_id exists."""
    data = load_scores()
    existing_ids = {s["question_id"] for s in data["scores"]}
    if question_id in existing_ids:
        return
    data["scores"].append({
        "question_id": question_id,
        "answered_at": now_utc()[:10],
        "category": category,
        "story_function": story_function,
        "focus": focus,
        "signals": signals,
        "richness_score": richness_score,
    })
    save_scores(data)


# ---------------------------------------------------------------------------
# Profile computation
# ---------------------------------------------------------------------------

def _aggregate(scores: list[dict], key: str) -> dict:
    """Aggregate richness scores by a dimension key."""
    buckets: dict[str, list[float]] = {}
    for s in scores:
        bucket = str(s.get(key) or "unknown")
        buckets.setdefault(bucket, []).append(float(s["richness_score"]))
    result = {}
    for bucket, values in buckets.items():
        avg = sum(values) / len(values)
        result[bucket] = {"avg": round(avg, 3), "count": len(values)}
    return result


def _multiplier(avg: float, global_avg: float) -> float:
    """Normalize avg vs global_avg into a weight multiplier, clamped."""
    if global_avg <= 0:
        return 1.0
    raw = avg / global_avg
    return round(max(MULTIPLIER_FLOOR, min(MULTIPLIER_CAP, raw)), 3)


def _top_patterns(by_story: dict, by_category: dict, global_avg: float) -> list[str]:
    """Generate natural language insights from aggregated data."""
    patterns = []

    # Best story function
    best_fn = max(by_story.items(), key=lambda x: x[1]["avg"], default=(None, {}))
    worst_fn = min(by_story.items(), key=lambda x: x[1]["avg"], default=(None, {}))
    if best_fn[0] and best_fn[1].get("count", 0) >= 5:
        pct = round((best_fn[1]["avg"] / global_avg - 1) * 100)
        if pct > 5:
            patterns.append(
                f"'{best_fn[0]}' questions score {pct}% higher than average — prefer this story function"
            )
    if worst_fn[0] and worst_fn[1].get("count", 0) >= 5 and worst_fn[0] != best_fn[0]:
        pct = round((1 - worst_fn[1]["avg"] / global_avg) * 100)
        if pct > 5:
            patterns.append(
                f"'{worst_fn[0]}' questions score {pct}% below average — use sparingly"
            )

    # Best category
    best_cat = max(by_category.items(), key=lambda x: x[1]["avg"], default=(None, {}))
    if best_cat[0] and best_cat[1].get("count", 0) >= 5:
        pct = round((best_cat[1]["avg"] / global_avg - 1) * 100)
        if pct > 5:
            patterns.append(
                f"Category {best_cat[0]} produces the richest answers ({pct}% above average)"
            )

    # Anchor/specificity hint (derived from entity_count signal correlation)
    high_entity = [s for s in [] if s]  # placeholder — enriched below
    if not patterns:
        patterns.append("Anchor questions to specific people, moments, or places for richer answers")

    return patterns[:4]


def compute_profile() -> dict:
    """Read answer_scores.json and compute quality_profile.json."""
    data = load_scores()
    scores = data.get("scores", [])
    total = len(scores)

    if total == 0:
        profile = {"active": False, "total_scored": 0, "computed_at": now_utc()}
        save_profile(profile)
        return profile

    global_avg = round(sum(s["richness_score"] for s in scores) / total, 3)

    by_story_raw = _aggregate(scores, "story_function")
    by_category_raw = _aggregate(scores, "category")
    by_focus_raw = _aggregate(scores, "focus")

    # Add multipliers
    by_story = {
        fn: {**v, "multiplier": _multiplier(v["avg"], global_avg)}
        for fn, v in by_story_raw.items()
    }
    by_category = {
        cat: {**v, "multiplier": _multiplier(v["avg"], global_avg)}
        for cat, v in by_category_raw.items()
    }
    by_focus = {
        f: {**v, "multiplier": _multiplier(v["avg"], global_avg)}
        for f, v in by_focus_raw.items()
    }

    patterns = _top_patterns(by_story, by_category, global_avg)

    profile = {
        "version": 1,
        "active": total >= ACTIVATION_THRESHOLD,
        "computed_at": now_utc(),
        "total_scored": total,
        "global_avg": global_avg,
        "by_story_function": by_story,
        "by_category": by_category,
        "by_focus": by_focus,
        "top_patterns": patterns,
    }
    save_profile(profile)
    return profile


# ---------------------------------------------------------------------------
# Retroactive scoring
# ---------------------------------------------------------------------------

def _infer_story_function(text: str) -> str:
    """Very lightweight story-function guesser for retroactive scoring."""
    t = text.lower()
    if any(w in t for w in ["who", "person", "friend", "family", "mom", "dad", "sister", "brother"]):
        return "relationship"
    if any(w in t for w in ["first", "began", "started", "origin", "grew up", "born"]):
        return "origin_story"
    if any(w in t for w in ["but", "however", "despite", "contradict", "yet"]):
        return "contradiction"
    if any(w in t for w in ["turn", "pivot", "changed", "realized", "decided"]):
        return "turning_point"
    if any(w in t for w in ["fear", "afraid", "scared", "worry", "risk"]):
        return "stakes_and_risk"
    return "foundation"


def score_all_retroactive() -> int:
    """Score all existing answer files that haven't been scored yet."""
    data = load_scores()
    existing_ids = {s["question_id"] for s in data["scores"]}

    questions_text = QUESTIONS_FILE.read_text(encoding="utf-8")
    questions = parse_questions(questions_text)
    q_map = {str(q["id"]): q for q in questions}

    answer_files = sorted(ANSWERS_DIR.glob("*.md"))
    scored = 0

    for af in answer_files:
        qid = af.stem
        if qid in existing_ids:
            continue
        q = q_map.get(qid)
        if not q or not q.get("answered"):
            continue

        text = af.read_text(encoding="utf-8")
        # Strip frontmatter header lines (first ~5 lines)
        body_lines = text.splitlines()
        body_start = next((i for i, l in enumerate(body_lines) if l.strip() == "---"), 4)
        body = "\n".join(body_lines[body_start + 1:]).strip()

        # Count follow-up questions in this file
        followup_count = len(re.findall(r"^- [A-Z]\d+[a-z]+:", text, re.MULTILINE))

        signals = extract_signals(body, wiki_nodes_added=0, followup_count=followup_count, retroactive=True)
        richness = score_richness(signals)
        category = str(q.get("category", ""))
        story_fn = _infer_story_function(str(q.get("text", "")))

        data["scores"].append({
            "question_id": qid,
            "answered_at": str(q.get("answered_at", ""))[:10] or now_utc()[:10],
            "category": category,
            "story_function": story_fn,
            "focus": None,
            "signals": signals,
            "richness_score": richness,
        })
        existing_ids.add(qid)
        scored += 1

    if scored:
        save_scores(data)
    return scored


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def cmd_show() -> None:
    profile = load_profile()
    if not profile.get("active"):
        total = profile.get("total_scored", 0)
        needed = ACTIVATION_THRESHOLD - total
        print(f"Quality profile: inactive ({total} scored, need {needed} more to activate)")
        return
    print(f"Quality profile — {profile['total_scored']} answers scored, global avg {profile['global_avg']:.2f}")
    print()
    print("By story function:")
    for fn, d in sorted(profile.get("by_story_function", {}).items(), key=lambda x: -x[1]["avg"]):
        bar = "▲" if d["multiplier"] > 1.05 else ("▼" if d["multiplier"] < 0.95 else "·")
        print(f"  {bar} {fn:22}  avg={d['avg']:.2f}  n={d['count']}  ×{d['multiplier']:.2f}")
    print()
    print("Top patterns:")
    for p in profile.get("top_patterns", []):
        print(f"  • {p}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Lifehug answer quality profiler")
    parser.add_argument("--update", action="store_true", help="Compute and save quality profile from scores")
    parser.add_argument("--score-all", action="store_true", help="Retroactively score all existing answers")
    parser.add_argument("--show", action="store_true", help="Print current quality profile")
    args = parser.parse_args()

    if args.score_all:
        n = score_all_retroactive()
        print(f"✓ Retroactively scored {n} answers")
        if n:
            profile = compute_profile()
            status = "active" if profile.get("active") else f"inactive ({profile['total_scored']}/{ACTIVATION_THRESHOLD})"
            print(f"✓ Profile recomputed — {status}")
        return 0

    if args.update:
        profile = compute_profile()
        status = "active" if profile.get("active") else f"inactive ({profile['total_scored']}/{ACTIVATION_THRESHOLD})"
        print(f"✓ Quality profile updated — {profile.get('total_scored', 0)} answers, {status}")
        if profile.get("top_patterns"):
            for p in profile["top_patterns"]:
                print(f"  • {p}")
        return 0

    if args.show or not any([args.update, args.score_all]):
        cmd_show()
        return 0

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
