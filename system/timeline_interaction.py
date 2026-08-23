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

_SYSTEM_DIR = Path(__file__).resolve().parent
if str(_SYSTEM_DIR) not in sys.path:
    sys.path.insert(0, str(_SYSTEM_DIR))

import chronology as chrono  # noqa: E402


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

#: The probe text per rung. `{label}` is the unknown, `{anchor}` the landmark.
#: None of these is a year question, and rung 1 is deliberately not about time
#: at all — dating is reconstructive inference, so content comes first
#: (Friedman 1993).
PROBE_TEXTS = {
    "content": "Tell me what happened — just the moment itself, however it comes.",
    "residence": "Where were you living when that happened?",
    "role": "What were you doing for work around then?",
    "parallel_domain": "What else was going on in your life then — home, work, "
                       "anyone new around?",
    "sequence": "Was that before or after {anchor}?",
    "landmark": "Had {anchor} happened yet when this took place?",
    "season": "What was the weather doing — what time of year does it feel like?",
    "bounds": "Would you say {label} sits inside one stretch, or is "
              "“somewhere in a couple of years” more honest?",
    "convergence": "That's enough to place it — does that sound right to you?",
    "defer": "No rush at all — find out whenever you like and tell me then.",
}

#: How precise this kind of unknown needs to be before the ladder stops. A
#: gap between two eras needs a year; a thin lineup only needs an era. Nothing
#: is ever pushed past its own slot's requirement (stop rule, §6.10).
TARGET_GRANULARITY = {
    "era_gap": "year",
    "no_chrono": "year",
    "no_events": "year",
    "all_undated": "year",
    "unplaced_events": "year",
    "date_contradiction": "season",
    "thin_lineup": "era",
    "unplaced_entities": "era",
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


def anchors_for_person(*, birth_date: object = None, periods: object = (),
                       places: object = (), events: object = ()) -> tuple[dict, ...]:
    """The person's own dated landmarks, ordered — the life-history calendar.

    Birthday first (it dates everything else by arithmetic), then residences
    with spans, then eras with spans, then dated landmark moments. Residence
    and role are the natural index of lifetime periods (Conway &
    Pleydell-Pearce 2000), which is why "when we lived in X" outperforms "what
    year".
    """
    rows: dict[str, dict] = {}
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
    granularity the probe is `convergence`, and a deferred unknown gets the
    `defer` line and is never pushed (ruling 5).
    """
    row = unknown if isinstance(unknown, dict) else {}
    anchor_rows = _anchor_rows(anchors)
    asked = {str(step) for step in (asked_steps or ())}
    label = str(row.get("label") or row.get("key") or "this moment").strip()
    anchor_label = anchor_rows[0]["label"] if anchor_rows else ""

    if row.get("deferred"):
        return _probe("defer", label, anchor_label)
    if _precise_enough(precision_so_far, row.get("kind")):
        step = "convergence" if "convergence" not in asked else "defer"
        return _probe(step, label, anchor_label)
    for step in PLAYBOOK_STEPS:
        if step["step"] in ("convergence", "defer"):
            continue
        if step["step"] in asked:
            continue
        if step["needs_anchor"] and not anchor_rows:
            continue
        return _probe(step["step"], label, anchor_label)
    return _probe("convergence" if "convergence" not in asked else "defer",
                  label, anchor_label)


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
VALID_TIMELINE_STAGES = frozenset({"open", "place", "close"})

#: Playbook stop rule §6.10 — "stop when two probes in a row return no new
#: bound". The caller counts; this module decides.
STOP_AFTER_UNPRODUCTIVE_PROBES = 2
#: And an absolute ceiling, so a placement episode can never become an
#: interrogation. Dating is never worth the relationship.
MAX_PROBES = 4


def timeline_stage_for_session(session: object, *, user_leaving: bool = False,
                               placement_settled: bool = False,
                               no_new_bound_streak: int = 0) -> str:
    """Derive `{timeline_stage}` from the transcript plus two caller facts.

    The caller facts mirror `arc_walk.arc_stage_for_session`'s `user_leaving`
    exactly: things only the caller can know (the router's departure signal,
    whether the placement it already accepted is good enough, and how many
    probes in a row produced no new bound). Everything else is read off the
    turns; no new session field is stored.
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
    if not any(isinstance(turn, dict) and turn.get("role") == "lifehug" for turn in turns):
        return "open"
    user_turns = sum(1 for turn in turns if isinstance(turn, dict) and turn.get("role") == "user")
    if user_turns >= MAX_PROBES:
        return "close"
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
# The closed validator for the one additive field
# --------------------------------------------------------------------------

DEFERRED_PLACED = {"deferred": True}


def validate_placed(value: object, *, anchors: object = ()) -> dict | None:
    """Closed layer of the additive ``placed`` field.

    `value` is the structural layer's own output
    (`conversation_delivery._parse_placed`) or any other untrusted shape (this
    function re-checks shape itself so it is safe standalone). Returns either
    `{"deferred": True}`, a normalized date-record dict, or `None`.

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
    if set(value) == {"deferred"}:
        return dict(DEFERRED_PLACED) if value.get("deferred") is True else None
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


def place_invocation(placed: object, *, source: str, description: str,
                     period: str) -> list[str] | None:
    """The exact `lifehug.py timeline-place` argv for an accepted placement.

    The package NAMES the date; the host WRITES it — the same split every
    other child's additive field uses (ADR 0018/0023). This is the bridge, and
    it is pure: a caller feeds `validate_placed`'s output in and gets the
    argument vector out, or `None` when there is nothing to file (a deferral
    is a memory, not a placement).
    """
    if not isinstance(placed, dict) or placed.get("deferred"):
        return None
    record = chrono.from_dict(placed)
    if record is None or not source or not period:
        return None
    args = ["timeline-place", str(source), "--period", str(period)]
    edtf = chrono.to_edtf(record)
    if edtf:
        args += ["--date", edtf]
    args += ["--basis", record.basis]
    for anchor in record.anchors:
        args += ["--anchor", anchor]
    when_hint = chrono.display_date(record, with_basis=False)
    if when_hint:
        args += ["--when-hint", when_hint]
    return args


# --------------------------------------------------------------------------
# Lints (the five `timeline_gates.*` classes)
# --------------------------------------------------------------------------

TIMELINE_LINT_CLASSES = (
    "no_year_opener",
    "one_question_per_reply",
    "offers_bounds",
    "accepts_defer",
    "never_invents_a_date",
)

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
_YEAR_RE = re.compile(r"\b(1[89]\d{2}|20\d{2})\b")
_SPAN_LIMIT = 400


def _span_of(text: str, needle: str) -> list[int]:
    start = text.lower().find((needle or "").lower())
    if start == -1:
        return [0, min(len(text), _SPAN_LIMIT)]
    return [start, start + len(needle)]


def lint_timeline_reply(text: str, *, stage: str, probe_step: str | None = None,
                        known_years: object = ()) -> list[dict]:
    """Deterministic findings for the five ``timeline_gates.*`` classes.

    Pure — no model, no I/O. `stage` is the same `{timeline_stage}` the leaf
    receives; an unrecognized stage is treated as `"place"` (fail toward the
    strictest ordinary rule). `known_years` are the years the person or their
    anchors have already supplied — the only years a reply is allowed to
    assert (ruling 1's other half: record what was said, never invent).

    Findings share `conversation_lints.lint_turn`'s shape so a caller can
    merge them with the inherited Conversation findings uniformly.
    """
    body = text or ""
    if stage not in VALID_TIMELINE_STAGES:
        stage = "place"
    findings: list[dict] = []

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


# --------------------------------------------------------------------------
# The timeline plan (`lifehug.py arc-plan-target --timeline`)
# --------------------------------------------------------------------------

#: How many unknowns one timeline episode offers. Sized like an arc-walk
#: episode: enough to be worth opening, small enough to close before it drags.
DEFAULT_TIMELINE_PLAN_SIZE = 6


def build_timeline_plan(data: dict, *, era: str | None = None,
                        limit: int | None = None) -> dict:
    """Order this vault's unknowns for one Play: leverage, then playbook cost.

    Keystones lead and are starred (ruling 5). Deferred unknowns are LISTED —
    the person can still see them — but never offered as the next question,
    which is the mechanical form of "never nags".

    `--timeline` is deliberately NOT an `arc_walk` target kind: an arc plan is
    a plan of BANK QUESTIONS and `arc_walk.normalize_target` requires bank
    categories, while a timeline unknown is neither. Keeping the closed roster
    closed is worth one extra plan builder (contract deviation 3).
    """
    import timeline  # noqa: PLC0415

    rows = list(data.get("unknowns") or timeline.unknowns(data))
    if era:
        wanted = str(era).strip().lower()
        rows = [row for row in rows
                if wanted == str(row.get("period") or "").lower()
                or wanted in [str(x).lower() for x in (row.get("between") or [])]]
    index = timeline.dependency_index(data)
    resolved_by = {}
    for anchor_key, keys in index.items():
        for key in keys:
            resolved_by[key] = max(resolved_by.get(key, 0), len(keys))
    starred = {row["anchor"] for row in (data.get("keystones") or [])}
    for row in rows:
        row["leverage"] = resolved_by.get(row["key"], 0)
        row["starred"] = row["key"] in starred
    rows.sort(key=lambda row: (
        not row["starred"],
        -int(row.get("leverage") or 0),
        int((row.get("probe") or {}).get("cost") or 99),
        row["key"],
    ))
    size = int(limit) if limit else DEFAULT_TIMELINE_PLAN_SIZE
    offered = [row for row in rows if not row.get("deferred")][:max(size, 0)]
    return {
        "target": {"kind": "timeline", "ref": era or "all",
                   "label": f"the timeline ({era})" if era else "the timeline"},
        "keystones": list(data.get("keystones") or []),
        "unknowns": rows,
        "offered": offered,
        "deferred": [row for row in rows if row.get("deferred")],
        "plan_n": len(rows),
    }


def describe_timeline_plan(plan: dict) -> list[str]:
    lines = [f"Timeline plan — {plan['target']['label']}: "
             f"{len(plan['offered'])} of {plan['plan_n']} unknown(s) offered"]
    for row in plan.get("keystones") or []:
        lines.append(f"  ★ one answer would place {row['leverage']} thing(s): "
                     f"{row['label']} — {row['probe']['text']}")
    for row in plan["offered"]:
        star = "★ " if row.get("starred") else "  "
        lines.append(f"{star}[{row['kind']}] {row['label']}")
        lines.append(f"      probe ({row['probe']['step']}): {row['probe']['text']}")
    for row in plan.get("deferred") or []:
        lines.append(f"  · deferred (quiet): {row['label']}")
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
