#!/usr/bin/env python3
"""Every classifier moment becomes a source-backed claim.

Timeline Fix 05 item 8.1 (contract: lifehug-platform `docs/pr-specs/
timeline-fix/05-one-timeline.md`; controlling designs `docs/design/eras.md`
§5.1/§5.6 and `docs/design/temporal-claims.md`). The owner read his own
Timeline on 2026-08-29 and found TWO of them: a calculated view holding 33
nodes derived from the claim substrate, and, below it, a legacy band list
holding 399 keyword-placed moments in nine bands every one of which honestly
said *undated*. Two "Childhood" rows, and no way to tell which was his life.

The two lists are the BEFORE and AFTER of a migration the design named in
§5.6 ("the legacy path is transitional — exit issue: migrate classifier
moments to source-backed nodes") and nobody built. This module is that
migration, and its whole principle is one sentence:

    classifier moments become CLAIMS, not hand-made nodes.

That is what makes it cheap and what makes it honest. The fold already turns
claims into nodes, so there is still ONE node minter
(`temporal_projection.derive_node_id`), ONE writer of the projection
(`temporal_publication.publish`) and ONE resolver of who a subject is
(`temporal_timeline._resolve_subjects`). This module adds no fourth. It reads
the classifier's output and files evidence; everything downstream is
unchanged machinery doing what it already did.

WHAT IT READS. The RAW classification (`classify_story.current_classification_files`
— the one iterator, so a stale classification is withheld here exactly as it
is withheld from every other reader). Raw, because `timeline.load_events()`
DROPS the document's `places` and `people` and this migration needs them:
places are the evidence a later co-location rule will place an undated moment
with (Timeline Fix 05 §8.3), and the people are how an event that happened to
somebody else stays off the owner's axis.

WHAT IT WRITES. One `ExtractionReceipt` per classifier EVENT, holding one
`TemporalClaim`, plus — when a source has been re-classified — one supersession
correction retiring the claims of the reading that no longer stands. Nothing
else. It never edits `state/classifications/`, never re-classifies anything,
never calls a model, and never redraws `state/landmarks.json` (a filing step
never redraws — CLAUDE.md's rule, learned on lifehug-platform#680).

WHY ONE RECEIPT PER EVENT AND NOT PER DOCUMENT. The contract asked for one
receipt per classification document. `temporal_claims.CLAIM_IDENTITY_KEYS` is
FROZEN at (claim_type, subject_key, event_kind, temporal_identity, source_ref,
extractor_version) and says out loud that nothing joins it without a schema
version bump and a documented re-identification. Two undated moments narrated
in one story share every one of those keys — same source, same subject, same
`moment` kind, and no temporal value to tell them apart — so filing them under
one source revision would derive ONE claim id for both and
`validate_extraction_receipt` would refuse the receipt as holding a duplicate
claim. The unit of source is therefore the unit of assertion, exactly as it
already is for landmark entries (`landmark_projection` promotes one source per
FILED RECORD, not one per entry). Each event gets its own `source_id` —
``classification:<stem>#<12 hex of the event's own words>`` — while
``source_path`` still points at the STORY the person told, so every claim
cites a vault source (owner amendment Q2/option B) and the recorder dedupe
below still joins on the story.

IDEMPOTENCY, which is the property everything else rests on. The receipt path
is a pure function of (source_id, revision, extractor version); the CLAIMS the
receipt asserts are a pure function of the classification's own bytes; and
`temporal_store.write_receipt` keeps what is already on disk. So a second run
writes nothing, the fold is unchanged, and `publish` republishes the same
generation. `tests/test_classifier_claims.py` proves it on the bytes of
`active-index.json` and `calculated-timeline.json` rather than asserting it.

That holds ACROSS FRAMEWORK VERSIONS, which is the part a single-version test
cannot see. The receipt's `extractor` block is this extraction's own
declaration about itself, and a later version legitimately declares more about
the identical claims — event identity I1 (v267) wired `telling_keys` and
`document_revision` into it, so every classifier receipt filed before v267
would otherwise have re-derived DIFFERENT bytes at its own identity and made
this migration crash on any vault that had already run it. It does not: the
declaration is annotation (`temporal_store.RECEIPT_ANNOTATION_KEYS`), the
filed receipt stands as filed, and the run counts it in `receipts_kept`. A
receipt is never back-dated into declaring something nobody declared when it
was written; the conservative reading of a missing declaration is the one
`event_identity.UNDECLARED_DOCUMENT_REVISION` already names.

SUPERSESSION, never an edit. A re-classification produces new bytes, so a new
`revision`, so a new receipt beside the old one — the store refuses to rewrite
a receipt and that refusal is the point. The prior reading is retired by a
filed `supersede` correction naming its claims, which is a durable source
record with its own idempotent digest. Nothing is deleted; the old claims stay
readable with `status: superseded` and the reason they stopped standing.

THE RECORDER IS CANONICAL (CLAUDE.md paradigm 9). Where a story's own words
were already heard by the landmark recorder or the general listener, those
claims stand and the classifier does not re-mint a rival: a classifier event
whose asserted date INTERSECTS a claim another extractor filed against the same
`source_path` is skipped and counted. The classifier still contributes the
moments nobody recorded, which is the entire 700-odd it is here for.

WHAT IT REFUSES TO INVENT, by name:

* **`when_hint` is never parsed.** It is free text ("sixth grade", "two weeks
  after the wedding") and `chronology.parse_age` is a FIELD parser, not a
  free-text detector: run over that field it reads *"two weeks after the
  wedding"* as age 2 and *"1985"* as age 5. The hint rides as evidence and
  dates nothing.
* **The free-text `anchor` is never an ordering claim.** The classifier's own
  prompt calls it "the nearest landmark", and *nearest* does not assert
  *during*. Only the structured `date.anchor_ref` becomes a `relative_order`
  claim, and its relation defaults to `within` exactly as
  `chronology.record_from_claim` already defaults a bare anchor to "during".
* **A subject is never read out of prose.** The event's own subject/people
  field names another actor or the subject is the owner. Guessing an actor
  from a description is a model call wearing a rule's clothes, and it is how
  somebody else's life ends up drawn as the owner's.
* **No date is ever fabricated.** An event with nothing datable becomes an
  `occurrence` claim — it happened, and when is not known — and the fold mints
  it a node with no value, which is what "not placed yet" means.
"""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path

SYSTEM_DIR = Path(__file__).resolve().parent
if str(SYSTEM_DIR) not in sys.path:
    sys.path.insert(0, str(SYSTEM_DIR))

import chronology as chrono  # noqa: E402
import classify_story  # noqa: E402
import event_identity as ei  # noqa: E402
import landmark_projection as lp  # noqa: E402
import temporal_claims as tc  # noqa: E402
import temporal_publication as pub  # noqa: E402
import temporal_store as store  # noqa: E402
import temporal_work_items as twi  # noqa: E402
from temporal_claims import (  # noqa: E402
    TemporalContractError,
    bounded_quote,
    collapsed_text,
    normalized_mention_key,
    optional_text,
)

# --------------------------------------------------------------------------
# Identity of this extractor and of the things it reads
# --------------------------------------------------------------------------

#: A DETERMINISTIC rule, and the extractor version says so: no model, no
#: prompt, no temperature. `temporal_claims.extractor_version_string` is the
#: one spelling, so "which extractor produced this" stays comparable.
EXTRACTOR_NAME = "classifier-claims"
RULE_VERSION = "1"
CLASSIFIER_EXTRACTOR = tc.extractor_version_string(
    EXTRACTOR_NAME, rule_version=RULE_VERSION
)

#: ``classification:<stem>#<event key>``. The prefix is what tells this
#: module's own claims apart from every other extractor's when it looks for
#: readings to supersede, and it is what the recorder-dedupe below uses to
#: know which claims are NOT its own.
SOURCE_ID_PREFIX = "classification"

#: The claims are read out of a record the classifier already wrote, exactly
#: as `landmark_projection`'s legacy import reads a filed entry: ``import``.
SOURCE_KIND = "import"

#: What a classifier event IS when it says nothing more specific. `moment` is
#: not in `temporal_claims.EVENT_KINDS`' seed set and does not need to be —
#: that set is explicitly a seed, `EVENT_KIND_RE` is the gate, and
#: `temporal_timeline.KIND_SENTENCES` already falls through to its ``None``
#: row, which titles a node ``{what}`` and asks "When did {what} happen?".
MOMENT_EVENT_KIND = "moment"

#: Hex characters of the event digest that separate one moment from another
#: inside one story. 48 bits over (title, description) within a single
#: classification.
EVENT_KEY_LENGTH = 12

#: `chronology.RELATIONS` -> `temporal_claims.CONSTRAINT_RELATIONS`. The two
#: vocabularies are deliberately different (one compares date records, one
#: places nodes) and this is the one crossing.
RELATION_BY_DATE_RELATION = {
    "before": "before",
    "after": "after",
    "during": "within",
}

#: What `chronology.record_from_claim` already does with an anchor whose
#: relation the person did not give. Re-stated here rather than re-decided.
DEFAULT_ANCHOR_RELATION = "within"

#: An age STATEMENT is what the person said about their age. These two are
#: calibrated the way `landmark_projection.CONFIDENCE_SCORE` calibrates a
#: date record's own confidence word: ordinal, never a substitute for basis.
AGE_CLAIM_CONFIDENCE = 0.7
ORDER_CLAIM_CONFIDENCE = 0.45
#: An occurrence asserts only that it happened, which the person's own telling
#: makes as certain as the telling. It carries no date, so this number never
#: competes with one.
OCCURRENCE_CLAIM_CONFIDENCE = 0.9

#: The subject when the event is the owner's own. `temporal_work_items` owns
#: the string; reading it from there is what keeps the fold's owner rule and
#: this module's default the same person.
OWNER_SUBJECT_REF = twi.OWNER_SUBJECT_REF

#: Event-level keys a classification may carry that name WHO the event
#: happened to. The current classify prompt has none of them — people are
#: document-level — and older/hand-edited classifications do, so they are read
#: tolerantly and their absence simply means "the owner's own moment".
EVENT_SUBJECT_KEYS = ("subject", "subject_mention", "who")
EVENT_PEOPLE_KEYS = ("people", "persons")
#: Event-level and document-level place lists, in the order they are preferred.
EVENT_PLACE_KEYS = ("places", "place", "locations")

#: The reason string of the supersession correction, as a format. It is part
#: of the correction's identity digest, so it is deterministic on purpose: the
#: same re-classification filed twice is ONE correction.
SUPERSEDE_REASON = (
    "{stem} was re-classified; the reading at {revisions} no longer stands. "
    "The current reading is filed at {revision}."
)
SUPERSEDE_SCOPE = "classifier_reclassification"


class ClassifierClaimsError(TemporalContractError):
    """A classification cannot be read into claims."""


ERROR_CODES = (
    "classification_not_a_mapping",
    "classification_stem_required",
)


# --------------------------------------------------------------------------
# Pure derivations — every one a function of the classification's own bytes
# --------------------------------------------------------------------------


def classification_revision(data: object) -> str:
    """``sha256:<64 hex>`` over the classification's canonical bytes.

    Canonical rather than the file's literal bytes so that re-writing the same
    interpretation with different whitespace is not a re-classification. What
    the file SAYS is the revision; how it is spelled is not.
    """
    if not isinstance(data, dict):
        raise ClassifierClaimsError(
            "classification_not_a_mapping", "a classification must be an object"
        )
    digest = hashlib.sha256(lp.canonical_json(data).encode("utf-8")).hexdigest()
    return f"sha256:{digest}"


def event_key(event: object) -> str:
    """The 12-hex key separating one moment from another inside one story.

    Over the event's own WORDS — its title and its description — rather than
    its index in the list, so that a re-classification that reorders the events
    does not re-identify every one of them, and two byte-identical events in
    one document are one moment (which is what they are).
    """
    row = event if isinstance(event, dict) else {}
    payload = {
        "title": collapsed_text(row.get("title")),
        "description": collapsed_text(row.get("description")),
    }
    return hashlib.sha256(
        lp.canonical_json(payload).encode("utf-8")
    ).hexdigest()[:EVENT_KEY_LENGTH]


def event_source_id(stem: object, event: object) -> str:
    """``classification:<stem>#<event key>`` — this moment's source identity."""
    text = collapsed_text(stem)
    if not text:
        raise ClassifierClaimsError(
            "classification_stem_required", "a classification is identified by its file stem"
        )
    return f"{SOURCE_ID_PREFIX}:{text}#{event_key(event)}"


def document_revision(vault_root: str | Path, source_path: object) -> str | None:
    """The STORY's own revision — the thing a PERSON corrects (event identity I1).

    C1 named this gap and carried it forward rather than papering over it: a
    claim cites the CLASSIFICATION's revision, which moves whenever the model
    rewords a title, so without a separately declared document revision the
    telling manifest cannot tell a model rewording (design §3.1 case 2) from a
    human source correction (case 4) and conservatively re-keys nothing.

    The story file's own ``content_sha256`` is exactly the missing fact, and
    `temporal_store.read_source_ref` is the one reader of it. A source that
    cannot be read, or whose bytes have drifted under the claims that cite it,
    yields ``None`` — the conservative reading stays, loudly, as
    ``telling_document_revision_undeclared`` rather than as a guessed digest.
    """
    try:
        ref = store.read_source_ref(vault_root, collapsed_text(source_path))
    except TemporalContractError:
        return None
    return ref.revision if ref is not None else None


def is_classifier_source_id(value: object) -> bool:
    """Is this source id one of THIS extractor's? (Never a text match on the
    extractor version, which a caller could spell three ways.)"""
    return collapsed_text(value).startswith(f"{SOURCE_ID_PREFIX}:")


def classification_source_prefix(stem: object) -> str:
    """Every event of one classification shares this source-id prefix."""
    return f"{SOURCE_ID_PREFIX}:{collapsed_text(stem)}#"


def event_source_ref(
    *, stem: object, event: object, revision: object, source_path: object
) -> dict:
    """The claim's source: this moment, of this classification, of that story."""
    return tc.validate_source_ref(
        {
            "source_id": event_source_id(stem, event),
            "revision": revision,
            "source_path": collapsed_text(source_path),
        }
    )


def moment_title(event: object) -> str:
    """What the person would call this moment — the classifier's noun phrase.

    `timeline.event_title` is the ONE fallback in this package for an event
    with no title (every pre-v195 classification), so it is called rather than
    re-implemented. The result becomes the claim's ``event_mention``, which is
    what `temporal_timeline._node_what` reads — so the node's title and every
    question about it read the moment's own words instead of ``I — moment``.
    """
    import timeline  # noqa: PLC0415 — avoids an import cycle at load

    row = event if isinstance(event, dict) else {}
    title = timeline.event_title(row)
    return collapsed_text(title)[: tc.MAX_EVENT_MENTION_CHARS]


def event_place_mentions(event: object, document_places: object = ()) -> tuple[str, ...]:
    """The places this moment names — its own first, the document's after.

    The document's places are included because the current classify prompt
    records places at document level only, and a story about one afternoon in
    Mesa names Mesa exactly once. They are EVIDENCE for a later co-location
    rule and never a date; carrying them here is what makes that rule a pure
    fold over claims instead of a second reader of the classifier.
    """
    names: list[str] = []
    row = event if isinstance(event, dict) else {}
    for key in EVENT_PLACE_KEYS:
        names.extend(_place_names(row.get(key)))
    names.extend(_place_names(document_places))
    return tc.normalized_place_mentions(names)


def _place_names(value: object) -> list[str]:
    """``[{"name": "Mesa"}, "Yucaipa"]`` -> ``["Mesa", "Yucaipa"]``."""
    if isinstance(value, (str, bytes)):
        value = [value]
    names: list[str] = []
    for item in (value or ()):
        if isinstance(item, dict):
            text = collapsed_text(item.get("name") or item.get("place"))
        else:
            text = collapsed_text(item)
        if text and len(text) <= tc.MAX_PLACE_MENTION_CHARS:
            names.append(text)
    return names


def event_subject_mention(event: object) -> str:
    """WHO this moment happened to — the owner unless the event says otherwise.

    Only the EVENT's own subject/people field can move the subject off the
    owner. A document-level person list describes the story, not the moment,
    and attributing a moment to a relative because they appear elsewhere in the
    same story is exactly the "a relative's unrelated history rides in on a
    stated relationship" defect eras §5 forbids.

    The mention is left RAW. Resolving it against the roster is
    `temporal_timeline._resolve_subjects`' job — the one resolver — and a
    second copy here would be a second identity, which is the one thing the
    fold promises never to have. What the fold does with a named other person
    is already decided: `_owner_relevance` gives it
    ``occurrence_subject_scope: other_person`` and keeps it off the owner's
    axis unless a landmark entry makes it owner-relevant.
    """
    row = event if isinstance(event, dict) else {}
    for key in EVENT_SUBJECT_KEYS:
        text = collapsed_text(row.get(key))
        if text and len(text) <= tc.MAX_SUBJECT_MENTION_CHARS:
            if len(tc.split_subject_enumeration(text)) == 1:
                return text
    for key in EVENT_PEOPLE_KEYS:
        for name in _place_names(row.get(key)):
            if len(name) <= tc.MAX_SUBJECT_MENTION_CHARS and \
                    len(tc.split_subject_enumeration(name)) == 1:
                return name
    return OWNER_SUBJECT_REF


def _age_band_text(value: object) -> str | None:
    """The age the person stated, or ``None`` — with the year trap closed.

    `chronology.parse_age` is a FIELD parser: handed *"1985"* it answers
    "age 5". That is correct for a field the classifier filled with an age and
    catastrophic for anything else, so a value carrying a four-digit year is
    refused here rather than filed as a childhood.
    """
    text = optional_text(value)
    if not text:
        return None
    if chrono.YEAR_RE.search(text):
        return None
    return text if chrono.parse_age(text) is not None else None


def temporal_reading(event: object) -> dict:
    """What this moment asserts about time: ``{claim_type, temporal_value,
    basis, confidence}``. Deterministic, and never a fabrication.

    In order, and each rung is the person's own words read through
    `chronology` — never a second parser:

    1. a date they SAID (`date.stated`) -> a ``date`` claim, ``explicit``;
    2. their AGE at the time (`date.age`) -> an ``age`` claim, ``explicit``;
       the fold turns it into an interval against the birth origin, and the
       interval it produces is the calculated one;
    3. the LANDMARK they dated it against (`date.anchor_ref`) -> a
       ``relative_order`` claim, ``explicit``; a missing relation defaults to
       ``within``, which is what `chronology.record_from_claim` already does
       with a bare anchor;
    4. nothing datable -> an ``occurrence`` claim. It happened. When is not
       known, and saying so is the whole reason that type exists.
    """
    row = event if isinstance(event, dict) else {}
    claim = chrono.possible_date_claim(row.get("date"))
    if claim:
        stated = optional_text(claim.get("stated"))
        if stated:
            record = chrono.parse_edtf(stated, basis="stated")
            if record is not None:
                return {
                    "claim_type": "date",
                    "temporal_value": record.to_dict(),
                    "basis": "explicit",
                    "confidence": lp.CONFIDENCE_SCORE.get(record.confidence, 0.45),
                }
        age = _age_band_text(claim.get("age"))
        if age:
            return {
                "claim_type": "age",
                "temporal_value": age,
                "basis": "explicit",
                "confidence": AGE_CLAIM_CONFIDENCE,
            }
        anchor_ref = optional_text(claim.get("anchor_ref"))
        if anchor_ref:
            relation = RELATION_BY_DATE_RELATION.get(
                collapsed_text(claim.get("relation")), DEFAULT_ANCHOR_RELATION
            )
            return {
                "claim_type": "relative_order",
                "temporal_value": {"relation": relation, "anchors": [anchor_ref]},
                "basis": "explicit",
                "confidence": ORDER_CLAIM_CONFIDENCE,
            }
    return {
        "claim_type": tc.OCCURRENCE_CLAIM_TYPE,
        "temporal_value": None,
        "basis": "explicit",
        "confidence": OCCURRENCE_CLAIM_CONFIDENCE,
    }


def event_evidence(event: object) -> list[dict]:
    """The bounded quotation behind the claim, and the hint that dates nothing.

    The description is the words the classifier read the moment out of. The
    ``when_hint`` rides along in the SAME quotation rather than as a parsed
    value, so "sixth grade" is visible to a person looking at the claim and
    invisible to the arithmetic.
    """
    row = event if isinstance(event, dict) else {}
    description = collapsed_text(row.get("description"))
    hint = collapsed_text(row.get("when_hint"))
    anchor = collapsed_text(row.get("anchor"))
    trailer = "; ".join(
        part for part in (
            f"when_hint: {hint}" if hint else "",
            f"anchor: {anchor}" if anchor else "",
        ) if part
    )
    quote = f"{description} ({trailer})" if trailer else description
    return [{"quote": bounded_quote(quote), "locator": "events/description"}]


def event_claim(
    *,
    stem: object,
    event: object,
    revision: object,
    source_path: object,
    document_places: object = (),
    now: object = None,
) -> dict:
    """One classifier event -> one validated `TemporalClaim`.

    The ``event_ref`` is minted here and it is load-bearing: without it every
    ``moment`` of the owner's would group into ONE node
    (`temporal_timeline._group_claims` keys on the claim's ``event_ref`` or on
    the derived node id, and a derived id for the same kind and subject is the
    same id). It is the substrate's own minter, through
    `temporal_projection.derive_node_id`, with the moment's key as the
    discriminator — the "stable ordinal or slug" that function asks for.
    """
    import temporal_projection as tp  # noqa: PLC0415 — pure, but keeps the load light

    row = event if isinstance(event, dict) else {}
    reading = temporal_reading(row)
    source_ref = event_source_ref(
        stem=stem, event=row, revision=revision, source_path=source_path
    )
    payload = {
        "source_ref": source_ref,
        "source_kind": SOURCE_KIND,
        "claim_type": reading["claim_type"],
        "subject_mention": event_subject_mention(row),
        "event_kind": MOMENT_EVENT_KIND,
        "event_ref": tp.derive_node_id(
            node_kind="event",
            event_kind=MOMENT_EVENT_KIND,
            subject_refs=[event_subject_mention(row)],
            discriminator=event_key(row),
        ),
        "event_mention": moment_title(row),
        "temporal_value": reading["temporal_value"],
        "evidence": event_evidence(row),
        "basis": reading["basis"],
        "confidence": reading["confidence"],
        "extractor_version": CLASSIFIER_EXTRACTOR,
        "place_mentions": event_place_mentions(row, document_places),
    }
    return tc.validate_temporal_claim(payload, now=now)


def classification_events(data: object) -> list[dict]:
    """The events this classification asserts, in its own order.

    An event with no description is skipped — the same predicate
    `timeline.load_events` applies, because a moment with no words is not a
    moment anybody can be shown.
    """
    rows = (data or {}).get("events") if isinstance(data, dict) else None
    return [
        row
        for row in (rows or ())
        if isinstance(row, dict) and collapsed_text(row.get("description"))
    ]


# --------------------------------------------------------------------------
# Reading what the vault already holds
# --------------------------------------------------------------------------


def _recorder_dates_by_source_path(index: object) -> dict[str, list]:
    """``source_path -> [DateRecord, ...]`` for every ACTIVE claim that is not
    this extractor's. The recorder is canonical; this is the set it is
    canonical over."""
    dates: dict[str, list] = {}
    for claim in store.active_claims(index if isinstance(index, dict) else {}):
        ref = claim.get("source_ref")
        if not isinstance(ref, dict):
            continue
        if is_classifier_source_id(ref.get("source_id")):
            continue
        path = collapsed_text(ref.get("source_path"))
        if not path:
            continue
        record = chrono.from_dict(claim.get("temporal_value"))
        if record is None:
            continue
        dates.setdefault(path, []).append(record)
    return dates


def _claims_by_source_id(index: object) -> dict[str, list[dict]]:
    """``source_id -> [active claim rows]``, this extractor's included."""
    rows: dict[str, list[dict]] = {}
    for claim in store.active_claims(index if isinstance(index, dict) else {}):
        ref = claim.get("source_ref")
        if not isinstance(ref, dict):
            continue
        rows.setdefault(collapsed_text(ref.get("source_id")), []).append(claim)
    return rows


def _superseded_by_reclassification(
    claims_by_source_id: dict[str, list[dict]], *, stem: str, revision: str
) -> tuple[list[str], list[str]]:
    """``(claim ids, revisions)`` of this classification's PREVIOUS reading.

    Every active claim of this stem whose source revision is not the current
    one. That covers both halves of a re-classification: an event whose words
    changed (new key, so the old key is orphaned) and an event that survived
    unchanged (same key, new revision) — in both cases the earlier reading is
    of bytes that no longer exist, and a claim of bytes that no longer exist is
    not the operative reading.
    """
    prefix = classification_source_prefix(stem)
    ids: set[str] = set()
    revisions: set[str] = set()
    for source_id, rows in claims_by_source_id.items():
        if not source_id.startswith(prefix):
            continue
        for claim in rows:
            ref = claim.get("source_ref")
            if not isinstance(ref, dict):
                continue
            if collapsed_text(ref.get("revision")) == revision:
                continue
            ids.add(collapsed_text(claim.get("claim_id")))
            revisions.add(collapsed_text(ref.get("revision")))
    return sorted(i for i in ids if i), sorted(r for r in revisions if r)


def _already_recorded(claim: dict, recorder_dates: list) -> bool:
    """Did another extractor already record THIS date from THIS story?

    Intersection, not equality: the recorder filing *11 July 1981* and the
    classifier reading *1981* off the same sentence are one fact told once, and
    the recorder's is the one that stands (CLAUDE.md paradigm 9). An undated
    classifier event is never deduped — it asserts nothing the recorder could
    have said instead, and dropping it would lose the moment entirely.
    """
    record = chrono.from_dict(claim.get("temporal_value"))
    if record is None:
        return False
    return any(chrono.intersect(record, other) is not None for other in recorder_dates)


# --------------------------------------------------------------------------
# The migration
# --------------------------------------------------------------------------


def _empty_report(dry_run: bool) -> dict:
    return {
        "dry_run": bool(dry_run),
        "extractor_version": CLASSIFIER_EXTRACTOR,
        "classifications": 0,
        "events": 0,
        "claims": 0,
        "claims_by_type": {
            "date": 0, "age": 0, "relative_order": 0, tc.OCCURRENCE_CLAIM_TYPE: 0,
        },
        "dated": 0,
        "undated": 0,
        "with_place": 0,
        "subjects": {"self": 0, "named_other": 0},
        "deduped_against_recorder": 0,
        "deduped_sources": 0,
        "receipts": 0,
        "receipts_written": 0,
        "receipts_kept": 0,
        "superseded_claims": 0,
        "superseded_classifications": 0,
        "skipped_no_source_path": [],
        "skipped_source_missing": [],
        "skipped_empty_description": 0,
        "nodes_before": 0,
        "nodes_after": 0,
    }


def migrate_classifier_moments(
    vault_root: str | Path,
    *,
    classifications_dir: object = None,
    sources: object = None,
    dry_run: bool = True,
    publish: bool = True,
    now: object = None,
) -> dict:
    """File every current classifier moment as a claim. Idempotent; pure input.

    ``dry_run`` writes NOTHING and returns the same report, so the counts can
    be read before the vault moves — the same convention `era-migrate` and
    `focus-autopilot` use.

    ``sources`` restricts the run to named story ``source_path`` values (the
    classify job's successor re-runs the migration for the one source it just
    classified). ``None`` is every current classification.
    """
    root = Path(str(vault_root))
    report = _empty_report(dry_run)
    wanted = {collapsed_text(s) for s in (sources or ())} or None

    index = store.fold_active_index(root)
    recorder_dates = _recorder_dates_by_source_path(index)
    claims_by_source_id = _claims_by_source_id(index)
    projection = pub.read_projection(root) or {}
    report["nodes_before"] = len(projection.get("nodes") or ())
    known_nodes = {
        collapsed_text(node.get("node_id"))
        for node in (projection.get("nodes") or ())
        if isinstance(node, dict)
    }

    directory = (
        Path(str(classifications_dir))
        if classifications_dir is not None
        else classify_story.CLASSIFICATIONS_DIR
    )
    receipts: list[dict] = []
    corrections: list[dict] = []
    new_nodes: set[str] = set()

    for path, data in classify_story.current_classification_files(directory):
        stem = path.stem
        source_path = collapsed_text((data or {}).get("source_path"))
        if wanted is not None and source_path not in wanted:
            continue
        report["classifications"] += 1
        if not source_path:
            report["skipped_no_source_path"].append(stem)
            continue
        if not store.store_path(root, source_path).is_file():
            report["skipped_source_missing"].append(stem)
            continue

        revision = classification_revision(data)
        # Event identity I1: declared once per classification, not once per
        # event — every event of one story shares the story.
        story_revision = document_revision(root, source_path)
        events = classification_events(data)
        report["skipped_empty_description"] += len(
            (data or {}).get("events") or ()
        ) - len(events)
        report["events"] += len(events)
        places = (data or {}).get("places") or ()
        deduped_here = 0

        for event in events:
            claim = event_claim(
                stem=stem, event=event, revision=revision,
                source_path=source_path, document_places=places, now=now,
            )
            if _already_recorded(claim, recorder_dates.get(source_path) or ()):
                report["deduped_against_recorder"] += 1
                deduped_here += 1
                continue
            report["claims"] += 1
            kind = claim["claim_type"]
            report["claims_by_type"][kind] = report["claims_by_type"].get(kind, 0) + 1
            if kind == tc.OCCURRENCE_CLAIM_TYPE:
                report["undated"] += 1
            else:
                report["dated"] += 1
            if claim.get("place_mentions"):
                report["with_place"] += 1
            if normalized_mention_key(claim["subject_mention"]) == \
                    normalized_mention_key(OWNER_SUBJECT_REF):
                report["subjects"]["self"] += 1
            else:
                report["subjects"]["named_other"] += 1
            node_ref = collapsed_text(claim.get("event_ref"))
            if node_ref and node_ref not in known_nodes:
                new_nodes.add(node_ref)
            receipts.append(
                {
                    "source_ref": claim["source_ref"],
                    "extractor_version": CLASSIFIER_EXTRACTOR,
                    "extractor": ei.declare_tellings(
                        {
                            "name": EXTRACTOR_NAME,
                            "rule_version": RULE_VERSION,
                            "deterministic": True,
                        },
                        telling_keys={
                            claim["claim_id"]: ei.classifier_telling_ref(stem, event),
                        },
                        document_revision=story_revision,
                    ),
                    "claims": [claim],
                    "recorder": "classifier_claims",
                }
            )
        if deduped_here:
            report["deduped_sources"] += 1

        stale_ids, stale_revisions = _superseded_by_reclassification(
            claims_by_source_id, stem=stem, revision=revision
        )
        if stale_ids:
            report["superseded_claims"] += len(stale_ids)
            report["superseded_classifications"] += 1
            corrections.append(
                {
                    "claim_ids": stale_ids,
                    "reason": SUPERSEDE_REASON.format(
                        stem=stem,
                        revisions=", ".join(stale_revisions),
                        revision=revision,
                    ),
                }
            )

    report["receipts"] = len(receipts)
    report["skipped_no_source_path"].sort()
    report["skipped_source_missing"].sort()

    if dry_run:
        report["nodes_after"] = report["nodes_before"] + len(new_nodes)
        return report

    for receipt in receipts:
        # A receipt identity that is already filed is KEPT, not re-derived onto
        # disk: the unit of assertion is the source revision, and this run is
        # asserting nothing the filed receipt does not already say. Counted, so
        # the no-op is visible in the report rather than inferred from a zero.
        before = store.store_path(root, tc.receipt_relative_path(
            receipt["source_ref"], CLASSIFIER_EXTRACTOR
        )).is_file()
        store.write_receipt(root, receipt, now=now)
        if before:
            report["receipts_kept"] += 1
        else:
            report["receipts_written"] += 1
    for correction in corrections:
        store.supersede_claims(
            root,
            correction["claim_ids"],
            reason=correction["reason"],
            scope=SUPERSEDE_SCOPE,
            title="Superseded by re-classification",
            author="classifier_claims",
            occurred_at=now,
        )

    store.rebuild_active_index(root)
    if publish:
        import timeline  # noqa: PLC0415 — the package's ONE publish caller

        timeline.publish_calculated_timeline(root)
    after = pub.read_projection(root) or {}
    report["nodes_after"] = len(after.get("nodes") or ())
    return report


def describe_migration(report: object) -> list[str]:
    """The report as lines a human reads before (or after) a vault moves."""
    row = report if isinstance(report, dict) else {}
    types = row.get("claims_by_type") or {}
    subjects = row.get("subjects") or {}
    lines = [
        "Classifier moments -> claims"
        + (" (dry run — nothing written)" if row.get("dry_run") else ""),
        f"  classifications read: {row.get('classifications')}",
        f"  events: {row.get('events')}  ->  claims: {row.get('claims')}",
        "    by type: "
        + ", ".join(f"{name} {types.get(name, 0)}" for name in sorted(types)),
        f"    dated: {row.get('dated')}   undated (occurrence): {row.get('undated')}",
        f"    carrying a place: {row.get('with_place')}",
        f"    subject: you {subjects.get('self', 0)}, "
        f"somebody named {subjects.get('named_other', 0)}",
        f"  deduped against the recorder: {row.get('deduped_against_recorder')} "
        f"event(s) across {row.get('deduped_sources')} source(s)",
        f"  superseded by re-classification: {row.get('superseded_claims')} claim(s) "
        f"across {row.get('superseded_classifications')} classification(s)",
        f"  nodes: {row.get('nodes_before')} -> {row.get('nodes_after')}"
        + (" (estimated)" if row.get("dry_run") else ""),
    ]
    for name, values in (
        ("classifications with no source_path", row.get("skipped_no_source_path")),
        ("classifications whose source is not in the vault",
         row.get("skipped_source_missing")),
    ):
        if values:
            lines.append(f"  skipped — {name}: {', '.join(str(v) for v in values)}")
    if row.get("skipped_empty_description"):
        lines.append(
            f"  skipped — events with no description: {row.get('skipped_empty_description')}"
        )
    if not row.get("dry_run"):
        lines.append(
            f"  wrote {row.get('receipts_written')} new receipt(s), "
            f"kept {row.get('receipts_kept')} already filed"
        )
    return lines


__all__ = [
    "AGE_CLAIM_CONFIDENCE",
    "CLASSIFIER_EXTRACTOR",
    "ERROR_CODES",
    "EVENT_KEY_LENGTH",
    "EXTRACTOR_NAME",
    "MOMENT_EVENT_KIND",
    "OCCURRENCE_CLAIM_CONFIDENCE",
    "ORDER_CLAIM_CONFIDENCE",
    "OWNER_SUBJECT_REF",
    "RELATION_BY_DATE_RELATION",
    "RULE_VERSION",
    "SOURCE_ID_PREFIX",
    "SOURCE_KIND",
    "SUPERSEDE_SCOPE",
    "ClassifierClaimsError",
    "classification_events",
    "classification_revision",
    "classification_source_prefix",
    "describe_migration",
    "event_claim",
    "event_evidence",
    "event_key",
    "event_place_mentions",
    "event_source_id",
    "event_source_ref",
    "event_subject_mention",
    "is_classifier_source_id",
    "migrate_classifier_moments",
    "moment_title",
    "temporal_reading",
]
