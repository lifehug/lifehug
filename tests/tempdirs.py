"""Temp-dir helpers for tests that must avoid macOS /var symlink paths."""

from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path


def root_parent_tmp(
    test_case: unittest.TestCase,
    root: Path,
    *,
    prefix: str | None = None,
) -> Path:
    """Create a ROOT.parent temp dir and register unconditional cleanup."""
    options: dict[str, object] = {"dir": root.parent}
    if prefix is not None:
        options["prefix"] = prefix
    tmp = Path(tempfile.mkdtemp(**options))
    test_case.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
    return tmp
