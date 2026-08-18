"""v182 / issue #170 — canonical candidate promotion receipt authority."""

from __future__ import annotations

import base64
import concurrent.futures
import inspect
import json
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SYSTEM = ROOT / "system"
sys.path.insert(0, str(SYSTEM))
sys.path.insert(0, str(ROOT / "tests"))

import candidate_promotion as promotion
import question_candidates as manager
import roadmap
from tempdirs import root_parent_tmp

BANK = (
    "# Questions\n\n"
    "## A: Origins (Childhood)\n\n"
    "- [ ] A1: What is your earliest synthetic memory?\n\n"
    "## B: Family\n\n"
    "- [ ] B1: Who taught you to listen?\n"
)


def _run(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(root), *args],
        check=False,
        capture_output=True,
        text=True,
    )


class PromotionCase(unittest.TestCase):
    def setUp(self):
        self.tmp = root_parent_tmp(self, ROOT, prefix="lifehug-promotion-")
        state = self.tmp / "state"
        state.mkdir()
        (self.tmp / ".gitignore").write_text("state/jobs/\n", encoding="utf-8")
        (self.tmp / "question-bank.md").write_text(BANK, encoding="utf-8")
        (state / "rotation.json").write_text(
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
            )
            + "\n",
            encoding="utf-8",
        )
        (state / "coverage.json").write_text(
            json.dumps({"version": 1, "last_updated": None, "categories": {}}) + "\n",
            encoding="utf-8",
        )
        self.candidate = {
            "id": "cand-synthetic-1",
            "text": "What did the paper lighthouse teach you about waiting?",
            "status": "candidate",
            "source_path": "sources/synthetic.md",
            "source_id": "SYN-1",
            "origin": "fixture",
            "source_type": "synthetic",
            "created_at": "2026-08-18T00:00:00Z",
            "reason": "synthetic test",
            "neighborhood_id": "nbhd-synthetic",
        }
        self._write_store([self.candidate])
        self.assertEqual(_run(self.tmp, "init", "-b", "main").returncode, 0)
        self.assertEqual(_run(self.tmp, "config", "user.name", "Fixture").returncode, 0)
        self.assertEqual(
            _run(
                self.tmp, "config", "user.email", "fixture@example.invalid"
            ).returncode,
            0,
        )
        self.assertEqual(_run(self.tmp, "add", ".").returncode, 0)
        self.assertEqual(_run(self.tmp, "commit", "-m", "fixture").returncode, 0)

    def _write_store(self, candidates: list[dict]) -> None:
        (self.tmp / "state" / "question_candidates.json").write_text(
            json.dumps(
                {
                    "version": 1,
                    "last_updated": "2026-08-18T00:00:00Z",
                    "candidates": candidates,
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )

    def request(self, category: str = "A") -> dict:
        return promotion.build_current_request(
            self.candidate["id"], category, vault_root=self.tmp
        )


class ReceiptTests(PromotionCase):
    def test_first_promotion_and_replay_have_one_question_and_stable_receipt(self):
        request = self.request()
        first = promotion.resolve_candidate_promotion(
            request, vault_root=self.tmp, push=False
        )
        replay = promotion.resolve_candidate_promotion(
            request, vault_root=self.tmp, push=False
        )
        self.assertTrue(first["changed"])
        self.assertFalse(replay["changed"])
        self.assertEqual(
            {k: v for k, v in first.items() if k != "changed"},
            {k: v for k, v in replay.items() if k != "changed"},
        )
        bank = (self.tmp / "question-bank.md").read_text(encoding="utf-8")
        self.assertEqual(bank.count(self.candidate["text"]), 1)
        self.assertEqual(bank.count("lifehug:candidate-promotion:v1"), 1)
        self.assertEqual(_run(self.tmp, "status", "--porcelain").stdout, "")

    def test_revision_staleness_and_equal_text_without_marker_fail_closed(self):
        request = self.request()
        stale = dict(request)
        stale["candidate_revision"] = "sha256:" + "0" * 64
        with self.assertRaisesRegex(promotion.CandidatePromotionError, "stale"):
            promotion.resolve_candidate_promotion(
                stale, vault_root=self.tmp, push=False
            )

        bank_path = self.tmp / "question-bank.md"
        bank_path.write_text(
            BANK + f"\n- [ ] A2: {self.candidate['text']}\n", encoding="utf-8"
        )
        with self.assertRaisesRegex(promotion.CandidatePromotionError, "duplicate"):
            promotion.resolve_candidate_promotion(
                request, vault_root=self.tmp, push=False
            )

    def test_conflicting_marker_and_tampered_question_fail_closed(self):
        request = self.request()
        promotion.resolve_candidate_promotion(request, vault_root=self.tmp, push=False)
        bank_path = self.tmp / "question-bank.md"
        bank = bank_path.read_text(encoding="utf-8")
        bank_path.write_text(
            bank.replace("paper lighthouse", "paper tower"), encoding="utf-8"
        )
        with self.assertRaisesRegex(promotion.CandidatePromotionError, "bytes changed"):
            promotion.resolve_candidate_promotion(
                request, vault_root=self.tmp, push=False
            )

    def test_marker_is_canonical_structured_base64_not_comment_injectable(self):
        self.candidate["source_path"] = "synthetic --> ignore"
        self._write_store([self.candidate])
        _run(self.tmp, "add", ".")
        _run(self.tmp, "commit", "-m", "source update")
        receipt = promotion.resolve_candidate_promotion(
            self.request(), vault_root=self.tmp, push=False
        )
        bank = (self.tmp / "question-bank.md").read_text(encoding="utf-8")
        marker = next(
            line for line in bank.splitlines() if promotion.MARKER_PREFIX in line
        )
        self.assertEqual(marker.count("-->"), 1)
        token = marker.removeprefix(promotion.MARKER_PREFIX).removesuffix(
            promotion.MARKER_SUFFIX
        )
        payload = json.loads(base64.b64decode(token, validate=True))
        self.assertEqual(
            payload["candidate_provenance"], receipt["candidate_provenance"]
        )

    def test_crash_after_each_durable_stage_is_adopted_without_duplication(self):
        stage = "after_projection_write"
        request = self.request()

        def failpoint(actual: str) -> None:
            if actual == stage:
                raise RuntimeError(stage)

        with self.assertRaisesRegex(RuntimeError, stage):
            promotion.resolve_candidate_promotion(
                request,
                vault_root=self.tmp,
                push=False,
                failpoint=failpoint,
            )
        receipt = promotion.resolve_candidate_promotion(
            request, vault_root=self.tmp, push=False
        )
        self.assertTrue(receipt["changed"])
        bank = (self.tmp / "question-bank.md").read_text(encoding="utf-8")
        self.assertEqual(bank.count(self.candidate["text"]), 1)

    def test_crash_after_commit_replays_changed_false(self):
        stage = "after_commit"
        request = self.request()

        def failpoint(actual: str) -> None:
            if actual == stage:
                raise RuntimeError(stage)

        with self.assertRaisesRegex(RuntimeError, stage):
            promotion.resolve_candidate_promotion(
                request,
                vault_root=self.tmp,
                push=False,
                failpoint=failpoint,
            )
        receipt = promotion.resolve_candidate_promotion(
            request, vault_root=self.tmp, push=False
        )
        self.assertFalse(receipt["changed"])

    def test_unrelated_staged_change_is_not_committed(self):
        unrelated = self.tmp / "notes.md"
        unrelated.write_text("one\n", encoding="utf-8")
        _run(self.tmp, "add", "notes.md")
        _run(self.tmp, "commit", "-m", "notes")
        unrelated.write_text("two\n", encoding="utf-8")
        _run(self.tmp, "add", "notes.md")
        receipt = promotion.resolve_candidate_promotion(
            self.request(), vault_root=self.tmp, push=False
        )
        staged = _run(self.tmp, "diff", "--cached", "--name-only").stdout.splitlines()
        self.assertEqual(staged, ["notes.md"])
        self.assertNotIn(
            "notes.md",
            _run(
                self.tmp, "show", "--format=", "--name-only", receipt["commit_sha"]
            ).stdout,
        )

    def test_concurrent_distinct_promotions_serialize_without_duplicate_ids(self):
        second = {
            **self.candidate,
            "id": "cand-synthetic-2",
            "text": "Who kept the paper lighthouse lit through the storm?",
            "source_id": "SYN-2",
        }
        self._write_store([self.candidate, second])
        _run(self.tmp, "add", ".")
        _run(self.tmp, "commit", "-m", "second candidate")
        requests = [
            promotion.build_current_request(row["id"], "A", vault_root=self.tmp)
            for row in (self.candidate, second)
        ]
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            receipts = list(
                pool.map(
                    lambda request: promotion.resolve_candidate_promotion(
                        request, vault_root=self.tmp, push=False
                    ),
                    requests,
                )
            )
        self.assertEqual({row["question_id"] for row in receipts}, {"A2", "A3"})
        bank = (self.tmp / "question-bank.md").read_text(encoding="utf-8")
        self.assertEqual(bank.count("lifehug:candidate-promotion:v1"), 2)

    def test_concurrent_same_request_has_one_commit_identity(self):
        request = self.request()
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            receipts = list(
                pool.map(
                    lambda _index: promotion.resolve_candidate_promotion(
                        request, vault_root=self.tmp, push=False
                    ),
                    range(2),
                )
            )
        self.assertEqual({row["question_id"] for row in receipts}, {"A2"})
        self.assertEqual(
            {row["commit_sha"] for row in receipts}, {receipts[0]["commit_sha"]}
        )
        self.assertEqual(sorted(row["changed"] for row in receipts), [False, True])

    def test_push_then_crash_is_adopted_from_remote_commit(self):
        remote = root_parent_tmp(self, ROOT, prefix="lifehug-promotion-remote-")
        self.assertEqual(_run(remote, "init", "--bare").returncode, 0)
        self.assertEqual(
            _run(self.tmp, "remote", "add", "origin", str(remote)).returncode, 0
        )
        self.assertEqual(
            _run(self.tmp, "push", "--set-upstream", "origin", "main").returncode,
            0,
        )
        request = self.request()

        def failpoint(stage: str) -> None:
            if stage == "after_push":
                raise RuntimeError(stage)

        with self.assertRaisesRegex(RuntimeError, "after_push"):
            promotion.resolve_candidate_promotion(
                request,
                vault_root=self.tmp,
                push=True,
                failpoint=failpoint,
            )
        replay = promotion.resolve_candidate_promotion(
            request, vault_root=self.tmp, push=True
        )
        self.assertFalse(replay["changed"])
        self.assertEqual(
            replay["commit_sha"],
            _run(self.tmp, "rev-parse", "origin/main").stdout.strip(),
        )

    def test_stable_cli_prints_one_compact_canonical_receipt(self):
        remote = root_parent_tmp(self, ROOT, prefix="lifehug-promotion-cli-")
        self.assertEqual(_run(remote, "init", "--bare").returncode, 0)
        _run(self.tmp, "remote", "add", "origin", str(remote))
        self.assertEqual(
            _run(self.tmp, "push", "--set-upstream", "origin", "main").returncode,
            0,
        )
        request = self.request()
        command = [
            sys.executable,
            str(SYSTEM / "lifehug.py"),
            "--vault-root",
            str(self.tmp),
            "candidates-promotion-receipt",
            request["candidate_id"],
            "--category",
            request["category_id"],
            "--candidate-revision",
            request["candidate_revision"],
            "--category-revision",
            request["category_revision"],
            "--placement-revision",
            request["placement_revision"],
            "--source-revision",
            request["source_revision"],
            "--json",
        ]
        first = subprocess.run(
            command, cwd=ROOT, check=False, capture_output=True, text=True
        )
        replay = subprocess.run(
            command, cwd=ROOT, check=False, capture_output=True, text=True
        )
        self.assertEqual((first.returncode, replay.returncode), (0, 0))
        self.assertEqual((first.stderr, replay.stderr), ("", ""))
        first_receipt = json.loads(first.stdout)
        replay_receipt = json.loads(replay.stdout)
        self.assertTrue(first_receipt.pop("changed"))
        self.assertFalse(replay_receipt.pop("changed"))
        self.assertEqual(first_receipt, replay_receipt)
        self.assertEqual(first.stdout.count("\n"), 1)

    def test_stable_cli_requires_and_recomputes_bound_interaction_objects(self):
        remote = root_parent_tmp(self, ROOT, prefix="lifehug-promotion-bound-cli-")
        self.assertEqual(_run(remote, "init", "--bare").returncode, 0)
        _run(self.tmp, "remote", "add", "origin", str(remote))
        self.assertEqual(
            _run(self.tmp, "push", "--set-upstream", "origin", "main").returncode,
            0,
        )
        bank = (self.tmp / "question-bank.md").read_text(encoding="utf-8")
        anchor, _text = promotion._candidate_facts(self.candidate)
        roster = promotion._category_roster(bank)
        payload = {
            "schema_version": 1,
            "candidate": anchor,
            "roster": roster,
            "association_stage": "after_answer",
            "provisional_category_id": "A",
            "latest_user_turn": "The synthetic answer is durable.",
            "previous_placement_question": None,
            "conversation_context": None,
            "answer_status": "durable",
            "requested_outcome": "engage",
        }
        decision = promotion.question_candidate.parse_question_candidate_output(
            {}, payload=payload
        )
        proposal = {"placement_action": "resolved"}
        request = promotion.build_current_request(
            self.candidate["id"],
            "A",
            vault_root=self.tmp,
            proposal=proposal,
            decision=decision,
        )
        command = [
            sys.executable,
            str(SYSTEM / "lifehug.py"),
            "--vault-root",
            str(self.tmp),
            "candidates-promotion-receipt",
            request["candidate_id"],
            "--category",
            "A",
            "--candidate-revision",
            request["candidate_revision"],
            "--category-revision",
            request["category_revision"],
            "--placement-revision",
            request["placement_revision"],
            "--source-revision",
            request["source_revision"],
            "--proposal-revision",
            request["proposal_revision"],
            "--decision-revision",
            request["decision_revision"],
            "--question-candidate-binding-stdin",
            "--json",
        ]
        missing = subprocess.run(
            [item for item in command if item != "--question-candidate-binding-stdin"],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(missing.returncode, 2)
        self.assertIn("exact bound proposal", missing.stderr)
        result = subprocess.run(
            command,
            cwd=ROOT,
            input=json.dumps({"proposal": proposal, "decision": decision}),
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual((result.returncode, result.stderr), (0, ""))
        receipt = json.loads(result.stdout)
        self.assertEqual(
            receipt["candidate_provenance"]["decision_revision"],
            request["decision_revision"],
        )

    def test_all_caller_held_revisions_fail_closed_when_forged(self):
        current = self.request()
        for field in (
            "source_revision",
            "candidate_revision",
            "category_revision",
            "placement_revision",
        ):
            with self.subTest(field=field):
                forged = dict(current)
                forged[field] = "sha256:" + "f" * 64
                with self.assertRaisesRegex(promotion.CandidatePromotionError, "stale"):
                    promotion.resolve_candidate_promotion(
                        forged, vault_root=self.tmp, push=False
                    )

    def test_revision_bound_builder_requires_exact_caller_facts(self):
        current = self.request()
        proposal = {"placement_action": "resolved", "category_id": "A"}
        proposal_revision = promotion.question_candidate.canonical_revision(proposal)
        with self.assertRaisesRegex(
            promotion.CandidatePromotionError, "exact bound proposal"
        ):
            promotion.build_revision_bound_request(
                current["candidate_id"],
                current["category_id"],
                candidate_revision=current["candidate_revision"],
                category_revision=current["category_revision"],
                placement_revision=current["placement_revision"],
                source_revision=current["source_revision"],
                proposal_revision=proposal_revision,
                vault_root=self.tmp,
            )
        rebuilt = promotion.build_revision_bound_request(
            current["candidate_id"],
            current["category_id"],
            candidate_revision=current["candidate_revision"],
            category_revision=current["category_revision"],
            placement_revision=current["placement_revision"],
            source_revision=current["source_revision"],
            proposal_revision=proposal_revision,
            proposal=proposal,
            vault_root=self.tmp,
        )
        self.assertEqual(rebuilt["proposal_revision"], proposal_revision)
        with self.assertRaisesRegex(promotion.CandidatePromotionError, "stale"):
            promotion.build_revision_bound_request(
                current["candidate_id"],
                current["category_id"],
                candidate_revision=current["candidate_revision"],
                category_revision=current["category_revision"],
                placement_revision=current["placement_revision"],
                proposal_revision="sha256:" + "1" * 64,
                proposal=proposal,
                vault_root=self.tmp,
            )
        with self.assertRaisesRegex(promotion.CandidatePromotionError, "stale"):
            promotion.build_revision_bound_request(
                current["candidate_id"],
                current["category_id"],
                candidate_revision="sha256:" + "0" * 64,
                category_revision=current["category_revision"],
                placement_revision=current["placement_revision"],
                vault_root=self.tmp,
            )

    def test_non_null_hashes_require_exact_objects_at_resolver_boundary(self):
        proposal = {"placement_action": "resolved", "category_id": "A"}
        request = promotion.build_current_request(
            self.candidate["id"], "A", vault_root=self.tmp, proposal=proposal
        )
        with self.assertRaisesRegex(
            promotion.CandidatePromotionError, "exact bound proposal"
        ):
            promotion.resolve_candidate_promotion(
                request, vault_root=self.tmp, push=False
            )
        with self.assertRaisesRegex(promotion.CandidatePromotionError, "stale"):
            promotion.resolve_candidate_promotion(
                request,
                vault_root=self.tmp,
                push=False,
                proposal={"placement_action": "ask_now"},
            )
        receipt = promotion.resolve_candidate_promotion(
            request, vault_root=self.tmp, push=False, proposal=proposal
        )
        self.assertTrue(receipt["changed"])

    def test_push_rejection_revalidates_question_bytes_after_rebase(self):
        remote = root_parent_tmp(self, ROOT, prefix="lifehug-promotion-tamper-")
        self.assertEqual(_run(remote, "init", "--bare").returncode, 0)
        _run(self.tmp, "remote", "add", "origin", str(remote))
        self.assertEqual(
            _run(self.tmp, "push", "--set-upstream", "origin", "main").returncode,
            0,
        )
        real_git = promotion.exact_file_git._git
        rejected = False

        def tampering_git(root: Path, *args: str):
            nonlocal rejected
            if args == ("push",) and not rejected:
                rejected = True
                return subprocess.CompletedProcess(args, 1, "", "synthetic reject")
            if rejected and args == ("pull", "--rebase", "--autostash"):
                bank_path = self.tmp / "question-bank.md"
                bank_path.write_text(
                    bank_path.read_text(encoding="utf-8").replace(
                        "paper lighthouse", "tampered lighthouse"
                    ),
                    encoding="utf-8",
                )
                return subprocess.CompletedProcess(args, 0, "", "")
            return real_git(root, *args)

        with mock.patch.object(promotion.exact_file_git, "_git", tampering_git):
            with self.assertRaisesRegex(
                promotion.CandidatePromotionError,
                "bytes changed|intended record changed",
            ):
                promotion.resolve_candidate_promotion(
                    self.request(), vault_root=self.tmp, push=True
                )

    def test_push_rejection_revalidates_request_provenance_after_rebase(self):
        remote = root_parent_tmp(self, ROOT, prefix="lifehug-promotion-stale-")
        self.assertEqual(_run(remote, "init", "--bare").returncode, 0)
        _run(self.tmp, "remote", "add", "origin", str(remote))
        self.assertEqual(
            _run(self.tmp, "push", "--set-upstream", "origin", "main").returncode,
            0,
        )
        request = self.request()
        real_git = promotion.exact_file_git._git
        rejected = False

        def tampering_git(root: Path, *args: str):
            nonlocal rejected
            if args == ("push",) and not rejected:
                rejected = True
                return subprocess.CompletedProcess(args, 1, "", "synthetic reject")
            if rejected and args == ("pull", "--rebase", "--autostash"):
                store_path = self.tmp / "state" / "question_candidates.json"
                store = json.loads(store_path.read_text(encoding="utf-8"))
                store["candidates"][0]["source_id"] = "FORGED"
                store_path.write_text(
                    json.dumps(store, indent=2) + "\n", encoding="utf-8"
                )
                return subprocess.CompletedProcess(args, 0, "", "")
            return real_git(root, *args)

        with mock.patch.object(promotion.exact_file_git, "_git", tampering_git):
            with self.assertRaisesRegex(
                promotion.CandidatePromotionError, "source_revision is stale"
            ):
                promotion.resolve_candidate_promotion(
                    request, vault_root=self.tmp, push=True
                )

    def test_complete_question_candidate_decision_binds_and_incomplete_fails(self):
        bank = (self.tmp / "question-bank.md").read_text(encoding="utf-8")
        anchor, _text = promotion._candidate_facts(self.candidate)
        roster = promotion._category_roster(bank)
        payload = {
            "schema_version": 1,
            "candidate": anchor,
            "roster": roster,
            "association_stage": "after_answer",
            "provisional_category_id": "A",
            "latest_user_turn": "The synthetic answer is already durably filed.",
            "previous_placement_question": None,
            "conversation_context": None,
            "answer_status": "durable",
            "requested_outcome": "engage",
        }
        decision = promotion.question_candidate.parse_question_candidate_output(
            {}, payload=payload
        )
        request = promotion.build_candidate_promotion_request(
            self.candidate,
            bank,
            "A",
            proposal={"placement_action": "resolved"},
            decision=decision,
        )
        self.assertIsNotNone(request["proposal_revision"])
        self.assertIsNotNone(request["decision_revision"])
        with self.assertRaisesRegex(
            promotion.CandidatePromotionError, "exact bound decision"
        ):
            promotion.resolve_candidate_promotion(
                request,
                vault_root=self.tmp,
                push=False,
                proposal={"placement_action": "resolved"},
            )
        receipt = promotion.resolve_candidate_promotion(
            request,
            vault_root=self.tmp,
            push=False,
            proposal={"placement_action": "resolved"},
            decision=decision,
        )
        self.assertTrue(receipt["changed"])
        incomplete = {**decision, "status": "active"}
        with self.assertRaisesRegex(
            promotion.CandidatePromotionError, "decision invalid"
        ):
            promotion.build_candidate_promotion_request(
                self.candidate, bank, "A", decision=incomplete
            )

    def test_promotion_callsites_delegate_to_the_canonical_authority(self):
        pure = inspect.getsource(manager.promote_candidate_record) + inspect.getsource(
            manager.promote_neighborhood
        )
        durable = (
            inspect.getsource(manager.cmd_promote)
            + inspect.getsource(manager.cmd_promote_neighborhood)
            + inspect.getsource(manager.auto_promote_candidates)
        )
        self.assertIn("candidate_promotion.apply_candidate_promotion", pure)
        self.assertNotIn("insert_question(", pure)
        self.assertIn("candidate_promotion.resolve_candidate_promotion", durable)
        self.assertNotIn("insert_question(", durable)
        roadmap_source = inspect.getsource(roadmap._generate_and_promote)
        self.assertIn("candidate_promotion.resolve_candidate_promotion", roadmap_source)
        self.assertNotIn("promote_neighborhood(", roadmap_source)
        authority = inspect.getsource(promotion)
        self.assertIn("exact_file_git.resolve_exact_file_transaction", authority)
        self.assertNotIn("subprocess.run", authority)


if __name__ == "__main__":
    unittest.main()
