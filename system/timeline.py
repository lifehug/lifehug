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
from datetime import datetime, timezone
from pathlib import Path

_SYSTEM_DIR = Path(__file__).resolve().parent
if str(_SYSTEM_DIR) not in sys.path:
    sys.path.insert(0, str(_SYSTEM_DIR))

import chronology as chrono  # noqa: E402
import classify_story  # noqa: E402
import cross_dating  # noqa: E402
import landmark_projection  # noqa: E402
import landmarks_interaction  # noqa: E402
import temporal_projection  # noqa: E402
import temporal_publication  # noqa: E402
import temporal_work_items as twi  # noqa: E402
import timeline_corroboration as tcorr  # noqa: E402

from lifehug_core import (  # noqa: E402
    CLASSIFICATIONS_DIR,
    CONNECTORS_STATE_DIR,
    ENTITY_ROSTERS_DIR,
    LANDMARKS_FILE,
    MANUAL_SOURCES_DIR,
    REPO_DIR,
    STATE_DIR,
    TIMELINE_PLACEMENTS_FILE,
    WIKI_DIR,
    now_utc,
    read_json,
    read_learning_failures,
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
# Legacy period identity: the ONE alias map onto the age frames (eras §3.5).
# ---------------------------------------------------------------------------

#: The prefixes a legacy period reference is written with across the product —
#: `?play=` keys, the per-vault zoom keys, a session plan's
#: `unknowns[].period` / `moments[].period`, and pins. One tuple, so a caller
#: never has to know which surface minted the string it is holding.
LEGACY_PERIOD_PREFIXES = ("period", "tl", "band")


def legacy_period_ref(ref: object) -> str | None:
    """A legacy period slug or prefixed reference → an age frame node id.

    `period:my-20s`, `tl:my-20s`, `band:my-20s`, the bare slug `my-20s` and the
    roster's own name `My 20s` are five spellings of one thing, and the thing
    they name is now a calculated node: `age:self:20s`. This is the single map
    (design §3.5) the platform re-exports, so a deep link, a stored zoom key, a
    session plan and a pin all resolve identically or all fail identically.

    ``None`` for anything that is not an age band. `College` and `the Mission`
    are NAMED ERAS — E3's opaque identities — and guessing one of those here
    would be precisely the wrong join ADR 0026 ranks above a miss.
    """
    text = " ".join(str(ref or "").split())
    if not text:
        return None
    prefix, sep, rest = text.partition(":")
    if sep and prefix.strip().lower() in LEGACY_PERIOD_PREFIXES:
        text = rest
    band = cross_dating.age_frame_band_of(text)
    if band is None:
        return None
    return temporal_projection.age_frame_node_id(band)


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
#: v218: `chronology.YEAR_RE`, the one year pattern (was an identical copy).
_CHAPTER_YEAR_RE = chrono.YEAR_RE


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
    import classify_story  # noqa: PLC0415 — avoids an import cycle at load

    out: list[dict] = []
    # v237: the ONE reader gate. A classification marked stale (a correction
    # was filed against its source) leaves the Timeline — and, through
    # wiki_compile's export, the wiki — the moment it is marked. The module's
    # OWN root is passed so `vault_roots()` rebinds keep working.
    for path, data in classify_story.current_classification_files(CLASSIFICATIONS_DIR):
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


# Era keywords per period slug, for placing an UNDATED event whose
# classification names an era ("early childhood", "high school", "my 20s"...).
# This is rung 3 — the last resort, tried only when the event carries no date
# and names no active era by name (eras design §5.1). `my-20s`'s `"mission"`
# row and `my-40s`'s `"present"`/`"today"`/`"current"` rows are DELETED (O-E2):
# they are era NAMES and deixis, not era language, and they were two of the
# founder's own mis-placements (design §1 item 1).
_PERIOD_KEYWORDS = {
    "childhood": ("childhood", "child", "kid", "elementary", "young boy", "young girl"),
    "my-teens": ("teen", "middle school", "junior high", "adolescen"),
    "high-school": ("high school",),
    "college": ("college", "university", "school of business", "student"),
    "my-20s": ("20s", "twenties", "newlywed", "early adult"),
    "my-30s": ("30s", "thirties"),
    "my-40s": ("40s", "forties", "midlife"),
}

#: `learned_era_vocabulary` / `_era_tokens` / `_ERA_STOPWORDS` and the
# source-membership rung (`event["source"] in period["sources"]`) are GONE
# (eras design O-E2, §1 items 1-2). Both were a membership rule with no
# stated fact behind it: an era silently learned the vocabulary of whatever
# the classifier said about ANY source cited on its page, and a moment
# entered an era because its SOURCE was cited there, whether or not the
# moment's own words ever named that era. `tests/test_eras_e2.py` guards
# against either name reappearing anywhere in `system/`.


# ---------------------------------------------------------------------------
# Manual placements (v102) — the owner's curation layer.
#
# The timeline is a validation surface; when the owner drags an unplaced
# moment into a period (or corrects a wrong one), that decision persists here
# and wins over every heuristic. Raw sources stay immutable — a placement is
# an overlay keyed by CONTENT (sha of source + description).
#
# v253 (lifehug#276): that content key is not stable, and this comment used to
# end by calling the consequence correct — "a reclassification that rewrites
# the description automatically orphans the placement (surfaced as
# `stale_placements`, never silently misapplied)". Rewriting descriptions is
# the classifier's ordinary weekly job, so that sentence described a pin
# quietly dying every time the loop did its work. `resolve_placements` now
# carries a THIRD rung that re-keys such a pin to the one live moment its
# source mints, and `rekey_orphaned_placements` persists that repair.
# "Never silently misapplied" survives intact: several candidates, or none,
# and the pin stays orphaned under a named diagnostic.
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


#: The longest description a placement carries — ONE definition, read by
#: `timeline_interaction.place_invocation` (which clamps every host's
#: description to it) and by `legacy_title_key` below (which must reproduce the
#: exact bytes a pre-v215 mint hashed). A live host clamping on its own is what
#: made this a two-recipe identity in the first place.
PLACEMENT_DESCRIPTION_MAX = 200

#: The longest description the placement's DURABLE BODY quotes back. Prose,
#: not identity — `PLACEMENT_DESCRIPTION_MAX` above is the identity clamp and
#: the two must never be conflated: shortening this one changes a sentence,
#: shortening that one changes a key.
PLACEMENT_ASSERTION_DESCRIPTION_MAX = 120


def placement_assertion(description: str, *, date: object = None,
                        when_hint: str = "") -> str:
    """The durable body of a placement correction: the DATE DECISION, only.

    ONE definition, because this text is durable twice over. It is the
    immutable payload of a vault source record (`--role placement`, v237/O-C2),
    and `classify_story.corrections_for` hands it back to the next
    classification prompt under the heading *"LATER CORRECTIONS
    (authoritative — these OVERRIDE the story text above)"*. Whatever this
    sentence says, the vault keeps forever and the model is told to obey.

    So it says the date and nothing else. Until v251 it opened
    ``"“…” happened during My 40s, May 2022"`` — one sentence carrying both a
    date and an ERA, which is the sentence shape of the 2026-08-25 defect one
    era to the right. Two authorities forbid it:

    * **v244 / O-C2** — a placement is a date DECISION about a moment the
      person accepts, not an assertion about the era it lands in.
    * **the Eras design §5.1** — the period is DERIVED from the date by frame
      arithmetic. ``My 40s`` is not something anybody said; it is what the
      arithmetic computed from ``May 2022``. Asserting the derived half back
      as fact gives it the date's own authority, and a later correction to the
      arithmetic cannot reach it: prose inside an immutable source is not a
      claim anything can supersede.

    The era is not lost, because it was never information this record held:
    it lives as ``period`` on the row in ``state/timeline_placements.json``,
    which is where rung 0 reads it (see `save_placement`).

    `date` is a `chronology.DateRecord` or its serialized form; `when_hint` is
    the person's own words for when, which stand on their own when no date
    parsed. With neither, the body states the placement and claims no time at
    all — the honest reading of a period-only pin from the viewer's form.
    """
    quoted = f"“{str(description)[:PLACEMENT_ASSERTION_DESCRIPTION_MAX]}”"
    record = date if isinstance(date, chrono.DateRecord) else (
        chrono.from_dict(date) if date is not None else None)
    clauses: list[str] = []
    stated = chrono.display_date(record, with_basis=False) if record is not None else ""
    if stated:
        anchors = tuple(getattr(record, "anchors", ()) or ())
        clauses.append(f"{stated} (anchored on {', '.join(anchors)})"
                       if anchors else stated)
    hint = str(when_hint or "").strip()
    # A host that derives its `--when-hint` FROM the date says the date twice:
    # `timeline_interaction.place_invocation` sets the hint to this very
    # `display_date`. The era used to stand between the two copies; without it
    # the duplication is the whole sentence.
    if hint and hint != stated:
        clauses.append(hint)
    if not clauses:
        return f"{quoted} — I placed this moment on my timeline; I stated no date."
    return f"{quoted} happened {', '.join(clauses)}"


def placement_key(event: dict) -> str:
    """The identity of one placement: the event's SOURCE and its DESCRIPTION.

    This is the mint AND the join — `resolve_placements` below is the only
    thing that pairs a stored placement with a live event, and it computes the
    event side with this function. A host that mints a key from anything else
    (v213 minted from the unknown's LABEL, which since v195 is the event's
    TITLE) files a record that lands in `stale_placements` and renders
    nowhere: exit 0, and the date the person named is gone (lifehug#228).
    """
    import hashlib  # noqa: PLC0415
    payload = f"{event.get('source', '')}\n{event.get('description', '')}"
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()[:12]


def legacy_title_key(event: dict) -> str:
    """The key a pre-v215 conversational mint would have produced for `event`.

    The one asymmetric recipe that ever shipped: `moment_unknown` names the row
    by the event's TITLE, `conversation_delivery._file_placement` passed that
    label as the description, and `cmd_timeline_place` hashed it against a join
    expecting the description. `""` when the event has no title, or when the
    title IS the description (nothing to repair — the two recipes agree).

    This is frozen history, not a second identity: it exists so
    `resolve_placements` can re-join the records that recipe orphaned, and
    nothing mints with it.
    """
    title = str((event or {}).get("title") or "").strip()[:PLACEMENT_DESCRIPTION_MAX]
    if not title:
        return ""
    legacy = placement_key({"source": (event or {}).get("source", ""),
                            "description": title})
    return "" if legacy == placement_key(event) else legacy


#: How a stored placement found its live moment — which rung of the join
#: fired. `resolve_placements_with_rung` reports it and
#: `rekey_orphaned_placements` reads it, because exactly one rung's repair is
#: DURABLE and the other two must never touch the store.
PLACEMENT_JOIN_EXACT = "exact"
PLACEMENT_JOIN_LEGACY_TITLE = "legacy_title"
PLACEMENT_JOIN_SOURCE_REKEY = "source_rekey"

#: The one named diagnostic for a pin the source rung could not repair —
#: either its source mints no live moment at all, or it mints SEVERAL and
#: picking one would file the person's date onto the wrong moment. Named, and
#: carried on `timeline_data()`, because the alternative is a silent zero.
PLACEMENT_ORPHANED_AMBIGUOUS = "placement_orphaned_ambiguous"


def _resolve_placements(placements: dict | None, events: list[dict],
                        ) -> tuple[list[tuple[dict, str, str]], list[dict]]:
    """`([(row, key, rung), ...], [diagnostic, ...])` — the whole join, once.

    Private because there is exactly ONE join and every public reader below is
    a projection of this: `resolve_placements` drops the rung,
    `resolve_placements_with_rung` keeps it, `placement_orphan_diagnostics`
    takes the second half.
    """
    rows = ((placements or {}).get("placements") or [])
    if not rows:
        return [], []
    live: dict[str, dict] = {}
    for event in events:
        live.setdefault(placement_key(event), event)
    legacy: dict[str, str | None] = {}
    for key, event in live.items():
        alias = legacy_title_key(event)
        if not alias or alias in live:
            continue
        legacy[alias] = None if alias in legacy and legacy[alias] != key else key
    # Rung 3's candidate set: the live moments each SOURCE mints. Two moments
    # of one source is not a tie to break, it is a repair that must not run.
    by_source: dict[str, list[str]] = {}
    for key, event in live.items():
        source = str(event.get("source") or "").strip()
        if source:
            by_source.setdefault(source, []).append(key)
    resolved: list[tuple[dict, str, str]] = []
    diagnostics: list[dict] = []
    taken: set[str] = set()
    for row in rows:
        key = str(row.get("key") or "")
        target, rung = "", ""
        if key in live:
            target, rung = key, PLACEMENT_JOIN_EXACT
        elif legacy.get(key):
            target, rung = str(legacy[key]), PLACEMENT_JOIN_LEGACY_TITLE
        else:
            source = str(row.get("source") or "").strip()
            candidates = by_source.get(source, []) if source else []
            if len(candidates) == 1:
                target, rung = candidates[0], PLACEMENT_JOIN_SOURCE_REKEY
            else:
                diagnostics.append({
                    "diagnostic": PLACEMENT_ORPHANED_AMBIGUOUS,
                    "key": key, "source": source,
                    "description": str(row.get("description") or ""),
                    "candidates": list(candidates),
                })
        if not target or target in taken:
            resolved.append((row, "", ""))
            continue
        taken.add(target)
        resolved.append((row, target, rung))
    return resolved, diagnostics


def resolve_placements_with_rung(placements: dict | None,
                                 events: list[dict]) -> list[tuple[dict, str, str]]:
    """`resolve_placements` plus the rung that joined each row (`""` when the
    row joined nothing) — the only reader that needs the rung is the durable
    re-key, which must persist rung 3's repair and NEVER rung 2's."""
    return _resolve_placements(placements, events)[0]


def placement_orphan_diagnostics(placements: dict | None,
                                 events: list[dict]) -> list[dict]:
    """One `placement_orphaned_ambiguous` record per pin the source rung
    refused to repair. Fail LOUD: a pin that cannot be re-keyed says so with a
    name, a source and the candidate keys it declined to choose between."""
    return _resolve_placements(placements, events)[1]


def resolve_placements(placements: dict | None,
                       events: list[dict]) -> list[tuple[dict, str]]:
    """Every stored placement paired with the live event key it joins, in store
    order — `""` when it joins nothing.

    ONE join, read by `place_events` (which pins the moment), `timeline_data`
    (which counts what is still orphaned) and `retire_redundant_placements`.

    Three ways a row resolves:

    1. its stored key IS a live event's `placement_key` — every placement the
       viewer and the CLI ever filed;
    2. its stored key is the pre-v215 `legacy_title_key` of exactly one live
       event — the deterministic REPAIR for the one asymmetric recipe that ever
       shipped, so a date captured in conversation between v213 and v215 joins
       on the next compile with no migration, no state file and no model call;
       and
    3. v253 (lifehug#276): its stored key joins nothing AND the row's own
       `source` mints EXACTLY ONE live moment — the reclassification repair.

    Rung 3 exists because the identity is content-addressed and the content is
    not stable. `placement_key` hashes the moment's DESCRIPTION, and rewriting
    descriptions is the classifier's ordinary weekly job, so every
    reclassification orphaned the pin of every moment it touched: the person
    named a date, the date is on disk, and the moment renders undated. The
    comment this module has carried since v102 called that orphaning correct
    ("never silently misapplied") — right instinct, wrong conclusion. The pin
    carries its own `source`, and a source that mints exactly one live moment
    is not a guess.

    It IS a guess the moment the source mints two, so it does not run: rung 3
    refuses zero candidates and refuses several, emitting
    `PLACEMENT_ORPHANED_AMBIGUOUS` instead — filing the person's date onto the
    wrong moment is worse than leaving it stranded, which is the rule rung 2
    has always followed. The one trade-off it does accept, stated plainly: if a
    source's only surviving moment is not the moment the pin was about (its own
    moment was deleted, not rewritten), the pin lands on the survivor. That is
    the price of a content-addressed identity, and the end of it is an opaque
    minted placement id, not a cleverer heuristic.

    Rungs 1 and 2 keep the row's stored `key` — a repaired pin renders, retires
    and unplaces under the identity the store actually holds. Rung 3 does not:
    its repair is persisted by `rekey_orphaned_placements` on the pin-
    maintenance pass, with `rekeyed_from` provenance, because a repair that
    lives only in memory proves the substrate is right and says nothing about
    the file the product reads. The read heals immediately; the store heals on
    the next pass.

    Ambiguity never guesses at any rung — two live events sharing one legacy
    key resolve neither, and a second row claiming a key some earlier row
    already took stays orphaned.
    """
    return [(row, key) for row, key, _ in _resolve_placements(placements, events)[0]]


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

    eras O-E2 (design §5.1, rung 0): a pin whose OWN date cannot be inside
    the age frame its `period` maps to is refused at filing —
    `ValueError("placement_outside_frame: ...")` — never stored silently
    contradicting the arithmetic the fold trusts completely. `period` is
    checked against `cross_dating.age_frame_band_of`; a period that is not an
    age frame (a named era) is unaffected — that containment is E3's.
    """
    parsed = chrono.from_dict(date) if date is not None else None
    if parsed is not None:
        band = cross_dating.age_frame_band_of(period)
        if band is not None:
            birth = None
            with contextlib.suppress(Exception):
                birth = landmark_birth_date()
            if birth is not None:
                frames = ()
                with contextlib.suppress(Exception):
                    frames = cross_dating.age_frames(birth, as_of=now_utc())
                frame = next((f for f in frames if f.band == band), None)
                if frame is not None and not cross_dating.frames_touching((frame,), parsed):
                    raise ValueError(
                        f"placement_outside_frame: {description!r} ({date!r}) "
                        f"does not fall inside {period}'s age frame"
                    )
    data = load_placements()
    data["placements"] = [p for p in data["placements"] if p.get("key") != key]
    record = {"key": key, "source": source, "description": description,
              "period": period, "when_hint": when_hint, "note": note,
              "correction": correction, "placed_at": now_utc()}
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


#: The directory names the landmark store can sit under, which
#: :func:`_projection_vault_root` strips to recover the vault root.
#:
#: Since v260 (Timeline Fix 01) the contract names ONE path in both layouts —
#: the store is always `<vault>/state/landmarks.json`. `system` stays in this
#: tuple on purpose: it is not a route, it is the INVERSE of one, and a vault
#: that still carries the pre-v260 embedded copy (until `update.py`'s v260
#: migration retires it) must still resolve to its own root rather than to its
#: `system/` directory. Removing it would make an old vault's root wrong.
LANDMARK_STORE_PARENTS = ("state", "system")


def _projection_vault_root():
    """The vault the landmark store belongs to, derived FROM the store's path.

    ONE definition of "which vault", never two. The obvious implementation is
    `lifehug_core.REPO_DIR` — the process binding — and it is wrong in a way
    that is silent and destructive: `LANDMARKS_STORE` is the seam every caller
    and every test rebinds to point at another vault, and it is deliberately
    NOT in `VAULT_ROOT_NAMES`, so `vault_roots()` does not rebind it either.
    A root read from the process binding while the store is read from the
    rebound path puts the drawing in one vault and its evidence in another —
    the same half-and-half split the `vault_roots()` comment above was written
    to end, and it writes real files into whichever vault the process happened
    to import from.

    Deriving the root from the store's own path makes that split impossible to
    express: rebind the store and the substrate follows it, every time.
    """
    store = Path(str(LANDMARKS_STORE))
    parent = store.parent
    if parent.name in LANDMARK_STORE_PARENTS:
        return parent.parent
    return parent


def redraw_landmarks() -> dict:
    """Redraw the landmark store from the claim substrate. THE ONE WRITER.

    Owner amendment 1 (2026-08-26), wave B item B3. Every other path that used
    to write this file now records evidence and calls this, and
    `tests/test_landmark_projection.py::test_only_one_writer_of_the_landmark_store`
    walks the AST of every module in `system/` to keep the count at one. A
    second writer is not untidiness: it is the dual truth the flip removed,
    coming back.

    The store's PATH stays here, in `LANDMARKS_STORE`, because that is where
    the embedded/external layout difference is already resolved
    (`lifehug_core._data("landmarks")`). The projector derives the file's
    CONTENT and never learns where it lands.
    """
    root = _projection_vault_root()
    drawing = landmark_projection.redraw(root)
    write_json(LANDMARKS_STORE, drawing)
    publish_calculated_timeline(root)
    return drawing


def publish_calculated_timeline(vault_root: object = None) -> dict:
    """Publish wave D's calculated timeline over the same substrate (v231).

    ONE COMPILE, ONE DRAWING, ONE TRUTH. `redraw_landmarks` above already
    stands at the moment this vault's claim substrate becomes current; the
    calculated projection is derived from that same substrate, so deriving it
    anywhere else would be a second answer to "when is the truth current?" —
    the dual truth the flip (wave B item B3) removed. There is deliberately no
    second trigger: `system/update.py`'s versioned seat publishes ONCE at
    upgrade so an existing vault does not wait for its next landmark write, and
    every write after that comes through here.

    The roster is host context, not substrate, and it is read from the process
    binding — so it is supplied ONLY when the projection's vault IS the
    process's vault. `_projection_vault_root`'s docstring names this hazard
    exactly: a root read from one place and a store read from another puts the
    drawing in one vault and its evidence in another. A rebound store (every
    test, and any host holding two vaults) therefore derives from the substrate
    alone, which is honest — unresolved mentions mint `identity_uncertain` work
    items rather than borrowing another vault's roster.

    A publication failure RAISES. The projection is a materialized view and its
    repair path is "delete the files and publish again" (plan §7), which only
    works if somebody learns it is broken; a queue that silently stops
    regenerating is the failure this whole wave exists to end. Nothing is lost
    by raising here: the landmark drawing is already written, and the
    publication is atomic per file.
    """
    root = Path(str(vault_root)) if vault_root is not None else _projection_vault_root()
    roster: object = ()
    if root == REPO_DIR:
        try:
            import entity_roster as _entity_roster  # noqa: PLC0415

            roster = _entity_roster.load_roster("person")
        except Exception:  # noqa: BLE001 — a roster problem is "no roster"
            roster = ()
    return temporal_publication.publish(root, roster_snapshot=roster)


def flip_landmarks_if_needed() -> dict | None:
    """Convert a pre-flip vault's entries into claims, once. ``None`` if done.

    Detection is "entries exist and no legacy-import receipt does", which is
    idempotent by CONTENT rather than by a marker file — the house pattern
    (`update.migrate_vault_to_v120`). Deliberately not keyed on a receipt id:
    a receipt id binds to a source revision, redrawing changes the file's
    bytes, and a revision-bound check would re-import the whole vault on the
    second call. See `landmark_projection.legacy_import_done`.
    """
    root = _projection_vault_root()
    summary = landmark_projection.flip_if_needed(root, load_landmarks())
    if summary is None:
        return None
    redraw_landmarks()
    return summary


def save_landmark(domain: str, record: object) -> dict:
    """Add or replace ONE landmark entry, keyed by its identity in a domain.

    The signature, the return value and the MEANING are v214's. What changed in
    v224 is where the answer goes: the record is promoted to a durable vault
    source and its temporal assertions are filed as claims with a receipt, and
    then the store is REDRAWN from the substrate. Nothing writes an entry into
    the file any more.

    Replacement is by identity because the ladder revisits the same subject —
    a city today, an address next week, a span after that, each pass adding
    rungs to the SAME entry rather than making a second one. HOW two records
    combine is still `landmarks_interaction.merge_landmark_entry`, and it is
    still the only definition; it simply runs in
    `landmark_projection.project_landmark_entries` at DRAW time instead of
    here at write time. That is why the flip is invisible: the same function
    folds the same records in the same order and gets the same entry.

    The one cross-entry rule (`landmarks_interaction.entry_superseded_by` — a
    none retires its domain, a substantive answer clears a standing terminal,
    a clean record retires the collapsed aggregate) is now expressed as a
    durable CORRECTION rather than as an entry quietly not copied forward. The
    retired entry keeps its evidence and gains a record of why it stopped
    standing.
    """
    if not isinstance(record, dict):
        raise ValueError("a landmark record must be an object")
    key = str(domain or "").strip()
    if not key:
        raise ValueError("a landmark needs a domain")
    try:
        row = landmarks_interaction.domain_row(key)
    except landmarks_interaction.LandmarkInteractionError:
        # A domain the question set does not declare still files, keyed on
        # the identity fields alone — degrade, never refuse a write.
        row = None

    root = _projection_vault_root()
    # A vault that has not been converted yet is converted before its first
    # post-upgrade write, so a record can never land in a half-flipped vault.
    landmark_projection.flip_if_needed(root, load_landmarks())

    entry_key = landmarks_interaction.landmark_entry_key(record, row)
    for existing in load_landmarks().get(key) or ():
        if landmarks_interaction.landmark_entry_key(existing, row) == entry_key:
            continue
        if landmarks_interaction.entry_superseded_by(existing, record, row):
            landmark_projection.retire_entry(
                root,
                domain=key,
                entry_key=landmarks_interaction.landmark_entry_key(existing, row),
                reason=(
                    f"superseded by a later {key} answer "
                    "(landmarks_interaction.entry_superseded_by)"
                ),
            )

    filed = dict(record)
    filed.setdefault("domain", key)
    landmark_projection.file_landmark_record(
        root,
        key,
        filed,
        ordinal=landmark_projection.next_ordinal(root),
        extractor_version=landmark_projection.LIVE_EXTRACTOR,
    )

    drawn = redraw_landmarks()
    # The interval-aware key (E-L2b, design §3.2): one identity may now be
    # SEVERAL entries — two stays at one address — so the entry this write
    # landed in is the one that shares the record's identity AND its stretch.
    # Matching on identity alone would return the person's FIRST stay to a
    # caller that just filed their second.
    drawn_entries = list((drawn.get("domains") or {}).get(key) or ())
    same_key = [entry for entry in drawn_entries
                if landmarks_interaction.landmark_entry_key(entry, row) == entry_key]
    for entry in same_key:
        if landmarks_interaction.same_landmark_stay(entry, record, row):
            return entry
    if same_key:
        return same_key[0]
    return landmarks_interaction.merge_landmark_entry(None, record)


def save_landmarks(domain: str, records: object) -> list[dict]:
    """File a whole recorder outcome — ONE entry per record (v214).

    The batch writer named by ADR 0028's many-records amendment: one answer
    can carry four children or twelve jobs, and every one of them is its own
    entry under the domain. There is no aggregate form and no second filing
    path — this is :func:`save_landmark` in order, which is exactly what a
    host looping `landmarks_interaction.landmark_invocations` does through
    the CLI.
    """
    rows = records if isinstance(records, (list, tuple)) else [records]
    saved = []
    for record in rows:
        if isinstance(record, dict) and not record.get("skipped"):
            saved.append(save_landmark(domain, record))
    return saved


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


def _era_label_match(haystack: str, periods: list[dict], eras: object = ()) -> str | None:
    """The most specific ACTIVE era label/alias the event's own language names.

    Whole-word only (the same conservatism as `cross_dating._names`), so
    "college" inside "collegial" never matches, and the LONGEST matching label
    wins when more than one does ("high school" over an alias that is merely
    "school"). `eras` is O-E3's forward seam for the named-era container
    records that do not exist yet; `periods` (the legacy roster) is what
    actually carries labels today, and matching is identical either way.
    """
    best_slug, best_len = None, 0

    def consider(label: object, slug: object) -> None:
        nonlocal best_slug, best_len
        text = str(label or "").strip()
        slug_text = str(slug or "").strip()
        if len(text) < 3 or not slug_text:
            return
        if re.search(rf"(?<!\w){re.escape(text.lower())}(?!\w)", haystack):
            if len(text) > best_len:
                best_slug, best_len = slug_text, len(text)

    for period in periods:
        consider(period.get("name"), period.get("slug"))
        for alias in period.get("aliases") or ():
            consider(alias, period.get("slug"))
    for era in eras or ():
        if not isinstance(era, dict):
            continue
        consider(era.get("name"), era.get("slug"))
        for alias in era.get("aliases") or ():
            consider(alias, era.get("slug"))
    return best_slug


def heuristic_slot(event: dict, periods: list[dict], *, frames: object = (),
                   eras: object = (), anchors: dict | None = None,
                   birth_date: object = None) -> tuple[str | None, dict]:
    """Where the system would place this event WITHOUT a manual pin, and WHY
    (eras design §5.1). Four rungs, and the two removed mechanisms — source
    membership and the learned era-vocabulary — do not come back:

      1. DATED — `cross_dating.frame_for` reads the event's own date against
         the age frames; the roster slug that aliases onto the winning band
         places it. ONE definition, shared with the fold (`O-E2f` parity).
      2. NAMED-ERA MEMBERSHIP — the event's OWN language (`when_hint`, then
         the classifier's `eras`) names an active era label or alias,
         whole-word, with the subject veto.
      3. UNDATED — an era-text keyword match (`_PERIOD_KEYWORDS`), same veto.
      4. unplaced.

    `anchors` / `birth_date` are accepted for the caller's convenience (a
    future per-subject age-arithmetic join reads them) and are not consulted
    by this function today; the subject veto below already stops an ownerless
    age statement from seeding a placement off the owner's birthday.

    Returns `(slug | None, placement_reason)`. `placement_reason` always
    carries `rung` (`None` when nothing fired) and `evidence`; `frame_by` /
    `era_by` / `subject_check` appear only where they applied.
    """
    del anchors, birth_date  # accepted, not yet consulted — see docstring
    text = str(event.get("when_hint") or "")
    subject_blocked = cross_dating.age_statement_is_third_person(text)

    # Rung 1 — dated: frame arithmetic decides the band. Never source
    # membership, never vocabulary.
    date = event.get("date")
    if date is not None and frames:
        band = cross_dating.frame_for(frames, date)
        if band is not None:
            live_slugs = {p["slug"] for p in periods}
            slug = next(
                (s for s in cross_dating.age_frame_legacy_slugs().get(band, ())
                 if s in live_slugs),
                None,
            )
            if slug is not None:
                return slug, {"rung": 1, "evidence": "date", "frame_by": "date"}

    haystack = " ".join([text, " ".join(event.get("eras") or ())]).lower()

    # Rung 2 — named-era membership: the event's OWN language, with the veto.
    if not subject_blocked:
        slug = _era_label_match(haystack, periods, eras)
        if slug is not None:
            return slug, {"rung": 2, "evidence": "era_language",
                          "era_by": "event_language"}

    # Rung 3 — undated era text, same veto.
    if not subject_blocked:
        slug = _keyword_slot(haystack, periods)
        if slug is not None:
            return slug, {"rung": 3, "evidence": "era_text", "era_by": "era_text"}

    reason = {"rung": None, "evidence": None}
    if subject_blocked:
        reason["subject_check"] = "third_person_age"
    return None, reason


def _placement_provenance_summary(reason: dict) -> str:
    """One sentence for the expanded card / eye pane (eras design §5.1) naming
    WHY a row landed where it did — every legacy row carries one, placed or
    not."""
    rung = reason.get("rung")
    if rung == 0:
        return "You placed this moment yourself."
    if rung == 1:
        return "Placed by its own date, against your age frames."
    if rung == 2:
        return "Placed because the moment names this era in its own words."
    if rung == 3:
        return "Placed by era language in its classification."
    if reason.get("subject_check") == "third_person_age":
        return "Not placed — the age statement names someone else, not you."
    return "Not placed yet — no date, era language, or pin points anywhere."


def place_events(events: list[dict], periods: list[dict],
                 placements: dict | None = None, *, frames: object = (),
                 eras: object = (), anchors: dict | None = None,
                 birth_date: object = None,
                 ) -> tuple[dict[str, list[dict]], list[dict]]:
    """({period_slug: [events...]}, unplaced). Placement order:
      0. the owner's manual placement (content-keyed overlay) — always wins,
         and is validated against the frames at FILING time (`save_placement`
         refuses a pin whose date cannot be inside its period's frame), never
         re-checked here.
      1-3. `heuristic_slot` (date → frame arithmetic; named-era language; era
         text), then an explicit unplaced bucket — never forced.

    Every row carries `placement_reason` (the rung that fired, its evidence,
    and — for a manual row — `rung: 0`) and a one-sentence
    `provenance_summary`; `O-E2f`'s parity test reads exactly this field.
    """
    placed: dict[str, list[dict]] = {p["slug"]: [] for p in periods}
    unplaced: list[dict] = []
    # v215: the join is `resolve_placements` — the ONE pairing of a stored
    # placement with the live event it is about, repair included.
    manual_by_key = {}
    if placements:
        manual_by_key = {key: row
                         for row, key in resolve_placements(placements, events)
                         if key and row.get("period") in placed}

    def auto_slot(event: dict) -> tuple[str | None, dict]:
        return heuristic_slot(event, periods, frames=frames, eras=eras,
                              anchors=anchors, birth_date=birth_date)

    for event in events:
        # 0) The owner said so — manual placement outranks every heuristic.
        if manual_by_key:
            manual = manual_by_key.get(placement_key(event))
            if manual:
                # Redundancy check runs on the ORIGINAL event: once the
                # classification itself places it here (the loop caught up),
                # the pin retires on the next weekly pass (v105).
                redundant = auto_slot(event)[0] == manual["period"]
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
                        # v254: the pre-placement pass may already have derived
                        # a date for this moment. The owner's pin outranks it —
                        # and a `date_derived` left behind would label a stated
                        # date as one this system worked out, which is exactly
                        # the provenance lie ADR 0026 exists to prevent.
                        event.pop("date_derived", None)
                if manual.get("note"):
                    event["placement_note"] = manual["note"]
                event["placement_reason"] = {"rung": 0, "evidence": "manual"}
                event["provenance_summary"] = _placement_provenance_summary(
                    event["placement_reason"])
                placed[manual["period"]].append(event)
                continue
        slot, reason = auto_slot(event)
        event = dict(event)
        event["placement_reason"] = reason
        event["provenance_summary"] = _placement_provenance_summary(reason)
        if slot is None:
            unplaced.append(event)
        else:
            placed[slot].append(event)
    for rows in placed.values():
        sort_period_events(rows)
    return placed, unplaced


def sort_period_events(rows: list[dict]) -> list[dict]:
    """Dated moments lead, in date order; everything after is v194's exact key,
    so a period with no dated events sorts byte-identically.

    v205: ONE definition, because `timeline_data` re-sorts after the
    cross-dating pass has dated moments `place_events` saw as undated.
    """
    rows.sort(key=lambda e: (e.get("date") is None,
                             chrono.year_of(e.get("date")) or 0,
                             not e["when_hint"], e["source_short"]))
    return rows


def rekey_orphaned_placements(dry_run: bool = False) -> list[dict]:
    """THE DURABLE HALF of rung 3 (v253, lifehug#276) — the store heals.

    `resolve_placements` re-keys an orphaned pin IN MEMORY, so the moment the
    classifier rewrites a description the page still renders the person's
    date. That is the read. This is the WRITE, and it has to exist separately:
    a repair that only recomputes proves the substrate is right and says
    nothing about the file the product reads (the `simulate_repair.py` lesson,
    2026-08-26). Until the store holds the live key, `remove_placement` and
    every host that posts a key back still name an identity nothing joins.

    Only rung 3 persists. Rung 2's legacy repair deliberately leaves the stored
    key alone — that identity is what the viewer's own remove button posts, and
    v215 pinned that behavior by test.

    Each rewritten row keeps its provenance: `rekeyed_from` is the key the
    person's pin was filed under, `rekeyed_at` is when the repair ran. Nothing
    is deleted, and a row is never rewritten twice to the same key (the second
    pass joins at rung 1 and this returns `[]` — the pass is idempotent, which
    is the property a runbook step has to have).

    Returns the rewritten records. `dry_run` computes them and writes nothing.
    """
    data = load_placements()
    if not data["placements"]:
        return []
    events = load_events()
    joined = {id(row): (key, rung)
              for row, key, rung in resolve_placements_with_rung(data, events)}
    rekeyed: list[dict] = []
    for row in data["placements"]:
        key, rung = joined.get(id(row), ("", ""))
        if rung != PLACEMENT_JOIN_SOURCE_REKEY or not key or key == row.get("key"):
            continue
        row["rekeyed_from"] = str(row.get("key") or "")
        row["key"] = key
        row["rekeyed_at"] = now_utc()
        rekeyed.append(dict(row))
    if rekeyed and not dry_run:
        write_json(PLACEMENTS_FILE, data)
    return rekeyed


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
    birth_date = None
    with contextlib.suppress(Exception):
        birth_date = landmark_birth_date()
    frames = ()
    if birth_date is not None:
        with contextlib.suppress(Exception):
            frames = cross_dating.age_frames(birth_date, as_of=now_utc())
    events_by_key = {placement_key(e): e for e in events}
    # v215: the same join every other reader uses, so a repaired pin retires
    # when the loop catches up with it instead of hanging around forever.
    joined = {id(row): key for row, key in resolve_placements(data, events)}
    period_slugs = {p["slug"] for p in periods}
    keep: list[dict] = []
    retired: list[dict] = []
    for pin in data["placements"]:
        event = events_by_key.get(joined.get(id(pin)) or "")
        auto_slot = (heuristic_slot(event, periods, frames=frames,
                                    birth_date=birth_date)[0]
                    if event is not None else None)
        if (event is not None and pin.get("period") in period_slugs
                and auto_slot == pin["period"]):
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
    return gaps


# `era_gaps` / `MIN_ERA_GAP_YEARS` are RETIRED (eras design O-E2, §5.2). A
# dated hole between two named eras was a gap kind measured against the same
# era-dates the founder's own eras were wrongly dated by (source membership,
# §1 item 1) — retiring the mechanism that dated eras from their members makes
# the hole it measured unmeasurable the same way, and `residence_gap` (the
# tiling chain in `landmarks_interaction.residence_gaps`) is untouched: it
# never depended on this.


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
            # v208: an envelope taken from the moments inside is a DERIVED
            # span, and ADR 0026's rule is that a derived date is marked by
            # `date_derived` and by nothing else. Without the mark the
            # placement score's stated half would read an envelope the
            # cross-dating pass produced as something the person stated, and
            # ADR 0027's pair would move when the pass ran.
            if place["date"] is not None:
                place["date_derived"] = {
                    "rule": "moments", "join": "moment_envelope",
                    "anchor": f"entity:{place['slug']}",
                    "label": str(place.get("label") or place["slug"]),
                    "provenance": "from the moments you have already dated",
                }
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
    """A residence's span inferred from the dated moments that happened there.

    v207: the arithmetic moved to `cross_dating.span_from_dated`, because a
    BAND needs exactly the same envelope one level up and the recurring-defect
    doctrine forbids the second copy. This name stays as the residence's own
    reading of it.
    """
    return cross_dating.span_from_dated(events)


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
    # `era_gap` is RETIRED (eras design O-E2, §5.2) with `era_gaps()` above —
    # `residence_gap` below is a different tiling chain and is untouched.
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
    """One undated moment, named by its own title — the commonest unknown.

    v215: the row carries the moment's own `placement_key`, so a host that
    files this unknown's answer files it under the identity `place_events`
    joins on. The `label` is what a person reads and the description is what
    they hear back; neither is identity any more (lifehug#228).
    """
    label = str(event.get("title") or event.get("description") or "this moment").strip()
    row = {
        "kind": "moment",
        "period": period,
        "source_short": event.get("source_short"),
        "source": event.get("source"),
        "label": label,
        "description": str(event.get("description") or "").strip(),
        "placement_key": placement_key(event),
        "hint": "Anchor it against something already dated — never a guessed year.",
    }
    row["key"] = unknown_key(row)
    return row


# ---------------------------------------------------------------------------
# The interval a thing occupies absent an answer — ONE definition (v208).
# ---------------------------------------------------------------------------


def _now_year() -> int:
    return datetime.now(timezone.utc).year


def life_span(data: object = None, birth_date: object = None) -> tuple[int, int] | None:
    """``(birth_year, current_year)`` — the stretch the timeline can order.

    This is `L` in the placement score and the honest floor for anything the
    vault cannot bound more tightly than *sometime in this life*. ``None``
    when no birth landmark exists — which is exactly why `birth` wears the ★:
    without it there is no denominator, no floor, and no score (ADR 0027).
    """
    record = birth_date
    if record is None and isinstance(data, dict):
        row = (data.get("anchors") or {}).get("birth")
        record = row.get("date") if isinstance(row, dict) else None
    year = chrono.year_of(record)
    if year is None:
        return None
    return (int(year), max(int(year), _now_year()))


def _record_years(record: object) -> list[int] | None:
    """A date record as ``[first_year, last_year]``; ``None`` when unusable."""
    first = chrono.year_of(record)
    last = chrono.year_of(record, end=True)
    if first is None or last is None:
        return None
    return [int(first), int(max(first, last))]


def _band_span(data: dict, ref: object) -> list[int] | None:
    """The span of the band a slug or band ref names.

    An era's OWN date where it carries one (including a span the v207 band
    ladder derived), else the band that covers it — which is how a moment
    inside a chapter-kind band still gets bounds when its period has none.
    """
    slug = str(ref or "").strip()
    if not slug:
        return None
    for period in data.get("periods") or ():
        if str(period.get("slug")) != slug or period.get("date") is None:
            continue
        years = _record_years(period["date"])
        if years:
            return years
    for band in data.get("bands") or ():
        if band.get("date") is None:
            continue
        members = [str(member) for member in (band.get("periods") or ())]
        if str(band.get("ref")) != slug and slug not in members:
            continue
        years = _record_years(band["date"])
        if years:
            return years
    return None


def _spine_hole(data: dict, slug: object) -> list[int] | None:
    """The hole an UNDATED era occupies between its dated neighbours.

    The retired `era_gaps`'s own arithmetic, read for ONE era instead of
    between two: the stretch after the last dated era before it and before
    the first dated era after it. ``None`` when either neighbour is missing,
    or when the two abut.
    """
    periods = list(data.get("periods") or ())
    index = next((n for n, row in enumerate(periods)
                  if str(row.get("slug")) == str(slug)), None)
    if index is None:
        return None
    before = next((chrono.year_of(row.get("date"), end=True)
                   for row in reversed(periods[:index]) if row.get("date") is not None),
                  None)
    after = next((chrono.year_of(row.get("date"))
                  for row in periods[index + 1:] if row.get("date") is not None), None)
    if before is None or after is None:
        return None
    start, end = int(before) + 1, int(after) - 1
    return [start, end] if end >= start else None


def _own_years(row: dict) -> list[int] | None:
    """The interval a row already carries, coerced to two ints.

    `residence_gap` mints its own (`landmarks_interaction.residence_gaps`);
    that is the honest answer for its kind and is not recomputed here.
    """
    years = row.get("years")
    if not isinstance(years, (list, tuple)) or len(years) != 2:
        return None
    try:
        first, last = int(years[0]), int(years[1])
    except (TypeError, ValueError):
        return None
    return [min(first, last), max(first, last)]


def unknown_years(row: dict, data: dict, *, life: tuple[int, int] | None) -> list[int]:
    """The interval this thing occupies **absent an answer** (v208, ADR 0027).

    **One definition, three consumers.** The placement score's per-thing width
    (`placement_score`), the certainty chart's cloud-dot position and
    tap-span, and the ghost's prior span (`cross_dating.stamp_prior_spans`)
    are all THIS interval. Divergence between what the cloud draws and what
    the score counts would be the promise/delivery drift the dating-dataflow
    audit already found once.

    | kind | years |
    |---|---|
    | `moment` in an era whose band has a span | the band's span (containment, ADR 0026, read as bounds) |
    | `moment` in an undated era, or unplaced | `life` — the honest floor |
    | `period_bound` | the era's derived span, else the hole between its dated neighbours on the spine, else `life` |
    | `place_span` | its band's span, else `life` |
    | `date_contradiction` | the union of the disputed claims' intervals |
    | `landmark_subject`, `residence_gap` | the row's own interval where the ladder named one, else `life` |

    ``life`` is `(birth_year, current_year)` from the birth landmark. With no
    birth date there is no floor, so a row carrying no interval of its own
    gets ``[]`` — no `years`, and (ADR 0027) no score at all. That is
    correct, and it is why `birth` wears the ★.
    """
    if not isinstance(row, dict) or not isinstance(data, dict):
        return []
    floor = [int(life[0]), int(life[1])] if life else []
    return _life_floor_years(row, data, life=life, floor=floor)


def range_is_whole_life(years: object, life: tuple[int, int] | None) -> bool:
    """Is this interval the ENTIRE life — i.e. no information at all?

    D5 (Timeline Fix 07): the owner's page read "could be 1981-2026" beside a
    question. A range equal to the life span says only "sometime while you
    were alive", which is what `undated` already means, and dressing it up as
    a range invites the reader to believe the system knows something. The
    interval itself is unchanged — the placement score's denominator depends
    on it (ADR 0027) — but a row carrying it is stamped `undated_range` so
    every surface renders it as undated rather than as a span.
    """
    if not life or not isinstance(years, (list, tuple)) or len(years) != 2:
        return False
    try:
        return [int(years[0]), int(years[1])] == [int(life[0]), int(life[1])]
    except (TypeError, ValueError):
        return False


def _life_floor_years(row: dict, data: dict, *, life, floor: list) -> list[int]:
    kind = str(row.get("kind") or "")
    if kind in ("residence_gap", "date_contradiction", "landmark_subject"):
        return _own_years(row) or floor
    if kind == "moment":
        return _band_span(data, row.get("period")) or floor
    if kind == "period_bound":
        slug = row.get("slug") or row.get("period")
        return _band_span(data, slug) or _spine_hole(data, slug) or floor
    if kind == "place_span":
        return _band_span(data, row.get("period")) or floor
    return _own_years(row) or floor


def unknowns(data: dict, landmarks: object = None) -> list[dict]:
    """Every ANSWERABLE unknown as `{kind, key, label, probe, ...}`.

    One subject per row (v196). An unknown is something a person can picture:
    *the dog that followed you home*, *when the Yucaipa years ended*, *the
    stretch between two dated eras*. Never a count.

    "I'll find out" is an ordinary answer — there is no `deferred` flag and no
    quiet window; an unknown the person could not date simply stays
    outstanding, keeps its leverage, and is asked again when the ordering says
    it is worth asking.

    v208 (ADR 0027): every row also carries `years`, the interval it currently
    occupies absent an answer (`unknown_years`) — the ONE interval the
    placement score's width, the chart's cloud dot and the ghost's prior span
    are all read from. `resolves` and `leverage` arrive later, in
    `offered_unknowns`, because they need the dependency index.
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

    # 2. A specific era's missing bounds — EXCEPT an age frame's.
    #
    # D5 (Timeline Fix 07, owner's 14:21 staging screenshot 2026-08-29): the
    # page asked "When did Childhood end — before or after First big paycheck
    # arrives by mail?". Childhood is an AGE FRAME: its bounds are arithmetic
    # off the birth origin (`cross_dating.age_frames`, ADR 0030 — frames are
    # the permanent calculated coordinate system, never model-authored and
    # never asked). The legacy `period.json` roster still names them, which is
    # exactly how they reached this loop; `legacy_period_ref` is the one map
    # that says which slugs those are, so there is no second list here.
    for period in data.get("periods") or []:
        if legacy_period_ref(period.get("slug")) is not None:
            continue
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

    # 4. The contradictions — already one subject each. `era_gap` is RETIRED
    # (eras design O-E2, §5.2): a dated hole measured against era dates that
    # were themselves the founder's own mis-placements is not a fact worth
    # asking about.
    gaps = list(data.get("global_gaps") or [])
    for period_gaps in (data.get("gaps_by_period") or {}).values():
        gaps.extend(period_gaps)
    for gap in gaps:
        kind = str(gap.get("kind") or "")
        if kind not in ("date_contradiction",):
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

    # v208 (ADR 0027): every row carries the interval it currently occupies
    # absent an answer, so `unknown_width` finds a real width where it used to
    # hit its 1.0 ranking floor — and the score, the chart's cloud and the
    # ghost's prior span all read the SAME number.
    life = life_span(data)
    for row in rows:
        years = unknown_years(row, data, life=life)
        if years:
            row["years"] = years
            # D5 (Timeline Fix 07): a range equal to the whole life carries no
            # information. The interval STAYS — the placement score's floor is
            # exactly this width (ADR 0027) — but the row says so, so no
            # surface renders "could be 1981-2026" as if it were a finding.
            if range_is_whole_life(years, life):
                row["undated_range"] = True

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


def unknown_anchor(row: object) -> str | None:
    """The anchor key this unknown would BECOME when it is answered (v208).

    The glow's source. `dependency_index` maps an anchor to everything one
    answer places; this maps a ROW to the anchor it would supply, so a row can
    be asked "and what else would that place?" without a second graph.

    | kind | anchor |
    |---|---|
    | `period_bound` | `period:<slug>` |
    | `place_span` | `entity:<slug>` |
    | `moment` | `event:<period>:<source_short>` |
    | `landmark_subject` | the landmark anchor key its ladder mints (`family:sibling-james:birth`, `residences-mesa`) |
    | unplaced `moment`, `date_contradiction`, `residence_gap` | ``None`` — self-only |

    One of those is deliberate honesty rather than omission. A
    **residence gap**'s answer mints a residence anchor whose slug nobody
    knows yet; naming a key for a place the person has not named would be a
    promise with no delivery behind it. An **unplaced** moment has no
    `event:` key to become either — dating it places itself.
    """
    if not isinstance(row, dict):
        return None
    kind = str(row.get("kind") or "")
    if kind == "period_bound":
        slug = str(row.get("slug") or row.get("period") or "").strip()
        return f"period:{slug}" if slug else None
    if kind == "place_span":
        slug = str(row.get("slug") or "").strip()
        return f"entity:{slug}" if slug else None
    if kind == "moment":
        period = str(row.get("period") or "").strip()
        if not period:
            return None
        return f"event:{period}:{row.get('source_short') or ''}"
    if kind == "landmark_subject":
        anchor = str(row.get("anchor") or "").strip()
        return anchor or None
    return None


def row_leverage(row: dict, index: dict[str, set[str]]) -> tuple[list[str], int]:
    """ONE unknown row's reach: `(resolves, leverage)` (v208, ADR 0027).

    The single definition of row leverage — extracted so every caller that
    orders unknowns (`offered_unknowns`, `timeline_interaction.build_timeline_plan`)
    reads it off the same arithmetic instead of keeping its own copy (issue
    #216: `build_timeline_plan` had drifted back to the PRE-v208 definition,
    which ranked a row by the largest resolve set it happened to BELONG to
    rather than what THIS answer would place — the recurring-defect doctrine
    forbids a second copy of a fact this load-bearing).

    * `resolves` — the other unknowns that answering THIS row would place,
      taken from `dependency_index` under the anchor this row would become
      (`unknown_anchor`), minus the row's own key. `[]` when the row becomes
      no anchor.
    * `leverage` — `1 + len(resolves)`, self-inclusive: a row with no reach
      has `leverage: 1` exactly, because answering it still places itself.
    """
    anchor = unknown_anchor(row)
    resolved = set(index.get(anchor) or ()) if anchor else set()
    resolved.discard(row["key"])
    resolves = sorted(resolved)
    return resolves, 1 + len(resolves)


def offered_unknowns(rows: list[dict], index: dict[str, set[str]],
                     limit: int = UNKNOWNS_PAGE_CAP) -> list[dict]:
    """The unknowns a page offers: leverage first, then the cheapest probe.

    Every row carries its own **reach** (v208, ADR 0027), computed by the one
    shared `row_leverage` definition, so the ordering is visible rather than
    mysterious and a host can draw the glow from honest numbers.

    The glow itself is RELATIVE and its ranking is the host's job — these are
    raw per-row numbers and nothing here quantiles them. `keystones()` is
    untouched: row `leverage` is display reach, keystone `gain` is marginal
    plan value, and they are different questions.
    """
    for row in rows:
        row["resolves"], row["leverage"] = row_leverage(row, index)
    ordered = sorted(rows, key=lambda row: (
        -int(row.get("leverage") or 0),
        int((row.get("probe") or {}).get("cost") or 99),
        str(row.get("key")),
    ))
    return ordered[:max(int(limit), 0)]


def dependency_index(data: dict) -> dict[str, set[str]]:
    """`{anchor_key: {unknown_key, ...}}` — what one answer would put in place.

    The anchor candidates are exactly the three ruling 5 names: a period's
    start/end, a landmark (dated) event, and an entity's arrival.

    **v205 (ADR 0026) — the promise and the delivery are the same join.**
    Before v205 this function counted what an anchor *touched*, and the package
    had no pass that turned a resolved anchor into a dated moment at all: the
    star said "one answer would place 53 more things" and answering it placed
    nothing. Now the MOMENT half of every resolve set is computed by
    `cross_dating.derivable_moments` — the cross-dating pass's own containment
    rule read backwards — so the number on the star is the number that dates on
    the next read. Two claims went away with it, both of them fictions:

    * a dated **event** no longer claims its undated neighbours (a point is not
      a span; nothing has ever derived a date from an adjacent moment), and
    * a **person** entity no longer claims the moments that share its sources
      (an arrival bounds nothing).

    Each keeps the claims that ARE definitional: an era's own bounds, and the
    `place_span` rows that fall out of a dated era's moments (`_place_span`
    derives a residence's span from the moments that happened there), and a
    place's own span. `era_gap` is RETIRED (eras design O-E2, §5.2) along
    with the reach it used to contribute here.

    v196: the keys on both sides are the CONCRETE unknown keys `unknowns()`
    emits, so leverage counts real answerable things rather than aggregate rows.
    """
    index: dict[str, set[str]] = {}
    rows = unknowns(data)
    live = {row["key"] for row in rows}
    by_period: dict[str, set[str]] = {}
    for row in rows:
        if row.get("period"):
            by_period.setdefault(str(row["period"]), set()).add(row["key"])

    event_lineup = data.get("event_lineup") or {}
    entity_lineup = data.get("entity_lineup") or {}
    periods = data.get("periods") or []

    # The one join that both promises and delivers.
    reach = cross_dating.derivable_moments(
        event_lineup=event_lineup,
        unplaced_events=data.get("unplaced_events") or [],
        periods=periods,
        entity_lineup=entity_lineup,
    )
    derivable: dict[str, set[str]] = {}
    for anchor, pairs in reach.items():
        keys = {unknown_key(moment_unknown(event, period)) for period, event in pairs}
        derivable[anchor] = keys & live

    for period in periods:
        slug = period["slug"]
        key = f"period:{slug}"
        # The era's own non-moment unknowns are definitional; its moments are
        # exactly what containment would bound.
        definitional = {row for row in by_period.get(slug, set())
                        if not row.startswith("moment:")}
        index[key] = definitional | derivable.get(key, set())

    for slug, rows_here in event_lineup.items():
        for event in rows_here:
            if event.get("date") is None:
                continue
            key = f"event:{slug}:{event.get('source_short') or ''}"
            # v205: a dated moment bounds no other moment (`era_gap` reach is
            # retired along with the gap kind it used to close).
            index[key] = set()

    place_slugs = {
        str(row.get("slug"))
        for rows_here in entity_lineup.values()
        for row in rows_here or ()
        if isinstance(row, dict) and row.get("type") == "place"
    }
    for rows_here in entity_lineup.values():
        for row in rows_here:
            if row.get("type") not in ("person", "place"):
                continue
            key = f"entity:{row['slug']}"
            claims = set(derivable.get(key, set()))
            if str(row.get("slug")) in place_slugs:
                own_span = f"place_span:{row['slug']}"
                if own_span in live:
                    claims.add(own_span)
            index[key] = index.get(key, set()) | claims
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

    O-E6: each row also carries its canonical `work_item_id`, derived through
    `temporal_work_items.canonical_work_item_id` from the anchor and the
    anchor's own KIND. That is the identity the substrate's fold mints for the
    same gap, so the ★ the daily surface shows and the item the whisper lane
    suppresses are provably one thing — and it is what lets a host put
    `work_item_id` on its "today" payload beside the existing `tl:<slug>`
    without re-deriving anything.
    """
    anchors = data.get("anchors") if isinstance(data, dict) else None
    kinds = {
        str(key): str((row or {}).get("kind") or "")
        for key, row in (anchors or {}).items()
        if isinstance(row, dict) or row is None
    } if isinstance(anchors, dict) else {}
    rows = []
    for row in _greedy_plan(_scored_anchors(data), n):
        anchor = str(row.get("anchor") or "")
        identity = twi.canonical_work_item_id(
            kind=twi.BIRTH_ORIGIN_KIND,
            subject_ref=anchor,
            anchor_kind=kinds.get(anchor),
        )
        rows.append({**row, "work_item_id": identity} if identity else dict(row))
    return rows


# ---------------------------------------------------------------------------
# The placement score (v208, ADR 0027) — the level and its margin, one
# arithmetic. Beside `keystones`/`dig_plan`, the house home for derived
# timeline arithmetic.
# ---------------------------------------------------------------------------

#: The band thresholds, Recoin-style (`system/research/chronology-vis.md`
#: §4.3): arbitrary but STABLE, and never peer-relative — there are no peers
#: in a private vault. `1: <0.2 · 2: <0.4 · 3: <0.6 · 4: <0.8 · 5: ≥0.8`.
PLACEMENT_BANDS = (0.2, 0.4, 0.6, 0.8)

#: The finest width the score can express — one day, in years. A fully
#: day-pinned vault ROUNDS to 1.0 at four places without ever reaching it,
#: which is the honest shape: an interval is never nothing.
DAY_YEARS = 1.0 / 365.0

#: Four places, everywhere. A score is a banded chip, not a readout.
PLACEMENT_ROUNDING = 4

#: What one answered anchor buys, as a width in years. Every rung of the
#: elicitation ladder ends at a year-or-finer claim
#: (`timeline_interaction.PLAYBOOK_STEPS`), and the year is the unit the score
#: is measured in — so the margin collapses its resolve set to one year. A
#: finer answer over-delivers and never under-delivers, which keeps the margin
#: a FLOOR exactly as the score itself is one (ADR 0027).
ANCHOR_GRAIN_YEARS = 1.0

#: What an INFERRED placement is worth against a stated one (Timeline Fix 05
#: §8.3, ADR 0027). `timeline-rules:4` puts an undated moment inside a dated
#: residence's span — real information, and not the same thing as somebody
#: saying when it was — so it earns HALF the credit.
#:
#: The arithmetic, once, here and in :func:`placement_score`'s docstring: the
#: level is ``1 − Σwᵢ/(n·L)``, which is the same as ``Σ (L − wᵢ)/(n·L)`` — each
#: thing CONTRIBUTES ``(L − wᵢ)/(n·L)``. Halving that contribution is the same
#: as scoring the thing at ``w′ᵢ = L − 0.5·(L − wᵢ) = (L + wᵢ)/2``, which is
#: what :func:`_effective_width` computes. Three properties come free and all
#: three are the reason it is this and not a fudge factor: an inference always
#: scores between its own width and the floor, a NARROWER inference still beats
#: a wider one, and an inference can never beat a stated placement of the same
#: width. Guessing still cannot pay (ADR 0027's first rule).
INFERRED_PLACEMENT_WEIGHT = 0.5

#: The placement score's own formula version, separate from
#: `temporal_work_items.SCORE_FORMULA_VERSION` (which versions the WORK-ITEM
#: score) because the two are recalibrated by different people for different
#: reasons. `placement-score:1` is v208's original; `:2` is this release, in
#: which an inferred placement stopped counting as a whole one.
PLACEMENT_SCORE_FORMULA_VERSION = "placement-score:2"


def _record_width(record: object, life: tuple[int, int]) -> float:
    """A dated thing's interval width in years, floored at one day.

    The bounds are filled by grain the way the rest of the chronology fills
    them — `chronology._ordinal` fills a bare year down to 1 January at the
    start and up to 31 December at the end — so "1984" is a whole year wide
    and "1984-07-11" is a day. An open bound (`1984/..`) is clamped to the
    life: the honest reading of "or later" is "or later, in this life".
    """
    parsed = chrono.from_dict(record)
    if parsed is None:
        return float(max(life[1] - life[0], 1))
    first = chrono._ordinal(parsed.earliest, end=False) or (life[0], 1, 1)  # noqa: SLF001
    last = chrono._ordinal(parsed.latest, end=True) or (life[1], 12, 31)  # noqa: SLF001
    try:
        days = (datetime(*last) - datetime(*first)).days
    except (TypeError, ValueError):
        return DAY_YEARS
    return max(float(days) / 365.0, DAY_YEARS)


def _years_width(years: object) -> float:
    """An unknown interval's width — `unknown_width`'s definition, reused so
    the score and the plan's ranking can never be two numbers."""
    return unknown_width({"years": years})


def _stated_view(data: dict) -> dict:
    """`data` as it would read if the cross-dating pass had never run.

    Ruling 3 (#637): **stated and derived are a pair**, and the stated half
    must be immovable by the pass. So the stated basis reads every DERIVED
    span as absent — an era the band ladder dated, and the band that reports
    that era's span — and an era's moments fall back to the honest floor
    exactly as they would have before the pass. Nothing is mutated: the view
    is shallow copies.
    """
    periods = []
    derived_slugs: set[str] = set()
    for period in data.get("periods") or ():
        if period.get("date_derived"):
            derived_slugs.add(str(period.get("slug")))
            period = {**period, "date": None}
        periods.append(period)
    bands = []
    for band in data.get("bands") or ():
        members = {str(slug) for slug in (band.get("periods") or ())}
        if band.get("date_derived") or (band.get("kind") == "period"
                                        and members & derived_slugs):
            band = {**band, "date": None}
        bands.append(band)
    return {**data, "periods": periods, "bands": bands}


def _thing(kind: str, key: str, *, record: object, unknown_row: dict,
           data: dict, stated: dict, life: tuple[int, int]) -> dict:
    """One scored thing: what it is, the interval it occupies, and the
    interval it would occupy on the stated basis alone."""
    derived = bool(unknown_row.get("date_derived"))
    dated = record is not None
    # `timeline-rules:4`: is this interval something the system INFERRED?
    # Read through `temporal_work_items.node_claim_basis`, which is the one
    # mapping from "how was the interval arrived at" onto the class the
    # product renders — so the score and the row's own `inferred` badge can
    # never disagree about which things are inferences.
    inferred = dated and twi.node_claim_basis(record) == "inferred"
    # An inference is not something anybody stated, so the STATED basis reads
    # it as unplaced exactly as it reads a cross-dated span as unplaced.
    derived = derived or inferred
    if dated:
        years = _record_years(record) or [life[0], life[1]]
        width = _record_width(record, life)
    else:
        years = unknown_years(unknown_row, data, life=life) or [life[0], life[1]]
        width = _years_width(years)
    if dated and not derived:
        stated_years, stated_width = years, width
    else:
        # Ruling 3: on the stated basis anything the person did not state is
        # UNPLACED, and the interval it falls back to must be one the pass
        # cannot have widened or narrowed — so an undated thing is read against
        # the stated view too, not only a derived one. Without this an undated
        # moment inherits the era span the pass just derived, and `score_stated`
        # moves when the pass runs.
        stated_years = unknown_years(unknown_row, stated, life=life) or [life[0], life[1]]
        stated_width = _years_width(stated_years)
    return {"kind": kind, "key": key, "years": years, "width": width,
            "stated_years": stated_years, "stated_width": stated_width,
            "dated": dated, "derived": derived, "inferred": inferred}


def _scored_things(data: dict, life: tuple[int, int]) -> list[dict]:
    """Every THING the timeline holds, with the interval it occupies.

    The population is exactly what `unknowns()` and the dated lineups
    enumerate between them — placed moments, unplaced moments, eras, and the
    place spans inside the bands. ONE enumeration, shared by `placement_score`
    and by its own tests, so "what is scored" can never become two lists.
    """
    stated = _stated_view(data)
    things: list[dict] = []

    def moment(event: dict, slug: object) -> None:
        row = dict(event)
        row.update({"kind": "moment", "period": slug,
                    "source_short": event.get("source_short")})
        things.append(_thing("moment", unknown_key(row), record=event.get("date"),
                             unknown_row=row, data=data, stated=stated, life=life))

    for slug, rows_here in (data.get("event_lineup") or {}).items():
        for event in rows_here or ():
            moment(event, slug)
    for event in data.get("unplaced_events") or ():
        moment(event, None)

    for period in data.get("periods") or ():
        # eras O-E2 (design §5.2): an age frame is the COORDINATE SYSTEM
        # placement is measured against, not a thing whose OWN placement is in
        # question — scoring it would drop the level by counting the ruler as
        # unplaced. Legacy `periods` never carries one today (they are
        # calculated nodes, not roster rows); the guard is explicit anyway so
        # it stays true if that ever changes.
        if str(period.get("kind") or period.get("event_kind") or "") == "age_frame":
            continue
        row = dict(period)
        row.update({"kind": "period_bound", "slug": period.get("slug"),
                    "period": period.get("slug")})
        things.append(_thing("period", unknown_key(row), record=period.get("date"),
                             unknown_row=row, data=data, stated=stated, life=life))

    seen: set[str] = set()
    for band in data.get("bands") or ():
        for place in band.get("places") or ():
            slug = str(place.get("slug") or "").strip()
            if not slug or slug in seen:
                continue
            seen.add(slug)
            row = dict(place)
            row.update({"kind": "place_span", "slug": slug, "period": band.get("ref")})
            things.append(_thing("place_span", unknown_key(row), record=place.get("date"),
                                 unknown_row=row, data=data, stated=stated, life=life))
    return things


def _effective_width(thing: dict, key: str, span: float) -> float:
    """The width the level counts for this thing.

    Its own, unless the interval was INFERRED rather than stated or worked
    out — in which case it counts for :data:`INFERRED_PLACEMENT_WEIGHT` of a
    stated placement, which is the width ``(L + wᵢ)/2``. See that constant for
    why halving the CONTRIBUTION is the same as widening the interval, and for
    the three properties that survive it.

    On the ``stated_width`` basis an inferred thing is already sitting at the
    floor (`_thing` reads it as underived), so the same arithmetic returns
    ``L`` and the stated half of the pair is unmoved — which is ruling 3.
    """
    width = float(thing[key])
    if not thing.get("inferred"):
        return width
    return span - INFERRED_PLACEMENT_WEIGHT * (span - width)


def _level(things: list[dict], life: tuple[int, int], *, key: str = "width") -> float:
    """`1 − Σw′ᵢ / (n · L)`, clamped to [0, 1] and rounded to four places.

    ``w′ᵢ`` is :func:`_effective_width` — a stated or calculated thing's own
    width, and an inferred thing's width discounted to half its credit."""
    span = float(max(life[1] - life[0], 1))
    if not things:
        return 0.0
    total = sum(_effective_width(thing, key, span) for thing in things)
    value = 1.0 - (total / (len(things) * span))
    return round(min(max(value, 0.0), 1.0), PLACEMENT_ROUNDING)


def placement_score_band(score: float) -> int:
    """`1..5` from a score — fixed thresholds, documented as arbitrary but
    stable (`chronology-vis.md` §4.3, design consequence 5: band it, never
    render a bare continuous percentage)."""
    for index, threshold in enumerate(PLACEMENT_BANDS, start=1):
        if score < threshold:
            return index
    return len(PLACEMENT_BANDS) + 1


def _per_year_band(things: list[dict], life: tuple[int, int]) -> list[dict]:
    """The strip: one row per calendar year of the life.

    `pinned_fraction` is the AORISTIC weight (Ratcliffe & McCullagh 1998, via
    `chronology-vis.md` §2.1) — each thing gives `min(1, 1/wᵢ)` to every year
    its interval covers, normalised by how many things cover that year — so a
    day-pinned thing contributes ~1 to its year and a decade-wide thing ~0.1
    to each of ten. This is the half that answers Crema's summation problem
    (§2.2): five smeared moments and five pinned ones sum identically and
    read here as very different lives.

    `stated_vs_derived` is the share of that year's weight carried by things
    the cross-dating pass did NOT date — §1.5's italic convention, as a
    number. An empty year emits `0`, honestly: a flat stretch means nobody
    asked (design consequence 16).
    """
    rows: list[dict] = []
    for year in range(int(life[0]), int(life[1]) + 1):
        covering = [thing for thing in things
                    if thing["years"] and thing["years"][0] <= year <= thing["years"][1]]
        if not covering:
            rows.append({"year": year, "pinned_fraction": 0.0,
                         "stated_vs_derived": 0.0})
            continue
        weights = [min(1.0, 1.0 / max(float(thing["width"]), DAY_YEARS))
                   for thing in covering]
        total = sum(weights)
        stated = sum(weight for weight, thing in zip(weights, covering)
                     if not thing["derived"])
        rows.append({
            "year": year,
            "pinned_fraction": round(total / len(covering), PLACEMENT_ROUNDING),
            "stated_vs_derived": (round(stated / total, PLACEMENT_ROUNDING)
                                  if total else 0.0),
        })
    return rows


def _next_gain(data: dict, things: list[dict], life: tuple[int, int],
               score: float) -> dict | None:
    """The margin, from the SAME arithmetic as the level (§B.5).

    The top row of the existing greedy plan, re-expressed in score units: the
    level recomputed with that anchor's resolve set collapsed to the anchor's
    own grain (:data:`ANCHOR_GRAIN_YEARS`), minus the level now. Computed by
    re-running the level over a copied population — the promise-equals-
    delivery discipline `cross_dating.gain_sentence_for_record` (v207) already
    applies to the filing sentence, applied here to the number.

    `count` is the MOMENTS the resolve set holds, because moments are what
    dating an anchor actually dates; the star's own `leverage` remains the
    whole set and is unchanged.
    """
    plan = keystones(data, 1)
    if not plan:
        return None
    row = plan[0]
    keys = set(row.get("unknown_keys") or row.get("resolves") or ())
    if not keys:
        return None
    collapsed = [
        # Answering the anchor makes these things STATED, so the inferred
        # discount lifts with the same answer that narrows them — modelling
        # the narrowing without the lift would understate the margin.
        {**thing, "width": min(float(thing["width"]), ANCHOR_GRAIN_YEARS),
         "inferred": False}
        if thing["key"] in keys else thing
        for thing in things
    ]
    delta = _level(collapsed, life) - score
    return {
        "anchor": str(row.get("anchor") or ""),
        "count": sum(1 for key in keys if str(key).startswith("moment:")),
        "delta": round(max(delta, 0.0), PLACEMENT_ROUNDING),
    }


def placement_score(data: dict) -> dict | None:
    """How placed this life is, 0 → 1 — **at least** this organised (ADR 0027).

    `None` when no birth landmark exists: without a birthday there is no `L`,
    no floor for an unplaced thing, and no honest denominator. That is correct,
    and it is why `birth` wears the ★.

    Otherwise `1 − Σwᵢ/(n·L)` over every thing the timeline holds, where `wᵢ`
    is the width in years of the interval that thing occupies — its own where
    it is dated, `unknown_years`' where it is not. Five rules travel with the
    number and are not optional:

    * **Width, never presence.** A field-filled meter is an improper scoring
      rule, maximised by writing anything down; a width score is not, because
      the ladder stores a hedge as a WIDER interval (Gneiting & Raftery 2007,
      via `chronology-vis.md` §4.6). Guessing cannot pay.
    * **It is a floor.** Marginal width sums overestimate wherever ordering
      constraints exist — by 3× in Mountakis, Klos & Witteveen's worked case
      (§4.4) — so the number says *at least this organised*, never *exactly*.
      `caveat_floor` is `True` and stays `True` until the concurrent-
      flexibility correction lands.
    * **Stated and derived are a pair.** `score_stated` recomputes with every
      derived record read as undated; the cross-dating pass moves `score` and
      cannot move `score_stated` (§1.5's italic convention, as two numbers).
    * **An inference is worth half.** `timeline-rules:4` (Timeline Fix 05
      §8.3) puts an undated moment inside a dated residence's span. That is
      real information and it is not the same as being told when something
      happened, so it earns half the credit: each thing contributes
      `(L − wᵢ)/(n·L)`, and halving THAT contribution is exactly scoring the
      thing at `w′ᵢ = L − 0.5·(L − wᵢ) = (L + wᵢ)/2`
      (:data:`INFERRED_PLACEMENT_WEIGHT`, :func:`_effective_width`). A
      narrower inference still beats a wider one; an inference never beats a
      stated placement of the same width; and `score_stated` reads every
      inference as unplaced, so the pair still moves independently.
    * **It is not a verdict on the life.** It is scoped to what the timeline
      can order and place — placement, never "completeness" or "accuracy".

    Returns the payload block described in ADR 0027; hosts render it, and
    nothing here renders anything.
    """
    if not isinstance(data, dict):
        return None
    life = life_span(data)
    if life is None:
        return None
    things = _scored_things(data, life)
    if not things:
        return None
    score = _level(things, life)
    dated = [thing for thing in things if thing["dated"]]
    derived = sum(1 for thing in dated if thing["derived"])
    inferred = sum(1 for thing in dated if thing["inferred"])
    stated = len(dated) - derived
    return {
        "score": score,
        "score_formula_version": PLACEMENT_SCORE_FORMULA_VERSION,
        "score_stated": _level(things, life, key="stated_width"),
        "band": placement_score_band(score),
        "stated_fraction": (round(stated / len(dated), PLACEMENT_ROUNDING)
                            if dated else 0.0),
        "derived_fraction": (round(derived / len(dated), PLACEMENT_ROUNDING)
                             if dated else 0.0),
        # The `derived` share that is specifically an INFERENCE, so the eye
        # pane can say "n of these are where the system thinks you were, not
        # where you said you were" without recomputing anything.
        "inferred_fraction": (round(inferred / len(dated), PLACEMENT_ROUNDING)
                              if dated else 0.0),
        "life_span_years": int(max(life[1] - life[0], 1)),
        "things": len(things),
        "per_year_band": _per_year_band(things, life),
        "caveat_floor": True,
        "next_gain": _next_gain(data, things, life, score),
    }


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
    return _type_the_origin(index, birth)


def _type_the_origin(index: dict, birth: object) -> dict:
    """Every row that IS the birth origin is typed `birth`, whatever minted it.

    Timeline Fix 07 D1 (lifehug-platform#761, owner-reported 2026-08-29). The
    exclusion `timeline_interaction.anchor_for_probe` has carried since v236
    keys off ``kind == "birth"`` — and on the founder's own vault it never
    fired, because his birthday also entered this index as an ordinary dated
    MOMENT ("Author's birth", `kind: "landmark"`, 1981-07-11), sorted first by
    year, and became `anchor_rows[0]`. That is how "When did Switzerland
    Mission begin — before or after Author's birth?" reached a page.

    So the origin is identified by its DATE, not by which loop above happened
    to add it: any row whose interval is exactly the birth record's is the
    birth. One definition, so a second writer of the same fact cannot smuggle
    it back in as a landmark.
    """
    if birth is None:
        return index
    bounds = (birth.earliest, birth.latest)
    for key, row in index.items():
        if not isinstance(row, dict) or row.get("kind") == "birth":
            continue
        record = chrono.from_dict(row.get("date"))
        if record is None:
            continue
        if (record.earliest, record.latest) == bounds:
            index[key] = dict(row, kind="birth")
    return index


def _place_refusal_diagnostics() -> dict:
    """O-E0c's one counter: how many `period_bound` answers the package
    refused to file rather than misjoin onto whatever undated moment happens
    to sit in that era's lineup (`timeline_interaction.place_refusal`,
    `conversation_delivery._file_placement`).

    Read-only over the vault's own learning-failures ledger — the same
    ledger every other filing diagnostic already lands in
    (`lifehug_core.record_learning_failure`) — so there is one authoritative
    count, not a second one this module keeps itself. Guarded: a ledger
    problem must never take the timeline down, and an unreadable ledger
    reads as zero refusals rather than an error.
    """
    try:
        import timeline_interaction  # noqa: PLC0415

        reason = timeline_interaction.PLACE_REFUSED_NO_ERA_WRITER
        rows = read_learning_failures(limit=1_000_000, since_days=None)
        count = sum(
            1 for row in rows
            if row.get("component") == "conversation_delivery"
            and row.get("operation") == "timeline_place"
            and row.get("error") == reason
        )
    except Exception:  # noqa: BLE001
        count = 0
    return {"place_refused_no_era_writer": count}


def _stale_classifications_withheld() -> int:
    """`O-C`'s withheld-stale count, read through ONE TRANSITIONAL shim.

    `classify_story.withheld_stale` belongs to `feat/eras-o-c-stale-first`
    (lifehug issue #256) and is not yet on `main` (contract
    eras-o-e2-memberships.md, "Transitional dependencies"). Until it lands
    this is a named seam, not a silent guess: absent the function this reads
    `0` rather than importing something that does not exist, and the shim is
    deleted the moment `O-C` and `O-E2` are both merged. The legacy placement
    pass never re-globs `CLASSIFICATIONS_DIR` itself either way — staleness is
    O-C's own gate, upstream of this pass, applied once.
    """
    withheld_stale = getattr(classify_story, "withheld_stale", None)
    if withheld_stale is None:
        return 0
    try:
        return int(withheld_stale())
    except Exception:  # noqa: BLE001
        return 0


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
    # v217 (person dates): a roster person's `born`/`died` is an anchor too —
    # this is the `entity_date` unlock `questions.yaml` has declared since
    # v197 with no consumer. `anchors_from_people` skips any fact the landmark
    # store already anchors, so there is exactly one anchor per person per
    # fact and no reconciler. Guarded like every other derived block here.
    try:
        import entity_roster as _entity_roster  # noqa: PLC0415

        landmark_anchors = dict(landmark_anchors)
        landmark_anchors.update(landmarks_interaction.anchors_from_people(
            _entity_roster.load_roster("person"), filed_landmarks))
    except Exception:  # noqa: BLE001
        pass
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
    # eras O-E2 (design §5.1): rung 1 of the legacy pass is frame arithmetic,
    # the SAME `cross_dating.age_frames` the fold computes — one definition,
    # parity-tested (`O-E2f`). No birth landmark means no frames, which is the
    # honest floor: a dated event still stays a row, it just cannot reach
    # rung 1 without an origin to measure it from.
    frames = ()
    if birth_date is not None:
        try:
            frames = cross_dating.age_frames(birth_date, as_of=now_utc())
        except Exception:  # noqa: BLE001
            frames = ()
    # v254 (issue #278, ADR 0030 §4) — DATE BEFORE YOU PLACE. `heuristic_slot`
    # rung 1 is "dated → frame arithmetic", and it was structurally unreachable:
    # this function placed first and cross-dated second, so a moment whose date
    # the pass supplies was undated at the moment somebody asked where it goes.
    # Twelve of the founder's thirteen dated moments were in that state and
    # every one of them landed by era LANGUAGE instead of by its date
    # (lifehug-platform#720 CERT-03). So the membership-INDEPENDENT rungs run
    # here, before placement; the rungs that need to know which era a moment is
    # in stay in `cross_date` below. Guarded like every other derived block —
    # a cross-dating problem must not take the timeline down, and a failure
    # here simply leaves the rows undated for `place_events`, exactly as before.
    try:
        cross_dating_report = cross_dating.cross_date_moments(
            events, entity_lineup=entity_lineup, anchors=anchors,
            birth_date=birth_date)
    except Exception:  # noqa: BLE001
        cross_dating_report = None
    event_lineup, unplaced_events = place_events(
        events, periods, placements, frames=frames, anchors=landmark_anchors,
        birth_date=birth_date,
    )

    # v205 (ADR 0026): CROSS-DATING. `keystones` has promised leverage since
    # v196 and nothing ever delivered it — a filed birthday left "Born in
    # Redlands" undated because dates only ever arrived through the
    # classifier's own claim or an explicit `timeline-place`. This pass walks
    # every still-undated moment and derives a date from the anchors the
    # person already gave: definitional joins first, then age statements, then
    # containment bounds. Pure, stateless, recomputed on every read — a better
    # landmark improves the whole timeline instantly — and it NEVER overwrites
    # an explicit record. Guarded like every other derived block here: a
    # cross-dating problem must not take the timeline down.
    #
    # v207 (design D2): the same call now also dates undated PERIODS from the
    # landmarks — the founder filed his birth and "Childhood" still read
    # `undated`, because `build_bands` reads only a band's own `date`. The pass
    # runs moments → bands → moments, so an era dated by its own first moment
    # immediately bounds the rest of them.
    try:
        cross_dating_report = cross_dating.cross_date(
            event_lineup=event_lineup,
            unplaced_events=unplaced_events,
            periods=periods,
            entity_lineup=entity_lineup,
            anchors=anchors,
            birth_date=birth_date,
            # v254: continue the pre-placement phase's report so the two halves
            # of one pass report ONE set of counts.
            report=cross_dating_report,
        )
        # v207 (ADR 0026 amendment, design D3): a band the pass just dated is
        # a new anchor for the spine's order, so the ordering improves on the
        # same read the date arrives on — `derive_chrono` is a no-op when
        # nothing was derived, and re-ranking it twice is idempotent.
        if cross_dating_report["bands"]["derived"]:
            periods = derive_chrono(periods)
    except Exception:  # noqa: BLE001
        # v254: phase one already ran and its counts are true — keep them
        # rather than reporting zero for work that demonstrably happened.
        cross_dating_report = cross_dating_report if isinstance(
            cross_dating_report, dict) else {"derived": 0, "by_rule": {},
                                             "by_join": {}, "moments": []}
        cross_dating_report["bands"] = {"derived": 0, "by_rule": {},
                                        "by_join": {}, "bands": [],
                                        "observed_envelopes": 0}
    for rows_here in event_lineup.values():
        sort_period_events(rows_here)

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
    # description, or a pre-v215 mint keyed on the title and `resolve_placements`
    # could not repair it) or whose period page is gone. v215: this list is the
    # LOUD end of the placement path — `counts["stale_placements"]` carries it
    # so a host can surface "you named a date and it landed nowhere" instead of
    # a silent zero, and `counts["placements_rejoined"]` says how many the
    # repair pass rescued on this read.
    period_slugs = {p["slug"] for p in periods}
    resolved_placements = resolve_placements(placements, events)
    stale_placements = [row for row, key in resolved_placements
                        if not key or row.get("period") not in period_slugs]
    rejoined_placements = sum(1 for row, key in resolved_placements
                              if key and key != str(row.get("key") or ""))
    # v253: the pins rung 3 REFUSED to re-key, each naming its source and the
    # candidates it declined to choose between. `rejoined_placements` above
    # already counts rung 3's successes — an in-memory repair the read applies
    # immediately and `rekey_orphaned_placements` persists on the next pass.
    orphan_diagnostics = placement_orphan_diagnostics(placements, events)

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
               # v208: the union of the two disputed claims' intervals, carried
               # through so `unknown_years` reads the claims rather than the
               # rendered sentence.
               "years": contradiction.get("years"),
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
        "placement_diagnostics": orphan_diagnostics,
        "gaps_by_period": gaps_by_period,
        "global_gaps": global_gaps,
        "corroboration": corroboration,
        # v195 (ADR 0024) — additive, every one of them.
        "anchors": anchors,
        # v205 (ADR 0026): what the cross-dating pass derived on THIS read.
        "cross_dating": cross_dating_report,
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
            "events_cross_dated": int(cross_dating_report.get("derived") or 0),
            # v207: eras that were undated until the pass gave them a span.
            "periods_cross_dated": int(
                (cross_dating_report.get("bands") or {}).get("derived") or 0),
            # v215 (lifehug#228): a placement that joins nothing is never
            # silent again.
            "stale_placements": len(stale_placements),
            "placements_rejoined": rejoined_placements,
            "placements_orphaned_ambiguous": len(orphan_diagnostics),
            # eras O-E2 (Transitional dependencies): `O-C`'s withheld-stale
            # count, read through one shim — see `_stale_classifications_withheld`.
            "stale_classifications_withheld": _stale_classifications_withheld(),
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
    # v208 (ADR 0027): the placement score — the level and its margin, from one
    # arithmetic. Derivation-time, stateless, additive-with-default, and
    # guarded exactly like every other derived block here: a scoring problem
    # must never take the timeline down. Absent on failure and absent with no
    # birth landmark, which is the honest shape rather than a zero.
    try:
        score = placement_score(data)
    except Exception:  # noqa: BLE001
        score = None
    if score is not None:
        data["placement"] = score
        data["counts"]["placement_band"] = score["band"]
    # v231 (wave D item D3, plan §7): the CALCULATED timeline, additively.
    #
    # Everything above this line is the derivation that has served the Timeline
    # page since v79 — periods, moments, bands, cross-dating. Everything in
    # `data["calculated"]` is the claim substrate's own projection, PUBLISHED
    # by `publish_calculated_timeline` and merely read here. The two ride side
    # by side this wave on purpose: the published projection is what the queue
    # already consumes (`question_planner.work_items_from_projection`), so
    # exposing it on the same payload lets a surface compare the two against a
    # real vault before anything is switched over. REPLACING the derivation
    # above with the projection below is a deliberate later cutover with its
    # own contract — it is not a side effect of this key existing.
    #
    # Read, never derive: a materialized projection whose page re-derived it
    # would not be a projection. Guarded like every other derived block here,
    # and ABSENT is stated rather than faked — `published: False` is not the
    # same fact as a projection holding no nodes.
    try:
        data["calculated"] = temporal_publication.calculated_view(
            _projection_vault_root()
        )
    except Exception:  # noqa: BLE001
        data["calculated"] = dict(temporal_publication.EMPTY_VIEW)
    data["counts"]["calculated_nodes"] = data["calculated"]["counts"]["nodes"]
    data["counts"]["calculated_work_items"] = data["calculated"]["counts"]["work_items"]
    data["counts"]["projection_generation"] = data["calculated"]["projection_generation"]
    # O-E0c (lifehug-platform#686): the posture is only real if a host can
    # PROVE it held. `conversation_delivery._file_placement` logs a refusal
    # to the vault's own learning-failures ledger through the same
    # `_diagnostic` every other filing failure uses; this counts them back
    # out, so a `period_bound` answer that was refused rather than misfiled
    # is visible on the very page that would otherwise show it landed
    # nowhere. Guarded like every other derived block here: a ledger problem
    # must never take the timeline down.
    data["diagnostics"] = _place_refusal_diagnostics()
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
