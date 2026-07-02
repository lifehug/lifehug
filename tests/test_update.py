"""Tests for the framework updater (system/update.py).

Covers the two bugs fixed in v56:
  1. run_git stripped trailing newlines, so every file the updater wrote lost
     its final newline. apply_version now uses read_repo_file_at (byte-exact).
  2. The protection check used prefix matching for file entries, so
     'config.yaml' shadowed 'config.yaml.example' and the updater could never
     update the example file. is_protected now matches files exactly and only
     treats trailing-slash entries as directory prefixes.
"""
import json
import subprocess
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "system"))
import update  # noqa: E402


class IsProtectedTests(unittest.TestCase):
    def test_exact_file_is_protected(self):
        self.assertTrue(update.is_protected("config.yaml"))
        self.assertTrue(update.is_protected("README.md"))

    def test_example_file_is_not_protected(self):
        # The whole point of the fix: config.yaml.example must be updatable.
        self.assertFalse(update.is_protected("config.yaml.example"))

    def test_ordinary_framework_file_is_not_protected(self):
        self.assertFalse(update.is_protected("system/ask.py"))

    def test_directory_prefix_is_protected(self):
        self.assertTrue(update.is_protected("answers/A1.md"))
        self.assertTrue(update.is_protected("sources/manual/story.md"))
        self.assertTrue(update.is_protected("answers"))  # the dir itself


class ApplyVersionTests(unittest.TestCase):
    def setUp(self):
        import tempfile
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: __import__("shutil").rmtree(self.tmp, ignore_errors=True))
        self._git("init", "-q")
        self._git("config", "user.email", "t@test")
        self._git("config", "user.name", "t")
        self._git("config", "commit.gpgsign", "false")
        # patch module globals to point at the temp repo
        self._orig = (update.REPO_DIR, update.VERSION_FILE)
        update.REPO_DIR = self.tmp
        update.VERSION_FILE = self.tmp / "system" / "version.json"
        self.addCleanup(self._restore)

    def _restore(self):
        update.REPO_DIR, update.VERSION_FILE = self._orig

    def _git(self, *args):
        subprocess.run(["git", "-C", str(self.tmp), *args], check=True,
                       capture_output=True, text=True)

    def _write(self, rel, data):
        p = self.tmp / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(data, bytes):
            p.write_bytes(data)
        else:
            p.write_text(data)
        return p

    def test_apply_preserves_trailing_newline_and_updates_example(self):
        framework_files = ["system/ask.py", "config.yaml.example", "config.yaml",
                           "README.md", "system/version.json"]
        # v2 tag: the "good" upstream content.
        self._write("system/version.json",
                    json.dumps({"version": 2, "framework_files": framework_files}) + "\n")
        self._write("system/ask.py", "print('hi')\n")          # note trailing newline
        self._write("config.yaml.example", "NEW example v35 split\n")
        self._write("config.yaml", "SECRET local\n")
        self._write("README.md", "USER README\n")
        self._git("add", "-A")
        self._git("commit", "-q", "-m", "v2")
        self._git("tag", "-a", "v2", "-m", "v2")

        # Now simulate a stale checkout that is BEHIND: strip newlines, revert the
        # example, and locally customise the protected files. Commit so the tree
        # is clean (apply refuses to run on dirty framework files).
        self._write("system/ask.py", "print('hi')")            # newline stripped
        self._write("config.yaml.example", "OLD pre-v35 example")
        self._write("config.yaml", "MY SECRETS — keep me")
        self._write("README.md", "MY PERSONAL README — keep me")
        self._write("system/version.json",
                    json.dumps({"version": 1, "framework_files": framework_files}) + "\n")
        self._git("add", "-A")
        self._git("commit", "-q", "-m", "stale")

        ok = update.apply_version(2)
        self.assertTrue(ok)

        # 1. Trailing newline restored (byte-exact to the tag).
        self.assertEqual((self.tmp / "system/ask.py").read_bytes(), b"print('hi')\n")
        # 2. config.yaml.example updated (no longer wrongly protected).
        self.assertEqual((self.tmp / "config.yaml.example").read_text(), "NEW example v35 split\n")
        # 3. Protected user data untouched.
        self.assertEqual((self.tmp / "config.yaml").read_text(), "MY SECRETS — keep me")
        self.assertEqual((self.tmp / "README.md").read_text(), "MY PERSONAL README — keep me")


if __name__ == "__main__":
    unittest.main()
