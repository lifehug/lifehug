#!/usr/bin/env python3
"""Narrow Git transaction/adoption authority for exact vault files.

Callers declare every path up front and may return only exact replacement
bytes for that closed set.  This module owns the vault writer lease, Git
ordering, commit scoping, marker-history adoption, and post-rebase validation;
domain policy remains in the caller's pure decision and validation callbacks.
"""

from __future__ import annotations

import contextlib
import fcntl
import os
import re
import subprocess
import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType

from vault_paths import (
    atomic_write_vault_text,
    ensure_vault_directory,
    open_vault_fd,
    read_vault_text,
    resolve_framework_system_dir,
    resolve_vault_root,
    validate_contained_path,
    vault_data_path,
)

COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
_LOCK_BOOTSTRAP = threading.Lock()
_MAX_FILES = 8
_MAX_MARKER_BYTES = 16_384
_MAX_COMMIT_MESSAGE = 512


class ExactFileTransactionError(ValueError):
    """An exact-file plan, vault path, or Git transition failed closed."""


@dataclass(frozen=True)
class ExactFilePlan:
    """Closed replacement plan produced under the vault writer lease."""

    writes: tuple[tuple[str, str], ...]
    marker_path: str
    marker_line: str
    commit_message: str


@dataclass(frozen=True)
class ExactFileResult:
    """Git identity of a newly committed or adopted exact-file plan."""

    changed: bool
    commit_sha: str


Snapshot = Mapping[str, str]
Decision = Callable[[Snapshot], ExactFilePlan]
Validator = Callable[[Snapshot, ExactFilePlan], None]
Failpoint = Callable[[str], None]


def _git(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            ["git", "-C", str(root), *args],
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ExactFileTransactionError(
            f"git {' '.join(args[:2])} failed: {exc}"
        ) from exc


def _git_ok(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    result = _git(root, *args)
    if result.returncode != 0:
        detail = f"{result.stdout or ''}{result.stderr or ''}".strip()[:4000]
        raise ExactFileTransactionError(
            f"git {' '.join(args[:2])} failed: {detail or result.returncode}"
        )
    return result


def _relative_path(value: object) -> str:
    if not isinstance(value, str) or not value or "\x00" in value:
        raise ExactFileTransactionError("transaction path is invalid")
    path = Path(value)
    if path.is_absolute() or path == Path(".") or ".." in path.parts:
        raise ExactFileTransactionError("transaction path escaped vault root")
    return path.as_posix()


def _closed_paths(root: Path, declared_paths: tuple[str, ...]) -> dict[str, Path]:
    if (
        not isinstance(declared_paths, tuple)
        or not 1 <= len(declared_paths) <= _MAX_FILES
    ):
        raise ExactFileTransactionError("declared_paths must contain 1-8 exact paths")
    normalized = tuple(_relative_path(value) for value in declared_paths)
    if len(set(normalized)) != len(normalized):
        raise ExactFileTransactionError("declared_paths contains duplicates")
    return {
        relative: validate_contained_path(
            root / relative, root, label="exact-file transaction path"
        )
        for relative in normalized
    }


def _snapshot(root: Path, paths: Mapping[str, Path]) -> Snapshot:
    return MappingProxyType(
        {
            relative: read_vault_text(path, vault_root=root)
            for relative, path in paths.items()
        }
    )


def _validate_plan(plan: object, paths: Mapping[str, Path]) -> ExactFilePlan:
    if not isinstance(plan, ExactFilePlan):
        raise ExactFileTransactionError("decision must return ExactFilePlan")
    marker_path = _relative_path(plan.marker_path)
    if marker_path not in paths:
        raise ExactFileTransactionError("marker_path was not declared")
    if (
        not isinstance(plan.marker_line, str)
        or not plan.marker_line
        or "\n" in plan.marker_line
        or "\r" in plan.marker_line
        or len(plan.marker_line.encode("utf-8")) > _MAX_MARKER_BYTES
    ):
        raise ExactFileTransactionError("marker_line must be one bounded UTF-8 line")
    if (
        not isinstance(plan.commit_message, str)
        or not plan.commit_message
        or "\n" in plan.commit_message
        or "\r" in plan.commit_message
        or len(plan.commit_message) > _MAX_COMMIT_MESSAGE
    ):
        raise ExactFileTransactionError("commit_message must be one bounded line")
    writes: list[tuple[str, str]] = []
    seen: set[str] = set()
    for raw_path, content in plan.writes:
        relative = _relative_path(raw_path)
        if relative not in paths:
            raise ExactFileTransactionError("plan attempted an undeclared write")
        if relative in seen:
            raise ExactFileTransactionError("plan contains a duplicate write")
        if not isinstance(content, str):
            raise ExactFileTransactionError("plan writes must be text")
        seen.add(relative)
        writes.append((relative, content))
    return ExactFilePlan(
        tuple(writes), marker_path, plan.marker_line, plan.commit_message
    )


def find_first_marker_commit(
    root: Path, marker_path: str, marker_line: str
) -> str | None:
    """Return the first commit whose exact file contains the exact marker line."""
    marker_path = _relative_path(marker_path)
    result = _git(
        root, "log", "--reverse", "--format=%H", f"-S{marker_line}", "--", marker_path
    )
    if result.returncode not in {0, 128}:
        raise ExactFileTransactionError("cannot inspect exact-file Git history")
    for value in result.stdout.splitlines():
        commit = value.strip()
        if not COMMIT_RE.fullmatch(commit):
            continue
        tree = _git(root, "show", f"{commit}:{marker_path}")
        if tree.returncode == 0 and marker_line in tree.stdout.splitlines():
            return commit
    return None


@contextlib.contextmanager
def vault_writer(root: Path):
    """Use the canonical writer lease for the selected root without rebinding it."""
    import jobs

    token = os.environ.get("LIFEHUG_JOB_RUNNER_TOKEN")
    if jobs.writer_token_is_live(token, vault_root=root):
        yield
        return
    if jobs.VAULT_ROOT == root:
        with jobs.writer_session(root):
            yield
        return
    jobs_dir = vault_data_path(
        "jobs", vault_root=root, framework_system_dir=resolve_framework_system_dir()
    )
    lock_path = jobs_dir / ".writer-v2.lock"
    with _LOCK_BOOTSTRAP:
        ensure_vault_directory(jobs_dir, vault_root=root)
        fd = open_vault_fd(
            lock_path,
            os.O_RDWR | os.O_CREAT,
            vault_root=root,
            create_parents=True,
        )
    deadline = time.monotonic() + 120
    try:
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise ExactFileTransactionError(
                        "vault writer lock is busy"
                    ) from None
                time.sleep(0.02)
        yield
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def _push(
    root: Path,
    paths: Mapping[str, Path],
    plan: ExactFilePlan,
    validate: Validator,
) -> str:
    last_error = ""
    for attempt in range(2):
        pushed = _git(root, "push")
        if pushed.returncode == 0:
            commit = find_first_marker_commit(root, plan.marker_path, plan.marker_line)
            if commit is None:
                raise ExactFileTransactionError(
                    "pushed marker commit cannot be resolved"
                )
            return commit
        last_error = f"{pushed.stdout or ''}{pushed.stderr or ''}".strip()
        if attempt == 0:
            pulled = _git(root, "pull", "--rebase", "--autostash")
            if pulled.returncode != 0:
                _git(root, "rebase", "--abort")
                raise ExactFileTransactionError(
                    f"push retry rebase failed: {pulled.stderr.strip()[:4000]}"
                )
            # This hook is the adoption boundary: marker presence alone proves
            # nothing after history changed.  The domain must prove its entire
            # intended record again from fresh exact file bytes.
            validate(_snapshot(root, paths), plan)
            if (
                find_first_marker_commit(root, plan.marker_path, plan.marker_line)
                is None
            ):
                raise ExactFileTransactionError("marker commit changed during rebase")
    raise ExactFileTransactionError(f"git push failed: {last_error[:4000]}")


def resolve_exact_file_transaction(
    *,
    vault_root: str | Path,
    declared_paths: tuple[str, ...],
    decide: Decision,
    validate: Validator,
    push: bool = True,
    failpoint: Failpoint | None = None,
) -> ExactFileResult:
    """Resolve one closed exact-file plan under the canonical Git/lease order.

    Callbacks receive only immutable text snapshots.  They cannot add paths,
    invoke writes through this API, or waive post-rebase validation.
    """
    framework = resolve_framework_system_dir()
    root = resolve_vault_root(
        vault_root, framework_system_dir=framework, bind_process=False
    )
    paths = _closed_paths(root, declared_paths)
    with vault_writer(root):
        if push:
            _git_ok(root, "pull", "--rebase", "--autostash")
        plan = _validate_plan(decide(_snapshot(root, paths)), paths)
        adopted_commit = find_first_marker_commit(
            root, plan.marker_path, plan.marker_line
        )
        if adopted_commit is not None:
            validate(_snapshot(root, paths), plan)
            changed = False
        elif plan.writes:
            for relative, content in plan.writes:
                atomic_write_vault_text(paths[relative], content, vault_root=root)
                if failpoint:
                    failpoint(f"after_write:{relative}")
            validate(_snapshot(root, paths), plan)
            _git_ok(
                root,
                "commit",
                "--only",
                "-m",
                plan.commit_message,
                "--",
                *(relative for relative, _content in plan.writes),
            )
            changed = True
            if failpoint:
                failpoint("after_commit")
        else:
            validate(_snapshot(root, paths), plan)
            changed = False
        commit = find_first_marker_commit(root, plan.marker_path, plan.marker_line)
        if commit is None:
            raise ExactFileTransactionError("exact marker commit cannot be resolved")
        if push:
            commit = _push(root, paths, plan, validate)
            if failpoint:
                failpoint("after_push")
        return ExactFileResult(changed=changed, commit_sha=commit)
