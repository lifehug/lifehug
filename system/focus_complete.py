#!/usr/bin/env python3
"""A Focus at 100% is a milestone, not an end (v394, ADR 0044).

Before this module, finishing a Focus changed nothing: its category ran out of
open questions, the planner moved on, and the Focus kept its slot in the
autopilot's keep-3-developing set, so a finished Focus could block a new one.
This is the whole of what happens now, in one place:

1. **The sweep** (`focus-complete-sweep`, one weekly step after `quality` and
   `judgment`, before `promote`). A Focus whose categories hold zero open,
   non-retired questions and at least one answered question takes
   `phase = "complete"`, AUTOMATICALLY. The rule is COVERAGE OF THE CATEGORY,
   not the tier: a `basic` Focus that answered its 8 questions is as complete
   as an `extreme` one that answered 50 (owner decision D3). The record keeps
   `completion = {completed_at, answered, total, row, second_pass, ...}`.
   `focus-finish` is unchanged: it is the manual accelerator that drains a
   Focus faster; it marks nothing complete.
2. **The second pass, by value, as Review candidates** (D2). On the completion
   transition only, for THAT Focus's person, the gap-finders the weekly run has
   already computed (the published Timeline's landmark opportunities,
   keystones and open date gaps) are filed as candidates with
   `source = "focus_complete:<slug>"`: through `question_craft.evaluate` like
   every candidate, parked at `needs_review` with a structural reason so the
   auto-promoter can never carry them into the bank, capped per Focus, and
   never by a model call at completion time. The owner approves what deserves
   a second pass. Mirror contradictions about the person are COUNTED on the
   row, not turned into questions: a contradiction is Mirror's own work and the
   Timeline lane deliberately keeps it off the question queue
   (`timeline_candidates` docstring).
3. **Say so once.** One Mirror row, kind `focus_complete`, with three Plays the
   host binds: `keep_going` (the second-pass candidates get Review attention),
   `rest` (the row closes; nothing else), `make` (a `studio_card` hint the
   platform turns into a Studio project card once Studio unparks). The row id
   is `fc:<slug>:<completed_at>`: minted once per completion, never re-minted
   while the Focus stays complete, and a Focus that reopens and finishes again
   is a new milestone with a new id.
4. **Reopen is derived.** A complete Focus whose category gains an open
   question (a new question approved into the bank) is `developing` again:
   `roadmap.is_complete` reads the live fill, so the planner and the autopilot
   are right on the next read, and `roadmap.reopen_completed` persists it on
   the next roadmap rebuild.

Nothing here appends to the question bank. A second-pass question reaches the
bank only through the existing candidate promotion path, on the owner's word.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

SYSTEM_DIR = Path(__file__).resolve().parent
if str(SYSTEM_DIR) not in sys.path:
    sys.path.insert(0, str(SYSTEM_DIR))

import question_craft  # noqa: E402
import roadmap as roadmap_mod  # noqa: E402
from lifehug_core import now_utc, parse_questions, write_json  # noqa: E402
from roadmap import COMPLETE_PHASE, focus_fill  # noqa: E402

#: The Mirror row kind this module owns. ONE kind.
FOCUS_COMPLETE_KIND = "focus_complete"

#: The three Plays a host binds on the row. `keep_going` / `rest` / `make`.
PLAYS = ("keep_going", "rest", "make")

#: Row states. `open` is the only one a surface renders.
ROW_OPEN = "open"
ROW_STATES = (ROW_OPEN, "kept_going", "rested", "made")
_PLAY_TO_STATE = {"keep_going": "kept_going", "rest": "rested", "make": "made"}

#: `source` on every second-pass candidate: `focus_complete:<slug>`.
SOURCE_PREFIX = "focus_complete:"
CANDIDATE_KIND = "focus_second_pass"

#: How many second-pass candidates one completion may file. The owner approves
#: each one, so the pile is kept small: a milestone, not a to-do list.
SECOND_PASS_CAP = 3

#: Why a second-pass candidate is parked. A STRUCTURAL reason: it contains
#: neither "score" nor "quality", so `question_candidates._is_resurfaceable`
#: leaves it for a human. The auto-promoter never takes it (D2).
NEEDS_REVIEW_REASON = "second_pass: focus_complete"

#: Open date-gap work item kinds the second pass may ask about. Contradictions
#: are Mirror's, not the question queue's.
GAP_KINDS = ("precision_gap", "missing_anchor")

#: The Studio card hint (`make`): platform-side rendering waits on Studio.
STUDIO_CARD_KIND = "focus_story"


# --------------------------------------------------------------------------
# Whose Focus is it — the keys a row must match to be "about" the person
# --------------------------------------------------------------------------


def _key(text: object) -> str:
    return " ".join(re.sub(r"[^\w\s]", " ", str(text or "").casefold()).split())


def person_keys(focus: dict) -> set[str]:
    """Every normalized string that names this Focus's person: label, slug, the
    person record's name, aliases and handle. Empty for a non-person Focus
    with no `person_ref`: the second pass then has no one to ask about."""
    keys = {_key(focus.get("label"))}
    ref = str(focus.get("person_ref") or "")
    if ref:
        keys.add(_key(ref))
        slug = ref.split("/", 1)[-1]
        keys.add(_key(slug.replace("-", " ")))
        try:
            from entity_roster import load_identity_roster  # noqa: PLC0415

            for entity in load_identity_roster("person").get("entities", []):
                if str(entity.get("slug") or "") != slug:
                    continue
                keys.add(_key(entity.get("name")))
                for alias in entity.get("aliases") or []:
                    keys.add(_key(alias.get("text") if isinstance(alias, dict) else alias))
        except Exception:  # noqa: BLE001 — a roster problem is "fewer names"
            pass
    keys.discard("")
    return keys


def _mentions(keys: set[str], *values: object) -> bool:
    """Does any value name the person, as a whole word run?"""
    for value in values:
        text = f" {_key(value)} "
        if text.strip() in keys:
            return True
        if any(f" {key} " in text for key in keys):
            return True
    return False


# --------------------------------------------------------------------------
# The second pass
# --------------------------------------------------------------------------


def _gap_rows(focus: dict, view: dict) -> list[dict]:
    """Second-pass proposals for this person, from the published projection the
    weekly run already computed. Pure: no model, no vault write."""
    keys = person_keys(focus)
    if not keys:
        return []
    import timeline_candidates as tc  # noqa: PLC0415

    rows: list[dict] = []
    # Landmark opportunities and keystones: the entry rule with no mint cap
    # (the owner reviews them, the queue is not being filled).
    for cand in tc.candidates_from_view(view, landmark_cap=tc.UNCAPPED):
        if _mentions(keys, cand.get("anchor"), cand.get("label"), cand.get("question")):
            rows.append({"origin": cand["id"], "text": cand["question"],
                         "leverage": int(cand.get("leverage") or 0),
                         "gap": cand.get("source") or "timeline"})
    # Open date gaps on a node about the person.
    for item in (view.get("work_items") or ()) if isinstance(view, dict) else ():
        if not isinstance(item, dict) or item.get("kind") not in GAP_KINDS:
            continue
        if item.get("state", "open") != "open":
            continue
        intent = " ".join(str(item.get("prompt_intent") or "").split())
        if "?" not in intent:
            continue
        if _mentions(keys, item.get("subject_ref"), item.get("node_ref")) or (
                _mentions(keys, intent)):
            rows.append({"origin": f"wi:{item.get('work_item_id')}", "text": intent,
                         "leverage": 0, "gap": item.get("kind")})
    rows.sort(key=lambda r: (-r["leverage"], r["origin"]))
    return rows


def count_open_contradictions(focus: dict, vault_root: object = None) -> int:
    """How many open Mirror rows about this person. Counted, never asked."""
    keys = person_keys(focus)
    if not keys:
        return 0
    try:
        import mirror_work  # noqa: PLC0415

        root = vault_root or roadmap_mod.REPO_DIR
        rows = mirror_work.load_mirror_rows(root, cap=None)
    except Exception:  # noqa: BLE001 — no projection is "none counted"
        return 0
    return sum(1 for row in rows
               if row.kind == "contradiction"
               and _mentions(keys, row.subject_ref, row.headline))


def second_pass(focus: dict, view: dict | None = None, *, store: dict | None = None,
                bank_text: str | None = None, cap: int = SECOND_PASS_CAP,
                dry_run: bool = False) -> list[dict]:
    """File this Focus's second-pass candidates; return the records filed.

    Every candidate goes through `question_craft.evaluate`: a FAIL is dropped,
    anything else is filed at `needs_review` with a structural reason. Never
    touches the bank. Idempotent: the candidate id is a digest of the gap's own
    identity, so a re-run files nothing twice.
    """
    import question_candidates as qc  # noqa: PLC0415
    import timeline_candidates as tc  # noqa: PLC0415

    slug = str(focus.get("id") or "")
    if view is None:
        view = tc.load_view()
    data = store if store is not None else qc.load_store(qc.QUESTION_CANDIDATES_FILE)
    if bank_text is None:
        qfile = roadmap_mod.QUESTIONS_FILE
        bank_text = qfile.read_text(encoding="utf-8") if Path(qfile).exists() else ""
    bank_pairs = [(str(q["id"]), str(q["text"])) for q in parse_questions(bank_text)]
    existing = {str(c.get("id")) for c in data.get("candidates", [])}
    pairs = [(str(c.get("id", "")), str(c.get("text", ""))) for c in data.get("candidates", [])]
    categories = [str(c) for c in focus.get("categories") or []]
    filed: list[dict] = []
    for row in _gap_rows(focus, view):
        if len(filed) >= cap:
            break
        digest = hashlib.sha1(f"{slug}|{row['origin']}".encode()).hexdigest()[:10]
        cid = f"cand-fc-{slug}-{digest}"
        if cid in existing:
            continue
        text = row["text"].strip()
        verdict = question_craft.evaluate(
            text, context={"bank": bank_pairs + pairs}, with_score=False)
        if verdict["verdict"] == question_craft.FAIL:
            continue
        reason = f"{NEEDS_REVIEW_REASON}:{slug}"
        if verdict["verdict"] == question_craft.REVIEW:
            reason += f" (craft_review: {', '.join(verdict['reasons'])})"
        if qc.near_duplicate_of(text, bank_pairs + pairs):
            continue
        record = {
            "id": cid,
            "kind": CANDIDATE_KIND,
            "text": text,
            "source": f"{SOURCE_PREFIX}{slug}",
            "source_path": f"{SOURCE_PREFIX}{slug}",
            "second_pass_origin": row["origin"],
            "second_pass_gap": row["gap"],
            "focus_id": slug,
            "priority": round(min(0.9, 0.5 + row["leverage"] / 40), 2),
            "reason": f"{focus.get('label', slug)} is complete; the Timeline still has this gap.",
            "status": "needs_review",
            "needs_review_reason": reason,
            "story_function": "meaning",
            "created_at": now_utc(),
        }
        if categories:
            record["target_category"] = categories[0]
        filed.append(record)
        existing.add(cid)
        pairs.append((cid, text))
    if filed and not dry_run:
        data.setdefault("candidates", []).extend(filed)
        if store is None:
            qc.save_store(data, qc.QUESTION_CANDIDATES_FILE)
    return filed


# --------------------------------------------------------------------------
# The sweep
# --------------------------------------------------------------------------


def completes(focus: dict, fill: dict) -> bool:
    """The completion rule, whole: not the primary life story, has categories,
    zero open questions, at least one answered. Tier plays no part (D3)."""
    return (not focus.get("primary")
            and bool(focus.get("categories"))
            and fill["pending"] == 0
            and fill["answered"] >= 1
            and focus.get("phase") != COMPLETE_PHASE)


def sweep(dry_run: bool = False, *, now: str | None = None, view: dict | None = None,
          roadmap: dict | None = None, questions: list[dict] | None = None) -> dict:
    """The weekly step. Returns `{completed, reopened, candidates, ...}`.

    Reopens first (a complete Focus that gained an open question), then marks
    every newly complete Focus and runs ITS second pass: only on this
    transition, only for this Focus.
    """
    when = now or now_utc()
    rm = roadmap if roadmap is not None else roadmap_mod.load_roadmap()
    if not rm.get("focuses"):
        rm = roadmap_mod.rebuild_roadmap(write=False)
    qfile = roadmap_mod.QUESTIONS_FILE
    bank_text = qfile.read_text(encoding="utf-8") if Path(qfile).exists() else ""
    qs = questions if questions is not None else parse_questions(bank_text)
    reopened = roadmap_mod.reopen_completed(rm.get("focuses", []), bank_text, when=when)

    completed: list[dict] = []
    filed: list[dict] = []
    import question_candidates as qc  # noqa: PLC0415

    store = qc.load_store(qc.QUESTION_CANDIDATES_FILE)
    for focus in rm.get("focuses", []):
        fill = focus_fill(focus, qs)
        if not completes(focus, fill):
            continue
        record = {
            "completed_at": when,
            "answered": fill["answered"],
            "total": fill["total"],
            "tier": focus.get("tier"),
            "target": fill["target"],
            "phase_before": focus.get("phase", "active"),
            "row": ROW_OPEN,
            "second_pass": [],
            "contradictions": 0,
        }
        candidates = second_pass(focus, view, store=store, bank_text=bank_text,
                                 dry_run=dry_run)
        record["second_pass"] = [c["id"] for c in candidates]
        record["contradictions"] = count_open_contradictions(focus)
        filed.extend(candidates)
        completed.append({"focus": focus.get("id"), "label": focus.get("label"),
                          **{k: record[k] for k in ("answered", "total")},
                          "second_pass": len(candidates)})
        if not dry_run:
            focus["phase"] = COMPLETE_PHASE
            focus["completion"] = record
    if not dry_run and (completed or reopened):
        rm["generated_at"] = when
        write_json(roadmap_mod.ROADMAP_FILE, rm)
        if filed:
            qc.save_store(store, qc.QUESTION_CANDIDATES_FILE)
    return {"completed": completed, "reopened": reopened, "candidates": filed,
            "dry_run": dry_run}


# --------------------------------------------------------------------------
# The Mirror row and its Plays
# --------------------------------------------------------------------------


def row_id(focus: dict) -> str:
    return f"fc:{focus.get('id')}:{(focus.get('completion') or {}).get('completed_at', '')}"


def row_for(focus: dict) -> dict | None:
    """The Mirror row for a complete Focus, or None. Pure; derived from the
    roadmap record, so there is no second store to reconcile."""
    completion = focus.get("completion") or {}
    if focus.get("phase") != COMPLETE_PHASE or not completion.get("completed_at"):
        return None
    state = completion.get("row", ROW_OPEN)
    label = str(focus.get("label") or focus.get("id"))
    answered, total = int(completion.get("answered") or 0), int(completion.get("total") or 0)
    headline = f"{label} is complete — {answered} of {total} answered"
    notes = []
    waiting = len(completion.get("second_pass") or ())
    if waiting:
        notes.append(f"{waiting} more question{'s' if waiting != 1 else ''} worth asking "
                     "are waiting on Review")
    contradictions = int(completion.get("contradictions") or 0)
    if contradictions:
        notes.append(f"{contradictions} open contradiction{'s' if contradictions != 1 else ''} "
                     "about them on Mirror")
    rid = row_id(focus)
    return {
        "work_item_id": rid,
        "kind": FOCUS_COMPLETE_KIND,
        "state": state,
        "headline": headline,
        "description": ". ".join([headline] + notes) + ".",
        "severity": 0.0,
        "focus_id": focus.get("id"),
        "plays": list(PLAYS),
        "play": {"kind": FOCUS_COMPLETE_KIND, "ref": rid, "label": headline,
                 "focus_id": focus.get("id"), "plays": list(PLAYS)},
        "updated_at": completion.get("completed_at"),
    }


def rows(roadmap: dict | None = None, *, include_resolved: bool = False) -> list[dict]:
    """Every focus_complete row, newest completion first. Quiet by default: only
    `open` rows."""
    rm = roadmap if roadmap is not None else roadmap_mod.load_roadmap()
    out = [r for r in (row_for(f) for f in rm.get("focuses", [])) if r]
    if not include_resolved:
        out = [r for r in out if r["state"] == ROW_OPEN]
    out.sort(key=lambda r: (r["updated_at"] or "", r["work_item_id"]), reverse=True)
    return out


def play(focus_id: str, which: str, *, roadmap: dict | None = None,
         store: dict | None = None, now: str | None = None, write: bool = True) -> dict:
    """Run one of the row's three Plays. Returns what happened.

    `keep_going` gives the Focus's second-pass candidates Review attention
    (a flag; they stay `needs_review`, so the owner still decides each one).
    `rest` closes the row and does nothing else. `make` closes the row and
    records a `studio_card` hint for the platform. A Play on a Focus that is
    not complete, or a row already played, raises ValueError: the row is
    played once.
    """
    if which not in PLAYS:
        raise ValueError(f"unknown Play {which!r}; choose from {', '.join(PLAYS)}")
    rm = roadmap if roadmap is not None else roadmap_mod.load_roadmap()
    focus = roadmap_mod.find_focus(rm, focus_id)
    if not focus or focus.get("phase") != COMPLETE_PHASE:
        raise ValueError(f"{focus_id} is not a complete Focus")
    completion = dict(focus.get("completion") or {})
    if completion.get("row", ROW_OPEN) != ROW_OPEN:
        raise ValueError(f"the {focus_id} completion row was already played "
                         f"({completion.get('row')})")
    when = now or now_utc()
    result: dict = {"focus": focus.get("id"), "play": which, "row_id": row_id(focus)}
    completion["row"] = _PLAY_TO_STATE[which]
    completion["played_at"] = when
    if which == "keep_going":
        import question_candidates as qc  # noqa: PLC0415

        data = store if store is not None else qc.load_store(qc.QUESTION_CANDIDATES_FILE)
        marked = []
        for cand in data.get("candidates", []):
            if (cand.get("source") == f"{SOURCE_PREFIX}{focus.get('id')}"
                    and cand.get("status") == "needs_review"):
                cand["review_attention"] = True
                cand["attention_at"] = when
                marked.append(cand["id"])
        result["review_attention"] = marked
        if write and store is None:
            qc.save_store(data, qc.QUESTION_CANDIDATES_FILE)
    elif which == "make":
        card = {
            "kind": STUDIO_CARD_KIND,
            "focus_id": focus.get("id"),
            "title": f"The story of {focus.get('label') or focus.get('id')} so far",
            "answered": completion.get("answered"),
            "categories": list(focus.get("categories") or []),
            "requested_at": when,
        }
        completion["studio_card"] = card
        result["studio_card"] = card
    focus["completion"] = completion
    if write:
        rm["generated_at"] = when
        write_json(roadmap_mod.ROADMAP_FILE, rm)
    return result


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------


def cli(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Complete a Focus at 100%% (ADR 0044)")
    sub = parser.add_subparsers(dest="cmd")
    p = sub.add_parser("sweep", help="Mark every Focus at 100%% complete; file its second pass")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--json", action="store_true")
    p = sub.add_parser("rows", help="The open focus_complete Mirror rows")
    p.add_argument("--json", action="store_true")
    p = sub.add_parser("play", help="Play a focus_complete row: keep_going | rest | make")
    p.add_argument("focus_id")
    p.add_argument("which", choices=PLAYS)
    args = parser.parse_args(argv)

    if args.cmd in (None, "sweep"):
        result = sweep(dry_run=getattr(args, "dry_run", False))
        if getattr(args, "json", False):
            print(json.dumps(result, indent=2, sort_keys=True))
            return 0
        prefix = "Would complete" if result["dry_run"] else "Completed"
        for row in result["completed"]:
            print(f"✓ {prefix}: {row['label']} — {row['answered']} of {row['total']} answered; "
                  f"{row['second_pass']} second-pass candidate(s) on Review")
        for fid in result["reopened"]:
            print(f"↺ Reopened: {fid} (a new question was approved)")
        if not result["completed"] and not result["reopened"]:
            print("No Focus reached 100% this run.")
        return 0
    if args.cmd == "rows":
        found = rows()
        if args.json:
            print(json.dumps(found, indent=2, sort_keys=True))
        else:
            for row in found:
                print(f"{row['work_item_id']}  {row['headline']}")
            if not found:
                print("No completed Focus is waiting.")
        return 0
    if args.cmd == "play":
        try:
            result = play(args.focus_id, args.which)
        except ValueError as exc:
            print(f"✗ {exc}")
            return 1
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(cli())
