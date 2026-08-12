"""v156 / issue #119 — conversation-close batching, jobs, Mirror inbound,
and the engagement quality-profile dimension (Conversation Interaction,
Wave 2 PR 6).

Four tightly-coupled pieces, tested at the level each actually lives:

* the in-session batching default in ``process_answer.py`` and the full
  close orchestration in ``lifehug.py`` — subprocess, against a synthetic
  vault with a real (local, remote-less) git repo, matching the
  ``ExternalVaultSubprocessTests`` precedent (tests/test_v120_vault_only.py);
* the idle-sweep's discovery/enqueue logic — in-process, with
  ``conversation.REPO_DIR`` pointed at the fixture and
  ``lifehug._queue_and_wait`` mocked so the test proves identity/selection,
  not the job worker;
* the ``jobs.py`` command-registry contract — in-process, unit-level;
* the engagement dimension in ``quality_profile.py`` and its two consumers
  — in-process, private module copies (``load()``, the
  tests/test_v69_signal.py idiom) so file constants are freely overridable.

Synthetic data only — NEVER ~/Workspace/dave.
"""

from __future__ import annotations

import importlib.util
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

from tempdirs import root_parent_tmp  # noqa: E402
import conversation  # noqa: E402
import jobs  # noqa: E402
import lifehug  # noqa: E402
import mirror  # noqa: E402


def load(name: str):
    """Load a private copy of system/<name>.py WITHOUT clobbering the shared
    sys.modules entry (tests/test_v69_signal.py idiom) — lets a test freely
    override module-level file-path constants without splitting state other
    test modules depend on."""
    spec = importlib.util.spec_from_file_location(name, SYSTEM / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    orig = sys.modules.get(name)
    sys.modules[name] = mod
    try:
        spec.loader.exec_module(mod)
    finally:
        if orig is not None:
            sys.modules[name] = orig
        else:
            sys.modules.pop(name, None)
    return mod


QUESTION_BANK = """# Synthetic Lifehug questions

## A: Origins
- [ ] A1: What is your earliest synthetic memory?
- [ ] A2: What did the synthetic kitchen smell like?
"""


def make_vault(root: Path) -> Path:
    """Minimal on-disk vault: question bank, rotation, coverage, git repo
    with one baseline commit. Matches tests/test_v120_vault_only.py's
    ``make_vault`` shape (proven to run ``process-answer`` successfully)."""
    root.mkdir(parents=True)
    state = root / "state"
    state.mkdir()
    (root / "question-bank.md").write_text(QUESTION_BANK, encoding="utf-8")
    (state / "rotation.json").write_text(json.dumps({
        "version": 1,
        "current_pass": 1,
        "pass_names": ["skeleton"],
        "last_question_id": None,
        "last_asked_at": None,
        "questions_asked": 0,
        "questions_answered": 0,
        "next_question_id": None,
        "focus_frequency": 4,
    }, indent=2) + "\n", encoding="utf-8")
    (state / "coverage.json").write_text(json.dumps({
        "version": 1,
        "last_updated": None,
        "categories": {"A": {"total": 2, "answered": 0, "status": "red"}},
    }, indent=2) + "\n", encoding="utf-8")
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.email", "synthetic@example.invalid"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.name", "Synthetic Fixture"], cwd=root, check=True)
    subprocess.run(["git", "add", "."], cwd=root, check=True)
    subprocess.run(["git", "commit", "-qm", "synthetic baseline"], cwd=root, check=True)
    return root


def commit_count(root: Path) -> int:
    result = subprocess.run(
        ["git", "-C", str(root), "rev-list", "--count", "HEAD"],
        capture_output=True, text=True, check=True,
    )
    return int(result.stdout.strip())


def last_commit_message(root: Path) -> str:
    result = subprocess.run(
        ["git", "-C", str(root), "log", "-1", "--format=%s"],
        capture_output=True, text=True, check=True,
    )
    return result.stdout.strip()


class VaultSubprocessTestCase(unittest.TestCase):
    """A synthetic vault driven via subprocess (env ``LIFEHUG_VAULT_ROOT``) —
    the only reliable way to exercise lifehug.py/process_answer.py's
    module-level, import-time-bound file constants against a fixture,
    matching the codebase's own ExternalVaultSubprocessTests precedent."""

    def setUp(self):
        self.tmp = root_parent_tmp(self, ROOT, prefix="lifehug-v156-close-")
        self.vault = make_vault(self.tmp / "vault")
        import os
        self.env = os.environ.copy()
        self.env.update({
            "LIFEHUG_VAULT_ROOT": str(self.vault),
            "LIFEHUG_JOB_DRAIN_IDLE": "0.05",
            "LIFEHUG_JOB_POLL_SECONDS": "0.02",
            "PYTHONDONTWRITEBYTECODE": "1",
        })
        self.env.pop("WORKSPACE", None)
        self.env.pop("PYTHONPATH", None)

    def run_script(self, script: str, *args: str, input_text: str | None = None,
                    timeout: float = 60) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(SYSTEM / script), *args],
            input=input_text, capture_output=True, text=True,
            env=self.env, cwd=self.vault, timeout=timeout,
        )

    def open_session(self, *, question_id: str = "A2", mode: str = "chat") -> str:
        doc = conversation.open_session(
            mode, "telegram", arc={"question_id": question_id}, vault_root=self.vault,
        )
        return str(doc["session_id"])

    def sentinel(self) -> Path:
        return self.vault / "state" / ".compile-needed"

    def answer_scores(self) -> dict:
        path = self.vault / "state" / "answer_scores.json"
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"scores": []}

    def mirror_responses(self) -> dict:
        path = self.vault / "state" / "mirror_responses.json"
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"responses": []}


class ProcessAnswerBatchingTests(VaultSubprocessTestCase):
    """Scope §1 — in-session filing batches by default."""

    def test_in_session_answer_skips_compile_and_commits_and_touches_sentinel(self):
        self.open_session(question_id="A2")
        before = commit_count(self.vault)

        result = self.run_script(
            "process_answer.py", "A2", "--source", "text",
            input_text="A synthetic answer filed inside an open session.\n",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("sentinel touched", result.stdout)
        self.assertNotIn("Compiled wiki", result.stdout)
        self.assertTrue(self.sentinel().exists(), "compile-needed sentinel must be touched")
        # No --commit/--push were passed, so no commit either way — the
        # in-session default and the no-flags default agree here; the
        # per-answer commits stay gone regardless.
        self.assertEqual(commit_count(self.vault), before)

    def test_no_session_behavior_unchanged(self):
        """Regression guard: no open session -> today's exact behavior,
        UNCHANGED by this PR — ``finalize_answer_delivery`` still attempts
        the two commits ("Answer A1: ..." then "Record answer A1 delivery
        metadata"). In this keyless test environment (no AI provider, no
        Telegram) the conversation turn degrades to a metadata-only skip and
        mints no follow-up, so nothing in the second commit's tracked-path
        set actually changed — its ``git commit`` is a legitimate no-op,
        exactly as it was before this PR (this test asserts that SEQUENCE
        is unchanged, not a specific commit count that depends on provider
        availability)."""
        before = commit_count(self.vault)

        result = self.run_script(
            "process_answer.py", "A1", "--source", "text", "--commit",
            input_text="A synthetic answer with no conversation session.\n",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Compiled wiki", result.stdout)
        self.assertFalse(self.sentinel().exists())
        self.assertEqual(commit_count(self.vault), before + 1)
        self.assertEqual(last_commit_message(self.vault), "Answer A1: What is your earliest synthetic memory?")

    def test_explicit_flags_override_session_default(self):
        self.open_session(question_id="A2")
        before = commit_count(self.vault)

        result = self.run_script(
            "process_answer.py", "A2", "--source", "text", "--compile-wiki", "--commit",
            input_text="A synthetic answer with explicit overrides.\n",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        # --compile-wiki wins over the session default: compile ran, no sentinel.
        self.assertIn("Compiled wiki", result.stdout)
        self.assertFalse(self.sentinel().exists())
        # --commit wins too: finalize_answer_delivery still attempts both
        # commits despite the session (see test_no_session_behavior_unchanged
        # for why only the first is non-empty in this keyless environment).
        self.assertEqual(commit_count(self.vault), before + 1)

    def test_absent_signals_never_fabricated(self):
        """No session at all -> the engagement block carries ONLY
        time_to_answer_hours (lesson 1's absent-signal-never-fabricated law,
        the #119 half of it)."""
        result = self.run_script(
            "process_answer.py", "A1", "--source", "text",
            input_text="A synthetic answer with no session anywhere.\n",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        scores = {s["question_id"]: s for s in self.answer_scores()["scores"]}
        engagement = scores["A1"].get("engagement")
        self.assertIsNotNone(engagement)
        self.assertEqual(set(engagement), {"time_to_answer_hours"})
        self.assertIsInstance(engagement["time_to_answer_hours"], (int, float))
        self.assertGreaterEqual(engagement["time_to_answer_hours"], 0)


class ConversationCloseCommandTests(VaultSubprocessTestCase):
    """Scope §2/§3/§4 — the durable close command's own filing/compile/commit
    steps, and the idle-sweep's stable identity."""

    def test_close_files_outputs_then_one_commit(self):
        session_id = self.open_session(question_id="A2")
        conversation.append_turn(
            session_id,
            {"role": "user", "text": "A synthetic user turn.", "channel": "telegram",
             "question_id": "A2"},
            expected_turns=0, vault_root=self.vault,
        )
        conversation.merge_session_extraction(
            session_id,
            extracted={"mirror_responses": [
                {"text": "I keep circling back to this and I think it's fine now.",
                 "tension_ref": "Sit with: the mantle you wear"},
            ]},
            vault_root=self.vault,
        )
        # Sentinel present beforehand (as if an earlier batched answer touched
        # it) — the close's own compile must clear it.
        self.sentinel().parent.mkdir(parents=True, exist_ok=True)
        self.sentinel().touch()
        before = commit_count(self.vault)

        result = self.run_script("lifehug.py", "conversation-close", session_id)
        self.assertEqual(result.returncode, 0, result.stderr)

        # Exactly one new commit, named per the contract.
        self.assertEqual(commit_count(self.vault), before + 1)
        self.assertEqual(last_commit_message(self.vault), f"Conversation close {session_id}")
        self.assertFalse(self.sentinel().exists())

        # Mirror inbound filed.
        responses = self.mirror_responses()["responses"]
        self.assertEqual(len(responses), 1)
        self.assertEqual(responses[0]["session_id"], session_id)
        self.assertIn("circling back", responses[0]["text"])

        # mirror.py has no vault_root override (single-vault-per-process, like
        # the rest of this CLI family) — point it at the fixture to read back
        # what the subprocess just wrote.
        saved = mirror.MIRROR_RESPONSES_FILE, mirror.CLASSIFICATIONS_DIR
        mirror.MIRROR_RESPONSES_FILE = self.vault / "state" / "mirror_responses.json"
        mirror.CLASSIFICATIONS_DIR = self.vault / "state" / "classifications"
        try:
            entries = mirror.load_mirror_entries()
        finally:
            mirror.MIRROR_RESPONSES_FILE, mirror.CLASSIFICATIONS_DIR = saved
        self.assertTrue(any(e["kind"] == "response" for e in entries))

        # The session is durably closed.
        closed = conversation.load_session(session_id, vault_root=self.vault)
        self.assertEqual(closed["status"], "closed")

    def test_close_git_failure_is_nonfatal_and_recorded(self):
        """No git repo at all -> the commit step fails but the close (and
        its filing) still succeeds; the failure is recorded, not raised."""
        no_git_vault = self.tmp / "no-git-vault"
        make_vault(no_git_vault)  # git-shaped fixture, but we never git-init it below
        import shutil
        shutil.rmtree(no_git_vault / ".git")
        session_id = conversation.open_session(
            "chat", "telegram", arc={"question_id": "A2"}, vault_root=no_git_vault,
        )["session_id"]
        conversation.append_turn(
            session_id,
            {"role": "user", "text": "A synthetic user turn.", "channel": "telegram",
             "question_id": "A2"},
            expected_turns=0, vault_root=no_git_vault,
        )
        conversation.merge_session_extraction(
            session_id, extracted={"mirror_responses": [{"text": "Still sitting with it."}]},
            vault_root=no_git_vault,
        )
        env = dict(self.env)
        env["LIFEHUG_VAULT_ROOT"] = str(no_git_vault)

        result = subprocess.run(
            [sys.executable, str(SYSTEM / "lifehug.py"), "conversation-close", session_id],
            capture_output=True, text=True, env=env, cwd=no_git_vault, timeout=60,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

        responses = json.loads(
            (no_git_vault / "state" / "mirror_responses.json").read_text(encoding="utf-8")
        )["responses"]
        self.assertEqual(len(responses), 1)

        failures = (no_git_vault / "state" / "learning_failures.jsonl").read_text(encoding="utf-8")
        self.assertIn("git_commit", failures)

    def test_sweep_enqueues_only_idle_expired_open_sessions_with_stable_identity(self):
        """Deterministic discovery: only OPEN + idle-expired sessions get
        enqueued, one job per session, identity conversation-close:<id>."""
        expired = conversation.open_session(
            "chat", "telegram", arc={"question_id": "A2"},
            session_id="conv-20200101-000000-aaaaaa", vault_root=self.vault,
        )
        fresh = conversation.open_session(
            "chat", "telegram", arc={"question_id": "A1"}, vault_root=self.vault,
        )
        closed = conversation.open_session(
            "chat", "telegram", arc={"question_id": "A1"},
            session_id="conv-20200101-000000-bbbbbb", vault_root=self.vault,
        )
        conversation.close_session(closed["session_id"], {"reason": "done"}, vault_root=self.vault)

        calls: list[tuple[str, dict, str | None]] = []

        def fake_queue_and_wait(command, payload, *, identity=None):
            calls.append((command, payload, identity))
            return 0

        with mock.patch.object(lifehug, "REPO_DIR", self.vault), \
             mock.patch.object(lifehug, "_queue_and_wait", side_effect=fake_queue_and_wait):
            rc = lifehug._enqueue_expired_conversation_closes()

        self.assertEqual(rc, 0)
        self.assertEqual(len(calls), 1, calls)
        command, payload, identity = calls[0]
        self.assertEqual(command, "conversation-close")
        self.assertEqual(payload["session_id"], expired["session_id"])
        self.assertEqual(payload["reason"], "idle_timeout")
        self.assertEqual(identity, f"conversation-close:{expired['session_id']}")
        # The fresh and already-closed sessions never got enqueued.
        enqueued_ids = {p["session_id"] for _c, p, _i in calls}
        self.assertNotIn(fresh["session_id"], enqueued_ids)
        self.assertNotIn(closed["session_id"], enqueued_ids)


class JobsConversationCloseCommandTests(unittest.TestCase):
    """Scope §2 — the jobs.py command-registry contract."""

    def test_conversation_close_command_registered_and_payload_validated(self):
        self.assertIn("conversation-close", jobs.COMMANDS)
        spec = jobs.COMMANDS["conversation-close"]
        self.assertEqual(spec.retry_safety, "never")

        invocations = spec.build({"session_id": "conv-20260811-140000-abc123"})
        self.assertEqual(len(invocations), 1)
        self.assertEqual(
            invocations[0].arguments,
            ("conversation-close", "conv-20260811-140000-abc123", "--reason", "done"),
        )

        invocations = spec.build({"session_id": "conv-20260811-140000-abc123", "reason": "idle_timeout"})
        self.assertIn("--reason", invocations[0].arguments)
        self.assertIn("idle_timeout", invocations[0].arguments)

        with self.assertRaises(ValueError):
            spec.build({"session_id": "not-a-valid-session-id"})
        with self.assertRaises(ValueError):
            spec.build({"session_id": "conv-20260811-140000-abc123", "unexpected": "field"})
        with self.assertRaises(ValueError):
            spec.build({})
        with self.assertRaises(ValueError):
            spec.build({"session_id": "conv-20260811-140000-abc123", "reason": "bogus"})


class MirrorInboundTests(unittest.TestCase):
    """Scope §4 — surgical, mirrors tests/test_mirror.py's own fixture style."""

    def setUp(self):
        self.tmp = root_parent_tmp(self, ROOT, prefix="lifehug-v156-mirror-")
        self._saved = mirror.MIRROR_RESPONSES_FILE
        mirror.MIRROR_RESPONSES_FILE = self.tmp / "mirror_responses.json"
        self.addCleanup(setattr, mirror, "MIRROR_RESPONSES_FILE", self._saved)

    def test_mirror_responses_written_idempotently(self):
        responses = [
            {"session_id": "conv-1", "text": "Still sitting with it.", "tension_ref": "t1",
             "responded_at": "2026-08-16T21:04:00Z"},
        ]
        self.assertEqual(mirror.append_mirror_responses(responses), 1)
        self.assertEqual(mirror.append_mirror_responses(responses), 0)  # idempotent replay
        data = json.loads(mirror.MIRROR_RESPONSES_FILE.read_text(encoding="utf-8"))
        self.assertEqual(len(data["responses"]), 1)
        self.assertEqual(data["version"], 1)

        # Same session, DIFFERENT text -> a second, distinct entry.
        self.assertEqual(mirror.append_mirror_responses(
            [{"session_id": "conv-1", "text": "A genuinely new reply."}]), 1)
        data = json.loads(mirror.MIRROR_RESPONSES_FILE.read_text(encoding="utf-8"))
        self.assertEqual(len(data["responses"]), 2)


class EngagementFieldsTests(unittest.TestCase):
    """Scope §5, lesson 1 — every engagement field demonstrably fires from a
    real capture path; nothing is ever fabricated for an absent signal."""

    def setUp(self):
        self.tmp = root_parent_tmp(self, ROOT, prefix="lifehug-v156-engagement-")
        self.scores_path = self.tmp / "answer_scores.json"

    def _seed(self, records: list[dict]) -> None:
        self.scores_path.write_text(json.dumps({"version": 1, "scores": records}), encoding="utf-8")

    def test_engagement_fields_fire_from_fixture_capture(self):
        # process_answer.py's own write (answer time, session or not).
        self._seed([{
            "question_id": "A2", "answered_at": "2026-08-11", "category": "A",
            "story_function": "scene", "focus": None, "signals": {"word_count": 42},
            "richness_score": 0.6, "engagement": {"time_to_answer_hours": 3.5},
        }])
        import conversation_delivery as engine
        import quality_profile

        session = {
            "session_id": "conv-20260811-140000-abcdef",
            "mode": "conversation",  # user-initiated -> unprompted_inbound fires True
            "turns": [
                {"role": "user", "text": "short", "question_id": "A2"},
                {"role": "lifehug", "text": "..."},
                {"role": "user", "text": "a much longer reply that keeps expanding outward",
                 "question_id": "A2"},
            ],
        }
        with mock.patch.object(engine, "record_learning_failure"):
            engine.append_engagement(session, close_reason="done", manifest={},
                                      scores_path=self.scores_path)
        # The engine's own write is session-turn fields only; unprompted_inbound
        # is #119's own close-time addition (lifehug._file_engagement_timing).
        quality_profile.merge_engagement(
            "A2", {"unprompted_inbound": session["mode"] == "conversation"}, scores_path=self.scores_path,
        )

        engagement = json.loads(self.scores_path.read_text(encoding="utf-8"))["scores"][0]["engagement"]
        for field in ("time_to_answer_hours", "continuation_past_exit",
                      "turn_length_trajectory", "unprompted_inbound"):
            self.assertIn(field, engagement, engagement)
        # The two writers COMPOSE — process_answer.py's field survives PR3's
        # close-time write (the merge fix this PR makes to append_engagement).
        self.assertEqual(engagement["time_to_answer_hours"], 3.5)
        self.assertTrue(engagement["unprompted_inbound"])
        self.assertEqual(engagement["turn_length_trajectory"], "expanding")

    def test_absent_signals_never_fabricated_no_session_record(self):
        """A record that never touched a session gets NOTHING beyond
        whatever process_answer.py itself seeded — merge_engagement never
        invents a record."""
        self._seed([{
            "question_id": "A9", "answered_at": "2026-08-11", "category": "A",
            "story_function": "scene", "focus": None, "signals": {},
            "richness_score": 0.4, "engagement": {"time_to_answer_hours": 1.0},
        }])
        import quality_profile
        self.assertFalse(quality_profile.merge_engagement(
            "NOT-A-REAL-ID", {"unprompted_inbound": True}, scores_path=self.scores_path,
        ))
        engagement = json.loads(self.scores_path.read_text(encoding="utf-8"))["scores"][0]["engagement"]
        self.assertEqual(engagement, {"time_to_answer_hours": 1.0})


class EngagementProfileTests(unittest.TestCase):
    """Scope §5 — aggregation, canonical vocabulary (lesson 2), clamps and
    the activation threshold."""

    def setUp(self):
        self.qprof = load("quality_profile")
        self.tmp = root_parent_tmp(self, ROOT, prefix="lifehug-v156-profile-")
        self.qprof.ANSWER_SCORES_FILE = self.tmp / "answer_scores.json"
        self.qprof.QUALITY_PROFILE_FILE = self.tmp / "quality_profile.json"

    def _record(self, qid: str, story_function: str, *, continuation: bool) -> dict:
        return {
            "question_id": qid, "answered_at": "2026-08-11", "category": "A",
            "story_function": story_function, "focus": None,
            "signals": {"word_count": 40}, "richness_score": 0.5,
            "engagement": {"continuation_past_exit": continuation},
        }

    def test_engagement_buckets_use_canonical_story_function(self):
        records = (
            [self._record(f"L{i}", "origin_story", continuation=True) for i in range(5)]
            + [self._record(f"S{i}", "scene", continuation=False) for i in range(5)]
        )
        self.qprof.save_scores({"version": 1, "scores": records})
        profile = self.qprof.compute_profile()
        buckets = profile["engagement"]["by_story_function"]
        self.assertIn("foundation", buckets)  # canonical, not "origin_story"
        self.assertNotIn("origin_story", buckets)

    def test_engagement_multiplier_clamped_and_inactive_below_threshold(self):
        # Below ACTIVATION_THRESHOLD (20 records) -> inactive, regardless of
        # per-bucket counts.
        records = [self._record(f"Q{i}", "scene", continuation=True) for i in range(10)]
        self.qprof.save_scores({"version": 1, "scores": records})
        profile = self.qprof.compute_profile()
        self.assertFalse(profile["engagement"]["active"])

        # At/above threshold: a bucket with count >= 5 whose avg is far above
        # the global average clamps at MULTIPLIER_CAP; a matching low bucket
        # clamps at MULTIPLIER_FLOOR. A thin (<5) bucket stays neutral (1.0)
        # even though its raw avg would otherwise justify a multiplier.
        high = [self._record(f"H{i}", "scene", continuation=True) for i in range(10)]
        low = [self._record(f"L{i}", "tension", continuation=False) for i in range(9)]
        thin = [self._record("T0", "meaning", continuation=True)]
        self.qprof.save_scores({"version": 1, "scores": high + low + thin})
        profile = self.qprof.compute_profile()
        engagement = profile["engagement"]
        self.assertTrue(engagement["active"])
        self.assertEqual(engagement["by_story_function"]["scene"]["multiplier"],
                          self.qprof.MULTIPLIER_CAP)
        self.assertEqual(engagement["by_story_function"]["tension"]["multiplier"],
                          self.qprof.MULTIPLIER_FLOOR)
        self.assertEqual(engagement["by_story_function"]["meaning"]["multiplier"], 1.0)

    def test_engagement_inactive_stub_has_full_shape(self):
        profile = self.qprof.compute_profile()  # zero scores at all
        engagement = profile["engagement"]
        self.assertFalse(engagement["active"])
        self.assertEqual(engagement["scored"], 0)
        self.assertEqual(engagement["by_story_function"], {})


class PlannerEngagementTests(unittest.TestCase):
    """Scope §5 consumer #1 — question_planner applies the multiplier as
    pacing/framing ONLY; the self-knowledge floor is untouched."""

    SELF_BANK = """# Synthetic Lifehug questions

## A: Origins
- [ ] A1: What do you fear becoming?
- [ ] A2: What did the synthetic kitchen smell like?
"""

    def setUp(self):
        import question_planner as qp

        self.qp = qp
        self.tmp = root_parent_tmp(self, ROOT, prefix="lifehug-v156-planner-")
        bank = self.tmp / "question-bank.md"
        bank.write_text(self.SELF_BANK, encoding="utf-8")
        self._saved_questions_file = qp.QUESTIONS_FILE
        qp.QUESTIONS_FILE = bank
        self.addCleanup(setattr, qp, "QUESTIONS_FILE", self._saved_questions_file)

    def test_planner_applies_engagement_multiplier_but_self_floor_untouched(self):
        qp = self.qp
        fake_profile = {
            "active": True,
            "engagement": {
                "active": True,
                "by_story_function": {"fear": {"avg": 0.2, "count": 8, "multiplier": 0.7}},
            },
        }
        with mock.patch("quality_profile.load_profile", return_value=fake_profile):
            questions, categories, coverage = qp.load_question_state()
            rows = qp.enriched_pending_questions(questions, categories, coverage, [])
            fear_row = next(r for r in rows if r["story_function"] == "fear")
            # The 0.7 engagement multiplier is folded into the weight...
            self.assertLess(fear_row["weight"], 1.0)

            data = qp.build_queue(limit=4, arc_max=2, seed=7)
            # ...but the self-knowledge floor still reserves and fills its
            # slot — a 0.7-weighted self question beats an empty slot.
            self_ids = {q["question_id"] for q in data["queue"]
                        if q["story_function"] in qp.SELF_FUNCTIONS}
            self.assertIn("A1", self_ids)


if __name__ == "__main__":
    unittest.main()
