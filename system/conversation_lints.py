#!/usr/bin/env python3
"""Lifehug — the deterministic conversation lint engine.

One authoritative module for the checks that will run both in CI evals and
at Wave-2 runtime (recurring-defect doctrine — never an inline copy).
``interactions/conversation/evals/lints.yaml`` (issue #114) is the config
authority (banned phrases, the length cap, on/off per lint id); this module
is the engine that reads that config and applies it.

Lints are heuristic by design, false-negative-lenient and false-positive-
strict (a lint that flags a genuinely good turn will be muted in Wave 2 —
bias against that). Two heuristics worth documenting explicitly:

* **"Count question sentences, not raw '?'."** A receipt legitimately
  quotes the user's own words, and the user's own words can themselves be
  a question they once asked ("You once asked me, \"was it hard?\", and I
  never really answered.") — that embedded, ECHOED question must not count
  as one the model is asking. Before splitting into sentences, any
  double-quoted span that itself contains a ``?`` is stripped. A quoted
  span WITHOUT a ``?`` (a cued invitation quoting a non-question phrase,
  e.g. "the old farmhouse") is left intact — it is what marks a question
  as ``cued``, a good pattern.
* **Sentence splitting** is a plain ``[^.!?]+[.!?]*`` regex scan — no NLP
  dependency (the repo is deliberately stdlib-only). It is good enough for
  the goldens this PR's tests exercise; goldens/real transcripts in the
  eval-harness PR may expose sharper cases later.

Public surface:

    load_lints_config(*, framework_root=None) -> dict
    lint_turn(text, *, is_reply_to_substantive=False, config=None) -> list[dict]
    lint_transcript(turns, *, config=None) -> list[dict]

Findings are ``{"lint": "<id>", "detail": "...", "span": [start, end]}``.
Implemented lint ids (exactly matching lints.yaml and behavior.md rule
numbers): ``one_question_per_turn`` (rule 1), ``banned_phrases`` (rules
4/5/12 + the do-not-use list), ``question_grammar_audit`` (rule 3),
``length_caps``, ``receipt_before_question`` (rule 2, structural),
``year_question_detector`` (rule 3).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from lifehug_core import INTERACTIONS_DIR, _parse_simple_yaml

DEFAULT_CAP_TURN_CHARS = 1200
SUBSTANTIVE_MIN_CHARS = 20  # heuristic floor for a "substantive" preceding user turn

#: The closed grammar-classification vocabulary (question_grammar_audit).
#: Only "closed" and "option_posing" produce findings; "ted"/"cued"/"other"
#: are informational tags a question sentence may also carry.
QUESTION_GRAMMAR_TAGS = frozenset({"ted", "cued", "closed", "option_posing", "other"})

_QUOTED_SPAN_RE = re.compile(r'"[^"]*"')
_QUOTED_QUESTION_RE = re.compile(r'"[^"]*\?[^"]*"')
_SENTENCE_RE = re.compile(r'[^.!?]+[.!?]*')
_TED_RE = re.compile(r'^\s*(tell me|describe|explain|walk me through)\b', re.IGNORECASE)
_CLOSED_RE = re.compile(
    r'^\s*(do|does|did|is|are|was|were|have|has|had|can|could|will|would|should|shall|may|might)\b',
    re.IGNORECASE,
)
_OR_RE = re.compile(r'\bor\b', re.IGNORECASE)
_YEAR_PATTERNS = ("what year", "which year", "in what year")


def _conversation_evals_path(*parts: str, framework_root: str | Path | None = None) -> Path:
    base = Path(framework_root) / "interactions" / "conversation" / "evals" if framework_root is not None \
        else INTERACTIONS_DIR / "conversation" / "evals"
    return base.joinpath(*parts)


def load_lints_config(*, framework_root: str | Path | None = None) -> dict:
    """Read evals/lints.yaml's flat subset: lint.<id>: on/off, cap.*, banned.N."""
    path = _conversation_evals_path("lints.yaml", framework_root=framework_root)
    raw = _parse_simple_yaml(path, validate_ai_routing=False)
    config: dict[str, object] = {}
    banned: list[str] = []
    for key, value in raw.items():
        if key.startswith("lint."):
            config[key] = value.strip().lower() == "on"
        elif key.startswith("cap."):
            try:
                config[key] = int(value)
            except ValueError:
                config[key] = value
        elif key.startswith("banned."):
            banned.append(value)
        else:
            config[key] = value
    config["banned_phrases"] = banned
    return config


def _strip_echoed_questions(text: str) -> str:
    return _QUOTED_QUESTION_RE.sub("", text)


def _split_sentences(text: str) -> list[str]:
    return [s for s in _SENTENCE_RE.findall(text) if s.strip()]


def _is_question(sentence: str) -> bool:
    return sentence.rstrip().endswith("?")


def _classify_question(sentence: str) -> set[str]:
    tags: set[str] = set()
    if _TED_RE.search(sentence):
        tags.add("ted")
    if _QUOTED_SPAN_RE.search(sentence):
        tags.add("cued")
    if _CLOSED_RE.match(sentence.strip()):
        tags.add("closed")
    if _OR_RE.search(sentence):
        tags.add("option_posing")
    if not tags:
        tags.add("other")
    return tags


def _span_of(text: str, needle: str) -> list[int]:
    clean = needle.strip()
    start = text.find(clean) if clean else -1
    if start == -1:
        return [0, len(text)]
    return [start, start + len(clean)]


def lint_turn(
    text: str,
    *,
    is_reply_to_substantive: bool = False,
    config: dict | None = None,
) -> list[dict]:
    """Deterministic findings for one lifehug-role turn's text."""
    config = config if config is not None else load_lints_config()
    findings: list[dict] = []

    stripped = _strip_echoed_questions(text)
    sentences = _split_sentences(stripped)
    question_sentences = [s for s in sentences if _is_question(s)]

    if config.get("lint.one_question_per_turn", True) and len(question_sentences) > 1:
        findings.append({
            "lint": "one_question_per_turn",
            "detail": f"{len(question_sentences)} questions found in one turn",
            "span": _span_of(text, question_sentences[-1]),
        })

    if config.get("lint.banned_phrases", True):
        lowered = text.lower()
        for phrase in config.get("banned_phrases", []):
            idx = lowered.find(str(phrase).lower())
            if idx != -1:
                findings.append({
                    "lint": "banned_phrases",
                    "detail": f"banned phrase: {phrase!r}",
                    "span": [idx, idx + len(phrase)],
                })

    if config.get("lint.question_grammar_audit", True):
        for sentence in question_sentences:
            tags = _classify_question(sentence)
            if "closed" in tags:
                findings.append({
                    "lint": "question_grammar_audit",
                    "detail": f"closed (yes/no) question: {sentence.strip()!r}",
                    "span": _span_of(text, sentence),
                })
            if "option_posing" in tags:
                findings.append({
                    "lint": "question_grammar_audit",
                    "detail": f"option-posing question: {sentence.strip()!r}",
                    "span": _span_of(text, sentence),
                })

    if config.get("lint.length_caps", True):
        cap = config.get("cap.turn_chars", DEFAULT_CAP_TURN_CHARS)
        if isinstance(cap, int) and len(text) > cap:
            findings.append({
                "lint": "length_caps",
                "detail": f"turn is {len(text)} chars, over the {cap}-char cap",
                "span": [cap, len(text)],
            })

    if config.get("lint.receipt_before_question", True) and is_reply_to_substantive:
        raw_sentences = _split_sentences(text)
        if raw_sentences and _is_question(raw_sentences[0]):
            findings.append({
                "lint": "receipt_before_question",
                "detail": "reply opens with a question instead of a receipt",
                "span": _span_of(text, raw_sentences[0]),
            })

    if config.get("lint.year_question_detector", True):
        lowered = text.lower()
        for pattern in _YEAR_PATTERNS:
            idx = lowered.find(pattern)
            if idx != -1:
                findings.append({
                    "lint": "year_question_detector",
                    "detail": f"'what year'-form question ({pattern!r})",
                    "span": [idx, idx + len(pattern)],
                })
                break

    return findings


def lint_transcript(turns: list[dict], *, config: dict | None = None) -> list[dict]:
    """Map lint_turn over lifehug-role turns; substantive-reply flag from the prior user turn."""
    config = config if config is not None else load_lints_config()
    findings: list[dict] = []
    previous_user_text = ""
    for index, turn in enumerate(turns):
        role = turn.get("role")
        text = turn.get("text") or ""
        if role == "user":
            previous_user_text = text
            continue
        if role != "lifehug":
            continue
        is_reply = len(previous_user_text.strip()) >= SUBSTANTIVE_MIN_CHARS
        for finding in lint_turn(text, is_reply_to_substantive=is_reply, config=config):
            findings.append({**finding, "turn_index": index})
    return findings


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Print deterministic conversation lint findings for stdin turn text"
    )
    parser.add_argument(
        "--reply-to-substantive",
        action="store_true",
        help="Treat this turn as a reply to a substantive preceding user message",
    )
    args = parser.parse_args()
    text = sys.stdin.read()
    # Linting is reporting, not failing (contract, Deliverable 5) — always
    # exit 0; an empty turn simply has zero findings.
    for finding in lint_turn(text, is_reply_to_substantive=args.reply_to_substantive):
        print(json.dumps(finding))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
