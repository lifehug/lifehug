#!/usr/bin/env python3
"""Private worker child: execute an in-memory Lifehug CLI envelope.

This entrypoint is not a public job API. The worker sends validated arguments
and stdin through this process's stdin so private text never appears in the OS
process list. A live writer token is mandatory.
"""

from __future__ import annotations

import io
import json
import os
import runpy
import sys
from pathlib import Path

from vault_paths import resolve_framework_system_dir, resolve_vault_root


def main() -> int:
    try:
        framework_system = resolve_framework_system_dir()
        selected = os.environ.get("LIFEHUG_VAULT_ROOT")
        vault = resolve_vault_root(
            Path(selected) if selected else None,
            framework_system_dir=framework_system,
            bind_process=True,
        )
        import jobs  # noqa: PLC0415

        jobs.configure(vault)
    except (RuntimeError, ValueError):
        return 77
    os.environ["LIFEHUG_VAULT_ROOT"] = str(vault)
    token = os.environ.get("LIFEHUG_JOB_RUNNER_TOKEN")
    if not jobs.writer_token_is_live(token, vault_root=vault):
        return 77
    try:
        envelope = json.load(sys.stdin)
    except (json.JSONDecodeError, UnicodeError):
        return 2
    arguments = envelope.get("arguments") if isinstance(envelope, dict) else None
    stdin_text = envelope.get("stdin_text") if isinstance(envelope, dict) else None
    if not isinstance(arguments, list) or not all(isinstance(item, str) for item in arguments):
        return 2
    if stdin_text is not None and not isinstance(stdin_text, str):
        return 2

    lifehug_path = jobs.FRAMEWORK_SYSTEM_DIR / "lifehug.py"
    os.environ["LIFEHUG_JOB_IN_PROCESS"] = "1"
    sys.argv = [str(lifehug_path), *arguments]
    sys.stdin = io.StringIO(stdin_text or "")
    try:
        runpy.run_path(str(lifehug_path), run_name="__main__")
    except SystemExit as exc:
        return int(exc.code or 0) if isinstance(exc.code, int | type(None)) else 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
