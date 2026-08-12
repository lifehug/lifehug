"""v119 / issue #56 — durable local queue, recovery, and single-writer proof."""

from __future__ import annotations

import json
import os
import shutil
import socket
import stat
import subprocess
import sys
import threading
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SYSTEM = ROOT / "system"
sys.path.insert(0, str(SYSTEM))
sys.path.insert(0, str(ROOT / "tests"))

from tempdirs import root_parent_tmp  # noqa: E402
import jobs  # noqa: E402
import lifehug  # noqa: E402
import vault_paths  # noqa: E402


EXPECTED_COMMANDS = frozenset({
    "artifact-assemble",
    "artifact-delivered",
    "artifact-final",
    "artifact-new",
    "artifact-promote",
    "artifact-revise",
    "artifact-save",
    "candidate-promote",
    "candidate-update",
    "compile",
    "compile-pending",
    "conversation-close",
    "daily",
    "file-answer",
    "fix-source",
    "focus-approve",
    "focus-dismiss",
    "monthly",
    "process-answer",
    "reflect-source",
    "second-voice-ack",
    "timeline-place",
    "timeline-unplace",
    "weekly",
})


FAKE_LIFEHUG = r'''#!/usr/bin/env python3
import json
import os
import sys
import time
from pathlib import Path

vault = Path(os.environ["LIFEHUG_VAULT_ROOT"])
state = vault / "state"
state.mkdir(parents=True, exist_ok=True)
control_path = state / "test-control.json"
control = json.loads(control_path.read_text()) if control_path.exists() else {}
active = state / "probe-active"
overlap = state / "probe-overlap"
try:
    active.mkdir()
except FileExistsError:
    overlap.write_text("overlap")
with (state / "probe-events.log").open("a") as handle:
    handle.write("start\n")
time.sleep(float(control.get("sleep", 0.05)))
with (state / "probe-events.log").open("a") as handle:
    handle.write("end\n")
try:
    active.rmdir()
except OSError:
    pass
raise SystemExit(int(control.get("exit_code", 0)))
'''


def make_minimum_vault(root: Path, *, embedded: bool = False) -> None:
    """Create the issue #64 minimum shape used by queue-only fixtures."""
    data_root = root / "system" if embedded else root
    data_root.mkdir(parents=True, exist_ok=True)
    (data_root / "question-bank.md").write_text(
        "# Questions\n\n## A: Origins\n\n- [ ] A1: Test question?\n",
        encoding="utf-8",
    )
    state_root = data_root if embedded else root / "state"
    state_root.mkdir(parents=True, exist_ok=True)
    (state_root / "rotation.json").write_text(json.dumps({
        "version": 1,
        "current_pass": 1,
        "pass_names": ["skeleton", "depth", "connections", "polish"],
        "last_question_id": None,
        "last_asked_at": None,
        "questions_asked": 0,
        "questions_answered": 0,
        "next_question_id": None,
        "focus_frequency": 4,
    }) + "\n", encoding="utf-8")
    (state_root / "coverage.json").write_text(json.dumps({
        "version": 1,
        "last_updated": None,
        "categories": {},
    }) + "\n", encoding="utf-8")


class DurableJobsTests(unittest.TestCase):
    def setUp(self):
        vault_paths._reset_process_binding_for_tests()
        self.tmp = root_parent_tmp(self, ROOT, prefix="lifehug-jobs-test-")
        self.vault = self.tmp / "vault-only"
        make_minimum_vault(self.vault)
        self.framework = self.tmp / "framework" / "system"
        self.framework.mkdir(parents=True)
        (self.framework / "lifehug.py").write_text(FAKE_LIFEHUG, encoding="utf-8")
        self.original_vault = jobs.VAULT_ROOT
        self.original_framework = jobs.FRAMEWORK_SYSTEM_DIR
        jobs.configure(self.vault)
        jobs.FRAMEWORK_SYSTEM_DIR = self.framework

    def tearDown(self):
        jobs.FRAMEWORK_SYSTEM_DIR = self.original_framework
        vault_paths._reset_process_binding_for_tests()
        jobs.configure(self.original_vault)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def control(self, **values) -> None:
        (self.vault / "state" / "test-control.json").write_text(json.dumps(values))

    def worker_process(self, *worker_flags: str) -> subprocess.Popen:
        env = os.environ.copy()
        env["LIFEHUG_FRAMEWORK_SYSTEM_DIR"] = str(self.framework)
        env["LIFEHUG_VAULT_ROOT"] = str(self.vault)
        env["LIFEHUG_JOB_POLL_SECONDS"] = "0.05"
        return subprocess.Popen(
            [sys.executable, str(SYSTEM / "jobs.py"), "worker", *(worker_flags or ("--once",)),
             "--vault-root", str(self.vault)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=env,
        )

    def mark_running(self, record: dict, attempt: str = "a" * 20) -> dict:
        record = dict(record)
        record.update({
            "state": "running",
            "attempt_id": attempt,
            "attempts": 1,
            "started_at": jobs._now(),
            "updated_at": jobs._now(),
            "lease_owner": "dead-owner",
            "lease_expires_at": "2000-01-01T00:00:00Z",
        })
        jobs._write_json(jobs._record_path(record["id"]), record)
        return record

    def recover_under_lease(self) -> list[dict]:
        with jobs._WriterLease(wait_seconds=0.1):
            return jobs.recover_interrupted_jobs()

    def test_exact_allowed_command_registry(self):
        self.assertEqual(jobs.ALLOWED_COMMANDS, EXPECTED_COMMANDS)
        self.assertEqual(set(jobs.COMMANDS), EXPECTED_COMMANDS)

    def test_public_help_lists_only_queue_administration_commands(self):
        help_text = jobs.build_parser().format_help()
        for command in ("worker", "enqueue", "file-answer", "show", "retry", "purge", "cleanup"):
            self.assertIn(command, help_text)
        self.assertNotIn("active", help_text)
        self.assertNotIn("==SUPPRESS==", help_text)

    def test_only_explicit_identity_deduplicates(self):
        first = jobs.enqueue("compile", {"no_ai": True}, kick=False)
        again = jobs.enqueue("compile", {"no_ai": True}, kick=False)
        stable = jobs.enqueue("compile", {"no_ai": True}, identity="schedule:one", kick=False)
        duplicate = jobs.enqueue("compile", {"no_ai": True}, identity="schedule:one", kick=False)
        self.assertNotEqual(first["id"], again["id"])
        self.assertEqual(stable["id"], duplicate["id"])

        stable.update({"state": "succeeded", "updated_at": jobs._now()})
        jobs._write_json(jobs._record_path(stable["id"]), stable)
        fresh_after_terminal = jobs.enqueue("compile", {"no_ai": True}, kick=False)
        self.assertNotEqual(fresh_after_terminal["id"], stable["id"])
        self.assertEqual(
            jobs.enqueue("compile", {"no_ai": True}, identity="schedule:one", kick=False)["id"],
            stable["id"],
        )

    def test_duplicate_runnable_identity_kicks_again(self):
        record = jobs.enqueue("compile", {}, identity="retry-kick", kick=False)
        with mock.patch.object(jobs, "_kick_worker") as kick:
            duplicate = jobs.enqueue("compile", {}, identity="retry-kick", kick=True)
        self.assertEqual(duplicate["id"], record["id"])
        kick.assert_called_once_with()

    def test_no_kick_mode_drains_supervised_without_detached_worker(self):
        with mock.patch.dict(os.environ, {"LIFEHUG_JOBS_NO_KICK": "1"}):
            with mock.patch.object(jobs, "_kick_worker") as kick:
                record = jobs.enqueue(
                    "compile",
                    {"no_ai": True},
                    identity="supervised-no-kick",
                    kick=True,
                )
                finished = jobs.wait_for_job_embedded_safe(record["id"], timeout=5)

        kick.assert_not_called()
        self.assertEqual(finished["state"], "succeeded")
        self.assertIn(
            "start",
            (self.vault / "state" / "probe-events.log").read_text(encoding="utf-8"),
        )

    def test_lifehug_queue_wait_uses_embedded_safe_wait(self):
        record = {"id": "a" * 20}
        finished = {"id": record["id"], "state": "succeeded"}
        with mock.patch.object(jobs, "configure"), \
                mock.patch.object(jobs, "enqueue", return_value=record), \
                mock.patch.object(
                    jobs, "wait_for_job_embedded_safe", return_value=finished
                ) as wait:
            self.assertEqual(lifehug._queue_and_wait("compile", {"no_ai": True}), 0)

        wait.assert_called_once_with(record["id"])

    def test_cold_start_identity_key_is_atomic_across_processes(self):
        cold_vault = self.tmp / "cold-vault"
        make_minimum_vault(cold_vault)
        gate = self.tmp / "cold-start-go"
        program = (
            "import sys,time; from pathlib import Path; "
            f"sys.path.insert(0,{str(SYSTEM)!r}); import jobs; "
            f"jobs.configure(Path({str(cold_vault)!r})); "
            f"gate=Path({str(gate)!r}); "
            "\nwhile not gate.exists(): time.sleep(.005)\n"
            "print(jobs.enqueue('compile',{},identity='same-logical-send',kick=False)['id'])"
        )
        processes = [
            subprocess.Popen(
                [sys.executable, "-c", program],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            for _ in range(2)
        ]
        gate.touch()
        outputs = []
        for process in processes:
            out, err = process.communicate(timeout=10)
            self.assertEqual(process.returncode, 0, err)
            outputs.append(out.strip())
        self.assertEqual(outputs[0], outputs[1])
        key = cold_vault / "state" / "jobs" / ".identity-key"
        payload = cold_vault / "state" / "jobs" / ".payloads" / f"{outputs[0]}.json"
        self.assertEqual(len(key.read_bytes()), 32)
        self.assertEqual(stat.S_IMODE(key.stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(payload.stat().st_mode), 0o600)

    def test_two_process_writers_serialize_in_fixture_vault(self):
        self.control(sleep=0.25)
        jobs.enqueue("compile", {}, identity="writer-a", kick=False)
        jobs.enqueue("compile", {}, identity="writer-b", kick=False)
        workers = [self.worker_process(), self.worker_process()]
        for worker in workers:
            _, err = worker.communicate(timeout=10)
            self.assertEqual(worker.returncode, 0, err)
        self.assertFalse((self.vault / "state" / "probe-overlap").exists())
        events = (self.vault / "state" / "probe-events.log").read_text().splitlines()
        self.assertEqual(events, ["start", "end", "start", "end"])
        states = [
            json.loads(path.read_text())["state"]
            for path in jobs.JOBS_DIR.glob("*.json")
        ]
        self.assertEqual(states, ["succeeded", "succeeded"])

    def test_fallback_drain_waits_behind_long_job_and_converges_next(self):
        self.control(sleep=0.4)
        first = jobs.enqueue("compile", {}, identity="long-a", kick=False)
        first_worker = self.worker_process("--once")
        active = self.vault / "state" / "probe-active"
        deadline = time.time() + 3
        while time.time() < deadline and not active.exists():
            time.sleep(0.01)
        self.assertTrue(active.exists(), "first job never entered its mutation")
        second = jobs.enqueue("compile", {}, identity="behind-b", kick=False)

        env = os.environ.copy()
        env.update({
            "LIFEHUG_FRAMEWORK_SYSTEM_DIR": str(self.framework),
            "LIFEHUG_JOB_DRAIN_LOCK_WAIT": "0.05",
            "LIFEHUG_JOB_DRAIN_IDLE": "0.1",
            "LIFEHUG_JOB_POLL_SECONDS": "0.02",
        })
        drain = subprocess.Popen(
            [sys.executable, str(SYSTEM / "jobs.py"), "worker", "--drain",
             "--vault-root", str(self.vault)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=env,
        )
        for process in (first_worker, drain):
            _, err = process.communicate(timeout=10)
            self.assertEqual(process.returncode, 0, err)
        self.assertEqual(jobs.load_job(first["id"])["state"], "succeeded")
        self.assertEqual(jobs.load_job(second["id"])["state"], "succeeded")

    def test_queued_job_survives_submitter_restart_and_external_layout(self):
        record = jobs.enqueue("compile", {}, kick=False)
        self.assertFalse((self.vault / "system").exists(), "fixture is a vault-only root")
        worker = self.worker_process()
        _, err = worker.communicate(timeout=10)
        self.assertEqual(worker.returncode, 0, err)
        done = jobs.load_job(record["id"])
        self.assertEqual(done["state"], "succeeded")
        self.assertFalse(done["payload_retained"])

    def test_completed_receipt_recovers_without_repeating_mutation(self):
        record = self.mark_running(jobs.enqueue("compile", {}, kick=False))
        jobs._write_json(jobs._receipt_path(record["id"], record["attempt_id"]), {
            "version": 1,
            "job_id": record["id"],
            "attempt_id": record["attempt_id"],
            "exit_code": 0,
            "finished_at": jobs._now(),
        })
        recovered = self.recover_under_lease()
        self.assertEqual(recovered[0]["state"], "succeeded")
        self.assertFalse((self.vault / "state" / "probe-events.log").exists())
        self.assertFalse(jobs.load_job(record["id"])["payload_retained"])

    def test_interrupted_retry_policy_distinguishes_idempotency(self):
        safe = self.mark_running(
            jobs.enqueue("compile", {}, identity="safe", kick=False), attempt="b" * 20
        )
        unsafe = self.mark_running(jobs.enqueue(
            "process-answer", {"question_id": "A1", "answer": "private answer"},
            identity="unsafe", kick=False,
        ), attempt="c" * 20)
        recovered = {row["id"]: row for row in self.recover_under_lease()}
        self.assertEqual(recovered[safe["id"]]["state"], "safely-retryable")
        self.assertTrue(recovered[safe["id"]]["can_retry"])
        self.assertEqual(recovered[unsafe["id"]]["state"], "failed")
        self.assertFalse(recovered[unsafe["id"]]["can_retry"])
        self.assertTrue(recovered[unsafe["id"]]["payload_retained"])
        with self.assertRaisesRegex(ValueError, "not safely retryable"):
            jobs.retry_job(unsafe["id"])

    def test_failed_job_visible_payload_retained_and_safe_manual_retry(self):
        self.control(exit_code=3)
        record = jobs.enqueue("compile", {}, kick=False)
        self.assertTrue(jobs.worker_once(wait_seconds=0.1))
        failed = jobs.load_job(record["id"])
        self.assertEqual(failed["state"], "failed")
        self.assertEqual(failed["exit_code"], 3)
        self.assertEqual(failed["failure_code"], "command_failed")
        self.assertTrue(failed["can_retry"])
        self.assertTrue(failed["payload_retained"])
        with mock.patch.object(jobs, "_kick_worker"):
            retried = jobs.retry_job(record["id"])
        self.assertEqual(retried["state"], "safely-retryable")

    def test_record_and_logs_never_contain_private_payload_or_argv(self):
        phrase = "SECRET answer words that must not enter job metadata"
        record = jobs.enqueue("artifact-save", {
            "ref": "outputs/test-piece", "content": phrase, "note": "private feedback",
        }, kick=False)
        raw_record = jobs._record_path(record["id"]).read_text()
        self.assertNotIn(phrase, raw_record)
        self.assertNotIn("private feedback", raw_record)
        self.assertNotIn("argv", raw_record)
        self.assertNotIn("stdin", raw_record)
        self.assertFalse(list(jobs.JOBS_DIR.glob("*.log")))
        self.assertTrue(jobs.load_job(record["id"])["payload_retained"])

    def test_private_fields_travel_in_stdin_envelope_not_process_argv(self):
        marker = "PRIVATE-MARKER-never-in-ps"
        payloads = (
            ("candidate-update", {"candidate_id": "abc", "status": "deferred", "reason": marker}),
            ("focus-dismiss", {"recommendation_id": "abc", "reason": marker}),
            ("artifact-revise", {"ref": "outputs/piece", "feedback": marker}),
            ("artifact-delivered", {"ref": "outputs/piece", "reaction": marker}),
            ("fix-source", {"ref": "answers/A1.md", "mode": "correct", "right": marker}),
            ("process-answer", {
                "question_id": "A1", "answer": marker, "followups": [marker],
                "summary": marker,
            }),
        )

        class FakeProcess:
            pid = os.getpid()
            returncode = 0

            def __init__(self, argv):
                self.argv = argv
                self.input = None

            def communicate(self, input=None, timeout=None):  # noqa: A002
                self.input = input
                return (None, None)

            def wait(self, timeout=None):
                return 0

        seen = []

        def fake_popen(argv, **_kwargs):
            process = FakeProcess(argv)
            seen.append(process)
            return process

        with mock.patch.object(jobs.subprocess, "Popen", side_effect=fake_popen), \
                mock.patch.object(jobs, "_terminate_process_group"):
            for command, payload in payloads:
                for invocation in jobs.COMMANDS[command].build(payload):
                    rc, _ = jobs._run_invocation(invocation, 1, owner_id="a" * 20)
                    self.assertEqual(rc, 0)
        self.assertTrue(seen)
        for process in seen:
            self.assertNotIn(marker, " ".join(process.argv))
        self.assertTrue(any(marker in (process.input or "") for process in seen))

    def test_retry_safety_registry_contains_only_success_preserving_compile(self):
        retryable = {
            name for name, spec in jobs.COMMANDS.items()
            if spec.retry_safety == "idempotent"
        }
        self.assertEqual(retryable, {"compile"})

    def test_ref_families_reject_symlink_traversal_at_execution(self):
        outside = self.tmp / "outside"
        outside.mkdir()
        cases = (
            ("outputs", "artifact-save", {"ref": "outputs/piece", "content": "x"}),
            ("answers", "reflect-source", {"ref": "answers/A1.md", "body": "x"}),
            ("sources", "fix-source", {
                "ref": "sources/manual/story.md", "mode": "correct", "right": "x",
            }),
        )
        for dirname, command, payload in cases:
            with self.subTest(dirname=dirname):
                target = self.vault / dirname
                if target.exists() or target.is_symlink():
                    if target.is_dir() and not target.is_symlink():
                        shutil.rmtree(target)
                    else:
                        target.unlink()
                target.symlink_to(outside, target_is_directory=True)
                with self.assertRaisesRegex(ValueError, "symlink"):
                    jobs._validate_execution_paths(command, payload)
                target.unlink()

    def test_file_answer_outer_queue_leaves_no_plaintext_temp(self):
        for name in (
            "jobs.py",
            "job_execute.py",
            "vault_contract.json",
            "vault_paths.py",
            "file_answer_bg.sh",
            "format_frameworks.py",
        ):
            shutil.copy2(SYSTEM / name, self.framework / name)
        controlled_tmp = self.tmp / "controlled-tmp"
        controlled_tmp.mkdir()
        self.control(sleep=0.25)
        env = os.environ.copy()
        env.update({
            "LIFEHUG_FRAMEWORK_SYSTEM_DIR": str(self.framework),
            "LIFEHUG_VAULT_ROOT": str(self.vault),
            "WORKSPACE": str(self.vault),
            "TMPDIR": str(controlled_tmp),
            "LIFEHUG_JOB_POLL_SECONDS": "0.02",
        })
        process = subprocess.Popen(
            ["bash", str(self.framework / "file_answer_bg.sh"), "A1"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=env,
        )
        process.stdin.write("private answer body\n")
        process.stdin.close()
        observed_modes = []
        deadline = time.time() + 5
        while process.poll() is None and time.time() < deadline:
            for path in controlled_tmp.glob("lifehug-answer.*"):
                observed_modes.append(stat.S_IMODE(path.stat().st_mode))
            time.sleep(0.01)
        process.wait(timeout=5)
        stderr = process.stderr.read()
        process.stderr.close()
        process.stdout.close()
        self.assertEqual(process.returncode, 0, stderr)
        self.assertTrue(observed_modes, "worker re-entry temp was not observed")
        self.assertEqual(set(observed_modes), {0o600})
        self.assertEqual(list(controlled_tmp.iterdir()), [])

        failed = subprocess.run(
            ["bash", str(self.framework / "file_answer_bg.sh"), "../../bad"],
            input="another private answer",
            capture_output=True,
            text=True,
            env=env,
        )
        self.assertNotEqual(failed.returncode, 0)
        self.assertEqual(list(controlled_tmp.iterdir()), [])

    def test_cleanup_and_owner_purge_preserve_failed_policy(self):
        failed = jobs.enqueue("compile", {}, identity="failed-retained", kick=False)
        failed.update({
            "state": "failed", "failure_code": "command_failed", "exit_code": 1,
            "finished_at": jobs._now(), "updated_at": jobs._now(),
            "can_retry": True, "payload_retained": True,
        })
        jobs._write_json(jobs._record_path(failed["id"]), failed)
        receipt = jobs._receipt_path(failed["id"], "b" * 20)
        jobs._write_json(receipt, {"job_id": failed["id"]})

        succeeded = jobs.enqueue("compile", {}, identity="success-leftover", kick=False)
        succeeded.update({"state": "succeeded", "updated_at": jobs._now()})
        jobs._write_json(jobs._record_path(succeeded["id"]), succeeded)
        orphan_payload = jobs.PAYLOADS_DIR / f"{'c' * 20}.json"
        orphan_receipt = jobs.RECEIPTS_DIR / f"{'d' * 20}-{'e' * 20}.json"
        jobs._write_json(orphan_payload, {"orphan": True})
        jobs._write_json(orphan_receipt, {"orphan": True})
        os.utime(orphan_payload, (0, 0))
        os.utime(orphan_receipt, (0, 0))

        removed = jobs.cleanup_sidecars(grace_seconds=60)
        self.assertFalse(jobs._payload_path(succeeded["id"]).exists())
        self.assertFalse(orphan_payload.exists())
        self.assertFalse(orphan_receipt.exists())
        self.assertTrue(jobs._payload_path(failed["id"]).exists())
        self.assertTrue(receipt.exists())
        self.assertEqual(removed["successful_payloads"], 1)

        purged = jobs.purge_job(failed["id"])
        self.assertFalse(jobs._payload_path(failed["id"]).exists())
        self.assertFalse(receipt.exists())
        self.assertFalse(purged["payload_retained"])
        self.assertTrue(purged["purged_at"])
        self.assertIsNotNone(jobs.load_job(failed["id"]))

    def test_every_canonical_command_has_one_writer_classification(self):
        parser = lifehug.build_parser()
        subparsers = next(
            action for action in parser._actions  # noqa: SLF001
            if isinstance(action, __import__("argparse")._SubParsersAction)
        )
        commands = set(subparsers.choices)
        classes = (
            lifehug.QUEUED_MUTATION_COMMANDS,
            lifehug.DIRECT_MUTATION_COMMANDS,
            lifehug.READ_ONLY_COMMANDS,
        )
        self.assertEqual(set().union(*classes), commands)
        self.assertEqual(sum(len(group) for group in classes), len(commands))

    def test_hostile_record_command_and_paths_are_rejected(self):
        bad_id = "d" * 20
        jobs._ensure_layout()
        jobs._write_json(jobs._record_path(bad_id), {
            "version": jobs.RECORD_VERSION,
            "id": bad_id,
            "command": "../../bin/rm",
            "state": "queued",
            "retry_safety": "never",
            "created_at": jobs._now(),
            "updated_at": jobs._now(),
            "attempts": 0,
            "argv": ["rm", "-rf", "/"],
        })
        self.assertIsNone(jobs.load_job(bad_id))
        self.assertFalse(jobs.worker_once(wait_seconds=0.1))
        for command, payload in (
            ("artifact-save", {"ref": "outputs/../escape", "content": "x"}),
            ("fix-source", {"ref": "../../etc/passwd", "mode": "correct", "right": "x"}),
            ("timeline-unplace", {"key": "../../escape"}),
        ):
            with self.subTest(command=command), self.assertRaises(ValueError):
                jobs.enqueue(command, payload, kick=False)

    def test_symlinked_state_and_job_sidecars_fail_closed(self):
        escaped = self.tmp / "escaped"
        escaped.mkdir()
        bad_vault = self.tmp / "bad-vault"
        bad_vault.mkdir()
        (bad_vault / "question-bank.md").write_text("# Questions\n", encoding="utf-8")
        (bad_vault / "state").symlink_to(escaped, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, "symlink"):
            jobs.configure(bad_vault)

        jobs.configure(self.vault)
        jobs._ensure_layout()
        shutil.rmtree(jobs.PAYLOADS_DIR)
        jobs.PAYLOADS_DIR.symlink_to(escaped, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, "special, or symlinked"):
            jobs.enqueue("compile", {}, identity="symlink-payload", kick=False)

    def test_vault_root_authority_precedence_and_validation(self):
        explicit = self.tmp / "explicit-vault"
        from_env = self.tmp / "environment-vault"
        embedded = self.tmp / "embedded-framework" / "system"
        make_minimum_vault(explicit)
        make_minimum_vault(from_env)
        make_minimum_vault(embedded.parent, embedded=True)
        with mock.patch.dict(os.environ, {"LIFEHUG_VAULT_ROOT": str(from_env)}):
            self.assertEqual(
                vault_paths.resolve_vault_root(
                    explicit,
                    framework_system_dir=embedded,
                ),
                explicit.resolve(),
            )
            self.assertEqual(
                vault_paths.resolve_vault_root(framework_system_dir=embedded),
                from_env.resolve(),
            )
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertEqual(
                vault_paths.resolve_vault_root(framework_system_dir=embedded),
                embedded.parent.resolve(),
            )

        symlink = self.tmp / "vault-symlink"
        symlink.symlink_to(explicit, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, "symlink"):
            vault_paths.resolve_vault_root(symlink, framework_system_dir=embedded)
        regular_file = self.tmp / "not-a-vault"
        regular_file.write_text("x")
        with self.assertRaisesRegex(ValueError, "existing directory"):
            vault_paths.resolve_vault_root(regular_file, framework_system_dir=embedded)

    def test_kernel_lock_serializes_acquisition_and_release_boundary(self):
        jobs._ensure_layout()
        entered = threading.Event()

        def contender():
            with jobs._KernelLock(jobs.WRITER_LOCK, wait_seconds=1):
                entered.set()

        with jobs._KernelLock(jobs.WRITER_LOCK, wait_seconds=0.1):
            inode = jobs.WRITER_LOCK.stat().st_ino
            thread = threading.Thread(target=contender)
            thread.start()
            time.sleep(0.08)
            self.assertFalse(entered.is_set(), "contender crossed a held kernel lock")
        thread.join(2)
        self.assertTrue(entered.is_set())
        self.assertTrue(jobs.WRITER_LOCK.is_file())
        self.assertEqual(jobs.WRITER_LOCK.stat().st_ino, inode)

    def test_enqueue_uses_same_kernel_lock_primitive(self):
        jobs._ensure_layout()
        with jobs._KernelLock(jobs.ENQUEUE_LOCK, wait_seconds=0.1):
            with self.assertRaises(TimeoutError):
                with jobs._KernelLock(jobs.ENQUEUE_LOCK, wait_seconds=0.03):
                    pass

    def test_live_reentry_token_valid_stale_and_forged(self):
        with jobs._WriterLease(wait_seconds=0.1) as lease:
            self.assertTrue(jobs.writer_token_is_live(lease.owner_id, vault_root=self.vault))
            self.assertFalse(jobs.writer_token_is_live("f" * 20, vault_root=self.vault))
            with mock.patch.dict(
                os.environ,
                {"LIFEHUG_JOB_RUNNER_TOKEN": lease.owner_id},
            ), mock.patch.object(lifehug, "REPO_DIR", self.vault):
                self.assertTrue(lifehug._job_runner_active())
        self.assertFalse(jobs.writer_token_is_live(lease.owner_id, vault_root=self.vault))
        with mock.patch.dict(
            os.environ,
            {"LIFEHUG_JOB_RUNNER_TOKEN": lease.owner_id},
        ), mock.patch.object(lifehug, "REPO_DIR", self.vault):
            self.assertFalse(lifehug._job_runner_active())

    def test_heartbeat_failure_is_caught_and_expired_owner_is_stale(self):
        owner = jobs._owned_lock_record("2" * 20, 30)
        owner["lease_expires_at"] = "2000-01-01T00:00:00Z"
        with mock.patch.object(jobs, "_pid_alive", return_value=True), \
                mock.patch.object(jobs, "_process_birth", return_value=owner["process_birth"]):
            self.assertTrue(jobs._owner_is_stale(owner))

        lease = jobs._WriterLease()
        lease.stop.wait = mock.Mock(return_value=False)
        with mock.patch.object(jobs, "_read_json", return_value={"owner_id": lease.owner_id}), \
                mock.patch.object(jobs, "_write_json", side_effect=OSError("disk unavailable")):
            lease._heartbeat()
        self.assertTrue(lease.heartbeat_failed)

    def test_pid_reuse_and_stale_heartbeat_do_not_wedge(self):
        owner = jobs._owned_lock_record("1" * 20, 30)
        owner["process_birth"] = "old-birth"
        with mock.patch.object(jobs, "_pid_alive", return_value=True), \
                mock.patch.object(jobs, "_process_birth", return_value="new-birth"):
            self.assertTrue(jobs._owner_is_stale(owner))

        owner["process_birth"] = None
        owner["lease_expires_at"] = (
            datetime.now(timezone.utc) - timedelta(seconds=1)
        ).strftime("%Y-%m-%dT%H:%M:%SZ")
        with mock.patch.object(jobs, "_pid_alive", return_value=True), \
                mock.patch.object(jobs, "_process_birth", return_value=None):
            self.assertTrue(jobs._owner_is_stale(owner))

    def test_timeout_kills_descendant_before_writer_lease_can_release(self):
        marker = self.tmp / "descendant-survived"
        script = self.tmp / "spawn-descendant.py"
        child = (
            "import time; from pathlib import Path; time.sleep(0.8); "
            f"Path({str(marker)!r}).write_text('survived')"
        )
        script.write_text(
            "import subprocess, sys, time\n"
            f"subprocess.Popen([sys.executable, '-c', {child!r}])\n"
            "time.sleep(10)\n",
            encoding="utf-8",
        )
        rc, failure = jobs._run_invocation(
            jobs.Invocation("exec", (sys.executable, str(script))), timeout_seconds=0.2
        )
        self.assertEqual((rc, failure), (-2, "command_timeout"))
        time.sleep(1)
        self.assertFalse(marker.exists(), "descendant escaped the timed-out command group")

    def test_detaching_script_is_rejected_before_it_can_escape(self):
        marker = self.tmp / "detached-survived"
        script = self.tmp / "detach.py"
        child = f"from pathlib import Path; Path({str(marker)!r}).write_text('escaped')"
        script.write_text(
            "import subprocess, sys\n"
            f"subprocess.Popen([sys.executable, '-c', {child!r}], start_new_session=True)\n"
        )
        rc, failure = jobs._run_invocation(
            jobs.Invocation("exec", (sys.executable, str(script))), timeout_seconds=1
        )
        self.assertEqual((rc, failure), (-1, "detached_child_forbidden"))
        time.sleep(0.1)
        self.assertFalse(marker.exists())


if __name__ == "__main__":
    unittest.main()
