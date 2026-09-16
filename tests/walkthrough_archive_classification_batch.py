#!/usr/bin/env python3
"""Offline archive batch walkthrough; synthetic data and recorded model output."""

from __future__ import annotations

import argparse
import contextlib
import json
import sys
import tempfile
import time
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "system"))

import classifier_claims  # noqa: E402
import classifier_context as cc  # noqa: E402
import classify_story as cs  # noqa: E402
import event_identity  # noqa: E402
import landmark_projection  # noqa: E402
import temporal_publication as publication  # noqa: E402
import temporal_store as store  # noqa: E402


def date(value: str) -> dict:
    return {
        "best": value,
        "earliest": value.split("/")[0],
        "latest": value.split("/")[-1],
        "granularity": "range" if "/" in value else "year",
        "confidence": "certain",
        "basis": "document",
        "anchors": [],
        "provenance": [{"source": "human:walkthrough", "quote": "synthetic date"}],
    }


def _timeline_response(snapshot: dict) -> str:
    return json.dumps({
        "_classification_mode": "timeline",
        "_classification_snapshot": cc.snapshot_metadata(snapshot),
        "events": [{
            "title": "Finding the envelope",
            "description": "I found the envelope while living in Cedarport.",
            "subject": "self",
            "places": ["Cedarport"],
            "when_hint": None,
            "anchor": None,
            "date": None,
            "timeline_relation": None,
        }],
    })


def run_real_context_scenario() -> dict:
    """Exercise real catalog/snapshot invalidation over durable synthetic records."""
    with tempfile.TemporaryDirectory(prefix="lifehug-archive-real-context-") as temporary:
        root = Path(temporary)
        sources = root / "sources" / "manual"
        classifications = root / "state" / "classifications"
        rosters = root / "state" / "entity_rosters"
        answers = root / "answers"
        candidate_store = root / "state" / "question_candidates.json"
        sources.mkdir(parents=True)
        classifications.mkdir(parents=True)
        rosters.mkdir(parents=True)
        answers.mkdir()
        candidate_store.write_text(
            json.dumps({
                "version": 1,
                "candidates": [{
                    "id": "cand-related-1",
                    "text": "What did the envelope contain?",
                    "source_path": "sources/manual/related.md",
                    "status": "candidate",
                }],
            }),
            encoding="utf-8",
        )
        related = sources / "related.md"
        unrelated = sources / "unrelated.md"
        related.write_text(
            "---\ntitle: Cedarport envelope\n---\n"
            "I found the envelope while we lived in Cedarport.\n",
            encoding="utf-8",
        )
        unrelated.write_text(
            "---\ntitle: Orchard notebook\n---\n"
            "I catalogued the orchard notebook while we lived in Orchardvale.\n",
            encoding="utf-8",
        )
        place_roster = {
            "version": 1,
            "type": "place",
            "entities": [
                {"name": "Cedarport", "slug": "cedarport", "aliases": []},
                {"name": "Orchardvale", "slug": "orchardvale", "aliases": []},
            ],
        }
        (rosters / "place.json").write_text(json.dumps(place_roster), encoding="utf-8")
        landmark_projection.file_landmark_record(
            root, "residences", {
                "domain": "residences",
                "label": "Orchardvale",
                "city": "Orchardvale",
                "span": {"start": date("1988"), "end": date("1990")},
            }, ordinal=0, now="2026-09-16T00:59:00Z",
        )
        publication.publish(root, roster_snapshot=place_roster, now="2026-09-16T01:00:00Z")

        telling_ref = "classification:sources-manual-related#aaaaaaaaaaaa"
        event_identity.write_telling_manifest(root, {
            "tellings": [{
                "telling_ref": telling_ref,
                "source_path": "sources/manual/related.md",
                "event_refs": [],
                "era_refs": [],
                "aliases": [],
                "bound_identity_ids": [],
            }],
        })
        identity, created = event_identity.file_event_identity(
            root,
            telling_ref=telling_ref,
            episode_id="episode:" + "a" * 24,
            relation="not_same",
            origin="confirmed",
            source_ref="sources/manual/related.md",
            created_at="2026-09-16T01:01:00Z",
        )
        assert created
        identity_path = root / identity["relative_path"]
        identity_bytes = identity_path.read_bytes()

        preserved = {
            "people": [{"name": "Owner", "slug": "owner"}],
            "places": [{"name": "Cedarport", "slug": "cedarport"}],
            "themes": ["memory"],
            "suggested_sensitivity": "private",
            "sensitivity_reason": "owner decision",
            "candidate_question_ids": ["cand-related-1"],
            "owner_note": "preserve this non-temporal field",
        }
        for source in (related, unrelated):
            snapshot = cc.build_context_snapshot(root, source)
            value = {
                "version": 2,
                "source_path": source.relative_to(root).as_posix(),
                "events": [{"title": "Existing event", "description": "Existing reading."}],
                "classification_snapshot": cc.snapshot_metadata(snapshot),
                "classified_at": "2026-09-16T01:02:00Z",
                "model_used": "synthetic-recorded-model",
            }
            if source == related:
                value.update(preserved)
            (classifications / f"{cs.classify_stem(source)}.json").write_text(
                json.dumps(value), encoding="utf-8"
            )
        unrelated_path = classifications / f"{cs.classify_stem(unrelated)}.json"
        unrelated_bytes = unrelated_path.read_bytes()

        transitions: list[dict] = []
        batch_index = 0

        def refresh(label: str) -> None:
            nonlocal batch_index
            batch_index += 1
            plan = cs.build_batch_plan(
                limit=10, sources=[related, unrelated], skip_candidates=True
            )
            assert plan["pending_count"] == 1, plan
            assert plan["selected_count"] == 1
            assert plan["items"][0]["source_path"] == "sources/manual/related.md"
            assert plan["items"][0]["mode"] == "timeline"
            related_snapshot = cc.build_context_snapshot(root, related)
            assert related_snapshot["candidates"]
            unrelated_snapshot = cc.build_context_snapshot(root, unrelated)
            unrelated_value = json.loads(unrelated_path.read_text(encoding="utf-8"))
            assert cc.refresh_reason(unrelated_snapshot, unrelated_value) is None
            receipt = cs.file_batch_response({
                "schema_version": 1,
                "batch_id": f"real-context-{batch_index}",
                "skip_candidates": True,
                "items": [{
                    "source_path": "sources/manual/related.md",
                    "mode": "timeline",
                    "response_text": _timeline_response(related_snapshot),
                }],
            }, model="synthetic-recorded-model")
            assert receipt["counts"] == {
                "accepted": 1, "refused": 0, "already_current": 0,
            }
            refreshed = json.loads(
                (classifications / f"{cs.classify_stem(related)}.json").read_text(encoding="utf-8")
            )
            for key, value in preserved.items():
                assert refreshed[key] == value
            assert unrelated_path.read_bytes() == unrelated_bytes
            assert identity_path.read_bytes() == identity_bytes
            assert related_snapshot["human_identity_decisions"][0]["identity_id"] == identity["identity_id"]
            assert related_snapshot["prior_event_identities"][0]["telling_ref"] == telling_ref
            transitions.append({
                "transition": label,
                "candidate_count": len(related_snapshot["candidates"]),
                "unrelated_current": True,
            })

        with contextlib.ExitStack() as stack:
            for name, value in (
                ("REPO_DIR", root),
                ("SOURCES_DIR", root / "sources"),
                ("MANUAL_SOURCES_DIR", sources),
                ("ANSWERS_DIR", answers),
                ("CLASSIFICATIONS_DIR", classifications),
                ("QUESTION_CANDIDATES_FILE", candidate_store),
            ):
                stack.enter_context(mock.patch.object(cs, name, value))
            stack.enter_context(mock.patch.object(cs, "load_mission", return_value="Synthetic mission."))

            landmark_projection.file_landmark_record(
                root, "residences", {
                    "domain": "residences",
                    "label": "Cedarport",
                    "city": "Cedarport",
                    "span": {"start": date("1994"), "end": date("1998")},
                }, ordinal=1, now="2026-09-16T01:03:00Z",
            )
            publication.publish(root, roster_snapshot=place_roster, now="2026-09-16T01:04:00Z")
            refresh("initial_anchor_added")

            competing = landmark_projection.file_landmark_record(
                root, "residences", {
                    "domain": "residences",
                    "label": "Cedarport",
                    "city": "Cedarport",
                    "span": {"start": date("2001"), "end": date("2004")},
                }, ordinal=2, now="2026-09-16T01:05:00Z",
            )
            publication.publish(root, roster_snapshot=place_roster, now="2026-09-16T01:06:00Z")
            refresh("competing_anchor_added")

            store.supersede_claims(
                root,
                [row["claim_id"] for row in competing["claims"]],
                reason="Replace the synthetic competing stay with corrected dates.",
                occurred_at="2026-09-16T01:07:00Z",
            )
            changed = landmark_projection.file_landmark_record(
                root, "residences", {
                    "domain": "residences",
                    "label": "Cedarport",
                    "city": "Cedarport",
                    "span": {"start": date("2002"), "end": date("2005")},
                }, ordinal=3, now="2026-09-16T01:08:00Z",
            )
            publication.publish(root, roster_snapshot=place_roster, now="2026-09-16T01:09:00Z")
            refresh("competing_anchor_changed")

            store.retract_claims(
                root,
                [row["claim_id"] for row in changed["claims"]],
                reason="Remove the synthetic competing stay.",
                occurred_at="2026-09-16T01:10:00Z",
            )
            publication.publish(root, roster_snapshot=place_roster, now="2026-09-16T01:11:00Z")
            refresh("competing_anchor_removed")
            assert cs.build_batch_plan(
                limit=10, sources=[related, unrelated], skip_candidates=True
            )["pending_count"] == 0

        return {
            "context_provider": "canonical-real-catalog-and-snapshot",
            "recorded_model_responses": True,
            "transitions": transitions,
            "non_temporal_fields_preserved": True,
            "candidate_ids_preserved": True,
            "owner_identity_decision_preserved": True,
        }


def run(count: int = 500) -> dict:
    if count != 500:
        raise ValueError("the contracted walkthrough count is exactly 500")
    with tempfile.TemporaryDirectory(prefix="lifehug-archive-batch-") as temporary:
        root = Path(temporary)
        sources = root / "sources" / "manual"
        answers = root / "answers"
        classifications = root / "state" / "classifications"
        candidates = root / "state" / "question_candidates.json"
        sources.mkdir(parents=True)
        answers.mkdir()
        classifications.mkdir(parents=True)
        candidates.write_text('{"version":1,"candidates":[]}\n', encoding="utf-8")
        source_paths = []
        context_versions: dict[str, str] = {}
        for index in range(count):
            path = sources / f"story-{index:03d}.md"
            path.write_text(
                f"---\ntitle: Synthetic story {index}\n---\n"
                f"I recorded synthetic event {index} in the year {1980 + index % 40}.\n",
                encoding="utf-8",
            )
            source_paths.append(path)
            context_versions[str(path)] = "1"

        def snap(_root, source, _catalog):
            path = Path(source)
            version = context_versions[str(path)]
            return {
                "schema_version": 1,
                "source_revision": cc.source_revision(path),
                "context_digest": "sha256:" + version.rjust(64, "0"),
                "prompt_version": cc.PROMPT_VERSION,
                "extractor_version": cc.EXTRACTOR_VERSION,
                "context_complete": True,
                "context_truncated": False,
                "remaining_candidate_count": 0,
                "catalog_omitted_count": 0,
                "remaining_decision_count": 0,
                "candidates": [],
                "human_identity_decisions": [],
                "prior_event_identities": [],
            }

        def response(path: Path, mode: str) -> dict:
            value = {
                "_classification_mode": mode,
                "_classification_snapshot": cc.snapshot_metadata(snap(root, path, {})),
                "events": [{
                    "title": f"Synthetic event {path.stem}",
                    "description": f"The event in {path.stem} happened.",
                    "subject": "self",
                    "places": [],
                    "when_hint": None,
                    "anchor": None,
                    "date": {
                        "stated": str(1980 + int(path.stem[-3:]) % 40),
                        "age": None,
                        "anchor_ref": None,
                        "relation": None,
                    },
                    "timeline_relation": None,
                }],
            }
            if mode == "full":
                value.update({
                    "people": [], "places": [], "time_periods": [],
                    "themes": ["adventure"], "projects": [],
                    "contradictions": [], "possible_outputs": [],
                    "focus_opportunities": [], "self_understanding_insights": [],
                    "suggested_sensitivity": "private",
                    "sensitivity_reason": "synthetic walkthrough",
                    "scene_slots": {}, "situation_vs_story": "balanced",
                    "candidate_questions": [],
                })
            return value

        timings = {"validation": 0.0, "application": 0.0}
        counts = {"validation_calls": 0, "application_calls": 0}

        def measured(name, original):
            def wrapper(*args, **kwargs):
                started = time.perf_counter()
                try:
                    return original(*args, **kwargs)
                finally:
                    timings[name] += time.perf_counter() - started
                    counts[f"{name}_calls"] += 1
            return wrapper

        with contextlib.ExitStack() as stack:
            for name, value in (
                ("REPO_DIR", root),
                ("SOURCES_DIR", root / "sources"),
                ("MANUAL_SOURCES_DIR", sources),
                ("ANSWERS_DIR", answers),
                ("CLASSIFICATIONS_DIR", classifications),
                ("QUESTION_CANDIDATES_FILE", candidates),
            ):
                stack.enter_context(mock.patch.object(cs, name, value))
            stack.enter_context(mock.patch.object(cs, "load_mission", return_value="Synthetic mission."))
            stack.enter_context(mock.patch.object(cc, "load_context_catalog", return_value={}))
            stack.enter_context(mock.patch.object(cc, "build_context_snapshot_from_catalog", side_effect=snap))
            stack.enter_context(mock.patch.object(
                cs, "prepare_classification", measured("validation", cs.prepare_classification)
            ))
            stack.enter_context(mock.patch.object(
                cs, "apply_prepared_classification", measured("application", cs.apply_prepared_classification)
            ))

            started = time.perf_counter()
            first_plan = cs.build_batch_plan(limit=500, skip_candidates=True)
            planning_seconds = time.perf_counter() - started
            assert first_plan["selected_count"] == count
            envelope = {
                "schema_version": 1,
                "batch_id": "synthetic-first-pass",
                "skip_candidates": True,
                "items": [{
                    "source_path": path.relative_to(root).as_posix(),
                    "mode": "full",
                    "response_text": json.dumps(response(path, "full")),
                } for path in source_paths],
            }
            started = time.perf_counter()
            filed = cs.file_batch_response(envelope, model="synthetic-recorded-model")
            filing_seconds = time.perf_counter() - started
            assert filed["counts"]["accepted"] == count
            first_pass_counts = dict(counts)
            first_pass_timings = dict(timings)

            started = time.perf_counter()
            migration = classifier_claims.migrate_classifier_moments(
                root,
                classifications_dir=classifications,
                dry_run=False,
                publish=False,
                now="2026-09-16T00:00:00Z",
            )
            migration_seconds = time.perf_counter() - started
            index = store.read_active_index(root)
            started = time.perf_counter()
            projected = publication.publish(
                root,
                active_index=index,
                constraints=(),
                event_resolution_records=(),
                episode_records=(),
                era_views=(),
                membership_assertions=(),
                display_decisions=(),
                frame_display_decisions=(),
                landmark_entries=(),
                now="2026-09-16T00:01:00Z",
            )
            projection_seconds = time.perf_counter() - started

            unchanged = cs.build_batch_plan(limit=500, skip_candidates=True)
            assert unchanged["pending_count"] == 0

            changed_path = source_paths[0]
            context_versions[str(changed_path)] = "2"
            changed_plan = cs.build_batch_plan(limit=500, skip_candidates=True)
            assert changed_plan["pending_count"] == 1
            assert changed_plan["items"][0]["mode"] == "timeline"
            changed_envelope = {
                "schema_version": 1,
                "batch_id": "synthetic-context-change",
                "skip_candidates": True,
                "items": [{
                    "source_path": changed_path.relative_to(root).as_posix(),
                    "mode": "timeline",
                    "response_text": json.dumps(response(changed_path, "timeline")),
                }],
            }
            cs.file_batch_response(changed_envelope, model="synthetic-recorded-model")

            added = sources / "story-500.md"
            added.write_text(
                "---\ntitle: Added synthetic story\n---\nA newly added synthetic event in 2020.\n",
                encoding="utf-8",
            )
            context_versions[str(added)] = "1"
            added_plan = cs.build_batch_plan(limit=500, skip_candidates=True)
            assert added_plan["pending_count"] == 1
            assert added_plan["items"][0]["mode"] == "full"

        return {
            "schema_version": 1,
            "fixture": "synthetic-recorded-model-with-context-provider-stub",
            "fixture_limitations": (
                "The 500-source timing isolates batching overhead with a deterministic "
                "snapshot stub; real context invalidation is proven separately below."
            ),
            "source_count": count,
            "model_work": {
                "first_build": first_plan["selected_count"],
                "no_change_rerun": unchanged["selected_count"],
                "changed_relevant_landmark": changed_plan["selected_count"],
                "added_story": added_plan["selected_count"],
            },
            "counts": {
                **first_pass_counts,
                "claims": migration["claims"],
                "projected_nodes": projected["nodes"],
            },
            "timings_seconds": {
                "planning": planning_seconds,
                "validation_inside_first_pass_filing": first_pass_timings["validation"],
                "application_inside_first_pass_filing": first_pass_timings["application"],
                "filing_total": filing_seconds,
                "claim_migration": migration_seconds,
                "projection": projection_seconds,
            },
            "real_context": run_real_context_scenario(),
        }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sources", type=int, default=500, choices=(500,))
    args = parser.parse_args()
    print(json.dumps(run(args.sources), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
