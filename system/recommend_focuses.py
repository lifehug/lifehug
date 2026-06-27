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
    answer_body,
    answer_id_from_filename,
    now_utc,
    parse_categories,
    read_json,
    slugify,
    write_json,
)

OLD_FOCUS_TERM = "Spot" "light"

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

RELATIONSHIP_WORDS = re.compile(
    r"\b(mom|dad|mother|father|brother|sister|friend|mentor|boss|wife|husband|"
    r"partner|son|daughter|grandma|grandpa|grandfather|grandmother|uncle|aunt|"
    r"cousin|teacher|coach|pastor|priest|therapist|neighbor|colleague|roommate|"
    r"boyfriend|girlfriend|fiance[é]?|stepmother|stepfather|stepbrother|stepsister)\b",
    re.IGNORECASE,
)

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
}


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
        name_m = re.search(r"\b([A-Z][a-z]{1,}(?:\s+[A-Z][a-z]{1,})?)\b", after)
        if name_m:
            name = name_m.group(1)
            if name not in STOPWORDS and len(name) > 2:
                ew = _window_has_emotion(text, m.start(), m.end())
                results.append((name, m.start(), ew))
        # Also capture bare relationship labels when no name follows
        # e.g. "my dad" → entity is "Dad"
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
    for clf in classifications:
        qid = clf.get("question_id") or clf.get("answer_id")
        for person in clf.get("people", []):
            name = person.get("name") or person if isinstance(person, str) else None
            if name:
                _record("person", name, qid, 0.5, f"Extracted from classification ({qid})")
        for place in clf.get("places", []):
            name = place.get("name") or place if isinstance(place, str) else None
            if name:
                _record("place", name, qid, 0.0, f"Place from classification ({qid})")
        for theme in clf.get("themes", []):
            name = theme.get("name") or theme if isinstance(theme, str) else None
            if name:
                _record("theme", name, qid, 0.0, f"Theme from classification ({qid})")

    return stats


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

def recommend(
    min_score: float = 3.0,
    include_dismissed: bool = False,
    filter_type: str | None = None,
) -> list[dict]:
    """Analyze content and return updated recommendation list."""
    md_text = QUESTIONS_FILE.read_text(encoding="utf-8") if QUESTIONS_FILE.exists() else ""
    existing_focuses = _existing_focus_names(md_text)

    answers = _load_answer_texts()
    source_texts = _load_source_texts()
    classifications = _load_classifications()

    stats = _build_entity_stats(answers, source_texts, classifications)

    # Load existing state
    existing = load_recommendation_state()
    existing_recs = {r["id"]: r for r in existing.get("recommendations", [])}
    dismissed_ids = {r["id"] for r in existing.get("dismissed", [])}

    now = now_utc()
    new_recs: list[dict] = []

    for (entity_type, entity), s in stats.items():
        # Skip already-focused entities
        if entity.lower() in existing_focuses:
            continue

        score = _score(s)
        if score < min_score:
            continue

        if filter_type and entity_type != filter_type:
            continue

        rec_id = f"rec-{slugify(entity)}"

        if rec_id in dismissed_ids and not include_dismissed:
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
        }
        new_recs.append(rec)

    new_recs.sort(key=lambda r: r["score"], reverse=True)

    return new_recs


def save_recommendations(recs: list[dict]) -> None:
    existing = load_recommendation_state()
    dismissed = existing.get("dismissed", [])
    write_json(FOCUS_RECS_FILE, {
        "version": 1,
        "generated_at": now_utc(),
        "recommendations": recs,
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
    dismissed.append(target)

    write_json(FOCUS_RECS_FILE, {
        "version": existing.get("version", 1),
        "generated_at": existing.get("generated_at", now_utc()),
        "recommendations": recs,
        "dismissed": dismissed,
    })
    print(f"✓ Dismissed: {rec_id}")
    return True


def approve_recommendation(rec_id: str) -> bool:
    existing = load_recommendation_state()
    recs = existing.get("recommendations", [])

    target = next((r for r in recs if r["id"] == rec_id), None)
    if not target:
        print(f"No recommendation found with id: {rec_id}", file=sys.stderr)
        return False

    target["status"] = "approved"
    target["approved_at"] = now_utc()

    write_json(FOCUS_RECS_FILE, {
        "version": existing.get("version", 1),
        "generated_at": existing.get("generated_at", now_utc()),
        "recommendations": recs,
        "dismissed": existing.get("dismissed", []),
    })
    print(f"✓ Approved: {rec_id} — {target['entity']}")
    print("  (Actual focus creation is a manual step — add category to question-bank.md)")
    return True


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
            print(f"  {emoji} {r['entity']} ({r['type']}) — score: {r['score']}{status_tag}")
            print(f"     {r['unique_answers']} answers, {len(r['cross_categories'])} categories ({cats}), emotional weight: {r['emotional_weight']}")
            if ev_short:
                print(f"     Evidence: {ev_short}")
            print()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Recommend Lifehug focuses.")
    parser.add_argument("--recommend", action="store_true", help="Analyze and show recommendations")
    parser.add_argument("--min-score", type=float, default=3.0, help="Minimum score to include (default: 3.0)")
    parser.add_argument("--include-dismissed", action="store_true", help="Include dismissed recommendations")
    parser.add_argument("--type", dest="filter_type", choices=["person", "place", "period", "theme"],
                        help="Filter by entity type")
    parser.add_argument("--dismiss", metavar="REC_ID", help="Dismiss a recommendation by id")
    parser.add_argument("--reason", default="", help="Reason for dismissal")
    parser.add_argument("--approve", metavar="REC_ID", help="Approve a recommendation by id")
    parser.add_argument("--json", action="store_true", help="Print current recommendations as JSON")

    args = parser.parse_args()

    if args.dismiss:
        dismiss_recommendation(args.dismiss, args.reason)
        return

    if args.approve:
        approve_recommendation(args.approve)
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
