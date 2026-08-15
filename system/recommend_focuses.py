#!/usr/bin/env python3
"""Recommend new Focus arcs based on answer/source analysis.

Usage:
    python3 system/recommend_focuses.py --recommend
    python3 system/recommend_focuses.py --recommend --min-score 10
    python3 system/recommend_focuses.py --recommend --include-dismissed
    python3 system/recommend_focuses.py --recommend --type person
    python3 system/recommend_focuses.py --dismiss rec-dad --reason "already covered"
    python3 system/recommend_focuses.py --approve rec-dad
    python3 system/recommend_focuses.py --json
"""

from __future__ import annotations

import argparse
import re
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

# Allow running from repo root or system/
SYSTEM_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SYSTEM_DIR))

from lifehug_core import (
    ANSWERS_DIR,
    CLASSIFICATIONS_DIR,
    MANUAL_SOURCES_DIR,
    QUESTIONS_FILE,
    FOCUS_RECS_FILE,
    LEGACY_FOCUS_RECS_FILE,
    WIKI_DIR,
    answer_body,
    answer_id_from_filename,
    load_config,
    normalized_focus_key,
    now_utc,
    parse_categories,
    parse_questions,
    read_json,
    slugify,
    write_json,
)
from progress import READY, verdict  # noqa: E402
from roadmap import focus_fill, load_roadmap, rebuild_roadmap  # noqa: E402

FOCUS_RECOMMENDATION_TYPES = ("person", "place", "period", "theme")

OLD_FOCUS_TERM = "Spot" "light"

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Issue #79: the score floor that separates "wait and see" from "genuinely
# strong candidate" — reused from _evidence_strength()'s own "moderate"
# cutoff below, so this isn't a second, competing threshold. A recommendation
# scoring at or above this is eligible for the ready_to_start flag (once the
# completion gate is open) and is exempt from rot-control expiry; below it,
# a recommendation is pending-but-quiet and eventually self-cleans.
FOCUS_READY_SCORE_FLOOR = 8.0

# Issue #79 rot control: a pending recommendation that has sat below
# FOCUS_READY_SCORE_FLOOR for this many weeks auto-dismisses instead of
# accumulating forever. Re-detection is not permanently blocked, but it is
# NOT a free pass either: recommend() only lets an expiry-dismissed entity
# back into "recommendations" once its re-detected score clears
# FOCUS_READY_SCORE_FLOOR — genuinely stronger evidence, not just showing up
# again unchanged. A dismissal is recognized as expiry-origin via the
# structured "dismissed_by": "expiry" marker (never by sniffing dismiss_reason
# text — an owner who happens to type "expired: ..." as a manual reason must
# not accidentally self-un-blocklist an entity).
FOCUS_RECOMMENDATION_EXPIRY_WEEKS = 6

# The structured marker distinguishing an automatic rot-control dismissal
# from an owner-issued one. See dismissed_by usage in apply_recommendation_expiry
# and the filtering in recommend().
EXPIRY_DISMISSED_BY = "expiry"

# ADR 0011 (the Convergence Principle's floor applied to focus creation):
# the owner's ratified "keep N focuses in development" target. Overridable
# per-vault via config.yaml's `focus_autopilot_target` (see
# resolve_autopilot_target); this is the module default, never a literal
# restated elsewhere (the viewer's policy line reads this constant).
AUTOPILOT_TARGET_DEVELOPING = 3

# Gentle by default: at most one auto-approval per weekly run, so the
# owner's "up to three" end-state is reached over successive weeks, not in
# one burst. --catch-up (manual CLI only, focus_autopilot(catch_up=True))
# raises the effective per-run cap to the target for the everything-done
# case.
AUTOPILOT_MAX_PER_RUN = 1

# approve_recommendation's additive provenance stamp. Manual approvals
# (CLI/viewer) keep the function's own "owner" default; only
# focus_autopilot() passes "auto". Records approved before this PR simply
# lack the field — absent means legacy, never re-derived.
AUTOPILOT_APPROVED_BY = "auto"
MANUAL_APPROVED_BY = "owner"

RELATIONSHIP_WORDS = re.compile(
    r"\b(mom|dad|mother|father|brother|sister|friend|mentor|boss|wife|husband|"
    r"partner|son|daughter|grandma|grandpa|grandfather|grandmother|uncle|aunt|"
    r"cousin|teacher|coach|pastor|priest|therapist|neighbor|colleague|roommate|"
    r"boyfriend|girlfriend|fiance[é]?|stepmother|stepfather|stepbrother|stepsister)\b",
    re.IGNORECASE,
)

# A person-name token: a normal Capitalized word (Emma, Taylor) OR a short
# all-caps initialism (AJ, JT). The initialism branch lets names like "AJ"
# through — the previous `[A-Z][a-z]+` form required a lowercase letter, so
# initials-style names were invisible. 4+ letter all-caps acronyms (NASA) are
# naturally excluded by the word boundaries around the match.
_NAME_TOKEN = r"(?:[A-Z][a-z]+|[A-Z]{2,3})"

PLACE_INDICATORS = re.compile(
    r"\b(lived in|moved to|grew up in|visited|traveled to|went to|school in|"
    r"church in|office in|home in|grew up|born in|raised in|based in|working in|"
    r"studying in|attending|from)\s+([A-Z][a-zA-Z\s,]+?)(?=[,\.;]|\s+(?:when|and|but|in|at|on)\b)",
    re.IGNORECASE,
)

TIME_PERIOD_PATTERNS = re.compile(
    r"\b(childhood|elementary school|middle school|high school|college|university|"
    r"first job|early career|grad school|graduate school|"
    r"(?:my\s+)?(?:early\s+|mid\s+|late\s+)?(?:teens|twenties|thirties|forties|fifties)|"
    r"(?:my\s+)?20s|(?:my\s+)?30s|(?:my\s+)?40s|(?:my\s+)?50s|"
    r"when I was \d+ years? old|at age \d+|in my \w+ year)",
    re.IGNORECASE,
)

THEME_KEYWORDS: dict[str, list[str]] = {
    "Faith": ["faith", "church", "god", "pray", "prayer", "spiritual", "religion",
               "religious", "worship", "bible", "jesus", "christ", "mosque", "temple",
               "synagogue", "holy", "sacred", "divine", "blessing", "ministry"],
    "Money": ["money", "poor", "rich", "broke", "wealthy", "afford", "financial",
               "debt", "poverty", "savings", "income", "salary", "paycheck",
               "struggling", "comfortable", "wealth"],
    "Belonging": ["belong", "belonging", "outsider", "fitting in", "lonely", "community",
                  "excluded", "included", "accepted", "rejected", "outcast", "fit in",
                  "part of", "included", "home"],
    "Grief": ["grief", "loss", "death", "died", "funeral", "mourning", "mourn",
               "grieve", "passed away", "passed on", "lost", "missing", "miss them",
               "gone", "terminal", "illness"],
    "Ambition": ["ambition", "ambitious", "drive", "hustle", "goal", "dream", "success",
                  "achieve", "accomplish", "aspire", "aspiration", "motivated", "hunger",
                  "pursue", "striving"],
    "Fear": ["fear", "scared", "anxious", "anxiety", "worried", "worry", "terrified",
              "terror", "panic", "afraid", "dread", "nervous", "phobia", "paranoid"],
    "Family": ["family", "home", "roots", "heritage", "tradition", "culture", "ancestry",
                "bloodline", "household", "upbringing", "legacy", "lineage", "kin"],
}

EMOTION_WORDS = re.compile(
    r"\b(love|loved|hate|hated|scared|afraid|fear|proud|miss|missing|grateful|"
    r"angry|anger|hurt|hurting|joy|happy|sad|devastated|heartbroken|inspired|"
    r"ashamed|embarrassed|grateful|resentful|bitter|hopeful|desperate|lonely|"
    r"adore|cherish|detest|terrified|anxious|relieved|overwhelmed)\b",
    re.IGNORECASE,
)

# Proper-noun pattern: capitalized word(s) not at sentence start
PROPER_NOUN_RE = re.compile(r"(?<![.!?]\s)(?<!\n)\b([A-Z][a-z]{2,}(?:\s+[A-Z][a-z]{2,})?)\b")

# Words to exclude from proper-noun extraction (common false positives)
STOPWORDS = {
    "I", "The", "A", "An", "This", "That", "These", "Those", "My", "Your",
    "His", "Her", "Our", "Their", "We", "He", "She", "They", "It", "But",
    "And", "Or", "So", "Because", "When", "Where", "What", "Who", "How",
    "Why", "If", "Then", "For", "From", "With", "At", "On", "In", "To",
    "By", "Of", "As", "Up", "Out", "About", "Into", "Through", "After",
    "Before", "During", "While", "Until", "Though", "Although", "Even",
    "Still", "Just", "Also", "Then", "Now", "Here", "There", "Back",
    "Very", "Really", "Always", "Never", "Sometimes", "Often", "Maybe",
    "God", "Jesus", "Lord",  # handled as themes instead
    "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday",
    "January", "February", "March", "April", "May", "June", "July",
    "August", "September", "October", "November", "December",
    "American", "Mexican", "Spanish", "English", "Latin", "Christian",
    # Pronouns / interrogatives / quantifiers / fillers the proper-noun scanner
    # mistakes for names. (entity_roster.py also gates these, but dropping them
    # here keeps the recommendation queue itself clean.)
    "You", "Which", "Some", "Not", "Question", "Being", "Things", "Pure",
    "Growing", "Missed", "Answered", "Dating", "Someone", "Something", "Anyone",
    "Everyone", "Nobody", "Somebody", "Everybody", "Anything", "Nothing",
    "Both", "Each", "Either", "Neither", "One", "Two", "Three", "Many", "Most",
    "Few", "Several", "Another", "Other", "Others", "Same", "Such", "Only",
    # Common short all-caps acronyms the initialism branch could mistake for a
    # name when they follow a relationship word.
    "US", "USA", "UK", "TV", "OK", "AM", "PM", "CEO", "CTO", "CFO", "ID", "DUI",
    "PhD", "USC", "UCLA", "NYC", "LA", "SF",
}


# ---------------------------------------------------------------------------
# Completion gate (issue #79)
# ---------------------------------------------------------------------------

def focus_start_gate() -> dict:
    """Starting a new Focus — auto-creation, or an elevated 'ready to start'
    recommendation flag — spends the same weekly question budget the
    author's *unfinished* focuses need. The owner's rule is about unanswered
    material ("I'd rather finish my open focuses"): no diverting to
    something new while an open focus still has pending questions to answer.

    Open iff every ACTIVE (phase != "maintenance"), NON-PRIMARY focus that
    still has pending (unanswered) questions has reached READY or SATURATED.
    A focus with zero pending questions is exempt from blocking outright,
    even if its saturation ratio reads low against a stale target_depth —
    you cannot "finish by answering" a focus with nothing left to answer, so
    it isn't the kind of unfinished the owner meant (roadmap.focus_fill's
    own `pending`/`room` fields carry this, never re-derived here). Uses
    roadmap.focus_fill for the saturation/pending math and progress.verdict
    for the readiness label — the existing authorities. The primary focus
    (the author's own life story) is exempt — per the issue, it is never
    "done".

    Returns {open: bool, reason: str, blocking: [{focus_id, label,
    saturation, verdict}]} — blocking lists exactly the focuses keeping the
    gate closed, in roadmap order.
    """
    roadmap = load_roadmap()
    if not roadmap.get("focuses"):
        try:
            roadmap = rebuild_roadmap(write=False)
        except OSError:
            roadmap = {"focuses": []}
    questions = parse_questions(QUESTIONS_FILE.read_text(encoding="utf-8")) if QUESTIONS_FILE.exists() else []

    non_primary_with_room = 0
    blocking: list[dict] = []
    for focus in roadmap.get("focuses", []):
        if focus.get("primary"):
            continue
        if focus.get("phase") == "maintenance":
            continue
        fill = focus_fill(focus, questions)
        if fill["pending"] <= 0:
            # Nothing left to answer — not "unfinished" in the owner's
            # sense, whatever the saturation ratio says against the target.
            continue
        non_primary_with_room += 1
        tag, _label = verdict(fill["saturation"])
        if fill["saturated"]:
            tag = "SATURATED"
        if tag not in ("READY", "SATURATED"):
            blocking.append({
                "focus_id": focus.get("id"),
                "label": focus.get("label", focus.get("id")),
                "saturation": fill["saturation"],
                "verdict": tag,
            })

    if blocking:
        labels = ", ".join(b["label"] for b in blocking)
        reason = f"{len(blocking)} open focus(es) unfinished: {labels}"
        return {"open": False, "reason": reason, "blocking": blocking}

    reason = ("every active non-primary focus with pending questions is "
              "READY or SATURATED"
              if non_primary_with_room
              else "no non-primary focus has pending questions to gate on")
    return {"open": True, "reason": reason, "blocking": []}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_answer_texts() -> dict[str, dict]:
    """Load all answer files, return {answer_id: {text, category, path}}."""
    results: dict[str, dict] = {}
    if not ANSWERS_DIR.exists():
        return results
    for path in sorted(ANSWERS_DIR.glob("*.md")):
        qid = answer_id_from_filename(path)
        if not qid:
            continue
        content = path.read_text(encoding="utf-8", errors="ignore")
        body = answer_body(content)
        category = qid[0] if qid else "?"
        results[qid] = {"text": body, "category": category, "path": str(path)}
    return results


def _load_source_texts() -> list[str]:
    """Load all manual source files."""
    texts: list[str] = []
    if not MANUAL_SOURCES_DIR.exists():
        return texts
    for path in sorted(MANUAL_SOURCES_DIR.rglob("*")):
        if path.is_file() and path.suffix in {".md", ".txt", ".text"}:
            texts.append(path.read_text(encoding="utf-8", errors="ignore"))
    return texts


def _load_classifications() -> list[dict]:
    """Load all classification JSON files."""
    results: list[dict] = []
    if not CLASSIFICATIONS_DIR.exists():
        return results
    for path in sorted(CLASSIFICATIONS_DIR.glob("*.json")):
        data = read_json(path, default={})
        if data:
            results.append(data)
    return results


def _existing_focus_names(md_text: str) -> set[str]:
    """Extract existing focus subject names from the question bank."""
    names: list[str] = []
    in_focus = False
    for line in md_text.splitlines():
        stripped = line.strip().lower()
        if stripped.startswith("## focus") or stripped.startswith("## " + OLD_FOCUS_TERM.lower()):
            in_focus = True
            continue
        if in_focus and stripped.startswith("## "):
            in_focus = False
        if in_focus:
            # Match category headers like "## K: Focus — Dad"
            m = re.match(r"^##\s+[A-Z]:\s*(.+?)(?:\s*\(.*\))?\s*$", line)
            if m:
                name = m.group(1)
                # Strip "Focus — " prefix if present
                name = re.sub(rf"^(Focus|{OLD_FOCUS_TERM})\s*[—–-]\s*", "", name, flags=re.IGNORECASE)
                names.append(name.strip())

    # Also look at category names with "focus" in them
    categories = parse_categories(md_text)
    for cat in categories.values():
        if cat.get("group") == "focus":
            raw_name = cat.get("name", "")
            name = re.sub(rf"^(Focus|{OLD_FOCUS_TERM})\s*[—–-]\s*", "", raw_name, flags=re.IGNORECASE)
            names.append(name.strip())

    return {n.lower() for n in names if n}


def _focus_covered_aliases() -> set[str]:
    """Names/aliases the AI-curated entity rosters already map to an existing
    Focus. recommend() must not re-surface these as *new* focus candidates —
    e.g. 'Father'/'James' both alias the "James Taylor"→Dad roster entry, and
    'Mother'→Mom, 'Wife'→Katie. Without this, role words get recommended even
    though that person is already a Focus."""
    covered: set[str] = set()
    try:
        from entity_roster import ENTITY_TYPES, load_roster  # noqa: PLC0415
    except Exception:
        return covered
    for etype in ENTITY_TYPES:
        try:
            entities = load_roster(etype).get("entities", [])
        except Exception:
            continue
        for e in entities:
            if not e.get("maps_to_focus"):
                continue
            covered.add(str(e.get("name", "")).lower())
            for alias in e.get("aliases", []) or []:
                covered.add(str(alias).lower())
    covered.discard("")
    return covered


def _window_has_emotion(text: str, start: int, end: int, window: int = 80) -> float:
    """Return count of emotion words within window characters of a mention."""
    lo = max(0, start - window)
    hi = min(len(text), end + window)
    snippet = text[lo:hi]
    return float(len(EMOTION_WORDS.findall(snippet)))


# ---------------------------------------------------------------------------
# Entity extraction
# ---------------------------------------------------------------------------

def _extract_people(text: str, qid: str) -> list[tuple[str, int, float]]:
    """Return [(name, start, emotional_weight)] for people found after relationship words."""
    results = []
    for m in RELATIONSHIP_WORDS.finditer(text):
        # Look for a capitalized name in the next ~40 chars
        after = text[m.end():m.end() + 60]
        name_m = re.search(rf"\b({_NAME_TOKEN}(?:\s+{_NAME_TOKEN})?)\b", after)
        named = False
        if name_m:
            name = name_m.group(1)
            if name not in STOPWORDS and len(name) >= 2:
                ew = _window_has_emotion(text, m.start(), m.end())
                results.append((name, m.start(), ew))
                named = True
        # Capture the bare relationship label ONLY when no real name followed,
        # e.g. "my dad" with nothing after → entity "Dad". Avoids doubling every
        # named mention with a generic role entity.
        if not named:
            rel_name = m.group(0).capitalize()
            ew = _window_has_emotion(text, m.start(), m.end())
            results.append((rel_name, m.start(), ew))
    return results


def _extract_places(text: str) -> list[tuple[str, int, float]]:
    """Return [(place_name, start, emotional_weight)] for places found."""
    results = []
    for m in PLACE_INDICATORS.finditer(text):
        if len(m.groups()) >= 2:
            raw = m.group(2).strip()
            # Clean trailing punctuation/stop words
            raw = re.split(r"\s+(?:and|but|where|which|that|when|because)\b", raw, flags=re.IGNORECASE)[0]
            raw = raw.strip(" ,.")
            if raw and len(raw) > 2 and raw not in STOPWORDS:
                ew = _window_has_emotion(text, m.start(), m.end())
                results.append((raw.title(), m.start(), ew))
    return results


def _extract_time_periods(text: str) -> list[tuple[str, int, float]]:
    """Return [(period, start, emotional_weight)]."""
    results = []
    for m in TIME_PERIOD_PATTERNS.finditer(text):
        period = m.group(0).strip()
        # Normalize
        period = period[0].upper() + period[1:].lower()
        ew = _window_has_emotion(text, m.start(), m.end())
        results.append((period, m.start(), ew))
    return results


def _extract_themes(text: str) -> list[tuple[str, int, float]]:
    """Return [(theme_name, match_start, emotional_weight)] for theme keyword matches."""
    results = []
    for theme, keywords in THEME_KEYWORDS.items():
        pattern = re.compile(
            r"\b(" + "|".join(re.escape(k) for k in keywords) + r")\b",
            re.IGNORECASE,
        )
        for m in pattern.finditer(text):
            ew = _window_has_emotion(text, m.start(), m.end())
            results.append((theme, m.start(), ew))
    return results


# ---------------------------------------------------------------------------
# Core analysis
# ---------------------------------------------------------------------------

def _build_entity_stats(
    answers: dict[str, dict],
    source_texts: list[str],
    classifications: list[dict],
) -> dict[str, dict]:
    """
    Build a stats dict keyed by (entity_type, canonical_name).
    Each value: {
        mention_count, unique_answer_ids, categories_seen,
        emotional_weight, evidence_snippets
    }
    """
    # entity_key → { mention_count, answers: set, categories: set, ew: float, evidence: list }
    stats: dict[tuple[str, str], dict] = defaultdict(lambda: {
        "mention_count": 0,
        "answers": set(),
        "categories": set(),
        "emotional_weight": 0.0,
        "evidence": [],
    })

    def _record(entity_type: str, name: str, qid: str | None, ew: float, snippet: str):
        key = (entity_type, name)
        s = stats[key]
        s["mention_count"] += 1
        s["emotional_weight"] += ew
        if qid:
            s["answers"].add(qid)
            s["categories"].add(qid[0])
        if len(s["evidence"]) < 6:
            s["evidence"].append(snippet)

    # --- Answers ---
    for qid, info in answers.items():
        text = info["text"]
        if not text:
            continue
        cat = info["category"]

        for name, start, ew in _extract_people(text, qid):
            snippet = f"Mentioned in {qid} (relationship context)"
            _record("person", name, qid, ew, snippet)

        for place, start, ew in _extract_places(text):
            snippet = f"Referenced in {qid} as a place"
            _record("place", place, qid, ew, snippet)

        for period, start, ew in _extract_time_periods(text):
            snippet = f"Time period in {qid}"
            _record("period", period, qid, ew, snippet)

        for theme, start, ew in _extract_themes(text):
            snippet = f"Theme '{theme}' present in {qid}"
            _record("theme", theme, qid, ew, snippet)

    # --- Sources ---
    for i, text in enumerate(source_texts):
        src_label = f"source-{i+1}"
        for name, _, ew in _extract_people(text, None):
            _record("person", name, None, ew, f"Found in {src_label}")
        for place, _, ew in _extract_places(text):
            _record("place", place, None, ew, f"Found in {src_label}")
        for period, _, ew in _extract_time_periods(text):
            _record("period", period, None, ew, f"Found in {src_label}")
        for theme, _, ew in _extract_themes(text):
            _record("theme", theme, None, ew, f"Found in {src_label}")

    # --- Classifications ---
    _OPPORTUNITY_BOOST = {"weak": 0.5, "moderate": 1.5, "strong": 3.0}

    def _clf_name(item) -> str | None:
        if isinstance(item, dict):
            return (item.get("name") or "").strip() or None
        if isinstance(item, str):
            return item.strip() or None
        return None

    for clf in classifications:
        qid = clf.get("question_id") or clf.get("answer_id")
        if not qid and clf.get("source_path"):
            # Classification files identify their source by path, not by id —
            # without this, every classification-derived entity accrues zero
            # unique_answers/cross_categories and never clears the roster gate.
            qid = answer_id_from_filename(Path(clf["source_path"]))
        for person in clf.get("people", []):
            name = _clf_name(person)
            if name:
                _record("person", name, qid, 0.5, f"Extracted from classification ({qid})")
        for place in clf.get("places", []):
            name = _clf_name(place)
            if name:
                _record("place", name, qid, 0.0, f"Place from classification ({qid})")
        for theme in clf.get("themes", []):
            name = _clf_name(theme)
            if name:
                _record("theme", name, qid, 0.0, f"Theme from classification ({qid})")
        # The classifier's explicit Focus judgments — typed, with evidence
        # strength, written for exactly this consumer (previously write-only).
        for opp in clf.get("focus_opportunities", []):
            if not isinstance(opp, dict):
                continue
            entity = str(opp.get("entity", "")).strip()
            opp_type = str(opp.get("type", "")).strip() or "theme"
            if not entity or opp_type not in ("person", "place", "period", "theme", "project"):
                continue
            strength = str(opp.get("evidence_strength", "moderate")).lower()
            boost = _OPPORTUNITY_BOOST.get(strength, 1.5)
            reason = str(opp.get("reason", "")).strip() or f"Classifier flagged as Focus opportunity ({qid})"
            record_type = "theme" if opp_type == "project" else opp_type
            _record(record_type, entity, qid, boost, f"[classifier: {strength}] {reason}")

    return stats


# ---------------------------------------------------------------------------
# Roster fold (contract: focus-duplicate-curation, Scope 2) — the roster's
# settled alias intelligence (monthly AI curation, apply_previous_decisions'
# merges) is consulted BEFORE scoring, so two pending ideas whose keys the
# roster already folded into one entity emerge as ONE recommendation instead
# of two same-named twins.
# ---------------------------------------------------------------------------

def _roster_alias_fold_map(entity_type: str) -> dict[str, str]:
    """{normalized_key: canonical_name} from entity_type's settled roster —
    built via entity_roster._entity_keys, the ONE shared key definition
    (recurring-defect doctrine), never re-derived here. "" / {} when the
    roster module or file is unavailable (a vault with no rosters yet)."""
    try:
        from entity_roster import _entity_keys, load_roster  # noqa: PLC0415
    except Exception:
        return {}
    try:
        entities = load_roster(entity_type).get("entities", [])
    except Exception:
        return {}
    out: dict[str, str] = {}
    for entity in entities:
        name = str(entity.get("name") or "").strip()
        if not name:
            continue
        for key in _entity_keys(entity):
            out.setdefault(key, name)
    return out


def _fold_stats_through_roster(stats: dict[tuple[str, str], dict]) -> dict[tuple[str, str], dict]:
    """Fold _build_entity_stats keys through each type's roster alias map
    before scoring: stats for a key the roster already settled as an alias
    of another entity merge into that entity's canonical name — mention
    counts summed, unique-answer/category sets unioned, evidence unioned
    (deduped, order-preserving). A type with no roster yet passes through
    unchanged."""
    fold_maps: dict[str, dict[str, str]] = {}
    folded: dict[tuple[str, str], dict] = {}
    for (entity_type, name), s in stats.items():
        fold_map = fold_maps.setdefault(entity_type, _roster_alias_fold_map(entity_type))
        canonical = fold_map.get(normalized_focus_key(name), name) if fold_map else name
        dest_key = (entity_type, canonical)
        dest = folded.get(dest_key)
        if dest is None:
            dest = {"mention_count": 0, "answers": set(), "categories": set(),
                    "emotional_weight": 0.0, "evidence": []}
            folded[dest_key] = dest
        dest["mention_count"] += s["mention_count"]
        dest["answers"] |= s["answers"]
        dest["categories"] |= s["categories"]
        dest["emotional_weight"] += s["emotional_weight"]
        for ev in s["evidence"]:
            if ev not in dest["evidence"]:
                dest["evidence"].append(ev)
    return folded


def _score(s: dict) -> float:
    mention_count = s["mention_count"]
    unique_answers = len(s["answers"])
    cross_categories = len(s["categories"])
    emotional_weight = s["emotional_weight"]
    return (
        mention_count * 1.0
        + unique_answers * 2.0
        + cross_categories * 3.0
        + emotional_weight * 1.5
    )


def _evidence_strength(score: float) -> str:
    if score >= 15:
        return "strong"
    if score >= 8:
        return "moderate"
    return "weak"


def _make_reason(entity: str, entity_type: str, s: dict, score: float) -> str:
    ua = len(s["answers"])
    cc = len(s["categories"])
    ew = round(s["emotional_weight"], 1)
    cats = ", ".join(sorted(s["categories"])) or "none"
    strength = _evidence_strength(score)
    return (
        f"{entity} appears in {ua} different answer(s) across {cc} categor{'ies' if cc != 1 else 'y'} "
        f"({cats}) with emotional weight {ew}. {strength.capitalize()} candidate for a dedicated Focus arc."
    )


def load_recommendation_state() -> dict:
    return (
        read_json(FOCUS_RECS_FILE, default=None)
        or read_json(LEGACY_FOCUS_RECS_FILE, default=None)
        or {"version": 1, "recommendations": [], "dismissed": []}
    )


# ---------------------------------------------------------------------------
# Recommend
# ---------------------------------------------------------------------------

def _existing_wiki_page_slugs() -> set[str]:
    """Slugs of pages the wiki already compiles — a recommendation duplicating
    an existing theme/entity page (Money, Family, Belonging all had live theme
    pages when they were recommended as 'new' Focuses) is noise, not signal."""
    slugs: set[str] = set()
    for dir_name in ("themes", "people", "places", "periods", "objects", "projects"):
        directory = WIKI_DIR / dir_name
        if not directory.exists():
            continue
        for page in directory.glob("*.md"):
            if page.name != ".gitkeep":
                slugs.add(page.stem)
    return slugs


def recommend(
    min_score: float = 3.0,
    include_dismissed: bool = False,
    filter_type: str | None = None,
) -> list[dict]:
    """Analyze content and return updated recommendation list."""
    md_text = QUESTIONS_FILE.read_text(encoding="utf-8") if QUESTIONS_FILE.exists() else ""
    # Existing Focus subject names, plus any roster names/aliases the curator
    # already mapped to a Focus (so 'Father'/'Mother'/'Wife' aren't re-recommended).
    existing_focuses = _existing_focus_names(md_text) | _focus_covered_aliases()
    existing_pages = _existing_wiki_page_slugs()

    answers = _load_answer_texts()
    source_texts = _load_source_texts()
    classifications = _load_classifications()

    stats = _build_entity_stats(answers, source_texts, classifications)
    stats = _fold_stats_through_roster(stats)

    # Load existing state
    existing = load_recommendation_state()
    existing_recs = {r["id"]: r for r in existing.get("recommendations", [])}
    # Issue #79: an owner-issued dismissal (any dismissal NOT carrying the
    # structured "dismissed_by": "expiry" marker) is a permanent blocklist —
    # never sniffed from dismiss_reason text, so an owner typing "expired:
    # ..." as a free-text reason can't accidentally self-un-blocklist an
    # entity. Expiry-origin dismissals are handled separately below: they
    # exempt from the blocklist ONLY once the re-detected score clears
    # FOCUS_READY_SCORE_FLOOR — genuinely stronger evidence, not just a
    # re-appearance at the same weak score (which would otherwise reset the
    # created_at clock and never actually expire again).
    dismissed_ids = {
        r["id"] for r in existing.get("dismissed", [])
        if r.get("dismissed_by") != EXPIRY_DISMISSED_BY
    }
    expiry_dismissed_ids = {
        r["id"] for r in existing.get("dismissed", [])
        if r.get("dismissed_by") == EXPIRY_DISMISSED_BY
    }

    # Issue #79: computed once per refresh (the one authority) — a pending
    # recommendation is ready_to_start only once the completion gate is open
    # AND its score clears FOCUS_READY_SCORE_FLOOR. Never auto-creates a
    # Focus; owner approval is unaffected.
    gate = focus_start_gate()

    now = now_utc()
    new_recs: list[dict] = []

    for (entity_type, entity), s in stats.items():
        # Skip already-focused entities
        if entity.lower() in existing_focuses:
            continue
        # Skip entities the wiki already compiles a page for — they're covered,
        # not new territory.
        if slugify(entity) in existing_pages:
            continue

        score = _score(s)
        if score < min_score:
            continue

        if filter_type and entity_type != filter_type:
            continue

        rec_id = f"rec-{slugify(entity)}"

        if not include_dismissed:
            if rec_id in dismissed_ids:
                continue
            # Expiry-origin dismissal: only let it back in once fresh
            # evidence has genuinely pushed the score past the floor.
            if rec_id in expiry_dismissed_ids and score < FOCUS_READY_SCORE_FLOOR:
                continue

        existing_rec = existing_recs.get(rec_id)
        status = existing_rec.get("status", "pending") if existing_rec else "pending"

        evidence = list(dict.fromkeys(s["evidence"]))[:5]  # dedupe, cap at 5

        rec: dict = {
            "id": rec_id,
            "entity": entity,
            "type": entity_type,
            "score": round(score, 2),
            "evidence_strength": _evidence_strength(score),
            "mention_count": s["mention_count"],
            "unique_answers": len(s["answers"]),
            "cross_categories": sorted(s["categories"]),
            "emotional_weight": round(s["emotional_weight"], 2),
            "evidence": evidence,
            "reason": _make_reason(entity, entity_type, s, score),
            "status": status,
            "created_at": existing_rec.get("created_at", now) if existing_rec else now,
            "ready_to_start": bool(
                status == "pending" and gate["open"] and score >= FOCUS_READY_SCORE_FLOOR
            ),
        }
        new_recs.append(rec)

    new_recs.sort(key=lambda r: r["score"], reverse=True)

    return new_recs


def _parse_recorded_at(value: str) -> datetime | None:
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return None


def apply_recommendation_expiry(recs: list[dict], now: str | None = None) -> tuple[list[dict], list[dict]]:
    """Rot control (issue #79): a *pending* recommendation that has sat below
    FOCUS_READY_SCORE_FLOOR for FOCUS_RECOMMENDATION_EXPIRY_WEEKS auto-
    dismisses, tagged with the structured "dismissed_by": "expiry" marker
    recommend() checks (never dismiss_reason text-sniffing — see recommend()'s
    comment). Re-detection can re-propose it later, but only once the score
    clears the floor again (recommend()'s job, not this function's). Recent
    low-score pending recs, and recs already at/above the floor, are left
    untouched regardless of age. Returns (kept, newly_expired)."""
    now_str = now or now_utc()
    now_dt = _parse_recorded_at(now_str) or datetime.now(timezone.utc)
    kept: list[dict] = []
    expired: list[dict] = []
    for r in recs:
        if r.get("status") != "pending" or (r.get("score", 0) or 0) >= FOCUS_READY_SCORE_FLOOR:
            kept.append(r)
            continue
        created = _parse_recorded_at(str(r.get("created_at", "")))
        if created is None:
            kept.append(r)
            continue
        age_weeks = (now_dt - created).days / 7
        if age_weeks >= FOCUS_RECOMMENDATION_EXPIRY_WEEKS:
            expired_rec = dict(r)
            expired_rec["status"] = "expired"
            expired_rec["dismissed_at"] = now_str
            expired_rec["dismissed_by"] = EXPIRY_DISMISSED_BY
            expired_rec["dismiss_reason"] = (
                f"expired: below threshold for {FOCUS_RECOMMENDATION_EXPIRY_WEEKS} weeks"
            )
            expired.append(expired_rec)
        else:
            kept.append(r)
    return kept, expired


def save_recommendations(recs: list[dict], now: str | None = None) -> None:
    existing = load_recommendation_state()
    dismissed = existing.get("dismissed", [])
    kept, newly_expired = apply_recommendation_expiry(recs, now=now)
    if newly_expired:
        # Dedup by id: a re-expiry REPLACES the prior expired entry for the
        # same entity rather than appending a duplicate (defensive — with
        # recommend()'s score-gated un-expiry above, a still-weak entity
        # never re-enters "recommendations" to be expired twice, but this
        # keeps save_recommendations() correct even if called with recs that
        # bypassed that path).
        replacing_ids = {r["id"] for r in newly_expired}
        dismissed = [r for r in dismissed if r.get("id") not in replacing_ids] + newly_expired
    write_json(FOCUS_RECS_FILE, {
        "version": 1,
        "generated_at": now_utc(),
        "recommendations": kept,
        "dismissed": dismissed,
    })


def dismiss_recommendation(rec_id: str, reason: str = "") -> bool:
    existing = load_recommendation_state()
    recs = existing.get("recommendations", [])
    dismissed = existing.get("dismissed", [])

    target = next((r for r in recs if r["id"] == rec_id), None)
    if not target:
        print(f"No recommendation found with id: {rec_id}", file=sys.stderr)
        return False

    recs = [r for r in recs if r["id"] != rec_id]
    target["dismissed_at"] = now_utc()
    target["dismiss_reason"] = reason
    # Explicit, not just "absent" — makes the owner-origin marker as durable
    # to future edits as the structured "expiry" one it's distinguished from.
    target["dismissed_by"] = "owner"
    dismissed.append(target)

    write_json(FOCUS_RECS_FILE, {
        "version": existing.get("version", 1),
        "generated_at": existing.get("generated_at", now_utc()),
        "recommendations": recs,
        "dismissed": dismissed,
    })
    print(f"✓ Dismissed: {rec_id}")
    return True


def approve_recommendation(rec_id: str, *, tier: str = "standard",
                           deliverable: str = "chapter",
                           approved_by: str = MANUAL_APPROVED_BY) -> bool:
    """Approve a recommendation AND create the Focus. Approval used to be a
    dead end — it set status=approved, nothing read it, and focus creation was
    'a manual step' nobody performed (19 recommendations sat pending forever).
    Now it scaffolds the category, registers the Focus, and seeds starter
    questions via roadmap.focus_new — so an approved Focus always has a
    question category (never a zombie).

    `approved_by` is additive provenance (ADR 0011): "owner" (the default —
    every CLI/viewer manual approval) or "auto" (focus_autopilot() only). A
    record approved before this field existed simply lacks it — absent means
    legacy, never re-derived. This is the ONE approval path — focus_autopilot
    calls this function verbatim rather than a parallel scaffold, so zombie
    protection, category scaffolding, and starter-question seeding ride
    along for free for auto-approvals too."""
    existing = load_recommendation_state()
    recs = existing.get("recommendations", [])

    target = next((r for r in recs if r["id"] == rec_id), None)
    if not target:
        print(f"No recommendation found with id: {rec_id}", file=sys.stderr)
        return False

    entity = str(target["entity"])
    focus_type = str(target.get("type", "theme"))
    try:
        from roadmap import focus_new  # noqa: PLC0415
        result = focus_new(entity, focus_type, tier,
                           objective=str(target.get("reason", ""))[:120],
                           deliverable=deliverable)
    except Exception as exc:  # noqa: BLE001
        print(f"✗ Focus creation failed for {entity}: {exc}", file=sys.stderr)
        return False

    target["status"] = "approved"
    target["approved_at"] = now_utc()
    target["approved_by"] = approved_by
    target["focus_id"] = result.get("focus_id")
    target["category"] = result.get("category")

    write_json(FOCUS_RECS_FILE, {
        "version": existing.get("version", 1),
        "generated_at": existing.get("generated_at", now_utc()),
        "recommendations": recs,
        "dismissed": existing.get("dismissed", []),
    })
    print(f"✓ Approved ({approved_by}): {rec_id} — {entity}")
    print(f"  Focus created: {result.get('focus_id')} (category {result.get('category')}, "
          f"{result.get('generated', 0)} starter question(s)"
          f"{'' if result.get('generation_ran') else ' — seed later with focus-new tooling'})")
    return True


# ---------------------------------------------------------------------------
# Autopilot (ADR 0011 — the Convergence Principle's floor applied to focus
# creation)
# ---------------------------------------------------------------------------

def resolve_autopilot_target(override: int | None = None) -> int:
    """target = knob: an explicit --target override wins; otherwise
    config.yaml's `focus_autopilot_target`; otherwise the module default
    AUTOPILOT_TARGET_DEVELOPING. Never a literal restated elsewhere — the
    viewer's policy line reads AUTOPILOT_TARGET_DEVELOPING directly."""
    if override is not None:
        return int(override)
    try:
        raw = load_config().get("focus_autopilot_target")
    except OSError:
        raw = None
    if raw not in (None, ""):
        try:
            value = int(float(raw))
        except (TypeError, ValueError):
            value = None
        if value and value > 0:
            return value
    return AUTOPILOT_TARGET_DEVELOPING


def _is_developing(focus: dict, questions: list[dict]) -> bool:
    """Owner's definition (ADR 0011): active, non-primary, saturation below
    READY (0.70, progress.py). Mirrors focus_start_gate()'s own phase
    exemption — a Focus explicitly parked in "maintenance" isn't unfinished
    work the owner is tracking, so it never counts as developing (matches
    the gate's existing convention rather than inventing a second one). The
    primary life-story focus is exempt, same as the gate."""
    if focus.get("primary"):
        return False
    if focus.get("phase") == "maintenance":
        return False
    fill = focus_fill(focus, questions)
    return fill["saturation"] < READY


def _developing_focuses(roadmap: dict, questions: list[dict]) -> list[dict]:
    return [f for f in roadmap.get("focuses", []) if _is_developing(f, questions)]


def _rec_folds_into_existing_focus(rec: dict, roadmap: dict) -> bool:
    """A pending recommendation is stale evidence for an already-existing
    Focus if the roadmap has grown a Focus with the same id since the
    recommendation was last refreshed — recommend() only screens against
    the roadmap/wiki it saw at refresh time, and the persisted
    recommendations file can be older than the live roadmap."""
    fid = slugify(str(rec.get("entity", "")))
    return any(f.get("id") == fid for f in roadmap.get("focuses", []))


def _autopilot_candidates(roadmap: dict) -> list[dict]:
    """Pending recommendations eligible for auto-approval: score at/above
    FOCUS_READY_SCORE_FLOOR, still pending (owner-dismissed and expired
    entries never appear in `recommendations` — dismiss_recommendation and
    apply_recommendation_expiry both move them into `dismissed`), and not
    already folded into an existing Focus. Highest score first."""
    state = load_recommendation_state()
    pending = [
        r for r in state.get("recommendations", [])
        if r.get("status", "pending") == "pending"
        and (r.get("score", 0) or 0) >= FOCUS_READY_SCORE_FLOOR
        and not _rec_folds_into_existing_focus(r, roadmap)
    ]
    pending.sort(key=lambda r: r.get("score", 0) or 0, reverse=True)
    return pending


def focus_autopilot(target: int | None = None, dry_run: bool = False,
                     *, catch_up: bool = False) -> dict:
    """The Convergence Principle's floor applied to focus creation (ADR
    0011): a passive user's system used to NEVER grow a new Focus —
    approval was the only path. While the "developing" set (active,
    non-primary, unsaturated Focuses — see _is_developing) is thinner than
    `target`, auto-approve the single highest-scoring pending idea at/above
    FOCUS_READY_SCORE_FLOOR through approve_recommendation() itself — the
    exact same path a manual CLI/viewer approval takes, never a parallel
    scaffold path, so zombie protection, category scaffolding, and
    starter-question seeding ride along for free (including the existing
    keyless emit-task fallback inside roadmap.focus_new when no model is
    available in-process).

    Gentle by default: AUTOPILOT_MAX_PER_RUN (1) approval per run, so the
    owner's "keep N in development" end-state is reached over successive
    weekly runs, not in one burst. `catch_up=True` (manual CLI `--catch-up`
    only) raises the effective per-run cap to `target`, filling to target in
    one run for the everything-answered/idle-queue case.

    `dry_run=True` computes and returns the identical decision — including
    which idea(s) it would approve and why — but never calls
    approve_recommendation. Nothing is written.

    Idempotent within a run and across runs: a real approval scaffolds a new
    Focus that itself immediately counts toward `developing` (freshly
    created, unsaturated, non-primary), so a second call the same week
    naturally sees a thinner gap (or the target already met) purely from
    re-reading durable state — no separate cursor file is needed.

    Returns {"target", "cap", "developing_count", "dry_run", "approved",
    "would_approve", "considered", "reason"}.
    """
    resolved_target = resolve_autopilot_target(target)
    cap = resolved_target if catch_up else AUTOPILOT_MAX_PER_RUN

    live_roadmap = load_roadmap()
    if not live_roadmap.get("focuses"):
        try:
            live_roadmap = rebuild_roadmap(write=False)
        except OSError:
            live_roadmap = {"focuses": []}
    questions = parse_questions(QUESTIONS_FILE.read_text(encoding="utf-8")) if QUESTIONS_FILE.exists() else []
    developing = _developing_focuses(live_roadmap, questions)

    pending = _autopilot_candidates(live_roadmap)
    considered = list(pending)

    taken: list[dict] = []
    approval_failed = False
    while len(developing) + len(taken) < resolved_target:
        idea = pending[0] if pending else None
        if idea is None or len(taken) >= cap:
            break
        pending.pop(0)
        if not dry_run:
            ok = approve_recommendation(idea["id"], approved_by=AUTOPILOT_APPROVED_BY)
            if not ok:
                approval_failed = True
                break
        taken.append(idea)

    approved = [] if dry_run else taken
    would_approve = taken if dry_run else []

    def _summary(items: list[dict]) -> str:
        return ", ".join(f"{r['entity']} ({r.get('score', 0):.1f})" for r in items)

    if taken:
        verb = "would approve" if dry_run else "approved"
        reason = (
            f"{verb} {_summary(taken)} — developing set was "
            f"{len(developing)}/{resolved_target}, below target"
        )
    elif approval_failed:
        reason = "an approval attempt failed — see stderr; not retried this run"
    elif len(developing) >= resolved_target:
        reason = f"developing set at/above target ({len(developing)}/{resolved_target}) — no action"
    elif not considered:
        reason = (
            f"developing set below target ({len(developing)}/{resolved_target}) "
            f"but no pending idea clears the floor ({FOCUS_READY_SCORE_FLOOR}) — no action"
        )
    else:
        reason = (
            f"developing set below target ({len(developing)}/{resolved_target}) "
            f"but the per-run cap ({cap}) is already spent — no action"
        )

    return {
        "target": resolved_target,
        "cap": cap,
        "developing_count": len(developing),
        "dry_run": dry_run,
        "approved": [{"id": r["id"], "entity": r["entity"], "score": r.get("score")} for r in approved],
        "would_approve": [{"id": r["id"], "entity": r["entity"], "score": r.get("score")} for r in would_approve],
        "considered": [{"id": r["id"], "entity": r["entity"], "score": r.get("score")} for r in considered],
        "reason": reason,
    }


# ---------------------------------------------------------------------------
# Display
# ---------------------------------------------------------------------------

TYPE_EMOJI = {
    "person": "👤",
    "place": "🏠",
    "period": "📅",
    "theme": "💭",
}


def display_recommendations(recs: list[dict], filter_type: str | None = None) -> None:
    if not recs:
        print("No focus recommendations found.")
        print("Tip: Add more answers to get recommendations.")
        return

    by_strength: dict[str, list[dict]] = {"strong": [], "moderate": [], "weak": []}
    for r in recs:
        by_strength[r["evidence_strength"]].append(r)

    print("\nFocus Recommendations\n")
    for strength in ("strong", "moderate", "weak"):
        group = by_strength[strength]
        if not group:
            continue
        print(f"{strength.capitalize()}:")
        for r in group:
            emoji = TYPE_EMOJI.get(r["type"], "•")
            cats = ", ".join(r["cross_categories"]) or "—"
            ev_short = "; ".join(r["evidence"][:3])
            if len(r["evidence"]) > 3:
                ev_short += f" (+{len(r['evidence'])-3} more)"
            status_tag = f" [{r['status'].upper()}]" if r["status"] != "pending" else ""
            ready_tag = " ★ ready to start" if r.get("ready_to_start") else ""
            print(f"  {emoji} {r['entity']} ({r['type']}) — score: {r['score']}{status_tag}{ready_tag}")
            print(f"     {r['unique_answers']} answers, {len(r['cross_categories'])} categories ({cats}), emotional weight: {r['emotional_weight']}")
            if ev_short:
                print(f"     Evidence: {ev_short}")
            print()


def display_autopilot_result(result: dict) -> None:
    """Dry-run prints the would-approve decision and why (contract Scope 1);
    a real run prints the same shape with "approved" instead of
    "would_approve". Never a second, competing message format from the
    weekly-wiring caller — weekly_maintenance.sh's report table captures
    this stdout verbatim."""
    prefix = "[DRY RUN] " if result["dry_run"] else ""
    print(f"{prefix}Focus autopilot — developing {result['developing_count']}/{result['target']} "
          f"(per-run cap {result['cap']})")
    print(f"  {result['reason']}")
    items = result["would_approve"] if result["dry_run"] else result["approved"]
    if items:
        label = "Would approve" if result["dry_run"] else "Approved"
        for r in items:
            score = r.get("score")
            score_str = f"{score:.1f}" if isinstance(score, (int, float)) else "—"
            print(f"  → {label}: {r['entity']} (score {score_str}, {r['id']})")
    elif result["considered"]:
        print(f"  Considered ({len(result['considered'])} eligible, none taken):")
        for r in result["considered"][:5]:
            score = r.get("score")
            score_str = f"{score:.1f}" if isinstance(score, (int, float)) else "—"
            print(f"    - {r['entity']} (score {score_str}, {r['id']})")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Recommend Lifehug focuses.")
    parser.add_argument("--recommend", action="store_true", help="Analyze and show recommendations")
    parser.add_argument("--min-score", type=float, default=3.0, help="Minimum score to include (default: 3.0)")
    parser.add_argument("--include-dismissed", action="store_true", help="Include dismissed recommendations")
    parser.add_argument("--type", dest="filter_type", choices=FOCUS_RECOMMENDATION_TYPES,
                        help="Filter by entity type")
    parser.add_argument("--dismiss", metavar="REC_ID", help="Dismiss a recommendation by id")
    parser.add_argument("--reason", default="", help="Reason for dismissal")
    parser.add_argument("--approve", metavar="REC_ID", help="Approve a recommendation by id")
    parser.add_argument("--json", action="store_true", help="Print current recommendations as JSON")
    parser.add_argument("--autopilot", action="store_true",
                        help="Convergence Principle floor (ADR 0011): auto-approve the top idea "
                             "when the developing set is thinner than target")
    parser.add_argument("--target", type=int, default=None,
                        help="Override the autopilot developing-set target (default: config or "
                             f"{AUTOPILOT_TARGET_DEVELOPING})")
    parser.add_argument("--catch-up", action="store_true",
                        help="With --autopilot: fill to target in one run instead of the gentle "
                             f"{AUTOPILOT_MAX_PER_RUN}/run cap (manual CLI only)")
    parser.add_argument("--dry-run", action="store_true", help="With --autopilot: preview, write nothing")

    args = parser.parse_args()

    if args.dismiss:
        dismiss_recommendation(args.dismiss, args.reason)
        return

    if args.approve:
        approve_recommendation(args.approve)
        return

    if args.autopilot:
        result = focus_autopilot(target=args.target, dry_run=args.dry_run, catch_up=args.catch_up)
        display_autopilot_result(result)
        return

    if args.json:
        import json
        data = load_recommendation_state()
        print(json.dumps(data, indent=2))
        return

    if args.recommend:
        recs = recommend(
            min_score=args.min_score,
            include_dismissed=args.include_dismissed,
            filter_type=args.filter_type,
        )
        save_recommendations(recs)
        display_recommendations(recs, filter_type=args.filter_type)
        return

    parser.print_help()


if __name__ == "__main__":
    main()
