#!/usr/bin/env python3
"""`state/landmarks.json` is a DRAWING. The whiteboard is glass now.

Owner amendment 1 to the audited final timeline build plan (2026-08-26),
wave B item B3. Until this module existed, a landmark entry was written
straight into `state/landmarks.json` and that file WAS the truth: a date the
person stated lived nowhere else, its provenance was whatever the entry
happened to carry, and "why does the timeline say 1978?" had no answer below
the file itself. v219-v223 built the substrate that can answer it — claims
with sources, receipts that rebuild the active set with no model call,
corrections that retire without deleting. This module performs the FLIP:

    every landmark entry becomes a promoted vault source + temporal claims,
    and `state/landmarks.json` becomes a projection redrawn from them.

Three properties are the whole point, and none may be weakened.

**No dual-truth window.** The converter, the write-path swap and the guard
land in one semantic commit. There is never a moment where an entry is
authoritative in the file AND in the substrate, because the moment the
substrate holds it the file is derived. `timeline.save_landmark` keeps its
signature and its meaning; what changed is that it now records evidence and
redraws, instead of editing the drawing directly.

**The flip is invisible.** For a vault with existing entries, convert -> fold
-> project reproduces the pre-flip file. The ladder, `landmark_rows`,
`anchors_from_landmarks` and every other reader keep reading exactly what they
read before, through `timeline.load_landmarks`, and never learn that anything
moved. `tests/test_landmark_projection.py` pins this against a founder-shaped
fixture with every domain populated.

**Reconciliation moves to READ time.** This is the deep change, and it is why
the projection is a fold rather than a lookup. Before the flip,
`merge_landmark_entry` reconciled two dates when the second one was FILED and
stored the winner plus its alternates. Now every telling is its own claim, and
`chronology.reconcile` runs over the live active set every time the file is
drawn. The stored result is identical — `reconcile` is deterministic and
idempotent over the same claims — but a retraction can now change the answer,
which a stored winner could never do.

WHAT LIVES WHERE, precisely, because this is the question a reader of this
module will actually have:

* `sources/landmarks/entry-<24 hex>.md` — one promoted vault source per FILED
  RECORD (not per entry: an entry that was answered over four conversations
  has four sources). It carries the record exactly as it was filed, which
  makes it evidence. Its frontmatter carries the grouping key
  (`landmark_domain`, `landmark_entry_key`) and its filing order
  (`filed_ordinal`), because those are facts about the filing and not
  interpretations of it.
* `state/temporal_claims/receipts/...` — one receipt per source, listing the
  temporal claims read out of that record by a DETERMINISTIC RULE. No model
  call happens here, ever; the extractor version says so
  (`legacy-entry-import/rule:1`, `landmark-record/rule:1`).
* `state/landmarks.json` — the drawing. Written by exactly one function
  (`timeline.redraw_landmarks`) and by nothing else in the package, which
  `tests/test_landmark_projection.py::test_no_other_writer_of_landmarks_json`
  enforces against the AST of every module.

THE SKELETON IS EVIDENCE, THE DATES ARE CLAIMS. A landmark entry is not
purely temporal — `residences` carries a city and an address, `schools` a name
and grades, `family` a relation. The v220 `TemporalClaim` schema is frozen and
deliberately has no slot for any of that, so those fields ride on the promoted
SOURCE, where they belong: they are what the person said, recorded immutably.
The projector reads the skeleton from the sources and the dates from the
claims, and it reads dates from a source NEVER — see :func:`skeleton_of`,
which strips them, and the note on its docstring about why that strip is
load-bearing rather than tidy.

WHY THE ENTRY'S EXISTENCE IS ITSELF A CLAIM. Every filed record also emits one
`identity` claim. It carries no date and asserts only "this entry was named",
and it is what makes a correction able to remove an entry: retract the
identity claim and the group has no active anchor, so the projection drops it.
Without it, retracting an entry's only date would leave a dateless ghost in
the drawing forever.

The wave-D calculated timeline (`system/temporal_projection.py`) is a
different projection over the same substrate and is deliberately not touched
here. This module draws the LADDER's file, at the ladder's own shape.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

SYSTEM_DIR = Path(__file__).resolve().parent
if str(SYSTEM_DIR) not in sys.path:
    sys.path.insert(0, str(SYSTEM_DIR))

import chronology as chrono  # noqa: E402
import landmarks_interaction  # noqa: E402
import temporal_store as store  # noqa: E402
from temporal_claims import (  # noqa: E402
    CLAIM_BASIS_BY_DATE_BASIS,
    SCHEMA_VERSION,
    SourceRef,
    TemporalContractError,
    bounded_quote,
    collapsed_text,
    extractor_version_string,
    normalized_timestamp,
    validate_extraction_receipt,
    validate_temporal_claim,
)
from vault_paths import atomic_create_vault_bytes  # noqa: E402

# --------------------------------------------------------------------------
# Layout and vocabulary
# --------------------------------------------------------------------------

#: Promoted landmark records. Under ``sources/`` and not ``state/`` for the
#: same reason amendment 2's conversational sources are: state is rebuildable
#: and evidence never is. Registered in ``vault_contract.json``.
LANDMARK_SOURCES_DIR = "sources/landmarks"

#: The ``type`` every promoted landmark record declares in its frontmatter.
LANDMARK_SOURCE_TYPE = "landmark_entry"

#: The projected file's own schema version. Deliberately equal to
#: ``timeline.LANDMARKS_SCHEMA_VERSION`` — the drawing's shape did not change
#: when what draws it did, and a reader that checked the version must not see
#: a number it does not know.
LANDMARKS_SCHEMA_VERSION = 1

#: The one-time converter's extractor version. ``rule:`` and no ``model:``,
#: because :func:`entry_claims` is a deterministic function of an entry and
#: calls nothing. Bump the rule version to re-import under a new reading; the
#: old receipts stay on disk beside the new ones, which is the substrate's
#: whole promise.
LEGACY_EXTRACTOR = extractor_version_string("legacy-entry-import", rule_version="1")

#: The live write path's extractor version. The SAME deterministic rule, named
#: differently so the fold and a debugging human can tell an imported record
#: from one filed after the flip. Both run :func:`entry_claims`.
LIVE_EXTRACTOR = extractor_version_string("landmark-record", rule_version="1")

#: A span's two bounds, as event kinds. Both are in
#: ``temporal_claims.LANDMARK_DATE_SEMANTICS``; a span is stored as two dated
#: claims rather than one range claim because the two bounds carry their own
#: basis, anchors and provenance and can exist independently — a job whose
#: start year is stated and whose end is unknown is one claim, not half of one.
SPAN_START_EVENT_KIND = "started"
SPAN_END_EVENT_KIND = "ended"

#: The event kind for an entry's own ``date`` when its domain dates SEVERAL
#: events. ``partnerships`` declares ``first_met|dating_started|married`` and
#: the pre-flip ladder stored ONE date without saying which of the three it
#: was, so naming any one of them here would fabricate a distinction the
#: person never drew. ``transition`` is the seeded semantic for exactly that:
#: an event transition whose kind is not yet settled. Wave C splits these into
#: per-event claims, which supersede rather than rewrite.
UNDISAMBIGUATED_EVENT_KIND = "transition"

#: The subject a ``birth`` landmark entry names (design §3.1). It is the
#: owner's own handle — ``temporal_timeline.DEFAULT_OWNER_REF`` — spelled here
#: as the literal the substrate stores, because this module mints MENTIONS and
#: a mention is text, not a ref. The fold resolves it to the owner like any
#: other mention; it simply never needs a roster to do it.
OWNER_BIRTH_MENTION = "self"

#: The entry keys the projector must never read from a promoted source: they
#: are the temporal assertion, and the temporal assertion lives in the claims.
#: See :func:`skeleton_of`.
TEMPORAL_ENTRY_KEYS = (
    "date",
    "span",
    landmarks_interaction.DATE_ALTERNATES_KEY,
    landmarks_interaction.SPAN_ALTERNATES_KEY,
)

#: Frontmatter keys this module adds to the shared source shape.
LANDMARK_FRONTMATTER_KEYS = (
    "landmark_domain",
    "landmark_entry_key",
    "filed_ordinal",
)


class LandmarkProjectionError(TemporalContractError):
    """A landmark record or promoted source that cannot be trusted."""


ERROR_CODES = (
    "landmark_domain_required",
    "landmark_record_empty",
    "landmark_source_malformed",
    "landmark_ordinal_required",
)


# --------------------------------------------------------------------------
# Pure derivation: an entry, read by a deterministic rule
# --------------------------------------------------------------------------


def canonical_json(payload: object) -> str:
    """One serialization for anything this module digests or stores."""
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _root(vault_root: str | Path) -> Path:
    """The vault root as an absolute directory. `temporal_store`'s rule, reused."""
    root = Path(vault_root).expanduser()
    if not root.is_absolute():
        root = Path.cwd() / root
    if not root.is_dir():
        raise LandmarkProjectionError(
            "landmark_source_malformed", f"vault root is not a directory: {root}"
        )
    return root


def skeleton_of(entry: object) -> dict:
    """The entry WITHOUT its temporal assertion — what the projector may read.

    Load-bearing rather than tidy. A promoted source carries the record
    exactly as filed, dates included, because evidence that edits itself is
    not evidence. But the projector must derive every date from the CLAIMS, or
    the flip would have produced two answers to "when" — one in the source and
    one in the substrate — which is the dual truth this whole change exists to
    end. Stripping here is how "the projector never reads a date from a source"
    becomes a property of the code instead of a promise in a comment.
    """
    if not isinstance(entry, dict):
        return {}
    return {key: value for key, value in entry.items() if key not in TEMPORAL_ENTRY_KEYS}


def domain_row_or_none(domain: object) -> dict | None:
    """The question set's row for ``domain``, or ``None`` when it declares none.

    Degrade, never refuse: `timeline.save_landmark` has always filed a domain
    the question set does not declare, keyed on its identity fields alone, and
    the flip does not get to start rejecting vaults that already hold one.
    """
    try:
        return landmarks_interaction.domain_row(str(domain or ""))
    except landmarks_interaction.LandmarkInteractionError:
        return None


def date_event_kind(row: object) -> str:
    """Which event an entry's own ``date`` field dates.

    One declared semantic -> that one (``children`` -> ``birth``, ``losses``
    -> ``death``). Several -> :data:`UNDISAMBIGUATED_EVENT_KIND`, because the
    legacy ladder stored one date for three distinct events and guessing which
    is the false precision the plan forbids. A domain the question set does
    not declare, or one whose semantic is ``span``, also lands on the
    undisambiguated kind: a bare ``date`` on a span domain is a point somebody
    filed against a stretch, and it is not the stretch's start by assumption.
    """
    semantics = landmarks_interaction.date_semantics(row) if isinstance(row, dict) else ()
    if len(semantics) == 1 and semantics[0] != "span":
        return semantics[0]
    return UNDISAMBIGUATED_EVENT_KIND


# --------------------------------------------------------------------------
# Owner relevance — a stated relationship AND an owner-relevant occurrence
# --------------------------------------------------------------------------

#: WHICH landmark domains make somebody ELSE's occurrence part of the owner's
#: life, and how (eras design §2.5). It is deliberately a table of FOUR rows,
#: not a rule over the nine domains: `residences`, `schools`, `work`,
#: `military` and `birth` are the owner's own life, so their entries never
#: reach this question, and no other domain enumerates a second person.
#:
#: The relation is the DESIGN's, not an inference: a partnership landmark is
#: something the owner was in (``participated``); a child's birth, a family
#: member's birth and a loss are things that happened to somebody else and that
#: the owner lived through (``lived_effect``).
OWNER_RELEVANCE_BY_DOMAIN = {
    "children": "lived_effect",
    "losses": "lived_effect",
    "family": "lived_effect",
    "partnerships": "participated",
}


def entry_supported_event_kinds(domain: object) -> tuple[str, ...]:
    """The event kinds ONE entry of ``domain`` is evidence for.

    This is the narrow half of §2.5, and the narrowness is the point. A
    ``children`` entry says a child was born and says nothing whatsoever about
    that child's graduation, their move, or the year they changed jobs — so the
    entry supports exactly the event kinds its own ``date_semantics`` mints,
    read through :func:`date_event_kind` and the two span bounds, and nothing
    else. *The relationship alone does not pull the relative's other dated
    events onto the axis.*
    """
    row = domain_row_or_none(domain)
    if row is None:
        return ()
    # The domain's OWN declared semantics, plus whatever `date_event_kind`
    # collapses them to. Both spellings are real on disk: a legacy
    # `partnerships` entry's single `date` field lands at `transition` (three
    # declared semantics, none of them guessable), while the recorder and the
    # listener emit `married` / `first_met` / `dating_started` directly. One
    # entry is evidence for both readings of the same fact and for nothing
    # wider than that.
    kinds = {date_event_kind(row)}
    kinds.update(landmarks_interaction.date_semantics(row))
    kinds.discard("span")
    if not landmarks_interaction.dates_each_entry(row):
        kinds.update((SPAN_START_EVENT_KIND, SPAN_END_EVENT_KIND))
    return tuple(sorted(kind for kind in kinds if kind))


def owner_relevance_for(domain: object, event_kind: object) -> str | None:
    """How this entry makes THIS occurrence the owner's, or ``None``.

    ``None`` is a real answer and the commonest one: it means the entry is not
    evidence that this occurrence belongs on the owner's axis, and the caller
    is then required to say ``contextual_only`` rather than quietly placing the
    row anyway. A domain the question set does not declare also returns
    ``None`` — an undeclared domain has no stated relationship semantics, and
    inventing one is the guess this whole phase exists to stop.
    """
    name = collapsed_text(domain)
    relation = OWNER_RELEVANCE_BY_DOMAIN.get(name)
    if relation is None:
        return None
    kind = collapsed_text(event_kind)
    return relation if kind and kind in entry_supported_event_kinds(name) else None


def entry_subject_mention(entry: object, row: object, domain: object) -> str:
    """The raw mention a claim about this entry names as its subject.

    The entry's own identity as the writer spelled it
    (`landmarks_interaction.identity_named` — label, then name, then the
    domain's identity rung), falling back to the DOMAIN word for an entry that
    names no subject. The substrate requires a non-empty mention on every claim
    and is right to — a claim about nobody is not a claim — so the fallback is
    named rather than left to an empty string.

    ``birth`` is the ONE domain whose subject is the person themselves, and it
    says so (design §3.1): the mention is :data:`OWNER_BIRTH_MENTION`,
    unconditionally, because a birth entry's ladder is three date grains and
    whatever else the row happens to carry, the birthday being filed is the
    owner's. Before this rule the fallback minted the domain word ``"birth"``,
    which read as a *person named "birth"* — and the moment a child's birth
    was filed the fold could no longer tell which of the two births was the
    owner's, so every age claim lost its anchor. Legacy receipts carrying that
    spelling are still read: ``identity_resolution.is_owner_birth_domain_word``
    maps them back to the owner at fold time, so no re-harvest is required and
    the two spellings group as one node.
    """
    if collapsed_text(domain) == "birth":
        return OWNER_BIRTH_MENTION
    named = landmarks_interaction.identity_named(entry, row) if isinstance(row, dict) else None
    if not named and isinstance(entry, dict):
        for field in landmarks_interaction.IDENTITY_FIELDS:
            text = entry.get(field)
            if isinstance(text, str) and text.strip():
                named = text.strip()
                break
    mention = collapsed_text(named) or collapsed_text(domain)
    return mention[:200]


def _evidence_for(entry: dict, domain: str, field_label: str) -> dict:
    """The bounded, HONEST quotation behind a converted claim.

    A legacy entry is not a sentence somebody said — the words that produced it
    were never kept, which is precisely the thinness this import is honest
    about. So the evidence quotes the RECORD, in its canonical form, and says
    which field of it the claim was read from. It is a real, checkable
    quotation of the real source document; it is simply a quotation of a filed
    record rather than of a spoken sentence, and the receipt's extractor
    version says so out loud.
    """
    quoted = entry.get(field_label) if field_label in entry else entry
    return {
        "quote": bounded_quote(f"{domain}.{field_label} = {canonical_json(quoted)}"),
        "locator": f"{domain}/{field_label}",
    }


def _date_claim(
    record: object,
    *,
    entry: dict,
    domain: str,
    mention: str,
    event_kind: str,
    field_label: str,
    source_ref: object,
    extractor_version: str,
    now: object,
) -> dict | None:
    """One dated claim read out of one stored `chronology` record, or ``None``.

    The record's own ``basis`` decides the claim's basis through
    :data:`temporal_claims.CLAIM_BASIS_BY_DATE_BASIS` — the v222 carriage
    landing where it was always going. Nothing is upgraded: a date the system
    calculated from an age arrives as ``calculated`` and stays there.
    """
    parsed = chrono.from_dict(record)
    if parsed is None:
        return None
    basis = CLAIM_BASIS_BY_DATE_BASIS.get(parsed.basis, "inferred")
    return validate_temporal_claim(
        {
            "source_ref": source_ref,
            "source_kind": "import",
            "claim_type": "date",
            "subject_mention": mention,
            "event_kind": event_kind,
            "temporal_value": parsed.to_dict(),
            "evidence": [_evidence_for(entry, domain, field_label)],
            "basis": basis,
            "confidence": _confidence_for(parsed),
            "extractor_version": extractor_version,
        },
        now=now,
    )


#: `chronology.CONFIDENCES` -> the claim's calibrated 0..1 support. The claim
#: schema wants a number and the package has always spoken in words; this is
#: the one place the two meet. The numbers are ORDINAL — they preserve the
#: package's own ordering and nothing more — and they are never allowed to
#: substitute for provenance, which is why `basis` is carried separately.
CONFIDENCE_SCORE = {
    "certain": 0.95,
    "approximate": 0.7,
    "inferred": 0.45,
    "conjectural": 0.2,
}


def _confidence_for(record: object) -> float:
    parsed = chrono.from_dict(record)
    if parsed is None:
        return 0.0
    return CONFIDENCE_SCORE.get(parsed.confidence, 0.45)


def entry_claims(
    domain: object,
    entry: object,
    *,
    source_ref: object,
    extractor_version: str = LEGACY_EXTRACTOR,
    now: object = None,
) -> list[dict]:
    """Every temporal claim one filed landmark record asserts. PURE, no model.

    The deterministic rule, in full:

    * ONE ``identity`` claim, always. It says the entry was named and carries
      no date, and it is what a correction retracts to remove the entry.
    * ``entry["date"]`` and each of its ``date_alternates`` -> a ``date``
      claim at :func:`date_event_kind`. The alternates are not decoration:
      v222 kept every claim a date OUTRANKED, and here they become what they
      always were — RIVAL CLAIMS, which the projection reconciles again on
      every draw.
    * ``entry["span"]["start"]`` / ``["end"]`` and their ``span_alternates``
      -> ``date`` claims at :data:`SPAN_START_EVENT_KIND` /
      :data:`SPAN_END_EVENT_KIND`.

    Claims whose id collides are folded to the first, in score order. That is
    not a shortcut: the substrate's own rule is that the same fact asserted
    twice in one source is one claim (``derive_claim_id`` deliberately keeps
    evidence out of the digest), and two stored alternates that reduce to the
    same interval on the same reading ARE the same fact. `chronology` folds
    repeat tellings by ``(edtf, basis)`` and the claim id folds by interval
    alone, so the narrow gap between those two definitions is the only thing
    this dedupe ever closes.
    """
    if not isinstance(entry, dict):
        raise LandmarkProjectionError(
            "landmark_record_empty", "a landmark record must be an object"
        )
    name = collapsed_text(domain)
    if not name:
        raise LandmarkProjectionError(
            "landmark_domain_required", "a landmark record needs a domain"
        )
    row = domain_row_or_none(name)
    mention = entry_subject_mention(entry, row, name)
    kind = date_event_kind(row)

    claims: list[dict] = [
        validate_temporal_claim(
            {
                "source_ref": source_ref,
                "source_kind": "import",
                "claim_type": "identity",
                "subject_mention": mention,
                "evidence": [_evidence_for(entry, name, "domain")],
                # An entry's existence is as explicit as the act of filing it.
                "basis": "explicit",
                "confidence": 1.0,
                "extractor_version": extractor_version,
            },
            now=now,
        )
    ]

    span = entry.get("span") if isinstance(entry.get("span"), dict) else {}
    span_alternates = entry.get(landmarks_interaction.SPAN_ALTERNATES_KEY)
    if not isinstance(span_alternates, dict):
        span_alternates = {}

    plan: list[tuple[object, str, str]] = []
    plan.append((entry.get("date"), kind, "date"))
    for alternate in _as_list(entry.get(landmarks_interaction.DATE_ALTERNATES_KEY)):
        plan.append((alternate, kind, "date"))
    for bound, bound_kind in (
        ("start", SPAN_START_EVENT_KIND),
        ("end", SPAN_END_EVENT_KIND),
    ):
        plan.append((span.get(bound), bound_kind, "span"))
        for alternate in _as_list(span_alternates.get(bound)):
            plan.append((alternate, bound_kind, "span"))

    for record, event_kind, field_label in plan:
        if not record:
            continue
        claim = _date_claim(
            record,
            entry=entry,
            domain=name,
            mention=mention,
            event_kind=event_kind,
            field_label=field_label,
            source_ref=source_ref,
            extractor_version=extractor_version,
            now=now,
        )
        if claim is not None:
            claims.append(claim)

    deduped: dict[str, dict] = {}
    for claim in claims:
        deduped.setdefault(claim["claim_id"], claim)
    return list(deduped.values())


def _as_list(value: object) -> list:
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


# --------------------------------------------------------------------------
# The promoted landmark source
# --------------------------------------------------------------------------


def entry_promotion_digest(domain: object, entry: object, *, ordinal: int) -> str:
    """The sha256 identifying ONE filed landmark record.

    Domain, the record's bytes and its filing ordinal. The ordinal is in the
    identity on purpose: filing the identical record twice in a row is two
    tellings, and the substrate's answer to "did they say it twice?" is two
    sources with two receipts, never one file silently absorbing the second.
    Re-running the SAME import, however, recomputes the same ordinals and
    therefore the same digests, which is what makes the flip idempotent.
    """
    payload = {
        "domain": collapsed_text(domain),
        "entry": entry if isinstance(entry, dict) else {},
        "ordinal": int(ordinal),
    }
    return store.payload_sha256(canonical_json(payload))


def landmark_source_relative_path(digest: str) -> str:
    """``sources/landmarks/entry-<24 hex>.md`` — a pure function of the record."""
    text = collapsed_text(digest).lower()
    if len(text) < store.FILENAME_DIGEST_LENGTH or not all(
        c in "0123456789abcdef" for c in text
    ):
        raise LandmarkProjectionError(
            "landmark_source_malformed", f"not a sha256 digest: {digest!r}"
        )
    return f"{LANDMARK_SOURCES_DIR}/entry-{text[:store.FILENAME_DIGEST_LENGTH]}.md"


def promote_landmark_entry(
    vault_root: str | Path,
    domain: object,
    entry: object,
    *,
    ordinal: int,
    filed_at: object = None,
) -> SourceRef:
    """File one landmark record as a durable vault source and return its ref.

    Amendment 2's pairing rule, applied to the ladder: the record becomes an
    ordinary source document BEFORE any claim cites it, so a crash between the
    two leaves a re-runnable state and never a receipt citing a source that is
    not in the vault. Idempotent on :func:`entry_promotion_digest`.

    The frontmatter carries the grouping key and the filing order because they
    are facts about the FILING — which domain it was filed under, which entry
    it is a telling of, and when in the sequence it arrived. The projection
    needs all three and may not re-derive them later from a drawing it is
    itself responsible for producing.
    """
    name = collapsed_text(domain)
    if not name:
        raise LandmarkProjectionError(
            "landmark_domain_required", "a landmark record needs a domain"
        )
    if not isinstance(entry, dict) or not entry:
        raise LandmarkProjectionError(
            "landmark_record_empty", "a landmark record must be a non-empty object"
        )

    row = domain_row_or_none(name)
    digest = entry_promotion_digest(name, entry, ordinal=ordinal)
    relative = landmark_source_relative_path(digest)
    payload = f"{canonical_json(entry)}\n"

    frontmatter: dict = {
        "title": _source_title(entry, row, name),
        "type": LANDMARK_SOURCE_TYPE,
        "source_id": f"landmark:entry-{digest[:store.FILENAME_DIGEST_LENGTH]}",
        "source_medium": "landmark_ladder",
        "landmark_domain": name,
        "landmark_entry_key": landmarks_interaction.landmark_entry_key(entry, row),
        "filed_ordinal": int(ordinal),
        "captured_at": normalized_timestamp(filed_at, error=LandmarkProjectionError),
        "visibility": "owner_only",
        "status": "raw",
        "immutable": True,
        "schema_version": SCHEMA_VERSION,
        "source_path": relative,
        "content_sha256": store.payload_sha256(payload),
    }

    content = f"{store.format_frontmatter(frontmatter)}\n\n{payload}"
    root = _root(vault_root)
    path = store.store_path(root, relative)
    try:
        atomic_create_vault_bytes(path, content.encode("utf-8"), vault_root=root)
    except FileExistsError:
        pass
    except ValueError as exc:
        raise LandmarkProjectionError("landmark_source_malformed", str(exc)) from exc

    source_ref = store.read_source_ref(vault_root, relative)
    if source_ref is None:  # pragma: no cover - the create above guarantees it
        raise LandmarkProjectionError(
            "landmark_source_malformed", f"{relative} vanished during promotion"
        )
    return source_ref


def _source_title(entry: dict, row: object, domain: str) -> str:
    named = landmarks_interaction.identity_named(entry, row) if isinstance(row, dict) else None
    if named:
        return f"{domain}: {named}"[:120]
    if entry.get("none") is True:
        return f"{domain}: none"
    if entry.get("skipped") is True:
        return f"{domain}: skipped"
    return domain


# --------------------------------------------------------------------------
# Filing: source, then receipt, both idempotent
# --------------------------------------------------------------------------


def file_landmark_record(
    vault_root: str | Path,
    domain: object,
    entry: object,
    *,
    ordinal: int,
    extractor_version: str = LIVE_EXTRACTOR,
    now: object = None,
) -> dict:
    """Promote one record and file its receipt. The pairing rule, in one call.

    Returns ``{"source_ref", "receipt_path", "claims"}``. Source first, then
    receipt, both idempotent — the identical ordering
    `temporal_store.file_message_extraction` uses, for the identical reason.
    """
    source_ref = promote_landmark_entry(
        vault_root, domain, entry, ordinal=ordinal, filed_at=now
    )
    claims = entry_claims(
        domain,
        entry,
        source_ref=source_ref.to_dict(),
        extractor_version=extractor_version,
        now=now,
    )
    receipt = validate_extraction_receipt(
        {
            "source_ref": source_ref.to_dict(),
            "extractor_version": extractor_version,
            "extractor": {
                "name": "landmark-entry-rule",
                "rule_version": "1",
                "deterministic": True,
            },
            "claims": claims,
            "recorder": "landmark_projection",
        },
        now=now,
    )
    path = store.write_receipt(vault_root, receipt, now=now)
    return {
        "source_ref": source_ref,
        "receipt_path": path.relative_to(_root(vault_root)).as_posix(),
        "claims": claims,
    }


# --------------------------------------------------------------------------
# Reading the promoted sources back
# --------------------------------------------------------------------------


def load_landmark_sources(vault_root: str | Path) -> list[dict]:
    """Every promoted landmark record, in filing order.

    ``[{"source_id", "relative_path", "domain", "entry_key", "ordinal",
    "record"}, ...]`` sorted by ``(ordinal, source_id)`` — a total order, so
    two records filed with the same ordinal (which the ordinal rules make
    impossible, but a hand-edited vault could still produce) still fold the
    same way on every machine.

    Unreadable or foreign files are skipped rather than raised on, the way
    every other read path in this package degrades.
    """
    root = _root(vault_root)
    base = store.store_path(root, LANDMARK_SOURCES_DIR)
    if not base.is_dir():
        return []
    rows: list[dict] = []
    for path in sorted(base.glob("entry-*.md")):
        if path.is_symlink() or not path.is_file():
            continue
        relative = path.relative_to(root).as_posix()
        try:
            content = path.read_text(encoding="utf-8")
        except OSError:
            continue
        metadata, body = store.split_frontmatter(content)
        if not metadata or metadata.get("type") != LANDMARK_SOURCE_TYPE:
            continue
        source_id = collapsed_text(metadata.get("source_id"))
        domain = collapsed_text(metadata.get("landmark_domain"))
        if not source_id or not domain:
            continue
        try:
            record = json.loads(body.strip() or "{}")
        except json.JSONDecodeError:
            continue
        if not isinstance(record, dict):
            continue
        rows.append(
            {
                "source_id": source_id,
                "relative_path": relative,
                "domain": domain,
                "entry_key": str(metadata.get("landmark_entry_key") or ""),
                "ordinal": _as_int(metadata.get("filed_ordinal")),
                "record": record,
            }
        )
    rows.sort(key=lambda row: (row["ordinal"], row["source_id"]))
    return rows


def _as_int(value: object) -> int:
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0


# --------------------------------------------------------------------------
# The projection
# --------------------------------------------------------------------------


def project_landmark_entries(active_index: object, *, sources: object) -> dict:
    """Draw ``state/landmarks.json`` from the active claims. PURE.

    ``active_index`` is `temporal_store.fold_active_index`'s mapping;
    ``sources`` is :func:`load_landmark_sources`'s list. Returns the file's
    own shape, ``{"version": 1, "domains": {domain: [entry, ...]}}``.

    The fold, in the order it runs:

    1. **Keep only sources with an active identity claim.** A source whose
       identity claim was retracted or superseded contributed a telling that
       no longer stands, and it drops out entirely. This is the one gate, and
       it is why the identity claim exists.
    2. **Group the survivors by ``(domain, entry_key)``**, in filing order.
       Several tellings of one entry — a city in March, an address in April —
       are one group.
    3. **Fold each group's SKELETONS** through
       `landmarks_interaction.merge_landmark_entry`, which is the same
       function the pre-flip write path used and therefore agrees with it by
       construction, including on the none terminal in both directions.
       Dates are stripped first (:func:`skeleton_of`) so this step cannot see
       one.
    4. **Reconcile each group's DATE CLAIMS** through `chronology.reconcile`,
       one reconciliation per date field, and write the winner plus every
       loser as the entry's ``date`` / ``date_alternates`` /
       ``span`` / ``span_alternates``. Identical to what
       `merge_landmark_entry` used to store at write time — same function,
       same claims, later.

    Entry ORDER within a domain is the order the group's FIRST telling was
    filed, which reproduces the pre-flip file exactly and keeps `residences`
    and `schools` — the sequence domains, whose order is part of the fact —
    walking forward in time as they did before.
    """
    active = {
        row.get("claim_id")
        for row in store.active_claims(active_index if isinstance(active_index, dict) else {})
    }
    by_source: dict[str, list[dict]] = {}
    for row in (active_index or {}).get("claims") or ():
        if not isinstance(row, dict) or row.get("claim_id") not in active:
            continue
        ref = row.get("source_ref")
        source_id = collapsed_text(ref.get("source_id")) if isinstance(ref, dict) else ""
        if source_id:
            by_source.setdefault(source_id, []).append(row)

    groups: dict[tuple[str, str], dict] = {}
    order: list[tuple[str, str]] = []
    for source in sources or ():
        claims = by_source.get(source["source_id"]) or []
        if not any(claim.get("claim_type") == "identity" for claim in claims):
            continue
        key = (source["domain"], source["entry_key"])
        if key not in groups:
            groups[key] = {"skeletons": [], "claims": []}
            order.append(key)
        groups[key]["skeletons"].append(skeleton_of(source["record"]))
        groups[key]["claims"].extend(claims)

    domains: dict[str, list[dict]] = {}
    for key in order:
        domain, _entry_key = key
        group = groups[key]
        entry: dict = {}
        for skeleton in group["skeletons"]:
            entry = landmarks_interaction.merge_landmark_entry(entry, skeleton)
        entry = skeleton_of(entry)
        row = domain_row_or_none(domain)
        _attach_dates(entry, group["claims"], row=row)
        domains.setdefault(domain, []).append(entry)

    return {"version": LANDMARKS_SCHEMA_VERSION, "domains": domains}


def _attach_dates(entry: dict, claims: list[dict], *, row: object) -> None:
    """Reconcile one group's dated claims onto the entry it belongs to."""
    kind = date_event_kind(row)
    buckets: dict[str, list[dict]] = {}
    for claim in claims:
        if claim.get("claim_type") != "date":
            continue
        record = chrono.from_dict(claim.get("temporal_value"))
        if record is None:
            continue
        buckets.setdefault(str(claim.get("event_kind") or ""), []).append(record.to_dict())

    best, alternates = _reconciled(buckets.get(kind))
    _set_or_drop(entry, "date", best)
    _set_or_drop(entry, landmarks_interaction.DATE_ALTERNATES_KEY, alternates or None)

    span: dict = {}
    span_alternates: dict = {}
    for bound, bound_kind in (
        ("start", SPAN_START_EVENT_KIND),
        ("end", SPAN_END_EVENT_KIND),
    ):
        bound_best, bound_alternates = _reconciled(buckets.get(bound_kind))
        if bound_best:
            span[bound] = bound_best
        if bound_alternates:
            span_alternates[bound] = bound_alternates
    _set_or_drop(entry, "span", span or None)
    _set_or_drop(entry, landmarks_interaction.SPAN_ALTERNATES_KEY, span_alternates or None)


def _reconciled(records: object) -> tuple[dict | None, list[dict]]:
    rows = [r for r in (records or ()) if r]
    if not rows:
        return None, []
    result = chrono.reconcile(rows)
    best = result["best_supported"]
    if best is None:
        return None, []
    return best.to_dict(), [record.to_dict() for record in result["alternates"]]


def _set_or_drop(target: dict, key: str, value: object) -> None:
    if value:
        target[key] = value
    else:
        target.pop(key, None)


# --------------------------------------------------------------------------
# The one-time flip
# --------------------------------------------------------------------------


def legacy_import_done(vault_root: str | Path) -> bool:
    """Has this vault already been converted?

    True when ANY receipt names :data:`LEGACY_EXTRACTOR`. Deliberately NOT a
    check for a specific receipt id: a receipt id binds to a source REVISION,
    the projection rewrites `state/landmarks.json` after the import, and a
    revision-bound check would therefore re-import the whole vault on the
    second compile and mint a duplicate of every claim. This is the exact
    trap the amendment's "idempotent by receipt" wording invites, and the
    state-machine test in `tests/test_landmark_projection.py` exists to keep
    it shut.
    """
    for relative in store.receipt_relative_paths(vault_root):
        receipt = store.read_receipt(vault_root, relative)
        if receipt is not None and receipt.extractor_version == LEGACY_EXTRACTOR:
            return True
    return False


def already_substrate_backed(vault_root: str | Path) -> bool:
    """Is this vault's drawing ALREADY derived? Then there is nothing to flip.

    Any promoted landmark source at all means the substrate is the truth,
    however it got that way — the one-time import, or an ordinary write in a
    vault that never held a legacy entry to import.

    :func:`legacy_import_done` alone is not this question and using it as the
    gate is a live bug, not a nicety: a vault created AFTER the flip has only
    ``landmark-record`` receipts and no ``legacy-entry-import`` one, so a
    legacy-receipt gate reads "never flipped", re-imports the projection it
    just drew, and files every entry a second time as its own ancestor. The
    committed none-supersession tests catch it, which is how it was found.
    """
    return bool(load_landmark_sources(vault_root))


def import_legacy_landmarks(
    vault_root: str | Path,
    landmarks: object,
    *,
    now: object = None,
) -> dict:
    """Convert every existing entry into sources + receipts. Deterministic.

    ``landmarks`` is `timeline.load_landmarks`'s mapping. Ordinals are
    assigned by walking the domains in the file's own order and each domain's
    entries in their stored order, so the projection redraws the file with its
    entries in the positions they already occupy.

    Idempotent: re-running assigns the same ordinals, so every promotion digest
    and every claim id is the same, every source file is already there and
    every receipt is byte-identical — nothing is written twice.
    """
    summary = {"sources": 0, "receipts": 0, "claims": 0, "entries": 0}
    ordinal = 0
    for domain, entries in (landmarks or {}).items():
        for entry in entries or ():
            if not isinstance(entry, dict) or not entry:
                continue
            ordinal += 1
            filed = dict(entry)
            filed.setdefault("domain", domain)
            result = file_landmark_record(
                vault_root,
                domain,
                filed,
                ordinal=ordinal,
                extractor_version=LEGACY_EXTRACTOR,
                now=now,
            )
            summary["entries"] += 1
            summary["sources"] += 1
            summary["receipts"] += 1
            summary["claims"] += len(result["claims"])
    return summary


def next_ordinal(vault_root: str | Path) -> int:
    """The ordinal the next filed record takes — one past the highest filed."""
    rows = load_landmark_sources(vault_root)
    return (max((row["ordinal"] for row in rows), default=0)) + 1


def entry_source_ids(sources: object, *, domain: str, entry_key: str) -> set[str]:
    """The promoted sources that are tellings of ONE entry."""
    return {
        source["source_id"]
        for source in (sources or ())
        if source.get("domain") == domain and source.get("entry_key") == entry_key
    }


def active_claim_ids_for_entry(
    vault_root: str | Path, *, domain: str, entry_key: str
) -> list[str]:
    """Every ACTIVE claim id standing behind one projected entry, sorted.

    What a correction has to name in order to remove that entry from the
    drawing. Sorted so the correction's own content digest — and therefore its
    filename — is the same on every machine.
    """
    index = store.read_active_index(vault_root) or store.fold_active_index(vault_root)
    ids = entry_source_ids(
        load_landmark_sources(vault_root), domain=domain, entry_key=entry_key
    )
    found = []
    for row in store.active_claims(index):
        ref = row.get("source_ref")
        if isinstance(ref, dict) and collapsed_text(ref.get("source_id")) in ids:
            found.append(str(row.get("claim_id")))
    return sorted(found)


def retire_entry(
    vault_root: str | Path,
    *,
    domain: str,
    entry_key: str,
    reason: str,
    occurred_at: object = None,
) -> object | None:
    """Supersede every claim behind one entry, so the projection drops it.

    This is how `entry_superseded_by`'s cross-entry rules are expressed after
    the flip. They used to be a `continue` in a rebuild loop — the entry simply
    was not copied forward, and the fact that it had ever been filed went with
    it. Now the entry's evidence stays on disk and a durable correction says
    which claims stopped standing and why, which is the difference between
    forgetting and remembering that you changed your mind.

    ``None`` when the entry has no active claims to retire — a no-op, not an
    error, so replaying a write cannot fail on the second pass.
    """
    claim_ids = active_claim_ids_for_entry(
        vault_root, domain=domain, entry_key=entry_key
    )
    if not claim_ids:
        return None
    return store.supersede_claims(
        vault_root,
        claim_ids,
        reason=reason,
        scope=f"landmarks/{domain}",
        occurred_at=occurred_at,
    )


def redraw(vault_root: str | Path) -> dict:
    """Fold the receipts, read the sources, draw the file's content. No I/O out.

    The whole projection in one call, and deliberately WITHOUT the write: the
    landmark store's path is resolved by `lifehug_core` against the process's
    bound vault and differs between an embedded-layout vault (where it is
    ``system/landmarks.json``) and an external one (``state/landmarks.json``).
    Re-deriving that path here would be a second definition of where the file
    lives, so the one writer is `timeline.redraw_landmarks`, which already
    holds it as ``LANDMARKS_STORE``.
    """
    index = store.rebuild_active_index(vault_root)
    sources = load_landmark_sources(vault_root)
    return project_landmark_entries(index, sources=sources)


def flip_if_needed(vault_root: str | Path, landmarks: object, *, now: object = None) -> dict | None:
    """Run the one-time conversion. ``None`` when this vault is already flipped.

    The migration trigger: entries exist and no legacy receipt does. The caller
    redraws afterwards — `timeline.redraw_landmarks` does both in order.
    Called on every derive/compile, and a no-op on every call after the first.
    """
    if already_substrate_backed(vault_root):
        return None
    if not any(entries for entries in (landmarks or {}).values()):
        return None
    return import_legacy_landmarks(vault_root, landmarks, now=now)
