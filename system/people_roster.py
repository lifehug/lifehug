#!/usr/bin/env python3
"""Resolve detected person mentions into a clean canonical roster.

The raw entity detector in recommend_focuses.py is noisy: it surfaces pronouns,
function words, places, and role-words ("Wife", "Father") as `person` entities,
and it never merges aliases ("Grandma" / "Grandma Betty" / "Betty Jo" are one
person). This module turns that noisy queue into `state/people_roster.json` — a
clean list of real, canonical people the wiki can safely build pages for, with
aliases merged and role-words mapped to existing Focuses.

Resolution priority (mirrors wiki synthesis):
  1. AI canonicalization via call_ai (OpenClaw gateway, else Anthropic key).
  2. Keyless desktop path: `--emit-task <path>` writes the prompt + candidates;
     the agent (Claude Code) writes the roster JSON; `--from-response <file>`
     ingests it. No key/gateway needed.
  3. Deterministic fallback when neither is available — conservative: only
     proper-name-looking candidates become people; role-words are dropped unless
     they match an existing Focus.

Page eligibility (a person gets a standalone page) uses the SAME score scale as
focus recommendations, at a lower bar: score >= PAGE_MIN_SCORE (default 8,
"moderate") AND unique_answers >= PAGE_MIN_ANSWERS (default 2) AND the AI marks
it a real person AND it isn't already a Focus. Thresholds are configurable in
config.yaml (people_page_min_score / people_page_min_answers).

Usage:
    python3 system/people_roster.py --resolve
    python3 system/people_roster.py --emit-task /tmp/roster_task.json
    python3 system/people_roster.py --from-response /tmp/roster.json
    python3 system/people_roster.py --show
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

SYSTEM_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SYSTEM_DIR))

from lifehug_core import (
    QUESTIONS_FILE,
    STATE_DIR,
    load_config,
    now_utc,
    parse_categories,
    read_json,
    slugify,
    write_json,
)
from recommend_focuses import (
    STOPWORDS,
    OLD_FOCUS_TERM,
    load_recommendation_state,
)

PEOPLE_ROSTER_FILE = STATE_DIR / "people_roster.json"

PAGE_MIN_SCORE_DEFAULT = 8.0
PAGE_MIN_ANSWERS_DEFAULT = 2

# Generic relationship labels — real referents, but not named individuals. They
# only earn a page when the AI maps them to a specific person; on their own they
# never become a standalone page (the deterministic fallback drops them).
ROLE_WORDS = {
    "mom", "dad", "mother", "father", "brother", "sister", "friend", "mentor",
    "boss", "wife", "husband", "partner", "son", "daughter", "grandma", "grandpa",
    "grandfather", "grandmother", "uncle", "aunt", "cousin", "teacher", "coach",
    "pastor", "priest", "therapist", "neighbor", "colleague", "roommate",
    "boyfriend", "girlfriend", "fiance", "stepmother", "stepfather", "kids",
    "child", "children", "parent", "parents", "family", "spouse",
}

# Capitalized non-names the detector mistakes for people.
EXTRA_STOP = {
    "You", "Which", "Three", "Some", "Not", "Question", "Being", "Things",
    "Pure", "Growing", "Missed", "Answered", "Dating", "Someone", "Something",
    "Anyone", "Everyone", "Nobody", "Somebody", "Everybody", "Anything",
    "Nothing", "Everything", "Both", "Each", "Either", "Neither", "One", "Two",
    "Many", "Most", "Few", "Several", "Another", "Other", "Others", "Same",
    "Such", "Only", "Once", "Twice", "Yes", "No", "Maybe", "Okay", "Well",
}


def _focus_map() -> dict[str, str]:
    """Return {focus_slug: display_name} for existing Focus categories."""
    md = QUESTIONS_FILE.read_text(encoding="utf-8") if QUESTIONS_FILE.exists() else ""
    result: dict[str, str] = {}
    import re
    for cat in parse_categories(md).values():
        if cat.get("group") != "focus":
            continue
        raw = cat.get("name", "")
        name = re.sub(rf"^(Focus|{OLD_FOCUS_TERM})\s*[—–:-]\s*", "", raw, flags=re.IGNORECASE)
        name = re.sub(r"\s*\(.*?\)\s*$", "", name).strip()
        if name:
            result[slugify(name)] = name
    return result


def load_person_candidates(min_answers: int) -> list[dict]:
    """Pre-filtered list of person recommendations worth resolving."""
    state = load_recommendation_state()
    recs = state.get("recommendations", [])
    # Names also detected as a place are almost certainly mis-typed (San Diego, Mesa).
    place_names = {r["entity"].lower() for r in recs if r.get("type") == "place"}
    candidates = []
    for r in recs:
        if r.get("type") != "person":
            continue
        entity = r.get("entity", "").strip()
        if not entity or entity in STOPWORDS or entity in EXTRA_STOP:
            continue
        if entity.lower() in place_names:
            continue
        if r.get("unique_answers", 0) < min_answers:
            continue
        candidates.append({
            "entity": entity,
            "score": r.get("score", 0.0),
            "unique_answers": r.get("unique_answers", 0),
            "cross_categories": r.get("cross_categories", []),
            "evidence": r.get("evidence", [])[:3],
        })
    candidates.sort(key=lambda c: c["score"], reverse=True)
    return candidates


def build_prompt(candidates: list[dict], focus_map: dict[str, str]) -> str:
    focuses = ", ".join(f'"{name}" (slug: {slug})' for slug, name in focus_map.items()) or "(none)"
    lines = [
        "You are curating a private life-story wiki. Below is a NOISY list of candidate "
        "people detected by a crude text scanner. Resolve them into a clean roster of REAL, "
        "DISTINCT individuals.",
        "",
        f"Existing Focus people (already have curated pages): {focuses}",
        "",
        "Rules:",
        "- Merge aliases of the same person into ONE entry (e.g. 'Grandma', 'Grandma Betty', "
        "'Betty Jo' → one person). Put the variants in `aliases`.",
        "- Pick the most complete, natural `name` for each person.",
        "- If a candidate is a generic role word ('Wife', 'Son', 'Father', 'Mother') OR a "
        "first name that clearly refers to an EXISTING Focus person above, set "
        "`maps_to_focus` to that focus slug (do not invent a separate person).",
        "- Set `is_real_person` false for anything that is not actually a specific human "
        "(pronouns, objects, places, abstractions, generic roles with no identifiable person).",
        "- When unsure whether something is a real, identifiable person, set is_real_person false.",
        "",
        "Candidates (entity — score / answers):",
    ]
    for c in candidates:
        ev = "; ".join(c["evidence"][:2])
        lines.append(f"- {c['entity']} — score {c['score']}, {c['unique_answers']} answers. {ev}")
    lines += [
        "",
        "Respond with ONLY a JSON object, no prose:",
        '{"people": [{"name": "Full Name", "aliases": ["Alias1"], '
        '"is_real_person": true, "maps_to_focus": null}]}',
    ]
    return "\n".join(lines)


def _candidate_stats(candidates: list[dict]) -> dict[str, dict]:
    """Index candidate stats by lowercased entity for eligibility lookup."""
    idx: dict[str, dict] = {}
    for c in candidates:
        idx[c["entity"].lower()] = c
    return idx


def _best_stats(person: dict, stats: dict[str, dict]) -> tuple[float, int]:
    """Best score / answer count across a person's name + aliases."""
    names = [person.get("name", "")] + list(person.get("aliases", []))
    score = 0.0
    answers = 0
    for n in names:
        s = stats.get((n or "").lower())
        if s:
            score = max(score, float(s.get("score", 0.0)))
            answers = max(answers, int(s.get("unique_answers", 0)))
    return score, answers


def normalize_people(raw_people: list[dict], candidates: list[dict], focus_map: dict[str, str],
                     min_score: float, min_answers: int) -> list[dict]:
    """Validate AI/agent output into roster entries with computed page_eligible."""
    stats = _candidate_stats(candidates)
    focus_slugs = set(focus_map)
    people = []
    for p in raw_people:
        name = (p.get("name") or "").strip()
        if not name:
            continue
        slug = slugify(name)
        aliases = [a.strip() for a in p.get("aliases", []) if isinstance(a, str) and a.strip()]
        is_real = bool(p.get("is_real_person", False))
        maps_to = p.get("maps_to_focus") or None
        if maps_to and maps_to not in focus_slugs:
            maps_to = focus_map.get(slugify(str(maps_to)))  # tolerate a name instead of a slug
        # A person whose own slug is a Focus is itself that Focus.
        if maps_to is None and slug in focus_slugs:
            maps_to = slug
        score, answers = _best_stats(p, stats)
        page_eligible = (
            is_real and maps_to is None
            and score >= min_score and answers >= min_answers
        )
        people.append({
            "name": name,
            "slug": slug,
            "aliases": aliases,
            "is_real_person": is_real,
            "maps_to_focus": maps_to,
            "score": round(score, 2),
            "unique_answers": answers,
            "page_eligible": page_eligible,
        })
    return people


def deterministic_roster(candidates: list[dict], focus_map: dict[str, str],
                         min_score: float, min_answers: int) -> list[dict]:
    """Conservative no-AI roster: proper-name candidates become people; role-words
    are dropped unless they match an existing Focus. No alias merging."""
    raw = []
    for c in candidates:
        entity = c["entity"]
        low = entity.lower()
        slug = slugify(entity)
        if slug in focus_map:
            # Already a Focus → enrich that Focus, never its own standalone page.
            raw.append({"name": entity, "aliases": [], "is_real_person": True, "maps_to_focus": slug})
            continue
        if low in ROLE_WORDS:
            # Generic role with no AI to resolve it to a person → no page.
            raw.append({"name": entity, "aliases": [], "is_real_person": False, "maps_to_focus": None})
            continue
        # Proper-name heuristic: starts capitalized, all-alphabetic tokens.
        looks_like_name = entity[:1].isupper() and all(p.isalpha() for p in entity.split())
        raw.append({"name": entity, "aliases": [], "is_real_person": looks_like_name,
                    "maps_to_focus": None})
    return normalize_people(raw, candidates, focus_map, min_score, min_answers)


def write_roster(people: list[dict]) -> None:
    write_json(PEOPLE_ROSTER_FILE, {
        "version": 1,
        "resolved_at": now_utc(),
        "people": people,
    })


def load_roster() -> dict:
    return read_json(PEOPLE_ROSTER_FILE, default={"version": 1, "people": []}) or {"version": 1, "people": []}


def _thresholds(args) -> tuple[float, int]:
    cfg = load_config()
    min_score = args.min_score if args.min_score is not None else float(
        cfg.get("people_page_min_score", PAGE_MIN_SCORE_DEFAULT))
    min_answers = args.min_answers if args.min_answers is not None else int(
        cfg.get("people_page_min_answers", PAGE_MIN_ANSWERS_DEFAULT))
    return min_score, min_answers


def main() -> int:
    parser = argparse.ArgumentParser(description="Resolve mentioned people into a canonical roster.")
    parser.add_argument("--resolve", action="store_true",
                        help="Resolve via AI (gateway/key) or deterministic fallback, then write the roster")
    parser.add_argument("--emit-task", metavar="PATH",
                        help="Write the resolution prompt + candidates to PATH and exit (keyless agent path)")
    parser.add_argument("--from-response", metavar="PATH",
                        help="Ingest an agent-written roster JSON ({\"people\": [...]}) and write the roster")
    parser.add_argument("--show", action="store_true", help="Print the current roster")
    parser.add_argument("--min-score", type=float, default=None, help="Page score threshold (default config/8)")
    parser.add_argument("--min-answers", type=int, default=None, help="Page answer threshold (default config/2)")
    parser.add_argument("--model", default=None, help="Override AI model")
    args = parser.parse_args()

    if args.show:
        print(json.dumps(load_roster(), indent=2, ensure_ascii=False))
        return 0

    min_score, min_answers = _thresholds(args)
    focus_map = _focus_map()
    candidates = load_person_candidates(min_answers=1)  # gather broadly; eligibility gates later

    if args.emit_task:
        Path(args.emit_task).write_text(json.dumps({
            "prompt": build_prompt(candidates, focus_map),
            "candidates": candidates,
            "focus_map": focus_map,
            "min_score": min_score,
            "min_answers": min_answers,
            "response_format": {"people": [{"name": "", "aliases": [], "is_real_person": True,
                                            "maps_to_focus": None}]},
        }, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"✓ Emitted roster task ({len(candidates)} candidates) to {args.emit_task}")
        print("  Write the resolved roster JSON, then run: "
              "python3 system/people_roster.py --from-response <file>")
        return 0

    if args.from_response:
        from research_expand import parse_ai_json
        raw = Path(args.from_response).read_text(encoding="utf-8")
        data = parse_ai_json(raw)
        people = normalize_people(data.get("people", []), candidates, focus_map, min_score, min_answers)
        write_roster(people)
        eligible = sum(1 for p in people if p["page_eligible"])
        print(f"✓ Roster written: {len(people)} people, {eligible} page-eligible → {PEOPLE_ROSTER_FILE.name}")
        return 0

    # Default / --resolve: try AI, else deterministic fallback.
    from research_expand import DEFAULT_MODEL, call_ai, parse_ai_json
    model = args.model or DEFAULT_MODEL
    try:
        raw = call_ai(build_prompt(candidates, focus_map), model)
        data = parse_ai_json(raw)
        people = normalize_people(data.get("people", []), candidates, focus_map, min_score, min_answers)
        source = "AI"
    except Exception as exc:  # noqa: BLE001 — no gateway/key or parse failure → safe fallback
        print(f"  ⚠ AI resolution unavailable ({exc}); using deterministic fallback")
        people = deterministic_roster(candidates, focus_map, min_score, min_answers)
        source = "deterministic"
    write_roster(people)
    eligible = sum(1 for p in people if p["page_eligible"])
    print(f"✓ Roster written via {source}: {len(people)} people, {eligible} page-eligible "
          f"→ {PEOPLE_ROSTER_FILE.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
