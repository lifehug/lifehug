#!/usr/bin/env python3
"""A remembered story never opens at the birth (v410, owner 2026-10-10).

The owner, reading his own Timeline: *"A kid's story shouldn't span from
birth. You should look for better context."* Born 1981-07-11, he had some
twenty episodes whose interval opened exactly on his birth day — "Friday
McDonald's trips as a kid" 1981-07-11→1990-06, "Constantly moving as a kid"
1981-07-11→1997-06, "Drew Manning's older brother seemed scary"
1981-07-11→1988-06 — because the telling said *as a kid* / *growing up* /
*childhood* and nothing stated a date, so a resolver or anchor-range reading
opened before the birth and `temporal_timeline.ORIGIN_FLOOR_RULE` slid it to
the birth itself. The floor was right that nothing happens before the birth;
it was wrong that a MEMORY can start there. Nobody remembers being a newborn.

Two rules, both fold-time readings (pure, deterministic, no model, no vault
I/O — the fold hands everything in):

* :data:`A_REMEMBERED_STORY_OPENS_AFTER_INFANCY` — a first-person telling by
  the owner about his own experience, dated only by a life-stage phrase, opens
  no earlier than his earliest-memory age (:data:`CONFIG_PATH`'s
  ``earliest_memory_age``, a 4th birthday by default). *As a kid/child/little*
  and *childhood* are ages 4–12, *growing up* 4–18, *as a teenager* 13–19. A
  THIRD-PERSON fact (*"Dad was in school during my early childhood"*) is not a
  memory and keeps the existing bands; the ``childhood`` AGE FRAME (0–13, the
  spine and eras) is not this rule's and is unchanged. A stated date, a stated
  age or a stated grade always wins: this only replaces an inferred opening.
* :data:`BETTER_CONTEXT_BEATS_THE_BAND` — before the band is used the telling
  is searched for better context and narrowed to it: a stated school grade, a
  named stay (the v360 place anchors, or a home named in so many words), a
  name the vault ties to exactly one stay (a neighbour is at the home where
  they were neighbours), and the lifetime of a person in the memory (a sister
  born after him, a grandmother who died). Only when nothing narrows does the
  band apply, and the finding lists every context tried.

The moved bound is recorded in the record's provenance
(:data:`REMEMBERED_STORY_FLOOR_RULE`, :data:`BETTER_CONTEXT_RULE`) exactly as
the origin floor records its own, so the number stays explainable.
"""

from __future__ import annotations

import json
import re
from dataclasses import replace
from pathlib import Path

import chronology as chrono
import cross_dating as cd

#: THE RULE (1).
A_REMEMBERED_STORY_OPENS_AFTER_INFANCY = (
    "a first-person telling by the owner about his own experience, dated only "
    "by a life-stage phrase, never opens at his birth: it opens no earlier than "
    "his earliest-memory age (a 4th birthday by default) — as a kid, child or "
    "little and childhood at 4 to 12, growing up at 4 to 18, as a teenager at "
    "13 to 19; a third-person fact keeps the existing bands and a stated date "
    "always wins"
)

#: THE RULE (2).
BETTER_CONTEXT_BEATS_THE_BAND = (
    "before a life-stage band dates a story, the telling is searched for better "
    "context and narrowed to it — a stated grade, a named stay, a name the vault "
    "ties to exactly one stay (a neighbour is at the home where they were "
    "neighbours), the lifetime of a person in the memory; only when nothing "
    "narrows does the band apply, and the finding names every context tried"
)

#: The provenance rules a moved bound records.
REMEMBERED_STORY_FLOOR_RULE = "remembered_story_floor"
BETTER_CONTEXT_RULE = "better_context"

#: The diagnostic finding, one per story the rule read.
FINDING = "remembered_story_placed"

#: v415: the finding for a candidate the rule looked at and left alone, with
#: its reason (:data:`DECLINE_REASONS`), so a vault can say why a story kept
#: its birth-day opening.
DECLINED_FINDING = "remembered_story_declined"
DECLINE_REASONS = ("stated_basis", "states_its_own_date", "third_person_fact")

#: v415 (owner's republish of 2026-10-10): the stage of a remembered moment
#: that names no life stage at all but whose inferred opening is at or before
#: his birth — "Birthday Sizzler tradition with Grandma" 1981-07-11→2000-08.
#: It reads the earliest-memory age as its band floor.
REMEMBERED_STAGE = "remembered"

#: v415. The locator contexts — the telling's own words saying WHEN or WHERE.
#: A locator REPLACES an inferred band (the resolver's "1981-07-11→1988-06"
#: for a story told "in San Diego" is simply wrong); the person-lifetime
#: context only bounds.
LOCATOR_CONTEXTS = ("stated_grade", "named_stay", "name_tied_to_one_stay")

#: A sentence that says the thing did NOT happen in that grade ("in 4th or
#: 5th grade we just never went out") is not where the story happened.
_NEGATION_RE = re.compile(r"\b(?:never|no\s+longer|stopped|didn['\u2019]?t|did\s+not|"
                          r"wasn['\u2019]?t|weren['\u2019]?t|not\s+anymore)\b", re.IGNORECASE)

#: A citation a system reader wrote from the owner's LIFE SHAPE, not from the
#: story (``spine: (Ridgeview): June 1990–June 1991``). It names the stretch
#: the reader guessed, never context the telling gave.
_SPINE_CITATION_RE = re.compile(r"^\s*spine\b[\w.:-]*:\s", re.IGNORECASE)

#: "narrator (as a kid)", "Narrator's family": the owner, said with a note.
_PARENTHETICAL_RE = re.compile(r"\(([^)]*)\)")
_OWNER_HANDLE_TAIL_RE = re.compile(r"['\u2019]s\s+(?:family|household)$", re.IGNORECASE)

#: The declarative table: the earliest-memory age and the bands.
CONFIG_PATH = Path(__file__).with_name("remembered_story.json")

#: The profile/config key a vault overrides the earliest-memory age with.
PROFILE_KEY = "earliest_memory_age"

#: The contexts :data:`BETTER_CONTEXT_BEATS_THE_BAND` tries, in order.
CONTEXTS = ("stated_grade", "named_stay", "name_tied_to_one_stay", "person_lifetime")

#: The life-stage phrases, by the band they read. ORDER MATTERS: the first
#: stage whose phrase is in the telling is the stage (a teenager is never a
#: kid). `general_listener.LIFE_STAGE_RES` is the prescreen that NOTICES these
#: words; this table says which ages they mean, which the listener never does.
STAGE_PATTERNS: tuple[tuple[str, tuple[re.Pattern, ...]], ...] = (
    ("teens", (
        re.compile(r"\bas\s+(?:a\s+)?teen(?:ager)?s?\b", re.IGNORECASE),
        re.compile(r"\bwhen\s+(?:I|we)\s+(?:was|were)\s+(?:a\s+)?teen(?:ager)?s?\b",
                   re.IGNORECASE),
        re.compile(r"\bin\s+(?:my|our)\s+(?:early\s+|late\s+)?teens\b", re.IGNORECASE),
        re.compile(r"\bteen(?:age)?\s+years\b", re.IGNORECASE),
    )),
    ("growing_up", (
        re.compile(r"\bgrowing\s+up\b", re.IGNORECASE),
        re.compile(r"\bgrew\s+up\b", re.IGNORECASE),
    )),
    ("kid", (
        re.compile(r"\bas\s+(?:a\s+)?(?:little\s+|small\s+)?(?:kid|child|boy|girl)s?\b",
                   re.IGNORECASE),
        re.compile(r"\bas\s+(?:little\s+)?children\b", re.IGNORECASE),
        # v415: "when I was really young" (the owner's own words about a
        # neighbour) — an intensifier before little/young/small.
        re.compile(r"\bwhen\s+(?:I|we)\s+(?:was|were)\s+(?:(?:really|very|so|pretty|quite)\s+)?"
                   r"(?:little|small|young|"
                   r"a\s+(?:little\s+|young\s+)?(?:kid|child|boy|girl)|kids|children)\b",
                   re.IGNORECASE),
        re.compile(r"\blittle\s+kids?\b", re.IGNORECASE),
    )),
    ("childhood", (
        re.compile(r"\bchildhood\b", re.IGNORECASE),
    )),
)

#: A life stage used as a POSSESSIVE time reference — "my early childhood",
#: "our teens". With no first-person experiencer in the sentence it is the
#: time of somebody else's fact, not a memory.
_POSSESSIVE_PERIOD_RE = re.compile(
    r"\b(?:my|our)\s+(?:early\s+|late\s+)?(?:childhood|teens|teenage\s+years|youth)\b",
    re.IGNORECASE)

#: Somebody else as the sentence's subject, stating a fact about themselves.
_THIRD_PERSON_FACT_RE = re.compile(
    r"^\W*(?:(?i:my|our)\s+(?i:dad|mom|father|mother|parents|brother|sister|"
    r"grandma|grandpa|grandmother|grandfather|uncle|aunt|stepdad|stepmom)"
    r"|(?i:he|she|they)|(?!I\b)[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)"
    r"(?:['’]s)?\s+(?i:was|were|had|worked|lived|went|did|used|ran|owned|served|studied)\b")

#: The owner as the one who lived it: I, me, we, us. ``my``/``our`` alone are
#: a time reference ("during my childhood"), never an experiencer.
_EXPERIENCER_RE = re.compile(r"\bI\b|\bI['’](?:m|d|ve|ll)\b|"
                             r"\b(?i:me|myself|we|us|we['’](?:re|d|ve))\b")

#: A telling that says when, in its own words, is dated by those words.
_DECADE_RE = re.compile(r"\b(?:1[89]\d{2}|20\d{2})s\b")

#: "at Harbor Lane", "in Port Ellis": a home named in so many words.
_NAMED_PLACE_RE = re.compile(
    r"\b(?:at|in|on|near|by)\s+(?:the\s+)?(?P<place>[A-Z][\w'’.-]*"
    r"(?:\s+(?:(?!I\b)[A-Z][\w'’.-]*|of))*)")

#: A proper name of two or more capitalized words ("Tobin Vance", "Juniper
#: Court"). One capitalized word is too often a sentence's first word.
_PROPER_NAME_RE = re.compile(r"\b[A-Z][a-z'’]+(?:\s+[A-Z][a-z'’]+)+\b")
_NAME_LEADERS = frozenset({
    "when", "as", "every", "my", "the", "our", "neighbor", "neighbors", "neighbour",
    "neighbours", "sister", "brother", "grandma", "grandpa", "mom", "dad", "in",
    "at", "on", "after", "before", "while", "we", "i", "back", "growing", "then",
    "and", "but", "so", "one", "that", "this", "there", "friday", "saturday",
    "sunday", "monday", "tuesday", "wednesday", "thursday", "story", "spine",
})

#: A memory that says the person died is not bounded by their death.
_DEATH_WORDS_RE = re.compile(r"\b(?:died|dies|death|passed|funeral|buried|grave)\b",
                             re.IGNORECASE)

#: The quote prefix the resolver writes ("story: …", "spine: …", "p3: …").
_CITATION_PREFIX_RE = re.compile(r"^[\w.:-]+:\s+")
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")


class RememberedStoryConfigError(ValueError):
    """The declarative table is malformed."""


def _validated(raw: object) -> dict:
    if not isinstance(raw, dict):
        raise RememberedStoryConfigError("remembered_story config must be a mapping")
    age = raw.get("earliest_memory_age")
    if not isinstance(age, int) or isinstance(age, bool) or not 0 <= age <= 12:
        raise RememberedStoryConfigError("earliest_memory_age must be a whole age 0..12")
    bands = raw.get("bands")
    if not isinstance(bands, dict):
        raise RememberedStoryConfigError("bands must be a mapping")
    out: dict[str, tuple[int, int]] = {}
    for stage, _patterns in STAGE_PATTERNS:
        pair = bands.get(stage)
        if not isinstance(pair, (list, tuple)) or len(pair) != 2:
            raise RememberedStoryConfigError(f"band {stage!r} must be [low, high]")
        low, high = pair
        low = age if low is None else low
        if not all(isinstance(v, int) and not isinstance(v, bool) for v in (low, high)):
            raise RememberedStoryConfigError(f"band {stage!r} ages must be whole years")
        # The earliest-memory age is the floor of every band.
        low = max(low, age)
        if not low <= high <= 120:
            raise RememberedStoryConfigError(f"band {stage!r} must have low <= high")
        out[stage] = (low, high)
    return {"earliest_memory_age": age, "bands": out}


def load_config(overrides: object = None) -> dict:
    """The effective, validated table: :data:`CONFIG_PATH` under ``overrides``.

    ``overrides`` is ``{"earliest_memory_age": n}`` (what a vault's profile
    says, :func:`profile_overrides`) and may carry ``bands``. A malformed
    override raises — a silently ignored number is a number nobody can trust.
    """
    try:
        raw = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:  # pragma: no cover - a shipped file
        raise RememberedStoryConfigError(f"cannot read {CONFIG_PATH.name}: {exc}") from exc
    merged = {"earliest_memory_age": raw.get("earliest_memory_age"),
              "bands": dict(raw.get("bands") or {})}
    if isinstance(overrides, dict):
        if overrides.get("earliest_memory_age") is not None:
            merged["earliest_memory_age"] = overrides["earliest_memory_age"]
        if isinstance(overrides.get("bands"), dict):
            merged["bands"].update(overrides["bands"])
    return _validated(merged)


def profile_overrides(profile: object) -> dict | None:
    """``{"earliest_memory_age": n}`` from a vault's merged profile/config, or
    ``None`` when it says nothing. A value that is not a whole age is refused
    loudly by :func:`load_config` when the fold reads it."""
    row = profile if isinstance(profile, dict) else {}
    value = row.get(PROFILE_KEY)
    if value is None or str(value).strip() == "":
        return None
    text = str(value).strip()
    return {"earliest_memory_age": int(text) if text.isdigit() else text}


# --------------------------------------------------------------------------
# Reading the telling
# --------------------------------------------------------------------------

def _texts_of(claim: dict) -> list[str]:
    """The claim's event mention and evidence quotes. A system reader's quote
    is ``"<doc>: <words> | <doc>: <words>"`` (the resolver's citations); its
    doc prefixes are dropped so only the cited words are read."""
    system = str(claim.get("source_kind") or "") == "system_derived"
    out = []
    mention = " ".join(str(claim.get("event_mention") or "").split())
    if mention:
        out.append(mention)
    for row in claim.get("evidence") or ():
        if not isinstance(row, dict):
            continue
        quote = str(row.get("quote") or "")
        for part in (quote.split(" | ") if system else [quote]):
            part = " ".join(part.split())
            if system:
                if _SPINE_CITATION_RE.match(part):
                    continue
                part = _CITATION_PREFIX_RE.sub("", part, count=1)
            if part:
                out.append(part)
    return out


def group_texts(group: dict) -> tuple[list[str], list[str]]:
    """``(every text, the owner's own texts)`` of a group's claims. The owner's
    own are the claims no system reader wrote (a resolver quotes spine lines
    with years in them; those never count as him stating a date)."""
    every: list[str] = []
    own: list[str] = []
    for claim in group.get("claims") or ():
        if not isinstance(claim, dict):
            continue
        texts = _texts_of(claim)
        every.extend(texts)
        if str(claim.get("source_kind") or "") != "system_derived":
            own.extend(texts)
    return every, own


def group_titles(group: dict) -> list[str]:
    """The event mentions (titles) a group's claims carry."""
    out = []
    for claim in group.get("claims") or ():
        if isinstance(claim, dict):
            title = " ".join(str(claim.get("event_mention") or "").split())
            if title and title not in out:
                out.append(title)
            # v415: "narrator (as a kid)" — the note on a subject is a title.
            for note in _PARENTHETICAL_RE.findall(str(claim.get("subject_mention") or "")):
                note = " ".join(note.split())
                if note and note not in out:
                    out.append(note)
    return out


def owner_handle(text: object) -> bool:
    """v415. Is this subject mention the owner said with a note — "narrator
    (as a kid)", "Narrator's family", "Self"? Read through
    `identity_resolution.OWNER_SUBJECT_MENTIONS`, the one owner-mention table."""
    import identity_resolution as ident  # noqa: PLC0415

    body = _PARENTHETICAL_RE.sub(" ", str(text or ""))
    body = _OWNER_HANDLE_TAIL_RE.sub("", " ".join(body.split()).strip(" ,.;"))
    key = ident.normalized_mention_key(body)
    return bool(key) and (key in ident.OWNER_SUBJECT_MENTIONS
                          or key in getattr(ident, "OWNER_COUPLE_SUBJECT_WORDS", ()))


def names_the_owner(group: dict) -> bool:
    """Does any claim's subject mention name the owner (:func:`owner_handle`)?"""
    return any(isinstance(claim, dict) and owner_handle(claim.get("subject_mention"))
               for claim in group.get("claims") or ())


def remembered_moment(texts: object, titles: object = ()) -> bool:
    """v415. A moment naming no life stage is the owner's memory unless EVERY
    sentence it is told in is somebody else's fact ("Dad worked nights at the
    cannery")."""
    sentences = _sentences([str(t) for t in texts or ()]) or \
        _sentences([str(t) for t in titles or ()])
    if not sentences:
        return True
    return not all(_third_person_fact(sentence) for sentence in sentences)


def negated(text: object) -> bool:
    """Does the sentence say the thing did not happen then?"""
    return bool(_NEGATION_RE.search(str(text or "")))


def group_quotes(group: dict) -> list[str]:
    """The group's texts that are sentences, not titles."""
    titles = set(group_titles(group))
    every, _own = group_texts(group)
    return [text for text in every if text not in titles]


def _sentences(texts: list[str]) -> list[str]:
    return [s for text in texts for s in _SENTENCE_SPLIT_RE.split(text) if s.strip()]


def life_stage(texts: object, titles: object = ()) -> dict | None:
    """``{"stage", "phrase", "remembered"}`` — the first life stage the telling
    names, and whether any sentence naming it is the owner's own memory — or
    ``None`` when no life-stage phrase is there.

    ``texts`` are the telling's own sentences; ``titles`` (a moment's event
    mention, "Dad in school during early childhood") are read only when no
    sentence names a stage, because a title has no grammar to say whose fact
    it is."""
    for body in (texts, titles):
        found = _stage_of(_sentences([str(t) for t in body or ()]))
        if found is not None:
            return found
    return None


def _stage_of(sentences: list[str]) -> dict | None:
    for stage, patterns in STAGE_PATTERNS:
        hits = []
        for sentence in sentences:
            for pattern in patterns:
                found = pattern.search(sentence)
                if found:
                    hits.append((sentence, " ".join(found.group(0).split())))
                    break
        if not hits:
            continue
        remembered = any(not _third_person_fact(sentence) for sentence, _ in hits)
        return {"stage": stage, "phrase": hits[0][1].lower(), "remembered": remembered}
    return None


def _third_person_fact(sentence: str) -> bool:
    """A sentence that dates somebody ELSE's fact by the owner's life stage."""
    if _EXPERIENCER_RE.search(sentence):
        return False
    return bool(_POSSESSIVE_PERIOD_RE.search(sentence)
                or _THIRD_PERSON_FACT_RE.search(sentence))


def states_its_own_date(own_texts: object) -> bool:
    """Does the owner's own wording carry a year, a decade or an age? Then it is
    dated by those words, and a life-stage phrase beside them reads nothing."""
    for text in own_texts or ():
        body = str(text)
        if chrono.YEAR_RE.search(body) or _DECADE_RE.search(body):
            return True
        if any(pattern.search(body) for pattern in cd.AGE_STATEMENT_RES):
            return True
    return False


def proper_names(texts: object) -> set[str]:
    """The multi-word proper names a telling uses, lead words dropped."""
    names: set[str] = set()
    for text in texts or ():
        for match in _PROPER_NAME_RE.finditer(str(text)):
            words = re.sub(r"['’]s$", "", match.group(0)).split()
            while words and words[0].lower().rstrip("'’s") in _NAME_LEADERS:
                words = words[1:]
            words = [re.sub(r"['’]s$", "", w) for w in words]
            if len(words) >= 2:
                names.add(" ".join(words))
    return names


def named_places(texts: object) -> list[str]:
    """"at Harbor Lane", "in Port Ellis" — the homes a telling names."""
    out: list[str] = []
    for text in texts or ():
        for match in _NAMED_PLACE_RE.finditer(str(text)):
            # A place never runs across a sentence end ("Seabright. Our").
            place = re.split(r"[.!?]\s", match.group("place"))[0].strip(" .,;")
            if place and place not in out:
                out.append(place)
    return out


def mentions(texts: object, spellings: object) -> bool:
    """Is any of these spellings in the texts, as whole words?"""
    body = " ".join(str(t) for t in texts or ())
    for spelling in spellings or ():
        word = " ".join(str(spelling or "").split())
        if len(word) < 3:
            continue
        flags = 0 if word[:1].isupper() else re.IGNORECASE
        if re.search(r"(?<![\w])" + re.escape(word) + r"(?![\w])", body, flags):
            return True
    return False


# --------------------------------------------------------------------------
# Narrowing and the floor
# --------------------------------------------------------------------------

def _ord(value: object, *, end: bool):
    return chrono._ordinal(str(value), end=end) if value else None  # noqa: SLF001


def _with_bounds(record: chrono.DateRecord, earliest: str, latest: str, note: dict):
    best = earliest if earliest == latest else f"{earliest}/{latest}"
    return replace(record, best=best, earliest=earliest, latest=latest,
                   granularity="range" if earliest != latest else record.granularity,
                   provenance=tuple(record.provenance) + (note,))


def _hull_within(record: chrono.DateRecord, pieces: list) -> tuple[str, str] | None:
    """The window cut back to the pieces it touches (the place anchors' own
    clip), or ``None`` when it touches none."""
    hits = [hit for hit in (chrono.intersect(record, piece) for piece in pieces)
            if hit is not None]
    if not hits:
        return None
    lows = [h.earliest for h in hits if h.earliest]
    highs = [h.latest for h in hits if h.latest]
    earliest = min(lows, key=lambda v: _ord(v, end=False)) if lows else record.earliest
    latest = max(highs, key=lambda v: _ord(v, end=True)) if highs else record.latest
    return earliest, latest


def _envelope(pieces: list) -> tuple[str, str] | None:
    lows = [p.earliest for p in pieces if p.earliest]
    highs = [p.latest for p in pieces if p.latest]
    if not lows or not highs:
        return None
    return (min(lows, key=lambda v: _ord(v, end=False)),
            max(highs, key=lambda v: _ord(v, end=True)))


def band_floor(stage: dict, config: dict) -> int:
    """The age a stage's band opens at (:data:`REMEMBERED_STAGE` reads the
    earliest-memory age)."""
    bands = config["bands"]
    if stage["stage"] in bands:
        return bands[stage["stage"]][0]
    return config["earliest_memory_age"]


def place_story(record: object, *, stage: dict, birth: object, contexts: object,
                config: dict) -> tuple[chrono.DateRecord | None, dict]:
    """The record placed by better context and floored at the memory age.

    ``contexts`` is ``[{"context", "text", "pieces": [DateRecord, …]}]`` in
    :data:`CONTEXTS` order (the fold gathers them; a context whose pieces are
    empty was looked for and not found, and ``outcome`` may be preset —
    ``already_applied``, ``negated``, ``ambiguous``). A LOCATOR
    (:data:`LOCATOR_CONTEXTS`) replaces the inferred band with its own window
    — the first one found; a later locator only narrows that, and is
    ``disjoint`` when it cannot. ``person_lifetime`` only bounds. Returns
    ``(new record or None, finding detail)``; ``None`` means nothing moved.
    """
    parsed = record if isinstance(record, chrono.DateRecord) else chrono.from_dict(record)
    birth_record = birth if isinstance(birth, chrono.DateRecord) else chrono.from_dict(birth)
    tried: list[dict] = []
    detail = {"stage": stage["stage"], "phrase": stage.get("phrase") or "",
              "remembered": stage["remembered"], "contexts_tried": tried}
    if parsed is None or birth_record is None or not parsed.earliest or not parsed.latest:
        return None, detail
    current = parsed
    located = False
    for row in contexts or ():
        name = row.get("context")
        pieces = [p for p in row.get("pieces") or () if p is not None]
        entry = {"context": name, "text": row.get("text") or ""}
        tried.append(entry)
        if row.get("outcome"):
            entry["outcome"] = row["outcome"]
            located = located or row["outcome"] == "already_applied"
            continue
        if not pieces:
            entry["outcome"] = "not_found"
            continue
        if name in LOCATOR_CONTEXTS and not located:
            window = _envelope(pieces)
            if window is None:
                entry["outcome"] = "not_found"
                continue
            located = True
            if window == (current.earliest, current.latest):
                entry["outcome"] = "no_change"
                continue
            entry["outcome"] = "replaced_inferred"
            current = _with_bounds(current, window[0], window[1], {
                "rule": BETTER_CONTEXT_RULE, "context": name,
                "text": f"from {row.get('text') or name}",
                "was": f"{parsed.earliest}/{parsed.latest}"})
            continue
        hull = _hull_within(current, pieces)
        if hull is None:
            entry["outcome"] = "disjoint"
        elif hull == (current.earliest, current.latest):
            entry["outcome"] = "no_change"
        else:
            entry["outcome"] = "narrowed"
            current = _with_bounds(current, hull[0], hull[1], {
                "rule": BETTER_CONTEXT_RULE, "context": name,
                "text": f"from {row.get('text') or name}",
                "was": f"{parsed.earliest}/{parsed.latest}"})
        if name in LOCATOR_CONTEXTS and entry["outcome"] != "disjoint":
            located = True
    age = config["earliest_memory_age"]
    low = (age if located else band_floor(stage, config)) if stage["remembered"] else None
    detail["band_applied"] = bool(stage["remembered"] and not located)
    if low is not None:
        floor_record = chrono.from_age_band(birth_record, low, low)
        floor = floor_record.earliest if floor_record is not None else None
        detail["floor_age"] = low
        if floor and _ord(current.earliest, end=False) < _ord(floor, end=False):
            if _ord(current.latest, end=True) < _ord(floor, end=False):
                # Context put the whole story before he could remember it: a
                # disagreement to surface, never a bound to slide.
                detail["outcome"] = "before_earliest_memory"
            else:
                said = (f"a memory told “{stage['phrase']}”" if stage.get("phrase")
                        else "a memory of yours")
                current = _with_bounds(current, floor, current.latest, {
                    "rule": REMEMBERED_STORY_FLOOR_RULE,
                    "text": (f"{said} opens no earlier than your "
                             f"{_ordinal_word(low)} birthday"),
                    "was": current.earliest, "floor": floor, "age": low})
    if current is parsed:
        return None, detail
    detail["was"] = f"{parsed.earliest}/{parsed.latest}"
    detail["now"] = f"{current.earliest}/{current.latest}"
    return current, detail


def _ordinal_word(age: int) -> str:
    suffix = "th" if 10 <= age % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(age % 10, "th")
    return f"{age}{suffix}"
