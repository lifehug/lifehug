#!/usr/bin/env python3
"""Registered Interaction packages and deterministic asset composition.

The registry is framework authority, never vault data.  Child Interactions
declare their parent and per-asset composition policy in flat-scalar
``interaction.yaml``.  Callers cannot override that policy.
"""

from __future__ import annotations

import json
import re
from pathlib import Path, PurePosixPath

from lifehug_core import INTERACTIONS_DIR, _parse_simple_yaml

REGISTRY_SCHEMA_VERSION = 1
REGISTRY_FILE = "registry.json"
REQUIRED_FILES = frozenset(
    {
        "README.md",
        "interaction.yaml",
        "prompt/identity.md",
        "prompt/behavior.md",
        "prompt/examples.md",
        "prompt/turn-instructions.md",
        "context/manifest.md",
        "overlays/anthropic.md",
        "overlays/moonshot.md",
        "overlays/openai.md",
        "overlays/qwen.md",
        "evals/lints.yaml",
        "evals/rubrics.md",
        "evals/goldens/README.md",
    }
)
COMPOSABLE_FILES = frozenset(
    {
        "prompt/identity.md",
        "prompt/behavior.md",
        "prompt/examples.md",
        "prompt/turn-instructions.md",
        "context/manifest.md",
        "router/router.md",
        "router/deflection.md",
    }
)
ID_RE = re.compile(r"^[a-z][a-z0-9_]*$")


class InteractionRegistryError(ValueError):
    """A registry, manifest, lineage, or composition contract is invalid."""


def _root(framework_root: str | Path | None) -> Path:
    if framework_root is None:
        return INTERACTIONS_DIR
    return Path(framework_root) / "interactions"


def _relative_path(value: object, *, name: str) -> str:
    if not isinstance(value, str) or not value:
        raise InteractionRegistryError(f"{name} must be a non-empty relative path")
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or "." in path.parts:
        raise InteractionRegistryError(f"{name} must stay inside its package")
    if "\\" in value or value.startswith("/"):
        raise InteractionRegistryError(f"{name} must use a safe POSIX relative path")
    return value


def _pipe_set(value: str | None, *, name: str) -> frozenset[str]:
    if not value:
        return frozenset()
    parts = value.split("|")
    if any(not part for part in parts) or len(parts) != len(set(parts)):
        raise InteractionRegistryError(f"{name} must contain unique non-empty paths")
    return frozenset(_relative_path(part, name=name) for part in parts)


def load_interaction_registry(*, framework_root: str | Path | None = None) -> dict:
    """Load and strictly validate the closed Interaction registry."""
    path = _root(framework_root) / REGISTRY_FILE
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise InteractionRegistryError(
            f"cannot load Interaction registry: {exc}"
        ) from exc
    if not isinstance(value, dict) or set(value) != {"schema_version", "interactions"}:
        raise InteractionRegistryError(
            "registry keys must be schema_version, interactions"
        )
    if value["schema_version"] != REGISTRY_SCHEMA_VERSION:
        raise InteractionRegistryError("registry.schema_version must be 1")
    entries = value["interactions"]
    if not isinstance(entries, list) or not entries:
        raise InteractionRegistryError("registry.interactions must be non-empty")
    ids: set[str] = set()
    packages: set[str] = set()
    normalized: list[dict[str, str]] = []
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict) or set(entry) != {"id", "package"}:
            raise InteractionRegistryError(
                f"registry.interactions[{index}] has invalid keys"
            )
        interaction_id = entry["id"]
        package = entry["package"]
        if not isinstance(interaction_id, str) or not ID_RE.fullmatch(interaction_id):
            raise InteractionRegistryError(
                f"registry.interactions[{index}].id is invalid"
            )
        package = _relative_path(
            package, name=f"registry.interactions[{index}].package"
        )
        if "/" in package or not ID_RE.fullmatch(package):
            raise InteractionRegistryError(
                f"registry.interactions[{index}].package is invalid"
            )
        if interaction_id in ids or package in packages:
            raise InteractionRegistryError("registry ids and packages must be unique")
        ids.add(interaction_id)
        packages.add(package)
        normalized.append({"id": interaction_id, "package": package})
    return {"schema_version": REGISTRY_SCHEMA_VERSION, "interactions": normalized}


def _entry(interaction_id: str, *, framework_root: str | Path | None) -> dict[str, str]:
    if not isinstance(interaction_id, str) or not ID_RE.fullmatch(interaction_id):
        raise InteractionRegistryError("interaction_id is invalid")
    for entry in load_interaction_registry(framework_root=framework_root)[
        "interactions"
    ]:
        if entry["id"] == interaction_id:
            return entry
    raise InteractionRegistryError(f"unregistered Interaction: {interaction_id}")


def _package_dir(interaction_id: str, *, framework_root: str | Path | None) -> Path:
    entry = _entry(interaction_id, framework_root=framework_root)
    return _root(framework_root) / entry["package"]


def load_interaction_manifest(
    interaction_id: str, *, framework_root: str | Path | None = None
) -> dict[str, str]:
    """Load a registered package's flat-scalar manifest."""
    path = (
        _package_dir(interaction_id, framework_root=framework_root) / "interaction.yaml"
    )
    try:
        manifest = _parse_simple_yaml(path)
    except OSError as exc:
        raise InteractionRegistryError(
            f"cannot load {interaction_id} manifest: {exc}"
        ) from exc
    if not manifest:
        raise InteractionRegistryError(f"{interaction_id} manifest is missing or empty")
    if manifest.get("interaction") != interaction_id:
        raise InteractionRegistryError(
            f"{interaction_id} manifest interaction must match registry id"
        )
    if not manifest.get("version"):
        raise InteractionRegistryError(f"{interaction_id} manifest version is required")
    return manifest


def resolve_interaction_lineage(
    interaction_id: str, *, framework_root: str | Path | None = None
) -> tuple[str, ...]:
    """Return registered ancestry from root parent to requested child."""
    reverse: list[str] = []
    current = interaction_id
    seen: set[str] = set()
    while True:
        if current in seen:
            raise InteractionRegistryError("Interaction inheritance cycle")
        seen.add(current)
        manifest = load_interaction_manifest(current, framework_root=framework_root)
        reverse.append(current)
        parent = manifest.get("extends")
        required_version = manifest.get("extends.version")
        if parent is None:
            if required_version is not None:
                raise InteractionRegistryError(
                    f"{current} has extends.version without extends"
                )
            break
        if not required_version:
            raise InteractionRegistryError(f"{current} must pin extends.version")
        parent_manifest = load_interaction_manifest(
            parent, framework_root=framework_root
        )
        if parent_manifest["version"] != required_version:
            raise InteractionRegistryError(
                f"{current} requires {parent} {required_version}, got {parent_manifest['version']}"
            )
        current = parent
    return tuple(reversed(reverse))


def _composition_policy(
    interaction_id: str, *, framework_root: str | Path | None
) -> tuple[frozenset[str], frozenset[str]]:
    manifest = load_interaction_manifest(interaction_id, framework_root=framework_root)
    append = _pipe_set(manifest.get("composition.append"), name="composition.append")
    leaf = _pipe_set(manifest.get("composition.leaf"), name="composition.leaf")
    if append & leaf:
        raise InteractionRegistryError(
            "composition.append and composition.leaf overlap"
        )
    unknown = (append | leaf) - COMPOSABLE_FILES
    if unknown:
        raise InteractionRegistryError(
            f"composition contains unknown assets: {sorted(unknown)}"
        )
    if manifest.get("extends") and (not append or not leaf):
        raise InteractionRegistryError(
            "child composition requires append and leaf assets"
        )
    return append, leaf


def compose_interaction_asset(
    interaction_id: str,
    relative_path: str,
    *,
    framework_root: str | Path | None = None,
) -> str:
    """Compose one manifest-declared asset with deterministic provenance."""
    relative_path = _relative_path(relative_path, name="relative_path")
    if relative_path not in COMPOSABLE_FILES:
        raise InteractionRegistryError(
            f"{relative_path} is not a composable Interaction asset"
        )
    lineage = resolve_interaction_lineage(interaction_id, framework_root=framework_root)
    if len(lineage) == 1:
        packages = lineage
    else:
        append, leaf = _composition_policy(
            interaction_id, framework_root=framework_root
        )
        if relative_path in append:
            packages = lineage
        elif relative_path in leaf:
            packages = (interaction_id,)
        else:
            raise InteractionRegistryError(
                f"{relative_path} is not declared in {interaction_id} composition"
            )
    chunks: list[str] = []
    for package in packages:
        path = _package_dir(package, framework_root=framework_root) / relative_path
        try:
            source = path.read_bytes().decode("utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            raise InteractionRegistryError(
                f"missing composed asset {package}/{relative_path}"
            ) from exc
        marker = f"<!-- interaction:{package} asset:{relative_path} -->"
        chunks.append(f"{marker}\n{source}")
    return "\n".join(chunks)


def audit_interaction_package(
    interaction_id: str, *, framework_root: str | Path | None = None
) -> list[str]:
    """Return deterministic audit errors; an empty list is executable/seatable."""
    errors: list[str] = []
    try:
        package_dir = _package_dir(interaction_id, framework_root=framework_root)
        manifest = load_interaction_manifest(
            interaction_id, framework_root=framework_root
        )
        resolve_interaction_lineage(interaction_id, framework_root=framework_root)
        append, leaf = _composition_policy(
            interaction_id, framework_root=framework_root
        )
    except InteractionRegistryError as exc:
        return [str(exc)]
    for relative_path in sorted(REQUIRED_FILES):
        if not (package_dir / relative_path).is_file():
            errors.append(f"missing required asset: {relative_path}")
    personas = package_dir / "evals" / "personas"
    if not personas.is_dir() or not any(path.is_file() for path in personas.iterdir()):
        errors.append("evals/personas must contain at least one definition")
    router_required = (package_dir / "router").is_dir() or bool(
        {"router/router.md", "router/deflection.md"} & (append | leaf)
    )
    if router_required:
        for relative_path in ("router/router.md", "router/deflection.md"):
            if not (package_dir / relative_path).is_file():
                errors.append(f"missing required asset: {relative_path}")
    if manifest.get("extends"):
        declared = append | leaf
        if declared != COMPOSABLE_FILES:
            errors.append(
                "composition policy must cover every prompt/context/router asset exactly"
            )
        for relative_path in sorted(declared):
            try:
                compose_interaction_asset(
                    interaction_id, relative_path, framework_root=framework_root
                )
            except InteractionRegistryError as exc:
                errors.append(str(exc))
    return errors
