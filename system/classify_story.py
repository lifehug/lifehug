#!/usr/bin/env python3
"""Classify ingested Lifehug stories using the shared AI provider.

Extracts entities, themes, story functions, and generates smart
candidate questions from any source file or answer file.

Modes
-----
--classify <source_path>          Classify a single file via AI.
--prompt <source_path>            Print the prompt only (no API call).
--classify-all [--unclassified]   Batch classify all (or only unclassified) sources.
--dry-run                         Preview actions without model calls or writes.

Examples
--------
python3 system/classify_story.py --classify sources/manual/arizona.md
python3 system/classify_story.py --prompt sources/manual/arizona.md
python3 system/classify_story.py --classify-all --unclassified
python3 system/classify_story.py --classify-all --unclassified --dry-run
python3 system/classify_story.py --classify sources/manual/arizona.md --model claude-opus-4-20250514
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

# ── path bootstrapping so the script is importable from anywhere ──────────────
SYSTEM_DIR = Path(__file__).resolve().parent
if str(SYSTEM_DIR) not in sys.path:
    sys.path.insert(0, str(SYSTEM_DIR))
LEGACY_FOCUS_KEY = "spot" "light_opportunities"

from ai_provider import AIResponseError, failure_metadata, normalize_question_records

from lifehug_core import (
    ANSWERS_DIR,
    CLASSIFICATIONS_DIR,
    MANUAL_SOURCES_DIR,
    MISSION_FILE,
    QUESTION_CANDIDATES_FILE,
    QUESTIONS_FILE,
    REPO_DIR,
    SOURCES_DIR,
    STORY_FUNCTIONS,
    answer_body,
    load_config,
    load_mission,
    now_utc,
    parse_categories,
    parse_questions,
    read_json,
    slugify,
    write_json,
    write_text,
)
from question_judgment import build_decision_context, load_judgment_rubric, owner_judgment_signals_block

# ── constants ─────────────────────────────────────────────────────────────────
# Non-dated alias — tracks the current Sonnet tier instead of pinning a
# snapshot that ages out. Override with `classify_model` in config.yaml.
# claude-sonnet-5 is the current active Sonnet per Anthropic's model catalog;
# a 2026-07-05 report of it 404ing could not be reproduced and is believed
# misdiagnosed — if it recurs on an instance, set `classify_model:
# claude-sonnet-4-6` in config.yaml and capture the actual error.
DEFAULT_MODEL = "claude-sonnet-5"

# Taxonomy themes for the AI prompt
THEME_TAXONOMY = [
    "hunger", "agency", "faith", "money", "belonging", "grief", "ambition",
    "identity", "family", "friendship", "love", "loss", "risk", "fear",
    "purpose", "work", "creativity", "race", "class", "migration",
    "education", "mentorship", "failure", "resilience", "legacy",
    "culture", "politics", "community", "health", "spirituality", "shame",
    "pride", "forgiveness", "betrayal", "justice", "freedom", "adventure",
    "solitude", "home", "nostalgia", "regret", "hope", "joy",
    "parenting", "marriage", "aging",
]


# ── AI client ─────────────────────────────────────────────────────────────────


def classify_with_ai(prompt: str, model: str = DEFAULT_MODEL) -> dict:
    """Classify through the shared provider while prompt mode stays keyless."""
    from ai_provider import call_ai  # local import keeps prompt mode keyless

    return extract_json(call_ai(prompt, model))


def get_model(args: argparse.Namespace) -> str:
    """Resolve effective model: CLI flag > config.yaml > default."""
    if getattr(args, "model", None):
        return args.model
    config = load_config()
    return config.get("classify_model", DEFAULT_MODEL)


# ── source file parsing ───────────────────────────────────────────────────────

def parse_frontmatter(content: str) -> tuple[dict, str]:
    """Return (frontmatter_dict, body_text) from a markdown file.

    Handles both source files (--- YAML ---) and answer files.
    """
    fm: dict = {}
    body = content

    if content.startswith("---"):
        # Find the closing ---
        end = content.find("\n---", 3)
        if end != -1:
            raw_fm = content[3:end].strip()
            body = content[end + 4:].strip()
            for line in raw_fm.splitlines():
                if ":" in line:
                    k, _, v = line.partition(":")
                    fm[k.strip()] = v.strip().strip('"').strip("'")
    return fm, body


def load_source_text(source_path: Path) -> tuple[dict, str]:
    """Load a source or answer file and return (metadata, story_text)."""
    content = source_path.read_text(encoding="utf-8")
    fm, body = parse_frontmatter(content)

    # Answer files: use answer_body() helper for cleaner extraction
    if source_path.parent.name == "answers" or source_path.is_relative_to(ANSWERS_DIR):
        body = answer_body(content)

    return fm, body


# Longest suffix appended to a stem is ".response.json" (14 chars); capping at
# 180 keeps every derived filename comfortably under the 255-byte filesystem
# limit. Stems at or under the cap are byte-identical to their historical
# values, so existing classification files keep matching.
MAX_STEM_LEN = 180


def classify_stem(source_path: Path) -> str:
    """Return the stable classification file stem for a given source path.

    Over-long stems (retraction slugs embed the full question text and can
    exceed the 255-byte filename limit by themselves) are truncated and made
    unique with a stable hash of the full stem."""
    if not source_path.is_absolute():
        source_path = REPO_DIR / source_path
    try:
        rel = source_path.relative_to(REPO_DIR)
        key = rel.with_suffix("").as_posix()
    except ValueError:
        key = source_path.stem
    stem = slugify(key)
    if len(stem) > MAX_STEM_LEN:
        import hashlib  # noqa: PLC0415

        digest = hashlib.sha256(stem.encode("utf-8")).hexdigest()[:12]
        stem = f"{stem[:MAX_STEM_LEN].rstrip('-')}-{digest}"
    return stem


def classification_path(source_path: Path) -> Path:
    return CLASSIFICATIONS_DIR / f"{classify_stem(source_path)}.json"


def legacy_classification_path(source_path: Path) -> Path:
    """Return the v14-v42 stem-only path, kept for existing state compatibility."""
    return CLASSIFICATIONS_DIR / f"{source_path.stem}.json"


def classification_paths(source_path: Path) -> list[Path]:
    paths = [classification_path(source_path)]
    legacy = legacy_classification_path(source_path)
    if legacy != paths[0]:
        paths.append(legacy)
    return paths


def is_classified(source_path: Path) -> bool:
    """Classified AND current. A classification carrying `stale: true` (a
    correction was filed against its source, v103) counts as unclassified so
    the weekly batch re-derives it — the classify prompt already injects
    corrections as authoritative, so the re-derivation asserts the corrected
    facts. The stale classification stays on disk (and keeps feeding the
    timeline/wiki) until the fresh one overwrites it."""
    for path in classification_paths(source_path):
        if path.exists():
            return not _is_stale(path)
    return False


def _is_stale(path: Path) -> bool:
    return bool((read_json(path, default=None) or {}).get("stale"))


def mark_stale(source_path: Path, reason: str = "") -> bool:
    """Flag an existing classification for re-derivation (v103). Returns True
    if a classification file was found (already-stale counts)."""
    marked = False
    for path in classification_paths(source_path):
        if not path.exists():
            continue
        data = read_json(path, default=None) or {}
        if not data.get("stale"):
            data["stale"] = True
            data["stale_reason"] = reason
            data["stale_at"] = now_utc()
            write_json(path, data)
        marked = True
    return marked


def all_source_files() -> list[Path]:
    """Return all source and answer files across the repo."""
    files: list[Path] = []
    for directory in (SOURCES_DIR, ANSWERS_DIR):
        if directory.exists():
            files.extend(
                p for p in directory.rglob("*.md")
                if not p.name.startswith(".")
            )
    return sorted(files)


# ── prompt construction ───────────────────────────────────────────────────────

def load_question_categories() -> str:
    """Return a compact list of question-bank categories for the prompt."""
    if not QUESTIONS_FILE.exists():
        return "(question bank unavailable)"
    md_text = QUESTIONS_FILE.read_text(encoding="utf-8")
    categories = parse_categories(md_text)
    lines = [
        f"  {cat_id}: {info['name']} [{info['group']}]"
        for cat_id, info in sorted(categories.items())
    ]
    return "\n".join(lines) or "(no categories found)"



def _relative_path(source_path) -> str:
    """Return path relative to REPO_DIR when possible, else str."""
    try:
        return source_path.relative_to(REPO_DIR).as_posix()
    except ValueError:
        return str(source_path)


def _corrections_block(source_path: Path) -> str:
    corrections = corrections_for(source_path)
    if not corrections:
        return ""
    joined = "\n".join(f"- {c}" for c in corrections)
    return (f"\n## LATER CORRECTIONS (authoritative — these OVERRIDE the story text "
            f"above; never extract the corrected-away version)\n{joined}\n")


def corrections_for(source_path: Path) -> list[str]:
    """Later authoritative corrections targeting this source (issue #24) —
    included in the classification prompt so a corrected-away fact is never
    re-derived into people/places/events/candidates."""
    corrections_dir = SOURCES_DIR / "corrections"
    if not corrections_dir.exists():
        return []
    rel_target = _relative_path(source_path)
    out: list[str] = []
    for path in sorted(corrections_dir.glob("*.md")):
        content = path.read_text(encoding="utf-8", errors="replace")
        fm2, body = parse_frontmatter(content)
        if fm2.get("type") != "source_correction":
            continue
        if fm2.get("corrects_path") == rel_target or fm2.get("corrects") == f"answer:{source_path.stem}":
            body = re.sub(r"^# .+?\n+", "", body, count=1).strip()
            out.append(body)
    return out


def build_prompt(source_path: Path, fm: dict, story_text: str) -> str:
    """Construct the full AI classification prompt for a source file."""
    mission = load_mission()
    judgment_rubric = load_judgment_rubric()
    judgment_section = f"## Question-Judgment Rubric\n{judgment_rubric}"
    signals_block = owner_judgment_signals_block(build_decision_context(limit=15))
    if signals_block:
        judgment_section += f"\n\n{signals_block}"
    categories_block = load_question_categories()
    story_functions_block = "\n".join(f"  - {sf}" for sf in STORY_FUNCTIONS)
    themes_block = ", ".join(THEME_TAXONOMY)

    relative_path = _relative_path(source_path)

    prompt = f"""You are a memoir analyst and oral history specialist helping to classify a personal story for the Lifehug memoir project.

## Lifehug Mission
{mission}

{judgment_section}

---

## Source File
Path: {relative_path}
Title: {fm.get('title', '(untitled)')}
Type: {fm.get('type', 'unknown')}
Captured at: {fm.get('captured_at', 'unknown')}

## Story Text
{story_text}
{_corrections_block(source_path)}

---

## Your Task
Analyze the story and return a single JSON object with the following keys.
Do NOT include any explanation before or after the JSON block.
Return ONLY the raw JSON (no markdown fences, no commentary).

### Required output schema:

{{
  "people": [
    {{ "name": "string", "relationship": "string", "role": "string", "mention_count": 1 }}
  ],
  "places": [
    {{ "name": "string", "type": "city|region|country|building|neighborhood|other", "time_period": "string or null" }}
  ],
  "time_periods": [
    {{ "era": "string", "approximate_dates": "string or null", "life_stage": "string" }}
  ],
  "themes": ["list of theme strings from this taxonomy: {themes_block}"],
  "projects": [
    {{ "name": "string", "type": "business|personal|creative|community|other" }}
  ],
  "contradictions": ["list of unresolved tensions as plain strings"],
  "possible_outputs": [
    {{ "type": "letter|chapter|essay|post|speech|profile", "description": "string" }}
  ],
  "focus_opportunities": [
    {{
      "entity": "string",
      "type": "person|place|period|project|theme",
      "evidence_strength": "weak|moderate|strong",
      "reason": "string"
    }}
  ],
  "self_understanding_insights": ["list of patterns, beliefs, or values surfaced as plain strings"],
  "suggested_sensitivity": "private|family|friends|public",
  "sensitivity_reason": "string — one line on why",
  "scene_slots": {{
    "what_happened": true,
    "when_and_where": false,
    "who_was_there": true,
    "thought_and_felt": false,
    "what_it_says_about_me": false
  }},
  "situation_vs_story": "situation_rich_story_empty|story_rich_situation_thin|balanced|neither",
  "events": [
    {{ "title": "string — a noun phrase of at most 7 words naming the THING, not the telling ('Grandpa\'s two-page letter')", "description": "string — one datable moment", "when_hint": "string or null — as stated ('sixth grade', 'two weeks after the wedding')", "anchor": "string or null — nearest landmark (a move, wedding, birth, job change)", "date": {{ "stated": "string or null — a date or year the author ACTUALLY SAID", "age": "string or null — the author's age at the time, in their words ('about five')", "anchor_ref": "string or null — the landmark this is dated against", "relation": "before|after|during|null" }} }}
  ],
  "candidate_questions": [
    {{
      "text": "string — the actual question",
      "story_function": "one of: {', '.join(STORY_FUNCTIONS)}",
      "priority": 0.75,
      "reason": "why this question matters for the memoir",
      "defer": false,
      "target_category": "one of these category IDs or null — {', '.join(sorted(parse_categories(QUESTIONS_FILE.read_text(encoding='utf-8') if QUESTIONS_FILE.exists() else '').keys()))}"
    }}
  ]
}}

### Guidelines
- `people`: include every named or described person; estimate mention_count from how prominent they are
- `themes`: prefer taxonomy terms when a close one exists; if the story's CENTRAL theme is genuinely absent from the taxonomy, name it (one or two words, lowercase) — the monthly theme roster curates and merges what you surface
- `suggested_sensitivity`: the most-open audience tier this source could EVER be rendered for.
  Taxonomy (default private when in doubt — the owner reviews before anything opens):
  private = sexuality/intimacy; raw mental-health texture; active wounds involving living
  people; other people's confided secrets; legal/deal specifics; anything a minor child
  disclosed. family = financial specifics, health/body specifics, children's inner lives
  (hard cap — never above family). friends = embarrassing-but-harmless stories, faith
  struggles. public = the narrative arcs themselves (struggle-and-rebuild, scarcity-to-
  success) told without the protected specifics.
- `scene_slots`: which of McAdams' five scene slots this story already fills — what happened / when & where / who was there / what the author thought & felt / what it says about them
- `situation_vs_story` (Gornick): situation = what happened; story = the insight, the thing the author has come to say. Tag which this source has.
- `events`: every datable moment. **Do not invent; do record what was said.** NEVER
  convert, infer, or guess a year the author did not say — record their own time
  words (`when_hint`) and the nearest landmark event (`anchor`); relative anchors
  beat guessed dates. Fill `date` ONLY from what the author explicitly stated: a
  date or year they actually said (`stated`), their age at the time in their own
  words (`age`), or the landmark plus the before/after/during relation they gave
  (`anchor_ref` + `relation`). Leave any key null when they did not say it, and
  leave `date` itself null when they said none of it. The system does the
  arithmetic from there — an age against a birthday, a relation against a dated
  landmark — so a guessed year is worse than no year at all.
- `events[].title`: a noun phrase of at most seven words naming the thing, not the
  telling: "Grandpa's two-page letter", not "the time Grandpa wrote to me about the
  farm". No verbs of narration, no dates in the title.
- `candidate_questions`: generate 3–8 high-quality follow-up questions. **Craft rules (violations get parked, so follow them):**
  - **Two-sentence rule**: one sentence of context quoting or referencing the author's own words, then ONE open question. One question mark per candidate.
  - **Target the empty scene_slots.** "What does it say about you?" is the highest-value follow-up when that slot is empty.
  - **Action↔identity ladder**: after an action answer ask what it says about them; after an identity claim ask for one specific moment that proves it.
  - **Situation-rich/story-empty sources get the meaning-making question**; story-rich/situation-thin sources get the scene question ("pick one of those mornings — what did it smell like?").
  - **"What"/"When"/"Tell me about", never "Why", for the author's own feelings** (why-questions about one's own emotions produce confabulation). "Why" is fine for events and other people.
  - **Never restate the author's account with changed details** — quote exactly or ask fresh (memory reconsolidation contamination).
  - **New angles only** — if the source retells a story the archive already holds, ask for what's NEVER been told ("a detail from that day you've never mentioned to anyone"), never a re-rehearsal.
  - **High-negative-affect material**: offer ONE distanced question (fly-on-the-wall retelling, or "when you're 80, what will this chapter mean?") rather than digging straight in. If the story describes an upheaval within the last ~2 months, set `"defer": true` on deep-processing questions (they will wait ~60 days — expressive-writing evidence says too-soon is harmful).
  - **Draw from the high-yield families** where they fit: typical-day reconstruction; era anchors (what things cost, the car, the music, the house room by room); photo/song cues ("what song puts you back there?"); perspective-taking ("tell it as your dad would tell it"); off-script probes ("which milestone did NOT go the way the script says?"); forgiveness/blessing ("what do you wish for them that you've never said out loud?").
  - Assign story_function from the list: {', '.join(STORY_FUNCTIONS)}
  - Set priority between 0.4 (nice-to-have) and 0.95 (critical gap)
- `focus_opportunities`: entities rich enough to anchor a dedicated wiki page or chapter section
- `contradictions`: tensions or paradoxes in values, beliefs, or events — leave them unresolved, do not explain them away
- `possible_outputs`: concrete deliverables this story could contribute to

### Question bank categories for target_category:
{categories_block}

Respond with ONLY valid JSON. No prose, no markdown fences.
"""
    # v96: opinion sources are STATED POSITIONS, not event accounts. The
    # addendum is strictly conditional so every other source's prompt stays
    # byte-identical.
    if fm.get("type") == "opinion":
        prompt += """
### OPINION ADDENDUM (this source is a stated position, not an event account)
- The author is stating a POSITION — a lens on life, a philosophical opinion.
  Do not treat it as a factual event narrative.
- Distill each distinct position it takes into `self_understanding_insights`,
  each prefixed with "position: " (e.g. "position: parents who rose above
  their natural selves deserve gratitude, not disappointment, when they
  revert"). These feed the author's self-knowledge surfaces.
- `contradictions`: only genuine tensions WITHIN the stated position or
  between it and the author's other known positions — never manufacture one.
- `events`: usually empty for an opinion; include only moments the author
  actually narrates.
- `candidate_questions`: use the SOCRATIC families instead of scene probes —
  origin (who taught this / what moment forged it → story_function "value"),
  lived counterexample (→ "contradiction"), how the position has changed
  (→ "growth_edge"), who would disagree and what they see (→
  "perception_by_others"), what holding it costs or protects (→ "fear").
  The Gornick rule still applies: an opinion is story without situation, so
  ONE grounding question asking for a specific lived moment behind the belief
  is high-value.
"""
    return prompt


# ── AI call ───────────────────────────────────────────────────────────────────

def extract_json(text: str) -> dict:
    """Extract a JSON object from the AI response text."""
    def require_object(value: object) -> dict:
        if isinstance(value, dict):
            return value
        raise AIResponseError(
            "AI response JSON had an invalid schema",
            provider="ai",
            operation="classify-parse",
            status="invalid_schema",
            response_bytes=len(text.encode("utf-8", errors="replace")),
        )

    # Try direct parse first
    stripped = text.strip()
    try:
        return require_object(json.loads(stripped))
    except json.JSONDecodeError:
        pass

    # Strip markdown code fences if present
    fence_match = re.search(r"```(?:json)?\s*([\s\S]+?)\s*```", stripped)
    if fence_match:
        try:
            return require_object(json.loads(fence_match.group(1)))
        except json.JSONDecodeError:
            pass

    # Find the first { ... } block
    brace_match = re.search(r"\{[\s\S]+\}", stripped)
    if brace_match:
        try:
            return require_object(json.loads(brace_match.group(0)))
        except json.JSONDecodeError:
            pass

    raise AIResponseError(
        "AI response was not valid JSON",
        provider="ai",
        operation="classify-parse",
        status="malformed",
        response_bytes=len(text.encode("utf-8", errors="replace")),
    )


# ── candidate store helpers ───────────────────────────────────────────────────

def load_candidate_store() -> dict:
    data = read_json(QUESTION_CANDIDATES_FILE, default=None)
    if not isinstance(data, dict):
        return {"version": 1, "candidates": []}
    data.setdefault("version", 1)
    data.setdefault("candidates", [])
    return data


def save_candidate_store(data: dict) -> None:
    data["last_updated"] = now_utc()
    write_json(QUESTION_CANDIDATES_FILE, data)


def next_candidate_index(store: dict, stem: str) -> int:
    """Return the next available candidate index for a given source stem."""
    prefix = f"cand-{slugify(stem)}-"
    existing = [
        c["id"] for c in store.get("candidates", [])
        if c.get("id", "").startswith(prefix)
    ]
    if not existing:
        return 1
    indices = []
    for cid in existing:
        m = re.search(r"-(\d+)$", cid)
        if m:
            indices.append(int(m.group(1)))
    return max(indices, default=0) + 1


def build_candidates(
    ai_questions: list[dict],
    source_path: Path,
    store: dict,
    created_at: str,
) -> list[dict]:
    """Convert AI candidate_questions into store-format candidate records."""
    stem = classify_stem(source_path)
    relative_path = _relative_path(source_path)

    existing_texts = {
        c.get("text", "").strip().lower()
        for c in store.get("candidates", [])
    }
    existing_ids = {c.get("id") for c in store.get("candidates", [])}

    start_idx = next_candidate_index(store, stem)
    candidates: list[dict] = []

    for offset, q in enumerate(ai_questions or []):
        text = str(q.get("text", "")).strip()
        if not text:
            continue
        if text.lower() in existing_texts:
            continue  # deduplicate by normalized text

        story_function = q.get("story_function", "")
        if story_function not in STORY_FUNCTIONS:
            story_function = "scene"  # safe fallback

        priority = float(q.get("priority", 0.5))
        priority = max(0.0, min(1.0, priority))

        cid = f"cand-{slugify(stem)}-{start_idx + offset}"
        # Ensure uniqueness even across concurrent runs
        while cid in existing_ids:
            start_idx += 1
            cid = f"cand-{slugify(stem)}-{start_idx + offset}"

        target_cat = q.get("target_category") or None
        if isinstance(target_cat, str):
            target_cat = target_cat.strip().upper() or None

        record: dict = {
            "id": cid,
            "text": text,
            "source_path": relative_path,
            "target_page": None,
            "kind": story_function,
            "priority": priority,
            "reason": str(q.get("reason", "")).strip(),
            "status": "candidate",
            "story_function": story_function,
            "created_at": created_at,
        }
        if target_cat:
            record["target_category"] = target_cat
        # Fresh-upheaval deferral (Pennebaker): deep-processing questions on a
        # recent upheaval wait ~60 days before becoming promotable.
        if q.get("defer"):
            from datetime import datetime, timedelta, timezone  # noqa: PLC0415
            defer_until = datetime.now(timezone.utc) + timedelta(days=60)
            record["defer_until"] = defer_until.isoformat().replace("+00:00", "Z")
            record["defer_reason"] = "fresh upheaval — deep processing deferred ~60 days"

        candidates.append(record)
        existing_texts.add(text.lower())
        existing_ids.add(cid)

    return candidates


# ── classification record ─────────────────────────────────────────────────────

def build_classification(
    source_path: Path,
    fm: dict,
    ai_result: dict,
    model: str,
    classified_at: str,
    candidate_ids: list[str],
) -> dict:
    relative_path = _relative_path(source_path)
    return {
        "version": 1,
        "source_path": relative_path,
        "source_title": fm.get("title", ""),
        "source_type": fm.get("type", "unknown"),
        "classified_at": classified_at,
        "model_used": model,
        "reviewable": True,
        "candidate_question_ids": candidate_ids,
        # ── extracted fields (as-returned by AI, mark reviewable) ──
        "people": ai_result.get("people", []),
        "places": ai_result.get("places", []),
        "time_periods": ai_result.get("time_periods", []),
        "themes": ai_result.get("themes", []),
        "projects": ai_result.get("projects", []),
        "contradictions": ai_result.get("contradictions", []),
        "possible_outputs": ai_result.get("possible_outputs", []),
        "focus_opportunities": ai_result.get(
            "focus_opportunities",
            ai_result.get(LEGACY_FOCUS_KEY, []),
        ),
        "self_understanding_insights": ai_result.get("self_understanding_insights", []),
        # v70/v71: five-slot scene coverage, Gornick tag, and datable events
        # (relative anchors, never guessed years) for the timeline surface.
        "suggested_sensitivity": ai_result.get("suggested_sensitivity", "private"),
        "sensitivity_reason": ai_result.get("sensitivity_reason", ""),
        "scene_slots": ai_result.get("scene_slots", {}),
        "situation_vs_story": ai_result.get("situation_vs_story", ""),
        "events": ai_result.get("events", []),
    }


# ── printing helpers ──────────────────────────────────────────────────────────

def print_summary(classification: dict, new_candidates: list[dict]) -> None:
    src = classification.get("source_path", "?")
    model = classification.get("model_used", "?")
    classified_at = classification.get("classified_at", "?")

    print(f"\n✓ Classified: {src}")
    print(f"  model   : {model}")
    print(f"  at      : {classified_at}")

    people = classification.get("people", [])
    places = classification.get("places", [])
    themes = classification.get("themes", [])
    contradictions = classification.get("contradictions", [])
    outputs = classification.get("possible_outputs", [])
    focuses = classification.get("focus_opportunities", classification.get(LEGACY_FOCUS_KEY, []))
    insights = classification.get("self_understanding_insights", [])

    if people:
        names = ", ".join(p.get("name", "?") for p in people[:6])
        suffix = f" (+{len(people)-6} more)" if len(people) > 6 else ""
        print(f"  people  : {names}{suffix}")
    if places:
        place_names = ", ".join(p.get("name", "?") for p in places[:4])
        print(f"  places  : {place_names}")
    if themes:
        print(f"  themes  : {', '.join(themes[:8])}")
    if contradictions:
        print(f"  tensions: {len(contradictions)}")
    if outputs:
        out_types = ", ".join(o.get("type", "?") for o in outputs)
        print(f"  outputs : {out_types}")
    if focuses:
        focus_names = ", ".join(s.get("entity", "?") for s in focuses[:4])
        print(f"  focuses : {focus_names}")
    if insights:
        print(f"  insights: {len(insights)}")

    if new_candidates:
        print(f"  cands   : {len(new_candidates)} new question candidates")
        for c in new_candidates:
            print(f"    [{c['id']}] ({c.get('priority', 0):.2f}) {c['text']}")
    else:
        print("  cands   : 0 new question candidates")


# ── core classify action ──────────────────────────────────────────────────────

def classify_file(
    source_path: Path,
    model: str,
    *,
    dry_run: bool = False,
    verbose: bool = False,
    skip_candidates: bool = False,
    precomputed_result: dict | None = None,
) -> int:
    """Classify a single source file. Returns 0 on success, 1 on error.

    `precomputed_result` (keyless path, --from-response): an externally-produced
    classification JSON that flows through the SAME validation/persistence as
    the AI path. `skip_candidates` suppresses candidate-question generation —
    used for archive backfills where hundreds of new candidates would flood
    the review store without adding craft value."""
    if not source_path.exists():
        print(f"Error: file not found: {source_path}", file=sys.stderr)
        return 1

    fm, story_text = load_source_text(source_path)

    if not story_text.strip():
        print(f"Warning: no story text found in {source_path}", file=sys.stderr)
        return 1

    if dry_run:
        clf_path = classification_path(source_path)
        print(f"[dry-run] would classify: {_relative_path(source_path)}")
        print(f"[dry-run] would call model: {model}")
        print(f"[dry-run] would write classification: {clf_path}")
        if not skip_candidates:
            print("[dry-run] would append candidate questions returned by the model")
        return 0

    if precomputed_result is not None:
        ai_result = precomputed_result
    else:
        prompt = build_prompt(source_path, fm, story_text)
        if verbose:
            print(f"[verbose] calling model={model} for {source_path}")
        try:
            ai_result = classify_with_ai(prompt, model=model)
        except Exception as exc:
            print(
                "Error: AI classification failed: "
                + failure_metadata("classify", exc, provider="ai"),
                file=sys.stderr,
            )
            return 1

    classified_at = now_utc()

    try:
        # Validate every model-derived coercion before any persistence.
        store = load_candidate_store()
        ai_questions = [] if skip_candidates else normalize_question_records(
            ai_result.get("candidate_questions", []),
            operation="classify-schema",
        )
        new_candidates = build_candidates(
            ai_questions, source_path, store, classified_at
        )
        candidate_ids = [c["id"] for c in new_candidates]
        classification = build_classification(
            source_path, fm, ai_result, model, classified_at, candidate_ids
        )
    except Exception as exc:  # noqa: BLE001 — model schema failures stay private
        print(
            "Error: AI classification schema failed: "
            + failure_metadata("classify-schema", exc, provider="ai"),
            file=sys.stderr,
        )
        return 1

    clf_path = classification_path(source_path)

    # Write classification
    CLASSIFICATIONS_DIR.mkdir(parents=True, exist_ok=True)
    write_json(clf_path, classification)

    # Append new candidates to store
    if new_candidates:
        store["candidates"].extend(new_candidates)
        save_candidate_store(store)

    print_summary(classification, new_candidates)
    return 0


# ── modes ─────────────────────────────────────────────────────────────────────

def cmd_classify(args: argparse.Namespace) -> int:
    source_path = Path(args.classify)
    if not source_path.is_absolute():
        source_path = REPO_DIR / source_path
    model = get_model(args)
    return classify_file(
        source_path,
        model,
        dry_run=args.dry_run,
        verbose=getattr(args, "verbose", False),
        skip_candidates=getattr(args, "no_candidates", False),
    )


def cmd_prompt(args: argparse.Namespace) -> int:
    """Print the classification prompt for a source file (no API call)."""
    source_path = Path(args.prompt_file)
    if not source_path.is_absolute():
        source_path = REPO_DIR / source_path

    if not source_path.exists():
        print(f"Error: file not found: {source_path}", file=sys.stderr)
        return 1

    fm, story_text = load_source_text(source_path)
    prompt = build_prompt(source_path, fm, story_text)
    print(prompt)
    return 0


def cmd_from_response(args: argparse.Namespace) -> int:
    """Keyless ingest: a classification JSON produced externally (an agent as
    the model) flows through the normal pipeline. Mirrors the entity_roster /
    research_expand --from-response pattern."""
    source_path = Path(args.source)
    if not source_path.is_absolute():
        source_path = REPO_DIR / source_path
    response_path = Path(args.from_response)
    try:
        raw_response = response_path.read_text(encoding="utf-8")
        result = extract_json(raw_response)
    except Exception as exc:  # noqa: BLE001
        print(
            "Error: could not parse response JSON: "
            + failure_metadata("classify-from-response", exc, provider="agent"),
            file=sys.stderr,
        )
        return 1
    return classify_file(
        source_path,
        model=args.model or "external-agent",
        dry_run=args.dry_run,
        verbose=getattr(args, "verbose", False),
        skip_candidates=args.no_candidates,
        precomputed_result=result,
    )


def emit_prompts(sources: list[Path], out_dir: Path) -> int:
    """Keyless batch path: write one classification prompt per source plus a
    manifest.json the agent works through via --from-response. Mirrors the
    entity_roster --emit-task pattern."""
    out_dir.mkdir(parents=True, exist_ok=True)
    items = []
    for source_path in sources:
        fm, story_text = load_source_text(source_path)
        if not story_text.strip():
            print(f"Warning: no story text found in {source_path}", file=sys.stderr)
            continue
        stem = classify_stem(source_path)
        prompt_file = out_dir / f"{stem}.prompt.md"
        write_text(prompt_file, build_prompt(source_path, fm, story_text))
        items.append({
            "source": _relative_path(source_path),
            "prompt": prompt_file.name,
            "response": f"{stem}.response.json",
        })
    manifest_path = out_dir / "manifest.json"
    write_json(manifest_path, {
        "task": "classify",
        "emitted_at": now_utc(),
        "ingest_command": (
            "python3 system/classify_story.py --from-response <response> --source <source>"
        ),
        "items": items,
    })
    print(f"✓ Emitted {len(items)} classification prompt(s) to {out_dir}")
    print(f"  Manifest: {manifest_path}")
    print("  For each item: write the classification JSON to <response>, then run the ingest_command.")
    return 0


def cmd_classify_all(args: argparse.Namespace) -> int:
    """Batch classify all (or unclassified) source files."""
    model = get_model(args)
    sources = all_source_files()

    if args.unclassified:
        sources = [s for s in sources if not is_classified(s)]
    if args.limit is not None:
        sources = sources[: max(0, args.limit)]

    if not sources:
        print("No source files to classify.")
        return 0

    if getattr(args, "emit_prompts", None):
        out_dir = Path(args.emit_prompts)
        if not out_dir.is_absolute():
            out_dir = REPO_DIR / out_dir
        return emit_prompts(sources, out_dir)

    action = "Previewing" if args.dry_run else "Classifying"
    print(f"{action} {len(sources)} source file(s) with model={model}")

    errors: list[str] = []
    for i, source_path in enumerate(sources, start=1):
        print(f"\n[{i}/{len(sources)}] {_relative_path(source_path)}")
        rc = classify_file(
            source_path,
            model,
            dry_run=args.dry_run,
            verbose=getattr(args, "verbose", False),
            skip_candidates=getattr(args, "no_candidates", False),
        )
        if rc != 0:
            errors.append(str(source_path))

    if errors:
        print(f"\n✗ {len(errors)} file(s) failed:")
        for e in errors:
            print(f"  {e}")
        return 1

    done_action = "Previewed" if args.dry_run else "Classified"
    print(f"\n✓ Done. {done_action} {len(sources) - len(errors)} file(s).")
    return 0


# ── CLI ───────────────────────────────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Classify Lifehug story sources with AI.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )

    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        "--classify",
        metavar="SOURCE_PATH",
        help="Classify a single source file.",
    )
    mode.add_argument(
        "--prompt",
        dest="prompt_file",
        metavar="SOURCE_PATH",
        help="Print the AI prompt only (no API call).",
    )
    mode.add_argument(
        "--classify-all",
        action="store_true",
        help="Batch classify source files.",
    )
    mode.add_argument(
        "--from-response",
        metavar="RESPONSE_JSON",
        help="Keyless: ingest an externally-produced classification JSON (requires --source).",
    )

    parser.add_argument(
        "--unclassified",
        action="store_true",
        help="With --classify-all: skip already-classified files.",
    )
    parser.add_argument(
        "--emit-prompts",
        metavar="DIR",
        help="With --classify-all: keyless agent path — write one prompt per "
             "pending source plus a manifest.json instead of calling AI.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        help="With --classify-all: maximum files to classify.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview actions without model calls or writes.",
    )
    parser.add_argument(
        "--model",
        default=None,
        help=f"Override the AI model (default: {DEFAULT_MODEL}).",
    )
    parser.add_argument(
        "--source",
        metavar="SOURCE_PATH",
        help="With --from-response: the source file the response classifies.",
    )
    parser.add_argument(
        "--no-candidates",
        action="store_true",
        help="Skip candidate-question generation (archive backfills).",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Extra diagnostic output.",
    )

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    if args.classify:
        return cmd_classify(args)
    if args.prompt_file:
        return cmd_prompt(args)
    if args.from_response:
        if not args.source:
            print("Error: --from-response requires --source <file>", file=sys.stderr)
            return 1
        return cmd_from_response(args)
    if args.classify_all:
        return cmd_classify_all(args)

    parser.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
