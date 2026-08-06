"""v117 — multi-writer git discipline (lifehug-platform ADR 0011).

One vault can be driven by several operators at once, so the framework must
read fresh before it decides and must survive losing a push race.

`process_answer.git_commit` is Python and is tested behaviorally with a faked
`subprocess.run`: the point is the *sequence* of git commands (rebase before
push, re-rebase before retry) and the promise that a failed push never costs
the author their commit.

The two shell entrypoints are bash. `daily_question.sh`'s new `safe_pull` is
extracted and actually executed against a temp repo with a broken remote — the
non-fatality claim is worth executing rather than asserting about. The pull in
`file_answer_bg.sh` is inline rather than a function, so it is pinned at the
text/ordering level. Its outer invocation enters the durable worker; the pull
and filing then run while that worker owns the vault-wide lease.
"""

import contextlib
import importlib.util
import io
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SYSTEM = ROOT / "system"
sys.path.insert(0, str(SYSTEM))

DAILY = SYSTEM / "daily_question.sh"
FILER = SYSTEM / "file_answer_bg.sh"


def load(name):
    """Load a private copy of system/<name>.py without clobbering sys.modules."""
    spec = importlib.util.spec_from_file_location(name, SYSTEM / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    orig = sys.modules.get(name)
    sys.modules[name] = mod
    try:
        spec.loader.exec_module(mod)
    finally:
        if orig is not None:
            sys.modules[name] = orig
        else:
            sys.modules.pop(name, None)
    return mod


class FakeGit:
    """Stand-in for subprocess.run that records git calls and scripts results.

    `codes` maps a git subcommand to a queue of return codes; anything not
    listed succeeds. `git diff --cached --quiet` defaults to 1, which is git's
    way of saying "there ARE staged changes".
    """

    def __init__(self, **codes):
        self.calls: list[list[str]] = []
        self.codes = {k: list(v) for k, v in codes.items()}

    @property
    def subcommands(self) -> list[str]:
        return [c[3] for c in self.calls if len(c) > 3]

    def __call__(self, cmd, *args, **kwargs):
        self.calls.append(list(cmd))
        sub = cmd[3] if len(cmd) > 3 else ""
        queue = self.codes.get(sub)
        if queue:
            rc = queue.pop(0)
        elif sub == "diff":
            rc = 1
        else:
            rc = 0
        if kwargs.get("check") and rc != 0:
            raise subprocess.CalledProcessError(rc, cmd)
        return subprocess.CompletedProcess(cmd, rc, stdout="", stderr="rejected\n")


DESTRUCTIVE = {"reset", "checkout", "restore", "stash"}


class GitCommitTests(unittest.TestCase):
    def setUp(self):
        self.mod = load("process_answer")

    @contextlib.contextmanager
    def run_git_commit(self, **codes):
        """Run git_commit against a faked git, capturing stderr.

        Keyword args are git subcommands ("push", "pull", "diff") mapped to a
        queue of return codes — note there is deliberately no `push=` flag
        here, so `push=[1, 0]` scripts the push RESULTS, not the argument.
        """
        fake = FakeGit(**codes)
        err = io.StringIO()
        with mock.patch.object(self.mod.subprocess, "run", fake), \
                mock.patch.object(self.mod, "record_learning_failure") as rec, \
                contextlib.redirect_stderr(err):
            fake.recorder = rec
            fake.stderr_buf = err
            yield fake

    def assert_commit_preserved(self, fake):
        """A failed push must never unwind the local commit."""
        self.assertIn("commit", fake.subcommands, "the commit must have been made")
        for cmd in fake.calls:
            sub = cmd[3] if len(cmd) > 3 else ""
            self.assertNotIn(
                sub, DESTRUCTIVE,
                f"git_commit ran a destructive command after a failed push: {cmd}",
            )

    # --- behavior without --push is unchanged -----------------------------

    def test_commit_without_push_never_touches_the_network(self):
        with self.run_git_commit() as fake:
            self.mod.git_commit("Answer A3: test", push=False)
        self.assertEqual(fake.subcommands, ["add", "diff", "commit"])

    def test_no_staged_changes_returns_before_committing(self):
        with self.run_git_commit(diff=[0]) as fake:
            self.mod.git_commit("Answer A3: test", push=True)
        self.assertEqual(fake.subcommands, ["add", "diff"])

    # --- discipline 3: pull, replay, retry --------------------------------

    def test_push_path_rebases_before_pushing(self):
        with self.run_git_commit(push=[0]) as fake:
            self.mod.git_commit("Answer A3: test", push=True)
        self.assertEqual(fake.subcommands, ["add", "diff", "commit", "pull", "push"])
        pull_cmd = next(c for c in fake.calls if c[3] == "pull")
        self.assertEqual(pull_cmd[3:], ["pull", "--rebase", "--autostash"])

    def test_rejected_push_retries_once_after_rebasing(self):
        with self.run_git_commit(push=[1, 0]) as fake:
            self.mod.git_commit("Answer A3: test", push=True)
        self.assertEqual(
            fake.subcommands,
            ["add", "diff", "commit", "pull", "push", "pull", "push"],
            "a rejected push must re-rebase before retrying, not just push again",
        )

    def test_persistent_rejection_exits_nonzero_and_keeps_the_commit(self):
        with self.run_git_commit(push=[1, 1]) as fake:
            with self.assertRaises(SystemExit) as caught:
                self.mod.git_commit("Answer A3: test", push=True)
            message = fake.stderr_buf.getvalue()
            recorder = fake.recorder
        self.assertEqual(caught.exception.code, 1)
        self.assertEqual(fake.subcommands.count("push"), self.mod.PUSH_ATTEMPTS)
        self.assert_commit_preserved(fake)
        recorder.assert_called_once()
        self.assertEqual(recorder.call_args.args[:2], ("process_answer", "git_push"))

    def test_failure_message_is_honest_about_what_survived(self):
        with self.run_git_commit(push=[1, 1]) as fake:
            with self.assertRaises(SystemExit):
                self.mod.git_commit("Answer A3: test", push=True)
            message = fake.stderr_buf.getvalue()
        self.assertIn("✗", message)
        self.assertIn("NOT pushed", message)
        self.assertIn("Nothing is lost", message)
        # It must tell the author how to finish the job themselves.
        self.assertIn("git pull --rebase --autostash && git push", message)

    def test_failed_pull_stops_before_pushing_and_keeps_the_commit(self):
        with self.run_git_commit(pull=[1]) as fake:
            with self.assertRaises(SystemExit) as caught:
                self.mod.git_commit("Answer A3: test", push=True)
        self.assertEqual(caught.exception.code, 1)
        self.assertNotIn("push", fake.subcommands)
        self.assert_commit_preserved(fake)


def extract_function(script: Path, name: str) -> str:
    """Pull a top-level bash function out of a script so it can run alone."""
    out = subprocess.run(
        ["sed", "-n", f"/^{name}() {{/,/^}}/p", str(script)],
        capture_output=True, text=True, check=True,
    ).stdout
    if not out.strip():
        raise AssertionError(f"{name} not found in {script}")
    return out


class SafePullTests(unittest.TestCase):
    """daily_question.sh's pull-before-pick, actually executed."""

    def setUp(self):
        self.func = extract_function(DAILY, "safe_pull")

    def run_safe_pull(self, workdir: Path) -> subprocess.CompletedProcess:
        script = (
            "set -euo pipefail\n"
            f"cd {workdir}\n"
            'record_learning_failure() { printf "%s %s %s\\n" "$1" "$2" "$3" >> recorded.log; }\n'
            f"{self.func}\n"
            "safe_pull\n"
            "echo SURVIVED\n"
        )
        return subprocess.run(["bash", "-c", script], capture_output=True, text=True)

    def test_bash_syntax_valid(self):
        result = subprocess.run(["bash", "-n", str(DAILY)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_unreachable_remote_is_non_fatal_and_recorded(self):
        with tempfile.TemporaryDirectory() as tmp:
            work = Path(tmp)
            subprocess.run(["git", "init", "-q", str(work)], check=True)
            subprocess.run(
                ["git", "-C", str(work), "remote", "add", "origin",
                 str(work / "nope-does-not-exist.git")],
                check=True,
            )
            result = self.run_safe_pull(work)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("SURVIVED", result.stdout)
            log = work / "recorded.log"
            self.assertTrue(log.exists(), "a failed pull must reach the learning loop")
            self.assertIn("git_pull_before_pick", log.read_text())

    def test_no_remote_is_skipped_silently(self):
        with tempfile.TemporaryDirectory() as tmp:
            work = Path(tmp)
            subprocess.run(["git", "init", "-q", str(work)], check=True)
            result = self.run_safe_pull(work)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("SURVIVED", result.stdout)
            self.assertFalse(
                (work / "recorded.log").exists(),
                "a local-only install must not log a failure every morning",
            )

    def test_pull_runs_before_the_question_is_picked(self):
        text = DAILY.read_text()
        call = text.index("\nsafe_pull\n")
        self.assertLess(call, text.index("wiki_compile.py"))
        self.assertLess(call, text.index("from lifehug_core import ROTATION_FILE"))
        # The live pick, not the dry-run branch above it (which exits early).
        self.assertLess(call, text.index("QUESTION_OUTPUT=$(python3"))

    def test_dry_run_exits_before_mutating_the_working_tree(self):
        text = DAILY.read_text()
        self.assertLess(text.index("LIFEHUG_DAILY_DRY_RUN"), text.index("\nsafe_pull\n"))


class FilerPullTests(unittest.TestCase):
    """file_answer_bg.sh's pull-before-filing (inline; pinned at text level)."""

    def setUp(self):
        self.text = FILER.read_text()

    def test_bash_syntax_valid(self):
        result = subprocess.run(["bash", "-n", str(FILER)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_pulls_with_rebase_and_autostash(self):
        self.assertIn("git pull --rebase --autostash", self.text)

    def test_pull_happens_before_filing_inside_worker_lease(self):
        pull = self.text.index("git pull --rebase --autostash")
        # The actual invocation, not the header comment that mentions it.
        self.assertLess(pull, self.text.index('python3 "$SCRIPT_DIR/lifehug.py" process-answer'),
                        "the pull must precede the filing it informs")
        active_guard = self.text.index('jobs.py" active')
        enqueue = self.text.index('jobs.py" file-answer')
        self.assertLess(active_guard, enqueue)
        self.assertLess(enqueue, pull,
                        "only the worker's active re-entry may reach the pull")
        self.assertNotIn("state/.filing.lock", self.text)

    def test_pull_is_guarded_and_non_fatal(self):
        self.assertIn("git rev-parse --is-inside-work-tree", self.text)
        self.assertIn("git remote", self.text)
        self.assertIn("git_pull_before_filing", self.text)
        # `set -e` would turn a failed pull into a dropped answer.
        self.assertNotIn("set -e", self.text)


if __name__ == "__main__":
    unittest.main()
