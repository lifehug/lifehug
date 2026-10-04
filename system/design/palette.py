"""The design palette: one definition of every colour a data view uses.

``system/design/palette.yaml`` mirrors lifehug-platform's
``architecture/design/palette.yaml`` BYTE FOR BYTE (the sha256 is pinned in
``tests/test_v393_design_palette.py`` and ``docs/design/palette.md``, and the
same digest is recorded on the platform side, so drift in either repo fails
loudly). This module loads it with the standard library only (a vault need not
have PyYAML) and emits:

* ``css()``        the CSS custom properties, light under ``:root`` and dark
                   under ``prefers-color-scheme: dark``;
* ``type_color()`` an entity type -> the NAME of its token (never a hex);
* ``legend()``     the fixed categorical order, for a legend.

Nothing is computed at run time: every value is read from the yaml. An unknown
type draws the neutral fallback and logs a warning; it never gets a colour.
"""

from __future__ import annotations

import hashlib
import logging
import re
from functools import lru_cache
from pathlib import Path

log = logging.getLogger(__name__)

PALETTE_PATH = Path(__file__).with_name("palette.yaml")

# The viewer's wiki directories are plural; the palette's types are singular.
# `life` (the hub page) shares `self`; a relationship wears the edge token.
VIEWER_TYPE_ALIASES = {
    "people": "person", "places": "place", "periods": "period",
    "projects": "project", "themes": "theme", "objects": "object",
    "events": "event", "life": "self",
}
RELATIONSHIP_TOKEN = "--graph-relationship"


def content_digest(path: Path = PALETTE_PATH) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


# --- a stdlib reader for exactly the YAML subset palette.yaml uses ----------
# Block mappings, block lists, flow mappings/lists, quoted and bare scalars,
# full-line comments. tests/test_v393_design_palette.py checks it against
# PyYAML wherever PyYAML is installed.

_KEY = re.compile(r"^([A-Za-z0-9_.\-]+):(?:\s+(.*))?$")


def _scalar(text: str):
    text = text.strip()
    if text[:1] in "{[":
        value, _ = _flow(text, 0)
        return value
    if len(text) >= 2 and text[0] == text[-1] and text[0] in "\"'":
        return text[1:-1]
    if text in ("true", "false"):
        return text == "true"
    if text in ("null", "~", ""):
        return None
    for cast in (int, float):
        try:
            return cast(text)
        except ValueError:
            pass
    return text


def _flow(s: str, i: int):
    while s[i] == " ":
        i += 1
    if s[i] == "{":
        out: dict = {}
        i += 1
        while True:
            while s[i] in " ,":
                i += 1
            if s[i] == "}":
                return out, i + 1
            j = s.index(":", i)
            key = s[i:j].strip()
            out[key], i = _flow_value(s, j + 1)
    if s[i] == "[":
        items: list = []
        i += 1
        while True:
            while s[i] in " ,":
                i += 1
            if s[i] == "]":
                return items, i + 1
            value, i = _flow_value(s, i)
            items.append(value)
    raise ValueError(f"not a flow collection: {s!r}")


def _flow_value(s: str, i: int):
    while s[i] == " ":
        i += 1
    if s[i] in "{[":
        return _flow(s, i)
    if s[i] in "\"'":
        q = s[i]
        j = s.index(q, i + 1)
        return s[i + 1:j], j + 1
    j = i
    while s[j] not in ",}]":
        j += 1
    return _scalar(s[i:j]), j


def parse(text: str):
    lines = []
    for raw in text.splitlines():
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        lines.append((len(raw) - len(raw.lstrip()), raw.strip()))
    value, _ = _block(lines, 0, lines[0][0])
    return value


def _block(lines, i, indent):
    if lines[i][1].startswith("- "):
        out: list = []
        while i < len(lines) and lines[i][0] == indent and lines[i][1].startswith("- "):
            rest = lines[i][1][2:].strip()
            if rest[:1] not in "{[" and _KEY.match(rest):
                lines[i] = (indent + 2, rest)
                item, i = _block(lines, i, indent + 2)
            else:
                item, i = _scalar(rest), i + 1
            out.append(item)
        return out, i
    out_d: dict = {}
    while i < len(lines) and lines[i][0] == indent:
        m = _KEY.match(lines[i][1])
        if not m:
            raise ValueError(f"cannot read palette line: {lines[i][1]!r}")
        key, rest = m.group(1), m.group(2)
        i += 1
        if rest is None:
            if i < len(lines) and lines[i][0] > indent:
                out_d[key], i = _block(lines, i, lines[i][0])
            else:
                out_d[key] = None
        else:
            out_d[key] = _scalar(rest)
    return out_d, i


@lru_cache(maxsize=1)
def load() -> dict:
    return parse(PALETTE_PATH.read_text(encoding="utf-8"))


def _tokened() -> list[dict]:
    """Every entry that carries a token, in file order."""
    data = load()
    rows: list[dict] = []
    for section in ("surfaces", "text", "status"):
        rows.extend(data.get(section) or [])
    cat = data["categorical"]
    rows.extend(cat["entries"])
    rows.append(cat["fallback"])
    rows.extend(data.get("edges") or [])
    return rows


def css() -> str:
    """The custom properties: light under :root, dark under the media query."""
    rows = _tokened()
    light = "".join(f"{r['token']}:{r['light']};" for r in rows)
    dark = "".join(f"{r['token']}:{r['dark']};" for r in rows)
    return (
        f"/* generated from system/design/palette.yaml (sha256 {content_digest()[:12]}) */\n"
        f":root{{{light}}}\n"
        f"@media (prefers-color-scheme: dark){{:root{{{dark}}}}}"
    )


def order() -> list[str]:
    return list(load()["categorical"]["order"])


def fallback_token() -> str:
    return load()["categorical"]["fallback"]["token"]


def type_color(entity_type: str) -> str:
    """The token NAME (``--graph-person``) for an entity type; fallback if unknown."""
    cat = load()["categorical"]
    key = (entity_type or "").strip()
    if key in ("relationship", "relationships"):
        return RELATIONSHIP_TOKEN
    key = VIEWER_TYPE_ALIASES.get(key, key)
    for entry in cat["entries"]:
        if entry["name"] == key:
            return entry["token"]
    log.warning("design palette: unknown entity type %r; drawing the neutral fallback", entity_type)
    return cat["fallback"]["token"]


def legend(types) -> list[dict]:
    """One row per present type, in the palette's FIXED order (never by count)."""
    present: dict[str, str] = {}
    for t in types:
        token = type_color(t)
        present.setdefault(token, t)
    by_token = {e["token"]: e["name"] for e in load()["categorical"]["entries"]}
    rows = []
    for entry in load()["categorical"]["entries"]:
        if entry["token"] in present:
            rows.append({"type": entry["name"], "token": entry["token"]})
    for token, t in present.items():
        if token not in by_token:
            rows.append({"type": t, "token": token})
    return rows
