#!/usr/bin/env python3
"""One path authority for the installed framework and active user vault.

The repository embeds both today, while a future vault-only layout can point
an installed framework at a separate data directory.  Callers should keep
these roots distinct: executable assets come from ``framework_system_dir``;
durable user data comes from ``resolve_vault_root``.
"""

from __future__ import annotations

import os
from pathlib import Path

EMBEDDED_FRAMEWORK_SYSTEM_DIR = Path(__file__).resolve().parent


def _real_directory(value: str | os.PathLike[str], *, label: str) -> Path:
    candidate = Path(value).expanduser()
    if not candidate.is_absolute():
        candidate = Path.cwd() / candidate
    # Check the supplied path before any resolve(), which would erase the fact
    # that the configured vault root itself was a symlink.
    if candidate.is_symlink():
        raise ValueError(f"{label} may not be a symlink")
    if not candidate.is_dir():
        raise ValueError(f"{label} must be an existing directory")
    return candidate.absolute()


def resolve_framework_system_dir(
    explicit: str | os.PathLike[str] | None = None,
) -> Path:
    """Resolve executable assets independently from the user vault."""
    selected = explicit or os.environ.get("LIFEHUG_FRAMEWORK_SYSTEM_DIR")
    return _real_directory(
        selected or EMBEDDED_FRAMEWORK_SYSTEM_DIR,
        label="framework system root",
    )


def resolve_vault_root(
    explicit: str | os.PathLike[str] | None = None,
    *,
    framework_system_dir: str | os.PathLike[str] | None = None,
) -> Path:
    """Resolve explicit argument > environment > embedded framework parent."""
    framework = resolve_framework_system_dir(framework_system_dir)
    selected = explicit or os.environ.get("LIFEHUG_VAULT_ROOT") or framework.parent
    return _real_directory(selected, label="vault root")


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
    candidate = candidate.absolute()
    boundary = boundary.absolute()
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
