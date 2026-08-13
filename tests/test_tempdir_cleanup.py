"""Regression guard: test temp dirs must never land in the workspace.

Tests once created temp vaults in the worktree's parent directory (to dodge
vault_paths' symlink refusal of macOS's /var temp prefix). Runs killed before
cleanup leaked thousands of tmp* dirs into the user's workspace. The policy
now: every tempfile.mkdtemp/TemporaryDirectory call in tests that passes an
explicit ``dir=`` must pass tempdirs.SYMLINK_FREE_TMP_BASE — never a path
derived from the repo's location (ROOT.parent, Path(...).parents[n], etc.).
"""

from __future__ import annotations

import ast
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TESTS = ROOT / "tests"

ALLOWED_DIR_NAME = "SYMLINK_FREE_TMP_BASE"


def _is_tempfile_tmp_call(node: ast.Call) -> bool:
    return (
        isinstance(node.func, ast.Attribute)
        and node.func.attr in {"mkdtemp", "TemporaryDirectory", "mktemp", "mkstemp"}
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "tempfile"
    )


def _is_allowed_dir_value(node: ast.AST) -> bool:
    # SYMLINK_FREE_TMP_BASE or tempdirs.SYMLINK_FREE_TMP_BASE
    if isinstance(node, ast.Name):
        return node.id == ALLOWED_DIR_NAME
    return isinstance(node, ast.Attribute) and node.attr == ALLOWED_DIR_NAME


class WorkspaceTempDirPolicyTests(unittest.TestCase):
    def test_no_test_creates_temp_dirs_outside_the_symlink_free_base(self):
        offenders: list[str] = []
        for path in sorted(TESTS.glob("test*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call) or not _is_tempfile_tmp_call(node):
                    continue
                for keyword in node.keywords:
                    if keyword.arg == "dir" and not _is_allowed_dir_value(keyword.value):
                        offenders.append(f"{path.relative_to(ROOT)}:{node.lineno}")

        self.assertEqual(
            offenders,
            [],
            "Explicit dir= in tempfile calls must be "
            "tempdirs.SYMLINK_FREE_TMP_BASE (or use tempdirs.symlink_free_tmp), "
            "so temp dirs never leak into the user's workspace.",
        )

    def test_symlink_free_base_really_has_no_symlink_components(self):
        import tempfile

        base = Path(tempfile.gettempdir()).resolve()
        chain = [base, *base.parents]
        self.assertEqual([p for p in chain if p.is_symlink()], [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
