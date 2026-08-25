#!/usr/bin/env python3
"""Dates as intervals with a basis — the package's chronology primitive (v195).

The timeline has never held a date. That was doctrine, and the doctrine was
**right about asking and wrong about storage** (ADR 0024, owner ruling 1):

- Dating a memory is reconstructive inference, not readout (Friedman 1993;
  Brown, Rips & Shevell 1985) — so "never open with 'what year'" survives as a
  lint (``arc_planner.BANNED_PHRASE``, ``interactions/timeline`` gates).
- But historians never pin without bounding first. *Terminus post quem* and
  *terminus ante quem* yield an interval, **and the interval is itself a
  finding, not a failure** (``system/research/chronology.md`` §1). Documentary
  editors mark an inferred date *conjectural* rather than declining to record
  it. The life-history calendar dates most of a life by inference from
  residence and role (Freedman et al. 1988; Belli 1998).

So: a date is an INTERVAL with a GRANULARITY, a CONFIDENCE, a BASIS, the
ANCHORS the arithmetic leaned on, and PROVENANCE per claim. This module is the
single authoritative definition of that object and of every rule that
manipulates it (recurring-defect doctrine) — pure, no I/O, no model, no vault.

Storage is EDTF / ISO 8601-2 level 1::

    1984      1984~     1984?     1984%     198X
    1998-06   1998-06-12          2001-21 (spring 2001)
    1984/1990           1984/..   ../1984

Contract: ``docs/pr-specs/timeline-chronology.md``.
Decision: ``docs/adr/0024-chronology-with-basis.md``.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field, replace
from datetime import date as _date
from datetime import datetime, timezone

# --------------------------------------------------------------------------
# The closed vocabularies (ADR 0024's durable data contract)
# --------------------------------------------------------------------------

#: Coarsest-last. The order IS the coarsening ladder `widen_for_elapsed` walks.
GRANULARITIES = ("day", "month", "season", "year", "range", "era")
#: Best-first. `certain` is a date the person stated; `conjectural` is the
#: documentary-editing convention for a date the system inferred and must
#: visibly mark as such.
CONFIDENCES = ("certain", "approximate", "inferred", "conjectural")
#: How the interval was arrived at. `stated` is what they said; `age` is
#: birthday arithmetic; `anchor` is a landmark they supplied; `order` is
#: relative sequence only; `public_event` is the living-in-history route;
#: `connector` is institutional evidence (timeline_corroboration).
#:
#: v204 (the Reading Room, ADR 0025) adds the three EVIDENCE bases, whose
#: warrant is none of the six above (`system/research/go-deep.md` §10):
#: `document` is a printed date read off paper — near-certain and often exact
#: to the day; `photo` is a contextual date, which is a WINDOW by construction
#: (§5.1) and an interval by default; `relative` is the person relaying
#: somebody else's memory, second-hand but — for the childhood facts a parent
#: witnessed and they did not — often better than their own dating (§6.4).
BASES = (
    "stated", "age", "anchor", "order", "public_event", "connector",
    "document", "photo", "relative",
)

#: The three evidence bases of the Reading Room, in one place so a caller can
#: ask "did this come out of an artifact?" without re-listing them.
EVIDENCE_BASES = ("document", "photo", "relative")

#: How much each basis is trusted when two claims disagree (ruling 3).
#:
#: The three v204 weights are FLAT — one number each, no era-conditional
#: term (Reading Room ruling 5). `document` outranks `stated` because a
#: printed date is not a reconstruction; `relative` sits just under `stated`
#: because proxy report is meant to be used *with* the index report and not
#: instead of it (Straughen et al. 2013, go-deep.md §6.4); `photo` sits under
#: both because a contextual date bounds rather than names. The research's
#: "relatives beat self for childhood" nuance stays a research note, NOT a
#: mechanism.
BASIS_WEIGHT = {
    "document": 7.0,
    "stated": 6.0,
    "relative": 5.5,
    "age": 5.0,
    "photo": 4.5,
    "anchor": 4.0,
    "public_event": 3.0,
    "connector": 2.0,
    "order": 1.0,
}
CONFIDENCE_WEIGHT = {
    "certain": 4.0,
    "approximate": 3.0,
    "inferred": 2.0,
    "conjectural": 1.0,
}
#: Consilience (chronology.md §4): each ADDITIONAL independent provenance
#: source corroborating one claim adds this much, capped — convergence from
#: independent origins is the historians' criterion, but it never outranks a
#: plainly stated date on its own.
CONSILIENCE_WEIGHT = 0.5
MAX_CONSILIENCE_SOURCES = 4

#: Huttenlocher, Hedges & Bradburn (1990): reported grain coarsens with
#: distance. Half a year of extra uncertainty per decade elapsed.
ELAPSED_WIDENING_YEARS_PER_DECADE = 0.5

#: EDTF sub-year season codes (ISO 8601-2 level 1) and their month spans.
SEASON_CODES = {21: "spring", 22: "summer", 23: "autumn", 24: "winter"}
SEASON_MONTHS = {21: (3, 5), 22: (6, 8), 23: (9, 11), 24: (12, 12)}
SEASON_NAMES = {
    "spring": 21, "summer": 22, "autumn": 23, "fall": 23, "winter": 24,
}

RELATIONS = ("before", "after", "during")


class ChronologyError(ValueError):
    """A date record, vocabulary value, or arithmetic input is unusable."""


# --------------------------------------------------------------------------
# The record
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class DateRecord:
    """One dated claim: an interval, how it was arrived at, and by whose word.

    ``best`` is the canonical EDTF expression; ``earliest``/``latest`` are the
    inclusive ISO bounds (``YYYY``, ``YYYY-MM``, or ``YYYY-MM-DD``), either of
    which may be ``None`` for an open-ended interval.
    """

    best: str | None = None
    earliest: str | None = None
    latest: str | None = None
    granularity: str = "year"
    confidence: str = "inferred"
    basis: str = "anchor"
    anchors: tuple[str, ...] = ()
    provenance: tuple[dict, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if self.granularity not in GRANULARITIES:
            raise ChronologyError(f"unknown granularity: {self.granularity!r}")
        if self.confidence not in CONFIDENCES:
            raise ChronologyError(f"unknown confidence: {self.confidence!r}")
        if self.basis not in BASES:
            raise ChronologyError(f"unknown basis: {self.basis!r}")
        if self.best is None and self.earliest is None and self.latest is None:
            raise ChronologyError("a date record needs at least one bound")
        object.__setattr__(self, "anchors", tuple(str(a) for a in self.anchors if str(a).strip()))
        object.__setattr__(
            self, "provenance", tuple(dict(p) for p in self.provenance if isinstance(p, dict))
        )

    # -- serialization ----------------------------------------------------

    def to_dict(self) -> dict:
        return {
            "best": self.best,
            "earliest": self.earliest,
            "latest": self.latest,
            "granularity": self.granularity,
            "confidence": self.confidence,
            "basis": self.basis,
            "anchors": list(self.anchors),
            "provenance": [dict(p) for p in self.provenance],
        }

    @property
    def edtf(self) -> str | None:
        return to_edtf(self)


def from_dict(value: object) -> DateRecord | None:
    """A stored record back into a :class:`DateRecord`; ``None`` when unusable.

    Never raises: a projection or a hand-edited vault file with a bad shape
    degrades to "no date", exactly as every other read path in the package
    degrades rather than erroring (the ``held_question_id`` precedent).
    """
    if isinstance(value, DateRecord):
        return value
    if isinstance(value, str):
        return parse_edtf(value)
    if not isinstance(value, dict):
        # A record produced by ANOTHER copy of this module — a vendored
        # platform runtime, or a test that loaded a private module object —
        # is still a date record. Duck-type it through its own serializer
        # rather than failing an identity check nobody meant to make.
        to_dict = getattr(value, "to_dict", None)
        if callable(to_dict) and hasattr(value, "granularity"):
            try:
                return from_dict(to_dict())
            except (TypeError, ValueError):
                return None
        return None
    try:
        return DateRecord(
            best=_opt_str(value.get("best")),
            earliest=_opt_str(value.get("earliest")),
            latest=_opt_str(value.get("latest")),
            granularity=str(value.get("granularity") or "year"),
            confidence=str(value.get("confidence") or "inferred"),
            basis=str(value.get("basis") or "anchor"),
            anchors=tuple(str(a) for a in (value.get("anchors") or ())),
            provenance=tuple(p for p in (value.get("provenance") or ()) if isinstance(p, dict)),
        )
    except (ChronologyError, TypeError, ValueError):
        return None


def _opt_str(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    return value.strip() or None


def normalized_date(value: object) -> dict | None:
    """One date, with its bounds filled in — the ONE normalization definition.

    A model (or a CLI flag, or a roster refresh) supplies ``best`` and rarely
    the bounds; a record with no ``earliest``/``latest`` renders as an empty
    string and dates nothing (:func:`display_date`, :func:`year_of`). So every
    stored date is re-derived through :func:`parse_edtf`, which fills the
    bounds from the EDTF expression, and the caller's own granularity /
    confidence / basis are kept where they were given.

    Promoted to this module in v217 (person dates). It was
    ``landmarks_interaction._normalized_date``, and the person-roster store
    needs the identical treatment for `born`/`died` — a second copy living in
    `entity_roster` is exactly the duplicate definition the recurring-defect
    doctrine forbids. `landmarks_interaction._normalized_date` is now an alias
    of this function; there is no second body.
    """
    parsed = from_dict(value)
    if parsed is None:
        return None
    if parsed.earliest or parsed.latest:
        return parsed.to_dict()
    rebuilt = parse_edtf(parsed.best, basis=parsed.basis)
    if rebuilt is None:
        return parsed.to_dict()
    supplied = value if isinstance(value, dict) else {}
    return DateRecord(
        best=rebuilt.best,
        earliest=rebuilt.earliest,
        latest=rebuilt.latest,
        granularity=supplied.get("granularity") or rebuilt.granularity,
        confidence=supplied.get("confidence") or rebuilt.confidence,
        basis=parsed.basis,
        anchors=parsed.anchors,
        provenance=parsed.provenance,
    ).to_dict()


# --------------------------------------------------------------------------
# EDTF parsing and rendering
# --------------------------------------------------------------------------

_QUALIFIERS = "~?%"
_YEAR_RE = re.compile(r"^(-?\d{4})$")
_DECADE_RE = re.compile(r"^(\d{3})X$", re.IGNORECASE)
_CENTURY_RE = re.compile(r"^(\d{2})XX$", re.IGNORECASE)
_MONTH_RE = re.compile(r"^(\d{4})-(\d{2})$")
_DAY_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")
_HUMAN_RANGE_RE = re.compile(r"^(\d{4})\s*[-–—]\s*(\d{4})$")
_HUMAN_DECADE_RE = re.compile(r"^(?:the\s+)?(\d{4})s$", re.IGNORECASE)
_HUMAN_SEASON_RE = re.compile(
    r"^(spring|summer|autumn|fall|winter)\s+(?:of\s+)?(\d{4})$", re.IGNORECASE
)
_HUMAN_SEASON_TRAILING_RE = re.compile(
    r"^(\d{4})\s+(spring|summer|autumn|fall|winter)$", re.IGNORECASE
)
_APPROX_PREFIX_RE = re.compile(r"^(?:about|around|circa|c\.|ca\.|approximately|approx\.?)\s+", re.IGNORECASE)
_BEFORE_PREFIX_RE = re.compile(r"^(?:before|prior to|earlier than|up to)\s+", re.IGNORECASE)
_AFTER_PREFIX_RE = re.compile(r"^(?:after|later than|since|from)\s+", re.IGNORECASE)


def parse_edtf(text: object, *, basis: str = "stated") -> DateRecord | None:
    """Parse an EDTF expression (or a human form) into a :class:`DateRecord`.

    Every canonical form in the contract's table round-trips through
    :func:`to_edtf`. Human forms a person or an older vault produces —
    ``2001–2021``, ``spring 1998``, ``1970s``, ``about 1984``, ``before
    1984`` — normalize onto the canonical form. Anything unparseable is
    ``None``; this function never raises.
    """
    if isinstance(text, DateRecord):
        return text
    if not isinstance(text, str):
        return None
    raw = " ".join(text.strip().split())
    if not raw:
        return None
    if basis not in BASES:
        basis = "stated"

    confidence_override: str | None = None
    match = _APPROX_PREFIX_RE.match(raw)
    if match:
        raw = raw[match.end():].strip()
        confidence_override = "approximate"
    match = _BEFORE_PREFIX_RE.match(raw)
    if match:
        inner = parse_edtf(raw[match.end():], basis=basis)
        return _open_interval(inner, "before", basis) if inner else None
    match = _AFTER_PREFIX_RE.match(raw)
    if match:
        inner = parse_edtf(raw[match.end():], basis=basis)
        return _open_interval(inner, "after", basis) if inner else None

    # --- intervals -------------------------------------------------------
    if "/" in raw:
        left, _, right = raw.partition("/")
        return _interval(left.strip(), right.strip(), basis)
    match = _HUMAN_RANGE_RE.match(raw)
    if match:
        return _interval(match.group(1), match.group(2), basis)

    # --- human seasons and decades --------------------------------------
    match = _HUMAN_SEASON_RE.match(raw) or _HUMAN_SEASON_TRAILING_RE.match(raw)
    if match:
        groups = match.groups()
        name, year = (groups[0], groups[1]) if groups[0].isalpha() else (groups[1], groups[0])
        raw = f"{int(year):04d}-{SEASON_NAMES[name.lower()]}"
    else:
        match = _HUMAN_DECADE_RE.match(raw)
        if match:
            raw = f"{match.group(1)[:3]}X"

    # --- qualifiers ------------------------------------------------------
    qualifier = ""
    while raw and raw[-1] in _QUALIFIERS:
        qualifier = raw[-1] + qualifier
        raw = raw[:-1]
    confidence = _confidence_for_qualifier(qualifier)

    record = _parse_plain(raw, basis=basis, confidence=confidence, qualifier=qualifier)
    if record is None:
        return None
    if confidence_override and not qualifier:
        record = replace(record, confidence=confidence_override, best=f"{record.best}~")
    return record


def _confidence_for_qualifier(qualifier: str) -> str:
    if "%" in qualifier:
        return "conjectural"
    if "?" in qualifier:
        return "conjectural"
    if "~" in qualifier:
        return "approximate"
    return "certain"


def _parse_plain(raw: str, *, basis: str, confidence: str,
                 qualifier: str = "") -> DateRecord | None:
    # The qualifier is carried through VERBATIM so `1984%` round-trips as
    # `1984%` and not as the `1984?` its confidence would imply.
    suffix = qualifier
    match = _DAY_RE.match(raw)
    if match:
        year, month, day = (int(g) for g in match.groups())
        if not (1 <= month <= 12 and 1 <= day <= 31):
            return None
        return DateRecord(best=f"{raw}{suffix}", earliest=raw, latest=raw,
                          granularity="day", confidence=confidence, basis=basis)
    match = _MONTH_RE.match(raw)
    if match:
        year, month = int(match.group(1)), int(match.group(2))
        if month in SEASON_CODES:
            first, last = SEASON_MONTHS[month]
            return DateRecord(best=f"{raw}{suffix}", earliest=f"{year:04d}-{first:02d}",
                              latest=f"{year:04d}-{last:02d}", granularity="season",
                              confidence=confidence, basis=basis)
        if not 1 <= month <= 12:
            return None
        return DateRecord(best=f"{raw}{suffix}", earliest=raw, latest=raw,
                          granularity="month", confidence=confidence, basis=basis)
    match = _DECADE_RE.match(raw)
    if match:
        stem = match.group(1)
        return DateRecord(best=f"{stem}X{suffix}", earliest=f"{stem}0", latest=f"{stem}9",
                          granularity="era",
                          confidence="approximate" if confidence == "certain" else confidence,
                          basis=basis)
    match = _CENTURY_RE.match(raw)
    if match:
        stem = match.group(1)
        return DateRecord(best=f"{stem}XX{suffix}", earliest=f"{stem}00", latest=f"{stem}99",
                          granularity="era",
                          confidence="approximate" if confidence == "certain" else confidence,
                          basis=basis)
    match = _YEAR_RE.match(raw)
    if match:
        return DateRecord(best=f"{raw}{suffix}", earliest=raw, latest=raw,
                          granularity="year", confidence=confidence, basis=basis)
    return None


def _interval(left: str, right: str, basis: str) -> DateRecord | None:
    open_left = left in ("", "..")
    open_right = right in ("", "..")
    if open_left and open_right:
        return None
    lo = None if open_left else _parse_plain(left.rstrip(_QUALIFIERS), basis=basis, confidence="certain")
    hi = None if open_right else _parse_plain(right.rstrip(_QUALIFIERS), basis=basis, confidence="certain")
    if (not open_left and lo is None) or (not open_right and hi is None):
        return None
    earliest = lo.earliest if lo else None
    latest = hi.latest if hi else None
    best = f"{lo.earliest if lo else '..'}/{hi.latest if hi else '..'}"
    return DateRecord(best=best, earliest=earliest, latest=latest, granularity="range",
                      confidence="inferred" if (open_left or open_right) else "certain",
                      basis=basis)


def _open_interval(inner: DateRecord, relation: str, basis: str) -> DateRecord:
    if relation == "before":
        return DateRecord(best=f"../{inner.earliest}", earliest=None, latest=inner.earliest,
                          granularity="range", confidence="inferred", basis=basis,
                          anchors=inner.anchors, provenance=inner.provenance)
    return DateRecord(best=f"{inner.latest}/..", earliest=inner.latest, latest=None,
                      granularity="range", confidence="inferred", basis=basis,
                      anchors=inner.anchors, provenance=inner.provenance)


def to_edtf(record: object) -> str | None:
    """The canonical EDTF expression for a record; inverse of :func:`parse_edtf`."""
    record = record if isinstance(record, DateRecord) else from_dict(record)
    if record is None:
        return None
    if record.best:
        return record.best
    if record.earliest and record.latest:
        return record.earliest if record.earliest == record.latest else f"{record.earliest}/{record.latest}"
    if record.earliest:
        return f"{record.earliest}/.."
    if record.latest:
        return f"../{record.latest}"
    return None


# --------------------------------------------------------------------------
# Display
# --------------------------------------------------------------------------

#: The twelve month names, in order. PUBLIC from v218: this module is the one
#: home for the package's time tables, and the general listener's prescreen
#: builds its month pattern from these very words rather than typing a tenth
#: copy of them (recurring-defect doctrine, docs/BUILDING.md §7). The private
#: name stays as the alias :func:`display_date` already uses; there is no
#: second tuple.
MONTH_NAMES = ("January", "February", "March", "April", "May", "June", "July",
               "August", "September", "October", "November", "December")
_MONTH_NAMES = MONTH_NAMES

#: The ONE four-digit-year pattern, 1800-2099 — the range a human life is
#: stated in. PROMOTED in v218 from the three identical private copies that
#: had grown up around it (`landmarks_interaction._ECHO_YEAR_RE`,
#: `timeline._CHAPTER_YEAR_RE`, `timeline_interaction._YEAR_RE`), each of
#: which now reads this object. A year the timeline can hold and a year the
#: recorder can hear must never be two different sentences.
YEAR_RE = re.compile(r"\b(1[89]\d{2}|20\d{2})\b")


def display_date(record: object, *, with_basis: bool = True) -> str:
    """Render a record the way the person would recognise it.

    ``"around 1984 — you said you were about 5"``, ``"spring 1998"``,
    ``"sometime in the 1980s"``, ``"1984–1990"``, ``"after the move to Mesa"``.
    The basis clause is appended only when the record carries a provenance
    ``claim`` (there is nothing to quote back otherwise).
    """
    record = record if isinstance(record, DateRecord) else from_dict(record)
    if record is None:
        return ""
    body = _display_interval(record)
    if not with_basis:
        return body
    claim, claim_basis = "", ""
    for item in record.provenance:
        value = str(item.get("claim") or "").strip()
        if value:
            claim, claim_basis = value, str(item.get("basis") or "")
            break
    if not claim:
        return body
    if claim_basis == "age":
        return f"{body} — you said you were {claim}"
    # v204 (the Reading Room): the three evidence bases each name their own
    # warrant, and `photo` says out loud that it is a window (go-deep.md
    # §11.21 — "the system should say so on the record it writes").
    if claim_basis == "document":
        return f"{body} — printed on {claim}"
    if claim_basis == "photo":
        return f"{body} — from the photograph: {claim} (a window, not a day)"
    if claim_basis == "relative":
        name = witness_name(record)
        return f"{body} — {name} says {claim}" if name else f"{body} — a relative says {claim}"
    return f"{body} — you said {claim}"


_POINT_BEST_RE = re.compile(r"^-?\d{2,4}(?:X{1,2}|-\d{2}(?:-\d{2})?)?[~?%]*$", re.IGNORECASE)


def _display_interval(record: DateRecord) -> str:
    earliest, latest = record.earliest, record.latest
    # `best` is the record's own single best expression — when it names a
    # POINT (a year, a month, a season, a decade), that is what the person
    # recognises, even though the bounds around it are wider. This is what
    # makes birthday + "about five" read as "around 1984" and not "1983-1986".
    if record.best and _POINT_BEST_RE.match(record.best) and earliest is not None and latest is not None:
        point = record.best.rstrip(_QUALIFIERS)
        if record.granularity == "era" or "X" in point.upper():
            return f"sometime in the {point.rstrip('Xx')}0s"
        if record.granularity == "season":
            year, _, month = point.partition("-")
            name = SEASON_CODES.get(int(month)) if month.isdigit() else None
            if name:
                return f"{name} {year}"
        rendered = _display_point(point)
        if record.confidence == "certain" and earliest == latest:
            return rendered
        return f"around {rendered}"
    if earliest is None and latest is not None:
        return f"before {_display_point(latest)}"
    if latest is None and earliest is not None:
        return f"after {_display_point(earliest)}"
    if record.granularity == "era" and earliest and latest and earliest[:3] == latest[:3]:
        return f"sometime in the {earliest[:3]}0s"
    if record.granularity == "season" and record.best:
        code = record.best.rstrip(_QUALIFIERS)
        year, _, month = code.partition("-")
        name = SEASON_CODES.get(int(month)) if month.isdigit() else None
        if name:
            return f"{name} {year}"
    if earliest and latest and earliest != latest:
        return f"{_display_point(earliest)}–{_display_point(latest)}"
    point = _display_point(earliest or latest or "")
    if record.confidence in ("approximate", "inferred", "conjectural"):
        return f"around {point}"
    return point


def _display_point(value: str) -> str:
    parts = value.split("-")
    if len(parts) == 3:
        month = int(parts[1])
        return f"{int(parts[2])} {_MONTH_NAMES[month - 1]} {parts[0]}"
    if len(parts) == 2 and parts[1].isdigit():
        month = int(parts[1])
        if month in SEASON_CODES:
            return f"{SEASON_CODES[month]} {parts[0]}"
        if 1 <= month <= 12:
            return f"{_MONTH_NAMES[month - 1]} {parts[0]}"
    return parts[0]


# --------------------------------------------------------------------------
# Bounds arithmetic
# --------------------------------------------------------------------------


def _ordinal(value: str | None, *, end: bool) -> tuple[int, int, int] | None:
    """An ISO bound as a comparable (year, month, day); ``end`` fills upward."""
    if not value:
        return None
    parts = value.split("-")
    try:
        year = int(parts[0])
    except (TypeError, ValueError):
        return None
    if len(parts) == 1:
        return (year, 12, 31) if end else (year, 1, 1)
    try:
        month = int(parts[1])
    except (TypeError, ValueError):
        return None
    if month in SEASON_CODES:
        first, last = SEASON_MONTHS[month]
        month = last if end else first
    if len(parts) == 2:
        return (year, month, _month_last_day(year, month)) if end else (year, month, 1)
    try:
        day = int(parts[2])
    except (TypeError, ValueError):
        return None
    return (year, month, day)


def _month_last_day(year: int, month: int) -> int:
    if month == 12:
        return 31
    return (_date(year, month + 1, 1) - _date(year, month, 1)).days


def year_of(record: object, *, end: bool = False) -> int | None:
    """The bounding year of a record — the timeline's ordering primitive."""
    record = record if isinstance(record, DateRecord) else from_dict(record)
    if record is None:
        return None
    bound = record.latest if end else record.earliest
    ordinal = _ordinal(bound or (record.latest if not end else record.earliest), end=end)
    return ordinal[0] if ordinal else None


def intersect(*records: object) -> DateRecord | None:
    """Terminus post quem ∧ terminus ante quem: the tightest bounds all inputs allow.

    Returns ``None`` when the inputs are DISJOINT — that is a contradiction,
    and contradictions belong to :func:`reconcile`, which never picks a winner
    silently (ruling 3). ``None`` inputs are ignored; zero usable inputs give
    ``None``.
    """
    usable = [r for r in (_as_record(x) for x in records) if r is not None]
    if not usable:
        return None
    if len(usable) == 1:
        return usable[0]
    lo_candidates = [(_ordinal(r.earliest, end=False), r.earliest) for r in usable if r.earliest]
    hi_candidates = [(_ordinal(r.latest, end=True), r.latest) for r in usable if r.latest]
    earliest = max(lo_candidates, key=lambda t: t[0])[1] if lo_candidates else None
    latest = min(hi_candidates, key=lambda t: t[0])[1] if hi_candidates else None
    lo = _ordinal(earliest, end=False)
    hi = _ordinal(latest, end=True)
    if lo and hi and lo > hi:
        return None
    bases = {r.basis for r in usable}
    basis = bases.pop() if len(bases) == 1 else "anchor"
    confidence = max((r.confidence for r in usable), key=CONFIDENCES.index)
    confidence = _at_most(confidence, "inferred")
    granularity = max((r.granularity for r in usable), key=GRANULARITIES.index)
    anchors: tuple[str, ...] = ()
    provenance: tuple[dict, ...] = ()
    for record in usable:
        anchors += tuple(a for a in record.anchors if a not in anchors)
        provenance += record.provenance
    best = earliest if (earliest and earliest == latest) else None
    if best is None:
        best = (f"{earliest or '..'}/{latest or '..'}") if (earliest or latest) else None
    return DateRecord(best=best, earliest=earliest, latest=latest, granularity=granularity,
                      confidence=confidence, basis=basis, anchors=anchors, provenance=provenance)


def _at_most(confidence: str, floor: str) -> str:
    """The weaker of two confidences (CONFIDENCES is best-first)."""
    return confidence if CONFIDENCES.index(confidence) >= CONFIDENCES.index(floor) else floor


def _as_record(value: object) -> DateRecord | None:
    if isinstance(value, DateRecord):
        return value
    if isinstance(value, str):
        return parse_edtf(value)
    return from_dict(value)


# --------------------------------------------------------------------------
# The arithmetic (owner ruling 1 — "the system does the arithmetic")
# --------------------------------------------------------------------------

#: Public: `cross_dating` builds its age-statement patterns from these very
#: words, so the two readers can never drift apart (recurring-defect doctrine).
NUMBER_WORDS = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
    "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12,
    "thirteen": 13, "fourteen": 14, "fifteen": 15, "sixteen": 16,
    "seventeen": 17, "eighteen": 18, "nineteen": 19, "twenty": 20,
    "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70,
    "eighty": 80, "ninety": 90,
}
_NUMBER_WORDS = NUMBER_WORDS
_HEDGES = ("about", "around", "roughly", "approximately", "maybe", "or so",
           "something like", "somewhere around", "ish", "give or take")
_AGE_TOKEN_RE = re.compile(r"\d{1,3}|[a-z]+", re.IGNORECASE)


def parse_age(age_text: object) -> tuple[int, int, bool] | None:
    """``"about 5"`` → ``(5, 5, True)``; ``"5 or 6"`` → ``(5, 6, False)``.

    Returns ``(min_age, max_age, hedged)`` or ``None``. Hedged means the
    person marked their own uncertainty, which widens the window by a year on
    each side (Huttenlocher's rounding: a hedged age is a rounded age).
    """
    if not isinstance(age_text, str):
        return None
    lowered = age_text.lower().strip()
    if not lowered:
        return None
    hedged = any(h in lowered for h in _HEDGES)
    ages: list[int] = []
    for token in _AGE_TOKEN_RE.findall(lowered):
        if token.isdigit():
            value = int(token)
            if 0 <= value <= 120:
                ages.append(value)
        elif token in _NUMBER_WORDS:
            ages.append(_NUMBER_WORDS[token])
    if not ages:
        return None
    return min(ages), max(ages), hedged


def from_age(birth_date: object, age_text: object, *, claim: str | None = None) -> DateRecord | None:
    """Birthday + a stated age → a dated interval (basis ``age``).

    The owner's own example: a birthday plus "about 5" gives ``1984~`` with
    the window the hedge earns. Someone who is age *a* occupies the window
    ``[birth_year + a, birth_year + a + 1]``; a hedge widens it by one year
    on each side; "5 or 6" takes the union before hedging.
    """
    birth = _as_record(birth_date)
    if birth is None:
        return None
    birth_year = year_of(birth)
    if birth_year is None:
        return None
    parsed = parse_age(age_text)
    if parsed is None:
        return None
    min_age, max_age, hedged = parsed
    low = birth_year + min_age
    high = birth_year + max_age + 1
    if hedged:
        low -= 1
        high += 1
    low = max(low, birth_year)
    mid = (low + high) // 2
    granularity = "year" if low == high else "range"
    provenance = ({"claim": str(age_text).strip(), "basis": "age"},) if age_text else ()
    if claim:
        provenance = ({"claim": claim, "basis": "age"},)
    return DateRecord(
        best=f"{mid}~",
        earliest=str(low),
        latest=str(high),
        granularity=granularity,
        confidence="approximate" if hedged else "inferred",
        basis="age",
        anchors=("birth",),
        provenance=provenance,
    )


def from_anchor(anchor_date_record: object, relation: str, grain: str = "range", *,
                key: str | None = None) -> DateRecord | None:
    """A landmark plus a relation → bounds (basis ``anchor``).

    ``before`` yields a terminus ante quem, ``after`` a terminus post quem,
    ``during`` the landmark's own span. Two bounds beat one guess and are
    directly storable (``chronology.md`` §6 rule 3).
    """
    anchor = _as_record(anchor_date_record)
    if anchor is None or relation not in RELATIONS:
        return None
    if grain not in GRANULARITIES:
        grain = "range"
    anchors = tuple(dict.fromkeys(anchor.anchors + ((key,) if key else ())))
    if relation == "before":
        if not anchor.earliest:
            return None
        return DateRecord(best=f"../{anchor.earliest}", earliest=None, latest=anchor.earliest,
                          granularity=grain, confidence="inferred", basis="anchor",
                          anchors=anchors, provenance=anchor.provenance)
    if relation == "after":
        if not anchor.latest:
            return None
        return DateRecord(best=f"{anchor.latest}/..", earliest=anchor.latest, latest=None,
                          granularity=grain, confidence="inferred", basis="anchor",
                          anchors=anchors, provenance=anchor.provenance)
    return DateRecord(best=anchor.best, earliest=anchor.earliest, latest=anchor.latest,
                      granularity=grain, confidence=_at_most(anchor.confidence, "inferred"),
                      basis="anchor", anchors=anchors, provenance=anchor.provenance)


def widen_for_elapsed(record: object, *, as_of: object = None) -> DateRecord | None:
    """Widen an inferred date for the time elapsed since it happened.

    Huttenlocher, Hedges & Bradburn (1990): people code elapsed time coarsely
    and the grain coarsens with distance. Deterministic rule — widen the
    bounds by :data:`ELAPSED_WIDENING_YEARS_PER_DECADE` per decade elapsed,
    rounded up to whole years; coarsen the granularity by one rung once the
    widening bites; drop the confidence at most one rung, never past
    ``inferred``.

    ``certain`` is NEVER widened: a stated calendar date does not decay
    because time passed. That is the boundary the doctrine keeps.
    """
    parsed = _as_record(record)
    if parsed is None:
        return None
    if parsed.confidence == "certain":
        return parsed
    reference = _as_of_year(as_of)
    anchor_year = year_of(parsed, end=True) or year_of(parsed)
    if anchor_year is None or reference is None:
        return parsed
    elapsed = max(reference - anchor_year, 0)
    widen = math.ceil(elapsed / 10.0 * ELAPSED_WIDENING_YEARS_PER_DECADE)
    if widen <= 0:
        return parsed
    low = year_of(parsed)
    high = year_of(parsed, end=True)
    earliest = str(low - widen) if low is not None and parsed.earliest else parsed.earliest
    latest = str(high + widen) if high is not None and parsed.latest else parsed.latest
    index = GRANULARITIES.index(parsed.granularity)
    granularity = GRANULARITIES[min(index + 1, GRANULARITIES.index("range"))]
    confidence = _at_most(parsed.confidence, "inferred")
    best = f"{earliest or '..'}/{latest or '..'}"
    return DateRecord(best=best, earliest=earliest, latest=latest, granularity=granularity,
                      confidence=confidence, basis=parsed.basis, anchors=parsed.anchors,
                      provenance=parsed.provenance)


def _as_of_year(value: object) -> int | None:
    if value is None:
        return datetime.now(timezone.utc).year
    if isinstance(value, int):
        return value
    if isinstance(value, datetime):
        return value.year
    if isinstance(value, _date):
        return value.year
    if isinstance(value, str):
        match = re.search(r"\d{4}", value)
        return int(match.group(0)) if match else None
    return None


# --------------------------------------------------------------------------
# Reconciliation (owner ruling 3 — both claims kept, never silently resolved)
# --------------------------------------------------------------------------


def claim_score(record: object) -> float:
    """How well-supported one dating claim is. Higher wins; never destructive."""
    parsed = _as_record(record)
    if parsed is None:
        return 0.0
    sources = {
        str(item.get("source") or item.get("session") or item.get("answer_id") or "")
        for item in parsed.provenance
    }
    sources.discard("")
    consilience = min(max(len(sources) - 1, 0), MAX_CONSILIENCE_SOURCES) * CONSILIENCE_WEIGHT
    return (
        BASIS_WEIGHT.get(parsed.basis, 0.0)
        + CONFIDENCE_WEIGHT.get(parsed.confidence, 0.0)
        + consilience
    )


def reconcile(claims: object) -> dict:
    """``{"best_supported": DateRecord|None, "alternates": [...]}`` — ruling 3.

    Historians corroborate and prefer convergence from independent origins;
    oral historians (Portelli) treat the disagreement itself as data. So this
    function **never drops a claim**: every usable input comes back either as
    ``best_supported`` or in ``alternates``, in score order, ties broken
    deterministically by EDTF text and then insertion order. Nothing is
    overwritten, and no AI-side silent pick is possible — the caller renders
    the best-supported interval and links the alternates.
    """
    parsed = [r for r in (_as_record(c) for c in (claims or ())) if r is not None]
    if not parsed:
        return {"best_supported": None, "alternates": []}
    ordered = sorted(
        enumerate(parsed),
        key=lambda pair: (-claim_score(pair[1]), to_edtf(pair[1]) or "", pair[0]),
    )
    records = [record for _, record in ordered]
    return {"best_supported": records[0], "alternates": records[1:]}


# --------------------------------------------------------------------------
# The witness (v204, the Reading Room — ADR 0025)
# --------------------------------------------------------------------------

#: A provenance entry whose `source` names the living person who told us the
#: fact. `witness:<slug>` is the WHOLE convention: there is no witness table,
#: no witness state, and no new file. `claim_score` already treats `source`
#: as the consilience identity, so two different witnesses corroborating one
#: claim count as two independent origins for free.
WITNESS_SOURCE_PREFIX = "witness:"


def witness_provenance(
    slug: object,
    *,
    name: object = None,
    said_at: object = None,
    claim: object = None,
) -> dict | None:
    """One provenance entry for something a relative relayed.

    ``witness_provenance("mom", name="Mom", said_at="2026-08-24",
    claim="we moved in '84")`` →
    ``{"source": "witness:mom", "name": "Mom", "said_at": "2026-08-24",
    "claim": "we moved in '84", "basis": "relative"}``.

    Returns ``None`` for a blank slug rather than minting ``"witness:"``.
    """
    text = str(slug or "").strip()
    # Idempotent: an already-prefixed slug must not be prefixed twice, and
    # `str.lstrip` would eat the leading letters of "sister" (every one of
    # them is in "witness:"), so removeprefix is the only correct tool here.
    text = text.removeprefix(WITNESS_SOURCE_PREFIX).strip()
    if not text:
        return None
    entry: dict = {"source": f"{WITNESS_SOURCE_PREFIX}{text}", "basis": "relative"}
    for key, value in (("name", name), ("said_at", said_at), ("claim", claim)):
        cleaned = str(value or "").strip()
        if cleaned:
            entry[key] = cleaned[:_CLAIM_TEXT_MAX_CHARS] if key == "claim" else cleaned
    return entry


def witness_slug(record: object) -> str | None:
    """The slug of the first witness in a record's provenance, or ``None``."""
    parsed = record if isinstance(record, DateRecord) else from_dict(record)
    if parsed is None:
        return None
    for item in parsed.provenance:
        source = str(item.get("source") or "")
        if source.startswith(WITNESS_SOURCE_PREFIX):
            slug = source[len(WITNESS_SOURCE_PREFIX):].strip()
            if slug:
                return slug
    return None


def witness_name(record: object) -> str | None:
    """The display name of the first witness in a record's provenance."""
    parsed = record if isinstance(record, DateRecord) else from_dict(record)
    if parsed is None:
        return None
    for item in parsed.provenance:
        if str(item.get("source") or "").startswith(WITNESS_SOURCE_PREFIX):
            name = str(item.get("name") or "").strip()
            if name:
                return name
            slug = str(item.get("source") or "")[len(WITNESS_SOURCE_PREFIX):].strip()
            if slug:
                return slug.replace("-", " ")
    return None


# --------------------------------------------------------------------------
# The classifier's date claim (Design §B)
# --------------------------------------------------------------------------

CLAIM_KEYS = ("stated", "age", "anchor_ref", "relation")
_CLAIM_TEXT_MAX_CHARS = 120


def possible_date_claim(value: object) -> dict | None:
    """Normalize the classifier's ``events[].date`` object; ``None`` when unusable.

    Structural only — this owns no calendar and does no arithmetic. A
    malformed claim degrades to ``None`` on every read path, exactly as
    ``conversation_delivery``'s additive fields degrade.
    """
    if not isinstance(value, dict):
        return None
    claim: dict = {}
    for key in ("stated", "age", "anchor_ref"):
        text = value.get(key)
        if isinstance(text, str) and text.strip():
            claim[key] = text.strip()[:_CLAIM_TEXT_MAX_CHARS]
    relation = value.get("relation")
    if isinstance(relation, str) and relation.strip().lower() in RELATIONS:
        claim["relation"] = relation.strip().lower()
    return claim or None


def record_from_claim(claim: object, *, birth_date: object = None,
                      anchors: dict | None = None) -> DateRecord | None:
    """Turn a classifier claim into a record — the arithmetic, in one place.

    ``stated`` is parsed as given; ``age`` runs :func:`from_age` against the
    birthday; ``anchor_ref`` + ``relation`` runs :func:`from_anchor` against
    the caller's anchor index. Several claims combine through
    :func:`intersect`; disjoint claims fall back to :func:`reconcile`'s
    best-supported (and the caller keeps the alternates — nothing is dropped).
    """
    normalized = possible_date_claim(claim)
    if not normalized:
        return None
    parts: list[DateRecord] = []
    stated = normalized.get("stated")
    if stated:
        record = parse_edtf(stated, basis="stated")
        if record:
            parts.append(replace(record, provenance=({"claim": stated, "basis": "stated"},)))
    age = normalized.get("age")
    if age and birth_date is not None:
        record = from_age(birth_date, age)
        if record:
            parts.append(record)
    anchor_ref = normalized.get("anchor_ref")
    relation = normalized.get("relation") or "during"
    if anchor_ref and anchors:
        anchor = lookup_anchor(anchor_ref, anchors)
        if anchor is not None:
            record = from_anchor(anchor, relation, key=anchor_key(anchor_ref, anchors))
            if record:
                parts.append(replace(
                    record,
                    provenance=record.provenance + ({"claim": f"{relation} {anchor_ref}", "basis": "anchor"},),
                ))
    if not parts:
        return None
    combined = intersect(*parts)
    if combined is not None:
        return combined
    return reconcile(parts)["best_supported"]


def anchor_key(reference: str, anchors: dict) -> str | None:
    """The anchor-index key `reference` names — by key, then by label.

    Exact, case-insensitive, never fuzzy: a free-text anchor that names
    nothing in the index resolves to ``None`` and the caller derives
    nothing from it. That is the whole guard against a wrong join.
    """
    lowered = reference.strip().lower()
    for key in anchors:
        if str(key).strip().lower() == lowered:
            return str(key)
    for key, value in anchors.items():
        label = str((value or {}).get("label", "")) if isinstance(value, dict) else ""
        if label.strip().lower() == lowered:
            return str(key)
    return None


def lookup_anchor(reference: str, anchors: dict) -> DateRecord | None:
    """The `DateRecord` behind :func:`anchor_key`, or ``None``."""
    key = anchor_key(reference, anchors)
    if key is None:
        return None
    value = anchors[key]
    if isinstance(value, dict) and "date" in value:
        return _as_record(value["date"])
    return _as_record(value)


#: Pre-v205 private names, kept so nothing that imported them breaks.
_anchor_key = anchor_key
_lookup_anchor = lookup_anchor
