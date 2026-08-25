#!/usr/bin/env python3
"""Timeline corroboration from connector date evidence (v110, issue #44;
calibrated v111 against live data).

Connector excavations harvest ``{date, entity, kind, message_id}`` assertions
from institutional mail (``state/connectors/<name>_date_evidence.json``) — the
utility-bill rule: content ignored, date + institution kept. This module lines
those assertions up against the assembled timeline, ZERO AI and read-only:

- an evidence entity matches a PERIOD when one of the period's name/slug/alias
  token sets is a subset of the entity's tokens — the same token-subset
  discipline as the connector scorer (entity "asu" matches the period whose
  roster alias is "ASU");
- an entity matches an EVENT only when the entity's tokens are a subset of the
  event's DESCRIPTION tokens (v111: eras and when_hint no longer attach
  entities — "Born in Redlands" must not carry an asu badge).

What it computes:

- a compact corroboration badge per period and per event, WINDOWED (v111):
  only records inside the memory window count — the event's when_hint year(s),
  else its placement period's stated ``approximate_dates`` (roster or page
  frontmatter); for periods, the stated range itself. Alumni mail spanning
  2010–2026 therefore badges as the in-window cluster (``asu ×43 ·
  2011–2012``), never the entity's full span. With no window the badge shows
  the full range but is context-only (status neutral). Counts are PER MATCHED
  ENTITY, never global totals; dominant entities first, display capped.
- DATE CONTRADICTIONS: description-matched evidence with ZERO records inside
  the memory window, at least MIN_CONTRADICTION_RECORDS matched, clustering in
  a tight span (≤ MAX_CONTRADICTION_SPAN_YEARS years) — email says 2003,
  memory says 2004. Diffuse out-of-window records are not a date claim about
  the moment and never contradict. Contradictions are SURFACED — as
  ``date_contradiction`` gap entries on the timeline and as question
  candidates appended by the connector excavation — never auto-applied.
  Memory is never silently overwritten.

Absent evidence (repos without connectors) is a clean no-op: ``available`` is
False, nothing is attached to periods/events, and every render is byte-for-
byte what it was before.
"""

from __future__ import annotations

import hashlib
import re
import sys
from pathlib import Path

_SYSTEM_DIR = Path(__file__).resolve().parent
if str(_SYSTEM_DIR) not in sys.path:
    sys.path.insert(0, str(_SYSTEM_DIR))

from lifehug_core import read_json
from connectors.scoring import text_tokens, tokens_known

# A single stray record is noise; a contradiction needs a small CLUSTER of
# matched records disagreeing with the story.
MIN_CONTRADICTION_RECORDS = 2

# ...and that cluster must be TIGHT: out-of-window records spanning more
# years than this are a diffuse stream (alumni mail never stops), not a date
# claim about the moment, so they can never contradict it.
MAX_CONTRADICTION_SPAN_YEARS = 5

# Display cap: dominant entities summarize as count + range, the rest fold
# into "+ N more".
BADGE_MAX_ENTITIES = 3

_YEAR_RE = re.compile(r"\b(?:19|20)\d{2}\b")
_DATE_RE = re.compile(r"^(\d{4})-\d{2}-\d{2}$")
_EVIDENCE_SUFFIX = "_date_evidence.json"


# ---------------------------------------------------------------------------
# Evidence loading / normalization.
# ---------------------------------------------------------------------------

def _normalize_evidence(items: list[dict], default_connector: str = "") -> list[dict]:
    """Validate raw {date, entity, kind, message_id} assertions and precompute
    year + entity tokens. Malformed rows (bad date, empty/untokenizable
    entity) are dropped, never matched."""
    out: list[dict] = []
    for item in items or []:
        if not isinstance(item, dict):
            continue
        date = str(item.get("date") or "")
        match = _DATE_RE.match(date)
        entity = str(item.get("entity") or "").strip()
        entity_tokens = text_tokens(entity)
        if not match or not entity or not entity_tokens:
            continue
        out.append({
            "date": date,
            "year": int(match.group(1)),
            "entity": entity,
            "entity_tokens": entity_tokens,
            "kind": str(item.get("kind") or ""),
            "message_id": str(item.get("message_id") or ""),
            "connector": str(item.get("connector") or default_connector),
        })
    out.sort(key=lambda e: (e["date"], e["entity"], e["message_id"]))
    return out


def load_evidence(connectors_dir) -> list[dict]:
    """Every connector's date-evidence assertions merged, each stamped with
    its connector name. Missing/corrupt files contribute nothing."""
    out: list[dict] = []
    directory = Path(connectors_dir)
    if not directory.exists():
        return out
    for path in sorted(directory.glob(f"*{_EVIDENCE_SUFFIX}")):
        connector = path.name[: -len(_EVIDENCE_SUFFIX)]
        data = read_json(path, default=None) or {}
        out.extend(_normalize_evidence(data.get("evidence") or [], connector))
    out.sort(key=lambda e: (e["date"], e["entity"], e["message_id"]))
    return out


# ---------------------------------------------------------------------------
# Year helpers.
# ---------------------------------------------------------------------------

def _years_in(text) -> set[int]:
    return {int(y) for y in _YEAR_RE.findall(str(text or ""))}


def _stated_range(text) -> tuple[int, int] | None:
    """A period's approximate_dates as (first, last) year, from whatever
    years the string carries ('2010–2013' → (2010, 2013))."""
    years = sorted(_years_in(text))
    return (years[0], years[-1]) if years else None


def _period_range(period: dict) -> tuple[int, int] | None:
    """A period's memory window: the DATE RECORD first (v195, ADR 0024), then
    the legacy `approximate_dates` string.

    Before v195 `approximate_dates` had no writer, so this window was almost
    always absent and every badge fell back to "context-only". A period that
    now carries a real `chronology.DateRecord` gets the window it always
    should have had; everything else behaves exactly as it did.
    """
    import chronology as chrono  # noqa: PLC0415

    record = chrono.from_dict(period.get("date")) if period.get("date") is not None else None
    if record is not None:
        first = chrono.year_of(record)
        last = chrono.year_of(record, end=True)
        if first is not None and last is not None:
            return (first, last)
    return _stated_range(period.get("approximate_dates"))


def _span_text(first: int, last: int) -> str:
    return f"{first}–{last}" if first != last else str(first)


def _year_span(items: list[dict]) -> tuple[int, int]:
    years = [i["year"] for i in items]
    return min(years), max(years)


def _in_window(items: list[dict], *, years: set[int] | None = None,
               stated: tuple[int, int] | None = None) -> list[dict]:
    """Records inside the memory window: exact when_hint year(s) when given,
    else the inclusive stated range of the placement period."""
    if years:
        return [i for i in items if i["year"] in years]
    if stated:
        return [i for i in items if stated[0] <= i["year"] <= stated[1]]
    return []


# ---------------------------------------------------------------------------
# Matching (the connector scorer's token-subset discipline).
# ---------------------------------------------------------------------------

def _period_token_sets(period: dict) -> list[set[str]]:
    names = [period.get("name", ""), period.get("slug", ""),
             *(period.get("aliases") or [])]
    token_sets = []
    for raw in names:
        tokens = text_tokens(raw)
        if tokens:
            token_sets.append(tokens)
    return token_sets


# ---------------------------------------------------------------------------
# Badges.
# ---------------------------------------------------------------------------

def _badge(matched: list[dict]) -> dict:
    """One compact badge over matched records: total count + per-entity
    count/span, dominant entities first. Counts are PER MATCHED ENTITY —
    the badge never reports ledger-global totals."""
    by_entity: dict[str, list[dict]] = {}
    for item in matched:
        by_entity.setdefault(item["entity"], []).append(item)
    entities = []
    for entity, items in by_entity.items():
        years = [i["year"] for i in items]
        entities.append({"entity": entity, "count": len(items),
                         "first": min(years), "last": max(years)})
    entities.sort(key=lambda e: (-e["count"], e["entity"]))
    years = [i["year"] for i in matched]
    return {"count": len(matched), "entities": entities,
            "first": min(years), "last": max(years), "status": "neutral"}


def badge_text(badge: dict, max_entities: int = BADGE_MAX_ENTITIES) -> str:
    """Compact display form: 'asu ×1100 · 2010–2013, mit ×42 · 2014 + 2 more'
    — dominant entities summarize as count + range, capped at a few."""
    parts = []
    for ent in badge["entities"][:max_entities]:
        parts.append(f"{ent['entity']} ×{ent['count']} · "
                     f"{_span_text(ent['first'], ent['last'])}")
    more = len(badge["entities"]) - max_entities
    text = ", ".join(parts)
    if more > 0:
        text += f" + {more} more"
    return text


def _content_key(source: str, description: str) -> str:
    """Same content-key recipe as timeline.placement_key (kept local so this
    module never imports the timeline — the timeline imports us)."""
    payload = f"{source}\n{description}"
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()[:12]


_CONTRADICTION_HINT = ("Answer to resolve it — your story is never silently "
                       "overwritten. The conflict also becomes a question "
                       "candidate on the next connector excavation.")


def _contradiction(level, *, period, key, entity, description, source,
                   connector, memory_says, evidence_says, evidence_count,
                   message, candidate_text, years=None):
    return {
        "kind": "date_contradiction",
        # v208 (ADR 0027): the UNION of the two disputed claims' intervals —
        # the honest width of a contradiction is everything both accounts
        # between them allow. Computed where the claims are; `unknown_years`
        # reads it and never re-derives it from the rendered sentences.
        "years": list(years) if years else None,
        "level": level,
        "period": period,
        "key": key,
        "entity": entity,
        "description": description,
        "source": source,
        "connector": connector,
        "memory_says": memory_says,
        "evidence_says": evidence_says,
        "evidence_count": evidence_count,
        "message": message,
        "hint": _CONTRADICTION_HINT,
        "candidate_text": candidate_text,
    }


# ---------------------------------------------------------------------------
# The computation.
# ---------------------------------------------------------------------------

def corroborate(periods: list[dict],
                event_lineup: dict[str, list[dict]],
                unplaced_events: list[dict],
                connectors_dir,
                evidence: list[dict] | None = None) -> dict:
    """Match connector date evidence against periods and events.

    ATTACHES a 'corroboration' badge dict onto matched periods/events with
    in-window records (the same in-place enrichment place_events already
    uses) and returns the summary timeline_data() exposes: {available,
    total, contradictions}. `evidence` overrides the on-disk files (the
    excavation passes its freshly extracted assertions so candidates never
    lag a run). No evidence → {'available': False} and NOTHING is attached."""
    if evidence is None:
        items = load_evidence(connectors_dir)
    else:
        items = _normalize_evidence(evidence)
    summary: dict[str, object] = {
        "available": bool(items),
        "total": len(items),
        "contradictions": [],
    }
    if not items:
        return summary

    # Group records by entity token set once — matching then runs per unique
    # entity, not per record (thousands of records, tens of entities).
    groups: dict[frozenset, list[dict]] = {}
    for item in items:
        groups.setdefault(frozenset(item["entity_tokens"]), []).append(item)

    stated_ranges = {p["slug"]: _period_range(p) for p in periods}
    period_names = {p["slug"]: p["name"] for p in periods}
    contradictions: list[dict] = summary["contradictions"]

    # --- periods: entity tokens ⊇ some period name/slug/alias token set ----
    for period in periods:
        token_sets = _period_token_sets(period)
        matched = [item for tokens, records in groups.items()
                   if tokens_known(tokens, token_sets) for item in records]
        if not matched:
            continue
        stated = stated_ranges[period["slug"]]
        if not stated:
            # No stated range: full-range badge, context-only.
            period["corroboration"] = _badge(matched)
            continue
        in_window = _in_window(matched, stated=stated)
        if in_window:
            badge = _badge(in_window)
            badge["status"] = "corroborated"
            period["corroboration"] = badge
            continue
        first, last = _year_span(matched)
        if (len(matched) >= MIN_CONTRADICTION_RECORDS
                and last - first <= MAX_CONTRADICTION_SPAN_YEARS):
            dominant = _badge(matched)["entities"][0]
            memory_says = _span_text(*stated)
            evidence_says = _span_text(first, last)
            contradictions.append(_contradiction(
                "period",
                years=[min(stated[0], first), max(stated[1], last)],
                period=period["slug"],
                key=f"period-{period['slug']}",
                entity=dominant["entity"],
                description=period["name"],
                source="",
                connector=matched[0]["connector"],
                memory_says=memory_says,
                evidence_says=evidence_says,
                evidence_count=len(matched),
                message=(f"✉ Date conflict: {dominant['entity']} email records span "
                         f"{evidence_says}, outside {period['name']}'s stated dates "
                         f"({memory_says})."),
                candidate_text=(f"Email records from {dominant['entity']} span "
                                f"{evidence_says}, but your \"{period['name']}\" period "
                                f"is dated {memory_says} — which is right?"),
            ))

    # --- events: entity tokens ⊆ the event's DESCRIPTION tokens (v111) -----
    placed = [(slug, event) for slug, rows in event_lineup.items() for event in rows]
    for slot, event in placed + [(None, e) for e in unplaced_events]:
        tokens = text_tokens(event.get("description", ""))
        matched = [item for group_tokens, records in groups.items()
                   if tokens and group_tokens <= tokens for item in records]
        if not matched:
            continue
        hint_years = _years_in(event.get("when_hint"))
        stated = stated_ranges.get(slot) if slot else None
        if not hint_years and not stated:
            # No window: full-range badge, context-only — NEVER a contradiction.
            event["corroboration"] = _badge(matched)
            continue
        in_window = _in_window(matched, years=hint_years or None, stated=stated)
        if in_window:
            badge = _badge(in_window)
            badge["status"] = "corroborated"
            event["corroboration"] = badge
            continue
        # Zero records inside the memory window. A contradiction needs the
        # out-of-window records to form a tight cluster (rule C); out-of-window
        # records never badge the moment either way.
        first, last = _year_span(matched)
        if not (len(matched) >= MIN_CONTRADICTION_RECORDS
                and last - first <= MAX_CONTRADICTION_SPAN_YEARS):
            continue
        evidence_says = _span_text(first, last)
        description = event["description"]
        if hint_years:
            memory_says = "/".join(str(y) for y in sorted(hint_years))
            story_bit = f"your story says {memory_says}"
            memory_span = (min(hint_years), max(hint_years))
        else:
            memory_says = _span_text(*stated)
            story_bit = (f"your story places it in {period_names.get(slot, slot)} "
                         f"({memory_says})")
            memory_span = stated
        contradictions.append(_contradiction(
            "event",
            years=[min(memory_span[0], first), max(memory_span[1], last)],
            period=slot,
            key=f"event-{_content_key(event.get('source', ''), description)}",
            entity=_badge(matched)["entities"][0]["entity"],
            description=description,
            source=event.get("source", ""),
            connector=matched[0]["connector"],
            memory_says=memory_says,
            evidence_says=evidence_says,
            evidence_count=len(matched),
            message=(f"✉ Date conflict: email records place \"{description}\" in "
                     f"{evidence_says}, but {story_bit}."),
            candidate_text=(f"Email records place \"{description}\" in "
                            f"{evidence_says} but {story_bit} — which is right?"),
        ))
    return summary
