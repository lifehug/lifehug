#!/usr/bin/env python3
"""Runtime authority for the registered Landmarks Interaction (v199).

The always-present dating question set is the sixth child of Conversation
(`interactions/README.md` § "The child-interaction paradigm"). Its one goal:
**collect the small set of dated facts that makes every other memory cheap to
place** — and never feel like a form.

Everything here is pure — no writes, no model calls, no lifecycle. The
question set, the specificity ladders, the stage, the closed validator and the
lints are all deterministic functions over data the caller supplies, exactly
as `timeline_interaction` and `arc_walk` are.

The mechanic these answers enable has a name: **cross-dating** — dating an
undated sequence by matching it against an already-dated one
(`system/research/go-deep.md` §7's terminology table). The landmarks are the
dated sequence; every other memory is the undated one.

**Naming** (owner-set, 2026-08-23): **Landmarks** is the product word AND the
package/module/CLI name, so there is one name from the surface down to this
file. `anchor` keeps the meaning it already had in code — the *derived* index
a landmark's date becomes once it can bound something (`timeline.anchor_index`,
`basis: "anchor"`, `chronology.from_anchor`). A landmark is the question and
the answer; an anchor is what the answer turns into. The join is
:func:`anchors_from_landmarks`.

Why this exists (`system/research/landmarks.md` §3.7): the arithmetic was
built before the inputs. `chronology.from_age` needs a birthday that nothing
ever supplied, and `PLAYBOOK_STEPS` rungs 5-6 are marked `needs_anchor` over
an anchor index that is nearly always empty. This Interaction fills it.

Three owner rulings shape the surface (2026-08-23):

1. Onboarding asks in **generalities** — "do you remember where you lived?
   where was that?" — and takes a skip without comment.
2. A landmark that is unanswered **or below target specificity** stays
   **open on the Timeline**, forever, answerable at any time. Never in the
   daily queue, never a reminder, never a nag. An open landmark is a normal
   resting state, not a debt.
3. A vague answer is an **answer**. "The eighties, somewhere in Ohio" bounds
   things already; the ladder exists because *more* would unlock more, not
   because less is a failure.

One more ruling arrived from a live incident (2026-08-24), and it is the
mirror of ruling 3 (rulings 4 and 5 — the ledger's shape and the keystone
star — live on `timeline.landmark_rows_for`):

6. **"That never happened" is a finished answer.** A person with no military
   service, no partnerships, or no children must be able to COMPLETE those
   domains — the row leaves the open list and is never offered again. The
   none terminal is derived from the question set (:func:`domain_accepts_none`
   — the four domains whose ladder opens at ``happened``), and a later
   reversal supersedes it rather than fighting it
   (:func:`merge_landmark_entry`).

Contract: ``docs/pr-specs/landmarks.md``.
Research: ``system/research/landmarks.md``.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

_SYSTEM_DIR = Path(__file__).resolve().parent
if str(_SYSTEM_DIR) not in sys.path:
    sys.path.insert(0, str(_SYSTEM_DIR))

import chronology as chrono  # noqa: E402
from lifehug_core import INTERACTIONS_DIR, _parse_simple_yaml  # noqa: E402


class LandmarkInteractionError(ValueError):
    """A domain, rung, stage or landmark record is unusable."""


# --------------------------------------------------------------------------
# The question set (interactions/landmarks/questions.yaml)
# --------------------------------------------------------------------------

QUESTIONS_FILE = "questions.yaml"

#: Every field a domain row carries, and how it is coerced.
_TEXT_FIELDS = ("ask", "complete_at", "precision", "why",
                "collection", "closure", "identity_kind")
_BOOL_FIELDS = ("onboarding", "sensitive", "per_entry_ladder")
_LIST_FIELDS = ("ladder", "unlocks", "date_semantics")

# --------------------------------------------------------------------------
# Cardinality is DATA, not a flag (v219, lifehug-platform#664; audited
# temporal-claims plan §6.2)
# --------------------------------------------------------------------------
#
# THE DEFECT, stated once. Until v219 a single boolean — `chain` — meant
# multiplicity ("this domain holds many entries"), order ("walked to the
# present") and closure ("finished when the person says so") simultaneously.
# `children`, `partnerships` and `losses` hold many entries by construction
# and were declared `chain: false`, because they are not WALKED — so every
# consumer that asked the multiplicity question through `chain` got the
# closure answer. :func:`incomplete_subjects` skipped all three, and the
# founder's four named children produced ONE aggregate gap ("What year was
# [all four] born?") instead of four independently closable ones.
#
# Four fields now say the four things, and none of them says two:
# `collection` (how many, and whether order is part of the fact), `closure`
# (what ends the GROUP — `complete_at` already says what ends one ENTRY),
# `identity_kind` (what one entry IS) and `date_semantics` (which events it
# dates). `per_entry_ladder` says whether the rungs below identity are walked
# once per entry. Every consumer below derives from these; `chain` is derived
# BACKWARD onto the row for hosts pinned to the old shape, and a guard test
# fails the build on any read of it inside `system/`.

#: How many entries a domain holds, and whether their order is part of the
#: fact. A `sequence` is walked forward in time (the residence chain, the job
#: history); a `set` is a group with no walk (your children, your losses); a
#: `singleton` is one entry with no subject of its own (your birthday).
COLLECTIONS = ("singleton", "set", "sequence")

#: What ends the GROUP — a different question from what completes one entry.
#: `user_completable`: the person declares the list finished (`chain_complete`
#: or the none terminal), and until they do the domain is `partial` no matter
#: how complete its entries are. `open`: the set is never declared closed and
#: the domain completes exactly when its entries reach `complete_at`.
CLOSURES = ("open", "user_completable")

#: What ONE entry is. Declared exactly where the ladder has an
#: :func:`identity_rung`, and empty where it has none.
IDENTITY_KINDS = ("person", "organization", "place", "relationship_edge",
                  "episode")

#: The events a domain dates. `span` is the only one that is a STRETCH rather
#: than a point, which is why :func:`dates_each_entry` can read this field
#: instead of re-deriving the same judgment from the ladder.
DATE_SEMANTICS = ("birth", "death", "first_met", "dating_started", "married",
                  "started", "ended", "transition", "span")


def is_multi_entry(row: object) -> bool:
    """True when one domain holds many entries — the MULTIPLICITY question.

    The one definition, and the one `chain` used to answer wrongly for
    `children`, `partnerships`, `losses` and `military`. Order is
    :func:`is_sequence`'s question and closure is
    :func:`requires_declared_closure`'s; neither is asked here.
    """
    return (isinstance(row, dict)
            and str(row.get("collection") or "") in ("set", "sequence"))


def is_sequence(row: object) -> bool:
    """True when the entries' ORDER is part of the fact (the walked lists)."""
    return isinstance(row, dict) and str(row.get("collection") or "") == "sequence"


def requires_declared_closure(row: object) -> bool:
    """True when only the PERSON can say the list is finished.

    The closure half of the old `chain` flag, alone. `residences` is complete
    when the person says that was the last house; `children` is a set with no
    declared end, so it completes when its entries do — the system never asks
    "any more children?" and never will.
    """
    return (isinstance(row, dict)
            and str(row.get("closure") or "") == "user_completable")


def enumerates_subjects(row: object) -> bool:
    """True when this domain's gaps are PER SUBJECT, not per domain.

    The Wave A exit criterion (audited plan §9) in one predicate, and the
    reason v219 exists: a domain that holds many named entries, each walking
    its own ladder, owes ONE independently closable gap per incomplete entry.
    Eight of the nine domains qualify; `birth` is the singleton axis and
    cannot.
    """
    return (is_multi_entry(row) and bool(row.get("per_entry_ladder"))
            and identity_rung(row) is not None)


def date_semantics(row: object) -> tuple[str, ...]:
    """The events this domain dates, in declared order."""
    return tuple(row.get("date_semantics") or ()) if isinstance(row, dict) else ()


def dates_each_entry(row: object) -> bool:
    """True when one entry of this domain carries ONE date, not a stretch.

    v219 moves this off the ladder and onto `date_semantics`, which is the
    field that actually says it: a `span` semantic is a stretch and one
    entry's stretch legitimately states two years ("1984 to 1990"), so a year
    count is no evidence there. Everything else — a birth, a death, a
    marriage — is one point per entry, and then the count IS evidence.
    """
    kinds = date_semantics(row)
    return bool(kinds) and "span" not in kinds


def _questions_path(framework_root: str | Path | None = None) -> Path:
    root = Path(framework_root) / "interactions" if framework_root else INTERACTIONS_DIR
    return Path(root) / "landmarks" / QUESTIONS_FILE


def _as_bool(value: object) -> bool:
    return str(value).strip().lower() in {"true", "yes", "1"}


def _as_tuple(value: object) -> tuple[str, ...]:
    text = str(value or "").strip()
    return tuple(part.strip() for part in text.split("|") if part.strip())


def load_questions(framework_root: str | Path | None = None) -> tuple[dict, ...]:
    """The ordered question set as rows.

    Each row: ``{domain, order, onboarding, ask, ladder, complete_at,
    precision, unlocks, sensitive, why}`` plus v219's cardinality block
    ``{collection, closure, identity_kind, date_semantics,
    per_entry_ladder}`` and the derived, deprecated ``chain``. Order is the
    file's ``domains`` line, not dictionary order, so the set's sequence is
    one edit in one place.
    """
    raw = _parse_simple_yaml(_questions_path(framework_root))
    if not raw:
        raise LandmarkInteractionError("landmarks/questions.yaml is missing or empty")
    domains = _as_tuple(raw.get("domains"))
    if not domains:
        raise LandmarkInteractionError("landmarks/questions.yaml declares no domains")
    rows: list[dict] = []
    for index, domain in enumerate(domains, start=1):
        row: dict = {"domain": domain, "order": index}
        for field in _TEXT_FIELDS:
            row[field] = str(raw.get(f"{domain}.{field}") or "").strip()
        for field in _BOOL_FIELDS:
            row[field] = _as_bool(raw.get(f"{domain}.{field}"))
        for field in _LIST_FIELDS:
            row[field] = _as_tuple(raw.get(f"{domain}.{field}"))
        if not row["ask"] or not row["ladder"]:
            raise LandmarkInteractionError(f"landmark domain {domain!r} is incomplete")
        if row["complete_at"] not in row["ladder"]:
            raise LandmarkInteractionError(
                f"landmark domain {domain!r} completes at {row['complete_at']!r}, "
                "which is not on its ladder"
            )
        _validate_cardinality(row)
        # v219: DERIVED BACKWARD and deprecated. `chain` used to be the
        # declaration; it is now one consequence of `closure`, kept on the row
        # so a host pinned to the pre-v219 shape still reads the same four
        # domains. Nothing in `system/` may read it — the AST guard in
        # `tests/test_landmarks.py` fails the build on a read — and the next
        # release that can drop the key drops it.
        row["chain"] = row["closure"] == "user_completable"
        rows.append(row)
    return tuple(rows)


def _validate_cardinality(row: dict) -> None:
    """Every cardinality field is declared, in vocabulary, and consistent.

    Loud at LOAD time, because the whole point of v219 is that a domain can
    no longer be silently mis-declared: `children` was wrong for two releases
    and the only symptom was a question that would not go away.
    """
    domain = row["domain"]

    def _refuse(detail: str) -> None:
        raise LandmarkInteractionError(f"landmark domain {domain!r} {detail}")

    if row["collection"] not in COLLECTIONS:
        _refuse(f"declares collection {row['collection']!r}, "
                f"which is not one of {COLLECTIONS}")
    if row["closure"] not in CLOSURES:
        _refuse(f"declares closure {row['closure']!r}, "
                f"which is not one of {CLOSURES}")
    if not row["date_semantics"]:
        _refuse("declares no date_semantics")
    unknown = [kind for kind in row["date_semantics"]
               if kind not in DATE_SEMANTICS]
    if unknown:
        _refuse(f"declares date_semantics {unknown!r}, "
                f"which are not in {DATE_SEMANTICS}")

    # identity_kind and identity_rung are two views of the same fact, so they
    # are cross-checked BOTH ways: a domain whose ladder names a subject must
    # say what that subject is, and `birth` — whose ladder is three date
    # grains and whose entry has no subject — must not pretend it has one.
    named = identity_rung(row) is not None
    if named and row["identity_kind"] not in IDENTITY_KINDS:
        _refuse(f"names a subject at rung {identity_rung(row)!r} but declares "
                f"identity_kind {row['identity_kind']!r}")
    if not named and row["identity_kind"]:
        _refuse(f"declares identity_kind {row['identity_kind']!r} but its "
                "ladder names no subject")

    # The three consistency rules that make the fields non-overlapping.
    if row["collection"] == "singleton":
        if row["per_entry_ladder"]:
            _refuse("is a singleton and cannot have a per-entry ladder")
        if row["closure"] == "user_completable":
            _refuse("is a singleton and has no group for the person to close")
    elif not row["per_entry_ladder"] and named:
        _refuse("holds many named entries but declares no per-entry ladder")


def domain_row(domain: object, *, framework_root: str | Path | None = None) -> dict:
    """One domain's row, by key. Raises on an unknown domain — closed set."""
    key = str(domain or "").strip()
    for row in load_questions(framework_root):
        if row["domain"] == key:
            return row
    raise LandmarkInteractionError(f"unknown landmark domain: {key!r}")


def onboarding_domains(framework_root: str | Path | None = None) -> tuple[str, ...]:
    """The domains asked at onboarding, in order (owner ruling 1)."""
    return tuple(row["domain"] for row in load_questions(framework_root)
                 if row["onboarding"])


# --------------------------------------------------------------------------
# The none terminal (owner ruling 6, 2026-08-24)
# --------------------------------------------------------------------------

#: The ladder rung that makes a domain answerable with "that never happened".
#: A domain whose ladder OPENS here asks a yes/no first — "did you serve?",
#: "do you have children?" — so "no" is a complete, final answer to the whole
#: domain, not a rung below target. Domains that open at `year`, `city`,
#: `name` or `what` ask for a THING, and their emptiness is not something a
#: person can assert in one word.
NONE_OPENER = "happened"


def domain_accepts_none(row: object) -> bool:
    """True when this domain can be answered ``none`` — and be DONE.

    Derived from the question set rather than declared beside it: the set
    already says which domains open with :data:`NONE_OPENER`, and those are
    exactly the ones a person can close by saying it never happened
    (`landmarks.md` §5.2). Gating matters — `{"domain": "birth", "none":
    true}` would complete the axis with no date and take
    `chronology.from_age` down with it.

    v202's ninth domain `family` is deliberately outside the gate, and the
    derivation reaches that on its own: its ladder opens at ``who``, because
    it is an ENUMERATION of people. "No siblings" does not mean there was no
    family — there are still parents and grandparents — so a family chain is
    finished the way every chain is, with ``chain_complete``, not with a none.
    A domain answered "none" is a domain that never existed; a chain answered
    "that's everyone" is a domain fully enumerated. They are different facts.
    """
    if not isinstance(row, dict):
        return False
    ladder = tuple(row.get("ladder") or ())
    return bool(ladder) and ladder[0] == NONE_OPENER


def none_domains(framework_root: str | Path | None = None) -> tuple[str, ...]:
    """Every domain a person can close with "that never happened", in order."""
    return tuple(row["domain"] for row in load_questions(framework_root)
                 if domain_accepts_none(row))


def is_none_entry(entry: object, row: object) -> bool:
    """True when this filed entry IS the domain's none terminal."""
    return (isinstance(entry, dict) and entry.get("none") is True
            and domain_accepts_none(row))


#: Keys that are bookkeeping rather than something the person said.
_NON_ANSWER_KEYS = frozenset({"domain", "none", "skipped", "chain_complete"})


def asserts_happened(entry: object) -> bool:
    """True when this entry answers ``happened`` by carrying anything at all.

    A live find, 2026-08-24: the founder named all four of his children with a
    span, and the row still read `open`, because the model filled `label` and
    `span` and nobody had filled `happened` — so the ladder's FIRST rung was
    unsatisfied and :func:`rung_reached` returned None for a fully answered
    domain. `happened` is not a fact anyone states separately; it is entailed
    by every other fact in the domain. You cannot name your children without
    having children.

    Read-side, deliberately: entries already filed in real vaults are healed
    by this the next time they are read, with no migration.
    """
    if not isinstance(entry, dict):
        return False
    return any(value not in (None, "", (), [], {})
               for key, value in entry.items()
               if key not in _NON_ANSWER_KEYS)


# --------------------------------------------------------------------------
# The specificity ladder (owner ruling 3)
# --------------------------------------------------------------------------

#: What each rung asks for, per domain. `{label}` is the subject when there is
#: one (a place, a school, a person); the bare form opens the domain.
#:
#: v219 — NO STANDALONE QUESTION OMITS ITS TARGET (audited plan §10,
#: "Questions and surfaces"). Every rung PAST the domain's
#: :func:`identity_rung` names its subject, because those are exactly the
#: rungs that reach a standalone surface: `incomplete_subjects` renders them
#: as their own Timeline unknown and the queue can mint one as the day's
#: question, where "Do you remember the month?" is a question about nothing.
#: The identity rung and the domain opener are the exemption, and the only
#: one — they are asking FOR the name. `test_no_standalone_question_omits_its
#: _subject` walks the rendered product objects, not the table.
RUNG_TEXTS = {
    ("birth", "year"): "What year were you born?",
    ("birth", "month"): "What month?",
    ("birth", "day"): "And the day?",
    # v202 (family-landmark): the constellation. `birth` is the direct year
    # question, permitted here for exactly the reason it is permitted for the
    # person's own birthday — a birth year is overlearned semantic knowledge,
    # not a reconstruction (landmarks.md §2.1 + §2.9).
    ("family", "who"): "Who was in your family growing up — brothers and sisters?",
    ("family", "relation"): "And how is {label} related to you?",
    ("family", "birth"): "What year was {label} born?",
    ("family", "living"): "Is {label} still with us?",
    ("residences", "city"): "Do you remember where you lived? Where was that?",
    ("residences", "address"): "Do you remember the address on {label}?",
    ("residences", "span"): "When did you move into {label}, and when did you leave?",
    ("residences", "household"): "Who else was in the house on {label}?",
    ("schools", "name"): "Which schools did you go to?",
    ("schools", "place"): "Where was {label} — what town?",
    ("schools", "grades"): "Which grades were you at {label}?",
    ("schools", "span"): "Roughly when did you start and finish at {label}?",
    ("partnerships", "happened"): "Have you ever been married, or had a long partnership?",
    ("partnerships", "who"): "Who was that?",
    ("partnerships", "year"): "Roughly when did you and {label} get together?",
    ("partnerships", "month"): "Do you remember the month you and {label} got together?",
    ("children", "happened"): "Do you have children?",
    ("children", "who"): "What are their names?",
    ("children", "year"): "What year was {label} born?",
    ("children", "month"): "Do you remember the month {label} was born?",
    ("work", "what"): "What work have you done?",
    ("work", "where"): "Where were you doing {label}?",
    ("work", "span"): "Roughly what years were you at {label}?",
    ("military", "happened"): "Did you serve?",
    ("military", "branch"): "Which branch?",
    ("military", "span"): "When did you go into the {label}, and when did you come out?",
    ("losses", "happened"): "Is there someone you have lost that belongs on this?",
    ("losses", "who"): "Who was that?",
    ("losses", "year"): "Roughly when did you lose {label}?",
}

#: The DISTINCT events a domain dates, as distinct asks (audited plan §2.2).
#: One rung cannot say three things: "when did this part begin?" is
#: insufficient for a partnership, whose first meeting, start of dating and
#: marriage are three events with three independent dates. `date_semantics`
#: declares which events a domain has; this table gives each of them its own
#: subject-named question, and the ladder-consistency guard requires a text
#: for every declared semantic of every enumerating domain.
#:
#: Question TEXT only in v219. Per-event claim RECORDS are Wave C's — a
#: partnership entry still carries one date today, and inventing a second
#: storage shape here would be the half-built machine the plan forbids.
EVENT_QUESTION_TEXTS = {
    ("family", "birth"): "What year was {label} born?",
    ("residences", "span"):
        "When did you move into {label}, and when did you leave?",
    ("schools", "span"): "Roughly when did you start and finish at {label}?",
    ("partnerships", "first_met"): "When did you and {label} first meet?",
    ("partnerships", "dating_started"): "When did you and {label} start dating?",
    ("partnerships", "married"): "When did you and {label} get married?",
    ("children", "birth"): "What year was {label} born?",
    ("work", "span"): "Roughly what years were you at {label}?",
    ("military", "span"):
        "When did you go into the {label}, and when did you come out?",
    ("losses", "death"): "Roughly when did you lose {label}?",
}


def event_questions(row: object, label: object) -> tuple[dict, ...]:
    """One precise, subject-named ask per event this domain dates.

    ``({"event": "first_met", "text": "When did you and Katie first meet?"},
    ...)`` — empty for a domain that does not enumerate subjects, and for a
    label nobody named. A single-event domain returns exactly one row, so a
    caller never special-cases `partnerships`: the split is data.
    """
    name = str(label or "").strip()
    if not name or not enumerates_subjects(row):
        return ()
    domain = str(row.get("domain") or "")
    rows: list[dict] = []
    for event in date_semantics(row):
        text = EVENT_QUESTION_TEXTS.get((domain, event))
        if text is None:
            raise LandmarkInteractionError(
                f"no event question for {domain}.{event}")
        rows.append({"event": event, "text": text.format(label=name)})
    return tuple(rows)


#: A rung the person has not reached costs more to ask than one they have.
#: The ladder is walked one rung at a time, never skipped ahead.
LADDER_COST = {"city": 1, "name": 1, "what": 1, "happened": 1, "year": 1,
               "who": 2, "place": 2, "where": 2, "branch": 2, "month": 2,
               "relation": 2, "birth": 2,
               "address": 3, "grades": 3, "day": 3,
               "span": 4, "household": 5, "living": 5}
DEFAULT_RUNG_COST = 3

#: A rung whose cost differs in ONE domain. `who` is a FOLLOW-UP rung in
#: partnerships, children and losses (something has to have happened first),
#: so it costs 2 — but it is `family`'s OPENER, and every other domain's
#: opener costs 1 because a name is the cheapest thing anyone can give.
#: Without this the family row sorts behind the residence chain in
#: `open_landmarks` and `build_landmarks_plan`, which inverts the reason the
#: domain exists (v202 §A.1: it is the cheapest anchor per question in the set).
DOMAIN_RUNG_COST = {("family", "who"): 1}

#: lifehug#207: the rungs a DateRecord satisfies on its own, and the grain each
#: one needs. The package's own CLI and turn writers produce ONE ``date``
#: record with no per-grain keys, so before this table a day-precision birthday
#: left the domain ``partial`` with ``next = year`` forever (found live on the
#: platform, lifehug-platform#613). ``span`` already had this fallback; the
#: date-grain rungs now have it too — including v202's ``family.birth``, which
#: is a relative's birth YEAR and is stored the same way.
_DATE_GRAIN_RUNGS = {"birth": 1, "year": 1, "month": 2, "day": 3}

#: How far up ``_DATE_GRAIN_RUNGS`` a granularity actually reaches. Season,
#: range and era rank 0 and fill nothing — a coarse date is still an ANSWER
#: (owner ruling 3), it just does not claim a month.
_GRAIN_RANK = {"year": 1, "month": 2, "day": 3}


def _date_grain_reaches(entry: dict, rung: str) -> bool:
    """True when this entry's own ``date`` record resolves ``rung``'s grain."""
    record = entry.get("date")
    if not isinstance(record, dict):
        return False
    grain = str(record.get("granularity") or "").strip().lower()
    return _GRAIN_RANK.get(grain, 0) >= _DATE_GRAIN_RUNGS[rung]


#: lifehug#219: the fields the WRITER puts a subject's IDENTITY in. The turn
#: contract tells the model to put "the school in ``label``", and
#: `timeline.save_landmark` merges entries BY ``label`` — so ``label`` is the
#: field every filed landmark carries its subject under, whatever that domain
#: calls the rung. ``name`` rides along because it is `schools`' own rung word
#: and a writer that reaches for it directly is naming the same thing.
IDENTITY_FIELDS = ("label", "name")

#: A label that is not a name. `_rung` renders an unnamed subject as "that
#: one" and `anchors_from_landmarks` falls back to the domain word, so both
#: can be written back into an entry by a careless caller; neither is somebody
#: the person named, and neither may satisfy an identity rung.
_PLACEHOLDER_LABELS = frozenset({"that one", "unknown", "unnamed", "n/a",
                                 "none", "someone", "?", "-", "—"})


def identity_rung(row: object) -> str | None:
    """The rung whose answer IS what the entry is called, or None.

    DERIVED from the ladder, never a hand-written per-domain list (the
    recurring-defect doctrine): it is the first rung that is neither
    :data:`NONE_OPENER` — entailed by everything else, and a yes, not a name —
    nor a date grain, because a date is not a name either. That lands on
    ``family.who``, ``partnerships.who``, ``children.who``, ``losses.who``,
    ``residences.city``, ``schools.name``, ``work.what`` and
    ``military.branch``, and on nothing at all for ``birth``, whose ladder is
    three date grains and whose entry has no subject to name.
    """
    ladder = tuple(row.get("ladder") or ()) if isinstance(row, dict) else ()
    for rung in ladder:
        if rung == NONE_OPENER or rung in _DATE_GRAIN_RUNGS:
            continue
        return rung
    return None


def identity_named(entry: object, row: object) -> str | None:
    """The subject this entry names, read from the writer's own fields.

    lifehug#219, live on the founder's own vault and confirmed by the
    executed certification audit (lifehug-platform#586): the store held
    ``partnerships`` with his wife's name in ``label`` and ``children`` with
    all four of his children labelled, and `/timeline` went on asking *"Who
    was that?"* and *"What are their names?"* — because
    :func:`rung_reached` counted the ``who`` rung only under a ``who`` key
    that the writer never emits. The ladder could not read what the writer
    writes; this is the same defect class as lifehug#207's date grains and
    v199's span, and it is fixed the same way — READ-SIDE, so vaults already
    written heal on the next read with no migration.

    Structural, never fuzzy: a non-empty, non-placeholder identity field is a
    name (a name-LIST is still names); an empty one, a whitespace one, the
    domain word itself, or one of :data:`_PLACEHOLDER_LABELS` is not.
    """
    if not isinstance(entry, dict) or not isinstance(row, dict):
        return None
    domain = str(row.get("domain") or "").strip().lower()
    for field in IDENTITY_FIELDS:
        text = entry.get(field)
        if not isinstance(text, str):
            continue
        cleaned = text.strip()
        lowered = cleaned.lower()
        if not cleaned or lowered in _PLACEHOLDER_LABELS or lowered == domain:
            continue
        return cleaned
    return None


#: Fields a landmark record carries that are NOT ladder rungs and never will
#: be: the bookkeeping keys plus the free-text descriptors. Named so the
#: ladder-consistency guard can tell "not a rung" from "a rung the writer
#: cannot reach", which is the shape of every defect in this class so far.
NON_RUNG_FIELDS = _NON_ANSWER_KEYS | frozenset({"place", "subject", "birth_order"})

#: Fields :func:`validate_landmark` stores on EVERY domain, because the record
#: shape is domain-agnostic — so a domain with no matching rung files them and
#: never reads them. Named rather than tolerated: the ladder-consistency guard
#: pins the exact ``(domain, field)`` pairs, so this slack cannot grow. Both
#: live ones are real: a ``span`` on `children` is the shape the founder's own
#: entry had, and a ``label`` on `birth` names a subject the axis has not got.
DOMAIN_AGNOSTIC_FIELDS = frozenset({"label", "span"})


def rung_satisfiers(row: object, rung: str) -> tuple[str, ...]:
    """Every entry field that can satisfy ``rung``, its own key first.

    ONE definition of *what answers this rung*, so the ladder-consistency
    guard can walk it and a rung the writer cannot reach fails the build
    instead of stranding a real vault. The three fallbacks are the three
    defects this class has already shipped:

    * ``span`` → ``date`` (v199)
    * the date grains → ``date`` (lifehug#207)
    * the identity rung → ``label`` / ``name`` (lifehug#219)

    :data:`NONE_OPENER` is the one rung with no named satisfier — it is
    entailed by ANY answer field at all (:func:`asserts_happened`), which is a
    shape rather than a field, and the guard says so out loud.
    """
    if not isinstance(row, dict) or rung not in tuple(row.get("ladder") or ()):
        raise LandmarkInteractionError(
            f"{rung!r} is not a rung of {(row or {}).get('domain')!r}")
    fields = [rung]
    if rung == "span" or rung in _DATE_GRAIN_RUNGS:
        fields.append("date")
    elif rung == identity_rung(row):
        fields.extend(IDENTITY_FIELDS)
    return tuple(dict.fromkeys(fields))


def unreadable_fields(entry: object, row: object) -> tuple[str, ...]:
    """The fields this entry carries that NO rung of its domain can read.

    v214 (lifehug#227), and the recurring-defect doctrine applied to the
    ladder-consistency guard's own leg 4: the guard derived this inline to
    pin :data:`DOMAIN_AGNOSTIC_FIELDS`, and the store now needs the same
    sentence to recognize a machine-written shape. One definition, both
    callers.

    A field is unreadable when it is neither a rung of the domain, nor a
    declared :func:`rung_satisfiers` of one, nor bookkeeping
    (:data:`NON_RUNG_FIELDS`). The live instance is a ``span`` on
    ``children``, whose ladder is `happened | who | year | month` and has no
    span at all: the founder's four children were filed as ONE entry with a
    span across all four birthdays, and every rung below `who` read nothing.
    """
    if not isinstance(entry, dict) or not isinstance(row, dict):
        return ()
    ladder = list(row.get("ladder") or ())
    satisfiers = {field for rung in ladder
                  for field in rung_satisfiers(row, rung)}
    return tuple(field for field in entry
                 if field not in ladder and field not in satisfiers
                 and field not in NON_RUNG_FIELDS)


def rung_reached(entry: object, row: object) -> str | None:
    """The finest ladder rung this entry actually satisfies, or None.

    A rung is satisfied when the entry carries a non-empty value under that
    rung's key. Rungs are checked in ladder order and the walk STOPS at the
    first unsatisfied one — a person who gave a span but no address is at
    ``address``'s predecessor, because the ladder is a ladder.

    Four rungs are satisfied by something other than a key of their own, and
    every one of them is the same defect: the ladder could not read what the
    writer writes. ``span``, since v199, and — since lifehug#207 — every rung
    in :data:`_DATE_GRAIN_RUNGS`, at the grain the entry's date record
    resolves. Since lifehug#219, the domain's :func:`identity_rung`, satisfied
    by the name the writer files under ``label`` (:func:`identity_named`) —
    the founder's four labelled children were being asked "What are their
    names?" forever. And ``happened``, the one rung nobody states outright, is
    satisfied by anything else in the entry at all (:func:`asserts_happened`);
    without that the ladder's first rung is unreachable in practice and every
    answer to a yes/no domain lands below rung one — which is what was
    happening. :func:`rung_satisfiers` is that list as data, and the
    ladder-consistency guard walks it so the next one fails the build.

    The one exception to the walk itself is the **none terminal** (owner
    ruling 6): a person who says they never served has answered the military
    ladder *to the end* — there is no branch and no span to climb to, and a
    life with none of a thing must be able to finish that domain the same way
    a life with one does. A none entry therefore reports the domain's
    ``complete_at`` rung, so every caller below — status, the next question,
    the rendered ledger — follows from this one definition instead of
    re-checking the flag.
    """
    if not isinstance(entry, dict) or not isinstance(row, dict):
        return None
    if is_none_entry(entry, row):
        ladder = tuple(row.get("ladder") or ())
        target = row.get("complete_at")
        return target if target in ladder else (ladder[-1] if ladder else None)
    reached: str | None = None
    identity = identity_rung(row)
    for rung in row.get("ladder") or ():
        value = entry.get(rung)
        if rung == "span":
            value = entry.get("span") or entry.get("date")
        elif rung in _DATE_GRAIN_RUNGS and value in (None, "", (), [], {}) \
                and _date_grain_reaches(entry, rung):
            value = True
        elif rung == NONE_OPENER and not value and asserts_happened(entry):
            value = True
        elif rung == identity and value in (None, "", (), [], {}) \
                and identity_named(entry, row):
            value = True
        if value in (None, "", (), [], {}):
            break
        reached = rung
    return reached


def status_for_domain(entries: object, row: object) -> str:
    """``open`` | ``partial`` | ``complete`` for one landmark domain.

    ``open``     nothing filed at all.
    ``partial``  filed, but at least one entry is below ``complete_at``.
    ``complete`` every entry has reached ``complete_at``, and — for a
                 ``closure: user_completable`` domain — the person has said
                 the list is finished (v219: the CLOSURE half of the old
                 `chain` flag, read on its own). A domain
                 answered with the none terminal is complete: "I never
                 served" is a finished answer, not a partial one.
    """
    if not isinstance(row, dict):
        raise LandmarkInteractionError("status_for_domain needs a domain row")
    rows = [e for e in (entries or ()) if isinstance(e, dict)]
    if not rows:
        return "open"
    ladder = list(row.get("ladder") or ())
    target = row.get("complete_at")
    target_index = ladder.index(target) if target in ladder else len(ladder) - 1
    for entry in rows:
        reached = rung_reached(entry, row)
        if reached is None or ladder.index(reached) < target_index:
            return "partial"
    if requires_declared_closure(row) and not any(
            e.get("chain_complete") or is_none_entry(e, row) for e in rows):
        return "partial"
    return "complete"


def next_rung(entries: object, row: object) -> dict | None:
    """The next thing to ask for this domain, or None when it is complete.

    Returns ``{"domain", "rung", "subject", "text", "cost"}``. The subject is
    the entry the question is about when the ladder is per-entry (a place, a
    school, a child); it is ``None`` for the domain's opening question.
    """
    if not isinstance(row, dict):
        raise LandmarkInteractionError("next_rung needs a domain row")
    domain = row["domain"]
    ladder = list(row.get("ladder") or ())
    target = row.get("complete_at")
    target_index = ladder.index(target) if target in ladder else len(ladder) - 1
    rows = [e for e in (entries or ()) if isinstance(e, dict)]
    if not rows:
        return _rung(domain, ladder[0], None)
    for entry in rows:
        reached = rung_reached(entry, row)
        index = ladder.index(reached) if reached in ladder else -1
        if index < target_index:
            # lifehug#219's read-side rule, applied to the QUESTION too: the
            # subject is whatever field the writer put the name in, so a
            # `who`-only child is asked about by name rather than as "that
            # one".
            return _rung(domain, ladder[index + 1],
                         identity_named(entry, row) or entry.get("label"))
    if requires_declared_closure(row) and not any(
            e.get("chain_complete") or is_none_entry(e, row) for e in rows):
        if domain == "family":
            # v202: which TIER is missing decides the question (see
            # FAMILY_TIER_TEXTS) — a fixed chain-more line would ask for more
            # siblings forever and never reach the elders.
            question = _rung(domain, ladder[0], None)
            question["text"] = FAMILY_TIER_TEXTS[family_next_tier(rows)]
            return question
        return _rung(domain, ladder[0], None, chain_more=True)
    return None


def _rung(domain: str, rung: str, subject: object, *, chain_more: bool = False) -> dict:
    label = str(subject).strip() if subject else ""
    text = RUNG_TEXTS.get((domain, rung))
    if text is None:
        raise LandmarkInteractionError(f"no rung text for {domain}.{rung}")
    if chain_more:
        text = CHAIN_MORE_TEXTS.get(domain, text)
    return {
        "domain": domain,
        "rung": rung,
        "subject": label or None,
        "text": text.format(label=label or "that one"),
        "cost": DOMAIN_RUNG_COST.get(
            (domain, rung), LADDER_COST.get(rung, DEFAULT_RUNG_COST)),
    }


#: Walking a chain forward is a different question from opening it.
CHAIN_MORE_TEXTS = {
    "residences": "And where did you go after that?",
    "schools": "Was there another school after that?",
    "work": "And after that?",
}

#: v202 (family-landmark): the family chain has TIERS, and the tier that is
#: missing decides the question. A single fixed "and who else?" would ask for
#: more siblings forever and never reach the elders — who are the witnesses
#: (`landmarks.md` §2.7 claim 2, §2.9). Consulted by :func:`next_rung`, which
#: is the only function holding both the entries and the row; `_rung` stays a
#: pure formatter.
FAMILY_TIERS = ("sibling", "parent", "grandparent")
FAMILY_TIER_TEXTS = {
    "sibling": "Who was in your family growing up — brothers and sisters?",
    "parent": "And your parents — what were their names?",
    "grandparent": "What about your grandparents — do you know their names?",
    None: "Anyone else in the family who belongs on this?",
}


def family_next_tier(entries: object) -> str | None:
    """The first family tier with nobody filed in it, or None when all three are.

    The tiers are walked in `FAMILY_TIERS` order — siblings, then parents, then
    grandparents — which is the order practitioner intake uses (research §2.9).
    """
    filed = {str((e or {}).get("relation") or "").strip().lower()
             for e in (entries or ()) if isinstance(e, dict)}
    for tier in FAMILY_TIERS:
        if tier not in filed:
            return tier
    return None


# --------------------------------------------------------------------------
# The landmark ledger the host renders (owner ruling 2)
# --------------------------------------------------------------------------

LANDMARK_STATUSES = ("open", "partial", "complete")


def landmark_rows(landmarks: object, *, keystone_domains: object = (),
                  framework_root: str | Path | None = None) -> tuple[dict, ...]:
    """Every domain with its status and its next question.

    This is what a host renders: ONLY the rows whose status is not
    ``complete`` are offerable, and each carries the exact next question so
    the surface never has to invent one. ``keystone: true`` marks the domain
    holding the highest-leverage anchor — the star moves with it.
    """
    filed = landmarks if isinstance(landmarks, dict) else {}
    starred = {str(k).strip() for k in (keystone_domains or ()) if str(k).strip()}
    rows: list[dict] = []
    for row in load_questions(framework_root):
        entries = filed.get(row["domain"]) or ()
        status = status_for_domain(entries, row)
        question = next_rung(entries, row)
        rows.append({
            "domain": row["domain"],
            "order": row["order"],
            "status": status,
            "onboarding": row["onboarding"],
            "sensitive": row["sensitive"],
            "precision": row["precision"],
            "unlocks": row["unlocks"],
            "count": len([e for e in entries if isinstance(e, dict)]),
            "next": question,
            "keystone": row["domain"] in starred,
        })
    return tuple(rows)


def open_landmarks(rows: object) -> tuple[dict, ...]:
    """The offerable rows, keystone first, then by ladder cost, then order.

    Complete domains never appear. Sensitive domains sort last within their
    cost — offered, never pressed (`landmarks.md` §5.2).
    """
    offerable = [r for r in (rows or ())
                 if isinstance(r, dict) and r.get("status") != "complete"]
    offerable.sort(key=lambda r: (
        not r.get("keystone"),
        bool(r.get("sensitive")),
        int((r.get("next") or {}).get("cost") or 99),
        int(r.get("order") or 99),
    ))
    return tuple(offerable)


# --------------------------------------------------------------------------
# The stage (the caller's deterministic decision)
# --------------------------------------------------------------------------

VALID_LANDMARK_STAGES = frozenset({"open", "ask", "close"})

#: Stop rules, mirroring the timeline lane: a landmark pass is never an
#: interrogation. The knobs in interaction.yaml carry the same two numbers and
#: a test pins them equal.
MAX_ASKS = 4
STOP_AFTER_SKIPS = 2


def landmark_stage_for_session(session: object, *, user_leaving: bool = False,
                               all_settled: bool = False,
                               skip_streak: int = 0) -> str:
    """``open`` on the first turn, ``close`` when done, ``ask`` in between.

    Pure. The caller supplies the things only it can know — the router's
    departure signal, whether every offered landmark is settled, and how many
    skips in a row the person has given.
    """
    turns = _user_turns(session)
    if turns <= 0:
        return "open"
    if user_leaving or all_settled:
        return "close"
    if skip_streak >= STOP_AFTER_SKIPS or turns >= MAX_ASKS:
        return "close"
    return "ask"


def _user_turns(session: object) -> int:
    if not isinstance(session, dict):
        return 0
    turns = session.get("turns")
    if not isinstance(turns, list):
        return 0
    return sum(1 for t in turns if isinstance(t, dict) and t.get("role") == "user")


# --------------------------------------------------------------------------
# The one additive turn-output field
# --------------------------------------------------------------------------

#: Free-text fields a landmark record may carry, and their length caps. A
#: label is a name, not a story.
#: v202 (family-landmark): ``birth_order`` ("two years older", "the middle
#: of five") is a free-text FIELD, not a ladder rung, so an unstated birth
#: order can never block the family ladder from reaching ``birth``.
_TEXT_CAPS = {"label": 120, "place": 120, "subject": 120, "birth_order": 60}

#: Ladder rungs whose value is a real bool rather than a string. ``living``
#: is TRI-STATE: absent means unknown, and ``False`` is a fact the person
#: stated — it must survive validation, so the string branch is not enough.
_BOOL_RUNGS = frozenset({"living"})
_RUNG_MAX_CHARS = 32


def validate_landmark(value: object, *,
                      framework_root: str | Path | None = None) -> dict | None:
    """Closed validation of the model's one additive output field.

    Accepts ``{"domain", "label", "date"?, "place"?, "subject"?,
    "chain_complete"?, "skipped"?, "none"?}``. Returns the normalized record,
    or None when the value is unusable, absent, or a skip with nothing in it.
    The domain must be one the question set declares — an invented domain is
    dropped, never stored.

    ``none`` is the terminal (owner ruling 6) and outranks ``skipped``: a
    skip is "not now", a none is "there is nothing here, ever". It is honored
    only where :func:`domain_accepts_none` allows it; asserted anywhere else
    it is simply dropped, and the rest of the record is read normally.
    """
    if not isinstance(value, dict):
        return None
    domain = str(value.get("domain") or "").strip()
    if not domain:
        return None
    try:
        row = domain_row(domain, framework_root=framework_root)
    except LandmarkInteractionError:
        return None
    if value.get("none") is True and domain_accepts_none(row):
        return {"domain": domain, "none": True}
    if value.get("skipped"):
        return {"domain": domain, "skipped": True}
    record: dict = {"domain": domain}
    for field, cap in _TEXT_CAPS.items():
        text = value.get(field)
        if isinstance(text, str) and text.strip():
            record[field] = text.strip()[:cap]
    date = _normalized_date(value.get("date"))
    if date is not None:
        record["date"] = date
    span = value.get("span")
    if isinstance(span, dict):
        bounds = {}
        for bound in ("start", "end"):
            parsed = _normalized_date(span.get(bound))
            if parsed is not None:
                bounds[bound] = parsed
        if bounds:
            record["span"] = bounds
    for rung in row["ladder"]:
        if rung in ("span", "date"):
            continue
        raw = value.get(rung)
        if isinstance(raw, str) and raw.strip():
            record[rung] = raw.strip()[:_RUNG_MAX_CHARS * 4]
        elif rung in _BOOL_RUNGS and isinstance(raw, bool):
            record[rung] = raw
        elif raw is True:
            record[rung] = True
    if value.get("chain_complete"):
        record["chain_complete"] = True
    # A record that carries nothing but its domain is not a landmark.
    if len(record) == 1:
        return None
    return record


#: One date, with its bounds filled in. v217 PROMOTED this body to
#: :func:`chronology.normalized_date` — the person roster needs the identical
#: treatment for `born`/`died`, and a second copy is the duplicate definition
#: the recurring-defect doctrine forbids. The private name stays as the alias
#: its callers here already use; there is no second body.
_normalized_date = chrono.normalized_date


# --------------------------------------------------------------------------
# The lints
# --------------------------------------------------------------------------

LANDMARK_LINT_CLASSES = (
    "landmark_gates.no_year_demand",
    "landmark_gates.accepts_vague",
    "landmark_gates.no_form_voice",
    "landmark_gates.one_domain_per_turn",
    "landmark_gates.never_presses_sensitive",
    # v198 (go-deep.md §4.3): a session never names a date and asks for
    # agreement. The DEFINITION is `timeline_interaction.proposes_a_date` —
    # one definition, two callers, per the recurring-defect doctrine.
    "landmark_gates.never_proposes_a_date",
    # v212 (lifehug#221): recording is the turn's FIRST job. A turn that
    # replies warmly to a real answer and emits no `landmark` has lost the
    # recording to the conversing — the observed live failure this class
    # exists to make impossible. BLOCKING (see ANSWER_MUST_RECORD_LINT).
    "landmark_gates.answer_must_record",
)

#: The one blocking landmark lint (v212). Named as a constant because a host
#: adds it to its own runtime blocking set and feeds the retry below; every
#: other landmark class is advisory, scored over the goldens.
ANSWER_MUST_RECORD_LINT = "landmark_gates.answer_must_record"

#: The RETRYABLE recording lint (v214, ADR 0028 amendment). Its sibling above
#: fires when NOTHING was recorded; this one fires when something was and the
#: person plainly stated more entries than came back. The difference in
#: severity is the whole point: a host regenerates once on this finding and
#: then files whatever it has, because a partial record is worth more than no
#: record and a lint must never cost the person a fact they gave.
#:
#: Deliberately NOT in :data:`LANDMARK_LINT_CLASSES`, which is the closed set
#: :func:`lint_landmark_reply` scores over the REPLY goldens. The turn's own
#: additive `landmark` field is singular by the pinned turn contract, so a
#: turn that records one entry of three is obeying its contract exactly — and
#: failing it for that would punish the only behavior available to it. The
#: plural output belongs to the RECORDER, so the class that reads it does
#: too; `landmark_recorder.record_answer` is its one caller.
RECORD_EVERY_ENTRY_LINT = "landmark_gates.record_every_entry"

#: The domains where asking for a calendar year outright is legitimate
#: (landmarks.md §2.1 + §2.9): the carve-out is about the KIND of fact, not
#: about whose fact it is. A birth year — anyone's — is overlearned semantic
#: knowledge, not a reconstruction, so `birth`, `family` and `children` all
#: qualify. `children`'s own v199 rung text ("What year was {label} born?")
#: already asked it; before v202 that domain violated its own lint.
#: ONE definition; `landmarks_evals._applicable` reads this set rather than
#: re-deriving it (recurring-defect doctrine).
YEAR_OPENER_DOMAINS = frozenset({"birth", "family", "children"})

#: Asking a person to produce a year for a MEMORY is the banned move
#: (chronology.md §6 rule 1). The carve-out above is recognized by the stage's
#: own domain, not by phrasing.
_YEAR_DEMAND_RES = (
    re.compile(r"\bwhat year (?:was|did|were)\b", re.IGNORECASE),
    re.compile(r"\bwhich year\b", re.IGNORECASE),
    re.compile(r"\bcan you give me (?:the|a) year\b", re.IGNORECASE),
    re.compile(r"\bexact(?:ly)? what year\b", re.IGNORECASE),
)

#: Form voice — the thing this Interaction must never sound like.
_FORM_VOICE_RES = (
    re.compile(r"\bplease (?:enter|provide|complete|fill)\b", re.IGNORECASE),
    re.compile(r"\b(?:field|form|questionnaire|survey) (?:is |are )?(?:required|incomplete)\b",
               re.IGNORECASE),
    re.compile(r"\byou (?:still )?(?:need|have) to (?:answer|complete|finish)\b",
               re.IGNORECASE),
    re.compile(r"\b\d+ (?:of|out of) \d+ (?:remaining|left|to go)\b", re.IGNORECASE),
)

#: Pressing someone about a loss, or refusing a skip.
_PRESSURE_RES = (
    re.compile(r"\b(?:are you sure|surely|try (?:harder|again)|think (?:harder|back))\b",
               re.IGNORECASE),
    re.compile(r"\bI (?:really )?need (?:you to|to know)\b", re.IGNORECASE),
    re.compile(r"\bwe can'?t (?:move on|continue) (?:until|without)\b", re.IGNORECASE),
)

def pressure(text: object) -> object:
    """The first span where a reply refuses a skip or leans on the person.

    ONE definition, TWO callers (recurring-defect doctrine): the landmarks
    lane runs it on a sensitive domain, and the Reading Room runs it on every
    turn, because "are you sure?" over somebody's photo album is the same
    defect as "are you sure?" over a loss. `reading_room.lint_reading_room_reply`
    is the second caller.
    """
    body = text if isinstance(text, str) else ""
    for pattern in _PRESSURE_RES:
        match = pattern.search(body)
        if match:
            return match
    return None


#: A reply that treats a coarse answer as a miss.
_REJECTS_VAGUE_RES = (
    re.compile(r"\bthat'?s (?:too )?(?:vague|not specific enough|not enough)\b",
               re.IGNORECASE),
    re.compile(r"\bI (?:need|'ll need) (?:something )?more (?:specific|precise|exact)\b",
               re.IGNORECASE),
    re.compile(r"\bcan you be more (?:specific|precise|exact)\b", re.IGNORECASE),
)

_SPAN_LIMIT = 400


# --------------------------------------------------------------------------
# v212 (lifehug#221): recording is the turn's first job
# --------------------------------------------------------------------------
#
# THE FAILURE. On a landmark session the model replied warmly to a real
# answer and emitted no `landmark` at all — twice, on the same leaf. Asked
# about military service: *"I have not served in the military. It's not
# military service, but I did serve a two-year mission for my church…"* — the
# reply took up the mission and recorded nothing, where the domain's own
# answer was a plain `{"domain": "military", "none": true}`. Asked about
# losses, the person named the people they had lost; the reply named them
# back and recorded nothing. Recording lost to conversing.
#
# THE BOUNDARY, stated honestly. This is a PURE lint over text: it cannot
# read a mind and it does not try. "Substantive" is undecidable from a
# string, so the class fires on exactly two deterministic shapes, both of
# which require the caller to pass the user's own message:
#
#   1. a NEGATIVE — the person plainly denied the domain — and only where the
#      domain can carry a none terminal (`domain_accepts_none`), because only
#      there is "no" a finished answer with a record of its own; and
#   2. an ECHO — the reply repeats back a proper noun or a year the person
#      supplied in that same message. That is the model's OWN acknowledgment
#      shape: it demonstrably received a specific fact, restated it, and filed
#      nothing.
#
# Everything else is UNKNOWN and never lints. A substantive answer carrying
# no name and no year ("we lived in a little house by the river") is
# invisible to this class and that under-detection is deliberate: this lint
# blocks a send, and a false positive would punish a good turn. Ambiguity —
# including every "I don't remember" shape, which is read as a SKIP before
# anything else is considered — fails toward skip, never toward lint.

#: The person ended the topic for now. Checked FIRST and it wins outright:
#: a skip records nothing by design, and every hedged half-answer that reads
#: like one is deliberately swept in here so the ambiguity fails toward skip.
_SKIP_RES = (
    re.compile(r"\b(?:i|we) (?:don'?t|do not|can'?t|cannot|couldn'?t) "
               r"(?:really )?(?:know|remember|recall|say|tell)\b", re.IGNORECASE),
    re.compile(r"\bno (?:idea|clue|memory)\b", re.IGNORECASE),
    re.compile(r"\b(?:skip|pass on) (?:that|this|it)\b", re.IGNORECASE),
    re.compile(r"\b(?:let'?s |can we )?(?:leave|drop|park) (?:that|this|it)\b",
               re.IGNORECASE),
    re.compile(r"\b(?:not|maybe) (?:now|today|right now|another time|later)\b",
               re.IGNORECASE),
    re.compile(r"\b(?:i'?d |i would )?rather not\b", re.IGNORECASE),
    re.compile(r"\bcome back to (?:that|this|it)\b", re.IGNORECASE),
)

#: The person denied the domain outright. Only consulted where the domain
#: accepts a none terminal, so the four yes/no domains and nothing else.
_DOMAIN_NEGATIVE_RES = (
    re.compile(r"\b(?:i|we) (?:have )?never\b", re.IGNORECASE),
    re.compile(r"\bnever (?:served|married|been married|had|did)\b", re.IGNORECASE),
    re.compile(r"\b(?:i|we) (?:did|do|have|had|was|were|am|are)"
               r"(?: not|n'?t)\b", re.IGNORECASE),
    re.compile(r"\bno (?:children|kids|service|military|marriage|partner|"
               r"partnership|losses)\b", re.IGNORECASE),
    re.compile(r"\bthere (?:is|was|'s) (?:nothing|no one|nobody|none)\b",
               re.IGNORECASE),
    re.compile(r"^\s*(?:no|nope|none|nah)\b", re.IGNORECASE),
    re.compile(r"\bnot (?:really|at all|that i know of)\b", re.IGNORECASE),
)

#: Capitalized words that carry no identity, so an echo of one proves
#: nothing. Deliberately short: a relationship word ("Mom", "Dad") IS an
#: identity here, and a month name IS a date the person supplied.
_ECHO_STOPWORDS = frozenset({
    "and", "but", "for", "the", "they", "them", "their", "there", "then",
    "that", "this", "these", "those", "she", "her", "his", "him", "you",
    "your", "yes", "not", "our", "was", "were", "when", "what", "where",
    "who", "why", "how", "one", "two", "all", "just", "well", "yeah",
    "okay", "sure", "thanks", "thank", "sorry", "maybe", "some", "any",
    "actually", "also", "about",
})

_ECHO_TOKEN_RE = re.compile(r"[A-Z][A-Za-z'’\-]{2,}")
#: v218: the ONE year pattern, `chronology.YEAR_RE`. This was a private
#: fourth copy of the same sentence; the name stays because the echo rules
#: below read it, but there is no second pattern.
_ECHO_YEAR_RE = chrono.YEAR_RE
_SENTENCE_ENDERS = frozenset(".!?:;\"'“”‘’(—–-\n\r")


def _echo_terms(text: str) -> set[str]:
    """Proper nouns and years a message states, folded to lowercase.

    A capitalized word that OPENS a sentence proves nothing — English
    capitalizes there anyway — so it is skipped unless it also appears
    mid-sentence somewhere. Years are taken wherever they fall.
    """
    terms: set[str] = set()
    for match in _ECHO_TOKEN_RE.finditer(text):
        start = match.start()
        prior = text[:start].rstrip()
        if not prior or prior[-1] in _SENTENCE_ENDERS:
            continue
        token = match.group(0).lower().strip("'’-")
        if len(token) > 2 and token not in _ECHO_STOPWORDS:
            terms.add(token)
    terms.update(_ECHO_YEAR_RE.findall(text))
    return terms


def answer_shape(user_message: object, reply: object, *,
                 accepts_none: bool = False,
                 known_labels: object = ()) -> str:
    """What the person's message was, as far as a string can honestly say.

    Returns one of :data:`ANSWER_SHAPES`. ONE definition (recurring-defect
    doctrine): the lint below is its only caller today and a host that wants
    the same judgment calls this rather than re-deriving it.

    * ``"skip"`` — "not now", and every hedge that reads like one.
    * ``"negative"`` — a plain denial of a domain that can carry a none.
    * ``"substantive"`` — the reply echoes a proper noun or a year the person
      supplied in this same message: the model received a specific fact and
      said it back.
    * ``"unknown"`` — anything else, including a real answer with no name and
      no year in it. Never lints.
    """
    user_text = user_message if isinstance(user_message, str) else ""
    reply_text = reply if isinstance(reply, str) else ""
    if not user_text.strip():
        return "unknown"
    for pattern in _SKIP_RES:
        if pattern.search(user_text):
            return "skip"
    if accepts_none:
        for pattern in _DOMAIN_NEGATIVE_RES:
            if pattern.search(user_text):
                return "negative"
    known = {str(label).strip().lower() for label in (known_labels or ())
             if str(label).strip()}
    known_terms: set[str] = set()
    for label in known:
        known_terms |= _echo_terms(label.title())
        known_terms.add(label)
    shared = (_echo_terms(user_text) & _echo_terms(reply_text)) - known_terms
    if shared:
        return "substantive"
    return "unknown"


#: The closed vocabulary :func:`answer_shape` returns.
ANSWER_SHAPES = ("skip", "negative", "substantive", "unknown")

#: What a host appends to ONE regeneration when
#: :data:`ANSWER_MUST_RECORD_LINT` fires. The reply was not the problem — the
#: missing record was — so the reminder asks for the record and explicitly
#: keeps the reply.
RECORDING_REMINDER = (
    "You answered them and recorded nothing. The `landmark` field is this "
    "turn's first job, not its afterthought: emit the record for the domain "
    "you asked about{domain_clause} — the fact in the rung's own key, or "
    "{{\"domain\": \"<the domain>\", \"none\": true}} when they said plainly "
    "that it never happened. Something they said alongside it does not "
    "excuse the domain's own answer. Keep the reply you wrote; send the "
    "record with it."
)


def recording_reminder(domain: object = None) -> str:
    """:data:`RECORDING_REMINDER`, with the asked domain named when known."""
    name = str(domain or "").strip()
    clause = f" (`{name}`)" if name else ""
    return RECORDING_REMINDER.format(domain_clause=clause)


def answer_must_record(user_message: object, record: object, *,
                       reply: object = "", domain: object = None,
                       known_labels: object = (),
                       framework_root: str | Path | None = None) -> dict | None:
    """The one definition of "they answered and nothing was recorded".

    ONE definition, TWO callers (recurring-defect doctrine): the RECORDER
    (`landmark_recorder.record_answer`, which is what actually files a
    landmark from v212 forward) runs it on its own extraction as the blocking
    backstop, and `lint_landmark_reply` runs it for a host that still reads
    the reply's own additive field. Both ask the same question of the same
    evidence.

    Returns a finding (`lint` / `detail` / `span`) or ``None``. ``record`` is
    whatever came back through validation — ONE record, or (v214) the whole
    tuple :func:`landmark_recorder.parse_recorder_output` now returns; any
    non-empty record in it clears the check, including a skip and a none.
    "Did they record ANYTHING" is this class's whole question, and one valid
    record answers it whatever else was missed — :data:`RECORD_EVERY_ENTRY_LINT`
    is the class that reads the rest. ``reply`` is the person-facing text,
    used only as the ECHO evidence described above the regexes — a recorder
    that runs with no reply at all (generation failed) still has the NEGATIVE
    signal, which is the case that matters most.
    """
    if isinstance(record, (list, tuple)):
        record = next((item for item in record
                       if isinstance(item, dict) and item), None)
    if isinstance(record, dict) and record:
        return None
    accepts_none = False
    asked = str(domain or "").strip()
    if asked:
        try:
            accepts_none = domain_accepts_none(
                domain_row(asked, framework_root=framework_root)
            )
        except LandmarkInteractionError:
            accepts_none = False
    body = reply if isinstance(reply, str) else ""
    shape = answer_shape(user_message, body, accepts_none=accepts_none,
                         known_labels=known_labels)
    if shape not in ("negative", "substantive"):
        return None
    detail = (
        "they said plainly that this never happened and nothing was recorded "
        '— a negative is the domain\'s answer: emit '
        '{"domain": "…", "none": true}'
        if shape == "negative" else
        "their own words come back in the reply and nothing was recorded — "
        "replying is not recording; emit the landmark"
    )
    return {
        "lint": ANSWER_MUST_RECORD_LINT,
        "detail": detail,
        "span": [0, min(len(body), _SPAN_LIMIT)],
    }


# --------------------------------------------------------------------------
# v214 (lifehug#227): one answer, many records
# --------------------------------------------------------------------------
#
# THE FAILURE, twice on the founder's own vault at v212. Asked what work he
# had done, he answered with about twelve jobs; the recorder's canonical
# output held exactly ONE `landmark`, both attempts degraded, and the whole
# answer was WITHHELD. Asked about his children, he named four of them with
# four exact birthdates; the writer of the day collapsed them into ONE
# aggregate entry carrying an illegal `span`, and the ladder — which reads
# per entry — went on asking who they were.
#
# Children, work, residences, family, partnerships and losses are all
# MULTI-ENTRY domains: one answer routinely carries many entries, and the
# recorder is now asked for all of them (`{"landmarks": [...]}`). This class
# is the deterministic backstop for that ask, and it is deliberately the
# WEAKER of the two recording lints: it fires on evidence that entries were
# missed, and a host answers it with ONE regeneration and then files what it
# has. It can never cost the person a record that was already made.
#
# THE BOUNDARY, stated as honestly as `answer_shape`'s. "How many entries is
# this answer?" is not decidable from a string. Two shapes ARE decidable and
# this class fires on those two and nothing else:
#
#   1. UNRECORDED NAMES — proper-noun groups in the person's own message whose
#      head word appears nowhere in any record that came back. TWO of them
#      normally, because ONE uncovered group is the ordinary shape of a
#      qualifier ("Dayton, Ohio", recorded as Dayton). One is enough only when
#      the answer is ALREADY known to be plural — two or more records came
#      back — where a leftover name is far likelier to be a missed entry than
#      a qualifier, and where the retry is the cheapest thing in the loop.
#   2. UNRECORDED YEARS — on a domain whose ladder dates each entry
#      SEPARATELY (a date grain and no `span`: birth-of-a-person and
#      event domains), the person stated two or more distinct years and
#      fewer records than that carry a date. Four birthdates, one record.
#
# And it never fires at all where the answer cannot be plural: a domain with
# no identity rung (`birth` — one person, one birthday), or a record set
# carrying the none or skip terminal, which is a whole-domain answer.

#: Word-ish tokens inside a stored record value, for the coverage test.
_RECORD_TOKEN_RE = re.compile(r"[A-Za-z'’\-]{2,}")


def _name_groups(text: object) -> tuple[tuple[str, ...], ...]:
    """Proper-noun GROUPS a message states, lowercased, in order.

    :func:`_echo_terms`' tokens, with adjacency preserved: consecutive
    capitalized words with only whitespace between them are ONE name ("James
    Edwin Thorne"), which is what makes counting entries possible at all. The
    sentence-opener and stopword rules are `_echo_terms`' own — a capital at
    the start of a sentence proves nothing about the word.
    """
    body = text if isinstance(text, str) else ""
    groups: list[tuple[str, ...]] = []
    current: list[str] = []
    last_end = -1
    for match in _ECHO_TOKEN_RE.finditer(body):
        start = match.start()
        prior = body[:start].rstrip()
        opens_sentence = not prior or prior[-1] in _SENTENCE_ENDERS
        adjacent = (bool(current) and last_end >= 0
                    and not body[last_end:start].strip()
                    and not opens_sentence)
        if not adjacent and current:
            groups.append(tuple(current))
            current = []
        last_end = match.end()
        token = match.group(0).lower().strip("'’-")
        if opens_sentence or len(token) <= 2 or token in _ECHO_STOPWORDS:
            continue
        current.append(token)
    if current:
        groups.append(tuple(current))
    return tuple(group for group in groups if group)


def _record_terms(records: object) -> set[str]:
    """Every word and year the filed records themselves carry.

    VALUES only, never keys: a record's own key names ("who", "domain") are
    the vocabulary of the store, not anything the person said, and counting
    them as coverage would hide a missed entry called Who.
    """
    terms: set[str] = set()

    def walk(value: object) -> None:
        if isinstance(value, str):
            terms.update(token.lower().strip("'’-")
                         for token in _RECORD_TOKEN_RE.findall(value))
            terms.update(_ECHO_YEAR_RE.findall(value))
        elif isinstance(value, dict):
            for item in value.values():
                walk(item)
        elif isinstance(value, (list, tuple)):
            for item in value:
                walk(item)

    for record in (records or ()):
        if isinstance(record, dict):
            walk(record)
    return terms


def records_missing_entries(user_message: object, records: object, *,
                            reply: object = "", domain: object = None,
                            known_labels: object = (),
                            framework_root: str | Path | None = None) -> dict | None:
    """The one definition of "they stated more entries than came back".

    ONE definition, one caller today: `landmark_recorder.record_answer` runs
    it over its own extraction as the retry trigger. Unlike
    :func:`answer_must_record` beside it, it is NOT run from
    :func:`lint_landmark_reply` — see :data:`RECORD_EVERY_ENTRY_LINT` for
    why a singular reply field must never be failed for being singular.

    Returns a finding (`lint` / `detail` / `span`) or ``None``. It answers
    ``None`` for everything it cannot decide — see the boundary above — and
    it is never a reason to drop or withhold a record. A false positive costs
    one regeneration and nothing else, which is why the name floor drops to
    one once the answer is already plural.
    """
    filed = [r for r in (records if isinstance(records, (list, tuple))
                         else [records]) if isinstance(r, dict) and r]
    if not filed:
        # Nothing recorded at all is `answer_must_record`'s question, not
        # this one. Two classes, two questions, no overlap.
        return None
    text = user_message if isinstance(user_message, str) else ""
    if not text.strip():
        return None
    asked = str(domain or "").strip()
    if not asked:
        return None
    try:
        row = domain_row(asked, framework_root=framework_root)
    except LandmarkInteractionError:
        return None
    if identity_rung(row) is None:
        return None
    if any(record.get("none") or record.get("skipped") for record in filed):
        # A terminal answers the WHOLE domain. There is no second entry.
        return None
    known = {str(label).strip().lower() for label in (known_labels or ())
             if str(label).strip()}
    covered = _record_terms(filed) | known
    for label in known:
        covered |= {token.lower() for token in _RECORD_TOKEN_RE.findall(label)}
    missed = [group for group in _name_groups(text) if group[0] not in covered]
    floor = 1 if len(filed) > 1 else 2
    detail = ""
    if len(missed) >= floor:
        detail = (
            f"they named {len(missed) + len(filed)} things and "
            f"{len(filed)} came back — one record per entry: "
            + ", ".join(" ".join(group) for group in missed[:4])
            + " were not recorded"
        )
    elif dates_each_entry(row):
        stated = {year for year in _ECHO_YEAR_RE.findall(text)} - known
        dated = sum(1 for record in filed if record.get("date"))
        if len(stated) >= 2 and dated < len(stated):
            detail = (
                f"they stated {len(stated)} separate dates and {dated} "
                "record(s) carry one — every entry they dated is its own "
                "record with its own date"
            )
    if not detail:
        return None
    body = reply if isinstance(reply, str) else ""
    return {
        "lint": RECORD_EVERY_ENTRY_LINT,
        "detail": detail,
        "span": [0, min(len(body), _SPAN_LIMIT)],
    }


#: What a host appends to ONE regeneration when
#: :data:`RECORD_EVERY_ENTRY_LINT` fires. It asks for the LIST and, in the
#: same breath, forbids padding it: the failure this class fixes is a lost
#: entry, and the failure it must not cause is an invented one.
MANY_RECORDS_REMINDER = (
    "You recorded {count}, and they stated more than that. One record per "
    "entry: send `{{\"landmarks\": [ ... ]}}` with EVERY entry they named "
    "for this domain{domain_clause} — each person, each job, each place its "
    "own object, carrying its own name and its own date. Record only what "
    "they said: never invent an entry, a name or a date to fill the list "
    "out, and never split one entry into two."
)


def many_records_reminder(domain: object = None, count: int = 1) -> str:
    """:data:`MANY_RECORDS_REMINDER`, with the domain and the count named."""
    name = str(domain or "").strip()
    clause = f" (`{name}`)" if name else ""
    return MANY_RECORDS_REMINDER.format(
        domain_clause=clause,
        count="one entry" if count == 1 else f"{count} entries",
    )


def lint_landmark_reply(text: object, *, stage: str, domain: object = None,
                        sensitive: bool = False,
                        domains_named: object = (),
                        landmark: object = None,
                        user_message: object = None,
                        known_labels: object = (),
                        framework_root: str | Path | None = None) -> list[dict]:
    """Deterministic findings for the seven ``landmark_gates.*`` classes.

    Pure — no model, no I/O. Findings share `conversation_lints.lint_turn`'s
    shape (`lint` / `detail` / `span`), exactly as
    `timeline_interaction.lint_timeline_reply` does, so one caller can merge
    both sets of findings uniformly. An unrecognized stage is treated as
    ``"ask"`` — fail toward the strictest ordinary rule.

    v212 (lifehug#221) adds three OPTIONAL inputs, all defaulting to the
    pre-v212 shape so every existing call site is byte-identical:

    * ``landmark`` — the ``landmark`` field this turn actually emitted (raw
      or validated; only its presence is read here). v214: a LIST of records
      is accepted here too, which is what the recorder returns now — any
      non-empty one in it clears the check.
    * ``user_message`` — the person's own message this reply answers. Without
      it, :data:`ANSWER_MUST_RECORD_LINT` cannot fire at all, because the
      only honest evidence for "they answered" lives in what they said.
    * ``known_labels`` — labels already in LANDMARKS. An echo of one is the
      model repeating something IT already had, not receiving something new,
      so those terms are excluded from the echo test.
    """
    body = text if isinstance(text, str) else ""
    if stage not in VALID_LANDMARK_STAGES:
        stage = "ask"
    findings: list[dict] = []

    def _first(patterns) -> object:
        for pattern in patterns:
            match = pattern.search(body)
            if match:
                return match
        return None

    # A birth date is the carve-out (landmarks.md §2.1 + §2.9): it is
    # overlearned semantic knowledge, not a reconstruction — and that is true
    # of a sibling's or a child's birth year exactly as of the person's own.
    if str(domain or "") not in YEAR_OPENER_DOMAINS:
        match = _first(_YEAR_DEMAND_RES)
        if match:
            findings.append({
                "lint": "landmark_gates.no_year_demand",
                "detail": "never ask for a calendar year outright — ask what else "
                          "was true then and let the date fall out",
                "span": [match.start(), match.end()],
            })

    match = _first(_REJECTS_VAGUE_RES)
    if match:
        findings.append({
            "lint": "landmark_gates.accepts_vague",
            "detail": "a coarse answer is an answer — a decade still bounds "
                      "everything it overlaps; never ask them to sharpen it",
            "span": [match.start(), match.end()],
        })

    match = _first(_FORM_VOICE_RES)
    if match:
        findings.append({
            "lint": "landmark_gates.no_form_voice",
            "detail": "this is a conversation, not a form — no counts, no "
                      "remaining, no required fields",
            "span": [match.start(), match.end()],
        })

    named = {str(d).strip() for d in (domains_named or ()) if str(d).strip()}
    if len(named) > 1:
        findings.append({
            "lint": "landmark_gates.one_domain_per_turn",
            "detail": f"asks across {len(named)} landmark domains in one turn — "
                      "one domain per turn, or it reads as intake",
            "span": [0, min(len(body), _SPAN_LIMIT)],
        })

    if sensitive:
        match = pressure(body)
        if match:
            findings.append({
                "lint": "landmark_gates.never_presses_sensitive",
                "detail": "a sensitive landmark is offered, never pressed — "
                          "dating is never worth the relationship",
                "span": [match.start(), match.end()],
            })

    # go-deep.md §4.3: the shared rule, from the shared definition.
    import timeline_interaction as _ti  # noqa: PLC0415

    proposal = _ti.proposes_a_date(body)
    if proposal is not None:
        findings.append({
            "lint": "landmark_gates.never_proposes_a_date",
            "detail": "never name a date and ask them to agree — ask, bound, "
                      "and do the arithmetic (go-deep.md §4.3, Lindsay et al. "
                      "2004)",
            "span": [proposal.start(), proposal.end()],
        })

    # v212 (lifehug#221): recording is not replying. The DEFINITION is
    # `answer_must_record` above — the recorder's own backstop — run here too
    # for a host that reads the reply's additive `landmark` field directly.
    recording = answer_must_record(
        user_message, landmark, reply=body, domain=domain,
        known_labels=known_labels, framework_root=framework_root,
    )
    if recording is not None:
        findings.append(recording)
    return findings


# --------------------------------------------------------------------------
# Filing (the package names it; the host writes it)
# --------------------------------------------------------------------------

def merge_landmark_entry(existing: object, record: object) -> dict:
    """How one filed landmark supersedes another, within a domain and label.

    The ladder revisits the same subject over many conversations, so the
    default is a MERGE — a city today, an address next week, a span after
    that, all landing on one entry. The none terminal is the exception in
    both directions, and neither direction argues with the person:

    * a none answer **replaces** whatever was there. "Actually I never
      served" is a correction, and leaving the old branch behind would keep
      contradicting it.
    * a substantive answer **clears** a standing none (and a standing skip).
      "Actually I did serve, briefly" reopens the domain at the rung the new
      answer reaches — the none record is superseded, not fought.

    One definition, so the store and every future caller agree
    (recurring-defect doctrine).
    """
    incoming = dict(record) if isinstance(record, dict) else {}
    prior = dict(existing) if isinstance(existing, dict) else {}
    if incoming.get("none") is True:
        return incoming
    merged = {**prior, **incoming}
    merged.pop("none", None)
    merged.pop("skipped", None)
    return merged


def entry_name(entry: object, row: object) -> str | None:
    """What ONE filed entry is CALLED, spelled the way it was filed.

    The READ side's identity as a NAME rather than as a merge key:
    :func:`identity_named` first (``label`` / ``name``, placeholders refused),
    then the domain's own :func:`identity_rung`, which is where a record filed
    straight to ``who`` puts the person — the founder's four children were
    filed exactly that way. Same order as :func:`landmark_entry_key`, which is
    this identity case-folded into the key two records of the same entry merge
    on.

    The one deliberate difference from that key: a PLACEHOLDER label
    (:data:`_PLACEHOLDER_LABELS`) is a fine merge key — two entries both
    called "unknown" are the same unidentified entry — and is not a name, so
    it is refused here and reads as an unnamed entry instead.

    ``None`` where the entry names nobody, which is the right answer for
    `birth`, whose ladder has no subject at all.
    """
    if not isinstance(entry, dict) or not isinstance(row, dict):
        return None
    named = identity_named(entry, row)
    if named:
        return named
    rung = identity_rung(row)
    if not rung:
        return None
    value = entry.get(rung)
    if not isinstance(value, str):
        return None
    cleaned = value.strip()
    lowered = cleaned.lower()
    if not cleaned or lowered in _PLACEHOLDER_LABELS \
            or lowered == str(row.get("domain") or "").strip().lower():
        return None
    return cleaned


def landmark_entry_key(entry: object, row: object = None) -> str:
    """The identity ONE filed entry is merged on, within its domain.

    v214 (lifehug#227). `timeline.save_landmark` merged on ``label`` alone,
    which is fine while every record carries one and catastrophic the moment
    a domain files MANY: four children filed as ``who`` with no ``label``
    all key on the empty string and collapse into a single entry — the
    aggregate shape the founder's own vault held. So the key is the same
    identity the READ side uses, in the same order (:data:`IDENTITY_FIELDS`),
    with the domain's own :func:`identity_rung` behind it — one definition of
    "which entry is this", used by the writer and the ladder alike.

    Case-folded, because "Bell Avenue" and "bell avenue" are one place. An
    entry with no identity at all keys on ``""`` and merges with the other
    unidentified entries of its domain, exactly as before — that is the right
    behavior for `birth`, whose ladder names no subject.
    """
    if not isinstance(entry, dict):
        return ""
    for field in IDENTITY_FIELDS:
        text = entry.get(field)
        if isinstance(text, str) and text.strip():
            return text.strip().casefold()
    rung = identity_rung(row) if isinstance(row, dict) else None
    if rung:
        value = entry.get(rung)
        if isinstance(value, str) and value.strip():
            return value.strip().casefold()
    return ""


def entry_superseded_by(existing: object, record: object,
                        row: object) -> bool:
    """Whether filing ``record`` retires a DIFFERENT prior entry outright.

    v214 (lifehug#227). :func:`merge_landmark_entry` says how two records of
    the SAME entry combine; this says the one thing that has to happen
    ACROSS entries, and it says it in two narrow rules. Everything else
    survives untouched — a machine that rewrites entries the person stated is
    a worse defect than the one being fixed here.

    1. **A none retires the whole domain.** "Actually I never served" is a
       correction of everything filed under `military`, however many entries
       that was — :func:`merge_landmark_entry` has always said a none
       *replaces whatever was there*, and per-domain is what that sentence
       means once a domain can hold many entries.
    2. **A substantive answer clears a standing terminal.** "Actually we did
       have children" retires the none, and a skip is not an answer to keep
       beside one — the same rule read the other way.
    3. **A clean record retires the collapsed aggregate.** An entry carrying
       a field no rung of its domain can read (:func:`unreadable_fields`) was
       written by a machine that had many entries and filed one — the
       founder's four children as a single row with a `span` across all four
       birthdays, which `children`'s ladder has no rung for. That shape is
       superseded the moment a record with no such field is filed for the
       domain. The test is the SHAPE, never the content: an entry whose every
       field its own ladder can read is an entry somebody stated, and it is
       never touched by this.
    """
    if not (isinstance(existing, dict) and isinstance(record, dict)
            and isinstance(row, dict)):
        return False
    if record.get("skipped") or not str(record.get("domain") or "").strip():
        return False
    substantive = not record.get("none")
    if not substantive:
        # Rule 1: a none is the domain's whole answer, so nothing else in the
        # domain survives it.
        return True
    terminal = is_none_entry(existing, row) or (
        bool(existing.get("skipped")) and not asserts_happened(existing))
    if terminal:
        return True
    return bool(unreadable_fields(existing, row)
                and not unreadable_fields(record, row))


def landmark_invocation(record: object) -> list[str] | None:
    """The ``lifehug.py landmark-record`` argv that files one landmark, or None.

    One writer for the whole set: a landmark with a date, a landmark with only
    a span, and a landmark with neither (a city, a school name) all file the
    same way, and `timeline.save_landmark` merges by label so the ladder's
    later rungs land on the same entry.

    A **skip** files nothing — it is not an answer. A **none** files, because
    it is: it is the answer that finishes the domain.
    """
    if not isinstance(record, dict) or record.get("skipped"):
        return None
    domain = str(record.get("domain") or "").strip()
    if not domain:
        return None
    if record.get("none") is True:
        return ["landmark-record", domain, "--none"]
    label = str(record.get("label") or "").strip()
    date = record.get("date")
    argv = ["landmark-record", domain]
    if label:
        argv += ["--label", label]
    for field in ("place", "subject"):
        value = str(record.get(field) or "").strip()
        if value:
            argv += [f"--{field}", value]
    # v202 (family-landmark): `birth_order` is a free-text field, not a rung.
    birth_order = str(record.get("birth_order") or "").strip()
    if birth_order:
        argv += ["--birth-order", birth_order]
    edtf = chrono.to_edtf(chrono.from_dict(date)) if date else None
    if edtf:
        argv += ["--date", edtf]
    span = record.get("span") if isinstance(record.get("span"), dict) else {}
    for bound in ("start", "end"):
        value = chrono.to_edtf(chrono.from_dict(span.get(bound))) if span.get(bound) else None
        if value:
            argv += [f"--{bound}", value]
    for rung in ("city", "address", "household", "name", "grades",
                 "happened", "who", "what", "where", "branch",
                 "relation", "year", "month", "day"):
        value = record.get(rung)
        if isinstance(value, str) and value.strip():
            argv += [f"--{rung}", value.strip()]
    # v202: `living` is a real bool and TRI-STATE — absent is unknown, and a
    # stated False is a fact, so it needs the two-flag form entity_verdict
    # already uses rather than a value pair.
    living = record.get("living")
    if isinstance(living, bool):
        argv.append("--living" if living else "--not-living")
    if record.get("chain_complete"):
        argv.append("--complete")
    return argv


def landmark_invocations(records: object) -> list[list[str]]:
    """Every ``landmark-record`` argv one recorder outcome files (v214).

    ONE record per entry, in the order the recorder emitted them, skips
    dropped by :func:`landmark_invocation`'s own rule. A host that files a
    recorder outcome runs exactly this list — there is no aggregate form and
    no second filing path, which is what keeps each entry its own row in
    `state/landmarks.json`.
    """
    rows = records if isinstance(records, (list, tuple)) else [records]
    argvs = []
    for record in rows:
        argv = landmark_invocation(record)
        if argv is not None:
            argvs.append(argv)
    return argvs


# --------------------------------------------------------------------------
# Anchors: the whole point (landmarks.md §3.7)
# --------------------------------------------------------------------------

#: How each landmark domain enters `timeline.anchor_index`.
ANCHOR_KINDS = {
    "birth": "birth",
    "family": "landmark",
    "residences": "residence",
    "schools": "period",
    "partnerships": "landmark",
    "children": "landmark",
    "work": "period",
    "military": "period",
    "losses": "landmark",
}


def anchors_from_landmarks(landmarks: object) -> dict:
    """``{key: {label, date, kind}}`` — the filed landmarks as an anchor index.

    This is the function that makes `chronology.from_age` reachable: the
    birthday enters as ``birth``, and every dated landmark enters with the
    kind `timeline.anchor_index` already understands.

    It is also the join between the two vocabularies. The product word for the
    question set is **Landmarks**; `anchor` already names the derived index in
    code (`anchor_index`, `basis: "anchor"`, `from_anchor`). This function is
    where one becomes the other, and **cross-dating** is the name of what
    happens next (`go-deep.md` §7).
    """
    filed = landmarks if isinstance(landmarks, dict) else {}
    index: dict[str, dict] = {}
    for domain, entries in filed.items():
        kind = ANCHOR_KINDS.get(str(domain), "landmark")
        for position, entry in enumerate(entries or (), start=1):
            if not isinstance(entry, dict):
                continue
            record = _entry_date(entry)
            if record is None:
                continue
            label = str(entry.get("label") or domain).strip()
            if domain == "birth":
                key = "birth"
            elif domain == "family":
                key = _family_anchor_key(entry, label, position)
            else:
                key = _anchor_key(domain, label, position)
            index.setdefault(key, {"label": _anchor_label(domain, label),
                                   "date": record, "kind": kind})
    return index


#: v217 (person dates): the anchor keys a ROSTER person mints. Namespaced
#: apart from `family:<relation>-<name>:birth` on purpose — the family
#: landmark is the SOURCE OF TRUTH for a family member's birth date and the
#: roster row is its derived copy, so the two must never both enter the index
#: for the same person. :func:`anchors_from_people` enforces that by slug.
PERSON_ANCHOR_KINDS = {"born": "landmark", "died": "landmark"}


def anchors_from_people(people: object, landmarks: object = None) -> dict:
    """``{key: {label, date, kind}}`` — roster people's `born`/`died` as anchors.

    This is what finally wires the `entity_date` unlock that
    `interactions/landmarks/questions.yaml` has declared on `partnerships` and
    `children` since v197 with zero consumers: a person's own dates become
    anchors the same way a family landmark's date does, so "the year my
    brother was born" can date anything else in the vault.

    **One anchor per person per fact (D10).** When BOTH a family landmark and
    a roster `born` exist for the same person, the LANDMARK WINS and the
    roster copy is skipped — the landmark store is the source of truth and the
    roster row is a derived copy of it (`person_roster_invocations` is the
    only writer of that copy). The same rule applies to `died` against a
    `losses` landmark. There is no reconciler and no second birth-date writer:
    there is one store per fact and a documented precedence.

    ``people`` is a person roster (``{"entities": [...]}``) or the entity list
    itself. ``landmarks`` is the RAW filed landmark store — the precedence
    above is resolved by person slug, which only the raw entries carry, so a
    caller that has already reduced its store to an anchor index must pass the
    raw store here (or nothing) rather than the index. Omit it and every
    roster date enters, which is correct for a caller that has no landmark
    store to duplicate.
    """
    entities = people
    if isinstance(entities, dict):
        entities = entities.get("entities")
    filed = landmarks if isinstance(landmarks, dict) and any(
        isinstance(value, list) for value in landmarks.values()) else {}
    claimed = {
        "born": {m["slug"] for m in family_members(filed)
                 if chrono.from_dict(m["date"]) is not None},
        "died": {p["slug"] for p in lost_people(filed) if p["date"] is not None},
    }
    index: dict[str, dict] = {}
    for entry in entities or ():
        if not isinstance(entry, dict):
            continue
        slug = str(entry.get("slug") or "").strip()
        if not slug:
            continue
        name = str(entry.get("name") or slug.replace("-", " ")).strip()
        for field, kind in PERSON_ANCHOR_KINDS.items():
            if slug in claimed[field]:
                continue  # the landmark store already anchors this fact
            record = chrono.from_dict(entry.get(field))
            if record is None:
                continue
            index.setdefault(f"person:{slug}:{field}",
                             {"label": _person_anchor_label(name, field),
                              "date": record, "kind": kind})
    return index


def _person_anchor_label(name: str, field: str) -> str:
    """The probe-style label, matching `_anchor_label`'s family phrasing."""
    return f"{name} was born" if field == "born" else f"{name} died"


def _entry_date(entry: dict) -> object:
    """One entry's date record — a point, or a span read as one interval.

    A span is composed through :func:`chronology.parse_edtf` so the resulting
    record carries real ``earliest``/``latest`` bounds; a half-open span
    yields the open interval EDTF already understands (``1984/..``).
    """
    direct = chrono.from_dict(entry.get("date"))
    if direct is not None:
        return direct
    span = entry.get("span") if isinstance(entry.get("span"), dict) else {}
    start = chrono.to_edtf(chrono.from_dict(span.get("start")))
    end = chrono.to_edtf(chrono.from_dict(span.get("end")))
    if not start and not end:
        return None
    if start and end:
        return chrono.parse_edtf(f"{start}/{end}", basis="stated")
    if start:
        return chrono.parse_edtf(f"{start}/..", basis="stated")
    return chrono.parse_edtf(f"../{end}", basis="stated")


_SLUG_RE = re.compile(r"[^a-z0-9]+")

#: How long a roster slug may be. The anchor keys use 40; a PERSON slug has
#: always used 60 (`family_members`, `lost_people`), and that number moves
#: here rather than being typed a third time.
PERSON_SLUG_LIMIT = 60


def person_slug(name: object) -> str:
    """``"Betty Jo Thorne"`` -> ``"betty-jo-thorne"`` — the roster slug.

    ONE definition (recurring-defect doctrine): :func:`family_members`,
    :func:`lost_people` and — from v218 — the general listener's person
    records all mint the slug a roster row is found by, and three copies of
    one lowercase-and-hyphenate line is how two of them quietly disagree.
    Returns ``""`` for anything with no slug in it, which every caller reads
    as "no row".
    """
    text = str(name or "").strip().lower()
    return _SLUG_RE.sub("-", text).strip("-")[:PERSON_SLUG_LIMIT]


def _anchor_key(domain: str, label: str, position: int) -> str:
    slug = _SLUG_RE.sub("-", label.lower()).strip("-")[:40]
    return f"{domain}-{slug or position}"


def _family_anchor_key(entry: dict, label: str, position: int) -> str:
    """``family:sibling-james:birth`` — relation-qualified, so two Jameses in
    two tiers cannot collide, and the key reads as what it is.

    The relation is the CLOSED `focus_candidate.FOCUS_RELATIONSHIPS` value
    (``sibling``), not the spoken word (``brother``): a second relationship
    vocabulary living only in anchor keys is the duplicate definition the
    recurring-defect doctrine forbids (contract §C, deviation 2).
    """
    name = _SLUG_RE.sub("-", label.lower()).strip("-")[:40] or str(position)
    relation = _SLUG_RE.sub("-", str(entry.get("relation") or "kin").lower()).strip("-")
    return f"family:{relation or 'kin'}-{name}:birth"


def _anchor_label(domain: str, label: str) -> str:
    if domain == "birth":
        return "when you were born"
    if domain == "family":
        # Renders the owner's own probe style through the existing anchored
        # opener: "Bell Avenue — was that before or after James was born?"
        return f"{label} was born"
    if domain == "residences":
        return label
    if domain == "schools":
        return label
    return label


# --------------------------------------------------------------------------
# The roster join and the witnesses (v202, family-landmark §D)
# --------------------------------------------------------------------------

#: The family tiers, as CLOSED `focus_candidate.FOCUS_RELATIONSHIPS` values.
#: There is no second relationship vocabulary: a family landmark's `relation`
#: IS the roster's `relationship`, which is why the join needs no translation
#: table and no parallel store.
FAMILY_RELATIONS = frozenset(FAMILY_TIERS)

#: The relationships that are NOT family, out of the roster's own closed
#: vocabulary (`focus_candidate.FOCUS_RELATIONSHIPS`). Named as the EXCLUSION
#: rather than as a tenth list of family words, so a relationship added to
#: that vocabulary lands on the family side by default and a test has to say
#: otherwise — the failure that matters is a stranger's birthday reaching the
#: roster, and defaulting the other way makes that failure the silent one.
NON_FAMILY_RELATIONS = frozenset({"friend", "colleague", "mentor", "other"})

#: v218 (ADR 0029), OWNER-RULED: **person dates as a user feature are FAMILY
#: ONLY.** A relationship in here is a person whose birth or death date the
#: general listener may file to the roster; anything else — a friend, a
#: colleague, a boss, an unqualified name — is anchor evidence for the
#: timeline and never a person record.
#:
#: DERIVED, never listed: the roster's closed vocabulary minus
#: :data:`NON_FAMILY_RELATIONS`. `family`'s own three tiers are in it by
#: construction, and so are the three the landmark set enumerates elsewhere —
#: `children` names a child, `partnerships` names a spouse or a partner.
#: `test_the_family_relations_are_the_roster_vocabulary_minus_the_strangers`
#: binds the derivation to `focus_candidate.FOCUS_RELATIONSHIPS`, so a new
#: relationship word cannot land here unnoticed.


def person_date_relations() -> frozenset[str]:
    """:data:`NON_FAMILY_RELATIONS` subtracted from the roster's own vocabulary.

    A function rather than a constant because `focus_candidate` is imported
    lazily everywhere in this family (it pulls the focus stack in), and the
    answer is a two-line set operation over a frozen tuple.
    """
    from focus_candidate import FOCUS_RELATIONSHIPS  # noqa: PLC0415

    return frozenset(FOCUS_RELATIONSHIPS) - NON_FAMILY_RELATIONS

def family_members(landmarks: object) -> tuple[dict, ...]:
    """Every filed family member as ``{slug, name, relation, living, date}``.

    ``living`` is TRI-STATE and stays ``None`` unless the person said so; a
    missing value is *unknown*, never "no longer with us".
    """
    filed = landmarks if isinstance(landmarks, dict) else {}
    rows: list[dict] = []
    seen: set[str] = set()
    for entry in filed.get("family") or ():
        if not isinstance(entry, dict):
            continue
        name = str(entry.get("label") or entry.get("who") or "").strip()
        if not name:
            continue
        slug = person_slug(name)
        if not slug or slug in seen:
            continue
        seen.add(slug)
        relation = str(entry.get("relation") or "").strip().lower()
        living = entry.get("living")
        rows.append({
            "slug": slug,
            "name": name,
            "relation": relation if relation in FAMILY_RELATIONS else None,
            "living": living if isinstance(living, bool) else None,
            "date": entry.get("date"),
        })
    return tuple(rows)


def lost_people(landmarks: object) -> tuple[dict, ...]:
    """Every person named in a `losses` entry, as ``{slug, name, date}``.

    v217 (person dates). `losses` is the domain whose whole point is a death
    year — its declared unlock is `terminus_ante_quem` — and before this the
    person it names never reached the roster at all: `family_members` reads
    only ``filed["family"]``, so a death date the person volunteered was
    collected and then dropped on the floor.

    ``date`` is the entry's own record read through :func:`_entry_date`, the
    same reader the anchor index uses, so a `year` rung and a `span` both
    resolve. A losses entry with no readable name yields nothing; an entry
    with a name and no date still yields a row, because knowing WHO was lost
    is itself the identity fact (`living: false`).
    """
    filed = landmarks if isinstance(landmarks, dict) else {}
    rows: list[dict] = []
    seen: set[str] = set()
    for entry in filed.get("losses") or ():
        if not isinstance(entry, dict) or entry.get("none"):
            continue
        name = str(entry.get("label") or entry.get("who") or "").strip()
        if not name:
            continue
        slug = person_slug(name)
        if not slug or slug in seen:
            continue
        seen.add(slug)
        rows.append({"slug": slug, "name": name, "date": _entry_date(entry)})
    return tuple(rows)


def person_roster_invocations(landmarks: object) -> list[list[str]]:
    """The ``entity-verdict`` argv that files each landmark-named PERSON on the
    ROSTER — the family tiers, and (v217) the people named in `losses`.

    The same "the package names it; the host writes it" split as
    :func:`landmark_invocation`. A person named in the landmark set reaches
    the roster as a PERSON entity carrying the identity facts —
    `entity_verdict`'s `--relationship` / `--living` / `--born` / `--died`
    (ADR 0013, v190, v217) are exactly the settled, refresh-surviving facts
    this is (`entity_roster._SETTLED_IDENTITY_FIELDS`).

    ``clear`` is the verdict because the landmark set asserts an IDENTITY, not
    a page verdict — graduating a brother named once would breach ADR 0013's
    >=1-mention floor. ``--ensure`` creates the entry when the roster has never
    heard the name; `entity_roster.apply_previous_decisions` folds it into the
    real entry by name/alias the moment they are actually mentioned.

    A FAMILY member with no relation yields nothing: the roster's vocabulary
    is closed, and an unqualified guess is worse than silence. A family
    member's stated birth year rides along as ``--born`` (v217) — before this
    it was collected by the `family` ladder and then discarded here.

    A LOSSES person yields ``--died`` (when the entry is dated) and always
    ``--not-living``, and carries NO ``--relationship``: the losses ladder
    never asks how the person was related, and the roster's relationship
    vocabulary is closed. The dates keep the basis of the landmark record they
    came from, so the roster copy is honestly a copy — the landmark store
    stays the source of truth, and :func:`anchors_from_people` is what keeps
    the copy from minting a duplicate anchor.

    NOTE ON SENSITIVITY: `losses` is the one `sensitive: true` domain, and a
    roster entry has nowhere to record that. Adding a sensitivity field to the
    roster is machinery this change deliberately does not invent; the created
    row is never page-eligible, exactly like the family rows, so nothing about
    the loss is published by this join.
    """
    argvs: list[list[str]] = []
    for member in family_members(landmarks):
        if not member["relation"]:
            continue
        argv = ["entity-verdict", "person", member["slug"], "clear",
                "--name", member["name"],
                "--relationship", member["relation"]]
        if member["living"] is True:
            argv.append("--living")
        elif member["living"] is False:
            argv.append("--not-living")
        argv.extend(_date_flags("born", chrono.from_dict(member["date"])))
        argv.append("--ensure")
        argvs.append(argv)
    for person in lost_people(landmarks):
        argv = ["entity-verdict", "person", person["slug"], "clear",
                "--name", person["name"], "--not-living"]
        argv.extend(_date_flags("died", person["date"]))
        argv.append("--ensure")
        argvs.append(argv)
    return argvs


def date_flags(flag: str, record: object) -> list[str]:
    """``["--born", "1948", "--born-basis", "stated"]`` for one date record.

    The basis travels with the date because the roster copy must not
    misrepresent a derived claim as a stated one: `entity_verdict`'s
    precedence rule (`_preferred_date`) reads exactly this to decide whether a
    later claim may replace an earlier one.
    """
    edtf = chrono.to_edtf(record)
    if not edtf:
        return []
    basis = getattr(record, "basis", None) or "stated"
    return [f"--{flag}", edtf, f"--{flag}-basis", str(basis)]


#: v218: PUBLIC, because the general listener emits the same two flags for a
#: person it heard a date for. The private name stays as this module's own
#: alias; there is no second body.
_date_flags = date_flags


#: v217: the pre-v217 name of :func:`person_roster_invocations`, kept because
#: hosts vendor these bytes and call it by name. One definition, two names —
#: never a second body.
family_roster_invocations = person_roster_invocations


#: The two closed lists a second person can supply COMPLETELY (`landmarks.md`
#: §2.7 claim 2). The research flags that claim as a DESIGN PREMISE, not a
#: measured finding — "is *not* measured anywhere we have found" — and this
#: does not upgrade it.
WITNESS_CAN_SUPPLY = ("residences", "schools")


def witness_candidates(landmarks: object) -> tuple[dict, ...]:
    """Living family members, as witnesses for the ask-the-living hooks.

    A **witness** is a living person who was there (`go-deep.md` §7). v200's
    `places_without_stories` sources witnesses from the residence `household`
    rung — a narrower and better claim about ONE house, deliberately left
    alone. This is the other source: the family constellation, which is where
    witnesses actually come from (`landmarks.md` §2.9).

    Only an EXPLICIT ``living: True`` qualifies. Unknown is not a witness and
    is not a non-witness, and nothing here ever invokes anybody's mortality.
    """
    return tuple({
        "slug": member["slug"],
        "name": member["name"],
        "relation": member["relation"],
        "can_supply": WITNESS_CAN_SUPPLY,
    } for member in family_members(landmarks) if member["living"] is True)


# --------------------------------------------------------------------------
# Concrete unknowns from the landmark set (v202, owner rulings 4 and 5)
# --------------------------------------------------------------------------

LANDMARK_SUBJECT_KIND = "landmark_subject"
RESIDENCE_GAP_KIND = "residence_gap"

#: How a landmark-derived unknown enters the timeline's probe vocabulary. Both
#: kinds arrive with their OWN exact question — the ladder's, subject-named —
#: so `timeline.unknowns` leaves their probe alone rather than replacing it
#: with a generic opener.
_LANDMARK_SUBJECT_STEP = "landmark"
_RESIDENCE_GAP_STEP = "residence"

RESIDENCE_GAP_OPENER = (
    "Where did you live between {first} and {second}, around {years}?"
)


def incomplete_subjects(landmarks: object, *,
                        framework_root: str | Path | None = None) -> tuple[dict, ...]:
    """One concrete unknown per HALF-FILLED subject in an enumeration domain.

    Owner ruling 4 (2026-08-24), the *unknowns are concrete* principle applied
    to the landmark set: a domain row carries exactly ONE ``next`` question no
    matter how many named people or places sit incomplete inside it. Each of
    those subjects is separately answerable, so each becomes its own unknown,
    NAMED — "What year was Jackie born?", never a generic re-ask.

    An **enumeration domain** is :func:`enumerates_subjects` — a domain whose
    `collection` holds many entries, each walking its own ladder under a name.
    v219 (lifehug-platform#664): until this release the test was
    ``chain: true``, and `chain` answered the CLOSURE question, not the
    multiplicity one. `children`, `partnerships`, `losses` and `military` hold
    many entries and are not walked lists, so all four were declared
    ``chain: false`` and skipped here — the founder named four children with
    four birth dates and got ONE aggregate gap that no answer could close.
    Eight domains enumerate; `birth` is the singleton axis and does not.

    The probe text is `next_rung`'s own rendering for that entry, so there is
    ONE definition of "the next question for this subject" and the domain row
    and the unknown can never disagree. Where a domain dates several DISTINCT
    events (`partnerships`: first meeting, the start of dating, the marriage —
    audited plan §2.2), the row also carries ``events``: one precise, subject-
    named ask per declared date semantic. Those are question TEXT only in this
    release; per-event claim records are Wave C's.
    """
    filed = landmarks if isinstance(landmarks, dict) else {}
    rows: list[dict] = []
    for row in load_questions(framework_root):
        if not enumerates_subjects(row):
            continue
        domain = row["domain"]
        ladder = list(row.get("ladder") or ())
        target = row.get("complete_at")
        target_index = ladder.index(target) if target in ladder else len(ladder) - 1
        for position, entry in enumerate(filed.get(domain) or (), start=1):
            if not isinstance(entry, dict):
                continue
            label = str(entry.get("label") or "").strip()
            if not label:
                continue
            reached = rung_reached(entry, row)
            index = ladder.index(reached) if reached in ladder else -1
            if index >= target_index:
                continue
            question = _rung(domain, ladder[index + 1], label)
            slug = _SLUG_RE.sub("-", label.lower()).strip("-")[:40]
            rows.append({
                "kind": LANDMARK_SUBJECT_KIND,
                "key": f"{LANDMARK_SUBJECT_KIND}:{domain}:{slug}",
                "label": label,
                # v208: the anchor key THIS subject's answer would mint, from
                # the same two functions `anchors_from_landmarks` uses — so
                # `timeline.unknown_anchor` can name it without a second
                # spelling of the key living in the timeline module.
                "anchor": (_family_anchor_key(entry, label, position)
                           if domain == "family"
                           else _anchor_key(domain, label, position)),
                "domain": domain,
                "rung": question["rung"],
                "identity_kind": row["identity_kind"],
                "landmark": {"domain": domain, "label": label},
                "events": event_questions(row, label),
                "probe": {"step": _LANDMARK_SUBJECT_STEP,
                          "cost": question["cost"],
                          "text": question["text"]},
            })
    return tuple(rows)


def residence_gaps(landmarks: object) -> tuple[dict, ...]:
    """The holes the residence chain leaves, as concrete unknowns.

    Owner ruling 5 (2026-08-24). The residence chain is the domain that is
    supposed to TILE the timeline (`landmarks.md` §2.7 consequence 1) — so a
    hole between two named spans is a real, answerable question with a name at
    each end: "Where did you live between Mesa and Yucaipa, around 1992-1995?"
    A partial list is accepted whole; the remaining holes persist; nothing
    nags.

    Rules:

    * **Interior only.** Nothing before the first residence (that asks about
      infancy) and nothing after the last (that is a nag).
    * **A hole needs a whole year in it** — ``end + 1 >= start`` is not a hole,
      so abutting, overlapping and consecutive-year spans mint nothing.
    * The years are **REPORTED** — the interval the person's own spans imply —
      never a date named and offered for agreement (`go-deep.md` §4.3).

    This is NOT `timeline.era_gap`: that is a hole between two dated wiki
    PERIODS. Both can surface for the same years; they are different questions
    with different answers, and neither derives the other.
    """
    filed = landmarks if isinstance(landmarks, dict) else {}
    dated: list[tuple[int, int, str]] = []
    for entry in filed.get("residences") or ():
        if not isinstance(entry, dict):
            continue
        label = str(entry.get("label") or "").strip()
        span = entry.get("span") if isinstance(entry.get("span"), dict) else {}
        start = chrono.year_of(chrono.from_dict(span.get("start")))
        end = chrono.year_of(chrono.from_dict(span.get("end")), end=True)
        if not label or start is None or end is None:
            continue
        dated.append((int(start), int(end), label))
    dated.sort()
    rows: list[dict] = []
    for (_, end, first), (start, _, second) in zip(dated, dated[1:]):
        if end + 1 >= start:
            continue
        years = f"{end}–{start}"
        first_slug = _SLUG_RE.sub("-", first.lower()).strip("-")[:40]
        second_slug = _SLUG_RE.sub("-", second.lower()).strip("-")[:40]
        rows.append({
            "kind": RESIDENCE_GAP_KIND,
            "key": f"{RESIDENCE_GAP_KIND}:{first_slug}:{second_slug}",
            "label": f"between {first} and {second}",
            "between": [first, second],
            "years": [str(end), str(start)],
            "probe": {"step": _RESIDENCE_GAP_STEP, "cost": 2,
                      "text": RESIDENCE_GAP_OPENER.format(
                          first=first, second=second, years=years)},
        })
    return tuple(rows)


# --------------------------------------------------------------------------
# The gap only a landmark can reveal (landmarks.md §5.3)
# --------------------------------------------------------------------------

#: A place the person told us about that has nothing in it. Not a DATING gap
#: (v196's `place_span` is that) — a STORY gap, and one the vault could not
#: express before a landmark named the place.
PLACE_NO_STORIES_KIND = "place_no_stories"

PLACE_NO_STORIES_OPENER = (
    "{label} — you lived there and there's nothing here from it. "
    "What happened there?"
)


def places_without_stories(landmarks: object, event_places: object = ()) -> tuple[dict, ...]:
    """Every residence with a known span and no moments attached.

    Returns unknown-shaped rows ``{kind, key, label, span, landmark, anchor,
    witnesses, probe}`` so the arc planner and the Mirror's gap finders consume
    them exactly like every other unknown.

    ``witnesses`` carries the people who were there — a witness being a living
    person who was there (`system/research/go-deep.md` §7; the term is law's
    and oral history's, "warm, honest, and free of collisions"). It comes from
    the residence ladder's own `household` rung, so no new state exists: the
    person already told us who was in the house, and those are exactly the
    people who can answer about it when they cannot.

    v200 adds three ADDITIVE fields so a consumer never re-derives what this
    function already knows (recurring-defect doctrine):

    * ``span`` — the person's OWN span, rendered the way they would recognise
      it (`chronology.display_date`, basis clause suppressed). It is what makes
      the arc-card line concrete ("they lived in Costa Mesa, 1990–1993"),
      and it is a REPORT of what they said, never a date proposed for
      agreement (`timeline_interaction.proposes_a_date`, go-deep.md §4.3).
    * ``landmark`` — ``{"domain": "residences", "label": ...}``, the reference
      back to the landmark entry this gap came from. `save_landmark` merges by
      label, so (domain, label) IS a landmark's identity.
    * ``anchor`` — the key `anchors_from_landmarks` mints for the same
      residence, so the story gap and the dating anchor can be joined without a
      second slug implementation anywhere.
    """
    filed = landmarks if isinstance(landmarks, dict) else {}
    seen = {str(p).strip().lower() for p in (event_places or ()) if str(p).strip()}
    rows: list[dict] = []
    for position, entry in enumerate(filed.get("residences") or (), start=1):
        if not isinstance(entry, dict):
            continue
        label = str(entry.get("label") or "").strip()
        if not label or label.lower() in seen:
            continue
        record = _entry_date(entry)
        if record is None:
            continue  # its span is the dating gap v196 already asks about
        anchor = _anchor_key("residences", label, position)
        household = str(entry.get("household") or "").strip()
        rows.append({
            "kind": PLACE_NO_STORIES_KIND,
            "key": f"{PLACE_NO_STORIES_KIND}:{anchor}",
            "label": label,
            "span": chrono.display_date(record, with_basis=False),
            "landmark": {"domain": "residences", "label": label},
            "anchor": anchor,
            "witnesses": household or None,
            "probe": {"step": "content", "cost": 1,
                      "text": PLACE_NO_STORIES_OPENER.format(label=label)},
        })
    return tuple(rows)


#: How a place-with-no-stories reads in a prompt. The sibling of
#: `timeline_interaction.render_whisper`, and deliberately the same shape: it
#: states what we know, names the gap, and hands the ask over as an
#: invitation — "if it fits" — rather than a script. The span is REPORTED
#: (the person's own words, back to them, showing the working); nothing here
#: names a date and invites agreement.
PLACE_NO_STORIES_LINE = (
    "{kind} — they lived in {label}{span} and there are no stories from "
    "there yet; if it fits, ask what life was like there"
)


def render_place_no_stories(item: object) -> str:
    """The place-with-no-stories intent's ONE rendering (v200).

    Degrades to the bare kind name when the intent carries no probe, exactly
    as `render_whisper` does — which is what keeps a bare
    ``{"kind": "place_no_stories"}`` intent rendering byte-for-byte like every
    other kind in `conversation._assemble_session_block`.
    """
    row = item if isinstance(item, dict) else {}
    probe = row.get("probe")
    probe_text = probe.get("text") if isinstance(probe, dict) else probe
    label = str(row.get("place") or row.get("label") or "").strip()
    if not str(probe_text or "").strip() or not label:
        return PLACE_NO_STORIES_KIND
    span = str(row.get("span") or "").strip()
    line = PLACE_NO_STORIES_LINE.format(
        kind=PLACE_NO_STORIES_KIND, label=label,
        span=f", {span}," if span else "",
    )
    witnesses = str(row.get("witnesses") or "").strip()
    if witnesses:
        line = f"{line} — someone who was there: {witnesses}"
    return line


# --------------------------------------------------------------------------
# The read-only plan verb
# --------------------------------------------------------------------------

DEFAULT_LANDMARK_PLAN_SIZE = 6


def build_landmarks_plan(landmarks: object, *, keystone_domains: object = (),
                         limit: int = DEFAULT_LANDMARK_PLAN_SIZE,
                         framework_root: str | Path | None = None) -> dict:
    """One Play's worth of open landmarks, best first.

    ``{"count", "complete", "items": [{domain, status, rung, text, keystone}]}``
    """
    rows = landmark_rows(landmarks, keystone_domains=keystone_domains,
                         framework_root=framework_root)
    offerable = open_landmarks(rows)
    items = []
    for row in offerable[:max(int(limit), 0)]:
        question = row.get("next") or {}
        items.append({
            "domain": row["domain"],
            "status": row["status"],
            "rung": question.get("rung"),
            "subject": question.get("subject"),
            "text": question.get("text"),
            "keystone": bool(row.get("keystone")),
            "sensitive": bool(row.get("sensitive")),
        })
    return {
        "count": len(offerable),
        "complete": sum(1 for r in rows if r["status"] == "complete"),
        "total": len(rows),
        "items": items,
    }


def describe_landmarks_plan(plan: object) -> list[str]:
    """Human lines for the CLI."""
    if not isinstance(plan, dict):
        return []
    lines = [f"Landmarks: {plan.get('complete', 0)} of {plan.get('total', 0)} complete, "
             f"{plan.get('count', 0)} open"]
    for item in plan.get("items") or ():
        star = "★ " if item.get("keystone") else "  "
        lines.append(f"{star}{item.get('domain')} [{item.get('status')}] "
                     f"— {item.get('text')}")
    return lines


def render_landmarks(rows: object, *, limit: int = 8) -> str:
    """The CONVERSATION's `{landmarks}` block — one line per DOMAIN, status
    only, so the model never asks for a domain twice.

    Its sibling :func:`render_known_entries` is the RECORDER's block and names
    the entries themselves: a status line is the right thing to show someone
    deciding what to ask, and the wrong thing to show a machine deciding what
    to file (v216, and the reason `- children: partial (4)` could not stop a
    single duplicate).
    """
    lines = []
    for row in (rows or ())[:max(int(limit), 0)]:
        if not isinstance(row, dict) or row.get("status") == "open":
            continue
        count = row.get("count") or 0
        lines.append(f"- {row.get('domain')}: {row.get('status')}"
                     + (f" ({count})" if count else ""))
    return "\n".join(lines) if lines else "(nothing yet)"


# --------------------------------------------------------------------------
# What is ALREADY FILED, per domain (v216, lifehug#230)
# --------------------------------------------------------------------------
#
# THE DEFECT the design audit found (D7). The recorder's leaf has carried the
# heading "ALREADY KNOWN — never record these again" since v212, and what was
# rendered under it was `render_landmarks` above: one line per DOMAIN, saying
# `- children: partial (4)`. A model cannot avoid re-filing four children it
# has never been shown. The instruction was unactionable, so a re-answer — the
# ordinary shape of a person going back over their own life, and the shape the
# per-turn listener will make routine — re-emits facts already in the store,
# and `answer_shape` then reads their own names coming back as fresh evidence.
#
# So the block names the ENTRIES. One rendering definition, here beside the
# ladder that reads them (`rung_reached`), so the prompt and any future host
# render a filed entry the same way — and `known_entry_labels` beside it is
# the ONE derivation both the block and the `known_labels` lint input come
# from, rather than two lists of names that can disagree.

#: How many filed entries :func:`render_known_entries` names before it stops
#: and says how many more there are. Twelve is a working life's worth of jobs
#: — the founder's own answer — and the tail keeps the block honest about
#: being a window rather than the whole store.
KNOWN_ENTRIES_LIMIT = 12

#: What :func:`render_known_entries` says when a domain holds nothing yet.
NO_KNOWN_ENTRIES = "(nothing filed for this domain yet)"


def landmark_entries(landmarks: object, domain: object) -> tuple[dict, ...]:
    """The entries filed under ONE domain, in whichever shape the caller has.

    ONE accessor for the store's own shape: a dict is the LANDMARKS store
    (``{domain: [entry, ...]}``) and is indexed by ``domain``; a list or tuple
    is that domain's entries, already selected by the caller. Anything else,
    and any non-dict or empty member, is nothing.
    """
    name = str(domain or "").strip()
    rows: object = (landmarks.get(name) if isinstance(landmarks, dict)
                    else landmarks)
    if not isinstance(rows, (list, tuple)):
        return ()
    return tuple(entry for entry in rows if isinstance(entry, dict) and entry)


def render_entry(entry: object, row: object) -> str:
    """ONE filed entry as one line: what it is called, and what is dated on it.

    The name comes from :func:`entry_name` — the same identity the ladder and
    the merge key read — and the date from the entry's own record or span,
    rendered the way the person would recognise it
    (:func:`chronology.display_date`, basis clause suppressed, exactly as
    :func:`places_without_stories` reports a span). A domain with no identity
    rung (`birth`) has no subject to name, so its line is the date alone.

    The two terminals say what they are: a domain answered with a no, or one
    the person declined, is filed and must never be re-filed as a fact.
    """
    if not isinstance(entry, dict) or not entry or not isinstance(row, dict):
        return ""
    if is_none_entry(entry, row):
        return "- (they said plainly this never happened)"
    if entry.get("skipped") is True:
        return "- (they declined this for now)"
    record = _entry_date(entry)
    dated = chrono.display_date(record, with_basis=False) if record else ""
    dated = dated.strip() or "no date filed"
    name = entry_name(entry, row)
    if identity_rung(row) is None:
        return f"- {dated}"
    return f"- {name or '(unnamed)'} — {dated}"


def render_known_entries(landmarks: object, domain: object, *,
                         limit: int = KNOWN_ENTRIES_LIMIT,
                         framework_root: str | Path | None = None) -> str:
    """The recorder's ``{known_entries}`` block — this domain's filed entries.

    What the store already holds for the ONE domain being asked about, one
    line per entry, so "never record these again" is something a model can
    actually act on. Other domains are not in it: the recorder can only emit
    records for the domain it was given, so a status line about another one is
    noise in a prompt whose whole virtue is being small.
    """
    row = domain_row(domain, framework_root=framework_root)
    entries = landmark_entries(landmarks, domain)
    ceiling = max(int(limit), 0)
    lines = [line for line in (render_entry(entry, row)
                               for entry in entries[:ceiling]) if line]
    if not lines:
        return NO_KNOWN_ENTRIES
    hidden = len(entries) - ceiling
    if hidden > 0:
        lines.append(f"- …and {hidden} more already filed for this domain")
    return "\n".join(lines)


def known_entry_labels(landmarks: object, domain: object, *,
                       extra: object = (),
                       framework_root: str | Path | None = None
                       ) -> tuple[str, ...]:
    """The names ALREADY filed for a domain — the ``known_labels`` derivation.

    ONE derivation, THREE consumers (recurring-defect doctrine): the
    ``{known_entries}`` block the recorder shows the model,
    :func:`answer_shape` (through :func:`answer_must_record`), which must not
    read a name it supplied itself coming back as the person's own evidence,
    and :func:`records_missing_entries`, which must not retry for an entry
    that is already in the store. Before v216 that argument was hand-passed at
    each call site, which is to say it was empty everywhere.

    ``extra`` is unioned in for a host holding names from somewhere else (a
    roster, a prior turn); order is the store's, then the extras, and the
    first spelling of a name wins.
    """
    row = domain_row(domain, framework_root=framework_root)
    names: list[str] = []
    seen: set[str] = set()
    candidates = [entry_name(entry, row)
                  for entry in landmark_entries(landmarks, domain)]
    candidates.extend(extra or ())
    for candidate in candidates:
        text = str(candidate or "").strip()
        key = text.casefold()
        if not text or key in seen:
            continue
        seen.add(key)
        names.append(text)
    return tuple(names)


def main(argv: list[str] | None = None) -> int:
    import argparse  # noqa: PLC0415
    import json  # noqa: PLC0415

    import timeline  # noqa: PLC0415

    parser = argparse.ArgumentParser(description="Plan a landmarks Play (read-only)")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    data = timeline.timeline_data()
    rows = timeline.landmark_rows_for(data)
    starred = {row["domain"] for row in rows if row.get("keystone")}
    plan = build_landmarks_plan(
        timeline.load_landmarks(),
        keystone_domains=starred,
        limit=args.limit if args.limit is not None else DEFAULT_LANDMARK_PLAN_SIZE,
    )
    if args.json:
        print(json.dumps(json.loads(json.dumps(plan, default=str)),
                         indent=2, sort_keys=True))
    else:
        print("\n".join(describe_landmarks_plan(plan)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
