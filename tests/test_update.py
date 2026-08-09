"""Tests for the framework updater (system/update.py).

Covers the two bugs fixed in v56:
  1. run_git stripped trailing newlines, so every file the updater wrote lost
     its final newline. apply_version now uses read_repo_file_at (byte-exact).
  2. The protection check used prefix matching for file entries, so
     'config.yaml' shadowed 'config.yaml.example' and the updater could never
     update the example file. is_protected now matches files exactly and only
     treats trailing-slash entries as directory prefixes.

Also covers the tag-lapse-proof --check (lifehug#84 item 1): v118-v128
shipped on main while the tag flow silently lapsed, so a tags-only check
reported "current: 117, latest: 117" for four days of real releases.
"""
import argparse
import contextlib
import io
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

    def test_apply_restores_exec_bit_on_new_and_existing_scripts(self):
        # v84 fix: write_bytes creates NEW files as 0o644, so an executable
        # framework script arriving via update lost its exec bit (seen live
        # with file_answer_bg.sh landing as rw-r--r--). apply_version now
        # mirrors the tag's git mode (100755 → chmod +x), repairing
        # already-broken copies on the next apply too.
        import os
        framework_files = ["system/new_tool.sh", "system/old_tool.sh",
                           "system/version.json"]
        new_tool = self._write("system/new_tool.sh", "#!/bin/bash\necho new\n")
        old_tool = self._write("system/old_tool.sh", "#!/bin/bash\necho old\n")
        new_tool.chmod(0o755)
        old_tool.chmod(0o755)
        self._write("system/version.json",
                    json.dumps({"version": 2, "framework_files": framework_files}) + "\n")
        self._git("add", "-A")
        self._git("commit", "-q", "-m", "v2")
        self._git("tag", "-a", "v2", "-m", "v2")

        # Stale checkout: new_tool.sh doesn't exist yet (the new-file case);
        # old_tool.sh exists but lost its exec bit (the already-broken case).
        new_tool.unlink()
        old_tool.chmod(0o644)
        self._write("system/version.json",
                    json.dumps({"version": 1, "framework_files": framework_files}) + "\n")
        self._git("add", "-A")
        self._git("commit", "-q", "-m", "stale")

        self.assertTrue(update.apply_version(2))
        self.assertTrue(os.access(self.tmp / "system/new_tool.sh", os.X_OK))
        self.assertTrue(os.access(self.tmp / "system/old_tool.sh", os.X_OK))


class TagLapseCheckTests(unittest.TestCase):
    """cmd_check compares origin/main's version.json in addition to tags
    (lifehug#84 item 1) and caches its result to state/update_check.json for
    the viewer (item 2)."""

    def setUp(self):
        import tempfile
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: __import__("shutil").rmtree(self.tmp, ignore_errors=True))
        self._orig = (update.REPO_DIR, update.VERSION_FILE)
        self.addCleanup(self._restore)

    def _restore(self):
        update.REPO_DIR, update.VERSION_FILE = self._orig

    def _git(self, repo, *args):
        subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True)

    def _init_repo(self, repo):
        repo.mkdir(parents=True, exist_ok=True)
        self._git(repo, "init", "-q")
        self._git(repo, "config", "user.email", "t@test")
        self._git(repo, "config", "user.name", "t")
        self._git(repo, "config", "commit.gpgsign", "false")

    def _write_version(self, repo, version, framework_files=None):
        p = repo / "system" / "version.json"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps({
            "version": version,
            "changelog": f"v{version} changelog",
            "framework_files": framework_files or ["system/version.json"],
        }) + "\n")
        return p

    def _make_lapsed_remote(self):
        """A remote whose tags stop at v1 but whose main is at v2 —
        find_upstream_remote() only matches URLs containing 'lifehug/lifehug',
        so the path itself has to carry that substring."""
        remote = self.tmp / "gh" / "lifehug" / "lifehug"
        self._init_repo(remote)
        self._write_version(remote, 1)
        self._git(remote, "add", "-A")
        self._git(remote, "commit", "-q", "-m", "v1")
        self._git(remote, "tag", "-a", "v1", "-m", "v1")
        # main advances to v2 with NO matching tag — the exact lapse that hid
        # v118-v128 from every vault for four days.
        self._write_version(remote, 2)
        self._git(remote, "add", "-A")
        self._git(remote, "commit", "-q", "-m", "v2, untagged")
        return remote

    def _make_local(self, current_version=1):
        local = self.tmp / "local"
        self._init_repo(local)
        self._write_version(local, current_version)
        self._git(local, "add", "-A")
        self._git(local, "commit", "-q", "-m", "local")
        update.REPO_DIR = local
        update.VERSION_FILE = local / "system" / "version.json"
        return local

    def _run_check(self, quiet=False):
        buf_out, buf_err = io.StringIO(), io.StringIO()
        args = argparse.Namespace(check=True, quiet=quiet, apply=False, version=None,
                                   rollback=False, migrate_vault=False, vault_root=None)
        exit_code = None
        with contextlib.redirect_stdout(buf_out), contextlib.redirect_stderr(buf_err):
            try:
                update.cmd_check(args)
            except SystemExit as exc:
                exit_code = exc.code
        return buf_out.getvalue(), buf_err.getvalue(), exit_code

    def test_tag_lapse_detected_against_remote_main(self):
        remote = self._make_lapsed_remote()
        local = self._make_local(current_version=1)
        self._git(local, "remote", "add", "upstream", str(remote))

        out, err, exit_code = self._run_check(quiet=False)

        self.assertIsNone(exit_code)
        result = json.loads(out)
        self.assertEqual(result["current"], 1)
        # latest reflects the true latest version (main), not the stale tag.
        self.assertEqual(result["latest"], 2)
        self.assertTrue(result["update_available"])
        self.assertEqual(result["main_version"], 2)
        self.assertTrue(result["tag_lapse"])
        self.assertIn("v2", result["diagnostic"])
        self.assertIn("not tagged", result["diagnostic"])
        self.assertIn("not tagged", err)  # loud stderr line, not just a JSON field

        # Persisted for the viewer (item 2) — daily --check writes this.
        state = json.loads((local / "state" / "update_check.json").read_text())
        self.assertEqual(state["main_version"], 2)
        self.assertTrue(state["tag_lapse"])
        self.assertIn("checked_at", state)

    def test_tag_lapse_diagnostic_persists_under_quiet(self):
        # The daily flow runs --check --quiet; the cache still has to be
        # written even though quiet mode only communicates via exit code.
        remote = self._make_lapsed_remote()
        local = self._make_local(current_version=1)
        self._git(local, "remote", "add", "upstream", str(remote))

        out, err, exit_code = self._run_check(quiet=True)

        self.assertEqual(exit_code, 1)  # update available
        self.assertEqual(out, "")
        state = json.loads((local / "state" / "update_check.json").read_text())
        self.assertTrue(state["tag_lapse"])
        self.assertEqual(state["latest"], 2)

    def test_no_tag_lapse_when_main_matches_latest_tag(self):
        remote = self.tmp / "gh" / "lifehug" / "lifehug"
        self._init_repo(remote)
        self._write_version(remote, 1)
        self._git(remote, "add", "-A")
        self._git(remote, "commit", "-q", "-m", "v1")
        self._git(remote, "tag", "-a", "v1", "-m", "v1")
        local = self._make_local(current_version=1)
        self._git(local, "remote", "add", "upstream", str(remote))

        out, _err, _exit = self._run_check(quiet=False)
        result = json.loads(out)
        self.assertFalse(result["tag_lapse"])
        self.assertIsNone(result["diagnostic"])
        self.assertFalse(result["update_available"])
        self.assertEqual(result["main_version"], 1)

    def test_network_failure_falls_back_to_tags_only_silently(self):
        # A remote whose URL matches but whose path is unreachable (network
        # down / repo deleted) must degrade to the pre-existing tags-only
        # behavior without raising and without a false diagnostic.
        local = self._make_local(current_version=1)
        unreachable = self.tmp / "gh" / "lifehug" / "lifehug"  # never created
        self._git(local, "remote", "add", "upstream", str(unreachable))

        out, err, exit_code = self._run_check(quiet=False)

        self.assertIsNone(exit_code)
        result = json.loads(out)
        self.assertIsNone(result["main_version"])
        self.assertFalse(result["tag_lapse"])
        self.assertIsNone(result["diagnostic"])
        self.assertEqual(result["latest"], 0)  # no tags reachable either
        self.assertNotIn("not tagged", err)

    def test_no_upstream_remote_is_tags_only(self):
        self._make_local(current_version=1)  # no remote configured at all

        out, _err, _exit = self._run_check(quiet=False)
        result = json.loads(out)
        self.assertIsNone(result["main_version"])
        self.assertFalse(result["tag_lapse"])
        self.assertIsNone(result["diagnostic"])


class LastUpdateStateTests(unittest.TestCase):
    """cmd_apply records the changelogs it crossed (lifehug#84 item 4)."""

    def setUp(self):
        import tempfile
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: __import__("shutil").rmtree(self.tmp, ignore_errors=True))
        self._orig = (update.REPO_DIR, update.VERSION_FILE)
        update.REPO_DIR = self.tmp
        update.VERSION_FILE = self.tmp / "system" / "version.json"
        self.addCleanup(self._restore)
        self._git("init", "-q")
        self._git("config", "user.email", "t@test")
        self._git("config", "user.name", "t")
        self._git("config", "commit.gpgsign", "false")

    def _restore(self):
        update.REPO_DIR, update.VERSION_FILE = self._orig

    def _git(self, *args):
        subprocess.run(["git", "-C", str(self.tmp), *args], check=True, capture_output=True, text=True)

    def _write(self, rel, data):
        p = self.tmp / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(data if isinstance(data, str) else json.dumps(data))
        return p

    def _tag_version(self, version):
        framework_files = ["system/version.json"]
        self._write("system/version.json", json.dumps({
            "version": version,
            "changelog": f"v{version}: change {version}",
            "framework_files": framework_files,
        }) + "\n")
        self._git("add", "-A")
        self._git("commit", "-q", "-m", f"v{version}")
        # get_tag_changelog reads the tag ANNOTATION, not version.json's field.
        self._git("tag", "-a", f"v{version}", "-m", f"v{version}: change {version}")

    def test_collect_crossed_changelogs_spans_a_multi_version_jump(self):
        for v in (1, 2, 3):
            self._tag_version(v)
        crossed = update.collect_crossed_changelogs(1, 3)
        self.assertEqual([c["version"] for c in crossed], [2, 3])
        self.assertIn("v2: change 2", crossed[0]["changelog"])
        self.assertIn("v3: change 3", crossed[1]["changelog"])

    def test_apply_writes_last_update_state_with_crossed_changelogs(self):
        for v in (1, 2, 3):
            self._tag_version(v)
        # Roll the local checkout back to v1 (stale), matching apply_version's
        # own dirty-check expectations (clean tree, framework files committed).
        self._write("system/version.json", json.dumps({
            "version": 1, "framework_files": ["system/version.json"],
        }) + "\n")
        self._git("add", "-A")
        self._git("commit", "-q", "-m", "stale")

        args = argparse.Namespace(version=None)
        with contextlib.redirect_stdout(io.StringIO()):
            update.cmd_apply(args)

        state = json.loads((self.tmp / "state" / "last_update.json").read_text())
        self.assertEqual(state["from_version"], 1)
        self.assertEqual(state["to_version"], 3)
        self.assertEqual([c["version"] for c in state["crossed"]], [2, 3])
        self.assertIn("applied_at", state)


if __name__ == "__main__":
    unittest.main()
