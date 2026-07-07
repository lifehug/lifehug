#!/usr/bin/env python3
"""Lifehug timeline data assembly (v79, issue #33).

The timeline is **the life graph projected onto time**: a vertical spine of
period entities (chrono-ordered — the graph's native time axis) with every
other entity (people, places, objects, projects) lined up against them by
SOURCE OVERLAP — computable and provable, never keyword-fuzzy. An entity's dot
sits in the period whose sources overlap its own the most, and the shared
source ids are shown as the evidence. The owner's own Life Chapters run as a
parallel band of era names.

The whole point is validation: the page shows what the system currently
believes about the chronology, makes wrong lineups and gaps visually obvious,
and tells the owner how to correct them (`lifehug.py fix`, or just answering
the gap questions). Unplaceable items land in an explicit "unplaced" bucket
rather than being forced somewhere.

Zero AI calls; read-only over live state.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

_SYSTEM_DIR = Path(__file__).resolve().parent
if str(_SYSTEM_DIR) not in sys.path:
    sys.path.insert(0, str(_SYSTEM_DIR))

from lifehug_core import (
    CLASSIFICATIONS_DIR,
    MANUAL_SOURCES_DIR,
    STATE_DIR,
    WIKI_DIR,
    read_json,
    slugify,
)

# Entity dirs that line up against the period spine (dir name -> type label).
LINEUP_DIRS = {
    "people": "person",
    "places": "place",
    "objects": "object",
    "projects": "project",
}

# Minimum shared sources for an entity to be *placed* in a period. One shared
# source is real evidence at this corpus size; raise later if noisy.
MIN_OVERLAP = 1


# ---------------------------------------------------------------------------
# Page parsing (frontmatter sources + chrono), shared with the wiki's format.
# ---------------------------------------------------------------------------

def _page_sources(text: str) -> set[str]:
    """Parse the `sources:` frontmatter block of a compiled wiki page."""
    refs: set[str] = set()
    lines = text.splitlines()
    for idx, line in enumerate(lines):
        if line.strip() != "sources:":
            continue
        for raw in lines[idx + 1:]:
            if not raw.startswith("  - "):
                break
            value = raw.split("-", 1)[1].strip().strip('"').strip("'")
            if value:
                refs.add(value)
    return refs


def _frontmatter_value(text: str, key: str, default: str = "") -> str:
    match = re.search(rf'^{re.escape(key)}:\s*["\']?(.+?)["\']?\s*$', text, re.MULTILINE)
    return match.group(1).strip() if match else default


# ---------------------------------------------------------------------------
# The spine: periods in chrono order.
# ---------------------------------------------------------------------------

def load_periods() -> list[dict]:
    """Chrono-ordered periods: roster entries joined with their wiki pages'
    source lists. Falls back to page frontmatter `chrono:` when the roster is
    missing. Periods without a chrono sort last (a visible gap in itself)."""
    roster = read_json(STATE_DIR / "entity_rosters" / "period.json", default=None) or {}
    by_slug: dict[str, dict] = {}
    for ent in roster.get("entities", []) or []:
        if not ent.get("page_eligible"):
            continue
        slug = ent.get("slug") or slugify(ent.get("name", ""))
        by_slug[slug] = {
            "slug": slug,
            "name": ent.get("name", slug),
            "chrono": ent.get("chrono"),
            "sources": set(),
            "page": None,
            "approximate_dates": "",
        }

    periods_dir = WIKI_DIR / "periods"
    if periods_dir.exists():
        for page in sorted(periods_dir.glob("*.md")):
            if page.name == ".gitkeep":
                continue
            text = page.read_text(encoding="utf-8", errors="replace")
            slug = page.stem
            entry = by_slug.setdefault(slug, {
                "slug": slug,
                "name": _frontmatter_value(text, "title", slug.replace("-", " ").title()),
                "chrono": None,
                "sources": set(),
                "page": None,
                "approximate_dates": "",
            })
            entry["page"] = page.relative_to(WIKI_DIR.parent).as_posix()
            entry["sources"] = _page_sources(text)
            if entry["chrono"] is None:
                raw = _frontmatter_value(text, "chrono")
                entry["chrono"] = int(raw) if raw.isdigit() else None

    periods = list(by_slug.values())
    periods.sort(key=lambda p: (p["chrono"] is None, p["chrono"] or 0, p["slug"]))
    return periods


# ---------------------------------------------------------------------------
# The owner's chapters band.
# ---------------------------------------------------------------------------

_CHAPTER_RE = re.compile(r"^## Chapter (\d+) — (.+?)\s*$", re.MULTILINE)


def load_chapters() -> list[dict]:
    """Parse the latest Life Chapters source (the annual chapters-exercise
    ritual saved via ingest-story). Returns [] when none exists — the spine
    renders alone. The chapter number is its order; the paragraph after each
    header is its description (including the 'It ends when…' transition)."""
    if not MANUAL_SOURCES_DIR.exists():
        return []
    candidates = sorted(p for p in MANUAL_SOURCES_DIR.glob("*.md")
                        if "life-chapters" in p.name)
    if not candidates:
        return []
    text = candidates[-1].read_text(encoding="utf-8", errors="replace")
    chapters: list[dict] = []
    matches = list(_CHAPTER_RE.finditer(text))
    for i, m in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        body = text[m.end():end].strip()
        chapters.append({
            "number": int(m.group(1)),
            "title": m.group(2).strip(),
            "body": body,
            "source": candidates[-1].name,
        })
    chapters.sort(key=lambda c: c["number"])
    return chapters


def align_chapters(chapters: list[dict], periods: list[dict],
                   entity_placement: dict[str, str] | None = None) -> list[dict]:
    """Conservative chapter→period alignment: ONLY a period NAME appearing in
    the chapter text ("the high school era" → high-school). Entity-vote
    alignment was tried and is too noisy — one era-spanning answer pollutes a
    whole chapter's placement. Unaligned chapters simply stack in their own
    order; absence of a band is honest, a wrong band is misleading."""
    period_names = {p["slug"]: p["name"].lower() for p in periods}
    aligned = []
    for chapter in chapters:
        body_lower = f"{chapter['title']} {chapter['body']}".lower()
        match_slug = None
        for slug, name in period_names.items():
            if name in body_lower:
                match_slug = slug
                break
        aligned.append({**chapter, "aligned_period": match_slug})
    return aligned


# ---------------------------------------------------------------------------
# Entity lineup by source overlap.
# ---------------------------------------------------------------------------

def load_entities() -> list[dict]:
    """Every people/places/objects/projects page with its parsed source set."""
    out: list[dict] = []
    for dir_name, type_label in LINEUP_DIRS.items():
        directory = WIKI_DIR / dir_name
        if not directory.exists():
            continue
        for page in sorted(directory.glob("*.md")):
            if page.name == ".gitkeep":
                continue
            text = page.read_text(encoding="utf-8", errors="replace")
            out.append({
                "slug": page.stem,
                "title": _frontmatter_value(text, "title", page.stem.replace("-", " ").title()),
                "type": type_label,
                "page": page.relative_to(WIKI_DIR.parent).as_posix(),
                "sources": _page_sources(text),
            })
    return out


def line_up_entities(entities: list[dict], periods: list[dict]) -> tuple[dict[str, list[dict]], list[dict]]:
    """Place each entity at its max-overlap period. Returns
    ({period_slug: [entity_rows...]}, unplaced_rows). Each placed row carries
    `evidence` (the shared source ids) and `also_in` (other periods with
    meaningful overlap) — the provable lineup the owner can verify."""
    placed: dict[str, list[dict]] = {p["slug"]: [] for p in periods}
    unplaced: list[dict] = []
    for entity in entities:
        overlaps = []
        for period in periods:
            shared = entity["sources"] & period["sources"]
            if len(shared) >= MIN_OVERLAP:
                overlaps.append((len(shared), period["slug"], shared))
        if not overlaps:
            unplaced.append({**entity, "evidence": [], "also_in": []})
            continue
        overlaps.sort(key=lambda t: (-t[0], t[1]))
        best_count, best_slug, best_shared = overlaps[0]
        also = [slug for count, slug, _ in overlaps[1:] if count >= max(1, best_count // 2)]
        placed[best_slug].append({
            **entity,
            "evidence": sorted(_short_source(s) for s in best_shared),
            "also_in": also,
        })
    for rows in placed.values():
        rows.sort(key=lambda r: (r["type"], r["slug"]))
    unplaced.sort(key=lambda r: (r["type"], r["slug"]))
    return placed, unplaced


def _short_source(source: str) -> str:
    """answers/A14.md -> A14; sources/manual/x.md -> x."""
    return Path(source).stem


# ---------------------------------------------------------------------------
# Events from classifications.
# ---------------------------------------------------------------------------

def load_events() -> list[dict]:
    """All classifier-extracted events with their source and era hints."""
    out: list[dict] = []
    if not CLASSIFICATIONS_DIR.exists():
        return out
    for path in sorted(CLASSIFICATIONS_DIR.glob("*.json")):
        data = read_json(path, default={}) or {}
        source = str(data.get("source_path", path.stem))
        eras = [str(tp.get("era", "")).lower()
                for tp in (data.get("time_periods") or []) if isinstance(tp, dict)]
        for event in data.get("events", []) or []:
            if not isinstance(event, dict):
                continue
            desc = str(event.get("description", "")).strip()
            if not desc:
                continue
            out.append({
                "description": desc,
                "when_hint": str(event.get("when_hint") or "").strip(),
                "anchor": str(event.get("anchor") or "").strip(),
                "source": source,
                "source_short": _short_source(source),
                "eras": eras,
            })
    return out


# Era keywords per period slug, for placing events whose classification names
# an era ("early childhood", "high school", "my 20s"...). Membership via the
# source answer's period sources is tried FIRST; this is the fallback.
_PERIOD_KEYWORDS = {
    "childhood": ("childhood", "child", "kid", "elementary", "young boy", "young girl"),
    "my-teens": ("teen", "middle school", "junior high", "adolescen"),
    "high-school": ("high school",),
    "college": ("college", "university", "school of business", "student"),
    "my-20s": ("20s", "twenties", "mission", "newlywed", "early adult"),
    "my-30s": ("30s", "thirties"),
    "my-40s": ("40s", "forties", "midlife", "present", "today", "current"),
}


_ERA_STOPWORDS = {
    "the", "a", "an", "of", "in", "at", "to", "and", "or", "era", "years",
    "year", "period", "time", "his", "her", "their", "my", "early", "late",
    "mid", "days", "life", "stage", "approximately", "approx", "around",
}


def _era_tokens(text: str) -> set[str]:
    return {t for t in re.findall(r"[a-z0-9]+", text.lower())
            if len(t) > 2 and t not in _ERA_STOPWORDS}


def learned_era_vocabulary(periods: list[dict], events: list[dict]) -> dict[str, set[str]]:
    """Each period's era-language, LEARNED from the classifications of its own
    member sources — the classifier described answers/H1.md with era 'founding
    Etherfuse', and H1 belongs to a period page, so that period now understands
    'founding'/'etherfuse'. Fully generic (no hardcoded user terms) and it gets
    smarter as more sources classify."""
    by_source: dict[str, set[str]] = {}
    for event in events:
        tokens = set()
        for era in event["eras"]:
            tokens |= _era_tokens(era)
        if tokens:
            by_source.setdefault(event["source"], set()).update(tokens)
    vocab: dict[str, set[str]] = {}
    for period in periods:
        tokens = _era_tokens(period["name"])
        for source in period["sources"]:
            tokens |= by_source.get(source, set())
        vocab[period["slug"]] = tokens
    # Distinctiveness filter: a token appearing in several periods' vocabularies
    # is era-ambiguous (an arc-spanning answer poisons every period that cites
    # it) — only tokens UNIQUE to one period count as placement evidence.
    token_owners: dict[str, int] = {}
    for tokens in vocab.values():
        for token in tokens:
            token_owners[token] = token_owners.get(token, 0) + 1
    for slug in vocab:
        vocab[slug] = {t for t in vocab[slug] if token_owners[t] == 1}
    return vocab


# ---------------------------------------------------------------------------
# Manual placements (v102) — the owner's curation layer.
#
# The timeline is a validation surface; when the owner drags an unplaced
# moment into a period (or corrects a wrong one), that decision persists here
# and wins over every heuristic. Raw sources stay immutable — a placement is
# an overlay keyed by CONTENT (sha of source + description), so a
# reclassification that rewrites the description automatically orphans the
# placement (surfaced as `stale_placements`, never silently misapplied).
# ---------------------------------------------------------------------------

PLACEMENTS_FILE = STATE_DIR / "timeline_placements.json"


def placement_key(event: dict) -> str:
    import hashlib  # noqa: PLC0415
    payload = f"{event.get('source', '')}\n{event.get('description', '')}"
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()[:12]


def load_placements() -> dict:
    data = read_json(PLACEMENTS_FILE, default=None) or {"version": 1, "placements": []}
    data.setdefault("placements", [])
    return data


def save_placement(key: str, source: str, description: str, period: str,
                   when_hint: str = "", note: str = "") -> dict:
    """Add or replace the manual placement for one event."""
    from lifehug_core import now_utc, write_json  # noqa: PLC0415
    data = load_placements()
    data["placements"] = [p for p in data["placements"] if p.get("key") != key]
    record = {"key": key, "source": source, "description": description,
              "period": period, "when_hint": when_hint, "note": note,
              "placed_at": now_utc()}
    data["placements"].append(record)
    write_json(PLACEMENTS_FILE, data)
    return record


def remove_placement(key: str) -> bool:
    from lifehug_core import write_json  # noqa: PLC0415
    data = load_placements()
    before = len(data["placements"])
    data["placements"] = [p for p in data["placements"] if p.get("key") != key]
    if len(data["placements"]) == before:
        return False
    write_json(PLACEMENTS_FILE, data)
    return True


def place_events(events: list[dict], periods: list[dict],
                 placements: dict | None = None) -> tuple[dict[str, list[dict]], list[dict]]:
    """({period_slug: [events...]}, unplaced). Placement order:
      0. the owner's manual placement (content-keyed overlay) — always wins
      1. the event's source answer appears in a period page's sources
      2. the classification's era text (or the when_hint) matches static
         period keywords
      3. learned era-vocabulary overlap (each period's era-language derived
         from its member sources' classifications) — best overlap of ≥2 tokens
      4. unplaced — an explicit bucket, never forced."""
    placed: dict[str, list[dict]] = {p["slug"]: [] for p in periods}
    unplaced: list[dict] = []
    vocab = learned_era_vocabulary(periods, events)
    manual_by_key = {}
    if placements:
        manual_by_key = {p["key"]: p for p in placements.get("placements", [])
                         if p.get("period") in placed}
    def _keyword_slot(haystack: str) -> str | None:
        for period in periods:
            for keyword in _PERIOD_KEYWORDS.get(period["slug"], ()):
                if keyword in haystack:
                    return period["slug"]
        return None

    for event in events:
        # 0) The owner said so — manual placement outranks every heuristic.
        if manual_by_key:
            manual = manual_by_key.get(placement_key(event))
            if manual:
                event = dict(event)
                event["placement"] = "manual"
                event["placement_key"] = manual["key"]
                if manual.get("when_hint"):
                    event["when_hint"] = manual["when_hint"]
                if manual.get("note"):
                    event["placement_note"] = manual["note"]
                placed[manual["period"]].append(event)
                continue
        # 1) The event's OWN when_hint is the most specific signal — an
        #    arc-spanning answer contributes events across many eras, so the
        #    per-event time-words outrank the answer's period membership
        #    ("a month before I graduated college" → college, even when the
        #    source answer sits on the high-school page).
        slot = _keyword_slot(event["when_hint"].lower()) if event["when_hint"] else None
        # 2) Source membership: the answer belongs to a period page.
        if slot is None:
            for period in periods:
                if event["source"] in period["sources"]:
                    slot = period["slug"]
                    break
        # 3) The classification's era text.
        if slot is None:
            slot = _keyword_slot(" ".join(event["eras"]))
        # 4) Learned distinctive era-vocabulary (≥2 shared tokens).
        if slot is None:
            event_tokens = _era_tokens(" ".join(event["eras"] + [event["when_hint"].lower()]))
            best_slug, best_overlap = None, 1
            for period in periods:
                overlap = len(event_tokens & vocab.get(period["slug"], set()))
                if overlap > best_overlap:
                    best_slug, best_overlap = period["slug"], overlap
            slot = best_slug
        if slot is None:
            unplaced.append(event)
        else:
            placed[slot].append(event)
    for rows in placed.values():
        rows.sort(key=lambda e: (not e["when_hint"], e["source_short"]))
    return placed, unplaced


# ---------------------------------------------------------------------------
# Gaps — the correctable holes, computed as first-class output.
# ---------------------------------------------------------------------------

def compute_gaps(periods: list[dict],
                 entity_lineup: dict[str, list[dict]],
                 event_lineup: dict[str, list[dict]],
                 unplaced_entities: list[dict],
                 unplaced_events: list[dict]) -> list[dict]:
    gaps: list[dict] = []
    for period in periods:
        slug = period["slug"]
        events_here = event_lineup.get(slug, [])
        entities_here = entity_lineup.get(slug, [])
        if period["chrono"] is None:
            gaps.append({"kind": "no_chrono", "period": slug,
                         "message": f"{period['name']} has no place in the chronological order yet."})
        if not events_here:
            gaps.append({"kind": "no_events", "period": slug,
                         "message": f"No datable moments recorded in {period['name']} yet.",
                         "hint": "Answers about this era will fill it — dates arrive as landmark "
                                 "anchors (before/after a move, a birth), never guessed years."})
        elif all(not e["when_hint"] for e in events_here):
            gaps.append({"kind": "all_undated", "period": slug,
                         "message": f"Moments in {period['name']} exist but none carry the author's own time words."})
        if not entities_here:
            gaps.append({"kind": "thin_lineup", "period": slug,
                         "message": f"No people, places, or objects line up with {period['name']} yet."})
    if unplaced_events:
        gaps.append({"kind": "unplaced_events", "period": None,
                     "message": f"{len(unplaced_events)} moment(s) I can't place in any period.",
                     "hint": "Tell the bot where they belong, or answer with a landmark anchor."})
    if unplaced_entities:
        gaps.append({"kind": "unplaced_entities", "period": None,
                     "message": f"{len(unplaced_entities)} page(s) share no sources with any period."})
    return gaps


# ---------------------------------------------------------------------------
# The assembled payload.
# ---------------------------------------------------------------------------

def timeline_data() -> dict:
    periods = load_periods()
    entities = load_entities()
    entity_lineup, unplaced_entities = line_up_entities(entities, periods)
    events = load_events()
    placements = load_placements()
    event_lineup, unplaced_events = place_events(events, periods, placements)

    # Placements whose event no longer exists (reclassification rewrote the
    # description) or whose period page is gone — surfaced, never silently
    # misapplied.
    live_keys = {placement_key(e) for e in events}
    period_slugs = {p["slug"] for p in periods}
    stale_placements = [p for p in placements.get("placements", [])
                        if p.get("key") not in live_keys
                        or p.get("period") not in period_slugs]

    chapters = align_chapters(load_chapters(), periods)
    chapters_by_period: dict[str, list[dict]] = {}
    for chapter in chapters:
        if chapter.get("aligned_period"):
            chapters_by_period.setdefault(chapter["aligned_period"], []).append(chapter)

    gaps = compute_gaps(periods, entity_lineup, event_lineup,
                        unplaced_entities, unplaced_events)
    gaps_by_period: dict[str, list[dict]] = {}
    global_gaps: list[dict] = []
    for gap in gaps:
        if gap.get("period"):
            gaps_by_period.setdefault(gap["period"], []).append(gap)
        else:
            global_gaps.append(gap)

    return {
        "periods": periods,
        "chapters": chapters,
        "chapters_by_period": chapters_by_period,
        "entity_lineup": entity_lineup,
        "event_lineup": event_lineup,
        "unplaced_entities": unplaced_entities,
        "unplaced_events": unplaced_events,
        "stale_placements": stale_placements,
        "gaps_by_period": gaps_by_period,
        "global_gaps": global_gaps,
        "counts": {
            "periods": len(periods),
            "entities_placed": sum(len(v) for v in entity_lineup.values()),
            "entities_unplaced": len(unplaced_entities),
            "events_placed": sum(len(v) for v in event_lineup.values()),
            "events_unplaced": len(unplaced_events),
        },
    }
