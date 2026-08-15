#!/usr/bin/env python3
"""Capture the Review lane's unified Quality column (issue #146, ADR 0008).

Boots the real owner-only viewer against `tests.walkthrough_lib`'s
disposable-vault / live-viewer / Playwright harness, seeded with 3 synthetic
candidates:

- `cand-clean` — stamped, penalty-free, high score (auto-promote territory).
- `cand-mid`   — stamped, parked in needs_review; the park reason quotes
  both the unified score and the tripped craft flag.
- `cand-heavy` — deliberately UNSTAMPED, so the Quality column must fall
  back to a live unified_quality_score() computation.

Then asserts:

1. the candidates table has ONE Quality column — the old separate Priority
   column is gone,
2. the stamped clean candidate renders its score with a breakdown
   (priority × multiplier, zero craft penalties),
3. the parked mid candidate's park reason quotes the unified score and its
   craft flag,
4. the unstamped heavy candidate renders via the live fallback (marked
   "live") with its own craft flags visible.

Usage:
    python3 tests/walkthrough_unified_quality.py \
      --artifacts artifacts/walkthroughs/unified-quality
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SYSTEM = ROOT / "system"
TESTS = ROOT / "tests"
sys.path.insert(0, str(SYSTEM))
sys.path.insert(0, str(TESTS))

import walkthrough_lib  # noqa: E402

CANDIDATES = {
    "version": 1,
    "candidates": [
        {
            "id": "cand-clean",
            "status": "candidate",
            "text": (
                "Walk me through the day you decided to leave — what did the "
                "room look like, and what were you most afraid of?"
            ),
            "priority": 0.90,
            "target_category": "A",
            "story_function": "turning_point",
            "source_path": "answers/B1.md",
            "created_at": "2026-08-01T00:00:00Z",
            "quality": {
                "score": 0.90,
                "components": {
                    "priority": 0.90,
                    "story_function_multiplier": 1.0,
                    "craft_penalties": [],
                    "penalty_total": 0.0,
                },
                "computed_at": "2026-08-14T12:00:00Z",
            },
        },
        {
            "id": "cand-mid",
            "status": "needs_review",
            "text": "Why do you always struggle with that decision?",
            "priority": 0.95,
            "target_category": "A",
            "story_function": "turning_point",
            "source_path": "answers/B2.md",
            "created_at": "2026-08-01T00:00:00Z",
            "needs_review_reason": "score 0.75 below threshold 0.82 (self_directed_why)",
            "quality": {
                "score": 0.75,
                "components": {
                    "priority": 0.95,
                    "story_function_multiplier": 1.0,
                    "craft_penalties": [{"flag": "self_directed_why", "penalty": 0.20}],
                    "penalty_total": 0.20,
                },
                "computed_at": "2026-08-14T12:00:00Z",
            },
        },
        {
            "id": "cand-heavy",
            "status": "candidate",
            # Deliberately UNSTAMPED — no "quality" key — so the Quality
            # column must fall back to a live computation for this row.
            "text": "Did you?",
            "priority": 0.95,
            "target_category": "A",
            "created_at": "2026-08-01T00:00:00Z",
        },
    ],
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifacts", type=Path, required=True)
    args = parser.parse_args()
    artifacts = args.artifacts.resolve()
    artifacts.mkdir(parents=True, exist_ok=True)

    with walkthrough_lib.WalkthroughHarness(
        question_candidates=CANDIDATES, viewport={"width": 1440, "height": 900}
    ) as harness:
        page = harness.page
        page.goto(f"{harness.base_url}/views/review", wait_until="networkidle")
        body = page.content()

        # --- 1. one Quality column, no separate Priority column -----------
        if "<th>Quality</th>" not in body:
            raise RuntimeError("Quality column header missing")
        if "<th>Priority</th>" in body:
            raise RuntimeError("the old separate Priority column is still rendering")

        # --- 2. stamped clean-high candidate: score + breakdown, no flags -
        if "0.90" not in body:
            raise RuntimeError("clean-high candidate's stamped score (0.90) did not render")
        if "0.90×1.00" not in body:
            raise RuntimeError(
                "clean-high candidate's breakdown (priority×multiplier) did not render")

        # --- 3. parked mid-flagged candidate: reason quotes score + flag --
        if "score 0.75 below threshold 0.82" not in body:
            raise RuntimeError(
                "mid-flagged candidate's park reason did not quote the unified score")
        if "self_directed_why" not in body:
            raise RuntimeError(
                "mid-flagged candidate's park reason did not quote the craft flag")
        if "parked: score 0.75" not in body:
            raise RuntimeError("park reason is not visible in the rendered row")

        # --- 4. unstamped heavy-flagged candidate: live fallback ----------
        if "0.30" not in body:
            raise RuntimeError("heavy-flagged candidate's live-computed score (0.30) did not render")
        if 'class="q-live' not in body:
            raise RuntimeError("heavy-flagged candidate did not render via the live fallback")
        if "yes_no_wording" not in body or "too_short" not in body:
            raise RuntimeError("heavy-flagged candidate's live-computed craft flags did not render")

        page.screenshot(path=str(artifacts / "review-quality-column-1440x900.png"), full_page=True)
        page.set_viewport_size({"width": 390, "height": 844})
        page.goto(f"{harness.base_url}/views/review", wait_until="networkidle")
        page.screenshot(path=str(artifacts / "review-quality-column-390x844.png"), full_page=True)

    expected = {
        "review-quality-column-1440x900.png",
        "review-quality-column-390x844.png",
    }
    found = {p.name for p in artifacts.glob("*.png")}
    missing = expected - found
    if missing:
        raise RuntimeError(f"missing expected screenshots: {sorted(missing)}")
    for name in expected:
        walkthrough_lib.png_dimensions(artifacts / name)

    print(f"unified-quality walkthrough OK — {len(expected)} screenshots captured in {artifacts}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
