#!/usr/bin/env python3
"""The READING — one model pass over volunteered text (v291, R6–R9).

Owner rulings R6–R9 of 2026-09-04 (`lifehug-platform
docs/decisions/2026-09-03-timeline-unification/add-landmark-reading-plan.md`
§2), an amendment to ADR 0033.

Add Landmark used to read a submission three times: a deterministic block
grammar first, then the general listener over the whole document blind to what
the grammar had taken, then one focused recorder per domain the listener named
— also blind. The first real use of it lost the date off every model-read unit,
labelled eight stays by their city, invented names, and showed "inferred" where
nothing had been read at all. The cause was the ORDER: a deterministic reader in
front of the interaction, hiding its own work from the model.

R6 reverses it. **The interaction reads; the system validates and files.** One
model pass sees the whole text with the whole context — the domains and the
exact keys each can read, the date forms, the estimation conventions, the
relation rule, the roster, what is already filed — and returns ONE reading.
Nothing deterministic touches the person's words before it. What stays
deterministic is everything downstream: the evidence guard
(`landmark_offer.date_evidence`), duplicates and conflicts, filing, receipts,
retraction.

This module owns three things and nothing else:

  * :func:`build_reading_prompt` — the leaf plus its substitutions, every one
    of them RENDERED FROM THE LIVE TABLES. The domain key lists are
    `general_listener.render_domain_digest`'s (the same derivation the focused
    recorder is offered), extended by :func:`render_name_keys` — the E-L2c
    name fields, derived by PROBING `landmarks_interaction.validate_landmark`
    rather than by a hand-typed list, so a field the validator stops accepting
    stops being taught in the same commit.
  * :func:`reading_extractor` — the pass's identity, versioned by its own
    leaf's bytes, exactly as `general_listener.listener_extractor` is.
  * :func:`parse_reading` — lenient in SHAPE, strict in SUBSTANCE (§3.1).
    Missing lists are empty; unknown keys are dropped with a finding; every
    quote must locate in the submitted text; dangling and cyclic ``within``
    refs are findings and never crashes; records go through
    `landmarks_interaction.validate_landmark` after the ``names`` block is
    mapped onto its E-L2c fields. A completion this cannot read at all is an
    EMPTY :class:`Reading` with a finding, never an exception.

What this module deliberately does NOT do: decide whether a bound is stated or
inferred (that is `landmark_offer.date_evidence`, off the bytes), inherit a
parent's dates (that is `landmark_offer.propose`, rule 4), or file anything.

Pure. No vault, no clock, no model call.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from pathlib import Path

_SYSTEM_DIR = Path(__file__).resolve().parent
if str(_SYSTEM_DIR) not in sys.path:
    sys.path.insert(0, str(_SYSTEM_DIR))

import chronology as chrono  # noqa: E402
import general_listener as gl  # noqa: E402
import landmarks_interaction as li  # noqa: E402
from lifehug_core import INTERACTIONS_DIR  # noqa: E402
from temporal_claims import collapsed_text  # noqa: E402


class LandmarkReadingError(ValueError):
    """The leaf could not be loaded. A COMPLETION never raises — see
    :func:`parse_reading`."""


#: The one reading leaf. `interaction.yaml` carries the same file name under
#: `composition.reading` and `tests/test_landmark_reading.py` pins them equal,
#: so declaring the slot and naming it in code stay one edit — the discipline
#: `composition.recorder` and `composition.listener` already keep.
READING_PROMPT = "reading.md"

#: The extractor name this pass files receipts under. A THIRD name beside
#: `general_listener` and `landmark_recorder`, never a rename of either: the
#: collect mode still uses both, and "what read this" must stay answerable.
READING_EXTRACTOR = "landmark_reading"

#: The model class the reading runs at. `interaction.yaml` carries the same
#: value as `role.reading` and a test pins them equal. Sonnet-class, not the
#: listener's Haiku-class: this pass carries the whole document, the whole
#: vocabulary and the relation rule at once, which is the judgment the
#: three-pass shape was splitting badly (R6).
DEFAULT_READING_ROLE = "sonnet-class"

#: The completion a caller gets when nothing was scripted for a prompt — an
#: empty reading, in the contract's own shape.
EMPTY_READING_COMPLETION = ('{"units": [], "events": [], "stories": [], '
                            '"unplaced": []}')


# --------------------------------------------------------------------------
# The vocabulary the leaf teaches — rendered, never typed
# --------------------------------------------------------------------------

#: The `names` block's own fields, in the order the leaf lists them. Which of
#: them a domain actually accepts is PROBED (:func:`name_keys_for`), never
#: declared here: `landmarks_interaction.validate_landmark` is the authority
#: and this is only the candidate set to ask it about.
NAME_FIELDS = ("nickname", "city", "address", "place_ref", "link")

#: One probe value per name field. Throwaway values; only whether
#: `validate_landmark` KEEPS the key matters — the same technique
#: `landmark_recorder._survives` uses for the ladder keys, run against the
#: SEMANTIC validator alone because the E-L2c fields are exactly the ones the
#: structural layer (`conversation_delivery._LANDMARK_KEYS`) does not know yet.
_NAME_PROBES = {
    "nickname": "The Blue House",
    "city": "Riverbend",
    "address": "12 Elm Street, Riverbend",
    "place_ref": "place/riverbend",
    "link": "https://example.invalid/map",
}


def name_keys_for(domain: object, *,
                  framework_root: str | Path | None = None) -> tuple[str, ...]:
    """Which ``names`` fields survive validation for ``domain``.

    Derived by asking `landmarks_interaction.validate_landmark` one field at a
    time. Four of the five are additive E-L2c fields the validator accepts on
    any domain; ``city`` and ``address`` are the residences ladder's own rungs
    and survive only there. Nothing here is a list somebody keeps up to date.
    """
    name = collapsed_text(domain)
    if not name:
        return ()
    keys: list[str] = []
    for field_name in NAME_FIELDS:
        probe = {"domain": name, field_name: _NAME_PROBES[field_name]}
        validated = li.validate_landmark(probe, framework_root=framework_root)
        if isinstance(validated, dict) and field_name in validated:
            keys.append(field_name)
    return tuple(keys)


def render_name_keys(framework_root: str | Path | None = None) -> str:
    """The ``names`` vocabulary, one line per domain that has one."""
    lines: list[str] = []
    for row in li.load_questions(framework_root=framework_root):
        keys = name_keys_for(row["domain"], framework_root=framework_root)
        if keys:
            lines.append(f"- {row['domain']}: {' | '.join(keys)}")
    return "\n".join(lines) if lines else "(no name fields on any domain)"


#: The words and marks that make a bound the person's own ESTIMATE rather than
#: their assertion (R8). The leaf teaches exactly this list and nothing else,
#: and `landmark_offer._HEDGE_RE` is the deterministic reader of the same
#: convention over the quote — two readers of one convention, and the leaf's
#: half is rendered from here so the two cannot drift into different words.
ESTIMATION_MARKS = (
    "[1974]", "about 1974", "around 1974", "maybe 1974", "1974?",
    "sometime in 1974",
)


def render_estimation_marks() -> str:
    return " · ".join(f"`{mark}`" for mark in ESTIMATION_MARKS)


#: Which noun a domain's span is called when a child inherits its dates
#: (R7's provenance clause: *"from the dates of the Avenue F stay"*).
#: `landmark_offer` renders the clause; the leaf shows the same three words so
#: the model reads and the system writes one vocabulary.
SPAN_NOUN_BY_DOMAIN = {
    "residences": "stay",
    "work": "tenure",
    "schools": "schooling",
    "military": "service",
}


def span_noun(domain: object) -> str:
    """The word for one span of ``domain``. Falls back to the unit kind."""
    name = collapsed_text(domain)
    noun = SPAN_NOUN_BY_DOMAIN.get(name)
    if noun:
        return noun
    import landmark_offer as lo  # noqa: PLC0415 — the unit-kind table's home

    return lo.UNIT_KIND_BY_DOMAIN.get(name, name or "unit")


def render_span_nouns() -> str:
    return " · ".join(f"{domain} → {noun}"
                      for domain, noun in SPAN_NOUN_BY_DOMAIN.items())


#: Which record shape a domain's dates file into — its ladder's own answer,
#: never a second table. A domain whose ladder has `span` takes a stretch; a
#: domain whose ladder has `date` takes one point.
def date_shape_for(row: object) -> str:
    """``"span"``, ``"date"`` or ``""`` for one question-set row."""
    from landmark_recorder import recordable_keys  # noqa: PLC0415

    keys = set(recordable_keys(row))
    if "span" in keys:
        return "span"
    if "date" in keys:
        return "date"
    return ""


def render_date_shapes(framework_root: str | Path | None = None) -> str:
    """Which domains take a stretch and which take one date."""
    spans: list[str] = []
    points: list[str] = []
    for row in li.load_questions(framework_root=framework_root):
        shape = date_shape_for(row)
        if shape == "span":
            spans.append(row["domain"])
        elif shape == "date":
            points.append(row["domain"])
    lines = []
    if spans:
        lines.append("- a stretch (start and end): " + ", ".join(spans))
    if points:
        lines.append("- one date: " + ", ".join(points))
    return "\n".join(lines) if lines else "(no dated domains)"


# --------------------------------------------------------------------------
# The prompt
# --------------------------------------------------------------------------

def _leaf_path(framework_root: str | Path | None = None) -> Path:
    base = (Path(framework_root) / "interactions" / "landmarks"
            if framework_root else INTERACTIONS_DIR / "landmarks")
    return base / "prompt" / READING_PROMPT


def load_reading_leaf(framework_root: str | Path | None = None) -> str:
    """The reading leaf, verbatim. A host REPLAYs exactly this text."""
    try:
        return _leaf_path(framework_root).read_text(encoding="utf-8")
    except OSError as exc:
        raise LandmarkReadingError(f"no reading leaf: {exc}") from exc


def build_reading_prompt(text: str, *, landmarks: object = (),
                         roster: object = (),
                         framework_root: str | Path | None = None) -> str:
    """The whole reading prompt, from the leaf plus its substitutions.

    ``.replace``, never ``.format`` — the leaf carries literal JSON braces and
    the person's own text may carry any brace at all.

    Every vocabulary block is derived from the live tables:
    ``{domains}`` is `general_listener.render_domain_digest`'s nine lines (the
    same closed key set the focused recorder is offered), ``{name_keys}`` is
    :func:`render_name_keys`, ``{date_shapes}`` is :func:`render_date_shapes`,
    ``{estimation_marks}`` is :func:`render_estimation_marks`,
    ``{span_nouns}`` is :func:`render_span_nouns`, ``{known_entries}`` is
    `general_listener.render_all_known_entries` and ``{roster}`` is
    `landmarks_interaction.render_roster`.
    """
    filled = load_reading_leaf(framework_root)
    for token, value in (
        ("{domains}", gl.render_domain_digest(framework_root)),
        ("{name_keys}", render_name_keys(framework_root)),
        ("{date_shapes}", render_date_shapes(framework_root)),
        ("{estimation_marks}", render_estimation_marks()),
        ("{span_nouns}", render_span_nouns()),
        ("{known_entries}", gl.render_all_known_entries(
            landmarks, framework_root=framework_root)),
        ("{roster}", li.render_roster(roster, landmarks=landmarks,
                                      framework_root=framework_root)),
        ("{text}", str(text or "").strip()),
    ):
        filled = filled.replace(token, value)
    return filled


def reading_extractor(model: object = DEFAULT_READING_ROLE, *,
                      framework_root: str | Path | None = None) -> dict:
    """This pass's extractor block, versioned by its OWN leaf's bytes.

    The same discipline as `general_listener.listener_extractor`: editing the
    leaf is a NEW extractor and lands on a new receipt path beside the old
    one, rather than rewriting yesterday's reading.
    """
    return gl.claim_extractor(READING_EXTRACTOR,
                              leaf=load_reading_leaf(framework_root),
                              model=model)


def reading_extractor_version(model: object = DEFAULT_READING_ROLE, *,
                              framework_root: str | Path | None = None) -> str:
    return gl.claim_extractor_version(
        reading_extractor(model, framework_root=framework_root))


# --------------------------------------------------------------------------
# The reading, typed
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class ReadUnit:
    """One unit of the reading — a stay, a tenure, a schooling, a birth…

    ``ref`` is the MODEL's own short handle, valid only inside this reading;
    `landmark_offer` mints the durable `unit_id`. ``within`` is another unit's
    ref, already validated (dangling and cyclic refs are dropped to ``None``
    with a finding).
    """

    ref: str
    domain: str
    subject: str
    record: dict
    quote: dict
    names: dict = field(default_factory=dict)
    dates: dict | None = None
    within: str | None = None


@dataclass(frozen=True)
class ReadEvent:
    """One thing that happened, dated or not.

    ``date`` is normalized (`chronology.normalized_date`) or ``None``. A dated
    event files as a claim and an undated one as a moment; 6g does the filing,
    and this reading only says which it is.
    """

    ref: str
    text: str
    kind: str
    subject_mention: str
    quote: dict
    date: dict | None = None
    within: str | None = None


@dataclass(frozen=True)
class ReadStory:
    """Prose the person offered that no unit and no event carries."""

    quote: dict
    within: str | None = None


@dataclass(frozen=True)
class ReadUnplaced:
    """A span the reading kept but could place nowhere, and why."""

    quote: dict
    why: str = ""


@dataclass(frozen=True)
class Reading:
    """One completion, parsed. Typed lists, never a mixed bag.

    An unreadable completion is this, empty, with one finding — never an
    exception: a person's words must not be lost to a model's bad JSON.
    """

    units: tuple[ReadUnit, ...] = ()
    events: tuple[ReadEvent, ...] = ()
    stories: tuple[ReadStory, ...] = ()
    unplaced: tuple[ReadUnplaced, ...] = ()
    findings: tuple[str, ...] = ()

    def __len__(self) -> int:
        return (len(self.units) + len(self.events) + len(self.stories)
                + len(self.unplaced))


# --------------------------------------------------------------------------
# The parse — lenient in shape, strict in substance (§3.1)
# --------------------------------------------------------------------------

#: The top-level keys the contract declares. Anything else is dropped with a
#: finding rather than guessed at.
READING_KEYS = ("units", "events", "stories", "unplaced")

#: The keys ONE unit may carry.
UNIT_ITEM_KEYS = ("ref", "domain", "subject", "names", "record", "dates",
                  "within", "quote")

#: The keys ONE event may carry.
EVENT_ITEM_KEYS = ("ref", "text", "kind", "subject_mention", "date", "within",
                   "quote")

#: The keys one story or one unplaced span may carry.
STORY_ITEM_KEYS = ("quote", "within")
UNPLACED_ITEM_KEYS = ("quote", "why")

#: The keys a unit's ``dates`` block may carry.
DATE_ITEM_KEYS = ("start", "end", "ongoing", "start_estimated", "end_estimated")

_UNREADABLE = "the reading was not usable JSON; nothing was read from it"


def _dropped(kind: str, detail: str) -> str:
    return f"dropped {kind}: {detail}"


class _Cursor:
    """Where the last quote ended, so the next one is looked for after it.

    A reading is emitted front to back over a document that repeats itself:
    the same employer named on three consecutive blocks is three units whose
    quotes are the same string. Threading the cursor is what makes them three
    DIFFERENT places in the text rather than three readings of the first one —
    and `landmark_offer.locate` still falls back to a search from the start,
    so a quote the model emitted out of order still locates.
    """

    def __init__(self) -> None:
        self.at = 0

    def reset(self) -> None:
        self.at = 0


def _quote_of(value: object, text: str, findings: list[str], *,
              kind: str, cursor: _Cursor | None = None) -> dict | None:
    """One item's quotation, LOCATED in the submitted text, or ``None``.

    Rule 1 of §3.1: a quote that is not in the text is not evidence of
    anything, so the item it belongs to is dropped rather than stored against
    a made-up offset.
    """
    import landmark_offer as lo  # noqa: PLC0415 — `locate` lives with the guard

    raw = value if isinstance(value, str) else ""
    if not raw.strip():
        findings.append(_dropped(kind, "no quote"))
        return None
    located = lo.locate(text, raw, hint=cursor.at if cursor else 0)
    if located is None:
        findings.append(_dropped(kind, f"quote is not in the text: {raw[:60]!r}"))
        return None
    if cursor is not None:
        cursor.at = located["offset"] + located["length"]
    return located


def _known_keys(row: dict, allowed: tuple[str, ...], findings: list[str], *,
                kind: str) -> dict:
    """``row`` with the contract's keys only; the rest named and dropped."""
    kept = {key: value for key, value in row.items() if key in allowed}
    extra = sorted(set(row) - set(allowed))
    for key in extra:
        findings.append(f"dropped unknown {kind} key: {key}")
    return kept


def _date_block(value: object, findings: list[str]) -> dict | None:
    """A unit's ``dates`` block, keys checked. ``None`` when there is none."""
    if value in (None, {}, ""):
        return None
    if not isinstance(value, dict):
        findings.append(_dropped("dates", "not an object"))
        return None
    block = _known_keys(value, DATE_ITEM_KEYS, findings, kind="dates")
    if not any(block.get(bound) for bound in ("start", "end")):
        return None
    return block


def _record_for(domain: str, *, record: object, names: dict, dates: dict | None,
                subject: str, findings: list[str],
                framework_root: str | Path | None = None) -> dict | None:
    """One unit's landmark record, through the pinned semantic validator.

    The model's ``record`` is merged with the ``names`` block mapped onto the
    E-L2c fields, the ``dates`` block is turned into the shape the domain's own
    ladder takes (:func:`date_shape_for`), and the whole thing goes through
    `landmarks_interaction.validate_landmark` — the SAME door a conversation
    answer goes through. Deliberately NOT through
    `conversation_delivery._parse_landmark`: that structural layer's closed key
    set predates the E-L2c fields and drops a whole record that carries one, so
    running it here would silently discard exactly the names R7 needs
    (`add-landmark-reading-plan.md` §3, "why names matter").
    """
    try:
        row = li.domain_row(domain, framework_root=framework_root)
    except li.LandmarkInteractionError:
        findings.append(_dropped("unit", f"unknown domain {domain!r}"))
        return None
    payload: dict = {"domain": domain}
    if isinstance(record, dict):
        for key, value in record.items():
            if key == "domain":
                continue
            payload[key] = value
    accepted = set(name_keys_for(domain, framework_root=framework_root))
    for key, value in (names or {}).items():
        if key not in accepted:
            findings.append(
                f"dropped name {key!r}: {domain} does not accept it")
            continue
        payload[key] = value
    from landmark_recorder import recordable_keys  # noqa: PLC0415

    if subject and "label" in recordable_keys(row) and not payload.get("label"):
        payload["label"] = subject
    shape = date_shape_for(row)
    if dates and shape == "span":
        span: dict = {}
        for bound in ("start", "end"):
            if dates.get(bound):
                span[bound] = dates[bound]
        if dates.get("start_estimated") is True and "start" in span:
            span["start_approximate"] = True
        if dates.get("end_estimated") is True and "end" in span:
            span["end_approximate"] = True
        if span:
            payload["span"] = span
        if dates.get("ongoing") is True:
            payload["ongoing"] = True
        elif dates.get("ongoing") is False and "end" in span:
            payload["ongoing"] = False
    elif dates and shape == "date":
        if dates.get("start"):
            payload["date"] = dates["start"]
            if dates.get("start_estimated") is True:
                payload["approximate"] = True
        if dates.get("end"):
            findings.append(
                f"dropped end date: {domain} records one date, not a stretch")
    elif dates:
        findings.append(f"dropped dates: {domain} does not date its entries")
    validated = li.validate_landmark(payload, framework_root=framework_root)
    if not isinstance(validated, dict):
        findings.append(_dropped("unit", f"{domain} record did not validate"))
        return None
    return validated


def _resolve_refs(units: list[dict], findings: list[str]) -> None:
    """``within`` refs validated in place: dangling and cyclic become ``None``.

    Rule 8 of §3.1. A ref that names nothing, names itself, or sits on a cycle
    is a finding and the item is KEPT with ``within: None`` — losing the unit
    because the model mis-linked it would be exactly the silent drop this whole
    mode exists to end.

    A cycle is cut where it is FOUND and nowhere else: the first unit walked
    into the loop loses the parent that closed it, and every other unit on it
    keeps the real parent it had. Blanking the whole cycle would throw away
    relations the model got right to punish the one it got wrong.
    """
    by_ref = {row["ref"]: row for row in units if row.get("ref")}
    for row in units:
        target = row.get("within")
        if not target:
            row["within"] = None
            continue
        if target not in by_ref:
            findings.append(
                f"dropped within on {row['ref']}: no unit {target!r}")
            row["within"] = None
    for row in units:
        seen = {row["ref"]}
        cursor = row.get("within")
        while cursor:
            if cursor in seen:
                findings.append(
                    f"dropped within on {row['ref']}: it is part of a cycle")
                row["within"] = None
                break
            seen.add(cursor)
            cursor = by_ref.get(cursor, {}).get("within")


def _event_within(value: object, refs: set[str], findings: list[str],
                  *, ref: str) -> str | None:
    target = collapsed_text(value)
    if not target:
        return None
    if target not in refs:
        findings.append(f"dropped within on event {ref}: no unit {target!r}")
        return None
    return target


def parse_reading(raw: object, *, text: str = "",
                  framework_root: str | Path | None = None) -> Reading:
    """One reading completion, through §3.1's rules, in order.

    Lenient in SHAPE: a missing list is an empty one, an unknown key is
    dropped with a finding, and a completion that is not JSON at all is an
    EMPTY :class:`Reading` with one finding rather than an exception.

    Strict in SUBSTANCE: every quote must locate in ``text`` (rule 1); dates go
    through `chronology.normalized_date`, which reads every form the leaf
    teaches (v290's `parse_loose_date`); ``*_estimated`` becomes
    `confidence: approximate` on that bound (rule 3, R8); refs are validated
    (rule 8); and every record goes through
    `landmarks_interaction.validate_landmark` after ``names`` is mapped onto
    its E-L2c fields.

    What this does NOT decide: whether a bound is STATED. That is
    `landmark_offer.date_evidence`, read off the bytes after this returns —
    rule 2 lives there because it is a question about the person's text, not
    about the model's JSON.
    """
    findings: list[str] = []
    body = str(text or "")
    if not isinstance(raw, str):
        return Reading(findings=(_UNREADABLE,))
    stripped = raw.strip()
    if stripped.startswith("```"):
        stripped = stripped.split("\n", 1)[-1].rsplit("```", 1)[0]
    try:
        data = json.loads(stripped)
    except (ValueError, TypeError):
        return Reading(findings=(_UNREADABLE,))
    if not isinstance(data, dict):
        return Reading(findings=(_UNREADABLE,))
    data = _known_keys(data, READING_KEYS, findings, kind="reading")
    cursor = _Cursor()

    # -- units ------------------------------------------------------------
    drafts: list[dict] = []
    used_refs: set[str] = set()
    for index, item in enumerate(data.get("units") or ()):
        if not isinstance(item, dict):
            findings.append(_dropped("unit", f"item {index} is not an object"))
            continue
        row = _known_keys(item, UNIT_ITEM_KEYS, findings, kind="unit")
        ref = collapsed_text(row.get("ref")) or f"u{index + 1}"
        if ref in used_refs:
            findings.append(_dropped("unit", f"duplicate ref {ref!r}"))
            continue
        domain = collapsed_text(row.get("domain"))
        if not domain:
            findings.append(_dropped("unit", f"{ref} names no domain"))
            continue
        quote = _quote_of(row.get("quote"), body, findings, kind=f"unit {ref}",
                          cursor=cursor)
        if quote is None:
            continue
        names = row.get("names") if isinstance(row.get("names"), dict) else {}
        names = {key: value for key, value in names.items()
                 if isinstance(value, str) and value.strip()}
        dates = _date_block(row.get("dates"), findings)
        subject = collapsed_text(row.get("subject"))
        record = _record_for(domain, record=row.get("record"), names=names,
                             dates=dates, subject=subject, findings=findings,
                             framework_root=framework_root)
        if record is None:
            continue
        used_refs.add(ref)
        drafts.append({
            "ref": ref, "domain": domain, "subject": subject,
            "record": record, "quote": quote, "names": dict(names),
            "dates": dates, "within": collapsed_text(row.get("within")) or None,
        })
    _resolve_refs(drafts, findings)
    units = tuple(ReadUnit(**row) for row in drafts)

    # -- events -----------------------------------------------------------
    cursor.reset()
    events: list[ReadEvent] = []
    seen_events: set[str] = set()
    for index, item in enumerate(data.get("events") or ()):
        if not isinstance(item, dict):
            findings.append(_dropped("event", f"item {index} is not an object"))
            continue
        row = _known_keys(item, EVENT_ITEM_KEYS, findings, kind="event")
        ref = collapsed_text(row.get("ref")) or f"e{index + 1}"
        if ref in seen_events:
            findings.append(_dropped("event", f"duplicate ref {ref!r}"))
            continue
        quote = _quote_of(row.get("quote"), body, findings, kind=f"event {ref}",
                          cursor=cursor)
        if quote is None:
            continue
        date = chrono.normalized_date(row.get("date")) if row.get("date") else None
        if row.get("date") and date is None:
            findings.append(f"dropped date on event {ref}: unreadable")
        seen_events.add(ref)
        events.append(ReadEvent(
            ref=ref,
            text=collapsed_text(row.get("text")),
            kind=collapsed_text(row.get("kind")),
            subject_mention=collapsed_text(row.get("subject_mention")),
            quote=quote, date=date,
            within=_event_within(row.get("within"), used_refs, findings,
                                 ref=ref),
        ))

    # -- stories and unplaced ---------------------------------------------
    cursor.reset()
    stories: list[ReadStory] = []
    for index, item in enumerate(data.get("stories") or ()):
        if isinstance(item, str):
            item = {"quote": item}
        if not isinstance(item, dict):
            findings.append(_dropped("story", f"item {index} is not an object"))
            continue
        row = _known_keys(item, STORY_ITEM_KEYS, findings, kind="story")
        quote = _quote_of(row.get("quote"), body, findings,
                          kind=f"story {index}", cursor=cursor)
        if quote is None:
            continue
        stories.append(ReadStory(
            quote=quote,
            within=_event_within(row.get("within"), used_refs, findings,
                                 ref=f"story {index}"),
        ))

    cursor.reset()
    unplaced: list[ReadUnplaced] = []
    for index, item in enumerate(data.get("unplaced") or ()):
        if isinstance(item, str):
            item = {"quote": item}
        if not isinstance(item, dict):
            findings.append(_dropped("unplaced",
                                     f"item {index} is not an object"))
            continue
        row = _known_keys(item, UNPLACED_ITEM_KEYS, findings, kind="unplaced")
        quote = _quote_of(row.get("quote"), body, findings,
                          kind=f"unplaced {index}", cursor=cursor)
        if quote is None:
            continue
        unplaced.append(ReadUnplaced(quote=quote,
                                     why=collapsed_text(row.get("why"))))

    return Reading(units=units, events=tuple(events), stories=tuple(stories),
                   unplaced=tuple(unplaced),
                   findings=tuple(dict.fromkeys(findings)))


__all__ = [
    "DEFAULT_READING_ROLE",
    "EMPTY_READING_COMPLETION",
    "ESTIMATION_MARKS",
    "LandmarkReadingError",
    "NAME_FIELDS",
    "READING_EXTRACTOR",
    "READING_PROMPT",
    "ReadEvent",
    "ReadStory",
    "ReadUnit",
    "ReadUnplaced",
    "Reading",
    "SPAN_NOUN_BY_DOMAIN",
    "build_reading_prompt",
    "date_shape_for",
    "load_reading_leaf",
    "name_keys_for",
    "parse_reading",
    "reading_extractor",
    "reading_extractor_version",
    "render_date_shapes",
    "render_estimation_marks",
    "render_name_keys",
    "render_span_nouns",
    "span_noun",
]
