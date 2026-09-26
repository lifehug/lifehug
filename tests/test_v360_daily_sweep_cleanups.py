"""v360 (owner, 2026-09-25): the two one-time vault cleanups are safe on every daily sweep.

`landmark-fold-duplicates --apply` (one place, one landmark) and
`landmark-refile --apply` (a record is filed where it belongs) were written to
clean up what landed in a vault before their rules existed. The platform runs
them on every daily sweep rather than once by hand, so each must be:

1. **a no-op when there is nothing to do** — on a clean vault the run exits 0,
   says so, and writes NOTHING (no merge or refile record, no redraw, no
   publication, not one byte anywhere in the vault);
2. **idempotent** — a second run after a real cleanup files nothing and changes
   nothing, in either order.

The exact argv the platform runs is pinned here through a real subprocess
(``LIFEHUG_VAULT_ROOT`` bound, as the platform's package runner does):

    python3 system/lifehug.py landmark-fold-duplicates --apply --json
    python3 system/lifehug.py landmark-refile --apply --json

Synthetic vault only; NEVER references ~/Workspace/dave.
"""

from __future__ import annotations

import argparse
import contextlib
import copy
import hashlib
import io
import json
import os
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SYSTEM = ROOT / "system"
sys.path.insert(0, str(SYSTEM))
sys.path.insert(0, str(ROOT / "tests"))

import landmark_projection as lp  # noqa: E402
import timeline  # noqa: E402
from tempdirs import root_parent_tmp  # noqa: E402
from test_conversation_close import make_vault  # noqa: E402
import test_v360_one_place_one_landmark as opl  # noqa: E402
import test_v360_records_and_readings as rr  # noqa: E402

NOW = "2026-09-25T12:00:00Z"

#: The two verbs, exactly as the platform's daily sweep runs them.
SWEEP_ARGV = (
    ("landmark-fold-duplicates", "--apply", "--json"),
    ("landmark-refile", "--apply", "--json"),
)

#: His landmarks with both kinds of mess cleared: one of each domain the two
#: rules read, no duplicate and no misfiled record.
CLEAN_SEED = {
    "residences": copy.deepcopy(opl.SEED["residences"]),
    "schools": copy.deepcopy(opl.SEED["schools"]),
    "work": copy.deepcopy(rr.SEED["work"]),
    "partnerships": copy.deepcopy(rr.SEED["partnerships"]),
}


#: The single-writer kernel's lock (`jobs`): an empty file every vault-mutation
#: verb takes before it runs, whether or not it then writes. It is the lock,
#: not vault data, so it is the one path a no-op may leave behind.
WRITER_LOCK = "state/jobs/.writer-v2.lock"


def snapshot(vault: Path) -> dict[str, str]:
    """Every file in the vault (outside .git and the writer lock) and its hash."""
    out = {}
    for path in sorted(vault.rglob("*")):
        rel = path.relative_to(vault)
        if ".git" in rel.parts or not path.is_file() or rel.as_posix() == WRITER_LOCK:
            continue
        out[path.relative_to(vault).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    return out


class SweepVault(unittest.TestCase):
    """A real on-disk vault; seeding runs in-process, the verbs in a subprocess."""

    def setUp(self) -> None:
        self.tmp = root_parent_tmp(self, ROOT, prefix="lifehug-v360-sweep-")
        self.vault = make_vault(self.tmp / "vault")
        self.store = self.vault / "state" / "landmarks.json"
        for patch in (mock.patch.object(timeline, "LANDMARKS_STORE", self.store),
                      mock.patch.object(timeline, "_projection_vault_root",
                                        lambda: self.vault)):
            patch.start()
            self.addCleanup(patch.stop)
        self.env = os.environ.copy()
        self.env.update({"LIFEHUG_VAULT_ROOT": str(self.vault),
                         "PYTHONDONTWRITEBYTECODE": "1"})
        self.env.pop("WORKSPACE", None)
        self.env.pop("PYTHONPATH", None)

    def seed(self, domains: dict) -> None:
        self.store.write_text(json.dumps({"version": 1, "domains": copy.deepcopy(domains)},
                                         indent=2) + "\n", encoding="utf-8")
        timeline.flip_landmarks_if_needed()

    def file_raw(self, domain: str, record: dict) -> None:
        """File a record the way the sweep did BEFORE either rule existed."""
        lp.file_landmark_record(self.vault, domain, dict(record),
                                ordinal=lp.next_ordinal(self.vault),
                                extractor_version=lp.LIVE_EXTRACTOR, now=NOW)
        timeline.redraw_landmarks()

    def run_verb(self, argv: tuple[str, ...]) -> dict:
        result = subprocess.run(
            [sys.executable, str(SYSTEM / "lifehug.py"), *argv],
            capture_output=True, text=True, env=self.env, cwd=self.vault, timeout=300)
        self.assertEqual(result.returncode, 0, f"{argv}: {result.stderr}")
        return json.loads(result.stdout)

    def sweep(self) -> list[dict]:
        return [self.run_verb(argv) for argv in SWEEP_ARGV]

    def assert_noop(self, results: list[dict]) -> None:
        for argv, result in zip(SWEEP_ARGV, results):
            self.assertEqual((result["plan"], result["filed"], result["applied"]),
                             ([], [], True), argv[0])


class ANoOpWhenThereIsNothingToDoTests(SweepVault):

    def test_a_vault_with_no_landmarks_at_all_is_untouched(self) -> None:
        before = snapshot(self.vault)
        self.assert_noop(self.sweep())
        self.assertEqual(snapshot(self.vault), before)

    def test_a_clean_vault_is_untouched(self) -> None:
        self.seed(CLEAN_SEED)
        before = snapshot(self.vault)
        self.assert_noop(self.sweep())
        self.assertEqual(snapshot(self.vault), before)
        self.assertFalse((self.vault / lp.REFILE_SOURCES_DIR).exists())
        self.assertEqual(lp.load_landmark_merges(self.vault), [])


class IdempotentTests(SweepVault):

    def setUp(self) -> None:
        super().setUp()
        self.seed(CLEAN_SEED)
        for domain, record in (("residences", opl.THUNDERHEAD_STREET),
                               ("residences", opl.FIEGERS),
                               ("schools", opl.MOUNTAIN_VIEW_HIGH),
                               ("schools", rr.KATIE_SCHOOL),
                               ("work", rr.SAFE),
                               ("partnerships", rr.CASTLE_SEED)):
            self.file_raw(domain, record)

    def test_the_first_sweep_cleans_and_every_later_sweep_changes_nothing(self) -> None:
        fold, refile = self.sweep()
        self.assertTrue(fold["plan"] and fold["filed"])
        self.assertTrue(refile["plan"] and refile["filed"])
        after_first = snapshot(self.vault)
        for _ in range(2):
            self.assert_noop(self.sweep())
            self.assertEqual(snapshot(self.vault), after_first)

    def test_either_order_settles_to_the_same_vault(self) -> None:
        for argv in reversed(SWEEP_ARGV):
            self.assertTrue(self.run_verb(argv)["filed"], argv[0])
        settled = snapshot(self.vault)
        self.assert_noop(self.sweep())
        for argv in reversed(SWEEP_ARGV):
            result = self.run_verb(argv)
            self.assertEqual((result["plan"], result["filed"]), ([], []), argv[0])
        self.assertEqual(snapshot(self.vault), settled)

    def test_the_cleaned_landmarks_are_the_ones_he_gave(self) -> None:
        self.sweep()
        self.sweep()
        drawn = timeline.load_landmarks()
        self.assertEqual(sorted(e["label"] for e in drawn.get("residences") or ()),
                         sorted(e["label"] for e in CLEAN_SEED["residences"]))
        self.assertEqual([e["label"] for e in drawn.get("schools") or ()], ["Mountain View"])
        self.assertNotIn("SAFE conversion", [e["label"] for e in drawn.get("work") or ()])
        self.assertEqual([e["label"] for e in drawn.get("partnerships") or ()],
                         ["Katie Ann Merrill"])


class InProcessDryRunTests(SweepVault):
    """The dry run (no --apply) is what the sweep can log first; it writes nothing."""

    def test_a_dry_run_never_writes(self) -> None:
        import lifehug

        self.seed(CLEAN_SEED)
        self.file_raw("residences", opl.THUNDERHEAD_STREET)
        self.file_raw("work", rr.SAFE)
        before = snapshot(self.vault)
        for command in (lifehug.cmd_landmark_fold_duplicates, lifehug.cmd_landmark_refile):
            args = argparse.Namespace(pair=[], apply=False, json=False)
            buffer = io.StringIO()
            with mock.patch.object(lifehug, "REPO_DIR", self.vault), \
                    contextlib.redirect_stdout(buffer):
                self.assertEqual(command(args), 0)
            self.assertIn("nothing written", buffer.getvalue())
        self.assertEqual(snapshot(self.vault), before)


if __name__ == "__main__":
    unittest.main()
