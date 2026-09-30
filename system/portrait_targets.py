#!/usr/bin/env python3
"""The graph portrait's knobs: one declarative file, one vault override.

Owner instruction (2026-09-29): "I'm sure we're going to adjust all these as we
go, so design them in a way that they're adjustable." Every number the graph
portrait uses lives in ``system/portrait_targets.json`` (shipped with the
framework). A vault may override any subset of it in
``state/portrait_targets.json`` — same shape, only the keys it wants to change.

The override is validated on load against the framework file itself: a key the
framework does not have, a value of the wrong type, or a value outside its
closed vocabulary rejects the WHOLE override (never half of it), and the reason
is reported — the graph keeps drawing on the framework values and ``doctor``
names the problem. ``lifehug doctor`` prints every effective value and where it
came from (:func:`effective_rows`). Keys starting with ``_`` are comments.

``serve_wiki.py`` holds no portrait numbers of its own; it reads them here.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

FRAMEWORK_FILE = Path(__file__).resolve().parent / "portrait_targets.json"
OVERRIDE_NAME = "portrait_targets.json"
FRAMEWORK_ORIGIN = "framework system/portrait_targets.json"
OVERRIDE_ORIGIN = "vault state/portrait_targets.json"

#: Closed vocabularies for string knobs (dotted key → allowed values).
ENUMS: dict[str, tuple[str, ...]] = {
    "credit.split": ("equal", "whole"),
}


class PortraitConfigError(ValueError):
    """The framework file itself is unreadable or malformed."""


def _strip_comments(value):
    if isinstance(value, dict):
        return {k: _strip_comments(v) for k, v in value.items() if not str(k).startswith("_")}
    return value


def _read(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("top level must be an object")
    return _strip_comments(data)


def _flatten(tree: dict, prefix: str = "") -> dict[str, object]:
    out: dict[str, object] = {}
    for key, value in tree.items():
        dotted = f"{prefix}{key}"
        if isinstance(value, dict):
            out.update(_flatten(value, dotted + "."))
        else:
            out[dotted] = value
    return out


def _same_kind(default: object, value: object) -> bool:
    if isinstance(default, bool):
        return isinstance(value, bool)
    if isinstance(default, (int, float)):
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if isinstance(default, list):
        return isinstance(value, list) and all(isinstance(v, type(d)) for d in default[:1] for v in value)
    return isinstance(value, type(default))


def validate_override(framework: dict, override: dict) -> list[str]:
    """Every reason ``override`` cannot be applied on top of ``framework``."""
    errors: list[str] = []
    flat_fw = _flatten(framework)
    fw_tables = {k.rsplit(".", 1)[0] for k in flat_fw if "." in k}
    for key, value in _flatten(override).items():
        if key == "schema_version":
            if value != framework.get("schema_version"):
                errors.append(f"schema_version {value!r} != framework {framework.get('schema_version')!r}")
            continue
        if key not in flat_fw:
            # A whole new row in an open table (e.g. a new type) is allowed
            # only where the framework marks the table open.
            parent = key.rsplit(".", 1)[0] if "." in key else ""
            if parent in fw_tables and _is_open_table(framework, parent):
                if not isinstance(value, (int, float)) or isinstance(value, bool) or value < 0:
                    errors.append(f"{key}: must be a number >= 0")
                continue
            errors.append(f"{key}: not a framework key")
            continue
        default = flat_fw[key]
        if not _same_kind(default, value):
            errors.append(f"{key}: expected {type(default).__name__}, got {type(value).__name__}")
            continue
        if isinstance(value, (int, float)) and not isinstance(value, bool) and value < 0:
            errors.append(f"{key}: must be >= 0")
        if key in ENUMS and value not in ENUMS[key]:
            errors.append(f"{key}: {value!r} not in {list(ENUMS[key])}")
    return errors


def _is_open_table(framework: dict, dotted: str) -> bool:
    node: object = framework
    for part in dotted.split("."):
        if not isinstance(node, dict):
            return False
        node = node.get(part)
    return isinstance(node, dict) and bool(node.get("__open__"))


def _merge(base: dict, over: dict) -> dict:
    out = dict(base)
    for key, value in over.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _merge(out[key], value)
        else:
            out[key] = value
    return out


@dataclass
class PortraitConfig:
    values: dict
    origin: dict[str, str]
    errors: list[str] = field(default_factory=list)
    override_path: Path | None = None

    def get(self, dotted: str):
        node: object = self.values
        for part in dotted.split("."):
            node = node[part]  # type: ignore[index]
        return node


def _load_framework() -> dict:
    try:
        raw = json.loads(FRAMEWORK_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PortraitConfigError(f"{FRAMEWORK_FILE.name} unreadable: {exc}") from exc
    return raw


def load(state_dir: Path | None = None) -> PortraitConfig:
    """Framework values, with the vault override applied if it validates."""
    raw_fw = _load_framework()
    framework = _strip_comments(raw_fw)
    # Keep open-table markers for validation, not for values.
    marks = _open_marks(raw_fw)
    origin = {k: FRAMEWORK_ORIGIN for k in _flatten(framework)}
    cfg = PortraitConfig(values=framework, origin=origin)
    if state_dir is None:
        return cfg
    path = Path(state_dir) / OVERRIDE_NAME
    cfg.override_path = path
    if not path.is_file():
        return cfg
    try:
        override = _read(path)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        cfg.errors.append(f"{OVERRIDE_ORIGIN} unreadable: {exc}")
        return cfg
    errors = validate_override(_merge(framework, marks), override)
    if errors:
        cfg.errors.extend(f"{OVERRIDE_ORIGIN}: {e}" for e in errors)
        return cfg
    override.pop("schema_version", None)
    cfg.values = _merge(framework, override)
    for key in _flatten(override):
        cfg.origin[key] = OVERRIDE_ORIGIN
    return cfg


def _open_marks(raw: dict) -> dict:
    """Only the ``__open__`` markers of ``raw``, as a nested tree."""
    out: dict = {}
    for key, value in raw.items():
        if isinstance(value, dict):
            sub = _open_marks(value)
            if value.get("__open__"):
                sub["__open__"] = True
            if sub:
                out[key] = sub
    return out


def effective_rows(cfg: PortraitConfig) -> list[tuple[str, object, str]]:
    """(dotted key, effective value, where it came from), sorted by key."""
    flat = _flatten(cfg.values)
    return [(k, flat[k], cfg.origin.get(k, OVERRIDE_ORIGIN)) for k in sorted(flat)]


# Framework values as module constants — for the handbook's parity gate and
# for readers that want the shipped default. The JSON file is the authority.
_FW = _strip_comments(_load_framework())
RADIUS_MIN = _FW["drawing"]["radius_min"]
RADIUS_SPAN = _FW["drawing"]["radius_span"]
CREDIT_SPLIT = _FW["credit"]["split"]
RANK_SINGLETON_TYPE = _FW["ranking"]["rank_singleton_type"]
RANK_ZERO_CREDIT = _FW["ranking"]["rank_zero_credit"]
