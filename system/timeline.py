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

v195 (ADR 0024): the timeline holds DATES. Every event, period, chapter and
place can carry a `chronology.DateRecord` — an interval with a granularity, a
confidence, a basis, its anchors and its provenance — and `chrono` is DERIVED
from those dates when they exist (the monthly roster ordinal stays as the
fallback). `bands` is the one render shape: the person's own life chapter is
the band wherever one covers the stretch, the system's period fills the rest,
places lived nest inside, and events sit under the place. Gaps become Play-able
`unknowns` with a probe and a leverage score; the highest-leverage anchors are
keystones, and a keystone carries the identity a whisper or a minted keystone
question is asked under (v196).

v110: connector date evidence (state/connectors/*_date_evidence.json) lines up
against periods and events as corroboration badges, and evidence clustering
against the story's own dates surfaces as date_contradiction gaps — surfaced,
never auto-applied (see timeline_corroboration.py).

Zero AI calls; read-only over live state.
"""

from __future__ import annotations

import contextlib
import re
import sys
from pathlib import Path

_SYSTEM_DIR = Path(__file__).resolve().parent
if str(_SYSTEM_DIR) not in sys.path:
    sys.path.insert(0, str(_SYSTEM_DIR))

import chronology as chrono  # noqa: E402
import landmarks_interaction  # noqa: E402
import timeline_corroboration as tcorr  # noqa: E402

from lifehug_core import (  # noqa: E402
    CLASSIFICATIONS_DIR,
    CONNECTORS_STATE_DIR,
    ENTITY_ROSTERS_DIR,
    LANDMARKS_FILE,
    MANUAL_SOURCES_DIR,
    STATE_DIR,
    TIMELINE_PLACEMENTS_FILE,
    WIKI_DIR,
    now_utc,
    read_json,
    slugify,
    write_json,
)

# ---------------------------------------------------------------------------
# The vault roots this module reads — one authoritative list (issue #129).
#
# `timeline_data()` is also run *on behalf of another vault root* by callers
# that own their own roots: wiki_compile's timeline export and a connector's
# excavation. Each used to rebind this module's globals by hand, and v120's
# vault-only refactor moved entity_rosters/ and connectors/ off hand-derived
# STATE_DIR subpaths onto their own contract names — so every hand-written
# rebind site silently kept HALF the call reading the process vault and half
# reading the caller's. `vault_roots()` is the single definition; it REQUIRES
# the complete set, so the next root added here fails loudly at every rebind
# site instead of quietly splitting a run across two vaults.
#
# (PLACEMENTS_FILE is defined further down, next to the placement store; the
# names are resolved out of module globals at rebind time.)
VAULT_ROOT_NAMES = (
    "CLASSIFICATIONS_DIR",
    "CONNECTORS_STATE_DIR",
    "ENTITY_ROSTERS_DIR",
    "MANUAL_SOURCES_DIR",
    "PLACEMENTS_FILE",
    "STATE_DIR",
    "WIKI_DIR",
)


@contextlib.contextmanager
def vault_roots(**roots: Path):
    """Run the enclosed timeline call against `roots` instead of this process's
    vault, restoring the originals afterwards. Every name in
    :data:`VAULT_ROOT_NAMES` must be supplied."""
    unknown = sorted(set(roots) - set(VAULT_ROOT_NAMES))
    if unknown:
        raise ValueError(f"not a timeline vault root: {', '.join(unknown)}")
    missing = sorted(set(VAULT_ROOT_NAMES) - set(roots))
    if missing:
        raise ValueError(
            "timeline vault rebind must supply every root; missing: "
            f"{', '.join(missing)}"
        )
    saved = {name: globals()[name] for name in VAULT_ROOT_NAMES}
    globals().update(roots)
    try:
        yield
    finally:
        globals().update(saved)


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
    roster = read_json(ENTITY_ROSTERS_DIR / "period.json", default=None) or {}
    by_slug: dict[str, dict] = {}
    for ent in roster.get("entities", []) or []:
        if not ent.get("page_eligible"):
            continue
        slug = ent.get("slug") or slugify(ent.get("name", ""))
        by_slug[slug] = {
            "slug": slug,
            "name": ent.get("name", slug),
            "aliases": [str(a) for a in (ent.get("aliases") or []) if str(a).strip()],
            "chrono": ent.get("chrono"),
            "chrono_source": "roster" if ent.get("chrono") is not None else None,
            "sources": set(),
            "page": None,
            "approximate_dates": str(ent.get("approximate_dates") or ""),
            "date": chrono.parse_edtf(ent.get("date")),
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
                "aliases": [],
                "chrono": None,
                "chrono_source": None,
                "sources": set(),
                "page": None,
                "approximate_dates": "",
                "date": None,
            })
            entry["page"] = page.relative_to(WIKI_DIR.parent).as_posix()
            entry["sources"] = _page_sources(text)
            if entry["chrono"] is None:
                raw = _frontmatter_value(text, "chrono")
                entry["chrono"] = int(raw) if raw.isdigit() else None
                if entry["chrono"] is not None:
                    entry["chrono_source"] = "page"
            if not entry["approximate_dates"]:
                entry["approximate_dates"] = _frontmatter_value(text, "approximate_dates")
            if entry.get("date") is None:
                entry["date"] = chrono.parse_edtf(_frontmatter_value(text, "date"))

    periods = list(by_slug.values())
    for entry in periods:
        # `approximate_dates` had no writer before v195 (the contract's hole 2).
        # It stays as the DERIVED display alias of the real record, so every
        # existing reader keeps working and the string finally has a source.
        if entry.get("date") is None and entry.get("approximate_dates"):
            entry["date"] = chrono.parse_edtf(entry["approximate_dates"])
        if entry.get("date") is not None:
            entry["approximate_dates"] = chrono.display_date(entry["date"], with_basis=False)
    return derive_chrono(periods)


def derive_chrono(periods: list[dict]) -> list[dict]:
    """Order the spine by DATES where they exist; the LLM ordinal is the floor.

    `chrono` was a monthly roster-model opinion and the sole spine order — so a
    period the owner had DATED still sorted by a guess (ADR 0024). The derived
    rule, in five deterministic steps:

      1. take the pre-v195 order (`chrono`, None last, slug tiebreak) as the
         fallback sequence — with nothing dated this function is a no-op and
         the spine is byte-identical to v194;
      2. anchor every dated period at its `date.earliest` year;
      3. estimate a year for each undated period by linear interpolation
         between its nearest dated neighbours in that fallback sequence
         (±1 per step beyond the ends);
      4. sort by (estimated year, fallback index, slug);
      5. dense-rank into `chrono`, recording `chrono_source` per period.

    Mutates and returns the same list objects (callers hold references).
    """
    ordered = sorted(periods, key=lambda p: (p.get("chrono") is None, p.get("chrono") or 0, p["slug"]))
    anchors = [(index, chrono.year_of(period.get("date")))
               for index, period in enumerate(ordered)
               if chrono.year_of(period.get("date")) is not None]
    if not anchors:
        return ordered
    estimates: list[float] = []
    for index, period in enumerate(ordered):
        year = chrono.year_of(period.get("date"))
        if year is not None:
            estimates.append(float(year))
            period["chrono_source"] = "date"
            continue
        before = [a for a in anchors if a[0] < index]
        after = [a for a in anchors if a[0] > index]
        if before and after:
            (li, ly), (ri, ry) = before[-1], after[0]
            estimates.append(ly + (ry - ly) * ((index - li) / (ri - li)))
        elif before:
            li, ly = before[-1]
            estimates.append(float(ly + (index - li)))
        else:
            ri, ry = after[0]
            estimates.append(float(ry - (ri - index)))
    ranked = sorted(range(len(ordered)), key=lambda i: (estimates[i], i, ordered[i]["slug"]))
    result = [ordered[i] for i in ranked]
    for rank, period in enumerate(result, start=1):
        period["chrono"] = rank
    return result


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
        chapter = {
            "number": int(m.group(1)),
            "title": m.group(2).strip(),
            "body": body,
            "source": candidates[-1].name,
        }
        chapter["date"] = chapter_date(chapter)
        chapters.append(chapter)
    chapters.sort(key=lambda c: c["number"])
    return chapters


#: The chapters exercise asks for the transition statements ("It ends when…",
#: "from X to Y"), and those statements are where a chapter's span lives.
_CHAPTER_SPAN_RES = (
    re.compile(r"\b(\d{4})\s*(?:[-–—]|to|through|until|till)\s*(\d{4})\b", re.IGNORECASE),
    re.compile(r"\bfrom\s+(\d{4})\s+(?:to|until|through)\s+(\d{4})\b", re.IGNORECASE),
)
_CHAPTER_YEAR_RE = re.compile(r"\b(1[89]\d{2}|20\d{2})\b")


def chapter_date(chapter: dict) -> object:
    """A life chapter's span, read from the exercise's own words (ADR 0024).

    The owner's hierarchy is Chapter → Places → Events, so a chapter needs a
    span before it can be a band. Explicit ranges win; two or more bare years
    in the chapter text give their outer bounds as an INFERRED interval (an
    interval is a finding, never a guessed point); a single year gives that
    year, conjecturally. No years at all is honestly `None` — an undated
    chapter simply is not a band.
    """
    text = f"{chapter.get('title', '')} {chapter.get('body', '')}"
    for pattern in _CHAPTER_SPAN_RES:
        match = pattern.search(text)
        if match:
            record = chrono.parse_edtf(f"{match.group(1)}/{match.group(2)}", basis="stated")
            if record:
                return record
    years = sorted({int(y) for y in _CHAPTER_YEAR_RE.findall(text)})
    if len(years) >= 2:
        return chrono.DateRecord(
            best=f"{years[0]}/{years[-1]}", earliest=str(years[0]), latest=str(years[-1]),
            granularity="range", confidence="inferred", basis="order",
        )
    if len(years) == 1:
        return chrono.DateRecord(
            best=f"{years[0]}?", earliest=str(years[0]), latest=str(years[0]),
            granularity="year", confidence="conjectural", basis="order",
        )
    return None


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
        # v195: DATE CONTAINMENT first when both sides carry spans — the
        # chapter and the period are then talking about the same stretch of
        # time and no keyword has to be trusted. The conservative name match
        # below stays as the fallback for undated chapters (unchanged), and
        # neither path ever guesses: an unaligned chapter stacks on its own.
        chapter_span = chapter.get("date")
        if chapter_span is not None:
            overlapping = [p for p in periods
                           if p.get("date") is not None and _spans_overlap(chapter_span, p["date"])]
            if overlapping:
                match_slug = min(
                    overlapping,
                    key=lambda p: (chrono.year_of(p["date"]) or 0, p["slug"]),
                )["slug"]
        if match_slug is None:
            for slug, name in period_names.items():
                if name in body_lower:
                    match_slug = slug
                    break
        aligned.append({**chapter, "aligned_period": match_slug})
    return aligned


def _spans_overlap(left: object, right: object) -> bool:
    """Do two date records share any year? (Open bounds extend forever.)"""
    lo_a, hi_a = chrono.year_of(left), chrono.year_of(left, end=True)
    lo_b, hi_b = chrono.year_of(right), chrono.year_of(right, end=True)
    lo_a = lo_a if lo_a is not None else -9999
    hi_a = hi_a if hi_a is not None else 9999
    lo_b = lo_b if lo_b is not None else -9999
    hi_b = hi_b if hi_b is not None else 9999
    return lo_a <= hi_b and lo_b <= hi_a


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
                # v195: a PLACE with a span is a residence — the life-history
                # calendar's own index (Conway & Pleydell-Pearce), and the
                # second level of the owner's Chapter -> Places -> Events
                # hierarchy. Written by the skeleton episode through
                # `timeline-place`; absent until then.
                "date": chrono.parse_edtf(_frontmatter_value(text, "date")),
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
            claim = chrono.possible_date_claim(event.get("date"))
            row = {
                "description": desc,
                # v195 (ruling 2): the classifier's noun phrase — the thing,
                # not the telling. `event_title` is the ONE fallback so no
                # caller invents a second one.
                "title": str(event.get("title") or "").strip(),
                "when_hint": str(event.get("when_hint") or "").strip(),
                "anchor": str(event.get("anchor") or "").strip(),
                "source": source,
                "source_short": _short_source(source),
                "eras": eras,
                # The raw claim survives beside the resolved record: the claim
                # is what the AUTHOR said, the record is what the system
                # worked out from it, and a later anchor can re-resolve the
                # claim without re-reading the classification.
                "date_claim": claim,
                # Resolved here with NO anchors — stated dates only.
                # `resolve_event_dates` upgrades age/anchor claims once
                # `timeline_data` has assembled the anchor index.
                "date": chrono.record_from_claim(claim) if claim else None,
            }
            row["title"] = row["title"] or event_title(row)
            out.append(row)
    return out


#: Ruling 2: a noun phrase of at most seven words. When the classifier has not
#: supplied one (every pre-v195 classification), the fallback is the
#: description's first clause, trimmed to the same length — deterministic, and
#: never invented content.
EVENT_TITLE_MAX_WORDS = 7


def event_title(event: dict) -> str:
    """The event's title, with the single authoritative fallback."""
    title = str((event or {}).get("title") or "").strip()
    if title:
        return " ".join(title.split()[:EVENT_TITLE_MAX_WORDS])
    description = str((event or {}).get("description") or "").strip()
    if not description:
        return ""
    clause = re.split(r"[,;:.!?]| — | – ", description, maxsplit=1)[0].strip()
    words = (clause or description).split()
    return " ".join(words[:EVENT_TITLE_MAX_WORDS])


def resolve_event_dates(events: list[dict], anchors: dict | None = None,
                        birth_date: object = None) -> list[dict]:
    """Re-resolve every event's date claim against the assembled anchors.

    This is where "I was about five" becomes `1984~` and "before the move to
    Mesa" becomes `../1984`: the arithmetic is `chronology`'s, the anchors are
    the person's own landmarks, and an event whose claim cannot be resolved
    keeps whatever stated-only record `load_events` already gave it. Mutates
    and returns the same rows.
    """
    for event in events:
        claim = event.get("date_claim")
        if not claim:
            continue
        resolved = chrono.record_from_claim(claim, birth_date=birth_date, anchors=anchors)
        if resolved is not None:
            event["date"] = resolved
    return events


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
#
# v103: the pin is display-only; the INFORMATION lives in the date-kind
# correction the viewer files alongside it (record's `correction` field).
# That correction marks the source for re-classification, so eventually the
# classification places the event itself — `placement_redundant` on a placed
# event means the loop has caught up.
#
# v105: caught-up pins retire AUTOMATICALLY — the weekly maintenance runs
# `retire_redundant_placements()` after classification, moving each redundant
# pin into the file's `retired` list (the filed correction remains the
# information; nothing is lost). Orphaned pins never auto-retire — they keep
# surfacing as stale notices for the owner to resolve.
# ---------------------------------------------------------------------------

PLACEMENTS_FILE = TIMELINE_PLACEMENTS_FILE
LANDMARKS_STORE = LANDMARKS_FILE


def placement_key(event: dict) -> str:
    import hashlib  # noqa: PLC0415
    payload = f"{event.get('source', '')}\n{event.get('description', '')}"
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()[:12]


def load_placements() -> dict:
    data = read_json(PLACEMENTS_FILE, default=None) or {"version": 1, "placements": []}
    data.setdefault("placements", [])
    data.setdefault("retired", [])
    return data


def save_placement(key: str, source: str, description: str, period: str,
                   when_hint: str = "", note: str = "", correction: str = "",
                   date: object = None) -> dict:
    """Add or replace the manual placement for one event. `correction` links
    the pin to the correction source the placement filed (v103) — the pin is
    the display overlay, the correction is the information.

    v195: `date` is a `chronology.DateRecord` (or its serialized form) — the
    placement's own dated claim, stored beside the pin so the timeline can
    render a chip without waiting for reclassification. Absent `date` the
    record is byte-identical to v194's.
    """
    data = load_placements()
    data["placements"] = [p for p in data["placements"] if p.get("key") != key]
    record = {"key": key, "source": source, "description": description,
              "period": period, "when_hint": when_hint, "note": note,
              "correction": correction, "placed_at": now_utc()}
    parsed = chrono.from_dict(date) if date is not None else None
    if parsed is not None:
        record["date"] = parsed.to_dict()
    data["placements"].append(record)
    write_json(PLACEMENTS_FILE, data)
    return record


def remove_placement(key: str) -> bool:
    data = load_placements()
    before = len(data["placements"])
    data["placements"] = [p for p in data["placements"] if p.get("key") != key]
    if len(data["placements"]) == before:
        return False
    write_json(PLACEMENTS_FILE, data)
    return True


# ---------------------------------------------------------------------------
# The landmark store (v197) — the answers to the always-present question set.
# ---------------------------------------------------------------------------

LANDMARKS_SCHEMA_VERSION = 1


def load_landmarks() -> dict:
    """``{domain: [entry, ...]}`` — every landmark the person has given.

    Degrades to an empty set rather than raising: a hand-edited or
    half-written store must never take the timeline down.
    """
    data = read_json(LANDMARKS_STORE, default=None)
    if not isinstance(data, dict):
        return {}
    domains = data.get("domains")
    if not isinstance(domains, dict):
        return {}
    return {str(key): [e for e in (value or []) if isinstance(e, dict)]
            for key, value in domains.items() if isinstance(value, list)}


def save_landmark(domain: str, record: object) -> dict:
    """Add or replace one landmark entry, keyed by its label within a domain.

    Replacement is by ``label`` because the ladder revisits the same subject —
    a city today, an address next week, a span after that — and each pass adds
    rungs to the SAME entry rather than making a second one. HOW the two
    records combine is `landmarks_interaction.merge_landmark_entry` — one
    definition, so the none terminal supersedes and is superseded here exactly
    as it does everywhere else.
    """
    if not isinstance(record, dict):
        raise ValueError("a landmark record must be an object")
    key = str(domain or "").strip()
    if not key:
        raise ValueError("a landmark needs a domain")
    data = read_json(LANDMARKS_STORE, default=None)
    if not isinstance(data, dict):
        data = {}
    data.setdefault("version", LANDMARKS_SCHEMA_VERSION)
    domains = data.setdefault("domains", {})
    if not isinstance(domains, dict):
        domains = data["domains"] = {}
    entries = [e for e in (domains.get(key) or []) if isinstance(e, dict)]
    label = str(record.get("label") or "").strip()
    merged = landmarks_interaction.merge_landmark_entry(None, record)
    for existing in entries:
        if str(existing.get("label") or "").strip() == label:
            merged = landmarks_interaction.merge_landmark_entry(existing, record)
            break
    entries = [e for e in entries
               if str(e.get("label") or "").strip() != label] + [merged]
    domains[key] = entries
    write_json(LANDMARKS_STORE, data)
    return merged


def landmark_birth_date(landmarks: object = None) -> object:
    """The person's birthday as a `chronology.DateRecord`, or None.

    This is the function that makes `chronology.from_age` reachable in
    production (`system/research/landmarks.md` §3.7): before v197 `birth_date`
    was a parameter nothing ever supplied.
    """
    filed = landmarks if isinstance(landmarks, dict) else load_landmarks()
    for entry in filed.get("birth") or ():
        if not isinstance(entry, dict):
            continue
        record = chrono.from_dict(entry.get("date"))
        if record is not None:
            return record
    return None


def _keyword_slot(haystack: str, periods: list[dict]) -> str | None:
    for period in periods:
        for keyword in _PERIOD_KEYWORDS.get(period["slug"], ()):
            if keyword in haystack:
                return period["slug"]
    return None


def heuristic_slot(event: dict, periods: list[dict],
                   vocab: dict[str, set[str]]) -> str | None:
    """Where the system would place this event WITHOUT a manual pin.
      1. The event's OWN when_hint is the most specific signal — an
         arc-spanning answer contributes events across many eras, so the
         per-event time-words outrank the answer's period membership
         ("a month before I graduated college" → college, even when the
         source answer sits on the high-school page).
      2. Source membership: the answer belongs to a period page.
      3. The classification's era text.
      4. Learned distinctive era-vocabulary (≥2 shared tokens)."""
    slot = _keyword_slot(event["when_hint"].lower(), periods) if event["when_hint"] else None
    if slot is None:
        for period in periods:
            if event["source"] in period["sources"]:
                slot = period["slug"]
                break
    if slot is None:
        slot = _keyword_slot(" ".join(event["eras"]), periods)
    if slot is None:
        event_tokens = _era_tokens(" ".join(event["eras"] + [event["when_hint"].lower()]))
        best_slug, best_overlap = None, 1
        for period in periods:
            overlap = len(event_tokens & vocab.get(period["slug"], set()))
            if overlap > best_overlap:
                best_slug, best_overlap = period["slug"], overlap
        slot = best_slug
    return slot


def place_events(events: list[dict], periods: list[dict],
                 placements: dict | None = None) -> tuple[dict[str, list[dict]], list[dict]]:
    """({period_slug: [events...]}, unplaced). Placement order:
      0. the owner's manual placement (content-keyed overlay) — always wins
      1-4. `heuristic_slot` (when_hint keywords → source membership → era
         text → learned era-vocabulary), then an explicit unplaced bucket —
         never forced."""
    placed: dict[str, list[dict]] = {p["slug"]: [] for p in periods}
    unplaced: list[dict] = []
    vocab = learned_era_vocabulary(periods, events)
    manual_by_key = {}
    if placements:
        manual_by_key = {p["key"]: p for p in placements.get("placements", [])
                         if p.get("period") in placed}

    for event in events:
        # 0) The owner said so — manual placement outranks every heuristic.
        if manual_by_key:
            manual = manual_by_key.get(placement_key(event))
            if manual:
                # Redundancy check runs on the ORIGINAL event: once the
                # classification itself places it here (the loop caught up),
                # the pin retires on the next weekly pass (v105).
                redundant = heuristic_slot(event, periods, vocab) == manual["period"]
                event = dict(event)
                event["placement"] = "manual"
                event["placement_key"] = manual["key"]
                event["placement_correction"] = manual.get("correction", "")
                event["placement_redundant"] = redundant
                if manual.get("when_hint"):
                    event["when_hint"] = manual["when_hint"]
                if manual.get("date"):
                    pinned = chrono.from_dict(manual["date"])
                    if pinned is not None:
                        event["date"] = pinned
                if manual.get("note"):
                    event["placement_note"] = manual["note"]
                placed[manual["period"]].append(event)
                continue
        slot = heuristic_slot(event, periods, vocab)
        if slot is None:
            unplaced.append(event)
        else:
            placed[slot].append(event)
    for rows in placed.values():
        # Dated moments lead, in date order; everything after is v194's exact
        # key, so a period with no dated events sorts byte-identically.
        rows.sort(key=lambda e: (e.get("date") is None,
                                 chrono.year_of(e.get("date")) or 0,
                                 not e["when_hint"], e["source_short"]))
    return placed, unplaced


def retire_redundant_placements(dry_run: bool = False) -> list[dict]:
    """Retire pins the loop has caught up with (v105).

    A pin retires only when its event is still LIVE (same content key) and
    `heuristic_slot` on the original event lands in the pinned period — i.e.
    the system now places the moment correctly with no pin at all. The record
    moves to the file's `retired` list (with the correction link intact), so
    provenance survives; the filed date assertion is untouched. Orphaned pins
    (event rewritten, period page gone) never retire here — they surface as
    stale notices instead. Returns the retired records."""
    data = load_placements()
    if not data["placements"]:
        return []
    periods = load_periods()
    events = load_events()
    vocab = learned_era_vocabulary(periods, events)
    events_by_key = {placement_key(e): e for e in events}
    period_slugs = {p["slug"] for p in periods}
    keep: list[dict] = []
    retired: list[dict] = []
    for pin in data["placements"]:
        event = events_by_key.get(pin.get("key"))
        if (event is not None and pin.get("period") in period_slugs
                and heuristic_slot(event, periods, vocab) == pin["period"]):
            retired.append({**pin, "retired_at": now_utc(),
                            "retired_reason": "loop caught up — places itself"})
        else:
            keep.append(pin)
    if retired and not dry_run:
        data["placements"] = keep
        data["retired"].extend(retired)
        write_json(PLACEMENTS_FILE, data)
    return retired


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
    gaps.extend(era_gaps(periods, event_lineup))
    return gaps


#: An era gap has to be a real hole, not two eras that touch.
MIN_ERA_GAP_YEARS = 1


def era_gaps(periods: list[dict], event_lineup: dict[str, list[dict]]) -> list[dict]:
    """Dated holes BETWEEN dated eras — "2000–2006 · nothing placed here yet".

    The one genuinely new gap kind (ADR 0024). It can only exist once eras
    carry dates, which is why it could not exist before v195: with no dates
    there is no measurable hole, only an unordered list. Emitted when two
    ADJACENT eras are both dated, the hole between them is at least
    :data:`MIN_ERA_GAP_YEARS` wide, and no dated moment sits inside it.
    """
    dated = [p for p in periods if chrono.year_of(p.get("date")) is not None]
    out: list[dict] = []
    for previous, following in zip(dated, dated[1:]):
        last = chrono.year_of(previous.get("date"), end=True)
        first = chrono.year_of(following.get("date"))
        if last is None or first is None:
            continue
        start, end = last + 1, first - 1
        if end - start + 1 < MIN_ERA_GAP_YEARS:
            continue
        occupied = any(
            start <= (chrono.year_of(event.get("date")) or -9999) <= end
            for rows in event_lineup.values() for event in rows
        )
        if occupied:
            continue
        span = f"{start}" if start == end else f"{start}–{end}"
        out.append({
            "kind": "era_gap",
            "period": None,
            "between": [previous["slug"], following["slug"]],
            "years": [start, end],
            "message": f"{span} — nothing placed here yet, between "
                       f"{previous['name']} and {following['name']}.",
            "hint": "Anchor it against something already dated — where were you "
                    "living, what work were you doing — never a calendar year first.",
        })
    return out


# ---------------------------------------------------------------------------
# Bands — Chapter → Places → Events (owner ruling 2, amended).
#
# The person's OWN life chapter (the McAdams exercise) is the band wherever one
# covers the stretch; the places lived sit inside it; events sit under each
# place; the system's era/period is the band ONLY where no chapter covers that
# stretch. `bands` is the one shape a renderer needs — every other key here is
# a convenience view over it.
# ---------------------------------------------------------------------------

BAND_KINDS = ("chapter", "period")


def build_bands(periods: list[dict], chapters: list[dict],
                entity_lineup: dict[str, list[dict]],
                event_lineup: dict[str, list[dict]]) -> list[dict]:
    """`[{kind, ref, label, date, places: [{slug,label,date,events}], unplaced_events}]`."""
    dated_chapters = [c for c in chapters if c.get("date") is not None]
    covered: dict[str, dict] = {}
    bands: list[dict] = []
    for chapter in sorted(dated_chapters, key=lambda c: (chrono.year_of(c["date"]) or 0, c["number"])):
        members = [p for p in periods
                   if p.get("date") is not None
                   and p["slug"] not in covered
                   and _spans_overlap(chapter["date"], p["date"])]
        if not members:
            continue
        band = {"kind": "chapter", "ref": str(chapter["number"]),
                "label": chapter["title"], "date": chapter["date"],
                "periods": [p["slug"] for p in members],
                "places": [], "unplaced_events": []}
        for member in members:
            covered[member["slug"]] = band
        bands.append(band)
    for period in periods:
        if period["slug"] in covered:
            continue
        bands.append({"kind": "period", "ref": period["slug"], "label": period["name"],
                      "date": period.get("date"), "periods": [period["slug"]],
                      "places": [], "unplaced_events": []})
    order = {p["slug"]: index for index, p in enumerate(periods)}
    bands.sort(key=lambda b: (min(order.get(slug, 0) for slug in b["periods"]), b["ref"]))
    for band in bands:
        _fill_band(band, entity_lineup, event_lineup)
    return bands


def _fill_band(band: dict, entity_lineup: dict[str, list[dict]],
               event_lineup: dict[str, list[dict]]) -> None:
    places: dict[str, dict] = {}
    for slug in band["periods"]:
        for row in entity_lineup.get(slug, []):
            if row.get("type") != "place":
                continue
            place = places.setdefault(row["slug"], {
                "slug": row["slug"], "label": row.get("title") or row["slug"],
                "date": row.get("date"), "page": row.get("page"),
                "sources": set(), "events": [],
            })
            place["sources"] |= set(row.get("sources") or ())
    events = [event for slug in band["periods"] for event in event_lineup.get(slug, [])]
    for event in events:
        home = _place_for_event(event, places)
        (home["events"] if home is not None else band["unplaced_events"]).append(event)
    for place in places.values():
        if place.get("date") is None:
            place["date"] = _place_span(place["events"])
        place.pop("sources", None)
    band["places"] = sorted(
        places.values(),
        key=lambda pl: (chrono.year_of(pl.get("date")) if pl.get("date") is not None else 9999,
                        pl["slug"]),
    )


def _place_for_event(event: dict, places: dict[str, dict]) -> dict | None:
    """The place whose OWN sources cite this event's source — the same provable
    source-overlap discipline the entity lineup uses, never keyword-fuzzy.
    Ties go to the more specific place (the smaller source set)."""
    matches = [place for place in places.values() if event.get("source") in place["sources"]]
    if not matches:
        return None
    return min(matches, key=lambda pl: (len(pl["sources"]), pl["slug"]))


def _place_span(events: list[dict]) -> object:
    """A residence's span inferred from the dated moments that happened there."""
    years = [y for y in (chrono.year_of(e.get("date")) for e in events) if y is not None]
    ends = [y for y in (chrono.year_of(e.get("date"), end=True) for e in events) if y is not None]
    if not years:
        return None
    first, last = min(years), max(ends or years)
    if first == last:
        return chrono.DateRecord(best=f"{first}?", earliest=str(first), latest=str(first),
                                 granularity="year", confidence="conjectural", basis="order")
    return chrono.DateRecord(best=f"{first}/{last}", earliest=str(first), latest=str(last),
                             granularity="range", confidence="inferred", basis="order")


# ---------------------------------------------------------------------------
# Unknowns, leverage, keystones (owner rulings 4 and 5).
# ---------------------------------------------------------------------------

#: v196 (owner ruling, "Unknowns are concrete"): an unknown is ONE SUBJECT the
#: person can actually answer about — a specific moment, a specific era's
#: missing bounds, a specific place's span, a dated hole between two named
#: eras, a specific contradiction. The v195 aggregate kinds
#: (`unplaced_events`, `no_chrono`, `no_events`, `all_undated`, `thin_lineup`,
#: `unplaced_entities`) are COUNTS, not questions: "116 moment(s) I can't place
#: in any period" is a number on a ledger, and the owner is right that it is
#: unanswerable as a question. They live on in `compute_gaps` (the page's own
#: gap notes) and in `unknown_ledger`; they never become an unknown.
UNKNOWN_KINDS = (
    "moment",
    "period_bound",
    "place_span",
    "era_gap",
    "date_contradiction",
    # v202 (family-landmark, owner rulings 4 and 5): the landmark set's own
    # concrete unknowns — ONE half-filled subject ("What year was Jackie
    # born?") and ONE hole in the residence chain ("Where did you live between
    # Mesa and Yucaipa?"). Both arrive from `landmarks_interaction` carrying
    # their own exact question.
    "landmark_subject",
    "residence_gap",
)

#: The aggregate gap kinds that are counted rather than asked.
LEDGER_GAP_KINDS = (
    "no_chrono", "no_events", "all_undated", "thin_lineup",
    "unplaced_events", "unplaced_entities",
)

#: Owner's cap: at most two starred keystones, ever.
KEYSTONE_CAP = 2

#: How many unknowns a page offers at once, leverage-ordered. The rest are not
#: hidden — `unknown_ledger` carries every total — but a list of 116 rows is
#: not a thing anyone answers.
UNKNOWNS_PAGE_CAP = 30


def unknown_key(gap: dict) -> str:
    """A stable, content-derived key for one unknown or gap row."""
    kind = str(gap.get("kind") or "unknown")
    if kind == "era_gap":
        return f"era_gap:{':'.join(str(x) for x in (gap.get('between') or []))}"
    if kind == "moment":
        return f"moment:{gap.get('period') or ''}:{gap.get('source_short') or ''}"
    if kind in ("period_bound", "place_span"):
        return f"{kind}:{gap.get('slug') or gap.get('period') or ''}"
    # v202: both landmark-derived kinds mint their own key at build time (the
    # domain and the two span labels are only known there); it is authoritative.
    if kind in ("landmark_subject", "residence_gap") and gap.get("key"):
        return str(gap["key"])
    scope = str(gap.get("period") or "")
    return f"{kind}:{scope}" if scope else kind


def moment_unknown(event: dict, period: str | None) -> dict:
    """One undated moment, named by its own title — the commonest unknown."""
    label = str(event.get("title") or event.get("description") or "this moment").strip()
    row = {
        "kind": "moment",
        "period": period,
        "source_short": event.get("source_short"),
        "source": event.get("source"),
        "label": label,
        "hint": "Anchor it against something already dated — never a guessed year.",
    }
    row["key"] = unknown_key(row)
    return row


def unknowns(data: dict, landmarks: object = None) -> list[dict]:
    """Every ANSWERABLE unknown as `{kind, key, label, probe, ...}`.

    One subject per row (v196). An unknown is something a person can picture:
    *the dog that followed you home*, *when the Yucaipa years ended*, *the
    stretch between two dated eras*. Never a count.

    "I'll find out" is an ordinary answer — there is no `deferred` flag and no
    quiet window; an unknown the person could not date simply stays
    outstanding, keeps its leverage, and is asked again when the ordering says
    it is worth asking.
    """
    import timeline_interaction  # noqa: PLC0415  (probe vocabulary lives with the interaction)

    rows: list[dict] = []
    seen: set[str] = set()
    anchors = data.get("anchors") or ()

    def add(row: dict) -> None:
        if row["key"] in seen:
            return
        seen.add(row["key"])
        rows.append(row)

    # 1. Specific undated moments — placed ones first (they carry an era), then
    #    the ones that belong to no period at all.
    for slug, events_here in (data.get("event_lineup") or {}).items():
        for event in events_here:
            if event.get("date") is None:
                add(moment_unknown(event, slug))
    for event in data.get("unplaced_events") or []:
        add(moment_unknown(event, None))

    # 2. A specific era's missing bounds.
    for period in data.get("periods") or []:
        if period.get("date") is None:
            row = {
                "kind": "period_bound",
                "period": period["slug"],
                "slug": period["slug"],
                "label": str(period.get("name") or period["slug"]),
                "hint": "Bound it against a move, a job, a birth — the ends are "
                        "usually easier to name than the middle.",
            }
            row["key"] = unknown_key(row)
            add(row)

    # 3. A specific place with no span.
    for band in data.get("bands") or []:
        for place in band.get("places") or []:
            if place.get("date") is not None or place.get("span") is not None:
                continue
            slug = str(place.get("slug") or place.get("ref") or "").strip()
            if not slug:
                continue
            row = {
                "kind": "place_span",
                "period": band.get("ref"),
                "slug": slug,
                "label": str(place.get("title") or place.get("label") or slug),
                "hint": "When you moved in and when you left is usually a clearer "
                        "memory than a year.",
            }
            row["key"] = unknown_key(row)
            add(row)

    # 4. The dated holes and the contradictions — already one subject each.
    gaps = list(data.get("global_gaps") or [])
    for period_gaps in (data.get("gaps_by_period") or {}).values():
        gaps.extend(period_gaps)
    for gap in gaps:
        kind = str(gap.get("kind") or "")
        if kind not in ("era_gap", "date_contradiction"):
            continue
        row = {
            "kind": kind,
            "key": unknown_key(gap),
            "label": str(gap.get("message") or unknown_key(gap)),
            "period": gap.get("period"),
            "between": gap.get("between"),
            "years": gap.get("years"),
            "hint": gap.get("hint", ""),
        }
        add(row)

    # 5. v202 (owner rulings 4 and 5): the landmark set's own concrete
    #    unknowns. Guarded exactly as `timeline_data`'s landmark reads are — a
    #    landmark problem must never take the timeline down.
    try:
        for row in landmarks_interaction.incomplete_subjects(landmarks):
            add(row)
        for row in landmarks_interaction.residence_gaps(landmarks):
            add(row)
    except Exception:  # noqa: BLE001
        pass

    for row in rows:
        # v202: a row that arrived with its OWN exact question keeps it. The
        # landmark-derived kinds carry the ladder's subject-named wording
        # ("What year was Jackie born?"), which a generic KIND_OPENERS entry
        # could not express — one mechanism instead of two. Byte-identical for
        # every pre-existing row: none of them carried a probe before this line.
        probe = row.get("probe")
        if isinstance(probe, dict) and str(probe.get("text") or "").strip():
            continue
        row["probe"] = timeline_interaction.choose_probe(row, anchors=anchors)
    return rows


def unknown_ledger(data: dict) -> dict:
    """The counts the page shows INSTEAD of unanswerable aggregate rows."""
    gaps = list(data.get("global_gaps") or [])
    for period_gaps in (data.get("gaps_by_period") or {}).values():
        gaps.extend(period_gaps)
    counts = {kind: 0 for kind in LEDGER_GAP_KINDS}
    for gap in gaps:
        kind = str(gap.get("kind") or "")
        if kind in counts:
            counts[kind] += 1
    return {
        "unplaced_moments": len(data.get("unplaced_events") or []),
        "unplaced_pages": len(data.get("unplaced_entities") or []),
        "gap_notes": counts,
    }


def offered_unknowns(rows: list[dict], index: dict[str, set[str]],
                     limit: int = UNKNOWNS_PAGE_CAP) -> list[dict]:
    """The unknowns a page offers: leverage first, then the cheapest probe.

    Every row keeps its own `leverage` (how many other unknowns the best
    anchor for it would also place), so the ordering is visible rather than
    mysterious.
    """
    resolved_by: dict[str, int] = {}
    for keys in index.values():
        for key in keys:
            resolved_by[key] = max(resolved_by.get(key, 0), len(keys))
    for row in rows:
        row["leverage"] = resolved_by.get(row["key"], 0)
    ordered = sorted(rows, key=lambda row: (
        -int(row.get("leverage") or 0),
        int((row.get("probe") or {}).get("cost") or 99),
        str(row.get("key")),
    ))
    return ordered[:max(int(limit), 0)]


def dependency_index(data: dict) -> dict[str, set[str]]:
    """`{anchor_key: {unknown_key, ...}}` — what one answer would put in place.

    The anchor candidates are exactly the three ruling 5 names: a period's
    start/end, a landmark (dated) event, and an entity's arrival. An anchor
    resolves an unknown when placing the anchor would place the unknown:

    * a PERIOD anchor resolves that era's own bounds, every undated moment and
      place inside it, and every `era_gap` touching it;
    * a LANDMARK EVENT anchor resolves the undated moments sharing its period
      (the neighbours it would bound);
    * an ENTITY ARRIVAL anchor resolves the undated moments sharing its
      sources, and that era's own bounds.

    v196: the keys on both sides are the CONCRETE unknown keys `unknowns()`
    emits, so leverage counts real answerable things rather than aggregate
    rows.
    """
    index: dict[str, set[str]] = {}
    rows = unknowns(data)
    by_period: dict[str, set[str]] = {}
    era_touch: dict[str, set[str]] = {}
    by_source: dict[str, set[str]] = {}
    for row in rows:
        if row.get("period"):
            by_period.setdefault(str(row["period"]), set()).add(row["key"])
        for slug in (row.get("between") or []):
            era_touch.setdefault(str(slug), set()).add(row["key"])
        if row.get("source"):
            by_source.setdefault(str(row["source"]), set()).add(row["key"])

    event_lineup = data.get("event_lineup") or {}
    entity_lineup = data.get("entity_lineup") or {}
    for period in data.get("periods") or []:
        slug = period["slug"]
        index[f"period:{slug}"] = set(by_period.get(slug, set())) | set(era_touch.get(slug, set()))

    for slug, rows_here in event_lineup.items():
        for event in rows_here:
            if event.get("date") is None:
                continue
            key = f"event:{slug}:{event.get('source_short') or ''}"
            neighbours = {f"moment:{slug}:{other.get('source_short') or ''}"
                          for other in rows_here if other.get("date") is None}
            index[key] = (neighbours & {row["key"] for row in rows}) | set(era_touch.get(slug, set()))

    for slug, rows_here in entity_lineup.items():
        for row in rows_here:
            if row.get("type") not in ("person", "place"):
                continue
            key = f"entity:{row['slug']}"
            shared: set[str] = set()
            for source in (row.get("sources") or ()):
                shared |= by_source.get(str(source), set())
            index[key] = index.get(key, set()) | shared | set(by_period.get(slug, set()))
    return index


def leverage(anchor_key: str, index: dict[str, set[str]]) -> int:
    """How many unknowns one anchor would resolve (ruling 5)."""
    return len(index.get(anchor_key) or ())


def keystones(data: dict, n: int = KEYSTONE_CAP) -> list[dict]:
    """A GREEDY PLAN over the residual graph — not a top-`n` leverage list.

    v198 (`system/research/go-deep.md` §8.2/§8.3): ordering independently by
    leverage double-counts. On real vault data one star's resolve set was a
    strict SUBSET of the other's, so the second star's marginal gain was
    **zero** — two questions that place exactly what one question places.

    So the list is built the way a plan is: take the anchor with the largest
    gain against what is *still* unknown, remove what it covers, repeat.

    ```
    S ← ∅
    for i in 1..n:
        aᵢ    ← argmax_a |R(a) minus S|   # marginal gain, not leverage
        gainᵢ ← |R(aᵢ) minus S|
        S     ← S ∪ R(aᵢ)
    ```

    The coverage objective is monotone submodular, so greedy is within
    `(1 − 1/e) ≈ 63%` of optimal ([Nemhauser, Wolsey & Fisher, 1978](https://doi.org/10.1007/BF01588971));
    at `n = 2` nothing better is worth building.

    Each row keeps `leverage` — its TOTAL resolve set, which is the number the
    person is shown ("one answer would place 14 moments") — and gains `gain`,
    the marginal contribution that earned it its place in the plan. An anchor
    whose marginal gain is zero is never starred, however large its leverage.

    Ties break by how CHEAP the playbook says the probe is (a high-gain anchor
    that needs an expensive probe loses to an equally gaining one that needs a
    cheap one), then by key.

    v196: every row carries the IDENTITY it is asked under —
    `question_id` (`tl:<anchor-slug>`), the `unknown_keys` one answer would
    place, and the person's own `anchors` so a placement can be validated
    against landmarks this episode actually showed. A whisper
    (`arc_planner._timeline_gap_intent`) and a minted keystone question
    (`timeline_interaction.mint_keystone_question`) are the two ways the row
    becomes a question, and both match by `question_id`, never by adjacency.

    v204 (the Reading Room, ADR 0025): the scoring pass and the greedy loop
    moved out to `_scored_anchors` and `_greedy_plan`, so `dig_plan` EXTENDS
    this same plan to `k` picks with a witness partition instead of forking a
    second, drifting copy of it. Nothing about a keystone changed.
    """
    return _greedy_plan(_scored_anchors(data), n)


def _anchor_labels(data: dict) -> dict[str, str]:
    """`{anchor_key: human label}` for every anchor `dependency_index` mints."""
    labels = {f"period:{p['slug']}": p["name"] for p in (data.get("periods") or [])}
    for slug, rows_here in (data.get("entity_lineup") or {}).items():  # noqa: B007
        for row in rows_here:
            if row.get("slug"):
                labels.setdefault(f"entity:{row['slug']}",
                                  str(row.get("title") or row["slug"]))
    for slug, rows_here in (data.get("event_lineup") or {}).items():
        for event in rows_here:
            labels.setdefault(f"event:{slug}:{event.get('source_short') or ''}",
                              str(event.get("title") or event.get("description") or ""))
    return labels


def _scored_anchors(data: dict) -> list[dict]:
    """Every anchor that resolves at least one unknown, with its probe.

    The rows are freshly built on every call, so the greedy loop is free to
    stamp `gain` on the ones it picks without mutating anything shared.
    """
    import timeline_interaction  # noqa: PLC0415

    index = dependency_index(data)
    labels = _anchor_labels(data)
    anchors = data.get("anchors") or ()
    anchor_rows = timeline_interaction.anchor_rows_for_prompt(anchors)
    scored = []
    for key, resolved in index.items():
        if not resolved:
            continue
        # v196: the star's own question. "Childhood — one answer would place 23
        # more things" is not a question anyone can answer; the probe names the
        # anchor and asks about it.
        probe = timeline_interaction.keystone_probe(
            key, label=labels.get(key, key.split(":", 1)[-1].replace("-", " ")),
            anchors=anchors)
        scored.append({
            "anchor": key,
            "question_id": timeline_interaction.keystone_question_id(key),
            "label": labels.get(key, key.split(":", 1)[-1].replace("-", " ")),
            "leverage": len(resolved),
            "unknown_keys": sorted(resolved),
            # `resolves` is v195's name for the same list, kept so nothing that
            # reads a keystone row today has to change.
            "resolves": sorted(resolved),
            "probe": probe,
            "anchors": [dict(row) for row in anchor_rows],
        })
    return scored


def _greedy_plan(
    scored: list[dict],
    n: int,
    *,
    width: object = None,
    universe: set[str] | None = None,
) -> list[dict]:
    """The one greedy-over-the-residual definition (go-deep.md §8.3).

    `universe`, when given, restricts every resolve set to it — that is how
    the Reading Room takes the unknowns a WITNESS owns off the in-session
    table without building a second graph.

    `width`, when given, is `unknown_key -> float`, and the objective becomes
    the CONTINUOUS width-sum the research demands (§8.4, warning 3: a
    threshold count such as "how many become month-precise" is not
    submodular, so greedy stalls on it; a width-sum is, and the count stays a
    display number). With `width=None` every unknown weighs 1.0 and the key
    degenerates to exactly the pre-v204 `(-gain, cost, anchor)` ordering.
    """
    plan: list[dict] = []
    covered: set[str] = set()
    remaining = list(scored)
    for _ in range(max(int(n), 0)):
        best: dict | None = None
        best_key: tuple | None = None
        best_marginal: set[str] = set()
        for row in remaining:
            resolved = set(row["unknown_keys"])
            if universe is not None:
                resolved &= universe
            marginal = resolved - covered
            gain = len(marginal)
            if gain <= 0:
                continue
            gained = float(sum(width(key) for key in marginal)) if width else float(gain)
            key = (-gained, -gain, row["probe"].get("cost", 99), row["anchor"])
            if best_key is None or key < best_key:
                best, best_key, best_marginal = row, key, marginal
        if best is None or best_key is None:
            break  # nothing left adds anything — a shorter plan is the honest one
        best["gain"] = len(best_marginal)
        if width is not None:
            best["width_gain"] = -best_key[0]
        plan.append(best)
        covered |= best_marginal
        remaining = [row for row in remaining if row is not best]
    return plan


# ---------------------------------------------------------------------------
# The Reading Room (v204, ADR 0025) — the plan, the precision grade, the witness.
# ---------------------------------------------------------------------------

#: How many asks one Reading Room session arrives with (ruling 4). Three is
#: the number the research settles on: greedy is within (1 − 1/e) of optimal
#: on a monotone submodular coverage objective, and "at k ≈ 3 nothing better
#: is worth building" (`system/research/go-deep.md` §8.3).
DIG_PLAN_SIZE = 3

#: How many witness lines the Timeline row shows (ruling 4). The lists
#: themselves are longer; the ROW is calm.
WITNESS_LINE_CAP = 2

#: How many questions one witness's dig list may carry. "Don't ask for too
#: much at once. Ask simple, straightforward questions." (FamilySearch, via
#: go-deep.md §6.6 — the sharpest craft warning in the whole review.)
WITNESS_LIST_CAP = 5

#: The one string both the renderer and the harvest filter match on, so a dig
#: list rendered into a person's `## Open Questions` never becomes one of the
#: vault owner's own bank questions. One definition, two callers
#: (recurring-defect doctrine).
DIG_LIST_MARKER = "Reading Room"

#: The single line of guidance every dig list carries. Never a form.
DIG_LIST_FOOTER = (
    "Ask about events, not processes — cue, don't correct."
)

#: Generation order for the witness partition (go-deep.md §6.1: the one place
#: age-based triage is codified is US federal statute, and it orders oldest
#: first). `other`, `colleague` and `mentor` sit last because they are rarely
#: witnesses to a childhood. Urgency is THIS ORDERING and nothing else — never
#: a label on a person, and never a word about anybody's mortality.
WITNESS_GENERATION_ORDER = (
    "grandparent", "parent", "sibling", "spouse", "partner", "friend",
    "child", "mentor", "colleague", "other",
)

#: The closed vocabulary of precision grades (owner ruling, 2026-08-24): rank
#: by marginal coverage AND ask for the grade of detail that unlocks the
#: derivations. A school is a name until you have its ADDRESS; then it is a
#: district, and a district keeps records, and records give exact years
#: (go-deep.md §5.3). A birthday guessed to the year dates nothing to the day.
PRECISION_TARGETS = ("day", "month", "year", "span", "address", "city", "order")

#: What each grade actually buys — the clause the session says out loud.
PRECISION_UNLOCKS = {
    "day": "day-grade arithmetic on every age in the story",
    "month": "the season and the school term it fell inside",
    "year": "everything that stretch of years contains",
    "span": "every moment inside it, bounded from both ends",
    "address": "the district that keeps the records — and the exact years inside them",
    "city": "the entrance cutoff in force that year, and the calendar it implies",
    "order": "the sequence, which is what people remember best",
}

#: The grade to reach for, by unknown/anchor kind. `entity` splits on the
#: entity's own type: a place wants its street address, a person wants a day.
PRECISION_TARGET_BY_KIND = {
    "period": "span",
    "period_bound": "span",
    "place_span": "address",
    "place": "address",
    "person": "day",
    "event": "day",
    "moment": "day",
    "era_gap": "year",
    "date_contradiction": "month",
}

#: v202 minted two landmark-derived unknown kinds that `dependency_index`
#: correctly gives leverage 0: they place nothing that exists today. But each
#: one CREATES AN ANCHOR, and an anchor is the thing every other unknown is
#: placed against — which is the Reading Room's whole premise. The decision
#: (ADR 0025): they are NOT ranked on the coverage axis (that would mean
#: simulating a graph that does not exist yet, and warning 1 says do not
#: generalize the solver). They are given a QUOTA at the head of the session
#: instead, because they are also exactly the questions a document in the room
#: can answer — "what year was Jackie born" is printed on a birth certificate.
#: Their `would_place` stays honest at 1: the agenda never claims a gain the
#: ask has not earned.
ANCHOR_CREATING_KINDS = ("landmark_subject", "residence_gap")
LANDMARK_ASK_QUOTA = 1

#: A landmark subject's precision grade is the grade of the RUNG it is short
#: of — the ladder already decided what the next answer has to be.
PRECISION_TARGET_BY_RUNG = {
    "year": "year", "month": "month", "day": "day", "birth": "day",
    "city": "city", "place": "city", "address": "address",
    "span": "span", "grades": "year", "household": "order",
    "who": "order", "relation": "order", "living": "order",
    "name": "order", "what": "order", "where": "city", "branch": "order",
    "happened": "year",
}

_SCHOOL_WORDS = (
    "school", "elementary", "primary", "middle", "junior high", "high school",
    "academy", "college", "university", "kindergarten", "grade",
)
_BIRTH_WORDS = ("birth", "born", "birthday")


def unknown_width(row: object) -> float:
    """Years of ambiguity one unknown carries — the CONTINUOUS ranking quantity.

    go-deep.md §8.4, warning 3: a threshold metric ("how many become
    month-precise") is **not submodular**, so greedy stalls on it — two asks
    that each halve an interval can jointly cross the line while each scores
    zero alone. A width-sum is submodular, so the plan ranks on width and
    *displays* the count.

    An unknown with no interval at all weighs 1.0, which is the honest floor:
    on a vault where nothing carries bounds the ranking degenerates EXACTLY
    to marginal coverage, and §8.2's worked example reproduces unchanged.
    """
    if not isinstance(row, dict):
        return 1.0
    years = row.get("years")
    if isinstance(years, (list, tuple)) and len(years) == 2:
        try:
            span = float(years[1]) - float(years[0])
        except (TypeError, ValueError):
            span = 0.0
        if span > 0:
            return span
    return 1.0


def _living_roster(roster: object, data: object = None) -> list[dict]:
    """The people who could be asked, ordered by generation, oldest first.

    Inferred ONLY from stated facts, from the TWO sources the package already
    has and never a third:

    1. **`timeline_data()["witnesses"]`** — v202's family landmark, which is
       where witnesses actually come from (`landmarks.md` §2.9). Its
       `relation` IS the roster's `relationship`: one closed vocabulary, no
       translation table.
    2. The person entity roster's `relationship` + `living`, supplied by the
       owner through `entity-verdict`.

    `living` is tri-state in both: only an EXPLICIT yes makes a witness.
    Unknown is not a witness and is not a non-witness, and nothing here ever
    invokes anybody's mortality.
    """
    people: list[dict] = []
    seen: set[str] = set()
    for row in ((data or {}).get("witnesses") or ()) if isinstance(data, dict) else ():
        if not isinstance(row, dict):
            continue
        slug = str(row.get("slug") or "").strip()
        relation = str(row.get("relation") or "").strip()
        if not slug or not relation or slug in seen:
            continue
        seen.add(slug)
        people.append({"slug": slug,
                       "name": str(row.get("name") or slug.replace("-", " ")),
                       "relationship": relation})
    entities = roster
    if isinstance(entities, dict):
        entities = entities.get("entities")
    if entities is None:
        try:
            import entity_roster  # noqa: PLC0415

            entities = entity_roster.load_roster("person").get("entities") or []
        except Exception:  # noqa: BLE001
            entities = []
    for entry in entities or ():
        if not isinstance(entry, dict) or entry.get("living") is not True:
            continue
        slug = str(entry.get("slug") or "").strip()
        relationship = str(entry.get("relationship") or "").strip()
        if not slug or not relationship or slug in seen:
            continue
        seen.add(slug)
        people.append({
            "slug": slug,
            "name": str(entry.get("name") or slug.replace("-", " ")),
            "relationship": relationship,
        })
    order = {name: i for i, name in enumerate(WITNESS_GENERATION_ORDER)}
    people.sort(key=lambda row: (order.get(row["relationship"], len(order)), row["slug"]))
    return people


def _entity_reach(data: dict) -> dict[str, tuple[set[str], set[str]]]:
    """`{entity_slug: (periods, sources)}` from the lineup the vault already has."""
    reach: dict[str, tuple[set[str], set[str]]] = {}
    for period_slug, rows_here in (data.get("entity_lineup") or {}).items():
        for row in rows_here or ():
            slug = str(row.get("slug") or "").strip()
            if not slug:
                continue
            periods, sources = reach.setdefault(slug, (set(), set()))
            periods.add(str(period_slug))
            for source in (row.get("sources") or ()):
                sources.add(str(source))
            for source in (row.get("evidence") or ()):
                sources.add(str(source))
    return reach


def _ref_reach(ref: str, data: dict, rows_by_key: dict[str, dict],
               reach: dict | None = None) -> tuple[set[str], set[str]]:
    """The (periods, sources) one anchor key or unknown key touches.

    These are the SAME two joins `dependency_index` walks — shared source, and
    presence in the era whose bounds are missing. No new edge type is invented
    here (design consequence 11: "no new state").
    """
    text = str(ref or "")
    periods: set[str] = set()
    sources: set[str] = set()
    row = rows_by_key.get(text)
    if row is not None:
        if row.get("period"):
            periods.add(str(row["period"]))
        # A residence gap's `between` names two HOUSES, not two era slugs —
        # reading it as a period slug would be a silent false join.
        if str(row.get("kind") or "") not in ANCHOR_CREATING_KINDS:
            for slug in (row.get("between") or ()):
                periods.add(str(slug))
        for key in ("source_short", "source"):
            if row.get(key):
                sources.add(str(row[key]))
        return periods, sources
    kind, _, tail = text.partition(":")
    if kind == "period":
        periods.add(tail)
    elif kind == "event":
        period_slug, _, short = tail.partition(":")
        periods.add(period_slug)
        if short:
            sources.add(short)
    elif kind == "entity":
        index = _entity_reach(data) if reach is None else reach
        entity_periods, entity_sources = index.get(tail, (set(), set()))
        periods |= entity_periods
        sources |= entity_sources
    return periods, sources


def _witness_matcher(data: dict, people: list[dict], rows: object = None):
    """A closure that answers `witness_for` for many refs at one graph cost.

    `witness_for` is the single-ref public face of this; `dig_plan` uses the
    matcher directly so it does not re-walk `unknowns()` once per unknown.
    """
    reach = _entity_reach(data)
    rows_by_key = {row["key"]: row for row in (rows if rows is not None
                                               else unknowns(data))}

    def match(ref: object) -> dict | None:
        text = str(ref or "")
        row = rows_by_key.get(text)
        # v202's landmark-derived unknowns have no era and no source to join
        # on — and they do not need one. Family, residences and schools are
        # the three enumeration domains, and an elder can supply all three
        # outright (`landmarks_interaction.WITNESS_CAN_SUPPLY` plus the family
        # constellation itself). So they route to the oldest living witness,
        # which is what the generation ordering already put first.
        if row is not None and str(row.get("kind") or "") in ANCHOR_CREATING_KINDS:
            return dict(people[0]) if people else None
        if text.startswith("entity:"):
            slug = text.split(":", 1)[1]
            for person in people:
                if person["slug"] == slug:
                    return dict(person)
        periods, sources = _ref_reach(text, data, rows_by_key, reach=reach)
        if not periods and not sources:
            return None
        for person in people:
            their_periods, their_sources = reach.get(person["slug"], (set(), set()))
            if (their_periods & periods) or (their_sources & sources):
                return dict(person)
        return None

    return match


def witness_for(ref: object, data: dict, roster: object = None,
                landmarks: object = None) -> dict | None:
    """The living person whose own facts touch `ref`, or ``None``.

    A **witness** is someone living who was there — §6 of the go-deep research
    and the one unknown class better probing will never place: "there are
    mysteries about Grandma I could resolve if I asked my uncle, who is still
    living, today."

    Inferred from stated facts only. `relationship` and `living` are the two
    identity fields the owner already supplied through `entity-verdict`; the
    JOIN is an edge `dependency_index` already walks (shared source, or
    presence in the era whose bounds are missing). No new state
    (design consequence 11). Returns ``{"slug", "name", "relationship"}``.
    """
    people = _living_roster(roster, data)
    if not people:
        return None
    return _witness_matcher(data, people, unknowns(data, landmarks))(ref)


def precision_target_for(ref: object, *, label: object = "", kind: object = None,
                         entity_type: object = None, rung: object = None) -> str:
    """The grade of detail to ask for — the owner's 2026-08-24 emphasis.

    The ladder, in order, and it is deliberately short:

    1. a birthday is asked to the **day** (the one date the whole calendar's
       axis starts from, and overlearned rather than reconstructed);
    2. a school is asked for its **address**, because the name alone unlocks
       nothing and the address unlocks the district, its records, and the
       exact years inside them (§5.3);
    3. a landmark subject is asked at the grade of the RUNG it is short of —
       the specificity ladder already decided what the next answer has to be,
       and a second opinion here would be a duplicate definition;
    4. otherwise the kind decides (`PRECISION_TARGET_BY_KIND`), defaulting to
       `year`.
    """
    text = str(label or "").lower()
    name = str(ref or "")
    if any(word in text for word in _BIRTH_WORDS) or name.endswith(":birth"):
        return "day"
    if any(word in text for word in _SCHOOL_WORDS):
        return "address"
    if rung:
        grade = PRECISION_TARGET_BY_RUNG.get(str(rung))
        if grade:
            return grade
    key = str(kind or "")
    if not key:
        head = name.partition(":")[0]
        key = str(entity_type or head) if head != "entity" else str(entity_type or "place")
    return PRECISION_TARGET_BY_KIND.get(key, "year")


def precision_ask(target: object) -> str:
    """The ONE extra clause the Reading Room adds to a probe.

    It names the grade and what the grade buys, and it never names a date —
    `timeline_interaction.proposes_a_date` is run over every one of these in
    the test suite.
    """
    grade = str(target or "")
    unlocks = PRECISION_UNLOCKS.get(grade, PRECISION_UNLOCKS["year"])
    openers = {
        "day": "If anything in front of you prints the exact day, read that out",
        "month": "The month, if the paper gives it",
        "year": "Whatever the paper says, even just the year",
        "span": "Both ends if you have them — when it started and when it ended",
        "address": "The street address is the piece that matters, not just the name",
        "city": "The town, not just the state",
        "order": "The order they came in, even without any dates",
    }
    return f"{openers.get(grade, openers['year'])} — that gives us {unlocks}."


def witness_question(row: object) -> str:
    """The plain question one dig list carries, addressed to the witness.

    Genealogy's QUESTION SHAPE, oral history's ETHICS (§6.7), and §6.4's rule
    on top of both: ask about **events**, not processes. Discrete, witnessed,
    publicly-marked facts survive thirty years; gradual ones drift, and always
    later.
    """
    if not isinstance(row, dict):
        return ""
    label = str(row.get("label") or "it").strip()
    kind = str(row.get("kind") or "")
    # v202's landmark-derived rows arrive with their OWN exact, subject-named
    # question ("What year was Jackie born?"). It reads correctly addressed to
    # a witness as it stands, and re-wording it here would be the second
    # definition the recurring-defect doctrine forbids.
    probe = row.get("probe")
    if kind in ANCHOR_CREATING_KINDS and isinstance(probe, dict):
        text = str(probe.get("text") or "").strip()
        if text:
            return text
    if kind == "place_span":
        return f"What years did we live at {label}?"
    if kind == "period_bound":
        return f"When did {label} start, and when did it end?"
    if kind == "era_gap":
        between = [str(slug).replace("-", " ") for slug in (row.get("between") or ())]
        if len(between) == 2:
            return f"What happened between {between[0]} and {between[1]}?"
        return "What happened in the years in between?"
    if kind == "date_contradiction":
        return f"Which came first — {label}?"
    return f"What year was {label}?"


#: The two lists that dominate everything else, and the only two that are
#: FINISHABLE (design consequence 17, go-deep.md §5.3/§5.4/§10). They head the
#: first witness's list whenever their landmark domain is still open.
STANDING_DIG_ASKS = (
    {
        "unknown_key": "landmark:residences",
        "question": "Every address we ever lived at, in order — as many as you can.",
        "unlocks": "every moment that happened inside one of them",
        "precision_target": "address",
    },
    {
        "unknown_key": "landmark:schools",
        "question": "Every school I went to, in order, and the town each one was in.",
        "unlocks": "the school-year arithmetic that turns every “I was in third grade” into a year",
        "precision_target": "address",
    },
)


def _open_landmark_domains(data: dict) -> set[str]:
    rows = data.get("landmarks")
    if not isinstance(rows, list):
        return set()
    return {
        str(row.get("domain"))
        for row in rows
        if isinstance(row, dict) and row.get("status") != "complete"
    }


def dig_plan(data: dict, roster: object = None, k: int = DIG_PLAN_SIZE,
             landmarks: object = None) -> dict:
    """The Reading Room's plan: what to ask, at what grade, and who to ask.

    ``{"asks": [...], "witness_lists": {...}, "witness_order": [...],
    "witness_lines": [...], "unreachable": [...], "remaining": int,
    "open_unknowns": int, "k": int}``.

    Built in three moves.

    **0. The anchor-creating quota.** v202 minted two landmark-derived unknown
    kinds (`landmark_subject`, `residence_gap`) that `dependency_index`
    correctly scores at leverage 0 — they place nothing that exists today. But
    each one CREATES AN ANCHOR, and an anchor is the thing every other unknown
    is placed against. Ranking them on the coverage axis would mean simulating
    a graph that does not exist yet, which warning 1 of §8.4 says not to do.
    So they get a QUOTA at the head of the session instead
    (`LANDMARK_ASK_QUOTA`), cheapest rung first, and their `would_place` stays
    honestly at 1. They are also exactly the questions a document in the room
    can answer: "what year was Jackie born" is printed on a birth certificate.

    **1. Greedy over the residual.** The same `_greedy_plan` `keystones` runs,
    extended to `k` picks and ranked on the CONTINUOUS width-sum with the
    count displayed (§8.4, warning 3). This is the session itself: the person
    has paper in front of them, and these are the things that paper can place.

    **2. The precision grade.** Each pick names the grade of detail that
    unlocks the derivations behind it, and says what the grade buys — the
    owner's 2026-08-24 emphasis, and the reason this is a Reading Room and
    not a list of open questions. A school is a name until you have its
    address; then it is a district, and a district keeps records.

    **3. The witness partition, over what is LEFT.** §8.2's real finding is
    that the greedy plan surfaces the unknowns *no anchor in the graph
    reaches at all* — "no amount of asking this person better will place it;
    one question to a relative will." So the residual after `k` asks, plus
    everything unreachable, is offered to the living roster: each unknown that
    has a witness becomes an item on THAT person's dig list, ordered by
    generation, oldest first (§6.1). What remains after that is
    `unreachable` — kept in the ledger, never deleted, because a witness who
    has died does not delete the question.

    The partition runs LAST on purpose. Running it first — taking every
    unknown a living relative shares an era with off the table before the
    session starts — empties the Reading Room of exactly the work it exists
    to do, because a parent shares an era with the whole of a childhood.

    NEVER proposes a date. Every string this function emits is a question or a
    derivation; naming a year and inviting agreement is the one banned move
    (§4.3, Lindsay et al. 2004) and the suite runs
    `timeline_interaction.proposes_a_date` over all of them.
    """
    rows = unknowns(data, landmarks)
    rows_by_key = {row["key"]: row for row in rows}
    open_keys = set(rows_by_key)

    # v204 ruling on v202's two landmark-derived kinds: they are asked on
    # their own merit, not ranked against the coverage objective. See
    # ANCHOR_CREATING_KINDS.
    anchor_creating = [
        row for row in rows
        if str(row.get("kind") or "") in ANCHOR_CREATING_KINDS
    ]
    anchor_creating.sort(
        key=lambda row: (int((row.get("probe") or {}).get("cost") or 99), row["key"]))
    quota = max(min(int(k), LANDMARK_ASK_QUOTA), 0)
    head_rows = anchor_creating[:quota]

    covered: set[str] = set()
    asks: list[dict] = []
    for row in head_rows:
        target = precision_target_for(row["key"], label=row.get("label"),
                                      kind=row.get("kind"), rung=row.get("rung"))
        probe = row.get("probe") or {}
        probe_text = str(probe.get("text") or "").strip()
        covered.add(row["key"])
        asks.append({
            "ref": row["key"],
            "anchor": None,
            "question_id": None,
            "label": str(row.get("label") or row["key"]),
            "probe": probe,
            "ask": f"{probe_text} {precision_ask(target)}".strip(),
            "precision_target": target,
            "precision_unlocks": PRECISION_UNLOCKS.get(target, ""),
            # Honest: it places itself. What it BUYS is a new anchor, and the
            # next session's plan is where that shows up.
            "would_place": 1,
            "gain": 1,
            "width_gain": unknown_width(row),
            "remaining": max(len(open_keys) - len(covered), 0),
            "unknown_keys": [row["key"]],
            "creates_anchor": True,
            "witness": None,
            "anchors": [],
        })

    scored = _scored_anchors(data)
    plan = _greedy_plan(
        scored, max(int(k) - len(asks), 0),
        width=lambda key: unknown_width(rows_by_key.get(key)),
        universe=open_keys - covered,
    )

    for row in plan:
        marginal = set(row["unknown_keys"]) - covered
        covered |= marginal
        entity_type = None
        if row["anchor"].startswith("entity:"):
            entity_type = _entity_type(data, row["anchor"].split(":", 1)[1])
        target = precision_target_for(row["anchor"], label=row["label"],
                                      entity_type=entity_type)
        probe_text = str((row.get("probe") or {}).get("text") or "").strip()
        asks.append({
            "ref": row["anchor"],
            "anchor": row["anchor"],
            "question_id": row["question_id"],
            "label": row["label"],
            "probe": row.get("probe"),
            "ask": f"{probe_text} {precision_ask(target)}".strip(),
            "precision_target": target,
            "precision_unlocks": PRECISION_UNLOCKS.get(target, ""),
            "would_place": row.get("gain", 0),
            "gain": row.get("gain", 0),
            "width_gain": row.get("width_gain", float(row.get("gain", 0))),
            "remaining": max(len(open_keys) - len(covered), 0),
            "unknown_keys": sorted(marginal),
            "creates_anchor": False,
            "witness": None,
            "anchors": row.get("anchors") or [],
        })

    people = _living_roster(roster, data)
    leftover = sorted(open_keys - covered)
    by_witness: dict[str, dict] = {}
    placed_with_a_witness: set[str] = set()
    if people:
        match = _witness_matcher(data, people, rows)
        for key in leftover:
            person = match(key)
            if person is None:
                continue
            placed_with_a_witness.add(key)
            row = rows_by_key.get(key) or {}
            entry = by_witness.setdefault(person["slug"], {
                "slug": person["slug"],
                "name": person["name"],
                "relationship": person["relationship"],
                "questions": [],
                "footer": DIG_LIST_FOOTER,
            })
            target = precision_target_for(key, label=row.get("label"),
                                          kind=row.get("kind"),
                                          rung=row.get("rung"))
            entry["questions"].append({
                "unknown_key": key,
                "question": witness_question(row),
                "unlocks": PRECISION_UNLOCKS.get(target, ""),
                "precision_target": target,
                "width": unknown_width(row),
            })

    order = {person["slug"]: i for i, person in enumerate(people)}
    witness_order = sorted(by_witness, key=lambda slug: (order.get(slug, len(order)), slug))
    for entry in by_witness.values():
        entry["questions"].sort(key=lambda q: (-float(q.get("width") or 1.0),
                                               q["unknown_key"]))
        entry["questions"] = entry["questions"][:WITNESS_LIST_CAP]
    # The two lists that dominate everything else (design consequence 17) head
    # the CLOSEST KIN in the living roster — not whoever happens to hold an
    # item — because "every address" and "every school" are exactly what a
    # parent can produce in one sitting (§5.3, §5.4, §10). They are the only
    # reason a witness list can exist with no unknown behind it.
    standing = [dict(item) for item in STANDING_DIG_ASKS
                if item["unknown_key"].split(":", 1)[1] in _open_landmark_domains(data)]
    if standing and people:
        first = people[0]
        head = by_witness.setdefault(first["slug"], {
            "slug": first["slug"],
            "name": first["name"],
            "relationship": first["relationship"],
            "questions": [],
            "footer": DIG_LIST_FOOTER,
        })
        head["questions"] = standing + head["questions"][:max(
            WITNESS_LIST_CAP - len(standing), 0)]
        if first["slug"] not in witness_order:
            witness_order = sorted(
                by_witness, key=lambda slug: (order.get(slug, len(order)), slug))

    return {
        "k": int(k),
        "asks": asks,
        "witness_lists": {slug: by_witness[slug] for slug in witness_order},
        "witness_order": witness_order,
        "witness_lines": witness_order[:WITNESS_LINE_CAP],
        # Kept, never deleted: an unknown whose only witness has died stays
        # here labelled "no living witness known" by the surface that renders
        # it (plan decision, 2026-08-23).
        "unreachable": [key for key in leftover if key not in placed_with_a_witness],
        "remaining": max(len(open_keys) - len(covered), 0),
        "open_unknowns": len(rows),
    }


def _entity_type(data: dict, slug: str) -> str | None:
    for rows_here in (data.get("entity_lineup") or {}).values():
        for row in rows_here or ():
            if str(row.get("slug") or "") == slug:
                return str(row.get("type") or "") or None
    return None


def render_dig_list(entry: object) -> list[str]:
    """One witness's dig list, as the lines a wiki page carries.

    Short, plain, never a form (§6.6). Every line is marked with
    :data:`DIG_LIST_MARKER` so the wiki harvester can tell a question meant
    for somebody ELSE from one meant for the vault's owner.
    """
    if not isinstance(entry, dict):
        return []
    name = str(entry.get("name") or entry.get("slug") or "").strip()
    lines = []
    for item in (entry.get("questions") or ())[:WITNESS_LIST_CAP]:
        question = str(item.get("question") or "").strip()
        if not question:
            continue
        unlocks = str(item.get("unlocks") or "").strip()
        tail = f" — would give us {unlocks}" if unlocks else ""
        lines.append(f"- **{DIG_LIST_MARKER}, for {name}:** {question}{tail}")
    if lines:
        lines.append(f"- **{DIG_LIST_MARKER}:** {entry.get('footer') or DIG_LIST_FOOTER}")
    return lines


# ---------------------------------------------------------------------------
# The assembled payload.
# ---------------------------------------------------------------------------

def anchor_index(periods: list[dict], entities: list[dict], events: list[dict],
                 birth_date: object = None, landmarks: object = None) -> dict:
    """`{key: {label, date, kind}}` — the person's own dated landmarks.

    This is the life-history calendar as data (Freedman et al. 1988): the
    birthday, the residences with spans, the eras with spans, and the dated
    landmark moments. Every later probe is cheap because this exists, and
    every `anchor`-basis date record resolves through it.
    """
    index: dict[str, dict] = {}
    birth = chrono.from_dict(birth_date) if birth_date is not None else None
    if birth is not None:
        index["birth"] = {"label": "when you were born", "date": birth, "kind": "birth"}
    # v197 (landmarks): the always-present question set's own answers enter
    # FIRST, so a landmark the person stated outright wins over anything the
    # compiler happened to derive from a page. `landmarks` is passed by
    # `timeline_data`; a caller that does not pass it gets the pre-v197 index.
    for key, row in (landmarks or {}).items():
        if isinstance(row, dict) and row.get("date") is not None:
            index.setdefault(key, dict(row))
    for entity in entities:
        if entity.get("type") != "place" or entity.get("date") is None:
            continue
        index[entity["slug"]] = {"label": entity.get("title") or entity["slug"],
                                 "date": entity["date"], "kind": "residence"}
    for period in periods:
        if period.get("date") is None:
            continue
        index[period["slug"]] = {"label": period["name"], "date": period["date"],
                                 "kind": "period"}
    for event in events:
        if event.get("date") is None:
            continue
        key = f"moment-{event['source_short']}-{slugify(event_title(event))[:32]}"
        index.setdefault(key, {"label": event_title(event), "date": event["date"],
                               "kind": "landmark"})
    return index


def timeline_data(evidence: list[dict] | None = None,
                  birth_date: object = None) -> dict:
    # v197 (landmarks): the store is read ONCE here and threaded through, and
    # `birth_date` finally has a source. Before v197 it was a parameter no
    # production caller ever passed, which made `chronology.from_age`
    # unreachable in production (`system/research/landmarks.md` §3.7).
    # Guarded: a landmark problem must never take the timeline down — the same
    # discipline v196 applies to the keystone read.
    try:
        filed_landmarks = load_landmarks()
        landmark_anchors = landmarks_interaction.anchors_from_landmarks(filed_landmarks)
    except Exception:  # noqa: BLE001
        filed_landmarks, landmark_anchors = {}, {}
    if birth_date is None:
        try:
            birth_date = landmark_birth_date(filed_landmarks)
        except Exception:  # noqa: BLE001
            birth_date = None
    periods = load_periods()
    entities = load_entities()
    entity_lineup, unplaced_entities = line_up_entities(entities, periods)
    events = load_events()
    # v195: two passes. The first resolves stated dates only (load_events);
    # the anchor index is then built from whatever IS dated, and the second
    # pass turns "about five" and "before the move" into real intervals.
    anchors = anchor_index(periods, entities, events, birth_date=birth_date,
                           landmarks=landmark_anchors)
    resolve_event_dates(events, anchors=anchors, birth_date=birth_date)
    anchors = anchor_index(periods, entities, events, birth_date=birth_date,
                           landmarks=landmark_anchors)
    placements = load_placements()
    event_lineup, unplaced_events = place_events(events, periods, placements)

    # v110: connector date-evidence corroboration — attaches badges to matched
    # periods/events and returns date_contradiction records (read-only; the
    # connector excavation turns the contradictions into question candidates).
    # `evidence` overrides the on-disk files (excavation passes its fresh
    # assertions so candidates never lag a run). No evidence → nothing
    # attached, nothing renders differently.
    corroboration = tcorr.corroborate(
        periods,
        event_lineup,
        unplaced_events,
        CONNECTORS_STATE_DIR,
        evidence=evidence,
    )

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

    # Date contradictions (v110) are gap entries like any other — the owner
    # resolves them by answering; nothing is auto-applied.
    for contradiction in corroboration["contradictions"]:
        gap = {"kind": "date_contradiction",
               "period": contradiction["period"],
               "message": contradiction["message"],
               "hint": contradiction["hint"]}
        if gap["period"]:
            gaps_by_period.setdefault(gap["period"], []).append(gap)
        else:
            global_gaps.append(gap)

    bands = build_bands(periods, chapters, entity_lineup, event_lineup)
    places_by_chapter = {band["ref"]: band["places"]
                         for band in bands if band["kind"] == "chapter"}
    places_by_period = {band["ref"]: band["places"]
                        for band in bands if band["kind"] == "period"}

    data = {
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
        "corroboration": corroboration,
        # v195 (ADR 0024) — additive, every one of them.
        "anchors": anchors,
        "bands": bands,
        "places_by_chapter": places_by_chapter,
        "places_by_period": places_by_period,
        "counts": {
            "periods": len(periods),
            "entities_placed": sum(len(v) for v in entity_lineup.values()),
            "entities_unplaced": len(unplaced_entities),
            "events_placed": sum(len(v) for v in event_lineup.values()),
            "events_unplaced": len(unplaced_events),
            "events_dated": sum(1 for rows in event_lineup.values()
                                for event in rows if event.get("date") is not None),
        },
    }
    # v196: concrete unknowns, leverage-ordered and capped for a page; the
    # aggregate counts live on the ledger where they belong.
    all_unknowns = unknowns(data, landmarks=filed_landmarks)
    data["unknown_ledger"] = unknown_ledger(data)
    data["unknowns"] = offered_unknowns(all_unknowns, dependency_index(data))
    data["keystones"] = keystones(data)
    data["counts"]["unknowns"] = len(all_unknowns)
    data["counts"]["unknowns_offered"] = len(data["unknowns"])
    # v197 (landmarks, owner rulings 2 and 4): every landmark domain with its
    # status and its next question, so a host can render ONLY the open ones —
    # and the gap a landmark set is the only thing that can reveal: a place
    # the person told us about that has nothing in it.
    try:
        data["landmarks"] = list(landmark_rows_for(data, landmarks=filed_landmarks))
        data["place_no_stories"] = list(
            landmarks_interaction.places_without_stories(
                filed_landmarks, event_places=_event_place_labels(data)
            )
        )
        # v202 (family-landmark §D): the living family members, as witnesses
        # for the ask-the-living hooks. v200's `place_no_stories.witnesses`
        # (who was in THAT house) is a narrower, better claim and is untouched.
        data["witnesses"] = list(
            landmarks_interaction.witness_candidates(filed_landmarks)
        )
    except Exception:  # noqa: BLE001
        data["landmarks"], data["place_no_stories"] = [], []
        data["witnesses"] = []
    data["counts"]["landmarks_open"] = sum(
        1 for row in data["landmarks"] if row.get("status") != "complete"
    )
    # v204 (the Reading Room, ADR 0025): additive, and derived — the plan and
    # the per-witness lists are recomputed from the graph every read, exactly
    # like `keystones`. There is no dig state and no homework inbox
    # (design consequence 13). Guarded the same way the landmark block is: a
    # broken roster must never take the whole timeline down.
    try:
        data["reading_room"] = dig_plan(data, landmarks=filed_landmarks)
    except Exception:  # noqa: BLE001
        data["reading_room"] = {
            "k": DIG_PLAN_SIZE, "asks": [], "witness_lists": {},
            "witness_order": [], "witness_lines": [], "unreachable": [],
            "remaining": 0, "open_unknowns": 0,
        }
    data["counts"]["reading_room_asks"] = len(data["reading_room"]["asks"])
    return data


def landmark_rows_for(data: dict, *, landmarks: object = None) -> tuple[dict, ...]:
    """`landmarks_interaction.landmark_rows` with the keystone star applied.

    Owner ruling 5: the ★ moves with the leverage. `keystones()` ranks
    *derived* anchors — `period:<slug>`, `event:…`, `entity:<slug>` — so the
    star is placed by mapping the current keystone back to the landmark domain
    whose next answer would supply it:

    * **No birth date filed → ★ `birth`.** Unarguable and independent of the
      keystones: with no axis `chronology.from_age` cannot fire at all, so a
      birthday is the highest-leverage single answer this vault can receive.
    * **A `period:` or a place `entity:` keystone → ★ `residences`.** Both are
      answered by the residence chain — an era's bounds and a place's span are
      the same question in the sourced playbook ("where were you living
      then?", rung 2).
    * Otherwise no star. The set is never starred for the sake of it.
    """
    filed = landmarks if isinstance(landmarks, dict) else load_landmarks()
    if landmark_birth_date(filed) is None:
        return landmarks_interaction.landmark_rows(filed,
                                                   keystone_domains=("birth",))
    place_slugs = {
        str(row.get("slug"))
        for rows in (data.get("entity_lineup") or {}).values()
        for row in rows or ()
        if isinstance(row, dict) and row.get("type") == "place"
    }
    starred: set[str] = set()
    for row in data.get("keystones") or ():
        if not isinstance(row, dict):
            continue
        anchor = str(row.get("anchor") or "")
        if anchor.startswith("period:"):
            starred.add("residences")
        elif anchor.startswith("entity:") and anchor.split(":", 1)[1] in place_slugs:
            starred.add("residences")
    return landmarks_interaction.landmark_rows(filed, keystone_domains=starred)


def _event_place_labels(data: dict) -> tuple[str, ...]:
    """Every place label a placed moment already sits in — the set a
    `place_no_stories` gap is checked against."""
    labels: set[str] = set()
    for band in data.get("bands") or ():
        for place in (band or {}).get("places") or ():
            title = str((place or {}).get("title") or "").strip()
            if title:
                labels.add(title)
    for rows in (data.get("entity_lineup") or {}).values():
        for entity in rows or ():
            if isinstance(entity, dict) and entity.get("type") == "place":
                title = str(entity.get("title") or "").strip()
                if title:
                    labels.add(title)
    return tuple(sorted(labels))
