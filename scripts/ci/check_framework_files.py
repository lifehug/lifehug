#!/usr/bin/env python3
"""Verify every path in system/version.json's framework_files exists on disk.

`system/update.py` ships every path listed in `framework_files` to existing
installs on upgrade — a path missing from disk but present in the manifest
would fail silently at apply time on the upgrader's machine, not at author
time here. Nothing has verified this manifest before (lifehug#85): this
script closes that gap as a required CI check.

Usage:
    python3 scripts/ci/check_framework_files.py

Exit code 0 if every entry resolves to a real file relative to the repo
root; exit code 1, with every missing path listed, otherwise.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
VERSION_JSON = ROOT / "system" / "version.json"


def check_framework_files(root: Path = ROOT, version_json: Path = VERSION_JSON) -> list[str]:
    """Return the list of framework_files entries missing from disk."""
    data = json.loads(version_json.read_text(encoding="utf-8"))
    entries = data.get("framework_files")
    if not isinstance(entries, list) or not entries:
        raise ValueError(f"{version_json} has no non-empty 'framework_files' list")
    missing = []
    for entry in entries:
        if not (root / entry).exists():
            missing.append(entry)
    return missing


def main() -> int:
    try:
        missing = check_framework_files()
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"check_framework_files: could not read manifest: {exc}", file=sys.stderr)
        return 1
    if missing:
        print(f"check_framework_files: {len(missing)} framework_files entries do not exist on disk:", file=sys.stderr)
        for entry in missing:
            print(f"  - {entry}", file=sys.stderr)
        print(
            "system/update.py ships these paths to every existing install on upgrade; "
            "fix the manifest (remove stale entries) or restore the missing files.",
            file=sys.stderr,
        )
        return 1
    print(f"check_framework_files: all {len(json.loads(VERSION_JSON.read_text())['framework_files'])} entries exist.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
