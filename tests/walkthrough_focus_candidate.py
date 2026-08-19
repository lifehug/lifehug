#!/usr/bin/env python3
"""Synthetic end-to-end walkthrough for the Focus Candidate Interaction."""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "system"))

import focus_candidate as focus  # noqa: E402
import source_integrity  # noqa: E402
import wiki_compile  # noqa: E402

from tests.test_focus_candidate import FocusCandidateTests  # noqa: E402
from tests.walkthrough_candidate_research import SyntheticFileAuthority  # noqa: E402


def main() -> int:
    fixture = FocusCandidateTests()
    turns = fixture.turns()
    with tempfile.TemporaryDirectory(prefix="lifehug-focus-candidate-") as tmp:
        vault = Path(tmp)
        (vault / "state").mkdir()
        (vault / "sources").mkdir()
        (vault / "answers").mkdir()
        (vault / "wiki").mkdir()
        recommendation = fixture.recommendation()
        state_path = vault / "state/focus_recommendations.json"
        state_path.write_text(
            json.dumps(
                {
                    "version": 1,
                    "recommendations": [recommendation],
                    "dismissed": [],
                }
            )
            + "\n",
            encoding="utf-8",
        )
        before = {
            path.relative_to(vault).as_posix(): path.read_bytes()
            for path in vault.rglob("*")
            if path.is_file()
        }
        loaded = focus.load_focus_candidate_subject(
            recommendation["id"], vault_root=vault
        )
        payload = focus.build_focus_candidate_input(
            candidate_id=recommendation["id"],
            authoritative_turns=turns,
            assessment=None,
            latest_turn_id="t3",
            previous_question=None,
            current_subject=loaded,
        )
        prompt = focus.build_focus_candidate_prompt(payload, current_subject=loaded)
        after = {
            path.relative_to(vault).as_posix(): path.read_bytes()
            for path in vault.rglob("*")
            if path.is_file()
        }
        assert before == after
        assert (
            "interaction:conversation" in prompt
            and "interaction:focus_candidate" in prompt
        )

        ready_decision = focus.parse_focus_candidate_output(
            fixture.ready_proposal(), payload=payload, current_subject=loaded
        )
        assert ready_decision["ready"] and not ready_decision["complete"]

        confirmed_turns = fixture.turns(confirmed=True)
        confirmation_payload = focus.build_focus_candidate_input(
            candidate_id=recommendation["id"],
            authoritative_turns=confirmed_turns,
            assessment=ready_decision["assessment"],
            latest_turn_id="t4",
            previous_question="What would you change before I preserve this research?",
            current_subject=loaded,
        )
        confirmation = {
            "reply": "I will hold those exact excerpts as candidate research.",
            "action": "accept_confirmation",
            "next_gap": None,
            "evidence_spans": [],
            "dimension_evidence": {name: [] for name in focus.FOCUS_DIMENSIONS},
            "seed_questions": [],
            "confirmation_span": {
                "turn_id": "t4",
                "start": 0,
                "end": len(confirmed_turns[-1]["text"]),
            },
        }
        completed = focus.parse_focus_candidate_output(
            confirmation,
            payload=confirmation_payload,
            current_subject=loaded,
            confirmed_at="2026-08-18T20:00:00Z",
        )
        assert completed["complete"]

        def loader() -> dict:
            return focus.load_focus_candidate_subject(
                recommendation["id"], vault_root=vault
            )

        authority = SyntheticFileAuthority()
        first = focus.resolve_focus_candidate_completion(
            completed["assessment"],
            authoritative_turns=confirmed_turns,
            candidate_id=recommendation["id"],
            current_subject_loader=loader,
            authority=authority,
            vault_root=vault,
            push=False,
        )
        replay = focus.resolve_focus_candidate_completion(
            completed["assessment"],
            authoritative_turns=confirmed_turns,
            candidate_id=recommendation["id"],
            current_subject_loader=loader,
            authority=authority,
            vault_root=vault,
            push=False,
        )
        assert first["changed"] and not replay["changed"]
        assert first["commit_sha"] == replay["commit_sha"]
        current_state = json.loads(state_path.read_text())
        assert current_state["recommendations"][0]["status"] == "pending"

        source_integrity.REPO_DIR = vault
        source_integrity.ANSWERS_DIR = vault / "answers"
        source_integrity.SOURCES_DIR = vault / "sources"
        source_integrity.SOURCE_MANIFEST_FILE = vault / "state/source_manifest.json"
        source_integrity.WIKI_DIR = vault / "wiki"
        records = source_integrity.scan_sources()
        source_integrity.sync_manifest(records, write=True, prune_missing=True)
        wiki_compile.REPO_DIR = vault
        wiki_compile.SOURCES_DIR = vault / "sources"
        wiki_compile._RETRACTIONS = []
        sources = wiki_compile.read_manual_sources()
        assert wiki_compile.plan_focuses({}, [], {}, sources, {"entities": []}) == []
        planned = wiki_compile.plan_focuses(
            {"K": {"group": "focus", "name": "Focus — Synthetic Harbor"}},
            [],
            {},
            sources,
            {"entities": []},
        )[0]
        page = wiki_compile.render_page(
            planned, wiki_compile.fallback_synthesis(planned), [], [], {}
        )
        assert planned["sources"] and "no source material yet" not in planned["summary"]
        assert completed["assessment"]["evidence"][0]["quote"] in page

        dismissed = dict(recommendation, status="dismissed")
        state_path.write_text(
            json.dumps({"version": 1, "recommendations": [], "dismissed": [dismissed]})
            + "\n"
        )
        try:
            loader()
        except focus.FocusCandidateError:
            stale_rejected = True
        else:
            stale_rejected = False
        assert stale_rejected

        print(
            json.dumps(
                {
                    "start_zero_write": before == after,
                    "eight_dimensions_ready": ready_decision["ready"],
                    "ready_not_complete": not ready_decision["complete"],
                    "explicit_confirmation_complete": completed["complete"],
                    "first_changed": first["changed"],
                    "replay_changed": replay["changed"],
                    "same_commit": first["commit_sha"] == replay["commit_sha"],
                    "candidate_still_pending": current_state["recommendations"][0][
                        "status"
                    ]
                    == "pending",
                    "before_approval_no_focus": True,
                    "after_approval_cited_non_placeholder": bool(planned["sources"]),
                    "stale_dismissed_rejected": stale_rejected,
                },
                indent=2,
                sort_keys=True,
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
