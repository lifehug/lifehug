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

import chronology
import relation_words
import roster_relations
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
from vault_paths import vault_data_path
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


#: entity-identity-context (v190, Design §E): the settled facts a roster entry
#: can carry that are NOT re-derivable from a refresh — an owner verdict
#: (ADR 0013) and the identity facts the owner supplies in the Play
#: conversation (`entity-verdict --relationship/--living|--not-living`, and
#: since v217 `--born/--died`). An entry carrying any of them survives a
#: refresh that drops or contradicts it, exactly as an owner_verdict alone did
#: before v190. `maps_to_focus` is deliberately NOT here: a merge's durability
#: lives on the SURVIVOR (the loser's names are unioned into the target's
#: aliases, which `_entity_keys`/`apply_previous_decisions` then fold by
#: forever), not on the loser's own row.
#:
#: v217 (person dates) adds `born` and `died`. They belong here for exactly
#: the reason the tuple exists: a birth or death date is stated ONCE — by the
#: person, or by a family/losses landmark — and is never re-derivable from the
#: entity-candidate refresh, whose whole input is mention statistics. Omitting
#: them would mean a roster refresh silently drops the most common datable
#: facts in a life story.
_SETTLED_IDENTITY_FIELDS = ("relationship", "living", "born", "died", *roster_relations.PLACE_IDENTITY_FIELDS,
                            # v358: the owner's answer to the relation-word card.
                            relation_words.RELATION_GENDER_FIELD,
                            relation_words.RELATION_GENDER_BASIS_FIELD,
                            # v360, owner 2026-09-25 (the person form): whose side
                            # a grandparent is on, and the word he calls them.
                            "grandparent_side", "relation_word")
_SETTLED_PLACE = object()

#: The two date-shaped settled fields, as a subset of the tuple above. Named
#: once so the store's precedence rule (`entity_verdict._preferred_date`) and
#: the anchor derivation both read the same list rather than re-typing it.
PERSON_DATE_FIELDS = ("born", "died")


def _has_settled_identity(entry: dict) -> bool:
    """True when this entry carries an owner decision a refresh must not lose."""
    if entry.get("owner_verdict"):
        return True
    return any(entry.get(field) is not None for field in _SETTLED_IDENTITY_FIELDS)


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

    Owner verdicts (contract: entity-owner-verdicts, Scope 1) are a
    stronger settled fact than any of the above: a previous entry's
    `owner_verdict` ALWAYS carries onto its folded slot below, overriding
    anything the raw entry says (or drops). A previous entry carrying an
    `owner_verdict` also survives even when NO raw entry matches it at all
    (the AI's candidate list can drop an owner-graduated or owner-vetoed
    entity entirely — its low/zero score may not even reach the prompt) —
    the roster is the settled-identity store for entities; a verdict on it
    is never contingent on this refresh's raw output.
    """
    # Model output cannot mint identity metadata or the in-process provenance
    # marker. Only this function's previous authoritative snapshot can do so.
    raw_entities = [{k: v for k, v in e.items()
                     if k not in (*roster_relations.PLACE_IDENTITY_FIELDS, "_settled_place")}
                    for e in raw_entities]
    previous = (previous_roster or {}).get("entities") or []
    if not previous:
        return list(raw_entities), 0
    place_refs = roster_relations.settled_place_refs(previous_roster)

    def protected_place(entry: dict) -> bool:
        return roster_relations.entity_ref("place", entry) in place_refs

    def preserved(entry: dict) -> dict:
        # This transient marker preserves even a containing city's authored
        # slug through normalize; it is never written into roster state.
        return {**entry, **({"_settled_place": _SETTLED_PLACE} if protected_place(entry) else {})}

    if not raw_entities:
        # Nothing to fold onto, but a settled owner_verdict must still
        # survive an empty refresh (e.g. an empty/failed candidate pass).
        survivors = [preserved(p) for p in previous if _has_settled_identity(p) or protected_place(p)]
        return survivors, len(survivors)

    key_to_prev: dict[str, dict] = {}
    for prev in previous:
        for key in _entity_keys(prev):
            key_to_prev.setdefault(key, prev)

    def _match(entry: dict) -> tuple[dict | None, bool]:
        candidates = [p for p in previous if _entity_keys(entry) & _entity_keys(p)]
        if any(protected_place(p) for p in candidates):
            exact = [p for p in candidates
                     if _entity_keys({k: entry[k] for k in ("name", "slug") if k in entry})
                     & _entity_keys({k: p[k] for k in ("name", "slug") if k in p})]
            if len(exact) == 1:
                return exact[0], False
            if len(candidates) == 1:
                return candidates[0], False
            return None, True
        for key in _entity_keys(entry):
            prev = key_to_prev.get(key)
            if prev:
                return prev, False
        return None, False

    out: list[dict] = []
    slots: dict[str, dict] = {}  # previous slug -> folded entry
    forced = 0
    for e in raw_entities:
        name = (e.get("name") or "").strip()
        if not name:
            out.append(dict(e))
            continue
        prev, ambiguous = _match(e)
        if ambiguous:
            # A shared alias is not permission to select the first house (or
            # merge a house into its city). All prior identities survive below.
            forced += 1
            continue
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
        if protected_place(prev):
            if slot is None:
                slot = preserved(prev)
                slots[prev_slug] = slot
                out.append(slot)
            forced += 1
            continue
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
        # entity-identity-context (v190): the owner's identity facts are
        # settled work too — carry them forward when a refresh response
        # drops them (the exact `keywords` recipe one line above).
        for field in _SETTLED_IDENTITY_FIELDS:
            if slot.get(field) is None and prev.get(field) is not None:
                slot[field] = prev[field]
        # An owner_verdict on the previous entry is a settled fact — it
        # always wins, whatever this refresh's raw entry carries or omits.
        if prev.get("owner_verdict"):
            slot["owner_verdict"] = prev["owner_verdict"]
        if name.strip().lower() != canonical.strip().lower():
            forced += 1

    # A previous entry carrying an owner_verdict must survive even when no
    # raw entry in THIS refresh matched it at all.
    for prev in previous:
        if not (_has_settled_identity(prev) or protected_place(prev)):
            continue
        prev_slug = prev.get("slug") or slugify(prev.get("name") or "")
        if prev_slug in slots:
            continue  # already folded above
        out.append(preserved(prev))
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
        "- Pick the most natural `name` (for objects, a title like 'The Cleats').",
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


def base_page_eligible(entity_type: str, qualifies: bool, maps_to: str | None,
                       score: float, answers: int, min_score: float, min_answers: int) -> bool:
    """The AI/deterministic-derived eligibility rule, BEFORE any owner_verdict
    override (contract: entity-owner-verdicts, Scope 1). Single authoritative
    definition (recurring-defect doctrine) — `normalize()` and
    `entity_verdict.py`'s `clear` both call this rather than each re-deriving
    the per-type formula."""
    if entity_type == "person":
        # People are the noisiest detections → keep a score/answers bar.
        return qualifies and maps_to is None and score >= min_score and answers >= min_answers
    # Places/periods/objects/themes: the AI's judgment is the gate (the noisy
    # detector undercounts real places). The actual "a few mentions" bar is
    # enforced at compile time against real mention counts, and objects
    # graduate on symbolic meaning regardless of frequency.
    return qualifies and maps_to is None


def apply_owner_verdict(entity_type: str, entry: dict) -> dict:
    """Enforce Scope 1's settled-decision semantics on ONE normalized roster
    entry, in place, AFTER the base eligibility above is computed. An
    `owner_verdict` is a permanent fact the AI can never remove or override:

      - `graduate`: `page_eligible` forced True — UNLESS the entity is
        mapped to a Focus (`maps_to_focus` wins; `entity_verdict.py` refuses
        to SET graduate on an already-mapped entity, and this guard also
        holds continuously if a later refresh maps an already-graduated
        entity — mapped always wins).
      - `never`: `page_eligible` forced False, permanently. Identity and
        alias folding continue unaffected — suppression is about pages, not
        identity (Scope 1).

    A verdict absent or unrecognized is a no-op — `entry` is returned
    unchanged in that case."""
    verdict = entry.get("owner_verdict")
    if verdict == "never":
        entry["page_eligible"] = False
    elif verdict == "graduate" and entry.get("maps_to_focus") is None:
        entry["page_eligible"] = True
    return entry


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
        page_eligible = base_page_eligible(entity_type, qualifies, maps_to, score, answers,
                                           min_score, min_answers)
        entry = {
            "name": name, "slug": slug, "aliases": aliases,
            "qualifies": qualifies, "maps_to_focus": maps_to,
            "score": round(score, 2), "unique_answers": answers,
            "page_eligible": page_eligible,
        }
        if entity_type == "place" and e.get("_settled_place") is _SETTLED_PLACE:
            entry["slug"] = e["slug"]
            for field in roster_relations.PLACE_IDENTITY_FIELDS:
                if field in e:
                    entry[field] = e[field]
        # entity-identity-context (v190, Design §E): identity facts the owner
        # supplied through `entity-verdict` survive normalization. Validated
        # here only for SHAPE — the closed relationship vocabulary belongs to
        # `focus_candidate.FOCUS_RELATIONSHIPS` and is enforced by the verb
        # before anything reaches the roster.
        relationship = e.get("relationship")
        if isinstance(relationship, str) and relationship.strip():
            entry["relationship"] = relationship.strip()
        living = e.get("living")
        if isinstance(living, bool):
            entry["living"] = living
        # v217 (person dates): `born`/`died` are settled identity facts too,
        # normalized through the ONE date definition every landmark date
        # already uses (`chronology.normalized_date`) so a record that arrives
        # with only `best` still carries real bounds and can date anything.
        for date_field in PERSON_DATE_FIELDS:
            record = chronology.normalized_date(e.get(date_field))
            if record is not None:
                entry[date_field] = record
        owner_verdict = e.get("owner_verdict")
        if owner_verdict in ("graduate", "never"):
            entry["owner_verdict"] = owner_verdict
            apply_owner_verdict(entity_type, entry)
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


def load_roster(entity_type: str = "person", *, vault_root: object = None) -> dict:
    """Load a canonical entity roster."""
    path = roster_file(entity_type)
    if vault_root is not None:
        path = vault_data_path("entity_rosters", vault_root=vault_root) / f"{entity_type}.json"
    data = read_json(path, default=None)
    if data and "entities" in data:
        return data
    return {"version": 1, "type": entity_type, "entities": []}


# --------------------------------------------------------------------------
# v360 (owner, 2026-09-25) — a `children`/`family` LANDMARK ENTRY introduces
# a person too, not just a claim's own words
# --------------------------------------------------------------------------
#
# THE DEFECT. The owner's vault carries four `children` landmark entries with
# real full names and dates — Charlee Joy Taylor, Dottie Ovelle Taylor, Harvey
# Rex Taylor, James Everett Taylor, all filed 2026-08-27 — plus a fifth, EMPTY
# `children` entry for Charlee filed overnight (2026-09-25T08:20:58Z). Two of
# the four — Charlee and Dottie — had no roster row at all. v344's
# `ensure_introduced_relatives` only reads the CLAIM substrate
# (`roster_relations.relationship_introduction_batch`) for a relationship
# PHRASE beside a name in the owner's own words, and no source in this vault
# happens to carry Charlee's or Dottie's name inside the SAME clause as a
# relationship word — the closest one, "I have my beautiful daughter Charlee"
# (`answer:E27`), produced no dated claim at all, so its source never entered
# the batch. The `children` landmark domain names them anyway, unambiguously
# (the domain itself IS the relation), and the vault had already filed it.
# This reads that.
#
# THE RULE. A `children` landmark entry with a full name earns "child" — the
# same relationship `harvey` and `james-everett-taylor` already carry under
# `source: "landmark:family"`; a `family` landmark entry keeps using its own
# `relation` field (already the roster's vocabulary —
# `roster_relations.landmark_recorded_relations`'s reading of the same field,
# used today only to REFUSE a contradiction, never to introduce a row). Both
# go through the SAME writer as v344, `entity_verdict.apply_verdict(...,
# ensure=True)` — never a parallel store.
#
# THE SAME GUARDS. Never from a first name alone (v202/v347's own principle,
# applied here): the name must be at least two capitalised, alphabetic
# tokens, so a bare "Harvey" landmark entry is never enough by itself. Never
# a second row for somebody the roster already answers to: a name already
# known by its own spelling, or one sharing its FIRST token with an existing
# person's name or alias ("Harvey Rex Taylor" shares "harvey" with the row
# `harvey` already on the roster, so it is read as the SAME person and left
# alone, never a duplicate) is skipped. No compounds, no "my dad's dad"
# confusion: the domain names one relation directly, so there is no
# relationship WORD to parse and nothing to misread.

CHILDREN_RELATION_DOMAIN = "children"
LANDMARK_RELATION_DOMAINS = (roster_relations.FAMILY_RELATION_DOMAIN, CHILDREN_RELATION_DOMAIN)


def _looks_like_a_full_name(text: str) -> bool:
    """At least two capitalised, alphabetic tokens — never a first name alone."""
    parts = text.split()
    return len(parts) >= 2 and all(
        p[:1].isupper() and p.replace("'", "").replace("-", "").isalpha() for p in parts)


def _first_token(text: str) -> str:
    parts = text.split()
    return parts[0].casefold() if parts else ""


def _roster_first_tokens(roster: object) -> set[str]:
    """Every first token any existing person row already answers to, by name
    or by alias — the guard that keeps "Harvey Rex Taylor" from becoming a
    second row beside the roster's existing "Harvey"."""
    out: set[str] = set()
    for entity in roster_relations.roster_entities(roster):
        for spelling in (entity.get("name"), *(entity.get("aliases") or ())):
            body = roster_relations.collapsed_text_of(spelling)
            if body:
                out.add(_first_token(body))
    out.discard("")
    return out


def landmark_relationship_introductions(landmark_entries: object, *,
                                        roster: object = ()) -> tuple[dict, ...]:
    """Every person a `children`/`family` LANDMARK ENTRY introduces and the
    roster lacks, one row per slug — the landmark-sourced half of
    :func:`ensure_introduced_relatives`. Pure: entries and a roster snapshot
    in, rows out. Deterministic (sorted by slug), so two runs propose the
    same rows in the same order; when more than one entry names the same
    slug (Charlee's two `children` entries), the one carrying a birth date
    wins over the one that does not, and the row never regresses from dated
    to undated.
    """
    import identity_resolution as ir  # noqa: PLC0415

    known_tokens = _roster_first_tokens(roster)
    index = None
    try:
        index = ir.roster_index(roster, entity_type="person")
    except Exception:  # noqa: BLE001 — a roster we cannot read knows nobody
        index = None

    def known(name: str) -> bool:
        key = ir.normalized_mention_key(name)
        if index is not None and (index.by_name_key.get(key) or index.by_alias_key.get(key)
                                   or index.has_ref(name)):
            return True
        return _first_token(name) in known_tokens

    by_slug: dict[str, dict] = {}
    for row in sorted(landmark_entries or (),
                      key=lambda r: (r.get("ordinal", 0) if isinstance(r, dict) else 0,
                                     r.get("source_id", "") if isinstance(r, dict) else "")):
        if not isinstance(row, dict):
            continue
        domain = roster_relations.collapsed_text_of(row.get("domain"))
        if domain not in LANDMARK_RELATION_DOMAINS:
            continue
        record = row.get("record")
        if not isinstance(record, dict):
            continue
        if domain == CHILDREN_RELATION_DOMAIN:
            relationship = "child"
        else:
            relationship = roster_relations.collapsed_text_of(record.get("relation"))
        if not relationship:
            continue
        name = roster_relations.collapsed_text_of(
            record.get("who") or record.get("label") or record.get("subject"))
        if not name or not _looks_like_a_full_name(name):
            continue
        if known(name):
            continue
        slug = ir.normalized_mention_key(name).replace(" ", "-")
        if not slug:
            continue
        date = record.get("date") if isinstance(record.get("date"), dict) else None
        born = roster_relations.collapsed_text_of(date.get("best")) if date else ""
        born_basis = roster_relations.collapsed_text_of(date.get("basis")) if date else ""
        candidate = {
            "name": name, "slug": slug, "relationship": relationship,
            "relationship_word": f"landmark:{domain}", "aliases": (),
            "source_id": row.get("source_id"), "mention": name,
        }
        if born:
            candidate["born"], candidate["born_basis"] = born, born_basis or "stated"
        existing = by_slug.get(slug)
        if existing is None or (candidate.get("born") and not existing.get("born")):
            by_slug[slug] = candidate
    return tuple(by_slug[key] for key in sorted(by_slug))


# --------------------------------------------------------------------------
# v360 (owner, 2026-09-25) — a roster row already answers to its own
# relation word
# --------------------------------------------------------------------------
#
# THE DEFECT. `grandma-betty-jo`'s own canonical NAME is "Grandma Betty Jo" —
# the owner's word for her is baked into the roster's name, not introduced by
# a separate relationship phrase beside a bare "Betty Jo". v344's
# introduction batch reads a relationship WORD beside a name it does not
# already know; the roster already had this row (`known()` was true from the
# first mention), so it never carried `relationship`.
#
# THE RULE. A roster row with no `relationship`, whose own canonical NAME
# opens with a relation word (`identity_resolution.RELATIONSHIP_MENTION_WORDS`,
# read through `roster_relations.roster_relationship_for`), gets that
# relationship — through the same writer, `entity_verdict.apply_verdict` (the
# row already exists, so never `--ensure`). Never a collective ("Kids",
# "Siblings") or a bare role word ("Son", "Daughter") — the same tests
# `relation_words.is_collective_row` / `is_role_row` already screen the
# gendered-word card with, read here rather than re-typed — and never a
# personal name that merely happens to start with a common word, because the
# check is against the CLOSED relation-word vocabulary, not any capitalised
# first token.


def relationship_from_own_name(roster: object, *, dry_run: bool = False) -> dict:
    """File `relationship` for every roster row whose own NAME already states
    it, and the row has none yet. ``{"updated": [...], "filed": n}``."""
    import entity_verdict  # noqa: PLC0415

    updated: list[dict] = []
    filed = 0
    for entity in roster_relations.roster_entities(roster):
        if roster_relations.collapsed_text_of(entity.get("relationship")):
            continue
        if relation_words.is_collective_row(entity) or relation_words.is_role_row(entity):
            continue
        name = roster_relations.collapsed_text_of(entity.get("name"))
        parts = name.split()
        if len(parts) < 2:
            continue
        relationship = roster_relations.roster_relationship_for(parts[0])
        if not relationship:
            continue
        slug = roster_relations.collapsed_text_of(entity.get("slug"))
        if not slug:
            continue
        updated.append({"slug": slug, "name": name, "relationship": relationship,
                        "relationship_word": parts[0]})
        if dry_run:
            continue
        entity_verdict.apply_verdict("person", slug, "clear", relationship=relationship)
        filed += 1
    return {"updated": updated, "filed": filed}


# --------------------------------------------------------------------------
# v360 (owner, 2026-09-25) — whose grandparent, when the roster does not say
# --------------------------------------------------------------------------
#
# `roster_relationship_for` places a "grandma"/"grandpa" word into the one
# roster bucket `grandparent` — `focus_candidate.FOCUS_RELATIONSHIPS` has no
# maternal/paternal seat, and none is needed to place her on the roster. But
# "your mom's side, or your dad's" is real information the owner may want,
# and the only way to get it is to ask: ONE low-rank card, following the v358
# `relation_words` card conventions (same `kind`, scored lowest, at most one
# per person, never re-minted once the field is set) — kind
# `relation_words.RELATION_WORD_KIND`, `requested_field` `"grandparent_side"`
# rather than `"relation_gender"`, because whose side is a different question
# about the same word.

GRANDPARENT_SIDE_FIELD = "grandparent_side"
REQUESTED_FIELD_GRANDPARENT_SIDE = "grandparent_side"

#: The two sides, as the card's own candidate refs.
MATERNAL = "maternal"
PATERNAL = "paternal"

#: v360 follow-up (owner, 2026-09-25) (item 6). A side he already SAID is known, and
#: a card about it is the failed question the owner ruled out ("a card is asked
#: only when a person could answer it" — and never when he already has). The
#: owner's own words, read the way `relation_words` reads a relationship word:
#: ONE clause, the grandparent's own spelling beside "my dad's dad" / "my mom's
#: mother" (either order), or a subject that is itself "maternal grandfather".
#: Never a surname, never a guess from "Sr.", never somebody else's words.
A_GRANDPARENT_SIDE_HE_SAID_IS_KNOWN = (
    "a grandparent's side is known when the owner's own words put it beside "
    "that grandparent's name in one clause — \"James Edwin Taylor Sr., my dad's "
    "dad\", \"my mom's mother Ruth\", \"my maternal grandmother Ruth\" — and then "
    "no side card is asked; a surname or a generational suffix decides nothing"
)

_SIDE_PARENT_WORDS = {
    "dad": PATERNAL, "father": PATERNAL, "papa": PATERNAL,
    "mom": MATERNAL, "mother": MATERNAL, "mum": MATERNAL, "mama": MATERNAL,
}
_SIDE_GRANDPARENT_WORDS = ("dad", "father", "mom", "mother", "mum", "grandpa",
                           "grandma", "grandfather", "grandmother", "parent", "parents")
_SIDE_PHRASE = (
    r"(?:my|our)\s+(?P<parent>dad|father|papa|mom|mother|mum|mama)['’]s\s+"
    r"(?:" + "|".join(_SIDE_GRANDPARENT_WORDS) + r")\b")
_SIDE_ADJECTIVE = r"(?:my\s+|our\s+)?(?P<side>maternal|paternal)\s+grand(?:father|mother|pa|ma|parent)s?\b"


def _side_spellings(entity: dict) -> list[str]:
    """The grandparent's own spellings a clause may name them by: the full name
    and any alias that is not a bare relationship word ("grandpa" is every
    grandfather)."""
    out: list[str] = []
    for value in [entity.get("name"), *(entity.get("aliases") or ())]:
        text = roster_relations.collapsed_text_of(value)
        text = re.sub(r"\s*\(.*?\)\s*", " ", text).strip()
        if not text or relation_words.bare_relation_word(text):
            continue
        if len(text) < 4 or text in out:
            continue
        out.append(text)
    return sorted(out, key=len, reverse=True)


def stated_grandparent_side(entity: object, texts: object) -> dict | None:
    """``{"side", "clause"}`` when the owner's own words give this grandparent's
    side (:data:`A_GRANDPARENT_SIDE_HE_SAID_IS_KNOWN`), else ``None``. Two
    clauses that disagree decide nothing."""
    if not isinstance(entity, dict):
        return None
    spellings = _side_spellings(entity)
    if not spellings:
        return None
    found: dict[str, str] = {}
    for text in texts or ():
        for clause in roster_relations.introduction_clauses(text):
            if not any(re.search(rf"(?<!\w){re.escape(name)}(?!\w)", clause, re.I)
                       for name in spellings):
                continue
            for match in re.finditer(_SIDE_PHRASE, clause, re.I):
                found.setdefault(_SIDE_PARENT_WORDS[match.group("parent").casefold()], clause)
            for match in re.finditer(_SIDE_ADJECTIVE, clause, re.I):
                found.setdefault(match.group("side").casefold(), clause)
    if len(found) != 1:
        return None
    side, clause = next(iter(found.items()))
    return {"side": side, "clause": clause}


def grandparent_side_rows(roster: object, *, claims: object = ()) -> tuple[dict, ...]:
    """One row per named grandparent whose side is not yet known — neither
    answered (the roster field) nor said (:func:`stated_grandparent_side` over
    the texts of ``claims``, `relation_words.texts_by_source`' own unit)."""
    import identity_resolution as ir  # noqa: PLC0415

    sources = relation_words.texts_by_source(claims)
    out: list[dict] = []
    for entity in roster_relations.roster_entities(roster):
        if roster_relations.collapsed_text_of(entity.get("relationship")) != "grandparent":
            continue
        if ir.is_alias_row(entity) or relation_words.is_collective_row(entity) \
                or relation_words.is_role_row(entity):
            continue
        if roster_relations.collapsed_text_of(entity.get(GRANDPARENT_SIDE_FIELD)):
            continue
        ref = roster_relations.entity_ref("person", entity)
        if not ref:
            continue
        sides = {row["side"] for texts in sources.values()
                 for row in (stated_grandparent_side(entity, texts),) if row}
        if len(sides) == 1:
            continue
        out.append({"subject_ref": ref, "name": roster_relations.collapsed_text_of(entity.get("name"))})
    return tuple(sorted(out, key=lambda row: row["subject_ref"]))


def grandparent_side_question(name: object) -> str:
    """The card's question, in the house wording (v358's relation-word card)."""
    body = roster_relations.collapsed_text_of(name)
    return f"Is {body} on your mom's side or your dad's?" if body else ""


def grandparent_side_cards(rows: object, *, now: object) -> tuple[dict, ...]:
    """At most one open card per row — the same shape
    `relation_words.relation_word_cards` mints, a different question."""
    import temporal_projection as tp  # noqa: PLC0415
    import temporal_timeline as tt  # noqa: PLC0415
    import temporal_work_items as twi  # noqa: PLC0415

    out: list[dict] = []
    seen: set[str] = set()
    for row in rows or ():
        name = row.get("name") if isinstance(row, dict) else ""
        if not name:
            continue
        ref = row["subject_ref"]
        work_item_id = twi.canonical_work_item_id(
            kind=relation_words.RELATION_WORD_KIND, subject_ref=ref,
            requested_field=REQUESTED_FIELD_GRANDPARENT_SIDE)
        if not work_item_id or work_item_id in seen:
            continue
        seen.add(work_item_id)
        scores = tt._score_components(  # noqa: SLF001 — the fold's one scorer
            relation_words.RELATION_WORD_KIND, system_value=0.0, event_kind=None,
            subject_ref=ref, resolved=True)
        item = tp.validate_temporal_work_item({
            "work_item_id": work_item_id,
            "kind": relation_words.RELATION_WORD_KIND,
            "state": "open",
            "subject_ref": ref,
            "requested_field": GRANDPARENT_SIDE_FIELD,
            "prompt_intent": grandparent_side_question(name),
            "allowed_surfaces": list(tt.SURFACES_BY_KIND.get(
                relation_words.RELATION_WORD_KIND, ("timeline",))),
            **scores,
            "created_at": now,
            "updated_at": now,
        }, now=now)
        item["label"] = name
        item["candidates"] = [
            {"ref": MATERNAL, "name": "my mom's side"},
            {"ref": PATERNAL, "name": "my dad's side"},
            {"ref": "unspecified", "name": "just “grandparent”"},
        ]
        out.append(item)
    return tuple(out)


def with_grandparent_side_cards(payloads: dict, *, roster: object, now: object = None,
                                claims: object = ()) -> dict:
    """Publish the ambiguity cards onto a rendered payload pair, in place —
    the same append shape `relation_words.with_relation_words` uses for its
    own cards, so the two kinds sit in the same queue without either module
    writing the other's. Wired into `temporal_publication` beside the
    relation-word cards (v360 follow-up, owner 2026-09-25, item 6)."""
    rows = grandparent_side_rows(roster, claims=claims)
    cards = grandparent_side_cards(rows, now=now)
    if cards:
        for payload in payloads.values():
            items = payload.get("work_items")
            if not isinstance(items, list):
                continue
            have = {str(row.get("work_item_id") or "") for row in items
                    if isinstance(row, dict)}
            added = [dict(card) for card in cards if card["work_item_id"] not in have]
            if not added:
                continue
            payload["work_items"] = [*items, *added]
            counts = payload.get("counts")
            if isinstance(counts, dict) and "work_items" in counts:
                counts["work_items"] = len(payload["work_items"])
            components = payload.get("score_components")
            if isinstance(components, dict):
                for card in added:
                    components[card["work_item_id"]] = {
                        key: card[key] for key in (
                            "person_value", "system_value", "interaction_cost",
                            "sensitivity", "context_fit", "combined_score")
                        if key in card}
    return {"rows": rows, "cards": cards}


# --------------------------------------------------------------------------
# v344 — the person a relationship phrase introduced gets a row
# --------------------------------------------------------------------------


def ensure_introduced_relatives(*, dry_run: bool = False) -> dict:
    """File a roster row for every person the claim substrate INTRODUCES.

    `roster_relations.relationship_introductions` is the whole rule
    (:data:`roster_relations.A_RELATIONSHIP_PHRASE_INTRODUCES_A_PERSON`) and
    this is the one seat that writes it — through
    `entity_verdict.apply_verdict(..., ensure=True)`, the door the `james` and
    `anthon-james-taylor` rows already came through (`source:
    "landmark:family"`), one atomic per-row roster write each and never a
    rewrite of the file. Verdict ``clear``, because this asserts an IDENTITY and
    not a page verdict — exactly `general_listener.person_invocations`' reading
    of the same seam.

    Idempotent twice over: a name already on the roster is never an
    introduction at all, and a second run of the same batch finds the row and
    unions nothing new. An alias an EXISTING row already answers to is dropped
    and reported rather than stolen, which is `roster_relations.alias_decision`'s
    refusal read before the write instead of after it.

    v347 also hands the rule what the vault ALREADY records — every `family`
    landmark entry's ``relation`` and every temporal correction's own words —
    so an introduction that contradicts one is refused out loud rather than
    written (`roster_relations.A_RECORDED_RELATION_OUTRANKS_AN_INTRODUCED_ONE`).
    The refusals come back as ``findings``; nothing about them is written.

    v360 (owner, 2026-09-25) (roster membership): the claim-sourced batch is joined
    by :func:`landmark_relationship_introductions` — a `children`/`family`
    LANDMARK ENTRY introduces a person exactly as a claim's relationship
    phrase does, through the same writer, for the person a claim alone never
    reaches (Charlee, Dottie) — and by :func:`relationship_from_own_name`, for
    a row the roster already has whose own name states the relation nobody
    ever filed (Grandma Betty Jo). Both are additive and additional to the
    claim-sourced rows, never a replacement of them.

    ``{"introduced": [...], "filed": n, "skipped_aliases": [...],
    "findings": [...], "own_name": [...]}``.
    """
    import entity_verdict  # noqa: PLC0415
    import landmark_projection as lp  # noqa: PLC0415
    import temporal_publication as pub  # noqa: PLC0415
    import temporal_store as store  # noqa: PLC0415
    from lifehug_core import REPO_DIR  # noqa: PLC0415

    roster, owner_names = pub.owner_identity_inputs(REPO_DIR)
    claims = store.active_claims(store.read_active_index(REPO_DIR))
    try:
        landmark_entries = lp.load_landmark_sources(REPO_DIR)
    except Exception:  # noqa: BLE001  — a vault we cannot read records nothing
        landmark_entries = ()
    try:
        correction_texts = [correction.reason for correction
                            in store.load_temporal_corrections(REPO_DIR)]
    except Exception:  # noqa: BLE001
        correction_texts = []
    batch = roster_relations.relationship_introduction_batch(
        claims, roster=roster, owner_names=owner_names,
        landmark_entries=landmark_entries, correction_texts=correction_texts,
    )
    rows = list(batch["rows"])
    have_slugs = {row["slug"] for row in rows}
    for row in landmark_relationship_introductions(landmark_entries, roster=roster):
        if row["slug"] not in have_slugs:
            rows.append(row)
            have_slugs.add(row["slug"])
    skipped: list[dict] = []
    filed = 0
    for row in rows:
        aliases = []
        for alias in row.get("aliases") or ():
            taken = [entity for entity in roster_relations.find_by_alias(roster, alias)
                     if entity.get("slug") != row["slug"]]
            if taken:
                skipped.append({"slug": row["slug"], "alias": alias,
                                "taken_by": [e.get("slug") for e in taken]})
                continue
            aliases.append(alias)
        if dry_run:
            continue
        entity_verdict.apply_verdict(
            "person", row["slug"], "clear",
            aliases=aliases,
            relationship=row["relationship"],
            born=row.get("born"),
            born_basis=row.get("born_basis"),
            ensure=True,
            name=row["name"],
        )
        filed += 1
    own_name = relationship_from_own_name(roster, dry_run=dry_run)
    return {"introduced": list(rows), "filed": filed, "skipped_aliases": skipped,
            "findings": list(batch["findings"]), "own_name": own_name["updated"]}


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
    parser.add_argument("--ensure-introduced", action="store_true",
                        help="File a person row for everybody the claim substrate "
                             "introduces with a relationship phrase (v344). "
                             "Deterministic, additive, idempotent — no AI.")
    parser.add_argument("--dry-run", action="store_true",
                        help="With --ensure-introduced: report the rows, write nothing.")
    args = parser.parse_args()
    t = args.type

    if args.ensure_introduced:
        result = ensure_introduced_relatives(dry_run=args.dry_run)
        verb = "would file" if args.dry_run else "filed"
        print(f"✓ relationship introductions: {verb} "
              f"{len(result['introduced']) if args.dry_run else result['filed']} "
              f"person row(s)")
        for row in result["introduced"]:
            aliases = ", ".join(row.get("aliases") or ()) or "—"
            born = f", born {row['born']}" if row.get("born") else ""
            print(f"  {row['slug']}: {row['name']} — {row['relationship']} "
                  f"(from “{row['relationship_word']}”{born}); aliases: {aliases}")
            for alias in row.get("contested_aliases") or ():
                print(f"    ↯ “{alias}” names more than one introduced person — bound to neither")
        for row in result.get("findings") or ():
            print(f"    ↯ {row['name']} — introduced as {row['introduced']} "
                  f"(from “{row['introduced_word']}”), but the vault records "
                  f"{row['recorded']} ({row['tier']}): {row['reason']}")
        for row in result["skipped_aliases"]:
            print(f"    ↯ “{row['alias']}” already answers to "
                  f"{', '.join(row['taken_by'])} — left alone")
        for row in result.get("own_name") or ():
            print(f"  {row['slug']}: {row['name']} — {row['relationship']} "
                  f"(from its own name's “{row['relationship_word']}”)")
        return 0

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
