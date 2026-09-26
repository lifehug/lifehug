#!/usr/bin/env python3
"""v358 — a gendered word when it is known, the neutral word when it is not.

THE OWNER'S RULING (2026-09-25), in his words:

    "we can use both child and son, I in life have four children all who are
    my child or children and I have 2 sons and 2 daughters so both"

    "son is more detailed than child and gives more information, so if you
    have to pick one i'd pick the gendered one daughter and son"

and the scope correction the same day: *"each person isn't my child, so is
this really for everyone?"* — it is, for every relation whose word HAS a
gendered form, and for no other.

WHAT WAS MISSING. The roster stores a relationship from a closed vocabulary
(`focus_candidate.FOCUS_RELATIONSHIPS` — parent, child, sibling, spouse,
grandparent, …) and held nothing that says which FORM of that word the owner
uses for a person. "Son" was not suppressed; it was unavailable.

THE MODEL — one field, set once per person. A roster person row may carry
:data:`RELATION_GENDER_FIELD` (``relation_gender``), one of
:data:`RELATION_GENDERS`: ``male``, ``female`` or ``neutral``. It is the
grammatical gender of the relationship word the owner uses for that person,
not a record of anybody's sex, and ``neutral`` is a real answer — "keep
'child'" — so the question is never asked twice. Every word is DERIVED from
the pair (relationship, relation_gender) through :func:`relation_word`: Son /
Daughter, Father / Mother, Brother / Sister, Husband / Wife, Grandfather /
Grandmother. Why a gender and not a stored word: a stored "son" duplicates
``relationship`` and can disagree with it (a row corrected from ``sibling`` to
``child`` would keep saying "brother"), and it would need a second answer for
the same person after every such correction. One orthogonal fact derives every
word, stays true when the relationship is corrected, and is asked once.

WHERE THE FIELD COMES FROM — ONLY the owner's own words
(:data:`THE_FIELD_IS_SET_ONLY_BY_THE_OWNERS_OWN_WORDS`):

1. his ANSWER to the one card this module mints (``relation_gender_basis:
   "answer"``, written by :func:`record_relation_gender`), which always wins;
2. otherwise, read fresh on every publish and never written: a gendered
   relationship word he used ABOUT that person — a roster spelling that is
   itself the word ("dad", "my mother", "A.J. (brother)"), a `family` landmark
   record whose ``relation`` is the word, or an introduction in his own
   tellings read by `roster_relations.relationship_phrase_match`, the v346/v347
   reading, so a possessor ("my dad's dad") and a compound ("mother-in-law")
   are refused exactly as they are there. Never a first name.

The vocabulary is `identity_resolution.RELATIONSHIP_MENTION_WORDS` and nothing
else: the gendered pair of a relationship is DERIVED from it
(:func:`gendered_pair`), and the only thing this module declares is which of
the two canonical words is the masculine one (:data:`WORD_GENDER`).

RENDERING (:data:`A_GENDERED_WORD_WHEN_IT_IS_KNOWN`). The gendered word when
the field is known, the neutral word when it is not — and a plural, collective
context keeps the neutral plural ("children"): the owner said all four are his
children AND he has two sons and two daughters. The words are PUBLISHED on the
calculated projection (``relation_words``), so a host reads the word rather
than mapping one onto another.

ASKING (:data:`A_CARD_ONLY_WHERE_THE_WORD_HAS_A_GENDERED_PAIR`). At most ONE
card per person, kind :data:`RELATION_WORD_KIND`, on the Timeline's queue and
never on a person page (the standing ruling: person pages do not ask). Only
for a real named person whose relationship has a gendered pair — never a
friend, a colleague, a bishop, a neighbour; never an alias row
(``maps_to_focus``), a collective or role row ("Kids", "Son"), or the owner.
Ranked below every dating card. Answering files through the ordinary card
answer path (`answer_placement.place_answers`, `landmark_recorder.file_claims`)
into :func:`file_relation_answer`, and a card whose person has the field is
never minted again.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

SYSTEM_DIR = Path(__file__).resolve().parent
if str(SYSTEM_DIR) not in sys.path:
    sys.path.insert(0, str(SYSTEM_DIR))

import identity_resolution as ir  # noqa: E402
import roster_relations as rr  # noqa: E402

# --------------------------------------------------------------------------
# The rules, one sentence each
# --------------------------------------------------------------------------

A_GENDERED_WORD_WHEN_IT_IS_KNOWN = (
    "a person's relationship is rendered with the gendered word when the owner "
    "has said which one it is — son, daughter, father, mother — and with the "
    "neutral word when he has not; a plural or collective context keeps the "
    "neutral plural, because all of his children are his children"
)

A_CARD_ONLY_WHERE_THE_WORD_HAS_A_GENDERED_PAIR = (
    "the relation-word card is minted only for a real named person on the "
    "roster whose relationship HAS a gendered pair and whose word is not yet "
    "known — once per person, on the Timeline, never on a person page, never "
    "for an alias row, a collective or role row, the owner, or a relation such "
    "as friend or colleague that has no gendered form"
)

THE_FIELD_IS_SET_ONLY_BY_THE_OWNERS_OWN_WORDS = (
    "relation_gender comes only from the owner's answer to the card or from a "
    "gendered relationship word he himself used about that person — a roster "
    "spelling, a family landmark record, or an introduction in his own "
    "tellings — and never from a first name"
)

#: The rule version of everything this module publishes. It is part of
#: `temporal_publication._rule_identity`, so a framework that changes what a
#: projection says about relation words re-derives rather than reusing a
#: standing generation that says less.
#: relation-words:2 (v360 follow-up, owner 2026-09-25): his own tellings are read
#: word for word and by the given name he uses
#: (:data:`HIS_OWN_TELLINGS_ARE_READ_BY_A_NAME_HE_USES`), and the
#: grandparent-side card rides the same seam.
RELATION_WORD_RULE_VERSION = "relation-words:2"

# --------------------------------------------------------------------------
# The field
# --------------------------------------------------------------------------

#: The roster field, and the field a card requests
#: (`temporal_work_items.REQUESTED_FIELD_RELATION_GENDER`, held equal by test).
RELATION_GENDER_FIELD = "relation_gender"
#: What decided it. ``answer`` is the card; ``stated`` is his own words.
RELATION_GENDER_BASIS_FIELD = "relation_gender_basis"
BASIS_ANSWER = "answer"
BASIS_STATED = "stated"
RELATION_GENDER_BASES = (BASIS_ANSWER, BASIS_STATED)

MALE = "male"
FEMALE = "female"
NEUTRAL = "neutral"
#: The closed vocabulary. ``neutral`` is the owner choosing the neutral word —
#: an answer, which is why a card never re-mints after it.
RELATION_GENDERS = (MALE, FEMALE, NEUTRAL)

#: The ONE declaration this module adds to the vocabulary: which canonical word
#: is which form. Everything else — which relationship a word belongs to, which
#: spoken words ("dad", "mom", "grandpa") mean which canonical word — is read
#: from `identity_resolution.RELATIONSHIP_MENTION_WORDS`.
WORD_GENDER = {
    "father": MALE, "mother": FEMALE,
    "son": MALE, "daughter": FEMALE,
    "brother": MALE, "sister": FEMALE,
    "husband": MALE, "wife": FEMALE,
    "grandfather": MALE, "grandmother": FEMALE,
}

#: The neutral plural where English does not add an ``s``.
IRREGULAR_PLURALS = {"child": "children"}

#: A colloquial word for a child, gendered only for a ``child`` row — never a
#: roster relationship (`identity_resolution.RELATIONSHIP_MENTION_WORDS` does
#: not know either word), never a card, never an answer. It only ever feeds
#: the "stated" basis (:func:`told_word_gender`), and only there: "my boy"
#: never makes a spouse a husband, whatever row it is read against.
INFORMAL_CHILD_WORDS = {"boy": MALE, "girl": FEMALE}

#: A classification summary, or the owner's own telling written in the third
#: person, names the owner "the author" rather than "my"/"our" — the one
#: possessive `roster_relations.relationship_phrase_match` cannot read,
#: because it is never one of the owner's own name spellings.
AUTHOR_POSSESSIVE = "the author"

# --------------------------------------------------------------------------
# The card
# --------------------------------------------------------------------------

#: The work-item kind, registered in `temporal_projection.WORK_ITEM_KINDS`.
RELATION_WORD_KIND = "relation_word"

#: The candidate ref an answer of "keep the neutral word" carries.
NEUTRAL_CHOICE = NEUTRAL

#: Named refusals for an answer that could not be filed.
REFUSED_NOT_A_RELATION_CARD = "not_a_relation_word_card"
REFUSED_PERSON_NOT_ON_ROSTER = "relation_card_person_not_on_roster"
REFUSED_ALREADY_KNOWN = "relation_word_already_known"
REFUSED_ANSWER_UNREADABLE = "relation_answer_unreadable"
RELATION_ANSWER_REFUSALS = (
    REFUSED_NOT_A_RELATION_CARD,
    REFUSED_PERSON_NOT_ON_ROSTER,
    REFUSED_ALREADY_KNOWN,
    REFUSED_ANSWER_UNREADABLE,
)


# --------------------------------------------------------------------------
# The vocabulary, derived
# --------------------------------------------------------------------------


def _focus_relationships() -> tuple[str, ...]:
    from focus_candidate import FOCUS_RELATIONSHIPS  # noqa: PLC0415

    return tuple(FOCUS_RELATIONSHIPS)


def canonical_gendered_word(word: object) -> str:
    """``"dad"`` -> ``"father"``; ``"wife"`` -> ``"wife"``; ``"child"`` -> ``""``.

    The canonical form a spoken relationship word names, read off
    `identity_resolution.RELATIONSHIP_MENTION_WORDS`: the members of its set
    that are not roster relationships. A word with exactly one such member that
    :data:`WORD_GENDER` knows is gendered; ``child`` (whose set holds both
    ``son`` and ``daughter``) and ``uncle`` (no roster seat) are not.
    """
    key = ir.relation_word_stem(word)
    values = ir.RELATIONSHIP_MENTION_WORDS.get(key)
    if not values:
        return ""
    forms = sorted(set(values) - set(_focus_relationships()))
    if len(forms) == 1 and forms[0] in WORD_GENDER:
        return forms[0]
    return ""


def word_gender(word: object) -> str:
    """``male`` / ``female`` for a gendered relationship word, else ``""``."""
    return WORD_GENDER.get(canonical_gendered_word(word), "")


def gendered_pair(relationship: object) -> tuple[str, str] | None:
    """``("son", "daughter")`` for ``child``; ``None`` for ``friend``.

    Derived: the neutral word's own set in
    `identity_resolution.RELATIONSHIP_MENTION_WORDS` minus the roster
    vocabulary is exactly the two gendered forms — ``child`` ->
    ``{son, daughter}``, ``spouse`` -> ``{wife, husband}`` (``partner`` is a
    roster relationship of its own). A relationship with no neutral entry, or
    whose forms are not exactly one masculine and one feminine word, has no
    pair — which is what keeps ``partner``, ``friend``, ``colleague``,
    ``mentor`` and ``other`` off the card.
    """
    key = rr.collapsed_text_of(relationship).casefold()
    if key not in _focus_relationships():
        return None
    values = ir.RELATIONSHIP_MENTION_WORDS.get(key)
    if not values:
        return None
    forms = set(values) - set(_focus_relationships())
    male = sorted(word for word in forms if WORD_GENDER.get(word) == MALE)
    female = sorted(word for word in forms if WORD_GENDER.get(word) == FEMALE)
    if len(male) != 1 or len(female) != 1 or len(forms) != 2:
        return None
    return male[0], female[0]


def gendered_relationships() -> tuple[str, ...]:
    """Every roster relationship that has a gendered pair, in vocabulary order."""
    return tuple(value for value in _focus_relationships() if gendered_pair(value))


def neutral_plural(relationship: object) -> str:
    word = rr.collapsed_text_of(relationship).casefold()
    if not word:
        return ""
    return IRREGULAR_PLURALS.get(word, f"{word}s")


def relation_word(relationship: object, gender: object = None, *,
                  plural: bool = False) -> str:
    """The word for one person, or for a group (:data:`A_GENDERED_WORD_WHEN_IT_IS_KNOWN`).

    ``relation_word("child", "male")`` is ``"son"``; with no gender, or
    ``neutral``, it is ``"child"``; ``plural=True`` is ALWAYS the neutral
    plural, ``"children"``, whatever the gender — a group of his children is
    his children. A relationship with no pair keeps its own word.
    """
    neutral = rr.collapsed_text_of(relationship).casefold()
    if not neutral:
        return ""
    if plural:
        return neutral_plural(neutral)
    pair = gendered_pair(neutral)
    if pair is not None and gender == MALE:
        return pair[0]
    if pair is not None and gender == FEMALE:
        return pair[1]
    return neutral


def relation_label(relationship: object, gender: object = None, *,
                   plural: bool = False) -> str:
    """:func:`relation_word`, as a label reads — ``"Son"``, ``"Children"``."""
    word = relation_word(relationship, gender, plural=plural)
    return word[:1].upper() + word[1:]


# --------------------------------------------------------------------------
# Who a row is
# --------------------------------------------------------------------------


def _role_words() -> frozenset[str]:
    import entity_roster  # noqa: PLC0415

    return frozenset(entity_roster.ROLE_WORDS)


#: v357's one reading of a `maps_to_focus` pointer row
#: (`identity_resolution.AN_ALIAS_ROW_IS_NEVER_A_CANDIDATE`), used as is.
is_alias_row = ir.is_alias_row


def is_collective_row(entity: object) -> bool:
    """A row whose NAME is a plural relationship word or a collective role word.

    "Kids", "Parents", "Siblings", "Children", "Family" — the group, never one
    person, so it is spoken of in the neutral plural and never asked about.
    """
    if not isinstance(entity, dict):
        return False
    key = ir.normalized_mention_key(entity.get("name"))
    if not key:
        return False
    if key in {"kids", "children", "family", "parents", "siblings", "grandparents"}:
        return True
    stem = ir.relation_word_stem(key)
    return bool(stem) and stem != key


def is_role_row(entity: object) -> bool:
    """A row whose NAME is a bare role word — "Son", "Daughter", "Friend".

    A placeholder, not a named person (v343's card-shape law: a card names a
    real person), so it may carry a label and never a card.
    """
    if not isinstance(entity, dict):
        return False
    key = ir.normalized_mention_key(entity.get("name"))
    if not key:
        return True
    names, _relations = ir.mention_tokens(key)
    return key in _role_words() or bool(ir.relation_word_stem(key)) or not names


def is_owner_row(entity: object, owner_names: object = ()) -> bool:
    if not isinstance(entity, dict):
        return False
    owner = {ir.normalized_mention_key(name) for name in owner_names or ()}
    owner.discard("")
    if not owner:
        return False
    spellings = {ir.normalized_mention_key(entity.get("name")),
                 *(ir.normalized_mention_key(a) for a in entity.get("aliases") or ())}
    return bool(owner & spellings)


def person_ref(entity: object) -> str:
    return rr.entity_ref("person", entity) if isinstance(entity, dict) else ""


def _spellings(entity: dict) -> list[str]:
    out: list[str] = []
    for spelling in (entity.get("name"), *(entity.get("aliases") or ())):
        body = rr.collapsed_text_of(spelling)
        if body and body not in out:
            out.append(body)
    return out


# --------------------------------------------------------------------------
# The owner's own words
# --------------------------------------------------------------------------


def bare_relation_word(spelling: object) -> str:
    """The relationship word a spelling IS, or ``""`` — ``"my mom"`` -> ``mom``.

    Whole spelling only, with its determiners dropped
    (`identity_resolution.mention_tokens`): a spelling that also carries a
    name token is a name, and a compound ("mother-in-law", "step-mother")
    leaves ``in``/``law``/``step`` behind as name tokens, so it is never the
    simple word inside it.
    """
    names, relations = ir.mention_tokens(spelling)
    if names or len(relations) != 1:
        return ""
    return relations[0]


def told_word_gender(word: object, relationship: object) -> str:
    """:func:`word_gender`, extended with :data:`INFORMAL_CHILD_WORDS`.

    "Boy"/"girl" have no roster relationship seat, so they are never checked
    against ``roster_relationship_for`` the way a vocabulary word is — they
    decide the "stated" basis only when the row's own relationship IS
    ``child``, exactly the same "belongs to this row's own relationship" guard
    :func:`stated_words` already applies to every other word.
    """
    word = rr.collapsed_text_of(word).casefold()
    gender = word_gender(word)
    if gender:
        return gender if rr.roster_relationship_for(word) == \
            rr.collapsed_text_of(relationship).casefold() else ""
    if rr.collapsed_text_of(relationship).casefold() == "child":
        return INFORMAL_CHILD_WORDS.get(word, "")
    return ""


#: The vocabulary of :func:`told_phrase_match`'s POSSESSIVE-WORD-NAME and
#: NAME-, POSSESSIVE-WORD patterns: every spoken word
#: `roster_relations.relationship_phrase_match` already reads, plus the two
#: informal child words it does not.
_TOLD_WORDS = rr._relation_word_alternation() + "|boy|girl"  # noqa: SLF001

#: The vocabulary of :func:`told_phrase_match`'s bare, third-person pattern —
#: "Son Harvey born …" — restricted to the formal, capitalised words a
#: classification summary actually writes; never the colloquial "Dad"/"Mom"/
#: "Grandpa", and never "Boy"/"Girl", which no telling opens a clause with.
_TOLD_BARE_WORDS = "|".join(
    re.escape(word.capitalize()) for word in sorted(WORD_GENDER, key=len, reverse=True))


#: v360 follow-up (owner, 2026-09-25) (item 9): *"I have my beautiful daughter
#: Charlee"* (answers/E27) puts one or two plain words between the possessive
#: and the relation word. At most two, each a plain lowercase-able word that is
#: NOT itself a relation word and carries no possessive — so "my dad's friend's
#: daughter" and "my uncle Bob's daughter" still never read as his daughter.
_TOLD_ADJECTIVES = (r"(?:(?!(?:" + _TOLD_WORDS + r")\b)[a-z]+\s+){0,2}")


def _told_possessives(owner_names: object) -> str:
    """``"(?:my|our|the author's|<owner spelling>'s) "`` — the possessives a
    telling or a classification summary uses for the owner himself."""
    possessives = [re.escape(word) for word in rr.INTRODUCTION_POSSESSIVES]
    possessives.append(re.escape(AUTHOR_POSSESSIVE) + r"['’]s")
    for spelling in owner_names or ():
        body = rr.collapsed_text_of(spelling)
        if body:
            possessives.append(re.escape(body) + r"['’]s")
    return "(?:" + "|".join(possessives) + r")\s+"


def _told_relationship_for(word: str) -> str:
    """Like `roster_relations.roster_relationship_for`, but "boy"/"girl" name
    ``child`` — the one relationship they are ever gendered for."""
    if word in INFORMAL_CHILD_WORDS:
        return "child"
    return rr.roster_relationship_for(word)


def told_phrase_match(name: object, texts: object, *, owner_names: object = (),
                      given_only: bool = False) -> dict | None:
    """``{"word", "clause"}`` for a gendered word the owner (or a
    classification summary, of him in the third person) applied to ``name`` —
    the shapes `roster_relations.relationship_phrase_match` cannot read:

    * an informal ``"my boy Harvey"`` / ``"my girl <Name>"`` — colloquial, and
      only ever :data:`INFORMAL_CHILD_WORDS`, on top of every spoken word that
      module already reads ("dad", "mom", "son", …);
    * the third person a classification summary writes the owner in —
      ``"the author's son <Name>"``, the same shape as ``"my son <Name>"`` with
      one more possessive;
    * a bare, clause-opening ``"Son <Name> born …"`` — no possessive at all,
      because a summary states it as a fact rather than the owner's speech,
      read only at the clause's own start so it can never reach into the
      middle of an unrelated sentence ("the reception was at my mother-in-law
      Ruth's house" opens with "the reception", not a relation word).

    Same clause discipline as v347/v350: read one :func:`introduction_clauses`
    clause at a time, and a word possessing the next noun
    (`roster_relations._NOT_A_POSSESSOR`) is never the name's own relation —
    *"my dad's dad"* gives the clause no word for the dad in front of it. The
    in-law suffix is the caller's own check, exactly as it already is for
    `roster_relations.relationship_phrase_match`.
    """
    anchor_name = rr.collapsed_text_of(name)
    if not anchor_name:
        return None
    anchor = re.escape(anchor_name)
    if given_only:
        # A GIVEN name alone (:func:`given_name_anchors`) is that person only
        # when no further name follows it: "my beautiful daughter Charlee, and"
        # is Charlee, while "married my dad Desiree Ann Taylor" (a lost comma)
        # names somebody whose full name is longer than the word read.
        anchor = anchor + r"(?!\w)(?-i:(?!\s+[A-Z][a-z]))"
    possessive = _told_possessives(owner_names)
    predicate = re.compile(
        rf"(?<!\w){possessive}{_TOLD_ADJECTIVES}(?P<word>{_TOLD_WORDS}){rr._NOT_A_POSSESSOR}"  # noqa: SLF001
        rf"\s+{anchor}(?!\w)", re.IGNORECASE)
    apposition = re.compile(
        rf"(?<!\w){anchor}\s*,\s*{possessive}(?P<word>{_TOLD_WORDS})"
        rf"{rr._NOT_A_POSSESSOR}(?!\w)", re.IGNORECASE)  # noqa: SLF001
    bare = re.compile(
        rf"^(?P<word>{_TOLD_BARE_WORDS}){rr._NOT_A_POSSESSOR}\s+(?i:{anchor})(?!\w)")  # noqa: SLF001
    for text in texts or ():
        for clause in rr.introduction_clauses(text):
            found: list[str] = []
            for pattern in (predicate, apposition):
                for match in pattern.finditer(clause):
                    word = match.group("word").casefold()
                    if word not in found:
                        found.append(word)
            bare_match = bare.match(clause)
            if bare_match:
                word = bare_match.group("word").casefold()
                if word not in found:
                    found.append(word)
            if not found:
                continue
            if len({_told_relationship_for(word) for word in found}) > 1:
                continue
            return {"word": found[0], "clause": clause}
    return None


#: v360 follow-up (owner, 2026-09-25) (item 9). The owner's tellings reached this
#: reader only through claims, and a telling the classifier drew no dated
#: moment from files none: *"I have my young buddy Harvey, my beautiful
#: daughter Charlee"* sits in answers/E27 and in no claim, so Charlee's card
#: stayed open. And a full-name row ("Charlee Joy Taylor", from the children
#: ladder) was read only by that full name, which he never says in passing.
HIS_OWN_TELLINGS_ARE_READ_BY_A_NAME_HE_USES = (
    "the relation word he used is read from his own tellings word for word — "
    "his answers, his own stories and his own messages, never a question or "
    "somebody else's record — and a person is found there by the given name he "
    "says as well as the full name the roster holds, when no other identity on "
    "the roster answers to that given name"
)

#: The frontmatter ``type`` of a source written in the owner's own words.
OWN_TELLING_TYPES = frozenset({"prompted_answer", "unprompted_story", "opinion",
                               "conversation_message"})
#: Where they live (`vault_contract.json`'s own registered directories).
OWN_TELLING_DIRS = ("answers", "sources/manual", "sources/conversations")

#: Lines in an answer file that are the SYSTEM's words: the question heading,
#: the asked/answered stamp and the follow-up questions it listed.
_NOT_HIS_LINE_RE = re.compile(
    r"^\s*(?:#|\*\*(?:Asked|Answered|Date)\b|[-*]\s*[A-Z]{1,2}\d+[a-z]?\s*:|>)")


def own_telling_texts(vault_root: object) -> dict[str, list[str]]:
    """``{source_path: [paragraph, …]}`` — the owner's own tellings, word for
    word (:data:`HIS_OWN_TELLINGS_ARE_READ_BY_A_NAME_HE_USES`). A conversation
    message counts only when the person spoke it. Unreadable files are
    skipped, as every read path here degrades."""
    import temporal_store as store  # noqa: PLC0415 - keeps this module import-light

    out: dict[str, list[str]] = {}
    if vault_root is None:
        return out
    root = Path(str(vault_root))
    for folder in OWN_TELLING_DIRS:
        base = root / folder
        if not base.is_dir():
            continue
        for path in sorted(base.glob("*.md")):
            if path.is_symlink() or not path.is_file():
                continue
            try:
                metadata, body = store.split_frontmatter(path.read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError):
                continue
            if not metadata or str(metadata.get("type") or "") not in OWN_TELLING_TYPES:
                continue
            speaker = str(metadata.get("speaker") or "person")
            if speaker not in ("person", "owner"):
                continue
            paragraphs = [line for line in (body or "").splitlines()
                          if line.strip() and not _NOT_HIS_LINE_RE.match(line)]
            if paragraphs:
                out[path.relative_to(root).as_posix()] = paragraphs
    return out


def given_name_census(roster: object) -> dict[str, frozenset]:
    """``{given name key: {identity refs}}`` — the first token of every identity
    row's own name, and every one-word spelling it answers to."""
    census: dict[str, set] = {}
    for entity in rr.roster_entities(roster):
        if is_alias_row(entity):
            target = ir.entity_ref(
                "person", rr.collapsed_text_of(entity.get(ir.ROSTER_MAPS_TO_FOCUS_KEY)))
        else:
            target = person_ref(entity)
        if not target:
            continue
        for spelling in _spellings(entity):
            name, _nicknames = rr.introduced_name(spelling)
            tokens = ir.normalized_mention_key(name or spelling).split()
            if tokens:
                census.setdefault(tokens[0], set()).add(target)
    return {key: frozenset(refs) for key, refs in census.items()}


def given_name_anchors(entity: object, census: object) -> list[str]:
    """The given name ("Charlee") of a multi-word row ("Charlee Joy Taylor"),
    when no other identity answers to it; ``[]`` otherwise."""
    if not isinstance(entity, dict):
        return []
    ref = person_ref(entity)
    name = rr.collapsed_text_of(entity.get("name"))
    parts = name.split()
    if len(parts) < 2 or not ref:
        return []
    given = parts[0]
    key = ir.normalized_mention_key(given)
    if len(key) < 3 or key in ir.RELATIONSHIP_MENTION_WORDS:
        return []
    owners = (census or {}).get(key) or frozenset()
    return [given] if owners == frozenset({ref}) else []


def texts_by_source(claims: object) -> dict[str, list[str]]:
    """``{source_id: [text, …]}`` — the texts a mention is read against.

    The same unit `roster_relations.relationship_introduction_batch` reads: the
    event mention, the subject mention and every evidence quote of the claims
    citing one source, so a relationship word in one telling never reaches a
    name in another.
    """
    out: dict[str, list[str]] = {}
    for claim in claims or ():
        if not isinstance(claim, dict):
            continue
        ref = claim.get("source_ref")
        source_id = rr.collapsed_text_of(ref.get("source_id")) if isinstance(ref, dict) else ""
        texts = out.setdefault(source_id, [])
        for value in (claim.get("event_mention"), claim.get("subject_mention")):
            body = rr.collapsed_text_of(value)
            if body and body not in texts:
                texts.append(body)
        for item in claim.get("evidence") or ():
            body = rr.collapsed_text_of(item.get("quote")) if isinstance(item, dict) else ""
            if body and body not in texts:
                texts.append(body)
    return out


def _shared_spelling_keys(roster: object) -> frozenset[str]:
    """Spellings more than one identity row answers to — "James" on four people.

    Such a spelling says nothing about which of them a phrase is about, so the
    reading below never anchors on it (the v334/v335 shared-name rule).
    """
    census: dict[str, set[str]] = {}
    for entity in rr.roster_entities(roster):
        if is_alias_row(entity):
            target = ir.entity_ref(
                "person", rr.collapsed_text_of(entity.get(ir.ROSTER_MAPS_TO_FOCUS_KEY)))
        else:
            target = person_ref(entity)
        for spelling in _spellings(entity):
            key = ir.normalized_mention_key(spelling)
            if key:
                census.setdefault(key, set()).add(target)
    return frozenset(key for key, owners in census.items() if len(owners) > 1)


def stated_words(entity: object, *, texts_by_source: object = None,
                 landmark_entries: object = (), owner_names: object = (),
                 shared_keys: object = frozenset(),
                 given_names: object = None) -> tuple[dict, ...]:
    """Every gendered relationship word the owner used about this person.

    ``[{"word", "where", "spelling"}]``, where ``where`` is ``roster`` (a
    spelling that is itself the word), ``landmark:family`` (a family record's
    ``relation``) or the ``source_id`` of the telling whose introduction said
    it. A word counts only when it is gendered AND belongs to this row's own
    relationship — "my son James" says nothing about a brother who shares the
    name — and an in-law clause is never read (``mother-in-law`` is not
    ``mother``).
    """
    if not isinstance(entity, dict):
        return ()
    relationship = rr.collapsed_text_of(entity.get("relationship"))
    if gendered_pair(relationship) is None:
        return ()
    shared = frozenset(shared_keys or ())

    def keep(word: str) -> bool:
        return bool(told_word_gender(word, relationship))

    found: list[dict] = []

    def add(word: str, where: str, spelling: str) -> None:
        row = {"word": word.casefold(), "where": where, "spelling": spelling}
        if row not in found:
            found.append(row)

    spellings = _spellings(entity)
    for spelling in spellings:
        word = bare_relation_word(spelling)
        if word and keep(word):
            add(word, "roster", spelling)
            continue
        name, _nicknames = rr.introduced_name(spelling)
        if name and name != spelling:
            match = rr.relationship_phrase_match(name, [spelling], owner_names=owner_names)
            if match and not ir.IN_LAW_RE.search(match["clause"]) and keep(match["word"]):
                add(match["word"], "roster", spelling)

    keys = {ir.normalized_mention_key(s) for s in spellings}
    for key, relation in sorted(rr.landmark_recorded_relations(landmark_entries).items()):
        if key in keys and key not in shared and keep(relation):
            add(relation, "landmark:family", key)

    anchors: list[str] = []
    for spelling in spellings:
        name, _nicknames = rr.introduced_name(spelling)
        key = ir.normalized_mention_key(name)
        if not name or key in shared or name in anchors:
            continue
        anchors.append(name)
    # :data:`HIS_OWN_TELLINGS_ARE_READ_BY_A_NAME_HE_USES`: the full-name row
    # "Charlee Joy Taylor" is also read by the given name he actually says —
    # "Charlee" — when no other identity on the roster answers to it.
    given_anchors = [given for given in given_name_anchors(entity, given_names or {})
                     if given not in anchors]
    sources = texts_by_source if isinstance(texts_by_source, dict) else {}
    for source_id in sorted(sources):
        texts = sources[source_id]
        for name in anchors:
            for match in (rr.relationship_phrase_match(name, texts, owner_names=owner_names),
                         told_phrase_match(name, texts, owner_names=owner_names)):
                if match is None or ir.IN_LAW_RE.search(match["clause"]):
                    continue
                if keep(match["word"]):
                    add(match["word"], source_id, name)
        for name in given_anchors:
            for match in (told_phrase_match(name, texts, owner_names=owner_names,
                                            given_only=True),):
                if match is None or ir.IN_LAW_RE.search(match["clause"]):
                    continue
                if keep(match["word"]):
                    add(match["word"], source_id, name)
    return tuple(found)


def stated_relation_gender(entity: object, **kwargs: object) -> dict | None:
    """``{"gender", "word", "basis": "stated", "evidence"}`` or ``None``.

    :func:`stated_words`, decided: every word the owner used must agree on one
    form. Two that disagree decide nothing, and the card asks.
    """
    words = stated_words(entity, **kwargs)
    relationship = rr.collapsed_text_of(entity.get("relationship")) \
        if isinstance(entity, dict) else ""
    genders = {told_word_gender(row["word"], relationship) for row in words}
    genders.discard("")
    if len(genders) != 1:
        return None
    gender = genders.pop()
    return {"gender": gender, "word": words[0]["word"], "basis": BASIS_STATED,
            "evidence": [dict(row) for row in words]}


def answered_relation_gender(entity: object) -> str:
    """The field the card's answer wrote, when it is one of :data:`RELATION_GENDERS`."""
    if not isinstance(entity, dict):
        return ""
    value = rr.collapsed_text_of(entity.get(RELATION_GENDER_FIELD)).casefold()
    return value if value in RELATION_GENDERS else ""


# --------------------------------------------------------------------------
# The published rows and the cards
# --------------------------------------------------------------------------


def relation_word_rows(roster: object, *, claims: object = (),
                       landmark_entries: object = (),
                       owner_names: object = (), told: object = None) -> tuple[dict, ...]:
    """One published row per roster person who has a relationship.

    ``{"subject_ref", "name", "spellings", "relationship", "relation_gender",
    "relation_gender_basis", "word", "label", "plural_word", "plural_label",
    "collective", "askable"}``, sorted by ``subject_ref``. Alias rows are
    skipped: their spellings are already their target's. ``relation_gender``
    is ``None`` when nothing the owner said decides it.
    """
    entities = [entity for entity in rr.roster_entities(roster)
                if not is_alias_row(entity)
                and rr.collapsed_text_of(entity.get("relationship"))]
    if not entities:
        return ()
    sources = texts_by_source(claims)
    for source_id, texts in (told or {}).items() if isinstance(told, dict) else ():
        bucket = sources.setdefault(f"told:{source_id}", [])
        for text in texts or ():
            body = rr.collapsed_text_of(text)
            if body and body not in bucket:
                bucket.append(body)
    shared = _shared_spelling_keys(roster)
    given = given_name_census(roster)
    rows: dict[str, dict] = {}
    for entity in entities:
        ref = person_ref(entity)
        if not ref or ref in rows:
            continue
        relationship = rr.collapsed_text_of(entity.get("relationship"))
        collective = is_collective_row(entity)
        gender = answered_relation_gender(entity)
        basis = BASIS_ANSWER if gender else ""
        if not gender and not collective:
            stated = stated_relation_gender(
                entity, texts_by_source=sources, landmark_entries=landmark_entries,
                owner_names=owner_names, shared_keys=shared, given_names=given)
            if stated is not None:
                gender, basis = stated["gender"], BASIS_STATED
        askable = bool(
            not gender
            and not collective
            and gendered_pair(relationship) is not None
            and not is_role_row(entity)
            and not is_owner_row(entity, owner_names)
        )
        rows[ref] = {
            "subject_ref": ref,
            "name": rr.collapsed_text_of(entity.get("name")),
            "spellings": sorted({ir.normalized_mention_key(s) for s in _spellings(entity)}
                                - {""}),
            "relationship": relationship,
            RELATION_GENDER_FIELD: gender or None,
            RELATION_GENDER_BASIS_FIELD: basis or None,
            "word": relation_word(relationship, gender, plural=collective),
            "label": relation_label(relationship, gender, plural=collective),
            "plural_word": relation_word(relationship, plural=True),
            "plural_label": relation_label(relationship, plural=True),
            "collective": collective,
            "askable": askable,
        }
    return tuple(rows[key] for key in sorted(rows))


def relation_card_question(name: object, relationship: object) -> str:
    """The card's question — "Is Harvey your son or your daughter …?"."""
    pair = gendered_pair(relationship)
    body = rr.collapsed_text_of(name)
    if pair is None or not body:
        return ""
    neutral = relation_word(relationship)
    return (f"Is {body} your {pair[0]} or your {pair[1]} — or would you "
            f"rather keep “{neutral}”?")


def relation_card_candidates(relationship: object) -> list[dict]:
    """The card's three options, as the ``candidates`` a work-item probe reads."""
    pair = gendered_pair(relationship)
    if pair is None:
        return []
    neutral = relation_word(relationship)
    return [{"ref": MALE, "name": pair[0]},
            {"ref": FEMALE, "name": pair[1]},
            {"ref": NEUTRAL_CHOICE, "name": f"just “{neutral}”"}]


def relation_word_cards(rows: object, *, now: object) -> tuple[dict, ...]:
    """At most one open card per askable row (:data:`A_CARD_ONLY_WHERE_THE_WORD_HAS_A_GENDERED_PAIR`).

    Validated through `temporal_projection.validate_temporal_work_item`, scored
    by the fold's own `temporal_timeline._score_components` from
    `temporal_timeline.WORK_ITEM_VALUE_DEFAULTS`, which prices this kind below
    every dating card; no ``resolves``/``leverage``, because the answer places
    no moment, so a host's leverage sort puts it last.
    """
    import temporal_projection as tp  # noqa: PLC0415
    import temporal_timeline as tt  # noqa: PLC0415
    import temporal_work_items as twi  # noqa: PLC0415

    out: list[dict] = []
    seen: set[str] = set()
    for row in rows or ():
        if not isinstance(row, dict) or not row.get("askable"):
            continue
        question = relation_card_question(row.get("name"), row.get("relationship"))
        if not question:
            continue
        ref = row["subject_ref"]
        work_item_id = twi.canonical_work_item_id(
            kind=RELATION_WORD_KIND, subject_ref=ref,
            requested_field=twi.REQUESTED_FIELD_RELATION_GENDER)
        if work_item_id in seen:
            continue
        seen.add(work_item_id)
        scores = tt._score_components(  # noqa: SLF001 — the fold's one scorer
            RELATION_WORD_KIND, system_value=0.0, event_kind=None,
            subject_ref=ref, resolved=True)
        item = tp.validate_temporal_work_item({
            "work_item_id": work_item_id,
            "kind": RELATION_WORD_KIND,
            "state": "open",
            "subject_ref": ref,
            "requested_field": RELATION_GENDER_FIELD,
            "prompt_intent": question,
            "allowed_surfaces": list(tt.SURFACES_BY_KIND[RELATION_WORD_KIND]),
            **scores,
            "created_at": now,
            "updated_at": now,
        }, now=now)
        item["label"] = row["name"]
        item["relationship"] = row["relationship"]
        item["candidates"] = relation_card_candidates(row["relationship"])
        out.append(item)
    return tuple(out)


def with_relation_words(payloads: dict, *, projection_key: str, roster: object,
                        claims: object = (), landmark_entries: object = (),
                        owner_names: object = (), now: object = None,
                        told: object = None) -> dict:
    """Publish the words and the cards onto a rendered payload pair, in place.

    The projection carries ``relation_words`` (only when there is a row, so a
    vault with no relationships publishes byte-identically to before); every
    payload carrying ``work_items`` gains the cards, after the fold's own items
    (they rank lowest), and its ``counts``. Returns ``{"rows", "cards"}``.
    """
    rows = relation_word_rows(roster, claims=claims, landmark_entries=landmark_entries,
                              owner_names=owner_names, told=told)
    projection = payloads.get(projection_key)
    if rows and isinstance(projection, dict):
        projection["relation_words"] = [dict(row) for row in rows]
    cards = relation_word_cards(rows, now=now)
    if cards:
        for payload in payloads.values():
            items = payload.get("work_items")
            if not isinstance(items, list):
                continue
            have = {str(row.get("work_item_id") or "") for row in items
                    if isinstance(row, dict)}
            added = [dict(card) for card in cards if card["work_item_id"] not in have]
            if not added:
                continue
            payload["work_items"] = [*items, *added]
            counts = payload.get("counts")
            if isinstance(counts, dict) and "work_items" in counts:
                counts["work_items"] = len(payload["work_items"])
            components = payload.get("score_components")
            if isinstance(components, dict):
                for card in added:
                    components[card["work_item_id"]] = {
                        key: card[key] for key in (
                            "person_value", "system_value", "interaction_cost",
                            "sensitivity", "context_fit", "combined_score")
                        if key in card}
    return {"rows": rows, "cards": cards}


# --------------------------------------------------------------------------
# The answer
# --------------------------------------------------------------------------

#: Words that choose the neutral option when no gendered word is given.
_NEUTRAL_CHOICE_WORDS = frozenset({"neutral", "either", "keep"})


def read_relation_answer(text: object, relationship: object) -> str:
    """``male`` / ``female`` / ``neutral`` for a reply to the card, or ``""``.

    Whole tokens only, through the one vocabulary. A gendered word counts when
    it is this relationship's own (``son`` answering a ``child`` card, "he's
    my boy" does not) and is not part of a compound — an in-law suffix or a
    prefix such as ``step`` (`identity_resolution._not_a_simple_relation`) —
    or a possessor (``son's``). One form, and the answer is that form; both
    forms is no answer. No gendered word but the neutral word itself, or a
    "keep"/"neutral"/"either", chooses the neutral word.
    """
    neutral = rr.collapsed_text_of(relationship).casefold()
    if gendered_pair(neutral) is None:
        return ""
    tokens = ir.normalized_mention_key(text).split()
    genders: set[str] = set()
    said_neutral = False
    for index, token in enumerate(tokens):
        stem = ir.relation_word_stem(token)
        if not stem:
            continue
        if index + 1 < len(tokens) and tokens[index + 1] == "s":
            continue  # a possessor: "my son's wife" is not the answer "wife"
        if ir._not_a_simple_relation(tokens, index, index + 1):  # noqa: SLF001
            continue
        if rr.roster_relationship_for(stem) != neutral:
            continue
        gender = word_gender(stem)
        if gender:
            genders.add(gender)
        elif stem == neutral or ir.RELATIONSHIP_MENTION_WORDS.get(stem) == \
                ir.RELATIONSHIP_MENTION_WORDS.get(neutral):
            said_neutral = True
    if len(genders) == 1:
        return genders.pop()
    if genders:
        return ""
    if said_neutral or _NEUTRAL_CHOICE_WORDS & set(tokens):
        return NEUTRAL
    return ""


def _roster_path(vault_root: object) -> Path:
    from vault_paths import vault_data_path  # noqa: PLC0415

    return Path(vault_data_path("entity_rosters", vault_root=vault_root)) / "person.json"


def record_relation_gender(vault_root: object, slug: object, gender: object, *,
                           basis: object = BASIS_ANSWER) -> dict:
    """Write the field onto one roster row, atomically. Returns the row.

    The field and its basis and nothing else: no verdict, no eligibility, no
    alias is touched, which is why this is not `entity_verdict.apply_verdict`
    (whose every call re-decides a page verdict). Refuses — writing nothing —
    an unknown value, an unknown basis, a missing roster or a missing slug.
    """
    from lifehug_core import read_json  # noqa: PLC0415
    from vault_paths import atomic_write_vault_text  # noqa: PLC0415

    value = rr.collapsed_text_of(gender).casefold()
    if value not in RELATION_GENDERS:
        raise ValueError(f"unknown relation_gender: {gender!r}")
    why = rr.collapsed_text_of(basis)
    if why not in RELATION_GENDER_BASES:
        raise ValueError(f"unknown relation_gender_basis: {basis!r}")
    path = _roster_path(vault_root)
    data = read_json(path, default=None)
    entities = (data or {}).get("entities") if isinstance(data, dict) else None
    if not entities:
        raise ValueError("no person roster on disk")
    wanted = rr.collapsed_text_of(slug)
    target = next((entity for entity in entities if isinstance(entity, dict)
                   and rr.collapsed_text_of(entity.get("slug")) == wanted), None)
    if target is None:
        raise ValueError(f"no such person: {wanted!r}")
    target[RELATION_GENDER_FIELD] = value
    target[RELATION_GENDER_BASIS_FIELD] = why
    atomic_write_vault_text(path, json.dumps(data, indent=2) + "\n",
                            vault_root=vault_root)
    return target


def _card_row(work_items: object, work_item_id: str) -> dict | None:
    import temporal_work_items as twi  # noqa: PLC0415

    rows = [row for row in ((work_items or {}).get("work_items") or ())
            if isinstance(row, dict)]
    aliases = (work_items or {}).get("work_item_aliases")
    aliases = aliases if isinstance(aliases, dict) else {}
    wanted = rr.collapsed_text_of(twi.resolve_work_item_id(work_item_id, aliases=aliases)) \
        or work_item_id
    for row in rows:
        if rr.collapsed_text_of(row.get("work_item_id")) == wanted:
            return row
    return None


_PERSON_REF_RE = re.compile(r"^person/(?P<slug>[^/\s]+)$")


def relation_card_of_session(vault_root: object, session_ref: object, *,
                             work_items: object = None) -> dict | None:
    """The published relation-word card a session answers, or ``None``."""
    import answer_placement as ap  # noqa: PLC0415
    import temporal_publication as pub  # noqa: PLC0415

    wanted = ap.work_item_of_session(session_ref)
    if not wanted:
        return None
    if work_items is None:
        work_items = pub.read_work_items(vault_root) or {}
    row = _card_row(work_items, wanted)
    if row is None or rr.collapsed_text_of(row.get("kind")) != RELATION_WORD_KIND:
        return None
    return row


def file_relation_answer(vault_root: object, *, session_ref: object, text: object,
                         work_items: object = None, roster: object = None,
                         dry_run: bool = False) -> dict | None:
    """File one reply to a relation-word card. ``None`` when it answers none.

    ``{"work_item_id", "subject_ref", "slug", "relation_gender", "written",
    "refused"}``. The field is written with basis ``answer`` — the owner's
    decision, which outranks anything read from his tellings — unless the row
    already carries an answer (an answered card is never re-decided by a later
    reply to the same conversation) or the reply names no form.
    """
    import entity_roster  # noqa: PLC0415

    card = relation_card_of_session(vault_root, session_ref, work_items=work_items)
    if card is None:
        return None
    ref = rr.collapsed_text_of(card.get("subject_ref"))
    match = _PERSON_REF_RE.match(ref)
    report = {"work_item_id": rr.collapsed_text_of(card.get("work_item_id")),
              "subject_ref": ref, "slug": match.group("slug") if match else "",
              "relation_gender": "", "written": False, "refused": ""}
    if roster is None:
        roster = entity_roster.load_roster("person", vault_root=vault_root)
    entity = next((row for row in rr.roster_entities(roster)
                   if person_ref(row) == ref and not is_alias_row(row)), None)
    if entity is None:
        report["refused"] = REFUSED_PERSON_NOT_ON_ROSTER
        return report
    if answered_relation_gender(entity):
        report["relation_gender"] = answered_relation_gender(entity)
        report["refused"] = REFUSED_ALREADY_KNOWN
        return report
    gender = read_relation_answer(text, entity.get("relationship"))
    if not gender:
        report["refused"] = REFUSED_ANSWER_UNREADABLE
        return report
    report["relation_gender"] = gender
    report["slug"] = rr.collapsed_text_of(entity.get("slug")) or report["slug"]
    if not dry_run:
        record_relation_gender(vault_root, report["slug"], gender, basis=BASIS_ANSWER)
        report["written"] = True
    return report


__all__ = [
    "A_CARD_ONLY_WHERE_THE_WORD_HAS_A_GENDERED_PAIR",
    "A_GENDERED_WORD_WHEN_IT_IS_KNOWN",
    "BASIS_ANSWER",
    "BASIS_STATED",
    "FEMALE",
    "MALE",
    "NEUTRAL",
    "RELATION_ANSWER_REFUSALS",
    "RELATION_GENDERS",
    "RELATION_GENDER_BASES",
    "RELATION_GENDER_BASIS_FIELD",
    "RELATION_GENDER_FIELD",
    "RELATION_WORD_KIND",
    "RELATION_WORD_RULE_VERSION",
    "THE_FIELD_IS_SET_ONLY_BY_THE_OWNERS_OWN_WORDS",
    "WORD_GENDER",
    "answered_relation_gender",
    "bare_relation_word",
    "canonical_gendered_word",
    "file_relation_answer",
    "gendered_pair",
    "gendered_relationships",
    "read_relation_answer",
    "record_relation_gender",
    "relation_card_question",
    "relation_label",
    "relation_word",
    "relation_word_cards",
    "relation_word_rows",
    "stated_relation_gender",
    "stated_words",
    "with_relation_words",
    "word_gender",
]
