#!/usr/bin/env python3
"""Report and build Lifehug question queues with balance caps."""

from __future__ import annotations

import argparse
import copy
import json
import math
import random
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone

from lifehug_core import (
    ANSWERS_DIR,
    CLASSIFICATIONS_DIR,
    MANUAL_SOURCES_DIR,
    NEIGHBORHOODS_FILE,
    PLANNER_STATE_FILE,
    QUESTION_CANDIDATES_FILE,
    QUESTION_QUEUE_FILE,
    QUESTIONS_FILE,
    REPO_DIR,
    SECOND_VOICE_OFFERS_FILE,
    SOURCES_DIR,
    STATE_DIR,
    FOCUS_RECS_FILE,
    LEGACY_FOCUS_RECS_FILE,
    WIKI_DIR,
    answer_body,
    answer_id_from_filename,
    compute_coverage,
    now_utc,
    parse_categories,
    parse_questions,
    read_json,
    read_text,
    record_learning_failure,
    slugify,
    write_json,
    write_text,
)
from neighborhoods import apply_readiness
from roadmap import (
    DEFAULT_CAP,
    FINISHING_CAP,
    MAINTENANCE_FACTOR,
    TIER_TARGETS,
    derive_roadmap,
    focus_fill,
    load_roadmap,
)

# Relative base weight by tier — how much pull a Focus has before saturation.
# Tier mainly sets target_depth (and thus how long it stays under-filled); base
# gives a book a little more daily pull than a blog, but the per-Focus cap keeps
# any one Focus from dominating a week.
TIER_BASE = {"basic": 0.8, "standard": 1.0, "extreme": 1.2}
PRIMARY_BASE = 1.5  # the primary focus (the author's life story) outweighs any sub-focus
DEFAULT_DELIVERY_QUEUE_LIMIT = 8

# Inner-story dimension of the life-story arc (the SELF_ARC). These are first-class
# story functions alongside the outer-narrative (memoir) ones — self-knowledge is
# part of building the life story, not a separate competing track.
SELF_FUNCTIONS = (
    "self_image", "value", "fear", "contradiction", "perception_by_others", "growth_edge",
)

# How much of a week is reserved (floored) for self-knowledge questions and how
# much weight objectives get. Overridable via planner_state["lane_policy"].
DEFAULT_LANE_POLICY = {
    "self_floor_fraction": 0.08,   # ~1 self-knowledge slot per 12-question week
    "chapter_boost_fraction": 0.15,  # v76: ~1-2 book chapter-gap slots per week
    "objective_boost": 2.5,        # multiplier on a question matching an objective
    # v196 (timeline-whispers-and-keystones): the ONE timeline dial. It is an
    # EXCHANGE RATE, not a nudge — how many timeline unknowns one answer must
    # place to be worth one ordinary story answer. It does two jobs with one
    # number: below it a keystone is not minted at all, and above it the
    # minted question's weight is `leverage / timeline_leverage_per_story` in
    # exactly the currency `objective_boost` (2.5) is quoted in.
    #
    # 6, conservatively: a week is ~8 questions, so a keystone ties an
    # ordinary question at 6 unknowns and only reaches the strongest lane in
    # the queue at 15. With KEYSTONE_CAP (2) and GROUP_CAPS["timeline"] (1 a
    # week) a vault can never spend more than one slot on the timeline no
    # matter how leveraged its anchors are.
    #
    # v195's `leverage_boost` is DELETED with the adjacency it expressed: a
    # bank question whose focus merely resembled a keystone slug was lifted
    # and starred while never asking for a date — the defect in
    # lifehug/lifehug-platform#586. A keystone is asked as itself now.
    "timeline_leverage_per_story": 6,
    # Wave F (plan §2.3, §8.5): the queue admission threshold for a temporal
    # WORK ITEM, in combined-score units (0..1). It is the whole of "ordinary
    # low-value gaps remain on Timeline and do not crowd out the daily
    # experience" — above it an item may be minted into the bank and compete
    # for the day, below it the item stays a Timeline invitation and nothing
    # else. It replaces nothing: `timeline_leverage_per_story` still sets the
    # weight a minted question carries once it IS in the bank.
    "work_item_queue_threshold": 0.45,
    "expansion_floor": 0.02,       # research-expansion residual when there's room
    "expansion_onset": 0.60,       # global fullness where expansion urgency starts
}

GROUP_CAPS = {
    "main": 0.50,
    "project": 0.35,
    "focus": 0.25,
    # v196: minted keystone questions live in their own group, and the cap is
    # the volume control — max_counts floors every group at 1, so ANY weekly
    # limit yields exactly one timeline question per week.
    "timeline": 0.01,
}

STORY_FUNCTIONS = (
    "foundation",
    "scene",
    "tension",
    "turning_point",
    "relationship",
    "meaning",
    "contradiction",
    "output_gap",
    # Inner story (SELF_ARC) — "contradiction" is shared with the memoir arc above.
    "self_image",
    "value",
    "fear",
    "perception_by_others",
    "growth_edge",
)

STORY_FUNCTION_CAPS = {
    "foundation": 0.35,
    "scene": 0.45,
    "tension": 0.30,
    "turning_point": 0.30,
    "relationship": 0.35,
    "meaning": 0.30,
    "contradiction": 0.20,
    "output_gap": 0.20,
    # Inner-story dimension — kept modest so it's always represented but never floods.
    "self_image": 0.15,
    "value": 0.15,
    "fear": 0.12,
    "perception_by_others": 0.12,
    "growth_edge": 0.15,
}

KIND_TO_STORY_FUNCTION = {
    "foundation": "foundation",
    "scene": "scene",
    "relationships": "relationship",
    "relationship": "relationship",
    "meaning": "meaning",
    "gap": "output_gap",
    "output_gap": "output_gap",
}

STORY_FUNCTION_KEYWORDS = {
    # Inner story first — specific phrases so genuine self-examination questions
    # classify as self functions, while plain event questions fall through below.
    "self_image": ["who are you", "who am i", "story you tell about yourself",
                   "how you see yourself", "kind of person you", "who you really are"],
    "value": ["value most", "what matters most", "care about most", "principle you",
              "what you stand for", "most important to you"],
    "fear": ["afraid of becoming", "what do you fear", "dread", "protect against",
             "scared of becoming", "avoid most"],
    "perception_by_others": ["how others see", "how people see you", "how they see you",
                             "others perceive", "misunderstood", "people get wrong about you"],
    "growth_edge": ["becoming", "working on about yourself", "want to change about yourself",
                    "who you want to be", "growth edge", "still figuring out about yourself"],
    "scene": [
        "walk me through",
        "what did it look",
        "what did it feel",
        "what did it smell",
        "what did the room",
        "specific day",
        "specific moment",
        "where were you",
        "what was the conversation",
    ],
    "tension": ["hardest", "conflict", "friction", "scared", "fear", "risk", "almost", "struggle", "pressure"],
    "turning_point": ["when did", "moment", "changed", "shift", "turning point", "decided", "realized", "clicked"],
    # Generic kinship/relation words only — never a specific user's names
    # (this file ships to every Lifehug user).
    "relationship": ["who", "relationship", "mom", "dad", "wife", "husband", "brother",
                     "sister", "friend", "mentor", "family", "partner", "grandma", "grandpa"],
    "meaning": ["what did", "teach", "mean", "understand", "explain", "why", "proud", "wisdom"],
    "contradiction": ["different from", "but", "contradiction", "surprised", "mismatch", "tension between"],
    "output_gap": ["letter", "chapter", "post", "essay", "missing", "unresolved", "gap", "what part"],
}


def qid_key(qid: str) -> tuple[str, int, str]:
    match = re.match(r"^([A-Z])(\d+)([a-z]*)$", qid)
    if not match:
        return (qid[:1], 0, qid)
    return (match.group(1), int(match.group(2)), match.group(3))


def parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    raw = str(value).strip()
    if not raw:
        return None
    try:
        if raw.endswith("Z"):
            return datetime.fromisoformat(raw[:-1] + "+00:00")
        if len(raw) == 10:
            return datetime.fromisoformat(raw + "T00:00:00+00:00")
        dt = datetime.fromisoformat(raw)
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def future_timestamp(days: int) -> str:
    return (datetime.now(timezone.utc) + timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")


def default_planner_state() -> dict:
    return {
        "version": 1,
        "active_objectives": [],
        # source_type caps were removed in v69: every queued item is
        # source_type "question_bank" (candidates promote into the bank before
        # they can be queued), so the cap gated nothing. group and
        # story_function caps are both ENFORCED in build_queue.
        "caps": {
            "group": GROUP_CAPS,
            "story_function": STORY_FUNCTION_CAPS,
        },
        "queue": {
            "default_limit": DEFAULT_DELIVERY_QUEUE_LIMIT,
            "arc_max": 2,
            "expires_after_days": 8,
        },
        "lane_policy": DEFAULT_LANE_POLICY,
    }


def merge_defaults(data: dict, defaults: dict) -> dict:
    merged = copy.deepcopy(defaults)
    for key, value in data.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = merge_defaults(value, merged[key])
        else:
            merged[key] = value
    return merged


def load_planner_state(*, write_default: bool = False) -> dict:
    data = read_json(PLANNER_STATE_FILE, default=None)
    if not isinstance(data, dict):
        data = default_planner_state()
    else:
        data = merge_defaults(data, default_planner_state())
    group_caps = data.get("caps", {}).get("group", {})
    old_focus_group = "spot" "light"
    if "focus" not in group_caps and old_focus_group in group_caps:
        group_caps["focus"] = group_caps[old_focus_group]
    group_caps.pop(old_focus_group, None)
    if write_default:
        data["last_updated"] = now_utc()
        write_json(PLANNER_STATE_FILE, data)
    return data


def load_question_state():
    text = QUESTIONS_FILE.read_text(encoding="utf-8")
    questions = parse_questions(text)
    categories = parse_categories(text)
    coverage = compute_coverage(questions, categories)
    return questions, categories, coverage


def load_candidates() -> list[dict]:
    data = read_json(QUESTION_CANDIDATES_FILE, default={}) or {}
    return list(data.get("candidates", []))


def frontmatter_value(text: str, key: str, default: str = "") -> str:
    match = re.search(rf"^{re.escape(key)}:\s*[\"']?(.+?)[\"']?\s*$", text, re.MULTILINE)
    return match.group(1).strip().strip('"').strip("'") if match else default


def _count_all_sources() -> dict[str, int]:
    """Count ingested source files by source type."""
    counts: dict[str, int] = {}
    if not SOURCES_DIR.exists():
        return counts
    for subdir in sorted(SOURCES_DIR.iterdir()):
        if subdir.is_dir() and subdir.name != ".gitkeep":
            n = sum(1 for f in subdir.glob("*.md") if f.is_file())
            if n:
                counts[subdir.name] = n
    return counts


def _count_classified(source_type: str) -> int:
    """Count CURRENT classified sources for a given type.

    v237: a stale classification is withheld from every derived reader, so
    counting it here would tell the planner the loop has coverage it cannot
    actually use. `classify_story.classification_is_current` takes the PATH,
    so this module keeps resolving candidates against its own roots."""
    import classify_story  # noqa: PLC0415

    if not CLASSIFICATIONS_DIR.exists():
        return 0
    count = 0
    source_dir = SOURCES_DIR / source_type
    if not source_dir.exists():
        return 0
    for path in source_dir.glob("*.md"):
        rel_key = slugify(path.relative_to(REPO_DIR).with_suffix("").as_posix())
        candidates = [
            CLASSIFICATIONS_DIR / f"{rel_key}.json",
            CLASSIFICATIONS_DIR / f"{path.stem}.json",
        ]
        if any(classify_story.classification_is_current(c) for c in candidates):
            count += 1
    return count


def read_manual_sources() -> list[dict]:
    if not MANUAL_SOURCES_DIR.exists():
        return []
    sources = []
    for path in sorted(MANUAL_SOURCES_DIR.glob("*.md")):
        text = path.read_text(encoding="utf-8", errors="replace")
        sources.append({
            "path": path.as_posix(),
            "title": frontmatter_value(text, "title", path.stem.replace("-", " ").title()),
            "source": frontmatter_value(text, "source", "manual"),
            "captured_at": frontmatter_value(text, "captured_at", ""),
        })
    sources.sort(key=lambda item: item.get("captured_at") or "", reverse=True)
    return sources


def read_answer_dates() -> dict[str, str]:
    dates = {}
    if not ANSWERS_DIR.exists():
        return dates
    for path in sorted(ANSWERS_DIR.glob("*.md")):
        qid = answer_id_from_filename(path)
        if not qid:
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        match = re.search(r"\*\*Asked:\*\*.*?\|\s*\*\*Answered:\*\*\s*([0-9-]+)", text)
        if match:
            dates[qid] = match.group(1)
    return dates


def read_answer_bodies() -> dict[str, str]:
    bodies = {}
    if not ANSWERS_DIR.exists():
        return bodies
    for path in sorted(ANSWERS_DIR.glob("*.md")):
        qid = answer_id_from_filename(path)
        if not qid:
            continue
        bodies[qid] = answer_body(path.read_text(encoding="utf-8", errors="replace"))
    return bodies


def category_ratio(coverage: dict, cat_id: str) -> float:
    data = coverage["categories"].get(cat_id, {})
    total = data.get("total", 0)
    return data.get("answered", 0) / total if total else 1.0


def infer_story_function(text: str, kind: str | None = None) -> str:
    if kind in KIND_TO_STORY_FUNCTION:
        return KIND_TO_STORY_FUNCTION[kind]
    haystack = text.lower()
    for function_name, keywords in STORY_FUNCTION_KEYWORDS.items():
        if any(keyword in haystack for keyword in keywords):
            return function_name
    if "tell me about" in haystack or "background" in haystack:
        return "foundation"
    return "foundation"


def objective_match(question: dict, objectives: list[dict]) -> tuple[str | None, int]:
    text = str(question.get("text", "")).lower()
    category = str(question.get("category", "")).upper()
    for objective in objectives:
        if objective.get("status", "active") != "active":
            continue
        categories = {str(c).upper() for c in objective.get("categories", [])}
        keywords = [str(k).lower() for k in objective.get("keywords", [])]
        if category in categories or any(keyword and keyword in text for keyword in keywords):
            return str(objective.get("label", "objective")), int(objective.get("max_questions", 3) or 3)
    return None, 0


def max_counts(limit: int, caps: dict[str, float]) -> dict[str, int]:
    return {key: max(1, math.ceil(limit * float(value))) for key, value in caps.items()}


def resolve_roadmap(questions: list[dict] | None = None) -> dict:
    """Load the roadmap; if absent (pre-v15 instance), derive it on the fly so
    the planner still works. Never writes."""
    roadmap = load_roadmap()
    if roadmap.get("focuses"):
        return roadmap
    return derive_roadmap(QUESTIONS_FILE.read_text(encoding="utf-8"))


def focus_weight(focus: dict, fill: dict) -> float:
    """weight = base(tier) × fill_factor × room. Saturated focuses decay to
    maintenance weight (never zero); empty-of-questions focuses go to zero."""
    if not fill["room"]:
        return 0.0
    base = PRIMARY_BASE if focus.get("primary") else TIER_BASE.get(focus.get("tier", "standard"), 1.0)
    sat = fill["saturation"]
    if sat >= 1.0:
        fill_factor = MAINTENANCE_FACTOR
    elif sat >= 0.8:
        fill_factor = 1.0 - (sat - 0.8) / 0.2 * 0.7   # 1.0 → 0.3 across .8–1.0
    else:
        fill_factor = 1.0
    return base * fill_factor


def build_focus_index(focuses: list[dict], questions: list[dict]) -> dict:
    """Map category → focus, and precompute each focus's fill, weight and cap."""
    cat_to_focus: dict[str, str] = {}
    info: dict[str, dict] = {}
    for focus in focuses:
        fill = focus_fill(focus, questions)
        cap_frac = FINISHING_CAP if focus.get("phase") == "finishing" else float(focus.get("cap", DEFAULT_CAP))
        info[focus["id"]] = {
            "focus": focus,
            "fill": fill,
            "weight": focus_weight(focus, fill),
            "cap_fraction": cap_frac,
            "type": focus.get("type", "project"),
        }
        for cat in focus.get("categories", []):
            cat_to_focus[str(cat)] = focus["id"]
    return {"cat_to_focus": cat_to_focus, "info": info}


# ---------------------------------------------------------------------------
# Second-voice offers (v72, Tier 2) — opportunity surfacing, never tasks.
# Hard rules from the owner: max N/month (default 2, config
# `second_voice_offers_per_month`, 0 disables), one line inside a summary the
# owner already reads, no checkbox, an ignored offer expires silently and is
# NEVER repeated.
# ---------------------------------------------------------------------------

DEFAULT_SECOND_VOICE_OFFERS_PER_MONTH = 2


# Focus-label heuristics for which interview bank fits (a focus can override
# with an explicit `relationship` field, preserved across roadmap rebuilds).
_RELATIONSHIP_HINTS = (
    (("mom", "mother", "dad", "father"), "parent"),
    (("grandma", "grandpa", "grandmother", "grandfather"), "grandparent"),
    (("wife", "husband", "spouse", "partner"), "spouse"),
    (("son", "daughter", "kid", "child"), "child"),
    (("brother", "sister", "sibling"), "sibling"),
    (("mentor", "coach", "teacher"), "mentor"),
    (("cofounder", "co-founder"), "cofounder"),
)


def _relationship_for(focus: dict) -> str:
    explicit = str(focus.get("relationship") or "").strip().lower()
    if explicit:
        return explicit
    haystack = f"{focus.get('label', '')} {focus.get('objective', '')}".lower()
    for keywords, relationship in _RELATIONSHIP_HINTS:
        if any(kw in haystack for kw in keywords):
            return relationship
    return "friend"


def pick_second_voice_offer(now: datetime | None = None) -> str | None:
    """One gentle, in-person suggestion — or None (most weeks). Picks a LIVING
    person-Focus and one question from their relationship-type interview bank.
    Bank questions are second-person by design — actually askable of the
    person — unlike category questions, which are the author's lens and must
    never be relayed ('ask James whether YOU lost patience with him' is
    nonsense; a dead parent must never become an errand)."""
    from lifehug_core import load_config  # noqa: PLC0415
    from research_expand import INTERVIEW_BANKS  # noqa: PLC0415

    try:
        per_month = int(load_config().get(
            "second_voice_offers_per_month", DEFAULT_SECOND_VOICE_OFFERS_PER_MONTH))
    except (TypeError, ValueError):
        per_month = DEFAULT_SECOND_VOICE_OFFERS_PER_MONTH
    if per_month <= 0:
        return None

    now = now or datetime.now(timezone.utc)
    month_key = now.strftime("%Y-%m")
    state = read_json(SECOND_VOICE_OFFERS_FILE, default=None) or {"version": 1, "offered": []}
    offered_keys = {str(o.get("key")) for o in state.get("offered", [])}
    this_month = sum(1 for o in state.get("offered", []) if str(o.get("month")) == month_key)
    if this_month >= per_month:
        return None

    questions, _categories, _coverage = load_question_state()
    focuses = [f for f in resolve_roadmap(questions).get("focuses", [])
               if f.get("type") in ("person", "relationship")
               and f.get("living") is not False        # deceased: never an errand
               and not f.get("primary")
               and f.get("categories")]
    if not focuses:
        return None

    pool: list[tuple[str, str, str]] = []  # (key, person, question)
    for focus in focuses:
        person = str(focus.get("label", ""))
        bank = INTERVIEW_BANKS.get(_relationship_for(focus), INTERVIEW_BANKS["friend"])
        for question in bank:
            key = f"{slugify(person)}::{slugify(question)[:60]}"
            if key not in offered_keys:
                pool.append((key, person, question))
    if not pool:
        return None
    # Deterministic pick, varies by month: stable across re-runs in a week.
    key, person, question = pool[(now.year * 12 + now.month) % len(pool)]

    state.setdefault("offered", []).append({
        "key": key,
        "person": person,
        "month": month_key,
        "offered_at": now.isoformat().replace("+00:00", "Z"),
    })
    write_json(SECOND_VOICE_OFFERS_FILE, state)
    return (f"💬 If it comes up naturally sometime, ask {person}: “{question}” — "
            f"then forward whatever they say (it saves as their account). No rush, no need.")


def acknowledge_second_voice_offer(key: str) -> bool:
    """Stamp `acknowledged_at` on a pending offer (v101 — the viewer's home
    card 'got it' button). Acknowledging only hides the card; the offer still
    never repeats, per the Tier-2 contract."""
    now = datetime.now(timezone.utc)
    state = read_json(SECOND_VOICE_OFFERS_FILE, default=None) or {"version": 1, "offered": []}
    for offer in state.get("offered", []):
        if str(offer.get("key")) == key and not offer.get("acknowledged_at"):
            offer["acknowledged_at"] = now.isoformat().replace("+00:00", "Z")
            write_json(SECOND_VOICE_OFFERS_FILE, state)
            return True
    return False


def zombie_focuses(focuses: list[dict]) -> list[dict]:
    """Focuses with no question categories: the planner can never ask about
    them (weight 0 forever). Seed them with questions (`lifehug.py focus-new`
    scaffolds a category) or remove them."""
    return [f for f in focuses if not f.get("categories")]


def global_fullness(focuses: list[dict], questions: list[dict]) -> float:
    answered = total = 0
    for focus in focuses:
        if not focus.get("categories"):
            continue  # zombie focus — no questions can ever land; counting its
                      # target would suppress expansion urgency with phantom room
        fill = focus_fill(focus, questions)
        answered += fill["answered"]
        total += fill["target"]
    return answered / total if total else 0.0


# Late-arc relational functions (Aron): escalation must be earned — never ask
# these about a person until the earlier arc slots have real answered material.
# (perception_by_others included: within a person/relationship Focus the
# keyword classifier routes "how they see you" questions there.)
LATE_RELATIONAL_FUNCTIONS = {"tension", "what_i_want_them_to_know", "how_they_see_me", "perception_by_others"}
ESCALATION_MIN_ANSWERED = 2

# Love-map staleness (Gottman): a living person's inner world changes — when a
# person-Focus category hasn't been answered in this long, boost it so the
# knowledge doesn't decay.
LOVE_MAP_STALE_DAYS = 60
LOVE_MAP_STALE_BOOST = 1.3


def enriched_pending_questions(questions: list[dict], categories: dict, coverage: dict, objectives: list[dict],
                               focus_index: dict | None = None) -> list[dict]:
    rows = []
    cat_to_focus = (focus_index or {}).get("cat_to_focus", {})
    info = (focus_index or {}).get("info", {})

    # Load quality profile once — applies story-function multipliers when active.
    try:
        from quality_profile import load_profile  # noqa: PLC0415
        _qprofile = load_profile()
    except Exception:  # noqa: BLE001
        _qprofile = {"active": False}

    # Per-category answered counts (escalation gate) and latest answer dates
    # (love-map staleness).
    answered_per_cat: Counter = Counter()
    for q in questions:
        if q["answered"]:
            answered_per_cat[str(q["category"])] += 1
    try:
        latest_dates = category_latest_dates(questions, read_answer_dates())
    except Exception:  # noqa: BLE001
        latest_dates = {}

    def _stale_days(category: str) -> float | None:
        raw = latest_dates.get(category)
        if not raw:
            return None
        try:
            latest = datetime.fromisoformat(str(raw)[:10])
        except ValueError:
            return None
        return (datetime.now() - latest).days

    for question in questions:
        if question["answered"]:
            continue
        category = str(question["category"])
        group = categories.get(category, {}).get("group", "main")
        story_function = infer_story_function(str(question["text"]))
        objective, objective_limit = objective_match(question, objectives)
        focus_id = cat_to_focus.get(category)
        finfo = info.get(focus_id, {})
        base_weight = float(finfo.get("weight", 1.0))

        # Apply quality multiplier from profile (only when profile is active).
        if _qprofile.get("active"):
            fn_data = _qprofile.get("by_story_function", {}).get(story_function, {})
            quality_multiplier = float(fn_data.get("multiplier", 1.0))
            base_weight = base_weight * quality_multiplier
            # Rumination cooldown: recent answers in this category show the
            # brooding signature — cool it hard rather than digging deeper.
            # Depth ≠ repetition; it returns when the profile flag clears.
            if category in (_qprofile.get("rumination_categories") or []):
                base_weight = base_weight * 0.25

        # Engagement multiplier (issue #119) — pacing/framing bias ONLY,
        # alongside the quality multiplier above. Guarded on
        # engagement.active; never touches the self-knowledge floor, the
        # escalation gate below, or the rumination cooldown above. Drain is
        # not negative (owner-set) — the only back-off remains rumination.
        _engagement = _qprofile.get("engagement") or {}
        if _engagement.get("active"):
            eng_data = _engagement.get("by_story_function", {}).get(story_function, {})
            engagement_multiplier = float(eng_data.get("multiplier", 1.0))
            base_weight = base_weight * engagement_multiplier

        # Aron escalation gate: late-arc relational questions wait until the
        # earlier slots have answered material for this person.
        escalation_hold = (
            story_function in LATE_RELATIONAL_FUNCTIONS
            and finfo.get("type") in ("person", "relationship")
            and answered_per_cat[category] < ESCALATION_MIN_ANSWERED
        )
        if escalation_hold:
            base_weight = base_weight * 0.05

        # Love-map staleness: living-person categories gone quiet get a boost.
        if finfo.get("type") in ("person", "relationship"):
            stale = _stale_days(category)
            if stale is not None and stale >= LOVE_MAP_STALE_DAYS:
                base_weight = base_weight * LOVE_MAP_STALE_BOOST

        rows.append({
            **question,
            "group": group,
            "source_type": "question_bank",
            "story_function": story_function,
            "category_ratio": category_ratio(coverage, category),
            "objective": objective,
            "objective_limit": objective_limit,
            "focus": focus_id,
            "focus_type": finfo.get("type", group),
            "weight": base_weight,
            "escalation_hold": escalation_hold,
        })
    rows.sort(key=lambda q: (
        q["objective"] is None,
        q["category_ratio"],
        q["group"] == "focus",
        qid_key(str(q["id"])),
    ))
    return rows


def accepted_candidate_recommendations(candidates: list[dict], limit: int = 8) -> list[dict]:
    rows = [c for c in candidates if c.get("status") == "accepted"]
    rows.sort(key=lambda c: (-float(c.get("priority", 0) or 0), c.get("created_at", "")))
    return rows[:limit]


def _week_seed(generated_at: str) -> int:
    """Stable per-week seed so each weekly rebuild varies, but a given week is
    reproducible (good for tests and idempotent re-runs within the week)."""
    dt = parse_time(generated_at) or datetime.now(timezone.utc)
    iso = dt.isocalendar()
    return iso[0] * 100 + iso[1]


def build_queue(limit: int, arc_max: int, expires_days: int = 8, planner_state: dict | None = None,
                seed: int | None = None, timeline_probes: object = None) -> dict:
    """Build the weekly queue by dynamic Focus-weighted sampling.

    Each Focus gets weight = base(tier) × fill_factor × room; saturated Focuses
    fade to maintenance weight. No Focus exceeds its cap (30%, or 50% while
    `finishing`). A self-knowledge floor reserves ~1 slot/week. Selection is
    weighted-random (seeded per week) so the daily sequence has real variety
    rather than a deterministic march. Research-expansion is NOT a queue slot —
    it surfaces as `expansion` urgency in the metadata for the cron to act on.
    """
    questions, categories, coverage = load_question_state()
    candidates = load_candidates()
    planner_state = planner_state or load_planner_state()
    story_caps = planner_state.get("caps", {}).get("story_function", STORY_FUNCTION_CAPS)
    max_by_story = max_counts(limit, story_caps)
    group_caps = planner_state.get("caps", {}).get("group", GROUP_CAPS)
    max_by_group = max_counts(limit, group_caps)
    policy = {**DEFAULT_LANE_POLICY, **planner_state.get("lane_policy", {})}

    focuses = resolve_roadmap(questions).get("focuses", [])
    findex = build_focus_index(focuses, questions)
    info = findex["info"]
    generated_at = now_utc()
    rng = random.Random(seed if seed is not None else _week_seed(generated_at))

    pending = enriched_pending_questions(
        questions, categories, coverage, planner_state.get("active_objectives", []), findex)

    # v196: a MINTED keystone question is an ordinary pending bank question
    # that happens to carry a leverage number. The index is supplied by the
    # CALLER (the CLI reads it through a guarded `current_timeline_probes()`),
    # never read here — the weekly queue must never be able to break on a
    # timeline problem. There is no adjacency: a question is a keystone
    # question because it IS the minted probe, by exact id, or it is not one.
    probes = timeline_probes if isinstance(timeline_probes, dict) else {}
    per_story = float(policy.get("timeline_leverage_per_story",
                                 DEFAULT_LANE_POLICY["timeline_leverage_per_story"]) or 0)
    queued_probes: list[dict] = []
    for question in pending:
        probe = probes.get(str(question.get("id")))
        if not isinstance(probe, dict):
            continue
        leverage = int(probe.get("leverage") or 0)
        question["timeline_probe"] = {
            "question_id": probe.get("question_id"),
            "anchor": probe.get("anchor"),
            "leverage": leverage,
            # Wave F: the identity the whisper lane suppresses against. Derived
            # here when the caller's probe index does not carry one, so an
            # injected index behaves exactly like the vault's own.
            "work_item_id": str(probe.get("work_item_id")
                                or timeline_work_item_id(anchor=probe.get("anchor")) or ""),
        }
        question["timeline_boost"] = (leverage / per_story) if per_story > 0 else 0.0

    # Per-Focus item caps (max share of the week any one Focus may take).
    focus_max = {
        fid: max(1, math.ceil(limit * d["cap_fraction"]))
        for fid, d in info.items()
    }

    queue = []
    per_focus = Counter()
    story_counts = Counter()
    group_counts = Counter()
    objective_counts = Counter()
    category_streak = None
    streak_count = 0
    remaining = pending[:]

    def record(selected: dict) -> None:
        nonlocal category_streak, streak_count
        remaining.remove(selected)
        cat = str(selected["category"])
        if cat == category_streak:
            streak_count += 1
        else:
            category_streak, streak_count = cat, 1
        if selected.get("focus"):
            per_focus[selected["focus"]] += 1
        story_counts[str(selected["story_function"])] += 1
        group_counts[str(selected["group"])] += 1
        if selected.get("objective"):
            objective_counts[str(selected["objective"])] += 1
        reason_parts = [
            f"focus {selected.get('focus') or selected['group']}",
            f"{selected['story_function']} story function",
            f"category coverage {selected['category_ratio']:.0%}",
        ]
        if selected.get("objective"):
            reason_parts.append(f"objective: {selected['objective']}")
        entry = {
            "question_id": selected["id"],
            "category": cat,
            "group": str(selected["group"]),
            "focus": selected.get("focus"),
            "source": "question_bank",
            "source_type": selected["source_type"],
            "story_function": str(selected["story_function"]),
            "objective": selected.get("objective"),
            "status": "queued",
            "reason": "; ".join(reason_parts),
        }
        # Wave F: a timeline-origin entry carries its work-item identity into
        # the week, which is what lets `arc_planner` refuse to whisper the very
        # item the day is already asking (plan §2.3).
        work_item_id = str((selected.get("timeline_probe") or {}).get("work_item_id") or "")
        if work_item_id:
            entry["work_item_id"] = work_item_id
        queue.append(entry)

    def eligible(q: dict, *, enforce_arc: bool = True, enforce_story: bool = True) -> bool:
        fid = q.get("focus")
        # Aron escalation: never queue a late-arc relational question before
        # the earlier slots have answers (relaxes only in the last-resort pool).
        if enforce_story and q.get("escalation_hold"):
            return False
        if fid and per_focus[fid] >= focus_max.get(fid, limit):
            return False
        if q.get("objective") and objective_counts[q["objective"]] >= int(q.get("objective_limit") or limit):
            return False
        if enforce_arc and str(q["category"]) == category_streak and streak_count >= arc_max:
            return False
        if enforce_story and story_counts[str(q["story_function"])] >= max_by_story.get(str(q["story_function"]), limit):
            return False
        # Group caps were previously display-only (state decorated, never
        # enforced); they now bound the queue like story-function caps do.
        if enforce_story and group_counts[str(q["group"])] >= max_by_group.get(str(q["group"]), limit):
            return False
        return True

    def weighted_pick(pool: list[dict]) -> dict:
        weights = [
            max(q.get("weight", 1.0), 0.0001)
            * (policy["objective_boost"] if q.get("objective") else 1.0)
            * (q.get("timeline_boost", 1.0) if q.get("timeline_probe") else 1.0)
            for q in pool
        ]
        return rng.choices(pool, weights=weights, k=1)[0]

    # 1) Inner-story floor — reserve ~1 slot/week for self-examination questions
    # (the SELF_ARC dimension) drawn from within the life story itself. Self-
    # knowledge isn't a separate focus; it's how the primary life story deepens.
    def is_self_dimension(q: dict) -> bool:
        return str(q.get("story_function")) in SELF_FUNCTIONS

    self_floor = max(1, round(limit * policy["self_floor_fraction"])) if any(
        is_self_dimension(q) for q in remaining) else 0
    self_taken = 0
    while self_taken < self_floor and len(queue) < limit:
        pool = [q for q in remaining if is_self_dimension(q) and eligible(q)]
        if not pool:
            break
        record(weighted_pick(pool))
        self_taken += 1

    # 1b) Chapter-gap boost (v76 phase 2) — reserve up to ~1 slot/week for the
    # top unanswered question in a chapter that's close to READY. Filling a
    # gap here actually tips a chapter over the READY line; without this
    # boost those questions compete with random category picks and lose more
    # than they should. Silent no-op when the book module is unavailable.
    chapter_boost_taken = 0
    chapter_boost_max = max(1, round(limit * policy.get("chapter_boost_fraction", 0.15)))
    try:
        import book as _book_mod  # noqa: PLC0415
        _gap_ids = set(_book_mod.gap_question_ids(max_per_chapter=2))
    except Exception:  # noqa: BLE001
        _gap_ids = set()
    while _gap_ids and chapter_boost_taken < chapter_boost_max and len(queue) < limit:
        pool = [q for q in remaining if str(q.get("id")) in _gap_ids and eligible(q)]
        if not pool:
            break
        record(weighted_pick(pool))
        chapter_boost_taken += 1

    # 2) Weighted sampling for the rest, relaxing constraints only if stuck.
    while remaining and len(queue) < limit:
        pool = [q for q in remaining if eligible(q)]
        if not pool:
            pool = [q for q in remaining if eligible(q, enforce_arc=False, enforce_story=False)]
        if not pool:
            pool = remaining[:]   # last resort: caps exhausted, fill anyway
        record(weighted_pick(pool))

    fullness = global_fullness(focuses, questions)
    onset = policy["expansion_onset"]
    urgency = 0.0 if fullness < onset else round(min(1.0, (fullness - onset) / (1 - onset)), 3)
    urgency = max(urgency, policy["expansion_floor"])
    # Running low on askable questions also raises expansion urgency.
    if len(queue) < limit:
        urgency = max(urgency, 0.5)

    return {
        "version": 3,
        "generated_at": generated_at,
        "expires_at": future_timestamp(expires_days),
        "policy": {
            "limit": limit,
            "arc_max": arc_max,
            "expires_days": expires_days,
            "allocation": "dynamic-focus-weighted",
            "candidate_policy": "accepted candidates are recommended for promotion but not asked until promoted to question-bank",
        },
        "allocation": {
            "global_fullness": round(fullness, 3),
            "focuses": [
                {
                    "id": fid,
                    "label": d["focus"].get("label", fid),
                    "tier": d["focus"].get("tier"),
                    "phase": d["focus"].get("phase", "active"),
                    "saturation": d["fill"]["saturation"],
                    "saturated": d["fill"]["saturated"],
                    "weight": round(d["weight"], 3),
                    "queued": per_focus.get(fid, 0),
                    "cap": focus_max.get(fid),
                }
                for fid, d in info.items()
            ],
            "self_floor": self_floor,
            "chapter_boost": {"cap": chapter_boost_max, "taken": chapter_boost_taken},
            "leverage": {
                "per_story": per_story,
                "minted": sorted(
                    str(q.get("id")) for q in pending if q.get("timeline_probe")
                ),
                "queued": sorted(
                    str(item["question_id"]) for item in queue
                    if str(item.get("group")) == "timeline"
                ),
            },
            "work_items": {
                "score_version": WORK_ITEM_SCORE_VERSION,
                "threshold": policy.get("work_item_queue_threshold"),
                "weights": dict(DEFAULT_WORK_ITEM_WEIGHTS),
                "queued": sorted(
                    str(item["work_item_id"]) for item in queue if item.get("work_item_id")
                ),
            },
            "expansion": {
                "urgency": round(urgency, 3),
                "recommended": urgency >= 0.5,
                "reason": "running low on askable questions" if len(queue) < limit
                          else f"global fullness {fullness:.0%}",
            },
        },
        "active_objectives": planner_state.get("active_objectives", []),
        "candidate_recommendations": accepted_candidate_recommendations(candidates),
        "queue": queue,
    }


def current_timeline_probes() -> dict:
    """The minted keystone questions in this vault's bank, or `{}` — GUARDED.

    A timeline problem must never be able to break the weekly queue, so every
    failure mode (an unreadable bank, an older package, a missing module)
    degrades to "no timeline questions", which is exactly v194's behavior.
    """
    try:
        import timeline_interaction  # noqa: PLC0415

        text = read_text(QUESTIONS_FILE)
        index = timeline_interaction.timeline_probe_index(text)
        # Wave F: the same rows, plus the work-item identity the whisper lane
        # matches on. A pre-wave-F row has no `work_item:` marker and its id is
        # DERIVED from the anchor it does carry, so the suppression rule works
        # on a bank minted by any version.
        table = published_work_item_aliases()
        markers = {
            row["bank_id"]: row["work_item_id"]
            for row in bank_work_items(text, aliases=table).values()
        }
        for bank_id, row in index.items():
            identity = markers.get(bank_id) or timeline_work_item_id(
                anchor=row.get("anchor"), anchor_kind=row.get("anchor_kind")
            )
            if identity:
                row["work_item_id"] = identity
        return index
    except Exception:  # noqa: BLE001
        return {}


# ---------------------------------------------------------------------------
# The work-item queue adapter (wave F — plan §2.3, §2.4, §8.5)
#
# v196 gave the timeline exactly ONE way into the daily question: a keystone,
# gated on leverage. That gate is a CLASS privilege wearing a number — it asks
# "is this a keystone?" before it asks "is this worth a day of the person's
# attention?", and everything that was not a keystone had no route at all.
#
# Wave F replaces the class gate with a VALUE gate. Any `TemporalWorkItem`
# whose `allowed_surfaces` includes `daily_question` is a queue CANDIDATE, and
# what earns it the slot is the §8.5 combined score. A keystone still usually
# wins — because reach and placement gain are two of the components and a
# keystone is a high-reach item by construction — but it wins by SCORING
# HIGHEST, never by being a keystone. Owner ethos, verbatim: "something of high
# value has a slot".
#
# Three properties are load-bearing here:
#
# **One identity, every surface.** The `work_item_id` from
# `temporal_projection.derive_work_item_id` travels into the minted bank row's
# provenance comment beside the `tl:` keystone id, and into the arc card's
# whisper intent. That is what makes "the same item must not be today's
# question AND today's whisper" a set operation, and what lets an answer on any
# surface close the item on the others.
#
# **The queue is normalized, not maximized.** Cadence, diversity and the group
# caps are NOT part of the score — they are admission policy applied after
# scoring, so `GROUP_CAPS["timeline"]` still bounds the whole lane at one
# question a week no matter how many items clear the threshold (§8.5: "change
# only from evidence").
#
# **Protections are refusals, not weights.** A generic loss-discovery opener is
# refused by name however it is scored (§2.4), because "offer-only" is a
# product rule and a rule you can outbid is not a rule.
# ---------------------------------------------------------------------------

#: Bumped whenever the formula below changes meaning. Every scored candidate
#: carries it, so a queue built under an older formula is recognizable rather
#: than silently comparable.
WORK_ITEM_SCORE_VERSION = 1

#: The components, in the order §8.5 lists them. Each is normalized `0.0..1.0`
#: BEFORE weighting, so a weight is readable as "how much of the decision is
#: this" rather than as an unbounded nudge.
WORK_ITEM_SCORE_COMPONENTS = (
    "person_value",
    "placement_gain",
    "downstream_reach",
    "context_fit",
    "interaction_cost",
    "sensitivity",
)

#: A deliberately SIMPLE first cut (§8.5: "simple first cut, components exposed
#: for tuning"). The four positive weights sum to 1.0, so a perfect item scores
#: 1.0 before costs; the two costs subtract, so an expensive or sensitive item
#: has to be genuinely valuable to survive them. These are a dict, not
#: constants folded into the arithmetic, precisely so tuning is an edit to one
#: readable table and the components stay individually inspectable.
DEFAULT_WORK_ITEM_WEIGHTS = {
    "person_value": 0.35,
    "placement_gain": 0.25,
    "downstream_reach": 0.25,
    "context_fit": 0.15,
    "interaction_cost": -0.15,
    "sensitivity": -0.20,
}

#: Placement gain by work-item kind — what answering settles about THIS node: a
#: missing anchor PLACES it, a precision gap only sharpens one already placed,
#: and a contradiction settles a node the person can currently see is wrong.
#:
#: This is deliberately NOT read from `system_value`. v224's derivation computes
#: `system_value` as `reach / REACH_SATURATION` — it is the DOWNSTREAM component,
#: what the answer settles about OTHER nodes — so scoring it as placement gain
#: too would count reach twice and leave placement gain unexpressed. An item may
#: still override this with an explicit `placement_gain`.
WORK_ITEM_PLACEMENT_GAIN = {
    "missing_anchor": 0.8,
    "precision_gap": 0.4,
    "contradiction": 0.7,
    "identity_uncertain": 0.5,
    # `timeline-rules:4`: the node is co-located but not placed, and the answer
    # is a choice between spans the substrate already holds — so it places the
    # node like a missing anchor does, at a fraction of the recall cost.
    "place_ambiguous": 0.8,
    # E-L2a §7.2: the same arithmetic for the same reason — the person is
    # choosing between tenures the substrate already holds, not recalling a
    # number, so it places the node like a missing anchor at a fraction of
    # the recall cost.
    "tenure_ambiguous": 0.8,
    # E-L2b §7.2: answering it does not place the member node it is minted on
    # — that stay is already dated — it CORRECTS one of two spans everything
    # else is measured against. Scored like a contradiction, which is the
    # other kind whose answer repairs a node rather than placing it.
    "residence_overlap": 0.7,
    # E-L2c §7.2/§8: a chain gap places a whole NEW stretch nobody has told
    # us about — closer to a missing anchor than to a choice between spans
    # already held (`place_ambiguous`), but the answer is likely to be a
    # whole new entry rather than one date, so it is scored a little below
    # `missing_anchor`'s single-node recall.
    "chain_gap": 0.6,
}

#: What an item is worth when it says nothing. Neutral on value and fit, mildly
#: costly (a temporal ask always spends some of a conversation), never sensitive
#: by default — sensitivity is a claim the minter makes, not one we assume.
WORK_ITEM_SCORE_DEFAULTS = {
    "person_value": 0.5,
    "context_fit": 0.5,
    "interaction_cost": 0.3,
    "sensitivity": 0.0,
}

#: How much RAW reach saturates the reach component, for the items that arrive
#: carrying a raw count instead of a normalized one. Quoted in the SAME currency
#: as `timeline_leverage_per_story` — twice the exchange rate — so the one
#: timeline dial keeps governing both minting and scoring: an item whose answer
#: would place 2× what one ordinary story answer is worth has maxed the component
#: out, and everything below scales linearly.
#:
#: v224's derivation normalizes reach ITSELF, against its own
#: `temporal_timeline.REACH_SATURATION`, and hands the result over as
#: `system_value` with the raw count beside it in `CalculatedTimeline.reach`.
#: That number is taken as given — "computed where the evidence is" is the whole
#: argument for wave D doing it — so this factor governs only v196's keystone
#: leverage. The two scales are honestly different quantities (unplaced NODES vs
#: timeline unknowns) and both raw counts stay visible on every score, which is
#: precisely what a later calibration pass needs.
WORK_ITEM_REACH_SATURATION_FACTOR = 2.0

DAILY_QUESTION_SURFACE = "daily_question"
WHISPER_SURFACE = "whisper"

#: §2.4, hard: loss discovery is OFFER-ONLY. The generic "have you lost
#: someone?" opener may live on Timeline and may be offered; it never becomes a
#: daily question, no matter what it scores and no matter what surfaces its
#: minter listed. Once a person NAMES someone who died, that item is about a
#: named subject and is an ordinary contextual question again — which is why
#: the refusal keys off the generic intent and the un-named subject, never off
#: the word "loss" appearing anywhere.
LOSS_DISCOVERY_INTENTS = frozenset({"loss_discovery", "losses_discovery", "loss_offer"})
LOSS_DISCOVERY_SUBJECTS = frozenset({
    "losses", "loss", "area:losses", "landmark:losses", "landmark/losses",
})

#: DEPRECATED (O-E6), and the only place in this module that may name it.
#: `temporal_anchor` was the keystone lane's single flat spelling of "the field
#: this gap is missing", and it was ALSO in
#: `temporal_projection.WORK_ITEM_IDENTITY_KEYS` — so the same birthday minted
#: here and minted by the substrate's fold were two `work:` ids for one
#: question, and answer-once closure is by identity. The canonical vocabulary
#: is `temporal_work_items.CANONICAL_REQUESTED_FIELDS`; this name survives for
#: readers that already import it and is asserted equal to
#: `temporal_work_items.LEGACY_REQUESTED_FIELD` by
#: `tests/test_work_item_aliases.py`. Nothing here mints under it any more.
TIMELINE_REQUESTED_FIELD = "temporal_anchor"


def _work_item_vocabulary():
    """`temporal_work_items`, or `None` — GUARDED, like every seam here.

    Every reach into the temporal package from this module is lazy and
    swallowed, because the weekly queue must never be able to break on a
    projection problem. One canonicalization that could not run degrades to
    "the id you were given", which is what the pre-O-E6 behaviour was.
    """
    try:
        import temporal_work_items  # noqa: PLC0415
    except Exception:  # noqa: BLE001
        return None
    # `import` hands back whatever sits in `sys.modules` under that name, which
    # a partially vendored package or a test double can make into something
    # that is not this module at all. Ask for the door before using it.
    if not hasattr(temporal_work_items, "canonical_ask"):
        return None
    return temporal_work_items


def _aliases_for(question_bank_text: object, aliases: object) -> dict:
    """Which alias map a bank-joining call should use.

    Explicit wins. Otherwise the map is read from the vault ONLY on the
    vault-bound path — the same seam issue #225 drew for the bank itself: a
    caller that injected a bank is vault-less on purpose and must not pick up
    the process checkout's published generation.
    """
    if isinstance(aliases, dict):
        return aliases
    if question_bank_text is None:
        return published_work_item_aliases()
    return {}


def published_work_item_aliases() -> dict:
    """`{legacy_id: canonical_id}` from the published generation, or `{}`.

    O-E6: the map is DERIVED and published beside the items in the same
    generation (`work-items.json`), so reading it here is reading the same
    bytes the items came from — never a second, drifting table.
    """
    try:
        import temporal_projection  # noqa: PLC0415

        published = read_json(REPO_DIR / temporal_projection.WORK_ITEMS_FILE, None)
    except Exception:  # noqa: BLE001
        return {}
    aliases = published.get("work_item_aliases") if isinstance(published, dict) else None
    if not isinstance(aliases, dict):
        return {}
    return {
        str(old): str(new)
        for old, new in aliases.items()
        if str(old or "").strip() and str(new or "").strip()
    }


def resolve_work_item_id(ref: object, *, aliases: object = None) -> str:
    """The ONE lookup, re-exported so the queue has a single door — GUARDED.

    `aliases=None` reads the published map. An id that is already canonical, or
    that no map knows, comes back unchanged: resolution never invents an
    identity.
    """
    vocabulary = _work_item_vocabulary()
    table = published_work_item_aliases() if aliases is None else aliases
    if vocabulary is None:
        return str(ref or "").strip()
    return vocabulary.resolve_work_item_id(ref, aliases=table)

#: The bank provenance marker that carries the work-item identity. It is
#: APPENDED to v196's `timeline_probe:` comment rather than replacing it: the
#: comment stays a `timeline_probe` row for every existing reader
#: (`timeline_interaction.timeline_probe_index`, the conversation's keystone
#: match, the host), and gains one field.
WORK_ITEM_BANK_MARKER = "work_item"

_WORK_ITEM_BANK_ROW_RE = re.compile(r"^- \[( |x)\] (?P<qid>[A-Z]\d+[a-z]*): (?P<text>.+)$")
_WORK_ITEM_TAG_RE = re.compile(
    r"^\s*<!--\s*timeline_probe:\s*(?P<keystone_id>\S+);\s*anchor:\s*(?P<anchor>[^;]+);"
    r"\s*leverage:\s*(?P<leverage>\d+)"
)
_WORK_ITEM_MARKER_RE = re.compile(
    WORK_ITEM_BANK_MARKER + r":\s*(?P<work_item_id>[A-Za-z0-9:._-]+)"
)


def _clamp_unit(value: object, default: float = 0.0) -> float:
    """`0.0..1.0`, or `default`. One definition (`temporal_work_items`)."""
    vocabulary = _work_item_vocabulary()
    if vocabulary is not None:
        return vocabulary.clamp_unit(value, default)
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return float(default)
    if math.isnan(number):
        return float(default)
    return max(0.0, min(1.0, number))


def timeline_work_item_id(*, anchor: object = "", unknown_key: object = "",
                          kind: str = "missing_anchor",
                          requested_field: object = None,
                          anchor_kind: object = None) -> str:
    """The ONE work-item identity for a timeline ask — GUARDED.

    A keystone names an ANCHOR; a whisper is chosen for a GAP that some anchor
    would resolve. Both derive the id from the anchor when there is one, so the
    keystone question and the whisper about the gap it resolves are provably
    the same item (plan §2.3, §5.4). A gap with no resolving anchor falls back
    to its own unknown key, which is still stable across rebuilds.

    **O-E6: and so is the SUBSTRATE's own item for the same gap.** This used to
    mint under `temporal_anchor`, which put it in a different identity from the
    fold's `birth_date` / `date` / `start_date` / `order` — two ids, one
    question, and the person could answer their birthday on Timeline and be
    asked for it by the daily question the same week. The whole tuple is now
    canonicalized by `temporal_work_items.canonical_ask`: the `birth` anchor
    becomes the owner's `self` subject and `temporal_anchor` becomes
    `birth_date`, together, because moving one half without the other mints a
    third id rather than one.

    Returns `""` when there is nothing to be about — an id derived from nothing
    would collide every anchorless gap into one item, which is worse than
    having no id at all.
    """
    subject = str(anchor or "").strip()
    event = str(unknown_key or "").strip()
    if not subject and not event:
        return ""
    vocabulary = _work_item_vocabulary()
    if vocabulary is None:
        return ""
    try:
        return vocabulary.canonical_work_item_id(
            kind=kind,
            subject_ref=subject or None,
            event_ref=None if subject else event,
            requested_field=requested_field,
            anchor_kind=anchor_kind,
        )
    except Exception:  # noqa: BLE001 — a projection problem never breaks the queue
        return ""


def work_item_from_keystone(keystone: object, *, now: str | None = None) -> dict | None:
    """One keystone -> one `TemporalWorkItem` dict — the generalization seam.

    This is where v196's keystone stops being a privileged class and becomes an
    ordinary candidate: its leverage becomes `downstream_reach`, its probe
    becomes `prompt_intent`, and from here on it competes on the same score as
    anything else the substrate implies.
    """
    row = keystone if isinstance(keystone, dict) else {}
    anchor = str(row.get("anchor") or "").strip()
    probe = row.get("probe") if isinstance(row.get("probe"), dict) else {}
    text = " ".join(str(probe.get("text") or "").split())
    if not anchor or not text:
        return None
    # O-E6: the keystone's identity tuple is CANONICALIZED before it is
    # validated, so the row this returns is the same item the fold minted for
    # the same gap rather than a second one wearing the old spelling. A
    # keystone row that already carries `work_item_id` (`timeline.keystones`
    # derives it the same way) is believed, and asserted equal below.
    vocabulary = _work_item_vocabulary()
    if vocabulary is None:
        return None
    kind, subject_ref, event_ref, requested_field = vocabulary.canonical_ask(
        kind=vocabulary.BIRTH_ORIGIN_KIND,
        subject_ref=anchor,
        requested_field=row.get("requested_field"),
        anchor_kind=row.get("anchor_kind") or row.get("kind"),
    )
    payload = {
        "kind": kind,
        "state": "open",
        "subject_ref": subject_ref,
        "event_ref": event_ref,
        "requested_field": requested_field,
        "prompt_intent": text,
        "allowed_surfaces": ["timeline", WHISPER_SURFACE, DAILY_QUESTION_SURFACE],
        "created_at": now or now_utc(),
    }
    try:
        import temporal_projection  # noqa: PLC0415

        item = temporal_projection.validate_temporal_work_item(payload)
    except Exception:  # noqa: BLE001
        return None
    item["downstream_reach"] = int(row.get("leverage") or 0)
    item["keystone"] = dict(row)
    return item


def current_work_items(*, timeline_payload: object = None) -> list[dict]:
    """Every work item this vault currently implies — GUARDED, deduped by id.

    Two sources today, in precedence order:

    1. `state/temporal_claims/work-items.json`, wave D's published projection.
       Nothing writes it yet — D1 mints work items from the calculated timeline
       and the stitch that publishes them is a follow-up — so this read is
       normally empty and is deliberately written to tolerate that.
    2. the timeline's own keystones, which is the whole supply today.

    The projection wins a tie because it is the richer record: it knows the
    claims behind the item and the person value of the subject, where a
    keystone knows only reach.
    """
    return _dedupe_work_items(
        _published_work_items() + _keystone_work_items(timeline_payload),
        aliases=published_work_item_aliases(),
    )


def work_items_from_projection(payload: object) -> list[dict]:
    """Wave D's published projection -> queue-ready work items.

    Consumes `temporal_timeline.CalculatedTimeline.to_dict()` exactly as it is
    written: `{"work_items": [...], "reach": {work_item_id: count}, ...}`. A
    bare list is accepted too, for a host that publishes only the items.

    Three things travel across the seam and each is deliberate:

    * the item itself, re-validated through v220's own door, because a stored
      envelope is re-read against the CURRENT classes and a projection written
      by an older release must fail as one bad row rather than as a broken week;
    * `reach`, the RAW count the derivation kept beside its normalized
      `system_value` precisely so wave F could calibrate against it — it is
      annotation here, not an input the score double-counts;
    * `combined_score`, preserved as `derivation_score`. Wave F owns the queue's
      number (§8.5) and overwrites `combined_score`, but throwing wave D's away
      would make a disagreement between the two invisible, and a disagreement
      between two scorers is the thing worth being able to see.
    """
    rows = payload.get("work_items") if isinstance(payload, dict) else payload
    reach = payload.get("reach") if isinstance(payload, dict) else None
    reach = reach if isinstance(reach, dict) else {}
    items: list[dict] = []
    for row in rows if isinstance(rows, list) else ():
        if not isinstance(row, dict):
            continue
        item = _validated_work_item(row)
        if item is None:
            continue
        identity = str(item.get("work_item_id") or "")
        if identity in reach:
            item["downstream_reach"] = reach[identity]
        for key in ("downstream_reach", "leverage", "placement_gain", "keystone"):
            if row.get(key) is not None:
                item[key] = row[key]
        if row.get("combined_score") is not None:
            item["derivation_score"] = row["combined_score"]
        items.append(item)
    return items


def _published_work_items() -> list[dict]:
    """Wave D's `work-items.json`, or `[]` — one bad row never hides the rest."""
    try:
        import temporal_projection  # noqa: PLC0415

        published = read_json(REPO_DIR / temporal_projection.WORK_ITEMS_FILE, None)
    except Exception:  # noqa: BLE001
        return []
    return work_items_from_projection(published)


def _validated_work_item(row: dict) -> dict | None:
    try:
        import temporal_projection  # noqa: PLC0415

        return temporal_projection.validate_temporal_work_item(row, now=now_utc())
    except Exception:  # noqa: BLE001
        return None


def _keystone_work_items(timeline_payload: object = None) -> list[dict]:
    """This vault's keystones, adapted into ordinary work items, or `[]`."""
    try:
        import timeline  # noqa: PLC0415

        payload = timeline_payload if isinstance(timeline_payload, dict) else timeline.timeline_data()
        keystones = timeline.keystones(payload) or ()
    except Exception:  # noqa: BLE001 — a timeline problem is "no timeline items"
        return []
    adapted = [work_item_from_keystone(keystone) for keystone in keystones]
    return [item for item in adapted if item]


def _dedupe_work_items(items: list[dict], *, aliases: object = None) -> list[dict]:
    """One row per CANONICAL identity, first source winning.

    O-E6: the dedupe KEY is resolved through the alias map, so a stale
    published generation holding a legacy id and a freshly adapted keystone
    holding the canonical one collapse into one row instead of competing as
    two questions about the same gap. The row itself is kept as it arrived —
    resolution decides what is the same, never what a row says.
    """
    table = aliases if isinstance(aliases, dict) else {}
    deduped: dict[str, dict] = {}
    for item in items:
        deduped.setdefault(
            resolve_work_item_id(item.get("work_item_id"), aliases=table), item
        )
    deduped.pop("", None)
    return list(deduped.values())


def is_loss_discovery(item: object) -> bool:
    """Is this the generic loss-discovery opener? (§2.4 — offer-only.)

    True only for the GENERIC prompt: a named person who died is an ordinary
    subject and an ordinary contextual question.
    """
    row = item if isinstance(item, dict) else {}
    intent = str(row.get("prompt_intent") or "").strip().lower()
    if intent in LOSS_DISCOVERY_INTENTS:
        return True
    subject = str(row.get("subject_ref") or "").strip().lower()
    event = str(row.get("event_ref") or "").strip().lower()
    return (subject in LOSS_DISCOVERY_SUBJECTS and not event) or (
        event in LOSS_DISCOVERY_SUBJECTS and not subject
    )


def work_item_reach(item: object) -> int:
    """How many uncertain things one answer would constrain.

    Source order — explicit annotation, then v196's `leverage` under its old
    name, then the keystone the item was adapted from, then zero. A work item
    with no reach is not disqualified; it simply earns nothing from the reach
    component.
    """
    row = item if isinstance(item, dict) else {}
    for key in ("downstream_reach", "leverage"):
        if row.get(key) is not None:
            try:
                return max(0, int(row[key]))
            except (TypeError, ValueError):
                return 0
    keystone = row.get("keystone")
    if isinstance(keystone, dict):
        try:
            return max(0, int(keystone.get("leverage") or 0))
        except (TypeError, ValueError):
            return 0
    return 0


def score_work_item(item: object, *, weights: object = None, policy: object = None,
                    reach: object = None) -> dict:
    """The §8.5 combined score for one work item — pure, versioned, inspectable.

    Returns the components as well as the number, because a queue nobody can
    explain is a queue nobody can tune: the weekly queue's own metadata carries
    these, and every future adjustment is a change to
    :data:`DEFAULT_WORK_ITEM_WEIGHTS` with a bump to
    :data:`WORK_ITEM_SCORE_VERSION`, not a new special case somewhere.

    Cadence, diversity and the group caps are deliberately ABSENT: they bound
    admission after the ranking (`GROUP_CAPS["timeline"]`), and folding them in
    here would make an item's own worth depend on what else happened to be
    queued that week.

    One honest gap, named rather than papered: for a CONTRADICTION the
    derivation states `system_value` as conflict severity, not reach, so this
    function would read severity under the reach component's name. It is inert
    today — `temporal_timeline.SURFACES_BY_KIND["contradiction"]` lists
    `mirror`, never `daily_question`, because Mirror's daily convergence is
    deferred (§2.5, lifehug/lifehug-platform#663) — so no contradiction is ever
    a queue candidate. When that lands, severity earns its own component and
    :data:`WORK_ITEM_SCORE_VERSION` bumps; a test pins the exclusion until then.
    """
    row = item if isinstance(item, dict) else {}
    lane = {**DEFAULT_LANE_POLICY, **(policy if isinstance(policy, dict) else {})}
    table = {**DEFAULT_WORK_ITEM_WEIGHTS, **(weights if isinstance(weights, dict) else {})}
    per_story = float(lane.get("timeline_leverage_per_story",
                               DEFAULT_LANE_POLICY["timeline_leverage_per_story"]) or 0)
    saturation = max(1.0, per_story * WORK_ITEM_REACH_SATURATION_FACTOR)
    measured_reach = work_item_reach(row) if reach is None else max(0, int(reach))

    kind = str(row.get("kind") or "")
    placement = row.get("placement_gain")
    if placement is None:
        placement = WORK_ITEM_PLACEMENT_GAIN.get(kind, 0.5)

    # Reach, from whoever normalized it. The derivation states `system_value` as
    # `reach / REACH_SATURATION` and is believed; a keystone states a raw
    # leverage count and is normalized here. `reach_source` is on the score so a
    # week is readable rather than merely reproducible.
    if row.get("system_value") is not None:
        reach_component = _clamp_unit(row.get("system_value"))
        reach_source = "derivation"
    elif measured_reach:
        reach_component = _clamp_unit(measured_reach / saturation)
        reach_source = "leverage"
    else:
        reach_component = 0.0
        reach_source = "none"

    components = {
        "person_value": _clamp_unit(row.get("person_value"),
                                    WORK_ITEM_SCORE_DEFAULTS["person_value"]),
        "placement_gain": _clamp_unit(placement, 0.5),
        "downstream_reach": reach_component,
        "context_fit": _clamp_unit(row.get("context_fit"),
                                   WORK_ITEM_SCORE_DEFAULTS["context_fit"]),
        "interaction_cost": _clamp_unit(row.get("interaction_cost"),
                                        WORK_ITEM_SCORE_DEFAULTS["interaction_cost"]),
        "sensitivity": _clamp_unit(row.get("sensitivity"),
                                   WORK_ITEM_SCORE_DEFAULTS["sensitivity"]),
    }
    combined = sum(float(table.get(name, 0.0)) * components[name]
                   for name in WORK_ITEM_SCORE_COMPONENTS)
    return {
        "work_item_id": str(row.get("work_item_id") or ""),
        "kind": kind,
        "score_version": WORK_ITEM_SCORE_VERSION,
        "reach": measured_reach,
        "reach_source": reach_source,
        "components": {name: round(components[name], 4) for name in WORK_ITEM_SCORE_COMPONENTS},
        "weights": {name: float(table.get(name, 0.0)) for name in WORK_ITEM_SCORE_COMPONENTS},
        "combined_score": round(_clamp_unit(combined), 4),
    }


def bank_work_items(question_bank_text: object, *, aliases: object = None) -> dict:
    """`{work_item_id: row}` for every timeline-origin question in the bank.

    Reads the bank's own provenance comment. A row minted before wave F carries
    no `work_item:` field — its identity is DERIVED from the anchor it does
    carry, by the same function everything else uses, so the pre-wave-F bank
    dedupes and closes exactly like a post-wave-F one and no migration exists.

    **O-E6: a row whose marker holds a LEGACY id is keyed under the canonical
    one.** The bank is the answer-once ledger, so a marker written last month
    under `temporal_anchor` has to tick the item the fold mints today or the
    person is asked their own birthday twice. `aliases` is the published map
    (`published_work_item_aliases`); pure by default, so a caller with no vault
    behaves exactly as it did before the map existed.
    """
    table = aliases if isinstance(aliases, dict) else {}
    text = str(question_bank_text or "")
    rows: dict[str, dict] = {}
    lines = text.splitlines()
    for position, line in enumerate(lines):
        bank_row = _WORK_ITEM_BANK_ROW_RE.match(line)
        if not bank_row or position + 1 >= len(lines):
            continue
        tag = _WORK_ITEM_TAG_RE.match(lines[position + 1])
        if not tag:
            continue
        marker = _WORK_ITEM_MARKER_RE.search(lines[position + 1])
        anchor = tag.group("anchor").strip()
        work_item_id = resolve_work_item_id(
            marker.group("work_item_id") if marker else timeline_work_item_id(anchor=anchor),
            aliases=table,
        )
        if not work_item_id:
            continue
        rows.setdefault(work_item_id, {
            "work_item_id": work_item_id,
            "bank_id": bank_row.group("qid"),
            "question_id": tag.group("keystone_id"),
            "anchor": anchor,
            "leverage": int(tag.group("leverage")),
            "text": bank_row.group("text").strip(),
            "answered": bank_row.group(1) == "x",
        })
    return rows


def work_item_states_from_bank(question_bank_text: object, *,
                               aliases: object = None) -> dict:
    """`{work_item_id: state}` — the deterministic cross-surface linkage.

    This is the answer-once half of plan §2.3: a bank row that is checked means
    the person answered that item, wherever they answered it, so the queue
    candidate is `answered` and the whisper for the same id is gone. The state
    lives in the bank, which is durable and already the thing "asked once,
    answered once" is expressed in — no second ledger, no second truth.
    """
    return {
        work_item_id: ("answered" if row["answered"] else "offered")
        for work_item_id, row in bank_work_items(
            question_bank_text, aliases=aliases
        ).items()
    }


def close_answered_work_items(items: object, *, question_bank_text: object = None,
                              aliases: object = None) -> list[dict]:
    """Stamp each item with the state the bank proves it is in.

    Items the bank has never seen are returned untouched: absence of a row is
    "not asked yet", never "answered". O-E6: a bank row under a legacy id
    answers the canonical item, because both sides of the join go through
    `resolve_work_item_id` first.
    """
    text = read_text(QUESTIONS_FILE) if question_bank_text is None else question_bank_text
    table = _aliases_for(question_bank_text, aliases)
    states = work_item_states_from_bank(text, aliases=table)
    closed: list[dict] = []
    for item in items or ():
        if not isinstance(item, dict):
            continue
        state = states.get(
            resolve_work_item_id(item.get("work_item_id"), aliases=table)
        )
        closed.append({**item, "state": state} if state else dict(item))
    return closed


def queue_candidates(items: object = None, *, question_bank_text: object = None,
                     policy: object = None, weights: object = None,
                     aliases: object = None) -> list[dict]:
    """The eligible, scored, ranked work items — highest combined score first.

    The admission ladder, in order, and each rung is a REFUSAL with a name:

    * `loss_discovery` — §2.4, offer-only, checked before anything else so no
      score can buy the slot;
    * `surface_not_allowed` — the item does not list `daily_question`, which is
      how a Timeline-only item stays Timeline-only;
    * `already_answered` / `already_asked` — the bank already holds a live or
      checked row for this identity ("asked once, answered once", the bank's
      own mechanism rather than a second one);
    * `below_threshold` — §2.3's "ordinary low-value gaps remain on Timeline
      and do not crowd out the daily experience", expressed as one number.

    Ties break on `work_item_id` so the ranking is total and a rebuild produces
    the same order.
    """
    lane = {**DEFAULT_LANE_POLICY, **(policy if isinstance(policy, dict) else {})}
    threshold = float(lane.get("work_item_queue_threshold",
                               DEFAULT_LANE_POLICY["work_item_queue_threshold"]) or 0)
    rows = list(items) if isinstance(items, (list, tuple)) else current_work_items()
    text = read_text(QUESTIONS_FILE) if question_bank_text is None else question_bank_text
    table = _aliases_for(question_bank_text, aliases)
    known = bank_work_items(text, aliases=table)
    candidates: list[dict] = []
    for item in rows:
        if not isinstance(item, dict):
            continue
        if is_loss_discovery(item):
            continue
        surfaces = item.get("allowed_surfaces") or ()
        if DAILY_QUESTION_SURFACE not in surfaces:
            continue
        if str(item.get("state") or "open") not in ("open", "offered"):
            continue
        # O-E6: both sides of "has this already been asked?" are canonical, so
        # a bank row minted under a legacy id refuses the item it was about.
        identity = resolve_work_item_id(item.get("work_item_id"), aliases=table)
        if not identity or identity in known:
            continue
        score = score_work_item(item, weights=weights, policy=lane)
        if score["combined_score"] < threshold:
            continue
        candidate = {**item, "score": score, "combined_score": score["combined_score"]}
        if item.get("combined_score") is not None and "derivation_score" not in candidate:
            # Wave D scored it too, under its own formula. Wave F's number wins
            # (§8.5), but the other one is kept visible rather than overwritten.
            candidate["derivation_score"] = item["combined_score"]
        candidates.append(candidate)
    candidates.sort(key=lambda row: (-row["combined_score"], str(row["work_item_id"])))
    return candidates


def mint_work_item_question(item: object, *, next_question_id: object,
                            minted_at: str | None = None) -> dict | None:
    """One work item -> one bank ROW carrying BOTH identities (pure).

    The row is minted by `timeline_interaction.mint_keystone_question` — one
    row minter, not two — and the work-item id is appended to the provenance
    comment it produced. Every existing reader still sees a `timeline_probe`
    row with an anchor and a leverage; the new field is additive, which is why
    no reader had to change.
    """
    row = item if isinstance(item, dict) else {}
    text = " ".join(str(row.get("prompt_intent") or "").split())
    if not text:
        return None
    keystone = row.get("keystone") if isinstance(row.get("keystone"), dict) else None
    try:
        import timeline_interaction  # noqa: PLC0415

        if keystone is None:
            anchor = str(row.get("subject_ref") or row.get("event_ref") or "").strip()
            if not anchor:
                return None
            keystone = {
                "anchor": anchor,
                "question_id": timeline_interaction.keystone_question_id(anchor),
                "label": anchor,
                "leverage": work_item_reach(row),
                "probe": {"text": text, "step": ""},
                "unknown_keys": [],
                "anchors": [],
            }
        minted = timeline_interaction.mint_keystone_question(
            keystone, next_question_id=next_question_id, minted_at=minted_at)
    except Exception:  # noqa: BLE001
        return None
    if not minted:
        return None
    identity = str(row.get("work_item_id") or "")
    if identity:
        minted["work_item_id"] = identity
        minted["line"] = minted["line"].replace(
            " -->", f"; {WORK_ITEM_BANK_MARKER}: {identity} -->", 1)
    minted["combined_score"] = row.get("combined_score")
    return minted


def mint_queue_questions(*, work_items: object = None, dry_run: bool = False,
                         question_bank_text: object = None) -> list[dict]:
    """Mint every work item that EARNED a slot into the bank — GUARDED.

    Runs at `planner-queue` time only, before the queue is built, so a minted
    question is an ordinary pending bank question by the time anything scores
    it as a question. What changed in wave F is which items may be minted: not
    "the keystones whose leverage clears the exchange rate" but "the work items
    whose combined score clears the queue threshold" — a keystone reaches the
    bank through exactly the same door as a high-value ordinary landmark gap,
    and reaches the daily question through the same weekly `timeline` group cap
    it always did.

    Every failure mode still degrades to "no timeline questions this week": the
    weekly queue must never be able to break on a timeline problem.
    """
    try:
        from question_candidates import next_question_id  # noqa: PLC0415

        policy = {**DEFAULT_LANE_POLICY, **load_planner_state().get("lane_policy", {})}
        text = read_text(QUESTIONS_FILE) if question_bank_text is None else str(question_bank_text)
        table = _aliases_for(question_bank_text, None)
        candidates = queue_candidates(work_items, question_bank_text=text,
                                      policy=policy, aliases=table)
        if not candidates:
            return []
        import timeline_interaction  # noqa: PLC0415

        minted: list[dict] = []
        seen = set(bank_work_items(text, aliases=table))
        for candidate in candidates:
            if resolve_work_item_id(candidate.get("work_item_id"), aliases=table) in seen:
                continue
            row = mint_work_item_question(
                candidate,
                next_question_id=lambda category: next_question_id(text, category))
            if not row:
                continue
            text = timeline_interaction.insert_keystone_question(text, row)
            seen.add(resolve_work_item_id(candidate.get("work_item_id"), aliases=table))
            minted.append(row)
        if minted and not dry_run and question_bank_text is None:
            write_text(QUESTIONS_FILE, text)
        return minted
    except Exception as exc:  # noqa: BLE001
        # Ledger only a run bound to the process vault (issue #225): an
        # injected-bank run is vault-less — the SAME seam that already gates
        # the bank write above — so a test never appends to the checkout's
        # own state/learning_failures.jsonl.
        if question_bank_text is None:
            record_learning_failure("question_planner", "mint_queue_questions", exc)
        return []


def mint_keystone_questions(*, dry_run: bool = False) -> list[dict]:
    """v196's name for what is now the general path — kept, delegating.

    A keystone has no separate minting route any more: it is adapted into a
    work item and minted if, and only if, its combined score earns the slot.
    The name survives because the CLI, the platform's weekly maintenance and
    v196's own tests all call it, and because "mint the timeline's questions"
    is still exactly what it does.
    """
    return mint_queue_questions(dry_run=dry_run)


def queue_is_stale(queue_data: dict) -> bool:
    if not queue_data.get("queue"):
        return False
    expires = parse_time(queue_data.get("expires_at"))
    return bool(expires and expires <= datetime.now(timezone.utc))


def category_latest_dates(questions: list[dict], answer_dates: dict[str, str]) -> dict[str, str]:
    latest = {}
    for question in questions:
        qid = str(question["id"])
        if not question["answered"] or qid not in answer_dates:
            continue
        cat = str(question["category"])
        latest[cat] = max(latest.get(cat, ""), answer_dates[qid])
    return latest


def category_story_counts(questions: list[dict]) -> dict[str, Counter]:
    counts = defaultdict(Counter)
    for question in questions:
        cat = str(question["category"])
        counts[cat][infer_story_function(str(question["text"]))] += 1
    return counts


def report(limit: int = 10) -> int:
    questions, categories, coverage = load_question_state()
    candidates = load_candidates()
    planner_state = load_planner_state()
    queue_data = read_json(QUESTION_QUEUE_FILE, default={}) or {}
    queue = queue_data.get("queue", [])
    answer_dates = read_answer_dates()
    latest_dates = category_latest_dates(questions, answer_dates)
    story_counts = category_story_counts(questions)

    print("Lifehug Planner Report")
    print()

    zombies = zombie_focuses(resolve_roadmap().get("focuses", []))
    if zombies:
        print("⚠ Zombie Focuses (no question categories — the planner can NEVER ask about these):")
        for focus in zombies:
            print(f"- {focus.get('label', focus.get('id'))}: seed questions with "
                  f"`lifehug.py focus-set {focus.get('id')} ...` + a category, or remove it")
        print()

    objectives = [o for o in planner_state.get("active_objectives", []) if o.get("status", "active") == "active"]
    print("Planner state:")
    if objectives:
        for objective in objectives:
            cats = ",".join(objective.get("categories", [])) or "-"
            kws = ",".join(objective.get("keywords", [])) or "-"
            print(f"- {objective.get('label')} (categories: {cats}; keywords: {kws})")
    else:
        print("- active objectives: none")

    print()
    print("Coverage by group:")
    grouped = defaultdict(lambda: {"answered": 0, "total": 0})
    for cat_id, data in coverage["categories"].items():
        group = categories.get(cat_id, {}).get("group", "main")
        grouped[group]["answered"] += data["answered"]
        grouped[group]["total"] += data["total"]
    for group in sorted(grouped):
        data = grouped[group]
        ratio = data["answered"] / data["total"] if data["total"] else 0
        state_caps = dict(planner_state.get("caps", {}).get("group", {}))
        old_focus_group = "spot" "light"
        if "focus" not in state_caps and old_focus_group in state_caps:
            state_caps["focus"] = state_caps[old_focus_group]
        cap_map = dict(GROUP_CAPS)
        cap_map.update(state_caps)
        cap = cap_map.get(group)
        cap_text = f", cap {cap:.0%}" if isinstance(cap, float) else ""
        print(f"- {group}: {data['answered']}/{data['total']} ({ratio:.0%}{cap_text})")

    print()
    print("Story-function balance in open question bank:")
    pending_functions = Counter(infer_story_function(str(q["text"])) for q in questions if not q["answered"])
    total_pending = sum(pending_functions.values()) or 1
    for function_name in STORY_FUNCTIONS:
        count = pending_functions.get(function_name, 0)
        print(f"- {function_name}: {count} ({count / total_pending:.0%})")

    print()
    print("Lowest-coverage categories:")
    rows = []
    for cat_id, data in coverage["categories"].items():
        total = data["total"]
        ratio = data["answered"] / total if total else 1
        rows.append((ratio, cat_id, data))
    for ratio, cat_id, data in sorted(rows)[:8]:
        name = categories.get(cat_id, {}).get("name", cat_id)
        print(f"- {cat_id} {name}: {data['answered']}/{data['total']} ({ratio:.0%})")

    print()
    print("Stale or untouched categories:")
    stale_rows = []
    for cat_id, data in coverage["categories"].items():
        if data["answered"] >= data["total"]:
            continue
        stale_rows.append((latest_dates.get(cat_id) or "0000-00-00", cat_id, data))
    for latest, cat_id, data in sorted(stale_rows)[:8]:
        label = latest if latest != "0000-00-00" else "never answered"
        name = categories.get(cat_id, {}).get("name", cat_id)
        print(f"- {cat_id} {name}: latest {label}; open {data['total'] - data['answered']}")

    print()
    print("Overrepresented areas:")
    answered_total = sum(data["answered"] for data in coverage["categories"].values()) or 1
    over_rows = []
    for cat_id, data in coverage["categories"].items():
        share = data["answered"] / answered_total
        ratio = data["answered"] / data["total"] if data["total"] else 0
        if data["answered"] >= 5 or ratio >= 0.70:
            over_rows.append((share, ratio, cat_id, data))
    for share, ratio, cat_id, data in sorted(over_rows, reverse=True)[:8]:
        name = categories.get(cat_id, {}).get("name", cat_id)
        print(f"- {cat_id} {name}: {data['answered']} answers, {ratio:.0%} covered, {share:.0%} of all answers")

    print()
    print("Narrative weak spots:")
    weak_rows = []
    for cat_id, counts in story_counts.items():
        total = sum(counts.values()) or 1
        scene_like = counts["scene"] + counts["tension"] + counts["turning_point"]
        ratio = scene_like / total
        answered = coverage["categories"].get(cat_id, {}).get("answered", 0)
        if answered >= 4 and ratio < 0.35:
            weak_rows.append((ratio, cat_id, answered))
    if weak_rows:
        for ratio, cat_id, answered in sorted(weak_rows)[:8]:
            name = categories.get(cat_id, {}).get("name", cat_id)
            print(f"- {cat_id} {name}: {answered} answers, only {ratio:.0%} scene/tension/turning-point questions")
    else:
        print("- none detected")

    sources = read_manual_sources()
    all_sources = _count_all_sources()
    print()
    print(f"Recent ingested sources: {len(sources)} manual, {sum(all_sources.values())} total across all types")
    if all_sources:
        for stype, count in sorted(all_sources.items()):
            classified = _count_classified(stype)
            print(f"  {stype}: {count} ingested, {classified} classified")
    for source in sources[:5]:
        print(f"- {source['captured_at'] or 'unknown date'}: {source['title']} [{source['source']}]")

    candidate_counts = Counter(c.get("status", "candidate") for c in candidates)
    print()
    print(f"Question candidates: {sum(candidate_counts.values())} total")
    if candidate_counts:
        print("- statuses: " + ", ".join(f"{status}={candidate_counts[status]}" for status in sorted(candidate_counts)))
    open_candidates = [c for c in candidates if c.get("status") in {"candidate", "accepted", "deferred"}]
    for candidate in sorted(open_candidates, key=lambda c: c.get("priority", 0), reverse=True)[:8]:
        story_function = infer_story_function(str(candidate.get("text", "")), candidate.get("kind"))
        print(f"- {candidate.get('id')}: {story_function}; {candidate.get('text')} [{candidate.get('source_path')}]")

    print()
    if queue:
        status = "stale" if queue_is_stale(queue_data) else "active"
        print(f"Active planned queue: {len(queue)} item(s), {status}, expires {queue_data.get('expires_at', 'unknown')}")
        for item in queue[:10]:
            print(f"- {item['question_id']} ({item.get('group')}/{item.get('story_function')}): {item['reason']}")
    else:
        print("Active planned queue: none")

    preview = build_queue(
        limit,
        int(planner_state.get("queue", {}).get("arc_max", 2)),
        int(planner_state.get("queue", {}).get("expires_after_days", 7)),
        planner_state,
        timeline_probes=current_timeline_probes(),
    )
    print()
    print("Recommended next queue preview (read-only):")
    for item in preview["queue"][:limit]:
        print(f"- {item['question_id']} ({item['group']}/{item['story_function']}): {item['reason']}")
    if preview.get("candidate_recommendations"):
        print()
        print("Accepted candidate recommendations to promote:")
        for candidate in preview["candidate_recommendations"][:5]:
            print(f"- {candidate.get('id')}: {candidate.get('text')}")

    # Neighborhoods section
    neighborhoods_data = read_json(NEIGHBORHOODS_FILE, default={}) or {}
    neighborhoods = [
        apply_readiness(neighborhood, {"candidates": candidates}, questions)
        for neighborhood in neighborhoods_data.get("neighborhoods", [])
    ]
    if neighborhoods:
        by_status = Counter(n.get("readiness_status", "empty") for n in neighborhoods)
        print()
        print(f"Neighborhoods: {len(neighborhoods)} total")
        print(f"  readiness: {', '.join(f'{s}={c}' for s, c in sorted(by_status.items()))}")
        for nbhd in neighborhoods[:5]:
            counts = nbhd.get("arc_lifecycle_counts", {})
            total = counts.get("total_slots", 0)
            generated = counts.get("questions_generated", 0)
            promoted = counts.get("questions_promoted", 0)
            answered = counts.get("answers_captured", 0)
            answered_c = nbhd.get("answered_completeness", 0)
            ready = " ready" if nbhd.get("ready_to_draft") else ""
            print(f"  - {nbhd.get('title', '?')} ({nbhd.get('type', '?')}) [{nbhd.get('status', 'draft')}] "
                  f"target: {nbhd.get('target_output', '?')}, answer-ready: {answered_c:.0%}{ready} "
                  f"({answered}/{total} answered, {promoted}/{total} promoted, {generated}/{total} generated)")
    else:
        print()
        print("Neighborhoods: none")

    # Focus recommendations section
    focus_data = (
        read_json(FOCUS_RECS_FILE, default=None)
        or read_json(LEGACY_FOCUS_RECS_FILE, default={})
        or {}
    )
    recs = focus_data.get("recommendations", [])
    pending_recs = [r for r in recs if r.get("status") == "pending"]
    if recs:
        print()
        print(f"Focus recommendations: {len(recs)} total, {len(pending_recs)} pending")
        for rec in sorted(pending_recs, key=lambda r: -r.get("score", 0))[:5]:
            strength = rec.get("evidence_strength", "?")
            emoji = {"strong": "\U0001f7e2", "moderate": "\U0001f7e1", "weak": "\U0001f534"}.get(strength, "\u26aa")
            print(f"  {emoji} {rec.get('entity', '?')} ({rec.get('type', '?')}) — score: {rec.get('score', 0):.1f} [{strength}]")
    else:
        print()
        print("Focus recommendations: none (run recommend-focuses to generate)")

    unanswered = sum(1 for q in questions if not q["answered"])
    print()
    print(f"Unanswered question-bank items: {unanswered}")
    return 0


def print_state() -> int:
    print(json.dumps(load_planner_state(), indent=2))
    return 0


def add_objective(args: argparse.Namespace) -> int:
    state = load_planner_state(write_default=True)
    objective = {
        "id": f"obj-{slugify(args.objective_add)}",
        "label": args.objective_add,
        "status": "active",
        "categories": [c.upper() for c in args.objective_category],
        "keywords": args.objective_keyword,
        "max_questions": args.objective_max_questions,
        "created_at": now_utc(),
    }
    state.setdefault("active_objectives", []).append(objective)
    state["last_updated"] = now_utc()
    write_json(PLANNER_STATE_FILE, state)
    print(f"✓ Added planner objective: {objective['label']}")
    return 0


def clear_objectives() -> int:
    state = load_planner_state(write_default=True)
    state["active_objectives"] = []
    state["last_updated"] = now_utc()
    write_json(PLANNER_STATE_FILE, state)
    print("✓ Cleared planner objectives")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Lifehug question planner")
    parser.add_argument("--report", action="store_true", help="Show planner report")
    parser.add_argument("--write-queue", action="store_true", help="Write state/question_queue.json")
    parser.add_argument("--clear-queue", action="store_true")
    parser.add_argument("--state", action="store_true", help="Show planner state")
    parser.add_argument("--init-state", action="store_true", help="Create or refresh default planner state")
    parser.add_argument("--objective-add", help="Add an active planner objective")
    parser.add_argument("--objective-category", action="append", default=[])
    parser.add_argument("--objective-keyword", action="append", default=[])
    parser.add_argument("--objective-max-questions", type=int, default=3)
    parser.add_argument("--objective-clear", action="store_true")
    parser.add_argument("--limit", type=int, default=DEFAULT_DELIVERY_QUEUE_LIMIT)
    parser.add_argument("--arc-max", type=int, default=2)
    parser.add_argument("--expires-days", type=int, default=8)
    args = parser.parse_args()

    if args.init_state:
        load_planner_state(write_default=True)
        if not args.state:
            print(f"✓ Initialized planner state: {PLANNER_STATE_FILE.relative_to(PLANNER_STATE_FILE.parents[1])}")

    if args.state:
        return print_state()

    if args.objective_add:
        return add_objective(args)

    if args.objective_clear:
        return clear_objectives()

    if args.clear_queue:
        write_json(QUESTION_QUEUE_FILE, {"version": 2, "cleared_at": now_utc(), "queue": []})
        print("✓ Cleared question queue")
        return 0

    if args.write_queue:
        state = load_planner_state(write_default=True)
        mint_keystone_questions()
        data = build_queue(args.limit, args.arc_max, args.expires_days, state,
                           timeline_probes=current_timeline_probes())
        write_json(QUESTION_QUEUE_FILE, data)
        print(f"✓ Wrote planned queue: {len(data['queue'])} item(s), expires {data['expires_at']}")
        return 0

    return report(args.limit)


if __name__ == "__main__":
    raise SystemExit(main())
