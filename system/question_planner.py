#!/usr/bin/env python3
"""Report and build Lifehug question queues with balance caps."""

from __future__ import annotations

import argparse
import math
import re
from collections import Counter, defaultdict

from lifehug_core import (
    QUESTION_CANDIDATES_FILE,
    QUESTION_QUEUE_FILE,
    QUESTIONS_FILE,
    compute_coverage,
    now_utc,
    parse_categories,
    parse_questions,
    read_json,
    write_json,
)

GROUP_CAPS = {
    "main": 0.50,
    "project": 0.35,
    "spotlight": 0.25,
}


def qid_key(qid: str) -> tuple[str, int, str]:
    match = re.match(r"^([A-Z])(\d+)([a-z]*)$", qid)
    if not match:
        return (qid[:1], 0, qid)
    return (match.group(1), int(match.group(2)), match.group(3))


def load_question_state():
    text = QUESTIONS_FILE.read_text(encoding="utf-8")
    questions = parse_questions(text)
    categories = parse_categories(text)
    coverage = compute_coverage(questions, categories)
    return questions, categories, coverage


def load_candidates() -> list[dict]:
    data = read_json(QUESTION_CANDIDATES_FILE, default={}) or {}
    return list(data.get("candidates", []))


def category_ratio(coverage: dict, cat_id: str) -> float:
    data = coverage["categories"].get(cat_id, {})
    total = data.get("total", 0)
    return data.get("answered", 0) / total if total else 1.0


def build_queue(limit: int, arc_max: int) -> dict:
    questions, categories, coverage = load_question_state()
    pending = [q for q in questions if not q["answered"]]
    pending.sort(key=lambda q: (
        category_ratio(coverage, q["category"]),
        categories.get(q["category"], {}).get("group", "main") == "spotlight",
        qid_key(q["id"]),
    ))

    max_by_group = {group: max(1, math.ceil(limit * ratio)) for group, ratio in GROUP_CAPS.items()}
    queue = []
    counts = Counter()
    category_streak = None
    streak_count = 0

    remaining = pending[:]
    while remaining and len(queue) < limit:
        selected = None
        for q in remaining:
            cat = q["category"]
            group = categories.get(cat, {}).get("group", "main")
            if counts[group] >= max_by_group.get(group, limit):
                continue
            if cat == category_streak and streak_count >= arc_max:
                continue
            selected = q
            break

        if selected is None:
            selected = remaining[0]

        remaining.remove(selected)
        cat = selected["category"]
        group = categories.get(cat, {}).get("group", "main")
        if cat == category_streak:
            streak_count += 1
        else:
            category_streak = cat
            streak_count = 1
        counts[group] += 1
        ratio = category_ratio(coverage, cat)
        queue.append({
            "question_id": selected["id"],
            "category": cat,
            "group": group,
            "source": "question_bank",
            "status": "queued",
            "reason": f"{group} question from {cat}; category coverage {ratio:.0%}; arc cap {arc_max}",
        })

    return {
        "version": 1,
        "last_updated": now_utc(),
        "policy": {
            "limit": limit,
            "arc_max": arc_max,
            "group_caps": GROUP_CAPS,
            "candidate_policy": "candidates are reported but not asked until promoted to question-bank",
        },
        "queue": queue,
    }


def report() -> int:
    questions, categories, coverage = load_question_state()
    candidates = load_candidates()
    queue_data = read_json(QUESTION_QUEUE_FILE, default={}) or {}
    queue = queue_data.get("queue", [])

    print("Lifehug Planner Report")
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
        print(f"- {group}: {data['answered']}/{data['total']} ({ratio:.0%})")

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

    open_candidates = [c for c in candidates if c.get("status") == "candidate"]
    print()
    print(f"Question candidates: {len(open_candidates)} open / {len(candidates)} total")
    for candidate in sorted(open_candidates, key=lambda c: c.get("priority", 0), reverse=True)[:8]:
        print(f"- {candidate.get('id')}: {candidate.get('text')} [{candidate.get('source_path')}]")

    print()
    if queue:
        print(f"Active planned queue: {len(queue)} item(s)")
        for item in queue[:10]:
            print(f"- {item['question_id']} ({item['group']}): {item['reason']}")
    else:
        print("Active planned queue: none")

    unanswered = sum(1 for q in questions if not q["answered"])
    print()
    print(f"Unanswered question-bank items: {unanswered}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Lifehug question planner")
    parser.add_argument("--report", action="store_true", help="Show planner report")
    parser.add_argument("--write-queue", action="store_true", help="Write state/question_queue.json")
    parser.add_argument("--clear-queue", action="store_true")
    parser.add_argument("--limit", type=int, default=14)
    parser.add_argument("--arc-max", type=int, default=2)
    args = parser.parse_args()

    if args.clear_queue:
        write_json(QUESTION_QUEUE_FILE, {"version": 1, "last_updated": now_utc(), "queue": []})
        print("✓ Cleared question queue")
        return 0

    if args.write_queue:
        data = build_queue(args.limit, args.arc_max)
        write_json(QUESTION_QUEUE_FILE, data)
        print(f"✓ Wrote planned queue: {len(data['queue'])} item(s)")
        return 0

    return report()


if __name__ == "__main__":
    raise SystemExit(main())
