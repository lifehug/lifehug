#!/usr/bin/env python3
"""Lifehug progress / deliverable-readiness dashboard.

Answers the question the author cares about most: *are we graduating toward finished
things?* For each Focus it shows fill vs. target and a readiness verdict, lists
neighborhoods (output arcs) with generated/promoted/answered readiness, and
suggests creating an artifact when a Focus or neighborhood is ready to draft.
"""

from __future__ import annotations

import sys
from pathlib import Path

_SYSTEM_DIR = Path(__file__).resolve().parent
if str(_SYSTEM_DIR) not in sys.path:
    sys.path.insert(0, str(_SYSTEM_DIR))

from lifehug_core import (
    CLASSIFICATIONS_DIR,
    NEIGHBORHOODS_FILE,
    QUESTION_CANDIDATES_FILE,
    QUESTIONS_FILE,
    parse_questions,
    read_json,
)
from neighborhoods import apply_readiness
from roadmap import focus_fill, load_roadmap, rebuild_roadmap


def _classifier_output_suggestions(limit: int = 5) -> list[tuple[str, str]]:
    """possible_outputs the weekly classifier extracted from real answers —
    write-only until v69. Deduped, most recent classifications win."""
    seen: set[str] = set()
    rows: list[tuple[str, str]] = []
    if not CLASSIFICATIONS_DIR.exists():
        return rows
    for path in sorted(CLASSIFICATIONS_DIR.glob("*.json"), reverse=True):
        data = read_json(path, default={}) or {}
        for item in data.get("possible_outputs", []) or []:
            if not isinstance(item, dict):
                continue
            kind = str(item.get("type", "piece")).strip()
            desc = str(item.get("description", "")).strip()
            key = (kind + ":" + desc.lower())[:80]
            if not desc or key in seen:
                continue
            seen.add(key)
            rows.append((kind, desc))
            if len(rows) >= limit:
                return rows
    return rows

# Saturation thresholds for the readiness verdict.
READY = 0.70
DEVELOPING = 0.40

# Map a Focus deliverable to the nearest artifact format.
DELIVERABLE_TO_FORMAT = {
    "book": "chapter", "chapter": "chapter", "memoir": "chapter",
    "letter": "letter", "essay": "chapter", "post": "post",
    "profile": "chapter", "tweet": "tweet",
}


def verdict(saturation: float) -> tuple[str, str]:
    if saturation >= READY:
        return "READY", "ready to draft"
    if saturation >= DEVELOPING:
        return "DEVELOPING", "building material"
    return "EARLY", "needs more answers"


def artifact_hint(focus: dict) -> str:
    fmt = DELIVERABLE_TO_FORMAT.get(focus.get("deliverable", "chapter"), "chapter")
    cats = ",".join(focus.get("categories", [])) or "?"
    label = str(focus.get("label", "")).replace('"', '\\"')
    return (f'python3 system/lifehug.py artifact new --format {fmt} '
            f'--subject "{label}" --categories {cats}   # -> {focus.get("deliverable", "draft")}')


def neighborhood_artifact_hint(neighborhood: dict) -> str:
    fmt = DELIVERABLE_TO_FORMAT.get(neighborhood.get("target_output", "chapter"), "chapter")
    subject = str(neighborhood.get("title", "")).replace('"', '\\"')
    return (f'python3 system/lifehug.py artifact new --format {fmt} '
            f'--subject "{subject}"   # -> {neighborhood.get("target_output", "draft")}')


def readiness_label(neighborhood: dict) -> str:
    status = neighborhood.get("readiness_status", "empty")
    if status == "answer_ready":
        return "ready to draft"
    if status == "answering":
        return "capturing answers"
    if status == "promoted":
        return "questions promoted"
    if status == "questions_generated":
        return "questions generated"
    return "needs questions"


def run() -> int:
    roadmap = load_roadmap()
    if not roadmap.get("focuses"):
        roadmap = rebuild_roadmap(write=False)
    questions = parse_questions(QUESTIONS_FILE.read_text())
    candidates = read_json(QUESTION_CANDIDATES_FILE, default={"version": 1, "candidates": []}) or {}
    nbhd = (read_json(NEIGHBORHOODS_FILE, default={}) or {}).get("neighborhoods", [])
    nbhd = [apply_readiness(n, candidates, questions) for n in nbhd]

    print("Lifehug — Progress toward deliverables\n")
    total_answered = total_target = 0
    ready_focuses = []
    ready_neighborhoods = []
    zombies = [f for f in roadmap["focuses"] if not f.get("categories")]
    for focus in roadmap["focuses"]:
        if not focus.get("categories"):
            continue  # zombie — listed separately below, excluded from totals
        fill = focus_fill(focus, questions)
        total_answered += fill["answered"]
        total_target += fill["target"]
        tag, label = verdict(fill["saturation"])
        if fill["saturated"]:
            tag, label = "SATURATED", "well-known — maintenance"
        bar = "█" * int(min(fill["saturation"], 1) * 12) + "·" * (12 - int(min(fill["saturation"], 1) * 12))
        phase = focus.get("phase", "active")
        phase_tag = f" «{phase}»" if phase != "active" else ""
        print(f"  {focus['label'][:22]:22}{phase_tag:12} {bar} "
              f"{fill['answered']:3}/{fill['target']:<3}  {tag:10} → {focus.get('deliverable','-')} ({label})")
        if tag in ("READY", "SATURATED") and fill["answered"] > 0:
            ready_focuses.append(focus)

    if zombies:
        print("\n  ⚠ Focuses with NO question category (the planner can never ask about these):")
        for focus in zombies:
            print(f"    - {focus.get('label', focus.get('id'))} — seed questions or remove")

    fullness = total_answered / total_target if total_target else 0
    print(f"\n  Overall: {total_answered}/{total_target} answered ({fullness:.0%} toward current targets)")

    if nbhd:
        print("\nNeighborhoods (output arcs):")
        for n in nbhd:
            counts = n.get("arc_lifecycle_counts", {})
            total = counts.get("total_slots", 0)
            generated = counts.get("questions_generated", 0)
            promoted = counts.get("questions_promoted", 0)
            answered = counts.get("answers_captured", 0)
            answered_c = n.get("answered_completeness", 0)
            if n.get("ready_to_draft"):
                ready_neighborhoods.append(n)
            flag = "  ← ready to draft" if n.get("ready_to_draft") else ""
            print(f"  - {n.get('title','?')} ({n.get('type','?')}) → {n.get('target_output','?')}: "
                  f"{answered_c:.0%} answer-ready "
                  f"({answered}/{total} answered, {promoted}/{total} promoted, {generated}/{total} generated) "
                  f"[{readiness_label(n)}]{flag}")

    if ready_focuses or ready_neighborhoods:
        print("\nReady to create — suggested next artifacts:")
        for focus in ready_focuses:
            print(f"  • {focus['label']}:")
            print(f"      {artifact_hint(focus)}")
        for neighborhood in ready_neighborhoods:
            print(f"  • {neighborhood.get('title', '?')} ({neighborhood.get('target_output', 'draft')}):")
            print(f"      {neighborhood_artifact_hint(neighborhood)}")
            # The WNRS Final Card move: a completed relational arc earns the
            # letter offer + a closing reflection.
            if neighborhood.get("type") == "relationship":
                print("      arc complete — offer the letter, and ask: "
                      "\"what surprised you about answering these?\"")

    # Artifact ideas the classifier spotted inside real answers
    # (possible_outputs was write-only until v69).
    classifier_outputs = _classifier_output_suggestions()
    if classifier_outputs:
        print("\nArtifact ideas spotted in your answers (weekly classifier):")
        for kind, desc in classifier_outputs:
            print(f"  • [{kind}] {desc}")

    # Expansion signal — when everything's full, it's time for new domains.
    if fullness >= 0.6:
        print(f"\n  Note: overall fullness {fullness:.0%} — consider research-expansion for new domains:")
        print("      python3 system/research_expand.py --gaps")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
