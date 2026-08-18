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
import conversation_delivery as engine  # noqa: E402
import lifehug_core as core  # noqa: E402
from ai_provider import ProviderStatus  # noqa: E402


def load(name):
    spec = importlib.util.spec_from_file_location(name, SYSTEM / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def ready_status(*_args, **_kwargs):
    return ProviderStatus("local-openai", "synthetic-model", True, "synthetic")


def keyless_status(*_args, **_kwargs):
    return ProviderStatus("agent-task", "synthetic-model", False, "synthetic")


class IngestStoryTests(unittest.TestCase):
    def test_title_from_text_uses_first_words(self):
        ingest = load("ingest_story")
        self.assertEqual(
            ingest.title_from_text("redlands was where the story really started for me"),
            "Redlands Was Where The Story Really Started For",
        )

    def test_generate_candidates_uses_source_path(self):
        ingest = load("ingest_story")
        candidates = ingest.generate_candidates(
            "Redlands Memory",
            "This is a story about money, family, and growing up.",
            "sources/manual/2026-01-01-redlands-memory.md",
            "2026-01-01T00:00:00Z",
        )
        self.assertGreaterEqual(len(candidates), 4)
        self.assertTrue(all(c["source_path"].startswith("sources/manual/") for c in candidates))
        self.assertTrue(all(c["status"] == "candidate" for c in candidates))


class PlannerTests(unittest.TestCase):
    def test_qid_key_sorts_suffixes_after_base_number(self):
        planner = load("question_planner")
        self.assertLess(planner.qid_key("A14"), planner.qid_key("A14a"))

    def test_story_function_detects_scene_questions(self):
        planner = load("question_planner")
        self.assertEqual(
            planner.infer_story_function("Walk me through that day. What did the room look like?"),
            "scene",
        )

    def test_queue_stale_detection_uses_expiry(self):
        planner = load("question_planner")
        self.assertTrue(planner.queue_is_stale({
            "queue": [{"question_id": "A1"}],
            "expires_at": "2000-01-01T00:00:00Z",
        }))

    def test_default_planner_state_uses_delivery_queue_limit(self):
        planner = load("question_planner")
        state = planner.default_planner_state()

        self.assertEqual(state["queue"]["default_limit"], planner.DEFAULT_DELIVERY_QUEUE_LIMIT)
        self.assertEqual(planner.DEFAULT_DELIVERY_QUEUE_LIMIT, 8)


class CandidateManagerTests(unittest.TestCase):
    def test_promote_candidate_appends_next_question_and_preserves_provenance(self):
        candidates = load("question_candidates")
        bank = (
            "# Lifehug — Question Bank\n\n"
            "## A: Origins\n"
            "- [x] A1: Existing answered question *(2026-01-01)*\n"
            "- [ ] A2: Existing open question\n\n"
            "## B: Becoming\n"
            "- [ ] B1: Another question\n"
        )
        store = {
            "version": 1,
            "candidates": [{
                "id": "cand-redlands-1",
                "text": "What did the room look like when you realized things had changed?",
                "source_path": "sources/manual/redlands.md",
                "status": "accepted",
                "priority": 0.8,
            }],
        }
        updated, question_id = candidates.promote_candidate_record(store, bank, "cand-redlands-1", "A")
        self.assertEqual(question_id, "A3")
        self.assertIn("- [ ] A3: What did the room look like", updated)
        marker, _line, _text = candidates.candidate_promotion._marker_records(updated)[0]
        self.assertEqual(marker["candidate_id"], "cand-redlands-1")
        self.assertEqual(marker["category_id"], "A")
        self.assertEqual(marker["question_id"], "A3")
        self.assertEqual(store["candidates"][0]["status"], "promoted")
        self.assertEqual(store["candidates"][0]["promoted_question_id"], "A3")

    def test_promote_candidate_rejects_duplicate_question_text(self):
        candidates = load("question_candidates")
        bank = (
            "## A: Origins\n"
            "- [ ] A1: What did the room look like when you realized things had changed?\n"
        )
        store = {
            "version": 1,
            "candidates": [{
                "id": "cand-duplicate",
                "text": "What did the room look like when you realized things had changed?",
                "source_path": "sources/manual/redlands.md",
                "status": "candidate",
            }],
        }
        with self.assertRaises(ValueError):
            candidates.promote_candidate_record(store, bank, "cand-duplicate", "A")
        self.assertEqual(store["candidates"][0]["status"], "candidate")


SOURCE_PATH = "sources/manual/2026-08-12-farm-truck.md"
STORY_TEXT = "A story about my grandfather's old blue truck and the summer we fixed it together."


def _turn_json(message="Diesel and hay — thank you for that.", followup="What was the north field like?",
                candidate_ideas=None):
    return json.dumps({
        "message": message,
        "followup_question": followup,
        "question_free": followup is None,
        "rolling_summary": "The farm's smells; grandfather's hands.",
        "insight_receipts": 0,
        "extracted": {
            "facts": [], "entities": [],
            "candidate_ideas": candidate_ideas if candidate_ideas is not None else [],
            "mirror_responses": [],
        },
    })


class StoryConversationTurnCase(unittest.TestCase):
    """Shared synthetic-vault + injected-collaborator fixture (issue #117,
    Part A: story -> Conversation). Mirrors tests/test_conversation_delivery.py's
    EngineTestCase pattern exactly — synthetic data only, NEVER ~/Workspace/dave.
    """

    def setUp(self):
        self.tmp = root_parent_tmp(self, ROOT, prefix="lifehug-v155-story-")
        self.vault = self.tmp / "vault"
        self.vault.mkdir()
        self.state_path = self.tmp / "conversation_deliveries.json"
        self.candidates_path = self.tmp / "question_candidates.json"
        self.sent: list[str] = []
        self.prompts: list[str] = []
        diagnostics = mock.patch.object(engine, "record_learning_failure")
        self.diagnostic = diagnostics.start()
        self.addCleanup(diagnostics.stop)

    def _ai(self, response=None, error=None):
        def call(prompt, _model):
            self.prompts.append(prompt)
            if error is not None:
                raise error
            return response if response is not None else _turn_json()

        return call

    def _send(self, status="confirmed", reason="telegram_confirmed"):
        def send(message):
            self.sent.append(message)
            return core.TelegramSendResult(status, reason, 1 if status == "confirmed" else 0, 1)

        return send

    def run_turn(self, **overrides):
        kwargs = {
            "source_id": f"story:{SOURCE_PATH}",
            "source_path": SOURCE_PATH,
            "title": "Farm Truck",
            "story_text": STORY_TEXT,
            "source_type": "unprompted_story",
            "channel": "telegram",
            "state_path": self.state_path,
            "vault_root": self.vault,
            "status_resolver": ready_status,
            "ai_call": self._ai(),
            "telegram_send": self._send(),
        }
        kwargs.update(overrides)
        return engine.run_story_conversation_turn(**kwargs)

    def only_session(self):
        sessions = conversation.list_sessions(vault_root=self.vault)
        self.assertEqual(len(sessions), 1, sessions)
        return conversation.load_session(sessions[0]["session_id"], vault_root=self.vault)

    def file_templates(self, *, source_path=SOURCE_PATH):
        """Fire the same generate_candidates() step ingest_story.py always
        runs (contract: "generated at ingest time in BOTH cases"), against
        this test's own candidates_path — proves the story-turn and the
        template-candidate filing are independent, coexisting effects."""
        ingest = load("ingest_story")
        candidates = ingest.generate_candidates(
            "Farm Truck", STORY_TEXT, source_path, "2026-08-12T00:00:00Z",
        )
        self.candidates_path.write_text(
            json.dumps({"version": 1, "candidates": candidates}), encoding="utf-8"
        )
        return candidates


class StoryOpensAndContinuesTests(StoryConversationTurnCase):
    def test_story_opens_conversation_and_sends_turn(self):
        self.file_templates()

        outcome = self.run_turn()

        self.assertEqual((outcome.status, outcome.reason), ("confirmed", "telegram_confirmed"))
        self.assertEqual(len(self.sent), 1)
        session = self.only_session()
        self.assertEqual(session["mode"], "conversation")
        self.assertEqual(session["channel"], "telegram")
        roles = [t["role"] for t in session["turns"]]
        self.assertEqual(roles, ["user", "lifehug"])
        self.assertEqual(session["turns"][0]["source_path"], SOURCE_PATH)
        entries = json.loads(self.state_path.read_text())["entries"]
        entry = entries[engine.turn_key(session["session_id"], 1)]
        self.assertEqual((entry["status"], entry["reason"]), ("confirmed", "telegram_confirmed"))

        # Template candidates ALSO filed — the immediate-value floor either way.
        filed = json.loads(self.candidates_path.read_text())["candidates"]
        self.assertGreaterEqual(len(filed), 4)
        self.assertTrue(all(c["status"] == "candidate" for c in filed))

    def test_story_continues_open_session(self):
        first = self.run_turn()
        second = self.run_turn(
            story_text="More about the truck — we found an old radio under the seat.",
            ai_call=self._ai(response=_turn_json(message="A radio under the seat — what a find.",
                                                  followup=None)),
        )

        self.assertEqual([o.status for o in (first, second)], ["confirmed", "confirmed"])
        session = self.only_session()
        self.assertEqual(len(conversation.list_sessions(vault_root=self.vault)), 1)
        roles = [t["role"] for t in session["turns"]]
        self.assertEqual(roles, ["user", "lifehug", "user", "lifehug"])
        self.assertEqual(session["turns"][2]["text"],
                          "More about the truck — we found an old radio under the seat.")

    def test_keyless_provider_creates_no_session(self):
        # No-session fallback: a not-ready provider never touches the store.
        ai = mock.Mock(side_effect=AssertionError("keyless must never generate"))
        outcome = self.run_turn(status_resolver=keyless_status, ai_call=ai)
        self.assertEqual((outcome.status, outcome.reason), ("skipped", "no_unattended_provider"))
        self.assertEqual(conversation.list_sessions(vault_root=self.vault), [])
        ai.assert_not_called()

    def test_definitive_failure_while_opening_creates_no_session(self):
        # Generation succeeds structurally but the lint engine rejects it
        # (two questions in one turn) — a definitive failure while OPENING a
        # brand new session must leave no orphaned session behind.
        outcome = self.run_turn(ai_call=self._ai(response=_turn_json(
            message="Diesel and hay. What was the field like? And who baled it?"
        )))
        self.assertEqual((outcome.status, outcome.reason), ("failed", "malformed_generation"))
        self.assertEqual(self.sent, [])
        self.assertEqual(conversation.list_sessions(vault_root=self.vault), [])

    def test_definitive_failure_while_continuing_leaves_session_without_a_reply(self):
        first = self.run_turn()
        session_id = self.only_session()["session_id"]
        second = self.run_turn(
            story_text="One more thing about that truck.",
            ai_call=self._ai(response="not json at all"),
        )
        self.assertEqual(first.status, "confirmed")
        self.assertEqual((second.status, second.reason), ("failed", "malformed_generation"))
        session = conversation.load_session(session_id, vault_root=self.vault)
        roles = [t["role"] for t in session["turns"]]
        # The second story turn's TEXT landed (it's a real user turn); no
        # lifehug reply followed it because generation failed.
        self.assertEqual(roles, ["user", "lifehug", "user"])
        self.assertEqual(session["turns"][2]["text"], "One more thing about that truck.")


class WitnessAndOpinionTurnTests(StoryConversationTurnCase):
    def test_witness_and_opinion_take_turn_path(self):
        for source_type in ("witness_account", "opinion"):
            with self.subTest(source_type=source_type):
                self.setUp()
                outcome = self.run_turn(source_type=source_type)
                self.assertEqual(outcome.status, "confirmed")
                self.assertTrue(self.prompts)
                self.assertIn(source_type, self.prompts[-1])

    def test_witness_and_opinion_fallback_identical_to_story(self):
        for source_type in ("witness_account", "opinion"):
            with self.subTest(source_type=source_type):
                self.setUp()
                outcome = self.run_turn(source_type=source_type, status_resolver=keyless_status)
                self.assertEqual((outcome.status, outcome.reason),
                                 ("skipped", "no_unattended_provider"))
                self.assertEqual(conversation.list_sessions(vault_root=self.vault), [])


class CloseSupersedeTests(StoryConversationTurnCase):
    def _seed_template(self, *, status="candidate", source_path=SOURCE_PATH, cid="cand-farm-truck-1"):
        data = {"version": 1, "candidates": [{
            "id": cid,
            "text": "What did the truck mean to your grandfather?",
            "source_path": source_path,
            "status": status,
            "priority": 0.5,
            "created_at": "2026-08-12T00:00:00Z",
        }]}
        self.candidates_path.write_text(json.dumps(data), encoding="utf-8")

    def test_close_supersedes_template_candidates(self):
        self._seed_template()
        candidate_ideas = [{"text": "What did he machine in that barn?"}]
        self.run_turn(ai_call=self._ai(response=_turn_json(candidate_ideas=candidate_ideas)))
        session_id = self.only_session()["session_id"]

        engine.close_session_now(
            session_id,
            state_path=self.state_path,
            vault_root=self.vault,
            candidates_path=self.candidates_path,
            status_resolver=ready_status,
            ai_call=lambda _p, _m: json.dumps({"message": "Thank you for that whole story."}),
            telegram_send=self._send(),
            prompt_builder=lambda payload: "SYNTHETIC CLOSING PROMPT",
        )

        candidates = {c["id"]: c for c in json.loads(self.candidates_path.read_text())["candidates"]}
        self.assertEqual(candidates["cand-farm-truck-1"]["status"], "superseded")
        filed = [c for c in candidates.values() if c.get("provenance") == "conversation"]
        self.assertEqual(len(filed), 1)
        self.assertEqual(filed[0]["status"], "candidate")

    def test_already_promoted_template_is_untouched(self):
        self._seed_template(status="promoted")
        candidate_ideas = [{"text": "What did he machine in that barn?"}]
        self.run_turn(ai_call=self._ai(response=_turn_json(candidate_ideas=candidate_ideas)))
        session_id = self.only_session()["session_id"]

        engine.close_session_now(
            session_id,
            state_path=self.state_path,
            vault_root=self.vault,
            candidates_path=self.candidates_path,
            status_resolver=ready_status,
            ai_call=lambda _p, _m: json.dumps({"message": "Thank you for that whole story."}),
            telegram_send=self._send(),
            prompt_builder=lambda payload: "SYNTHETIC CLOSING PROMPT",
        )

        candidates = load("question_candidates")
        self.assertEqual(candidates.PROMOTABLE_STATUSES, {"candidate", "accepted", "deferred"})
        on_disk = {c["id"]: c for c in json.loads(self.candidates_path.read_text())["candidates"]}
        self.assertEqual(on_disk["cand-farm-truck-1"]["status"], "promoted")

    def test_close_without_extraction_keeps_templates_live(self):
        self._seed_template()
        self.run_turn(ai_call=self._ai(response=_turn_json(candidate_ideas=[])))
        session_id = self.only_session()["session_id"]

        engine.close_session_now(
            session_id,
            state_path=self.state_path,
            vault_root=self.vault,
            candidates_path=self.candidates_path,
            status_resolver=ready_status,
            ai_call=lambda _p, _m: json.dumps({"message": "Thank you for that whole story."}),
            telegram_send=self._send(),
            prompt_builder=lambda payload: "SYNTHETIC CLOSING PROMPT",
        )

        on_disk = {c["id"]: c for c in json.loads(self.candidates_path.read_text())["candidates"]}
        self.assertEqual(on_disk["cand-farm-truck-1"]["status"], "candidate")


class SupersededStatusTests(unittest.TestCase):
    def test_superseded_is_valid_but_never_promotable(self):
        candidates = load("question_candidates")
        self.assertIn("superseded", candidates.VALID_STATUSES)
        self.assertNotIn("superseded", candidates.PROMOTABLE_STATUSES)

    def test_promote_candidate_record_rejects_superseded(self):
        candidates = load("question_candidates")
        bank = "## A: Origins\n- [ ] A1: An existing question\n"
        store = {"version": 1, "candidates": [{
            "id": "cand-superseded-1",
            "text": "A superseded template question",
            "source_path": "sources/manual/x.md",
            "status": "superseded",
        }]}
        with self.assertRaises(ValueError):
            candidates.promote_candidate_record(store, bank, "cand-superseded-1", "A")


class IngestCliRegressionTests(unittest.TestCase):
    """Full-process regression pins for the keyless/dry-run seams — subprocess
    against a synthetic external vault (env LIFEHUG_VAULT_ROOT), same style
    as tests/test_v130_migration.py. A bare env (no API keys) guarantees the
    keyless path deterministically.
    """

    def setUp(self):
        self.tmp = root_parent_tmp(self, ROOT, prefix="lifehug-v155-ingest-cli-")

    def _make_vault(self) -> Path:
        vault = self.tmp / f"vault-{len(list(self.tmp.iterdir()))}"
        vault.mkdir(parents=True)
        (vault / "question-bank.md").write_text(
            "# Synthetic Lifehug questions\n\n## A: Origins\n"
            "- [ ] A1: What is your earliest synthetic memory?\n",
            encoding="utf-8",
        )
        rotation = {
            "version": 1, "current_pass": 1,
            "pass_names": ["skeleton", "depth", "connections", "polish"],
            "last_question_id": None, "last_asked_at": None, "questions_asked": 0,
            "questions_answered": 0, "next_question_id": None, "focus_frequency": 4,
        }
        coverage = {"version": 1, "last_updated": None,
                    "categories": {"A": {"total": 1, "answered": 0, "status": "red"}}}
        (vault / "state").mkdir(parents=True, exist_ok=True)
        (vault / "state" / "rotation.json").write_text(json.dumps(rotation), encoding="utf-8")
        (vault / "state" / "coverage.json").write_text(json.dumps(coverage), encoding="utf-8")
        return vault

    def _run_ingest(self, vault: Path, story: str, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(SYSTEM / "ingest_story.py"),
             "--source", "telegram", "--title", "Test Story", *args],
            input=story, capture_output=True, text=True, cwd=str(vault),
            env={"PATH": "/usr/bin:/bin", "HOME": str(vault), "LIFEHUG_VAULT_ROOT": str(vault)},
        )

    def test_keyless_ingest_is_byte_identical_to_today(self):
        vault = self._make_vault()
        result = self._run_ingest(vault, STORY_TEXT)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, "")
        lines = result.stdout.splitlines()
        self.assertRegex(
            lines[0], r"^✓ Ingested story: sources/manual/\d{4}-\d{2}-\d{2}-test-story\.md$"
        )
        self.assertTrue(lines[1].startswith("✓ Added candidates: "))
        self.assertEqual(len(lines), 2)  # no third "Conversation turn" line, keyless
        self.assertFalse((vault / "state" / "conversations").exists())

    def test_dry_run_makes_no_calls_and_no_session(self):
        vault = self._make_vault()
        before = sorted(p.relative_to(vault).as_posix() for p in vault.rglob("*") if p.is_file())
        result = self._run_ingest(vault, STORY_TEXT, "--dry-run")
        self.assertEqual(result.returncode, 0, result.stderr)
        lines = result.stdout.splitlines()
        self.assertRegex(
            lines[0], r"^would write sources/manual/\d{4}-\d{2}-\d{2}-test-story\.md$"
        )
        self.assertEqual(lines[1], "would add 4 question candidate(s)")
        self.assertEqual(len(lines), 2)
        after = sorted(p.relative_to(vault).as_posix() for p in vault.rglob("*") if p.is_file())
        self.assertEqual(before, after)  # nothing written at all, including no session
        self.assertFalse((vault / "state" / "conversations").exists())


if __name__ == "__main__":
    unittest.main()
