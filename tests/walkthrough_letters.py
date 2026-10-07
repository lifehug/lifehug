#!/usr/bin/env python3
"""Capture letter records in Source Integrity and the v120 reader (lifehug#471 PR 1).

Boots the real owner-only viewer on ``tests.walkthrough_lib``'s disposable
synthetic vault, files the synthetic fixture letters repository
(``tests/fixtures/letters_repo``, committed into a throwaway git repo) through
``lifehug.py documents file``, then asserts and screenshots:

1. ``/views/sources``: letters listed under their own ``letter`` type, one
   table per collection, with Written / Writer / Recipient columns;
2. ``/source/sources/letters/pat-mission/dad-letter.md``: the reader's letter
   fields, the scan link, the page marker as a quiet label, and the transcript
   header opened from its collapsed block.

Usage:
    python3 tests/walkthrough_letters.py --artifacts artifacts/walkthroughs/letters
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SYSTEM = ROOT / "system"
TESTS = ROOT / "tests"
sys.path.insert(0, str(SYSTEM))
sys.path.insert(0, str(TESTS))

import walkthrough_lib  # noqa: E402

FIXTURE = TESTS / "fixtures" / "letters_repo"
GIT = ["git", "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid"]


def file_fixture_letters(harness: walkthrough_lib.WalkthroughHarness) -> None:
    repo = harness.vault.parent / "letters-repo"
    shutil.copytree(FIXTURE, repo)
    for args in (["init", "-q", "-b", "main"], ["add", "-A"], ["commit", "-q", "-m", "fixture"]):
        subprocess.run([*GIT, "-C", str(repo), *args], check=True)
    result = subprocess.run(
        [sys.executable, str(SYSTEM / "lifehug.py"), "documents", "file", str(repo), "--all",
         "--commit", "HEAD", "--map", "pat-owner=self", "--map", "sam-owner=person/dad",
         "--map", "lee-owner=person/mom",
         "--scan-url-template", "https://letters.example/letters/{id}/scan.pdf"],
        cwd=harness.vault, env=harness.env, capture_output=True, text=True,
    )
    if result.returncode != 0 or "wrote: 5 (5 new" not in result.stdout:
        raise RuntimeError(f"documents file failed: {result.stdout}{result.stderr}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifacts", type=Path, required=True)
    args = parser.parse_args()
    artifacts = args.artifacts.resolve()
    artifacts.mkdir(parents=True, exist_ok=True)
    reader = "/source/sources/letters/pat-mission/dad-letter.md"

    with walkthrough_lib.WalkthroughHarness(viewport={"width": 1440, "height": 900}) as harness:
        file_fixture_letters(harness)
        page = harness.page

        page.goto(f"{harness.base_url}/views/sources", wait_until="networkidle")
        body = page.content()
        for needle in ("<h3>letter (5)</h3>", "<h4>pat-mission (4)</h4>", "<h4>old-box (1)</h4>",
                       "<th>Written</th>", "<th>Writer</th>", "<th>Recipient</th>",
                       "Dad (Sam Owner) to Elder Owner, 12 June 2001", "2001-06-12"):
            if needle not in body:
                raise RuntimeError(f"Sources view is missing {needle!r}")
        page.locator("h3", has_text="letter (5)").scroll_into_view_if_needed()
        page.screenshot(path=str(artifacts / "sources-letters-1440x900.png"), full_page=True)

        page.goto(f"{harness.base_url}{reader}", wait_until="networkidle")
        body = page.content()
        for needle in ("<td>Writer</td><td>Dad (Sam Owner)</td>", "<td>Recipient refs</td><td>self</td>",
                       "<td>Written</td><td>2001-06-12</td>", "<td>Collection</td><td>pat-mission</td>",
                       "https://letters.example/letters/pat-mission/dad-letter/scan.pdf",
                       "<em>[scan page 1; confidence 0.90]</em>", 'class="transcript-header"'):
            if needle not in body:
                raise RuntimeError(f"reader is missing {needle!r}")
        page.locator("details.transcript-header summary").click()
        page.screenshot(path=str(artifacts / "reader-letter-1440x900.png"), full_page=True)

        page.set_viewport_size({"width": 390, "height": 844})
        page.goto(f"{harness.base_url}/views/sources", wait_until="networkidle")
        page.screenshot(path=str(artifacts / "sources-letters-390x844.png"), full_page=True)
        page.goto(f"{harness.base_url}{reader}", wait_until="networkidle")
        page.screenshot(path=str(artifacts / "reader-letter-390x844.png"), full_page=True)

    expected = {
        "sources-letters-1440x900.png", "reader-letter-1440x900.png",
        "sources-letters-390x844.png", "reader-letter-390x844.png",
    }
    missing = expected - {p.name for p in artifacts.glob("*.png")}
    if missing:
        raise RuntimeError(f"missing expected screenshots: {sorted(missing)}")
    for name in expected:
        walkthrough_lib.png_dimensions(artifacts / name)
    print(f"letters walkthrough OK — {len(expected)} screenshots captured in {artifacts}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
