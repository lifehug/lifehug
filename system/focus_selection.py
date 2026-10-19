#!/usr/bin/env python3
"""A Focus is a queue preference; selection is one field (v423, ADR 0046).

The owner's ruling (2026-10-19): "A focus is a preference to get a question in
the question queue — it gets a higher chance of being the daily question. To
remove a focus should only mean that it's no longer preferential in the queue,
not anything more, no deletion or anything."

So a Focus carries ONE boolean on its roadmap row, `selected` (absent means
`True`), orthogonal to `phase`, plus a small receipt of who last changed it:

    {"selected": false,
     "selection": {"by": "sweep" | "owner", "at": "<iso>",
                   "reason": "tier_target" | "complete" | "removed" | "added"
                             | "reopened"}}

Selected, the Focus carries its tier weight in the planner exactly as before.
Unselected, `question_planner.focus_weight` returns 0.0 (as for a complete
Focus), the autopilot's keep-3-developing count skips it, and the viewer's
Foundation list leaves it out. NOTHING ELSE reads the flag: the category, every
question, the answers, the roster link and the wiki page are untouched, and an
unselected Focus's open questions can still arrive by coverage rotation.

This module is the one definition. The planner, the weekly sweep, the
autopilot, the CLI and the viewer import it; reading `selected` inline
anywhere else fails the build (tests/test_v423_focus_selection.py).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

SYSTEM_DIR = Path(__file__).resolve().parent
if str(SYSTEM_DIR) not in sys.path:
    sys.path.insert(0, str(SYSTEM_DIR))

from lifehug_core import now_utc, write_json  # noqa: E402

#: Who changed a selection. The owner's word is never undone by the sweep.
BY_OWNER = "owner"
BY_SWEEP = "sweep"
BYS = (BY_OWNER, BY_SWEEP)

#: Why. `tier_target` / `complete` are the sweep's; `added` / `removed` the owner's.
REASON_TIER_TARGET = "tier_target"
REASON_COMPLETE = "complete"
REASON_REMOVED = "removed"
REASON_ADDED = "added"
#: The sweep's own undo: a Focus it rested as complete reopened (ADR 0044).
REASON_REOPENED = "reopened"
REASONS = (REASON_TIER_TARGET, REASON_COMPLETE, REASON_REMOVED, REASON_ADDED,
           REASON_REOPENED)

#: The rule, by name: a Focus is a preference in the queue, nothing more.
A_FOCUS_IS_A_QUEUE_PREFERENCE = (
    "Removing a Focus only stops it being preferred in the question queue; "
    "nothing is deleted, and adding it back restores its preference."
)
#: The rest rule, by name (design D1): the bar's 100% is the tier target.
A_FOCUS_AT_ITS_TARGET_RESTS = (
    "A non-primary Focus whose answered count reaches its tier target, or that "
    "is complete, is unselected by the weekly sweep, unless the owner selected it."
)


def is_selected(focus: dict) -> bool:
    """Is this Focus preferred in the queue? Absent means yes."""
    return bool(focus.get("selected", True))


def _set(focus: dict, value: bool, *, by: str, reason: str, now: str | None) -> bool:
    if by not in BYS:
        raise ValueError(f"unknown selection actor {by!r}; choose from {', '.join(BYS)}")
    if reason not in REASONS:
        raise ValueError(f"unknown selection reason {reason!r}; choose from {', '.join(REASONS)}")
    prior = focus.get("selection") or {}
    if is_selected(focus) == value and prior.get("by") == by and prior.get("reason") == reason:
        return False  # idempotent: the same word twice changes nothing
    focus["selected"] = value
    focus["selection"] = {"by": by, "at": now or now_utc(), "reason": reason}
    return True


def select(focus: dict, *, by: str, reason: str, now: str | None = None) -> bool:
    """Mark the Focus selected. Returns whether anything changed."""
    return _set(focus, True, by=by, reason=reason, now=now)


def unselect(focus: dict, *, by: str, reason: str, now: str | None = None) -> bool:
    """Mark the Focus unselected. Returns whether anything changed."""
    return _set(focus, False, by=by, reason=reason, now=now)


def should_rest(focus: dict, fill: dict) -> bool:
    """Should the weekly sweep unselect this Focus? (A_FOCUS_AT_ITS_TARGET_RESTS)

    Selected, at or past its tier target (`fill["saturation"] >= 1.0`) or
    complete (ADR 0044), and not last selected by the owner: an owner's
    explicit add is never undone by the sweep.
    """
    from roadmap import is_complete  # noqa: PLC0415

    return (is_selected(focus)
            and (float(fill.get("saturation") or 0.0) >= 1.0 or is_complete(focus, fill))
            and (focus.get("selection") or {}).get("by") != BY_OWNER)


def reopen_selection(focus: dict, *, when: str | None = None) -> bool:
    """A complete Focus reopened (a new question was approved into its
    category, ADR 0044). If the sweep had rested it BECAUSE it was complete,
    the reason no longer holds: select it again as the sweep's own undo. An
    owner's Remove and a rest at the tier target are left alone (the next
    sweep re-judges the target). Returns whether anything changed."""
    selection = focus.get("selection") or {}
    if is_selected(focus) or selection.get("by") != BY_SWEEP \
            or selection.get("reason") != REASON_COMPLETE:
        return False
    return select(focus, by=BY_SWEEP, reason=REASON_REOPENED, now=when)


def selection_row(focus: dict) -> dict:
    """The additive fields a reader prints: `selected` and `selection`."""
    return {"selected": is_selected(focus), "selection": focus.get("selection")}


# --------------------------------------------------------------------------
# CLI (reached through `lifehug.py focus-select` / `focus-unselect`)
# --------------------------------------------------------------------------


def set_by_owner(focus_id: str, value: bool, *, now: str | None = None) -> dict:
    """The owner's Add (value=True) or Remove (value=False). Writes the roadmap.
    Raises LookupError for an unknown id."""
    import roadmap as roadmap_mod  # noqa: PLC0415

    rm = roadmap_mod.load_roadmap()
    if not rm.get("focuses"):
        rm = roadmap_mod.rebuild_roadmap(write=False)
    focus = roadmap_mod.find_focus(rm, focus_id)
    if not focus:
        raise LookupError(f"No such focus: {focus_id}")
    when = now or now_utc()
    if value:
        changed = select(focus, by=BY_OWNER, reason=REASON_ADDED, now=when)
    else:
        changed = unselect(focus, by=BY_OWNER, reason=REASON_REMOVED, now=when)
    if changed:
        rm["generated_at"] = when
        write_json(roadmap_mod.ROADMAP_FILE, rm)
    return {"focus": focus.get("id"), "label": focus.get("label"), "changed": changed,
            **selection_row(focus)}


def cli(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Select or unselect a Focus: a queue preference, nothing more (ADR 0046)")
    sub = parser.add_subparsers(dest="cmd", required=True)
    for name, text in (("select", "Prefer this Focus in the question queue again"),
                       ("unselect", "Stop preferring this Focus in the queue; nothing is deleted")):
        p = sub.add_parser(name, help=text)
        p.add_argument("focus_id")
        p.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    try:
        result = set_by_owner(args.focus_id, args.cmd == "select")
    except LookupError as exc:
        if args.json:
            print(json.dumps({"error": "unknown_focus", "focus": args.focus_id}, sort_keys=True))
        else:
            print(f"✗ {exc}")
        return 1
    if args.json:
        print(json.dumps(result, sort_keys=True))
    else:
        state = "selected" if result["selected"] else "unselected"
        note = "" if result["changed"] else " (unchanged)"
        print(f"✓ {result['label'] or result['focus']} is {state}{note}")
    return 0


if __name__ == "__main__":
    raise SystemExit(cli())
