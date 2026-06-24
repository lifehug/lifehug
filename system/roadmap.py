#!/usr/bin/env python3
"""Lifehug Focus / roadmap layer.

A **Focus** is the unit of intent — anything the author is building toward (a
person, a book, a blog, a theme, a life's work). It unifies the older
"spotlight" and "project" split into one primitive with an *objective* and a
*tier* (which sets default depth/scale).

The roadmap is the durable plan: a list of Focuses with targets, caps, and
phases. It is a **metadata layer over the existing question-bank category
letters** — it never renumbers questions or moves answers. `fill` is derived
live from answers, not stored, so the roadmap file stays a pure config object.

This module is the single source of truth for deriving the roadmap, used by both
the v15 migration (backfill) and `lifehug roadmap-rebuild`.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

_SYSTEM_DIR = Path(__file__).resolve().parent
if str(_SYSTEM_DIR) not in sys.path:
    sys.path.insert(0, str(_SYSTEM_DIR))

from lifehug_core import (  # noqa: E402
    QUESTIONS_FILE,
    STATE_DIR,
    WIKI_DIR,
    now_utc,
    parse_categories,
    parse_questions,
    read_json,
    slugify,
    write_json,
)

ROADMAP_FILE = STATE_DIR / "roadmap.json"

# Tier → default target depth (number of answers that count as "well-known").
TIER_TARGETS = {"basic": 8, "standard": 20, "extreme": 50}
TIER_ORDER = ("basic", "standard", "extreme")

DEFAULT_CAP = 0.30        # max share of a week's questions one Focus may take
FINISHING_CAP = 0.50      # raised cap while a Focus is being pushed to done
MAINTENANCE_FACTOR = 0.1  # weight multiplier once a Focus is saturated

# Map a Focus type to its wiki directory (for the Focus ↔ wiki node link).
TYPE_TO_WIKI_DIR = {
    "person": "people",
    "place": "places",
    "period": "periods",
    "project": "projects",
    "theme": "themes",
    "event": "events",
    "lifes_work": "lifes_work",
}


def tier_for_size(num_questions: int) -> str:
    """Heuristic tier from how many questions a category already carries."""
    if num_questions >= 30:
        return "extreme"
    if num_questions >= 15:
        return "standard"
    return "basic"


def _wiki_node_for(focus_type: str, label: str) -> str | None:
    subdir = TYPE_TO_WIKI_DIR.get(focus_type)
    if not subdir:
        return None
    return f"wiki/{subdir}/{slugify(label)}.md"


_HEADER_RE = re.compile(r"^## ([A-Z]): (.+?)(?:\s*\((.*)\))?\s*$", re.MULTILINE)


def _clean_label(name: str) -> str:
    """Strip 'Spotlight'/leading-dash decoration from a category name.

    e.g. 'Spotlight — Mom' -> 'Mom', 'Spotlight on Dad' -> 'Dad'.
    """
    name = name.strip()
    for prefix in ("Spotlight on ", "Spotlight: ", "Spotlight —", "Spotlight -", "Spotlight "):
        if name.startswith(prefix):
            name = name[len(prefix):]
            break
    return name.strip().lstrip("—-").strip() or "untitled"


def _project_group_tag(paren: str | None) -> str | None:
    """The parenthetical tag projects share to mark one deliverable.

    '(Etherfuse Story)' -> 'Etherfuse'. Returns None when there's no tag.
    """
    if not paren:
        return None
    tag = paren.strip()
    for suffix in (" Story", " Project", " Book"):
        if tag.endswith(suffix):
            tag = tag[: -len(suffix)]
    return tag.strip() or None


def _header_parens(md_text: str) -> dict[str, str | None]:
    """Map category letter -> raw parenthetical content (or None)."""
    out: dict[str, str | None] = {}
    for cat_id, _name, paren in _HEADER_RE.findall(md_text):
        out[cat_id] = paren.strip() if paren else None
    return out


def derive_focuses(md_text: str) -> list[dict]:
    """Derive Focuses from the question bank. Pure: reads only the bank text."""
    categories = parse_categories(md_text)
    questions = parse_questions(md_text)

    counts: dict[str, int] = {}
    for q in questions:
        counts[str(q["category"])] = counts.get(str(q["category"]), 0) + 1

    focuses: list[dict] = []

    # Life-story baseline: A–E collapse into one always-present Focus.
    main_cats = sorted(c for c, m in categories.items() if m["group"] == "main")
    if main_cats:
        total_main = sum(counts.get(c, 0) for c in main_cats)
        focuses.append({
            "id": "my-life",
            "label": "My Life",
            "type": "life_story",
            "tier": "standard",
            "objective": "a faithful record of my life story",
            "deliverable": "memoir",
            "categories": main_cats,
            "target_depth": max(total_main, TIER_TARGETS["standard"]),
            "cap": DEFAULT_CAP,
            "phase": "active",
            "wiki_node": None,
            "neighborhoods": [],
        })

    parens = _header_parens(md_text)

    # Project categories (F–J) sharing a parenthetical tag — e.g. all the
    # "(Etherfuse Story)" categories — collapse into ONE Focus (the book), with
    # those categories as its sub-arcs. Untagged projects stand alone.
    project_groups: dict[str, list[str]] = {}
    for cat_id, meta in sorted(categories.items()):
        if meta["group"] != "project":
            continue
        tag = _project_group_tag(parens.get(cat_id)) or f"__solo__{cat_id}"
        project_groups.setdefault(tag, []).append(cat_id)

    for tag, cats in project_groups.items():
        n = sum(counts.get(c, 0) for c in cats)
        tier = tier_for_size(n)
        if tag.startswith("__solo__"):
            label = _clean_label(categories[cats[0]]["name"])
        else:
            label = tag
        focuses.append({
            "id": slugify(label),
            "label": label,
            "type": "project",
            "tier": tier,
            "objective": f"build toward the {label} story",
            "deliverable": "book" if tier == "extreme" else "chapter",
            "categories": sorted(cats),
            "target_depth": max(TIER_TARGETS[tier], n),
            "cap": DEFAULT_CAP,
            "phase": "active",
            "wiki_node": _wiki_node_for("project", label),
            "neighborhoods": [],
        })

    # Spotlights (K+) — each its own person Focus.
    for cat_id, meta in sorted(categories.items()):
        if meta["group"] != "spotlight":
            continue
        n = counts.get(cat_id, 0)
        tier = tier_for_size(n)
        label = _clean_label(meta["name"])
        focuses.append({
            "id": slugify(label),
            "label": label,
            "type": "person",
            "tier": tier,
            "objective": f"tell the story of {label}",
            "deliverable": "letter",
            "categories": [cat_id],
            "target_depth": max(TIER_TARGETS[tier], n),
            "cap": DEFAULT_CAP,
            "phase": "active",
            "wiki_node": _wiki_node_for("person", label),
            "neighborhoods": [],
        })

    return focuses


# Fields a user can override; preserved across re-derivation.
_USER_FIELDS = ("label", "tier", "objective", "deliverable", "target_depth",
                "cap", "phase", "type", "wiki_node", "neighborhoods")


def derive_roadmap(md_text: str, existing: dict | None = None) -> dict:
    """Derive the roadmap, preserving any user overrides from `existing`.

    Idempotent: re-running refreshes the derived `categories` of each Focus and
    adds Focuses for new categories, but never clobbers user-set fields or drops
    a Focus the user created.
    """
    derived = derive_focuses(md_text)
    prior = {f["id"]: f for f in (existing or {}).get("focuses", [])}

    merged: list[dict] = []
    seen: set[str] = set()
    for focus in derived:
        fid = focus["id"]
        seen.add(fid)
        if fid in prior:
            old = prior[fid]
            focus["categories"] = sorted(set(focus["categories"]) | set(old.get("categories", [])))
            for field in _USER_FIELDS:
                if field in old:
                    focus[field] = old[field]
        merged.append(focus)

    # Keep user-created Focuses that don't map to a derived category.
    for fid, old in prior.items():
        if fid not in seen:
            merged.append(old)

    return {"version": 1, "generated_at": now_utc(), "focuses": merged}


def load_roadmap() -> dict:
    return read_json(ROADMAP_FILE, default={"version": 1, "focuses": []}) or {"version": 1, "focuses": []}


def focus_fill(focus: dict, questions: list[dict]) -> dict:
    """Compute live fill for a Focus: answered / total in its categories, and
    the saturation ratio against target_depth."""
    cats = set(focus.get("categories", []))
    cat_qs = [q for q in questions if str(q["category"]) in cats]
    total = len(cat_qs)
    answered = sum(1 for q in cat_qs if q["answered"])
    pending = total - answered
    target = focus.get("target_depth") or TIER_TARGETS.get(focus.get("tier", "standard"), 20)
    saturation = answered / target if target else 0.0
    return {
        "answered": answered,
        "total": total,
        "pending": pending,
        "target": target,
        "saturation": round(saturation, 3),
        "saturated": saturation >= 1.0,
        "room": pending > 0,
    }


def rebuild_roadmap(write: bool = True) -> dict:
    """Derive (or refresh) the roadmap from the current question bank."""
    md_text = QUESTIONS_FILE.read_text()
    roadmap = derive_roadmap(md_text, existing=load_roadmap())
    if write:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        write_json(ROADMAP_FILE, roadmap)
    return roadmap


def _print_roadmap(roadmap: dict) -> None:
    qs = parse_questions(QUESTIONS_FILE.read_text())
    print(f"Roadmap: {len(roadmap['focuses'])} focuses")
    for f in roadmap["focuses"]:
        fill = focus_fill(f, qs)
        phase = f.get("phase", "active")
        phase_tag = f" «{phase}»" if phase != "active" else ""
        bar = "█" * int(fill["saturation"] * 10) + "·" * (10 - int(min(fill["saturation"], 1) * 10))
        print(f"  [{f['tier']:8}] {f['label']:24}{phase_tag:12} {f['type']:11} "
              f"{bar} {fill['answered']:3}/{fill['target']:<3} (sat {fill['saturation']:.0%})"
              f"{'  SATURATED' if fill['saturated'] else ''}")
        cats = ",".join(f.get("categories", []))
        print(f"            objective: {f.get('objective','-')}  →  {f.get('deliverable','-')}  [{cats}]")


def find_focus(roadmap: dict, focus_id: str) -> dict | None:
    fid = slugify(focus_id)
    return next((f for f in roadmap["focuses"] if f["id"] == fid or f["id"] == focus_id), None)


def cli(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Lifehug roadmap / Focus management")
    sub = parser.add_subparsers(dest="cmd")

    sub.add_parser("show", help="Show the roadmap with live fill")
    sub.add_parser("rebuild", help="Derive/refresh the roadmap from the question bank")

    p = sub.add_parser("add", help="Add a Focus")
    p.add_argument("label")
    p.add_argument("--type", default="project",
                   choices=["person", "place", "period", "project", "theme", "event", "lifes_work", "self", "life_story"])
    p.add_argument("--tier", default="standard", choices=list(TIER_ORDER))
    p.add_argument("--objective", default="")
    p.add_argument("--deliverable", default="chapter")
    p.add_argument("--category", action="append", default=[], help="Question-bank category letter (repeatable)")
    p.add_argument("--target", type=int, default=None)

    p = sub.add_parser("set", help="Update a Focus")
    p.add_argument("focus_id")
    p.add_argument("--tier", choices=list(TIER_ORDER))
    p.add_argument("--target", type=int)
    p.add_argument("--cap", type=float)
    p.add_argument("--phase", choices=["active", "finishing", "maintenance"])
    p.add_argument("--objective")
    p.add_argument("--deliverable")
    p.add_argument("--category", action="append", default=[], help="Replace categories (repeatable)")

    p = sub.add_parser("finish", help="Flag a Focus as finishing (lifts its variety cap)")
    p.add_argument("focus_id")

    args = parser.parse_args(argv)

    if args.cmd in (None, "show"):
        _print_roadmap(load_roadmap() or rebuild_roadmap())
        return 0

    if args.cmd == "rebuild":
        _print_roadmap(rebuild_roadmap(write=True))
        return 0

    if args.cmd == "add":
        roadmap = load_roadmap()
        if not roadmap.get("focuses"):
            roadmap = rebuild_roadmap()
        fid = slugify(args.label)
        if find_focus(roadmap, fid):
            print(f"✗ Focus already exists: {fid}")
            return 1
        roadmap["focuses"].append({
            "id": fid, "label": args.label, "type": args.type, "tier": args.tier,
            "objective": args.objective or f"build toward {args.label}",
            "deliverable": args.deliverable,
            "categories": [c.upper() for c in args.category],
            "target_depth": args.target or TIER_TARGETS[args.tier],
            "cap": DEFAULT_CAP, "phase": "active",
            "wiki_node": _wiki_node_for(args.type, args.label), "neighborhoods": [],
        })
        roadmap["generated_at"] = now_utc()
        write_json(ROADMAP_FILE, roadmap)
        print(f"✓ Added focus: {args.label} ({args.tier} {args.type})")
        return 0

    if args.cmd in ("set", "finish"):
        roadmap = load_roadmap()
        focus = find_focus(roadmap, args.focus_id)
        if not focus:
            print(f"✗ No such focus: {args.focus_id}")
            return 1
        if args.cmd == "finish":
            focus["phase"] = "finishing"
        else:
            if args.tier:
                focus["tier"] = args.tier
            if args.target is not None:
                focus["target_depth"] = args.target
            if args.cap is not None:
                focus["cap"] = args.cap
            if args.phase:
                focus["phase"] = args.phase
            if args.objective is not None:
                focus["objective"] = args.objective
            if args.deliverable is not None:
                focus["deliverable"] = args.deliverable
            if args.category:
                focus["categories"] = [c.upper() for c in args.category]
        roadmap["generated_at"] = now_utc()
        write_json(ROADMAP_FILE, roadmap)
        print(f"✓ Updated focus: {focus['label']} (phase={focus.get('phase')}, "
              f"tier={focus.get('tier')}, target={focus.get('target_depth')})")
        return 0

    return 0


if __name__ == "__main__":
    raise SystemExit(cli())
