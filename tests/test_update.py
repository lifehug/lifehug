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
import os
import subprocess
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "system"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from tempdirs import symlink_free_tmp  # noqa: E402
import update  # noqa: E402
import vault_paths  # noqa: E402


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
        self._git("init", "-q", "-b", "main")
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
        self._git(repo, "init", "-q", "-b", "main")
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
        # `latest` keeps its v131, TAGS-ONLY meaning exactly (merge-gate
        # finding 4/9) — existing callers (CLAUDE.md's session-start check,
        # any script parsing this JSON) must not see it silently change
        # meaning. `available_version` is the new, additive "true latest".
        self.assertEqual(result["latest"], 1)
        self.assertEqual(result["available_version"], 2)
        self.assertTrue(result["update_available"])
        self.assertEqual(result["main_version"], 2)
        self.assertTrue(result["tag_lapse"])
        self.assertIn("v2", result["diagnostic"])
        self.assertIn("not tagged", result["diagnostic"])
        self.assertIn("not tagged", err)  # loud stderr line, not just a JSON field

        # Persisted for the viewer (item 2) — daily --check writes this.
        state = json.loads((local / "state" / "update_check.json").read_text())
        self.assertEqual(state["latest"], 1)
        self.assertEqual(state["available_version"], 2)
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
        self.assertEqual(state["latest"], 1)
        self.assertEqual(state["available_version"], 2)

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
        self.assertEqual(result["latest"], 1)
        self.assertEqual(result["available_version"], 1)

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
        self.assertEqual(result["available_version"], 0)
        self.assertNotIn("not tagged", err)

    def test_no_upstream_remote_is_tags_only(self):
        self._make_local(current_version=1)  # no remote configured at all

        out, _err, _exit = self._run_check(quiet=False)
        result = json.loads(out)
        self.assertIsNone(result["main_version"])
        self.assertFalse(result["tag_lapse"])
        self.assertIsNone(result["diagnostic"])

    def test_latest_field_is_a_backward_compatible_tags_only_pin(self):
        # Explicit v131-compat pin (merge-gate finding 4/9): a plain,
        # unremarkable tag bump with no lapse and no remote at all must
        # report EXACTLY what v131 reported — `latest` == the tag ceiling,
        # nothing more — so any existing script parsing this JSON never
        # observes a behavior change.
        local = self._make_local(current_version=1)
        self._git(local, "tag", "-a", "v1", "-m", "v1")
        self._write_version(local, 2)
        self._git(local, "add", "-A")
        self._git(local, "commit", "-q", "-m", "v2")
        self._git(local, "tag", "-a", "v2", "-m", "v2 changelog")
        update.VERSION_FILE.write_text(json.dumps({"version": 1}) + "\n")  # local stays at v1

        out, _err, _exit = self._run_check(quiet=False)
        result = json.loads(out)
        self.assertEqual(result["current"], 1)
        self.assertEqual(result["latest"], 2)
        self.assertEqual(result["available_version"], 2)
        self.assertTrue(result["update_available"])
        self.assertIn("v2 changelog", result["changelog"])
        self.assertIsNone(result["main_version"])
        self.assertFalse(result["tag_lapse"])
        self.assertIsNone(result["diagnostic"])


class StateDirResolutionTests(unittest.TestCase):
    """Where update.py's cache lives MUST match where serve_wiki.py's
    vault-rooted STATE_DIR reads (merge-gate finding 1). update.py's own
    REPO_DIR is the FRAMEWORK checkout (correct for git tags/commits) — but
    the documented external layout installs the framework separately from
    the vault, so caching under REPO_DIR there writes somewhere the viewer
    never reads, silently inerting the whole feature forever."""

    def setUp(self):
        self.tmp = symlink_free_tmp(self, prefix="lifehug-update-")
        self._orig = (update.REPO_DIR, update.VERSION_FILE)
        self.addCleanup(self._restore)
        self._orig_env = os.environ.get("LIFEHUG_VAULT_ROOT")
        self.addCleanup(self._restore_env)

    def _restore(self):
        update.REPO_DIR, update.VERSION_FILE = self._orig

    def _restore_env(self):
        if self._orig_env is None:
            os.environ.pop("LIFEHUG_VAULT_ROOT", None)
        else:
            os.environ["LIFEHUG_VAULT_ROOT"] = self._orig_env

    def _git(self, repo, *args):
        subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True)

    def _init_repo(self, repo, version=1):
        repo.mkdir(parents=True, exist_ok=True)
        self._git(repo, "init", "-q", "-b", "main")
        self._git(repo, "config", "user.email", "t@test")
        self._git(repo, "config", "user.name", "t")
        self._git(repo, "config", "commit.gpgsign", "false")
        vf = repo / "system" / "version.json"
        vf.parent.mkdir(parents=True, exist_ok=True)
        vf.write_text(json.dumps({"version": version, "framework_files": ["system/version.json"]}) + "\n")
        self._git(repo, "add", "-A")
        self._git(repo, "commit", "-q", "-m", f"v{version}")

    def test_vault_root_arg_beats_env_beats_repo_dir(self):
        # Same precedence as cmd_migrate_vault, exactly.
        framework_checkout = self.tmp / "framework"
        self._init_repo(framework_checkout)
        update.REPO_DIR = framework_checkout
        update.VERSION_FILE = framework_checkout / "system" / "version.json"

        # No override -> the framework checkout itself (embedded layout).
        self.assertEqual(update.resolve_state_vault_root(None), framework_checkout)

        # LIFEHUG_VAULT_ROOT -> a vault installed SEPARATELY from the
        # framework checkout (the documented external layout).
        external_vault = self.tmp / "external-vault"
        external_vault.mkdir()
        os.environ["LIFEHUG_VAULT_ROOT"] = str(external_vault)
        self.assertEqual(update.resolve_state_vault_root(None), external_vault)

        # --vault-root beats the env var.
        explicit_vault = self.tmp / "explicit-vault"
        explicit_vault.mkdir()
        args = argparse.Namespace(vault_root=str(explicit_vault))
        self.assertEqual(update.resolve_state_vault_root(args), explicit_vault)

    def test_external_layout_check_writes_land_where_serve_wiki_reads(self):
        """The actual proof, not just an assertion of intent: --check's
        cache directory must equal vault_paths.vault_data_path("state", ...)
        computed for the SAME vault root — the exact authority
        lifehug_core's STATE_DIR (which serve_wiki.py reads) is built from."""
        framework_checkout = self.tmp / "framework"
        self._init_repo(framework_checkout)
        self._git(framework_checkout, "tag", "-a", "v1", "-m", "v1")
        update.REPO_DIR = framework_checkout
        update.VERSION_FILE = framework_checkout / "system" / "version.json"

        external_vault = self.tmp / "external-vault"
        external_vault.mkdir()

        args = argparse.Namespace(check=True, quiet=False, apply=False, version=None,
                                   rollback=False, migrate_vault=False,
                                   vault_root=str(external_vault))
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            update.cmd_check(args)

        written = external_vault / "state" / "update_check.json"
        self.assertTrue(written.exists())
        # Nothing leaked into the framework checkout's own state/ directory
        # (the pre-fix bug: the feature would have been silently inert here,
        # not merely misplaced).
        self.assertFalse((framework_checkout / "state" / "update_check.json").exists())

        expected_dir = vault_paths.vault_data_path(
            "state", vault_root=external_vault, framework_system_dir=update.SYSTEM_DIR,
        )
        self.assertEqual(written.parent.resolve(), expected_dir.resolve())

    def test_lifehug_vault_root_env_also_lands_where_serve_wiki_reads(self):
        framework_checkout = self.tmp / "framework"
        self._init_repo(framework_checkout)
        self._git(framework_checkout, "tag", "-a", "v1", "-m", "v1")
        update.REPO_DIR = framework_checkout
        update.VERSION_FILE = framework_checkout / "system" / "version.json"

        external_vault = self.tmp / "external-vault"
        external_vault.mkdir()
        os.environ["LIFEHUG_VAULT_ROOT"] = str(external_vault)

        args = argparse.Namespace(check=True, quiet=False, apply=False, version=None,
                                   rollback=False, migrate_vault=False, vault_root=None)
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            update.cmd_check(args)

        self.assertTrue((external_vault / "state" / "update_check.json").exists())
        self.assertFalse((framework_checkout / "state" / "update_check.json").exists())


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
        self._git("init", "-q", "-b", "main")
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

    def test_apply_refreshes_the_stale_update_check_cache(self):
        # merge-gate finding 3: without this, the viewer's update card keeps
        # announcing an update that was JUST installed until someone happens
        # to run --check again.
        for v in (1, 2, 3):
            self._tag_version(v)
        self._write("system/version.json", json.dumps({
            "version": 1, "framework_files": ["system/version.json"],
        }) + "\n")
        self._git("add", "-A")
        self._git("commit", "-q", "-m", "stale")

        state_dir = self.tmp / "state"
        state_dir.mkdir(parents=True, exist_ok=True)
        cache_path = state_dir / "update_check.json"
        cache_path.write_text(json.dumps({
            "current": 1, "latest": 3, "available_version": 3,
            "update_available": True, "changelog": "v3: change 3",
            "main_version": None, "tag_lapse": False, "diagnostic": None,
            "checked_at": "2026-08-01T00:00:00Z",
        }))

        args = argparse.Namespace(version=None, vault_root=None)
        with contextlib.redirect_stdout(io.StringIO()):
            update.cmd_apply(args)

        state = json.loads(cache_path.read_text())
        self.assertEqual(state["current"], 3)
        self.assertFalse(state["update_available"])  # no longer stale
        self.assertNotEqual(state["checked_at"], "2026-08-01T00:00:00Z")

    def test_rollback_refreshes_the_stale_update_check_cache(self):
        # merge-gate finding 11: cmd_rollback moves `current` too.
        for v in (1, 2):
            self._tag_version(v)

        state_dir = self.tmp / "state"
        state_dir.mkdir(parents=True, exist_ok=True)
        cache_path = state_dir / "update_check.json"
        cache_path.write_text(json.dumps({
            "current": 2, "latest": 2, "available_version": 2,
            "update_available": False, "changelog": None,
            "main_version": None, "tag_lapse": False, "diagnostic": None,
            "checked_at": "2026-08-01T00:00:00Z",
        }))

        args = argparse.Namespace(vault_root=None)
        with contextlib.redirect_stdout(io.StringIO()):
            update.cmd_rollback(args)

        state = json.loads(cache_path.read_text())
        self.assertEqual(state["current"], 1)
        # available_version (2) is now ahead of the rolled-back current (1)
        # again — correctly re-flagged, not left stuck at False.
        self.assertTrue(state["update_available"])


if __name__ == "__main__":
    unittest.main()
