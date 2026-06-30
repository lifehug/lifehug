#!/usr/bin/env python3
"""Derived readiness metrics for Lifehug research neighborhoods."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path

from lifehug_core import (
    NEIGHBORHOODS_FILE,
    QUESTION_CANDIDATES_FILE,
    QUESTIONS_FILE,
    now_utc,
    parse_questions,
    read_json,
    write_json,
)

READY_TO_DRAFT_THRESHOLD = 0.8


def ratio(count: int, total: int) -> float:
    return round(count / total, 3) if total else 0.0


def candidate_lookup(candidates: dict | list[dict] | None) -> dict[str, dict]:
    rows = candidates.get("candidates", []) if isinstance(candidates, dict) else (candidates or [])
    return {str(item.get("id")): item for item in rows if item.get("id")}


def question_lookup(questions: list[dict] | None) -> dict[str, dict]:
    return {str(item.get("id")): item for item in (questions or []) if item.get("id")}


def resolve_slot(slot: dict, candidates_by_id: dict[str, dict], questions_by_id: dict[str, dict]) -> dict:
    """Return a slot annotated with candidate/promoted/answered lifecycle state."""
    out = dict(slot)
    raw_id = str(slot.get("question_id") or "").strip()

    lifecycle = "pending"
    candidate_id = ""
    promoted_question_id = ""
    answered_question_id = ""

    if raw_id:
        lifecycle = "candidate"
        if raw_id in candidates_by_id:
            candidate_id = raw_id
            promoted_question_id = str(candidates_by_id[raw_id].get("promoted_question_id") or "").strip()
        else:
            promoted_question_id = raw_id

        if promoted_question_id:
            question = questions_by_id.get(promoted_question_id)
            if question:
                if question.get("answered"):
                    lifecycle = "answered"
                    answered_question_id = promoted_question_id
                else:
                    lifecycle = "promoted"
            else:
                lifecycle = "promoted_missing" if candidate_id else "question_missing"

    out["lifecycle_status"] = lifecycle
    if candidate_id:
        out["candidate_id"] = candidate_id
    else:
        out.pop("candidate_id", None)
    if promoted_question_id:
        out["promoted_question_id"] = promoted_question_id
    else:
        out.pop("promoted_question_id", None)
    if answered_question_id:
        out["answered_question_id"] = answered_question_id
    else:
        out.pop("answered_question_id", None)
    out["status"] = lifecycle
    return out


def readiness_status(question_count: int, promoted_count: int, answered_count: int, ready: bool) -> str:
    if ready:
        return "answer_ready"
    if answered_count:
        return "answering"
    if promoted_count:
        return "promoted"
    if question_count:
        return "questions_generated"
    return "empty"


def compute_readiness(
    neighborhood: dict,
    candidates: dict | list[dict] | None,
    questions: list[dict] | None,
    *,
    threshold: float = READY_TO_DRAFT_THRESHOLD,
) -> dict:
    """Compute question, promotion, and answer readiness for one neighborhood."""
    arc = [dict(slot) for slot in neighborhood.get("arc", [])]
    candidates_by_id = candidate_lookup(candidates)
    questions_by_id = question_lookup(questions)
    resolved_arc = [resolve_slot(slot, candidates_by_id, questions_by_id) for slot in arc]

    total = len(resolved_arc)
    question_count = sum(1 for slot in resolved_arc if slot.get("question_id"))
    promoted_count = sum(1 for slot in resolved_arc if slot.get("lifecycle_status") in {"promoted", "answered"})
    answered_count = sum(1 for slot in resolved_arc if slot.get("lifecycle_status") == "answered")

    question_completeness = ratio(question_count, total)
    promoted_completeness = ratio(promoted_count, total)
    answered_completeness = ratio(answered_count, total)
    ready = answered_completeness >= threshold

    return {
        "arc": resolved_arc,
        "arc_lifecycle_counts": {
            "total_slots": total,
            "questions_generated": question_count,
            "questions_promoted": promoted_count,
            "answers_captured": answered_count,
        },
        "question_arc_completeness": question_completeness,
        "promoted_completeness": promoted_completeness,
        "answered_completeness": answered_completeness,
        "ready_to_draft": ready,
        "readiness_status": readiness_status(question_count, promoted_count, answered_count, ready),
    }


def apply_readiness(
    neighborhood: dict,
    candidates: dict | list[dict] | None,
    questions: list[dict] | None,
) -> dict:
    """Return a neighborhood copy with split readiness fields applied."""
    updated = deepcopy(neighborhood)
    metrics = compute_readiness(updated, candidates, questions)
    updated.update({
        "arc": metrics["arc"],
        "arc_lifecycle_counts": metrics["arc_lifecycle_counts"],
        "question_arc_completeness": metrics["question_arc_completeness"],
        "promoted_completeness": metrics["promoted_completeness"],
        "answered_completeness": metrics["answered_completeness"],
        "ready_to_draft": metrics["ready_to_draft"],
        "readiness_status": metrics["readiness_status"],
        # Legacy field: keep meaning as "questions generated" for compatibility.
        "completeness": metrics["question_arc_completeness"],
    })
    return updated


def load_candidates(path: Path = QUESTION_CANDIDATES_FILE) -> dict:
    return read_json(path, default={"version": 1, "candidates": []}) or {"version": 1, "candidates": []}


def load_questions(path: Path = QUESTIONS_FILE) -> list[dict]:
    if not path.exists():
        return []
    return parse_questions(path.read_text(encoding="utf-8"))


def refresh_all_neighborhood_readiness(*, write: bool = True) -> dict:
    """Recompute and optionally persist readiness for every stored neighborhood."""
    data = read_json(NEIGHBORHOODS_FILE, default=None)
    if not isinstance(data, dict):
        return {"version": 1, "neighborhoods": []}
    neighborhoods = data.get("neighborhoods", [])
    if not isinstance(neighborhoods, list) or not neighborhoods:
        return data

    candidates = load_candidates()
    questions = load_questions()
    refreshed = dict(data)
    refreshed["neighborhoods"] = [
        apply_readiness(neighborhood, candidates, questions)
        for neighborhood in neighborhoods
    ]

    if refreshed["neighborhoods"] != data.get("neighborhoods", []):
        refreshed["last_readiness_updated"] = now_utc()
        if write:
            write_json(NEIGHBORHOODS_FILE, refreshed)
    return refreshed
