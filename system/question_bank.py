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

v422 (ADR 0045, owner 2026-10-15) gives the owner two more verbs on an OPEN
row, beside retire:

* KEEP — ``THE_OWNERS_KEEP_IS_ON_THE_ROW``: ``keep_question`` writes
  ``  <!-- craft: kept DATE: reason -->`` on the line after the row (where a
  ``craft: review:`` comment goes, and it replaces one: the owner has
  looked). A kept row is the owner's pass
  (`question_craft.A_KEPT_QUESTION_IS_THE_OWNERS_PASS`): ``lint_bank`` and the
  planner pass ``kept`` into ``evaluate``, so a kept row is never held back,
  and the hosted send-time gate must pass it too.
* REWRITE — ``A_REWRITE_IS_THE_SAME_QUESTION_RESAID``: ``rewrite_question``
  re-says the row in place — same id, same position, same box — after
  evaluating the new text against the bank. A FAIL is refused
  (``CraftRefused``, nothing written); a REVIEW is written with a fresh
  review comment; a PASS is written clean. Any prior review or kept comment
  is dropped (a rewrite stands on its own) and
  ``  <!-- craft: rewritten DATE: was "old text" -->`` records what it said.
  A promoted row's ``lifehug:candidate-promotion:v1`` marker is re-stamped
  for the new text (`candidate_promotion.restamp_marker_question`) so the
  promotion ledger still verifies.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date

from question_craft import A_KEPT_QUESTION_IS_THE_OWNERS_PASS as A_KEPT_QUESTION_IS_THE_OWNERS_PASS_CRAFT
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
CRAFT_KEPT_MARKER = "craft: kept"
CRAFT_REWRITTEN_MARKER = "craft: rewritten"

#: v422 rule names (ADR 0045) — see the module docstring. The craft side of
#: the keep is `question_craft.A_KEPT_QUESTION_IS_THE_OWNERS_PASS`.
THE_OWNERS_KEEP_IS_ON_THE_ROW = "the_owners_keep_is_on_the_row"
A_REWRITE_IS_THE_SAME_QUESTION_RESAID = "a_rewrite_is_the_same_question_resaid"
A_KEPT_QUESTION_IS_THE_OWNERS_PASS = A_KEPT_QUESTION_IS_THE_OWNERS_PASS_CRAFT
DEFAULT_KEEP_REASON = "kept by the owner"


class CraftRefused(ValueError):
    """A rewrite whose new text is a craft FAIL — nothing was written."""

    def __init__(self, question_id: str, reasons: list[str]):
        self.question_id = question_id
        self.reasons = list(reasons)
        super().__init__(f"rewrite of {question_id} refused: {', '.join(self.reasons)}")


def bank_rows(bank_text: str) -> list[dict]:
    """Every row with its state: ``open`` / ``answered`` / ``retired``."""
    rows = []
    kept = craft_kept_index(bank_text)
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
            "kept": match.group("qid") in kept,
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


def _row_comments(bank_text: str, marker: str) -> dict[str, str]:
    """``{bank_id: body}`` — the text after ``marker`` in the comment lines
    that follow a row (the one comment walk every craft index reads)."""
    index: dict[str, str] = {}
    current = None
    for line in (bank_text or "").splitlines():
        match = ANY_BANK_LINE_RE.match(line)
        if match:
            current = match.group("qid")
            continue
        stripped = line.strip()
        if current and stripped.startswith("<!--"):
            if marker in stripped:
                index[current] = stripped.split(marker, 1)[1].rsplit("-->", 1)[0].strip()
            continue
        current = None
    return index


def craft_review_index(bank_text: str) -> dict[str, list[str]]:
    """``{bank_id: [reasons]}`` for rows filed with a craft-review comment."""
    return {qid: [r.strip() for r in body.split(";") if r.strip()]
            for qid, body in _row_comments(bank_text, CRAFT_REVIEW_MARKER).items()}


def craft_kept_index(bank_text: str) -> dict[str, dict[str, str]]:
    """``{bank_id: {"date", "reason"}}`` for rows the owner kept
    (THE_OWNERS_KEEP_IS_ON_THE_ROW)."""
    index: dict[str, dict[str, str]] = {}
    for qid, body in _row_comments(bank_text, CRAFT_KEPT_MARKER).items():
        stamp, _, reason = body.partition(":")
        index[qid] = {"date": stamp.strip(), "reason": reason.strip()}
    return index


def craft_kept_comment(kept_on: str, reason: str) -> str:
    return f"  <!-- {CRAFT_KEPT_MARKER} {kept_on}: {_safe_comment(reason)} -->"


def craft_rewritten_comment(rewritten_on: str, old_text: str, reason: str | None = None) -> str:
    was = _safe_comment(old_text).replace('"', "'")
    why = _safe_comment(reason or "")
    return (f'  <!-- {CRAFT_REWRITTEN_MARKER} {rewritten_on}: was "{was}"'
            + (f"; {why}" if why else "") + " -->")


def _safe_comment(value: str) -> str:
    """One line that cannot close the HTML comment it sits in."""
    return " ".join(str(value or "").replace("-->", "-- >").split())


def _open_row_span(bank_text: str, question_id: str) -> tuple[list[str], int, int, re.Match]:
    """``(lines, row_index, end, match)`` for one OPEN row: ``lines`` keep
    their endings; ``lines[row_index + 1:end]`` are the row's comment lines.
    ValueError for an unknown, answered or retired id."""
    qid = str(question_id or "").strip()
    lines = (bank_text or "").splitlines(keepends=True)
    for index, line in enumerate(lines):
        match = ANY_BANK_LINE_RE.match(line.rstrip("\r\n"))
        if not match or match.group("qid") != qid:
            continue
        box = match.group("box")
        if box == RETIRED_BOX:
            raise ValueError(f"question is retired: {qid}")
        if box.lower() == "x":
            raise ValueError(f"question is already answered: {qid}")
        end = index + 1
        while end < len(lines) and lines[end].strip().startswith("<!--"):
            end += 1
        return lines, index, end, match
    raise ValueError(f"question not found in the bank: {qid}")


def _without_markers(comment_lines: list[str], *markers: str) -> tuple[list[str], list[str]]:
    """Bare comment lines split into (kept, dropped-for-a-marker)."""
    kept, dropped = [], []
    for line in comment_lines:
        bare = line.rstrip("\r\n")
        (dropped if any(m in bare for m in markers) else kept).append(bare)
    return kept, dropped


def _splice(bank_text: str, lines: list[str], index: int, end: int, block: list[str]) -> str:
    """Replace ``lines[index:end]`` with ``block`` (bare lines), keeping the
    row's own line ending and whether the text ended with one."""
    row = lines[index]
    newline = row[len(row.rstrip("\r\n")):] or "\n"
    spliced = "".join(line + newline for line in block)
    new_text = "".join(lines[:index]) + spliced + "".join(lines[end:])
    if end == len(lines) and not (bank_text or "").endswith(("\n", "\r")):
        new_text = new_text[:-len(newline)]
    return new_text


def _restamp_promotion(line: str, question_id: str, text: str) -> str:
    """A promoted row's marker pins the question's bytes; a rewrite re-stamps it
    (`candidate_promotion.restamp_marker_question`) so promotion still reads
    the bank. Any other comment line is returned unchanged."""
    if "lifehug:candidate-promotion:v1" not in line:
        return line
    import candidate_promotion  # noqa: PLC0415 - it imports this module

    return candidate_promotion.restamp_marker_question(line, question_id, text)


def keep_question(bank_text: str, question_id: str, *, reason: str | None = None,
                  kept_on: str | None = None) -> tuple[str, dict]:
    """THE_OWNERS_KEEP_IS_ON_THE_ROW: write ``  <!-- craft: kept DATE: reason -->``
    under one OPEN row. Pure.

    Re-keeping replaces the earlier kept comment (the reason is updated); a
    ``craft: review:`` comment on the row is dropped (the owner has looked).
    The row itself is untouched. ValueError for unknown, answered or retired.
    """
    lines, index, end, match = _open_row_span(bank_text, question_id)
    qid = match.group("qid")
    stamp = kept_on or date.today().isoformat()
    why = _safe_comment(reason or "") or DEFAULT_KEEP_REASON
    previous = craft_kept_index("".join(lines[index:end])).get(qid)
    comments, dropped = _without_markers(lines[index + 1:end], CRAFT_KEPT_MARKER,
                                         CRAFT_REVIEW_MARKER)
    new_text = _splice(bank_text, lines, index, end,
                       [lines[index].rstrip("\r\n"), *comments, craft_kept_comment(stamp, why)])
    verdict = evaluate(match.group("text").strip(), with_score=False,
                       context={"bank": [(r["id"], r["text"]) for r in bank_rows(bank_text)],
                                "self_id": qid, "kept": True})
    return new_text, {
        "id": qid, "text": match.group("text").strip(), "kept_on": stamp, "reason": why,
        "rekept": previous is not None,
        "dropped_review": bool([d for d in dropped if CRAFT_REVIEW_MARKER in d]),
        "overridden": verdict.get("overridden", []),
    }


def rewrite_question(bank_text: str, question_id: str, text: str, *,
                     reason: str | None = None,
                     rewritten_on: str | None = None) -> tuple[str, dict]:
    """A_REWRITE_IS_THE_SAME_QUESTION_RESAID: re-say one OPEN row in place. Pure.

    Same id, same position, same box; only the text segment of the line
    changes. The new text is evaluated against the bank (``self_id`` = the
    row): a FAIL raises ``CraftRefused`` (``.reasons``) and nothing is
    written; a REVIEW is written with a fresh ``craft: review:`` comment; a
    PASS is written clean. Prior review and kept comments are dropped, and
    ``  <!-- craft: rewritten DATE: was "…" -->`` records the old text.
    """
    lines, index, end, match = _open_row_span(bank_text, question_id)
    qid = match.group("qid")
    body = str(text or "").strip()
    if "\n" in body or "\r" in body:
        raise CraftRefused(qid, ["multiline"])
    old = match.group("text").strip()
    if not body:
        raise ValueError(f"a rewrite needs text: {qid}")
    if body == old:
        raise ValueError(f"the rewrite is the same text: {qid}")
    pairs = [(r["id"], r["text"]) for r in bank_rows(bank_text)]
    verdict = evaluate(body, context={"bank": pairs, "self_id": qid}, with_score=False)
    if verdict["verdict"] == FAIL:
        raise CraftRefused(qid, verdict["reasons"])
    stamp = rewritten_on or date.today().isoformat()
    bare = lines[index].rstrip("\r\n")
    row = bare[:match.start("text")] + body + bare[match.end("text"):]
    comments, dropped = _without_markers(lines[index + 1:end], CRAFT_KEPT_MARKER,
                                         CRAFT_REVIEW_MARKER)
    comments = [_restamp_promotion(line, qid, body) for line in comments]
    block = [row, *comments, craft_rewritten_comment(stamp, old, reason)]
    if verdict["verdict"] == REVIEW:
        block.append(craft_review_comment(verdict["reasons"]))
    new_text = _splice(bank_text, lines, index, end, block)
    return new_text, {
        "id": qid, "was": old, "text": body, "rewritten_on": stamp,
        "verdict": verdict["verdict"], "reasons": verdict["reasons"],
        "dropped": [d.strip() for d in dropped],
    }


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
    """Every row with its verdict and reasons — read-only.

    A kept row is evaluated with ``kept`` (THE_OWNERS_KEEP_IS_ON_THE_ROW): its
    verdict is the owner's pass and ``overridden`` lists what the rules said.
    """
    rows = bank_rows(bank_text)
    pairs = [(r["id"], r["text"]) for r in rows]
    out = []
    for row in rows:
        context = {"bank": pairs, "self_id": row["id"]}
        if row["kept"]:
            context["kept"] = True
        verdict = evaluate(row["text"], context=context, with_score=False)
        out.append({"id": row["id"], "status": row["status"], "text": row["text"],
                    "verdict": verdict["verdict"], "reasons": verdict["reasons"],
                    "kept": row["kept"], "overridden": verdict.get("overridden", [])})
    return out


def _format_table(entries: list[dict]) -> str:
    lines = [f"{'ID':<8} {'STATUS':<9} {'VERDICT':<7} {'KEPT':<4} REASONS / TEXT"]
    for entry in entries:
        reasons = ", ".join(entry["reasons"]) or "-"
        if entry.get("kept") and entry.get("overridden"):
            reasons = "overridden: " + ", ".join(entry["overridden"])
        kept = "kept" if entry.get("kept") else "-"
        lines.append(f"{entry['id']:<8} {entry['status']:<9} {entry['verdict']:<7} {kept:<4} "
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


def cmd_keep(args: argparse.Namespace) -> int:
    from lifehug_core import QUESTIONS_FILE, write_text  # noqa: PLC0415

    text = QUESTIONS_FILE.read_text(encoding="utf-8")
    try:
        new_text, receipt = keep_question(text, args.question_id, reason=args.reason)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    write_text(QUESTIONS_FILE, new_text)
    if args.json:
        print(json.dumps(receipt, indent=2, ensure_ascii=False))
    else:
        overridden = ", ".join(receipt["overridden"]) or "nothing"
        print(f"Kept {receipt['id']} ({receipt['kept_on']}: {receipt['reason']}); "
              f"overrides {overridden}")
    return 0


def cmd_rewrite(args: argparse.Namespace) -> int:
    from lifehug_core import QUESTIONS_FILE, write_text  # noqa: PLC0415

    text = QUESTIONS_FILE.read_text(encoding="utf-8")
    try:
        new_text, receipt = rewrite_question(text, args.question_id, args.text,
                                             reason=args.reason)
    except CraftRefused as exc:
        if args.json:
            print(json.dumps({"refused": True, "id": exc.question_id, "reasons": exc.reasons},
                             indent=2, ensure_ascii=False))
        else:
            print(f"Refused: the rewrite of {exc.question_id} is not a question "
                  f"({', '.join(exc.reasons)}); nothing written", file=sys.stderr)
        return 1
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    write_text(QUESTIONS_FILE, new_text)
    if args.json:
        print(json.dumps({"refused": False, **receipt}, indent=2, ensure_ascii=False))
    else:
        tail = f" ({', '.join(receipt['reasons'])})" if receipt["reasons"] else ""
        print(f"Rewrote {receipt['id']} [{receipt['verdict']}{tail}]: {receipt['text']}")
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
    keep = sub.add_parser("keep", help="Keep one open bank entry: the owner's pass beats the "
                                       "craft rules everywhere (ADR 0045)")
    keep.add_argument("question_id")
    keep.add_argument("--reason", help=f"Why (default: {DEFAULT_KEEP_REASON!r})")
    keep.add_argument("--json", action="store_true")
    keep.set_defaults(func=cmd_keep)
    rewrite = sub.add_parser("rewrite", help="Re-say one open bank entry in place: same id, "
                                             "re-evaluated; a FAIL is refused (ADR 0045)")
    rewrite.add_argument("question_id")
    rewrite.add_argument("--text", required=True, help="The new question text")
    rewrite.add_argument("--reason", help="Why (recorded on the rewritten comment)")
    rewrite.add_argument("--json", action="store_true")
    rewrite.set_defaults(func=cmd_rewrite)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
