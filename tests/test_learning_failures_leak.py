"""Issue #225 — the test suite leaves the checkout byte-clean.

Running the full suite once wrote ``state/learning_failures.jsonl`` into the
repo checkout: two tests stub ``sys.modules["timeline_interaction"]`` with a
bare ``object()`` and drive ``question_planner.mint_keystone_questions``; on
v196-era code the timeline walk ran INSIDE the recorded try, the stub raised
``AttributeError: 'object' object has no attribute 'anchor_rows_for_prompt'``,
and ``record_learning_failure`` resolved the ledger against the process-bound
vault — which, in a test run, is the checkout itself. The file was not
gitignored either, so ``git add -A`` committed it.

These tests pin both fixes:

* the incident replay (a fresh interpreter, the bare-object stub, the mint
  path against the checkout-bound vault) leaves the checkout's ledger
  untouched — this is the guard that fails if the mint path ever again
  ledgers a stub-induced failure into the checkout;
* the offending test modules themselves leave the checkout's ledger and
  ``git status`` for ``state/`` unchanged after a full run;
* ``record_learning_failure(vault_root=...)`` — the one definition of the
  root-scoped ledger path — writes into THAT vault, never the checkout;
* ``state/learning_failures.jsonl`` is gitignored (defense in depth).

Synthetic data only; NEVER references ~/Workspace/dave.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SYSTEM = ROOT / "system"
LEDGER = ROOT / "state" / "learning_failures.jsonl"

#: The historical trigger, byte-faithful to the incident: a bare object() in
#: sys.modules and the two guarded planner reads, in a FRESH interpreter whose
#: process vault is the checkout itself.
INCIDENT_REPLAY = """
import sys
sys.path.insert(0, {system!r})
import importlib.util

spec = importlib.util.spec_from_file_location("question_planner",
                                              {system!r} + "/question_planner.py")
qp = importlib.util.module_from_spec(spec)
sys.modules["question_planner"] = qp
spec.loader.exec_module(qp)

sys.modules["timeline_interaction"] = object()  # the issue #225 stub
assert qp.current_timeline_probes() == {{}}
assert qp.mint_keystone_questions() == []
assert qp.mint_queue_questions(work_items=[], question_bank_text="# Questions\\n") == []
print("degraded-clean")
"""


def _ledger_bytes() -> bytes | None:
    try:
        return LEDGER.read_bytes()
    except FileNotFoundError:
        return None


def _checkout_env() -> dict[str, str]:
    # The replay must resolve the CHECKOUT as the process vault — drop any
    # explicit binding the harness may carry.
    env = {k: v for k, v in os.environ.items() if k != "LIFEHUG_VAULT_ROOT"}
    return env


def _state_status() -> str | None:
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain", "--", "state"],
            capture_output=True, text=True, cwd=ROOT, timeout=60,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    return result.stdout if result.returncode == 0 else None


class CheckoutStaysCleanTests(unittest.TestCase):
    def test_the_incident_replay_leaves_the_checkout_ledger_untouched(self):
        """The bare-object stub + the mint path, against the checkout vault:
        degrade to nothing, record nothing into the checkout."""
        before = _ledger_bytes()
        result = subprocess.run(
            [sys.executable, "-c", INCIDENT_REPLAY.format(system=str(SYSTEM))],
            capture_output=True, text=True, cwd=ROOT, env=_checkout_env(), timeout=120,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("degraded-clean", result.stdout)
        self.assertEqual(_ledger_bytes(), before,
                         "the mint path ledgered a test failure into the "
                         "checkout's state/learning_failures.jsonl (issue #225)")

    def test_the_offending_test_modules_leave_the_checkout_clean(self):
        """Issue #225's ask verbatim: repo status is clean after the offending
        test modules run."""
        before_ledger = _ledger_bytes()
        before_status = _state_status()
        result = subprocess.run(
            [sys.executable, "-m", "unittest", "-q",
             "tests.test_timeline_unknowns", "tests.test_work_item_queue"],
            capture_output=True, text=True, cwd=ROOT, env=_checkout_env(), timeout=300,
        )
        self.assertEqual(result.returncode, 0, result.stderr[-2000:])
        self.assertEqual(_ledger_bytes(), before_ledger,
                         "running the offending test modules wrote the "
                         "checkout's state/learning_failures.jsonl (issue #225)")
        if before_status is not None:
            self.assertEqual(_state_status(), before_status)

    def test_the_ledger_writer_scopes_to_the_given_vault_root(self):
        """One definition (issue #225): ``vault_root`` puts the row in THAT
        vault's state/, and the checkout's ledger stays untouched."""
        sys.path.insert(0, str(SYSTEM))
        try:
            import lifehug_core  # noqa: PLC0415
        finally:
            sys.path.remove(str(SYSTEM))
        before = _ledger_bytes()
        with tempfile.TemporaryDirectory(prefix="lifehug-ledger-") as tmp:
            record = lifehug_core.record_learning_failure(
                "question_planner", "mint_queue_questions",
                "synthetic issue #225 probe", vault_root=tmp)
            written = Path(tmp) / "state" / "learning_failures.jsonl"
            self.assertTrue(written.exists())
            self.assertIn("synthetic issue #225 probe", written.read_text(encoding="utf-8"))
            self.assertEqual(record["component"], "question_planner")
        self.assertEqual(_ledger_bytes(), before)

    def test_the_ledger_file_is_gitignored(self):
        """Defense in depth: even a leaked ledger never reaches `git add -A`."""
        try:
            result = subprocess.run(
                ["git", "check-ignore", "-q", "state/learning_failures.jsonl"],
                capture_output=True, text=True, cwd=ROOT, timeout=60,
            )
        except (OSError, subprocess.TimeoutExpired):
            self.skipTest("git unavailable")
        if result.returncode not in (0, 1):
            self.skipTest("not a git checkout")
        self.assertEqual(result.returncode, 0,
                         "state/learning_failures.jsonl must be gitignored (issue #225)")


if __name__ == "__main__":
    unittest.main()
