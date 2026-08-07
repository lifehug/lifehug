#!/usr/bin/env python3
"""Durable, restart-safe local job queue and single-writer worker.

Every queued job names one command from :data:`COMMANDS`; records never carry
an argv, stdin, prompt, source body, answer, feedback, secret, or subprocess
output.  Inputs live in an opaque, mode-0600 payload sidecar and are converted
to canonical Lifehug CLI/script invocations only after strict validation.

The worker owns the one vault-wide writer lease.  A completion receipt is
written before the public job record is finalized.  Recovery can therefore
recognize a completed attempt without repeating it.  If an attempt has no
receipt, only commands declared idempotent become ``safely-retryable``;
possibly-completed non-idempotent work becomes ``failed`` with an ambiguous
outcome and is never replayed automatically.

The framework and vault roots are deliberately separate.  Today they are the
same checkout.  A future external framework can set ``LIFEHUG_VAULT_ROOT`` (or
pass ``--vault-root``) while this module and the canonical scripts remain in
the installed framework tree.
"""

from __future__ import annotations

import argparse
import contextlib
import fcntl
import hashlib
import hmac
import json
import os
import re
import secrets
import signal
import socket
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable

from vault_paths import (
    resolve_framework_system_dir,
    resolve_vault_root,
    validate_contained_path,
)

FRAMEWORK_SYSTEM_DIR = resolve_framework_system_dir()
DEFAULT_VAULT_ROOT = resolve_vault_root(framework_system_dir=FRAMEWORK_SYSTEM_DIR)

VAULT_ROOT = DEFAULT_VAULT_ROOT
JOBS_DIR = VAULT_ROOT / "state" / "jobs"
PAYLOADS_DIR = JOBS_DIR / ".payloads"
RECEIPTS_DIR = JOBS_DIR / ".receipts"
WRITER_LOCK = JOBS_DIR / ".writer-v2.lock"
WRITER_OWNER_FILE = JOBS_DIR / ".writer-owner.json"
ENQUEUE_LOCK = JOBS_DIR / ".enqueue-v2.lock"
IDENTITY_KEY_FILE = JOBS_DIR / ".identity-key"

LEASE_SECONDS = max(10, int(os.environ.get("LIFEHUG_JOB_LEASE_SECONDS", "120")))
POLL_SECONDS = max(0.05, float(os.environ.get("LIFEHUG_JOB_POLL_SECONDS", "1")))
DRAIN_IDLE_SECONDS = max(0.05, float(os.environ.get("LIFEHUG_JOB_DRAIN_IDLE", "0.5")))
DRAIN_LOCK_WAIT_SECONDS = max(0.05, float(os.environ.get("LIFEHUG_JOB_DRAIN_LOCK_WAIT", "1")))
WAIT_TIMEOUT_SECONDS = max(1, int(os.environ.get("LIFEHUG_JOB_WAIT_TIMEOUT", "86400")))
ORPHAN_GRACE_SECONDS = max(60, int(os.environ.get("LIFEHUG_JOB_ORPHAN_GRACE", "86400")))
PAYLOAD_VERSION = 1
RECORD_VERSION = 2

JOB_STATES = frozenset({"queued", "running", "succeeded", "failed", "safely-retryable"})
TERMINAL_STATES = frozenset({"succeeded", "failed"})
_ID_RE = re.compile(r"^[0-9a-f]{20}$")
_TOKEN_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:@/-]{0,255}$")
_QUESTION_ID_RE = re.compile(r"^[A-Z][0-9]+[a-z]*$")
_ARTIFACT_REF_RE = re.compile(r"^outputs/[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_PLACEMENT_KEY_RE = re.compile(r"^[0-9a-f]{12}$")


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_time(value: str) -> datetime | None:
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def _write_json(path: Path, data: object, *, mode: int = 0o600) -> None:
    """Atomically write JSON without following a destination symlink."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_symlink():
        raise ValueError("refusing symlinked job storage")
    tmp = path.parent / f".{path.name}.{secrets.token_hex(8)}.tmp"
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    fd = os.open(tmp, flags, mode)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=2, ensure_ascii=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    finally:
        with contextlib.suppress(FileNotFoundError):
            tmp.unlink()


def _read_json(path: Path) -> dict | None:
    if path.is_symlink() or not path.is_file():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeError):
        return None
    return value if isinstance(value, dict) else None


def configure(vault_root: Path) -> None:
    """Point queue state at ``vault_root`` (used by CLI and fixture tests)."""
    global VAULT_ROOT, JOBS_DIR, PAYLOADS_DIR, RECEIPTS_DIR
    global WRITER_LOCK, WRITER_OWNER_FILE, ENQUEUE_LOCK, IDENTITY_KEY_FILE
    VAULT_ROOT = resolve_vault_root(
        vault_root,
        framework_system_dir=FRAMEWORK_SYSTEM_DIR,
    )
    JOBS_DIR = VAULT_ROOT / "state" / "jobs"
    PAYLOADS_DIR = JOBS_DIR / ".payloads"
    RECEIPTS_DIR = JOBS_DIR / ".receipts"
    WRITER_LOCK = JOBS_DIR / ".writer-v2.lock"
    WRITER_OWNER_FILE = JOBS_DIR / ".writer-owner.json"
    ENQUEUE_LOCK = JOBS_DIR / ".enqueue-v2.lock"
    IDENTITY_KEY_FILE = JOBS_DIR / ".identity-key"


def _ensure_layout() -> None:
    state_root = VAULT_ROOT / "state"
    if state_root.is_symlink():
        raise ValueError("vault/state may not be a symlink")
    if state_root.exists() and not state_root.is_dir():
        raise ValueError("vault/state must be a directory")
    state_root.mkdir(parents=True, exist_ok=True)
    if JOBS_DIR.exists() and (JOBS_DIR.is_symlink() or not JOBS_DIR.is_dir()):
        raise ValueError("job directory must be a real directory under vault/state")
    JOBS_DIR.mkdir(exist_ok=True)
    if JOBS_DIR.resolve().parent != state_root.resolve():
        raise ValueError("job directory escaped vault/state")
    for directory in (PAYLOADS_DIR, RECEIPTS_DIR):
        if directory.exists() and (directory.is_symlink() or not directory.is_dir()):
            raise ValueError("job sidecar directories must be real directories")
    PAYLOADS_DIR.mkdir(mode=0o700, exist_ok=True)
    RECEIPTS_DIR.mkdir(mode=0o700, exist_ok=True)


def _identity_key() -> bytes:
    _ensure_layout()
    if IDENTITY_KEY_FILE.is_symlink():
        raise ValueError("identity key may not be a symlink")
    try:
        key = IDENTITY_KEY_FILE.read_bytes()
    except FileNotFoundError:
        key = secrets.token_bytes(32)
        tmp = IDENTITY_KEY_FILE.parent / f".identity-key-{secrets.token_hex(8)}.tmp"
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(key)
                handle.flush()
                os.fsync(handle.fileno())
            try:
                # A hard-link publishes only a fully-written inode and fails
                # atomically if another cold-start process won the race.
                os.link(tmp, IDENTITY_KEY_FILE, follow_symlinks=False)
            except FileExistsError:
                key = IDENTITY_KEY_FILE.read_bytes()
        finally:
            with contextlib.suppress(FileNotFoundError):
                tmp.unlink()
    if len(key) != 32:
        raise ValueError("invalid job identity key")
    return key


def _expect_payload(
    payload: dict,
    *,
    required: set[str] | frozenset[str] = frozenset(),
    optional: set[str] | frozenset[str] = frozenset(),
) -> None:
    if not isinstance(payload, dict):
        raise ValueError("payload must be an object")
    missing = required - payload.keys()
    extra = payload.keys() - required - optional
    if missing or extra:
        raise ValueError("payload fields do not match the command contract")


def _text(payload: dict, key: str, *, maximum: int = 10000, empty: bool = False) -> str:
    value = payload.get(key, "")
    if not isinstance(value, str) or len(value) > maximum or (not empty and not value.strip()):
        raise ValueError(f"invalid {key}")
    if "\x00" in value:
        raise ValueError(f"invalid {key}")
    return value


def _optional_text(payload: dict, key: str, *, maximum: int = 10000) -> str:
    if key not in payload or payload[key] is None:
        return ""
    return _text(payload, key, maximum=maximum, empty=True)


def _token(payload: dict, key: str) -> str:
    value = _text(payload, key, maximum=256)
    if not _TOKEN_RE.fullmatch(value) or ".." in Path(value).parts:
        raise ValueError(f"invalid {key}")
    return value


def _source_ref(payload: dict, key: str = "ref") -> str:
    value = _text(payload, key, maximum=512)
    path = Path(value)
    if path.is_absolute() or ".." in path.parts or value.startswith(("~", "-")):
        raise ValueError("invalid source reference")
    allowed = value.startswith(("answers/", "sources/", "answer:", "source:"))
    if not allowed:
        raise ValueError("invalid source reference")
    return value


def _artifact_ref(payload: dict) -> str:
    value = _text(payload, "ref", maximum=136)
    if not _ARTIFACT_REF_RE.fullmatch(value):
        raise ValueError("invalid artifact reference")
    return value


def _question_id(payload: dict) -> str:
    value = _text(payload, "question_id", maximum=32)
    if not _QUESTION_ID_RE.fullmatch(value):
        raise ValueError("invalid question id")
    return value


@dataclass(frozen=True)
class Invocation:
    kind: str
    arguments: tuple[str, ...]
    stdin_text: str | None = None


@dataclass(frozen=True)
class CommandSpec:
    build: Callable[[dict], tuple[Invocation, ...]]
    retry_safety: str
    timeout_seconds: int = 3600


def _cli(*args: str, stdin_text: str | None = None) -> Invocation:
    # CLI arguments are transported in a private stdin envelope to
    # job_execute.py; user text never appears in the OS process argv.
    return Invocation("lifehug-cli", tuple(args), stdin_text)


def _script(name: str, stdin_text: str | None = None, *args: str) -> Invocation:
    return Invocation("exec", ("bash", str(FRAMEWORK_SYSTEM_DIR / name), *args), stdin_text)


def _build_schedule(script_name: str) -> Callable[[dict], tuple[Invocation, ...]]:
    def build(payload: dict) -> tuple[Invocation, ...]:
        _expect_payload(payload)
        return (_script(script_name),)
    return build


def _build_candidate_promote(payload: dict) -> tuple[Invocation, ...]:
    _expect_payload(payload, required={"candidate_id", "category"})
    candidate = _token(payload, "candidate_id")
    category = _text(payload, "category", maximum=1)
    if not re.fullmatch(r"[A-Z]", category):
        raise ValueError("invalid category")
    return (_cli("candidates-promote", candidate, "--category", category),)


def _build_candidate_update(payload: dict) -> tuple[Invocation, ...]:
    _expect_payload(payload, required={"candidate_id", "status"}, optional={"reason"})
    candidate = _token(payload, "candidate_id")
    status = _text(payload, "status", maximum=32)
    if status not in {"rejected", "deferred", "accepted"}:
        raise ValueError("invalid candidate status")
    args = ["candidates-update", candidate, "--status", status]
    reason = _optional_text(payload, "reason", maximum=1000)
    if reason:
        args += ["--reason", reason]
    return (_cli(*args),)


def _build_focus(payload: dict, action: str) -> tuple[Invocation, ...]:
    required = {"recommendation_id"}
    optional = {"reason"} if action == "dismiss" else set()
    _expect_payload(payload, required=required, optional=optional)
    recommendation = _token(payload, "recommendation_id")
    args = [f"focus-{action}", recommendation]
    reason = _optional_text(payload, "reason", maximum=1000)
    if reason:
        args += ["--reason", reason]
    return (_cli(*args),)


def _build_focus_approve(payload: dict) -> tuple[Invocation, ...]:
    return _build_focus(payload, "approve")


def _build_focus_dismiss(payload: dict) -> tuple[Invocation, ...]:
    return _build_focus(payload, "dismiss")


def _build_second_voice(payload: dict) -> tuple[Invocation, ...]:
    _expect_payload(payload, required={"key"})
    return (_cli("second-voice-ack", _token(payload, "key")),)


def _build_artifact_save(payload: dict) -> tuple[Invocation, ...]:
    _expect_payload(
        payload,
        required={"ref", "content"},
        optional={"note", "model", "final"},
    )
    ref = _artifact_ref(payload)
    content = _text(payload, "content", maximum=2_000_000)
    model = _optional_text(payload, "model", maximum=256) or "manual-edit"
    args = ["artifact", "save", ref, "--model", model]
    note = _optional_text(payload, "note", maximum=4000)
    if note:
        args += ["--feedback", note]
    final = payload.get("final", False)
    if not isinstance(final, bool):
        raise ValueError("invalid final flag")
    if final:
        args.append("--final")
    return (_cli(*args, stdin_text=content),)


def _build_artifact_revise(payload: dict) -> tuple[Invocation, ...]:
    _expect_payload(payload, required={"ref", "feedback"}, optional={"model"})
    args = ["artifact", "revise", _artifact_ref(payload), "--feedback",
            _text(payload, "feedback", maximum=20_000)]
    model = _optional_text(payload, "model", maximum=256)
    if model:
        args += ["--model", model]
    return (_cli(*args),)


def _build_artifact_final(payload: dict) -> tuple[Invocation, ...]:
    _expect_payload(payload, required={"ref"}, optional={"version"})
    version = _optional_text(payload, "version", maximum=16) or "latest"
    if not re.fullmatch(r"(?:latest|v?[0-9]+)", version):
        raise ValueError("invalid artifact version")
    return (_cli("artifact", "final", _artifact_ref(payload), "--version", version),)


def _build_artifact_promote(payload: dict) -> tuple[Invocation, ...]:
    _expect_payload(payload, required={"ref"}, optional={"kind", "version", "source"})
    ref = _artifact_ref(payload)
    kind = _optional_text(payload, "kind", maximum=16) or "all"
    if kind not in {"context", "final", "all"}:
        raise ValueError("invalid promotion kind")
    version = _optional_text(payload, "version", maximum=16) or "final"
    if not re.fullmatch(r"(?:final|latest|v?[0-9]+)", version):
        raise ValueError("invalid artifact version")
    source = _optional_text(payload, "source", maximum=500) or "viewer"
    return (
        _cli("artifact", "promote-source", ref, "--kind", kind,
             "--version", version, "--source", source),
        _cli("compile", "--no-ai"),
    )


def _build_artifact_new(payload: dict) -> tuple[Invocation, ...]:
    _expect_payload(
        payload,
        required={"format"},
        optional={
            "subject", "occasion", "date", "title", "audience", "privacy",
            "categories", "seed", "force",
        },
    )
    format_name = _text(payload, "format", maximum=32)
    if format_name not in {
        "letter", "tweet", "instagram", "post", "essay", "chapter",
        "unsent_letter", "legacy_letter",
    }:
        raise ValueError("invalid artifact format")
    args = ["artifact", "new", "--format", format_name]
    for key, flag, maximum in (
        ("subject", "--subject", 1000),
        ("occasion", "--occasion", 1000),
        ("date", "--date", 32),
        ("title", "--title", 500),
        ("audience", "--audience", 1000),
        ("privacy", "--privacy", 64),
        ("categories", "--categories", 1000),
    ):
        value = _optional_text(payload, key, maximum=maximum)
        if value:
            args += [flag, value]
    seed = _optional_text(payload, "seed", maximum=512)
    if seed:
        path = Path(seed)
        if path.is_absolute() or ".." in path.parts or not seed.startswith("sources/"):
            raise ValueError("invalid artifact seed")
        args += ["--seed", seed]
    force = payload.get("force", False)
    if not isinstance(force, bool):
        raise ValueError("invalid force flag")
    if force:
        args.append("--force")
    return (_cli(*args),)


def _build_compile(payload: dict) -> tuple[Invocation, ...]:
    _expect_payload(payload, optional={"no_ai", "model"})
    args = ["compile"]
    no_ai = payload.get("no_ai", False)
    if not isinstance(no_ai, bool):
        raise ValueError("invalid no_ai flag")
    if no_ai:
        args.append("--no-ai")
    model = _optional_text(payload, "model", maximum=256)
    if model:
        args += ["--model", model]
    return (_cli(*args),)


def _build_artifact_delivered(payload: dict) -> tuple[Invocation, ...]:
    _expect_payload(payload, required={"ref"}, optional={"to", "note", "reaction"})
    args = ["artifact", "delivered", _artifact_ref(payload)]
    for key, flag, maximum in (
        ("to", "--to", 500),
        ("note", "--note", 20_000),
        ("reaction", "--reaction", 200_000),
    ):
        value = _optional_text(payload, key, maximum=maximum)
        if value:
            args += [flag, value]
    return (_cli(*args),)


def _build_reflect(payload: dict) -> tuple[Invocation, ...]:
    _expect_payload(payload, required={"ref", "body"})
    return (_cli("reflect-source", _source_ref(payload), "--source", "viewer",
                 stdin_text=_text(payload, "body", maximum=500_000)),)


def _build_fix(payload: dict) -> tuple[Invocation, ...]:
    _expect_payload(
        payload,
        required={"ref", "mode"},
        optional={"reason", "from_pages", "right", "wrong", "kind"},
    )
    ref = _source_ref(payload)
    mode = _text(payload, "mode", maximum=16)
    if mode == "retract":
        reason = _text(payload, "reason", maximum=20_000)
        pages = payload.get("from_pages", [])
        if not isinstance(pages, list) or len(pages) > 50:
            raise ValueError("invalid retraction pages")
        args = ["fix", ref, "--retract", "--reason", reason]
        for page in pages:
            if not isinstance(page, str) or not re.fullmatch(r"[A-Za-z0-9._-]{1,128}", page):
                raise ValueError("invalid page slug")
            args += ["--from-page", page]
        return (_cli(*args),)
    if mode != "correct":
        raise ValueError("invalid fix mode")
    right = _text(payload, "right", maximum=100_000)
    kind = _optional_text(payload, "kind", maximum=32) or "factual"
    if kind not in {"factual", "context", "date", "identity", "privacy"}:
        raise ValueError("invalid correction kind")
    args = ["fix", ref, "--right", right, "--kind", kind]
    wrong = _optional_text(payload, "wrong", maximum=100_000)
    if wrong:
        args += ["--wrong", wrong]
    return (_cli(*args),)


def _build_timeline_place(payload: dict) -> tuple[Invocation, ...]:
    _expect_payload(
        payload,
        required={"source", "description", "period"},
        optional={"when_hint", "note"},
    )
    source_payload = {"ref": payload["source"]}
    source = _source_ref(source_payload)
    period = _text(payload, "period", maximum=128)
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", period):
        raise ValueError("invalid period")
    args = ["timeline-place", source, "--period", period]
    when_hint = _optional_text(payload, "when_hint", maximum=1000)
    note = _optional_text(payload, "note", maximum=4000)
    if when_hint:
        args += ["--when-hint", when_hint]
    if note:
        args += ["--note", note]
    return (_cli(*args, stdin_text=_text(payload, "description", maximum=100_000)),)


def _build_timeline_unplace(payload: dict) -> tuple[Invocation, ...]:
    _expect_payload(payload, required={"key"})
    key = _text(payload, "key", maximum=12)
    if not _PLACEMENT_KEY_RE.fullmatch(key):
        raise ValueError("invalid placement key")
    return (_cli("timeline-unplace", key),)


def _build_process_answer(payload: dict) -> tuple[Invocation, ...]:
    _expect_payload(
        payload,
        required={"question_id", "answer"},
        optional={
            "source", "answered_date", "asked_date", "followups", "force", "commit",
            "push", "summary", "no_compile_wiki", "sensitivity",
        },
    )
    args = ["process-answer", _question_id(payload)]
    for key, flag, maximum in (
        ("source", "--source", 500),
        ("answered_date", "--answered-date", 32),
        ("asked_date", "--asked-date", 32),
        ("summary", "--summary", 1000),
    ):
        value = _optional_text(payload, key, maximum=maximum)
        if value:
            args += [flag, value]
    sensitivity = _optional_text(payload, "sensitivity", maximum=16)
    if sensitivity:
        if sensitivity not in {"private", "family", "friends", "public"}:
            raise ValueError("invalid sensitivity")
        args += ["--sensitivity", sensitivity]
    followups = payload.get("followups", [])
    if not isinstance(followups, list) or len(followups) > 100:
        raise ValueError("invalid followups")
    for followup in followups:
        if not isinstance(followup, str) or not followup.strip() or len(followup) > 20_000:
            raise ValueError("invalid followup")
        args += ["--followup", followup]
    for key, flag in (
        ("force", "--force"),
        ("commit", "--commit"),
        ("push", "--push"),
        ("no_compile_wiki", "--no-compile-wiki"),
    ):
        value = payload.get(key, False)
        if not isinstance(value, bool):
            raise ValueError(f"invalid {key}")
        if value:
            args.append(flag)
    return (_cli(*args, stdin_text=_text(payload, "answer", maximum=2_000_000)),)


_FILE_ANSWER_VALUE_FLAGS = {
    "--source", "--answered-date", "--asked-date", "--followup", "--summary", "--sensitivity",
}
_FILE_ANSWER_BOOL_FLAGS = {"--force", "--commit", "--push", "--no-compile-wiki"}


def _validated_file_answer_args(raw: object) -> list[str]:
    if not isinstance(raw, list) or not raw or not all(isinstance(item, str) for item in raw):
        raise ValueError("invalid file-answer arguments")
    if not _QUESTION_ID_RE.fullmatch(raw[0]):
        raise ValueError("invalid question id")
    out = [raw[0]]
    index = 1
    while index < len(raw):
        flag = raw[index]
        if flag in _FILE_ANSWER_BOOL_FLAGS:
            out.append(flag)
            index += 1
            continue
        if flag not in _FILE_ANSWER_VALUE_FLAGS or index + 1 >= len(raw):
            raise ValueError("unsupported file-answer argument")
        value = raw[index + 1]
        if "\x00" in value or len(value) > 20_000:
            raise ValueError("invalid file-answer argument")
        if flag == "--sensitivity" and value not in {"private", "family", "friends", "public"}:
            raise ValueError("invalid sensitivity")
        out += [flag, value]
        index += 2
    return out


def _build_file_answer(payload: dict) -> tuple[Invocation, ...]:
    _expect_payload(payload, required={"args", "body"})
    args = _validated_file_answer_args(payload["args"])
    return (_script("file_answer_bg.sh", _text(payload, "body", maximum=2_000_000), *args),)


# This is the complete executable registry.  Job files cannot extend it and no
# record field is ever treated as argv or a filesystem path.
COMMANDS: dict[str, CommandSpec] = {
    "artifact-delivered": CommandSpec(_build_artifact_delivered, "never"),
    "artifact-final": CommandSpec(_build_artifact_final, "never"),
    "artifact-new": CommandSpec(_build_artifact_new, "never"),
    "artifact-promote": CommandSpec(_build_artifact_promote, "never"),
    "artifact-revise": CommandSpec(_build_artifact_revise, "never", timeout_seconds=1800),
    "artifact-save": CommandSpec(_build_artifact_save, "never"),
    "candidate-promote": CommandSpec(_build_candidate_promote, "never"),
    "candidate-update": CommandSpec(_build_candidate_update, "never"),
    "compile": CommandSpec(_build_compile, "idempotent"),
    "compile-pending": CommandSpec(_build_schedule("compile_and_commit.sh"), "never"),
    "daily": CommandSpec(_build_schedule("daily_question.sh"), "never", timeout_seconds=1800),
    "file-answer": CommandSpec(_build_file_answer, "never", timeout_seconds=1800),
    "fix-source": CommandSpec(_build_fix, "never"),
    "focus-approve": CommandSpec(_build_focus_approve, "never", timeout_seconds=1800),
    "focus-dismiss": CommandSpec(_build_focus_dismiss, "never"),
    "monthly": CommandSpec(_build_schedule("monthly_research.sh"), "never", timeout_seconds=21600),
    "process-answer": CommandSpec(_build_process_answer, "never", timeout_seconds=1800),
    "reflect-source": CommandSpec(_build_reflect, "never"),
    "second-voice-ack": CommandSpec(_build_second_voice, "never"),
    "timeline-place": CommandSpec(_build_timeline_place, "never"),
    "timeline-unplace": CommandSpec(_build_timeline_unplace, "never"),
    "weekly": CommandSpec(_build_schedule("weekly_maintenance.sh"), "never", timeout_seconds=21600),
}
ALLOWED_COMMANDS = frozenset(COMMANDS)


def _payload_path(job_id: str) -> Path:
    return PAYLOADS_DIR / f"{job_id}.json"


def _record_path(job_id: str) -> Path:
    return JOBS_DIR / f"{job_id}.json"


def _receipt_path(job_id: str, attempt_id: str) -> Path:
    return RECEIPTS_DIR / f"{job_id}-{attempt_id}.json"


def _valid_record(record: dict | None, job_id: str | None = None) -> bool:
    if not isinstance(record, dict):
        return False
    required = {"version", "id", "command", "state", "retry_safety", "created_at", "updated_at", "attempts"}
    if not required.issubset(record):
        return False
    if record.get("version") != RECORD_VERSION:
        return False
    rid = record.get("id")
    if not isinstance(rid, str) or not _ID_RE.fullmatch(rid) or (job_id and rid != job_id):
        return False
    command = record.get("command")
    if command not in COMMANDS or record.get("retry_safety") != COMMANDS[command].retry_safety:
        return False
    if record.get("state") not in JOB_STATES or not isinstance(record.get("attempts"), int):
        return False
    # Explicitly reject the old executable/sensitive record shape.
    if any(key in record for key in ("argv", "stdin", "stdin_file", "tail", "output", "payload_path")):
        return False
    return True


def load_job(job_id: str) -> dict | None:
    """Load a validated metadata-only record by opaque id."""
    if not isinstance(job_id, str) or not _ID_RE.fullmatch(job_id):
        return None
    record = _read_json(_record_path(job_id))
    return record if _valid_record(record, job_id) else None


def _job_identity(command: str, payload: dict, identity: str | None) -> str:
    material = {
        "command": command,
        "request": identity if identity is not None else payload,
    }
    canonical = json.dumps(material, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    return hmac.new(_identity_key(), canonical, hashlib.sha256).hexdigest()[:20]


def enqueue(
    command: str,
    payload: dict | None = None,
    *,
    identity: str | None = None,
    kick: bool = True,
) -> dict:
    """Durably enqueue one allowlisted command, deduplicated by stable identity."""
    if command not in COMMANDS:
        raise ValueError("command is not in the Lifehug job registry")
    payload = {} if payload is None else payload
    # Validate before anything is persisted.  The built argv is discarded.
    COMMANDS[command].build(payload)
    # Only an explicit provider/schedule identity deduplicates. Interactive
    # actions are fresh requests even when their content happens to match.
    request_identity = identity if identity is not None else secrets.token_hex(16)
    job_id = _job_identity(command, payload, request_identity)
    created = False
    with _KernelLock(ENQUEUE_LOCK, wait_seconds=5.0):
        existing = load_job(job_id)
        if existing is not None:
            record = existing
        else:
            now = _now()
            payload_record = {"version": PAYLOAD_VERSION, "command": command, "payload": payload}
            _write_json(_payload_path(job_id), payload_record)
            record = {
                "version": RECORD_VERSION,
                "id": job_id,
                "command": command,
                "state": "queued",
                "retry_safety": COMMANDS[command].retry_safety,
                "created_at": now,
                "updated_at": now,
                "attempts": 0,
                "can_retry": False,
                "payload_retained": True,
            }
            _write_json(_record_path(job_id), record)
            created = True
    if kick and (created or record["state"] in {"queued", "safely-retryable"}):
        _kick_worker()
    return record


def _kick_worker() -> None:
    """Best-effort one-shot worker so installs work before launchd is loaded."""
    try:
        subprocess.Popen(
            [sys.executable, str(Path(__file__).resolve()), "worker", "--drain",
             "--vault-root", str(VAULT_ROOT)],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            cwd=VAULT_ROOT,
            start_new_session=True,
        )
    except OSError:
        # The durable queued record remains for the launchd worker or a manual run.
        pass


def _pid_alive(pid: object) -> bool:
    if not isinstance(pid, int) or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _process_birth(pid: int) -> str | None:
    """Return an opaque process-start signature, protecting against PID reuse."""
    try:
        result = subprocess.run(
            ["ps", "-o", "lstart=", "-p", str(pid)],
            capture_output=True,
            text=True,
            timeout=2,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    started = result.stdout.strip() if result.returncode == 0 else ""
    if not started:
        return None
    return hashlib.sha256(started.encode("utf-8")).hexdigest()[:20]


def _owner_is_stale(owner: dict | None) -> bool:
    if not owner:
        return True
    expires = _parse_time(str(owner.get("lease_expires_at", "")))
    if expires is None or expires <= datetime.now(timezone.utc):
        return True
    if owner.get("host") == socket.gethostname() and _pid_alive(owner.get("pid")):
        current_birth = _process_birth(owner["pid"])
        recorded_birth = owner.get("process_birth")
        if current_birth and recorded_birth:
            return current_birth != recorded_birth
        return False
    if owner.get("host") == socket.gethostname():
        return True  # same-host dead owner: no need to wait for the wall clock
    return False


def _owned_lock_record(owner_id: str, lease_seconds: int) -> dict:
    expires = datetime.now(timezone.utc) + timedelta(seconds=lease_seconds)
    return {
        "version": 1,
        "owner_id": owner_id,
        "pid": os.getpid(),
        "host": socket.gethostname(),
        "process_birth": _process_birth(os.getpid()),
        "heartbeat_at": _now(),
        "lease_expires_at": expires.strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


def _open_lock_file(path: Path) -> int:
    _ensure_layout()
    if path.is_symlink() or (path.exists() and not path.is_file()):
        raise ValueError("lock path must be a regular local file")
    flags = os.O_RDWR | os.O_CREAT
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    return os.open(path, flags, 0o600)


class _KernelLock:
    """Crash-released local lock; filesystem owner JSON is advisory only."""

    def __init__(self, path: Path, *, wait_seconds: float = 0.0):
        self.path = path
        self.wait_seconds = wait_seconds
        self.fd: int | None = None

    def __enter__(self):
        deadline = time.monotonic() + self.wait_seconds
        self.fd = _open_lock_file(self.path)
        while True:
            try:
                fcntl.flock(self.fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                return self
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    os.close(self.fd)
                    self.fd = None
                    raise TimeoutError("vault lock is busy")
                time.sleep(0.02)

    def __exit__(self, _exc_type, _exc, _tb):
        if self.fd is not None:
            fcntl.flock(self.fd, fcntl.LOCK_UN)
            os.close(self.fd)
            self.fd = None


class _WriterLease:
    def __init__(self, *, wait_seconds: float = 0.0):
        self.wait_seconds = wait_seconds
        self.owner_id = secrets.token_hex(10)
        self.stop = threading.Event()
        self.thread: threading.Thread | None = None
        self.lock: _KernelLock | None = None
        self.heartbeat_failed = False

    def _owner(self) -> dict:
        return _owned_lock_record(self.owner_id, LEASE_SECONDS)

    def _heartbeat(self) -> None:
        interval = max(1.0, LEASE_SECONDS / 3)
        while not self.stop.wait(interval):
            current = _read_json(WRITER_OWNER_FILE)
            if not current or current.get("owner_id") != self.owner_id:
                return
            try:
                _write_json(WRITER_OWNER_FILE, self._owner())
            except (OSError, ValueError):
                self.heartbeat_failed = True
                return

    def __enter__(self):
        _ensure_layout()
        self.lock = _KernelLock(WRITER_LOCK, wait_seconds=self.wait_seconds)
        self.lock.__enter__()
        _write_json(WRITER_OWNER_FILE, self._owner())
        self.thread = threading.Thread(target=self._heartbeat, daemon=True)
        self.thread.start()
        return self

    def __exit__(self, _exc_type, _exc, _tb):
        self.stop.set()
        if self.thread is not None:
            self.thread.join(timeout=2)
        owner = _read_json(WRITER_OWNER_FILE)
        if owner and owner.get("owner_id") == self.owner_id:
            with contextlib.suppress(FileNotFoundError):
                WRITER_OWNER_FILE.unlink()
        if self.lock is not None:
            self.lock.__exit__(_exc_type, _exc, _tb)
            self.lock = None


def writer_token_is_live(token: str | None, *, vault_root: Path | None = None) -> bool:
    """Confirm a re-entry token against fresh advisory owner metadata."""
    if not isinstance(token, str) or not re.fullmatch(r"[0-9a-f]{20}", token):
        return False
    root = resolve_vault_root(vault_root, framework_system_dir=FRAMEWORK_SYSTEM_DIR)
    jobs_dir = root / "state" / "jobs"
    owner_file = jobs_dir / ".writer-owner.json"
    lock_file = jobs_dir / ".writer-v2.lock"
    try:
        validate_contained_path(owner_file, jobs_dir, label="writer owner metadata")
        validate_contained_path(lock_file, jobs_dir, label="writer lock")
    except ValueError:
        return False
    owner = _read_json(owner_file)
    if not owner or _owner_is_stale(owner):
        return False
    if not secrets.compare_digest(str(owner.get("owner_id", "")), token):
        return False
    try:
        flags = os.O_RDWR
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        fd = os.open(lock_file, flags)
    except OSError:
        return False
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return True
        fcntl.flock(fd, fcntl.LOCK_UN)
        return False
    finally:
        os.close(fd)


@contextlib.contextmanager
def writer_session(vault_root: Path, *, wait_seconds: float = WAIT_TIMEOUT_SECONDS):
    """Serialize an unqueued canonical mutator with the durable worker."""
    configure(vault_root)
    with _WriterLease(wait_seconds=wait_seconds) as lease:
        previous = os.environ.get("LIFEHUG_JOB_RUNNER_TOKEN")
        os.environ["LIFEHUG_JOB_RUNNER_TOKEN"] = lease.owner_id
        try:
            yield
        finally:
            if previous is None:
                os.environ.pop("LIFEHUG_JOB_RUNNER_TOKEN", None)
            else:
                os.environ["LIFEHUG_JOB_RUNNER_TOKEN"] = previous


def _load_payload(job_id: str, command: str) -> dict:
    envelope = _read_json(_payload_path(job_id))
    if not envelope or envelope.get("version") != PAYLOAD_VERSION or envelope.get("command") != command:
        raise ValueError("missing or invalid job payload")
    payload = envelope.get("payload")
    if not isinstance(payload, dict):
        raise ValueError("missing or invalid job payload")
    return payload


def _validate_execution_paths(command: str, payload: dict) -> None:
    """Re-check typed refs after queueing, closing enqueue-to-run symlink races."""
    if command.startswith("artifact-"):
        validate_contained_path(
            VAULT_ROOT / "outputs",
            VAULT_ROOT / "outputs",
            label="output root",
        )
        ref = payload.get("ref")
        if isinstance(ref, str):
            validate_contained_path(VAULT_ROOT / ref, VAULT_ROOT / "outputs", label="artifact ref")
        seed = payload.get("seed")
        if isinstance(seed, str):
            validate_contained_path(VAULT_ROOT / seed, VAULT_ROOT / "sources", label="source seed")
    if command in {"fix-source", "reflect-source", "timeline-place"}:
        ref = payload.get("ref") if command != "timeline-place" else payload.get("source")
        if isinstance(ref, str) and ref.startswith(("answers/", "sources/")):
            allowed = "answers" if ref.startswith("answers/") else "sources"
            validate_contained_path(VAULT_ROOT / ref, VAULT_ROOT / allowed, label="source ref")
        validate_contained_path(
            VAULT_ROOT / "sources" / "corrections",
            VAULT_ROOT / "sources",
            label="correction destination",
        )
    if command in {"process-answer", "file-answer"}:
        validate_contained_path(
            VAULT_ROOT / "answers",
            VAULT_ROOT / "answers",
            label="answer root",
        )


def _receipt(record: dict) -> dict | None:
    attempt_id = record.get("attempt_id")
    if not isinstance(attempt_id, str) or not re.fullmatch(r"[0-9a-f]{20}", attempt_id):
        return None
    receipt = _read_json(_receipt_path(record["id"], attempt_id))
    if not receipt or receipt.get("job_id") != record["id"] or receipt.get("attempt_id") != attempt_id:
        return None
    if not isinstance(receipt.get("exit_code"), int):
        return None
    return receipt


def _finalize_from_receipt(record: dict, receipt: dict) -> dict:
    exit_code = receipt["exit_code"]
    payload_path = _payload_path(record["id"])
    if exit_code == 0:
        with contextlib.suppress(OSError):
            payload_path.unlink()
    payload_retained = payload_path.exists()
    record.update({
        "state": "succeeded" if exit_code == 0 else "failed",
        "exit_code": exit_code,
        "finished_at": receipt.get("finished_at") or _now(),
        "updated_at": _now(),
        "can_retry": bool(exit_code != 0 and record["retry_safety"] == "idempotent"),
        "payload_retained": payload_retained,
    })
    if exit_code != 0:
        record["failure_code"] = "command_failed"
    else:
        record.pop("failure_code", None)
    record.pop("lease_expires_at", None)
    record.pop("lease_owner", None)
    _write_json(_record_path(record["id"]), record)
    return record


def recover_interrupted_jobs() -> list[dict]:
    """Recover ``running`` records after owning the writer lease.

    A receipt proves completion.  No receipt means the outcome is unknown:
    idempotent work is explicitly marked safe to retry; everything else fails
    closed and keeps ``can_retry=false``.
    """
    recovered: list[dict] = []
    for path in sorted(JOBS_DIR.glob("*.json")):
        if path.is_symlink() or not _ID_RE.fullmatch(path.stem):
            continue
        record = load_job(path.stem)
        if not record or record["state"] != "running":
            continue
        receipt = _receipt(record)
        if receipt is not None:
            recovered.append(_finalize_from_receipt(record, receipt))
            continue
        record.update({
            "state": "safely-retryable" if record["retry_safety"] == "idempotent" else "failed",
            "failure_code": "interrupted_before_receipt",
            "updated_at": _now(),
            "finished_at": _now(),
            "can_retry": record["retry_safety"] == "idempotent",
            "payload_retained": _payload_path(record["id"]).exists(),
        })
        record.pop("lease_expires_at", None)
        record.pop("lease_owner", None)
        _write_json(path, record)
        recovered.append(record)
    return recovered


def retry_job(job_id: str) -> dict:
    record = load_job(job_id)
    if not record:
        raise ValueError("unknown job")
    if record["state"] != "failed" or record["retry_safety"] != "idempotent":
        raise ValueError("job is not safely retryable")
    if not _payload_path(job_id).is_file() or _payload_path(job_id).is_symlink():
        raise ValueError("retry payload is unavailable")
    record.update({"state": "safely-retryable", "updated_at": _now(), "can_retry": True})
    _write_json(_record_path(job_id), record)
    _kick_worker()
    return record


def _next_runnable() -> dict | None:
    rows: list[dict] = []
    for path in JOBS_DIR.glob("*.json"):
        if path.is_symlink() or not _ID_RE.fullmatch(path.stem):
            continue
        record = load_job(path.stem)
        if record and record["state"] in {"queued", "safely-retryable"}:
            rows.append(record)
    rows.sort(key=lambda row: (row["created_at"], row["id"]))
    return rows[0] if rows else None


def cleanup_sidecars(*, grace_seconds: int = ORPHAN_GRACE_SECONDS) -> dict[str, int]:
    """Remove safe leftovers; failed/ambiguous payloads are never GC'd."""
    cutoff = time.time() - grace_seconds
    removed = {"successful_payloads": 0, "orphan_payloads": 0, "orphan_receipts": 0}
    for path in PAYLOADS_DIR.glob("*.json"):
        if path.is_symlink() or not _ID_RE.fullmatch(path.stem):
            continue
        record = load_job(path.stem)
        if record and record["state"] == "succeeded":
            with contextlib.suppress(OSError):
                path.unlink()
                removed["successful_payloads"] += 1
            if not path.exists() and record.get("payload_retained"):
                record.update({"payload_retained": False, "updated_at": _now()})
                _write_json(_record_path(record["id"]), record)
        elif record is None and path.stat().st_mtime <= cutoff:
            with contextlib.suppress(OSError):
                path.unlink()
                removed["orphan_payloads"] += 1
    for path in RECEIPTS_DIR.glob("*.json"):
        if path.is_symlink():
            continue
        job_id = path.name.split("-", 1)[0]
        if _ID_RE.fullmatch(job_id) and load_job(job_id) is None and path.stat().st_mtime <= cutoff:
            with contextlib.suppress(OSError):
                path.unlink()
                removed["orphan_receipts"] += 1
    return removed


def purge_job(job_id: str) -> dict:
    """Purge terminal private sidecars while preserving public metadata."""
    with _WriterLease(wait_seconds=WAIT_TIMEOUT_SECONDS):
        record = load_job(job_id)
        if not record:
            raise ValueError("unknown job")
        if record["state"] not in TERMINAL_STATES:
            raise ValueError("only terminal jobs can be purged")
        with contextlib.suppress(OSError):
            _payload_path(job_id).unlink()
        for receipt in RECEIPTS_DIR.glob(f"{job_id}-*.json"):
            if not receipt.is_symlink():
                with contextlib.suppress(OSError):
                    receipt.unlink()
        record.update({
            "payload_retained": False,
            "purged_at": _now(),
            "updated_at": _now(),
        })
        _write_json(_record_path(job_id), record)
        return record


def _child_env(owner_id: str) -> dict[str, str]:
    env = os.environ.copy()
    env["LIFEHUG_FRAMEWORK_SYSTEM_DIR"] = str(FRAMEWORK_SYSTEM_DIR)
    env["LIFEHUG_VAULT_ROOT"] = str(VAULT_ROOT)
    env["LIFEHUG_JOB_RUNNER_TOKEN"] = owner_id
    env.pop("LIFEHUG_JOB_RUNNER_ACTIVE", None)
    env["WORKSPACE"] = str(VAULT_ROOT)
    return env


def _terminate_process_group(proc: subprocess.Popen, *, grace_seconds: float = 2.0) -> None:
    """Stop the command's whole session so descendants cannot outlive the lease."""
    try:
        os.killpg(proc.pid, signal.SIGTERM)
    except (ProcessLookupError, PermissionError):
        return
    deadline = time.monotonic() + grace_seconds
    while time.monotonic() < deadline:
        try:
            os.killpg(proc.pid, 0)
        except ProcessLookupError:
            return
        except PermissionError:
            break
        time.sleep(0.05)
    with contextlib.suppress(ProcessLookupError, PermissionError):
        os.killpg(proc.pid, signal.SIGKILL)


def _contains_detach_primitive(invocation: Invocation) -> bool:
    """Fail closed for executable registry scripts that can escape the group."""
    if invocation.kind != "exec" or len(invocation.arguments) < 2:
        return False
    script_path = Path(invocation.arguments[1])
    if script_path.suffix not in {".py", ".sh"} or not script_path.is_file():
        return False
    try:
        executable = "\n".join(
            line for line in script_path.read_text(encoding="utf-8").splitlines()
            if not line.lstrip().startswith("#")
        )
    except OSError:
        return True
    return bool(
        "start_new_session" in executable
        or "os.setsid" in executable
        or re.search(r"(?:^|\s)setsid(?:\s|$)", executable)
        or re.search(r"(?:^|\s)nohup\b[^\n]*&", executable)
    )


def _run_invocation(
    invocation: Invocation,
    timeout_seconds: int,
    *,
    owner_id: str = "0" * 20,
) -> tuple[int, str]:
    proc: subprocess.Popen | None = None
    if _contains_detach_primitive(invocation):
        return -1, "detached_child_forbidden"
    if invocation.kind == "lifehug-cli":
        argv = [sys.executable, str(Path(__file__).resolve().parent / "job_execute.py")]
        private_input = json.dumps({
            "arguments": list(invocation.arguments),
            "stdin_text": invocation.stdin_text,
        })
    elif invocation.kind == "exec":
        argv = list(invocation.arguments)
        private_input = invocation.stdin_text
    else:
        return -1, "invalid_invocation"
    try:
        proc = subprocess.Popen(
            argv,
            stdin=subprocess.PIPE if private_input is not None else subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            text=True,
            cwd=VAULT_ROOT,
            env=_child_env(owner_id),
            start_new_session=True,
        )
        proc.communicate(input=private_input, timeout=timeout_seconds)
        exit_code, failure_code = int(proc.returncode or 0), "command_failed"
    except subprocess.TimeoutExpired:
        exit_code, failure_code = -2, "command_timeout"
    except OSError:
        exit_code, failure_code = -1, "command_unavailable"
    finally:
        if proc is not None:
            # Also runs after a nominally successful direct child: a background
            # grandchild is not allowed to keep writing after the receipt/lease.
            _terminate_process_group(proc)
            with contextlib.suppress(subprocess.TimeoutExpired):
                proc.wait(timeout=2)
    return exit_code, failure_code


def _execute_record(record: dict, owner_id: str) -> dict:
    command = record["command"]
    spec = COMMANDS[command]
    try:
        payload = _load_payload(record["id"], command)
        invocations = spec.build(payload)
        _validate_execution_paths(command, payload)
    except (OSError, ValueError, TypeError):
        record.update({
            "state": "failed", "failure_code": "invalid_payload", "exit_code": -1,
            "finished_at": _now(), "updated_at": _now(), "can_retry": False,
            "payload_retained": _payload_path(record["id"]).exists(),
        })
        _write_json(_record_path(record["id"]), record)
        return record

    attempt_id = secrets.token_hex(10)
    record.update({
        "state": "running",
        "attempt_id": attempt_id,
        "attempts": record["attempts"] + 1,
        "started_at": _now(),
        "updated_at": _now(),
        "lease_owner": owner_id,
        "lease_expires_at": (datetime.now(timezone.utc) + timedelta(seconds=LEASE_SECONDS)).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        ),
        "can_retry": False,
    })
    record.pop("failure_code", None)
    _write_json(_record_path(record["id"]), record)

    exit_code = 0
    failure_code = "command_failed"
    for invocation in invocations:
        exit_code, failure_code = _run_invocation(
            invocation,
            spec.timeout_seconds,
            owner_id=owner_id,
        )
        if exit_code != 0:
            break

    receipt = {
        "version": 1,
        "job_id": record["id"],
        "attempt_id": attempt_id,
        "exit_code": exit_code,
        "finished_at": _now(),
    }
    _write_json(_receipt_path(record["id"], attempt_id), receipt)
    record = _finalize_from_receipt(record, receipt)
    if exit_code != 0 and failure_code != "command_failed":
        record["failure_code"] = failure_code
        _write_json(_record_path(record["id"]), record)
    return record


def worker_once(*, wait_seconds: float = 0.0) -> bool:
    """Run at most one job.  Returns whether a job was executed."""
    try:
        with _WriterLease(wait_seconds=wait_seconds) as lease:
            recover_interrupted_jobs()
            cleanup_sidecars()
            record = _next_runnable()
            if record is None:
                return False
            _execute_record(record, lease.owner_id)
            return True
    except TimeoutError:
        return False


def _runnable_exists() -> bool:
    _ensure_layout()
    return _next_runnable() is not None


def worker_drain() -> int:
    """Fallback service: release between jobs and exit after bounded idle."""
    idle_since: float | None = None
    while True:
        if worker_once(wait_seconds=DRAIN_LOCK_WAIT_SECONDS):
            idle_since = None
            continue
        if _runnable_exists():
            # Another worker owns a long job. Keep this fallback alive until
            # the runnable work behind it has had a chance to acquire the lock.
            idle_since = None
            time.sleep(min(POLL_SECONDS, 0.1))
            continue
        idle_since = idle_since or time.monotonic()
        if time.monotonic() - idle_since >= DRAIN_IDLE_SECONDS:
            return 0
        time.sleep(min(POLL_SECONDS, 0.1))


def worker_forever() -> int:
    while True:
        if not worker_once():
            time.sleep(POLL_SECONDS)


def wait_for_job(job_id: str, *, timeout: float = WAIT_TIMEOUT_SECONDS) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        record = load_job(job_id)
        if record is None:
            raise ValueError("unknown job")
        if record["state"] in TERMINAL_STATES:
            return record
        time.sleep(min(POLL_SECONDS, 0.2))
    raise TimeoutError("timed out waiting for job")


def _cmd_enqueue(args: argparse.Namespace) -> int:
    if args.command not in {"daily", "weekly", "monthly", "compile-pending", "compile"}:
        print("error: use the typed application API for commands with inputs", file=sys.stderr)
        return 2
    identity = args.identity
    record = enqueue(args.command, identity=identity)
    print(record["id"])
    if not args.wait:
        return 0
    try:
        record = wait_for_job(record["id"])
    except TimeoutError:
        return 124
    return int(record.get("exit_code", 1)) if record["state"] == "failed" else 0


def _cmd_file_answer(args: argparse.Namespace) -> int:
    body = sys.stdin.read()
    payload = {"args": [args.question_id, *args.file_args], "body": body}
    try:
        record = enqueue("file-answer", payload)
    except ValueError:
        print("error: invalid file-answer request", file=sys.stderr)
        return 2
    print(record["id"])
    if not args.wait:
        return 0
    try:
        record = wait_for_job(record["id"])
    except TimeoutError:
        return 124
    return int(record.get("exit_code", 1)) if record["state"] == "failed" else 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Lifehug durable local job worker")
    sub = parser.add_subparsers(dest="action", required=True)

    worker = sub.add_parser("worker", help="Run the single-writer worker")
    worker.add_argument("--once", action="store_true", help="Run at most one queued job")
    worker.add_argument("--drain", action="store_true", help=argparse.SUPPRESS)
    worker.add_argument("--vault-root", type=Path, default=DEFAULT_VAULT_ROOT)

    enqueue_parser = sub.add_parser("enqueue", help="Enqueue a schedule/compile command")
    enqueue_parser.add_argument("command", choices=["daily", "weekly", "monthly", "compile-pending", "compile"])
    enqueue_parser.add_argument("--identity")
    enqueue_parser.add_argument("--wait", action="store_true")
    enqueue_parser.add_argument("--vault-root", type=Path, default=DEFAULT_VAULT_ROOT)

    file_answer = sub.add_parser("file-answer", help="Queue Telegram answer filing (body on stdin)")
    file_answer.add_argument("--wait", action="store_true")
    file_answer.add_argument("--vault-root", type=Path, default=DEFAULT_VAULT_ROOT)
    file_answer.add_argument("question_id")
    file_answer.add_argument("file_args", nargs=argparse.REMAINDER)

    show = sub.add_parser("show", help="Print one metadata-only job record")
    show.add_argument("job_id")
    show.add_argument("--vault-root", type=Path, default=DEFAULT_VAULT_ROOT)

    retry = sub.add_parser("retry", help="Retry a failed idempotent job")
    retry.add_argument("job_id")
    retry.add_argument("--vault-root", type=Path, default=DEFAULT_VAULT_ROOT)

    purge = sub.add_parser("purge", help="Remove a terminal job's private sidecars")
    purge.add_argument("job_id")
    purge.add_argument("--vault-root", type=Path, default=DEFAULT_VAULT_ROOT)

    cleanup = sub.add_parser("cleanup", help="Clean safe orphan/success sidecars")
    cleanup.add_argument("--vault-root", type=Path, default=DEFAULT_VAULT_ROOT)

    return parser


def main(argv: list[str] | None = None) -> int:
    raw_argv = list(sys.argv[1:] if argv is None else argv)
    # Private probe used only by the canonical shell wrappers. Keeping it out
    # of argparse's subparser registry prevents the implementation detail from
    # leaking into the public queue-administration help.
    if raw_argv[:1] == ["active"]:
        probe = argparse.ArgumentParser(add_help=False)
        probe.add_argument("--vault-root", type=Path, default=DEFAULT_VAULT_ROOT)
        probe_args = probe.parse_args(raw_argv[1:])
        configure(probe_args.vault_root)
        return 0 if writer_token_is_live(
            os.environ.get("LIFEHUG_JOB_RUNNER_TOKEN"), vault_root=probe_args.vault_root
        ) else 1

    args = build_parser().parse_args(raw_argv)
    configure(args.vault_root)
    if args.action == "worker":
        if args.once:
            worker_once(wait_seconds=10.0)
            return 0
        if args.drain:
            return worker_drain()
        return worker_forever()
    if args.action == "enqueue":
        return _cmd_enqueue(args)
    if args.action == "file-answer":
        return _cmd_file_answer(args)
    if args.action == "show":
        record = load_job(args.job_id)
        if record is None:
            return 1
        print(json.dumps(record, indent=2))
        return 0
    if args.action == "retry":
        try:
            record = retry_job(args.job_id)
        except ValueError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2
        print(record["id"])
        return 0
    if args.action == "purge":
        try:
            record = purge_job(args.job_id)
        except ValueError:
            print("error: job cannot be purged", file=sys.stderr)
            return 2
        print(record["id"])
        return 0
    if args.action == "cleanup":
        with _WriterLease(wait_seconds=WAIT_TIMEOUT_SECONDS):
            print(json.dumps(cleanup_sidecars(), sort_keys=True))
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
