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
    ANSWER_SCORES_FILE,
    ANSWERS_DIR,
    QUESTIONS_FILE,
    QUALITY_PROFILE_FILE,
    now_utc,
    parse_questions,
    read_json,
    write_json,
)

# Minimum scored answers before the profile activates and influences anything.
ACTIVATION_THRESHOLD = 20

# Richness score weights. wiki_nodes_added is retired at weight 0: it counted
# wiki FILE creation per answer, which almost never happens, so a 0.25-weight
# signal sat at ~zero and systematically depressed live scores vs retro ones.
WEIGHTS_LIVE = {"word_count": 0.40, "entity_count": 0.35, "wiki_nodes_added": 0.00, "followup_count": 0.25}
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

# LIWC-lite word lists (Pennebaker): rising insight/causal density across a
# theme predicts productive processing; flat insight + high negative + high
# I-rate is the brooding signature. Coarse but directionally useful.
_INSIGHT_WORDS = {
    "realize", "realized", "realizing", "understand", "understood", "understand",
    "because", "reason", "meant", "means", "learned", "learn", "insight", "see now",
    "makes sense", "figured", "cause", "caused", "why", "therefore", "so that",
    "know now", "knew", "clarity", "perspective",
}
_NEGATIVE_WORDS = {
    "sad", "afraid", "scared", "fear", "angry", "anger", "hate", "hated", "hurt",
    "pain", "painful", "ashamed", "shame", "guilt", "guilty", "worthless", "alone",
    "lonely", "hopeless", "anxious", "worried", "worry", "regret", "failure",
    "failed", "broken", "lost", "cry", "cried", "terrible", "awful", "worst",
}


def _word_rate(words: list[str], vocabulary: set[str]) -> float:
    if not words:
        return 0.0
    lower = [w.strip(".,!?;:'\"").lower() for w in words]
    hits = sum(1 for w in lower if w in vocabulary)
    return round(hits / len(lower), 4)


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

    lower_words = [w.strip(".,!?;:'\"").lower() for w in words]
    i_rate = round(sum(1 for w in lower_words if w in ("i", "i'm", "i've", "i'd", "me", "my", "myself")) / word_count, 4) if word_count else 0.0

    return {
        "word_count": word_count,
        "entity_count": entity_count,
        "wiki_nodes_added": wiki_nodes_added,
        "followup_count": followup_count,
        # Pennebaker-style processing signals (not part of richness score;
        # consumed by the rumination detector and future trend analysis).
        "insight_rate": _word_rate(words, _INSIGHT_WORDS),
        "negative_rate": _word_rate(words, _NEGATIVE_WORDS),
        "i_rate": i_rate,
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
    *,
    engagement: dict | None = None,
) -> None:
    """Append a single answer score. Idempotent — skips if question_id exists.

    ``engagement`` (issue #119) seeds the record's engagement block at
    filing time — today that is only ``time_to_answer_hours`` (computable
    for every answer from frontmatter, session or no session). The other
    three engagement fields are added LATER, at conversation close, by
    ``conversation_delivery.append_engagement`` (MERGING into this same
    dict, never overwriting it — see that function's docstring).
    """
    data = load_scores()
    existing_ids = {s["question_id"] for s in data["scores"]}
    if question_id in existing_ids:
        return
    record = {
        "question_id": question_id,
        "answered_at": now_utc()[:10],
        "category": category,
        "story_function": story_function,
        "focus": focus,
        "signals": signals,
        "richness_score": richness_score,
    }
    if engagement:
        record["engagement"] = dict(engagement)
    data["scores"].append(record)
    save_scores(data)


def merge_engagement(question_id: str, fields: dict, *, scores_path: Path | None = None) -> bool:
    """Merge ``fields`` into one record's engagement block (issue #119).

    Never overwrites what another writer already stored there — two writers
    of one field must compose (recurring-defect doctrine). No-ops when the
    record doesn't exist or ``fields`` is empty. Returns whether a record was
    found and updated.
    """
    if not fields:
        return False
    scores_path = scores_path if scores_path is not None else ANSWER_SCORES_FILE
    data = read_json(scores_path, default=None)
    if not isinstance(data, dict) or not isinstance(data.get("scores"), list):
        return False
    for record in data["scores"]:
        if not isinstance(record, dict) or str(record.get("question_id") or "") != question_id:
            continue
        existing = record.get("engagement")
        merged = dict(existing) if isinstance(existing, dict) else {}
        merged.update(fields)
        record["engagement"] = merged
        data["last_updated"] = now_utc()
        write_json(scores_path, data)
        return True
    return False


# ---------------------------------------------------------------------------
# Profile computation
# ---------------------------------------------------------------------------

def _aggregate(scores: list[dict], key: str) -> dict:
    """Aggregate richness scores by a dimension key. Story-function buckets
    normalize legacy names into the canonical vocabulary so pre-v69 scores
    keep contributing signal."""
    buckets: dict[str, list[float]] = {}
    for s in scores:
        bucket = str(s.get(key) or "unknown")
        if key == "story_function":
            bucket = canonical_story_function(bucket)
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

    if not patterns:
        patterns.append("Anchor questions to specific people, moments, or places for richer answers")

    return patterns[:4]


# ---------------------------------------------------------------------------
# Engagement dimension (issue #119, design §5, "Engagement in the Loop" /
# "Drain is not negative" — decision log). A PARALLEL dimension to richness:
# richness scores WHAT was said, engagement scores whether the author kept
# coming back. Buckets key exclusively through canonical_story_function
# (lesson 2, below) and only fire from signals #122/#119 actually capture
# (lesson 1) — never a guessed or invented vocabulary.
# ---------------------------------------------------------------------------

# Response-latency normalization window for the engagement blend: a reply
# inside this many hours earns full responsiveness credit, one a week or
# slower earns none, linear between. Deliberately generous — the daily
# question is asked once a day, so same-day-ish replies are the norm, not
# the exception.
_TIME_TO_ANSWER_FAST_HOURS = 4.0
_TIME_TO_ANSWER_SLOW_HOURS = 168.0

_TRAJECTORY_SCORE = {"expanding": 1.0, "flat": 0.5, "contracting": 0.0}


def _engagement_component_score(engagement: dict) -> float | None:
    """Normalize one record's fired engagement signals into a single 0-1
    score — the unweighted average of whichever components fired.
    Components:
      - continuation_past_exit: 1.0 (kept going) / 0.0 (stopped at the exit)
      - turn_length_trajectory: expanding=1.0, flat=0.5, contracting=0.0
      - unprompted_inbound: 1.0 (the author brought it up) / 0.0
      - time_to_answer_hours: faster -> higher, normalized against the
        fast/slow window above, clamped to [0, 1]
    Absent components are never fabricated: with nothing fired, returns
    None rather than guessing a score (lesson 1 — a signal that can't
    demonstrably fire must not silently count as zero).
    """
    parts: list[float] = []
    if isinstance(engagement.get("continuation_past_exit"), bool):
        parts.append(1.0 if engagement["continuation_past_exit"] else 0.0)
    trajectory = engagement.get("turn_length_trajectory")
    if trajectory in _TRAJECTORY_SCORE:
        parts.append(_TRAJECTORY_SCORE[trajectory])
    if isinstance(engagement.get("unprompted_inbound"), bool):
        parts.append(1.0 if engagement["unprompted_inbound"] else 0.0)
    hours = engagement.get("time_to_answer_hours")
    if isinstance(hours, (int, float)) and not isinstance(hours, bool):
        span = _TIME_TO_ANSWER_SLOW_HOURS - _TIME_TO_ANSWER_FAST_HOURS
        normalized = 1.0 - ((float(hours) - _TIME_TO_ANSWER_FAST_HOURS) / span)
        parts.append(max(0.0, min(1.0, normalized)))
    if not parts:
        return None
    return round(sum(parts) / len(parts), 3)


def _engagement_records(scores: list[dict]) -> list[tuple[dict, float]]:
    """(score record, component score) for every record with ≥1 fired signal."""
    out: list[tuple[dict, float]] = []
    for s in scores:
        engagement = s.get("engagement")
        if not isinstance(engagement, dict) or not engagement:
            continue
        comp = _engagement_component_score(engagement)
        if comp is not None:
            out.append((s, comp))
    return out


def _aggregate_engagement(records: list[tuple[dict, float]], key: str, global_avg: float) -> dict:
    """Bucket engagement component scores by ``key``, same clamp as richness.

    A bucket only earns a non-1.0 multiplier at count >= 5 (the
    ``_top_patterns`` precedent) — below that, avg/count still show but the
    multiplier stays neutral so a thin sample never biases the planner.
    """
    buckets: dict[str, list[float]] = {}
    for s, comp in records:
        bucket = str(s.get(key) or "unknown")
        if key == "story_function":
            bucket = canonical_story_function(bucket)
        buckets.setdefault(bucket, []).append(comp)
    result = {}
    for bucket, values in buckets.items():
        avg = sum(values) / len(values)
        count = len(values)
        multiplier = _multiplier(avg, global_avg) if count >= 5 else 1.0
        result[bucket] = {"avg": round(avg, 3), "count": count, "multiplier": multiplier}
    return result


def _compute_engagement_block(scores: list[dict]) -> dict:
    records = _engagement_records(scores)
    scored = len(records)
    global_avg = round(sum(c for _, c in records) / scored, 3) if scored else 0.0
    return {
        "active": scored >= ACTIVATION_THRESHOLD,
        "scored": scored,
        "global_avg": global_avg,
        "by_story_function": _aggregate_engagement(records, "story_function", global_avg),
        "by_category": _aggregate_engagement(records, "category", global_avg),
        "by_focus": _aggregate_engagement(records, "focus", global_avg),
    }


# Rumination detector thresholds: the last N answers in a category all show
# the brooding signature (high negative + high self-focus + no insight growth).
RUMINATION_WINDOW = 3
RUMINATION_NEGATIVE_MIN = 0.02   # ≥2% negative-affect words
RUMINATION_I_RATE_MIN = 0.08     # ≥8% first-person words


def detect_rumination(scores: list[dict], window: int = RUMINATION_WINDOW) -> list[str]:
    """Categories whose recent answers show brooding (Nolen-Hoeksema/Treynor):
    repetitive negative self-focus with flat/falling insight. The planner
    cools these categories; depth ≠ repetition — return via a distancing or
    concrete-behavior lens after a break."""
    by_cat: dict[str, list[dict]] = {}
    for s in scores:
        sig = s.get("signals") or {}
        if "insight_rate" not in sig:
            continue  # pre-v70 score without processing signals
        by_cat.setdefault(str(s.get("category") or "?"), []).append(sig)

    flagged: list[str] = []
    for cat, sigs in by_cat.items():
        recent = sigs[-window:]
        if len(recent) < window:
            continue
        all_negative = all(s.get("negative_rate", 0) >= RUMINATION_NEGATIVE_MIN for s in recent)
        all_self = all(s.get("i_rate", 0) >= RUMINATION_I_RATE_MIN for s in recent)
        insight_flat = recent[-1].get("insight_rate", 0) <= recent[0].get("insight_rate", 0)
        if all_negative and all_self and insight_flat:
            flagged.append(cat)
    return sorted(flagged)


def compute_profile() -> dict:
    """Read answer_scores.json and compute quality_profile.json."""
    data = load_scores()
    scores = data.get("scores", [])
    total = len(scores)

    if total == 0:
        profile = {
            "active": False,
            "total_scored": 0,
            "computed_at": now_utc(),
            "engagement": {"active": False, "scored": 0, "global_avg": 0.0,
                           "by_story_function": {}, "by_category": {}, "by_focus": {}},
        }
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
        "rumination_categories": detect_rumination(scores),
        "top_patterns": patterns,
        "engagement": _compute_engagement_block(scores),
    }
    save_profile(profile)
    return profile


# ---------------------------------------------------------------------------
# Retroactive scoring
# ---------------------------------------------------------------------------

# One vocabulary. The profile used to run its own guesser emitting names
# ("origin_story", "stakes_and_risk") that exist NOWHERE else — so its
# strongest signal keyed functions the planner could never assign, and the
# feedback multiplier applied to nothing. Legacy scores normalize on
# aggregation; new scores classify through the planner's shared classifier.
LEGACY_FUNCTION_MAP = {
    "origin_story": "foundation",
    "stakes_and_risk": "tension",
}


def canonical_story_function(name: str | None) -> str:
    value = str(name or "unknown")
    return LEGACY_FUNCTION_MAP.get(value, value)


def _infer_story_function(text: str) -> str:
    """Classify with the SAME keyword classifier the planner uses, so profile
    buckets and planner assignments speak one vocabulary."""
    from question_planner import infer_story_function  # noqa: PLC0415 — lazy: planner imports us

    return infer_story_function(text)


def focus_for_category(category: str) -> str | None:
    """Which Focus owns a question category, per the roadmap. Attribution was
    previously hardcoded to None everywhere, leaving by_focus 100% 'unknown'."""
    try:
        from roadmap import load_roadmap  # noqa: PLC0415
        for focus in load_roadmap().get("focuses", []):
            if category in (focus.get("categories") or []):
                return str(focus.get("id"))
    except Exception:  # noqa: BLE001
        return None
    return None


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
            "focus": focus_for_category(category),
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
    print()
    engagement = profile.get("engagement") or {}
    if not engagement.get("active"):
        scored = engagement.get("scored", 0)
        needed = ACTIVATION_THRESHOLD - scored
        print(f"Engagement: inactive ({scored} scored, need {needed} more to activate)")
    else:
        print(f"Engagement — {engagement['scored']} answers scored, "
              f"global avg {engagement['global_avg']:.2f}")
        for fn, d in sorted(engagement.get("by_story_function", {}).items(), key=lambda x: -x[1]["avg"]):
            bar = "▲" if d["multiplier"] > 1.05 else ("▼" if d["multiplier"] < 0.95 else "·")
            print(f"  {bar} {fn:22}  avg={d['avg']:.2f}  n={d['count']}  ×{d['multiplier']:.2f}")


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
