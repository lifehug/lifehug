"""Candidate-research source authority: pure v183 contract gates."""

from __future__ import annotations

import concurrent.futures
import copy
import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "system"))
sys.path.insert(0, str(ROOT / "tests"))

import candidate_research as research
from question_candidate import canonical_revision
from tempdirs import root_parent_tmp

FOCUS_RECOMMENDATION = {
    "id": "rec-synthetic-harbor",
    "entity": "Synthetic Harbor",
    "type": "place",
    "status": "pending",
    "score": 12.0,
}


def _git(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(root), *args],
        check=False,
        capture_output=True,
        text=True,
    )


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

    def resolve_exact_source(
        self,
        plan,
        *,
        vault_root=None,
        push=True,
        failpoint=None,
        revalidate_current_subject,
    ):
        del vault_root
        revalidate_current_subject()
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
            current_subject=subject,
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
        with self.assertRaisesRegex(research.CandidateResearchError, "must be boolean"):
            research.build_entity_candidate_subject(
                "object", {**base, "page_eligible": 1}
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
    def test_confirmation_cannot_reuse_or_overlap_substantive_evidence(self):
        subject, turns, ready = _focus_assessment()
        evidence_turn = turns[0]
        with self.assertRaisesRegex(
            research.CandidateResearchError, "must not overlap substantive evidence"
        ):
            research.build_research_confirmation(
                ready,
                turn=evidence_turn,
                start=0,
                end=len(evidence_turn["text"]),
                confirmed_at="2026-08-18T20:00:00Z",
                authoritative_turns=turns,
                current_subject=subject,
            )

    def test_boolean_schema_and_readiness_integers_fail_closed(self):
        subject, turns, assessment = _focus_assessment(confirmed=True)
        forged_subject = {**subject, "schema_version": True}
        with self.assertRaisesRegex(research.CandidateResearchError, "integer 1"):
            research.validate_candidate_research_subject(
                forged_subject, require_active=True
            )
        forged = copy.deepcopy(assessment)
        forged["readiness"]["substantive_evidence_count"] = True
        with self.assertRaisesRegex(
            research.CandidateResearchError, "must be an integer"
        ):
            research.validate_research_assessment(
                forged, authoritative_turns=turns, current_subject=subject
            )

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
                current_subject=not_ready["subject"],
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
            current_subject=ready["subject"],
        )
        self.assertTrue(confirmed["complete"])
        self.assertNotEqual(ready["research_revision"], confirmed["research_revision"])

    def test_forged_readiness_assessment_and_confirmation_revisions_fail(self):
        _subject, turns, assessment = _focus_assessment(confirmed=True)
        forged = copy.deepcopy(assessment)
        forged["readiness"]["substantive_evidence_count"] = 99
        with self.assertRaisesRegex(research.CandidateResearchError, "readiness"):
            research.validate_research_assessment(
                forged, authoritative_turns=turns, current_subject=forged["subject"]
            )
        forged = copy.deepcopy(assessment)
        forged["confirmation"]["assessment_revision"] = canonical_revision("stale")
        with self.assertRaisesRegex(
            research.CandidateResearchError, "stale assessment"
        ):
            research.validate_research_assessment(
                forged, authoritative_turns=turns, current_subject=forged["subject"]
            )

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
    def test_disk_tree_restart_ignores_manifest_and_rejects_unmarked_or_contenders(
        self,
    ):
        from tests.walkthrough_candidate_research import SyntheticFileAuthority

        subject, turns, assessment = _focus_assessment(confirmed=True)
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            kwargs = {
                "authoritative_turns": turns,
                "current_subject_loader": lambda: subject,
                "vault_root": root,
                "push": False,
            }
            first = research.resolve_candidate_research_source(
                assessment, authority=SyntheticFileAuthority(), **kwargs
            )
            manifest = root / "state" / "source_manifest.json"
            manifest.parent.mkdir(parents=True)
            manifest.write_text('{"sources":{"stale":true}}', encoding="utf-8")
            restarted = research.resolve_candidate_research_source(
                assessment, authority=SyntheticFileAuthority(), **kwargs
            )
            self.assertTrue(first["changed"])
            self.assertFalse(restarted["changed"])
            manifest.unlink()
            self.assertFalse(
                research.resolve_candidate_research_source(
                    assessment, authority=SyntheticFileAuthority(), **kwargs
                )["changed"]
            )

            source_path = root / first["source_path"]
            valid_bytes = source_path.read_bytes()
            marker = next(
                line
                for line in valid_bytes.decode("utf-8").splitlines()
                if line.startswith(research.MARKER_PREFIX)
            )
            source_path.write_text(
                valid_bytes.decode("utf-8").replace(marker + "\n", "", 1),
                encoding="utf-8",
            )
            with self.assertRaises(research.CandidateResearchConflict):
                research.resolve_candidate_research_source(
                    assessment, authority=SyntheticFileAuthority(), **kwargs
                )

            source_path.write_bytes(valid_bytes)
            contender = source_path.with_name("contender.md")
            contender.write_bytes(valid_bytes)
            with self.assertRaisesRegex(
                research.CandidateResearchConflict, "second identity contender"
            ):
                research.resolve_candidate_research_source(
                    assessment, authority=SyntheticFileAuthority(), **kwargs
                )

    def test_source_requires_current_subject_and_post_pull_reload(self):
        subject, turns, assessment = _focus_assessment(confirmed=True)
        with self.assertRaises(TypeError):
            research.build_candidate_research_source(
                assessment, authoritative_turns=turns
            )
        with self.assertRaises(TypeError):
            research.resolve_candidate_research_source(
                assessment,
                authoritative_turns=turns,
                authority=SyntheticGitAuthority(),
            )
        consumed = research.build_focus_candidate_subject(
            {**FOCUS_RECOMMENDATION, "status": "approved"}
        )
        calls = iter((subject, consumed))
        with self.assertRaisesRegex(
            research.CandidateResearchError, "not active|stale"
        ):
            research.resolve_candidate_research_source(
                assessment,
                authoritative_turns=turns,
                current_subject_loader=lambda: next(calls),
                authority=SyntheticGitAuthority(),
            )

        class OmitsCallback:
            def resolve_exact_source(self, plan, **kwargs):
                del kwargs
                return {
                    "source_path": plan["source_path"],
                    "changed": False,
                    "commit_sha": "a" * 40,
                }

        with self.assertRaisesRegex(
            research.CandidateResearchError, "omitted post-pull"
        ):
            research.resolve_candidate_research_source(
                assessment,
                authoritative_turns=turns,
                current_subject_loader=lambda: subject,
                authority=OmitsCallback(),
            )

    def test_body_and_seed_sections_are_marker_bound_not_just_content_hashed(self):
        subject, turns, assessment = _focus_assessment(confirmed=True)
        plan = research.build_candidate_research_source(
            assessment, authoritative_turns=turns, current_subject=subject
        )
        text = plan["source_bytes"].decode("utf-8")
        for original, replacement in (
            (
                assessment["evidence"][0]["quote"],
                "Model summary replacing the exact first-person evidence span.",
            ),
            (
                assessment["seed_questions"][0]["question"],
                "A replacement generated question?",
            ),
        ):
            with self.subTest(original=original):
                metadata, body = research.split_frontmatter(text)
                body = body.replace(original, replacement, 1)
                metadata["content_sha256"] = research.payload_sha256(body)
                tampered = f"{research.format_frontmatter(metadata)}\n\n{body}"
                with self.assertRaisesRegex(
                    research.CandidateResearchError, "marker-bound"
                ):
                    research.validate_candidate_research_source_text(
                        tampered, expected_path=plan["source_path"]
                    )

    def test_boolean_frontmatter_schema_fails_even_though_true_equals_one(self):
        subject, turns, assessment = _focus_assessment(confirmed=True)
        plan = research.build_candidate_research_source(
            assessment, authoritative_turns=turns, current_subject=subject
        )
        text = (
            plan["source_bytes"]
            .decode("utf-8")
            .replace("schema_version: 1", "schema_version: true", 1)
        )
        with self.assertRaisesRegex(research.CandidateResearchError, "schema_version"):
            research.validate_candidate_research_source_text(
                text, expected_path=plan["source_path"]
            )

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
        self.assertEqual(
            parsed["evidence_quotes"],
            [span["quote"] for span in assessment["evidence"]],
        )
        self.assertEqual(
            parsed["seed_questions"],
            [row["question"] for row in assessment["seed_questions"]],
        )
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
            current_subject=subject,
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
            current_subject_loader=lambda: subject,
            authority=authority,
            push=True,
        )
        second = research.resolve_candidate_research_source(
            assessment,
            authoritative_turns=turns,
            current_subject_loader=lambda: subject,
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
                        current_subject_loader=lambda: subject,
                        authority=authority,
                        failpoint=failpoint,
                    )
                adopted = research.resolve_candidate_research_source(
                    assessment,
                    authoritative_turns=turns,
                    current_subject_loader=lambda: subject,
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
        authority.resolve_exact_source(plan, revalidate_current_subject=lambda: None)
        source_bytes, commit = authority.tree[plan["source_path"]]
        authority.tree[plan["source_path"]] = (source_bytes + b"changed", commit)
        with self.assertRaises(research.CandidateResearchConflict):
            research.resolve_candidate_research_source(
                assessment,
                authoritative_turns=turns,
                current_subject_loader=lambda: subject,
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
                current_subject_loader=lambda: subject,
                authority=authority,
            )

    def test_authority_receipt_cannot_redirect_or_forge_types(self):
        subject, turns, assessment = _focus_assessment(confirmed=True)

        class BadAuthority:
            def resolve_exact_source(self, plan, **kwargs):
                kwargs["revalidate_current_subject"]()
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
                current_subject_loader=lambda: subject,
                authority=BadAuthority(),
            )


class RealGitAuthorityTests(unittest.TestCase):
    def setUp(self):
        self.root = root_parent_tmp(self, ROOT, prefix="lifehug-research-git-")
        self._init_root(self.root)
        self.subject, self.turns, self.assessment = _focus_assessment(confirmed=True)

    def _init_root(self, root: Path) -> None:
        state = root / "state"
        state.mkdir()
        (root / ".gitignore").write_text("state/jobs/\n", encoding="utf-8")
        (root / "question-bank.md").write_text("# Questions\n", encoding="utf-8")
        (state / "rotation.json").write_text(
            json.dumps(
                {
                    "version": 1,
                    "current_pass": 1,
                    "pass_names": ["skeleton"],
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
            '{"version":1,"last_updated":null,"categories":{}}\n',
            encoding="utf-8",
        )
        self.assertEqual(_git(root, "init", "-b", "main").returncode, 0)
        _git(root, "config", "user.name", "Fixture")
        _git(root, "config", "user.email", "fixture@example.invalid")
        _git(root, "add", ".")
        self.assertEqual(_git(root, "commit", "-m", "fixture").returncode, 0)

    def resolve(self, **kwargs):
        return research.resolve_candidate_research_source(
            self.assessment,
            authoritative_turns=self.turns,
            current_subject_loader=lambda: self.subject,
            vault_root=self.root,
            push=False,
            **kwargs,
        )

    def add_remote(self) -> Path:
        remote = root_parent_tmp(self, ROOT, prefix="lifehug-research-remote-")
        self.assertEqual(_git(remote, "init", "--bare").returncode, 0)
        _git(self.root, "remote", "add", "origin", str(remote))
        self.assertEqual(
            _git(self.root, "push", "--set-upstream", "origin", "main").returncode,
            0,
        )
        return remote

    def test_real_git_first_commit_replay_and_manifest_repairs(self):
        first = self.resolve()
        replay = self.resolve()
        self.assertTrue(first["changed"])
        self.assertFalse(replay["changed"])
        self.assertEqual(first["commit_sha"], replay["commit_sha"])
        self.assertEqual(_git(self.root, "status", "--porcelain").stdout, "")

        manifest = self.root / "state" / "source_manifest.json"
        manifest.unlink()
        _git(self.root, "add", "state/source_manifest.json")
        _git(self.root, "commit", "-m", "remove repairable projection")
        repaired = self.resolve()
        self.assertFalse(repaired["changed"])
        self.assertEqual(repaired["commit_sha"], first["commit_sha"])
        self.assertTrue(manifest.is_file())

        data = json.loads(manifest.read_text(encoding="utf-8"))
        data["sources"][first["source_path"]]["research_revision"] = (
            "sha256:" + "0" * 64
        )
        manifest.write_text(json.dumps(data) + "\n", encoding="utf-8")
        _git(self.root, "add", "state/source_manifest.json")
        _git(self.root, "commit", "-m", "stale repairable projection")
        repaired_again = self.resolve()
        self.assertFalse(repaired_again["changed"])
        self.assertEqual(repaired_again["commit_sha"], first["commit_sha"])
        fixed = json.loads(manifest.read_text(encoding="utf-8"))
        self.assertEqual(
            fixed["sources"][first["source_path"]]["research_revision"],
            self.assessment["research_revision"],
        )

    def test_real_git_crash_after_write_and_commit_adopts(self):
        for stage_prefix in ("after_write:sources/candidate-research", "after_commit"):
            with self.subTest(stage=stage_prefix):
                root = root_parent_tmp(self, ROOT, prefix="lifehug-research-crash-")
                self._init_root(root)

                def failpoint(stage, expected=stage_prefix):
                    if stage.startswith(expected):
                        raise RuntimeError(expected)

                with self.assertRaisesRegex(RuntimeError, stage_prefix):
                    research.resolve_candidate_research_source(
                        self.assessment,
                        authoritative_turns=self.turns,
                        current_subject_loader=lambda: self.subject,
                        vault_root=root,
                        push=False,
                        failpoint=failpoint,
                    )
                adopted = research.resolve_candidate_research_source(
                    self.assessment,
                    authoritative_turns=self.turns,
                    current_subject_loader=lambda: self.subject,
                    vault_root=root,
                    push=False,
                )
                self.assertRegex(adopted["commit_sha"], r"^[0-9a-f]{40}$")
                self.assertEqual(_git(root, "status", "--porcelain").stdout, "")

    def test_real_git_concurrency_and_two_contender_conflict(self):
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            receipts = list(pool.map(lambda _index: self.resolve(), range(2)))
        self.assertEqual(sorted(row["changed"] for row in receipts), [False, True])
        source = self.root / receipts[0]["source_path"]
        contender = source.with_name("contender.md")
        contender.write_bytes(source.read_bytes())
        _git(self.root, "add", contender.relative_to(self.root).as_posix())
        _git(self.root, "commit", "-m", "add conflicting contender")
        with self.assertRaisesRegex(
            research.CandidateResearchConflict, "conflicting path"
        ):
            self.resolve()

    def test_push_and_rebase_tamper_revalidate_exact_source(self):
        self.add_remote()
        real_git = research.exact_file_git._git
        rejected = False

        def tampering_git(root: Path, *args: str):
            nonlocal rejected
            if args == ("push",) and not rejected:
                rejected = True
                return subprocess.CompletedProcess(args, 1, "", "synthetic reject")
            if rejected and args == ("pull", "--rebase", "--autostash"):
                source = next((root / "sources" / "candidate-research").rglob("*.md"))
                source.write_text(
                    source.read_text(encoding="utf-8").replace(
                        "Only the literal user-turn excerpts",
                        "Tampered user-turn excerpts",
                    ),
                    encoding="utf-8",
                )
                return subprocess.CompletedProcess(args, 0, "", "")
            return real_git(root, *args)

        with mock.patch.object(research.exact_file_git, "_git", tampering_git):
            with self.assertRaises(research.CandidateResearchConflict):
                research.resolve_candidate_research_source(
                    self.assessment,
                    authoritative_turns=self.turns,
                    current_subject_loader=lambda: self.subject,
                    vault_root=self.root,
                    push=True,
                )

    def test_crash_after_push_adopts_original_commit(self):
        self.add_remote()

        def failpoint(stage):
            if stage == "after_push":
                raise RuntimeError(stage)

        with self.assertRaisesRegex(RuntimeError, "after_push"):
            research.resolve_candidate_research_source(
                self.assessment,
                authoritative_turns=self.turns,
                current_subject_loader=lambda: self.subject,
                vault_root=self.root,
                push=True,
                failpoint=failpoint,
            )
        introducing = research.exact_file_git.find_first_marker_commit(
            self.root,
            research.candidate_research_source_path(
                self.subject["candidate_kind"], self.subject["candidate_id"]
            ),
            research.build_candidate_research_source(
                self.assessment,
                authoritative_turns=self.turns,
                current_subject=self.subject,
            )["marker_line"],
        )
        replay = research.resolve_candidate_research_source(
            self.assessment,
            authoritative_turns=self.turns,
            current_subject_loader=lambda: self.subject,
            vault_root=self.root,
            push=True,
        )
        self.assertFalse(replay["changed"])
        self.assertEqual(replay["commit_sha"], introducing)

    def test_post_rebase_callback_reloads_current_subject(self):
        self.add_remote()
        real_git = research.exact_file_git._git
        rejected = False

        def rejecting_git(root: Path, *args: str):
            nonlocal rejected
            if args == ("push",) and not rejected:
                rejected = True
                return subprocess.CompletedProcess(args, 1, "", "synthetic reject")
            if rejected and args == ("pull", "--rebase", "--autostash"):
                return subprocess.CompletedProcess(args, 0, "", "")
            return real_git(root, *args)

        consumed = research.build_focus_candidate_subject(
            {**FOCUS_RECOMMENDATION, "status": "approved"}
        )
        calls = 0

        def load_subject():
            nonlocal calls
            calls += 1
            return consumed if calls >= 4 else self.subject

        with mock.patch.object(research.exact_file_git, "_git", rejecting_git):
            with self.assertRaisesRegex(
                research.CandidateResearchError, "not active|stale"
            ):
                research.resolve_candidate_research_source(
                    self.assessment,
                    authoritative_turns=self.turns,
                    current_subject_loader=load_subject,
                    vault_root=self.root,
                    push=True,
                )
        self.assertGreaterEqual(calls, 4)


if __name__ == "__main__":
    unittest.main()
