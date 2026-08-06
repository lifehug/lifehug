"""v120 / issue #64 — installed framework against a data-only vault."""

from __future__ import annotations

import hashlib
import json
import os
import signal
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SYSTEM = ROOT / "system"
sys.path.insert(0, str(SYSTEM))

import vault_paths  # noqa: E402


QUESTION_BANK = """# Synthetic Lifehug questions

## A: Origins
- [ ] A1: What is your earliest synthetic memory?
"""

EXPECTED_DATA_PATHS = {
    "agent_tasks",
    "answer_scores",
    "answers",
    "artifact_sources",
    "book_offers",
    "classifications",
    "compile_needed",
    "config",
    "connectors_state",
    "correction_sources",
    "coverage",
    "entity_rosters",
    "focus_recommendations",
    "import_sources",
    "jobs",
    "learning_failures",
    "legacy_focus_recommendations",
    "manual_sources",
    "neighborhoods",
    "outputs",
    "perennials",
    "planner_state",
    "profile",
    "quality_profile",
    "question_bank",
    "question_candidates",
    "question_queue",
    "readme",
    "reports",
    "roadmap",
    "rotation",
    "second_voice_offers",
    "source_lint_findings",
    "source_manifest",
    "sources",
    "state",
    "synthesis",
    "timeline_placements",
    "wiki",
    "wiki_synthesis_cache",
}


def make_vault(root: Path, *, answered: bool = False) -> Path:
    root.mkdir(parents=True)
    state = root / "state"
    state.mkdir()
    bank = QUESTION_BANK.replace("- [ ] A1", "- [x] A1") if answered else QUESTION_BANK
    (root / "question-bank.md").write_text(bank, encoding="utf-8")
    (state / "rotation.json").write_text(
        json.dumps({
            "version": 1,
            "current_pass": 1,
            "pass_names": ["skeleton", "depth", "connections", "polish"],
            "last_question_id": "A1" if answered else None,
            "last_asked_at": None,
            "questions_asked": 1 if answered else 0,
            "questions_answered": 1 if answered else 0,
            "next_question_id": None,
            "focus_frequency": 4,
        }, indent=2) + "\n",
        encoding="utf-8",
    )
    (state / "coverage.json").write_text(
        json.dumps({
            "version": 1,
            "last_updated": None,
            "categories": {
                "A": {
                    "total": 1,
                    "answered": 1 if answered else 0,
                    "status": "green" if answered else "red",
                }
            },
        }, indent=2) + "\n",
        encoding="utf-8",
    )
    return root


def tree_digest(root: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        if path.is_file() and "__pycache__" not in path.parts:
            result[path.relative_to(root).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    return result


class VaultContractTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="lifehug-v120-contract-", dir=ROOT.parent))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_versioned_contract_is_the_exported_path_and_schema_authority(self):
        raw = json.loads((SYSTEM / "vault_contract.json").read_text(encoding="utf-8"))
        self.assertEqual(vault_paths.VAULT_CONTRACT, raw)
        self.assertEqual(vault_paths.VAULT_DATA_PATHS, raw["data_paths"])
        self.assertEqual(set(vault_paths.VAULT_DATA_PATHS), EXPECTED_DATA_PATHS)
        self.assertEqual(vault_paths.FRAMEWORK_PATHS, raw["framework_paths"])
        self.assertEqual(
            vault_paths.MINIMUM_VAULT_SHAPE,
            ("question_bank", "rotation", "coverage"),
        )
        self.assertEqual(
            {name: raw["data_paths"][name]["path"] for name in vault_paths.MINIMUM_VAULT_SHAPE},
            {
                "question_bank": "question-bank.md",
                "rotation": "state/rotation.json",
                "coverage": "state/coverage.json",
            },
        )
        self.assertEqual(vault_paths.STATE_SCHEMA_TABLE["rotation"]["supported"], [1])
        self.assertEqual(vault_paths.STATE_SCHEMA_TABLE["coverage"]["supported"], [1])
        self.assertEqual(raw["external_forbidden_paths"], ["system"])

    def test_precedence_is_explicit_then_environment_then_embedded(self):
        explicit = make_vault(self.tmp / "explicit")
        environment = make_vault(self.tmp / "environment")
        framework = self.tmp / "framework"
        framework_system = framework / "system"
        framework_system.mkdir(parents=True)
        for name in ("question-bank.md", "rotation.json", "coverage.json"):
            shutil.copy2(SYSTEM / name, framework_system / name)

        with mock.patch.dict(os.environ, {"LIFEHUG_VAULT_ROOT": str(environment)}):
            self.assertEqual(
                vault_paths.resolve_vault_root(explicit, framework_system_dir=framework_system),
                explicit.resolve(),
            )
            self.assertEqual(
                vault_paths.resolve_vault_root(framework_system_dir=framework_system),
                environment.resolve(),
            )
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertEqual(
                vault_paths.resolve_vault_root(framework_system_dir=framework_system),
                framework.resolve(),
            )

    def test_missing_invalid_forbidden_and_symlinked_shapes_fail_before_write(self):
        missing = self.tmp / "missing"
        missing.mkdir()
        before = set(missing.rglob("*"))
        with self.assertRaisesRegex(ValueError, "missing required question_bank"):
            vault_paths.resolve_vault_root(missing)
        self.assertEqual(set(missing.rglob("*")), before)

        invalid = make_vault(self.tmp / "invalid")
        (invalid / "state" / "rotation.json").write_text('{"version": 999}\n')
        with self.assertRaisesRegex(ValueError, "unsupported schema"):
            vault_paths.resolve_vault_root(invalid)

        forbidden = make_vault(self.tmp / "forbidden")
        (forbidden / "system").mkdir()
        with self.assertRaisesRegex(ValueError, "may not contain system"):
            vault_paths.resolve_vault_root(forbidden)

        valid = make_vault(self.tmp / "valid")
        root_link = self.tmp / "root-link"
        root_link.symlink_to(valid, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, "symlink"):
            vault_paths.resolve_vault_root(root_link)

        nested_parent = self.tmp / "nested-parent"
        nested_parent.mkdir()
        nested_vault = make_vault(nested_parent / "vault")
        parent_link = self.tmp / "parent-link"
        parent_link.symlink_to(nested_parent, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, "symlink"):
            vault_paths.resolve_vault_root(parent_link / nested_vault.name)

        escaped = self.tmp / "escaped"
        escaped.mkdir()
        state_link = make_vault(self.tmp / "state-link")
        shutil.rmtree(state_link / "state")
        (state_link / "state").symlink_to(escaped, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, "symlink"):
            vault_paths.resolve_vault_root(state_link)

        file_link = make_vault(self.tmp / "file-link")
        rotation = file_link / "state" / "rotation.json"
        rotation.unlink()
        outside_rotation = self.tmp / "outside-rotation.json"
        outside_rotation.write_text('{"version": 1}\n')
        rotation.symlink_to(outside_rotation)
        with self.assertRaisesRegex(ValueError, "symlink"):
            vault_paths.resolve_vault_root(file_link)

    def test_external_data_and_framework_assets_resolve_to_disjoint_roots(self):
        vault = make_vault(self.tmp / "vault")
        self.assertEqual(
            vault_paths.vault_data_path("question_bank", vault_root=vault),
            vault.resolve() / "question-bank.md",
        )
        self.assertEqual(
            vault_paths.vault_data_path("rotation", vault_root=vault),
            vault.resolve() / "state" / "rotation.json",
        )
        templates = vault_paths.framework_path("templates")
        self.assertTrue(templates.is_relative_to(ROOT.resolve()))
        self.assertFalse(templates.is_relative_to(vault.resolve()))

    def test_runtime_guard_rejects_competing_root_derivations_and_hosted_marker(self):
        offenders: list[str] = []
        hosted_readers: list[str] = []
        for path in sorted(SYSTEM.rglob("*.py")):
            if "__pycache__" in path.parts:
                continue
            text = path.read_text(encoding="utf-8")
            relative = path.relative_to(ROOT).as_posix()
            if "state/hosted.json" in text or '"hosted.json"' in text or "'hosted.json'" in text:
                hosted_readers.append(relative)
            if path.name != "update.py":
                if "Path(__file__).parent.parent" in text or "Path(__file__).resolve().parents[1]" in text:
                    offenders.append(relative)
                if "REPO_DIR = SYSTEM_DIR.parent" in text or "REPO_DIR = _SYSTEM_DIR.parent" in text:
                    offenders.append(relative)
        self.assertEqual(hosted_readers, [], "hosted marker must not affect OSS runtime")
        self.assertEqual(offenders, [], "runtime modules must import the vault authority")

    def test_shell_entrypoints_validate_the_selected_root_before_cd_or_write(self):
        target = make_vault(self.tmp / "shell-target")
        selected = self.tmp / "shell-root-link"
        selected.symlink_to(target, target_is_directory=True)
        before = tree_digest(target)
        for name in (
            "daily_question.sh",
            "weekly_maintenance.sh",
            "monthly_research.sh",
            "compile_and_commit.sh",
            "file_answer_bg.sh",
        ):
            text = (SYSTEM / name).read_text(encoding="utf-8")
            validation = text.index('vault_paths.py" root --vault-root "$WORKSPACE"')
            for needle in ('cd "$WORKSPACE"', 'touch "$WORKSPACE/'):
                if needle in text:
                    self.assertLess(validation, text.index(needle), name)
            env = os.environ.copy()
            env["WORKSPACE"] = str(selected)
            args = ["bash", str(SYSTEM / name)]
            if name == "file_answer_bg.sh":
                args.append("A1")
            result = subprocess.run(
                args,
                input="synthetic answer\n",
                capture_output=True,
                text=True,
                env=env,
                timeout=10,
            )
            self.assertNotEqual(result.returncode, 0, name)
        self.assertEqual(tree_digest(target), before)


class ExternalVaultSubprocessTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="lifehug-v120-smoke-", dir=ROOT.parent))
        self.framework = self.tmp / "framework"
        shutil.copytree(SYSTEM, self.framework / "system", ignore=shutil.ignore_patterns("__pycache__"))
        shutil.copytree(ROOT / "templates", self.framework / "templates")
        self.script = self.framework / "system" / "lifehug.py"
        self.vault = make_vault(self.tmp / "vault")
        self.other_vault = make_vault(self.tmp / "other-vault", answered=True)
        subprocess.run(["git", "init", "-q"], cwd=self.vault, check=True)
        subprocess.run(["git", "config", "user.email", "synthetic@example.invalid"], cwd=self.vault, check=True)
        subprocess.run(["git", "config", "user.name", "Synthetic Fixture"], cwd=self.vault, check=True)
        subprocess.run(["git", "add", "."], cwd=self.vault, check=True)
        subprocess.run(["git", "commit", "-qm", "synthetic baseline"], cwd=self.vault, check=True)
        self.env = os.environ.copy()
        self.env.update({
            "LIFEHUG_FRAMEWORK_SYSTEM_DIR": str(self.framework / "system"),
            "LIFEHUG_VAULT_ROOT": str(self.vault),
            "LIFEHUG_JOB_DRAIN_IDLE": "0.05",
            "LIFEHUG_JOB_POLL_SECONDS": "0.02",
            "PYTHONDONTWRITEBYTECODE": "1",
        })
        self.env.pop("WORKSPACE", None)
        self.framework_before = tree_digest(self.framework)
        for path in self.framework.rglob("*"):
            if path.is_file():
                path.chmod(0o444)

    def tearDown(self):
        for path in self.framework.rglob("*") if self.framework.exists() else ():
            if path.is_file():
                path.chmod(0o644)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def run_cli(
        self,
        *args: str,
        input_text: str | None = None,
        env: dict[str, str] | None = None,
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(self.script), *args],
            input=input_text,
            capture_output=True,
            text=True,
            env=env or self.env,
            timeout=30,
        )

    def assert_cli_ok(self, *args: str, input_text: str | None = None) -> subprocess.CompletedProcess[str]:
        result = self.run_cli(*args, input_text=input_text)
        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
        return result

    def test_data_only_vault_runs_read_write_queue_compile_and_viewer_flows(self):
        status = self.assert_cli_ok("status")
        self.assertIn("Total: 0/1", status.stdout)
        lint = self.assert_cli_ok("source-lint", "--no-write-findings")
        self.assertIn("0 error(s)", lint.stdout)

        filed = self.assert_cli_ok(
            "process-answer",
            "A1",
            "--no-compile-wiki",
            input_text="A bright synthetic kitchen and a red toy train.\n",
        )
        self.assertIn("process-answer job succeeded", filed.stdout)
        compiled = self.assert_cli_ok("compile", "--no-ai")
        self.assertIn("compile job succeeded", compiled.stdout)

        records = [
            json.loads(path.read_text(encoding="utf-8"))
            for path in (self.vault / "state" / "jobs").glob("[0-9a-f]*.json")
        ]
        self.assertGreaterEqual(len(records), 2)
        self.assertTrue(all(record["state"] == "succeeded" for record in records))

        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
        viewer = subprocess.Popen(
            [sys.executable, str(self.script), "serve", "--port", str(port)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=self.env,
            start_new_session=True,
        )
        try:
            body = ""
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline:
                try:
                    with urllib.request.urlopen(f"http://localhost:{port}/", timeout=1) as response:
                        body = response.read().decode("utf-8")
                    break
                except (OSError, urllib.error.URLError):
                    if viewer.poll() is not None:
                        break
                    time.sleep(0.05)
            self.assertIsNone(viewer.poll(), "viewer exited before serving the vault")
            self.assertIn("Lifehug", body)
            self.assertIn("Origins", body)
        finally:
            if viewer.poll() is None:
                os.killpg(viewer.pid, signal.SIGTERM)
            try:
                viewer.communicate(timeout=5)
            except subprocess.TimeoutExpired:
                os.killpg(viewer.pid, signal.SIGKILL)
                viewer.communicate(timeout=5)

        self.assertFalse((self.vault / "system").exists())
        self.assertEqual(list(self.vault.rglob("*.py")), [])
        self.assertFalse((self.vault / "templates").exists())
        self.assertTrue((self.vault / "answers" / "A1.md").is_file())
        self.assertTrue((self.vault / "wiki" / "index.md").is_file())

        forbidden = (str(self.vault.resolve()), str(self.framework.resolve()), "vault/system")
        inspectable = {".json", ".jsonl", ".md", ".yaml", ".yml"}
        for path in self.vault.rglob("*"):
            if path.is_file() and ".git" not in path.parts and path.suffix in inspectable:
                text = path.read_text(encoding="utf-8")
                for value in forbidden:
                    self.assertNotIn(value, text, path)

        subprocess.run(["git", "add", "-A"], cwd=self.vault, check=True)
        staged = subprocess.run(
            ["git", "diff", "--cached", "--name-only"],
            cwd=self.vault,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.splitlines()
        self.assertTrue(staged)
        self.assertFalse(any(path == "system" or path.startswith("system/") for path in staged))
        self.assertEqual(tree_digest(self.framework), self.framework_before)

    def test_explicit_cli_root_beats_environment_and_embedded_default_is_identical(self):
        embedded_env = self.env.copy()
        embedded_env.pop("LIFEHUG_VAULT_ROOT", None)
        embedded = self.run_cli("status", env=embedded_env)
        self.assertEqual(embedded.returncode, 0, embedded.stderr)

        hostile_env = self.env.copy()
        hostile_env["LIFEHUG_VAULT_ROOT"] = str(self.other_vault)
        explicit = self.run_cli("--vault-root", str(self.framework), "status", env=hostile_env)
        self.assertEqual(explicit.returncode, 0, explicit.stderr)
        self.assertEqual(explicit.stdout, embedded.stdout)

        selected_environment = self.run_cli("status", env=hostile_env)
        self.assertEqual(selected_environment.returncode, 0, selected_environment.stderr)
        self.assertIn("Total: 1/1", selected_environment.stdout)


if __name__ == "__main__":
    unittest.main()
