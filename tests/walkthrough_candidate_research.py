#!/usr/bin/env python3
"""Synthetic executable walkthrough for candidate-research source authority."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "system"))

import candidate_research as research
import source_integrity
import wiki_compile


class SyntheticFileAuthority:
    """Dependency-free exact-byte adapter; v182 supplies the live Git adapter."""

    def resolve_exact_source(
        self,
        plan,
        *,
        vault_root=None,
        push=True,
        failpoint=None,
        revalidate_current_subject,
    ):
        del push
        revalidate_current_subject()
        root = Path(vault_root)
        path = root / plan["source_path"]
        for candidate in sorted(
            (root / "sources" / "candidate-research").rglob("*.md")
        ):
            try:
                parsed = research.validate_candidate_research_source_text(
                    candidate.read_text(encoding="utf-8")
                )
            except (UnicodeDecodeError, research.CandidateResearchError) as exc:
                raise research.CandidateResearchConflict(
                    "synthetic canonical tree contains invalid candidate research"
                ) from exc
            marker = parsed["marker"]
            if (
                marker["candidate_kind"] == plan["candidate_kind"]
                and marker["candidate_id"] == plan["candidate_id"]
                and candidate != path
            ):
                raise research.CandidateResearchConflict(
                    "synthetic canonical tree has a second identity contender"
                )
        path.parent.mkdir(parents=True, exist_ok=True)
        changed = not path.exists()
        if path.exists() and path.read_bytes() != plan["source_bytes"]:
            raise research.CandidateResearchConflict("synthetic exact-byte conflict")
        if changed:
            path.write_bytes(plan["source_bytes"])
        if failpoint:
            failpoint("after_source_write")
        commit_sha = hashlib.sha1(
            b"synthetic-walkthrough\0" + plan["source_bytes"]
        ).hexdigest()
        return {
            "source_path": plan["source_path"],
            "changed": changed,
            "commit_sha": commit_sha,
        }


def turns():
    return [
        research.build_authoritative_user_turn(
            "walk-turn-1",
            "Synthetic Harbor was where my grandmother taught me to wait for the tide.",
        ),
        research.build_authoritative_user_turn(
            "walk-turn-2",
            "After the storm I returned alone, and the broken pier made the loss feel concrete.",
        ),
        research.build_authoritative_user_turn(
            "walk-turn-3",
            "Now I connect that harbor to patience, grief, and what I pass to my children.",
        ),
        research.build_authoritative_user_turn(
            "walk-confirm",
            "Yes, that is the exact research I want preserved.",
        ),
    ]


def spans(user_turns, count=3):
    kinds = ("statement", "concrete_event", "concrete_observation")
    return [
        research.extract_research_evidence_span(
            user_turns[index], 0, len(user_turns[index]["text"]), kinds[index]
        )
        for index in range(count)
    ]


def dimensions(names, evidence):
    refs = [span["evidence_revision"] for span in evidence]
    return {name: [refs[index % len(refs)]] for index, name in enumerate(names)}


def confirm(assessment, user_turns):
    return research.confirm_research_assessment(
        assessment,
        turn=user_turns[-1],
        start=0,
        end=len(user_turns[-1]["text"]),
        confirmed_at="2026-08-18T20:00:00Z",
        authoritative_turns=user_turns,
        current_subject=assessment["subject"],
    )


def main() -> int:
    user_turns = turns()
    evidence = spans(user_turns)
    results: dict[str, object] = {
        "adapter": "v182-public-exact-file-git",
        "live_git_adapter": "integrated",
    }

    with tempfile.TemporaryDirectory(
        dir=ROOT.parent, prefix="lifehug-candidate-research-"
    ) as td:
        vault = Path(td)
        (vault / "answers").mkdir()
        (vault / "state").mkdir()
        (vault / "wiki").mkdir()
        (vault / ".gitignore").write_text("state/jobs/\n", encoding="utf-8")
        (vault / "question-bank.md").write_text("# Questions\n", encoding="utf-8")
        (vault / "state" / "rotation.json").write_text(
            json.dumps(
                {
                    "version": 1,
                    "current_pass": 1,
                    "pass_names": ["skeleton"],
                    "last_question_id": None,
                    "last_asked_at": None,
                    "questions_asked": 0,
                    "questions_answered": 0,
                    "next_question_id": None,
                    "focus_frequency": 4,
                }
            )
            + "\n",
            encoding="utf-8",
        )
        (vault / "state" / "coverage.json").write_text(
            '{"version":1,"last_updated":null,"categories":{}}\n',
            encoding="utf-8",
        )
        for args in (
            ("init", "-b", "main"),
            ("config", "user.name", "Fixture"),
            ("config", "user.email", "fixture@example.invalid"),
            ("add", "."),
            ("commit", "-m", "fixture"),
        ):
            subprocess.run(
                ["git", "-C", str(vault), *args],
                check=True,
                capture_output=True,
                text=True,
            )

        focus_subject = research.build_focus_candidate_subject(
            {
                "id": "rec-synthetic-harbor",
                "entity": "Synthetic Harbor",
                "type": "place",
                "status": "pending",
            }
        )
        focus_dimensions = dimensions(research.FOCUS_DIMENSIONS, evidence)
        incomplete_dimensions = dict(focus_dimensions)
        incomplete_dimensions["why_it_matters"] = []
        not_ready = research.build_research_assessment(
            subject=focus_subject,
            evidence=evidence,
            dimension_evidence=incomplete_dimensions,
            seed_questions=[
                {"question": "What changed when you returned?", "evidence": False},
                {"question": "Who else understood the harbor?", "evidence": False},
            ],
            authoritative_turns=user_turns,
        )
        assert not not_ready["readiness"]["ready"]

        ready = research.build_research_assessment(
            subject=focus_subject,
            evidence=evidence,
            dimension_evidence=focus_dimensions,
            seed_questions=[
                {"question": "What changed when you returned?", "evidence": False},
                {"question": "Who else understood the harbor?", "evidence": False},
            ],
            authoritative_turns=user_turns,
        )
        assert ready["readiness"]["ready"] and not ready["complete"]
        completed = confirm(ready, user_turns)
        assert completed["complete"]

        first = research.resolve_candidate_research_source(
            completed,
            authoritative_turns=user_turns,
            current_subject_loader=lambda: focus_subject,
            vault_root=vault,
            push=False,
        )
        # A brand-new adapter instance discovers the canonical bytes from disk;
        # no memory-only index or manifest projection participates in adoption.
        replay = research.resolve_candidate_research_source(
            completed,
            authoritative_turns=user_turns,
            current_subject_loader=lambda: focus_subject,
            vault_root=vault,
            push=False,
        )
        assert first["changed"] and not replay["changed"]
        assert {key: value for key, value in first.items() if key != "changed"} == {
            key: value for key, value in replay.items() if key != "changed"
        }

        entity_receipts = {}
        for entity_type, minimum in research.ENTITY_MIN_EVIDENCE_SPANS.items():
            subject = research.build_entity_candidate_subject(
                entity_type,
                {
                    "name": f"Synthetic {entity_type.title()}",
                    "slug": f"synthetic-{entity_type}",
                    "aliases": [],
                    "qualifies": False,
                    "maps_to_focus": None,
                    "page_eligible": False,
                },
            )
            entity_evidence = evidence[:minimum]
            assessment = research.build_research_assessment(
                subject=subject,
                evidence=entity_evidence,
                dimension_evidence=dimensions(
                    research.ENTITY_DIMENSIONS, entity_evidence
                ),
                seed_questions=[],
                authoritative_turns=user_turns,
            )
            assert assessment["readiness"]["ready"]
            entity_receipts[entity_type] = research.resolve_candidate_research_source(
                confirm(assessment, user_turns),
                authoritative_turns=user_turns,
                current_subject_loader=lambda subject=subject: subject,
                vault_root=vault,
                push=False,
            )

        source_integrity.REPO_DIR = vault
        source_integrity.ANSWERS_DIR = vault / "answers"
        source_integrity.SOURCES_DIR = vault / "sources"
        source_integrity.SOURCE_MANIFEST_FILE = vault / "state" / "source_manifest.json"
        source_integrity.WIKI_DIR = vault / "wiki"
        records = source_integrity.scan_sources()
        manifest = source_integrity.sync_manifest(
            records, write=True, prune_missing=True
        )
        findings = source_integrity.lint_records(records)
        assert not [finding for finding in findings if finding["severity"] == "error"]
        assert all(
            manifest["sources"][record["path"]].get("research_revision")
            for record in records
        )

        wiki_compile.REPO_DIR = vault
        wiki_compile.SOURCES_DIR = vault / "sources"
        wiki_compile._RETRACTIONS = []
        manual_sources = wiki_compile.read_manual_sources()
        focus_desc = wiki_compile.plan_focuses(
            {"K": {"group": "focus", "name": "Focus — Synthetic Harbor"}},
            [],
            {},
            manual_sources,
            {"entities": []},
        )[0]
        assert focus_desc["sources"]
        assert "no source material yet" not in focus_desc["summary"]
        focus_synthesis = wiki_compile.fallback_synthesis(focus_desc)
        focus_page = wiki_compile.render_page(focus_desc, focus_synthesis, [], [], {})
        focus_quote = completed["evidence"][0]["quote"]
        assert focus_quote in focus_page
        assert research.MARKER_PREFIX not in focus_page

        generic_project = wiki_compile.plan_projects(
            {"P": {"group": "project", "name": "Synthetic Harbor"}},
            [],
            {},
            manual_sources,
        )[0]
        assert not generic_project["sources"]

        compiled_entity_types = []
        for entity_type in ("person", "place", "period", "object"):
            slug = f"synthetic-{entity_type}"
            descs = wiki_compile.plan_entities(
                entity_type,
                {},
                manual_sources,
                {
                    "entities": [
                        {
                            "name": f"Synthetic {entity_type.title()}",
                            "slug": slug,
                            "aliases": [],
                            "page_eligible": True,
                            "maps_to_focus": None,
                        }
                    ]
                },
                set(),
            )
            assert len(descs) == 1 and descs[0]["sources"]
            compiled_entity_types.append(entity_type)
        theme_descs = wiki_compile.plan_themes(
            {},
            manual_sources,
            {
                "entities": [
                    {
                        "name": "Synthetic Theme",
                        "slug": "synthetic-theme",
                        "aliases": [],
                        "keywords": ["absent-keyword"],
                        "page_eligible": True,
                        "maps_to_focus": None,
                    }
                ]
            },
            author_slug="synthetic-author",
        )
        assert next(row for row in theme_descs if row["slug"] == "synthetic-theme")[
            "sources"
        ]
        assert not any(
            row["slug"] == "family"
            for row in wiki_compile.plan_themes(
                {},
                manual_sources,
                {"entities": []},
                author_slug="synthetic-author",
            )
        )
        compiled_entity_types.append("theme")

        results.update(
            {
                "not_ready_missing": not_ready["readiness"]["missing"],
                "ready_unconfirmed": ready["readiness"]["ready"]
                and not ready["complete"],
                "confirmed_complete": completed["complete"],
                "first_changed": first["changed"],
                "replay_changed": replay["changed"],
                "same_receipt_identity": first["commit_sha"] == replay["commit_sha"],
                "typed_manifest_sources": len(manifest["sources"]),
                "focus_placeholder_replaced": (
                    "no source material yet" not in focus_desc["summary"]
                    and focus_quote in focus_page
                ),
                "rendered_exact_user_quote": focus_quote in focus_page,
                "generic_keyword_route_excluded": not generic_project["sources"],
                "entity_types_cited": compiled_entity_types,
                "entity_receipts": len(entity_receipts),
            }
        )

    print(json.dumps(results, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
