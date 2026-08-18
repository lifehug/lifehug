"""Candidate-research source authority: pure v183 contract gates."""

from __future__ import annotations

import copy
import hashlib
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "system"))

import candidate_research as research
from question_candidate import canonical_revision

FOCUS_RECOMMENDATION = {
    "id": "rec-synthetic-harbor",
    "entity": "Synthetic Harbor",
    "type": "place",
    "status": "pending",
    "score": 12.0,
}


class SyntheticGitAuthority:
    """Canonical-tree simulation; no filesystem, Git, projection, or lease."""

    def __init__(self):
        self.worktree: dict[str, bytes] = {}
        self.tree: dict[str, tuple[bytes, str]] = {}
        self.pushed: set[str] = set()
        self.marker_paths: dict[tuple[str, str], str] = {}

    @staticmethod
    def _commit(source_bytes: bytes) -> str:
        return hashlib.sha1(b"synthetic-commit\0" + source_bytes).hexdigest()

    def resolve_exact_source(self, plan, *, vault_root=None, push=True, failpoint=None):
        del vault_root
        path = plan["source_path"]
        identity = (plan["candidate_kind"], plan["candidate_id"])
        other_path = self.marker_paths.get(identity)
        if other_path is not None and other_path != path:
            raise research.CandidateResearchConflict(
                "candidate marker already exists at another path"
            )
        committed = self.tree.get(path)
        if committed is not None:
            source_bytes, commit_sha = committed
            if source_bytes != plan["source_bytes"]:
                raise research.CandidateResearchConflict(
                    "canonical Git tree contains different source bytes"
                )
            if push:
                self.pushed.add(commit_sha)
            return {
                "source_path": path,
                "changed": False,
                "commit_sha": commit_sha,
            }
        existing = self.worktree.get(path)
        if existing is not None and existing != plan["source_bytes"]:
            raise research.CandidateResearchConflict("worktree source bytes conflict")
        self.worktree[path] = plan["source_bytes"]
        self.marker_paths[identity] = path
        if failpoint:
            failpoint("after_source_write")
        commit_sha = self._commit(plan["source_bytes"])
        self.tree[path] = (plan["source_bytes"], commit_sha)
        if failpoint:
            failpoint("after_commit")
        if push:
            self.pushed.add(commit_sha)
            if failpoint:
                failpoint("after_push")
        return {"source_path": path, "changed": True, "commit_sha": commit_sha}


def _turns():
    return [
        research.build_authoritative_user_turn(
            "turn-1",
            "Synthetic Harbor was where my grandmother taught me to wait for the tide.",
        ),
        research.build_authoritative_user_turn(
            "turn-2",
            "After the storm I returned alone, and the broken pier made the loss feel concrete.",
        ),
        research.build_authoritative_user_turn(
            "turn-3",
            "Now I want the harbor story to connect patience, grief, and what I pass to my children.",
        ),
        research.build_authoritative_user_turn(
            "turn-confirm",
            "Yes, that captures the exact research I want preserved.",
        ),
    ]


def _spans(turns, count=3):
    kinds = ["statement", "concrete_event", "concrete_observation"]
    return [
        research.extract_research_evidence_span(
            turns[index], 0, len(turns[index]["text"]), kinds[index]
        )
        for index in range(count)
    ]


def _focus_assessment(*, confirmed=False, missing_dimension=None):
    subject = research.build_focus_candidate_subject(FOCUS_RECOMMENDATION)
    turns = _turns()
    spans = _spans(turns)
    refs = [span["evidence_revision"] for span in spans]
    dimensions = {
        dimension: ([] if dimension == missing_dimension else [refs[index % 3]])
        for index, dimension in enumerate(research.FOCUS_DIMENSIONS)
    }
    # Every span must be used, including when the chosen missing dimension was
    # the only original owner of one.
    used = {ref for values in dimensions.values() for ref in values}
    for ref in refs:
        if ref not in used:
            dimensions["identity"].append(ref)
    assessment = research.build_research_assessment(
        subject=subject,
        evidence=spans,
        dimension_evidence=dimensions,
        seed_questions=[
            {"question": "What changed the next time you returned?", "evidence": False},
            {
                "question": "Who else understands what the harbor meant?",
                "evidence": False,
            },
        ],
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
        )
    return subject, turns, assessment


def _entity_assessment(entity_type: str, count: int):
    entry = {
        "name": f"Synthetic {entity_type.title()}",
        "slug": f"synthetic-{entity_type}",
        "aliases": [],
        "qualifies": False,
        "maps_to_focus": None,
        "page_eligible": False,
    }
    subject = research.build_entity_candidate_subject(entity_type, entry)
    turns = _turns()
    spans = _spans(turns, count=count)
    refs = [span["evidence_revision"] for span in spans]
    dimensions = {
        dimension: [refs[index % count]]
        for index, dimension in enumerate(research.ENTITY_DIMENSIONS)
    }
    assessment = research.build_research_assessment(
        subject=subject,
        evidence=spans,
        dimension_evidence=dimensions,
        seed_questions=[],
        authoritative_turns=turns,
    )
    return subject, turns, assessment


class SubjectAuthorityTests(unittest.TestCase):
    def test_focus_score_only_refresh_does_not_churn_revision(self):
        first = research.build_focus_candidate_subject(FOCUS_RECOMMENDATION)
        changed = {**FOCUS_RECOMMENDATION, "score": 99.0, "mention_count": 10}
        second = research.build_focus_candidate_subject(changed)
        self.assertEqual(first, second)

    def test_identity_and_state_churn_are_revision_bound(self):
        first = research.build_focus_candidate_subject(FOCUS_RECOMMENDATION)
        renamed = research.build_focus_candidate_subject(
            {**FOCUS_RECOMMENDATION, "entity": "Synthetic New Harbor"}
        )
        consumed = research.build_focus_candidate_subject(
            {**FOCUS_RECOMMENDATION, "status": "approved"}
        )
        self.assertNotEqual(first["identity_revision"], renamed["identity_revision"])
        self.assertNotEqual(first["subject_revision"], renamed["subject_revision"])
        self.assertNotEqual(first["subject_revision"], consumed["subject_revision"])
        with self.assertRaises(research.CandidateResearchError):
            research.revalidate_candidate_research_subject(first, consumed)

    def test_closed_kind_and_type_rosters_fail_closed(self):
        with self.assertRaises(research.CandidateResearchError):
            research.build_candidate_research_subject(
                candidate_kind="conversation",
                candidate_id="x",
                subject_type="place",
                subject_label="X",
                subject_slug="x",
                subject_aliases=[],
                candidate_state="active",
            )
        with self.assertRaises(research.CandidateResearchError):
            research.build_candidate_research_subject(
                candidate_kind="focus_candidate",
                candidate_id="x",
                subject_type="object",
                subject_label="X",
                subject_slug="x",
                subject_aliases=[],
                candidate_state="active",
            )

    def test_entity_verdict_mapping_and_eligibility_close_candidate(self):
        base = {
            "name": "Synthetic Compass",
            "slug": "synthetic-compass",
            "aliases": [],
            "maps_to_focus": None,
            "page_eligible": False,
        }
        self.assertEqual(
            research.build_entity_candidate_subject("object", base)["candidate_state"],
            "active",
        )
        self.assertEqual(
            research.build_entity_candidate_subject(
                "object", {**base, "owner_verdict": "never"}
            )["candidate_state"],
            "tombstoned",
        )
        self.assertEqual(
            research.build_entity_candidate_subject(
                "object", {**base, "maps_to_focus": "compass"}
            )["candidate_state"],
            "consumed",
        )
        with self.assertRaises(research.CandidateResearchError):
            research.build_entity_candidate_subject(
                "object", {**base, "owner_verdict": "maybe"}
            )
        self.assertEqual(
            research.build_entity_candidate_subject(
                "object", {**base, "page_eligible": True}
            )["candidate_state"],
            "consumed",
        )


class EvidenceTests(unittest.TestCase):
    def test_exact_unicode_codepoint_slice_and_revision(self):
        turn = research.build_authoritative_user_turn(
            "turn-unicode", "Before 🧭, after the tide changed."
        )
        start = turn["text"].index("🧭")
        end = len(turn["text"])
        span = research.extract_research_evidence_span(
            turn, start, end, "concrete_observation"
        )
        self.assertEqual(span["quote"], "🧭, after the tide changed.")
        self.assertEqual(span, research.validate_research_evidence_span(span, [turn]))

    def test_whitespace_unicode_and_quote_changes_are_not_normalized(self):
        turn = research.build_authoritative_user_turn(
            "turn-exact", "Café  tide\nchanged exactly here."
        )
        span = research.extract_research_evidence_span(
            turn, 0, len(turn["text"]), "statement"
        )
        for key, value in (
            ("quote", span["quote"].replace("  ", " ")),
            ("turn_revision", canonical_revision("different")),
        ):
            forged = {**span, key: value}
            with self.assertRaises(research.CandidateResearchError):
                research.validate_research_evidence_span(forged, [turn])

    def test_assistant_or_summary_turn_is_never_evidence(self):
        source = {"turn_id": "summary", "role": "assistant", "text": "A summary."}
        forged = {
            "schema_version": 1,
            **source,
            "turn_revision": canonical_revision(source),
        }
        with self.assertRaisesRegex(
            research.CandidateResearchError, "only authoritative user turns"
        ):
            research.validate_authoritative_user_turn(forged)

    def test_overlapping_spans_fail_closed(self):
        turn = research.build_authoritative_user_turn(
            "turn-overlap",
            "The synthetic harbor observation was concrete and emotionally important.",
        )
        first = research.extract_research_evidence_span(
            turn, 0, 48, "concrete_observation"
        )
        second = research.extract_research_evidence_span(turn, 20, 70, "statement")
        subject = research.build_focus_candidate_subject(FOCUS_RECOMMENDATION)
        dimensions = {
            dimension: [first["evidence_revision"]]
            for dimension in research.FOCUS_DIMENSIONS
        }
        dimensions["identity"].append(second["evidence_revision"])
        with self.assertRaisesRegex(
            research.CandidateResearchError, "must not overlap"
        ):
            research.build_research_assessment(
                subject=subject,
                evidence=[first, second],
                dimension_evidence=dimensions,
                seed_questions=[],
                authoritative_turns=[turn],
            )


class AssessmentTests(unittest.TestCase):
    def test_readiness_is_recomputed_and_confirmation_is_separate(self):
        _subject, turns, not_ready = _focus_assessment(
            missing_dimension="why_it_matters"
        )
        self.assertFalse(not_ready["readiness"]["ready"])
        self.assertFalse(not_ready["complete"])
        self.assertIn("dimension:why_it_matters", not_ready["readiness"]["missing"])
        with self.assertRaises(research.CandidateResearchError):
            research.build_research_confirmation(
                not_ready,
                turn=turns[-1],
                start=0,
                end=len(turns[-1]["text"]),
                confirmed_at="2026-08-18T20:00:00Z",
                authoritative_turns=turns,
            )

        _subject, turns, ready = _focus_assessment()
        self.assertTrue(ready["readiness"]["ready"])
        self.assertFalse(ready["complete"])
        confirmed = research.confirm_research_assessment(
            ready,
            turn=turns[-1],
            start=0,
            end=len(turns[-1]["text"]),
            confirmed_at="2026-08-18T20:00:00Z",
            authoritative_turns=turns,
        )
        self.assertTrue(confirmed["complete"])
        self.assertNotEqual(ready["research_revision"], confirmed["research_revision"])

    def test_forged_readiness_assessment_and_confirmation_revisions_fail(self):
        _subject, turns, assessment = _focus_assessment(confirmed=True)
        forged = copy.deepcopy(assessment)
        forged["readiness"]["substantive_evidence_count"] = 99
        with self.assertRaisesRegex(research.CandidateResearchError, "readiness"):
            research.validate_research_assessment(forged, authoritative_turns=turns)
        forged = copy.deepcopy(assessment)
        forged["confirmation"]["assessment_revision"] = canonical_revision("stale")
        with self.assertRaisesRegex(
            research.CandidateResearchError, "stale assessment"
        ):
            research.validate_research_assessment(forged, authoritative_turns=turns)

    def test_focus_requires_three_spans_concrete_and_two_non_evidence_questions(self):
        subject = research.build_focus_candidate_subject(FOCUS_RECOMMENDATION)
        turns = _turns()
        spans = _spans(turns, count=2)
        dimensions = {
            dimension: [spans[index % 2]["evidence_revision"]]
            for index, dimension in enumerate(research.FOCUS_DIMENSIONS)
        }
        assessment = research.build_research_assessment(
            subject=subject,
            evidence=spans,
            dimension_evidence=dimensions,
            seed_questions=[{"question": "One question?", "evidence": False}],
            authoritative_turns=turns,
        )
        self.assertFalse(assessment["readiness"]["ready"])
        self.assertEqual(
            assessment["readiness"]["missing"],
            ["seed_questions", "substantive_evidence:3"],
        )
        with self.assertRaisesRegex(research.CandidateResearchError, "evidence=false"):
            research.build_research_assessment(
                subject=subject,
                evidence=spans,
                dimension_evidence=dimensions,
                seed_questions=[{"question": "Forged?", "evidence": True}],
                authoritative_turns=turns,
            )

    def test_entity_minima_are_closed_per_type(self):
        for entity_type, minimum in research.ENTITY_MIN_EVIDENCE_SPANS.items():
            with self.subTest(entity_type=entity_type):
                _subject, _turns_value, assessment = _entity_assessment(
                    entity_type, minimum
                )
                self.assertTrue(assessment["readiness"]["ready"])


class SourceAndReceiptTests(unittest.TestCase):
    def test_source_bytes_are_deterministic_typed_and_summary_free(self):
        subject, turns, assessment = _focus_assessment(confirmed=True)
        first = research.build_candidate_research_source(
            assessment, authoritative_turns=turns, current_subject=subject
        )
        second = research.build_candidate_research_source(
            assessment, authoritative_turns=turns, current_subject=subject
        )
        self.assertEqual(first, second)
        source_text = first["source_bytes"].decode()
        parsed = research.validate_candidate_research_source_text(
            source_text, expected_path=first["source_path"]
        )
        self.assertEqual(parsed["metadata"]["type"], "candidate_research")
        self.assertTrue(parsed["metadata"]["user_confirmed"])
        self.assertFalse(parsed["metadata"]["generated_seed_questions_evidence"])
        self.assertIn("Generated seed questions — not evidence", source_text)
        self.assertNotIn("model summary", source_text.lower())
        for span in assessment["evidence"]:
            self.assertIn(span["quote"], source_text)

    def test_candidate_id_comment_and_path_injection_stays_data(self):
        recommendation = {
            **FOCUS_RECOMMENDATION,
            "id": "rec--><!---still-data",
        }
        subject = research.build_focus_candidate_subject(recommendation)
        _old_subject, turns, base = _focus_assessment()
        rebuilt = research.build_research_assessment(
            subject=subject,
            evidence=base["evidence"],
            dimension_evidence=base["dimension_evidence"],
            seed_questions=base["seed_questions"],
            authoritative_turns=turns,
        )
        confirmed = research.confirm_research_assessment(
            rebuilt,
            turn=turns[-1],
            start=0,
            end=len(turns[-1]["text"]),
            confirmed_at="2026-08-18T20:00:00Z",
            authoritative_turns=turns,
        )
        plan = research.build_candidate_research_source(
            confirmed, authoritative_turns=turns, current_subject=subject
        )
        self.assertRegex(
            plan["source_path"],
            r"^sources/candidate-research/focus_candidate/[0-9a-f]{32}\.md$",
        )
        body = plan["source_bytes"].decode().split("---\n", 2)[-1]
        marker_lines = [
            line
            for line in body.splitlines()
            if line.startswith(research.MARKER_PREFIX)
        ]
        self.assertEqual(len(marker_lines), 1)

    def test_same_bytes_replay_and_commit_push_adoption(self):
        subject, turns, assessment = _focus_assessment(confirmed=True)
        authority = SyntheticGitAuthority()
        first = research.resolve_candidate_research_source(
            assessment,
            authoritative_turns=turns,
            current_subject=subject,
            authority=authority,
            push=True,
        )
        second = research.resolve_candidate_research_source(
            assessment,
            authoritative_turns=turns,
            current_subject=subject,
            authority=authority,
            push=True,
        )
        self.assertTrue(first["changed"])
        self.assertFalse(second["changed"])
        self.assertEqual(
            {k: v for k, v in first.items() if k != "changed"},
            {k: v for k, v in second.items() if k != "changed"},
        )

    def test_crash_after_commit_and_push_adopts_canonical_tree(self):
        subject, turns, assessment = _focus_assessment(confirmed=True)
        for stage in ("after_commit", "after_push"):
            with self.subTest(stage=stage):
                authority = SyntheticGitAuthority()

                def failpoint(current, expected=stage):
                    if current == expected:
                        raise RuntimeError(expected)

                with self.assertRaisesRegex(RuntimeError, stage):
                    research.resolve_candidate_research_source(
                        assessment,
                        authoritative_turns=turns,
                        current_subject=subject,
                        authority=authority,
                        failpoint=failpoint,
                    )
                adopted = research.resolve_candidate_research_source(
                    assessment,
                    authoritative_turns=turns,
                    current_subject=subject,
                    authority=authority,
                )
                self.assertFalse(adopted["changed"])
                self.assertRegex(adopted["commit_sha"], r"^[0-9a-f]{40}$")

    def test_changed_bytes_and_other_path_are_hard_conflicts(self):
        subject, turns, assessment = _focus_assessment(confirmed=True)
        plan = research.build_candidate_research_source(
            assessment, authoritative_turns=turns, current_subject=subject
        )
        authority = SyntheticGitAuthority()
        authority.resolve_exact_source(plan)
        source_bytes, commit = authority.tree[plan["source_path"]]
        authority.tree[plan["source_path"]] = (source_bytes + b"changed", commit)
        with self.assertRaises(research.CandidateResearchConflict):
            research.resolve_candidate_research_source(
                assessment,
                authoritative_turns=turns,
                current_subject=subject,
                authority=authority,
            )

        authority = SyntheticGitAuthority()
        authority.marker_paths[(plan["candidate_kind"], plan["candidate_id"])] = (
            "sources/candidate-research/focus_candidate/other.md"
        )
        with self.assertRaises(research.CandidateResearchConflict):
            research.resolve_candidate_research_source(
                assessment,
                authoritative_turns=turns,
                current_subject=subject,
                authority=authority,
            )

    def test_authority_receipt_cannot_redirect_or_forge_types(self):
        subject, turns, assessment = _focus_assessment(confirmed=True)

        class BadAuthority:
            def resolve_exact_source(self, plan, **kwargs):
                del plan, kwargs
                return {
                    "source_path": "sources/elsewhere.md",
                    "changed": 1,
                    "commit_sha": "a" * 40,
                }

        with self.assertRaises(research.CandidateResearchConflict):
            research.resolve_candidate_research_source(
                assessment,
                authoritative_turns=turns,
                current_subject=subject,
                authority=BadAuthority(),
            )


if __name__ == "__main__":
    unittest.main()
