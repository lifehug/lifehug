#!/usr/bin/env python3
"""Lifehug — the weekly arc planner (issue #118, Conversation Interaction Wave 2).

The daily Chat's ~3 exchanges used to be three unrelated questions. This
module plans, once a week, ONE **arc card** per queued question — an opening
framing plus 2–4 follow-up *intents* (not scripted text) — so the daily loop
merely ATTACHES a card that already exists. That split is the ratified
deviation from design decision C: arc GENERATION lives in the weekly loop
precisely so the daily loop stays AI-FREE by construction (``arc-card
--daily-text`` is a pure file read).

The spec this implements is ``interactions/conversation/plan/arc-templates.md``
(read verbatim into the model prompt via
``conversation.read_conversation_definition``); the card schema below is the
authority the store helpers in ``conversation.py`` defer to (their mid-flight
amendment M1).

``state/arc_cards.json``::

    {
      "version": 1,
      "generated_at": "...",
      "queue_generated_at": "<question_queue.json generated_at verbatim>",
      "expires_at":        "<question_queue.json expires_at verbatim>",
      "source": "model | deterministic | mixed",
      "cards": [
        {
          "question_id": "A14",
          "opening": "one context sentence drawn from the record, or null",
          "opening_receipts": ["A7", "sources/manual/2026-03-01-ghana.md"],
          "intents": [{"kind": "<one of ARC_INTENT_KINDS>", ...}],
          "planned_at": "...",
          "planner": "model | deterministic"
        }
      ],
      "thread_offers": [{"neighborhood_id": "...", "offered_at": "...", "month": "2026-08"}]
    }

Binding rules:

- The intent ``kind`` vocabulary is CLOSED — ``conversation.ARC_INTENT_KINDS``
  is the single definition (the turn engine, the evals, and the platform all
  inherit it); adding a kind is a schema bump.
- 2–4 intents per card. The deterministic pass may emit fewer (minimum 1) but
  never zero cards for a queued question.
- ``opening`` is nullable. When present it obeys research.md §1's two-sentence
  rule (one context sentence from the author's own record, then the question)
  and every id/path in ``opening_receipts`` must resolve on disk — an opening
  citing a receipt that does not exist is dropped to null and the card
  survives (session honesty: never fabricate memory).
- No card text may contain "what year" (case-insensitive) — research.md §4's
  landmark-anchor rule, enforced as a validation lint.
- Cards live and die WITH the queue: ``expires_at`` is copied verbatim, and a
  card is "live" only while unexpired AND its question is still in the current
  queue. Stale-plan fallback therefore needs no code — ``ask.py`` falls back to
  the rotation pick, nothing attaches, and the day degrades to today's format.

Every vault read/write goes through ``vault_paths``; the planner never sends a
message and imports no AI provider at module scope.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import conversation
from lifehug_core import (
    REPO_DIR,
    SYSTEM_DIR,
    load_config,
    now_utc,
    split_frontmatter,
    write_json,
    write_text,
)
from vault_paths import read_vault_text, vault_data_path

# The closed intent vocabulary has exactly one definition (recurring-defect
# doctrine): conversation.py's, shared with the store and the turn engine.
INTENT_KINDS = conversation.ARC_INTENT_KINDS

#: Timeline gap kinds this planner turns into conversation input. The other
#: kinds compute_gaps() emits (no_chrono, thin_lineup, unplaced_entities,
#: date_contradiction) stay display-only — they name a curation chore, not a
#: question the author can answer.
CONSUMED_GAP_KINDS = ("no_events", "all_undated", "unplaced_events")

MIN_INTENTS = 1          # deterministic floor — a card with one intent is still a card
TARGET_MIN_INTENTS = 2   # design §1 target band …
MAX_INTENTS = 4          # … 2–4 intents per card

#: The timeline whispers (the wiki-harvest precedent): at most one timeline_gap
#: intent per card, and this many across the whole week.
#:
#: v200: `place_no_stories` is counted within this SAME number and takes the
#: same one-slot-per-card. There is deliberately no second dial — the two kinds
#: are the only intents that carry a real ask, they compete for the same turn,
#: and the whole point of the cap is "how often may a conversation be asked to
#: carry a second agenda", which is one question, not two.
DEFAULT_GAP_MAX = 3

#: Monthly conversation-thread offers, and how long an offered neighborhood
#: stays quiet afterwards (a quarter — the second-voice never-repeat precedent,
#: scoped lighter).
DEFAULT_THREAD_OFFERS = 1
THREAD_OFFER_QUIET_DAYS = 92

#: research.md §4, hard: landmark anchors, never a demand for a calendar year.
#:
#: v195 (ADR 0024) widened STORAGE — the timeline now holds real dates as
#: intervals with a basis — and deliberately did NOT widen ASKING. This ban
#: stays exactly as it was, and the `timeline` child interaction's
#: `timeline_gates.no_year_opener` lint enforces the same rule inside the
#: conversation. `test_the_year_demand_patterns_cover_the_planners_banned_
#: phrase` pins the two together, so they can never become two rules.
BANNED_PHRASE = "what year"

DEFAULT_MODEL_FALLBACK = "claude-sonnet-5"  # classify_story.DEFAULT_MODEL, resolved lazily


class ArcPlanError(Exception):
    """A planning input or an ingested response was unusable."""


# ---------------------------------------------------------------------------
# Vault I/O — every path resolves through vault_paths, with a vault_root
# override so tests point at a synthetic vault without rebinding the process.
# ---------------------------------------------------------------------------


def _resolve_root(vault_root: str | Path | None) -> Path:
    return REPO_DIR if vault_root is None else Path(vault_root)


def _data_path(name: str, root: Path) -> Path:
    return vault_data_path(name, vault_root=root, framework_system_dir=SYSTEM_DIR)


def _read_json(path: Path, root: Path, default):
    try:
        text = read_vault_text(path, vault_root=root)
    except (FileNotFoundError, OSError):
        return default
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return default


def _read_text(path: Path, root: Path) -> str:
    try:
        return read_vault_text(path, vault_root=root)
    except (FileNotFoundError, OSError):
        return ""


def load_queue(*, vault_root: str | Path | None = None) -> dict:
    """``state/question_queue.json`` as written by question_planner.build_queue."""
    root = _resolve_root(vault_root)
    data = _read_json(_data_path("question_queue", root), root, {})
    return data if isinstance(data, dict) else {}


def queued_items(queue: dict, *, limit: int | None = None,
                 statuses: tuple[str, ...] = ("queued",)) -> list[dict]:
    """Queue items in queue order, filtered by status."""
    items = queue.get("queue")
    if not isinstance(items, list):
        return []
    rows = [item for item in items
            if isinstance(item, dict)
            and str(item.get("status", "queued")) in statuses
            and item.get("question_id")]
    return rows[:limit] if limit else rows


def _parse_time(value: object) -> datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        moment = datetime.fromisoformat(raw[:-1] + "+00:00" if raw.endswith("Z") else raw)
    except ValueError:
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# Material collection — the gap seams this planner claims. Every collector is
# individually guarded: a missing/oddly-shaped source silently contributes no
# intents (the book/chapter-boost precedent) rather than costing the week its
# cards.
# ---------------------------------------------------------------------------


def _five_slots() -> tuple[str, ...]:
    """book.FIVE_SLOTS — the classifier's slot NAMES have one definition.

    A name mismatch here reads as permanently-empty slots (book.py's own
    header warns about exactly this), so the names are imported, never
    retyped; tests/test_arc_planner.py pins the parity.
    """
    try:
        import book  # noqa: PLC0415
        slots = tuple(str(slot) for slot in book.FIVE_SLOTS)
        return slots
    except Exception:  # noqa: BLE001 — an unavailable book module is a silent no-op
        return ()


def collect_scene_slots(*, vault_root: str | Path | None = None) -> dict[str, dict[str, bool]]:
    """``{question_id: {slot: filled}}`` from the classifier's scene_slots stamp.

    Same read as ``book._load_scene_slots`` (classifications keyed by
    ``source_path`` "answers/<QID>.md"), honoring a vault_root override so a
    synthetic fixture vault works without rebinding the process.
    """
    slots = _five_slots()
    if not slots:
        return {}
    root = _resolve_root(vault_root)
    directory = _data_path("classifications", root)
    if not directory.exists():
        return {}
    out: dict[str, dict[str, bool]] = {}
    for path in sorted(directory.glob("*.json")):
        data = _read_json(path, root, {})
        if not isinstance(data, dict):
            continue
        source = str(data.get("source_path", "")).strip()
        if not source.startswith("answers/") or not source.endswith(".md"):
            continue
        stamped = data.get("scene_slots") or {}
        if not isinstance(stamped, dict):
            continue
        out[Path(source).stem] = {slot: bool(stamped.get(slot)) for slot in slots}
    return out


def collect_timeline_gaps(*, payload: dict | None = None) -> list[dict]:
    """The consumed-kind gaps, read from ``timeline.timeline_data()``'s payload.

    This is the FIRST non-display consumer of ``timeline.compute_gaps()`` — and
    it consumes the ASSEMBLED payload rather than re-deriving gap logic, so the
    two views can never disagree about what a gap is. ``payload`` may be
    injected (tests assemble one with the real compute_gaps); otherwise the
    real timeline is assembled, guarded.
    """
    if payload is None:
        try:
            import timeline  # noqa: PLC0415
            payload = timeline.timeline_data()
        except Exception:  # noqa: BLE001 — no timeline is a silent no-op
            return []
    if not isinstance(payload, dict):
        return []
    gaps: list[dict] = []
    by_period = payload.get("gaps_by_period")
    if isinstance(by_period, dict):
        for rows in by_period.values():
            if isinstance(rows, list):
                gaps.extend(row for row in rows if isinstance(row, dict))
    global_gaps = payload.get("global_gaps")
    if isinstance(global_gaps, list):
        gaps.extend(row for row in global_gaps if isinstance(row, dict))
    consumed = [gap for gap in gaps if str(gap.get("kind")) in CONSUMED_GAP_KINDS]
    # v196: each consumed gap carries the LEVERAGE of the best anchor that
    # would resolve it, and the keystone row behind that anchor when there is
    # one. This is what makes whispers leverage-ranked instead of
    # era-affinity-ranked — the same number `build_timeline_plan` computes,
    # read from the assembled payload so the two can never disagree.
    return _with_leverage(consumed, payload)


def _with_leverage(gaps: list[dict], payload: dict) -> list[dict]:
    """Stamp `leverage` and the resolving `keystone` row on each gap."""
    try:
        import timeline  # noqa: PLC0415

        index = timeline.dependency_index(payload)
        keystones = {str(row.get("anchor")): row
                     for row in (payload.get("keystones") or []) if isinstance(row, dict)}
    except Exception:  # noqa: BLE001 — a timeline problem is a silent no-op
        return gaps
    best: dict[str, tuple[int, str]] = {}
    for anchor_key, resolved in index.items():
        for unknown_key in resolved or ():
            current = best.get(unknown_key)
            if current is None or len(resolved) > current[0]:
                best[unknown_key] = (len(resolved), anchor_key)
    try:
        import timeline_interaction  # noqa: PLC0415

        anchors = timeline_interaction.anchor_rows_for_prompt(payload.get("anchors") or ())
    except Exception:  # noqa: BLE001
        anchors = []
    stamped = []
    for gap in gaps:
        row = dict(gap)
        row["anchors"] = anchors
        try:
            key = timeline.unknown_key(gap)
        except Exception:  # noqa: BLE001
            key = ""
        leverage, anchor_key = best.get(key, (0, ""))
        row["unknown_key"] = key
        row["leverage"] = int(leverage)
        row["anchor"] = anchor_key
        if anchor_key in keystones:
            row["keystone"] = keystones[anchor_key]
        stamped.append(row)
    return stamped


def collect_places_without_stories(*, payload: dict | None = None) -> list[dict]:
    """The places the person named that have nothing in them (v200).

    Read off the SAME assembled `timeline.timeline_data()` payload
    `collect_timeline_gaps` reads, at `payload["place_no_stories"]`, so the
    planner and the Timeline surface can never disagree about what a place with
    no stories is. `timeline_data()` already computes the rows guarded (a
    landmark problem degrades to `[]`), and this read is guarded again for the
    injected-payload path.
    """
    if payload is None:
        try:
            import timeline  # noqa: PLC0415
            payload = timeline.timeline_data()
        except Exception:  # noqa: BLE001 — no timeline is a silent no-op
            return []
    if not isinstance(payload, dict):
        return []
    rows = payload.get("place_no_stories")
    if not isinstance(rows, list):
        return []
    return [row for row in rows if isinstance(row, dict) and str(row.get("label") or "").strip()]


def collect_sit_with(*, vault_root: str | Path | None = None) -> list[str]:
    """The Mirror's "## Sit with" lines (exactly 3 by mirror.py's contract)."""
    root = _resolve_root(vault_root)
    page = _data_path("wiki", root) / "self" / "mirror.md"
    body = _read_text(page, root)
    if "## Sit with" not in body:
        return []
    tail = body.split("## Sit with", 1)[1].split("\n## ", 1)[0]
    lines: list[str] = []
    for raw in tail.splitlines():
        stripped = raw.strip()
        if not stripped:
            continue
        cleaned = re.sub(r"^([-*]|\d+\.)\s+", "", stripped)
        if cleaned != stripped:
            lines.append(cleaned.strip())
    return lines[:3]


def collect_neighborhoods(*, vault_root: str | Path | None = None) -> dict:
    """Sibling material: which neighborhood a question sits in, and its pending
    siblings (promotable candidates sharing the neighborhood_id).

    Returns ``{"by_question": {qid: nid}, "siblings": {nid: [candidate, ...]},
    "neighborhoods": [...]}``.
    """
    root = _resolve_root(vault_root)
    neighborhoods = _read_json(_data_path("neighborhoods", root), root, {})
    candidates = _read_json(_data_path("question_candidates", root), root, {})
    rows = neighborhoods.get("neighborhoods") if isinstance(neighborhoods, dict) else None
    rows = [row for row in rows if isinstance(row, dict)] if isinstance(rows, list) else []
    cand_rows = candidates.get("candidates") if isinstance(candidates, dict) else None
    cand_rows = [row for row in cand_rows if isinstance(row, dict)] if isinstance(cand_rows, list) else []

    try:
        from question_candidates import PROMOTABLE_STATUSES  # noqa: PLC0415
        promotable = set(PROMOTABLE_STATUSES)
    except Exception:  # noqa: BLE001
        promotable = {"candidate", "accepted", "deferred"}

    by_id = {str(row.get("id")): row for row in cand_rows if row.get("id")}
    by_question: dict[str, str] = {}
    for neighborhood in rows:
        nid = str(neighborhood.get("id") or "")
        if not nid:
            continue
        for slot in neighborhood.get("arc") or []:
            if not isinstance(slot, dict):
                continue
            raw_id = str(slot.get("question_id") or "").strip()
            if not raw_id:
                continue
            by_question[raw_id] = nid
            promoted = str(by_id.get(raw_id, {}).get("promoted_question_id") or "").strip()
            if promoted:
                by_question[promoted] = nid

    siblings: dict[str, list[dict]] = {}
    for candidate in cand_rows:
        nid = str(candidate.get("neighborhood_id") or "")
        if not nid or str(candidate.get("status", "candidate")) not in promotable:
            continue
        siblings.setdefault(nid, []).append(candidate)
    return {"by_question": by_question, "siblings": siblings, "neighborhoods": rows}


def collect_answers(*, vault_root: str | Path | None = None) -> dict:
    """Answered material on record: ids per category, bodies, and answered dates.

    Category is the answer id's leading letter(s) — the same convention the
    question bank and every state index use.
    """
    root = _resolve_root(vault_root)
    directory = _data_path("answers", root)
    ids: list[str] = []
    bodies: dict[str, str] = {}
    dates: dict[str, str] = {}
    if directory.exists():
        for path in sorted(directory.glob("*.md")):
            qid = path.stem
            text = _read_text(path, root)
            if not text:
                continue
            metadata, body = split_frontmatter(text)
            ids.append(qid)
            bodies[qid] = body.strip()
            dates[qid] = str(metadata.get("answered_date", "") or "")
    by_category: dict[str, list[str]] = {}
    for qid in ids:
        match = re.match(r"^([A-Za-z]+)", qid)
        if match:
            by_category.setdefault(match.group(1).upper(), []).append(qid)
    return {"ids": ids, "bodies": bodies, "dates": dates, "by_category": by_category}


def collect_studio_slots(items: list[dict], *, vault_root: str | Path | None = None,
                         cards: list[dict] | None = None) -> dict[str, list[dict]]:
    """Unfilled format-framework slots per focus id (guarded; silent no-op).

    ``cards`` may be injected (readiness cards as produced by
    ``format_readiness.readiness_for_focus``); otherwise they are computed for
    the focuses this week's queue actually touches.
    """
    if cards is None:
        wanted = {str(item.get("focus")) for item in items if item.get("focus")}
        if not wanted:
            return {}
        try:
            import format_readiness  # noqa: PLC0415
            import roadmap as roadmap_mod  # noqa: PLC0415
            from lifehug_core import QUESTIONS_FILE, parse_questions  # noqa: PLC0415
            questions = parse_questions(QUESTIONS_FILE.read_text(encoding="utf-8"))
            focuses = roadmap_mod.load_roadmap().get("focuses", [])
            cards = []
            for focus in focuses:
                if str(focus.get("id")) not in wanted:
                    continue
                cards.extend(format_readiness.readiness_for_focus(focus, questions))
        except Exception:  # noqa: BLE001 — no framework, no studio intents
            return {}
    out: dict[str, list[dict]] = {}
    for card in cards or []:
        if not isinstance(card, dict):
            continue
        focus_id = str(card.get("focus_id") or "")
        for slot in card.get("slots") or []:
            if not isinstance(slot, dict) or slot.get("filled"):
                continue
            out.setdefault(focus_id, []).append({
                "format": str(card.get("format") or ""),
                "slot": str(slot.get("id") or ""),
                "label": str(slot.get("label") or ""),
            })
    return out


def collect_quality_profile(*, vault_root: str | Path | None = None) -> dict:
    """quality_profile + PR6's engagement block, both read GUARDED.

    Behavioral signals order OPTIONAL intents only; they never drop a
    scene_slot, timeline_gap, or sit_with intent (owner: drain is not
    negative — pacing and framing may adapt, whether hard questions get asked
    may not).
    """
    root = _resolve_root(vault_root)
    profile = _read_json(_data_path("quality_profile", root), root, {})
    return profile if isinstance(profile, dict) else {}


def collect_material(items: list[dict], *, vault_root: str | Path | None = None,
                     timeline_payload: dict | None = None,
                     readiness_cards: list[dict] | None = None) -> dict:
    """Everything the deterministic pass and the model prompt plan against."""
    # v200: two consumers now read the assembled timeline, so assemble it ONCE
    # here rather than letting each collector re-derive it (the payload stays
    # injectable for tests exactly as before).
    if timeline_payload is None:
        try:
            import timeline  # noqa: PLC0415
            timeline_payload = timeline.timeline_data()
        except Exception:  # noqa: BLE001 — no timeline is a silent no-op
            timeline_payload = {}
    return {
        "scene_slots": collect_scene_slots(vault_root=vault_root),
        "timeline_gaps": collect_timeline_gaps(payload=timeline_payload),
        "places_without_stories": collect_places_without_stories(payload=timeline_payload),
        "sit_with": collect_sit_with(vault_root=vault_root),
        "neighborhoods": collect_neighborhoods(vault_root=vault_root),
        "answers": collect_answers(vault_root=vault_root),
        "studio_slots": collect_studio_slots(items, vault_root=vault_root, cards=readiness_cards),
        "quality": collect_quality_profile(vault_root=vault_root),
    }


# ---------------------------------------------------------------------------
# Deterministic planning — ALWAYS computed first. The model pass, when a route
# exists, replaces/enriches these cards; when it doesn't (keyless, failure,
# invalid output) these ARE the week's cards. A queued question never ends the
# week without one.
# ---------------------------------------------------------------------------


def _self_functions() -> tuple[str, ...]:
    try:
        from question_planner import SELF_FUNCTIONS  # noqa: PLC0415
        return tuple(str(fn) for fn in SELF_FUNCTIONS)
    except Exception:  # noqa: BLE001
        return ("self_image", "value", "fear", "contradiction",
                "perception_by_others", "growth_edge")


def is_self_arc(item: dict) -> bool:
    """A self-arc queue item — the SELF_ARC dimension the Mirror speaks to."""
    return str(item.get("story_function", "")) in _self_functions()


def _category_of(item: dict) -> str:
    return str(item.get("category", "")).strip().upper()


def _answered_in_category(item: dict, material: dict) -> list[str]:
    answers = material.get("answers") or {}
    by_category = answers.get("by_category") or {}
    dates = answers.get("dates") or {}
    ids = list(by_category.get(_category_of(item), []))
    # Newest first — the freshest material is the most conversational.
    return sorted(ids, key=lambda qid: (dates.get(qid, ""), qid), reverse=True)


def _scene_slot_intents(item: dict, material: dict) -> list[dict]:
    """Unfilled five-slot probes for the answered material in this category.

    "What it says about you" is the highest-value follow-up when empty
    (research.md §1), so it leads; one concrete slot follows it. With no
    classification at all every slot reads unfilled — which is the correct
    reading of a category with nothing on record yet.
    """
    slots = _five_slots()
    if not slots:
        return []
    stamped = material.get("scene_slots") or {}
    answered = _answered_in_category(item, material)
    source_qid = ""
    unfilled: list[str] = []
    for qid in answered:
        card = stamped.get(qid)
        if card is None:
            continue
        missing = [slot for slot in slots if not card.get(slot)]
        if missing:
            source_qid, unfilled = qid, missing
            break
    if not unfilled:
        # No classified material (or every slot filled on the ones we have) —
        # an unanswered category reads as all five unfilled.
        if any(stamped.get(qid) and not [s for s in slots if not stamped[qid].get(s)]
               for qid in answered):
            return []
        unfilled = list(slots)
        source_qid = answered[0] if answered else ""

    ordered: list[str] = []
    if "what_it_says_about_me" in unfilled:
        ordered.append("what_it_says_about_me")
    ordered.extend(slot for slot in unfilled if slot not in ordered)

    intents: list[dict] = []
    for slot in ordered[:2]:
        note = f"the answer's {slot.replace('_', ' ')} is not on record yet"
        if source_qid:
            note += f" (nearest material: {source_qid})"
        intent = {"kind": "scene_slot", "slot": slot, "note": note}
        if source_qid:
            intent["source_question_id"] = source_qid
        intents.append(intent)
    return intents


def _sit_with_intent(item: dict, material: dict) -> list[dict]:
    """Only for self-arc items, quoting ONE current Sit-with line verbatim.

    The conversation invites toward a tension; it never adjudicates it.
    """
    if not is_self_arc(item):
        return []
    lines = material.get("sit_with") or []
    if not lines:
        return []
    index = sum(ord(ch) for ch in str(item.get("question_id", ""))) % len(lines)
    return [{"kind": "sit_with", "text": lines[index],
             "note": "invite toward this tension; never adjudicate it"}]


def _gap_note(gap: dict) -> str:
    """Landmark-anchor phrasing, taken from the gap's own hint where it has one.

    compute_gaps already models the rule ("dates arrive as landmark anchors …
    never guessed years"); reusing its words is how this consumer inherits the
    phrasing instead of inventing a second, driftable copy.
    """
    hint = str(gap.get("hint") or "").strip()
    message = str(gap.get("message") or "").strip()
    note = hint or message or "anchor this against a landmark the author already named"
    return f"landmark-anchor phrasing — {note}"


def _timeline_gap_intent(item: dict, material: dict, used: dict) -> list[dict]:
    """At most one timeline whisper per card, capped across the week.

    v196: ordered by LEVERAGE first — the gap whose answer would place the
    most — with the item's own era as the TIEBREAK between equally leveraged
    gaps, then the playbook's own preference for a global gap over someone
    else's era. A whisper carries the real probe, the person's own anchors,
    and the identity (`tl:<anchor-slug>`) both the conversation and the host
    match on, so "the star means this exact question" is true by construction
    (lifehug/lifehug-platform#586).
    """
    if used["gaps"] >= used["gap_max"]:
        return []
    gaps = material.get("timeline_gaps") or []
    if not gaps:
        return []
    # Wave F (plan §2.3): an item presented as the main daily question must not
    # ALSO be whispered in the same interaction. The queue entry carries the
    # work-item identity of the question it is asking, and a gap's identity is
    # derived by the SAME function, so "is this the same item?" is an equality
    # check rather than a phrasing heuristic — the whole reason one id travels
    # across surfaces.
    asking = str(item.get("work_item_id") or "")
    if asking:
        gaps = [gap for gap in gaps if _gap_work_item_id(gap) != asking]
        if not gaps:
            return []
    era_hints = {str(item.get("focus") or "").lower(), _category_of(item).lower()}
    era_hints.discard("")

    def era_match(gap: dict) -> bool:
        period = str(gap.get("period") or "").lower()
        return bool(period) and any(hint and hint in period for hint in era_hints)

    def rank(gap: dict) -> tuple:
        return (
            -int(gap.get("leverage") or 0),
            0 if era_match(gap) else (1 if gap.get("period") is None else 2),
            str(gap.get("kind") or ""),
            str(gap.get("period") or ""),
        )

    for gap in sorted(gaps, key=rank):
        key = (str(gap.get("kind")), str(gap.get("period") or ""))
        if key in used["gap_keys"]:
            continue
        used["gap_keys"].add(key)
        used["gaps"] += 1
        return [_whisper_intent(gap)]
    return []


def _gap_work_item_id(gap: dict) -> str:
    """The work-item identity of one timeline gap — GUARDED, one definition.

    Delegated to `question_planner.timeline_work_item_id` rather than derived
    here: the keystone that a gap's anchor resolves and the gap itself are the
    same question, and two derivations of "the same question" is exactly the
    drift plan §2.3 exists to forbid.
    """
    try:
        from question_planner import timeline_work_item_id  # noqa: PLC0415

        return timeline_work_item_id(anchor=gap.get("anchor") or "",
                                     unknown_key=gap.get("unknown_key") or "")
    except Exception:  # noqa: BLE001 — no identity is still a valid whisper
        return ""


def _whisper_intent(gap: dict) -> dict:
    """One gap -> the arc card's timeline intent (the whisper payload).

    The probe and the anchors come from the interaction's own authority
    (`timeline_interaction.whisper_from_keystone` / `choose_probe`), never
    from a second phrasing here.
    """
    intent = {"kind": "timeline_gap", "gap_kind": str(gap.get("kind")),
              "period": gap.get("period"), "note": _gap_note(gap),
              "leverage": int(gap.get("leverage") or 0),
              "unknown_keys": [gap.get("unknown_key")] if gap.get("unknown_key") else []}
    # Wave F: the whisper carries the SAME work-item id the daily queue and
    # Timeline use, so answering it on any surface closes it on all of them.
    # Stamped BEFORE the probe work below — `whisper_from_keystone` names no
    # such field, so the keystone's payload enriches the whisper without ever
    # being able to change which item it is about.
    work_item_id = _gap_work_item_id(gap)
    if work_item_id:
        intent["work_item_id"] = work_item_id
    try:
        import timeline_interaction  # noqa: PLC0415

        keystone = gap.get("keystone")
        if isinstance(keystone, dict):
            whisper = timeline_interaction.whisper_from_keystone(keystone, gap=gap)
            if whisper:
                # The keystone's identity and probe WIN; the gap's own note and
                # kind survive underneath, so nothing that reads a v195 intent
                # loses a field.
                intent.update(whisper)
                return intent
        probe = gap.get("probe")
        if not isinstance(probe, dict):
            probe = timeline_interaction.choose_probe(
                {"kind": gap.get("kind"), "label": gap.get("message") or gap.get("period") or ""},
                anchors=gap.get("anchors") or (),
            )
        anchor = str(gap.get("anchor") or "")
        intent.update({
            "anchor": anchor,
            "question_id": timeline_interaction.keystone_question_id(anchor) if anchor else "",
            "probe": str(probe.get("text") or ""),
            "probe_step": str(probe.get("step") or ""),
            "anchors": list(gap.get("anchors") or []),
            "label": str(gap.get("message") or gap.get("period") or "this stretch"),
        })
    except Exception:  # noqa: BLE001 — a whisper without a probe is v195's intent
        return intent
    return intent


def _place_no_stories_intent(item: dict, material: dict, used: dict) -> list[dict]:
    """At most one place-with-no-stories aside per card, RANKED AFTER the
    timeline whisper and counted within the same `DEFAULT_GAP_MAX` (v200).

    Three rules, all of them the whisper's rules applied to the second kind:

    * **Ranked after `timeline_gap`.** A card that already took a whisper takes
      no aside — the two are the only intents that carry a real ask, and two of
      them on one card would compete for the same turn.
    * **≤1 per card**, and never the same place twice in one week's plan.
    * **Counted within `DEFAULT_GAP_MAX`.** The cap answers "how often may a
      conversation be asked to carry a second agenda"; that is one budget.

    Order is the residence chain's own, which is the person's own chronology.
    There is deliberately no score: v196's `leverage` counts what a DATE would
    place, and a story gap places nothing — inventing a number here would be
    inventing a fact. (`item` is unused for exactly that reason; the signature
    matches `_timeline_gap_intent`'s so the two read as the pair they are.)
    """
    del item  # see the docstring: no per-question ranking, by design
    if used["gaps"] >= used["gap_max"]:
        return []
    for row in material.get("places_without_stories") or []:
        if not isinstance(row, dict):
            continue
        key = str(row.get("key") or row.get("label") or "")
        if not key or key in used["place_keys"]:
            continue
        used["place_keys"].add(key)
        used["gaps"] += 1
        return [_place_no_stories_intent_from_row(row)]
    return []


def _place_no_stories_intent_from_row(row: dict) -> dict:
    """One `place_no_stories` row -> the arc card's intent.

    The probe, the span and the witnesses come from the landmark interaction's
    own authority (`landmarks_interaction.places_without_stories`), never from
    a second phrasing here.
    """
    import landmarks_interaction  # noqa: PLC0415

    probe = row.get("probe")
    probe_text = probe.get("text") if isinstance(probe, dict) else probe
    return {
        "kind": landmarks_interaction.PLACE_NO_STORIES_KIND,
        "place": str(row.get("label") or ""),
        "span": str(row.get("span") or ""),
        "landmark": row.get("landmark"),
        "anchor": str(row.get("anchor") or ""),
        "witnesses": row.get("witnesses"),
        "probe": str(probe_text or ""),
        "unknown_keys": [row["key"]] if row.get("key") else [],
        "note": "a place they named with nothing in it — ask what happened "
                "there, never when",
    }


def _neighborhood_sibling_intents(item: dict, material: dict) -> list[dict]:
    """Pending siblings in the same neighborhood arc — the research
    neighborhood's conversation entry point (it had none before this)."""
    neighborhoods = material.get("neighborhoods") or {}
    by_question = neighborhoods.get("by_question") or {}
    siblings = neighborhoods.get("siblings") or {}
    qid = str(item.get("question_id", ""))
    nid = by_question.get(qid)
    if not nid:
        return []
    intents = []
    for candidate in siblings.get(nid, []):
        if str(candidate.get("id")) == qid or str(candidate.get("promoted_question_id") or "") == qid:
            continue
        intents.append({
            "kind": "neighborhood_sibling",
            "candidate_id": str(candidate.get("id") or ""),
            "neighborhood_id": nid,
            "note": " ".join(str(candidate.get("text") or "").split())[:200]
                    or "a sibling question in the same arc",
        })
    return intents[:2]


def _studio_slot_intents(item: dict, material: dict) -> list[dict]:
    """Format slots the eventual answer could fill (silent no-op without a
    framework — the book/chapter-boost precedent)."""
    focus_id = str(item.get("focus") or "")
    if not focus_id:
        return []
    rows = (material.get("studio_slots") or {}).get(focus_id) or []
    return [{
        "kind": "studio_slot",
        "format": row.get("format", ""),
        "slot": row.get("slot", ""),
        "note": f"unfilled {row.get('format', '')} slot: {row.get('label') or row.get('slot')}",
    } for row in rows[:2]]


def _demonstrated_knowledge_intent(item: dict, material: dict) -> list[dict]:
    """Small summaries before dossiers (gradual introduction, phase-3 A):
    only once a category has ≥2 answers to summarize FROM, receipts real."""
    answered = _answered_in_category(item, material)
    if len(answered) < 2:
        return []
    receipts = answered[:3]
    return [{"kind": "demonstrated_knowledge_summary", "receipts": receipts,
             "note": "summarize what the record already shows about this "
                     "category before asking for more"}]


def _multiplier_for(item: dict, profile: dict) -> float:
    """quality_profile / PR6 engagement multiplier for OPTIONAL intent order.

    Guarded on every level: an absent profile, an absent engagement block, or a
    non-numeric multiplier all read as 1.0 (no bias).
    """
    if not isinstance(profile, dict):
        return 1.0
    weight = 1.0
    story_function = str(item.get("story_function", ""))
    category = _category_of(item)
    for block in (profile, profile.get("engagement") if isinstance(profile.get("engagement"), dict) else {}):
        if not isinstance(block, dict):
            continue
        for key, lookup in (("by_story_function", story_function), ("by_category", category)):
            bucket = block.get(key)
            if not isinstance(bucket, dict):
                continue
            row = bucket.get(lookup)
            value = row.get("multiplier") if isinstance(row, dict) else row
            try:
                weight *= max(0.1, min(3.0, float(value)))
            except (TypeError, ValueError):
                continue
    return weight


def _first_sentence(text: str) -> str:
    flat = " ".join(str(text).split())
    if not flat:
        return ""
    match = re.search(r"^(.{20,240}?[.!?])(\s|$)", flat)
    return (match.group(1) if match else flat[:240]).strip()


def deterministic_opening(item: dict, material: dict) -> tuple[str | None, list[str]]:
    """A verbatim-quote framing, or (None, []).

    Without a model the ONLY honest opening is the author's own words quoted
    exactly — paraphrasing an account back with altered details is the
    reconsolidation failure research.md §1 forbids. No on-record answer in the
    category ⇒ null opening ⇒ the daily message keeps today's format.
    """
    answers = material.get("answers") or {}
    bodies = answers.get("bodies") or {}
    for qid in _answered_in_category(item, material):
        quote = _first_sentence(bodies.get(qid, ""))
        if len(quote) >= 20 and BANNED_PHRASE not in quote.lower():
            return (f'You wrote: "{quote}"', [qid])
    return (None, [])


def plan_deterministic(items: list[dict], material: dict, *,
                       gap_max: int = DEFAULT_GAP_MAX,
                       now: str | None = None) -> list[dict]:
    """One card per queued item — the always-computed floor."""
    planned_at = now or now_utc()
    profile = material.get("quality") or {}
    used = {"gaps": 0, "gap_max": max(0, int(gap_max)), "gap_keys": set(),
            "place_keys": set()}
    cards: list[dict] = []
    for item in items:
        # Hard intents first: they are the reason the question is worth asking
        # and behavioral bias may never drop them.
        # v200: the whisper is tried first and the place aside only fills the
        # card's ONE gap slot when the whisper left it empty — "ranked after
        # timeline_gap", applied here rather than by a flag passed downward.
        whisper = _timeline_gap_intent(item, material, used)
        aside = [] if whisper else _place_no_stories_intent(item, material, used)
        hard = (_scene_slot_intents(item, material)
                + _sit_with_intent(item, material)
                + whisper + aside)
        optional = _neighborhood_sibling_intents(item, material) + _studio_slot_intents(item, material)
        if _multiplier_for(item, profile) < 1.0:
            optional.reverse()  # weak signal: try the other optional lane first
        optional += _demonstrated_knowledge_intent(item, material)

        intents = (hard + optional)[:MAX_INTENTS]
        if not intents:
            # Never zero intents for a queued question: the five-slot probe is
            # always available, since an unclassified category reads unfilled.
            slots = _five_slots()
            if slots:
                intents = [{"kind": "scene_slot", "slot": "what_it_says_about_me",
                            "note": "nothing on record for this category yet"}]
        opening, receipts = deterministic_opening(item, material)
        cards.append({
            "question_id": str(item.get("question_id")),
            "opening": opening,
            "opening_receipts": receipts,
            "intents": intents,
            "planned_at": planned_at,
            "planner": "deterministic",
        })
    return cards


# ---------------------------------------------------------------------------
# Validation — the lint gate every card passes, model-planned or not.
# ---------------------------------------------------------------------------


def _card_text_blob(card: dict) -> str:
    parts = [str(card.get("opening") or "")]
    for intent in card.get("intents") or []:
        if isinstance(intent, dict):
            parts.extend(str(value) for value in intent.values())
    return " ".join(parts)


def receipt_resolves(receipt: str, material: dict, *, vault_root: str | Path | None = None) -> bool:
    """An answer id on record, or a vault-relative path that exists."""
    raw = str(receipt or "").strip()
    if not raw:
        return False
    answers = material.get("answers") or {}
    if raw in set(answers.get("ids") or []):
        return True
    if "/" not in raw:
        return False
    root = _resolve_root(vault_root)
    try:
        return (root / raw).exists()
    except OSError:
        return False


def validate_card(card: object, *, allowed_ids: set[str], material: dict,
                  vault_root: str | Path | None = None,
                  require_target_band: bool = False) -> tuple[dict | None, list[str]]:
    """Return (clean card, errors). Errors ⇒ the caller keeps the deterministic one.

    A fabricated receipt is NOT fatal: the opening drops to null and the card
    survives (the intents are still good planning). A closed-vocabulary breach,
    a foreign question id, an empty/oversized intent list, or the "what year"
    lint rejects the card outright.
    """
    errors: list[str] = []
    if not isinstance(card, dict):
        return None, ["card is not an object"]
    question_id = str(card.get("question_id") or "")
    if question_id not in allowed_ids:
        return None, [f"question_id {question_id!r} is not in the current queue"]

    intents_raw = card.get("intents")
    if not isinstance(intents_raw, list) or not intents_raw:
        return None, [f"{question_id}: intents must be a non-empty list"]
    intents: list[dict] = []
    for intent in intents_raw:
        if not isinstance(intent, dict):
            return None, [f"{question_id}: intent is not an object"]
        kind = str(intent.get("kind", ""))
        if kind not in INTENT_KINDS:
            return None, [f"{question_id}: unknown intent kind {kind!r}"]
        intents.append(intent)
    floor = TARGET_MIN_INTENTS if require_target_band else MIN_INTENTS
    if not floor <= len(intents) <= MAX_INTENTS:
        return None, [f"{question_id}: {len(intents)} intent(s) outside the "
                      f"{floor}–{MAX_INTENTS} band"]

    clean = {
        "question_id": question_id,
        "opening": card.get("opening") if isinstance(card.get("opening"), str) and card.get("opening").strip() else None,
        "opening_receipts": [str(r) for r in (card.get("opening_receipts") or [])
                             if isinstance(r, str | int)],
        "intents": intents,
        "planned_at": str(card.get("planned_at") or now_utc()),
        "planner": "model" if str(card.get("planner")) == "model" else "deterministic",
    }
    if BANNED_PHRASE in _card_text_blob(clean).lower():
        return None, [f"{question_id}: contains the banned phrase {BANNED_PHRASE!r} "
                      "(research.md §4 — landmark anchors, never a calendar year)"]

    if clean["opening"]:
        unresolved = [r for r in clean["opening_receipts"]
                      if not receipt_resolves(r, material, vault_root=vault_root)]
        if unresolved or not clean["opening_receipts"]:
            errors.append(f"{question_id}: opening dropped — unresolvable receipts "
                          f"{unresolved or '(none cited)'}")
            clean["opening"] = None
            clean["opening_receipts"] = []
    else:
        clean["opening_receipts"] = []
    return clean, errors


def validate_cards(cards: object, *, allowed_ids: set[str], material: dict,
                   vault_root: str | Path | None = None,
                   require_target_band: bool = False) -> tuple[list[dict], list[str]]:
    """Validate a whole model response; returns (valid cards, all errors)."""
    if isinstance(cards, dict):
        cards = cards.get("cards")
    if not isinstance(cards, list):
        return [], ["response has no `cards` list"]
    valid: list[dict] = []
    errors: list[str] = []
    seen: set[str] = set()
    for card in cards:
        clean, card_errors = validate_card(
            card, allowed_ids=allowed_ids, material=material,
            vault_root=vault_root, require_target_band=require_target_band)
        errors.extend(card_errors)
        if clean is None:
            continue
        if clean["question_id"] in seen:
            errors.append(f"{clean['question_id']}: duplicate card ignored")
            continue
        seen.add(clean["question_id"])
        valid.append(clean)
    return valid, errors


def merge_model_cards(deterministic: list[dict], model_cards: list[dict]) -> tuple[list[dict], str]:
    """Upgrade deterministic cards IN PLACE with their model counterparts.

    Returns (cards, source) where source is model / deterministic / mixed —
    the container's honesty field about who planned this week.
    """
    by_id = {card["question_id"]: dict(card) for card in deterministic}
    upgraded = 0
    for card in model_cards:
        qid = card["question_id"]
        if qid not in by_id:
            continue
        merged = dict(card)
        merged["planner"] = "model"
        by_id[qid] = merged
        upgraded += 1
    cards = [by_id[card["question_id"]] for card in deterministic]
    if upgraded == 0:
        return cards, "deterministic"
    return cards, ("model" if upgraded == len(cards) else "mixed")


# ---------------------------------------------------------------------------
# The model pass — ONE prompt per weekly run (not per card: bounded cost at a
# weekly cadence), carrying the definition file verbatim plus this week's
# assembled material.
# ---------------------------------------------------------------------------


def resolve_model(explicit: str | None = None) -> str:
    """arc_plan_model → classify_model → classify_story.DEFAULT_MODEL."""
    if explicit:
        return explicit
    config = load_config()
    for key in ("arc_plan_model", "classify_model"):
        value = str(config.get(key) or "").strip()
        if value:
            return value
    try:
        from classify_story import DEFAULT_MODEL  # noqa: PLC0415
        return str(DEFAULT_MODEL)
    except Exception:  # noqa: BLE001
        return DEFAULT_MODEL_FALLBACK


def _record_summary(item: dict, material: dict) -> str:
    answers = material.get("answers") or {}
    bodies = answers.get("bodies") or {}
    dates = answers.get("dates") or {}
    lines = []
    for qid in _answered_in_category(item, material)[:3]:
        excerpt = " ".join(str(bodies.get(qid, "")).split())[:300]
        lines.append(f"  [{qid}, {dates.get(qid) or 'undated'}] {excerpt}")
    return "\n".join(lines) or "  (nothing on record in this category yet — cold start)"


def arc_judgment_signals(*, vault_root: str | Path | None = None) -> str:
    """The learned `## Arc judgment signals` block, or "" — GUARDED."""
    try:
        import question_judgment  # noqa: PLC0415

        return question_judgment.load_arc_signals(vault_root=vault_root)
    except Exception:  # noqa: BLE001
        return ""


def build_plan_prompt(items: list[dict], material: dict, deterministic: list[dict]) -> str:
    """The definition file verbatim + a runtime INPUT block (the shape
    ``conversation.build_arc_prompt`` established), extended from one question
    to the whole week's queue."""
    template = conversation.read_conversation_definition("plan", "arc-templates.md")
    # v196 (ruling 6): what the loop has LEARNED about arcs, composed after the
    # framework template exactly as `load_judgment_rubric` composes
    # state/question_judgment/learned.md after the question rubric. Empty until
    # the weekly judgment step writes one, so the prompt is byte-identical to
    # v195's until there is something to say.
    template = f"{template}\n\n{arc_judgment_signals()}".rstrip()
    by_id = {card["question_id"]: card for card in deterministic}
    blocks: list[str] = []
    for item in items:
        qid = str(item.get("question_id"))
        card = by_id.get(qid, {})
        blocks.append(
            f"### QUESTION [{qid}] (category {item.get('category', '')}, "
            f"focus {item.get('focus') or '—'}, story function "
            f"{item.get('story_function', '')}{', SELF-ARC' if is_self_arc(item) else ''})\n"
            f"Why it was queued: {item.get('reason', '')}\n"
            f"RECORD (quote from this exactly, never paraphrased):\n{_record_summary(item, material)}\n"
            f"DETERMINISTIC INTENT MATERIAL (typed; keep, reorder, or replace — "
            f"same closed vocabulary):\n{json.dumps(card.get('intents', []), indent=2)}"
        )
    gaps = json.dumps(material.get("timeline_gaps") or [], indent=2)
    sit_with = "\n".join(f"  - {line}" for line in material.get("sit_with") or []) or "  (none)"
    # v200: emitted ONLY when there is at least one, so a vault with no such
    # place produces a byte-identical prompt to v199's
    # (test_place_no_stories_arcs.ByteIdentityTests).
    places = material.get("places_without_stories") or []
    places_block = (
        "PLACES WITH NO STORIES (a place they named that has nothing in it — "
        "a STORY gap, never a dating one; ask what happened there, never "
        f"when):\n{json.dumps(places, indent=2)}\n\n"
    ) if places else ""
    return (
        f"{template}\n\n"
        "## INPUT (assembled at runtime — plan this week's arc cards)\n\n"
        f"{chr(10).join(blocks)}\n\n"
        f"TIMELINE GAPS (consumed kinds only):\n{gaps}\n\n"
        f"{places_block}"
        f"MIRROR — Sit with (quote one verbatim, self-arc questions only):\n{sit_with}\n\n"
        "## CRAFT RULES (hard)\n\n"
        "1. Two-sentence rule: `opening` is ONE context sentence drawn from the "
        "record above — quote the author's own words EXACTLY, never paraphrased "
        "with altered details. A cold-start question may prove memory without "
        "faking continuity (\"You've told me about X; this is somewhere we "
        "haven't been yet —\"). Set it to null rather than invent one.\n"
        "2. Every id or path in `opening_receipts` must be one that appears "
        "above. An unresolvable receipt costs the card its opening.\n"
        "3. Dates arrive as landmark anchors (before/after a move, a birth). "
        f"The phrase \"{BANNED_PHRASE}\" is forbidden anywhere in your output.\n"
        f"4. 2–4 intents per card, each an object whose `kind` is one of: "
        f"{', '.join(sorted(INTENT_KINDS))}. Intents are INTENTS, not scripted "
        "questions — the turn engine phrases them live.\n"
        "5. Quality first, coverage second: a card that would make a "
        "technically-uncovered topic feel forced is the wrong card.\n\n"
        "## OUTPUT\n\n"
        "Return STRICT JSON only (no prose, no code fence):\n"
        '{"cards": [{"question_id": "...", "opening": "..." | null, '
        '"opening_receipts": ["..."], "intents": [{"kind": "...", ...}]}]}\n'
        f"Plan exactly {len(items)} card(s), one per question above.\n"
    )


def emit_tasks(out_dir: Path, prompt: str, *, count: int) -> Path:
    """Keyless path: the prompt + a manifest naming the --from-response ingest
    (the mirror.emit_task / classify --emit-prompts convention).

    Both writes go through lifehug_core's helpers, which route vault paths to
    the no-follow I/O authority in vault_paths — never a bare Path.write_text
    (v120's runtime guard).
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    prompt_file = out_dir / "arcs.prompt.md"
    write_text(prompt_file, prompt)
    manifest = out_dir / "manifest.json"
    write_json(manifest, {
        "task": "arcs",
        "emitted_at": now_utc(),
        "ingest_command": "python3 system/lifehug.py arc-plan --from-response <response>",
        "cards_expected": count,
        "items": [{"prompt": prompt_file.name, "response": "arcs.response.json"}],
    })
    return manifest


def _strip_fences(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```[a-zA-Z]*\n", "", stripped)
        stripped = re.sub(r"\n```\s*$", "", stripped)
    return stripped.strip()


def parse_model_response(raw: str) -> object:
    try:
        return json.loads(_strip_fences(raw))
    except json.JSONDecodeError as exc:
        raise ArcPlanError(f"model response is not valid JSON: {exc}") from exc


# ---------------------------------------------------------------------------
# The weekly run
# ---------------------------------------------------------------------------


def build_container(queue: dict, cards: list[dict], source: str, *,
                    thread_offers: list[dict] | None = None,
                    now: str | None = None) -> dict:
    """Cards live and die WITH the queue: both stamps are copied VERBATIM."""
    return {
        "version": conversation.ARC_CARDS_VERSION,
        "generated_at": now or now_utc(),
        "queue_generated_at": queue.get("generated_at"),
        "expires_at": queue.get("expires_at"),
        "source": source,
        "cards": cards,
        "thread_offers": list(thread_offers or []),
    }


def plan(*, limit: int | None = None, model: str | None = None, dry_run: bool = False,
         emit_tasks_dir: str | Path | None = None, gap_max: int = DEFAULT_GAP_MAX,
         force: bool = False, vault_root: str | Path | None = None,
         now: str | None = None, timeline_payload: dict | None = None,
         readiness_cards: list[dict] | None = None) -> tuple[int, list[str]]:
    """Plan this week's arc cards. Returns (exit code, report lines)."""
    root = _resolve_root(vault_root)
    report: list[str] = []
    queue = load_queue(vault_root=root)
    items = queued_items(queue, limit=limit)
    if not items:
        report.append("No queued questions to plan arcs for.")
        return 0, report

    existing = conversation.load_arc_cards(vault_root=root)
    same_queue = (existing.get("queue_generated_at")
                  and existing.get("queue_generated_at") == queue.get("generated_at"))
    model_planned = {str(card.get("question_id")) for card in existing.get("cards") or []
                     if isinstance(card, dict) and card.get("planner") == "model"}

    material = collect_material(items, vault_root=root, timeline_payload=timeline_payload,
                               readiness_cards=readiness_cards)
    cards = plan_deterministic(items, material, gap_max=gap_max, now=now)
    source = "deterministic"

    # A model-planned card is not clobbered by a later deterministic re-run in
    # the same week (unless --force): the week's best plan survives a re-run.
    if same_queue and model_planned and not force:
        preserved = {str(card.get("question_id")): card for card in existing.get("cards") or []
                     if isinstance(card, dict) and card.get("planner") == "model"}
        cards = [preserved.get(card["question_id"], card) for card in cards]
        if preserved:
            source = "mixed" if len(preserved) < len(cards) else "model"
            report.append(f"Preserved {len(preserved)} model-planned card(s) from this week's run "
                          "(--force replans them).")

    allowed_ids = {str(item.get("question_id")) for item in items}
    prompt = build_plan_prompt(items, material, cards)

    if emit_tasks_dir is not None:
        # Keyless: the deterministic cards are written NOW (the week is never
        # lost) and the prompt goes out for agent completion.
        manifest = emit_tasks(Path(emit_tasks_dir), prompt, count=len(items))
        report.append(f"✓ Emitted arc-plan task to {Path(emit_tasks_dir)}")
        report.append(f"  Manifest: {manifest}")
        report.append("  Write strict JSON to arcs.response.json, then run the ingest_command.")
    elif not dry_run:
        try:
            from ai_provider import call_ai  # noqa: PLC0415
            resolved = resolve_model(model)
            report.append(f"Planning {len(items)} arc card(s) with {resolved}…")
            valid, errors = validate_cards(
                parse_model_response(call_ai(prompt, resolved)),
                allowed_ids=allowed_ids, material=material, vault_root=root,
                require_target_band=True)
            for error in errors:
                report.append(f"  ⚠ {error}")
            if valid:
                cards, source = merge_model_cards(cards, valid)
                report.append(f"✓ {len(valid)} card(s) planned by the model.")
            else:
                report.append("⚠ No usable model cards — keeping the deterministic plan.")
        except Exception as exc:  # noqa: BLE001 — a model failure never costs the week its cards
            report.append(f"⚠ Model pass unavailable ({exc.__class__.__name__}: {exc}) — "
                          "deterministic cards kept.")
            _record_failure("arc_plan_model", exc, root=root)

    # Every card passes the same lint gate, model-planned or not.
    cards, lint_errors = validate_cards(cards, allowed_ids=allowed_ids, material=material,
                                        vault_root=root)
    for error in lint_errors:
        report.append(f"  ⚠ {error}")
    if len(cards) != len(items):
        planned = {card["question_id"] for card in cards}
        for item in items:
            qid = str(item.get("question_id"))
            if qid not in planned:
                report.append(f"  ⚠ {qid}: no valid card survived validation")

    container = build_container(queue, cards, source,
                                thread_offers=existing.get("thread_offers"), now=now)
    if dry_run:
        report.append(f"DRY RUN — would write {len(cards)} card(s) "
                      f"(source: {source}, expires {container['expires_at']}):")
        report.extend(describe_cards(cards))
        return 0, report

    conversation.save_arc_cards(container, vault_root=root)
    report.append(f"✓ Wrote {len(cards)} arc card(s) to state/arc_cards.json "
                  f"(source: {source}, expires {container['expires_at']})")
    report.extend(describe_cards(cards))
    return 0, report


def describe_cards(cards: list[dict]) -> list[str]:
    lines = []
    for card in cards:
        kinds = ", ".join(str(intent.get("kind")) for intent in card.get("intents") or [])
        opening = card.get("opening")
        lines.append(f"  [{card['question_id']}] {card.get('planner')}: {kinds}")
        if opening:
            lines.append(f"      opening: {opening[:120]}")
    return lines


def _record_failure(operation: str, exc: BaseException, *, root: Path | None = None) -> None:
    """Record a non-blocking learning-loop failure IN THE PLANNED VAULT.

    Scoped to ``root`` so a run against a synthetic vault (tests, a second
    checkout) never appends to the process-bound vault's ledger — the default
    resolves to REPO_DIR exactly as every other caller's does.
    """
    try:
        from lifehug_core import LEARNING_FAILURES_FILE, record_learning_failure  # noqa: PLC0415
        path = LEARNING_FAILURES_FILE
        # Never wrap REPO_DIR in Path() — that strips its VaultPath authority
        # (v120 runtime guard); compare the string forms instead.
        if root is not None and os.fspath(root) != os.fspath(REPO_DIR):
            path = _data_path("learning_failures", Path(root))
        record_learning_failure("arc_planner", operation,
                                f"{exc.__class__.__name__}: {exc}", path=path)
    except Exception:  # noqa: BLE001 — never let bookkeeping raise on a fallback path
        pass


def ingest_response(path: str | Path, *, dry_run: bool = False,
                    vault_root: str | Path | None = None,
                    now: str | None = None) -> tuple[int, list[str]]:
    """`--from-response`: UPGRADE deterministic cards in place (planner→model)."""
    root = _resolve_root(vault_root)
    report: list[str] = []
    raw = Path(path).read_text(encoding="utf-8")
    payload = parse_model_response(raw)

    queue = load_queue(vault_root=root)
    items = queued_items(queue)
    allowed_ids = {str(item.get("question_id")) for item in items}
    if not allowed_ids:
        report.append("No queued questions — nothing to ingest against.")
        return 1, report

    material = collect_material(items, vault_root=root)
    valid, errors = validate_cards(payload, allowed_ids=allowed_ids, material=material,
                                   vault_root=root, require_target_band=True)
    for error in errors:
        report.append(f"  ⚠ {error}")
    if not valid:
        report.append("✗ No valid cards in the response — the existing plan is unchanged.")
        return 1, report

    existing = conversation.load_arc_cards(vault_root=root)
    base = [card for card in existing.get("cards") or [] if isinstance(card, dict)]
    if not base:
        base = plan_deterministic(items, material, now=now)
    cards, source = merge_model_cards(base, valid)
    container = build_container(queue, cards, source,
                                thread_offers=existing.get("thread_offers"), now=now)
    if dry_run:
        report.append(f"DRY RUN — would upgrade {len(valid)} card(s) to model-planned.")
        report.extend(describe_cards(cards))
        return 0, report
    conversation.save_arc_cards(container, vault_root=root)
    report.append(f"✓ Upgraded {len(valid)} card(s) to model-planned (source: {source})")
    report.extend(describe_cards(cards))
    return 0, report


# ---------------------------------------------------------------------------
# The daily attach — a pure file read. No model, no network, no state write.
# ---------------------------------------------------------------------------


def live_card(question_id: str, *, vault_root: str | Path | None = None,
              now: datetime | None = None) -> dict | None:
    """The card for this question IF it is live.

    Live = unexpired AND the question is still in the current queue (queued or
    already sent today). Dead cards return None, which is the whole of the
    stale-plan fallback: nothing attaches and the daily message keeps today's
    format.
    """
    root = _resolve_root(vault_root)
    container = conversation.load_arc_cards(vault_root=root)
    cards = [card for card in container.get("cards") or []
             if isinstance(card, dict) and str(card.get("question_id")) == str(question_id)]
    if not cards:
        return None
    expires = _parse_time(container.get("expires_at"))
    moment = now or datetime.now(timezone.utc)
    if expires and expires <= moment:
        return None
    queue = load_queue(vault_root=root)
    in_queue = {str(item.get("question_id"))
                for item in queued_items(queue, statuses=("queued", "sent"))}
    if str(question_id) not in in_queue:
        return None
    return cards[0]


def _question_and_categories(question_id: str, root: Path):
    """The bank row + category map for one question (vault-root aware)."""
    from lifehug_core import parse_categories, parse_questions, question_by_id  # noqa: PLC0415
    text = _read_text(_data_path("question_bank", root), root)
    if not text:
        return None, {}
    questions = parse_questions(text)
    return question_by_id(questions, question_id), parse_categories(text)


def daily_text(question_id: str, *, vault_root: str | Path | None = None,
               now: datetime | None = None) -> str:
    """The assembled daily message for a LIVE carded question, else "".

    The shell attach hinges on empty-vs-nonempty, which keeps the daily loop
    AI-free and branch-free. The output ALWAYS carries the ``[QID]`` marker in
    ``ask.format_question``'s exact shape — daily_question.sh parses it and the
    answer-filing flow keys on it, so the marker is produced by that one
    function rather than retyped here.
    """
    root = _resolve_root(vault_root)
    card = live_card(question_id, vault_root=root, now=now)
    if not card or not card.get("opening"):
        return ""
    question, categories = _question_and_categories(question_id, root)
    if not question:
        return ""
    import ask  # noqa: PLC0415
    formatted = ask.format_question(question, categories)
    header, _, body = formatted.partition("\n")
    opening = str(card["opening"]).strip()
    question_text = body.strip() or str(question.get("text", "")).strip()
    if question_text and question_text.lower() in opening.lower():
        # The planner embedded the question in the framing — don't say it twice.
        return f"{header}\n{opening}"
    return f"{header}\n{opening}\n\n{question_text}"


# ---------------------------------------------------------------------------
# Monthly conversation-thread offers
# ---------------------------------------------------------------------------


def conversation_ready_neighborhoods(*, vault_root: str | Path | None = None) -> list[dict]:
    """Neighborhoods with somewhere to go AND record to open from.

    Derived exactly like ``neighborhoods.apply_readiness`` reads: an active or
    draft neighborhood with at least one unanswered arc slot (somewhere to go)
    and at least one answered or promoted slot (record to open from). Nothing
    is written to the neighborhood — "conversation-ready" is derived, never a
    stored flag that can go stale.
    """
    root = _resolve_root(vault_root)
    material = collect_neighborhoods(vault_root=root)
    candidates = _read_json(_data_path("question_candidates", root), root, {})
    cand_rows = candidates.get("candidates") if isinstance(candidates, dict) else []
    try:
        import neighborhoods as neighborhoods_mod  # noqa: PLC0415
        from lifehug_core import parse_questions  # noqa: PLC0415
        questions = parse_questions(_read_text(_data_path("question_bank", root), root))
        candidates_by_id = neighborhoods_mod.candidate_lookup(cand_rows)
        questions_by_id = neighborhoods_mod.question_lookup(questions)
        resolve = neighborhoods_mod.resolve_slot
    except Exception:  # noqa: BLE001
        return []

    ready: list[dict] = []
    for neighborhood in material.get("neighborhoods") or []:
        if str(neighborhood.get("status", "active")) not in {"active", "draft"}:
            continue
        slots = [slot for slot in neighborhood.get("arc") or [] if isinstance(slot, dict)]
        if not slots:
            continue
        resolved = [resolve(slot, candidates_by_id, questions_by_id) for slot in slots]
        lifecycles = [str(slot.get("lifecycle_status")) for slot in resolved]
        somewhere_to_go = any(state != "answered" for state in lifecycles)
        record_to_open_from = any(state in {"answered", "promoted"} for state in lifecycles)
        if somewhere_to_go and record_to_open_from:
            ready.append(neighborhood)
    return ready


def plan_thread_offers(*, limit: int = DEFAULT_THREAD_OFFERS, dry_run: bool = False,
                       vault_root: str | Path | None = None,
                       now: datetime | None = None) -> tuple[list[str], list[dict]]:
    """At most `limit` offer line(s); an offered neighborhood stays quiet a quarter.

    Returns (telegram lines, new offer records).
    """
    root = _resolve_root(vault_root)
    moment = now or datetime.now(timezone.utc)
    container = conversation.load_arc_cards(vault_root=root)
    offers = [row for row in container.get("thread_offers") or [] if isinstance(row, dict)]
    quiet_since = moment - timedelta(days=THREAD_OFFER_QUIET_DAYS)
    recent = {str(row.get("neighborhood_id")) for row in offers
              if (_parse_time(row.get("offered_at")) or moment) > quiet_since}

    lines: list[str] = []
    fresh: list[dict] = []
    for neighborhood in conversation_ready_neighborhoods(vault_root=root):
        if len(fresh) >= max(0, int(limit)):
            break
        nid = str(neighborhood.get("id") or "")
        if not nid or nid in recent:
            continue
        title = str(neighborhood.get("title") or nid)
        lines.append(f"💬 I've been wanting to ask about {title} — shall we?")
        fresh.append({"neighborhood_id": nid,
                      "offered_at": moment.strftime("%Y-%m-%dT%H:%M:%SZ"),
                      "month": moment.strftime("%Y-%m")})
    if fresh and not dry_run:
        container["thread_offers"] = offers + fresh
        conversation.save_arc_cards(container, vault_root=root)
    return lines, fresh


# ---------------------------------------------------------------------------
# CLI (wrapped by lifehug.py's arc-plan / arc-card / arc-thread-offers)
# ---------------------------------------------------------------------------


def _emit(report: list[str]) -> None:
    for line in report:
        print(line)


def cmd_plan(args: argparse.Namespace) -> int:
    if args.from_response:
        code, report = ingest_response(args.from_response, dry_run=args.dry_run)
        _emit(report)
        return code
    code, report = plan(
        limit=args.limit,
        model=args.model,
        dry_run=args.dry_run,
        emit_tasks_dir=args.emit_tasks,
        gap_max=args.gap_max,
        force=args.force,
    )
    _emit(report)
    return code


def cmd_card(args: argparse.Namespace) -> int:
    if args.daily_text:
        text = daily_text(args.question_id)
        if text:
            print(text)
        return 0
    card = live_card(args.question_id)
    if not card:
        print(f"No live arc card for {args.question_id}.")
        return 0
    print(json.dumps(card, indent=2))
    return 0


def cmd_thread_offers(args: argparse.Namespace) -> int:
    lines, fresh = plan_thread_offers(limit=args.limit, dry_run=args.dry_run)
    if not lines:
        print("No conversation-thread offers this month.")
        return 0
    prefix = "DRY RUN — would offer:" if args.dry_run else f"✓ Offered {len(fresh)} thread(s):"
    print(prefix)
    for line in lines:
        print(line)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Lifehug weekly arc planner")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("plan", help="Plan this week's arc cards")
    p.add_argument("--limit", type=int, default=None, help="Plan at most N queued questions")
    p.add_argument("--gap-max", type=int, default=int(os.environ.get("LIFEHUG_WEEKLY_ARC_GAP_MAX", DEFAULT_GAP_MAX)),
                   help="Max gap intents (timeline_gap + place_no_stories, one budget) across the week (default 3)")
    p.add_argument("--model", default=None, help="AI model override")
    p.add_argument("--dry-run", action="store_true", help="Print the plan; write nothing")
    p.add_argument("--emit-tasks", metavar="DIR", default=None,
                   help="Keyless: write deterministic cards and emit the prompt for agent completion")
    p.add_argument("--from-response", metavar="PATH", default=None,
                   help="Ingest an agent-written response and upgrade cards in place")
    p.add_argument("--force", action="store_true",
                   help="Replan model-planned cards for the same queue")
    p.set_defaults(func=cmd_plan)

    p = sub.add_parser("card", help="Read one live arc card (pure read)")
    p.add_argument("question_id")
    p.add_argument("--daily-text", action="store_true",
                   help="Print the assembled daily message for a live card, else nothing")
    p.set_defaults(func=cmd_card)

    p = sub.add_parser("thread-offers", help="Monthly conversation-thread offers")
    p.add_argument("--limit", type=int,
                   default=int(os.environ.get("LIFEHUG_MONTHLY_THREAD_OFFERS", DEFAULT_THREAD_OFFERS)))
    p.add_argument("--dry-run", action="store_true")
    p.set_defaults(func=cmd_thread_offers)

    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except ArcPlanError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
