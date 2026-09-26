#!/usr/bin/env python3
"""One place, one landmark: a record that names a landmark he gave IS it.

The owner's ruling (2026-09-25):

    "The mention must not become a new place. It should be tied to a landmark
    I've given. This also gives you the fidelity I care about. If I say
    Arizona, I really just care that it's in Arizona. If I say Kristen or BJ's
    house, I'm giving you the higher fidelity that I care about."

WHERE IT WAS SEEN. His 15 September residences/schools/work document is fully
dated, with addresses. Overnight on 2026-09-25 the nightly sweep's
``landmark-record`` filings wrote twelve landmark entries, ten of them empty
copies of entries he had already given — "Thunderhead Street, San Diego"
beside "Thunderhead" (13353 Thunderhead St), "Mountain View High" beside
"Mountain View", "Mesa, Arizona" twice, "Fiegers' house" beside "Figers
House" — and every one became an undated node and a *"When did X happen?"*
card. The cause was the key: `landmarks_interaction.landmark_entry_key` is the
case-folded label, so "thunderhead" and "thunderhead street, san diego" were
two entries.

This module is the ONE definition of "is this record the same thing as an
entry he already gave?", per domain, and of what a place named in a story
resolves to. It is pure: no vault, no model, no clock. Its readers are the
landmark write seat (`timeline.save_landmark`), the draw seat
(`landmark_projection.load_landmark_sources` applying the merge records), the
fold's place anchors (`temporal_timeline`) and the one-time
``landmark-fold-duplicates`` verb.

Identity, by domain (:func:`same_entry`):

* **residences** — the same ``place_ref``; the same address (normalised:
  "N"/"North", "St"/"Street", unit and zip optional); the same street in the
  same city; or a house NAME (nickname, label, the street's own word) that
  matches his, tolerant of voice-to-text spelling (:func:`same_word`).
* **schools** — the same name core, generic words (High, School, Elementary)
  ignored, plus a compatible place; a record that is ONLY generic words ("high
  school") is the one school he gave at that level, when there is exactly one.
* **work** — the same employer.
* **family / children / losses / partnerships** — the same person.

A city or a state is never a residence of its own when his stays there exist
(:func:`place_level`), and a residence whose subject is someone else ("they")
is never filed as his.
"""

from __future__ import annotations

import re
import unicodedata

#: The rule, as the one sentence every seat cites.
ONE_PLACE_ONE_LANDMARK = (
    "a landmark record that names an entry the person already gave IS that "
    "entry: it merges into it and adds only what is new, and never mints a "
    "second one; a record with no date and nothing new is not written; a city "
    "or a state named as a residence is a mention of his stays there, never a "
    "residence of its own; a residence whose subject is someone else is never "
    "filed as his"
)

#: The ruling's second half, for the fold's place anchors.
A_PLACE_MENTION_TIES_TO_HIS_LANDMARKS = (
    "a place named in a story resolves to his existing stays at the level he "
    "named it: a state or a city is the union of his stays there, a house is "
    "that stay, 'left <house>' is that stay's end; the bounds come from the "
    "stays at month grain at most, and the mention never creates a place"
)

#: v360 follow-up (owner, 2026-09-25) (item 7), owner: *"Dad's house could be many
#: houses."* A residence named by a relation word's possessive — "dad's
#: house", "mom's place", "grandma's house", "my parents' home" — is a RELATIVE
#: place reference: that person's home at the time of the story, which moved
#: as they did. It is never a residence entry of its own (so never a "When
#: were you in dad's house?" card), never merged into one of his stays (it is
#: not BJ's House, though there was a time it was), and never resolved to a
#: stay by its words: the telling's other clues place the moment. A record of
#: it that carries his own dates is still his stay and is kept — a date he
#: gave is never dropped.
A_RELATION_WORDS_HOME_IS_A_RELATIVE_PLACE = (
    "a residence named by a relation word's possessive — dad's house, mom's "
    "place, grandma's house — is a relative reference to that person's home "
    "at the time of the story: never an entry of its own, never merged into "
    "one of his stays, never resolved to a stay by its words; an undated "
    "record of it is a mention, and a dated one keeps his dates"
)

#: The relation words a relative place is named by (the owner's own words for
#: his people; `identity_resolution.RELATIONSHIP_MENTION_WORDS` is the fuller
#: vocabulary, re-stated here because this module imports nothing).
RELATIVE_PLACE_WORDS = frozenset({
    "dad", "mom", "father", "mother", "mum", "mama", "papa", "parents", "folks",
    "grandma", "grandpa", "grandmother", "grandfather", "grandparents", "nana",
    "granny", "gramps", "brother", "sister", "aunt", "uncle", "cousin", "son",
    "daughter", "wife", "husband", "inlaws", "in", "law", "laws",
})
#: The dwelling words such a phrase ends on.
RELATIVE_PLACE_DWELLINGS = frozenset({"house", "home", "place", "apartment", "apt",
                                      "condo", "farm", "ranch", "trailer"})
_RELATIVE_GLUE = frozenset({"my", "our", "the", "and", "his", "her"})

#: Why a record was not written: :data:`A_RELATION_WORDS_HOME_IS_A_RELATIVE_PLACE`.
RELATIVE_PLACE_REFERENCE = "relative_place_reference"


def relative_place_words(text: object) -> tuple[str, ...]:
    """The relation words a phrase names a relative place by — ``("dad",)`` for
    "dad's house", ``("mom", "dad")`` for "mom and dad's place" — or ``()``."""
    tokens = words(text)
    if len(tokens) < 2 or tokens[-1] not in RELATIVE_PLACE_DWELLINGS:
        return ()
    body = tokens[:-1]
    who = [token for token in body if token not in _RELATIVE_GLUE]
    if not who or any(token not in RELATIVE_PLACE_WORDS for token in who):
        return ()
    if who in (["in"], ["law"], ["laws"]):
        return ()
    return tuple(who)


def is_relative_place(record: object) -> bool:
    """Does this residence record name a relative place
    (:data:`A_RELATION_WORDS_HOME_IS_A_RELATIVE_PLACE`) — by its label, its
    nickname or its address, with no street or city of its own?"""
    if not isinstance(record, dict):
        return False
    place = residence_place(record)
    if place["street"] or _text(record, "place_ref"):
        return False
    return any(relative_place_words(_text(record, key))
               for key in ("label", "nickname", "address"))


#: The decision words :func:`decide` returns, as a closed vocabulary.
FILE_NEW = "new"
MERGE_INTO = "merge"
NOT_WRITTEN = "not_written"
DECISIONS = (FILE_NEW, MERGE_INTO, NOT_WRITTEN)

#: Why a record was not written, as a closed vocabulary.
NOTHING_NEW = "nothing_new"
PLACE_LEVEL_MENTION = "place_level_mention"
NOT_HIS_RESIDENCE = "not_his_residence"
#: (and :data:`RELATIVE_PLACE_REFERENCE`, declared with its rule above)

#: The finding a write seat appends, in `lint_landmark_reply`'s shape.
JOINED_LINT = "landmarks.joined_existing_entry"
NOT_WRITTEN_LINT = "landmarks.not_written"

# --------------------------------------------------------------------------
# Words
# --------------------------------------------------------------------------

_APOSTROPHES = str.maketrans({"’": "'", "‘": "'", "`": "'"})

#: Street-type spellings, folded to one form each.
STREET_TYPES = {
    "st": "st", "street": "st", "str": "st", "strasse": "st",
    "ave": "ave", "av": "ave", "avenue": "ave",
    "dr": "dr", "drive": "dr",
    "ln": "ln", "lane": "ln",
    "rd": "rd", "road": "rd",
    "blvd": "blvd", "boulevard": "blvd",
    "ct": "ct", "court": "ct",
    "way": "way", "pl": "pl", "place": "pl",
    "cir": "cir", "circle": "cir",
    "pkwy": "pkwy", "parkway": "pkwy",
    "hwy": "hwy", "highway": "hwy",
    "ter": "ter", "terrace": "ter",
    "trl": "trl", "trail": "trl",
}

DIRECTIONS = {
    "n": "n", "north": "n", "s": "s", "south": "s",
    "e": "e", "east": "e", "w": "w", "west": "w",
    "ne": "ne", "northeast": "ne", "nw": "nw", "northwest": "nw",
    "se": "se", "southeast": "se", "sw": "sw", "southwest": "sw",
}

_UNIT_WORDS = frozenset({"apt", "apartment", "unit", "suite", "ste", "no"})

#: Words that describe a dwelling without naming it.
RESIDENCE_GENERIC = frozenset({
    "the", "a", "an", "our", "my", "his", "her", "their", "your", "we",
    "house", "home", "residence", "apartment", "apt", "condo", "place",
    "owned", "rented", "rental", "family", "lived", "living", "live", "at",
    "in", "on", "of", "to", "with", "from", "and", "old", "new", "first",
    "second", "third",
})

#: Words that describe a school without naming it.
SCHOOL_GENERIC = frozenset({
    "the", "a", "an", "high", "school", "hs", "elementary", "middle",
    "junior", "jr", "intermediate", "primary", "secondary", "grade", "grades",
    "es", "ms", "my", "at", "in", "of",
})

#: Words that describe an employer without naming it.
WORK_GENERIC = frozenset({
    "the", "a", "an", "inc", "llc", "ltd", "co", "corp", "corporation",
    "company", "at", "in", "of", "for", "job",
})

US_STATES = {
    "al": "alabama", "ak": "alaska", "az": "arizona", "ar": "arkansas",
    "ca": "california", "co": "colorado", "ct": "connecticut",
    "de": "delaware", "fl": "florida", "ga": "georgia", "hi": "hawaii",
    "id": "idaho", "il": "illinois", "in": "indiana", "ia": "iowa",
    "ks": "kansas", "ky": "kentucky", "la": "louisiana", "me": "maine",
    "md": "maryland", "ma": "massachusetts", "mi": "michigan",
    "mn": "minnesota", "ms": "mississippi", "mo": "missouri",
    "mt": "montana", "ne": "nebraska", "nv": "nevada",
    "nh": "new hampshire", "nj": "new jersey", "nm": "new mexico",
    "ny": "new york", "nc": "north carolina", "nd": "north dakota",
    "oh": "ohio", "ok": "oklahoma", "or": "oregon", "pa": "pennsylvania",
    "ri": "rhode island", "sc": "south carolina", "sd": "south dakota",
    "tn": "tennessee", "tx": "texas", "ut": "utah", "vt": "vermont",
    "va": "virginia", "wa": "washington", "wv": "west virginia",
    "wi": "wisconsin", "wy": "wyoming", "dc": "district of columbia",
}
_STATE_NAMES = frozenset(US_STATES.values())


def fold(text: object) -> str:
    """Case-folded, accent-free, possessive-free words joined by spaces."""
    raw = unicodedata.normalize("NFKD", str(text or "")).translate(_APOSTROPHES)
    raw = "".join(ch for ch in raw if not unicodedata.combining(ch)).casefold()
    raw = re.sub(r"(\w)\.(?=\w\.)", r"\1", raw)       # A.J.'s -> AJ's
    raw = re.sub(r"(\w)\.(?=\w)", r"\1", raw)
    raw = re.sub(r"'s\b", "", raw)                       # Horsepool's -> Horsepool
    raw = re.sub(r"s'(?=\W|$)", "s", raw)                # Fiegers' -> Fiegers
    raw = raw.replace("'", "")
    return " ".join(re.findall(r"[a-z0-9]+", raw))


def words(text: object) -> list[str]:
    return fold(text).split()


def canonical_region(text: object) -> str:
    """A US state from its name or postal code; otherwise the folded words."""
    folded = fold(text)
    folded = re.sub(r"\b\d{4,6}\b", "", folded).strip()
    folded = " ".join(token for token in folded.split()
                      if not re.fullmatch(r"[a-z]?\d+", token))
    if folded in US_STATES:
        return US_STATES[folded]
    return folded


# --------------------------------------------------------------------------
# Voice-to-text spelling: one tolerant word test
# --------------------------------------------------------------------------


def soundex(word: str) -> str:
    """American Soundex. Deterministic, and blind to vowels, which is the point:
    voice-to-text drops, adds and swaps vowels far more than consonants."""
    text = "".join(ch for ch in word.lower() if ch.isalpha())
    if not text:
        return ""
    codes = {**dict.fromkeys("bfpv", "1"), **dict.fromkeys("cgjkqsxz", "2"),
             **dict.fromkeys("dt", "3"), "l": "4", **dict.fromkeys("mn", "5"),
             "r": "6"}
    out = text[0].upper()
    last = codes.get(text[0], "")
    for ch in text[1:]:
        code = codes.get(ch, "")
        if code and code != last:
            out += code
        if ch not in "hw":
            last = code
    return (out + "000")[:4]


def edit_distance(left: str, right: str) -> int:
    """Optimal-string-alignment distance: insert, delete, substitute, swap."""
    a, b = left, right
    rows = [list(range(len(b) + 1))]
    for i in range(1, len(a) + 1):
        row = [i] + [0] * len(b)
        for j in range(1, len(b) + 1):
            cost = 0 if a[i - 1] == b[j - 1] else 1
            row[j] = min(rows[i - 1][j] + 1, row[j - 1] + 1, rows[i - 1][j - 1] + cost)
            if i > 1 and j > 1 and a[i - 1] == b[j - 2] and a[i - 2] == b[j - 1]:
                row[j] = min(row[j], rows[i - 2][j - 2] + 1)
        rows.append(row)
    return rows[-1][-1]


#: THE THRESHOLD, and why. Two words are one word misheard when they sound the
#: same (equal Soundex) AND are at most ONE edit apart — two for words of
#: eight letters or more — and both are at least four letters long. Measured
#: on the owner's own houses: "Fiegers"/"Figers" (1 edit, F262/F262) and
#: "Horsepools"/"Horsepool" (1 edit) join, while no two of his thirty-odd
#: distinct nicknames and street words join each other ("Fisches"/"Figers" is
#: 3 edits and F220/F262; "Harris"/"Hope", "Berna"/"Bothell", "Curtis"/
#: "Christamon" all differ in Soundex). Short words (three letters or fewer)
#: must match exactly: "Hope" vs "Hops" is a different word, not a mishearing.
FUZZY_MIN_LENGTH = 4


def same_word(left: object, right: object) -> bool:
    """One word, or one phrase word by word, misheard or not.

    A phrase ("san diego") compares token by token, the same number of
    tokens, so "Harbor00 City" is never "Harbor01 City". A token carrying a
    digit ("2nd", "180th", "Academy01") must match exactly: a number is
    heard or it is not.
    """
    ta, tb = fold(left).split(), fold(right).split()
    if not ta or not tb:
        return False
    if len(ta) != len(tb):
        return "".join(ta) == "".join(tb)
    return all(_same_token(x, y) for x, y in zip(ta, tb))


def _same_token(a: str, b: str) -> bool:
    if a == b:
        return True
    if (min(len(a), len(b)) < FUZZY_MIN_LENGTH
            or any(ch.isdigit() for ch in a + b)):
        return False
    limit = 2 if min(len(a), len(b)) >= 8 else 1
    return soundex(a) == soundex(b) and edit_distance(a, b) <= limit


def _covered(tokens: object, pool: object) -> bool:
    """Every token of ``tokens`` is a word of ``pool`` (misheard or not)."""
    pool = list(pool or ())
    items = list(tokens or ())
    return bool(items) and all(any(same_word(t, p) for p in pool) for t in items)


# --------------------------------------------------------------------------
# Residences: what a place record names, at which level
# --------------------------------------------------------------------------


def _text(entry: object, key: str) -> str:
    value = entry.get(key) if isinstance(entry, dict) else None
    return value.strip() if isinstance(value, str) else ""


def parse_street(line: object) -> dict | None:
    """``{"number", "core", "type"}`` for one street line, or None.

    A line is a street when it carries a house number or a street-type word;
    "the Fiegers' house" is neither, and is a house NAME instead.
    """
    tokens = words(line)
    if not tokens:
        return None
    number = ""
    core: list[str] = []
    street_type = ""
    for token in tokens:
        if token.isdigit() and not number and not core:
            number = token
            continue
        if token in _UNIT_WORDS or re.fullmatch(r"[a-z]{0,2}\d+[a-z]?", token) and core:
            # a unit ("DD-106", "B204") or the number of a Swiss address
            if token.isdigit() and not number:
                number = token
            continue
        if token in DIRECTIONS and not core:
            continue
        if token in STREET_TYPES:
            street_type = STREET_TYPES[token]
            continue
        if token.endswith("strasse") and len(token) > 7:
            core.append(token[:-7])
            street_type = "st"
            continue
        if token in RESIDENCE_GENERIC:
            continue
        core.append(token)
    if not core or not (number or street_type):
        return None
    return {"number": number, "core": tuple(core), "type": street_type}


def residence_place(entry: object) -> dict:
    """What one residence record says about WHERE, split into its levels.

    ``{"street", "city", "region", "names"}`` — ``street`` from
    :func:`parse_street` over the address's first line, ``city`` and
    ``region`` folded (a US state from its name or code), ``names`` the
    words that name the HOUSE (nickname, label, a non-street address) with
    generic words and the city/region's own words taken out.
    """
    address = _text(entry, "address")
    city_field = _text(entry, "city")
    parts = [part.strip() for part in address.split(",")] if address else []
    street = parse_street(parts[0]) if parts else None
    city = region = ""
    if city_field:
        city_parts = [part.strip() for part in city_field.split(",")]
        city = fold(city_parts[0])
        if len(city_parts) > 1:
            region = canonical_region(city_parts[-1])
    if len(parts) > 1:
        if not city:
            city = fold(re.sub(r"\d", "", parts[1]))
        if not region and len(parts) > 2:
            region = canonical_region(parts[-1])
    if city in US_STATES.values() or city in US_STATES:
        region, city = canonical_region(city), ""
    place_words = set(city.split()) | set(region.split())
    names: list[str] = []
    label = _text(entry, "label")
    label_head = label.split(",")[0] if label else ""
    label_tail = [part.strip() for part in label.split(",")[1:]] if label else []
    for tail in label_tail:
        folded = canonical_region(tail)
        if folded in _STATE_NAMES and not region:
            region = folded
        place_words |= set(fold(tail).split()) | set(folded.split())
    sources = [_text(entry, "nickname"), label_head]
    if address and street is None:
        sources.append(parts[0])
    for source in sources:
        head = parse_street(source)
        tokens = list(head["core"]) if head else words(source)
        for token in tokens:
            if (token in RESIDENCE_GENERIC or token in place_words
                    or token in STREET_TYPES or token in DIRECTIONS
                    or token.isdigit()):
                continue
            if token not in names:
                names.append(token)
    return {"street": street, "city": city, "region": region,
            "names": tuple(names)}


def _cities_compatible(left: str, right: str) -> bool:
    return not left or not right or left == right or same_word(left, right)


def same_residence(record: object, entry: object) -> str | None:
    """Why two residence records are ONE place, or None. See the module doc."""
    if not isinstance(record, dict) or not isinstance(entry, dict):
        return None
    ref_a, ref_b = _text(record, "place_ref"), _text(entry, "place_ref")
    if ref_a and ref_b:
        return "same_place_ref" if ref_a == ref_b else None
    a, b = residence_place(record), residence_place(entry)
    if not _cities_compatible(a["city"], b["city"]):
        return None
    if a["region"] and b["region"] and a["region"] != b["region"]:
        return None
    sa, sb = a["street"], b["street"]
    if sa and sb and len(sa["core"]) == len(sb["core"]) and all(
            same_word(x, y) for x, y in zip(sa["core"], sb["core"])):
        if sa["number"] and sb["number"]:
            return "same_address" if sa["number"] == sb["number"] else None
        if a["city"] and b["city"]:
            return "same_street_and_city"
    own = list(a["names"]) or (list(sa["core"]) if sa else [])
    theirs = list(b["names"]) + (list(sb["core"]) if sb else [])
    if own and _covered(own, theirs):
        return "same_house_name"
    return None


def place_level(record: object) -> tuple[str, str] | None:
    """``("city", "mesa")`` / ``("region", "arizona")`` when a residence record
    names only a city or a state — no house, no street — else None."""
    if not isinstance(record, dict):
        return None
    place = residence_place(record)
    if place["street"] or place["names"] or _text(record, "place_ref"):
        return None
    if place["city"]:
        return ("city", place["city"])
    if place["region"]:
        return ("region", place["region"])
    return None


def stays_at(level: str, value: str, residences: object) -> list[dict]:
    """His residence entries in that city or that state/country."""
    found = []
    for entry in residences or ():
        if not isinstance(entry, dict):
            continue
        place = residence_place(entry)
        if level == "city" and place["city"] and same_word(place["city"], value):
            found.append(entry)
        elif level == "region" and place["region"] == value:
            found.append(entry)
    return found


#: Whose residence a record is. Absent, or one of these words anywhere in the
#: subject, is the owner; anyone else ("they", "Mom") is not his residence.
OWNER_SUBJECT_WORDS = frozenset({
    "i", "me", "my", "myself", "self", "you", "we", "us", "our", "subject",
    "narrator", "author", "owner",
})


def is_his(record: object, owner_names: object = ()) -> bool:
    subject = _text(record, "subject")
    if not subject:
        return True
    tokens = set(words(subject))
    if tokens & OWNER_SUBJECT_WORDS:
        return True
    for name in owner_names or ():
        if set(words(name)) & tokens:
            return True
    return False


# --------------------------------------------------------------------------
# Schools, work, people
# --------------------------------------------------------------------------

_HIGH_GRADES = re.compile(
    r"\b(9th|10th|11th|12th|ninth|tenth|eleventh|twelfth|freshman|sophomore|"
    r"junior year|senior year|junior|senior)\b")
_MIDDLE = re.compile(r"\b(middle|junior high|jr high|7th|8th|seventh|eighth)\b")
_ELEMENTARY = re.compile(
    r"\b(elementary|kindergarten|pk|1st|2nd|3rd|4th|5th|6th|first grade)\b")


def school_level(entry: object) -> str:
    text = " ".join(fold(_text(entry, key)) for key in ("name", "label", "grades"))
    if _MIDDLE.search(text):
        return "middle"
    if re.search(r"\bhigh\b", text) or _HIGH_GRADES.search(text):
        return "high"
    if _ELEMENTARY.search(text):
        return "elementary"
    return ""


def school_core(entry: object) -> tuple[str, ...]:
    name = _text(entry, "name") or _text(entry, "label")
    return tuple(t for t in words(re.sub(r"\(.*?\)", " ", name) or name)
                 if t not in SCHOOL_GENERIC) or tuple(
        t for t in words(name) if t not in SCHOOL_GENERIC)


def same_school(record: object, entry: object) -> str | None:
    a, b = school_core(record), school_core(entry)
    if not a or not b or len(a) != len(b):
        return None
    if not all(same_word(x, y) for x, y in zip(a, b)):
        return None
    pa, pb = fold(_text(record, "place")), fold(_text(entry, "place"))
    if pa and pb and not (pa == pb or set(pa.split()) & set(pb.split())):
        return None
    return "same_school_name"


def employer_core(entry: object) -> tuple[str, ...]:
    name = _text(entry, "label") or _text(entry, "what")
    return tuple(t for t in words(name) if t not in WORK_GENERIC)


def same_employer(record: object, entry: object) -> str | None:
    a, b = employer_core(record), employer_core(entry)
    if a and b and len(a) == len(b) and all(same_word(x, y) for x, y in zip(a, b)):
        return "same_employer"
    return None


def person_names(entry: object) -> list[tuple[str, ...]]:
    names = []
    for key in ("who", "name", "label"):
        text = re.sub(r"\(.*?\)", " ", _text(entry, key))
        tokens = tuple(words(text))
        if tokens and tokens not in names:
            names.append(tokens)
    return names


def same_person(record: object, entry: object, siblings: object = ()) -> str | None:
    """The same roster person: a full name, or a lone first name that is the
    first name of exactly one of the domain's entries."""
    own, theirs = person_names(record), person_names(entry)
    for a in own:
        for b in theirs:
            if a == b:
                return "same_person"
    firsts = {}
    for other in siblings or ():
        for tokens in person_names(other):
            if len(tokens) > 1:
                firsts.setdefault(tokens[0], set()).add(tokens)
    for a in own:
        if len(a) != 1:
            continue
        full = firsts.get(a[0]) or set()
        if len(full) == 1 and any(b in full for b in theirs):
            return "same_person_first_name"
    return None


PERSON_DOMAINS = frozenset({"family", "children", "losses", "partnerships"})


def same_entry(domain: object, record: object, entry: object, *,
               siblings: object = ()) -> str | None:
    """Why ``record`` is the SAME thing as ``entry`` in ``domain``, or None."""
    name = str(domain or "")
    if name == "residences":
        return same_residence(record, entry)
    if name == "schools":
        return same_school(record, entry)
    if name == "work":
        return same_employer(record, entry)
    if name in PERSON_DOMAINS:
        return same_person(record, entry, siblings)
    return None


# --------------------------------------------------------------------------
# What a matched record adds
# --------------------------------------------------------------------------

#: Keys that name or describe the entry and are never "something new": the
#: entry already has its own name, and a second spelling of it is not news.
DESCRIPTOR_KEYS = frozenset({
    "domain", "label", "name", "nickname", "who", "what", "subject", "link",
    "place_ref", "birth_order",
})

#: Keys whose content is a date.
DATE_KEYS = frozenset({"date", "span", "year", "month", "day", "birth",
                       "start", "end", "date_alternates", "span_alternates"})


def _entry_words(entry: object) -> list[str]:
    pool: list[str] = []
    for value in (entry or {}).values() if isinstance(entry, dict) else ():
        if isinstance(value, str):
            pool.extend(words(value))
            street = parse_street(value.split(",")[0])
            if street:
                pool.extend(street["core"])
    return pool


def already_said(value: object, entry: object) -> bool:
    """Is this value's every meaningful word already in the entry?"""
    if not isinstance(value, str):
        return False
    tokens = [t for t in words(value)
              if t not in RESIDENCE_GENERIC and t not in STREET_TYPES
              and t not in DIRECTIONS]
    if not tokens:
        return True
    pool = _entry_words(entry)
    for code, state in US_STATES.items():
        if state in " ".join(pool):
            pool.extend(state.split())
    return _covered(tokens, pool)


def carries_a_date(record: object) -> bool:
    if not isinstance(record, dict):
        return False
    for key in DATE_KEYS:
        value = record.get(key)
        if isinstance(value, dict) and value:
            return True
        if isinstance(value, (str, int)) and str(value).strip():
            return True
    return False


def new_content(record: object, entry: object) -> dict:
    """The fields ``record`` adds to ``entry``: absent there, not a descriptor,
    not already said in other words. Dates are judged by :func:`carries_a_date`."""
    if not isinstance(record, dict):
        return {}
    found = {}
    for key, value in record.items():
        if key in DESCRIPTOR_KEYS or key in DATE_KEYS:
            continue
        if isinstance(entry, dict) and key in entry:
            continue
        if value in (None, "", False, [], {}):
            continue
        if already_said(value, entry):
            continue
        found[key] = value
    return found


# --------------------------------------------------------------------------
# The decision a write seat takes
# --------------------------------------------------------------------------


def entry_identity(entry: object) -> str:
    """A readable name for an entry, for findings."""
    for key in ("label", "name", "who", "what", "nickname", "city"):
        text = _text(entry, key)
        if text:
            return text
    return ""


def _school_by_level(record: object, entries: list[dict]) -> list[dict]:
    if school_core(record):
        return []
    level = school_level(record)
    if not level:
        return []
    found = [entry for entry in entries
             if school_core(entry) and school_level(entry) == level]
    dated = [entry for entry in found if entry.get("span") or entry.get("date")]
    return dated or found


def matches(domain: object, record: object, entries: object) -> list[tuple[dict, str]]:
    """Every entry ``record`` is the same thing as, with the reason."""
    rows = [entry for entry in entries or () if isinstance(entry, dict)]
    found = []
    for entry in rows:
        if entry is record:
            continue
        reason = same_entry(domain, record, entry, siblings=rows)
        if reason:
            found.append((entry, reason))
    if not found and str(domain) == "schools":
        found = [(entry, "the_one_school_at_that_level")
                 for entry in _school_by_level(record, rows)]
    return found


def decide(domain: object, record: object, entries: object, *,
           residences: object = (), owner_names: object = (),
           key_of=None) -> dict:
    """What a write seat does with ``record``. Pure.

    ``{"decision", "reason", "target", "new"}``:

    * ``new`` — nothing he gave is this; file it as before.
    * ``merge`` — it is ``target``; file it as a telling OF ``target`` (the
      caller records the merge) because it carries a date or something new.
    * ``not_written`` — it is ``target`` and adds nothing, or it is only a
      city/state he has stays in, or it is someone else's residence.

    ``key_of(entry)`` is the entry-key function (defaults to the label), used
    so several stays of ONE identity (two stays at Williams) are one target.
    """
    name = str(domain or "")
    rows = [entry for entry in entries or () if isinstance(entry, dict)]
    new = {"decision": FILE_NEW, "reason": "", "target": None, "new": {}}
    if not isinstance(record, dict) or record.get("none") or record.get("skipped"):
        return new
    dated = carries_a_date(record)
    if name == "residences":
        if is_relative_place(record) and not dated:
            return {"decision": NOT_WRITTEN, "reason": RELATIVE_PLACE_REFERENCE,
                    "target": None, "new": {}}
        if not is_his(record, owner_names):
            return {"decision": NOT_WRITTEN, "reason": NOT_HIS_RESIDENCE,
                    "target": None, "new": {}}
        level = place_level(record)
        if level is not None:
            stays = stays_at(level[0], level[1], residences or rows)
            if stays and not dated:
                return {"decision": NOT_WRITTEN, "reason": PLACE_LEVEL_MENTION,
                        "target": None, "new": {}, "level": level,
                        "stays": stays}
            # A DATED city is his word about when: it is one of his stays
            # there when exactly one fits, and otherwise a stay of its own.
            fits = [row for row in stays if _fits_stay(row, record)]
            if len(fits) == 1:
                return {"decision": MERGE_INTO, "reason": PLACE_LEVEL_MENTION,
                        "target": fits[0], "new": new_content(record, fits[0]),
                        "pin": True}
            return new
    keyer = key_of or (lambda entry: fold(entry_identity(entry)))
    own_key = keyer(record)
    same_key = [entry for entry in rows if keyer(entry) == own_key]
    if same_key and (dated or len(same_key) == 1):
        # The ladder's own incremental fill (the city today, the address next
        # week, a span after that) and a second dated stay at one place are
        # the entry key's business, exactly as before.
        return new
    if same_key:
        found = [(entry, "same_entry_key") for entry in same_key]
    else:
        found = matches(name, record, rows)
    if not found:
        return new
    keys = {keyer(entry) for entry, _ in found}
    if len(keys) != 1:
        return {**new, "reason": "ambiguous_match",
                "candidates": [entry_identity(entry) for entry, _ in found]}
    # The DATED stay of the identity first, then filing order.
    target, reason = sorted(
        found, key=lambda pair: (not carries_a_date(pair[0]),
                                 rows.index(pair[0])))[0]
    added = new_content(record, target)
    if not added and not dated:
        return {"decision": NOT_WRITTEN, "reason": NOTHING_NEW,
                "target": target, "new": {}, "match": reason}
    # An undated telling joins the dated stay; a dated one joins the stay
    # its dates fall in, and is a stay of its own when they fall in none.
    fits = [entry for entry, _ in found if _fits_stay(entry, record)]
    if dated and len(fits) == 1:
        target = fits[0]
    return {"decision": MERGE_INTO, "reason": reason, "target": target,
            "new": added, "pin": (not dated) or len(fits) == 1}


def _fits_stay(entry: object, record: object) -> bool:
    """Does a dated record's stretch fall in this stay (the ladder's own
    `landmarks_interaction.same_landmark_stay`, with both sides dated)?"""
    import landmarks_interaction as li  # noqa: PLC0415

    if not (li.entry_stay_interval(entry) and li.entry_stay_interval(record)):
        return False
    return li.same_landmark_stay(entry, record, {"collection": "sequence"})


def finding_for(domain: object, record: object, decision: dict) -> dict:
    """The one finding a write seat appends for a non-``new`` decision."""
    target = decision.get("target")
    what = entry_identity(record) or str(domain)
    if decision.get("decision") == MERGE_INTO:
        return {"lint": JOINED_LINT, "domain": str(domain),
                "detail": (f"{domain}: {what!r} is {entry_identity(target)!r} "
                           f"({decision.get('reason')}); filed as a telling of "
                           f"it, adding {sorted(decision.get('new') or ()) or 'its date'}"),
                "rule": ONE_PLACE_ONE_LANDMARK}
    reason = decision.get("reason")
    if reason == PLACE_LEVEL_MENTION:
        level = decision.get("level") or ("", "")
        stays = [entry_identity(entry) for entry in decision.get("stays") or ()]
        detail = (f"{domain}: {what!r} names a {level[0]} ({level[1]}) he has "
                  f"{len(stays)} stay(s) in ({', '.join(stays)}); it is a mention "
                  f"of those stays, not a residence")
    elif reason == RELATIVE_PLACE_REFERENCE:
        detail = (f"{domain}: {what!r} names a relative's home at the time of "
                  f"the story, not a residence of his own; a mention, not an entry")
        return {"lint": NOT_WRITTEN_LINT, "domain": str(domain), "reason": reason,
                "detail": detail, "rule": A_RELATION_WORDS_HOME_IS_A_RELATIVE_PLACE}
    elif reason == NOT_HIS_RESIDENCE:
        detail = (f"{domain}: {what!r} is {record.get('subject')!r}'s, not his; "
                  f"not filed as his residence")
    else:
        detail = (f"{domain}: {what!r} is {entry_identity(target)!r} "
                  f"({decision.get('match')}) and adds nothing; not written")
    return {"lint": NOT_WRITTEN_LINT, "domain": str(domain), "reason": reason,
            "detail": detail, "rule": ONE_PLACE_ONE_LANDMARK}


# --------------------------------------------------------------------------
# Place anchors in a telling (the fold's half)
# --------------------------------------------------------------------------

#: The phrases that make a place an ANCHOR of the telling, deterministic and
#: narrow on purpose: "lived in/at X", "while living in X", "when we were in
#: X", "left X", "(anchor: … X)". A bare "in X" inside prose is read only when
#: the whole anchor handle is the place itself ("in Yucaipa").
_LEFT_RE = re.compile(
    r"^\s*(?:after\s+|when\s+)?(?:i|we|he|she)?\s*"
    r"(?:left|leaving|moved out of|moving out of)\s+(?P<place>[^,;.()]+)", re.I)
#: A place as he names it: capitalised words ("San Diego", "BJ's"), with an
#: optional leading "the" and a trailing dwelling word ("the Fiegers' house").
_PLACE = (r"(?:the\s+)?[A-Z][\w'\u2019.-]*(?:\s+(?:[A-Z][\w'\u2019.-]*|of))*"
          r"(?:\s+(?:house|residence|home|place|street|st|avenue|ave))?")
_LIVED_RE = re.compile(
    r"(?i:(?:when|while|back when)\s+(?:i|we|the family|the author|author|narrator|he|she|they)?\s*"
    r"(?:lived|was living|were living|living|was|were|stayed)\s+(?:in|at)\s+"
    r"|(?:while|when)\s+living\s+(?:in|at)\s+"
    r"|^\s*(?:lived|living)\s+(?:in|at)\s+"
    r"|^\s*in\s+)"
    r"(?P<place>" + _PLACE + r")"
)


def anchor_place_phrase(text: object) -> tuple[str, str] | None:
    """``("end", "Kristen")`` for "left Kristen"; ``("during", "Arizona")``
    for "when I lived in Arizona" / "in Yucaipa"; None otherwise."""
    raw = str(text or "").strip()
    if not raw:
        return None
    left = _LEFT_RE.match(raw)
    if left:
        return ("end", left.group("place").strip(" .,;"))
    lived = _LIVED_RE.search(raw)
    if lived:
        return ("during", lived.group("place").strip(" .,;"))
    return None


def resolve_place(text: object, stays: object) -> dict | None:
    """What a named place is among his stays, at the level he named it.

    ``stays`` is ``[{"id", "record", ...}]`` — one row per residence stay he
    gave. Returns ``{"level", "value", "ids"}``: ``house`` (the stays that one
    house was), ``city`` or ``region`` (every stay there). None when the words
    name none of his places — a mention never creates one.
    """
    phrase = str(text or "").strip()
    if not phrase:
        return None
    if relative_place_words(phrase):
        # :data:`A_RELATION_WORDS_HOME_IS_A_RELATIVE_PLACE`: "dad's house" is
        # whichever house dad had then — the telling's other clues place it.
        return None
    rows = [row for row in stays or () if isinstance(row, dict)]
    probe = {"label": phrase}
    level = place_level(probe)
    if level is not None:
        ids = [row["id"] for row in rows
               if stays_at(level[0], level[1], [row.get("record")])]
        if ids:
            return {"level": level[0], "value": level[1], "ids": sorted(set(ids))}
    # A state or a country named alone ("Arizona", "Switzerland").
    region = canonical_region(phrase)
    ids = [row["id"] for row in rows
           if residence_place(row.get("record"))["region"] == region]
    if ids:
        return {"level": "region", "value": region, "ids": sorted(set(ids))}
    ids = [row["id"] for row in rows
           if residence_place(row.get("record"))["city"]
           and same_word(residence_place(row.get("record"))["city"], fold(phrase))]
    if ids:
        return {"level": "city", "value": fold(phrase), "ids": sorted(set(ids))}
    ids = [row["id"] for row in rows if same_residence(probe, row.get("record"))]
    if ids:
        return {"level": "house", "value": phrase, "ids": sorted(set(ids))}
    return None
