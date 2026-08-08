#!/usr/bin/env python3
"""Lifehug — format framework registry (v125).

Single authoritative source for artifact format specs (letter, tweet,
instagram, chapter, post, essay, unsent_letter, legacy_letter, book, ...).
Each format is a JSON file under ``templates/<id>.json`` describing its
label, prompt template, subject shape, composability, target length, guided
slots, readiness thresholds, research basis, and AI-context notes.

Recurring-defect doctrine (issue #202 exemplar): compose.py and jobs.py both
previously hardcoded the list of valid formats. This module is now the only
place that list is derived from; both call sites import it.

Graceful degradation: if templates/*.json specs are missing entirely (e.g.
an old vault mid-update, before the v125 spec files have landed), the
composable-format list falls back to the pre-v125 hardcoded order so compose
and jobs keep working without a hard failure.

Import note: ``lifehug_core`` binds the whole process to one vault as a
side effect of merely being imported (see its module-level
``resolve_vault_root(bind_process=True)``). jobs.py is deliberately
importable and configurable (``jobs.configure(vault_root)``) before any
vault is chosen, so this module defers importing ``lifehug_core`` until a
registry function is actually called, instead of at module import time.
That keeps ``import format_frameworks`` (and therefore jobs.py's own
module-level ``import format_frameworks``) free of side effects.
"""

from __future__ import annotations

import json
from pathlib import Path

# Populated lazily by ``_lifehug_core()`` — see the import note above. Tests
# may also set these directly (bypassing lifehug_core entirely) before
# calling into the registry.
TEMPLATES_DIR: Path | None = None
FRAMEWORK_ROOT: Path | None = None

_lifehug_core_module = None


def _lifehug_core():
    """Import lifehug_core lazily and backfill TEMPLATES_DIR/FRAMEWORK_ROOT."""
    global _lifehug_core_module, TEMPLATES_DIR, FRAMEWORK_ROOT
    if _lifehug_core_module is None:
        import lifehug_core as _lc

        _lifehug_core_module = _lc
        if TEMPLATES_DIR is None:
            TEMPLATES_DIR = _lc.TEMPLATES_DIR
        if FRAMEWORK_ROOT is None:
            FRAMEWORK_ROOT = TEMPLATES_DIR.parent
    return _lifehug_core_module


# Pre-v125 hardcoded VALID_FORMATS order (compose.py:55). New composable
# format ids that aren't in this tuple are appended alphabetically after it;
# ids present here keep their historical position so compose.VALID_FORMATS
# stays byte-identical for existing formats.
CANONICAL_ORDER = (
    "letter",
    "tweet",
    "instagram",
    "chapter",
    "post",
    "essay",
    "unsent_letter",
    "legacy_letter",
)

_REQUIRED_STR_KEYS = ("id", "label", "kind", "summary", "template", "subject_kind")
_VALID_KINDS = {"single", "composite"}
_VALID_SUBJECT_KINDS = {"person", "self", "categories", "any"}

_CACHE: dict[str, dict] | None = None


def _fail(path: Path, problem: str) -> ValueError:
    return ValueError(f"{path}: {problem}")


def _validate_length(path: Path, length: object) -> None:
    if not isinstance(length, dict):
        raise _fail(path, "'length' must be an object")
    for key in ("min_words", "max_words"):
        if key not in length:
            raise _fail(path, f"'length' missing '{key}'")
        if not isinstance(length[key], int) or isinstance(length[key], bool):
            raise _fail(path, f"'length.{key}' must be an int")
    if length["min_words"] > length["max_words"]:
        raise _fail(path, "'length.min_words' must be <= 'length.max_words'")


def _validate_slots(path: Path, slots: object, story_functions: object) -> None:
    if not isinstance(slots, list):
        raise _fail(path, "'slots' must be a list")
    for i, slot in enumerate(slots):
        if not isinstance(slot, dict):
            raise _fail(path, f"slots[{i}] must be an object")
        for key in ("id", "label", "description", "story_functions", "min_answers"):
            if key not in slot:
                raise _fail(path, f"slots[{i}] missing '{key}'")
        for key in ("id", "label", "description"):
            if not isinstance(slot[key], str) or not slot[key]:
                raise _fail(path, f"slots[{i}].{key} must be a non-empty string")
        functions = slot["story_functions"]
        if not isinstance(functions, list) or not functions:
            raise _fail(path, f"slots[{i}].story_functions must be a non-empty list")
        unknown = [f for f in functions if f not in story_functions]
        if unknown:
            raise _fail(
                path,
                f"slots[{i}].story_functions has unknown story function(s): {unknown}",
            )
        min_answers = slot["min_answers"]
        if not isinstance(min_answers, int) or isinstance(min_answers, bool) or min_answers < 1:
            raise _fail(path, f"slots[{i}].min_answers must be an int >= 1")


def _validate_thresholds(path: Path, thresholds: object) -> None:
    if not isinstance(thresholds, dict):
        raise _fail(path, "'thresholds' must be an object")
    for key in ("ready", "developing"):
        if key not in thresholds:
            raise _fail(path, f"'thresholds' missing '{key}'")
        value = thresholds[key]
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            raise _fail(path, f"'thresholds.{key}' must be a number")
    ready = thresholds["ready"]
    developing = thresholds["developing"]
    if not (0 < developing < ready <= 1):
        raise _fail(
            path,
            f"'thresholds' must satisfy 0 < developing < ready <= 1 "
            f"(got developing={developing!r}, ready={ready!r})",
        )


def _validate_research(path: Path, research: object) -> None:
    if not isinstance(research, dict):
        raise _fail(path, "'research' must be an object")
    if "basis" not in research or not isinstance(research["basis"], str) or not research["basis"]:
        raise _fail(path, "'research.basis' must be a non-empty string")
    if "citations" not in research or not isinstance(research["citations"], list):
        raise _fail(path, "'research.citations' must be a list")


def _validate_framework(path: Path, data: dict, story_functions: object) -> dict:
    if not isinstance(data, dict):
        raise _fail(path, "top-level JSON must be an object")

    stem = path.stem
    for key in _REQUIRED_STR_KEYS:
        if key not in data:
            raise _fail(path, f"missing required key '{key}'")

    if not isinstance(data["id"], str) or not data["id"]:
        raise _fail(path, "'id' must be a non-empty string")
    if data["id"] != stem:
        raise _fail(path, f"'id' ({data['id']!r}) must equal the filename stem ({stem!r})")

    for key in ("label", "summary"):
        if not isinstance(data[key], str) or not data[key]:
            raise _fail(path, f"'{key}' must be a non-empty string")

    if data["kind"] not in _VALID_KINDS:
        raise _fail(path, f"'kind' must be one of {sorted(_VALID_KINDS)}")

    if not isinstance(data["template"], str) or not data["template"]:
        raise _fail(path, "'template' must be a non-empty string")
    template_path = FRAMEWORK_ROOT / data["template"]
    if not template_path.exists():
        raise _fail(path, f"'template' path does not exist: {data['template']}")

    if data["subject_kind"] not in _VALID_SUBJECT_KINDS:
        raise _fail(path, f"'subject_kind' must be one of {sorted(_VALID_SUBJECT_KINDS)}")

    if "composable" not in data or not isinstance(data["composable"], bool):
        raise _fail(path, "'composable' must be a bool")

    if "length" not in data:
        raise _fail(path, "missing required key 'length'")
    _validate_length(path, data["length"])

    if "slots" not in data:
        raise _fail(path, "missing required key 'slots'")
    _validate_slots(path, data["slots"], story_functions)

    if "thresholds" not in data:
        raise _fail(path, "missing required key 'thresholds'")
    _validate_thresholds(path, data["thresholds"])

    if "research" not in data:
        raise _fail(path, "missing required key 'research'")
    _validate_research(path, data["research"])

    if "ai_context" not in data or not isinstance(data["ai_context"], list):
        raise _fail(path, "'ai_context' must be a list")

    if "deliverables" in data:
        if not isinstance(data["deliverables"], list):
            raise _fail(path, "'deliverables' must be a list")
        if data["kind"] != "composite":
            raise _fail(path, "'deliverables' is only valid for kind == 'composite'")

    return data


def load_frameworks(refresh: bool = False) -> dict[str, dict]:
    """Load, validate, and cache every templates/*.json format framework.

    Keyed by ``id``. Raises ``ValueError`` naming the offending file and the
    schema violation on any invalid spec.
    """
    global _CACHE
    if _CACHE is not None and not refresh:
        return _CACHE

    story_functions = _lifehug_core().STORY_FUNCTIONS

    frameworks: dict[str, dict] = {}
    if TEMPLATES_DIR is not None and TEMPLATES_DIR.exists():
        for path in sorted(TEMPLATES_DIR.glob("*.json")):
            try:
                data = json.loads(path.read_text())
            except json.JSONDecodeError as exc:
                raise _fail(path, f"invalid JSON: {exc}") from exc
            frameworks[path.stem] = _validate_framework(path, data, story_functions)

    _CACHE = frameworks
    return frameworks


def valid_formats() -> tuple[str, ...]:
    """Composable format ids, in canonical (then alphabetical) order.

    Falls back to :data:`CANONICAL_ORDER` when no spec files are present at
    all (e.g. an old vault mid-update), so compose keeps working.
    """
    frameworks = load_frameworks()
    if not frameworks:
        return CANONICAL_ORDER

    composable_ids = [fid for fid, spec in frameworks.items() if spec.get("composable")]

    def sort_key(fid: str) -> tuple[int, str]:
        try:
            return (CANONICAL_ORDER.index(fid), "")
        except ValueError:
            return (len(CANONICAL_ORDER), fid)

    return tuple(sorted(composable_ids, key=sort_key))


def get(format_id: str) -> dict:
    """Return the validated framework spec for ``format_id``."""
    frameworks = load_frameworks()
    try:
        return frameworks[format_id]
    except KeyError:
        known = ", ".join(sorted(frameworks)) or "(none loaded)"
        raise KeyError(
            f"unknown format {format_id!r}; known formats: {known}"
        ) from None
