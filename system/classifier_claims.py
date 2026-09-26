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
— the one iterator, so a correction-stale classification is withheld here
exactly as it is withheld from every other reader). Raw, because
`timeline.load_events()` drops event-local people, places, direct dates and
validated contextual relations. Document-level place lists are retrieval
hints only; they are never copied onto every event.

WHAT IT WRITES. One `ExtractionReceipt` per classifier reading: an event's
direct date or age and a validated `within`/`before`/`after` relation may
coexist under separate source references. Rule 3 revisions hash the canonical
normalized assertion and its existing source provenance, not generated ids or
clocks. Changed assertions append new interpretations; identical grounded
direct assertions survive unrelated link refresh. When a source is re-classified,
one supersession correction retires only the older classifier-family reading.
Nothing else. It never edits `state/classifications/`, never re-classifies
anything, never calls a model, and never redraws `state/landmarks.json`.

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

* **`when_hint` is never parsed AS A DATE OR AN AGE.** It is free text
  ("sixth grade", "two weeks after the wedding") and `chronology.parse_age` is
  a FIELD parser, not a free-text detector: run over that field it reads *"two
  weeks after the wedding"* as age 2 and *"1985"* as age 5. The hint rides as
  evidence and dates nothing — with ONE named exception, added under the
  owner's 2026-09-23 ruling and no wider than the ruling: a RECENCY cue
  (`chronology.RECENCY_RUNGS`) read together with the telling's own capture
  date. That is not free-text date parsing. It is a closed vocabulary of six
  rungs matched against the moment's prose and against the question that
  prompted the answer, and the interval it yields is bounded at both ends by
  two facts the vault already holds: a word the person chose and the day they
  said it. See :func:`recency_reading`.
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
import json
import re
import sys
from pathlib import Path

SYSTEM_DIR = Path(__file__).resolve().parent
if str(SYSTEM_DIR) not in sys.path:
    sys.path.insert(0, str(SYSTEM_DIR))

import answer_placement as ap  # noqa: E402
import chronology as chrono  # noqa: E402
import classify_story  # noqa: E402
import cross_dating  # noqa: E402
import event_identity as ei  # noqa: E402
import landmark_projection as lp  # noqa: E402
import temporal_claims as tc  # noqa: E402
import temporal_publication as pub  # noqa: E402
import temporal_store as store  # noqa: E402
import temporal_work_items as twi  # noqa: E402
import timeline_evidence  # noqa: E402
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
RULE_VERSION = timeline_evidence.CLASSIFIER_CLAIMS_RULE_VERSION
CLASSIFIER_EXTRACTOR = timeline_evidence.CLASSIFIER_CLAIMS_EXTRACTOR

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
EVENT_KEY_LENGTH = timeline_evidence.EVENT_KEY_LENGTH

#: `chronology.RELATIONS` -> `temporal_claims.CONSTRAINT_RELATIONS`. The two
#: vocabularies are deliberately different (one compares date records, one
#: places nodes) and this is the one crossing.
RELATION_BY_DATE_RELATION = {
    "before": "before",
    "after": "after",
    "during": "within",
    "within": "within",
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

#: The frontmatter keys a telling's CAPTURE DATE has been written under, best
#: first. `process_answer` writes all three on a prompted answer
#: (`captured_at` to the second, `answered_date` and `asked_at` to the day);
#: an older answer file carries `captured_at` alone, and a hand-filed source
#: may carry only `date`. First key that parses wins, so the most precise
#: record of when the telling happened is the one the recency rung counts back
#: from. `chronology.capture_day` does the parsing, so a timestamp shape this
#: list has never seen is refused rather than guessed at.
CAPTURE_DATE_KEYS = ("captured_at", "answered_date", "asked_at", "date")

#: Where the PROMPTING QUESTION's words live. The owner's ruling puts the cue
#: in *"the story OR the question that prompted the answer"*, and it is the
#: question that carries it in the case the ruling was written for: `answers/
#: O6.md`'s story has no time words at all and its question asks for *"a
#: **recent** moment"*. `question_text` is what `process_answer` writes;
#: `title` is the fallback for the older answers written before that key
#: existed, which embed the question verbatim (*"Question A7 — Was there a
#: moment…"*).
QUESTION_TEXT_KEYS = ("question_text", "title")

#: A recency placement is the person's own loose bound, so it is scored the way
#: `landmark_projection.CONFIDENCE_SCORE` scores an `approximate` record they
#: stated: below a named date, above an age statement's arithmetic. The record
#: itself carries the same word (`chronology.from_recency`), so this number and
#: that one cannot disagree.
RECENCY_CLAIM_CONFIDENCE = lp.CONFIDENCE_SCORE["approximate"]

#: Event-level keys a classification may carry that name WHO the event
#: happened to. The current classify prompt asks for `subject` per event
#: ("who or what experienced this event", `classify_story.py`'s event schema);
#: `subject_mention` and `who` are older and hand-edited spellings of the same
#: thing. All three are read tolerantly, and an event that names none of them
#: is the owner's own moment. The mention is kept RAW — who that is is
#: identity resolution's question, and since `timeline-rules:9` a mention the
#: roster cannot place is not the owner merely because it is unplaced
#: (`temporal_timeline._mention_names_another_person`).
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
    return timeline_evidence.event_key(event)


def event_source_id(stem: object, event: object, *, link: bool = False) -> str:
    """``classification:<stem>#<event key>`` — this moment's source identity."""
    text = collapsed_text(stem)
    if not text:
        raise ClassifierClaimsError(
            "classification_stem_required", "a classification is identified by its file stem"
        )
    suffix = ":link" if link else ""
    return f"{SOURCE_ID_PREFIX}:{text}#{event_key(event)}{suffix}"


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
    *, stem: object, event: object, revision: object, source_path: object,
    link: bool = False,
) -> dict:
    """The claim's source: this moment, of this classification, of that story."""
    return tc.validate_source_ref(
        {
            "source_id": event_source_id(stem, event, link=link),
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
    """Places explicitly attached to this event, never document-wide places."""
    del document_places
    names: list[str] = []
    row = event if isinstance(event, dict) else {}
    for key in EVENT_PLACE_KEYS:
        names.extend(_place_names(row.get(key)))
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


#: WHOSE AGE A STATED AGE IS (lifehug#415, the classifier seat; v360, owner
#: 2026-09-25). `date.age` is filed under the claim's subject and the fold
#: measures it from THAT subject's birth (v346), so the subject is the whole
#: arithmetic. The classifier filed the owner's own words as another person's
#: age three times on his vault:
#:
#: * *"Father's four years bedridden"* — ``when I was just off my mission, so
#:   like 22, 23`` filed as his FATHER's 22-23, drawn from the father's 1954
#:   birth to ≈1976–1978;
#: * *"Dad wins pet snake at fair"* — ``I must have been like four or five
#:   years old`` filed as Dad's;
#: * *"Charlee currently 15 and a half"* — subject *"Narrator and Charlee"*
#:   (two people, so the event fell back to the owner), ``Charlee is 15 and a
#:   half right now`` measured from the OWNER's birth.
#:
#: THE RULE, read from the person's own words (the ``when_hint`` and the
#: grounded quote, never the classifier's third-person description):
#:
#: 1. an age in the FIRST PERSON (`chronology.NARRATOR_AGE_RE`, the one
#:    definition the card-answer seat also asks) is the narrator's: the claim's
#:    subject is the owner, on the SAME moment (``event_ref`` is untouched);
#: 2. an age stated OF a named person (*"Charlee is 15 and a half"*, *"when my
#:    dad was 19"*) is that person's — the event's own spelling of them when
#:    the event names them, else the name as written;
#: 3. an age held NOW (*"currently"*, *"is 15 … right now"*) dates the
#:    TELLING: the moment is the capture month (`chronology.from_present_age`),
#:    not a year counted from anybody's birth;
#: 4. otherwise the event's own subject, as before.
#:
#: The moment keeps its own subject: when the age moves off it, an
#: ``occurrence`` under the event's subject rides beside the age on the same
#: ``event_ref`` (:func:`event_claims`).
#:
#: REPAIR, not edit. A vault that already filed the old readings is repaired
#: by the next `migrate_classifier_moments` sweep: the changed readings are
#: new content-addressed claims (a new receipt beside the old), and the old
#: ones are retired by :func:`_superseded_by_reclassification`'s correction.
#: `timeline_evidence.CLASSIFIER_CLAIMS_RULE_VERSION` deliberately does NOT
#: move: since v354 a reading's receipt is keyed on its own assertion, so
#: only the readings that changed are re-filed. Bumping it re-keys all ~1,200
#: readings, and on the owner's vault that drops 18 nodes that only a stale
#: claim id was keeping clear of the recorder dedupe — a different defect,
#: not this one's to trigger.
AGE_BELONGS_TO_WHOEVER_SAID_IT_OF = "age_belongs_to_whoever_said_it_of"


def _age_texts(event: dict) -> list[str]:
    """The person's own words an age was read out of."""
    texts = [collapsed_text(event.get("when_hint"))]
    grounding = event.get("source_grounding")
    if isinstance(grounding, dict):
        texts.append(collapsed_text(grounding.get("quote")))
    return [text for text in texts if text]


def _event_subject_parts(event: dict) -> list[str]:
    """Every person the event itself names as its subject or people."""
    parts: list[str] = []
    for key in EVENT_SUBJECT_KEYS:
        parts.extend(tc.split_subject_enumeration(collapsed_text(event.get(key))))
    for key in EVENT_PEOPLE_KEYS:
        parts.extend(_place_names(event.get(key)))
    return [part for part in parts if part]


def age_subject(event: object, age: object) -> dict:
    """``{"subject_mention": <str or "">, "present": bool}`` for one age.

    ``subject_mention`` is empty when the event's own subject stands
    (:data:`AGE_BELONGS_TO_WHOEVER_SAID_IT_OF`, rule 4).
    """
    import temporal_timeline as tt  # noqa: PLC0415 — the one owner-reference reader

    row = event if isinstance(event, dict) else {}
    statement = None
    for text in _age_texts(row):
        statement = chrono.age_statement_of(text, age)
        if statement is not None:
            break
    if statement is None:
        return {"subject_mention": "", "present": False}
    own = event_subject_mention(row)
    subject = ""
    if statement["speaker"] == "narrator":
        if own != OWNER_SUBJECT_REF and not tt.is_owner_reference_only(own):
            subject = OWNER_SUBJECT_REF
    elif statement["speaker"] == "named":
        who = collapsed_text(statement["who"])
        bare = re.sub(r"^my\s+", "", who, flags=re.IGNORECASE)
        named = who[:1].isupper() or bare != who
        if named:
            wanted = {normalized_mention_key(who), normalized_mention_key(bare)}
            match = next((part for part in _event_subject_parts(row)
                          if normalized_mention_key(part) in wanted), "")
            spelled = match or who
            if normalized_mention_key(spelled) != normalized_mention_key(own) and \
                    len(spelled) <= tc.MAX_SUBJECT_MENTION_CHARS:
                subject = spelled
    return {"subject_mention": subject, "present": bool(statement["present"])}


def capture_context(vault_root: str | Path, source_path: object) -> dict:
    """``{"captured": <ISO day>, "question_text": <str>}`` for one telling.

    The one reader of a telling's own frontmatter in this module, and the only
    reason it exists: the owner's recency ruling needs the DAY the telling was
    recorded, and that day does not survive into
    ``state/classifications/``. `classify_story.build_classification` keeps
    ``source_path``, ``source_title`` and ``source_type`` and drops
    ``captured_at``, ``answered_date`` and ``question_text``, so the capture
    date has to come from the answer file itself.

    Read through `classify_story.load_source_text`, which is the ONE loader for
    an answer or a source (it wraps `lifehug_core.skip_leading_frontmatter_blocks`
    so a stacked preamble reads the same here as everywhere else). Everything
    unreadable degrades to ``{}`` — the same degradation
    :func:`document_revision` already makes — and an event with no capture date
    stays exactly the occurrence it was.
    """
    try:
        path = store.store_path(vault_root, source_path)
        metadata, _body = classify_story.load_source_text(path)
    except (OSError, ValueError, TypeError, UnicodeDecodeError):
        return {}
    if not isinstance(metadata, dict):
        return {}
    captured = ""
    for key in CAPTURE_DATE_KEYS:
        if chrono.capture_day(metadata.get(key)) is not None:
            captured = str(metadata.get(key))
            break
    question = ""
    for key in QUESTION_TEXT_KEYS:
        question = collapsed_text(metadata.get(key))
        if question:
            break
    found = {}
    if captured:
        found["captured"] = captured
    if question:
        found["question_text"] = question
    return found


def recency_reading(event: object, capture: object = None) -> dict | None:
    """A recency cue plus the capture date, as a STATED range. Owner ruling 1.

        "'Recent' with a known capture date IS a placement, not a guess. Place
        the moment as a STATED range [capture_date - 6 months, capture_date],
        basis stated — it renders as 'placed by you', because the person is the
        one saying it was recent." (owner, staging, 2026-09-23)

    The moment this ruling was written for: `answers/O6.md`, captured
    2026-07-14, answering *"What's a **recent** moment that was peak James…?"*.
    The story has no time words, the classifier stamped ``when_hint: recent``,
    and the substrate filed an ``occurrence`` — *when is not known* — which is
    not what the person said. They said it was recent, and the vault knows what
    day they said it on. Two facts, one interval.

    The cue is looked for in the moment's own prose
    (`cross_dating.moment_fields` — title, description, ``when_hint``, the ONE
    reader of a moment's prose fields) and in the QUESTION that prompted the
    answer, because a person answering *"a recent moment"* in kind has said the
    word as surely as if they had typed it. Which rung fires is
    `chronology.RECENCY_RUNGS`' decision and not this module's: there is ONE
    recency vocabulary and every reader goes through it.

    ``None`` — still an occurrence — when there is no cue, or no capture date.
    Not a fabrication in either direction: without the capture date "recent"
    bounds nothing, and without the cue there is nothing to bound.
    """
    row = capture if isinstance(capture, dict) else {}
    captured = row.get("captured")
    if not captured:
        return None
    record = chrono.from_recency(
        captured,
        *cross_dating.moment_fields(event),
        collapsed_text(row.get("question_text")),
    )
    if record is None:
        return None
    return {
        "claim_type": "date",
        "temporal_value": record.to_dict(),
        "basis": "explicit",
        "confidence": RECENCY_CLAIM_CONFIDENCE,
    }


def grade_reading(event: object) -> dict | None:
    """A school GRADE the moment's own words name, as an ``age`` claim reading.

    The second named exception to "``when_hint`` dates nothing", and as narrow
    as the first: a closed vocabulary (`chronology.SCHOOL_GRADE_RE` — "sixth
    grade", "middle of 6th grade", "freshman year", "kindergarten") read by the
    ONE grade reader, `chronology.school_grade_of`, which the card-answer seat
    (`answer_placement.grade_reading`) asks too. The fold measures it on the
    school calendar against the SUBJECT's birth
    (`chronology.A_SCHOOL_GRADE_IS_AN_AGE_ON_THE_SCHOOL_CALENDAR`). Whose grade:
    the event's own subject, unless the words say "I was in" / "my" (the
    narrator) or name somebody ("for James", "James's sixth grade").
    """
    import temporal_timeline as tt  # noqa: PLC0415 — the one owner-reference reader

    row = event if isinstance(event, dict) else {}
    found = None
    for text in cross_dating.moment_fields(row):
        found = chrono.school_grade_of(text)
        if found is not None:
            break
    value = chrono.school_grade_quantity(found)
    if value is None:
        return None
    reading = {
        "claim_type": "age",
        "temporal_value": value,
        "basis": "explicit",
        "confidence": AGE_CLAIM_CONFIDENCE,
    }
    own = event_subject_mention(row)
    if found["speaker"] == "narrator":
        if own != OWNER_SUBJECT_REF and not tt.is_owner_reference_only(own):
            reading["subject_mention"] = OWNER_SUBJECT_REF
    elif found["speaker"] == "named":
        who = collapsed_text(found["who"])
        wanted = normalized_mention_key(who)
        match = next((part for part in _event_subject_parts(row)
                      if wanted and wanted in normalized_mention_key(part)), "")
        if not match and len(who) <= tc.MAX_SUBJECT_MENTION_CHARS \
                and wanted != normalized_mention_key(own):
            reading["subject_mention"] = who
    return reading


def temporal_reading(event: object, capture: object = None) -> dict:
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
    4. a RECENCY cue plus the telling's capture date -> a ``date`` claim,
       ``explicit``, basis ``stated`` (:func:`recency_reading`, owner ruling 1
       of 2026-09-23). It sits BELOW the three above because a date, an age or
       a landmark the person named is always tighter and always wins; it sits
       ABOVE the occurrence because "recent, told on this day" is a placement
       and an occurrence is the admission that there is none;
    5. nothing datable -> an ``occurrence`` claim. It happened. When is not
       known, and saying so is the whole reason that type exists.

    ``capture`` is :func:`capture_context`'s output for the telling this event
    came out of. Absent — a source with no capture date, or any caller written
    before the ruling — rung 4 cannot fire and the reading is byte-identical to
    what it was, which is what keeps this change additive.
    """
    row = event if isinstance(event, dict) else {}
    claim = chrono.possible_date_claim(row.get("date"))
    if claim:
        stated = optional_text(claim.get("stated"))
        if stated:
            record = chrono.parse_stated_date(stated)
            if record is not None:
                return {
                    "claim_type": "date",
                    "temporal_value": record.to_dict(),
                    "basis": "explicit",
                    "confidence": lp.CONFIDENCE_SCORE.get(record.confidence, 0.45),
                }
        age = _age_band_text(claim.get("age"))
        if age:
            # :data:`AGE_BELONGS_TO_WHOEVER_SAID_IT_OF` — whose age, and
            # whether it is held on the day of the telling.
            whose = age_subject(row, age)
            subject = {"subject_mention": whose["subject_mention"]} \
                if whose["subject_mention"] else {}
            if whose["present"]:
                captured = (capture if isinstance(capture, dict) else {}).get("captured")
                record = chrono.from_present_age(captured)
                if record is not None:
                    return {
                        "claim_type": "date",
                        "temporal_value": record.to_dict(),
                        "basis": "explicit",
                        "confidence": lp.CONFIDENCE_SCORE.get(record.confidence, 0.45),
                        **subject,
                    }
            return {
                "claim_type": "age",
                "temporal_value": age,
                "basis": "explicit",
                "confidence": AGE_CLAIM_CONFIDENCE,
                **subject,
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
    grade = grade_reading(row)
    if grade is not None:
        return grade
    recency = recency_reading(row, capture)
    if recency is not None:
        return recency
    return {
        "claim_type": tc.OCCURRENCE_CLAIM_TYPE,
        "temporal_value": None,
        "basis": "explicit",
        "confidence": OCCURRENCE_CLAIM_CONFIDENCE,
    }


def _grounded_evidence(event: object) -> list[dict] | None:
    row = event if isinstance(event, dict) else {}
    grounding = row.get("source_grounding")
    if not isinstance(grounding, dict):
        return None
    quote = collapsed_text(grounding.get("quote"))
    start = grounding.get("start")
    end = grounding.get("end")
    if not quote or type(start) is not int or type(end) is not int:
        return None
    return [{"quote": bounded_quote(quote), "start": start, "end": end}]


def _reading_assertion(normalized: dict) -> dict:
    """All canonical semantics, without generated identity or clocks."""
    assertion = {key: value for key, value in normalized.items()
                 if key not in ("claim_id", "created_at", "source_ref")}
    assertion["source_ref"] = {
        key: value for key, value in normalized["source_ref"].items()
        if key != "revision"
    }
    return assertion


def _validated_reading_claim(
    payload: dict, *, event: dict, reading_kind: str, fallback: object, now: object,
) -> dict:
    """Content-address the normalized assertion, then mint its canonical id."""
    normalized = tc.validate_temporal_claim(payload, now=now)
    provenance: object = collapsed_text(fallback)
    grounding = event.get("source_grounding")
    if reading_kind == "direct" and isinstance(grounding, dict):
        revision = collapsed_text(grounding.get("source_revision"))
        if revision:
            provenance = revision
    if reading_kind == "contextual":
        resolution = event.get("timeline_resolution")
        provenance = {
            "source_revision": (
                resolution.get("source_revision")
                if isinstance(resolution, dict) else None
            ),
            "input_fingerprint": (
                resolution.get("input_fingerprint")
                if isinstance(resolution, dict) else None
            ),
        }
    # Hash all canonical assertions, not a second list of temporal fields.
    # The first id/revision and clock are generated, not asserted semantics.
    assertion = _reading_assertion(normalized)
    revision = "sha256:" + hashlib.sha256(lp.canonical_json({
        "assertion": assertion, "source_provenance": provenance,
    }).encode("utf-8")).hexdigest()
    normalized["source_ref"] = {**normalized["source_ref"], "revision": revision}
    return tc.validate_temporal_claim(normalized, now=now)


def _raw_anchor_is_canonicalized(direct: dict, contextual: dict, event: dict) -> bool:
    """True only when source evidence proves the raw handle is this edge."""
    if (direct.get("claim_type") != "relative_order"
            or contextual.get("claim_type") != "relative_order"):
        return False
    direct_value = direct.get("temporal_value") or {}
    contextual_value = contextual.get("temporal_value") or {}
    if direct_value.get("relation") != contextual_value.get("relation"):
        return False
    resolution = event.get("timeline_resolution")
    if not isinstance(resolution, dict) or resolution.get("status") != "linked":
        return False
    anchors = direct_value.get("anchors") or ()
    evidence = contextual.get("evidence") or ()
    quote = evidence[0].get("quote") if evidence and isinstance(evidence[0], dict) else ""
    raw = normalized_mention_key(anchors[0]) if len(anchors) == 1 else ""
    proof = normalized_mention_key(quote)
    return bool(raw and re.search(rf"(?<!\w){re.escape(raw)}(?!\w)", proof))


def contextual_reading(event: object) -> dict | None:
    """A validated contextual relationship to a supplied canonical candidate."""
    row = event if isinstance(event, dict) else {}
    relation = row.get("timeline_relation")
    if not isinstance(relation, dict):
        return None
    relation_name = collapsed_text(relation.get("relation"))
    candidate_id = collapsed_text(relation.get("candidate_id"))
    evidence = relation.get("evidence")
    refs = relation.get("entity_refs")
    if relation_name not in ("within", "before", "after") or not candidate_id:
        return None
    if not isinstance(evidence, dict) or not collapsed_text(evidence.get("quote")):
        return None
    if not isinstance(refs, list) or not refs:
        return None
    return {
        "reading_kind": "contextual",
        "claim_type": "relative_order",
        "temporal_value": {"relation": relation_name, "anchors": [candidate_id]},
        "basis": "explicit",
        "confidence": ORDER_CLAIM_CONFIDENCE,
        "evidence": [{
            "quote": bounded_quote(evidence.get("quote")),
            "start": evidence.get("start"),
            "end": evidence.get("end"),
        }],
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


def event_claims(
    *,
    stem: object,
    event: object,
    revision: object,
    source_path: object,
    document_places: object = (),
    capture: object = None,
    now: object = None,
) -> list[dict]:
    """One classifier event -> its direct and contextual validated claims.

    The ``event_ref`` is minted here and it is load-bearing: without it every
    ``moment`` of the owner's would group into ONE node
    (`temporal_timeline._group_claims` keys on the claim's ``event_ref`` or on
    the derived node id, and a derived id for the same kind and subject is the
    same id). It is the substrate's own minter, through
    `temporal_projection.derive_node_id`, with the moment's key as the
    discriminator — the "stable ordinal or slug" that function asks for.

    ``capture`` is :func:`capture_context` for the telling, computed once per
    classification by the caller rather than once per event: every event of one
    story was recorded on the same day and prompted by the same question, and
    re-reading the frontmatter per event would read one file N times.
    """
    import temporal_projection as tp  # noqa: PLC0415 — pure, but keeps the load light

    row = event if isinstance(event, dict) else {}
    direct = {**temporal_reading(row, capture), "reading_kind": "direct"}
    # :data:`AGE_BELONGS_TO_WHOEVER_SAID_IT_OF`: when the age is somebody
    # else's than the moment's own subject, the moment still happened to its
    # own subject — "Dad wins pet snake at fair" is Dad's, the "four or five"
    # is the owner's. The age moves; the moment's subject is kept by an
    # occurrence under it, on the same ``event_ref``.
    companion = None
    if direct.get("subject_mention") and \
            normalized_mention_key(direct["subject_mention"]) != \
            normalized_mention_key(event_subject_mention(row)):
        companion = {
            "claim_type": tc.OCCURRENCE_CLAIM_TYPE,
            "temporal_value": None,
            "basis": "explicit",
            "confidence": OCCURRENCE_CLAIM_CONFIDENCE,
            "reading_kind": "direct",
        }
    grounding = row.get("source_grounding")
    direct_grounded = False
    if (isinstance(grounding, dict)
            and grounding.get("kind") == direct.get("claim_type")):
        grounded_evidence = _grounded_evidence(row)
        if grounded_evidence is not None:
            direct["evidence"] = grounded_evidence
            direct_grounded = True
    event_kind = (
        timeline_evidence.event_role(row) if direct_grounded else None
    ) or MOMENT_EVENT_KIND
    readings = [direct]
    contextual = contextual_reading(row)
    if contextual is not None and readings[0]["claim_type"] == tc.OCCURRENCE_CLAIM_TYPE:
        readings = [contextual]
    elif contextual is not None and _raw_anchor_is_canonicalized(
            readings[0], contextual, row):
        readings = [contextual]
    elif contextual is not None and not any(
        reading["claim_type"] == contextual["claim_type"]
        and reading["temporal_value"] == contextual["temporal_value"]
        for reading in readings
    ):
        readings.append(contextual)
    if companion is not None:
        readings.append(companion)
    event_ref = tp.derive_node_id(
        node_kind="event",
        event_kind=MOMENT_EVENT_KIND,
        subject_refs=[event_subject_mention(row)],
        discriminator=event_key(row),
    )
    claims = []
    for reading in readings:
        source_ref = event_source_ref(
            stem=stem,
            event=row,
            revision=revision,
            source_path=source_path,
            link=reading.get("reading_kind") == "contextual",
        )
        payload = {
            "source_ref": source_ref,
            "source_kind": SOURCE_KIND,
            "claim_type": reading["claim_type"],
            # The reading's own subject when it names one (an age said of
            # someone, :data:`AGE_BELONGS_TO_WHOEVER_SAID_IT_OF`); the moment —
            # ``event_ref`` above — is the event's either way.
            "subject_mention": (reading.get("subject_mention")
                                or event_subject_mention(row)),
            "event_kind": event_kind,
            "event_ref": event_ref,
            "event_mention": moment_title(row),
            "temporal_value": reading["temporal_value"],
            "evidence": reading.get("evidence") or event_evidence(row),
            "basis": reading["basis"],
            "confidence": reading["confidence"],
            "extractor_version": CLASSIFIER_EXTRACTOR,
            "place_mentions": event_place_mentions(row, document_places),
        }
        resolution = row.get("timeline_resolution")
        if isinstance(resolution, dict) and resolution.get("status"):
            payload["timeline_resolution_status"] = resolution["status"]
        claims.append(_validated_reading_claim(
            payload, event=row, reading_kind=reading["reading_kind"],
            fallback=revision, now=now,
        ))
    return claims


def event_claim(**kwargs) -> dict:
    """Compatibility helper returning the event's primary direct reading."""
    return event_claims(**kwargs)[0]


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


#: Source types whose whole content the landmark recorder already filed as a
#: claim. A classifier moment read out of one of these that asserts no time of
#: its own can only restate the record it came from; minting it a second node
#: draws one school year twice and counts the copy as an unplaced story.
RECORDER_RECORD_SOURCE_TYPES = frozenset({"landmark_entry"})


#: v360 (owner, 2026-09-25). The landmark entry "schools: high school" (grades
#: "sophomore or junior year") was folded into Mountain View by the landmark
#: fold, and the classifier's own reading of the entry's FILE came back as a
#: node of its own, "High school (sophomore or junior year)", unplaced and
#: uncarded. The recorder had filed that entry — undated, so the dedupe that
#: asked for a recorder DATE on the file let it through. A record the recorder
#: filed is canonical whether or not it carries a date; an undated classifier
#: restatement of it is never a second moment.
A_RECORDED_RECORD_IS_CANONICAL_DATED_OR_NOT = (
    "an undated classifier moment read from a landmark entry file the recorder "
    "filed restates that record and is never a claim of its own, whether or not "
    "the recorder's claim carries a date"
)


def _recorder_source_paths(index: object) -> frozenset:
    """Every ``source_path`` a non-classifier ACTIVE claim cites
    (:data:`A_RECORDED_RECORD_IS_CANONICAL_DATED_OR_NOT`)."""
    paths: set[str] = set()
    for claim in store.active_claims(index if isinstance(index, dict) else {}):
        ref = claim.get("source_ref")
        if not isinstance(ref, dict) or is_classifier_source_id(ref.get("source_id")):
            continue
        path = collapsed_text(ref.get("source_path"))
        if path:
            paths.add(path)
    return frozenset(paths)


#: v360 (owner, 2026-09-25). The owner answered the card about Harvey's late talking
#: with *"He only really started talking when he was 4"*. `place-answers` filed
#: that age on Harvey's node, where the card was — and the classifier, reading
#: the same message with no card beside it, filed it again as "Child's late
#: start talking" about an unidentified child: a second node, unplaced and
#: uncarded, for one sentence. A card answer is read once, by the seat that
#: knows which card it answers; a classifier age read off the same message
#: that says the same age is that reading again.
A_CARD_ANSWER_IS_READ_ONCE = (
    "a classifier age read off a card answer that states the same age the "
    "answer placement already filed from that message is that answer read "
    "again, never a claim of its own"
)


def _answer_ages_by_source_path(index: object) -> dict[str, set]:
    """``source_path -> {(low, high)}`` the answer placement filed as ages
    (:data:`A_CARD_ANSWER_IS_READ_ONCE`)."""
    out: dict[str, set] = {}
    for claim in store.active_claims(index if isinstance(index, dict) else {}):
        if tc.extractor_identity(claim.get("extractor_version")) != ap.EXTRACTOR_NAME:
            continue
        if collapsed_text(claim.get("claim_type")) != "age":
            continue
        value = claim.get("temporal_value") or {}
        path = collapsed_text((claim.get("source_ref") or {}).get("source_path"))
        if path and isinstance(value, dict):
            out.setdefault(path, set()).add((value.get("low"), value.get("high")))
    return out


def _restates_the_answer(claim: dict, answer_ages: object) -> bool:
    """:data:`A_CARD_ANSWER_IS_READ_ONCE` for one classifier claim."""
    if not answer_ages or collapsed_text(claim.get("claim_type")) != "age":
        return False
    value = claim.get("temporal_value") or {}
    return isinstance(value, dict) and (value.get("low"), value.get("high")) in answer_ages


def _restates_recorded_record(
    claims: list[dict], *, source_type: object, recorded: bool,
) -> bool:
    """An undated, unlinked classifier moment from a record the recorder filed.

    A moment dated only by the GRADE the record itself states ("Attended fifth
    grade at Hillside Elementary", read out of the school's own entry) is the
    same restatement: the record already dates that school, and the grade is
    one of its own fields (v360, owner 2026-09-25, :func:`grade_reading`)."""
    if not recorded or collapsed_text(source_type) not in RECORDER_RECORD_SOURCE_TYPES:
        return False
    return bool(claims) and all(
        claim.get("claim_type") == tc.OCCURRENCE_CLAIM_TYPE
        or (claim.get("claim_type") == "age"
            and isinstance(claim.get("temporal_value"), dict)
            and claim["temporal_value"].get("grade") is not None)
        for claim in claims
    )


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
    claims_by_source_id: dict[str, list[dict]], *, stem: str,
    current_claim_ids: set[str],
) -> tuple[list[str], list[str]]:
    """``(claim ids, revisions)`` of this classification's PREVIOUS reading.

    Every active claim of this stem that the current classification no longer
    emits. Grounded direct facts keep their ids across link-only refreshes
    when their own assertion is unchanged; changed interpretations do not.
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
            if collapsed_text(claim.get("claim_id")) in current_claim_ids and \
                    collapsed_text(claim.get("extractor_version")) == CLASSIFIER_EXTRACTOR:
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
    # An age held NOW dates the telling from its capture day
    # (`chronology.from_present_age`); no other reader could have recorded
    # that date from the story's words, so any overlap is another moment of
    # the same month, never this one told twice.
    if any(isinstance(row, dict)
           and row.get("source") == chrono.PRESENT_AGE_PROVENANCE_SOURCE
           for row in (claim.get("temporal_value") or {}).get("provenance") or ()):
        return False
    return any(chrono.intersect(record, other) is not None for other in recorder_dates)


def _correction_equivalence_key(claim: dict) -> str:
    assertion = _reading_assertion(claim)
    assertion.pop("extractor_version")
    source_ref = assertion["source_ref"]
    source_ref["source_id"] = source_ref["source_id"].removesuffix(":link")
    return lp.canonical_json(assertion)


def _equivalent_correction_carries(
    root: Path, index: dict, receipts: list[dict], provenance: dict[str, set[str]],
) -> list[dict]:
    """Carry explicit corrections only across proven equivalent re-identification."""
    corrections = [row for row in index.get("corrections", ())
                   if row.get("scope") not in (SUPERSEDE_SCOPE, store.CONSTRAINT_CORRECTION_SCOPE)]
    if not corrections:
        return []
    old_rows = {row["claim_id"]: row for row in index.get("claims", ())
                if is_classifier_source_id(row.get("source_ref", {}).get("source_id"))}
    current: dict[str, list[tuple[dict, str | None]]] = {}
    for receipt in receipts:
        document = receipt["extractor"].get("document_revision")
        for claim in receipt["claims"]:
            current.setdefault(_correction_equivalence_key(claim), []).append((claim, document))
    # Folded status is derived and its dataclass view may omit additive fields.
    # Read only targeted receipts through the canonical no-follow store reader.
    raw_receipts: dict[str, dict] = {}
    carries = []
    for correction in corrections:
        targets: set[str] = set()
        original_ids = set(correction["claim_ids"])
        for claim_id in original_ids:
            old = old_rows.get(claim_id)
            if old is None:
                continue
            path = old["receipt_path"]
            if path not in raw_receipts:
                raw_receipts[path] = tc.validate_extraction_receipt(
                    json.loads(store.read_store_text(root, path)))
            receipt = raw_receipts[path]
            old_claim = next(row for row in receipt["claims"] if row["claim_id"] == claim_id)
            old_document = (receipt.get("extractor") or {}).get("document_revision")
            for claim, document in current.get(_correction_equivalence_key(old_claim), ()):
                if claim["claim_id"] in original_ids:
                    continue
                proven = (old_document == document if old_document else
                          old_claim["source_ref"]["revision"] in provenance[claim["claim_id"]])
                if proven:
                    targets.add(claim["claim_id"])
        if targets:
            carries.append({
                "kind": correction["kind"], "claim_ids": sorted(targets),
                "scope": correction.get("scope"),
                "reason": (f"Carried from {correction['correction_id']} across equivalent "
                           f"classifier interpretation identity: {correction['reason']}"),
            })
    return carries


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
        "deduped_undated_recorder_records": 0, "deduped_refiled_records": 0,
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
        # v352. The SECOND rung of this sweep, reported apart from the first
        # because it reads a different thing: not a classification's events but
        # a promoted ANSWER and the card its `session_ref` names
        # (`answer_placement.ANSWERING_A_CARD_PLACES_ITS_MOMENT`). Its own
        # report, whole, so a reader never has to guess which rung a number
        # came from.
        "answers": ap.empty_report(),
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
    recorder_sources = _recorder_source_paths(index)
    refiled_paths = lp.refiled_record_paths(root)
    answer_ages = _answer_ages_by_source_path(index)
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
    provenance: dict[str, set[str]] = {}
    corrections: list[dict] = []
    new_nodes: set[str] = set()

    for path, data in classify_story.current_classification_files(directory):
        stem = path.stem
        source_path = collapsed_text((data or {}).get("source_path"))
        if wanted is not None and source_path not in wanted:
            continue
        source_type = collapsed_text((data or {}).get("source_type"))
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
        # Owner ruling 1 (2026-09-23): the recency rung needs the DAY the
        # telling was recorded and the question that prompted it, and neither
        # survives into the classification. Read once per story, for the same
        # reason `story_revision` is.
        capture = capture_context(root, source_path)
        events = classification_events(data)
        report["skipped_empty_description"] += len(
            (data or {}).get("events") or ()
        ) - len(events)
        report["events"] += len(events)
        deduped_here = 0
        current_claim_ids: set[str] = set()

        for event in events:
            if source_path in refiled_paths:
                # v360 (owner, 2026-09-25) (`landmark_projection.A_RECORD_IS_FILED_WHERE_IT_BELONGS`):
                # a refiled record read back by the classifier is the record
                # again, and its refile already says what it is.
                report["deduped_refiled_records"] += 1
                deduped_here += 1
                continue
            claims = event_claims(
                stem=stem, event=event, revision=revision,
                source_path=source_path, capture=capture, now=now,
            )
            if _restates_recorded_record(
                    claims, source_type=source_type,
                    recorded=bool(recorder_dates.get(source_path))
                    or source_path in recorder_sources):
                report["deduped_undated_recorder_records"] += 1
                deduped_here += 1
                continue
            current_claim_ids.update(claim["claim_id"] for claim in claims)
            kept_claims = []
            for claim in claims:
                if _restates_the_answer(claim, answer_ages.get(source_path)):
                    # :data:`A_CARD_ANSWER_IS_READ_ONCE` — and a copy already
                    # filed is superseded by this re-reading, not kept.
                    current_claim_ids.discard(claim["claim_id"])
                    report["deduped_against_recorder"] += 1
                    deduped_here += 1
                    continue
                if _already_recorded(claim, recorder_dates.get(source_path) or ()):
                    report["deduped_against_recorder"] += 1
                    deduped_here += 1
                    continue
                kept_claims.append(claim)
                grounding = event.get("source_grounding")
                provenance[claim["claim_id"]] = {
                    revision, collapsed_text(grounding.get("source_revision"))
                    if isinstance(grounding, dict) else "",
                } - {""}
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
            if not kept_claims:
                continue
            by_source_ref: dict[str, list[dict]] = {}
            for claim in kept_claims:
                by_source_ref.setdefault(
                    lp.canonical_json(claim["source_ref"]), []
                ).append(claim)
            for grouped_claims in by_source_ref.values():
                receipts.append({
                    "source_ref": grouped_claims[0]["source_ref"],
                    "extractor_version": CLASSIFIER_EXTRACTOR,
                    "extractor": ei.declare_tellings(
                        {
                            "name": EXTRACTOR_NAME,
                            "rule_version": RULE_VERSION,
                            "deterministic": True,
                        },
                        telling_keys={
                            claim["claim_id"]: ei.classifier_telling_ref(stem, event)
                            for claim in grouped_claims
                        },
                        document_revision=story_revision,
                    ),
                    "claims": grouped_claims,
                    "recorder": "classifier_claims",
                })
        if deduped_here:
            report["deduped_sources"] += 1

        stale_ids, stale_revisions = _superseded_by_reclassification(
            claims_by_source_id, stem=stem, current_claim_ids=current_claim_ids
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

    carried_corrections = _equivalent_correction_carries(root, index, receipts, provenance)
    if dry_run:
        report["answers"] = ap.place_answers(root, dry_run=True, now=now)
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
    for correction in carried_corrections:
        store.file_temporal_correction(
            root, **correction, author="classifier_claims", occurred_at=now,
            title="Preserved correction on equivalent classifier reading",
        )

    # v352, ANSWERING A CARD PLACES ITS MOMENT. The second rung, and it runs
    # HERE — after the classifier's own receipts and before the one rebuild and
    # the one publish — for two reasons. It reads the PUBLISHED work items and
    # projection, which is the generation whose card the person was answering,
    # so running it before the republish is what makes "the card the person saw"
    # the card the answer lands on. And it files receipts exactly as the rung
    # above does, so one rebuild and one publish carry both: a claim filed here
    # is not visible until the projection moves, which is v231's rule and not
    # this rung's to re-decide.
    report["answers"] = ap.place_answers(root, now=now)
    store.rebuild_active_index(root)
    ei.rebuild_telling_manifest(root)
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
        f"  undated restatements of recorder records: "
        f"{row.get('deduped_undated_recorder_records', 0)}",
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
    # v352's rung, printed under its own heading and through its own describer,
    # so the two rungs of this sweep are never read as one number.
    answers = row.get("answers")
    if isinstance(answers, dict) and answers.get("answers"):
        lines.append("Answers to cards -> a claim on the card's own moment")
        lines.extend(f"  {line}" for line in ap.describe(answers))
    return lines


__all__ = [
    "A_CARD_ANSWER_IS_READ_ONCE",
    "A_RECORDED_RECORD_IS_CANONICAL_DATED_OR_NOT",
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
    "event_claims",
    "event_evidence",
    "event_key",
    "event_place_mentions",
    "event_source_id",
    "event_source_ref",
    "event_subject_mention",
    "contextual_reading",
    "is_classifier_source_id",
    "migrate_classifier_moments",
    "moment_title",
    "temporal_reading",
]
