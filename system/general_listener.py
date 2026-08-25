#!/usr/bin/env python3
"""The GENERAL LISTENER — one recorder, a second trigger (v218, ADR 0029).

ADR 0028 gave the landmark lane a recorder: recording is its own pass, with
its own prompt, its own model call and its own blocking backstop. That
recorder is FOCUSED. It is handed a domain, it is shown that domain's ladder
and that domain's filed entries, and it records the answer to the question
that was asked. Its restriction to the asked domain is deliberate and the
adversarial audit of 2026-08-25 refused to repeal it: *"Something else in the
same breath never excuses the domain's own answer"* is what stopped a mission
abroad being filed as military service, and a focused session that starts
recording off-domain loses that.

But people say datable things everywhere, not only when a landmark question
asked them to. *"We moved to Dayton the summer after Mom died"* is two
anchors and a death year, said in a conversation about a house. Nothing
listened.

**This module is the second trigger, not a second recorder.** It runs the
same attempt/lint/retry loop in `landmark_recorder.record_answer` — there is
exactly one loop and this module adds no other — with three things swapped:
its own leaf (:func:`build_listener_prompt`), its own parse
(:func:`parse_listener_output`), and its own backstop
(:func:`listener_heard_nothing`). The focused mode is untouched.

**Typed lists, never a heterogeneous bag.** The output is
``{"landmarks": [...], "people": [...]}``:

* ``landmarks`` are ordinary landmark records of ANY domain, each through
  BOTH pinned validators exactly as the focused recorder's are. The
  vocabulary is the same vocabulary; only the restriction to ONE domain was
  ever a property of focused mode.
* ``people`` are person DATES — ``{name, relation, born|died, basis}`` — and
  they file through v217's roster seam (`entity-verdict --born/--died`).
  **Owner ruling: person dates as a user feature are FAMILY ONLY.** A record
  whose relation is absent or is not a family relation is DROPPED at
  validation with a named finding (:data:`DROPPED_NON_FAMILY`), never filed.
  The leaf is taught the rule; this is the guard that does not depend on the
  leaf being obeyed, which is ADR 0028's whole lesson.

There is no ``placements`` list. Moment identity for prose — deciding WHICH
sentence a date belongs to — is phase 2 and is stated as not-done in ADR
0029 rather than half-built here.

Pure except for the injected ``call`` in `landmark_recorder`: the prescreen,
the prompt build, the parse, the validation and the lint are all
deterministic and separately testable.
"""

from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path

SYSTEM_DIR = Path(__file__).resolve().parent
if str(SYSTEM_DIR) not in sys.path:
    sys.path.insert(0, str(SYSTEM_DIR))

import chronology as chrono  # noqa: E402
import conversation_delivery  # noqa: E402
import cross_dating  # noqa: E402
import landmarks_interaction as li  # noqa: E402
from lifehug_core import INTERACTIONS_DIR  # noqa: E402
from recommend_focuses import TIME_PERIOD_PATTERNS  # noqa: E402

LISTENER_PROMPT = "listener.md"

#: The listener's own role — the same haiku-class extraction the focused
#: recorder runs on, for the same reason (`landmark_recorder`'s cost note).
#: `interaction.yaml`'s `role.listener` carries the same value and
#: `test_the_listener_role_matches_the_manifest` pins them equal.
DEFAULT_LISTENER_ROLE = "haiku-class"

#: The LLM purpose the FOCUSED recorder's completion is spent on. Named here
#: because until v218 nothing package-side named it at all, and the listener
#: needs a name to be a SECOND of.
LANDMARK_RECORD_PURPOSE = "landmark_record"

#: The listener's own purpose — a SECOND name, never a rename of the one
#: above. The two passes have different prompts, different outputs and
#: different backstops, and a host budgets, routes and audits them
#: separately; collapsing them into one purpose would make the listener's
#: cost invisible inside the recorder's. Platform registers its own rows.
DATE_RECORD_PURPOSE = "date_record"

#: The blocking lint of the no-focus mode, and the ONLY thing that makes this
#: mode shippable. ADR 0028's finding was that prompt prose alone cannot be
#: certified: the instruction was present and the model ignored it. So the
#: listener does not ship on "the leaf says to listen". It ships on: the
#: PRESCREEN says there is something datable in here, the listener came back
#: with nothing, and that is a LINT with one bounded retry and then
#: `landmark_recorder.STATUS_WITHHELD` — a state a host sweep can run again,
#: never a silent drop. Exactly the shape of `answer_must_record`.
LISTENER_HEARD_NOTHING_LINT = "landmark_gates.listener_heard_nothing"

#: The named finding a dropped person record carries. A non-family person's
#: date is not an error and not a landmark — it is simply not a person record
#: (owner ruling), and the drop says so by name rather than vanishing.
DROPPED_NON_FAMILY = "person_relation_not_family"

#: The named finding for a person record with a name and no date at all. The
#: listener's people list is about DATES; a roster fact with no date belongs
#: to the identity conversation, not here.
DROPPED_NO_DATE = "person_record_has_no_date"

#: How much of the store the no-focus prompt may show. The focused leaf shows
#: ONE domain's entries under `KNOWN_ENTRIES_LIMIT = 12`; this mode has nine
#: domains and would carry 108 lines at that rate. The cap is TWO numbers and
#: the block says what it hid: at most :data:`KNOWN_PER_DOMAIN` lines from any
#: one domain, and at most :data:`KNOWN_TOTAL` lines in all. Domains are
#: walked in `questions.yaml` order, so what survives the cap is the same set
#: every time rather than whichever domain happened to be biggest.
KNOWN_PER_DOMAIN = 3
KNOWN_TOTAL = 21

#: What the block says when the whole store is empty.
NO_KNOWN_ENTRIES = "(nothing filed in any domain yet)"

#: Free-text caps on a person record, matching the landmark record's own
#: (`landmarks_interaction._TEXT_CAPS`): a name is a name, not a story.
PERSON_NAME_LIMIT = 120


class GeneralListenerError(Exception):
    """The listener could not be composed (never raised into capture)."""


# --------------------------------------------------------------------------
# 1. The prescreen — deterministic, table-driven, DERIVED
# --------------------------------------------------------------------------
#
# The prescreen answers ONE question about a raw message: *could there be a
# datable fact in here?* It is not an extractor and it never decides what the
# date IS. It exists so the backstop has something to compare against: a
# listener that returns nothing is only a failure where something was there
# to hear.
#
# EVERY table below is either an existing table of this repo read by name, or
# a pattern nothing in the repo had. That split is the whole design. Before
# v218 the package held FIVE overlapping ways of noticing time — the year
# regex existed three times over — and a sixth parallel list is exactly the
# recurring defect (docs/BUILDING.md §7). So:
#
#   * years            `chronology.YEAR_RE` (v218 promoted it; the three
#                       private copies now read the same object)
#   * month names      `chronology.MONTH_NAMES`
#   * ages             `cross_dating.AGE_STATEMENT_RES` (v218 promoted it) —
#                       including its own exclusions: `at 19%`, `at 19:30`,
#                       `at 19 Elm Street` and `at 19th` are NOT ages, and
#                       that judgment is not re-typed here
#   * number words     `chronology.NUMBER_WORDS`
#   * life stages      `recommend_focuses.TIME_PERIOD_PATTERNS` and
#                       `cross_dating.AGE_BAND_AGES`
#
# and the four tables this module ADDS are the four shapes the measurement
# found and nothing in the repo could see: relative counts ("three years
# back"), becoming-an-age ("turning forty"), a THIRD PERSON's age ("until she
# was nine" — every existing age table is first-person, because every
# existing caller was reading the subject's own moment), and anchor-relative
# phrases ("the summer after we moved", "when Ivo was born"), which the
# owner's relative-dates ruling makes evidence in their own right.

#: The verdict vocabulary — the table that fired, by name. A reason is data:
#: the lint quotes it back and the goldens pin it.
PRESCREEN_REASONS = ("year", "month", "age", "duration", "becoming",
                     "third_person_age", "life_stage", "anchor_relative")

#: Always used through one of the three GROUPED forms below. A bare
#: alternation spliced into a longer pattern binds at the top level and
#: silently matches the bare word ("five" on its own), which is exactly the
#: over-fire this prescreen is otherwise careful not to make.
_NUMBER_WORD = "|".join(sorted(chrono.NUMBER_WORDS, key=len, reverse=True))
_WORD_COUNT = rf"(?:{_NUMBER_WORD})"
_COUNT = rf"(?:\d{{1,3}}|{_NUMBER_WORD})"
_SMALL_AGE = rf"(?:\d{{1,2}}|{_NUMBER_WORD})"

#: Months, word-bounded. TWO patterns, because `May` is a modal verb and the
#: other eleven are not. The others match case-insensitively on their full
#: name or the standard three-letter abbreviation, and `\b` is what keeps
#: `mar` out of `marry` and `march` out of `marching`.
_MONTH_WORDS = tuple(name for name in chrono.MONTH_NAMES if name != "May")
_MONTH_ABBREVS = tuple(name[:3] for name in _MONTH_WORDS)
_MONTH_RE = re.compile(
    r"\b(?:" + "|".join(
        sorted((*_MONTH_WORDS, *_MONTH_ABBREVS), key=len, reverse=True)
    ) + r")\b\.?", re.IGNORECASE)

#: `May` is a month ONLY when it is capitalized AND sits next to a day number
#: or a year. "We may have moved" never fires; "May 1979", "May of 1979" and
#: "2 May 1979" all do. Case-SENSITIVE on purpose — a lowercase "may" in a
#: life story is a modal verb every time.
_MAY_RES = (
    re.compile(r"\bMay\b[ ,]+(?:of\s+)?(?:1[89]\d{2}|20\d{2})\b"),
    re.compile(r"\bMay\b[ ,]+\d{1,2}(?:st|nd|rd|th)?\b"),
    re.compile(r"\b\d{1,2}(?:st|nd|rd|th)?\s+May\b"),
)

#: "three years ago" / "two decades back". `back` is the half nothing in the
#: repo read, and it is how a lot of people say it.
DURATION_RES = (
    re.compile(rf"\b{_COUNT}\s+(?:and\s+a\s+half\s+)?"
               r"(?:year|month|decade|week|day|summer|winter)s?\s+"
               r"(?:ago|back|later|earlier|before that|after that)\b",
               re.IGNORECASE),
    re.compile(rf"\bfor\s+{_COUNT}\s+(?:and\s+a\s+half\s+)?"
               r"(?:year|month|decade)s?\b", re.IGNORECASE),
    re.compile(rf"\b{_WORD_COUNT}\s+(?:and\s+a\s+half\s+)?"
               r"(?:year|month|decade)s?\b", re.IGNORECASE),
)

#: "turning forty", "becoming a teenager", "when I turned 18". An age
#: statement in the future or the moment of crossing, which every table in
#: `cross_dating.AGE_STATEMENT_RES` reads as the past.
BECOMING_RES = (
    re.compile(rf"\b(?:turn(?:ed|ing|s)?|becom(?:e|es|ing)|became)\s+"
               rf"(?:the\s+age\s+of\s+)?{_SMALL_AGE}\b", re.IGNORECASE),
    re.compile(r"\b(?:turn(?:ed|ing|s)?|becom(?:e|es|ing)|became)\s+"
               r"(?:a\s+)?(?:teenager|adult|grown[- ]up)\b", re.IGNORECASE),
)

#: "until she was nine", "when he was 12", "before Ivo was three". Every
#: existing age table is FIRST person, because every existing caller was
#: dating the subject's own moment; a listener hears about other people all
#: day. A capitalized name counts as the subject, which is what makes
#: "when Ivo was three" evidence.
THIRD_PERSON_AGE_RES = (
    re.compile(rf"\b(?:when|until|till|after|before|by\s+the\s+time)\s+"
               r"(?:he|she|they|we|I|[A-Z][a-z]+)\s+(?:was|were|turned)\s+"
               rf"{_SMALL_AGE}\b"),
    re.compile(rf"\b(?:he|she|they)\s+(?:was|were)\s+{_SMALL_AGE}\s+"
               r"years?\s+old\b", re.IGNORECASE),
)

#: "as a kid", "growing up", "back in those days". Life STAGES with no number
#: in them, which `TIME_PERIOD_PATTERNS` covers for the named periods
#: (childhood, high school, my twenties) and does not cover for these.
LIFE_STAGE_RES = (
    re.compile(r"\bas\s+a\s+(?:kid|child|boy|girl|teenager|young\s+"
               r"(?:man|woman))\b", re.IGNORECASE),
    re.compile(r"\bgrowing\s+up\b", re.IGNORECASE),
    re.compile(r"\bback\s+(?:then|in\s+(?:those|the)\s+days)\b", re.IGNORECASE),
    re.compile(r"\bwhen\s+I\s+was\s+(?:little|young|small|a\s+kid|a\s+child)\b",
               re.IGNORECASE),
)

#: The owner's relative-dates ruling, as a table: a phrase that fixes a
#: moment AGAINST ANOTHER MOMENT is dating evidence even though it carries no
#: number. "The summer after we moved" is a date the arithmetic can reach the
#: moment the move is dated, and `cross_dating` is the pass that will reach
#: it; the listener's job is only to notice that it was said.
ANCHOR_RELATIVE_RES = (
    re.compile(r"\bwhen\s+(?:[A-Z][a-z]+|he|she|they|we|I|my\s+\w+)\s+"
               r"(?:was|were)\s+born\b"),
    re.compile(r"\b(?:the\s+)?(?:spring|summer|fall|autumn|winter|year|"
               r"month|week|day|night|morning)\s+"
               r"(?:after|before|(?:that|when)\s+we|(?:that|when)\s+I)\b",
               re.IGNORECASE),
    re.compile(r"\b(?:right\s+|just\s+)?(?:after|before)\s+"
               r"(?:we|I|he|she|they|my\s+\w+)\s+"
               r"(?:moved|married|got\s+married|left|graduated|enlisted|"
               r"retired|died|passed|had\s+\w+|was\s+born|were\s+born)\b",
               re.IGNORECASE),
    re.compile(r"\bthe\s+(?:year|summer|winter|spring|fall|autumn)\s+"
               r"(?:[A-Z][a-z]+|he|she|they|we|I)\s+"
               r"(?:died|passed|was\s+born|were\s+born|married|moved)\b"),
)

#: The decade form. `chronology`'s own `_HUMAN_DECADE_RE` is ANCHORED (it
#: parses a whole value, not prose), so it cannot be spliced into a message
#: scan; this is the same sentence with the anchors off, and "the 1970s" is
#: as datable as any year.
DECADE_RE = re.compile(r"\b(?:1[89]\d{2}|20\d{2})s\b", re.IGNORECASE)

#: reason -> the patterns that raise it. `TIME_PERIOD_PATTERNS` and the age
#: tables are read by name from their own modules; nothing here is a copy.
PRESCREEN_TABLES: dict[str, tuple] = {
    "year": (chrono.YEAR_RE, DECADE_RE),
    "month": (_MONTH_RE, *_MAY_RES),
    "age": tuple(cross_dating.AGE_STATEMENT_RES),
    "duration": DURATION_RES,
    "becoming": BECOMING_RES,
    "third_person_age": THIRD_PERSON_AGE_RES,
    "life_stage": (TIME_PERIOD_PATTERNS, *LIFE_STAGE_RES),
    "anchor_relative": ANCHOR_RELATIVE_RES,
}


#: The reasons whose tables are CASE-SENSITIVE by design and must therefore
#: read the message exactly as written: `May` is a month only capitalized, and
#: the other eleven are matched case-insensitively anyway.
_VERBATIM_REASONS = frozenset({"month"})

_SENTENCE_OPENER_RE = re.compile(r"(^|[.!?]\s+|\n\s*)([A-Z])")


def _sentence_normalized(text: str) -> str:
    """The message with each sentence's OPENING capital folded down.

    Every table this prescreen borrows was written for prose read MID
    sentence: `cross_dating.AGE_STATEMENT_RES`' "at 19" rung is deliberately
    case-sensitive (it is guarding against "at 19 Elm Street", and its
    exclusions depend on real capitals), and a moment fragment never began a
    sentence. A message does — "At 19 I shipped out", "When Ivo was born" —
    and re-typing those patterns with a capital in them is the duplicate this
    module exists not to make. So the TEXT is normalized instead, and every
    exclusion those tables carry survives untouched: "At 19 Elm Street"
    becomes "at 19 Elm Street" and is still correctly refused.

    This is `_echo_terms`' own doctrine read the other way round — a capital
    at the start of a sentence proves nothing about the word.
    """
    return _SENTENCE_OPENER_RE.sub(
        lambda match: match.group(1) + match.group(2).lower(), text)


@dataclass(frozen=True)
class Verdict:
    """What the prescreen found. ``fired`` is the only decision it makes."""

    fired: bool
    reasons: tuple[str, ...] = ()
    terms: tuple[str, ...] = ()

    def __bool__(self) -> bool:
        return self.fired


#: How many distinct matched fragments a verdict carries. Every match of
#: every table is collected, not just the first per pattern: the terms are
#: what `listener_heard_nothing` tests against the store to recognise a
#: RESTATEMENT, and a sample of one fragment per pattern would call
#: "Corinne, 1979 — and Wren, 1990" fully consumed by a store holding only
#: Corinne. The cap is a bound on the work, not on the evidence; the reminder
#: and the finding quote four of them, because a reminder is not a
#: transcript.
MAX_TERMS = 24


def may_contain_datable(text: object) -> Verdict:
    """*Could* there be a datable fact in this message? Deterministic.

    Over-firing is CHEAP by construction and under-firing is not, so the
    tables are liberal (the owner's budget ruling) and every ambiguity is
    resolved toward firing. A false positive costs at most one extra
    haiku-class regeneration on a message the listener honestly found nothing
    in; a false negative is a date nobody ever hears. See
    :func:`listener_heard_nothing` for the asymmetry stated as a rule.
    """
    body = text if isinstance(text, str) else ""
    if not body.strip():
        return Verdict(False)
    reasons: list[str] = []
    terms: list[str] = []
    folded = _sentence_normalized(body)
    for reason in PRESCREEN_REASONS:
        hit = False
        subject = body if reason in _VERBATIM_REASONS else folded
        for pattern in PRESCREEN_TABLES[reason]:
            for match in pattern.finditer(subject):
                hit = True
                fragment = " ".join(match.group(0).split())
                if fragment and fragment not in terms:
                    terms.append(fragment)
                if len(terms) >= MAX_TERMS:
                    break
        if hit:
            reasons.append(reason)
    return Verdict(bool(reasons), tuple(reasons), tuple(terms[:MAX_TERMS]))


# --------------------------------------------------------------------------
# 2. The backstop — a blocking lint and exactly one retry
# --------------------------------------------------------------------------

#: What a host appends to the ONE regeneration when
#: :data:`LISTENER_HEARD_NOTHING_LINT` fires. It names what the prescreen saw
#: and, in the same breath, forbids inventing anything to satisfy it — the
#: same double sentence `MANY_RECORDS_REMINDER` carries, for the same reason.
LISTENING_REMINDER = (
    "You recorded nothing, and there is time in what they said{term_clause}. "
    "Read it again and emit every datable fact in it: a landmark record for "
    "each one that belongs to a domain above, and a `people` record for a "
    "FAMILY member whose birth or death they dated. Record only what they "
    "actually said — never invent a date, a name or a domain to fill the "
    "lists out — and if, reading it again, there genuinely is no fact here, "
    "emit the empty lists and say nothing else."
)


def listening_reminder(verdict: object = None) -> str:
    """:data:`LISTENING_REMINDER`, naming what the prescreen actually saw."""
    terms = tuple(getattr(verdict, "terms", ()) or ())
    clause = ""
    if terms:
        quoted = ", ".join(f'"{term}"' for term in terms[:4])
        clause = f" — {quoted}"
    return LISTENING_REMINDER.format(term_clause=clause)


#: One word of a fragment or of a filed entry. Single characters count: a
#: day number ("2 April 1979") is one, and the coverage test must not call a
#: fragment consumed on the strength of the words it happened to skip.
_TERM_TOKEN_RE = re.compile(r"[A-Za-z0-9'\u2019\-]+")


def store_terms(landmarks: object,
                framework_root: str | Path | None = None) -> frozenset[str]:
    """Every word the store ALREADY holds — filed names and filed dates.

    v216's dedupe, carried into the no-focus mode. The focused recorder keeps
    a restatement from costing a regeneration by deriving `known_labels` for
    ONE domain; a listener has no domain, so the same derivation runs over
    all nine — the entry's own name through
    `landmarks_interaction.entry_name` and its date through
    `chronology.display_date`, which are the SAME two readers v216's
    ``{known_entries}`` block renders with. Never a second reader, and never
    a stored index: it is recomputed from the store it was handed.
    """
    terms: set[str] = set()
    for row in li.load_questions(framework_root=framework_root):
        for entry in li.landmark_entries(landmarks, row["domain"]):
            name = li.entry_name(entry, row) or ""
            record = li._entry_date(entry)  # noqa: SLF001
            shown = (chrono.display_date(record, with_basis=False)
                     if record else "")
            for token in _TERM_TOKEN_RE.findall(f"{name} {shown}"):
                terms.add(token.casefold())
    return frozenset(terms)


def _consumed(term: str, covered: frozenset[str]) -> bool:
    """Whether every word of a prescreen fragment is already in the store."""
    tokens = [token.casefold() for token in _TERM_TOKEN_RE.findall(term)]
    return bool(tokens) and all(token in covered for token in tokens)


def listener_heard_nothing(user_message: object, records: object,
                           people: object = (), *,
                           findings: object = (),
                           landmarks: object = (),
                           verdict: object = None,
                           framework_root: str | Path | None = None
                           ) -> dict | None:
    """The one definition of "there was time in it and nothing came back".

    The no-focus twin of `landmarks_interaction.answer_must_record`, and
    deliberately the same shape: a finding (``lint`` / ``detail`` /
    ``reasons``) or ``None``, one bounded retry on a finding, then
    ``STATUS_WITHHELD``. Never silence.

    **The asymmetry, stated rather than hidden.** A prescreen FALSE POSITIVE
    is not a listener failure: a message can carry a month name and no fact.
    Ideally the lint would fire only where the prescreen's own reason tokens
    come back UNCONSUMED — but "was this fragment consumed by that record?"
    is not decidable from a string any more than "how many entries is this
    answer?" was (ADR 0028 amendment's boundary note). So the rule is the
    decidable one: **the prescreen fired, both lists are empty, and the
    person did not decline.** The noise is accepted, it costs exactly one
    haiku-class regeneration, and it can never drop, alter or withhold a
    record that was made.

    A DECLINE clears the check outright, through `answer_shape`'s own skip
    rules — one definition of "not now", never a second list of hedges.

    So does a :data:`DROPPED_NON_FAMILY` finding, and ONLY that one. The
    listener heard a dated person and the owner's family-only rule refused
    the record: that is a DECISION, not a miss, and regenerating would ask
    the model to break the rule it just obeyed. :data:`DROPPED_NO_DATE` is
    the opposite — a malformed object is not a thing heard — so it clears
    nothing.
    """
    heard = [item for item in
             (list(records or ()) + list(people or ()))
             if isinstance(item, dict) and item]
    if heard:
        return None
    if DROPPED_NON_FAMILY in tuple(findings or ()):
        return None
    if verdict is None:
        verdict = may_contain_datable(user_message)
    if not getattr(verdict, "fired", False):
        return None
    if li.answer_shape(user_message, "") == "skip":
        return None
    terms_seen = tuple(getattr(verdict, "terms", ()) or ())
    if terms_seen:
        covered = store_terms(landmarks, framework_root)
        if covered and all(_consumed(term, covered) for term in terms_seen):
            # A RESTATEMENT. Every fragment the prescreen saw is already in
            # the store, word for word, so "nothing came back" is the right
            # answer and not a miss — v216's dedupe, read in the no-focus
            # mode. This is the one place where "was the fragment consumed?"
            # IS decidable, and it is decidable because the store answers it.
            return None
    reasons = tuple(getattr(verdict, "reasons", ()) or ())
    terms = tuple(getattr(verdict, "terms", ()) or ())
    quoted = ", ".join(f'"{term}"' for term in terms[:4]) or ", ".join(reasons)
    return {
        "lint": LISTENER_HEARD_NOTHING_LINT,
        "detail": ("there is time in what they said and nothing was "
                   f"recorded — {quoted}: listening is not recording, emit "
                   "the record"),
        "reasons": reasons,
    }


# --------------------------------------------------------------------------
# 3. Person records — FAMILY ONLY (owner ruling)
# --------------------------------------------------------------------------

PERSON_DATE_FIELDS = ("born", "died")


def validate_person_record(value: object) -> tuple[dict | None, str]:
    """One ``people`` record, validated. Returns ``(record, finding)``.

    ``finding`` is ``""`` when the record is kept and one of
    :data:`DROPPED_NON_FAMILY` / :data:`DROPPED_NO_DATE` when it is not — a
    NAMED drop, because a person's date going missing must be legible, and
    because the owner's family-only ruling is the kind of rule a prompt is
    certain to be talked out of eventually. This is the guard that does not
    depend on the leaf.

    The date itself is not re-read here: `entity_verdict.parse_person_date`
    is the one door a `--born`/`--died` value goes through, and it is exactly
    the `chronology.parse_edtf` + `chronology.normalized_date` pair every
    landmark date already uses. An unreadable date drops that FIELD, and a
    record left with no date at all drops as :data:`DROPPED_NO_DATE`.
    """
    from entity_verdict import EntityVerdictError, parse_person_date  # noqa: PLC0415

    if not isinstance(value, dict) or not value:
        return None, DROPPED_NO_DATE
    name = str(value.get("name") or "").strip()[:PERSON_NAME_LIMIT]
    if not name or not li.person_slug(name):
        return None, DROPPED_NO_DATE
    relation = str(value.get("relation") or "").strip().lower()
    if relation not in li.person_date_relations():
        # The owner's ruling, enforced deterministically: a stranger's
        # birthday is anchor evidence for the timeline, never a roster row.
        return None, DROPPED_NON_FAMILY
    basis = str(value.get("basis") or "stated").strip() or "stated"
    if basis not in chrono.BASES:
        basis = "stated"
    record: dict = {"name": name, "relation": relation, "basis": basis}
    for field in PERSON_DATE_FIELDS:
        raw = value.get(field)
        if raw in (None, ""):
            continue
        try:
            parsed = parse_person_date(field, raw, basis)
        except EntityVerdictError:
            continue
        if parsed:
            record[field] = parsed
    if not any(field in record for field in PERSON_DATE_FIELDS):
        return None, DROPPED_NO_DATE
    return record, ""


def person_invocations(people: object) -> list[list[str]]:
    """The ``entity-verdict`` argv that files each heard person date.

    The SAME seam v217 built for the landmark set
    (`landmarks_interaction.person_roster_invocations`): verdict ``clear``,
    because this asserts an IDENTITY and not a page verdict; ``--ensure``,
    because the roster may never have heard the name; and
    `landmarks_interaction.date_flags`, so the basis travels with the date
    and `entity_verdict._preferred_date` can honour *derived never overwrites
    stated*. A person with a ``died`` date is stamped ``--not-living``, the
    one inference this makes, because it is an identity and not a date.
    """
    argvs: list[list[str]] = []
    for record in (people or ()):
        if not isinstance(record, dict) or not record:
            continue
        slug = li.person_slug(record.get("name"))
        if not slug:
            continue
        argv = ["entity-verdict", "person", slug, "clear",
                "--name", str(record["name"]),
                "--relationship", str(record["relation"])]
        if record.get("died"):
            argv.append("--not-living")
        for field in PERSON_DATE_FIELDS:
            argv.extend(li.date_flags(field, chrono.from_dict(record.get(field))))
        argv.append("--ensure")
        argvs.append(argv)
    return argvs


# --------------------------------------------------------------------------
# 4. The prompt
# --------------------------------------------------------------------------

def _prompt_path(framework_root: str | Path | None = None) -> Path:
    base = (Path(framework_root) / "interactions" / "landmarks"
            if framework_root else INTERACTIONS_DIR / "landmarks")
    return base / "prompt" / LISTENER_PROMPT


def load_listener_leaf(framework_root: str | Path | None = None) -> str:
    """The listener leaf, verbatim. A host REPLAYs exactly this text."""
    try:
        return _prompt_path(framework_root).read_text(encoding="utf-8")
    except OSError as exc:
        raise GeneralListenerError(f"no listener leaf: {exc}") from exc


def render_domain_digest(framework_root: str | Path | None = None) -> str:
    """The nine domains as nine lines: ``- domain: key | key | key``.

    Deliberately NOT nine full ladders with nine rung texts. The focused leaf
    can afford one domain's whole shape; a no-focus prompt that pasted all
    nine would be an order of magnitude bigger than the pass it belongs to,
    and the thing a recorder actually needs is the closed KEY SET per domain
    — the same `landmark_recorder.recordable_keys` derivation the focused
    leaf renders as *THE ONLY KEYS THIS DOMAIN CAN READ*, which is already
    the ladder walked through both validators. Nine of those lines is ~780
    characters, and the ``none`` key appearing on a line is how that line
    says the domain can be answered *never happened*.
    """
    from landmark_recorder import recordable_keys  # noqa: PLC0415

    lines = []
    for row in li.load_questions(framework_root=framework_root):
        keys = " | ".join(recordable_keys(row))
        lines.append(f"- {row['domain']}: {keys}")
    return "\n".join(lines)


def render_all_known_entries(landmarks: object, *,
                             per_domain: int = KNOWN_PER_DOMAIN,
                             total: int = KNOWN_TOTAL,
                             framework_root: str | Path | None = None) -> str:
    """v216's known-entries block, for EVERY domain, bounded twice.

    The focused recorder shows one domain and caps at
    `landmarks_interaction.KNOWN_ENTRIES_LIMIT`; a no-focus pass has nine
    domains and the same cap would put 108 lines in a prompt whose whole
    virtue is being small. So the block is capped BOTH ways and says what it
    hid: at most ``per_domain`` lines from any one domain, at most ``total``
    lines in all, domains walked in `questions.yaml` order so the surviving
    set is stable rather than whichever domain grew fastest.

    Each line is `landmarks_interaction.render_entry` — the same renderer the
    focused block uses, never a second formatter.
    """
    rows = li.load_questions(framework_root=framework_root)
    lines: list[str] = []
    hidden = 0
    ceiling = max(int(total), 0)
    per = max(int(per_domain), 0)
    for row in rows:
        entries = li.landmark_entries(landmarks, row["domain"])
        if not entries:
            continue
        room = min(per, max(ceiling - len(lines), 0))
        shown = [line for line in (li.render_entry(entry, row)
                                   for entry in entries[:room]) if line]
        hidden += len(entries) - len(shown)
        # `render_entry` yields "- Name — date"; the domain is what a
        # no-focus reader needs that a focused one already knew.
        lines.extend(f"- {row['domain']} · {line[2:]}" for line in shown)
    if not lines:
        return NO_KNOWN_ENTRIES
    if hidden > 0:
        lines.append(f"- …and {hidden} more already filed across the domains")
    return "\n".join(lines)


def build_listener_prompt(*, answer: str, reply: str = "",
                          landmarks: object = (),
                          reminder: str = "",
                          framework_root: str | Path | None = None) -> str:
    """The listener's whole prompt, from the leaf plus five substitutions.

    The same discipline as `landmark_recorder.build_recorder_prompt`: no
    identity, no behavior, no examples, no transcript. What it carries that
    the focused prompt does not is the nine-line domain digest and the
    family-relation vocabulary; what it drops is the one domain's ask, ladder
    and none-rule, which are in the digest instead.
    """
    filled = load_listener_leaf(framework_root)
    known = render_all_known_entries(landmarks, framework_root=framework_root)
    relations = " | ".join(sorted(li.person_date_relations()))
    # `.replace`, never `.format` — the leaf carries literal JSON braces.
    for token, value in (
        ("{domains}", render_domain_digest(framework_root)),
        ("{known_entries}", known),
        ("{family_relations}", relations),
        ("{answer}", (answer or "").strip()),
        ("{reply}", (reply or "(no reply was generated)").strip()),
        ("{reminder}", f"\n\n{reminder.strip()}" if reminder else ""),
    ):
        filled = filled.replace(token, value)
    return filled


# --------------------------------------------------------------------------
# 5. The parse — typed lists, each item validated ALONE
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class Heard:
    """One listener completion, parsed. Typed lists, never a mixed bag."""

    landmarks: tuple[dict, ...] = ()
    people: tuple[dict, ...] = ()
    findings: tuple[str, ...] = ()

    def __len__(self) -> int:
        return len(self.landmarks) + len(self.people)


def parse_listener_output(raw: object, *,
                          framework_root: str | Path | None = None) -> Heard:
    """One listener completion through the pinned validators, per record.

    ``landmarks`` run `conversation_delivery._parse_landmark` then
    `landmarks_interaction.validate_landmark` — BOTH pinned layers, exactly
    as `landmark_recorder.parse_recorder_output` runs them, and each record
    ALONE so an invalid one never takes a sibling with it. The only thing the
    no-focus mode changes is that the domain is not fixed in advance; the
    vocabulary of what a landmark IS is not touched.

    ``people`` run :func:`validate_person_record`, whose drops are NAMED in
    :attr:`Heard.findings`.

    A malformed envelope degrades to an EMPTY :class:`Heard`, never an error.
    """
    if not isinstance(raw, str):
        return Heard()
    text = raw.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[-1].rsplit("```", 1)[0]
    try:
        data = json.loads(text)
    except (ValueError, TypeError):
        return Heard()
    if not isinstance(data, dict):
        return Heard()
    records: list[dict] = []
    payload = data.get("landmarks")
    if isinstance(payload, dict):
        payload = [payload]
    if not isinstance(payload, (list, tuple)):
        payload = [data.get("landmark")] if data.get("landmark") else []
    for candidate in payload:
        structural = conversation_delivery._parse_landmark(candidate)  # noqa: SLF001
        validated = li.validate_landmark(structural,
                                         framework_root=framework_root)
        if isinstance(validated, dict) and validated not in records:
            records.append(validated)
    people: list[dict] = []
    findings: list[str] = []
    crowd = data.get("people")
    if isinstance(crowd, dict):
        crowd = [crowd]
    if not isinstance(crowd, (list, tuple)):
        crowd = []
    for candidate in crowd:
        record, finding = validate_person_record(candidate)
        if record is not None and record not in people:
            people.append(record)
        elif finding:
            findings.append(finding)
    return Heard(tuple(records), tuple(people), tuple(findings))


# --------------------------------------------------------------------------
# CLI — the stdin-JSON path every prompt builder in this package carries
# --------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    """`general_listener.py [--dry-run] < payload.json`.

    Payload: ``{"answer", "reply"?, "landmarks"?}``. ``--dry-run`` prints the
    composed prompt and the prescreen verdict and calls nothing, which is how
    a host verifies its own REPLAY against this leaf without spending a
    completion.
    """
    import argparse  # noqa: PLC0415

    parser = argparse.ArgumentParser(description="Run the general listener")
    parser.add_argument("--model", default=DEFAULT_LISTENER_ROLE)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except ValueError as exc:
        print(json.dumps({"error": f"unreadable payload: {exc}"}))
        return 1
    answer = payload.get("answer", "")
    try:
        if args.dry_run:
            verdict = may_contain_datable(answer)
            print(json.dumps({"prescreen": {"fired": verdict.fired,
                                            "reasons": list(verdict.reasons),
                                            "terms": list(verdict.terms)}},
                             indent=2, sort_keys=True))
            print(build_listener_prompt(
                answer=answer, reply=payload.get("reply", ""),
                landmarks=payload.get("landmarks") or {}))
            return 0
        from ai_provider import call_ai  # noqa: PLC0415
        from landmark_recorder import (  # noqa: PLC0415
            STATUS_NOTHING,
            STATUS_RECORDED,
            listen_to_answer,
        )

        outcome = listen_to_answer(
            answer=answer, reply=payload.get("reply", ""),
            landmarks=payload.get("landmarks") or {},
            call=call_ai, model=args.model,
        )
    except (li.LandmarkInteractionError, GeneralListenerError) as exc:
        print(json.dumps({"error": str(exc)}))
        return 1
    print(json.dumps({
        "status": outcome.status,
        "records": list(outcome.records),
        "people": list(outcome.people),
        "invocations": li.landmark_invocations(outcome.records)
        + person_invocations(outcome.people),
        "attempts": outcome.attempts,
        "lint_ids": list(outcome.lint_ids),
        "findings": list(outcome.findings),
        "reason": outcome.reason,
    }, indent=2, sort_keys=True))
    return 0 if outcome.status in (STATUS_RECORDED, STATUS_NOTHING) else 1


if __name__ == "__main__":
    raise SystemExit(main())
