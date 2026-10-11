#!/usr/bin/env python3
"""Who wrote a letter, to whom, and about whom — as vault refs (v412).

A family-letters archive keeps its cast in ``letters/people.yaml``: one entry
per person, each with case-insensitive regex ``aliases`` (a dict alias
``{p: <regex>, in: [<collection>, …]}`` applies only inside those
collections, so "Dad" is one man in the mission letters and another in the
old box). The letters site resolves a transcript's ``from``/``to`` through
it; :class:`People` is a port of that resolver (``pipeline/build_site.py``
``People``), not an import.

Which people.yaml id is which VAULT person is vault data, not archive data:
``documents file --map ID=REF`` (``self`` for the owner, ``person/<slug>``),
remembered in ``state/documents/letters.json`` together with the scan URL
template and the archive's repo name. An id with no mapping is filed as
``person/<id>``; ``unknown`` and the site's automatic ``other-*`` ids name
nobody and become no ref.

`family_letters.render_source` is the one writer; this module only answers
"who" for it: :func:`refs_for` turns a transcript header into
``author_refs`` / ``recipient_refs`` / ``subject_refs``.
"""

from __future__ import annotations

import re
from pathlib import Path

from lifehug_core import STATE_DIR, read_json, write_json

#: The owner's ref. `temporal_work_items` owns the string; every claim the
#: fold reads names the owner this way.
OWNER_REF = "self"

CONFIG_FILE = STATE_DIR / "documents" / "letters.json"
PEOPLE_FILE = "letters/people.yaml"

#: people.yaml ids that name nobody: never a ref.
UNRESOLVED_PEOPLE_IDS = frozenset({"unknown"})

REF_RE = re.compile(r"^(self|(person|place|period|object|theme|project)/[a-z0-9][a-z0-9-]*)$")


class PeopleError(ValueError):
    """people.yaml or a --map value that must not be used."""


class People:
    """Port of the letters site's ``People``.

    ``resolve`` returns the people.yaml ids named in a from/to string, primary
    first: the earliest match wins (then the longest), and other parties count
    only when they are named outside parentheses and quotes. A string no alias
    matches resolves to an automatic ``other-<name>`` id, exactly as the site
    does; such ids name nobody in people.yaml and never become refs.
    """

    def __init__(self, cfg: dict | None):
        people = cfg.get("people") if isinstance(cfg, dict) else None
        if cfg is not None and not isinstance(people, list):
            raise PeopleError("people.yaml has no people list")
        self.by_id: dict[str, dict] = {}
        self.rules: list[tuple[re.Pattern, set[str] | None, str]] = []
        for person in people or []:
            if not isinstance(person, dict) or not isinstance(person.get("id"), str):
                raise PeopleError("people.yaml entry without an id")
            self.by_id[person["id"]] = person
            for alias in person.get("aliases") or []:
                if isinstance(alias, dict):
                    pattern, colls = str(alias.get("p") or ""), set(alias.get("in") or [])
                else:
                    pattern, colls = str(alias), None
                try:
                    self.rules.append((re.compile(pattern, re.I), colls, person["id"]))
                except re.error as exc:
                    raise PeopleError(f"people.yaml alias {pattern!r}: {exc}") from exc

    @classmethod
    def from_text(cls, text: str | None) -> "People":
        """From people.yaml's text; ``None`` (no people.yaml) is an empty cast."""
        if text is None:
            return cls(None)
        import mini_yaml  # noqa: PLC0415

        try:
            return cls(mini_yaml.loads(text))
        except mini_yaml.YamlSubsetError as exc:
            raise PeopleError(f"people.yaml unreadable: {exc}") from exc

    @classmethod
    def from_archive(cls, root: Path) -> "People":
        """The cast in an archive's working tree (``intake letter``'s door)."""
        path = Path(root) / PEOPLE_FILE
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            text = None
        return cls.from_text(text)

    @staticmethod
    def other(raw: str) -> str:
        name = re.split(r"\s*[(;,—]|\s+-\s+", raw.strip())[0].strip(" '\"") or raw.strip()
        name = name[:48]
        return "other-" + re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")

    def resolve(self, raw: object, coll: str) -> list[str]:
        s = str(raw or "unknown")
        hits = []
        for rx, colls, pid in self.rules:
            if colls and coll not in colls:
                continue
            match = rx.search(s)
            if match:
                hits.append((match.start(), -len(match.group(0)), pid))
        if not hits:
            return [self.other(s)]
        hits.sort()
        primary = hits[0][2]
        outside = re.sub(r"\([^)]*\)|\"[^\"]*\"|'[^']*'", " ", s)
        ids = [primary]
        for _, _, pid in hits:
            if pid not in ids and any(
                rx.search(outside)
                for rx, colls, p in self.rules
                if p == pid and (not colls or coll in colls)
            ):
                ids.append(pid)
        return ids

    def resolve_mention(self, raw: object, coll: str) -> str | None:
        """The one person a ``people:`` list item names, or None.

        Not part of the letters site, which resolves only from/to. A people
        list item is prose ("Ashley (baby; Dave's cousin)", "Your mom
        (unnamed)"), and an alias written for a from/to field over-matches
        it, so this is deliberately conservative: an alias must match a WHOLE
        name — the item's leading name, else one ;/,-separated name inside
        its parentheses — or the item names nobody."""
        text = str(raw or "").strip()
        lead = re.split(r"\s*[(;,—]|\s+-\s+", text)[0].strip(" '\"")
        names = [lead]
        for inner in re.findall(r"\(([^)]*)\)", text):
            names += [piece.strip(" '\"") for piece in re.split(r"[;,]", inner)]
        for name in names:
            if not name:
                continue
            best: tuple[int, str] | None = None
            for rx, colls, pid in self.rules:
                if colls and coll not in colls:
                    continue
                match = rx.search(name)
                if match and match.start() == 0 and match.end() == len(name):
                    if best is None or len(match.group(0)) > best[0]:
                        best = (len(match.group(0)), pid)
            if best is not None:
                return best[1]
        return None


# --------------------------------------------------------------------------
# The vault's map from people.yaml ids to refs (state/documents/letters.json)
# --------------------------------------------------------------------------

def validate_ref(ref: str) -> str:
    if not REF_RE.match(ref):
        raise PeopleError(f"not a ref: {ref!r} (want self or <type>/<slug>)")
    return ref


def parse_map_args(values: list[str] | None) -> dict[str, str]:
    out: dict[str, str] = {}
    for value in values or []:
        pid, sep, ref = value.partition("=")
        pid, ref = pid.strip(), ref.strip()
        if not sep or not pid or not ref:
            raise PeopleError(f"--map wants ID=REF, got {value!r}")
        out[pid] = validate_ref(ref)
    return out


def load_config() -> dict:
    """``{"people_map": {…}, "scan_url_template"?, "repo"?}``; empty when unset."""
    data = read_json(CONFIG_FILE, default=None)
    if not isinstance(data, dict):
        data = {}
    people_map = data.get("people_map")
    data["people_map"] = dict(people_map) if isinstance(people_map, dict) else {}
    return data


def save_config(*, people_map: dict[str, str], scan_url_template: str | None,
                repo: str | None) -> None:
    config = load_config()
    config["version"] = 1
    config["people_map"] = dict(sorted({**config["people_map"], **people_map}.items()))
    if scan_url_template:
        config["scan_url_template"] = scan_url_template
    if repo:
        config["repo"] = repo
    write_json(CONFIG_FILE, config)


def ref_for(pid: str, people_map: dict[str, str]) -> str | None:
    """The vault ref a people.yaml id stands for, or None for nobody."""
    if pid in people_map:
        return people_map[pid]
    if pid.startswith("other-") or pid in UNRESOLVED_PEOPLE_IDS:
        return None
    slug = re.sub(r"[^a-z0-9-]+", "-", pid.lower()).strip("-")
    return f"person/{slug}" if slug else None


def _refs(ids: list[str], people_map: dict[str, str]) -> list[str]:
    out: list[str] = []
    for pid in ids:
        ref = ref_for(pid, people_map)
        if ref and ref not in out:
            out.append(ref)
    return out


def refs_for(header: dict, collection: str, people: People,
             people_map: dict[str, str]) -> dict[str, list[str]]:
    """``author_refs`` / ``recipient_refs`` / ``subject_refs`` for one header.

    ``subject_refs`` is who the letter is ABOUT, from the header's ``people``
    list, without its writers and recipients (the design's example)."""
    author = _refs(people.resolve(header.get("from"), collection), people_map)
    recipient = _refs(people.resolve(header.get("to"), collection), people_map)
    named = [pid for pid in (people.resolve_mention(item, collection)
                             for item in (header.get("people") or []))
             if pid]
    subject = [ref for ref in _refs(named, people_map)
               if ref not in author and ref not in recipient]
    return {"author_refs": author, "recipient_refs": recipient, "subject_refs": subject}


def unmapped_ids(header: dict, collection: str, people: People,
                 people_map: dict[str, str]) -> list[str]:
    """Writer/recipient people.yaml ids filed as ``person/<id>`` for want of a map."""
    ids = people.resolve(header.get("from"), collection) + people.resolve(header.get("to"), collection)
    return [pid for pid in ids
            if pid not in people_map and not pid.startswith("other-")
            and pid not in UNRESOLVED_PEOPLE_IDS]


__all__ = [
    "CONFIG_FILE", "OWNER_REF", "PEOPLE_FILE", "People", "PeopleError", "REF_RE",
    "load_config", "parse_map_args", "ref_for", "refs_for", "save_config",
    "unmapped_ids", "validate_ref",
]
