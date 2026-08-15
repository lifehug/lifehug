#!/usr/bin/env python3
"""Capture the Review lane's history-lane decision-reason display
(decisions-feed-the-loop contract, Scope 1 — the field-overwrite fix).

Before this fix, ``question_candidates.update_candidate()``'s ``reason``
kwarg clobbered the generator's own provenance ``reason`` field in place —
a dismissed/deferred/promoted candidate's ORIGINAL "why this was proposed"
text was gone the moment the owner typed a decision reason over it. The
fix writes the owner's text to a new ``decision_reason`` field instead, so
both survive.

Boots the real owner-only viewer against ``tests.walkthrough_lib``'s
disposable-vault / live-viewer / Playwright harness, seeded with one
``rejected`` candidate carrying BOTH a generator ``reason`` (provenance —
why it was proposed) and an owner ``decision_reason`` (why it was
dismissed). Asserts the Review lane's history section (the "rejected"
status group) renders both, labeled distinctly.

Usage:
    python3 tests/walkthrough_decision_reason.py \
      --artifacts artifacts/walkthroughs/decision-reason
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
            "id": "cand-dismissed",
            "status": "rejected",
            "text": "Did you go to the store that day?",
            "priority": 0.55,
            "target_category": "A",
            "story_function": "scene",
            "source_path": "answers/B1.md",
            "created_at": "2026-08-01T00:00:00Z",
            "updated_at": "2026-08-14T00:00:00Z",
            # Generator provenance — set at candidate-creation time, never
            # touched again after this PR's fix.
            "reason": "classifier inferred this from a store receipt mentioned in the source",
            # Owner's decision — a DISTINCT field now (the overwrite fix).
            "decision_reason": "already covered by B7 last month, and it reads as a yes/no form question",
        },
        {
            "id": "cand-candidate",
            "status": "candidate",
            "text": "Walk me through the morning of the move, start to finish.",
            "priority": 0.80,
            "target_category": "A",
            "story_function": "scene",
            "source_path": "answers/B2.md",
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

        # --- 1. the "rejected" history group renders at all -----------
        if "<h3>rejected (1)</h3>" not in body:
            raise RuntimeError("the rejected history group did not render")

        # --- 2. BOTH the provenance reason and the owner's decision
        #        reason are visible, labeled distinctly ------------------
        if "proposed: classifier inferred this from a store receipt" not in body:
            raise RuntimeError("the generator's provenance reason did not render in the history lane")
        if "owner: already covered by B7 last month" not in body:
            raise RuntimeError("the owner's decision_reason did not render in the history lane")
        if 'class="q-provenance-reason' not in body or 'class="q-decision-reason' not in body:
            raise RuntimeError("provenance/decision reason cells are not distinctly labeled")

        # --- 3. the untouched candidate row is unaffected ------------------
        if "Walk me through the morning of the move" not in body:
            raise RuntimeError("the actionable candidate row did not render")

        page.screenshot(path=str(artifacts / "review-decision-reason-1440x900.png"), full_page=True)
        page.set_viewport_size({"width": 390, "height": 844})
        page.goto(f"{harness.base_url}/views/review", wait_until="networkidle")
        page.screenshot(path=str(artifacts / "review-decision-reason-390x844.png"), full_page=True)

    expected = {
        "review-decision-reason-1440x900.png",
        "review-decision-reason-390x844.png",
    }
    found = {p.name for p in artifacts.glob("*.png")}
    missing = expected - found
    if missing:
        raise RuntimeError(f"missing expected screenshots: {sorted(missing)}")
    for name in expected:
        walkthrough_lib.png_dimensions(artifacts / name)

    print(f"decision-reason walkthrough OK — {len(expected)} screenshots captured in {artifacts}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
