#!/usr/bin/env python3
"""Lifehug Focus / roadmap layer.

A **Focus** is the unit of intent — anything the author is building toward (a
person, a book, a blog, a theme, a life's work). It unifies the older
separate category types into one primitive with an *objective* and a
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
    REPO_DIR,
    ROADMAP_FILE,
    STATE_DIR,
    load_config,
    normalized_focus_key,
    now_utc,
    parse_categories,
    parse_questions,
    read_json,
    rebuild_coverage,
    slugify,
    write_json,
    write_text,
)

# Tier → default target depth (number of answers that count as "well-known").
TIER_TARGETS = {"basic": 8, "standard": 20, "extreme": 50}
TIER_ORDER = ("basic", "standard", "extreme")

DEFAULT_CAP = 0.30        # max share of a week's questions one Focus may take
PRIMARY_CAP = 0.40        # the author's own life story (primary focus) may take a larger share
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
    "self": "self",
}

OLD_FOCUS_TERM = "Spot" "light"


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
    """Strip leading Focus decoration from a category name.

    e.g. 'Focus — Mom' -> 'Mom', 'Focus on Dad' -> 'Dad'.
    """
    name = name.strip()
    for prefix in (
        "Focus on ", "Focus: ", "Focus —", "Focus -", "Focus ",
        f"{OLD_FOCUS_TERM} on ", f"{OLD_FOCUS_TERM}: ", f"{OLD_FOCUS_TERM} —",
        f"{OLD_FOCUS_TERM} -", f"{OLD_FOCUS_TERM} ",
    ):
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


class FocusKeyCollisionError(ValueError):
    """Raised by a Focus-creation door (focus_new, the `roadmap add` CLI)
    when the requested label's normalized_focus_key collides with an
    EXISTING focus — the exact-name-modulo-case / "the "-prefix duplicate
    class (contract: focus-duplicate-curation, Scope 1). Carries the
    colliding focus so the caller can point at it instead of materializing
    a twin, per the door-guard doctrine: refuse and name the existing
    Focus rather than silently creating a duplicate."""

    def __init__(self, label: str, existing: dict):
        self.label = label
        self.existing = existing
        existing_label = existing.get("label") or existing.get("id") or "?"
        super().__init__(
            f"Focus '{label}' collides with existing focus '{existing_label}' "
            f"(id={existing.get('id')}) — attach the new category to it instead "
            "of creating a duplicate."
        )


def find_focus_by_key(roadmap: dict, label: str) -> dict | None:
    """The existing focus (if any) whose normalized_focus_key matches
    `label`'s — the collision check every creation door runs before
    scaffolding. Compares against both the candidate focus's `label` and
    its `id` (ids are slugified labels, but can drift from a user-edited
    label via _USER_FIELDS overrides)."""
    key = normalized_focus_key(label)
    for focus in roadmap.get("focuses", []):
        if normalized_focus_key(focus.get("label") or "") == key:
            return focus
        if normalized_focus_key(focus.get("id") or "") == key:
            return focus
    return None


def _fold_focus_collisions(focuses: list[dict]) -> list[dict]:
    """Auto-derived focuses whose normalized_focus_key collides (the
    case / "the "-prefix duplicate class — separately-scaffolded question-
    bank categories that normalize to the same Focus, e.g. a "K: Focus —
    Fear" and an "L: Focus — fear") fold into ONE focus entry: the later
    category(ies) attach to the first-seen entry instead of materializing a
    twin (contract Scope 1, the `derive_focuses` door). The primary
    life-story focus and any focus with no id are never folded."""
    folded_by_key: dict[str, dict] = {}
    out: list[dict] = []
    for focus in focuses:
        if focus.get("primary") or not focus.get("id"):
            out.append(focus)
            continue
        key = normalized_focus_key(focus.get("label") or focus.get("id") or "")
        target = folded_by_key.get(key)
        if target is None:
            folded_by_key[key] = focus
            out.append(focus)
            continue
        target["categories"] = sorted(set(target.get("categories", [])) | set(focus.get("categories", [])))
        target["target_depth"] = max(int(target.get("target_depth") or 0), int(focus.get("target_depth") or 0))
    return out


def derive_focuses(md_text: str) -> list[dict]:
    """Derive Focuses from the question bank. Pure: reads only the bank text."""
    categories = parse_categories(md_text)
    questions = parse_questions(md_text)

    counts: dict[str, int] = {}
    for q in questions:
        counts[str(q["category"])] = counts.get(str(q["category"]), 0) + 1

    focuses: list[dict] = []

    # Life-story baseline: A–E collapse into one always-present Focus — and it's
    # the PRIMARY focus (the author themselves). It carries both the outer
    # narrative and the inner story (self-knowledge), gets the largest share of
    # questions, and is the heart of the whole system.
    main_cats = sorted(c for c, m in categories.items() if m["group"] == "main")
    if main_cats:
        total_main = sum(counts.get(c, 0) for c in main_cats)
        full_name = load_config().get("full_name") or load_config().get("name") or "My Life"
        focuses.append({
            "id": "my-life",
            "label": full_name,
            "type": "life_story",
            "primary": True,
            "tier": "extreme",
            "objective": "a faithful record of my life story",
            "deliverable": "book",
            "categories": main_cats,
            "target_depth": max(total_main, TIER_TARGETS["extreme"]),
            "cap": PRIMARY_CAP,
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

    # Standalone Focus categories (K+) — each its own person/theme/place Focus.
    for cat_id, meta in sorted(categories.items()):
        if meta["group"] != "focus":
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

    return _fold_focus_collisions(focuses)


def _settled_key_owners(prior_focuses: list[dict]) -> dict[str, str]:
    """normalized_focus_key -> the EXISTING roadmap entry id that owns it.

    The roadmap is the record of settled Focus identity: once an entry
    exists under a key, that entry owns the key. First entry wins, and the
    primary life-story focus is excluded (its identity is system-owned and
    never a merge participant)."""
    owners: dict[str, str] = {}
    for focus in prior_focuses:
        fid = focus.get("id")
        if not fid or focus.get("primary"):
            continue
        for raw in (focus.get("label") or "", fid):
            key = normalized_focus_key(raw)
            if key:
                owners.setdefault(key, fid)
    return owners


def _settled_id_for(focus: dict, prior: dict[str, dict], settled_owner: dict[str, str]) -> str:
    """The id a freshly derived focus should claim.

    Normally its own. But when the derived id is NOT already in the roadmap
    and an EXISTING entry owns its normalized key under a different id, the
    derived focus attaches to that existing entry instead of materializing
    beside it.

    This is the `derive_roadmap` door of ADR 0010's guard doctrine, and it
    is what makes `focus-merge` (ADR 0012) survive a rebuild in BOTH
    orientations. `_fold_focus_collisions` only folds focuses derived
    within ONE pass, and derive_roadmap's "keep user-created focuses" tail
    re-appends any prior entry the pass didn't derive — so without this,
    merging "fear" INTO "the-fear" (i.e. the surviving id is not the one
    the bank happens to derive first) resurrected the absorbed focus on the
    very next `roadmap-rebuild`, silently re-splitting a healed vault.
    """
    fid = str(focus["id"])
    if fid in prior or focus.get("primary"):
        return fid
    owner = settled_owner.get(normalized_focus_key(focus.get("label") or fid))
    return owner if owner and owner != fid else fid


# Fields a user can override; preserved across re-derivation.
_USER_FIELDS = ("label", "tier", "objective", "deliverable", "target_depth",
                "cap", "phase", "type", "wiki_node", "neighborhoods",
                # living: false on a person Focus = deceased; second-voice
                # offers skip them (you can't ask). relationship: which
                # interview bank fits (parent/spouse/child/...), overriding
                # the label heuristic.
                "living", "relationship")


def derive_roadmap(md_text: str, existing: dict | None = None) -> dict:
    """Derive the roadmap, preserving any user overrides from `existing`.

    Idempotent: re-running refreshes the derived `categories` of each Focus and
    adds Focuses for new categories, but never clobbers user-set fields or drops
    a Focus the user created.
    """
    derived = derive_focuses(md_text)
    prior_focuses = (existing or {}).get("focuses", [])
    prior = {f["id"]: f for f in prior_focuses}
    settled_owner = _settled_key_owners(prior_focuses)

    merged: list[dict] = []
    seen: set[str] = set()
    for focus in derived:
        fid = _settled_id_for(focus, prior, settled_owner)
        focus["id"] = fid
        seen.add(fid)
        if fid in prior:
            old = prior[fid]
            focus["categories"] = sorted(set(focus["categories"]) | set(old.get("categories", [])))
            # The primary life-story focus's identity is system-owned (label tracks
            # full_name; tier/cap/deliverable are policy) — always refresh those so
            # an upgrade actually promotes the author to the primary, biggest focus.
            system_owned = {"label", "tier", "cap", "deliverable"} if focus.get("primary") else set()
            for field in _USER_FIELDS:
                if field in old and field not in system_owned:
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


# --- Category scaffolding + one-shot focus creation -------------------------

# Focus type → which question-bank section a new category lands in.
def _section_header_for(focus_type: str) -> str:
    return "## Project Categories" if focus_type in ("project", "lifes_work") else "## Focuses"


# Focus type → research_expand --type and --output.
RESEARCH_TYPE = {
    "person": "person", "project": "project", "theme": "theme", "place": "place",
    "period": "time_period", "event": "event", "self": "self",
    "relationship": "relationship", "lifes_work": "project", "life_story": "theme",
}
RESEARCH_OUTPUT = {
    "book": "chapter", "memoir": "chapter", "chapter": "chapter",
    "letter": "letter", "essay": "essay", "post": "post", "profile": "profile",
}


def next_free_letter(md_text: str) -> str:
    used = set(parse_categories(md_text).keys())
    for code in range(ord("A"), ord("Z") + 1):
        if chr(code) not in used:
            return chr(code)
    raise ValueError("no free category letter (A–Z all used)")


def scaffold_category(md_text: str, label: str, focus_type: str, tag: str | None = None) -> tuple[str, str]:
    """Insert a new `## <Letter>: <Label> (<tag>)` category under the right
    section, creating the section if absent. Returns (new_md, letter)."""
    letter = next_free_letter(md_text)
    cat_line = f"## {letter}: {label}" + (f" ({tag})" if tag else "")
    section = _section_header_for(focus_type)
    block = f"{cat_line}\n"

    if section in md_text:
        start = md_text.index(section) + len(section)
        # End of this section = the next top-level section header, or EOF.
        nexts = [
            p for p in (
                md_text.find("\n## Project Categories", start),
                md_text.find("\n## Focuses", start),
                md_text.find("\n## " + OLD_FOCUS_TERM + "s", start),
            ) if p != -1
        ]
        boundary = min(nexts) if nexts else len(md_text)
        new_md = md_text[:boundary].rstrip() + "\n\n" + block + md_text[boundary:]
    else:
        new_md = md_text.rstrip() + f"\n\n{section}\n\n{block}"
    return new_md, letter


def _generate_and_promote(label: str, focus_type: str, deliverable: str, category: str) -> tuple[bool, int]:
    """Generate starter questions via research_expand (needs API) and promote
    them into the new category. Returns (generation_ran, num_promoted)."""
    import subprocess

    rtype = RESEARCH_TYPE.get(focus_type, "theme")
    routput = RESEARCH_OUTPUT.get(deliverable, "chapter")
    proc = subprocess.run(
        [sys.executable, str(_SYSTEM_DIR / "research_expand.py"),
         "--topic", label, "--type", rtype, "--output", routput, "--force"],
        capture_output=True, text=True,
    )
    if proc.returncode != 0:
        return False, 0

    import candidate_promotion
    import question_candidates as qc
    data = qc.load_store()
    bank = QUESTIONS_FILE.read_text(encoding="utf-8")
    rows = [candidate for candidate in data.get("candidates", [])
            if candidate.get("neighborhood_id") == f"nbhd-{slugify(label)}"
            and candidate.get("status") in qc.PROMOTABLE_STATUSES]
    rows.sort(key=lambda candidate: (
        -float(candidate.get("priority", 0) or 0), candidate.get("created_at", "")))
    ids: list[str] = []
    for candidate in rows:
        request = candidate_promotion.build_candidate_promotion_request(
            candidate, bank, category)
        receipt = candidate_promotion.resolve_candidate_promotion(
            request, vault_root=REPO_DIR,
            promotion_mode="neighborhood", push=True)
        ids.append(receipt["question_id"])
        bank = QUESTIONS_FILE.read_text(encoding="utf-8")
    return True, len(ids)


def focus_new(label: str, focus_type: str, tier: str, objective: str = "",
              deliverable: str = "chapter", generate: bool = True) -> dict:
    """End-to-end: scaffold a category, register the Focus, and (optionally)
    generate + promote starter questions. Non-destructive to existing answers.

    Door guard (contract Scope 1): refuses when `label`'s normalized_focus_key
    collides with an EXISTING focus under a DIFFERENT id — e.g. creating
    "fear" when "Fear" already exists — raising FocusKeyCollisionError
    pointing at the existing focus instead of materializing a twin. A
    collision against the SAME id (the exact focus this label would derive)
    is the pre-existing "zombie focus" healing case, not a duplicate, and is
    left to the caller (see roadmap.py cli()'s `new` subcommand)."""
    roadmap = load_roadmap()
    if not roadmap.get("focuses"):
        try:
            roadmap = rebuild_roadmap(write=False)
        except OSError:
            roadmap = {"version": 1, "focuses": []}
    collision = find_focus_by_key(roadmap, label)
    if collision is not None and collision.get("id") != slugify(label):
        raise FocusKeyCollisionError(label, collision)

    md = QUESTIONS_FILE.read_text(encoding="utf-8")
    tag = label if focus_type in ("project", "lifes_work") else None
    new_md, letter = scaffold_category(md, label, focus_type, tag)
    write_text(QUESTIONS_FILE, new_md)

    # Derive the Focus from the new category, then apply chosen attributes.
    rebuild_roadmap(write=True)
    roadmap = load_roadmap()
    fid = slugify(label)
    focus = find_focus(roadmap, fid)
    if focus:
        focus["type"] = focus_type
        focus["tier"] = tier
        if objective:
            focus["objective"] = objective
        if deliverable:
            focus["deliverable"] = deliverable
        focus["target_depth"] = max(TIER_TARGETS.get(tier, 20), int(focus.get("target_depth", 0)))
        focus["wiki_node"] = _wiki_node_for(focus_type, label)
        roadmap["generated_at"] = now_utc()
        write_json(ROADMAP_FILE, roadmap)

    result = {"focus_id": fid, "category": letter, "type": focus_type,
              "tier": tier, "generated": 0, "generation_ran": False}
    if generate:
        ran, n = _generate_and_promote(label, focus_type, deliverable, letter)
        result["generation_ran"] = ran
        result["generated"] = n
        rebuild_roadmap(write=True)
    rebuild_coverage()
    return result


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

    p = sub.add_parser("new", help="Create a Focus end-to-end: scaffold category, register, seed questions")
    p.add_argument("label")
    p.add_argument("--type", default="theme",
                   choices=["person", "place", "period", "project", "theme", "event", "lifes_work", "self", "relationship"])
    p.add_argument("--tier", default="standard", choices=list(TIER_ORDER))
    p.add_argument("--objective", default="")
    p.add_argument("--deliverable", default="chapter")
    p.add_argument("--no-generate", action="store_true", help="Scaffold only; don't AI-generate starter questions")

    args = parser.parse_args(argv)

    if args.cmd in (None, "show"):
        _print_roadmap(load_roadmap() or rebuild_roadmap())
        return 0

    if args.cmd == "rebuild":
        _print_roadmap(rebuild_roadmap(write=True))
        return 0

    if args.cmd == "new":
        existing = find_focus(load_roadmap(), slugify(args.label))
        if existing and existing.get("categories"):
            print(f"✗ A focus '{slugify(args.label)}' already exists with categories "
                  f"{existing['categories']}. Use focus-set to change it.")
            return 1
        if existing:
            # Zombie focus (registered, but no question category — the planner
            # can never ask about it). focus-new is the healing path: scaffold
            # the category and attach it; the roadmap rebuild merges by id.
            print(f"↺ Focus '{slugify(args.label)}' exists with no question category — healing it.")
        try:
            res = focus_new(args.label, args.type, args.tier, args.objective,
                            args.deliverable, generate=not args.no_generate)
        except FocusKeyCollisionError as exc:
            print(f"✗ {exc}")
            return 1
        verb = "healed with" if existing else "added as"
        print(f"✓ Focus '{args.label}' ({res['tier']} {res['type']}) {verb} category {res['category']}.")
        if args.no_generate:
            print(f"  Scaffolded only. Seed questions later: "
                  f"python3 system/research_expand.py --topic \"{args.label}\" --type {RESEARCH_TYPE.get(args.type,'theme')}")
        elif res["generation_ran"]:
            print(f"  Generated and promoted {res['generated']} starter question(s) → category {res['category']}.")
        else:
            print(
                "  ⚠ Could not generate starter questions (selected AI provider "
                "is not ready — use ai-status or the keyless agent flow)."
            )
            print(
                "     With ai-status ready, run: python3 system/research_expand.py "
                f"--topic \"{args.label}\" --type {RESEARCH_TYPE.get(args.type, 'theme')}"
            )
            print(f"     then: python3 system/question_candidates.py promote-neighborhood --neighborhood nbhd-{slugify(args.label)} --category {res['category']}")
        print()
        _print_roadmap(load_roadmap())
        return 0

    if args.cmd == "add":
        roadmap = load_roadmap()
        if not roadmap.get("focuses"):
            roadmap = rebuild_roadmap()
        fid = slugify(args.label)
        if find_focus(roadmap, fid):
            print(f"✗ Focus already exists: {fid}")
            return 1
        collision = find_focus_by_key(roadmap, args.label)
        if collision is not None:
            existing_label = collision.get("label") or collision.get("id") or "?"
            print(f"✗ Focus '{args.label}' collides with existing focus "
                  f"'{existing_label}' (id={collision.get('id')}) — use "
                  "roadmap-set to attach a category to it instead of "
                  "creating a duplicate.")
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
