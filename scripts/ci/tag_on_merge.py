#!/usr/bin/env python3
"""Tag system/version.json's version on push to main, and check for drift.

Automates the step that lapsed silently for ten releases (v118-v128, see
issue #84): a human noticing a red "needs a tag" check and running the tag
command by hand. This script removes that human step from the loop by
tagging automatically on every push to main; `.github/workflows/tag-on-
merge.yml` runs it with `contents: write` permission.

Two modes:

  python3 scripts/ci/tag_on_merge.py
      Default. Reads system/version.json, computes `v<version>`. If that
      tag does not already exist, creates it as an ANNOTATED tag (message =
      the changelog field) and pushes it to origin. Idempotent: a re-run
      after a no-op push does nothing. Safe against double-push races: a
      push failure because the tag already exists on the remote is treated
      as success, not error.

  python3 scripts/ci/tag_on_merge.py --check-drift
      Safety net for the tagging workflow's own failure mode (bad token
      permissions, API hiccup, disabled workflow). Fetches tags from origin
      and compares the highest numeric v<N> tag to system/version.json's
      version. A push to main and the tag-on-merge workflow's own tagging
      race on the same event, so this polls (fetching tags again each time)
      for up to --wait-seconds before failing loudly — that is the "race
      window" the design calls for, not an immediate false-positive.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
VERSION_JSON = ROOT / "system" / "version.json"
TAG_RE = re.compile(r"^v(\d+)$")


def _load_version_and_changelog() -> tuple[int, str]:
    data = json.loads(VERSION_JSON.read_text(encoding="utf-8"))
    version = data.get("version")
    changelog = data.get("changelog")
    if not isinstance(version, int):
        raise ValueError(f"{VERSION_JSON} has no integer 'version' field")
    if not isinstance(changelog, str) or not changelog.strip():
        raise ValueError(f"{VERSION_JSON} has no non-empty 'changelog' field")
    return version, changelog


def _run(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, capture_output=True, text=True)


def _tag_exists_locally(tag: str) -> bool:
    result = _run(["git", "rev-parse", "-q", "--verify", f"refs/tags/{tag}"])
    return result.returncode == 0


def _highest_remote_tag_version(remote: str = "origin") -> int | None:
    fetch = _run(["git", "fetch", remote, "--tags", "--force"])
    if fetch.returncode != 0:
        raise RuntimeError(f"git fetch --tags failed: {fetch.stderr.strip()}")
    tags = _run(["git", "tag", "-l"])
    versions = []
    for line in tags.stdout.splitlines():
        match = TAG_RE.match(line.strip())
        if match:
            versions.append(int(match.group(1)))
    return max(versions) if versions else None


def tag_on_merge(remote: str = "origin") -> int:
    version, changelog = _load_version_and_changelog()
    tag = f"v{version}"

    if _tag_exists_locally(tag):
        print(f"tag_on_merge: {tag} already exists locally, nothing to do.")
        return 0

    create = _run(["git", "tag", "-a", tag, "-m", changelog])
    if create.returncode != 0:
        # Another concurrent run created it between our check and our create.
        if _tag_exists_locally(tag):
            print(f"tag_on_merge: {tag} was created concurrently, nothing to do.")
            return 0
        print(f"tag_on_merge: failed to create tag {tag}: {create.stderr.strip()}", file=sys.stderr)
        return 1

    push = _run(["git", "push", remote, tag])
    if push.returncode != 0:
        stderr = push.stderr.lower()
        if "already exists" in stderr:
            print(f"tag_on_merge: {tag} already exists on {remote} (race), treating as success.")
            return 0
        print(f"tag_on_merge: failed to push tag {tag}: {push.stderr.strip()}", file=sys.stderr)
        return 1

    print(f"tag_on_merge: created and pushed annotated tag {tag}.")
    return 0


def check_drift(remote: str = "origin", wait_seconds: int = 90, poll_seconds: int = 10) -> int:
    version, _changelog = _load_version_and_changelog()
    deadline = time.monotonic() + wait_seconds
    last_seen: int | None = None
    while True:
        try:
            last_seen = _highest_remote_tag_version(remote)
        except RuntimeError as exc:
            print(f"check_drift: {exc}", file=sys.stderr)
            return 1
        if last_seen == version:
            print(f"check_drift: highest tag v{last_seen} matches system/version.json's version {version}. OK.")
            return 0
        if time.monotonic() >= deadline:
            break
        time.sleep(poll_seconds)

    print(
        f"check_drift: highest tag on {remote} is "
        f"{'v' + str(last_seen) if last_seen is not None else '(none)'}, "
        f"but system/version.json's version is {version}, after waiting "
        f"{wait_seconds}s for tag-on-merge.yml to catch up. The tagging "
        "workflow likely failed (permissions, API hiccup) — see "
        ".github/workflows/tag-on-merge.yml and issue #84.",
        file=sys.stderr,
    )
    return 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--check-drift", action="store_true", help="run the drift-check safety net instead of tagging")
    parser.add_argument("--remote", default="origin")
    parser.add_argument("--wait-seconds", type=int, default=90, help="check-drift only: race-window budget")
    parser.add_argument("--poll-seconds", type=int, default=10, help="check-drift only: retry interval")
    args = parser.parse_args()

    try:
        if args.check_drift:
            return check_drift(args.remote, args.wait_seconds, args.poll_seconds)
        return tag_on_merge(args.remote)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"tag_on_merge: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
