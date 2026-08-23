"""v185 / ADR 0022 — independent Entity Candidate runtime."""

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
import entity_candidate as focus  # noqa: E402
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


class EntityCandidateTests(unittest.TestCase):
    def recommendation(self, status="pending"):
        del status
        return {
            "name": "Synthetic Harbor",
            "slug": "synthetic-harbor",
            "aliases": [],
            "page_eligible": False,
            "maps_to_focus": None,
            "owner_verdict": None,
        }

    def subject(self):
        return research.build_entity_candidate_subject("place", self.recommendation())

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
        return focus.build_entity_candidate_input(
            candidate_id="entity:place:synthetic-harbor",
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
                "identity_disambiguation": [0],
                "relationship_relevance_and_significance": [0],
                "timeline_context": [1],
                "connections": [2],
                "tension_or_open_question": [1],
                "type_specific_context": [1],
                "grounded_evidence": [1],
            },
            "seed_questions": [
                "How did waiting at the harbor shape your patience?",
                "What do you hope your children carry from that place?",
            ],
            "confirmation_span": None,
        }

    def ready_decision(self):
        return focus.parse_entity_candidate_output(
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
            rosters = state / "entity_rosters"
            rosters.mkdir()
            path = rosters / "place.json"
            path.write_text(
                json.dumps(
                    {
                        "version": 1,
                        "entities": [self.recommendation()],
                    }
                )
            )
            self.assertEqual(
                focus.load_entity_candidate_subject(
                    "entity:place:synthetic-harbor", vault_root=tmp
                ),
                self.subject(),
            )
            for value in (
                {
                    "version": 1,
                    "entities": [],
                },
                {
                    "version": 1,
                    "entities": [self.recommendation(), self.recommendation()],
                },
            ):
                with self.subTest(value=value):
                    path.write_text(json.dumps(value))
                    with self.assertRaises(focus.EntityCandidateError):
                        focus.load_entity_candidate_subject(
                            "entity:place:synthetic-harbor", vault_root=tmp
                        )

            # Collection membership is lifecycle authority; a tombstoned row
            # cannot be made active by a forged payload status.
            path.write_text(
                json.dumps(
                    {
                        "version": 1,
                        "entities": [],
                    }
                )
            )
            with self.assertRaisesRegex(
                focus.EntityCandidateError, "resolve exactly once"
            ):
                focus.load_entity_candidate_subject(
                    "entity:place:synthetic-harbor", vault_root=tmp
                )

    def test_prompt_exact_composes_and_treats_candidate_as_untrusted(self):
        prompt = focus.build_entity_candidate_prompt(
            self.payload(), current_subject=self.subject()
        )
        self.assertLess(
            prompt.index("interaction:conversation"),
            prompt.index("interaction:entity_candidate"),
        )
        self.assertIn("runtime-boundary:untrusted-data", prompt)
        self.assertIn("entity:place:synthetic-harbor", prompt)
        self.assertNotIn("interaction:question_candidate", prompt)

    def test_preexisting_interaction_assets_remain_byte_identical(self):
        expected = {
            "conversation": (
                # v196: prompt/turn-instructions.md carries the whisper direction.
                "9e201849154a49d698aabc48cd856f5358a0f9e3e31bea85ad0690075b4b1970"
            ),
            "question_candidate": (
                # issue #181 (v188): question-candidate-placement-aside
                # intentionally changes this package's prompt/README/lint
                # files — this digest tracks that content, not a freeze.
                # v192 (docs pass): README.md gained the Platform-twin
                # surface table; no prompt, eval, or manifest byte moved.
                "f549af401b4765166cc8d3618439d2b367ab799f16f43f3a1a3c5dae764786f5"
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
        self.assertTrue((ROOT / "interactions/entity_candidate").exists())
        self.assertTrue((SYSTEM / "entity_candidate.py").exists())

    def test_seven_dimension_mapping_yields_v183_ready_assessment(self):
        decision = self.ready_decision()
        self.assertEqual(decision["status"], "continue")
        self.assertTrue(decision["ready"])
        self.assertFalse(decision["complete"])
        self.assertEqual(
            tuple(focus.ENTITY_TO_RESEARCH_DIMENSION.values()),
            research.ENTITY_DIMENSIONS,
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
            focus.parse_entity_candidate_output(
                proposal, payload=self.payload(), current_subject=self.subject()
            )["status"],
            "invalid",
        )

    @staticmethod
    def _type_assessment(entity_type: str, type_context: list[str], *, confirmed=False):
        entry = {
            "name": f"Synthetic {entity_type.title()}",
            "slug": f"synthetic-{entity_type}",
            "aliases": [],
            "page_eligible": False,
            "maps_to_focus": None,
            "owner_verdict": None,
        }
        subject = research.build_entity_candidate_subject(entity_type, entry)
        texts = [
            *type_context,
            "During the storm, I saw the broken pier and carried that memory home.",
            "It connects this part of my story to a question I still hold.",
        ]
        if confirmed:
            texts.append("Yes, preserve these exact excerpts.")
        turns = [
            research.build_authoritative_user_turn(f"t{index}", text)
            for index, text in enumerate(texts, start=1)
        ]
        evidence_count = max(research.ENTITY_MIN_EVIDENCE_SPANS[entity_type], 3)
        evidence = [
            research.extract_research_evidence_span(
                turn,
                0,
                len(turn["text"]),
                "concrete_event" if index == len(type_context) else "statement",
            )
            for index, turn in enumerate(turns[:evidence_count])
        ]
        refs = [span["evidence_revision"] for span in evidence]
        dimensions = {
            name: [refs[index % len(refs)]]
            for index, name in enumerate(research.ENTITY_DIMENSIONS)
        }
        dimensions["type_specific_context"] = refs[: len(type_context)]
        assessment = research.build_research_assessment(
            subject=subject,
            evidence=evidence,
            dimension_evidence=dimensions,
            seed_questions=[],
            authoritative_turns=turns,
        )
        if confirmed:
            assessment = research.confirm_research_assessment(
                assessment,
                turn=turns[-1],
                start=0,
                end=len(turns[-1]["text"]),
                confirmed_at="2026-08-18T20:00:00Z",
                authoritative_turns=turns,
                current_subject=subject,
            )
        return subject, turns, assessment

    def test_type_specific_semantic_rubrics_reject_plausible_near_misses(self):
        cases = {
            "person": (
                [
                    "My aunt Marisol taught me to fix radios, and her patient voice changed how I listen."
                ],
                ["My aunt Marisol is important to me."],
            ),
            "place": (
                [
                    "The salt harbor and its broken pier were where I returned to wait for the tide."
                ],
                ["Synthetic Harbor is important in my story."],
            ),
            "period": (
                [
                    "During college, most mornings I studied before work; after graduation that routine ended."
                ],
                ["College was an important time in my life."],
            ),
            "object": (
                [
                    "My grandmother gave me the brass compass; I carried it because it reminds me of her promise."
                ],
                ["I kept the brass compass in a drawer."],
            ),
            "theme": (
                [
                    "At school, I kept starting over after mistakes.",
                    "Later at work, starting over changed from shame into confidence.",
                ],
                [
                    "At school I felt resilient whenever my plans fell apart.",
                    "At work I felt resilient whenever a project went wrong.",
                ],
            ),
        }
        for entity_type, (positive, negative) in cases.items():
            with self.subTest(entity_type=entity_type, result="positive"):
                subject, _turns, assessment = self._type_assessment(
                    entity_type, positive
                )
                self.assertTrue(assessment["readiness"]["ready"])
                self.assertTrue(
                    focus.type_specific_context_passes(assessment, subject=subject)
                )
            with self.subTest(entity_type=entity_type, result="near-miss"):
                subject, _turns, assessment = self._type_assessment(
                    entity_type, negative
                )
                self.assertTrue(assessment["readiness"]["ready"])
                self.assertFalse(
                    focus.type_specific_context_passes(assessment, subject=subject)
                )

    def test_direct_completion_cannot_bypass_entity_readiness_or_confirmation(self):
        subject, turns, structural_only = self._type_assessment(
            "theme",
            [
                "At school I felt resilient whenever my plans fell apart.",
                "At work I felt resilient whenever a project went wrong.",
            ],
            confirmed=True,
        )
        authority = MemoryAuthority()
        with self.assertRaisesRegex(
            focus.EntityCandidateError, "recomputed Entity readiness"
        ):
            focus.resolve_entity_candidate_completion(
                structural_only,
                authoritative_turns=turns,
                candidate_id=subject["candidate_id"],
                current_subject_loader=lambda: subject,
                authority=authority,
                vault_root="/synthetic",
            )
        self.assertEqual(authority.calls, 0)

        subject, turns, completed = self._type_assessment(
            "person",
            [
                "My aunt Marisol taught me to fix radios, and her patient voice changed how I listen."
            ],
            confirmed=True,
        )
        turns.append(
            research.build_authoritative_user_turn(
                "t-final", "One more detail came to mind."
            )
        )
        with self.assertRaisesRegex(focus.EntityCandidateError, "not current"):
            focus.resolve_entity_candidate_completion(
                completed,
                authoritative_turns=turns,
                candidate_id=subject["candidate_id"],
                current_subject_loader=lambda: subject,
                authority=MemoryAuthority(),
                vault_root="/synthetic",
            )

    def test_authority_guard_catches_durability_variants_without_blocking_an_offer(
        self,
    ):
        for reply in (
            "I preserved those excerpts.",
            "We recorded the research.",
            "Your excerpts were stored.",
            "The candidate research has been preserved.",
        ):
            with self.subTest(reply=reply):
                self.assertTrue(
                    any(
                        finding["lint"] == "entity_candidate_authority_claim"
                        for finding in focus.lint_entity_candidate_reply(reply)
                    )
                )
        offer_findings = focus.lint_entity_candidate_reply(
            "Would you like me to preserve these exact excerpts?", seam_ok=True
        )
        self.assertFalse(
            any(
                finding["lint"] == "entity_candidate_authority_claim"
                for finding in offer_findings
            )
        )
        proposal = self.ready_proposal()
        proposal["evidence_spans"][0]["end"] += 1000
        self.assertEqual(
            focus.parse_entity_candidate_output(
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
                    "dimension_evidence": {
                        name: [] for name in focus.ENTITY_DIMENSIONS
                    },
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
                    "dimension_evidence": {
                        name: [] for name in focus.ENTITY_DIMENSIONS
                    },
                    "seed_questions": [],
                    "confirmation_span": None,
                },
                self.payload(),
            ),
        ]
        for proposal, payload in cases:
            with self.subTest(action=proposal["action"]):
                self.assertEqual(
                    focus.parse_entity_candidate_output(
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
            "dimension_evidence": {name: [] for name in focus.ENTITY_DIMENSIONS},
            "seed_questions": [],
            "confirmation_span": {
                "turn_id": "t4",
                "start": 0,
                "end": len(turns[-1]["text"]),
            },
        }
        decision = focus.parse_entity_candidate_output(
            proposal,
            payload=payload,
            current_subject=self.subject(),
            confirmed_at="2026-08-18T20:00:00Z",
        )
        self.assertEqual(decision["status"], "complete")
        self.assertTrue(decision["complete"])
        self.assertEqual(
            focus.validate_entity_candidate_decision(
                decision, payload=payload, current_subject=self.subject()
            ),
            decision,
        )
        authority = MemoryAuthority()
        loader = self.subject
        first = focus.resolve_entity_candidate_completion(
            decision["assessment"],
            authoritative_turns=turns,
            candidate_id="entity:place:synthetic-harbor",
            current_subject_loader=loader,
            authority=authority,
            vault_root="/synthetic",
        )
        second = focus.resolve_entity_candidate_completion(
            decision["assessment"],
            authoritative_turns=turns,
            candidate_id="entity:place:synthetic-harbor",
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
            "dimension_evidence": {name: [] for name in focus.ENTITY_DIMENSIONS},
            "seed_questions": [],
            "confirmation_span": {
                "turn_id": "t4",
                "start": 0,
                "end": len(turns[-1]["text"]),
            },
        }
        self.assertEqual(
            focus.parse_entity_candidate_output(
                base,
                payload=payload,
                current_subject=self.subject(),
                confirmed_at="2026-08-18T20:00:00Z",
            )["status"],
            "invalid",
        )
        base["reply"] = "I understand that you do not want this preserved."
        self.assertEqual(
            focus.parse_entity_candidate_output(
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
                decision = focus.parse_entity_candidate_output(
                    {
                        "reply": "I will keep this available for your review.",
                        "action": "accept_confirmation",
                        "next_gap": None,
                        "evidence_spans": [],
                        "dimension_evidence": {
                            name: [] for name in focus.ENTITY_DIMENSIONS
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
            "The entity page was created.",
            "I have approved this recommendation.",
            "Your research has been saved.",
            "I preserved your excerpts.",
            "Your research was recorded.",
            "The source is stored.",
            "A commit was pushed.",
            "The next identity_disambiguation is unclear.",
        ):
            with self.subTest(reply=reply):
                self.assertEqual(
                    focus.parse_entity_candidate_output(
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
            focus.parse_entity_candidate_output(
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
            "dimension_evidence": {name: [] for name in focus.ENTITY_DIMENSIONS},
            "seed_questions": [],
            "confirmation_span": {
                "turn_id": "t4",
                "start": 0,
                "end": len(turns[-1]["text"]),
            },
        }
        completed = focus.parse_entity_candidate_output(
            proposal,
            payload=payload,
            current_subject=self.subject(),
            confirmed_at="2026-08-18T20:00:00Z",
        )["assessment"]
        consumed = research.build_entity_candidate_subject(
            "place", {**self.recommendation(), "page_eligible": True}
        )
        calls = 0

        def changing_loader():
            nonlocal calls
            calls += 1
            return self.subject() if calls < 3 else consumed

        with self.assertRaises(focus.EntityCandidateError):
            focus.resolve_entity_candidate_completion(
                completed,
                authoritative_turns=turns,
                candidate_id="entity:place:synthetic-harbor",
                current_subject_loader=changing_loader,
                authority=MemoryAuthority(),
                vault_root="/synthetic",
            )

    def test_stale_subject_and_forged_decision_fail_closed(self):
        payload = self.payload()
        stale = research.build_entity_candidate_subject(
            "place",
            {**self.recommendation(), "name": "Other Harbor", "slug": "other-harbor"},
        )
        with self.assertRaises(focus.EntityCandidateError):
            focus.validate_entity_candidate_input(payload, current_subject=stale)
        decision = self.ready_decision()
        decision["ready"] = False
        with self.assertRaises(focus.EntityCandidateError):
            focus.validate_entity_candidate_decision(
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
        with self.assertRaises(focus.EntityCandidateError):
            focus.validate_entity_candidate_decision(
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
                with self.assertRaises(focus.EntityCandidateError):
                    focus.validate_entity_candidate_decision(
                        decision, payload=payload, current_subject=self.subject()
                    )
        decision = self.ready_decision()
        decision["status"] = "complete"
        source = {
            key: value for key, value in decision.items() if key != "decision_revision"
        }
        decision["decision_revision"] = research.canonical_revision(source)
        with self.assertRaises(focus.EntityCandidateError):
            focus.validate_entity_candidate_decision(
                decision, payload=payload, current_subject=self.subject()
            )

    def test_cli_command_classification_and_framework_manifest(self):
        self.assertIn("entity-candidate-prompt", lifehug.READ_ONLY_COMMANDS)
        self.assertIn("entity-candidate-evals", lifehug.READ_ONLY_COMMANDS)
        self.assertIn("entity-candidate-complete", lifehug.DIRECT_MUTATION_COMMANDS)
        shipped = {
            path.relative_to(ROOT).as_posix()
            for path in (ROOT / "interactions/entity_candidate").rglob("*")
            if path.is_file()
        } | {
            "system/entity_candidate.py",
            "system/entity_candidate_evals.py",
            "tests/walkthrough_entity_candidate.py",
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
        source = (SYSTEM / "entity_candidate.py").read_text()
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
