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
import re
from dataclasses import dataclass, field
from pathlib import Path

FRAMEWORK_FILE = Path(__file__).resolve().parent / "portrait_targets.json"
OVERRIDE_NAME = "portrait_targets.json"
FRAMEWORK_ORIGIN = "framework system/portrait_targets.json"
OVERRIDE_ORIGIN = "vault state/portrait_targets.json"

#: Closed vocabularies for string knobs (dotted key → allowed values).
ENUMS: dict[str, tuple[str, ...]] = {
    "credit.split": ("equal", "whole"),
    "credit.answer_rule": ("listed", "tagged"),
    "credit.classified_rule": ("tagged", "none"),
}

#: Tables a vault may extend with NEW rows (a new kind, a new type): any
#: dotted key under these prefixes may be added if its value is a number >= 0.
OPEN_PREFIXES: tuple[str, ...] = ("targets.",)

#: String knobs that must compile as a regular expression.
REGEX_KEYS: tuple[str, ...] = ("kinds.age_frame_pattern",)


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
    for key, value in _flatten(override).items():
        if key == "schema_version":
            if value != framework.get("schema_version"):
                errors.append(f"schema_version {value!r} != framework {framework.get('schema_version')!r}")
            continue
        if key not in flat_fw:
            if any(key.startswith(p) for p in OPEN_PREFIXES) and key.count(".") == 2:
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
        if key in REGEX_KEYS:
            try:
                re.compile(str(value))
            except re.error as exc:
                errors.append(f"{key}: not a regular expression ({exc})")
        if key == "calibration.quantile" and not 0 < float(value) <= 1:
            errors.append(f"{key}: must be in (0, 1]")
    return errors


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
    errors = validate_override(framework, override)
    if errors:
        cfg.errors.extend(f"{OVERRIDE_ORIGIN}: {e}" for e in errors)
        return cfg
    override.pop("schema_version", None)
    cfg.values = _merge(framework, override)
    for key in _flatten(override):
        cfg.origin[key] = OVERRIDE_ORIGIN
    return cfg


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
CALIBRATION_QUANTILE = _FW["calibration"]["quantile"]
CALIBRATION_MIN_PEERS = _FW["calibration"]["min_peers"]
TIER_NONE = _FW["tiers"]["none"]
TIER_BASIC = _FW["tiers"]["basic"]
TIER_STANDARD = _FW["tiers"]["standard"]
TIER_EXTREME = _FW["tiers"]["extreme"]
WEIGHT_PARENT = _FW["targets"]["person"]["parent"]
WEIGHT_SIBLING = _FW["targets"]["person"]["sibling"]
WEIGHT_GRANDPARENT = _FW["targets"]["person"]["grandparent"]
WEIGHT_FRIEND = _FW["targets"]["person"]["friend"]
WEIGHT_RESIDENCE = _FW["targets"]["place"]["residence"]
WEIGHT_WORKPLACE = _FW["targets"]["place"]["workplace"]


# --- The target model (v378: the ring is a target) -------------------------
#
# Every entity gets a target (graph-vis D4: an owner table, not learned from
# citations; the table and its rationale: system/research/life-portrait-
# targets.md). told = credit. target = table weight x tier multiplier x the
# type's calibration scale, on the same scale as credit. gap = max(0, 1 -
# told/target). Peers compare only within a type (D5); nothing sums across
# types (D7).

#: The credit relevance gate (owner ruling 2026-09-29; research note §6): a
#: non-answer source tells only the entities its current classification tags.
A_SOURCE_TELLS_ONLY_ITS_SUBJECTS = "A_SOURCE_TELLS_ONLY_ITS_SUBJECTS"

#: wiki subdirectory -> entity type (the targets table's first key).
DIR_TYPES = {
    "people": "person", "places": "place", "periods": "period",
    "projects": "project", "themes": "theme", "objects": "object",
    "self": "self", "lifes_work": "lifes_work", "life": "life",
    "relationships": "relationship",
}


def table_weight(cfg: PortraitConfig, etype: str, kind: str) -> float:
    """The owner table's weight for (type, kind); unknown kinds fall back."""
    table = cfg.values.get("targets", {}).get(etype, {})
    if kind in table:
        return float(table[kind])
    if len(table) == 1:
        return float(next(iter(table.values())))
    for fallback in ("other", "unknown"):
        if fallback in table:
            return float(table[fallback])
    return 1.0


def tier_multiplier(cfg: PortraitConfig, tier: str | None) -> float:
    tiers = cfg.values.get("tiers", {})
    return float(tiers.get(tier or "none", tiers.get("none", 1.0)))


def _quantile(values: list[float], q: float) -> float:
    ordered = sorted(values)
    idx = max(0, min(len(ordered) - 1, int(-(-q * len(ordered) // 1)) - 1))
    return ordered[idx]


def calibrate(rows: list[dict], cfg: PortraitConfig) -> dict[str, dict]:
    """Per-type scale putting ``base`` (weight x tier) on the credit scale.

    ``rows``: ``{"type", "kind", "credit", "base"}``. The scale of a type is the
    ``calibration.quantile`` of credit/base over its credited, non-excluded
    members — at 1.0 the best-told member sits exactly on its target. A type
    with fewer than ``min_peers`` credited members borrows the median scale
    of the types that have enough (1.0 if none do). Returns
    ``{type: {"scale": float, "source": "own"|"borrowed"}}``.
    """
    q = float(cfg.get("calibration.quantile"))
    min_peers = int(cfg.get("calibration.min_peers"))
    exclude = set(cfg.get("calibration.exclude_kinds"))
    ratios: dict[str, list[float]] = {}
    types = set()
    for row in rows:
        types.add(row["type"])
        if row["credit"] > 0 and row["base"] > 0 and row["kind"] not in exclude:
            ratios.setdefault(row["type"], []).append(row["credit"] / row["base"])
    own = {t: _quantile(v, q) for t, v in ratios.items() if len(v) >= min_peers}
    borrowed = sorted(own.values())
    fallback = borrowed[len(borrowed) // 2] if borrowed else 1.0
    out = {}
    for t in types:
        if t in own:
            out[t] = {"scale": own[t], "source": "own"}
        else:
            out[t] = {"scale": fallback, "source": "borrowed"}
    return out


def gap(told: float, target: float) -> float:
    """How much of the target is still untold, in [0, 1]."""
    if target <= 0:
        return 0.0
    return max(0.0, 1.0 - told / target)


def apply_targets(rows: list[dict], cfg: PortraitConfig) -> dict[str, dict]:
    """Fill ``target`` and ``gap`` on every row in place; return the calibration."""
    cal = calibrate(rows, cfg)
    for row in rows:
        row["target"] = row["base"] * cal[row["type"]]["scale"]
        row["gap"] = gap(row["credit"], row["target"])
    return cal


def split_share(n: int, cfg: PortraitConfig) -> float:
    """What one of ``n`` holders of a source earns (``credit.split``)."""
    if n <= 0:
        return 0.0
    return 1.0 / n if cfg.get("credit.split") == "equal" else 1.0


def tag_names(classification: dict, cfg: PortraitConfig) -> list[str]:
    """The subject names a classification tags, through the relevance gate.

    Only the fields in ``credit.tag_fields``; a person needs at least
    ``credit.min_person_mentions``. Names only — resolving them to pages is
    the caller's job, and a name that resolves to no page earns nothing.
    """
    fields = set(cfg.get("credit.tag_fields"))
    min_mentions = int(cfg.get("credit.min_person_mentions"))
    names: list[str] = []
    for field_name in ("people", "places", "themes", "time_periods", "projects"):
        if field_name not in fields:
            continue
        for item in classification.get(field_name) or []:
            if isinstance(item, str):
                name = item
            elif isinstance(item, dict):
                if field_name == "people":
                    try:
                        mentions = int(item.get("mention_count") or 1)
                    except (TypeError, ValueError):
                        mentions = 1
                    if mentions < min_mentions:
                        continue
                name = item.get("name") or item.get("era") or ""
            else:
                continue
            if str(name).strip():
                names.append(str(name).strip())
    return names


def name_variants(name: str) -> list[str]:
    """Exact spellings a tag may match: as written, without a trailing
    parenthetical, and its first comma segment ("Mesa, Arizona (Tippett
    house)" -> "Mesa, Arizona", "Mesa"). Never a substring search."""
    out = [name.strip()]
    bare = re.sub(r"\s*\(.*?\)\s*$", "", name).strip()
    if bare and bare not in out:
        out.append(bare)
    first = bare.split(",")[0].strip()
    if first and first not in out:
        out.append(first)
    return out
