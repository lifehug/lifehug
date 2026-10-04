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
``{"landmarks": [...], "people": [...], "claims": [...]}``:

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

* ``claims`` (v229, Wave C item C3) are TEMPORAL CLAIMS in the substrate's
  own vocabulary (`temporal_claims`), and they are the reason this module
  changed at all. A landmark record is a ladder row: it belongs to a domain,
  carries at most one date, and can express neither *"we moved when James was
  two"* (no date) nor *"my neighbour's boy was born in 2019"* (no domain), so
  both were dropped by design. The audited plan calls both usable information
  (§2.1, §6.4). Claims are emitted BESIDE the records, never instead of them,
  and one message with N facts becomes one promoted vault source, one receipt
  and N claims (owner amendment 2). See section 6 below for the draft/bind
  split and why there is one.

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
import episode_fold_contract as efc  # noqa: E402
import identity_resolution as ir  # noqa: E402
import landmarks_interaction as li  # noqa: E402
import temporal_claims as tc  # noqa: E402
from lifehug_core import INTERACTIONS_DIR, fill_how_words_arrive  # noqa: E402
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
    # v229: the SAME clause in the other order. Every table above — borrowed
    # and local alike — anchors the age on a leading conjunction ("when I was
    # twelve"), because that is the order a moment FRAGMENT is written in. A
    # message is written in either order, and *"I was about twelve when we
    # left the farm"* fired nothing at all: measured on this branch, filed as
    # a finding, fixed here rather than left. The `when` is what keeps it from
    # being a count — "she was nine when it happened" is an age and "there
    # were three of us" is not — and `i` is lower case because
    # `_sentence_normalized` folds the opening capital of the very sentence
    # this shape usually opens.
    re.compile(rf"\b(?:[Ii]|we|he|she|they|[A-Z][a-z]+)\s+(?:was|were)\s+"
               r"(?:about\s+|around\s+|almost\s+|nearly\s+|just\s+|"
               rf"barely\s+)?{_SMALL_AGE}\s+when\b"),
    # ...and the same subject with an approximator and no `when` at all
    # ("I was about twelve"). An APPROXIMATOR is doing the work the `when`
    # does above: nobody hedges a count of their own children with "about"
    # and then says it was them.
    re.compile(rf"\b(?:[Ii]|we|he|she|they|[A-Z][a-z]+)\s+(?:was|were)\s+"
               rf"(?:about|around|almost|nearly)\s+{_SMALL_AGE}\b"),
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
    "Read it again and emit every datable fact in it: a `claims` entry for "
    "each fact, a landmark record for each one that also belongs to a domain "
    "above, and a `people` record for a FAMILY member whose birth or death "
    "they dated. Record only what they actually said — never invent a date, a "
    "name or a domain to fill the lists out — and if, reading it again, there "
    "genuinely is no fact here, emit the empty lists and say nothing else."
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
                           claims: object = (),
                           identity_assertions: object = (),
                           findings: object = (),
                           landmarks: object = (),
                           verdict: object = None,
                           framework_root: str | Path | None = None,
                           person_identity: object = (),
                           identity_verdict: object = None,
                           person_roster: object = (),
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

    **v229: a CLAIM is a thing heard.** The backstop reads the claims list
    beside the other two, so a completion that speaks only the substrate's
    vocabulary — the shape this program is walking toward — clears it exactly
    as a landmark record does, and a completion that emits NEITHER shape lints
    exactly as it did before. That is the whole bridge in one line: the
    question this class asks is *did anything come back*, never *did the old
    shape come back*.

    So does a :data:`DROPPED_NON_FAMILY` finding, and ONLY that one. The
    listener heard a dated person and the owner's family-only rule refused
    the record: that is a DECISION, not a miss, and regenerating would ask
    the model to break the rule it just obeyed. :data:`DROPPED_NO_DATE` is
    the opposite — a malformed object is not a thing heard — so it clears
    nothing.

    **Event identity I3: an identity assertion is a thing heard too.** It
    joins the same union as `claims` — an ambiguous-hint REFUSAL is not a
    miss (the candidate context genuinely had zero or two matches; the
    ordinary `same_event` question path is what resolves it, not a retry of
    the same prompt), so a refusal finding clears the check exactly as
    :data:`DROPPED_NON_FAMILY` does, and is not itself added to ``heard``.

    **v387: a person-identity record is a thing heard, and a message that
    only TEACHES A NAME lints too.** When the datable half finds nothing to
    complain about, :func:`identity_heard_nothing` is asked the same question
    of the identity prescreen — so "Mara Ellis Dunn is my wife", with no
    date anywhere, is one retry and then withheld if nothing came back, never
    silence. A family-only identity drop is a decision and clears it.
    """
    heard = [item for item in
             (list(records or ()) + list(people or ()) + list(claims or ())
              + list(identity_assertions or ()) + list(person_identity or ()))
             if isinstance(item, dict) and item]
    if heard:
        return None
    datable = _datable_heard_nothing(
        user_message, findings=findings, landmarks=landmarks,
        verdict=verdict, framework_root=framework_root)
    if datable is not None:
        return datable
    if IDENTITY_DECISION_FINDINGS & set(findings or ()):
        return None
    return identity_heard_nothing(user_message, (), findings=findings,
                                  verdict=identity_verdict,
                                  person_roster=person_roster)


def _datable_heard_nothing(user_message: object, *, findings: object,
                           landmarks: object, verdict: object,
                           framework_root: str | Path | None) -> dict | None:
    """The pre-v387 body of :func:`listener_heard_nothing`, unchanged, for a
    completion that heard nothing at all."""
    if DROPPED_NON_FAMILY in tuple(findings or ()):
        return None
    if any(
        collapsed.startswith(IDENTITY_ASSERTION_REFUSED_PREFIX)
        for collapsed in (tc.collapsed_text(finding) for finding in (findings or ()))
    ):
        # An ambiguous or unresolved hint is structural, not a prompt miss —
        # the candidate context did not disambiguate, and re-asking the same
        # model the same question would not either. The ordinary
        # `same_event` path is what resolves it.
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
    """The listener leaf, verbatim but for the shared ``{how_words_arrive}``
    block (`lifehug_core.fill_how_words_arrive`). A host REPLAYs exactly this
    text, and the extractor version is taken over it."""
    try:
        return fill_how_words_arrive(
            _prompt_path(framework_root).read_text(encoding="utf-8"), framework_root)
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


#: No candidate context supplied — the leaf's honest read of "nothing to
#: resolve an identity hint against", same shape as :data:`NO_KNOWN_ENTRIES`.
NO_IDENTITY_CANDIDATES = "(no episode candidates supplied for this turn)"


def render_identity_candidates(candidates: object) -> str:
    """The candidate-context excerpt, as lines the leaf can read.

    Event identity I3 (design §6.4): the host supplies this — never the
    model's own guess — so a hint the model emits resolves against something
    real or refuses. One line per candidate, its kind and its labels.
    """
    lines: list[str] = []
    for row in candidates or ():
        if not isinstance(row, dict):
            continue
        ref = tc.collapsed_text(row.get("ref"))
        kind = tc.collapsed_text(row.get("kind"))
        labels = [tc.collapsed_text(label) for label in (row.get("labels") or ())]
        labels = [label for label in labels if label]
        if not ref or not labels:
            continue
        lines.append(f"- {kind or 'candidate'}: {', '.join(labels)}")
    return "\n".join(lines) if lines else NO_IDENTITY_CANDIDATES


def build_listener_prompt(*, answer: str, reply: str = "",
                          landmarks: object = (),
                          identity_candidates: object = (),
                          person_roster: object = (),
                          reminder: str = "",
                          framework_root: str | Path | None = None) -> str:
    """The listener's whole prompt, from the leaf plus its substitutions.

    The same discipline as `landmark_recorder.build_recorder_prompt`: no
    identity, no behavior, no examples, no transcript. What it carries that
    the focused prompt does not is the nine-line domain digest and the
    family-relation vocabulary; what it drops is the one domain's ask, ladder
    and none-rule, which are in the digest instead.

    v229 adds two more DERIVED substitutions — `temporal_claims.CLAIM_TYPES`
    and :func:`render_event_kinds` — so the claim vocabulary the leaf offers
    is the contract's own and cannot drift from it by a hand edit. Event
    identity I3 adds `{identity_relations}` (`episode_fold_contract.RELATIONS`,
    the same reason) and `{identity_candidates}` (:func:`render_identity_candidates`)
    — the host's own excerpt, never a model guess. v387 adds `{known_people}`
    (`person_resolution.render_known_people`, the classifier's own renderer at
    the listener's cap) — the roster snapshot the host passes as
    ``person_roster``, the same one the `person_identity` list is resolved
    against.
    """
    import person_resolution as pr  # noqa: PLC0415

    filled = load_listener_leaf(framework_root)
    known = render_all_known_entries(landmarks, framework_root=framework_root)
    known_people = pr.render_known_people(
        person_roster, story_text=answer,
        limit=pr.LISTENER_KNOWN_PEOPLE_LIMIT)
    relations = " | ".join(sorted(li.person_date_relations()))
    # `.replace`, never `.format` — the leaf carries literal JSON braces.
    for token, value in (
        ("{domains}", render_domain_digest(framework_root)),
        ("{known_entries}", known),
        ("{family_relations}", relations),
        # Timeline Fix 05: MODEL_CLAIM_TYPES, not CLAIM_TYPES — the dateless
        # `occurrence` type is the deterministic classifier migration's alone
        # and is never offered to a model whose whole job is hearing time.
        # This keeps the composed prompt byte-identical across that release.
        ("{claim_types}", " | ".join(tc.MODEL_CLAIM_TYPES)),
        ("{event_kinds}", render_event_kinds()),
        ("{identity_relations}", " | ".join(efc.RELATIONS)),
        ("{identity_candidates}", render_identity_candidates(identity_candidates)),
        ("{known_people}", known_people),
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
    """One listener completion, parsed. Typed lists, never a mixed bag.

    v229 (Wave C, item C3) adds a THIRD typed list, :attr:`claims`, and adds
    it at the END so a caller that built a :class:`Heard` positionally keeps
    building the same one. It is the same message read into the temporal-claim
    substrate's own vocabulary (`temporal_claims.TemporalClaim`) rather than
    into the landmark ladder's, and the two lists are emitted TOGETHER during
    the transition: the landmark path keeps working unchanged, and the claims
    are what `landmark_recorder.file_claims` promotes and receipts.
    """

    landmarks: tuple[dict, ...] = ()
    people: tuple[dict, ...] = ()
    findings: tuple[str, ...] = ()
    claims: tuple[dict, ...] = ()
    #: Event identity I3 (design §6.4, ADR 0029 amendment). A FOURTH typed
    #: list, added at the end for the same reason `claims` was: a caller
    #: that built a `Heard` positionally keeps building the same one. Each
    #: draft is ``{telling_ref, episode_id, relation, evidence}`` — MENTIONS
    #: resolved against the caller's own candidate-context excerpt, never
    #: model-minted refs (see :func:`parse_identity_assertions`).
    identity_assertions: tuple[dict, ...] = ()
    #: v387 (identity §4.1.4): what the person TAUGHT about who somebody is —
    #: resolved here against the host's roster snapshot (section 8). Last,
    #: for the same positional-compat reason as the two lists above.
    person_identity: tuple[dict, ...] = ()

    def __len__(self) -> int:
        return (
            len(self.landmarks) + len(self.people) + len(self.claims)
            + len(self.identity_assertions) + len(self.person_identity)
        )


def parse_listener_output(raw: object, *,
                          framework_root: str | Path | None = None,
                          identity_candidates: object = (),
                          person_roster: object = ()) -> Heard:
    """One listener completion through the pinned validators, per record.

    ``landmarks`` run `conversation_delivery._parse_landmark` then
    `landmarks_interaction.validate_landmark` — BOTH pinned layers, exactly
    as `landmark_recorder.parse_recorder_output` runs them, and each record
    ALONE so an invalid one never takes a sibling with it. The only thing the
    no-focus mode changes is that the domain is not fixed in advance; the
    vocabulary of what a landmark IS is not touched.

    ``people`` run :func:`validate_person_record`, whose drops are NAMED in
    :attr:`Heard.findings`.

    ``claims`` (v229) run :func:`validate_claim_draft` — the temporal-claim
    contract's own door — and their drops are named in the same list through
    :func:`claim_refused`. The three lists are independent: a refused claim
    never costs a landmark record and a refused record never costs a claim.

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
    claims, refusals = parse_claims(data.get("claims"))
    findings.extend(refusals)
    identity_assertions, identity_refusals = parse_identity_assertions(
        data.get("identity_assertions"), candidates=identity_candidates,
    )
    findings.extend(identity_refusals)
    person_identity, person_identity_findings = parse_person_identity(
        data.get("person_identity"), person_roster=person_roster,
    )
    findings.extend(person_identity_findings)
    return Heard(tuple(records), tuple(people),
                 tuple(dict.fromkeys(findings)), claims, identity_assertions,
                 person_identity)


# --------------------------------------------------------------------------
# 6. Claims — the ear learns to speak the substrate's language (v229, Wave C)
# --------------------------------------------------------------------------
#
# v220 froze what a temporal interpretation IS (`temporal_claims`) and v221
# put one on disk (`temporal_store`). Nothing yet SAID one. The landmark
# record shape the recorder and the listener emit is a ladder row: it belongs
# to a domain, it carries at most one date, and it cannot express *"we moved
# when James was two"* or *"my neighbour's boy was born in 2019"* at all —
# the first has no date and the second belongs to no domain, so both were
# dropped by design. The audited plan calls both of them usable information
# (§2.1, §6.4), and dropping them is the defect the whole substrate exists to
# end.
#
# So the two leaves gain a SECOND output list, `claims`, in the contract's own
# vocabulary. It is emitted BESIDE the landmark records, never instead of
# them, and the two reach the substrate by different roads: a RECORD still
# files through `timeline.save_landmark`, which since v225 promotes it to
# `sources/landmarks/` and converts it by a deterministic rule, while one
# MESSAGE with N facts becomes one promoted source under
# `sources/conversations/`, one receipt and N claims (Amendment 2). Two
# sources, two extractors, one active index — `landmark_recorder.file_claims`
# states why that is corroboration rather than duplication.
#
# THE DRAFT, and why there is one. `temporal_claims.validate_temporal_claim`
# is the one door a claim goes through, and it requires four fields the EAR
# cannot know: the vault `source_ref` (the message is not a source until
# `temporal_store.promote_conversational_source` files it), the
# `extractor_version` (the host's, not the model's), `created_at`, and the
# derived `claim_id`, which is a function of the first two. A claim is
# therefore parsed as a DRAFT — validated through that same door against a
# NAMED unbound placeholder and then stripped of exactly those four fields —
# and BOUND at filing time, when the source exists. There is no second
# validator and no second vocabulary; `test_a_bound_draft_is_the_drafts_own
# _fields` pins that binding adds the binding and changes nothing else.

#: The keys a leaf may put on ONE claim: the contract's own field names, minus
#: the four the FILER supplies. Deliberately CLOSED, exactly as
#: `conversation_delivery._LANDMARK_KEYS` is closed — a key outside this set
#: is a key nothing reads, and a model told it may write one would be told a
#: falsehood. `subject_ref`/`event_ref` are absent on purpose: resolution
#: happens after the claim exists (plan §6.3) and must never re-mint it.
#:
#: E3 (eras §4.3, an ADR 0029 AMENDMENT) adds exactly one key:
#: ``event_mention``, what the person CALLED the stretch of life the fact
#: belongs to — *"College"*, *"the Mission"*. It is the same kind of thing
#: ``subject_mention`` is and it is added for the same reason: the ear records
#: the words, and a later deterministic pass decides what they point at.
#: `event_ref` stays absent — the model may still never link — and
#: `test_the_leaf_may_not_emit_a_ref` pins that.
CLAIM_PROMPT_KEYS = frozenset({
    "claim_type", "subject_mention", "event_kind", "event_mention",
    "temporal_value", "evidence", "basis", "confidence",
})

#: The draft's own field order — stable, so a draft is comparable and a
#: receipt's bytes do not depend on dict insertion luck.
CLAIM_DRAFT_KEYS = ("claim_type", "subject_mention", "event_kind",
                    "event_mention", "temporal_value", "evidence", "basis",
                    "confidence")

#: The fields BINDING supplies and a draft therefore never carries. Named so
#: the strip is a declaration rather than four literals in a comprehension.
CLAIM_BINDING_KEYS = ("claim_id", "source_ref", "source_kind",
                      "extractor_version", "created_at", "schema_version",
                      "status", "supersedes_claim_ids")

#: The placeholder a draft is validated against. It is a legal `SourceRef` —
#: `validate_source_ref` is not weakened for this — and it is recognisable on
#: sight, so a draft that ever escaped into a receipt would be obvious rather
#: than plausible. `test_no_unbound_placeholder_survives_binding` is the guard.
UNBOUND_SOURCE_ID = "unbound:draft"
UNBOUND_REVISION = "sha256:" + "0" * 64
UNBOUND_EXTRACTOR = "unbound"

#: A claim the ear heard and the contract refused, by name. The person said
#: it; the record must say why it did not survive. The suffix is one of
#: `temporal_claims.ERROR_CODES`.
CLAIM_REFUSED_PREFIX = "claim_refused:"

#: The ONE refusal code this layer raises that the contract does not: the leaf
#: emitted a key outside :data:`CLAIM_PROMPT_KEYS`, which means the leaf and
#: this parser disagree about the vocabulary. Every other code comes from
#: `temporal_claims.ERROR_CODES`.
CLAIM_UNKNOWN_KEY = "claim_unknown_key"

#: The ear records what was SAID. Anything worked out from an anchor, an age
#: or the order of things is a later pass's (`cross_dating`, and the fold),
#: so a claim from this layer whose basis the leaf left unstated is
#: `explicit` — the contract's own default is `inferred`, which would be the
#: understatement, and understating provenance is as dishonest as inflating
#: it. This is a BINDING of `temporal_claims.CLAIM_BASES`, never a second one.
CAPTURE_BASIS = "explicit"


def claim_refused(code: object) -> str:
    """The named finding a refused claim carries."""
    return f"{CLAIM_REFUSED_PREFIX}{tc.collapsed_text(code) or 'unknown'}"


def validate_claim_draft(value: object) -> tuple[dict | None, str]:
    """One emitted claim, through the contract's own door. ``(draft, finding)``.

    The draft is what the ear can honestly assert: what kind of claim it is,
    whose it is in the person's own words, which event, the temporal value in
    its one legal shape, the bounded quotation that proves it, the basis and
    the confidence. Everything else is the filer's.

    ``finding`` is ``""`` when the draft is kept and
    :func:`claim_refused`\\ ``(code)`` when it is not — a NAMED drop, never a
    silent one, and the code is the contract's own
    (`temporal_claims.ERROR_CODES`) or the one this layer adds,
    :data:`CLAIM_UNKNOWN_KEY`. The refusals that matter most are already
    written there and are not re-decided here: an aggregate subject
    (*"Ada, Bo, Cy and Della"*) is `aggregate_subject_mention`, a date with no
    event is `temporal_claim_needs_event_kind`, and a claim with no quotation
    is `evidence_required`.
    """
    if not isinstance(value, dict) or not value:
        return None, claim_refused("claim_not_a_mapping")
    if not set(value) <= CLAIM_PROMPT_KEYS:
        # The closed key set, checked BEFORE the contract sees it: an unknown
        # key means the leaf and this parser disagree about the vocabulary,
        # and that is a defect to name rather than a field to ignore.
        return None, claim_refused(CLAIM_UNKNOWN_KEY)
    payload = dict(value)
    payload.setdefault("basis", CAPTURE_BASIS)
    payload["source_ref"] = {"source_id": UNBOUND_SOURCE_ID,
                             "revision": UNBOUND_REVISION}
    payload["source_kind"] = "conversation"
    payload["extractor_version"] = UNBOUND_EXTRACTOR
    try:
        normalized = tc.validate_temporal_claim(payload)
    except tc.TemporalContractError as exc:
        return None, claim_refused(getattr(exc, "code", "") or str(exc))
    draft = {key: normalized[key] for key in CLAIM_DRAFT_KEYS
             if key in normalized}
    if "confidence" not in value:
        # The contract defaults an unstated confidence to 0.0; a draft that
        # carried it would be asserting "no support" for something the person
        # said out loud. Calibration is the fold's, so the draft says nothing
        # and binding restores the contract's own default.
        draft.pop("confidence", None)
    return draft, ""


def parse_claims(payload: object) -> tuple[tuple[dict, ...], tuple[str, ...]]:
    """A leaf's ``claims`` list, validated PER CLAIM. ``(drafts, findings)``.

    The same discipline the two record lists already have: each claim runs the
    validator ALONE, so a refused one drops by itself and never takes a
    sibling with it — the founder's twelve-job answer must not be lost because
    the eleventh job named an event kind the contract cannot read — and
    duplicates collapse. Accepts the singular ``{"claim": {...}}`` shape too,
    for the same reason `parse_recorder_output` accepts ``{"landmark": ...}``:
    a model that emits one fact often emits it singular.
    """
    if isinstance(payload, dict):
        payload = [payload]
    if not isinstance(payload, (list, tuple)):
        return (), ()
    drafts: list[dict] = []
    findings: list[str] = []
    for candidate in payload:
        draft, finding = validate_claim_draft(candidate)
        if draft is not None:
            if draft not in drafts:
                drafts.append(draft)
        elif finding:
            findings.append(finding)
    return tuple(drafts), tuple(dict.fromkeys(findings))


def bind_claims(drafts: object, *, source_ref: object,
                extractor_version: object,
                source_kind: str = "conversation",
                now: object = None) -> list[dict]:
    """Bind drafts to the source that was promoted for them. The filing half.

    A draft becomes a claim exactly when there is a vault source to cite
    (Amendment 2 / option B): the message is promoted first, its
    :class:`temporal_claims.SourceRef` comes back, and every draft from that
    message binds to it — one message, one source, N claims, all citing the
    same revision. The claim id is DERIVED here for the first time, which is
    why a retry of the same extraction over the same revision mints the same
    ids and files nothing twice.

    Raises the contract's own error on a draft that will not bind; a draft
    that survived :func:`validate_claim_draft` binds by construction, so a
    raise here means the binding itself is wrong.
    """
    ref = tc.validate_source_ref(source_ref)
    version = tc.collapsed_text(extractor_version)
    bound: list[dict] = []
    for draft in (drafts or ()):
        if not isinstance(draft, dict) or not draft:
            continue
        payload = {key: value for key, value in draft.items()
                   if key not in CLAIM_BINDING_KEYS}
        payload["source_ref"] = ref
        payload["source_kind"] = source_kind
        payload["extractor_version"] = version
        claim = tc.validate_temporal_claim(payload, now=now)
        if claim not in bound:
            bound.append(claim)
    return bound


# --------------------------------------------------------------------------
# 7. Identity assertions — stated bindings, from ordinary conversation
#    (event identity I3, design §6.4, an ADR 0029 amendment)
# --------------------------------------------------------------------------
#
# The settled product contract says information given in ordinary
# conversation is usable (audit B4) — *"that was the same trip"* must be a
# source too, not only something a Timeline conversation can hear. So the
# listener gains a FOURTH typed output, `identity_assertions`, exactly the
# shape `claims` arrived in at v229: the leaf emits MENTIONS — a hint at the
# telling, a hint at the episode, and the relation the person actually
# asserted — and this layer, never the model, resolves each hint against a
# CANDIDATE-CONTEXT excerpt the host supplies (the episode roster and their
# tellings' own labels, already on the page the person is looking at).
#
# **Zero or two matches per hint is a REFUSAL, not a guess.** An ambiguous or
# unresolved hint mints no binding — it is reported by name
# (:data:`IDENTITY_ASSERTION_REFUSED_PREFIX`) so the ordinary `same_event`
# question path can pick it up instead of a wrong link firing silently (Law
# 6). There is no draft/bind split for the RESOLUTION half — the candidate
# context is available at PARSE time, not only at filing time — but there is
# still a draft/bind split for what only the FILER knows:
# `origin`/`rule_version`/`source_ref`/`created_at`. :func:`bind_identity_assertions`
# is that filing half; :func:`event_identity.file_event_identity` is the only
# writer either path ever reaches.

#: The three fields a leaf may emit for ONE identity assertion — MENTIONS,
#: never refs. Deliberately closed, like every other prompt-key set in this
#: module.
IDENTITY_ASSERTION_PROMPT_KEYS = frozenset({"telling_hint", "episode_hint", "relation"})

#: The draft's own field order.
IDENTITY_ASSERTION_DRAFT_KEYS = ("telling_ref", "episode_id", "relation", "evidence")

#: A dropped identity assertion carries this prefix plus a named code — the
#: person said something; the record must say why it did not survive.
IDENTITY_ASSERTION_REFUSED_PREFIX = "identity_assertion_refused:"

IDENTITY_ASSERTION_UNKNOWN_KEY = "identity_assertion_unknown_key"
IDENTITY_ASSERTION_UNKNOWN_RELATION = "identity_assertion_unknown_relation"
IDENTITY_ASSERTION_AMBIGUOUS_TELLING = "identity_assertion_ambiguous_telling_hint"
IDENTITY_ASSERTION_AMBIGUOUS_EPISODE = "identity_assertion_ambiguous_episode_hint"
IDENTITY_ASSERTION_UNRESOLVED_TELLING = "identity_assertion_unresolved_telling_hint"
IDENTITY_ASSERTION_UNRESOLVED_EPISODE = "identity_assertion_unresolved_episode_hint"


def identity_assertion_refused(code: object) -> str:
    """The named finding a refused identity assertion carries."""
    return f"{IDENTITY_ASSERTION_REFUSED_PREFIX}{tc.collapsed_text(code) or 'unknown'}"


def _resolve_identity_hint(hint: object, candidates: object, *, kind: str) -> tuple[str | None, str]:
    """``(ref, "")`` on exactly one match; ``(None, code)`` on zero or two+.

    ``candidates`` is the host's own excerpt — never the model's guess —
    of ``{"ref": telling_ref_or_episode_id, "kind": "telling" | "episode",
    "labels": [...]}`` rows. Matching is exact-or-substring on normalized
    text, deliberately generous: a generous MATCH is cheap to double-check
    (it either resolves to one thing or it refuses), while a generous
    THRESHOLD that bound something wrong would not be.
    """
    text = tc.collapsed_text(hint).casefold()
    unresolved = (
        IDENTITY_ASSERTION_UNRESOLVED_TELLING if kind == "telling"
        else IDENTITY_ASSERTION_UNRESOLVED_EPISODE
    )
    if not text:
        return None, unresolved
    matches: set[str] = set()
    for row in candidates or ():
        if not isinstance(row, dict) or tc.collapsed_text(row.get("kind")) != kind:
            continue
        ref = tc.collapsed_text(row.get("ref"))
        if not ref:
            continue
        for label in row.get("labels") or ():
            label_text = tc.collapsed_text(label).casefold()
            if label_text and (label_text == text or label_text in text or text in label_text):
                matches.add(ref)
                break
    if len(matches) == 1:
        return next(iter(matches)), ""
    ambiguous = (
        IDENTITY_ASSERTION_AMBIGUOUS_TELLING if kind == "telling"
        else IDENTITY_ASSERTION_AMBIGUOUS_EPISODE
    )
    return None, (unresolved if not matches else ambiguous)


def validate_identity_assertion_draft(
    value: object, *, candidates: object = (),
) -> tuple[dict | None, str]:
    """One emitted assertion, resolved against ``candidates``. ``(draft, finding)``.

    ``finding`` is ``""`` when the draft is kept. A relation outside
    `episode_fold_contract.RELATIONS` (``same``/``part_of``/``related``/
    ``not_same`` — never ``unknown``, which is an epistemic state on a work
    item, not something a person STATES) is refused by name, and so is a hint
    that resolves to zero or two-or-more candidates.
    """
    if not isinstance(value, dict) or not value:
        return None, identity_assertion_refused("not_a_mapping")
    if not set(value) <= IDENTITY_ASSERTION_PROMPT_KEYS:
        return None, identity_assertion_refused(IDENTITY_ASSERTION_UNKNOWN_KEY)
    relation = tc.collapsed_text(value.get("relation"))
    if relation not in efc.RELATIONS:
        return None, identity_assertion_refused(IDENTITY_ASSERTION_UNKNOWN_RELATION)
    telling_ref, telling_finding = _resolve_identity_hint(
        value.get("telling_hint"), candidates, kind="telling",
    )
    if telling_ref is None:
        return None, identity_assertion_refused(telling_finding)
    episode_id, episode_finding = _resolve_identity_hint(
        value.get("episode_hint"), candidates, kind="episode",
    )
    if episode_id is None:
        return None, identity_assertion_refused(episode_finding)
    draft = {
        "telling_ref": telling_ref,
        "episode_id": episode_id,
        "relation": relation,
        "evidence": {
            "telling_quote": tc.collapsed_text(value.get("telling_hint")),
            "episode_quote": tc.collapsed_text(value.get("episode_hint")),
        },
    }
    return draft, ""


def parse_identity_assertions(
    payload: object, *, candidates: object = (),
) -> tuple[tuple[dict, ...], tuple[str, ...]]:
    """A leaf's ``identity_assertions`` list, validated PER ASSERTION.

    Same discipline as :func:`parse_claims`: each assertion is judged alone,
    so one ambiguous hint never costs a sibling that resolved cleanly.
    """
    if isinstance(payload, dict):
        payload = [payload]
    if not isinstance(payload, (list, tuple)):
        return (), ()
    drafts: list[dict] = []
    findings: list[str] = []
    for candidate in payload:
        draft, finding = validate_identity_assertion_draft(candidate, candidates=candidates)
        if draft is not None:
            if draft not in drafts:
                drafts.append(draft)
        elif finding:
            findings.append(finding)
    return tuple(drafts), tuple(dict.fromkeys(findings))


def bind_identity_assertions(
    drafts: object, *, source_ref: object = None, now: object = None,
) -> list[dict]:
    """Drafts, plus what only the filer knows — ``origin: "stated"`` and the
    rule version — ready for `event_identity.file_event_identity`.

    Spontaneous conversation is `stated` origin, never `confirmed`: the
    person was not answering a directed `same_event` question (that path,
    `identity_questions.resolve_same_event_answer`, is where `confirmed`
    comes from). Both land beside each other under `sources/identity/` —
    Law 7, human decisions are sources, not state.
    """
    import event_identity as ei  # noqa: PLC0415

    bound: list[dict] = []
    for draft in (drafts or ()):
        if not isinstance(draft, dict) or not draft:
            continue
        payload = dict(draft)
        payload["origin"] = "stated"
        payload["rule_version"] = ei.IDENTITY_RULE_VERSION
        payload["source_ref"] = tc.collapsed_text(source_ref) or None
        payload["created_at"] = now
        if payload not in bound:
            bound.append(payload)
    return bound


# -- the extractor's own identity ------------------------------------------

#: How much of a leaf's digest names its version. A prompt edit is a NEW
#: extractor: it lands on a new receipt path beside the old one rather than
#: rewriting yesterday's reading (`temporal_store.write_receipt`), which is
#: the §4.2 invariant that makes "a later model is a new interpretation"
#: true of a later PROMPT as well.
PROMPT_VERSION_LENGTH = 12


def leaf_prompt_version(leaf: object) -> str:
    """A stable short digest of the leaf text a completion was drawn from."""
    import hashlib  # noqa: PLC0415

    body = leaf if isinstance(leaf, str) else ""
    return hashlib.sha256(body.encode("utf-8")).hexdigest()[:PROMPT_VERSION_LENGTH]


def claim_extractor(name: str, *, leaf: object, model: object = None) -> dict:
    """The receipt's structured ``extractor`` block for one capture pass."""
    block: dict = {"name": tc.collapsed_text(name),
                   "schema_version": tc.SCHEMA_VERSION,
                   "prompt_version": leaf_prompt_version(leaf)}
    if tc.collapsed_text(model):
        block["model"] = tc.collapsed_text(model)
    return block


def claim_extractor_version(block: object) -> str:
    """The one canonical spelling of the block above.

    `temporal_claims.extractor_version_string` is the only renderer, so the
    receipt's structured block and its `extractor_version` string cannot say
    two different things about which extractor wrote it.
    """
    data = block if isinstance(block, dict) else {}
    return tc.extractor_version_string(
        data.get("name"),
        schema_version=data.get("schema_version"),
        prompt_version=data.get("prompt_version"),
        model=data.get("model"),
        rule_version=data.get("rule_version"),
    )


LISTENER_EXTRACTOR = "general_listener"


def listener_extractor(*, model: object = DEFAULT_LISTENER_ROLE,
                       framework_root: str | Path | None = None) -> dict:
    """This pass's extractor block, versioned by its OWN leaf's bytes."""
    return claim_extractor(LISTENER_EXTRACTOR,
                           leaf=load_listener_leaf(framework_root),
                           model=model)


def listener_extractor_version(*, model: object = DEFAULT_LISTENER_ROLE,
                               framework_root: str | Path | None = None) -> str:
    return claim_extractor_version(
        listener_extractor(model=model, framework_root=framework_root))


# -- the plurality backstop, read over claims ------------------------------

#: The RETRYABLE claims lint (v229), and deliberately the claims-shaped twin
#: of `landmarks_interaction.RECORD_EVERY_ENTRY_LINT` rather than a second
#: severity: it fires on evidence that facts were missed, a host answers it
#: with ONE regeneration, and then it files what it has. It can never cost the
#: person a claim that was already made, and it never withholds.
CLAIMS_MISSING_SUBJECTS_LINT = "landmark_gates.claims_missing_subjects"

#: What a host appends to the ONE regeneration when the lint above fires.
#: Same double sentence `LISTENING_REMINDER` carries, for the same reason:
#: name what was missed, and forbid inventing anything to satisfy it.
EVERY_CLAIM_REMINDER = (
    "You emitted {count} claim(s) and they stated more than that{term_clause}. "
    "One claim per asserted fact: every person named is their own claim, "
    "every date is the date of ONE event, and a fact fixed against another "
    "moment is a `relative_order` claim rather than a dropped one. Emit them "
    "all — and add nothing they did not say to make the list longer."
)


def every_claim_reminder(count: object = 0, missed: object = ()) -> str:
    """:data:`EVERY_CLAIM_REMINDER`, naming what went unclaimed."""
    names = [" ".join(group) if isinstance(group, (list, tuple)) else str(group)
             for group in (missed or ())]
    quoted = ", ".join(f'"{name}"' for name in names[:4])
    clause = f" — {quoted}" if quoted else ""
    try:
        number = int(count)
    except (TypeError, ValueError):
        number = 0
    return EVERY_CLAIM_REMINDER.format(count=number, term_clause=clause)


def claims_missing_subjects(user_message: object, claims: object, *,
                            known_labels: object = ()) -> dict | None:
    """The one definition of "they asserted more facts than came back".

    v214's class, read over the claims list. It is a BINDING of that class's
    two decidable primitives, not a second copy of them: the proper-noun
    grouping is `landmarks_interaction._name_groups` and the coverage test is
    `landmarks_interaction._record_terms`, both read by name, because a second
    table of what a name looks like is exactly the recurring defect the
    package's doctrine forbids (docs/BUILDING.md §7).

    What it does NOT inherit is the domain half — the identity rung, the
    per-entry dating rule, the none/skip terminals — because a claim has no
    domain to be complete for. What replaces it is the contract's own
    cardinality rule: one claim per independently asserted subject/event
    (plan §5.1), so an uncovered name is a missed claim wherever it appears.

    Returns a finding (``lint`` / ``detail`` / ``missed``) or ``None``, and
    ``None`` for everything it cannot decide. A false positive costs one
    haiku-class regeneration and nothing else.
    """
    filed = [claim for claim in (claims or ()) if isinstance(claim, dict) and claim]
    if not filed:
        # Nothing at all is the backstop's question (`listener_heard_nothing`
        # / `answer_must_record`), not this one. Two classes, two questions.
        return None
    text = user_message if isinstance(user_message, str) else ""
    if not text.strip():
        return None
    known = {str(label).strip().lower() for label in (known_labels or ())
             if str(label).strip()}
    covered = li._record_terms(filed) | known  # noqa: SLF001
    for label in known:
        covered |= {token.lower()
                    for token in li._RECORD_TOKEN_RE.findall(label)}  # noqa: SLF001
    missed = [group for group in li._name_groups(text)  # noqa: SLF001
              if group[0] not in covered]
    floor = 1 if len(filed) > 1 else 2
    detail = ""
    if len(missed) >= floor:
        detail = (
            f"they named {len(missed) + len(filed)} things and {len(filed)} "
            "claim(s) came back — one claim per asserted fact: "
            + ", ".join(" ".join(group) for group in missed[:4])
            + " were not claimed"
        )
    else:
        stated = set(chrono.YEAR_RE.findall(text)) - known
        dated = sum(1 for claim in filed
                    if claim.get("claim_type") in tc.DATED_CLAIM_TYPES)
        if len(stated) >= 2 and dated < len(stated):
            detail = (
                f"they stated {len(stated)} separate dates and {dated} "
                "claim(s) carry one — every date is the date of ONE event"
            )
    if not detail:
        return None
    return {"lint": CLAIMS_MISSING_SUBJECTS_LINT, "detail": detail,
            "missed": tuple(" ".join(group) for group in missed[:4])}


def render_event_kinds() -> str:
    """The seed event vocabulary, as the leaf shows it.

    DERIVED from `temporal_claims.EVENT_KINDS` rather than re-typed, so the
    day a kind joins the contract the leaf offers it without a second edit.
    The set is a SEED and not a closed one (the contract accepts any lowercase
    token), which the leaf says out loud — refusing an event the person
    plainly named would be the drop this whole pass exists to end.
    """
    return " | ".join(tc.EVENT_KINDS)



# --------------------------------------------------------------------------
# 8. Person identity — a conversation can teach who somebody is
#    (v387, identity design §4.1.4, ADR 0029 amendment 2026-10-04)
# --------------------------------------------------------------------------
#
# Before v387 an answer could not teach identity. *"Mara Ellis Dunn is my
# wife, the Mara Holt I talk about"* filed nothing: this listener ran only
# when the datable prescreen fired (that sentence has no date), its `people`
# list carries DATES and drops a dateless person, and had a date been present
# it would have `--ensure`d a brand-new row `mara-ellis-dunn` — a duplicate.
#
# So the listener gains a typed `person_identity` list. (The design calls it
# the `identity` list; the JSON key says `person_` because this module already
# owns `identity_assertions`, the EVENT-identity list, and a model shown both
# `identity` and `identity_assertions` side by side is being invited to mix
# them up.) Each item is what the person TAUGHT:
#
#   {"name": "Mara Ellis Dunn", "refers_to": "Mara Holt",
#    "relationship": "wife", "evidence": "Mara Ellis Dunn is my wife"}
#
# and, exactly like `identity_assertions`, the model emits MENTIONS and THIS
# layer resolves them — through `person_resolution.resolve_person` (the
# adapter onto I-1's `identity_resolution.resolve_person`) against the roster
# snapshot the host supplies. Never a model-minted ref.
#
# Four outcomes, by name (:data:`PERSON_IDENTITY_RESOLUTIONS`):
#
# * ``resolved`` — exactly one person: the record carries ``alias_of`` and
#   :func:`identity_invocations` files ``--alias <name>`` on it (plus
#   ``--relationship`` only when the record has none yet).
# * ``ambiguous`` — two or more candidates (two spouses on record; "my son"
#   in a family with two sons; a name already borne by somebody else). Nothing
#   is filed; the host turns the record into the existing `identity_uncertain`
#   Mirror row naming every claimant.
# * ``unknown_person`` — nobody on the roster. **A conversation never mints a
#   person (D3)**: nothing is filed; the host raises "New person?" as Play.
# * ``unknown_handle`` — an explicit ``@handle`` (design §4.1.4b) that names
#   no record. Never guessed at, never fuzzily matched.
#
# FAMILY-ONLY for relationship words, by the same deterministic guard the
# `people` list uses (`landmarks_interaction.person_date_relations`): a record
# whose relationship word maps outside the family is DROPPED with
# :data:`DROPPED_IDENTITY_NOT_FAMILY` — a decision, not a miss.
#
# **THE REPLY ACKNOWLEDGES ONLY AFTER FILING (D4).** ADR 0028's "speak, then
# file" is deliberately reversed for identity: a host files the argv this
# module names FIRST, and only on a successful verdict may the reply say so,
# through :func:`acknowledgement_line`. A wrong "got it" is worse than a plain
# reply, and an alias refused by the collision rule must never be announced.
#
# The cost is budgeted under its own purpose, :data:`IDENTITY_RECORD_PURPOSE`
# — never `date_record` — so a host weights and audits it on its own row.

#: The listener's THIRD purpose name. A host registers its own weight; this
#: package names the purpose and invents no number.
IDENTITY_RECORD_PURPOSE = "identity_record"

#: The blocking/retryable lint of the identity half — the
#: :data:`LISTENER_HEARD_NOTHING_LINT` shape: the identity prescreen saw
#: somebody being named and nothing came back.
IDENTITY_HEARD_NOTHING_LINT = "landmark_gates.identity_heard_nothing"

#: The keys a leaf may emit on ONE identity record — MENTIONS, never refs.
PERSON_IDENTITY_PROMPT_KEYS = frozenset({"name", "refers_to", "relationship",
                                         "evidence"})

IDENTITY_RESOLVED = "resolved"
IDENTITY_AMBIGUOUS = "ambiguous"
UNKNOWN_PERSON = "unknown_person"
UNKNOWN_HANDLE = "unknown_handle"
PERSON_IDENTITY_RESOLUTIONS = (IDENTITY_RESOLVED, IDENTITY_AMBIGUOUS,
                               UNKNOWN_PERSON, UNKNOWN_HANDLE)

#: Named drops. A non-family relationship word is a DECISION (it clears the
#: backstop, like :data:`DROPPED_NON_FAMILY`); a malformed record is not.
DROPPED_IDENTITY_NOT_FAMILY = "identity_relation_not_family"
DROPPED_IDENTITY_MALFORMED = "identity_record_malformed"
IDENTITY_DECISION_FINDINGS = frozenset({DROPPED_IDENTITY_NOT_FAMILY})

#: A capitalised name, case-sensitive by design — that capital IS the signal.
#: Never a pronoun, a determiner, a sentence-opening function word, or a
#: relationship word ("Mom was my rock" teaches nobody a name).
_NAME_STOP = (r"(?!(?:I|He|She|They|We|It|This|That|These|Those|There|Here|My|"
              r"Our|His|Her|Their|And|But|So|Then|When|What|Who|Yes|No|"
              r"The|A|An|" + "|".join(
                  w.capitalize() for w in sorted(
                      ir.RELATIONSHIP_MENTION_WORDS,
                      key=len, reverse=True)) + r")\b)")
_NAME_WORD = r"[A-Z](?:[a-z'\u2019]+|[A-Z]{1,3}\b)"
_NAME = (_NAME_STOP + _NAME_WORD + r"(?:[ -](?:" + _NAME_STOP + _NAME_WORD
         + r"|[A-Z]\.))*")

#: The relationship words — DERIVED from
#: `identity_resolution.RELATIONSHIP_MENTION_WORDS`, never re-typed.
_REL_WORDS = "|".join(sorted(
    ir.RELATIONSHIP_MENTION_WORDS,
    key=len, reverse=True))
_REL = rf"(?i:(?:my|our)\s+(?:[a-z]+\s+){{0,2}}(?:{_REL_WORDS})s?)\b"

#: The explicit-reference token (design §4.1.4b).
_HANDLE = r"@[a-z0-9][a-z0-9-]*"

#: reason -> patterns, the `PRESCREEN_TABLES` shape. Each pattern's ``name``
#: group (or ``handle``) is what the restatement check resolves.
IDENTITY_PRESCREEN_TABLES: dict[str, tuple] = {
    # "Mara Ellis Dunn is my wife" / "Bo was our grandpa"
    "name_is_relation": (
        re.compile(rf"(?P<name>{_NAME})\s+(?:is|was)\s+(?:also\s+)?{_REL}"),
    ),
    # "my wife Mara" / "my wife, Mara Ellis" / "Mara, my wife"
    "relation_name": (
        re.compile(rf"\b{_REL},?\s+(?P<name>{_NAME})"),
        re.compile(rf"(?P<name>{_NAME}),\s+{_REL}"),
    ),
    # "Mara is my ..." — the design's bare "is/was my"
    "is_my": (
        re.compile(rf"(?P<name>{_NAME})\s+(?:is|was)\s+(?:also\s+)?(?:my|our)\b"),
    ),
    # "also known as BL", "goes by Kit", "née Merrill", "we called her Dot"
    "also_known_as": (
        re.compile(r"(?i:\b(?:also\s+known\s+as|a\.?k\.?a\.?|goes\s+by|"
                   r"went\s+by|n[ée]e))\s+(?P<name>" + _NAME + ")"),
        re.compile(r"(?i:\bwe\s+(?:call|called)\s+(?:her|him|them))\s+"
                   r"(?P<name>" + _NAME + ")"),
    ),
    # "this is @mara-holt", "same as @dad", "@mara-holt is ..."
    "handle": (
        re.compile(r"\b(?:is|this\s+is|same\s+as|in)\s+(?P<handle>" + _HANDLE + ")",
                   re.IGNORECASE),
        re.compile(r"(?P<handle>" + _HANDLE + r")\s+(?:is|was)\b", re.IGNORECASE),
    ),
}
IDENTITY_PRESCREEN_REASONS = tuple(IDENTITY_PRESCREEN_TABLES)


def may_contain_identity(text: object) -> Verdict:
    """*Could* this message teach who somebody is? Deterministic.

    The :func:`may_contain_datable` twin: a capitalised name within one clause
    of a relationship word, of "is/was my", "also known as", "goes by", "née",
    "we call(ed) her/him", or an ``@handle`` beside "is"/"this is"/"same as"/
    "in". Matched per CLAUSE, so a relationship word in one clause never
    reaches a name in the next. ``terms`` are the names (and ``@handles``)
    seen — what :func:`identity_heard_nothing` resolves to recognise a
    restatement. Over-firing costs one haiku-class regeneration; under-firing
    is a name nobody hears.
    """
    body = text if isinstance(text, str) else ""
    if not body.strip():
        return Verdict(False)
    reasons: list[str] = []
    terms: list[str] = []
    for clause in re.split(r"[.;!?\n]+", body):
        if not clause.strip():
            continue
        for reason in IDENTITY_PRESCREEN_REASONS:
            for pattern in IDENTITY_PRESCREEN_TABLES[reason]:
                for match in pattern.finditer(clause):
                    groups = match.groupdict()
                    term = " ".join((groups.get("name") or groups.get("handle")
                                     or "").split())
                    if reason not in reasons:
                        reasons.append(reason)
                    if term and term not in terms and len(terms) < MAX_TERMS:
                        terms.append(term)
    ordered = tuple(r for r in IDENTITY_PRESCREEN_REASONS if r in reasons)
    return Verdict(bool(ordered), ordered, tuple(terms))


def should_listen(text: object) -> bool:
    """The host's gate for running the listener at all (identity §4.2.5): the
    datable prescreen OR the identity prescreen. A message that only teaches
    a name — no date anywhere — is now heard."""
    return bool(may_contain_datable(text)) or bool(may_contain_identity(text))


#: What a host appends to the ONE regeneration when the identity lint fires.
IDENTITY_REMINDER = (
    "You recorded no `person_identity`, and they named somebody{term_clause}. "
    "Read it again: if they said who a person is — another name for someone "
    "(\"X is my wife\", \"also known as\", \"goes by\", \"this is @handle\") — "
    "emit a `person_identity` record for it. Record only what they actually "
    "said — never invent a name, a relationship or a person — and if they "
    "taught nobody anything, emit the empty list."
)


def identity_reminder(verdict: object = None) -> str:
    terms = tuple(getattr(verdict, "terms", ()) or ())
    clause = ""
    if terms:
        clause = " — " + ", ".join(f'"{term}"' for term in terms[:4])
    return IDENTITY_REMINDER.format(term_clause=clause)


def _identity_term_consumed(term: str, person_roster: object) -> bool:
    """A name the roster ALREADY resolves is a restatement, not a lesson.

    v388: a resolution reached only by the FIRST-NAME rung ("Rosalind Ann
    Quill" sharing "Rosalind" with one record) is not a restatement — the
    full name is exactly the lesson the listener exists to hear."""
    import person_resolution as pr  # noqa: PLC0415

    found = pr.resolve_person(term, person_roster)
    return found.resolved and found.reason != "first_name"


def _heard_tokens(heard: object) -> frozenset[str]:
    """Every word of every string value of every record already heard."""
    tokens: set[str] = set()

    def walk(value: object) -> None:
        if isinstance(value, str):
            tokens.update(t.casefold() for t in _TERM_TOKEN_RE.findall(value))
        elif isinstance(value, dict):
            for item in value.values():
                walk(item)
        elif isinstance(value, (list, tuple)):
            for item in value:
                walk(item)

    walk(heard)
    return frozenset(tokens)


def identity_heard_nothing(user_message: object, person_identity: object, *,
                           findings: object = (), verdict: object = None,
                           person_roster: object = (),
                           also_heard: object = ()) -> dict | None:
    """The one definition of "somebody was named and no identity came back".

    :func:`listener_heard_nothing`'s shape, read over the identity list: a
    finding or ``None``. ``None`` when an identity record came back, when a
    family-only drop decided it (:data:`IDENTITY_DECISION_FINDINGS`), when the
    prescreen did not fire, when the person declined, or when EVERY name the
    prescreen saw already resolves on the roster — v216's restatement dedupe,
    decidable here because the roster answers it — or is already named by a
    record the same completion DID return (``also_heard``: "my sister Ruth
    was born in 1948" is answered by Ruth's `people` record, and a retry
    asking for her identity too would be noise).
    """
    if any(isinstance(item, dict) and item for item in (person_identity or ())):
        return None
    if IDENTITY_DECISION_FINDINGS & set(findings or ()):
        return None
    if verdict is None:
        verdict = may_contain_identity(user_message)
    if not getattr(verdict, "fired", False):
        return None
    if li.answer_shape(user_message, "") == "skip":
        return None
    terms = tuple(getattr(verdict, "terms", ()) or ())
    covered = _heard_tokens(also_heard)
    if terms and all(
            _identity_term_consumed(term, person_roster)
            or _consumed(term, covered) for term in terms):
        return None
    quoted = ", ".join(f'"{term}"' for term in terms[:4]) or ", ".join(
        getattr(verdict, "reasons", ()) or ())
    return {
        "lint": IDENTITY_HEARD_NOTHING_LINT,
        "detail": ("they named somebody and no identity was recorded — "
                   f"{quoted}: emit the person_identity record"),
        "reasons": tuple(getattr(verdict, "reasons", ()) or ()),
    }


def _family_relationship(word: object) -> tuple[str, bool]:
    """``(roster relationship, is_family)`` for a spoken relationship word."""
    import roster_relations as rr  # noqa: PLC0415

    stem = ir.relation_word_stem(word) or ir.normalized_mention_key(word)
    relationship = rr.roster_relationship_for(stem) if stem else ""
    if not relationship and stem in li.person_date_relations():
        relationship = stem
    return relationship, relationship in li.person_date_relations()


def validate_person_identity(value: object, *,
                             person_roster: object = ()) -> tuple[dict | None, str]:
    """One emitted identity record, RESOLVED here. ``(record, finding)``.

    The returned record is ``{name, alias_of, alias_of_name, relationship,
    basis, evidence, resolution, candidates, file_relationship}``:
    ``alias_of`` is a ``person/<slug>`` ref ONLY when ``resolution`` is
    ``resolved``; ``basis`` is ``handle`` when the person typed an explicit
    ``@handle`` and ``statement`` otherwise.
    """
    import person_resolution as pr  # noqa: PLC0415

    if not isinstance(value, dict) or not value:
        return None, DROPPED_IDENTITY_MALFORMED
    if not set(value) <= PERSON_IDENTITY_PROMPT_KEYS:
        return None, DROPPED_IDENTITY_MALFORMED
    name = tc.collapsed_text(value.get("name"))[:PERSON_NAME_LIMIT]
    if not name or not li.person_slug(name) or pr.parse_handles(name):
        return None, DROPPED_IDENTITY_MALFORMED
    refers_to = tc.collapsed_text(value.get("refers_to"))
    word = tc.collapsed_text(value.get("relationship")).casefold() or None
    if word in ("unknown", "none"):
        word = None
    relationship = ""
    if word:
        relationship, family = _family_relationship(word)
        if not family:
            # D3 + the owner's family-only ruling, enforced HERE, not by the leaf.
            return None, DROPPED_IDENTITY_NOT_FAMILY
    record: dict = {"name": name, "alias_of": None, "alias_of_name": None,
                    "relationship": word, "basis": pr.BASIS_STATEMENT,
                    "evidence": tc.collapsed_text(value.get("evidence")) or None,
                    "resolution": UNKNOWN_PERSON, "candidates": [],
                    "file_relationship": None}

    handles = pr.parse_handles(refers_to)
    if handles:
        # §4.1.4b: an explicit reference. Exact, no model judgement.
        record["basis"] = pr.BASIS_HANDLE
        found = pr.resolve_handle(handles[0], person_roster)
        if not found.resolved:
            record["resolution"] = UNKNOWN_HANDLE
            record["handle"] = handles[0]
            return record, ""
    else:
        found = _resolve_target(refers_to, word, person_roster)

    if found.kind == pr.AMBIGUOUS:
        record["resolution"] = IDENTITY_AMBIGUOUS
        record["candidates"] = list(found.candidates)
        return record, ""
    if not found.resolved:
        record["candidates"] = list(found.candidates)
        return record, ""
    # The taught name must not already be somebody ELSE's: that is a
    # collision, never a silent re-point.
    owner = pr.resolve_person(name, person_roster)
    if owner.resolved and owner.ref != found.ref:
        record["resolution"] = IDENTITY_AMBIGUOUS
        record["candidates"] = [found.ref, owner.ref]
        return record, ""
    target = next((row for row in pr.person_rows(person_roster)
                   if pr.ref_of(row) == found.ref), {})
    record["resolution"] = IDENTITY_RESOLVED
    record["alias_of"] = found.ref
    record["alias_of_name"] = tc.collapsed_text(target.get("name")) or None
    record["candidates"] = [found.ref]
    if relationship and not ir.collapsed_text(
            target.get(ir.ROSTER_RELATIONSHIP_KEY)):
        record["file_relationship"] = relationship
    return record, ""


def _resolve_target(refers_to: str, word: str | None, person_roster: object):
    """Who the record is ABOUT: the ``refers_to`` mention and the
    relationship word, each resolved; they must agree or it is ambiguous."""
    import person_resolution as pr  # noqa: PLC0415

    context = {"relationship": word} if word else None
    by_mention = (pr.resolve_person(refers_to, person_roster, context=context)
                  if refers_to else None)
    by_word = (pr.resolve_person(f"my {word}", person_roster)
               if word else None)
    if by_mention is None and by_word is None:
        return pr.Resolution(pr.UNKNOWN, reason="no_target")
    if by_mention is None:
        return by_word
    if by_word is None or not by_word.resolved:
        return by_mention
    if by_mention.resolved and by_mention.ref != by_word.ref:
        return pr.Resolution(pr.AMBIGUOUS,
                             candidates=(by_mention.ref, by_word.ref),
                             reason="mention_and_relationship_disagree")
    if by_mention.kind == pr.UNKNOWN:
        return by_word
    return by_mention


def parse_person_identity(payload: object, *, person_roster: object = ()
                          ) -> tuple[tuple[dict, ...], tuple[str, ...]]:
    """A leaf's ``person_identity`` list, each record judged ALONE."""
    if isinstance(payload, dict):
        payload = [payload]
    if not isinstance(payload, (list, tuple)):
        return (), ()
    records: list[dict] = []
    findings: list[str] = []
    for candidate in payload:
        record, finding = validate_person_identity(candidate,
                                                   person_roster=person_roster)
        if record is not None:
            if record not in records:
                records.append(record)
        elif finding:
            findings.append(finding)
    return tuple(records), tuple(dict.fromkeys(findings))


def identity_invocations(records: object) -> list[list[str]]:
    """The ``entity-verdict`` argv that files each RESOLVED identity record.

    ADR 0021: the package names the argv, the host writes it. Verdict
    ``clear`` (an identity, not a page verdict); ``--alias`` under the v383
    collision rule (`roster_relations.alias_decision` — a refusal surfaces as
    `EntityAliasContested`, which the host turns into an `identity_uncertain`
    row); ``--relationship`` only when the record had none; **never
    ``--ensure``** — a conversation never mints a person (D3). ``ambiguous``,
    ``unknown_person`` and ``unknown_handle`` records file nothing.
    """
    import person_resolution as pr  # noqa: PLC0415

    argvs: list[list[str]] = []
    for record in records or ():
        if not isinstance(record, dict):
            continue
        if record.get("resolution") != IDENTITY_RESOLVED or not record.get("alias_of"):
            continue
        slug = pr.slug_of_ref(record["alias_of"])
        argv = ["entity-verdict", "person", slug, "clear",
                "--alias", str(record["name"])]
        if record.get("file_relationship"):
            argv.extend(["--relationship", str(record["file_relationship"])])
        if argv not in argvs:
            argvs.append(argv)
    return argvs


def handle_statement_records(answer: object, entity_rosters: object, *,
                             subject: str = "", subject_ref: str = ""
                             ) -> tuple[dict, ...]:
    """The statements the person made BY HANDLE — resolved, deterministic, no
    model (design §4.1.4b, P14). ``entity_rosters`` is ``{type: roster}``.

    ``this is @katie`` / ``Kit is @katie`` -> ``--alias`` on that record;
    ``same as @h`` -> ``--fold-into`` (an object or theme that is already a
    record) or ``--alias``; ``@a is in @b`` -> ``--located-in`` (places).
    Every record carries ``basis: "handle"``; ``unknown_handle`` / ``ambiguous``
    / ``unknown_subject`` ones are returned too — so the host can say so — and
    file nothing (:func:`handle_statement_invocations`). See
    `identity_handles.handle_statements`.
    """
    import identity_handles as ih  # noqa: PLC0415

    return tuple(st.to_dict() for st in ih.handle_statements(
        answer, entity_rosters, subject=subject, subject_ref=subject_ref))


def handle_statement_invocations(records: object) -> list[list[str]]:
    """The ``entity-verdict`` argv that files each RESOLVED handle statement.
    The same host contract as :func:`identity_invocations`: file FIRST, then
    (and only then) acknowledge; **never ``--ensure``**."""
    import identity_handles as ih  # noqa: PLC0415

    return ih.statement_invocations(records)


def acknowledgement_line(record: object) -> str:
    """What the reply MAY say — and only AFTER the host filed the record (D4).

    ``""`` for anything not ``resolved``: an ambiguous or unknown record is a
    question for the Mirror, never a "got it".
    """
    if not isinstance(record, dict) or record.get("resolution") != IDENTITY_RESOLVED:
        return ""
    target = record.get("alias_of_name") or ""
    name = record.get("name") or ""
    if not target or not name:
        return ""
    if tc.normalized_mention_key(target) == tc.normalized_mention_key(name):
        return ""
    return f"Got it — {name} is {target}."


# --------------------------------------------------------------------------
# CLI — the stdin-JSON path every prompt builder in this package carries
# --------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    """`general_listener.py [--dry-run] < payload.json`.

    Payload: ``{"answer", "reply"?, "landmarks"?, "person_roster"?}``. ``--dry-run`` prints the
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
            heard_identity = may_contain_identity(answer)
            print(json.dumps({"prescreen": {"fired": verdict.fired,
                                            "reasons": list(verdict.reasons),
                                            "terms": list(verdict.terms)},
                              "identity_prescreen": {
                                  "fired": heard_identity.fired,
                                  "reasons": list(heard_identity.reasons),
                                  "terms": list(heard_identity.terms)}},
                             indent=2, sort_keys=True))
            print(build_listener_prompt(
                answer=answer, reply=payload.get("reply", ""),
                landmarks=payload.get("landmarks") or {},
                person_roster=payload.get("person_roster") or {}))
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
            person_roster=payload.get("person_roster") or {},
            call=call_ai, model=args.model,
        )
    except (li.LandmarkInteractionError, GeneralListenerError) as exc:
        print(json.dumps({"error": str(exc)}))
        return 1
    print(json.dumps({
        "status": outcome.status,
        "records": list(outcome.records),
        "people": list(outcome.people),
        # v229: the claim DRAFTS, unbound. A host binds them to the source it
        # promotes (`landmark_recorder.file_claims`); printing them bound
        # would mean promoting a source from a --dry-run-shaped CLI, which is
        # a write this front door has never made.
        "claims": list(outcome.claims),
        "extractor_version": listener_extractor_version(model=args.model),
        "invocations": li.landmark_invocations(outcome.records)
        + person_invocations(outcome.people),
        # v387: identity argv, kept apart because a host files it FIRST and
        # acknowledges only on success (D4), and budgets it as
        # `identity_record`.
        "person_identity": list(outcome.person_identity),
        "identity_invocations": identity_invocations(outcome.person_identity),
        "attempts": outcome.attempts,
        "lint_ids": list(outcome.lint_ids),
        "findings": list(outcome.findings),
        "reason": outcome.reason,
    }, indent=2, sort_keys=True))
    return 0 if outcome.status in (STATUS_RECORDED, STATUS_NOTHING) else 1


if __name__ == "__main__":
    raise SystemExit(main())
