"""v184 / ADR 0021 — independent Focus Candidate runtime."""

from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SYSTEM = ROOT / "system"
sys.path.insert(0, str(SYSTEM))

import candidate_research as research  # noqa: E402
import focus_candidate as focus  # noqa: E402
import lifehug  # noqa: E402


class MemoryAuthority:
    def __init__(self):
        self.source: bytes | None = None
        self.commit = "a" * 40
        self.calls = 0

    def resolve_exact_source(
        self,
        plan,
        *,
        vault_root=None,
        push=True,
        failpoint=None,
        revalidate_current_subject,
    ):
        del vault_root, push, failpoint
        self.calls += 1
        revalidate_current_subject()
        changed = self.source is None
        if self.source is not None and self.source != plan["source_bytes"]:
            raise research.CandidateResearchConflict("conflicting source")
        self.source = plan["source_bytes"]
        return {
            "source_path": plan["source_path"],
            "changed": changed,
            "commit_sha": self.commit,
        }


class FocusCandidateTests(unittest.TestCase):
    def recommendation(self, status="pending"):
        return {
            "id": "rec-synthetic-harbor",
            "entity": "Synthetic Harbor",
            "type": "place",
            "status": status,
        }

    def subject(self):
        return research.build_focus_candidate_subject(self.recommendation())

    def turns(self, confirmed=False):
        rows = [
            (
                "t1",
                "My grandmother taught me to wait for the tide at Synthetic Harbor.",
            ),
            (
                "t2",
                "After the winter storm I returned alone and found the old "
                "pier broken.",
            ),
            (
                "t3",
                "Now it connects patience and grief with what I want to pass "
                "to my children.",
            ),
        ]
        if confirmed:
            rows.append(("t4", "Yes, preserve this exact research."))
        return [research.build_authoritative_user_turn(*row) for row in rows]

    def payload(self, *, turns=None, assessment=None, latest="t3", previous=None):
        turns = turns or self.turns()
        return focus.build_focus_candidate_input(
            candidate_id="rec-synthetic-harbor",
            authoritative_turns=turns,
            assessment=assessment,
            latest_turn_id=latest,
            previous_question=previous,
            current_subject=self.subject(),
        )

    def ready_proposal(self):
        turns = self.turns()
        return {
            "reply": "That links the harbor to what you want to carry forward.",
            "action": "continue",
            "next_gap": None,
            "evidence_spans": [
                {
                    "turn_id": turn["turn_id"],
                    "start": 0,
                    "end": len(turn["text"]),
                    "evidence_kind": kind,
                }
                for turn, kind in zip(
                    turns,
                    ("statement", "concrete_event", "concrete_observation"),
                    strict=True,
                )
            ],
            "dimension_evidence": {
                "focus_identity": [0],
                "why_it_matters": [0],
                "scope_boundary": [1],
                "present_state_direction": [2],
                "relationships": [0, 2],
                "grounded_evidence": [1],
                "tensions": [1],
                "open_questions": [2],
            },
            "seed_questions": [
                "How did waiting at the harbor shape your patience?",
                "What do you hope your children carry from that place?",
            ],
            "confirmation_span": None,
        }

    def ready_decision(self):
        return focus.parse_focus_candidate_output(
            self.ready_proposal(),
            payload=self.payload(),
            current_subject=self.subject(),
        )

    def test_loader_resolves_one_active_candidate_and_rejects_lifecycle_or_duplicates(
        self,
    ):
        with tempfile.TemporaryDirectory(dir=ROOT.parent) as tmp:
            state = Path(tmp) / "state"
            state.mkdir()
            path = state / "focus_recommendations.json"
            path.write_text(
                json.dumps(
                    {
                        "version": 1,
                        "recommendations": [self.recommendation()],
                        "dismissed": [],
                    }
                )
            )
            self.assertEqual(
                focus.load_focus_candidate_subject(
                    "rec-synthetic-harbor", vault_root=tmp
                ),
                self.subject(),
            )
            for value in (
                {
                    "version": 1,
                    "recommendations": [],
                    "dismissed": [self.recommendation("dismissed")],
                },
                {
                    "version": 1,
                    "recommendations": [self.recommendation(), self.recommendation()],
                    "dismissed": [],
                },
            ):
                with self.subTest(value=value):
                    path.write_text(json.dumps(value))
                    with self.assertRaises(focus.FocusCandidateError):
                        focus.load_focus_candidate_subject(
                            "rec-synthetic-harbor", vault_root=tmp
                        )

            # Collection membership is lifecycle authority; a tombstoned row
            # cannot be made active by a forged payload status.
            path.write_text(
                json.dumps(
                    {
                        "version": 1,
                        "recommendations": [],
                        "dismissed": [self.recommendation("pending")],
                    }
                )
            )
            with self.assertRaisesRegex(
                focus.FocusCandidateError, "collection/status contradiction"
            ):
                focus.load_focus_candidate_subject(
                    "rec-synthetic-harbor", vault_root=tmp
                )

    def test_prompt_exact_composes_and_treats_candidate_as_untrusted(self):
        prompt = focus.build_focus_candidate_prompt(
            self.payload(), current_subject=self.subject()
        )
        self.assertLess(
            prompt.index("interaction:conversation"),
            prompt.index("interaction:focus_candidate"),
        )
        self.assertIn("runtime-boundary:untrusted-data", prompt)
        self.assertIn("rec-synthetic-harbor", prompt)
        self.assertNotIn("interaction:question_candidate", prompt)

    def test_preexisting_interaction_assets_remain_byte_identical(self):
        expected = {
            "conversation": (
                "107a26a9255eb86784f088dbb081184416da0a3edc12216cdd7ca6c62ff00ffd"
            ),
            "question_candidate": (
                # issue #181 (v188): question-candidate-placement-aside
                # intentionally changes this package's prompt/README/lint
                # files — this digest tracks that content, not a freeze.
                "deb584b26a443c8c5346d6effda4b8459ce3fff9d174d70a29add72d958e8aee"
            ),
        }
        for package, digest in expected.items():
            hasher = hashlib.sha256()
            root = ROOT / "interactions" / package
            for path in sorted(root.rglob("*")):
                if path.is_file():
                    hasher.update(path.relative_to(root).as_posix().encode())
                    hasher.update(b"\0")
                    hasher.update(path.read_bytes())
                    hasher.update(b"\0")
            self.assertEqual(hasher.hexdigest(), digest)
        # v185 adds Entity Candidate independently; this guard protects the
        # existing package digests above rather than forbidding new siblings.
        self.assertTrue((ROOT / "interactions/entity_candidate").exists())
        self.assertTrue((SYSTEM / "entity_candidate.py").exists())

    def test_eight_dimension_mapping_yields_v183_ready_assessment(self):
        decision = self.ready_decision()
        self.assertEqual(decision["status"], "continue")
        self.assertTrue(decision["ready"])
        self.assertFalse(decision["complete"])
        self.assertEqual(
            tuple(focus.FOCUS_TO_RESEARCH_DIMENSION.values()), research.FOCUS_DIMENSIONS
        )
        self.assertNotIn(
            "grounded_evidence", decision["assessment"]["dimension_evidence"]
        )
        self.assertGreaterEqual(
            decision["assessment"]["readiness"]["concrete_evidence_count"], 1
        )

    def test_grounded_gate_rejects_nonconcrete_and_exact_span_forgery(self):
        proposal = self.ready_proposal()
        proposal["evidence_spans"][1]["evidence_kind"] = "statement"
        self.assertEqual(
            focus.parse_focus_candidate_output(
                proposal, payload=self.payload(), current_subject=self.subject()
            )["status"],
            "invalid",
        )
        proposal = self.ready_proposal()
        proposal["evidence_spans"][0]["end"] += 1000
        self.assertEqual(
            focus.parse_focus_candidate_output(
                proposal, payload=self.payload(), current_subject=self.subject()
            )["status"],
            "invalid",
        )

    def test_all_actions_pass_inherited_lints_and_one_question_contract(self):
        ready = self.ready_decision()["assessment"]
        cases = [
            (
                {**self.ready_proposal(), "reply": "Was it family? Or was it work?"},
                self.payload(),
            ),
            (
                {
                    "reply": "Is this right? Or should it change?",
                    "action": "offer_confirmation",
                    "next_gap": None,
                    "evidence_spans": [],
                    "dimension_evidence": {name: [] for name in focus.FOCUS_DIMENSIONS},
                    "seed_questions": [],
                    "confirmation_span": None,
                },
                self.payload(assessment=ready),
            ),
            (
                {
                    "reply": "What year did that happen?",
                    "action": "ask_gap",
                    "next_gap": "tensions",
                    "evidence_spans": [],
                    "dimension_evidence": {name: [] for name in focus.FOCUS_DIMENSIONS},
                    "seed_questions": [],
                    "confirmation_span": None,
                },
                self.payload(),
            ),
        ]
        for proposal, payload in cases:
            with self.subTest(action=proposal["action"]):
                self.assertEqual(
                    focus.parse_focus_candidate_output(
                        proposal, payload=payload, current_subject=self.subject()
                    )["status"],
                    "invalid",
                )

    def test_confirmation_is_distinct_and_completion_delegates_without_approval(self):
        ready = self.ready_decision()["assessment"]
        turns = self.turns(confirmed=True)
        payload = self.payload(turns=turns, assessment=ready, latest="t4")
        proposal = {
            "reply": "I will hold those exact words as candidate research.",
            "action": "accept_confirmation",
            "next_gap": None,
            "evidence_spans": [],
            "dimension_evidence": {name: [] for name in focus.FOCUS_DIMENSIONS},
            "seed_questions": [],
            "confirmation_span": {
                "turn_id": "t4",
                "start": 0,
                "end": len(turns[-1]["text"]),
            },
        }
        decision = focus.parse_focus_candidate_output(
            proposal,
            payload=payload,
            current_subject=self.subject(),
            confirmed_at="2026-08-18T20:00:00Z",
        )
        self.assertEqual(decision["status"], "complete")
        self.assertTrue(decision["complete"])
        self.assertEqual(
            focus.validate_focus_candidate_decision(
                decision, payload=payload, current_subject=self.subject()
            ),
            decision,
        )
        authority = MemoryAuthority()
        loader = self.subject
        first = focus.resolve_focus_candidate_completion(
            decision["assessment"],
            authoritative_turns=turns,
            candidate_id="rec-synthetic-harbor",
            current_subject_loader=loader,
            authority=authority,
            vault_root="/synthetic",
        )
        second = focus.resolve_focus_candidate_completion(
            decision["assessment"],
            authoritative_turns=turns,
            candidate_id="rec-synthetic-harbor",
            current_subject_loader=loader,
            authority=authority,
            vault_root="/synthetic",
        )
        self.assertTrue(first["changed"])
        self.assertFalse(second["changed"])
        self.assertEqual(first["commit_sha"], second["commit_sha"])

    def test_negative_confirmation_and_model_authority_claim_fail_closed(self):
        ready = self.ready_decision()["assessment"]
        turns = self.turns() + [
            research.build_authoritative_user_turn(
                "t4", "No, do not preserve this research."
            )
        ]
        payload = self.payload(turns=turns, assessment=ready, latest="t4")
        base = {
            "reply": "I committed the new Focus.",
            "action": "accept_confirmation",
            "next_gap": None,
            "evidence_spans": [],
            "dimension_evidence": {name: [] for name in focus.FOCUS_DIMENSIONS},
            "seed_questions": [],
            "confirmation_span": {
                "turn_id": "t4",
                "start": 0,
                "end": len(turns[-1]["text"]),
            },
        }
        self.assertEqual(
            focus.parse_focus_candidate_output(
                base,
                payload=payload,
                current_subject=self.subject(),
                confirmed_at="2026-08-18T20:00:00Z",
            )["status"],
            "invalid",
        )
        base["reply"] = "I understand that you do not want this preserved."
        self.assertEqual(
            focus.parse_focus_candidate_output(
                base,
                payload=payload,
                current_subject=self.subject(),
                confirmed_at="2026-08-18T20:00:00Z",
            )["status"],
            "invalid",
        )

    def test_qualified_confirmation_and_indirect_authority_claims_fail_closed(self):
        ready = self.ready_decision()["assessment"]
        for confirmation in (
            "Yes, but do not preserve this research.",
            "I confirm not to preserve.",
        ):
            with self.subTest(confirmation=confirmation):
                turns = self.turns() + [
                    research.build_authoritative_user_turn("t4", confirmation)
                ]
                decision = focus.parse_focus_candidate_output(
                    {
                        "reply": "I will keep this available for your review.",
                        "action": "accept_confirmation",
                        "next_gap": None,
                        "evidence_spans": [],
                        "dimension_evidence": {
                            name: [] for name in focus.FOCUS_DIMENSIONS
                        },
                        "seed_questions": [],
                        "confirmation_span": {
                            "turn_id": "t4",
                            "start": 0,
                            "end": len(confirmation),
                        },
                    },
                    payload=self.payload(turns=turns, assessment=ready, latest="t4"),
                    current_subject=self.subject(),
                    confirmed_at="2026-08-18T20:00:00Z",
                )
                self.assertEqual(decision["status"], "invalid")

        base = self.ready_proposal()
        for reply in (
            "The Focus was created.",
            "I have approved this recommendation.",
            "Your research has been saved.",
            "A commit was pushed.",
            "The next focus_identity is relationships.",
        ):
            with self.subTest(reply=reply):
                self.assertEqual(
                    focus.parse_focus_candidate_output(
                        {**base, "reply": reply},
                        payload=self.payload(),
                        current_subject=self.subject(),
                    )["status"],
                    "invalid",
                )

    def test_confirmation_cannot_create_readiness_in_the_same_turn(self):
        turns = self.turns(confirmed=True)
        proposal = self.ready_proposal()
        proposal.update(
            {
                "reply": "Those exact excerpts are ready for candidate research.",
                "action": "accept_confirmation",
                "confirmation_span": {
                    "turn_id": "t4",
                    "start": 0,
                    "end": len(turns[-1]["text"]),
                },
            }
        )
        self.assertEqual(
            focus.parse_focus_candidate_output(
                proposal,
                payload=self.payload(turns=turns, latest="t4"),
                current_subject=self.subject(),
                confirmed_at="2026-08-18T20:00:00Z",
            )["status"],
            "invalid",
        )

    def test_completion_rejects_concurrent_candidate_consumption(self):
        ready = self.ready_decision()["assessment"]
        turns = self.turns(confirmed=True)
        payload = self.payload(turns=turns, assessment=ready, latest="t4")
        proposal = {
            "reply": "Those exact excerpts are ready for candidate research.",
            "action": "accept_confirmation",
            "next_gap": None,
            "evidence_spans": [],
            "dimension_evidence": {name: [] for name in focus.FOCUS_DIMENSIONS},
            "seed_questions": [],
            "confirmation_span": {
                "turn_id": "t4",
                "start": 0,
                "end": len(turns[-1]["text"]),
            },
        }
        completed = focus.parse_focus_candidate_output(
            proposal,
            payload=payload,
            current_subject=self.subject(),
            confirmed_at="2026-08-18T20:00:00Z",
        )["assessment"]
        consumed = research.build_focus_candidate_subject(
            self.recommendation(status="approved")
        )
        calls = 0

        def changing_loader():
            nonlocal calls
            calls += 1
            return self.subject() if calls < 3 else consumed

        with self.assertRaises(focus.FocusCandidateError):
            focus.resolve_focus_candidate_completion(
                completed,
                authoritative_turns=turns,
                candidate_id="rec-synthetic-harbor",
                current_subject_loader=changing_loader,
                authority=MemoryAuthority(),
                vault_root="/synthetic",
            )

    def test_stale_subject_and_forged_decision_fail_closed(self):
        payload = self.payload()
        stale = research.build_focus_candidate_subject(
            {**self.recommendation(), "entity": "Other Harbor"}
        )
        with self.assertRaises(focus.FocusCandidateError):
            focus.validate_focus_candidate_input(payload, current_subject=stale)
        decision = self.ready_decision()
        decision["ready"] = False
        with self.assertRaises(focus.FocusCandidateError):
            focus.validate_focus_candidate_decision(
                decision, payload=payload, current_subject=self.subject()
            )

        decision = self.ready_decision()
        decision.update(
            {
                "status": "complete",
                "action": "accept_confirmation",
                "assessment": None,
                "ready": True,
                "complete": True,
            }
        )
        source = {
            key: value for key, value in decision.items() if key != "decision_revision"
        }
        decision["decision_revision"] = research.canonical_revision(source)
        with self.assertRaises(focus.FocusCandidateError):
            focus.validate_focus_candidate_decision(
                decision, payload=payload, current_subject=self.subject()
            )

        for field, forged in (("ready", 1), ("complete", 0)):
            with self.subTest(field=field):
                decision = self.ready_decision()
                decision[field] = forged
                source = {
                    key: value
                    for key, value in decision.items()
                    if key != "decision_revision"
                }
                decision["decision_revision"] = research.canonical_revision(source)
                with self.assertRaises(focus.FocusCandidateError):
                    focus.validate_focus_candidate_decision(
                        decision, payload=payload, current_subject=self.subject()
                    )
        decision = self.ready_decision()
        decision["status"] = "complete"
        source = {
            key: value for key, value in decision.items() if key != "decision_revision"
        }
        decision["decision_revision"] = research.canonical_revision(source)
        with self.assertRaises(focus.FocusCandidateError):
            focus.validate_focus_candidate_decision(
                decision, payload=payload, current_subject=self.subject()
            )

    def test_cli_command_classification_and_framework_manifest(self):
        self.assertIn("focus-candidate-prompt", lifehug.READ_ONLY_COMMANDS)
        self.assertIn("focus-candidate-evals", lifehug.READ_ONLY_COMMANDS)
        self.assertIn("focus-candidate-complete", lifehug.DIRECT_MUTATION_COMMANDS)
        shipped = {
            path.relative_to(ROOT).as_posix()
            for path in (ROOT / "interactions/focus_candidate").rglob("*")
            if path.is_file()
        } | {
            "system/focus_candidate.py",
            "system/focus_candidate_evals.py",
            "tests/walkthrough_focus_candidate.py",
        }
        version = json.loads((ROOT / "system/version.json").read_text())
        self.assertEqual(shipped - set(version["framework_files"]), set())
        # >= not == (issue #181/v188 propagation): an exact pin here breaks
        # on every subsequent version bump, unlike test_decisions_feed_loop.py
        # / test_question_judgment.py's correct assertGreaterEqual pattern.
        self.assertGreaterEqual(version["version"], 187)

    def test_runtime_has_one_completion_delegation_and_no_parallel_writer_or_approval(
        self,
    ):
        source = (SYSTEM / "focus_candidate.py").read_text()
        self.assertEqual(
            source.count("candidate_research.resolve_candidate_research_source("), 1
        )
        for forbidden in (
            "approve_recommendation",
            "focus_new(",
            "exact_file_git",
            ".write_text(",
            ".write_bytes(",
            "subprocess",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main()
