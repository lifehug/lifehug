#!/usr/bin/env python3
"""Capture the Review page's Entity candidates lane and its owner-verdict
flow (entity-owner-verdicts contract, Scope 3 — ADR 0013).

Boots the real owner-only viewer against ``tests.walkthrough_lib``'s
disposable-vault / live-viewer / Playwright harness, seeded with two
synthetic person candidates: "Trevor" (below the automatic score/answers
bar) and "Junk Fragment" (a detector false-positive the AI keeps
re-proposing). Two actions are exercised end to end:

  1. **Graduate now** on Trevor — the queued job forces his roster entry's
     ``page_eligible`` true and he moves from the Candidates table into the
     Owner-decided roster-browser table with the small ``owner`` tag.
  2. **Not a page** on Junk Fragment — the queued job forces his
     ``page_eligible`` false forever and he disappears from the lane
     entirely (no further viewer affordance — Scope 3).

Four states are captured, at both viewports:

  1. **before** — the lane open (both candidates carry real actions now,
     so it opens by default), both candidates listed with their actions.
  2. **graduate-queued** — the interaction sequence: press Graduate now on
     Trevor, land back on Review with the flash confirming the verdict was
     enqueued. Recorded to video and converted to a GIF.
  3. **veto-queued** — the same sequence for Junk Fragment's Not a page.
  4. **after** — both enqueued jobs have actually run (this script only
     WATCHES the person roster file until the worker applies both
     verdicts; it never applies them itself): Trevor shows in
     Owner-decided with the owner tag, Junk Fragment is gone, and the
     candidates count has dropped to 0.

The whole path is real: each button POSTs to ``/actions/entity-verdict``,
the handler enqueues an ``entity-verdict`` job, ``jobs.enqueue``'s kick
starts the worker, and the worker runs the same ``lifehug entity-verdict``
verb the CLI runs, under the single-writer lock.

No private vault is read or written: everything lives in the harness's
temporary directory.

Usage:
    python3 tests/walkthrough_entity_verdicts.py \
      --artifacts artifacts/walkthroughs/entity-verdicts
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SYSTEM = ROOT / "system"
TESTS = ROOT / "tests"
sys.path.insert(0, str(SYSTEM))
sys.path.insert(0, str(TESTS))

# See walkthrough_focus_merge.py for why both the module tempdir and TMPDIR
# must be pinned to the resolved, symlink-free path on macOS.
tempfile.tempdir = str(Path(tempfile.gettempdir()).resolve())
os.environ["TMPDIR"] = tempfile.tempdir

import walkthrough_lib  # noqa: E402

PERSON_ROSTER = {
    "version": 1, "type": "person", "resolved_at": "2026-08-01T00:00:00Z", "source": "ai",
    "entities": [
        {"name": "Trevor", "slug": "trevor", "aliases": [], "qualifies": False,
         "maps_to_focus": None, "score": 1.0, "unique_answers": 0, "page_eligible": False},
        {"name": "Junk Fragment", "slug": "junk-fragment", "aliases": [], "qualifies": True,
         "maps_to_focus": None, "score": 3.0, "unique_answers": 1, "page_eligible": False},
    ],
}


def seed_entity_candidates(vault: Path) -> None:
    """Write the synthetic person-roster candidate pair into the harness's
    disposable vault. Every path here is inside the temp vault."""
    walkthrough_lib.write_json(vault / "state" / "entity_rosters" / "person.json", PERSON_ROSTER)


def _person_entities(vault: Path) -> list[dict]:
    path = vault / "state" / "entity_rosters" / "person.json"
    return json.loads(path.read_text(encoding="utf-8"))["entities"]


def wait_for_verdict(vault: Path, slug: str, expected_page_eligible: bool, timeout: float = 60.0) -> None:
    """Wait for the ENQUEUED job to apply one verdict. This never applies
    the verdict itself — it only watches the person roster file until the
    worker `jobs.enqueue`'s kick started has written the expected
    page_eligible for `slug`."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        entities = _person_entities(vault)
        entity = next((e for e in entities if e.get("slug") == slug), None)
        if entity is not None and bool(entity.get("page_eligible")) == expected_page_eligible:
            print(f"the queued entity-verdict job completed for {slug}: page_eligible={expected_page_eligible}")
            return
        time.sleep(0.5)
    raise RuntimeError(f"the enqueued entity-verdict job for {slug} never completed")


def _row_button(page, row_text: str, button_text: str):
    return page.locator("tr", has_text=row_text).get_by_role("button", name=button_text)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifacts", type=Path, required=True)
    args = parser.parse_args()
    artifacts = args.artifacts.resolve()
    artifacts.mkdir(parents=True, exist_ok=True)

    with walkthrough_lib.WalkthroughHarness(
        viewport={"width": 1440, "height": 900}, record_video=True
    ) as harness:
        page = harness.page
        vault = harness.vault
        assert vault is not None
        seed_entity_candidates(vault)

        review = f"{harness.base_url}/views/review"

        # --- state 1: both candidates, before ----------------------------
        page.goto(review, wait_until="networkidle")
        body = page.content()
        if "Entity candidates" not in body:
            raise RuntimeError("the Entity candidates lane did not render")
        if "2 entity candidates" not in body:
            raise RuntimeError("Review's summary line did not count both candidates")
        for expected in ("Trevor", "Junk Fragment", "Graduate now", "Not a page"):
            if expected not in body:
                raise RuntimeError(f"the lane is missing {expected!r}")
        page.screenshot(path=str(artifacts / "review-entities-before-1440x900.png"), full_page=True)

        # --- state 2: the Graduate-now sequence (recorded) ---------------
        _row_button(page, "Trevor", "Graduate now").click()
        page.wait_for_load_state("networkidle")
        graduated = page.content()
        if "queued graduate now for person/trevor" not in graduated:
            raise RuntimeError("the Graduate now action did not report the verdict as queued")
        page.screenshot(path=str(artifacts / "review-entities-graduate-queued-1440x900.png"), full_page=True)

        # --- state 3: the Not-a-page sequence (recorded, same page) ------
        _row_button(page, "Junk Fragment", "Not a page").click()
        page.wait_for_load_state("networkidle")
        vetoed = page.content()
        if "queued not a page for person/junk-fragment" not in vetoed:
            raise RuntimeError("the Not a page action did not report the verdict as queued")
        page.screenshot(path=str(artifacts / "review-entities-veto-queued-1440x900.png"), full_page=True)

        # --- let both enqueued jobs actually run -------------------------
        wait_for_verdict(vault, "trevor", True)
        wait_for_verdict(vault, "junk-fragment", False)

        # --- state 4: settled -------------------------------------------
        page.goto(review, wait_until="networkidle")
        after = page.content()
        if "0 entity candidates" not in after:
            raise RuntimeError("Review's summary line did not drop to zero")
        if "Junk Fragment" in after:
            raise RuntimeError("the vetoed entity did not disappear from the lane entirely")
        if "Owner-decided" not in after or "Trevor" not in after:
            raise RuntimeError("the graduated entity did not appear in the Owner-decided table")
        if "owner" not in after:
            raise RuntimeError("the small owner tag did not render")
        page.screenshot(path=str(artifacts / "review-entities-after-1440x900.png"), full_page=True)

        video = page.video
        page.close()  # closing the page finalizes the recording
        if video is None:
            raise RuntimeError("no video was recorded for the verdict sequence")
        webm = artifacts / "verdict-sequence.webm"
        # save_as() blocks until the recording is fully written and copies
        # across filesystems; Path.replace() on video.path() can race the
        # muxer and hand ffmpeg a truncated file.
        video.save_as(str(webm))
        video.delete()
        walkthrough_lib.make_compact_gif(webm, artifacts / "verdict-sequence.gif")

    # --- a second run, phone-first, for the before/queued/after phone stills
    with walkthrough_lib.WalkthroughHarness(viewport={"width": 390, "height": 844}) as harness:
        page = harness.page
        vault = harness.vault
        assert vault is not None
        seed_entity_candidates(vault)
        review = f"{harness.base_url}/views/review"
        page.goto(review, wait_until="networkidle")
        page.screenshot(path=str(artifacts / "review-entities-before-390x844.png"), full_page=True)

        _row_button(page, "Trevor", "Graduate now").click()
        page.wait_for_load_state("networkidle")
        page.screenshot(path=str(artifacts / "review-entities-graduate-queued-390x844.png"), full_page=True)

        _row_button(page, "Junk Fragment", "Not a page").click()
        page.wait_for_load_state("networkidle")
        page.screenshot(path=str(artifacts / "review-entities-veto-queued-390x844.png"), full_page=True)

        # Let this run's worker finish before the harness tears its vault
        # down — a worker still writing into the temp vault makes
        # TemporaryDirectory.cleanup() fail with "Directory not empty".
        wait_for_verdict(vault, "trevor", True)
        wait_for_verdict(vault, "junk-fragment", False)
        page.goto(review, wait_until="networkidle")
        page.screenshot(path=str(artifacts / "review-entities-after-390x844.png"), full_page=True)
        time.sleep(1.0)

    expected_stills = {
        "review-entities-before-1440x900.png",
        "review-entities-before-390x844.png",
        "review-entities-graduate-queued-1440x900.png",
        "review-entities-graduate-queued-390x844.png",
        "review-entities-veto-queued-1440x900.png",
        "review-entities-veto-queued-390x844.png",
        "review-entities-after-1440x900.png",
        "review-entities-after-390x844.png",
    }
    found = {p.name for p in artifacts.glob("*.png")}
    missing = expected_stills - found
    if missing:
        raise RuntimeError(f"missing expected screenshots: {sorted(missing)}")
    for name in expected_stills:
        width, _height = walkthrough_lib.png_dimensions(artifacts / name)
        wanted = 1440 if "1440x900" in name else 390
        if width != wanted:
            raise RuntimeError(f"{name} is {width}px wide, expected {wanted}")
    for motion in ("verdict-sequence.gif", "verdict-sequence.webm"):
        if not (artifacts / motion).exists():
            raise RuntimeError(f"missing motion evidence: {motion}")

    print(f"entity-verdicts walkthrough OK — {len(expected_stills)} stills + GIF + webm in {artifacts}")
    print(json.dumps(sorted(p.name for p in artifacts.iterdir()), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
