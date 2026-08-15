#!/usr/bin/env python3
"""Lifehug — the Focus/idea duplicate damage list (read-only, zero AI).

Detects, but never resolves, the duplicate/near-duplicate Focus classes the
focus-duplicate-curation contract names:

    (a) roadmap focuses whose normalized_focus_key collide — certain
        duplicates (the "fear"/"Fear" class the door guards in roadmap.py
        block going forward, but a roadmap.json written before those guards
        existed can still carry, and derive_focuses only folds what IT
        derives from the current question bank).
    (b) near-name pairs — one label's token set a proper subset of
        another's (the "Betty Jo" / "Betty Jo Taylor" shape), across both
        existing focuses and pending recommendation ideas — flagged for
        judgment, never auto-merged deterministically. Exact
        normalized_focus_key collisions are excluded here (they're
        "certain", reported in (a)/(c), not "near").
    (c) pending recommendation ideas whose normalized_focus_key collides
        with an existing focus (redundant — already has a home) or with
        another pending idea (a duplicate the next recommend() run's roster
        fold, contract Scope 2, would need a settled roster alias to
        actually collapse).

Zero writes, zero AI, deterministic — this is the detection half F4
(focus-merge) and the owner's own cleanup consume; merging EXISTING
duplicates is explicitly out of this module's scope (contract:
focus-duplicate-curation, "Out").

Usage:
    python3 system/focus_dupes.py --report
    python3 system/focus_dupes.py --json
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

SYSTEM_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SYSTEM_DIR))

from lifehug_core import normalized_focus_key  # noqa: E402
from recommend_focuses import load_recommendation_state  # noqa: E402
from roadmap import load_roadmap  # noqa: E402

_TOKEN_RE = re.compile(r"[^a-z0-9]+")


def _tokens(label: str) -> set[str]:
    """Lowercase alphanumeric word tokens for the token-subset check."""
    return {t for t in _TOKEN_RE.split(str(label or "").lower()) if t}


def _token_subset_pairs(items: list[tuple[str, str]]) -> list[dict]:
    """items: [(id, label), ...]. Near-name pairs where one item's token set
    is a PROPER subset of another's (the "Betty Jo" shape). Pairs whose
    normalized_focus_key already matches exactly are excluded — those are
    certain duplicates, reported elsewhere, not merely "near"."""
    pairs: list[dict] = []
    for i, (id_a, label_a) in enumerate(items):
        tokens_a = _tokens(label_a)
        if not tokens_a:
            continue
        for id_b, label_b in items[i + 1:]:
            tokens_b = _tokens(label_b)
            if not tokens_b or tokens_a == tokens_b:
                continue
            if normalized_focus_key(label_a) == normalized_focus_key(label_b):
                continue  # exact collision — reported in (a)/(c), not "near"
            if tokens_a < tokens_b:
                shorter, longer = (id_a, label_a), (id_b, label_b)
            elif tokens_b < tokens_a:
                shorter, longer = (id_b, label_b), (id_a, label_a)
            else:
                continue
            pairs.append({
                "shorter_id": shorter[0], "shorter_label": shorter[1],
                "longer_id": longer[0], "longer_label": longer[1],
            })
    return pairs


def _non_primary_focuses(roadmap: dict) -> list[dict]:
    return [f for f in roadmap.get("focuses", []) if f.get("id") and not f.get("primary")]


def suggested_merge(group: list[dict]) -> dict:
    """The survivor/loser split this report SUGGESTS for one certain-duplicate
    group, and the exact `focus-merge` command that heals it (contract
    focus-merge, Scope 2 — the hint line).

    Deterministic and conservative: the entry carrying the most question-bank
    categories survives (it is the one the bank has grown around), ties broken
    by id so the same vault always yields the same hint. It is a SUGGESTION —
    the owner picks the survivor, and merging is never automatic.
    """
    ordered = sorted(group, key=lambda f: (-len(f.get("categories") or []), str(f.get("id"))))
    survivor, *losers = [str(f.get("id")) for f in ordered]
    return {
        "survivor": survivor,
        "losers": losers,
        "commands": [f"lifehug focus-merge {survivor} {loser}" for loser in losers],
    }


def certain_focus_duplicates(roadmap: dict) -> list[dict]:
    """(a) roadmap focuses whose normalized_focus_key collide."""
    by_key: dict[str, list[dict]] = {}
    for focus in _non_primary_focuses(roadmap):
        key = normalized_focus_key(focus.get("label") or focus.get("id") or "")
        by_key.setdefault(key, []).append(focus)
    return [
        {
            "key": key,
            "focuses": [{"id": f.get("id"), "label": f.get("label")} for f in group],
            "suggested_merge": suggested_merge(group),
        }
        for key, group in by_key.items() if len(group) > 1
    ]


def near_name_pairs(roadmap: dict, pending: list[dict]) -> list[dict]:
    """(b) token-subset near-name pairs across both existing focuses and
    pending recommendation ideas."""
    items: list[tuple[str, str]] = []
    for focus in _non_primary_focuses(roadmap):
        items.append((f"focus:{focus['id']}", focus.get("label") or focus["id"]))
    for rec in pending:
        items.append((f"idea:{rec.get('id')}", rec.get("entity", "")))
    return _token_subset_pairs(items)


def pending_idea_duplicates(roadmap: dict, pending: list[dict]) -> list[dict]:
    """(c) pending ideas that fold into an existing focus (a redundant
    recommendation) or into each other (a certain duplicate pair the roster
    fold has no settled alias for yet)."""
    focus_keys = {
        normalized_focus_key(f.get("label") or f.get("id") or ""): f.get("id")
        for f in _non_primary_focuses(roadmap)
    }
    out: list[dict] = []
    by_key: dict[str, list[dict]] = {}
    for rec in pending:
        key = normalized_focus_key(rec.get("entity", ""))
        by_key.setdefault(key, []).append(rec)
        if key in focus_keys:
            out.append({
                "kind": "folds_into_existing_focus",
                "idea_id": rec.get("id"), "idea": rec.get("entity"),
                "focus_id": focus_keys[key],
            })
    for group in by_key.values():
        if len(group) > 1:
            out.append({
                "kind": "folds_into_each_other",
                "ideas": [{"id": r.get("id"), "entity": r.get("entity")} for r in group],
            })
    return out


def report() -> dict:
    """The full damage list: deterministic, zero AI, zero writes."""
    roadmap = load_roadmap()
    pending = load_recommendation_state().get("recommendations", [])
    return {
        "certain_focus_duplicates": certain_focus_duplicates(roadmap),
        "near_name_pairs": near_name_pairs(roadmap, pending),
        "pending_idea_duplicates": pending_idea_duplicates(roadmap, pending),
    }


def _print_report(data: dict) -> None:
    print("Focus duplicate report (deterministic, zero AI, zero writes)")
    print()

    print("(a) Certain focus duplicates (normalized keys collide):")
    if not data["certain_focus_duplicates"]:
        print("  none")
    for dup in data["certain_focus_duplicates"]:
        labels = ", ".join(f"{f['label']} ({f['id']})" for f in dup["focuses"])
        print(f"  key={dup['key']}: {labels}")
        # The healing hint (contract focus-merge, Scope 2). Detection stays
        # zero-write: this prints the command, it never runs it.
        for command in dup["suggested_merge"]["commands"]:
            print(f"      heal: {command}   (add --dry-run to see the full plan first)")
    print()

    print("(b) Near-name pairs (token-subset — flagged for judgment):")
    if not data["near_name_pairs"]:
        print("  none")
    for pair in data["near_name_pairs"]:
        print(f"  '{pair['shorter_label']}' ({pair['shorter_id']}) is a subset of "
              f"'{pair['longer_label']}' ({pair['longer_id']})")
    print()

    print("(c) Pending ideas that fold into existing focuses or each other:")
    if not data["pending_idea_duplicates"]:
        print("  none")
    for item in data["pending_idea_duplicates"]:
        if item["kind"] == "folds_into_existing_focus":
            print(f"  '{item['idea']}' ({item['idea_id']}) -> existing focus {item['focus_id']}")
        else:
            names = ", ".join(f"{i['entity']} ({i['id']})" for i in item["ideas"])
            print(f"  fold into each other: {names}")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Report Focus/idea duplicates — read-only, zero AI, zero writes.",
    )
    parser.add_argument("--report", action="store_true", help="Print the damage list")
    parser.add_argument("--json", action="store_true", help="Print the damage list as JSON")
    args = parser.parse_args()

    if not (args.report or args.json):
        parser.print_help()
        return 0

    data = report()
    if args.json:
        print(json.dumps(data, indent=2, ensure_ascii=False))
    else:
        _print_report(data)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
