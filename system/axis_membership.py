#!/usr/bin/env python3
"""Whose moments ride the owner's axis (owner ruling, 2026-09-23).

ADR 0030 amendment. Until v333 the Timeline answered "does this moment about
somebody else belong on the owner's axis?" with ``owner_timeline_relation``
alone, and the answer for everything the evidence rules could not grant was
``contextual_only`` — a bucket the page drew as its own group, *"About someone
else"*. On the owner's own vault that group held 37 rows, and 34 of them were
his own family: his children's childhood anecdotes, his mother babysitting,
his father's graduation. The classifier put them there because no sentence in
them says *"I was there"*, which is a judgement about presence made from
words — exactly the judgement the owner ruled out.

**The ruling, in his terms.** Which moments about other people belong on his
timeline is decided by ONE deterministic rule at fold time, from the roster
relationship and his birth date:

1. he lived it — ``participated``, or it changed his life (``lived_effect``) —
   his timeline, whoever else it is about. Unchanged;
2. an IMMEDIATE FAMILY member's own event during his lifetime — his timeline,
   marked as being about them;
3. anyone else's own event (a friend's divorce, a colleague's move) — not on
   his axis at all. It stays in the substrate and on that person's page;
4. anything before his birth — family history, on the person's page, never on
   his axis. That is v324's own pre-birth rule, kept.

**The v338 correction.** Rule 3 is a DECISION, and v334 let it swallow the
cases where no decision had been made. Any subject whose tier could not be read
— a roster person with no ``relationship`` recorded, or a name the roster has
never heard of — came out ``not_family``, and downstream (`temporal_timeline`)
that is the reason that SUPPRESSES the date question and drops the node from
``diagnostics["unplaced"]``. So "Lumen died." minted no "when?" card at all, and
the owner's own marriage lost its card because the spouse's row carried no
relationship word. The owner ruled (2026-09-23) that an unknown relationship is
not rule 3: treat it like ``subject_unresolved`` — nothing has been decided, so
the node keeps its questions. Hence the sixth reason,
``relationship_unknown``, and rule 3 now needs the tier to be affirmatively
:data:`DISTANT_TIER`.

Immediate family is spouse/partner, parents, siblings, grandparents, children,
grandchildren. In-laws, aunts/uncles/cousins, friends and colleagues are not.

**The encoding.** ``owner_timeline_relation`` keeps every value it had —
tolerant readers are unaffected, and the evidence it records ("a `losses`
entry says he lived this") is a different fact from the ruling's tiers. What is
added is one FOLD-DERIVED pair on every node, :data:`AXIS_MEMBERSHIP_FIELD` and
:data:`AXIS_MEMBERSHIP_REASON_FIELD`, saying whether the node is drawn on the
owner's axis and why. Hosts read that pair instead of inferring a surface from
``contextual_only``; as a Timeline surface the ``contextual_only`` GROUP is
retired, and the relation value that named it is now just one input to this
rule among several.

**Why a module of its own.** The rule is a pure function of four things — the
roster relationship, the owner's birth, the node's date and the relation the
evidence rules already reached — and none of them is chronology. Keeping it
here rather than inside `temporal_timeline._owner_relevance` is what lets the
tier tests hand in synthetic roster rows with no substrate at all, and what
keeps "is this immediate family?" from being asked a second way somewhere else
later. The closed value lists live in `temporal_projection` beside
``LIFE_VIEWS``/``OWNER_TIMELINE_RELATIONS``, where every other node vocabulary
the validator enforces already lives.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

_SYSTEM_DIR = Path(__file__).resolve().parent
if str(_SYSTEM_DIR) not in sys.path:
    sys.path.insert(0, str(_SYSTEM_DIR))

import cross_dating as cd  # noqa: E402
import identity_resolution as ir  # noqa: E402
import temporal_projection as tp  # noqa: E402
from temporal_claims import collapsed_text  # noqa: E402

#: The two published fields, spelled once so the fold, the validator and the
#: tests cannot disagree about their names.
AXIS_MEMBERSHIP_FIELD = "axis_membership"
AXIS_MEMBERSHIP_REASON_FIELD = "axis_membership_reason"

#: The roster ``relationship`` values that ARE immediate family. The roster's
#: own vocabulary is `focus_candidate.FOCUS_RELATIONSHIPS` (parent,
#: grandparent, child, sibling, spouse, partner, friend, colleague, mentor,
#: other); ``grandchild`` is named by the ruling and is accepted here although
#: that tuple lacks it, because a roster written by any other seat may carry it
#: and refusing the owner's own word would be the defect, not the guard.
IMMEDIATE_FAMILY_RELATIONSHIPS = frozenset({
    "parent", "grandparent", "child", "grandchild",
    "sibling", "spouse", "partner",
})

#: The roster ``relationship`` values that are NOT. ``other`` is here on
#: purpose and it is where the ruling's exclusions land: an aunt, a cousin and
#: a mother-in-law have no word of their own in the roster vocabulary, so they
#: are recorded as ``other``, and the owner ruled that they are not immediate
#: family. A stated relationship is the OWNER'S OWN statement and therefore
#: beats every lexical reading below it — an entity named "Grandma Betty Jo"
#: whose relationship says ``friend`` is a friend.
DISTANT_RELATIONSHIPS = frozenset({"friend", "colleague", "mentor", "other"})

#: The lexical layer, for the (common) case of a roster row with no
#: ``relationship`` at all — on the owner's own vault only 2 of 11 person rows
#: carry one — and for a subject mention that resolved to no row.
#:
#: The two sets below PARTITION `cross_dating.THIRD_PARTY_RELATION_WORDS`, the
#: one vocabulary the birth veto, the age veto and
#: `temporal_timeline._mention_names_another_person` already read; a test
#: asserts the partition is total, so that list cannot grow a word without this
#: rule being told which tier it belongs to. Each set then names its own extras
#: — singulars and plurals that list has no reason to carry but a roster NAME
#: does ("Parents", "Siblings", "Kids") — and matching singularizes a trailing
#: "s", so "siblings" reads as "sibling" without a second spelling of either.
IMMEDIATE_FAMILY_RELATION_WORDS = frozenset({
    # from THIRD_PARTY_RELATION_WORDS
    "brother", "sister", "sibling", "son", "daughter", "mom", "mother",
    "grandma", "grandmother", "dad", "father", "grandpa", "grandfather",
    "wife", "husband", "partner", "child", "children", "baby", "twin",
    "grandson", "granddaughter", "grandchild", "parents", "grandparents",
    # extras this rule names: the singulars and the household words a roster
    # row is titled with.
    "parent", "grandparent", "grandchildren", "spouse", "kid", "kids",
    "mum", "mama", "papa", "stepmother", "stepfather", "stepson",
    "stepdaughter",
})

#: Related, or close, and still not immediate family (the ruling names
#: aunts/uncles/cousins, friends and colleagues explicitly). ``dog`` and
#: ``cat`` are in the shared vocabulary because they mark a sentence as being
#: about somebody other than the owner; they are not people, so they are not
#: family either.
DISTANT_RELATION_WORDS = frozenset({
    # from THIRD_PARTY_RELATION_WORDS
    "cousin", "nephew", "niece", "uncle", "aunt", "friend", "dog", "cat",
    # extras this rule names.
    "colleague", "coworker", "boss", "neighbor", "neighbour", "mentor",
    "roommate", "teacher", "student", "godmother", "godfather",
})

#: An in-law is never immediate family, whatever relation word the phrase is
#: built out of — "mother-in-law" contains "mother" and is not the owner's
#: mother. Checked on the WHOLE mention before any word is read, because the
#: hyphenated word is the thing that changes the answer.
IN_LAW_RE = re.compile(r"(?<!\w)in[-\s]?laws?(?!\w)", re.IGNORECASE)

#: The tiers this module reads a subject into. ``unknown`` is not ``distant``,
#: and since v338 that distinction reaches the published reason: nothing in the
#: roster and nothing in the words answered, so the ruling's rule 3 — which is a
#: DECISION about a person whose relationship is KNOWN to be outside the
#: immediate family — has not been made. ``unknown`` still takes the ruling's
#: default membership (``none``: not drawn on his axis until somebody says who
#: this is) under a reason of its own, ``relationship_unknown``, and it keeps
#: its questions. Only :data:`DISTANT_TIER` is rule 3.
IMMEDIATE_FAMILY_TIER = "immediate_family"
DISTANT_TIER = "distant"
UNKNOWN_TIER = "unknown"
FAMILY_TIERS = (IMMEDIATE_FAMILY_TIER, DISTANT_TIER, UNKNOWN_TIER)

#: Where a tier was read from, for a caller that wants to explain itself. Not
#: published on the node: the owner asked for two fields and this is the third
#: thing a reader could recompute.
TIER_BASES = ("roster_relationship", "roster_name", "mention", "none")

_WORD_RE = re.compile(r"[A-Za-z][A-Za-z'’]*")


def _singularized(word: str) -> str:
    """``siblings`` -> ``sibling``. A trailing "s" and nothing cleverer: the
    vocabulary carries its own irregulars ("children", "grandchildren") and a
    stemmer here would turn "Chris" into "Chri"."""
    lowered = word.casefold()
    if len(lowered) > 3 and lowered.endswith("s") and not lowered.endswith("ss"):
        return lowered[:-1]
    return lowered


def relation_word_tier(text: object) -> str:
    """The tier the WORDS of ``text`` state, or :data:`UNKNOWN_TIER`.

    Immediate family wins a text that says both ("my brother and his friend"):
    the phrase names a brother, and the friend is somebody the brother knows.
    An in-law reading vetoes immediate family outright.
    """
    phrase = collapsed_text(text)
    if not phrase:
        return UNKNOWN_TIER
    in_law = bool(IN_LAW_RE.search(phrase))
    found_distant = False
    for match in _WORD_RE.finditer(phrase):
        raw = match.group(0)
        for candidate in (raw.casefold(), _singularized(raw)):
            if candidate in IMMEDIATE_FAMILY_RELATION_WORDS:
                if in_law:
                    found_distant = True
                    break
                return IMMEDIATE_FAMILY_TIER
            if candidate in DISTANT_RELATION_WORDS:
                found_distant = True
                break
    if in_law:
        return DISTANT_TIER
    return DISTANT_TIER if found_distant else UNKNOWN_TIER


def relationship_tier(relationship: object) -> str:
    """The tier a roster ``relationship`` field states, or
    :data:`UNKNOWN_TIER` when the field is absent or a word nobody has told
    this rule about. An unknown WORD is deliberately not ``distant``: it falls
    through to the lexical layer, which is how a roster that starts spelling
    ``stepparent`` keeps working before anybody edits this list."""
    word = collapsed_text(relationship).casefold()
    if not word:
        return UNKNOWN_TIER
    if word in IMMEDIATE_FAMILY_RELATIONSHIPS:
        return IMMEDIATE_FAMILY_TIER
    if word in DISTANT_RELATIONSHIPS:
        return DISTANT_TIER
    return UNKNOWN_TIER


def roster_person_rows(roster_snapshot: object) -> list[dict]:
    """Every PERSON row in what a fold was handed as its roster.

    Tolerant of all three shapes a seat may pass (`entity_roster.load_roster`'s
    ``{"type": "person", "entities": [...]}``, a bare list of rows, or a
    sequence of such snapshots), because `temporal_publication.publish` passes
    the first and `lifehug.py`'s frame-display command passes the third.
    """
    if isinstance(roster_snapshot, dict):
        if collapsed_text(roster_snapshot.get("type")) not in ("", "person"):
            return []
        rows = roster_snapshot.get("entities")
        return [row for row in rows or () if isinstance(row, dict)]
    rows: list[dict] = []
    for item in roster_snapshot or ():
        if isinstance(item, dict) and (item.get("entities") is not None
                                       or collapsed_text(item.get("type"))):
            rows.extend(roster_person_rows(item))
        elif isinstance(item, dict):
            rows.append(item)
    return rows


def family_tier_index(roster_snapshot: object) -> dict:
    """``{key: (tier, basis)}`` over one person roster, built once per fold.

    Keyed by the entity REF (``person/james``) and by every
    `identity_resolution.normalized_mention_key` the row answers to — its name,
    its slug and its aliases — so a subject that resolved to a ref and a
    subject that is still only a display name read the SAME tier. A key two
    rows disagree about is dropped rather than decided by file order: two
    people answering to one alias bind to neither, which is the roster's own
    shared-alias rule (`roster_relations.alias_decision`).
    """
    index: dict[str, tuple[str, str]] = {}
    conflicted: set[str] = set()

    def record(key: str, value: tuple[str, str]) -> None:
        if not key or key in conflicted:
            return
        standing = index.get(key)
        if standing is None:
            index[key] = value
        elif standing[0] != value[0]:
            conflicted.add(key)
            del index[key]

    for row in roster_person_rows(roster_snapshot):
        tier = relationship_tier(row.get("relationship"))
        basis = "roster_relationship"
        if tier == UNKNOWN_TIER:
            # No stated relationship. The row's own NAME is the next honest
            # reading: the owner (or the classifier writing for him) titled
            # these rows "Grandma Betty Jo", "Parents", "Siblings", "Kids".
            names = [row.get("name"), row.get("slug"), *(row.get("aliases") or ())]
            tier = next(
                (found for found in (relation_word_tier(name) for name in names)
                 if found != UNKNOWN_TIER),
                UNKNOWN_TIER,
            )
            basis = "roster_name" if tier != UNKNOWN_TIER else "none"
        if tier == UNKNOWN_TIER:
            continue
        value = (tier, basis)
        # The same ``type/slug`` ref shape every other reader of this roster
        # derives, re-derived here rather than reaching across a private name —
        # exactly as `roster_relations._slug_of` already does.
        slug = (ir.normalized_mention_key(row.get("slug"))
                or ir.normalized_mention_key(row.get("name"))).replace(" ", "-")
        if slug:
            record(collapsed_text(ir.entity_ref("person", slug)), value)
        for key_field in ("name", "slug"):
            record(ir.normalized_mention_key(row.get(key_field)), value)
        for alias in row.get("aliases") or ():
            record(ir.normalized_mention_key(alias), value)
    return index


def subject_family_tier(subject: object, *, tier_index: dict,
                        mention_texts: object = ()) -> tuple[str, str]:
    """``(tier, basis)`` for one node's subject.

    Three layers, most authoritative first, and each of them deterministic:
    the roster row's stated ``relationship``; the words in that row's own name
    or aliases; the words of the SUBJECT MENTION itself (and of any extra text
    the caller offers, which is how "James Taylor (Dad)" says who James is
    when the roster has never heard of him).
    """
    key = collapsed_text(subject)
    for candidate in (key, ir.normalized_mention_key(key)):
        hit = tier_index.get(candidate)
        if hit is not None:
            return hit
    for text in (key, *(mention_texts or ())):
        tier = relation_word_tier(text)
        if tier != UNKNOWN_TIER:
            return tier, "mention"
    return UNKNOWN_TIER, "none"


def axis_membership(*, occurrence_subject_scope: object,
                    owner_timeline_relation: object,
                    family_tier: object,
                    before_owner_birth: bool) -> dict:
    """THE rule. ``{axis_membership, axis_membership_reason}``, and nothing else.

    Pure, total, and ordered exactly as the owner stated it:

    * his OWN occurrence — ``occurrence_subject_scope: "owner"``, identity
      landed on him — ``owner`` / ``lived``. Rule 1, and it outranks everything
      including rule 4: an owner-subject occurrence before his own birth stays
      ``owner``, because that is a contradiction Mirror owns (``life_view:
      contradictory``) and rule 4 is about other people's events;
    * wholly before his birth — ``none`` / ``pre_birth``. Rule 4, which is
      v324's own pre-birth rule under a name. **v344 moved it above the two
      clauses below**, so it now outranks an evidence RELATION and an
      unidentified subject alike: the owner's mother's birthday, 1955-06-19,
      reached `axis_membership` with ``owner_timeline_relation:
      "participated"`` — the zero-candidate fallback's reading of a name the
      roster had never heard of — and was drawn on his axis as something he
      lived, twenty-six years before he was born. Nothing about a subject
      nobody has identified can make 1955 part of his life, which is why this
      clause does not wait for identity to land;
    * identity has not landed — ``none`` / ``subject_unresolved``. The fifth
      reason, and the honest one: no tier can be read for a subject nobody has
      identified, and §2.6 is explicit that an unresolved subject is never
      ``self`` by default. It is not rule 3: nothing has been decided against
      this node, and the identity question stays open;
    * a relation the evidence rules already put on the axis
      (`temporal_projection.AXIS_RELATIONS`) — ``owner`` / ``lived``. Rule 1's
      other half: what he lived is his, whoever else it is about;
    * immediate family — ``family`` / ``immediate_family_in_lifetime``. Rule 2.
      ``family`` means DRAWN ON HIS AXIS, as a moment about them;
    * affirmatively somebody ELSE — a relationship that is KNOWN and outside
      the immediate family (:data:`DISTANT_TIER`: a friend, a colleague, a
      cousin, an in-law) — ``none`` / ``not_family``. Rule 3;
    * a person nobody has said anything about — ``none`` /
      ``relationship_unknown``. The SIXTH reason (v338), and the defect it
      fixes is v334 folding it into rule 3. Rule 3 is a DECISION: it needs a
      relationship, known, and outside the immediate set. :data:`UNKNOWN_TIER`
      is the absence of that statement, not a statement of it — a roster row
      with no ``relationship`` whose name carries no relation word, or a named
      subject the roster has never heard of. So it reads exactly like
      ``subject_unresolved``: ``none``, because it is still not drawn on the
      owner's axis until somebody says who this is (the ruling's default, and
      the person-page home), and NOTHING has been decided, so the node keeps
      every question it had before the ruling existed.
    """
    scope = collapsed_text(occurrence_subject_scope)
    relation = collapsed_text(owner_timeline_relation)
    if scope == "owner":
        return _row(tp.AXIS_MEMBERSHIP_OWNER, tp.AXIS_REASON_LIVED)
    if before_owner_birth:
        return _row(tp.AXIS_MEMBERSHIP_NONE, tp.AXIS_REASON_PRE_BIRTH)
    if scope == "unresolved" or relation == "unresolved":
        return _row(tp.AXIS_MEMBERSHIP_NONE, tp.AXIS_REASON_SUBJECT_UNRESOLVED)
    if relation in tp.AXIS_RELATIONS:
        return _row(tp.AXIS_MEMBERSHIP_OWNER, tp.AXIS_REASON_LIVED)
    tier = collapsed_text(family_tier)
    if tier == IMMEDIATE_FAMILY_TIER:
        return _row(tp.AXIS_MEMBERSHIP_FAMILY, tp.AXIS_REASON_IMMEDIATE_FAMILY)
    if tier == DISTANT_TIER:
        return _row(tp.AXIS_MEMBERSHIP_NONE, tp.AXIS_REASON_NOT_FAMILY)
    return _row(tp.AXIS_MEMBERSHIP_NONE, tp.AXIS_REASON_RELATIONSHIP_UNKNOWN)


def _row(membership: str, reason: str) -> dict:
    return {AXIS_MEMBERSHIP_FIELD: membership, AXIS_MEMBERSHIP_REASON_FIELD: reason}


def on_owner_axis(node_or_row: object) -> bool:
    """Is this row DRAWN on the owner's axis? ``owner`` and ``family`` are;
    ``none`` is not. One predicate, so the fold, the work-item accounting and a
    host cannot answer it three ways. A row with no ``axis_membership`` at all
    is a projection written before this rule existed, and the tolerant reading
    of it is the one the page already had: the old axis test."""
    if not isinstance(node_or_row, dict):
        return False
    membership = collapsed_text(node_or_row.get(AXIS_MEMBERSHIP_FIELD))
    if membership:
        return membership != tp.AXIS_MEMBERSHIP_NONE
    return collapsed_text(node_or_row.get("owner_timeline_relation")) in tp.AXIS_RELATIONS


__all__ = [
    "AXIS_MEMBERSHIP_FIELD",
    "AXIS_MEMBERSHIP_REASON_FIELD",
    "DISTANT_RELATIONSHIPS",
    "DISTANT_RELATION_WORDS",
    "DISTANT_TIER",
    "FAMILY_TIERS",
    "IMMEDIATE_FAMILY_RELATIONSHIPS",
    "IMMEDIATE_FAMILY_RELATION_WORDS",
    "IMMEDIATE_FAMILY_TIER",
    "IN_LAW_RE",
    "TIER_BASES",
    "UNKNOWN_TIER",
    "axis_membership",
    "family_tier_index",
    "on_owner_axis",
    "relation_word_tier",
    "relationship_tier",
    "roster_person_rows",
    "subject_family_tier",
]
