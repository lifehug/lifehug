#!/usr/bin/env python3
"""Runtime authority for the registered Timeline Interaction (v195).

Placing a memory in time is the fifth child of Conversation
(`interactions/README.md` § "The child-interaction paradigm"). Its one goal:
**place a memory in time without ever demanding a year.**

Everything here is pure — no writes, no model calls, no lifecycle. The
elicitation ladder, the anchors, the stage, the closed validator and the five
lints are all deterministic functions over data the caller supplies, exactly
as `arc_walk` is.

The ladder is the sourced one (`system/research/chronology.md` §6):
content → residence → role → parallel domain → sequence → personal landmark →
season → offered bounds → convergence → defer. It ascends **only while
cheap** and stops at the first rung the person can hold without hedging — a
hedged month is worse than a confident season (Huttenlocher, Hedges &
Bradburn 1990).

Contract: ``docs/pr-specs/timeline-chronology.md``.
Decision: ``docs/adr/0024-chronology-with-basis.md``.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import NamedTuple

_SYSTEM_DIR = Path(__file__).resolve().parent
if str(_SYSTEM_DIR) not in sys.path:
    sys.path.insert(0, str(_SYSTEM_DIR))

import chronology as chrono  # noqa: E402
from lifehug_core import fill_how_words_arrive, now_utc  # noqa: E402


class TimelineInteractionError(ValueError):
    """A stage, probe, or placement contract is unusable."""


# --------------------------------------------------------------------------
# The elicitation playbook (research/chronology.md §6)
# --------------------------------------------------------------------------

#: Ordered; `cost` is the rung, and the ladder ascends only while cheap.
#: `needs_anchor` marks the rungs that are pointless without a landmark the
#: person already supplied — van der Vaart & Glasner (2011) found landmark
#: prompting works when the landmark is important, domain-related, and
#: PERSONAL, and does nothing when it is not.
PLAYBOOK_STEPS = (
    {"step": "content", "cost": 1, "needs_anchor": False},
    {"step": "residence", "cost": 2, "needs_anchor": False},
    {"step": "role", "cost": 3, "needs_anchor": False},
    {"step": "parallel_domain", "cost": 4, "needs_anchor": False},
    {"step": "sequence", "cost": 5, "needs_anchor": True},
    {"step": "landmark", "cost": 6, "needs_anchor": True},
    {"step": "season", "cost": 7, "needs_anchor": False},
    {"step": "bounds", "cost": 8, "needs_anchor": False},
    {"step": "convergence", "cost": 9, "needs_anchor": False},
    {"step": "defer", "cost": 10, "needs_anchor": False},
)
PLAYBOOK_ORDER = tuple(row["step"] for row in PLAYBOOK_STEPS)
_STEP_BY_NAME = {row["step"]: row for row in PLAYBOOK_STEPS}

#: The probe text per rung. `{label}` is the unknown's own SUBJECT, `{anchor}`
#: the landmark. None of these is a year question — and none of them is
#: abstract: every rung NAMES the thing being placed (v196, owner-set: "I have
#: no idea what that means or what we're talking about"). Rung 1 is deliberately
#: not about time at all — dating is reconstructive inference, so content comes
#: first (Friedman 1993) — and it is the ONE rung that does not need the
#: subject to already be known, which is why it is skipped the moment we have
#: a titled subject or a landmark to anchor against.
PROBE_TEXTS = {
    "content": "Tell me about {label} — just the moment itself, however it comes.",
    "residence": "Where were you living around the time of {label}?",
    "role": "What were you doing for work around the time of {label}?",
    "parallel_domain": "What else was going on in your life around {label} — "
                       "home, work, anyone new around?",
    "sequence": "{label} — was that before or after {anchor}?",
    "landmark": "Had {anchor} happened yet, by the time of {label}?",
    "season": "{label} — what was the weather doing, what time of year does it "
              "feel like?",
    "bounds": "Would you say {label} sits inside one stretch, or is "
              "\u201csomewhere in a couple of years\u201d more honest?",
    "convergence": "That's enough to place it — does that sound right to you?",
    "defer": "No rush at all — find out whenever you like and tell me then.",
}

#: The OPENING probe for the unknown kinds that are not a single moment. Each
#: names its own subject and asks one question; the `_anchored` variant is used
#: when the person has already given us a landmark to hang it on. These replace
#: the ladder's first rung for their kind — the ladder itself is unchanged and
#: takes over from the second probe onward.
KIND_OPENERS = {
    "moment": {
        "step": "content", "cost": 1,
        "anchored_step": "sequence", "anchored_cost": 5,
        # Timeline Fix 09 (lifehug-platform#767, owner-ruled 2026-08-29): a
        # person presses Play on a moment they can already see on the page —
        # the content is known, the missing thing is WHEN. This overrides the
        # v196 content-first rule for exactly this path; the anchored variant
        # below was already a WHEN question and is unchanged.
        "text": "About when was {label}? A year, how old you were, or where "
                "you were living is enough.",
        "anchored": "{label} — was that before or after {anchor}?",
    },
    "period_bound": {
        "step": "bounds", "cost": 2,
        "text": "When did {label} begin and end?",
        "anchored": "When did {label} end — before or after {anchor}?",
    },
    "place_span": {
        "step": "residence", "cost": 2,
        "text": "When did you live in {label} — moving in to moving out?",
        "anchored": "Were you living in {label} before or after {anchor}?",
    },
    "era_gap": {
        "step": "parallel_domain", "cost": 3,
        "text": "What was going on in your life in the stretch between "
                "{between_first} and {between_second}?",
        "anchored": "Between {between_first} and {between_second} — where were "
                    "you living by then?",
    },
    "date_contradiction": {
        "step": "convergence", "cost": 4,
        "text": "Two accounts put {label} in different places in time — which "
                "one feels right to you?",
        "anchored": "Two accounts disagree about {label} — was it before or "
                    "after {anchor}?",
    },
}

#: The keystone's own question, by anchor kind. A star that says "one answer
#: would place 23 more things" and asks nothing is not a question (v196,
#: owner-set).
KEYSTONE_PROBES = {
    "period": {"step": "bounds", "cost": 2,
               "text": "When did {label} begin and end?",
               "anchored": "When did {label} begin — before or after {anchor}?"},
    "entity": {"step": "landmark", "cost": 3,
               "text": "When did {label} first come into your life?",
               "anchored": "Did {label} come into your life before or after "
                           "{anchor}?"},
    "event": {"step": "sequence", "cost": 3,
              "text": "When did {label} happen?",
              "anchored": "{label} — was that before or after {anchor}?"},
}

#: How precise this kind of unknown needs to be before the ladder stops. A
#: gap between two eras needs a year; a thin lineup only needs an era. Nothing
#: is ever pushed past its own slot's requirement (stop rule, §6.10).
TARGET_GRANULARITY = {
    "era_gap": "year",
    "moment": "year",
    "period_bound": "year",
    "place_span": "era",
    "date_contradiction": "season",
}
DEFAULT_TARGET_GRANULARITY = "year"


def _anchor_rows(anchors: object) -> list[dict]:
    """Normalize an anchor index (dict) or a sequence into ordered rows."""
    rows: list[dict] = []
    if isinstance(anchors, dict):
        items = anchors.items()
    else:
        items = [(str((row or {}).get("key") or ""), row) for row in (anchors or ())
                 if isinstance(row, dict)]
    for key, value in items:
        if not isinstance(value, dict):
            continue
        record = chrono.from_dict(value.get("date"))
        rows.append({
            "key": str(key or value.get("key") or ""),
            "label": str(value.get("label") or key or "").strip(),
            "kind": str(value.get("kind") or "landmark"),
            "date": record,
        })
    order = {"birth": 0, "residence": 1, "period": 2, "landmark": 3}
    rows.sort(key=lambda row: (order.get(row["kind"], 9),
                               chrono.year_of(row["date"]) if row["date"] else 9999,
                               row["key"]))
    return [row for row in rows if row["key"]]


#: O-E0a (lifehug-platform#686), REVISED by Timeline Fix 07 D1
#: (lifehug-platform#761, owner-ruled 2026-08-29). The structural anchors — a
#: residence or an era — are spans of the life axis, and sorting one against
#: another is a question a person can answer. A bare landmark MOMENT is not
#: structural, so it only qualifies when it is demonstrably about the same
#: subject, place or era (:func:`anchor_is_relevant`); "When did Childhood end
#: — before or after First big paycheck arrives by mail?" is what adjacency
#: without relevance produces.
_RELATIONAL_ELIGIBLE_KINDS = frozenset({"residence", "period"})
#: The two unknown kinds that must be sorted against structure.
_RELATIONAL_KINDS = frozenset({"place_span", "period_bound"})

#: **Birth is never an anchor, for anything.** The owner's ruling of
#: 2026-08-29 — *"obviously nothing can happen before my birth, so this is a
#: silly question. No questions should ever be asked before my birth"* —
#: REVERSES v236's carve-out that "a moment may legitimately sort against the
#: birthday". The origin of the coordinate system is not one of its landmarks.
NEVER_AN_ANCHOR_KINDS = frozenset({"birth"})

#: Words too common to prove two labels are about the same thing.
_RELEVANCE_STOPWORDS = frozenset({
    "the", "a", "an", "of", "in", "on", "at", "to", "and", "my", "your", "our",
    "years", "year", "time", "times", "when", "was", "were", "is", "it", "that",
    "this", "with", "for", "from", "by", "big", "first", "new", "old", "day",
})


def _relevance_tokens(text: object) -> set:
    return {
        word for word in re.findall(r"[a-z0-9]+", str(text or "").lower())
        if len(word) > 2 and word not in _RELEVANCE_STOPWORDS
    }


def anchor_is_relevant(unknown: object, anchor_row: object) -> bool:
    """Does this anchor SHARE a subject, a place or an era with the target?

    Timeline Fix 07 D5 (lifehug-platform#761). The anchor the founder was shown
    — *"before or after First big paycheck arrives by mail?"* — was picked by
    adjacency in a sorted list, and had nothing whatever to do with the thing
    being asked about. An anchor a person cannot relate to the target is worse
    than no anchor: it makes the question unanswerable AND makes the system
    look as though it thinks the two belong together.

    Relevant means one of two things, both checkable:

    * the anchor IS the target's own era or place (``period`` / ``slug`` /
      ``key``), or
    * their labels share a content word — the same person, place or thing
      named twice.
    """
    row = unknown if isinstance(unknown, dict) else {}
    anchor = anchor_row if isinstance(anchor_row, dict) else {}
    own = {str(row.get(name) or "").strip()
           for name in ("period", "slug", "key")} - {""}
    if str(anchor.get("key") or "").strip() in own:
        return True
    return bool(_relevance_tokens(row.get("label")) & _relevance_tokens(anchor.get("label")))


def anchor_for_probe(unknown: object, anchor_rows: object) -> dict | None:
    """The anchor whose RELATIONSHIP to this unknown makes it honest to name.

    `choose_probe` used to hand every anchored opener ``anchor_rows[0]`` — and
    `_anchor_rows` sorts birth first, because it dates everything else by
    arithmetic — so any unknown asked to sort itself against the person's own
    birth: *"Were you living in Mexico before or after when you were born?"*
    (lifehug-platform#686 defect 1), and later *"When did Switzerland Mission
    begin — before or after Author's birth?"* (lifehug-platform#761 D1).

    Three filters, in order, and every one of them can leave the set empty —
    ``None`` is a first-class answer and means *ask the unanchored question*:

    1. **Never the birth.** The origin is not a landmark to sort against, for
       ANY unknown kind (Timeline Fix 07 D1, owner-ruled). This reverses the
       v236 carve-out that let a `moment` anchor on the birthday.
    2. **Never itself** — an era is not asked whether it came before itself.
    3. **Never something unrelated** (D5): a `place_span` or a `period_bound`
       sorts against STRUCTURE — another residence, another era — or against a
       landmark that is demonstrably about the same subject, place or era
       (:func:`anchor_is_relevant`). "When did Childhood end — before or after
       First big paycheck arrives by mail?" is what adjacency without
       relevance produces. The rule is deliberately NOT extended to a bare
       `moment` or a `date_contradiction`: ordering one memory against another
       is how people actually date them, and the ladder's `sequence` rung
       exists for exactly that.

    Within what survives: nearest by year to the unknown's own ``years`` hint
    (`timeline.unknown_years`) when it has one, otherwise `anchor_rows`' own
    order, which is already residence → period → landmark, then year, then key.
    """
    row = unknown if isinstance(unknown, dict) else {}
    rows = anchor_rows if isinstance(anchor_rows, list) else list(anchor_rows or ())
    kind = str(row.get("kind") or "")
    own_key = str(row.get("slug") or row.get("period") or row.get("key") or "").strip()
    eligible = [
        candidate for candidate in rows
        if candidate.get("kind") not in NEVER_AN_ANCHOR_KINDS
        and (not own_key or candidate.get("key") != own_key)
    ]
    if kind in _RELATIONAL_KINDS:
        eligible = [
            candidate for candidate in eligible
            if candidate.get("kind") in _RELATIONAL_ELIGIBLE_KINDS
            or anchor_is_relevant(row, candidate)
        ]
    if not eligible:
        return None
    hint_year = None
    years = row.get("years")
    if isinstance(years, (list, tuple)):
        for value in years:
            try:
                hint_year = int(value)
                break
            except (TypeError, ValueError):
                continue
    if hint_year is None:
        return eligible[0]
    return min(
        eligible,
        key=lambda r: (abs((chrono.year_of(r["date"]) if r.get("date") else 9999)
                           - hint_year),
                       r["key"]),
    )


def anchors_for_person(*, birth_date: object = None, periods: object = (),
                       places: object = (), events: object = (),
                       landmarks: object = None, people: object = ()) -> tuple[dict, ...]:
    """The person's own dated landmarks, ordered — the life-history calendar.

    Birthday first (it dates everything else by arithmetic), then residences
    with spans, then eras with spans, then dated landmark moments. Residence
    and role are the natural index of lifetime periods (Conway &
    Pleydell-Pearce 2000), which is why "when we lived in X" outperforms "what
    year".

    v217: `people` is the PERSON roster. A person's `born`/`died` enters as an
    anchor through `landmarks_interaction.anchors_from_people`, which is also
    where the one-anchor-per-fact precedence lives (a family landmark's birth
    date beats the roster's derived copy of it). This is what makes the
    `entity_date` unlock real.

    v197: `landmarks` is the filed answer set from the Landmarks Interaction
    (`landmarks_interaction.anchors_from_landmarks`'s output, or the raw store
    it takes). It enters FIRST, so a landmark the person stated outright wins
    over anything derived from a page, and it is what finally makes this
    function return a non-empty set for most people
    (`system/research/landmarks.md` §3.7).
    """
    rows: dict[str, dict] = {}
    filed = landmarks
    if isinstance(filed, dict) and any(
        isinstance(v, list) for v in filed.values()
    ):
        import landmarks_interaction as _li  # noqa: PLC0415

        filed = _li.anchors_from_landmarks(filed)
    for key, row in (filed or {}).items():
        if not isinstance(row, dict):
            continue
        record = chrono.from_dict(row.get("date"))
        if record is None:
            continue
        rows[str(key)] = {"label": str(row.get("label") or key),
                          "date": record,
                          "kind": str(row.get("kind") or "landmark")}
    if people:
        import landmarks_interaction as _li  # noqa: PLC0415

        for key, row in _li.anchors_from_people(people, landmarks).items():
            rows.setdefault(key, dict(row))
    birth = chrono.from_dict(birth_date) if birth_date is not None else None
    if birth is not None:
        rows["birth"] = {"label": "when you were born", "date": birth, "kind": "birth"}
    for place in places or ():
        record = chrono.from_dict((place or {}).get("date"))
        if record is None:
            continue
        key = str(place.get("slug") or place.get("key") or "").strip()
        if key:
            rows[key] = {"label": str(place.get("title") or place.get("label") or key),
                         "date": record, "kind": "residence"}
    for period in periods or ():
        record = chrono.from_dict((period or {}).get("date"))
        if record is None:
            continue
        key = str(period.get("slug") or "").strip()
        if key:
            rows[key] = {"label": str(period.get("name") or key), "date": record,
                         "kind": "period"}
    for event in events or ():
        record = chrono.from_dict((event or {}).get("date"))
        if record is None:
            continue
        key = str(event.get("key") or event.get("source_short") or "").strip()
        label = str(event.get("title") or event.get("description") or key).strip()
        if key:
            rows.setdefault(key, {"label": label, "date": record, "kind": "landmark"})
    return tuple(_anchor_rows(rows))


def render_anchors(anchors: object, *, limit: int = 8) -> str:
    """The `{anchors}` block: the landmarks this person actually supplied."""
    rows = _anchor_rows(anchors)[:max(int(limit), 0)]
    if not rows:
        return "(nothing dated yet — start with what happened, not when)"
    return "\n".join(
        f"- {row['label']} — {chrono.display_date(row['date'], with_basis=False)}"
        for row in rows
    )


def choose_probe(unknown: object, *, anchors: object = (),
                 precision_so_far: object = None,
                 asked_steps: object = ()) -> dict:
    """The cheapest playbook question still worth asking for this unknown.

    Returns `{"step", "cost", "text"}` — always a probe, never `None`, because
    a row the page offers Play on must have something to say. The ladder stops
    early: once `precision_so_far` is at or finer than the unknown's target
    granularity the probe is `convergence`.

    v196: there is no deferred state to consult. The `defer` rung survives as
    the ladder's last, gentlest line — "I'll find out" is an ordinary answer,
    received and never pressed (`timeline_gates.accepts_defer`).
    """
    row = unknown if isinstance(unknown, dict) else {}
    anchor_rows = _anchor_rows(anchors)
    asked = {str(step) for step in (asked_steps or ())}
    label = str(row.get("label") or row.get("key") or "this moment").strip()
    # Timeline Fix 07 D1/D5: the LADDER's anchor is chosen by the same rule as
    # the opener's. `anchor_rows[0]` was the second way the birth reached a
    # question — the opener stopped naming it in v236 and the ladder went on.
    fallback = anchor_for_probe(row, anchor_rows)
    anchor_label = fallback["label"] if fallback else ""

    if _precise_enough(precision_so_far, row.get("kind")):
        step = "convergence" if "convergence" not in asked else "defer"
        return _probe(step, label, anchor_label)

    kind = str(row.get("kind") or "")
    opener = KIND_OPENERS.get(kind)
    if opener is not None and opener["step"] not in asked \
            and opener.get("anchored_step", opener["step"]) not in asked:
        between = [str(x) for x in (row.get("between") or [])]
        # O-E0a: the OPENER's anchor is chosen by relationship to this
        # unknown, never by `anchor_rows`' own rank — a residence or an era
        # never sorts against the person's own birth (`anchor_for_probe`).
        opener_anchor = anchor_for_probe(row, anchor_rows)
        opener_anchor_label = opener_anchor["label"] if opener_anchor else ""
        anchored = bool(opener_anchor_label) and "anchored" in opener
        text = opener["anchored"] if anchored else opener["text"]
        return {
            "step": opener["anchored_step"] if anchored and "anchored_step" in opener
                    else opener["step"],
            "cost": opener["anchored_cost"] if anchored and "anchored_cost" in opener
                    else opener["cost"],
            "text": text.format(
                label=label, anchor=opener_anchor_label or "that move",
                between_first=(between[0].replace("-", " ") if between else "then"),
                between_second=(between[1].replace("-", " ")
                                if len(between) > 1 else "now"),
            ),
        }

    for step in PLAYBOOK_STEPS:
        if step["step"] in ("convergence", "defer"):
            continue
        if step["step"] in asked:
            continue
        if step["needs_anchor"] and not anchor_rows:
            continue
        # v196: "tell me what happened" is only ever right for a moment we
        # cannot name and have nothing to hang on. The instant we have either
        # a subject or a landmark, the opening question is about THAT.
        if step["step"] == "content" and anchor_rows:
            continue
        return _probe(step["step"], label, anchor_label)
    return _probe("convergence" if "convergence" not in asked else "defer",
                  label, anchor_label)


def keystone_probe(anchor_key: object, *, label: str, anchors: object = ()) -> dict:
    """The question a STARRED anchor is asked as (v196).

    `keystones()` rows are the highest-leverage anchors in the vault; each one
    needs a question of its own, naming the anchor, or the star means nothing
    to the person looking at it.

    O-E0a: a `period` keystone (an era) is governed by the same
    never-birth-never-itself rule as an ordinary `period_bound` unknown,
    through the same `anchor_for_probe` — an era never sorts against the
    person's own birth or against itself. `entity`/`event` keystones are
    unchanged: a person or a moment may legitimately anchor on the birthday.
    """
    kind = str(anchor_key or "").split(":", 1)[0]
    template = KEYSTONE_PROBES.get(kind, KEYSTONE_PROBES["event"])
    rows = _anchor_rows(anchors)
    own_key = str(anchor_key or "").split(":", 1)[-1]
    probe_kind = "period_bound" if kind == "period" else "moment"
    anchor_row = anchor_for_probe({"kind": probe_kind, "key": own_key}, rows)
    anchor_label = anchor_row["label"] if anchor_row else ""
    text = template["anchored"] if anchor_label else template["text"]
    return {
        "step": template["step"],
        "cost": template["cost"],
        "text": text.format(label=str(label).strip() or "that stretch",
                            anchor=anchor_label),
    }


def _probe(step: str, label: str, anchor_label: str) -> dict:
    text = PROBE_TEXTS[step].format(label=label, anchor=anchor_label or "that move")
    return {"step": step, "cost": _STEP_BY_NAME[step]["cost"], "text": text}


def _precise_enough(precision_so_far: object, kind: object) -> bool:
    """Has the ladder already reached this unknown's target rung?"""
    granularity = None
    if isinstance(precision_so_far, str) and precision_so_far in chrono.GRANULARITIES:
        granularity = precision_so_far
    else:
        record = chrono.from_dict(precision_so_far) if precision_so_far is not None else None
        granularity = record.granularity if record is not None else None
    if granularity is None:
        return False
    target = TARGET_GRANULARITY.get(str(kind), DEFAULT_TARGET_GRANULARITY)
    return chrono.GRANULARITIES.index(granularity) <= chrono.GRANULARITIES.index(target)


# --------------------------------------------------------------------------
# Stage (the leaf's `{timeline_stage}`)
# --------------------------------------------------------------------------

#: The three `{timeline_stage}` values the leaf is keyed on.
#: The stage a WORK-ITEM conversation runs in — one gap, one conversation
#: (lifehug-platform#664, plan §2.5/§2.2). Resolving a temporal contradiction,
#: an identity the resolver could not place, or a precision gap IS dating
#: work, so it is a STAGE of this child rather than an eighth child of
#: Conversation: the registry's own paradigm makes a new child a build-breaker
#: until every row is wired, and a seventh interaction would have bought a new
#: output vocabulary, a new filer and a new set of lints to say the thing this
#: lane already says. The string is deliberately the same string as
#: ``mirror_work.PLAY_TARGET_KIND`` — the Play kind and the stage it opens are
#: one word, pinned by ``test_the_play_kind_and_the_stage_are_one_word``.
WORK_ITEM_STAGE = "work_item"

#: The stage an ERA conversation runs in (eras E3, design §5.4). Play lives on
#: eras and frames, not on moments: one ▸ per era opens a conversation about a
#: STRETCH of a life — where it started, where it ended, what else was going on
#: inside it — rather than twenty ▸ asking about twenty undated things one at a
#: time. Like `work_item` it is a STAGE of this child rather than an eighth
#: child of Conversation: it mints no output field of its own (`placed` is the
#: lane's existing one) and buys no new vocabulary, filer or lint set.
#:
#: The string is deliberately the Play kind's own word, exactly as
#: `work_item` is (`?play=era:<era_id>`), so a host binds one verb and one
#: stage and the two cannot drift.
ERA_STAGE = "era"

#: The stage a conversation opened right after a MOVE on the Timeline runs in
#: (v362, owner 2026-09-26: "after I make an edit or a move… it asks me why I
#: made that move"). Like `work_item` and `era` it is a stage of this child,
#: not a new child: it mints no output field (`placed` is the lane's own, and a
#: correction that carries a time fills it), and a correction files through the
#: card seat (`answer_placement.SESSION_MOVE_MARKER`). See
#: :data:`A_TIMELINE_ACTION_CONVERSATION_DOES_ONE_JOB`.
MOVE_STAGE = "moved"

VALID_TIMELINE_STAGES = frozenset({"open", "place", "close", WORK_ITEM_STAGE,
                                   ERA_STAGE, MOVE_STAGE})

#: Playbook stop rule §6.10 — "stop when two probes in a row return no new
#: bound". The caller counts; this module decides.
STOP_AFTER_UNPRODUCTIVE_PROBES = 2
#: And an absolute ceiling, so a placement episode can never become an
#: interrogation. Dating is never worth the relationship.
MAX_PROBES = 4


def timeline_stage_for_session(session: object, *, user_leaving: bool = False,
                               placement_settled: bool = False,
                               no_new_bound_streak: int = 0,
                               work_item: object = None,
                               era: object = None) -> str:
    """Derive `{timeline_stage}` from the transcript plus two caller facts.

    The caller facts mirror `arc_walk.arc_stage_for_session`'s `user_leaving`
    exactly: things only the caller can know (the router's departure signal,
    whether the placement it already accepted is good enough, and how many
    probes in a row produced no new bound). Everything else is read off the
    turns; no new session field is stored.

    **`work_item` is the fourth caller fact and it selects the stage, not a
    rung.** A conversation the person deliberately opened on a Play target
    (:func:`work_item_target`) is in :data:`WORK_ITEM_STAGE` for its whole
    working life. There is no `open`-then-`place` progression there because
    there is nothing to warm up to: the deep link already said which
    disagreement this is about, and the first reply's job is to put the two
    readings in front of the person — plan §2.5's *"Play opens a conversation
    grounded in that exact contradiction"*.

    Every close rule above still wins, and in the same order: leaving, a
    settled placement, two probes with no new bound, and the probe ceiling all
    end a work-item episode exactly as they end a placement episode. §2.2
    permits *"several progressively precise questions while the person remains
    willing"* in a conversation they opened — `MAX_PROBES` is what "willing"
    is measured against, and it is deliberately not raised here.
    """
    if user_leaving or placement_settled:
        return "close"
    try:
        streak = int(no_new_bound_streak)
    except (TypeError, ValueError):
        streak = 0
    if streak >= STOP_AFTER_UNPRODUCTIVE_PROBES:
        return "close"
    turns = (session or {}).get("turns") or [] if isinstance(session, dict) else []
    target = work_item_target(work_item)
    # E3: an era target selects the stage for the conversation's whole working
    # life, exactly as a work item does, and for the same reason — the deep
    # link already said which stretch of life this is about, so there is
    # nothing to warm up to. A work item wins on the rare occasion both
    # arrive: it is a specific disagreement, and the era is the room it is in.
    era_row = None if target else era_target(era)
    if not target and not era_row and not any(
        isinstance(turn, dict) and turn.get("role") == "lifehug" for turn in turns
    ):
        return "open"
    user_turns = sum(1 for turn in turns if isinstance(turn, dict) and turn.get("role") == "user")
    if user_turns >= MAX_PROBES:
        return "close"
    if target:
        return WORK_ITEM_STAGE
    if era_row:
        return ERA_STAGE
    return "place"


def precision_so_far(session: object) -> object:
    """The finest date record this episode has already established, or None."""
    best = None
    turns = (session or {}).get("turns") or [] if isinstance(session, dict) else []
    for turn in turns:
        record = chrono.from_dict((turn or {}).get("placed")) if isinstance(turn, dict) else None
        if record is None:
            continue
        if best is None or (chrono.GRANULARITIES.index(record.granularity)
                            < chrono.GRANULARITIES.index(best.granularity)):
            best = record
    return best


# --------------------------------------------------------------------------
# The work-item stage (v234) — one gap, one conversation
# --------------------------------------------------------------------------
#
# Plan §2.5 gives every actionable Mirror row a **Play now** that "opens a
# conversation grounded in that exact contradiction", and §2.3 says resolving
# a temporal work item on ANY surface closes it everywhere. Those two
# sentences together describe a conversation whose subject is a
# `temporal_projection.TemporalWorkItem`, not a surface — which is why the
# Play kind is `work_item` and why this stage lives here rather than in a
# seventh child of Conversation.
#
# Everything the stage needs already exists and none of it is re-decided here:
#
# * the TARGET and its bounded evidence are `mirror_work.play_target`'s
#   (claim readings and their sources for a contradiction, the candidate set
#   for an identity, the gap statement for a missing anchor or a precision
#   gap);
# * the OUTPUT is the lane's own `placed` record — no new vocabulary — plus
#   whatever the v229 general listener hears in the same message, because the
#   person's answer is just a message and the extraction is already listening
#   to messages;
# * the FILING is `mirror_work.resolve_mirror_item` (bound per vault as
#   `mirror.resolve_actionable_item`), which promotes the words, files
#   replacement claims through a receipt, and retires by correction.
#
# What this section adds is the join: which probe, which context, which
# claims a placement actually settles, and the refusal that keeps §2.5's
# quiet case quiet.

#: The work item kinds this stage can run a conversation about — the whole of
#: `temporal_projection.WORK_ITEM_KINDS`. Mirror renders only some of them
#: (`mirror_work.MIRROR_WORK_ITEM_KINDS`) because §2.3 keeps routine
#: incompleteness off that page; Play is not a page and has no such rule, so a
#: precision gap the queue surfaced opens the same conversation a
#: contradiction does.
#:
#: ``same_event`` and ``possible_overmerge`` join here at event identity I3 —
#: no new Interaction, stage or awaiting state (design §6.1/§6.3): the Play
#: kind is `work_item` exactly as it is for every sibling kind, and the five
#: answers / the split gesture file through `resolve-work-item`, never a
#: second conversation surface.
WORK_ITEM_KINDS = ("contradiction", "identity_uncertain",
                   "missing_anchor", "place_ambiguous", "precision_gap",
                   "residence_overlap", "tenure_ambiguous", "chain_gap",
                   "same_event", "possible_overmerge", "relation_word")

#: How many quoted spans a work-item context block carries. The same number as
#: `mirror_work.MAX_PLAY_EVIDENCE` and pinned equal to it
#: (`test_the_evidence_caps_are_one_number`): the target is built there and
#: rendered here, and two caps would mean the renderer silently dropped
#: evidence the target went to the trouble of bounding.
MAX_WORK_ITEM_EVIDENCE = 6

#: How many rival readings the context block shows beside the best-supported
#: one. Mirrors `mirror_work.MAX_ALTERNATIVES` for the same reason.
MAX_WORK_ITEM_READINGS = 5

#: The probe per work-item kind. `step` is the playbook rung the lints score
#: against, so these are not free choices: a contradiction converges (both
#: readings are already on the table), an identity asks what the person meant,
#: a missing anchor is an ordinary placement opening, and a precision gap
#: OFFERS bounds — `timeline_gates.offers_bounds` then holds the reply to
#: §2.2's "never demand false precision" mechanically.
WORK_ITEM_PROBES = {
    "contradiction": {
        "step": "convergence", "cost": 4,
        "text": "Two things you've told me put {label} in different places in "
                "time \u2014 {readings}. Which of those feels right to you?",
        "anchored": "Two things you've told me disagree about {label} \u2014 "
                    "was that before or after {anchor}?",
    },
    "identity_uncertain": {
        "step": "content", "cost": 1,
        "text": "When you said {label}, which one did you mean \u2014 "
                "{candidates}?",
        "anchored": "When you said {label}, which one did you mean \u2014 "
                    "{candidates}?",
    },
    "missing_anchor": {
        "step": "content", "cost": 1,
        "anchored_step": "sequence", "anchored_cost": 5,
        "text": "Tell me about {label} \u2014 just the moment itself, however "
                "it comes.",
        "anchored": "{label} \u2014 was that before or after {anchor}?",
    },
    "precision_gap": {
        "step": "bounds", "cost": 2,
        "text": "You've told me about {label} \u2014 do you know {field} any "
                "closer, or is somewhere in that stretch more honest?",
        "anchored": "You've told me about {label} \u2014 do you know {field} "
                    "any closer, or is somewhere around {anchor} more honest?",
    },
    # `timeline-rules:4` (Timeline Fix 05 §8.3). The place is named and the
    # person was there more than once, so the probe asks WHICH TIME rather
    # than which year — the same converging move a contradiction makes, on a
    # choice the substrate already holds both halves of.
    "place_ambiguous": {
        "step": "content", "cost": 2,
        "text": "You've told me about {label}, and you were in that place more "
                "than once \u2014 which of those times was this?",
        "anchored": "You've told me about {label} \u2014 was that before or "
                    "after {anchor}?",
    },
    # E-L2a §7.2. The place probe's sibling for an employer or a school: the
    # same converging move on the same kind of choice, in the words that fit
    # an organization ("worked there", not "were in that place").
    "tenure_ambiguous": {
        "step": "content", "cost": 2,
        "text": "You've told me about {label}, and you were there more than "
                "once \u2014 which of those times was this?",
        "anchored": "You've told me about {label} \u2014 was that before or "
                    "after {anchor}?",
    },
    # E-L2b \u00a73.2. Two stays claiming the same weeks. The probe names both and
    # asks for a CORRECTION, never for an explanation: owner decision 2 keeps
    # one home at a time and fixes an overlap by editing a date, so the three
    # offers are this stay's dates, the other's, or "that was not a home"
    # (a `retract` correction on the entry's promoted source, \u00a75 rule 6).
    "residence_overlap": {
        "step": "convergence", "cost": 3,
        "text": "Two of the places you've told me about overlap \u2014 {label} and "
                "the next one. Which dates need fixing, or was one of them "
                "not really a home?",
        "anchored": "Two of the places you've told me about overlap \u2014 "
                    "{label} \u2014 was that before or after {anchor}?",
    },
    # E-L2c \u00a77.2/\u00a78. A stretch none of the three chains covers \u2014 the target
    # already NAMES what it is missing (`label`, from
    # `landmarks_interaction.chain_gaps`), so the probe just asks it, exactly
    # as `residence_gap`'s own opener does. Routine incompleteness, not a
    # disagreement \u2014 it never reaches Mirror (`temporal_timeline.SURFACES_BY_KIND`).
    "chain_gap": {
        "step": "chain", "cost": 2,
        "text": "{label} \u2014 what was going on then?",
        "anchored": "{label} \u2014 was that before or after {anchor}?",
    },
    # Event identity I3 (design \u00a76.1). The five answers are a CLOSED choice
    # (`identity_questions.RELATION_ANSWERS`), not free text this probe's
    # reply is parsed for \u2014 the same "structured payload, not prose
    # parsing" shape `timeline-move --relation` already uses. `{cast}` is a
    # pre-formatted suffix (e.g. " with Sarah and Tom", or "").
    "same_event": {
        "step": "content", "cost": 3,
        "text": "Is \u201c{telling_quote}\u201d the same thing as "
                "\u201c{episode_quote}\u201d{cast}? Same thing, part of it, "
                "related but different, different, or not sure?",
        "anchored": "Is \u201c{telling_quote}\u201d the same thing as "
                    "\u201c{episode_quote}\u201d{cast} \u2014 that was "
                    "around {anchor}?",
    },
    # \u00a74.5/\u00a76.3. An audit of a bind already made, not a proposal \u2014 the
    # four offers are keep together / split / part of / fix the date
    # (`identity_questions.OVERMERGE_ANSWERS`).
    "possible_overmerge": {
        "step": "convergence", "cost": 4,
        "text": "I've been treating \u201c{telling_quote}\u201d and "
                "\u201c{episode_quote}\u201d as one thing, but their dates "
                "don't agree \u2014 keep them together, split them apart, "
                "call one part of the other, or is a date just off?",
        "anchored": "I've been treating \u201c{telling_quote}\u201d and "
                    "\u201c{episode_quote}\u201d as one thing, but "
                    "something doesn't line up around {anchor} \u2014 keep "
                    "together, split, or fix a date?",
    },
    # v358 (`relation_words.A_CARD_ONLY_WHERE_THE_WORD_HAS_A_GENDERED_PAIR`).
    # One choice about one named person, the three options already on the
    # card (`candidates`): the gendered pair, or keep the neutral word. No
    # anchored variant: a landmark has nothing to do with which word he uses.
    "relation_word": {
        "step": "content", "cost": 1,
        "text": "When you talk about {label}, which word is right \u2014 "
                "{candidates}?",
    },
}

#: How a `requested_field` reads inside a precision probe. An unlisted field
#: falls back to the neutral "it", never to the raw key: a probe that says
#: "do you know earliest_bound any closer" is the abstraction v196 already
#: ruled out of the ladder ("I have no idea what that means").
FIELD_DISPLAY = {
    "day": "the day",
    "month": "the month",
    "season": "the time of year",
    "year": "the year",
    "start": "when it started",
    "end": "when it ended",
    "range": "the stretch",
}
DEFAULT_FIELD_DISPLAY = "it"


def _play_target_kinds() -> tuple[str, ...]:
    """The kind strings a Play target may ARRIVE as — `mirror_work`'s own set.

    Imported lazily and defaulted defensively. `mirror_work` pulls the whole
    temporal store in behind it and a target's kind is not worth that cost on
    every import of this module; and if the store cannot be imported at all,
    the fallback is the canonical kind ALONE — degrading toward the new word,
    never toward v227's retired alias.
    """
    try:
        import mirror_work  # noqa: PLC0415

        return tuple(mirror_work.PLAY_TARGET_KINDS)
    except Exception:  # noqa: BLE001
        return (WORK_ITEM_STAGE,)


def _reading_view(value: object) -> dict | None:
    """One rival dating, as `mirror_work._reading` already shaped it."""
    if not isinstance(value, dict):
        return None
    display = str(value.get("display") or "").strip()
    edtf = str(value.get("edtf") or "").strip()
    if not display and not edtf:
        return None
    refs = [str(ref).strip() for ref in (value.get("claim_refs") or ()) if str(ref).strip()]
    # `sources` arrives as `mirror_work`'s citation dicts the first time and
    # as the flattened ids this function produced on any later pass, so both
    # are read — normalizing a normalized target must be a no-op.
    sources = [
        str(row.get("source_id") or row.get("claim_id") or "").strip()
        if isinstance(row, dict) else str(row).strip()
        for row in (value.get("sources") or ())
    ]
    return {
        "display": display or edtf,
        "edtf": edtf,
        "basis": str(value.get("basis") or "").strip(),
        "confidence": str(value.get("confidence") or "").strip(),
        "claim_refs": refs,
        "sources": [s for s in sources if s],
    }


def _resolved_work_item_id(value: object, aliases: object) -> str:
    """One stored reference to the id it is addressed by NOW — GUARDED.

    O-E6: a session, a bank marker or a `?play=` link minted before the
    vocabulary converged carries a legacy `work:` id. Resolving it here is what
    keeps it OPENING; without this, the same conversation would refuse a target
    the person can still see on their Timeline. Unknown ids come back unchanged
    — resolution never invents an identity — and a broken temporal package
    degrades to exactly the pre-O-E6 behaviour rather than closing the door.
    """
    raw = str(value or "").strip()
    if not raw:
        return ""
    try:
        import temporal_work_items  # noqa: PLC0415

        return temporal_work_items.resolve_work_item_id(raw, aliases=aliases) or raw
    except Exception:  # noqa: BLE001
        return raw


def work_item_target(value: object, *, aliases: object = None) -> dict | None:
    """Normalize a Play target (or a bare work item) for this stage, or `None`.

    Two shapes arrive and both are legitimate. A **Play target** is
    `mirror_work.play_target`'s output: `kind` is the Play kind, `item_kind`
    is the work item's kind, and the bounded evidence is already on it. A
    **bare work item** is the projection's own row, where `kind` IS the work
    item kind and there is no evidence — what a queue-minted gap has before
    anything rendered it.

    Refusal is by returning `None`, never by raising: a target this stage
    cannot read must degrade to an ordinary turn, exactly as a missing
    timeline item does. An unrecognized kind, a missing id, and a plain string
    all take that door.
    """
    if not isinstance(value, dict) or not value:
        return None
    kind = str(value.get("kind") or "").strip()
    item_kind = str(value.get("item_kind") or "").strip()
    if kind in _play_target_kinds():
        pass
    elif kind in WORK_ITEM_KINDS:
        item_kind = item_kind or kind
    else:
        return None
    if item_kind not in WORK_ITEM_KINDS:
        return None
    work_item_id = _resolved_work_item_id(
        value.get("work_item_id") or value.get("ref"),
        aliases if aliases is not None else value.get("work_item_aliases"),
    )
    if not work_item_id:
        return None

    # Idempotent: a target that has already been through here carries its
    # rivals as one `readings` list, and re-normalizing it must not lose them.
    # (It did once, silently, and `work_item_resolution` then retired nothing
    # for every caller that normalized before filing.)
    readings: list[dict] = []
    if isinstance(value.get("readings"), list):
        for row in value["readings"][:MAX_WORK_ITEM_READINGS + 1]:
            view = _reading_view(row)
            if view is not None:
                readings.append(view)
    else:
        best = _reading_view(value.get("best_supported"))
        if best is not None:
            readings.append(best)
        for row in (value.get("alternatives") or ())[:MAX_WORK_ITEM_READINGS]:
            alt = _reading_view(row)
            if alt is not None:
                readings.append(alt)

    evidence: list[dict] = []
    for row in (value.get("evidence") or ())[:MAX_WORK_ITEM_EVIDENCE]:
        if not isinstance(row, dict):
            continue
        quote = str(row.get("quote") or "").strip()
        if not quote:
            continue
        evidence.append({
            "claim_id": str(row.get("claim_id") or "").strip(),
            "source_id": str(row.get("source_id") or "").strip(),
            "quote": quote,
        })

    candidates: list[dict] = []
    for row in (value.get("candidates") or ()):
        if not isinstance(row, dict):
            continue
        name = str(row.get("name") or row.get("ref") or "").strip()
        if name:
            candidates.append({"ref": str(row.get("ref") or "").strip(), "name": name})

    target = {
        "kind": WORK_ITEM_STAGE,
        "work_item_id": work_item_id,
        "item_kind": item_kind,
        "label": str(value.get("label") or value.get("headline") or work_item_id).strip(),
        "readings": readings[:MAX_WORK_ITEM_READINGS + 1],
        "candidates": candidates,
        "evidence": evidence,
        # The person's own landmarks travel WITH the target, exactly as they
        # travel with a timeline item, so `answer_timeline_probe`'s closed
        # anchor check means the same thing on this path as on that one.
        "anchors": _anchor_rows(value.get("anchors")),
        "resolvable_claim_ids": [
            str(ref).strip()
            for ref in (value.get("resolvable_claim_ids") or value.get("claim_refs") or ())
            if str(ref).strip()
        ],
    }
    for key in ("prompt_intent", "description", "requested_field",
                "subject_ref", "event_ref", "node_ref",
                # Event identity I3: the two quoted utterances a `same_event`
                # or `possible_overmerge` probe puts side by side, and the
                # shared cast suffix (already formatted, e.g. " with Sarah");
                # absent for every other kind, so every other probe's
                # `.format()` call sees the same empty string it always did.
                "telling_quote", "episode_quote", "cast"):
        text = str(value.get(key) or "").strip()
        if text:
            target[key] = text
    return target


def _work_item_has_material(row: dict) -> bool:
    """Does the target itself carry what its own probe needs to be asked?

    A contradiction needs both readings, an identity needs its candidates, a
    precision gap needs the field or the reading it is refining. A missing
    anchor, by definition, needs the thing it does not have — which is why it
    is the one kind that always prefers the anchored fallback.
    """
    kind = row["item_kind"]
    if kind == "contradiction":
        return len(row["readings"]) >= 2
    if kind == "identity_uncertain":
        return bool(row["candidates"])
    if kind == "precision_gap":
        return bool(row["readings"]) or bool(row.get("requested_field"))
    if kind == "relation_word":
        return bool(row["candidates"])
    if kind in ("same_event", "possible_overmerge"):
        # Event identity I3: the pair's own two quotes ARE the question — an
        # anchored before/after fallback would ask something the person
        # cannot answer with one of the five relations.
        return bool(row.get("telling_quote")) and bool(row.get("episode_quote"))
    return False


def work_item_probe(target: object, *, anchors: object = ()) -> dict:
    """The probe this work item opens with — `{probe}`'s value for the leaf.

    Same return shape as :func:`choose_probe` (`step`, `cost`, `text`), because
    the leaf, the lints and the eval harness all read that shape and a second
    one would be a second contract for the same slot.

    The probe NAMES what it is about, like every rung of the ladder does, and
    it never proposes a date to be agreed with: a contradiction puts BOTH
    readings in the same sentence and asks which, which is the opposite move
    from naming one and inviting a yes (ADR 0025's suggestive-interviewing
    hazard).
    """
    row = work_item_target(target)
    if row is None:
        raise TimelineInteractionError("work item target is unusable")
    spec = WORK_ITEM_PROBES[row["item_kind"]]
    anchor_rows = _anchor_rows(anchors) or row["anchors"]
    # Timeline Fix 07 D1/D5: never the birth, never something unrelated. A work
    # item's anchored variant is already a fallback; an irrelevant fallback is
    # worse than the unanchored question it replaces.
    chosen = anchor_for_probe(
        {"kind": row["item_kind"], "label": row.get("label"),
         "key": row.get("node_ref") or row.get("event_ref")},
        anchor_rows,
    )
    anchor_label = str(chosen.get("label") or "") if chosen else ""
    readings = " and ".join(r["display"] for r in row["readings"]) or "two different times"
    candidates = " or ".join(c["name"] for c in row["candidates"]) or "which one"
    field = FIELD_DISPLAY.get(row.get("requested_field", ""), DEFAULT_FIELD_DISPLAY)
    # The anchored variant is a FALLBACK, not an upgrade: converting a
    # contradiction whose two readings are right there into a before/after
    # against an unrelated landmark throws away the only thing that makes the
    # question answerable. It is used when the target's own material is
    # missing and a landmark is the next best handle.
    anchored = (bool(anchor_label) and bool(spec.get("anchored"))
                and not _work_item_has_material(row))
    text = (spec["anchored"] if anchored else spec["text"]).format(
        label=row["label"], anchor=anchor_label,
        readings=readings, candidates=candidates, field=field,
        telling_quote=row.get("telling_quote") or row["label"],
        episode_quote=row.get("episode_quote") or candidates,
        cast=row.get("cast") or "",
    )
    return {
        "step": spec.get("anchored_step", spec["step"]) if anchored else spec["step"],
        "cost": spec.get("anchored_cost", spec["cost"]) if anchored else spec["cost"],
        "text": text,
    }


def work_item_known_years(target: object) -> tuple[str, ...]:
    """Every year the TARGET itself supplies — the years the reply may repeat.

    `timeline_gates.never_invents_a_date` allows a reply to assert only years
    the person has already supplied. A contradiction conversation must repeat
    both rival readings back or it cannot ask the question at all, so the
    readings and the quoted evidence are exactly that supply — and nothing
    else is. A year that appears in neither is still an invention here.
    """
    row = work_item_target(target)
    if row is None:
        return ()
    years: list[str] = []
    haystacks = [r["display"] for r in row["readings"]]
    haystacks += [r["edtf"] for r in row["readings"]]
    haystacks += [e["quote"] for e in row["evidence"]]
    haystacks += [str(row.get("description") or ""), str(row.get("prompt_intent") or "")]
    for text in haystacks:
        for match in _YEAR_RE.finditer(text or ""):
            if match.group(0) not in years:
                years.append(match.group(0))
    return tuple(years)


def _work_item_subject_sentence(row: dict) -> str:
    """The sentence naming WHOSE moment this is, or ``""``.

    lifehug/lifehug#382, parity with the hosted platform's
    `work_item_walk.render_card_aside` / `card_subject` (platform#903, the
    2026-09-23 owner incident): a card on "Father's mission to New Zealand"
    (`subject_ref` "James Edwin Taylor") asked "what year, or about how old
    was your dad", the owner typed "19-21 years old", and the reply placed
    the OWNER at nineteen. `render_work_item`'s own ``about: James Edwin
    Taylor`` line names the subject in ONE WORD, and the model discounted
    it. This sentence says the same thing the platform now says, in words,
    so the local medium (`lifehug conversation`) reads a card answer the
    way the hosted product does.

    ``""`` — and the block renders exactly as it did before this sentence
    existed — in three cases:

    * **no subject at all** — most work items (a plain contradiction or
      precision gap on the owner's own life) never carry `subject_ref`;
    * **the subject IS the owner** — ``self`` (`temporal_work_items.
      OWNER_SUBJECT_REF`) or a bare owner pronoun (`temporal_timeline.
      is_owner_reference_only`, the same test `resolver._subject_is_owner`
      applies; that function also matches the owner's own name against the
      spine, which this leaf does not carry, so a subject spelled out as the
      owner's full name is not caught here — an acceptable gap, since every
      caller that mints a work item for the owner's own life spells the
      subject ``self``);
    * **the subject is a binder HANDLE, not a resolved person** —
      `identity_resolution.is_unresolved_ref` ("which of the four Jameses?")
      or `temporal_work_items.is_anchor_handle_ref` ("the move to
      Orderville") — a handle nobody has resolved is not a person to
      attribute an age to, exactly as the platform's `card_subject` refuses
      one.
    """
    subject = str(row.get("subject_ref") or "").strip()
    if not subject or subject.lower() == "self":
        return ""
    try:
        import identity_resolution as _ident  # noqa: PLC0415
        import temporal_work_items as _twi  # noqa: PLC0415
        from temporal_timeline import is_owner_reference_only  # noqa: PLC0415
    except Exception:  # noqa: BLE001 — a work-item problem never costs a turn
        return ""
    if _ident.is_unresolved_ref(subject) or _twi.is_anchor_handle_ref(subject):
        return ""
    if is_owner_reference_only(subject):
        return ""
    who = subject
    return (
        f"This moment is about {who}, not about the person you are talking "
        f"with. An age, a grade, a year, a season or a before/after in their "
        f'answer belongs to {who} unless they say otherwise — "19" is how '
        f"old {who} was, never how old they were. Confirm it as {who}'s, and "
        f"never ask what they themselves remember of a time they may not have "
        f"lived."
    )


def render_work_item(target: object, *, limit: int = MAX_WORK_ITEM_EVIDENCE) -> str:
    """The `{work_item}` block: what conflicts, said in the person's own words.

    Bounded on purpose (§12: model context is bounded). It carries the two
    things a grounded conversation needs — the disagreement and the sentences
    it came from — and never a transcript, never a claim id the person has no
    use for, and never a count of anything.

    Additive (v332, `lifehug/lifehug#382`): when the target's subject names a
    resolved person other than the owner, a sentence naming them is inserted
    right after ``about:`` — see `_work_item_subject_sentence`. Absent a
    subject, or when the subject is the owner or an unresolved binder handle,
    the block is byte-identical to what it always rendered.
    """
    row = work_item_target(target)
    if row is None:
        return ""
    lines = [f"kind: {row['item_kind']}", f"about: {row['label']}"]
    subject_sentence = _work_item_subject_sentence(row)
    if subject_sentence:
        lines.append(subject_sentence)
    statement = row.get("description") or row.get("prompt_intent") or ""
    if statement:
        lines.append(f"what is open: {statement}")
    if row["readings"]:
        lines.append("readings (all of them stand until you settle it):")
        for reading in row["readings"]:
            detail = ", ".join(x for x in (reading["confidence"], reading["basis"]) if x)
            sources = ", ".join(reading["sources"])
            suffix = f" [{detail}]" if detail else ""
            suffix += f" (source: {sources})" if sources else ""
            lines.append(f"  - {reading['display']}{suffix}")
    if row["candidates"]:
        lines.append("candidates: " + ", ".join(c["name"] for c in row["candidates"]))
    quotes = row["evidence"][:max(0, int(limit))]
    if quotes:
        lines.append("their own words:")
        for span in quotes:
            source = f" ({span['source_id']})" if span["source_id"] else ""
            lines.append(f"  - \u201c{span['quote']}\u201d{source}")
    return "\n".join(lines)


def work_item_retire_ids(target: object, placed: object) -> tuple[str, ...]:
    """The claims this placement actually settles — often none, and that is fine.

    A reading is retired when the person named a DIFFERENT one of the readings
    already on the table. Three refusals, each of them §2.5 made mechanical:

    * **Nothing placed retires nothing.** "I don't know", a skip, a closed
      tab: no correction is invented and the item stays.
    * **A THIRD answer retires nothing.** If the placement matches none of the
      readings, the person has supplied new evidence rather than picked a
      side; it files as a claim through the ordinary extraction and the fold
      decides what that does to the conflict. Retiring both rivals here would
      be this module resolving a contradiction it was only asked to host.
    * **Nothing outside the row.** The result is intersected with the
      target's `resolvable_claim_ids`, so a conversation cannot reach past its
      own disagreement even if a reading cites something it should not.
    """
    row = work_item_target(target)
    if row is None:
        return ()
    record = chrono.from_dict(placed) if placed else None
    chosen = chrono.to_edtf(record) if record is not None else None
    if not chosen:
        return ()
    readings = row["readings"]
    if not any(r["edtf"] == chosen for r in readings):
        return ()
    allowed = set(row["resolvable_claim_ids"])
    retire: list[str] = []
    for reading in readings:
        if reading["edtf"] == chosen:
            continue
        for ref in reading["claim_refs"]:
            if ref in allowed and ref not in retire:
                retire.append(ref)
    return tuple(retire)


#: v362: the `correction_kind` of an answer that PLACES a card with nothing to
#: retire. A host routes it to `answer_placement.place_card_answer` (the card
#: seat), never to `mirror_work.resolve_mirror_item`, which retires readings.
CORRECTION_KIND_PLACE = "place"

#: The rule, in one sentence (v362).
AN_ANSWER_WITH_NOTHING_TO_RETIRE_IS_PLACED = (
    "an answer that dates a card with no rival readings (a precision gap, a "
    "missing anchor) is placed on the turn through the card seat, so the card "
    "leaves Needs placing now rather than after the daily sweep"
)


def work_item_resolution(target: object, placed: object, *,
                         resolution_text: str) -> dict | None:
    """The kwargs for `mirror.resolve_actionable_item`, or `None` to write nothing.

    The whole filing decision, in one pure function, so the host that writes
    is not also the host that judges. `None` means §2.5's quiet case — the
    person said nothing that settles anything — and a host that receives it
    calls `mirror_work.abandon_mirror_item`, which cannot write at all, or
    simply does nothing.

    A non-`None` result carries the person's own words as `resolution_text`
    and the `retire_claim_ids` :func:`work_item_retire_ids` derived. It never
    carries `claims_for`: replacement claims come from the v229 general
    listener hearing the same message, on the path that already hears every
    other message, and asserting them twice would be the dual write wave B
    removed.
    """
    row = work_item_target(target)
    if row is None:
        return None
    text = " ".join(str(resolution_text or "").split())
    if not text:
        return None
    if not row["readings"]:
        # v362 (:data:`AN_ANSWER_WITH_NOTHING_TO_RETIRE_IS_PLACED`): a card with
        # no rival readings — a precision gap, a missing anchor — has nothing
        # to retire, and before this its answer filed NOTHING on the turn and
        # waited for the daily sweep while the card stayed in front of him.
        # When the reply actually dated it, the answer is PLACED now, through
        # the card seat (`answer_placement.place_card_answer`).
        if chrono.from_dict(placed) is None:
            return None
        return {
            "work_item_id": row["work_item_id"],
            "resolution_text": text,
            "retire_claim_ids": [],
            "correction_kind": CORRECTION_KIND_PLACE,
        }
    retire = work_item_retire_ids(row, placed)
    if not retire:
        return None
    return {
        "work_item_id": row["work_item_id"],
        "resolution_text": text,
        "retire_claim_ids": list(retire),
        "correction_kind": "supersede",
    }


# --------------------------------------------------------------------------
# A conversation opened from a Timeline ACTION does one job (v362)
# --------------------------------------------------------------------------
#
# Owner, 2026-09-26 (staging): he pressed ▸ on "About Charlee · What year did
# Charlee switch from flag football to track?", typed "Charlee switched from
# football to track her freshmen year January 2026", and was answered
# "Football to track, freshman year, January 2026 — noted. What pulled you
# toward track?" — a story beat, about the wrong person. He typed "This is
# Charlee not me". And after a move on the Timeline, the conversation that
# opened asked him why he had made the move. His words: "when I actually make
# an edit on the timeline, it doesn't have context… when we're answering
# questions it is aware of all the context and it's specifically trying to
# answer the timely question."
#
# Everything below is the ONE definition of that rule, for every host. The
# hosted platform used to keep its own copy (`work_item_walk.card_is_done` /
# `render_card_aside`, Timeline Fix 10); owner ruling 2026-09-25 ("the Lifehug
# platform and the Lifehug OSS should work exactly the same") moves it here,
# and a host now calls these functions rather than re-deciding them:
#
# * WHAT the conversation is about — :func:`card_view` (a card: its question,
#   its node, the person it is about, where it stands now, the grounded
#   related moments) and :func:`move_target` (a move: what moved, what he
#   asserted, where it landed);
# * WHO it is about — :func:`subject_view`, read off the published
#   ``relation_words`` and ``cornerstones_view`` rows, so the model is told
#   "your child Charlee, born 21 December 2010", in words, and told to speak
#   of her in the third person;
# * WHEN it is done — :func:`card_is_done` / :func:`move_is_done`, pure over the
#   transcript, and :func:`action_question_allowed`, which a host applies to
#   its own turn shape so a closing reply cannot carry a question at all;
# * WHAT the model reads — :func:`render_card_context` /
#   :func:`render_move_context`, the whole block, and :func:`move_confirmation`,
#   the one line a move conversation opens with.

#: The rule, in one sentence, so a reader and a test name the same thing.
A_TIMELINE_ACTION_CONVERSATION_DOES_ONE_JOB = (
    "a conversation opened from a Timeline action (a card's answer, a move or "
    "an edit just saved) carries its target, the person it is about, where it "
    "stands and what the action changed, and does that one job: confirm in one "
    "line and stop, or ask ONE related question grounded in a real open item, "
    "about the right person; never a story beat and never why they did it"
)

#: The headings the two blocks open with — one spelling, so a host that
#: asserts an ordinary prompt carries no action text asserts the same bytes.
CARD_HEADING = "## This conversation came from a Timeline card"
MOVE_HEADING = "## This conversation came from a move on the Timeline"

#: Relationship -> the neutral relation word, used only when no word was
#: published for the person (a gendered word always wins when one is known,
#: owner ruling 2026-09-25 "Relationship words").
_NEUTRAL_RELATION_WORDS = {
    "child": "child", "parent": "parent", "sibling": "sibling",
    "spouse": "spouse", "grandparent": "grandparent",
    "grandchild": "grandchild",
}
_SHE_WORDS = frozenset({"daughter", "mother", "wife", "sister", "grandmother",
                        "granddaughter", "mom", "aunt", "niece"})
_HE_WORDS = frozenset({"son", "father", "husband", "brother", "grandfather",
                       "grandson", "dad", "uncle", "nephew"})
#: Names that are themselves kinship words — what he calls his father ("Dad")
#: or his grandfather ("Grandpa") — so the phrase does not say it twice.
_KINSHIP_NAMES = _SHE_WORDS | _HE_WORDS | frozenset({
    "grandpa", "grandma", "papa", "mama", "nana", "granny", "gramps", "mum",
})


def _fold(text: object) -> str:
    return " ".join(str(text or "").split()).strip()


def _fold_key(text: object) -> str:
    return _fold(text).lower().rstrip(".")


def _subject_is_the_owner(subject: str) -> bool:
    if not subject or subject.lower() == "self":
        return True
    try:
        from temporal_timeline import is_owner_reference_only  # noqa: PLC0415
    except Exception:  # noqa: BLE001 — a context read never costs a turn
        return False
    return bool(is_owner_reference_only(subject))


def _subject_is_a_handle(subject: str) -> bool:
    try:
        import identity_resolution as _ident  # noqa: PLC0415
        import temporal_work_items as _twi  # noqa: PLC0415
    except Exception:  # noqa: BLE001
        return False
    return bool(_ident.is_unresolved_ref(subject) or _twi.is_anchor_handle_ref(subject))


def _row_names(row: dict) -> set[str]:
    names = {_fold_key(row.get(key)) for key in ("subject_ref", "person_ref", "name",
                                                  "display_name")}
    names |= {_fold_key(s) for s in (row.get("spellings") or ()) if isinstance(s, str)}
    full = _fold(row.get("name"))
    if full:
        names.add(_fold_key(full.split()[0]))
    return {name for name in names if name}


def _people_rows(people: object) -> list[dict]:
    """``cornerstones_view`` people, whether handed the whole view (its
    ``groups[].people``) or the flat list."""
    if isinstance(people, dict):
        rows: list[dict] = []
        for group in people.get("groups") or ():
            if isinstance(group, dict):
                rows.extend(p for p in (group.get("people") or ()) if isinstance(p, dict))
        rows.extend(p for p in (people.get("others") or ()) if isinstance(p, dict))
        return rows
    return [p for p in (people or ()) if isinstance(p, dict)]


def subject_view(subject_ref: object, *, relation_words: object = (),
                 people: object = ()) -> dict:
    """WHO a card or a move is about, as the model must be told it.

    ``{"ref", "name", "word", "phrase", "pronoun", "born", "is_owner"}``:

    * the OWNER (``self``, a bare owner pronoun, or no subject) —
      ``is_owner: True`` and nothing else to say;
    * a binder HANDLE nobody resolved ("unresolved:…", "anchor:…") — ``{}``:
      a handle is not a person to attribute an age to;
    * anyone else — their name as he calls them, the relation word the
      projection published (``relation_words``, gendered when known), the
      phrase "your child Charlee", a pronoun when the word says one, and their
      birth when the Cornerstones view has it — so "freshman year" and
      "January 2026" are read as Charlee's, at Charlee's age.

    ``relation_words`` is the calculated projection's own list (v358) and
    ``people`` its ``cornerstones_view`` (v360); either may be empty. A person
    neither lists still gets their name and ``is_owner: False``, which is the
    whole of the 2026-09-26 fix: the model is told it is not the person typing.
    """
    subject = _fold(subject_ref)
    if _subject_is_the_owner(subject):
        return {"ref": subject or "self", "is_owner": True}
    if _subject_is_a_handle(subject):
        return {}
    wanted = _fold_key(subject)
    word_row = next((row for row in (relation_words or ())
                     if isinstance(row, dict) and wanted in _row_names(row)), None)
    person = next((row for row in _people_rows(people) if wanted in _row_names(row)),
                  None)
    name = subject
    if person is not None and _fold(person.get("display_name")):
        name = _fold(person.get("display_name"))
    elif word_row is not None and _fold(word_row.get("name")) and "/" in subject:
        name = _fold(word_row.get("name"))
    elif "/" in subject:
        # A roster REF nobody's row names ("person/katie") is a machine
        # spelling; the model is given the name it spells, never the ref.
        name = " ".join(part.capitalize() for part in
                        subject.rsplit("/", 1)[-1].replace("_", "-").split("-") if part)
    word = ""
    gender = ""
    if word_row is not None:
        word = _fold_key(word_row.get("word"))
        gender = _fold_key(word_row.get("relation_gender"))
    if not word and person is not None:
        word = (_fold_key(person.get("relation_word"))
                or _NEUTRAL_RELATION_WORDS.get(_fold_key(person.get("relationship")), ""))
    pronoun = ""
    if gender == "female" or word in _SHE_WORDS:
        pronoun = "she"
    elif gender == "male" or word in _HE_WORDS:
        pronoun = "he"
    born = ""
    if person is not None and isinstance(person.get("born"), dict):
        born = _fold(person["born"].get("display"))
    if not word:
        phrase = name
    elif _fold_key(name) in _KINSHIP_NAMES:
        # What he calls them IS a kinship word ("Dad", "Grandpa"): "Dad (your
        # father)", never "your father Dad".
        phrase = f"{name} (your {word})"
    else:
        phrase = f"your {word} {name}"
    return {
        "ref": subject,
        "name": name,
        "word": word,
        "phrase": phrase,
        "pronoun": pronoun,
        "born": born,
        "is_owner": False,
    }


def _node_index(nodes: object) -> dict[str, dict]:
    index: dict[str, dict] = {}
    for node in nodes if isinstance(nodes, (list, tuple)) else ():
        if isinstance(node, dict):
            node_id = _fold(node.get("node_id"))
            if node_id and node_id not in index:
                index[node_id] = node
    return index


def _node_label(node: object) -> str:
    row = node if isinstance(node, dict) else {}
    return _fold(row.get("label") or row.get("headline"))


def _placement_text(node: object, item: object) -> str:
    """Where the card's moment stands NOW, in words: the node's own placement
    at its grain, or "not placed yet" plus the system's guess — labelled as a
    guess, because his answer replaces it (owner ruling 2026-09-25: a system
    inference never overrides what he said)."""
    row = node if isinstance(node, dict) else {}
    record = chrono.from_dict(row.get("best_temporal_value")) if row else None
    if record is not None and row.get("usable_placement") is not False:
        shown = chrono.display_date(record, with_basis=False)
        if shown:
            return f"placed at {shown}"
    window = (item or {}).get("probable_window") if isinstance(item, dict) else None
    if not isinstance(window, dict):
        window = row.get("probable_window") if isinstance(row.get("probable_window"), dict) else None
    if isinstance(window, dict):
        earliest = _fold(window.get("earliest"))
        latest = _fold(window.get("latest"))
        guess = None
        if earliest and latest:
            guess = chrono.parse_edtf(f"{earliest}/{latest}")
        elif earliest or latest:
            guess = chrono.parse_edtf(earliest or latest)
        shown = chrono.display_date(guess, with_basis=False) if guess is not None else ""
        if shown:
            return (f"not placed yet — the system only guessed {shown}; their "
                    f"answer replaces that guess, never argue with it")
    return "not placed yet"


def card_related(item: object, nodes: object, *, node_aliases: object = None,
                 relation_words: object = (), people: object = ()) -> tuple[dict, ...]:
    """The moments THIS card's answer would also place — its ``resolves``
    (`timeline_gain.item_gain`, what the Timeline renders as "could place N
    stories") labelled off the projection's own nodes, each with WHO it is
    about.

    Grounded, never invented: an id the projection no longer publishes is
    skipped, a node with no label is skipped (a node id is a machine spelling,
    never a question), duplicates collapse, and a former node id resolves
    through ``node_aliases`` first. Moved here from the platform's
    `work_item_walk.card_constellation` (v362), unchanged in what it keeps.
    """
    if not isinstance(item, dict):
        return ()
    aliases = node_aliases if isinstance(node_aliases, dict) else {}
    index = _node_index(nodes)
    out: list[dict] = []
    seen: set[str] = set()
    for ref in item.get("resolves") or ():
        node_id = _fold(ref)
        if not node_id:
            continue
        node_id = _fold(aliases.get(node_id, node_id)) or node_id
        if node_id in seen:
            continue
        node = index.get(node_id)
        label = _node_label(node)
        if not label:
            continue
        seen.add(node_id)
        refs = [_fold(r) for r in (node.get("subject_refs") or ()) if _fold(r)]
        who = subject_view(refs[0], relation_words=relation_words,
                           people=people) if len(refs) == 1 else {}
        out.append({"node_id": node_id, "label": label,
                    "about": "" if not who or who.get("is_owner") else who["name"]})
    return tuple(out)


def card_view(item: object, *, nodes: object = (), node_aliases: object = None,
              relation_words: object = (), people: object = (),
              target: object = None) -> dict:
    """Everything a card conversation must know, from the published row.

    ``item`` is the bare published work item (it carries ``resolves`` and
    ``probable_window``, which the normalized Play target drops); ``target``
    is the normalized target when the host has one, read first for the
    question. Keys: ``work_item_id``, ``question``, ``label`` (the moment the
    card is about), ``subject`` (:func:`subject_view`), ``placement`` (where it
    stands now, in words) and ``related`` (:func:`card_related`).
    """
    row = item if isinstance(item, dict) else {}
    normalized = target if isinstance(target, dict) else {}
    question = _fold(normalized.get("prompt_intent") or row.get("prompt_intent"))
    aliases = node_aliases if isinstance(node_aliases, dict) else {}
    node_ref = _fold(row.get("node_ref") or row.get("event_ref")
                     or normalized.get("node_ref") or normalized.get("event_ref"))
    node_ref = _fold(aliases.get(node_ref, node_ref)) or node_ref
    node = _node_index(nodes).get(node_ref)
    subject_ref = _fold(normalized.get("subject_ref") or row.get("subject_ref"))
    if not subject_ref and isinstance(node, dict):
        refs = [_fold(r) for r in (node.get("subject_refs") or ()) if _fold(r)]
        subject_ref = refs[0] if len(refs) == 1 else ""
    return {
        "work_item_id": _fold(row.get("work_item_id") or normalized.get("work_item_id")),
        "question": question,
        "label": _node_label(node) or _fold(normalized.get("label")),
        "subject": subject_view(subject_ref, relation_words=relation_words, people=people),
        "placement": _placement_text(node, row),
        "related": card_related(row, nodes, node_aliases=aliases,
                                relation_words=relation_words, people=people),
    }


def _turn_rows(session: object) -> list[dict]:
    if isinstance(session, dict):
        turns = session.get("turns") or []
    else:
        turns = session or []
    return [turn for turn in turns if isinstance(turn, dict)] if isinstance(
        turns, (list, tuple)) else []


def card_answered(session: object) -> bool:
    """Has the person typed? The card's question is shown by the tab, never as
    a lifehug turn, so the first user turn IS the answer to the card."""
    return any(turn.get("role") == "user" for turn in _turn_rows(session))


def card_is_done(session: object, *, related: object = 0) -> bool:
    """Is THIS reply the card conversation's last one? Pure over the
    PRE-reply transcript (``session`` is the session dict or its turn list).

    * Nobody has answered yet -> not done: there is nothing to confirm.
    * Nothing related remains -> done. The card's grounded related moments are
      the ceiling on further questions, one per reply, so with none left the
      reply confirms and stops — a card with none is done on the FIRST reply.
    * The previous reply asked nothing -> done: it judged that nothing related
      followed, or the person did not know, and wrapped up.
    * The previous answer fed no placement -> done: a "no idea" or an
      off-topic reply leaves the previous reply's ``placed`` null, and the
      conversation ends there rather than pressing on.

    ``related`` is a count or the related rows themselves. There is no
    `MAX_PROBES` here (owner amendment 2026-09-22, "no hard cap"): the related
    moments bound it. Moved from the platform's `work_item_walk.card_is_done`
    (v362), unchanged.
    """
    turns = _turn_rows(session)
    if not any(turn.get("role") == "user" for turn in turns):
        return False
    try:
        ceiling = len(related) if isinstance(related, (list, tuple)) else int(related or 0)
    except (TypeError, ValueError):
        ceiling = 0
    replies = [turn for turn in turns if turn.get("role") == "lifehug"]
    if ceiling - len(replies) <= 0:
        return True
    if not replies:
        return False
    last = replies[-1]
    if "?" not in str(last.get("text") or ""):
        return True
    return not last.get("placed")


def card_stage_for_session(session: object, *, related: object = 0) -> str:
    """`close` when :func:`card_is_done`, else :data:`WORK_ITEM_STAGE`."""
    return "close" if card_is_done(session, related=related) else WORK_ITEM_STAGE


def action_question_allowed(stage: object) -> bool:
    """May THIS reply of a Timeline-action conversation carry a question?

    ``False`` for a card's closing reply and for every reply of a move
    conversation: a host applies it to its own turn shape
    (`conversation_delivery.TurnShape.question_allowed`, the platform's
    `shape_question_allowed`), so a question the model writes anyway is
    withheld by the machinery that already withholds one — never left to the
    model's good behaviour.
    """
    return str(stage or "") not in ("close", MOVE_STAGE)


def card_known_years(target: object, session: object) -> tuple[str, ...]:
    """Every year a card reply may say: the target's own
    (:func:`work_item_known_years`) plus every year the person typed in this
    conversation — "January 2026" is his, so confirming it invents nothing."""
    years = list(work_item_known_years(target))
    for turn in _turn_rows(session):
        if turn.get("role") != "user":
            continue
        for match in chrono.YEAR_RE.finditer(str(turn.get("text") or "")):
            if match.group(0) not in years:
                years.append(match.group(0))
    return tuple(years)


def _subject_lines(subject: object) -> list[str]:
    who = subject if isinstance(subject, dict) else {}
    if not who or who.get("is_owner") or not who.get("name"):
        return []
    name = who["name"]
    lines = [f"**This moment is about {who.get('phrase') or name}, not about the "
             "person you are talking with.**"]
    facts = []
    if who.get("born"):
        facts.append(f"{name} was born {who['born']}")
    if facts:
        lines.append("- " + "; ".join(facts) + ".")
    pronoun = who.get("pronoun")
    third = f'"{name}"' + (f' or "{pronoun}"' if pronoun else "")
    lines += [
        f"- Speak of {name} in the third person — {third} — never \"you\" or",
        f'  "your" for {name}\'s life. "What drew you to it?" asks the wrong',
        "  person.",
        "- An age, a grade, a year, a season or a before/after in their answer",
        f'  belongs to {name} unless they say otherwise — "19" is how old {name} was,',
        "  never how old they were; \"freshman year\" is "
        f"{name}'s freshman year.",
        "- Never ask what they themselves remember of a time they may not have",
        "  lived.",
    ]
    return lines


#: The replies the owner has ruled out after a Timeline action — said once,
#: read by the block and by `lint_timeline_reply`'s `timeline_gates.one_job`.
STORY_BEAT_EXAMPLES = (
    "what pulled you toward…",
    "what led you to…",
    "tell me what happened",
    "what do you remember about…",
    "what comes to mind…",
    "that's worth sitting with",
    "why did you move it?",
)


def render_card_context(card: object, *, answered: bool, closing: bool) -> str:
    """The card block a card conversation's prompt carries, for THIS reply.

    Three phases, chosen by two transcript facts the host already has
    (:func:`card_answered` and :func:`card_is_done`):

    * not ``answered`` — ask the card's question and nothing else;
    * ``answered``, not ``closing`` — confirm in one line, then at most ONE
      question about one of the related moments, only if it follows;
    * ``closing`` (or nothing related) — confirm in one line and ask nothing.

    The block names the target (the question and the moment), the person it
    is about (:func:`subject_view`, third person), where it stands now, and the
    one job. It is the platform's former Timeline Fix 10 aside made the
    package's, with the 2026-09-26 context added.
    """
    view = card if isinstance(card, dict) else {}
    asked = _fold(view.get("question")) or "(the card carried no question in words)"
    lines = [
        CARD_HEADING,
        "",
        "They pressed ▸ on ONE card on their Timeline, and the card's question was",
        "already in front of them when they typed:",
        "",
        f"  «{asked}»",
        "",
    ]
    if _fold(view.get("label")):
        lines.append(f"- The moment: {_fold(view['label'])}")
    lines.append(f"- Where it stands now: {_fold(view.get('placement')) or 'not placed yet'}")
    lines.append("")
    subject_lines = _subject_lines(view.get("subject"))
    if subject_lines:
        lines += subject_lines + [""]
    lines += [
        "Your ONE job is this card's answer. This is NOT a story conversation: no",
        "reflective beat, no invitation to keep telling, no thread opened, and never",
        "a question about why — not " + ", ".join(f'"{x}"' for x in STORY_BEAT_EXAMPLES[:5])
        + ".",
        "",
    ]
    if not answered:
        lines += [
            "- They have not answered yet. Ask the card's question, in your own words,",
            "  and nothing else.",
        ]
        return "\n".join(lines)
    lines += [
        "- **Confirm in ONE line** what was filed, naming it in their own words and",
        '  using "placed", "filed" or "noted" — "Noted — <the moment>, <what they',
        '  said>." A grade, an age, a season or a stretch is a real landing. Never a',
        "  year they did not give you.",
        '- **"I don\'t know", a shrug, or a change of subject ends it.** Confirm',
        "  whatever still stands in one small true line and ask nothing.",
    ]
    related = [row for row in (view.get("related") or ()) if isinstance(row, dict)
               and _fold(row.get("label"))]
    if closing or not related:
        lines += [
            "- **Ask nothing.** This is the last reply of this conversation: the",
            "  one-line confirmation is the whole message.",
        ]
        return "\n".join(lines)
    lines += [
        "- **Then, ONLY if it follows from what they just said, ask ONE question",
        "  about one of these open moments — the same answer would also place them:**",
    ]
    for row in related:
        about = _fold(row.get("about"))
        lines.append(f"  - {_fold(row['label'])}" + (f" (about {about})" if about else ""))
    lines += [
        "  One per reply, about the person that moment is about. Skip any you have",
        "  already asked about. Never a moment that is not on this list. If none",
        "  follows naturally, ask nothing.",
    ]
    return "\n".join(lines)


# -- a MOVE ------------------------------------------------------------------

#: The relations a move can assert (the web's `OrderGesture` / membership /
#: containment acts), read into words for the confirmation line.
MOVE_RELATIONS = ("before", "after", "between", "within", "part_of",
                  "associated_with", "display")


def move_target(value: object) -> dict | None:
    """Normalize what a host knows about a move it just saved, or ``None``.

    A gesture carries no date by design (`docs/design/eras.md` §2.6 on the
    platform), so the facts are: the node and its label, the relation he
    asserted and the moments or landmark it names, and — only when the host
    computed one — the range it now spans (``range``, display text) and the
    landmark it landed inside (``inside``). ``None`` without a node id or a
    label: a confirmation about "node:…" is a machine spelling, never a line
    to show a person.
    """
    if not isinstance(value, dict):
        return None
    node_id = _fold(value.get("node_id") or value.get("key") or value.get("ref"))
    label = _fold(value.get("label"))
    if not node_id or not label or label == node_id:
        return None
    relation = _fold_key(value.get("relation"))
    if relation not in MOVE_RELATIONS:
        relation = ""
    anchors = [_fold(a) for a in (value.get("anchors") or ()) if _fold(a)][:2]
    return {
        "kind": MOVE_STAGE,
        "node_id": node_id,
        "label": label,
        "relation": relation,
        "anchors": anchors,
        "inside": _fold(value.get("inside")),
        "range": _fold(value.get("range")),
        "subject_ref": _fold(value.get("subject_ref")),
    }


def move_confirmation(move: object) -> str:
    """The one line a move conversation opens with — what moved and where it
    landed, then "Right?". Composed from facts only, never a date the host did
    not supply:

    * ``Moved “X” to June 1990–June 1991, inside Beauchamps. Right?``
    * ``Moved “X” inside Beauchamps. Right?``
    * ``Moved “X” — now before “Y”. Right?``
    * ``Moved “X”. Right?`` (nothing else known)
    """
    row = move_target(move) if not (isinstance(move, dict) and move.get("kind") == MOVE_STAGE) else move
    if not isinstance(row, dict):
        return ""
    text = f"Moved “{row['label']}”"
    inside = row.get("inside") or ""
    if not inside and row.get("relation") in ("within", "part_of", "associated_with") and row.get("anchors"):
        inside = row["anchors"][0]
    if row.get("range"):
        text += f" to {row['range']}"
        if inside:
            text += f", inside {inside}"
    elif inside:
        text += f" inside {inside}"
    elif row.get("relation") in ("before", "after") and row.get("anchors"):
        text += f" — now {row['relation']} “{row['anchors'][0]}”"
    elif row.get("relation") == "between" and len(row.get("anchors") or ()) == 2:
        text += (f" — now between “{row['anchors'][0]}” and "
                 f"“{row['anchors'][1]}”")
    return text + ". Right?"


def move_is_done(session: object) -> bool:
    """A move conversation is done once the person has replied at all: the
    reply to that reply confirms or takes the correction, and stops."""
    return card_answered(session)


def move_stage_for_session(session: object) -> str:
    """Always :data:`MOVE_STAGE` — the conversation has one reply to write."""
    return MOVE_STAGE


def render_move_context(move: object, *, subject: object = None) -> str:
    """The block a move conversation's prompt carries.

    Names what moved, what he asserted, where it landed, the confirmation line
    he was already shown, and the one job: a yes is "Noted." and stop; a
    correction IS the move — take it in one line, fill ``placed`` when it
    carries a time, and stop. Never why he moved it.
    """
    row = move_target(move) if not (isinstance(move, dict) and move.get("kind") == MOVE_STAGE) else move
    if not isinstance(row, dict):
        return ""
    lines = [
        MOVE_HEADING,
        "",
        f"They just moved “{row['label']}” on their Timeline, and it is already",
        "saved. The line in front of them when they typed was:",
        "",
        f"  «{move_confirmation(row)}»",
        "",
    ]
    if row.get("range"):
        lines.append(f"- Where it landed: {row['range']}")
    if row.get("inside"):
        lines.append(f"- Inside: {row['inside']}")
    if row.get("relation") and row.get("anchors"):
        lines.append(f"- What they asserted: {row['relation'].replace('_', ' ')} "
                     + " and ".join(f"“{a}”" for a in row["anchors"]))
    lines.append("")
    subject_lines = _subject_lines(subject)
    if subject_lines:
        lines += subject_lines + [""]
    lines += [
        "Your ONE job is to confirm the move. The move was theirs to make and it",
        "needs no reason: NEVER ask why they moved it, what made them change it, or",
        "anything about the story behind it.",
        "",
        '- **They agree** ("yes", "right", "correct"): reply "Noted." or one short',
        "  line that says the move stands. Nothing else.",
        "- **They correct it** (a different time, place or order): the correction IS",
        "  the move. Say in ONE line where it now goes, in their words (\"Got it —",
        "  spring 1991 instead.\"), and fill `placed` if the correction carries a",
        "  time. Never a year they did not give you.",
        "- **Ask nothing.** This is the only reply of this conversation.",
    ]
    return "\n".join(lines)


# --------------------------------------------------------------------------
# The closed validator for the one additive field
# --------------------------------------------------------------------------

def validate_placed(value: object, *, anchors: object = ()) -> dict | None:
    """Closed layer of the additive ``placed`` field.

    `value` is the structural layer's own output
    (`conversation_delivery._parse_placed`) or any other untrusted shape (this
    function re-checks shape itself so it is safe standalone). Returns a
    normalized date-record dict or `None`.

    v196: a RANGE WITH A BASIS is first-class — "about preschool, three to
    five" files as `{granularity: "range", earliest, latest, basis: "age"}`
    and is a finding, not a failure (`research/chronology.md` §1). There is no
    `{"deferred": true}` shape any more: saying you will find out is an
    ordinary answer that files nothing.

    The closed checks this layer owns, and `conversation_delivery` deliberately
    does not:

    * the three vocabularies (`chronology.GRANULARITIES|CONFIDENCES|BASES`);
    * EDTF parseability of `best`/`earliest`/`latest`;
    * **exact** membership of every anchor key in the anchors the CALLER
      supplied — an anchor this episode never showed the model is an invented
      anchor, and the record drops to `None`, exactly as
      `arc_walk.validate_answered_question_id` refuses an off-plan qid.
    """
    if not isinstance(value, dict) or not value:
        return None
    record = chrono.from_dict(value)
    if record is None:
        return None
    if chrono.to_edtf(record) is None:
        return None
    for bound in (record.earliest, record.latest):
        if bound is not None and chrono.parse_edtf(bound) is None:
            return None
    if record.best is not None and chrono.parse_edtf(record.best) is None:
        return None
    known = {row["key"] for row in _anchor_rows(anchors)}
    if any(anchor not in known for anchor in record.anchors):
        return None
    return record.to_dict()


class PlaceInvocation(NamedTuple):
    """ONE complete call to `lifehug.py timeline-place`: argv AND its stdin.

    The two travel together because the command cannot run without both —
    `cmd_timeline_place` reads the moment's description off stdin and exits 1
    when it is empty, so argv alone is not a call, it is half of one. They
    were two values once: `place_invocation` took a `description` and dropped
    it on the floor, `conversation_delivery._file_placement` ran the argv with
    no `input=`, and every date a person named in conversation exited 1 into a
    `place_failed` diagnostic (lifehug#223). A single return value makes that
    mistake unspeakable: a host that has the argv has the stdin too.

    ``stdin_text`` mirrors the name the durable-queue twin already uses
    (``jobs.Invocation.stdin_text``) — one vocabulary for "the text this
    command reads", whichever host is running it.
    """

    argv: list[str]
    stdin_text: str


#: O-E0c (lifehug-platform#686, defect 3): an era's own bounds have no
#: legitimate writer until E3's `era-record` exists. Filing a `period_bound`
#: answer through `timeline-place` is a WRONG JOIN — it lands on whatever
#: undated moment happens to sit in that era's lineup — and ADR 0026 ranks a
#: wrong join above a miss. The one typed reason a host logs for the refusal.
PLACE_REFUSED_NO_ERA_WRITER = "place_refused_no_era_writer"


def place_refusal(placed: object, item: object) -> str | None:
    """Why `place_invocation` would refuse to file this item, or `None`.

    Pure, and checked BEFORE the ordinary shape checks so a REFUSAL (an era's
    bounds, which has no writer yet) is never confused with an ordinary
    "nothing to file" (a missing source/period/description). `item` is
    whatever `timeline_item_for_turn` handed the turn — three shapes reach
    here today, and all three are covered:

    * a concrete `period_bound` unknown row (`item["kind"] == "period_bound"`,
      `timeline.unknowns`) — the direct case, and what the test plan
      constructs;
    * a whisper (`arc_planner._whisper_intent`), whose own `kind` is always
      the fixed `"timeline_gap"` but whose `gap_kind` carries the unknown's
      real kind;
    * a minted keystone question (`timeline_item_for_session`'s
      `kind == "keystone_question"`), whose identity is `item["anchor"]` —
      `"period:<slug>"` for an era keystone, `"entity:"`/`"event:"` for the
      two kinds that DO have a moment to write onto.

    `placed` is accepted (and unused past its presence) so the signature
    reads the same as every other placed-shaped check in this module, and so
    a future rule that inspects the accepted record itself is not a second
    call shape.
    """
    row = item if isinstance(item, dict) else {}
    if str(row.get("kind") or "") == "period_bound":
        return PLACE_REFUSED_NO_ERA_WRITER
    if str(row.get("gap_kind") or "") == "period_bound":
        return PLACE_REFUSED_NO_ERA_WRITER
    if str(row.get("anchor") or "").startswith("period:"):
        return PLACE_REFUSED_NO_ERA_WRITER
    return None


def place_invocation(placed: object, *, source: str, description: str,
                     period: str, placement_key: str = "",
                     item: object = None) -> PlaceInvocation | None:
    """The exact `lifehug.py timeline-place` call for an accepted placement.

    The package NAMES the date; the host WRITES it — the same split every
    other child's additive field uses (ADR 0018/0023). This is the bridge, and
    it is pure: a caller feeds `validate_placed`'s output in and gets the
    complete invocation out — argv plus the description the command reads on
    stdin — or `None` when there is nothing to file.

    The host's contract is one line::

        subprocess.run([..., *inv.argv], input=inv.stdin_text, text=True)

    `description` is REQUIRED for the same reason `source` and `period` are:
    an empty one is a call the CLI refuses, so it never becomes an argv here.
    It is clamped to `timeline.PLACEMENT_DESCRIPTION_MAX` HERE, once, so no
    host has to know the length — a host clamping on its own is half of how
    identity became two recipes (lifehug#228).

    `placement_key` is that identity, and it travels whole: an unknown row
    carries its event's own `timeline.placement_key`
    (`timeline.moment_unknown`), this passes it through as `--placement-key`,
    and the CLI stores it verbatim. Absent it the CLI derives the key from
    source + description exactly as it always has — which is right for the
    viewer's own placement form, where the description IS the event's.

    `item` is O-E0c's addition: passed through to `place_refusal` so this
    function refuses a `period_bound` item on its own, defense-in-depth for
    any future caller that does not check `place_refusal` itself. The one
    caller today (`conversation_delivery._file_placement`) checks it
    separately first, so it can log the typed reason before ever reaching
    here.
    """
    if place_refusal(placed, item) is not None:
        return None
    if not isinstance(placed, dict):
        return None
    record = chrono.from_dict(placed)
    if record is None or not source or not period or not str(description).strip():
        return None
    args = ["timeline-place", str(source), "--period", str(period)]
    key = str(placement_key or "").strip()
    if key:
        args += ["--placement-key", key]
    edtf = chrono.to_edtf(record)
    if edtf:
        args += ["--date", edtf]
    args += ["--basis", record.basis]
    for anchor in record.anchors:
        args += ["--anchor", anchor]
    when_hint = chrono.display_date(record, with_basis=False)
    if when_hint:
        args += ["--when-hint", when_hint]
    import timeline  # noqa: PLC0415

    return PlaceInvocation(args, str(description)[:timeline.PLACEMENT_DESCRIPTION_MAX])


# --------------------------------------------------------------------------
# Identity: whispers and keystone questions (v196)
# --------------------------------------------------------------------------
#
# A keystone becomes a question in exactly two ways, and BOTH are matched by
# the same identity — never by adjacency (a bank question whose focus merely
# resembles a keystone slug is not a keystone, which is the whole of
# lifehug/lifehug-platform#586):
#
#   * a WHISPER — the week's arc card carries the probe and the person's own
#     anchors, and the conversation raises it once, only where it fits; and
#   * a KEYSTONE QUESTION — the probe minted as an ordinary bank row, asked as
#     the day's question like any other, answered once, never re-asked.
#
# Everything here is pure: identity, the bank row, the bank text, the index
# back out of the bank, and the per-session lookups. The host does the writing.

#: The prefix every keystone identity carries. `tl:` is deliberately unlike a
#: bank id (`A14`, `G5c`) so a reader never has to guess which namespace it is
#: in, and the whole id is safe as a filename or a document key.
KEYSTONE_ID_PREFIX = "tl:"

#: Anchor keys can hold anything a slug can (`person/friend`, `my 30s`). A
#: document id that contains `/` becomes a path separator in half the stores
#: that will ever hold it, so identity is sanitized AT THE MINT, once.
_ID_UNSAFE_RE = re.compile(r"[^a-z0-9:._-]+")

#: The minted keystone question's home in the bank. One category, one group,
#: one tag — the group is what the weekly cap bounds, the tag is what
#: `timeline_probe_index` reads back out.
TIMELINE_CATEGORY_ID = "T"
TIMELINE_CATEGORY_NAME = "Timeline"
TIMELINE_GROUP = "timeline"
TIMELINE_BANK_TAG = "timeline_probe"

_BANK_TAG_RE = re.compile(
    r"^\s*<!--\s*" + TIMELINE_BANK_TAG +
    r":\s*(?P<keystone_id>\S+);\s*anchor:\s*(?P<anchor>[^;]+);"
    r"\s*leverage:\s*(?P<leverage>\d+)",
    re.MULTILINE,
)
_BANK_ROW_RE = re.compile(r"^- \[( |x)\] (?P<qid>[A-Z]\d+[a-z]*): (?P<text>.+)$")


def anchor_slug(anchor: object) -> str:
    """The thing behind an anchor key: `period:mesa` -> `mesa`."""
    return str(anchor or "").split(":", 1)[-1].strip()


def keystone_question_id(anchor: object) -> str:
    """`tl:<anchor-slug>` — the one identity a keystone is ever asked under."""
    slug = _ID_UNSAFE_RE.sub("-", anchor_slug(anchor).lower()).strip("-")
    return f"{KEYSTONE_ID_PREFIX}{slug}" if slug else ""


def is_timeline_probe(entry: object) -> bool:
    """Is this queue entry / arc intent / bank row a timeline ask?"""
    if not isinstance(entry, dict):
        return False
    if str(entry.get("kind") or "") == "timeline_gap":
        return True
    if str(entry.get("group") or "") == TIMELINE_GROUP:
        return True
    return str(entry.get("question_id") or "").startswith(KEYSTONE_ID_PREFIX)


def anchor_rows_for_prompt(anchors: object, *, limit: int = 8) -> list[dict]:
    """Anchor rows as PLAIN DATA — the shape a card, a prompt, or a projected
    envelope can carry, and the shape `validate_placed` accepts back."""
    rows = []
    for row in _anchor_rows(anchors)[:max(int(limit), 0)]:
        rows.append({
            "key": row["key"],
            "label": row["label"],
            "kind": row["kind"],
            "date": chrono.to_edtf(row["date"]) if row["date"] else None,
        })
    return rows


def whisper_from_keystone(keystone: object, *, gap: object = None) -> dict | None:
    """The arc-card timeline intent for one keystone row.

    ONE definition of the intent payload: `arc_planner` calls it, the prompt
    rendering below reads it, and the turn engine validates a placement
    against the very anchors it carries.
    """
    row = keystone if isinstance(keystone, dict) else {}
    anchor = str(row.get("anchor") or "").strip()
    probe = row.get("probe") if isinstance(row.get("probe"), dict) else {}
    text = str(probe.get("text") or "").strip()
    if not anchor or not text:
        return None
    gap_row = gap if isinstance(gap, dict) else {}
    intent = {
        "kind": "timeline_gap",
        "anchor": anchor,
        "question_id": row.get("question_id") or keystone_question_id(anchor),
        "probe": text,
        "probe_step": str(probe.get("step") or ""),
        "anchors": list(row.get("anchors") or []),
        "unknown_keys": list(row.get("unknown_keys") or row.get("resolves") or []),
        "leverage": int(row.get("leverage") or 0),
        "label": str(row.get("label") or anchor_slug(anchor)),
    }
    if gap_row:
        intent["gap_kind"] = str(gap_row.get("kind") or "")
        intent["period"] = gap_row.get("period")
    return intent


def render_whisper(item: object, *, with_anchors: bool = True) -> str:
    """How a timeline item reads in a prompt — the ONLY rendering of it.

    Deliberately not a script: the probe is the thing to draw out, the anchors
    are what the person has already given us to draw it out WITH.
    """
    row = item if isinstance(item, dict) else {}
    probe = str(row.get("probe") or "").strip()
    if not probe:
        return "timeline_gap"
    leverage = int(row.get("leverage") or 0)
    label = str(row.get("label") or "").strip()
    parts = [f"timeline_gap — ask, if it fits: \u201c{probe}\u201d"]
    if leverage and label:
        parts.append(f"(one answer would place {leverage} thing(s) around {label})")
    elif leverage:
        parts.append(f"(one answer would place {leverage} thing(s))")
    line = " ".join(parts)
    if not with_anchors:
        return line
    anchors = [a for a in (row.get("anchors") or []) if isinstance(a, dict)]
    if not anchors:
        return line
    rendered = "; ".join(
        f"{str(a.get('label') or a.get('key'))}"
        + (f" ({a['date']})" if a.get("date") else "")
        for a in anchors[:4]
    )
    return f"{line} — their own landmarks: {rendered}"


def category_from_anchor(anchor: object) -> str:
    """Which bank category a minted keystone question lands in.

    All of them land in one: the ask is about the timeline, not about the
    period the anchor happens to name, and one category is what makes the
    group cap a single readable number.
    """
    return TIMELINE_CATEGORY_ID


def mint_keystone_question(keystone: object, *, next_question_id: object,
                           category_from_anchor: object = category_from_anchor,
                           minted_at: str | None = None) -> dict | None:
    """One keystone -> one bank ROW (pure; the caller writes it).

    `next_question_id` is the bank's OWN allocator, injected — a callable
    `(category) -> "T3"` (or a plain id) — so this function never reads the
    vault and the host can REPLAY it. Returns `None` for a row that cannot be
    asked (no anchor, no probe text).
    """
    row = keystone if isinstance(keystone, dict) else {}
    anchor = str(row.get("anchor") or "").strip()
    probe = row.get("probe") if isinstance(row.get("probe"), dict) else {}
    text = " ".join(str(probe.get("text") or "").split())
    if not anchor or not text:
        return None
    category = str(category_from_anchor(anchor) if callable(category_from_anchor)
                   else category_from_anchor).upper()
    qid = str(next_question_id(category) if callable(next_question_id) else next_question_id)
    if not qid:
        return None
    keystone_id = row.get("question_id") or keystone_question_id(anchor)
    leverage = int(row.get("leverage") or 0)
    stamp = minted_at or now_utc()
    return {
        "id": qid,
        "category": category,
        "group": TIMELINE_GROUP,
        "text": text,
        "tag": TIMELINE_BANK_TAG,
        "anchor": anchor,
        "question_id": keystone_id,
        "leverage": leverage,
        "unknown_keys": list(row.get("unknown_keys") or row.get("resolves") or []),
        "anchors": list(row.get("anchors") or []),
        "minted_at": stamp,
        "line": (f"- [ ] {qid}: {text}\n"
                 f"  <!-- {TIMELINE_BANK_TAG}: {keystone_id}; anchor: {anchor}; "
                 f"leverage: {leverage}; minted: {stamp} -->"),
    }


def insert_keystone_question(question_bank_text: str, row: object) -> str:
    """Append a minted row to the bank text, creating `## Timeline` once.

    Pure string work, mirroring `question_candidates.insert_question` — the
    section header is what gives the category its `timeline` group, exactly as
    `## Focus` and `## Project` give theirs.
    """
    if not isinstance(row, dict) or not row.get("line"):
        return question_bank_text
    text = question_bank_text or ""
    header = f"## {TIMELINE_CATEGORY_ID}: {TIMELINE_CATEGORY_NAME}"
    if header not in text:
        section = (f"\n## Timeline\n\n{header}\n\n"
                   "<!-- Minted by the weekly planner from the timeline's own "
                   "keystones; asked once, answered once. -->\n")
        text = text.rstrip("\n") + "\n" + section
    index = text.index(header)
    tail = text.find("\n## ", index + len(header))
    end = len(text) if tail == -1 else tail
    body = text[index:end].rstrip("\n") + "\n" + str(row["line"]) + "\n"
    return text[:index] + body + text[end:]


def timeline_probe_index(question_bank_text: str) -> dict:
    """`{bank_id: {keystone_id, anchor, leverage, text}}` read back out of the
    bank's own provenance comments — how any caller knows the day's question
    IS a keystone."""
    text = question_bank_text or ""
    index: dict[str, dict] = {}
    lines = text.splitlines()
    for position, line in enumerate(lines):
        row = _BANK_ROW_RE.match(line)
        if not row or position + 1 >= len(lines):
            continue
        tag = _BANK_TAG_RE.match(lines[position + 1])
        if not tag:
            continue
        index[row.group("qid")] = {
            "question_id": tag.group("keystone_id"),
            "anchor": tag.group("anchor").strip(),
            "leverage": int(tag.group("leverage")),
            "text": row.group("text").strip(),
            "answered": row.group(1) == "x",
        }
    return index


def timeline_item_for_session(session: object, *, question_id: object = None,
                              probe_index: object = None) -> dict | None:
    """The timeline item this turn is carrying, or None — ONE definition.

    Two sources, in order: the day's question when it is a minted keystone
    (an exact `probe_index` hit), then the session's arc-card timeline intent
    (the whisper). Everything downstream — the stage, the output contract, the
    placement, the one-per-conversation rule — hangs off this one lookup.
    """
    index = probe_index if isinstance(probe_index, dict) else {}
    qid = str(question_id or "")
    minted = index.get(qid)
    if isinstance(minted, dict):
        item = dict(minted)
        item.setdefault("kind", "keystone_question")
        item["bank_question_id"] = qid
        return item
    doc = session if isinstance(session, dict) else {}
    arc = doc.get("arc") if isinstance(doc.get("arc"), dict) else {}
    for intent in (arc.get("intents") or []):
        if isinstance(intent, dict) and str(intent.get("kind")) == "timeline_gap":
            return dict(intent)
    return None


def timeline_asks_so_far(session: object) -> int:
    """How many turns in this session already raised the timeline.

    Read off the session document (`turn["timeline_probe_id"]`), never a new
    state file — the same posture `asked_from_supply` takes.
    """
    doc = session if isinstance(session, dict) else {}
    return sum(1 for turn in (doc.get("turns") or [])
               if isinstance(turn, dict) and turn.get("timeline_probe_id"))


def answer_timeline_probe(entry: object, reply: object,
                          anchors: object = None) -> dict | None:
    """The reply to a timeline ask -> a validated placement, or None.

    `reply` may be the raw model output (a JSON string), the parsed turn
    output, or the bare `placed` object; `anchors` defaults to the ones the
    entry itself carries, which is what makes the closed anchor check mean
    anything. "I'll find out" simply lands here as None: nothing to file.
    """
    row = entry if isinstance(entry, dict) else {}
    known = anchors if anchors is not None else row.get("anchors") or ()
    raw: object = reply
    if isinstance(reply, str):
        from conversation_delivery import parse_turn_output  # noqa: PLC0415
        parsed = parse_turn_output(reply)
        raw = parsed.get("placed") if isinstance(parsed, dict) else None
    elif isinstance(reply, dict) and "placed" in reply:
        raw = reply.get("placed")
    if raw is None:
        return None
    from conversation_delivery import _parse_placed  # noqa: PLC0415
    structural = _parse_placed(raw)
    if structural is None:
        return None
    return validate_placed(structural, anchors=known)


# --------------------------------------------------------------------------
# Lints (the five `timeline_gates.*` classes)
# --------------------------------------------------------------------------

TIMELINE_LINT_CLASSES = (
    "no_year_opener",
    "one_question_per_reply",
    "offers_bounds",
    "accepts_defer",
    "never_invents_a_date",
    # v196 (whispers): the timeline is raised ONCE in a conversation, where it
    # fits. A second ask is the interrogation the whole design refuses, and it
    # is the one rule a single reply cannot see on its own — the caller
    # counts, exactly as it counts `no_new_bound_streak`.
    "one_per_conversation",
    # v198 (ADR 0025's suggestive-interviewing hazard, Lindsay et al. 2004):
    # a session NEVER proposes a date and asks for agreement. True photographs
    # plus suggestive interviewing produced false memories in 65-66% of
    # participants — "the highest rate in any previously published study" —
    # and a dating probe
    # backed by the person's own evidence is precisely that configuration. The
    # system elicits readings and does the arithmetic; the person supplies
    # evidence, never confirmations. Shared verbatim with the landmarks lane
    # (`landmarks_interaction.LANDMARK_LINT_CLASSES`) — one definition, two
    # callers (recurring-defect doctrine).
    "never_proposes_a_date",
    # v362 (owner, 2026-09-26, `A_TIMELINE_ACTION_CONVERSATION_DOES_ONE_JOB`):
    # a conversation opened from a Timeline action does ONE job. After a
    # card's answer or a move, a story beat ("What pulled you toward
    # track?"), a question about why, or any question where the stage allows
    # none is the defect. Scored only on turns that name the action.
    "one_job",
    # v362: a card or a move about SOMEONE ELSE is spoken of in the third
    # person. A question that says "you"/"your" about a life that is not the
    # person typing's ("What pulled you toward track?" on a card about his
    # daughter) asks the wrong person. Scored only when the subject is not
    # the owner.
    "right_person",
)

#: v362: the replies the owner has ruled out after a Timeline action — a
#: reflective story beat, an invitation to keep telling, a question about why.
#: Matched anywhere in the reply, and only on a turn that names its action.
ONE_JOB_STORY_BEAT_RES = (
    re.compile(r"\bwhat\s+(?:pulled|drew|led|made|brought|got|inspired|prompted)\s+"
               r"(?:you|him|her|them|[A-Z][a-z]+)\s+(?:to|toward|towards|into|in)\b",
               re.IGNORECASE),
    re.compile(r"\bwhat\s+led\s+you\b", re.IGNORECASE),
    re.compile(r"\bworth\s+sitting\s+with\b", re.IGNORECASE),
    re.compile(r"\btell\s+me\s+(?:more|what\s+happened|about)\b", re.IGNORECASE),
    re.compile(r"\bwhat\s+do\s+you\s+remember\b", re.IGNORECASE),
    re.compile(r"\bwhat\s+comes\s+to\s+mind\b", re.IGNORECASE),
    re.compile(r"\bhow\s+did\s+(?:that|it)\s+feel\b", re.IGNORECASE),
    re.compile(r"\bwhy\s+(?:did|would)\s+you\b", re.IGNORECASE),
    re.compile(r"\bwhat\s+made\s+you\s+(?:move|change|put|drag|decide|want)\b",
               re.IGNORECASE),
)
_SECOND_PERSON_RE = re.compile(r"\b(?:you|your|yours|yourself)\b", re.IGNORECASE)
_QUESTION_SENTENCE_RE = re.compile(r"[^.!?\n]*\?")

#: The banned move: naming a date the person did not name and inviting a yes.
#: Reporting back a date the ARITHMETIC produced is different and allowed —
#: "you were twelve, so that puts it around 1986" states a derivation and
#: shows its working; "was it 1986?" asks for a confirmation.
PROPOSES_A_DATE_RES = (
    re.compile(r"\b(?:was|were|is|would)\s+(?:it|that|this|they|you)\s+"
               r"(?:in\s+)?(?:around\s+|about\s+|maybe\s+)?"
               r"(?:1[89]\d{2}|20\d{2})\b", re.IGNORECASE),
    re.compile(r"\b(?:sound|seem)s?\s+(?:about\s+)?right\s*\?"
               r"|\bdoes\s+(?:1[89]\d{2}|20\d{2})\s+sound\b", re.IGNORECASE),
    re.compile(r"\b(?:shall\s+we|let'?s|I'?ll)\s+(?:say|put\s+it\s+(?:at|down\s+as))\s+"
               r"(?:around\s+|about\s+)?(?:1[89]\d{2}|20\d{2})\b", re.IGNORECASE),
    re.compile(r"\bcan\s+I\s+put\s+(?:it\s+)?(?:down\s+)?(?:as|at)\s+"
               r"(?:1[89]\d{2}|20\d{2})\b", re.IGNORECASE),
)


def proposes_a_date(text: object) -> object:
    """The first span where a reply names a date and invites agreement.

    One definition, two callers: the timeline lane and the landmarks lane both
    run it, because "was it 1984?" is the same defect in both (ADR 0025's
    suggestive-interviewing hazard).
    """
    body = text if isinstance(text, str) else ""
    for pattern in PROPOSES_A_DATE_RES:
        match = pattern.search(body)
        if match:
            return match
    return None

#: `arc_planner.BANNED_PHRASE` is "what year", and that phrase must be a
#: SUBSTRING of the first pattern here — `test_the_year_demand_patterns_cover_
#: the_planners_banned_phrase` pins it, so the planner's ban and this lint can
#: never drift into two different rules (recurring-defect doctrine).
_YEAR_DEMAND_RES = (
    re.compile(r"\bwhat year\b", re.IGNORECASE),
    re.compile(r"\bwhich year\b", re.IGNORECASE),
    re.compile(r"\bin what year\b", re.IGNORECASE),
    re.compile(r"\bwhat\s+(?:was|were)\s+the\s+year\b", re.IGNORECASE),
    re.compile(r"\bcan you (?:give|tell) me (?:the|a) year\b", re.IGNORECASE),
)
#: A bounds probe OFFERS an interval or a choice; it never demands a point.
_BOUNDS_OFFER_RES = (
    re.compile(r"\bor\s+(?:is|would|was)\b", re.IGNORECASE),
    re.compile(r"\bsomewhere\b", re.IGNORECASE),
    re.compile(r"\bsometime\b", re.IGNORECASE),
    re.compile(r"\bbetween\b[^.?!]*\band\b", re.IGNORECASE),
    re.compile(r"\d{2,4}\s*[-–—]\s*\d{2,4}"),
    re.compile(r"\bbefore or after\b", re.IGNORECASE),
)
#: Pressing someone who has said they will find out.
_DEFER_PRESSURE_PHRASES = (
    "are you sure",
    "can you try",
    "take a guess",
    "best guess",
    "even a rough",
    "even roughly",
    "before we move on",
    "just give me",
    "surely you",
)
#: v218: `chronology.YEAR_RE`, the one year pattern (was an identical copy).
_YEAR_RE = chrono.YEAR_RE
_SPAN_LIMIT = 400


def _span_of(text: str, needle: str) -> list[int]:
    start = text.lower().find((needle or "").lower())
    if start == -1:
        return [0, min(len(text), _SPAN_LIMIT)]
    return [start, start + len(needle)]


def lint_timeline_reply(text: str, *, stage: str, probe_step: str | None = None,
                        known_years: object = (),
                        timeline_asks_so_far: int = 0,
                        action: str | None = None,
                        subject: object = None) -> list[dict]:
    """Deterministic findings for the five ``timeline_gates.*`` classes.

    Pure — no model, no I/O. `stage` is the same `{timeline_stage}` the leaf
    receives; an unrecognized stage is treated as `"place"` (fail toward the
    strictest ordinary rule). :data:`WORK_ITEM_STAGE` is scored exactly like
    `place` with ONE carve-out, marked below: the once-per-conversation rule
    is an ambient rule and a work-item episode is not ambient. `known_years`
    are the years the person or their anchors have already supplied — the only
    years a reply is allowed to assert (ruling 1's other half: record what was
    said, never invent).

    Findings share `conversation_lints.lint_turn`'s shape so a caller can
    merge them with the inherited Conversation findings uniformly.

    v362: ``action`` ("card" or "move") names a conversation opened from a
    Timeline action and turns on ``timeline_gates.one_job``; ``subject`` (a
    :func:`subject_view` dict, or a name) turns on
    ``timeline_gates.right_person`` when it is not the owner. Absent, both
    are silent and every existing caller's findings are unchanged.
    """
    body = text or ""
    if stage not in VALID_TIMELINE_STAGES:
        stage = "place"
    if action in ("card", "move") and not action_question_allowed(stage):
        # v362: a Timeline action's closing reply CONFIRMS — it asks nothing,
        # so the probe's rung (a card's `bounds` probe, say) no longer judges
        # it: "Noted — January 2026" is not a bounds question that failed to
        # offer bounds. It is scored as the rung that means "that's enough to
        # place it".
        probe_step = "convergence"
    findings: list[dict] = []
    findings += _one_job_findings(body, stage=stage, action=action)
    findings += _right_person_findings(body, subject=subject)

    if stage == "open" or probe_step in (None, "content", "residence", "role"):
        for pattern in _YEAR_DEMAND_RES:
            match = pattern.search(body)
            if match:
                findings.append({
                    "lint": "timeline_gates.no_year_opener",
                    "detail": "never open by asking for a calendar year — dating is "
                              "reconstructive inference; anchor first",
                    "span": [match.start(), match.end()],
                })
                break

    if body.count("?") > 1:
        findings.append({
            "lint": "timeline_gates.one_question_per_reply",
            "detail": "at most one question per reply — placing a memory is a "
                      "conversation, not an interrogation",
            "span": [0, min(len(body), _SPAN_LIMIT)],
        })

    if probe_step == "bounds" and not any(p.search(body) for p in _BOUNDS_OFFER_RES):
        findings.append({
            "lint": "timeline_gates.offers_bounds",
            "detail": "offer an interval or a choice ('spring 1998, or is "
                      "“sometime 97-99” more honest?'), never demand a point",
            "span": [0, min(len(body), _SPAN_LIMIT)],
        })

    lowered = body.lower()
    for phrase in _DEFER_PRESSURE_PHRASES:
        if phrase in lowered:
            findings.append({
                "lint": "timeline_gates.accepts_defer",
                "detail": f"a deferral is accepted, never pressed: {phrase!r}",
                "span": _span_of(body, phrase),
            })
            break
    else:
        if probe_step == "defer" and "?" in body:
            findings.append({
                "lint": "timeline_gates.accepts_defer",
                "detail": "when they say they will find out, receive it and ask nothing",
                "span": [0, min(len(body), _SPAN_LIMIT)],
            })

    try:
        asked_already = int(timeline_asks_so_far)
    except (TypeError, ValueError):
        asked_already = 0
    # `one_per_conversation` is an AMBIENT rule: it stops the timeline being
    # raised twice in a conversation the person opened to talk about something
    # else. A work-item episode IS the conversation they opened, and §2.2
    # allows "several progressively precise questions while the person remains
    # willing" there — so the class does not apply, and the willingness is
    # measured by `MAX_PROBES` and the no-new-bound streak instead.
    if (stage != WORK_ITEM_STAGE and asked_already >= 1 and "?" in body
            and probe_step not in (None, "convergence", "defer")):
        findings.append({
            "lint": "timeline_gates.one_per_conversation",
            "detail": "the timeline is raised once per conversation, where it "
                      "fits — a second ask is an interrogation",
            "span": [0, min(len(body), _SPAN_LIMIT)],
        })

    proposal = proposes_a_date(body)
    if proposal is not None:
        findings.append({
            "lint": "timeline_gates.never_proposes_a_date",
            "detail": "never name a date and ask them to agree — elicit the "
                      "evidence and do the arithmetic (Lindsay et al. 2004)",
            "span": [proposal.start(), proposal.end()],
        })

    allowed = {str(year) for year in (known_years or ())}
    for match in _YEAR_RE.finditer(body):
        if match.group(0) not in allowed:
            findings.append({
                "lint": "timeline_gates.never_invents_a_date",
                "detail": f"the reply asserts a year nobody supplied: {match.group(0)}",
                "span": [match.start(), match.end()],
            })
            break

    return findings


def _one_job_findings(body: str, *, stage: str, action: str | None) -> list[dict]:
    """`timeline_gates.one_job` — see :data:`TIMELINE_LINT_CLASSES`."""
    if action not in ("card", "move"):
        return []
    for pattern in ONE_JOB_STORY_BEAT_RES:
        match = pattern.search(body)
        if match:
            return [{
                "lint": "timeline_gates.one_job",
                "detail": "a Timeline action's conversation confirms and stops — "
                          "never a story beat or a question about why "
                          f"({match.group(0)!r})",
                "span": [match.start(), match.end()],
            }]
    if not action_question_allowed(stage) and "?" in body:
        return [{
            "lint": "timeline_gates.one_job",
            "detail": "this reply confirms and asks nothing — the action's one "
                      "job is done",
            "span": [0, min(len(body), _SPAN_LIMIT)],
        }]
    return []


def _right_person_findings(body: str, *, subject: object) -> list[dict]:
    """`timeline_gates.right_person` — see :data:`TIMELINE_LINT_CLASSES`."""
    if isinstance(subject, dict):
        if not subject or subject.get("is_owner"):
            return []
        name = str(subject.get("name") or "").strip()
    else:
        name = str(subject or "").strip()
        if not name or _subject_is_the_owner(name):
            return []
    if not name:
        return []
    for match in _QUESTION_SENTENCE_RE.finditer(body):
        sentence = match.group(0)
        if _SECOND_PERSON_RE.search(sentence) and name.lower() not in sentence.lower():
            return [{
                "lint": "timeline_gates.right_person",
                "detail": f"this moment is about {name}: speak of {name} in the "
                          "third person, never \"you\"",
                "span": [match.start(), match.end()],
            }]
    return []


# --------------------------------------------------------------------------
# The timeline plan (`lifehug.py arc-plan-target --timeline`)
# --------------------------------------------------------------------------

#: How many unknowns one timeline episode offers. Sized like an arc-walk
#: episode: enough to be worth opening, small enough to close before it drags.
DEFAULT_TIMELINE_PLAN_SIZE = 6


def build_timeline_plan(data: dict, *, era: str | None = None,
                        limit: int | None = None) -> dict:
    """Order this vault's unknowns for one Play: leverage, then playbook cost.

    Keystones lead and are starred (ruling 5). v196: there is no deferred
    lane — an unknown the person said they would find out is simply still
    outstanding, and it is offered again when the ordering says it is worth
    offering.

    `--timeline` is deliberately NOT an `arc_walk` target kind: an arc plan is
    a plan of BANK QUESTIONS and `arc_walk.normalize_target` requires bank
    categories, while a timeline unknown is neither. Keeping the closed roster
    closed is worth one extra plan builder (contract deviation 3).

    Leverage is `timeline.row_leverage` — the one definition `offered_unknowns`
    also reads off (issue #216: this function used to carry its own pre-v208
    copy of the arithmetic, which drifted from the self-inclusive `1 +
    len(resolves)` definition `offered_unknowns` moved to in v208).
    """
    import timeline  # noqa: PLC0415

    rows = list(data.get("unknowns") or timeline.unknowns(data))
    if era:
        wanted = str(era).strip().lower()
        rows = [row for row in rows
                if wanted == str(row.get("period") or "").lower()
                or wanted in [str(x).lower() for x in (row.get("between") or [])]]
    index = timeline.dependency_index(data)
    starred = {row["anchor"] for row in (data.get("keystones") or [])}
    for row in rows:
        row["resolves"], row["leverage"] = timeline.row_leverage(row, index)
        row["starred"] = row["key"] in starred
    rows.sort(key=lambda row: (
        not row["starred"],
        -int(row.get("leverage") or 0),
        int((row.get("probe") or {}).get("cost") or 99),
        row["key"],
    ))
    size = int(limit) if limit else DEFAULT_TIMELINE_PLAN_SIZE
    offered = rows[:max(size, 0)]
    return {
        "target": {"kind": "timeline", "ref": era or "all",
                   "label": f"the timeline ({era})" if era else "the timeline"},
        # v196: the counts live beside the questions, never as questions.
        "ledger": dict(data.get("unknown_ledger") or {}),
        "keystones": list(data.get("keystones") or []),
        "unknowns": rows,
        "offered": offered,
        "plan_n": len(rows),
    }


# --------------------------------------------------------------------------
# The era stage (E3) — one stretch of a life, one conversation
# --------------------------------------------------------------------------

#: The era ladder, spelled out (design §5.4). Read TOP DOWN and stop at the
#: first rung that is still open:
#:
#: 1. **bounds** — a `stretch` with an unbounded end. Everything else about an
#:    era is cheaper once it has edges, and an era with no end is the one
#:    thing that cannot be drawn.
#: 2. **residence** — the residence chain inside it. Where somebody lived is
#:    the strongest ordinary anchor there is and it dates several things at
#:    once.
#: 3. **events** — E-L2c (design §7.3): "what major events happened during
#:    {era}?", asked ONCE per era and re-openable, never a daily send. It is
#:    gated by `events_asked` (a caller-supplied marker, the same shape
#:    `precision_so_far` already is for the precision rung below — this
#:    module decides the NEXT rung given the asked-state; persisting that
#:    state durably is the caller's job, exactly as it already is for
#:    precision).
#: 4. **leverage** — the highest-leverage undated moment inside it, which is
#:    `timeline.row_leverage`'s own number and not a second one.
#: 5. **precision** — and only while cheap: era → year → season → month, stop
#:    at the first rung held WITHOUT hedging.
#:
#: A `thread` skips rung 1 outright: it has no honest end, and asking for one
#: is the question §4.5's whole kind distinction exists to stop asking.
ERA_LADDER = ("bounds", "residence", "events", "leverage", "precision")

#: The precision ladder, ascending, and it stops the moment the person holds a
#: rung without hedging. "Somewhere in the early nineties" IS an answer.
ERA_PRECISION_RUNGS = ("era", "year", "season", "month")

ERA_PROBES = {
    "bounds": {"step": "bounds", "cost": 2,
               "text": "When did {label} end?",
               "anchored": "Did {label} end before or after {anchor}?"},
    "residence": {"step": "residence", "cost": 2,
                  "text": "Where were you living during {label}?",
                  "anchored": "During {label}, were you still at {anchor}?"},
    # E-L2c §7.3. Asked once per era, never a daily send — the ladder's
    # `events_asked` gate is what makes this rung close after its one ask.
    "events": {"step": "events", "cost": 3,
              "text": "What major events happened during {label}?",
              "anchored": "What major events happened during {label}, "
                          "around {anchor}?"},
    "leverage": {"step": "parallel_domain", "cost": 4,
                 "text": "What else was going on during {label} — home, work, "
                         "anyone new around?",
                 "anchored": "During {label} — had {anchor} happened yet?"},
    "precision": {"step": "season", "cost": 7,
                  "text": "{label} — what time of year does the start of it "
                          "feel like?",
                  "anchored": "{label} — was the start of it before or after "
                              "{anchor}?"},
}


def era_target(value: object) -> dict | None:
    """Normalize an era Play target, or ``None``. Refusal never raises.

    Two shapes arrive and both are legitimate, exactly as they do for a work
    item: a Play target (`kind` is the Play kind, `ref` the era id) and a bare
    `era_identity.era_views` row. An unrecognized shape degrades to an
    ordinary turn rather than raising — a target this stage cannot read must
    not take the conversation down with it.
    """
    if not isinstance(value, dict) or not value:
        return None
    kind = str(value.get("kind") or "").strip()
    if kind and kind not in (ERA_STAGE, "frame", "named_era"):
        return None
    era_id = str(value.get("era_id") or value.get("ref") or "").strip()
    if not era_id:
        return None
    aliases = [str(a).strip() for a in (value.get("aliases") or ()) if str(a).strip()]
    return {
        "kind": ERA_STAGE,
        "era_id": era_id,
        "label": str(value.get("label") or value.get("headline") or era_id).strip(),
        "era_kind": str(value.get("era_kind") or "").strip(),
        "aliases": aliases,
        "bounded": bool(value.get("bounded")),
        "anchors": _anchor_rows(value.get("anchors")),
    }


def era_ladder_rung(target: object, *, rows: object = (),
                    precision_so_far: object = None,
                    events_asked: bool = False) -> dict | None:
    """The first OPEN rung of :data:`ERA_LADDER` for this era, or ``None``.

    ``rows`` are the era's own unknown rows (`build_timeline_plan(era=…)`'s
    `unknowns`), already leverage-ordered. ``None`` means every rung this
    conversation could climb is held, which is a real answer and the reason
    the stage can close on its own.

    ``events_asked`` gates the E-L2c "events" rung (§7.3): ``False`` (the
    default — a brand-new era) lets it fire once the residence rung is
    closed; a caller that has already asked it passes ``True`` and the
    ladder falls straight through to ``leverage``, exactly the pre-E-L2c
    sequence. Persisting that marker durably, per era, is the caller's job —
    the same division of labor this function already has with
    ``precision_so_far``.
    """
    row = era_target(target)
    if row is None:
        return None
    ordered = [item for item in (rows or ()) if isinstance(item, dict)]
    for rung in ERA_LADDER:
        if rung == "bounds":
            # A thread has no honest end. Never ask for one.
            if row["era_kind"] == "thread" or row["bounded"]:
                continue
            return {"rung": rung, **ERA_PROBES[rung]}
        if rung == "residence":
            found = next((item for item in ordered
                          if str(item.get("kind")) == "place_span"), None)
            if found is not None:
                return {"rung": rung, "row": found, **ERA_PROBES[rung]}
            continue
        if rung == "events":
            if events_asked:
                continue
            return {"rung": rung, **ERA_PROBES[rung]}
        if rung == "leverage":
            found = next((item for item in ordered
                          if str(item.get("kind")) != "place_span"), None)
            if found is not None:
                return {"rung": rung, "row": found, **ERA_PROBES[rung]}
            continue
        # precision — and only while cheap.
        if _precise_enough(precision_so_far, "period_bound"):
            return None
        return {"rung": rung, **ERA_PROBES[rung]}
    return None


#: The era stage's recorder leaf (design §5.4). The ADR 0028 loop, unchanged:
#: a SECOND model call after the reply is sent, with its own prompt, its own
#: output and its own blocking backstop — because one completion cannot both
#: be good company and file a fact, and it loses the fact.
ERA_RECORDER_PROMPT = "recorder.md"

#: The LLM purpose this pass spends its completion on: `date_record`, REUSED
#: (owner decision 21). Not a third purpose name and not a denominator move —
#: "what does hearing time cost" is one question with one answer, and the era
#: stage is another place it is heard, not another thing being bought.
ERA_RECORDER_PURPOSE = "date_record"


def load_era_recorder_leaf(framework_root: str | Path | None = None) -> str:
    """The era recorder leaf, verbatim but for the shared ``{how_words_arrive}``
    block (`lifehug_core.fill_how_words_arrive`). A host REPLAYs exactly this
    text."""
    base = (Path(framework_root) / "interactions" / "timeline"
            if framework_root else _SYSTEM_DIR.parent / "interactions" / "timeline")
    return fill_how_words_arrive(
        (base / "prompt" / ERA_RECORDER_PROMPT).read_text(encoding="utf-8"), framework_root)


def build_era_recorder_prompt(*, target: object, question_asked: str,
                              answer: str, reply: str = "",
                              known: object = (), reminder: str = "",
                              framework_root: str | Path | None = None) -> str:
    """The era recorder's whole prompt, from the leaf plus its substitutions.

    Deliberately NOT the conversation prompt: no identity, no behavior, no
    examples, no transcript. The era, what is already known about it, the
    question, what they said and what they were told — that is the entire
    evidence a recording decision needs, and leaving the rest out is what
    makes the second call small.
    """
    import temporal_claims as _tc  # noqa: PLC0415

    row = era_target(target) or {"label": "", "era_kind": "", "aliases": []}
    known_lines = [f"- {str(item).strip()}" for item in (known or ()) if str(item).strip()]
    filled = load_era_recorder_leaf(framework_root)
    # `.replace`, never `.format` — every leaf in this package substitutes the
    # same way, and these leaves carry literal JSON braces.
    for token, value in (
        ("{era_label}", row["label"] or "(unnamed)"),
        ("{era_kind}", row["era_kind"] or "not decided yet"),
        ("{era_aliases}", ", ".join(row["aliases"]) or "(none)"),
        ("{era_known}", "\n".join(known_lines) or "(nothing yet)"),
        ("{question_asked}", (question_asked or "").strip()),
        # Timeline Fix 05: MODEL_CLAIM_TYPES, not CLAIM_TYPES — the dateless
        # `occurrence` type is the deterministic classifier migration's alone
        # and is never offered to a model whose whole job is hearing time.
        # This keeps the composed prompt byte-identical across that release.
        ("{claim_types}", " | ".join(_tc.MODEL_CLAIM_TYPES)),
        ("{event_kinds}", _era_event_kinds()),
        ("{answer}", (answer or "").strip()),
        ("{reply}", (reply or "(no reply was generated)").strip()),
        ("{reminder}", f"\n\n{reminder.strip()}" if reminder else ""),
    ):
        filled = filled.replace(token, value)
    return filled


def _era_event_kinds() -> str:
    """The event-kind starting set, with the era's own two named first."""
    import general_listener as _gl  # noqa: PLC0415

    return " | ".join(("period_started", "period_ended")) + " | " + _gl.render_event_kinds()


def era_plan(data: dict, *, target: object, rows: object = None,
             limit: int | None = None, events_asked: bool = False) -> dict:
    """One era's Play plan: the era, its open rows, and the rung to ask next.

    `build_timeline_plan(era=…)` already scopes and orders the rows; this adds
    the era's own identity and the explicit ladder on top, so the caller does
    not re-derive either. Nothing here reads a vault or calls a model.
    ``events_asked`` passes straight through to :func:`era_ladder_rung`.
    """
    row = era_target(target)
    if row is None:
        raise TypeError("era_plan needs an era target")
    scoped = (rows if rows is not None
              else build_timeline_plan(data, era=row["era_id"], limit=limit))
    offered = list(scoped.get("offered") or ())
    rung = era_ladder_rung(row, rows=offered, events_asked=events_asked)
    return {
        "target": {"kind": ERA_STAGE, "ref": row["era_id"], "label": row["label"]},
        "era": row,
        "unknowns": list(scoped.get("unknowns") or ()),
        "offered": offered,
        "ladder": list(ERA_LADDER),
        "rung": rung,
        "plan_n": int(scoped.get("plan_n") or 0),
    }


# --------------------------------------------------------------------------
# The chain chooser — ONE definition, many hosts (E-L2c, §7.3, M7, ADR 0021)
# --------------------------------------------------------------------------
#
# "Go Dig's 'next, next, next' is the same walk" as the era Play ladder's
# residence rung (design M7): both ask "what is the next uncovered stretch
# in this chain?" over `landmarks_interaction.chain_coverage`. Under ADR
# 0021 that walk is defined ONCE and bound to both hosts, or it is a build
# failure — this function IS that one definition. `test_chain_coverage.py`'s
# `test_two_hosts_calling_the_one_function_pick_the_same_unit` proves two
# independent callers over one fixture vault pick the same next unit by
# construction: they call this function and nothing else. Wiring a real
# host to it — the era ladder's own "residence" rung
# (which still reads pre-computed `place_span` rows today, unchanged by
# this release) and a Go Dig page — is E-L4's and E-L6's, named here rather
# than silently assumed.


def next_chain_unit(landmarks: object, *, domain: object = None,
                    birth_year: object = None, as_of_year: object = None,
                    closures: object = ()) -> dict | None:
    """The next uncovered stretch across the chains, oldest first.

    ``domain`` narrows to one chain (`landmarks_interaction.CHAIN_DOMAINS`);
    ``None`` walks all three and returns the single earliest stretch across
    them, chain order breaking a tie. A chain the person has told to close
    for now (`landmarks_interaction.chain_is_closed`) is skipped here —
    closure suppresses ROUTINE prompting only (§8); the chain's gaps stay
    computed and drawn everywhere else, because this function is never the
    only reader of `chain_gaps`.

    ``None`` when every open chain is fully covered (or every chain is
    closed) — a real answer, not a degraded one.
    """
    import landmarks_interaction as li  # noqa: PLC0415

    if domain:
        wanted = str(domain).strip()
        domains = (wanted,) if wanted in li.CHAIN_DOMAINS else ()
    else:
        domains = li.CHAIN_DOMAINS
    candidates: list[dict] = []
    for name in domains:
        if li.chain_is_closed(name, closures):
            continue
        rows = li.chain_gaps(name, landmarks, birth_year=birth_year, as_of_year=as_of_year)
        if rows:
            candidates.append(rows[0])
    if not candidates:
        return None
    candidates.sort(key=lambda row: (
        int(row["years"][0]), li.CHAIN_DOMAINS.index(row["domain"]), row["key"],
    ))
    return candidates[0]


#: A moment that belongs to no era stays a row in Unknowns with NO question of
#: its own (§5.4). "Talk about this" opens the era stage with the moment as
#: visible context and NO era target, and the recorder's first move is the open
#: `parallel_domain` question — never "before or after you were born", which is
#: what the anchor-ordered opener asks a moment with nothing to hang on.
NO_ERA_FIRST_RUNG = "parallel_domain"


def no_era_moment_target(row: object) -> dict | None:
    """"Talk about this" on a moment in no era: context, and no era target.

    Returns the era-stage target shape with ``era_id`` absent and the moment
    carried as context, or ``None`` when the row is not a moment. The absence
    of an era id is the point: the conversation is grounded in the moment the
    person tapped and claims nothing about where it sits, and any date they
    say files on that moment's own `event_ref` (T-CV-13).
    """
    if not isinstance(row, dict) or not row:
        return None
    label = str(row.get("label") or row.get("key") or "").strip()
    if not label:
        return None
    probe = dict(PROBE_TEXTS)
    return {
        "kind": ERA_STAGE,
        "era_id": None,
        "label": label,
        "moment": {"key": str(row.get("key") or "").strip(), "label": label,
                   "event_ref": str(row.get("event_ref") or "").strip()},
        "rung": {"rung": NO_ERA_FIRST_RUNG,
                 "step": NO_ERA_FIRST_RUNG,
                 "cost": _STEP_BY_NAME[NO_ERA_FIRST_RUNG]["cost"],
                 "text": probe[NO_ERA_FIRST_RUNG]},
        "anchors": _anchor_rows(row.get("anchors")),
    }


def describe_timeline_plan(plan: dict) -> list[str]:
    lines = [f"Timeline plan — {plan['target']['label']}: "
             f"{len(plan['offered'])} of {plan['plan_n']} unknown(s) offered"]
    ledger = plan.get("ledger") or {}
    if ledger:
        lines.append(f"  ledger: {ledger.get('unplaced_moments', 0)} moment(s) "
                     f"in no period, {ledger.get('unplaced_pages', 0)} page(s) "
                     "sharing no sources")
    for row in plan.get("keystones") or []:
        lines.append(f"  ★ one answer would place {row['leverage']} thing(s): "
                     f"{row['label']} — {row['probe']['text']}")
    for row in plan["offered"]:
        star = "★ " if row.get("starred") else "  "
        lines.append(f"{star}[{row['kind']}] {row['label']}")
        lines.append(f"      probe ({row['probe']['step']}): {row['probe']['text']}")
    return lines


def main(argv: list[str] | None = None) -> int:
    import argparse  # noqa: PLC0415
    import json  # noqa: PLC0415

    import timeline  # noqa: PLC0415

    parser = argparse.ArgumentParser(description="Plan a timeline Play (read-only)")
    parser.add_argument("--era", default=None, help="Scope to one period slug")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    plan = build_timeline_plan(timeline.timeline_data(), era=args.era, limit=args.limit)
    if args.json:
        payload = json.loads(json.dumps(plan, default=str))
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print("\n".join(describe_timeline_plan(plan)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
