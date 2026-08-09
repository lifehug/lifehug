#!/usr/bin/env python3
"""Fail a PR that does not bump system/version.json's version field.

Encodes AGENTS.md's existing rule ("every PR bumps system/version.json ...
No PR ships without a bump") as a CI gate instead of an honor system. No
exemption: doc-only and CI-only PRs bump too (owner decision, lifehug#85 —
this very PR bumps to v132 to prove the rule against its own introduction).

Usage:
    python3 scripts/ci/check_version_bump.py --base <base-sha> --head <head-sha>

Both SHAs must already be present in the local clone's history (CI checks
out with fetch-depth: 0 for this reason — no network fetch is performed
here). Exit code 0 if head's version is strictly greater than base's; exit
code 1 otherwise, with both versions printed.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys

VERSION_PATH = "system/version.json"


def _version_at(sha: str) -> int:
    result = subprocess.run(
        ["git", "show", f"{sha}:{VERSION_PATH}"],
        capture_output=True,
        text=True,
        check=True,
    )
    data = json.loads(result.stdout)
    version = data.get("version")
    if not isinstance(version, int):
        raise ValueError(f"{VERSION_PATH} at {sha} has no integer 'version' field")
    return version


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", required=True, help="base commit SHA (PR target branch tip)")
    parser.add_argument("--head", required=True, help="head commit SHA (PR branch tip)")
    args = parser.parse_args()

    try:
        base_version = _version_at(args.base)
        head_version = _version_at(args.head)
    except (subprocess.CalledProcessError, ValueError, json.JSONDecodeError) as exc:
        print(f"check_version_bump: could not resolve version: {exc}", file=sys.stderr)
        return 1

    if head_version <= base_version:
        print(
            f"check_version_bump: system/version.json's version did not increase "
            f"(base={base_version}, head={head_version}). Every PR bumps "
            "system/version.json (AGENTS.md Definition of Done) — no exemption, "
            "including doc/CI-only PRs.",
            file=sys.stderr,
        )
        return 1

    print(f"check_version_bump: version {base_version} -> {head_version}, OK.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
