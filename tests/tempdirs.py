"""Temp-dir helpers for tests that must avoid macOS /var symlink paths.

vault_paths' no-follow authority rejects any path that traverses a symlink,
and the default temp dir on macOS does (/var -> /private/var). Fixtures used
to dodge that by creating temp dirs in the worktree's parent directory, which
littered the user's workspace whenever a run was killed before cleanup.
Instead, create them under the fully RESOLVED system temp dir: it has no
symlink components (so guarded code accepts it), and anything a killed run
leaks lands in the OS temp area, never in the workspace.
"""

from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

# /var/folders/... -> /private/var/folders/... on macOS; a no-op elsewhere.
SYMLINK_FREE_TMP_BASE = Path(tempfile.gettempdir()).resolve()


def symlink_free_tmp(
    test_case: unittest.TestCase,
    *,
    prefix: str | None = None,
) -> Path:
    """Create a symlink-free temp dir and register unconditional cleanup."""
    options: dict[str, object] = {"dir": SYMLINK_FREE_TMP_BASE}
    if prefix is not None:
        options["prefix"] = prefix
    tmp = Path(tempfile.mkdtemp(**options))
    test_case.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
    return tmp
