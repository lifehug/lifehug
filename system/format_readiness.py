#!/usr/bin/env python3
"""Lifehug — format readiness engine (v126).

Answers "how much material do I have for a letter to Mom before I write it?"
the same way :mod:`book` answers it for book chapters — except the unit of
readiness here is a FORMAT FRAMEWORK SLOT (templates/<format>.json), not a
question category.

The mechanism:

  1. Every question in the focus's categories is classified into a story
     function by ``question_planner.infer_story_function`` (the same
     classifier the weekly planner uses — one authoritative definition, no
     re-implementation here).
  2. A framework slot is FILLED when at least ``min_answers`` ANSWERED
     questions carry one of the slot's ``story_functions``.
  3. filled / total slots is the ratio; the framework's own thresholds turn
     that into the SAME verdict vocabulary book.py uses (EARLY / DEVELOPING /
     READY), so a UI badge renders identically for a chapter and a letter.

Zero AI calls on the compute path — pure read-only inspection of the question
bank, exactly like book.py.

Degraded mode: a missing framework (``format_frameworks.get_or_none`` → None)
or one with no slots yields a benign empty result rather than an exception.
Readiness is optional enrichment; it must never take down a drafting flow.

Import note: this module is always used vault-bound (it reads the question
bank), so unlike ``format_frameworks`` it imports ``lifehug_core`` (via
``book`` / ``question_planner``) at module scope in the ordinary repo style.
"""

from __future__ import annotations

import sys
from pathlib import Path

_SYSTEM_DIR = Path(__file__).resolve().parent
if str(_SYSTEM_DIR) not in sys.path:
    sys.path.insert(0, str(_SYSTEM_DIR))

import format_frameworks
from book import BOOK_DELIVERABLES, DEVELOPING as BOOK_DEVELOPING, READY as BOOK_READY
from lifehug_core import QUESTIONS_FILE, parse_questions
from progress import DELIVERABLE_TO_FORMAT
from question_planner import infer_story_function

# Same verdict vocabulary as book.py / progress.py. A framework spec normally
# carries its own thresholds; these are the fallback when a spec omits them
# (or when a caller hands in a partial dict).
DEFAULT_READY = BOOK_READY
DEFAULT_DEVELOPING = BOOK_DEVELOPING

# How many unanswered questions to show per slot. Three is a sitting's worth —
# more reads as a chore list, not a nudge.
MAX_GAP_QUESTIONS = 3

# Fallback when the composite "book" framework isn't on disk (vault
# mid-update). Mirrors book.BOOK_DELIVERABLES.
FALLBACK_BOOK_DELIVERABLES = frozenset(BOOK_DELIVERABLES)

# The format a person-shaped focus falls back to when its deliverable has no
# entry in progress.DELIVERABLE_TO_FORMAT.
DEFAULT_PERSON_FORMAT = "letter"

_PERSON_FOCUS_TYPES = {"person", "relationship"}


def verdict_for(ratio: float, thresholds: dict | None = None) -> str:
    """Turn a filled/total ratio into EARLY / DEVELOPING / READY."""
    thresholds = thresholds or {}
    try:
        ready = float(thresholds.get("ready", DEFAULT_READY))
    except (TypeError, ValueError):
        ready = DEFAULT_READY
    try:
        developing = float(thresholds.get("developing", DEFAULT_DEVELOPING))
    except (TypeError, ValueError):
        developing = DEFAULT_DEVELOPING
    if ratio >= ready:
        return "READY"
    if ratio >= developing:
        return "DEVELOPING"
    return "EARLY"


def _empty_result(format_id: str = "") -> dict:
    """The benign shape returned in degraded mode (no framework / no slots)."""
    return {
        "format": format_id,
        "slots": [],
        "filled_slots": 0,
        "total_slots": 0,
        "ratio": 0.0,
        "verdict": "EARLY",
    }


def _qid(question: dict) -> str:
    return str(question.get("id", ""))


# The planner's keyword tables (question_planner.STORY_FUNCTION_KEYWORDS)
# predate the relational/dyadic arc: the five relational story functions have
# no keywords there, so bank questions can never classify into them via
# infer_story_function alone — which would cap letter readiness at 1/5
# (permanently EARLY) despite a bank full of exactly these questions.
#
# This overlay is deliberately CONTAINED here rather than added to the
# planner: question_planner's own STORY_FUNCTIONS tuple and its caps tables
# cover only the 13 memoir/self functions, and teaching infer_story_function
# new return values would need a full audit of the planner's cap/lane logic.
# Readiness matching composes the overlay first, then falls back to the
# planner's classifier. Delete this table the day the planner learns the
# relational arc (research_expand.RELATIONSHIP_ARC has the definitions).
#
# Ordered most-specific first; phrases are lowercase substring matches,
# calibrated against real vault bank phrasing.
RELATIONAL_KEYWORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("what_i_want_them_to_know", (
        "haven't said", "havent said", "never told", "never said",
        "wish you had told", "wish you could tell", "want to say to",
        "want them to know", "want her to know", "want him to know",
        "found the words", "want her to feel", "want him to feel",
        "want them to feel",
    )),
    ("how_they_see_me", (
        "describe you", "see you as", "think of you", "sees you",
        "how they see you", "proud of you",
    )),
    ("what_i_see_in_them", (
        "admire", "appreciate about", "seen and appreciated", "feel seen",
        "what do you see in", "most impressed", "successful as a mother",
        "successful as a father",
    )),
    ("shared_history", (
        "moment with your", "memory with", "you two", "the two of you",
        "do together", "did together", "you both", "relive",
    )),
    ("who_they_are", (
        "like as a person", "as a person", "who was she", "who was he",
        "who is she", "who is he", "beyond being", "full person",
        "her own history", "his own history", "her passions", "his passions",
        "what was she like", "what was he like",
    )),
)


def _relational_story_function(text: str) -> str | None:
    """Relational-arc classification by phrase overlay; None if no match."""
    lowered = text.lower()
    for function, phrases in RELATIONAL_KEYWORDS:
        if any(phrase in lowered for phrase in phrases):
            return function
    return None


def story_functions_for(questions: list[dict]) -> dict[str, str]:
    """{question_id: story_function} for bank questions.

    Bank questions (``lifehug_core.parse_questions``) carry no ``kind``, so the
    classifier runs on text alone — the same call the planner makes at
    question_planner.py:592. Computed once per question and shared across every
    slot so a five-slot framework doesn't classify the bank five times.
    """
    out: dict[str, str] = {}
    for question in questions:
        qid = _qid(question)
        if not qid:
            continue
        text = str(question.get("text", ""))
        out[qid] = _relational_story_function(text) or infer_story_function(text)
    return out


def compute_readiness(framework: dict | None,
                      categories: list[str],
                      questions: list[dict]) -> dict:
    """Slot-by-slot readiness for one format against one set of categories.

    ``framework`` is a spec dict from :mod:`format_frameworks` (or None).
    ``questions`` is ``lifehug_core.parse_questions()`` output. Only questions
    whose category is in ``categories`` are considered.

    Never raises on a missing/slotless framework — returns the benign empty
    result so an optional readiness panel degrades to "nothing to show".
    """
    if not isinstance(framework, dict):
        return _empty_result()

    format_id = str(framework.get("id", "") or "")
    slots = framework.get("slots") or []
    if not isinstance(slots, list) or not slots:
        return _empty_result(format_id)

    wanted = {str(c).strip().upper() for c in (categories or []) if str(c).strip()}
    in_scope = [q for q in questions
                if str(q.get("category", "")).strip().upper() in wanted]

    functions = story_functions_for(in_scope)
    # book.py's dominant sort in practice: bank questions carry no priority, so
    # its (-priority, id) key collapses to ascending id. Same order here.
    answered = sorted((q for q in in_scope if q.get("answered")), key=_qid)
    unanswered = sorted((q for q in in_scope if not q.get("answered")), key=_qid)

    slot_rows: list[dict] = []
    filled_count = 0
    for slot in slots:
        if not isinstance(slot, dict):
            continue
        wanted_functions = {str(f) for f in (slot.get("story_functions") or [])}
        try:
            needed = int(slot.get("min_answers", 1))
        except (TypeError, ValueError):
            needed = 1
        needed = max(needed, 1)

        matched = [_qid(q) for q in answered
                   if functions.get(_qid(q)) in wanted_functions]
        gaps = [q for q in unanswered
                if functions.get(_qid(q)) in wanted_functions][:MAX_GAP_QUESTIONS]

        filled = len(matched) >= needed
        if filled:
            filled_count += 1

        slot_rows.append({
            "id": str(slot.get("id", "")),
            "label": str(slot.get("label", "")),
            "description": str(slot.get("description", "")),
            "filled": filled,
            "matched": matched,
            "needed": needed,
            "gap_questions": [
                {"id": _qid(q), "text": str(q.get("text", ""))} for q in gaps
            ],
        })

    total = len(slot_rows)
    if not total:
        return _empty_result(format_id)

    ratio = filled_count / total
    return {
        "format": format_id,
        "slots": slot_rows,
        "filled_slots": filled_count,
        "total_slots": total,
        "ratio": ratio,
        "verdict": verdict_for(ratio, framework.get("thresholds")),
    }


def book_deliverables() -> frozenset[str]:
    """Deliverables owned by book.compute_books(), read from the book framework.

    The composite "book" spec is the authoritative list; falls back to
    book.BOOK_DELIVERABLES when the spec files aren't on disk.
    """
    spec = format_frameworks.get_or_none("book")
    if isinstance(spec, dict):
        declared = spec.get("deliverables")
        if isinstance(declared, list) and declared:
            return frozenset(str(d).lower().strip() for d in declared)
    return FALLBACK_BOOK_DELIVERABLES


def default_formats_for_focus(focus: dict) -> list[str]:
    """Which format(s) a non-book focus should show a readiness card for.

    The focus's own deliverable, mapped through progress.DELIVERABLE_TO_FORMAT
    (the existing single mapping — see progress.py:59), when that lands on a
    real composable format. A person/relationship focus whose deliverable maps
    nowhere falls back to the letter, which is the format such a focus is
    almost always heading toward.
    """
    deliverable = str(focus.get("deliverable", "")).lower().strip()
    mapped = DELIVERABLE_TO_FORMAT.get(deliverable)
    if mapped and mapped in format_frameworks.valid_formats():
        return [mapped]
    if str(focus.get("type", "")).lower().strip() in _PERSON_FOCUS_TYPES:
        return [DEFAULT_PERSON_FORMAT]
    return []


def readiness_for_focus(focus: dict,
                        questions: list[dict],
                        formats: list[str] | None = None) -> list[dict]:
    """Readiness cards for one focus — the Studio's uniform adapter.

    Book-deliverable focuses return ``[]``: book.compute_books() already owns
    that view and duplicating it would put two different readiness numbers on
    one screen. Everything else gets one card per format, each tagged with
    ``focus_id`` so the caller can group without a second lookup.
    """
    deliverable = str(focus.get("deliverable", "")).lower().strip()
    if deliverable in book_deliverables():
        return []

    wanted_formats = formats if formats is not None else default_formats_for_focus(focus)
    categories = list(focus.get("categories", []) or [])

    cards: list[dict] = []
    for format_id in wanted_formats:
        framework = format_frameworks.get_or_none(str(format_id))
        if not isinstance(framework, dict) or not framework.get("slots"):
            continue
        card = compute_readiness(framework, categories, questions)
        card["focus_id"] = focus.get("id")
        cards.append(card)
    return cards


# ---------------------------------------------------------------------------
# CLI helper (called from lifehug.py's `artifact readiness` wrapper)
# ---------------------------------------------------------------------------

GAP_TEXT_WIDTH = 80


def _truncate(text: str, width: int = GAP_TEXT_WIDTH) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= width else text[: width - 1] + "…"


def load_bank_questions() -> list[dict]:
    """Parse the question bank; an absent bank reads as no questions."""
    if not QUESTIONS_FILE.exists():
        return []
    return parse_questions(QUESTIONS_FILE.read_text(encoding="utf-8"))


def print_readiness(format_id: str,
                    categories: list[str],
                    questions: list[dict] | None = None) -> int:
    """`lifehug.py artifact readiness --format letter --subject Mom`.

    Read-only and informational: always exits 0, including when the format has
    no framework yet (that's a "nothing researched for this format", not an
    error the caller should branch on).
    """
    questions = load_bank_questions() if questions is None else questions
    framework = format_frameworks.get_or_none(str(format_id))
    if not isinstance(framework, dict) or not framework.get("slots"):
        print(f"No format framework with slots for '{format_id}' — nothing to score.")
        return 0

    result = compute_readiness(framework, categories, questions)
    label = framework.get("label") or format_id
    scope = ",".join(str(c).upper() for c in (categories or [])) or "(no categories)"
    print(f"{label} readiness — categories {scope}\n")
    for slot in result["slots"]:
        box = "[x]" if slot["filled"] else "[ ]"
        print(f"{box} {slot['label']} — matched {len(slot['matched'])}/{slot['needed']}")
        for gap in slot["gap_questions"]:
            print(f"  ○ {gap['id']} {_truncate(gap['text'])}")
    print(f"\n{result['verdict']} — {result['filled_slots']}/{result['total_slots']} slots")
    return 0
