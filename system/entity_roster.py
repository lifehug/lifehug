#!/usr/bin/env python3
"""Resolve detected mentions into clean, canonical ENTITY rosters — for any
entity type, not just people.

An entity is a node of the life graph: a Person, Place, Period, or Object. The
raw detectors in recommend_focuses.py are noisy (pronouns, fragments, "The
Outside", "Her"), so this module curates them — via AI (gateway/key), a keyless
agent path (--emit-task / --from-response), or a conservative deterministic
fallback — into `state/entity_rosters/<type>.json`: a clean list of entities the
wiki can graduate into pages, with aliases merged and dupes mapped to existing
focuses.

Graduation rules differ by type (entities are the scaffolding of storytelling):
  - person  : a real, distinct individual; score >= min AND >= min answers.
  - place   : a real place; low bar (a few mentions) — we want many.
  - period  : a real life period; low bar; aliases merged (20s/My 20s/Twenties).
  - object  : a SYMBOLIC object that carries meaning (the cleats, the orange
              shorts, the blue Toyota) — judged by the AI, NOT by frequency.

Usage:
    python3 system/entity_roster.py --type place --resolve
    python3 system/entity_roster.py --type object --emit-task /tmp/t.json
    python3 system/entity_roster.py --type place --from-response /tmp/r.json
    python3 system/entity_roster.py --type person --show
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

SYSTEM_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SYSTEM_DIR))

from lifehug_core import (
    ANSWERS_DIR,
    QUESTIONS_FILE,
    STATE_DIR,
    answer_body,
    answer_id_from_filename,
    load_config,
    now_utc,
    parse_categories,
    read_json,
    slugify,
    write_json,
)
from recommend_focuses import STOPWORDS, OLD_FOCUS_TERM, load_recommendation_state

ENTITY_TYPES = ("person", "place", "period", "object")
ENTITY_DIR = STATE_DIR / "entity_rosters"

# (page_min_score, page_min_answers) defaults per type. Objects are symbolic-gated,
# not score-gated, so their thresholds are 0/1.
THRESHOLDS = {
    "person": (8.0, 2),
    "place": (6.0, 2),
    "period": (6.0, 2),
    "object": (0.0, 1),
}

# Pronouns / fragments / quantifiers the detectors mistake for entities.
JUNK = {
    "You", "Which", "Three", "Some", "Not", "Question", "Being", "Things",
    "Pure", "Growing", "Missed", "Answered", "Dating", "Someone", "Something",
    "Anyone", "Everyone", "Nobody", "Somebody", "Everybody", "Anything",
    "Nothing", "Everything", "Both", "Each", "Either", "Neither", "One", "Two",
    "Many", "Most", "Few", "Several", "Another", "Other", "Others", "Same",
    "Such", "Only", "Once", "Twice", "Yes", "No", "Maybe", "Okay", "Well",
    "Her", "Him", "Them", "It", "Scratch", "The Outside", "An Environment",
    "So Near", "A House Together", "Hugging People",
}

# Generic relationship labels — person-only; never their own page unless mapped.
ROLE_WORDS = {
    "mom", "dad", "mother", "father", "brother", "sister", "friend", "mentor",
    "boss", "wife", "husband", "partner", "son", "daughter", "grandma", "grandpa",
    "grandfather", "grandmother", "uncle", "aunt", "cousin", "teacher", "coach",
    "pastor", "priest", "therapist", "neighbor", "colleague", "roommate",
    "boyfriend", "girlfriend", "fiance", "stepmother", "stepfather", "kids",
    "child", "children", "parent", "parents", "family", "spouse",
}

# What "qualifies" means per type, for the AI prompt.
QUALIFY_RULE = {
    "person": "a real, distinct, identifiable individual (not a pronoun, role, or place)",
    "place": "a real place — a town, region, building, country, or named location",
    "period": "a real life period or era (childhood, high school, your 20s, the mission, etc.)",
    "object": "a SYMBOLIC object that carries real meaning in the author's story — it stands "
              "for something larger (e.g. the cleats he couldn't afford, the stained orange "
              "shorts, the blue Toyota). NOT a mundane prop. Judge by resonance, not frequency",
}


def roster_file(entity_type: str) -> Path:
    return ENTITY_DIR / f"{entity_type}.json"


def _focus_map() -> dict[str, str]:
    """{focus_slug: display_name} for existing Focus categories (to avoid dupes)."""
    md = QUESTIONS_FILE.read_text(encoding="utf-8") if QUESTIONS_FILE.exists() else ""
    result: dict[str, str] = {}
    for cat in parse_categories(md).values():
        if cat.get("group") != "focus":
            continue
        raw = cat.get("name", "")
        name = re.sub(rf"^(Focus|{OLD_FOCUS_TERM})\s*[—–:-]\s*", "", raw, flags=re.IGNORECASE)
        name = re.sub(r"\s*\(.*?\)\s*$", "", name).strip()
        if name:
            result[slugify(name)] = name
    return result


def load_candidates(entity_type: str, min_answers: int = 1) -> list[dict]:
    """Pre-filtered detector candidates for a type. Objects have no detector —
    they're proposed by the AI from answer excerpts instead (see answer_excerpts)."""
    if entity_type == "object":
        return []
    state = load_recommendation_state()
    recs = state.get("recommendations", [])
    candidates = []
    for r in recs:
        if r.get("type") != entity_type:
            continue
        entity = (r.get("entity") or "").strip()
        if not entity or entity in STOPWORDS or entity in JUNK:
            continue
        if len(entity) < 3:
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


def answer_excerpts(limit: int = 60, cap: int = 400) -> list[dict]:
    """Answer bodies (trimmed) for the object pass — the AI reads these to spot
    symbolic objects."""
    out = []
    if not ANSWERS_DIR.exists():
        return out
    for path in sorted(ANSWERS_DIR.glob("*.md"))[:limit]:
        qid = answer_id_from_filename(path)
        if not qid:
            continue
        body = re.sub(r"\s+", " ", answer_body(path.read_text(encoding="utf-8", errors="replace"))).strip()
        if body:
            out.append({"id": qid, "body": body[:cap]})
    return out


def build_prompt(entity_type: str, candidates: list[dict], focus_map: dict[str, str],
                 excerpts: list[dict] | None = None) -> str:
    focuses = ", ".join(f'"{n}" (slug: {s})' for s, n in focus_map.items()) or "(none)"
    plural = {"person": "people", "place": "places", "period": "periods", "object": "objects"}[entity_type]
    lines = [
        f"You are curating a private life-story wiki — specifically the {plural} in it. "
        f"Resolve the material below into a clean roster of distinct {plural}.",
        "",
        f"A {entity_type} QUALIFIES if it is {QUALIFY_RULE[entity_type]}.",
        f"Existing Focus pages (don't duplicate — map to these): {focuses}",
        "",
        "Rules:",
        f"- Merge aliases/variants of the same {entity_type} into ONE entry (e.g. "
        "'20s'/'My 20s'/'Twenties' → one; 'Mit' → 'MIT'). Put variants in `aliases`.",
        f"- Pick the most natural `name` (for objects, a title like 'The Cleats').",
        "- If it clearly refers to an existing Focus above, set `maps_to_focus` to that slug.",
        "- Set `qualifies` false for anything that doesn't meet the bar above (fragments, "
        "pronouns, wrong type, mundane objects). When unsure, set qualifies false.",
        "",
    ]
    if entity_type == "period":
        lines += [
            "- Also set `chrono`: an integer ranking these periods in the order they "
            "occur across a life, EARLIEST = 1 and increasing (e.g. Childhood=1, "
            "My Teens=2, High School=3, College=4, My 20s=5, My 30s=6). Overlapping "
            "stages get an order that reads naturally earliest→latest; use your best "
            "judgment for named eras ('the war years', 'after the divorce').",
            "",
        ]
    if entity_type == "object":
        lines.append("Source answers (find symbolic objects mentioned in these):")
        for e in (excerpts or []):
            lines.append(f"[{e['id']}] {e['body']}")
    else:
        lines.append(f"Candidates ({entity_type} — score / answers):")
        for c in candidates:
            ev = "; ".join(c["evidence"][:2])
            lines.append(f"- {c['entity']} — score {c['score']}, {c['unique_answers']} answers. {ev}")
    chrono_field = ', "chrono": 1' if entity_type == "period" else ""
    lines += [
        "",
        "Respond with ONLY a JSON object, no prose:",
        '{"entities": [{"name": "Name", "aliases": ["Variant"], "qualifies": true, '
        '"maps_to_focus": null' + chrono_field + "}]}",
    ]
    return "\n".join(lines)


def _stats_index(candidates: list[dict]) -> dict[str, dict]:
    return {c["entity"].lower(): c for c in candidates}


def _best_stats(entity: dict, stats: dict[str, dict]) -> tuple[float, int]:
    names = [entity.get("name", "")] + list(entity.get("aliases", []))
    score = answers = 0
    for n in names:
        s = stats.get((n or "").lower())
        if s:
            score = max(score, float(s.get("score", 0.0)))
            answers = max(answers, int(s.get("unique_answers", 0)))
    return float(score), int(answers)


def normalize(entity_type: str, raw_entities: list[dict], candidates: list[dict],
              focus_map: dict[str, str], min_score: float, min_answers: int) -> list[dict]:
    """Validate AI/agent output into roster entries with computed page_eligible."""
    stats = _stats_index(candidates)
    focus_slugs = set(focus_map)
    out = []
    for e in raw_entities:
        name = (e.get("name") or "").strip()
        if not name:
            continue
        slug = slugify(name)
        aliases = [a.strip() for a in e.get("aliases", []) if isinstance(a, str) and a.strip()]
        qualifies = bool(e.get("qualifies", e.get("is_real_person", e.get("is_symbolic", False))))
        maps_to = e.get("maps_to_focus") or None
        if maps_to and maps_to not in focus_slugs:
            maps_to = focus_map.get(slugify(str(maps_to)))
        if maps_to is None and slug in focus_slugs:
            maps_to = slug
        score, answers = _best_stats(e, stats)
        if entity_type == "person":
            # People are the noisiest detections → keep a score/answers bar.
            page_eligible = (qualifies and maps_to is None
                             and score >= min_score and answers >= min_answers)
        else:
            # Places/periods/objects: the AI's judgment is the gate (the noisy
            # detector undercounts real places). The actual "a few mentions" bar
            # is enforced at compile time against real mention counts, and objects
            # graduate on symbolic meaning regardless of frequency.
            page_eligible = qualifies and maps_to is None
        entry = {
            "name": name, "slug": slug, "aliases": aliases,
            "qualifies": qualifies, "maps_to_focus": maps_to,
            "score": round(score, 2), "unique_answers": answers,
            "page_eligible": page_eligible,
        }
        if entity_type == "period":
            # Chronological rank (1 = earliest in life) drives index ordering.
            try:
                entry["chrono"] = int(e.get("chrono"))
            except (TypeError, ValueError):
                entry["chrono"] = None
        out.append(entry)
    return out


def deterministic(entity_type: str, candidates: list[dict], focus_map: dict[str, str],
                  min_score: float, min_answers: int) -> list[dict]:
    """Conservative no-AI roster. No alias merging; objects need AI (returns [])."""
    if entity_type == "object":
        return []
    raw = []
    for c in candidates:
        entity = c["entity"]
        slug = slugify(entity)
        if slug in focus_map:
            raw.append({"name": entity, "qualifies": True, "maps_to_focus": slug})
            continue
        if entity_type == "person" and entity.lower() in ROLE_WORDS:
            raw.append({"name": entity, "qualifies": False, "maps_to_focus": None})
            continue
        looks_named = entity[:1].isupper() and all(p.isalpha() for p in entity.split())
        # places/periods are less strict than person names.
        qualifies = looks_named or entity_type in ("place", "period")
        raw.append({"name": entity, "qualifies": qualifies, "maps_to_focus": None})
    return normalize(entity_type, raw, candidates, focus_map, min_score, min_answers)


def write_roster(entity_type: str, entities: list[dict]) -> None:
    ENTITY_DIR.mkdir(parents=True, exist_ok=True)
    write_json(roster_file(entity_type), {
        "version": 1, "type": entity_type, "resolved_at": now_utc(), "entities": entities,
    })


def load_roster(entity_type: str = "person") -> dict:
    """Load a canonical entity roster."""
    data = read_json(roster_file(entity_type), default=None)
    if data and "entities" in data:
        return data
    return {"version": 1, "type": entity_type, "entities": []}


def _thresholds(entity_type: str, args) -> tuple[float, int]:
    cfg = load_config()
    dscore, dans = THRESHOLDS.get(entity_type, (8.0, 2))
    score = args.min_score if args.min_score is not None else float(
        cfg.get(f"{entity_type}_page_min_score", cfg.get("entity_min_score", dscore)))
    answers = args.min_answers if args.min_answers is not None else int(
        cfg.get(f"{entity_type}_page_min_answers", cfg.get("entity_min_answers", dans)))
    return score, answers


def main() -> int:
    parser = argparse.ArgumentParser(description="Resolve mentioned entities into a canonical roster.")
    parser.add_argument("--type", choices=ENTITY_TYPES, default="person")
    parser.add_argument("--resolve", action="store_true")
    parser.add_argument("--emit-task", metavar="PATH")
    parser.add_argument("--from-response", metavar="PATH")
    parser.add_argument("--show", action="store_true")
    parser.add_argument("--min-score", type=float, default=None)
    parser.add_argument("--min-answers", type=int, default=None)
    parser.add_argument("--model", default=None)
    args = parser.parse_args()
    t = args.type

    if args.show:
        print(json.dumps(load_roster(t), indent=2, ensure_ascii=False))
        return 0

    min_score, min_answers = _thresholds(t, args)
    focus_map = _focus_map()
    candidates = load_candidates(t, min_answers=1)
    excerpts = answer_excerpts() if t == "object" else None

    if args.emit_task:
        Path(args.emit_task).write_text(json.dumps({
            "type": t,
            "prompt": build_prompt(t, candidates, focus_map, excerpts),
            "candidates": candidates,
            "focus_map": focus_map,
            "min_score": min_score, "min_answers": min_answers,
            "response_format": {"entities": [dict({"name": "", "aliases": [], "qualifies": True,
                                              "maps_to_focus": None},
                                             **({"chrono": 1} if t == "period" else {}))]},
        }, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        n = len(excerpts or candidates)
        print(f"✓ Emitted {t} roster task ({n} items) to {args.emit_task}")
        print(f"  Write the roster JSON, then: python3 system/entity_roster.py --type {t} --from-response <file>")
        return 0

    if args.from_response:
        from research_expand import parse_ai_json
        data = parse_ai_json(Path(args.from_response).read_text(encoding="utf-8"))
        ents = normalize(t, data.get("entities", []), candidates, focus_map, min_score, min_answers)
        write_roster(t, ents)
        elig = sum(1 for e in ents if e["page_eligible"])
        print(f"✓ {t} roster written: {len(ents)} entities, {elig} page-eligible → {roster_file(t).name}")
        return 0

    from research_expand import DEFAULT_MODEL, call_ai, parse_ai_json
    try:
        data = parse_ai_json(call_ai(build_prompt(t, candidates, focus_map, excerpts),
                                     args.model or DEFAULT_MODEL))
        ents = normalize(t, data.get("entities", []), candidates, focus_map, min_score, min_answers)
        source = "AI"
    except Exception as exc:  # noqa: BLE001
        print(f"  ⚠ AI resolution unavailable ({exc}); using deterministic fallback")
        ents = deterministic(t, candidates, focus_map, min_score, min_answers)
        source = "deterministic"
    write_roster(t, ents)
    elig = sum(1 for e in ents if e["page_eligible"])
    print(f"✓ {t} roster via {source}: {len(ents)} entities, {elig} page-eligible → {roster_file(t).name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
