#!/usr/bin/env python3
"""Who is who, and which event is which — resolution that never destroys.

Wave C1 of the audited final timeline build plan (§6.3 "Identity and
episodes", §10 "Event and identity semantics", §2.5). This module answers two
questions the claim substrate deliberately left open:

1. **Which person is this mention about?** ``"AJ"`` should resolve to the known
   AJ when the vault makes that unambiguous — and when it does not, the claim
   is *kept* as an unresolved claim with its candidate set, never dropped.
2. **Which event/episode is this claim about?** A relationship is not one
   timeless fact: first meeting, dating start, engagement and marriage are
   distinct events on one *edge*. A second stint at the same employer is a
   second episode, not an amendment of the first.

It is pure — no I/O, no model, no vault, no clock it does not receive. The
entity roster is taken as an **argument** (a snapshot dict or its entity list),
because ``entity_roster`` imports ``lifehug_core``, ``ai_provider`` and
``recommend_focuses``, and dragging vault paths and a provider into this module
would make it unusable from the worker, the sandboxed prompt seam and the
platform mirror. Callers load the snapshot with ``entity_roster.load_roster()``
and hand it over; the alias *data* still has exactly one owner.

What this module is NOT
-----------------------

The **model-assisted high-confidence nickname link** that §6.3 also permits is
a Wave C listener/platform seam and is deliberately *not* here. What is here is
the deterministic resolver plus :func:`validate_resolution_record` — the record
contract that the deterministic rules and the model rung both emit, so a
resolution's provenance reads the same however it was reached
(``reason="model"`` versus a named deterministic rule).

There is also **no containment folding and no fuzzy matching**. The prior audit
rejected both: a rule that lets ``"Jim"`` silently absorb ``"Jimmy Carter"``,
or that merges two people because their names are three edits apart, destroys
information that no later correction can recover. Every rule in this module is
exact-match plus a uniqueness gate. When exactness runs out, the answer is
``uncertain`` with the candidates attached — which is a Mirror item, not a
guess (§2.5: uncertain surfaces, never drops).

The ladder
----------

In order, each step a *named* rule that appears in the record's ``reason``:

``exact_ref``
    The mention is already a stable entity ref (``person/katie``). Resolution
    is idempotent: running the resolver over an already-resolved ref returns
    the same ref rather than re-deciding it.

``roster_alias`` / ``unique_name``
    The mention's :func:`~temporal_claims.normalized_mention_key` matches the
    roster keys of **exactly one** entity in the whole roster. The reason names
    which kind of key matched: an alias the roster curation already folded
    (``roster_alias``), or the entity's own name/slug (``unique_name``).

``ambiguous_candidates`` / ``no_candidate``
    Everything else. Two or more entities answer to the mention, or none does.
    Either way the resolution is ``uncertain``, the claim is retained, and the
    candidate set travels with it.

A note on why alias-matching is *uniqueness-gated* rather than a strict
precedence rung above name-matching. Consider a roster where entity A is named
``"Mom"`` and entity B carries ``"Mom"`` as an alias. A strict alias-first
ladder silently picks B — a rule that merges two people without saying so,
which is precisely the class the audit rejected. Here that roster yields two
candidates and one honest ``uncertain``. The ordering is preserved where it is
safe (a ref beats a key match; among key matches the reason records which kind
it was) and abandoned exactly where it would become a silent merge.

Episodes
--------

:func:`derive_episode_ref` mints the ``episode`` node id a claim's ``event_ref``
points at, through :func:`temporal_projection.derive_node_id` — the one
identity function — so an episode ref *is* the node id Wave D's projection
publishes. Two rules are enforced rather than documented:

* A **relationship transition** requires a counterpart. It attaches to the
  edge between two people, order-normalized, so ``derive_episode_ref`` gives
  the same answer whichever person is named the subject.
* A **repeatable** episode (job, school, residence, move, military) requires a
  discriminator. Without one, a second stint at the same employer would collide
  with the first and be silently merged — so the ref is refused loudly instead.
  :func:`episode_discriminator` builds the discriminator from the episode's own
  start claim, which is what makes "second Boeing stint" a *second* episode.

Reversibility
-------------

Resolution is data **about** a claim, never mutation **of** it. A claim's
identity derives from its raw ``subject_mention`` (``temporal_claims``
``CLAIM_IDENTITY_KEYS``, which deliberately excludes ``subject_ref``), so
attaching a resolution cannot re-mint the claim — :func:`apply_resolution`
asserts that rather than trusting it. :func:`unresolve` reverses a link without
destroying it: the previously resolved ref stays in the candidate set and the
reversed decision is recorded in ``reverses``.

Controlling contract: the audited final timeline build plan §2.5, §6.3, §10,
and the prior audit's accepted amendment — entity identity is not event or
episode identity, and a display label is never a primary key.
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

SYSTEM_DIR = Path(__file__).resolve().parent
if str(SYSTEM_DIR) not in sys.path:
    sys.path.insert(0, str(SYSTEM_DIR))

from temporal_claims import (
    SCHEMA_VERSION,
    TemporalContractError,
    collapsed_text,
    digest_id,
    normalized_mention_key,
    normalized_timestamp,
    optional_text,
    unit_score,
    validate_temporal_claim,
)
from temporal_projection import (
    derive_node_id,
    validate_temporal_work_item,
)

# --------------------------------------------------------------------------
# The closed vocabularies
# --------------------------------------------------------------------------

#: What a resolution record can say. ``same`` links the mention to an entity;
#: ``different`` records a *negative* link (the model rung or an owner verdict
#: saying "this AJ is not that AJ"), which is knowledge worth keeping and not
#: the same thing as never having looked; ``uncertain`` is the honest answer
#: that keeps the claim and hands the question to Mirror (§2.5).
RESOLUTIONS = ("same", "different", "uncertain")

#: A bare given name BINDS NOBODY when the roster holds more than one person
#: who bears it. A roster may spell one person's whole entry with a single given
#: name ("James", the entry a family landmark minted for the owner's brother)
#: while three other people on the same roster — a son, a father, a grandfather
#: — carry that same given name inside a longer name. The exact-key uniqueness
#: gate reads the short entry as unique and binds *every* bare "James" to it,
#: which is how one ref came to hold two people. The census that decides this is
#: over name TOKENS, not over whole keys, so a name that several people answer
#: to is ambiguous however few of them happen to spell it that way alone.
SHARED_NAME_TOKEN_REASON = "shared_name_token"

#: A given name plus a RELATIONSHIP WORD the roster corroborates: "my son
#: James", "my brother James", "my father James". The relationship word is the
#: distinguishing token that makes the shared given name answerable — it is
#: matched against the roster's own ``relationship`` field, so the roster, not
#: the sentence, is what decides. Still uniqueness-gated: two children named
#: James would leave "my son James" uncertain, as it should.
RELATIONSHIP_QUALIFIED_REASON = "relationship_qualified_name"

#: Named deterministic rules, in ladder order. These are the values ``reason``
#: may take when the resolver reached the verdict on its own.
DETERMINISTIC_REASONS = (
    "exact_ref",
    "roster_alias",
    "unique_name",
    RELATIONSHIP_QUALIFIED_REASON,
    SHARED_NAME_TOKEN_REASON,
    "ambiguous_candidates",
    "no_candidate",
)

#: The reason a resolution reached by the Wave C model rung carries. It is one
#: token on purpose: *which* model and at what version belongs to the claim's
#: ``extractor_version`` and the receipt, not to a free-text reason field.
MODEL_REASON = "model"

#: A person settled it directly (an entity verdict, a Mirror answer).
OWNER_REASON = "owner_verdict"

#: What :func:`unresolve` stamps. It is its own reason so a reversal is
#: legible as a reversal rather than as a fresh failure to resolve.
UNRESOLVED_REASON = "unresolved"

#: The subject a landmark entry that names nobody falls back to is its own
#: DOMAIN word (``landmark_projection.entry_subject_mention``), and for one
#: domain — ``birth`` — that word denotes the person themselves. Receipts
#: filed before design §3.1's extractor rule therefore say ``"birth"`` where
#: they mean ``self``. This is the named deterministic rule that reads them,
#: recorded on the record like every other resolution so it is visible and
#: reversible rather than a silent rewrite of the receipt.
OWNER_BIRTH_DOMAIN_REASON = "owner_birth_domain_word"
#: A roster entity that bears the owner's own name IS the owner. A roster built
#: from the owner's answers will list the owner among the people it found, and
#: resolving "Dave" to that entity drew a hundred of the owner's own moments as
#: somebody else's life. The profile names the owner; the roster does not get
#: to make a stranger of that name.
OWNER_NAME_REASON = "owner_own_name"

#: The legacy spelling that rule answers to.
LEGACY_OWNER_BIRTH_MENTION = "birth"

RESOLUTION_REASONS = DETERMINISTIC_REASONS + (
    OWNER_BIRTH_DOMAIN_REASON,
    OWNER_NAME_REASON,
    MODEL_REASON,
    OWNER_REASON,
    UNRESOLVED_REASON,
)

#: The reasons that mean "we did not decide". Both are ``uncertain``; they
#: differ in whether anybody was in the running.
UNCERTAIN_REASONS = (
    "ambiguous_candidates",
    "no_candidate",
    SHARED_NAME_TOKEN_REASON,
    UNRESOLVED_REASON,
)

#: How a candidate got into the running — the "score-basis" the record carries
#: per candidate, so a human reading a Mirror row can see *why* each name is
#: there rather than only that it is.
CANDIDATE_BASES = ("exact_ref", "alias", "name", "model")

#: Transitions in a relationship. §5.1 and §10: first meeting, dating start,
#: engagement, marriage, separation, divorce and reconciliation are distinct
#: records about the same two people, and each one attaches to the *edge*
#: between them rather than to one person. ``met`` and ``first_met`` are both
#: here because ``temporal_claims.EVENT_KINDS`` seeds ``first_met`` while §5.1's
#: prose says ``met``; accepting both is cheaper than a mismatch that silently
#: routes one of them down the non-relationship path.
RELATIONSHIP_EVENT_KINDS = (
    "met",
    "first_met",
    "dating_started",
    "engaged",
    "married",
    "separated",
    "divorced",
    "reconciled",
)

#: Event kinds a life can hold more than one of. §6.3: "do not collapse every
#: event involving the same people into one timeless relationship", and a
#: repeated school or job period is not one incompatible span (§10). For these,
#: :func:`derive_episode_ref` REFUSES to mint a ref without a discriminator,
#: because a missing discriminator is exactly how a second stint at the same
#: employer silently becomes an edit of the first.
REPEATABLE_EVENT_KINDS = (
    "job",
    "school",
    "move",
    "residence",
    "military",
    "transition",
    "span",
)

#: The other side of that coin, and the one the DUPLICATE class needs: event
#: kinds a life holds AT MOST ONCE for one subject. A person is born once and
#: dies once; a marriage to one named person happens once. So two tellings of
#: one of these about the SAME subject are two tellings of one fact — never two
#: facts — and the deterministic identity binder may join them without asking
#: (`episode_binder.RULE_ID_MILESTONE`).
#:
#: `married` is in the list although a life can hold a second marriage, because
#: the rule that reads this tuple requires the NON-OWNER people named on both
#: sides to agree: "married Katie" and "married Anne" name different subjects
#: and never meet. `graduation` is deliberately ABSENT for the mirror-image
#: reason — high school and college are two graduations of one subject and
#: nothing in the label distinguishes their subjects.
#:
#: **v345 amendment: a marriage is once per COUPLE.** `married` is in this list
#: on a subject rung, and a subject rung cannot see that *"Mom married dad at
#: 21"* (subject `mother`) and *"Parents' wedding date"* (subject `parents`) are
#: one wedding — the owner's own vault held them as two nodes, one of them
#: undated with its own *"when?"* card, beside a third drawn from the `family`
#: landmark. So the milestone rung reads a COUPLE key beside the subject key
#: (:data:`ONCE_PER_COUPLE_EVENT_KINDS`, :func:`couple_key`) and a marriage of
#: one resolved couple is one fact.
ONCE_PER_SUBJECT_EVENT_KINDS = (
    "birth",
    "child_born",
    "death",
    "loss",
    "married",
)

#: v345. The event kinds a COUPLE holds at most once — the other half of
#: :data:`ONCE_PER_SUBJECT_EVENT_KINDS`, and the one the owner's parents' wedding
#: needs. A marriage is the only kind here, and deliberately: a birth and a
#: death happen to one person, so the subject rung already has them; a wedding
#: happens to two, and neither of the two is the fact's discriminator on their
#: own.
ONCE_PER_COUPLE_EVENT_KINDS = ("married",)

#: The relation words that name a COUPLE, mapped to the couple they name.
#:
#: SHORT on purpose, and the omissions are the design. A person has one set of
#: parents and therefore one parents' wedding, so ``mom``/``dad``/``parents``
#: all name the same couple and a telling about any of them is a telling about
#: it. ``grandparents`` is ABSENT for the reason `graduation` is absent from
#: :data:`ONCE_PER_SUBJECT_EVENT_KINDS`: a person has up to four grandparents
#: and two of their weddings, and the bare word discriminates neither — the
#: owner's vault holds "Naming of maternal grandparents" and "Naming of
#: paternal grandparents" side by side. ``wife``/``husband``/``spouse`` ARE here
#: because a wedding told as *"when I got married"* names the owner's own
#: couple and nothing else; a life that holds a SECOND marriage told only by
#: relation and never by name folds onto the first and surfaces a contradiction
#: card naming both dates, which is `episode_binder`'s v340 ruling working
#: rather than failing — two tellings of "my wedding" at two dates is an
#: ambiguity only the person can settle.
COUPLE_OF_RELATION_WORD = {
    "mom": "parents",
    "mommy": "parents",
    "mother": "parents",
    "mum": "parents",
    "mama": "parents",
    "momma": "parents",
    "dad": "parents",
    "daddy": "parents",
    "father": "parents",
    "papa": "parents",
    "poppa": "parents",
    "parent": "parents",
    "parents": "parents",
    "wife": "spouse",
    "husband": "spouse",
    "spouse": "spouse",
}

#: How a couple key is spelled, so no caller composes one by hand.
COUPLE_KEY_PREFIX = "couple"

#: v350. The first-person PLURAL subject words, read as the owner's couple and
#: nowhere else. *"our wedding"*, *"we got married"* — a marriage told in the
#: first person plural on the owner's own timeline is his own, and
#: :data:`ONCE_PER_COUPLE_EVENT_KINDS` is the only vocabulary that consults
#: this, so the reading cannot reach a telling where "we" might be the owner and
#: his brothers. Deliberately NOT added to :data:`OWNER_SUBJECT_MENTIONS`: that
#: set is what drops a mention before two tellings are compared at all, and "we"
#: names somebody besides the owner as well as the owner.
OWNER_COUPLE_SUBJECT_WORDS = frozenset({"we", "us", "our", "ourselves"})

#: v350. The couple a telling belongs to when its own subject is the OWNER.
#: A life holds one *"our wedding"*, so the owner's own subject names his own
#: couple and never anybody else's — which is the leg the owner's wedding
#: reception needed (:data:`episode_binder.A_COUPLE_IS_TWO_PEOPLE`).
OWNER_COUPLE = "spouse"

#: v350, the one sentence.
A_COUPLE_IS_READ_FROM_THE_TELLINGS_OWN_SUBJECTS = (
    "a couple key is read from a telling's own SUBJECTS and never from a word "
    "loose in what it is called: the owner's subject names the owner's couple, "
    "a couple word names that couple, and a compound relationship word is "
    "never the simple word inside it"
)


def couple_relation_word(subject: object) -> str:
    """The COUPLE-naming relationship word one SUBJECT mention states, or ``""``.

    :data:`COUPLE_OF_RELATION_WORD`'s own vocabulary, read whole-token out of a
    mention that may carry a possessive or a qualifier around it — *"Author's
    parents"* states ``parents``, *"my mom"* states ``mom``.

    Compound-aware, and that is the whole reason this function exists rather
    than a dictionary lookup on the mention
    (:data:`A_COMPOUND_RELATION_IS_NEVER_THE_WORD_INSIDE_IT`): *"mother-in-law"*
    states NOTHING here, because she is not the owner's mother and her
    daughter's wedding is not the owner's parents'.
    """
    body = normalized_mention_key(subject)
    if not body or IN_LAW_RE.search(body):
        return ""
    tokens = body.split()
    for index, token in enumerate(tokens):
        if index and tokens[index - 1] in COMPOUND_RELATION_PREFIXES:
            continue
        for candidate in (token, depluralized(token)):
            if candidate in COUPLE_OF_RELATION_WORD:
                return candidate
    return ""


def couple_key(subjects: object) -> str:
    """``"couple:parents"`` for the couple a telling's own SUBJECTS name, else ``""``.

    ``subjects`` are the telling's ``subject_mention`` texts
    (`episode_binder.TellingView.subject_mentions`) — who it is ABOUT, not
    every name it happens to contain. Every one of them must name the SAME
    couple, so ``{mother}``, ``{parents}`` and ``{mom, dad}`` are one key and
    ``{mother, katie}`` is no key at all: a telling about a couple AND somebody
    outside it is not a telling about the couple alone.

    The OWNER's own subject names :data:`OWNER_COUPLE` — ``self``, ``me``,
    ``narrator`` (:data:`OWNER_SUBJECT_MENTIONS`) and the first-person plural
    ``we``/``our`` (:data:`OWNER_COUPLE_SUBJECT_WORDS`). A life holds one
    *"our wedding"*, and a telling about it belongs to that couple rather than
    to whichever relationship word its label mentions.

    A name resolves nothing here: ``{katie}`` has no couple key, and *"Married
    Katie"* meets *"Getting married to Katie"* through the ordinary subject rung
    on the name, which is the discriminator a vault that holds two marriages
    actually has.

    **v350 changed what is read, not what is decided.** It used to be handed
    the telling's non-owner person TOKENS — every name anywhere in it,
    tokenized — and the owner's vault paid for it: *"Wedding reception in
    mother-in-law's backyard"*, the owner's own reception, reached his PARENTS'
    1976 wedding because the word ``mother`` was found inside
    ``mother-in-law``. The subjects are what a telling is about; a word in a
    backyard is not.
    """
    keys = set()
    for subject in subjects or ():
        body = collapsed_text(subject)
        if not body:
            continue
        key = normalized_mention_key(body)
        if key in OWNER_SUBJECT_MENTIONS or key in OWNER_COUPLE_SUBJECT_WORDS:
            keys.add(OWNER_COUPLE)
            continue
        keys.add(COUPLE_OF_RELATION_WORD.get(couple_relation_word(body)))
    if len(keys) != 1:
        return ""
    only = keys.pop()
    return f"{COUPLE_KEY_PREFIX}:{only}" if only else ""


#: Mentions that name the OWNER rather than anybody else. The owner is on every
#: telling, so agreeing about him is not evidence about which event a telling is
#: about (`episode_binder.INDEPENDENT_SIGNALS`' own reason) — these are dropped
#: before a subject is compared.
OWNER_SUBJECT_MENTIONS = frozenset({
    "self", "me", "i", "myself", "narrator", "the narrator",
    "author", "the author", "owner", "the owner",
})

#: Which surfaces an identity work item may reach. §6.3 sends ambiguous
#: identity to Mirror; §2.5 defers Mirror's daily-question convergence to the
#: issue tracked separately, so ``daily_question`` is deliberately absent.
IDENTITY_WORK_SURFACES = ("mirror", "timeline")

#: The field an identity work item asks for.
IDENTITY_REQUESTED_FIELD = "identity"

#: Prefix for a relationship edge id. An edge is not a node — it is the
#: event-kind-free grouping key that proves "dating started in 2005" and
#: "married in 2007" are two facts about ONE pair of people.
EDGE_ID_PREFIX = "edge"

#: Prefix for the handle standing in for a subject that has not resolved.
#: It is a handle, never an entity ref: the amendment says a display label is
#: never a primary key, and this is what keeps an unresolved mention from
#: being mistaken for a resolved identity downstream. It is derived from the
#: mention key, so the same unresolved mention produces the same work item
#: across Timeline, Mirror and the queue — one row, not one per sighting.
UNRESOLVED_REF_PREFIX = "unresolved"

#: Keys on a roster entity this module reads. Nothing else is touched:
#: ``entity_roster`` owns the roster's internals and this module is a reader.
ROSTER_NAME_KEYS = ("name", "slug")
ROSTER_ALIAS_KEY = "aliases"

#: The roster field that says how this person stands to the owner. Written by
#: the family landmark recorder and by roster curation; read here only to
#: corroborate a relationship word the mention itself supplied.
ROSTER_RELATIONSHIP_KEY = "relationship"

#: The roster field that says a row is a DUPLICATE of another row — curation
#: found this spelling already answers to an existing Focus and pointed it
#: there rather than minting a second page for it (`entity_roster.py`'s own
#: convention; `entity_candidate.py`, `entity_verdict.py`, `wiki_compile.py`
#: and every other reader already treat a non-null value here as "this row is
#: not its own identity"). `roster_index` is the one place that convention
#: reaches identity resolution (v343, `timeline-rules:13`): a row with this
#: field set contributes NO ref, NO key and NO census token — every spelling
#: it carries is expected to already be curated onto the row it maps to, so a
#: bare "James" no longer runs against both the alias row AND its target as
#: if they were two different people.
ROSTER_MAPS_TO_FOCUS_KEY = "maps_to_focus"

#: Determiners and possessives a mention may wrap a name in. They carry no
#: identity, so they are dropped before a mention's tokens are counted —
#: "my son James" and "our son James" are the same three-token question.
MENTION_QUALIFIER_WORDS = frozenset(
    {"a", "an", "the", "my", "our", "his", "her", "their", "its", "of", "and"}
)

#: Relationship words a mention may carry, mapped to the roster
#: ``relationship`` values that satisfy them. A word resolves nothing on its
#: own; it only narrows the people a shared given name could mean.
RELATIONSHIP_MENTION_WORDS = {
    "son": frozenset({"child", "son"}),
    "daughter": frozenset({"child", "daughter"}),
    "child": frozenset({"child", "son", "daughter"}),
    "kid": frozenset({"child", "son", "daughter"}),
    "brother": frozenset({"sibling", "brother"}),
    "sister": frozenset({"sibling", "sister"}),
    "sibling": frozenset({"sibling", "brother", "sister"}),
    "dad": frozenset({"parent", "father"}),
    "father": frozenset({"parent", "father"}),
    "mom": frozenset({"parent", "mother"}),
    "mother": frozenset({"parent", "mother"}),
    "parent": frozenset({"parent", "father", "mother"}),
    "grandpa": frozenset({"grandparent", "grandfather"}),
    "grandfather": frozenset({"grandparent", "grandfather"}),
    "grandma": frozenset({"grandparent", "grandmother"}),
    "grandmother": frozenset({"grandparent", "grandmother"}),
    "grandparent": frozenset({"grandparent", "grandfather", "grandmother"}),
    "wife": frozenset({"spouse", "wife", "partner"}),
    "husband": frozenset({"spouse", "husband", "partner"}),
    "spouse": frozenset({"spouse", "wife", "husband", "partner"}),
    "uncle": frozenset({"uncle"}),
    "aunt": frozenset({"aunt"}),
    "cousin": frozenset({"cousin"}),
    "nephew": frozenset({"nephew"}),
    "niece": frozenset({"niece"}),
}


#: An in-law is never immediate family, whatever relation word the phrase is
#: built out of — "mother-in-law" contains "mother" and is not the owner's
#: mother. Checked on the WHOLE mention before any word is read, because the
#: hyphenated word is the thing that changes the answer.
#:
#: **v350 moved it here**, beside the vocabulary it is a reading OF.
#: `axis_membership.IN_LAW_RE` is this same object under its historical name
#: (that module is what `roster_relations` reads it through), and it had to
#: move because the reading is now needed by `episode_containers` — which
#: `axis_membership` imports, so the old seat could not be imported back.
IN_LAW_RE = re.compile(r"(?<!\w)in[-\s]?laws?(?!\w)", re.IGNORECASE)

#: The words that COMPOUND a relationship word into a DIFFERENT relationship.
#: A step-mother is not a mother, a grandmother is not a mother, a half-brother
#: is not a brother, an ex-wife is not a wife. Kept as the words that stand in
#: FRONT of the simple word, because the one that stands behind it is the
#: in-law suffix and :data:`IN_LAW_RE` is already its one reading.
#:
#: ``grandmother`` and ``grandparent`` are also whole entries of
#: :data:`RELATIONSHIP_MENTION_WORDS` in their own right — the single-word
#: spelling never needed this list, because a whole-token vocabulary has never
#: read ``mother`` out of ``grandmother``. This list is for the spellings a
#: person actually writes with a hyphen or a space in them.
COMPOUND_RELATION_PREFIXES = frozenset({
    "step", "grand", "great", "half", "god", "foster", "adoptive", "ex",
    "former", "late",
})

#: v350, and the analogue of v347's `roster_relations._NOT_A_POSSESSOR`: the
#: rule that a relationship word is only the word it IS.
A_COMPOUND_RELATION_IS_NEVER_THE_WORD_INSIDE_IT = (
    "a compound relationship word is never the simple word inside it: "
    "mother-in-law is not mother, step-mother is not mother, ex-wife is not "
    "wife — so neither the roster nor a couple key may read the simple word "
    "out of the compound one"
)


def depluralized(text: object) -> str:
    """``"parents"`` -> ``"parent"``; anything already singular is unchanged.

    The one plural reading this module does, so a vocabulary keyed on singular
    words can still answer about the plural a person wrote. Deliberately
    shallow — ``s`` off a word of more than three characters that does not end
    in ``ss`` — which is `axis_membership._singularized`'s own rule for the
    same job on the tier side.
    """
    body = collapsed_text(text).casefold()
    if len(body) > 3 and body.endswith("s") and not body.endswith("ss"):
        return body[:-1]
    return body


def relation_word_stem(text: object) -> str:
    """The :data:`RELATIONSHIP_MENTION_WORDS` word ``text`` IS, or ``""``.

    Whole-word, singular or plural. ``"grandson"`` is not ``"son"`` and
    ``"childhood"`` is not ``"child"``, for the reason
    `roster_relations._relation_words_in` says so: the vocabulary is read whole
    tokens in both directions.
    """
    body = normalized_mention_key(text)
    for candidate in (body, depluralized(body)):
        if candidate in RELATIONSHIP_MENTION_WORDS:
            return candidate
    return ""


def _not_a_simple_relation(tokens: object, start: int, end: int) -> bool:
    """Do the words AROUND ``tokens[start:end]`` make it a COMPOUND relation?

    :data:`A_COMPOUND_RELATION_IS_NEVER_THE_WORD_INSIDE_IT`, as the token-level
    predicate a run-matching reader needs. It answers only about a run that is
    ONE relationship word — a longer key is the compound itself and matching it
    is the right answer, and a run that is no relationship word at all has no
    compound to be part of.

    :data:`A_COMPOUND_RELATION_IS_NEVER_THE_WORD_INSIDE_IT`, as the token-level
    predicate a run-matching reader needs.

    Two ways the surrounding words change the answer, and both are read from a
    declaration rather than a case list. The tokens BEHIND the run read as an
    in-law suffix through :data:`IN_LAW_RE` — which is how ``"mother"`` inside
    ``"mother-in-law's backyard"`` stops being the owner's mother, and how the
    roster alias ``"my mother"`` stops being her inside ``"my mother-in-law"``.
    Or the token in FRONT of the run is one of
    :data:`COMPOUND_RELATION_PREFIXES` — ``"step mother"``, ``"ex wife"``.

    It answers only about a run that ENDS (for the suffix) or BEGINS (for the
    prefix) on a relationship word. A run whose own last token is ``law`` is the
    compound itself and matching it is the right answer: a roster that knows a
    mother-in-law by that phrase resolves her by it.
    """
    words = [normalized_mention_key(token) for token in tokens or ()]
    if not (0 <= start < end <= len(words)):
        return False
    if relation_word_stem(words[end - 1]) and IN_LAW_RE.search(
        " ".join(words[end:end + 2])
    ):
        return True
    return bool(
        start
        and relation_word_stem(words[start])
        and words[start - 1] in COMPOUND_RELATION_PREFIXES
    )


class IdentityResolutionError(TemporalContractError):
    """A resolution record or an episode ref that cannot be trusted."""


ERROR_CODES = (
    "resolution_not_a_mapping",
    "resolution_needs_mention",
    "unknown_resolution",
    "unknown_resolution_reason",
    "unknown_candidate_basis",
    "candidate_needs_ref",
    "resolution_needs_evidence",
    "resolved_ref_required",
    "resolved_ref_forbidden",
    "resolved_ref_not_a_candidate",
    "ambiguous_needs_candidates",
    "no_candidate_has_candidates",
    "resolution_not_reversible",
    "resolution_would_remint",
    "owner_ref_required",
    "episode_needs_event_kind",
    "episode_needs_subject",
    "episode_needs_counterpart",
    "episode_needs_discriminator",
    "edge_needs_two_subjects",
    "timestamp_unusable",
    "score_out_of_range",
)


# --------------------------------------------------------------------------
# The roster, read as a snapshot
# --------------------------------------------------------------------------


def entity_ref(entity_type: object, slug: object) -> str:
    """``person/katie`` — the ref shape the rest of the substrate already uses.

    It is a *type plus slug*, never a display name, so renaming "Mom" to
    "Desi" on a page does not re-point every claim that ever mentioned her.
    """
    kind = normalized_mention_key(entity_type).replace(" ", "_") or "entity"
    tail = normalized_mention_key(slug).replace(" ", "-")
    return f"{kind}/{tail}"


def _entity_slug(entity: dict) -> str:
    """The entity's slug, falling back to its name.

    ``entity_roster`` slugifies through ``lifehug_core.slugify``; importing it
    here would pull vault paths into a pure module, so the fallback re-derives
    a slug from the mention key (lowercase, unpunctuated, hyphen-joined) and is
    only ever reached for a snapshot entry that has no ``slug`` at all. Rosters
    written by ``entity_roster.write_roster`` always carry one.
    """
    slug = collapsed_text(entity.get("slug"))
    if slug:
        return normalized_mention_key(slug).replace(" ", "-")
    return normalized_mention_key(entity.get("name")).replace(" ", "-")


@dataclass(frozen=True)
class RosterCandidate:
    """One entity the roster offers for a mention, and why it is in the running."""

    ref: str
    name: str
    basis: str

    def to_dict(self) -> dict:
        return {"ref": self.ref, "name": self.name, "basis": self.basis}


@dataclass(frozen=True)
class RosterIndex:
    """An immutable read model over one roster snapshot.

    Built once, queried many times. It holds only what resolution needs — the
    ref, the display name, and the exact keys each entity answers to, split by
    whether the key came from the entity's own name/slug or from curated alias
    data, because the split is what the ``reason`` reports.
    """

    entity_type: str = "person"
    refs: dict = field(default_factory=dict)
    by_name_key: dict = field(default_factory=dict)
    by_alias_key: dict = field(default_factory=dict)
    #: One name TOKEN -> every ref that bears it anywhere in a name, slug or
    #: alias. This is the census :data:`SHARED_NAME_TOKEN_REASON` reads. It is
    #: only ever used to DENY a binding, never to create one: a rule that let a
    #: token reach into a longer name to bind it would be the containment
    #: folding this module's docstring rejects.
    by_name_token: dict = field(default_factory=dict)
    #: One GIVEN name -> every ref that answers to it: the first word of each
    #: name, slug and alias, plus any spelling that is that word entire. This —
    #: not :attr:`by_name_token` — is the census the bare-name gate reads,
    #: because a name buried inside somebody else's is not a name they answer
    #: to. The owner whose whole spelling is "Pat Quincy Example" does not
    #: answer to "Quincy", so a stranger named Quincy still resolves; three
    #: Jameses whose names BEGIN with James all answer to "James", so that word
    #: answers nobody. (The middle-name half is the same rule
    #: ``temporal_publication.owner_names_from_profile`` already applies to the
    #: owner's own name: whole spellings only.)
    by_given_name: dict = field(default_factory=dict)
    #: ref -> the roster's own ``relationship`` value, normalized.
    relationship_of: dict = field(default_factory=dict)

    def size(self) -> int:
        return len(self.refs)

    def refs_bearing(self, token: object) -> tuple[str, ...]:
        """Every ref whose name, slug or alias contains this exact token."""
        return self.by_name_token.get(normalized_mention_key(token), ())

    def refs_named(self, token: object) -> tuple[str, ...]:
        """Every ref that ANSWERS to this word — a given name, not a middle one."""
        return self.by_given_name.get(normalized_mention_key(token), ())

    def name_of(self, ref: object) -> str:
        return self.refs.get(collapsed_text(ref), "")

    def has_ref(self, ref: object) -> bool:
        return collapsed_text(ref) in self.refs


#: A DELIBERATE DUPLICATE of `entity_roster.ROLE_WORDS`, never an import of
#: it. This module's own purity contract (`test_identity_resolution
#: .RosterReadTests.test_the_module_never_imports_the_roster_module_or_any_io`
#: — "safe to vendor into the worker and the sandboxed prompt seam") forbids
#: importing `entity_roster` at all, lazily or otherwise, the same way
#: :func:`_entity_slug`'s own docstring already re-derives a slug rather than
#: importing `lifehug_core.slugify`. `tests/test_v343_card_quality_gate.py`
#: asserts this set stays a subset of the live `entity_roster.ROLE_WORDS` so
#: the two cannot silently drift.
_COLLECTIVE_ROLE_WORDS = frozenset({
    "mom", "dad", "mother", "father", "brother", "sister", "friend", "mentor",
    "boss", "wife", "husband", "partner", "son", "daughter", "grandma", "grandpa",
    "grandfather", "grandmother", "uncle", "aunt", "cousin", "teacher", "coach",
    "pastor", "priest", "therapist", "neighbor", "colleague", "roommate",
    "boyfriend", "girlfriend", "fiance", "stepmother", "stepfather", "kids",
    "child", "children", "parent", "parents", "family", "spouse",
})


def roster_index(snapshot: object, *, entity_type: object = None) -> RosterIndex:
    """Build the read model from an ``entity_roster`` snapshot.

    Accepts what ``entity_roster.load_roster()`` returns (``{"type": ...,
    "entities": [...]}``), a bare list of entities, or an already-built
    :class:`RosterIndex` (so callers may pass either through the resolver
    without branching).

    Entities the owner marked ``owner_verdict: never`` are kept. That verdict
    suppresses a wiki *page*; ``entity_roster`` says so in its own comment
    ("suppression is about pages, not alias folding"), and an unresolvable
    mention is a worse outcome than a resolved mention with no page.

    Two v343 (`timeline-rules:13`) exclusions, both narrow and both read off
    an existing roster convention rather than a new one:

    * A row with :data:`ROSTER_MAPS_TO_FOCUS_KEY` set is dropped ENTIRELY —
      no ref, no exact key, no census token. It is curation's own statement
      that this spelling is not a second identity (see the field's
      docstring), so a "James" alias row naming the same person as
      "Anthon James Taylor" never again runs as its own candidate.
    * A person row whose name or slug is a bare collective/role word
      (`entity_roster.ROLE_WORDS` — "Kids", "Parents", ...) keeps its exact
      keys (a mention that says "the kids" still means them) but never
      enters the CENSUS (:attr:`RosterIndex.by_name_token` /
      :attr:`RosterIndex.by_given_name`): a collective's own alias ("Dave's
      kids") starting with the owner's first name must not make that name
      "ambiguous" against a group nobody meant.
    """
    if isinstance(snapshot, RosterIndex):
        return snapshot
    if isinstance(snapshot, dict):
        entities = snapshot.get("entities") or []
        kind = collapsed_text(entity_type) or collapsed_text(snapshot.get("type")) or "person"
    else:
        entities = list(snapshot or ())
        kind = collapsed_text(entity_type) or "person"

    role_words = _COLLECTIVE_ROLE_WORDS
    refs: dict = {}
    by_name_key: dict = {}
    by_alias_key: dict = {}
    by_name_token: dict = {}
    by_given_name: dict = {}
    relationship_of: dict = {}
    for entity in entities:
        if not isinstance(entity, dict):
            continue
        if collapsed_text(entity.get(ROSTER_MAPS_TO_FOCUS_KEY)):
            continue
        name = collapsed_text(entity.get("name"))
        slug = _entity_slug(entity)
        if not name and not slug:
            continue
        ref = entity_ref(kind, slug or name)
        refs.setdefault(ref, name or slug)

        relationship = normalized_mention_key(entity.get(ROSTER_RELATIONSHIP_KEY))
        if relationship:
            relationship_of.setdefault(ref, relationship)

        is_collective = kind == "person" and (
            normalized_mention_key(name) in role_words
            or normalized_mention_key(slug) in role_words
        )

        keys: list[str] = []
        for key_field in ROSTER_NAME_KEYS:
            key = normalized_mention_key(entity.get(key_field))
            if key:
                keys.append(key)
                by_name_key.setdefault(key, []).append(ref)
        raw_aliases = entity.get(ROSTER_ALIAS_KEY) or ()
        if isinstance(raw_aliases, (str, bytes)):
            raw_aliases = [raw_aliases]
        for alias in raw_aliases:
            key = normalized_mention_key(alias)
            if key:
                keys.append(key)
                by_alias_key.setdefault(key, []).append(ref)

        if is_collective:
            continue

        # The token census. Every word of every spelling this person answers to,
        # counted per REF, so one person spelled five ways is still one person.
        for key in keys:
            words = [
                token
                for token in key.split()
                if token not in MENTION_QUALIFIER_WORDS and len(token) >= 2
            ]
            for token in words:
                by_name_token.setdefault(token, []).append(ref)
            if words:
                by_given_name.setdefault(words[0], []).append(ref)

    return RosterIndex(
        entity_type=kind,
        refs=refs,
        by_name_key={k: tuple(dict.fromkeys(v)) for k, v in by_name_key.items()},
        by_alias_key={k: tuple(dict.fromkeys(v)) for k, v in by_alias_key.items()},
        by_name_token={k: tuple(dict.fromkeys(v)) for k, v in by_name_token.items()},
        by_given_name={k: tuple(dict.fromkeys(v)) for k, v in by_given_name.items()},
        relationship_of=relationship_of,
    )


# --------------------------------------------------------------------------
# The resolution record
# --------------------------------------------------------------------------


def unresolved_subject_ref(mention: object) -> str:
    """``unresolved:<mention key>`` — a handle, never an entity ref.

    Deterministic in the mention, so every sighting of the same unresolved name
    produces the same work-item identity: one Mirror row for "who is AJ?", not
    one per claim (§5.4's "answer once, update everywhere"). It carries no
    ``/`` so it is a legal document id on the hosted side.
    """
    key = normalized_mention_key(mention)
    return f"{UNRESOLVED_REF_PREFIX}:{key}" if key else UNRESOLVED_REF_PREFIX


def is_unresolved_ref(value: object) -> bool:
    """Is this a handle for an unresolved mention rather than a real ref?"""
    text = collapsed_text(value)
    return text == UNRESOLVED_REF_PREFIX or text.startswith(f"{UNRESOLVED_REF_PREFIX}:")


def _candidate_dict(value: object) -> dict:
    """Normalize one candidate, or raise."""
    if isinstance(value, RosterCandidate):
        value = value.to_dict()
    if isinstance(value, (str, bytes)):
        value = {"ref": value}
    if not isinstance(value, dict):
        raise IdentityResolutionError(
            "candidate_needs_ref", "a candidate is a mapping with a ref"
        )
    ref = collapsed_text(value.get("ref"))
    if not ref:
        raise IdentityResolutionError(
            "candidate_needs_ref", "a candidate without a ref names nobody"
        )
    basis = collapsed_text(value.get("basis")) or "name"
    if basis not in CANDIDATE_BASES:
        raise IdentityResolutionError(
            "unknown_candidate_basis", f"unknown candidate basis: {basis!r}"
        )
    candidate: dict = {"ref": ref, "name": collapsed_text(value.get("name")), "basis": basis}
    if value.get("score") is not None:
        try:
            candidate["score"] = unit_score(value.get("score"), error=IdentityResolutionError)
        except TemporalContractError as exc:
            raise IdentityResolutionError("score_out_of_range", exc.message) from None
    return candidate


def validate_resolution_record(value: object, *, now: object = None) -> dict:
    """Normalize a resolution record or raise :class:`IdentityResolutionError`.

    This is the door every resolution goes through, deterministic or model, so
    the two cannot describe the same decision differently. The refusals that
    carry §6.3's weight:

    * ``resolution_needs_mention`` — the raw mention is the record's spine. A
      resolution that dropped it could not be reversed, because the thing being
      reversed *to* would be gone.
    * ``resolution_needs_evidence`` — a link with no evidence is an assertion,
      and §6.3 requires the evidence be preserved so the link is reversible.
    * ``resolved_ref_required`` / ``resolved_ref_forbidden`` — ``same`` names
      exactly one ref; ``different`` and ``uncertain`` name none. An "uncertain"
      record still carrying a resolved ref is a guess wearing a hedge.
    * ``resolved_ref_not_a_candidate`` — the answer must be one of the names
      that was in the running, so a Mirror row can show the alternatives that
      lost rather than a ref that appeared from nowhere.
    * ``ambiguous_needs_candidates`` — ambiguity *is* the candidate set. An
      ambiguous record with no candidates gives Mirror nothing to offer.
    * ``resolution_not_reversible`` — ``reversible`` is a stated property of
      this contract, not a per-record choice; a caller trying to write an
      irreversible resolution is refused.
    """
    if isinstance(value, ResolutionRecord):
        value = value.to_dict()
    if not isinstance(value, dict):
        raise IdentityResolutionError(
            "resolution_not_a_mapping", "a resolution record must be a mapping"
        )

    mention = collapsed_text(value.get("mention"))
    if not mention:
        raise IdentityResolutionError(
            "resolution_needs_mention", "a resolution record keeps the raw mention"
        )

    resolution = collapsed_text(value.get("resolution"))
    if resolution not in RESOLUTIONS:
        raise IdentityResolutionError(
            "unknown_resolution", f"unknown resolution: {resolution!r}"
        )

    reason = collapsed_text(value.get("reason"))
    if reason not in RESOLUTION_REASONS:
        raise IdentityResolutionError(
            "unknown_resolution_reason", f"unknown reason: {reason!r}"
        )

    evidence_ref = optional_text(value.get("evidence_ref"))
    if not evidence_ref:
        raise IdentityResolutionError(
            "resolution_needs_evidence",
            "a resolution cites the claim or span it was drawn from",
        )

    raw_candidates = value.get("candidates")
    if isinstance(raw_candidates, (str, bytes, dict, RosterCandidate)):
        raw_candidates = [raw_candidates]
    candidates: list[dict] = []
    seen: set[str] = set()
    for raw in raw_candidates or ():
        candidate = _candidate_dict(raw)
        if candidate["ref"] in seen:
            continue
        seen.add(candidate["ref"])
        candidates.append(candidate)

    resolved_ref = optional_text(value.get("resolved_ref"))
    if resolution == "same":
        if not resolved_ref:
            raise IdentityResolutionError(
                "resolved_ref_required", "a 'same' resolution names the ref it resolved to"
            )
        if resolved_ref not in seen:
            raise IdentityResolutionError(
                "resolved_ref_not_a_candidate",
                f"{resolved_ref!r} was never a candidate for {mention!r}",
            )
    elif resolved_ref:
        raise IdentityResolutionError(
            "resolved_ref_forbidden",
            f"a {resolution!r} resolution cannot carry a resolved ref",
        )

    if reason == "ambiguous_candidates" and len(candidates) < 2:
        raise IdentityResolutionError(
            "ambiguous_needs_candidates",
            f"ambiguity is the candidate set, got {len(candidates)}",
        )
    if reason == "no_candidate" and candidates:
        raise IdentityResolutionError(
            "no_candidate_has_candidates",
            f"'no_candidate' contradicts {len(candidates)} candidate(s)",
        )

    if value.get("reversible") is False:
        raise IdentityResolutionError(
            "resolution_not_reversible",
            "every resolution in this substrate is reversible; see unresolve()",
        )

    created_at = normalized_timestamp(
        value.get("created_at") or now, error=IdentityResolutionError
    )

    normalized: dict = {
        "schema_version": SCHEMA_VERSION,
        "mention": mention,
        "mention_key": normalized_mention_key(mention),
        "candidates": candidates,
        "resolution": resolution,
        "reason": reason,
        "evidence_ref": evidence_ref,
        "reversible": True,
        "created_at": created_at,
    }
    if resolved_ref:
        normalized["resolved_ref"] = resolved_ref
    if value.get("confidence") is not None:
        try:
            normalized["confidence"] = unit_score(
                value.get("confidence"), error=IdentityResolutionError
            )
        except TemporalContractError as exc:
            raise IdentityResolutionError("score_out_of_range", exc.message) from None
    reverses = value.get("reverses")
    if isinstance(reverses, dict) and reverses:
        normalized["reverses"] = {
            key: reverses[key]
            for key in ("resolution", "resolved_ref", "reason", "created_at")
            if reverses.get(key)
        }
    return normalized


@dataclass(frozen=True)
class ResolutionRecord:
    """§6.3's reversible link: the mention, who it could be, what we decided, why.

    ``reversible`` is a constant rather than a field a writer may set — see
    :func:`unresolve`. ``reverses`` is the audit trail of a reversal: the
    decision that was undone, kept so that undoing an undo is possible and so
    that a Mirror row can say what changed.
    """

    mention: str
    resolution: str
    reason: str
    evidence_ref: str
    mention_key: str = ""
    candidates: tuple[dict, ...] = ()
    resolved_ref: str | None = None
    confidence: float | None = None
    created_at: str = ""
    reverses: dict | None = None
    schema_version: int = SCHEMA_VERSION

    @property
    def reversible(self) -> bool:
        return True

    def to_dict(self) -> dict:
        payload: dict = {
            "schema_version": self.schema_version,
            "mention": self.mention,
            "mention_key": self.mention_key or normalized_mention_key(self.mention),
            "candidates": [dict(c) for c in self.candidates],
            "resolution": self.resolution,
            "reason": self.reason,
            "evidence_ref": self.evidence_ref,
            "reversible": True,
            "created_at": self.created_at,
        }
        for key, value in (
            ("resolved_ref", self.resolved_ref),
            ("confidence", self.confidence),
            ("reverses", self.reverses),
        ):
            if value is not None:
                payload[key] = value
        return payload

    def is_resolved(self) -> bool:
        return self.resolution == "same" and bool(self.resolved_ref)


def resolution_record(value: object, *, now: object = None) -> ResolutionRecord:
    """Validate and build. The strict constructor every writer should use."""
    normalized = validate_resolution_record(value, now=now)
    return record_from_dict(normalized)


def record_from_dict(value: object) -> ResolutionRecord | None:
    """Tolerant reader — ``None`` rather than an exception (the substrate's rule)."""
    try:
        normalized = validate_resolution_record(value)
    except TemporalContractError:
        return None
    return ResolutionRecord(
        mention=normalized["mention"],
        mention_key=normalized["mention_key"],
        candidates=tuple(normalized["candidates"]),
        resolution=normalized["resolution"],
        reason=normalized["reason"],
        evidence_ref=normalized["evidence_ref"],
        resolved_ref=normalized.get("resolved_ref"),
        confidence=normalized.get("confidence"),
        created_at=normalized["created_at"],
        reverses=normalized.get("reverses"),
        schema_version=normalized["schema_version"],
    )


# --------------------------------------------------------------------------
# The deterministic resolver
# --------------------------------------------------------------------------


def candidates_for(mention: object, roster: object, *, entity_type: object = None) -> tuple[dict, ...]:
    """Every roster entity that answers to this mention, exactly.

    Exposed so a caller — including the Wave C model rung, which must choose
    *among the deterministic candidate set* rather than invent a name — can see
    the running without committing to a verdict. Exact keys only: no
    containment, no edit distance, no first-name folding.
    """
    index = roster_index(roster, entity_type=entity_type)
    key = normalized_mention_key(mention)
    text = collapsed_text(mention)

    if index.has_ref(text):
        return (
            RosterCandidate(ref=text, name=index.name_of(text), basis="exact_ref").to_dict(),
        )

    out: list[dict] = []
    seen: set[str] = set()
    for ref in index.by_name_key.get(key, ()):
        if ref in seen:
            continue
        seen.add(ref)
        out.append(RosterCandidate(ref=ref, name=index.name_of(ref), basis="name").to_dict())
    for ref in index.by_alias_key.get(key, ()):
        if ref in seen:
            continue
        seen.add(ref)
        out.append(RosterCandidate(ref=ref, name=index.name_of(ref), basis="alias").to_dict())
    return tuple(out)


def mention_tokens(mention: object) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Split a mention into ``(name_tokens, relationship_words)``.

    Determiners and possessives are dropped (:data:`MENTION_QUALIFIER_WORDS`),
    a word :data:`RELATIONSHIP_MENTION_WORDS` knows becomes a relationship word,
    and everything else is a name token. Order is preserved and duplicates are
    kept out, so ``"my son James"`` is ``(("james",), ("son",))`` and
    ``"James Edwin Taylor Sr"`` is ``(("james", "edwin", "taylor", "sr"), ())``.

    A word can only be one or the other, which is why "Dad" alone yields no name
    token at all: it is a relationship word, and a mention that names no name
    has nothing for the bare-given-name gate to be bare *about*. That mention
    resolves — or does not — through the ordinary exact-key path, exactly as it
    did before this rule existed.
    """
    names: list[str] = []
    relations: list[str] = []
    for token in normalized_mention_key(mention).split():
        if token in MENTION_QUALIFIER_WORDS:
            continue
        if token in RELATIONSHIP_MENTION_WORDS:
            if token not in relations:
                relations.append(token)
        elif token not in names:
            names.append(token)
    return tuple(names), tuple(relations)


def shared_name_token_refs(
    mention: object, roster: object, *, entity_type: object = None
) -> tuple[str, ...]:
    """The refs that make a BARE given name unanswerable, or ``()``.

    A mention is bare when its meaningful words are exactly one name token and
    no relationship word narrows it. Such a mention is unanswerable the moment
    two or more roster people ANSWER to that token — the son *James* Everett
    Taylor, the brother whose roster entry is spelled only ``James``, the father
    *James* Edwin Taylor, the grandfather *James* Edwin Taylor Sr. Answering is
    :attr:`RosterIndex.by_given_name`, so a word that merely sits inside somebody
    else's name does not count: a person named Quincy still resolves next to an
    owner spelled "Pat Quincy Example". Returned in roster order so the candidate
    set, and therefore the Mirror row's wording, is deterministic.

    Empty when the mention is not bare, or when at most one person bears the
    token — a vault with one Della still resolves "Della" on sight.
    """
    names, relations = mention_tokens(mention)
    if relations or len(names) != 1:
        return ()
    index = roster_index(roster, entity_type=entity_type)
    bearers = index.refs_named(names[0])
    return bearers if len(bearers) > 1 else ()


def relationship_qualified_candidates(
    mention: object, roster: object, *, entity_type: object = None
) -> tuple[dict, ...]:
    """Candidates for a mention whose relationship word the ROSTER corroborates.

    ``"my son James"`` names a given name several people share plus one word
    that only one of them satisfies. The narrowing is done by the roster's own
    ``relationship`` field, never by the sentence: a person whose roster entry
    says nothing about how they stand to the owner is never pulled in by a
    relationship word, and every name token in the mention must be borne by the
    candidate, so ``"my son James Everett"`` is at least as narrow as
    ``"my son James"`` and never wider.

    This rung is consulted only when no exact key matched, so it can never
    override a curated alias or a full name — and it is uniqueness-gated by
    :func:`resolve_mention` like every other rung, so two sons named James leave
    the mention uncertain rather than picking one.
    """
    names, relations = mention_tokens(mention)
    if not names or not relations:
        return ()
    index = roster_index(roster, entity_type=entity_type)
    wanted: set[str] = set()
    for word in relations:
        wanted |= RELATIONSHIP_MENTION_WORDS.get(word, frozenset())
    if not wanted:
        return ()

    bearers = [set(index.refs_bearing(token)) for token in names]
    shared = set.intersection(*bearers) if bearers else set()
    out: list[dict] = []
    for ref in index.refs:
        if ref not in shared:
            continue
        if index.relationship_of.get(ref, "") not in wanted:
            continue
        out.append(
            RosterCandidate(ref=ref, name=index.name_of(ref), basis="name").to_dict()
        )
    return tuple(out)


def resolve_mention(
    mention: object,
    *,
    roster: object = (),
    evidence_ref: object,
    entity_type: object = None,
    now: object = None,
) -> ResolutionRecord:
    """Resolve one raw mention against a roster snapshot, deterministically.

    Returns a validated :class:`ResolutionRecord` in every case — including
    when nothing resolves, because "we looked and could not tell" is knowledge
    the claim should carry (§2.5: uncertain surfaces, never drops). The caller
    attaches it with :func:`apply_resolution`; the claim is never modified here
    and never re-minted anywhere.

    The verdict is ``same`` only when exactly one entity answers to the mention.
    Two or more is ``uncertain`` with the full running attached, which
    :func:`identity_work_item` turns into a Mirror row. ``different`` is never
    produced by this function: a deterministic exact-match resolver has no way
    to learn that two names denote different people, so that verdict belongs to
    the model rung and to owner judgment, both of which write through
    :func:`resolution_record`.
    """
    matches = candidates_for(mention, roster, entity_type=entity_type)

    if len(matches) == 1:
        only = matches[0]
        # An already-resolved ref is idempotent and answers to nothing else, so
        # the bare-name census does not apply to it. For a name or alias match,
        # the census is the gate: one exact key is not uniqueness when the vault
        # holds several people who answer to that word.
        if only["basis"] != "exact_ref":
            shared = shared_name_token_refs(mention, roster, entity_type=entity_type)
            if shared:
                index = roster_index(roster, entity_type=entity_type)
                return resolution_record(
                    {
                        "mention": mention,
                        "candidates": [
                            RosterCandidate(
                                ref=ref, name=index.name_of(ref), basis="name"
                            ).to_dict()
                            for ref in shared
                        ],
                        "resolution": "uncertain",
                        "reason": SHARED_NAME_TOKEN_REASON,
                        "evidence_ref": evidence_ref,
                    },
                    now=now,
                )
        reason = {
            "exact_ref": "exact_ref",
            "alias": "roster_alias",
            "name": "unique_name",
        }.get(only["basis"], "unique_name")
        return resolution_record(
            {
                "mention": mention,
                "candidates": matches,
                "resolution": "same",
                "resolved_ref": only["ref"],
                "reason": reason,
                "evidence_ref": evidence_ref,
            },
            now=now,
        )

    if not matches:
        qualified = relationship_qualified_candidates(
            mention, roster, entity_type=entity_type
        )
        if len(qualified) == 1:
            return resolution_record(
                {
                    "mention": mention,
                    "candidates": qualified,
                    "resolution": "same",
                    "resolved_ref": qualified[0]["ref"],
                    "reason": RELATIONSHIP_QUALIFIED_REASON,
                    "evidence_ref": evidence_ref,
                },
                now=now,
            )
        if len(qualified) > 1:
            return resolution_record(
                {
                    "mention": mention,
                    "candidates": qualified,
                    "resolution": "uncertain",
                    "reason": "ambiguous_candidates",
                    "evidence_ref": evidence_ref,
                },
                now=now,
            )
        shared = shared_name_token_refs(mention, roster, entity_type=entity_type)
        if shared:
            # No exact key matched, but the bare word is one several people
            # bear. Reporting *who* is what turns it into an answerable Mirror
            # row instead of a nameless "no candidate".
            index = roster_index(roster, entity_type=entity_type)
            return resolution_record(
                {
                    "mention": mention,
                    "candidates": [
                        RosterCandidate(
                            ref=ref, name=index.name_of(ref), basis="name"
                        ).to_dict()
                        for ref in shared
                    ],
                    "resolution": "uncertain",
                    "reason": SHARED_NAME_TOKEN_REASON,
                    "evidence_ref": evidence_ref,
                },
                now=now,
            )

    return resolution_record(
        {
            "mention": mention,
            "candidates": matches,
            "resolution": "uncertain",
            "reason": "ambiguous_candidates" if matches else "no_candidate",
            "evidence_ref": evidence_ref,
        },
        now=now,
    )


def is_owner_birth_domain_word(mention: object, event_kind: object) -> bool:
    """Is this claim a legacy birth landmark naming the domain instead of the person?

    BOTH halves are required, on purpose. The word alone proves nothing — a
    person may be mentioned by any word — so the rule fires only where the
    claim is also *about a birth*, which is the one place
    ``entry_subject_mention``'s domain fallback ever meant "the person whose
    vault this is". A ``birth``-worded mention on any other event kind is left
    exactly where it is, unresolved, for the ordinary resolver to answer.
    """
    return (
        normalized_mention_key(mention) == normalized_mention_key(LEGACY_OWNER_BIRTH_MENTION)
        and collapsed_text(event_kind) == "birth"
    )


def owner_birth_domain_resolution(
    mention: object,
    *,
    owner_ref: object,
    evidence_ref: object,
    now: object = None,
) -> ResolutionRecord:
    """The :data:`OWNER_BIRTH_DOMAIN_REASON` rule, as a record.

    It resolves ``same`` to the owner's own handle and carries that handle as
    its single candidate, so the decision reads back through exactly the same
    door — and the same ``unresolve`` — as a roster match or an owner verdict.
    """
    ref = collapsed_text(owner_ref)
    if not ref:
        raise IdentityResolutionError(
            "owner_ref_required", "the owner-birth rule resolves to the owner's own handle"
        )
    return resolution_record(
        {
            "mention": mention,
            "candidates": [{"ref": ref, "name": ref, "basis": "exact_ref"}],
            "resolution": "same",
            "resolved_ref": ref,
            "reason": OWNER_BIRTH_DOMAIN_REASON,
            "evidence_ref": evidence_ref,
        },
        now=now,
    )


def owner_name_refs(roster: object, owner_names: object) -> frozenset[str]:
    """The roster refs that answer to one of the owner's own names."""
    refs: set[str] = set()
    for name in owner_names or ():
        text = collapsed_text(name)
        if not text:
            continue
        for match in candidates_for(text, roster):
            ref = collapsed_text(match.get("ref"))
            if ref:
                refs.add(ref)
    return frozenset(refs)


def owner_name_resolution(
    mention: object,
    *,
    owner_ref: object,
    evidence_ref: object,
    now: object = None,
) -> ResolutionRecord:
    """The :data:`OWNER_NAME_REASON` rule, as a record: same shape and same
    reversal path as the owner-birth rule and a roster match."""
    ref = collapsed_text(owner_ref)
    if not ref:
        raise IdentityResolutionError(
            "owner_ref_required", "the owner-name rule resolves to the owner's own handle"
        )
    return resolution_record(
        {
            "mention": mention,
            "candidates": [{"ref": ref, "name": ref, "basis": "exact_ref"}],
            "resolution": "same",
            "resolved_ref": ref,
            "reason": OWNER_NAME_REASON,
            "evidence_ref": evidence_ref,
        },
        now=now,
    )


def unresolve(record: object, *, now: object = None) -> ResolutionRecord:
    """Reverse a resolution without destroying it (§6.3's "reversible").

    The returned record is ``uncertain`` with reason ``unresolved``. Nothing is
    thrown away: the candidate set survives intact — including the ref that had
    won, so the reversal can itself be reversed — and the undone decision is
    recorded in ``reverses``. This is the only supported way to undo a link,
    and it produces *new* data rather than editing old data, which is the same
    rule the claim substrate applies to supersession.

    Unresolving an already-uncertain record is a no-op that still returns a
    valid record, so a caller need not check first.
    """
    current = record if isinstance(record, ResolutionRecord) else record_from_dict(record)
    if current is None:
        raise IdentityResolutionError(
            "resolution_not_a_mapping", "unresolve needs a valid resolution record"
        )
    if current.resolution == "uncertain":
        return current

    payload: dict = {
        "mention": current.mention,
        "candidates": [dict(c) for c in current.candidates],
        "resolution": "uncertain",
        "reason": UNRESOLVED_REASON,
        "evidence_ref": current.evidence_ref,
        "reverses": {
            "resolution": current.resolution,
            "resolved_ref": current.resolved_ref,
            "reason": current.reason,
            "created_at": current.created_at,
        },
    }
    return resolution_record(payload, now=now)


# --------------------------------------------------------------------------
# Attaching a resolution to a claim — annotation, never mutation
# --------------------------------------------------------------------------


def resolution_annotation(record: object) -> dict:
    """Project a record into ``TemporalClaim.subject_resolution``'s shape.

    ``temporal_claims`` already reserves a slot for §6.3's reversibility record
    and normalizes it to ``{candidates: [ref, ...], reason, confidence}``. This
    is the one projection into it, so the richer record here and the claim's
    stored annotation cannot drift. The full record — per-candidate names and
    bases, the ``reverses`` trail — belongs to the resolution ledger Wave B/D
    stores beside the receipts; the claim carries the summary.
    """
    current = record if isinstance(record, ResolutionRecord) else record_from_dict(record)
    if current is None:
        return {}
    annotation: dict = {
        "candidates": [c["ref"] for c in current.candidates],
        "reason": current.reason,
    }
    if current.confidence is not None:
        annotation["confidence"] = current.confidence
    return annotation


def apply_resolution(claim: object, record: object, *, now: object = None) -> dict:
    """Return a NEW claim dict carrying the resolution. The claim id must not move.

    §6.3 and §5.1: the raw mention is what identity derives from, so resolving
    an alias later never re-mints the claim. That is a property of
    ``temporal_claims.CLAIM_IDENTITY_KEYS`` — but a property nothing checks is a
    property waiting to break at the next pin bump, so this function asserts it
    and raises ``resolution_would_remint`` rather than filing a duplicate.

    The input claim is not mutated. ``subject_mention`` is untouched; only
    ``subject_ref`` (when the record resolved) and ``subject_resolution`` (in
    every case, including uncertain — the fact that we looked is worth keeping)
    are added.
    """
    if not isinstance(claim, dict):
        claim = validate_temporal_claim(claim, now=now)
    before = validate_temporal_claim(claim, now=now)

    current = record if isinstance(record, ResolutionRecord) else record_from_dict(record)
    if current is None:
        raise IdentityResolutionError(
            "resolution_not_a_mapping", "apply_resolution needs a valid resolution record"
        )

    after_input = dict(before)
    after_input["subject_resolution"] = resolution_annotation(current)
    if current.is_resolved():
        after_input["subject_ref"] = current.resolved_ref
    else:
        after_input.pop("subject_ref", None)

    after = validate_temporal_claim(after_input, now=now)
    if after["claim_id"] != before["claim_id"]:
        raise IdentityResolutionError(
            "resolution_would_remint",
            f"resolving {current.mention!r} moved the claim id "
            f"{before['claim_id']} -> {after['claim_id']}",
        )
    return after


# --------------------------------------------------------------------------
# The Mirror hand-off
# --------------------------------------------------------------------------


def identity_work_item(
    record: object,
    *,
    claim_refs: object = (),
    now: object = None,
    owner_refs: object = (),
) -> dict | None:
    """Mint the ``identity_uncertain`` work item an ambiguous mention deserves.

    §6.3: "Ambiguous identity becomes a Mirror item; it does not justify
    dropping the claim." The item's identity is derived from the *mention*
    handle, so every claim that ever said "AJ" ambiguously points at one row
    — answer once, update everywhere (§5.4).

    Returns ``None`` for anything that is not genuine ambiguity, and the
    exclusions are deliberate rather than incidental:

    * A **resolved** record has nothing to ask.
    * A record with **no candidates** is a name nobody in the roster resembles
      — which is a person we have not met yet, not a disagreement. Minting a
      Mirror row for every first mention of a new name would fill Mirror with
      noise and bury the real contradictions §2.5 exists to surface. Nothing is
      lost by the omission: the claim is retained with its ``uncertain``
      record, and the mention resolves the moment the roster learns the name.
    * v343 (`timeline-rules:13`). ``owner_refs`` — the roster refs that answer
      to the OWNER's own name (`identity_resolution.owner_name_refs`,
      `temporal_publication.owner_identity_inputs`) — are never offered as a
      candidate here: the owner does not need to be told which "Dave" he is.
      This is deliberately NOT `timeline-rules:9` ("an unknown name is not
      the owner"): that rule is about a mention nobody in the roster
      resembles defaulting to the owner; this is the opposite direction — a
      mention that DOES resolve to the owner's own roster row, among others,
      dropping that one true candidate from the running. Fewer than two
      candidates left after the drop is not ambiguity either, so it mints
      nothing (§6.3's "did not justify dropping the claim" still holds — the
      claim keeps its ``uncertain`` record; only the CARD is withheld).
    """
    current = record if isinstance(record, ResolutionRecord) else record_from_dict(record)
    if current is None or current.resolution != "uncertain" or not current.candidates:
        return None

    owners = {collapsed_text(ref) for ref in (owner_refs or ()) if collapsed_text(ref)}
    candidates = tuple(
        c for c in current.candidates if collapsed_text(c.get("ref")) not in owners
    ) if owners else current.candidates
    if len(candidates) < 2:
        return None

    refs = claim_refs
    if isinstance(refs, (str, bytes)):
        refs = [refs]
    names = [c["name"] or c["ref"] for c in candidates]

    return validate_temporal_work_item(
        {
            "kind": "identity_uncertain",
            "state": "open",
            "subject_ref": unresolved_subject_ref(current.mention),
            "requested_field": IDENTITY_REQUESTED_FIELD,
            "prompt_intent": (
                f"Which {' or '.join(names)} is {current.mention!r} here?"
                if names
                else f"Who is {current.mention!r}?"
            ),
            "claim_refs": list(refs or ()),
            "evidence_refs": [current.evidence_ref],
            "allowed_surfaces": list(IDENTITY_WORK_SURFACES),
        },
        now=now,
    )


# --------------------------------------------------------------------------
# Episode identity — which event is which
# --------------------------------------------------------------------------


def is_relationship_event(event_kind: object) -> bool:
    """Does this event kind describe a transition between two people?"""
    return collapsed_text(event_kind) in RELATIONSHIP_EVENT_KINDS


def is_repeatable_event(event_kind: object) -> bool:
    """Can a life hold more than one of these, needing a discriminator?"""
    return collapsed_text(event_kind) in REPEATABLE_EVENT_KINDS


def relationship_edge_ref(subject: object, counterpart: object) -> str:
    """``edge:<24 hex>`` — the order-normalized pair, free of any event kind.

    This is the grouping key that makes "dating started in 2005" and "married
    in 2007" two facts about ONE relationship rather than two unrelated events
    or one collapsed blob (§6.3, §10). It deliberately excludes the event kind,
    the dates and the direction: ``edge(a, b) == edge(b, a)``, forever.
    """
    keys = sorted({normalized_mention_key(v) for v in (subject, counterpart) if collapsed_text(v)})
    if len(keys) != 2:
        raise IdentityResolutionError(
            "edge_needs_two_subjects",
            "a relationship edge joins two distinct subjects",
        )
    return digest_id(EDGE_ID_PREFIX, {"subject_keys": keys})


def episode_discriminator(start_value: object) -> str | None:
    """The episode's OWN start, as the thing that separates it from its repeats.

    §6.3 and §10: a second stint at the same employer is a second episode. What
    makes it a second one is its own start claim, so the discriminator is drawn
    from that rather than from an arrival order the fold cannot reproduce.

    Accepts an EDTF string, a ``chronology.DateRecord``-shaped mapping (any of
    ``best``/``start``/``edtf``/``value``), or ``None``. Returns ``None`` when
    there is nothing to discriminate on — the caller then supplies an explicit
    ordinal, or :func:`derive_episode_ref` refuses.

    Note this is not the "never a timestamp" ``derive_node_id`` warns about: a
    wall clock records when the fold ran and moves on every rebuild, while an
    asserted start date is part of what the episode *is* and is stable across
    every rebuild from the same claims.
    """
    if isinstance(start_value, dict):
        for key in ("best", "start", "edtf", "value"):
            text = collapsed_text(start_value.get(key))
            if text:
                return text
        return None
    text = collapsed_text(start_value)
    return text or None


def derive_episode_ref(
    *,
    event_kind: object,
    subject_ref: object = None,
    subject_mention: object = None,
    counterpart_ref: object = None,
    discriminator: object = None,
) -> str:
    """``node:<24 hex>`` — the stable identity of one event or episode.

    Built through :func:`temporal_projection.derive_node_id`, the substrate's
    one identity function, so an episode ref *is* the node id Wave D's
    projection publishes and a claim's ``event_ref`` points at the same thing a
    Mirror row and a work item do.

    The subject may be a resolved ref or, when identity has not resolved, the
    raw mention — an unresolved subject must still be able to hold an event, or
    §2.5's "never dropped" would fail exactly where identity is hardest. Both
    normalize through ``normalized_mention_key``, so an episode minted against
    ``"Katie"`` before resolution and against ``person/katie`` after it are
    *different* refs; the fold re-derives event refs from resolved subjects, and
    that re-derivation is a projection rebuild, never a claim edit.

    Two refusals, each preventing a silent merge:

    * ``episode_needs_counterpart`` — a relationship transition without the
      other person would attach to one half of an edge and collide with every
      other relationship that person ever had.
    * ``episode_needs_discriminator`` — a repeatable kind (job, school, move,
      residence, military) without one collapses a second stint into the first.
      Pass ``episode_discriminator(start)`` or an explicit ordinal.
    """
    kind = collapsed_text(event_kind)
    if not kind:
        raise IdentityResolutionError(
            "episode_needs_event_kind",
            "a date is the date OF AN EVENT; an episode ref needs its kind",
        )

    subject = collapsed_text(subject_ref) or collapsed_text(subject_mention)
    if not subject:
        raise IdentityResolutionError(
            "episode_needs_subject", "an episode is about somebody or something"
        )

    counterpart = collapsed_text(counterpart_ref)
    relationship = is_relationship_event(kind)
    if relationship and not counterpart:
        raise IdentityResolutionError(
            "episode_needs_counterpart",
            f"{kind!r} is a transition between two people; name the counterpart",
        )

    disc = collapsed_text(discriminator) or None
    if is_repeatable_event(kind) and not disc:
        raise IdentityResolutionError(
            "episode_needs_discriminator",
            f"{kind!r} can happen more than once; a second one without a "
            "discriminator would silently merge into the first",
        )

    subjects = [subject, counterpart] if counterpart else [subject]
    return derive_node_id(
        node_kind="episode" if (relationship or is_repeatable_event(kind)) else "event",
        event_kind=kind,
        subject_refs=subjects,
        discriminator=disc,
    )


__all__ = [
    "CANDIDATE_BASES",
    "DETERMINISTIC_REASONS",
    "EDGE_ID_PREFIX",
    "ERROR_CODES",
    "IDENTITY_REQUESTED_FIELD",
    "IDENTITY_WORK_SURFACES",
    "MENTION_QUALIFIER_WORDS",
    "MODEL_REASON",
    "OWNER_REASON",
    "RELATIONSHIP_MENTION_WORDS",
    "RELATIONSHIP_QUALIFIED_REASON",
    "ROSTER_RELATIONSHIP_KEY",
    "SHARED_NAME_TOKEN_REASON",
    "mention_tokens",
    "relationship_qualified_candidates",
    "shared_name_token_refs",
    "RELATIONSHIP_EVENT_KINDS",
    "ONCE_PER_COUPLE_EVENT_KINDS",
    "ONCE_PER_SUBJECT_EVENT_KINDS",
    "COUPLE_OF_RELATION_WORD",
    "COUPLE_KEY_PREFIX",
    "OWNER_COUPLE",
    "OWNER_COUPLE_SUBJECT_WORDS",
    "couple_key",
    "couple_relation_word",
    "A_COUPLE_IS_READ_FROM_THE_TELLINGS_OWN_SUBJECTS",
    "A_COMPOUND_RELATION_IS_NEVER_THE_WORD_INSIDE_IT",
    "COMPOUND_RELATION_PREFIXES",
    "IN_LAW_RE",
    "depluralized",
    "relation_word_stem",
    "OWNER_SUBJECT_MENTIONS",
    "REPEATABLE_EVENT_KINDS",
    "RESOLUTIONS",
    "RESOLUTION_REASONS",
    "OWNER_BIRTH_DOMAIN_REASON",
    "OWNER_NAME_REASON",
    "owner_name_refs",
    "owner_name_resolution",
    "LEGACY_OWNER_BIRTH_MENTION",
    "is_owner_birth_domain_word",
    "owner_birth_domain_resolution",
    "UNCERTAIN_REASONS",
    "UNRESOLVED_REASON",
    "UNRESOLVED_REF_PREFIX",
    "IdentityResolutionError",
    "ResolutionRecord",
    "RosterCandidate",
    "RosterIndex",
    "apply_resolution",
    "candidates_for",
    "derive_episode_ref",
    "entity_ref",
    "episode_discriminator",
    "identity_work_item",
    "is_relationship_event",
    "is_repeatable_event",
    "is_unresolved_ref",
    "record_from_dict",
    "relationship_edge_ref",
    "resolution_annotation",
    "resolution_record",
    "resolve_mention",
    "roster_index",
    "unresolve",
    "unresolved_subject_ref",
]
