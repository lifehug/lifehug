#!/usr/bin/env python3
"""Capture the Review page's Duplicate focuses lane and its Combine flow
(focus-merge contract, Scope 3 — ADR 0012).

Boots the real owner-only viewer against ``tests.walkthrough_lib``'s
disposable-vault / live-viewer / Playwright harness, seeded with the
synthetic "fear" / "The Fear" duplicate pair the contract names: two
question-bank categories (K and L), two roadmap focuses whose
``normalized_focus_key`` collide, two focus-origin wiki pages, and a theme
roster whose entries point at both.

Three states are captured, at both viewports:

  1. **before** — the lane open, the pair listed, the survivor picker
     seeded with ``focus-dupes``' own suggestion, a Combine button.
  2. **queued** — the interaction sequence: press Combine, land back on
     Review with the flash confirming the merge was enqueued through the
     single-writer job queue. Recorded to video and converted to a GIF.
  3. **after** — the enqueued job has actually run (this script only
     WATCHES ``state/roadmap.json`` until the worker drops the absorbed
     focus; it never performs the merge itself), the lane reads "No
     duplicate focuses", and Review's summary line drops to 0.

The whole path is real: the button POSTs to ``/actions/focus-merge``, the
handler enqueues a ``focus-merge`` job, ``jobs.enqueue``'s kick starts the
worker, and the worker runs the same ``lifehug focus-merge`` transaction
the CLI runs, under the single-writer lock.

No private vault is read or written: everything lives in the harness's
temporary directory.

Usage:
    python3 tests/walkthrough_focus_merge.py \
      --artifacts artifacts/walkthroughs/focus-merge
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

# macOS's default temp dir is reached through a symlink (/var -> /private/var),
# and `vault_paths.resolve_vault_root` rejects any vault path that traverses
# one — the viewer exits before it ever becomes ready, with the harness only
# able to report "viewer exited before it became ready". Pinning BOTH the
# module-level tempdir (what this process creates the vault under) and TMPDIR
# (what the viewer subprocess inherits) to the resolved, symlink-free path
# makes `make walkthrough-focus-merge` work without the caller having to know.
tempfile.tempdir = str(Path(tempfile.gettempdir()).resolve())
os.environ["TMPDIR"] = tempfile.tempdir

import walkthrough_lib  # noqa: E402

BANK_ADDITION = """

## Focuses

## K: Focus — Fear
- [x] K1: What scares you most? *(2026-02-01)*
- [ ] K2: When did you first feel afraid?

## L: Focus — The Fear
- [ ] L1: What is the fear you never name?
- [ ] L2: Who taught you to be afraid?
"""

ROADMAP = {
    "version": 1,
    "focuses": [
        {"id": "my-life", "label": "My Life", "type": "life_story", "primary": True,
         "tier": "extreme", "objective": "a faithful record of my life story",
         "deliverable": "book", "categories": ["A"], "target_depth": 50, "cap": 0.4,
         "phase": "active", "wiki_node": None, "neighborhoods": []},
        {"id": "fear", "label": "Fear", "type": "theme", "tier": "standard",
         "objective": "understand what fear has cost me", "deliverable": "essay",
         "categories": ["K"], "target_depth": 20, "cap": 0.3, "phase": "active",
         "wiki_node": "wiki/themes/fear.md", "neighborhoods": ["nbhd-fear"]},
        {"id": "the-fear", "label": "The Fear", "type": "theme", "tier": "basic",
         "objective": "the fear I never name", "deliverable": "essay",
         "categories": ["L"], "target_depth": 30, "cap": 0.3, "phase": "active",
         "wiki_node": "wiki/themes/the-fear.md", "neighborhoods": ["nbhd-the-fear"]},
    ],
}

THEME_ROSTER = {
    "version": 1, "type": "theme", "resolved_at": "2026-08-01T00:00:00Z", "source": "ai",
    "entities": [
        {"name": "Fear", "slug": "fear", "aliases": ["dread"], "qualifies": True,
         "maps_to_focus": "fear", "page_eligible": True},
        {"name": "The Fear", "slug": "the-fear", "aliases": [], "qualifies": True,
         "maps_to_focus": "the-fear", "page_eligible": True},
    ],
}


def _page(title: str) -> str:
    return f'---\ntitle: "{title}"\ntype: theme\norigin: focus\n---\n\n# {title}\n'


def seed_duplicate_pair(vault: Path) -> None:
    """Write the synthetic fear/Fear duplicate state into the harness's
    disposable vault. Every path here is inside the temp vault."""
    bank = vault / "question-bank.md"
    bank.write_text(bank.read_text(encoding="utf-8").rstrip() + BANK_ADDITION, encoding="utf-8")
    walkthrough_lib.write_json(vault / "state" / "roadmap.json", ROADMAP)
    walkthrough_lib.write_json(vault / "state" / "entity_rosters" / "theme.json", THEME_ROSTER)
    themes = vault / "wiki" / "themes"
    themes.mkdir(parents=True, exist_ok=True)
    (themes / "fear.md").write_text(_page("Fear"), encoding="utf-8")
    (themes / "the-fear.md").write_text(_page("The Fear"), encoding="utf-8")


def wait_for_the_merge(vault: Path, timeout: float = 60.0) -> None:
    """Wait for the ENQUEUED job to do the merge. This never performs the
    merge itself — it only watches state/roadmap.json until the worker
    `jobs.enqueue`'s kick started has dropped the absorbed focus."""
    roadmap_file = vault / "state" / "roadmap.json"
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        ids = [f.get("id") for f in json.loads(roadmap_file.read_text(encoding="utf-8"))["focuses"]]
        if "the-fear" not in ids:
            print(f"the queued focus-merge job completed; roadmap focuses are now {ids}")
            return
        time.sleep(0.5)
    raise RuntimeError("the enqueued focus-merge job never completed")


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
        seed_duplicate_pair(vault)

        review = f"{harness.base_url}/views/review"

        # --- state 1: the duplicate pair, before ------------------------
        page.goto(review, wait_until="networkidle")
        body = page.content()
        if "Duplicate focuses" not in body:
            raise RuntimeError("the Duplicate focuses lane did not render")
        if "1 duplicate focus " not in body:
            raise RuntimeError("Review's summary line did not count the duplicate pair")
        if 'action="/actions/focus-merge"' not in body:
            raise RuntimeError("the Combine form did not render")
        # The picker's live value, not the serialized attribute — the DOM
        # normalizes `selected` to `selected=""` in page.content().
        if page.eval_on_selector('select[name="survivor"]', "el => el.value") != "fear":
            raise RuntimeError("the survivor picker was not seeded with the suggested survivor")
        if page.eval_on_selector(
            'select[name="survivor"]', "el => [...el.options].map(o => o.value).join(',')"
        ) != "fear,the-fear":
            raise RuntimeError("the survivor picker did not offer both focuses")
        for expected in ("Fear", "The Fear", "Combine"):
            if expected not in body:
                raise RuntimeError(f"the lane is missing {expected!r}")
        page.screenshot(path=str(artifacts / "review-duplicates-before-1440x900.png"), full_page=True)

        # --- state 2: the Combine sequence (recorded) -------------------
        page.click('form[action="/actions/focus-merge"] button[type="submit"]')
        page.wait_for_load_state("networkidle")
        queued = page.content()
        if "queued combine" not in queued:
            raise RuntimeError("the Combine action did not report the merge as queued")
        if "the-fear → fear" not in queued:
            raise RuntimeError("the flash did not name the survivor and the absorbed focus")
        page.screenshot(path=str(artifacts / "review-combine-queued-1440x900.png"), full_page=True)

        # --- let the enqueued job actually run ---------------------------
        wait_for_the_merge(vault)

        # --- state 3: healed --------------------------------------------
        page.goto(review, wait_until="networkidle")
        after = page.content()
        if "No duplicate focuses" not in after:
            raise RuntimeError("the lane did not empty after the merge")
        if "0 duplicate focuses" not in after:
            raise RuntimeError("Review's summary line did not drop to zero")
        page.screenshot(path=str(artifacts / "review-duplicates-after-1440x900.png"), full_page=True)

        # --- phone viewport, all three states ---------------------------
        page.set_viewport_size({"width": 390, "height": 844})
        page.goto(review, wait_until="networkidle")
        page.screenshot(path=str(artifacts / "review-duplicates-after-390x844.png"), full_page=True)

        video = page.video
        page.close()  # closing the page finalizes the recording
        if video is None:
            raise RuntimeError("no video was recorded for the Combine sequence")
        webm = artifacts / "combine-sequence.webm"
        # save_as() blocks until the recording is fully written and copies
        # across filesystems; Path.replace() on video.path() can race the
        # muxer and hand ffmpeg a truncated file.
        video.save_as(str(webm))
        video.delete()
        walkthrough_lib.make_compact_gif(webm, artifacts / "combine-sequence.gif")

    # --- a second run, phone-first, for the before/queued phone stills ---
    with walkthrough_lib.WalkthroughHarness(viewport={"width": 390, "height": 844}) as harness:
        page = harness.page
        vault = harness.vault
        assert vault is not None
        seed_duplicate_pair(vault)
        review = f"{harness.base_url}/views/review"
        page.goto(review, wait_until="networkidle")
        page.screenshot(path=str(artifacts / "review-duplicates-before-390x844.png"), full_page=True)
        page.click('form[action="/actions/focus-merge"] button[type="submit"]')
        page.wait_for_load_state("networkidle")
        page.screenshot(path=str(artifacts / "review-combine-queued-390x844.png"), full_page=True)
        # Let this run's worker finish before the harness tears its vault
        # down — a worker still writing into the temp vault makes
        # TemporaryDirectory.cleanup() fail with "Directory not empty".
        wait_for_the_merge(vault)
        time.sleep(1.0)

    expected_stills = {
        "review-duplicates-before-1440x900.png",
        "review-duplicates-before-390x844.png",
        "review-combine-queued-1440x900.png",
        "review-combine-queued-390x844.png",
        "review-duplicates-after-1440x900.png",
        "review-duplicates-after-390x844.png",
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
    for motion in ("combine-sequence.gif", "combine-sequence.webm"):
        if not (artifacts / motion).exists():
            raise RuntimeError(f"missing motion evidence: {motion}")

    print(f"focus-merge walkthrough OK — {len(expected_stills)} stills + GIF + webm in {artifacts}")
    print(json.dumps(sorted(p.name for p in artifacts.iterdir()), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
