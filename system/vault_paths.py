#!/usr/bin/env python3
"""Authoritative framework/vault roots and versioned durable-data contract.

Executable assets always come from the installed framework. Durable user data
always comes from the selected vault. ``vault_contract.json`` is the one
machine-readable path/minimum-shape/schema table consumed here and, after an
explicit package pin, by hosted import/preflight parity checks.
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import os
import secrets
import stat
import sys
from pathlib import Path
from typing import Callable

EMBEDDED_FRAMEWORK_SYSTEM_DIR = Path(__file__).resolve().parent
VAULT_CONTRACT_FILE = EMBEDDED_FRAMEWORK_SYSTEM_DIR / "vault_contract.json"

_NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)
_DIRECTORY = getattr(os, "O_DIRECTORY", 0)
_BOUND_VAULT_ROOT: Path | None = None
_BOUND_VAULT_IDENTITY: tuple[int, int] | None = None


def _relative_contract_path(value: object, *, label: str) -> Path:
    if not isinstance(value, str) or not value or "\x00" in value:
        raise RuntimeError(f"invalid {label} in vault contract")
    path = Path(value)
    if path.is_absolute() or ".." in path.parts or path == Path("."):
        raise RuntimeError(f"unsafe {label} in vault contract")
    return path


def _load_contract() -> dict[str, object]:
    try:
        value = json.loads(VAULT_CONTRACT_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError("Lifehug vault contract is missing or invalid") from exc
    if not isinstance(value, dict) or value.get("contract_version") != 1:
        raise RuntimeError("unsupported Lifehug vault contract")
    data_paths = value.get("data_paths")
    framework_paths = value.get("framework_paths")
    if not isinstance(data_paths, dict) or not isinstance(framework_paths, dict):
        raise RuntimeError("Lifehug vault contract has no path tables")
    for name, raw in data_paths.items():
        if not isinstance(name, str) or not isinstance(raw, dict):
            raise RuntimeError("invalid durable-data entry in vault contract")
        _relative_contract_path(raw.get("path"), label=f"data path {name}")
        if "embedded_path" in raw:
            _relative_contract_path(raw["embedded_path"], label=f"embedded data path {name}")
        if raw.get("kind") not in {"file", "directory"}:
            raise RuntimeError(f"invalid durable-data kind for {name}")
    for name, raw in framework_paths.items():
        _relative_contract_path(raw, label=f"framework path {name}")
    return value


def _contract_digest(value: dict[str, object]) -> str:
    canonical = json.loads(json.dumps(value))
    identity = canonical.get("identity")
    if isinstance(identity, dict):
        identity.pop("content_digest", None)
    payload = json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode()
    return f"sha256:{hashlib.sha256(payload).hexdigest()}"


def _normalized_contract(value: dict[str, object]) -> dict[str, object]:
    """Return the stable, JSON-only export consumed by hosted preflight."""
    normalized = json.loads(json.dumps(value))
    data_paths = normalized["data_paths"]
    assert isinstance(data_paths, dict)
    for name, entry in data_paths.items():
        assert isinstance(entry, dict)
        external = entry.pop("path", entry.get("external_path", ""))
        entry["external_path"] = external
        entry["embedded_path"] = entry.get("embedded_path", external)
        entry["classification"] = "durable_data"
        schema = entry.get("schema")
        if isinstance(schema, dict):
            if "supported" in schema and "supported_versions" not in schema:
                schema["supported_versions"] = schema.pop("supported")
            schema.setdefault("validation_policy", "deferred")
            schema.setdefault("required_keys", {})
            schema.setdefault("unknown_fields", "allow")
    framework_paths = normalized["framework_paths"]
    assert isinstance(framework_paths, dict)
    normalized["framework_paths"] = {
        name: {
            "path": path,
            "kind": "directory" if name in {"system", "templates", "connectors"} else "file",
            "classification": "framework",
        }
        for name, path in framework_paths.items()
    }
    normalized["data_paths"] = dict(sorted(data_paths.items()))
    normalized["framework_paths"] = dict(sorted(normalized["framework_paths"].items()))
    normalized["path_classifications"] = ["durable_data", "framework", "unknown"]
    normalized.setdefault("special_file_policy", {
        "regular_files": "allow",
        "directories": "allow",
        "symlinks": "reject",
        "fifos": "reject",
        "sockets": "reject",
        "devices": "reject",
    })
    return normalized


_RAW_VAULT_CONTRACT = _load_contract()
VAULT_CONTRACT = _normalized_contract(_RAW_VAULT_CONTRACT)
_CONTRACT_IDENTITY = VAULT_CONTRACT.get("identity")
if not isinstance(_CONTRACT_IDENTITY, dict) or _CONTRACT_IDENTITY.get(
    "content_digest"
) != _contract_digest(VAULT_CONTRACT):
    raise RuntimeError("Lifehug vault contract identity digest does not match its content")
VAULT_DATA_PATHS: dict[str, dict[str, object]] = VAULT_CONTRACT["data_paths"]  # type: ignore[assignment]
FRAMEWORK_PATHS: dict[str, dict[str, object]] = VAULT_CONTRACT["framework_paths"]  # type: ignore[assignment]
MINIMUM_VAULT_SHAPE = tuple(VAULT_CONTRACT["required_data_paths"])
STATE_SCHEMA_TABLE = {
    name: entry["schema"] for name, entry in VAULT_DATA_PATHS.items() if "schema" in entry
}


def _absolute_without_symlinks(value: str | os.PathLike[str], *, label: str) -> Path:
    candidate = Path(os.path.abspath(Path(value).expanduser()))
    current = Path(candidate.anchor)
    for part in candidate.parts[1:]:
        current /= part
        if current.is_symlink():
            raise ValueError(f"{label} may not traverse symlinks")
    return candidate


def _real_directory(value: str | os.PathLike[str], *, label: str) -> Path:
    candidate = Path(value).expanduser()
    if not candidate.is_absolute():
        candidate = Path.cwd() / candidate
    candidate = _absolute_without_symlinks(candidate, label=label)
    if not candidate.is_dir():
        raise ValueError(f"{label} must be an existing directory")
    return candidate


def resolve_framework_system_dir(
    explicit: str | os.PathLike[str] | None = None,
) -> Path:
    """Resolve executable assets independently from the user vault."""
    selected = explicit or os.environ.get("LIFEHUG_FRAMEWORK_SYSTEM_DIR")
    return _real_directory(
        selected or EMBEDDED_FRAMEWORK_SYSTEM_DIR,
        label="framework system root",
    )


def resolve_framework_root(
    framework_system_dir: str | os.PathLike[str] | None = None,
) -> Path:
    return resolve_framework_system_dir(framework_system_dir).parent


def vault_layout(
    vault_root: str | os.PathLike[str],
    *,
    framework_system_dir: str | os.PathLike[str] | None = None,
) -> str:
    vault = _real_directory(vault_root, label="vault root")
    framework = resolve_framework_system_dir(framework_system_dir)
    return "embedded" if vault == framework.parent else "external"


def vault_relative_path(
    name: str,
    *,
    vault_root: str | os.PathLike[str],
    framework_system_dir: str | os.PathLike[str] | None = None,
) -> Path:
    try:
        entry = VAULT_DATA_PATHS[name]
    except KeyError as exc:
        raise KeyError(f"unknown Lifehug durable-data path: {name}") from exc
    layout = vault_layout(vault_root, framework_system_dir=framework_system_dir)
    raw = entry["embedded_path"] if layout == "embedded" else entry["external_path"]
    return _relative_contract_path(raw, label=f"data path {name}")


def vault_data_path(
    name: str,
    *,
    vault_root: str | os.PathLike[str],
    framework_system_dir: str | os.PathLike[str] | None = None,
) -> Path:
    vault = _real_directory(vault_root, label="vault root")
    relative = vault_relative_path(
        name,
        vault_root=vault,
        framework_system_dir=framework_system_dir,
    )
    return validate_contained_path(vault / relative, vault, label=f"vault data path {name}")


def framework_path(
    name: str,
    *,
    framework_system_dir: str | os.PathLike[str] | None = None,
) -> Path:
    try:
        relative = _relative_contract_path(
            FRAMEWORK_PATHS[name]["path"], label=f"framework path {name}"
        )
    except KeyError as exc:
        raise KeyError(f"unknown Lifehug framework path: {name}") from exc
    root = resolve_framework_root(framework_system_dir)
    return validate_contained_path(root / relative, root, label=f"framework path {name}")


def _schema_value_matches(value: object, expected: str) -> bool:
    allowed = expected.split("|")
    matches = {
        "null": value is None,
        "string": isinstance(value, str),
        "integer": isinstance(value, int) and not isinstance(value, bool),
        "number": isinstance(value, int | float) and not isinstance(value, bool),
        "boolean": isinstance(value, bool),
        "array": isinstance(value, list),
        "object": isinstance(value, dict),
    }
    return any(matches.get(option, False) for option in allowed)


def _validate_required_json(
    name: str,
    path: Path,
    entry: dict[str, object],
    *,
    vault_root: Path,
) -> None:
    schema = entry.get("schema")
    if not isinstance(schema, dict) or schema.get("format") != "json":
        return
    try:
        value = json.loads(read_vault_text(path, vault_root=vault_root))
    except (OSError, json.JSONDecodeError, UnicodeError) as exc:
        raise ValueError(f"vault {name} must be valid JSON") from exc
    if not isinstance(value, dict):
        raise ValueError(f"vault {name} must be a JSON object")
    field = schema.get("version_field")
    supported = schema.get("supported_versions")
    if field and isinstance(supported, list) and value.get(field) not in supported:
        raise ValueError(f"vault {name} has an unsupported schema version")
    required_keys = schema.get("required_keys")
    if schema.get("validation_policy") == "blocking" and isinstance(required_keys, dict):
        for key, expected in required_keys.items():
            if key not in value or not isinstance(expected, str) or not _schema_value_matches(
                value[key], expected
            ):
                raise ValueError(f"vault {name} has invalid required key {key}")


def validate_minimum_vault_shape(
    vault_root: str | os.PathLike[str],
    *,
    framework_system_dir: str | os.PathLike[str] | None = None,
) -> Path:
    vault = _real_directory(vault_root, label="vault root")
    framework = resolve_framework_system_dir(framework_system_dir)
    layout = vault_layout(vault, framework_system_dir=framework)
    if layout == "external":
        for raw in VAULT_CONTRACT.get("external_forbidden_paths", []):
            relative = _relative_contract_path(raw, label="external forbidden path")
            candidate = vault / relative
            if candidate.exists() or candidate.is_symlink():
                raise ValueError(f"external vault may not contain {relative.as_posix()}")
    for name in MINIMUM_VAULT_SHAPE:
        entry = VAULT_DATA_PATHS[name]
        path = vault_data_path(name, vault_root=vault, framework_system_dir=framework)
        expected = entry["kind"]
        try:
            if expected == "file":
                fd = open_vault_fd(path, os.O_RDONLY, vault_root=vault)
                os.close(fd)
            else:
                directory_fd = _open_absolute_dir_no_follow(path)
                os.close(directory_fd)
        except FileNotFoundError as exc:
            raise ValueError(f"vault is missing required {name}") from exc
        except (ValueError, OSError) as exc:
            raise ValueError(f"vault has invalid required {name}: {exc}") from exc
        _validate_required_json(name, path, entry, vault_root=vault)
    if layout == "external":
        walk_vault_tree(vault, layout="external")
    return vault


def resolve_vault_root(
    explicit: str | os.PathLike[str] | None = None,
    *,
    framework_system_dir: str | os.PathLike[str] | None = None,
    bind_process: bool = False,
) -> Path:
    """Resolve explicit argument > environment > embedded framework parent."""
    framework = resolve_framework_system_dir(framework_system_dir)
    selected = explicit or os.environ.get("LIFEHUG_VAULT_ROOT") or framework.parent
    root = validate_minimum_vault_shape(selected, framework_system_dir=framework)
    return bind_vault_root(root) if bind_process else root


def bind_vault_root(vault_root: str | os.PathLike[str]) -> Path:
    """Bind this interpreter to one vault; unsafe in-process switching rejects."""
    global _BOUND_VAULT_IDENTITY, _BOUND_VAULT_ROOT
    root = _real_directory(vault_root, label="vault root")
    root_fd = _open_absolute_dir_no_follow(root)
    try:
        info = os.fstat(root_fd)
        identity = (info.st_dev, info.st_ino)
    finally:
        os.close(root_fd)
    if _BOUND_VAULT_ROOT is None:
        _BOUND_VAULT_ROOT = root
        _BOUND_VAULT_IDENTITY = identity
    elif _BOUND_VAULT_ROOT != root or _BOUND_VAULT_IDENTITY != identity:
        raise RuntimeError(
            f"process is already bound to vault {_BOUND_VAULT_ROOT}; start a new process to use {root}"
        )
    return root


def bound_vault_root() -> Path | None:
    return _BOUND_VAULT_ROOT


def _reset_process_binding_for_tests() -> None:
    """Test-only reset; runtime code must never rebind import-bound constants."""
    global _BOUND_VAULT_IDENTITY, _BOUND_VAULT_ROOT
    _BOUND_VAULT_ROOT = None
    _BOUND_VAULT_IDENTITY = None


def bootstrap_cli_vault_root(
    argv: list[str] | tuple[str, ...] | None = None,
    *,
    framework_system_dir: str | os.PathLike[str] | None = None,
) -> Path | None:
    """Apply a top-level ``--vault-root`` before data modules are imported."""
    values = list(sys.argv[1:] if argv is None else argv)
    selected: str | None = None
    for index, value in enumerate(values):
        if value == "--vault-root":
            if index + 1 >= len(values):
                return None  # argparse emits the canonical missing-value error
            selected = values[index + 1]
        elif value.startswith("--vault-root="):
            selected = value.split("=", 1)[1]
    if selected is None:
        return None
    root = resolve_vault_root(
        selected,
        framework_system_dir=framework_system_dir,
        bind_process=True,
    )
    os.environ["LIFEHUG_VAULT_ROOT"] = str(root)
    return root


def normalize_cli_vault_args(argv: list[str] | tuple[str, ...]) -> list[str]:
    """Move the reserved global vault selector before the subcommand."""
    values = list(argv)
    selected: list[str] = []
    remaining: list[str] = []
    index = 0
    while index < len(values):
        value = values[index]
        if value == "--vault-root":
            if index + 1 >= len(values):
                return values  # argparse owns the canonical missing-value error
            if selected:
                raise ValueError("--vault-root may be supplied only once")
            selected = ["--vault-root", values[index + 1]]
            index += 2
            continue
        if value.startswith("--vault-root="):
            if selected:
                raise ValueError("--vault-root may be supplied only once")
            selected = ["--vault-root", value.split("=", 1)[1]]
            index += 1
            continue
        remaining.append(value)
        index += 1
    return [*selected, *remaining]


def tracked_vault_paths(
    vault_root: str | os.PathLike[str],
    *,
    framework_system_dir: str | os.PathLike[str] | None = None,
) -> tuple[str, ...]:
    """Relative roots safe for canonical git housekeeping (never secrets)."""
    vault = resolve_vault_root(vault_root, framework_system_dir=framework_system_dir)
    selected = [
        (vault_relative_path(name, vault_root=vault, framework_system_dir=framework_system_dir), entry["kind"])
        for name, entry in VAULT_DATA_PATHS.items()
        if entry.get("tracked") is True
    ]
    paths: list[Path] = []
    for path, _kind in selected:
        if path not in paths:
            paths.append(path)
    directories = [path for path, kind in selected if kind == "directory"]
    roots = [
        path for path in paths
        if not any(directory != path and directory in path.parents for directory in directories)
    ]
    return tuple(path.as_posix() for path in roots)


def validate_contained_path(
    path: str | os.PathLike[str],
    root: str | os.PathLike[str],
    *,
    label: str = "vault path",
) -> Path:
    """Reject escapes and every existing symlink from ``root`` to ``path``."""
    candidate = Path(path).expanduser()
    boundary = Path(root).expanduser()
    if not candidate.is_absolute():
        candidate = Path.cwd() / candidate
    if not boundary.is_absolute():
        boundary = Path.cwd() / boundary
    candidate = Path(os.path.abspath(candidate))
    boundary = Path(os.path.abspath(boundary))
    try:
        relative = candidate.relative_to(boundary)
    except ValueError as exc:
        raise ValueError(f"{label} escaped its allowed root") from exc
    current = boundary
    for part in (Path(), *[Path(piece) for piece in relative.parts]):
        if part != Path():
            current = current / part
        if current.is_symlink():
            raise ValueError(f"{label} may not traverse symlinks")
        if current.exists() and current != candidate and not current.is_dir():
            raise ValueError(f"{label} has a non-directory parent")
    return candidate


def _relative_to_vault(
    path: str | os.PathLike[str],
    vault_root: str | os.PathLike[str],
) -> Path:
    root = Path(os.path.abspath(Path(vault_root).expanduser()))
    raw = Path(path).expanduser()
    candidate = Path(os.path.abspath(raw if raw.is_absolute() else root / raw))
    try:
        relative = candidate.relative_to(root)
    except ValueError as exc:
        raise ValueError("vault path escaped its selected root") from exc
    if relative == Path(".") or ".." in relative.parts:
        raise ValueError("vault file path must name a child of the selected root")
    return relative


def _open_absolute_dir_no_follow(path: str | os.PathLike[str]) -> int:
    """Open an absolute directory one component at a time without symlinks."""
    absolute = Path(os.path.abspath(Path(path).expanduser()))
    flags = os.O_RDONLY | _DIRECTORY | _NOFOLLOW
    fd = os.open(absolute.anchor, flags)
    try:
        for part in absolute.parts[1:]:
            next_fd = os.open(part, flags, dir_fd=fd)
            os.close(fd)
            fd = next_fd
        if _BOUND_VAULT_ROOT == absolute and _BOUND_VAULT_IDENTITY is not None:
            info = os.fstat(fd)
            if (info.st_dev, info.st_ino) != _BOUND_VAULT_IDENTITY:
                raise ValueError("bound vault root identity changed during process lifetime")
        return fd
    except BaseException:
        os.close(fd)
        raise


def _open_relative_dir_no_follow(root_fd: int, relative: Path, *, create: bool) -> int:
    fd = os.dup(root_fd)
    flags = os.O_RDONLY | _DIRECTORY | _NOFOLLOW
    try:
        for part in relative.parts:
            try:
                next_fd = os.open(part, flags, dir_fd=fd)
            except FileNotFoundError:
                if not create:
                    raise
                try:
                    os.mkdir(part, mode=0o700, dir_fd=fd)
                except FileExistsError:
                    pass
                next_fd = os.open(part, flags, dir_fd=fd)
            os.close(fd)
            fd = next_fd
        return fd
    except BaseException:
        os.close(fd)
        raise


def _verify_directory_binding(
    vault_root: str | os.PathLike[str],
    parent: Path,
    pinned_fd: int,
) -> None:
    """Reject a root/intermediate swap after the pinned dirfd was acquired."""
    root_fd = _open_absolute_dir_no_follow(vault_root)
    try:
        current_fd = _open_relative_dir_no_follow(root_fd, parent, create=False)
        try:
            current = os.fstat(current_fd)
            pinned = os.fstat(pinned_fd)
            if (current.st_dev, current.st_ino) != (pinned.st_dev, pinned.st_ino):
                raise ValueError("vault directory binding changed during operation")
        finally:
            os.close(current_fd)
    except OSError as exc:
        raise ValueError("vault directory binding changed during operation") from exc
    finally:
        os.close(root_fd)


def ensure_vault_directory(
    path: str | os.PathLike[str],
    *,
    vault_root: str | os.PathLike[str],
) -> Path:
    """Create/open one vault directory using no-follow component traversal."""
    relative = _relative_to_vault(path, vault_root)
    root_fd = _open_absolute_dir_no_follow(vault_root)
    try:
        directory_fd = _open_relative_dir_no_follow(root_fd, relative, create=True)
        try:
            _verify_directory_binding(vault_root, relative, directory_fd)
        finally:
            os.close(directory_fd)
    except OSError as exc:
        raise ValueError("vault directory is missing, special, or symlinked") from exc
    finally:
        os.close(root_fd)
    return Path(os.path.abspath(Path(vault_root).expanduser())) / relative


def open_vault_file(
    path: str | os.PathLike[str],
    mode: str = "r",
    *,
    vault_root: str | os.PathLike[str],
    encoding: str | None = None,
    errors: str | None = None,
    create_parents: bool = False,
    file_mode: int = 0o600,
    _before_final_open: Callable[[], None] | None = None,
):
    """Open a regular vault file through pinned no-follow directory handles."""
    if mode not in {"r", "rb", "w", "wb", "a", "ab", "x", "xb"}:
        raise ValueError(f"unsupported secure vault open mode: {mode}")
    relative = _relative_to_vault(path, vault_root)
    root_fd = _open_absolute_dir_no_follow(vault_root)
    parent_fd: int | None = None
    try:
        parent_fd = _open_relative_dir_no_follow(
            root_fd,
            relative.parent if relative.parent != Path(".") else Path(),
            create=create_parents,
        )
        if _before_final_open:
            _before_final_open()
        _verify_directory_binding(vault_root, relative.parent, parent_fd)
        access = {
            "r": os.O_RDONLY,
            "rb": os.O_RDONLY,
            "w": os.O_WRONLY | os.O_CREAT | os.O_TRUNC,
            "wb": os.O_WRONLY | os.O_CREAT | os.O_TRUNC,
            "a": os.O_WRONLY | os.O_CREAT | os.O_APPEND,
            "ab": os.O_WRONLY | os.O_CREAT | os.O_APPEND,
            "x": os.O_WRONLY | os.O_CREAT | os.O_EXCL,
            "xb": os.O_WRONLY | os.O_CREAT | os.O_EXCL,
        }[mode]
        fd = os.open(relative.name, access | _NOFOLLOW, file_mode, dir_fd=parent_fd)
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            os.close(fd)
            raise ValueError("vault path must be a regular file")
        kwargs: dict[str, object] = {}
        if "b" not in mode:
            kwargs = {"encoding": encoding or "utf-8", "errors": errors}
        return os.fdopen(fd, mode, **kwargs)
    except FileNotFoundError:
        raise
    except OSError as exc:
        raise ValueError("vault file is missing, special, or symlinked") from exc
    finally:
        if parent_fd is not None:
            os.close(parent_fd)
        os.close(root_fd)


def open_vault_fd(
    path: str | os.PathLike[str],
    flags: int,
    *,
    vault_root: str | os.PathLike[str],
    mode: int = 0o600,
    create_parents: bool = False,
) -> int:
    """Open a regular vault file descriptor through the same no-follow boundary."""
    relative = _relative_to_vault(path, vault_root)
    root_fd = _open_absolute_dir_no_follow(vault_root)
    parent_fd: int | None = None
    try:
        parent_fd = _open_relative_dir_no_follow(
            root_fd,
            relative.parent if relative.parent != Path(".") else Path(),
            create=create_parents,
        )
        _verify_directory_binding(vault_root, relative.parent, parent_fd)
        fd = os.open(relative.name, flags | _NOFOLLOW, mode, dir_fd=parent_fd)
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            os.close(fd)
            raise ValueError("vault path must be a regular file")
        return fd
    except FileNotFoundError:
        raise
    except OSError as exc:
        raise ValueError("vault file is missing, special, or symlinked") from exc
    finally:
        if parent_fd is not None:
            os.close(parent_fd)
        os.close(root_fd)


def read_vault_bytes(
    path: str | os.PathLike[str],
    *,
    vault_root: str | os.PathLike[str],
    _before_final_open: Callable[[], None] | None = None,
) -> bytes:
    with open_vault_file(
        path,
        "rb",
        vault_root=vault_root,
        _before_final_open=_before_final_open,
    ) as handle:
        return handle.read()


def read_vault_text(
    path: str | os.PathLike[str],
    *,
    vault_root: str | os.PathLike[str],
    encoding: str = "utf-8",
    errors: str | None = None,
    _before_final_open: Callable[[], None] | None = None,
) -> str:
    with open_vault_file(
        path,
        "r",
        vault_root=vault_root,
        encoding=encoding,
        errors=errors,
        _before_final_open=_before_final_open,
    ) as handle:
        return handle.read()


def atomic_write_vault_bytes(
    path: str | os.PathLike[str],
    content: bytes,
    *,
    vault_root: str | os.PathLike[str],
    mode: int = 0o600,
    _before_replace: Callable[[], None] | None = None,
) -> None:
    """Atomically write without following roots, parents, or destinations."""
    relative = _relative_to_vault(path, vault_root)
    root_fd = _open_absolute_dir_no_follow(vault_root)
    parent_fd: int | None = None
    tmp_name = f".{relative.name}.{secrets.token_hex(8)}.tmp"
    try:
        parent_fd = _open_relative_dir_no_follow(
            root_fd,
            relative.parent if relative.parent != Path(".") else Path(),
            create=True,
        )
        fd = os.open(
            tmp_name,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | _NOFOLLOW,
            mode,
            dir_fd=parent_fd,
        )
        try:
            with os.fdopen(fd, "wb", closefd=False) as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
        finally:
            os.close(fd)
        if _before_replace:
            _before_replace()
        _verify_directory_binding(vault_root, relative.parent, parent_fd)
        try:
            destination = os.stat(relative.name, dir_fd=parent_fd, follow_symlinks=False)
        except FileNotFoundError:
            destination = None
        if destination is not None and not stat.S_ISREG(destination.st_mode):
            raise ValueError("vault destination must be a regular file")
        os.rename(tmp_name, relative.name, src_dir_fd=parent_fd, dst_dir_fd=parent_fd)
        os.fsync(parent_fd)
    except OSError as exc:
        raise ValueError("vault write target is special, symlinked, or changed") from exc
    finally:
        if parent_fd is not None:
            with contextlib.suppress(FileNotFoundError):
                os.unlink(tmp_name, dir_fd=parent_fd)
            os.close(parent_fd)
        os.close(root_fd)


def atomic_write_vault_text(
    path: str | os.PathLike[str],
    content: str,
    *,
    vault_root: str | os.PathLike[str],
    encoding: str = "utf-8",
    mode: int = 0o600,
    _before_replace: Callable[[], None] | None = None,
) -> None:
    atomic_write_vault_bytes(
        path,
        content.encode(encoding),
        vault_root=vault_root,
        mode=mode,
        _before_replace=_before_replace,
    )


def atomic_create_vault_bytes(
    path: str | os.PathLike[str],
    content: bytes,
    *,
    vault_root: str | os.PathLike[str],
    mode: int = 0o600,
) -> None:
    """Publish a new regular file atomically; never replace an existing node."""
    relative = _relative_to_vault(path, vault_root)
    root_fd = _open_absolute_dir_no_follow(vault_root)
    parent_fd: int | None = None
    tmp_name = f".{relative.name}.{secrets.token_hex(8)}.tmp"
    try:
        parent_fd = _open_relative_dir_no_follow(
            root_fd,
            relative.parent if relative.parent != Path(".") else Path(),
            create=True,
        )
        fd = os.open(
            tmp_name,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | _NOFOLLOW,
            mode,
            dir_fd=parent_fd,
        )
        try:
            with os.fdopen(fd, "wb", closefd=False) as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
        finally:
            os.close(fd)
        _verify_directory_binding(vault_root, relative.parent, parent_fd)
        os.link(
            tmp_name,
            relative.name,
            src_dir_fd=parent_fd,
            dst_dir_fd=parent_fd,
            follow_symlinks=False,
        )
        os.fsync(parent_fd)
    except FileExistsError:
        raise
    except OSError as exc:
        raise ValueError("vault create target is special, symlinked, or changed") from exc
    finally:
        if parent_fd is not None:
            with contextlib.suppress(FileNotFoundError):
                os.unlink(tmp_name, dir_fd=parent_fd)
            os.close(parent_fd)
        os.close(root_fd)


def append_vault_text(
    path: str | os.PathLike[str],
    content: str,
    *,
    vault_root: str | os.PathLike[str],
    encoding: str = "utf-8",
    mode: int = 0o600,
) -> None:
    with open_vault_file(
        path,
        "a",
        vault_root=vault_root,
        encoding=encoding,
        create_parents=True,
        file_mode=mode,
    ) as handle:
        handle.write(content)
        handle.flush()
        os.fsync(handle.fileno())


def unlink_vault_file(
    path: str | os.PathLike[str],
    *,
    vault_root: str | os.PathLike[str],
    missing_ok: bool = False,
) -> None:
    """Remove one regular vault file without following its parent or final node."""
    relative = _relative_to_vault(path, vault_root)
    root_fd = _open_absolute_dir_no_follow(vault_root)
    parent_fd: int | None = None
    try:
        parent_fd = _open_relative_dir_no_follow(
            root_fd,
            relative.parent if relative.parent != Path(".") else Path(),
            create=False,
        )
        _verify_directory_binding(vault_root, relative.parent, parent_fd)
        try:
            info = os.stat(relative.name, dir_fd=parent_fd, follow_symlinks=False)
        except FileNotFoundError:
            if missing_ok:
                return
            raise
        if not stat.S_ISREG(info.st_mode):
            raise ValueError("vault path must be a regular file")
        os.unlink(relative.name, dir_fd=parent_fd)
        os.fsync(parent_fd)
    except OSError as exc:
        raise ValueError("vault delete target is special, symlinked, or changed") from exc
    finally:
        if parent_fd is not None:
            os.close(parent_fd)
        os.close(root_fd)


def classify_contract_path(
    relative_path: str | os.PathLike[str],
    *,
    authority: str,
    layout: str = "external",
) -> str:
    """Classify a relative path without consulting policy or the filesystem."""
    relative = _relative_contract_path(str(relative_path), label="classification path")
    if authority == "vault":
        if layout not in {"embedded", "external"}:
            raise ValueError("layout must be embedded or external")
        for entry in VAULT_DATA_PATHS.values():
            raw = entry[f"{layout}_path"]
            candidate = _relative_contract_path(raw, label="data classification path")
            if relative == candidate or (
                entry["kind"] == "directory" and candidate in relative.parents
            ):
                return "durable_data"
        return "unknown"
    if authority == "framework":
        for entry in FRAMEWORK_PATHS.values():
            candidate = _relative_contract_path(entry["path"], label="framework classification path")
            if relative == candidate or (
                entry["kind"] == "directory" and candidate in relative.parents
            ):
                return "framework"
        return "unknown"
    raise ValueError("authority must be vault or framework")


def walk_vault_tree(
    vault_root: str | os.PathLike[str],
    *,
    layout: str = "external",
) -> tuple[dict[str, str], ...]:
    """Deterministically walk regular files/directories; reject every special node."""
    root = _real_directory(vault_root, label="vault root")
    root_fd = _open_absolute_dir_no_follow(root)
    rows: list[dict[str, str]] = []

    def visit(directory_fd: int, prefix: Path) -> None:
        with os.scandir(directory_fd) as scan:
            entries = sorted(scan, key=lambda entry: entry.name)
        for entry in entries:
            relative = prefix / entry.name
            info = entry.stat(follow_symlinks=False)
            if stat.S_ISLNK(info.st_mode) or not (
                stat.S_ISREG(info.st_mode) or stat.S_ISDIR(info.st_mode)
            ):
                raise ValueError(f"vault tree contains forbidden special path {relative.as_posix()}")
            kind = "directory" if stat.S_ISDIR(info.st_mode) else "file"
            rows.append({
                "path": relative.as_posix(),
                "kind": kind,
                "classification": classify_contract_path(
                    relative, authority="vault", layout=layout
                ),
            })
            if kind == "directory":
                child_fd = os.open(
                    entry.name,
                    os.O_RDONLY | _DIRECTORY | _NOFOLLOW,
                    dir_fd=directory_fd,
                )
                try:
                    visit(child_fd, relative)
                finally:
                    os.close(child_fd)

    try:
        visit(root_fd, Path())
        _verify_directory_binding(root, Path(), root_fd)
    except OSError as exc:
        raise ValueError("vault tree changed or contains a forbidden path") from exc
    finally:
        os.close(root_fd)
    return tuple(rows)


def exported_contract() -> dict[str, object]:
    """Stable one-way export for hosted parity; contains no machine-local roots."""
    return json.loads(json.dumps(VAULT_CONTRACT, sort_keys=True))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Lifehug vault path contract")
    sub = parser.add_subparsers(dest="command", required=True)
    paths = sub.add_parser("git-paths", help="Print tracked vault roots, one per line")
    paths.add_argument("--vault-root", type=Path)
    data_path = sub.add_parser("data-path", help="Print one selected vault-relative path")
    data_path.add_argument("name", choices=sorted(VAULT_DATA_PATHS))
    data_path.add_argument("--vault-root", type=Path)
    root_path = sub.add_parser("root", help="Validate and print the selected vault root")
    root_path.add_argument("--vault-root", type=Path)
    sub.add_parser("contract", help="Print the versioned JSON contract")
    classify = sub.add_parser("classify", help="Classify one contract-relative path")
    classify.add_argument("path")
    classify.add_argument("--authority", choices=("vault", "framework"), required=True)
    classify.add_argument("--layout", choices=("embedded", "external"), default="external")
    walk = sub.add_parser("walk", help="No-follow deterministic vault tree preflight")
    walk.add_argument("--vault-root", type=Path)
    args = parser.parse_args(argv)
    if args.command == "contract":
        print(json.dumps(exported_contract(), indent=2, sort_keys=True))
        return 0
    if args.command == "classify":
        print(classify_contract_path(args.path, authority=args.authority, layout=args.layout))
        return 0
    root = resolve_vault_root(args.vault_root)
    if args.command == "root":
        print(root)
        return 0
    if args.command == "data-path":
        print(vault_relative_path(args.name, vault_root=root))
        return 0
    if args.command == "walk":
        print(json.dumps(walk_vault_tree(root, layout=vault_layout(root)), indent=2))
        return 0
    print("\n".join(tracked_vault_paths(root)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
