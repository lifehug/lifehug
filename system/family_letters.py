#!/usr/bin/env python3
"""A cited family letter is filed as a letter (letters-in-the-vault D1, v404).

The family-letters archive (repo ``lifehug/letters``) holds one transcript per
letter at ``letters/<collection>/<letter>/transcript.md``: a YAML header
(``id``, ``date``, ``date_precision``, ``date_evidence``, ``from``,
``from_relationship``, ``to``, ``people``, ``places``, ``summary``,
``source_file`` …) and then the transcript body. Until v404 intake cited a
letter only as a string (``record_ref: family-letters:<id>``) on the update
memo it filed; the letter itself never reached the vault.

This module is the one place that turns a letter id into a vault source:

* :func:`letters_dir` — where the archive is: env
  ``LIFEHUG_FAMILY_LETTERS_DIR``, else config ``family_letters_dir``
  (``profile.yaml``/``config.yaml`` through ``load_config``), else
  ``~/Workspace/family-letters``.
* :func:`file_letter` — files ONE letter as an immutable source
  ``sources/letters/<collection>--<letter>.md``: ``type: letter`` (a sub-kind
  of ``external_record``: ``source_trust: external_record``, ``authority:
  third_party_record``), sensitivity ``family``, ``source_id
  letters:<collection>--<letter>`` (no ``/``: see :func:`source_id`), the
  header fields the vault can use in the
  frontmatter, and the transcript body VERBATIM. Manifest-registered through
  ``source_integrity`` like every source. Idempotent by id: a letter already
  filed is never rewritten (a record is immutable; a revised transcript is a
  later, superseding version — D1 — not an edit).
* :func:`stamp_cites` — adds ``cites: [<letter source id>, …]`` to the frontmatter
  of a record memo. Frontmatter only: the body, and so ``content_sha256``,
  is untouched.
* :func:`link_citing_memos` — every record memo whose ``record_ref`` names a
  letter gets that letter in its ``cites``. This is how a memo filed before
  v404 (or filed while the archive was not on this machine) is linked once
  the letter is filed.

A missing archive or a missing letter is never a crash: one honest line, and
the caller files whatever it was filing exactly as before.

CLI (``lifehug.py intake letter`` is the door; this is the worker)::

    python3 system/family_letters.py file <id|family-letters:<id>[,<id>]> … [--json]
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

from lifehug_core import REPO_DIR, SOURCES_DIR, load_config, now_utc, split_frontmatter, write_text

RECORD_REF_PREFIX = "family-letters:"
SOURCE_ID_PREFIX = "letters:"
LETTERS_SUBDIR = "letters"
SOURCE_TYPE = "letter"
SENSITIVITY = "family"
ORIGIN_REPO = "lifehug/letters"
ENV_DIR = "LIFEHUG_FAMILY_LETTERS_DIR"
CONFIG_KEY = "family_letters_dir"
DEFAULT_DIR = "~/Workspace/family-letters"

#: A letter id is ``<collection>/<letter>``; the same shape
#: `intake_updates.LETTER_ID_RE` reads out of backticks.
LETTER_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]*/[a-z0-9][a-z0-9._-]*$")

#: The transcript header fields the vault carries on the source, in order.
#: Everything else in the header (page order, per-page confidence, model,
#: pass) is the archive's own working state and stays there.
HEADER_FIELDS = (
    "date", "date_text", "date_precision", "date_evidence", "from",
    "from_relationship", "to", "people", "places", "topics", "summary",
    "document_type", "source_file", "confidence", "status",
)

#: Frontmatter key the archive's ``status`` lands under: the vault's own
#: ``status`` is the source contract's (``raw``).
TRANSCRIPT_STATUS_KEY = "transcript_status"
TRANSCRIPT_CONFIDENCE_KEY = "transcript_confidence"

CITES_KEY = "cites"


class LetterError(Exception):
    """A letter could not be read. ``code``: ``missing_dir``,
    ``missing_letter``, ``invalid_id`` or ``unreadable``."""

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(detail)
        self.code = code


# --------------------------------------------------------------------------
# Where the archive is, and which ids a reference names
# --------------------------------------------------------------------------

def letters_dir(*, env: dict | None = None, config: dict | None = None) -> Path:
    """The family-letters archive root. Env, then config, then the default."""
    env = os.environ if env is None else env
    value = str(env.get(ENV_DIR) or "").strip()
    if not value:
        if config is None:
            try:
                config = load_config()
            except Exception:  # noqa: BLE001 — a bad config never blocks filing
                config = {}
        value = str((config or {}).get(CONFIG_KEY) or "").strip()
    return Path(value or DEFAULT_DIR).expanduser()


def normalize_id(value: str) -> str:
    """A letter id from any of its spellings: ``<collection>/<letter>``,
    ``family-letters:<id>``, or the source id ``letters:<collection>--<letter>``."""
    text = str(value or "").strip()
    for prefix in (RECORD_REF_PREFIX, SOURCE_ID_PREFIX):
        if text.startswith(prefix):
            text = text[len(prefix):]
    text = text.strip().strip("`").strip()
    if "/" not in text and "--" in text:
        text = text.replace("--", "/", 1)
    return text


def ids_from_ref(ref: str | None) -> list[str]:
    """The letter ids a ``family-letters:<id>[,<id>]`` reference names.

    A reference with another prefix names no letter; ``update/<stem>`` is the
    name `intake_updates.record_ref` gives a memo that cites none."""
    text = str(ref or "").strip()
    if not text.startswith(RECORD_REF_PREFIX):
        return []
    seen: list[str] = []
    for part in text[len(RECORD_REF_PREFIX):].split(","):
        letter = normalize_id(part)
        if not LETTER_ID_RE.match(letter) or letter.startswith("update/"):
            continue
        if letter not in seen:
            seen.append(letter)
    return seen


def source_stem(letter_id: str) -> str:
    """``<collection>--<letter>``: the file stem, and the id's vault spelling."""
    collection, letter = letter_id.split("/", 1)
    return f"{collection}--{letter}"


def source_id(letter_id: str) -> str:
    """``letters:<collection>--<letter>``.

    NOT ``letters:<collection>/<letter>``: Lifehug Cloud's vault validator
    hard-rejects a ``source_id`` outside ``^[A-Za-z0-9][A-Za-z0-9:._-]{0,127}$``
    (`INVALID_ID`, lifehug-platform `app/vault_safety/validator.py`), and a
    rejected vault is not served at all. The archive's own id (with its ``/``)
    is kept as ``letter_id`` and ``origin.id``."""
    return f"{SOURCE_ID_PREFIX}{source_stem(letter_id)}"


def source_relpath(letter_id: str) -> str:
    return f"sources/{LETTERS_SUBDIR}/{source_stem(letter_id)}.md"


def transcript_path(root: Path, letter_id: str) -> Path:
    return Path(root) / "letters" / letter_id / "transcript.md"


# --------------------------------------------------------------------------
# Reading a transcript header (the subset the archive writes; stdlib only)
# --------------------------------------------------------------------------

def _fold(lines: list[str]) -> str:
    """YAML flow folding for a multi-line quoted scalar: a line break is a
    space, an empty line is a newline."""
    out = ""
    pending_space = False
    for index, raw in enumerate(lines):
        line = raw.strip() if index else raw.rstrip()
        if index and not line:
            out += "\n"
            pending_space = False
            continue
        if pending_space:
            out += " "
        out += line
        pending_space = True
    return out


def _closes(text: str, quote: str) -> int:
    """Index of the closing quote in ``text`` (which starts after the opening
    quote), or -1."""
    i = 0
    while i < len(text):
        ch = text[i]
        if quote == "'" and ch == "'":
            if i + 1 < len(text) and text[i + 1] == "'":
                i += 2
                continue
            return i
        if quote == '"':
            if ch == "\\":
                i += 2
                continue
            if ch == '"':
                return i
        i += 1
    return -1


def _scalar(first: str, rest: list[str]) -> tuple[object, int]:
    """One scalar starting at ``first`` (text after ``key:`` or ``- ``),
    continuing into ``rest`` when it is a multi-line quoted string.
    Returns (value, continuation lines consumed)."""
    value = first.strip()
    if value[:1] in ("'", '"'):
        quote = value[0]
        lines = [value[1:]]
        used = 0
        while _closes("\n".join(lines), quote) < 0 and used < len(rest):
            lines.append(rest[used])
            used += 1
        text = _fold(lines)
        end = _closes(text, quote)
        inner = text[:end] if end >= 0 else text
        if quote == "'":
            return inner.replace("''", "'"), used
        try:
            return json.loads(f'"{inner}"'), used
        except ValueError:
            return inner, used
    used = 0
    while (used < len(rest) and rest[used].startswith((" ", "\t")) and rest[used].strip()
           and not re.match(r"^\s*-(\s|$)", rest[used])
           and not re.match(r"^\s+[A-Za-z_][A-Za-z0-9_]*:(\s|$)", rest[used])):
        used += 1
    if used:
        # A plain scalar folded over indented lines.
        return " ".join([value, *(line.strip() for line in rest[:used])]), used
    if value in ("", "~", "null", "Null", "NULL"):
        return None, 0
    if value == "[]":
        return [], 0
    if value == "{}":
        return {}, 0
    if value in ("true", "True"):
        return True, 0
    if value in ("false", "False"):
        return False, 0
    if re.fullmatch(r"-?\d+", value):
        return int(value), 0
    if re.fullmatch(r"-?\d+\.\d+", value):
        return float(value), 0
    return value, 0


def parse_header(text: str) -> tuple[dict, str]:
    """``(header, body)`` of one transcript. The header is the archive's
    YAML subset: top-level scalars (plain, single- or double-quoted, quoted
    ones possibly folded over lines), block lists of scalars, and one-level
    mappings of scalars. The body is every byte after the closing ``---``."""
    if not text.startswith("---\n"):
        return {}, text
    end = text.find("\n---\n", 3)
    if end < 0:
        if text.rstrip().endswith("\n---"):
            end = text.rstrip().rfind("\n---")
        else:
            return {}, text
    block = text[4:end].split("\n")
    body = text[end + 5:]
    header: dict = {}
    i = 0
    while i < len(block):
        line = block[i]
        match = re.match(r"^([A-Za-z_][A-Za-z0-9_]*):(?:\s(.*))?$", line)
        if not match:
            i += 1
            continue
        key, first = match.group(1), (match.group(2) or "")
        i += 1
        if first.strip():
            value, used = _scalar(first, block[i:])
            header[key] = value
            i += used
            continue
        # A block list or a nested mapping, or nothing.
        items: list = []
        mapping: dict = {}
        while i < len(block) and (block[i].startswith(("-", " ")) or not block[i].strip()):
            child = block[i]
            if not child.strip():
                i += 1
                continue
            item = re.match(r"^\s*-\s?(.*)$", child)
            if item and (child.startswith("-") or child.lstrip().startswith("-")):
                value, used = _scalar(item.group(1), block[i + 1:])
                items.append(value)
                i += 1 + used
                continue
            pair = re.match(r"^\s+([A-Za-z_][A-Za-z0-9_]*):\s*(.*)$", child)
            if pair:
                value, used = _scalar(pair.group(2), block[i + 1:])
                mapping[pair.group(1)] = value
                i += 1 + used
                continue
            i += 1
        header[key] = items if items else (mapping if mapping else None)
    return header, body


def read_letter(root: Path, letter_id: str) -> dict:
    """``{"id", "header", "body", "path"}`` for one letter, or LetterError."""
    if not LETTER_ID_RE.match(letter_id or ""):
        raise LetterError("invalid_id", f"not a letter id: {letter_id!r}")
    root = Path(root)
    if not root.is_dir():
        raise LetterError("missing_dir", f"family-letters archive not found at {root}")
    path = transcript_path(root, letter_id)
    if not path.is_file():
        raise LetterError("missing_letter", f"letter {letter_id} not found in {root}")
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise LetterError("unreadable", f"letter {letter_id}: {exc}") from exc
    header, body = parse_header(text)
    return {"id": letter_id, "header": header, "body": body, "path": path}


# --------------------------------------------------------------------------
# The source
# --------------------------------------------------------------------------

def _title(header: dict, body: str, letter_id: str) -> str:
    match = re.search(r"^#\s+(.+?)\s*$", body, re.M)
    if match:
        return match.group(1)
    who, to = header.get("from"), header.get("to")
    if who and to:
        return f"{who} to {to}"
    return f"Letter {letter_id}"


#: The transcript's date at each precision, as EDTF.
PRECISION_CHARS = {"day": 10, "month": 7, "year": 4}


def written_edtf(header: dict) -> str | None:
    """The DATE WRITTEN as EDTF at the transcript's own precision
    (``1984-03-05``, ``1985-12``, ``1985``), or ``None`` when undated."""
    date = str(header.get("date") or "").strip()
    precision = str(header.get("date_precision") or "").strip() or "day"
    width = PRECISION_CHARS.get(precision)
    if not width or len(date) < width:
        return None
    value = date[:width]
    if not re.fullmatch(r"\d{4}(-\d{2}(-\d{2})?)?", value):
        return None
    return value


def _written_at(header: dict) -> str | None:
    """``captured_at`` when the letter is dated TO THE DAY: the day written,
    never the filing date. A month or a year is not a timestamp (and Lifehug
    Cloud's validator refuses a non-ISO value under any ``*_at``/``date`` key),
    so a letter dated only to its month or year is captured at its filing time
    and its written date lives in ``date_edtf``."""
    value = written_edtf(header)
    if value and len(value) == 10:
        return f"{value}T00:00:00Z"
    return None


def render_source(letter: dict, *, filed_at: str) -> tuple[str, str]:
    """``(relative path, file content)`` for one letter. Pure."""
    from source_integrity import SCHEMA_VERSION, format_frontmatter, payload_sha256  # noqa: PLC0415

    letter_id = letter["id"]
    header = dict(letter.get("header") or {})
    body = str(letter.get("body") or "").lstrip("\n")
    relpath = source_relpath(letter_id)
    collection = letter_id.split("/", 1)[0]
    values: dict = {
        "title": _title(header, body, letter_id),
        "type": SOURCE_TYPE,
        "source_id": source_id(letter_id),
        "source_medium": "letter",
        "source_trust": "external_record",
        "authority": "third_party_record",
        "captured_at": _written_at(header) or filed_at,
        "visibility": "owner_only",
        "sensitivity": SENSITIVITY,
        "status": "raw",
        "immutable": True,
        "schema_version": SCHEMA_VERSION,
        "source_path": relpath,
        "content_sha256": payload_sha256(body),
        "letter_id": letter_id,
        "collection": collection,
        "filed_at": filed_at,
        "origin": {"repo": ORIGIN_REPO, "id": letter_id,
                   "path": f"letters/{letter_id}/transcript.md"},
    }
    edtf = written_edtf(header)
    if edtf:
        values["date_edtf"] = edtf
    for key in HEADER_FIELDS:
        if key not in header:
            continue
        if key == "date" and not (edtf and len(edtf) == 10):
            # `date` only as an ISO day: a month or year lives in `date_edtf`
            # (Lifehug Cloud's validator refuses a non-ISO `date`).
            continue
        target = {"status": TRANSCRIPT_STATUS_KEY,
                  "confidence": TRANSCRIPT_CONFIDENCE_KEY}.get(key, key)
        values[target] = header[key]
    return relpath, f"{format_frontmatter(values)}\n\n{body}"


def file_letter(letter_id: str, *, root: Path | None = None,
                now: str | None = None) -> dict:
    """File one letter. Never raises for a missing archive or letter.

    ``{"id", "status", "path", "source_id", "detail"}`` where ``status`` is
    ``filed`` (written now), ``already`` (on file; nothing written) or one of
    :class:`LetterError`'s codes.
    """
    from source_integrity import register_source  # noqa: PLC0415

    letter_id = normalize_id(letter_id)
    out = {"id": letter_id, "source_id": source_id(letter_id), "path": None,
           "status": "", "detail": ""}
    if not LETTER_ID_RE.match(letter_id):
        out.update(status="invalid_id", detail=f"not a letter id: {letter_id!r}")
        return out
    relpath = source_relpath(letter_id)
    target = REPO_DIR / relpath
    out["path"] = relpath
    if target.is_file():
        out.update(status="already", detail="already filed")
        return out
    try:
        letter = read_letter(Path(root) if root is not None else letters_dir(), letter_id)
    except LetterError as exc:
        out.update(status=exc.code, detail=str(exc), path=None)
        return out
    _rel, content = render_source(letter, filed_at=now or now_utc())
    write_text(target, content)
    register_source(target)
    out.update(status="filed", detail="filed")
    return out


def file_cited(ref: str | None, *, root: Path | None = None,
               now: str | None = None) -> list[dict]:
    """File every letter a ``family-letters:`` reference names."""
    return [file_letter(letter_id, root=root, now=now) for letter_id in ids_from_ref(ref)]


def on_file(outcome: dict) -> bool:
    return outcome.get("status") in ("filed", "already")


def outcome_line(outcome: dict) -> str:
    """One honest line per letter, the shape intake parses."""
    status = outcome.get("status")
    if status == "filed":
        return f"✓ Filed letter {outcome['id']}: {outcome['path']}"
    if status == "already":
        return f"  letter {outcome['id']} already filed: {outcome['path']}"
    return f"! letter {outcome['id']} not filed ({status}): {outcome.get('detail')}"


# --------------------------------------------------------------------------
# cites: on the memo that cites a letter
# --------------------------------------------------------------------------

def _frontmatter_bounds(content: str) -> tuple[int, int] | None:
    if not content.startswith("---\n"):
        return None
    end = content.find("\n---", 3)
    if end < 0:
        return None
    return 4, end


def merged_cites(existing: object, add: list[str]) -> list[str]:
    rows = [str(v) for v in existing] if isinstance(existing, list) else []
    for value in add:
        if value not in rows:
            rows.append(value)
    return rows


def with_cites(content: str, add: list[str]) -> str | None:
    """``content`` with ``cites`` merged into its frontmatter; ``None`` when
    nothing changes. Only the one ``cites:`` line is written or replaced; every
    other byte of the file is kept."""
    bounds = _frontmatter_bounds(content)
    if bounds is None or not add:
        return None
    start, end = bounds
    metadata, _body = split_frontmatter(content)
    cites = merged_cites(metadata.get(CITES_KEY), add)
    if cites == metadata.get(CITES_KEY):
        return None
    line = f"{CITES_KEY}: {json.dumps(cites, ensure_ascii=True)}"
    block = content[start:end].split("\n")
    for index, row in enumerate(block):
        if row.startswith(f"{CITES_KEY}:"):
            block[index] = line
            break
    else:
        block.append(line)
    return content[:start] + "\n".join(block) + content[end:]


def stamp_cites(path: Path, add: list[str]) -> bool:
    """Merge ``add`` into one source's ``cites``; re-register it. True when
    the file changed."""
    from source_integrity import register_source  # noqa: PLC0415

    path = Path(path)
    content = path.read_text(encoding="utf-8")
    updated = with_cites(content, add)
    if updated is None:
        return False
    write_text(path, updated)
    register_source(path)
    return True


def citing_memos(letter_ids: list[str]) -> dict[str, list[str]]:
    """``{memo relative path: [letter ids it names]}`` for every non-letter
    source whose ``record_ref`` names one of ``letter_ids``."""
    wanted = set(letter_ids)
    found: dict[str, list[str]] = {}
    base = SOURCES_DIR
    if not base.is_dir():
        return found
    for path in sorted(base.rglob("*.md")):
        rel = path.relative_to(REPO_DIR).as_posix()
        if rel.startswith(f"sources/{LETTERS_SUBDIR}/"):
            continue
        try:
            head = path.read_text(encoding="utf-8")[:8192]
        except (OSError, UnicodeDecodeError):
            continue
        if RECORD_REF_PREFIX not in head:
            continue
        metadata, _body = split_frontmatter(head if "\n---" in head[4:] else "")
        named = [i for i in ids_from_ref(str(metadata.get("record_ref") or "")) if i in wanted]
        if named:
            found[rel] = named
    return found


def link_citing_memos(letter_ids: list[str]) -> list[str]:
    """Stamp ``cites`` on every memo that names one of these (filed) letters.
    Returns the memos that changed."""
    changed = []
    for rel, named in citing_memos(letter_ids).items():
        if stamp_cites(REPO_DIR / rel, [source_id(i) for i in named]):
            changed.append(rel)
    return changed


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def file_and_link(refs: list[str], *, root: Path | None = None,
                  now: str | None = None) -> dict:
    """The ``intake letter`` door: file each letter, then link the memos that
    already cite the ones on file."""
    ids: list[str] = []
    for ref in refs:
        named = ids_from_ref(ref) if str(ref).startswith(RECORD_REF_PREFIX) else [normalize_id(ref)]
        for letter_id in named:
            if letter_id not in ids:
                ids.append(letter_id)
    outcomes = [file_letter(letter_id, root=root, now=now) for letter_id in ids]
    linked = link_citing_memos([o["id"] for o in outcomes if on_file(o)])
    return {"letters": outcomes, "linked": linked}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="File family letters as letter sources")
    sub = parser.add_subparsers(dest="verb")
    f = sub.add_parser("file", help="file letters by id and link the memos that cite them")
    f.add_argument("ids", nargs="+", help="<collection>/<letter> or family-letters:<id>[,<id>]")
    f.add_argument("--dir", default=None, help=f"the archive (default: ${ENV_DIR}, "
                                               f"config {CONFIG_KEY}, {DEFAULT_DIR})")
    f.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    if args.verb != "file":
        parser.print_help()
        return 1
    root = Path(args.dir).expanduser() if args.dir else letters_dir()
    result = file_and_link(args.ids, root=root)
    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        for outcome in result["letters"]:
            print(outcome_line(outcome))
        for rel in result["linked"]:
            print(f"✓ Linked {rel} (cites)")
    return 0 if all(on_file(o) for o in result["letters"]) else 1


__all__ = [
    "CITES_KEY", "LETTER_ID_RE", "LetterError", "RECORD_REF_PREFIX", "SOURCE_ID_PREFIX",
    "SOURCE_TYPE", "citing_memos", "file_and_link", "file_cited", "file_letter",
    "ids_from_ref", "letters_dir", "link_citing_memos", "merged_cites", "on_file",
    "outcome_line", "parse_header", "read_letter", "render_source", "source_id",
    "source_relpath", "stamp_cites", "with_cites",
]


if __name__ == "__main__":
    raise SystemExit(main())
