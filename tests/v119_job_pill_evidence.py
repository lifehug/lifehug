#!/usr/bin/env python3
"""Capture v119 job-pill evidence against a disposable synthetic vault.

This is an evidence harness, not part of the unit-test suite: it requires the
locally installed Playwright browser.  It starts the real owner-only viewer,
clicks its real Candidate action, then advances that durable synthetic job
record through every user-visible state.  No private vault or live credential
is read or written.

Since v132 (lifehug#85), the disposable-vault / live-viewer / Playwright
scaffolding lives in `tests/walkthrough_lib.py` — this script keeps only what
is actually specific to the job-pill evidence: the STATE_SPECS sequence, the
writer-lease holder subprocess, and the pill-text/overflow assertions. Its
own assertions (screenshot count, exact PNG dimensions) are the regression
test that the extraction didn't change behavior.

Usage:
    python3 tests/v119_job_pill_evidence.py \
      --artifacts artifacts/walkthroughs/pr-71-jobs
"""

from __future__ import annotations

import argparse
import contextlib
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parents[1]
SYSTEM = ROOT / "system"
TESTS = ROOT / "tests"
sys.path.insert(0, str(SYSTEM))
sys.path.insert(0, str(TESTS))

import jobs  # noqa: E402

import walkthrough_lib  # noqa: E402


STATE_SPECS = (
    ("queued", {"state": "queued", "can_retry": False}),
    ("running", {"state": "running", "can_retry": False}),
    ("succeeded", {
        "state": "succeeded", "exit_code": 0, "can_retry": False,
        "finished_at": "2026-08-06T00:00:00Z", "payload_retained": False,
    }),
    ("failed", {
        "state": "failed", "exit_code": 1, "failure_code": "command_failed",
        "can_retry": False, "finished_at": "2026-08-06T00:00:00Z",
        "payload_retained": True,
    }),
    ("safely-retryable", {
        "state": "safely-retryable", "failure_code": "interrupted_before_receipt",
        "can_retry": True, "finished_at": "2026-08-06T00:00:00Z",
        "payload_retained": True,
    }),
)

QUESTION_CANDIDATES = {
    "version": 1,
    "candidates": [{
        "id": "synthetic-v119-candidate",
        "text": "What ordinary moment from a recent week deserves to be remembered?",
        "status": "candidate",
        "priority": 0.87,
        "story_function": "scene",
        "source_path": "sources/manual/synthetic-v119.md",
        "target_category": "A",
    }],
}


def _set_state(record: dict, values: dict) -> dict:
    updated = dict(record)
    updated.update(values)
    updated["updated_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    jobs._write_json(jobs._record_path(updated["id"]), updated)
    return updated


def _capture_state(page, url: str, label: str, artifacts: Path, width: int, height: int) -> None:
    page.set_viewport_size({"width": width, "height": height})
    page.goto(url, wait_until="networkidle")
    page.wait_for_timeout(3200)  # the real viewer poll interval is 3 seconds
    expected = {
        "queued": "queued…",
        "running": "running…",
        "succeeded": "done ✓",
        "failed": "failed ✗",
        "safely-retryable": "ready to retry…",
    }[label]
    pill = page.locator(".jobpill")
    if pill.text_content() != expected:
        raise RuntimeError(f"{label} pill rendered {pill.text_content()!r}, expected {expected!r}")
    if width == 390:
        overflow = page.evaluate(
            """() => ({
                page: document.documentElement.scrollWidth - document.documentElement.clientWidth,
                main: document.querySelector('main').scrollWidth - document.querySelector('main').clientWidth,
            })"""
        )
        if overflow["page"] != 0 or overflow["main"] <= 0:
            raise RuntimeError(f"mobile table overflow is not safely contained: {overflow}")
    page.screenshot(path=str(artifacts / f"job-pill-{label}-{width}x{height}.png"), full_page=False)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifacts", type=Path, required=True)
    args = parser.parse_args()
    artifacts = args.artifacts.resolve()
    artifacts.mkdir(parents=True, exist_ok=True)

    with walkthrough_lib.WalkthroughHarness(
        question_candidates=QUESTION_CANDIDATES,
        viewport={"width": 1440, "height": 900},
        record_video=True,
    ) as harness:
        jobs.configure(harness.vault)
        holder = subprocess.Popen(
            [
                sys.executable,
                "-c",
                (
                    "import sys,time; from pathlib import Path; "
                    f"sys.path.insert(0,{str(SYSTEM)!r}); import jobs; "
                    f"jobs.configure(Path({str(harness.vault)!r})); "
                    "\nwith jobs._WriterLease(wait_seconds=1): time.sleep(90)"
                ),
            ],
            env=harness.env,
        )
        try:
            writer_owner = harness.vault / "state" / "jobs" / ".writer-owner.json"
            deadline = time.monotonic() + 5
            while not writer_owner.exists():
                if time.monotonic() >= deadline:
                    raise RuntimeError("evidence writer lease did not start")
                time.sleep(0.05)

            page = harness.page
            page.goto(f"{harness.base_url}/views/review", wait_until="networkidle")
            # v128: the candidates lane is a <details>; it opens
            # automatically when actionable, but force it so the
            # Defer button is visible regardless of fixture state.
            page.evaluate("document.querySelectorAll('details.fnd-focus').forEach(d => d.open = true)")
            page.get_by_role("button", name="Defer").click()
            page.wait_for_url("**/views/review?**")
            query = parse_qs(urlparse(page.url).query)
            job_id = (query.get("job") or [""])[0]
            record = jobs.load_job(job_id)
            if record is None:
                raise RuntimeError("real viewer action did not create a durable job")
            action_url = page.url
            # The lease holds the actual worker behind the clicked action,
            # keeping its initial queued state visible. The remaining
            # durable states are then deterministic synthetic recoveries.
            current = record
            for label, values in STATE_SPECS:
                current = _set_state(current, values)
                _capture_state(page, action_url, label, artifacts, 1440, 900)
                _capture_state(page, action_url, label, artifacts, 390, 844)
            page.set_viewport_size({"width": 1440, "height": 900})
            page.goto(action_url, wait_until="networkidle")
            for label, values in STATE_SPECS:
                current = _set_state(current, values)
                page.reload(wait_until="networkidle")
                page.wait_for_timeout(3200)
            video = page.video
            harness.context.close()
            harness.context = None
            if video is None:
                raise RuntimeError("Playwright did not create walkthrough video")
            source_video = Path(video.path())
            if not source_video.is_file():
                raise RuntimeError("Playwright did not finalize walkthrough video")
            shutil.copy2(source_video, artifacts / "job-pill-action-sequence.webm")
        finally:
            holder.terminate()
            with contextlib.suppress(subprocess.TimeoutExpired):
                holder.wait(timeout=5)
            if holder.poll() is None:
                holder.kill()

    expected_count = len(STATE_SPECS) * 2
    screenshots = list(artifacts.glob("job-pill-*.png"))
    if len(screenshots) != expected_count:
        raise RuntimeError(f"expected {expected_count} screenshots, found {len(screenshots)}")
    expected_dimensions = {
        artifacts / f"job-pill-{label}-{width}x{height}.png": (width, height)
        for label, _values in STATE_SPECS
        for width, height in ((1440, 900), (390, 844))
    }
    for screenshot in screenshots:
        expected = expected_dimensions.get(screenshot)
        if expected is None:
            raise RuntimeError(f"unexpected still filename: {screenshot.name}")
        actual = walkthrough_lib.png_dimensions(screenshot)
        if actual != expected:
            raise RuntimeError(
                f"{screenshot.name} is {actual[0]}x{actual[1]}, expected {expected[0]}x{expected[1]}"
            )
    walkthrough_lib.make_compact_gif(
        artifacts / "job-pill-action-sequence.webm",
        artifacts / "job-pill-action-sequence.gif",
    )
    print(f"captured {expected_count} exact-size screenshots, WebM, and compact GIF in {artifacts}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
