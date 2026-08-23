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
    lint_turn(text, *, is_reply_to_substantive=False, seam_ok=False, config=None) -> list[dict]
    lint_closing_phrases(text, *, config=None) -> list[dict]
    lint_repetition(text, prior_asks, *, config=None) -> list[dict]
    lint_transcript(turns, *, config=None) -> list[dict]

**ADR 0014 (issue #163, structured close)**: ``lint_closing_phrases`` was
extended beyond the pure-chat wave's declarative-close phrase ban to also
catch leaked model scaffolding in the DELIVERED ``takeaway_prose`` — labeled
fields ("Hook for next time:"), meta-commentary judging the conversation's
quality or the author's own conversational behavior, instructions addressed
to a future turn/session, and raw ``**`` markdown emphasis (channel delivery
never renders markdown). Each class keeps its own lint id
(``closing_label_leak`` / ``closing_meta_commentary`` / ``closing_future_turn``
/ ``closing_markdown_leak``) so a golden or test can assert exactly which
class tripped — see that function's docstring for the full contract.

Findings are ``{"lint": "<id>", "detail": "...", "span": [start, end]}``.
Implemented lint ids (exactly matching lints.yaml and behavior.md rule
numbers): ``one_question_per_turn`` (rule 1), ``banned_phrases`` (rules
4/5/12 + the do-not-use list), ``question_grammar_audit`` (rule 3),
``length_caps``, ``receipt_before_question`` (rule 2, structural),
``year_question_detector`` (rule 3), ``no_repetition`` (v201,
lifehug#206 — rule 13's back-off doctrine made structural: a reply may
not re-ask what this same voice already asked in its last few turns).

**Eval-harness amendment (issue #120, consistency-audit)**: the grammar
classifier's baseline tags (``ted``/``cued``/``closed``/``option_posing``/
``other``) are wave-1 (#115) reality and stay as landed — the eval
contract's own vocabulary sketch (``cued``/``cued_invitation``/``closed``/
``option_posing``/``presupposing``) is not renamed onto them (merged
reality wins per the contract's own binding fact). This module ADDS
``presupposing`` to the set additively: a question sentence that assumes an
unconfirmed narrative fact or motive ("what made you decide", "why did you
choose", "when did you realize", or a "So you ..." lead-in before the
question) rather than inviting the user to supply one. ``closed``,
``option_posing``, and ``presupposing`` findings are suppressed when the
caller marks the turn ``seam_ok=True`` (a golden-annotated exception to
rule 3, e.g. a deliberate closed confirmation at a narrative seam) — every
other lint stays enforced regardless of ``seam_ok``.
"""

from __future__ import annotations

import argparse
import difflib
import json
import re
import sys
from collections.abc import Sequence
from pathlib import Path

from lifehug_core import INTERACTIONS_DIR, _parse_simple_yaml

DEFAULT_CAP_TURN_CHARS = 1200
SUBSTANTIVE_MIN_CHARS = 20  # heuristic floor for a "substantive" preceding user turn

#: The closed grammar-classification vocabulary (question_grammar_audit).
#: "closed", "option_posing", and "presupposing" produce findings (subject
#: to the seam_ok exemption below); "ted"/"cued"/"other" are informational
#: tags a question sentence may also carry.
QUESTION_GRAMMAR_TAGS = frozenset(
    {"ted", "cued", "closed", "option_posing", "presupposing", "other"}
)
#: The subset of QUESTION_GRAMMAR_TAGS that produce findings unless the
#: turn is annotated seam_ok (behavior.md rule 3; issue #120 amendment) —
#: documentation only; lint_turn gates the whole audit block on seam_ok
#: since "ted"/"cued"/"other" never produce findings in the first place.
GATED_GRAMMAR_TAGS = frozenset({"closed", "option_posing", "presupposing"})

_QUOTED_SPAN_RE = re.compile(r'"[^"]*"')
_QUOTED_QUESTION_RE = re.compile(r'"[^"]*\?[^"]*"')
_SENTENCE_RE = re.compile(r'[^.!?]+[.!?]*')
_TED_RE = re.compile(r'^\s*(tell me|describe|explain|walk me through)\b', re.IGNORECASE)
_CLOSED_RE = re.compile(
    r'^\s*(do|does|did|is|are|was|were|have|has|had|can|could|will|would|should|shall|may|might)\b',
    re.IGNORECASE,
)
_OR_RE = re.compile(r'\bor\b', re.IGNORECASE)
#: Presupposing lead-ins (issue #120): the question assumes a decision,
#: realization, or narrative frame the user has not actually confirmed yet,
#: rather than inviting them to supply one.
_PRESUPPOSING_RE = re.compile(
    r'^\s*(what made you|why did you (?:decide|choose)|when did you realize|so you\b.*,)',
    re.IGNORECASE,
)
_YEAR_PATTERNS = ("what year", "which year", "in what year")
#: Clause-initial "next time," followed by an imperative — a grammatical
#: shape (ADR 0014, issue #163), not a literal phrase, so it stays an engine
#: constant rather than lints.yaml data (same precedent as _PRESUPPOSING_RE
#: above). Matches at the start of the text or right after sentence-ending
#: punctuation, so it never flags "...with your sister next time." (mid-
#: sentence, no comma, no instruction) the way the existing goldens use it.
_FUTURE_TURN_CLAUSE_RE = re.compile(r'(?:^|[.!?]\s+)next time,\s+\S', re.IGNORECASE)
#: Raw markdown emphasis leaking into channel-delivered text (ADR 0014) —
#: Telegram never renders "**bold**"; a close that carries it is scaffolding.
_MARKDOWN_EMPHASIS_RE = re.compile(r'\*\*')


def _conversation_evals_path(*parts: str, framework_root: str | Path | None = None) -> Path:
    base = Path(framework_root) / "interactions" / "conversation" / "evals" if framework_root is not None \
        else INTERACTIONS_DIR / "conversation" / "evals"
    return base.joinpath(*parts)


def load_lints_config(*, framework_root: str | Path | None = None) -> dict:
    """Read evals/lints.yaml's flat subset: lint.<id>: on/off, cap.*, banned.N,
    closing_banned.N (pure-chat wave, issue #139 — the declarative-close
    doctrine's own banned-phrase list, checked only against closing turns),
    and — ADR 0014, issue #163 — closing_label.N / closing_meta.N /
    closing_future.N (the structured-close scaffolding-leak checks, also
    closing-only), and repetition.* (v201, lifehug#206 — the no_repetition
    lint's lookback/similarity; closing_meta.N values are matched as case-insensitive
    regex, since the meta-commentary class needs alternation)."""
    path = _conversation_evals_path("lints.yaml", framework_root=framework_root)
    raw = _parse_simple_yaml(path, validate_ai_routing=False)
    config: dict[str, object] = {}
    banned: list[str] = []
    closing_banned: list[str] = []
    closing_label: list[str] = []
    closing_meta: list[str] = []
    closing_future: list[str] = []
    for key, value in raw.items():
        if key.startswith("lint."):
            config[key] = value.strip().lower() == "on"
        elif key.startswith("cap."):
            try:
                config[key] = int(value)
            except ValueError:
                config[key] = value
        elif key.startswith("closing_banned."):
            closing_banned.append(value)
        elif key.startswith("closing_label."):
            closing_label.append(value)
        elif key.startswith("closing_meta."):
            closing_meta.append(value)
        elif key.startswith("closing_future."):
            closing_future.append(value)
        elif key.startswith("repetition."):
            # v201 (lifehug#206): lookback is an int, similarity a float —
            # cast here so the engine never sees these as strings.
            try:
                config[key] = int(value) if key.endswith(".lookback") else float(value)
            except ValueError:
                config[key] = value
        elif key.startswith("banned."):
            banned.append(value)
        else:
            config[key] = value
    config["banned_phrases"] = banned
    config["closing_banned_phrases"] = closing_banned
    config["closing_label_phrases"] = closing_label
    config["closing_meta_commentary_patterns"] = closing_meta
    config["closing_future_turn_phrases"] = closing_future
    return config


#: Punctuation dropped before two asks are compared (v201, lifehug#206) —
#: quotes, dashes and terminal marks differ freely between two renderings
#: of the same question.
_ASK_PUNCT_RE = re.compile(r"[^\w\s]+", re.UNICODE)


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
    if _PRESUPPOSING_RE.match(sentence.strip()):
        tags.add("presupposing")
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
    seam_ok: bool = False,
    config: dict | None = None,
) -> list[dict]:
    """Deterministic findings for one lifehug-role turn's text.

    ``seam_ok`` (issue #120) suppresses only the gated grammar findings
    (closed/option_posing/presupposing) — every other lint, including
    ``one_question_per_turn`` and ``banned_phrases``, is unaffected. Runtime
    callers (``conversation_delivery``) never annotate seams and so always
    pass the default ``False``; only golden-transcript evaluation does.
    """
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

    if config.get("lint.question_grammar_audit", True) and not seam_ok:
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
            if "presupposing" in tags:
                findings.append({
                    "lint": "question_grammar_audit",
                    "detail": f"presupposing question: {sentence.strip()!r}",
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


def lint_closing_phrases(text: str, *, config: dict | None = None) -> list[dict]:
    """Every closing-only check for CLOSING turns (never applied mid-
    conversation, where the same words are often fine).

    Two doctrines, both checked here (single authority — recurring-defect
    doctrine):

    1. **Declarative-close phrase ban** (behavior.md rule 8, pure-chat wave,
       issue #139, 2026-08-12): phrases that narrate the close is
       happening ("leave it here", "for now", "a good place to rest")
       instead of simply closing. ``lint.closing_declarative`` /
       ``closing_banned.N``. The companion "no question at all" half of
       this doctrine is enforced elsewhere (``conversation_delivery
       .lint_outgoing``'s ``question_allowed=False`` pass;
       ``interaction_evals._check_closing_is_declarative`` re-derives the
       same "no question mark" rule directly), so this function stays
       scoped to banned-phrase-shaped checks only.

    2. **Structured-close scaffolding-leak ban** (ADR 0014, issue #163,
       2026-08-15): the DELIVERED ``takeaway_prose`` must be the model's
       one woven statement, never its own bookkeeping. Four independently-
       flagged classes:

       - ``lint.closing_label_leak`` (``closing_label.N``): literal
         labeled-field substrings ("Hook for next time:", "Takeaway:") —
         the exact shape issue #163's incident rendered verbatim.
       - ``lint.closing_meta_commentary`` (``closing_meta.N``, matched as
         case-insensitive regex — the class needs alternation, e.g. "made
         this (actually )?(useful|productive)"): commentary evaluating the
         CONVERSATION's quality or the author's own conversational
         behavior ("I appreciated that you pushed back"). Distinct from
         the rule-8-required "specific appreciation" of what the person
         actually shared, which stays allowed and unflagged.
       - ``lint.closing_future_turn`` (``closing_future.N`` literal phrases
         plus the engine-side ``_FUTURE_TURN_CLAUSE_RE`` grammatical
         shape): instructions addressed to a future turn or session
         ("Next time, pick up wherever...", "no need to re-explain").
         Continuity is the machine's job via the structured ``hook`` field
         now — never a sentence talking to the next session's model.
       - ``lint.closing_markdown_leak`` (no data — pure structural): a raw
         ``**`` emphasis marker. Channel delivery never renders markdown,
         so its presence is scaffolding, not formatting.

    Single authority for both callers of this whole function (recurring-
    defect doctrine): the runtime (``conversation_delivery
    .lint_outgoing(is_closing=True)``) and the golden-transcript property
    checker (``interaction_evals._check_closing_is_declarative``) both call
    it rather than each keeping its own phrase/pattern lists.
    """
    config = config if config is not None else load_lints_config()
    findings: list[dict] = []

    if config.get("lint.closing_declarative", True):
        lowered = text.lower()
        for phrase in config.get("closing_banned_phrases", []):
            idx = lowered.find(str(phrase).lower())
            if idx != -1:
                findings.append({
                    "lint": "closing_declarative",
                    "detail": f"banned closing meta-phrase: {phrase!r}",
                    "span": [idx, idx + len(phrase)],
                })

    if config.get("lint.closing_label_leak", True):
        lowered = text.lower()
        for phrase in config.get("closing_label_phrases", []):
            idx = lowered.find(str(phrase).lower())
            if idx != -1:
                findings.append({
                    "lint": "closing_label_leak",
                    "detail": f"labeled scaffolding field leaked into the close: {phrase!r}",
                    "span": [idx, idx + len(phrase)],
                })

    if config.get("lint.closing_meta_commentary", True):
        for pattern in config.get("closing_meta_commentary_patterns", []):
            match = re.search(str(pattern), text, re.IGNORECASE)
            if match:
                findings.append({
                    "lint": "closing_meta_commentary",
                    "detail": f"meta-commentary on the conversation itself: {pattern!r}",
                    "span": [match.start(), match.end()],
                })

    if config.get("lint.closing_future_turn", True):
        match = _FUTURE_TURN_CLAUSE_RE.search(text)
        if match:
            findings.append({
                "lint": "closing_future_turn",
                "detail": "clause-initial 'next time,' instruction addressed to a future turn",
                "span": [match.start(), match.end()],
            })
        lowered = text.lower()
        for phrase in config.get("closing_future_turn_phrases", []):
            idx = lowered.find(str(phrase).lower())
            if idx != -1:
                findings.append({
                    "lint": "closing_future_turn",
                    "detail": f"instruction addressed to a future turn or session: {phrase!r}",
                    "span": [idx, idx + len(phrase)],
                })

    if config.get("lint.closing_markdown_leak", True):
        match = _MARKDOWN_EMPHASIS_RE.search(text)
        if match:
            findings.append({
                "lint": "closing_markdown_leak",
                "detail": "raw markdown emphasis ('**') leaked into channel-delivered text",
                "span": [match.start(), match.end()],
            })

    return findings


#: Defaults for the `no_repetition` lint (v201, lifehug#206) when
#: lints.yaml is absent or holds a non-numeric value.
DEFAULT_REPETITION_LOOKBACK = 2
DEFAULT_REPETITION_SIMILARITY = 0.86

#: Openers that carry no content of their own — stripped before two asks are
#: compared so "So what were you about to say?" and "What were you about to
#: say?" are recognised as the same ask, which is how a person hears them.
_ASK_PREFIXES = (
    "so ", "and ", "but ", "ok ", "okay ", "well ", "then ", "now ",
)


def _normalize_ask(sentence: str) -> str:
    """One question sentence reduced to what it actually asks."""
    text = _ASK_PUNCT_RE.sub(" ", sentence.lower())
    text = " ".join(text.split())
    changed = True
    while changed:
        changed = False
        for prefix in _ASK_PREFIXES:
            if text.startswith(prefix):
                text = text[len(prefix):]
                changed = True
    return text


def asks_in(text: str) -> list[str]:
    """The normalized question sentences this turn asks — the user's own
    echoed questions stripped first, exactly like every other lint here."""
    stripped = _strip_echoed_questions(text)
    return [
        _normalize_ask(s) for s in _split_sentences(stripped) if _is_question(s)
    ]


def _near_duplicate(left: str, right: str, threshold: float) -> bool:
    if not left or not right:
        return False
    if left == right:
        return True
    if left in right or right in left:
        # A strict containment is a repeat with padding, not a new ask.
        shorter, longer = sorted((left, right), key=len)
        if len(shorter) >= 12 and len(shorter) / len(longer) >= 0.5:
            return True
    return difflib.SequenceMatcher(None, left, right).ratio() >= threshold


def lint_repetition(
    text: str, prior_asks: Sequence[Sequence[str]], *, config: dict | None = None
) -> list[dict]:
    """Findings for a reply that re-asks what this same voice just asked.

    v201 (lifehug#206). behavior.md rule 13 (mid-thread back-off) already
    forbids this in prose, but prose is not a gate, and the incident that
    produced this lint was a model asking the SAME question three turns
    running — including once directly after the person typed "you're
    repeating". The root cause was a prompt defect (a frozen, mid-sentence
    transcript; see `conversation._session_transcript_lines`), and that is
    fixed at the root — but a conversation product should not be able to
    ship a turn that repeats itself just because some future prompt bug
    makes the model blind. This is the structural floor under rule 13.

    ``prior_asks`` is this session's earlier lifehug turns' asks, oldest
    first, as produced by `asks_in` — only the last ``repetition.lookback``
    TURNS are compared (turns that asked nothing included, and spending
    the budget), because a question legitimately returned to later in a
    long conversation is a callback, not a loop.
    """
    config = config if config is not None else load_lints_config()
    if not config.get("lint.no_repetition", True):
        return []
    lookback = config.get("repetition.lookback", DEFAULT_REPETITION_LOOKBACK)
    lookback = lookback if isinstance(lookback, int) and lookback > 0 else DEFAULT_REPETITION_LOOKBACK
    threshold = config.get("repetition.similarity", DEFAULT_REPETITION_SIMILARITY)
    threshold = float(threshold) if isinstance(threshold, (int, float)) else DEFAULT_REPETITION_SIMILARITY

    # Lookback counts TURNS, not asking turns: a question returned to after
    # a few turns of pure listening is a callback, not a loop.
    recent = [asks for asks in list(prior_asks)[-lookback:] if asks]
    if not recent:
        return []
    findings: list[dict] = []
    stripped = _strip_echoed_questions(text)
    for sentence in _split_sentences(stripped):
        if not _is_question(sentence):
            continue
        normalized = _normalize_ask(sentence)
        for asks in recent:
            if any(_near_duplicate(normalized, prior, threshold) for prior in asks):
                findings.append({
                    "lint": "no_repetition",
                    "detail": f"re-asks a question from one of the last {lookback} "
                              f"turns: {sentence.strip()!r}",
                    "span": _span_of(text, sentence),
                })
                break
    return findings


def lint_transcript(turns: list[dict], *, config: dict | None = None) -> list[dict]:
    """Map lint_turn over lifehug-role turns.

    substantive-reply flag from the prior user turn; ``seam_ok`` (issue
    #120) is read per-turn from ``turn["annotations"]["seam_ok"]`` when
    present — golden transcripts annotate it, runtime turns never carry
    annotations and so default to False (unchanged runtime behavior).
    """
    config = config if config is not None else load_lints_config()
    findings: list[dict] = []
    previous_user_text = ""
    prior_asks: list[list[str]] = []
    for index, turn in enumerate(turns):
        role = turn.get("role")
        text = turn.get("text") or ""
        if role == "user":
            previous_user_text = text
            continue
        if role != "lifehug":
            continue
        is_reply = len(previous_user_text.strip()) >= SUBSTANTIVE_MIN_CHARS
        annotations = turn.get("annotations")
        seam_ok = bool(annotations.get("seam_ok")) if isinstance(annotations, dict) else False
        for finding in lint_turn(
            text, is_reply_to_substantive=is_reply, seam_ok=seam_ok, config=config
        ):
            findings.append({**finding, "turn_index": index})
        # v201 (lifehug#206): the repetition check is the one lint that needs
        # more than this turn's own text, so it runs here where the earlier
        # turns are in hand rather than inside lint_turn.
        for finding in lint_repetition(text, prior_asks, config=config):
            findings.append({**finding, "turn_index": index})
        prior_asks.append(asks_in(text))
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
