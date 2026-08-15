#!/usr/bin/env python3
"""Lifehug — Focus-Curation interaction loader + runtime.

The third and smallest layer of the focus-duplicate-curation contract's
three-layer dedupe (ADR 0010):

    1. Door guards (roadmap.py) — deterministic, kills exact-name-modulo-
       case duplicates at creation time.
    2. Roster fold (recommend_focuses.py, at recommend() time) —
       deterministic, folds settled roster aliases before scoring.
    3. THIS MODULE — AI judgment, for first-encounter near-name pairs
       (the "Betty Jo" / "Betty Jo Taylor" shape) neither deterministic
       layer can resolve on its own.

There is NO deterministic fallback that merges here. Absent AI (a keyless
machine with no completed agent task), layer 2's roster fold is the floor —
a near-name pair simply sits apart, correctly, rather than being merged on
a guess (see ``interactions/focus_curation/README.md`` §1).

Public API:

    build_pending_idea_list(*, roadmap=None, pending=None) -> list[dict]
    build_roster_context(idea_types) -> list[dict]
    build_existing_focuses(roadmap=None) -> dict[str, str]
    build_curation_prompt(pending_ideas, roster_context, existing_focuses) -> str
    apply_verdicts(verdict, pending_ideas, *, roadmap=None) -> dict
    run_curation(...) -> dict

Every vault read goes through the same modules the rest of the Focus
machinery already uses (roadmap.load_roadmap, recommend_focuses.
load_recommendation_state, entity_roster.load_roster) — never a hand-built
path, and never a re-derived normalization (normalized_focus_key stays the
one shared definition in lifehug_core.py).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

SYSTEM_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SYSTEM_DIR))

from lifehug_core import (  # noqa: E402
    FOCUS_CURATION_STATE_DIR,
    INTERACTIONS_DIR,
    now_utc,
    read_json,
    write_json,
    write_text,
)
from roadmap import load_roadmap  # noqa: E402

INTERACTION_NAME = "focus_curation"

# role.worker: medium capability tier (interaction.yaml) — mirrors the
# project-wide convention of a single default model string per feature,
# overridable via config.yaml (focus_curation_model).
DEFAULT_MODEL = "claude-opus-4-8"

# state/focus_curation/ — vault data (focus_curation_state in
# vault_contract.json), never a framework file. settled.json is a
# per-id ledger of already-curated pending-idea ids (contract: "applied
# merges persist"). Simplification, documented: once an id has been
# curated into ANY bucket (merge/map/keep), it is never re-presented to
# the JUDGE again — a "keep" verdict is as settled as a "merge" one. This
# trades a theoretical re-judging opportunity (the same id could later form
# a genuinely new near-name pair with a different idea) for guaranteed
# convergence: without this ledger, an id the JUDGE correctly kept apart
# would be re-presented on every recommend()/focus-curate run forever.
SETTLED_FILE = FOCUS_CURATION_STATE_DIR / "settled.json"

_VALID_VERDICT_KEYS = {"merge", "map_to_focus", "keep"}


def _definition_dir(*, framework_root: str | Path | None = None) -> Path:
    if framework_root is not None:
        return Path(framework_root) / "interactions" / INTERACTION_NAME
    return INTERACTIONS_DIR / INTERACTION_NAME


def read_curation_definition(*parts: str, framework_root: str | Path | None = None) -> str:
    """Read one interactions/focus_curation/ definition file verbatim.

    Raises OSError when the file is absent — the definition tree is a
    framework file, not optional vault state."""
    return _definition_dir(framework_root=framework_root).joinpath(*parts).read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Settled-decision ledger (state/focus_curation/settled.json) — see the
# module-level SETTLED_FILE comment for the documented simplification.
# ---------------------------------------------------------------------------

def _load_settled(*, path: Path | None = None) -> dict:
    data = read_json(path or SETTLED_FILE, default=None)
    if not isinstance(data, dict):
        data = {}
    data.setdefault("version", 1)
    data.setdefault("decisions", {})
    return data


def _record_settled(ids: list[str], bucket: str, *, path: Path | None = None) -> None:
    if not ids:
        return
    data = _load_settled(path=path)
    now = now_utc()
    for idea_id in ids:
        data["decisions"][idea_id] = {"bucket": bucket, "at": now}
    write_json(path or SETTLED_FILE, data)


# ---------------------------------------------------------------------------
# Input assembly (contract Scope 4)
# ---------------------------------------------------------------------------

def build_pending_idea_list(*, roadmap: dict | None = None, pending: list[dict] | None = None,
                            settled_path: Path | None = None) -> list[dict]:
    """Pending recommendation ideas needing AI judgment: ids appearing in a
    near-name (token-subset) pair with another idea or an existing focus —
    the residue neither the door guards nor the roster fold (Scopes 1/2)
    can resolve deterministically, MINUS any id already curated in a prior
    run (the settled-decision ledger — see SETTLED_FILE). Deduped, stable
    id order. Reuses focus_dupes.near_name_pairs (the ONE shared near-name
    detector), never re-derived here."""
    from focus_dupes import near_name_pairs  # noqa: PLC0415 — avoid an import-time cycle
    from recommend_focuses import load_recommendation_state  # noqa: PLC0415

    if roadmap is None:
        roadmap = load_roadmap()
    if pending is None:
        pending = load_recommendation_state().get("recommendations", [])

    pairs = near_name_pairs(roadmap, pending)
    idea_ids: set[str] = set()
    for pair in pairs:
        for key in ("shorter_id", "longer_id"):
            raw = str(pair.get(key, ""))
            if raw.startswith("idea:"):
                idea_ids.add(raw[len("idea:"):])

    settled_ids = set(_load_settled(path=settled_path).get("decisions", {}))
    idea_ids -= settled_ids

    by_id = {rec.get("id"): rec for rec in pending}
    return [
        {
            "id": rid,
            "type": by_id[rid].get("type"),
            "entity": by_id[rid].get("entity"),
            "evidence": by_id[rid].get("evidence", []),
        }
        for rid in sorted(idea_ids) if rid in by_id
    ]


def build_roster_context(idea_types: set[str]) -> list[dict]:
    """Settled roster entries for the given entity types — identity signal
    for the CURATE call, never re-derived (entity_roster.load_roster is the
    one roster authority)."""
    try:
        from entity_roster import load_roster  # noqa: PLC0415
    except Exception:
        return []
    out: list[dict] = []
    for etype in sorted(t for t in idea_types if t):
        try:
            entities = load_roster(etype).get("entities", [])
        except Exception:
            continue
        for entity in entities:
            out.append({
                "type": etype,
                "name": entity.get("name"),
                "aliases": entity.get("aliases", []),
                "maps_to_focus": entity.get("maps_to_focus"),
            })
    return out


def build_existing_focuses(roadmap: dict | None = None) -> dict[str, str]:
    """{slug: label} for every non-primary current Focus — the only valid
    map_to_focus targets."""
    if roadmap is None:
        roadmap = load_roadmap()
    return {
        f["id"]: f.get("label", f["id"])
        for f in roadmap.get("focuses", [])
        if f.get("id") and not f.get("primary")
    }


def build_curation_prompt(
    pending_ideas: list[dict],
    roster_context: list[dict],
    existing_focuses: dict[str, str],
    *,
    framework_root: str | Path | None = None,
) -> str:
    """Assemble the CURATE call: identity -> behavior -> examples -> the
    CURATE turn-instructions template with its {placeholder}s filled
    (context/manifest.md's assembly order)."""
    identity = read_curation_definition("prompt", "identity.md", framework_root=framework_root)
    behavior = read_curation_definition("prompt", "behavior.md", framework_root=framework_root)
    try:
        examples = read_curation_definition("prompt", "examples.md", framework_root=framework_root)
    except OSError:
        examples = ""
    full_template = read_curation_definition("prompt", "turn-instructions.md", framework_root=framework_root)
    marker = "## Mode: CURATE"
    template = full_template[full_template.index(marker):].strip()
    filled = (
        template
        .replace("{pending_ideas}", json.dumps(pending_ideas, indent=2, ensure_ascii=False))
        .replace("{roster_context}", json.dumps(roster_context, indent=2, ensure_ascii=False))
        .replace("{existing_focuses}", json.dumps(existing_focuses, indent=2, ensure_ascii=False))
    )
    parts = [identity.strip(), behavior.strip()]
    if examples.strip():
        parts.append(examples.strip())
    parts.append(filled)
    return "\n\n".join(parts)


# ---------------------------------------------------------------------------
# Verdict validation + deterministic application (contract Scope 4)
# ---------------------------------------------------------------------------

def _validate_verdict(verdict: object, valid_ids: set[str], valid_slugs: set[str]) -> bool:
    """Structural validation only — ANY violation makes the whole verdict
    malformed (contract: "malformed verdict -> no-op", never a partial
    application). Enforces prompt/behavior.md's hard rules 1-3."""
    if not isinstance(verdict, dict) or set(verdict.keys()) - _VALID_VERDICT_KEYS:
        return False
    merge = verdict.get("merge", [])
    map_to_focus = verdict.get("map_to_focus", {})
    keep = verdict.get("keep", [])
    if not isinstance(merge, list) or not isinstance(map_to_focus, dict) or not isinstance(keep, list):
        return False

    seen: set[str] = set()

    for group in merge:
        if not isinstance(group, list) or len(group) < 2:
            return False
        if len(set(group)) != len(group):
            return False
        for gid in group:
            if not isinstance(gid, str) or gid not in valid_ids or gid in seen:
                return False
            seen.add(gid)

    for mid, slug in map_to_focus.items():
        if not isinstance(mid, str) or mid not in valid_ids or mid in seen:
            return False
        if not isinstance(slug, str) or slug not in valid_slugs:
            return False
        seen.add(mid)

    for kid in keep:
        if not isinstance(kid, str) or kid not in valid_ids or kid in seen:
            return False
        seen.add(kid)

    return seen == set(valid_ids)


def apply_verdicts(verdict: object, pending_ideas: list[dict], *, roadmap: dict | None = None,
                   settled_path: Path | None = None) -> dict:
    """Deterministic application of one CURATE verdict. A malformed verdict
    applies NOTHING (no partial application) and returns status='invalid'.

    merge: the group's first (canonical) id absorbs the rest — variant
    records are dismissed with dismissed_by='curation', dismiss_reason=''
    (no reason capture, owner decision — README.md §4), same structured-
    marker convention recommend_focuses.py's 'expiry'/'owner' dismissals
    already use.
    map_to_focus: the idea's record is dismissed the same way, carrying a
    structured mapped_to_focus fact (not a reason).
    keep: no-op for that id — it remains pending, untouched."""
    import recommend_focuses as rf  # noqa: PLC0415 — avoid an import-time cycle

    if roadmap is None:
        roadmap = load_roadmap()
    valid_ids = {i["id"] for i in pending_ideas}
    valid_slugs = set(build_existing_focuses(roadmap))

    if not _validate_verdict(verdict, valid_ids, valid_slugs):
        return {"status": "invalid", "applied": False, "merged_groups": 0, "mapped": 0}

    existing = rf.load_recommendation_state()
    recs = existing.get("recommendations", [])
    dismissed = existing.get("dismissed", [])
    by_id = {r["id"]: r for r in recs}
    now = now_utc()

    merged_groups = 0
    for group in verdict.get("merge", []):
        canonical_id, *variant_ids = group
        canonical = by_id.get(canonical_id)
        if canonical is None:
            continue  # canonical isn't a live pending rec anymore — nothing to fold into
        for variant_id in variant_ids:
            variant = by_id.pop(variant_id, None)
            if variant is None:
                continue
            canonical["mention_count"] = int(canonical.get("mention_count", 0)) + int(variant.get("mention_count", 0))
            canonical["emotional_weight"] = round(
                float(canonical.get("emotional_weight", 0.0)) + float(variant.get("emotional_weight", 0.0)), 2,
            )
            canonical["cross_categories"] = sorted(
                set(canonical.get("cross_categories", [])) | set(variant.get("cross_categories", [])),
            )
            canonical["evidence"] = list(dict.fromkeys(
                [*canonical.get("evidence", []), *variant.get("evidence", [])],
            ))[:5]
            variant["dismissed_at"] = now
            variant["dismiss_reason"] = ""
            variant["dismissed_by"] = "curation"
            variant["curated_into"] = canonical_id
            dismissed.append(variant)
        merged_groups += 1

    mapped = 0
    for idea_id, slug in verdict.get("map_to_focus", {}).items():
        rec = by_id.pop(idea_id, None)
        if rec is None:
            continue
        rec["dismissed_at"] = now
        rec["dismiss_reason"] = ""
        rec["dismissed_by"] = "curation"
        rec["mapped_to_focus"] = slug
        dismissed.append(rec)
        mapped += 1

    rf.write_json(rf.FOCUS_RECS_FILE, {
        "version": existing.get("version", 1),
        "generated_at": existing.get("generated_at", now_utc()),
        "recommendations": list(by_id.values()),
        "dismissed": dismissed,
    })

    # Settled-decision discipline (contract Scope 4): record every id this
    # verdict decided so a future run never re-presents it to the JUDGE —
    # see SETTLED_FILE's module-level comment for the documented tradeoff.
    for group in verdict.get("merge", []):
        _record_settled(list(group), "merge", path=settled_path)
    _record_settled(list(verdict.get("map_to_focus", {})), "map", path=settled_path)
    _record_settled(list(verdict.get("keep", [])), "keep", path=settled_path)

    return {"status": "applied", "applied": True, "merged_groups": merged_groups, "mapped": mapped}


# ---------------------------------------------------------------------------
# The keyless-aware runtime (contract Scope 4)
# ---------------------------------------------------------------------------

def _write_task(path: Path, *, prompt: str, pending_ideas: list[dict],
                 roster_context: list[dict], existing_focuses: dict[str, str]) -> None:
    """Keyless emit-task convention (same shape as system/entity_roster.py's
    and system/question_judgment.py's --emit-task)."""
    payload = {
        "type": "focus_curation",
        "prompt": prompt,
        "pending_ideas": pending_ideas,
        "roster_context": roster_context,
        "existing_focuses": existing_focuses,
        "response_format": {"merge": [], "map_to_focus": {}, "keep": []},
    }
    write_text(Path(path), json.dumps(payload, indent=2, ensure_ascii=False) + "\n")


def _resolve_model(explicit: str | None) -> str:
    if explicit:
        return explicit
    from lifehug_core import load_config  # noqa: PLC0415
    return str(load_config().get("focus_curation_model", DEFAULT_MODEL))


def run_curation(
    *,
    dry_run: bool = False,
    emit_task: str | Path | None = None,
    from_response: str | Path | None = None,
    model: str | None = None,
    framework_root: str | Path | None = None,
) -> dict:
    """The CURATE runtime: builds the pending idea list (the near-name
    residue neither door guard nor roster fold resolved), assembles the
    prompt, and either emits a keyless task, applies an agent-written
    response, or calls AI directly. NO deterministic fallback that merges —
    if AI is unavailable and neither --emit-task nor --from-response is
    used, this returns status='no_ai' and applies nothing; the roster fold
    (contract Scope 2) remains the floor."""
    from recommend_focuses import load_recommendation_state  # noqa: PLC0415

    roadmap = load_roadmap()
    pending = load_recommendation_state().get("recommendations", [])
    pending_ideas = build_pending_idea_list(roadmap=roadmap, pending=pending)

    if not pending_ideas:
        return {"status": "no_change", "reason": "no first-encounter near-name pairs to judge"}

    idea_types = {i["type"] for i in pending_ideas if i.get("type")}
    roster_context = build_roster_context(idea_types)
    existing_focuses = build_existing_focuses(roadmap)
    prompt = build_curation_prompt(pending_ideas, roster_context, existing_focuses, framework_root=framework_root)

    result: dict = {
        "pending_ideas": pending_ideas,
        "roster_context": roster_context,
        "existing_focuses": existing_focuses,
    }

    if dry_run:
        result.update({"status": "dry_run", "prompt": prompt})
        return result

    if emit_task:
        _write_task(Path(emit_task), prompt=prompt, pending_ideas=pending_ideas,
                    roster_context=roster_context, existing_focuses=existing_focuses)
        result.update({"status": "emitted_task", "task_path": str(emit_task)})
        return result

    if from_response:
        raw_response = Path(from_response).read_text(encoding="utf-8", errors="replace")
    else:
        try:
            from ai_provider import call_ai  # noqa: PLC0415
        except Exception:
            result.update({"status": "no_ai", "reason": "no AI provider module available"})
            return result
        try:
            raw_response = call_ai(prompt, _resolve_model(model))
        except Exception as exc:  # noqa: BLE001
            from ai_provider import failure_metadata  # noqa: PLC0415
            result.update({"status": "no_ai", "reason": failure_metadata("focus-curation", exc, provider="ai")})
            return result

    try:
        from research_expand import parse_ai_json  # noqa: PLC0415
        verdict = parse_ai_json(raw_response)
    except Exception as exc:  # noqa: BLE001
        result.update({"status": "invalid_response", "error": str(exc)[:500]})
        return result

    applied = apply_verdicts(verdict, pending_ideas, roadmap=roadmap)
    result.update(applied)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Curate first-encounter Focus/idea duplicate variants (interactions/focus_curation/).",
    )
    parser.add_argument("--dry-run", action="store_true", help="Preview the pending ideas and prompt without writing")
    parser.add_argument("--emit-task", metavar="PATH", help="Keyless: emit the curation prompt for agent completion")
    parser.add_argument("--from-response", metavar="PATH", help="Apply an agent-written CURATE verdict (no model call)")
    parser.add_argument("--model", help="AI model override for the CURATE call")
    args = parser.parse_args()

    result = run_curation(dry_run=args.dry_run, emit_task=args.emit_task,
                          from_response=args.from_response, model=args.model)
    status = result.get("status", "unknown")

    if status == "no_change":
        print(f"✓ focus-curate: {result.get('reason')}")
        return 0
    if status == "dry_run":
        print(f"[DRY RUN] focus-curate ({len(result['pending_ideas'])} pending idea(s))")
        print()
        print("--- PROMPT ---")
        print(result["prompt"])
        return 0
    if status == "emitted_task":
        print(f"✓ Emitted curation task ({len(result['pending_ideas'])} idea(s)) to {result['task_path']}")
        print("  Complete it, then: python3 system/focus_curation.py --from-response <file>")
        return 0
    if status == "no_ai":
        print(f"✓ focus-curate: no AI available — {result.get('reason')} (roster fold remains the floor)")
        return 0
    if status == "invalid_response":
        print(f"✗ focus-curate: invalid response: {result.get('error')}", file=sys.stderr)
        return 1
    if status == "invalid":
        print("✗ focus-curate: malformed verdict — applied nothing", file=sys.stderr)
        return 1
    if status == "applied":
        print(f"✓ focus-curate: applied — {result.get('merged_groups', 0)} merge group(s), "
              f"{result.get('mapped', 0)} mapped to existing focus(es)")
        return 0
    print(f"✗ focus-curate: unknown status {status!r}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
