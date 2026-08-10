#!/usr/bin/env python3
"""Capture Answers view evidence against a disposable synthetic vault (#110).

Boots the real owner-only viewer against `tests.walkthrough_lib`'s
disposable-vault / live-viewer / Playwright harness, then:

1. asserts the empty state renders when the vault has no answers yet,
2. writes synthetic answer files (never ~/Workspace/dave) and reloads,
3. asserts the menu shows Answers under System (next to Source Integrity),
4. asserts rows render question text, category, date, and word count
   newest-first (missing dates sorted last as "unknown"),
5. asserts a row's action link targets /source-actions?ref=answers/<file>
   and that navigating it lands on the real act-on-source page.

Usage:
    python3 tests/walkthrough_answers.py \
      --artifacts artifacts/walkthroughs/answers
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SYSTEM = ROOT / "system"
TESTS = ROOT / "tests"
sys.path.insert(0, str(SYSTEM))
sys.path.insert(0, str(TESTS))

import walkthrough_lib  # noqa: E402


def _write_answer(vault: Path, filename: str, metadata: dict, body: str) -> None:
    lines = ["---"]
    for key, value in metadata.items():
        lines.append(f"{key}: {json.dumps(value)}")
    lines.append("---")
    content = "\n".join(lines) + "\n\n" + body + "\n"
    (vault / "answers" / filename).write_text(content, encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifacts", type=Path, required=True)
    args = parser.parse_args()
    artifacts = args.artifacts.resolve()
    artifacts.mkdir(parents=True, exist_ok=True)

    with walkthrough_lib.WalkthroughHarness(viewport={"width": 1440, "height": 900}) as harness:
        page = harness.page

        # --- 1. empty state -------------------------------------------------
        page.goto(f"{harness.base_url}/views/answers", wait_until="networkidle")
        if "No answers yet" not in page.content():
            raise RuntimeError("empty state did not render for a vault with no answers")
        if page.locator("table.dash").count() != 0:
            raise RuntimeError("empty state must not render a table")
        page.screenshot(path=str(artifacts / "answers-empty-1440x900.png"), full_page=True)

        # --- 2. menu shows Answers under System, next to Source Integrity --
        page.click("#menuBtn")
        dropdown = page.locator("#menuDropdown")
        if "open" not in (page.locator("#menuDropdown").get_attribute("class") or ""):
            raise RuntimeError("menu dropdown did not open")
        menu_html = dropdown.inner_html()
        system_idx = menu_html.find(">System<")
        sources_idx = menu_html.find("Source Integrity")
        answers_idx = menu_html.find(">Answers<")
        if not (system_idx != -1 and system_idx < sources_idx < answers_idx):
            raise RuntimeError(
                "Answers is not listed under System, after Source Integrity, "
                f"in the menu markup: {menu_html!r}")
        page.click("#menuBtn")  # close it again

        # --- 3. populate synthetic answers (never ~/Workspace/dave) --------
        assert harness.vault is not None
        _write_answer(
            harness.vault, "A1.md",
            {
                "title": "Question A1: Earliest?",
                "question_id": "A1",
                "question_text": "What is your earliest memory?",
                "category": "A",
                "category_name": "Origins",
                "answered_date": "2026-01-01",
            },
            "# Question A1: Earliest?\n\nOne two three four five.",
        )
        _write_answer(
            harness.vault, "F1.md",
            {
                "title": "Question F1: Why?",
                "question_id": "F1",
                "question_text": "Why did you start it?",
                "category": "F",
                "category_name": "The Problem",
                "answered_date": "2026-03-15",
            },
            "# Question F1: Why?\n\nOne two three.",
        )
        _write_answer(
            harness.vault, "B1.md",
            {
                "title": "Question B1: Undated",
                "question_id": "B1",
                "question_text": "A question answered before dates were tracked",
                "category": "B",
                "category_name": "Undated Era",
            },
            "No answered_date on this one.",
        )

        page.goto(f"{harness.base_url}/views/answers", wait_until="networkidle")
        body_text = page.content()

        # --- 4. summary line + newest-first ordering + fallback ------------
        if "3 answers · 2026-01-01 → 2026-03-15" not in body_text:
            raise RuntimeError("summary line missing or wrong (N answers · first -> last date)")
        f1_pos = body_text.find("Why did you start it?")
        a1_pos = body_text.find("What is your earliest memory?")
        b1_pos = body_text.find("A question answered before dates were tracked")
        if not (f1_pos != -1 and a1_pos != -1 and b1_pos != -1 and f1_pos < a1_pos < b1_pos):
            raise RuntimeError(
                "rows are not newest-first with the undated row last "
                f"(F1={f1_pos}, A1={a1_pos}, B1={b1_pos})")
        if "unknown" not in body_text:
            raise RuntimeError("undated row did not render its date as 'unknown'")
        for expected in ("Origins", "The Problem", "Undated Era", "2026-01-01", "2026-03-15"):
            if expected not in body_text:
                raise RuntimeError(f"expected {expected!r} in the rendered rows")
        # A1 body word count: "# Question A1: Earliest?" (4) + "One two three
        # four five." (5) = 9. F1: "# Question F1: Why?" (4) + "One two
        # three." (3) = 7.
        if ">9<" not in body_text or ">7<" not in body_text:
            raise RuntimeError("word counts did not render as expected (9 and 7)")

        # --- 5. header note explains the missing status column --------------
        if "synchronous" not in body_text:
            raise RuntimeError(
                "the view's header line does not explain why there is no "
                "status column (filing is synchronous locally)")

        page.screenshot(path=str(artifacts / "answers-populated-1440x900.png"), full_page=True)
        page.set_viewport_size({"width": 390, "height": 844})
        page.goto(f"{harness.base_url}/views/answers", wait_until="networkidle")
        page.screenshot(path=str(artifacts / "answers-populated-390x844.png"), full_page=True)
        page.set_viewport_size({"width": 1440, "height": 900})
        page.goto(f"{harness.base_url}/views/answers", wait_until="networkidle")

        # --- 6. row action link targets /source-actions?ref=answers/<file> -
        link = page.locator('a[href="/source-actions?ref=answers/F1.md"]')
        if link.count() != 1:
            raise RuntimeError("F1's row is missing its /source-actions action link")
        link.click()
        page.wait_for_url("**/source-actions?ref=answers/F1.md")
        if "Act on" not in page.content() and "act" not in page.content().lower():
            raise RuntimeError("clicking the action link did not land on the act-on-source page")
        page.screenshot(path=str(artifacts / "answers-source-actions-1440x900.png"), full_page=True)

    expected = {
        "answers-empty-1440x900.png",
        "answers-populated-1440x900.png",
        "answers-populated-390x844.png",
        "answers-source-actions-1440x900.png",
    }
    found = {p.name for p in artifacts.glob("*.png")}
    missing = expected - found
    if missing:
        raise RuntimeError(f"missing expected screenshots: {sorted(missing)}")
    for name in expected:
        walkthrough_lib.png_dimensions(artifacts / name)  # raises if not a valid PNG

    print(f"answers walkthrough OK — {len(expected)} screenshots captured in {artifacts}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
