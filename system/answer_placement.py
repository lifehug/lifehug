#!/usr/bin/env python3
"""Answering a card places its moment (v352).

WHAT THE OWNER HIT, three times in two days, on his own vault:

1. ``sources/conversations/msg-a2a65da9bda477a98f67f20c.md`` — *"This was
   mostly last month and he's stopped mostly now"*, captured
   2026-09-24T01:09:30Z, ``session_ref:
   conversation:cand:work_item:work:577ecc4639edf0f8ead752ca``, answering the
   card **"When did Harvey's love of cussing happen?"**
   (``node:3380558928426602253447c7``). Its classification holds
   ``time_periods: [{era: "last month", approximate_dates: "2026-08"}]`` and
   ``events: []`` — the extractor found the TIME and no event, so
   `classifier_claims` had nothing to file, the general listener heard nothing,
   and the card was still open that night with the node unplaced.
2. ``msg-fc9845c47f8dc2b5099724a5.md`` — *"19-21 years old"*, answering the
   card about his father's mission. The general listener filed
   ``claim:65573521952535272873944a``: ``claim_type: age``, 19–21,
   ``subject_mention: "they"``, ``event_kind: span``, **no ``event_mention``**,
   ``confidence: 0.0``. That minted a node labelled *they* and a card *"When
   was they?"*. v343 suppresses the bogus node; the ANSWER still never reached
   the moment it was about.
3. ``msg-57c728860e184aaf2146b021.md`` — *"He only really started talking when
   he was 4"*, ``session_ref: …work:aae137468432564920dbf100``. Receipt
   ``claim:bf9f8a7a0faeb8bbb1ab77f1``: ``claim_type: age``, 4,
   ``subject_mention: "he"``, ``event_mention: null``. The same shape — a time
   with no event.

ONE CAUSE, and it is not the model being careless. **The reply carries the
WHEN and the card carries the WHAT, and nothing joined them.** Every extractor
that reads a promoted answer is shown the MESSAGE ALONE: the classify prompt
(`classifier_context`, ``contextual-timeline:3``) names no work item, and
`general_listener.build_listener_prompt` takes ``answer`` and ``reply`` and no
question. Asked to find an event in *"19-21 years old"* there is none to find,
so an honest extractor either files nothing (case 1) or files the time against
whatever pronoun the sentence happens to carry (cases 2 and 3). The join was
there the whole time — ``session_ref: conversation:cand:work_item:<id>`` is on
the frontmatter of every promoted message, and the work item's own row (the
published ``state/temporal_claims/work-items.json``) carries ``node_ref``,
``subject_ref`` and the card's own question — and nobody read it.

THE RULE, :data:`ANSWERING_A_CARD_PLACES_ITS_MOMENT`. A reply promoted with a
``session_ref`` naming a work item is read as an answer to THAT work item:

* the TIME it carries — a date, a range, an age, or a recency expression
  resolved against the message's own capture date — becomes a claim on the node
  the card is about, with the reply as its source and the record's basis
  ``stated``, because the person is the one saying it (:func:`answer_reading`);
* the SUBJECT comes from the NODE, never from a pronoun in the reply
  (:func:`aim_at_card`). This is the other half of v343's suppression:
  suppressing the bogus ``they`` node was right, and the answer must still land
  somewhere;
* a reply that carries NO time at all still files as a TELLING of that node —
  an ``occurrence`` claim, which asserts that it happened and says nothing
  about when — so the card stays open with the owner's words visible on it and
  never silently nothing.

NOTHING HERE IS A SECOND PARSER. The date, age and recency rungs are
`chronology`'s own (`parse_stated_date`, `parse_age`, `from_recency` and its
``RECENCY_RUNGS``), in the SAME order `classifier_claims.temporal_reading`
already reads them, and the confidences are that module's own constants. The
one thing this module adds is :data:`AGE_PHRASE_RES` — a CLOSED vocabulary of
age phrasings, because `chronology.parse_age` is a FIELD parser and run over
prose it reads *"March 1998"* as age 8 (`classifier_claims._age_band_text`'s
own year trap, reused here rather than re-decided).

WHAT IT REFUSES, by name:

* **A card nobody published.** The work item must be in the published
  ``work-items.json`` and ``open``. An answer to a card that has already been
  settled files nothing (:data:`REFUSED_CARD_NOT_OPEN`).
* **A node nobody drew.** The card's ``node_ref`` must name a node in the
  published projection, or there is nothing to place
  (:data:`REFUSED_NODE_NOT_DRAWN`).
* **A card whose subject nobody resolved.** ``unresolved:`` is the binder
  saying it does not know WHO — the platform already refuses to file a
  resolution against such a row (Timeline Fix 01 P0b) and so does this
  (:data:`REFUSED_SUBJECT_UNRESOLVED`).
* **A second reading of the same answer.** One answer files ONE claim about
  one card: the claim id is derived from the reply's own revision, so a re-run
  writes nothing (`temporal_store.write_receipt` keeps what is on disk).

WHERE IT RUNS — two seats, one derivation:

* `landmark_recorder.file_claims`, which already receives the ``session_ref``:
  the drafts the listener heard are AIMED at the card before they are bound, so
  cases 2 and 3 land on the right node instead of minting ``they``/``he``, and
  a message whose drafts carry no time files the reading of the reply itself.
* `classifier_claims.migrate_classifier_moments`, the vault's one deterministic
  claim-filing sweep: every promoted answer with a card, whether or not any
  extractor heard anything in it. That is the seat that fixes an answer already
  in the vault — the owner's three — and the backstop that makes "never
  silently nothing" true of a road this module was not told about.

AN EPISODE TARGET IS NOT REFUSED (v353, decided from the code and written here
so it is not re-litigated). The card an answer lands on is often about an
EPISODE — the repeat kinds are where "when did X happen?" clusters (moves, jobs,
schools, teams, residences: `identity_resolution.REPEATABLE_EVENT_KINDS`) — and
the owner's reply really is another telling of that episode, which is exactly
the unit :func:`answer_telling_ref` already mints (v337: one fact inside one
message, keyed on the NODE's digest so two answers to one card are two tellings
of the same fact). So the claim is filed unchanged and there is no
``card_is_an_episode`` refusal: refusing would drop the owner's answers for the
most common card class there is, and it would contradict this module's own
receipt. What v353 fixed is on the other side of the wire, where it belongs: the
FOLD reads "is this node an episode?" off the node id rather than off whichever
claim it read first
(`episode_fold.AN_EPISODE_NODES_KIND_IS_THE_NODES_AND_NOT_ITS_FIRST_CLAIMS`).
Two things here are load-bearing for that and must not drift:
:func:`answer_claim` takes ``event_kind`` from the CARD's node, which for an
episode is that episode's canonical kind, so the claim never argues with the
node about what it is; and the telling is declared and NOT bound — binding is
`episode_binder`'s decision under Law 6 (*a miss is cheap, a wrong link is
not*), never a claim filer's.

Synthetic data only; this module NEVER references a real vault.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

SYSTEM_DIR = Path(__file__).resolve().parent
if str(SYSTEM_DIR) not in sys.path:
    sys.path.insert(0, str(SYSTEM_DIR))

import chronology as chrono  # noqa: E402
import event_identity as ei  # noqa: E402
import landmark_projection as lp  # noqa: E402
import temporal_claims as tc  # noqa: E402
import temporal_publication as pub  # noqa: E402
import temporal_store as store  # noqa: E402
import temporal_work_items as twi  # noqa: E402
from lifehug_core import split_frontmatter  # noqa: E402
from temporal_claims import collapsed_text, normalized_mention_key  # noqa: E402

#: The rule, in one sentence, so a reader and a test name the same thing.
ANSWERING_A_CARD_PLACES_ITS_MOMENT = (
    "a reply promoted with a session_ref naming a work item is an answer to THAT "
    "work item: the time it carries becomes a claim on the node the card is about, "
    "with the reply as its source and basis stated; its subject is the node's and "
    "never a pronoun in the reply; and a reply carrying no time at all is still "
    "filed as a telling of that node"
)

#: This reading's own extractor version. Its own, and not the listener's or the
#: classifier's, for the reason every extractor version exists: two readings of
#: one message are two interpretations under `temporal_claims
#: .CLAIM_IDENTITY_KEYS`, and a shared version would make them one claim that
#: overwrote itself.
EXTRACTOR_VERSION = "answer-placement/rule:1"
EXTRACTOR_NAME = "answer-placement"

#: The marker inside a candidate conversation session that names the work item
#: the person is answering — ``conversation:cand:work_item:work:<hex>``. ONE
#: definition; `resolver` reads it from here rather than keeping a second copy.
SESSION_WORK_ITEM_MARKER = "work_item:"

#: The DAY-SCOPED sibling the platform opens when the plain session for a card
#: has already closed (`app.conversation.store`'s
#: ``…:work:<hex>:<YYYY-MM-DD>``). It is the same card, so the suffix is
#: stripped rather than making a second work id nobody can resolve.
_SESSION_DAY_SUFFIX_RE = re.compile(r":(\d{4}-\d{2}-\d{2})$")

#: A PRONOUN IS NEVER A SUBJECT. The words cases 2 and 3 filed their claims
#: under — ``they``, ``he`` — plus every other bare pronoun a reply can open
#: with. A mention in this set is replaced by the card's own subject; anything
#: else the person actually named is left exactly as they said it, because who
#: a mention names is identity resolution's question and never this module's.
#:
#: The owner's own first person is deliberately ABSENT: *"I was 19"* answering a
#: card about somebody else's mission is the owner talking about himself, and
#: rewriting that to the card's subject would be this module inventing a fact.
PRONOUN_SUBJECT_MENTIONS = frozenset({
    "he", "him", "his", "she", "her", "hers", "they", "them", "their",
    "theirs", "it", "its", "himself", "herself", "themselves", "itself",
})

#: The prefix the binder uses for a subject it could not resolve
#: (Timeline Fix 01 P0b). A card whose subject is one of these knows WHEN but
#: not WHO, and an answer filed against it would be filed against nobody.
UNRESOLVED_SUBJECT_PREFIX = "unresolved:"

#: The work-item states an answer may be read against. ``open`` and nothing
#: else: a settled card's answer was already filed by whatever settled it.
ANSWERABLE_WORK_ITEM_STATES = ("open",)

#: The event kind a card's node falls back to when the projection names none.
#: `temporal_claims.EVENT_KINDS`' own generic, and the same fallback
#: `resolver.targets` uses, so the two agree about an unlabelled moment.
DEFAULT_EVENT_KIND = "moment"

#: Where a promoted conversation message lives. `temporal_store`'s own name for
#: it, read from there rather than restated, so a move of that directory moves
#: this walk with it.
CONVERSATIONS_DIR = store.CONVERSATION_SOURCES_DIR

#: Named refusals, so a report says WHY an answer placed nothing instead of
#: showing a smaller number.
REFUSED_NO_WORK_ITEM = "no_work_item_in_session"
REFUSED_CARD_NOT_PUBLISHED = "card_not_published"
REFUSED_CARD_NOT_OPEN = "card_not_open"
REFUSED_NODE_NOT_DRAWN = "card_node_not_drawn"
REFUSED_SUBJECT_UNRESOLVED = "card_subject_unresolved"
REFUSED_NO_WORDS = "reply_has_no_words"
REFUSED_SOURCE_UNREADABLE = "reply_source_unreadable"
REFUSALS = (
    REFUSED_NO_WORK_ITEM,
    REFUSED_CARD_NOT_PUBLISHED,
    REFUSED_CARD_NOT_OPEN,
    REFUSED_NODE_NOT_DRAWN,
    REFUSED_SUBJECT_UNRESOLVED,
    REFUSED_NO_WORDS,
    REFUSED_SOURCE_UNREADABLE,
)

#: How the three readings are named on a report and on the receipt's extractor
#: block — the rung that fired, so a reader can tell a date the person typed
#: from a recency window the capture date bounded.
READING_DATE = "stated_date"
READING_AGE = "stated_age"
READING_RECENCY = "recency_and_capture_date"
READING_TELLING = "telling_only"
READINGS = (READING_DATE, READING_AGE, READING_RECENCY, READING_TELLING)


# --------------------------------------------------------------------------
# 1. The join: a session names a work item; a work item names a node
# --------------------------------------------------------------------------

def work_item_of_session(session_ref: object) -> str:
    """``conversation:cand:work_item:work:<hex>`` → ``work:<hex>``, else ``""``.

    The day-scoped sibling (``…:work:<hex>:2026-09-24``, which the platform
    opens when the plain session for a card has already closed) resolves to the
    SAME card: a second conversation about one question is not a second
    question.
    """
    text = collapsed_text(session_ref)
    if SESSION_WORK_ITEM_MARKER not in text:
        return ""
    tail = text.split(SESSION_WORK_ITEM_MARKER, 1)[1].strip()
    return _SESSION_DAY_SUFFIX_RE.sub("", tail)


def _node_view(projection: object, node_ref: str) -> dict | None:
    """The published node a card is about, or ``None``."""
    wanted = collapsed_text(node_ref)
    if not wanted:
        return None
    for node in (projection or {}).get("nodes") or ():
        if isinstance(node, dict) and collapsed_text(node.get("node_id")) == wanted:
            return node
    return None


def _node_subject(node: dict, card_subject: str) -> str:
    """WHO the card's node is about: the node's own resolved subject when it has
    exactly one, and the work item's ``subject_ref`` otherwise.

    The node is asked FIRST because ``subject_refs`` is what the fold resolved
    and what the page renders; the work item's own field is the fallback for a
    node the projection publishes without one. Exactly one, because a node two
    people share names neither of them (`temporal_timeline._person_key_index`'s
    own shared-name rule, applied to the other end of the same question).
    """
    refs = [collapsed_text(ref) for ref in (node.get("subject_refs") or ())
            if collapsed_text(ref)]
    if len(refs) == 1:
        return refs[0]
    return collapsed_text(card_subject)


def card_for_work_item(work_item_id: object, *, work_items: object,
                       projection: object) -> tuple[dict | None, str]:
    """``(card, refusal)`` for one work id, from the two published files.

    The card is everything an answer needs and nothing else::

        {"work_item_id", "node_ref", "subject_ref", "event_kind", "label",
         "question", "requested_field", "kind"}

    ``refusal`` is ``""`` when a card came back and one of :data:`REFUSALS`
    when none did. The alias map is consulted first for the reason
    `temporal_work_items.resolve_work_item_id` exists: an id minted last month
    must keep opening its own conversation.
    """
    wanted = collapsed_text(work_item_id)
    if not wanted:
        return None, REFUSED_NO_WORK_ITEM
    rows = [row for row in ((work_items or {}).get("work_items") or ())
            if isinstance(row, dict)]
    aliases = (work_items or {}).get("work_item_aliases")
    aliases = aliases if isinstance(aliases, dict) else {}
    wanted = collapsed_text(twi.resolve_work_item_id(wanted, aliases=aliases)) or wanted
    found = None
    for row in rows:
        row_id = collapsed_text(row.get("work_item_id"))
        if wanted in (row_id, collapsed_text(twi.resolve_work_item_id(row_id, aliases=aliases))):
            found = row
            break
    if found is None:
        return None, REFUSED_CARD_NOT_PUBLISHED
    if collapsed_text(found.get("state")) not in ANSWERABLE_WORK_ITEM_STATES:
        return None, REFUSED_CARD_NOT_OPEN
    node_ref = collapsed_text(found.get("node_ref")) or collapsed_text(found.get("event_ref"))
    node = _node_view(projection, node_ref)
    if node is None:
        return None, REFUSED_NODE_NOT_DRAWN
    subject = _node_subject(node, found.get("subject_ref"))
    if not subject or subject.startswith(UNRESOLVED_SUBJECT_PREFIX):
        return None, REFUSED_SUBJECT_UNRESOLVED
    return {
        "work_item_id": collapsed_text(found.get("work_item_id")),
        "node_ref": node_ref,
        "subject_ref": subject,
        "event_kind": (collapsed_text(node.get("event_kind"))
                       or DEFAULT_EVENT_KIND),
        "label": collapsed_text(node.get("label")),
        "question": collapsed_text(found.get("prompt_intent")),
        "requested_field": collapsed_text(found.get("requested_field")),
        "kind": collapsed_text(found.get("kind")),
    }, ""


def card_for_answer(vault_root: str | Path, session_ref: object, *,
                    work_items: object = None,
                    projection: object = None) -> tuple[dict | None, str]:
    """:func:`card_for_work_item` for the card a ``session_ref`` names.

    ``work_items``/``projection`` are accepted so a sweep reads the two
    published files ONCE for a whole run; absent, they are read here.
    """
    wanted = work_item_of_session(session_ref)
    if not wanted:
        return None, REFUSED_NO_WORK_ITEM
    if work_items is None:
        work_items = pub.read_work_items(vault_root) or {}
    if projection is None:
        projection = pub.read_projection(vault_root) or {}
    return card_for_work_item(wanted, work_items=work_items, projection=projection)


# --------------------------------------------------------------------------
# 2. The reading: what time a reply carries
# --------------------------------------------------------------------------

#: A CLOSED vocabulary of age phrasings, the same discipline
#: `chronology.RECENCY_RUNGS` is. Each pattern captures ONE age text — a number
#: or a band — and that text goes through `chronology.parse_age`, which is the
#: one age parser this repo has. The vocabulary exists because `parse_age` is a
#: FIELD parser: handed prose it reads *"March 1998"* as age 8 and *"1985"* as
#: age 5, which is correct for a field a classifier filled with an age and
#: catastrophic for a sentence.
_AGE_TEXT = r"(\d{1,3}(?:\s*(?:-|–|—|to)\s*\d{1,3})?)"
AGE_PHRASE_RES = (
    # "when he was 4", "while they were 19-21"
    re.compile(r"\b(?:when|while)\s+(?:he|she|they|it|i|we|you)\s+"
               r"(?:was|were)\s+(?:about\s+|around\s+|maybe\s+)?" + _AGE_TEXT,
               re.IGNORECASE),
    # "19-21 years old", "4 yrs old", "19 years"
    re.compile(r"\b" + _AGE_TEXT + r"\s*(?:years?|yrs?|yo)(?:\s*old)?\b",
               re.IGNORECASE),
    # "aged 19-21", "age 4", "the age of 4"
    re.compile(r"\bage[ds]?\s+(?:of\s+)?" + _AGE_TEXT + r"\b", re.IGNORECASE),
    # "at about 4 years old" — "at 19" ALONE is refused: a bare number behind
    # "at" is as often a street number as an age, and ADR 0026 ranks a miss
    # above a wrong join.
    re.compile(r"\bat\s+(?:about\s+|around\s+)?" + _AGE_TEXT
               + r"\s*(?:years?|yrs?)\b", re.IGNORECASE),
)

#: The whole reply is a bare number — *"4"*, *"19-21"* — which answering a
#: "when did this happen?" card makes an AGE and nothing else. Bounded to three
#: digits, and the year trap below still applies, so *"1998"* is never an age.
_BARE_AGE_RE = re.compile(r"^" + _AGE_TEXT + r"$")


def age_phrase(text: object) -> str:
    """The age a reply states, as the words it stated it in, or ``""``.

    TWO REFUSALS, both `chronology.recency_cue`'s own and applied for the same
    reason: a text naming a four-digit year DATES ITSELF (`chronology.YEAR_RE`,
    which is also `classifier_claims._age_band_text`'s guard), and a phrase
    `chronology.parse_age` cannot read is not an age however much it looks like
    one.
    """
    body = collapsed_text(text)
    if not body or chrono.YEAR_RE.search(body):
        return ""
    bare = _BARE_AGE_RE.match(body)
    candidates = [bare.group(1)] if bare else []
    for pattern in AGE_PHRASE_RES:
        match = pattern.search(body)
        if match is not None:
            candidates.append(match.group(1))
    for candidate in candidates:
        found = collapsed_text(candidate)
        if found and chrono.parse_age(found) is not None:
            return found
    return ""


def answer_reading(text: object, *, captured: object = None,
                   question: object = None) -> dict | None:
    """What time this reply carries: ``{claim_type, temporal_value, basis,
    confidence, reading}``, or ``None`` when it carries none.

    The rungs are `classifier_claims.temporal_reading`'s own, in its own order,
    because there is one ladder and this is a second reader of it and not a
    second ladder:

    1. a DATE they said — the whole reply through `chronology.parse_stated_date`,
       which reads *"March 1998"*, *"1998-2001"* and *"around 2005"* and
       refuses prose. A ``date`` claim, and the tightest thing a reply can be;
    2. an AGE they said (:func:`age_phrase`) — an ``age`` claim, which the fold
       measures against the SUBJECT's own birth (v346's
       ``BIRTH_ANCHOR_TIERS``), so *"he was 4"* about a child the roster knows
       places without anybody naming a year;
    3. a RECENCY cue plus the message's own capture date
       (`chronology.from_recency`) — a ``date`` claim whose record is
       ``basis: stated``, because the person is the one saying it was recent
       (v336's owner ruling 1). The CARD'S OWN QUESTION is a haystack here for
       the same reason the prompting question is one in
       `classifier_claims.recency_reading`: somebody answering *"when did this
       happen?"* with *"last month"* has said the word as surely as if the
       question had.

    ``None`` is rung 4 — nothing datable — and the caller files the reply as a
    telling of the card's node instead of inventing a date for it.
    """
    import classifier_claims as ccl  # noqa: PLC0415 — avoids an import cycle

    body = collapsed_text(text)
    if not body:
        return None
    record = chrono.parse_stated_date(body)
    if record is not None:
        return {
            "claim_type": "date",
            "temporal_value": record.to_dict(),
            "basis": "explicit",
            "confidence": lp.CONFIDENCE_SCORE.get(record.confidence, 0.45),
            "reading": READING_DATE,
        }
    age = age_phrase(body)
    if age:
        return {
            "claim_type": "age",
            "temporal_value": age,
            "basis": "explicit",
            "confidence": ccl.AGE_CLAIM_CONFIDENCE,
            "reading": READING_AGE,
        }
    recency = chrono.from_recency(captured, body, collapsed_text(question))
    if recency is not None:
        return {
            "claim_type": "date",
            "temporal_value": recency.to_dict(),
            "basis": "explicit",
            "confidence": ccl.RECENCY_CLAIM_CONFIDENCE,
            "reading": READING_RECENCY,
        }
    return None


def telling_reading() -> dict:
    """The reading of a reply that carries no time: an ``occurrence``.

    It happened — the person answered a card about it — and when is not known.
    That is exactly what `temporal_claims.OCCURRENCE_CLAIM_TYPE` exists to say,
    and it is why the card stays OPEN with the owner's words on the node
    instead of the answer vanishing.
    """
    import classifier_claims as ccl  # noqa: PLC0415

    return {
        "claim_type": tc.OCCURRENCE_CLAIM_TYPE,
        "temporal_value": None,
        "basis": "explicit",
        "confidence": ccl.OCCURRENCE_CLAIM_CONFIDENCE,
        "reading": READING_TELLING,
    }


# --------------------------------------------------------------------------
# 3. Aiming what somebody else heard at the card
# --------------------------------------------------------------------------

def is_pronoun_subject(mention: object) -> bool:
    """Is this subject mention a bare pronoun — i.e. nobody?"""
    return normalized_mention_key(mention) in PRONOUN_SUBJECT_MENTIONS


def aim_at_card(draft: object, card: object) -> dict:
    """One listener draft, AIMED at the card it is an answer to.

    Three edits and no more, each of them the card telling the draft something
    the draft could not know:

    * ``event_ref`` becomes the card's node, so the claim folds onto the moment
      the question was about instead of minting a node of its own
      (`temporal_timeline._group_claims` groups on a claim's own ``event_ref``
      when it carries one);
    * ``subject_mention`` becomes the card's subject when the draft named a
      bare PRONOUN or named nobody at all — cases 2 and 3, verbatim. A name the
      person actually used is never overwritten;
    * ``event_mention`` becomes the node's label when the draft named none, so
      the claim reads as what it is on every surface that shows a mention.

    ``event_kind`` is deliberately left alone: the listener heard the kind from
    the sentence and the card's node may be an episode of another kind, and a
    claim whose kind disagreed with its own evidence would be this module
    editing what somebody said.
    """
    row = dict(draft) if isinstance(draft, dict) else {}
    view = card if isinstance(card, dict) else {}
    node_ref = collapsed_text(view.get("node_ref"))
    if not node_ref:
        return row
    row["event_ref"] = node_ref
    subject = collapsed_text(row.get("subject_mention"))
    if not subject or is_pronoun_subject(subject):
        row["subject_mention"] = collapsed_text(view.get("subject_ref"))
    if not collapsed_text(row.get("event_mention")) and view.get("label"):
        row["event_mention"] = collapsed_text(
            view["label"])[:tc.MAX_EVENT_MENTION_CHARS]
    return row


def aim_drafts(drafts: object, card: object) -> tuple[dict, ...]:
    """:func:`aim_at_card` over a whole listener output, order preserved."""
    if not isinstance(card, dict) or not card.get("node_ref"):
        return tuple(row for row in (drafts or ()) if isinstance(row, dict) and row)
    return tuple(aim_at_card(row, card)
                 for row in (drafts or ()) if isinstance(row, dict) and row)


def drafts_carry_time(drafts: object) -> bool:
    """Does anything the listener heard already assert WHEN?

    The test for whether the deterministic reading is needed at all. A draft of
    a dateless type asserts no time, and neither does a list with nothing in
    it — which is case 1's whole shape.
    """
    for row in (drafts or ()):
        if not isinstance(row, dict):
            continue
        if collapsed_text(row.get("claim_type")) not in tc.DATELESS_CLAIM_TYPES:
            return True
    return False


# --------------------------------------------------------------------------
# 4. Filing
# --------------------------------------------------------------------------

def answer_telling_ref(source_id: object, node_ref: object) -> str:
    """``<promoted source id>#<node hex>`` — one fact inside one message.

    v337's unit, and the answer's own: a reply is a message, the card is ONE
    moment inside it, and `event_identity.conversation_telling_ref` is the one
    minter of that ref. The key is the NODE's digest rather than the reply's
    words, so two answers to one card are two tellings of the SAME fact and the
    binder's `one fact, one episode` rung joins them.
    """
    node = collapsed_text(node_ref)
    return ei.conversation_telling_ref(source_id, node.split(":")[-1])


def answer_claim(card: object, reading: object, *, source_ref: object,
                 quote: object, now: object = None) -> dict:
    """The ONE claim an answer files about its card. Validated, never invented.

    ``basis`` is the CLAIM's epistemic class and it is ``explicit`` because the
    person said it out loud; the RECORD's own basis stays whatever `chronology`
    gave it, which for a recency window is ``stated`` and is why the page
    renders it *placed by you* (v336). Nothing here re-decides either.
    """
    view = card if isinstance(card, dict) else {}
    row = reading if isinstance(reading, dict) else {}
    payload = {
        "source_ref": source_ref,
        "source_kind": "conversation",
        "claim_type": collapsed_text(row.get("claim_type")),
        "subject_mention": collapsed_text(view.get("subject_ref")),
        "event_kind": collapsed_text(view.get("event_kind")) or DEFAULT_EVENT_KIND,
        "event_ref": collapsed_text(view.get("node_ref")),
        "temporal_value": row.get("temporal_value"),
        "evidence": [{"quote": tc.bounded_quote(collapsed_text(quote))}],
        "basis": collapsed_text(row.get("basis")) or "explicit",
        "confidence": row.get("confidence"),
        "extractor_version": EXTRACTOR_VERSION,
    }
    label = collapsed_text(view.get("label"))
    if label:
        payload["event_mention"] = label[:tc.MAX_EVENT_MENTION_CHARS]
    return tc.validate_temporal_claim(payload, now=now)


def file_answer(vault_root: str | Path, *, source_path: object, card: object,
                reading: object, text: object, now: object = None) -> dict:
    """Write the receipt for one answer's one claim. ``{claim_id, receipt_path,
    reading, node_ref, work_item_id}``.

    The reply is ALREADY a vault source — the platform promoted it before
    anything cited it (owner amendment 2 / option B) — so this reads its
    :class:`temporal_claims.SourceRef` off its own frontmatter rather than
    promoting anything a second time. The receipt is immutable and idempotent:
    its path is a function of (source id, revision, extractor version) and
    `temporal_store.write_receipt` keeps what is on disk, so a re-run of a
    sweep files nothing twice.
    """
    root = Path(str(vault_root))
    relative = collapsed_text(source_path)
    ref = store.read_source_ref(root, relative)
    if ref is None:
        raise store.TemporalStoreError(
            REFUSED_SOURCE_UNREADABLE, f"{relative} is not a filed vault source")
    source_ref = {"source_id": ref.source_id, "revision": ref.revision,
                  "source_path": ref.source_path or relative}
    claim = answer_claim(card, reading, source_ref=source_ref, quote=text, now=now)
    extractor = ei.declare_tellings(
        {"name": EXTRACTOR_NAME,
         "rule_version": EXTRACTOR_VERSION.rsplit(":", 1)[-1],
         "deterministic": True,
         "reading": collapsed_text((reading or {}).get("reading")),
         "work_item_id": collapsed_text((card or {}).get("work_item_id"))},
        telling_keys={claim["claim_id"]: answer_telling_ref(
            ref.source_id, (card or {}).get("node_ref"))},
    )
    path = store.write_receipt(root, {
        "source_ref": source_ref,
        "extractor_version": EXTRACTOR_VERSION,
        "extractor": extractor,
        "claims": [claim],
    }, now=now)
    return {
        "claim_id": claim["claim_id"],
        "receipt_path": str(path),
        "reading": collapsed_text((reading or {}).get("reading")),
        "node_ref": collapsed_text((card or {}).get("node_ref")),
        "work_item_id": collapsed_text((card or {}).get("work_item_id")),
        "source_path": source_ref["source_path"],
    }


# --------------------------------------------------------------------------
# 5. The sweep: every promoted answer with a card
# --------------------------------------------------------------------------

#: `temporal_store.promote_conversational_source` writes the message under an
#: H1 that IS the message (truncated). The heading is the file's own furniture
#: and not a second sentence, so it is dropped before the reply is quoted or
#: read for time — otherwise a bounded quotation would carry the person's words
#: twice and a two-sentence reply would read as four.
_PROMOTED_TITLE_RE = re.compile(r"\A\s*#[^\n]*\n")


def reply_words(body: object) -> str:
    """The words the person actually typed, out of a promoted source's body."""
    return collapsed_text(_PROMOTED_TITLE_RE.sub("", str(body or ""), count=1))


def promoted_answers(vault_root: str | Path, *, sources: object = None) -> list[dict]:
    """``[{source_path, session_ref, captured, text}]`` for every promoted
    conversation message, newest path last.

    Reads only what is needed to decide: the frontmatter's ``session_ref`` and
    capture date, and the body. ``sources`` restricts the walk to named paths,
    which is what the per-source re-run of a sweep passes.
    """
    root = Path(str(vault_root))
    wanted = {collapsed_text(s) for s in (sources or ())} or None
    base = root / CONVERSATIONS_DIR
    found: list[dict] = []
    if not base.is_dir():
        return found
    for path in sorted(base.rglob("*.md")):
        relative = path.relative_to(root).as_posix()
        if wanted is not None and relative not in wanted:
            continue
        try:
            metadata, body = split_frontmatter(
                path.read_text(encoding="utf-8", errors="replace"))
        except OSError:
            continue
        if not isinstance(metadata, dict):
            continue
        captured = ""
        for key in _capture_keys():
            if chrono.capture_day(metadata.get(key)) is not None:
                captured = str(metadata.get(key))
                break
        found.append({
            "source_path": relative,
            "session_ref": collapsed_text(metadata.get("session_ref")),
            "captured": captured,
            "text": reply_words(body),
        })
    return found


def _capture_keys() -> tuple[str, ...]:
    """`classifier_claims.CAPTURE_DATE_KEYS`, read from there so the day a
    telling was recorded is found the same way by every reader."""
    import classifier_claims as ccl  # noqa: PLC0415

    return ccl.CAPTURE_DATE_KEYS


def empty_report() -> dict:
    """The shape :func:`place_answers` always returns, zeros included."""
    return {"rule": ANSWERING_A_CARD_PLACES_ITS_MOMENT,
            "extractor_version": EXTRACTOR_VERSION,
            "answers": 0, "placed": 0, "tellings": 0, "filed": [],
            "by_reading": {name: 0 for name in READINGS},
            "refused": {name: 0 for name in REFUSALS},
            # v358: answers to a relation-word card, which carry a word about
            # a person rather than a time about a moment
            # (`relation_words.file_relation_answer`).
            "relation_words": [],
            "errors": []}


def place_answers(vault_root: str | Path, *, sources: object = None,
                  dry_run: bool = False, now: object = None) -> dict:
    """The rule over a whole vault: every promoted answer lands on its card.

    ``dry_run`` reads everything and writes nothing, returning the same report,
    the convention `classifier_claims.migrate_classifier_moments` and
    `era-migrate` already use.

    Walks the promoted answers ONCE against ONE read of the two published files
    — the card an answer names is a fact about the published generation, not
    about the order this walk happens to take — so the run is deterministic
    whatever order the directory yields.
    """
    root = Path(str(vault_root))
    report = empty_report()
    report["dry_run"] = bool(dry_run)
    answers = [row for row in promoted_answers(root, sources=sources)
               if work_item_of_session(row["session_ref"])]
    if not answers:
        return report
    work_items = pub.read_work_items(root) or {}
    projection = pub.read_projection(root) or {}
    for row in answers:
        report["answers"] += 1
        relation = _relation_answer(root, row, work_items=work_items, dry_run=dry_run,
                                    report=report)
        if relation:
            continue
        card, refusal = card_for_answer(root, row["session_ref"],
                                        work_items=work_items, projection=projection)
        if card is None:
            report["refused"][refusal] = report["refused"].get(refusal, 0) + 1
            continue
        if not row["text"]:
            report["refused"][REFUSED_NO_WORDS] += 1
            continue
        reading = answer_reading(row["text"], captured=row["captured"],
                                 question=card["question"]) or telling_reading()
        report["by_reading"][reading["reading"]] += 1
        if reading["reading"] == READING_TELLING:
            report["tellings"] += 1
        else:
            report["placed"] += 1
        if dry_run:
            report["filed"].append({"source_path": row["source_path"],
                                    "node_ref": card["node_ref"],
                                    "work_item_id": card["work_item_id"],
                                    "reading": reading["reading"]})
            continue
        try:
            report["filed"].append(file_answer(
                root, source_path=row["source_path"], card=card,
                reading=reading, text=row["text"], now=now))
        except Exception as exc:  # noqa: BLE001 — one bad answer never stops the rest
            report["errors"].append(
                f"{row['source_path']}: {type(exc).__name__}: {str(exc)[:200]}")
    return report


def _relation_answer(root: Path, row: dict, *, work_items: object, dry_run: bool,
                     report: dict) -> bool:
    """v358: an answer to a relation-word card files the owner's word, not a time.

    `relation_words.file_relation_answer` is the whole rule; this is the seat.
    ``True`` when the answer named a relation-word card — whatever the reply
    said — so the time readings below never read it.
    """
    import relation_words as rw  # noqa: PLC0415

    try:
        filed = rw.file_relation_answer(root, session_ref=row["session_ref"],
                                        text=row["text"], work_items=work_items,
                                        dry_run=dry_run)
    except Exception as exc:  # noqa: BLE001 — one bad answer never stops the rest
        report["errors"].append(
            f"{row['source_path']}: {type(exc).__name__}: {str(exc)[:200]}")
        return True
    if filed is None:
        return False
    report["relation_words"].append({**filed, "source_path": row["source_path"]})
    return True


def describe(report: object) -> list[str]:
    """One human line per fact a run produced, for a CLI to print."""
    row = report if isinstance(report, dict) else {}
    lines = [f"answers with a card: {row.get('answers', 0)}",
             f"placed: {row.get('placed', 0)}",
             f"filed as a telling only: {row.get('tellings', 0)}"]
    for name, count in sorted((row.get("by_reading") or {}).items()):
        if count:
            lines.append(f"  {name}: {count}")
    for name, count in sorted((row.get("refused") or {}).items()):
        if count:
            lines.append(f"  refused {name}: {count}")
    for filed in row.get("relation_words") or ():
        outcome = (f"relation word {filed.get('relation_gender')}"
                   if filed.get("relation_gender") and not filed.get("refused")
                   else f"refused {filed.get('refused')}")
        lines.append(f"  {filed.get('subject_ref')}: {outcome}")
    for problem in row.get("errors") or ():
        lines.append(f"  error {problem}")
    return lines
