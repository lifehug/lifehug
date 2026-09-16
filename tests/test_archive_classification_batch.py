"""Canonical archive classifier batch tests. All data is synthetic."""

from __future__ import annotations

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


def full_response(snap: dict, *, events: list[dict] | None = None) -> dict:
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
        "events": [] if events is None else events,
        "candidate_questions": [],
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
            "events": [{"title": "Old event"}],
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
        self.assertNotIn('"candidate_questions"', full_prompt)
        self.assertNotIn("Question-Judgment Rubric", full_prompt)

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
        ])
        self.assertEqual(parsed.exclude_items_json, str(transport))
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
        prior = self.existing(self.a, old)
        response = {
            "_classification_mode": "timeline",
            "_classification_snapshot": cc.snapshot_metadata(current),
            "events": [{"title": "New synthetic event", "timeline_relation": None}],
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
        self.assertEqual(filed["events"], response["events"])

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
        self.assertEqual(json.loads(self.candidates.read_text())["candidates"], [])

    def test_correction_selects_full_mode_and_saved_old_response_is_refused(self) -> None:
        before = cc.build_context_snapshot(self.root, self.a)
        prior = self.existing(self.a, {**before, "source_revision": "sha256:" + "0" * 64})
        response = full_response(before)
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
            "events": [],
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
