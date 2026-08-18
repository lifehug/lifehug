"""v182 exact-file Git transaction/adoption authority regressions."""

from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SYSTEM = ROOT / "system"
sys.path.insert(0, str(SYSTEM))
sys.path.insert(0, str(ROOT / "tests"))

import exact_file_git
from tempdirs import root_parent_tmp


def _run(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(root), *args],
        check=False,
        capture_output=True,
        text=True,
    )


class ExactFileGitTests(unittest.TestCase):
    def setUp(self):
        self.tmp = root_parent_tmp(self, ROOT, prefix="lifehug-exact-git-")
        (self.tmp / "state").mkdir()
        (self.tmp / ".gitignore").write_text("state/jobs/\n", encoding="utf-8")
        (self.tmp / "question-bank.md").write_text("# Questions\n", encoding="utf-8")
        (self.tmp / "state" / "rotation.json").write_text(
            json.dumps(
                {
                    "version": 1,
                    "current_pass": 1,
                    "pass_names": ["skeleton"],
                    "last_question_id": None,
                    "last_asked_at": None,
                    "questions_asked": 0,
                    "questions_answered": 0,
                    "next_question_id": None,
                    "focus_frequency": 4,
                }
            )
            + "\n",
            encoding="utf-8",
        )
        (self.tmp / "state" / "coverage.json").write_text(
            json.dumps({"version": 1, "last_updated": None, "categories": {}}) + "\n",
            encoding="utf-8",
        )
        (self.tmp / "record.md").write_text("before\n", encoding="utf-8")
        self.assertEqual(_run(self.tmp, "init", "-b", "main").returncode, 0)
        _run(self.tmp, "config", "user.name", "Fixture")
        _run(self.tmp, "config", "user.email", "fixture@example.invalid")
        _run(self.tmp, "add", ".")
        self.assertEqual(_run(self.tmp, "commit", "-m", "fixture").returncode, 0)

    def test_closed_plan_commits_only_declared_path_and_adopts_first_marker(self):
        marker = "<!-- exact-file:test:v1 -->"

        def decide(snapshot: exact_file_git.Snapshot) -> exact_file_git.ExactFilePlan:
            content = snapshot["record.md"]
            writes = (
                ()
                if marker in content.splitlines()
                else (("record.md", content + marker + "\n"),)
            )
            return exact_file_git.ExactFilePlan(
                writes, "record.md", marker, "Add exact marker"
            )

        def validate(
            snapshot: exact_file_git.Snapshot, plan: exact_file_git.ExactFilePlan
        ) -> None:
            self.assertIn(plan.marker_line, snapshot[plan.marker_path].splitlines())

        first = exact_file_git.resolve_exact_file_transaction(
            vault_root=self.tmp,
            declared_paths=("record.md",),
            decide=decide,
            validate=validate,
            push=False,
        )
        replay = exact_file_git.resolve_exact_file_transaction(
            vault_root=self.tmp,
            declared_paths=("record.md",),
            decide=decide,
            validate=validate,
            push=False,
        )
        self.assertTrue(first.changed)
        self.assertFalse(replay.changed)
        self.assertEqual(first.commit_sha, replay.commit_sha)

        (self.tmp / "other.md").write_text("later\n", encoding="utf-8")
        _run(self.tmp, "add", "other.md")
        _run(self.tmp, "commit", "-m", "later")
        self.assertEqual(
            exact_file_git.find_first_marker_commit(self.tmp, "record.md", marker),
            first.commit_sha,
        )

    def test_plan_cannot_write_an_undeclared_path(self):
        def decide(_snapshot: exact_file_git.Snapshot) -> exact_file_git.ExactFilePlan:
            return exact_file_git.ExactFilePlan(
                (("other.md", "no\n"),),
                "record.md",
                "marker",
                "Unsafe write",
            )

        with self.assertRaisesRegex(
            exact_file_git.ExactFileTransactionError, "undeclared write"
        ):
            exact_file_git.resolve_exact_file_transaction(
                vault_root=self.tmp,
                declared_paths=("record.md",),
                decide=decide,
                validate=lambda _snapshot, _plan: None,
                push=False,
            )

    def test_path_escape_and_multiline_marker_fail_closed(self):
        with self.assertRaisesRegex(
            exact_file_git.ExactFileTransactionError, "escaped vault root"
        ):
            exact_file_git.resolve_exact_file_transaction(
                vault_root=self.tmp,
                declared_paths=("../record.md",),
                decide=lambda _snapshot: None,  # type: ignore[arg-type,return-value]
                validate=lambda _snapshot, _plan: None,
                push=False,
            )

        def multiline(
            _snapshot: exact_file_git.Snapshot,
        ) -> exact_file_git.ExactFilePlan:
            return exact_file_git.ExactFilePlan(
                (), "record.md", "one\ntwo", "Invalid marker"
            )

        with self.assertRaisesRegex(
            exact_file_git.ExactFileTransactionError, "one bounded"
        ):
            exact_file_git.resolve_exact_file_transaction(
                vault_root=self.tmp,
                declared_paths=("record.md",),
                decide=multiline,
                validate=lambda _snapshot, _plan: None,
                push=False,
            )


if __name__ == "__main__":
    unittest.main()
