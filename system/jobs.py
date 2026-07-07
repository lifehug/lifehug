#!/usr/bin/env python3
"""Detached job runner for the viewer's long-running write actions (v101).

The local viewer must answer HTTP requests fast, while some actions take
30 s–minutes (wiki compile, AI artifact revision, focus approval with starter
question generation). ``start_job`` records ``state/jobs/<id>.json`` and
spawns a detached runner process (``jobs.py run <id>``) that executes the
recorded argv and finalizes the status file — the runner owns the record, so
a viewer restart never orphans a job. The viewer polls ``/jobs/<id>.json``.

Stdlib only, matching the file_answer_bg.sh detached-work precedent.
"""

from __future__ import annotations

import re
import subprocess
import sys
import time
import uuid
from pathlib import Path

from lifehug_core import REPO_DIR, STATE_DIR, now_utc, read_json, write_json

JOBS_DIR = STATE_DIR / "jobs"
GC_DAYS = 7
TAIL_CHARS = 2000
_ID_RE = re.compile(r"^[0-9a-f]{12}$")


def _gc() -> None:
    cutoff = time.time() - GC_DAYS * 86400
    for p in JOBS_DIR.glob("*"):
        try:
            if p.stat().st_mtime < cutoff:
                p.unlink()
        except OSError:
            pass


def start_job(kind: str, argv: list[str], stdin_text: str | None = None) -> dict:
    """Record the job and spawn the detached runner. Returns the job record."""
    JOBS_DIR.mkdir(parents=True, exist_ok=True)
    _gc()
    job_id = uuid.uuid4().hex[:12]
    record = {
        "id": job_id,
        "kind": kind,
        "status": "running",
        "started_at": now_utc(),
        "argv": argv,
    }
    if stdin_text is not None:
        stdin_file = JOBS_DIR / f"{job_id}.stdin"
        stdin_file.write_text(stdin_text, encoding="utf-8")
        record["stdin_file"] = stdin_file.name
    write_json(JOBS_DIR / f"{job_id}.json", record)
    log = (JOBS_DIR / f"{job_id}.log").open("ab")
    # The runner is a separate process — hand it the jobs dir explicitly so a
    # monkeypatched JOBS_DIR (tests) or future relocation carries over.
    subprocess.Popen(  # noqa: S603 — argv is built by the viewer's own handlers
        [sys.executable, str(Path(__file__).resolve()), "run", job_id,
         "--dir", str(JOBS_DIR)],
        stdout=log, stderr=log, cwd=REPO_DIR, start_new_session=True)
    return record


def load_job(job_id: str) -> dict | None:
    """Fetch a job record by id (id format enforced — this feeds a URL)."""
    if not _ID_RE.match(job_id or ""):
        return None
    return read_json(JOBS_DIR / f"{job_id}.json", default=None)


def run_job(job_id: str) -> int:
    path = JOBS_DIR / f"{job_id}.json"
    record = read_json(path, default=None)
    if not record:
        print(f"unknown job {job_id}", file=sys.stderr)
        return 1
    stdin_data = None
    stdin_name = record.get("stdin_file")
    if stdin_name:
        try:
            stdin_data = (JOBS_DIR / stdin_name).read_text(encoding="utf-8")
        except OSError:
            stdin_data = None
    try:
        proc = subprocess.run(  # noqa: S603
            record["argv"], input=stdin_data, capture_output=True,
            text=True, cwd=REPO_DIR)
        output = (proc.stdout or "") + (("\n" + proc.stderr) if proc.stderr else "")
        record.update({
            "status": "done" if proc.returncode == 0 else "failed",
            "rc": proc.returncode,
            "finished_at": now_utc(),
            "tail": output[-TAIL_CHARS:].strip(),
        })
        print(output)
    except Exception as exc:  # noqa: BLE001 — the record must always finalize
        record.update({"status": "failed", "rc": -1,
                       "finished_at": now_utc(), "tail": str(exc)})
    write_json(path, record)
    if stdin_name:
        (JOBS_DIR / stdin_name).unlink(missing_ok=True)
    return 0 if record["status"] == "done" else 1


def main(argv: list[str] | None = None) -> int:
    global JOBS_DIR
    argv = argv if argv is not None else sys.argv[1:]
    if len(argv) >= 2 and argv[0] == "run":
        if len(argv) == 4 and argv[2] == "--dir":
            JOBS_DIR = Path(argv[3])
        return run_job(argv[1])
    print("usage: jobs.py run <job-id> [--dir JOBS_DIR]", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
