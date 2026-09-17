"""Focused local lifecycle hooks for the timeline evidence refresh loop."""

from __future__ import annotations

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

import classification_refresh  # noqa: E402
import classifier_context  # noqa: E402
import classify_story  # noqa: E402
import jobs  # noqa: E402
import lifehug  # noqa: E402
import vault_paths  # noqa: E402


class CanonicalRefreshBatchTests(unittest.TestCase):
    def test_batch_identity_binds_the_saved_response_attempt(self) -> None:
        plan = [{
            "source_path": "answers/A1.md",
            "mode": "full",
            "snapshot": {"source_revision": "sha256:" + "a" * 64},
        }]
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
        with mock.patch.object(
            classify_story, "classification_inventory", return_value=([], [])
        ), mock.patch.object(
            classifier_context, "select_refresh_targets", return_value=selection
        ), mock.patch.object(classify_story, "build_batch_plan") as plan, mock.patch.object(
            classify_story, "classify_with_ai"
        ) as ai, mock.patch.object(classify_story, "file_batch_response") as file_response:
            report = classification_refresh.run_batch(ROOT, limit=50)

        self.assertEqual(report["status"], "unchanged")
        plan.assert_not_called()
        ai.assert_not_called()
        file_response.assert_not_called()

    def test_selected_targets_use_one_canonical_batch_and_serial_provider_calls(self) -> None:
        first = ROOT / "answers" / "A1.md"
        second = ROOT / "sources" / "manual" / "older.md"
        selection = {
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
        with mock.patch.object(
            classify_story, "classification_inventory", return_value=([first, second], [])
        ), mock.patch.object(
            classifier_context, "select_refresh_targets", return_value=selection
        ) as select, mock.patch.object(
            classify_story, "build_batch_plan", return_value=plan
        ) as build, mock.patch.object(
            classify_story, "classify_with_ai", side_effect=responses
        ) as ai, mock.patch.object(
            classify_story, "file_batch_response", return_value=receipt
        ) as file_response:
            report = classification_refresh.run_batch(ROOT, limit=50, model="synthetic")

        select.assert_called_once_with(ROOT, [first, second], limit=50)
        build.assert_called_once_with(
            limit=50, sources=[first, second], skip_candidates=True
        )
        self.assertEqual(
            ai.call_args_list,
            [mock.call("first prompt", "synthetic"), mock.call("second prompt", "synthetic")],
        )
        envelope = file_response.call_args.args[0]
        self.assertEqual(envelope["schema_version"], 1)
        self.assertTrue(envelope["batch_id"].startswith("local-refresh-"))
        self.assertTrue(envelope["skip_candidates"])
        self.assertEqual(
            [json.loads(item["response_text"]) for item in envelope["items"]],
            responses,
        )
        self.assertEqual(report["accepted_sources"], [
            "answers/A1.md", "sources/manual/older.md",
        ])

    def test_pending_selection_without_a_plan_is_an_explicit_failure(self) -> None:
        selection = {
            "targets": [{"source_path": "answers/A1.md", "reason": "context_changed"}],
            "selected_count": 1,
            "pending_count": 1,
            "remaining_count": 0,
            "complete": True,
            "limit": 50,
        }
        with mock.patch.object(
            classify_story,
            "classification_inventory",
            return_value=([ROOT / "answers" / "A1.md"], []),
        ), mock.patch.object(
            classifier_context, "select_refresh_targets", return_value=selection
        ), mock.patch.object(
            classify_story,
            "build_batch_plan",
            return_value={"selected_count": 0, "items": []},
        ):
            with self.assertRaises(classification_refresh.ClassificationRefreshError):
                classification_refresh.run_batch(ROOT, limit=50, model="synthetic")

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
        with mock.patch.object(
            classify_story, "classification_inventory", return_value=([], ineligible)
        ), mock.patch.object(
            classifier_context, "select_refresh_targets", return_value=selection
        ), mock.patch.object(classify_story, "classify_with_ai") as ai:
            with self.assertRaises(classification_refresh.ClassificationRefreshError):
                classification_refresh.run_batch(ROOT, limit=50, model="synthetic")
        ai.assert_not_called()


class DurableLifecycleSuccessorTests(unittest.TestCase):
    def setUp(self) -> None:
        vault_paths._reset_process_binding_for_tests()
        self.tmp = Path(tempfile.mkdtemp(prefix="lifehug-local-hooks-", dir=ROOT))
        (self.tmp / "question-bank.md").write_text("# Questions\n", encoding="utf-8")
        (self.tmp / "state").mkdir()
        (self.tmp / "state" / "rotation.json").write_text(
            json.dumps({
                "version": 1,
                "current_pass": 1,
                "pass_names": ["skeleton", "depth", "connections", "polish"],
                "last_question_id": None,
                "last_asked_at": None,
                "questions_asked": 0,
                "questions_answered": 0,
                "next_question_id": None,
                "focus_frequency": 4,
            }),
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
        record.update({"state": "succeeded", "exit_code": 0, "finished_at": jobs._now()})
        jobs._write_json(jobs._record_path(record["id"]), record)
        return record

    def test_answer_and_close_coalesce_onto_one_nonblocking_refresh(self) -> None:
        predecessors = [
            self.succeeded(
                "process-answer", {"question_id": "A1", "answer": "Synthetic."}, "answer"
            ),
            self.succeeded(
                "conversation-close",
                {"session_id": "conv-20260917-120000-abcdef", "reason": "done"},
                "close",
            ),
        ]
        with mock.patch.object(jobs, "_kick_worker") as kick:
            successors = [jobs._ensure_lifecycle_refresh_successor(row) for row in predecessors]

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
        with mock.patch.object(jobs, "_run_invocation", return_value=(0, "command_failed")):
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
        with mock.patch.object(jobs, "_run_invocation", return_value=(1, "command_failed")):
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
        close = lifehug.build_parser().parse_args([
            "conversation-close", "conv-20260917-120000-abcdef",
        ])
        calls = []

        def queue(command, payload, *, identity=None):
            calls.append((command, payload, identity))
            return 0

        with mock.patch.object(lifehug, "_job_runner_active", return_value=False), \
                mock.patch.object(lifehug, "run_python", return_value=0), \
                mock.patch.object(lifehug, "_queue_and_wait", side_effect=queue), \
                mock.patch.object(jobs, "configure"), \
                mock.patch.object(
                    jobs,
                    "enqueue_classification_refresh",
                    return_value={"id": "a" * 20},
                ) as enqueue_refresh:
            self.assertEqual(lifehug.cmd_ingest_story(ingest), 0)
            self.assertEqual(lifehug.cmd_conversation_close(close), 0)

        enqueue_refresh.assert_called_once_with(kick=True)
        self.assertEqual(calls[0], (
            "conversation-close",
            {"session_id": "conv-20260917-120000-abcdef", "reason": "done"},
            "conversation-close:conv-20260917-120000-abcdef",
        ))

    def test_refresh_runs_downstream_only_after_accepted_changes(self) -> None:
        args = lifehug.build_parser().parse_args(["classification-refresh"])
        unchanged = {
            "status": "unchanged",
            "accepted_sources": [],
            "counts": {"accepted": 0, "refused": 0, "already_current": 0},
            "selection": {"remaining_count": 0},
        }
        accepted = {
            "status": "accepted",
            "accepted_sources": ["sources/manual/older.md"],
            "counts": {"accepted": 1, "refused": 0, "already_current": 0},
            "selection": {"remaining_count": 0},
        }
        with mock.patch.object(lifehug, "_job_runner_active", return_value=True), \
                mock.patch.object(classification_refresh, "run_batch", return_value=unchanged), \
                mock.patch.object(lifehug, "cmd_migrate_classifier_moments") as migrate, \
                mock.patch.object(lifehug, "cmd_timeline_retire") as retire, \
                mock.patch.object(lifehug, "cmd_compile") as compile_wiki:
            self.assertEqual(lifehug.cmd_classification_refresh(args), 0)
            migrate.assert_not_called()
            retire.assert_not_called()
            compile_wiki.assert_not_called()

        with mock.patch.object(lifehug, "_job_runner_active", return_value=True), \
                mock.patch.object(classification_refresh, "run_batch", return_value=accepted), \
                mock.patch.object(
                    lifehug, "cmd_migrate_classifier_moments", return_value=0
                ) as migrate, mock.patch.object(
                    lifehug, "cmd_timeline_retire", return_value=0
                ) as retire, mock.patch.object(
                    lifehug, "cmd_compile", return_value=0
                ) as compile_wiki:
            self.assertEqual(lifehug.cmd_classification_refresh(args), 0)
            self.assertEqual(migrate.call_args.args[0].source, ["sources/manual/older.md"])
            retire.assert_called_once()
            self.assertTrue(compile_wiki.call_args.args[0].no_ai)

    def test_hosted_processor_modules_do_not_import_the_local_queue(self) -> None:
        for name in ("process_answer.py", "ingest_story.py"):
            source = (SYSTEM / name).read_text(encoding="utf-8")
            self.assertNotIn("import jobs", source)
            self.assertNotIn("jobs.enqueue", source)


if __name__ == "__main__":
    unittest.main()
