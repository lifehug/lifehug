#!/usr/bin/env python3
"""The never-resend rule — one definition every sender calls (v368).

Owner ruling "Question queue" (2026-09-27): "A send must never repeat a
question that's already been sent or answered… That should never happen."
Refined the same day: "a question sent but not answered CAN be re-sent if the
queue was empty — it could go back to that one. But I feel like I already
answered them and then it was sent again. That's the problem."

So there are two named rules, both answered from the vault's OWN records:

* ``AN_ANSWERED_QUESTION_IS_NEVER_SENT_AGAIN`` — hard. A question is answered
  when its bank line is checked (``- [x]``) or an ``answers/<id>.md`` exists.
* ``A_SENT_QUESTION_WAITS_UNTIL_NOTHING_UNASKED_REMAINS`` — a question that
  went out and was not answered is not sent again while any other unanswered
  question has never been sent (an unsent queued item, or an unasked bank
  question). Only when none remain may an unanswered one be offered again,
  least-offered first and never the same one two days running when another
  exists. A question is sent when ``system/rotation.json`` counts a delivery
  of it, or the planned queue marks it ``sent``.

A host (the hosted platform) may know of sends or answers the vault has not
recorded yet — its own delivery ledger, a capture still filing. It passes
those as ``also_sent`` / ``also_answered``; they only ever ADD records, so a
host can make the rule stricter, never looser. ``ask.py`` selects with this
rule and ``send_verdict`` / the ``delivery-check`` verb let a host refuse a
send before delivery with the same function.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Iterable
from pathlib import Path

from lifehug_core import (
    ANSWERS_DIR,
    QUESTION_QUEUE_FILE,
    QUESTIONS_FILE,
    ROTATION_FILE,
    answer_id_from_filename,
    parse_questions,
    read_json,
)

AN_ANSWERED_QUESTION_IS_NEVER_SENT_AGAIN = "delivery_guard.AN_ANSWERED_QUESTION_IS_NEVER_SENT_AGAIN"
A_SENT_QUESTION_WAITS_UNTIL_NOTHING_UNASKED_REMAINS = (
    "delivery_guard.A_SENT_QUESTION_WAITS_UNTIL_NOTHING_UNASKED_REMAINS"
)
RULE_VERSION = "delivery-guard:1"

#: Exit code of the check CLI when a send is refused (0 = allowed).
REFUSED_EXIT = 3


def _ids(values: Iterable[object] | None) -> set[str]:
    out: set[str] = set()
    for value in values or ():
        for part in str(value).split(","):
            part = part.strip()
            if part:
                out.add(part)
    return out


def _delivery_count(rotation: dict, question_id: str) -> int:
    counts = rotation.get("delivery_counts")
    if not isinstance(counts, dict):
        return 0
    raw = counts.get(question_id, 0)
    if isinstance(raw, bool) or not isinstance(raw, (int, str)):
        return 0
    try:
        return max(0, int(raw))
    except ValueError:
        return 0


def answered_file_ids(answers_dir: Path | None = None) -> set[str]:
    """Question ids with an answer file on disk (absent dir = none)."""
    root = ANSWERS_DIR if answers_dir is None else answers_dir
    try:
        paths = list(Path(root).glob("*.md"))
    except OSError:
        return set()
    return {qid for qid in (answer_id_from_filename(path) for path in paths) if qid}


def delivery_records(
    questions: list[dict],
    *,
    rotation: dict | None = None,
    queue_data: dict | None = None,
    answers_dir: Path | None = None,
    also_sent: Iterable[object] | None = None,
    also_answered: Iterable[object] | None = None,
) -> dict:
    """What the vault (plus a host's additions) says was answered and sent.

    Returns ``{"answered": set, "sent": set, "counts": {qid: n}}``. Reads
    ``rotation.json`` / the planned queue / ``answers/`` when not supplied.
    """
    if rotation is None:
        rotation = read_json(ROTATION_FILE, default={}) or {}
    if queue_data is None:
        queue_data = read_json(QUESTION_QUEUE_FILE, default={}) or {}
    answered = {str(q["id"]) for q in questions if q.get("answered")}
    answered |= answered_file_ids(answers_dir)
    answered |= _ids(also_answered)
    counts = {str(q["id"]): _delivery_count(rotation, str(q["id"])) for q in questions}
    sent = {qid for qid, count in counts.items() if count > 0}
    queue = queue_data.get("queue") if isinstance(queue_data, dict) else None
    for item in queue if isinstance(queue, list) else ():
        if isinstance(item, dict) and item.get("status") == "sent" and item.get("question_id"):
            sent.add(str(item["question_id"]))
    sent |= _ids(also_sent)
    return {"answered": answered, "sent": sent, "counts": counts}


def unanswered(questions: list[dict], records: dict) -> list[dict]:
    return [q for q in questions if str(q["id"]) not in records["answered"]]


def never_sent(questions: list[dict], records: dict) -> list[dict]:
    """Unanswered questions that have never gone out — what must go first."""
    return [q for q in unanswered(questions, records) if str(q["id"]) not in records["sent"]]


def reoffer_pool(questions: list[dict], records: dict, *, last_question_id: object = None) -> list[dict]:
    """Sent-but-unanswered questions, eligible ONLY when ``never_sent`` is
    empty: least-offered first, yesterday's question last (kept when it is the
    only one). Bank order breaks ties."""
    pool = [q for q in unanswered(questions, records) if str(q["id"]) in records["sent"]]
    if not pool:
        return []
    alternatives = [q for q in pool if str(q["id"]) != str(last_question_id or "")]
    pool = alternatives or pool
    least = min(records["counts"].get(str(q["id"]), 0) for q in pool)
    return [q for q in pool if records["counts"].get(str(q["id"]), 0) == least]


def send_verdict(
    question_id: str,
    questions: list[dict],
    records: dict,
) -> dict:
    """May ``question_id`` be sent now? The one decision every sender asks."""
    qid = str(question_id or "").strip()
    known = {str(q["id"]) for q in questions}
    verdict = {
        "question_id": qid,
        "rule_version": RULE_VERSION,
        "answered": qid in records["answered"],
        "sent": qid in records["sent"],
        "delivery_count": int(records["counts"].get(qid, 0)),
    }
    if qid in records["answered"]:
        return {**verdict, "allowed": False, "rule": AN_ANSWERED_QUESTION_IS_NEVER_SENT_AGAIN,
                "reason": "already answered"}
    if qid not in known:
        return {**verdict, "allowed": False, "rule": None, "reason": "not in the question bank"}
    if qid in records["sent"]:
        waiting = never_sent(questions, records)
        if waiting:
            return {**verdict, "allowed": False,
                    "rule": A_SENT_QUESTION_WAITS_UNTIL_NOTHING_UNASKED_REMAINS,
                    "reason": f"already sent; {len(waiting)} unasked question(s) come first"}
        return {**verdict, "allowed": True,
                "rule": A_SENT_QUESTION_WAITS_UNTIL_NOTHING_UNASKED_REMAINS,
                "reason": "re-offer: nothing unasked remains"}
    return {**verdict, "allowed": True, "rule": None, "reason": "never sent"}


def check(
    question_id: str,
    *,
    also_sent: Iterable[object] | None = None,
    also_answered: Iterable[object] | None = None,
) -> dict:
    """``send_verdict`` against this vault's files, over the same eligible set
    ``ask.py`` selects from (retired timeline questions excluded)."""
    import ask  # noqa: PLC0415 — ask imports this module at top level

    questions = parse_questions(QUESTIONS_FILE.read_text(encoding="utf-8"))
    records = delivery_records(questions, also_sent=also_sent, also_answered=also_answered)
    return send_verdict(question_id, ask.eligible_questions(questions), records)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Is this question already sent or answered? (the never-resend rule)")
    parser.add_argument("question_id")
    parser.add_argument("--also-sent", action="append", default=[],
                        help="comma-separated ids a host knows were sent (adds to the vault's records)")
    parser.add_argument("--also-answered", action="append", default=[],
                        help="comma-separated ids a host knows were answered")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    verdict = check(args.question_id, also_sent=args.also_sent, also_answered=args.also_answered)
    if args.json:
        print(json.dumps(verdict, sort_keys=True))
    else:
        state = "allowed" if verdict["allowed"] else "REFUSED"
        print(f"{verdict['question_id']}: {state} — {verdict['reason']}")
    return 0 if verdict["allowed"] else REFUSED_EXIT


if __name__ == "__main__":
    sys.exit(main())
