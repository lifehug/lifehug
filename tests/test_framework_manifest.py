"""A_FIXTURE_NEVER_SHIPS_TO_A_VAULT (v416): framework_files never names a
test fixture, and update --apply retires fixtures an old version shipped."""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "system"))
sys.path.insert(0, str(ROOT / "scripts" / "ci"))

import check_framework_files  # noqa: E402
import update  # noqa: E402


class ManifestNamesNoFixtureTests(unittest.TestCase):
    def test_version_json_lists_nothing_under_tests_fixtures(self):
        files = json.loads((ROOT / "system" / "version.json").read_text())["framework_files"]
        bad = [f for f in files if f.startswith(update.A_FIXTURE_NEVER_SHIPS_TO_A_VAULT)]
        self.assertEqual(bad, [])

    def test_ci_check_flags_a_listed_fixture(self):
        with tempfile.TemporaryDirectory() as d:
            vj = Path(d) / "version.json"
            vj.write_text(json.dumps({"framework_files": [
                "system/ask.py", "tests/test_x.py",
                "tests/fixtures/letters_repo/letters/a/transcript.md"]}))
            self.assertEqual(check_framework_files.check_no_fixtures(vj),
                             ["tests/fixtures/letters_repo/letters/a/transcript.md"])

    def test_plain_test_py_files_and_lookalikes_are_not_fixtures(self):
        for ok in ("tests/test_update.py", "tests/goldens/a.json",
                   "tests/fixtures", "tests/fixturesX/a.md", "system/tests/fixtures/a.md",
                   "tests/fixtures/../../x", "/tests/fixtures/a"):
            self.assertFalse(update.is_fixture_path(ok), ok)
        self.assertTrue(update.is_fixture_path("tests/fixtures/a/b.pdf"))


class RetireShippedFixturesTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: __import__("shutil").rmtree(self.tmp, ignore_errors=True))
        for a in (("init", "-q", "-b", "main"), ("config", "user.email", "t@t"),
                  ("config", "user.name", "t"), ("config", "commit.gpgsign", "false")):
            self._git(*a)
        self._orig = (update.REPO_DIR, update.VERSION_FILE)
        update.REPO_DIR = self.tmp
        update.VERSION_FILE = self.tmp / "system" / "version.json"
        self.addCleanup(lambda: setattr(update, "REPO_DIR", self._orig[0]))
        self.addCleanup(lambda: setattr(update, "VERSION_FILE", self._orig[1]))

    def _git(self, *args):
        subprocess.run(["git", "-C", str(self.tmp), *args], check=True,
                       capture_output=True, text=True)

    def _w(self, rel, text):
        p = self.tmp / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)

    def test_apply_removes_only_the_fixtures_the_old_version_shipped(self):
        fx = "tests/fixtures/letters_repo/letters/a/transcript.md"
        pdf = "tests/fixtures/letters_repo/source/A B.pdf"
        # v2 tag: the corrected list (no fixtures).
        new = ["system/ask.py", "system/version.json"]
        self._w("system/version.json", json.dumps({"version": 2, "framework_files": new}))
        self._w("system/ask.py", "v2\n")
        self._git("add", "-A"); self._git("commit", "-q", "-m", "v2"); self._git("tag", "-a", "v2", "-m", "v2")
        # The vault at v1 (as after v412-v415): its list named the fixtures.
        old = new + [fx, pdf]
        self._w("system/version.json", json.dumps({"version": 1, "framework_files": old}))
        self._w(fx, "---\nid: letters/a/b\n---\n")
        self._w(pdf, "pdf")
        # NOT shipped by any update: a fixture the vault's own list never named,
        # the owner's own file, and a non-fixture the old list named.
        self._w("tests/fixtures/mine.md", "keep")
        self._w("answers/A1.md", "keep")
        self._git("add", "-A"); self._git("commit", "-q", "-m", "stale")

        import contextlib, io
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertTrue(update.apply_version(2))

        self.assertFalse((self.tmp / fx).exists())
        self.assertFalse((self.tmp / pdf).exists())
        self.assertFalse((self.tmp / "tests/fixtures/letters_repo").exists())  # emptied dirs pruned
        self.assertTrue((self.tmp / "tests/fixtures/mine.md").exists())
        self.assertTrue((self.tmp / "answers/A1.md").exists())
        lines = [l for l in out.getvalue().splitlines() if "Removed" in l]
        self.assertEqual(len(lines), 2)
        self.assertIn(fx, lines[0])
        tracked = subprocess.run(["git", "-C", str(self.tmp), "ls-files"], capture_output=True, text=True).stdout
        self.assertNotIn("letters_repo", tracked)
        self.assertIn("tests/fixtures/mine.md", tracked)

    def test_never_removes_a_non_fixture_even_if_dropped_from_the_list(self):
        self.assertEqual(update.fixtures_to_retire(
            ["system/old.py", "tests/test_a.py", "tests/fixtures/x.md"], ["system/ask.py"]),
            ["tests/fixtures/x.md"])


if __name__ == "__main__":
    unittest.main()
