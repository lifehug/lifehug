#!/usr/bin/env python3
"""Lifehug — Answer Acknowledgment: warm reply prompt after an answer is saved.

Builds the AI prompt for the warm acknowledgment message sent right after a
daily answer is filed (see CLAUDE.md "Processing an Answer" / AGENTS.md's
"Acknowledge warmly" step). This is the behavioral authority for the
acknowledgment tone contract — the local Claude skill and the hosted Lifehug
platform both build the message this way, so it stays consistent whichever
surface answered.

It does NOT call the AI itself — it prints a prompt; the calling model (or
platform) completes it into the actual message.

Usage:
    echo '{"question_id": "A3", "question_text": "...", "question_category": "A",
           "answer_text": "...", "followup_pending": true}' \
        | python3 system/answer_ack.py

Reads a single JSON object on stdin with:
    question_id       str  — the question's ID, e.g. "A3"
    question_text     str  — the question as asked
    question_category str  — the category letter, e.g. "A"
    answer_text       str  — the author's answer, verbatim
    followup_pending  bool — whether a same-day follow-up question will follow

Prints the built prompt to stdout, nothing else. On empty stdin, invalid
JSON, or a missing/mis-typed required field, prints a one-line error to
stderr and exits 1.
"""

from __future__ import annotations

import argparse
import json
import sys

REQUIRED_FIELDS = {
    "question_id": str,
    "question_text": str,
    "question_category": str,
    "answer_text": str,
    "followup_pending": bool,
}


def build_prompt(payload: dict) -> str:
    """Assemble the acknowledgment prompt from a validated payload."""
    question_id = payload["question_id"]
    question_text = payload["question_text"]
    question_category = payload["question_category"]
    answer_text = payload["answer_text"]
    followup_pending = payload["followup_pending"]

    lines = []
    lines.append("=" * 70)
    lines.append("LIFEHUG — ANSWER ACKNOWLEDGMENT")
    lines.append("=" * 70)
    lines.append("")
    lines.append(f"Question: [{question_id}] (category {question_category})")
    lines.append("")
    lines.append("-" * 70)
    lines.append("YOUR TASK")
    lines.append("-" * 70)
    lines.append("")
    lines.append("The author just answered today's Lifehug question. Write the warm")
    lines.append("acknowledgment message that goes back to them immediately, before")
    lines.append("anything else follows.")
    lines.append("")
    lines.append("You are warm but not sycophantic. You're genuinely curious about")
    lines.append("this person's life, and you show it by noticing what they actually")
    lines.append("said — not with a generic compliment.")
    lines.append("")
    lines.append("Tone contract:")
    lines.append("  1. Thank the author warmly. 2-4 sentences total.")
    lines.append("  2. Reflect ONE concrete detail from their answer back at them —")
    lines.append("     a name, a place, an image, a feeling they named. Show you")
    lines.append("     actually listened. Not a generic compliment ('what a great")
    lines.append("     story') — something that could only be said about THIS answer.")
    lines.append("  3. No advice. No analysis. No questions back.")
    if followup_pending:
        lines.append("  4. End with one light sentence noting another question is")
        lines.append("     coming while you're here, and that it's totally optional.")
    else:
        lines.append("  4. Do not mention a follow-up question — none is coming today.")
    lines.append("")
    lines.append("-" * 70)
    lines.append("THE QUESTION")
    lines.append("-" * 70)
    lines.append("")
    lines.append(question_text)
    lines.append("")
    lines.append("-" * 70)
    lines.append("THE ANSWER")
    lines.append("-" * 70)
    lines.append("")
    lines.append(answer_text)
    lines.append("")
    lines.append("=" * 70)
    lines.append("END OF CONTEXT")
    lines.append("=" * 70)
    lines.append("")
    lines.append("Output ONLY the acknowledgment message text. No explanation, no")
    lines.append("preamble, no quotes, no markdown fences. Just the message.")

    return "\n".join(lines)


def _validate(payload) -> str | None:
    """Return an error string if payload is invalid, else None."""
    if not isinstance(payload, dict):
        return "payload must be a JSON object"
    for field, expected_type in REQUIRED_FIELDS.items():
        if field not in payload:
            return f"missing required field: {field}"
        value = payload[field]
        if expected_type is bool:
            # bool is a subclass of int in Python — guard against ints/strings
            # silently passing as booleans.
            if not isinstance(value, bool):
                return f"field {field!r} must be a boolean"
        elif not isinstance(value, expected_type):
            return f"field {field!r} must be a string"
    return None


def main() -> None:
    argparse.ArgumentParser(
        description="Print the warm answer-acknowledgment prompt (stdin: question/answer JSON)"
    ).parse_args()

    raw = sys.stdin.read()
    if not raw.strip():
        print("Error: empty stdin — expected a JSON payload", file=sys.stderr)
        sys.exit(1)

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        print(f"Error: invalid JSON on stdin: {exc}", file=sys.stderr)
        sys.exit(1)

    error = _validate(payload)
    if error:
        print(f"Error: {error}", file=sys.stderr)
        sys.exit(1)

    print(build_prompt(payload))


if __name__ == "__main__":
    main()
