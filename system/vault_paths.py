#!/usr/bin/env python3
"""Authoritative framework/vault roots and versioned durable-data contract.

Executable assets always come from the installed framework. Durable user data
always comes from the selected vault. ``vault_contract.json`` is the one
machine-readable path/minimum-shape/schema table consumed here and, after an
explicit package pin, by hosted import/preflight parity checks.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

EMBEDDED_FRAMEWORK_SYSTEM_DIR = Path(__file__).resolve().parent
VAULT_CONTRACT_FILE = EMBEDDED_FRAMEWORK_SYSTEM_DIR / "vault_contract.json"


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


VAULT_CONTRACT = _load_contract()
VAULT_DATA_PATHS: dict[str, dict[str, object]] = VAULT_CONTRACT["data_paths"]  # type: ignore[assignment]
FRAMEWORK_PATHS: dict[str, str] = VAULT_CONTRACT["framework_paths"]  # type: ignore[assignment]
MINIMUM_VAULT_SHAPE = tuple(
    name for name, entry in VAULT_DATA_PATHS.items() if entry.get("required") is True
)
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
    raw = entry.get("embedded_path") if layout == "embedded" else None
    return _relative_contract_path(raw or entry["path"], label=f"data path {name}")


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
        relative = _relative_contract_path(FRAMEWORK_PATHS[name], label=f"framework path {name}")
    except KeyError as exc:
        raise KeyError(f"unknown Lifehug framework path: {name}") from exc
    root = resolve_framework_root(framework_system_dir)
    return validate_contained_path(root / relative, root, label=f"framework path {name}")


def _validate_required_json(name: str, path: Path, entry: dict[str, object]) -> None:
    schema = entry.get("schema")
    if not isinstance(schema, dict) or schema.get("format") != "json":
        return
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeError) as exc:
        raise ValueError(f"vault {name} must be valid JSON") from exc
    if not isinstance(value, dict):
        raise ValueError(f"vault {name} must be a JSON object")
    field = schema.get("version_field")
    supported = schema.get("supported")
    if field and isinstance(supported, list) and value.get(field) not in supported:
        raise ValueError(f"vault {name} has an unsupported schema version")


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
        present = path.is_file() if expected == "file" else path.is_dir()
        if not present:
            raise ValueError(f"vault is missing required {name}")
        _validate_required_json(name, path, entry)
    return vault


def resolve_vault_root(
    explicit: str | os.PathLike[str] | None = None,
    *,
    framework_system_dir: str | os.PathLike[str] | None = None,
) -> Path:
    """Resolve explicit argument > environment > embedded framework parent."""
    framework = resolve_framework_system_dir(framework_system_dir)
    selected = explicit or os.environ.get("LIFEHUG_VAULT_ROOT") or framework.parent
    return validate_minimum_vault_shape(selected, framework_system_dir=framework)


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
    root = resolve_vault_root(selected, framework_system_dir=framework_system_dir)
    os.environ["LIFEHUG_VAULT_ROOT"] = str(root)
    return root


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
    args = parser.parse_args(argv)
    if args.command == "contract":
        print(json.dumps(VAULT_CONTRACT, indent=2))
        return 0
    root = resolve_vault_root(args.vault_root)
    if args.command == "root":
        print(root)
        return 0
    if args.command == "data-path":
        print(vault_relative_path(args.name, vault_root=root))
        return 0
    print("\n".join(tracked_vault_paths(root)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
