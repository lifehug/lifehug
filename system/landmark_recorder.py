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

Pure except for the one injected ``call``: the prompt build, the parse, the
validation and the lints are all deterministic and separately testable, and a
host that runs its own model REPLAYs those four and never this module's loop.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import conversation_delivery
import landmarks_interaction as li
from lifehug_core import INTERACTIONS_DIR

RECORDER_PROMPT = "recorder.md"

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
    """

    status: str
    records: tuple[dict, ...] = ()
    attempts: int = 0
    lint_ids: tuple[str, ...] = ()
    reason: str = ""
    prompts: tuple[str, ...] = field(default=(), repr=False)

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
    * ``chain_complete`` — where the domain is a chain.
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
    if row.get("chain"):
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
    the question that was asked, what the person said, and what they were
    told back. That is the entire evidence a recording decision needs, and
    leaving the rest out is what makes the second call small.
    """
    row = li.domain_row(domain, framework_root=framework_root)
    rows = landmarks if isinstance(landmarks, (list, tuple)) else ()
    block = li.render_landmarks(rows) if rows else "(nothing yet)"
    filled = load_recorder_leaf(framework_root)
    # `.replace`, never `.format` — every leaf in this package substitutes the
    # same way, and these leaves carry literal JSON braces.
    for token, value in (
        ("{question_asked}", (question_asked or row["ask"]).strip()),
        ("{ladder}", " | ".join(row["ladder"])),
        ("{recordable_keys}", " | ".join(recordable_keys(row))),
        ("{none_allowed}", "yes" if li.domain_accepts_none(row) else "no"),
        ("{landmarks}", block),
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


def record_answer(*, domain: str, answer: str, call, reply: str = "",
                  question_asked: str = "", landmarks: object = (),
                  known_labels: object = (),
                  model: str = DEFAULT_RECORDER_ROLE,
                  framework_root: str | Path | None = None) -> RecorderOutcome:
    """Run the recorder over one answer: extract, lint, retry once, file.

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
    """
    prompts: list[str] = []
    reminder = ""
    finding: dict | None = None
    best: tuple[dict, ...] = ()
    for attempt in range(1, MAX_ATTEMPTS + 1):
        prompt = build_recorder_prompt(
            domain=domain, question_asked=question_asked, answer=answer,
            reply=reply, landmarks=landmarks, reminder=reminder,
            framework_root=framework_root,
        )
        prompts.append(prompt)
        try:
            raw = call(prompt, model)
        except Exception as exc:  # noqa: BLE001 — provider failures are data here
            if best:
                return RecorderOutcome(status=STATUS_RECORDED, records=best,
                                       attempts=attempt, reason=str(exc),
                                       prompts=tuple(prompts))
            return RecorderOutcome(status=STATUS_UNAVAILABLE, attempts=attempt,
                                   reason=str(exc), prompts=tuple(prompts))
        records = parse_recorder_output(raw, framework_root=framework_root)
        if len(records) > len(best):
            best = records
        if best:
            missed = li.records_missing_entries(
                answer, best, reply=reply, domain=domain,
                known_labels=known_labels, framework_root=framework_root,
            )
            if missed is None or attempt == MAX_ATTEMPTS:
                return RecorderOutcome(
                    status=STATUS_RECORDED, records=best, attempts=attempt,
                    lint_ids=((li.RECORD_EVERY_ENTRY_LINT,) if missed
                              else ()),
                    reason=str((missed or {}).get("detail", "")),
                    prompts=tuple(prompts),
                )
            reminder = li.many_records_reminder(domain, len(best))
            continue
        finding = li.answer_must_record(
            answer, records, reply=reply, domain=domain,
            known_labels=known_labels, framework_root=framework_root,
        )
        if finding is None:
            return RecorderOutcome(status=STATUS_NOTHING, attempts=attempt,
                                   prompts=tuple(prompts))
        reminder = li.recording_reminder(domain)
    return RecorderOutcome(
        status=STATUS_WITHHELD, attempts=MAX_ATTEMPTS,
        lint_ids=(li.ANSWER_MUST_RECORD_LINT,),
        reason=str((finding or {}).get("detail", "")),
        prompts=tuple(prompts),
    )


# --------------------------------------------------------------------------
# CLI — the stdin-JSON path every prompt builder in this package carries
# --------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    """`landmark_recorder.py --domain X [--dry-run] < payload.json`.

    Payload: ``{"domain"?, "answer", "reply"?, "question_asked"?,
    "landmarks"?, "known_labels"?}``. ``--dry-run`` prints the composed
    prompt and calls nothing, which is how a host verifies its own REPLAY
    against this leaf without spending a completion.
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
    try:
        if args.dry_run:
            print(build_recorder_prompt(
                domain=domain,
                question_asked=payload.get("question_asked", ""),
                answer=payload.get("answer", ""),
                reply=payload.get("reply", ""),
                landmarks=payload.get("landmarks") or (),
            ))
            return 0
        from ai_provider import call_ai  # noqa: PLC0415

        outcome = record_answer(
            domain=domain, answer=payload.get("answer", ""),
            reply=payload.get("reply", ""),
            question_asked=payload.get("question_asked", ""),
            landmarks=payload.get("landmarks") or (),
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
        "invocations": li.landmark_invocations(outcome.records),
        "attempts": outcome.attempts,
        "lint_ids": list(outcome.lint_ids),
        "reason": outcome.reason,
    }, indent=2, sort_keys=True))
    return 0 if outcome.status in (STATUS_RECORDED, STATUS_NOTHING) else 1


if __name__ == "__main__":
    raise SystemExit(main())
