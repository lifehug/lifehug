"""Shared scaffolding for walkthrough evidence scripts.

Extracted from `tests/v119_job_pill_evidence.py` (lifehug#85 / v132) so each
PR-specific walkthrough (`tests/walkthrough_<slug>.py`) reuses the same
disposable-vault -> live-viewer -> Playwright lifecycle instead of
reinventing it. No private vault or live credential is ever read or written
by anything in this module.

This module requires the locally installed Playwright browser. Like the
script it was extracted from, it is evidence-harness code, not part of the
`python3 -m unittest discover` suite — nothing here matches the `test_*.py`
glob, and nothing here should be imported by files that do.

See `docs/pr-specs/TEMPLATE.md`'s Launch-and-verify section and the root
`Makefile`'s `walkthrough-%` pattern rule for how a walkthrough script built
on this harness gets invoked.
"""

from __future__ import annotations

import contextlib
import json
import os
import shutil
import socket
import struct
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SYSTEM = ROOT / "system"


def free_port() -> int:
    """Return a free loopback TCP port picked by the OS."""
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def synthetic_vault(root: Path, *, question_candidates: dict[str, Any] | None = None) -> Path:
    """Build a disposable vault under `root` with no private data.

    Copies the framework's own question bank / rotation / coverage fixtures
    (never a user vault — see the platform's boundary rule) and creates the
    standard vault directory layout. Pass `question_candidates` when the
    walkthrough needs a specific candidate queued (e.g. to drive a Defer or
    Promote action in the viewer); omit it for walkthroughs that don't touch
    the candidates lane.
    """
    vault = root / "synthetic-vault"
    (vault / "state").mkdir(parents=True)
    shutil.copy2(SYSTEM / "question-bank.md", vault / "question-bank.md")
    shutil.copy2(SYSTEM / "rotation.json", vault / "state" / "rotation.json")
    shutil.copy2(SYSTEM / "coverage.json", vault / "state" / "coverage.json")
    for directory in ("answers", "outputs", "sources/manual", "sources/corrections", "wiki"):
        (vault / directory).mkdir(parents=True, exist_ok=True)
    if question_candidates is not None:
        write_json(vault / "state" / "question_candidates.json", question_candidates)
    return vault


def wait_for_server(url: str, process: subprocess.Popen[str]) -> None:
    from urllib.request import urlopen

    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError("viewer exited before it became ready")
        try:
            with urlopen(url, timeout=1) as response:  # noqa: S310 -- fixed loopback URL
                if response.status == 200:
                    return
        except OSError:
            time.sleep(0.1)
    raise RuntimeError("viewer did not become ready")


def png_dimensions(path: Path) -> tuple[int, int]:
    header = path.read_bytes()[:24]
    if len(header) != 24 or header[:8] != b"\x89PNG\r\n\x1a\n" or header[12:16] != b"IHDR":
        raise RuntimeError(f"still is not a valid PNG: {path}")
    return struct.unpack(">II", header[16:24])


def make_compact_gif(webm: Path, gif: Path) -> None:
    if shutil.which("ffmpeg") is None:
        raise RuntimeError("ffmpeg is required to create the compact evidence GIF")
    subprocess.run(
        [
            "ffmpeg", "-y", "-loglevel", "error", "-i", str(webm),
            "-vf",
            (
                "fps=10,scale=640:-1:flags=lanczos,split[s0][s1];"
                "[s0]palettegen=max_colors=128[p];"
                "[s1][p]paletteuse=dither=bayer:bayer_scale=3"
            ),
            "-loop", "0", str(gif),
        ],
        check=True,
    )


class WalkthroughHarness:
    """Owns the disposable-vault -> live viewer -> Playwright browser lifecycle.

    Usage::

        with WalkthroughHarness(record_video=True) as harness:
            harness.page.goto(f"{harness.base_url}/views/review", wait_until="networkidle")
            ...

    Teardown (browser/context close, server terminate, temp-dir cleanup)
    always runs via `close()`, even on error — the same `finally` discipline
    proven in `tests/v119_job_pill_evidence.py` before this extraction.

    `LIFEHUG_WALKTHROUGH_PORT` is an escape hatch to pin a fixed port (e.g.
    to point browser devtools at a specific run while debugging); it is not
    required for concurrency — each run already self-probes a free port via
    `free_port()`, unlike the platform's fixed dev-port walkthrough pairs.
    """

    def __init__(
        self,
        *,
        question_candidates: dict[str, Any] | None = None,
        viewport: dict[str, int] | None = None,
        record_video: bool = False,
    ) -> None:
        self._question_candidates = question_candidates
        self._viewport = viewport or {"width": 1440, "height": 900}
        self._record_video = record_video
        self._tmp: tempfile.TemporaryDirectory[str] | None = None
        self.vault: Path | None = None
        self.port: int | None = None
        self.base_url: str = ""
        self.env: dict[str, str] = {}
        self._server: subprocess.Popen[str] | None = None
        self._playwright: Any = None
        self.browser: Any = None
        self.context: Any = None
        self.page: Any = None

    def __enter__(self) -> "WalkthroughHarness":
        from playwright.sync_api import sync_playwright

        self._tmp = tempfile.TemporaryDirectory(prefix="lifehug-walkthrough-")
        tmp = Path(self._tmp.name)
        self.vault = synthetic_vault(tmp, question_candidates=self._question_candidates)
        self.port = int(os.environ.get("LIFEHUG_WALKTHROUGH_PORT") or free_port())
        self.env = os.environ | {
            "LIFEHUG_VAULT_ROOT": str(self.vault),
            "LIFEHUG_FRAMEWORK_SYSTEM_DIR": str(SYSTEM),
            "PYTHONPATH": str(SYSTEM),
        }
        self.base_url = f"http://127.0.0.1:{self.port}"
        self._server = subprocess.Popen(
            [sys.executable, str(SYSTEM / "serve_wiki.py"), "--port", str(self.port)],
            cwd=ROOT,
            env=self.env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        try:
            wait_for_server(f"{self.base_url}/views/review", self._server)
            self._playwright = sync_playwright().start()
            self.browser = self._playwright.chromium.launch()
            context_kwargs: dict[str, Any] = {"viewport": self._viewport}
            if self._record_video:
                video_dir = tmp / "video"
                video_dir.mkdir(exist_ok=True)
                context_kwargs["record_video_dir"] = str(video_dir)
                context_kwargs["record_video_size"] = self._viewport
            self.context = self.browser.new_context(**context_kwargs)
            self.page = self.context.new_page()
        except Exception:
            self.close()
            raise
        return self

    def close(self) -> None:
        if self.context is not None:
            with contextlib.suppress(Exception):
                self.context.close()
            self.context = None
        if self.browser is not None:
            with contextlib.suppress(Exception):
                self.browser.close()
            self.browser = None
        if self._playwright is not None:
            with contextlib.suppress(Exception):
                self._playwright.stop()
            self._playwright = None
        if self._server is not None:
            self._server.terminate()
            with contextlib.suppress(subprocess.TimeoutExpired):
                self._server.wait(timeout=5)
            if self._server.poll() is None:
                self._server.kill()
            self._server = None
        if self._tmp is not None:
            self._tmp.cleanup()
            self._tmp = None

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        self.close()
