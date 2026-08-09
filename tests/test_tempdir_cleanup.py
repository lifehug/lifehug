"""Regression guard for workspace-parent temp dirs in tests."""

from __future__ import annotations

import ast
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TESTS = ROOT / "tests"


def _is_tempfile_mkdtemp(node: ast.Call) -> bool:
    return (
        isinstance(node.func, ast.Attribute)
        and node.func.attr == "mkdtemp"
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "tempfile"
    )


def _is_root_parent(node: ast.AST) -> bool:
    return (
        isinstance(node, ast.Attribute)
        and node.attr == "parent"
        and isinstance(node.value, ast.Name)
        and node.value.id == "ROOT"
    )


class RootParentTempDirPolicyTests(unittest.TestCase):
    def test_root_parent_mkdtemp_uses_cleanup_helper(self):
        offenders: list[str] = []
        for path in sorted(TESTS.glob("test*.py")):
            if path.name == Path(__file__).name:
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call) or not _is_tempfile_mkdtemp(node):
                    continue
                if any(
                    keyword.arg == "dir" and _is_root_parent(keyword.value)
                    for keyword in node.keywords
                ):
                    offenders.append(f"{path.relative_to(ROOT)}:{node.lineno}")

        self.assertEqual(
            offenders,
            [],
            "Use root_parent_tmp(self, ROOT, ...) from tests/tempdirs.py so "
            "cleanup is registered.",
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
