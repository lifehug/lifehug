#!/usr/bin/env python3
"""Lifehug — Update Manager

Checks for, applies, and rolls back framework updates from the upstream repo.
User data (answers/, outputs/, sources/manual/, question-bank.md, planner state) is never touched.

Usage:
    python3 system/update.py --check              # JSON: current, latest, update_available, changelog
    python3 system/update.py --check --quiet       # Exit code only (0=current, 1=update available)
    python3 system/update.py --apply               # Apply latest version
    python3 system/update.py --apply --version N   # Apply specific version
    python3 system/update.py --rollback            # Revert to previous version
"""

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

SYSTEM_DIR = Path(__file__).parent
REPO_DIR = SYSTEM_DIR.parent
VERSION_FILE = SYSTEM_DIR / "version.json"

# Files that are never overwritten by updates (user data)
PROTECTED_FILES = {
    "system/question-bank.md",
    "system/rotation.json",
    "system/coverage.json",
    "system/schedule.json",
    "config.yaml",
    "README.md",
    "answers/",
    "outputs/",
    "sources/manual/",
    "state/question_candidates.json",
    "state/question_queue.json",
    "state/planner_state.json",
    # Legacy paths (pre-v8) — still protected so historical content isn't clobbered
    "drafts/",
    "spotlights/",
}


def load_json(path):
    with open(path) as f:
        return json.load(f)


def save_json(path, data):
    with open(path, "w") as f:
        json.dump(data, f, indent=2)
        f.write("\n")


def run_git(*args, check=True):
    """Run a git command in the repo directory and return stdout."""
    result = subprocess.run(
        ["git", "-C", str(REPO_DIR)] + list(args),
        capture_output=True, text=True, check=check,
    )
    return result.stdout.strip()


def find_upstream_remote():
    """Find the remote pointing to the lifehug upstream repo.

    Prefers a remote named 'upstream', falls back to 'origin',
    then any remote whose URL contains 'lifehug/lifehug'.
    """
    try:
        output = run_git("remote", "-v")
    except subprocess.CalledProcessError:
        return None

    remotes = {}
    for line in output.splitlines():
        parts = line.split()
        if len(parts) >= 2:
            remotes[parts[0]] = parts[1]

    # Prefer 'upstream' only when it points to the framework repo.
    if "upstream" in remotes and "lifehug/lifehug" in remotes["upstream"]:
        return "upstream"

    # Check if any remote URL contains lifehug/lifehug
    for name, url in remotes.items():
        if "lifehug/lifehug" in url:
            return name

    # In the framework repo itself, origin is acceptable when it is the framework.
    if "origin" in remotes and "lifehug/lifehug" in remotes["origin"]:
        return "origin"

    return None


def get_local_version():
    """Read the local version number from version.json."""
    if not VERSION_FILE.exists():
        return 0
    data = load_json(VERSION_FILE)
    return data.get("version", 0)


def fetch_tags(remote):
    """Fetch tags from the remote."""
    run_git("fetch", remote, "--tags", "--quiet", check=False)


def get_available_versions():
    """Get all version tags (vN format) sorted by version number."""
    try:
        output = run_git("tag", "-l", "v*")
    except subprocess.CalledProcessError:
        return []

    versions = []
    for tag in output.splitlines():
        tag = tag.strip()
        match = re.match(r"^v(\d+)$", tag)
        if match:
            versions.append(int(match.group(1)))

    return sorted(versions)


def get_latest_version():
    """Get the highest version number from tags."""
    versions = get_available_versions()
    return versions[-1] if versions else 0


def get_tag_changelog(version):
    """Read the changelog from a tag's annotation."""
    tag = f"v{version}"
    try:
        output = run_git("tag", "-l", "--format=%(contents)", tag)
        return output.strip() if output.strip() else None
    except subprocess.CalledProcessError:
        return None


def get_framework_files_from_tag(version):
    """Read the framework_files list from a specific version's version.json."""
    tag = f"v{version}"
    try:
        content = run_git("show", f"{tag}:system/version.json")
        data = json.loads(content)
        return data.get("framework_files", [])
    except (subprocess.CalledProcessError, json.JSONDecodeError):
        return None


def check_dirty_framework_files(framework_files):
    """Check if any framework files have uncommitted changes."""
    dirty = []
    try:
        status = run_git("status", "--porcelain")
    except subprocess.CalledProcessError:
        return []

    changed_files = set()
    for line in status.splitlines():
        if len(line) > 3:
            filepath = line[3:].strip()
            # Handle renames: "R  old -> new"
            if " -> " in filepath:
                filepath = filepath.split(" -> ")[-1]
            changed_files.add(filepath)

    for f in framework_files:
        if f in changed_files:
            dirty.append(f)

    return dirty


def run_migrations(target_version, current_version):
    """Run any one-time migrations needed for the target version.

    v8: drafts/ and spotlights/ are replaced by outputs/. We don't delete the
    legacy directories (they're protected user data), but we do ensure outputs/
    exists with a .gitkeep so compose.py can write to it.

    v12: unprompted story ingest and planner state need sources/manual/ and
    state/ to exist, but all actual source and planner files remain user data.
    """
    if target_version >= 8 and current_version < 8:
        outputs = REPO_DIR / "outputs"
        outputs.mkdir(exist_ok=True)
        gitkeep = outputs / ".gitkeep"
        if not gitkeep.exists():
            gitkeep.write_text("")
        legacy = []
        for name in ("drafts", "spotlights"):
            d = REPO_DIR / name
            if d.exists():
                # Check if it has any content beyond .gitkeep
                contents = [p for p in d.iterdir() if p.name != ".gitkeep"]
                if contents:
                    legacy.append(name)
        if legacy:
            print(
                f"  Note: legacy dirs still present with content: {', '.join(legacy)}.\n"
                f"  These were the pre-v8 deliverables location. New outputs go to outputs/.\n"
                f"  Move existing content to outputs/ at your leisure — nothing will overwrite it.",
            )

    if target_version >= 12 and current_version < 12:
        for directory in (REPO_DIR / "sources" / "manual", REPO_DIR / "state"):
            directory.mkdir(parents=True, exist_ok=True)
            gitkeep = directory / ".gitkeep"
            if not gitkeep.exists():
                gitkeep.write_text("")

    if target_version >= 15 and current_version < 15:
        # v15: introduce the Focus/roadmap layer. This is a pure backfill —
        # the roadmap is *derived* from the existing question bank and answers.
        # No answers, no question-bank entries, and no outputs are touched.
        (REPO_DIR / "state").mkdir(parents=True, exist_ok=True)
        try:
            from roadmap import ROADMAP_FILE, rebuild_roadmap  # local import; same dir
            roadmap = rebuild_roadmap(write=True)
            print(
                f"  Derived roadmap of {len(roadmap['focuses'])} focuses → "
                f"state/{ROADMAP_FILE.name} (your answers and question bank were untouched)."
            )
        except Exception as exc:  # never let a migration break the update
            print(f"  Note: roadmap backfill deferred (run `python3 system/roadmap.py`): {exc}")


def apply_version(version):
    """Apply a specific version by extracting framework files from its tag."""
    tag = f"v{version}"

    # Get framework files list from the TARGET version
    framework_files = get_framework_files_from_tag(version)
    if framework_files is None:
        print(f"Error: Cannot read framework file list from {tag}", file=sys.stderr)
        return False

    current_version = get_local_version()

    # Check for uncommitted changes in framework files
    dirty = check_dirty_framework_files(framework_files)
    if dirty:
        print("Error: The following framework files have uncommitted changes:", file=sys.stderr)
        for f in dirty:
            print(f"  {f}", file=sys.stderr)
        print("\nCommit or stash your changes before updating.", file=sys.stderr)
        return False

    # Extract each framework file from the tag
    updated = []
    skipped = []
    for filepath in framework_files:
        # Special handling: question-bank.md gets saved as upstream copy.
        if filepath == "system/question-bank.md":
            try:
                content = run_git("show", f"{tag}:{filepath}")
                upstream_path = REPO_DIR / "system" / "question-bank-upstream.md"
                upstream_path.write_text(content)
                print(f"  Saved upstream question bank to system/question-bank-upstream.md")
            except subprocess.CalledProcessError:
                pass
            continue

        # Never touch protected files
        if filepath in PROTECTED_FILES or any(filepath.startswith(p) for p in PROTECTED_FILES):
            skipped.append(filepath)
            continue

        try:
            content = run_git("show", f"{tag}:{filepath}")
            target = REPO_DIR / filepath
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content)
            updated.append(filepath)
        except subprocess.CalledProcessError:
            print(f"  Warning: {filepath} not found in {tag}, skipping", file=sys.stderr)

    # Run any version-specific migrations
    run_migrations(version, current_version)

    if updated:
        # Stage and commit
        for f in updated:
            run_git("add", f)
        # Stage .gitkeep files if they were just created by migrations.
        for marker in ("outputs/.gitkeep", "sources/manual/.gitkeep", "state/.gitkeep", "state/roadmap.json"):
            if (REPO_DIR / marker).exists():
                run_git("add", marker, check=False)
        result = subprocess.run(
            ["git", "-C", str(REPO_DIR), "commit", "-m", f"Update Lifehug to v{version}"],
            capture_output=True, text=True,
        )
        if result.returncode != 0:
            # Check if it failed because there was nothing to commit
            if "nothing to commit" in result.stdout or "nothing to commit" in result.stderr:
                print("  Files already match target version — nothing to commit.")
            else:
                print(f"  Warning: git commit failed: {result.stderr.strip()}", file=sys.stderr)
    else:
        print("  All framework files already up to date.")

    return True


def cmd_check(args):
    """Check for available updates."""
    remote = find_upstream_remote()
    if remote:
        fetch_tags(remote)
    else:
        if not args.quiet:
            print(
                "Warning: No upstream remote found. Tags will be checked locally only.\n"
                "To receive updates, add the upstream remote:\n"
                "  git remote add upstream https://github.com/lifehug/lifehug.git",
                file=sys.stderr,
            )

    current = get_local_version()
    latest = get_latest_version()
    update_available = latest > current

    if args.quiet:
        sys.exit(1 if update_available else 0)

    changelog = None
    if update_available:
        changelog = get_tag_changelog(latest)

    result = {
        "current": current,
        "latest": latest,
        "update_available": update_available,
        "changelog": changelog,
    }
    print(json.dumps(result, indent=2))


def cmd_apply(args):
    """Apply an update."""
    remote = find_upstream_remote()
    if remote:
        fetch_tags(remote)
    else:
        print(
            "Warning: No upstream remote found. Using local tags only.\n"
            "To receive updates, add the upstream remote:\n"
            "  git remote add upstream https://github.com/lifehug/lifehug.git",
            file=sys.stderr,
        )

    current = get_local_version()

    if args.version:
        target = args.version
    else:
        target = get_latest_version()

    if target <= 0:
        print("No versions available to apply.")
        return

    if target == current:
        print(f"Already at v{current}. Nothing to update.")
        return

    if target < current:
        print(f"Warning: Downgrading from v{current} to v{target}.")

    print(f"Updating Lifehug from v{current} to v{target}...")

    if apply_version(target):
        print(f"\nLifehug updated to v{target}.")
        changelog = get_tag_changelog(target)
        if changelog:
            print(f"\nChangelog:\n{changelog}")
    else:
        print("\nUpdate failed.", file=sys.stderr)
        sys.exit(1)


def cmd_rollback(args):
    """Rollback to the previous version."""
    current = get_local_version()
    if current <= 1:
        print("Cannot rollback: already at v1 (initial version).")
        return

    target = current - 1
    print(f"Rolling back from v{current} to v{target}...")

    if apply_version(target):
        print(f"\nRolled back to v{target}.")
    else:
        print("\nRollback failed.", file=sys.stderr)
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(description="Lifehug update manager")
    parser.add_argument("--check", action="store_true", help="Check for updates")
    parser.add_argument("--quiet", action="store_true", help="Exit code only (with --check)")
    parser.add_argument("--apply", action="store_true", help="Apply latest update")
    parser.add_argument("--version", type=int, metavar="N", help="Target version (with --apply)")
    parser.add_argument("--rollback", action="store_true", help="Rollback to previous version")
    args = parser.parse_args()

    if args.check:
        cmd_check(args)
    elif args.apply:
        cmd_apply(args)
    elif args.rollback:
        cmd_rollback(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
