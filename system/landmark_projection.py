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
    # v356: "a mission is a span like military service" (owner, 2026-09-25).
    "missions": "mission",
}

PARTICIPATION_EPISODE_RULE_TEXT = (
    "A landmark entry of a span domain IS a participation episode: its "
    "promoted telling's own domain names the episode's kind (residences -> "
    "residence, work -> job, schools -> school, military -> military, "
    "missions -> mission), its "
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


# --------------------------------------------------------------------------
# v345 — the evidence may NAME the kind the classifier's wildcard did not
# --------------------------------------------------------------------------

#: The single-word members of :data:`BIRTH_DOMAIN_WORDS`, read as whole TOKENS
#: rather than as a whole text. :func:`is_birth_domain_word` asks *"is this
#: whole text the domain's own vocabulary, naming nobody"*; :func:`names_a_birth`
#: asks the opposite question — *"does this sentence say a birth, and whose"* —
#: so the same words are matched inside a phrase and the rest of the phrase is
#: the name. Derived from the one set rather than re-listed, so a word added
#: there reaches both readers (recurring-defect doctrine).
BIRTH_PHRASE_WORDS = frozenset(
    word for word in BIRTH_DOMAIN_WORDS if " " not in word
)

#: The verbs a life's ARRIVAL is said with when no birth noun is present, and
#: the reason this rule exists at all: the owner's vault holds *"Harvey
#: arriving"*, whose evidence reads *"Birth of Harvey during the Etherfuse
#: chapter"*, classified as the `moment` wildcard — so the binder could not see
#: that a birth is what it is. Closed and small, exactly as
#: the binder's own `EVENT_VERB_STEMS` table is closed: a verb outside the list
#: leaves the sentence unread, which can only ever refuse a fold.
BIRTH_ARRIVAL_VERBS = ("was born", "arriving", "arrived", "arrives", "arrive")

_BIRTH_PHRASE_ALTERNATION = "|".join(
    re.escape(word) for word in sorted(BIRTH_PHRASE_WORDS, key=len, reverse=True)
)
_BIRTH_ARRIVAL_ALTERNATION = "|".join(
    re.escape(verb) for verb in sorted(BIRTH_ARRIVAL_VERBS, key=len, reverse=True)
)

#: Where a NAME stops inside a birth phrase. A birth sentence in the wild
#: carries the rest of the story with it ("Birth of Harvey during the Etherfuse
#: chapter"), and the name is the part before the first of these.
_BIRTH_NAME_STOP_RE = re.compile(
    r"(?<!\w)(?:during|in|on|at|after|before|while|when|and|as|to|from|the)"
    r"(?!\w)|[,;:()\[\]\u2014\u2013.!?\"]",
    re.IGNORECASE,
)

#: The birth phrase shapes, in the order they are tried. Each captures ``who``.
_BIRTH_PHRASE_RES = (
    re.compile(rf"(?<!\w)(?:{_BIRTH_PHRASE_ALTERNATION})\s+of\s+(?P<who>.+)$",
               re.IGNORECASE),
    re.compile(rf"^(?P<who>.+?)['\u2019]s\s+(?:{_BIRTH_PHRASE_ALTERNATION})(?!\w)",
               re.IGNORECASE),
    re.compile(rf"^(?P<who>.+?)\s+(?:{_BIRTH_ARRIVAL_ALTERNATION})(?!\w)",
               re.IGNORECASE),
)

#: A name longer than this is prose the shapes above failed to cut, not a
#: person. Refusing it is cheaper than half-reading it.
MAX_BIRTH_PHRASE_NAME = 80

#: A birth named AFTER one of these is an ADJUNCT: it says when the telling
#: happened, not what the telling is. The owner's vault taught both halves of
#: this list on the first two runs of this release. *"Katie and James joined the
#: author in Seattle once she was able to fly after childbirth (when_hint:
#: shortly after James's birth; anchor: James's birth)"* is a FLIGHT, and reading
#: it as James's birth folded a trip dated 2013-06/2013-07 onto a birthday dated
#: 2013-05-10. *"I remember her, when James was born, saying, 'I love him'"* is a
#: four-year-old's DECLARATION about her brother, and the subordinating
#: conjunction is the whole difference: a birth inside a ``when`` clause is the
#: clock the sentence is read against, never the sentence's own event.
BIRTH_PHRASE_IS_AN_ADJUNCT_AFTER = frozenset({
    "after", "before", "since", "until", "till", "during", "following",
    "shortly", "just", "soon", "post", "pre", "around", "near", "by",
    "when", "whenever", "once", "while", "as", "because", "though",
    "although", "remember", "remembers", "remembered",
})

#: The classifier's own WHEN metadata, which rides inside an evidence quote in
#: parentheses. Everything past one of these markers is a statement about when a
#: moment happened — very often *by naming another moment* — so it is cut before
#: the shapes are read at all. Whole-marker and casefolded.
BIRTH_PHRASE_WHEN_MARKERS = ("when_hint:", "anchor:", "spine:")

#: Determiners and possessives that carry no act, dropped before the adjunct
#: test looks at the word in front of a birth phrase — *"shortly after THE birth
#: of James"* is as much an adjunct as *"shortly after James's birth"*.
_BIRTH_PHRASE_QUALIFIERS = frozenset({
    "a", "an", "the", "my", "our", "his", "her", "their", "its", "of",
})


def _leads_the_phrase(text: object) -> str:
    """The last word that carries anything, in the run of words before a phrase."""
    for token in reversed(collapsed_text(text).split()):
        word = token.casefold().strip(".,;:()[]\u2014\u2013\"'")
        if word and word not in _BIRTH_PHRASE_QUALIFIERS:
            return word
    return ""


def names_a_birth(text: object) -> str:
    """Whose birth this sentence says it is, or ``""``.

    The three shapes a birth is said in — ``birth of X``, ``X's birth``,
    ``X arriving`` / ``X was born`` — read over :data:`BIRTH_PHRASE_WORDS` and
    :data:`BIRTH_ARRIVAL_VERBS`, whole-token in both directions so *"Bornstein"*
    and *"rebirth"* say nothing. The answer is a NAME and never a verdict: the
    caller is required to check that the name is somebody the telling is
    already about, because *"the birth of the company"* is not a person's birth
    and no word list can tell the difference.

    Two refusals keep the shapes off a birth the sentence names as an ANCHOR
    rather than as its own event, and both are the owner's vault's own lesson:
    the classifier's when-metadata is cut first
    (:data:`BIRTH_PHRASE_WHEN_MARKERS`), and a birth introduced by a temporal
    preposition is an adjunct (:data:`BIRTH_PHRASE_IS_AN_ADJUNCT_AFTER`) —
    *"shortly after James's birth"* dates a flight and is not one.
    """
    body = collapsed_text(text)
    if not body:
        return ""
    lowered = body.casefold()
    for marker in BIRTH_PHRASE_WHEN_MARKERS:
        cut = lowered.find(marker)
        if cut >= 0:
            body, lowered = body[:cut], lowered[:cut]
    body = collapsed_text(body)
    if not body:
        return ""
    for index, pattern in enumerate(_BIRTH_PHRASE_RES):
        match = pattern.search(body)
        if match is None:
            continue
        who = collapsed_text(match.group("who"))
        if not who:
            continue
        lead = ""
        if index == 0:
            # ``birth of X`` puts the name FIRST and the story after it, so the
            # adjunct word sits before the birth NOUN.
            lead = _leads_the_phrase(body[: match.start()])
            stops = list(_BIRTH_NAME_STOP_RE.finditer(who))
            if stops:
                who = who[: stops[0].start()]
        else:
            # The other two put the story first and the name last, so the
            # adjunct word is the token the name was cut away from.
            stops = list(_BIRTH_NAME_STOP_RE.finditer(who))
            if stops:
                lead = collapsed_text(who[stops[-1].start():stops[-1].end()])
                who = who[stops[-1].end():]
        if collapsed_text(lead).casefold().strip(".,;:()") in \
                BIRTH_PHRASE_IS_AN_ADJUNCT_AFTER:
            continue
        who = collapsed_text(who).strip(" '\u2019\u2014-")
        if who and len(who) <= MAX_BIRTH_PHRASE_NAME:
            return who
    return ""


# v344 — a dated birthday of a named person IS that person's birth
# --------------------------------------------------------------------------
#
# The owner filed his mother's birthday as a manual source on 2026-09-14 and
# the classifier read it exactly right: a `date` claim, 1955-06-19,
# certain/stated, `event_mention: "Desiree Taylor's birthday"`. What it could
# not say is WHAT KIND of event a birthday is, so the claim came out
# `event_kind: "moment"` — and `temporal_timeline`'s births are read off
# birth-KINDED nodes, so the one fact that anchors every age his mother is ever
# given was invisible to the arithmetic that needed it.
#
# THE RULE, and it belongs beside :data:`BIRTH_DOMAIN_WORDS` because it is the
# same vocabulary asked a different question. `is_birth_domain_word` asks *does
# this text name the domain instead of a person?*; :func:`birth_event_subject`
# asks *does this text name a PERSON'S birth?* — the possessive shape the
# domain words take when a name is in front of them. One set of nouns, two
# predicates, no third list.

#: The birth domain's own nouns, in the shape an event mention trails them in:
#: ``Desiree Taylor's birthday``, ``Harvey's birth date``, ``Katie was born``.
#: A SUBSET of :data:`BIRTH_DOMAIN_WORDS` — every member is one of those words
#: — and a test pins the containment, so this can never drift into a second
#: vocabulary. ``my birthday`` and the other owner-possessive spellings are
#: deliberately absent: they name the owner, whose birth v339/v340 govern.
BIRTH_EVENT_NOUNS = frozenset({
    "birth",
    "birthday",
    "birthdate",
    "birth date",
    "birth day",
    "date of birth",
    "born",
})

#: ``<Name>'s <noun>`` and ``<Name> was born`` / ``<Name> born``. The name is
#: whatever precedes the possessive, matched lazily so the LAST possessive wins
#: ("my brother James's birthday" names "my brother James"), and the noun is
#: compared whole against :data:`BIRTH_EVENT_NOUNS` rather than spelled into
#: the pattern, so the set stays the one definition.
_BIRTH_EVENT_RE = re.compile(
    r"^(?P<name>.*\S)(?:['’]s|s['’])\s+(?P<noun>[A-Za-z][A-Za-z ]*)$"
)
#: The verbal shape, and it REQUIRES the verb: ``Katie was born`` names Katie's
#: birth, while ``Mary Born`` is a person called Mary Born and names no event at
#: all — which is v341's own ruling about that exact string, kept.
_BIRTH_BORN_RE = re.compile(
    r"^(?P<name>.*?\S)\s+(?:was|is|were)\s+born$", re.IGNORECASE
)


def birth_event_subject(text: object) -> str:
    """The NAME whose birth ``text`` is, or ``""`` — whole-token, deterministic.

    ``"Desiree Taylor's birthday"`` -> ``"Desiree Taylor"``.
    ``"Harvey's birth date"`` -> ``"Harvey"``. ``"Katie was born"`` ->
    ``"Katie"``. ``"birthday"``, ``"my birthday"``, ``"Bornstein"`` and
    ``"Mary Born"`` -> ``""`` — the first two name the domain
    (:func:`is_birth_domain_word`), and the last two are names that merely
    contain one of its words, which is v341's ruling kept intact.

    Never a substring search. The noun must be the WHOLE tail of the mention
    after the possessive, so ``"Desiree's birthday cake"`` names no birth; the
    bare verbal form needs its verb, so ``"Mary Born"`` names none either; and
    the name must not itself be one of the domain's own words, so
    ``"the birth's date"`` names nobody.
    """
    body = collapsed_text(text).translate(_BIRTH_WORD_APOSTROPHES)
    if not body or is_birth_domain_word(body):
        return ""
    match = _BIRTH_EVENT_RE.match(body)
    if match is not None:
        noun = " ".join(match.group("noun").casefold().split())
        if noun not in BIRTH_EVENT_NOUNS:
            return ""
        name = collapsed_text(match.group("name"))
        return "" if is_birth_domain_word(name) else name
    match = _BIRTH_BORN_RE.match(body)
    if match is None:
        return ""
    name = collapsed_text(match.group("name"))
    return "" if not name or is_birth_domain_word(name) else name


#: The landmark domains whose ladder declares ``date_semantics: ["birth"]`` for
#: somebody OTHER than the owner — `family` (a sibling's or parent's birth year)
#: and `children` (a child's). Named here because the fold is a pure function of
#: its arguments and cannot read `interactions/landmarks/questions.yaml`; a
#: parity test derives the same pair from that file, so a ladder that changes
#: its semantics fails the build instead of silently teaching the age
#: arithmetic to read a wedding as a birthday. `birth` itself is absent: that
#: domain is the OWNER's own birthday (v339).
BIRTH_DATE_SEMANTICS_DOMAINS = ("children", "family")

#: What a ladder row's ``date_semantics`` says when its date is a birth. The
#: parity test reads this key rather than re-typing the word.
BIRTH_DATE_SEMANTICS = "birth"


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
# v345 — a landmark is drawn as WHAT IT IS
# --------------------------------------------------------------------------

#: v345. *"A collective/couple entry never has a birth; a family entry whose
#: date semantics are unknown should not be drawn as one."* (owner review of
#: staging, 2026-09-24.)
#:
#: :func:`date_event_kind` answers for a DOMAIN, and it is the right answer for
#: eight of the nine: a ``children`` entry dates a birth and a ``losses`` entry
#: dates a death whatever else the record happens to carry. ``family`` is the
#: one domain whose entries are not all the same shape. It declares
#: ``date_semantics: birth`` because a sibling entry dates a sibling's birth —
#: and the owner's own vault holds ONE ``family`` entry,
#: ``{"label": "parents", "who": "parents", "relation": "parent",
#: "date": 1976-06-25}``, which is his parents' WEDDING. Read as the domain
#: declares, that entry drew ``node:9ca9a5b1…`` "Parents's birth" at
#: 1976-06-25, beside ``node:6ece5329…`` "Parents' wedding date" at the same
#: day: one fact, two nodes, and one of them a birth nobody has ever had.
#:
#: A couple is not born. The one date two people share is the day they became
#: two people who share dates, so a collective subject's date is read as the
#: wedding — and a collective that may not be a COUPLE (three enumerated
#: siblings) is read as :data:`UNDISAMBIGUATED_EVENT_KIND`, which is this
#: module's existing word for *"a date whose event the record does not say"*.
A_LANDMARK_IS_DRAWN_AS_WHAT_IT_IS = (
    "a landmark entry's date is drawn as the event the ENTRY dates, not only "
    "as the event its domain declares: a collective subject has no birth, and "
    "the one date a couple shares is the day they became one — so a `family` "
    "entry whose subject is `parents` draws a wedding and never `<who>'s birth`"
)

#: The event kind a couple's shared date is. `landmarks_interaction`'s own
#: vocabulary (`DATE_SEMANTICS`), not a new word.
MARRIAGE_EVENT_KIND = "married"

#: Subjects that name exactly ONE couple, compared WHOLE and casefolded for the
#: reason :func:`is_birth_domain_word` is — "Parents" names a couple and
#: "Parenteau" names a man. A person has one set of parents and therefore one
#: parents' wedding, which is what makes this list's date readable at all.
COUPLE_SUBJECT_WORDS = frozenset({
    "parents", "my parents", "our parents", "the parents", "both parents",
    "mom and dad", "my mom and dad", "dad and mom", "mum and dad",
    "mother and father", "my mother and father", "father and mother",
    "husband and wife", "the couple", "my folks",
})

#: Subjects that name a GROUP but not necessarily one couple. Their date is not
#: a birth either — nobody is born collectively — but which event it IS cannot be
#: read, so it lands on :data:`UNDISAMBIGUATED_EVENT_KIND`. ``grandparents`` is
#: the reason this list is separate: a person has up to four of them and two of
#: their weddings, exactly the ambiguity that keeps the word out of
#: `identity_resolution.COUPLE_OF_RELATION_WORD`.
COLLECTIVE_SUBJECT_WORDS = frozenset({
    "grandparents", "my grandparents", "our grandparents", "the grandparents",
    "siblings", "my siblings", "brothers", "sisters", "my brothers",
    "my sisters", "the kids", "my kids", "children", "my children",
    "the family", "my family", "family",
})

#: Words in an entry's OWN text that say its date is the wedding. Read as whole
#: tokens; ``anniversary`` is here because a wedding anniversary is the wedding
#: day said another way, and a record that offers one is offering the other.
MARRIAGE_DATE_WORDS = frozenset({
    "married", "marriage", "marry", "wedding", "wed", "wedded", "anniversary",
})

#: Where an entry states a birth OUTRIGHT, beside the ladder's own ``date``.
#: An entry that carries one of these is a birth however collective its label
#: reads — the record said so — and the refinement leaves it alone.
ENTRY_BIRTH_FIELDS = ("birth", "born", "birthday", "birth_date", "date_of_birth",
                      "birth_year", "birthdate")


def _folded(text: object) -> str:
    return collapsed_text(text).casefold().translate(_BIRTH_WORD_APOSTROPHES)


def is_couple_subject(text: object) -> bool:
    """Does this subject name exactly ONE couple?

    WHOLE-text and casefolded, over :data:`COUPLE_SUBJECT_WORDS`, with the
    typographic apostrophes folded exactly as :func:`is_birth_domain_word`
    folds them.
    """
    body = _folded(text)
    return bool(body) and body in COUPLE_SUBJECT_WORDS


def is_collective_subject(text: object) -> bool:
    """Does this subject name a GROUP of people rather than one person?

    A couple is one (:func:`is_couple_subject`); so is every group in
    :data:`COLLECTIVE_SUBJECT_WORDS`, and so is any enumeration of two or more
    names (`temporal_claims.split_subject_enumeration`). Nobody in any of them
    was born collectively.
    """
    body = _folded(text)
    if not body:
        return False
    return (body in COUPLE_SUBJECT_WORDS
            or body in COLLECTIVE_SUBJECT_WORDS
            or len(split_subject_enumeration(collapsed_text(text))) > 1)


def entry_subject_text(entry: object, row: object, domain: object) -> str:
    """The subject an entry NAMES, before any fallback to the domain word.

    :func:`entry_subject_mention` is the claim-side reader and always returns
    something, because the substrate requires a non-empty mention. This one may
    return ``""``, which is what the refinement below needs: an entry that
    named nobody has no collective subject either.
    """
    if not isinstance(entry, dict):
        return ""
    named = landmarks_interaction.identity_named(entry, row) if isinstance(row, dict) else None
    if not named:
        for field in BIRTH_SUBJECT_FIELDS:
            value = entry.get(field)
            if isinstance(value, str) and value.strip():
                named = value.strip()
                break
    return collapsed_text(named)


def entry_words_name_a_marriage(entry: object) -> bool:
    """Do the entry's own words say its date is a wedding?

    Whole tokens over :data:`MARRIAGE_DATE_WORDS`, across the same free-text
    fields :data:`BIRTH_TEXT_FIELDS` names plus ``relation``, so a record that
    says ``married`` anywhere is read as saying it.
    """
    if not isinstance(entry, dict):
        return False
    for field in (*BIRTH_TEXT_FIELDS, "relation", "event"):
        value = entry.get(field)
        if not isinstance(value, str):
            continue
        for token in re.split(r"[^a-z]+", value.casefold()):
            if token and token in MARRIAGE_DATE_WORDS:
                return True
    return False


def entry_states_a_birth(entry: object) -> bool:
    """Does the entry carry an explicit birth of its own?"""
    return isinstance(entry, dict) and any(
        entry.get(field) for field in ENTRY_BIRTH_FIELDS
    )


def entry_date_event_kind(domain: object, entry: object, *, row: object = None) -> str:
    """Which event THIS ENTRY's own ``date`` field dates.

    :data:`A_LANDMARK_IS_DRAWN_AS_WHAT_IT_IS`. The domain's declared answer
    (:func:`date_event_kind`) stands for every entry that does not contradict
    it, so eight domains and every ordinary sibling entry are untouched. Only a
    declared ``birth`` is ever refined, and only three ways:

    * the entry STATES a birth of its own (:func:`entry_states_a_birth`) — it
      is a birth, whatever else it says;
    * the entry's own words name a marriage (:func:`entry_words_name_a_marriage`)
      — ``married``, because the record said so;
    * the entry's subject is exactly ONE couple (:func:`is_couple_subject`) —
      ``married``, because the one date a couple shares is the day they became
      one; and a collective that is not one couple
      (:func:`is_collective_subject` — ``grandparents``, an enumeration of
      three) is :data:`UNDISAMBIGUATED_EVENT_KIND`, a date whose event the
      record does not say.

    PURE and read at three seats — :func:`entry_claims` at filing,
    :func:`_attach_dates` and `temporal_timeline` at draw — so a vault that
    already holds the record heals on its next redraw with no migration, the
    way item 10's and item 16's rules do.
    """
    declared = date_event_kind(row if isinstance(row, dict) else domain_row_or_none(domain))
    if declared != "birth":
        return declared
    if entry_states_a_birth(entry):
        return declared
    if entry_words_name_a_marriage(entry):
        return MARRIAGE_EVENT_KIND
    subject = entry_subject_text(entry, row if isinstance(row, dict)
                                 else domain_row_or_none(domain), domain)
    if not subject:
        return declared
    if is_couple_subject(subject):
        return MARRIAGE_EVENT_KIND
    if is_collective_subject(subject):
        return UNDISAMBIGUATED_EVENT_KIND
    return declared


def wedding_mention_for(subject: object) -> str:
    """``"parents"`` -> ``"Parents' wedding"`` — what to CALL a couple's date.

    The node's human text comes from what somebody said about it
    (`temporal_timeline._node_what` reads the claims' ``event_mention``), and a
    landmark record says nothing: its claims carry no mention at all, so the
    old drawing fell back to the subject and the kind table and printed
    ``Parents's birth``. This is the entry's own words, made into the phrase the
    entry is: never ``<who>'s birth``, and never the event kind.
    """
    body = collapsed_text(subject)
    if not body:
        return ""
    titled = body[0].upper() + body[1:]
    tail = "'" if titled.casefold().endswith("s") else "'s"
    return f"{titled}{tail} wedding"


def landmark_date_readings(sources: object) -> dict:
    """``{source_id: {"event_kind", "declared_event_kind", "event_mention"}}``.

    One row per filed landmark record whose own ``date`` dates something other
    than the event its domain declares (:func:`entry_date_event_kind`). Records
    that agree with their domain are absent, so an ordinary vault gets an empty
    mapping and no reader does any work.

    PURE, over `load_landmark_sources`' list. It is the ARGUMENT shape the fold
    and the binder both read, for the reason `participation_kinds_by_telling`
    is one: a roster read inside a pure function is the drift this program
    exists to remove.
    """
    readings: dict[str, dict] = {}
    for source in sources or ():
        if not isinstance(source, dict):
            continue
        source_id = collapsed_text(source.get("source_id"))
        domain = collapsed_text(source.get("domain"))
        record = source.get("record")
        if not source_id or not domain or not isinstance(record, dict):
            continue
        row = domain_row_or_none(domain)
        declared = date_event_kind(row)
        kind = entry_date_event_kind(domain, record, row=row)
        if kind == declared:
            continue
        mention = ""
        if kind == MARRIAGE_EVENT_KIND:
            mention = wedding_mention_for(entry_subject_text(record, row, domain))
        readings[source_id] = {
            "event_kind": kind,
            "declared_event_kind": declared,
            "event_mention": mention,
        }
    return readings


def read_landmark_dates(claims: object, sources: object) -> list[dict]:
    """The claims, with every landmark date claim read as what its entry dates.

    :data:`A_LANDMARK_IS_DRAWN_AS_WHAT_IT_IS`, applied once so that every reader
    downstream — the grouping, the node label, the milestone rung, the binder's
    views — sees one answer. Returns a new list of new dicts; **no receipt is
    rewritten**, which is what makes this a reading and not a migration: the
    claim on disk still says what the importer read out of the record, and the
    drawing says what the record means.

    A claim is rewritten only when it is a ``date`` claim of a source
    :func:`landmark_date_readings` has a row for, and only when its stored
    ``event_kind`` is the one the domain DECLARED or the one the entry says — a
    span bound, or an alternate filed at a third kind, is left exactly as it is.
    Both spellings are accepted because both are real on disk: a receipt written
    before this release carries the declared kind and a receipt written after it
    carries the entry's, and the only difference the reading makes to the second
    one is the ``event_mention``, which is filled in only where the claim has
    none — the person's own words are never overwritten.
    """
    rows = [row for row in (claims or ()) if isinstance(row, dict)]
    # v360 (owner, 2026-09-25): the same seat reads a school's stay-inferred end
    # against his stated graduation (:data:`A_STATED_GRADUATION_ENDS_THE_SCHOOL`),
    # so the fold and the binder see one end.
    rows = read_school_ends(rows, sources)
    readings = landmark_date_readings(sources)
    if not readings:
        return rows
    out: list[dict] = []
    for row in rows:
        ref = row.get("source_ref")
        source_id = collapsed_text(ref.get("source_id")) if isinstance(ref, dict) else ""
        reading = readings.get(source_id)
        kind = collapsed_text(row.get("event_kind"))
        if (reading is None
                or collapsed_text(row.get("claim_type")) != "date"
                or kind not in (reading["declared_event_kind"], reading["event_kind"])):
            out.append(row)
            continue
        updated = dict(row)
        updated["event_kind"] = reading["event_kind"]
        if reading["event_mention"] and not collapsed_text(updated.get("event_mention")):
            updated["event_mention"] = reading["event_mention"]
        out.append(updated)
    return out


# --------------------------------------------------------------------------
# v360 (owner, 2026-09-25): a stated graduation ends the school
# --------------------------------------------------------------------------

#: THE RULE. "He went to Mountain View until he graduated in June 1999." The
#: 11th-12th telling of Mountain View was filed with the WILLIAMS STAY's bounds
#: (1997-06 to 2000-08, "from the dates of the Williams stay") by the old offer
#: reader, which read a school tenure off the home he lived in at the time; he
#: lived at Williams until his mission, a year after he graduated. His stated
#: high school graduation (1999, and "Mountain View High graduation", June
#: 1999) ENDS the school: a school end inferred from a stay never outruns a
#: graduation he stated. Read at DRAW time over the claims, so the vault heals
#: on its next publish with no migration; the filed claim still says what the
#: reader read.
A_STATED_GRADUATION_ENDS_THE_SCHOOL = (
    "a school tenure's end inferred from a residence stay never outruns the "
    "graduation he stated for that school; the stated graduation ends it"
)

#: The provenance clause the bounded end carries (an inferred clause, rendered
#: verbatim — never attributed to him as words he said).
GRADUATION_END_CLAUSE = "from your stated graduation from {school}"

_STAY_INFERRED_RE = re.compile(r"^from the dates of the .+ (?:stay|tenure)$", re.IGNORECASE)
_OWNER_SUBJECTS = frozenset({"self", "i", "me", "my", "myself", "narrator", "owner",
                             "author", "the author", "the narrator", "speaker"})
_NOT_HIS_GRADUATION_RE = re.compile(
    r"\b(?:dad|mom|father|mother|brother|sister|son|daughter|wife|husband|"
    r"grandpa|grandma|uncle|aunt|cousin|friend|he|she|they|his|her|their)\b",
    re.IGNORECASE)
#: The US school year's last month: a graduation stated only by its year ends
#: the school in June of that year (`chronology.GRADE_PARTS`' calendar).
SCHOOL_YEAR_END_MONTH = 6


def _is_stay_inferred(record: object) -> bool:
    parsed = chrono.from_dict(record)
    if parsed is None:
        return False
    return any(isinstance(item, dict) and collapsed_text(item.get("basis")) == "inferred"
               and _STAY_INFERRED_RE.match(collapsed_text(item.get("claim")))
               for item in parsed.provenance)


def stated_graduations(claims: object) -> list[tuple[str, chrono.DateRecord]]:
    """``[(the words, the record)]`` for every graduation HE stated. PURE.

    A ``date`` claim he said (claim basis ``explicit``, record basis
    ``stated``) whose kind is ``graduation`` or whose words say "graduat",
    about himself or about a school — never one whose subject is somebody else
    ("Dad's graduation").
    """
    found = []
    for claim in claims or ():
        if not isinstance(claim, dict) or collapsed_text(claim.get("claim_type")) not in ("date", "range"):
            continue
        if collapsed_text(claim.get("basis")) != "explicit":
            continue
        mention = collapsed_text(claim.get("event_mention"))
        subject = collapsed_text(claim.get("subject_mention"))
        text = f"{subject} {mention}".strip()
        if collapsed_text(claim.get("event_kind")) != "graduation" and "graduat" not in text.lower():
            continue
        if subject.lower() not in _OWNER_SUBJECTS and _NOT_HIS_GRADUATION_RE.search(subject):
            continue
        if _NOT_HIS_GRADUATION_RE.search(mention):
            continue
        record = chrono.from_dict(claim.get("temporal_value"))
        if record is None or record.basis != "stated" or not record.latest:
            continue
        found.append((text, record))
    return found


def graduation_month_for(record: object, graduations: object) -> str:
    """The month the owner's stated graduation from THIS school fell in, or ``""``.

    A graduation names the school when its words carry the school's own name
    (`landmark_identity.school_core`), or say "high school" of a high school
    (`landmark_identity.school_level`). Of the graduations that do, the finest
    wins; one stated only by its year is June of that year.
    """
    import landmark_identity as lid  # noqa: PLC0415 - avoids an import cycle

    core = set(lid.school_core(record))
    level = lid.school_level(record)
    matches = []
    for text, found in graduations or ():
        words = set(lid.words(text))
        names_it = bool(core) and core <= words
        says_level = level == "high" and {"high", "school"} <= words
        if names_it or says_level:
            matches.append(found)
    if not matches:
        return ""
    finest = min(matches, key=lambda r: (chrono.span_months(r) or 0, r.latest or ""))
    latest = collapsed_text(finest.latest)
    if len(latest) >= 7:
        return latest[:7]
    return f"{latest[:4]}-{SCHOOL_YEAR_END_MONTH:02d}"


#: v360 (owner, 2026-09-25): "I don't think I started Longfellow when I was
#: 2 or 1 year old… I bet if you go back and look at the residency doc, that's
#: a misinterpretation." His 15 September document lists "School: Longfellow
#: Elementary" under the Figers House block (August 1982 - June 1986) — the
#: house he lived in from his first year — and the offer reader gave the SCHOOL
#: the HOUSE's dates. A school tenure a stay dated never starts before he could
#: be in school: its start is read as no earlier than the August he was old
#: enough for pre-kindergarten (`chronology.school_year_start` - 1, the school
#: calendar every grade reading uses), and no later than the stay's end — the
#: only thing the document says is that it happened while he lived there.
A_SCHOOL_NEVER_STARTS_BEFORE_SCHOOL_AGE = (
    "a school tenure inferred from a stay never starts before the owner could "
    "be in school (pre-kindergarten, the August before kindergarten); a stay "
    "that began earlier dates only where he lived"
)
SCHOOL_AGE_START_CLAUSE = ("no earlier than pre-kindergarten ({month}); the "
                           "{stay} stay dates where you lived, not the school")


def _owner_birth_for(sources: object, claims: object) -> object:
    """The owner's stated birth: his `birth` landmark, else a stated birth claim
    about himself."""
    stated = owner_stated_birth(sources)
    if stated:
        return stated
    for claim in claims or ():
        if (isinstance(claim, dict) and collapsed_text(claim.get("event_kind")) == "birth"
                and collapsed_text(claim.get("subject_mention")).lower() in _OWNER_SUBJECTS
                and collapsed_text(claim.get("basis")) == "explicit"):
            record = chrono.from_dict(claim.get("temporal_value"))
            if record is not None and record.basis == "stated" and record.granularity == "day":
                return record.to_dict()
    return None


def read_school_ends(claims: object, sources: object) -> list[dict]:
    """:data:`A_STATED_GRADUATION_ENDS_THE_SCHOOL` and
    :data:`A_SCHOOL_NEVER_STARTS_BEFORE_SCHOOL_AGE`, applied to the claims. PURE.

    Returns a new list. A school source's stay-inferred ``ended`` claim that
    runs past his stated graduation from that school is READ as ending at the
    graduation's month; its stay-inferred ``started`` claim that falls before
    he could be in school is READ as the stretch from pre-kindergarten age to
    the stay's end. No receipt is rewritten.
    """
    rows = [row for row in (claims or ()) if isinstance(row, dict)]
    schools = {collapsed_text(source.get("source_id")): source.get("record")
               for source in sources or ()
               if isinstance(source, dict) and source.get("domain") == "schools"
               and isinstance(source.get("record"), dict)}
    if not schools:
        return rows
    graduations = stated_graduations(rows)
    kindergarten = chrono.school_year_start(_owner_birth_for(sources, rows))
    earliest_school = f"{kindergarten - 1:04d}-08" if kindergarten else ""
    if not graduations and not earliest_school:
        return rows
    out = []
    for row in rows:
        ref = row.get("source_ref")
        source_id = collapsed_text(ref.get("source_id")) if isinstance(ref, dict) else ""
        record = schools.get(source_id)
        kind = collapsed_text(row.get("event_kind"))
        if (record is None or collapsed_text(row.get("claim_type")) != "date"
                or kind not in (SPAN_START_EVENT_KIND, SPAN_END_EVENT_KIND)
                or not _is_stay_inferred(row.get("temporal_value"))):
            out.append(row)
            continue
        value = chrono.from_dict(row.get("temporal_value"))
        school = collapsed_text(record.get("name") or record.get("label")) or "school"
        if kind == SPAN_START_EVENT_KIND:
            out.append(_school_age_start(row, value, record, earliest_school))
            continue
        month = graduation_month_for(record, graduations) if graduations else ""
        if not month or value is None or not value.latest or value.latest[:7] <= month:
            out.append(row)
            continue
        bounded = chrono.DateRecord(
            best=month, earliest=month, latest=month, granularity="month",
            confidence="inferred", basis="anchor",
            provenance=({"basis": "inferred",
                         "claim": GRADUATION_END_CLAUSE.format(school=school)},))
        out.append({**row, "temporal_value": _read_as(bounded, row)})
    return out


#: A READ bound keeps the value it was FILED with, inside its own provenance
#: entry (the one part of a claim every validator carries through), because a
#: node id is the filing's and never the reading's: an episode's discriminator
#: (:func:`_span_start_value`) reads it, so reading Longfellow's start as
#: school age moves the drawing and not the node.
FILED_VALUE_KEY = "filed_value"


def _read_as(record: object, row: dict) -> dict:
    value = record.to_dict()
    value["provenance"] = [dict(item, **{FILED_VALUE_KEY: row.get("temporal_value")})
                           for item in value.get("provenance") or ()]
    return value


def filed_value_of(value: object) -> object:
    """The value a READ bound was filed with, or the value itself."""
    for item in (value or {}).get("provenance") or () if isinstance(value, dict) else ():
        if isinstance(item, dict) and isinstance(item.get(FILED_VALUE_KEY), dict):
            return item[FILED_VALUE_KEY]
    return value


def _school_age_start(row: dict, value: object, record: dict, earliest_school: str) -> dict:
    """One stay-inferred school START, read against his school age."""
    if not earliest_school or value is None or not value.earliest \
            or value.earliest[:7] >= earliest_school:
        return row
    span = record.get("span") if isinstance(record.get("span"), dict) else {}
    stay_end = chrono.from_dict(span.get("end"))
    latest = (stay_end.latest or "")[:7] if stay_end is not None else ""
    if not latest or latest < earliest_school:
        # The whole stay ended before he could be in school: nothing to read.
        return row
    stay = ""
    for item in value.provenance:
        match = _STAY_INFERRED_RE.match(collapsed_text(item.get("claim")))
        if match:
            stay = collapsed_text(item.get("claim"))[len("from the dates of the "):-len(" stay")]
            break
    bounded = chrono.DateRecord(
        best=f"{earliest_school}/{latest}" if latest != earliest_school else earliest_school,
        earliest=earliest_school, latest=latest,
        granularity="range" if latest != earliest_school else "month",
        confidence="inferred", basis="anchor",
        provenance=({"basis": "inferred",
                     "claim": SCHOOL_AGE_START_CLAUSE.format(month=earliest_school,
                                                             stay=stay or "home's")},))
    return {**row, "temporal_value": _read_as(bounded, row)}


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
    # v356: every OTHER singleton is the owner's too, for the reason `birth`
    # is — `collection: singleton` is "one entry and no subject of its own"
    # (questions.yaml), so the domain word would read as a person named
    # "baptism". The owner's baptism is the owner's.
    if isinstance(row, dict) and row.get("collection") == "singleton":
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
    event_mention: str = "",
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
    named = {"event_mention": event_mention} if collapsed_text(event_mention) else {}
    return validate_temporal_claim(
        {
            "source_ref": source_ref,
            "source_kind": "import",
            "claim_type": "date",
            "subject_mention": mention,
            **subject_annotation,
            **named,
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
    # v345, :data:`A_LANDMARK_IS_DRAWN_AS_WHAT_IT_IS`. The ENTRY's own kind, not
    # only the domain's: a `family` entry whose subject is a couple dates their
    # wedding, and a newly filed record says so on its own receipt.
    kind = entry_date_event_kind(name, entry, row=row)
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

    # v345. A re-read entry is NAMED on its own receipt, so a record filed from
    # today forward needs no read-side help to be drawn as the thing it is.
    # `event_mention` is outside `derive_claim_id`'s digest, so this adds a name
    # and changes no identity.
    event_mention = (wedding_mention_for(entry_subject_text(entry, row, name))
                     if kind == MARRIAGE_EVENT_KIND else "")
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
            event_mention=event_mention if event_kind == kind else "",
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


def load_landmark_sources(vault_root: str | Path, *,
                          apply_merges: bool = True) -> list[dict]:
    """Every promoted landmark record, in filing order.

    **One place, one landmark** (`landmark_identity.ONE_PLACE_ONE_LANDMARK`,
    owner 2026-09-25). Every filed merge record (:func:`file_landmark_merge`)
    is applied HERE, the one seat every reader of landmark entries goes
    through: the drawing, the fold's participation episodes, the write seat's
    provenance guard. A record merged INTO an entry reads as a telling of that
    entry. Its ``entry_key`` is the target's, ``merged_into`` names the source
    of the stay it joined, and ``merged_from_key`` keeps its own. A record
    filed as a MENTION (a city or state he has stays in, someone else's
    residence) is not an entry at all and is left out. The promoted source
    itself is never rewritten. ``apply_merges=False`` is the raw filing, which
    only :func:`next_ordinal` wants.

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
    if apply_merges:
        rows = apply_landmark_merges(rows, load_landmark_merges(vault_root))
    return rows


# --------------------------------------------------------------------------
# One place, one landmark: the merge record (owner ruling 2026-09-25)
# --------------------------------------------------------------------------
#
# A duplicate the write seat catches is filed as a telling of the entry it
# names; one that landed before the rule existed is folded by a merge record
# filed by `lifehug.py landmark-fold-duplicates`. Both are the same record,
# because a merge is a decision ABOUT a promoted source and the source itself
# is immutable, the way `chain_closure` records a decision beside the entries
# rather than editing them. `sources/landmarks/merges/` sits under the
# registered `sources/landmarks` directory (see the closure note below).

MERGE_SOURCES_DIR = f"{LANDMARK_SOURCES_DIR}/merges"
LANDMARK_MERGE_SOURCE_TYPE = "landmark_merge"

#: A merge record's two kinds: INTO an entry, or AS A MENTION of his stays.
MERGE_INTO_ENTRY = "into_entry"
MERGE_AS_MENTION = "mention"
MERGE_KINDS = (MERGE_INTO_ENTRY, MERGE_AS_MENTION)


def landmark_merge_digest(*, merged_source_id: object, kind: object,
                          into_entry_key: object = None,
                          into_source_id: object = None,
                          pin_stay: bool = True) -> str:
    """The sha256 of what one merge ASSERTS, so a re-filed merge finds itself."""
    payload = {
        "merged_source_id": collapsed_text(merged_source_id),
        "kind": collapsed_text(kind),
        "into_entry_key": collapsed_text(into_entry_key) or None,
        "into_source_id": collapsed_text(into_source_id) or None,
    }
    if not pin_stay:
        payload["pin_stay"] = False
    return store.payload_sha256(json.dumps(payload, sort_keys=True,
                                           separators=(",", ":")))


def landmark_merge_relative_path(digest: str) -> str:
    return f"{MERGE_SOURCES_DIR}/merge-{collapsed_text(digest)[:store.FILENAME_DIGEST_LENGTH]}.md"


def file_landmark_merge(
    vault_root: str | Path,
    *,
    domain: object,
    merged_source_id: object,
    kind: object = MERGE_INTO_ENTRY,
    into_entry_key: object = None,
    into_source_id: object = None,
    reason: object = None,
    mention: object = None,
    pin_stay: bool = True,
    now: object = None,
) -> dict:
    """File one merge decision; idempotent on :func:`landmark_merge_digest`.

    ``pin_stay`` (the default) joins the STAY ``into_source_id`` is a telling
    of. ``False`` joins the identity only: a dated telling whose stretch falls
    in none of the place's stays is a stay of its own at that place.

    ``kind`` is :data:`MERGE_INTO_ENTRY` (``into_entry_key`` and the
    ``into_source_id`` of the stay it joins are required) or
    :data:`MERGE_AS_MENTION` (the record names a city or state he has stays
    in, or is someone else's residence, and draws nothing). ``reason`` is the
    `landmark_identity` rule that matched. Returns
    :func:`read_landmark_merge`'s shape.
    """
    verb = collapsed_text(kind)
    if verb not in MERGE_KINDS:
        raise LandmarkProjectionError("landmark_merge_kind_unknown",
                                      f"unknown merge kind: {kind!r}")
    merged = collapsed_text(merged_source_id)
    if not merged:
        raise LandmarkProjectionError("landmark_merge_source_required",
                                      "a merge names the source it merges")
    into_key = collapsed_text(into_entry_key)
    into_source = collapsed_text(into_source_id)
    if verb == MERGE_INTO_ENTRY and not (into_key and into_source):
        raise LandmarkProjectionError(
            "landmark_merge_target_required",
            "a merge into an entry names its entry key and a source of its stay")
    digest = landmark_merge_digest(merged_source_id=merged, kind=verb,
                                   into_entry_key=into_key,
                                   into_source_id=into_source,
                                   pin_stay=pin_stay)
    relative = landmark_merge_relative_path(digest)
    heading = (f"{collapsed_text(domain)}: {merged} is {into_key}"
               if verb == MERGE_INTO_ENTRY else
               f"{collapsed_text(domain)}: {merged} is a mention")
    prose = collapsed_text(reason) or heading
    payload = f"# {heading}\n\n{prose}\n"
    frontmatter: dict = {
        "title": heading[:120],
        "type": LANDMARK_MERGE_SOURCE_TYPE,
        "source_id": f"landmark_merge:merge-{digest[:store.FILENAME_DIGEST_LENGTH]}",
        "source_medium": "rule",
        "domain": collapsed_text(domain),
        "merged_source_id": merged,
        "merge_kind": verb,
        "captured_at": normalized_timestamp(now, error=LandmarkProjectionError),
        "visibility": "owner_only",
        "immutable": True,
        "schema_version": SCHEMA_VERSION,
        "source_path": relative,
        "content_sha256": store.payload_sha256(payload),
    }
    if into_key:
        frontmatter["into_entry_key"] = into_key
    if into_source:
        frontmatter["into_source_id"] = into_source
    if collapsed_text(mention):
        frontmatter["mention"] = collapsed_text(mention)
    if not pin_stay:
        frontmatter["pin_stay"] = False
    store.create_or_keep(
        vault_root, relative, f"{store.format_frontmatter(frontmatter)}\n\n{payload}"
    )
    record = read_landmark_merge(vault_root, relative)
    if record is None:  # pragma: no cover - the create above guarantees it
        raise LandmarkProjectionError("landmark_merge_malformed",
                                      f"{relative} vanished during filing")
    return record


def read_landmark_merge(vault_root: str | Path, relative: str) -> dict | None:
    """One merge record back, or ``None`` when it is not one of ours."""
    text = store.read_store_text(vault_root, relative)
    if text is None:
        return None
    metadata, _ = store.split_frontmatter(text)
    if not metadata or metadata.get("type") != LANDMARK_MERGE_SOURCE_TYPE:
        return None
    merged = collapsed_text(metadata.get("merged_source_id"))
    kind = collapsed_text(metadata.get("merge_kind"))
    if not merged or kind not in MERGE_KINDS:
        return None
    return {
        "source_id": collapsed_text(metadata.get("source_id")),
        "domain": collapsed_text(metadata.get("domain")),
        "merged_source_id": merged,
        "kind": kind,
        "into_entry_key": collapsed_text(metadata.get("into_entry_key")),
        "into_source_id": collapsed_text(metadata.get("into_source_id")),
        "mention": collapsed_text(metadata.get("mention")),
        "pin_stay": metadata.get("pin_stay") is not False,
        "captured_at": collapsed_text(metadata.get("captured_at")),
        "source_path": relative,
    }


def load_landmark_merges(vault_root: str | Path) -> list[dict]:
    """Every filed merge record, sorted by its own source id (a total order)."""
    root = _root(vault_root)
    base = store.store_path(root, MERGE_SOURCES_DIR)
    if not base.is_dir():
        return []
    rows = []
    for path in sorted(base.glob("merge-*.md")):
        if path.is_symlink() or not path.is_file():
            continue
        record = read_landmark_merge(vault_root, path.relative_to(root).as_posix())
        if record is not None:
            rows.append(record)
    rows.sort(key=lambda row: row["source_id"])
    return rows


def apply_landmark_merges(rows: object, merges: object) -> list[dict]:
    """The filed merges applied to :func:`load_landmark_sources`' rows. PURE.

    A merge naming a source that is not filed, or a target that is not filed,
    is ignored rather than raised on: the write seat files the merge BEFORE
    the source it names, so a crash between the two leaves an inert record.
    Two merges for one source: the first by merge id wins, deterministically.
    A chain (A into B, B into C) is followed to its end.
    """
    sources = [dict(row) for row in rows or () if isinstance(row, dict)]
    by_id = {row["source_id"]: row for row in sources}
    decided: dict[str, dict] = {}
    for merge in merges or ():
        if not isinstance(merge, dict):
            continue
        merged = merge.get("merged_source_id")
        if merged not in by_id or merged in decided:
            continue
        if (merge.get("kind") == MERGE_INTO_ENTRY
                and merge.get("into_source_id") not in by_id):
            continue
        decided[merged] = merge

    def target_of(source_id: str) -> str:
        seen = {source_id}
        current = source_id
        while current in decided and decided[current]["kind"] == MERGE_INTO_ENTRY:
            nxt = decided[current]["into_source_id"]
            if nxt in seen:
                break
            seen.add(nxt)
            current = nxt
        return current

    out = []
    for row in sources:
        merge = decided.get(row["source_id"])
        if merge is None:
            out.append(row)
            continue
        if merge["kind"] == MERGE_AS_MENTION:
            continue
        into = target_of(row["source_id"])
        if into == row["source_id"] or into not in by_id \
                or by_id[into]["domain"] != row["domain"]:
            out.append(row)
            continue
        row["merged_from_key"] = row["entry_key"]
        row["entry_key"] = by_id[into]["entry_key"]
        row["merged_into"] = into
        row["merge_pinned"] = bool(merge.get("pin_stay", True))
        row["merge_id"] = merge["source_id"]
        out.append(row)
    return out


def stay_source_for(sources: object, *, domain: str, entry_key: str,
                    target: object = None, record: object = None) -> str:
    """The source id of ONE stay of an identity, for a merge to join. PURE.

    The stay a dated ``record`` falls in when exactly one does
    (`landmarks_interaction.same_landmark_stay`); otherwise the stay whose
    drawn span is ``target``'s; otherwise the identity's first stay. ``""``
    when the identity has no source at all.
    """
    rows = [source for source in (sources or ())
            if isinstance(source, dict) and source.get("domain") == domain
            and source.get("entry_key") == entry_key]
    if not rows:
        return ""
    slots = stay_slots(sources)
    folded: dict[int, dict] = {}
    first: dict[int, str] = {}
    for source in rows:
        slot = (slots.get(source["source_id"]) or (domain, entry_key, 0))[2]
        folded[slot] = landmarks_interaction.merge_landmark_entry(
            folded.get(slot), source.get("record"))
        first.setdefault(slot, source["source_id"])
    row = domain_row_or_none(domain)
    if isinstance(record, dict) and landmarks_interaction.entry_stay_interval(record):
        fits = [slot for slot, entry in sorted(folded.items())
                if landmarks_interaction.entry_stay_interval(entry)
                and landmarks_interaction.same_landmark_stay(entry, record, row)]
        if len(fits) == 1:
            return first[fits[0]]
    want = landmarks_interaction.entry_stay_interval(target) if isinstance(target, dict) else None
    if want:
        for slot, entry in sorted(folded.items()):
            have = landmarks_interaction.entry_stay_interval(entry)
            if have and (have["earliest"], have["latest"]) == (want["earliest"], want["latest"]):
                return first[slot]
    dated = [slot for slot, entry in sorted(folded.items())
             if landmarks_interaction.entry_stay_interval(entry)]
    return first[(dated or sorted(folded))[0]]


#: The domains whose duplicates the fold looks for (`landmark_identity.same_entry`).
FOLDABLE_DOMAINS = ("residences", "schools", "work", "children", "family",
                    "losses", "partnerships")


def duplicate_fold_plan(sources: object, *, owner_names: object = (),
                        active_source_ids: object = None) -> list[dict]:
    """Every existing duplicate, and the dated entry it folds into. PURE.

    `landmark_identity.ONE_PLACE_ONE_LANDMARK` applied to what landed BEFORE
    the write seat knew it. The unit is ONE drawn entry (a stay slot and all
    its tellings, merges already applied). An UNDATED entry that
    `landmark_identity.decide` says is the same thing as another entry of its
    domain folds into that entry's stay; an undated residence that names only
    a city or state he has stays in, or someone else's, folds as a mention. A
    dated entry is never folded away: two dated readings of one thing are a
    contradiction to show, not a duplicate to hide.

    ``[{"domain", "kind", "source_ids", "from", "into", "into_entry_key",
    "into_source_id", "reason", "mention"}]`` in filing order.
    """
    import landmark_identity as lid  # noqa: PLC0415

    rows = [row for row in (sources or ()) if isinstance(row, dict)]
    if active_source_ids is not None:
        # Only what is DRAWN: a source whose identity claim a correction
        # already retired is not an entry to fold, nor one to fold into.
        standing = set(active_source_ids)
        rows = [row for row in rows if row["source_id"] in standing]
    slots = stay_slots(rows)
    groups: dict[tuple, dict] = {}
    order: list[tuple] = []
    for source in rows:
        domain = source["domain"]
        if domain not in FOLDABLE_DOMAINS or not_a_landmark(domain, source.get("record")):
            continue
        key = slots.get(source["source_id"]) or (domain, source["entry_key"], 0)
        if key not in groups:
            groups[key] = {"entry": {}, "source_ids": [], "merged": False}
            order.append(key)
        group = groups[key]
        group["entry"] = landmarks_interaction.merge_landmark_entry(
            group["entry"], skeleton_of(source["record"]) if source.get("merged_into")
            else source["record"])
        group["source_ids"].append(source["source_id"])
    plan: list[dict] = []
    by_domain: dict[str, list[tuple]] = {}
    for key in order:
        by_domain.setdefault(key[0], []).append(key)
    residences = [groups[key]["entry"] for key in by_domain.get("residences", ())]
    for key in order:
        domain, entry_key, _slot = key
        group = groups[key]
        entry = group["entry"]
        # DATED is what the drawing dates: a date or a span. A bare "year"
        # word the rule read no claim from dates nothing.
        if entry.get("date") or entry.get("span"):
            continue
        others = [groups[other]["entry"] for other in by_domain[domain] if other != key]
        decision = lid.decide(
            domain, entry, others,
            residences=[row for row in residences if row is not entry],
            owner_names=owner_names,
            key_of=lambda row, _d=domain: landmarks_interaction.landmark_entry_key(
                row, domain_row_or_none(_d)),
        )
        verdict = decision["decision"]
        if verdict == lid.FILE_NEW:
            continue
        target = decision.get("target")
        if target is None:
            # A mention is decided per telling: "Mesa" said by him is a city
            # mention, "Mesa" said of "they" is not his residence at all.
            by_id = {row["source_id"]: row for row in rows}
            for source_id in group["source_ids"]:
                own = lid.decide(
                    domain, by_id[source_id]["record"], others,
                    residences=[row for row in residences if row is not entry],
                    owner_names=owner_names)
                if own["decision"] != lid.NOT_WRITTEN or own.get("target") is not None:
                    own = decision
                plan.append({"domain": domain, "kind": MERGE_AS_MENTION,
                             "source_ids": [source_id],
                             "from": lid.entry_identity(by_id[source_id]["record"]),
                             "into": "", "into_entry_key": "", "into_source_id": "",
                             "reason": own["reason"],
                             "mention": ":".join(own.get("level") or ())})
            continue
        target_key = landmarks_interaction.landmark_entry_key(
            target, domain_row_or_none(domain))
        into = stay_source_for(rows, domain=domain, entry_key=target_key,
                               target=target)
        if not into or into in group["source_ids"]:
            continue
        plan.append({"domain": domain, "kind": MERGE_INTO_ENTRY,
                     "source_ids": list(group["source_ids"]),
                     "from": lid.entry_identity(entry),
                     "into": lid.entry_identity(target),
                     "into_entry_key": target_key, "into_source_id": into,
                     "reason": decision.get("match") or decision["reason"],
                     "mention": ""})
    return plan


def new_skeleton_only(record: object, entry: object) -> dict:
    """What a MERGED telling adds to the entry it joined: the keys the entry
    does not have yet, and its dates. `landmark_identity.new_content`'s
    draw-time twin: a merged record never respells the entry he gave."""
    if not isinstance(record, dict):
        return {}
    held = entry if isinstance(entry, dict) else {}
    return {key: value for key, value in record.items()
            if (key not in held and key not in _DATE_GRAIN_WORDS)
            or key in ("date", "span")}


#: A merged telling's raw date WORDS never respell the entry it joined: its
#: dates reach the entry as claims, reconciled with his, or not at all.
_DATE_GRAIN_WORDS = frozenset({"year", "month", "day", "birth"})


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
        # ONE PLACE, ONE LANDMARK: a merged telling joins the stay its merge
        # record names, never a new slot, which is what an undated telling of
        # a place he lived at twice would otherwise open.
        pinned = (slots.get(collapsed_text(source.get("merged_into")))
                  if source.get("merge_pinned", True) else None)
        if pinned is not None and pinned[:2] == (domain, entry_key):
            chosen = pinned[2]
            held[chosen] = landmarks_interaction.merge_landmark_entry(
                held[chosen], new_skeleton_only(record, held[chosen]))
            slots[source_id] = (domain, entry_key, chosen)
            continue
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
        #: The subset of `node_aliases` a MERGE made (one place, one
        #: landmark): the id a duplicate was drawn at, onto the entry he gave.
        #: `temporal_timeline._group_claims` carries every claim still holding
        #: one of these ids onto the target, v350's rule for a moved id.
        self.merge_aliases: dict[str, str] = {}
        #: ``node id -> [promoted source ids]`` — which tellings each episode
        #: folds, so a reader can ask what a stay's own record SAYS (its city,
        #: its address) without re-deriving the grouping.
        self.sources_of_node: dict[str, list[str]] = {}
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
                "merged_into": collapsed_text(row.get("merged_into")),
                "merge_pinned": bool(row.get("merge_pinned", True)),
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
                "own_subject": subject,
                "merged_into": entry["merged_into"],
                "merge_pinned": entry["merge_pinned"],
            })

        # ONE PLACE, ONE LANDMARK (`landmark_identity.ONE_PLACE_ONE_LANDMARK`).
        # A telling merged into an entry he gave is a telling OF that entry,
        # so it takes that entry's subject and lands on its episode instead of
        # minting one under its own words. The id it used to be drawn at is
        # published below as an alias, so no card, session or answer that
        # named it is lost.
        subject_of = {row["source_id"]: row["subject"] for row in tellings
                      if not row["merged_into"]}
        for row in tellings:
            target = subject_of.get(row["merged_into"]) if row["merged_into"] else None
            if target and target != row["subject"]:
                row["subject"] = target
                row["group"] = (row["group"][0], target)

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

        # A merged telling is walked AFTER every telling of its own, so the
        # episode's seed is always the entry he gave, never the copy.
        for row in sorted(tellings, key=lambda item: (bool(item["merged_into"]),
                                                      item["source_id"])):
            discriminator = chain_start.get(row["source_id"], "")
            if row["merged_into"] and row["merge_pinned"]:
                # The stay it was merged into decides the episode: an undated
                # telling of a place he lived at twice joins the stay its merge
                # record names instead of becoming a third, undated one.
                # A merged telling that states its own start keeps the chain
                # that start falls in, which is the stay its dates say.
                discriminator = ((discriminator if row["start"] else "")
                                 or chain_start.get(row["merged_into"], "")
                                 or row["merged_into"])
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
            if row["merged_into"]:
                for former in (row["start"], row["source_id"]):
                    if not former:
                        continue
                    try:
                        was = ident.derive_episode_ref(
                            event_kind=row["kind"],
                            subject_mention=row["own_subject"],
                            discriminator=former,
                        )
                    except ident.IdentityResolutionError:
                        continue
                    if was != node_id:
                        self.node_aliases[was] = node_id
                        self.merge_aliases[was] = node_id
                unplaced = node_id in self.unplaced or (
                    discriminator == row["merged_into"]
                    and not chain_start.get(row["merged_into"]))
            if not unplaced and not row["merged_into"]:
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
            self.sources_of_node.setdefault(node_id, []).append(row["source_id"])
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
        value = ident.episode_discriminator(filed_value_of(claim.get("temporal_value")))
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
                             owner_names: object = (), with_refs: bool = False) -> dict:
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

    ``with_refs`` (v360, owner 2026-09-25, the edit forms) stamps each drawn entry
    with ``ref`` — ``{"domain", "entry_key", "slot"}``, the interval-aware key
    it was drawn under (:func:`stay_slots`) — and ``source_ids``, the tellings
    behind it, so a host can name ONE stay back to `landmark_edit`. Off by
    default: ``state/landmarks.json`` is drawn without them and stays
    byte-identical.
    """
    active = {
        row.get("claim_id")
        for row in store.active_claims(active_index if isinstance(active_index, dict) else {})
    }
    by_source: dict[str, list[dict]] = {}
    standing = [row for row in (active_index or {}).get("claims") or ()
                if isinstance(row, dict) and row.get("claim_id") in active]
    # v360 (owner, 2026-09-25): :data:`A_STATED_GRADUATION_ENDS_THE_SCHOOL`.
    for row in read_school_ends(standing, sources):
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
        groups[key]["skeletons"].append(
            (skeleton_of(source["record"]),
             bool(source.get("merged_into")) and source.get("merge_pinned", True)))
        groups[key]["claims"].extend(claims)
        groups[key].setdefault("source_ids", []).append(source["source_id"])

    domains: dict[str, list[dict]] = {}
    for key in order:
        domain = key[0]
        group = groups[key]
        entry: dict = {}
        for skeleton, merged in group["skeletons"]:
            if merged:
                skeleton = new_skeleton_only(skeleton, entry)
            entry = landmarks_interaction.merge_landmark_entry(entry, skeleton)
        entry = skeleton_of(entry)
        row = domain_row_or_none(domain)
        _attach_dates(entry, group["claims"], row=row, domain=domain)
        # v360 (owner, 2026-09-25): :data:`HIS_WORD_PRESENT_IS_ONGOING`.
        if stated_as_ongoing(entry, row):
            entry["ongoing"] = True
        if with_refs:
            entry["ref"] = {"domain": domain, "entry_key": key[1], "slot": key[2]}
            entry["source_ids"] = list(group.get("source_ids") or ())
        domains.setdefault(domain, []).append(entry)

    # v360 (owner, 2026-09-25): :data:`ONE_SCHOOL_IS_ONE_CONTINUOUS_TENURE`.
    if domains.get("schools"):
        domains["schools"] = chained_school_tenures(domains["schools"])
    return {"version": LANDMARKS_SCHEMA_VERSION, "domains": domains}


#: v360 (owner, 2026-09-25): "Longfellow shows as three entries and should be
#: one continuous school span." His document gave Longfellow under three
#: consecutive homes ("School: Longfellow Elementary", then "PK and 1st grade",
#: then "2nd grade"), and Mountain View under two ("9th and 10th", "11th and
#: 12th"). Consecutive stretches of ONE school — overlapping or abutting within
#: `landmarks_interaction.SEQUENCE_ENTRY_ABUT_MONTHS` — are one tenure: its span
#: runs from the first stretch's start to the last stretch's end and its grades
#: are every stretch's, in order. The participation episode already chains them
#: this way (`_chain_starts`); this is the landmark list agreeing with it. A
#: school he went back to years later is still a second tenure.
ONE_SCHOOL_IS_ONE_CONTINUOUS_TENURE = (
    "consecutive stretches of one school are one tenure, from the first "
    "stretch's start to the last one's end, carrying every stretch's grades"
)


def chained_school_tenures(entries: list[dict]) -> list[dict]:
    """:data:`ONE_SCHOOL_IS_ONE_CONTINUOUS_TENURE` over one drawn `schools`
    list. PURE; order is the first stretch's filing position."""
    row = domain_row_or_none("schools")
    abut = landmarks_interaction.SEQUENCE_ENTRY_ABUT_MONTHS
    keyed: dict[str, list[int]] = {}
    for position, entry in enumerate(entries):
        if isinstance(entry, dict) and landmarks_interaction.entry_stay_interval(entry):
            keyed.setdefault(landmarks_interaction.landmark_entry_key(entry, row), []).append(position)
    replaced: dict[int, dict] = {}
    dropped: set[int] = set()
    for positions in keyed.values():
        if len(positions) < 2:
            continue
        ordered = sorted(positions, key=lambda at: (
            landmarks_interaction.entry_stay_interval(entries[at])["earliest"], at))
        chains: list[list[int]] = []
        running_end = None
        for at in ordered:
            interval = landmarks_interaction.entry_stay_interval(entries[at])
            if chains and running_end is not None:
                gap = chrono.gap_months({"earliest": running_end, "latest": running_end},
                                        interval)
                if gap is None or gap <= abut:
                    chains[-1].append(at)
                    running_end = max(running_end, interval["latest"])
                    continue
            chains.append([at])
            running_end = interval["latest"]
        for chain in chains:
            if len(chain) < 2:
                continue
            replaced[min(chain)] = _one_tenure([entries[at] for at in chain])
            dropped.update(at for at in chain if at != min(chain))
    return [replaced.get(at, entry) for at, entry in enumerate(entries) if at not in dropped]


def _one_tenure(stretches: list[dict]) -> dict:
    """Consecutive stretches of one school, as the one tenure they are."""
    merged: dict = {}
    for stretch in stretches:
        for key, value in stretch.items():
            if key in ("span", landmarks_interaction.SPAN_ALTERNATES_KEY, "grades"):
                continue
            merged.setdefault(key, value)
    grades = []
    for stretch in stretches:
        text = collapsed_text(stretch.get("grades"))
        if text and text not in grades:
            grades.append(text)
    if grades:
        merged["grades"] = "; ".join(grades)
    first, last = stretches[0].get("span") or {}, None
    for stretch in stretches:
        end = (stretch.get("span") or {}).get("end")
        record = chrono.from_dict(end)
        if record is not None and (last is None or (record.latest or "") >= (
                chrono.from_dict(last).latest or "")):
            last = end
    span = {"start": first.get("start")} if first.get("start") else {}
    if last:
        span["end"] = last
    merged["span"] = span
    alternates: dict = {}
    for stretch in stretches:
        for bound, rows in (stretch.get(landmarks_interaction.SPAN_ALTERNATES_KEY) or {}).items():
            for rec in rows or ():
                if rec not in alternates.setdefault(bound, []):
                    alternates[bound].append(rec)
    if alternates:
        merged[landmarks_interaction.SPAN_ALTERNATES_KEY] = alternates
    return merged


#: v360 (owner, 2026-09-25). "It's still my company and it's still ongoing." His
#: work history says Etherfuse ran "May 2022 - Present" and "I still work there
#: today", and the reader that filed it kept the start and dropped the
#: "Present", so the entry read as a tenure with an UNKNOWN end
#: (``missing_end``) instead of an open one. A span whose own stated start
#: carries his words for "still going" (``- Present``, ``to now``, ``still
#: there``) is ``ongoing`` — the flag residences already carry
#: (`landmarks_interaction.validate_landmark`) — and nothing else is: a start
#: with no end and no such words stays a missing end, so an undated end is
#: never guessed open.
HIS_WORD_PRESENT_IS_ONGOING = (
    "a span whose stated start is told as running to the present "
    "('May 2022 - Present', 'still work there today') is ongoing; a start "
    "with no end and no such words is a missing end, never an ongoing one"
)
_ONGOING_WORDS_RE = re.compile(
    r"(?:[-–—]|\bto\b|\buntil\b|\bthrough\b|\btill\b)\s*(?:the\s+)?"
    r"(?:present|now|today|current(?:ly)?|ongoing)\b"
    r"|\bstill\s+(?:work|working|there|ongoing|going|running|mine|my\s+company)\b"
    r"|\b(?:is|it's|it’s)\s+(?:still\s+)?ongoing\b",
    re.IGNORECASE)


def stated_as_ongoing(entry: object, row: object = None) -> bool:
    """:data:`HIS_WORD_PRESENT_IS_ONGOING` for one drawn entry. PURE."""
    if not isinstance(entry, dict) or not landmarks_interaction.is_sequence(row):
        return False
    span = entry.get("span") if isinstance(entry.get("span"), dict) else {}
    if not span.get("start") or span.get("end"):
        return False
    if entry.get("ongoing") is False:
        return False
    records = [span.get("start")] + list(
        (entry.get(landmarks_interaction.SPAN_ALTERNATES_KEY) or {}).get("start") or ())
    for record in records:
        for item in (record or {}).get("provenance") or ():
            if not isinstance(item, dict):
                continue
            if collapsed_text(item.get("basis")) in chrono.VERBATIM_PROVENANCE_BASES:
                continue
            if _ONGOING_WORDS_RE.search(collapsed_text(item.get("claim"))):
                return True
    return False


def _attach_dates(entry: dict, claims: list[dict], *, row: object,
                  domain: object = None) -> None:
    """Reconcile one group's dated claims onto the entry it belongs to.

    v345: the bucket is the ENTRY's own kind (:func:`entry_date_event_kind`),
    read off the merged skeleton. A vault whose ``family`` entry is a couple's
    wedding holds its date claim at ``birth`` — the kind the importer read from
    the domain — and reading the claim as the wedding it is without moving this
    bucket with it would drop the date out of the drawing altogether. Both
    spellings are accepted, so an already-corrected receipt and a legacy one
    land in the same bucket.
    """
    kind = entry_date_event_kind(domain, entry, row=row) if domain else date_event_kind(row)
    declared = date_event_kind(row)
    buckets: dict[str, list[dict]] = {}
    for claim in claims:
        if claim.get("claim_type") != "date":
            continue
        record = chrono.from_dict(claim.get("temporal_value"))
        if record is None:
            continue
        buckets.setdefault(str(claim.get("event_kind") or ""), []).append(record.to_dict())

    dated = list(buckets.get(kind) or ())
    if declared != kind:
        dated += [row for row in (buckets.get(declared) or ()) if row not in dated]
    best, alternates = _reconciled(dated)
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
    rows = load_landmark_sources(vault_root, apply_merges=False)
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


# --------------------------------------------------------------------------
# v360 (owner, 2026-09-25): a record filed in the wrong domain is refiled
# --------------------------------------------------------------------------
#
# THE INCIDENTS, the owner's vault (all three filed by the conversation turn
# engine's `landmark-record` reflect decision, `maintenance:reflect:…`):
#
# * `landmark:entry-6b91f918c2f133a22d1e271f` — schools: "Katie Ann Merrill",
#   2006. His wife's name, filed as a SCHOOL: the model read "Katie graduated
#   esthetician school in 2006" and put the graduate where the school goes. The
#   moment itself ("Katie graduates esthetician school", 2006) is already on
#   the timeline from his telling (`answers/L13.md` and its listeners).
# * `landmark:entry-a0123eb89528c71a613ce6e2` — work: "SAFE conversion", one
#   day, 2025-08-28 ("SAFE conversion terms negotiation"). "It is signing a
#   paper, so that should be removed." A dated EVENT at his company filed as a
#   JOB.
# * `landmark:entry-94b40f96…` and `landmark:entry-a512fa5b…` — partnerships:
#   "Castle Island Ventures" (subject "Etherfuse"), 2024-04 and 2025-05. A
#   venture fund that passed on Etherfuse twice, filed as a PARTNERSHIP.
#   Partnerships are personal (owner, 2026-09-25): a company or a fund is never
#   one.
#
# THE RULE. :func:`misfiled_landmark` names why a record is not an entry of its
# domain (a closed vocabulary), and a REFILE puts it where it belongs, the way
# the substrate records every correction: its claims are SUPERSEDED (a durable
# correction, scope ``landmarks/<domain>``, exactly :func:`retire_entry`'s) and
# — for an event — what is true instead is filed as its own act: a refile
# record under ``sources/landmarks/refiles/`` and ONE receipt over it holding
# the ordinary moment (``event_kind: moment``) at the record's own dates.
# ONE definition, two seats: `timeline.save_landmark` refiles a new record the
# moment it lands, and `lifehug.py landmark-refile --apply` refiles what landed
# before the rule. Idempotent: a refiled source has no active claim left, so a
# second run plans nothing.

#: A person's name filed as a school.
PERSON_IS_NOT_A_SCHOOL = "person_is_not_a_school"
#: A dated event (signing a paper, a round, a deal) filed as a job.
EVENT_IS_NOT_A_JOB = "event_is_not_a_job"
#: A company or a fund filed as a partnership.
ORGANIZATION_IS_NOT_A_PARTNER = "organization_is_not_a_partner"
MISFILED_REASONS = (PERSON_IS_NOT_A_SCHOOL, EVENT_IS_NOT_A_JOB, ORGANIZATION_IS_NOT_A_PARTNER)

#: What each reason refiles AS: nothing (the record is not a moment of its
#: own — Katie's graduation is already told), or an ordinary moment.
REFILE_RETIRED = "retired"
REFILE_AS_MOMENT = "moment"
REFILE_KIND_FOR = {PERSON_IS_NOT_A_SCHOOL: REFILE_RETIRED,
                   EVENT_IS_NOT_A_JOB: REFILE_AS_MOMENT,
                   ORGANIZATION_IS_NOT_A_PARTNER: REFILE_AS_MOMENT}

A_RECORD_IS_FILED_WHERE_IT_BELONGS = (
    "a person is never a school, a dated event is never a job, and a company "
    "or a fund is never a partnership; such a record is refiled - retired, or "
    "an ordinary moment at its own dates - never drawn as a landmark"
)

REFILE_SOURCES_DIR = f"{LANDMARK_SOURCES_DIR}/refiles"
LANDMARK_REFILE_SOURCE_TYPE = "landmark_refile"
REFILE_EXTRACTOR = "landmark-refile/rule:1"
REFILE_EXTRACTOR_NAME = "landmark-refile"

#: The words that make a one-date `work` record an EVENT. Closed, and only
#: ever read over a record that states no span: a job is a stretch.
_EVENT_WORDS_RE = re.compile(
    r"\b(?:safe|safes|conversion|convert(?:ed|ing)?|sign(?:ed|ing)?|signature|"
    r"paper(?:s|work)?|term\s+sheet|terms|negotiat(?:ion|ions|ed|ing)|funding|"
    r"investment|invest(?:ed|or|ors)?|round|closing|closed|wire[ds]?|deal|contract|"
    r"agreement|acquisition|acquired|merger|ipo|loan|settlement|lawsuit|pitch|"
    r"meeting|email|call)\b",
    re.IGNORECASE)
#: Words that make a name an ORGANIZATION.
_ORGANIZATION_WORDS_RE = re.compile(
    r"\b(?:ventures?|capital|partners|fund|funds|llc|inc|corp(?:oration)?|company|"
    r"labs?|holdings|group|bank|vc|investments?|studios?|foundation|university|"
    r"college|church|ltd|gmbh|s\.?a\.?|associates|technologies|systems)\b",
    re.IGNORECASE)
#: The domains whose `who`/label names a PERSON the owner has told about.
PERSON_DOMAINS = ("partnerships", "children", "family", "losses")


def people_named_in(sources: object) -> frozenset[str]:
    """Every person name the landmark records give (folded), for
    :data:`PERSON_IS_NOT_A_SCHOOL`."""
    import landmark_identity as lid  # noqa: PLC0415

    names = set()
    for source in sources or ():
        if not isinstance(source, dict) or source.get("domain") not in PERSON_DOMAINS:
            continue
        record = source.get("record") if isinstance(source.get("record"), dict) else {}
        for key in ("who", "label", "name"):
            text = lid.fold(record.get(key))
            if text and not _ORGANIZATION_WORDS_RE.search(text):
                names.add(text)
    return frozenset(names)


def organizations_named_in(sources: object) -> frozenset[str]:
    """Every employer the `work` records name (folded)."""
    import landmark_identity as lid  # noqa: PLC0415

    names = set()
    for source in sources or ():
        if not isinstance(source, dict) or source.get("domain") != "work":
            continue
        record = source.get("record") if isinstance(source.get("record"), dict) else {}
        text = lid.fold(record.get("label"))
        if text:
            names.add(text)
    return frozenset(names)


def misfiled_landmark(domain: object, record: object, *, people: object = (),
                      organizations: object = ()) -> str | None:
    """Why ``record`` is not an entry of ``domain`` at all, or ``None``. PURE.

    * :data:`PERSON_IS_NOT_A_SCHOOL` — a ``schools`` record that names no
      school (no ``name``, no ``grades``, no ``place``) and whose label is a
      person the owner's records already name.
    * :data:`EVENT_IS_NOT_A_JOB` — a ``work`` record that states ONE date and
      no span, in words that name an event (:data:`_EVENT_WORDS_RE`).
    * :data:`ORGANIZATION_IS_NOT_A_PARTNER` — a ``partnerships`` record whose
      person is an organization (:data:`_ORGANIZATION_WORDS_RE`), or whose
      subject is one of his own employers.
    """
    import landmark_identity as lid  # noqa: PLC0415

    if not isinstance(record, dict) or record.get("none") is True or record.get("skipped"):
        return None
    name = collapsed_text(domain)
    if name == "schools":
        if any(collapsed_text(record.get(key)) for key in ("name", "grades", "place")):
            return None
        label = lid.fold(record.get("label"))
        if label and label in set(people or ()):
            return PERSON_IS_NOT_A_SCHOOL
        return None
    if name == "work":
        if isinstance(record.get("span"), dict) and record["span"]:
            return None
        if not isinstance(record.get("date"), dict):
            return None
        words = " ".join(collapsed_text(record.get(key)) for key in ("label", "what"))
        return EVENT_IS_NOT_A_JOB if _EVENT_WORDS_RE.search(words) else None
    if name == "partnerships":
        who = collapsed_text(record.get("who")) or collapsed_text(record.get("label"))
        if who and _ORGANIZATION_WORDS_RE.search(who):
            return ORGANIZATION_IS_NOT_A_PARTNER
        subject = lid.fold(record.get("subject"))
        if subject and subject in set(organizations or ()):
            return ORGANIZATION_IS_NOT_A_PARTNER
        return None
    return None


def refile_plan(sources: object, active_index: object) -> list[dict]:
    """Every standing record :func:`misfiled_landmark` names. PURE.

    ``[{"source_id", "domain", "entry_key", "label", "reason", "kind",
    "claim_ids"}]`` in filing order; only sources with an ACTIVE claim, so a
    refiled record never plans twice.
    """
    rows = [row for row in (sources or ()) if isinstance(row, dict)]
    people = people_named_in(rows)
    organizations = organizations_named_in(rows)
    standing: dict[str, list[str]] = {}
    for claim in store.active_claims(active_index if isinstance(active_index, dict) else {}):
        ref = claim.get("source_ref")
        source_id = collapsed_text(ref.get("source_id")) if isinstance(ref, dict) else ""
        if source_id and collapsed_text(claim.get("extractor_version")) != REFILE_EXTRACTOR:
            standing.setdefault(source_id, []).append(collapsed_text(claim.get("claim_id")))
    plan = []
    for source in rows:
        ids = standing.get(source["source_id"])
        if not ids:
            continue
        reason = misfiled_landmark(source["domain"], source.get("record"),
                                   people=people, organizations=organizations)
        if reason is None:
            continue
        record = source.get("record") or {}
        plan.append({"source_id": source["source_id"], "domain": source["domain"],
                     "entry_key": source.get("entry_key") or "",
                     "label": collapsed_text(record.get("label") or record.get("who")),
                     "subject": collapsed_text(record.get("subject")),
                     "reason": reason, "kind": REFILE_KIND_FOR[reason],
                     "claim_ids": sorted(ids)})
    return plan


def refile_relative_path(source_id: object, kind: object) -> str:
    digest = store.payload_sha256(json.dumps(
        {"source_id": collapsed_text(source_id), "kind": collapsed_text(kind)},
        sort_keys=True, separators=(",", ":")))
    return f"{REFILE_SOURCES_DIR}/refile-{digest[:store.FILENAME_DIGEST_LENGTH]}.md"


def refiled_record_paths(vault_root: str | Path) -> frozenset[str]:
    """The ``sources/landmarks/entry-*.md`` paths a refile record names.

    Read by the classifier migration: a refiled record's own words, read back
    by the story classifier, are the record again and never a moment of their
    own (`classifier_claims.A_RECORDED_RECORD_IS_CANONICAL_DATED_OR_NOT`) —
    the refile already says what it is."""
    root = _root(vault_root)
    base = store.store_path(root, REFILE_SOURCES_DIR)
    if not base.is_dir():
        return frozenset()
    found = set()
    for path in sorted(base.glob("refile-*.md")):
        text = store.read_store_text(root, path.relative_to(root).as_posix())
        metadata, _ = store.split_frontmatter(text or "")
        if not metadata or metadata.get("type") != LANDMARK_REFILE_SOURCE_TYPE:
            continue
        refiled = collapsed_text(metadata.get("refiled_source_id"))
        digest = refiled.partition(":entry-")[2]
        if digest:
            found.add(f"{LANDMARK_SOURCES_DIR}/entry-{digest}.md")
    return frozenset(found)


def moment_claims_for(step: dict, claims: object, *, source_ref: object,
                      now: object = None) -> list[dict]:
    """The ORDINARY MOMENT a refiled record is, one claim per date it carried.

    Its words are the record's own label; its subject is the record's own
    subject when it names one (Castle Island's "Etherfuse") and the owner
    otherwise (a moment at his own work); its ``event_ref`` is minted from the
    label, so each refiled record is one moment and two dates for one of them
    stay two readings of it (a contradiction to ask, not a merge to hide).
    """
    import temporal_projection as tp  # noqa: PLC0415

    label = collapsed_text(step.get("label")) or collapsed_text(step.get("entry_key"))
    subject = collapsed_text(step.get("subject")) or "self"
    event_ref = tp.derive_node_id(node_kind="event", event_kind="moment",
                                  subject_refs=[f"landmark-refile:{label.casefold()}"])
    out = []
    seen = set()
    for claim in claims or ():
        if not isinstance(claim, dict) or collapsed_text(claim.get("claim_type")) != "date":
            continue
        record = chrono.from_dict(claim.get("temporal_value"))
        if record is None:
            continue
        key = chrono.to_edtf(record)
        if key in seen:
            continue
        seen.add(key)
        out.append(validate_temporal_claim({
            "source_ref": source_ref,
            "source_kind": "import",
            "claim_type": "date",
            "subject_mention": subject,
            "event_kind": "moment",
            "event_mention": label[:200],
            "event_ref": event_ref,
            "temporal_value": record.to_dict(),
            "evidence": [{"quote": bounded_quote(
                f"{step.get('domain')}.{label} refiled as a moment "
                f"({step.get('reason')}): {chrono.to_edtf(record)}")}],
            "basis": collapsed_text(claim.get("basis")) or "explicit",
            "confidence": claim.get("confidence"),
            "extractor_version": REFILE_EXTRACTOR,
        }, now=now))
    return out


def file_landmark_refile(vault_root: str | Path, step: dict, *, active_index: object,
                         now: object = None) -> dict:
    """Refile ONE misfiled record (:data:`A_RECORD_IS_FILED_WHERE_IT_BELONGS`).

    The moment first (record, then receipt), then the supersession — so a
    crash between them leaves the old reading standing beside the new one,
    never a record with neither. Every write is idempotent on its content.
    Returns ``{"source_id", "kind", "reason", "refile_path", "receipt_path",
    "correction", "claims"}``.
    """
    root = _root(vault_root)
    kind = collapsed_text(step.get("kind"))
    source_id = collapsed_text(step.get("source_id"))
    claim_ids = set(step.get("claim_ids") or ())
    claims = [row for row in store.active_claims(
        active_index if isinstance(active_index, dict) else {})
        if collapsed_text(row.get("claim_id")) in claim_ids]
    result = {"source_id": source_id, "kind": kind, "reason": step.get("reason"),
              "refile_path": "", "receipt_path": "", "correction": "", "claims": 0}
    if kind in (REFILE_AS_MOMENT, REFILE_RETIRED):
        relative = refile_relative_path(source_id, kind)
        heading = (f"{step.get('domain')}: {step.get('label')} is a moment, not a landmark"
                   if kind == REFILE_AS_MOMENT else
                   f"{step.get('domain')}: {step.get('label')} is not a landmark")
        payload = (f"# {heading}\n\n{step.get('reason')}: "
                   f"{A_RECORD_IS_FILED_WHERE_IT_BELONGS}\n")
        frontmatter = {
            "title": heading[:120],
            "type": LANDMARK_REFILE_SOURCE_TYPE,
            "source_id": f"landmark_refile:{Path(relative).stem}",
            "source_medium": "rule",
            "domain": collapsed_text(step.get("domain")),
            "refiled_source_id": source_id,
            "refile_kind": kind,
            "refile_reason": collapsed_text(step.get("reason")),
            "captured_at": normalized_timestamp(now, error=LandmarkProjectionError),
            "visibility": "owner_only",
            "immutable": True,
            "schema_version": SCHEMA_VERSION,
            "source_path": relative,
            "content_sha256": store.payload_sha256(payload),
        }
        store.create_or_keep(root, relative,
                             f"{store.format_frontmatter(frontmatter)}\n\n{payload}")
        ref = store.read_source_ref(root, relative)
        source_ref = {"source_id": ref.source_id, "revision": ref.revision,
                      "source_path": ref.source_path or relative}
        moments = (moment_claims_for(step, claims, source_ref=source_ref, now=now)
                   if kind == REFILE_AS_MOMENT else [])
        if moments:
            path = store.write_receipt(root, {
                "source_ref": source_ref,
                "extractor_version": REFILE_EXTRACTOR,
                "extractor": {"name": REFILE_EXTRACTOR_NAME, "rule_version": "1",
                              "deterministic": True},
                "claims": moments,
            }, now=now)
            result["receipt_path"] = str(Path(path).relative_to(root))
            result["claims"] = len(moments)
        result["refile_path"] = relative
    if claims:
        correction = store.supersede_claims(
            root, sorted(claim_ids), reason=(
                f"{step.get('reason')}: refiled by landmark-refile "
                f"({A_RECORD_IS_FILED_WHERE_IT_BELONGS})"),
            scope=landmark_correction_scope(step.get("domain")), occurred_at=now)
        result["correction"] = getattr(correction, "relative_path", "") or str(
            getattr(correction, "correction_id", ""))
    return result


#: v349. The scope every landmark supersession this module files already
#: carries — ``landmarks/<domain>`` — read back by :func:`domain_supersessions`
#: so the repair verb selects exactly what :func:`retire_entry` wrote and
#: nothing else.
LANDMARK_CORRECTION_SCOPE_PREFIX = "landmarks/"


def landmark_correction_scope(domain: object) -> str:
    """``landmarks/<domain>`` — ONE spelling, written and read here."""
    return f"{LANDMARK_CORRECTION_SCOPE_PREFIX}{collapsed_text(domain)}"


def domain_supersessions(
    vault_root: str | Path,
    *,
    domain: object,
    since: object = None,
    until: object = None,
) -> list[dict]:
    """The supersessions standing against one landmark domain, sorted. v349.

    ``[{"correction_id", "relative_path", "created_at", "claim_ids",
    "reason"}, ...]`` in ``correction_id`` order — a total order that does not
    consult a clock, so the same vault yields the same list on every machine.

    Only ``supersede`` rows scoped to :func:`landmark_correction_scope`, only
    ones no reinstatement has already voided
    (`temporal_store.reinstated_correction_ids`), and — when ``since`` /
    ``until`` are given — only ones whose ``captured_at`` falls in that window.
    The window is what makes the repair surgical: a domain may hold perfectly
    good supersessions from other days, and a verb that reinstated those would
    be the same class of defect it exists to undo.
    """
    scope = landmark_correction_scope(domain)
    lower = store.normalized_timestamp(since, error=LandmarkProjectionError) if since else None
    upper = store.normalized_timestamp(until, error=LandmarkProjectionError) if until else None
    voided = set(store.reinstated_correction_ids(vault_root))
    rows = []
    for correction in store.load_temporal_corrections(vault_root):
        if correction.scope != scope or correction.kind != "supersede":
            continue
        if correction.correction_id in voided:
            continue
        if lower is not None and correction.created_at < lower:
            continue
        if upper is not None and correction.created_at > upper:
            continue
        rows.append({
            "correction_id": correction.correction_id,
            "relative_path": correction.relative_path,
            "created_at": correction.created_at,
            "claim_ids": list(correction.claim_ids),
            "reason": correction.reason,
        })
    rows.sort(key=lambda row: (row["correction_id"], row["relative_path"]))
    return rows


def reinstate_domain(
    vault_root: str | Path,
    *,
    domain: object,
    since: object = None,
    until: object = None,
    reason: object = None,
    apply: bool = False,
    occurred_at: object = None,
) -> dict:
    """Put one landmark domain's superseded entries back. v349.

    The repair half of `landmarks_interaction.A_STATED_ENTRY_IS_NEVER_RETIRED_BY_SHAPE`:
    the rule stops the next wipe, and this undoes the one that already
    happened. On 2026-09-24 a single bare residences answer retired thirty
    entries the owner had stated and filed 29 supersessions doing it, taking
    the claims behind those stays out of the projection and dropping every
    moment they had placed — a marriage, a graduation, a fall on a nail — back
    to unplaced.

    ONE act, three properties:

    * **deterministic** — the corrections are selected and sorted by content
      (:func:`domain_supersessions`), never by mtime, and one reinstatement
      record names them all;
    * **idempotent** — the record's id is a digest of what it says, and
      :func:`domain_supersessions` already excludes what a previous run
      reinstated, so a second run proposes nothing and writes nothing;
    * **narrow** — it writes ``sources/corrections/`` (one file) and nothing
      else. The ENTRIES come back because `state/landmarks.json` is a drawing:
      the claims behind them go active again on the next fold and
      `timeline.redraw_landmarks` draws them from the
      ``sources/landmarks/entry-*.md`` that were never touched. Nothing here
      writes an entry, which is the invariant the flip (v225) established.

    Returns the summary either way; ``apply=False`` (the default — a repair
    verb shows its work first) fills ``corrections`` and ``claim_ids`` and
    leaves ``filed`` at ``None``.
    """
    name = collapsed_text(domain)
    rows = domain_supersessions(vault_root, domain=name, since=since, until=until)
    claim_ids = sorted({claim for row in rows for claim in row["claim_ids"]})
    summary: dict = {
        "domain": name,
        "since": store.normalized_timestamp(since, error=LandmarkProjectionError) if since else None,
        "until": store.normalized_timestamp(until, error=LandmarkProjectionError) if until else None,
        "corrections": [row["correction_id"] for row in rows],
        "correction_paths": [row["relative_path"] for row in rows],
        "claim_ids": claim_ids,
        "applied": False,
        "filed": None,
    }
    if not rows or not apply:
        return summary
    prose = collapsed_text(reason) or (
        f"reinstated: these {name} entries were retired by shape, not by "
        f"anything the person said "
        f"({landmarks_interaction.A_STATED_ENTRY_IS_NEVER_RETIRED_BY_SHAPE})"
    )
    correction = store.reinstate_corrections(
        vault_root,
        [row["correction_id"] for row in rows],
        reason=prose,
        title=f"Reinstate {len(rows)} {name} supersession(s)",
        occurred_at=occurred_at,
    )
    summary["applied"] = True
    summary["filed"] = correction.relative_path
    return summary


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
