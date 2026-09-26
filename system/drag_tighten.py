"""Drag-to-tighten — a drop inside the landmark brackets narrows the moment.

The owner, 2026-09-26 (v365): *"That's a loose range that lets the user
drop it and make it tighter. Your system can use those landmarks as a way to
make those ranges tighter because if it fits within three, the smallest set of
those landmarks is the new added range."* / *"I don't want this to change how
the system works when movement happens today, other than to be additive. If it
is a more narrow range, move it and add more information. Yes the moments
above and below it are also information. And it counts as my statement.
Conflict brings it up."*

What this module is, and what it is not:

* It is ADDITIVE to the v232 drag (`lifehug.py timeline-move`). The move files
  its ordering constraint exactly as it always has; this module runs after,
  on the projection the person was LOOKING AT when they dropped, and decides
  whether the drop also says WHEN.
* The drop position is read off the move itself — ``between(A, B)`` is a drop
  between the rows A (above) and B (below); ``after(A)`` is the tail of a
  list, under A; ``before(B)`` is the head of a list, over B. ``within`` is a
  drop on a frame band, not a position among the brackets, and tightens
  nothing. The accessible Move menu files the same four relations, so the
  menu and the drag cannot drift into saying different things.
* The candidate window is the intersection of (a) the span of every landmark
  bracket drawn through the drop gap — home, school, work, mission; a blank
  lane adds nothing — and (b) the moments directly above and below: after the
  upper neighbour's START, before the lower neighbour's START (rows sort by
  their start, so a loose range sorts at its start and bounds at its start).
  At the head of a list the row above is the frame heading, and at the tail
  the row below is the next frame's heading, so those sides are bounded by
  the brackets alone.
* Month grain, always (*"the fidelity of a month is enough"*).
* It files only when the window is NARROWER than the moment's current
  placement, as the owner's own statement (claim basis ``explicit``, record
  basis ``stated``) — `temporal_timeline.AN_ANSWER_IS_THE_PLACEMENT` then
  places it like any other thing he said. A window that misses a date HE
  gave is filed all the same, and the fold's existing contradiction card
  asks which is right: never a silent move. Anything else is today's move,
  exactly.

The bracket a row shows (:func:`drawn_landmark`) is the same definition the
web's rails draw (`apps/web/app/(product)/timeline/views/landmark-palette.ts`
`coveringAt`): the latest-starting stay in that lane whose month span holds
the row's start month. One rule, read in two places.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

import chronology as chrono
import event_identity as ei
import temporal_claims as tc
import temporal_store as store
from temporal_claims import collapsed_text

#: The owner's ruling, as the rule's name (v365 (owner, 2026-09-26)).
A_DROP_INSIDE_LANDMARKS_TIGHTENS_TO_THEIR_OVERLAP = (
    "a moment dropped among the landmark brackets is placed, as the person's "
    "own statement at month grain, in the overlap of every bracket drawn "
    "through the drop and the moments directly above and below it — only when "
    "that is narrower than where it sat; a window that misses a date they gave "
    "is filed and raised as a question, never a silent move; anything else is "
    "the ordinary move"
)

#: v365 (owner, 2026-09-26), the landmark boundary lines: a drop just below a
#: boundary stack is "inside everything that starts here", just above one
#: "inside everything that ends here, up to its last month". The move names the
#: boundary as an extra anchor (``landmark:<entry_id>:<stay_index>:start|end``,
#: `landmark_fold.boundary_anchor`), read as a neighbour whose month is that
#: stay's start or end: the window is intersected with that stay's span. A move
#: without one decides exactly as before.
A_DROP_AT_A_BOUNDARY_IS_INSIDE_WHAT_STARTS_OR_ENDS_THERE = (
    "a drop just below a landmark boundary is inside every stay that starts "
    "there, and just above one inside every stay that ends there; the named "
    "stays' spans bound the window like any other bound"
)

#: v365 (owner, 2026-09-26), the empty-landmark row: a landmark with no rows inside
#: it (the MTC) is drawn as one slim row, and a drop INTO it names the whole
#: stay (``landmark:<entry_id>:<stay_index>:stay``). The window is that stay's
#: span intersected with the bands it sits in — the rows either side are
#: outside it by construction and bound nothing. A moment already inside it
#: is left as it is; one partly inside is narrowed to the part inside; one
#: wholly outside is placed inside it (a date he gave raises the question).
A_DROP_ON_AN_EMPTY_LANDMARK_IS_INSIDE_IT = (
    "a drop onto an empty landmark's row places the moment inside that stay's "
    "span, intersected with its bands, as the person's own statement at month "
    "grain; a moment already inside it is left as it is"
)

DRAG_TIGHTEN_RULE_VERSION = "drag-tighten:4"
EXTRACTOR_NAME = "drag-tighten"
EXTRACTOR_VERSION = "drag-tighten/rule:1"

#: The lane each landmarks-view domain draws in (`timeline_views`' span kinds;
#: the web's `FAMILY_OF_DOMAIN`).
FAMILY_OF_DOMAIN = {
    "residences": "home",
    "schools": "school",
    "work": "work",
    "missions": "mission",
    "military": "mission",
}
FAMILIES = ("home", "school", "work", "mission")
FAMILY_WORD = {"home": "home", "school": "school", "work": "work", "mission": "mission"}

#: The outcomes, by name. Only the first three file anything.
OUTCOME_TIGHTENED = "tightened"
OUTCOME_HIS_DATE_DISAGREES = "his_date_disagrees"
OUTCOME_REPLACES_INFERENCE = "replaces_inference"
OUTCOME_NOT_NARROWER = "not_narrower"
OUTCOME_NO_WINDOW = "no_window"
FILING_OUTCOMES = (OUTCOME_TIGHTENED, OUTCOME_HIS_DATE_DISAGREES, OUTCOME_REPLACES_INFERENCE)

MONTH_WORDS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun",
               "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")

OPEN_END = 10**9  # an ongoing stay with no clock to close it

_ISO_RE = re.compile(r"^(\d{4})(?:-(\d{2}))?(?:-(\d{2}))?")


# --------------------------------------------------------------------------
# Months
# --------------------------------------------------------------------------

def month_of(value: object, *, end: bool = False) -> int | None:
    """An ISO bound as a month index (``year * 12 + month - 1``). A bare year is
    its January as an earliest bound and its December as a latest one."""
    match = _ISO_RE.match(collapsed_text(value).lstrip("~?"))
    if not match:
        return None
    year = int(match.group(1))
    if match.group(2):
        return year * 12 + int(match.group(2)) - 1
    return year * 12 + (11 if end else 0)


def month_text(index: int) -> str:
    """``YYYY-MM``."""
    return f"{index // 12:04d}-{index % 12 + 1:02d}"


def month_words(index: int) -> str:
    """``Jun 1989``."""
    return f"{MONTH_WORDS[index % 12]} {index // 12}"


def window_words(window: dict) -> str:
    low, high = month_of(window["earliest"]), month_of(window["latest"])
    if low == high:
        return month_words(low)
    return f"{month_words(low)} – {month_words(high)}"


def _record_bounds(record: object) -> tuple[int | None, int | None]:
    if not isinstance(record, dict):
        return None, None
    best = collapsed_text(record.get("best"))
    parts = best.split("/") if "/" in best else [best, best]
    low = month_of(record.get("earliest")) if record.get("earliest") else None
    high = month_of(record.get("latest"), end=True) if record.get("latest") else None
    if low is None and parts[0] not in ("", ".."):
        low = month_of(parts[0])
    if high is None and parts[-1] not in ("", ".."):
        high = month_of(parts[-1], end=True)
    return low, high


# --------------------------------------------------------------------------
# Rows
# --------------------------------------------------------------------------

def placement_of(node: dict) -> dict | None:
    """The node's canonical placement record (the web's
    `canonicalPlacementDate`), or ``None``."""
    if node.get("usable_placement") is False:
        return None
    best = node.get("best_temporal_value")
    if node.get("usable_placement") is True and not isinstance(best, dict):
        best = node.get("possible_temporal_value")
    return best if isinstance(best, dict) else None


def row_start(node: dict) -> int | None:
    """The month a row sorts, and draws its brackets, at — its START.

    A span's own ``definition_span.start`` first, then the placement's earliest
    bound (then its latest, then its best), exactly as the web's `nodeSpan`
    reads ``from``: *"A loosely dated moment sorts at its start."*"""
    span = node.get("definition_span")
    start = span.get("start") if isinstance(span, dict) else None
    if isinstance(start, dict):
        for key in ("earliest", "latest", "best"):
            month = month_of(start.get(key))
            if month is not None:
                return month
    record = placement_of(node)
    if record is None:
        return None
    for key in ("earliest", "latest", "best"):
        month = month_of(record.get(key))
        if month is not None:
            return month
    return None


def _age_frames(projection: dict) -> list[tuple[int, int, dict]]:
    out = []
    for node in projection.get("nodes") or ():
        if not isinstance(node, dict) or node.get("node_kind") != "period":
            continue
        if collapsed_text(node.get("event_kind")) not in ("age_frame", ""):
            continue
        low, high = _record_bounds(node.get("best_temporal_value"))
        if low is not None and high is not None:
            out.append((low, high, node))
    return sorted(out, key=lambda row: row[0])


#: Owner, 2026-09-26: *"all bands should be additive… mission, Wetzikon, 20s
#: don't conflict but the subset narrow ranges for higher fidelity."* The band a
#: drop lands in — its age frame and any named era with a closed span holding
#: the drop — bounds the window exactly as a landmark bracket does. Dropping a
#: moment into Teen years says "when I was a teen", so it can never start
#: before the 13th birthday. Every bound is intersected; none overrides.
BANDS_ARE_BOUNDS_TOO = (
    "the age frame and any closed named era a drop lands in bound its window "
    "like a landmark bracket; all bounds intersect"
)


def bands_holding(projection: dict, month: int) -> list[tuple[int, int, dict]]:
    """Every period node (age frame or named era) whose closed span holds
    ``month`` — the bands a drop at that month sits inside."""
    out = []
    for node in projection.get("nodes") or ():
        if not isinstance(node, dict) or node.get("node_kind") != "period":
            continue
        low, high = _record_bounds(node.get("best_temporal_value"))
        if low is not None and high is not None and high < OPEN_END and low <= month <= high:
            out.append((low, high, node))
    return sorted(out, key=lambda row: row[0])


def frame_at(projection: dict, month: int) -> tuple[int, int, dict] | None:
    for low, high, node in _age_frames(projection):
        if low <= month <= high:
            return low, high, node
    return None


def next_frame_start(projection: dict, month: int) -> int | None:
    """The month the next frame's heading row draws at, below a list whose
    rows sit in the frame holding ``month`` (that frame's end when it is the
    last)."""
    frames = _age_frames(projection)
    for index, (low, high, node) in enumerate(frames):
        if low <= month <= high:
            if index + 1 < len(frames):
                following = frames[index + 1]
                return row_start(following[2]) or following[0]
            return high
    return None


# --------------------------------------------------------------------------
# Brackets
# --------------------------------------------------------------------------

def landmark_stays(projection: dict, *, now_month: int | None = None) -> list[dict]:
    """Every dated stay in the published ``landmarks_view``, as a bracket.

    ``{family, domain, entry_id, label, stay_index, start, end}`` with month
    indexes. An ongoing stay runs to ``now_month`` (or open); a stay with a
    start and no end that is not ongoing is its one month — the web's
    `coverSegments`, read the same way."""
    view = projection.get("landmarks_view")
    out: list[dict] = []
    for domain in (view or {}).get("domains") or ():
        family = FAMILY_OF_DOMAIN.get(collapsed_text(domain.get("domain")))
        if not family:
            continue
        for landmark in domain.get("landmarks") or ():
            name = collapsed_text(landmark.get("nickname")) or collapsed_text(landmark.get("label"))
            for stay in landmark.get("stays") or ():
                start = month_of(stay.get("start") or stay.get("end"))
                if start is None:
                    continue
                if stay.get("ongoing"):
                    end = now_month if now_month is not None else OPEN_END
                else:
                    end = month_of(stay.get("end") or stay.get("start"), end=True)
                if end is None or end < start:
                    continue
                out.append({
                    "family": family,
                    "domain": collapsed_text(domain.get("domain")),
                    "entry_id": collapsed_text(landmark.get("entry_id")),
                    "label": name,
                    "stay_index": int(stay.get("stay_index") or 0),
                    "start": start,
                    "end": end,
                    "ongoing": bool(stay.get("ongoing")),
                })
    return sorted(out, key=lambda row: (row["start"], row["end"], row["entry_id"]))


def drawn_landmark(stays: list[dict], family: str, month: int) -> dict | None:
    """The bracket a row at ``month`` shows in ``family``'s lane: the
    latest-starting stay whose month span holds it (a move month belongs to
    the stay it starts). ``None`` is a blank lane."""
    found = None
    for stay in stays:
        if stay["family"] == family and stay["start"] <= month <= stay["end"]:
            found = stay  # sorted by start: the last one wins
    return found


def _same(a: dict | None, b: dict | None) -> bool:
    return bool(a and b and (a["entry_id"], a["stay_index"]) == (b["entry_id"], b["stay_index"]))


def brackets_through(stays: list[dict], above: int, below: int) -> list[dict]:
    """Every bracket drawn continuously from the row at ``above`` to the row at
    ``below``: the same stay in its lane at both ends."""
    out = []
    for family in FAMILIES:
        top = drawn_landmark(stays, family, above)
        if _same(top, drawn_landmark(stays, family, below)):
            out.append(top)
    return out


# --------------------------------------------------------------------------
# The decision
# --------------------------------------------------------------------------

def _node_index(projection: dict) -> dict[str, dict]:
    return {collapsed_text(n.get("node_id")): n for n in projection.get("nodes") or ()
            if isinstance(n, dict) and collapsed_text(n.get("node_id"))}


def _label(node: dict | None) -> str:
    return collapsed_text((node or {}).get("label")) or collapsed_text((node or {}).get("node_id"))


def his_own_date(node: dict) -> bool:
    """Is the moment's current placement a date the person gave? The page's
    blue dot (`basis: explicit`)."""
    return collapsed_text(node.get("basis")) == "explicit"


def boundary_stays(stays: list[dict], anchors: object) -> tuple[list[dict], list[str]]:
    """The stays a move's boundary anchors name, each with its ``side``, and
    the anchors that name no drawn stay."""
    import landmark_fold  # noqa: PLC0415 - one anchor grammar

    found: list[dict] = []
    unknown: list[str] = []
    for text in anchors or ():
        parsed = landmark_fold.parse_boundary_anchor(text)
        stay = None
        if parsed is not None:
            entry_id, index, side = parsed
            stay = next((s for s in stays if s["entry_id"] == entry_id and s["stay_index"] == index), None)
        if stay is None:
            unknown.append(collapsed_text(text))
            continue
        found.append({**stay, "side": side, "anchor": collapsed_text(text)})
    return found, unknown


def decide(projection: object, *, subject_node_id: str, relation: str,
           anchor_node_ids: object, now_month: int | None = None,
           boundary_anchors: object = ()) -> dict:
    """:data:`A_DROP_INSIDE_LANDMARKS_TIGHTENS_TO_THEIR_OVERLAP`, as a decision.

    Pure: the published projection and the move in, a dict out. ``outcome`` is
    one of the ``OUTCOME_*`` names; only :data:`FILING_OUTCOMES` file."""
    payload = projection if isinstance(projection, dict) else {}
    nodes = _node_index(payload)
    subject = nodes.get(collapsed_text(subject_node_id))
    verb = collapsed_text(relation).lower()
    anchors = [collapsed_text(a) for a in (anchor_node_ids or ()) if collapsed_text(a)]
    result: dict = {
        "rule": "A_DROP_INSIDE_LANDMARKS_TIGHTENS_TO_THEIR_OVERLAP",
        "rule_version": DRAG_TIGHTEN_RULE_VERSION,
        "subject_node_id": collapsed_text(subject_node_id),
        "relation": verb,
        "outcome": OUTCOME_NO_WINDOW,
        "window": None,
        "current": None,
        "landmarks": [],
        "neighbours": {},
        "bands": [],
        "boundaries": [],
    }
    if subject is None or verb not in ("between", "after", "before"):
        result["why"] = "not a drop among the rows" if subject is not None else "moment not drawn"
        return result
    if verb == "between" and len(anchors) == 2:
        above, below = nodes.get(anchors[0]), nodes.get(anchors[1])
    elif verb == "after" and len(anchors) == 1:
        above, below = nodes.get(anchors[0]), None
    elif verb == "before" and len(anchors) == 1:
        above, below = None, nodes.get(anchors[0])
    else:
        result["why"] = "the move names no neighbours"
        return result
    top = row_start(above) if above else None
    bottom = row_start(below) if below else None
    if (above and top is None) or (below and bottom is None):
        result["why"] = "a neighbour has no date to bound it"
        return result
    stays = landmark_stays(payload, now_month=now_month)
    # The rows either side of the gap: the neighbours, or — at a list's head
    # and tail — the frame heading above and the next frame's heading below.
    edge_top, edge_bottom = top, bottom
    if edge_top is None:
        frame = frame_at(payload, bottom)
        edge_top = (row_start(frame[2]) or frame[0]) if frame else None
    if edge_bottom is None:
        edge_bottom = next_frame_start(payload, top)
    brackets = (brackets_through(stays, edge_top, edge_bottom)
                if edge_top is not None and edge_bottom is not None else [])
    # :data:`A_DROP_AT_A_BOUNDARY_IS_INSIDE_WHAT_STARTS_OR_ENDS_THERE`.
    edges, unknown = boundary_stays(stays, boundary_anchors)
    if unknown:
        result["boundaries_unknown"] = unknown
    held = {(b["entry_id"], b["stay_index"]) for b in brackets}
    brackets = brackets + [e for e in edges if (e["entry_id"], e["stay_index"]) not in held]
    result["boundaries"] = [
        {"anchor": e["anchor"], "family": e["family"], "entry_id": e["entry_id"],
         "label": e["label"], "stay_index": e["stay_index"], "side": e["side"],
         "month": month_text(e["start"] if e["side"] in ("start", "stay") else min(e["end"], OPEN_END - 1))}
        for e in edges
    ]
    inside = [e for e in edges if e["side"] == "stay"]
    if inside:
        return _decide_inside(result, payload, subject, inside,
                              neighbours=((above, top), (below, bottom)))
    # :data:`BANDS_ARE_BOUNDS_TOO` — the bands holding the drop: read at the
    # row above's start when there is one (the drop is under it, in its band),
    # else at the row below's.
    anchor_month = top if top is not None else bottom
    bands = bands_holding(payload, anchor_month) if anchor_month is not None else []
    low = max([m for m in [top, *(b["start"] for b in brackets), *(band[0] for band in bands)]
               if m is not None], default=None)
    high = min([m for m in [bottom, *(b["end"] for b in brackets), *(band[1] for band in bands)]
                if m is not None], default=None)
    result["bands"] = [
        {"node_id": collapsed_text(band[2].get("node_id")), "label": _label(band[2]),
         "start": month_text(band[0]), "end": month_text(band[1])}
        for band in bands
    ]
    result["landmarks"] = [
        {"family": b["family"], "domain": b["domain"], "entry_id": b["entry_id"],
         "label": b["label"], "stay_index": b["stay_index"],
         "start": month_text(b["start"]),
         "end": None if b["end"] >= OPEN_END else month_text(b["end"])}
        for b in brackets
    ]
    if above:
        result["neighbours"]["above"] = {"node_id": collapsed_text(above.get("node_id")),
                                         "label": _label(above), "start": month_text(top)}
    if below:
        result["neighbours"]["below"] = {"node_id": collapsed_text(below.get("node_id")),
                                         "label": _label(below), "start": month_text(bottom)}
    if low is None or high is None or high >= OPEN_END:
        result["why"] = "the drop is bounded on one side only"
        return result
    if low > high:
        result["why"] = "the neighbours and brackets leave no room"
        return result
    window = {"earliest": month_text(low), "latest": month_text(high)}
    result["window"] = window
    width = high - low + 1
    current = placement_of(subject)
    cur_low, cur_high = _record_bounds(current)
    result["current"] = {
        "best": collapsed_text((current or {}).get("best")) or None,
        "earliest": month_text(cur_low) if cur_low is not None else None,
        "latest": month_text(cur_high) if cur_high is not None else None,
        "his": his_own_date(subject),
    }
    current_width = (cur_high - cur_low + 1) if cur_low is not None and cur_high is not None else None
    if current_width is not None and width >= current_width:
        result["outcome"] = OUTCOME_NOT_NARROWER
        result["why"] = f"{window_words(window)} is no narrower than where it sits"
        return result
    fits = (cur_low is None or high >= cur_low) and (cur_high is None or low <= cur_high)
    if fits:
        result["outcome"] = OUTCOME_TIGHTENED
    elif his_own_date(subject):
        result["outcome"] = OUTCOME_HIS_DATE_DISAGREES
    else:
        result["outcome"] = OUTCOME_REPLACES_INFERENCE
    return result


def _decide_inside(result: dict, payload: dict, subject: dict, inside: list[dict], *,
                   neighbours: tuple) -> dict:
    """:data:`A_DROP_ON_AN_EMPTY_LANDMARK_IS_INSIDE_IT`."""
    result["rule"] = "A_DROP_ON_AN_EMPTY_LANDMARK_IS_INSIDE_IT"
    first = min(e["start"] for e in inside)
    bands = bands_holding(payload, first)
    low = max([e["start"] for e in inside] + [band[0] for band in bands])
    high = min([e["end"] for e in inside] + [band[1] for band in bands])
    result["bands"] = [
        {"node_id": collapsed_text(band[2].get("node_id")), "label": _label(band[2]),
         "start": month_text(band[0]), "end": month_text(band[1])}
        for band in bands
    ]
    result["landmarks"] = [
        {"family": e["family"], "domain": e["domain"], "entry_id": e["entry_id"],
         "label": e["label"], "stay_index": e["stay_index"],
         "start": month_text(e["start"]), "end": None if e["end"] >= OPEN_END else month_text(e["end"])}
        for e in inside
    ]
    for side, (node, month) in zip(("above", "below"), neighbours):
        if node is not None and month is not None:
            result["neighbours"][side] = {"node_id": collapsed_text(node.get("node_id")),
                                          "label": _label(node), "start": month_text(month)}
    if high >= OPEN_END:
        result["why"] = "the stay is still going on"
        return result
    if low > high:
        result["why"] = "the stay and its bands leave no room"
        return result
    current = placement_of(subject)
    cur_low, cur_high = _record_bounds(current)
    result["current"] = {
        "best": collapsed_text((current or {}).get("best")) or None,
        "earliest": month_text(cur_low) if cur_low is not None else None,
        "latest": month_text(cur_high) if cur_high is not None else None,
        "his": his_own_date(subject),
    }
    if cur_low is not None and cur_high is not None and low <= cur_low and cur_high <= high:
        result["window"] = {"earliest": month_text(low), "latest": month_text(high)}
        result["outcome"] = OUTCOME_NOT_NARROWER
        result["why"] = f"it is already inside {', '.join(e['label'] for e in inside)}"
        return result
    overlaps = (cur_low is None or high >= cur_low) and (cur_high is None or low <= cur_high)
    if overlaps:
        low = max(low, cur_low) if cur_low is not None else low
        high = min(high, cur_high) if cur_high is not None else high
        result["outcome"] = OUTCOME_TIGHTENED
    elif his_own_date(subject):
        result["outcome"] = OUTCOME_HIS_DATE_DISAGREES
    else:
        result["outcome"] = OUTCOME_REPLACES_INFERENCE
    result["window"] = {"earliest": month_text(low), "latest": month_text(high)}
    return result


# --------------------------------------------------------------------------
# Filing
# --------------------------------------------------------------------------

def decide_drop(projection: object, *, node: str, relation: str, anchors: object = (),
                boundaries: object = ()) -> dict:
    """READ-ONLY: what a drop WOULD tighten to — :func:`decide` exactly as
    `timeline-move` calls it before it files (the projection's own
    ``published_at`` month as "now"), with nothing filed.

    v365 (owner, 2026-09-26, "the view adjusts immediately"): the page asks
    this while the drag hovers so it can show the drop's window at once; the
    filing that follows decides again for itself. Every host calls THIS —
    `timeline-move-decide`, the hosted platform's ``…/timeline/move/decide``
    route and the local sandbox bridge — never a copy of the rule. Adds
    ``filing_outcomes`` (the outcomes that would file a window) and the
    ``projection_generation`` it was decided against."""
    seen = projection if isinstance(projection, dict) else {}
    listed = [collapsed_text(a) for a in (anchors or ()) if collapsed_text(a)]
    edges = [collapsed_text(b) for b in (boundaries or ()) if collapsed_text(b)]
    decision = decide(seen, subject_node_id=collapsed_text(node), relation=collapsed_text(relation),
                      anchor_node_ids=listed, now_month=month_of(seen.get("published_at")),
                      boundary_anchors=edges)
    return {**decision, "filing_outcomes": list(FILING_OUTCOMES),
            "projection_generation": seen.get("projection_generation")}


def evidence_sentence(decision: dict, *, subject_label: str = "") -> str:
    """What the drop said, in words, for the claim's evidence: the window, the
    brackets and the neighbours it came from."""
    window = decision.get("window") or {}
    parts = [f"Dropped {subject_label or 'this moment'} on the timeline: {window_words(window)}."]
    marks = decision.get("landmarks") or []
    if marks:
        parts.append("Inside " + ", ".join(f"{m['label']} ({FAMILY_WORD[m['family']]})" for m in marks) + ".")
    for edge in decision.get("boundaries") or []:
        when = month_words(month_of(edge["month"]))
        if edge["side"] == "stay":
            continue  # named with the landmarks, "Inside MTC (mission)."
        parts.append(f"Just after {edge['label']} began ({when})." if edge["side"] == "start"
                     else f"Before {edge['label']} ended ({when}).")
    bands = decision.get("bands") or []
    if bands:
        parts.append("Within " + ", ".join(b["label"] for b in bands) + ".")
    near = decision.get("neighbours") or {}
    if near.get("above"):
        parts.append(f"After {near['above']['label']}.")
    if near.get("below"):
        parts.append(f"Before {near['below']['label']}.")
    return " ".join(parts)


def _record(window: dict) -> dict:
    low, high = window["earliest"], window["latest"]
    return chrono.DateRecord(
        best=low if low == high else f"{low}/{high}",
        earliest=low, latest=high,
        granularity="month" if low == high else "range",
        confidence="certain", basis="stated",
    ).to_dict()


def _subject_ref(node: dict) -> str:
    refs = [collapsed_text(r) for r in (node.get("subject_refs") or ()) if collapsed_text(r)]
    return refs[0] if len(refs) == 1 else "self"


def file_tightening(vault_root: str | Path, *, constraint: dict, decision: dict,
                    subject: dict, now: object = None) -> dict:
    """File the drop's window as the person's own date claim on the moment.

    ONE receipt, citing the move's own correction source (the source the
    `timeline-move` path already filed), with one ``date`` claim aimed at the
    moment (``event_ref`` = its node, the `answer_placement.aim_at_card`
    seat), claim basis ``explicit``, record basis ``stated``, month grain. The
    receipt's extractor block names the brackets and neighbours it came from.
    Idempotent: `temporal_store.write_receipt` keeps what is on disk."""
    root = Path(str(vault_root))
    ref = store.read_source_ref(root, constraint["relative_path"])
    if ref is None:
        raise store.TemporalStoreError("drag_tighten_source_unreadable",
                                       f"{constraint['relative_path']} is not a filed source")
    source_ref = {"source_id": ref.source_id, "revision": ref.revision,
                  "source_path": ref.source_path or constraint["relative_path"]}
    node_id = collapsed_text(subject.get("node_id"))
    label = _label(subject)
    claim = tc.validate_temporal_claim({
        "source_ref": source_ref,
        "source_kind": "correction",
        "claim_type": "date",
        "subject_mention": _subject_ref(subject),
        "event_kind": collapsed_text(subject.get("event_kind")) or "moment",
        "event_ref": node_id,
        "event_mention": label[:tc.MAX_EVENT_MENTION_CHARS],
        "temporal_value": _record(decision["window"]),
        "evidence": [{"quote": tc.bounded_quote(evidence_sentence(decision, subject_label=label))}],
        "basis": "explicit",
        "confidence": 0.9,
        "extractor_version": EXTRACTOR_VERSION,
    }, now=now)
    extractor = ei.declare_tellings(
        {"name": EXTRACTOR_NAME,
         "rule_version": EXTRACTOR_VERSION.rsplit(":", 1)[-1],
         "deterministic": True,
         "rule": decision["rule"],
         "outcome": decision["outcome"],
         "constraint_id": constraint["constraint_id"],
         "window": decision["window"],
         "landmarks": decision.get("landmarks") or [],
         "boundaries": decision.get("boundaries") or [],
         "neighbours": decision.get("neighbours") or {},
         "current": decision.get("current")},
        telling_keys={claim["claim_id"]: ei.conversation_telling_ref(
            ref.source_id, node_id.split(":")[-1])},
    )
    path = store.write_receipt(root, {
        "source_ref": source_ref,
        "extractor_version": EXTRACTOR_VERSION,
        "extractor": extractor,
        "claims": [claim],
    }, now=now)
    return {"claim_id": claim["claim_id"], "receipt_path": str(path),
            "window": decision["window"], "outcome": decision["outcome"]}


def tightening_claim_ids(vault_root: str | Path, constraint: dict) -> list[str]:
    """The claim ids a move's tightening receipt holds (``[]`` for a move that
    tightened nothing) — what its undo retracts."""
    root = Path(str(vault_root))
    ref = store.read_source_ref(root, constraint.get("relative_path") or "")
    if ref is None:
        return []
    source_ref = {"source_id": ref.source_id, "revision": ref.revision,
                  "source_path": ref.source_path or constraint["relative_path"]}
    path = store.receipt_path(root, source_ref, EXTRACTOR_VERSION)
    try:
        stored = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return sorted(collapsed_text(c.get("claim_id")) for c in stored.get("claims") or ()
                  if isinstance(c, dict) and collapsed_text(c.get("claim_id")))


def undo_tightening(vault_root: str | Path, constraint: dict, *, reason: str,
                    author: str | None = None, now: object = None) -> list[str]:
    """Retract a move's tightening claim with the move (one retraction,
    idempotent). Returns the claim ids retracted."""
    ids = tightening_claim_ids(vault_root, constraint)
    if ids:
        store.retract_claims(vault_root, ids, reason=reason,
                             title=f"Undo the drop's window ({constraint['constraint_id']})",
                             author=author, occurred_at=now)
    return ids


def summary_digest(decision: dict) -> str:
    """A short stable digest of a decision, for logs."""
    blob = json.dumps({k: decision.get(k) for k in ("window", "landmarks", "neighbours", "outcome")},
                      sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:12]
