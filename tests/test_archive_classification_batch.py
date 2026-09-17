"""Canonical archive classifier batch tests. All data is synthetic."""

from __future__ import annotations

import copy
import hashlib
import io
import json
import sys
import tempfile
import unittest
from contextlib import ExitStack, redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "system"))

import classifier_context as cc  # noqa: E402
import classify_story as cs  # noqa: E402
import timeline_evidence as te  # noqa: E402


def snapshot(source: Path, context: str = "context-1") -> dict:
    return {
        "schema_version": 1,
        "source_revision": cc.source_revision(source),
        "context_digest": "sha256:" + hashlib.sha256(context.encode()).hexdigest(),
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


def full_response(
    snap: dict,
    *,
    events: list[dict] | None = None,
    candidate_questions: list[dict] | None = None,
) -> dict:
    normalized_events = []
    for supplied in events or ():
        event = copy.deepcopy(supplied)
        key = te.event_key(event)
        context = (snap.get("event_contexts") or {}).get(key) or te.build_event_context(
            event, [row for row in snap.get("candidates") or () if isinstance(row, dict)]
        )
        candidate_ids = list(context.get("candidate_ids") or [
            row["candidate_id"] for row in snap.get("candidates") or ()
        ])
        event.setdefault("source_grounding", None)
        event.setdefault("timeline_resolution", {
            "status": (
                "linked" if event.get("timeline_relation") is not None else
                "incomplete" if not context.get(
                    "complete", not snap.get("context_truncated")
                ) else "missing_evidence"
            ),
            "candidate_ids": candidate_ids,
            "reason": "Synthetic evidence-link outcome.",
        })
        normalized_events.append(event)
    return {
        "_classification_mode": "full",
        "_classification_snapshot": cc.snapshot_metadata(snap),
        "people": [],
        "places": [],
        "time_periods": [],
        "themes": ["adventure"],
        "projects": [],
        "contradictions": [],
        "possible_outputs": [],
        "focus_opportunities": [],
        "self_understanding_insights": [],
        "suggested_sensitivity": "private",
        "sensitivity_reason": "synthetic",
        "scene_slots": {},
        "situation_vs_story": "balanced",
        "events": normalized_events,
        "candidate_questions": [] if candidate_questions is None else candidate_questions,
    }


def timeline_delta(event: dict, snap: dict, *, status: str = "missing_evidence") -> dict:
    key = te.event_key(event)
    context = (snap.get("event_contexts") or {}).get(key) or {}
    candidate_ids = list(context.get("candidate_ids") or [
        row["candidate_id"] for row in snap.get("candidates") or ()
    ])
    return {
        "event_key": key,
        "source_grounding": None,
        "timeline_relation": None,
        "timeline_resolution": {
            "status": status,
            "candidate_ids": candidate_ids,
            "reason": "Synthetic evidence-link outcome.",
        },
    }


class ArchiveClassificationBatchTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="lifehug-archive-batch-")
        self.root = Path(self.tmp.name)
        self.sources = self.root / "sources"
        self.answers = self.root / "answers"
        self.classifications = self.root / "state" / "classifications"
        self.candidates = self.root / "state" / "question_candidates.json"
        (self.sources / "manual").mkdir(parents=True)
        self.answers.mkdir()
        self.classifications.mkdir(parents=True)
        self.a = self.sources / "manual" / "alpha.md"
        self.b = self.sources / "manual" / "bravo.md"
        self.a.write_text("---\ntitle: Alpha\n---\nA synthetic first story.\n", encoding="utf-8")
        self.b.write_text("---\ntitle: Bravo\n---\nA synthetic second story.\n", encoding="utf-8")
        self.candidates.write_text('{"version": 1, "candidates": []}\n', encoding="utf-8")
        self.stack = ExitStack()
        for name, value in (
            ("REPO_DIR", self.root),
            ("SOURCES_DIR", self.sources),
            ("MANUAL_SOURCES_DIR", self.sources / "manual"),
            ("ANSWERS_DIR", self.answers),
            ("CLASSIFICATIONS_DIR", self.classifications),
            ("QUESTION_CANDIDATES_FILE", self.candidates),
        ):
            self.stack.enter_context(mock.patch.object(cs, name, value))
        self.stack.enter_context(mock.patch.object(cs, "load_mission", return_value="Synthetic mission."))

    def tearDown(self) -> None:
        self.stack.close()
        self.tmp.cleanup()

    def existing(self, source: Path, snap: dict, **extra) -> dict:
        value = {
            "version": 2,
            "source_path": source.relative_to(self.root).as_posix(),
            "source_title": source.stem,
            "source_type": "story",
            "classified_at": "2026-01-01T00:00:00Z",
            "model_used": "synthetic-old",
            "reviewable": True,
            "candidate_question_ids": ["cand-preserved-1"],
            "classification_snapshot": cc.snapshot_metadata(snap),
            "people": [{"name": "Preserved Person"}],
            "places": [],
            "time_periods": [],
            "themes": ["legacy"],
            "projects": [],
            "contradictions": ["preserve me"],
            "possible_outputs": [],
            "focus_opportunities": [],
            "self_understanding_insights": ["preserve me"],
            "suggested_sensitivity": "friends",
            "sensitivity_reason": "preserve me",
            "scene_slots": {"what_happened": True},
            "situation_vs_story": "balanced",
            "events": [{
                "title": "Old event",
                "description": "A synthetic first story.",
                "subject": "self",
                "places": [],
                "when_hint": None,
                "anchor": None,
                "date": None,
                "custom_field": "preserve exactly",
            }],
        }
        value.update(extra)
        cs.write_json(cs.classification_path(source), value)
        return value

    def catalogs(self, snapshots: dict[Path, dict]):
        return (
            mock.patch.object(cc, "load_context_catalog", return_value={"synthetic": True}),
            mock.patch.object(
                cc,
                "build_context_snapshot_from_catalog",
                side_effect=lambda _root, source, _catalog: snapshots[Path(source)],
            ),
        )

    def envelope(self, batch_id: str, items: list[dict], *, skip: bool = True) -> dict:
        return {
            "schema_version": 1,
            "batch_id": batch_id,
            "skip_candidates": skip,
            "items": items,
        }

    def write_correction(self, name: str, body: str) -> None:
        corrections = self.sources / "corrections"
        corrections.mkdir(parents=True, exist_ok=True)
        (corrections / f"{name}.md").write_text(
            "---\n"
            'type: "source_correction"\n'
            f'source_id: "correction:{name}"\n'
            f'source_path: "sources/corrections/{name}.md"\n'
            'corrects_path: "sources/manual/alpha.md"\n'
            'correction_kind: "factual"\n'
            "---\n\n"
            f"# Synthetic correction\n\n{body}\n",
            encoding="utf-8",
        )

    def test_plan_loads_one_catalog_and_uses_full_and_timeline_modes(self) -> None:
        current_a = snapshot(self.a)
        old_b = snapshot(self.b, "old")
        current_b = snapshot(self.b, "new")
        self.existing(self.b, old_b)
        load, build = self.catalogs({self.a: current_a, self.b: current_b})
        with load as loaded, build:
            plan = cs.build_batch_plan(limit=500, skip_candidates=True)
        self.assertEqual(loaded.call_count, 1)
        self.assertEqual(plan["selected_count"], 2)
        self.assertEqual({row["mode"] for row in plan["items"]}, {"full", "timeline"})
        self.assertTrue(plan["skip_candidates"])
        full_prompt = next(row["prompt"] for row in plan["items"] if row["mode"] == "full")
        timeline_prompt = next(
            row["prompt"] for row in plan["items"] if row["mode"] == "timeline"
        )
        self.assertNotIn('"candidate_questions"', full_prompt)
        self.assertNotIn("Question-Judgment Rubric", full_prompt)
        self.assertIn('"event_contexts": {}', full_prompt)
        self.assertIn("provisional full-extraction", full_prompt)
        self.assertIn("context is retrieval input", full_prompt)
        self.assertNotIn("across the ENTIRE supplied candidate list", full_prompt)
        self.assertIn('"event_contexts": {}', timeline_prompt)
        self.assertIn("Treat each `event_contexts[event_key]` entry independently", timeline_prompt)
        for prompt in (full_prompt, timeline_prompt):
            normalized = " ".join(prompt.split())
            self.assertIn("Timeline Evidence Uses Two Independent Decisions", normalized)
            self.assertIn("does NOT need a calendar date or age", normalized)
            self.assertIn(
                "an empty candidate set for a real event is `missing_evidence`",
                normalized,
            )
            self.assertIn("`incomplete` is allowed ONLY", normalized)
            self.assertIn("Prefer the most specific relation", normalized)
            self.assertIn("preserve the supported `before` relation", normalized)
            self.assertIn(
                "CURRENT EXTRACTED EVENT relative to SELECTED CANDIDATE",
                normalized,
            )
            self.assertIn("FIRST test whether a supplied candidate", normalized)
            self.assertIn("candidate's WHOLE occurrence", normalized)
            self.assertIn("before that duration starts", normalized)
            self.assertIn("after it ends", normalized)
            self.assertIn('"early in", and "late in"', normalized)
            self.assertIn('"After the wedding"', normalized)
            self.assertIn("date.anchor_ref", normalized)
            self.assertIn("TIGHTEST SUPPORTED TIME BOUNDS", normalized)
            self.assertIn("a one-sided open interval", normalized)
            self.assertIn(
                f"1-{te.MAX_RESOLUTION_REASON_CHARS} character explanation",
                normalized,
            )
            self.assertIn(
                f"{te.MAX_RESOLUTION_REASON_CHARS} characters",
                normalized,
            )

    def test_plan_builds_prompts_only_for_selected_items_and_names_ineligible(self) -> None:
        empty = self.sources / "manual" / "empty.md"
        empty.write_text("---\ntitle: Empty\n---\n", encoding="utf-8")
        snapshots = {self.a: snapshot(self.a), self.b: snapshot(self.b)}
        load, build = self.catalogs(snapshots)
        with load, build, mock.patch.object(cs, "build_prompt", wraps=cs.build_prompt) as prompt:
            plan = cs.build_batch_plan(limit=1, skip_candidates=True)
        self.assertEqual(prompt.call_count, 1)
        self.assertEqual(plan["selected_count"], 1)
        self.assertEqual(plan["pending_count"], 2)
        self.assertEqual(plan["remaining_count"], 1)
        self.assertEqual(plan["ineligible_count"], 1)
        self.assertEqual(plan["ineligible_items"], [{
            "source_path": "sources/manual/empty.md",
            "refusal_code": "source_empty",
        }])
        self.assertEqual(plan["inventory_scope"], "all")

    def test_exact_exclusion_advances_past_a_refused_first_page(self) -> None:
        snapshots = {self.a: snapshot(self.a), self.b: snapshot(self.b)}
        load, build = self.catalogs(snapshots)
        with load, build:
            first = cs.build_batch_plan(limit=1, skip_candidates=True)
        self.assertEqual(first["items"][0]["source_path"], "sources/manual/alpha.md")
        exclusion = [{
            "source_path": first["items"][0]["source_path"],
            "snapshot": first["items"][0]["snapshot"],
        }]
        load, build = self.catalogs(snapshots)
        with load, build:
            second = cs.build_batch_plan(
                limit=1, skip_candidates=True, exclude_items=exclusion
            )
        self.assertEqual(second["pending_count"], 2)
        self.assertEqual(second["excluded_count"], 1)
        self.assertEqual(second["selected_count"], 1)
        self.assertEqual(second["remaining_count"], 0)
        self.assertEqual(second["items"][0]["source_path"], "sources/manual/bravo.md")

    def test_changed_snapshot_does_not_match_an_old_exclusion(self) -> None:
        before = snapshot(self.a, "before")
        exclusion = [{
            "source_path": "sources/manual/alpha.md",
            "snapshot": cc.snapshot_metadata(before),
        }]
        changed = snapshot(self.a, "changed")
        load, build = self.catalogs({self.a: changed})
        with load, build:
            plan = cs.build_batch_plan(
                limit=1,
                sources=[self.a],
                skip_candidates=True,
                exclude_items=exclusion,
            )
        self.assertEqual(plan["pending_count"], 1)
        self.assertEqual(plan["excluded_count"], 0)
        self.assertEqual(plan["selected_count"], 1)
        self.assertEqual(plan["items"][0]["snapshot"], cc.snapshot_metadata(changed))

    def test_exclusion_document_is_closed_identity_bound_and_bounded(self) -> None:
        relative = "sources/manual/alpha.md"
        current = cc.snapshot_metadata(snapshot(self.a))
        with self.assertRaises(cs.ClassificationPreparationError) as path_only:
            cs._normalize_exclude_items([{"source_path": relative}])
        self.assertEqual(path_only.exception.code, "exclude_schema_invalid")
        malformed = {**current, "context_digest": "context-only"}
        with self.assertRaises(cs.ClassificationPreparationError) as bad_snapshot:
            cs._normalize_exclude_items([{
                "source_path": relative, "snapshot": malformed,
            }])
        self.assertEqual(bad_snapshot.exception.code, "exclude_schema_invalid")
        item = {"source_path": relative, "snapshot": current}
        with self.assertRaises(cs.ClassificationPreparationError) as duplicate:
            cs._normalize_exclude_items([item, item])
        self.assertEqual(duplicate.exception.code, "duplicate_exclude_item")
        transport = self.root / "exclude.json"
        valid_document = {"schema_version": 1, "items": [item]}
        transport.write_text(json.dumps(valid_document), encoding="utf-8")
        self.assertEqual(cs._exclude_items(str(transport)), [item])
        parsed = cs.build_parser().parse_args([
            "--batch-plan", "--exclude-items-json", str(transport),
            "--require-candidates",
        ])
        self.assertEqual(parsed.exclude_items_json, str(transport))
        self.assertTrue(parsed.require_candidates)
        transport.write_text(json.dumps({"items": [item]}), encoding="utf-8")
        with self.assertRaises(cs.ClassificationPreparationError) as unversioned:
            cs._exclude_items(str(transport))
        self.assertEqual(unversioned.exception.code, "exclude_schema_invalid")
        transport.write_bytes(b"x" * 9)
        with mock.patch.object(cs, "MAX_EXCLUDE_ITEMS_BYTES", 8):
            with self.assertRaises(cs.ClassificationPreparationError) as oversized:
                cs._exclude_items(str(transport))
        self.assertEqual(oversized.exception.code, "input_too_large")

    def test_partial_refusal_keeps_old_item_and_commits_valid_sibling(self) -> None:
        old_a = snapshot(self.a, "old")
        current_a = snapshot(self.a, "new")
        current_b = snapshot(self.b)
        prior = self.existing(self.a, old_a)
        prior_bytes = cs.classification_path(self.a).read_bytes()
        load, build = self.catalogs({self.a: current_a, self.b: current_b})
        payload = self.envelope("partial-one", [
            {"source_path": "sources/manual/alpha.md", "mode": "timeline", "response_text": "not json"},
            {"source_path": "sources/manual/bravo.md", "mode": "full", "response_text": json.dumps(full_response(current_b))},
        ])
        with load, build:
            report = cs.file_batch_response(payload)
        self.assertEqual(report["counts"], {"accepted": 1, "refused": 1, "already_current": 0})
        self.assertEqual(cs.classification_path(self.a).read_bytes(), prior_bytes)
        self.assertEqual(json.loads(cs.classification_path(self.a).read_text()), prior)
        self.assertEqual(json.loads(cs.classification_path(self.b).read_text())["themes"], ["adventure"])
        self.assertTrue((self.root / report["receipt_path"]).is_file())

    def test_timeline_refresh_preserves_every_non_timeline_field_and_candidate_id(self) -> None:
        old = snapshot(self.a, "old")
        current = snapshot(self.a, "new")
        prior = self.existing(self.a, old, classification_skip_candidates=True)
        response = {
            "_classification_mode": "timeline",
            "_classification_snapshot": cc.snapshot_metadata(current),
            "events": [timeline_delta(prior["events"][0], current)],
        }
        load, build = self.catalogs({self.a: current})
        with load, build:
            report = cs.file_batch_response(self.envelope("timeline-one", [{
                "source_path": "sources/manual/alpha.md",
                "mode": "timeline",
                "response_text": json.dumps(response),
            }]))
        self.assertEqual(report["counts"]["accepted"], 1)
        filed = json.loads(cs.classification_path(self.a).read_text())
        for key, value in prior.items():
            if key not in {"events", "classification_snapshot", "classified_at", "model_used"}:
                self.assertEqual(filed[key], value, key)
        expected_event = copy.deepcopy(prior["events"][0])
        expected_event["event_key"] = te.event_key(expected_event)
        for key, value in expected_event.items():
            self.assertEqual(filed["events"][0][key], value, key)
        self.assertIsNone(filed["events"][0]["source_grounding"])
        self.assertIsNone(filed["events"][0]["timeline_relation"])
        self.assertEqual(
            filed["events"][0]["timeline_resolution"]["status"], "missing_evidence"
        )
        self.assertEqual(filed["events"][0]["custom_field"], "preserve exactly")
        self.assertTrue(filed[cs.CLASSIFICATION_SKIP_CANDIDATES_FIELD])

    def test_timeline_response_requires_exact_existing_event_keys_and_delta_fields(self) -> None:
        old = snapshot(self.a, "old")
        current = snapshot(self.a, "new")
        prior = self.existing(self.a, old)
        valid = timeline_delta(prior["events"][0], current)
        cases = {
            "omitted": [],
            "unknown": [{**valid, "event_key": "0" * 12}],
            "duplicate": [valid, copy.deepcopy(valid)],
            "replacement": [{**valid, "title": "Model rewrote extraction"}],
        }
        for index, (name, events) in enumerate(cases.items(), start=1):
            with self.subTest(name=name):
                response = {
                    "_classification_mode": "timeline",
                    "_classification_snapshot": cc.snapshot_metadata(current),
                    "events": events,
                }
                load, build = self.catalogs({self.a: current})
                with load, build:
                    receipt = cs.file_batch_response(self.envelope(
                        f"timeline-keys-{index}", [{
                            "source_path": "sources/manual/alpha.md",
                            "mode": "timeline",
                            "response_text": json.dumps(response),
                        }],
                    ))
                self.assertEqual(receipt["counts"]["refused"], 1)
                self.assertIn(
                    receipt["items"][0]["refusal_code"],
                    {"context_event_keys_invalid", "timeline_schema_invalid"},
                )
                self.assertEqual(json.loads(cs.classification_path(self.a).read_text()), prior)

    def test_relationship_prompt_change_selects_timeline_not_full(self) -> None:
        current = snapshot(self.a)
        prior_snapshot = {**current, "prompt_version": "contextual-timeline:1"}
        prior = self.existing(self.a, prior_snapshot)
        self.assertEqual(cc.refresh_reason(current, prior), "relationship_changed")
        self.assertEqual(cs.classification_mode(current, prior), "timeline")

    def test_full_skip_candidates_preserves_prior_candidate_ids(self) -> None:
        old = snapshot(self.a, "old")
        current = snapshot(self.a, "new")
        old["source_revision"] = "sha256:" + "0" * 64
        self.existing(self.a, old)
        load, build = self.catalogs({self.a: current})
        response = full_response(current)
        with load, build:
            cs.file_batch_response(self.envelope("skip-one", [{
                "source_path": "sources/manual/alpha.md",
                "mode": "full",
                "response_text": json.dumps(response),
            }]))
        filed = json.loads(cs.classification_path(self.a).read_text())
        self.assertEqual(filed["candidate_question_ids"], ["cand-preserved-1"])
        self.assertTrue(filed[cs.CLASSIFICATION_SKIP_CANDIDATES_FIELD])
        self.assertEqual(json.loads(self.candidates.read_text())["candidates"], [])

    def test_explicit_candidate_requirement_converges_once_without_default_refresh(self) -> None:
        current = snapshot(self.a)
        load, build = self.catalogs({self.a: current})
        with load, build:
            archive = cs.file_batch_response(self.envelope("archive-first", [{
                "source_path": "sources/manual/alpha.md",
                "mode": "full",
                "response_text": json.dumps(full_response(current)),
            }], skip=True))
        self.assertEqual(archive["items"][0]["status"], "accepted")
        archived = json.loads(cs.classification_path(self.a).read_text())
        current = {
            **current,
            **cc.snapshot_metadata_for_events(current, archived["events"]),
            "event_contexts": {},
        }
        self.assertTrue(archived[cs.CLASSIFICATION_SKIP_CANDIDATES_FIELD])
        self.assertIsNone(cc.refresh_reason(current, archived))
        with mock.patch.object(cc, "_load_context_catalog", return_value={}), \
                mock.patch.object(
                    cc, "_build_context_snapshot_from_catalog", return_value=current
                ):
            weekly = cc.select_refresh_targets(
                self.root,
                [self.a],
                classifications={"sources/manual/alpha.md": archived},
            )
        self.assertEqual(weekly["pending_count"], 0)

        load, build = self.catalogs({self.a: current})
        with load, build:
            default_plan = cs.build_batch_plan(sources=[self.a], skip_candidates=False)
        self.assertEqual(default_plan["pending_count"], 0)
        load, build = self.catalogs({self.a: current})
        with load, build:
            required_plan = cs.build_batch_plan(
                sources=[self.a],
                skip_candidates=False,
                require_candidates=True,
            )
        self.assertEqual(required_plan["pending_count"], 1)
        self.assertEqual(required_plan["items"][0]["reason"], "candidate_generation_needed")
        self.assertEqual(required_plan["items"][0]["mode"], "full")
        self.assertIn('"candidate_questions"', required_plan["items"][0]["prompt"])

        response = full_response(current, candidate_questions=[{
            "text": "What made this synthetic moment stay with you?",
            "story_function": "meaning",
            "priority": 0.8,
            "reason": "Synthetic candidate-generation proof.",
        }])
        load, build = self.catalogs({self.a: current})
        with load, build:
            ordinary = cs.file_batch_response(self.envelope("ordinary-after-archive", [{
                "source_path": "sources/manual/alpha.md",
                "mode": "full",
                "response_text": json.dumps(response),
            }], skip=False))
        self.assertEqual(ordinary["items"][0]["status"], "accepted")
        filed = json.loads(cs.classification_path(self.a).read_text())
        self.assertFalse(filed[cs.CLASSIFICATION_SKIP_CANDIDATES_FIELD])
        self.assertEqual(len(filed["candidate_question_ids"]), 1)
        self.assertEqual(len(json.loads(self.candidates.read_text())["candidates"]), 1)

        load, build = self.catalogs({self.a: current})
        with load, build:
            converged = cs.build_batch_plan(
                sources=[self.a],
                skip_candidates=False,
                require_candidates=True,
            )
        self.assertEqual(converged["pending_count"], 0)

    def test_inflight_normal_full_response_survives_archive_first_race(self) -> None:
        current = snapshot(self.a)
        normal_payload = self.envelope("normal-inflight", [{
            "source_path": "sources/manual/alpha.md",
            "mode": "full",
            "response_text": json.dumps(full_response(current, candidate_questions=[{
                "text": "Which synthetic detail would you tell first?",
                "story_function": "scene",
                "priority": 0.7,
                "reason": "Synthetic in-flight response.",
            }])),
        }], skip=False)
        load, build = self.catalogs({self.a: current})
        with load, build:
            cs.file_batch_response(self.envelope("archive-wins-race", [{
                "source_path": "sources/manual/alpha.md",
                "mode": "full",
                "response_text": json.dumps(full_response(current)),
            }], skip=True))
        load, build = self.catalogs({self.a: current})
        with load, build:
            normal = cs.file_batch_response(normal_payload)
        self.assertEqual(normal["items"][0]["status"], "accepted")
        filed = json.loads(cs.classification_path(self.a).read_text())
        self.assertFalse(filed[cs.CLASSIFICATION_SKIP_CANDIDATES_FIELD])
        self.assertEqual(len(filed["candidate_question_ids"]), 1)

    def test_candidate_requirement_is_one_source_explicit_and_legacy_safe(self) -> None:
        current = snapshot(self.a)
        self.existing(self.a, current)
        load, build = self.catalogs({self.a: current})
        with load, build:
            legacy = cs.build_batch_plan(
                sources=[self.a], require_candidates=True, skip_candidates=False
            )
        self.assertEqual(legacy["pending_count"], 0)
        invalid_calls = (
            {"sources": None, "require_candidates": True},
            {"sources": [self.a, self.b], "require_candidates": True},
            {
                "sources": [self.a],
                "require_candidates": True,
                "skip_candidates": True,
            },
        )
        for kwargs in invalid_calls:
            with self.subTest(kwargs=kwargs), self.assertRaises(
                    cs.ClassificationPreparationError) as invalid:
                cs.build_batch_plan(**kwargs)
            self.assertEqual(invalid.exception.code, "candidate_request_scope_invalid")

    def test_default_timeline_refresh_preserves_archive_candidate_policy(self) -> None:
        old = snapshot(self.a, "old")
        current = snapshot(self.a, "new")
        self.existing(self.a, old, classification_skip_candidates=True)
        load, build = self.catalogs({self.a: current})
        with load, build:
            plan = cs.build_batch_plan(sources=[self.a], skip_candidates=False)
        self.assertEqual(plan["items"][0]["mode"], "timeline")
        response = {
            "_classification_mode": "timeline",
            "_classification_snapshot": cc.snapshot_metadata(current),
            "events": [timeline_delta(
                json.loads(cs.classification_path(self.a).read_text())["events"][0],
                current,
            )],
        }
        load, build = self.catalogs({self.a: current})
        with load, build:
            receipt = cs.file_batch_response(self.envelope("timeline-after-archive", [{
                "source_path": "sources/manual/alpha.md",
                "mode": "timeline",
                "response_text": json.dumps(response),
            }], skip=False))
        self.assertEqual(receipt["items"][0]["status"], "accepted")
        filed = json.loads(cs.classification_path(self.a).read_text())
        self.assertTrue(filed[cs.CLASSIFICATION_SKIP_CANDIDATES_FIELD])
        self.assertEqual(filed["candidate_question_ids"], ["cand-preserved-1"])
        self.assertEqual(json.loads(self.candidates.read_text())["candidates"], [])

    def test_correction_selects_full_mode_and_saved_old_response_is_refused(self) -> None:
        before = cc.build_context_snapshot(self.root, self.a)
        prior = self.existing(self.a, {**before, "source_revision": "sha256:" + "0" * 64})
        current = cc.build_context_snapshot(self.root, self.a)
        response = full_response(current)
        original_prepare = cs.prepare_classification
        calls = 0

        def prepare(*args, **kwargs):
            nonlocal calls
            calls += 1
            prepared = original_prepare(*args, **kwargs)
            if calls == 2:
                self.write_correction("arrived-during-model", "Alpha happened later.")
            return prepared

        with mock.patch.object(cs, "prepare_classification", side_effect=prepare):
            report = cs.file_batch_response(self.envelope("correction-race", [{
                "source_path": "sources/manual/alpha.md",
                "mode": "full",
                "response_text": json.dumps(response),
            }]))
        self.assertEqual(report["items"][0]["status"], "refused")
        self.assertEqual(report["items"][0]["refusal_code"], "source_context_race")
        self.assertEqual(json.loads(cs.classification_path(self.a).read_text()), prior)

        plan = cs.build_batch_plan(sources=[self.a], limit=1)
        self.assertEqual(plan["items"][0]["reason"], "source_changed")
        self.assertEqual(plan["items"][0]["mode"], "full")

    def test_exact_replay_is_noop_and_changed_body_conflicts(self) -> None:
        current = snapshot(self.a)
        load, build = self.catalogs({self.a: current})
        item = {"source_path": "sources/manual/alpha.md", "mode": "full", "response_text": json.dumps(full_response(current))}
        payload = self.envelope("replay-one", [item])
        with load, build:
            first = cs.file_batch_response(payload)
        before = cs.classification_path(self.a).read_bytes()
        second = cs.file_batch_response(payload)
        self.assertEqual(second, first)
        self.assertEqual(cs.classification_path(self.a).read_bytes(), before)
        changed = self.envelope("replay-one", [{**item, "response_text": item["response_text"] + " "}])
        with self.assertRaisesRegex(cs.ClassificationPreparationError, "different input"):
            cs.file_batch_response(changed)

    def test_public_receipt_validator_binds_closed_ordered_envelope(self) -> None:
        snapshots = {self.a: snapshot(self.a), self.b: snapshot(self.b)}
        payload = self.envelope("validate-one", [
            {
                "source_path": "sources/manual/bravo.md",
                "mode": "full",
                "response_text": json.dumps(full_response(snapshots[self.b])),
            },
            {
                "source_path": "sources/manual/alpha.md",
                "mode": "full",
                "response_text": json.dumps(full_response(snapshots[self.a])),
            },
        ])
        load, build = self.catalogs(snapshots)
        with load, build:
            receipt = cs.file_batch_response(payload)
        with mock.patch.object(
                cs, "_safe_source_path", side_effect=AssertionError("not pure")):
            self.assertIs(cs.validate_batch_receipt(payload, receipt), receipt)
        self.assertEqual(
            [row["source_path"] for row in receipt["items"]],
            ["sources/manual/bravo.md", "sources/manual/alpha.md"],
        )

        cases = {}
        changed = copy.deepcopy(receipt)
        changed.pop("counts")
        cases["missing top field"] = changed
        changed = copy.deepcopy(receipt)
        changed["unexpected"] = True
        cases["extra top field"] = changed
        changed = copy.deepcopy(receipt)
        changed["schema_version"] = 2
        cases["schema"] = changed
        changed = copy.deepcopy(receipt)
        changed["schema_version"] = True
        cases["boolean schema"] = changed
        changed = copy.deepcopy(receipt)
        changed["batch_id"] = "different"
        cases["batch id"] = changed
        changed = copy.deepcopy(receipt)
        changed["skip_candidates"] = False
        cases["skip policy"] = changed
        changed = copy.deepcopy(receipt)
        changed["input_digest"] = "sha256:" + "0" * 64
        cases["top digest"] = changed
        changed = copy.deepcopy(receipt)
        changed["receipt_path"] = "state/classification_batches/other.json"
        cases["receipt path"] = changed
        changed = copy.deepcopy(receipt)
        changed["items"].reverse()
        cases["item order"] = changed
        changed = copy.deepcopy(receipt)
        changed["items"][0]["source_path"] = "sources/manual/alpha.md"
        cases["duplicate source"] = changed
        changed = copy.deepcopy(receipt)
        changed["items"][0]["source_path"] = "sources/manual/other.md"
        cases["source"] = changed
        changed = copy.deepcopy(receipt)
        changed["items"][0]["mode"] = "timeline"
        cases["mode"] = changed
        changed = copy.deepcopy(receipt)
        changed["items"][0]["input_digest"] = "sha256:" + "0" * 64
        cases["item digest"] = changed
        changed = copy.deepcopy(receipt)
        changed["items"][0].pop("refusal_code")
        cases["missing item field"] = changed
        changed = copy.deepcopy(receipt)
        changed["items"][0]["extra"] = True
        cases["extra item field"] = changed
        changed = copy.deepcopy(receipt)
        changed["items"][0]["status"] = "unknown"
        cases["status"] = changed
        changed = copy.deepcopy(receipt)
        changed["items"][0]["status"] = []
        cases["unhashable status"] = changed
        changed = copy.deepcopy(receipt)
        changed["items"][0]["refusal_code"] = "not-allowed"
        cases["successful refusal code"] = changed
        changed = copy.deepcopy(receipt)
        changed["items"][0]["status"] = "refused"
        changed["items"][0]["refusal_code"] = None
        cases["missing refusal code"] = changed
        changed = copy.deepcopy(receipt)
        changed["counts"]["accepted"] -= 1
        cases["counts"] = changed
        changed = copy.deepcopy(receipt)
        changed["counts"]["refused"] = False
        cases["boolean count"] = changed
        for label, changed in cases.items():
            with self.subTest(label=label), self.assertRaises(
                    cs.ClassificationPreparationError) as invalid:
                cs.validate_batch_receipt(payload, changed)
            self.assertEqual(invalid.exception.code, "receipt_invalid")

        malformed_envelopes = (
            {key: value for key, value in payload.items() if key != "items"},
            {**payload, "unexpected": True},
        )
        for changed in malformed_envelopes:
            with self.assertRaises(cs.ClassificationPreparationError) as invalid:
                cs.validate_batch_receipt(changed, receipt)
            self.assertEqual(invalid.exception.code, "batch_schema_invalid")

    def test_receipt_validator_rejects_changed_envelope_identity(self) -> None:
        current = snapshot(self.a)
        item = {
            "source_path": "sources/manual/alpha.md",
            "mode": "full",
            "response_text": json.dumps(full_response(current)),
        }
        payload = self.envelope("envelope-binding", [item])
        load, build = self.catalogs({self.a: current})
        with load, build:
            receipt = cs.file_batch_response(payload)
        changed_envelopes = {
            "source": self.envelope("envelope-binding", [{
                **item, "source_path": "sources/manual/bravo.md",
            }]),
            "mode": self.envelope("envelope-binding", [{**item, "mode": "timeline"}]),
            "skip": self.envelope("envelope-binding", [item], skip=False),
            "response": self.envelope("envelope-binding", [{
                **item, "response_text": item["response_text"] + " ",
            }]),
            "extra": self.envelope("envelope-binding", [{**item, "extra": True}]),
        }
        for label, changed in changed_envelopes.items():
            with self.subTest(label=label), self.assertRaises(
                    cs.ClassificationPreparationError) as invalid:
                cs.validate_batch_receipt(changed, receipt)
            self.assertEqual(invalid.exception.code, "receipt_invalid")

    def test_malformed_item_receipt_binds_its_exact_attempt(self) -> None:
        payload = self.envelope("malformed-binding", [{
            "source_path": "sources/manual/alpha.md",
            "mode": "full",
            "response_text": "{}",
            "unexpected": "first",
        }])
        load, build = self.catalogs({self.a: snapshot(self.a)})
        with load, build:
            receipt = cs.file_batch_response(payload)
        self.assertEqual(receipt["items"][0]["status"], "refused")
        self.assertEqual(receipt["items"][0]["refusal_code"], "item_schema_invalid")
        self.assertEqual(cs.validate_batch_receipt(payload, receipt), receipt)
        changed = copy.deepcopy(payload)
        changed["items"][0]["unexpected"] = "second"
        with self.assertRaises(cs.ClassificationPreparationError) as invalid:
            cs.validate_batch_receipt(changed, receipt)
        self.assertEqual(invalid.exception.code, "receipt_invalid")

    def test_receipt_validator_checks_consistency_not_historical_authenticity(self) -> None:
        current = snapshot(self.a)
        payload = self.envelope("outcome-boundary", [{
            "source_path": "sources/manual/alpha.md",
            "mode": "full",
            "response_text": json.dumps(full_response(current)),
        }])
        load, build = self.catalogs({self.a: current})
        with load, build:
            receipt = cs.file_batch_response(payload)
        rewritten = copy.deepcopy(receipt)
        rewritten["items"][0]["status"] = "refused"
        rewritten["items"][0]["refusal_code"] = "self_consistent_rewrite"
        rewritten["counts"] = {"accepted": 0, "refused": 1, "already_current": 0}
        self.assertEqual(cs.validate_batch_receipt(payload, rewritten), rewritten)

    def test_exact_replay_revalidates_the_durable_receipt(self) -> None:
        current = snapshot(self.a)
        payload = self.envelope("revalidate-replay", [{
            "source_path": "sources/manual/alpha.md",
            "mode": "full",
            "response_text": json.dumps(full_response(current)),
        }])
        load, build = self.catalogs({self.a: current})
        with load, build:
            receipt = cs.file_batch_response(payload)
        receipt["items"][0]["input_digest"] = "sha256:" + "0" * 64
        cs._write_batch_receipt(receipt["receipt_path"], receipt)
        with self.assertRaises(cs.ClassificationPreparationError) as invalid:
            cs.file_batch_response(payload)
        self.assertEqual(invalid.exception.code, "receipt_invalid")

    def test_noncanonical_batch_source_is_refused_before_any_write(self) -> None:
        current = snapshot(self.a)
        payload = self.envelope("noncanonical-source", [{
            "source_path": "./sources/manual/alpha.md",
            "mode": "full",
            "response_text": json.dumps(full_response(current)),
        }])
        load, build = self.catalogs({self.a: current})
        with load, build, mock.patch.object(cs, "apply_prepared_classification") as apply:
            receipt = cs.file_batch_response(payload)
        apply.assert_not_called()
        self.assertEqual(receipt["items"][0]["status"], "refused")
        self.assertEqual(receipt["items"][0]["refusal_code"], "source_path_invalid")
        self.assertEqual(cs.validate_batch_receipt(payload, receipt), receipt)
        self.assertFalse(cs.classification_path(self.a).exists())

    def test_duplicate_invalid_source_labels_fail_before_valid_sibling_writes(self) -> None:
        current = snapshot(self.b)
        payload = self.envelope("duplicate-invalid-label", [
            {"source_path": "not/a/source.md", "mode": "full", "response_text": "{}"},
            {"source_path": "not/a/source.md", "mode": "full", "response_text": "{}"},
            {
                "source_path": "sources/manual/bravo.md",
                "mode": "full",
                "response_text": json.dumps(full_response(current)),
            },
        ])
        with mock.patch.object(cs, "apply_prepared_classification") as apply:
            with self.assertRaises(cs.ClassificationPreparationError) as duplicate:
                cs.file_batch_response(payload)
        self.assertEqual(duplicate.exception.code, "duplicate_source")
        apply.assert_not_called()
        self.assertFalse(cs.classification_path(self.b).exists())

    def test_already_current_skips_even_an_unusable_response(self) -> None:
        current = snapshot(self.a)
        before = self.existing(self.a, current)
        load, build = self.catalogs({self.a: current})
        with load, build:
            report = cs.file_batch_response(self.envelope("current-one", [{
                "source_path": "sources/manual/alpha.md",
                "mode": "full",
                "response_text": "",
            }]))
        self.assertEqual(report["counts"]["already_current"], 1)
        self.assertEqual(json.loads(cs.classification_path(self.a).read_text()), before)

    def test_ordinary_single_source_current_snapshot_skips_model(self) -> None:
        current = snapshot(self.a)
        before = self.existing(self.a, current)
        with mock.patch.object(cc, "build_context_snapshot", return_value=current), \
                mock.patch.object(cs, "classify_with_ai") as model:
            self.assertEqual(cs.classify_file(self.a, "synthetic-model"), 0)
        model.assert_not_called()
        self.assertEqual(json.loads(cs.classification_path(self.a).read_text()), before)

    def test_context_race_refuses_without_erasing_old_classification(self) -> None:
        old = snapshot(self.a, "old")
        first = snapshot(self.a, "first")
        changed = snapshot(self.a, "changed")
        prior = self.existing(self.a, old)
        response = {
            "_classification_mode": "timeline",
            "_classification_snapshot": cc.snapshot_metadata(first),
            "events": [timeline_delta(prior["events"][0], first)],
        }
        calls = 0

        def build(_root, _source, _catalog):
            nonlocal calls
            calls += 1
            return first if calls == 1 else changed

        with mock.patch.object(cc, "load_context_catalog", return_value={}), \
                mock.patch.object(cc, "build_context_snapshot_from_catalog", side_effect=build):
            report = cs.file_batch_response(self.envelope("race-one", [{
                "source_path": "sources/manual/alpha.md",
                "mode": "timeline",
                "response_text": json.dumps(response),
            }]))
        self.assertEqual(report["items"][0]["refusal_code"], "source_context_race")
        self.assertEqual(json.loads(cs.classification_path(self.a).read_text()), prior)

    def test_already_current_is_rechecked_against_second_catalog(self) -> None:
        first = snapshot(self.a, "first")
        changed = snapshot(self.a, "changed")
        prior = self.existing(self.a, first)
        calls = 0

        def build(_root, _source, _catalog):
            nonlocal calls
            calls += 1
            return first if calls == 1 else changed

        with mock.patch.object(cc, "load_context_catalog", return_value={}), \
                mock.patch.object(cc, "build_context_snapshot_from_catalog", side_effect=build):
            report = cs.file_batch_response(self.envelope("current-race", [{
                "source_path": "sources/manual/alpha.md",
                "mode": "full",
                "response_text": "unused because it began current",
            }]))
        self.assertEqual(report["items"][0]["status"], "refused")
        self.assertEqual(report["items"][0]["refusal_code"], "source_context_race")
        self.assertEqual(json.loads(cs.classification_path(self.a).read_text()), prior)

    def test_source_change_after_final_preparation_refuses_before_write(self) -> None:
        current = snapshot(self.a)
        response = full_response(current)
        original_prepare = cs.prepare_classification
        calls = 0

        def prepare(*args, **kwargs):
            nonlocal calls
            calls += 1
            prepared = original_prepare(*args, **kwargs)
            if calls == 3:
                self.a.write_text(self.a.read_text() + "Changed during filing.\n")
            return prepared

        load, build = self.catalogs({self.a: current})
        with load, build, mock.patch.object(cs, "prepare_classification", side_effect=prepare):
            report = cs.file_batch_response(self.envelope("source-race", [{
                "source_path": "sources/manual/alpha.md",
                "mode": "full",
                "response_text": json.dumps(response),
            }]))
        self.assertEqual(report["items"][0]["status"], "refused")
        self.assertEqual(report["items"][0]["refusal_code"], "source_context_race")
        self.assertFalse(cs.classification_path(self.a).exists())

    def test_duplicate_path_traversal_symlink_and_oversize_are_rejected(self) -> None:
        current = snapshot(self.a)
        item = {"source_path": "sources/manual/alpha.md", "mode": "full", "response_text": json.dumps(full_response(current))}
        with self.assertRaisesRegex(cs.ClassificationPreparationError, "duplicate"):
            cs.file_batch_response(self.envelope("dupe-one", [item, item]))
        outside = self.root.parent / "outside-synthetic.md"
        outside.write_text("synthetic", encoding="utf-8")
        try:
            with self.assertRaises(cs.ClassificationPreparationError) as traversal:
                cs._safe_source_path("../outside-synthetic.md")
            self.assertEqual(traversal.exception.code, "source_path_escape")
        finally:
            outside.unlink()
        link = self.sources / "manual" / "linked.md"
        link.symlink_to(self.a)
        with self.assertRaises(cs.ClassificationPreparationError) as symlinked:
            cs._safe_source_path("sources/manual/linked.md")
        self.assertEqual(symlinked.exception.code, "source_path_symlink")
        response_file = self.root / "too-large.json"
        response_file.write_bytes(b"x" * 9)
        with self.assertRaises(cs.ClassificationPreparationError) as oversized:
            cs._read_transport_json(str(response_file), max_bytes=8)
        self.assertEqual(oversized.exception.code, "input_too_large")

    def test_receipt_directory_and_file_symlinks_never_escape_vault(self) -> None:
        outside = self.root / "outside"
        outside.mkdir()
        receipt_dir = self.root / "state" / "classification_batches"
        receipt_dir.parent.mkdir(exist_ok=True)
        receipt_dir.symlink_to(outside, target_is_directory=True)
        with self.assertRaises(ValueError):
            cs._write_batch_receipt(
                "state/classification_batches/synthetic.json", {"schema_version": 1}
            )
        self.assertEqual(list(outside.iterdir()), [])
        receipt_dir.unlink()
        receipt_dir.mkdir()
        outside_file = outside / "outside.json"
        outside_file.write_text('{"canary":true}\n', encoding="utf-8")
        linked = receipt_dir / "synthetic.json"
        linked.symlink_to(outside_file)
        with self.assertRaises(ValueError):
            cs._read_batch_receipt("state/classification_batches/synthetic.json")
        with self.assertRaises(ValueError):
            cs._write_batch_receipt(
                "state/classification_batches/synthetic.json", {"schema_version": 1}
            )
        self.assertEqual(json.loads(outside_file.read_text()), {"canary": True})

    def test_zero_event_opinion_is_success(self) -> None:
        self.a.write_text("---\ntitle: Position\ntype: opinion\n---\nA synthetic position.\n", encoding="utf-8")
        current = snapshot(self.a)
        load, build = self.catalogs({self.a: current})
        with load, build:
            report = cs.file_batch_response(self.envelope("opinion-one", [{
                "source_path": "sources/manual/alpha.md",
                "mode": "full",
                "response_text": json.dumps(full_response(current, events=[])),
            }]))
        self.assertEqual(report["counts"]["accepted"], 1)
        self.assertEqual(json.loads(cs.classification_path(self.a).read_text())["events"], [])

    def test_refresh_report_is_incomplete_when_inventory_has_ineligible_rows(self) -> None:
        empty = self.sources / "manual" / "empty.md"
        empty.write_text("---\ntitle: Empty\n---\n", encoding="utf-8")
        base = {
            "targets": [],
            "selected_count": 0,
            "pending_count": 0,
            "remaining_count": 0,
            "complete": True,
            "limit": 50,
        }
        output = io.StringIO()
        with mock.patch.object(cc, "select_refresh_targets", return_value=base), \
                redirect_stdout(output):
            self.assertEqual(cs.cmd_refresh_targets(SimpleNamespace(limit=50)), 0)
        report = json.loads(output.getvalue())
        self.assertEqual(report["ineligible_count"], 1)
        self.assertFalse(report["complete"])


if __name__ == "__main__":
    unittest.main()
