#!/usr/bin/env python3
"""The one door into the question bank (ADR 0042).

``append_questions`` is the ONLY function in ``system/`` that builds a
``- [ ] {id}: {text}`` bank line. Every writer — follow-ups
(`process_answer.append_followups`, `gen_followups --append`), keystone probes
(`timeline_interaction.insert_keystone_question`) and candidate promotion
(`candidate_promotion.apply_candidate_promotion`,
`question_candidates.insert_question`) — goes through it, and it runs
`question_craft.evaluate` on every row:

* ``fail``   -> REFUSED: returned with its reasons, never written;
* ``review`` -> written, with a ``<!-- craft: review: … -->`` comment;
* ``pass``   -> written.

A guard test (`tests/test_question_bank.py`) fails if any other module builds
an open bank line.

The bank grammar gains one state: ``- [-] {id}: {text} *(retired DATE:
reason)*``. A retired row keeps its id and its history and is never deleted;
it is neither open nor answered (`lifehug_core.QUESTION_LINE_RE` reads only
``[ ]``/``[x]``), so selection, planning, coverage and rotation never see it.
Ids are still allocated past it (`next_bank_id`), so an id is never reused.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date

from question_craft import FAIL, REVIEW, evaluate

QUESTION_ID_PATTERN = r"[A-Z]\d+[a-z]*"
#: Every bank row in any state — open ``[ ]``, answered ``[x]``, retired ``[-]``.
ANY_BANK_LINE_RE = re.compile(
    rf"^- \[(?P<box>[ xX-])\] (?P<qid>{QUESTION_ID_PATTERN}): (?P<text>.+?)"
    r"(?:\s+\*\((?P<note>.+)\)\*)?\s*$",
    re.MULTILINE,
)
RETIRED_BOX = "-"
CRAFT_REVIEW_MARKER = "craft: review:"


def bank_rows(bank_text: str) -> list[dict]:
    """Every row with its state: ``open`` / ``answered`` / ``retired``."""
    rows = []
    for match in ANY_BANK_LINE_RE.finditer(bank_text or ""):
        box = match.group("box")
        status = ("retired" if box == RETIRED_BOX
                  else "answered" if box.lower() == "x" else "open")
        rows.append({
            "id": match.group("qid"),
            "category": match.group("qid")[0],
            "text": match.group("text").strip(),
            "status": status,
            "note": (match.group("note") or "").strip(),
        })
    return rows


def all_bank_ids(bank_text: str) -> list[str]:
    """Every id the bank has ever issued, retired rows included."""
    return [row["id"] for row in bank_rows(bank_text)]


def next_bank_id(bank_text: str, category: str) -> str:
    """The next base id in ``category`` — past every row, retired included."""
    category = str(category).upper()
    numbers = []
    for qid in all_bank_ids(bank_text):
        match = re.match(rf"^{re.escape(category)}(\d+)", qid)
        if match:
            numbers.append(int(match.group(1)))
    return f"{category}{max(numbers, default=0) + 1}"


def next_followup_id(bank_text: str, source_id: str) -> str:
    """The next follow-up id under ``source_id`` (``A14`` -> ``A14a`` …)."""
    suffixes = [qid[len(source_id):] for qid in all_bank_ids(bank_text)
                if re.fullmatch(rf"{re.escape(source_id)}[a-z]+", qid)]
    single_letters = [s for s in suffixes if len(s) == 1 and "a" <= s <= "z"]
    if not single_letters:
        return f"{source_id}a"
    next_ord = ord(max(single_letters)) + 1
    if next_ord > ord("z"):
        raise ValueError(f"too many follow-ups for {source_id}")
    return f"{source_id}{chr(next_ord)}"


def format_row(question_id: str, text: str, provenance: str | None = None) -> str:
    """The text of one open bank row (+ its provenance line) — pure, and the
    only place the ``- [ ] `` grammar is spelled. A caller that wants a row
    PREVIEW (`timeline_interaction.mint_keystone_question`'s ``line``) uses
    this; only :func:`append_questions` ever puts one in the bank."""
    block = f"- [ ] {question_id}: {text}"
    return block + ("\n" + provenance if provenance else "")


def _insert_block(bank_text: str, category: str, block: str, new_section: str | None) -> str:
    pattern = re.compile(
        rf"^(## {re.escape(category)}:.+?)(?=\n## |\Z)", re.MULTILINE | re.DOTALL)
    match = pattern.search(bank_text)
    if not match:
        if new_section is None:
            raise ValueError(f"category section not found: {category}")
        return bank_text.rstrip() + new_section + block + "\n"
    section = match.group(1).rstrip()
    return bank_text[:match.start()] + section + "\n" + block + "\n" + bank_text[match.end():]


def craft_review_comment(reasons: list[str]) -> str:
    return f"  <!-- {CRAFT_REVIEW_MARKER} {'; '.join(reasons)} -->"


def append_questions(bank_text: str, rows: list[dict], *,
                     context: dict | None = None) -> tuple[str, list[dict], list[dict]]:
    """File ``rows`` into the bank text — THE door. Pure.

    Each row: ``text`` (required); ``id`` (or allocated by ``next_bank_id``);
    ``category`` (default: the id's letter); ``provenance`` — the comment
    line(s) written on the line after the row, exactly as given;
    ``new_section`` — the text appended when the category has no section yet
    (``None`` raises ``ValueError``, the old behaviour of the strict writers).

    Returns ``(new_text, filed, refused)``. A refused row never touches the
    text; the next row is evaluated against the bank AS FILED so far, so two
    near-identical rows in one call land as one pass and one review.
    """
    text = bank_text or ""
    shared = dict(context) if isinstance(context, dict) else {}
    filed: list[dict] = []
    refused: list[dict] = []
    for row in rows or ():
        if not isinstance(row, dict):
            continue
        body = str(row.get("text") or "").strip()
        qid = str(row.get("id") or "").strip()
        category = str(row.get("category") or (qid[:1] if qid else "")).upper()
        record = {"id": qid, "text": body, "category": category}
        if "\n" in body:
            refused.append({**record, "verdict": FAIL, "reasons": ["multiline"]})
            continue
        ctx = {**shared, **(row.get("context") or {})}
        ctx["bank"] = [(r["id"], r["text"]) for r in bank_rows(text)]
        verdict = evaluate(body, context=ctx, with_score=False)
        if verdict["verdict"] == FAIL:
            refused.append({**record, "verdict": FAIL, "reasons": verdict["reasons"]})
            continue
        if not category:
            raise ValueError("a bank row needs an id or a category")
        if not qid:
            qid = next_bank_id(text, category)
            record["id"] = qid
        block = format_row(qid, body, str(row.get("provenance") or ""))
        if verdict["verdict"] == REVIEW:
            block += "\n" + craft_review_comment(verdict["reasons"])
        text = _insert_block(text, category, block, row.get("new_section"))
        filed.append({**record, "verdict": verdict["verdict"], "reasons": verdict["reasons"]})
    return text, filed, refused


def craft_review_index(bank_text: str) -> dict[str, list[str]]:
    """``{bank_id: [reasons]}`` for rows filed with a craft-review comment."""
    index: dict[str, list[str]] = {}
    lines = (bank_text or "").splitlines()
    current = None
    for line in lines:
        match = ANY_BANK_LINE_RE.match(line)
        if match:
            current = match.group("qid")
            continue
        stripped = line.strip()
        if current and stripped.startswith("<!--"):
            if CRAFT_REVIEW_MARKER in stripped:
                body = stripped.split(CRAFT_REVIEW_MARKER, 1)[1].rsplit("-->", 1)[0]
                index[current] = [r.strip() for r in body.split(";") if r.strip()]
            continue
        current = None
    return index


def _safe_note(value: str) -> str:
    return " ".join(str(value or "").replace(")*", ")").replace("*(", "(").split())


def retire_question(bank_text: str, question_id: str, *, reason: str | None = None,
                    retired_on: str | None = None) -> tuple[str, dict]:
    """Rewrite one row to ``- [-] {id}: {text} *(retired DATE: reason)*``. Pure.

    Never deletes: the id, the text, and an answered row's own date survive
    on the line. Raises ``ValueError`` for an unknown or already-retired id.
    """
    qid = question_id.strip()
    pattern = re.compile(
        rf"^- \[(?P<box>[ xX-])\] (?P<qid>{re.escape(qid)}): (?P<text>.+?)"
        r"(?:\s+\*\((?P<note>.+)\)\*)?\s*$",
        re.MULTILINE,
    )
    match = pattern.search(bank_text or "")
    if not match:
        raise ValueError(f"question not found in the bank: {qid}")
    if match.group("box") == RETIRED_BOX:
        raise ValueError(f"question already retired: {qid}")
    stamp = retired_on or date.today().isoformat()
    body = match.group("text").strip()
    why = _safe_note(reason or "")
    if not why:
        verdict = evaluate(body, with_score=False)
        why = ", ".join(verdict["reasons"]) if verdict["verdict"] == FAIL else "retired by request"
    note = f"retired {stamp}: {why}"
    if match.group("box").lower() == "x" and match.group("note"):
        note += f"; answered {_safe_note(match.group('note'))}"
    line = f"- [-] {qid}: {body} *({note})*"
    new_text = bank_text[:match.start()] + line + bank_text[match.end():]
    return new_text, {"id": qid, "text": body, "was": "answered" if match.group("box").lower() == "x"
                      else "open", "note": note}


def lint_bank(bank_text: str) -> list[dict]:
    """Every row with its verdict and reasons — read-only."""
    rows = bank_rows(bank_text)
    pairs = [(r["id"], r["text"]) for r in rows]
    out = []
    for row in rows:
        verdict = evaluate(row["text"], context={"bank": pairs, "self_id": row["id"]},
                           with_score=False)
        out.append({"id": row["id"], "status": row["status"], "text": row["text"],
                    "verdict": verdict["verdict"], "reasons": verdict["reasons"]})
    return out


def _format_table(entries: list[dict]) -> str:
    lines = [f"{'ID':<8} {'STATUS':<9} {'VERDICT':<7} REASONS / TEXT"]
    for entry in entries:
        reasons = ", ".join(entry["reasons"]) or "-"
        lines.append(f"{entry['id']:<8} {entry['status']:<9} {entry['verdict']:<7} "
                     f"{reasons} | {entry['text']}")
    counts = {v: sum(1 for e in entries if e["verdict"] == v) for v in ("pass", "review", "fail")}
    lines.append(f"\n{len(entries)} entries: {counts['pass']} pass, {counts['review']} review, "
                 f"{counts['fail']} fail")
    return "\n".join(lines)


def cmd_lint(args: argparse.Namespace) -> int:
    from lifehug_core import QUESTIONS_FILE  # noqa: PLC0415

    entries = lint_bank(QUESTIONS_FILE.read_text(encoding="utf-8"))
    if args.verdict:
        entries = [e for e in entries if e["verdict"] == args.verdict]
    if args.json:
        print(json.dumps({"entries": entries}, indent=2, ensure_ascii=False))
    else:
        print(_format_table(entries))
    return 0


def cmd_retire(args: argparse.Namespace) -> int:
    from lifehug_core import QUESTIONS_FILE, write_text  # noqa: PLC0415

    text = QUESTIONS_FILE.read_text(encoding="utf-8")
    try:
        new_text, receipt = retire_question(text, args.question_id, reason=args.reason)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    write_text(QUESTIONS_FILE, new_text)
    if args.json:
        print(json.dumps(receipt, indent=2, ensure_ascii=False))
    else:
        print(f"Retired {receipt['id']} ({receipt['was']}): {receipt['note']}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="The question bank's one door (ADR 0042)")
    sub = parser.add_subparsers(dest="command", required=True)
    lint = sub.add_parser("lint", help="Print every bank entry with its verdict (read-only)")
    lint.add_argument("--json", action="store_true")
    lint.add_argument("--verdict", choices=["pass", "review", "fail"],
                      help="Only print entries with this verdict")
    lint.set_defaults(func=cmd_lint)
    retire = sub.add_parser("retire", help="Retire one bank entry (never deletes)")
    retire.add_argument("question_id")
    retire.add_argument("--reason")
    retire.add_argument("--json", action="store_true")
    retire.set_defaults(func=cmd_retire)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
