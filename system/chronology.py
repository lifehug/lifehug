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

import json
import math
import re
from dataclasses import dataclass, field, replace
from datetime import date as _date
from datetime import datetime, timedelta as _timedelta, timezone

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
#: v204 (ADR 0025, retired 2026-09-03) adds the three EVIDENCE bases, whose
#: warrant is none of the six above:
#: `document` is a printed date read off paper — near-certain and often exact
#: to the day; `photo` is a contextual date, which is a WINDOW by construction
#: (§5.1) and an interval by default; `relative` is the person relaying
#: somebody else's memory, second-hand but — for the childhood facts a parent
#: witnessed and they did not — often better than their own dating (§6.4).
BASES = (
    "stated", "age", "anchor", "order", "public_event", "connector",
    "document", "photo", "relative",
)

#: The three evidence bases, in one place so a caller can
#: ask "did this come out of an artifact?" without re-listing them.
EVIDENCE_BASES = ("document", "photo", "relative")

#: The provenance-entry basis for a clause that explains HOW a value was worked
#: out instead of quoting something the person said (lifehug#266). It is not a
#: member of :data:`BASES` — a record's basis says what KIND of evidence dated
#: it, while this says what a *sentence* is, and the two vocabularies were
#: conflated for exactly one release: an age frame drawn on a calculated birth
#: origin carried the stated-birthday clause and :func:`display_date` rendered
#: it as *"— you said from your birthday"* on a vault with no birthday on file.
#: A claim filed under this basis is rendered VERBATIM after the dash, so it
#: has to read as a whole clause ("calculated from “I was 30 in June 2011”").
CALCULATED_PROVENANCE_BASIS = "calculated"

#: The provenance-entry basis for a clause the system INFERRED rather than
#: worked out arithmetically (Timeline Fix 05 §8.3, lifehug-platform#759). Same
#: shape and the same reason as :data:`CALCULATED_PROVENANCE_BASIS` and, like
#: it, NOT a member of :data:`BASES`: place co-location writes *"you lived in
#: San Diego 1988-1990"*, which is a sentence about how the interval was
#: reached, not a quotation of anything the person said. It is rendered
#: VERBATIM for exactly that reason — the default clause is *"you said …"*, and
#: attributing an inference to the person is the lifehug#266 defect wearing a
#: new hat.
INFERRED_PROVENANCE_BASIS = "inferred"

#: The provenance bases whose ``claim`` is a whole clause ABOUT the derivation
#: and is therefore rendered as itself, with nobody attributed.
VERBATIM_PROVENANCE_BASES = (CALCULATED_PROVENANCE_BASIS, INFERRED_PROVENANCE_BASIS)

#: How much each basis is trusted when two claims disagree (ruling 3).
#:
#: The three v204 weights are FLAT — one number each, no era-conditional
#: term (ADR 0025 ruling 5). `document` outranks `stated` because a
#: printed date is not a reconstruction; `relative` sits just under `stated`
#: because proxy report is meant to be used *with* the index report and not
#: instead of it (Straughen et al. 2013); `photo` sits under
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

    v290: EDTF is the only thing :func:`parse_edtf` reads, but the landmark
    leaves' own prompts teach a person writes a date "plainly" — ``2 April
    1979``, ``July 11, 1981``, ``Jun 1986`` — none of which is EDTF. Both
    places :func:`parse_edtf` can fail below now fall back to
    :func:`parse_loose_date` for a string ``best`` before giving up; a form
    that fails BOTH stays exactly what it always was, an unparsed ``best``
    with no bounds.
    """
    parsed = from_dict(value)
    if parsed is None:
        if isinstance(value, str):
            return parse_loose_date(value)
        return None
    if parsed.earliest or parsed.latest:
        return parsed.to_dict()
    rebuilt = parse_edtf(parsed.best, basis=parsed.basis)
    if rebuilt is None and isinstance(parsed.best, str):
        loose = parse_loose_date(parsed.best)
        if loose is not None:
            rebuilt = from_dict(loose)
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


# --------------------------------------------------------------------------
# Loose / natural date text
# --------------------------------------------------------------------------

#: Month name (and 3-letter abbreviation) -> 1-12, case-insensitive. Built
#: from :data:`MONTH_NAMES` rather than re-typed — the same discipline
#: `go_dig_grammar._MONTH_LOOKUP` and `general_listener._MONTH_WORDS` already
#: follow for their own tables (recurring-defect doctrine). This module does
#: NOT import `go_dig_grammar` (that module is being retired); the lookup
#: shape is copied, not shared, because the two are allowed to diverge.
_LOOSE_MONTH_LOOKUP: dict[str, int] = {}
for _loose_index, _loose_name in enumerate(MONTH_NAMES, start=1):
    _LOOSE_MONTH_LOOKUP[_loose_name.lower()] = _loose_index
    _LOOSE_MONTH_LOOKUP[_loose_name[:3].lower()] = _loose_index
del _loose_index, _loose_name

#: The owner's own written convention for an estimate — a whole date
#: bracketed, e.g. ``[Jun 1986]`` — also read by
#: `go_dig_grammar.parse_date_bound`. Copied, not shared, for the same reason
#: the month lookup above is copied.
_LOOSE_BRACKET_RE = re.compile(r"^\[(.*)\]$")
#: ``Month D, YYYY`` / ``Month D YYYY`` — the comma is optional either way.
_LOOSE_MONTH_DAY_YEAR_RE = re.compile(
    r"^([A-Za-z]+)\.?\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{4})$", re.IGNORECASE
)
#: ``D Month YYYY``.
_LOOSE_DAY_MONTH_YEAR_RE = re.compile(
    r"^(\d{1,2})(?:st|nd|rd|th)?\s+([A-Za-z]+)\.?\s+(\d{4})$", re.IGNORECASE
)
#: ``Month YYYY``.
_LOOSE_MONTH_YEAR_RE = re.compile(r"^([A-Za-z]+)\.?\s+(\d{4})$")
#: One explicit whole-string range connector. Endpoints are parsed separately
#: by the same single-date authority below; two connectors are ambiguous.
_LOOSE_RANGE_CONNECTOR_RE = re.compile(
    r"\s+(?:through|to|until|till|[-–—])\s+", re.IGNORECASE
)
_LOOSE_RANGE_FROM_RE = re.compile(r"^from\s+", re.IGNORECASE)
#: Natural forms beyond the landmark leaves' plain dates. Each is deterministic
#: and each is refused when the year is missing. A trailing clock time is noise
#: on a date ("May 10, 2013 10:25pm"): the date stands and the time is dropped.
_LOOSE_TRAILING_TIME_RE = re.compile(
    r"\s+(?:at\s+)?\d{1,2}(?::\d{2})?\s*(?:a\.?m\.?|p\.?m\.?)$", re.IGNORECASE
)
#: ``M/D/YYYY`` or ``D/M/YYYY``. Unambiguous when one field exceeds 12 or both
#: agree; when both readings are calendar days the parse is the interval that
#: covers both readings, never a guess at the writer's convention.
_LOOSE_NUMERIC_DATE_RE = re.compile(r"^(\d{1,2})/(\d{1,2})/(\d{4})$")
#: ``Month D–D, YYYY``: a few days inside one month.
_LOOSE_MONTH_DAY_SPAN_RE = re.compile(
    r"^([A-Za-z]+)\.?\s+(\d{1,2})(?:st|nd|rd|th)?\s*[-–—]\s*"
    r"(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{4})$",
    re.IGNORECASE,
)
#: ``early 1990s`` / ``mid-90s`` / ``the late '80s``. A bare two-digit decade
#: reads against the twentieth century from the 30s on and the twenty-first
#: before that; the qualified thirds are the conventional ones.
_LOOSE_DECADE_RE = re.compile(
    r"^(?:the\s+)?(?:(early|mid|late)[\s-]*)?'?(\d{4}|\d{2})s$", re.IGNORECASE
)
_DECADE_THIRDS = {"early": (0, 3), "mid": (3, 6), "late": (7, 9)}
#: Holidays a person names instead of a calendar date. Thanksgiving is
#: month-level on purpose: its day depends on the country.
_LOOSE_HOLIDAY_RE = re.compile(
    r"^(thanksgiving|christmas eve|christmas|new year'?s eve|new year'?s(?: day)?|"
    r"halloween|(?:fourth|4th) of july|independence day|valentine'?s(?: day)?)"
    r"\s+(?:of\s+)?(\d{4})$",
    re.IGNORECASE,
)
_HOLIDAY_DATES = {
    "thanksgiving": "-11",
    "christmas eve": "-12-24",
    "christmas": "-12-25",
    "new years eve": "-12-31",
    "new years": "-01-01",
    "new years day": "-01-01",
    "halloween": "-10-31",
    "fourth of july": "-07-04",
    "4th of july": "-07-04",
    "independence day": "-07-04",
    "valentines": "-02-14",
    "valentines day": "-02-14",
}


def _parse_loose_single_date(raw: str) -> DateRecord | None:
    """Parse one finite date, deliberately refusing every interval form."""
    record = parse_edtf(raw, basis="stated")
    if record is None:
        edtf: str | None = None
        match = _LOOSE_MONTH_DAY_YEAR_RE.match(raw)
        if match:
            month = _LOOSE_MONTH_LOOKUP.get(match.group(1).lower())
            day = int(match.group(2))
            if month and 1 <= day <= 31:
                edtf = f"{int(match.group(3)):04d}-{month:02d}-{day:02d}"
        if edtf is None:
            match = _LOOSE_DAY_MONTH_YEAR_RE.match(raw)
            if match:
                day = int(match.group(1))
                month = _LOOSE_MONTH_LOOKUP.get(match.group(2).lower())
                if month and 1 <= day <= 31:
                    edtf = f"{int(match.group(3)):04d}-{month:02d}-{day:02d}"
        if edtf is None:
            match = _LOOSE_MONTH_YEAR_RE.match(raw)
            if match:
                month = _LOOSE_MONTH_LOOKUP.get(match.group(1).lower())
                if month:
                    edtf = f"{int(match.group(2)):04d}-{month:02d}"
        if edtf is None:
            match = _LOOSE_NUMERIC_DATE_RE.match(raw)
            if match:
                first, second, year = (int(group) for group in match.groups())
                if first > 12 >= second >= 1 and first <= 31:
                    edtf = f"{year:04d}-{second:02d}-{first:02d}"
                elif (second > 12 >= first >= 1 and second <= 31) or (
                        first == second and 1 <= first <= 12):
                    edtf = f"{year:04d}-{first:02d}-{second:02d}"
        if edtf is None:
            match = _LOOSE_HOLIDAY_RE.match(raw)
            if match:
                name = re.sub(r"[^a-z0-9 ]", "", match.group(1).lower())
                suffix = _HOLIDAY_DATES.get(name)
                if suffix:
                    edtf = f"{int(match.group(2)):04d}{suffix}"
        record = parse_edtf(edtf, basis="stated") if edtf is not None else None
    if (record is None or record.granularity == "range"
            or record.earliest is None or record.latest is None):
        return None
    return record


def _parse_loose_natural_range(raw: str) -> DateRecord | None:
    """Parse one explicit ``A through B`` / ``A to B`` whole-string range."""
    body = _LOOSE_RANGE_FROM_RE.sub("", raw, count=1)
    connectors = list(_LOOSE_RANGE_CONNECTOR_RE.finditer(body))
    if len(connectors) != 1:
        return None
    connector = connectors[0]
    left = _parse_loose_single_date(body[:connector.start()].strip())
    right = _parse_loose_single_date(body[connector.end():].strip())
    if left is None or right is None:
        return None
    left_bound = _ordinal(left.earliest, end=False)
    right_bound = _ordinal(right.latest, end=True)
    if left_bound is None or right_bound is None or left_bound > right_bound:
        return None
    confidence = max((left.confidence, right.confidence), key=CONFIDENCES.index)
    return DateRecord(
        best=f"{left.best}/{right.best}",
        earliest=left.earliest,
        latest=right.latest,
        granularity="range",
        confidence=confidence,
        basis="stated",
        anchors=(
            left.anchors + tuple(a for a in right.anchors if a not in left.anchors)
        ),
        provenance=left.provenance + right.provenance,
    )


def _parse_loose_span_forms(raw: str) -> DateRecord | None:
    """Whole-string spans a person writes as one phrase.

    A few days inside one month (``December 21-22, 2010``), a decade or a
    third of one (``early 1990s``, ``the '90s``), or a numeric date whose day
    and month cannot be told apart (``05/10/2013``), which parses to the
    interval covering both readings rather than to a guess at the convention.
    """
    match = _LOOSE_MONTH_DAY_SPAN_RE.match(raw)
    if match:
        month = _LOOSE_MONTH_LOOKUP.get(match.group(1).lower())
        first, last = int(match.group(2)), int(match.group(3))
        year = int(match.group(4))
        if month and 1 <= first <= last <= 31:
            return _interval(
                f"{year:04d}-{month:02d}-{first:02d}",
                f"{year:04d}-{month:02d}-{last:02d}",
                "stated",
            )
        return None
    match = _LOOSE_DECADE_RE.match(raw)
    if match:
        third, digits = match.group(1), match.group(2)
        if len(digits) == 2:
            digits = ("19" if int(digits) >= 30 else "20") + digits
        decade = int(digits) // 10 * 10
        if third is None:
            return parse_edtf(f"{decade // 10}X", basis="stated")
        low, high = _DECADE_THIRDS[third.lower()]
        record = _interval(str(decade + low), str(decade + high), "stated")
        return replace(record, confidence="approximate") if record else None
    match = _LOOSE_NUMERIC_DATE_RE.match(raw)
    if match:
        first, second, year = (int(group) for group in match.groups())
        if 1 <= first <= 12 and 1 <= second <= 12 and first != second:
            low, high = sorted((
                f"{year:04d}-{first:02d}-{second:02d}",
                f"{year:04d}-{second:02d}-{first:02d}",
            ))
            record = _interval(low, high, "stated")
            if record is None:
                return None
            return replace(
                record,
                confidence="approximate",
                provenance=({
                    "claim": raw,
                    "basis": "stated",
                    "note": "day/month order ambiguous; interval covers both readings",
                },),
            )
    return None


def parse_loose_date(text: object) -> dict | None:
    """Natural date text into the identical normalized dict :func:`normalized_date` returns.

    The landmark leaves' own prompts (``interactions/landmarks/prompt/``)
    teach a date is written "plainly" as a year, a year-month, a full date,
    or a month name with a year — ``1974``, ``1974-06``, ``1981-07-11``,
    ``2 April 1979``, ``April 2, 1979``, ``July 11, 1981``, ``Jun 1986``,
    ``June 1986`` — case-insensitive, full month names or their 3-letter
    abbreviations. A whole-string range may join two such explicit dates with
    one ``through`` or ``to`` and may start with ``from``. Each endpoint is
    parsed by the same single-date path; missing years, nested ranges,
    multiple connectors, ambiguous numeric dates, and reversed endpoints are
    refused. The EDTF forms are handed straight to :func:`parse_edtf`, which
    already reads them (and every other human form it accepts, such as
    ``spring 1998`` or ``1970s``, for free); the month-name forms are turned
    into the equivalent EDTF expression first. A whole string wrapped in
    square brackets — ``[Jun 1986]`` — parses to the same date with
    ``confidence: "approximate"``, the owner's own estimation convention.

    Beyond those plain forms, the deterministic phrases people actually write
    are read too: a numeric ``M/D/YYYY`` (an ambiguous one becomes the interval
    covering both readings), a few days inside one month, a decade or a third
    of one, a fixed-date holiday with its year, an ``about``/``around`` prefix
    (``approximate``), and a trailing clock time, which is dropped. A range may
    also join two dates with ``until``, ``till`` or a spaced dash.

    Never raises; text that is none of the above is ``None``, exactly like
    :func:`parse_edtf`. This is the ONLY fuzzy-date parsing this module
    performs — no other natural-language form is accepted.
    """
    if not isinstance(text, str):
        return None
    raw = " ".join(text.strip().split())
    if not raw:
        return None
    approximate = False
    match = _LOOSE_BRACKET_RE.match(raw)
    if match:
        raw = match.group(1).strip()
        if not raw:
            return None
        approximate = True
    raw = _LOOSE_TRAILING_TIME_RE.sub("", raw)
    match = _APPROX_PREFIX_RE.match(raw)
    if match:
        raw = raw[match.end():].strip()
        approximate = True

    record = parse_edtf(raw, basis="stated")
    if record is None:
        record = _parse_loose_natural_range(raw)
    if record is None:
        record = _parse_loose_single_date(raw)
    if record is None:
        record = _parse_loose_span_forms(raw)
    if record is None:
        return None
    if approximate:
        record = replace(record, confidence="approximate", best=f"{record.best}~")
    return record.to_dict()


def parse_stated_date(text: object) -> DateRecord | None:
    """A date in a person's own words as a record: EDTF first, then the loose forms.

    The one entry point for a classifier ``date.stated`` value. ``May 2022``
    and ``December 21, 2010`` are dates the person said; refusing them because
    they are not spelled as EDTF filed the moment as undated, which is a
    fabricated ignorance. Anything neither parser reads is still ``None``.
    """
    record = parse_edtf(text, basis="stated")
    if record is not None:
        return record
    loose = parse_loose_date(text)
    return from_dict(loose) if loose else None



# --------------------------------------------------------------------------
# Recency — "recent" is a PLACEMENT, not a guess (owner ruling 1, 2026-09-23)
# --------------------------------------------------------------------------

#: THE ONE RECENCY VOCABULARY. Owner ruling, staging 2026-09-23:
#:
#:     "'Recent' with a known capture date IS a placement, not a guess. Place
#:     the moment as a STATED range [capture_date − 6 months, capture_date],
#:     basis stated — it renders as 'placed by you', because the person is the
#:     one saying it was recent."
#:
#: The reasoning is the same one ADR 0024 already made about intervals: a
#: recency word plus a capture date bounds the moment, and *the interval is
#: itself a finding, not a failure*. What was new in the defect was the other
#: half — the system had been treating its OWN reading of "recent" as an
#: estimate it then asked the person to improve, when the person is the one who
#: said it. A capture date is a fact the vault holds; "recent" is a fact the
#: person stated; the interval between them is not arithmetic over a guess.
#:
#: Stronger recency words narrow it DETERMINISTICALLY, which is why this is a
#: table and not a single constant. Each rung is ``(months, days)`` back from
#: the capture date — months where the person spoke in months, days where they
#: spoke in days — plus the patterns that mean it. ``months=0, days=0`` marks
#: the one calendar-anchored rung ("this year" runs from 1 January of the
#: capture year, not from an offset).
#:
#: This table lives HERE, beside the other time tables (:data:`YEAR_RE`,
#: :data:`NUMBER_WORDS`, the loose-date forms) and beside
#: `cross_dating.AGE_STATEMENT_RES` and `general_listener.PRESCREEN_TABLES`
#: which both read their vocabularies from this module rather than re-typing
#: them. There is ONE recency vocabulary and every reader of ``when_hint`` or
#: of a recency cue goes through :func:`recency_cue`; a second table of
#: recency phrasings is exactly the duplicate the recurring-defect doctrine
#: forbids.
#:
#: NARROWEST FIRST, and the order is load-bearing: "this week" must beat "this
#: year", and "a few weeks ago" must beat "a few months ago". The first rung
#: that matches wins, so a story saying both "recently" and "yesterday" is
#: placed on the tighter of the two — the stronger word is the one the person
#: chose to be precise with.
#: THE VETO. A recency word used to say the OPPOSITE of recency, which English
#: does constantly: *"I remember it like it was yesterday"* is a claim about how
#: vivid the memory is, and *"in recent decades"* is a claim about a stretch far
#: wider than any rung below. Checked BEFORE the rungs and applied to the whole
#: text, exactly as `cross_dating.THIRD_PERSON_AGE_RES` vetoes an age statement
#: over the moment's whole text rather than over the fragment that matched — a
#: veto beside a positive table, for the same reason and at the same grain.
#:
#: Over-refusing is the CHEAP direction here and under-refusing is not. A cue
#: this table wrongly vetoes leaves the moment exactly the undated occurrence it
#: was, which is visible and still asked about; a cue that wrongly fires files a
#: `stated` interval that reads as *placed by you*, is never re-asked, and no
#: longer shows as a gap — a wrong date that hides itself.
RECENCY_VETO_RES = (
    # "like it was yesterday", "as though it were yesterday", "feels like
    # yesterday" — vividness, not a date.
    re.compile(r"\b(?:like|as if|as though)\s+it\s+(?:was|were|happened)\s+yesterday\b",
               re.IGNORECASE),
    re.compile(r"\bfe(?:el|els|lt)s?\s+like\s+(?:it\s+was\s+)?yesterday\b", re.IGNORECASE),
    # "in recent years", "recent decades", "recent memory", "recent history" —
    # a stretch, and a wide one.
    re.compile(r"\brecent\s+(?:years|decades|centuries|generations|times|"
               r"memory|history|past|months|weeks|days)\b", re.IGNORECASE),
    # "in those days" sitting beside "these days".
    re.compile(r"\b(?:back\s+)?in\s+(?:those|the)\s+days\b", re.IGNORECASE),
)

RECENCY_RUNGS = (
    # "yesterday" / "the other day" / "this week" -> 2 weeks
    ("immediate", 0, 14, (
        re.compile(r"\byesterday\b", re.IGNORECASE),
        re.compile(r"\bthe other (?:day|night|morning|evening)\b", re.IGNORECASE),
        re.compile(r"\bthis (?:week|morning|afternoon|evening)\b", re.IGNORECASE),
        re.compile(r"\b(?:a few|couple of) days ago\b", re.IGNORECASE),
    )),
    # "last week" -> 1 month
    ("last_week", 1, 0, (
        re.compile(r"\blast (?:week|weekend)\b", re.IGNORECASE),
        re.compile(r"\ba week ago\b", re.IGNORECASE),
    )),
    # "last month" / "a few weeks ago" -> 2 months
    ("last_month", 2, 0, (
        re.compile(r"\blast month\b", re.IGNORECASE),
        re.compile(r"\b(?:a few|a couple of|a couple|several) weeks ago\b", re.IGNORECASE),
        re.compile(r"\ba month ago\b", re.IGNORECASE),
    )),
    # "recently" / "lately" / "these days" / "a recent …" -> 6 months.
    # The bare word is included on purpose: the classifier's own
    # ``when_hint`` for a story with no time words in it is the single word
    # `recent`, which is what node `d49b31bc` carried, and the prompting
    # question — *"What's a recent moment that was peak James…?"* — is where
    # the word was actually said.
    ("recent", 6, 0, (
        re.compile(r"\brecent(?:ly)?\b", re.IGNORECASE),
        re.compile(r"\blately\b", re.IGNORECASE),
        re.compile(r"\bthese days\b", re.IGNORECASE),
        re.compile(r"\bnowadays\b", re.IGNORECASE),
        re.compile(r"\bin the last (?:little )?while\b", re.IGNORECASE),
    )),
    # "a few months ago" -> 9 months
    ("months_ago", 9, 0, (
        re.compile(r"\b(?:a few|a couple of|a couple|several) months ago\b", re.IGNORECASE),
    )),
    # "this year" -> 1 January of the capture year to the capture date.
    #
    # "earlier this year" belongs HERE and not on the 9-month rung above,
    # however much wider this is: the phrase ASSERTS the calendar year, and a
    # 9-month offset from a February capture would start in the year before the
    # one the person just named. A rung may be wider than the phrase suggests;
    # it may never contradict it.
    ("this_year", 0, 0, (
        re.compile(r"\b(?:earlier )?this year\b", re.IGNORECASE),
    )),
)

#: The rung whose window is the ruling's DEFAULT — the one a bare "recent"
#: lands on, and the six months the ruling names in its first sentence. Named
#: so a caller can say "the default recency window" without re-counting the
#: table.
DEFAULT_RECENCY_RUNG = "recent"

#: The calendar-anchored rung's marker: it runs from 1 January of the capture
#: year rather than from an offset behind the capture date.
RECENCY_YEAR_START_RUNG = "this_year"

#: What a recency placement's provenance ``claim`` reads as. The owner's words
#: for it are *"it renders as 'placed by you', because the person is the one
#: saying it was recent"*, so the clause is filed under basis ``stated`` and
#: :func:`display_date` renders it *"— you said recent, told 2026-07-14"*. It
#: is deliberately NOT one of :data:`VERBATIM_PROVENANCE_BASES`: a calculated
#: or inferred clause is the one thing this must not read as.
RECENCY_PROVENANCE = "{cue}, told {captured}"

#: Where a recency placement came from, for the provenance entry's ``source``.
RECENCY_PROVENANCE_SOURCE = "recency"


def recency_cue(*texts: object) -> tuple[str, str] | None:
    """``(rung name, the words that matched)`` for the strongest cue, or ``None``.

    Reads each text in the order given and returns the NARROWEST rung any of
    them matched (:data:`RECENCY_RUNGS` is narrowest-first, and the scan is by
    rung rather than by text, so a tight cue in the prompting question beats a
    loose one in the story and vice versa). This is the one reader of the
    recency vocabulary: `classifier_claims`, the fold and the prescreen all
    call it rather than matching the patterns themselves.

    TWO REFUSALS, both applied per TEXT before any rung is tried, and both of
    them the cheap direction (see :data:`RECENCY_VETO_RES`):

    * **The year trap.** A text that names a four-digit year DATES ITSELF, so a
      recency word inside it is not the reading — *"this week in 1985 we drove
      to Mesa"*, *"I remember it like it was yesterday: he wrote from Korea in
      1952"*. This is `classifier_claims._age_band_text`'s own guard, reused
      rather than re-decided: that function refuses an age value carrying a year
      for exactly this reason, and :data:`YEAR_RE` is the one table both ask.
      Per text and not per call, so a ``when_hint`` of *"recent"* still places a
      story whose description happens to mention a year elsewhere.
    * **The idioms**, :data:`RECENCY_VETO_RES` — a recency word saying the
      opposite of recency.
    """
    haystacks = [
        str(text) for text in texts
        if isinstance(text, str) and text.strip()
        and not YEAR_RE.search(text)
        and not any(veto.search(text) for veto in RECENCY_VETO_RES)
    ]
    if not haystacks:
        return None
    for name, _months, _days, patterns in RECENCY_RUNGS:
        for pattern in patterns:
            for body in haystacks:
                match = pattern.search(body)
                if match is not None:
                    return name, " ".join(match.group(0).split())
    return None


def recency_window(name: object) -> tuple[int, int] | None:
    """One rung's ``(months, days)`` back from the capture date, or ``None``."""
    wanted = str(name or "").strip()
    for rung, months, days, _patterns in RECENCY_RUNGS:
        if rung == wanted:
            return months, days
    return None


def _shift_months(day: _date, months: int) -> _date:
    """``day`` that many months EARLIER, clamped into a shorter month.

    31 August less six months is 28 February, not an error: the same clamp
    :func:`_shift_token` already applies to a leap day, applied to the one
    other place a month's length can bite.
    """
    total = (day.year * 12 + (day.month - 1)) - months
    year, month = divmod(total, 12)
    month += 1
    return _date(year, month, min(day.day, _month_last_day(year, month)))


def from_recency(captured: object, *texts: object) -> DateRecord | None:
    """A recency cue plus a capture date as a STATED range (owner ruling 1).

    ``captured`` is when the telling was recorded — a prompted answer's
    ``captured_at``/``answered_date``, the one date the vault holds about the
    telling itself. ``texts`` are the places the cue may have been said, in
    preference order: the story's own words, and the QUESTION that prompted the
    answer, because *"What's a recent moment…"* is the person being told the
    word and answering in it.

    ``None`` — unchanged, still an occurrence — when there is no cue, or no
    capture date, or the capture date is unreadable. The capture date is the
    whole warrant: without it "recent" bounds nothing and the honest reading is
    the one the substrate already had.

    The record is ``basis: "stated"``, because the person stated it, and its
    provenance clause is :data:`RECENCY_PROVENANCE` under the same basis, so it
    renders as *placed by you* and never as arithmetic.
    """
    day = capture_day(captured)
    if day is None:
        return None
    # v360 (owner, 2026-09-25), :data:`N_MONTHS_AGO_IS_COUNTED_BACK_FROM_THE_TELLING`:
    # a COUNTED cue ("six to eight months ago") is tighter than any rung, so it
    # is read first, under the same two refusals the rungs keep.
    counted = from_months_ago(day, *texts)
    if counted is not None:
        return counted
    found = recency_cue(*texts)
    if found is None:
        return None
    name, phrase = found
    window = recency_window(name)
    if window is None:
        return None
    months, days = window
    if name == RECENCY_YEAR_START_RUNG:
        start = _date(day.year, 1, 1)
    elif months:
        start = _shift_months(day, months)
    elif days:
        start = day - _timedelta(days=days)
    else:  # pragma: no cover - a rung with no window is a table error
        return None
    if start > day:
        return None
    earliest, latest = start.isoformat(), day.isoformat()
    return DateRecord(
        best=f"{earliest}/{latest}",
        earliest=earliest,
        latest=latest,
        granularity="range",
        # They said it loosely and they said it themselves: `approximate` is
        # the confidence for a bound the person asserted without naming a day.
        confidence="approximate",
        basis="stated",
        provenance=({
            "claim": RECENCY_PROVENANCE.format(cue=phrase.lower(), captured=latest),
            "basis": "stated",
            "source": RECENCY_PROVENANCE_SOURCE,
        },),
    )


def capture_day(value: object) -> _date | None:
    """A capture timestamp as a calendar day, or ``None``.

    PUBLIC because the recency rung's two halves live in two modules: this one
    turns the frontmatter value into a day, and `classifier_claims.
    capture_context` needs the same answer to decide which of
    :data:`classifier_claims.CAPTURE_DATE_KEYS` to use. One parser, two
    callers — a second reading of ``captured_at`` is exactly the duplicate this
    module exists not to have.

    Accepts a ``date``/``datetime``, an ISO day, and an ISO timestamp with or
    without a zone — every shape a vault's ``captured_at`` has ever carried —
    and refuses everything else rather than guessing.
    """
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, _date):
        return value
    text = str(value or "").strip()
    if not text:
        return None
    match = _DAY_RE.match(text[:10])
    if match is None:
        return None
    year, month, day = (int(part) for part in match.groups())
    if not (1 <= month <= 12) or not (1 <= day <= _month_last_day(year, month)):
        return None
    return _date(year, month, day)

def display_date(record: object, *, with_basis: bool = True) -> str:
    """Render a record the way the person would recognise it.

    ``"around 1984 — you said you were about 5"``, ``"spring 1998"``,
    ``"sometime in the 1980s"``, ``"1984–1990"``, ``"after the move to Mesa"``.
    The basis clause is appended only when the record carries a provenance
    ``claim`` (there is nothing to quote back otherwise), and every clause but
    :data:`VERBATIM_PROVENANCE_BASES` attributes that claim to somebody — the
    person, a relative, a document. A calculated or inferred clause is rendered
    verbatim because there is nobody to attribute it to.
    """
    record = record if isinstance(record, DateRecord) else from_dict(record)
    if record is None:
        return ""
    body = _display_interval(shown_at_its_grain(record))
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
    # v204 (ADR 0025, retired 2026-09-03): the three evidence bases each
    # name their own warrant, and `photo` says out loud that it is a window
    # ("the system should say so on the record it writes").
    if claim_basis == "document":
        return f"{body} — printed on {claim}"
    if claim_basis == "photo":
        return f"{body} — from the photograph: {claim} (a window, not a day)"
    if claim_basis == "relative":
        name = witness_name(record)
        return f"{body} — {name} says {claim}" if name else f"{body} — a relative says {claim}"
    # A calculated clause already IS the sentence (lifehug#266): it names the
    # arithmetic, so "you said" in front of it would attribute to the person a
    # statement they never made.
    if claim_basis in VERBATIM_PROVENANCE_BASES:
        return f"{body} — {claim}"
    return f"{body} — you said {claim}"


#: Owner ruling, 2026-09-25 (the cornerstones ruling): *"Days worked out by
#: arithmetic display as months."* A day is shown only when somebody SAID it —
#: the person, a document, a relative (:data:`DAY_SAYING_BASES`) — or when it
#: is a definitional join to such a day: a ``certain`` single-day ``anchor``
#: record is a landmark's own date carried onto a moment that IS that landmark
#: (the Derived-date entry in the handbook glossary: "a certain birthday gives
#: 11 July 1981"), and every cornerstone the fold holds to a day is one of
#: those two. A day that came out of arithmetic — an age frame's edge, a
#: containment window opening on a birthday, a stay's inferred start — is
#: shown at its MONTH ("June 1989"). DISPLAY ONLY: the stored interval keeps
#: its day, so every derivation downstream still has it.
A_WORKED_OUT_DAY_IS_SHOWN_AS_ITS_MONTH = (
    "a day is displayed only when the person or a document stated it, or when "
    "it is a certain definitional join to such a day; a day worked out by "
    "arithmetic is displayed as its month, and the stored interval is unchanged"
)

#: The bases whose day somebody actually said.
DAY_SAYING_BASES = ("stated", "document", "relative")

_DAY_POINT_RE = re.compile(r"^(-?\d{4}-\d{2})-\d{2}([~?%]*)$")


def day_was_said(record: object) -> bool:
    """Did a person or a document give this record's DAY?
    (:data:`A_WORKED_OUT_DAY_IS_SHOWN_AS_ITS_MONTH`)"""
    record = record if isinstance(record, DateRecord) else from_dict(record)
    if record is None:
        return False
    if record.basis in DAY_SAYING_BASES:
        return True
    return (record.basis == "anchor" and record.confidence == "certain"
            and record.earliest is not None and record.earliest == record.latest)


def shown_at_its_grain(record: DateRecord) -> DateRecord:
    """The record as it may be DISPLAYED: a worked-out day becomes its month."""
    if day_was_said(record):
        return record

    def month(value: str | None) -> str | None:
        return value[:7] if isinstance(value, str) and _DAY_RE.match(value) else value

    earliest, latest = month(record.earliest), month(record.latest)
    if (earliest, latest) == (record.earliest, record.latest):
        return record
    best = record.best
    point = _DAY_POINT_RE.match(best or "")
    if point:
        best = point.group(1) + point.group(2)
    elif best and "/" in best:
        best = None
    granularity = record.granularity
    if granularity == "day":
        granularity = "month"
    return replace(record, best=best, earliest=earliest, latest=latest,
                   granularity=granularity)


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
    confidence = at_most(confidence, "inferred")
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


def dates_agree(left: object, right: object) -> bool:
    """Do two readings leave any date they could BOTH be?

    An ABSENT side agrees with everything — an undated telling is the one asking
    for a date, and caution is not a contradiction. Two dated sides must
    intersect: :func:`intersect` returns ``None`` for disjoint inputs, and
    disjoint bounds are a contradiction no deterministic rung, and no re-key,
    may pass through (`episode_binder.A_MERGE_NEVER_MOVES_A_DATED_MOMENT`).

    One definition, three readers (v342): the binder's rungs, the binder's
    placed-window half, and the fold's own carry. The first two used to hold a
    private copy of this arithmetic and the third would have been the fourth.
    """
    if left is None or right is None:
        return True
    return intersect(left, right) is not None


#: What an ABSENT bound means to the interval arithmetic below. An interval
#: with no ``earliest`` reaches back forever; one with no ``latest`` runs past
#: today ("May 2022 – present"). Spelled as ordinals rather than as ``None``
#: branches at four comparison sites, because the branches are where the two
#: functions below would eventually disagree about what an open end is.
UNBOUNDED_EARLIEST = (-9999, 1, 1)
UNBOUNDED_LATEST = (9999, 12, 31)


def _interval_ordinals(record: object) -> tuple[tuple[int, int, int], tuple[int, int, int]] | None:
    """One record as ``(lo, hi)`` comparable ordinals, absent bounds filled."""
    parsed = _as_record(record)
    if parsed is None:
        return None
    lo = _ordinal(parsed.earliest, end=False) or UNBOUNDED_EARLIEST
    hi = _ordinal(parsed.latest, end=True) or UNBOUNDED_LATEST
    if lo > hi:
        return None
    return lo, hi


def _month_index(ordinal: tuple[int, int, int]) -> int:
    return ordinal[0] * 12 + (ordinal[1] - 1)


def overlap_months(left: object, right: object) -> int:
    """Whole calendar months two intervals SHARE; ``0`` when they share none.

    GRAIN-HONEST, because `_ordinal` is: a year fills to its own two edges, so
    1988 and 1988–1990 share the twelve months of 1988, while 1990 and 1991
    share none at all. The count is inclusive of both end months, which is the
    reading a person uses — "we overlapped June, July and August" is three.

    This and :func:`gap_months` are ONE arithmetic read two ways, and they are
    here rather than at their two call sites (the interval-aware ladder key and
    the residence-overlap rule) because two copies of "do these stretches
    touch" is exactly the recurring-defect class this repo keeps consolidating
    time tables to avoid.
    """
    a = _interval_ordinals(left)
    b = _interval_ordinals(right)
    if a is None or b is None:
        return 0
    lo = max(a[0], b[0])
    hi = min(a[1], b[1])
    if lo > hi:
        return 0
    return _month_index(hi) - _month_index(lo) + 1


def gap_months(left: object, right: object) -> int | None:
    """Whole months BETWEEN two disjoint intervals; ``None`` when they overlap.

    ``0`` is abutting — one ends in December and the next begins in January,
    with no month unaccounted for between them. Anything an interval cannot
    bound (an open end that runs past the other interval) overlaps rather than
    gaps, so this returns ``None`` there too.
    """
    a = _interval_ordinals(left)
    b = _interval_ordinals(right)
    if a is None or b is None:
        return None
    lo = max(a[0], b[0])
    hi = min(a[1], b[1])
    if lo <= hi:
        return None
    return max(0, _month_index(lo) - _month_index(hi) - 1)


def span_months(record: object) -> int | None:
    """How many whole calendar months ONE interval covers; ``None`` when unbounded.

    The third reading of the same arithmetic :func:`overlap_months` and
    :func:`gap_months` already share, and here for the same stated reason: how
    WIDE a placement is is a question two callers now ask (the precision-card
    stakes gate, and anything that wants to say "this is inside about a year"),
    and a second implementation of it is the duplicate those two docstrings
    exist to prevent.

    Inclusive of both end months, exactly as :func:`overlap_months` is: a
    single year is 12, a single month is 1, and 2026-01-14/2026-07-14 is 7. An
    open-ended or unreadable record is ``None`` — an interval with no far edge
    has no width, and a caller must decide what that means rather than be
    handed a number that pretends otherwise.
    """
    parsed = record if isinstance(record, DateRecord) else from_dict(record)
    if parsed is None or parsed.earliest is None or parsed.latest is None:
        return None
    bounds = _interval_ordinals(parsed)
    if bounds is None:
        return None
    lo, hi = bounds
    if lo > hi:
        return None
    return _month_index(hi) - _month_index(lo) + 1


def at_most(confidence: str, floor: str) -> str:
    """The weaker of two confidences (CONFIDENCES is best-first).

    The rule every calculation here obeys: a value the system worked out is
    never held more firmly than the weakest thing it was worked out from. It
    is public because callers outside this module do the same arithmetic —
    re-spelling it as a ``max(..., key=CONFIDENCES.index)`` at a call site is
    a second copy of a rule that must only ever have one (recurring-defect
    doctrine).
    """
    return confidence if CONFIDENCES.index(confidence) >= CONFIDENCES.index(floor) else floor


#: The private spelling this rule shipped under, kept so no caller breaks.
_at_most = at_most


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
#: One age token. Four shapes, first match wins at each position, and the
#: order is load-bearing (v360, owner 2026-09-25, ``parse_age("nineteen to
#: twenty-one")`` had answered ``(1, 20)`` because "twenty-one" split into
#: 20 and 1):
#:
#: * a small FRACTION (``1/2``, ``3/4``) is consumed and counts for nothing —
#:   *"15 1/2"* is fifteen, not fifteen-or-one;
#: * a number with an optional DECIMAL tail — *"15.5"* is fifteen, the year the
#:   person is in, exactly as *"fifteen and a half"* is;
#: * a COMPOUND number word — a tens word, then a hyphen or a space, then a
#:   unit word (*"twenty-one"*, *"thirty two"*) — is ONE age;
#: * any other word, looked up in :data:`NUMBER_WORDS`.
_AGE_TOKEN_RE = re.compile(
    r"(?P<fraction>\b[1-3]\s*/\s*[2-4]\b)"
    r"|(?P<num>\d{1,3})(?:\.\d+)?"
    r"|(?P<tens>twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety)"
    r"(?:[\s-]+(?P<unit>one|two|three|four|five|six|seven|eight|nine)\b)?"
    r"|(?P<word>[a-z]+)",
    re.IGNORECASE)
_AGE_DECADE_RE = re.compile(r"\b(?:in\s+(?:my\s+)?)?(?P<decade>\d{2})s\b", re.IGNORECASE)
_AGE_DECADE_WORDS = {
    "twenties": 20,
    "thirties": 30,
    "forties": 40,
    "fifties": 50,
    "sixties": 60,
    "seventies": 70,
    "eighties": 80,
    "nineties": 90,
}


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
    decade_match = _AGE_DECADE_RE.search(lowered)
    if decade_match:
        decade = int(decade_match.group("decade"))
        if 10 <= decade <= 90 and decade % 10 == 0:
            return decade, decade + 9, hedged
    for word, decade in _AGE_DECADE_WORDS.items():
        if re.search(rf"\b{word}\b", lowered):
            return decade, decade + 9, hedged
    ages: list[int] = []
    for token in _AGE_TOKEN_RE.finditer(lowered):
        if token.group("fraction"):
            continue
        if token.group("num"):
            value = int(token.group("num"))
            if 0 <= value <= 120:
                ages.append(value)
        elif token.group("tens"):
            ages.append(_NUMBER_WORDS[token.group("tens")]
                        + _NUMBER_WORDS.get(token.group("unit") or "", 0))
        elif token.group("word") in _NUMBER_WORDS:
            ages.append(_NUMBER_WORDS[token.group("word")])
    if not ages:
        return None
    return min(ages), max(ages), hedged


# --------------------------------------------------------------------------
# WHOSE AGE IT IS (lifehug#415; v359's card-answer rule, moved here to serve
# the classifier seat too — v360, owner 2026-09-25)
# --------------------------------------------------------------------------

#: One stated age, as the person said it: a number or a number word (compound
#: words included), optionally a band — *"4 or 5"*, *"19-21"*, *"22, 23"*,
#: *"four or five"*, *"nineteen to twenty-one"*, *"15 and a half"*. Captured as
#: group 1. The words are :data:`NUMBER_WORDS`' own, so this vocabulary and
#: :func:`parse_age` cannot drift apart.
_AGE_WORD = (r"(?:\d{1,3}(?:\.\d+)?|(?:" + "|".join(
    sorted(NUMBER_WORDS, key=len, reverse=True))
    + r")(?:[\s-]+(?:one|two|three|four|five|six|seven|eight|nine)\b)?)")
AGE_TEXT = (r"(" + _AGE_WORD
            + r"(?:\s*(?:-|–|—|to|or|,)\s*" + _AGE_WORD + r")?"
            + r"(?:\s+and\s+a\s+half)?)")

#: The words between a speaker's verb and the age: hedges and asides (*"like"*,
#: *"probably"*, *"just off my mission, so like"*). Bounded, inside one
#: sentence, and it may not hold ANOTHER copula — *"I was there when Dad was
#: 19"* is Dad's 19, never mine — so the age belongs to the nearest speaker.
_AGE_BRIDGE = (r"(?:(?!\b(?:was|is|were|are|am|been|turned|turns)\b|['’](?:s|m|re)\b)"
               r"[^.!?;:()]){0,40}?")

#: AN AGE SAID IN THE FIRST PERSON IS THE NARRATOR'S (v359, extended for the
#: classifier seat). *"when I was just off my mission, so like 22, 23"*, *"I
#: must have been like four or five years old"*, *"probably when I was 4 or
#: 5"*: the owner's own age, whatever moment it dates — it is measured from HIS
#: birth and stays on the same moment. A closed vocabulary of first-person
#: verbs; group 1 is the age text.
NARRATOR_AGE_RE = re.compile(
    r"\b(?:i|we)\s*(?:was|am|['’]m|were|are|['’]re|must\s+have\s+been|"
    r"would\s+have\s+been|might\s+have\s+been|could\s+have\s+been|"
    r"had\s+been|['’]d\s+been|['’]d\s+have\s+been|turned)\s+"
    + _AGE_BRIDGE + r"(?<![\w-])" + AGE_TEXT + r"(?![\w])",
    re.IGNORECASE)

#: An age stated OF a named person or a pronoun: *"Charlee is 15 and a half"*,
#: *"when Dad was 19"*, *"she's 15 and a half now"*, *"AJ was around nine"*.
#: Group ``who`` is the person as written, group ``tense`` the verb, group 3
#: the age text. STRICTER than the first person: only hedge words may sit
#: between the verb and the age, so *"two weeks after James was born, age
#: 31"* is never James's 31 — moving an age OFF the event's subject needs the
#: plainest statement there is.
_AGE_HEDGES = (r"(?:(?:about|around|maybe|only|just|like|probably|roughly|almost|"
               r"nearly|barely|currently|now|already|still)\s+)*")
THIRD_PERSON_AGE_RE = re.compile(
    r"\b(?P<who>(?:my\s+)?[a-z][\w’'-]*)\s*(?P<tense>is|was|['’]s|turned|turns)\s+"
    + _AGE_HEDGES + r"(?<![\w-])" + AGE_TEXT + r"(?![\w])",
    re.IGNORECASE)

#: Words that say the age is the one held ON THE DAY OF THE TELLING.
PRESENT_AGE_WORDS_RE = re.compile(
    r"\b(?:now|currently|right\s+now|today|at\s+the\s+moment|these\s+days|nowadays)\b",
    re.IGNORECASE)
_CURRENTLY_AGE_RE = re.compile(
    r"\bcurrently\s+" + _AGE_BRIDGE + r"(?<![\w-])" + AGE_TEXT + r"(?![\w])",
    re.IGNORECASE)
_PRESENT_TENSES = frozenset({"is", "'s", "’s", "am", "'m", "’m", "are", "turns"})
_SPEAKER_PRONOUNS = frozenset({"i", "we"})
_THIRD_PERSON_PRONOUNS = frozenset({"he", "she", "they", "it", "that", "this",
                                    "there", "which", "who", "what"})


def _same_age(found: object, wanted: object) -> bool:
    """Is the age a field names inside the age text a pattern captured?

    By parse, not by spelling: *"22, 23"* in the hint and *"22 or 23"* in the
    field are one age, and *"4"* read off a reply is inside *"4 or 5"*. One
    direction only: a field band WIDER than the statement (*"19 or 20
    (author); AJ about 9"* against *"AJ was around nine"*) is not that
    statement's age."""
    have, want = parse_age(str(found or "")), parse_age(str(wanted or ""))
    if have is None or want is None:
        return False
    return have[0] <= want[0] and want[1] <= have[1]


def age_is_first_person(text: object, age: object) -> bool:
    """Is ``age`` said in the first person anywhere in ``text``
    (:data:`NARRATOR_AGE_RE`)? The one test both seats ask — the card answer
    (`answer_placement.age_is_the_narrators`) and the classifier's claims
    (`classifier_claims.age_subject`)."""
    body = " ".join(str(text or "").split())
    if not body:
        return False
    return any(_same_age(match.group(1), age)
               for match in NARRATOR_AGE_RE.finditer(body))


def age_statement_of(text: object, age: object) -> dict | None:
    """Who ``text`` says holds ``age``, and whether they hold it NOW.

    ``{"speaker": "narrator"|"named"|"pronoun", "who": <as written>,
    "present": bool}`` or ``None`` when the text states that age of nobody.
    First person wins (:func:`age_is_first_person`); otherwise the nearest
    third-person statement of the same age. ``present`` is a present-tense
    verb (*"is"*, *"'s"*) or *"currently"* before the age, in a text that
    carries a word for the day of the telling (:data:`PRESENT_AGE_WORDS_RE`).
    """
    body = " ".join(str(text or "").split())
    if not body or parse_age(str(age or "")) is None:
        return None
    now_word = PRESENT_AGE_WORDS_RE.search(body) is not None
    for match in NARRATOR_AGE_RE.finditer(body):
        if _same_age(match.group(1), age):
            verb = match.group(0)[:match.start(1) - match.start(0)].lower()
            present = now_word and bool(re.search(r"\b(?:am|are)\b|['’](?:m|re)\b", verb))
            return {"speaker": "narrator", "who": "I", "present": present}
    for match in THIRD_PERSON_AGE_RE.finditer(body):
        if not _same_age(match.group(3), age):
            continue
        who = match.group("who")
        word = who.lower().removeprefix("my ").strip()
        if word in _SPEAKER_PRONOUNS:
            continue
        tense = match.group("tense").lower()
        return {
            "speaker": "pronoun" if word in _THIRD_PERSON_PRONOUNS else "named",
            "who": who,
            "present": now_word and tense in _PRESENT_TENSES,
        }
    for match in _CURRENTLY_AGE_RE.finditer(body):
        if _same_age(match.group(1), age):
            return {"speaker": "pronoun", "who": "", "present": True}
    return None


def from_present_age(captured: object) -> DateRecord | None:
    """An age held NOW, told on ``captured``: the moment is the telling's own
    MONTH (basis ``stated``). *"Charlee is 15 and a half right now"* dates
    the telling, not a year fifteen after anybody's birth; the owner's
    ruling ("almost nothing needs precision of more than a month") sets the
    grain. ``None`` without a readable capture date."""
    day = capture_day(captured)
    if day is None:
        return None
    month = f"{day.year:04d}-{day.month:02d}"
    return DateRecord(
        best=month, earliest=month, latest=month, granularity="month",
        confidence="certain", basis="stated",
        provenance=({
            "claim": PRESENT_AGE_PROVENANCE.format(captured=day.isoformat()),
            "basis": "stated",
            "source": PRESENT_AGE_PROVENANCE_SOURCE,
        },),
    )


PRESENT_AGE_PROVENANCE = "an age held now, told {captured}"
PRESENT_AGE_PROVENANCE_SOURCE = "present_age"


# --------------------------------------------------------------------------
# Counted recency: "six to eight months ago" (v360, owner 2026-09-25)
# --------------------------------------------------------------------------

#: THE RULE. *"Six to eight months ago, the author and James were hanging out
#: every day practicing baseball"* (``msg-969d8348ddfa64be466dc602``) is a
#: placement: two numbers he chose and the day he said them. The months are
#: counted back from the telling's capture date and held at MONTH grain (the
#: owner's "month is enough" ruling). A band is the stretch it names; a single
#: count is that month, widened by a month each side when he hedged it
#: ("about six months ago"). The count is read by :func:`parse_age` — the ONE
#: number reader, which already reads number words and bands ("six to eight",
#: "twenty-one") — so this vocabulary cannot drift from the age one.
N_MONTHS_AGO_IS_COUNTED_BACK_FROM_THE_TELLING = (
    "'N months ago' and 'N to M months ago', in digits or words, are counted "
    "back from the telling's capture date and placed at month grain"
)

_COUNT_WORD = (r"(?:\d{1,2}|(?:" + "|".join(sorted(NUMBER_WORDS, key=len, reverse=True))
               + r")(?:[\s-]+(?:one|two|three|four|five|six|seven|eight|nine)\b)?)")
MONTHS_AGO_RE = re.compile(
    r"\b(?P<hedge>(?:about|around|roughly|maybe|like|probably|approximately)\s+)?"
    r"(?P<count>" + _COUNT_WORD + r"(?:\s*(?:-|–|—|to|or)\s*" + _COUNT_WORD + r")?)"
    r"\s+months?\s+ago\b",
    re.IGNORECASE)

#: A counted-recency placement's provenance clause, under basis ``stated``.
MONTHS_AGO_PROVENANCE = "{cue}, told {captured}"
MONTHS_AGO_PROVENANCE_SOURCE = "months_ago"


def _month_back(day: _date, months: int) -> str:
    total = (day.year * 12 + (day.month - 1)) - months
    year, month = divmod(total, 12)
    return f"{year:04d}-{month + 1:02d}"


def from_months_ago(captured: object, *texts: object) -> DateRecord | None:
    """:data:`N_MONTHS_AGO_IS_COUNTED_BACK_FROM_THE_TELLING`, or ``None``.

    The same two refusals :func:`recency_cue` applies, per text: a text naming
    a four-digit year dates itself (:data:`YEAR_RE`), and the idioms of
    :data:`RECENCY_VETO_RES` say the opposite of recency. A count above 60
    months is not recency and reads nothing.
    """
    day = capture_day(captured)
    if day is None:
        return None
    for text in texts:
        if not isinstance(text, str) or not text.strip() or YEAR_RE.search(text):
            continue
        if any(veto.search(text) for veto in RECENCY_VETO_RES):
            continue
        match = MONTHS_AGO_RE.search(text)
        if match is None:
            continue
        parsed = parse_age(match.group("count"))
        if parsed is None:
            continue
        low, high, hedged = parsed
        hedged = hedged or bool(match.group("hedge"))
        if high > 60 or low < 0:
            continue
        widen = 1 if low == high and hedged else 0
        earliest = _month_back(day, high + widen)
        latest = _month_back(day, max(low - widen, 0))
        best = earliest if earliest == latest else f"{earliest}/{latest}"
        cue = " ".join(match.group(0).split()).lower()
        return DateRecord(
            best=best, earliest=earliest, latest=latest,
            granularity="month" if earliest == latest else "range",
            confidence="approximate", basis="stated",
            provenance=({
                "claim": MONTHS_AGO_PROVENANCE.format(cue=cue, captured=day.isoformat()),
                "basis": "stated",
                "source": MONTHS_AGO_PROVENANCE_SOURCE,
            },),
        )
    return None


# --------------------------------------------------------------------------
# School grades: "middle of sixth grade for James" (v360, owner 2026-09-25)
# --------------------------------------------------------------------------

#: THE RULE. A school GRADE is an age on the school calendar. *"This happened
#: in the middle of sixth grade for James"* (``msg-3737a80061e5fd4938204b9b``)
#: names a grade and whose grade it is, and the vault knows that person's
#: birth: the US school year (:func:`school_year_start` — kindergarten the
#: August after the child turns five on or before 1 September, the convention
#: the owner's places follow) turns the two into a school year, August to June.
#: *"Middle of"* is that year's winter months (December to February), *"start
#: of"* its first three months, *"end of"* its last three, at month grain.
#: ONE definition, read by every seat: the resolver's grade table
#: (`resolver.grade_table`), the card-answer seat (`answer_placement`) and the
#: classifier seat (`classifier_claims.temporal_reading`) all call
#: :func:`school_grade_of`, and the fold measures the claim against its
#: SUBJECT's birth in the one seat that measures ages
#: (`temporal_timeline._record_for_age_claim` -> :func:`school_year_record`).
A_SCHOOL_GRADE_IS_AN_AGE_ON_THE_SCHOOL_CALENDAR = (
    "a school grade said of a person is that person's school year, measured "
    "from their birth on the US school calendar; 'middle of' is its winter "
    "months, at month grain"
)

#: Grade 0 is kindergarten; 1..12 are the numbered grades.
GRADE_NAMES = ("kindergarten",) + tuple(
    f"{n}{'st' if n == 1 else 'nd' if n == 2 else 'rd' if n == 3 else 'th'} grade"
    for n in range(1, 13))
_ORDINAL_WORDS = {
    "first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5, "sixth": 6,
    "seventh": 7, "eighth": 8, "ninth": 9, "tenth": 10, "eleventh": 11, "twelfth": 12,
}
#: High-school year names; "junior HIGH" is a school, never a grade.
_CLASS_YEAR_GRADES = {"freshman": 9, "sophomore": 10, "junior": 11, "senior": 12}
#: A part of the school year, as ``(first month offset, last month offset)``
#: from the August the year starts (0 = August, 10 = June).
GRADE_PARTS = {"start": (0, 2), "middle": (4, 6), "end": (8, 10)}
_PART_WORDS = {"beginning": "start", "start": "start", "early": "start",
               "middle": "middle", "mid": "middle", "end": "end", "late": "end"}
_GRADE_ORDINAL = (r"(?:" + "|".join(sorted(_ORDINAL_WORDS, key=len, reverse=True))
                  + r"|\d{1,2}(?:st|nd|rd|th))")
_GRADE_JOIN = r"\s*(?:or|and|to|through|thru|-|–|—|/)\s*"
_CLASS_YEAR = r"(?:freshman|sophomore|junior|senior)"
SCHOOL_GRADE_RE = re.compile(
    r"\b(?:(?:the\s+)?(?P<part>beginning|start|early|middle|mid|end|late)"
    r"(?:\s+part)?(?:\s+of|-)?\s+(?:the\s+|his\s+|her\s+|my\s+|their\s+|our\s+)?)?"
    r"(?:(?P<ordinal>" + _GRADE_ORDINAL + r")(?:" + _GRADE_JOIN + r"(?P<ordinal_high>"
    + _GRADE_ORDINAL + r"))?[\s-]+grade(?:r|s)?"
    r"|grades?\s+(?P<number>\d{1,2})(?:" + _GRADE_JOIN + r"(?P<number_high>\d{1,2}))?\b"
    r"|(?P<class_year>" + _CLASS_YEAR + r")(?:" + _GRADE_JOIN + r"(?P<class_year_high>"
    + _CLASS_YEAR + r"))?\s+years?"
    r"|(?P<kindergarten>kindergarten))\b",
    re.IGNORECASE)
_NOT_SCHOOL_AFTER_RE = re.compile(
    r"^\W{0,3}(?:(?:of|in|at)\s+(?:college|university|uni|grad(?:uate)?\s+school|law\s+school|"
    r"med(?:ical)?\s+school)|(?:in|at)\s+[A-Z][\w.]*\s+(?:University|College))",
    re.IGNORECASE)
_GRADE_FOR_RE = re.compile(r"^\s*(?:for|of)\s+(?P<who>(?:my\s+)?[A-Z][\w’'-]*)")
_GRADE_POSSESSIVE_RE = re.compile(r"(?P<who>\b[A-Z][\w-]*)['’]s\s*$")
_GRADE_WAS_IN_RE = re.compile(
    r"(?P<who>\b[A-Za-z][\w’'-]*)\s+(?:was|were|is|am|['’]m)\s+"
    r"(?:(?:probably|maybe|about|around|like|only|just|still|already|in\s+about)\s+)*"
    r"in\s*(?:the\s+)?$", re.IGNORECASE)
_GRADE_MY_RE = re.compile(r"\bmy\s*$", re.IGNORECASE)
#: The words a classifier writes for the owner himself.
_NARRATOR_WORDS = frozenset({"narrator", "author", "speaker", "owner", "self"})


def _grade_number(word: object) -> int | None:
    text = str(word or "").lower()
    if not text:
        return None
    if text in _CLASS_YEAR_GRADES:
        return _CLASS_YEAR_GRADES[text]
    if text in _ORDINAL_WORDS:
        return _ORDINAL_WORDS[text]
    match = re.match(r"\d+", text)
    return int(match.group(0)) if match else None


def school_year_start(birth_date: object) -> int | None:
    """The calendar year a person born on ``birth_date`` starts kindergarten
    (August), or ``None`` without a readable birth. Born on or before 1
    September -> the year they turn five; later -> the year after."""
    record = birth_date if isinstance(birth_date, DateRecord) else (
        from_dict(birth_date) if isinstance(birth_date, dict) else None)
    text = str((record.earliest or record.best) if record is not None else (birth_date or "")).strip()
    match = re.match(r"^(\d{4})-(\d{2})(?:-(\d{2}))?", text)
    if not match:
        return None
    year, month, day = int(match.group(1)), int(match.group(2)), int(match.group(3) or 1)
    return year + 5 if (month, day) <= (9, 1) else year + 6


def school_grade_of(text: object) -> dict | None:
    """The first school grade ``text`` names, or ``None``.

    ``{"grade": 0..12, "part": "start"|"middle"|"end"|None, "phrase": <words>,
    "speaker": "narrator"|"named"|None, "who": <as written>}``. ``speaker`` is
    whose grade the words say: *"for James"*, *"James's sixth grade"*, *"when
    James was in sixth grade"* name a person; *"I was in"*, *"my sixth grade"*
    are the narrator; ``None`` leaves it to the claim's own subject.

    Refused: a text naming a four-digit year (it dates itself — the
    :data:`YEAR_RE` trap every recency and age reader keeps), and a class-year
    word about college (*"freshman year of college"*).
    """
    body = " ".join(str(text or "").split())
    if not body or YEAR_RE.search(body):
        return None
    for match in SCHOOL_GRADE_RE.finditer(body):
        after = body[match.end():]
        if _NOT_SCHOOL_AFTER_RE.search(after):
            continue
        if match.group("kindergarten"):
            grade, high = 0, None
        elif match.group("class_year"):
            grade, high = (_grade_number(match.group("class_year")),
                           _grade_number(match.group("class_year_high")))
        elif match.group("number"):
            grade, high = (_grade_number(match.group("number")),
                           _grade_number(match.group("number_high")))
        else:
            grade, high = (_grade_number(match.group("ordinal")),
                           _grade_number(match.group("ordinal_high")))
        if grade is None or not 0 <= grade <= 12:
            continue
        if high is not None and not grade < high <= 12:
            high = None
        part = _PART_WORDS.get((match.group("part") or "").lower())
        before = body[:match.start()]
        speaker, who = None, ""
        found = _GRADE_FOR_RE.match(after)
        if found is None:
            found = _GRADE_POSSESSIVE_RE.search(before)
        if found is None:
            found = _GRADE_WAS_IN_RE.search(before)
        if found is not None:
            who = found.group("who")
            word = who.lower().removeprefix("my ").strip()
            if word in _SPEAKER_PRONOUNS or word in _NARRATOR_WORDS:
                speaker, who = "narrator", "I"
            elif word in _THIRD_PERSON_PRONOUNS:
                speaker, who = None, ""
            else:
                speaker = "named"
        elif _GRADE_MY_RE.search(before):
            speaker, who = "narrator", "I"
        return {"grade": grade, "grade_high": high, "part": None if high else part,
                "phrase": " ".join(match.group(0).split()),
                "speaker": speaker, "who": who}
    return None


def school_grade_quantity(found: object) -> dict | None:
    """:func:`school_grade_of`'s reading as an ``age`` claim's value: the ages
    a child is during that grade (a band, approximate) carrying the grade, so
    the fold measures it on the school calendar (:func:`school_year_record`)."""
    row = found if isinstance(found, dict) else {}
    grade = row.get("grade")
    if not isinstance(grade, int) or not 0 <= grade <= 12:
        return None
    high = row.get("grade_high")
    high = high if isinstance(high, int) and grade < high <= 12 else None
    value = {"kind": "age", "low": float(grade + 5), "high": float((high or grade) + 6),
             "unit": "years", "approximate": True, "grade": grade,
             "text": collapsed_phrase(row.get("phrase"))}
    if high is not None:
        value["grade_high"] = high
    elif row.get("part") in GRADE_PARTS:
        value["grade_part"] = row["part"]
    return value


def collapsed_phrase(text: object) -> str:
    return " ".join(str(text or "").split())


def school_year_record(birth_date: object, grade: object, *, part: object = None,
                       grade_high: object = None,
                       claim: str | None = None) -> DateRecord | None:
    """:data:`A_SCHOOL_GRADE_IS_AN_AGE_ON_THE_SCHOOL_CALENDAR`'s arithmetic.

    Birth + grade -> that school year (August to June), or the part of it
    ``part`` names, at month grain, basis ``age`` (it is birthday arithmetic)
    and ``approximate`` (a school calendar is a convention, not a record).
    """
    start = school_year_start(birth_date)
    try:
        index = int(grade)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    if start is None or not 0 <= index <= 12:
        return None
    try:
        top = int(grade_high) if grade_high is not None else index  # type: ignore[arg-type]
    except (TypeError, ValueError):
        top = index
    if not index <= top <= 12:
        top = index
    first, last = GRADE_PARTS.get(str(part or ""), (0, 10)) if top == index else (0, 10)
    year = start + index

    def month(at_year: int, offset: int) -> str:
        total = at_year * 12 + 7 + offset  # August is month index 7
        return f"{total // 12:04d}-{total % 12 + 1:02d}"

    earliest, latest = month(year, first), month(start + top, last)
    said = collapsed_phrase(claim) or GRADE_NAMES[index]
    named = (GRADE_NAMES[index] if top == index
             else f"{GRADE_NAMES[index]} to {GRADE_NAMES[top]}")
    return DateRecord(
        best=f"{earliest}/{latest}", earliest=earliest, latest=latest,
        granularity="range", confidence="approximate", basis="age",
        provenance=({
            "claim": (f"calculated from “{said}” on the US school year "
                      f"({named}, {year}-08 to {start + top + 1}-06)"),
            "basis": CALCULATED_PROVENANCE_BASIS,
        },),
    )


def grade_table_lines(birth_date: object) -> list[str]:
    """``"2nd grade -> 2020-08 to 2021-06"`` for a whole US school career —
    the resolver's grade table, read off :func:`school_year_start` so the
    table and the fold cannot disagree about a school year."""
    start = school_year_start(birth_date)
    if start is None:
        return []
    names = list(GRADE_NAMES)
    for grade, word in ((9, "freshman"), (10, "sophomore"), (11, "junior"), (12, "senior")):
        names[grade] += f" ({word})"
    return [f"{name} -> {start + n}-08 to {start + n + 1}-06" for n, name in enumerate(names)]


def _age_band(low: object, high: object) -> tuple[int, int] | None:
    """``(min_age, max_age)`` when the pair is a band :func:`parse_age` could
    itself have produced — whole years, ``0..120``, low end first. Anything
    else is ``None``: a band no phrase could have asserted gets no interval.
    """
    try:
        lo, hi = float(low), float(high)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    if not (math.isfinite(lo) and math.isfinite(hi)):
        return None
    if lo != int(lo) or hi != int(hi) or lo < 0 or hi > 120 or hi < lo:
        return None
    return int(lo), int(hi)


def from_age_band(birth_date: object, low: object, high: object, *,
                  approximate: bool = False, claim: str | None = None) -> DateRecord | None:
    """Birthday + a stored age BAND → a dated interval (basis ``age``).

    The same one rule as :func:`from_age`, entered from the other end.
    :func:`from_age` takes the *phrase*, because the phrase is what a person
    asserted; a stored quantity (``temporal_claims.TemporalQuantity``) has
    already been through :func:`parse_age` and kept the band, and it enters
    HERE. The alternative — rebuilding a phrase from the band and hoping it
    re-parses — is a second age rule wearing a disguise, and the package has
    one age rule (recurring-defect doctrine).

    Someone who is age *a* occupies ``[birthday_a, birthday_(a+1))`` — the
    span from the birthday on which they turned *a* up to (not including) the
    birthday on which they turn *a + 1*. When the birth record only carries a
    YEAR (or a month), that span is approximated at year grain —
    ``[birth_year + a, birth_year + a + 1]`` — because there is no day to
    build a calendar span from. But when the birth record carries day
    precision, the year-only approximation is wrong in a way that matters: it
    can straddle a later frame boundary that the true, day-precise span never
    crosses (a person born 1981-07-11 who is "39" is entirely within
    2020-07-11..2021-07-10, never touching 2021-07-11 onward, but the
    year-only arithmetic reports 2020..2021 as if it might). So a day-precise
    birth computes the span by calendar arithmetic on the birthday itself,
    via :func:`add_years` — the package's other, grain-preserving age
    arithmetic — rather than by year subtraction. A month-only birth keeps
    the year-level approximation: a month cannot anchor a day-precise span
    any more than a bare year can, and the extra complexity of a month-grain
    span buys nothing no caller needs today.

    An ``approximate`` band is a rounded one, so it widens by a year on each
    side (Huttenlocher, Hedges & Bradburn 1990); a band spanning two ages
    takes the union before widening. The widened (or day-precise) earliest
    bound is never allowed before the birth itself. The band's own domain is
    :func:`parse_age`'s (see :func:`_age_band`), so a band that parser could
    never have produced comes back ``None`` rather than an invented interval.
    """
    birth = _as_record(birth_date)
    if birth is None:
        return None
    birth_year = year_of(birth)
    if birth_year is None:
        return None
    band = _age_band(low, high)
    if band is None:
        return None
    min_age, max_age = band

    day_precise = (
        birth.granularity == "day"
        and bool(birth.earliest)
        and len(str(birth.earliest).split("-")) == 3
    )
    earliest_token: str | None = None
    latest_token: str | None = None
    extra_provenance: tuple[dict, ...] = ()
    if day_precise:
        turned_min = add_years(birth, min_age)
        turned_next = add_years(birth, max_age + 1)
        if turned_min is None or turned_next is None or not (
            turned_min.earliest and turned_next.earliest
        ):
            day_precise = False
        else:
            earliest_token = turned_min.earliest
            latest_token = day_before(turned_next.earliest)
            if latest_token is None:
                day_precise = False
            else:
                for rec in (turned_min, turned_next):
                    for prov in rec.provenance:
                        if prov not in extra_provenance:
                            extra_provenance += (prov,)
                if approximate:
                    shifted_lo, hit_lo = _shift_iso(earliest_token, -1)
                    shifted_hi, hit_hi = _shift_iso(latest_token, 1)
                    if shifted_lo is not None:
                        earliest_token = shifted_lo
                    if shifted_hi is not None:
                        latest_token = shifted_hi
                    if (hit_lo or hit_hi) and not any(
                        prov.get("source") == AGE_FRAME_CLAMP_RULE for prov in extra_provenance
                    ):
                        extra_provenance += (
                            {"claim": _CLAMP_CLAIM, "basis": "age", "source": AGE_FRAME_CLAMP_RULE},
                        )
                if earliest_token < birth.earliest:
                    earliest_token = birth.earliest

    provenance = ({"claim": claim, "basis": "age"},) if claim else ()
    provenance = provenance + extra_provenance

    if day_precise and earliest_token is not None and latest_token is not None:
        lo_year = int(earliest_token[:4])
        hi_year = int(latest_token[:4])
        mid = (lo_year + hi_year) // 2
        return DateRecord(
            best=f"{mid}~",
            earliest=earliest_token,
            latest=latest_token,
            granularity="year" if earliest_token == latest_token else "range",
            confidence="approximate" if approximate else "inferred",
            basis="age",
            anchors=("birth",),
            provenance=provenance,
        )

    lo = birth_year + min_age
    hi = birth_year + max_age + 1
    if approximate:
        lo -= 1
        hi += 1
    lo = max(lo, birth_year)
    mid = (lo + hi) // 2
    return DateRecord(
        best=f"{mid}~",
        earliest=str(lo),
        latest=str(hi),
        granularity="year" if lo == hi else "range",
        confidence="approximate" if approximate else "inferred",
        basis="age",
        anchors=("birth",),
        provenance=provenance,
    )


#: The finest grain an AGE is said at. Owner, 2026-09-25: *"If I say 19-21 you
#: can say the start of his birth month to the end range of his birth month …
#: I don't care that much about days."* An age names a year of somebody's life,
#: and the birthday's MONTH is the finest edge that year honestly has — so a
#: day-precise birth still gives a month-grained window, never a day-exact one.
AGE_STATEMENT_GRAIN = "month"


def at_grain(record: object, grain: str) -> DateRecord | None:
    """``record`` with each bound rounded OUTWARD to ``grain``. Only ever widens.

    ``1973-06-04/1976-06-03`` at ``month`` is ``1973-06/1976-06``: truncation
    (:func:`_truncate_iso`), which reads as the 1st of the month for an
    ``earliest`` bound and the last day for a ``latest`` one, so the result
    always CONTAINS the input. A bound already at or coarser than ``grain`` is
    kept as it is, and a record with nothing to round comes back unchanged
    (the same object). ``best`` is re-derived only when it named the old
    bounds as an interval; a hedged point (``1974~``) is left alone, because
    it is the reading a person recognises and rounding the bounds does not
    move it.
    """
    parsed = _as_record(record)
    if parsed is None or grain not in ("day", "month", "year"):
        return parsed

    def rounded(token: str | None) -> str | None:
        if not token or len(str(token).split("-")) != 3:
            return token
        return _truncate_iso(token, grain)

    earliest, latest = rounded(parsed.earliest), rounded(parsed.latest)
    if (earliest, latest) == (parsed.earliest, parsed.latest):
        return parsed
    best = parsed.best
    if best and "/" in best and best == f"{parsed.earliest or '..'}/{parsed.latest or '..'}":
        best = f"{earliest or '..'}/{latest or '..'}"
    granularity = parsed.granularity
    if granularity == "day":
        granularity = grain if earliest == latest else "range"
    return replace(parsed, best=best, earliest=earliest, latest=latest,
                   granularity=granularity)


def age_statement_record(birth_date: object, low: object, high: object, *,
                         approximate: bool = False,
                         claim: str | None = None) -> DateRecord | None:
    """An age as the person SAID it: :func:`from_age_band` at the age's grain.

    Two things, both the owner's ruling (:data:`AGE_STATEMENT_GRAIN`): the
    bounds are rounded to the birthday's month, and a band said as a band —
    *"19 to 21"*, not *"about 20"* — reads as the stretch it names
    (``1973-06/1976-06``) rather than as its midpoint year (``1974~``). A hedged
    age keeps its hedged point, which is the owner's own example (*"about 5"*
    reads *around 1984*). The arithmetic is :func:`from_age_band`'s and there
    is still one of it; this only decides how finely its answer is held.
    """
    record = from_age_band(birth_date, low, high, approximate=approximate, claim=claim)
    if record is None:
        return None
    record = at_grain(record, AGE_STATEMENT_GRAIN) or record
    band = _age_band(low, high)
    if (not approximate and band is not None and band[0] < band[1]
            and record.earliest and record.latest):
        record = replace(record, best=f"{record.earliest}/{record.latest}",
                         granularity="range")
    return record


def from_age(birth_date: object, age_text: object, *, claim: str | None = None) -> DateRecord | None:
    """Birthday + a stated age → a dated interval (basis ``age``).

    The owner's own example: a birthday plus "about 5" gives ``1984~`` with
    the window the hedge earns. This is the door a *phrase* comes in through:
    :func:`parse_age` reads it — the package's one age parser — and
    :func:`from_age_band` does the arithmetic. The phrase itself is kept as
    the record's provenance, because it is what was actually said.
    """
    parsed = parse_age(age_text)
    if parsed is None:
        return None
    min_age, max_age, hedged = parsed
    return from_age_band(
        birth_date, min_age, max_age, approximate=hedged,
        claim=claim or (str(age_text).strip() or None),
    )


# --------------------------------------------------------------------------
# Anniversaries: the same date, n years later (v-E1, eras design §3.3)
# --------------------------------------------------------------------------

#: The ONE rule name for the 29 February clamp, recorded in a shifted record's
#: provenance whenever it fires. A calendar fact the arithmetic had to invent —
#: there is no 29 February in 1997 — is never allowed to be invisible.
AGE_FRAME_CLAMP_RULE = "age-frame:1"

_CLAMP_CLAIM = "29 February falls on 28 February in a year that has no 29th"

#: A `best` expression's optional EDTF qualifier suffix.
_QUALIFIER_SUFFIX_RE = re.compile(r"^(.*?)([~?%]*)$", re.DOTALL)


def add_years(record: object, years: object) -> DateRecord | None:
    """The same date, ``years`` later — GRAIN PRESERVED (eras design §3.3).

    :func:`from_age_band` is the package's other age arithmetic and it is
    deliberately coarser: it works off ``year_of(birth)`` and discards the
    birth's day and month, which is right for *"when I was about five"* and
    wrong for a frame EDGE. A twentieth birthday is a day when the birthday is
    a day, a month when it is a month, and a decade-wide window when the
    birthday is only known to a decade. This is the one definition of that.

    * ``1981-07-11 + 20 → 2001-07-11`` (day), ``1981-07 + 20 → 2001-07``
      (month), ``1981-22 + 20 → 2001-22`` (season, bounds moved with it),
      ``1981 + 20 → 2001`` (year).
    * **29 February clamps to the 28th** in a target year that has no 29th, and
      the record says so: rule :data:`AGE_FRAME_CLAMP_RULE` is appended to
      ``provenance``. A silent clamp is a date the person never gave and
      nothing on the page could explain.
    * A grain that CANNOT survive the shift widens rather than lying. A decade
      (``197X``, granularity ``era``) moved by an amount that is not a multiple
      of ten is not a decade any more, so both bounds move (``1983``/``1992``)
      and the result is a ``range`` — decade-WIDE, which is the honest reading
      of a decade-grain origin, and never a decade it is not.

    Confidence, basis and anchors ride through untouched: shifting a date by a
    whole number of years neither strengthens nor weakens the warrant it had.
    """
    parsed = _as_record(record)
    if parsed is None:
        return None
    try:
        offset = int(years)
    except (TypeError, ValueError):
        return None

    clamped = False
    bounds: dict[str, str | None] = {}
    for name in ("earliest", "latest"):
        value = getattr(parsed, name)
        if not value:
            bounds[name] = None
            continue
        moved, hit = _shift_iso(value, offset)
        if moved is None:
            return None
        bounds[name] = moved
        clamped = clamped or hit

    best, best_hit, kept_grain = _shift_best(parsed.best, offset)
    clamped = clamped or best_hit
    granularity = parsed.granularity
    if not kept_grain:
        earliest, latest = bounds["earliest"], bounds["latest"]
        if not earliest and not latest:
            return None
        best = earliest if (earliest and earliest == latest) else (
            f"{earliest or '..'}/{latest or '..'}"
        )
        granularity = parsed.granularity if earliest == latest else "range"

    provenance = parsed.provenance
    if clamped:
        provenance = provenance + (
            {"claim": _CLAMP_CLAIM, "basis": parsed.basis, "source": AGE_FRAME_CLAMP_RULE},
        )
    return DateRecord(
        best=best,
        earliest=bounds["earliest"],
        latest=bounds["latest"],
        granularity=granularity,
        confidence=parsed.confidence,
        basis=parsed.basis,
        anchors=parsed.anchors,
        provenance=provenance,
    )


def _shift_iso(token: str, years: int) -> tuple[str | None, bool]:
    """One ISO bound, ``years`` later. Returns ``(token, clamped)``.

    Handles the four bound shapes :func:`_ordinal` accepts — ``YYYY``,
    ``YYYY-MM`` (including the season codes 21–24), ``YYYY-MM-DD`` — and
    clamps 29 February. ``(None, False)`` for anything else, so a caller
    refuses rather than guessing.
    """
    parts = str(token).split("-")
    try:
        year = int(parts[0]) + years
    except (TypeError, ValueError):
        return None, False
    if len(parts) == 1:
        return f"{year:04d}", False
    if not parts[1].isdigit():
        return None, False
    if len(parts) == 2:
        return f"{year:04d}-{parts[1]}", False
    if len(parts) != 3 or not parts[2].isdigit():
        return None, False
    month, day = int(parts[1]), int(parts[2])
    if not (1 <= month <= 12) or not (1 <= day <= 31):
        return None, False
    last = _month_last_day(year, month)
    if day > last:
        return f"{year:04d}-{month:02d}-{last:02d}", True
    return f"{year:04d}-{month:02d}-{day:02d}", False


def _shift_best(best: object, years: int) -> tuple[str | None, bool, bool]:
    """A ``best`` EDTF expression, ``years`` later.

    Returns ``(expression, clamped, kept_grain)``. ``kept_grain`` is False when
    the expression's own grain cannot express the shifted value — a decade
    moved by 13 years — and the caller falls back to the shifted bounds.
    """
    text = str(best or "").strip()
    if not text:
        return None, False, False
    pieces = text.split("/")
    if len(pieces) > 2:
        return None, False, False
    moved: list[str] = []
    clamped = False
    for piece in pieces:
        piece = piece.strip()
        if piece == "..":
            moved.append(piece)
            continue
        match = _QUALIFIER_SUFFIX_RE.match(piece)
        body, qualifier = (match.group(1), match.group(2)) if match else (piece, "")
        shifted = _shift_coarse(body, years)
        if shifted is None:
            shifted, hit = _shift_iso(body, years)
            clamped = clamped or hit
        if shifted is None:
            return None, clamped, False
        moved.append(shifted + qualifier)
    return "/".join(moved), clamped, True


def day_before(token: object) -> str | None:
    """The ISO day before ``YYYY-MM-DD`` — a half-open end, closed.

    ``[2001-07-11, 2011-07-11)`` and ``2001-07-11/2011-07-10`` are the same
    interval said two ways, and the second is the one this module stores. The
    conversion is one line of calendar arithmetic and it lives here, with the
    rest of the calendar, rather than in whichever caller needed it first.
    """
    parts = str(token or "").split("-")
    if len(parts) != 3:
        return None
    try:
        return (_date(int(parts[0]), int(parts[1]), int(parts[2])) - _timedelta(days=1)).isoformat()
    except (TypeError, ValueError):
        return None


def day_after(token: object) -> str | None:
    """The ISO day after ``YYYY-MM-DD`` — an exclusive low bound, closed.

    :func:`day_before` closes a half-open END; this closes a half-open START,
    and the two belong side by side. ``(2001-07-11, …`` and
    ``2001-07-12/…`` are the same interval said two ways.
    """
    parts = str(token or "").split("-")
    if len(parts) != 3:
        return None
    try:
        return (_date(int(parts[0]), int(parts[1]), int(parts[2])) + _timedelta(days=1)).isoformat()
    except (TypeError, ValueError):
        return None


# --------------------------------------------------------------------------
# The birth origin: an age plus a dated event, run backwards (eras §3.2)
# --------------------------------------------------------------------------

#: The ONE rule name for the birth-origin arithmetic, recorded in the
#: provenance of every record it produces. A date nobody stated and the system
#: worked out has to say which rule worked it out.
BIRTH_ORIGIN_RULE = "birth-origin:1"

#: The rule name for the 29 February widening below. Separate from
#: :data:`BIRTH_ORIGIN_RULE` because it fires on a minority of inputs and a
#: person looking at an edge case deserves to see that the edge case is why.
BIRTH_ORIGIN_LEAP_RULE = "birth-origin:leap-day"

_LEAP_CLAIM = (
    "a 29 February birthday keeps its anniversary on the 28th in a year with "
    "no 29th, so the end of February is widened by a day rather than guessed"
)

#: The grain a birth-origin EDGE is expressed at, per the event's own grain.
#: A month-grain event cannot bound a birth to a day and a year-grain event
#: cannot bound it to a month; rounding outward to these is the only direction
#: that can never exclude the true birthday (eras design §3.2, §3.3).
BIRTH_ORIGIN_EDGE_GRAIN = {
    "day": "day", "month": "month", "season": "month",
    "year": "year", "range": "year", "era": "year",
}


def birth_origin_from_age(event: object, age: object, *,
                          claim: str | None = None) -> DateRecord | None:
    """A dated event plus the age someone WAS at it → when they were born.

    :func:`from_age_band` runs this arithmetic forwards and coarsely — it reads
    only ``year_of(birth)``, which is right for placing *"when I was about
    five"* and useless for bounding a birthday. This runs it backwards at the
    event's own grain, and it is the origin of the age frames whenever nobody
    has stated a birthday (eras design §3.2).

    Exact age ``a`` at an event whose instant range is ``[t0, t1]`` puts the
    birth in ``(t0 − (a+1)y, t1 − a·y]`` — open at the low end, because
    somebody born one day earlier would already have had the next birthday.
    Three things widen it and nothing narrows it:

    * an ``approximate`` band widens by a year on each side, the same
      Huttenlocher rounding :func:`from_age_band` applies to its own output;
    * the edges round OUTWARD to the event's grain
      (:data:`BIRTH_ORIGIN_EDGE_GRAIN`) — a year-grain event gives
      *"about 1980–1981"*, never a day in January;
    * rule :data:`BIRTH_ORIGIN_LEAP_RULE`: because ``add_years`` clamps 29
      February to the 28th (rule :data:`AGE_FRAME_CLAMP_RULE`), a 29 February
      birthday ages up a day early in a non-leap year and the exact endpoints
      become calendar-dependent. Both endpoints widen by a day around the end
      of February. Over-including a candidate birthday is a wider interval;
      under-including one is a wrong answer.

    ``basis`` is ``age`` — which is what makes the frames built on this record
    publish ``origin_basis: calculated``, through
    ``temporal_claims.CLAIM_BASIS_BY_DATE_BASIS`` and no second table — and the
    confidence is never firmer than ``inferred`` (:func:`at_most`).

    ``None``, never a guess, for: an unusable event, an event with no bounds,
    a band outside :func:`parse_age`'s own domain, or a quantity in any unit
    but years (a birth origin from *"about eight months"* is a precision this
    has no honest way to express).
    """
    parsed = _as_record(event)
    if parsed is None:
        return None
    quantity = age.to_dict() if hasattr(age, "to_dict") else age
    if not isinstance(quantity, dict):
        return None
    unit = " ".join(str(quantity.get("unit") or "years").split()) or "years"
    if unit != "years":
        return None
    band = _age_band(quantity.get("low"), quantity.get("high"))
    if band is None:
        return None
    min_age, max_age = band
    if bool(quantity.get("approximate")):
        min_age, max_age = max(min_age - 1, 0), max_age + 1

    grain = BIRTH_ORIGIN_EDGE_GRAIN.get(parsed.granularity, "year")
    low_ordinal = _ordinal(parsed.earliest, end=False)
    high_ordinal = _ordinal(parsed.latest, end=True)
    if low_ordinal is None and high_ordinal is None:
        return None

    leap_widened = False
    earliest: str | None = None
    if low_ordinal is not None:
        shifted, _clamped = _shift_iso(_iso_day(low_ordinal), -(max_age + 1))
        if shifted is None:
            return None
        if _is_late_february(shifted):
            # The exclusive bound's own day stays IN: whether a birthday on it
            # counts depends on the target year's calendar (see the rule).
            leap_widened = True
        else:
            shifted = day_after(shifted)
        earliest = _truncate_iso(shifted, grain)
    latest: str | None = None
    if high_ordinal is not None:
        shifted, _clamped = _shift_iso(_iso_day(high_ordinal), -min_age)
        if shifted is None:
            return None
        extended = _extend_through_leap_day(shifted)
        if extended != shifted:
            leap_widened = True
        latest = _truncate_iso(extended, grain)
    if earliest is None and latest is None:
        return None

    granularity = grain if earliest == latest else "range"
    best = earliest if (earliest and earliest == latest) else (
        f"{earliest or '..'}/{latest or '..'}"
    )
    phrase = _prov_text(claim) or _prov_text(quantity.get("text"))
    said = f"age {min_age}" if min_age == max_age else f"age {min_age}\u2013{max_age}"
    entries: list[dict] = [
        {"claim": phrase or f"{said} at a dated event",
         "basis": "age", "source": BIRTH_ORIGIN_RULE}
    ]
    if leap_widened:
        entries.append({"claim": _LEAP_CLAIM, "basis": "age",
                        "source": BIRTH_ORIGIN_LEAP_RULE})
    return DateRecord(
        best=best,
        earliest=earliest,
        latest=latest,
        granularity=granularity,
        confidence=at_most(parsed.confidence, "inferred"),
        basis="age",
        anchors=parsed.anchors,
        provenance=parsed.provenance + tuple(entries),
    )


def _prov_text(value: object) -> str:
    """A provenance phrase, whitespace-collapsed; ``""`` for anything else."""
    if not isinstance(value, str):
        return ""
    return " ".join(value.split())


def _iso_day(ordinal: tuple[int, int, int]) -> str:
    return "{:04d}-{:02d}-{:02d}".format(*ordinal)


def _is_late_february(token: str) -> bool:
    """Is this ISO day 28 or 29 February? — the calendar-dependent boundary."""
    parts = str(token or "").split("-")
    return len(parts) == 3 and parts[1] == "02" and parts[2] in ("28", "29")


def _extend_through_leap_day(token: str) -> str:
    """28 February of a leap year reaches the 29th (rule ``birth-origin:leap-day``)."""
    parts = str(token or "").split("-")
    if len(parts) != 3 or parts[1] != "02" or parts[2] != "28":
        return token
    try:
        year = int(parts[0])
    except (TypeError, ValueError):
        return token
    return f"{year:04d}-02-29" if _month_last_day(year, 2) == 29 else token


def _truncate_iso(token: object, grain: str) -> str | None:
    """An ISO day rounded OUTWARD to ``grain``: truncation, which only widens.

    As an ``earliest`` bound ``1980-06`` reads as 1 June and as a ``latest``
    bound it reads as the 30th (:func:`_ordinal`), so dropping the finer
    components moves each bound away from the middle in both cases.
    """
    parts = str(token or "").split("-")
    if len(parts) != 3:
        return None
    if grain == "day":
        return "-".join(parts)
    if grain == "month":
        return "-".join(parts[:2])
    return parts[0]


def _shift_coarse(body: str, years: int) -> str | None:
    """A decade (``197X``) or century (``19XX``), when the shift keeps it one."""
    decade = _DECADE_RE.match(body)
    if decade:
        if years % 10:
            return None
        return f"{(int(decade.group(1)) * 10 + years) // 10:03d}X"
    century = _CENTURY_RE.match(body)
    if century:
        if years % 100:
            return None
        return f"{(int(century.group(1)) * 100 + years) // 100:02d}XX"
    return None


# --------------------------------------------------------------------------
# Durations: a span's far end, once something says where it began
# --------------------------------------------------------------------------

#: Days in a mean Gregorian year — the constant the unit conversions lean on,
#: and the reason a duration in weeks or days still lands on a whole number of
#: years rather than a precision it never had.
DAYS_PER_YEAR = 365.2425

#: How many of each unit make one year. The keys are exactly
#: ``temporal_claims.QUANTITY_UNITS`` (a test pins the two together); an
#: unrecognized unit converts to ``None``, never to a guess.
DURATION_UNITS_PER_YEAR = {
    "years": 1.0,
    "months": 12.0,
    "weeks": DAYS_PER_YEAR / 7.0,
    "days": DAYS_PER_YEAR,
}


def duration_years_band(quantity: object) -> tuple[int, int] | None:
    """A duration in any known unit as a whole-year band, rounded OUTWARD.

    *"We lived there three years"* bounds a span; *"about eight months"*
    bounds it to within a year. Outward is the only honest direction: a unit
    conversion may WIDEN a duration and may never tighten one, so the low end
    floors and the high end ceils, and an ``approximate`` quantity first
    widens by one of its own units on each side.

    Takes the stored quantity mapping (``temporal_claims.TemporalQuantity``'s
    ``to_dict``, or the object itself). ``None`` for an unknown unit or for a
    pair that is not a band.
    """
    if hasattr(quantity, "to_dict"):
        quantity = quantity.to_dict()
    if not isinstance(quantity, dict):
        return None
    unit = " ".join(str(quantity.get("unit") or "years").split()) or "years"
    divisor = DURATION_UNITS_PER_YEAR.get(unit)
    if divisor is None:
        return None
    try:
        low, high = float(quantity.get("low")), float(quantity.get("high"))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    if not (math.isfinite(low) and math.isfinite(high)) or low < 0 or high < low:
        return None
    if bool(quantity.get("approximate")):
        low, high = max(low - 1, 0.0), high + 1
    return math.floor(low / divisor), math.ceil(high / divisor)


def from_duration(start_date: object, quantity: object, *,
                  claim: str | None = None) -> DateRecord | None:
    """A start bound + a stated duration → the span it closes (basis ``anchor``).

    A duration says nothing at all until something says when the span began:
    *"we lived there three years"* is not a date. Given a start it says where
    the span ENDS, and the result is an interval rather than a date because an
    interval is what was asserted.

    The far end moves out from the start by the high end of
    :func:`duration_years_band` — outward-rounded, so the span is never
    shorter than what was said — while the near end stays where the start put
    it. Confidence follows :func:`at_most`: never firmer than the start's, and
    never better than ``inferred``, because this end was calculated.
    """
    start = _as_record(start_date)
    if start is None:
        return None
    band = duration_years_band(quantity)
    if band is None:
        return None
    start_year = year_of(start)
    if start_year is None:
        return None
    earliest = start.earliest or str(start_year)
    latest = str(start_year + band[1])
    return DateRecord(
        best=f"{earliest}/{latest}",
        earliest=earliest,
        latest=latest,
        granularity="range",
        confidence=at_most(start.confidence, "inferred"),
        basis="anchor",
        anchors=start.anchors,
        provenance=start.provenance + (({"claim": claim, "basis": "anchor"},) if claim else ()),
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
                      granularity=grain, confidence=at_most(anchor.confidence, "inferred"),
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
    confidence = at_most(parsed.confidence, "inferred")
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


def claim_identity(record: object) -> tuple[str, str] | None:
    """``(edtf, basis)`` — WHICH claim this is, for folding corroboration.

    Two records saying the same interval on the same basis are ONE claim told
    twice, not two rival claims: the second telling is corroboration, and
    :func:`claim_score` already counts distinct provenance ``source`` values as
    consilience. Anchors and confidence are deliberately NOT part of the
    identity — they are how well the one claim is held, not which claim it is.
    """
    parsed = _as_record(record)
    if parsed is None:
        return None
    return (to_edtf(parsed) or "", parsed.basis)


def merge_claims(claims: object) -> list[DateRecord]:
    """Fold repeat tellings of the SAME claim into one, in first-seen order.

    The fold :func:`reconcile` wants in front of it, and the reason a landmark
    entry re-filed twenty times does not accumulate twenty alternates. Same
    :func:`claim_identity` → one record, its anchors unioned and its
    provenance unioned (duplicate provenance entries collapse, so re-filing
    the identical record is a no-op and cannot manufacture consilience).
    """
    folded: dict[tuple[str, str], DateRecord] = {}
    for claim in (claims or ()):
        parsed = _as_record(claim)
        if parsed is None:
            continue
        key = claim_identity(parsed)
        if key is None:
            continue
        prior = folded.get(key)
        if prior is None:
            folded[key] = parsed
            continue
        anchors = prior.anchors + tuple(a for a in parsed.anchors if a not in prior.anchors)
        seen = [json.dumps(item, sort_keys=True, default=str) for item in prior.provenance]
        provenance = prior.provenance
        for item in parsed.provenance:
            if json.dumps(item, sort_keys=True, default=str) not in seen:
                provenance += (item,)
                seen.append(json.dumps(item, sort_keys=True, default=str))
        confidence = min((prior.confidence, parsed.confidence), key=CONFIDENCES.index)
        folded[key] = replace(prior, anchors=anchors, provenance=provenance,
                              confidence=confidence)
    return list(folded.values())


def conflict_strength(best: object, alternates: object) -> float:
    """How hard the surviving claims CONTRADICT the winner, in ``0.0``–``1.0``.

    An alternate that merely bounds the winner more loosely (``1984`` beside
    ``1980/1990``) is not a conflict — it INTERSECTS, which is corroboration
    at a coarser grain. A conflict is an alternate that cannot be true at the
    same time as the winner, and its strength is how well supported that rival
    is relative to the winner: ``1.0`` is a dead tie between two claims that
    cannot both be right, and ``0.0`` is "no surviving claim contradicts this".

    Derived, never stored — a caller holding the claim list can always ask.
    """
    winner = _as_record(best)
    if winner is None:
        return 0.0
    top = claim_score(winner)
    if top <= 0:
        return 0.0
    rivals = [r for r in (_as_record(a) for a in (alternates or ())) if r is not None]
    disputed = [r for r in rivals if intersect(winner, r) is None]
    if not disputed:
        return 0.0
    return min(1.0, max(claim_score(r) for r in disputed) / top)


def reconcile(claims: object) -> dict:
    """``{"best_supported", "alternates", "conflict"}`` — ruling 3.

    Historians corroborate and prefer convergence from independent origins;
    oral historians (Portelli) treat the disagreement itself as data. So this
    function **never drops a claim**: every usable input comes back either as
    ``best_supported`` or in ``alternates``, in score order, ties broken
    deterministically by EDTF text and then insertion order. Nothing is
    overwritten, and no AI-side silent pick is possible — the caller renders
    the best-supported interval and links the alternates.

    Repeat tellings of one claim are folded first (:func:`merge_claims`), so
    the alternates are RIVALS rather than echoes, and ``conflict`` says how
    hard the surviving rivals contradict the winner
    (:func:`conflict_strength`) — the number a caller needs to decide whether
    to show the disagreement or simply date the thing.

    Order is score, then GRAIN, then EDTF text, then insertion. Grain is in
    there because a REFINEMENT is not a rival: "June 14th, 2001" beside
    "2001" is the same claim said better, and on equal support the finer one
    is the answer. Without that rung the two tie on score and break on text,
    where ``"2001"`` sorts before ``"2001-06-14"`` and the day the person
    just gave you loses to the year they gave you last month.
    """
    parsed = merge_claims(claims)
    if not parsed:
        return {"best_supported": None, "alternates": [], "conflict": 0.0}
    ordered = sorted(
        enumerate(parsed),
        key=lambda pair: (-claim_score(pair[1]),
                          GRANULARITIES.index(pair[1].granularity),
                          to_edtf(pair[1]) or "", pair[0]),
    )
    records = [record for _, record in ordered]
    return {
        "best_supported": records[0],
        "alternates": records[1:],
        "conflict": conflict_strength(records[0], records[1:]),
    }


# --------------------------------------------------------------------------
# Carriage: a record survives the trip through an argv (B4, lifehug#233)
# --------------------------------------------------------------------------
#
# A date is only as good as its BASIS, and until v222 the basis never left the
# package: `landmarks_interaction.landmark_invocation` serialized the EDTF
# expression alone and `lifehug.py landmark-record` rebuilt every record with
# `basis="stated"`. A date the system CALCULATED from an age therefore reached
# the vault claiming the person had stated it — worth +2.0 of `claim_score`
# it had not earned, and enough to beat a genuinely stated rival. These two
# functions are the one definition of how a `DateRecord` crosses a process
# boundary, so the two halves can never drift apart again.

#: The record's fields an EDTF expression CANNOT carry, in flag order.
#: `granularity` and `confidence` are in here for the same reason `basis` is:
#: `to_edtf` renders the interval and nothing else, so an `approximate` claim
#: rebuilt from its own expression comes back `certain` — worth another +1.0
#: of `claim_score` on top of the basis's +2.0. `anchors` and `provenance` are
#: the repeatable ones. PUBLIC so a caller can ask what carriage covers.
WARRANT_FIELDS = ("basis", "granularity", "confidence", "anchors", "provenance")

#: The closed vocabulary each single-valued warrant flag is checked against —
#: one lookup, so no caller re-lists the values (recurring-defect doctrine).
WARRANT_VOCABULARIES = {
    "basis": BASES,
    "granularity": GRANULARITIES,
    "confidence": CONFIDENCES,
}


def date_flag_names(meta_prefix: str = "") -> dict:
    """The warrant flag names under one bound prefix.

    ``""`` for `--date`; ``start-``/``end-`` for the two ends of a span, which
    are two SEPARATE claims ("we moved in when I was five", "we moved out in
    1991") and are rarely dated the same way. PUBLIC so the CLI's parser and
    the invocation builder read the SAME strings and can never drift.
    """
    prefix = str(meta_prefix or "")
    names = {name: f"--{prefix}{name}" for name in ("basis", "granularity", "confidence")}
    names["anchor"] = f"--{prefix}anchor"
    names["provenance"] = f"--{prefix}provenance"
    return names


def provenance_arg(item: object) -> str | None:
    """One provenance entry as the compact JSON a flag can carry."""
    if not isinstance(item, dict) or not item:
        return None
    try:
        return json.dumps(item, sort_keys=True, separators=(",", ":"), default=str)
    except (TypeError, ValueError):
        return None


def parse_provenance_arg(text: object) -> dict:
    """The inverse of :func:`provenance_arg`; raises on anything unusable.

    Loud, not degrading: a provenance entry that does not survive the trip is
    evidence that has silently gone missing, and silently-missing evidence is
    the whole defect this section exists to close.
    """
    if isinstance(text, dict):
        return dict(text)
    if not isinstance(text, str) or not text.strip():
        raise ChronologyError("a provenance entry cannot be empty")
    try:
        value = json.loads(text)
    except (TypeError, ValueError) as exc:
        raise ChronologyError(f"unreadable provenance {text!r}") from exc
    if not isinstance(value, dict) or not value:
        raise ChronologyError(f"a provenance entry must be an object: {text!r}")
    return value


def date_argv(record: object, *, value_flag: str, meta_prefix: str = "") -> list[str]:
    """The argv fragment that carries ONE record whole — value AND warrant.

    ``value_flag`` is where the EDTF expression goes (``--date``, ``--start``,
    ``--end``); ``meta_prefix`` namespaces the three warrant flags so the two
    ends of a span each keep their own basis (they are separate claims —
    "we moved in when I was five" and "we moved out in 1991").

    Empty when there is no readable date: a warrant with nothing to warrant is
    not a fragment worth emitting.
    """
    parsed = _as_record(record)
    edtf = to_edtf(parsed) if parsed is not None else None
    if parsed is None or not edtf:
        return []
    names = date_flag_names(meta_prefix)
    argv = [str(value_flag), edtf]
    for name in ("basis", "granularity", "confidence"):
        argv += [names[name], getattr(parsed, name)]
    for anchor in parsed.anchors:
        argv += [names["anchor"], anchor]
    for item in parsed.provenance:
        encoded = provenance_arg(item)
        if encoded:
            argv += [names["provenance"], encoded]
    return argv


def _declared(name: str, value: object) -> str:
    """One warrant word, checked against its own closed vocabulary. Loud."""
    text = str(value).strip() if isinstance(value, str) else ""
    if not text:
        return ""
    allowed = WARRANT_VOCABULARIES[name]
    if text not in allowed:
        raise ChronologyError(f"unknown {name} {text!r} — one of {', '.join(allowed)}")
    return text


def date_from_argv(edtf: object, *, basis: object = None, granularity: object = None,
                   confidence: object = None, anchors: object = (),
                   provenance: object = (), default_basis: str = "stated") -> DateRecord | None:
    """The inverse of :func:`date_argv`: the flags a CLI parsed, back to a record.

    ``default_basis`` is what the record is when the CALLER DECLARED NOTHING —
    a person typing ``--date 1984`` at a terminal is stating it, which is the
    only reading under which ``stated`` is honest. Every machine caller goes
    through :func:`date_argv`, which always declares, so the default is never
    what a derived date lands as. ``None`` when there is no date; raises
    :class:`ChronologyError` when a flag is unusable — a warrant that does not
    survive the trip is evidence gone silently missing, which is the whole
    defect this pair exists to close.
    """
    text = edtf if isinstance(edtf, str) else ""
    if not text.strip():
        return None
    declared_basis = _declared("basis", basis)
    declared_granularity = _declared("granularity", granularity)
    declared_confidence = _declared("confidence", confidence)
    parsed = parse_edtf(text, basis=declared_basis or default_basis)
    if parsed is None:
        raise ChronologyError(f"unreadable date {text!r}")
    anchor_list = tuple(str(a).strip() for a in (anchors or ()) if str(a).strip())
    entries = tuple(parse_provenance_arg(item) for item in (provenance or ()))
    return replace(parsed,
                   basis=declared_basis or parsed.basis,
                   granularity=declared_granularity or parsed.granularity,
                   confidence=declared_confidence or parsed.confidence,
                   anchors=anchor_list, provenance=entries)


# --------------------------------------------------------------------------
# The witness (v204, ADR 0025 — retired 2026-09-03, dated note)
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
        record = parse_stated_date(stated)
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
