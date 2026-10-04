#!/usr/bin/env python3
"""One evaluation for every question the bank can hold (ADR 0042).

``evaluate(text, context=None)`` returns a VERDICT, not a number:

* ``fail`` — absolute and structural. A failing text is not a question a
  person would ask: one word ("update"), a raw label dropped into a date
  template ("When was wedding?"), an internal id, a sentence that narrates the
  vault's records or the system's own leverage, a bare yes/no. A fail is
  never filed (`question_bank.append_questions` refuses it), never queued
  (`question_planner.build_queue` skips it) and never promoted
  (`question_candidates.auto_promote_candidates`). Points cannot buy it back.
* ``review`` — plausibly fine, but a person should look: a 5–7 word question
  with no concrete thing in it, or a duplicate of a question already in the
  bank. Filed with a ``<!-- craft: review: … -->`` provenance comment; never
  auto-promoted.
* ``pass`` — and only a pass carries a ``score``: the unified quality score
  (ADR 0008), which ranks among passes and never rescues a fail.

Deterministic, no model call, no vault read — every input arrives in
``context`` — so the hosted platform can REPLAY it at send time exactly.

Every rule is written to be NARROW. A rule that fails a good question is worse
than no rule: an imperative ("Tell me about…") is a good question without a
question mark; ``day-to-day`` is a word, not a slug; "When did you…" is the
person's own date, not a template.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from typing import TypedDict

#: The three verdicts, in order of severity.
PASS = "pass"
REVIEW = "review"
FAIL = "fail"
VERDICTS = (PASS, REVIEW, FAIL)

#: Fewer words than this is not a question (`update`, `gist`, `When was MIT?`).
MIN_WORDS = 5
#: A question this short must name something concrete or a person looks at it.
REVIEW_MAX_WORDS = 7

#: An imperative opener is a GOOD prompt with no question mark ("Tell me about
#: a failure that taught you something."). Matched case-insensitively at the
#: start of the text, on a word boundary.
IMPERATIVE_OPENERS = (
    "tell me",
    "describe",
    "walk me through",
    "pick one",
    "take me back",
    "think of",
    "think about",
    "say more",
    "imagine",
    "picture",
    "share",
    "name",
    "finish this sentence",
    "talk about",
    "show me",
    "help me",
)

#: Yes/no openers (moved here from `question_candidates`, which re-exports it).
YES_NO_PATTERNS = re.compile(
    r"^(did you|do you|have you|were you|was it|is it|are you|can you|could you|would you|should you)\b",
    re.IGNORECASE,
)

# A question that narrates the vault's own records ("appears in your records
# only as a name") is the system talking about itself, not asking the person
# anything. Whole-phrase, case-insensitive (roster-identity §4.4, P6; v382).
# Defined HERE (ADR 0042); `question_candidates.check_quality` imports it for
# its score-path penalty.
NARRATES_RECORDS_PHRASES = (
    "in your records",
    "your records only",
    "your archive",
    "appears only as",
    "no story behind",
    "no story yet",
    "nothing written about",
    "nothing recorded about",
    "your vault",
    "your wiki",
    "your files",
)
NARRATES_RECORDS_PATTERN = re.compile(
    "|".join(r"\b" + re.escape(p) + r"\b" for p in NARRATES_RECORDS_PHRASES),
    re.IGNORECASE,
)

#: The system narrating its own leverage or coverage to the person ("your
#: answer places 8 timeline moments at once", "category coverage", "40%").
NARRATES_SYSTEM_PATTERNS = (
    re.compile(r"\bplaces?\s+\d+\s+(?:timeline\s+)?(?:moments?|things?|events?)\b", re.IGNORECASE),
    re.compile(r"\bwould\s+place\s+\d+\b", re.IGNORECASE),
    re.compile(r"\byour\s+answer\s+(?:would\s+)?places?\b", re.IGNORECASE),
    re.compile(r"\bcategory\s+coverage\b", re.IGNORECASE),
    re.compile(r"\b\d+(?:\.\d+)?\s?%"),
)

#: ``When was <label>?`` / ``When did <label>?`` — the whole text, one clause.
_DATE_TEMPLATE_RE = re.compile(
    r"^when\s+(?P<verb>was|did)\s+(?P<body>[^?]+?)\s*\?$", re.IGNORECASE)
_DETERMINED_RE = re.compile(
    r"^(?:the|a|an|this|that|our|my|his|her|their|its)\s|^\S+['\u2019]s\s", re.IGNORECASE)
_PERSON_SUBJECT_RE = re.compile(r"\b(you|your|yours|yourself)\b", re.IGNORECASE)
#: A ``When did <X>?`` whose X ends in an event NOUN rather than a verb is a
#: label in a template ("When did wedding?", "When did the graduation?").
#: Words that are also verbs ("move", "start") are deliberately absent:
#: "When did the Calloways move?" is a sentence.
_EVENT_NOUNS = frozenset({
    "wedding", "marriage", "birth", "death", "graduation", "mission",
    "divorce", "engagement", "funeral", "retirement", "job", "school",
    "span", "transition", "episode", "period", "event", "loss",
})
_NOMINAL_SUFFIX_RE = re.compile(r"(?:tion|sion|ment|ance|ence)$", re.IGNORECASE)

#: Internal identifiers: the substrate's ``<prefix>:<hex>`` ids (any length a
#: person could not have typed), and slugs — but only a slug that carries a
#: digit or that the caller names as an anchor/roster slug. A bare hyphen is
#: never enough: ``day-to-day``, ``matter-of-fact``, ``hand-me-downs``.
_PREFIXED_ID_RE = re.compile(r"(?<![\w])[a-z_]+:[0-9a-f]{8,}(?![\w])", re.IGNORECASE)
_SLUG_RE = re.compile(r"(?<![\w-])[a-z]+(?:-[a-z0-9]+){2,}(?![\w-])")
_SNAKE_RE = re.compile(r"(?<![\w])[a-z]+_[a-z0-9_]+(?![\w])")
_PLACEHOLDER_RE = re.compile(r"\{[a-z_]+\}")
_EMPTY_SUBJECT_RE = re.compile(
    r"\b(?:was|were|did|about|for)\s+(?:none|null|nan|undefined)\b", re.IGNORECASE)

#: A yes/no opener that is really a polite imperative or carries an embedded
#: wh-question is not BARE: "Can you tell me about…", "Do you know the year
#: you got married?".
_POLITE_IMPERATIVE_RE = re.compile(
    r"^(?:can|could|would|will)\s+you\s+(?:tell|describe|walk|share|say|talk|"
    r"explain|paint|recall|remember|picture|think|name|list|give|take)\b",
    re.IGNORECASE,
)
_EMBEDDED_WH_RE = re.compile(
    r"^(?:do|did|can|could)\s+you\s+(?:know|remember|recall)\s+(?:what|when|where|who|"
    r"how|which|why|whether|if|the\s+(?:year|month|day|date|season|age|name|place|"
    r"time|moment|first|last))\b",
    re.IGNORECASE,
)
#: Follow-through: a second clause or question after the yes/no.
_FOLLOW_THROUGH_RE = re.compile(
    r"(?:\s[—–]\s|\s--?\s|;\s|"
    r",\s*(?:and\s+|or\s+|but\s+)?(?:what|how|why|who|where|when|which|tell me|if so|if not)\b|"
    r"\b(?:and|or)\s+(?:what|how|why|who|where|when|which)\b|\bif so\b)",
    re.IGNORECASE,
)

#: Words that name nothing. A 5–7 word question whose every content word is
#: in here (or a stopword) asks about nothing concrete: review.
_STOPWORDS = frozenset({
    "a", "an", "the", "you", "your", "yours", "yourself", "me", "my", "i", "we",
    "us", "our", "they", "them", "their", "he", "she", "him", "her", "his", "its",
    "it", "of", "in", "on", "at", "to", "for", "and", "or", "but", "if", "so",
    "is", "are", "was", "were", "be", "been", "being", "am", "do", "did", "does",
    "done", "have", "has", "had", "what", "when", "where", "how", "who", "whom",
    "whose", "which", "why", "that", "this", "these", "those", "there", "here",
    "about", "with", "as", "would", "could", "should", "will", "can", "may",
    "might", "must", "from", "by", "into", "out", "up", "down", "over", "not",
    "no", "yes", "then", "now", "just", "also", "very", "really", "too",
    "d", "s", "ll", "re", "ve", "t", "m",
})
_VAGUE_WORDS = frozenset({
    "thing", "things", "stuff", "something", "anything", "everything", "nothing",
    "more", "else", "other", "another", "some", "any", "all", "one", "ones",
    "much", "many", "lot", "lots", "way", "ways", "kind", "sort", "part",
    "update", "updates", "gist", "detail", "details", "story", "stories",
    "tell", "say", "said", "think", "thought", "feel", "felt", "know", "knew",
    "mean", "meant", "happen", "happened", "happening", "go", "went", "going",
    "get", "got", "like", "make", "made", "want", "wanted", "come", "came",
    "remember", "important", "interesting", "different", "same",
})
_WORD_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9'’-]*")
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.?!])\s+")
_TRAILING_JUNK = " \t\r\n\"'“”‘’*)"


# Two questions whose normalized token sets overlap at/above this Jaccard
# ratio are treated as the same question (semantic dedup, no AI needed).
# Moved here from `question_candidates` (which re-exports it) so the one
# evaluation needs nothing but itself to judge a duplicate.
NEAR_DUPLICATE_JACCARD = 0.75


def normalize_question(text: str) -> str:
    text = text.strip().lower()
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


_DEDUP_STOPWORDS = {
    "a", "an", "the", "you", "your", "yours", "me", "my", "i", "we", "us",
    "of", "in", "on", "at", "to", "for", "and", "or", "is", "are", "was",
    "were", "do", "did", "does", "what", "when", "where", "how", "that",
    "this", "it", "about", "with", "have", "has", "had", "be", "been",
    "as", "would", "could", "should", "will", "can",
    # contraction fragments left by normalization ("you'd" → "you d")
    "d", "s", "ll", "re", "ve", "t", "m",
}


def _question_tokens(text: str) -> set[str]:
    return {t for t in normalize_question(text).split()
            if len(t) > 1 and t not in _DEDUP_STOPWORDS}


def near_duplicate_of(text: str, other_texts: list[tuple[str, str]],
                      threshold: float = NEAR_DUPLICATE_JACCARD) -> str | None:
    """Return the label of the first near-duplicate of `text` among
    (label, text) pairs, judged by content-token Jaccard overlap. Catches
    reworded duplicates that exact normalization misses (e.g. three
    'what did you promise yourself you'd do differently' variants)."""
    tokens = _question_tokens(text)
    if len(tokens) < 3:
        return None  # too short to judge similarity meaningfully
    for label, other in other_texts:
        other_tokens = _question_tokens(other)
        if len(other_tokens) < 3:
            continue
        union = tokens | other_tokens
        if union and len(tokens & other_tokens) / len(union) >= threshold:
            return label
    return None


class Verdict(TypedDict):
    verdict: str
    reasons: list[str]
    score: float


def _clean(text: object) -> str:
    return " ".join(str(text or "").split()).strip()


def words(text: str) -> list[str]:
    """The words a person reads — punctuation and dashes are not words."""
    return _WORD_RE.findall(text)


def _ends_as_question(text: str) -> bool:
    stripped = text.rstrip(_TRAILING_JUNK)
    if stripped.endswith("?"):
        return True
    # A question with one line of guidance after it ("About when was it? A
    # year is enough.") is still a question: its FIRST sentence asks.
    first = _SENTENCE_SPLIT_RE.split(text, maxsplit=1)[0].rstrip(_TRAILING_JUNK)
    return first.endswith("?")


def opens_as_imperative(text: str) -> bool:
    lowered = text.lstrip(" \"'“‘").lower()
    return any(re.match(re.escape(opener) + r"\b", lowered) for opener in IMPERATIVE_OPENERS)


def _content_tokens(text: str) -> list[str]:
    return [w.lower().strip("'’") for w in words(text)
            if w.lower().strip("'’") not in _STOPWORDS]


def _label_template(text: str) -> bool:
    match = _DATE_TEMPLATE_RE.match(text.rstrip(_TRAILING_JUNK.replace(")", "")))
    if not match:
        return False
    body = match.group("body")
    if _PERSON_SUBJECT_RE.search(body):
        return False
    if match.group("verb").lower() == "was":
        # A raw label has no determiner: "When was wedding?", "When was move
        # to Springfield?", "When was MIT?". "When was the kitchen fire?" and
        # "When was Harvey's birth?" are sentences a person would say.
        return not _DETERMINED_RE.match(body)
    tokens = words(body)
    if len(tokens) <= 1:
        return True
    last = tokens[-1].lower()
    return last in _EVENT_NOUNS or bool(_NOMINAL_SUFFIX_RE.search(last))


def _garbled_repeat(text: str) -> bool:
    """The same stem twice where one is its nominalization: "graduate from
    high school graduation". Both tokens six letters or longer."""
    tokens = [t.lower() for t in words(text) if len(t) >= 6]
    for i, left in enumerate(tokens):
        for right in tokens[i + 1:]:
            if left == right or left[:6] != right[:6]:
                continue
            if _NOMINAL_SUFFIX_RE.search(left) or _NOMINAL_SUFFIX_RE.search(right):
                return True
    return False


def _context_slugs(context: dict) -> set[str]:
    slugs: set[str] = set()
    for key in ("slugs", "anchors", "roster"):
        for value in context.get(key) or ():
            item = str(value or "").strip().lower()
            # Only a slug-SHAPED string can be matched as a slug: a bare name
            # ("james") is a word a person says.
            if item and ("-" in item or "_" in item or "/" in item):
                slugs.add(item)
    return slugs


def _internal_id(text: str, context: dict) -> str | None:
    match = _PREFIXED_ID_RE.search(text)
    if match:
        return match.group(0)
    for slug in _SLUG_RE.findall(text):
        if any(ch.isdigit() for ch in slug):
            return slug
    match = _SNAKE_RE.search(text)
    if match:
        return match.group(0)
    match = _PLACEHOLDER_RE.search(text)
    if match:
        return match.group(0)
    lowered = text.lower()
    for slug in _context_slugs(context):
        if re.search(rf"(?<![\w-]){re.escape(slug)}(?![\w-])", lowered):
            return slug
    return None


def _bare_yes_no(text: str) -> bool:
    if not YES_NO_PATTERNS.match(text):
        return False
    if _POLITE_IMPERATIVE_RE.match(text) or _EMBEDDED_WH_RE.match(text):
        return False
    if text.count("?") >= 2:
        return False
    return not _FOLLOW_THROUGH_RE.search(text)


def _bank_rows(context: dict) -> list[tuple[str, str]]:
    rows: list[tuple[str, str]] = []
    for row in context.get("bank") or ():
        if isinstance(row, dict):
            rows.append((str(row.get("id") or "?"), str(row.get("text") or "")))
        elif isinstance(row, (list, tuple)) and len(row) == 2:
            rows.append((str(row[0]), str(row[1])))
    self_id = str(context.get("self_id") or "")
    return [(qid, text) for qid, text in rows if not self_id or qid != self_id]


def fail_reasons(text: str, context: dict | None = None) -> list[str]:
    """Every structural reason ``text`` is not a question. Empty = not a fail."""
    ctx = context if isinstance(context, dict) else {}
    body = _clean(text)
    reasons: list[str] = []
    if len(words(body)) < MIN_WORDS:
        reasons.append("too_short")
    if not _ends_as_question(body) and not opens_as_imperative(body):
        reasons.append("not_a_question")
    if _label_template(body):
        reasons.append("label_template")
    leaked = _internal_id(body, ctx)
    if leaked:
        reasons.append(f"internal_id:{leaked}")
    if _EMPTY_SUBJECT_RE.search(body):
        reasons.append("empty_subject")
    if _garbled_repeat(body):
        reasons.append("garbled_repeat")
    if NARRATES_RECORDS_PATTERN.search(body):
        reasons.append("narrates_records")
    if any(pattern.search(body) for pattern in NARRATES_SYSTEM_PATTERNS):
        reasons.append("narrates_system")
    if _bare_yes_no(body):
        reasons.append("bare_yes_no")
    return reasons


def review_reasons(text: str, context: dict | None = None) -> list[str]:
    """Reasons a person should look before this question is asked."""
    ctx = context if isinstance(context, dict) else {}
    body = _clean(text)
    reasons: list[str] = []
    count = len(words(body))
    if MIN_WORDS <= count <= REVIEW_MAX_WORDS:
        concrete = [t for t in _content_tokens(body) if t not in _VAGUE_WORDS]
        if not concrete:
            reasons.append("no_concrete_noun")
    bank = _bank_rows(ctx)
    if bank:
        wanted = normalize_question(body)
        exact = next((qid for qid, other in bank if normalize_question(other) == wanted), None)
        if exact:
            reasons.append(f"duplicate_of:{exact}")
        else:
            near = near_duplicate_of(body, bank)
            if near:
                reasons.append(f"near_duplicate_of:{near}")
    return reasons


def evaluate(text: object, *, context: dict | None = None, with_score: bool = True) -> Verdict:
    """The verdict on one question text. See the module docstring.

    ``context`` (all optional): ``bank`` — ``[(id, text)]`` or ``[{id, text}]``
    for the duplicate check; ``self_id`` — the bank id being re-evaluated, so a
    question is never its own duplicate; ``slugs``/``anchors``/``roster`` —
    slug-shaped handles a template might leak; ``candidate`` — candidate fields
    (``priority``, ``story_function``, ``source_path``) for the score.
    """
    ctx = context if isinstance(context, dict) else {}
    body = _clean(text)
    failed = fail_reasons(body, ctx)
    if failed:
        return {"verdict": FAIL, "reasons": failed, "score": 0.0}
    reviewed = review_reasons(body, ctx)
    if reviewed:
        return {"verdict": REVIEW, "reasons": reviewed, "score": 0.0}
    score = 0.0
    if with_score:
        from question_candidates import unified_quality_score  # noqa: PLC0415

        candidate = dict(ctx.get("candidate") or {})
        candidate["text"] = body
        score = float(unified_quality_score(candidate)["score"])
    return {"verdict": PASS, "reasons": [], "score": score}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Evaluate one question text (ADR 0042)")
    parser.add_argument("text", help="The question text")
    args = parser.parse_args(argv)
    print(json.dumps(evaluate(args.text), indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
