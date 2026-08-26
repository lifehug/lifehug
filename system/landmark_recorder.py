#!/usr/bin/env python3
"""The landmark RECORDER — recording is a separate job from replying (v212).

ADR 0028 (lifehug#221). Until v209 one model completion did two jobs on a
landmark turn: talk to the person, and file what they said in the additive
``landmark`` field. On the founder's own vault, twice on one leaf, the first
job won and the second silently did not happen — a warm reply about a mission
abroad where the domain's answer was a plain ``none``, and the names of people
lost said back and never filed. The instruction telling the model to record
was already in that leaf. Prose alone cannot be certified.

So the recording is its own pass. The conversation writes the reply; the
RECORDER reads the person's own message afterwards and files the record. It
has no voice, no person to please, and exactly one output. Its backstop is
:data:`landmarks_interaction.ANSWER_MUST_RECORD_LINT` — the one blocking
landmark lint — and ONE regeneration carrying
:func:`landmarks_interaction.recording_reminder`.

**One recorder, two triggers.** :func:`record_answer` is the whole contract:
the live landmark turn calls it right after the reply is generated, and a
historical sweep (the platform's landmark re-harvest) calls the SAME function
over the turns people already gave. The sweep therefore inherits the lint and
the retry for free, which is the only reason re-running a historical answer is
a fix rather than a second roll of the same dice.

**One answer, MANY records (v214, lifehug#227).** The canonical output is
``{"landmarks": [<record>, ...]}`` and the whole module speaks in record
SETS. v212's ``{"landmark": {...}}`` is still accepted and normalizes to a
one-element set, so no prompt, no host and no stored payload has a flag day.
Children, work, residences, family, partnerships and losses are all
multi-entry domains: one answer routinely carries many entries, and filing
one of them is losing the rest. Each record is validated ALONE, so an invalid
one drops without taking its siblings with it.

**ONE COMPLETION, TWO SHAPES (v229, Wave C item C3).** The same pass now also
emits TEMPORAL CLAIMS — `temporal_claims.TemporalClaim` drafts, one per
independently asserted fact — beside the landmark records, and
:func:`file_claims` promotes the message as a vault source and files ONE
immutable receipt over it (owner amendment 2). Nothing about the landmark path
changes: `timeline.save_landmark` keeps its signature and its meaning, every
pre-v229 stored completion parses exactly as it did, and a completion carrying
no ``claims`` list yields an empty :attr:`RecorderOutcome.claims`. The claim
shape exists because a ladder row cannot hold what people actually say —
*"we moved when James was two"* has no date and *"my neighbour's boy was born
in 2019"* has no domain, so both were dropped by design, and the audited plan
(§2.1, §6.4) calls both usable information.

**AND THE PROJECTION MOVES IN THE SAME ACT (v231, wave D item D3).**
:func:`file_claims` publishes the calculated timeline as its last step,
through the same `temporal_publication.publish` the landmark seat
(`timeline.redraw_landmarks`) uses. Before this a conversational claim landed
in the substrate and waited for an unrelated landmark write before the daily
queue or Mirror could see it; now saying something out loud and answering a
ladder row reach those surfaces by the same road, from one publisher.

Pure except for the one injected ``call``: the prompt build, the parse, the
validation and the lints are all deterministic and separately testable, and a
host that runs its own model REPLAYs those four and never this module's loop.
:func:`file_claims` is the one exception and the one function here that
touches a vault.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import conversation_delivery
import general_listener as gl
import landmarks_interaction as li
import temporal_claims as tc
from lifehug_core import INTERACTIONS_DIR

RECORDER_PROMPT = "recorder.md"

#: The LLM purpose this pass spends its completion on. v218 names it here
#: because nothing package-side named it before, and the general listener
#: needs a name to be a SECOND of: `general_listener.DATE_RECORD_PURPOSE` is
#: `"date_record"`, a second name and never a rename of this one. Two prompts,
#: two outputs, two backstops — a host budgets, routes and audits them apart.
RECORDER_PURPOSE = gl.LANDMARK_RECORD_PURPOSE

#: The recorder's own role. A small model is the right one here and the cost
#: statement is honest: ONE extra completion per landmark ANSWER — not per
#: turn of every conversation, not on the daily question, not on any session
#: that is not a landmark session. The prompt is a few hundred tokens with no
#: transcript in it (see `build_recorder_prompt`), which is why the second
#: call is cheaper than the first by an order of magnitude.
DEFAULT_RECORDER_ROLE = "haiku-class"

STATUS_RECORDED = "recorded"
STATUS_NOTHING = "nothing"
STATUS_WITHHELD = "withheld"
STATUS_UNAVAILABLE = "unavailable"

#: How many times the recorder runs at most: the attempt, and ONE regeneration
#: carrying the reminder. Never more — a second failure is a withheld record a
#: host can retry later, never a loop.
MAX_ATTEMPTS = 2


class LandmarkRecorderError(Exception):
    """The recorder could not be composed (never raised into capture)."""


@dataclass(frozen=True)
class RecorderOutcome:
    """What one recorder pass produced.

    v214: :attr:`records` is the outcome — a person can answer one question
    with four children or twelve jobs, and every one of them is an entry.
    :attr:`record` remains as the FIRST of them so a caller written against
    v212 keeps working unchanged; a caller that files is filing
    :attr:`records`, and `landmarks_interaction.landmark_invocations` turns
    the set into one invocation per entry.

    v229 adds :attr:`claims` BESIDE them, not instead of them, and the two
    reach the substrate by DIFFERENT ROADS. A record goes on filing through
    `timeline.save_landmark`, which since v225 promotes it to
    ``sources/landmarks/`` and converts it by a deterministic RULE
    (`landmark_projection`); the claims go to ``sources/conversations/``
    through `temporal_store.file_message_extraction` — one message, one
    promoted source, one receipt, N claims. Two sources, two extractors, one
    active index. See :func:`file_claims` for why that is corroboration and
    not duplication.
    """

    status: str
    records: tuple[dict, ...] = ()
    #: v218 (ADR 0029): the PERSON DATES a no-focus pass heard, typed
    #: separately because they file through a different seam
    #: (`entity-verdict --born/--died`, v217) and are FAMILY-ONLY by owner
    #: ruling. Always empty in focused mode, so every v214 caller is
    #: untouched — a heterogeneous `records` list was the shape the audit
    #: refused.
    people: tuple[dict, ...] = ()
    #: The NAMED drops a no-focus parse made
    #: (`general_listener.DROPPED_NON_FAMILY` / `DROPPED_NO_DATE`). A refused
    #: record must be legible, not silent.
    findings: tuple[str, ...] = ()
    attempts: int = 0
    lint_ids: tuple[str, ...] = ()
    reason: str = ""
    prompts: tuple[str, ...] = field(default=(), repr=False)
    #: v229 (Wave C, item C3): the TEMPORAL CLAIM DRAFTS the same completion
    #: emitted — one per independently asserted fact, in the substrate's own
    #: vocabulary (`temporal_claims`), UNBOUND until a source is promoted for
    #: the message (`file_claims`). Deliberately the LAST field: a caller that
    #: built or unpacked this outcome positionally keeps building and
    #: unpacking the same one, which is what "bridging, not big-bang" costs
    #: here. Always empty for a completion that emitted no `claims` list, so
    #: every pre-v229 stored completion parses exactly as it did.
    claims: tuple[dict, ...] = ()

    @property
    def record(self) -> dict | None:
        """The first record, for every v212 caller (see the class note)."""
        return self.records[0] if self.records else None


def _prompt_path(framework_root: str | Path | None = None) -> Path:
    base = (Path(framework_root) / "interactions" / "landmarks"
            if framework_root else INTERACTIONS_DIR / "landmarks")
    return base / "prompt" / RECORDER_PROMPT


def load_recorder_leaf(framework_root: str | Path | None = None) -> str:
    """The recorder leaf, verbatim. A host REPLAYs exactly this text."""
    try:
        return _prompt_path(framework_root).read_text(encoding="utf-8")
    except OSError as exc:
        raise LandmarkRecorderError(f"no recorder leaf: {exc}") from exc


def recordable_keys(row: object) -> tuple[str, ...]:
    """The keys the recorder may emit for ONE domain — v211's own declaration.

    lifehug#219/#220 fixed the READ side of a defect class: a ladder rung is
    satisfied by whatever the WRITER files it under, not only by a key of its
    own name, and `landmarks_interaction.rung_satisfiers(row, rung)` is that
    list as data. This is the WRITE side of the same fact, and it is the SAME
    list, walked: the recorder is offered exactly the fields the ladder can
    read, so it cannot manufacture a record that validates, stores, and is
    seen by nothing.

    ONE declaration, not two (recurring-defect doctrine). `rung_satisfiers`
    is the only source of the rung fields here — no local date-grain set, no
    local identity-rung set — and
    `test_recordable_keys_are_exactly_the_ladders_satisfiers` binds them.
    `DOMAIN_AGNOSTIC_FIELDS` names the two shapes this excludes, and they are
    the two the certification audit found live: `span` on `children` (whose
    ladder has no span) and `label` on `birth` (whose ladder names no
    subject).

    Three fields are not rungs and never will be
    (`landmarks_interaction.NON_RUNG_FIELDS`), so they are added by their own
    rule rather than derived:

    * ``skipped`` — always; a decline is an answer this pass can record.
    * ``none`` — where `domain_accepts_none` allows the terminal.
    * ``chain_complete`` — where the domain's `closure` is
      `user_completable`, i.e. where only the person can say the list is
      finished (v219: read off `closure`, never off the retired `chain`
      flag, which also meant multiplicity and order).
    * ``subject`` and ``birth_order`` — free-text descriptors
      `landmark_invocation` passes through to the writer. ``subject``
      describes a NAMED subject, so it is offered exactly where
      `identity_rung` finds one (never on `birth`); ``birth_order`` is the
      companion to a `birth` rung on an enumeration of people, which the
      ladder states outright as `birth` AND `relation` — `family`, and
      nothing else.
    """
    if not isinstance(row, dict):
        return ()
    ladder = tuple(row.get("ladder") or ())
    keys = ["domain"]
    for rung in ladder:
        # `happened` is entailed by any answer field at all, never written by
        # name (`asserts_happened`) — `rung_satisfiers` says so out loud.
        if rung == li.NONE_OPENER:
            continue
        keys.extend(li.rung_satisfiers(row, rung))
    if li.identity_rung(row) is not None:
        keys.append("subject")
        if {"birth", "relation"} <= set(ladder):
            keys.append("birth_order")
    keys.append("skipped")
    if li.domain_accepts_none(row):
        keys.append("none")
    if li.requires_declared_closure(row):
        keys.append("chain_complete")
    domain = str(row.get("domain") or "")
    return tuple(key for key in dict.fromkeys(keys) if _survives(domain, key))


#: One probe value per key shape, for :func:`_survives`. The values are
#: throwaway; only whether `validate_landmark` KEEPS the key matters.
_PROBE_SPAN = {"best": "1984", "earliest": "1984-01-01", "latest": "1984-12-31"}
_PROBE_VALUES: dict[str, object] = {
    "date": dict(_PROBE_SPAN),
    "span": {"start": dict(_PROBE_SPAN), "end": dict(_PROBE_SPAN)},
    "skipped": True,
    "none": True,
    "chain_complete": True,
    "living": True,
}


def _survives(domain: str, key: str) -> bool:
    """Whether ``key`` survives BOTH validation layers for ``domain``.

    The second half of the offer, and the one the ladder alone cannot give.
    It probes the very path :func:`parse_recorder_output` runs — structural
    first, semantic second — because a key that does not survive it is a key
    the recorder must never be told to write. Two live instances, both caught
    here rather than by a hand-kept list:

    * ``name`` satisfies any domain's identity rung on the READ side
      (`identity_named` looks in `label` OR `name`), but `validate_landmark`
      stores a rung key only when it is that domain's OWN rung — a `name`
      filed on `children` is dropped before anything reads it.
    * ``birth`` is `family`'s own ladder rung and is NOT in
      `conversation_delivery._LANDMARK_KEYS`, so emitting it degrades the
      WHOLE record to None. A sibling's birth year reaches the ladder through
      `date`, which is what `rung_satisfiers` lists beside it.
    """
    if key == "domain":
        return True
    probe = {"domain": domain, key: _PROBE_VALUES.get(key, "x")}
    structural = conversation_delivery._parse_landmark(probe)  # noqa: SLF001
    validated = li.validate_landmark(structural)
    return isinstance(validated, dict) and key in validated


def build_recorder_prompt(*, domain: str, question_asked: str,
                          answer: str, reply: str = "",
                          landmarks: object = (),
                          reminder: str = "",
                          framework_root: str | Path | None = None) -> str:
    """The recorder's whole prompt, from the leaf plus six substitutions.

    Deliberately NOT the conversation prompt. It carries no identity, no
    behavior, no examples and no transcript — only the domain, its ladder,
    what is ALREADY FILED under it, the question that was asked, what the
    person said, and what they were told back. That is the entire evidence a
    recording decision needs, and leaving the rest out is what makes the
    second call small.

    ``landmarks`` is the LANDMARKS store (``{domain: [entry, ...]}``) or, for
    a caller that has already selected them, this domain's own entries —
    `landmarks_interaction.landmark_entries` reads both. v216 (lifehug#230)
    changed what it is FOR: until then the block under "ALREADY KNOWN — never
    record these again" was `render_landmarks`, one line per domain saying
    `- children: partial (4)`, and a store dict — which is what every real
    caller holds, this module's own CLI included — rendered as "(nothing
    yet)". A model cannot decline to re-file four children it has never been
    shown. It is now `render_known_entries`, which names them.
    """
    row = li.domain_row(domain, framework_root=framework_root)
    known = li.render_known_entries(landmarks, domain,
                                    framework_root=framework_root)
    filled = load_recorder_leaf(framework_root)
    # `.replace`, never `.format` — every leaf in this package substitutes the
    # same way, and these leaves carry literal JSON braces.
    for token, value in (
        ("{question_asked}", (question_asked or row["ask"]).strip()),
        ("{ladder}", " | ".join(row["ladder"])),
        ("{recordable_keys}", " | ".join(recordable_keys(row))),
        ("{none_allowed}", "yes" if li.domain_accepts_none(row) else "no"),
        ("{known_entries}", known),
        ("{claim_types}", " | ".join(tc.CLAIM_TYPES)),
        ("{event_kinds}", gl.render_event_kinds()),
        ("{answer}", (answer or "").strip()),
        ("{reply}", (reply or "(no reply was generated)").strip()),
        ("{reminder}", f"\n\n{reminder.strip()}" if reminder else ""),
        ("{domain}", domain),
    ):
        filled = filled.replace(token, value)
    return filled


def parse_recorder_output(raw: object, *,
                          framework_root: str | Path | None = None
                          ) -> tuple[dict, ...]:
    """One recorder completion through BOTH pinned validation layers, per record.

    `conversation_delivery._parse_landmark` (structural, closed key set) then
    `landmarks_interaction.validate_landmark` (semantic, closed domain set,
    dates normalized). The SAME two layers the live turn's additive field
    goes through — the recorder introduces no second vocabulary for what a
    landmark is.

    v214 (lifehug#227) changes the SHAPE and nothing else. The canonical
    envelope is ``{"landmarks": [ ... ]}``; ``{"landmark": {...}}`` is still
    read and normalizes to a one-element result, so a v212 prompt, host or
    stored completion parses exactly as it did. EACH record runs both layers
    ALONE — the founder's twelve-job answer must not be lost because the
    eleventh job named a key `work` cannot read — and duplicates collapse.
    A malformed envelope degrades to an EMPTY tuple, never to an error, never
    to a half-record, and never to a dropped sibling.
    """
    if not isinstance(raw, str):
        return ()
    text = raw.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[-1].rsplit("```", 1)[0]
    try:
        data = json.loads(text)
    except (ValueError, TypeError):
        return ()
    if not isinstance(data, dict):
        return ()
    payload = data.get("landmarks")
    if isinstance(payload, dict):
        candidates: list[object] = [payload]
    elif isinstance(payload, (list, tuple)):
        candidates = list(payload)
    else:
        candidates = [data.get("landmark")]
    records: list[dict] = []
    for candidate in candidates:
        structural = conversation_delivery._parse_landmark(candidate)  # noqa: SLF001
        validated = li.validate_landmark(structural,
                                         framework_root=framework_root)
        if isinstance(validated, dict) and validated not in records:
            records.append(validated)
    return tuple(records)


def parse_recorder_claims(raw: object) -> tuple[tuple[dict, ...],
                                                tuple[str, ...]]:
    """The focused recorder's ``claims`` list. ``(drafts, findings)``.

    A named door onto `general_listener.parse_claims`, never a second parse:
    the claim vocabulary is ONE vocabulary and both modes read it with one
    function, exactly as both modes already validate a landmark record through
    the same two pinned layers. This exists so a focused call site says what
    it is doing (`parse_recorder_output` beside it reads the LANDMARK half of
    the same completion) and so the two halves stay visibly separate: a
    refused claim never costs a record and a refused record never costs a
    claim.
    """
    if not isinstance(raw, str):
        return (), ()
    text = raw.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[-1].rsplit("```", 1)[0]
    try:
        data = json.loads(text)
    except (ValueError, TypeError):
        return (), ()
    if not isinstance(data, dict):
        return (), ()
    payload = data.get("claims")
    if payload is None:
        payload = data.get("claim")
    return gl.parse_claims(payload)


RECORDER_EXTRACTOR = "landmark_recorder"


def recorder_extractor(*, model: object = DEFAULT_RECORDER_ROLE,
                       framework_root: str | Path | None = None) -> dict:
    """This pass's extractor block, versioned by its OWN leaf's bytes.

    §4.2 requires a receipt to identify the extractor's prompt, schema and
    model version. The prompt version is a digest of
    :func:`load_recorder_leaf`'s text, so EDITING THE LEAF IS A NEW EXTRACTOR:
    the next extraction lands on a new receipt path beside the old one rather
    than rewriting yesterday's reading, which is how "a later reading is a new
    interpretation, never a cache rebuild" stays true of a later PROMPT and
    not only of a later model.
    """
    return gl.claim_extractor(RECORDER_EXTRACTOR,
                              leaf=load_recorder_leaf(framework_root),
                              model=model)


def recorder_extractor_version(*, model: object = DEFAULT_RECORDER_ROLE,
                               framework_root: str | Path | None = None) -> str:
    return gl.claim_extractor_version(
        recorder_extractor(model=model, framework_root=framework_root))


def file_claims(vault_root, outcome: object, *, message_text: str,
                extractor_version: str, extractor: object = None,
                session_ref: object = None, turn_ref: object = None,
                speaker: object = None, channel: object = None,
                occurred_at: object = None, recorder: object = None,
                now: object = None):
    """Promote the message and file ONE receipt carrying every claim.

    The whole write path of item C3, and deliberately three lines of it: the
    pairing rule, the promotion and the receipt are all
    `temporal_store.file_message_extraction`'s, and this function exists to
    bind an outcome to them rather than to re-decide any of it.

    * **Amendment 2 / option B.** The message becomes an ordinary vault source
      BEFORE anything cites it, so no claim's only citation is a session row.
      One message with N facts is promoted ONCE and every claim cites the same
      revision — the source's own content digest.
    * **One extraction, one receipt, N claims.** The receipt is immutable and
      idempotent: re-running the same extractor over the same message writes
      nothing, and re-running a DIFFERENT extractor (a new model, or an edited
      leaf — see :func:`recorder_extractor`) writes a NEW receipt beside the
      old one.
    * **Idempotency** is `temporal_claims.derive_extraction_idempotency_key`
      over session, turn, source revision, recorder and extractor version.
      ``session_ref`` and ``turn_ref`` travel here for exactly that reason and
      for the claim evidence's own ``turn_ref``.

    **TWO ROADS INTO ONE SUBSTRATE, and why that is corroboration.** Since
    v225 a landmark RECORD is itself promoted (to ``sources/landmarks/``) and
    converted to claims by a deterministic rule, so a fact stated in a focused
    landmark turn can reach the active index twice: once as the ladder row a
    rule read, once as the sentence a model read. They are not duplicates and
    cannot collide — different source, different revision, different extractor
    version, therefore different `derive_claim_id`. They are two INTERPRETATIONS
    of two different sources (plan §4.1), which is exactly the shape the fold
    is built for: v225 moved `chronology.reconcile` to draw time over the live
    active set, and two claims that agree strengthen the placement rather than
    contend for it. What the model's road carries that the rule's cannot is the
    reason this item exists — an event kind, an order against another moment, a
    non-family subject, and the bounded quotation that proves any of it.

    **THE FILING IS NOT DONE UNTIL THE PROJECTION MOVES (v231, wave D item
    D3).** A receipt nobody derived from is a fact the person cannot see: the
    calculated timeline is a materialized projection (plan §7), so a claim
    heard in conversation becomes visible only when that projection is
    republished. This function therefore publishes as the last step of the
    same act, through the SAME one publisher `timeline.redraw_landmarks` uses
    — `temporal_publication.publish` — because two derivations of one truth is
    the dual truth wave B removed and wave D must not reintroduce. Answering
    on the ladder and saying it out loud in a sentence now reach the queue and
    Mirror by the same road.

    The order is the durability rule and it is one way round: promote, receipt,
    THEN publish. The receipt is evidence and the projection is derived from
    it, so a crash before the publish loses nothing a re-run cannot rebuild —
    `file_message_extraction` is idempotent and the publisher's next generation
    reads the receipt that already landed. A publication failure RAISES for the
    same reason it does at the landmark seat: the repair path is "publish
    again", which only works if somebody learns it is needed.

    A host that must not do this work inside a conversation turn (the hosted
    platform's ADR 0020 — *conversations never wait on the vault*) moves the
    whole call off the turn. It does not get a second publisher, and it does
    not get a flag that skips this one.

    Returns ``(source_ref, receipt_path)``, or ``None`` when the outcome
    carries no claims — a message that produced nothing files NOTHING, which
    is the amendment's own rule and not an optimization. Nothing filed means
    nothing derived, so a message with no claims publishes no generation
    either.
    """
    drafts = tuple(getattr(outcome, "claims", None) or
                   (outcome if isinstance(outcome, (list, tuple)) else ()))
    drafts = tuple(draft for draft in drafts
                   if isinstance(draft, dict) and draft)
    if not drafts:
        return None
    from temporal_publication import publish  # noqa: PLC0415
    from temporal_store import file_message_extraction  # noqa: PLC0415

    metadata = {"session_ref": session_ref, "turn_ref": turn_ref,
                "speaker": speaker, "channel": channel,
                "occurred_at": occurred_at}
    metadata = {key: value for key, value in metadata.items() if value}
    filed = file_message_extraction(
        vault_root,
        message_text=message_text,
        extractor_version=extractor_version,
        claims_for=lambda source_ref: gl.bind_claims(
            drafts, source_ref=source_ref,
            extractor_version=extractor_version, now=now),
        metadata=metadata,
        extractor=extractor,
        recorder=str(recorder) if recorder else None,
        now=now,
    )
    publish(vault_root, now=now)
    return filed


def record_answer(*, answer: str, call, domain: str | None = None,
                  reply: str = "", question_asked: str = "",
                  landmarks: object = (), known_labels: object = (),
                  model: str = DEFAULT_RECORDER_ROLE,
                  framework_root: str | Path | None = None) -> RecorderOutcome:
    """Run the recorder over one answer: extract, lint, retry once, file.

    **THE ONE LOOP, TWO MODES (v218, ADR 0029).** With a ``domain`` this is
    the FOCUSED recorder ADR 0028 built: it is shown that domain's ladder and
    that domain's filed entries, and it records the answer to the question
    that was asked — and only that domain, which the 2026-08-25 audit
    explicitly refused to repeal. With ``domain=None`` it is the GENERAL
    LISTENER: no question was asked, so it hears whatever datable facts are
    in the message, across every domain, plus FAMILY person dates. Same
    attempt count, same single retry, same withheld terminal; a different
    leaf, a different parse and a different lint. There is no second loop, and
    `listen_to_answer` is a named door onto this one.

    ``call(prompt, model) -> str`` is injected so this loop is testable and so
    a host can route the completion however it routes every other one. The
    contract:

    * at least one validated record -> ``STATUS_RECORDED``, carrying ALL of
      them (v214). "Recorded" has always meant *the answer is in the store*,
      and one valid record means it is;
    * nothing found, and nothing in the person's message says they answered ->
      ``STATUS_NOTHING`` — the correct outcome when they changed the subject;
    * nothing found while `landmarks_interaction.answer_must_record` says they
      DID answer -> ONE regeneration with the reminder appended, then, if it
      still comes back empty, ``STATUS_WITHHELD`` carrying the lint id. A
      withheld record is a thing a host can try again later; it is never a
      silent drop and never a fabricated record.
    * records found while `landmarks_interaction.records_missing_entries` says
      they stated MORE of them (v214) -> the SAME one regeneration, carrying
      `many_records_reminder`, and then ``STATUS_RECORDED`` regardless, with
      the larger of the two sets and the retryable lint id on it. This branch
      can never withhold: a partial record is worth more than none, and the
      person already said it once.
    * the provider being unavailable is ``STATUS_UNAVAILABLE`` — the person's
      turn is untouched either way, which is the point of separating the two
      jobs in the first place. Unavailable on the RETRY, with records already
      in hand, files those records rather than throwing them away.

    There is exactly ONE retry across both findings, and :data:`MAX_ATTEMPTS`
    is still 2: a second regeneration would be a loop, and the lints exist to
    make a failure legible, not to keep rolling the dice.

    **v229 adds a THIRD finding to that same single retry, never a fourth
    attempt.** `general_listener.claims_missing_subjects` reads the CLAIMS the
    same completion emitted and asks v214's question of them — *did they
    assert more facts than came back?* — and it is consulted only where the
    records themselves are complete, so the two never spend two regenerations
    between them. Like `records_missing_entries` it can never withhold. And in
    FOCUSED mode `answer_must_record` still reads the records and only the
    records: the focused recorder is the canonical writer for a focused turn
    (plan §2.1, §6.1), so a claim heard alongside upgrades the terminal from
    ``STATUS_NOTHING`` to ``STATUS_RECORDED`` but never excuses a missing
    record. In LISTENING mode a claim IS a thing heard and clears
    `listener_heard_nothing` exactly as a landmark record does — there the
    claim is the point, not a second copy of the domain's answer.

    In NO-FOCUS mode the contract reads the same with one substitution:
    `general_listener.listener_heard_nothing` replaces `answer_must_record`
    as the blocking backstop, and it asks a question only a no-focus pass can
    ask — *the deterministic prescreen
    (`general_listener.may_contain_datable`) saw time in this message and
    nothing came back*. One regeneration carrying
    `general_listener.listening_reminder`, then ``STATUS_WITHHELD`` with
    `general_listener.LISTENER_HEARD_NOTHING_LINT` on it, which a host sweep
    can run again. Never silence, and never a fabricated record.
    `records_missing_entries` does NOT run there: it is a per-DOMAIN
    completeness class and a no-focus pass has no domain to be complete for.

    ``known_labels`` is DERIVED, not hand-passed (v216, lifehug#230). Both
    lints take it and both were being run with an empty one, because the only
    thing that could fill it — the entries already in the store — reached this
    function as ``landmarks`` and went nowhere but the prompt. It is now
    `landmarks_interaction.known_entry_labels` over that same store, so the
    block the model reads and the lints that judge its answer name the same
    entries; the argument survives as the ``extra`` union for a host holding
    names from somewhere else.
    """
    listening = not str(domain or "").strip()
    known = () if listening else li.known_entry_labels(
        landmarks, domain, extra=known_labels, framework_root=framework_root)
    verdict = gl.may_contain_datable(answer) if listening else None
    prompts: list[str] = []
    reminder = ""
    finding: dict | None = None
    best: tuple[dict, ...] = ()
    people: tuple[dict, ...] = ()
    claims: tuple[dict, ...] = ()
    findings: tuple[str, ...] = ()
    for attempt in range(1, MAX_ATTEMPTS + 1):
        prompt = (
            gl.build_listener_prompt(answer=answer, reply=reply,
                                     landmarks=landmarks, reminder=reminder,
                                     framework_root=framework_root)
            if listening else
            build_recorder_prompt(
                domain=domain, question_asked=question_asked, answer=answer,
                reply=reply, landmarks=landmarks, reminder=reminder,
                framework_root=framework_root,
            )
        )
        prompts.append(prompt)
        try:
            raw = call(prompt, model)
        except Exception as exc:  # noqa: BLE001 — provider failures are data here
            if best or people or claims:
                return RecorderOutcome(status=STATUS_RECORDED, records=best,
                                       people=people, findings=findings,
                                       claims=claims,
                                       attempts=attempt, reason=str(exc),
                                       prompts=tuple(prompts))
            return RecorderOutcome(status=STATUS_UNAVAILABLE, attempts=attempt,
                                   findings=findings, reason=str(exc),
                                   prompts=tuple(prompts))
        if listening:
            # THE NO-FOCUS RUNG of the same loop (ADR 0029). Same attempts,
            # same single retry, same withheld terminal — a different leaf, a
            # different parse and a different lint, and nothing else.
            heard = gl.parse_listener_output(raw,
                                             framework_root=framework_root)
            findings = tuple(dict.fromkeys(findings + heard.findings))
            if len(heard) > len(best) + len(people) + len(claims):
                best, people, claims = (heard.landmarks, heard.people,
                                        heard.claims)
            finding = gl.listener_heard_nothing(
                answer, best, people, claims=claims, findings=findings,
                landmarks=landmarks, verdict=verdict,
                framework_root=framework_root)
            if finding is None:
                # v229: the plurality rung, read over the CLAIMS. Same
                # severity as `RECORD_EVERY_ENTRY_LINT` and the same single
                # regeneration: it can never withhold, because a partial set
                # of claims is worth more than none and the person already
                # said it once.
                missed = gl.claims_missing_subjects(answer, claims)
                if missed is None or attempt == MAX_ATTEMPTS:
                    return RecorderOutcome(
                        status=(STATUS_RECORDED if (best or people or claims)
                                else STATUS_NOTHING),
                        records=best, people=people, claims=claims,
                        findings=findings, attempts=attempt,
                        lint_ids=((gl.CLAIMS_MISSING_SUBJECTS_LINT,) if missed
                                  else ()),
                        reason=str((missed or {}).get("detail", "")),
                        prompts=tuple(prompts))
                reminder = gl.every_claim_reminder(len(claims),
                                                   missed.get("missed"))
                continue
            reminder = gl.listening_reminder(verdict)
            continue
        records = parse_recorder_output(raw, framework_root=framework_root)
        heard_claims, refusals = parse_recorder_claims(raw)
        findings = tuple(dict.fromkeys(findings + refusals))
        if len(records) > len(best):
            best = records
        if len(heard_claims) > len(claims):
            claims = heard_claims
        if best:
            missed = li.records_missing_entries(
                answer, best, reply=reply, domain=domain,
                known_labels=known, framework_root=framework_root,
            )
            lint_id = li.RECORD_EVERY_ENTRY_LINT
            regen = li.many_records_reminder(domain, len(best))
            if missed is None:
                # The RECORDS are complete; the CLAIMS may not be. One retry
                # across both findings still (MAX_ATTEMPTS is unchanged), and
                # this rung never withholds either.
                missed = gl.claims_missing_subjects(answer, claims,
                                                    known_labels=known)
                if missed is not None:
                    lint_id = gl.CLAIMS_MISSING_SUBJECTS_LINT
                    regen = gl.every_claim_reminder(len(claims),
                                                    missed.get("missed"))
            if missed is None or attempt == MAX_ATTEMPTS:
                return RecorderOutcome(
                    status=STATUS_RECORDED, records=best, claims=claims,
                    findings=findings, attempts=attempt,
                    lint_ids=((lint_id,) if missed else ()),
                    reason=str((missed or {}).get("detail", "")),
                    prompts=tuple(prompts),
                )
            reminder = regen
            continue
        finding = li.answer_must_record(
            answer, records, reply=reply, domain=domain,
            known_labels=known, framework_root=framework_root,
        )
        if finding is None:
            # THE FOCUSED GUARANTEE IS UNCHANGED. `answer_must_record` reads
            # the RECORDS and only the records: the focused recorder is the
            # canonical writer for a focused turn (plan §2.1, §6.1), and
            # letting a claim satisfy the domain's own answer would weaken
            # that backstop during the very transition it has to survive.
            # A claim heard alongside is still a thing heard, so it upgrades
            # the terminal from "nothing" to "recorded" and rides out on the
            # outcome — it just never excuses a missing record.
            return RecorderOutcome(
                status=(STATUS_RECORDED if claims else STATUS_NOTHING),
                claims=claims, findings=findings, attempts=attempt,
                prompts=tuple(prompts))
        reminder = li.recording_reminder(domain)
    return RecorderOutcome(
        status=STATUS_WITHHELD, attempts=MAX_ATTEMPTS,
        people=people, findings=findings, claims=claims,
        lint_ids=((gl.LISTENER_HEARD_NOTHING_LINT,) if listening
                  else (li.ANSWER_MUST_RECORD_LINT,)),
        reason=str((finding or {}).get("detail", "")),
        prompts=tuple(prompts),
    )


def listen_to_answer(*, answer: str, call, reply: str = "",
                     landmarks: object = (),
                     model: str = gl.DEFAULT_LISTENER_ROLE,
                     framework_root: str | Path | None = None
                     ) -> RecorderOutcome:
    """The GENERAL LISTENER (v218, ADR 0029) — the recorder with no domain.

    A named door onto :func:`record_answer` with ``domain=None``, never a
    second loop: the attempt count, the single retry and the withheld
    terminal are the same body, and this exists so a caller's intent is
    legible at the call site and so the listener's own default role
    (`general_listener.DEFAULT_LISTENER_ROLE`) applies without every host
    remembering to pass it.

    It listens to ONE user message — with the reply alongside only as echo
    evidence, exactly as the focused recorder uses it — and returns
    :attr:`RecorderOutcome.records` (landmark records of ANY domain) and
    :attr:`RecorderOutcome.people` (FAMILY person dates, owner-ruled). The
    focused mode's restriction to the asked domain is untouched and stays a
    property of that mode: an off-domain fact in a focused landmark session
    is still not that session's to record.
    """
    return record_answer(domain=None, answer=answer, call=call, reply=reply,
                         landmarks=landmarks, model=model,
                         framework_root=framework_root)


# --------------------------------------------------------------------------
# CLI — the stdin-JSON path every prompt builder in this package carries
# --------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    """`landmark_recorder.py --domain X [--dry-run] < payload.json`.

    Payload: ``{"domain"?, "answer", "reply"?, "question_asked"?,
    "landmarks"?, "known_labels"?}``. ``landmarks`` is the LANDMARKS store as
    `timeline.load_landmarks` returns it — a dict of domain to entries — and
    from v216 it is what fills the prompt's ALREADY-FILED block and the lints'
    ``known_labels`` alike; ``known_labels`` remains for names from elsewhere
    and is unioned in. ``--dry-run`` prints the composed prompt and calls
    nothing, which is how a host verifies its own REPLAY against this leaf
    without spending a completion.
    """
    import argparse  # noqa: PLC0415
    import sys  # noqa: PLC0415

    parser = argparse.ArgumentParser(description="Run the landmark recorder")
    parser.add_argument("--domain")
    parser.add_argument("--model", default=DEFAULT_RECORDER_ROLE)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except ValueError as exc:
        print(json.dumps({"error": f"unreadable payload: {exc}"}))
        return 1
    domain = args.domain or payload.get("domain") or ""
    if not domain.strip():
        # This CLI is the FOCUSED recorder's. The no-focus mode has its own
        # front door (`general_listener.py`), and defaulting into it on a
        # missing flag would hide a typo behind a different pass.
        print(json.dumps({"error": "a domain is required "
                                   "(the no-focus mode is general_listener.py)"}))
        return 1
    try:
        if args.dry_run:
            print(build_recorder_prompt(
                domain=domain,
                question_asked=payload.get("question_asked", ""),
                answer=payload.get("answer", ""),
                reply=payload.get("reply", ""),
                landmarks=payload.get("landmarks") or {},
            ))
            return 0
        from ai_provider import call_ai  # noqa: PLC0415

        outcome = record_answer(
            domain=domain, answer=payload.get("answer", ""),
            reply=payload.get("reply", ""),
            question_asked=payload.get("question_asked", ""),
            landmarks=payload.get("landmarks") or {},
            known_labels=payload.get("known_labels") or (),
            call=call_ai, model=args.model,
        )
    except (li.LandmarkInteractionError, LandmarkRecorderError) as exc:
        print(json.dumps({"error": str(exc)}))
        return 1
    print(json.dumps({
        "status": outcome.status,
        # v214: `records` is the answer; `record` stays as its first entry so
        # a v212 reader of this CLI keeps reading.
        "records": list(outcome.records),
        "record": outcome.record,
        # v229: the claim DRAFTS, unbound. Binding them means promoting a
        # vault source for the message, which is `file_claims`' write and not
        # this front door's.
        "claims": list(outcome.claims),
        "extractor_version": recorder_extractor_version(model=args.model),
        "invocations": li.landmark_invocations(outcome.records),
        "attempts": outcome.attempts,
        "lint_ids": list(outcome.lint_ids),
        "findings": list(outcome.findings),
        "reason": outcome.reason,
    }, indent=2, sort_keys=True))
    return 0 if outcome.status in (STATUS_RECORDED, STATUS_NOTHING) else 1


if __name__ == "__main__":
    raise SystemExit(main())
