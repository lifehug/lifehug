#!/usr/bin/env python3
"""Lifehug — Research Neighborhood Expander

Generates output-oriented question neighborhoods — clusters of 6-12 questions that
build toward a tangible deliverable (chapter, letter, essay, blog post, social post).

Modes:
    --expand <path>         Expand from a wiki page, answer file, or source file
    --topic <name>          Expand from a named topic
      --type <kind>         Topic type: person|place|time_period|project|theme|event
    --gaps                  Auto-detect thin areas and suggest neighborhood-openers
    --prompt                Output the AI prompt only (no API call)
    --dry-run               Preview without writing anything
    --output <fmt>          Target output: chapter|letter|essay|post (default: chapter)
    --model <model>         Override the AI model
    --force                 Recreate neighborhood even if it already exists

Examples:
    python3 system/research_expand.py --expand wiki/people/mom.md
    python3 system/research_expand.py --topic "7th grade" --type time_period --output chapter
    python3 system/research_expand.py --topic "faith" --type theme --output essay
    python3 system/research_expand.py --topic "Dad" --type person --output letter
    python3 system/research_expand.py --gaps
    python3 system/research_expand.py --gaps --dry-run
    python3 system/research_expand.py --prompt --topic "Dad" --type person
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

# Ensure system dir is on the path when run directly
_SYSTEM_DIR = Path(__file__).resolve().parent
if str(_SYSTEM_DIR) not in sys.path:
    sys.path.insert(0, str(_SYSTEM_DIR))

from ai_provider import (
    AIResponseError,
    ai_available,
    call_ai,
    failure_metadata,
    get_anthropic_client,
    model_is_kimi,
    normalize_question_records,
)
from lifehug_core import (
    ANSWERS_DIR,
    CLASSIFICATIONS_DIR,
    MANUAL_SOURCES_DIR,
    MISSION_FILE,
    NEIGHBORHOODS_FILE,
    QUESTION_CANDIDATES_FILE,
    QUESTIONS_FILE,
    REPO_DIR,
    STATE_DIR,
    STORY_FUNCTIONS,
    WIKI_DIR,
    answer_body,
    answer_id_from_filename,
    load_config,
    load_mission,
    now_utc,
    parse_categories,
    parse_questions,
    read_json,
    slugify,
    write_json,
)
from neighborhoods import apply_readiness
from question_judgment import load_judgment_rubric

__all__ = ["ai_available", "call_ai", "get_client", "model_is_kimi"]

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Non-dated alias — tracks the current Opus tier instead of pinning a snapshot
# that ages out. Override with `research_model` in config.yaml.
DEFAULT_MODEL = "claude-opus-4-8"
VALID_OUTPUT_TYPES = ("chapter", "letter", "essay", "post", "profile")
VALID_TOPIC_TYPES = ("person", "place", "time_period", "project", "theme", "event", "self", "relationship")

# Arc story functions — the spine of a neighborhood. The arc is chosen by topic
# type: most topics use the memoir arc, but self-knowledge and relational
# (dyadic) topics get arcs built for escalating self-disclosure.
MEMOIR_ARC = (
    ("foundation", "establishes context, baseline facts, setting"),
    ("scene", "specific vivid moment, sensory detail, dialogue"),
    ("tension", "conflict, stakes, uncertainty, difficulty"),
    ("turning_point", "the moment things changed; decision; revelation"),
    ("relationship", "how this topic intersects with key people"),
    ("meaning", "reflection, retrospective insight, what it means now"),
)
SELF_ARC = (
    ("self_image", "the story you tell about who you are"),
    ("value", "what you most care about; the principle under the choice"),
    ("fear", "what you avoid, dread, or protect against"),
    ("contradiction", "where your actions and your self-image disagree"),
    ("perception_by_others", "how others see you — and the gap with how you see yourself"),
    ("growth_edge", "who you are becoming; the change you're working toward"),
)
RELATIONSHIP_ARC = (
    ("who_they_are", "who this person is in your eyes, beyond their role"),
    ("shared_history", "the moments that defined your bond"),
    ("tension", "the friction, distance, or unspoken difficulty between you"),
    ("what_i_see_in_them", "what you admire or notice that they may not"),
    ("what_i_want_them_to_know", "the thing you'd most want to say to them"),
    ("how_they_see_me", "how you think they see you — and whether it's accurate"),
)
# Time-period arc (v71) — the synthesized six-step chapter method:
# McAdams (name & bound), Levinson (life structure + the Dream), oral
# history (typical day, era anchors), McAdams five-slot scenes, Bridges
# (ending → neutral zone → beginning), Butler (evaluative integration).
PERIOD_ARC = (
    ("foundation", "name and bound the chapter — what would you title it, how did it begin, and how did it end"),
    ("meaning", "the life structure of those years — the pillars (work, relationships, home, a guiding Dream), which was the keystone, what was neglected"),
    ("scene", "a typical day, waking to sleeping — where you lived, what things cost, the car, the music, the rooms"),
    ("turning_point", "the key scenes — a high point, a low point, a turning point, each with what happened / where / who / what you felt / what it says about you"),
    ("tension", "the transition out — what happened, AND when it ended inside you; what you let go of; the in-between stretch when the old life was gone but the new hadn't started"),
    ("meaning", "the later look back — how you make peace with that chapter now, and what it gave you that you only see from here"),
)
ARCS = {"self": SELF_ARC, "relationship": RELATIONSHIP_ARC, "time_period": PERIOD_ARC}

# ---------------------------------------------------------------------------
# Interview packs (v72, Tier 3 — on demand only, never scheduled).
# Questions the AUTHOR asks the other person directly, StoryCorps-style —
# organized by relationship type (mirroring the Great Questions lists).
# The conversation records/ingests back via `ingest-story --witness <person>`.
# ---------------------------------------------------------------------------

INTERVIEW_BANKS: dict[str, list[str]] = {
    "parent": [
        "What do you remember about the day I was born?",
        "What was your life like right before you became a parent — who were you then?",
        "What's something about your own childhood I'd be surprised by?",
        "What was the hardest season of raising me, and what got you through it?",
        "What did your parents do that you promised yourself you'd do differently?",
        "What's a moment with me you find yourself returning to?",
        "What do you know now about being a parent that you wish someone had told you?",
        "What's something you've always wanted to tell me but never quite have?",
        "How do you want to be remembered?",
    ],
    "grandparent": [
        "Where did our family come from — what's the oldest family story you know?",
        "What was a typical day like when you were my age?",
        "What did things cost then — and what was the first big thing you saved for?",
        "How did you and Grandpa/Grandma meet? Tell it the long way.",
        "What was the hardest thing your generation lived through, from where you stood?",
        "Which of your parents do you see in yourself — and in me?",
        "What's something you made or built that you were proud of?",
        "What do you want your great-grandchildren to know about you?",
    ],
    "spouse": [
        "What did you first assume about me that turned out to be wrong?",
        "When did you know — actually know — about us?",
        "What's a hard season of ours you're proud of how we survived?",
        "What do I do that quietly drives you crazy — and what do I do that quietly holds you up?",
        "What dream have you never fully said out loud?",
        "What are you most worried about right now?",
        "What do you hope the kids take from how we love each other?",
    ],
    "child": [
        "What's your earliest memory — the very first thing you can see?",
        "What's something you think I don't understand about being you right now?",
        "What's a time I embarrassed you — and a time I made you proud?",
        "What do you want to be like when you're my age?",
        "If you could keep one day we've had together forever, which one?",
        "What's something you're scared to tell me you're scared of?",
    ],
    "sibling": [
        "What's your version of the story I always tell about us?",
        "What was our house actually like from where you stood?",
        "What did you envy about me — and what do you think I envied about you?",
        "When did we feel most like a team?",
        "What do you remember about Mom and Dad that I might have missed?",
        "What's something you've forgiven me for that I never apologized for?",
    ],
    "mentor": [
        "What did you see in me back then that made you invest the time?",
        "What was I like to work with — honestly?",
        "What's the advice you gave me that you most hoped would stick?",
        "Who mentored you, and what did you carry forward from them?",
        "What should I be paying attention to in the next ten years?",
    ],
    "cofounder": [
        "What did you first assume about me that turned out to be wrong?",
        "What was the moment you almost quit — and what kept you in?",
        "Which decision do you still think we got wrong, and does it matter now?",
        "What's the story of us you tell people when I'm not in the room?",
        "What did building this cost you that you've never fully said?",
        "What do you hope this thing outlives?",
    ],
    "friend": [
        "What's the first thing you remember about meeting me?",
        "What's a side of me you see that my family probably doesn't?",
        "When did our friendship almost break — and why didn't it?",
        "What's something we did that you'd never tell either of our spouses?",
        "What do you count on me for?",
    ],
    "remembering": [
        "Tell me about them the way you'd want a stranger to know them.",
        "What did their voice sound like? What did they always say?",
        "What's a moment with them you find yourself returning to?",
        "What did they teach you without ever saying it out loud?",
        "What would they make of your life now?",
        "What do you wish you'd asked them?",
    ],
}


def build_interview_pack(person: str, relationship: str) -> str:
    """A forwardable question pack for a real conversation with `person`.
    On demand only; the recording ingests via `ingest-story --witness`."""
    bank = INTERVIEW_BANKS.get(relationship, INTERVIEW_BANKS["friend"])
    lines = [
        f"🎙 Interview pack — {person} ({relationship})",
        "",
        "Not a checklist — pick the ones that open windows and skip the rest.",
        "Let silence work. Ask for a specific example whenever you get a general",
        "answer. Don't interrupt tangents; tangents are where the good stuff lives.",
        "",
    ]
    for i, question in enumerate(bank, 1):
        lines.append(f"  {i}. {question}")

    # Personalize from the wiki: this person's page gaps become themes to chase.
    slug = slugify(person)
    page_candidates = [
        WIKI_DIR / "people" / f"{slug}.md",
        *(sorted((WIKI_DIR / "relationships").glob(f"*{slug}*.md")) if (WIKI_DIR / "relationships").exists() else []),
    ]
    for page in page_candidates:
        if not page.exists():
            continue
        text = page.read_text(encoding="utf-8", errors="replace")
        section = re.search(r"^## Open Questions\n(.*?)(?=^## |\Z)", text, re.MULTILINE | re.DOTALL)
        if not section:
            continue
        gaps = [ln.strip().lstrip("-*").strip() for ln in section.group(1).splitlines()
                if ln.strip().lstrip("-*").strip()]
        if gaps:
            lines += ["", f"Specific to your story (gaps on their wiki page, {page.name}):"]
            lines += [f"  • {g}" for g in gaps[:4]]
        break

    lines += [
        "",
        "Afterwards, save their words (voice memo transcript, notes, anything):",
        f'  printf \'%s\' "$THEIR_WORDS" | python3 system/lifehug.py ingest-story --witness "{person}"',
    ]
    return "\n".join(lines)


def arc_for(topic_type: str = "") -> tuple[tuple[str, str], ...]:
    return ARCS.get(topic_type, MEMOIR_ARC)


# Backward-compatible default (memoir) arc function names.
ARC_FUNCTIONS = tuple(fn for fn, _ in MEMOIR_ARC)

# Gap-detection thresholds
GAP_COVERAGE_THRESHOLD = 0.30   # < 30% = thin
GAP_PERSON_MENTION_MIN = 3       # mentioned ≥ 3 times but no Focus → flag

# ---------------------------------------------------------------------------
# Gap detection keyword maps
# ---------------------------------------------------------------------------

TIME_PERIOD_KEYWORDS: dict[str, list[str]] = {
    "early_childhood":    ["childhood", "toddler", "preschool", "kindergarten", "elementary",
                           "grew up", "growing up", "little kid", "young child"],
    "middle_school":      ["middle school", "junior high", "6th grade", "7th grade", "8th grade",
                           "11 years old", "12 years old", "13 years old"],
    "high_school":        ["high school", "9th grade", "10th grade", "11th grade", "12th grade",
                           "teenager", "14 years old", "15 years old", "16 years old",
                           "17 years old", "18 years old", "prom", "homecoming"],
    "college":            ["college", "university", "freshman", "sophomore", "junior year",
                           "senior year", "campus", "dorm", "frat", "sorority", "grad school",
                           "undergraduate"],
    "early_career":       ["first job", "entry level", "junior", "internship", "new hire",
                           "just starting out", "20s", "early career", "after college"],
    "mid_career":         ["senior role", "manager", "director", "startup", "founded",
                           "co-founder", "raised money", "vc", "30s", "promotion"],
    "parenthood":         ["became a parent", "first child", "having kids", "pregnancy",
                           "newborn", "baby", "son was born", "daughter was born", "fatherhood",
                           "motherhood", "raising kids"],
    "recent":             ["recently", "last year", "now", "today", "currently", "lately",
                           "these days", "this year"],
}

FAMILY_KEYWORDS: dict[str, list[str]] = {
    "mom":       ["mom", "mother", "mama", "ma ", "my mom", "my mother"],
    "dad":       ["dad", "father", "papa", "my dad", "my father", "pop "],
    "brother":   ["brother", "my brother", "bro "],
    "sister":    ["sister", "my sister", "sis "],
    "grandma":   ["grandma", "grandmother", "nana", "gran ", "granny"],
    "grandpa":   ["grandpa", "grandfather", "pops", "papa", "gramps"],
    "wife":      ["wife", "my wife", "spouse", "partner"],
    "husband":   ["husband", "my husband"],
    "son":       [" son ", "my son", "my boy"],
    "daughter":  ["daughter", "my daughter", "my girl"],
}

THEME_KEYWORDS: dict[str, list[str]] = {
    "faith":        ["faith", "church", "god ", "prayer", "religious", "spiritual",
                     "bible", "belief", "worship", "pastor", "priest", "monk",
                     "meditat", "buddhis", "christianit", "muslim", "jew"],
    "money":        ["money", "poor", "rich", "broke", "debt", "salary", "income",
                     "financial", "afford", "poverty", "wealth", "savings", "budget"],
    "belonging":    ["belong", "outsider", "fit in", "accepted", "rejected", "community",
                     "identity", "culture", "immigrant", "foreigner", "home"],
    "grief":        ["grief", "loss", "died", "death", "funeral", "mourning", "miss them",
                     "passed away", "cancer", "illness", "terminal", "devastat"],
    "ambition":     ["ambition", "goal", "dream", "driven", "achieve", "success",
                     "career", "climb", "hustle", "grind", "accomplish"],
    "fear":         ["afraid", "fear", "scared", "anxiety", "terrified", "panic",
                     "worried", "dread", "phobia", "nervous"],
    "love":         ["fell in love", "romance", "relationship", "dating", "first love",
                     "heartbreak", "breakup", "marriage", "wedding", "divorce"],
    "philosophy":   ["meaning", "purpose", "existential", "why are we", "philosophy",
                     "absurd", "stoic", "values", "ethics", "moral"],
    "identity":     ["who am i", "identity", "race", "ethnicity", "gender",
                     "sexuality", "orientation", "culture", "heritage"],
    "creativity":   ["creative", "art", "music", "writing", "painting", "design",
                     "craft", "make things", "build", "compose", "invent"],
    # Birren's Guided Autobiography themes most banks under-cover — high-yield
    # domains a life story is incomplete without (v70). Money/faith already above.
    "health_and_body": ["health", "sick", "illness", "injur", "hospital", "surgery",
                        "body", "weight", "diagnos", "chronic", "pain", "doctor",
                        "fitness", "workout", "aging", "energy"],
    "death_and_mortality": ["mortality", "own death", "dying", "deathbed", "legacy",
                            "when i die", "when i'm gone", "funeral", "bury", "afterlife",
                            "time left", "running out of time"],
}

# Backward-compatible name for callers that previously imported this helper
# from research_expand. Provider construction now lives in ai_provider.
get_client = get_anthropic_client


# ---------------------------------------------------------------------------
# Neighborhood store helpers
# ---------------------------------------------------------------------------


def load_neighborhoods() -> dict:
    data = read_json(NEIGHBORHOODS_FILE, default=None)
    if not isinstance(data, dict):
        return {"version": 1, "neighborhoods": []}
    data.setdefault("version", 1)
    data.setdefault("neighborhoods", [])
    return data


def save_neighborhoods(data: dict) -> None:
    data["last_updated"] = now_utc()
    write_json(NEIGHBORHOODS_FILE, data)


def find_neighborhood(data: dict, nbhd_id: str) -> dict | None:
    for nbhd in data.get("neighborhoods", []):
        if nbhd.get("id") == nbhd_id:
            return nbhd
    return None


def make_arc(topic_type: str = "") -> list[dict]:
    """Create an empty arc with the story-function slots for this topic type."""
    return [
        {"story_function": fn, "question_id": None, "status": "pending"}
        for fn, _ in arc_for(topic_type)
    ]


def compute_completeness(arc: list[dict]) -> float:
    """Legacy fraction of arc slots that have a generated question candidate."""
    if not arc:
        return 0.0
    filled = sum(1 for slot in arc if slot.get("question_id") is not None)
    return round(filled / len(arc), 3)


def neighborhood_id_for(title: str) -> str:
    return f"nbhd-{slugify(title)}"


# ---------------------------------------------------------------------------
# Candidate store helpers
# ---------------------------------------------------------------------------


def load_candidates() -> dict:
    data = read_json(QUESTION_CANDIDATES_FILE, default=None)
    if not isinstance(data, dict):
        return {"version": 1, "candidates": []}
    data.setdefault("version", 1)
    data.setdefault("candidates", [])
    return data


def save_candidates(data: dict) -> None:
    data["last_updated"] = now_utc()
    write_json(QUESTION_CANDIDATES_FILE, data)


def next_candidate_id(candidates: list[dict], slug: str) -> str:
    prefix = f"cand-{slug}-"
    existing = [c["id"] for c in candidates if c.get("id", "").startswith(prefix)]
    max_n = 0
    for cid in existing:
        tail = cid[len(prefix):]
        if tail.isdigit():
            max_n = max(max_n, int(tail))
    return f"{prefix}{max_n + 1}"


def add_candidates_from_ai(
    candidates_data: dict,
    ai_questions: list[dict],
    neighborhood_id: str,
    source_path: str,
) -> list[str]:
    """Append AI-generated questions to the candidate store. Return new IDs."""
    candidates = candidates_data["candidates"]
    slug = slugify(neighborhood_id.removeprefix("nbhd-"))
    new_ids: list[str] = []

    for q in ai_questions:
        text = str(q.get("text", "")).strip()
        if not text:
            continue
        story_fn = q.get("story_function", "")
        if story_fn not in STORY_FUNCTIONS:
            story_fn = "scene"
        priority = float(q.get("priority", 0.5))
        priority = max(0.0, min(1.0, priority))
        reason = str(q.get("reason", "")).strip()

        cand_id = next_candidate_id(candidates, slug)
        candidate = {
            "id": cand_id,
            "text": text,
            "source_path": source_path,
            "kind": story_fn,
            "priority": priority,
            "reason": reason,
            "status": "candidate",
            "story_function": story_fn,
            "neighborhood_id": neighborhood_id,
            "created_at": now_utc(),
        }
        candidates.append(candidate)
        new_ids.append(cand_id)

    return new_ids


# ---------------------------------------------------------------------------
# Content loading helpers
# ---------------------------------------------------------------------------


def load_answers() -> list[dict]:
    """Load all answer files. Returns list of {id, path, body}."""
    answers = []
    if not ANSWERS_DIR.exists():
        return answers
    for fpath in sorted(ANSWERS_DIR.glob("*.md")):
        try:
            content = fpath.read_text(encoding="utf-8")
            qid = answer_id_from_filename(fpath) or fpath.stem
            body = answer_body(content)
            answers.append({"id": qid, "path": str(fpath), "body": body})
        except Exception:
            continue
    return answers


def load_wiki_pages(topic_lower: str = "", topic_type: str = "") -> list[dict]:
    """Load wiki pages relevant to a topic. Returns list of {path, content}."""
    pages = []
    if not WIKI_DIR.exists():
        return pages

    # Determine candidate directories based on topic_type
    type_to_dir = {
        "person":      WIKI_DIR / "people",
        "place":       WIKI_DIR / "places",
        "time_period": WIKI_DIR / "periods",
        "project":     WIKI_DIR / "projects",
        "theme":       WIKI_DIR / "themes",
        "event":       WIKI_DIR / "periods",  # events can be in periods or objects
        "relationship": WIKI_DIR / "people",  # dyadic topics pull the person's page
        "self":        WIKI_DIR / "self",
    }

    search_dirs: list[Path] = []
    if topic_type in type_to_dir:
        search_dirs.append(type_to_dir[topic_type])
    else:
        # Search all dirs
        search_dirs = [d for d in WIKI_DIR.iterdir() if d.is_dir()]

    for search_dir in search_dirs:
        if not search_dir.exists():
            continue
        for fpath in sorted(search_dir.glob("*.md")):
            if fpath.stat().st_size == 0:
                continue
            stem_lower = fpath.stem.lower().replace("-", " ").replace("_", " ")
            # Include if topic matches stem or topic is empty (get all)
            if not topic_lower or topic_lower in stem_lower or stem_lower in topic_lower:
                try:
                    content = fpath.read_text(encoding="utf-8")
                    pages.append({"path": str(fpath.relative_to(REPO_DIR)), "content": content})
                except Exception:
                    continue
    return pages


def load_source_file(path: Path) -> str:
    """Load a source/wiki/answer file and return its body text."""
    if not path.exists():
        return ""
    try:
        content = path.read_text(encoding="utf-8")
        # If it looks like an answer file, extract the body
        if "---" in content:
            return answer_body(content)
        return content
    except Exception:
        return ""


# ---------------------------------------------------------------------------
# Gap detection
# ---------------------------------------------------------------------------


def detect_gaps(answers: list[dict]) -> dict:
    """
    Heuristic gap analysis across time periods, family members, and themes.
    Returns structured gap report.
    """
    all_text = " ".join(a["body"].lower() for a in answers)
    total_answers = len(answers)

    # --- Time period coverage ---
    period_counts: dict[str, int] = {}
    for period, keywords in TIME_PERIOD_KEYWORDS.items():
        count = sum(
            1 for a in answers
            if any(kw in a["body"].lower() for kw in keywords)
        )
        period_counts[period] = count

    # --- Family coverage ---
    family_counts: dict[str, int] = {}
    for person, keywords in FAMILY_KEYWORDS.items():
        count = sum(
            1 for a in answers
            if any(kw in a["body"].lower() for kw in keywords)
        )
        family_counts[person] = count

    # --- Theme coverage ---
    theme_counts: dict[str, int] = {}
    for theme, keywords in THEME_KEYWORDS.items():
        count = sum(
            1 for a in answers
            if any(kw in a["body"].lower() for kw in keywords)
        )
        theme_counts[theme] = count

    # --- Build gap lists ---
    thin_periods: list[dict] = []
    for period, count in period_counts.items():
        ratio = count / total_answers if total_answers else 0.0
        if ratio < GAP_COVERAGE_THRESHOLD:
            thin_periods.append({
                "key": period,
                "label": period.replace("_", " ").title(),
                "mentions": count,
                "coverage": round(ratio, 3),
            })

    thin_themes: list[dict] = []
    for theme, count in theme_counts.items():
        ratio = count / total_answers if total_answers else 0.0
        if ratio < GAP_COVERAGE_THRESHOLD:
            thin_themes.append({
                "key": theme,
                "label": theme.replace("_", " ").title(),
                "mentions": count,
                "coverage": round(ratio, 3),
            })

    # Family: flag people mentioned ≥3 times who appear to have no wiki Focus page
    unfocused_family: list[dict] = []
    for person, count in family_counts.items():
        if count >= GAP_PERSON_MENTION_MIN:
            # Check if there's a wiki page for them
            wiki_people = WIKI_DIR / "people"
            has_wiki = any(
                p for p in wiki_people.glob("*.md")
                if person in p.stem.lower() and p.stat().st_size > 0
            ) if wiki_people.exists() else False
            if not has_wiki:
                unfocused_family.append({
                    "key": person,
                    "label": person.replace("_", " ").title(),
                    "mentions": count,
                    "has_wiki": False,
                })

    return {
        "total_answers": total_answers,
        "thin_periods": sorted(thin_periods, key=lambda x: x["mentions"]),
        "thin_themes": sorted(thin_themes, key=lambda x: x["mentions"]),
        "unfocused_family": sorted(unfocused_family, key=lambda x: -x["mentions"]),
    }


# ---------------------------------------------------------------------------
# AI Prompt construction
# ---------------------------------------------------------------------------


def load_classified_self_signals(limit: int = 12) -> list[str]:
    """Contradictions and self-understanding insights the weekly classifier
    extracted from real answers. These fields were write-only until v69 —
    they now ground the self-arc in observed patterns instead of generic
    introspection ('You say no one is coming to save you, but you list four
    people who saved you' beats 'what contradictions do you carry?')."""
    from lifehug_core import CLASSIFICATIONS_DIR  # noqa: PLC0415

    signals: list[str] = []
    seen: set[str] = set()
    if not CLASSIFICATIONS_DIR.exists():
        return signals
    for path in sorted(CLASSIFICATIONS_DIR.glob("*.json")):
        data = read_json(path, default={}) or {}
        for key, prefix in (("contradictions", "contradiction"), ("self_understanding_insights", "insight")):
            for item in data.get(key, []) or []:
                text = str(item.get("description", item) if isinstance(item, dict) else item).strip()
                if not text or text.lower() in seen:
                    continue
                seen.add(text.lower())
                signals.append(f"[{prefix}] {text}")
    return signals[-limit:]  # most recent classifications last → keep the freshest


def build_expansion_prompt(
    *,
    topic: str,
    topic_type: str,
    target_output: str,
    mission: str,
    source_content: str,
    relevant_answers: list[dict],
    question_bank_categories: str,
    research_notes: str = "",
    self_signals: list[str] | None = None,
) -> str:
    """Build the full AI prompt for neighborhood expansion."""
    output_guidance = {
        "chapter": (
            "a memoir chapter (3-8 pages). The questions should collectively surface "
            "vivid scenes, key tensions, turning points, and reflections that give a "
            "ghostwriter enough material to draft one complete chapter."
        ),
        "letter": (
            "a personal letter to or about this person/topic. The questions should "
            "surface specific memories, things left unsaid, expressions of love or "
            "gratitude, honest reflections, and what this person means to the author."
        ),
        "essay": (
            "a reflective essay (1,500-3,000 words). The questions should build toward "
            "a through-line — a central insight or argument — with supporting scenes "
            "and honest reflection."
        ),
        "post": (
            "a personal blog post or social post (500-1,000 words). The questions should "
            "surface one compelling story or insight, told crisply and personally."
        ),
    }.get(target_output, "a memoir chapter")

    lines = []
    lines.append("=" * 70)
    lines.append(f"LIFEHUG — RESEARCH EXPANSION: {topic.upper()}")
    lines.append("=" * 70)
    lines.append("")

    lines.append("## MISSION")
    lines.append(mission.strip() if mission else "(no mission loaded)")
    lines.append("")

    lines.append("## YOUR TASK")
    lines.append(f"Generate 8-12 questions for a Lifehug neighborhood about: **{topic}**")
    lines.append(f"Topic type: {topic_type}")
    lines.append(f"Target output: {target_output} — {output_guidance}")
    lines.append("")
    lines.append("These questions form an **output-oriented arc**. The author should be able to")
    lines.append("answer them over 1-2 weeks and emerge with enough raw material to produce")
    lines.append(f"the target output: {target_output}.")
    lines.append("")

    arc = arc_for(topic_type)
    lines.append("## ARC STRUCTURE")
    lines.append("Map your questions to these story functions (at least one per function):")
    for fn, desc in arc:
        lines.append(f"  {fn:22} — {desc}")
    if topic_type not in ARCS:
        lines.append("You may also use: contradiction, output_gap")
    lines.append("")

    lines.append("## QUESTION DESIGN PRINCIPLES")
    lines.append("Draw from proven conversation-starter methodologies:")
    lines.append("  - StoryCorps oral history: open-ended, specific, sensory")
    lines.append("  - We're Not Really Strangers: vulnerable, emotionally honest")
    lines.append("  - 36 Questions (Aron): escalating intimacy, self-disclosure")
    lines.append("  - School of Life: philosophical self-examination")
    lines.append("  - Table Topics: unexpected angles, interesting specifics")
    lines.append("  - Narrative therapy: reframing, agency, alternative stories")
    lines.append("  - Faith/spirituality prompts: meaning, transcendence, values")
    lines.append("")
    lines.append("Craft rules (hard requirements):")
    lines.append("  - Two-sentence rule: at most one sentence of context, then ONE open question.")
    lines.append("  - 'What'/'When'/'Tell me about', never 'Why', for the author's own feelings.")
    lines.append("  - Include at least one from these high-yield families where the topic allows:")
    lines.append("    typical-day reconstruction ('walk me through a typical Tuesday, waking to sleeping');")
    lines.append("    era anchors (what things cost, the car, the music, the house room by room);")
    lines.append("    photo/song cue ('what song puts you back there? where were you when you heard it?');")
    lines.append("    perspective-taking ('tell that story the way [person] would tell it');")
    lines.append("    off-script probe ('which milestone did NOT go the way the script says?');")
    lines.append("    forgiveness/blessing ('what do you wish for them that you've never said out loud?').")
    lines.append("  - For heavy themes (death, loss, shame): never open cold — one gentle framing")
    lines.append("    sentence first, and offer a distanced variant (fly-on-the-wall, or 'when")
    lines.append("    you're 80, what will this mean?') rather than only digging in.")
    lines.append("")

    # Personalization hints from the quality profile (only when active).
    try:
        from quality_profile import load_profile  # noqa: PLC0415
        _profile = load_profile()
        if _profile.get("active") and _profile.get("top_patterns"):
            lines.append("## PERSONALIZATION INSIGHTS")
            lines.append("Based on this author's answer history, questions that produce richer responses:")
            for _pattern in _profile["top_patterns"][:3]:
                lines.append(f"  - {_pattern}")
            lines.append("Lean toward these patterns when choosing framing and story functions.")
            lines.append("")

    except Exception:  # noqa: BLE001
        pass  # never break prompt generation

    if self_signals:
        lines.append("## OBSERVED PATTERNS IN THIS AUTHOR (from classified answers)")
        lines.append("The weekly classifier extracted these contradictions and self-understanding")
        lines.append("insights from the author's real answers. Ground your questions in THESE —")
        lines.append("a question that names the author's actual tension cuts far deeper than a")
        lines.append("generic introspective prompt. Quote or paraphrase them where it helps.")
        for signal in self_signals:
            lines.append(f"  - {signal}")
        lines.append("")

    if topic_type == "self":
        lines.append("## SELF-KNOWLEDGE MODE")
        lines.append("This is NOT a memoir arc — the deliverable is self-understanding, not a story.")
        lines.append("Goal: help the author see patterns, values, fears, and contradictions they")
        lines.append("haven't yet articulated. Lean hard into:")
        lines.append("  - Internal Family Systems / parts work: 'a part of you that...'")
        lines.append("  - 36 Questions + WNRS: escalating, genuinely vulnerable self-disclosure")
        lines.append("  - Perception gap: how others see you vs. how you see yourself")
        lines.append("  - Honest contradiction: where your stated values and actions diverge")
        lines.append("Each question should go one layer deeper than the last (progressive disclosure).")
        lines.append("")
    elif topic_type == "relationship":
        lines.append("## RELATIONAL (DYADIC) MODE")
        lines.append("The deliverable centers on the bond between the author and this person.")
        lines.append("Ask from BOTH sides of the relationship:")
        lines.append("  - what the author sees, admires, fears, or resents")
        lines.append("  - what the author imagines this person feels or sees in return")
        lines.append("  - what has gone unsaid, and what the author would want them to know")
        lines.append("Surface perception gaps and the things that are hard to say out loud.")
        lines.append("")
    elif topic_type == "time_period":
        lines.append("## LIFE-CHAPTER MODE")
        lines.append("This period is a CHAPTER of a life, not a list of facts. Follow the arc order:")
        lines.append("bound it → its life structure → a typical day with era texture → key scenes →")
        lines.append("the transition out (including the inner ending and the neutral-zone stretch")
        lines.append("between lives — the richest under-captured memoir material) → the later look back.")
        lines.append("Dating rule: NEVER ask 'what year was that?' — use landmark anchors instead")
        lines.append("('was that before or after the move? was [child] born yet?').")
        lines.append("")
    lines.append("Principles:")
    lines.append("  1. Never yes/no — always open-ended ('Tell me about...')")
    lines.append("  2. Sensory — 'What did it look like? Sound like? Smell like?'")
    lines.append("  3. Specific moment — 'Think of one time when...' not 'In general...'")
    lines.append("  4. Emotional anchor — 'What were you feeling when that happened?'")
    lines.append("  5. Contrast — 'How was that different from what you expected?'")
    lines.append("  6. Dialogue — 'What did they say? What did you say back?'")
    lines.append("  7. Unexpected angle — avoid the obvious question; go deeper")
    lines.append("  8. Progressive disclosure — each question should feel like it could")
    lines.append("     only be asked once you already know the answer to the previous one")
    lines.append("")

    if source_content:
        lines.append("## EXISTING CONTENT (wiki page / source file)")
        lines.append(source_content.strip()[:2000])
        if len(source_content) > 2000:
            lines.append("... [truncated]")
        lines.append("")

    if relevant_answers:
        lines.append("## RELEVANT EXISTING ANSWERS")
        lines.append("(These answers already exist — build on them, don't repeat them)")
        for ans in relevant_answers[:8]:
            lines.append(f"\n### [{ans['id']}]")
            body = ans["body"][:600]
            if len(ans["body"]) > 600:
                body += "... [truncated]"
            lines.append(body)
        lines.append("")

    if question_bank_categories:
        lines.append("## QUESTION BANK CATEGORIES (for context)")
        lines.append(question_bank_categories)
        lines.append("")

    if research_notes:
        lines.append("## QUESTION-JUDGMENT RUBRIC")
        lines.append(research_notes.strip())
        lines.append("")

    lines.append("## OUTPUT FORMAT")
    lines.append("Return ONLY valid JSON — no explanation, no markdown wrapper:")
    lines.append("")
    lines.append(json.dumps({
        "neighborhood": {
            "title": topic,
            "type": topic_type,
            "target_output": target_output,
        },
        "questions": [
            {
                "text": "Tell me about the moment you first realized...",
                "story_function": "turning_point",
                "priority": 0.85,
                "reason": "This is the central pivot of the chapter arc",
                "target_output_relevance": "Core scene for the chapter climax",
            },
            {
                "text": "What did that place look like? Smell like? Who was there?",
                "story_function": "scene",
                "priority": 0.75,
                "reason": "Sensory grounding for the setting",
                "target_output_relevance": "Opens the chapter with vivid detail",
            },
        ],
    }, indent=2))
    lines.append("")
    lines.append(f"Generate 8-12 questions. Cover all arc functions. Make them specific to: {topic}")
    lines.append("=" * 70)
    lines.append("OUTPUT JSON ONLY — no explanation, no commentary")
    lines.append("=" * 70)

    return "\n".join(lines)


def build_gaps_prompt(gaps: dict, mission: str) -> str:
    """Build a human-readable gap report (no AI call needed)."""
    lines = []
    lines.append("=" * 70)
    lines.append("LIFEHUG — GAP DETECTION REPORT")
    lines.append("=" * 70)
    lines.append(f"Total answers analyzed: {gaps['total_answers']}")
    lines.append("")

    lines.append("## THIN TIME PERIODS")
    if gaps["thin_periods"]:
        for p in gaps["thin_periods"]:
            pct = f"{p['coverage']*100:.0f}%"
            lines.append(f"  {p['label']:20s}  {p['mentions']} answers  ({pct} coverage)")
    else:
        lines.append("  No thin time periods detected.")
    lines.append("")

    lines.append("## THIN THEMES")
    if gaps["thin_themes"]:
        for t in gaps["thin_themes"]:
            pct = f"{t['coverage']*100:.0f}%"
            lines.append(f"  {t['label']:20s}  {t['mentions']} answers  ({pct} coverage)")
    else:
        lines.append("  No thin themes detected.")
    lines.append("")

    lines.append("## FAMILY MENTIONED BUT NO WIKI FOCUS")
    if gaps["unfocused_family"]:
        for f in gaps["unfocused_family"]:
            lines.append(f"  {f['label']:20s}  mentioned {f['mentions']} times")
    else:
        lines.append("  All frequently mentioned family members have wiki pages.")
    lines.append("")

    lines.append("## SUGGESTED NEXT NEIGHBORHOODS")
    suggestions = []
    for p in gaps["thin_periods"][:3]:
        suggestions.append({
            "title": p["label"],
            "type": "time_period",
            "why": f"Only {p['mentions']} answers cover this period",
            "cmd": f"python3 system/research_expand.py --topic \"{p['label']}\" --type time_period",
        })
    for t in gaps["thin_themes"][:3]:
        suggestions.append({
            "title": t["label"],
            "type": "theme",
            "why": f"Only {t['mentions']} answers cover this theme",
            "cmd": f"python3 system/research_expand.py --topic \"{t['label']}\" --type theme --output essay",
        })
    for f in gaps["unfocused_family"][:2]:
        suggestions.append({
            "title": f["label"],
            "type": "person",
            "why": f"Mentioned {f['mentions']} times but no Focus yet",
            "cmd": f"python3 system/research_expand.py --topic \"{f['label']}\" --type person --output letter",
        })

    if suggestions:
        for s in suggestions:
            lines.append(f"  [{s['type']}] {s['title']}")
            lines.append(f"    Why: {s['why']}")
            lines.append(f"    Run: {s['cmd']}")
            lines.append("")
    else:
        lines.append("  No suggestions (library looks well-covered, or no answers yet).")

    lines.append("=" * 70)
    lines.append("Use --dry-run to preview without writing, or run the suggested commands above.")
    lines.append("=" * 70)

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Core expand logic
# ---------------------------------------------------------------------------


def _infer_topic_from_path(path: Path) -> tuple[str, str]:
    """Infer topic name and type from a file path."""
    stem = path.stem.replace("-", " ").replace("_", " ").title()
    parent = path.parent.name

    type_map = {
        "people":      "person",
        "places":      "place",
        "periods":     "time_period",
        "projects":    "project",
        "themes":      "theme",
        "objects":     "event",
        "manual":      "theme",
        "answers":     "theme",
    }
    topic_type = type_map.get(parent, "theme")
    return stem, topic_type


def resolve_path(path_str: str) -> Path:
    """Resolve a path relative to REPO_DIR if not absolute."""
    p = Path(path_str)
    if p.is_absolute():
        return p
    # Try relative to REPO_DIR
    candidate = REPO_DIR / p
    if candidate.exists():
        return candidate
    # Try as-is
    if p.exists():
        return p
    return REPO_DIR / p  # Return even if not found (will be checked later)


def find_relevant_answers(answers: list[dict], topic: str, max_answers: int = 8) -> list[dict]:
    """Return answers that mention the topic."""
    topic_words = set(topic.lower().split())
    topic_lower = topic.lower()

    scored: list[tuple[int, dict]] = []
    for ans in answers:
        body_lower = ans["body"].lower()
        score = 0
        # Direct match
        if topic_lower in body_lower:
            score += 3
        # Word-level match
        for word in topic_words:
            if len(word) >= 4 and word in body_lower:
                score += 1
        if score > 0:
            scored.append((score, ans))

    scored.sort(key=lambda x: -x[0])
    return [a for _, a in scored[:max_answers]]


def parse_ai_json(raw: str) -> dict:
    """Parse AI JSON response, handling markdown code fences."""
    response_bytes = len(raw.encode("utf-8", errors="replace"))
    raw = raw.strip()
    # Strip markdown fences
    if raw.startswith("```"):
        lines = raw.splitlines()
        start = 1
        end = len(lines)
        for i in range(len(lines) - 1, 0, -1):
            if lines[i].strip() == "```":
                end = i
                break
        raw = "\n".join(lines[start:end])
    try:
        parsed = json.loads(raw)
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise AIResponseError(
            "AI response was not valid JSON",
            provider="ai",
            operation="parse-json",
            status="malformed",
            response_bytes=response_bytes,
        ) from None
    if not isinstance(parsed, dict):
        raise AIResponseError(
            "AI response JSON had an invalid schema",
            provider="ai",
            operation="parse-json",
            status="invalid_schema",
            response_bytes=response_bytes,
        )
    return parsed


# ---------------------------------------------------------------------------
# Mode: --expand
# ---------------------------------------------------------------------------


def cmd_expand(args: argparse.Namespace) -> int:
    path = resolve_path(args.expand)
    if not path.exists():
        print(f"Error: file not found: {path}", file=sys.stderr)
        return 1

    topic, topic_type = _infer_topic_from_path(path)
    # Allow CLI overrides
    if args.type:
        topic_type = args.type

    source_content = load_source_file(path)
    return _run_expansion(
        args=args,
        topic=topic,
        topic_type=topic_type,
        source_path=str(path.relative_to(REPO_DIR) if path.is_relative_to(REPO_DIR) else path),
        source_content=source_content,
    )


# ---------------------------------------------------------------------------
# Mode: --topic
# ---------------------------------------------------------------------------


def cmd_topic(args: argparse.Namespace) -> int:
    topic = args.topic
    topic_type = args.type or "theme"
    topic_lower = topic.lower()

    # Try to find a matching wiki/source file
    wiki_pages = load_wiki_pages(topic_lower, topic_type)
    source_content = ""
    source_path = f"topic:{topic_type}/{slugify(topic)}"
    if wiki_pages:
        # Use the first match
        source_content = wiki_pages[0]["content"]
        source_path = wiki_pages[0]["path"]

    return _run_expansion(
        args=args,
        topic=topic,
        topic_type=topic_type,
        source_path=source_path,
        source_content=source_content,
    )


# ---------------------------------------------------------------------------
# Shared expansion runner
# ---------------------------------------------------------------------------


def _run_expansion(
    args: argparse.Namespace,
    topic: str,
    topic_type: str,
    source_path: str,
    source_content: str,
) -> int:
    target_output = args.output or "chapter"
    dry_run = getattr(args, "dry_run", False)
    prompt_only = getattr(args, "prompt", False)
    from_response = getattr(args, "from_response", None)
    force = getattr(args, "force", False)

    model_cfg = load_config().get("research_model", DEFAULT_MODEL)
    model = getattr(args, "model", None) or model_cfg

    nbhd_id = neighborhood_id_for(topic)

    # Check for existing neighborhood
    nbhd_data = load_neighborhoods()
    existing = find_neighborhood(nbhd_data, nbhd_id)
    if existing and not force:
        print(f"⚠️  Neighborhood already exists: {nbhd_id}")
        print("   Use --force to regenerate questions and update it.")
        return 1

    # Load context
    mission = load_mission()
    answers = load_answers()
    relevant_answers = find_relevant_answers(answers, topic)

    # The question-judgment rubric (interactions/question_judgment/), never
    # truncated — see system/question_judgment.py's module docstring for
    # the graceful legacy fallback this loader falls back to on an
    # un-upgraded vault.
    research_notes = load_judgment_rubric()

    # Question bank categories summary
    qbank_text = QUESTIONS_FILE.read_text(encoding="utf-8") if QUESTIONS_FILE.exists() else ""
    cats = parse_categories(qbank_text) if qbank_text else {}
    cat_summary = "\n".join(
        f"  {k}: {v['name']}" for k, v in sorted(cats.items())
    )

    # Build the prompt
    prompt = build_expansion_prompt(
        topic=topic,
        topic_type=topic_type,
        target_output=target_output,
        mission=mission,
        source_content=source_content,
        relevant_answers=relevant_answers,
        question_bank_categories=cat_summary,
        research_notes=research_notes,
        self_signals=load_classified_self_signals() if topic_type == "self" else None,
    )

    if prompt_only:
        print(prompt)
        return 0

    if dry_run:
        print(f"[DRY RUN] Would expand neighborhood: {nbhd_id}")
        print(f"  Topic:   {topic}")
        print(f"  Type:    {topic_type}")
        print(f"  Output:  {target_output}")
        print(f"  Model:   {model}")
        print(f"  Source:  {source_path}")
        print(f"  Relevant answers found: {len(relevant_answers)}")
        print()
        print("--- PROMPT PREVIEW (first 500 chars) ---")
        print(prompt[:500])
        print("... [truncated]")
        return 0

    # Get the model response: from an agent-written file (keyless desktop path)
    # or by calling the shared AI provider.
    if from_response:
        resp_path = Path(from_response)
        if not resp_path.exists():
            print(f"Error: response file not found: {resp_path}", file=sys.stderr)
            return 1
        print(f"Expanding neighborhood '{topic}' from {resp_path} (no model call)...")
        raw_response = resp_path.read_text(encoding="utf-8", errors="replace")
    else:
        print(f"Expanding neighborhood '{topic}' via {model}...")
        raw_response = call_ai(prompt, model)

    try:
        ai_data = parse_ai_json(raw_response)
        ai_questions = normalize_question_records(
            ai_data.get("questions", []),
            operation="research-expand-schema",
        )
    except Exception as exc:  # noqa: BLE001 — report metadata, never response text
        print(
            "Error: AI returned invalid JSON: "
            + failure_metadata(
                "research-expand-parse",
                exc,
                provider="ai",
                response_bytes=len(raw_response.encode("utf-8", errors="replace")),
            ),
            file=sys.stderr,
        )
        return 1

    if not ai_questions:
        print("Error: AI returned no questions.", file=sys.stderr)
        return 1

    # Build neighborhood record
    arc = make_arc(topic_type)
    # Try to fill arc slots from AI questions by story_function
    fn_to_slot = {slot["story_function"]: i for i, slot in enumerate(arc)}
    used_fns: set[str] = set()
    question_ids_for_arc: list[str] = []

    # Add candidates to store
    cands_data = load_candidates()
    new_cand_ids = add_candidates_from_ai(
        cands_data, ai_questions, nbhd_id, source_path
    )
    # Map first candidate of each story_function into the arc
    fn_to_cand_id: dict[str, str] = {}
    for q, cand_id in zip(ai_questions, new_cand_ids):
        fn = q.get("story_function", "")
        if fn in fn_to_slot and fn not in fn_to_cand_id:
            fn_to_cand_id[fn] = cand_id

    for slot in arc:
        fn = slot["story_function"]
        if fn in fn_to_cand_id:
            slot["question_id"] = fn_to_cand_id[fn]
            slot["status"] = "candidate"

    completeness = compute_completeness(arc)
    questions = parse_questions(QUESTIONS_FILE.read_text(encoding="utf-8")) if QUESTIONS_FILE.exists() else []

    # Build or update neighborhood record
    now = now_utc()
    if existing and force:
        refreshed = apply_readiness({
            **existing,
            "arc": arc,
            "completeness": completeness,
            "status": "draft",
            "target_output": target_output,
            "source": source_path,
            "updated_at": now,
        }, cands_data, questions)
        existing.clear()
        existing.update(refreshed)
        print(f"✓ Updated neighborhood: {nbhd_id}")
    else:
        neighborhood = apply_readiness({
            "id": nbhd_id,
            "title": topic,
            "type": topic_type,
            "target_output": target_output,
            "source": source_path,
            "arc": arc,
            "completeness": completeness,
            "status": "draft",
            "created_at": now,
        }, cands_data, questions)
        nbhd_data["neighborhoods"].append(neighborhood)
        print(f"✓ Created neighborhood: {nbhd_id}")

    save_candidates(cands_data)
    save_neighborhoods(nbhd_data)

    # Report
    print(f"  Title:       {topic}")
    print(f"  Type:        {topic_type}")
    print(f"  Output:      {target_output}")
    print(f"  Questions:   {len(new_cand_ids)} candidates added")
    counts = (existing if existing and force else neighborhood).get("arc_lifecycle_counts", {})
    readiness = existing if existing and force else neighborhood
    print(f"  Generated:   {counts.get('questions_generated', 0)} / {counts.get('total_slots', len(arc))} arc slots")
    print(f"  Promoted:    {counts.get('questions_promoted', 0)} / {counts.get('total_slots', len(arc))} arc slots")
    print(f"  Answered:    {counts.get('answers_captured', 0)} / {counts.get('total_slots', len(arc))} arc slots")
    print(f"  Draft ready: {'yes' if readiness.get('ready_to_draft') else 'no'}")
    print()
    print("Candidate questions added:")
    cands_data2 = load_candidates()
    cand_map = {c["id"]: c for c in cands_data2.get("candidates", [])}
    for cid in new_cand_ids:
        c = cand_map.get(cid, {})
        fn = c.get("story_function", "?")
        text = c.get("text", "")
        priority = c.get("priority", 0)
        print(f"  [{cid}] [{fn}] (p={priority:.2f}) {text[:80]}{'...' if len(text) > 80 else ''}")

    return 0


# ---------------------------------------------------------------------------
# Mode: --gaps
# ---------------------------------------------------------------------------


def cmd_gaps(args: argparse.Namespace) -> int:
    dry_run = getattr(args, "dry_run", False)
    answers = load_answers()

    if not answers:
        print("No answers found. Start answering some questions first!")
        print(f"  (Looking in: {ANSWERS_DIR})")
        return 0

    gaps = detect_gaps(answers)
    report = build_gaps_prompt(gaps, load_mission())
    print(report)

    if dry_run:
        return 0

    # Optionally, output suggestions for confirmation (don't auto-create)
    suggestions = []
    for p in gaps["thin_periods"][:2]:
        suggestions.append(("time_period", p["label"]))
    for t in gaps["thin_themes"][:2]:
        suggestions.append(("theme", t["label"]))
    for f in gaps["unfocused_family"][:1]:
        suggestions.append(("person", f["label"]))

    if suggestions:
        print()
        print("To create a neighborhood for any of the above, run the suggested commands.")
        print("No neighborhoods were created automatically. Confirmation required.")

    return 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Lifehug research neighborhood expander",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )

    # Mode flags (mutually exclusive-ish)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--expand",
        metavar="PATH",
        help="Expand from a wiki page, answer file, or source file",
    )
    mode.add_argument(
        "--topic",
        metavar="NAME",
        help="Expand from a named topic",
    )
    mode.add_argument(
        "--gaps",
        action="store_true",
        help="Auto-detect thin areas and suggest neighborhood-opening questions",
    )

    # Modifiers
    parser.add_argument(
        "--type",
        choices=VALID_TOPIC_TYPES,
        help="Topic type: person|place|time_period|project|theme|event",
    )
    parser.add_argument(
        "--output",
        choices=VALID_OUTPUT_TYPES,
        default="chapter",
        help="Target output format (default: chapter)",
    )
    parser.add_argument(
        "--prompt",
        action="store_true",
        help="Output the AI prompt only without calling the API",
    )
    parser.add_argument(
        "--from-response",
        metavar="PATH",
        help="Deposit questions from an agent-written response file instead of calling the API "
             "(keyless desktop path: pair with --prompt). File holds the questions JSON "
             "(optionally in a ```json fence).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview what would happen without writing anything",
    )
    parser.add_argument(
        "--model",
        metavar="MODEL",
        help=f"Override AI model (default: {DEFAULT_MODEL} or config.yaml research_model)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Recreate neighborhood even if it already exists",
    )

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    if args.gaps:
        return cmd_gaps(args)
    elif args.expand:
        return cmd_expand(args)
    elif args.topic:
        return cmd_topic(args)
    else:
        parser.print_help()
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
