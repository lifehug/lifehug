#!/usr/bin/env python3
"""Cross-dating: a resolved anchor places its dependent moments (v205).

`keystones()` has promised leverage since v196 — *"one answer would place 53
more things"* — and nothing in the package ever delivered it. A date reached
the timeline through exactly two doors: the classifier's own
``events[].date`` claim, and an explicit per-moment ``timeline-place``. So the
owner filed his birth landmark (1981-07-11, day, basis stated) and the moment
*"Born in Redlands while the family lived in the area"* still read **undated**,
carrying a stale free-text ``anchor: dad attending ASU`` that was not even
temporally right. **The leverage number promised what no pass delivered.**

This module is that pass. It is pure — no I/O, no model, no vault — and it is
run at derivation time by :func:`timeline.timeline_data`, which means it holds
**no state at all**: every derived date is recomputed on every read, so a
better landmark improves the whole timeline instantly and a corrected landmark
un-derives what it used to support. There is nothing to migrate and nothing to
repair.

**The ladder, strongest first** (``system/research/chronology.md`` §1 and §6;
``system/research/go-deep.md`` §7):

1. **Definitional joins** — the moment *is* a landmark fact. A birth moment
   IS the birth landmark; a move IS a residence-span boundary; a graduation IS
   the end of a schooling span. The join is made on an explicit, small,
   testable marker set per domain plus the classifier's own ``anchor`` field
   *when it names a landmark in the index exactly* — never on semantic
   resemblance. A miss is fine; a wrong join is not.
2. **Age statements** — an explicit age in the person's own words
   (``"when I was about five"``, ``"at 19"``) plus the birthday, through
   :func:`chronology.from_age`. This is the arithmetic ADR 0024 already owns;
   what is new is reading the age out of ``when_hint``/prose the classifier
   never lifted into ``date.age``.
3. **Containment** — a moment inside a place or an era whose SPAN is known
   takes that span as **bounds**: a *terminus post quem* and a *terminus ante
   quem*, granularity ``range``. Bounds, never a point. "The interval is
   itself a finding, not a failure."

**Four rules that make this safe:**

* An explicit record is **never** overwritten. A moment that already has a
  date — stated, age-resolved, connector-corroborated, or pinned by the owner
  through ``timeline-place`` — is skipped outright.
* Nothing is invented. Every derived interval is arithmetic over dates the
  person actually gave, and it says so: ``basis`` is ``anchor`` or ``age``,
  ``anchors`` names the landmark it leaned on, and ``provenance`` carries the
  human sentence the page shows ("from your birthday").
* Confidence is graded by how tight the join is — a definitional join is
  ``inferred``, era containment is ``conjectural`` (the documentary editors'
  mark for a date the system worked out rather than one the person asserted).
* **The promise and the delivery come from the same join.**
  :func:`derivable_moments` — which is what ``timeline.dependency_index``
  counts leverage with — is computed by the same matching helpers the pass
  itself uses. A number this module cannot deliver is a number it does not
  promise.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace

import chronology as chrono

# ---------------------------------------------------------------------------
# The closed vocabularies of the pass.
# ---------------------------------------------------------------------------

#: Strongest first. The order IS the ladder :func:`derive` walks.
RULES = ("definitional", "age", "containment")

#: Which landmark identity a derivation leaned on.
JOINS = (
    "birth",          # the moment IS the person's birth
    "move_in",        # the moment IS a residence span's start
    "move_out",       # the moment IS a residence span's end
    "graduation",     # the moment IS a schooling span's end
    "named_anchor",   # the classifier's own `anchor` names an indexed landmark
    "age",            # an explicit age statement against the birthday
    "place",          # inside a place whose span is known
    "era",            # inside an era whose span is known
)

#: Provenance `source` for everything this module writes, so `claim_score`
#: counts one origin per derivation and a reader can tell a derived claim from
#: a stated one without guessing.
PROVENANCE_SOURCE = "cross-dating"

#: Anchor-index kinds that can carry a residence span.
RESIDENCE_KINDS = ("residence",)

#: Landmark anchor-key prefixes (`landmarks_interaction._anchor_key` mints
#: `"<domain>-<slug>"`; the birthday is the bare key `birth`).
RESIDENCE_PREFIX = "residences-"
SCHOOL_PREFIX = "schools-"
BIRTH_KEY = "birth"


# ---------------------------------------------------------------------------
# What one derivation is.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Derivation:
    """One derived date, and the whole reason it is believed.

    ``provenance`` is the sentence a page shows in place of the classifier's
    free-text anchor ("from your birthday"); the classifier's own ``anchor``
    text is never destroyed, only demoted to the detail view.
    """

    record: chrono.DateRecord
    rule: str
    join: str
    anchor: str
    label: str
    provenance: str

    def to_dict(self) -> dict:
        return {"rule": self.rule, "join": self.join, "anchor": self.anchor,
                "label": self.label, "provenance": self.provenance}


def _stamp(record: chrono.DateRecord, *, anchor: str, basis: str,
           confidence: str, provenance: str) -> chrono.DateRecord:
    """Re-badge a record as this pass's own claim, with its warrant on it."""
    anchors = tuple(dict.fromkeys(record.anchors + ((anchor,) if anchor else ())))
    return replace(
        record,
        basis=basis,
        confidence=confidence,
        anchors=anchors,
        provenance=({"claim": provenance, "basis": basis,
                     "source": f"{PROVENANCE_SOURCE}:{anchor}"},),
    )


# ---------------------------------------------------------------------------
# The text a moment offers up. The classifier's `anchor` is NOT part of it:
# that field is free text the model wrote, it is exactly the field the owner
# caught being wrong, and it earns a derivation only through the exact
# index lookup in `_named_anchor` below.
# ---------------------------------------------------------------------------


def moment_fields(event: object) -> tuple[str, ...]:
    """The moment's prose fields, separately — title, description, hint.

    Kept separate because a `^`-anchored marker ("the sentence OPENS on the
    verb") is a claim about one field, and concatenating them would make it a
    claim about whichever field happened to come first.
    """
    row = event if isinstance(event, dict) else {}
    parts = (str(row.get("title") or ""), str(row.get("description") or ""),
             str(row.get("when_hint") or ""))
    return tuple(part.strip() for part in parts if part.strip())


def moment_text(event: object) -> str:
    """The moment's prose as one string, for markers that are not anchored."""
    return " ".join(moment_fields(event))


# ---------------------------------------------------------------------------
# 1. Definitional joins.
# ---------------------------------------------------------------------------

#: The subject's OWN birth, stated explicitly. `^born` covers the classifier's
#: commonest shape ("Born in Redlands while the family lived in the area") —
#: an event whose sentence opens on the verb has no other subject.
_BIRTH_SELF_RES = (
    re.compile(r"^\s*(?:i was\s+)?born\b", re.IGNORECASE),
    re.compile(r"\bi was born\b", re.IGNORECASE),
    re.compile(r"\bwhen i was born\b", re.IGNORECASE),
    re.compile(r"\bthe day i was born\b", re.IGNORECASE),
    re.compile(r"\bmy (?:own )?birth\b(?!day\b)", re.IGNORECASE),
)

#: The veto. Somebody ELSE's birth in the same moment kills the join outright —
#: a miss is fine, a wrong join is not.
_BIRTH_OTHER_RE = re.compile(
    r"\b(?:brother|sister|sibling|son|daughter|mom|mother|dad|father|wife|"
    r"husband|partner|child|children|baby|twin|cousin|nephew|niece|grandson|"
    r"granddaughter|grandchild|uncle|aunt|friend|dog|cat)\b[^.]{0,40}?"
    r"\b(?:was|were|is|are|got)\s+born\b",
    re.IGNORECASE,
)

#: A move INTO a home: the moment IS that residence span's start.
_MOVE_IN_RES = (
    re.compile(r"\bmov(?:ed|ing|e)\s+(?:in\s*)?(?:to|into)\b", re.IGNORECASE),
    re.compile(r"\bmoved in\b", re.IGNORECASE),
    re.compile(r"\bthe move (?:in\s*)?(?:to|into)\b", re.IGNORECASE),
)

#: A move OUT of a home: the moment IS that residence span's end.
_MOVE_OUT_RES = (
    re.compile(r"\bmov(?:ed|ing|e)\s+(?:out of|out|away from)\b", re.IGNORECASE),
    re.compile(r"\bthe move (?:out of|away from)\b", re.IGNORECASE),
    re.compile(r"\b(?:we|i) left\b", re.IGNORECASE),
)

#: The end of a schooling span.
_GRADUATION_RES = (
    re.compile(r"\bgraduat(?:ed|ion|ing)\b", re.IGNORECASE),
    re.compile(r"\bcommencement\b", re.IGNORECASE),
)


def _matches(text: str, patterns: tuple) -> bool:
    return any(pattern.search(text) for pattern in patterns)


def _matches_any_field(event: object, patterns: tuple) -> bool:
    return any(_matches(field, patterns) for field in moment_fields(event))


def _anchor_rows(anchors: object) -> dict:
    return anchors if isinstance(anchors, dict) else {}


def _label_of(row: object) -> str:
    return str((row or {}).get("label") or "").strip() if isinstance(row, dict) else ""


def _names(text: str, label: str) -> bool:
    """Does the moment's prose name this landmark, as a whole word?

    Exact substring on a word boundary — the same conservatism
    `chronology.anchor_key` applies to the classifier's anchor field. "Mesa"
    matches "we moved to Mesa"; it does not match "Mesabi".
    """
    label = label.strip()
    if len(label) < 3:
        return False
    return re.search(rf"(?<!\w){re.escape(label)}(?!\w)", text, re.IGNORECASE) is not None


def _named_landmark(text: str, anchors: dict, *, prefix: str = "",
                    kinds: tuple = ()) -> tuple[str, dict] | None:
    """The most specific landmark of a domain whose label the moment names."""
    best: tuple[str, dict] | None = None
    for key, row in anchors.items():
        if not isinstance(row, dict) or row.get("date") is None:
            continue
        key_text = str(key)
        if prefix and not key_text.startswith(prefix):
            if not (kinds and str(row.get("kind") or "") in kinds):
                continue
        label = _label_of(row)
        if not _names(text, label):
            continue
        if best is None or len(_label_of(best[1])) < len(label):
            best = (key_text, row)
    return best


def _bound_record(record: object, *, end: bool) -> chrono.DateRecord | None:
    """One end of a span, as a record of its own (the move-in / move-out date)."""
    parsed = chrono.from_dict(record) if not isinstance(record, chrono.DateRecord) else record
    if parsed is None:
        return None
    bound = parsed.latest if end else parsed.earliest
    if not bound:
        return None
    return chrono.parse_edtf(bound, basis="anchor")


def definitional(event: object, anchors: object) -> Derivation | None:
    """Rule 1 — the moment IS a landmark fact, so it takes that fact's date."""
    rows = _anchor_rows(anchors)
    if not rows:
        return None
    text = moment_text(event)
    if not text:
        return None

    # (a) The person's own birth.
    birth = rows.get(BIRTH_KEY)
    if (isinstance(birth, dict) and birth.get("date") is not None
            and _matches_any_field(event, _BIRTH_SELF_RES)
            and not _BIRTH_OTHER_RE.search(text)):
        record = chrono.from_anchor(birth["date"], "during",
                                    grain=_grain_of(birth["date"]), key=BIRTH_KEY)
        if record is not None:
            return Derivation(
                record=_stamp(record, anchor=BIRTH_KEY, basis="anchor",
                              confidence="inferred", provenance="from your birthday"),
                rule="definitional", join="birth", anchor=BIRTH_KEY,
                label=_label_of(birth) or "your birthday",
                provenance="from your birthday")

    # (b) A move — the boundary of a residence span the moment names.
    for patterns, end, join, phrase in (
        (_MOVE_IN_RES, False, "move_in", "from when you moved to {label}"),
        (_MOVE_OUT_RES, True, "move_out", "from when you left {label}"),
    ):
        if not _matches(text, patterns):
            continue
        found = _named_landmark(text, rows, prefix=RESIDENCE_PREFIX,
                                kinds=RESIDENCE_KINDS)
        if found is None:
            continue
        key, row = found
        record = _bound_record(row["date"], end=end)
        if record is None:
            continue
        label = _label_of(row)
        provenance = phrase.format(label=label)
        return Derivation(
            record=_stamp(record, anchor=key, basis="anchor",
                          confidence="inferred", provenance=provenance),
            rule="definitional", join=join, anchor=key, label=label,
            provenance=provenance)

    # (c) A graduation — the end of a schooling span the moment names.
    if _matches(text, _GRADUATION_RES):
        found = _named_landmark(text, rows, prefix=SCHOOL_PREFIX)
        if found is not None:
            key, row = found
            record = _bound_record(row["date"], end=True)
            if record is not None:
                label = _label_of(row)
                provenance = f"from when {label} ended"
                return Derivation(
                    record=_stamp(record, anchor=key, basis="anchor",
                                  confidence="inferred", provenance=provenance),
                    rule="definitional", join="graduation", anchor=key,
                    label=label, provenance=provenance)

    # (d) The classifier's OWN anchor field — but only when it names a landmark
    #     in the index EXACTLY. "dad attending ASU" names nothing and derives
    #     nothing, which is the owner's case and the point of the guard.
    return _named_anchor(event, rows)


def _named_anchor(event: object, anchors: dict) -> Derivation | None:
    reference = str((event or {}).get("anchor") or "").strip() if isinstance(event, dict) else ""
    if not reference:
        return None
    key = chrono.anchor_key(reference, anchors)
    if key is None:
        return None
    anchor = chrono.lookup_anchor(reference, anchors)
    if anchor is None:
        return None
    record = chrono.from_anchor(anchor, "during", grain=_grain_of(anchor), key=key)
    if record is None:
        return None
    label = _label_of(anchors.get(key)) or reference
    provenance = f"from {label}"
    return Derivation(
        record=_stamp(record, anchor=key, basis="anchor",
                      confidence="inferred", provenance=provenance),
        rule="definitional", join="named_anchor", anchor=key, label=label,
        provenance=provenance)


def _grain_of(record: object) -> str:
    parsed = record if isinstance(record, chrono.DateRecord) else chrono.from_dict(record)
    return parsed.granularity if parsed is not None else "range"


# ---------------------------------------------------------------------------
# 2. Age statements.
# ---------------------------------------------------------------------------

#: Number words come from `chronology.NUMBER_WORDS` itself, so the detector and
#: the parser can never disagree about what counts as an age.
_AGE_WORD = "|".join(sorted(chrono.NUMBER_WORDS, key=len, reverse=True))
_HEDGE = r"(?:about|around|roughly|approximately|maybe|nearly|almost|some(?:thing|where) (?:like|around))"
_AGE_VALUE = rf"(?:\d{{1,2}}|{_AGE_WORD})"

#: Explicit age STATEMENTS only. `chronology.parse_age` is deliberately greedy
#: (it reads any number it is handed), so the pass never hands it raw prose —
#: it hands it exactly the fragment one of these matched.
_AGE_STATEMENT_RES = (
    re.compile(rf"\bwhen (?:i|we) (?:was|were)\s+({_HEDGE}\s+)?({_AGE_VALUE}(?:\s+or\s+{_AGE_VALUE})?)\b",
               re.IGNORECASE),
    re.compile(rf"\b(?:i|we) (?:was|were)\s+({_HEDGE}\s+)?({_AGE_VALUE}(?:\s+or\s+{_AGE_VALUE})?)\s+years old\b",
               re.IGNORECASE),
    re.compile(rf"\b({_HEDGE}\s+)?({_AGE_VALUE})[\s-]years?[\s-]old\b", re.IGNORECASE),
    re.compile(rf"\bat (?:the )?age(?:d)?(?: of)?\s+({_HEDGE}\s+)?({_AGE_VALUE})\b", re.IGNORECASE),
    # "at 19" — but never "at 19 Elm Street", "at 19th", "at 19:30", "at 19%".
    re.compile(rf"\bat ({_HEDGE}\s+)?(\d{{1,2}})\b(?!\s*(?:st\b|nd\b|rd\b|th\b|%|:|am\b|pm\b))(?!\s+[A-Z][a-z])"),
)


def age_statement(event: object) -> str | None:
    """The age fragment a moment states in the person's own words, or ``None``."""
    text = moment_text(event)
    if not text:
        return None
    for pattern in _AGE_STATEMENT_RES:
        match = pattern.search(text)
        if match is None:
            continue
        fragment = " ".join(" ".join(part.split())
                            for part in match.groups() if part).strip()
        if chrono.parse_age(fragment) is not None:
            return fragment
    return None


def from_age_statement(event: object, birth_date: object) -> Derivation | None:
    """Rule 2 — an explicit age plus the birthday, through `chronology.from_age`."""
    if birth_date is None:
        return None
    fragment = age_statement(event)
    if fragment is None:
        return None
    record = chrono.from_age(birth_date, fragment)
    if record is None:
        return None
    provenance = f'from "{fragment}" and your birthday'
    return Derivation(
        record=replace(record, provenance=(
            {"claim": fragment, "basis": "age",
             "source": f"{PROVENANCE_SOURCE}:{BIRTH_KEY}"},)),
        rule="age", join="age", anchor=BIRTH_KEY, label="your birthday",
        provenance=provenance)


# ---------------------------------------------------------------------------
# 3. Containment — bounds, never a point.
# ---------------------------------------------------------------------------


def containment(span: object, *, anchor: str, label: str, join: str) -> Derivation | None:
    """Rule 3 — a known span read as a *terminus post/ante quem* pair."""
    parsed = span if isinstance(span, chrono.DateRecord) else chrono.from_dict(span)
    if parsed is None or not (parsed.earliest and parsed.latest):
        return None
    record = chrono.from_anchor(parsed, "during", grain="range", key=anchor)
    if record is None:
        return None
    confidence = "inferred" if join == "place" else "conjectural"
    provenance = (f"within your years at {label}" if join == "place"
                  else f"within {label}")
    return Derivation(
        record=_stamp(record, anchor=anchor, basis="anchor",
                      confidence=confidence, provenance=provenance),
        rule="containment", join=join, anchor=anchor, label=label,
        provenance=provenance)


# ---------------------------------------------------------------------------
# The ladder.
# ---------------------------------------------------------------------------


def derive(event: object, *, anchors: object = None, birth_date: object = None,
           period: object = None, place: object = None) -> Derivation | None:
    """The one derivation for one undated moment, strongest rule first.

    `period` is `{slug, name, date}`; `place` is `{slug, title, date}` — the
    entity whose OWN sources cite this moment's source (the provable overlap
    `timeline._place_for_event` uses, never keyword-fuzzy).
    """
    if not isinstance(event, dict) or event.get("date") is not None:
        return None
    found = definitional(event, anchors)
    if found is not None:
        return found
    found = from_age_statement(event, birth_date)
    if found is not None:
        return found
    if isinstance(place, dict) and place.get("date") is not None:
        found = containment(place["date"], anchor=f"entity:{place.get('slug')}",
                            label=str(place.get("title") or place.get("slug") or ""),
                            join="place")
        if found is not None:
            return found
    if isinstance(period, dict) and period.get("date") is not None:
        return containment(period["date"], anchor=f"period:{period.get('slug')}",
                           label=str(period.get("name") or period.get("slug") or ""),
                           join="era")
    return None


# ---------------------------------------------------------------------------
# The pass.
# ---------------------------------------------------------------------------


def cross_date(*, event_lineup: object, unplaced_events: object = (),
               periods: object = (), entity_lineup: object = None,
               anchors: object = None, birth_date: object = None) -> dict:
    """Run the pass over an assembled lineup. Returns a report; mutates rows.

    Each dated moment gains ``date`` (a `chronology.DateRecord`) and
    ``date_derived`` (this pass's own `Derivation.to_dict()`), which is the
    ONLY marker of a derived date and the only thing a renderer needs to show
    the landmark provenance in place of the classifier's free-text anchor.

    Nothing is written anywhere. The report is
    ``{"derived": n, "by_rule": {...}, "by_join": {...}, "moments": [...]}``.
    """
    lineup = event_lineup if isinstance(event_lineup, dict) else {}
    period_by_slug = {str(p.get("slug")): p for p in (periods or ())
                      if isinstance(p, dict) and p.get("slug")}
    places = _places_by_source(entity_lineup)
    report = {"derived": 0, "by_rule": {rule: 0 for rule in RULES},
              "by_join": {join: 0 for join in JOINS}, "moments": []}

    def run(event: object, period_slug: object) -> None:
        if not isinstance(event, dict) or event.get("date") is not None:
            return
        found = derive(event, anchors=anchors, birth_date=birth_date,
                       period=period_by_slug.get(str(period_slug)),
                       place=places.get(str(event.get("source") or "")))
        if found is None:
            return
        event["date"] = found.record
        event["date_derived"] = found.to_dict()
        report["derived"] += 1
        report["by_rule"][found.rule] = report["by_rule"].get(found.rule, 0) + 1
        report["by_join"][found.join] = report["by_join"].get(found.join, 0) + 1
        report["moments"].append({
            "period": None if period_slug is None else str(period_slug),
            "source_short": str(event.get("source_short") or ""),
            "rule": found.rule, "join": found.join, "anchor": found.anchor,
        })

    for slug, rows in lineup.items():
        for event in rows or ():
            run(event, slug)
    for event in unplaced_events or ():
        run(event, None)
    return report


def _places_by_source(entity_lineup: object) -> dict[str, dict]:
    """`{source: place}` — the same provable source overlap `_place_for_event`
    uses, resolved once. Ties go to the more specific place (smaller source
    set), exactly as they do there."""
    by_source: dict[str, tuple[int, str, dict]] = {}
    for rows in (entity_lineup or {}).values() if isinstance(entity_lineup, dict) else ():
        for row in rows or ():
            if not isinstance(row, dict) or row.get("type") != "place":
                continue
            sources = [str(s) for s in (row.get("sources") or ())]
            for source in sources:
                candidate = (len(sources), str(row.get("slug") or ""), row)
                current = by_source.get(source)
                if current is None or candidate[:2] < current[:2]:
                    by_source[source] = candidate
    return {source: row for source, (_, _, row) in by_source.items()}


# ---------------------------------------------------------------------------
# The promise — computed from the SAME joins as the delivery.
# ---------------------------------------------------------------------------


def derivable_moments(*, event_lineup: object, unplaced_events: object = (),
                      periods: object = (), entity_lineup: object = None
                      ) -> dict[str, list[tuple[str | None, dict]]]:
    """`{anchor_key: [(period_slug, moment), ...]}` — what dating one anchor
    would place, and nothing else.

    This is the leverage promise, and it is the pass's own containment rule
    read backwards: an era's span bounds the moments placed in it, a place's
    span bounds the moments its sources cite. A dated MOMENT bounds nothing
    (a point is not a span) and a PERSON's arrival bounds nothing, so neither
    appears here — before v205 both claimed moments they could never place.
    """
    lineup = event_lineup if isinstance(event_lineup, dict) else {}
    reach: dict[str, list[tuple[str | None, dict]]] = {}
    known = {str(p.get("slug")) for p in (periods or ())
             if isinstance(p, dict) and p.get("slug")}
    places = _places_by_source(entity_lineup)

    def add(key: str, period_slug: object, event: dict) -> None:
        reach.setdefault(key, []).append(
            (None if period_slug is None else str(period_slug), event))

    def consider(event: object, period_slug: object) -> None:
        if not isinstance(event, dict) or event.get("date") is not None:
            return
        place = places.get(str(event.get("source") or ""))
        if isinstance(place, dict) and place.get("slug"):
            add(f"entity:{place['slug']}", period_slug, event)
        if period_slug is not None and str(period_slug) in known:
            add(f"period:{period_slug}", period_slug, event)

    for slug, rows in lineup.items():
        for event in rows or ():
            consider(event, slug)
    for event in unplaced_events or ():
        consider(event, None)
    return reach
