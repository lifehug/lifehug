"""v395 — the Focus-complete CLI parsers must build under the running Python.

v394 shipped a bare ``100%`` inside argparse help strings; Python 3.14 rejects
that with ``ValueError: badly formed help string`` before the verb runs, so
both verbs exited 1. These tests drive the real parsers (no mocks) under
whatever interpreter runs the suite. Synthetic vault only.
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SYSTEM = ROOT / "system"


def run(*argv: str, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, *argv], capture_output=True, text=True, cwd=cwd or ROOT, timeout=120
    )


class FocusCompleteCliHelpTests(unittest.TestCase):
    def test_lifehug_verbs_build_their_help(self):
        for verb in ("focus-complete-sweep", "focus-complete-play"):
            with self.subTest(verb=verb):
                r = run(str(SYSTEM / "lifehug.py"), verb, "--help")
                self.assertEqual(r.returncode, 0, r.stderr)
                self.assertNotIn("badly formed help string", r.stderr)

    def test_lifehug_top_level_help_lists_both_verbs(self):
        r = run(str(SYSTEM / "lifehug.py"), "--help")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("focus-complete-sweep", r.stdout)

    def test_focus_complete_module_parsers_build_their_help(self):
        for argv in (["--help"], ["sweep", "--help"], ["rows", "--help"], ["play", "--help"]):
            with self.subTest(argv=argv):
                r = run(str(SYSTEM / "focus_complete.py"), *argv)
                self.assertEqual(r.returncode, 0, r.stderr)
                self.assertNotIn("badly formed help string", r.stderr)
        r = run(str(SYSTEM / "focus_complete.py"), "--help")
        self.assertIn("100%", r.stdout)

    def test_no_bare_percent_in_help_strings_of_the_module(self):
        import argparse
        import importlib

        sys.path.insert(0, str(SYSTEM))
        try:
            fc = importlib.import_module("focus_complete")
        finally:
            sys.path.remove(str(SYSTEM))
        # Building help for every subparser is the real check.
        for argv in (["--help"], ["sweep", "--help"], ["play", "--help"]):
            with self.assertRaises(SystemExit) as cm:
                import contextlib
                import io

                with contextlib.redirect_stdout(io.StringIO()):
                    fc.cli(argv)
            self.assertEqual(cm.exception.code, 0)
        self.assertTrue(hasattr(argparse, "ArgumentParser"))

    def test_sweep_dry_run_runs_in_an_empty_synthetic_vault(self):
        with tempfile.TemporaryDirectory() as td:
            r = run(str(SYSTEM / "focus_complete.py"), "sweep", "--dry-run", cwd=Path(td))
            self.assertNotIn("badly formed help string", r.stderr)
            self.assertNotIn("ValueError", r.stderr)


if __name__ == "__main__":
    unittest.main()
