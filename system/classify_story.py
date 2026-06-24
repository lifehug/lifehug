#!/usr/bin/env python3
"""Classify ingested Lifehug stories using the Anthropic SDK.

Extracts entities, themes, story functions, and generates smart
candidate questions from any source file or answer file.

Modes
-----
--classify <source_path>          Classify a single file via AI.
--prompt <source_path>            Print the prompt only (no API call).
--classify-all [--unclassified]   Batch classify all (or only unclassified) sources.
--dry-run                         Preview actions without writing anything.

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
import os
import re
import sys
from pathlib import Path

# ── path bootstrapping so the script is importable from anywhere ──────────────
SYSTEM_DIR = Path(__file__).resolve().parent
if str(SYSTEM_DIR) not in sys.path:
    sys.path.insert(0, str(SYSTEM_DIR))

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
)

# ── constants ─────────────────────────────────────────────────────────────────
DEFAULT_MODEL = "claude-sonnet-4-20250514"
RESEARCH_FILE = SYSTEM_DIR / "research.md"

# Taxonomy themes for the AI prompt
THEME_TAXONOMY = [
    "hunger", "agency", "faith", "money", "belonging", "grief", "ambition",
    "identity", "family", "friendship", "love", "loss", "risk", "fear",
    "purpose", "work", "creativity", "race", "class", "migration",
    "education", "mentorship", "failure", "resilience", "legacy",
    "culture", "politics", "community", "health", "spirituality", "shame",
    "pride", "forgiveness", "betrayal", "justice", "freedom", "adventure",
    "solitude", "home", "nostalgia", "regret", "hope", "joy",
]


# ── Anthropic client ──────────────────────────────────────────────────────────

def get_client():
    """Return an Anthropic client, sourcing the key from env or config."""
    import anthropic  # local import keeps CLI importable without the package

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        config = load_config()
        api_key = config.get("anthropic_api_key")
    if not api_key:
        raise RuntimeError(
            "ANTHROPIC_API_KEY not set. "
            "Export it or add 'anthropic_api_key: ...' to config.yaml."
        )
    return anthropic.Anthropic(api_key=api_key)


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


def classify_stem(source_path: Path) -> str:
    """Return the classification file stem for a given source path."""
    return source_path.stem


def classification_path(source_path: Path) -> Path:
    return CLASSIFICATIONS_DIR / f"{classify_stem(source_path)}.json"


def is_classified(source_path: Path) -> bool:
    return classification_path(source_path).exists()


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


def build_prompt(source_path: Path, fm: dict, story_text: str) -> str:
    """Construct the full AI classification prompt for a source file."""
    mission = load_mission()
    research = RESEARCH_FILE.read_text(encoding="utf-8") if RESEARCH_FILE.exists() else ""
    categories_block = load_question_categories()
    story_functions_block = "\n".join(f"  - {sf}" for sf in STORY_FUNCTIONS)
    themes_block = ", ".join(THEME_TAXONOMY)

    relative_path = _relative_path(source_path)

    prompt = f"""You are a memoir analyst and oral history specialist helping to classify a personal story for the Lifehug memoir project.

## Lifehug Mission
{mission}

## Research Background (condensed)
{research[:3000]}

---

## Source File
Path: {relative_path}
Title: {fm.get('title', '(untitled)')}
Type: {fm.get('type', 'unknown')}
Captured at: {fm.get('captured_at', 'unknown')}

## Story Text
{story_text}

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
  "spotlight_opportunities": [
    {{
      "entity": "string",
      "type": "person|place|period|project|theme",
      "evidence_strength": "weak|moderate|strong",
      "reason": "string"
    }}
  ],
  "self_understanding_insights": ["list of patterns, beliefs, or values surfaced as plain strings"],
  "candidate_questions": [
    {{
      "text": "string — the actual question",
      "story_function": "one of: {', '.join(STORY_FUNCTIONS)}",
      "priority": 0.75,
      "reason": "why this question matters for the memoir",
      "target_category": "one of these category IDs or null — {', '.join(sorted(parse_categories(QUESTIONS_FILE.read_text(encoding='utf-8') if QUESTIONS_FILE.exists() else '').keys()))}"
    }}
  ]
}}

### Guidelines
- `people`: include every named or described person; estimate mention_count from how prominent they are
- `themes`: use only themes from the provided taxonomy (add new ones only if truly missing)
- `candidate_questions`: generate 3–8 high-quality follow-up questions
  - Draw on memoir methodology (StoryCorps, oral history, narrative therapy, We're Not Really Strangers)
  - Prioritize questions that deepen thin or unresolved areas
  - Assign story_function from the list: {', '.join(STORY_FUNCTIONS)}
  - Set priority between 0.4 (nice-to-have) and 0.95 (critical gap)
- `spotlight_opportunities`: entities rich enough to anchor a dedicated wiki page or chapter section
- `contradictions`: tensions or paradoxes in values, beliefs, or events — leave them unresolved, do not explain them away
- `possible_outputs`: concrete deliverables this story could contribute to

### Question bank categories for target_category:
{categories_block}

Respond with ONLY valid JSON. No prose, no markdown fences.
"""
    return prompt


# ── AI call ───────────────────────────────────────────────────────────────────

def extract_json(text: str) -> dict:
    """Extract a JSON object from the AI response text."""
    # Try direct parse first
    stripped = text.strip()
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        pass

    # Strip markdown code fences if present
    fence_match = re.search(r"```(?:json)?\s*([\s\S]+?)\s*```", stripped)
    if fence_match:
        try:
            return json.loads(fence_match.group(1))
        except json.JSONDecodeError:
            pass

    # Find the first { ... } block
    brace_match = re.search(r"\{[\s\S]+\}", stripped)
    if brace_match:
        try:
            return json.loads(brace_match.group(0))
        except json.JSONDecodeError:
            pass

    raise ValueError(f"Could not extract JSON from AI response (first 200 chars): {stripped[:200]}")


def classify_with_ai(prompt: str, model: str = DEFAULT_MODEL) -> dict:
    """Send the prompt to Anthropic and return the parsed classification dict."""
    client = get_client()
    response = client.messages.create(
        model=model,
        max_tokens=4096,
        messages=[{"role": "user", "content": prompt}],
    )
    text = response.content[0].text
    return extract_json(text)


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
        "spotlight_opportunities": ai_result.get("spotlight_opportunities", []),
        "self_understanding_insights": ai_result.get("self_understanding_insights", []),
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
    spotlights = classification.get("spotlight_opportunities", [])
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
    if spotlights:
        spot_names = ", ".join(s.get("entity", "?") for s in spotlights[:4])
        print(f"  spotlts : {spot_names}")
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
) -> int:
    """Classify a single source file. Returns 0 on success, 1 on error."""
    if not source_path.exists():
        print(f"Error: file not found: {source_path}", file=sys.stderr)
        return 1

    fm, story_text = load_source_text(source_path)

    if not story_text.strip():
        print(f"Warning: no story text found in {source_path}", file=sys.stderr)
        return 1

    prompt = build_prompt(source_path, fm, story_text)

    if verbose:
        print(f"[verbose] calling model={model} for {source_path}")

    try:
        ai_result = classify_with_ai(prompt, model=model)
    except Exception as exc:
        print(f"Error: AI classification failed for {source_path}: {exc}", file=sys.stderr)
        return 1

    classified_at = now_utc()

    # Build candidate records
    store = load_candidate_store()
    ai_questions = ai_result.get("candidate_questions", [])
    new_candidates = build_candidates(ai_questions, source_path, store, classified_at)

    candidate_ids = [c["id"] for c in new_candidates]
    classification = build_classification(
        source_path, fm, ai_result, model, classified_at, candidate_ids
    )

    clf_path = classification_path(source_path)

    if dry_run:
        print(f"[dry-run] would write classification: {clf_path}")
        print(f"[dry-run] would add {len(new_candidates)} candidate question(s)")
        print_summary(classification, new_candidates)
        return 0

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


def cmd_classify_all(args: argparse.Namespace) -> int:
    """Batch classify all (or unclassified) source files."""
    model = get_model(args)
    sources = all_source_files()

    if args.unclassified:
        sources = [s for s in sources if not is_classified(s)]

    if not sources:
        print("No source files to classify.")
        return 0

    print(f"Classifying {len(sources)} source file(s) with model={model}")

    errors: list[str] = []
    for i, source_path in enumerate(sources, start=1):
        print(f"\n[{i}/{len(sources)}] {_relative_path(source_path)}")
        rc = classify_file(
            source_path,
            model,
            dry_run=args.dry_run,
            verbose=getattr(args, "verbose", False),
        )
        if rc != 0:
            errors.append(str(source_path))

    if errors:
        print(f"\n✗ {len(errors)} file(s) failed:")
        for e in errors:
            print(f"  {e}")
        return 1

    print(f"\n✓ Done. Classified {len(sources) - len(errors)} file(s).")
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

    parser.add_argument(
        "--unclassified",
        action="store_true",
        help="With --classify-all: skip already-classified files.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview actions without writing files.",
    )
    parser.add_argument(
        "--model",
        default=None,
        help=f"Override the AI model (default: {DEFAULT_MODEL}).",
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
    if args.classify_all:
        return cmd_classify_all(args)

    parser.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
