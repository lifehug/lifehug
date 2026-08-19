#!/usr/bin/env python3
"""Synthetic all-type walkthrough for the Entity Candidate Interaction."""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "system"))

import candidate_research as research  # noqa: E402
import entity_candidate as entity  # noqa: E402

from tests.test_entity_candidate import MemoryAuthority  # noqa: E402


def _row(kind: str) -> dict:
    return {
        "name": f"Synthetic {kind.title()}",
        "slug": f"synthetic-{kind}",
        "aliases": [],
        "page_eligible": False,
        "maps_to_focus": None,
        "owner_verdict": None,
    }


def _turns(kind: str, confirmed: bool = False) -> list[dict]:
    text = [
        f"Synthetic {kind.title()} is distinct in my story and matters because it changed how I live.",
        f"During the storm, I returned to Synthetic {kind.title()} with my sister and saw its meaning change.",
        "It connects my childhood and the question I still carry about what comes next.",
    ]
    if confirmed:
        text.append("Yes, preserve these exact excerpts.")
    return [
        research.build_authoritative_user_turn(f"t{i + 1}", value)
        for i, value in enumerate(text)
    ]


def _proposal(turns: list[dict]) -> dict:
    spans = [
        {
            "turn_id": turn["turn_id"],
            "start": 0,
            "end": len(turn["text"]),
            "evidence_kind": "concrete_event" if index == 1 else "statement",
        }
        for index, turn in enumerate(turns)
    ]
    return {
        "reply": "That gives this part of your story shape.",
        "action": "continue",
        "next_gap": None,
        "evidence_spans": spans,
        "dimension_evidence": {
            "identity_disambiguation": [0],
            "relationship_relevance_and_significance": [0],
            "timeline_context": [1],
            "connections": [2],
            "tension_or_open_question": [2],
            "type_specific_context": [1, 2],
            "grounded_evidence": [1],
        },
        "seed_questions": [],
        "confirmation_span": None,
    }


def _run_type(vault: Path, kind: str) -> dict:
    roster = vault / "state/entity_rosters"
    roster.mkdir(parents=True, exist_ok=True)
    row = _row(kind)
    (roster / f"{kind}.json").write_text(
        json.dumps({"version": 1, "entities": [row]}) + "\n"
    )
    candidate_id = f"entity:{kind}:synthetic-{kind}"
    before = {
        p.relative_to(vault).as_posix(): p.read_bytes()
        for p in vault.rglob("*")
        if p.is_file()
    }
    subject = entity.load_entity_candidate_subject(candidate_id, vault_root=vault)
    turns = _turns(kind)
    payload = entity.build_entity_candidate_input(
        candidate_id=candidate_id,
        authoritative_turns=turns,
        assessment=None,
        latest_turn_id="t3",
        previous_question=None,
        current_subject=subject,
    )
    entity.build_entity_candidate_prompt(payload, current_subject=subject)
    after = {
        p.relative_to(vault).as_posix(): p.read_bytes()
        for p in vault.rglob("*")
        if p.is_file()
    }
    decision = entity.parse_entity_candidate_output(
        _proposal(turns), payload=payload, current_subject=subject
    )
    confirmed = _turns(kind, True)
    confirm_payload = entity.build_entity_candidate_input(
        candidate_id=candidate_id,
        authoritative_turns=confirmed,
        assessment=decision["assessment"],
        latest_turn_id="t4",
        previous_question=None,
        current_subject=subject,
    )
    accepted = entity.parse_entity_candidate_output(
        {
            "reply": "I can preserve the exact excerpts.",
            "action": "accept_confirmation",
            "next_gap": None,
            "evidence_spans": [],
            "dimension_evidence": {name: [] for name in entity.ENTITY_DIMENSIONS},
            "seed_questions": [],
            "confirmation_span": {
                "turn_id": "t4",
                "start": 0,
                "end": len(confirmed[-1]["text"]),
            },
        },
        payload=confirm_payload,
        current_subject=subject,
        confirmed_at="2026-08-18T20:00:00Z",
    )
    authority = MemoryAuthority()

    def loader() -> dict:
        return entity.load_entity_candidate_subject(candidate_id, vault_root=vault)

    first = entity.resolve_entity_candidate_completion(
        accepted["assessment"],
        authoritative_turns=confirmed,
        candidate_id=candidate_id,
        current_subject_loader=loader,
        authority=authority,
        vault_root=vault,
        push=False,
    )
    replay = entity.resolve_entity_candidate_completion(
        accepted["assessment"],
        authoritative_turns=confirmed,
        candidate_id=candidate_id,
        current_subject_loader=loader,
        authority=authority,
        vault_root=vault,
        push=False,
    )
    return {
        "type": kind,
        "start_zero_write": before == after,
        "ready_not_complete": decision["ready"] and not decision["complete"],
        "completed": accepted["complete"],
        "changed": first["changed"],
        "replay_unchanged": not replay["changed"],
        "pending": not row["page_eligible"],
    }


def main() -> int:
    with tempfile.TemporaryDirectory(
        dir=ROOT.parent, prefix="lifehug-entity-candidate-"
    ) as tmp:
        vault = Path(tmp)
        rows = [
            _run_type(vault / kind, kind)
            for kind in ("person", "place", "period", "object", "theme")
        ]
    passed = all(
        all(value is True for key, value in row.items() if key != "type")
        for row in rows
    )
    print(json.dumps({"passed": passed, "types": rows}, indent=2, sort_keys=True))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
