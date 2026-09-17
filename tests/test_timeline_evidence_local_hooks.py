"""Focused local lifecycle hooks for the timeline evidence refresh loop."""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SYSTEM = ROOT / "system"
sys.path.insert(0, str(SYSTEM))

import classification_refresh
import classifier_context
import classify_story
import jobs
import lifehug
import vault_paths


class CanonicalRefreshBatchTests(unittest.TestCase):
    def setUp(self) -> None:
        self.vault = Path(tempfile.mkdtemp(prefix="lifehug-refresh-helper-", dir=ROOT))
        (self.vault / "state").mkdir()

    def tearDown(self) -> None:
        shutil.rmtree(self.vault, ignore_errors=True)

    def test_batch_identity_binds_the_saved_response_attempt(self) -> None:
        plan = [
            {
                "source_path": "answers/A1.md",
                "mode": "full",
                "snapshot": {"source_revision": "sha256:" + "a" * 64},
            }
        ]
        first = [{"response_text": '{"result": 1}'}]
        corrected = [{"response_text": '{"result": 2}'}]
        self.assertEqual(
            classification_refresh._batch_id(plan, first),
            classification_refresh._batch_id(plan, first),
        )
        self.assertNotEqual(
            classification_refresh._batch_id(plan, first),
            classification_refresh._batch_id(plan, corrected),
        )

    def test_unchanged_selection_makes_no_ai_or_filing_call(self) -> None:
        selection = {
            "targets": [],
            "selected_count": 0,
            "pending_count": 0,
            "remaining_count": 0,
            "complete": True,
            "limit": 50,
        }
        with (
            mock.patch.object(
                classify_story, "classification_inventory", return_value=([], [])
            ),
            mock.patch.object(
                classifier_context, "select_refresh_targets", return_value=selection
            ),
            mock.patch.object(classify_story, "build_batch_plan") as plan,
            mock.patch.object(classify_story, "classify_with_ai") as ai,
            mock.patch.object(classify_story, "get_model") as get_model,
            mock.patch.object(classify_story, "file_batch_response") as file_response,
        ):
            report = classification_refresh.run_batch(self.vault, limit=50)

        self.assertEqual(report["status"], "unchanged")
        plan.assert_not_called()
        ai.assert_not_called()
        get_model.assert_not_called()
        file_response.assert_not_called()

    def test_selected_targets_use_one_canonical_batch_and_serial_provider_calls(
        self,
    ) -> None:
        first = self.vault / "answers" / "A1.md"
        second = self.vault / "sources" / "manual" / "older.md"
        selected = {
            "targets": [
                {"source_path": "answers/A1.md", "reason": "context_changed"},
                {"source_path": "sources/manual/older.md", "reason": "context_changed"},
            ],
            "selected_count": 2,
            "pending_count": 2,
            "remaining_count": 0,
            "complete": True,
            "limit": 50,
        }
        complete = {
            "targets": [],
            "selected_count": 0,
            "pending_count": 0,
            "remaining_count": 0,
            "complete": True,
            "limit": 50,
        }
        plan = {
            "selected_count": 2,
            "pending_count": 2,
            "remaining_count": 0,
            "items": [
                {
                    "source_path": "answers/A1.md",
                    "mode": "full",
                    "snapshot": {"source_revision": "sha256:" + "a" * 64},
                    "prompt": "first prompt",
                },
                {
                    "source_path": "sources/manual/older.md",
                    "mode": "timeline",
                    "snapshot": {"source_revision": "sha256:" + "b" * 64},
                    "prompt": "second prompt",
                },
            ],
        }
        receipt = {
            "receipt_path": "state/classification_batches/local-refresh.json",
            "counts": {"accepted": 2, "refused": 0, "already_current": 0},
            "items": [
                {"source_path": "answers/A1.md", "status": "accepted"},
                {"source_path": "sources/manual/older.md", "status": "accepted"},
            ],
        }
        responses = [{"result": 1}, {"result": 2}]
        with (
            mock.patch.object(
                classify_story,
                "classification_inventory",
                return_value=([first, second], []),
            ),
            mock.patch.object(
                classifier_context,
                "select_refresh_targets",
                side_effect=[selected, complete],
            ) as select,
            mock.patch.object(
                classify_story, "build_batch_plan", return_value=plan
            ) as build,
            mock.patch.object(
                classify_story, "classify_with_ai", side_effect=responses
            ) as ai,
            mock.patch.object(
                classify_story, "file_batch_response", return_value=receipt
            ) as file_response,
            mock.patch.object(classification_refresh, "_migrate") as migrate,
        ):
            report = classification_refresh.run_batch(
                self.vault, limit=50, model="synthetic"
            )

        self.assertEqual(select.call_count, 2)
        select.assert_any_call(self.vault, [first, second], limit=50)
        build.assert_called_once_with(
            limit=50, sources=[first, second], skip_candidates=True
        )
        self.assertEqual(
            ai.call_args_list,
            [
                mock.call("first prompt", "synthetic"),
                mock.call("second prompt", "synthetic"),
            ],
        )
        envelope = file_response.call_args.args[0]
        self.assertEqual(envelope["schema_version"], 1)
        self.assertTrue(envelope["batch_id"].startswith("local-refresh-"))
        self.assertTrue(envelope["skip_candidates"])
        self.assertEqual(
            [json.loads(item["response_text"]) for item in envelope["items"]],
            responses,
        )
        self.assertEqual(
            report["accepted_sources"],
            [
                "answers/A1.md",
                "sources/manual/older.md",
            ],
        )
        self.assertEqual(report["batch_count"], 1)
        self.assertTrue(report["publication_needed"])
        migrate.assert_called_once_with(
            self.vault, ["answers/A1.md", "sources/manual/older.md"]
        )

    def test_pending_selection_without_a_plan_is_an_explicit_failure(self) -> None:
        selection = {
            "targets": [{"source_path": "answers/A1.md", "reason": "context_changed"}],
            "selected_count": 1,
            "pending_count": 1,
            "remaining_count": 0,
            "complete": True,
            "limit": 50,
        }
        with (
            mock.patch.object(
                classify_story,
                "classification_inventory",
                return_value=([ROOT / "answers" / "A1.md"], []),
            ),
            mock.patch.object(
                classifier_context, "select_refresh_targets", return_value=selection
            ),
            mock.patch.object(
                classify_story,
                "build_batch_plan",
                return_value={"selected_count": 0, "items": []},
            ),
            self.assertRaises(classification_refresh.ClassificationRefreshError),
        ):
            classification_refresh.run_batch(self.vault, limit=50, model="synthetic")

    def test_only_ineligible_inventory_is_an_explicit_zero_ai_failure(self) -> None:
        selection = {
            "targets": [],
            "selected_count": 0,
            "pending_count": 0,
            "remaining_count": 0,
            "complete": True,
            "limit": 50,
        }
        ineligible = [{"source_path": "answers/A1.md", "refusal_code": "source_empty"}]
        with (
            mock.patch.object(
                classify_story,
                "classification_inventory",
                return_value=([], ineligible),
            ),
            mock.patch.object(
                classifier_context, "select_refresh_targets", return_value=selection
            ),
            mock.patch.object(classify_story, "classify_with_ai") as ai,
            self.assertRaises(classification_refresh.ClassificationRefreshError),
        ):
            classification_refresh.run_batch(self.vault, limit=50, model="synthetic")
        ai.assert_not_called()

    def test_repeated_pending_snapshot_set_is_an_explicit_failure(self) -> None:
        selected = {
            "targets": [
                {
                    "source_path": "answers/A1.md",
                    "reason": "new_source",
                    "snapshot": {"source_revision": "sha256:" + "a" * 64},
                }
            ],
            "selected_count": 1,
            "pending_count": 1,
            "remaining_count": 0,
            "complete": True,
            "limit": 1,
        }
        plan = {
            "selected_count": 1,
            "pending_count": 1,
            "remaining_count": 0,
            "items": [
                {
                    "source_path": "answers/A1.md",
                    "mode": "full",
                    "snapshot": selected["targets"][0]["snapshot"],
                    "prompt": "new source",
                }
            ],
        }
        receipt = {
            "receipt_path": "state/classification_batches/repeated.json",
            "counts": {"accepted": 1, "refused": 0, "already_current": 0},
            "items": [{"source_path": "answers/A1.md", "status": "accepted"}],
        }
        source = self.vault / "answers" / "A1.md"
        with (
            mock.patch.object(
                classify_story, "classification_inventory", return_value=([source], [])
            ),
            mock.patch.object(
                classifier_context, "select_refresh_targets", return_value=selected
            ),
            mock.patch.object(classify_story, "build_batch_plan", return_value=plan),
            mock.patch.object(
                classify_story, "classify_with_ai", return_value={"events": []}
            ) as ai,
            mock.patch.object(
                classify_story, "file_batch_response", return_value=receipt
            ),
            mock.patch.object(classification_refresh, "_migrate"),
            self.assertRaisesRegex(
                classification_refresh.ClassificationRefreshError,
                "same pending snapshot set",
            ),
        ):
            classification_refresh.run_batch(self.vault, limit=1, model="synthetic")
        self.assertEqual(ai.call_count, 1)

    def test_more_than_one_limit_is_drained_in_successive_bounded_batches(self) -> None:
        paths = [f"sources/manual/story-{index:02d}.md" for index in range(51)]
        sources = [self.vault / path for path in paths]

        def selection(selected: list[str], *, pending: int, remaining: int) -> dict:
            return {
                "targets": [
                    {"source_path": path, "reason": "new_source", "snapshot": {}}
                    for path in selected
                ],
                "selected_count": len(selected),
                "pending_count": pending,
                "remaining_count": remaining,
                "complete": remaining == 0,
                "limit": 50,
            }

        selections = [
            selection(paths[:50], pending=51, remaining=1),
            selection(paths[50:], pending=1, remaining=0),
            selection([], pending=0, remaining=0),
        ]

        def plan(*, sources: list[Path], **_kwargs: object) -> dict:
            items = [
                {
                    "source_path": path.relative_to(self.vault).as_posix(),
                    "mode": "full",
                    "snapshot": {},
                    "prompt": path.name,
                }
                for path in sources
            ]
            return {
                "selected_count": len(items),
                "pending_count": len(items),
                "remaining_count": 0,
                "items": items,
            }

        def file_response(envelope: dict, **_kwargs: object) -> dict:
            items = [
                {"source_path": item["source_path"], "status": "accepted"}
                for item in envelope["items"]
            ]
            return {
                "receipt_path": f"state/classification_batches/{envelope['batch_id']}.json",
                "counts": {
                    "accepted": len(items),
                    "refused": 0,
                    "already_current": 0,
                },
                "items": items,
            }

        with (
            mock.patch.object(
                classify_story, "classification_inventory", return_value=(sources, [])
            ),
            mock.patch.object(
                classifier_context, "select_refresh_targets", side_effect=selections
            ),
            mock.patch.object(classify_story, "build_batch_plan", side_effect=plan),
            mock.patch.object(
                classify_story, "classify_with_ai", return_value={"events": []}
            ) as ai,
            mock.patch.object(
                classify_story, "file_batch_response", side_effect=file_response
            ),
            mock.patch.object(classification_refresh, "_migrate") as migrate,
        ):
            report = classification_refresh.run_batch(
                self.vault, limit=50, model="synthetic"
            )

        self.assertEqual(report["batch_count"], 2)
        self.assertEqual(report["counts"]["accepted"], 51)
        self.assertEqual(ai.call_count, 51)
        self.assertEqual(migrate.call_count, 2)


class DurableLifecycleSuccessorTests(unittest.TestCase):
    def setUp(self) -> None:
        vault_paths._reset_process_binding_for_tests()
        self.tmp = Path(tempfile.mkdtemp(prefix="lifehug-local-hooks-", dir=ROOT))
        (self.tmp / "question-bank.md").write_text("# Questions\n", encoding="utf-8")
        (self.tmp / "state").mkdir()
        (self.tmp / "state" / "rotation.json").write_text(
            json.dumps(
                {
                    "version": 1,
                    "current_pass": 1,
                    "pass_names": ["skeleton", "depth", "connections", "polish"],
                    "last_question_id": None,
                    "last_asked_at": None,
                    "questions_asked": 0,
                    "questions_answered": 0,
                    "next_question_id": None,
                    "focus_frequency": 4,
                }
            ),
            encoding="utf-8",
        )
        (self.tmp / "state" / "coverage.json").write_text(
            '{"version": 1, "last_updated": null, "categories": {}}\n',
            encoding="utf-8",
        )
        (self.tmp / "answers").mkdir()
        self.original_vault = jobs.VAULT_ROOT
        jobs.configure(self.tmp)

    def tearDown(self) -> None:
        vault_paths._reset_process_binding_for_tests()
        jobs.configure(self.original_vault)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def succeeded(self, command: str, payload: dict, identity: str) -> dict:
        record = jobs.enqueue(command, payload, identity=identity, kick=False)
        record.update(
            {"state": "succeeded", "exit_code": 0, "finished_at": jobs._now()}
        )
        jobs._write_json(jobs._record_path(record["id"]), record)
        return record

    def test_answer_and_close_coalesce_onto_one_nonblocking_refresh(self) -> None:
        predecessors = [
            self.succeeded(
                "process-answer",
                {"question_id": "A1", "answer": "Synthetic."},
                "answer",
            ),
            self.succeeded(
                "conversation-close",
                {"session_id": "conv-20260917-120000-abcdef", "reason": "done"},
                "close",
            ),
        ]
        with mock.patch.object(jobs, "_kick_worker") as kick:
            successors = [
                jobs._ensure_lifecycle_refresh_successor(row) for row in predecessors
            ]

        successor_ids = {row["id"] for row in successors if row is not None}
        self.assertEqual(len(successor_ids), 1)
        successor_id = successor_ids.pop()
        self.assertEqual(jobs.load_job(successor_id)["state"], "queued")
        for predecessor in predecessors:
            self.assertEqual(
                jobs.load_job(predecessor["id"])["classification_refresh_job_id"],
                successor_id,
            )
        kick.assert_not_called()

    def test_recovery_links_a_succeeded_predecessor_once(self) -> None:
        predecessor = self.succeeded(
            "process-answer", {"question_id": "A1", "answer": "Synthetic."}, "answer"
        )
        jobs._recover_lifecycle_refresh_successors()
        first = jobs.load_job(predecessor["id"])["classification_refresh_job_id"]
        jobs._recover_lifecycle_refresh_successors()
        second = jobs.load_job(predecessor["id"])["classification_refresh_job_id"]
        self.assertEqual(first, second)
        refreshes = [
            jobs.load_job(path.stem)
            for path in jobs.JOBS_DIR.glob("*.json")
            if jobs.load_job(path.stem)["command"] == "classification-refresh"
        ]
        self.assertEqual(len(refreshes), 1)

    def test_success_receipt_queues_refresh_but_failed_capture_does_not(self) -> None:
        succeeded = jobs.enqueue(
            "process-answer",
            {"question_id": "A1", "answer": "Synthetic."},
            identity="succeeds",
            kick=False,
        )
        with mock.patch.object(
            jobs, "_run_invocation", return_value=(0, "command_failed")
        ):
            result = jobs._execute_record(succeeded, "a" * 20)
        self.assertEqual(result["state"], "succeeded")
        self.assertEqual(
            jobs.load_job(result["classification_refresh_job_id"])["state"], "queued"
        )

        failed = jobs.enqueue(
            "process-answer",
            {"question_id": "A1", "answer": "Synthetic failure."},
            identity="fails",
            kick=False,
        )
        with mock.patch.object(
            jobs, "_run_invocation", return_value=(1, "command_failed")
        ):
            result = jobs._execute_record(failed, "b" * 20)
        self.assertEqual(result["state"], "failed")
        self.assertNotIn("classification_refresh_job_id", result)

    def test_refresh_job_payload_has_no_source_or_answer_content(self) -> None:
        invocation = jobs.COMMANDS["classification-refresh"].build({})[0]
        self.assertEqual(invocation.arguments, ("classification-refresh",))
        self.assertIsNone(invocation.stdin_text)


class LocalCliHookTests(unittest.TestCase):
    def test_story_and_single_session_close_schedule_durable_refresh_work(self) -> None:
        ingest = lifehug.build_parser().parse_args(["ingest-story", "--source", "web"])
        close = lifehug.build_parser().parse_args(
            [
                "conversation-close",
                "conv-20260917-120000-abcdef",
            ]
        )
        calls = []

        def queue(command, payload, *, identity=None):
            calls.append((command, payload, identity))
            return 0

        with (
            mock.patch.object(lifehug, "_job_runner_active", return_value=False),
            mock.patch.object(lifehug, "run_python", return_value=0),
            mock.patch.object(lifehug, "_queue_and_wait", side_effect=queue),
            mock.patch.object(jobs, "configure"),
            mock.patch.object(
                jobs,
                "enqueue_classification_refresh",
                return_value={"id": "a" * 20},
            ) as enqueue_refresh,
        ):
            self.assertEqual(lifehug.cmd_ingest_story(ingest), 0)
            self.assertEqual(lifehug.cmd_conversation_close(close), 0)

        enqueue_refresh.assert_called_once_with(kick=True)
        self.assertEqual(
            calls[0],
            (
                "conversation-close",
                {"session_id": "conv-20260917-120000-abcdef", "reason": "done"},
                "conversation-close:conv-20260917-120000-abcdef",
            ),
        )

    def test_refresh_runs_downstream_only_after_accepted_changes(self) -> None:
        args = lifehug.build_parser().parse_args(["classification-refresh"])
        unchanged = {
            "status": "unchanged",
            "accepted_sources": [],
            "counts": {"accepted": 0, "refused": 0, "already_current": 0},
            "selection": {"remaining_count": 0},
            "publication_needed": False,
            "batch_count": 0,
        }
        accepted = {
            "status": "accepted",
            "accepted_sources": ["sources/manual/older.md"],
            "counts": {"accepted": 1, "refused": 0, "already_current": 0},
            "selection": {"remaining_count": 0},
            "publication_needed": True,
            "batch_count": 1,
        }
        with (
            mock.patch.object(lifehug, "_job_runner_active", return_value=True),
            mock.patch.object(
                classification_refresh, "run_batch", return_value=unchanged
            ),
            mock.patch.object(lifehug, "cmd_timeline_retire") as retire,
            mock.patch.object(lifehug, "cmd_compile") as compile_wiki,
        ):
            self.assertEqual(lifehug.cmd_classification_refresh(args), 0)
            retire.assert_not_called()
            compile_wiki.assert_not_called()

        with (
            mock.patch.object(lifehug, "_job_runner_active", return_value=True),
            mock.patch.object(
                classification_refresh, "run_batch", return_value=accepted
            ),
            mock.patch.object(lifehug, "cmd_timeline_retire", return_value=0) as retire,
            mock.patch.object(lifehug, "cmd_compile", return_value=0) as compile_wiki,
            mock.patch.object(
                classification_refresh, "clear_publication_checkpoint"
            ) as clear,
        ):
            self.assertEqual(lifehug.cmd_classification_refresh(args), 0)
            retire.assert_called_once()
            self.assertTrue(compile_wiki.call_args.args[0].no_ai)
            clear.assert_called_once_with(lifehug.REPO_DIR)

    def test_new_answer_drains_old_story_then_publishes_once_and_noops(self) -> None:
        vault = Path(tempfile.mkdtemp(prefix="lifehug-refresh-closure-", dir=ROOT))
        (vault / "state").mkdir()
        new_source = vault / "answers" / "A1.md"
        old_source = vault / "sources" / "manual" / "old-story.md"
        new_source.parent.mkdir()
        old_source.parent.mkdir(parents=True)
        new_source.write_text("New independent evidence.\n", encoding="utf-8")
        old_source.write_text("An older settled story.\n", encoding="utf-8")
        snapshot_new = {"source_revision": "sha256:" + "a" * 64}
        snapshot_old = {"source_revision": "sha256:" + "b" * 64}
        new_selection = {
            "targets": [
                {
                    "source_path": "answers/A1.md",
                    "reason": "new_source",
                    "snapshot": snapshot_new,
                }
            ],
            "selected_count": 1,
            "pending_count": 1,
            "remaining_count": 0,
            "complete": True,
            "limit": 1,
        }
        old_selection = {
            "targets": [
                {
                    "source_path": "sources/manual/old-story.md",
                    "reason": "context_changed",
                    "snapshot": snapshot_old,
                }
            ],
            "selected_count": 1,
            "pending_count": 1,
            "remaining_count": 0,
            "complete": True,
            "limit": 1,
        }
        complete = {
            "targets": [],
            "selected_count": 0,
            "pending_count": 0,
            "remaining_count": 0,
            "complete": True,
            "limit": 1,
        }
        plans = [
            {
                "selected_count": 1,
                "pending_count": 1,
                "remaining_count": 0,
                "items": [
                    {
                        "source_path": "answers/A1.md",
                        "mode": "full",
                        "snapshot": snapshot_new,
                        "prompt": "classify new answer",
                    }
                ],
            },
            {
                "selected_count": 1,
                "pending_count": 1,
                "remaining_count": 0,
                "items": [
                    {
                        "source_path": "sources/manual/old-story.md",
                        "mode": "timeline",
                        "snapshot": snapshot_old,
                        "prompt": "refresh older story",
                    }
                ],
            },
        ]
        receipts = [
            {
                "receipt_path": "state/classification_batches/new.json",
                "counts": {"accepted": 1, "refused": 0, "already_current": 0},
                "items": [{"source_path": "answers/A1.md", "status": "accepted"}],
            },
            {
                "receipt_path": "state/classification_batches/old.json",
                "counts": {"accepted": 1, "refused": 0, "already_current": 0},
                "items": [
                    {"source_path": "sources/manual/old-story.md", "status": "accepted"}
                ],
            },
        ]
        args = argparse.Namespace(limit=1, model="synthetic")
        migrations: list[list[str] | None] = []

        def select_after_migration(*_args: object, **_kwargs: object) -> dict:
            if not migrations:
                return new_selection
            if migrations == [["answers/A1.md"]]:
                return old_selection
            return complete

        try:
            with (
                mock.patch.object(lifehug, "REPO_DIR", vault),
                mock.patch.object(lifehug, "_job_runner_active", return_value=True),
                mock.patch.object(
                    classify_story,
                    "classification_inventory",
                    return_value=([new_source, old_source], []),
                ),
                mock.patch.object(
                    classifier_context,
                    "select_refresh_targets",
                    side_effect=select_after_migration,
                ),
                mock.patch.object(
                    classify_story, "build_batch_plan", side_effect=plans
                ),
                mock.patch.object(
                    classify_story,
                    "classify_with_ai",
                    side_effect=[{"events": ["new"]}, {"events": ["old"]}],
                ) as ai,
                mock.patch.object(
                    classify_story, "file_batch_response", side_effect=receipts
                ),
                mock.patch.object(
                    classification_refresh,
                    "_migrate",
                    side_effect=lambda _root, sources: migrations.append(sources) or {},
                ),
                mock.patch.object(
                    lifehug, "cmd_timeline_retire", return_value=0
                ) as retire,
                mock.patch.object(
                    lifehug, "cmd_compile", return_value=0
                ) as compile_wiki,
            ):
                self.assertEqual(lifehug.cmd_classification_refresh(args), 0)
                self.assertEqual(lifehug.cmd_classification_refresh(args), 0)

            self.assertEqual(ai.call_count, 2)
            self.assertEqual(
                migrations,
                [["answers/A1.md"], ["sources/manual/old-story.md"]],
            )
            retire.assert_called_once()
            compile_wiki.assert_called_once()
            self.assertFalse((vault / "state" / ".compile-needed").exists())
        finally:
            shutil.rmtree(vault, ignore_errors=True)

    def test_retry_after_filing_resumes_migration_and_publication_without_model(
        self,
    ) -> None:
        vault = Path(tempfile.mkdtemp(prefix="lifehug-refresh-resume-", dir=ROOT))
        (vault / "state").mkdir()
        source = vault / "answers" / "A1.md"
        source.parent.mkdir()
        source.write_text("New independent evidence.\n", encoding="utf-8")
        snapshot = {"source_revision": "sha256:" + "c" * 64}
        selected = {
            "targets": [
                {
                    "source_path": "answers/A1.md",
                    "reason": "new_source",
                    "snapshot": snapshot,
                }
            ],
            "selected_count": 1,
            "pending_count": 1,
            "remaining_count": 0,
            "complete": True,
            "limit": 1,
        }
        complete = {
            "targets": [],
            "selected_count": 0,
            "pending_count": 0,
            "remaining_count": 0,
            "complete": True,
            "limit": 1,
        }
        plan = {
            "selected_count": 1,
            "pending_count": 1,
            "remaining_count": 0,
            "items": [
                {
                    "source_path": "answers/A1.md",
                    "mode": "full",
                    "snapshot": snapshot,
                    "prompt": "classify new answer",
                }
            ],
        }
        classification = vault / "state" / "classifications" / "answer-a1.json"

        def file_then_crash(_envelope: dict, *, model: str) -> dict:
            self.assertEqual(model, "synthetic")
            classification.parent.mkdir(parents=True, exist_ok=True)
            classification.write_text(
                '{"source_path":"answers/A1.md"}\n', encoding="utf-8"
            )
            raise RuntimeError("after durable filing, before return")

        args = argparse.Namespace(limit=1, model="synthetic")
        try:
            with (
                mock.patch.object(lifehug, "REPO_DIR", vault),
                mock.patch.object(lifehug, "_job_runner_active", return_value=True),
                mock.patch.object(
                    classify_story,
                    "classification_inventory",
                    return_value=([source], []),
                ),
                mock.patch.object(
                    classifier_context,
                    "select_refresh_targets",
                    side_effect=[selected, complete],
                ),
                mock.patch.object(
                    classify_story, "build_batch_plan", return_value=plan
                ),
                mock.patch.object(
                    classify_story, "classify_with_ai", return_value={"events": []}
                ) as ai,
                mock.patch.object(
                    classify_story,
                    "file_batch_response",
                    side_effect=file_then_crash,
                ) as file_response,
                mock.patch.object(
                    classification_refresh,
                    "_migrate",
                    return_value={},
                ) as migrate,
                mock.patch.object(
                    lifehug, "cmd_timeline_retire", return_value=0
                ) as retire,
                mock.patch.object(
                    lifehug, "cmd_compile", return_value=0
                ) as compile_wiki,
                mock.patch("lifehug_core.record_learning_failure"),
            ):
                self.assertEqual(lifehug.cmd_classification_refresh(args), 1)
                self.assertTrue(classification.is_file())
                self.assertTrue((vault / "state" / ".compile-needed").is_file())
                self.assertEqual(lifehug.cmd_classification_refresh(args), 0)

            self.assertEqual(ai.call_count, 1)
            file_response.assert_called_once()
            migrate.assert_called_once_with(vault, None)
            retire.assert_called_once()
            compile_wiki.assert_called_once()
            self.assertFalse((vault / "state" / ".compile-needed").exists())
        finally:
            shutil.rmtree(vault, ignore_errors=True)

    def test_hosted_processor_modules_do_not_import_the_local_queue(self) -> None:
        for name in ("process_answer.py", "ingest_story.py"):
            source = (SYSTEM / name).read_text(encoding="utf-8")
            self.assertNotIn("import jobs", source)
            self.assertNotIn("jobs.enqueue", source)


if __name__ == "__main__":
    unittest.main()
