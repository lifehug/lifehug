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

from ai_provider import failure_metadata
from lifehug_core import (
    ANSWERS_DIR,
    ENTITY_ROSTERS_DIR,
    QUESTIONS_FILE,
    answer_body,
    answer_id_from_filename,
    load_config,
    normalized_focus_key,
    now_utc,
    parse_categories,
    read_json,
    slugify,
    write_json,
    write_text,
)
from recommend_focuses import STOPWORDS, OLD_FOCUS_TERM, load_recommendation_state

ENTITY_TYPES = ("person", "place", "period", "object", "theme")
ENTITY_DIR = ENTITY_ROSTERS_DIR

# (page_min_score, page_min_answers) defaults per type. Objects are symbolic-gated,
# not score-gated, so their thresholds are 0/1.
THRESHOLDS = {
    "person": (8.0, 2),
    "place": (6.0, 2),
    "period": (6.0, 2),
    "object": (0.0, 1),
    "theme": (6.0, 2),
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
    "theme": "a recurring THEME of the author's life — a subject or tension the story keeps "
             "returning to (parenting, faith, money, urgency). Merge synonyms and levels of "
             "abstraction (fatherhood/raising kids → parenting); map duplicates of existing "
             "theme pages to them. NOT a person, place, event, or one-off topic",
}


def roster_file(entity_type: str) -> Path:
    return ENTITY_DIR / f"{entity_type}.json"


def _known_theme_names() -> set[str]:
    """Names the deterministic theme fallback may accept (v97): the classifier
    taxonomy plus existing theme page slugs. Lazy imports keep module load light."""
    from classify_story import THEME_TAXONOMY  # noqa: PLC0415
    from lifehug_core import WIKI_DIR  # noqa: PLC0415

    names = {t.lower() for t in THEME_TAXONOMY}
    themes_dir = WIKI_DIR / "themes"
    if themes_dir.exists():
        for page in themes_dir.glob("*.md"):
            names.add(page.stem.replace("-", " ").lower())
            names.add(page.stem.lower())
    return names


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
        if len(entity) < 2:  # allow initials-style names (AJ, JT); single chars still out
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


def _answer_sort_key(path: Path) -> tuple:
    qid = answer_id_from_filename(path) or path.stem
    match = re.match(r"^([A-Z]+)(\d+)([a-z]*)$", qid)
    if match:
        prefix, number, suffix = match.groups()
        return (prefix, int(number), suffix, path.name)
    return (qid, path.name)


def _evenly_spaced_indices(total: int, count: int) -> list[int]:
    if total <= 0 or count <= 0:
        return []
    if count >= total:
        return list(range(total))
    if count == 1:
        return [0]
    return sorted({round(i * (total - 1) / (count - 1)) for i in range(count)})


def _object_search_terms(roster: dict) -> list[str]:
    terms: set[str] = set()
    for ent in (roster or {}).get("entities", []):
        raw_terms = [ent.get("name", ""), *ent.get("aliases", [])]
        for raw in raw_terms:
            term = str(raw or "").strip().lower()
            if len(term) < 3:
                continue
            terms.add(term)
            if term.startswith("the "):
                terms.add(term[4:])
    return sorted(terms, key=len, reverse=True)


def _select_excerpt_records(records: list[dict], limit: int) -> list[dict]:
    if limit <= 0:
        return []
    if len(records) <= limit:
        return records

    selected: set[int] = set()

    def add(indices, quota: int) -> None:
        added = 0
        for idx in indices:
            if len(selected) >= limit or added >= quota:
                break
            if idx < 0 or idx >= len(records):
                continue
            before = len(selected)
            selected.add(idx)
            if len(selected) > before:
                added += 1

    # Keep broad archive coverage first, so late answers cannot disappear just
    # because early categories are dense.
    add(_evenly_spaced_indices(len(records), max(1, limit // 2)), max(1, limit // 2))

    terms = _object_search_terms(load_roster("object"))
    if terms:
        linked = [
            idx for idx, rec in enumerate(records)
            if any(term in rec["body"].lower() for term in terms)
        ]
        add(linked, max(1, limit // 5))

    long_answers = sorted(range(len(records)), key=lambda idx: len(records[idx]["body"]), reverse=True)
    add(long_answers, max(1, limit // 5))

    recent_answers = sorted(
        range(len(records)),
        key=lambda idx: records[idx]["path"].stat().st_mtime,
        reverse=True,
    )
    add(recent_answers, max(1, limit // 5))

    if len(selected) < limit:
        add(_evenly_spaced_indices(len(records), limit), limit - len(selected))
    if len(selected) < limit:
        add(range(len(records)), limit - len(selected))

    return [records[idx] for idx in sorted(selected)]


def answer_excerpts(limit: int = 60, cap: int = 400) -> list[dict]:
    """Answer bodies (trimmed) for the object pass — the AI reads these to spot
    symbolic objects."""
    if not ANSWERS_DIR.exists():
        return []
    records = []
    for path in sorted(ANSWERS_DIR.glob("*.md"), key=_answer_sort_key):
        qid = answer_id_from_filename(path)
        if not qid:
            continue
        body = re.sub(r"\s+", " ", answer_body(path.read_text(encoding="utf-8", errors="replace"))).strip()
        if body:
            records.append({"path": path, "id": qid, "body": body})
    return [
        {"id": rec["id"], "body": rec["body"][:cap]}
        for rec in _select_excerpt_records(records, limit)
    ]


def _entity_keys(entity: dict) -> set[str]:
    """Match-key variants for one roster entity (name + slug + aliases).

    Delegates the actual lowercase/slugify/"the "-strip logic to
    lifehug_core.normalized_focus_key — the ONE authoritative definition
    (recurring-defect doctrine) also used by every Focus-creation door in
    roadmap.py and by recommend_focuses.py's roster fold, so this module
    never re-derives its own copy of that normalization."""
    keys: set[str] = set()
    raw_values = [
        entity.get("name", ""),
        entity.get("slug", ""),
        *entity.get("aliases", []),
    ]
    for raw in raw_values:
        value = str(raw or "").strip().lower()
        if not value:
            continue
        keys.add(value)
        keys.add(slugify(value))
        keys.add(normalized_focus_key(value))
        if value.startswith("the "):
            keys.add(value[4:])
    return {k for k in keys if k}


def carry_forward_objects(entities: list[dict], previous_roster: dict | None) -> tuple[list[dict], int]:
    """Keep known symbolic objects unless a new response names/replaces them."""
    previous = (previous_roster or {}).get("entities") or []
    if not previous:
        return entities, 0

    merged = [dict(e) for e in entities]
    current_keys: set[str] = set()
    for ent in merged:
        current_keys.update(_entity_keys(ent))

    preserved = 0
    for ent in previous:
        keys = _entity_keys(ent)
        if keys & current_keys:
            continue
        merged.append(dict(ent))
        current_keys.update(keys)
        preserved += 1
    return merged, preserved


def preserve_existing_object_roster(entity_type: str, entities: list[dict],
                                    previous_roster: dict | None,
                                    force_empty: bool = False) -> tuple[list[dict], bool]:
    if entity_type != "object" or entities or force_empty:
        return entities, False
    previous_entities = (previous_roster or {}).get("entities") or []
    if not previous_entities:
        return entities, False
    return [dict(e) for e in previous_entities], True


def apply_previous_decisions(raw_entities: list[dict], previous_roster: dict | None) -> tuple[list[dict], int]:
    """Safety net: fold raw AI output back onto the previous roster's settled
    identity decisions BEFORE normalize().

    Any raw entry whose name or alias matches a previous entry (case-insensitive,
    including slug and "the "-stripped forms via _entity_keys) is folded into that
    previous entry's canonical name — so slugs stay stable even if the AI re-splits
    a merged entity ('Grandma Betty Jo' → 'Grandma' + 'Betty Jo'). Two raw entries
    hitting the same previous entry collapse into one, with aliases unioned.
    `qualifies` is the OR of the folded raw entries (the AI can still demote an
    entity by marking every variant unqualified); `maps_to_focus` falls back to
    the previous value when the raw output drops it.

    Exception — role-word promotion: when the previous canonical is a bare
    role word (Brother, Friend, Son) and the raw entry supplies a proper name
    for the same individual, the proper name WINS as canonical and the role
    word demotes to an alias. A generic role word is a placeholder, not a
    settled identity — locking it in forever would keep a real person
    (e.g. AJ) buried under "Brother" no matter how much source material
    names them. The slug changes with the name; cleanup_orphan_entity_pages
    removes any stale role-word page on the next compile.

    Tradeoff: an intentional AI re-split of a previously merged entity is
    overridden. Splitting a wrongly merged entity requires hand-editing
    state/entity_rosters/<type>.json (remove the merged entry, then re-resolve).
    """
    previous = (previous_roster or {}).get("entities") or []
    if not previous or not raw_entities:
        return list(raw_entities), 0

    key_to_prev: dict[str, dict] = {}
    for prev in previous:
        for key in _entity_keys(prev):
            key_to_prev.setdefault(key, prev)

    def _match(entry: dict) -> dict | None:
        for key in _entity_keys(entry):
            prev = key_to_prev.get(key)
            if prev:
                return prev
        return None

    out: list[dict] = []
    slots: dict[str, dict] = {}  # previous slug -> folded entry
    forced = 0
    for e in raw_entities:
        name = (e.get("name") or "").strip()
        if not name:
            out.append(dict(e))
            continue
        prev = _match(e)
        if prev is None:
            out.append(dict(e))
            continue
        prev_name = (prev.get("name") or "").strip()
        # Role-word promotion: a bare role-word canonical yields to a proper name.
        promoted = (
            prev_name.lower() in ROLE_WORDS
            and name.lower() not in ROLE_WORDS
        )
        canonical = name if promoted else (prev_name or name)
        prev_slug = prev.get("slug") or slugify(prev_name or canonical)
        slot = slots.get(prev_slug)
        if slot is None:
            slot = dict(e)
            slot["name"] = canonical
            slots[prev_slug] = slot
            out.append(slot)
        else:
            # A second raw entry collapsed into an already-folded slot.
            if promoted and str(slot.get("name", "")).strip().lower() in ROLE_WORDS:
                slot["name"] = canonical  # the proper name upgrades the slot too
            slot["qualifies"] = bool(slot.get("qualifies")) or bool(e.get("qualifies"))
            if not slot.get("maps_to_focus"):
                slot["maps_to_focus"] = e.get("maps_to_focus") or None
            forced += 1
        canonical = str(slot.get("name") or canonical)
        # Union aliases: previous name/aliases + raw name/aliases, minus the
        # canonical name (a demoted role word survives here as an alias).
        seen = {canonical.strip().lower()}
        merged_aliases: list[str] = []
        for alias in [*slot.get("aliases", []), *prev.get("aliases", []), prev_name, name, *e.get("aliases", [])]:
            alias = str(alias or "").strip()
            if not alias or alias.lower() in seen:
                continue
            seen.add(alias.lower())
            merged_aliases.append(alias)
        slot["aliases"] = merged_aliases
        if not slot.get("maps_to_focus"):
            slot["maps_to_focus"] = prev.get("maps_to_focus") or None
        # Themes: curated keywords are settled work — carry them forward when
        # a refresh response drops them (harmless no-op for other types).
        if not slot.get("keywords") and prev.get("keywords"):
            slot["keywords"] = list(prev["keywords"])
        if name.strip().lower() != canonical.strip().lower():
            forced += 1
    return out, forced


def build_prompt(entity_type: str, candidates: list[dict], focus_map: dict[str, str],
                 excerpts: list[dict] | None = None,
                 previous_roster: dict | None = None) -> str:
    focuses = ", ".join(f'"{n}" (slug: {s})' for s, n in focus_map.items()) or "(none)"
    plural = {"person": "people", "place": "places", "period": "periods",
              "object": "objects", "theme": "themes"}[entity_type]
    lines = [
        f"You are curating a private life-story wiki — specifically the {plural} in it. "
        f"Resolve the material below into a clean roster of distinct {plural}.",
        "",
        f"A {entity_type} QUALIFIES if it is {QUALIFY_RULE[entity_type]}.",
        f"Existing Focus pages (don't duplicate — map to these): {focuses}",
    ]
    previous_entities = (previous_roster or {}).get("entities") or []
    if previous_entities:
        lines += [
            "",
            f"Previous roster — last run's settled decisions for these same {plural}:",
        ]
        for prev in previous_entities:
            aliases = ", ".join(prev.get("aliases") or []) or "(none)"
            line = f'- "{prev.get("name", "")}" (slug: {prev.get("slug", "")}) — aliases: {aliases}'
            if prev.get("maps_to_focus"):
                line += f'; maps_to_focus: {prev["maps_to_focus"]}'
            lines.append(line)
        lines += [
            "These prior merges and mappings are settled identity decisions. Keep each "
            "previous entry as ONE entry, reusing its exact `name` and keeping (or "
            f"extending) its aliases and `maps_to_focus`, unless the material below clearly "
            f"shows two different {plural} were wrongly merged. Never re-split one "
            f"{entity_type} into multiple entries and never rename a previous entry to a "
            "different `name` — with ONE exception: if a previous entry's `name` is a bare "
            "kinship/role word (Brother, Friend, Son) and the material supplies that "
            "person's proper name, use the proper name as `name` and keep the role word "
            "in `aliases`. A role word is a placeholder, never a settled identity.",
        ]
    lines += [
        "",
        "Rules:",
        f"- Merge aliases/variants of the same {entity_type} into ONE entry (e.g. "
        "'20s'/'My 20s'/'Twenties' → one; 'Mit' → 'MIT'). Put variants in `aliases`.",
        f"- Pick the most natural `name` (for objects, a title like 'The Cleats').",
        "- If it clearly refers to an existing Focus above, set `maps_to_focus` to that slug.",
        "- Set `qualifies` false for anything that doesn't meet the bar above (fragments, "
        "pronouns, wrong type, mundane objects). When unsure, set qualifies false.",
    ]
    if entity_type == "person":
        lines += [
            "- People are often referred to BOTH by a kinship/role word (Mom, Dad, Grandma, "
            "Coach, Wife) and by a proper name. If a role word and a proper name appear in "
            "overlapping answers and plausibly refer to the same individual (e.g. 'Grandma' "
            "and 'Betty Jo'), output ONE entry — the fullest proper name as `name` (even "
            "when the previous roster used the bare role word), the role word and other "
            "variants in `aliases`. Never emit both a role-word entry and a proper-name "
            "entry for the same individual.",
        ]
    lines += [
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
    if entity_type == "theme":
        lines += [
            "- Also set `keywords`: 4-10 lowercase surface phrases the wiki compiler will "
            "match against source text to attach material to this theme's page (e.g. "
            'parenting → ["parenting", "as a father", "my kids", "raise the kids", '
            '"discipline"]). Include the theme name itself; prefer phrases the author '
            "actually uses in the material.",
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
    keywords_field = ', "keywords": ["phrase"]' if entity_type == "theme" else ""
    lines += [
        "",
        "Respond with ONLY a JSON object, no prose:",
        '{"entities": [{"name": "Name", "aliases": ["Variant"], "qualifies": true, '
        '"maps_to_focus": null' + chrono_field + keywords_field + "}]}",
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
        if entity_type == "theme":
            # Surface vocabulary the compiler matches sources with (v97) —
            # the dynamic replacement for a static THEME_KEYWORDS row.
            keywords = [str(k).strip().lower() for k in (e.get("keywords") or [])
                        if isinstance(k, str) and str(k).strip()]
            if name.lower() not in keywords:
                keywords.insert(0, name.lower())
            entry["keywords"] = keywords
        out.append(entry)
    return out


def deterministic(entity_type: str, candidates: list[dict], focus_map: dict[str, str],
                  min_score: float, min_answers: int,
                  previous_roster: dict | None = None) -> list[dict]:
    """Conservative no-AI roster. No alias merging beyond previous decisions;
    objects need AI (returns [])."""
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
        if entity_type == "theme":
            # Conservative keyless fallback: only names already vouched for by
            # the classifier taxonomy or an existing theme page qualify; the
            # AI path is what curates keywords and merges abstraction levels.
            qualifies = entity.lower() in _known_theme_names()
            raw.append({"name": entity, "qualifies": qualifies, "maps_to_focus": None,
                        "keywords": [entity.lower()]})
            continue
        looks_named = entity[:1].isupper() and all(p.isalpha() for p in entity.split())
        # places/periods are less strict than person names.
        qualifies = looks_named or entity_type in ("place", "period")
        raw.append({"name": entity, "qualifies": qualifies, "maps_to_focus": None})
    raw, _ = apply_previous_decisions(raw, previous_roster)
    return normalize(entity_type, raw, candidates, focus_map, min_score, min_answers)


def write_roster(entity_type: str, entities: list[dict], *, source: str | None = None,
                 sampled_answer_ids: list[str] | None = None,
                 preserved_count: int = 0,
                 failure_reason: str | None = None) -> None:
    ENTITY_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": 1, "type": entity_type, "resolved_at": now_utc(), "entities": entities,
    }
    if source:
        payload["source"] = source
    if sampled_answer_ids is not None:
        payload["sampled_answer_ids"] = sampled_answer_ids
    if preserved_count:
        payload["preserved_count"] = preserved_count
    if failure_reason:
        payload["failure_reason"] = failure_reason
    write_json(roster_file(entity_type), payload)


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
    parser.add_argument("--force-empty", action="store_true",
                        help="Allow an empty object roster to overwrite an existing one.")
    args = parser.parse_args()
    t = args.type

    if args.show:
        print(json.dumps(load_roster(t), indent=2, ensure_ascii=False))
        return 0

    min_score, min_answers = _thresholds(t, args)
    focus_map = _focus_map()
    candidates = load_candidates(t, min_answers=1)
    excerpts = answer_excerpts() if t == "object" else None
    sampled_answer_ids = [e["id"] for e in excerpts or []] if t == "object" else None
    previous_roster = load_roster(t)

    if args.emit_task:
        write_text(Path(args.emit_task), json.dumps({
            "type": t,
            "prompt": build_prompt(t, candidates, focus_map, excerpts, previous_roster),
            "candidates": candidates,
            "previous_roster": previous_roster.get("entities", []),
            "sampled_answer_ids": sampled_answer_ids,
            "focus_map": focus_map,
            "min_score": min_score, "min_answers": min_answers,
            "response_format": {"entities": [dict({"name": "", "aliases": [], "qualifies": True,
                                              "maps_to_focus": None},
                                             **({"chrono": 1} if t == "period" else {}),
                                             **({"keywords": ["phrase"]} if t == "theme" else {}))]},
        }, indent=2, ensure_ascii=False) + "\n")
        n = len(excerpts or candidates)
        print(f"✓ Emitted {t} roster task ({n} items) to {args.emit_task}")
        print(f"  Write the roster JSON, then: python3 system/entity_roster.py --type {t} --from-response <file>")
        return 0

    if args.from_response:
        from research_expand import parse_ai_json
        data = parse_ai_json(Path(args.from_response).read_text(encoding="utf-8"))
        raw, forced = apply_previous_decisions(data.get("entities", []), previous_roster)
        if forced:
            print(f"  ↺ enforced {forced} previous roster decision(s)")
        ents = normalize(t, raw, candidates, focus_map, min_score, min_answers)
        preserved = 0
        if t == "object" and not args.force_empty:
            ents, preserved = carry_forward_objects(ents, previous_roster)
        ents, was_preserved = preserve_existing_object_roster(t, ents, previous_roster, args.force_empty)
        if was_preserved:
            print("  ⚠ Empty object response; preserving existing object roster")
            return 0
        write_roster(t, ents, source="response", sampled_answer_ids=sampled_answer_ids,
                     preserved_count=preserved)
        elig = sum(1 for e in ents if e["page_eligible"])
        extra = f", preserved {preserved}" if preserved else ""
        print(f"✓ {t} roster written: {len(ents)} entities, {elig} page-eligible{extra} → {roster_file(t).name}")
        return 0

    from ai_provider import call_ai
    from research_expand import DEFAULT_MODEL, parse_ai_json
    preserved = 0
    failure_reason = None
    try:
        data = parse_ai_json(call_ai(build_prompt(t, candidates, focus_map, excerpts, previous_roster),
                                     args.model or DEFAULT_MODEL))
        raw, forced = apply_previous_decisions(data.get("entities", []), previous_roster)
        if forced:
            print(f"  ↺ enforced {forced} previous roster decision(s)")
        ents = normalize(t, raw, candidates, focus_map, min_score, min_answers)
        if t == "object" and not args.force_empty:
            ents, preserved = carry_forward_objects(ents, previous_roster)
        source = "AI"
    except Exception as exc:  # noqa: BLE001
        safe_failure = failure_metadata("entity-roster", exc, provider="ai")
        print(f"  ⚠ AI resolution unavailable ({safe_failure}); using deterministic fallback")
        ents = deterministic(t, candidates, focus_map, min_score, min_answers, previous_roster)
        source = "deterministic"
        failure_reason = safe_failure

    ents, was_preserved = preserve_existing_object_roster(t, ents, previous_roster, args.force_empty)
    if was_preserved:
        elig = sum(1 for e in ents if e["page_eligible"])
        print(f"✓ {t} roster preserved: {len(ents)} existing entities, {elig} page-eligible → {roster_file(t).name}")
        return 0

    write_roster(t, ents, source=source.lower(), sampled_answer_ids=sampled_answer_ids,
                 preserved_count=preserved, failure_reason=failure_reason)
    elig = sum(1 for e in ents if e["page_eligible"])
    extra = f", preserved {preserved}" if preserved else ""
    print(f"✓ {t} roster via {source}: {len(ents)} entities, {elig} page-eligible{extra} → {roster_file(t).name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
