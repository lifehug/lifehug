#!/usr/bin/env python3
"""Add Landmark — the `offer` mode of the Landmarks Interaction (v287).

Owner rulings R3, R3a and R3b of 2026-09-03 (`lifehug-platform
docs/decisions/2026-09-03-timeline-unification/decision-record.md` §5), ADR
0033. The `collect` mode asks a question and files the answer. This mode
reverses the direction: **the person hands the system ordinary text** — one
dated event, a residence history, a work history, a pasted document — and the
same three passes read it, propose landmark units with evidence, and file the
confirmed ones through the SAME landmark writer a conversation answer uses.

It is a MODE, not an interaction kind (R3b). Nothing here composes a second
writer.

**ONE READING (v291, owner rulings R6-R9).** Until v290 this path read a
submission three times — a deterministic block grammar first, then the general
listener over the whole document blind to what the grammar had taken, then one
focused recorder per domain, also blind. The owner's first real use of it lost
the date off every model-read unit, labelled eight stays by their city and
showed "inferred" where nothing had been read at all. R6 reverses the order:
**the interaction reads, and the system validates and files.** :func:`propose`
composes ONE prompt (`landmark_reading.build_reading_prompt`), makes ONE call,
and parses ONE completion (`landmark_reading.parse_reading`). No grammar runs
first, no listener runs, no recorder runs. :func:`grammar_units` survives this
release unused, and Cut 6h deletes it.

**Nothing files before a person confirms.** :func:`propose` writes exactly one
file, the proposal, and the submitted text is retained inside it from the
moment it is submitted (R3: evidence is durable before confirmation, and the
Codex audit's "nothing durable until confirmed" is narrowed by that ruling).
:func:`apply` files the units the person named and NOTHING else.

**A confirmed unit is a STATED fact** (decision record §4.2) — but only where
the person's own words carry the date. This module never trusts a model's
self-declared basis: :func:`date_evidence` re-reads every bound against the
source text, and a bound the text does not carry files as an INFERENCE
(`confidence: inferred`, a verbatim `inferred` provenance clause) no matter
what the completion said. A model's reading of the person's words is stated; a
model's guess beyond the words is not, and the difference is decided here,
deterministically, from the bytes. A bound the text does NOT carry is dropped
with a finding rather than rewritten into a confident-looking inference.

**A span is the unit of relation (R7).** A school, a job or an event named
inside a stay carries ``within``, and a unit with no dates whose ``within``
target HAS dates inherits them — ``basis: anchor``, ``confidence: inferred``,
and the verbatim provenance clause *"from the dates of the Orchard House stay"*,
rendered through the same `_restate` path every other inference goes through.
A unit with no dates and no dated parent is ``basis: "none"`` and says "no date
read"; it never says "inferred", because nothing was read.

**Idempotency.** A unit's identity is content-addressed
(:func:`derive_unit_id`) from its domain, kind, subject, dates and quote, so
the same text proposed twice yields the same unit ids. Filing goes through
`go_dig_writer.record_unit`'s ``digest_override`` seam — the identity is
``(proposal_id, unit_id)``, never a filing ordinal — so applying the same
units twice promotes the same source, derives the same claims, and files
nothing a second time. The apply receipt is content-addressed the same way
and is written once.

**Model tiers, and format repair.** Both extraction passes are the ones the
interaction already declares — `role.listener` and `role.recorder`, both
Haiku-class — and the worker that shows the reading back is `role.worker`,
Sonnet-class. There is no separate repair prompt and there is deliberately no
place for one: a paste the grammar cannot read is not "malformed input" to be
fixed before reading, it is ordinary text, and the Haiku-class listener is
what reads it. **No model call recalculates a date.** Every interval that
files is `chronology`'s, derived from what the person wrote.

**Undo** is `temporal_store.retract_claims` over exactly the claims the filed
units stand on, then a republish. The evidence and the receipt stay on disk;
the retraction is its own immutable file beside the receipt, never an edit of
it.

Pure except for the injected ``call`` and the three functions that name a
vault (:func:`propose`, :func:`apply`, :func:`retract`).
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

_SYSTEM_DIR = Path(__file__).resolve().parent
if str(_SYSTEM_DIR) not in sys.path:
    sys.path.insert(0, str(_SYSTEM_DIR))

import chronology as chrono  # noqa: E402
import landmark_projection as lp  # noqa: E402
import landmark_reading as lr  # noqa: E402
import landmarks_interaction as li  # noqa: E402
import temporal_claims as tc  # noqa: E402
import temporal_publication as pub  # noqa: E402
import temporal_receipts as trcpt  # noqa: E402
import temporal_store as store  # noqa: E402
from lifehug_core import INTERACTIONS_DIR  # noqa: E402
from vault_paths import atomic_write_vault_text  # noqa: E402
from temporal_claims import collapsed_text, normalized_timestamp  # noqa: E402

# --------------------------------------------------------------------------
# The mode, the states, the failures
# --------------------------------------------------------------------------

#: The two modes of the ONE landmarks interaction (R3b). `interaction.yaml`
#: carries the same pair as `modes: collect|offer` and
#: `tests/test_landmark_offer.py` pins them equal, so declaring a mode and
#: naming it in code stay one edit.
COLLECT_MODE = "collect"
OFFER_MODE = "offer"
MODES = (COLLECT_MODE, OFFER_MODE)

#: Decision record §5.3 — the six states the interface must distinguish. The
#: OSS side owns three of them as a proposal's own `state`
#: (`needs_clarification`, `proposed`, `failed`); `submitted`, `applying` and
#: `published` are transitions the host renders around a call into this
#: module. Named here in one tuple so 6b's surface and this module cannot
#: drift into two vocabularies.
OFFER_STATES = (
    "submitted", "needs_clarification", "proposed", "applying", "published",
    "failed",
)

#: The states a PROPOSAL file may carry.
PROPOSAL_STATES = ("needs_clarification", "proposed", "failed")

#: §5.3 state 6 — the failure classes a host must be able to tell apart. A
#: caller never sees a collapsed "could not do that right now" from this
#: module: every raise carries one of these on `.code`.
FAILURE_CLASSES = (
    "content_ambiguity", "unsupported_input", "model_failure",
    "service_unavailable", "write_failure",
)


class LandmarkOfferError(ValueError):
    """An offer could not be proposed, applied or retracted.

    ``code`` is one of :data:`FAILURE_CLASSES` — the honest failure class
    §5.3 requires, never a collapsed string.
    """

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code if code in FAILURE_CLASSES else "write_failure"


# --------------------------------------------------------------------------
# Where it lives
# --------------------------------------------------------------------------

#: `vault_contract.json` registers this directory as durable, tracked data:
#: the submitted text lives in it before anything is confirmed, which is the
#: whole of R3's "retained as durable evidence from the moment it is
#: submitted". Receipts are a subdirectory, and a registered directory covers
#: its children (`vault_paths.classify_contract_path`).
OFFERS_DIR = "state/landmarks/offers"
OFFER_RECEIPTS_DIR = f"{OFFERS_DIR}/receipts"

PROPOSAL_SCHEMA_VERSION = 1
OFFER_RECEIPT_SCHEMA_VERSION = 1

#: The source type the submitted text is promoted under when units are
#: applied. An ordinary promoted conversational source in every other
#: respect, so the text enters classification and the listener like any other
#: (`temporal_store.promote_conversational_source`).
OFFER_SOURCE_TYPE = "landmark_offer"
OFFER_CHANNEL = "landmark_offer"

PROPOSAL_ID_PREFIX = "lmo"
UNIT_ID_PREFIX = "lmu"
EVENT_ID_PREFIX = "lme"
RECEIPT_ID_PREFIX = "lmr"
#: v292: a STORY's own id. `groups[]` names its members by id, and a story
#: had none — the only row in the proposal that was identified by its
#: position in a list. Content-addressed like every other id here.
STORY_ID_PREFIX = "lms"
_DIGEST_LENGTH = 24

_ID_RE = re.compile(r"^(lmo|lmu|lme|lmr|lms):[0-9a-f]{%d}$" % _DIGEST_LENGTH)


def _digest(payload: object) -> str:
    return store.payload_sha256(lp.canonical_json(payload))[:_DIGEST_LENGTH]


def valid_id(value: object) -> bool:
    """Whether ``value`` is one of this module's content-addressed ids."""
    return bool(_ID_RE.fullmatch(str(value or "")))


def proposal_path(vault_root: str | Path, proposal_id: str) -> Path:
    if not valid_id(proposal_id) or not str(proposal_id).startswith(
            f"{PROPOSAL_ID_PREFIX}:"):
        raise LandmarkOfferError("unsupported_input",
                                 f"not a proposal id: {proposal_id!r}")
    name = str(proposal_id).split(":", 1)[1]
    return store.store_path(vault_root, f"{OFFERS_DIR}/{name}.json")


def offer_receipt_path(vault_root: str | Path, receipt_id: str) -> Path:
    if not valid_id(receipt_id) or not str(receipt_id).startswith(
            f"{RECEIPT_ID_PREFIX}:"):
        raise LandmarkOfferError("unsupported_input",
                                 f"not a receipt id: {receipt_id!r}")
    name = str(receipt_id).split(":", 1)[1]
    return store.store_path(vault_root, f"{OFFER_RECEIPTS_DIR}/{name}.json")


def retraction_path(vault_root: str | Path, receipt_id: str) -> Path:
    """The retraction beside the receipt. A SEPARATE file, deliberately:
    §5.4's undo keeps the receipt, so nothing rewrites it."""
    return offer_receipt_path(vault_root, receipt_id).with_suffix(
        ".retracted.json")


# --------------------------------------------------------------------------
# The vocabulary of a unit
# --------------------------------------------------------------------------

#: What ONE unit IS, per landmark domain — the word the proposal says out loud
#: ("one residence unit", "one tenure unit", decision record §5.6). Derived
#: from nothing: it is the product's own noun for a domain's entry, and the
#: import-time guard in `tests/test_landmark_offer.py` pins the key set equal
#: to the question set's domains so a tenth domain cannot arrive unnamed.
UNIT_KIND_BY_DOMAIN = {
    "birth": "birth",
    "family": "family_member",
    "residences": "residence",
    "schools": "schooling",
    "partnerships": "relationship",
    "children": "child",
    "work": "tenure",
    "military": "service",
    "losses": "loss",
}

#: The unit kind of text that is not a landmark at all (R3a: non-landmark
#: input is never refused — it is accepted, routed as a story, and the worker
#: says so).
STORY_KIND = "story"

#: Which landmark domain a CLAIM the listener heard belongs to, where the
#: claim's own event kind says so unambiguously. Used only to ask a focused
#: question about a fact no unit could carry — "we moved around a lot after
#: Dad changed jobs" is a real thing the person said, it fabricates no
#: residence and no year, and the honest response is the residence domain's
#: own opening question.
#:
#: Deliberately partial. `birth` is absent because a birth event is the
#: owner's, a sibling's or a child's and the kind alone cannot say which;
#: guessing there is exactly the fabrication this mode exists to avoid.
DOMAIN_BY_EVENT_KIND = {
    "move": "residences",
    "job": "work",
    "school": "schools",
    "graduation": "schools",
    "military": "military",
    "child_born": "children",
    "loss": "losses",
    "death": "losses",
    "first_met": "partnerships",
    "dating_started": "partnerships",
    "married": "partnerships",
    "engaged": "partnerships",
    "separated": "partnerships",
    "divorced": "partnerships",
    "reconciled": "partnerships",
}

#: Words that make a date the person's own approximation rather than their
#: assertion. Read off the QUOTE, never off the model's `confidence` field.
_HEDGE_RE = re.compile(
    r"\b(about|around|roughly|approximately|sometime|somewhere around|"
    r"or so|circa|maybe|probably|i think|thereabouts|ish)\b|~",
    re.IGNORECASE,
)

#: A four-digit year, and the two-digit form people actually write ("'91").
_YEAR_RE = re.compile(r"\b(1[6-9]\d{2}|20\d{2})\b")
_SHORT_YEAR_RE = re.compile(r"['’](\d{2})\b")

#: The month a bound names, in every spelling the person may have written it.
#: v291: `chronology.MONTH_NAMES` is the ONE table (recurring-defect
#: doctrine — this module used to keep a lower-cased copy), and the 3-letter
#: abbreviation is here because `chronology.parse_loose_date` ACCEPTS it: a
#: reader that parses `Jun 1986` and then an evidence guard that only looks
#: for `june` would drop, as unevidenced, the exact date the person typed.
_MONTH_SPELLINGS = tuple(
    (name.lower(), name[:3].lower()) for name in chrono.MONTH_NAMES
)

#: How many characters of context a quote may carry around the words that
#: fixed the fact. A quotation is evidence, not the document.
QUOTE_MAX_CHARS = 400

#: Spans shorter than this, or carrying no letters, are `unrecognized` rather
#: than `stories`: a fragment is not prose somebody offered.
STORY_MIN_WORDS = 3

#: §3.2's own threshold, reused: two dated stretches that overlap by more
#: than this many months are a conflict a person should see before filing.
CONFLICT_OVERLAP_MONTHS = 3


# --------------------------------------------------------------------------
# Spans of the source text — nothing is silently dropped
# --------------------------------------------------------------------------

_SPAN_SPLIT_RE = re.compile(r"(?<=[.!?])\s+|\n{2,}|\n")


def source_spans(text: str) -> list[dict]:
    """Every sentence-ish span of the submitted text, with its own offsets.

    The unit of accounting. Every span of the source ends up under exactly
    one of a unit's quote, `stories` or `unrecognized`, and
    `tests/test_landmark_offer.py` asserts that the three cover the text
    between them — which is what "never silently dropped" has to mean if it
    is to be testable at all.
    """
    body = text or ""
    spans: list[dict] = []
    cursor = 0
    for piece in _SPAN_SPLIT_RE.split(body):
        if piece is None:
            continue
        offset = body.find(piece, cursor) if piece else cursor
        if offset < 0:
            offset = cursor
        cursor = offset + len(piece)
        stripped = piece.strip()
        if not stripped:
            continue
        start = offset + piece.find(stripped)
        spans.append({"text": stripped, "offset": start,
                      "length": len(stripped)})
    return spans


def _overlaps(a_offset: int, a_length: int, b_offset: int, b_length: int) -> bool:
    return a_offset < b_offset + b_length and b_offset < a_offset + a_length


def claim_evidence_text(claim: object) -> str:
    """The QUOTATION a claim carries, whichever accepted shape it is in.

    `general_listener.parse_claims` normalizes a model's ``"evidence": "..."``
    into the contract's own ``[{"quote": "..."}]``, so a caller that reads the
    raw key gets a list where it expected a sentence — and then silently fails
    to find it in the source. One reader, here, for every shape the contract
    accepts.
    """
    value = claim.get("evidence") if isinstance(claim, dict) else claim
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        return str(value.get("quote") or "")
    if isinstance(value, (list, tuple)):
        for item in value:
            text = claim_evidence_text({"evidence": item})
            if text:
                return text
    return ""


def locate(text: str, quote: object, *, hint: int = 0) -> dict | None:
    """One quotation, located in the source. ``None`` when it is not there.

    A quote that is not IN the text is not evidence of anything, so it is
    refused rather than stored with a made-up offset.

    ``hint`` is where to look FIRST, and a caller walking a reading in order
    threads it forward. A real document repeats itself — *"Work: Delaney
    Hardware"* on three consecutive blocks is one employer across three
    stays, not one line read three times — and without the hint all three
    units would land on the first occurrence, leaving two blocks looking
    uncovered. v291 makes the whitespace-tolerant fallback honour the hint
    too: a multi-line block quote never matches `str.find` at all, so before
    this it was the one path that could not be walked forward.
    """
    needle = " ".join(str(quote or "").split())
    if not needle:
        return None
    body = text or ""
    start = max(int(hint), 0)
    index = body.find(needle, start)
    if index < 0:
        index = body.find(needle)
    if index < 0:
        # Whitespace in the source may not match the model's transcription of
        # it; fall back to a whitespace-tolerant search before giving up.
        pattern = re.compile(r"\s+".join(re.escape(word)
                                         for word in needle.split()))
        match = pattern.search(body, start) or pattern.search(body)
        if match is None:
            return None
        return {"text": body[match.start():match.end()][:QUOTE_MAX_CHARS],
                "offset": match.start(), "length": match.end() - match.start()}
    return {"text": needle[:QUOTE_MAX_CHARS], "offset": index,
            "length": len(needle)}


# --------------------------------------------------------------------------
# Stated, or inferred — decided from the bytes, never from the completion
# --------------------------------------------------------------------------

def _year_tokens(value: object) -> set[str]:
    text = str(value or "")
    return set(_YEAR_RE.findall(text))


def date_evidence(record: object, quote: object, source_text: str) -> bool:
    """Does the person's own text carry this date?

    Every bound the record states — ``best``, ``earliest``, ``latest`` — must
    have its YEAR present in the evidence, either in full (``1990``) or in the
    two-digit form people write (``'91``); where the grain is finer than a
    year, the month must be named too. Read off the quote first and the whole
    submitted text second, because a model may quote one sentence of a
    paragraph that dates the fact in the next one.

    This is the whole of decision record §4.2's dividing line, and it is
    deliberately a BYTES question rather than a model question: a completion
    that declares ``basis: stated`` over a year nobody typed is answered here,
    not believed.
    """
    parsed = chrono.from_dict(record)
    if parsed is None:
        return False
    haystacks = [str((quote or {}).get("text") or "") if isinstance(quote, dict)
                 else str(quote or ""), str(source_text or "")]
    present_years: set[str] = set()
    present_short: set[str] = set()
    lowered = ""
    for haystack in haystacks:
        present_years.update(_YEAR_RE.findall(haystack))
        present_short.update(_SHORT_YEAR_RE.findall(haystack))
        lowered += " " + haystack.lower()
    bounds = [value for value in (parsed.best, parsed.earliest, parsed.latest)
              if value]
    if not bounds:
        return False
    for bound in bounds:
        years = _year_tokens(bound)
        if not years:
            return False
        for year in years:
            if year not in present_years and year[2:] not in present_short:
                return False
        if parsed.granularity in ("month", "day"):
            parts = str(bound).split("-")
            if len(parts) < 2:
                return False
            try:
                spellings = _MONTH_SPELLINGS[int(parts[1]) - 1]
            except (ValueError, IndexError):
                return False
            numeric = f"-{parts[1]}"
            if numeric not in lowered and not any(
                    spelling in lowered for spelling in spellings):
                return False
    return True


def _hedged(quote: object) -> bool:
    text = (quote or {}).get("text") if isinstance(quote, dict) else quote
    return bool(_HEDGE_RE.search(str(text or "")))


#: The provenance clause an inferred bound carries. Rendered VERBATIM
#: (`chronology.INFERRED_PROVENANCE_BASIS`), so nothing attributes an
#: inference to the person.
INFERRED_CLAUSE = "read from the text you gave; you did not name this date"


def _closed(payload: dict) -> dict:
    """A bound with BOTH ends, derived from ``best`` when the model gave one.

    A model routinely emits ``{"best": "1990"}`` and nothing else. That is a
    date to a reader and NOT AN INTERVAL to the fold: `entry_stay_interval`
    returns nothing for it, so `same_landmark_stay` cannot tell a second stay
    at an address from the first, and the interval-aware key silently
    collapses two stays into one. The bounds a bare year implies are not a
    guess — `chronology.parse_edtf` derives them from the grain — so they are
    filled here, once, on the way in.
    """
    if payload.get("earliest") and payload.get("latest"):
        return payload
    best = payload.get("best")
    if not best:
        return payload
    implied = chrono.parse_edtf(str(best), basis=payload.get("basis") or "stated")
    if implied is None:
        return payload
    payload["earliest"] = payload.get("earliest") or implied.earliest
    payload["latest"] = payload.get("latest") or implied.latest
    return payload


def _restate(record: object, *, stated: bool, hedged: bool,
             clause: str = INFERRED_CLAUSE) -> dict | None:
    """One date bound, re-based on the evidence. Never on the completion.

    ``clause`` is the sentence an INFERRED bound carries as its verbatim
    provenance. It defaults to :data:`INFERRED_CLAUSE`; R7's inheritance passes
    its own — *"from the dates of the Orchard House stay"* — through this one path
    rather than writing a second provenance mechanism beside it.
    """
    parsed = chrono.from_dict(record)
    if parsed is None:
        return None
    payload = _closed(parsed.to_dict())
    if stated:
        payload["basis"] = "stated"
        confidence = payload.get("confidence")
        if hedged or confidence == "approximate":
            payload["confidence"] = "approximate"
        elif confidence not in ("certain", "approximate"):
            payload["confidence"] = "certain"
        return payload
    payload["basis"] = "anchor"
    payload["confidence"] = "inferred"
    provenance = [dict(item) for item in (payload.get("provenance") or ())]
    entry = {"basis": chrono.INFERRED_PROVENANCE_BASIS, "claim": clause}
    if entry not in provenance:
        provenance.append(entry)
    payload["provenance"] = provenance
    return payload


def _bounds_of(record: dict) -> list[tuple[str, object]]:
    """``[(path, value)]`` for every date bound a landmark record carries."""
    rows: list[tuple[str, object]] = []
    if isinstance(record.get("date"), dict):
        rows.append(("date", record["date"]))
    span = record.get("span")
    if isinstance(span, dict):
        for bound in ("start", "end"):
            if isinstance(span.get(bound), dict):
                rows.append((f"span.{bound}", span[bound]))
    return rows


def _set_bound(record: dict, path: str, value: object) -> None:
    if path == "date":
        record["date"] = value
        return
    record.setdefault("span", {})[path.split(".", 1)[1]] = value


def _date_summary(filed: dict) -> dict:
    """The unit's own date block, read back off the record that just filed.

    ONE reader for both roads into a unit's dates — the evidence guard
    (:func:`rebase_record`) and R7's inheritance (:func:`inherit_dates`) — so
    the two cannot describe the same record differently. It reports what the
    RECORD says and decides nothing: `basis`, `inherited_from` and `clause`
    are the caller's, because only the caller knows which road it took.
    """
    precision = None
    start = end = None
    confidence = "certain"
    estimated = {"start": False, "end": False}
    for path, value in _bounds_of(filed):
        parsed = chrono.from_dict(value)
        if parsed is None:
            continue
        grain = parsed.granularity
        # The COARSEST grain any bound carries. A span whose start is a year
        # and whose end is a month is a YEAR-precision span: reporting the
        # finer of the two would promise a precision the other half does not
        # have, which is the false precision the ladder exists to refuse.
        if precision is None or chrono.GRANULARITIES.index(grain) > \
                chrono.GRANULARITIES.index(precision):
            precision = grain
        if parsed.confidence != "certain":
            confidence = parsed.confidence
        display = parsed.best or parsed.earliest or parsed.latest
        if path in ("date", "span.start"):
            if start is None:
                start = display
            estimated["start"] = (estimated["start"]
                                  or parsed.confidence == "approximate")
        if path == "span.end":
            end = display
            estimated["end"] = parsed.confidence == "approximate"
    return {"start": start, "end": end, "precision": precision,
            "confidence": confidence, "estimated": estimated}


#: The `dates` block's exact key set (§3.2 of the reading plan). The platform
#: transports the proposal verbatim, so this IS the web side's contract; named
#: here in one tuple rather than spelled out at three call sites.
DATE_KEYS = ("start", "end", "precision", "basis", "confidence", "estimated",
             "inherited_from", "clause")

#: The three bases a UNIT's summary may carry. Deliberately not
#: `chronology.BASES`: a bound's basis is `stated` or `anchor` and lives on
#: the record, and this is the summary a person reads — "you said it", "it was
#: read from something else", "nothing was read".
UNIT_BASES = ("stated", "inferred", "none")


def rebase_record(record: dict, quote: object, source_text: str) -> tuple[dict, dict]:
    """``(record, dates)`` — the filed record, and the unit's own date block.

    Every bound is re-based by :func:`date_evidence`. A bound the person's own
    words DO carry files ``basis: stated``; a bound they do not is DROPPED from
    the record with nothing put in its place — never rewritten into a
    confident-looking inference, which is the v290 defect this reverses (D5).
    A record left with no bounds at all summarises ``basis: "none"``, which
    renders "no date read" and earns the domain's own question.
    """
    filed = json.loads(json.dumps(record))
    hedged = _hedged(quote)
    bounds = _bounds_of(filed)
    dropped: list[str] = []
    for path, value in bounds:
        if not date_evidence(value, quote, source_text):
            _drop_bound(filed, path)
            dropped.append(path)
            continue
        restated = _restate(value, stated=True, hedged=hedged)
        if restated is None:
            _drop_bound(filed, path)
            dropped.append(path)
            continue
        _set_bound(filed, path, restated)
    summary = _date_summary(filed)
    summary["basis"] = "stated" if _bounds_of(filed) else "none"
    if summary["basis"] == "none":
        summary["confidence"] = None
    summary["inherited_from"] = None
    summary["clause"] = None
    return filed, {key: summary[key] for key in DATE_KEYS}


def _drop_bound(record: dict, path: str) -> None:
    """Remove one bound the person's text does not carry, and its container
    when that empties it."""
    if path == "date":
        record.pop("date", None)
        return
    span = record.get("span")
    if isinstance(span, dict):
        span.pop(path.split(".", 1)[1], None)
        if not span:
            record.pop("span", None)


def inherit_dates(unit: dict, parent: dict, *,
                  framework_root: str | Path | None = None) -> bool:
    """R7 rule 4: a dateless unit takes its parent span's dates, and says so.

    A school named inside a stay belongs to that stay and is dated by it. The
    bounds are copied onto the child's record through :func:`_restate` — so
    they carry ``basis: anchor``, ``confidence: inferred`` and the verbatim
    provenance clause *"from the dates of the <subject> <stay|tenure|
    schooling>"* — and the child's summary reads ``basis: "inferred"`` with
    ``inherited_from`` naming the unit it came from.

    Returns whether anything was inherited. It refuses in two cases, both
    deliberately: a child whose domain records ONE DATE rather than a stretch
    (a birth, a child, a loss) — a stay's span is not a person's birthday, and
    putting one there is exactly the fabrication R6 exists to end — and a
    parent that has no dates of its own to give.
    """
    try:
        row = li.domain_row(unit["domain"], framework_root=framework_root)
    except li.LandmarkInteractionError:
        return False
    if lr.date_shape_for(row) != "span":
        return False
    bounds = dict(_bounds_of(parent.get("record") or {}))
    start = bounds.get("span.start") or bounds.get("date")
    end = bounds.get("span.end")
    if start is None and end is None:
        return False
    subject = parent.get("subject") or "that"
    clause = (f"from the dates of the {subject} "
              f"{lr.span_noun(parent.get('domain'))}")
    span: dict = {}
    for name, value in (("start", start), ("end", end)):
        if value is None:
            continue
        restated = _restate(value, stated=False, hedged=False, clause=clause)
        if restated is not None:
            span[name] = restated
    if not span:
        return False
    unit["record"]["span"] = span
    summary = _date_summary(unit["record"])
    summary["basis"] = "inferred"
    summary["confidence"] = "inferred"
    summary["inherited_from"] = {"unit_id": parent.get("unit_id"),
                                 "subject": subject,
                                 "kind": parent.get("kind")}
    summary["clause"] = clause
    unit["dates"] = {key: summary[key] for key in DATE_KEYS}
    return True


# --------------------------------------------------------------------------
# Identity
# --------------------------------------------------------------------------

def derive_unit_id(*, domain: object, kind: object, subject: object,
                   dates: object, quote: object) -> str:
    """One unit's content-addressed identity.

    Domain, kind, subject, the dates as the person's words fixed them, and the
    quotation they came from. Two proposals over the same text yield the same
    ids; a unit whose date or evidence changed is a DIFFERENT unit, which is
    what makes "apply exactly these" safe to retry.
    """
    dates_row = dates if isinstance(dates, dict) else {}
    quote_row = quote if isinstance(quote, dict) else {}
    payload = {
        "domain": collapsed_text(domain),
        "kind": collapsed_text(kind),
        "subject": collapsed_text(subject).casefold(),
        "start": collapsed_text(dates_row.get("start")),
        "end": collapsed_text(dates_row.get("end")),
        "precision": collapsed_text(dates_row.get("precision")),
        "basis": collapsed_text(dates_row.get("basis")),
        "quote": collapsed_text(quote_row.get("text")),
    }
    return f"{UNIT_ID_PREFIX}:{_digest(payload)}"


def derive_event_id(*, kind: object, subject: object, date: object,
                    quote: object) -> str:
    """One EVENT's content-addressed identity (v291).

    The same shape :func:`derive_unit_id` uses and for the same reason: two
    readings of the same submission name the same events, so 6g's filing is
    safe to retry. What happened, to whom, when, and the words it came from.
    """
    quote_row = quote if isinstance(quote, dict) else {}
    date_row = date if isinstance(date, dict) else {}
    payload = {
        "kind": collapsed_text(kind),
        "subject": collapsed_text(subject).casefold(),
        "date": collapsed_text(date_row.get("best")),
        "quote": collapsed_text(quote_row.get("text")),
    }
    return f"{EVENT_ID_PREFIX}:{_digest(payload)}"


def derive_story_id(*, offset: object, length: object, quote: object) -> str:
    """One STORY's content-addressed identity (v292).

    A story is a span of the person's own text that no unit and no event
    covers, so its identity is that span: where it starts, how long it is, and
    what it says. The same shape :func:`derive_event_id` uses, and for the same
    reason — `groups[]` names its members by id, and 6g's filing has to be able
    to say which story it filed and which one a retraction undoes.
    """
    payload = {
        "offset": int(offset or 0),
        "length": int(length or 0),
        "quote": collapsed_text(quote),
    }
    return f"{STORY_ID_PREFIX}:{_digest(payload)}"


def derive_proposal_id(text: object, generation: object) -> str:
    """The proposal's identity: the submitted text, against the vault
    generation it was read against.

    The generation is in it deliberately. The same paragraph offered again
    after the timeline moved is a NEW reading — the known entries the recorder
    saw are different, so the duplicates and conflicts it reports are
    different — and pretending otherwise would hand somebody yesterday's
    proposal for today's vault.
    """
    payload = {"text": store.normalize_payload(str(text or "")),
               "generation": int(generation or 0)}
    return f"{PROPOSAL_ID_PREFIX}:{_digest(payload)}"


def derive_receipt_id(proposal_id: object, unit_ids: object) -> str:
    """The apply receipt's identity: the proposal, and exactly which units.

    Applying the same units of the same proposal twice lands on the same
    receipt id and therefore on the same file; applying a SECOND, larger set
    is a second act with a receipt of its own, and the units the two share
    were already filed under their own ``(proposal_id, unit_id)`` digests, so
    nothing files twice either way.
    """
    payload = {"proposal_id": collapsed_text(proposal_id),
               "unit_ids": sorted({collapsed_text(value)
                                   for value in (unit_ids or ()) if value})}
    return f"{RECEIPT_ID_PREFIX}:{_digest(payload)}"


def landmark_opportunity_id(*, domain: object, subject: object, kind: object,
                            event: object = None) -> str:
    """Cut 5a's opportunity identity: ``domain`` + ``kind`` + ``subject``.

    A NAMED DOOR onto `landmark_opportunities.opportunity_id`, never a second
    definition of it (ADR 0021, ADR 0032). This exists so the offer side can
    say what it is addressing at its own call sites; the digest is 5a's, and
    `tests/test_landmark_offer.py` pins the two equal.
    """
    import landmark_opportunities as lop  # noqa: PLC0415

    return lop.opportunity_id(domain=domain, kind=kind, subject=subject,
                              event=event)


# --------------------------------------------------------------------------
# The deterministic first pass (R4: the parse kept, the product gone)
# --------------------------------------------------------------------------

def _grammar_block_quote(text: str, block: dict, *, cursor: int) -> dict | None:
    return locate(text, block.get("raw"), hint=cursor)


def _date_dict(bound: object, *, ongoing: bool = False) -> dict | None:
    """One grammar-parsed bound as a `chronology` record dict."""
    if ongoing or not isinstance(bound, dict):
        return None
    edtf = bound.get("edtf")
    if not edtf:
        return None
    parsed = chrono.parse_edtf(str(edtf), basis="stated")
    if parsed is None:
        return None
    payload = parsed.to_dict()
    grain = bound.get("grain")
    if grain in chrono.GRANULARITIES:
        payload["granularity"] = grain
    payload["confidence"] = "certain"
    return payload


def grammar_units(text: str) -> tuple[list[dict], set[int]]:
    """``(units, consumed_offsets)`` — the model-free extractor.

    The deterministic block grammar runs FIRST over text it fully matches
    (decision record §5.6, last example: *"anything it does not recognize goes
    to the listener rather than being discarded"*). A block qualifies only
    when it parsed cleanly AND every one of its lines was a field the grammar
    knows — a block with a stray prose line is handed on whole, because half a
    parse is a guess.

    Zero model calls, by construction: nothing on this path consults a
    completion, and a 30-block residence document therefore proposes 30 units
    for the cost of a string split.
    """
    import go_dig_writer as _writer  # noqa: PLC0415 — internal extractor only

    body = text or ""
    plan = _writer.plan_import(body)
    blocks = plan["blocks"]
    clean = {block["ordinal"]: block for block in blocks
             if not block["errors"] and not block["note_lines"]
             and block["status"] == "ready"}
    units: list[dict] = []
    consumed: set[int] = set()
    cursor = 0
    for block in blocks:
        if block["ordinal"] not in clean:
            continue
        quote = _grammar_block_quote(body, block, cursor=cursor)
        if quote is None:
            continue
        cursor = quote["offset"] + quote["length"]
        consumed.add(block["ordinal"])
        place = block.get("place_name")
        dates = block.get("dates") or {}
        if not place:
            consumed.discard(block["ordinal"])
            continue
        record: dict = {"domain": "residences", "label": place, "city": place}
        if block.get("address"):
            record["address"] = block["address"]
        if block.get("nickname"):
            record["nickname"] = block["nickname"]
        start = _date_dict((dates or {}).get("start"))
        end = _date_dict((dates or {}).get("end"),
                         ongoing=bool((dates.get("end") or {}).get("ongoing")))
        span = {key: value for key, value in (("start", start), ("end", end))
                if value}
        if span:
            record["span"] = span
        validated = li.validate_landmark(record)
        if validated is None:
            consumed.discard(block["ordinal"])
            continue
        units.append(_unit(domain="residences", record=validated,
                           subject=place, quote=quote, source_text=body,
                           extractor="grammar"))
    return units, consumed


# --------------------------------------------------------------------------
# One unit
# --------------------------------------------------------------------------

def _subject_of(record: dict, domain: str) -> str:
    try:
        row = li.domain_row(domain)
    except li.LandmarkInteractionError:
        row = None
    if row is not None:
        named = li.identity_named(record, row)
        if named:
            return named
    for field in li.IDENTITY_FIELDS:
        value = record.get(field)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _unit(*, domain: str, record: dict, subject: str, quote: object,
          source_text: str, extractor: str, within: object = None,
          names: object = None) -> dict:
    filed, dates = rebase_record(record, quote, source_text)
    kind = UNIT_KIND_BY_DOMAIN.get(domain, domain)
    return {
        "unit_id": derive_unit_id(domain=domain, kind=kind, subject=subject,
                                  dates=dates, quote=quote),
        "domain": domain,
        "kind": kind,
        "subject": subject,
        "entity_candidates": [],
        "dates": dates,
        "quote": quote,
        # R7: the unit this one belongs to, as that unit's own `unit_id` —
        # never the reading's short-lived ref, which means nothing once the
        # proposal is written.
        "within": collapsed_text(within) or None,
        # The place's own NAMES (E-L2c): nickname, city, address, place_ref,
        # link. They ride on the record too; carried here as well so a host
        # can render "the blue house · Riverbend · 12 Elm Street" without
        # knowing which of them are ladder rungs and which are additive.
        "names": dict(names or {}),
        "duplicates": [],
        "conflicts": [],
        "questions": [],
        "auto_file_eligible": False,
        "extractor": extractor,
        "record": filed,
    }


def _remint(unit: dict) -> dict:
    """The unit's id, recomputed after its dates moved (R7 inheritance)."""
    unit["unit_id"] = derive_unit_id(
        domain=unit["domain"], kind=unit["kind"], subject=unit["subject"],
        dates=unit["dates"], quote=unit["quote"])
    return unit


#: The exact key set of a unit. Named so a reader — and 6b's typed surface —
#: has one place to read the contract from.
UNIT_KEYS = (
    "unit_id", "domain", "kind", "subject", "entity_candidates", "dates",
    "quote", "within", "names", "duplicates", "conflicts", "questions",
    "auto_file_eligible", "extractor", "record",
)


# --------------------------------------------------------------------------
# What the vault already knows: duplicates, conflicts, entity candidates
# --------------------------------------------------------------------------

def entry_id(domain: object, entry_key: object) -> str:
    return f"{collapsed_text(domain)}/{collapsed_text(entry_key)}"


def annotate_against_known(unit: dict, landmarks: object) -> dict:
    """Duplicates and conflicts against what is already filed.

    * A **duplicate** is an entry of the same identity that the merge would
      fold this record INTO — same key, and `same_landmark_stay` says the two
      tellings are one stay. Filing it again adds nothing.
    * A **second stay** at a known identity is neither a duplicate nor a
      conflict. It is a second entry, and the interval-aware key
      (`landmarks_interaction.landmark_entry_key` + `same_landmark_stay`) is
      what makes it one — which is exactly why the recorder is shown the
      domain's filed entries before it proposes anything.
    * A **conflict** is a dated stretch that overlaps a DIFFERENT identity's
      by more than :data:`CONFLICT_OVERLAP_MONTHS`, or a record that
      contradicts a standing "that never happened".
    """
    domain = unit["domain"]
    try:
        row = li.domain_row(domain)
    except li.LandmarkInteractionError:
        return unit
    record = unit["record"]
    key = li.landmark_entry_key(record, row)
    mine = li.entry_stay_interval(record)
    duplicates: list[str] = []
    conflicts: list[dict] = []
    for existing in li.landmark_entries(landmarks, domain):
        existing_key = li.landmark_entry_key(existing, row)
        if li.is_none_entry(existing, row) and li.asserts_happened(record):
            conflicts.append({
                "entry_id": entry_id(domain, existing_key),
                "kind": "contradicts_none",
                "detail": f"{domain} is filed as never having happened",
            })
            continue
        if existing_key == key:
            if li.same_landmark_stay(existing, record, row):
                duplicates.append(entry_id(domain, existing_key))
            continue
        theirs = li.entry_stay_interval(existing)
        if mine and theirs and chrono.overlap_months(mine, theirs) > \
                CONFLICT_OVERLAP_MONTHS:
            conflicts.append({
                "entry_id": entry_id(domain, existing_key),
                "kind": "overlapping_span",
                "detail": (f"overlaps {li.entry_name(existing, row) or 'a filed entry'} "
                           f"by more than {CONFLICT_OVERLAP_MONTHS} months"),
            })
    unit["duplicates"] = sorted(dict.fromkeys(duplicates))
    unit["conflicts"] = sorted(conflicts, key=lambda row_: (row_["kind"],
                                                            row_["entry_id"]))
    return unit


#: Which roster type a domain's subject is an entity of. Read from the
#: question set's own `identity_kind` (`landmarks_interaction.IDENTITY_KINDS`)
#: rather than re-declared, with the two roster types that exist
#: (`entity_roster.ENTITY_TYPES` for people and places,
#: `roster_relations.ORGANIZATION_ENTITY_TYPE` for organizations).
ROSTER_TYPE_BY_IDENTITY_KIND = {
    "person": "person",
    "place": "place",
    "organization": "organization",
    "relationship_edge": "person",
    "episode": None,
}


def annotate_entities(unit: dict, roster: object) -> dict:
    """Roster matches for the unit's subject, with an honest confidence.

    ``match`` is the same name, normalized; ``possible`` is an alias of some
    other entity — which is a thing to SHOW, never to resolve silently
    (`roster_relations.alias_decision` owns that judgment); ``new`` is a name
    the roster has never seen, proposed rather than minted.
    """
    import identity_resolution as ir  # noqa: PLC0415
    import roster_relations as rr  # noqa: PLC0415

    subject = unit.get("subject") or ""
    if not subject:
        return unit
    try:
        row = li.domain_row(unit["domain"])
    except li.LandmarkInteractionError:
        return unit
    roster_type = ROSTER_TYPE_BY_IDENTITY_KIND.get(row.get("identity_kind"))
    if roster_type is None:
        return unit
    snapshot = (roster or {}).get(roster_type) if isinstance(roster, dict) else None
    entities = rr.roster_entities(snapshot)
    key = ir.normalized_mention_key(subject)
    candidates: list[dict] = []
    for entity in entities:
        name = entity.get("name")
        if ir.normalized_mention_key(name) == key:
            candidates.append({"ref": rr.entity_ref(roster_type, entity),
                               "name": name, "type": roster_type,
                               "confidence": "match"})
            continue
        aliases = entity.get("aliases")
        if isinstance(aliases, list) and any(
                ir.normalized_mention_key(alias) == key for alias in aliases):
            candidates.append({"ref": rr.entity_ref(roster_type, entity),
                               "name": name, "type": roster_type,
                               "confidence": "possible"})
    if not candidates:
        candidates.append({"ref": None, "name": subject, "type": roster_type,
                           "confidence": "new"})
    unit["entity_candidates"] = candidates
    return unit


# --------------------------------------------------------------------------
# Questions — asked, never guessed
# --------------------------------------------------------------------------

def unit_questions(unit: dict, landmarks: object) -> list[str]:
    """The focused clarifications MATERIAL ambiguity earns. Nothing else.

    §5.3's "needs clarification" is about a person, place, event,
    relationship or date that cannot be RESOLVED — not about a ladder rung
    that is merely unfilled. A residence with a city and a span is a good
    landmark whether or not anybody ever names the street, and asking for the
    address on a confirmation screen would turn the proposal into the form
    this Interaction exists not to be. So exactly three things ask:

    * a unit whose domain names a subject and whose subject is missing;
    * a unit whose domain dates its entries and that carries no date at all —
      ``basis: "none"``, R7 rule 5 — asked with
      `landmarks_interaction.event_questions`, so a partnership asks its three
      distinct events by name rather than one flattened "when";
    * a date this module INFERRED from something OTHER than a span it belongs
      to. A date the person did not say is the one thing that must be checked
      before it is filed — and it is checked with the domain's OWN question,
      never by naming the inferred value and inviting agreement with it.
      Showing an inference on the confirmation screen is honest (the leaf
      requires it, marked as an inference); asking *"was it 1991?"* is the
      suggestive-interviewing hazard ADR 0025 named, and it stays banned in
      this mode exactly as in the other one.

    A date INHERITED from the stay a unit sits inside (R7 rule 4) is
    deliberately NOT asked about. It carries its own provenance clause on the
    card — *"from the dates of the Orchard House stay"* — so the person can see
    exactly where it came from and correct it there; asking the schooling
    ladder's opening question once per school in a thirty-block document would
    turn a reading into the interrogation this Interaction refuses to be.
    """
    try:
        row = li.domain_row(unit["domain"])
    except li.LandmarkInteractionError:
        return []
    record = unit["record"]
    subject = unit.get("subject") or ""
    asks: list[str] = []
    if li.identity_rung(row) and not li.identity_named(record, row):
        opening = li.next_rung((), row)
        if opening is not None:
            asks.append(opening["text"])
    elif not _bounds_of(record) and li.date_semantics(row):
        asks.extend(question["text"] for question
                    in li.event_questions(row, subject))
    if (unit["dates"].get("basis") == "inferred"
            and not unit["dates"].get("inherited_from")):
        events = [question["text"] for question
                  in li.event_questions(row, subject)]
        if events:
            asks.extend(events)
        else:
            opening = li.next_rung((), row)
            if opening is not None:
                asks.append(opening["text"])
    return list(dict.fromkeys(asks))


def open_event_claims(events: object) -> list[dict]:
    """The reading's UNDATED, UNPLACED events, in the shape
    :func:`open_claim_questions` reads.

    *"We moved around a lot after Dad changed jobs"* is a real thing somebody
    said about moving. It fabricates no residence and no year, so the reading
    carries it as an event with no date and no ``within`` — and that pair is
    exactly what earns the domain's own opening question. An event that HAS a
    date needs no question, and one held inside a stay is already placed.
    """
    return [{"event_kind": row.get("kind"),
             "evidence": (row.get("quote") or {}).get("text")}
            for row in (events or ())
            if isinstance(row, dict) and not row.get("date")
            and not row.get("within")]


def open_claim_questions(claims: object, units: object, landmarks: object,
                         source_text: str) -> list[dict]:
    """One question per datable thing the person said that no unit carries.

    *"We moved around a lot after Dad changed jobs"* fabricates no residence
    and no year (§5.6). It is a real claim about moving, so the honest
    response is the residences ladder's own opening question — asked once,
    against the domain, from `next_rung`, and never with a year in it.
    """
    covered: list[tuple[int, int]] = [
        (unit["quote"]["offset"], unit["quote"]["length"])
        for unit in (units or ())
        if isinstance(unit.get("quote"), dict)
    ]
    asked: dict[str, dict] = {}
    for claim in claims or ():
        if not isinstance(claim, dict):
            continue
        domain = DOMAIN_BY_EVENT_KIND.get(collapsed_text(claim.get("event_kind")))
        if domain is None or domain in asked:
            continue
        located = locate(source_text, claim_evidence_text(claim))
        if located is not None and any(
                _overlaps(located["offset"], located["length"], offset, length)
                for offset, length in covered):
            continue
        try:
            row = li.domain_row(domain)
        except li.LandmarkInteractionError:
            continue
        rung = li.next_rung(li.landmark_entries(landmarks, domain), row)
        if rung is None:
            continue
        asked[domain] = {"domain": domain, "text": rung["text"],
                         "quote": located,
                         "why": "you mentioned this but did not say when or where"}
    return [asked[key] for key in sorted(asked)]


# --------------------------------------------------------------------------
# The vault this offer belongs to
# --------------------------------------------------------------------------

def _write_json(vault_root: str | Path, path: Path, payload: dict) -> Path:
    """One writer for the three files this module owns, atomic and no-follow.

    Every vault write in this package goes through `vault_paths`'
    symlink-refusing authority — `tests/test_v120_vault_only.py` sweeps the
    AST of every module in `system/` to keep it that way — and the bytes are
    `landmark_projection.canonical_json`'s, so two runs over identical inputs
    produce identical files.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        atomic_write_vault_text(path, lp.canonical_json(payload) + "\n",
                                vault_root=Path(vault_root))
    except (OSError, ValueError) as exc:
        raise LandmarkOfferError("write_failure", str(exc)) from exc
    return path


def _bound_vault(vault_root: str | Path) -> Path:
    """The vault, checked against the landmark store's own binding.

    `timeline.LANDMARKS_STORE` is the seam every caller and every test
    rebinds, and `timeline._projection_vault_root` derives the substrate root
    FROM it precisely so a drawing and its evidence cannot land in two
    different vaults. This module writes proposals beside that substrate and
    files through that writer, so it refuses rather than straddles.
    """
    import timeline  # noqa: PLC0415

    root = Path(str(vault_root)).expanduser().resolve()
    bound = Path(str(timeline._projection_vault_root())).expanduser().resolve()  # noqa: SLF001
    if root != bound:
        raise LandmarkOfferError(
            "write_failure",
            f"landmark offers write beside the landmark store; this process is "
            f"bound to {bound}, not {root}")
    return root


def _known_landmarks() -> dict:
    import timeline  # noqa: PLC0415

    return timeline.load_landmarks()


def _roster_snapshot() -> dict:
    import entity_roster  # noqa: PLC0415

    snapshot: dict = {}
    for roster_type in ("person", "place", "organization"):
        try:
            snapshot[roster_type] = entity_roster.load_roster(roster_type)
        except Exception:  # noqa: BLE001 — a roster problem is "no roster"
            snapshot[roster_type] = {"entities": []}
    return snapshot


# --------------------------------------------------------------------------
# propose
# --------------------------------------------------------------------------

def _auto_file_eligible(unit: dict) -> bool:
    """The existing extraction policy, applied to a unit.

    Explicit (every bound the person's own words carry), high-confidence
    (nothing hedged), nothing already filed that this would merge into, and
    nothing it contradicts. It depends on the EVIDENCE, never on a model
    saying it is confident (§5.3), and the owner has not asked for
    auto-filing — so this is a flag a host may read, not a permission this
    module exercises. :func:`apply` files what a person named and nothing
    else.

    An unfilled ladder rung is deliberately NOT disqualifying: "I lived in
    Mesa from 1990 to 1992" is a complete, explicit residence whether or not
    anybody ever names the street, and the ladder will ask for the address in
    its own time through the collect mode.
    """
    dates = unit.get("dates") or {}
    return bool(
        dates.get("basis") == "stated"
        and dates.get("confidence") == "certain"
        and dates.get("start")
        and not unit.get("duplicates")
        and not unit.get("conflicts")
    )


def _quote_spans(rows: object) -> list[tuple[int, int]]:
    return [(row["quote"]["offset"], row["quote"]["length"])
            for row in (rows or ())
            if isinstance(row, dict) and isinstance(row.get("quote"), dict)]


def _partition_text(source_text: str, units: list[dict],
                    events: object = (),
                    told: object = ()) -> tuple[list[dict], list[dict]]:
    """``(stories, unrecognized)`` — every span no unit and no EVENT covers.

    R3a: non-landmark input is never refused. Prose the person offered is a
    STORY and says so; a fragment with nothing to route is ``unrecognized``
    and is still carried, because a proposal that quietly loses half a paste
    is the failure this whole mode replaces.

    ``events`` count as coverage exactly as units do (v291): "Wren was born
    12 May 1991" is read, filed and shown, and a coverage invariant that
    called it uncovered would report the one thing the reading got right as
    the thing it dropped.

    ``told`` is the reading's OWN stories — the model's `{quote, within}`
    rows. The span partition stays the authority on WHICH spans are stories
    (it is the thing the coverage invariant is measured against), and the
    reading supplies the one thing a partition cannot know: which stay a story
    belongs to (R7).
    """
    covered = _quote_spans(units) + _quote_spans(events)
    within_by_span = [(row["quote"]["offset"], row["quote"]["length"],
                       row.get("within"))
                      for row in (told or ())
                      if isinstance(row, dict)
                      and isinstance(row.get("quote"), dict)]
    stories: list[dict] = []
    unknown: list[dict] = []
    for span in source_spans(source_text):
        if any(_overlaps(span["offset"], span["length"], offset, length)
               for offset, length in covered):
            continue
        words = [word for word in re.split(r"\s+", span["text"]) if word]
        if len(words) >= STORY_MIN_WORDS and re.search(r"[A-Za-z]", span["text"]):
            within = next(
                (value for offset, length, value in within_by_span
                 if value and _overlaps(span["offset"], span["length"],
                                        offset, length)), None)
            stories.append({**span, "route": STORY_KIND, "within": within,
                            "story_id": derive_story_id(
                                offset=span["offset"], length=span["length"],
                                quote=span["text"])})
        else:
            unknown.append(dict(span))
    return stories, unknown


#: The `events` list's exact key set (§3.2). `filing` says which road 6g takes
#: with it — a DATED event becomes a `TemporalClaim`, an undated one a moment
#: held inside the unit it belongs to.
EVENT_KEYS = ("event_id", "text", "kind", "subject_mention", "date", "within",
              "quote", "filing")


def _event_row(read_event: object, by_ref: dict, source_text: str = "") -> dict:
    """One reading event as the proposal carries it (§3.2 item 3).

    The date is re-read against the person's own bytes, exactly as a unit's
    bounds are (:func:`date_evidence`, §3.1 rule 2): a year the submission does
    not carry is DROPPED and the event files as a moment instead of as a dated
    claim. `filing` therefore says what will actually happen to it, which is
    the only thing that makes it safe for `apply` to act on.
    """
    date = read_event.date
    parent = by_ref.get(read_event.within) if read_event.within else None
    slim = None
    if isinstance(date, dict) and date_evidence(date, read_event.quote,
                                                source_text):
        slim = {"best": date.get("best"),
                "granularity": date.get("granularity"),
                "confidence": date.get("confidence")}
    return {
        # The id is derived from what the PROPOSAL carries, never from what
        # the completion said: an event whose date the text does not carry is
        # a different event from one whose date it does.
        "event_id": derive_event_id(kind=read_event.kind,
                                    subject=read_event.subject_mention,
                                    date=slim, quote=read_event.quote),
        "text": read_event.text,
        "kind": read_event.kind,
        "subject_mention": read_event.subject_mention,
        "date": slim,
        "within": (parent or {}).get("unit_id"),
        "quote": read_event.quote,
        "filing": "claim" if slim else "moment",
    }


#: The `groups[]` list's exact key set (§3.2 of the reading plan) and the three
#: kinds of thing a group can hold. Named here so a host — and 6j's renderer —
#: reads the contract from one place.
GROUP_KEYS = ("unit_id", "members")
MEMBER_KINDS = ("unit", "event", "story")


def _text_offset(row: object) -> int:
    """Where a unit, an event or a story starts in the submitted text.

    A unit and an event carry a located ``quote``; a story IS a located span
    and carries ``offset`` itself. One reader for the three, because `groups`
    orders all three against the same axis — the person's own text.
    """
    if not isinstance(row, dict):
        return 1 << 30
    quote = row.get("quote")
    if isinstance(quote, dict) and isinstance(quote.get("offset"), int):
        return quote["offset"]
    if isinstance(row.get("offset"), int):
        return row["offset"]
    return 1 << 30


def _head_unit_id(unit: dict, by_id: dict) -> str | None:
    """The TOP-LEVEL unit this one belongs to, walking ``within`` upward.

    Transitive by design (§3.2): a school inside a stay is the stay's member,
    and so is an event inside that school — one group per stay is what the
    owner asked for ("~30 cards, not ~90 rows"), not one card per nesting
    level. The walk is bounded by a seen-set so a caller that skipped
    `landmark_reading.parse_reading`'s cycle cut degrades to "no head" rather
    than looping forever.
    """
    cursor = unit
    seen = {cursor.get("unit_id")}
    while cursor is not None and cursor.get("within"):
        parent = by_id.get(cursor["within"])
        if parent is None or parent.get("unit_id") in seen:
            return None
        seen.add(parent.get("unit_id"))
        cursor = parent
    return cursor.get("unit_id") if cursor is not None else None


def build_groups(units: object, events: object, stories: object) -> list[dict]:
    """§3.2's ``groups[]`` — the proposal read BY STAY rather than as a list.

    Every unit with ``within: None`` heads exactly one group, in text order.
    Its ``members`` are the units, events and stories whose ``within`` resolves
    to it TRANSITIVELY — a school inside a stay is a member, and so is an event
    inside that school — each named ``{kind, id}`` and ordered by where it sits
    in the person's own text. A trailing ``{unit_id: None}`` group holds the
    events and stories that belong to nothing, so a renderer that walks
    `groups` alone never loses a row (`unrecognized` spans are not members:
    nothing was made of them, and they render as themselves).

    This is what 6j renders and what 6g files against: one promoted slice per
    group, so a moment read inside a stay cites that stay's own words and not
    the whole submission.
    """
    unit_rows = [row for row in (units or ()) if isinstance(row, dict)
                 and row.get("unit_id")]
    by_id = {row["unit_id"]: row for row in unit_rows}
    members: dict[str, list[dict]] = {}
    order: dict[str, tuple] = {}
    heads: list[dict] = []
    for row in unit_rows:
        if row.get("within"):
            continue
        members[row["unit_id"]] = []
        order[row["unit_id"]] = (_text_offset(row), row["unit_id"])
        heads.append(row)
    loose: list[dict] = []

    def _place(kind: str, identity: object, offset: int, head: object) -> None:
        row = {"kind": kind, "id": collapsed_text(identity)}
        bucket = members.get(collapsed_text(head)) if head else None
        (loose if bucket is None else bucket).append((offset, row))

    for row in unit_rows:
        if not row.get("within"):
            continue
        _place("unit", row["unit_id"], _text_offset(row),
               _head_unit_id(row, by_id))
    for row in (events or ()):
        if not isinstance(row, dict) or not row.get("event_id"):
            continue
        parent = by_id.get(row.get("within"))
        head = _head_unit_id(parent, by_id) if parent is not None else None
        _place("event", row["event_id"], _text_offset(row), head)
    for row in (stories or ()):
        if not isinstance(row, dict) or not row.get("story_id"):
            continue
        parent = by_id.get(row.get("within"))
        head = _head_unit_id(parent, by_id) if parent is not None else None
        _place("story", row["story_id"], _text_offset(row), head)

    groups = [{"unit_id": head["unit_id"],
               "members": [row for _offset, row
                           in sorted(members[head["unit_id"]],
                                     key=lambda item: (item[0], item[1]["kind"],
                                                       item[1]["id"]))]}
              for head in sorted(heads, key=lambda row: order[row["unit_id"]])]
    if loose:
        groups.append({"unit_id": None,
                       "members": [row for _offset, row
                                   in sorted(loose,
                                             key=lambda item: (item[0],
                                                               item[1]["kind"],
                                                               item[1]["id"]))]})
    return groups


def _units_from_reading(reading: object, source_text: str, *,
                        framework_root: str | Path | None = None) -> tuple[list[dict], dict]:
    """``(units, by_ref)`` — the reading's units, in text order, with R7's
    inheritance already applied.

    Parents are built before their children (the reading's ``within`` graph is
    acyclic by the time :func:`landmark_reading.parse_reading` returns), so a
    child that inherits its parent's dates can name the parent's own
    ``unit_id`` and be re-minted over the dates it ended up with.
    """
    drafts = list(getattr(reading, "units", ()) or ())
    by_ref: dict[str, dict] = {}
    units: list[dict] = []
    pending = list(drafts)
    while pending:
        progressed = False
        remaining = []
        for read_unit in pending:
            parent_ref = read_unit.within
            if parent_ref and parent_ref not in by_ref:
                remaining.append(read_unit)
                continue
            parent = by_ref.get(parent_ref) if parent_ref else None
            unit = _unit(domain=read_unit.domain, record=read_unit.record,
                         subject=read_unit.subject, quote=read_unit.quote,
                         source_text=source_text, extractor="reading",
                         within=(parent or {}).get("unit_id"),
                         names=read_unit.names)
            if parent is not None and unit["dates"].get("basis") == "none":
                if inherit_dates(unit, parent, framework_root=framework_root):
                    _remint(unit)
            by_ref[read_unit.ref] = unit
            units.append(unit)
            progressed = True
        pending = remaining
        if not progressed:
            # Unreachable while `parse_reading` guarantees an acyclic graph;
            # kept so a future caller that skips it degrades to "no parent"
            # rather than looping forever.
            for read_unit in pending:
                unit = _unit(domain=read_unit.domain, record=read_unit.record,
                             subject=read_unit.subject, quote=read_unit.quote,
                             source_text=source_text, extractor="reading",
                             names=read_unit.names)
                by_ref[read_unit.ref] = unit
                units.append(unit)
            break
    return units, by_ref


def propose(text: str, vault_root: object = None, *, call,
            model: object = None, now: object = None,
            write: bool = True, landmarks: object = None,
            roster: object = None, generation: object = None,
            framework_root: str | Path | None = None) -> dict:
    """Read volunteered text; propose landmark units. Files NOTHING.

    **ONE reading (R6, R9).** ``call(prompt, model) -> str`` is injected
    exactly as the recorder's is, so this loop is testable, replayable and
    host-routable — and it is called ONCE, with the prompt
    `landmark_reading.build_reading_prompt` composes. No deterministic grammar
    runs first and no second pass re-reads the text: the interaction sees the
    whole submission with the whole context and returns one reading, and
    everything after that is deterministic.

    Writes exactly one file — ``state/landmarks/offers/<proposal_id>.json`` —
    carrying the submitted text, the units, the events, the stories, the spans
    nothing recognized and the questions. That file IS R3's durable evidence:
    it exists before anybody confirms anything, and a failure writes it too, so
    the input is never the thing that gets lost.

    ``landmarks``, ``roster`` and ``generation`` are the vault context. They
    default to this vault's, and supplying ALL THREE with ``write=False``
    makes the whole function pure over data the caller holds — which is how
    the eval harness replays recorded completions against fixed context
    without a vault at all.
    """
    body = str(text or "")
    if not body.strip():
        raise LandmarkOfferError("unsupported_input",
                                 "an offer needs some text")
    supplied = (landmarks is not None and roster is not None
                and generation is not None)
    root = None if (not write and supplied) else _bound_vault(vault_root)
    generation = (pub.published_generation(root) if generation is None
                  else int(generation))
    proposal_id = derive_proposal_id(body, generation)
    landmarks = _known_landmarks() if landmarks is None else landmarks
    roster = _roster_snapshot() if roster is None else roster
    stamp = normalized_timestamp(now, error=tc.TemporalContractError)

    role = str(model or lr.DEFAULT_READING_ROLE)
    findings: list[str] = []
    failure: dict | None = None
    reading = lr.Reading()
    try:
        prompt = lr.build_reading_prompt(body, landmarks=landmarks,
                                         roster=roster,
                                         framework_root=framework_root)
        raw = call(prompt, role)
    except Exception as exc:  # noqa: BLE001 — a provider failure is data here
        failure = {"class": "service_unavailable", "detail": str(exc)}
    else:
        reading = lr.parse_reading(raw, text=body,
                                   framework_root=framework_root)
        findings.extend(reading.findings)
        if not len(reading) and reading.findings:
            failure = {"class": "content_ambiguity",
                       "detail": reading.findings[0]}

    units, by_ref = _units_from_reading(reading, body,
                                        framework_root=framework_root)
    for unit in units:
        annotate_against_known(unit, landmarks)
        annotate_entities(unit, roster)
        unit["questions"] = unit_questions(unit, landmarks)
        unit["auto_file_eligible"] = _auto_file_eligible(unit)

    units.sort(key=lambda row_: (
        row_["quote"]["offset"] if isinstance(row_.get("quote"), dict) else 1 << 30,
        row_["domain"], row_["unit_id"]))

    events = [_event_row(read_event, by_ref, body)
              for read_event in reading.events]
    events.sort(key=lambda row_: (row_["quote"]["offset"], row_["event_id"]))

    told = [{"quote": story.quote,
             "within": (by_ref.get(story.within) or {}).get("unit_id")}
            for story in reading.stories]
    questions = open_claim_questions(open_event_claims(events), units,
                                     landmarks, body)
    stories, unrecognized = _partition_text(body, units, events, told)
    groups = build_groups(units, events, stories)

    if failure is not None:
        state = "failed"
    elif units:
        state = "proposed"
    elif questions:
        state = "needs_clarification"
    else:
        state = "proposed"

    proposal = {
        "schema_version": PROPOSAL_SCHEMA_VERSION,
        "proposal_id": proposal_id,
        "mode": OFFER_MODE,
        "interaction": "landmarks",
        "created_at": stamp,
        "vault_generation": int(generation),
        "state": state,
        "source_text": body,
        "source_digest": f"sha256:{store.payload_sha256(store.normalize_payload(body))}",
        "units": units,
        "events": events,
        "stories": stories,
        "groups": groups,
        "unrecognized": unrecognized,
        "questions": questions,
        "findings": sorted(dict.fromkeys(findings)),
        "failure": failure,
        "extractors": _extractors(role, framework_root=framework_root),
    }
    if write:
        _save_proposal(root, proposal)
    return proposal


def _extractors(model: object,
                framework_root: str | Path | None = None) -> list[dict]:
    """Which prompt bytes and which model read this text.

    §4.2 of the audited claim plan requires a receipt to name the extractor's
    prompt, schema and model version. There is ONE reading pass now
    (`landmark_reading.reading_extractor`), so there is one row, and editing
    the leaf is a NEW extractor rather than a cache rebuild.
    """
    try:
        return [lr.reading_extractor(str(model or lr.DEFAULT_READING_ROLE),
                                     framework_root=framework_root)]
    except Exception:  # noqa: BLE001
        return []


def _save_proposal(vault_root: Path, proposal: dict) -> Path:
    """Write the proposal once. A FAILED one is replaced by a later reading.

    Content-addressed, so a retry of the same text against the same
    generation lands on the same path: two readings of one submission are one
    proposal, and the first successful reading stands. A proposal that FAILED
    is the one exception — a retry after the provider came back must be able
    to replace it, or the failure becomes permanent.
    """
    relative = f"{OFFERS_DIR}/{proposal['proposal_id'].split(':', 1)[1]}.json"
    path = store.store_path(vault_root, relative)
    if path.is_file():
        try:
            standing = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            standing = None
        if isinstance(standing, dict) and standing.get("state") != "failed":
            return path
    _write_json(vault_root, path, proposal)
    return path


def read_proposal(vault_root: str | Path, proposal_id: str) -> dict:
    path = proposal_path(vault_root, proposal_id)
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise LandmarkOfferError("unsupported_input",
                                 f"no such proposal: {proposal_id}") from exc
    if not isinstance(value, dict):
        raise LandmarkOfferError("unsupported_input",
                                 f"unreadable proposal: {proposal_id}")
    return value


# --------------------------------------------------------------------------
# apply — the SAME writer a conversation answer files through
# --------------------------------------------------------------------------

def unit_filing_digest(proposal_id: object, unit: dict) -> str:
    """``(proposal_id, unit_id)`` as the promoted record's own identity.

    The idempotency key, and the reason a retry files nothing twice: it is a
    function of what the person offered and which unit they confirmed, never
    of the filing ORDINAL, which moves under a retry as earlier units land.
    It rides into `timeline.save_landmark` through the ``digest_override``
    seam that already exists for exactly this problem.
    """
    import go_dig_writer as _writer  # noqa: PLC0415 — internal writer seam

    return _writer.go_dig_unit_digest(
        import_operation_id=collapsed_text(proposal_id),
        block_content_digest=collapsed_text(unit.get("unit_id")),
        unit_kind=collapsed_text(unit.get("domain")),
        discriminator="",
    )


def unit_source_relative_path(proposal_id: object, unit: dict) -> str:
    """Where the record this unit files lands, computed before it is filed."""
    return lp.landmark_source_relative_path(unit_filing_digest(proposal_id, unit))


def _source_id_for(vault_root: Path, proposal_id: str, unit: dict) -> str | None:
    ref = store.read_source_ref(vault_root,
                               unit_source_relative_path(proposal_id, unit))
    return ref.source_id if ref is not None else None


def _place_name_for(unit: dict) -> str | None:
    """The roster place a unit names, where its domain has one.

    Only `residences` mints a place from a unit today, and only from the city
    rung — the same narrow rule the one-unit writer already applies. A domain
    whose subject is an organization proposes it as an entity candidate and
    leaves the minting to the roster's own resolver.
    """
    if unit.get("domain") != "residences":
        return None
    record = unit.get("record") or {}
    city = record.get("city") or record.get("label")
    return str(city).strip() or None if isinstance(city, str) else None


# --------------------------------------------------------------------------
# R7 filing: a group's own words, and what rides on them
# --------------------------------------------------------------------------
#
# A submission is promoted whole, because R3 says the person's words are
# evidence the moment they are handed over. That whole-paste source is the
# wrong thing for one stay's events to cite, though: a later reader joining a
# moment to a place does it by PROVABLE SOURCE OVERLAP with the roster place
# (`timeline._place_for_event`, and the containment rung's own
# `question_context` seam), and a source that is the whole document overlaps
# with every place in it. So `apply` also promotes ONE SLICE PER GROUP — the
# head unit's own words, extended to cover the words of everything inside it —
# and the events, moments and stories that group holds cite that.
#
# The slice carries `question_context` = the stay's own telling ref, which is
# `episode_binder`'s deterministic containment rung (`QUESTION_CONTEXT_SEAM`,
# event identity §12b ruling 5): "this was told about that stay" is a FACT
# about what was said, not an inference from it, so the binder files it as a
# `part_of` rather than proposing it. Filing that binding is the BINDER's act,
# not this one — `bind-episodes --apply` is an owner-reviewed step and calling
# it from here would be a second writer of the identity substrate.

#: This module's own deterministic rule version, for a proposal that recorded
#: no reading extractor (a failed reading, or a leaf that could not be read).
FILING_RULE_VERSION = "1"


def _filing_extractor(proposal: object) -> tuple[dict, str]:
    """``(extractor block, extractor_version)`` for the claims one apply files.

    The READING is the extractor: these events are the ones it read, so they
    name its prompt bytes and its model — the block `propose` already recorded
    (`landmark_reading.reading_extractor`). A proposal that recorded none names
    this module's own deterministic rule instead of filing an unnamed
    extractor, which `temporal_claims.validate_temporal_claim` refuses outright.
    """
    import general_listener as gl  # noqa: PLC0415 — the one version renderer

    rows = (proposal or {}).get("extractors") or ()
    block = next((row for row in rows
                  if isinstance(row, dict) and row.get("name")), None)
    if block is None:
        block = {"name": "landmark_offer", "schema_version": tc.SCHEMA_VERSION,
                 "rule_version": FILING_RULE_VERSION, "deterministic": True}
    return dict(block), gl.claim_extractor_version(block)


def _promotion_metadata(proposal_id: object, *, turn_ref: object = None,
                        question_context: object = None) -> dict:
    """The metadata every source this mode promotes carries.

    ``session_ref`` and ``turn_ref`` are the identity keys
    (`temporal_store.PROMOTION_IDENTITY_KEYS`); ``question_context`` is not, so
    stamping a slice with the stay it was told about never moves its digest or
    its path.

    A GROUP's slice carries the head unit's id as its ``turn_ref``, and it has
    to: a submission that IS one stay ("I lived on Elm from 1990 to 1992, we
    called it the blue house…") has a slice whose bytes are the whole
    submission's, and without a distinct turn the slice would promote onto the
    whole submission's own file — which is already there, without the stamp,
    because promotion keeps the standing file. Same proposal, same unit, same
    turn: a retry still lands on one source.
    """
    meta = {"channel": OFFER_CHANNEL, "visibility": "owner_only",
            "session_ref": f"landmark-offer:{collapsed_text(proposal_id)}"}
    turn = collapsed_text(turn_ref)
    if turn:
        meta["turn_ref"] = turn
    stamp = collapsed_text(question_context)
    if stamp:
        meta[store.QUESTION_CONTEXT_KEY] = stamp
    return meta


def _span_of(row: object) -> tuple[int, int] | None:
    """``(offset, length)`` for a unit, an event or a story."""
    if not isinstance(row, dict):
        return None
    quote = row.get("quote")
    if isinstance(quote, dict) and isinstance(quote.get("offset"), int):
        return int(quote["offset"]), int(quote.get("length") or 0)
    if isinstance(row.get("offset"), int):
        return int(row["offset"]), int(row.get("length") or 0)
    return None


def group_members(proposal: object, group: object) -> list[tuple[str, dict]]:
    """``[(kind, row)]`` — the proposal rows one group's members name.

    `groups[]` carries ids, not rows, because it is a wire shape a host
    transports verbatim. This is the one place that resolves them back, so
    `apply`, `render_proposal` and a test never each write their own lookup.
    """
    row = proposal if isinstance(proposal, dict) else {}
    tables = {
        "unit": {item.get("unit_id"): item for item in (row.get("units") or ())
                 if isinstance(item, dict)},
        "event": {item.get("event_id"): item for item in (row.get("events") or ())
                  if isinstance(item, dict)},
        "story": {item.get("story_id"): item for item in (row.get("stories") or ())
                  if isinstance(item, dict)},
    }
    found: list[tuple[str, dict]] = []
    for member in ((group or {}).get("members") or ()):
        if not isinstance(member, dict):
            continue
        table = tables.get(collapsed_text(member.get("kind")))
        item = table.get(collapsed_text(member.get("id"))) if table else None
        if item is not None:
            found.append((collapsed_text(member.get("kind")), item))
    return found


def group_slice(proposal: object, group: object) -> dict | None:
    """``{offset, length, text}`` — the words ONE group is made of.

    The head unit's own quote, extended to cover every member's quote. Not the
    whole submission (that is promoted separately and is nobody's stay) and not
    the head's quote alone (an event read inside the stay has to be inside the
    slice its claim cites, or the quotation is evidence for nothing).
    """
    row = proposal if isinstance(proposal, dict) else {}
    text = str(row.get("source_text") or "")
    head = {item.get("unit_id"): item for item in (row.get("units") or ())
            if isinstance(item, dict)}.get(
                collapsed_text((group or {}).get("unit_id")))
    if head is None:
        return None
    spans = [span for span in
             [_span_of(head)] + [_span_of(item) for _kind, item
                                 in group_members(row, group)]
             if span is not None and span[1] > 0]
    if not spans:
        return None
    start = min(offset for offset, _length in spans)
    end = max(offset + length for offset, length in spans)
    body = text[start:end]
    return {"offset": start, "length": len(body), "text": body}


def group_source_relative_path(proposal_id: object, unit_id: object,
                               slice_text: object) -> str:
    """Where a group's slice lands, computed BEFORE it is promoted.

    The sibling of :func:`unit_source_relative_path` — that one names the path
    the landmark RECORD files to, this one names the path the group's own words
    file to. Both are pure functions of what the person offered, which is what
    makes a receipt readable before anything has been written and a retry
    recognisable afterwards.
    """
    return store.conversation_source_relative_path(
        store.promotion_digest(str(slice_text or ""),
                               _promotion_metadata(proposal_id,
                                                   turn_ref=unit_id)))


def _claim_draft(event: dict, *, parent: object, origin: int) -> dict | None:
    """One read event as a claim draft — dated or not.

    A DATED event is a ``date`` claim; an UNDATED one is an ``occurrence``, the
    claim type that asserts a thing happened and asserts nothing about when
    (`temporal_claims.OCCURRENCE_CLAIM_TYPE`). That choice is the SYSTEM's and
    is made from the bytes: `occurrence` is withheld from every model-facing
    vocabulary (`temporal_claims.MODEL_CLAIM_TYPES`) and the reading leaf never
    names a claim type at all — it reports an event and whether the person
    dated it, exactly as `classifier_claims.temporal_reading` decides the same
    thing over a classification it did not make.

    **The stay rides on ``place_mentions``, not on ``event_mention``** — the
    one place this build departs from §3.1 rule 7's letter, for a verified
    reason. `temporal_timeline._node_what` publishes the longest
    ``event_mention`` as the node's own HUMAN TEXT ("what a person would call
    this thing"), so putting the stay's name there labels *"Dad started at the
    mill"* as *"the blue house"* on the person's own timeline — the same class
    of defect as D2's cities-as-labels. The rule's INTENT is the join, and
    `place_mentions` is the field the join actually reads
    (`event_identity`'s entity signal, `temporal_timeline._group_place_mentions`),
    so the stay's names go there and the event keeps its own words.
    ``question_context`` on the group's slice carries the containment itself.
    """
    quote = event.get("quote") if isinstance(event.get("quote"), dict) else {}
    text = collapsed_text(quote.get("text"))
    kind = collapsed_text(event.get("kind"))
    subject = collapsed_text(event.get("subject_mention"))
    if not text or not kind or not subject:
        return None
    start = max(int(quote.get("offset") or 0) - int(origin or 0), 0)
    draft: dict = {
        "claim_type": ("date" if event.get("filing") == "claim"
                       else tc.OCCURRENCE_CLAIM_TYPE),
        "subject_mention": subject,
        "event_kind": kind,
        "evidence": [{"quote": text, "start": start,
                      "end": start + max(int(quote.get("length") or 0), 1)}],
        "basis": "explicit",
        "confidence": 1.0,
    }
    draft["event_mention"] = collapsed_text(event.get("text")) or text
    places = [name for name in
              (collapsed_text((parent or {}).get("subject")),
               _place_name_for(parent) if isinstance(parent, dict) else None)
              if name]
    if places:
        draft["place_mentions"] = list(dict.fromkeys(places))
    if draft["claim_type"] == "date":
        value = chrono.normalized_date(event.get("date"))
        if value is None:
            return None
        draft["temporal_value"] = value
    return draft


def _file_group(vault_root: Path, proposal: dict, group: dict, *,
                telling_ref: object, extractor: dict, version: str,
                now: object) -> dict | None:
    """Promote one group's slice and file the events and stories it holds.

    Returns the receipt row for the slice, or ``None`` when the group holds
    nothing to file. Idempotent twice over: the slice is content-addressed, so
    a second apply promotes no second file, and the claims derive their ids
    from that same source, so the receipt lands on the path it already
    occupies and `temporal_store.write_receipt` keeps the standing one.
    """
    body = group_slice(proposal, group)
    if body is None:
        return None
    by_unit = {row.get("unit_id"): row for row in (proposal.get("units") or ())
               if isinstance(row, dict)}
    events: list[tuple[dict, dict]] = []
    stories: list[dict] = []
    for kind, row in group_members(proposal, group):
        if kind == "event":
            draft = _claim_draft(row, parent=by_unit.get(row.get("within")),
                                 origin=body["offset"])
            if draft is not None:
                events.append((row, draft))
        elif kind == "story":
            stories.append(row)
    if not events and not stories:
        return None

    metadata = _promotion_metadata(proposal["proposal_id"],
                                   turn_ref=group.get("unit_id"),
                                   question_context=telling_ref)
    try:
        slice_ref = store.promote_conversational_source(
            vault_root, body["text"], metadata, source_type=OFFER_SOURCE_TYPE)
    except Exception as exc:  # noqa: BLE001 — every write failure is typed
        raise LandmarkOfferError(
            "write_failure",
            f"{group.get('unit_id')} slice did not promote: {exc}") from exc

    claims: list[dict] = []
    if events:
        import general_listener as gl  # noqa: PLC0415 — the one claim binder

        try:
            claims = gl.bind_claims([draft for _row, draft in events],
                                    source_ref=slice_ref,
                                    extractor_version=version, now=now)
            store.write_receipt(vault_root, {
                "source_ref": slice_ref.to_dict(),
                "extractor_version": version,
                "extractor": dict(extractor),
                "claims": claims,
                "idempotency_key": store.derive_extraction_idempotency_key(
                    session_ref=metadata.get("session_ref"),
                    turn_ref=metadata.get("turn_ref"),
                    source_ref=slice_ref, recorder=None,
                    extractor_version=version),
            }, now=now)
        except Exception as exc:  # noqa: BLE001 — every write failure is typed
            raise LandmarkOfferError(
                "write_failure",
                f"{group.get('unit_id')} events did not file: {exc}") from exc

    # `bind_claims` drops a draft that duplicates another exactly, so a claim
    # is looked up by WHAT IT ASSERTS rather than by its position in the list.
    by_assertion = {(claim.get("claim_type"), claim.get("subject_mention"),
                     claim.get("event_kind")): claim.get("claim_id")
                    for claim in claims}
    return {
        "unit_id": group.get("unit_id"),
        "source_id": slice_ref.source_id,
        "relative_path": group_source_relative_path(
            proposal["proposal_id"], group.get("unit_id"), body["text"]),
        "question_context": collapsed_text(telling_ref) or None,
        "offset": body["offset"],
        "length": body["length"],
        "events": [{"event_id": row.get("event_id"),
                    "filing": row.get("filing"),
                    "kind": row.get("kind"),
                    "subject_mention": row.get("subject_mention"),
                    "within": row.get("within"),
                    "claim_id": by_assertion.get(
                        (draft["claim_type"], draft["subject_mention"],
                         draft.get("event_kind")))}
                   for row, draft in events],
        "stories": [{"story_id": row.get("story_id"),
                     "within": row.get("within")} for row in stories],
    }


def apply(proposal_id: str, unit_ids: object, vault_root: str | Path, *,
          now: object = None, reason: object = None) -> dict:
    """File the units a person confirmed. Idempotent by ``(proposal, unit)``.

    Every unit goes through the SAME road a landmark ANSWER takes —
    `timeline.save_landmark`, the one landmark writer — so a confirmed offer
    and an answered question are indistinguishable downstream, which is the
    whole of R3a ("same unit, same landmark recorder, same value
    calculation"). The submitted text is promoted once as an ordinary vault
    source so no filed claim's only citation is a proposal file.

    Returns the receipt: what was filed, the generations either side, the
    realized-gain diff Cut 4c publishes, and its sentence.
    """
    import go_dig_writer as _writer  # noqa: PLC0415 — internal writer seam

    root = _bound_vault(vault_root)
    proposal = read_proposal(root, proposal_id)
    by_id = {unit["unit_id"]: unit for unit in proposal.get("units") or ()
             if isinstance(unit, dict) and unit.get("unit_id")}
    wanted = [collapsed_text(value) for value in (unit_ids or ()) if value]
    unknown = [value for value in wanted if value not in by_id]
    if unknown:
        raise LandmarkOfferError(
            "unsupported_input",
            f"{proposal_id} has no unit(s) {', '.join(sorted(unknown))}")
    chosen = [by_id[value] for value in dict.fromkeys(wanted)]
    if not chosen:
        raise LandmarkOfferError("content_ambiguity",
                                 "confirm at least one unit before applying")

    receipt_id = derive_receipt_id(proposal_id, [u["unit_id"] for u in chosen])
    stamp = normalized_timestamp(now, error=tc.TemporalContractError)
    before = pub.read_projection(root)
    open_before = open_opportunity_ids(root, projection=before)

    # R3: the words are evidence, and they become an ordinary vault source the
    # moment anything is filed from them — promoted ONCE, idempotent by its
    # own content digest, so a retry adds no second copy.
    text_ref = store.promote_conversational_source(
        root, proposal.get("source_text") or "",
        _promotion_metadata(proposal_id), source_type=OFFER_SOURCE_TYPE,
    )

    filed: list[dict] = []
    names: list[dict] = []
    telling_refs: dict[str, str] = {}
    for unit in sorted(chosen, key=lambda row_: row_["unit_id"]):
        payload = {
            "landmark": dict(unit["record"]),
            "import_operation_id": proposal_id,
            "block_content_digest": unit["unit_id"],
            "session_ref": f"landmark-offer:{proposal_id}",
        }
        place_name = _place_name_for(unit)
        if place_name:
            payload["landmark"]["place_name"] = place_name
        try:
            summary = _writer.record_unit(payload, now=now)
        except Exception as exc:  # noqa: BLE001 — every write failure is typed
            raise LandmarkOfferError("write_failure",
                                     f"{unit['unit_id']} did not file: {exc}") from exc
        entry = summary.get("entry") or {}
        try:
            row = li.domain_row(unit["domain"])
        except li.LandmarkInteractionError:
            row = None
        telling = collapsed_text(summary.get("telling_ref"))
        if telling:
            telling_refs[unit["unit_id"]] = telling
        filed.append({
            "unit_id": unit["unit_id"],
            "domain": unit["domain"],
            "kind": unit["kind"],
            "subject": unit["subject"],
            "entry_key": li.landmark_entry_key(entry or unit["record"], row),
            "basis": (unit.get("dates") or {}).get("basis"),
            "filing_digest": unit_filing_digest(proposal_id, unit),
            "source_id": _source_id_for(root, proposal_id, unit),
            "place_ref": summary.get("place_ref"),
            "telling_ref": telling or None,
        })
        # The NAMES the record carried (§3 "why names matter"): the E-L2c
        # fields rode on the record through the one writer, and `record_unit`
        # filed the nickname as a roster ALIAS on the place the city minted.
        # What is reported here is what the ENTRY ended up with, never what
        # the reading asked for — a name the validator dropped was not filed.
        filed_names = {key: entry[key] for key in lr.NAME_FIELDS
                       if isinstance(entry, dict) and entry.get(key)}
        alias = summary.get("alias") if isinstance(summary.get("alias"), dict) else None
        if filed_names or alias:
            names.append({
                "unit_id": unit["unit_id"],
                "place_ref": summary.get("place_ref"),
                "names": filed_names,
                "alias": ({"applied": bool(alias.get("applied")),
                           "changed": bool(alias.get("changed")),
                           "alias": collapsed_text(entry.get("nickname")),
                           "reason": alias.get("reason")}
                          if alias else None),
            })

    # R7: what each confirmed stay HOLDS — the events read inside it, the
    # moments it dates, the stories told about it — filed against that stay's
    # own words rather than against the whole submission. A group whose head
    # unit the person did not confirm files nothing: an event rides its stay,
    # and an unconfirmed stay carries nothing.
    extractor, version = _filing_extractor(proposal)
    confirmed = {unit["unit_id"] for unit in chosen}
    slices: list[dict] = []
    for group in (proposal.get("groups") or ()):
        if not isinstance(group, dict) or group.get("unit_id") not in confirmed:
            continue
        row = _file_group(root, proposal, group,
                          telling_ref=telling_refs.get(group["unit_id"]),
                          extractor=extractor, version=version, now=now)
        if row is not None:
            slices.append(row)
    if slices:
        # The one writer: the claims just filed become the current substrate
        # and the calculated projection is republished from it, exactly as
        # `save_landmark` does for a landmark record.
        import timeline as _timeline  # noqa: PLC0415 — the one republisher

        _timeline.redraw_landmarks()

    after = pub.read_projection(root)
    gain = trcpt.diff_projections(before, after) if after is not None else {}
    open_after = open_opportunity_ids(root, projection=after)
    retired = [retire_matching_opportunity(unit, root, open_before=open_before,
                                           open_after=open_after)
               for unit in chosen]

    receipt = {
        "schema_version": OFFER_RECEIPT_SCHEMA_VERSION,
        "receipt_id": receipt_id,
        "proposal_id": proposal_id,
        "created_at": stamp,
        "reason": collapsed_text(reason) or None,
        "unit_ids": sorted(unit["unit_id"] for unit in chosen),
        "filed": filed,
        # v292: everything else this act filed, so Cut 4c's realized-gain
        # sentence can count it and `retract` can undo exactly it.
        "filed_names": names,
        "filed_slices": slices,
        "counts": {
            "units": len(filed),
            "names": len(names),
            "claims": sum(1 for row in slices for event in row["events"]
                          if event["filing"] == "claim"),
            "moments": sum(1 for row in slices for event in row["events"]
                           if event["filing"] == "moment"),
            "stories": sum(len(row["stories"]) for row in slices),
        },
        "evidence_ref": text_ref.to_dict(),
        "generation_before": pub._generation_of(before) if before else 0,  # noqa: SLF001
        "generation_after": pub._generation_of(after) if after else 0,  # noqa: SLF001
        "gain": gain,
        "sentence": trcpt.render_realized_gain(gain),
        "retired_opportunities": retired,
    }
    return _save_receipt(root, receipt)


def _save_receipt(vault_root: Path, receipt: dict) -> dict:
    """Write the apply receipt once; a retry reads the standing one back.

    The receipt is the record of an ACT, so the first one stands: a second
    apply of the same units files nothing (the promoted sources are already
    there under the same digests) and must therefore not claim to have gained
    anything a second time.
    """
    name = receipt["receipt_id"].split(":", 1)[1]
    path = store.store_path(vault_root, f"{OFFER_RECEIPTS_DIR}/{name}.json")
    if path.is_file():
        try:
            standing = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            standing = None
        if isinstance(standing, dict):
            return standing
    _write_json(vault_root, path, receipt)
    return receipt


def read_offer_receipt(vault_root: str | Path, receipt_id: str) -> dict:
    path = offer_receipt_path(vault_root, receipt_id)
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise LandmarkOfferError("unsupported_input",
                                 f"no such receipt: {receipt_id}") from exc
    if not isinstance(value, dict):
        raise LandmarkOfferError("unsupported_input",
                                 f"unreadable receipt: {receipt_id}")
    return value


# --------------------------------------------------------------------------
# The 5a seam
# --------------------------------------------------------------------------

def opportunity_ids_for(unit: dict) -> list[str]:
    """Every Cut 5a opportunity id this unit could be the answer to.

    An opportunity's identity is its GAP — domain, kind, subject — and one
    filed unit can close several kinds of gap about the same subject: a
    residence with both bounds answers `span_missing`, `span_open_start` and
    `span_open_end` alike. So the unit names all of them and
    :func:`retire_matching_opportunity` reports which ones actually closed.
    """
    import landmark_opportunities as lop  # noqa: PLC0415

    domain = unit.get("domain")
    subject = unit.get("subject")
    if not domain or not subject:
        return []
    return [lop.opportunity_id(domain=domain, kind=kind, subject=subject)
            for kind in lop.OPPORTUNITY_KINDS]


def open_opportunity_ids(vault_root: str | Path, *,
                         projection: object = None) -> set[str]:
    """The ids of the opportunities the PUBLISHED projection is offering.

    Read from the published block Cut 5a writes (`landmark_opportunities`) —
    the same bytes the page and the queue read — never re-derived here. A
    generation published before 5a carries none, which reads as "nothing is
    being offered", and that is what a generation that never measured it
    knows.
    """
    payload = (pub.read_projection(vault_root) if projection is None
               else projection) or {}
    rows = payload.get("landmark_opportunities") or ()
    return {collapsed_text(row.get("id")) for row in rows
            if isinstance(row, dict) and row.get("id")}


def retire_matching_opportunity(unit: dict, vault_root: str | Path, *,
                                open_before: object = None,
                                open_after: object = None) -> dict:
    """Which landmark opportunity this filed unit retired (R3a, §5.4).

    A confirmed Add Landmark counts toward landmark sufficiency and retires
    the matching open question. It does so by CLOSING THE GAP, not by setting
    a flag: Cut 5a derives its opportunities from the calculated graph on
    every publish, so a stay that now has both its bounds simply stops
    generating `span_open_end` — and a retirement that is measured against
    the published generations either side of the filing cannot claim
    something the graph does not agree with.

    ``open_before``/``open_after`` are the published opportunity ids either
    side of the act (:func:`open_opportunity_ids`). Called without a
    ``open_before``, NOTHING is claimed retired and the currently open
    candidates are reported instead — an unmeasured before cannot support the
    claim that something closed, and overclaiming here would put a
    retirement on a receipt that the graph does not agree with.
    """
    candidates = opportunity_ids_for(unit)
    after = (set(open_after) if open_after is not None
             else open_opportunity_ids(vault_root))
    before = set(open_before) if open_before is not None else set(after)
    retired = sorted((set(candidates) & before) - after)
    return {
        "unit_id": unit.get("unit_id"),
        "opportunity_ids": candidates,
        "retired": retired,
        "still_open": sorted(set(candidates) & after),
    }


# --------------------------------------------------------------------------
# retract — the undo that marks rather than deletes
# --------------------------------------------------------------------------

RETRACTION_REASON = "the person undid an Add Landmark"


def _claim_ids_for_sources(vault_root: Path, source_ids: object) -> list[str]:
    wanted = {collapsed_text(value) for value in (source_ids or ()) if value}
    if not wanted:
        return []
    index = store.read_active_index(vault_root) or store.fold_active_index(vault_root)
    found = []
    for row in store.active_claims(index):
        ref = row.get("source_ref")
        if isinstance(ref, dict) and collapsed_text(ref.get("source_id")) in wanted:
            found.append(str(row.get("claim_id")))
    return sorted(dict.fromkeys(found))


#: The scope a retraction files the EVENTS and MOMENTS of an offer under.
#: Not a domain — a moment held inside a stay belongs to no landmark ladder,
#: and filing it under one would claim a domain nobody named.
EVENTS_SCOPE = "events"


def _retract_aliases(receipt: dict) -> list[dict]:
    """Take back the roster aliases this receipt's apply added. Idempotent.

    Only an alias the apply itself CHANGED is removed: a nickname the place
    already answered to was not this act's to file and is not this act's to
    take away. `roster_relations.retract_alias` is the one definition of
    removing one; this only decides which.
    """
    import entity_roster  # noqa: PLC0415 — process-bound roster, as everywhere
    import roster_relations as rr  # noqa: PLC0415

    wanted = [row for row in (receipt.get("filed_names") or ())
              if isinstance(row, dict) and isinstance(row.get("alias"), dict)
              and row["alias"].get("changed") and row.get("place_ref")
              and collapsed_text(row["alias"].get("alias"))]
    if not wanted:
        return []
    snapshot = entity_roster.load_roster("place")
    removed: list[dict] = []
    changed = False
    for row in wanted:
        result = rr.retract_alias("place", row["place_ref"],
                                  row["alias"]["alias"], snapshot)
        if result.get("applied") and result.get("changed"):
            snapshot = result["snapshot"]
            changed = True
        removed.append({"place_ref": row["place_ref"],
                        "alias": collapsed_text(row["alias"].get("alias")),
                        "removed": bool(result.get("changed"))})
    if changed:
        entity_roster.write_roster("place",
                                   list(snapshot.get("entities") or ()))
    return removed


def retract(receipt_id: str, vault_root: str | Path, *, reason: object = None,
            now: object = None) -> dict:
    """Undo an applied offer. The evidence and the receipt stay on disk.

    §5.4's undo, through the correction machinery every other undo in this
    package uses: `temporal_store.retract_claims` names exactly the claims the
    filed units stand on — found by the promoted SOURCE each unit wrote, so
    undoing the second stay at an address never touches the first — and the
    projection is republished by the one writer. Nothing is deleted: the
    promoted sources, their receipts and this offer's own receipt all remain,
    and the retraction is a new immutable file beside the receipt.
    """
    import timeline  # noqa: PLC0415

    root = _bound_vault(vault_root)
    receipt = read_offer_receipt(root, receipt_id)
    path = retraction_path(root, receipt_id)
    if path.is_file():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            pass
    why = collapsed_text(reason) or RETRACTION_REASON
    corrections: list[dict] = []
    by_domain: dict[str, list[str]] = {}
    for row in receipt.get("filed") or ():
        if not isinstance(row, dict):
            continue
        by_domain.setdefault(collapsed_text(row.get("domain")), []).append(
            collapsed_text(row.get("source_id")))
    # v292: the events, moments and stories the confirmed stays HELD stand on
    # their group's own promoted slice, not on any unit's record source, so
    # they are named by that slice and retracted under their own scope. The
    # slice itself stays on disk — it is an immutable promoted source, and the
    # discipline for one of those is to retract what stands on it, never to
    # delete it.
    slice_sources = [collapsed_text(row.get("source_id"))
                     for row in (receipt.get("filed_slices") or ())
                     if isinstance(row, dict) and row.get("source_id")]
    if slice_sources:
        by_domain.setdefault(EVENTS_SCOPE, []).extend(slice_sources)
    for domain in sorted(by_domain):
        claim_ids = _claim_ids_for_sources(root, by_domain[domain])
        if not claim_ids:
            continue
        correction = store.retract_claims(
            root, claim_ids, reason=f"{why} ({receipt_id})",
            scope=f"landmarks/{domain}" if domain else "landmarks",
            occurred_at=now,
        )
        corrections.append({"domain": domain,
                            "correction_id": correction.correction_id,
                            "claim_ids": list(claim_ids)})
    # The NAMES: a nickname this apply added to a roster place is taken back
    # off it. Only one this apply actually CHANGED — an alias that was already
    # there was not filed by this act and is not this act's to remove.
    aliases = _retract_aliases(receipt)
    # The one writer: redraw the landmark store from the substrate and
    # republish the calculated projection in the same act.
    timeline.redraw_landmarks()
    after = pub.read_projection(root)
    retraction = {
        "schema_version": OFFER_RECEIPT_SCHEMA_VERSION,
        "receipt_id": receipt_id,
        "proposal_id": receipt.get("proposal_id"),
        "retracted_at": normalized_timestamp(now, error=tc.TemporalContractError),
        "reason": why,
        "corrections": corrections,
        "aliases": aliases,
        "generation_after": pub._generation_of(after) if after else 0,  # noqa: SLF001
    }
    _write_json(root, path, retraction)
    return retraction


def receipt_is_retracted(vault_root: str | Path, receipt_id: str) -> bool:
    return retraction_path(vault_root, receipt_id).is_file()


# --------------------------------------------------------------------------
# The lints — deterministic, run over a proposal and over the worker's reply
# --------------------------------------------------------------------------

#: The offer gate NAMESPACE. Deliberately its own, not `landmark_gates.`:
#: that family is the closed set `landmarks_interaction.LANDMARK_LINT_CLASSES`
#: scored by `landmarks_evals.score_goldens` over the collect-mode REPLY
#: goldens, and `load_gates` is one-to-one with it by test. These four judge a
#: different artifact (a PROPOSAL, and a reply about one) over a different
#: golden set, scored by a different function — so they get a prefix of their
#: own rather than making the older contract mean two things.
OFFER_GATE_PREFIX = "landmark_offer_gates"

OFFER_LINT_CLASSES = (
    # A proposed date must be in the person's own text. This is the class R3's
    # whole "never invent a date" rests on, and v291 widens it from stated
    # bounds to EVERY bound: an inherited date is still a year the document
    # carries somewhere, so a year that is nowhere in it is fabricated
    # whatever basis the unit claims.
    f"{OFFER_GATE_PREFIX}.no_fabricated_date",
    # Every span of the submission is a unit, an event, a story or an
    # explicitly unrecognized span. Nothing is silently dropped.
    f"{OFFER_GATE_PREFIX}.nothing_dropped",
    # R3a: non-landmark text is accepted and routed as a story, never refused.
    f"{OFFER_GATE_PREFIX}.never_refuses",
    # The stop rules, in offer clothing: no form voice, no homework, no
    # pressure, no "are you sure".
    f"{OFFER_GATE_PREFIX}.keeps_stop_rules",
    # v291: every unit and every event carries a quotation LOCATED in the
    # submitted text. A reading whose evidence cannot be pointed at is not
    # evidence, and the confirmation screen has nothing honest to show.
    f"{OFFER_GATE_PREFIX}.quotes_locate",
    # v291: the basis says what it means. No `inferred` without the verbatim
    # provenance clause that names where it came from (D5), and no `stated`
    # bound shown certain when the reading marked it estimated (D3, R8).
    f"{OFFER_GATE_PREFIX}.honest_basis",
)

NO_FABRICATED_DATE_LINT = OFFER_LINT_CLASSES[0]
NOTHING_DROPPED_LINT = OFFER_LINT_CLASSES[1]
NEVER_REFUSES_LINT = OFFER_LINT_CLASSES[2]
KEEPS_STOP_RULES_LINT = OFFER_LINT_CLASSES[3]
QUOTES_LOCATE_LINT = OFFER_LINT_CLASSES[4]
HONEST_BASIS_LINT = OFFER_LINT_CLASSES[5]

#: What a refusal sounds like. Any of these in the worker's reply is the
#: R3a violation: the person handed over something real and was told no.
_REFUSAL_RES = (
    re.compile(r"\b(?:I )?can'?t (?:use|accept|read|parse|process|do anything with)\b",
               re.IGNORECASE),
    re.compile(r"\bcould(?:\s+not|n['’]?t)\s+"
               r"(?:parse|read|use|understand|process|make anything)\b",
               re.IGNORECASE),
    re.compile(r"\b(?:that|this) (?:is )?(?:isn'?t|is not) (?:a )?(?:valid|supported|"
               r"something I can)\b", re.IGNORECASE),
    re.compile(r"\bplease (?:use|try) (?:the )?(?:correct|proper|right) format\b",
               re.IGNORECASE),
    re.compile(r"\bnot (?:a )?landmark[,.]? (?:so )?(?:I )?(?:can'?t|won'?t|will not)\b",
               re.IGNORECASE),
)


def lint_offer_proposal(proposal: object) -> list[dict]:
    """Deterministic findings over one proposal. Empty is clean.

    ``[{"lint", "detail"}]``, one row per finding, sorted — the same shape
    `landmarks_interaction.lint_landmark_reply` returns, so a host runs both
    through one reporter.

    Six checks, all off the bytes and none off a completion's own claim about
    itself: no year a unit's dates carry that the submitted text does not
    (whatever its basis) · every span of the text accounted for · every unit
    and event quote LOCATED in the text · no `inferred` without a provenance
    clause · no `stated` bound shown certain that the reading marked estimated.
    """
    findings: list[dict] = []
    row = proposal if isinstance(proposal, dict) else {}
    text = str(row.get("source_text") or "")
    units = [unit for unit in (row.get("units") or ()) if isinstance(unit, dict)]
    events = [event for event in (row.get("events") or ())
              if isinstance(event, dict)]
    for unit in units:
        dates = unit.get("dates") or {}
        for _path, bound in _bounds_of(unit.get("record") or {}):
            if not date_evidence(bound, unit.get("quote"), text):
                findings.append({
                    "lint": NO_FABRICATED_DATE_LINT,
                    "detail": (f"{unit.get('unit_id')} carries a date the "
                               f"text does not"),
                })
                break
        if dates.get("basis") == "inferred" and not collapsed_text(
                dates.get("clause")):
            findings.append({
                "lint": HONEST_BASIS_LINT,
                "detail": f"{unit.get('unit_id')} is inferred and says nothing "
                          f"about where the date came from",
            })
        estimated = dates.get("estimated") if isinstance(
            dates.get("estimated"), dict) else {}
        if dates.get("basis") == "stated" and (
                estimated.get("start") or estimated.get("end")) and \
                dates.get("confidence") == "certain":
            findings.append({
                "lint": HONEST_BASIS_LINT,
                "detail": f"{unit.get('unit_id')} marks an estimated bound "
                          f"certain",
            })
    for item, label in ([(unit, unit.get("unit_id")) for unit in units]
                        + [(event, event.get("event_id")) for event in events]):
        quote = item.get("quote")
        if not isinstance(quote, dict) or not quote.get("text") or \
                locate(text, quote.get("text")) is None:
            findings.append({
                "lint": QUOTES_LOCATE_LINT,
                "detail": f"{label} has no quotation in the text",
            })
    covered = _quote_spans(units) + _quote_spans(events)
    covered += [(span["offset"], span["length"])
                for group in ("stories", "unrecognized")
                for span in (row.get(group) or ())
                if isinstance(span, dict) and "offset" in span]
    for span in source_spans(text):
        if not any(_overlaps(span["offset"], span["length"], offset, length)
                   for offset, length in covered):
            findings.append({
                "lint": NOTHING_DROPPED_LINT,
                "detail": f"nothing accounts for offset {span['offset']}",
            })
    return sorted(findings, key=lambda item: (item["lint"], item["detail"]))


def lint_offer_reply(text: object, *, stage: str = "ask",
                     domain: object = None, sensitive: bool = False) -> list[dict]:
    """The worker's reply, in offer mode. Empty is clean.

    The landmarks stop rules are not re-implemented here — they are
    `landmarks_interaction.lint_landmark_reply`'s, run whole and reported
    under this mode's own stop-rule class, plus the one rule this mode adds:
    a reply may never refuse what the person handed over.
    """
    body = text if isinstance(text, str) else ""
    findings: list[dict] = []
    for pattern in _REFUSAL_RES:
        match = pattern.search(body)
        if match:
            findings.append({"lint": NEVER_REFUSES_LINT,
                             "detail": match.group(0)})
            break
    for finding in li.lint_landmark_reply(body, stage=stage, domain=domain,
                                          sensitive=sensitive):
        findings.append({"lint": KEEPS_STOP_RULES_LINT,
                         "detail": f"{finding['lint']}: {finding.get('span') or ''}".strip()})
    return sorted(findings, key=lambda item: (item["lint"], item["detail"]))


# --------------------------------------------------------------------------
# What the worker is shown
# --------------------------------------------------------------------------

#: What a unit with `basis: "none"` says out loud. NOT "inferred" and not "no
#: dates yet": nothing was read, and the honest word for that is its own (D5).
NO_DATE_READ = "no date read"

#: What an estimated bound says. R8: brackets, "about", "?" are the person's
#: own convention for an estimate, so the reading says it back as theirs.
ESTIMATED_PHRASE = "estimated, as you marked it"


def _date_phrase(dates: object) -> str:
    """One unit's dates, in the words the person should recognise (§3.2)."""
    row = dates if isinstance(dates, dict) else {}
    start, end = row.get("start"), row.get("end")
    if start and end:
        body = f"{start}–{end}"
    elif start:
        body = f"from {start}"
    elif end:
        body = f"until {end}"
    else:
        return NO_DATE_READ
    if row.get("basis") == "inferred":
        clause = collapsed_text(row.get("clause")) or INFERRED_CLAUSE
        return f"{body} ({clause})"
    estimated = row.get("estimated") if isinstance(row.get("estimated"), dict) else {}
    if estimated.get("start") or estimated.get("end") or \
            row.get("confidence") == "approximate":
        return f"{body}, {ESTIMATED_PHRASE}"
    return body


def render_unit(unit: object) -> str:
    """ONE proposed unit, in plain language, with the words it came from."""
    row = unit if isinstance(unit, dict) else {}
    subject = row.get("subject") or "(unnamed)"
    lines = [f"- {row.get('kind')}: {subject} — {_date_phrase(row.get('dates'))}"]
    names = row.get("names") if isinstance(row.get("names"), dict) else {}
    shown = [str(names[key]) for key in ("nickname", "city", "address", "link")
             if names.get(key)]
    if shown:
        lines.append("  " + " · ".join(shown))
    quote = row.get("quote")
    if isinstance(quote, dict) and quote.get("text"):
        lines.append(f"  from your words: “{quote['text']}”")
    for candidate in row.get("entity_candidates") or ():
        if candidate.get("confidence") == "new":
            lines.append(f"  {candidate.get('name')} is new to your roster")
        elif candidate.get("confidence") == "possible":
            lines.append(f"  this may be {candidate.get('name')}, already on your roster")
    for duplicate in row.get("duplicates") or ():
        lines.append(f"  already filed as {duplicate}")
    for conflict in row.get("conflicts") or ():
        lines.append(f"  conflicts: {conflict.get('detail')}")
    for question in row.get("questions") or ():
        lines.append(f"  to check: {question}")
    return "\n".join(lines)


NO_UNITS = "(nothing in this reads as a landmark)"


def render_event(event: object) -> str:
    """ONE read event, in plain language, with the words it came from."""
    row = event if isinstance(event, dict) else {}
    date = row.get("date") if isinstance(row.get("date"), dict) else {}
    when = collapsed_text(date.get("best"))
    text = row.get("text") or row.get("kind") or "something happened"
    line = f"- {text} — {when}" if when else f"- {text} — {NO_DATE_READ}"
    quote = row.get("quote")
    if isinstance(quote, dict) and quote.get("text"):
        line += f"\n  from your words: “{quote['text']}”"
    return line


#: What the group with no head unit is called. Its members are real — they were
#: read out of the person's own words — they just belong to no stay.
UNPLACED_GROUP = "- not part of anything you named:"


def _indent(block: str) -> str:
    """One member's lines, moved under the head they belong to."""
    return "\n".join(f"  {line}" if line else line
                      for line in str(block or "").splitlines())


def render_story(story: object) -> str:
    """ONE story span, in plain language."""
    row = story if isinstance(story, dict) else {}
    return f"- “{row.get('text')}”"


def render_group(proposal: object, group: object) -> str:
    """ONE group — the stay, and everything read inside it, indented under it.

    This is the shape the owner asked for: a thirty-stay document reads as
    thirty cards with their schools, jobs, events and stories under them, not
    as ninety flat rows. The group with no head unit holds what belongs to
    nothing, and says so.
    """
    row = proposal if isinstance(proposal, dict) else {}
    head = {item.get("unit_id"): item for item in (row.get("units") or ())
            if isinstance(item, dict)}.get(
                collapsed_text((group or {}).get("unit_id")))
    lines = [render_unit(head)] if head is not None else [UNPLACED_GROUP]
    for kind, member in group_members(row, group):
        if kind == "unit":
            lines.append(_indent(render_unit(member)))
        elif kind == "event":
            lines.append(_indent(render_event(member)))
        else:
            lines.append(_indent(render_story(member)))
    return "\n".join(lines)


def render_proposal(proposal: object) -> str:
    """The whole reading, as the worker leaf's ``{proposed_units}`` block.

    Rendered BY GROUP since v292 (§3.2): one head per group with its members
    indented under it. A proposal written before `groups` existed — one read
    back off disk at an older pin — still renders, as the flat list it is.

    The headless group is deliberately NOT rendered as a card. Its members
    belong to no stay, and the two sections below already say what they are in
    the person's own terms ("things that happened", "read as story"); giving
    them a card headed "not part of anything you named" would make the absence
    of a stay louder than the thing they said.
    """
    row = proposal if isinstance(proposal, dict) else {}
    groups = [group for group in (row.get("groups") or ())
              if isinstance(group, dict) and group.get("unit_id")]
    grouped = {collapsed_text(member.get("id"))
               for group in groups
               for member in (group.get("members") or ())
               if isinstance(member, dict)}
    if groups:
        blocks = [render_group(row, group) for group in groups]
    else:
        blocks = [render_unit(unit) for unit in (row.get("units") or ())
                  if isinstance(unit, dict)]
    lines = blocks or [NO_UNITS]
    events = [event for event in (row.get("events") or ())
              if isinstance(event, dict)
              and event.get("event_id") not in grouped]
    if events:
        lines.append("")
        lines.append("Things that happened, read out of the same text:")
        lines.extend(render_event(event) for event in events[:12])
    stories = [span for span in (row.get("stories") or ())
               if isinstance(span, dict)
               and span.get("story_id") not in grouped]
    if stories:
        lines.append("")
        lines.append("Read as story, not as a landmark:")
        lines.extend(render_story(span) for span in stories[:8])
    unknown = [span for span in (row.get("unrecognized") or ())
               if isinstance(span, dict)]
    if unknown:
        lines.append("")
        lines.append("Kept, but nothing was made of it:")
        lines.extend(f"- “{span['text']}”" for span in unknown[:8])
    questions = [item for item in (row.get("questions") or ())
                 if isinstance(item, dict)]
    if questions:
        lines.append("")
        lines.append("Still open:")
        lines.extend(f"- {item['text']}" for item in questions)
    return "\n".join(lines)


#: The `offer` mode's turn leaf. `interaction.yaml` carries the same file name
#: under `composition.offer_turn` and `tests/test_landmark_offer.py` pins them
#: equal, so declaring the slot and naming it in code stay one edit — the
#: discipline `landmark_recorder.RECORDER_PROMPT` already keeps.
OFFER_TURN_PROMPT = "turn-instructions-offer.md"

NO_OPEN_QUESTIONS = "(nothing is unresolved)"


def _offer_leaf_path(framework_root: str | Path | None = None) -> Path:
    base = (Path(framework_root) / "interactions" / "landmarks"
            if framework_root else INTERACTIONS_DIR / "landmarks")
    return base / "prompt" / OFFER_TURN_PROMPT


def load_offer_leaf(framework_root: str | Path | None = None) -> str:
    """The offer turn leaf, verbatim. A host REPLAYs exactly this text."""
    try:
        return _offer_leaf_path(framework_root).read_text(encoding="utf-8")
    except OSError as exc:
        raise LandmarkOfferError("unsupported_input",
                                 f"no offer turn leaf: {exc}") from exc


def render_open_questions(proposal: object) -> str:
    """The leaf's ``{open_questions}`` block — the proposal's own, and the
    units' own, in one list."""
    row = proposal if isinstance(proposal, dict) else {}
    lines = [f"- {item['text']}" for item in (row.get("questions") or ())
             if isinstance(item, dict) and item.get("text")]
    for unit in (row.get("units") or ()):
        if not isinstance(unit, dict):
            continue
        for question in unit.get("questions") or ():
            line = f"- {question}"
            if line not in lines:
                lines.append(line)
    return "\n".join(lines) if lines else NO_OPEN_QUESTIONS


def build_offer_turn(proposal: object, *, landmark_stage: str = "ask",
                     filing_gain: str = "",
                     framework_root: str | Path | None = None) -> str:
    """The composed offer turn, from the leaf plus its substitutions.

    ``.replace``, never ``.format`` — the leaf carries the person's own words
    and their braces. The two substitutions this mode adds are
    ``{proposed_units}`` (:func:`render_proposal`) and ``{open_questions}``
    (:func:`render_open_questions`); ``{landmark_stage}`` and
    ``{filing_gain}`` are the collect mode's own and mean the same thing here.
    """
    filled = load_offer_leaf(framework_root)
    for token, value in (
        ("{landmark_stage}", str(landmark_stage or "ask")),
        ("{proposed_units}", render_proposal(proposal)),
        ("{open_questions}", render_open_questions(proposal)),
        ("{filing_gain}", str(filing_gain or "")),
    ):
        filled = filled.replace(token, value)
    return filled


def offer_context(vault_root: str | Path) -> dict:
    """The `offer` mode's three manifest additions (decision record §5.2).

    ``{"roster", "known_spans", "age_frames"}`` — rendered DETERMINISTICALLY
    by the caller, from the roster and the published projection, never fetched
    by the model. The renderers live in `landmarks_interaction` beside
    `render_known_entries` because they are the same kind of thing: a pure
    function from what the vault holds to the block a leaf carries.
    """
    root = _bound_vault(vault_root)
    roster = _roster_snapshot()
    projection = pub.read_projection(root) or {}
    landmarks = _known_landmarks()
    return {
        "roster": li.render_roster(roster, landmarks=landmarks),
        "known_spans": li.render_known_spans(projection),
        "age_frames": li.render_age_frames(projection),
    }


# --------------------------------------------------------------------------
# The host-run reading protocol (Cut 6f, ADR 0033 amendment)
# --------------------------------------------------------------------------
#
# A host that cannot let this package call a model (staging's package sandbox
# has no AI provider, by design) can still produce the IDENTICAL proposal: it
# asks the package for the prompt `propose` would have sent, makes the call
# itself through its own router, and hands the completion back. TWO doors, one
# each way, because after R6 there is ONE reading:
#
#   1. :func:`host_reading_prompt` — the reading's prompt, exactly as
#      `propose` composes it. Calls no model, writes nothing.
#   2. :func:`propose_from_completions` — `propose` itself, driven by the
#      completion a host already made instead of a live `call`. Writes the
#      proposal exactly as `propose` always has.
#
# Cut 6c's three doors were the three-pass shape's: a listener prompt, the
# per-domain recorder prompts its own completion implied, then the run. R6
# deleted the passes and this protocol shrank with them —
# `host_recorder_prompts` and `--listener-completion` are gone rather than
# kept as aliases, because a host threading a listener completion into a
# reading would be threading it into nothing.
#
# Both doors read the SAME leaf `propose` reads and substitute the SAME
# values, so a host that replays this protocol gets the byte-identical
# proposal (modulo `created_at`) a package-driven call would have produced —
# `tests/test_landmark_offer_host.py` pins it against the five
# `offer_fixtures.json` goldens both ways.

#: The completion `ScriptedCall` and `landmarks_evals._RecordedCall` both
#: answer with when nothing is scripted for a prompt. The host protocol's own
#: default for the SAME reason: an unanswered prompt reads as "nothing here"
#: rather than as a crash.
EMPTY_COMPLETION = lr.EMPTY_READING_COMPLETION


def _completion_text(value: object) -> str:
    """One completion, as the TEXT a ``call`` must return.

    Mirrors `tests/test_landmark_offer.py`'s ``ScriptedCall`` and
    `landmarks_evals.py`'s ``_RecordedCall`` exactly: a completion may
    already be the raw string a model would have returned, or — as every row
    of `offer_fixtures.json` carries it, for readability — the parsed JSON
    object. Either way this is the one place that decides which, so a
    completions file can be written in whichever shape is convenient.
    """
    if value is None:
        return EMPTY_COMPLETION
    return value if isinstance(value, str) else json.dumps(value)


def _usable_completion(value: object) -> str:
    """A completion's text, refused where it is not JSON at all.

    A host that could not get a parseable response out of its own model call
    is exactly the failure `propose` already has a class for
    (:data:`FAILURE_CLASSES`) — raising here, rather than handing the
    package prose it can only degrade to an empty reading, is what lets that
    failure land on the proposal's own ``failure`` field instead of quietly
    reading as "the person said nothing datable". The same lenient parse
    `landmark_reading.parse_reading` applies (a fenced code block strips) runs
    here first, so a completion it would accept is never refused by this
    earlier gate.
    """
    text = _completion_text(value)
    body = text.strip()
    if body.startswith("```"):
        body = body.split("\n", 1)[-1].rsplit("```", 1)[0]
    try:
        json.loads(body)
    except (ValueError, TypeError) as exc:
        raise LandmarkOfferError(
            "content_ambiguity",
            f"host completion is not usable JSON: {exc}") from exc
    return text


def host_completions_call(completions: object):
    """The ``call(prompt, model) -> str`` a host builds from the prompt it has
    already answered — what :func:`propose_from_completions` runs `propose`
    with.

    There is exactly one prompt per submission (R9), so there is no dispatch:
    whatever `propose` asks, the host's ONE reading completion answers.
    """
    payload = completions if isinstance(completions, dict) else {}
    reading = payload.get("reading")

    def _call(prompt: str, model: str) -> str:  # noqa: ARG001 — `call`'s shape
        return _usable_completion(reading)

    return _call


def _prompt_row(prompt: str, *, extractor: dict) -> dict:
    return {"prompt": prompt, "model": extractor.get("model") or "",
            "prompt_version": extractor.get("prompt_version")}


def host_reading_prompt(text: str, vault_root: object = None, *,
                        model: object = None, landmarks: object = None,
                        roster: object = None,
                        framework_root: str | Path | None = None) -> dict:
    """Step 1 of the host-run protocol: the reading's prompt. Calls no model;
    writes nothing.

    The exact prompt `propose` would send to `call` — same leaf, same
    substitutions, same domain digest, same known-entries and roster rendering
    (`landmark_reading.build_reading_prompt`). ``landmarks``/``roster`` are the
    vault context a host may already hold (`propose`'s own keywords); left
    unset, this reads the bound vault's, the way ``--propose`` always has.

    Returns ``{"reading": {"prompt", "model", "prompt_version"}}`` —
    ``prompt_version`` is `landmark_reading.reading_extractor`'s, the same
    block `propose`'s own ``extractors[]`` carries for this pass.
    """
    body = str(text or "")
    if landmarks is None or roster is None:
        _bound_vault(vault_root)
        landmarks = _known_landmarks() if landmarks is None else landmarks
        roster = _roster_snapshot() if roster is None else roster
    role = str(model or lr.DEFAULT_READING_ROLE)
    prompt = lr.build_reading_prompt(body, landmarks=landmarks, roster=roster,
                                     framework_root=framework_root)
    extractor = lr.reading_extractor(role, framework_root=framework_root)
    return {"reading": _prompt_row(prompt, extractor=extractor)}


def propose_from_completions(text: str, vault_root: object,
                             completions: object, *, model: object = None,
                             now: object = None, write: bool = True,
                             landmarks: object = None, roster: object = None,
                             generation: object = None,
                             framework_root: str | Path | None = None) -> dict:
    """Step 2 of the host-run protocol: `propose`, driven by the completion a
    host already made rather than by a live model call.

    ``completions`` is exactly ``{"reading": <completion>}`` — the one
    completion :func:`host_reading_prompt` handed the host, either the raw
    completion TEXT or its parsed JSON object
    (:func:`host_completions_call`'s own reader). Runs `propose` with a
    ``call`` built from exactly that, so a host that cannot let the package
    call a model still produces the SAME proposal a package-driven call would
    have — deterministically, byte-identical modulo ``created_at``.

    Writes the proposal exactly as `propose` always has, INCLUDING a
    ``state: failed`` one: a host completion `propose` could not use (unusable
    JSON where the reading needed an answer) still leaves the submitted text
    durable in a written document, which is R3's whole point — a person's
    words must never be lost to a host's own extraction trouble, on submit.
    """
    call = host_completions_call(completions)
    return propose(text, vault_root, call=call, model=model, now=now,
                   write=write, landmarks=landmarks, roster=roster,
                   generation=generation, framework_root=framework_root)


def load_host_context(path: str | Path) -> dict:
    """The ``--context`` file: ``{"landmarks", "roster", "generation"}``, the
    same three keywords `propose` itself accepts — so a host that already
    holds the vault context can hand it over instead of this module reading
    the vault a second time.
    """
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise LandmarkOfferError("unsupported_input",
                                 f"unreadable context file: {exc}") from exc
    if not isinstance(data, dict):
        raise LandmarkOfferError("unsupported_input",
                                 f"context must be a JSON object: {path}")
    return data


# --------------------------------------------------------------------------
# CLI — the stdin-text path `lifehug.py landmark-offer` dispatches to
# --------------------------------------------------------------------------

def _unit_ids_from(args, proposal: dict) -> list[str]:
    if getattr(args, "all_units", False):
        return [unit["unit_id"] for unit in (proposal.get("units") or ())
                if isinstance(unit, dict) and unit.get("unit_id")]
    raw = getattr(args, "units", "") or ""
    return [piece.strip() for piece in raw.split(",") if piece.strip()]


def main(argv: list[str] | None = None) -> int:
    """``landmark_offer.py --propose|--apply <id>|--retract <id>``.

    ``--propose`` reads the text on stdin and prints the proposal as JSON.
    ``--dry-run`` prints the composed reading prompt and calls nothing, which
    is how a host verifies its own REPLAY against this leaf without spending a
    completion.

    **The host-run reading protocol (Cut 6f, ADR 0033 amendment)** adds two
    more shapes to ``--propose``, for a host that cannot let this process call
    a model itself (staging's package sandbox, by design, has none):

    * ``--prompts`` prints the ONE reading prompt and calls nothing —
      :func:`host_reading_prompt`.
    * ``--completions FILE`` runs `propose` from the ``{"reading": …}``
      completion a host already made and WRITES the proposal, exactly as a
      package-driven ``--propose`` does — :func:`propose_from_completions`.

    Cut 6c's ``--listener-completion`` is REMOVED with the pass it named
    (R6): there is one reading, so there is nothing for a listener completion
    to imply.

    ``--context FILE`` (any of the three) hands over ``{"landmarks",
    "roster", "generation"}`` a host already holds, so this module need not
    read the vault a second time for context it was already given.

    **Exit code, every shape that can write a proposal:** 0 whenever a
    proposal document was written, whatever its ``state`` — including
    ``failed`` — because R3 makes the submitted text durable the moment it is
    submitted, and a host that retries on a nonzero exit must never re-lose
    it. 1 only when no document could be produced at all (unreadable input,
    an unbound vault, a write failure) — those raise :class:`LandmarkOfferError`
    and are caught below.
    """
    import argparse  # noqa: PLC0415

    parser = argparse.ArgumentParser(description="Add Landmark — the offer mode")
    parser.add_argument("--propose", action="store_true")
    parser.add_argument("--apply", dest="apply_id", default=None)
    parser.add_argument("--retract", dest="retract_id", default=None)
    parser.add_argument("--units", default="")
    parser.add_argument("--all", dest="all_units", action="store_true")
    parser.add_argument("--from-file", dest="from_file", default=None)
    parser.add_argument("--reason", default=None)
    parser.add_argument("--model", default=None)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--prompts", action="store_true",
                        help="print the host-run reading prompt; call no "
                             "model, write nothing")
    parser.add_argument("--context", default=None,
                        help="a JSON file of {landmarks, roster, generation}")
    parser.add_argument("--completions", default=None,
                        help="a JSON file of {reading: <completion>} a host "
                             "already made; runs and writes the proposal "
                             "from it")
    args = parser.parse_args(argv)

    from lifehug_core import REPO_DIR  # noqa: PLC0415

    root = REPO_DIR
    try:
        if args.retract_id:
            print(json.dumps(retract(args.retract_id, root,
                                     reason=args.reason), indent=2,
                             sort_keys=True))
            return 0
        if args.apply_id:
            proposal = read_proposal(root, args.apply_id)
            unit_ids = _unit_ids_from(args, proposal)
            print(json.dumps(apply(args.apply_id, unit_ids, root,
                                   reason=args.reason), indent=2,
                             sort_keys=True))
            return 0

        context = load_host_context(args.context) if args.context else {}
        landmarks_ctx = context.get("landmarks")
        roster_ctx = context.get("roster")
        generation_ctx = context.get("generation")

        if args.completions:
            text = (Path(args.from_file).read_text(encoding="utf-8")
                    if args.from_file else sys.stdin.read())
            completions = json.loads(Path(args.completions).read_text(
                encoding="utf-8"))
            proposal = propose_from_completions(
                text, root, completions, model=args.model,
                landmarks=landmarks_ctx, roster=roster_ctx,
                generation=generation_ctx)
            print(json.dumps(proposal, indent=2, sort_keys=True))
            return 0

        if args.prompts:
            text = (Path(args.from_file).read_text(encoding="utf-8")
                    if args.from_file else sys.stdin.read())
            output = host_reading_prompt(text, root, model=args.model,
                                         landmarks=landmarks_ctx,
                                         roster=roster_ctx)
            print(json.dumps(output, indent=2, sort_keys=True))
            return 0

        text = (Path(args.from_file).read_text(encoding="utf-8")
                if args.from_file else sys.stdin.read())
        if args.dry_run:
            print(host_reading_prompt(text, root, model=args.model,
                                      landmarks=landmarks_ctx,
                                      roster=roster_ctx)["reading"]["prompt"])
            return 0
        from ai_provider import call_ai  # noqa: PLC0415

        proposal = propose(text, root, call=call_ai, model=args.model)
        print(json.dumps(proposal, indent=2, sort_keys=True))
        # R3: a WRITTEN proposal is durable regardless of its state, so a
        # `failed` reading is not a nonzero exit — see this function's own
        # docstring.
        return 0
    except LandmarkOfferError as exc:
        print(json.dumps({"error": str(exc), "class": exc.code}, indent=2))
        return 1
    except (OSError, ValueError) as exc:
        print(json.dumps({"error": str(exc), "class": "unsupported_input"},
                         indent=2))
        return 1


__all__ = [
    "COLLECT_MODE",
    "EMPTY_COMPLETION",
    "FAILURE_CLASSES",
    "LandmarkOfferError",
    "MODES",
    "OFFERS_DIR",
    "OFFER_GATE_PREFIX",
    "OFFER_LINT_CLASSES",
    "OFFER_MODE",
    "OFFER_RECEIPTS_DIR",
    "OFFER_STATES",
    "PROPOSAL_STATES",
    "UNIT_KEYS",
    "UNIT_KIND_BY_DOMAIN",
    "annotate_against_known",
    "annotate_entities",
    "claim_evidence_text",
    "apply",
    "DATE_KEYS",
    "EVENT_KEYS",
    "GROUP_KEYS",
    "MEMBER_KINDS",
    "UNIT_BASES",
    "UNPLACED_GROUP",
    "build_groups",
    "group_members",
    "group_slice",
    "group_source_relative_path",
    "date_evidence",
    "derive_event_id",
    "derive_proposal_id",
    "derive_story_id",
    "derive_receipt_id",
    "derive_unit_id",
    "grammar_units",
    "host_completions_call",
    "host_reading_prompt",
    "inherit_dates",
    "landmark_opportunity_id",
    "lint_offer_proposal",
    "lint_offer_reply",
    "load_host_context",
    "OFFER_TURN_PROMPT",
    "build_offer_turn",
    "load_offer_leaf",
    "offer_context",
    "open_claim_questions",
    "open_event_claims",
    "open_opportunity_ids",
    "opportunity_ids_for",
    "propose",
    "propose_from_completions",
    "read_offer_receipt",
    "read_proposal",
    "receipt_is_retracted",
    "render_event",
    "render_group",
    "render_open_questions",
    "render_proposal",
    "render_story",
    "render_unit",
    "retire_matching_opportunity",
    "retract",
    "source_spans",
    "unit_filing_digest",
    "unit_source_relative_path",
]


if __name__ == "__main__":
    raise SystemExit(main())
