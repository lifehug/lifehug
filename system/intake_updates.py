#!/usr/bin/env python3
"""Intake's `--from-updates DIR` mode — the family-letters update folder as
one intake per proposal file (lifehug#469, v399).

The answer pass in the family-letters archive writes one Markdown file per
proposed change to the vault (``~/Desktop/lifehug-updates/<name>.md``) plus
an ``index.md``. Each file is evidence about the vault, not the owner's own
words, so each one runs as

    intake start --record family-letters:<letter ids> --evidence document

with the WHOLE file as the source body — title, current and proposed value,
confidence, the reasoning and the verbatim quotes — filed as an immutable
``external_record`` source (``authority: third_party_record``, sensitivity
``family``). The vault copy is the durable one; the folder file becomes a
receipt: once its intake is done, it moves to ``DIR/applied/<name>.md`` with
the outcome (receipt id, filed source) appended. Nothing here reads a date:
dates are read by Add Landmark's reading like every other intake (R6), and
filed only through ``landmark-offer --apply`` after the owner's yes.

This module is the pure part: which files, what each one is, and the move.
It parses STRUCTURE only — an optional front-matter block (the contract the
family-letters answer pass will emit: ``kind``, ``letters``, ``question``),
backticked letter ids, and the update format's labelled ``**Proposed
value:**`` field — never the prose.

Kinds:

* ``flag`` — the file asks a question and proposes no change ("Proposed
  value: no change yet; flag …"). It writes NOTHING: no source, no reading,
  no move. The question is printed, every run, until the owner answers it
  some other way and removes the file.
* ``record`` — filed as a source; no landmark reading.
* ``landmark`` / ``auto`` — filed as a source and read for landmarks. A file
  whose reading asks nothing (no new, revised or conflicting unit) is
  *record-only* in the summary.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

UPDATE_KINDS = ("landmark", "record", "flag", "auto")
APPLIED_DIR_NAME = "applied"
INDEX_NAME = "index.md"
RECORD_REF_PREFIX = "family-letters:"
SOURCE_LABEL = "family-letters"
SENSITIVITY = "family"

#: A family-letters letter id as the answer pass quotes it: ``group/letter``
#: in backticks. A path with a file extension (``letters/people.md``,
#: ``state/landmarks.json``) is a document, not a letter, and is not cited
#: as one.
LETTER_ID_RE = re.compile(r"`([a-z0-9][a-z0-9._-]*/[a-z0-9][a-z0-9._-]*)`")
PROPOSED_FIELD_RE = re.compile(r"^\*\*Proposed value:\*\*\s*(.+)$", re.M | re.I)
NO_CHANGE_RE = re.compile(r"^no change\b", re.I)
TITLE_RE = re.compile(r"^#\s+(.+?)\s*$", re.M)
APPLIED_MARK = "<!-- lifehug intake applied -->"


def _front_matter(text: str) -> dict:
    """``key: value`` lines of a leading ``---`` block; nothing else."""
    if not text.startswith("---\n"):
        return {}
    end = text.find("\n---", 4)
    if end < 0:
        return {}
    out: dict = {}
    for line in text[4:end].splitlines():
        key, sep, value = line.partition(":")
        if sep and key.strip() and not key.startswith((" ", "\t", "#")):
            out[key.strip().lower()] = value.strip().strip('"').strip("'")
    return out


def _list(value: str) -> list[str]:
    raw = value.strip().strip("[]")
    return [part.strip().strip('"').strip("'") for part in raw.split(",") if part.strip()]


def letter_ids(text: str) -> list[str]:
    seen: list[str] = []
    for match in LETTER_ID_RE.finditer(text):
        token = match.group(1)
        if "." in token.rsplit("/", 1)[-1] or token in seen:
            continue
        seen.append(token)
    return seen


def parse_update(path: Path) -> dict:
    """What one update file is. Pure over the file's bytes."""
    from vault_paths import read_vault_text  # noqa: PLC0415

    path = Path(path)
    text = read_vault_text(path, vault_root=path.parent)
    front = _front_matter(text)
    title_match = TITLE_RE.search(text)
    title = front.get("title") or (title_match.group(1) if title_match else path.stem)
    letters = _list(front["letters"]) if front.get("letters") else letter_ids(text)
    proposed = PROPOSED_FIELD_RE.search(text)
    proposed_value = proposed.group(1).strip() if proposed else ""
    kind = (front.get("kind") or "").lower()
    if kind not in UPDATE_KINDS:
        kind = "flag" if NO_CHANGE_RE.match(proposed_value) else "auto"
    question = front.get("question") or (
        f"{title} — {proposed_value}" if kind == "flag" else "")
    return {
        "file": str(path),
        "name": path.name,
        "text": text,
        "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        "title": title,
        "kind": kind,
        "letters": letters,
        "record_ref": record_ref(letters, path.stem),
        "question": question,
    }


def record_ref(letters: list[str], stem: str) -> str:
    """``family-letters:<id>,<id>`` — or the file's own name when it cites
    no letter, so the record still says where it came from."""
    return RECORD_REF_PREFIX + (",".join(letters) if letters else f"update/{stem}")


def update_files(folder: Path) -> list[Path]:
    """The proposal files in ``folder``, in ``index.md`` order where the
    index names them, then by name. ``index.md`` and ``applied/`` are not
    proposals."""
    folder = Path(folder)
    if not folder.is_dir():
        raise FileNotFoundError(f"no such folder: {folder}")
    files = sorted(p for p in folder.glob("*.md")
                   if p.is_file() and not p.is_symlink() and p.name != INDEX_NAME)
    order: list[str] = []
    index = folder / INDEX_NAME
    if index.is_file():
        for match in re.finditer(r"([A-Za-z0-9._-]+\.md)", index.read_text(encoding="utf-8")):
            if match.group(1) not in order:
                order.append(match.group(1))
    rank = {name: i for i, name in enumerate(order)}
    return sorted(files, key=lambda p: (rank.get(p.name, len(rank)), p.name))


def applied_note(outcome: dict) -> str:
    lines = ["", "", APPLIED_MARK, f"Applied by lifehug intake {outcome.get('intake_id')}"
             f" on {outcome.get('at')}."]
    if outcome.get("source_path"):
        lines.append(f"- source: {outcome['source_path']}")
    if outcome.get("receipt_id"):
        lines.append(f"- receipt: {outcome['receipt_id']} "
                     f"(undo: python3 system/lifehug.py landmark-offer --retract {outcome['receipt_id']})")
    else:
        lines.append("- receipt: none (no landmark filed; the file is a source in the vault)")
    return "\n".join(lines) + "\n"


def move_applied(path: Path, outcome: dict) -> Path:
    """Move a done update file to ``applied/`` with its outcome appended.

    Written first, unlinked second, both through the no-follow I/O
    authority rooted at the update folder: a crash between leaves both
    copies, and the next run sees the applied one and only unlinks the
    original.
    """
    from vault_paths import (  # noqa: PLC0415
        atomic_write_vault_text, ensure_vault_directory, read_vault_text,
        unlink_vault_file)

    path = Path(path)
    folder = path.parent
    target = folder / APPLIED_DIR_NAME / path.name
    ensure_vault_directory(target.parent, vault_root=folder)
    text = read_vault_text(path, vault_root=folder)
    if target.exists():
        if APPLIED_MARK not in read_vault_text(target, vault_root=folder):
            raise FileExistsError(f"{target} exists and is not an applied receipt")
    else:
        atomic_write_vault_text(target, text.rstrip("\n") + applied_note(outcome),
                                vault_root=folder, mode=0o644)
    unlink_vault_file(path, vault_root=folder)
    return target


__all__ = [
    "APPLIED_DIR_NAME", "APPLIED_MARK", "RECORD_REF_PREFIX", "SENSITIVITY",
    "SOURCE_LABEL", "UPDATE_KINDS", "applied_note", "letter_ids", "move_applied",
    "parse_update", "record_ref", "update_files",
]
