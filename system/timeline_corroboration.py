#!/usr/bin/env python3
"""Timeline corroboration from connector date evidence (v110, issue #44).

Connector excavations harvest ``{date, entity, kind, message_id}`` assertions
from institutional mail (``state/connectors/<name>_date_evidence.json``) — the
utility-bill rule: content ignored, date + institution kept. This module lines
those assertions up against the assembled timeline, ZERO AI and read-only:

- an evidence entity matches a PERIOD when one of the period's name/slug/alias
  token sets is a subset of the entity's tokens — the same token-subset
  discipline as the connector scorer (entity "asu" matches the period whose
  roster alias is "ASU");
- an entity matches an EVENT when the entity's tokens are a subset of the
  event's OWN text tokens (description + when_hint + era words).

What it computes:

- a compact corroboration badge per period and per event — per-entity counts
  with the matched year span, dominant entities first (``asu ×1100 ·
  2010–2013``), the display capped at a few entities. Counts are PER MATCHED
  ENTITY, never global totals;
- DATE CONTRADICTIONS: matched evidence clustering in a different year than
  the author's own time words (email says 2003, memory says 2004), or
  concentrated outside a period's stated ``approximate_dates``. Contradictions
  are SURFACED — as ``date_contradiction`` gap entries on the timeline and as
  question candidates appended by the connector excavation — never
  auto-applied. Memory is never silently overwritten.

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


def _span_text(first: int, last: int) -> str:
    return f"{first}–{last}" if first != last else str(first)


def _ranges_overlap(a: tuple[int, int], b: tuple[int, int]) -> bool:
    return not (a[1] < b[0] or a[0] > b[1])


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


def _event_tokens(event: dict) -> set[str]:
    text = " ".join([event.get("description", ""), event.get("when_hint", ""),
                     *(event.get("eras") or [])])
    return text_tokens(text)


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
                   message, candidate_text):
    return {
        "kind": "date_contradiction",
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

    ATTACHES a 'corroboration' badge dict onto each matched period/event (the
    same in-place enrichment place_events already uses) and returns the
    summary timeline_data() exposes: {available, total, contradictions}.
    `evidence` overrides the on-disk files (the excavation passes its freshly
    extracted assertions so candidates never lag a run). No evidence →
    {'available': False} and NOTHING is attached."""
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

    stated_ranges = {p["slug"]: _stated_range(p.get("approximate_dates"))
                     for p in periods}
    period_names = {p["slug"]: p["name"] for p in periods}
    contradictions: list[dict] = summary["contradictions"]

    # --- periods: entity tokens ⊇ some period name/slug/alias token set ----
    for period in periods:
        token_sets = _period_token_sets(period)
        matched = [item for tokens, records in groups.items()
                   if tokens_known(tokens, token_sets) for item in records]
        if not matched:
            continue
        badge = _badge(matched)
        stated = stated_ranges[period["slug"]]
        if stated:
            overlap = _ranges_overlap((badge["first"], badge["last"]), stated)
            badge["status"] = "corroborated" if overlap else "contradiction"
        period["corroboration"] = badge
        if (badge["status"] == "contradiction"
                and badge["count"] >= MIN_CONTRADICTION_RECORDS):
            dominant = badge["entities"][0]
            memory_says = _span_text(*stated)
            evidence_says = _span_text(badge["first"], badge["last"])
            contradictions.append(_contradiction(
                "period",
                period=period["slug"],
                key=f"period-{period['slug']}",
                entity=dominant["entity"],
                description=period["name"],
                source="",
                connector=matched[0]["connector"],
                memory_says=memory_says,
                evidence_says=evidence_says,
                evidence_count=badge["count"],
                message=(f"✉ Date conflict: {dominant['entity']} email records span "
                         f"{evidence_says}, outside {period['name']}'s stated dates "
                         f"({memory_says})."),
                candidate_text=(f"Email records from {dominant['entity']} span "
                                f"{evidence_says}, but your \"{period['name']}\" period "
                                f"is dated {memory_says} — which is right?"),
            ))

    # --- events: entity tokens ⊆ the event's own text tokens ---------------
    placed = [(slug, event) for slug, rows in event_lineup.items() for event in rows]
    for slot, event in placed + [(None, e) for e in unplaced_events]:
        tokens = _event_tokens(event)
        matched = [item for group_tokens, records in groups.items()
                   if tokens and group_tokens <= tokens for item in records]
        if not matched:
            continue
        badge = _badge(matched)
        hint_years = _years_in(event.get("when_hint"))
        evidence_years = {i["year"] for i in matched}
        stated = stated_ranges.get(slot) if slot else None
        memory_says = ""
        if hint_years:
            if hint_years & evidence_years:
                badge["status"] = "corroborated"
            elif badge["count"] >= MIN_CONTRADICTION_RECORDS:
                badge["status"] = "contradiction"
                memory_says = "/".join(str(y) for y in sorted(hint_years))
        elif stated:
            overlap = _ranges_overlap((badge["first"], badge["last"]), stated)
            badge["status"] = "corroborated" if overlap else "contradiction"
            if not overlap and badge["count"] >= MIN_CONTRADICTION_RECORDS:
                memory_says = _span_text(*stated)
        event["corroboration"] = badge
        if badge["status"] == "contradiction" and memory_says:
            evidence_says = _span_text(badge["first"], badge["last"])
            description = event["description"]
            if hint_years:
                story_bit = f"your story says {memory_says}"
            else:
                story_bit = (f"your story places it in {period_names.get(slot, slot)} "
                             f"({memory_says})")
            contradictions.append(_contradiction(
                "event",
                period=slot,
                key=f"event-{_content_key(event.get('source', ''), description)}",
                entity=badge["entities"][0]["entity"],
                description=description,
                source=event.get("source", ""),
                connector=matched[0]["connector"],
                memory_says=memory_says,
                evidence_says=evidence_says,
                evidence_count=badge["count"],
                message=(f"✉ Date conflict: email records place \"{description}\" in "
                         f"{evidence_says}, but {story_bit}."),
                candidate_text=(f"Email records place \"{description}\" in "
                                f"{evidence_says} but {story_bit} — which is right?"),
            ))
    return summary
