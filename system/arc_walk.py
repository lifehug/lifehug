#!/usr/bin/env python3
"""Runtime authority for the registered Arc Walk Interaction (v193).

Arc walking is the fourth child of Conversation (`interactions/README.md`
§ "The child-interaction paradigm"). Its one goal: **work a set of open
questions casually, in resumable episodes**. Pressing Play on a focus, a
chapter, or a book is a commitment to answer a lot in one sitting; this
module builds the map that conversation walks.

Everything here is pure in the sense the planner is: no writes, no model
calls, no lifecycle. The only reads are the guarded, optional ones
``question_planner.enriched_pending_questions`` already performs (answer
dates, the quality profile) — exactly as ``conversation.asking_supply_
selection`` inherits them — and every one degrades to a default rather
than raising.

Contract: ``docs/pr-specs/arc-walk-interaction.md``.
Decision: ``docs/adr/0023-arc-walking.md``.
"""

from __future__ import annotations

import argparse
import json
import re
import sys

import conversation
import question_planner


class ArcWalkError(ValueError):
    """A target, plan, or stage contract is unusable."""


# --------------------------------------------------------------------------
# The target (Design §B.1)
# --------------------------------------------------------------------------

#: The closed set of Play-target kinds an arc plan can be built for
#: (platform issue #570 §1's `kind`, restricted to the ones that carry a SET
#: of questions — a single `question` Play is an ordinary chat and needs no
#: plan at all).
ARC_TARGET_KINDS = ("focus", "chapter", "book", "category", "queue")
MAX_TARGET_LABEL_CHARS = 120


def normalize_target(value: object) -> dict:
    """Normalize a Play target into the four keys a plan needs.

    ``{"kind", "ref", "label", "categories"}``. ``kind`` must be an exact
    member of :data:`ARC_TARGET_KINDS` (no case-fold, no fuzzy). Categories
    are bank category letters, trimmed, deduplicated, order-preserved.

    Raises :class:`ArcWalkError` on an unknown kind, a missing ref, or an
    empty category set — a target nobody can enumerate is a caller bug, not
    something to degrade around (the ``opening_question`` precedent from
    v189/v190).
    """
    if not isinstance(value, dict):
        raise ArcWalkError("target must be an object")
    kind = str(value.get("kind") or "").strip()
    if kind not in ARC_TARGET_KINDS:
        raise ArcWalkError(f"unknown target kind: {kind!r}")
    ref = str(value.get("ref") or "").strip()
    if not ref:
        raise ArcWalkError("target requires a ref")
    raw_categories = value.get("categories") or ()
    if isinstance(raw_categories, str):
        raw_categories = [raw_categories]
    categories: list[str] = []
    for item in raw_categories:
        letter = str(item or "").strip()
        if letter and letter not in categories:
            categories.append(letter)
    if not categories:
        raise ArcWalkError("target requires at least one category")
    label = str(value.get("label") or ref).strip()[:MAX_TARGET_LABEL_CHARS]
    return {
        "kind": kind,
        "ref": ref,
        "label": label,
        "categories": tuple(categories),
    }


# --------------------------------------------------------------------------
# Episode size (Design §B.3)
# --------------------------------------------------------------------------

#: Owner ruling 3 — "episodes, not marathons", sized by tier. These ship
#: BOTH as constants here and as `knob.episode_size_*` in the interaction
#: manifest; `test_episode_manifest_knobs_match_the_module_constants` pins
#: them equal, so tuning the knob and tuning the constant are one edit.
EPISODE_SIZES = {"basic": 4, "standard": 6, "extreme": 8}
DEFAULT_EPISODE_SIZE = 6
MIN_EPISODE_SIZE = 1
#: Well under `knob.conversation_turn_cap_exchanges` (25), so an episode
#: always closes on its own terms rather than being cut off by the cap
#: (issue #570 risk 2).
MAX_EPISODE_SIZE = 12
#: `build_queue`'s same-category streak cap, applied here as a re-ordering
#: rule rather than a sampling filter. AST-pinned against `lifehug.py`'s
#: `planner-queue --arc-max` default so the weekly loop and the episode
#: cannot drift (recurring-defect doctrine).
DEFAULT_ARC_MAX = 2


def _manifest_episode_sizes() -> dict[str, int]:
    """`knob.episode_size_<tier>` from the interaction manifest, or {}.

    The `knob.asking_supply_top_k` pattern (`conversation.asking_supply_
    selection`): the package manifest is the tunable surface, the module
    constants are the floor, and a missing/corrupt manifest degrades to the
    constants rather than raising on a read path a Play touches.
    """
    try:
        import interaction_registry  # noqa: PLC0415

        manifest = interaction_registry.load_interaction_manifest("arc_walk")
    except Exception:  # noqa: BLE001 — a bad manifest never breaks a Play
        return {}
    sizes: dict[str, int] = {}
    for tier in EPISODE_SIZES:
        raw = manifest.get(f"knob.episode_size_{tier}")
        # `lifehug_core._parse_simple_yaml` returns every scalar as a STRING
        # (the flat-YAML subset does no typing), so coerce here rather than
        # silently ignoring the knob — the bug `conversation`'s
        # `knob.asking_supply_top_k` read has, which is why that knob never
        # actually applies. Deliberately not fixed there in this PR.
        try:
            value = int(str(raw).strip())
        except (TypeError, ValueError):
            continue
        if MIN_EPISODE_SIZE <= value <= MAX_EPISODE_SIZE:
            sizes[tier] = value
    return sizes


def episode_size_for(tier: object, *, override: object = None) -> int:
    """How many questions one episode of this target's plan walks.

    ``override`` wins when it is an ``int`` inside
    ``[MIN_EPISODE_SIZE, MAX_EPISODE_SIZE]``; anything else is ignored
    rather than raising (a caller passing garbage still gets a walkable
    episode). An unknown or blank ``tier`` falls back to
    :data:`DEFAULT_EPISODE_SIZE` — a focus whose tier nobody set is still
    walkable.
    """
    if isinstance(override, bool):
        override = None
    if isinstance(override, int) and MIN_EPISODE_SIZE <= override <= MAX_EPISODE_SIZE:
        return override
    key = str(tier or "").strip()
    sizes = {**EPISODE_SIZES, **_manifest_episode_sizes()}
    return int(sizes.get(key, DEFAULT_EPISODE_SIZE))


# --------------------------------------------------------------------------
# The plan (Design §B.2)
# --------------------------------------------------------------------------


def _plan_weight(row: dict, policy: dict) -> float:
    """`build_queue.weighted_pick`'s own weight expression, verbatim.

    `question_planner.build_queue` feeds exactly this to `rng.choices`; an
    episode needs an ORDER rather than a sample, so the same weights sort
    instead. `test_build_arc_plan_weight_expression_matches_build_queue`
    pins the two by AST, so a lane-policy change fails the build instead of
    drifting.
    """
    return max(float(row.get("weight", 1.0) or 0.0), 0.0001) * (
        float(policy["objective_boost"]) if row.get("objective") else 1.0
    )


def intent_note(card: object) -> str | None:
    """A short bridge note from one arc card, or None.

    The card's FIRST intent object rendered short — its ``note``, else its
    ``slot``, else its ``kind`` — where ``kind`` must be a member of
    ``conversation.ARC_INTENT_KINDS`` (imported, never re-listed). No card,
    no intents, or an unknown kind gives ``None``: the plan carries a
    planner's suggestion or nothing, never an invention.

    Card LIVENESS is deliberately NOT re-derived here — `arc_planner.
    live_card` owns that rule and the caller applies it.
    """
    if not isinstance(card, dict):
        return None
    intents = card.get("intents")
    if not isinstance(intents, list) or not intents:
        return None
    first = intents[0]
    if not isinstance(first, dict):
        return None
    if str(first.get("kind") or "") not in conversation.ARC_INTENT_KINDS:
        return None
    for key in ("note", "slot", "kind"):
        value = first.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _ordered_plan_rows(rows: list[dict], *, policy: dict, arc_max: int) -> list[dict]:
    """Weight-sorted, then re-ordered by `build_queue`'s streak cap.

    Greedy walk of the weight-sorted list: a question whose category equals
    the current streak category is DEFERRED once the streak has reached
    ``arc_max``, and the next eligible one is taken instead. When nothing
    else is eligible the deferred one is taken anyway — `build_queue`'s own
    last-resort ("caps exhausted, fill anyway").
    """
    sorted_rows = sorted(
        rows,
        key=lambda row: (
            -_plan_weight(row, policy),
            float(row.get("category_ratio", 0.0) or 0.0),
            question_planner.qid_key(str(row.get("id"))),
        ),
    )
    ordered: list[dict] = []
    remaining = list(sorted_rows)
    streak_category: str | None = None
    streak_count = 0
    cap = max(1, int(arc_max))
    while remaining:
        pick = None
        for row in remaining:
            if str(row.get("category")) == streak_category and streak_count >= cap:
                continue
            pick = row
            break
        if pick is None:  # last resort: the cap is exhausted, fill anyway
            pick = remaining[0]
        remaining.remove(pick)
        category = str(pick.get("category"))
        if category == streak_category:
            streak_count += 1
        else:
            streak_category, streak_count = category, 1
        ordered.append(pick)
    return ordered


def build_arc_plan(
    target: object,
    *,
    questions: list[dict],
    categories: dict,
    coverage: dict,
    tier: object,
    episode_size: object = None,
    focus_index: dict | None = None,
    objectives: object = (),
    cards: object = (),
    declined_question_ids: object = (),
    arc_max: int = DEFAULT_ARC_MAX,
) -> dict:
    """The map an episode walks — recomputed at every Play, never persisted.

    Owner ruling 4: answered questions fall out because the plan is rebuilt
    from the bank, so nothing needs storing except the engine's existing
    ``declined_question_ids`` (ADR 0016).

    Ordering REUSES the planner and re-derives nothing:
    ``question_planner.enriched_pending_questions`` supplies the one
    ranking authority (focus weighting, quality multiplier, rumination
    cooldown, the escalation gate, love-map staleness), restricted to the
    target's categories; ``_plan_weight`` is ``build_queue``'s own weight
    expression; ``_ordered_plan_rows`` is its ``arc_max`` streak cap.

    ``plan_n`` counts EVERY question in the target's categories and
    ``answered_k`` how many are already answered — "k of N" is a bank fact
    (platform issue #570 §3) — so
    ``len(plan["questions"]) == plan_n - answered_k`` holds by construction.
    """
    normalized = normalize_target(target)
    target_categories = set(normalized["categories"])
    in_target = [
        q for q in questions if str(q.get("category")) in target_categories
    ]
    plan_n = len(in_target)
    answered_k = sum(1 for q in in_target if q.get("answered"))

    declined = {str(qid) for qid in (declined_question_ids or ()) if qid}
    rows = question_planner.enriched_pending_questions(
        questions, categories, coverage, list(objectives or []), focus_index
    )
    rows = [
        row
        for row in rows
        if str(row.get("category")) in target_categories
        and str(row.get("id")) not in declined
    ]
    policy = dict(question_planner.DEFAULT_LANE_POLICY)
    ordered = _ordered_plan_rows(rows, policy=policy, arc_max=arc_max)

    by_question: dict[str, dict] = {}
    for card in cards or ():
        if isinstance(card, dict) and card.get("question_id"):
            by_question.setdefault(str(card["question_id"]), card)

    planned = [
        {
            "id": str(row.get("id")),
            "text": str(row.get("text") or ""),
            "category": str(row.get("category")),
            "intent": intent_note(by_question.get(str(row.get("id")))),
        }
        for row in ordered
    ]
    return {
        "target": normalized,
        "focus_label": normalized["label"],
        "questions": planned,
        "episode_size": episode_size_for(tier, override=episode_size),
        "plan_n": plan_n,
        "answered_k": answered_k,
    }


def plan_question_ids(plan: dict) -> tuple[str, ...]:
    """The ordered OPEN question ids this plan carries."""
    rows = (plan or {}).get("questions") or []
    return tuple(str(row["id"]) for row in rows if isinstance(row, dict) and row.get("id"))


def episode_questions(plan: dict) -> list[dict]:
    """The first ``episode_size`` plan questions — today's slice."""
    rows = (plan or {}).get("questions") or []
    size = int((plan or {}).get("episode_size") or DEFAULT_EPISODE_SIZE)
    return list(rows[: max(0, size)])


def render_agenda(plan: dict) -> str:
    """``{agenda}`` — the episode's question texts, numbered, one per line.

    The intent, when the arc planner had one for that question, rides along
    in parentheses as a bridge suggestion. Empty string when the episode has
    nothing in it (an exhausted target), so the leaf renders honestly rather
    than promising an agenda that does not exist.
    """
    lines = []
    for index, row in enumerate(episode_questions(plan), start=1):
        text = str(row.get("text") or "").strip()
        intent = row.get("intent")
        suffix = f" ({intent})" if isinstance(intent, str) and intent.strip() else ""
        lines.append(f"{index}. [{row.get('id')}] {text}{suffix}")
    return "\n".join(lines)


# --------------------------------------------------------------------------
# Stage and the question on the table (Design §B.4/§B.5)
# --------------------------------------------------------------------------

#: The three `{arc_stage}` values the leaf is keyed on.
VALID_ARC_STAGES = frozenset({"open", "walk", "close"})


def asked_question_id(turn: object) -> str | None:
    """The qid the assistant turn ASKED — the one naming of an existing concept.

    ``held_question_id`` is what the MODEL returns when it asked a question
    from ASKING_SUPPLY; the ENGINE writes that same qid onto the assistant
    turn as ``turn["question_id"]`` (``conversation_delivery``'s
    ``lifehug_turn`` literal); the hosted platform calls that field
    ``stamped_question_id``. All three are ONE concept. This function is the
    reader; no second field, session key, or lifecycle state is added.

    A ``user`` turn's ``question_id`` is what the answer was FILED against,
    not what was asked, so only ``role == "lifehug"`` turns answer here.
    """
    if not isinstance(turn, dict) or turn.get("role") != "lifehug":
        return None
    qid = turn.get("question_id")
    if not isinstance(qid, str):
        return None
    return qid.strip() or None


def answered_plan_question_ids(session: dict, plan: dict) -> tuple[str, ...]:
    """Distinct plan qids this session's USER turns are stamped with, in order.

    The episode's own progress — a transcript fact, never a stored counter
    (the `focus_stage_for_session` precedent).
    """
    wanted = set(plan_question_ids(plan))
    seen: list[str] = []
    for turn in (session or {}).get("turns") or []:
        if not isinstance(turn, dict) or turn.get("role") != "user":
            continue
        qid = turn.get("question_id")
        if not isinstance(qid, str):
            continue
        qid = qid.strip()
        if qid and qid in wanted and qid not in seen:
            seen.append(qid)
    return tuple(seen)


def arc_stage_for_session(
    session: dict, plan: dict, *, user_leaving: bool = False
) -> str:
    """Derive ``{arc_stage}`` from the transcript alone — no new session field.

    ``user_leaving`` (the router's "I need to go" signal, Design §A.2) wins
    over everything: an episode a person is walking out of closes, however
    far in it got. Otherwise the first reply is ``open`` (the agenda
    announcement lives there and nowhere else), a full episode is ``close``,
    and everything between is ``walk``.
    """
    if user_leaving:
        return "close"
    turns = (session or {}).get("turns") or []
    if not any(isinstance(t, dict) and t.get("role") == "lifehug" for t in turns):
        return "open"
    size = int((plan or {}).get("episode_size") or DEFAULT_EPISODE_SIZE)
    if len(answered_plan_question_ids(session, plan)) >= size:
        return "close"
    return "walk"


def question_on_the_table(session: dict, plan: dict) -> str | None:
    """The qid a user turn arriving NOW would be answering (owner ruling 5).

    The LAST assistant turn's asked qid when it is a plan question, else the
    first plan question this session has not answered yet, else ``None`` (an
    exhausted episode has nothing on the table).
    """
    ids = plan_question_ids(plan)
    wanted = set(ids)
    for turn in reversed((session or {}).get("turns") or []):
        qid = asked_question_id(turn)
        if qid:
            return qid if qid in wanted else None
    answered = set(answered_plan_question_ids(session, plan))
    for qid in ids:
        if qid not in answered:
            return qid
    return None


# --------------------------------------------------------------------------
# The closed validator for the one additive field (Design §B.6)
# --------------------------------------------------------------------------


def validate_answered_question_id(value: object, *, plan: dict) -> str | None:
    """Closed layer of the additive ``answered_question_id`` field.

    ``value`` is the structural layer's own output
    (``conversation_delivery._parse_answered_question_id`` — a trimmed,
    non-empty, length-capped string or ``None``) or any other untrusted
    shape (this function re-checks shape itself so it is safe standalone).

    Exact membership in the plan's OPEN question ids: no case-fold, no
    prefix match, no chain-root walking. A qid the plan does not carry drops
    to ``None`` — the package refuses to file an answer against a question
    this episode never put on the table, exactly as
    ``question_candidate.validate_placement`` refuses an off-roster
    category.

    PRIMARY ONLY (owner ruling 5, issue #570 risk 1): one qid, never a list.
    An answer covering two questions names the primary; the compiler already
    cross-links the rest by content.
    """
    if not isinstance(value, str):
        return None
    qid = value.strip()
    if not qid:
        return None
    return qid if qid in set(plan_question_ids(plan)) else None


# --------------------------------------------------------------------------
# Lints (Design §D)
# --------------------------------------------------------------------------

#: The seven `arc_walk_gates.*` classes, matching `lint_arc_reply`'s finding
#: ids minus the "arc_walk." prefix.
ARC_WALK_LINT_CLASSES = (
    "agenda_announced_once",
    "agenda_never_repeated",
    "one_question_per_reply",
    "no_counters",
    "no_mechanism_talk",
    "close_summarizes",
    "no_pressure",
)

#: The agenda's invariant anchor (owner ruling 2): a sentence pairing a
#: TODAY cue with a HEARING cue, in either order. The model varies the
#: connective tissue, never the move.
_TODAY_CUE = r"(?:today|this time|this session|right now)"
_HEARING_CUE = (
    r"(?:love to hear|like to hear|want to hear|hoping to hear|talk about|"
    r"go through|get into|walk through|cover)"
)
_AGENDA_MARKER_RE = re.compile(
    rf"\b{_TODAY_CUE}\b[^.!?]*\b{_HEARING_CUE}\b"
    rf"|\b{_HEARING_CUE}\b[^.!?]*\b{_TODAY_CUE}\b",
    re.IGNORECASE,
)
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")
#: arc_walk.no_counters — "never 'you still have N'" (owner ruling 3).
_COUNTER_RES = (
    re.compile(r"\b\d+\s*(?:of|/|out of)\s*\d+\b", re.IGNORECASE),
    re.compile(
        r"\b(?:\d+|one|two|three|four|five|six|seven|eight|nine|ten|a couple|"
        r"a few)\s+(?:more|left|remaining|to go)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:questions?|things?)\s+(?:left|remaining|to go|outstanding)\b",
        re.IGNORECASE,
    ),
    re.compile(r"\byou\s+(?:still\s+have|have)\s+\w+\s+(?:more|left)\b", re.IGNORECASE),
)
#: arc_walk.no_mechanism_talk — the plan is machinery; narrating it is not
#: conversation.
_MECHANISM_PHRASES = (
    "the plan",
    "my plan",
    "the agenda",
    "the queue",
    "question bank",
    "i'll file this",
    "i will file this",
    "the system will",
    "arc card",
    "arc plan",
    "the next item",
    "on my list",
)
#: arc_walk.no_pressure — "no checklist, no streak, never 'unfinished'".
_PRESSURE_PHRASES = (
    "unfinished",
    "you didn't",
    "you did not",
    "still need to",
    "need to finish",
    "finish the rest",
    "streak",
    "fell behind",
    "falling behind",
    "incomplete",
)
#: arc_walk.close_summarizes — a close names what was covered AND says the
#: rest waits. Both, because a close that says what happened but not that
#: the rest waits is the "missing something if they leave" failure owner
#: ruling 1 forbids.
_COVERED_RES = (
    re.compile(
        r"\bwe\s+(?:covered|got|talked about|went through|touched on|did)\b",
        re.IGNORECASE,
    ),
    re.compile(r"\b(?:that's|this is)\s+(?:a\s+)?good\s+(?:stretch|amount)\b", re.IGNORECASE),
)
_WAITS_RES = (
    re.compile(r"\bwhenever\s+you\s+(?:like|want|feel)\b", re.IGNORECASE),
    re.compile(r"\b(?:will|can)\s+keep\b", re.IGNORECASE),
    re.compile(r"\b(?:the\s+)?rest\s+(?:waits|will wait|is there)\b", re.IGNORECASE),
    re.compile(r"\bno\s+rush\b", re.IGNORECASE),
    re.compile(r"\bwhen\s+you\s+want\s+(?:to|them|it)\b", re.IGNORECASE),
    re.compile(r"\bany\s+time\s+you\s+(?:like|want)\b", re.IGNORECASE),
)


def _sentences(text: str) -> list[str]:
    return [s.strip() for s in _SENTENCE_SPLIT_RE.split((text or "").strip()) if s.strip()]


def _span_of(text: str, needle: str) -> list[int]:
    clean = (needle or "").strip()
    start = text.find(clean) if clean else -1
    if start == -1:
        return [0, len(text)]
    return [start, start + len(clean)]


def _any_match(patterns, text: str):
    for pattern in patterns:
        match = pattern.search(text)
        if match:
            return match
    return None


def lint_arc_reply(
    text: str, *, stage: str, agenda_announced: bool = False
) -> list[dict]:
    """Deterministic findings for the seven ``arc_walk_gates.*`` classes.

    Pure — no model, no I/O. ``stage`` is the same ``{arc_stage}`` value the
    turn-instructions leaf receives (``"open" | "walk" | "close"``); an
    unrecognized stage is treated as ``"walk"`` (fail toward the strictest
    ordinary rule: no agenda, no counters). ``agenda_announced`` is the
    caller's own fact — has this episode already announced its agenda — and
    is what makes a second ``open``-stage announcement a repeat.

    Findings share ``conversation_lints.lint_turn``'s shape —
    ``{"lint": "<id>", "detail": "...", "span": [start, end]}`` — so a
    caller can merge them with the inherited Conversation findings
    uniformly.
    """
    body = text or ""
    if stage not in VALID_ARC_STAGES:
        stage = "walk"
    findings: list[dict] = []
    sentences = _sentences(body)
    agenda_sentences = [s for s in sentences if _AGENDA_MARKER_RE.search(s)]

    if stage == "open" and not agenda_announced:
        if len(agenda_sentences) != 1:
            findings.append({
                "lint": "arc_walk.agenda_announced_once",
                "detail": "the opener must announce the agenda exactly once, as exactly one sentence",
                "span": [0, len(body)],
            })
    elif agenda_sentences:
        findings.append({
            "lint": "arc_walk.agenda_never_repeated",
            "detail": "the agenda is announced once, on the opener, and never again",
            "span": _span_of(body, agenda_sentences[0]),
        })

    if body.count("?") > 1:
        findings.append({
            "lint": "arc_walk.one_question_per_reply",
            "detail": "at most one question per reply — an episode is a conversation, not an interview",
            "span": [0, len(body)],
        })

    counter = _any_match(_COUNTER_RES, body)
    if counter:
        findings.append({
            "lint": "arc_walk.no_counters",
            "detail": f"coverage counting is never spoken: {counter.group(0)!r}",
            "span": [counter.start(), counter.end()],
        })

    lowered = body.lower()
    for phrase in _MECHANISM_PHRASES:
        index = lowered.find(phrase)
        if index != -1:
            findings.append({
                "lint": "arc_walk.no_mechanism_talk",
                "detail": f"mechanism talk: {phrase!r}",
                "span": [index, index + len(phrase)],
            })
            break

    for phrase in _PRESSURE_PHRASES:
        index = lowered.find(phrase)
        if index != -1:
            findings.append({
                "lint": "arc_walk.no_pressure",
                "detail": f"nothing waiting is a failure to report: {phrase!r}",
                "span": [index, index + len(phrase)],
            })
            break

    if stage == "close":
        covered = _any_match(_COVERED_RES, body)
        waits = _any_match(_WAITS_RES, body)
        if covered is None or waits is None or "?" in body:
            findings.append({
                "lint": "arc_walk.close_summarizes",
                "detail": "a close names what was covered, says the rest waits, and asks nothing",
                "span": [0, len(body)],
            })

    return findings


# --------------------------------------------------------------------------
# The read-only CLI driver: `lifehug.py arc-plan-target` (Design §E)
# --------------------------------------------------------------------------


def _target_from_roadmap(kind: str, ref: str) -> tuple[dict, str]:
    """(target dict, tier) for a vault-resolved target. Reads only."""
    questions, _categories, _coverage = question_planner.load_question_state()
    roadmap = question_planner.resolve_roadmap(questions)
    focuses = roadmap.get("focuses") or []
    if kind in ("focus", "book"):
        focus = next(
            (f for f in focuses if str(f.get("id")) == ref or str(f.get("label")) == ref),
            None,
        )
        if focus is None:
            raise ArcWalkError(f"no focus {ref!r} in the roadmap")
        return (
            {
                "kind": kind,
                "ref": str(focus.get("id") or ref),
                "label": str(focus.get("label") or ref),
                "categories": list(focus.get("categories") or []),
            },
            str(focus.get("tier") or ""),
        )
    if kind in ("category", "chapter"):
        letter = ref.strip()
        owner = next(
            (f for f in focuses if letter in (f.get("categories") or [])), {}
        )
        return (
            {
                "kind": kind,
                "ref": letter,
                "label": str(owner.get("label") or letter),
                "categories": [letter],
            },
            str(owner.get("tier") or ""),
        )
    # queue: whatever categories this week's queue actually covers. The
    # queue reader is the arc planner's own (`load_queue`/`queued_items`) —
    # never a second parse of state/question_queue.json.
    from arc_planner import load_queue, queued_items  # noqa: PLC0415

    letters: list[str] = []
    for item in queued_items(load_queue()):
        letter = str(item.get("category") or "").strip()
        if letter and letter not in letters:
            letters.append(letter)
    return (
        {"kind": "queue", "ref": "queue", "label": "this week", "categories": letters},
        "standard",
    )


def plan_for_target(
    kind: str, ref: str, *, episode_size: object = None
) -> dict:
    """Resolve a target from the vault and build its plan. No writes."""
    target, tier = _target_from_roadmap(kind, ref)
    questions, categories, coverage = question_planner.load_question_state()
    focuses = question_planner.resolve_roadmap(questions).get("focuses", [])
    focus_index = question_planner.build_focus_index(focuses, questions)
    try:
        cards = conversation.load_arc_cards().get("cards") or []
    except Exception:  # noqa: BLE001 — a cold vault plans fine without cards
        cards = []
    return build_arc_plan(
        target,
        questions=questions,
        categories=categories,
        coverage=coverage,
        tier=tier,
        episode_size=episode_size,
        focus_index=focus_index,
        cards=cards,
    )


def describe_plan(plan: dict) -> list[str]:
    target = plan["target"]
    lines = [
        f"{target['kind']}: {plan['focus_label']} "
        f"({', '.join(target['categories'])})",
        f"{plan['answered_k']} of {plan['plan_n']} answered — "
        f"{len(plan['questions'])} open, episode of {plan['episode_size']}",
        "",
        "Agenda:",
    ]
    agenda = render_agenda(plan)
    lines.extend(agenda.splitlines() if agenda else ["  (nothing open — this target is done)"])
    return lines


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Plan an arc-walk episode (read-only)")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--focus", help="focus id or label")
    group.add_argument("--category", help="bank category letter")
    group.add_argument("--chapter", help="bank category letter (a book chapter)")
    group.add_argument("--book", help="focus id or label of a book focus")
    group.add_argument("--queue", action="store_true", help="this week's queue")
    parser.add_argument("--episode-size", type=int, default=None)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    if args.focus:
        kind, ref = "focus", args.focus
    elif args.book:
        kind, ref = "book", args.book
    elif args.chapter:
        kind, ref = "chapter", args.chapter
    elif args.category:
        kind, ref = "category", args.category
    else:
        kind, ref = "queue", "queue"

    try:
        plan = plan_for_target(kind, ref, episode_size=args.episode_size)
    except ArcWalkError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(plan, indent=2, sort_keys=True))
    else:
        print("\n".join(describe_plan(plan)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
