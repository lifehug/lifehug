#!/usr/bin/env python3
"""A family letter is filed as a letter (letters-in-the-vault D1, v404 + v412).

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
  third_party_record``, or ``first_person_record`` when the owner wrote it),
  sensitivity ``family``, ``source_id letters:<collection>--<letter>`` (no
  ``/``: see :func:`source_id`), the header fields the vault can use in the
  frontmatter, and the transcript body VERBATIM. Manifest-registered through
  ``source_integrity`` like every source. It is THE writer of a letter record
  for every door: ``intake`` (the archive's working tree) and ``documents
  file`` (v412: the archive read through git at a pinned commit) hand it the
  same transcript and get the same record.
* v412 adds, on top of v404's record: ``author_refs`` / ``recipient_refs`` /
  ``subject_refs`` resolved through the archive's ``letters/people.yaml`` and
  the vault's ``--map`` (`letter_people`); ``origin`` with ``commit``,
  ``source_file``, ``source_pages``, ``scan_blob``, ``scan_url`` and
  ``transcript_blob``; and, AFTER the verbatim body, a trailing section
  holding the transcript's own YAML header verbatim, so
  :func:`transcript_from_record` rebuilds the archive's file byte for byte
  (source-lint checks it against ``origin.transcript_blob``).
* Idempotent: a letter whose current record IS this transcript is never
  rewritten. A REVISED transcript (its blob changed) files a NEW record that
  ``supersedes`` the current one —
  ``sources/letters/<collection>--<letter>--<blob12>.md``, ``source_id
  letters:<collection>--<letter>:<blob12>`` — and the old record stays. The
  first record keeps the bare id for good.
* :func:`stamp_cites` — adds ``cites: [<letter source id>, …]`` to the frontmatter
  of a record memo. Frontmatter only: the body, and so ``content_sha256``,
  is untouched.
* :func:`link_citing_memos` — every record memo whose ``record_ref`` names a
  letter gets that letter in its ``cites``. This is how a memo filed before
  v404 (or filed while the archive was not on this machine) is linked once
  the letter is filed.

A missing archive or a missing letter is never a crash: one honest line, and
the caller files whatever it was filing exactly as before.

CLI (``lifehug.py intake letter`` and ``lifehug.py documents file`` are the
doors; this is the worker)::

    python3 system/family_letters.py file <id|family-letters:<id>[,<id>]> … [--json]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
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

#: The trailing section that keeps the transcript's own YAML header verbatim
#: AFTER the verbatim body (v412), so the archive's file rebuilds exactly.
TRAILER_MARKER = "<!-- lifehug:transcript-header -->"
TRAILER_HEADING = "## Transcript header"

#: Between a letter's source id and a superseding version's blob token:
#: ``letters:<collection>--<letter>:<blob12>`` (v412).
VERSION_SEPARATOR = ":"
_VERSION_SUFFIX_RE = re.compile(r":[0-9a-f]{12}$")


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
    text = _VERSION_SUFFIX_RE.sub("", text.strip().strip("`").strip())
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
    """One letter from the archive's WORKING TREE (the ``intake`` doors):
    ``{"id", "header", "body", "path", "raw", "transcript_blob", "commit",
    "scan_blob"}``, or LetterError.

    ``commit`` is the archive's HEAD only when the transcript on disk IS the
    one HEAD holds (same git blob), so a letter filed here and the same letter
    filed by ``documents file --commit HEAD`` are the same record. An
    uncommitted transcript files with ``commit: null``."""
    if not LETTER_ID_RE.match(letter_id or ""):
        raise LetterError("invalid_id", f"not a letter id: {letter_id!r}")
    root = Path(root)
    if not root.is_dir():
        raise LetterError("missing_dir", f"family-letters archive not found at {root}")
    path = transcript_path(root, letter_id)
    if not path.is_file():
        raise LetterError("missing_letter", f"letter {letter_id} not found in {root}")
    try:
        data = path.read_bytes()
        text = data.decode("utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise LetterError("unreadable", f"letter {letter_id}: {exc}") from exc
    header, body = parse_header(text)
    blob = git_blob_sha(data)
    commit, scan_blob = _working_tree_origin(root, letter_id, blob, header)
    return {"id": letter_id, "header": header, "body": body, "path": path, "raw": text,
            "transcript_blob": blob, "commit": commit, "scan_blob": scan_blob}


def git_blob_sha(data: bytes) -> str:
    """The id ``git hash-object`` gives these bytes."""
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


def scan_candidates(source_file: str) -> list[str]:
    """Where a header's ``source_file`` lives in the archive: under
    ``source/`` (the letters repo's layout), else as written."""
    return [f"source/{source_file}", source_file] if source_file else []


def _git_out(root: Path, *args: str) -> str | None:
    try:
        done = subprocess.run(["git", "-C", str(root), *args], capture_output=True,
                              text=True, check=False, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None
    return done.stdout.strip() if done.returncode == 0 else None


def _working_tree_origin(root: Path, letter_id: str, blob: str,
                         header: dict) -> tuple[str | None, str | None]:
    """``(commit, scan_blob)`` for a transcript read from the working tree."""
    source_file = str(header.get("source_file") or "")
    commit = None
    if (root / ".git").exists():
        head = _git_out(root, "rev-parse", "--verify", "--quiet", "HEAD^{commit}")
        at_head = _git_out(root, "rev-parse", "--verify", "--quiet",
                           f"HEAD:letters/{letter_id}/transcript.md") if head else None
        if head and at_head == blob:
            commit = head
            for spec in scan_candidates(source_file):
                oid = _git_out(root, "rev-parse", "--verify", "--quiet", f"HEAD:{spec}")
                if oid:
                    return commit, oid
            return commit, None
    for spec in scan_candidates(source_file):
        scan = root / spec
        if scan.is_file():
            try:
                return commit, git_blob_sha(scan.read_bytes())
            except OSError:
                return commit, None
    return commit, None


def split_exact(raw: str | None) -> tuple[str, str] | None:
    """``(header text, body)`` such that ``---\\n{header}\\n---\\n{body}`` IS
    ``raw``, or ``None`` when the transcript has no header to keep."""
    if not raw or not raw.startswith("---\n"):
        return None
    end = raw.find("\n---\n", 3)
    if end < 0:
        return None
    header_text, body = raw[4:end], raw[end + 5:]
    if f"---\n{header_text}\n---\n{body}" != raw:
        return None
    return header_text, body


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


def header_values(header: dict) -> dict:
    """The header fields as the record's frontmatter carries them (v404)."""
    values: dict = {}
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
    return values


def trailer(header_text: str) -> str:
    """The section after the verbatim body that keeps the transcript's own
    YAML header verbatim, so :func:`transcript_from_record` can rebuild the
    archive's file exactly. Fenced one backtick longer than any run inside."""
    longest = max((len(run) for run in re.findall(r"`+", header_text)), default=0)
    fence = "`" * max(3, longest + 1)
    return (f"\n{TRAILER_MARKER}\n{TRAILER_HEADING}\n\n"
            "The letters project's own header for this transcript, kept verbatim.\n\n"
            f"{fence}yaml\n{header_text}\n{fence}\n")


def _payload_after_frontmatter(text: str) -> str:
    if not text.startswith("---\n"):
        raise LetterError("unreadable", "record has no frontmatter")
    end = text.find("\n---\n", 3)
    if end == -1:
        raise LetterError("unreadable", "record frontmatter is not closed")
    return text[end + len("\n---\n"):]


def has_trailer(text: str) -> bool:
    return f"\n{TRAILER_MARKER}\n" in text


def transcript_from_record(text: str) -> bytes:
    """The archive's ``transcript.md`` bytes, rebuilt from a filed record:
    ``---``, the trailer's header, ``---``, then the verbatim body."""
    payload = _payload_after_frontmatter(text)
    cut = payload.rfind(f"\n{TRAILER_MARKER}\n")
    if cut == -1:
        raise LetterError("unreadable", "record has no transcript-header trailer")
    body, tail = payload[:cut], payload[cut:]
    match = re.search(r"\n(`{3,})yaml\n(.*)\n\1\n\Z", tail, re.S)
    if not match:
        raise LetterError("unreadable", "record's transcript-header trailer is malformed")
    return f"---\n{match.group(2)}\n---\n{body}".encode("utf-8")


def version_token(letter: dict) -> str:
    """The 12-hex suffix a superseding version carries: its transcript blob.
    Content-addressed, so both doors (and any commit) name a revision the
    same way."""
    blob = str(letter.get("transcript_blob") or "")
    if not blob:
        blob = git_blob_sha(str(letter.get("raw") or letter.get("body") or "").encode("utf-8"))
    return blob[:12]


def versioned_source_id(letter_id: str, token: str) -> str:
    """``letters:<collection>--<letter>:<blob12>``. ``:`` is the separator
    because Lifehug Cloud's validator accepts it in an id
    (``^[A-Za-z0-9][A-Za-z0-9:._-]{0,127}$``) and a letter id never holds it;
    ``@`` and ``/`` are both ``INVALID_ID`` there."""
    return f"{source_id(letter_id)}{VERSION_SEPARATOR}{token}"


def versioned_relpath(letter_id: str, token: str) -> str:
    return f"sources/{LETTERS_SUBDIR}/{source_stem(letter_id)}--{token}.md"


def filing_context(root: Path | None = None, *, people=None, people_map: dict | None = None,
                   scan_url_template: str | None = None, repo: str | None = None) -> dict:
    """Who-is-who and where-it-came-from for a filing: the archive's
    people.yaml (working tree when ``people`` is not given), the vault's
    remembered ``--map`` / scan URL template / repo name
    (``state/documents/letters.json``), and any overrides."""
    import letter_people as lp  # noqa: PLC0415

    config = lp.load_config()
    if people is None:
        try:
            people = lp.People.from_archive(Path(root)) if root is not None else lp.People(None)
        except lp.PeopleError:
            people = lp.People(None)
    return {
        "people": people,
        "people_map": {**config["people_map"], **(people_map or {})},
        "scan_url_template": scan_url_template or config.get("scan_url_template") or None,
        "repo": repo or config.get("repo") or ORIGIN_REPO,
    }


def letter_refs(letter: dict, context: dict | None) -> dict[str, list[str]]:
    import letter_people as lp  # noqa: PLC0415

    context = context or {}
    collection = letter["id"].split("/", 1)[0]
    return lp.refs_for(dict(letter.get("header") or {}), collection,
                       context.get("people") or lp.People(None),
                       context.get("people_map") or {})


def render_source(letter: dict, *, filed_at: str, context: dict | None = None,
                  supersedes: dict | None = None) -> tuple[str, str]:
    """``(relative path, file content)`` for one letter. Pure.

    ``context`` (:func:`filing_context`) resolves the refs and the origin's
    repo and scan URL; without one the letter names nobody and its origin is
    ``lifehug/letters``. ``supersedes`` (``{"source_id", "path"}``) makes this
    a superseding version: its own path and id carry :func:`version_token`."""
    from source_integrity import SCHEMA_VERSION, format_frontmatter, payload_sha256  # noqa: PLC0415

    import letter_people as lp  # noqa: PLC0415

    context = context or {}
    letter_id = letter["id"]
    header = dict(letter.get("header") or {})
    exact = split_exact(letter.get("raw"))
    raw_body = exact[1] if exact else str(letter.get("body") or "")
    body = raw_body.lstrip("\n")
    if supersedes:
        token = version_token(letter)
        relpath = versioned_relpath(letter_id, token)
        sid = versioned_source_id(letter_id, token)
    else:
        relpath, sid = source_relpath(letter_id), source_id(letter_id)
    collection = letter_id.split("/", 1)[0]
    refs = letter_refs(letter, context)
    source_file = str(header.get("source_file") or "") or None
    source_pages = header.get("source_pages")
    template = context.get("scan_url_template")
    collection_slug = letter_id.split("/", 1)
    origin = {
        "repo": context.get("repo") or ORIGIN_REPO,
        "id": letter_id,
        "path": f"letters/{letter_id}/transcript.md",
        "commit": letter.get("commit") or None,
        "source_file": source_file,
        "source_pages": source_pages if isinstance(source_pages, list) else None,
        "scan_blob": letter.get("scan_blob") or None,
        "scan_url": (template.format(id=letter_id, collection=collection_slug[0],
                                     slug=collection_slug[1], letter=collection_slug[1])
                     if template else None),
        "transcript_blob": letter.get("transcript_blob") or None,
    }
    values: dict = {
        "title": _title(header, body, letter_id),
        "type": SOURCE_TYPE,
        "source_id": sid,
        "source_medium": "letter",
        "source_trust": "external_record",
        "authority": ("first_person_record" if lp.OWNER_REF in refs["author_refs"]
                      else "third_party_record"),
        "captured_at": _written_at(header) or filed_at,
        "visibility": "owner_only",
        "sensitivity": SENSITIVITY,
        "status": "raw",
        "immutable": True,
        "schema_version": SCHEMA_VERSION,
        "source_path": relpath,
        "content_sha256": "",
        "letter_id": letter_id,
        "collection": collection,
        "filed_at": filed_at,
        "origin": origin,
        **refs,
    }
    if supersedes:
        values["supersedes"] = supersedes["source_id"]
        values["supersedes_path"] = supersedes["path"]
    values.update(header_values(header))
    if exact:
        # The body verbatim, then the header verbatim: the record rebuilds
        # the archive's file byte for byte (`transcript_from_record`).
        payload = f"{raw_body}{trailer(exact[0])}"
        joiner = "\n"
    else:
        payload, joiner = body, "\n\n"
    _meta, split_body = split_frontmatter(f"{format_frontmatter(values)}{joiner}{payload}")
    values["content_sha256"] = payload_sha256(split_body)
    return relpath, f"{format_frontmatter(values)}{joiner}{payload}"


# --------------------------------------------------------------------------
# What the vault already holds: versions, and which one is current
# --------------------------------------------------------------------------

def letter_index() -> dict[str, list[dict]]:
    """Every filed letter record, by archive id: ``{"path", "source_id",
    "supersedes", "meta", "abs"}``. Frontmatter decides, not the path."""
    out: dict[str, list[dict]] = {}
    base = SOURCES_DIR / LETTERS_SUBDIR
    if not base.is_dir():
        return out
    for path in sorted(base.glob("*.md")):
        try:
            metadata, _body = split_frontmatter(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError):
            continue
        if metadata.get("type") != SOURCE_TYPE or not metadata.get("letter_id"):
            continue
        _add_to_index(out, path, metadata)
    return out


def _add_to_index(index: dict, path: Path, metadata: dict) -> None:
    index.setdefault(str(metadata["letter_id"]), []).append({
        "path": path.relative_to(REPO_DIR).as_posix(),
        "abs": path,
        "source_id": str(metadata.get("source_id") or ""),
        "supersedes": str(metadata.get("supersedes") or ""),
        "meta": metadata,
    })


def current_record(records: list[dict]) -> dict | None:
    """The version nothing supersedes. A healthy chain has exactly one; if a
    chain is ever broken, a superseding version outranks an original."""
    if not records:
        return None
    superseded = {r["supersedes"] for r in records if r["supersedes"]}
    heads = [r for r in records if r["source_id"] not in superseded] or records
    return sorted(heads, key=lambda r: (bool(r["supersedes"]),
                                        str(r["meta"].get("filed_at") or ""), r["path"]))[-1]


def same_transcript(record: dict, letter: dict) -> bool:
    """Is this filed record the letter as the archive now holds it?

    A record that names its ``origin.transcript_blob`` is compared by blob. A
    v404 record (no blob) is the same when its body and every header field it
    carries are the transcript's."""
    from source_integrity import payload_sha256  # noqa: PLC0415

    meta = record["meta"]
    origin = meta.get("origin") if isinstance(meta.get("origin"), dict) else {}
    blob = origin.get("transcript_blob")
    if blob:
        return blob == letter.get("transcript_blob")
    exact = split_exact(letter.get("raw"))
    body = exact[1] if exact else str(letter.get("body") or "")
    if meta.get("content_sha256") != payload_sha256(body):
        return False
    expected = header_values(dict(letter.get("header") or {}))
    return all(meta.get(key) == value for key, value in expected.items())


def file_letter(letter_id: str, *, root: Path | None = None, now: str | None = None,
                letter: dict | None = None, context: dict | None = None,
                index: dict | None = None, register: bool = True,
                dry_run: bool = False) -> dict:
    """File one letter — THE writer of a letter record, for every door.
    Never raises for a missing archive or letter.

    ``letter`` is a transcript already read (``documents file`` reads it
    through git at a commit); without it the archive's working tree at
    ``root`` is read. ``context`` is :func:`filing_context`'s. ``index``
    (:func:`letter_index`) is reused across a bulk filing. ``register=False``
    leaves the manifest to the caller (one sync for many records).

    ``{"id", "status", "path", "source_id", "detail", …}`` where ``status`` is
    ``filed`` (written now; with ``supersedes`` when it is a new version of a
    revised transcript), ``would_file`` (``dry_run``), ``already`` (the
    current record IS this transcript; nothing written), ``conflict``, or one
    of :class:`LetterError`'s codes.
    """
    from source_integrity import register_source  # noqa: PLC0415

    letter_id = normalize_id(letter_id)
    out = {"id": letter_id, "source_id": source_id(letter_id), "path": None,
           "status": "", "detail": ""}
    if not LETTER_ID_RE.match(letter_id):
        out.update(status="invalid_id", detail=f"not a letter id: {letter_id!r}")
        return out
    index = letter_index() if index is None else index
    current = current_record(index.get(letter_id, []))
    if letter is None:
        archive = Path(root) if root is not None else letters_dir()
        try:
            letter = read_letter(archive, letter_id)
        except LetterError as exc:
            if current is not None:
                # On file; the archive cannot say whether it was revised.
                out.update(status="already", path=current["path"],
                           source_id=current["source_id"],
                           detail=f"already filed (not checked for a revision: {exc.code})")
                return out
            out.update(status=exc.code, detail=str(exc))
            return out
        if context is None:
            context = filing_context(archive)
    context = context if context is not None else filing_context(None)
    import letter_people as lp  # noqa: PLC0415

    collection = letter_id.split("/", 1)[0]
    out["unmapped"] = lp.unmapped_ids(dict(letter.get("header") or {}), collection,
                                      context["people"], context["people_map"])
    if current is not None and same_transcript(current, letter):
        refs = letter_refs(letter, context)
        out.update(status="already", path=current["path"], source_id=current["source_id"],
                   detail="already filed",
                   refs_drifted=any(key in current["meta"] and current["meta"][key] != value
                                    for key, value in refs.items()))
        return out
    supersedes = ({"source_id": current["source_id"], "path": current["path"]}
                  if current is not None else None)
    filed_at = now or now_utc()
    relpath, content = render_source(letter, filed_at=filed_at, context=context,
                                     supersedes=supersedes)
    out.update(path=relpath, source_id=split_frontmatter(content)[0]["source_id"])
    if supersedes:
        out["supersedes"] = supersedes
    out["authority"] = split_frontmatter(content)[0]["authority"]
    target = REPO_DIR / relpath
    if target.exists():
        out.update(status="conflict", path=None,
                   detail=f"{relpath} exists but is not the current version; refusing to overwrite")
        return out
    problems = letter_problems(split_frontmatter(content)[0], content)
    if problems:
        out.update(status="invalid", path=None, detail="; ".join(problems))
        return out
    if dry_run:
        out.update(status="would_file", detail="would file")
        return out
    write_text(target, content)
    if register:
        register_source(target)
    _add_to_index(index, target, split_frontmatter(content)[0])
    out.update(status="filed", detail="filed")
    return out


def file_cited(ref: str | None, *, root: Path | None = None,
               now: str | None = None) -> list[dict]:
    """File every letter a ``family-letters:`` reference names."""
    return [file_letter(letter_id, root=root, now=now) for letter_id in ids_from_ref(ref)]


def on_file(outcome: dict) -> bool:
    return outcome.get("status") in ("filed", "already")


def outcome_line(outcome: dict) -> str:
    """One honest line per letter, the shape intake parses (a superseding
    version adds one indented line after it)."""
    status = outcome.get("status")
    if status == "filed":
        line = f"✓ Filed letter {outcome['id']}: {outcome['path']}"
        if outcome.get("supersedes"):
            old = outcome["supersedes"]
            line += f"\n  supersedes {old['source_id']} ({old['path']}); the old record stays"
        return line
    if status == "already":
        return f"  letter {outcome['id']} already filed: {outcome['path']}"
    return f"! letter {outcome['id']} not filed ({status}): {outcome.get('detail')}"


# --------------------------------------------------------------------------
# What a letter record must keep (source-lint; one definition)
# --------------------------------------------------------------------------

#: Lifehug Cloud's vault validator's id rule (`INVALID_ID`, hard reject).
PLATFORM_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9:._-]{0,127}$")
AUTHORITIES = ("third_party_record", "first_person_record")


def letter_problems(metadata: dict, text: str | None = None) -> list[str]:
    """Why a ``type: letter`` record is malformed (empty when it is not).
    A v404 record (no refs, no trailer) passes on the checks it can."""
    import letter_people as lp  # noqa: PLC0415

    problems: list[str] = []
    if metadata.get("source_trust") != "external_record":
        problems.append("source_trust must be external_record")
    if metadata.get("sensitivity") != SENSITIVITY:
        problems.append("sensitivity must be family")
    if metadata.get("immutable") is not True:
        problems.append("immutable must be true")
    sid = str(metadata.get("source_id") or "")
    if not PLATFORM_ID_RE.match(sid) or not sid.startswith(SOURCE_ID_PREFIX):
        problems.append(f"source_id {sid!r} is not a letters: id Lifehug Cloud accepts")
    authority = metadata.get("authority")
    if authority not in AUTHORITIES:
        problems.append(f"authority {authority!r} is not one of {', '.join(AUTHORITIES)}")
    refs_ok = True
    for key in ("author_refs", "recipient_refs", "subject_refs"):
        if key not in metadata:
            continue
        value = metadata[key]
        if not isinstance(value, list) or not all(isinstance(r, str) and lp.REF_RE.match(r)
                                                  for r in value):
            problems.append(f"{key} must be a list of refs")
            refs_ok = False
    if refs_ok and authority in AUTHORITIES:
        first_person = lp.OWNER_REF in (metadata.get("author_refs") or [])
        if first_person != (authority == "first_person_record"):
            problems.append("authority does not match whether the owner wrote it")
    origin = metadata.get("origin")
    blob = origin.get("transcript_blob") if isinstance(origin, dict) else None
    if text is not None and (blob or has_trailer(text)):
        try:
            rebuilt = transcript_from_record(text)
        except LetterError as exc:
            problems.append(str(exc))
        else:
            if blob and git_blob_sha(rebuilt) != blob:
                problems.append("body no longer rebuilds the filed transcript (origin.transcript_blob)")
    return problems


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


def link_citing_memos(letter_ids: list[str] | dict[str, str]) -> list[str]:
    """Stamp ``cites`` on every memo that names one of these (filed) letters.
    ``letter_ids`` may map each id to the source id to cite (the CURRENT
    version's, v412); a plain list cites the bare id. Returns the memos that
    changed."""
    wanted = letter_ids if isinstance(letter_ids, dict) else {i: source_id(i) for i in letter_ids}
    changed = []
    for rel, named in citing_memos(list(wanted)).items():
        if stamp_cites(REPO_DIR / rel, [wanted[i] for i in named]):
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
    linked = link_citing_memos({o["id"]: o["source_id"] for o in outcomes if on_file(o)})
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
    "CITES_KEY", "LETTER_ID_RE", "LetterError", "PLATFORM_ID_RE", "RECORD_REF_PREFIX",
    "SOURCE_ID_PREFIX", "SOURCE_TYPE", "TRAILER_MARKER", "citing_memos", "current_record",
    "file_and_link", "file_cited", "file_letter", "filing_context", "git_blob_sha",
    "header_values", "ids_from_ref", "letter_index", "letter_problems", "letters_dir",
    "link_citing_memos", "merged_cites", "on_file", "outcome_line", "parse_header",
    "read_letter", "render_source", "same_transcript", "source_id", "source_relpath",
    "split_exact", "stamp_cites", "transcript_from_record", "versioned_source_id",
    "with_cites",
]


if __name__ == "__main__":
    raise SystemExit(main())
