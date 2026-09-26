"""Cornerstones — the fixed dated points a life is measured from.

The owner named them (2026-09-25), beside the two words the Timeline already
had:

* **landmarks** are the universal dating skeleton — the questions everyone
  gets, answered as spans and points, by domain (`interactions/landmarks/`);
* **keystones** are computed — the highest-leverage unknown right now
  (`timeline.keystones`, at most two starred);
* **cornerstones** are FIXED — the same small set for everyone, each a single
  day, and worth asking outright because everything else is measured from
  them.

    "We almost never need more than month precision except for extremely
    important dates like birth, death, wedding, divorce." ... "I like
    Cornerstones … I agree with that set. If I happen to mention a cornerstone
    for someone else in a discussion, I think it's worth a question. For
    example, 'When did your sister get divorced?' You accept the precision I
    give you, which is probably not a date but more like a month or a year.
    And yes marriages should become spans and stay open while you're married."
    (owner, 2026-09-25)

The set (:data:`CORNERSTONES`) is written over the vocabulary that already
exists rather than as a parallel list: the MILESTONE a node is comes from
`temporal_claims.EVENT_KINDS` (:data:`MILESTONE_OF_EVENT_KIND`), and WHOSE it
is comes from the roster's own relationship vocabulary
(`axis_membership.IMMEDIATE_FAMILY_RELATIONSHIPS`, `focus_candidate`'s
closed list) plus ``self``. A landmark entry says the relationship where the
roster does not (`children` -> child, an owner `partnerships` marriage ->
spouse, `family` -> its own ``relation`` rung).

This module DECIDES nothing about placement. It answers three questions the
fold asks: is this node a cornerstone (and whose), what grain may a card about
it ask for (`temporal_work_items.A_DAY_IS_ASKED_ONLY_OF_A_CORNERSTONE`), and
what the owner's cornerstones currently are (:func:`cornerstone_table`).

Pure; synthetic data only in its tests; NEVER references any real vault.
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

SYSTEM_DIR = Path(__file__).resolve().parent
if str(SYSTEM_DIR) not in sys.path:
    sys.path.insert(0, str(SYSTEM_DIR))

import chronology as chrono  # noqa: E402
import identity_resolution as ir  # noqa: E402
import temporal_claims as tc  # noqa: E402
from temporal_claims import collapsed_text, normalized_mention_key  # noqa: E402

# --------------------------------------------------------------------------
# The term and the set
# --------------------------------------------------------------------------

#: The owner's own word, as the rule text every seat cites.
CORNERSTONES_ARE_THE_FIXED_DAYS = (
    "a cornerstone is one of the small fixed set of dates, the same for "
    "everyone, that a life is measured from: the owner's birth; each child's "
    "birth; the births of his parents, siblings and spouse; each of his "
    "weddings and divorces; the deaths of his parents, spouse, siblings, "
    "children and grandparents; and his baptism, only once he mentions it. A "
    "cornerstone is asked to the DAY; every other moment is asked no finer "
    "than a month"
)

#: The milestones, keyed by the `temporal_claims.EVENT_KINDS` words that ARE
#: them. `child_born` is a birth and `loss` is a death exactly as
#: `episode_binder.MILESTONE_OF_EVENT_KIND` reads them; `divorced` and
#: `baptism` are the two it does not need and this set does.
MILESTONE_OF_EVENT_KIND = {
    "birth": "birth",
    "child_born": "birth",
    "death": "death",
    "loss": "death",
    "married": "wedding",
    "divorced": "divorce",
    "baptism": "baptism",
}
assert set(MILESTONE_OF_EVENT_KIND) <= set(tc.EVENT_KINDS), "a cornerstone kind left EVENT_KINDS"

MILESTONES = ("birth", "wedding", "divorce", "death", "baptism")

#: The owner's own subject.
SELF = "self"

#: THE SET, as (milestone, whose). ``whose`` is roster relationship words plus
#: :data:`SELF`. A wedding and a divorce are the OWNER's and his spouse's at
#: once — either end of the couple names the same day — so both words are
#: listed; a baptism is his alone and only once mentioned (v356's
#: `A_LADDER_OPENS_ON_A_MENTION`: no node exists until he raises it).
CORNERSTONES = (
    ("birth", (SELF, "child", "parent", "sibling", "spouse")),
    ("wedding", (SELF, "spouse")),
    ("divorce", (SELF, "spouse")),
    ("death", ("parent", "spouse", "sibling", "child", "grandparent")),
    ("baptism", (SELF,)),
)
WHOSE = {milestone: frozenset(whose) for milestone, whose in CORNERSTONES}

#: The relationship words the set speaks, checked against the roster's own
#: vocabulary by the tests (`axis_membership.IMMEDIATE_FAMILY_RELATIONSHIPS`).
RELATIONSHIPS = ("parent", "grandparent", "child", "grandchild", "sibling",
                 "spouse", "partner")

#: The three answers :func:`status_of` gives.
CORNERSTONE = "cornerstone"
#: A cornerstone-TYPE event (a birth, a wedding, a divorce, a death, a
#: baptism) for somebody outside the set — his sister's divorce, a friend's
#: wedding. Worth ONE question at whatever grain he gives, never pressed.
OUTSIDE_THE_SET = "outside_the_set"
NOT_A_CORNERSTONE = ""

#: The grains a card may ask for (`temporal_work_items.precision_card_grain`).
CORNERSTONE_GRAIN = "day"
OUTSIDE_THE_SET_GRAIN = "year"
#: "Never ask him to go finer than a month" — for everything that is not a
#: cornerstone, whatever its leverage.
FINEST_GRAIN_FOR_EVERYTHING_ELSE = "month"


# --------------------------------------------------------------------------
# What milestone a node is
# --------------------------------------------------------------------------

#: The milestone read out of a LABEL, for the `moment` wildcard the classifier
#: gives "a thing that happened" ("Father dies of COVID"). Whole tokens, and
#: only in the shape a telling OF the milestone has — see
#: :func:`milestone_of_label`. `marriage` is deliberately absent (a marriage is
#: the SPAN, not the day), as are plurals ("Grandfathers' deaths" is two).
MILESTONE_OF_LABEL_WORD = {
    "birth": "birth", "born": "birth",
    "death": "death", "died": "death", "dies": "death", "die": "death",
    "wedding": "wedding", "married": "wedding", "marries": "wedding",
    "divorce": "divorce", "divorced": "divorce", "divorces": "divorce",
    "baptism": "baptism", "baptized": "baptism", "baptised": "baptism",
}

#: Words that may stand before the milestone word in a telling OF it: the
#: owner's and the possessive handles. Anything else before it ("Begins
#: processing father's death", "Dad's words of pride before death") means the
#: label is about something else that happened near the milestone.
_LEADING_WORDS = frozenset({"my", "our", "his", "her", "the", "a", "grandpa",
                            "grandma", "grandfather", "grandmother"})
_ADJUNCTS = frozenset({"after", "before", "during", "since", "until", "till",
                       "near", "around", "about", "following", "post", "pre",
                       "anniversary", "processing"})
_TOKEN_RE = re.compile(r"[a-z0-9]+")

#: Roster rows that name a role rather than a person ("Friend", "Neighbor").
_GENERIC_ROWS = frozenset({"friend", "neighbor", "neighbour", "kids", "family",
                           "colleague", "boss", "mentor"})


def _tokens(text: object) -> list[str]:
    body = collapsed_text(text).casefold().replace("’", "'")
    body = re.sub(r"'s\b|s'(?=\s|$)", "", body)
    # A normalized handle spells a possessive as a lone "s" ("dad s death").
    return [token for token in _TOKEN_RE.findall(body) if token != "s"]


def milestone_of_kind(event_kind: object) -> str:
    return MILESTONE_OF_EVENT_KIND.get(collapsed_text(event_kind), "")


def milestone_of_label(label: object, *, subject_words: object = ()) -> str:
    """The milestone a label TELLS, or ``""``.

    One milestone word, no conjunction ("Father's near-death and death" is two
    things), no adjunct before it, and every word before it is a subject word
    (a name the node's subjects or the roster carry, a relation word, a
    possessive handle). "Father dies of COVID", "Grandpa died at 66", "Betty
    Jo's death in Gilbert", "Married Katie", "Dottie's birth" pass; "Dad's
    words of pride before death" and "Grandfathers' deaths" do not.
    """
    tokens = _tokens(label)
    if not tokens or "and" in tokens:
        return ""
    hits = [(index, MILESTONE_OF_LABEL_WORD[token]) for index, token in enumerate(tokens)
            if token in MILESTONE_OF_LABEL_WORD]
    if len({milestone for _, milestone in hits}) != 1:
        return ""
    index, milestone = hits[0]
    allowed = set(_LEADING_WORDS) | set(ir.RELATIONSHIP_MENTION_WORDS)
    allowed |= set(ir.OWNER_SUBJECT_MENTIONS)
    for word in subject_words or ():
        allowed.update(_tokens(word))
    for token in tokens[:index]:
        if token in _ADJUNCTS or token not in allowed:
            return ""
    return milestone


def milestone_of_node(node: object) -> str:
    """The milestone this node is: its kind first, else its label's reading."""
    row = node if isinstance(node, dict) else {}
    milestone = milestone_of_kind(row.get("event_kind"))
    if milestone:
        return milestone
    if collapsed_text(row.get("event_kind")) not in ("", "moment"):
        return ""
    if collapsed_text(row.get("node_kind")) == "period":
        return ""
    return milestone_of_label(row.get("label"), subject_words=[
        collapsed_text(ref).rpartition("/")[2].replace("-", " ")
        for ref in (row.get("subject_refs") or ())
    ])


# --------------------------------------------------------------------------
# What a cornerstone is called (v360 follow-up, owner 2026-09-25, item 3)
# --------------------------------------------------------------------------

#: The owner's wedding, folded from twelve tellings, was titled "Wedding
#: reception in mother-in-law's backyard" — the LONGEST telling's words
#: (`temporal_timeline._node_what`), which here named a party that happened on
#: the day rather than the day itself. A cornerstone is the fixed point a life
#: is measured from; its title is its own name.
A_CORNERSTONE_IS_TITLED_BY_ITS_OWN_NAME = (
    "a cornerstone node's title comes from the cornerstone itself, never from "
    "the longest or first telling: a landmark entry's own words for it first, "
    "then a telling filed under the milestone's own kind (\"Married Katie Ann "
    "Merrill\"), then a telling titled as nothing but the milestone and who "
    "(\"Married Katie\", \"Father's death\"); only when none of those exists is "
    "the longest telling kept"
)

#: Words a title OF the milestone may carry besides the milestone word and the
#: people it is about.
_TITLE_GLUE = frozenset({"to", "of", "the", "a", "my", "our", "his", "her", "and"})


def _is_landmark_claim(claim: dict) -> bool:
    ref = claim.get("source_ref") if isinstance(claim.get("source_ref"), dict) else {}
    source_id = collapsed_text(ref.get("source_id"))
    path = collapsed_text(ref.get("source_path"))
    return (source_id.startswith(("landmark:", "classification:sources-landmarks-"))
            or path.startswith("sources/landmarks/"))


def names_only_the_milestone(label: object, milestone: object, name_words: object) -> bool:
    """Is this label the milestone and who, and nothing else?"""
    tokens = _tokens(label)
    if not tokens or "and" in tokens:
        return False
    hits = [token for token in tokens if MILESTONE_OF_LABEL_WORD.get(token) == milestone]
    if len(hits) != 1:
        return False
    allowed = set(_TITLE_GLUE) | set(_LEADING_WORDS) | set(ir.RELATIONSHIP_MENTION_WORDS)
    allowed |= set(ir.OWNER_SUBJECT_MENTIONS)
    allowed |= {token for word in (name_words or ()) for token in _tokens(word)}
    return all(token in allowed or token in hits for token in tokens)


def cornerstone_title(claims: object, milestone: object, *, subject_words: object = (),
                      name_words: object = ()) -> str:
    """The title :data:`A_CORNERSTONE_IS_TITLED_BY_ITS_OWN_NAME` gives, or ``""``
    (keep the fold's own). Every candidate must itself read as the milestone
    (:func:`milestone_of_label`); within a tier the longest wins, then the
    alphabetically first, so the choice is a pure function of the claim set."""
    rows = [claim for claim in claims or () if isinstance(claim, dict)]
    words = tuple(subject_words or ()) + tuple(name_words or ())

    def mentions(select) -> list[str]:
        found = []
        for claim in rows:
            text = collapsed_text(claim.get("event_mention"))
            if (text and select(claim, text) and text not in found
                    and milestone_of_label(text, subject_words=words) == milestone):
                found.append(text)
        return found

    tiers = (
        mentions(lambda claim, _text: _is_landmark_claim(claim)),
        mentions(lambda claim, _text: milestone_of_kind(claim.get("event_kind")) == milestone),
        mentions(lambda _claim, text: names_only_the_milestone(text, milestone, words)),
    )
    for tier in tiers:
        if tier:
            return sorted(tier, key=lambda text: (-len(text), text))[0]
    return ""


def name_words_of(relations: "Relations") -> tuple[str, ...]:
    """Every name the roster and the landmark entries give a person."""
    out: list[str] = []
    for person in getattr(relations, "people", ()) or ():
        for name in sorted(person.names):
            if name not in out:
                out.append(name)
    return tuple(out)


# --------------------------------------------------------------------------
# Whose it is
# --------------------------------------------------------------------------


def _relationship_of_word(word: object) -> str:
    """The roster relationship a relation word states (``father`` -> parent)."""
    key = normalized_mention_key(word)
    wanted = ir.RELATIONSHIP_MENTION_WORDS.get(key)
    if wanted is None and key and not ir.IN_LAW_RE.search(collapsed_text(word)):
        # "maternal grandfather", "older sister": the head word says it.
        wanted = ir.RELATIONSHIP_MENTION_WORDS.get(key.split()[-1])
    return next((value for value in RELATIONSHIPS if value in (wanted or ())), "")


@dataclass
class Person:
    key: str
    name: str
    relationship: str = ""
    names: set = field(default_factory=set)
    born: object = None

    def tokens(self) -> set:
        found: set = set()
        for name in self.names:
            found.update(_tokens(name))
        return found


def _collective(text: object) -> bool:
    import landmark_projection as lp  # noqa: PLC0415 - avoids an import cycle
    return lp.is_collective_subject(text)


class Relations:
    """Who is who, read once per fold from the roster and the landmark entries.

    The roster's stated ``relationship`` first (the owner's own statement), then
    the words its row is titled with ("Grandma Betty Jo"); a landmark entry
    names the relationship its domain implies (`children` -> child; an owner's
    `partnerships` entry that dates a marriage -> spouse; `family` -> the entry's
    own ``relation`` rung). A collective row ("Kids", "Parents") is nobody.
    """

    def __init__(self, roster_snapshot: object = (), landmark_entries: object = (), *,
                 owner_names: object = ()) -> None:
        import axis_membership as axm  # noqa: PLC0415 - avoids an import cycle
        import landmark_projection as lp  # noqa: PLC0415

        self.people: list[Person] = []
        self.owner_keys = {normalized_mention_key(name) for name in owner_names or ()
                           if normalized_mention_key(name)}
        for row in axm.roster_person_rows(roster_snapshot):
            name = collapsed_text(row.get("name"))
            if not name or _collective(name) or self.is_owner_text(name):
                continue
            if all(token in ir.RELATIONSHIP_MENTION_WORDS or token in _GENERIC_ROWS
                   for token in _tokens(name)):
                # "Son", "Daughter", "Friend" — a relationship word, not a person.
                continue
            slug = (normalized_mention_key(row.get("slug"))
                    or normalized_mention_key(name)).replace(" ", "-")
            relationship = collapsed_text(row.get("relationship"))
            if relationship not in RELATIONSHIPS:
                relationship = ""
            names = {name, slug.replace("-", " "), *[a for a in (row.get("aliases") or ())
                                                     if isinstance(a, str)]}
            if not relationship:
                relationship = next((found for found in (
                    _relationship_of_word(token) for text in names for token in _tokens(text))
                    if found), "")
            self._add(Person(key=ir.entity_ref("person", slug), name=name,
                             relationship=relationship, names=names,
                             born=row.get("born")))
        for source in landmark_entries or ():
            if not isinstance(source, dict):
                continue
            domain = collapsed_text(source.get("domain"))
            record = source.get("record") if isinstance(source.get("record"), dict) else {}
            who = collapsed_text(record.get("who") or record.get("label"))
            if not who or _collective(who):
                continue
            relationship = ""
            if domain == "children":
                relationship = "child"
            elif domain == "family":
                relationship = (collapsed_text(record.get("relation"))
                                if collapsed_text(record.get("relation")) in RELATIONSHIPS
                                else _relationship_of_word(record.get("relation")))
            elif domain == "partnerships":
                if collapsed_text(record.get("subject")) and not self.is_owner_text(
                        record.get("subject")):
                    continue
                if not self.partnership_is_a_marriage(record):
                    continue
                relationship = "spouse"
            elif domain != "losses":
                continue
            names = {who, *[collapsed_text(record.get(key)) for key in ("label", "subject")
                            if collapsed_text(record.get(key))]}
            self._add(Person(key=f"landmark:{normalized_mention_key(who)}", name=who,
                             relationship=relationship, names=names))

    @staticmethod
    def partnership_is_a_marriage(record: dict) -> bool:
        """Does an owner's `partnerships` record date a MARRIAGE?

        Its own words (`landmark_projection.entry_words_name_a_marriage`, read
        over the record and the provenance of its date), or a date semantic of
        ``married`` filed on it.
        """
        import landmark_projection as lp  # noqa: PLC0415

        if lp.entry_words_name_a_marriage(record):
            return True
        date = record.get("date") if isinstance(record.get("date"), dict) else {}
        for item in date.get("provenance") or ():
            if isinstance(item, dict) and re.search(
                    r"\b(married|marry|wedding|wed)\b", str(item.get("claim") or ""), re.I):
                return True
        return collapsed_text(record.get("event")) == "married"

    def _add(self, person: Person) -> None:
        keys = {normalized_mention_key(n) for n in person.names if normalized_mention_key(n)}
        for held in self.people:
            held_keys = {normalized_mention_key(n) for n in held.names}
            if (keys & held_keys or self._nested(person.tokens(), held.tokens())
                    or self._same_given_name(person, held)):
                held.names |= person.names
                held.relationship = held.relationship or person.relationship
                held.born = held.born or person.born
                return
        self.people.append(person)

    @staticmethod
    def _nested(left: set, right: set) -> bool:
        return len(left & right) >= 2 and (left <= right or right <= left)

    @staticmethod
    def _same_given_name(left: "Person", right: "Person") -> bool:
        """"Harvey" and "Harvey Rex Taylor", both a child; "Katie Taylor" and
        "Katie Ann Merrill", both the spouse — one person under a short name or
        a maiden name. Only inside ONE relationship, and for a child or a
        sibling only when one side is the bare given name, so two children
        who share a first name are never folded by it."""
        if not left.relationship or left.relationship != right.relationship:
            return False
        a, b = _tokens(left.name), _tokens(right.name)
        if not a or not b or a[0] != b[0]:
            return False
        return len(a) == 1 or len(b) == 1 or left.relationship in ("spouse", "parent")

    def is_owner_text(self, text: object) -> bool:
        key = normalized_mention_key(text)
        return bool(key) and (key in ir.OWNER_SUBJECT_MENTIONS or key in self.owner_keys)

    def person_for(self, text: object) -> Person | None | str:
        """One subject mention -> a :class:`Person`, :data:`SELF`, or ``None``."""
        body = collapsed_text(text)
        if not body:
            return None
        if body.startswith("person/"):
            for person in self.people:
                if person.key == body:
                    return person
            body = body.partition("/")[2].replace("-", " ")
        key = normalized_mention_key(body)
        if self.is_owner_text(key):
            return SELF
        # "narrator's father", "Dave's father", "my dad" — the owner's X is X.
        words = _tokens(body)
        stripped = True
        while stripped and len(words) > 1:
            stripped = False
            for size in (2, 1):
                head = " ".join(words[:size])
                if len(words) > size and (head in ("my", "the", "our")
                                          or self.is_owner_text(head)):
                    words, stripped = words[size:], True
                    break
        key = " ".join(words)
        exact = [p for p in self.people
                 if key in {normalized_mention_key(n) for n in p.names}]
        if len(exact) == 1:
            return exact[0]
        tokens = set(_tokens(key))
        if not tokens:
            return None
        nested = [p for p in self.people
                  if (tokens <= p.tokens() or (p.tokens() and p.tokens() <= tokens))
                  and not (len(tokens) == 1 and next(iter(tokens)) in ir.RELATIONSHIP_MENTION_WORDS)]
        if len(nested) == 1:
            return nested[0]
        relationship = _relationship_of_word(key)
        if relationship:
            # A bare relation word nobody's aliases carry still says WHICH
            # relationship; the person is the one roster row holding it, or a
            # handle of its own.
            holders = [p for p in self.people if p.relationship == relationship
                       and key in {normalized_mention_key(n) for n in p.names}]
            if len(holders) == 1:
                return holders[0]
            return Person(key=f"relation:{key}", name=key, relationship=relationship,
                          names={key})
        return None

    def whose(self, subjects: object) -> Person | str | None:
        """The one person a node is ABOUT: a named person outranks the owner."""
        found: list = []
        for subject in subjects or ():
            person = self.person_for(subject)
            if person is not None:
                found.append(person)
        others = {p.key: p for p in found if isinstance(p, Person)}
        if len(others) == 1:
            return next(iter(others.values()))
        if others:
            return None
        return SELF if found else None


def status_of(milestone: object, whose: object) -> str:
    """:data:`CORNERSTONE`, :data:`OUTSIDE_THE_SET` or :data:`NOT_A_CORNERSTONE`."""
    name = collapsed_text(milestone)
    if name not in WHOSE:
        return NOT_A_CORNERSTONE
    relationship = SELF if whose == SELF else (
        whose.relationship if isinstance(whose, Person) else "")
    return CORNERSTONE if relationship in WHOSE[name] else OUTSIDE_THE_SET


def label_lead(label: object) -> str:
    """The words before a label's milestone word — who the label says it is
    about ("Father's death" -> ``father``), or ``""``."""
    tokens = _tokens(label)
    for index, token in enumerate(tokens):
        if token in MILESTONE_OF_LABEL_WORD:
            return " ".join(tokens[:index])
    return ""


def node_status(node: object, relations: Relations) -> tuple[str, str, object]:
    """``(status, milestone, whose)`` for one node.

    Whose is read off the node's SUBJECTS; when they name only the owner (the
    classifier often files a telling about his father under ``self``), the
    label's own possessor decides — "Father's death" is his father's.
    """
    row = node if isinstance(node, dict) else {}
    milestone = milestone_of_node(row)
    if not milestone:
        return NOT_A_CORNERSTONE, "", None
    whose = relations.whose(row.get("subject_refs") or ())
    if whose in (SELF, None):
        lead = label_lead(row.get("label"))
        named = relations.person_for(lead) if lead else None
        if isinstance(named, Person) and named.relationship:
            whose = named
    return status_of(milestone, whose), milestone, whose


def is_known_person(whose: object) -> bool:
    """A person the roster or a landmark entry holds (or the owner) — the only
    ones a cornerstone card may be asked about. "My maternal grandfather" when
    two men could be meant is a relationship, not yet a person."""
    return whose == SELF or (isinstance(whose, Person)
                             and not whose.key.startswith("relation:"))


def is_a_day(record: object) -> bool:
    """Is this placement a single known DAY?"""
    parsed = chrono.from_dict(record)
    return bool(parsed and parsed.earliest and parsed.earliest == parsed.latest
                and len(parsed.earliest) == 10)


# --------------------------------------------------------------------------
# The owner's cornerstones, as a table
# --------------------------------------------------------------------------


def _whose_key(whose: object) -> str:
    return SELF if whose == SELF else (whose.key if isinstance(whose, Person) else "")


def _rank(node: dict) -> tuple:
    record = chrono.from_dict(node.get("best_temporal_value"))
    width = chrono.span_months(record) if record is not None else None
    stated = bool(record and record.basis in ("stated", "document"))
    return (record is None, not is_a_day(record), not stated,
            width if width is not None else 10 ** 6, collapsed_text(node.get("node_id")))


def cornerstone_nodes(nodes: object, relations: Relations) -> dict:
    """``{(milestone, whose key): [node, ...]}`` for every owner cornerstone,
    best-placed node first (a day, then stated, then narrowest)."""
    grouped: dict[tuple, list] = {}
    for node in nodes or ():
        if not isinstance(node, dict):
            continue
        status, milestone, whose = node_status(node, relations)
        if status != CORNERSTONE:
            continue
        if milestone in ("wedding", "divorce"):
            # One couple, two ends: the owner's wedding to his spouse is ONE
            # cornerstone whichever of the two a telling names.
            whose = SELF
        grouped.setdefault((milestone, _whose_key(whose)), []).append(node)
    return {key: sorted(rows, key=_rank) for key, rows in sorted(grouped.items())}


def cornerstone_table(nodes: object, relations: Relations) -> list[dict]:
    """Each cornerstone the vault holds or owes: whose, value, grain, and
    whether a card would ask for the day.

    A birth is owed for everyone in the set whether or not it was mentioned; a
    death only once it is (a node, or a `losses` entry) — nothing here ever
    invokes anybody's mortality; a wedding, a divorce and a baptism only once
    told.
    """
    held = cornerstone_nodes(nodes, relations)
    rows: list[dict] = []
    for (milestone, key), members in held.items():
        best = members[0]
        record = best.get("best_temporal_value")
        person = next((p for p in relations.people if p.key == key), None)
        rows.append({
            "milestone": milestone,
            "whose": "owner" if key == SELF else (person.name if person else key),
            "relationship": SELF if key == SELF else (person.relationship if person else
                                                      key.partition(":")[2]),
            "node_id": best.get("node_id"),
            "label": best.get("label"),
            "nodes": len(members),
            "value": (chrono.to_edtf(chrono.from_dict(record)) if record else None),
            "grain": _grain(record),
            "asks_for_the_day": not is_a_day(record),
            # A card is minted only about somebody the vault can name.
            "card": not is_a_day(record) and (key == SELF or person is not None),
        })
    births = {key for (milestone, key) in held if milestone == "birth"}
    for person in relations.people:
        if person.relationship in WHOSE["birth"] and person.key not in births:
            born = chrono.from_dict(person.born) if person.born else None
            rows.append({
                "milestone": "birth", "whose": person.name,
                "relationship": person.relationship, "node_id": None, "label": None,
                "nodes": 0,
                "value": chrono.to_edtf(born) if born else None,
                "grain": _grain(person.born) if born else None,
                "asks_for_the_day": not is_a_day(born) if born else True,
                # No node to ask on: the family/children ladder's own birth
                # rung is where a birth nobody has told yet is asked.
                "card": False,
            })
    return sorted(rows, key=lambda r: (MILESTONES.index(r["milestone"]),
                                       r["relationship"] != SELF, r["whose"]))


def _grain(record: object) -> str | None:
    parsed = chrono.from_dict(record)
    if parsed is None:
        return None
    if is_a_day(parsed):
        return "day"
    if parsed.earliest and parsed.earliest == parsed.latest:
        return "month" if len(parsed.earliest) == 7 else "year"
    return parsed.granularity


__all__ = [
    "A_CORNERSTONE_IS_TITLED_BY_ITS_OWN_NAME", "cornerstone_title", "name_words_of",
    "names_only_the_milestone",
    "CORNERSTONE", "CORNERSTONES", "CORNERSTONES_ARE_THE_FIXED_DAYS",
    "CORNERSTONE_GRAIN", "FINEST_GRAIN_FOR_EVERYTHING_ELSE", "MILESTONES",
    "MILESTONE_OF_EVENT_KIND", "MILESTONE_OF_LABEL_WORD", "NOT_A_CORNERSTONE",
    "OUTSIDE_THE_SET", "OUTSIDE_THE_SET_GRAIN", "Person", "RELATIONSHIPS",
    "Relations", "SELF", "WHOSE", "cornerstone_nodes", "cornerstone_table",
    "is_a_day", "is_known_person", "label_lead", "milestone_of_kind", "milestone_of_label", "milestone_of_node",
    "node_status", "status_of",
]
