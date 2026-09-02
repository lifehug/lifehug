#!/usr/bin/env python3
"""E-L3: the deterministic Go Dig import grammar (design §10.6).

Pure text parsing. No vault, no model, no writes — every function here takes
a string and returns a plain dict or tuple of dicts, so the preview and the
apply path (`go_dig_writer.py`) read the SAME parse, which is the whole point
of a grammar rather than two hand-written readings of one document shape.

Blocks are blank-line-separated ``Key: value`` groups; a leading ``#``
heading line is ignored; a line whose key this module does not recognize
falls to the block's note, verbatim, rather than being silently dropped
(design §10.4: "what the structured fields cannot express is never lost; it
is a note").

Month names are PROMOTED from :data:`chronology.MONTH_NAMES` rather than
re-typed — the same discipline `general_listener._MONTH_WORDS` already
follows for its own prescreen table (recurring-defect doctrine).
"""

from __future__ import annotations

import hashlib
import re
import sys
from pathlib import Path

_SYSTEM_DIR = Path(__file__).resolve().parent
if str(_SYSTEM_DIR) not in sys.path:
    sys.path.insert(0, str(_SYSTEM_DIR))

import chronology as chrono  # noqa: E402
import landmarks_interaction as li  # noqa: E402

# --------------------------------------------------------------------------
# Blocks
# --------------------------------------------------------------------------


def split_blocks(text: str) -> list[str]:
    """Blank-line-separated blocks, in paste order (§10.6).

    A leading ``#`` heading line inside a block is stripped before the block
    is handed to :func:`parse_block` — it is decoration, never a field.
    """
    normalized = (text or "").replace("\r\n", "\n").replace("\r", "\n")
    stripped = normalized.strip("\n")
    if not stripped.strip():
        return []
    chunks = re.split(r"\n[ \t]*\n+", stripped)
    blocks: list[str] = []
    for chunk in chunks:
        lines = chunk.split("\n")
        while lines and lines[0].strip().startswith("#"):
            lines = lines[1:]
        body = "\n".join(lines).strip("\n")
        if body.strip():
            blocks.append(body)
    return blocks


def canonical_block_bytes(block_text: str) -> bytes:
    """The block's identity bytes — every line right-trimmed, blank lines at
    the edges dropped. Two pastes of the same block that differ only in
    trailing whitespace are the same block."""
    lines = [line.rstrip() for line in (block_text or "").strip("\n").split("\n")]
    return "\n".join(lines).strip().encode("utf-8")


def content_digest(block_text: str) -> str:
    """The sha256 of a block's canonical bytes — order-independent identity.

    This is what `go_dig_writer` folds into a filed block's promotion digest
    (design §10.4/H4): re-ordering the same blocks in a re-paste changes
    their POSITION, never their content, so identity keyed on this digest
    alone is immune to the reorder row 28 requires (§12 row 28).
    """
    return hashlib.sha256(canonical_block_bytes(block_text)).hexdigest()


def block_local_id(ordinal: int, block_text: str) -> str:
    """``"{ordinal}:{content digest prefix}"`` — §10.6's own words: "the
    block's ordinal in the paste plus a digest of its canonical bytes".

    This is a REPORTING label ("block 17"), not the filing identity: the
    ordinal half moves when a paste is re-ordered, so `go_dig_writer` files
    on :func:`content_digest` alone, never on this label. See that module's
    own docstring for why both sentences of §10.6/row 28 can be true at
    once only when they are two different things.
    """
    return f"{int(ordinal)}:{content_digest(block_text)[:16]}"


# --------------------------------------------------------------------------
# Line-level splitting
# --------------------------------------------------------------------------

RECOGNIZED_KEYS = {
    "dates": "dates",
    "city/state": "place",
    "city/country": "place",
    "kanton/country": "place",
    "country": "place",
    "nickname": "nickname",
    "address": "address",
    "link": "link",
    "school": "school",
    "work": "work",
    "events": "events",
}

#: Which raw keys count as "place" and their coarse-to-fine priority — the
#: LAST finer key present wins over a bare ``Country`` (§10.6: "a block may
#: carry both; the finer wins").
_PLACE_KEYS_FINE_FIRST = ("city/state", "city/country", "kanton/country")


def _parse_lines(block_text: str) -> list[tuple[str, str]]:
    """``[(key, value), ...]``. A colon-less line is ``("", raw line)`` so it
    can fall to the note verbatim; a ``#`` heading line is dropped."""
    rows: list[tuple[str, str]] = []
    for line in block_text.split("\n"):
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("#"):
            continue
        if ":" in line:
            key, _, value = line.partition(":")
            rows.append((key.strip(), value.strip()))
        else:
            rows.append(("", stripped))
    return rows


# --------------------------------------------------------------------------
# Dates
# --------------------------------------------------------------------------

_MONTH_LOOKUP: dict[str, int] = {}
for _index, _name in enumerate(chrono.MONTH_NAMES, start=1):
    _MONTH_LOOKUP[_name.lower()] = _index
    _MONTH_LOOKUP[_name[:3].lower()] = _index
del _index, _name

_BRACKET_RE = re.compile(r"^\[(.*)\]$")
_MONTH_DAY_YEAR_RE = re.compile(r"^([A-Za-z]+)\.?\s+(\d{1,2}),\s*(\d{4})$")
_MONTH_YEAR_RE = re.compile(r"^([A-Za-z]+)\.?\s+(\d{4})$")
_YEAR_ONLY_RE = re.compile(r"^(\d{4})$")
_ONGOING_WORDS = ("now", "present")
_DATES_SPLIT_RE = re.compile(r"\s+[-–—]\s+")
_TRAILING_PAREN_RE = re.compile(r"^(.*?)\s*\(([^()]*)\)\s*$")


def month_text_to_edtf(text: str) -> tuple[str | None, str | None]:
    """``(edtf, grain)`` for ``Month D, YYYY`` / ``Month YYYY`` / ``Mon
    YYYY`` / ``YYYY``, or ``(None, None)`` when the text is none of those."""
    stripped = text.strip()
    match = _MONTH_DAY_YEAR_RE.match(stripped)
    if match:
        month = _MONTH_LOOKUP.get(match.group(1).lower())
        if month:
            return f"{int(match.group(3)):04d}-{month:02d}-{int(match.group(2)):02d}", "day"
    match = _MONTH_YEAR_RE.match(stripped)
    if match:
        month = _MONTH_LOOKUP.get(match.group(1).lower())
        if month:
            return f"{int(match.group(2)):04d}-{month:02d}", "month"
    match = _YEAR_ONLY_RE.match(stripped)
    if match:
        return stripped, "year"
    return None, None


def parse_date_bound(token: str) -> dict:
    """One side of a ``Dates`` field.

    ``{"edtf", "grain", "approximate", "ongoing", "unparseable"}``. ``[…]``
    brackets set ``approximate`` on THAT bound only (§10.6); ``now``/
    ``present`` set ``ongoing`` and carry no ``edtf``.
    """
    text = token.strip()
    approximate = False
    match = _BRACKET_RE.match(text)
    if match:
        approximate = True
        text = match.group(1).strip()
    if text.lower() in _ONGOING_WORDS:
        return {"edtf": None, "grain": None, "approximate": approximate,
                "ongoing": True, "unparseable": False}
    edtf, grain = month_text_to_edtf(text)
    return {"edtf": edtf, "grain": grain, "approximate": approximate,
            "ongoing": False, "unparseable": edtf is None}


def parse_dates_value(value: str) -> dict:
    """``Dates: START - END`` -> ``{"start", "end", "note", "unparseable"}``.

    A trailing parenthetical after END falls to the note rather than being
    read as a lease-length assumption (§10.6). The split is on a
    whitespace-padded hyphen or en/em dash; none of the three stated date
    forms ever contain one.
    """
    text = value.strip()
    parts = _DATES_SPLIT_RE.split(text, maxsplit=1)
    if len(parts) != 2:
        return {"start": None, "end": None, "note": None, "unparseable": True}
    start_raw, end_raw = parts
    trailing_note = None
    paren = _TRAILING_PAREN_RE.match(end_raw)
    if paren:
        candidate_end, note_text = paren.groups()
        if candidate_end.strip():
            end_raw = candidate_end.strip()
            trailing_note = note_text.strip() or None
    start = parse_date_bound(start_raw)
    end = parse_date_bound(end_raw)
    unparseable = start["unparseable"] or (end["unparseable"] and not end["ongoing"])
    return {"start": start, "end": end, "note": trailing_note, "unparseable": unparseable}


# --------------------------------------------------------------------------
# Place
# --------------------------------------------------------------------------


def parse_place_value(value: str) -> dict:
    """``"X, Y"`` -> ``{"place": X, "region": Y or None}`` — the last comma
    splits place from region (§10.6)."""
    text = value.strip()
    if "," in text:
        place, _, region = text.rpartition(",")
        return {"place": place.strip(), "region": region.strip() or None}
    return {"place": text, "region": None}


# --------------------------------------------------------------------------
# School
# --------------------------------------------------------------------------

_ORDINAL_GRADE = r"\d{1,2}(?:st|nd|rd|th)"
_GRADE_PHRASE = (
    rf"(?:PK|K|{_ORDINAL_GRADE}(?:\s+and\s+{_ORDINAL_GRADE})?\s+grade"
    rf"(?:\s+then\s+.+)?)"
)
_TRAILING_GRADE_RE = re.compile(rf",?\s*({_GRADE_PHRASE})\s*$", re.IGNORECASE)
_PARENTHESIZED_NAME_RE = re.compile(r"^\(([^()]+)\)\s*(.*)$")


def parse_school_value(value: str) -> dict:
    """``School:`` -> ``{"status": "none"|"done"|"named", ...}`` (§10.6).

    A parenthesized name ("the person was unsure of it") keeps the name and
    sends the raw line to the note. A trailing grade phrase splits even
    without a comma.
    """
    text = value.strip()
    lowered = text.lower()
    if not text or lowered == "none":
        return {"status": "none", "name": None, "grades": None, "note": None}
    if lowered == "done":
        return {"status": "done", "name": None, "grades": None, "note": None}
    paren = _PARENTHESIZED_NAME_RE.match(text)
    if paren:
        name = paren.group(1).strip()
        return {"status": "named", "name": name or text, "grades": None,
                "note": f"School: {text}"}
    grade_match = _TRAILING_GRADE_RE.search(text)
    if grade_match:
        name = text[:grade_match.start()].rstrip(", ").strip()
        grades = grade_match.group(1).strip()
        return {"status": "named", "name": name or text, "grades": grades, "note": None}
    if "," in text:
        name, _, grades = text.rpartition(",")
        return {"status": "named", "name": name.strip(), "grades": grades.strip() or None,
                "note": None}
    return {"status": "named", "name": text, "grades": None, "note": None}


# --------------------------------------------------------------------------
# Work
# --------------------------------------------------------------------------


def _split_top_level(text: str, sep: str = ",") -> list[str]:
    """Split on ``sep`` OUTSIDE parentheses — an inline ``(start Jun 1990,
    end Jun 1991)`` never gets cut in half."""
    parts: list[str] = []
    depth = 0
    current: list[str] = []
    for char in text:
        if char == "(":
            depth += 1
        elif char == ")":
            depth = max(0, depth - 1)
        if char == sep and depth == 0:
            parts.append("".join(current))
            current = []
        else:
            current.append(char)
    parts.append("".join(current))
    return [part.strip() for part in parts if part.strip()]


_START_PAREN_RE = re.compile(r"\(\s*start\s+(.+?)\s*\)", re.IGNORECASE)
_END_PAREN_RE = re.compile(r"\(\s*end\s+(.+?)\s*\)", re.IGNORECASE)
_ANY_PAREN_RE = re.compile(r"\(([^()]+)\)")
_DASH_ORG_RE = re.compile(r"\s+-\s+(.+)$")
_IN_PLACE_RE = re.compile(r"\bin\s+([A-Z][A-Za-z .]+)$")


def parse_work_item(raw: str) -> dict:
    """One comma-separated ``Work`` item -> ``{"what", "org", "where",
    "start", "end"}`` (§10.6). ``org`` = the parenthesized or dashed
    organization when present, else ``what`` itself.

    A tenure's identity for the import's own consecutive-mention grouping
    (:func:`group_tenures`) is ``(what, where)`` together, not ``what``
    alone: "Boeing" and "Boeing in Seattle" both reduce to ``what="Boeing"``
    once the ``in place`` clause is read off as ``where``, and it is exactly
    that NEW ``where`` — Seattle, absent from the first mention — that makes
    the wording change row 32 calls "a second tenure at one organization"
    even though ``org`` resolves to the same roster entity both times.
    """
    text = raw.strip()
    start = None
    match = _START_PAREN_RE.search(text)
    if match:
        start = parse_date_bound(match.group(1))
        text = (text[:match.start()] + text[match.end():]).strip()
    end = None
    match = _END_PAREN_RE.search(text)
    if match:
        end = parse_date_bound(match.group(1))
        text = (text[:match.start()] + text[match.end():]).strip()
    org = None
    match = _ANY_PAREN_RE.search(text)
    if match:
        org = match.group(1).strip()
        text = (text[:match.start()] + text[match.end():]).strip()
    else:
        match = _DASH_ORG_RE.search(text)
        if match:
            org = match.group(1).strip()
            text = text[:match.start()].strip()
    where = None
    match = _IN_PLACE_RE.search(text)
    if match:
        where = match.group(1).strip()
        text = text[:match.start()].strip()
    what = text.strip(" -,")
    if not org:
        org = what
    return {"what": what, "org": org, "where": where, "start": start, "end": end}


def parse_work_value(value: str) -> dict:
    """``Work:`` -> ``{"status": "none"|"listed", "items": (...)}`` (§10.6,
    owner Q6: ``None``/blank files nothing)."""
    text = value.strip()
    if not text or text.lower() == "none":
        return {"status": "none", "items": ()}
    items = tuple(parse_work_item(part) for part in _split_top_level(text))
    return {"status": "listed", "items": items}


# --------------------------------------------------------------------------
# One block
# --------------------------------------------------------------------------


def _choose_place_row(rows: list[tuple[str, str]]) -> tuple[str, str]:
    """The finer place key wins over a bare ``Country`` (§10.6)."""
    finer = [row for row in rows if row[0] != "country"]
    return finer[-1] if finer else rows[-1]


def parse_block(raw_block: str, *, ordinal: int) -> dict:
    """One block, fully parsed (§10.6). Never raises: a line the grammar
    cannot place falls to ``note_lines`` and the block is reported
    ``needs_a_hand`` only for a genuinely malformed ``Dates`` field."""
    fields: dict[str, list[tuple[str, str]]] = {}
    note_lines: list[str] = []
    for key, value in _parse_lines(raw_block):
        norm_key = key.strip().lower()
        kind = RECOGNIZED_KEYS.get(norm_key)
        if kind is None:
            note_lines.append(f"{key}: {value}" if key else value)
            continue
        fields.setdefault(kind, []).append((norm_key, value))

    errors: list[str] = []

    dates = None
    if "dates" in fields:
        parsed_dates = parse_dates_value(fields["dates"][-1][1])
        if parsed_dates["unparseable"]:
            errors.append("dates_unparseable")
        else:
            dates = parsed_dates
            if parsed_dates["note"]:
                note_lines.append(parsed_dates["note"])

    place_name = None
    region_name = None
    if "place" in fields:
        norm_key, raw_place = _choose_place_row(fields["place"])
        parsed_place = parse_place_value(raw_place)
        place_name = parsed_place["place"] or None
        region_name = parsed_place["region"] if norm_key != "country" else None

    nickname = None
    if "nickname" in fields:
        clean, nickname_note = li.strip_nickname_parenthetical(fields["nickname"][-1][1])
        nickname = clean or None
        if nickname_note:
            note_lines.append(nickname_note)

    address = fields["address"][-1][1].strip() or None if "address" in fields else None

    link = None
    if "link" in fields:
        candidate = fields["link"][-1][1].strip()
        if candidate.lower().startswith("https:"):
            link = candidate

    school = None
    if "school" in fields:
        school = parse_school_value(fields["school"][-1][1])
        if school.get("note"):
            note_lines.append(school["note"])

    work_items: tuple = ()
    if "work" in fields:
        work_items = parse_work_value(fields["work"][-1][1])["items"]

    events_text = fields["events"][-1][1].strip() or None if "events" in fields else None

    return {
        "ordinal": int(ordinal),
        "raw": raw_block,
        "content_digest": content_digest(raw_block),
        "block_local_id": block_local_id(ordinal, raw_block),
        "dates": dates,
        "place_name": place_name,
        "region_name": region_name,
        "nickname": nickname,
        "address": address,
        "link": link,
        "school": school,
        "work_items": work_items,
        "events_text": events_text,
        "note_lines": tuple(note_lines),
        "errors": tuple(errors),
        "status": "needs_a_hand" if errors else "ready",
    }


def parse_paste(text: str) -> list[dict]:
    """Every block of a pasted document, parsed in paste order (§10.6)."""
    return [parse_block(block, ordinal=i)
            for i, block in enumerate(split_blocks(text), start=1)]
