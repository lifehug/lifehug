#!/usr/bin/env python3
"""Documents: file finished letter transcripts into the vault as records.

lifehug#471, PR 1 (design: docs/pr-specs/letters-in-the-vault.md, D1).

A letters repository (the family-letters workshop: scan, transcribe, review,
answer pass) holds one ``letters/<collection>/<slug>/transcript.md`` per
document. ``documents file`` files a COPY of each finished transcript into the
vault as an immutable ``type: letter`` source under
``sources/letters/<collection>/<slug>.md``:

* the frontmatter is Lifehug's (who wrote it, to whom, about whom, when it
  was written, where it came from, pinned to a commit and blob);
* the body is the transcript body byte for byte, followed by one trailing
  section holding the transcript's own YAML header verbatim, so the original
  transcript can be rebuilt exactly (:func:`transcript_from_record`).

Filing is Loop-adjacent. It is never run by the daily, weekly or monthly
rhythm, and it creates no question candidates, conversation turns or
classifications. It reads the letters repository through ``git`` at the
named commit — never its working tree — so what is filed is exactly what
that commit holds. The letters repository is never written to.

Re-running on the same commit changes nothing. A transcript whose blob has
changed since its last filed version gets a NEW record that ``supersedes``
the old one (``letters:<id>@<old commit>``); the old record stays, as the
source contract requires of every raw source.

The vault-specific part — which ``people.yaml`` id is which vault person —
is user data, not framework: ``--map ID=REF`` (``self`` for the owner), kept
in ``state/documents/letters.json`` once a real filing has used it.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

import mini_yaml
from lifehug_core import (
    SOURCES_DIR,
    STATE_DIR,
    read_json,
    split_frontmatter,
    write_json,
    write_text,
)
from source_integrity import LETTER_TYPE, payload_sha256, rel, source_record, sync_manifest

LETTERS_DIR = SOURCES_DIR / "letters"
LETTERS_CONFIG_FILE = STATE_DIR / "documents" / "letters.json"
SOURCE_ID_PREFIX = "letters:"
SCHEMA_VERSION = 1

#: The owner's subject ref. `temporal_work_items` owns the string; every
#: claim the fold reads names the owner this way.
OWNER_REF = "self"

#: `document_type` as the letters project writes it.
DOCUMENT_TYPES = ("letter", "card", "note", "newsletter", "postcard", "envelope_only", "other")
#: `written_date_precision` vocabulary, one per EDTF shape below.
DATE_PRECISIONS = ("day", "month", "year", "unknown")
AUTHORITIES = ("third_party_record", "first_person_record")
ORIGIN_KEYS = (
    "repo", "id", "commit", "source_file", "source_pages",
    "scan_blob", "scan_url", "transcript_blob",
)
#: Frontmatter keys every letter record carries (beyond the source contract's
#: own REQUIRED_SOURCE_KEYS).
LETTER_FIELDS = (
    "source_trust", "authority", "sensitivity", "document_type", "collection",
    "written_date", "written_date_precision", "written_date_evidence",
    "author_label", "recipient_label", "author_refs", "recipient_refs",
    "subject_refs", "origin",
)
#: Copied into state/source_manifest.json so the Sources view and the reader
#: can show a letter without reopening it.
LETTER_MANIFEST_FIELDS = (
    "authority", "sensitivity", "document_type", "collection", "written_date",
    "written_date_precision", "author_label", "recipient_label", "author_refs",
    "recipient_refs", "subject_refs", "supersedes", "origin",
)

#: people.yaml ids that name nobody: never a ref.
UNRESOLVED_PEOPLE_IDS = frozenset({"unknown"})

TRAILER_MARKER = "<!-- lifehug:transcript-header -->"
TRAILER_HEADING = "## Transcript header"

_TRANSCRIPT_PATH_RE = re.compile(r"^letters/([a-z0-9][a-z0-9-]*)/([a-z0-9][a-z0-9-]*)/transcript\.md$")
_TRANSCRIPT_RE = re.compile(r"^---\n(.*?)\n---\n(.*)$", re.S)
_REF_RE = re.compile(r"^(self|(person|place|period|object|theme|project)/[a-z0-9][a-z0-9-]*)$")
_EDTF = {
    "day": re.compile(r"^\d{4}-\d{2}-\d{2}$"),
    "month": re.compile(r"^\d{4}-\d{2}$"),
    "year": re.compile(r"^\d{4}$"),
}


class DocumentsError(RuntimeError):
    """A filing that must not proceed (bad repo, commit, map or transcript)."""


# ── the letters repository, read through git at one commit ────────────────


def _git(repo: Path, *args: str, stdin: bytes | None = None) -> bytes:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        input=stdin, capture_output=True, check=False,
    )
    if result.returncode != 0:
        raise DocumentsError(
            f"git {' '.join(args[:2])} failed in {repo}: "
            + result.stderr.decode("utf-8", "replace").strip()
        )
    return result.stdout


def resolve_commit(repo: Path, commit: str) -> str:
    if not commit or commit.startswith("-"):
        raise DocumentsError("--commit must name a commit")
    return _git(repo, "rev-parse", "--verify", "--quiet", f"{commit}^{{commit}}").decode().strip()


def repo_name(repo: Path) -> str:
    """``owner/name`` from the repository's origin URL, else its directory."""
    try:
        url = _git(repo, "remote", "get-url", "origin").decode().strip()
    except DocumentsError:
        return repo.resolve().name
    match = re.search(r"[:/]([^/:]+/[^/]+?)(?:\.git)?/?$", url)
    return match.group(1) if match else repo.resolve().name


def _batch_objects(repo: Path, specs: list[str]) -> dict[str, tuple[str, bytes] | None]:
    """``git cat-file --batch`` over ``<commit>:<path>`` specs."""
    if not specs:
        return {}
    for spec in specs:
        if "\n" in spec:
            raise DocumentsError(f"path with a newline: {spec!r}")
    out = _git(repo, "cat-file", "--batch", stdin=("\n".join(specs) + "\n").encode("utf-8"))
    found: dict[str, tuple[str, bytes] | None] = {}
    pos = 0
    for spec in specs:
        nl = out.index(b"\n", pos)
        header = out[pos:nl].decode("utf-8", "replace")
        pos = nl + 1
        if header.endswith(" missing") or header.endswith(" ambiguous"):
            found[spec] = None
            continue
        oid, _kind, size = header.split(" ")
        data = out[pos:pos + int(size)]
        pos += int(size) + 1
        found[spec] = (oid, data)
    return found


def _batch_oids(repo: Path, specs: list[str]) -> dict[str, str | None]:
    if not specs:
        return {}
    out = _git(
        repo, "cat-file", "--batch-check=%(objectname) %(objecttype)",
        stdin=("\n".join(specs) + "\n").encode("utf-8"),
    ).decode("utf-8", "replace").splitlines()
    result: dict[str, str | None] = {}
    for spec, line in zip(specs, out):
        parts = line.split(" ")
        result[spec] = parts[0] if len(parts) == 2 and parts[1] == "blob" else None
    return result


def git_blob_sha(data: bytes) -> str:
    """The id ``git hash-object`` gives these bytes."""
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


# ── people.yaml: the letters site's resolver, ported ──────────────────────


class People:
    """Port of the letters site's ``pipeline/build_site.py`` ``People``.

    Every alias is a case-insensitive regex; a dict alias ``{p: ..., in:
    [collections]}`` applies only inside those collections. ``resolve`` returns
    the people.yaml ids named in a from/to string, primary first: the earliest
    match wins (then the longest), and other parties count only when they are
    named outside parentheses and quotes. A string no alias matches resolves to
    an automatic ``other-<name>`` id, exactly as the site does; such ids name
    nobody in people.yaml and never become refs.
    """

    def __init__(self, cfg: dict):
        people = cfg.get("people") if isinstance(cfg, dict) else None
        if not isinstance(people, list):
            raise DocumentsError("people.yaml has no people list")
        self.by_id: dict[str, dict] = {}
        self.rules: list[tuple[re.Pattern, set[str] | None, str]] = []
        for person in people:
            if not isinstance(person, dict) or not isinstance(person.get("id"), str):
                raise DocumentsError("people.yaml entry without an id")
            self.by_id[person["id"]] = person
            for alias in person.get("aliases") or []:
                if isinstance(alias, dict):
                    pattern, colls = str(alias["p"]), set(alias.get("in") or [])
                else:
                    pattern, colls = str(alias), None
                try:
                    self.rules.append((re.compile(pattern, re.I), colls, person["id"]))
                except re.error as exc:
                    raise DocumentsError(f"people.yaml alias {pattern!r}: {exc}") from exc

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


# ── the vault's mapping from people.yaml ids to refs ──────────────────────


def parse_map_args(values: list[str] | None) -> dict[str, str]:
    out: dict[str, str] = {}
    for value in values or []:
        pid, sep, ref = value.partition("=")
        pid, ref = pid.strip(), ref.strip()
        if not sep or not pid or not ref:
            raise DocumentsError(f"--map wants ID=REF, got {value!r}")
        out[pid] = ref
    return out


def validate_ref(ref: str) -> str:
    if not _REF_RE.match(ref):
        raise DocumentsError(f"not a ref: {ref!r} (want self or <type>/<slug>)")
    return ref


def load_config() -> dict:
    data = read_json(LETTERS_CONFIG_FILE, default=None)
    if not isinstance(data, dict):
        data = {}
    people_map = data.get("people_map")
    data["people_map"] = dict(people_map) if isinstance(people_map, dict) else {}
    return data


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


# ── one record ─────────────────────────────────────────────────────────────


def split_transcript(text: str) -> tuple[str, str]:
    """``(header, body)`` exactly as the letters site splits a transcript."""
    match = _TRANSCRIPT_RE.match(text)
    if not match:
        raise DocumentsError("transcript has no YAML header")
    return match.group(1), match.group(2)


def _fence(header: str) -> str:
    longest = max((len(run) for run in re.findall(r"`+", header)), default=0)
    return "`" * max(3, longest + 1)


def trailer(header: str) -> str:
    fence = _fence(header)
    return (
        f"\n{TRAILER_MARKER}\n{TRAILER_HEADING}\n\n"
        "The letters project's own header for this transcript, kept verbatim.\n\n"
        f"{fence}yaml\n{header}\n{fence}\n"
    )


def _payload_after_frontmatter(text: str) -> str:
    if not text.startswith("---\n"):
        raise DocumentsError("record has no frontmatter")
    end = text.find("\n---\n", 3)
    if end == -1:
        raise DocumentsError("record frontmatter is not closed")
    return text[end + len("\n---\n"):]


def transcript_from_record(text: str) -> bytes:
    """Rebuild the original transcript.md bytes from a filed record."""
    payload = _payload_after_frontmatter(text)
    cut = payload.rfind(f"\n{TRAILER_MARKER}\n")
    if cut == -1:
        raise DocumentsError("record has no transcript-header trailer")
    body, tail = payload[:cut], payload[cut:]
    match = re.search(r"\n(`{3,})yaml\n(.*)\n\1\n\Z", tail, re.S)
    if not match:
        raise DocumentsError("record's transcript-header trailer is malformed")
    return f"---\n{match.group(2)}\n---\n{body}".encode("utf-8")


def written_date(header: dict) -> tuple[str | None, str]:
    """``(EDTF, precision)`` from the transcript's own date fields."""
    raw = header.get("date")
    precision = str(header.get("date_precision") or "unknown")
    if raw in (None, ""):
        return None, "unknown"
    value = str(raw)
    if precision not in _EDTF or not _EDTF[precision].match(value):
        raise DocumentsError(f"date {value!r} does not have precision {precision!r}")
    return value, precision


def captured_at_for(date: str | None, precision: str) -> str:
    """When the letter was WRITTEN — never when it was filed.

    A day-precise date is midnight UTC that day. A month- or year-precise
    date stays the EDTF string it is, because a timestamp would claim a day
    nobody wrote; an undated letter is the empty string."""
    if date is None:
        return ""
    if precision == "day":
        return f"{date}T00:00:00Z"
    return date


def _title(body: str, header: dict, date: str | None) -> str:
    heading = re.search(r"^#\s+(.+?)\s*$", body, re.MULTILINE)
    if heading:
        return heading.group(1).strip()
    return f"{header.get('from') or 'Unknown'} to {header.get('to') or 'unknown'}, {date or 'undated'}"


@dataclass
class Transcript:
    path: str               # letters/<collection>/<slug>/transcript.md
    blob: str
    data: bytes
    header_text: str
    body: str
    header: dict
    collection: str
    slug: str

    @property
    def letter_id(self) -> str:
        return f"{self.collection}/{self.slug}"


def read_transcript(path: str, blob: str, data: bytes) -> Transcript:
    match = _TRANSCRIPT_PATH_RE.match(path)
    if not match:
        raise DocumentsError(f"not a transcript path: {path}")
    collection, slug = match.groups()
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise DocumentsError(f"{path}: not UTF-8 ({exc})") from exc
    header_text, body = split_transcript(text)
    try:
        header = mini_yaml.loads(header_text)
    except mini_yaml.YamlSubsetError as exc:
        raise DocumentsError(f"{path}: header unreadable ({exc})") from exc
    if not isinstance(header, dict):
        raise DocumentsError(f"{path}: header is not a mapping")
    if header.get("id") != f"{collection}/{slug}" or header.get("collection") != collection:
        raise DocumentsError(f"{path}: header id/collection do not match the path")
    return Transcript(path, blob, data, header_text, body, header, collection, slug)


def build_metadata(
    t: Transcript,
    *,
    people: People,
    people_map: dict[str, str],
    origin: dict,
    source_id: str,
    source_path: str,
    supersedes: str | None = None,
    supersedes_path: str | None = None,
) -> dict:
    header = t.header
    date, precision = written_date(header)
    author_ids = people.resolve(header.get("from"), t.collection)
    recipient_ids = people.resolve(header.get("to"), t.collection)
    author_refs = _refs(author_ids, people_map)
    recipient_refs = _refs(recipient_ids, people_map)
    named = [
        pid for pid in (people.resolve_mention(item, t.collection) for item in header.get("people") or [])
        if pid
    ]
    subject_refs = [
        ref for ref in _refs(named, people_map)
        if ref not in author_refs and ref not in recipient_refs
    ]
    document_type = str(header.get("document_type") or "other")
    if document_type not in DOCUMENT_TYPES:
        raise DocumentsError(f"{t.path}: unknown document_type {document_type!r}")
    metadata = {
        "title": _title(t.body, header, date),
        "type": LETTER_TYPE,
        "source_id": source_id,
        "source_medium": "letter",
        "source_trust": "external_record",
        "authority": "first_person_record" if OWNER_REF in author_refs else "third_party_record",
        "document_type": document_type,
        "collection": t.collection,
        "written_date": date,
        "written_date_precision": precision,
        "written_date_evidence": str(header.get("date_evidence") or ""),
        "author_label": str(header.get("from") or ""),
        "recipient_label": str(header.get("to") or ""),
        "author_refs": author_refs,
        "recipient_refs": recipient_refs,
        "subject_refs": subject_refs,
        "origin": origin,
        "captured_at": captured_at_for(date, precision),
        "visibility": "owner_only",
        "sensitivity": "family",
        "status": "raw",
        "immutable": True,
        "schema_version": SCHEMA_VERSION,
        "source_path": source_path,
    }
    if supersedes:
        metadata["supersedes"] = supersedes
        metadata["supersedes_path"] = supersedes_path or ""
    return metadata


#: Frontmatter order for a letter record: the source contract's keys first,
#: then who/when/where in reading order. (Written here rather than added to
#: `source_integrity.FRONTMATTER_ORDER`, which would move keys such as
#: `sensitivity` in every other writer's output.)
LETTER_FRONTMATTER_ORDER = (
    "title", "type", "source_id", "source_medium", "source_trust", "authority",
    "document_type", "collection", "written_date", "written_date_precision",
    "written_date_evidence", "author_label", "author_refs", "recipient_label",
    "recipient_refs", "subject_refs", "origin", "captured_at", "visibility",
    "sensitivity", "status", "immutable", "schema_version", "supersedes",
    "supersedes_path", "source_path", "content_sha256",
)


def format_frontmatter(metadata: dict) -> str:
    """Same line format as `source_integrity.format_frontmatter` (one JSON
    value per key, which `split_frontmatter` reads back exactly)."""
    keys = [key for key in LETTER_FRONTMATTER_ORDER if key in metadata]
    keys.extend(sorted(key for key in metadata if key not in keys))
    lines = ["---", *(f"{key}: {json.dumps(metadata[key], ensure_ascii=True)}" for key in keys), "---"]
    return "\n".join(lines)


def render_record(metadata: dict, t: Transcript) -> str:
    """The record's full text, with its content hash filled in.

    The hash is `source_integrity.payload_sha256` of the body exactly as
    `split_frontmatter` returns it, so source-lint recomputes the same value."""
    payload = t.body + trailer(t.header_text)
    draft = dict(metadata, content_sha256="")
    _fm, body = split_frontmatter(f"{format_frontmatter(draft)}\n{payload}")
    final = dict(metadata, content_sha256=payload_sha256(body))
    return f"{format_frontmatter(final)}\n{payload}"


# ── validation: one definition for the writer and source-lint ─────────────


def letter_record_problems(metadata: dict, text: str | None = None) -> list[str]:
    """Why a ``type: letter`` record is malformed (empty when it is not)."""
    problems: list[str] = []
    missing = [key for key in LETTER_FIELDS if key not in metadata]
    if missing:
        problems.append("missing letter fields: " + ", ".join(missing))
    if metadata.get("source_trust", "external_record") != "external_record":
        problems.append("source_trust must be external_record")
    authority = metadata.get("authority")
    if "authority" in metadata and authority not in AUTHORITIES:
        problems.append(f"authority {authority!r} is not one of {', '.join(AUTHORITIES)}")
    if metadata.get("sensitivity", "family") != "family":
        problems.append("sensitivity must be family")
    if metadata.get("immutable") is not True:
        problems.append("immutable must be true")
    if "document_type" in metadata and metadata["document_type"] not in DOCUMENT_TYPES:
        problems.append(f"unknown document_type {metadata['document_type']!r}")
    refs_ok = True
    for key in ("author_refs", "recipient_refs", "subject_refs"):
        value = metadata.get(key, [])
        if not isinstance(value, list) or not all(isinstance(r, str) and _REF_RE.match(r) for r in value):
            problems.append(f"{key} must be a list of refs")
            refs_ok = False
    if refs_ok and authority in AUTHORITIES:
        first_person = OWNER_REF in metadata.get("author_refs", [])
        if first_person != (authority == "first_person_record"):
            problems.append("authority does not match whether the owner wrote it")
    precision = metadata.get("written_date_precision")
    date = metadata.get("written_date")
    if "written_date_precision" in metadata:
        if precision not in DATE_PRECISIONS:
            problems.append(f"unknown written_date_precision {precision!r}")
        elif precision == "unknown":
            if date is not None:
                problems.append("an undated letter has written_date null")
        elif not isinstance(date, str) or not _EDTF[precision].match(date):
            problems.append(f"written_date {date!r} does not have precision {precision}")
        elif metadata.get("captured_at") != captured_at_for(date, precision):
            problems.append("captured_at is not the written date")
    origin = metadata.get("origin")
    if "origin" in metadata:
        if not isinstance(origin, dict):
            problems.append("origin must be a mapping")
        else:
            absent = [key for key in ORIGIN_KEYS if key not in origin]
            if absent:
                problems.append("origin missing: " + ", ".join(absent))
            source_id = str(metadata.get("source_id") or "")
            if origin.get("id") and not source_id.startswith(f"{SOURCE_ID_PREFIX}{origin['id']}"):
                problems.append("source_id does not name origin.id")
            if text is not None and isinstance(origin.get("transcript_blob"), str):
                try:
                    rebuilt = transcript_from_record(text)
                except DocumentsError as exc:
                    problems.append(str(exc))
                else:
                    if git_blob_sha(rebuilt) != origin["transcript_blob"]:
                        problems.append("body no longer rebuilds the filed transcript (origin.transcript_blob)")
    return problems


# ── what the vault already holds ───────────────────────────────────────────


@dataclass
class FiledRecord:
    path: Path
    source_id: str
    letter_id: str
    commit: str
    transcript_blob: str
    supersedes: str
    metadata: dict = field(repr=False)


def filed_records() -> dict[str, list[FiledRecord]]:
    """Every letter record under sources/letters, by origin id."""
    out: dict[str, list[FiledRecord]] = {}
    if not LETTERS_DIR.exists():
        return out
    for path in sorted(LETTERS_DIR.rglob("*.md")):
        metadata, _body = split_frontmatter(path.read_text(encoding="utf-8", errors="replace"))
        if metadata.get("type") != LETTER_TYPE or not isinstance(metadata.get("origin"), dict):
            continue
        origin = metadata["origin"]
        record = FiledRecord(
            path=path,
            source_id=str(metadata.get("source_id") or ""),
            letter_id=str(origin.get("id") or ""),
            commit=str(origin.get("commit") or ""),
            transcript_blob=str(origin.get("transcript_blob") or ""),
            supersedes=str(metadata.get("supersedes") or ""),
            metadata=metadata,
        )
        out.setdefault(record.letter_id, []).append(record)
    return out


def version_ref(record: FiledRecord) -> str:
    return f"{SOURCE_ID_PREFIX}{record.letter_id}@{record.commit}"


def head_record(records: list[FiledRecord]) -> FiledRecord | None:
    """The version nothing supersedes. A healthy chain has exactly one; if a
    chain is ever broken, a superseding version outranks an original."""
    if not records:
        return None
    superseded = {r.supersedes for r in records if r.supersedes}
    heads = [r for r in records if version_ref(r) not in superseded] or records
    return sorted(heads, key=lambda r: (bool(r.supersedes), r.path.name))[-1]


def is_letter_record(path: Path) -> bool:
    """Is this vault file a filed letter record? (Frontmatter, not path.)"""
    try:
        with open(path, encoding="utf-8", errors="replace") as handle:
            head = handle.read(4096)
    except OSError:
        return False
    if not head.startswith("---\n"):
        return False
    return re.search(r'^type: "?letter"?\s*$', head.split("\n---\n", 1)[0], re.MULTILINE) is not None


# ── the filing ─────────────────────────────────────────────────────────────


@dataclass
class FilingReport:
    commit: str
    repo: str
    transcripts: int = 0
    selected: int = 0
    new: list[str] = field(default_factory=list)
    superseding: list[str] = field(default_factory=list)
    unchanged: int = 0
    refs_drifted: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    authority: dict[str, int] = field(default_factory=dict)
    unmapped_people: dict[str, int] = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {
            "commit": self.commit, "repo": self.repo,
            "transcripts": self.transcripts, "selected": self.selected,
            "written": len(self.new) + len(self.superseding),
            "new": len(self.new), "superseding": len(self.superseding),
            "unchanged": self.unchanged, "refs_drifted": len(self.refs_drifted),
            "errors": self.errors, "authority": self.authority,
        }


def _slug_path(collection: str, slug: str, commit: str | None = None) -> Path:
    name = f"{slug}.md" if commit is None else f"{slug}--{commit[:12]}.md"
    return LETTERS_DIR / collection / name


def file_letters(
    repo: Path,
    commit: str,
    *,
    ids: list[str] | None = None,
    people_map: dict[str, str] | None = None,
    scan_url_template: str | None = None,
    origin_repo: str | None = None,
    dry_run: bool = False,
) -> FilingReport:
    repo = Path(repo).expanduser()
    if not (repo / ".git").exists() and not repo.joinpath("HEAD").exists():
        raise DocumentsError(f"{repo} is not a git repository")
    full = resolve_commit(repo, commit)
    people_map = {pid: validate_ref(ref) for pid, ref in (people_map or {}).items()}
    report = FilingReport(commit=full, repo=origin_repo or repo_name(repo))

    listing = _git(repo, "ls-tree", "-r", "-z", "--name-only", full, "--", "letters/")
    paths = sorted(p for p in listing.decode("utf-8").split("\0") if _TRANSCRIPT_PATH_RE.match(p))
    report.transcripts = len(paths)
    if ids is not None:
        wanted = {i.strip().strip("/") for i in ids}
        paths = [p for p in paths if "/".join(p.split("/")[1:3]) in wanted]
        missing = wanted - {"/".join(p.split("/")[1:3]) for p in paths}
        for letter_id in sorted(missing):
            report.errors.append(f"{letter_id}: no transcript at {full[:12]}")
    report.selected = len(paths)

    people_spec = f"{full}:letters/people.yaml"
    objects = _batch_objects(repo, [people_spec, *(f"{full}:{p}" for p in paths)])
    if objects.get(people_spec) is None:
        raise DocumentsError(f"letters/people.yaml is missing at {full[:12]}")
    try:
        people = People(mini_yaml.loads(objects[people_spec][1].decode("utf-8")))
    except mini_yaml.YamlSubsetError as exc:
        raise DocumentsError(f"people.yaml unreadable: {exc}") from exc

    transcripts: list[Transcript] = []
    for p in paths:
        oid, data = objects[f"{full}:{p}"]  # type: ignore[misc]
        try:
            transcripts.append(read_transcript(p, oid, data))
        except DocumentsError as exc:
            report.errors.append(str(exc))

    scan_specs: list[str] = []
    for t in transcripts:
        source_file = str(t.header.get("source_file") or "")
        if source_file:
            scan_specs += [f"{full}:source/{source_file}", f"{full}:{source_file}"]
    scan_oids = _batch_oids(repo, scan_specs)

    existing = filed_records()
    written: list[Path] = []
    for t in transcripts:
        source_file = str(t.header.get("source_file") or "")
        scan_blob = (
            scan_oids.get(f"{full}:source/{source_file}") or scan_oids.get(f"{full}:{source_file}")
            if source_file else None
        )
        source_pages = t.header.get("source_pages")
        origin = {
            "repo": report.repo,
            "id": t.letter_id,
            "commit": full,
            "source_file": source_file or None,
            "source_pages": source_pages if isinstance(source_pages, list) else None,
            "scan_blob": scan_blob,
            "scan_url": scan_url_template.format(id=t.letter_id, collection=t.collection, slug=t.slug)
            if scan_url_template else None,
            "transcript_blob": t.blob,
        }
        head = head_record(existing.get(t.letter_id, []))
        if head is not None and head.transcript_blob == t.blob:
            report.unchanged += 1
            current = build_metadata(
                t, people=people, people_map=people_map, origin=dict(head.metadata["origin"]),
                source_id=head.source_id, source_path=rel(head.path),
            )
            if any(head.metadata.get(k) != current[k] for k in ("author_refs", "recipient_refs", "subject_refs")):
                report.refs_drifted.append(t.letter_id)
            continue
        if head is None:
            path = _slug_path(t.collection, t.slug)
            source_id = f"{SOURCE_ID_PREFIX}{t.letter_id}"
            supersedes = supersedes_path = None
        else:
            path = _slug_path(t.collection, t.slug, full)
            source_id = f"{SOURCE_ID_PREFIX}{t.letter_id}@{full[:12]}"
            supersedes, supersedes_path = version_ref(head), rel(head.path)
        if path.exists():
            report.errors.append(f"{t.letter_id}: {rel(path)} exists but is not this transcript; refusing to overwrite")
            continue
        try:
            metadata = build_metadata(
                t, people=people, people_map=people_map, origin=origin,
                source_id=source_id, source_path=rel(path),
                supersedes=supersedes, supersedes_path=supersedes_path,
            )
            text = render_record(metadata, t)
            problems = letter_record_problems(split_frontmatter(text)[0], text)
        except DocumentsError as exc:
            report.errors.append(str(exc))
            continue
        if problems:
            report.errors.append(f"{t.letter_id}: " + "; ".join(problems))
            continue
        if transcript_from_record(text) != t.data:
            report.errors.append(f"{t.letter_id}: record would not rebuild the transcript byte for byte")
            continue
        report.authority[metadata["authority"]] = report.authority.get(metadata["authority"], 0) + 1
        for pid in people.resolve(t.header.get("from"), t.collection) + people.resolve(t.header.get("to"), t.collection):
            if pid not in people_map and not pid.startswith("other-") and pid not in UNRESOLVED_PEOPLE_IDS:
                report.unmapped_people[pid] = report.unmapped_people.get(pid, 0) + 1
        (report.superseding if head is not None else report.new).append(t.letter_id)
        if not dry_run:
            write_text(path, text)
            written.append(path)

    if written:
        sync_manifest([source_record(p) for p in written], write=True)
    return report


def save_config(people_map: dict[str, str], scan_url_template: str | None, origin_repo: str) -> None:
    config = load_config()
    config["version"] = 1
    config["people_map"] = dict(sorted({**config["people_map"], **people_map}.items()))
    if scan_url_template:
        config["scan_url_template"] = scan_url_template
    config["repo"] = origin_repo
    write_json(LETTERS_CONFIG_FILE, config)


# ── CLI ────────────────────────────────────────────────────────────────────


def print_report(report: FilingReport, *, dry_run: bool) -> None:
    verb = "would write" if dry_run else "wrote"
    print(f"letters: {report.repo} @ {report.commit[:12]}")
    print(f"  transcripts at commit: {report.transcripts}; selected: {report.selected}")
    print(f"  {verb}: {len(report.new) + len(report.superseding)} "
          f"({len(report.new)} new, {len(report.superseding)} superseding)")
    print(f"  unchanged: {report.unchanged}")
    if report.authority:
        print("  authority: " + ", ".join(f"{k} {v}" for k, v in sorted(report.authority.items())))
    if report.refs_drifted:
        print(f"  refs drifted (filed records keep their refs; immutable): {len(report.refs_drifted)}")
    if report.unmapped_people:
        top = sorted(report.unmapped_people.items(), key=lambda kv: (-kv[1], kv[0]))[:8]
        print("  writers/recipients filed as person/<people.yaml id> (no --map): "
              + ", ".join(f"{pid} ×{n}" for pid, n in top)
              + (" …" if len(report.unmapped_people) > 8 else ""))
    for error in report.errors:
        print(f"  ✗ {error}")
    if not dry_run and (report.new or report.superseding):
        print("  commit: git add sources/letters state/documents state/source_manifest.json "
              f"&& git commit -m 'File letters @ {report.commit[:12]}'")


def cmd_file(args: argparse.Namespace) -> int:
    if not args.all and not args.ids:
        print("documents file: pass --all or --ids ID [ID ...]", file=sys.stderr)
        return 2
    try:
        config = load_config()
        people_map = {**config["people_map"], **parse_map_args(args.map)}
        template = args.scan_url_template or config.get("scan_url_template") or None
        report = file_letters(
            Path(args.repo), args.commit,
            ids=None if args.all else list(args.ids),
            people_map=people_map, scan_url_template=template,
            origin_repo=args.repo_name or config.get("repo") or None,
            dry_run=args.dry_run,
        )
        if not args.dry_run and (report.new or report.superseding or args.map or args.scan_url_template):
            save_config(people_map, template, report.repo)
    except DocumentsError as exc:
        print(f"documents file: {exc}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(report.as_dict(), indent=2, sort_keys=True))
    else:
        print_report(report, dry_run=args.dry_run)
    return 1 if report.errors else 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="action", required=True)
    p = sub.add_parser("file", help="File letter transcripts into sources/letters/ as immutable records")
    p.add_argument("repo", help="Path to the letters repository (read through git; never written)")
    pick = p.add_mutually_exclusive_group()
    pick.add_argument("--all", action="store_true", help="Every transcript at the commit")
    pick.add_argument("--ids", nargs="+", metavar="ID", help="Letter ids (<collection>/<slug>)")
    p.add_argument("--commit", required=True, help="Commit of the letters repository to file from")
    p.add_argument("--map", action="append", metavar="ID=REF",
                   help="Map a people.yaml id to a vault ref (self, person/<slug>); repeatable; remembered")
    p.add_argument("--scan-url-template", default=None,
                   help="Scan URL with {id}/{collection}/{slug}; remembered")
    p.add_argument("--repo-name", default=None, help="origin.repo (default: from the origin remote)")
    p.add_argument("--dry-run", action="store_true", help="Report what would be filed; write nothing")
    p.add_argument("--json", action="store_true", help="Machine-readable counts")
    p.set_defaults(func=cmd_file)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
