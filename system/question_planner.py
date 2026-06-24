#!/usr/bin/env python3
"""Report and build Lifehug question queues with balance caps."""

from __future__ import annotations

import argparse
import copy
import json
import math
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone

from lifehug_core import (
    ANSWERS_DIR,
    CLASSIFICATIONS_DIR,
    MANUAL_SOURCES_DIR,
    NEIGHBORHOODS_FILE,
    PLANNER_STATE_FILE,
    QUESTION_CANDIDATES_FILE,
    QUESTION_QUEUE_FILE,
    QUESTIONS_FILE,
    SOURCES_DIR,
    SPOTLIGHT_RECS_FILE,
    WIKI_DIR,
    answer_body,
    answer_id_from_filename,
    compute_coverage,
    now_utc,
    parse_categories,
    parse_questions,
    read_json,
    slugify,
    write_json,
)

GROUP_CAPS = {
    "main": 0.50,
    "project": 0.35,
    "spotlight": 0.25,
}

STORY_FUNCTIONS = (
    "foundation",
    "scene",
    "tension",
    "turning_point",
    "relationship",
    "meaning",
    "contradiction",
    "output_gap",
)

STORY_FUNCTION_CAPS = {
    "foundation": 0.35,
    "scene": 0.45,
    "tension": 0.30,
    "turning_point": 0.30,
    "relationship": 0.35,
    "meaning": 0.30,
    "contradiction": 0.20,
    "output_gap": 0.20,
}

KIND_TO_STORY_FUNCTION = {
    "foundation": "foundation",
    "scene": "scene",
    "relationships": "relationship",
    "relationship": "relationship",
    "meaning": "meaning",
    "gap": "output_gap",
    "output_gap": "output_gap",
}

STORY_FUNCTION_KEYWORDS = {
    "scene": [
        "walk me through",
        "what did it look",
        "what did it feel",
        "what did it smell",
        "what did the room",
        "specific day",
        "specific moment",
        "where were you",
        "what was the conversation",
    ],
    "tension": ["hardest", "conflict", "friction", "scared", "fear", "risk", "almost", "struggle", "pressure"],
    "turning_point": ["when did", "moment", "changed", "shift", "turning point", "decided", "realized", "clicked"],
    "relationship": ["who", "relationship", "mom", "dad", "katie", "friend", "mentor", "family", "partner", "aj"],
    "meaning": ["what did", "teach", "mean", "understand", "explain", "why", "proud", "wisdom"],
    "contradiction": ["different from", "but", "contradiction", "surprised", "mismatch", "tension between"],
    "output_gap": ["letter", "chapter", "post", "essay", "missing", "unresolved", "gap", "what part"],
}


def qid_key(qid: str) -> tuple[str, int, str]:
    match = re.match(r"^([A-Z])(\d+)([a-z]*)$", qid)
    if not match:
        return (qid[:1], 0, qid)
    return (match.group(1), int(match.group(2)), match.group(3))


def parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    raw = str(value).strip()
    if not raw:
        return None
    try:
        if raw.endswith("Z"):
            return datetime.fromisoformat(raw[:-1] + "+00:00")
        if len(raw) == 10:
            return datetime.fromisoformat(raw + "T00:00:00+00:00")
        dt = datetime.fromisoformat(raw)
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def future_timestamp(days: int) -> str:
    return (datetime.now(timezone.utc) + timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")


def default_planner_state() -> dict:
    return {
        "version": 1,
        "active_objectives": [],
        "caps": {
            "group": GROUP_CAPS,
            "story_function": STORY_FUNCTION_CAPS,
            "source_type": {
                "question_bank": 1.0,
                "candidate": 0.20,
                "manual_source": 0.20,
            },
        },
        "queue": {
            "default_limit": 14,
            "arc_max": 2,
            "expires_after_days": 7,
        },
    }


def merge_defaults(data: dict, defaults: dict) -> dict:
    merged = copy.deepcopy(defaults)
    for key, value in data.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = merge_defaults(value, merged[key])
        else:
            merged[key] = value
    return merged


def load_planner_state(*, write_default: bool = False) -> dict:
    data = read_json(PLANNER_STATE_FILE, default=None)
    if not isinstance(data, dict):
        data = default_planner_state()
    else:
        data = merge_defaults(data, default_planner_state())
    if write_default:
        data["last_updated"] = now_utc()
        write_json(PLANNER_STATE_FILE, data)
    return data


def load_question_state():
    text = QUESTIONS_FILE.read_text(encoding="utf-8")
    questions = parse_questions(text)
    categories = parse_categories(text)
    coverage = compute_coverage(questions, categories)
    return questions, categories, coverage


def load_candidates() -> list[dict]:
    data = read_json(QUESTION_CANDIDATES_FILE, default={}) or {}
    return list(data.get("candidates", []))


def frontmatter_value(text: str, key: str, default: str = "") -> str:
    match = re.search(rf"^{re.escape(key)}:\s*[\"']?(.+?)[\"']?\s*$", text, re.MULTILINE)
    return match.group(1).strip().strip('"').strip("'") if match else default


def _count_all_sources() -> dict[str, int]:
    """Count ingested source files by source type."""
    counts: dict[str, int] = {}
    if not SOURCES_DIR.exists():
        return counts
    for subdir in sorted(SOURCES_DIR.iterdir()):
        if subdir.is_dir() and subdir.name != ".gitkeep":
            n = sum(1 for f in subdir.glob("*.md") if f.is_file())
            if n:
                counts[subdir.name] = n
    return counts


def _count_classified(source_type: str) -> int:
    """Count classified sources for a given type."""
    if not CLASSIFICATIONS_DIR.exists():
        return 0
    # Classifications are stored by source stem
    count = 0
    source_dir = SOURCES_DIR / source_type
    if not source_dir.exists():
        return 0
    for path in source_dir.glob("*.md"):
        classification = CLASSIFICATIONS_DIR / f"{path.stem}.json"
        if classification.exists():
            count += 1
    return count


def read_manual_sources() -> list[dict]:
    if not MANUAL_SOURCES_DIR.exists():
        return []
    sources = []
    for path in sorted(MANUAL_SOURCES_DIR.glob("*.md")):
        text = path.read_text(encoding="utf-8", errors="replace")
        sources.append({
            "path": path.as_posix(),
            "title": frontmatter_value(text, "title", path.stem.replace("-", " ").title()),
            "source": frontmatter_value(text, "source", "manual"),
            "captured_at": frontmatter_value(text, "captured_at", ""),
        })
    sources.sort(key=lambda item: item.get("captured_at") or "", reverse=True)
    return sources


def read_answer_dates() -> dict[str, str]:
    dates = {}
    if not ANSWERS_DIR.exists():
        return dates
    for path in sorted(ANSWERS_DIR.glob("*.md")):
        qid = answer_id_from_filename(path)
        if not qid:
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        match = re.search(r"\*\*Asked:\*\*.*?\|\s*\*\*Answered:\*\*\s*([0-9-]+)", text)
        if match:
            dates[qid] = match.group(1)
    return dates


def read_answer_bodies() -> dict[str, str]:
    bodies = {}
    if not ANSWERS_DIR.exists():
        return bodies
    for path in sorted(ANSWERS_DIR.glob("*.md")):
        qid = answer_id_from_filename(path)
        if not qid:
            continue
        bodies[qid] = answer_body(path.read_text(encoding="utf-8", errors="replace"))
    return bodies


def category_ratio(coverage: dict, cat_id: str) -> float:
    data = coverage["categories"].get(cat_id, {})
    total = data.get("total", 0)
    return data.get("answered", 0) / total if total else 1.0


def infer_story_function(text: str, kind: str | None = None) -> str:
    if kind in KIND_TO_STORY_FUNCTION:
        return KIND_TO_STORY_FUNCTION[kind]
    haystack = text.lower()
    for function_name, keywords in STORY_FUNCTION_KEYWORDS.items():
        if any(keyword in haystack for keyword in keywords):
            return function_name
    if "tell me about" in haystack or "background" in haystack:
        return "foundation"
    return "foundation"


def objective_match(question: dict, objectives: list[dict]) -> tuple[str | None, int]:
    text = str(question.get("text", "")).lower()
    category = str(question.get("category", "")).upper()
    for objective in objectives:
        if objective.get("status", "active") != "active":
            continue
        categories = {str(c).upper() for c in objective.get("categories", [])}
        keywords = [str(k).lower() for k in objective.get("keywords", [])]
        if category in categories or any(keyword and keyword in text for keyword in keywords):
            return str(objective.get("label", "objective")), int(objective.get("max_questions", 3) or 3)
    return None, 0


def max_counts(limit: int, caps: dict[str, float]) -> dict[str, int]:
    return {key: max(1, math.ceil(limit * float(value))) for key, value in caps.items()}


def enriched_pending_questions(questions: list[dict], categories: dict, coverage: dict, objectives: list[dict]) -> list[dict]:
    rows = []
    for question in questions:
        if question["answered"]:
            continue
        category = str(question["category"])
        group = categories.get(category, {}).get("group", "main")
        story_function = infer_story_function(str(question["text"]))
        objective, objective_limit = objective_match(question, objectives)
        rows.append({
            **question,
            "group": group,
            "source_type": "question_bank",
            "story_function": story_function,
            "category_ratio": category_ratio(coverage, category),
            "objective": objective,
            "objective_limit": objective_limit,
        })
    rows.sort(key=lambda q: (
        q["objective"] is None,
        q["category_ratio"],
        q["group"] == "spotlight",
        qid_key(str(q["id"])),
    ))
    return rows


def accepted_candidate_recommendations(candidates: list[dict], limit: int = 8) -> list[dict]:
    rows = [c for c in candidates if c.get("status") == "accepted"]
    rows.sort(key=lambda c: (-float(c.get("priority", 0) or 0), c.get("created_at", "")))
    return rows[:limit]


def build_queue(limit: int, arc_max: int, expires_days: int = 7, planner_state: dict | None = None) -> dict:
    questions, categories, coverage = load_question_state()
    candidates = load_candidates()
    planner_state = planner_state or load_planner_state()
    caps = planner_state.get("caps", {})
    group_caps = caps.get("group", GROUP_CAPS)
    story_caps = caps.get("story_function", STORY_FUNCTION_CAPS)
    max_by_group = max_counts(limit, group_caps)
    max_by_story = max_counts(limit, story_caps)

    pending = enriched_pending_questions(questions, categories, coverage, planner_state.get("active_objectives", []))
    queue = []
    counts = Counter()
    story_counts = Counter()
    objective_counts = Counter()
    category_streak = None
    streak_count = 0

    remaining = pending[:]
    while remaining and len(queue) < limit:
        selected = None
        for question in remaining:
            cat = str(question["category"])
            group = str(question["group"])
            story_function = str(question["story_function"])
            objective = question.get("objective")
            objective_limit = int(question.get("objective_limit") or limit)
            if counts[group] >= max_by_group.get(group, limit):
                continue
            if story_counts[story_function] >= max_by_story.get(story_function, limit):
                continue
            if objective and objective_counts[objective] >= objective_limit:
                continue
            if cat == category_streak and streak_count >= arc_max:
                continue
            selected = question
            break

        if selected is None:
            selected = remaining[0]

        remaining.remove(selected)
        cat = str(selected["category"])
        group = str(selected["group"])
        story_function = str(selected["story_function"])
        if cat == category_streak:
            streak_count += 1
        else:
            category_streak = cat
            streak_count = 1

        counts[group] += 1
        story_counts[story_function] += 1
        if selected.get("objective"):
            objective_counts[str(selected["objective"])] += 1

        reason_parts = [
            f"{group} question from {cat}",
            f"{story_function} story function",
            f"category coverage {selected['category_ratio']:.0%}",
            f"arc cap {arc_max}",
        ]
        if selected.get("objective"):
            reason_parts.append(f"objective: {selected['objective']}")

        queue.append({
            "question_id": selected["id"],
            "category": cat,
            "group": group,
            "source": "question_bank",
            "source_type": selected["source_type"],
            "story_function": story_function,
            "objective": selected.get("objective"),
            "status": "queued",
            "reason": "; ".join(reason_parts),
        })

    return {
        "version": 2,
        "generated_at": now_utc(),
        "expires_at": future_timestamp(expires_days),
        "policy": {
            "limit": limit,
            "arc_max": arc_max,
            "expires_days": expires_days,
            "group_caps": group_caps,
            "story_function_caps": story_caps,
            "candidate_policy": "accepted candidates are recommended for promotion but not asked until promoted to question-bank",
        },
        "active_objectives": planner_state.get("active_objectives", []),
        "candidate_recommendations": accepted_candidate_recommendations(candidates),
        "queue": queue,
    }


def queue_is_stale(queue_data: dict) -> bool:
    if not queue_data.get("queue"):
        return False
    expires = parse_time(queue_data.get("expires_at"))
    return bool(expires and expires <= datetime.now(timezone.utc))


def category_latest_dates(questions: list[dict], answer_dates: dict[str, str]) -> dict[str, str]:
    latest = {}
    for question in questions:
        qid = str(question["id"])
        if not question["answered"] or qid not in answer_dates:
            continue
        cat = str(question["category"])
        latest[cat] = max(latest.get(cat, ""), answer_dates[qid])
    return latest


def category_story_counts(questions: list[dict]) -> dict[str, Counter]:
    counts = defaultdict(Counter)
    for question in questions:
        cat = str(question["category"])
        counts[cat][infer_story_function(str(question["text"]))] += 1
    return counts


def report(limit: int = 10) -> int:
    questions, categories, coverage = load_question_state()
    candidates = load_candidates()
    planner_state = load_planner_state()
    queue_data = read_json(QUESTION_QUEUE_FILE, default={}) or {}
    queue = queue_data.get("queue", [])
    answer_dates = read_answer_dates()
    latest_dates = category_latest_dates(questions, answer_dates)
    story_counts = category_story_counts(questions)

    print("Lifehug Planner Report")
    print()

    objectives = [o for o in planner_state.get("active_objectives", []) if o.get("status", "active") == "active"]
    print("Planner state:")
    if objectives:
        for objective in objectives:
            cats = ",".join(objective.get("categories", [])) or "-"
            kws = ",".join(objective.get("keywords", [])) or "-"
            print(f"- {objective.get('label')} (categories: {cats}; keywords: {kws})")
    else:
        print("- active objectives: none")

    print()
    print("Coverage by group:")
    grouped = defaultdict(lambda: {"answered": 0, "total": 0})
    for cat_id, data in coverage["categories"].items():
        group = categories.get(cat_id, {}).get("group", "main")
        grouped[group]["answered"] += data["answered"]
        grouped[group]["total"] += data["total"]
    for group in sorted(grouped):
        data = grouped[group]
        ratio = data["answered"] / data["total"] if data["total"] else 0
        cap = planner_state.get("caps", {}).get("group", GROUP_CAPS).get(group)
        cap_text = f", cap {cap:.0%}" if isinstance(cap, float) else ""
        print(f"- {group}: {data['answered']}/{data['total']} ({ratio:.0%}{cap_text})")

    print()
    print("Story-function balance in open question bank:")
    pending_functions = Counter(infer_story_function(str(q["text"])) for q in questions if not q["answered"])
    total_pending = sum(pending_functions.values()) or 1
    for function_name in STORY_FUNCTIONS:
        count = pending_functions.get(function_name, 0)
        print(f"- {function_name}: {count} ({count / total_pending:.0%})")

    print()
    print("Lowest-coverage categories:")
    rows = []
    for cat_id, data in coverage["categories"].items():
        total = data["total"]
        ratio = data["answered"] / total if total else 1
        rows.append((ratio, cat_id, data))
    for ratio, cat_id, data in sorted(rows)[:8]:
        name = categories.get(cat_id, {}).get("name", cat_id)
        print(f"- {cat_id} {name}: {data['answered']}/{data['total']} ({ratio:.0%})")

    print()
    print("Stale or untouched categories:")
    stale_rows = []
    for cat_id, data in coverage["categories"].items():
        if data["answered"] >= data["total"]:
            continue
        stale_rows.append((latest_dates.get(cat_id) or "0000-00-00", cat_id, data))
    for latest, cat_id, data in sorted(stale_rows)[:8]:
        label = latest if latest != "0000-00-00" else "never answered"
        name = categories.get(cat_id, {}).get("name", cat_id)
        print(f"- {cat_id} {name}: latest {label}; open {data['total'] - data['answered']}")

    print()
    print("Overrepresented areas:")
    answered_total = sum(data["answered"] for data in coverage["categories"].values()) or 1
    over_rows = []
    for cat_id, data in coverage["categories"].items():
        share = data["answered"] / answered_total
        ratio = data["answered"] / data["total"] if data["total"] else 0
        if data["answered"] >= 5 or ratio >= 0.70:
            over_rows.append((share, ratio, cat_id, data))
    for share, ratio, cat_id, data in sorted(over_rows, reverse=True)[:8]:
        name = categories.get(cat_id, {}).get("name", cat_id)
        print(f"- {cat_id} {name}: {data['answered']} answers, {ratio:.0%} covered, {share:.0%} of all answers")

    print()
    print("Narrative weak spots:")
    weak_rows = []
    for cat_id, counts in story_counts.items():
        total = sum(counts.values()) or 1
        scene_like = counts["scene"] + counts["tension"] + counts["turning_point"]
        ratio = scene_like / total
        answered = coverage["categories"].get(cat_id, {}).get("answered", 0)
        if answered >= 4 and ratio < 0.35:
            weak_rows.append((ratio, cat_id, answered))
    if weak_rows:
        for ratio, cat_id, answered in sorted(weak_rows)[:8]:
            name = categories.get(cat_id, {}).get("name", cat_id)
            print(f"- {cat_id} {name}: {answered} answers, only {ratio:.0%} scene/tension/turning-point questions")
    else:
        print("- none detected")

    sources = read_manual_sources()
    all_sources = _count_all_sources()
    print()
    print(f"Recent ingested sources: {len(sources)} manual, {sum(all_sources.values())} total across all types")
    if all_sources:
        for stype, count in sorted(all_sources.items()):
            classified = _count_classified(stype)
            print(f"  {stype}: {count} ingested, {classified} classified")
    for source in sources[:5]:
        print(f"- {source['captured_at'] or 'unknown date'}: {source['title']} [{source['source']}]")

    candidate_counts = Counter(c.get("status", "candidate") for c in candidates)
    print()
    print(f"Question candidates: {sum(candidate_counts.values())} total")
    if candidate_counts:
        print("- statuses: " + ", ".join(f"{status}={candidate_counts[status]}" for status in sorted(candidate_counts)))
    open_candidates = [c for c in candidates if c.get("status") in {"candidate", "accepted", "deferred"}]
    for candidate in sorted(open_candidates, key=lambda c: c.get("priority", 0), reverse=True)[:8]:
        story_function = infer_story_function(str(candidate.get("text", "")), candidate.get("kind"))
        print(f"- {candidate.get('id')}: {story_function}; {candidate.get('text')} [{candidate.get('source_path')}]")

    print()
    if queue:
        status = "stale" if queue_is_stale(queue_data) else "active"
        print(f"Active planned queue: {len(queue)} item(s), {status}, expires {queue_data.get('expires_at', 'unknown')}")
        for item in queue[:10]:
            print(f"- {item['question_id']} ({item.get('group')}/{item.get('story_function')}): {item['reason']}")
    else:
        print("Active planned queue: none")

    preview = build_queue(
        limit,
        int(planner_state.get("queue", {}).get("arc_max", 2)),
        int(planner_state.get("queue", {}).get("expires_after_days", 7)),
        planner_state,
    )
    print()
    print("Recommended next queue preview (read-only):")
    for item in preview["queue"][:limit]:
        print(f"- {item['question_id']} ({item['group']}/{item['story_function']}): {item['reason']}")
    if preview.get("candidate_recommendations"):
        print()
        print("Accepted candidate recommendations to promote:")
        for candidate in preview["candidate_recommendations"][:5]:
            print(f"- {candidate.get('id')}: {candidate.get('text')}")

    # Neighborhoods section
    neighborhoods_data = read_json(NEIGHBORHOODS_FILE, default={}) or {}
    neighborhoods = neighborhoods_data.get("neighborhoods", [])
    if neighborhoods:
        by_status = Counter(n.get("status", "draft") for n in neighborhoods)
        print()
        print(f"Neighborhoods: {len(neighborhoods)} total")
        print(f"  statuses: {', '.join(f'{s}={c}' for s, c in sorted(by_status.items()))}")
        for nbhd in neighborhoods[:5]:
            completeness = nbhd.get("completeness", 0)
            print(f"  - {nbhd.get('title', '?')} ({nbhd.get('type', '?')}) [{nbhd.get('status', 'draft')}] "
                  f"target: {nbhd.get('target_output', '?')}, completeness: {completeness:.0%}")
    else:
        print()
        print("Neighborhoods: none")

    # Spotlight recommendations section
    spotlight_data = read_json(SPOTLIGHT_RECS_FILE, default={}) or {}
    recs = spotlight_data.get("recommendations", [])
    pending_recs = [r for r in recs if r.get("status") == "pending"]
    if recs:
        print()
        print(f"Spotlight recommendations: {len(recs)} total, {len(pending_recs)} pending")
        for rec in sorted(pending_recs, key=lambda r: -r.get("score", 0))[:5]:
            strength = rec.get("evidence_strength", "?")
            emoji = {"strong": "\U0001f7e2", "moderate": "\U0001f7e1", "weak": "\U0001f534"}.get(strength, "\u26aa")
            print(f"  {emoji} {rec.get('entity', '?')} ({rec.get('type', '?')}) — score: {rec.get('score', 0):.1f} [{strength}]")
    else:
        print()
        print("Spotlight recommendations: none (run recommend-spotlights to generate)")

    unanswered = sum(1 for q in questions if not q["answered"])
    print()
    print(f"Unanswered question-bank items: {unanswered}")
    return 0


def print_state() -> int:
    print(json.dumps(load_planner_state(), indent=2))
    return 0


def add_objective(args: argparse.Namespace) -> int:
    state = load_planner_state(write_default=True)
    objective = {
        "id": f"obj-{slugify(args.objective_add)}",
        "label": args.objective_add,
        "status": "active",
        "categories": [c.upper() for c in args.objective_category],
        "keywords": args.objective_keyword,
        "max_questions": args.objective_max_questions,
        "created_at": now_utc(),
    }
    state.setdefault("active_objectives", []).append(objective)
    state["last_updated"] = now_utc()
    write_json(PLANNER_STATE_FILE, state)
    print(f"✓ Added planner objective: {objective['label']}")
    return 0


def clear_objectives() -> int:
    state = load_planner_state(write_default=True)
    state["active_objectives"] = []
    state["last_updated"] = now_utc()
    write_json(PLANNER_STATE_FILE, state)
    print("✓ Cleared planner objectives")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Lifehug question planner")
    parser.add_argument("--report", action="store_true", help="Show planner report")
    parser.add_argument("--write-queue", action="store_true", help="Write state/question_queue.json")
    parser.add_argument("--clear-queue", action="store_true")
    parser.add_argument("--state", action="store_true", help="Show planner state")
    parser.add_argument("--init-state", action="store_true", help="Create or refresh default planner state")
    parser.add_argument("--objective-add", help="Add an active planner objective")
    parser.add_argument("--objective-category", action="append", default=[])
    parser.add_argument("--objective-keyword", action="append", default=[])
    parser.add_argument("--objective-max-questions", type=int, default=3)
    parser.add_argument("--objective-clear", action="store_true")
    parser.add_argument("--limit", type=int, default=14)
    parser.add_argument("--arc-max", type=int, default=2)
    parser.add_argument("--expires-days", type=int, default=7)
    args = parser.parse_args()

    if args.init_state:
        load_planner_state(write_default=True)
        if not args.state:
            print(f"✓ Initialized planner state: {PLANNER_STATE_FILE.relative_to(PLANNER_STATE_FILE.parents[1])}")

    if args.state:
        return print_state()

    if args.objective_add:
        return add_objective(args)

    if args.objective_clear:
        return clear_objectives()

    if args.clear_queue:
        write_json(QUESTION_QUEUE_FILE, {"version": 2, "cleared_at": now_utc(), "queue": []})
        print("✓ Cleared question queue")
        return 0

    if args.write_queue:
        state = load_planner_state(write_default=True)
        data = build_queue(args.limit, args.arc_max, args.expires_days, state)
        write_json(QUESTION_QUEUE_FILE, data)
        print(f"✓ Wrote planned queue: {len(data['queue'])} item(s), expires {data['expires_at']}")
        return 0

    return report(args.limit)


if __name__ == "__main__":
    raise SystemExit(main())
