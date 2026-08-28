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
* Confidence is graded by how tight the join is. A **definitional** join
  INHERITS the landmark record's own confidence — the marker sets are
  exact-match and an identity is not an estimate, so a certain birthday dates
  the birth moment ``certain`` (owner ruling, 2026-08-24). An **age** join
  keeps whatever :func:`chronology.from_age` earned, and **containment** is
  ``inferred`` for a place and ``conjectural`` for an era — the documentary
  editors' mark for a date the system worked out rather than one the person
  asserted.
* **The promise and the delivery come from the same join.**
  :func:`derivable_moments` — which is what ``timeline.dependency_index``
  counts leverage with — is computed by the same matching helpers the pass
  itself uses. A number this module cannot deliver is a number it does not
  promise.

**v207 — the same idea one level up (ADR 0026 amendment, design D2).** The
founder filed his birth and *"Childhood"* still read `undated`, because
``build_bands``/``chapter_date`` read only a band's OWN ``date``. So
:func:`date_bands` walks every undated period with a second, smaller ladder
(:data:`BAND_RULES`) and gives it a span:

1. **residence** — the union of the spans of the PLACES that line up with the
   era (their own page span, or the residence landmark whose label they name).
   Where you were living is the person's own fact, and it bounds the era that
   contains it.
2. **age_label** — an era the roster NAMED after an age (*"My 20s"*) plus the
   birthday, which is a definitional join and inherits the birthday's own
   confidence.

**v254 removed a third rung that used to sit between those two** — `moments`,
the envelope of the era's already-dated members. See :data:`BAND_RULES` and
:func:`observed_envelope`.

The order is deliberately NOT :data:`RULES`' order. A definitional join is the
strongest thing a MOMENT can have, because the marker is the person's own
sentence; an age label is a name a roster model wrote, so it is ranked under
the two rules grounded in what the person actually did. A miss is still fine
and a wrong join is still not.

Because a band's span is what CONTAINMENT reads, the pass runs the moment
ladder, then the band ladder, then the moment ladder again — the second moment
pass is what places the moments the newly dated eras now bound. It is the same
idempotent pass twice, not two mechanisms, and a moment already dated is
skipped both times.

**v207 — the filing beat.** :func:`gain_sentence_for_record` answers, at the
moment a landmark or a placement is filed, the only question the person
actually has: *what did that just do?* It runs THIS pass over copies of the
current payload with the new record folded in and counts what dates — the same
promise-equals-delivery discipline, applied to a sentence instead of a star.
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

#: Strongest first. The order IS the ladder :func:`band_span` walks — and it is
#: deliberately NOT :data:`RULES`' order. For a MOMENT a definitional join is
#: the strongest thing there is, because the marker is the person's own
#: sentence. For a BAND the "definitional" rung is an age the ROSTER MODEL put
#: in a name ("My 20s"), so it is ranked under the rung grounded in what the
#: person actually did: where they lived.
#:
#: **v254 (issue #278, ADR 0030 decision 4): `moments` LEFT THIS LADDER.** An
#: era is never dated by whatever got sorted into it — the envelope of its
#: members is COVERAGE and is published as :func:`observed_envelope` on the
#: row, never as the era's bounds. See that function's docstring for the
#: incident.
BAND_RULES = ("residence", "age_label")

#: Which band identity a derivation leaned on. One per rule, so far.
BAND_JOINS = ("residence_span", "age_label")

#: Which band rules produce a span that BOUNDS the era on both sides — the only
#: kind a moment inside it may then take as containment bounds.
#:
#: This is the sharpest line in the amendment. A residence union says *"this
#: era at least covers that"* — a floor on its extent, not a ceiling — so it is
#: honest to DISPLAY as the era's span, to order the spine by, and to measure a
#: hole between eras with, and it is dishonest to push back down onto the era's
#: other moments: one dated moment would otherwise pin forty-seven undated ones
#: to its own year. (The moment envelope used to sit here too; v254 took it out
#: of the ladder entirely — it is not even a floor, because what is "inside" an
#: era is itself a placement this pass helps decide.) An age label is different
#: in kind: *"My 20s"* IS the decade from the twentieth birthday,
#: closed at both ends, so it bounds what is inside it exactly as an explicitly
#: dated era does.
BAND_RULES_THAT_BOUND = ("age_label",)

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

#: The relation/possessive vocabulary that marks a sentence as being about
#: somebody OTHER than the owner. ONE typing, promoted (recurring-defect
#: doctrine) rather than re-typed a second time for the age veto below —
#: `_BIRTH_OTHER_RE` and `THIRD_PERSON_AGE_RES` are two applications of the
#: same vocabulary, not two vocabularies. `grandma`/`grandmother`/`grandpa`/
#: `grandfather` join the list here (eras design O-E2, §5.1's own example,
#: "Grandma was 30 years old in 1951") — the pre-E2 birth veto never needed
#: them because nobody states "grandma was born" about anyone but grandma.
_THIRD_PARTY_RELATION_WORDS = (
    "brother", "sister", "sibling", "son", "daughter", "mom", "mother",
    "grandma", "grandmother", "dad", "father", "grandpa", "grandfather",
    "wife", "husband", "partner", "child", "children", "baby", "twin",
    "cousin", "nephew", "niece", "grandson", "granddaughter", "grandchild",
    "uncle", "aunt", "friend", "dog", "cat",
)
_THIRD_PARTY_RELATION_FRAGMENT = "|".join(_THIRD_PARTY_RELATION_WORDS)

#: The veto. Somebody ELSE's birth in the same moment kills the join outright —
#: a miss is fine, a wrong join is not.
_BIRTH_OTHER_RE = re.compile(
    rf"\b(?:{_THIRD_PARTY_RELATION_FRAGMENT})\b[^.]{{0,40}}?"
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
                              confidence=_inherited_confidence(birth["date"]),
                              provenance="from your birthday"),
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
                          confidence=_inherited_confidence(row["date"]),
                          provenance=provenance),
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
                                  confidence=_inherited_confidence(row["date"]),
                                  provenance=provenance),
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
                      confidence=_inherited_confidence(anchor), provenance=provenance),
        rule="definitional", join="named_anchor", anchor=key, label=label,
        provenance=provenance)


def _grain_of(record: object) -> str:
    parsed = record if isinstance(record, chrono.DateRecord) else chrono.from_dict(record)
    return parsed.granularity if parsed is not None else "range"


def _inherited_confidence(record: object) -> str:
    """A DEFINITIONAL join inherits the landmark record's OWN confidence.

    Owner ruling (2026-08-24): the marker sets are deliberately exact-match, so
    a definitional identity — *this moment IS your birth*, *this moment IS that
    residence span's start* — is not an estimate. A certain birthday therefore
    dates the birth moment `certain`, and the chip reads "11 July 1981" rather
    than "around 11 July 1981". `chronology.from_anchor` floors its result at
    `inferred`, which is right for a RELATION ("before the move") and wrong for
    an identity; this is where that floor is lifted, and only here — age and
    containment joins keep their inferred/conjectural grading.
    """
    parsed = record if isinstance(record, chrono.DateRecord) else chrono.from_dict(record)
    return parsed.confidence if parsed is not None else "inferred"


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
AGE_STATEMENT_RES = (
    re.compile(rf"\bwhen (?:i|we) (?:was|were)\s+({_HEDGE}\s+)?({_AGE_VALUE}(?:\s+or\s+{_AGE_VALUE})?)\b",
               re.IGNORECASE),
    # eras/E-BO: the SAME clause in the other order — "I was thirty when I
    # started there" — which `general_listener.THIRD_PERSON_AGE_RES` already
    # covers for every subject (that table's own v229 note: "a message is
    # written in either order"). This table's job is telling first person
    # apart from everyone else, so it needs the reverse order too, or a
    # first-person statement written this way reads as third-person's to
    # anything that treats "matches THIRD_PERSON_AGE_RES, doesn't match this"
    # as its veto (`birth_origin._reads_as_someone_else`) — found by T-BO-06.
    re.compile(rf"\b(?:i|we) (?:was|were)\s+({_HEDGE}\s+)?({_AGE_VALUE}(?:\s+or\s+{_AGE_VALUE})?)\s+when\b",
               re.IGNORECASE),
    re.compile(rf"\b(?:i|we) (?:was|were)\s+({_HEDGE}\s+)?({_AGE_VALUE}(?:\s+or\s+{_AGE_VALUE})?)\s+years old\b",
               re.IGNORECASE),
    re.compile(rf"\b({_HEDGE}\s+)?({_AGE_VALUE})[\s-]years?[\s-]old\b", re.IGNORECASE),
    re.compile(rf"\bat (?:the )?age(?:d)?(?: of)?\s+({_HEDGE}\s+)?({_AGE_VALUE})\b", re.IGNORECASE),
    # "at 19" — but never "at 19 Elm Street", "at 19th", "at 19:30", "at 19%".
    re.compile(rf"\bat ({_HEDGE}\s+)?(\d{{1,2}})\b(?!\s*(?:st\b|nd\b|rd\b|th\b|%|:|am\b|pm\b))(?!\s+[A-Z][a-z])"),
)


#: v218: PUBLIC, because the general listener's prescreen asks the same
#: question of raw prose that this pass asks of a moment — "is there an age
#: statement in here?" — and a second table of age phrasings is exactly the
#: duplicate the recurring-defect doctrine forbids. The private name stays as
#: the alias this module's own reader uses; there is no second tuple.
_AGE_STATEMENT_RES = AGE_STATEMENT_RES

#: A possessive/relation word sitting near an age statement — "Grandma was 30
#: years old", "my brother turned 19" — is evidence the age names somebody
#: ELSE, not the owner. `AGE_STATEMENT_RES` patterns 1-2 already require
#: "i"/"we" and never reach this veto; patterns 3-5 ("30 years old", "at the
#: age of 30", "at 19") have NO subject at all, so without this veto
#: `from_age_statement` dates any such fragment off the owner's OWN birthday
#: (eras design O-E2, §5.1). Built from the SAME relation vocabulary
#: `_BIRTH_OTHER_RE` uses — promoted, not re-typed.
THIRD_PERSON_AGE_RES = (
    re.compile(
        rf"\b(?:{_THIRD_PARTY_RELATION_FRAGMENT})\b[^.]{{0,40}}?"
        rf"\b(?:was|were|is|are|turned|turns|will be)\s+"
        rf"({_HEDGE}\s+)?({_AGE_VALUE})\b",
        re.IGNORECASE,
    ),
    re.compile(
        rf"\b(?:{_THIRD_PARTY_RELATION_FRAGMENT})(?:'s)?\s+"
        r"(\d{1,2})(?:st|nd|rd|th)\s+birthday\b",
        re.IGNORECASE,
    ),
)


def age_statement_is_third_person(text: object) -> bool:
    """Does this fragment/sentence name somebody ELSE's age?

    Applied over the moment's own text — never just the matched age
    fragment — because the relation word ("Grandma") and the age
    ("30 years old") sit in the same sentence but not necessarily the same
    substring `AGE_STATEMENT_RES` captured. `E-BO`'s `birth_origin_from_age`
    (not built by this contract) calls the same predicate; it is exported for
    that (eras design O-E2, §5.1).
    """
    value = str(text or "")
    if not value:
        return False
    return any(pattern.search(value) for pattern in THIRD_PERSON_AGE_RES)


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
    """Rule 2 — an explicit age plus the birthday, through `chronology.from_age`.

    eras O-E2 (design §5.1): vetoed when the moment's own text names somebody
    ELSE's age (`age_statement_is_third_person`) — "Grandma was 30 years old
    in 1951" never seeds the owner's axis off the owner's birthday.
    """
    if birth_date is None:
        return None
    text = moment_text(event)
    if age_statement_is_third_person(text):
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
# 4. Bands — the same three ideas one level up (v207, ADR 0026 amendment).
# ---------------------------------------------------------------------------


def _stamp_band(record: chrono.DateRecord, *, keys: tuple = (), source: str = "band",
                basis: str, confidence: str, provenance: str) -> chrono.DateRecord:
    """A band's derived span, badged with every anchor it leaned on.

    A band can rest on SEVERAL anchors at once — the union of three residence
    spans is one interval warranted by three landmarks — so unlike
    :func:`_stamp` this keeps the whole tuple, and `Derivation.anchor` names
    the first (the one the provenance sentence is about). ``keys`` is empty
    where the warrant is not an anchor at all: the moment envelope leans on
    what is already dated inside the era, and naming a fake anchor key for it
    would put a claim in `anchors` that no index could resolve.
    """
    keys = tuple(dict.fromkeys(str(key) for key in keys if str(key).strip()))
    return replace(
        record,
        basis=basis,
        confidence=confidence,
        anchors=keys,
        provenance=({"claim": provenance, "basis": basis,
                     "source": f"{PROVENANCE_SOURCE}:{keys[0] if keys else source}"},),
    )


def span_from_dated(events: object) -> chrono.DateRecord | None:
    """A span inferred from the dated things inside it — the ONE definition.

    `timeline._place_span` has derived a residence's span from the moments that
    happened there since v195; v207 needs exactly that arithmetic for an ERA
    too, so the definition moved here and `_place_span` delegates (the
    recurring-defect doctrine: one importable definition, never a second copy).

    A single year is `conjectural` and says so with EDTF's own `?`; two or more
    give their outer bounds as an `inferred` interval. An interval is a
    finding, not a failure — and it is never a point the person did not give.
    """
    rows = [row for row in (events or ()) if isinstance(row, dict)]
    starts = [year for year in (chrono.year_of(row.get("date")) for row in rows)
              if year is not None]
    ends = [year for year in (chrono.year_of(row.get("date"), end=True) for row in rows)
            if year is not None]
    if not starts:
        return None
    first, last = min(starts), max(ends or starts)
    if first == last:
        return chrono.DateRecord(best=f"{first}?", earliest=str(first), latest=str(first),
                                 granularity="year", confidence="conjectural", basis="order")
    return chrono.DateRecord(best=f"{first}/{last}", earliest=str(first), latest=str(last),
                             granularity="range", confidence="inferred", basis="order")


def _residence_landmark(label: str, anchors: object) -> tuple[str, object] | None:
    """The residence landmark a place page IS, matched on the whole label.

    Exact (case-insensitive) equality, not the substring test `_names` runs on
    prose: a place page called "Mesa" is the `residences-mesa` landmark; a page
    called "Mesa Community College" is not.
    """
    wanted = " ".join(str(label or "").split()).casefold()
    if not wanted:
        return None
    for key, row in _anchor_rows(anchors).items():
        if not isinstance(row, dict) or row.get("date") is None:
            continue
        key_text = str(key)
        if not key_text.startswith(RESIDENCE_PREFIX) and str(row.get("kind") or "") not in RESIDENCE_KINDS:
            continue
        if " ".join(_label_of(row).split()).casefold() == wanted:
            return key_text, row["date"]
    return None


def band_places(entity_lineup: object, slug: object, anchors: object = None) -> list[dict]:
    """`[{key, label, date}]` — the SPANNED places that line up with this era.

    A place's span is its own page date where it has one, and otherwise the
    residence landmark it names exactly. Both are the person's own statement of
    where they were living; neither is guessed.
    """
    rows = (entity_lineup or {}).get(str(slug)) if isinstance(entity_lineup, dict) else None
    found: list[dict] = []
    for row in rows or ():
        if not isinstance(row, dict) or row.get("type") != "place":
            continue
        label = str(row.get("title") or row.get("label") or row.get("slug") or "").strip()
        key = f"entity:{row.get('slug')}"
        record = chrono.from_dict(row.get("date")) if row.get("date") is not None else None
        if record is None:
            landmark = _residence_landmark(label, anchors)
            if landmark is not None:
                key, record = landmark[0], chrono.from_dict(landmark[1])
        if record is None or not (record.earliest and record.latest):
            continue
        found.append({"key": key, "label": label, "date": record})
    return found


def residence_span(places: object) -> Derivation | None:
    """Band rule 1 — the union of the spans of the places lived in this era.

    Containment read outwards: an era that CONTAINS a residence starts no later
    than that residence began and ends no earlier than it ended. Several
    residences union into one interval; the confidence is `inferred`, the
    documentary mark for a bound the system worked out from something stated.
    """
    rows = [row for row in (places or ()) if isinstance(row, dict) and row.get("date") is not None]
    if not rows:
        return None
    starts = [year for year in (chrono.year_of(row["date"]) for row in rows) if year is not None]
    ends = [year for year in (chrono.year_of(row["date"], end=True) for row in rows)
            if year is not None]
    if not starts:
        return None
    first, last = min(starts), max(ends or starts)
    ordered = sorted(rows, key=lambda row: (chrono.year_of(row["date"]) or 0, str(row["key"])))
    if len(ordered) == 1:
        provenance = f"from your years at {ordered[0]['label']}"
    else:
        provenance = "from where you were living then"
    if first == last:
        record = chrono.DateRecord(best=str(first), earliest=str(first), latest=str(first),
                                   granularity="year")
    else:
        record = chrono.DateRecord(best=f"{first}/{last}", earliest=str(first),
                                   latest=str(last), granularity="range")
    return Derivation(
        record=_stamp_band(record, keys=tuple(row["key"] for row in ordered),
                           basis="anchor", confidence="inferred", provenance=provenance),
        rule="residence", join="residence_span", anchor=str(ordered[0]["key"]),
        label=str(ordered[0]["label"]), provenance=provenance)


def observed_envelope(moments: object) -> chrono.DateRecord | None:
    """One era's COVERAGE of its dated members — **never a bound** (v254).

    This is the single most dangerous number in the whole design and this
    docstring is where the danger is named. Until v254 this was band rule 2
    (`moment_envelope`) and it WROTE the era's span. The founder's real vault
    is what proved it wrong: twelve of his thirteen dated moments got their
    date from the cross-dating pass that ran AFTER placement, so at placement
    time they were undated and fell to era-language matching — "Married Katie"
    (2007), "Moved to Seattle" (2012) and Etherfuse (2020) all landed in
    `high-school`, which then took `1997/2021` as its bounds *from those very
    moments*. `my-20s` and `my-30s` held zero. The era was dated by the
    accident of what got sorted into it, and the dated era then read as placed
    (lifehug#278, lifehug-platform#720 CERT-02/03).

    So the coverage is computed, published on its own key
    (`period["observed_envelope"]`, the same name and the same arithmetic the
    projection layer already uses in `temporal_timeline.observed_envelope`),
    and is never written to ``date``, ``date_derived`` or
    ``approximate_dates``. It says what the era's members happen to span. It
    does not say when the era was. — ADR 0030 decision 4, design §4.2.

    One definition: :func:`span_from_dated`, which `timeline._place_span` also
    delegates to.
    """
    return span_from_dated(moments)


#: The age-named eras a roster actually mints, and the ages each one means.
#: `my` is REQUIRED — "the 80s" is a decade of the century and "his 40s" is
#: somebody else's life, and neither of them is this person's era.
AGE_BAND_AGES = {
    "teens": (13, 20), "teenage years": (13, 20),
    "twenties": (20, 30), "20s": (20, 30),
    "thirties": (30, 40), "30s": (30, 40),
    "forties": (40, 50), "40s": (40, 50),
    "fifties": (50, 60), "50s": (50, 60),
    "sixties": (60, 70), "60s": (60, 70),
    "seventies": (70, 80), "70s": (70, 80),
    "eighties": (80, 90), "80s": (80, 90),
    "nineties": (90, 100), "90s": (90, 100),
}

_AGE_BAND_RE = re.compile(
    r"\bmy\s+(" + "|".join(sorted((re.escape(k) for k in AGE_BAND_AGES), key=len, reverse=True))
    + r")\b", re.IGNORECASE)


def age_band_label(name: object) -> str | None:
    """The age-label an era's NAME states, or ``None``."""
    match = _AGE_BAND_RE.search(" ".join(str(name or "").split()))
    return match.group(1).lower() if match else None


def age_band_span(name: object, birth_date: object) -> Derivation | None:
    """Band rule 3 — an age-named era plus the birthday, as an interval.

    A DEFINITIONAL join in ADR 0026's sense: *"My 20s"* IS the decade that
    starts on the twentieth birthday, so the span inherits the birthday's own
    confidence (§3's inheritance rule) rather than being floored at `inferred`.
    The bounds are calendar years, which is the honest granularity for an era —
    never a point, and never a day the person did not give.
    """
    label = age_band_label(name)
    if label is None:
        return None
    birth = chrono.year_of(birth_date)
    if birth is None:
        return None
    low, high = AGE_BAND_AGES[label]
    first, last = birth + low, birth + high
    record = chrono.DateRecord(best=f"{first}/{last}", earliest=str(first),
                               latest=str(last), granularity="range")
    provenance = "from your birthday"
    return Derivation(
        record=_stamp_band(record, keys=(BIRTH_KEY,), basis="anchor",
                           confidence=_inherited_confidence(birth_date),
                           provenance=provenance),
        rule="age_label", join="age_label", anchor=BIRTH_KEY,
        label="your birthday", provenance=provenance)


# ---------------------------------------------------------------------------
# Age frames — the permanent calculated coordinate system (eras design §3.3).
# ---------------------------------------------------------------------------

#: The two named bands, and where the decades take over. `childhood [0,13)`
#: and `teens [13,20)` are the design's own words; everything after is
#: `[10k, 10k+10)` for every REACHED k ≥ 2, with **no maximum**.
AGE_FRAME_FIXED_BANDS = (("childhood", 0, 13), ("teens", 13, 20))
AGE_FRAME_DECADE_FLOOR = 20
AGE_FRAME_DECADE = 10

#: How far up the generated ladder is walked when a caller needs the WHOLE
#: table rather than one life's reached frames — the alias map and the age
#: pair a label states. One ceiling, read by both, so "no maximum" cannot
#: mean two different maximums.
AGE_FRAME_LADDER_CEILING = 200

#: What each band is NAMED. A decade names itself ("My 20s"), so only the two
#: fixed bands need a name written down.
AGE_FRAME_NAMES = {"childhood": "Childhood", "teens": "Teen years"}

#: The separator and the phrase that turn a band NAME into the display string
#: eras design §3.3 specifies — "Childhood · ages 0–12". They live here, beside
#: the ladder they read, because the whole point of `O-E1b` finding 2 is that
#: the PACKAGE mints the string a host renders verbatim: a host that composed
#: "· ages 0–12" itself would be writing a title, which is exactly the thing
#: the standing ruling forbids, and two hosts composing it would be two
#: definitions of one sentence.
AGE_FRAME_LABEL_SEPARATOR = " \u00b7 "
AGE_FRAME_AGES_PHRASE = "ages {low}\u2013{high}"

#: The one sentence a frame shows for where it came from, when the origin is
#: the owner's own STATED birthday. `chronology.display_date` renders it as
#: *"— you said from your birthday"*, which is only true of an explicit origin.
AGE_FRAME_PROVENANCE = "from your birthday"

#: The two sentences a frame shows when its origin was CALCULATED — a
#: provisional scaffold seeded from age statements, with no birthday on file
#: (`birth_origin.provisional_origin`, design §3.2). The quoted form is used
#: whenever the origin record kept the person's own words about their age; the
#: bare form when it did not. Neither says "you said": a provisional frame is
#: arithmetic over what the person said about their AGE, and a birthday is
#: exactly the thing they have not given. (lifehug#266.)
AGE_FRAME_CALCULATED_QUOTED_PROVENANCE = "calculated from \u201c{phrase}\u201d"
AGE_FRAME_CALCULATED_PROVENANCE = "calculated from what you have said about your age"

#: The value of a node's ``origin_basis`` that means "the owner stated this
#: birthday". The MAPPING from a date basis to it is
#: `temporal_claims.CLAIM_BASIS_BY_DATE_BASIS`, read by the fold and passed in
#: — this module never re-answers it, it only reads the answer.
ORIGIN_BASIS_EXPLICIT = "explicit"

#: Re-exported so a caller reading frames does not have to know that the clamp
#: rule is minted one module down. There is one name for it, and this is it.
AGE_FRAME_CLAMP_RULE = chrono.AGE_FRAME_CLAMP_RULE

#: How a record sits against a frame. `within` is one frame containing the
#: whole interval; `overlaps` is every frame a wider or boundary-straddling
#: interval touches — and NOTHING picks a winner among them (design §2.4).
FRAME_RELATIONS = ("within", "overlaps")

_OPEN_LOW = (-9999, 1, 1)
_OPEN_HIGH = (9999, 12, 31)


@dataclass(frozen=True)
class AgeFrame:
    """One age frame: the interval, how it is bounded, and where life stops.

    ``end`` is EXCLUSIVE — the thirtieth birthday belongs to My 30s — while
    ``value`` is the same interval closed, at the birth's own grain, because a
    closed interval is what a `chronology.DateRecord` stores and what every
    reader already knows how to compare.
    """

    band: str
    label: str
    low: int
    high: int
    start: chrono.DateRecord
    end: chrono.DateRecord
    value: chrono.DateRecord
    current: bool
    life_clip_end: str

    def to_dict(self) -> dict:
        return {
            "band": self.band,
            "label": self.label,
            "ages": [self.low, self.high],
            "definition_span": {"start": self.start.to_dict(), "end": self.end.to_dict()},
            "value": self.value.to_dict(),
            "current": self.current,
            "life_clip_end": self.life_clip_end,
        }


def age_frame_name(band: object) -> str:
    """A band key as its bare NAME — "Childhood", "Teen years", "My 20s"."""
    key = str(band or "").strip()
    return AGE_FRAME_NAMES.get(key) or (f"My {key}" if key else "")


def age_frame_ages(band: object) -> tuple[int, int] | None:
    """The band's INCLUSIVE age pair, read off the one ladder — `(0, 12)`.

    Inclusive because that is what a person reads: the ladder's half-open
    `[0, 13)` and the display's "ages 0–12" are the same fact, and this is the
    single place the second spelling is derived from the first.
    """
    key = str(band or "").strip()
    for name, low, high in age_frame_ladder(AGE_FRAME_LADDER_CEILING):
        if name == key:
            return low, high - 1
    return None


def age_frame_label(band: object) -> str:
    """A band as the person reads it — the WHOLE display string (§3.3).

    "Childhood · ages 0–12", "Teen years · ages 13–19", "My 20s". A decade's
    own name already states its ages, so it carries no suffix; a named band
    does not, so it carries one. That rule is the reason the suffix is derived
    from :data:`AGE_FRAME_NAMES` rather than listed a second time.

    This string is the node's ``label``, and a host renders it verbatim — see
    `docs/pr-specs/eras-o-e1b-view-block.md` finding 2.
    """
    key = str(band or "").strip()
    name = age_frame_name(key)
    if not name or key not in AGE_FRAME_NAMES:
        return name
    ages = age_frame_ages(key)
    if ages is None:
        return name
    low, high = ages
    return name + AGE_FRAME_LABEL_SEPARATOR + AGE_FRAME_AGES_PHRASE.format(
        low=low, high=high
    )


def age_frame_ladder(max_age: object) -> tuple[tuple[str, int, int], ...]:
    """Every band whose FLOOR is at or below ``max_age``: `(band, low, high)`.

    The ladder is generated, not tabulated, which is what "no maximum" means:
    there is no last row to forget to add when somebody turns 100.
    """
    try:
        ceiling = int(max_age)
    except (TypeError, ValueError):
        return ()
    rows = [row for row in AGE_FRAME_FIXED_BANDS if row[1] <= ceiling]
    age = AGE_FRAME_DECADE_FLOOR
    while age <= ceiling:
        rows.append((f"{age}s", age, age + AGE_FRAME_DECADE))
        age += AGE_FRAME_DECADE
    return tuple(rows)


#: The canonical band NAMES a roster mints, per frame — the design's own
#: "`Childhood`, `My Teens`, `My 20s`…" (§3.5). Everything else is generated
#: from :data:`AGE_BAND_AGES`, which is the legacy table those very rows were
#: named from, so the two can never drift into two vocabularies.
AGE_FRAME_CANONICAL_NAMES = {"childhood": ("childhood",)}


def age_frame_slug(name: object) -> str:
    """A period name as the roster's own slug — lowercase, hyphenated."""
    return "-".join(re.findall(r"[a-z0-9]+", str(name or "").lower()))


def age_frame_legacy_slugs() -> dict:
    """`{band: (slug, …)}` — every legacy period slug that IS an age frame.

    Built from :data:`AGE_BAND_AGES`' own keys (so `my-20s`, `my-twenties`,
    `my-teens`, `my-teenage-years` all arrive without a second list) plus the
    bare spellings and `childhood`, which the legacy band table never held
    because it had no `[0,13)` rung. A band name whose ages do not match this
    ladder's is deliberately absent: `My 50s` is a frame the moment it is
    reached, and `AGE_BAND_AGES`' 50s row agrees with the ladder, so it maps.
    """
    ladder = {band: (low, high)
              for band, low, high in age_frame_ladder(AGE_FRAME_LADDER_CEILING)}
    slugs: dict[str, list[str]] = {}
    for band, names in AGE_FRAME_CANONICAL_NAMES.items():
        slugs[band] = [age_frame_slug(name) for name in names]
    for label, ages in AGE_BAND_AGES.items():
        band = next((key for key, span in ladder.items() if span == ages), None)
        if band is None:
            continue
        for spelling in (f"my {label}", label):
            slug = age_frame_slug(spelling)
            if slug and slug not in slugs.setdefault(band, []):
                slugs[band].append(slug)
    return {band: tuple(values) for band, values in slugs.items()}


def age_frame_band_of(name: object) -> str | None:
    """The band a legacy period NAME or slug means, or ``None``.

    ``None`` for anything that is not an age band — `College`, `the Mission`.
    A named era is E3's identity and guessing one here would be exactly the
    wrong join ADR 0026 ranks above a miss.
    """
    slug = age_frame_slug(name)
    if not slug:
        return None
    for band, slugs in age_frame_legacy_slugs().items():
        if slug in slugs:
            return band
    return None


def _bounds(record: object) -> tuple[tuple, tuple] | None:
    """A record as a comparable closed `(low, high)`; open ends run to ±9999."""
    parsed = record if isinstance(record, chrono.DateRecord) else chrono.from_dict(record)
    if parsed is None:
        return None
    low = chrono._ordinal(parsed.earliest, end=False) or _OPEN_LOW  # noqa: SLF001
    high = chrono._ordinal(parsed.latest, end=True) or _OPEN_HIGH  # noqa: SLF001
    if parsed.earliest is None and parsed.latest is None:
        return None
    return low, high


def _as_of_bound(value: object) -> tuple | None:
    """`as_of` — an ISO day, a date record, or anything either parses."""
    if value is None:
        return None
    text = value.isoformat() if hasattr(value, "isoformat") else str(value)
    text = text.split("T")[0].strip()
    ordinal = chrono._ordinal(text, end=False)  # noqa: SLF001
    if ordinal is not None:
        return ordinal
    bounds = _bounds(chrono.from_dict(value))
    return bounds[0] if bounds else None


def origin_is_explicit(origin_basis: object) -> bool:
    """Did the owner STATE this birthday? The ONE predicate (lifehug#266).

    One place decides, so the frame's provenance entry and the node's
    `birth_origin.origin_provenance_summary` sentence cannot disagree about
    whether a birthday is on file. The value itself is the fold's answer,
    computed once through `temporal_claims.CLAIM_BASIS_BY_DATE_BASIS`.
    """
    return " ".join(str(origin_basis or "").split()) == ORIGIN_BASIS_EXPLICIT


def frame_origin_provenance(origin: object, origin_basis: object) -> dict:
    """The ONE provenance entry a frame carries for where its origin came from.

    An explicit origin gets :data:`AGE_FRAME_PROVENANCE` — the person really
    did say a birthday, and `chronology.display_date` may quote it back at
    them. A CALCULATED origin gets a clause that names the arithmetic instead,
    filed under `chronology.CALCULATED_PROVENANCE_BASIS` so the renderer prints
    it verbatim: quoting the person's own age statement when the origin record
    kept one (it is written there by `chronology.birth_origin_from_age`, under
    rule `chronology.BIRTH_ORIGIN_RULE`, and no other module re-derives it),
    and the bare sentence when it did not.

    There is no third outcome and no "omit the clause" branch: a frame whose
    provenance opens with the calendar CLAMP row would be rendered by
    `display_date` as *"you said <the clamp rule>"*, which is the same lie in
    a different sentence.
    """
    if origin_is_explicit(origin_basis):
        return {"claim": AGE_FRAME_PROVENANCE, "basis": "anchor",
                "source": f"{PROVENANCE_SOURCE}:{BIRTH_KEY}"}
    record = origin if isinstance(origin, chrono.DateRecord) else chrono.from_dict(origin)
    phrase = ""
    for row in (record.provenance if record is not None else ()):
        if row.get("source") != chrono.BIRTH_ORIGIN_RULE:
            continue
        phrase = " ".join(str(row.get("claim") or "").split())
        if phrase:
            break
    claim = (AGE_FRAME_CALCULATED_QUOTED_PROVENANCE.format(phrase=phrase)
             if phrase else AGE_FRAME_CALCULATED_PROVENANCE)
    return {"claim": claim, "basis": chrono.CALCULATED_PROVENANCE_BASIS,
            "source": f"{PROVENANCE_SOURCE}:{BIRTH_KEY}"}


def _frame_provenance(origin: object, *records: chrono.DateRecord,
                      origin_basis: object) -> tuple[dict, ...]:
    """The frame's own sentence, plus any calendar rule the shift had to use."""
    entries: list[dict] = [frame_origin_provenance(origin, origin_basis)]
    for record in records:
        for row in record.provenance:
            if row.get("source") == AGE_FRAME_CLAMP_RULE and row not in entries:
                entries.append(dict(row))
    return tuple(entries)


def age_frames(birth: object, *, as_of: object, death: object = None,
               origin_basis: object = ORIGIN_BASIS_EXPLICIT) -> tuple[AgeFrame, ...]:
    """The reached age frames of one life. ONE definition (design §3.3).

    Pure arithmetic over the birth origin: `start_k = add_years(birth, low)`,
    `end_k = add_years(birth, high)` exclusive, for every band whose start is
    at or before ``as_of`` (or before a given ``death``). Disjoint on age by
    construction, so no frame needs to know about any other.

    What this function deliberately does NOT decide: whether the origin is
    ``explicit`` or ``calculated``. That is a *claim* basis with exactly one
    definition already — `temporal_claims.CLAIM_BASIS_BY_DATE_BASIS` — and
    importing the substrate here to re-answer it would be a second copy of that
    table inside a module whose whole value is that it is pure. It is passed
    in as ``origin_basis``, and the frames READ it: a frame drawn on a
    calculated origin says how it was calculated, never that you said it
    (:func:`frame_origin_provenance`, lifehug#266). The default is
    ``explicit`` because every caller that holds a plain vault birthday —
    `timeline.py`'s three — holds a stated one; the one caller that can hold a
    provisional origin is the fold, and it passes what `_origin_basis_of`
    already answered.
    """
    origin = birth if isinstance(birth, chrono.DateRecord) else chrono.from_dict(birth)
    if origin is None:
        return ()
    limit = _as_of_bound(as_of)
    if limit is None:
        return ()
    death_record = death if isinstance(death, chrono.DateRecord) else chrono.from_dict(death)
    death_bound = _as_of_bound(death) if death_record is not None else None
    clipped_by_death = death_bound is not None and death_bound <= limit
    if clipped_by_death:
        limit = death_bound

    confidence = _inherited_confidence(origin)
    day_grain = origin.granularity == "day"
    rows: list[tuple[str, int, int, chrono.DateRecord, chrono.DateRecord]] = []
    age = 0
    while True:
        ladder = age_frame_ladder(age)
        if not ladder:
            break
        band, low, high = ladder[-1]
        start = chrono.add_years(origin, low)
        end = chrono.add_years(origin, high)
        if start is None or end is None:
            break
        start_bound = _bounds(start)
        if start_bound is None or start_bound[0] > limit:
            break
        rows.append((band, low, high, start, end))
        age = high

    frames: list[AgeFrame] = []
    for index, (band, low, high, start, end) in enumerate(rows):
        earliest = start.earliest or start.best
        latest = chrono.day_before(end.earliest) if day_grain else (end.latest or end.best)
        if not earliest or not latest:
            continue
        value = chrono.DateRecord(
            best=f"{earliest}/{latest}", earliest=earliest, latest=latest,
            granularity="range", confidence=confidence, basis="anchor",
            anchors=(BIRTH_KEY,),
            provenance=_frame_provenance(origin, start, end,
                                         origin_basis=origin_basis),
        )
        last = index == len(rows) - 1
        if last and clipped_by_death:
            clip = (death_record.earliest or death_record.best) if death_record else latest
            frames.append(AgeFrame(band, age_frame_label(band), low, high, start, end,
                                   value, False, str(clip)))
        elif last:
            frames.append(AgeFrame(band, age_frame_label(band), low, high, start, end,
                                   value, True, "present"))
        else:
            frames.append(AgeFrame(band, age_frame_label(band), low, high, start, end,
                                   value, False, latest))
    return tuple(frames)


def frames_touching(frames: object, record: object) -> tuple[tuple[str, str], ...]:
    """Every frame a record touches, and how — `within` once, `overlaps` else.

    This is the whole of age-frame membership (design §2.4): arithmetic, not
    judgment. A fuzzy interval that crosses three frames keeps all three, and
    nothing here picks a winner — which frame a row RENDERS in is a display
    role, and display roles are E2's.
    """
    bounds = _bounds(record)
    if bounds is None:
        return ()
    low, high = bounds
    touched: list[tuple[str, tuple, tuple]] = []
    for frame in frames or ():
        span = _bounds(getattr(frame, "value", None))
        if span is None:
            continue
        if low <= span[1] and span[0] <= high:
            touched.append((frame.band, span[0], span[1]))
    if len(touched) == 1:
        band, span_low, span_high = touched[0]
        if span_low <= low and high <= span_high:
            return ((band, "within"),)
    return tuple((band, "overlaps") for band, _, _ in touched)


def frame_for(frames: object, record: object) -> str | None:
    """The ONE frame a record lies inside, or ``None``. Same body as above."""
    for band, relation in frames_touching(frames, record):
        if relation == "within":
            return band
    return None


def band_span(period: object, *, places: object = (),
              birth_date: object = None) -> Derivation | None:
    """The one derivation for one undated band, :data:`BAND_RULES` in order.

    v254: the ``moments`` rung and its parameter are GONE — an era's members
    are coverage, not bounds (:func:`observed_envelope`). Passing `moments=`
    now fails loud rather than silently doing nothing.
    """
    if not isinstance(period, dict) or period.get("date") is not None:
        return None
    found = residence_span(places)
    if found is not None:
        return found
    return age_band_span(period.get("name") or period.get("label") or period.get("slug"),
                         birth_date)


def date_bands(*, periods: object = (), event_lineup: object = None,
               entity_lineup: object = None, anchors: object = None,
               birth_date: object = None) -> dict:
    """Give every UNDATED period a span. Returns a report; mutates the rows.

    A dated band gains ``date`` (a `chronology.DateRecord`), ``date_derived``
    (the `Derivation.to_dict()`, the only marker of a derived band date) and
    the ``approximate_dates`` display alias `timeline.load_periods` maintains
    for every other reader. An explicit date — a `timeline-place` correction, a
    page's own frontmatter, a roster span — is never touched.

    Nothing is written anywhere: like the moment pass this is recomputed on
    every read, so a corrected landmark un-dates the era it used to bound.

    **v254.** Every period — dated or not — also gets ``observed_envelope``:
    the coverage of its dated members, on its own key, never a bound. That is
    the whole of what its members are allowed to say about it
    (:func:`observed_envelope`, ADR 0030 decision 4).
    """
    lineup = event_lineup if isinstance(event_lineup, dict) else {}
    report = {"derived": 0, "by_rule": {rule: 0 for rule in BAND_RULES},
              "by_join": {join: 0 for join in BAND_JOINS}, "bands": [],
              "observed_envelopes": 0}
    for period in periods or ():
        if not isinstance(period, dict):
            continue
        slug = str(period.get("slug") or "")
        # Coverage first, and for EVERY era: an explicitly dated era has
        # members too, and what they span is worth rendering beside a span the
        # person stated. Recomputed here, never accumulated.
        period.pop("observed_envelope", None)
        envelope = observed_envelope(lineup.get(slug) or ())
        if envelope is not None:
            period["observed_envelope"] = envelope.to_dict()
            report["observed_envelopes"] += 1
        if period.get("date") is not None:
            continue
        found = band_span(period,
                          places=band_places(entity_lineup, slug, anchors),
                          birth_date=birth_date)
        if found is None:
            continue
        period["date"] = found.record
        period["date_derived"] = found.to_dict()
        period["approximate_dates"] = chrono.display_date(found.record, with_basis=False)
        report["derived"] += 1
        report["by_rule"][found.rule] = report["by_rule"].get(found.rule, 0) + 1
        report["by_join"][found.join] = report["by_join"].get(found.join, 0) + 1
        report["bands"].append({
            "slug": slug,
            "label": str(period.get("name") or period.get("label") or slug),
            "rule": found.rule, "join": found.join, "anchor": found.anchor,
        })
    return report


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


def _moment_report() -> dict:
    """A fresh, empty moment report — the ONE shape both phases accumulate."""
    return {"derived": 0, "by_rule": {rule: 0 for rule in RULES},
            "by_join": {join: 0 for join in JOINS}, "moments": []}


def _record_derivation(event: dict, found: Derivation, *, period_slug: object,
                       report: dict) -> None:
    """Stamp one derived date onto its moment and count it. One definition,
    shared by both phases, so the two can never drift in what they record."""
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


def cross_date_moments(events: object, *, entity_lineup: object = None,
                       anchors: object = None, birth_date: object = None,
                       report: object = None) -> dict:
    """**Phase one: date before you place** (v254, issue #278).

    Every rung of :func:`derive` that needs NO era membership — a definitional
    anchor, an age statement, and the containment of a PLACE whose own sources
    cite this moment's source. All three read the person's own facts and the
    entity lineup, both of which exist before a single moment has been slotted
    into an era.

    This exists because `timeline.heuristic_slot`'s rung 1 is *"dated → frame
    arithmetic"* and it was structurally unreachable: `timeline_data` placed
    first and cross-dated second, so a moment whose date this pass supplies was
    undated at the moment somebody asked where it goes. Twelve of the founder's
    thirteen dated moments were in exactly that state, and every one of them
    landed by era LANGUAGE instead of by its date
    (lifehug-platform#720 CERT-03).

    No cycle, and that is not an assertion: nothing here reads a period, so
    nothing here can be an input to the placement it precedes. The rung that
    DOES read a period — containment from the era's own span — stays in
    :func:`cross_date`, after placement, where a membership exists; a date
    derived from an era can never move the moment out of that era, because it
    was derived from being in it.

    ``report`` continues an existing moment report instead of starting one, so
    the two phases add up to ONE set of counts. A row derived here carries
    ``"period": None`` — it had no era yet, which is the entire point.
    """
    report = report if isinstance(report, dict) else _moment_report()
    places = _places_by_source(entity_lineup)
    for event in events or ():
        if not isinstance(event, dict) or event.get("date") is not None:
            continue
        found = derive(event, anchors=anchors, birth_date=birth_date,
                       period=None,
                       place=places.get(str(event.get("source") or "")))
        if found is None:
            continue
        _record_derivation(event, found, period_slug=None, report=report)
    return report


def cross_date(*, event_lineup: object, unplaced_events: object = (),
               periods: object = (), entity_lineup: object = None,
               anchors: object = None, birth_date: object = None,
               report: object = None) -> dict:
    """Run the pass over an assembled lineup. Returns a report; mutates rows.

    Each dated moment gains ``date`` (a `chronology.DateRecord`) and
    ``date_derived`` (this pass's own `Derivation.to_dict()`), which is the
    ONLY marker of a derived date and the only thing a renderer needs to show
    the landmark provenance in place of the classifier's free-text anchor.

    **v254 — this is PHASE TWO.** :func:`cross_date_moments` has already run
    the membership-independent rungs before `timeline.place_events`, so the
    first sweep here is normally a no-op over rows that are already dated; what
    remains is everything that needs to know which era a moment is in. Pass
    that phase's report as ``report`` and the two add up to one set of counts.
    Called on its own with no ``report`` it still runs the WHOLE ladder — a
    caller holding an already-placed lineup (`record_gain`) is unchanged.

    **Three phases (v207).** Moments, then bands, then the moments the newly
    dated bands now bound. The third phase is the SAME idempotent pass as the
    first — a moment that already carries a date is skipped in both — and it
    exists because containment reads a band's span, which phase two is what
    supplies. A band derived here is reported under ``bands``; nothing else
    about the report's shape moved.

    Nothing is written anywhere. The report is
    ``{"derived": n, "by_rule": {...}, "by_join": {...}, "moments": [...],
    "bands": {...}}``.
    """
    lineup = event_lineup if isinstance(event_lineup, dict) else {}
    period_by_slug = {str(p.get("slug")): p for p in (periods or ())
                      if isinstance(p, dict) and p.get("slug")}
    places = _places_by_source(entity_lineup)
    report = report if isinstance(report, dict) else _moment_report()

    def run(event: object, period_slug: object) -> None:
        if not isinstance(event, dict) or event.get("date") is not None:
            return
        found = derive(event, anchors=anchors, birth_date=birth_date,
                       period=period_by_slug.get(str(period_slug)),
                       place=places.get(str(event.get("source") or "")))
        if found is None:
            return
        _record_derivation(event, found, period_slug=period_slug, report=report)

    def sweep() -> None:
        for slug, rows in lineup.items():
            for event in rows or ():
                run(event, slug)
        for event in unplaced_events or ():
            run(event, None)

    sweep()
    report["bands"] = date_bands(periods=periods, event_lineup=lineup,
                                 entity_lineup=entity_lineup, anchors=anchors,
                                 birth_date=birth_date)
    if report["bands"]["derived"]:
        # Only a span that bounds the era on BOTH sides may bound what is
        # inside it (:data:`BAND_RULES_THAT_BOUND`); a floor-only span is
        # hidden from the second sweep rather than pinning its own moments.
        period_by_slug = containment_periods(periods)
        sweep()
    # v208 (ADR 0027 §9): the ghost's source. Every DATED moment — stated or
    # derived — learns what its interval would be absent its date, on the same
    # walk rather than in a second pass that could drift from this one.
    report["prior_spans"] = stamp_prior_spans(
        event_lineup=lineup, unplaced_events=unplaced_events, periods=periods,
        birth_date=birth_date)
    return report


# ---------------------------------------------------------------------------
# The ghost's source (v208, ADR 0027 §9) — reconstructed, never stored.
# ---------------------------------------------------------------------------


def prior_span(event: object, *, periods: object = (), bands: object = None,
               life: object = None) -> list[int] | None:
    """What this dated moment's interval WOULD be absent its date.

    The 4A ghost is *reconstructable*, not stored history (the dating-dataflow
    rule: no state). It is `timeline.unknown_years` read for a moment that now
    has a date — its era's span where the era has one, else the life — and it
    is ``None`` when that reconstruction is not WIDER than the moment's own
    interval, because then there is nothing to ghost.

    **Honesty note.** After an era's own dates improve, old ghosts *tighten* on
    the next read: the ghost shows today's honest reconstruction of "before",
    not a historical screenshot of what the page once said. That is the
    stateless trade, and it is stated rather than fixed by keeping history.
    """
    import timeline  # noqa: PLC0415  (one definition of the interval, lazily)

    if not isinstance(event, dict) or event.get("date") is None:
        return None
    row = {"kind": "moment", "period": event.get("__period")}
    view = {"periods": list(periods or ()), "bands": list(bands or ())}
    prior = timeline.unknown_years(row, view, life=life)
    if not prior:
        return None
    first = chrono.year_of(event.get("date"))
    last = chrono.year_of(event.get("date"), end=True)
    if first is None or last is None:
        return None
    if (prior[1] - prior[0]) <= (int(last) - int(first)):
        return None
    return prior


def stamp_prior_spans(*, event_lineup: object, unplaced_events: object = (),
                      periods: object = (), bands: object = None,
                      birth_date: object = None) -> int:
    """Give every DATED moment its ``prior_span``; returns how many were given.

    One walk, in the same pass that stamps ``date_derived``, so a stated moment
    and a derived one carry the ghost alike — the ghost is about what the
    timeline could bound the moment to before it had a date, and that is a
    property of the era, not of who supplied the date.
    """
    import timeline  # noqa: PLC0415

    life = timeline.life_span(None, birth_date)
    lineup = event_lineup if isinstance(event_lineup, dict) else {}
    stamped = 0
    for slug, rows in list(lineup.items()) + [(None, unplaced_events or ())]:
        for event in rows or ():
            if not isinstance(event, dict):
                continue
            event.pop("prior_span", None)
            event["__period"] = slug
            try:
                found = prior_span(event, periods=periods, bands=bands, life=life)
            finally:
                event.pop("__period", None)
            if found is not None:
                event["prior_span"] = found
                stamped += 1
    return stamped


def containment_periods(periods: object) -> dict:
    """`{slug: period}` for the containment rule, with floor-only spans hidden.

    Never mutates: a period whose span is a derived FLOOR is substituted by a
    shallow copy carrying ``date: None``, so the row a renderer holds keeps the
    span it should display while the pass declines to reason from it.
    """
    lookup: dict[str, dict] = {}
    for period in periods or ():
        if not isinstance(period, dict) or not period.get("slug"):
            continue
        derived = period.get("date_derived") or {}
        if derived and str(derived.get("rule") or "") not in BAND_RULES_THAT_BOUND:
            period = {**period, "date": None}
        lookup[str(period["slug"])] = period
    return lookup


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


# ---------------------------------------------------------------------------
# The filing beat — what an answer JUST placed, said in the conversation
# (v207, design T3). The page catches up in about two minutes; the sentence
# does not have to wait for it.
# ---------------------------------------------------------------------------

#: Small counts read as words, exactly as the Reading Room has always said
#: them. Beyond twelve the digits are clearer than the word.
NUMBER_WORDS_SPOKEN = ("no", "one", "two", "three", "four", "five", "six",
                       "seven", "eight", "nine", "ten", "eleven", "twelve")


def spoken_count(count: object) -> str:
    """`9` → ``"nine"``; `40` → ``"40"``. One definition, three callers."""
    try:
        value = max(int(count), 0)
    except (TypeError, ValueError):
        return "no"
    return NUMBER_WORDS_SPOKEN[value] if value < len(NUMBER_WORDS_SPOKEN) else str(value)


def moment_clause(count: object) -> str:
    """``"dates nine moments"`` — the ONE clause every gain sentence is built
    from, so `reading_room.placement_gain_sentence` and the landmark/timeline
    filing beat can never drift into two ways of saying the same true thing."""
    try:
        value = max(int(count), 0)
    except (TypeError, ValueError):
        value = 0
    return f"dates {spoken_count(value)} {'moment' if value == 1 else 'moments'}"


def band_clause(labels: object) -> str:
    """``"your Childhood years"`` — the band half of the sentence.

    A leading article is dropped ("your Yucaipa Years", not "your The Yucaipa
    Years") and a label that already says "years" is not given a second pair,
    and past one band the eras are counted rather than listed: the sentence is
    a gift, not a report.
    """
    names = [_band_name(label) for label in (labels or ()) if str(label).strip()]
    names = [name for name in names if name]
    if not names:
        return ""
    if len(names) > 1:
        return f"{spoken_count(len(names))} of your eras"
    return f"your {names[0]}" if "year" in names[0].casefold() else f"your {names[0]} years"


def _band_name(label: object) -> str:
    name = " ".join(str(label or "").split())
    return name[4:].strip() if name[:4].casefold() == "the " else name


def gain_sentence(moments: object = 0, bands: object = ()) -> str:
    """*"Got it — that dates nine moments and your Childhood years."*

    The whole sentence, or ``""`` when an answer placed nothing beyond itself —
    and ``""`` is the right answer far more often than not. A count of what
    REMAINS is never said here (`reading_room.placement_gain_sentence`'s own
    rule, and the owner's).
    """
    try:
        count = max(int(moments or 0), 0)
    except (TypeError, ValueError):
        count = 0
    eras = band_clause(bands)
    if not count and not eras:
        return ""
    if count and eras:
        return f"Got it — that {moment_clause(count)} and {eras}."
    if count:
        return f"Got it — that {moment_clause(count)}."
    return f"Got it — that dates {eras}."


def record_gain(record: object, timeline_payload: object) -> dict:
    """`{"moments": n, "bands": [label, ...]}` — what filing THIS just placed.

    Pure. It runs the pass itself over COPIES of the payload's own rows with
    the new record folded in, and counts what dates that did not date before.
    That is the promise-equals-delivery discipline of ADR 0026 §5 applied to a
    sentence: the conversation can only claim what the next derivation will
    actually deliver, because the same code computed both.

    `record` is either a LANDMARK record (it carries a `domain`, and enters as
    anchors through `landmarks_interaction.anchors_from_landmarks`) or a
    PLACEMENT (a `chronology` record with the `source` of the moment it dates).
    Anything else places nothing, which is also the honest answer.
    """
    payload = timeline_payload if isinstance(timeline_payload, dict) else {}
    lineup = {str(slug): [dict(row) for row in rows or () if isinstance(row, dict)]
              for slug, rows in (payload.get("event_lineup") or {}).items()}
    unplaced = [dict(row) for row in payload.get("unplaced_events") or ()
                if isinstance(row, dict)]
    periods = [dict(row) for row in payload.get("periods") or () if isinstance(row, dict)]
    anchors = dict(_anchor_rows(payload.get("anchors")))
    for key, row in _landmark_anchors(record).items():
        anchors.setdefault(key, row)
    _apply_placement(record, lineup, unplaced)
    report = cross_date(event_lineup=lineup, unplaced_events=unplaced,
                        periods=periods, entity_lineup=payload.get("entity_lineup"),
                        anchors=anchors,
                        birth_date=(anchors.get(BIRTH_KEY) or {}).get("date"))
    return {"moments": int(report["derived"]),
            "bands": [str(row["label"]) for row in report["bands"]["bands"]]}


def gain_sentence_for_record(record: object, timeline_payload: object) -> str:
    """The filing beat's sentence for one just-filed record, or ``""``."""
    gain = record_gain(record, timeline_payload)
    return gain_sentence(gain["moments"], gain["bands"])


def _landmark_anchors(record: object) -> dict:
    """The anchor rows a landmark record supplies, through the one function
    that mints them. A placement supplies none."""
    if not isinstance(record, dict):
        return {}
    domain = str(record.get("domain") or "").strip()
    if not domain:
        return {}
    import landmarks_interaction as _li  # noqa: PLC0415  (avoids an import cycle)

    try:
        return _li.anchors_from_landmarks({domain: [record]})
    except Exception:  # noqa: BLE001
        return {}


def _apply_placement(record: object, lineup: dict, unplaced: list) -> None:
    """Date the moment a `timeline-place` record is about, in the copies.

    The moment's own date is what the person just said, so it is never counted
    as a gain — but it is exactly what a band's envelope then reads.
    """
    if not isinstance(record, dict) or record.get("domain"):
        return
    parsed = chrono.from_dict(record.get("date") if "date" in record else record)
    if parsed is None:
        return
    source = str(record.get("source") or "").strip()
    short = str(record.get("source_short") or "").strip()
    if not source and not short:
        return
    for rows in [*lineup.values(), unplaced]:
        for row in rows:
            if row.get("date") is not None:
                continue
            if (source and str(row.get("source") or "") == source) or \
               (short and str(row.get("source_short") or "") == short):
                row["date"] = parsed


#: The direction the landmark and timeline leaves carry for `{filing_gain}`.
#: It is rendered TOGETHER with the sentence, so a turn with nothing to report
#: substitutes the empty string and the prompt is byte-identical to v205's.
FILING_GAIN_DIRECTION = (
    "**What their answer just placed.** Weave this into your reply, in your "
    "own words, once, and then let it go: {sentence} Say it as the plain good "
    "news it is — and, only if it fits, that the pages catch up in a minute "
    "or two. Never read it as a list, never say what is left, never promise "
    "to remind them of anything."
)


def render_filing_gain(sentence: object) -> str:
    """The `{filing_gain}` substitution: ``""``, or the direction and its
    sentence as a paragraph of their own."""
    text = " ".join(str(sentence or "").split())
    if not text:
        return ""
    return "\n\n" + FILING_GAIN_DIRECTION.format(sentence=text)
