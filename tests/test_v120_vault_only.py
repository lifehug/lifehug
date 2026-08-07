"""v120 / issue #64 — installed framework against a data-only vault."""

from __future__ import annotations

import hashlib
import json
import os
import re
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
        vault_paths._reset_process_binding_for_tests()
        self.tmp = Path(tempfile.mkdtemp(prefix="lifehug-v120-contract-", dir=ROOT.parent))

    def tearDown(self):
        vault_paths._reset_process_binding_for_tests()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_versioned_contract_is_the_exported_path_and_schema_authority(self):
        raw = json.loads((SYSTEM / "vault_contract.json").read_text(encoding="utf-8"))
        exported = vault_paths.exported_contract()
        self.assertEqual(vault_paths.VAULT_CONTRACT, exported)
        self.assertEqual(vault_paths.VAULT_DATA_PATHS, exported["data_paths"])
        self.assertEqual(set(vault_paths.VAULT_DATA_PATHS), EXPECTED_DATA_PATHS)
        self.assertEqual(vault_paths.FRAMEWORK_PATHS, exported["framework_paths"])
        self.assertEqual(list(exported["data_paths"]), sorted(exported["data_paths"]))
        self.assertEqual(list(exported["framework_paths"]), sorted(exported["framework_paths"]))
        self.assertEqual(exported["identity"]["framework_version"], 120)
        self.assertEqual(
            exported["identity"]["content_digest"],
            vault_paths._contract_digest(exported),
        )
        self.assertEqual(
            vault_paths.MINIMUM_VAULT_SHAPE,
            ("question_bank", "rotation", "coverage"),
        )
        self.assertEqual(
            {
                name: exported["data_paths"][name]["external_path"]
                for name in vault_paths.MINIMUM_VAULT_SHAPE
            },
            {
                "question_bank": "question-bank.md",
                "rotation": "state/rotation.json",
                "coverage": "state/coverage.json",
            },
        )
        for entry in exported["data_paths"].values():
            self.assertIn("external_path", entry)
            self.assertIn("embedded_path", entry)
            self.assertEqual(entry["classification"], "durable_data")
            self.assertIn(entry["schema"]["validation_policy"], {"blocking", "deferred", "opaque"})
            self.assertIn("required_keys", entry["schema"])
            self.assertEqual(entry["schema"]["unknown_fields"], "allow")
        self.assertEqual(vault_paths.STATE_SCHEMA_TABLE["rotation"]["supported_versions"], [1])
        self.assertEqual(vault_paths.STATE_SCHEMA_TABLE["coverage"]["supported_versions"], [1])
        self.assertEqual(raw["external_forbidden_paths"], ["system", "templates"])
        serialized = json.dumps(exported, sort_keys=True)
        self.assertNotIn(str(ROOT), serialized)
        self.assertNotIn("hosted", serialized.lower())
        self.assertEqual(exported["special_file_policy"]["symlinks"], "reject")
        self.assertEqual(
            vault_paths.classify_contract_path(
                "state/rotation.json", authority="vault", layout="external"
            ),
            "durable_data",
        )
        self.assertEqual(
            vault_paths.classify_contract_path("system/lifehug.py", authority="framework"),
            "framework",
        )
        self.assertEqual(
            vault_paths.classify_contract_path("mystery.bin", authority="vault"),
            "unknown",
        )

        core = (SYSTEM / "lifehug_core.py").read_text(encoding="utf-8")
        self.assertEqual(set(re.findall(r'_data\("([^"]+)"\)', core)), EXPECTED_DATA_PATHS)

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
        self.assertEqual(vault_paths.bind_vault_root(explicit), explicit.resolve())
        self.assertEqual(vault_paths.bind_vault_root(explicit), explicit.resolve())
        with self.assertRaisesRegex(RuntimeError, "already bound.*start a new process"):
            vault_paths.bind_vault_root(environment)

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

        invalid_keys = make_vault(self.tmp / "invalid-keys")
        (invalid_keys / "state" / "coverage.json").write_text(
            '{"version": 1, "last_updated": null}\n'
        )
        with self.assertRaisesRegex(ValueError, "invalid required key categories"):
            vault_paths.resolve_vault_root(invalid_keys)

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

    def test_no_follow_io_rejects_traversal_special_files_and_deterministic_swaps(self):
        vault = make_vault(self.tmp / "secure-vault")
        outside = self.tmp / "outside"
        outside.mkdir()
        outside_file = outside / "target.txt"
        outside_file.write_text("outside stays untouched\n", encoding="utf-8")

        target = vault / "state" / "target.txt"
        vault_paths.atomic_write_vault_text(target, "original\n", vault_root=vault)
        self.assertEqual(
            vault_paths.read_vault_text("state/target.txt", vault_root=vault),
            "original\n",
        )
        with self.assertRaisesRegex(ValueError, "escaped"):
            vault_paths.read_vault_text("../outside/target.txt", vault_root=vault)
        with self.assertRaisesRegex(ValueError, "escaped"):
            vault_paths.atomic_write_vault_text(
                outside_file.resolve(), "escape\n", vault_root=vault
            )

        def swap_final_before_read() -> None:
            target.unlink()
            target.symlink_to(outside_file)

        with self.assertRaisesRegex(ValueError, "symlink"):
            vault_paths.read_vault_text(
                target,
                vault_root=vault,
                _before_final_open=swap_final_before_read,
            )
        self.assertEqual(outside_file.read_text(encoding="utf-8"), "outside stays untouched\n")
        target.unlink()
        target.write_text("original\n", encoding="utf-8")

        def swap_final_before_write() -> None:
            target.unlink()
            target.symlink_to(outside_file)

        with self.assertRaisesRegex(ValueError, "regular file"):
            vault_paths.atomic_write_vault_text(
                target,
                "must not escape\n",
                vault_root=vault,
                _before_replace=swap_final_before_write,
            )
        self.assertEqual(outside_file.read_text(encoding="utf-8"), "outside stays untouched\n")
        target.unlink()
        target.write_text("original\n", encoding="utf-8")

        original_state = vault / "state-original"

        def swap_parent_before_write() -> None:
            (vault / "state").rename(original_state)
            (vault / "state").symlink_to(outside, target_is_directory=True)

        with self.assertRaisesRegex(ValueError, "binding changed"):
            vault_paths.atomic_write_vault_text(
                target,
                "must not escape\n",
                vault_root=vault,
                _before_replace=swap_parent_before_write,
            )
        self.assertFalse((outside / "target.txt.tmp").exists())
        self.assertEqual(outside_file.read_text(encoding="utf-8"), "outside stays untouched\n")
        (vault / "state").unlink()
        original_state.rename(vault / "state")

        fifo = vault / "state" / "forbidden.fifo"
        os.mkfifo(fifo)
        with self.assertRaisesRegex(ValueError, "forbidden special"):
            vault_paths.walk_vault_tree(vault)
        fifo.unlink()

        rows = vault_paths.walk_vault_tree(vault)
        self.assertEqual([row["path"] for row in rows], sorted(row["path"] for row in rows))
        self.assertTrue(all(row["classification"] in {"durable_data", "unknown"} for row in rows))

        vault_paths.bind_vault_root(vault)
        original_vault = self.tmp / "secure-vault-original"
        vault.rename(original_vault)
        make_vault(vault)
        with self.assertRaisesRegex(ValueError, "root identity changed"):
            vault_paths.read_vault_text("question-bank.md", vault_root=vault)

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
        direct_writers: list[str] = []
        authority_escapes: list[str] = []
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
                if re.search(
                    r'(?:REPO_DIR|VAULT_ROOT)\s*/\s*["\'](?:state|answers|outputs|sources|wiki)',
                    text,
                ):
                    offenders.append(relative)
            if path.name not in {"lifehug_core.py", "update.py", "vault_paths.py"} and re.search(
                r"\.(?:write_text|write_bytes|open)\(", text
            ):
                direct_writers.append(relative)
            if path.name != "update.py" and re.search(
                r"Path\(REPO_DIR\)|REPO_DIR\.(?:joinpath|open|read_text|read_bytes|write_text|write_bytes|unlink|mkdir|touch)",
                text,
            ):
                authority_escapes.append(relative)
        self.assertEqual(hosted_readers, [], "hosted marker must not affect OSS runtime")
        self.assertEqual(offenders, [], "runtime modules must import the vault authority")
        self.assertEqual(direct_writers, [], "vault writes must use the no-follow I/O authority")
        self.assertEqual(authority_escapes, [], "runtime paths must preserve VaultPath authority")

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

        quoted = make_vault(self.tmp / "vault with spaces and 'quotes'")
        stub_dir = self.tmp / "stub bin"
        stub_dir.mkdir()
        stub_log = self.tmp / "python argv.jsonl"
        stub = stub_dir / "python3"
        stub.write_text(
            f"#!{sys.executable}\n"
            "import json, os, sys\n"
            "with open(os.environ['STUB_LOG'], 'a', encoding='utf-8') as handle:\n"
            "    handle.write(json.dumps(sys.argv[1:]) + '\\n')\n"
            "if len(sys.argv) >= 5 and sys.argv[1].endswith('vault_paths.py') and sys.argv[2] == 'root':\n"
            "    print(sys.argv[4])\n"
            "    raise SystemExit(0)\n"
            "raise SystemExit(23)\n",
            encoding="utf-8",
        )
        stub.chmod(0o755)
        caller_cwd = self.tmp / "unrelated caller cwd"
        caller_cwd.mkdir()
        framework_before = tree_digest(SYSTEM)
        for name in (
            "daily_question.sh",
            "weekly_maintenance.sh",
            "monthly_research.sh",
            "compile_and_commit.sh",
            "file_answer_bg.sh",
        ):
            stub_log.unlink(missing_ok=True)
            env = os.environ.copy()
            env.update({
                "WORKSPACE": str(quoted),
                "PATH": f"{stub_dir}{os.pathsep}{env['PATH']}",
                "STUB_LOG": str(stub_log),
            })
            args = ["/bin/bash", str(SYSTEM / name)]
            if name == "file_answer_bg.sh":
                args.append("A1")
            result = subprocess.run(
                args,
                input="synthetic answer\n",
                capture_output=True,
                text=True,
                env=env,
                cwd=caller_cwd,
                timeout=10,
            )
            self.assertNotEqual(result.returncode, 0, name)
            first = json.loads(stub_log.read_text(encoding="utf-8").splitlines()[0])
            self.assertEqual(
                first,
                [str(SYSTEM / "vault_paths.py"), "root", "--vault-root", str(quoted)],
                name,
            )
        self.assertEqual(tree_digest(SYSTEM), framework_before)


class ExternalVaultSubprocessTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="lifehug-v120-smoke-", dir=ROOT.parent))
        self.framework = self.tmp / "framework"
        shutil.copytree(SYSTEM, self.framework / "system", ignore=shutil.ignore_patterns("__pycache__"))
        shutil.copytree(ROOT / "templates", self.framework / "templates")
        self.script = self.framework / "system" / "lifehug.py"
        self.caller_cwd = self.tmp / "cwd independent of framework and vault"
        self.caller_cwd.mkdir()
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
        self.env.pop("PYTHONPATH", None)
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
            cwd=self.caller_cwd,
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
            "--commit",
            input_text="A bright synthetic kitchen and a red toy train.\n",
        )
        self.assertIn("process-answer job succeeded", filed.stdout)
        committed = subprocess.run(
            ["git", "diff-tree", "--no-commit-id", "--name-only", "-r", "HEAD"],
            cwd=self.vault,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.splitlines()
        self.assertEqual(
            committed,
            [
                "answers/A1.md",
                "question-bank.md",
                "state/answer_scores.json",
                "state/coverage.json",
                "state/rotation.json",
                "state/source_manifest.json",
            ],
        )
        self.assertFalse(any(path.startswith("state/jobs/") for path in committed))
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
            cwd=self.caller_cwd,
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

        changed = subprocess.run(
            ["git", "status", "--porcelain=v1", "-uall"],
            cwd=self.vault,
            check=True,
            capture_output=True,
            text=True,
        ).stdout
        self.assertTrue(changed)
        self.assertNotIn(" system/", changed)
        self.assertNotIn(" vault/system/", changed)
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

        post_subcommand = self.run_cli(
            "status", "--vault-root", str(self.framework), env=hostile_env
        )
        self.assertEqual(post_subcommand.returncode, 0, post_subcommand.stderr)
        self.assertEqual(post_subcommand.stdout, embedded.stdout)

        equals_form = self.run_cli(
            "status", f"--vault-root={self.framework}", env=hostile_env
        )
        self.assertEqual(equals_form.returncode, 0, equals_form.stderr)
        self.assertEqual(equals_form.stdout, embedded.stdout)

        selected_environment = self.run_cli("status", env=hostile_env)
        self.assertEqual(selected_environment.returncode, 0, selected_environment.stderr)
        self.assertIn("Total: 1/1", selected_environment.stdout)

        contract = subprocess.run(
            [sys.executable, str(self.framework / "system" / "vault_paths.py"), "contract"],
            cwd=self.caller_cwd,
            env=self.env,
            capture_output=True,
            text=True,
            timeout=10,
        )
        self.assertEqual(contract.returncode, 0, contract.stderr)
        contract_value = json.loads(contract.stdout)
        self.assertNotIn(str(self.framework), json.dumps(contract_value))
        self.assertNotIn(str(self.vault), json.dumps(contract_value))

    def test_same_process_vault_switch_and_hostile_worker_root_reject(self):
        program = """
import importlib
import os
import sys
sys.path.insert(0, sys.argv[1])
os.environ['LIFEHUG_FRAMEWORK_SYSTEM_DIR'] = sys.argv[1]
os.environ['LIFEHUG_VAULT_ROOT'] = sys.argv[2]
import lifehug_core
assert str(lifehug_core.REPO_DIR) == sys.argv[2]
os.environ['LIFEHUG_VAULT_ROOT'] = sys.argv[3]
try:
    importlib.reload(lifehug_core)
except RuntimeError as exc:
    assert 'already bound' in str(exc)
else:
    raise SystemExit('unsafe in-process vault switch was accepted')
print('rebind rejected')
"""
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                program,
                str(self.framework / "system"),
                str(self.vault),
                str(self.other_vault),
            ],
            cwd=self.caller_cwd,
            env={"PATH": self.env["PATH"], "PYTHONDONTWRITEBYTECODE": "1"},
            capture_output=True,
            text=True,
            timeout=10,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("rebind rejected", result.stdout)

        root_link = self.tmp / "hostile worker root"
        root_link.symlink_to(self.vault, target_is_directory=True)
        hostile_env = self.env.copy()
        hostile_env["LIFEHUG_VAULT_ROOT"] = str(root_link)
        child = subprocess.run(
            [sys.executable, str(self.framework / "system" / "job_execute.py")],
            input='{"arguments": ["status"], "stdin_text": null}',
            cwd=self.caller_cwd,
            env=hostile_env,
            capture_output=True,
            text=True,
            timeout=10,
        )
        self.assertEqual(child.returncode, 77, child.stderr)
        self.assertEqual(tree_digest(self.framework), self.framework_before)

    def test_post_bind_symlinked_source_is_never_followed(self):
        outside = self.tmp / "outside-source.md"
        outside.write_text("outside sentinel must stay private\n", encoding="utf-8")
        program = """
import os
import sys
from pathlib import Path
sys.path.insert(0, os.environ['LIFEHUG_FRAMEWORK_SYSTEM_DIR'])
from lifehug_core import REPO_DIR, SOURCES_DIR, VaultPath
import classify_story
import wiki_compile

outside = Path(os.environ['LIFEHUG_TEST_OUTSIDE_SOURCE'])
SOURCES_DIR.mkdir(parents=True, exist_ok=True)
(SOURCES_DIR / 'post-bind.md').symlink_to(outside)
assert isinstance(REPO_DIR, VaultPath)
assert isinstance(REPO_DIR / 'sources' / 'post-bind.md', VaultPath)
try:
    wiki_compile.read_manual_sources()
except ValueError as exc:
    assert 'symlink' in str(exc)
else:
    raise SystemExit('post-bind source symlink was followed')
try:
    classify_story.cmd_prompt(type('Args', (), {'prompt_file': 'sources/post-bind.md'})())
except ValueError as exc:
    assert 'symlink' in str(exc)
else:
    raise SystemExit('post-bind classify prompt symlink was followed')
"""
        env = self.env.copy()
        env["LIFEHUG_TEST_OUTSIDE_SOURCE"] = str(outside)
        result = subprocess.run(
            [sys.executable, "-c", program],
            cwd=self.caller_cwd,
            env=env,
            capture_output=True,
            text=True,
            timeout=10,
        )
        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)


if __name__ == "__main__":
    unittest.main()
