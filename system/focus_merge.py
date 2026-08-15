#!/usr/bin/env python3
"""Lifehug — `focus-merge`, the healing verb for duplicate Focuses (ADR 0012).

Duplicate curation (ADR 0010, v168) PREVENTS new duplicate focuses (door
guards) and DETECTS the ones a vault already carries
(`focus_dupes.report()`), but nothing could HEAL them. This module is the
one missing verb: a deliberate, owner-initiated, auditable multi-file
transaction that fuses two Focuses into one.

    focus_merge(survivor_id, loser_id, *, dry_run=False, adopt_target=False)

The transaction, in the order ADR 0012 fixes (each step fully RESOLVED in
the plan phase before the first byte is written, so an impossible merge
fails before it mutates anything):

    a. Validate  — both exist, distinct entries, neither is primary.
    b. Roadmap   — union the loser's categories/neighborhoods into the
                   survivor (order preserved), drop the loser's entry.
                   The survivor's user fields are UNCHANGED unless
                   `adopt_target` recomputes target_depth as max(both).
    c. Bank      — the loser's category headers ADOPT the survivor's own
                   header text verbatim and gain a provenance comment.
                   Question ids are NEVER renumbered (bank doctrine).
    d. Rosters   — every entry whose `maps_to_focus` is the loser
                   re-points to the survivor; the loser's name/slug join
                   the survivor's roster aliases (or the curation settled
                   ledger, when the survivor has no roster entry).
    e. Ledger    — the merge is recorded as a settled identity decision so
                   recommend()/curation can never re-propose the loser.
    f. Wiki      — the loser's `origin: focus` page file is removed (the
                   survivor's page absorbs at next compile) and logged.
                   A hand-authored / foreign-origin page is LEFT + warned.
    g. Audit     — an append-only record lands in `state/focus_merges.json`.
    h. Recompile — the existing `state/.compile-needed` sentinel is touched;
                   compiling inline is never this verb's job.

`--dry-run` prints the complete plan — every concrete edit of every step —
and writes nothing at all.

Detection is never re-derived here: `focus_dupes` owns "what is a
duplicate" and `lifehug_core.normalized_focus_key` owns "what counts as
the same Focus name". This module consumes both.

Usage:
    python3 system/focus_merge.py <survivor> <loser> [--dry-run] [--adopt-target]
    python3 system/focus_merge.py <survivor> <loser> --json
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

SYSTEM_DIR = Path(__file__).resolve().parent
if str(SYSTEM_DIR) not in sys.path:
    sys.path.insert(0, str(SYSTEM_DIR))

from lifehug_core import (  # noqa: E402
    CATEGORY_HEADER_RE,
    COMPILE_NEEDED_FILE,
    FOCUS_MERGES_FILE,
    QUESTIONS_FILE,
    REPO_DIR,
    ROADMAP_FILE,
    WIKI_DIR,
    now_utc,
    read_json,
    slugify,
    write_json,
    write_text,
)
from roadmap import load_roadmap  # noqa: E402

# The audit file's schema version (vault_contract.json: focus_merges).
MERGES_VERSION = 1


class FocusMergeError(ValueError):
    """A merge that must not proceed — an unknown focus, a self-merge, or a
    primary focus on either side. Raised during validation, ALWAYS before
    any write: a refused merge leaves the vault byte-for-byte unchanged."""


# ---------------------------------------------------------------------------
# Step a — validation
# ---------------------------------------------------------------------------

def _resolve(roadmap: dict, focus_id: str) -> dict:
    """The roadmap entry for `focus_id`, matched exactly or by slug (the
    same two-way match `roadmap.find_focus` uses). Raises rather than
    returning None — every caller here treats a miss as fatal."""
    wanted = str(focus_id or "").strip()
    if not wanted:
        raise FocusMergeError("a focus id is required")
    slug = slugify(wanted)
    for focus in roadmap.get("focuses", []):
        if focus.get("id") in (wanted, slug):
            return focus
    known = ", ".join(sorted(str(f.get("id")) for f in roadmap.get("focuses", []) if f.get("id")))
    raise FocusMergeError(f"no such focus: {wanted!r} (known: {known or 'none'})")


def validate(roadmap: dict, survivor_id: str, loser_id: str) -> tuple[dict, dict]:
    """Step (a). Both focuses exist, resolve to DISTINCT entries, and
    neither is the primary life-story focus.

    The primary refusal is two-sided and non-negotiable (ADR 0012): the
    primary can absorb nothing (its categories are the derived A–E main
    group, system-owned) and it never dies. The distinctness check is on
    the resolved ENTRY, not on the strings — "Fear" and "fear" slugify to
    the same id and so name the same entry, which is a self-merge.
    """
    survivor = _resolve(roadmap, survivor_id)
    loser = _resolve(roadmap, loser_id)

    if survivor is loser or survivor.get("id") == loser.get("id"):
        raise FocusMergeError(
            f"a focus cannot absorb itself: {survivor_id!r} and {loser_id!r} "
            f"both resolve to {survivor.get('id')!r}")

    for role, focus in (("survivor", survivor), ("loser", loser)):
        if focus.get("primary"):
            raise FocusMergeError(
                f"refusing: the primary life-story focus ({focus.get('id')}) cannot be "
                f"a merge {role} — it absorbs nothing and never dies")

    return survivor, loser


# ---------------------------------------------------------------------------
# Step b — roadmap
# ---------------------------------------------------------------------------

def _ordered_union(first: list, second: list) -> list:
    """Union preserving `first`'s order, then `second`'s new items — never
    a sort, so the survivor's own category order survives the merge."""
    out: list = []
    for item in [*(first or []), *(second or [])]:
        if item not in out:
            out.append(item)
    return out


# ---------------------------------------------------------------------------
# Step c — question bank
# ---------------------------------------------------------------------------

def _header_lines(md_text: str) -> dict[str, tuple[int, str, str, str]]:
    """category letter -> (line index, whole line, display name, qualifier).

    Parsed with lifehug_core.CATEGORY_HEADER_RE — the same regex
    `parse_categories` uses, never a second header grammar."""
    out: dict[str, tuple[int, str, str, str]] = {}
    for index, line in enumerate(md_text.splitlines()):
        match = CATEGORY_HEADER_RE.match(line)
        if match:
            out[match.group(1)] = (index, line, match.group(2).strip(), (match.group(3) or "").strip())
    return out


def _merge_comment(survivor_id: str, previous_name: str, when: str) -> str:
    """The provenance comment line a merged-away category carries forever.

    The contract's literal prefix — `<!-- merged into <id> by focus-merge
    YYYY-MM-DD` — is fixed; the trailing `(was "...")` clause records what
    the header said before, which is what makes the rename reversible."""
    return f'<!-- merged into {survivor_id} by focus-merge {when} (was "{previous_name}") -->'


def _bank_plan(md_text: str, survivor: dict, loser: dict, when: str) -> tuple[list[dict], list[str]]:
    """Step (c), resolved but not applied.

    Each of the LOSER's category headers adopts the SURVIVOR's own header
    text (display name + parenthetical) verbatim, and gains the provenance
    comment beneath it.

    Adopting the survivor's header text verbatim — rather than inventing an
    annotation — is what makes the merge survive `derive_roadmap`: a
    category whose header text is identical to the survivor's derives the
    survivor's identity, whichever section it sits in, so
    `_fold_focus_collisions` collapses the pair instead of re-materializing
    the loser. Question ids are untouched: only the `## X: ...` header LINE
    changes, never a `- [ ] X7:` line (bank doctrine — ids only ever grow,
    provenance comments elsewhere reference them by id).
    """
    warnings: list[str] = []
    headers = _header_lines(md_text)
    all_lines = md_text.splitlines()
    survivor_cats = [c for c in survivor.get("categories", []) if c in headers]
    survivor_id = str(survivor.get("id"))

    if survivor_cats:
        _, _, model_name, model_qualifier = headers[survivor_cats[0]]
    else:
        model_name, model_qualifier = f"Focus — {survivor.get('label') or survivor_id}", ""
        warnings.append(
            f"the survivor ({survivor_id}) has no question-bank category header; merged-away "
            f"headers will read {model_name!r} instead of adopting an existing one")

    edits: list[dict] = []
    for letter in loser.get("categories", []):
        entry = headers.get(letter)
        if entry is None:
            warnings.append(f"category {letter} has no header in the question bank — left untouched")
            continue
        index, line, name, _qualifier = entry
        new_line = f"## {letter}: {model_name}" + (f" ({model_qualifier})" if model_qualifier else "")
        # Never stack a second identical provenance comment on a re-run.
        following = all_lines[index + 1] if index + 1 < len(all_lines) else ""
        already = following.strip().startswith(f"<!-- merged into {survivor_id} by focus-merge")
        comment = "" if already else _merge_comment(survivor_id, name, when)
        if new_line == line and already:
            continue  # this header is already fully merged — nothing to do
        edits.append({"category": letter, "line_index": index, "line_before": line,
                      "line_after": new_line, "comment": comment, "renamed": new_line != line})
    return edits, warnings


def _apply_bank(md_text: str, edits: list[dict]) -> str:
    """Replace each planned header line in place, inserting its provenance
    comment beneath it. Applied bottom-up so earlier line indexes stay
    valid as lines are inserted."""
    lines = md_text.splitlines(keepends=True)
    for edit in sorted(edits, key=lambda e: e["line_index"], reverse=True):
        index = edit["line_index"]
        replacement = edit["line_after"] + "\n"
        if edit["comment"]:
            replacement += edit["comment"] + "\n"
        lines[index] = replacement
    return "".join(lines)


# ---------------------------------------------------------------------------
# Step d — rosters
# ---------------------------------------------------------------------------

def _roster_types() -> tuple[str, ...]:
    from entity_roster import ENTITY_TYPES  # noqa: PLC0415
    return tuple(ENTITY_TYPES)


def _roster_payload(entity_type: str) -> tuple[Path, dict | None]:
    """The raw roster payload for a type, read through entity_roster's own
    path authority. Raw (not `load_roster`'s normalized default) so a
    repoint rewrites the file without dropping its other keys
    (`resolved_at`, `source`, `sampled_answer_ids`, ...)."""
    from entity_roster import roster_file  # noqa: PLC0415
    path = roster_file(entity_type)
    data = read_json(path, default=None)
    if not isinstance(data, dict) or not isinstance(data.get("entities"), list):
        return path, None
    return path, data


def _entity_matches_focus(entity: dict, focus: dict) -> bool:
    """Whether a roster entity IS this focus — either an explicit
    `maps_to_focus` tie or a name/alias/slug key match. The key match
    delegates to entity_roster._entity_keys, which itself delegates to
    lifehug_core.normalized_focus_key: one definition of "same name",
    never a second copy here (recurring-defect doctrine)."""
    from entity_roster import _entity_keys  # noqa: PLC0415
    from lifehug_core import normalized_focus_key  # noqa: PLC0415

    focus_id = str(focus.get("id") or "")
    if entity.get("maps_to_focus") == focus_id:
        return True
    keys = _entity_keys(entity)
    return bool({normalized_focus_key(focus.get("label") or ""), normalized_focus_key(focus_id)} & keys)


def _roster_plan(survivor: dict, loser: dict) -> tuple[list[dict], list[dict], list[str]]:
    """Step (d), resolved but not applied: (repoints, alias_additions, aliases_needing_the_ledger)."""
    from lifehug_core import normalized_focus_key  # noqa: PLC0415

    survivor_id, loser_id = str(survivor.get("id")), str(loser.get("id"))
    loser_label = str(loser.get("label") or loser_id)
    repoints: list[dict] = []
    alias_additions: list[dict] = []

    for entity_type in _roster_types():
        _path, data = _roster_payload(entity_type)
        if data is None:
            continue
        for position, entity in enumerate(data["entities"]):
            if entity.get("maps_to_focus") == loser_id:
                repoints.append({"type": entity_type, "index": position,
                                 "entity": entity.get("name"), "from": loser_id, "to": survivor_id})
        for position, entity in enumerate(data["entities"]):
            if not _entity_matches_focus(entity, survivor):
                continue
            existing = {normalized_focus_key(a) for a in entity.get("aliases", [])}
            existing.add(normalized_focus_key(entity.get("name") or ""))
            adding = [a for a in (loser_label, loser_id)
                      if a and normalized_focus_key(a) not in existing]
            # Dedupe within the pair itself ("Fear"/"fear" -> one alias).
            deduped: list[str] = []
            for alias in adding:
                if normalized_focus_key(alias) not in {normalized_focus_key(d) for d in deduped}:
                    deduped.append(alias)
            if deduped:
                alias_additions.append({"type": entity_type, "index": position,
                                        "entity": entity.get("name"), "aliases_added": deduped})
            break  # one survivor entry per roster is enough

    ledger_aliases: list[str] = []
    if not alias_additions:
        # No roster entry owns the survivor — record the alias pair in the
        # curation settled ledger instead, so the next roster resolve folds
        # it (contract Scope 1d's fallback path).
        ledger_aliases = [loser_label] if normalized_focus_key(loser_label) == normalized_focus_key(loser_id) \
            else [loser_label, loser_id]
    return repoints, alias_additions, ledger_aliases


# ---------------------------------------------------------------------------
# Step f — wiki
# ---------------------------------------------------------------------------

def _wiki_plan(loser: dict) -> tuple[dict, list[str]]:
    """Step (f), resolved but not applied. Only a page whose frontmatter
    says `origin: focus` is removable: a hand-authored page (no frontmatter
    origin, or a foreign one) is structurally untouchable and is LEFT with
    a warning, exactly as `wiki_compile.cleanup_orphan_entity_pages` treats
    non-`mention` pages."""
    from wiki_compile import frontmatter_value  # noqa: PLC0415

    node = loser.get("wiki_node")
    if not node:
        return {"page": None, "action": "absent", "origin": None}, []
    path = REPO_DIR / str(node)
    if not path.exists():
        return {"page": str(node), "action": "absent", "origin": None}, []
    origin = frontmatter_value(path.read_text(encoding="utf-8", errors="replace"), "origin")
    if origin != "focus":
        return ({"page": str(node), "action": "keep", "origin": origin or None},
                [f"{node} is not focus-origin (origin: {origin or 'missing'}) — left in place, "
                 "hand-authored pages are never removed by a merge"])
    return {"page": str(node), "action": "delete", "origin": origin}, []


def _log_wiki(message: str) -> None:
    """Append one line to wiki/log.md — the same ledger
    `wiki_compile.cleanup_orphan_entity_pages` writes its removals to."""
    from datetime import datetime  # noqa: PLC0415

    log = WIKI_DIR / "log.md"
    existing = log.read_text(encoding="utf-8") if log.exists() else "# Lifehug Compile Log\n"
    stamp = datetime.now().isoformat(timespec="seconds")
    write_text(log, existing.rstrip() + f"\n- {stamp}: {message}\n")


# ---------------------------------------------------------------------------
# Step g — the append-only audit record
# ---------------------------------------------------------------------------

def load_merges() -> dict:
    data = read_json(FOCUS_MERGES_FILE, default=None)
    if not isinstance(data, dict) or not isinstance(data.get("merges"), list):
        return {"version": MERGES_VERSION, "merges": []}
    data.setdefault("version", MERGES_VERSION)
    return data


def _append_merge_record(record: dict) -> None:
    """Append-only: a merge record is never rewritten or removed, so the
    file is the vault's permanent answer to "where did this focus go?"."""
    data = load_merges()
    data["merges"].append(record)
    write_json(FOCUS_MERGES_FILE, data)


# ---------------------------------------------------------------------------
# The plan
# ---------------------------------------------------------------------------

def plan_merge(survivor_id: str, loser_id: str, *, roadmap: dict | None = None,
               adopt_target: bool = False, when: str | None = None) -> dict:
    """Resolve the complete transaction WITHOUT writing anything.

    Every step's concrete edits are computed here, so `--dry-run` prints
    exactly what `focus_merge` would do, and a merge that cannot proceed
    raises before the first byte is written."""
    roadmap = load_roadmap() if roadmap is None else roadmap
    when = when or date.today().isoformat()

    survivor, loser = validate(roadmap, survivor_id, loser_id)
    warnings: list[str] = []

    categories_before = list(survivor.get("categories", []))
    categories_after = _ordered_union(categories_before, loser.get("categories", []))
    neighborhoods_after = _ordered_union(survivor.get("neighborhoods", []), loser.get("neighborhoods", []))
    target_before = int(survivor.get("target_depth") or 0)
    target_after = max(target_before, int(loser.get("target_depth") or 0)) if adopt_target else target_before

    md_text = QUESTIONS_FILE.read_text(encoding="utf-8") if QUESTIONS_FILE.exists() else ""
    bank_edits, bank_warnings = _bank_plan(md_text, survivor, loser, when)
    warnings.extend(bank_warnings)

    repoints, alias_additions, ledger_aliases = _roster_plan(survivor, loser)
    wiki, wiki_warnings = _wiki_plan(loser)
    warnings.extend(wiki_warnings)

    files_touched = [_rel(ROADMAP_FILE)]
    if bank_edits:
        files_touched.append(_rel(QUESTIONS_FILE))
    from entity_roster import roster_file  # noqa: PLC0415
    for item in [*repoints, *alias_additions]:
        ref = _rel(roster_file(item["type"]))
        if ref not in files_touched:
            files_touched.append(ref)
    from focus_curation import SETTLED_FILE  # noqa: PLC0415
    files_touched.append(_rel(SETTLED_FILE))
    if wiki["action"] == "delete":
        files_touched.append(str(wiki["page"]))
    files_touched.append(_rel(FOCUS_MERGES_FILE))

    return {
        "survivor": {"id": survivor.get("id"), "label": survivor.get("label")},
        "loser": {"id": loser.get("id"), "label": loser.get("label")},
        "adopt_target": bool(adopt_target),
        "date": when,
        "roadmap": {
            "categories_before": categories_before,
            "categories_after": categories_after,
            "categories_moved": [c for c in categories_after if c not in categories_before],
            "neighborhoods_after": neighborhoods_after,
            "target_depth_before": target_before,
            "target_depth_after": target_after,
            "dropped_entry": loser.get("id"),
        },
        "bank": bank_edits,
        "roster_repoints": repoints,
        "roster_aliases": alias_additions,
        "ledger_aliases": ledger_aliases,
        "settled_ids": _settled_ids(loser),
        "wiki": wiki,
        "files_touched": files_touched,
        "warnings": warnings,
    }


def _rel(path: Path) -> str:
    try:
        return Path(path).relative_to(REPO_DIR).as_posix()
    except ValueError:
        return str(path)


def _settled_ids(loser: dict) -> list[str]:
    """The recommendation ids a merge settles, so `recommend()`/curation can
    never re-propose the loser. `recommend_focuses` mints ids as
    `rec-<slugify(entity)>`; both the loser's label and its id are recorded
    because a focus's id can drift from a user-edited label."""
    label = str(loser.get("label") or "")
    ids = []
    for raw in (label, str(loser.get("id") or "")):
        if not raw:
            continue
        candidate = f"rec-{slugify(raw)}"
        if candidate not in ids:
            ids.append(candidate)
    return ids


# ---------------------------------------------------------------------------
# The verb
# ---------------------------------------------------------------------------

def focus_merge(survivor_id: str, loser_id: str, *, dry_run: bool = False,
                adopt_target: bool = False) -> dict:
    """Fuse `loser_id` into `survivor_id`. See the module docstring for the
    step order. `dry_run=True` writes NOTHING and returns the same plan."""
    roadmap = load_roadmap()
    plan = plan_merge(survivor_id, loser_id, roadmap=roadmap, adopt_target=adopt_target)

    if dry_run:
        return {"status": "dry_run", "applied": False, "plan": plan}

    survivor_id_resolved = str(plan["survivor"]["id"])
    loser_id_resolved = str(plan["loser"]["id"])

    # (b) roadmap
    focuses = []
    for focus in roadmap.get("focuses", []):
        if focus.get("id") == loser_id_resolved:
            continue
        if focus.get("id") == survivor_id_resolved:
            focus = dict(focus)
            focus["categories"] = plan["roadmap"]["categories_after"]
            focus["neighborhoods"] = plan["roadmap"]["neighborhoods_after"]
            focus["target_depth"] = plan["roadmap"]["target_depth_after"]
        focuses.append(focus)
    write_json(ROADMAP_FILE, {"version": roadmap.get("version", 1), "generated_at": now_utc(),
                              "focuses": focuses})

    # (c) bank
    if plan["bank"]:
        write_text(QUESTIONS_FILE, _apply_bank(QUESTIONS_FILE.read_text(encoding="utf-8"), plan["bank"]))

    # (d) rosters
    _apply_rosters(plan)

    # (e) curation settled ledger
    import focus_curation  # noqa: PLC0415

    focus_curation.record_settled_merge(
        plan["settled_ids"], survivor_id_resolved,
        aliases=plan["ledger_aliases"], loser_id=loser_id_resolved)

    # (f) wiki
    if plan["wiki"]["action"] == "delete":
        page = REPO_DIR / str(plan["wiki"]["page"])
        page.unlink(missing_ok=True)
        _log_wiki(f"removed {plan['wiki']['page']} (focus {loser_id_resolved} merged into {survivor_id_resolved})")

    # (g) audit
    record = {
        "at": now_utc(),
        "date": plan["date"],
        "survivor": survivor_id_resolved,
        "loser": loser_id_resolved,
        "loser_label": plan["loser"]["label"],
        "categories_moved": plan["roadmap"]["categories_moved"],
        "roster_repoints": [{"type": r["type"], "entity": r["entity"]} for r in plan["roster_repoints"]],
        "files_touched": plan["files_touched"],
        "warnings": plan["warnings"],
    }
    _append_merge_record(record)

    # (h) recompile sentinel — never an inline compile
    COMPILE_NEEDED_FILE.parent.mkdir(parents=True, exist_ok=True)
    COMPILE_NEEDED_FILE.touch()

    return {"status": "merged", "applied": True, "plan": plan, "record": record}


def _apply_rosters(plan: dict) -> None:
    survivor_id = str(plan["survivor"]["id"])
    by_type: dict[str, list[dict]] = {}
    for item in plan["roster_repoints"]:
        by_type.setdefault(item["type"], []).append({"op": "repoint", **item})
    for item in plan["roster_aliases"]:
        by_type.setdefault(item["type"], []).append({"op": "alias", **item})

    for entity_type, operations in by_type.items():
        path, data = _roster_payload(entity_type)
        if data is None:
            continue
        for operation in operations:
            entity = data["entities"][operation["index"]]
            if operation["op"] == "repoint":
                entity["maps_to_focus"] = survivor_id
            else:
                entity["aliases"] = [*entity.get("aliases", []), *operation["aliases_added"]]
        write_json(path, data)


# ---------------------------------------------------------------------------
# Printing
# ---------------------------------------------------------------------------

def print_plan(plan: dict, *, dry_run: bool) -> None:
    head = "[DRY RUN] focus-merge" if dry_run else "focus-merge"
    survivor, loser = plan["survivor"], plan["loser"]
    print(f"{head}: {loser['label']} ({loser['id']}) → {survivor['label']} ({survivor['id']})")
    print()

    road = plan["roadmap"]
    print("(b) roadmap — state/roadmap.json")
    print(f"    categories : {road['categories_before']} → {road['categories_after']}"
          f"  (moved: {road['categories_moved'] or 'none'})")
    print(f"    neighborhoods: {road['neighborhoods_after'] or 'none'}")
    print(f"    target_depth: {road['target_depth_before']} → {road['target_depth_after']}"
          f"{'' if plan['adopt_target'] else '  (unchanged — pass --adopt-target to raise it)'}")
    print(f"    drop entry : {road['dropped_entry']}")
    print()

    print("(c) question bank — headers annotated, question ids untouched")
    if not plan["bank"]:
        print("    no category headers to annotate")
    for edit in plan["bank"]:
        print(f"    {edit['category']}: {edit['line_before']}")
        print(f"     -> {edit['line_after']}")
        print(f"     +  {edit['comment']}")
    print()

    print("(d) entity rosters")
    if not plan["roster_repoints"]:
        print("    no maps_to_focus repoints")
    for item in plan["roster_repoints"]:
        print(f"    {item['type']}: {item['entity']} maps_to_focus {item['from']} → {item['to']}")
    if plan["roster_aliases"]:
        for item in plan["roster_aliases"]:
            print(f"    {item['type']}: {item['entity']} += aliases {item['aliases_added']}")
    else:
        print(f"    no survivor roster entry — aliases go to the settled ledger: {plan['ledger_aliases']}")
    print()

    print("(e) curation settled ledger — state/focus_curation/settled.json")
    print(f"    settle: {plan['settled_ids']} (bucket 'merge' → never re-proposed)")
    print()

    wiki = plan["wiki"]
    print("(f) wiki")
    if wiki["action"] == "delete":
        print(f"    remove {wiki['page']} (origin: focus) — the survivor's page absorbs at next compile")
    elif wiki["action"] == "keep":
        print(f"    KEEP {wiki['page']} (origin: {wiki['origin'] or 'missing'}) — hand-authored, never removed")
    else:
        print("    no focus page to remove")
    print()

    print("(g) audit — state/focus_merges.json (append-only)")
    print(f"    files touched: {plan['files_touched']}")
    print()
    print("(h) recompile — touch state/.compile-needed (never an inline compile)")

    if plan["warnings"]:
        print()
        print("warnings:")
        for warning in plan["warnings"]:
            print(f"    ⚠ {warning}")
    if dry_run:
        print()
        print("[DRY RUN] nothing was written.")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Merge one Focus into another — a deliberate, auditable, "
                    "multi-file transaction (ADR 0012).")
    parser.add_argument("survivor", help="The Focus id that survives and absorbs")
    parser.add_argument("loser", help="The Focus id that is absorbed and dropped")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print the full plan and write nothing")
    parser.add_argument("--adopt-target", action="store_true",
                        help="Raise the survivor's target_depth to max(survivor, loser)")
    parser.add_argument("--json", action="store_true", help="Print the result as JSON")
    args = parser.parse_args(argv)

    try:
        result = focus_merge(args.survivor, args.loser,
                             dry_run=args.dry_run, adopt_target=args.adopt_target)
    except FocusMergeError as exc:
        print(f"✗ focus-merge: {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0

    print_plan(result["plan"], dry_run=args.dry_run)
    if result["applied"]:
        print()
        print(f"✓ merged {result['record']['loser']} into {result['record']['survivor']} "
              f"— recorded in state/focus_merges.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
