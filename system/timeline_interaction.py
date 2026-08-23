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
from lifehug_core import now_utc  # noqa: E402


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
        # With no landmark at all there is nothing to place it against, so the
        # honest opening is the moment itself — the one place the bare content
        # probe belongs.
        "text": "Tell me about {label} — just the moment itself, however it "
                "comes.",
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


def anchors_for_person(*, birth_date: object = None, periods: object = (),
                       places: object = (), events: object = (),
                       landmarks: object = None) -> tuple[dict, ...]:
    """The person's own dated landmarks, ordered — the life-history calendar.

    Birthday first (it dates everything else by arithmetic), then residences
    with spans, then eras with spans, then dated landmark moments. Residence
    and role are the natural index of lifetime periods (Conway &
    Pleydell-Pearce 2000), which is why "when we lived in X" outperforms "what
    year".

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
    anchor_label = anchor_rows[0]["label"] if anchor_rows else ""

    if _precise_enough(precision_so_far, row.get("kind")):
        step = "convergence" if "convergence" not in asked else "defer"
        return _probe(step, label, anchor_label)

    kind = str(row.get("kind") or "")
    opener = KIND_OPENERS.get(kind)
    if opener is not None and opener["step"] not in asked \
            and opener.get("anchored_step", opener["step"]) not in asked:
        between = [str(x) for x in (row.get("between") or [])]
        anchored = bool(anchor_label) and "anchored" in opener
        text = opener["anchored"] if anchored else opener["text"]
        return {
            "step": opener["anchored_step"] if anchored and "anchored_step" in opener
                    else opener["step"],
            "cost": opener["anchored_cost"] if anchored and "anchored_cost" in opener
                    else opener["cost"],
            "text": text.format(
                label=label, anchor=anchor_label or "that move",
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
    """
    kind = str(anchor_key or "").split(":", 1)[0]
    template = KEYSTONE_PROBES.get(kind, KEYSTONE_PROBES["event"])
    rows = _anchor_rows(anchors)
    anchor_label = ""
    for row in rows:
        if row["key"] and row["key"] not in str(anchor_key):
            anchor_label = row["label"]
            break
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


def place_invocation(placed: object, *, source: str, description: str,
                     period: str) -> list[str] | None:
    """The exact `lifehug.py timeline-place` argv for an accepted placement.

    The package NAMES the date; the host WRITES it — the same split every
    other child's additive field uses (ADR 0018/0023). This is the bridge, and
    it is pure: a caller feeds `validate_placed`'s output in and gets the
    argument vector out, or `None` when there is nothing to file.
    """
    if not isinstance(placed, dict):
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
    # v198 (go-deep.md §4.3, Lindsay et al. 2004): a session NEVER proposes a
    # date and asks for agreement. True photographs plus suggestive
    # interviewing produced false memories in 65-66% of participants — "the
    # highest rate in any previously published study" — and a dating probe
    # backed by the person's own evidence is precisely that configuration. The
    # system elicits readings and does the arithmetic; the person supplies
    # evidence, never confirmations. Shared verbatim with the landmarks lane
    # (`landmarks_interaction.LANDMARK_LINT_CLASSES`) — one definition, two
    # callers (recurring-defect doctrine).
    "never_proposes_a_date",
)

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
    run it, because "was it 1984?" is the same defect in both
    (`system/research/go-deep.md` §4.3).
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
_YEAR_RE = re.compile(r"\b(1[89]\d{2}|20\d{2})\b")
_SPAN_LIMIT = 400


def _span_of(text: str, needle: str) -> list[int]:
    start = text.lower().find((needle or "").lower())
    if start == -1:
        return [0, min(len(text), _SPAN_LIMIT)]
    return [start, start + len(needle)]


def lint_timeline_reply(text: str, *, stage: str, probe_step: str | None = None,
                        known_years: object = (),
                        timeline_asks_so_far: int = 0) -> list[dict]:
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

    try:
        asked_already = int(timeline_asks_so_far)
    except (TypeError, ValueError):
        asked_already = 0
    if asked_already >= 1 and "?" in body and probe_step not in (None, "convergence", "defer"):
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
                      "evidence and do the arithmetic (go-deep.md §4.3, "
                      "Lindsay et al. 2004)",
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
