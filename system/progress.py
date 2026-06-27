#!/usr/bin/env python3
"""Lifehug progress / deliverable-readiness dashboard.

Answers the question Dave cares about most: *are we graduating toward finished
things?* For each Focus it shows fill vs. target and a readiness verdict, lists
neighborhoods (output arcs) with completeness, and suggests creating an
artifact when a Focus is ready to draft.
"""

from __future__ import annotations

import sys
from pathlib import Path

_SYSTEM_DIR = Path(__file__).resolve().parent
if str(_SYSTEM_DIR) not in sys.path:
    sys.path.insert(0, str(_SYSTEM_DIR))

from lifehug_core import NEIGHBORHOODS_FILE, QUESTIONS_FILE, parse_questions, read_json
from roadmap import focus_fill, load_roadmap, rebuild_roadmap

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


def run() -> int:
    roadmap = load_roadmap()
    if not roadmap.get("focuses"):
        roadmap = rebuild_roadmap(write=False)
    questions = parse_questions(QUESTIONS_FILE.read_text())
    nbhd = (read_json(NEIGHBORHOODS_FILE, default={}) or {}).get("neighborhoods", [])
    nbhd_by_focus: dict[str, list[dict]] = {}
    for n in nbhd:
        nbhd_by_focus.setdefault(n.get("type", ""), []).append(n)

    print("Lifehug — Progress toward deliverables\n")
    total_answered = total_target = 0
    ready_focuses = []
    for focus in roadmap["focuses"]:
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

    fullness = total_answered / total_target if total_target else 0
    print(f"\n  Overall: {total_answered}/{total_target} answered ({fullness:.0%} toward current targets)")

    if nbhd:
        print("\nNeighborhoods (output arcs):")
        for n in nbhd:
            c = n.get("completeness", 0)
            flag = "  ← ready to draft" if c >= 0.8 else ""
            print(f"  - {n.get('title','?')} ({n.get('type','?')}) → {n.get('target_output','?')}: "
                  f"{c:.0%} arc complete [{n.get('status','draft')}]{flag}")

    if ready_focuses:
        print("\nReady to create — suggested next artifacts:")
        for focus in ready_focuses:
            print(f"  • {focus['label']}:")
            print(f"      {artifact_hint(focus)}")

    # Expansion signal — when everything's full, it's time for new domains.
    if fullness >= 0.6:
        print(f"\n  Note: overall fullness {fullness:.0%} — consider research-expansion for new domains:")
        print("      python3 system/research_expand.py --gaps")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
