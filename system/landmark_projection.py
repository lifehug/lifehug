#!/usr/bin/env python3
"""`state/landmarks.json` is a DRAWING. The whiteboard is glass now.

Owner amendment 1 to the audited final timeline build plan (2026-08-26),
wave B item B3. Until this module existed, a landmark entry was written
straight into `state/landmarks.json` and that file WAS the truth: a date the
person stated lived nowhere else, its provenance was whatever the entry
happened to carry, and "why does the timeline say 1978?" had no answer below
the file itself. v219-v223 built the substrate that can answer it — claims
with sources, receipts that rebuild the active set with no model call,
corrections that retire without deleting. This module performs the FLIP:

    every landmark entry becomes a promoted vault source + temporal claims,
    and `state/landmarks.json` becomes a projection redrawn from them.

Three properties are the whole point, and none may be weakened.

**No dual-truth window.** The converter, the write-path swap and the guard
land in one semantic commit. There is never a moment where an entry is
authoritative in the file AND in the substrate, because the moment the
substrate holds it the file is derived. `timeline.save_landmark` keeps its
signature and its meaning; what changed is that it now records evidence and
redraws, instead of editing the drawing directly.

**The flip is invisible.** For a vault with existing entries, convert -> fold
-> project reproduces the pre-flip file. The ladder, `landmark_rows`,
`anchors_from_landmarks` and every other reader keep reading exactly what they
read before, through `timeline.load_landmarks`, and never learn that anything
moved. `tests/test_landmark_projection.py` pins this against a founder-shaped
fixture with every domain populated.

**Reconciliation moves to READ time.** This is the deep change, and it is why
the projection is a fold rather than a lookup. Before the flip,
`merge_landmark_entry` reconciled two dates when the second one was FILED and
stored the winner plus its alternates. Now every telling is its own claim, and
`chronology.reconcile` runs over the live active set every time the file is
drawn. The stored result is identical — `reconcile` is deterministic and
idempotent over the same claims — but a retraction can now change the answer,
which a stored winner could never do.

WHAT LIVES WHERE, precisely, because this is the question a reader of this
module will actually have:

* `sources/landmarks/entry-<24 hex>.md` — one promoted vault source per FILED
  RECORD (not per entry: an entry that was answered over four conversations
  has four sources). It carries the record exactly as it was filed, which
  makes it evidence. Its frontmatter carries the grouping key
  (`landmark_domain`, `landmark_entry_key`) and its filing order
  (`filed_ordinal`), because those are facts about the filing and not
  interpretations of it.
* `state/temporal_claims/receipts/...` — one receipt per source, listing the
  temporal claims read out of that record by a DETERMINISTIC RULE. No model
  call happens here, ever; the extractor version says so
  (`legacy-entry-import/rule:1`, `landmark-record/rule:1`).
* `state/landmarks.json` — the drawing. Written by exactly one function
  (`timeline.redraw_landmarks`) and by nothing else in the package, which
  `tests/test_landmark_projection.py::test_no_other_writer_of_landmarks_json`
  enforces against the AST of every module.

THE SKELETON IS EVIDENCE, THE DATES ARE CLAIMS. A landmark entry is not
purely temporal — `residences` carries a city and an address, `schools` a name
and grades, `family` a relation. The v220 `TemporalClaim` schema is frozen and
deliberately has no slot for any of that, so those fields ride on the promoted
SOURCE, where they belong: they are what the person said, recorded immutably.
The projector reads the skeleton from the sources and the dates from the
claims, and it reads dates from a source NEVER — see :func:`skeleton_of`,
which strips them, and the note on its docstring about why that strip is
load-bearing rather than tidy.

WHY THE ENTRY'S EXISTENCE IS ITSELF A CLAIM. Every filed record also emits one
`identity` claim. It carries no date and asserts only "this entry was named",
and it is what makes a correction able to remove an entry: retract the
identity claim and the group has no active anchor, so the projection drops it.
Without it, retracting an entry's only date would leave a dateless ghost in
the drawing forever.

The wave-D calculated timeline (`system/temporal_projection.py`) is a
different projection over the same substrate and is deliberately not touched
here. This module draws the LADDER's file, at the ladder's own shape.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

SYSTEM_DIR = Path(__file__).resolve().parent
if str(SYSTEM_DIR) not in sys.path:
    sys.path.insert(0, str(SYSTEM_DIR))

import chronology as chrono  # noqa: E402
import event_identity as ei  # noqa: E402
import landmarks_interaction  # noqa: E402
import temporal_store as store  # noqa: E402
from temporal_claims import (  # noqa: E402
    ATOMIC_LANDMARK_IDENTITY_KINDS,
    CLAIM_BASIS_BY_DATE_BASIS,
    LANDMARK_LEGACY_EXTRACTOR,
    LANDMARK_RECORD_EXTRACTOR,
    SCHEMA_VERSION,
    SourceRef,
    TemporalContractError,
    bounded_quote,
    collapsed_text,
    normalized_timestamp,
    split_subject_enumeration,
    validate_extraction_receipt,
    validate_temporal_claim,
)
from vault_paths import atomic_create_vault_bytes  # noqa: E402

# --------------------------------------------------------------------------
# Layout and vocabulary
# --------------------------------------------------------------------------

#: Promoted landmark records. Under ``sources/`` and not ``state/`` for the
#: same reason amendment 2's conversational sources are: state is rebuildable
#: and evidence never is. Registered in ``vault_contract.json``.
LANDMARK_SOURCES_DIR = "sources/landmarks"

#: The ``type`` every promoted landmark record declares in its frontmatter.
LANDMARK_SOURCE_TYPE = "landmark_entry"

#: The projected file's own schema version. Deliberately equal to
#: ``timeline.LANDMARKS_SCHEMA_VERSION`` — the drawing's shape did not change
#: when what draws it did, and a reader that checked the version must not see
#: a number it does not know.
LANDMARKS_SCHEMA_VERSION = 1

#: The one-time converter's extractor version. ``rule:`` and no ``model:``,
#: because :func:`entry_claims` is a deterministic function of an entry and
#: calls nothing. Bump the rule version to re-import under a new reading; the
#: old receipts stay on disk beside the new ones, which is the substrate's
#: whole promise.
LEGACY_EXTRACTOR = LANDMARK_LEGACY_EXTRACTOR

#: The live write path's extractor version. The SAME deterministic rule, named
#: differently so the fold and a debugging human can tell an imported record
#: from one filed after the flip. Both run :func:`entry_claims`.
LIVE_EXTRACTOR = LANDMARK_RECORD_EXTRACTOR

#: A span's two bounds, as event kinds. Both are in
#: ``temporal_claims.LANDMARK_DATE_SEMANTICS``; a span is stored as two dated
#: claims rather than one range claim because the two bounds carry their own
#: basis, anchors and provenance and can exist independently — a job whose
#: start year is stated and whose end is unknown is one claim, not half of one.
SPAN_START_EVENT_KIND = "started"
SPAN_END_EVENT_KIND = "ended"

#: E-L2a (design §3.2, M1/M2). THE LANDMARK DOMAIN IS THE EPISODE'S KIND.
#:
#: A residence, a job, a schooling and a stint of service are *participation
#: episodes*: stretches the person was somewhere, doing something. The two
#: claims :func:`entry_claims` files for one of them say ``started`` and
#: ``ended`` and nothing else, so below the promoted source NOTHING could tell
#: a move-in from a job start — and the fold drew two loose point nodes per
#: stay, neither of which is a stretch anything can be inside. That is why the
#: retired ``place_co_location`` pass could never fire: it wanted an episode of
#: kind ``residence`` and no producer in this package ever emitted one.
#:
#: The fix is READ-SIDE and takes no migration, which is the whole reason it is
#: spelled as a table over the DOMAIN rather than as new event kinds on the
#: claim. The claims on disk are immutable and stay exactly as they are; the
#: promoted landmark source already records which domain it was filed under
#: (``landmark_domain`` in its frontmatter, published by
#: :func:`load_landmark_sources`), so every vault written since the flip —
#: including every legacy-imported one — folds into participation episodes on
#: the next read with nothing rewritten and nothing re-harvested.
#:
#: The four kinds are `identity_resolution.REPEATABLE_EVENT_KINDS`' own words,
#: which is what makes a second stay at one place a second episode
#: (:func:`identity_resolution.derive_episode_ref` refuses a repeatable kind
#: with no discriminator) rather than a silent merge.
PARTICIPATION_EPISODE_KINDS = {
    "residences": "residence",
    "work": "job",
    "schools": "school",
    "military": "military",
}

PARTICIPATION_EPISODE_RULE_TEXT = (
    "A landmark entry of a span domain IS a participation episode: its "
    "promoted telling's own domain names the episode's kind (residences -> "
    "residence, work -> job, schools -> school, military -> military), its "
    "identity mention names the subject, and its stated start is the "
    "discriminator that keeps a second stay at one place from merging into "
    "the first. An entry with no stated start is discriminated by its "
    "promoted source id instead, folds unplaced, and is never a container - "
    "no span, no window. The claims are never rewritten: the domain rides on "
    "the promoted source, so an existing vault folds into episodes with no "
    "migration."
)


#: WHY A FILED RECORD DRAWS NOTHING ON THE TIMELINE (ADR 0037's amendment).
#: A CLOSED vocabulary, because "this is not a landmark" is a typed answer and
#: not a shrug. A landmark record has one job — improve the spine — and a
#: record that cannot improve it must still be FILED (it is what the person
#: said) and must never become a node the fold asks a question about.
NONE_TERMINAL = "none_terminal"
SKIPPED_ANSWER = "skipped_answer"
UNNAMED_ORGANIZATION = "unnamed_organization"
#: v339 (lifehug#394). A ``birth`` record that is somebody ELSE's birth. See
#: :func:`birth_landmark_not_owner` for the rule and the incident.
BIRTH_LANDMARK_NOT_OWNER = "birth_landmark_not_owner"
NOT_A_LANDMARK_REASONS = (NONE_TERMINAL, SKIPPED_ANSWER, UNNAMED_ORGANIZATION,
                          BIRTH_LANDMARK_NOT_OWNER)

# --------------------------------------------------------------------------
# v339: the `birth` domain is the OWNER's own birth and nothing else
# --------------------------------------------------------------------------
#
# THE INCIDENT (owner's vault, staging, 2026-09-23 20:34 UTC, commit
# b6982658 "Landmark: birth"). The owner pasted two of his grandfathers'
# vital records into a Timeline card conversation on 2026-09-21 — the
# genealogy-app shape, `Name • 8 Sources / James Edwin Taylor Sr`,
# `Birth • 6 Sources / 17 October 1930` — and a landmark-record filing
# (`maintenance:reflect:…:landmark-record`) turned both men's births into
# `birth` landmark records: `landmark:entry-35a59936fc440531af66b360`
# (1930-10-17, basis `anchor`) and `landmark:entry-9c618f4b4d540072b4ec2103`
# (1929-09-30, basis `anchor`, carrying the raw grains `day: "30"`,
# `month: "September"`, `year: "1929"`).
#
# `birth` has NO identity rung (`questions.yaml`: `birth.identity_kind:` is
# empty, `birth.collection: singleton`), so every one of those records keyed
# on the same empty `entry_key` as the owner's own stated 1981-07-11 and
# folded into ONE entry. Two things followed, and this module is where both
# of them happened:
#
#   1. `landmarks_interaction.merge_landmark_entry`'s `{**prior, **incoming}`
#      let the later record's raw grains OVERWRITE the owner's, so
#      `state/landmarks.json` → `/domains/birth[0]` read
#      `30 September 1929` beside a `date` of `1981-07-11`.
#   2. `_attach_dates` reconciled all three date claims onto the owner's
#      entry, so 1929-09-30 and 1930-10-17 became the owner's own
#      `date_alternates` — and, because `entry_subject_mention` mints
#      :data:`OWNER_BIRTH_MENTION` for this domain UNCONDITIONALLY, the fold
#      filed three `self` birth claims and minted the Mirror contradiction
#      *"Two dates are claimed for your birth — 11 July 1981 and 30
#      September 1929. Which is right?"*
#
# THE RULE. A `birth` landmark record is the owner's own birth. A record that
# names somebody else, or that is dated a human lifetime away from the birth
# year the owner STATED, is a relative's birth — it belongs to `family`,
# which has a `who` rung for exactly this — and it never touches the owner's
# entry. Refused at FILING so nothing new lands (`timeline.save_landmark`),
# skipped at DRAW so what already landed heals, which is the same two-seat
# shape `UNNAMED_ORGANIZATION` and
# `landmark_recorder.refuse_unnamed_tenures` already have.

#: The one domain whose entry is the OWNER's own, has no subject rung, and
#: therefore cannot tell two people's births apart by identity.
OWNER_BIRTH_DOMAIN = "birth"

# --------------------------------------------------------------------------
# v341: a birth record's OWN domain words name nobody
# --------------------------------------------------------------------------
#
# THE SECOND INCIDENT (2026-09-23, the hosted platform's CI against the pinned
# v339/v340 package). v339 read every subject field of a `birth` record and
# treated any body that was not a placeholder, not the literal domain word
# `"birth"`, and not an owner spelling as the name of a THIRD PARTY. But the
# platform — and every older package seat — files the owner's own birth with
# the domain's natural DISPLAY LABEL: `{"domain": "birth", "label": "Born",
# "date": {"best": "1979"}}`. "Born" is not a person. v339 read it as one, so
# `birth_landmark_not_owner` refused the owner's own birthday and
# `timeline.py`'s draw seat dropped an unnamed self-birth from the drawing
# without a word. Four platform tests said so on the pin
# (`test_landmark_record.py::test_a_birth_date_files_as_an_edtf_date_and_the_
# timeline_reads_it_back`, two in `test_landmark_flip_invisibility.py`, and
# `test_landmark_flip_containment.py::test_a_parked_entry_keeps_its_exact_
# value_in_the_drawing`, which asserts the literal `['Born']` survives).
#
# THE RULE. A `birth` record whose subject-field text is the birth domain's OWN
# vocabulary names NOBODY — it says which domain this is, not whose birth it
# is — so it can never be a third party. :data:`BIRTH_DOMAIN_WORDS` is the ONE
# definition, read by BOTH seats that ask the question: this module's
# :func:`third_party_birth_subject` (the landmark) and
# `temporal_timeline._birth_names_only_the_owner` (the projection's age
# anchor), which spoke of "the legacy birth domain word" with a list of its own
# until this release. Compared WHOLE and casefolded after ``collapsed_text``,
# never as a substring, so a real name that merely CONTAINS one of these words
# — "Bornstein", "Mary Born" — is still a name and still refuses.

#: Every way a `birth` record names its own domain instead of a person. The
#: display label (``Born``), the rung's own words (``birthday``, ``date of
#: birth``), the owner-possessive spellings the hosts write (``my birth``,
#: ``your birth``, ``owner's birth``) and the sentence fragment a harvester
#: leaves behind (``I was born``). ``birth`` itself — the legacy mention
#: `identity_resolution.LEGACY_OWNER_BIRTH_MENTION`, which
#: :func:`entry_subject_mention` minted before design §3.1 — is a member, so
#: this set SUPERSEDES the bare domain-word comparison v339 shipped rather
#: than sitting beside it.
BIRTH_DOMAIN_WORDS = frozenset({
    OWNER_BIRTH_DOMAIN,
    "born",
    "birthday",
    "birthdate",
    "birth date",
    "birth day",
    "date of birth",
    "my birth",
    "my birthday",
    "my birthdate",
    "my birth date",
    "my date of birth",
    "my own birth",
    "your birth",
    "your birthday",
    "your birthdate",
    "your birth date",
    "your date of birth",
    "owner's birth",
    "owner's birthday",
    "own birth",
    "the birth",
    "was born",
    "i was born",
    "when i was born",
    "date of my birth",
})

#: The typographic apostrophes a paste carries, folded to the plain one before
#: the WHOLE-text comparison — ``owner’s birth`` is ``owner's birth``, and a
#: curly quote is not a different word.
_BIRTH_WORD_APOSTROPHES = str.maketrans({"’": "'", "ʼ": "'", "`": "'"})


def is_birth_domain_word(text: object) -> bool:
    """Is this text the `birth` domain's own vocabulary
    (:data:`BIRTH_DOMAIN_WORDS`), naming nobody?

    WHOLE-text, casefolded, whitespace-collapsed. Never a substring test: the
    whole reason this is a set membership rather than a regex is that "Born"
    names nobody while "Mary Born" and "Bornstein" name somebody.
    """
    body = collapsed_text(text).casefold().translate(_BIRTH_WORD_APOSTROPHES)
    return bool(body) and body in BIRTH_DOMAIN_WORDS

#: How far a ``birth`` record's year may sit from the year the owner STATED
#: and still be read as a correction of it rather than a different person's
#: birth. Fifteen years is under the shortest plausible generation gap and
#: well over any correction a person makes to their own birthday — the real
#: records were 52 and 51 years out. A record inside the bound is merged as
#: it always was; the bound only ever decides whether a record is REFUSED,
#: never which of two dates wins (that is `chronology.reconcile`'s).
OWNER_BIRTH_YEAR_TOLERANCE = 15

#: The genealogy-app / vital-record ``Name`` header, whose value is on the
#: NEXT line: ``Name • 8 Sources\nJames Edwin Taylor Sr``. This is the exact
#: shape the owner pasted, and a `birth` record carrying it is quoting
#: somebody's record rather than stating the owner's own birthday.
BIRTH_NAME_LINE_RE = re.compile(
    r"(?im)^[ \t]*name\b[^\n]*\n[ \t]*(?P<name>[^\n]{2,120}?)[ \t]*$")

#: Where a `birth` record could be carrying a person. ``label``/``name`` are
#: `landmarks_interaction.IDENTITY_FIELDS`; ``subject`` is the recorder's own
#: field; ``who`` is `family`'s identity rung, which a mis-domained record
#: routinely brings with it.
BIRTH_SUBJECT_FIELDS = ("label", "name", "subject", "who")

#: Free-text fields a pasted record's prose can ride in on.
BIRTH_TEXT_FIELDS = ("label", "name", "subject", "who", "what", "note",
                     "household", "place")


def _owner_spellings(owner_names: object) -> frozenset[str]:
    return frozenset(
        collapsed_text(name).casefold() for name in (owner_names or ())
        if collapsed_text(name))


def _is_owner_spelling(text: object, owner_names: object) -> bool:
    """Is this text the owner, and only the owner?

    `temporal_timeline.is_owner_reference_only` is the one definition of
    "this says nothing but *me*" ("I", "myself", "self"); the vault's own
    owner spellings come from `temporal_publication.owner_identity_inputs`
    and are compared WHOLE, exactly as `timeline-rules:8` requires.
    """
    from temporal_timeline import is_owner_reference_only  # noqa: PLC0415

    body = collapsed_text(text)
    if not body:
        return True
    if is_owner_reference_only(body):
        return True
    return body.casefold() in _owner_spellings(owner_names)


def third_party_birth_subject(record: object, *, owner_names: object = ()) -> str | None:
    """The OTHER person a ``birth`` record names, or ``None``.

    Read in two passes, structural both times:

    * the record's own subject fields (:data:`BIRTH_SUBJECT_FIELDS`) — a
      `birth` entry names nobody by construction, so a name in one of them
      is a name that does not belong to this domain unless it is the owner's
      own spelling, or (v341) the domain's OWN vocabulary
      (:func:`is_birth_domain_word`), which is the display label the hosts
      file the owner's own birthday under and names nobody at all;
    * the pasted vital record's ``Name`` header
      (:data:`BIRTH_NAME_LINE_RE`) in any free-text field, which is how the
      real records arrived. It requires a NEWLINE — the header is on one line
      and the man on the next — so a one-word ``label`` can never reach it.

    A bare RELATION word ("my grandfather") names a third party without
    naming a person, so it is reported by :func:`birth_landmark_not_owner`
    and deliberately NOT returned here: there is no ``who`` to file a
    `family` entry under, and an unnamed `family` entry is the
    :data:`UNNAMED_ORGANIZATION` hazard in a second domain.
    """
    if not isinstance(record, dict):
        return None
    for field in BIRTH_SUBJECT_FIELDS:
        text = record.get(field)
        if not isinstance(text, str):
            continue
        body = collapsed_text(text)
        if not body or body.casefold() in landmarks_interaction.PLACEHOLDER_LABELS:
            continue
        if is_birth_domain_word(body):
            continue
        if _is_owner_spelling(body, owner_names):
            continue
        return body[:120]
    for field in BIRTH_TEXT_FIELDS:
        text = record.get(field)
        if not isinstance(text, str) or "\n" not in text:
            continue
        match = BIRTH_NAME_LINE_RE.search(text)
        if match is None:
            continue
        body = collapsed_text(match.group("name"))
        if body and not _is_owner_spelling(body, owner_names):
            return body[:120]
    return None


def _names_a_third_party_relation(record: object) -> bool:
    """Does this ``birth`` record say whose birth it is, and say *not mine*?

    `cross_dating.THIRD_PARTY_RELATION_WORDS` is the ONE vocabulary for
    "this names somebody other than the owner" and there is no second list
    here (`axis_membership` partitions the same tuple).
    """
    if not isinstance(record, dict):
        return False
    import cross_dating  # noqa: PLC0415

    for field in BIRTH_TEXT_FIELDS:
        text = record.get(field)
        if isinstance(text, str) and cross_dating.THIRD_PARTY_RELATION_RE.search(text):
            return True
    return False


def owner_stated_birth(sources: object) -> dict | None:
    """The owner's own STATED birth claim, read off the filed records.

    The first ``birth`` record in FILING ORDER whose date carries
    ``basis: "stated"`` — a date the owner typed or said, which is the only
    kind of birth claim that can speak for whose entry this is. An
    ``anchor``, ``document`` or ``age`` basis is a date somebody worked out
    or copied, and the incident is precisely a pair of copied ones.

    ``None`` when no birth has been stated, which is what disarms the year
    bound: with nothing to be far FROM, only a named subject refuses.
    """
    for source in sources or ():
        if not isinstance(source, dict):
            continue
        if collapsed_text(source.get("domain")) != OWNER_BIRTH_DOMAIN:
            continue
        record = source.get("record")
        date = record.get("date") if isinstance(record, dict) else None
        if isinstance(date, dict) and collapsed_text(date.get("basis")) == "stated":
            return date
    return None


def birth_landmark_not_owner(record: object, *, owner_birth: object = None,
                             owner_names: object = ()) -> str | None:
    """:data:`BIRTH_LANDMARK_NOT_OWNER` when this ``birth`` record is not the
    owner's, else ``None``.

    Two independent reasons, and either is enough:

    (a) **it names another person.** `birth` names nobody
        (`landmarks_interaction.identity_rung` → ``None`` for this domain),
        so a subject field or a pasted ``Name`` header that is not an owner
        spelling is a person this domain has no slot for
        (:func:`third_party_birth_subject`); a bare relation word is the
        same statement without a name
        (:func:`_names_a_third_party_relation`).
    (b) **its year is a lifetime from the owner's STATED birth year.**
        :data:`OWNER_BIRTH_YEAR_TOLERANCE`, and only when a stated birth
        exists to measure against. This is the half that caught the real
        records, which carried no name at all by the time they were filed:
        ``{"date": {"best": "1929-09-30", "basis": "anchor"}, "day": "30",
        "month": "September", "year": "1929"}`` against a stated 1981.

    The record that SUPPLIED the stated birth is never refused by (b) — it
    is zero years from itself — so an ordinary correction of the owner's own
    birthday ("actually I was born on the 12th") is untouched.
    """
    if not isinstance(record, dict):
        return None
    if record.get("none") is True or record.get("skipped") is True:
        return None
    if third_party_birth_subject(record, owner_names=owner_names) \
            or _names_a_third_party_relation(record):
        return BIRTH_LANDMARK_NOT_OWNER
    stated_year = chrono.year_of(owner_birth) if owner_birth else None
    record_year = chrono.year_of(record.get("date"))
    if stated_year is not None and record_year is not None \
            and abs(record_year - stated_year) >= OWNER_BIRTH_YEAR_TOLERANCE:
        return BIRTH_LANDMARK_NOT_OWNER
    return None


def relative_birth_record(record: object, subject: str) -> dict | None:
    """The same birth, re-domained to ``family`` under the person it names.

    The ROUTE half of the rule: a grandfather's birth is a real landmark and
    a real fact about the owner's life — `family` is the domain that holds
    one, with `who` for the person and the same ``birth`` date semantics —
    so a refused `birth` record is re-filed there rather than thrown away.
    Built through `landmarks_interaction.validate_landmark`, so the rungs
    `family` does not declare drop out instead of riding along (the raw
    ``day``/``month``/``year`` grains belong to `birth`'s ladder, not this
    one). ``None`` when nothing survives validation.
    """
    who = collapsed_text(subject)
    if not who:
        return None
    rerouted: dict = {"domain": "family", "who": who[:120], "label": who[:120]}
    date = record.get("date") if isinstance(record, dict) else None
    if isinstance(date, dict):
        rerouted["date"] = date
    relation = record.get("relation") if isinstance(record, dict) else None
    if isinstance(relation, str) and relation.strip():
        rerouted["relation"] = relation.strip()
    return landmarks_interaction.validate_landmark(rerouted)


def not_a_landmark(domain: object, record: object, *, owner_birth: object = None,
                   owner_names: object = ()) -> str | None:
    """Why this filed record must never become a timeline node, or ``None``.

    ONE definition, read twice: the recorder refuses to file an
    :data:`UNNAMED_ORGANIZATION` at all, and the fold skips every reason here
    at DRAW time, so a vault that already holds one heals on its next redraw
    with no migration. The entry itself is untouched — it stays in
    ``state/landmarks.json`` and its domain goes on reading complete, which is
    the whole point of a ``none``: the person answered.

    The three reasons, and the live records behind each (lifehug#365, seen on
    a real vault at v316):

    * :data:`NONE_TERMINAL` — ``{"domain": "military", "none": true}``, the
      ladder's own "that never happened". It projected as an undated
      ``military`` episode with a card and no question. A none is a complete
      answer to a domain, not a stretch of somebody's life.
    * :data:`SKIPPED_ANSWER` — a decline. It was never an answer about time.
    * :data:`UNNAMED_ORGANIZATION` — ``{"domain": "work", "what": "SEO
      work"}``, filed without a label. A tenure is a tenure AT an
      organization, and the question set says which domains those are
      (``identity_kind: organization`` — ``work`` and ``schools``); with no
      name, :func:`entry_subject_mention` falls back to the DOMAIN WORD and
      the person reads a card asking *"When were you at work?"*. Derived from
      the question set rather than listed here, so a tenth domain declaring
      itself an organization is covered by the same sentence.

    ``residences`` is deliberately outside the unnamed rule: a place stub that
    duplicates a dated stay is an IDENTITY problem (lifehug#365 item 3), and
    attaching it to the stay it repeats is a different fix from refusing it.

    v339 adds the fourth reason, :data:`BIRTH_LANDMARK_NOT_OWNER`, and the
    two keywords it needs: ``owner_birth`` is the claim
    :func:`owner_stated_birth` read off this vault's records and
    ``owner_names`` the spellings `temporal_publication.owner_identity_inputs`
    hands over. Both default to "unknown", and an unknown owner never refuses
    a record on the year bound — a caller with no vault context gets exactly
    the three pre-v339 reasons.
    """
    if not isinstance(record, dict):
        return None
    if record.get("skipped") is True:
        return SKIPPED_ANSWER
    if record.get("none") is True:
        return NONE_TERMINAL
    if collapsed_text(domain) == OWNER_BIRTH_DOMAIN:
        return birth_landmark_not_owner(record, owner_birth=owner_birth,
                                        owner_names=owner_names)
    row = domain_row_or_none(domain)
    if not isinstance(row, dict) or row.get("identity_kind") != "organization":
        return None
    if landmarks_interaction.identity_named(record, row) is None:
        return UNNAMED_ORGANIZATION
    return None


#: The event kind for an entry's own ``date`` when its domain dates SEVERAL
#: events. ``partnerships`` declares ``first_met|dating_started|married`` and
#: the pre-flip ladder stored ONE date without saying which of the three it
#: was, so naming any one of them here would fabricate a distinction the
#: person never drew. ``transition`` is the seeded semantic for exactly that:
#: an event transition whose kind is not yet settled. Wave C splits these into
#: per-event claims, which supersede rather than rewrite.
UNDISAMBIGUATED_EVENT_KIND = "transition"

#: The subject a ``birth`` landmark entry names (design §3.1). It is the
#: owner's own handle — ``temporal_timeline.DEFAULT_OWNER_REF`` — spelled here
#: as the literal the substrate stores, because this module mints MENTIONS and
#: a mention is text, not a ref. The fold resolves it to the owner like any
#: other mention; it simply never needs a roster to do it.
OWNER_BIRTH_MENTION = "self"

#: The entry keys the projector must never read from a promoted source: they
#: are the temporal assertion, and the temporal assertion lives in the claims.
#: See :func:`skeleton_of`.
TEMPORAL_ENTRY_KEYS = (
    "date",
    "span",
    landmarks_interaction.DATE_ALTERNATES_KEY,
    landmarks_interaction.SPAN_ALTERNATES_KEY,
)

#: Frontmatter keys this module adds to the shared source shape.
LANDMARK_FRONTMATTER_KEYS = (
    "landmark_domain",
    "landmark_entry_key",
    "filed_ordinal",
)


class LandmarkProjectionError(TemporalContractError):
    """A landmark record or promoted source that cannot be trusted."""


ERROR_CODES = (
    "landmark_domain_required",
    "landmark_record_empty",
    "landmark_source_malformed",
    "landmark_ordinal_required",
)


# --------------------------------------------------------------------------
# Pure derivation: an entry, read by a deterministic rule
# --------------------------------------------------------------------------


def canonical_json(payload: object) -> str:
    """One serialization for anything this module digests or stores."""
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _root(vault_root: str | Path) -> Path:
    """The vault root as an absolute directory. `temporal_store`'s rule, reused."""
    root = Path(vault_root).expanduser()
    if not root.is_absolute():
        root = Path.cwd() / root
    if not root.is_dir():
        raise LandmarkProjectionError(
            "landmark_source_malformed", f"vault root is not a directory: {root}"
        )
    return root


def skeleton_of(entry: object) -> dict:
    """The entry WITHOUT its temporal assertion — what the projector may read.

    Load-bearing rather than tidy. A promoted source carries the record
    exactly as filed, dates included, because evidence that edits itself is
    not evidence. But the projector must derive every date from the CLAIMS, or
    the flip would have produced two answers to "when" — one in the source and
    one in the substrate — which is the dual truth this whole change exists to
    end. Stripping here is how "the projector never reads a date from a source"
    becomes a property of the code instead of a promise in a comment.
    """
    if not isinstance(entry, dict):
        return {}
    return {key: value for key, value in entry.items() if key not in TEMPORAL_ENTRY_KEYS}


def domain_row_or_none(domain: object) -> dict | None:
    """The question set's row for ``domain``, or ``None`` when it declares none.

    Degrade, never refuse: `timeline.save_landmark` has always filed a domain
    the question set does not declare, keyed on its identity fields alone, and
    the flip does not get to start rejecting vaults that already hold one.
    """
    try:
        return landmarks_interaction.domain_row(str(domain or ""))
    except landmarks_interaction.LandmarkInteractionError:
        return None


def date_event_kind(row: object) -> str:
    """Which event an entry's own ``date`` field dates.

    One declared semantic -> that one (``children`` -> ``birth``, ``losses``
    -> ``death``). Several -> :data:`UNDISAMBIGUATED_EVENT_KIND`, because the
    legacy ladder stored one date for three distinct events and guessing which
    is the false precision the plan forbids. A domain the question set does
    not declare, or one whose semantic is ``span``, also lands on the
    undisambiguated kind: a bare ``date`` on a span domain is a point somebody
    filed against a stretch, and it is not the stretch's start by assumption.
    """
    semantics = landmarks_interaction.date_semantics(row) if isinstance(row, dict) else ()
    if len(semantics) == 1 and semantics[0] != "span":
        return semantics[0]
    return UNDISAMBIGUATED_EVENT_KIND


# --------------------------------------------------------------------------
# Owner relevance — a stated relationship AND an owner-relevant occurrence
# --------------------------------------------------------------------------

#: WHICH landmark domains make somebody ELSE's occurrence part of the owner's
#: life, and how (eras design §2.5). It is deliberately a table of FOUR rows,
#: not a rule over the nine domains: `residences`, `schools`, `work`,
#: `military` and `birth` are the owner's own life, so their entries never
#: reach this question, and no other domain enumerates a second person.
#:
#: The relation is the DESIGN's, not an inference: a partnership landmark is
#: something the owner was in (``participated``); a child's birth, a family
#: member's birth and a loss are things that happened to somebody else and that
#: the owner lived through (``lived_effect``).
OWNER_RELEVANCE_BY_DOMAIN = {
    "children": "lived_effect",
    "losses": "lived_effect",
    "family": "lived_effect",
    "partnerships": "participated",
}


def entry_supported_event_kinds(domain: object) -> tuple[str, ...]:
    """The event kinds ONE entry of ``domain`` is evidence for.

    This is the narrow half of §2.5, and the narrowness is the point. A
    ``children`` entry says a child was born and says nothing whatsoever about
    that child's graduation, their move, or the year they changed jobs — so the
    entry supports exactly the event kinds its own ``date_semantics`` mints,
    read through :func:`date_event_kind` and the two span bounds, and nothing
    else. *The relationship alone does not pull the relative's other dated
    events onto the axis.*
    """
    row = domain_row_or_none(domain)
    if row is None:
        return ()
    # The domain's OWN declared semantics, plus whatever `date_event_kind`
    # collapses them to. Both spellings are real on disk: a legacy
    # `partnerships` entry's single `date` field lands at `transition` (three
    # declared semantics, none of them guessable), while the recorder and the
    # listener emit `married` / `first_met` / `dating_started` directly. One
    # entry is evidence for both readings of the same fact and for nothing
    # wider than that.
    kinds = {date_event_kind(row)}
    kinds.update(landmarks_interaction.date_semantics(row))
    kinds.discard("span")
    if not landmarks_interaction.dates_each_entry(row):
        kinds.update((SPAN_START_EVENT_KIND, SPAN_END_EVENT_KIND))
    return tuple(sorted(kind for kind in kinds if kind))


def owner_relevance_for(domain: object, event_kind: object) -> str | None:
    """How this entry makes THIS occurrence the owner's, or ``None``.

    ``None`` is a real answer and the commonest one: it means the entry is not
    evidence that this occurrence belongs on the owner's axis, and the caller
    is then required to say ``contextual_only`` rather than quietly placing the
    row anyway. A domain the question set does not declare also returns
    ``None`` — an undeclared domain has no stated relationship semantics, and
    inventing one is the guess this whole phase exists to stop.
    """
    name = collapsed_text(domain)
    relation = OWNER_RELEVANCE_BY_DOMAIN.get(name)
    if relation is None:
        return None
    kind = collapsed_text(event_kind)
    return relation if kind and kind in entry_supported_event_kinds(name) else None


def entry_subject_mention(entry: object, row: object, domain: object) -> str:
    """The raw mention a claim about this entry names as its subject.

    The entry's own identity as the writer spelled it
    (`landmarks_interaction.identity_named` — label, then name, then the
    domain's identity rung), falling back to the DOMAIN word for an entry that
    names no subject. The substrate requires a non-empty mention on every claim
    and is right to — a claim about nobody is not a claim — so the fallback is
    named rather than left to an empty string.

    ``birth`` is the ONE domain whose subject is the person themselves, and it
    says so (design §3.1): the mention is :data:`OWNER_BIRTH_MENTION`,
    unconditionally, because a birth entry's ladder is three date grains and
    whatever else the row happens to carry, the birthday being filed is the
    owner's. Before this rule the fallback minted the domain word ``"birth"``,
    which read as a *person named "birth"* — and the moment a child's birth
    was filed the fold could no longer tell which of the two births was the
    owner's, so every age claim lost its anchor. Legacy receipts carrying that
    spelling are still read: ``identity_resolution.is_owner_birth_domain_word``
    maps them back to the owner at fold time, so no re-harvest is required and
    the two spellings group as one node.
    """
    if collapsed_text(domain) == "birth":
        return OWNER_BIRTH_MENTION
    named = landmarks_interaction.identity_named(entry, row) if isinstance(row, dict) else None
    if not named and isinstance(entry, dict):
        for field in landmarks_interaction.IDENTITY_FIELDS:
            text = entry.get(field)
            if isinstance(text, str) and text.strip():
                named = text.strip()
                break
    mention = collapsed_text(named) or collapsed_text(domain)
    return mention[:200]


def _evidence_for(entry: dict, domain: str, field_label: str) -> dict:
    """The bounded, HONEST quotation behind a converted claim.

    A legacy entry is not a sentence somebody said — the words that produced it
    were never kept, which is precisely the thinness this import is honest
    about. So the evidence quotes the RECORD, in its canonical form, and says
    which field of it the claim was read from. It is a real, checkable
    quotation of the real source document; it is simply a quotation of a filed
    record rather than of a spoken sentence, and the receipt's extractor
    version says so out loud.
    """
    quoted = entry.get(field_label) if field_label in entry else entry
    return {
        "quote": bounded_quote(f"{domain}.{field_label} = {canonical_json(quoted)}"),
        "locator": f"{domain}/{field_label}",
    }


def _date_claim(
    record: object,
    *,
    entry: dict,
    domain: str,
    mention: str,
    event_kind: str,
    field_label: str,
    source_ref: object,
    extractor_version: str,
    now: object,
    subject_annotation: dict,
) -> dict | None:
    """One dated claim read out of one stored `chronology` record, or ``None``.

    The record's own ``basis`` decides the claim's basis through
    :data:`temporal_claims.CLAIM_BASIS_BY_DATE_BASIS` — the v222 carriage
    landing where it was always going. Nothing is upgraded: a date the system
    calculated from an age arrives as ``calculated`` and stays there.
    """
    parsed = chrono.from_dict(record)
    if parsed is None:
        return None
    basis = CLAIM_BASIS_BY_DATE_BASIS.get(parsed.basis, "inferred")
    return validate_temporal_claim(
        {
            "source_ref": source_ref,
            "source_kind": "import",
            "claim_type": "date",
            "subject_mention": mention,
            **subject_annotation,
            "event_kind": event_kind,
            "temporal_value": parsed.to_dict(),
            "evidence": [_evidence_for(entry, domain, field_label)],
            "basis": basis,
            "confidence": _confidence_for(parsed),
            "extractor_version": extractor_version,
        },
        now=now,
    )


#: `chronology.CONFIDENCES` -> the claim's calibrated 0..1 support. The claim
#: schema wants a number and the package has always spoken in words; this is
#: the one place the two meet. The numbers are ORDINAL — they preserve the
#: package's own ordering and nothing more — and they are never allowed to
#: substitute for provenance, which is why `basis` is carried separately.
CONFIDENCE_SCORE = {
    "certain": 0.95,
    "approximate": 0.7,
    "inferred": 0.45,
    "conjectural": 0.2,
}


def _confidence_for(record: object) -> float:
    parsed = chrono.from_dict(record)
    if parsed is None:
        return 0.0
    return CONFIDENCE_SCORE.get(parsed.confidence, 0.45)


def entry_claims(
    domain: object,
    entry: object,
    *,
    source_ref: object,
    extractor_version: str = LEGACY_EXTRACTOR,
    now: object = None,
) -> list[dict]:
    """Every temporal claim one filed landmark record asserts. PURE, no model.

    The deterministic rule, in full:

    * ONE ``identity`` claim, always. It says the entry was named and carries
      no date, and it is what a correction retracts to remove the entry.
    * ``entry["date"]`` and each of its ``date_alternates`` -> a ``date``
      claim at :func:`date_event_kind`. The alternates are not decoration:
      v222 kept every claim a date OUTRANKED, and here they become what they
      always were — RIVAL CLAIMS, which the projection reconciles again on
      every draw.
    * ``entry["span"]["start"]`` / ``["end"]`` and their ``span_alternates``
      -> ``date`` claims at :data:`SPAN_START_EVENT_KIND` /
      :data:`SPAN_END_EVENT_KIND`.

    Claims whose id collides are folded to the first, in score order. That is
    not a shortcut: the substrate's own rule is that the same fact asserted
    twice in one source is one claim (``derive_claim_id`` deliberately keeps
    evidence out of the digest), and two stored alternates that reduce to the
    same interval on the same reading ARE the same fact. `chronology` folds
    repeat tellings by ``(edtf, basis)`` and the claim id folds by interval
    alone, so the narrow gap between those two definitions is the only thing
    this dedupe ever closes.
    """
    if not isinstance(entry, dict):
        raise LandmarkProjectionError(
            "landmark_record_empty", "a landmark record must be an object"
        )
    name = collapsed_text(domain)
    if not name:
        raise LandmarkProjectionError(
            "landmark_domain_required", "a landmark record needs a domain"
        )
    row = domain_row_or_none(name)
    mention = entry_subject_mention(entry, row, name)
    kind = date_event_kind(row)
    # Keep ordinary old receipts identical on re-file. Only names refused by
    # the untyped heuristic need the question set's non-person qualification.
    subject_annotation = {}
    if (
        isinstance(row, dict)
        and row.get("identity_kind") in ATOMIC_LANDMARK_IDENTITY_KINDS
        and len(split_subject_enumeration(mention)) > 1
    ):
        subject_annotation["landmark_identity_kind"] = row["identity_kind"]

    claims: list[dict] = [
        validate_temporal_claim(
            {
                "source_ref": source_ref,
                "source_kind": "import",
                "claim_type": "identity",
                "subject_mention": mention,
                **subject_annotation,
                "evidence": [_evidence_for(entry, name, "domain")],
                # An entry's existence is as explicit as the act of filing it.
                "basis": "explicit",
                "confidence": 1.0,
                "extractor_version": extractor_version,
            },
            now=now,
        )
    ]

    span = entry.get("span") if isinstance(entry.get("span"), dict) else {}
    span_alternates = entry.get(landmarks_interaction.SPAN_ALTERNATES_KEY)
    if not isinstance(span_alternates, dict):
        span_alternates = {}

    plan: list[tuple[object, str, str]] = []
    plan.append((entry.get("date"), kind, "date"))
    for alternate in _as_list(entry.get(landmarks_interaction.DATE_ALTERNATES_KEY)):
        plan.append((alternate, kind, "date"))
    for bound, bound_kind in (
        ("start", SPAN_START_EVENT_KIND),
        ("end", SPAN_END_EVENT_KIND),
    ):
        plan.append((span.get(bound), bound_kind, "span"))
        for alternate in _as_list(span_alternates.get(bound)):
            plan.append((alternate, bound_kind, "span"))

    for record, event_kind, field_label in plan:
        if not record:
            continue
        claim = _date_claim(
            record,
            entry=entry,
            domain=name,
            mention=mention,
            event_kind=event_kind,
            field_label=field_label,
            source_ref=source_ref,
            extractor_version=extractor_version,
            now=now,
            subject_annotation=subject_annotation,
        )
        if claim is not None:
            claims.append(claim)

    deduped: dict[str, dict] = {}
    for claim in claims:
        deduped.setdefault(claim["claim_id"], claim)
    return list(deduped.values())


def _as_list(value: object) -> list:
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


# --------------------------------------------------------------------------
# The promoted landmark source
# --------------------------------------------------------------------------


def entry_promotion_digest(domain: object, entry: object, *, ordinal: int) -> str:
    """The sha256 identifying ONE filed landmark record.

    Domain, the record's bytes and its filing ordinal. The ordinal is in the
    identity on purpose: filing the identical record twice in a row is two
    tellings, and the substrate's answer to "did they say it twice?" is two
    sources with two receipts, never one file silently absorbing the second.
    Re-running the SAME import, however, recomputes the same ordinals and
    therefore the same digests, which is what makes the flip idempotent.
    """
    payload = {
        "domain": collapsed_text(domain),
        "entry": entry if isinstance(entry, dict) else {},
        "ordinal": int(ordinal),
    }
    return store.payload_sha256(canonical_json(payload))


def landmark_source_relative_path(digest: str) -> str:
    """``sources/landmarks/entry-<24 hex>.md`` — a pure function of the record."""
    text = collapsed_text(digest).lower()
    if len(text) < store.FILENAME_DIGEST_LENGTH or not all(
        c in "0123456789abcdef" for c in text
    ):
        raise LandmarkProjectionError(
            "landmark_source_malformed", f"not a sha256 digest: {digest!r}"
        )
    return f"{LANDMARK_SOURCES_DIR}/entry-{text[:store.FILENAME_DIGEST_LENGTH]}.md"


def promote_landmark_entry(
    vault_root: str | Path,
    domain: object,
    entry: object,
    *,
    ordinal: int,
    filed_at: object = None,
    digest: str | None = None,
) -> SourceRef:
    """File one landmark record as a durable vault source and return its ref.

    Amendment 2's pairing rule, applied to the ladder: the record becomes an
    ordinary source document BEFORE any claim cites it, so a crash between the
    two leaves a re-runnable state and never a receipt citing a source that is
    not in the vault. Idempotent on :func:`entry_promotion_digest` — or, when
    ``digest`` is supplied, on that digest instead.

    The frontmatter carries the grouping key and the filing order because they
    are facts about the FILING — which domain it was filed under, which entry
    it is a telling of, and when in the sequence it arrived. The projection
    needs all three and may not re-derive them later from a drawing it is
    itself responsible for producing.

    ``digest``, when given, REPLACES :func:`entry_promotion_digest` as this
    source's identity. E-L3 (design §10.4, H4) is the reason it exists: an
    imported block's identity is ``(import_operation_id, block_local_id,
    canonical block bytes)`` — never the filing ordinal, because
    ``next_ordinal`` shifts on every retry as earlier blocks in the same
    import land, and a digest keyed on it would mint a duplicate source for
    every block already filed before a crash. ``ordinal`` is still recorded
    in the frontmatter for filing order — retry safety just no longer runs
    through it.
    """
    name = collapsed_text(domain)
    if not name:
        raise LandmarkProjectionError(
            "landmark_domain_required", "a landmark record needs a domain"
        )
    if not isinstance(entry, dict) or not entry:
        raise LandmarkProjectionError(
            "landmark_record_empty", "a landmark record must be a non-empty object"
        )

    row = domain_row_or_none(name)
    digest = collapsed_text(digest) or entry_promotion_digest(name, entry, ordinal=ordinal)
    relative = landmark_source_relative_path(digest)
    payload = f"{canonical_json(entry)}\n"

    frontmatter: dict = {
        "title": _source_title(entry, row, name),
        "type": LANDMARK_SOURCE_TYPE,
        "source_id": f"landmark:entry-{digest[:store.FILENAME_DIGEST_LENGTH]}",
        "source_medium": "landmark_ladder",
        "landmark_domain": name,
        "landmark_entry_key": landmarks_interaction.landmark_entry_key(entry, row),
        "filed_ordinal": int(ordinal),
        "captured_at": normalized_timestamp(filed_at, error=LandmarkProjectionError),
        "visibility": "owner_only",
        "status": "raw",
        "immutable": True,
        "schema_version": SCHEMA_VERSION,
        "source_path": relative,
        "content_sha256": store.payload_sha256(payload),
    }

    content = f"{store.format_frontmatter(frontmatter)}\n\n{payload}"
    root = _root(vault_root)
    path = store.store_path(root, relative)
    try:
        atomic_create_vault_bytes(path, content.encode("utf-8"), vault_root=root)
    except FileExistsError:
        pass
    except ValueError as exc:
        raise LandmarkProjectionError("landmark_source_malformed", str(exc)) from exc

    source_ref = store.read_source_ref(vault_root, relative)
    if source_ref is None:  # pragma: no cover - the create above guarantees it
        raise LandmarkProjectionError(
            "landmark_source_malformed", f"{relative} vanished during promotion"
        )
    return source_ref


def _source_title(entry: dict, row: object, domain: str) -> str:
    named = landmarks_interaction.identity_named(entry, row) if isinstance(row, dict) else None
    if named:
        return f"{domain}: {named}"[:120]
    if entry.get("none") is True:
        return f"{domain}: none"
    if entry.get("skipped") is True:
        return f"{domain}: skipped"
    return domain


# --------------------------------------------------------------------------
# Filing: source, then receipt, both idempotent
# --------------------------------------------------------------------------


def file_landmark_record(
    vault_root: str | Path,
    domain: object,
    entry: object,
    *,
    ordinal: int,
    extractor_version: str = LIVE_EXTRACTOR,
    now: object = None,
    digest: str | None = None,
) -> dict:
    """Promote one record and file its receipt. The pairing rule, in one call.

    Returns ``{"source_ref", "receipt_path", "claims"}``. Source first, then
    receipt, both idempotent — the identical ordering
    `temporal_store.file_message_extraction` uses, for the identical reason.

    ``digest`` passes straight through to :func:`promote_landmark_entry` — see
    its own docstring (E-L3, design §10.4).
    """
    source_ref = promote_landmark_entry(
        vault_root, domain, entry, ordinal=ordinal, filed_at=now, digest=digest
    )
    claims = entry_claims(
        domain,
        entry,
        source_ref=source_ref.to_dict(),
        extractor_version=extractor_version,
        now=now,
    )
    # Event identity I1 (C1's named gap, design §3.1). The recorder DECLARES
    # its tellings rather than leaving a reader to infer them: one telling per
    # promoted entry, keyed by the entry id, which is minted by the recorder
    # and does not move when a later model describes the same entry with other
    # words. That id is therefore also the strongest re-key evidence there is,
    # and the promoted source is written once and never rewritten, so its own
    # revision IS the document revision a person would correct.
    entry_id = source_ref.source_id.partition(":")[2] or source_ref.source_id
    receipt = validate_extraction_receipt(
        {
            "source_ref": source_ref.to_dict(),
            "extractor_version": extractor_version,
            "extractor": ei.declare_tellings(
                {
                    "name": "landmark-entry-rule",
                    "rule_version": "1",
                    "deterministic": True,
                },
                telling_keys={
                    collapsed_text(row.get("claim_id")): ei.landmark_telling_ref(entry_id)
                    for row in claims
                    if collapsed_text(row.get("claim_id"))
                },
                document_revision=source_ref.revision,
                recorder_event_id=entry_id,
            ),
            "claims": claims,
            "recorder": "landmark_projection",
        },
        now=now,
    )
    path = store.write_receipt(vault_root, receipt, now=now)
    return {
        "source_ref": source_ref,
        "receipt_path": path.relative_to(_root(vault_root)).as_posix(),
        "claims": claims,
    }


# --------------------------------------------------------------------------
# Reading the promoted sources back
# --------------------------------------------------------------------------


def load_landmark_sources(vault_root: str | Path) -> list[dict]:
    """Every promoted landmark record, in filing order.

    ``[{"source_id", "relative_path", "domain", "entry_key", "ordinal",
    "record"}, ...]`` sorted by ``(ordinal, source_id)`` — a total order, so
    two records filed with the same ordinal (which the ordinal rules make
    impossible, but a hand-edited vault could still produce) still fold the
    same way on every machine.

    Unreadable or foreign files are skipped rather than raised on, the way
    every other read path in this package degrades.
    """
    root = _root(vault_root)
    base = store.store_path(root, LANDMARK_SOURCES_DIR)
    if not base.is_dir():
        return []
    rows: list[dict] = []
    for path in sorted(base.glob("entry-*.md")):
        if path.is_symlink() or not path.is_file():
            continue
        relative = path.relative_to(root).as_posix()
        try:
            content = path.read_text(encoding="utf-8")
        except OSError:
            continue
        metadata, body = store.split_frontmatter(content)
        if not metadata or metadata.get("type") != LANDMARK_SOURCE_TYPE:
            continue
        source_id = collapsed_text(metadata.get("source_id"))
        domain = collapsed_text(metadata.get("landmark_domain"))
        if not source_id or not domain:
            continue
        try:
            record = json.loads(body.strip() or "{}")
        except json.JSONDecodeError:
            continue
        if not isinstance(record, dict):
            continue
        rows.append(
            {
                "source_id": source_id,
                "relative_path": relative,
                "domain": domain,
                "entry_key": str(metadata.get("landmark_entry_key") or ""),
                "ordinal": _as_int(metadata.get("filed_ordinal")),
                "record": record,
            }
        )
    rows.sort(key=lambda row: (row["ordinal"], row["source_id"]))
    return rows


def stay_slots(sources: object) -> dict:
    """``{source_id: (domain, entry_key, slot)}`` — the INTERVAL-AWARE key.

    Design §3.2 / audit finding H1, applied where it can actually be applied.
    The identity half of the key (`landmarks_interaction.landmark_entry_key`)
    is a pure function of ONE record and is written on the promoted source's
    own frontmatter at filing time; the interval half is a property of a
    record AND its siblings, which no per-record function can know. So the
    split happens HERE, in the fold, over the filing-ordered sources: the
    stored frontmatter never moves, no promoted source is rewritten, no
    digest churns, and a vault filed years ago splits its second stay on its
    next redraw with no migration at all (M11 answered by derivation).

    The walk is filing order and the predicate is
    `landmarks_interaction.same_landmark_stay`; the running fold of a slot is
    `merge_landmark_entry` — the SAME function the projection will use to
    build the entry — so the interval a record is compared against is exactly
    the interval the entry it would join actually has.

    EXACTLY ONE compatible slot joins; zero or several open a new one. That is
    §4.1 condition 4's own posture — *several compatible episodes of one entity
    place nothing* — applied to the ladder rather than to a story, and it is
    what keeps E-L2a's refusal true instead of quietly reversing it: an
    undated telling that names a place a person lived at twice belongs to one
    of those stays and NOBODY KNOWS WHICH. Rather than attributing it to the
    earlier one, it becomes its own undated stay — unplaced, never a
    container, carrying its own span question (M3) — and one human `same`
    answer joins it (§5.4). The incremental fill is untouched, because while
    there is one slot there is nothing to be ambiguous about.

    The practical consequence, and the reason it is worth the extra entry: NO
    EPISODE ID CHURNS. An undated telling in a group that already held two
    starts was `unplaced` before this function existed and is `unplaced`
    after it, discriminated by the same promoted source id.
    """
    rows: dict[str, list[dict]] = {}
    slots: dict[str, tuple[str, str, int]] = {}
    domain_rows: dict[str, object] = {}
    for source in sources or ():
        if not isinstance(source, dict):
            continue
        domain = collapsed_text(source.get("domain"))
        source_id = collapsed_text(source.get("source_id"))
        if not source_id:
            continue
        entry_key = collapsed_text(source.get("entry_key"))
        record = source.get("record") if isinstance(source.get("record"), dict) else {}
        if domain not in domain_rows:
            domain_rows[domain] = domain_row_or_none(domain)
        row = domain_rows[domain]
        key = f"{domain}\x00{entry_key}"
        held = rows.setdefault(key, [])
        compatible = [index for index, folded in enumerate(held)
                      if landmarks_interaction.same_landmark_stay(folded, record, row)]
        if len(compatible) == 1:
            chosen = compatible[0]
            held[chosen] = landmarks_interaction.merge_landmark_entry(held[chosen], record)
        else:
            held.append(landmarks_interaction.merge_landmark_entry(None, record))
            chosen = len(held) - 1
        slots[source_id] = (domain, entry_key, chosen)
    return slots


def participation_kinds_by_telling(landmark_entries: object) -> dict:
    """``{telling ref: episode kind}`` for every participation entry.

    The SAME table :class:`ParticipationEpisodes` folds with, handed to the
    binder so the fold and the binder cannot disagree about what a residence
    is (ADR 0021). Without it the binder's own ``_kind_of`` reads a landmark
    telling's ``started``/``ended`` claims and its family table files a
    residence under ``work`` — the misfiling design §0.2 M1 names.

    That module's name is deliberately not written in this file: `compile`
    reaches this module, and `test_the_binder_never_runs_inside_compile`
    sweeps the modules compile reaches for exactly that string. The guard is
    textual on purpose — an import is what it is there to catch — so the
    honest way past it is to not name the module, never to loosen the sweep.
    """
    import event_identity as identity  # noqa: PLC0415

    found: dict[str, str] = {}
    for row in (landmark_entries or ()):
        if not isinstance(row, dict):
            continue
        domain = collapsed_text(row.get("domain"))
        source_id = collapsed_text(row.get("source_id"))
        kind = PARTICIPATION_EPISODE_KINDS.get(domain)
        if not kind or not source_id:
            continue
        entry_id = source_id.partition(":")[2] or source_id
        found[identity.landmark_telling_ref(entry_id)] = kind
    return found


class ParticipationEpisodes:
    """:data:`PARTICIPATION_EPISODE_RULE_TEXT`, applied. Pure; no vault, no model.

    Built once per fold from the RESOLVED claims and
    :func:`load_landmark_sources`' rows, and read three ways:

    * :meth:`node_for` — the node id a claim of a participation entry groups
      under, so an entry's ``started`` and ``ended`` claims land on ONE
      episode node instead of two loose points;
    * :meth:`seed_groups` — the group an entry with no dated claim still gets,
      which is how an UNDATED stay exists as a node at all (design §3.2 M3);
    * :attr:`node_aliases` — ``former node id -> node id`` for a stay that
      has since been dated, so every id an undated stay was ever cited under
      still resolves (Law 5's shape, derived rather than remembered);
    * :attr:`node_of_episode` — ``container episode id -> node id``, the join
      the containment window needs. A container the binder has not bound is
      named by `episode_containers.container_episode_id`, and until this map
      existed the record the rung filed pointed at an episode the projection
      had no node for, so no window could ever be drawn.

    Nothing here writes and nothing here guesses: an entry reaches this class
    only through its own promoted source's ``landmark_domain``.
    """

    def __init__(self, claims: object = (), landmark_entries: object = ()) -> None:
        import episode_containers as ec  # noqa: PLC0415
        import event_identity as identity  # noqa: PLC0415
        import identity_resolution as ident  # noqa: PLC0415

        self.node_of_claim: dict[str, str] = {}
        self.node_of_episode: dict[str, str] = {}
        self.node_aliases: dict[str, str] = {}
        self.seeds: dict[str, dict] = {}
        self.unplaced: set[str] = set()

        slots = stay_slots(landmark_entries)
        entries = {}
        for row in (landmark_entries or ()):
            if not isinstance(row, dict):
                continue
            domain = collapsed_text(row.get("domain"))
            source_id = collapsed_text(row.get("source_id"))
            if not source_id or domain not in PARTICIPATION_EPISODE_KINDS:
                continue
            # NOT EVERY FILED RECORD IS A LANDMARK (lifehug#365,
            # :func:`not_a_landmark`). A none terminal, a skip and an
            # organization nobody named are complete answers that improve no
            # spine, so they seed NO episode, take NO stay slot and carry no
            # card. Skipped HERE, at draw time, so an existing vault heals on
            # its next redraw.
            if not_a_landmark(domain, row.get("record")):
                continue
            entries[source_id] = {
                "domain": domain,
                # The ladder's own grouping key — :func:`stay_slots`, which is
                # the identity published on the promoted source's frontmatter
                # PLUS §3.2's interval half. Several tellings of ONE entry (the
                # ladder fills a stay incrementally — the city first, the span
                # later) share it, which is what lets a start stated in a
                # second breath reach the episode the first breath minted; two
                # disjoint stays at one address no longer do, which is what
                # lets the second one exist.
                "entry_key": slots.get(source_id) or (domain, collapsed_text(
                    row.get("entry_key")) or source_id, 0),
            }
        if not entries:
            return

        by_source: dict[str, list] = {}
        for claim in (claims or ()):
            if not isinstance(claim, dict):
                continue
            ref = claim.get("source_ref")
            source_id = collapsed_text(ref.get("source_id")) if isinstance(ref, dict) else ""
            if source_id in entries:
                by_source.setdefault(source_id, []).append(claim)

        tellings: list[dict] = []
        for source_id in sorted(by_source):
            rows = sorted(by_source[source_id],
                          key=lambda row: collapsed_text(row.get("claim_id")))
            subject = ""
            for row in rows:
                subject = (collapsed_text(row.get("subject_ref"))
                           or collapsed_text(row.get("subject_mention")))
                if subject:
                    break
            if not subject:
                continue
            entry = entries[source_id]
            tellings.append({
                "source_id": source_id,
                "claims": rows,
                "subject": subject,
                "kind": PARTICIPATION_EPISODE_KINDS[entry["domain"]],
                "domain": entry["domain"],
                "group": (entry["entry_key"], subject),
                "start": _span_start_value(rows),
                "end": _span_end_value(rows),
            })

        #: Which stay a telling with no start belongs to. The ladder fills one
        #: entry over several breaths, so a telling that names only the city
        #: and a telling that gives the span are ONE stay — and the second one
        #: is what re-keys the episode from its source id to its start date
        #: (design §3.2 M3). It resolves only when the stay key has exactly
        #: ONE start. Since E-L2b that key is interval-aware, so two disjoint
        #: stays at one address are two keys rather than one key with two
        #: starts — and a telling that genuinely cannot be attributed (an
        #: undated telling the interval half could not separate) still gets
        #: its own unplaced episode rather than a guess.
        starts: dict[tuple, set] = {}
        for row in tellings:
            if row["start"]:
                starts.setdefault(row["group"], set()).add(row["start"])

        # THE SLOT IS THE EPISODE. `stay_slots` has already decided which
        # tellings are one entry — the ladder's own interval-aware identity,
        # which joins stretches that intersect or abut and splits a stay the
        # person returned to years later — so every telling of one slot folds
        # to ONE episode node, discriminated by the slot's earliest start. A
        # school or a job the ladder recorded under three consecutive stays
        # ("from the dates of the Orchard House stay", three times) is one
        # tenure across them, not three rival tenures no story can tell apart;
        # a second stay at one place is still a second slot and a second
        # episode. The id each later telling would have carried alone still
        # resolves through `node_aliases`, derived rather than remembered, so
        # nothing already cited churns.
        # `stay_slots` compares each record against the FIRST stretch of its
        # slot, so a chain of abutting windows (four consecutive stays that each
        # name the same employer) can span several slots. The chain is walked
        # here, once, in start order: a window that overlaps or begins within
        # `SEQUENCE_ENTRY_ABUT_MONTHS` of the running end joins the tenure.
        chain_start = _chain_starts(tellings)
        del starts

        for row in sorted(tellings, key=lambda item: item["source_id"]):
            discriminator = chain_start.get(row["source_id"], "")
            # M3: an undated stay is still an episode. Its discriminator is
            # the promoted source id — durable, minted by the recorder, unique
            # per telling — so two undated stays at one place stay two.
            unplaced = not discriminator
            if unplaced:
                discriminator = row["source_id"]
            try:
                node_id = ident.derive_episode_ref(
                    event_kind=row["kind"], subject_mention=row["subject"],
                    discriminator=discriminator,
                )
            except ident.IdentityResolutionError:
                continue
            if not unplaced:
                # THE RE-KEY, DERIVED RATHER THAN REMEMBERED. The id this
                # telling would have carried alone — its own start, or its
                # promoted source id while it had no start — still resolves.
                # Both ids are pure functions of the same records, so the alias
                # survives a `state/` deletion exactly as event identity's own
                # Law 5 aliases do — nothing is carried in state to lose.
                for former in (row["start"], row["source_id"]):
                    if not former or former == discriminator:
                        continue
                    try:
                        self.node_aliases[ident.derive_episode_ref(
                            event_kind=row["kind"], subject_mention=row["subject"],
                            discriminator=former,
                        )] = node_id
                    except ident.IdentityResolutionError:
                        pass
            entry_id = row["source_id"].partition(":")[2] or row["source_id"]
            telling_ref = identity.landmark_telling_ref(entry_id)
            self.node_of_episode[ec.container_episode_id(telling_ref)] = node_id
            if unplaced:
                self.unplaced.add(node_id)
            else:
                self.unplaced.discard(node_id)
            self.seeds.setdefault(node_id, {
                "node_id": node_id,
                "event_kind": row["kind"],
                "node_kind": "episode",
                "subject": row["subject"],
                "subjects": [],
                "resolved": False,
                "claims": [],
                "participation_domain": row["domain"],
                "participation_source_id": row["source_id"],
            })
            for claim in row["claims"]:
                claim_id = collapsed_text(claim.get("claim_id"))
                if claim_id:
                    self.node_of_claim[claim_id] = node_id

    def __bool__(self) -> bool:
        return bool(self.node_of_claim)

    def node_for(self, claim: object) -> str:
        """The participation node this claim belongs to, or ``""``."""
        if not self.node_of_claim:
            return ""
        return self.node_of_claim.get(
            collapsed_text((claim or {}).get("claim_id")), ""
        )

    def seed_groups(self) -> dict:
        """A fresh copy of the seeds, so a caller may mutate its own groups."""
        return {
            node_id: {**row, "subjects": list(row["subjects"]),
                      "claims": list(row["claims"])}
            for node_id, row in self.seeds.items()
        }

    def is_unplaced(self, node_id: object) -> bool:
        return collapsed_text(node_id) in self.unplaced


def _months(text: object) -> int | None:
    """A start or end as whole months since year zero; ``None`` when unreadable."""
    import chronology as chrono  # noqa: PLC0415

    record = chrono.parse_edtf(text)
    value = collapsed_text(record.earliest if record is not None else text)
    parts = value.split("-")
    try:
        year = int(parts[0])
        month = int(parts[1]) if len(parts) > 1 else 1
    except (TypeError, ValueError):
        return None
    return year * 12 + month


def _chain_starts(tellings: object) -> dict[str, str]:
    """``source id -> the start that discriminates its tenure``, chaining windows.

    The tellings of one entry key and subject are sorted by start. A telling
    whose window overlaps the running chain, or begins within
    `landmarks_interaction.SEQUENCE_ENTRY_ABUT_MONTHS` of its end, joins it;
    the chain's discriminator is its earliest start. An open-ended window keeps
    the chain open. A telling with no start joins when its key has exactly one
    chain and stays undiscriminated otherwise (design §3.2 M3) — an undated
    telling of a place the person returned to belongs to one stay and nobody
    knows which.
    """
    by_key: dict[tuple, list] = {}
    for row in tellings or ():
        slot = row["group"][0]
        entry_key = slot[1] if isinstance(slot, tuple) and len(slot) > 1 else slot
        by_key.setdefault((row["domain"], entry_key, row["subject"]), []).append(row)
    result: dict[str, str] = {}
    abut = landmarks_interaction.SEQUENCE_ENTRY_ABUT_MONTHS
    for rows in by_key.values():
        dated = sorted(
            (row for row in rows if row["start"]),
            key=lambda row: (_start_ordinal(row["start"]), row["source_id"]),
        )
        chains: list[list] = []  # [discriminator, running end in months or None (open), member ids]
        for row in dated:
            start = _months(row["start"])
            end = _months(row["end"]) if row["end"] else None
            current = chains[-1] if chains else None
            joins = current is not None and (
                current[1] is None or start is None or start - current[1] <= abut
            )
            if joins:
                current[2].append(row["source_id"])
                if current[1] is not None:
                    current[1] = None if end is None else max(current[1], end)
            else:
                chains.append([row["start"], end, [row["source_id"]]])
        for discriminator, _end, members in chains:
            for source_id in members:
                result[source_id] = discriminator
        if len(chains) == 1:
            for row in rows:
                if not row["start"]:
                    result[row["source_id"]] = chains[0][0]
    return result


def _start_ordinal(text: object) -> str:
    """An ISO-comparable key for a start discriminator; the text itself otherwise."""
    import chronology as chrono  # noqa: PLC0415

    record = chrono.parse_edtf(text)
    return (record.earliest if record is not None and record.earliest else
            collapsed_text(text))


def _span_end_value(claims: object) -> str:
    """The latest bound of a participation entry's ``ended`` claim, or ``""``."""
    import chronology as chrono  # noqa: PLC0415

    for claim in claims or ():
        if not isinstance(claim, dict):
            continue
        if collapsed_text(claim.get("event_kind")) != SPAN_END_EVENT_KIND:
            continue
        record = chrono.from_dict(claim.get("temporal_value"))
        if record is not None and record.latest:
            return record.latest
    return ""


def _span_start_value(claims: object) -> str:
    """The stated start of a participation entry, as the episode discriminator.

    ``identity_resolution.episode_discriminator``'s own reading of a start
    value, applied to the ONE claim that carries it. A start the person did
    not state is not a discriminator — it is the absence M3 mints an unplaced
    episode for.
    """
    import identity_resolution as ident  # noqa: PLC0415

    for claim in claims or ():
        if not isinstance(claim, dict):
            continue
        if collapsed_text(claim.get("event_kind")) != SPAN_START_EVENT_KIND:
            continue
        value = ident.episode_discriminator(claim.get("temporal_value"))
        if value:
            return value
    return ""


def _as_int(value: object) -> int:
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0


# --------------------------------------------------------------------------
# The projection
# --------------------------------------------------------------------------


def project_landmark_entries(active_index: object, *, sources: object,
                             owner_names: object = ()) -> dict:
    """Draw ``state/landmarks.json`` from the active claims. PURE.

    ``active_index`` is `temporal_store.fold_active_index`'s mapping;
    ``sources`` is :func:`load_landmark_sources`'s list. Returns the file's
    own shape, ``{"version": 1, "domains": {domain: [entry, ...]}}``.

    The fold, in the order it runs:

    1. **Keep only sources with an active identity claim.** A source whose
       identity claim was retracted or superseded contributed a telling that
       no longer stands, and it drops out entirely. This is the one gate, and
       it is why the identity claim exists.
    2. **Group the survivors by ``(domain, entry_key)``**, in filing order.
       Several tellings of one entry — a city in March, an address in April —
       are one group.
    3. **Fold each group's SKELETONS** through
       `landmarks_interaction.merge_landmark_entry`, which is the same
       function the pre-flip write path used and therefore agrees with it by
       construction, including on the none terminal in both directions.
       Dates are stripped first (:func:`skeleton_of`) so this step cannot see
       one.
    4. **Reconcile each group's DATE CLAIMS** through `chronology.reconcile`,
       one reconciliation per date field, and write the winner plus every
       loser as the entry's ``date`` / ``date_alternates`` /
       ``span`` / ``span_alternates``. Identical to what
       `merge_landmark_entry` used to store at write time — same function,
       same claims, later.

    Entry ORDER within a domain is the order the group's FIRST telling was
    filed, which reproduces the pre-flip file exactly and keeps `residences`
    and `schools` — the sequence domains, whose order is part of the fact —
    walking forward in time as they did before.

    **A ``birth`` record that is not the owner's does not join step 2**
    (v339, :data:`BIRTH_LANDMARK_NOT_OWNER`). Dropping it HERE, before the
    group exists, is what makes both halves of the incident heal on the next
    redraw with no migration: its skeleton never reaches step 3, so the
    owner's raw ``day``/``month``/``year`` stay his, and its date claim never
    reaches step 4, so it is not written as one of his ``date_alternates``.
    The claim itself is still in the substrate and still says what it said —
    un-drawing a record is not retracting it — which is why the vault-side
    repair supersedes the claims separately.

    ``owner_names`` is this vault's owner spellings
    (`temporal_publication.owner_identity_inputs`, supplied by :func:`redraw`);
    ``()`` is "not told", and the rule then leans on the year bound and
    `temporal_timeline.is_owner_reference_only` alone.
    """
    active = {
        row.get("claim_id")
        for row in store.active_claims(active_index if isinstance(active_index, dict) else {})
    }
    by_source: dict[str, list[dict]] = {}
    for row in (active_index or {}).get("claims") or ():
        if not isinstance(row, dict) or row.get("claim_id") not in active:
            continue
        ref = row.get("source_ref")
        source_id = collapsed_text(ref.get("source_id")) if isinstance(ref, dict) else ""
        if source_id:
            by_source.setdefault(source_id, []).append(row)

    slots = stay_slots(sources)
    stated_birth = owner_stated_birth(sources)
    groups: dict[tuple[str, str, int], dict] = {}
    order: list[tuple[str, str, int]] = []
    for source in sources or ():
        claims = by_source.get(source["source_id"]) or []
        if not any(claim.get("claim_type") == "identity" for claim in claims):
            continue
        # THE `birth` DOMAIN IS THE OWNER'S OWN BIRTH (v339). A relative's
        # birth filed here keys on the same empty `entry_key` as the owner's
        # and would fold into his entry; it is skipped at draw time so a
        # vault that already holds one heals on its next redraw, exactly as
        # `not_a_landmark`'s other reasons do.
        if not_a_landmark(source["domain"], source["record"],
                          owner_birth=stated_birth,
                          owner_names=owner_names) == BIRTH_LANDMARK_NOT_OWNER:
            continue
        # THE INTERVAL-AWARE KEY (design §3.2). Two stays at one address share
        # the identity half of the key and differ in the interval half, so
        # they are two groups here and two entries below — where before H1's
        # fix the second stay's bounds landed in the first one's
        # `span_alternates` and the second stay ceased to exist.
        key = slots.get(source["source_id"]) or (source["domain"], source["entry_key"], 0)
        if key not in groups:
            groups[key] = {"skeletons": [], "claims": []}
            order.append(key)
        groups[key]["skeletons"].append(skeleton_of(source["record"]))
        groups[key]["claims"].extend(claims)

    domains: dict[str, list[dict]] = {}
    for key in order:
        domain = key[0]
        group = groups[key]
        entry: dict = {}
        for skeleton in group["skeletons"]:
            entry = landmarks_interaction.merge_landmark_entry(entry, skeleton)
        entry = skeleton_of(entry)
        row = domain_row_or_none(domain)
        _attach_dates(entry, group["claims"], row=row)
        domains.setdefault(domain, []).append(entry)

    return {"version": LANDMARKS_SCHEMA_VERSION, "domains": domains}


def _attach_dates(entry: dict, claims: list[dict], *, row: object) -> None:
    """Reconcile one group's dated claims onto the entry it belongs to."""
    kind = date_event_kind(row)
    buckets: dict[str, list[dict]] = {}
    for claim in claims:
        if claim.get("claim_type") != "date":
            continue
        record = chrono.from_dict(claim.get("temporal_value"))
        if record is None:
            continue
        buckets.setdefault(str(claim.get("event_kind") or ""), []).append(record.to_dict())

    best, alternates = _reconciled(buckets.get(kind))
    _set_or_drop(entry, "date", best)
    _set_or_drop(entry, landmarks_interaction.DATE_ALTERNATES_KEY, alternates or None)

    span: dict = {}
    span_alternates: dict = {}
    for bound, bound_kind in (
        ("start", SPAN_START_EVENT_KIND),
        ("end", SPAN_END_EVENT_KIND),
    ):
        bound_best, bound_alternates = _reconciled(buckets.get(bound_kind))
        if bound_best:
            span[bound] = bound_best
        if bound_alternates:
            span_alternates[bound] = bound_alternates
    _set_or_drop(entry, "span", span or None)
    _set_or_drop(entry, landmarks_interaction.SPAN_ALTERNATES_KEY, span_alternates or None)


def _reconciled(records: object) -> tuple[dict | None, list[dict]]:
    rows = [r for r in (records or ()) if r]
    if not rows:
        return None, []
    result = chrono.reconcile(rows)
    best = result["best_supported"]
    if best is None:
        return None, []
    return best.to_dict(), [record.to_dict() for record in result["alternates"]]


def _set_or_drop(target: dict, key: str, value: object) -> None:
    if value:
        target[key] = value
    else:
        target.pop(key, None)


# --------------------------------------------------------------------------
# The one-time flip
# --------------------------------------------------------------------------


def legacy_import_done(vault_root: str | Path) -> bool:
    """Has this vault already been converted?

    True when ANY receipt names :data:`LEGACY_EXTRACTOR`. Deliberately NOT a
    check for a specific receipt id: a receipt id binds to a source REVISION,
    the projection rewrites `state/landmarks.json` after the import, and a
    revision-bound check would therefore re-import the whole vault on the
    second compile and mint a duplicate of every claim. This is the exact
    trap the amendment's "idempotent by receipt" wording invites, and the
    state-machine test in `tests/test_landmark_projection.py` exists to keep
    it shut.
    """
    for relative in store.receipt_relative_paths(vault_root):
        receipt = store.read_receipt(vault_root, relative)
        if receipt is not None and receipt.extractor_version == LEGACY_EXTRACTOR:
            return True
    return False


def already_substrate_backed(vault_root: str | Path) -> bool:
    """Is this vault's drawing ALREADY derived? Then there is nothing to flip.

    Any promoted landmark source at all means the substrate is the truth,
    however it got that way — the one-time import, or an ordinary write in a
    vault that never held a legacy entry to import.

    :func:`legacy_import_done` alone is not this question and using it as the
    gate is a live bug, not a nicety: a vault created AFTER the flip has only
    ``landmark-record`` receipts and no ``legacy-entry-import`` one, so a
    legacy-receipt gate reads "never flipped", re-imports the projection it
    just drew, and files every entry a second time as its own ancestor. The
    committed none-supersession tests catch it, which is how it was found.
    """
    return bool(load_landmark_sources(vault_root))


def import_legacy_landmarks(
    vault_root: str | Path,
    landmarks: object,
    *,
    now: object = None,
) -> dict:
    """Convert every existing entry into sources + receipts. Deterministic.

    ``landmarks`` is `timeline.load_landmarks`'s mapping. Ordinals are
    assigned by walking the domains in the file's own order and each domain's
    entries in their stored order, so the projection redraws the file with its
    entries in the positions they already occupy.

    Idempotent: re-running assigns the same ordinals, so every promotion digest
    and every claim id is the same, every source file is already there and
    every receipt is byte-identical — nothing is written twice.
    """
    summary = {"sources": 0, "receipts": 0, "claims": 0, "entries": 0}
    ordinal = 0
    for domain, entries in (landmarks or {}).items():
        for entry in entries or ():
            if not isinstance(entry, dict) or not entry:
                continue
            ordinal += 1
            filed = dict(entry)
            filed.setdefault("domain", domain)
            result = file_landmark_record(
                vault_root,
                domain,
                filed,
                ordinal=ordinal,
                extractor_version=LEGACY_EXTRACTOR,
                now=now,
            )
            summary["entries"] += 1
            summary["sources"] += 1
            summary["receipts"] += 1
            summary["claims"] += len(result["claims"])
    return summary


def next_ordinal(vault_root: str | Path) -> int:
    """The ordinal the next filed record takes — one past the highest filed."""
    rows = load_landmark_sources(vault_root)
    return (max((row["ordinal"] for row in rows), default=0)) + 1


def entry_source_ids(sources: object, *, domain: str, entry_key: str,
                     slot: object = None) -> set[str]:
    """The promoted sources that are tellings of ONE entry.

    ``slot`` narrows it to ONE STAY of that identity (:func:`stay_slots`).
    Since the interval-aware key an identity may be several entries — two
    stays at one address — so "the sources of the Millgate entry" is an
    ambiguous question the moment a person lived there twice, and a caller
    retiring the second stay must not retire the first. ``None`` keeps the
    identity-wide reading, which is what the domain-level rules
    (`landmarks_interaction.entry_superseded_by`) actually mean.
    """
    rows = [source for source in (sources or ())
            if source.get("domain") == domain and source.get("entry_key") == entry_key]
    if slot is not None:
        slots = stay_slots(sources)
        wanted = int(slot)
        rows = [source for source in rows
                if (slots.get(source["source_id"]) or (domain, entry_key, 0))[2] == wanted]
    return {source["source_id"] for source in rows}


def active_claim_ids_for_entry(
    vault_root: str | Path, *, domain: str, entry_key: str, slot: object = None
) -> list[str]:
    """Every ACTIVE claim id standing behind one projected entry, sorted.

    What a correction has to name in order to remove that entry from the
    drawing. Sorted so the correction's own content digest — and therefore its
    filename — is the same on every machine.
    """
    index = store.read_active_index(vault_root) or store.fold_active_index(vault_root)
    ids = entry_source_ids(
        load_landmark_sources(vault_root), domain=domain, entry_key=entry_key,
        slot=slot,
    )
    found = []
    for row in store.active_claims(index):
        ref = row.get("source_ref")
        if isinstance(ref, dict) and collapsed_text(ref.get("source_id")) in ids:
            found.append(str(row.get("claim_id")))
    return sorted(found)


def retire_entry(
    vault_root: str | Path,
    *,
    domain: str,
    entry_key: str,
    reason: str,
    slot: object = None,
    occurred_at: object = None,
) -> object | None:
    """Supersede every claim behind one entry, so the projection drops it.

    This is how `entry_superseded_by`'s cross-entry rules are expressed after
    the flip. They used to be a `continue` in a rebuild loop — the entry simply
    was not copied forward, and the fact that it had ever been filed went with
    it. Now the entry's evidence stays on disk and a durable correction says
    which claims stopped standing and why, which is the difference between
    forgetting and remembering that you changed your mind.

    ``None`` when the entry has no active claims to retire — a no-op, not an
    error, so replaying a write cannot fail on the second pass.

    ``slot`` is E-L2b's *"this stay was not a home"* (§5 rule 6): ONE stay of
    an identity a person lived at twice, retired without touching the other.
    Omit it and the identity-wide reading stands, which is what the
    cross-entry domain rules mean and what every existing caller passes.
    """
    claim_ids = active_claim_ids_for_entry(
        vault_root, domain=domain, entry_key=entry_key, slot=slot
    )
    if not claim_ids:
        return None
    return store.supersede_claims(
        vault_root,
        claim_ids,
        reason=reason,
        scope=f"landmarks/{domain}",
        occurred_at=occurred_at,
    )


def redraw(vault_root: str | Path) -> dict:
    """Fold the receipts, read the sources, draw the file's content. No I/O out.

    The whole projection in one call, and deliberately WITHOUT the write: the
    landmark store's path is resolved by `lifehug_core` against the process's
    bound vault. Re-deriving that path here would be a second definition of
    where the file lives, so the one writer is `timeline.redraw_landmarks`,
    which already holds it as ``LANDMARKS_STORE``.

    v260 (Timeline Fix 01) removed the layout difference this paragraph used
    to have to explain: the store was at ``system/landmarks.json`` on an
    embedded vault and under ``state/`` on an external one, and the embedded
    path was a framework file an update re-shipped empty. It is now the one
    path in both layouts.
    """
    index = store.rebuild_active_index(vault_root)
    sources = load_landmark_sources(vault_root)
    return project_landmark_entries(index, sources=sources,
                                    owner_names=owner_names_for(vault_root))


def owner_names_for(vault_root: str | Path) -> tuple[str, ...]:
    """This vault's owner spellings, or ``()`` — never raises (v339).

    `temporal_publication.owner_identity_inputs` is the ONE definition of who
    the owner is for a fold of this vault (v328), and the birth rule reads it
    through the same seat rather than spelling a profile key of its own. A
    vault with no profile, or a profile that cannot be read, is "not told":
    the rule then refuses only on the year bound and on the bare owner
    references `temporal_timeline.is_owner_reference_only` knows, which is the
    conservative direction — an unknown owner never makes a record MORE
    suspect.
    """
    try:
        import temporal_publication  # noqa: PLC0415

        _roster, names = temporal_publication.owner_identity_inputs(vault_root)
        return tuple(names or ())
    except Exception:  # noqa: BLE001 — an unreadable profile is no profile
        return ()


def flip_if_needed(vault_root: str | Path, landmarks: object, *, now: object = None) -> dict | None:
    """Run the one-time conversion. ``None`` when this vault is already flipped.

    The migration trigger: entries exist and no legacy receipt does. The caller
    redraws afterwards — `timeline.redraw_landmarks` does both in order.
    Called on every derive/compile, and a no-op on every call after the first.
    """
    if already_substrate_backed(vault_root):
        return None
    if not any(entries for entries in (landmarks or {}).values()):
        return None
    return import_legacy_landmarks(vault_root, landmarks, now=now)


# --------------------------------------------------------------------------
# Chain closure (E-L2c; design §8, §12 row 19, §14.3)
# --------------------------------------------------------------------------
#
# "That is all for now" for one chain (residences, work, schools) is a
# decision RECORD, not a deletion and not a silent flag on the projection.
# It suppresses ROUTINE prompting only — the daily queue and the era Play
# chain rung skip a closed chain's gaps — and nothing else:
# `landmarks_interaction.chain_gaps` keeps computing every unknown stretch
# and Timeline/Go Dig keep drawing it. A later fact files normally.
# Reopening is a SUPERSEDING record, never an edit — the same shape every
# other correction in this package already holds to.
#
# `sources/landmarks/closures/` is a subdirectory of `LANDMARK_SOURCES_DIR`,
# already registered in `vault_contract.json` as a `directory`-kind entry —
# `vault_paths.classify_contract_path` treats any path under a registered
# directory as durable data, so no separate contract entry is needed here
# (verified against `classify_contract_path`'s own `candidate in
# relative.parents` rule rather than assumed).

CLOSURE_SOURCES_DIR = f"{LANDMARK_SOURCES_DIR}/closures"
CHAIN_CLOSURE_SOURCE_TYPE = "chain_closure"


def chain_closure_digest(*, domain: object, status: object, as_of: object,
                         supersedes: object = None) -> str:
    """The sha256 identifying one closure decision.

    A pure function of what the decision ASSERTS — domain, status, the day
    it was made, and what it supersedes — the same shape
    `temporal_store.move_digest` gives a drag, so a re-filed identical
    closure finds its own existing record rather than minting a sibling.
    """
    payload = {
        "domain": collapsed_text(domain),
        "status": collapsed_text(status),
        "as_of": collapsed_text(as_of),
        "supersedes": collapsed_text(supersedes) or None,
    }
    return store.payload_sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")))


def chain_closure_relative_path(digest: str) -> str:
    """``sources/landmarks/closures/closure-<24 hex>.md`` — a pure function
    of the record, exactly like every other immutable source this package
    writes."""
    text = collapsed_text(digest).lower()
    if len(text) < store.FILENAME_DIGEST_LENGTH or not all(
        c in "0123456789abcdef" for c in text
    ):
        raise LandmarkProjectionError(
            "chain_closure_malformed", f"not a sha256 digest: {digest!r}"
        )
    return f"{CLOSURE_SOURCES_DIR}/closure-{text[:store.FILENAME_DIGEST_LENGTH]}.md"


def file_chain_closure(
    vault_root: str | Path,
    *,
    domain: object,
    status: object,
    as_of: object,
    reason: object = None,
    supersedes: object = None,
    now: object = None,
) -> dict:
    """File one closure decision; idempotent on :func:`chain_closure_digest`.

    ``supersedes`` names the ``source_id`` of the closure this one amends or
    reopens (design §5 rule 10: "a superseding `chain_closure` with `status:
    open`"). Returns the normalized record (:func:`read_chain_closure`'s
    shape).
    """
    name = collapsed_text(domain)
    if name not in landmarks_interaction.CHAIN_DOMAINS:
        raise LandmarkProjectionError(
            "chain_closure_domain_unknown", f"unknown chain domain: {domain!r}"
        )
    verb = collapsed_text(status)
    if verb not in landmarks_interaction.CHAIN_CLOSURE_STATUSES:
        raise LandmarkProjectionError(
            "chain_closure_status_unknown", f"unknown closure status: {status!r}"
        )
    as_of_text = collapsed_text(as_of)
    if not as_of_text:
        raise LandmarkProjectionError(
            "chain_closure_as_of_required", "a closure needs an as_of date"
        )
    supersedes_id = collapsed_text(supersedes) or None
    digest = chain_closure_digest(domain=name, status=verb, as_of=as_of_text,
                                  supersedes=supersedes_id)
    relative = chain_closure_relative_path(digest)
    heading = f"{name} chain: {verb.replace('_', ' ')}"
    prose = collapsed_text(reason) or f"{heading}, as of {as_of_text}."
    payload = f"# {heading}\n\n{prose}\n"
    frontmatter: dict = {
        "title": heading,
        "type": CHAIN_CLOSURE_SOURCE_TYPE,
        "source_id": f"chain_closure:closure-{digest[:store.FILENAME_DIGEST_LENGTH]}",
        "source_medium": "owner",
        "domain": name,
        "status": verb,
        "as_of": as_of_text,
        "captured_at": normalized_timestamp(now, error=LandmarkProjectionError),
        "visibility": "owner_only",
        "immutable": True,
        "schema_version": SCHEMA_VERSION,
        "source_path": relative,
        "content_sha256": store.payload_sha256(payload),
    }
    if supersedes_id:
        frontmatter["supersedes"] = supersedes_id
    store.create_or_keep(
        vault_root, relative, f"{store.format_frontmatter(frontmatter)}\n\n{payload}"
    )
    record = read_chain_closure(vault_root, relative)
    if record is None:  # pragma: no cover - the create above guarantees it
        raise LandmarkProjectionError(
            "chain_closure_malformed", f"{relative} vanished during filing"
        )
    return record


def read_chain_closure(vault_root: str | Path, relative: str) -> dict | None:
    """Read one closure source back, or ``None`` when it is not one of ours."""
    text = store.read_store_text(vault_root, relative)
    if text is None:
        return None
    metadata, _ = store.split_frontmatter(text)
    if not metadata or metadata.get("type") != CHAIN_CLOSURE_SOURCE_TYPE:
        return None
    domain = collapsed_text(metadata.get("domain"))
    status = collapsed_text(metadata.get("status"))
    as_of = collapsed_text(metadata.get("as_of"))
    if not domain or not status or not as_of:
        return None
    return {
        "domain": domain,
        "status": status,
        "as_of": as_of,
        "source_id": collapsed_text(metadata.get("source_id")),
        "supersedes": collapsed_text(metadata.get("supersedes")) or None,
        "captured_at": collapsed_text(metadata.get("captured_at")),
        "source_path": relative,
    }


def load_chain_closures(vault_root: str | Path) -> list[dict]:
    """Every filed closure decision, in no particular order.

    The caller folds them with :func:`landmarks_interaction.active_chain_closures`
    to find the active one per domain — this function does no folding of its
    own, matching :func:`load_landmark_sources`'s own "read raw, fold
    elsewhere" shape.
    """
    root = _root(vault_root)
    base = store.store_path(root, CLOSURE_SOURCES_DIR)
    if not base.is_dir():
        return []
    rows: list[dict] = []
    for path in sorted(base.glob("closure-*.md")):
        if path.is_symlink() or not path.is_file():
            continue
        relative = path.relative_to(root).as_posix()
        record = read_chain_closure(vault_root, relative)
        if record is not None:
            rows.append(record)
    return rows
