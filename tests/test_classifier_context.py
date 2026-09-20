"""Canonical contextual classifier freshness and validation (PR342)."""

from __future__ import annotations

import io
import json
import shutil
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "system"))

import classifier_context as cc  # noqa: E402
from ai_provider import failure_metadata  # noqa: E402
import classifier_claims  # noqa: E402
import classify_story  # noqa: E402
import entity_roster  # noqa: E402
import episode_fold  # noqa: E402
import event_identity  # noqa: E402
import landmark_projection  # noqa: E402
import temporal_claims  # noqa: E402
import temporal_publication  # noqa: E402
import temporal_projection  # noqa: E402
import temporal_store  # noqa: E402
import temporal_timeline  # noqa: E402
import timeline_evidence  # noqa: E402


def date(value: str) -> dict:
    return {
        "best": value,
        "earliest": value.split("/")[0],
        "latest": value.split("/")[-1],
        "granularity": "range" if "/" in value else "year",
        "confidence": "certain",
        "basis": "document",
        "anchors": [],
        "provenance": [{"source": "human:test", "quote": "a supported date"}],
    }


def node(node_id="node:stay", value="1998/2001", claim_id="claim:external") -> dict:
    return {
        "node_id": node_id,
        "node_kind": "episode",
        "event_kind": "residence",
        "episode_id": "episode:stay",
        "label": "Cedarport stay",
        "subject_refs": ["place/cedarport", "self"],
        "legacy_refs": ["cedarport"],
        "best_temporal_value": date(value),
        "alternate_values": [],
        "input_claim_refs": [claim_id],
        "basis": "explicit",
        "conflict_state": "none",
    }


class ContextCase(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp(prefix="lifehug-classifier-context-"))
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        self.source = self.root / "sources" / "manual" / "story.md"
        self.source.parent.mkdir(parents=True)
        self.source.write_text("I found the letter while we lived in Cedarport.", encoding="utf-8")
        (self.root / "state" / "temporal_claims").mkdir(parents=True)
        # Retrieval/validator unit fixtures start at the independent fold's
        # output. Real receipt/fold coverage lives in test_classifier_context_independent.
        self.fold_patch = mock.patch.object(cc, "_derive_context_timeline",
            side_effect=lambda *_args: SimpleNamespace(nodes=self.candidate_nodes))
        self.fold_patch.start()
        self.addCleanup(self.fold_patch.stop)
        self.write_projection([node()])

    def write_projection(self, nodes, *, generation=1) -> None:
        self.candidate_nodes = nodes
        (self.root / cc.CALCULATED_TIMELINE_PATH).write_text(json.dumps({
            "version": 1,
            "projection_generation": generation,
            "generated_at": f"2026-09-{generation:02d}T00:00:00Z",
            "nodes": nodes,
        }), encoding="utf-8")

    def snapshot(self):
        return cc.build_context_snapshot(self.root, self.source)

    def response(self, snapshot=None):
        snap = snapshot or self.snapshot()
        quote = "while we lived in Cedarport"
        return {
            "_classification_snapshot": cc.snapshot_metadata(snap),
            "events": [{
                "title": "Finding the letter",
                "description": "I found the letter.",
                "places": ["Cedarport"],
                "timeline_relation": {
                    "relation": "within",
                    "candidate_id": "node:stay",
                    "entity_refs": ["place/cedarport"],
                    "evidence": {"quote": quote},
                },
            }],
        }

    def write_correction(
        self,
        name: str,
        body: str,
        *,
        target: Path | None = None,
        supersedes: str = "",
    ) -> str:
        target = target or self.source
        corrections = self.root / "sources" / "corrections"
        corrections.mkdir(parents=True, exist_ok=True)
        path = corrections / f"{name}.md"
        source_id = f"correction:{name}"
        target_relative = target.relative_to(self.root).as_posix()
        supersedes_lines = (
            f'supersedes: "{supersedes}"\n'
            f'supersedes_path: "sources/corrections/{supersedes.removeprefix("correction:")}.md"\n'
            if supersedes
            else ""
        )
        path.write_text(
            "---\n"
            'type: "source_correction"\n'
            f'source_id: "{source_id}"\n'
            f'source_path: "sources/corrections/{name}.md"\n'
            f'corrects_path: "{target_relative}"\n'
            f"{supersedes_lines}"
            'correction_kind: "factual"\n'
            "---\n\n"
            f"# Synthetic correction\n\n{body}\n",
            encoding="utf-8",
        )
        return source_id


class StableFreshnessTests(ContextCase):
    def test_effective_source_revision_binds_active_correction_leaves(self):
        other = self.source.parent / "other.md"
        other.write_text("An unrelated synthetic story.", encoding="utf-8")
        raw_revision = cc.source_revision(self.source)
        before = self.snapshot()
        other_before = cc.build_context_snapshot(self.root, other)
        self.assertEqual(before["source_revision"], raw_revision)

        first = self.write_correction("first", "The city was Harborview, not Cedarport.")
        after_add = self.snapshot()
        self.assertNotEqual(after_add["source_revision"], raw_revision)
        self.assertEqual(
            cc.refresh_reason(after_add, {"classification_snapshot": cc.snapshot_metadata(before)}),
            "source_changed",
        )

        second = self.write_correction(
            "second",
            "The city was Thunderhead, not Harborview.",
            supersedes=first,
        )
        after_supersede = self.snapshot()
        self.assertNotEqual(
            after_supersede["source_revision"], after_add["source_revision"]
        )

        self.write_correction(
            "retract-second",
            "The previous correction is retracted; the original wording stands.",
            supersedes=second,
        )
        after_retraction = self.snapshot()
        self.assertNotEqual(
            after_retraction["source_revision"], after_supersede["source_revision"]
        )
        self.assertEqual(
            cc.build_context_snapshot(self.root, other)["source_revision"],
            other_before["source_revision"],
        )

    def test_source_relevant_roster_alias_changes_freshness_with_same_candidate(self):
        roster_dir = self.root / "state" / "entity_rosters"
        roster_dir.mkdir(parents=True)
        roster_path = roster_dir / "place.json"
        roster = {
            "version": 1,
            "type": "place",
            "entities": [
                {"name": "Cedarport", "slug": "cedarport", "aliases": []},
                {"name": "Elsewhere", "slug": "elsewhere", "aliases": []},
            ],
        }
        roster_path.write_text(json.dumps(roster), encoding="utf-8")
        self.source.write_text("Thunderhead was home.", encoding="utf-8")
        self.write_projection([node()])
        before = self.snapshot()
        self.assertEqual(
            [row["candidate_id"] for row in before["candidates"]], ["node:stay"]
        )

        roster["entities"][0]["aliases"] = ["Thunderhead"]
        roster_path.write_text(json.dumps(roster), encoding="utf-8")
        matched = self.snapshot()
        self.assertEqual(
            [row["candidate_id"] for row in matched["candidates"]], ["node:stay"]
        )
        self.assertNotEqual(matched["context_digest"], before["context_digest"])

        roster["entities"][1]["aliases"] = ["Thunderhead"]
        roster_path.write_text(json.dumps(roster), encoding="utf-8")
        ambiguous = self.snapshot()
        self.assertEqual(
            [row["candidate_id"] for row in ambiguous["candidates"]], ["node:stay"]
        )
        self.assertNotEqual(ambiguous["context_digest"], matched["context_digest"])

        roster["entities"][1]["aliases"] = ["Elsewhere Station"]
        roster_path.write_text(json.dumps(roster), encoding="utf-8")
        unrelated_before = self.snapshot()
        roster["entities"][1]["aliases"] = ["Another Unmentioned Alias"]
        roster_path.write_text(json.dumps(roster), encoding="utf-8")
        unrelated_after = self.snapshot()
        self.assertEqual(
            unrelated_after["context_digest"], unrelated_before["context_digest"]
        )

    def test_machine_telling_alias_churn_does_not_change_freshness(self):
        first = node() | {"legacy_refs": ["machine:first"]}
        self.write_projection([first])
        before = self.snapshot()
        second = node() | {"legacy_refs": ["machine:second"]}
        self.write_projection([second], generation=2)
        after = self.snapshot()
        self.assertNotEqual(
            before["candidates"][0]["aliases"], after["candidates"][0]["aliases"]
        )
        self.assertEqual(after["context_digest"], before["context_digest"])

    def test_generation_and_timestamp_do_not_change_digest(self):
        first = self.snapshot()["context_digest"]
        self.write_projection([node()], generation=9)
        self.assertEqual(self.snapshot()["context_digest"], first)

    def test_this_sources_own_classifier_output_cannot_invalidate_itself(self):
        self.fold_patch.stop()
        active = self.root / cc.ACTIVE_INDEX_PATH
        active.write_text(json.dumps({"claims": [{
            "claim_id": "claim:self",
            "status": "active",
            "source_ref": {
                "source_id": "classification:story#event",
                "source_path": "sources/manual/story.md",
            },
        }]}), encoding="utf-8")
        self.write_projection([node(claim_id="claim:self")])
        first = self.snapshot()
        self.write_projection([node(value="2005/2008", claim_id="claim:self")], generation=2)
        second = self.snapshot()
        self.assertEqual(first["context_digest"], second["context_digest"])
        self.assertEqual(first["candidates"], [])

    def test_context_change_refreshes_even_a_nonstale_classification(self):
        first = self.snapshot()
        stored = {"classification_snapshot": cc.snapshot_metadata(first)}
        self.assertIsNone(cc.refresh_reason(first, stored))
        self.write_projection([node(value="2005/2008")])
        self.assertIsNone(
            cc.refresh_reason(self.snapshot(), stored),
            "a bound-only candidate correction propagates through the canonical link",
        )

    def test_context_removal_invalidates_the_prior_reading(self):
        first = self.snapshot()
        stored = {"classification_snapshot": cc.snapshot_metadata(first)}
        self.write_projection([])
        self.assertEqual(cc.refresh_reason(self.snapshot(), stored), "context_changed")

    def test_inherited_job_episode_is_retrieved_by_grounded_entity_ref(self):
        claim = temporal_claims.validate_temporal_claim({
            "subject_ref": "org/tidewheel",
            "subject_mention": "Tidewheel",
            "source_ref": {
                "source_id": "listener:story",
                "revision": temporal_store.payload_sha256("synthetic"),
                "source_path": "sources/manual/story.md",
            },
            "source_kind": "conversation", "claim_type": "date", "event_kind": "job",
            "temporal_value": date("2002/2006"), "basis": "explicit", "confidence": 1.0,
            "evidence": [{"quote": "Synthetic evidence"}], "extractor_version": "test:1",
        })
        temporal_store.write_receipt(self.root, {"source_ref": claim["source_ref"],
            "extractor_version": "test:1", "claims": [claim]})
        job = node("node:tidewheel-job", "2002/2006", "claim:job") | {
            "episode_id": None,
            "event_kind": "job",
            "subject_refs": ["org/tidewheel", "self"],
        }
        self.write_projection([node(), job])
        snapshot = self.snapshot()
        self.assertEqual(
            [row["candidate_id"] for row in snapshot["candidates"]],
            ["node:stay", "node:tidewheel-job"],
        )

    def test_human_negative_identity_is_visible_and_changes_freshness(self):
        telling_ref = "classification:story#aaaaaaaaaaaa"
        claim = temporal_claims.validate_temporal_claim({
            "source_ref": {"source_id": telling_ref,
                           "revision": temporal_store.payload_sha256("synthetic"),
                           "source_path": "sources/manual/story.md"},
            "source_kind": "system_derived", "claim_type": "date", "subject_ref": "self",
            "subject_mention": "I",
            "event_kind": "moment", "temporal_value": date("1999"),
            "basis": "explicit", "confidence": 1.0,
            "evidence": [{"quote": "Synthetic evidence"}], "extractor_version": "test:1",
        })
        temporal_store.write_receipt(self.root, {"source_ref": claim["source_ref"],
            "extractor_version": "test:1", "claims": [claim]})
        event_identity.write_telling_manifest(self.root, {
            "tellings": [{
                "telling_ref": telling_ref,
                "source_path": "sources/manual/story.md",
                "event_refs": [],
                "era_refs": [],
                "aliases": [],
                "bound_identity_ids": [],
            }],
        })
        before = self.snapshot()
        record, created = event_identity.file_event_identity(
            self.root,
            telling_ref=telling_ref,
            episode_id="episode:" + "b" * 24,
            relation="not_same",
            origin="confirmed",
            created_at="2026-09-15T00:00:00Z",
        )
        self.assertTrue(created)
        after = self.snapshot()
        self.assertNotEqual(after["context_digest"], before["context_digest"])
        self.assertEqual(after["human_identity_decisions"][0]["identity_id"], record["identity_id"])
        self.assertEqual(after["human_identity_decisions"][0]["relation"], "not_same")

    def test_unrelated_human_identity_does_not_refresh_this_source(self):
        before = self.snapshot()
        event_identity.file_event_identity(
            self.root,
            telling_ref="classification:other#aaaaaaaaaaaa",
            episode_id="episode:" + "c" * 24,
            relation="not_same",
            origin="confirmed",
            created_at="2026-09-15T00:00:00Z",
        )
        after = self.snapshot()
        self.assertEqual(after["human_identity_decisions"], [])
        self.assertEqual(after["context_digest"], before["context_digest"])

    def test_target_selection_is_capped_and_reports_unfinished_work(self):
        second = self.root / "sources" / "manual" / "other.md"
        second.write_text("Another synthetic story.", encoding="utf-8")
        report = cc.select_refresh_targets(self.root, [self.source, second], limit=1)
        self.assertEqual(report["selected_count"], 1)
        self.assertEqual(report["remaining_count"], 1)
        self.assertFalse(report["complete"])

    def test_new_words_outrank_the_context_backlog(self):
        """lifehug#371: a just-edited story is selected before a context refresh
        that merely sorts earlier by path."""
        early = self.root / "sources" / "manual" / "a-backlog.md"
        early.write_text("An older synthetic story in Cedarport.", encoding="utf-8")
        late = self.root / "sources" / "manual" / "z-just-told.md"
        late.write_text("A synthetic story the author just told.", encoding="utf-8")
        current = {
            cc._relative_source(self.root, source): cc.snapshot_metadata(
                cc.build_context_snapshot(self.root, source)
            )
            for source in (early, late)
        }
        records = {
            cc._relative_source(self.root, early): {
                "classification_snapshot": {
                    **current[cc._relative_source(self.root, early)],
                    "context_digest": "sha256:" + "0" * 64,
                }
            },
            cc._relative_source(self.root, late): {
                "classification_snapshot": {
                    **current[cc._relative_source(self.root, late)],
                    "source_revision": "sha256:" + "1" * 64,
                }
            },
        }
        report = cc.select_refresh_targets(
            self.root, [early, late], classifications=records, limit=1
        )
        self.assertEqual(
            [(row["source_path"], row["reason"]) for row in report["targets"]],
            [(cc._relative_source(self.root, late), "source_changed")],
        )
        self.assertEqual(report["remaining_count"], 1)
        full = cc.select_refresh_targets(
            self.root, [early, late], classifications=records, limit=2
        )
        self.assertEqual([row["reason"] for row in full["targets"]], ["source_changed", "context_changed"])

    def test_target_selection_loads_canonical_catalog_once_for_many_sources(self):
        sources = []
        for index in range(100):
            source = self.source.parent / f"story-{index:03d}.md"
            source.write_text(f"Synthetic story {index} in Cedarport.", encoding="utf-8")
            sources.append(source)

        with mock.patch.object(
            cc,
            "_derive_context_timeline",
            wraps=cc._derive_context_timeline,
        ) as derive_context, mock.patch.object(
            temporal_store,
            "fold_active_index",
            wraps=temporal_store.fold_active_index,
        ) as fold_active_index, mock.patch.object(
            entity_roster,
            "load_roster",
            wraps=entity_roster.load_roster,
        ) as load_roster, mock.patch.object(
            event_identity,
            "load_event_identities",
            wraps=event_identity.load_event_identities,
        ) as load_event_identities, mock.patch.object(
            event_identity,
            "load_episode_operations",
            wraps=event_identity.load_episode_operations,
        ) as load_episode_operations, mock.patch.object(
            event_identity,
            "read_telling_manifest",
            wraps=event_identity.read_telling_manifest,
        ) as read_telling_manifest:
            report = cc.select_refresh_targets(
                self.root, sources, limit=50, classifications={}
            )

        self.assertEqual(report["selected_count"], 50)
        self.assertEqual(report["pending_count"], 100)
        self.assertEqual(report["remaining_count"], 50)
        self.assertFalse(report["complete"])
        self.assertEqual(derive_context.call_count, 1)
        self.assertEqual(fold_active_index.call_count, 1)
        self.assertEqual(load_roster.call_count, 4)
        self.assertEqual(load_event_identities.call_count, 1)
        self.assertEqual(load_episode_operations.call_count, 1)
        self.assertEqual(read_telling_manifest.call_count, 1)

    def test_standalone_snapshots_keep_independent_fresh_catalog_reads(self):
        with mock.patch.object(
            cc,
            "_derive_context_timeline",
            wraps=cc._derive_context_timeline,
        ) as derive_context, mock.patch.object(
            temporal_store,
            "fold_active_index",
            wraps=temporal_store.fold_active_index,
        ) as fold_active_index:
            self.snapshot()
            self.snapshot()

        self.assertEqual(derive_context.call_count, 2)
        self.assertEqual(fold_active_index.call_count, 2)

    def test_empty_target_inventory_does_not_load_the_catalog(self):
        with mock.patch.object(cc, "_load_context_catalog") as load_catalog:
            report = cc.select_refresh_targets(self.root, [], classifications={})

        load_catalog.assert_not_called()
        self.assertEqual(report["pending_count"], 0)
        self.assertTrue(report["complete"])

    def test_shared_independent_candidate_is_available_to_every_source(self):
        second = self.source.parent / "other.md"
        second.write_text("Another synthetic story.", encoding="utf-8")
        (self.root / cc.ACTIVE_INDEX_PATH).write_text(json.dumps({"claims": [
            {
                "claim_id": "claim:self",
                "status": "active",
                "source_ref": {
                    "source_id": "classification:story#event",
                    "source_path": "sources/manual/story.md",
                },
            },
            {
                "claim_id": "claim:grounded",
                "status": "active",
                "source_ref": {
                    "source_id": "listener:landmark",
                    "source_path": "sources/manual/landmark.md",
                },
            },
        ]}), encoding="utf-8")
        self.write_projection([
            node(claim_id="claim:self") | {
                "input_claim_refs": ["claim:self", "claim:grounded"],
            }
        ])

        catalog = cc._load_context_catalog(self.root)
        own = cc._build_context_snapshot_from_catalog(
            self.root, self.source, catalog
        )
        other = cc._build_context_snapshot_from_catalog(self.root, second, catalog)

        self.assertEqual(other["candidates"], [])
        self.assertEqual(
            [row["candidate_id"] for row in own["candidates"]], ["node:stay"]
        )

    def test_large_catalog_keeps_relevant_repeated_stays_and_real_aliases(self):
        roster_dir = self.root / "state" / "entity_rosters"
        roster_dir.mkdir(parents=True)
        (roster_dir / "place.json").write_text(json.dumps({
            "version": 1,
            "type": "place",
            "entities": [{
                "name": "Cedarport",
                "slug": "cedarport",
                "aliases": ["Cedar City"],
            }],
        }), encoding="utf-8")
        noise = [
            node(
                node_id=f"node:noise-{index:03d}",
                value=f"{1900 + index}/{1901 + index}",
                claim_id=f"claim:noise-{index:03d}",
            ) | {
                "episode_id": None,
                "node_kind": "event",
                "event_kind": "moment",
                "label": f"Noise moment {index}",
                "legacy_refs": [f"noise-{index}"],
                "subject_refs": ["self"],
            }
            for index in range(110)
        ]
        unrelated = [
            node(
                node_id=f"node:stay-{index:03d}",
                value="1980/1981",
                claim_id=f"claim:stay-{index:03d}",
            ) | {
                "episode_id": None,
                "subject_refs": [f"place/other-{index}", "self"],
                "label": f"Other residence {index}",
                "legacy_refs": [f"other-{index}"],
            }
            for index in range(70)
        ]
        repeated = [
            node("node:cedar-one", "1990/1992", "claim:cedar-one") | {
                "episode_id": None,
                "subject_refs": ["place/cedarport", "self"],
            },
            node("node:cedar-two", "2000/2002", "claim:cedar-two") | {
                "episode_id": None,
                "subject_refs": ["place/cedarport", "self"],
            },
        ]
        self.write_projection(noise + unrelated + repeated)
        snapshot = self.snapshot()
        self.assertEqual(
            [row["candidate_id"] for row in snapshot["candidates"]],
            ["node:cedar-one", "node:cedar-two"],
        )
        self.assertFalse(snapshot["context_truncated"])
        self.assertGreater(snapshot["catalog_omitted_count"], 60)
        for row in snapshot["candidates"]:
            self.assertIn("Cedar City", row["aliases"])

    def test_large_catalog_resolves_raw_subject_label_through_canonical_roster(self):
        roster_dir = self.root / "state" / "entity_rosters"
        roster_dir.mkdir(parents=True)
        (roster_dir / "place.json").write_text(json.dumps({
            "version": 1,
            "type": "place",
            "entities": [{
                "name": "Cedarport",
                "slug": "cedarport",
                "aliases": ["The old Cedarport house"],
            }],
        }), encoding="utf-8")
        self.source.write_text(
            "I found the envelope while we lived in Cedarport.", encoding="utf-8"
        )
        unrelated = [
            node(
                node_id=f"node:other-{index:03d}",
                value="1980/1981",
                claim_id=f"claim:other-{index:03d}",
            ) | {
                "episode_id": None,
                "subject_refs": [f"place/other-{index}", "self"],
                "label": f"Other residence {index}",
                "legacy_refs": [f"other-{index}"],
            }
            for index in range(110)
        ]
        repeated = [
            node("node:zz-cedarport-one", "1990/1992", "claim:cedarport-one") | {
                "episode_id": None,
                "subject_refs": ["Cedarport", "self"],
            },
            node("node:zz-cedarport-two", "2000/2002", "claim:cedarport-two") | {
                "episode_id": None,
                "subject_refs": ["Cedarport", "self"],
            },
        ]
        self.write_projection(unrelated + repeated)

        snapshot = self.snapshot()

        self.assertEqual(
            [row["candidate_id"] for row in snapshot["candidates"]],
            ["node:zz-cedarport-one", "node:zz-cedarport-two"],
        )
        self.assertFalse(snapshot["context_truncated"])
        self.assertGreater(snapshot["catalog_omitted_count"], 100)
        for row in snapshot["candidates"]:
            self.assertEqual(row["entity_refs"], ["place/cedarport", "self"])
            self.assertEqual(row["unresolved_entity_mentions"], [])
            self.assertEqual(row["entity_ref_ambiguities"], [])
            self.assertIn("The old Cedarport house", row["aliases"])

    def test_ambiguous_raw_subject_label_is_not_bound_or_used_for_retrieval(self):
        roster_dir = self.root / "state" / "entity_rosters"
        roster_dir.mkdir(parents=True)
        (roster_dir / "place.json").write_text(json.dumps({
            "version": 1,
            "type": "place",
            "entities": [
                {"name": "North Ranch", "slug": "north-ranch", "aliases": ["The Ranch"]},
                {"name": "South Ranch", "slug": "south-ranch", "aliases": ["The Ranch"]},
            ],
        }), encoding="utf-8")
        self.source.write_text(
            "I found the envelope while we lived at The Ranch.", encoding="utf-8"
        )
        unrelated = [
            node(
                node_id=f"node:other-{index:03d}",
                value="1980/1981",
                claim_id=f"claim:other-{index:03d}",
            ) | {
                "episode_id": None,
                "subject_refs": [f"place/other-{index}", "self"],
            }
            for index in range(110)
        ]
        target = node("node:zz-ranch", "1990/1992", "claim:ranch") | {
            "episode_id": None,
            "subject_refs": ["The Ranch", "self"],
        }
        self.write_projection(unrelated + [target])

        snapshot = self.snapshot()

        self.assertFalse(snapshot["context_truncated"])
        self.assertIn(
            "node:zz-ranch",
            [row["candidate_id"] for row in snapshot["candidates"]],
        )
        resolved = cc._candidate(
            target,
            roster_aliases=cc._roster_context(
                self.root, self.source.read_text(encoding="utf-8")
            )[0],
            rosters=cc._roster_context(
                self.root, self.source.read_text(encoding="utf-8")
            )[2],
        )
        self.assertEqual(resolved["entity_refs"], ["self"])
        self.assertEqual(resolved["unresolved_entity_mentions"], [])
        self.assertEqual(resolved["entity_ref_ambiguities"], [{
            "mention": "The Ranch",
            "candidate_refs": ["place/north-ranch", "place/south-ranch"],
        }])


class ResponseValidationTests(ContextCase):
    def test_valid_relation_uses_exact_candidate_ref_and_source_quote(self):
        result = self.response()
        self.assertIs(cc.validate_response(result, self.snapshot(), self.source.read_text()), result)
        evidence = result["events"][0]["timeline_relation"]["evidence"]
        self.assertEqual(
            self.source.read_text()[evidence["start"]:evidence["end"]],
            evidence["quote"],
        )

    def test_unknown_candidate_invalid_ref_and_bad_quote_are_rejected(self):
        cases = []
        unknown = self.response()
        unknown["events"][0]["timeline_relation"]["candidate_id"] = "node:invented"
        cases.append(unknown)
        invalid_ref = self.response()
        invalid_ref["events"][0]["timeline_relation"]["entity_refs"] = ["place/invented"]
        cases.append(invalid_ref)
        bad_quote = self.response()
        bad_quote["events"][0]["timeline_relation"]["evidence"]["quote"] = "words never written"
        cases.append(bad_quote)
        for result in cases:
            with self.subTest(result=result):
                with self.assertRaises(cc.ClassifierContextError):
                    cc.validate_response(result, self.snapshot(), self.source.read_text())

    def test_long_multibyte_source_derives_offsets_without_model_counting(self):
        prefix = ("Long source material. " * 900) + "Caf\u00e9 memories: "
        quote = "while we lived in Cedarport"
        self.source.write_text(prefix + quote + ".", encoding="utf-8")
        snapshot = self.snapshot()
        result = self.response(snapshot)
        evidence = result["events"][0]["timeline_relation"]["evidence"]
        self.assertNotIn("start", evidence)
        cc.validate_response(result, snapshot, self.source.read_text())
        self.assertEqual(evidence["start"], len(prefix))
        self.assertEqual(evidence["end"], len(prefix) + len(quote))

    def test_duplicate_exact_quote_is_rejected_as_ambiguous(self):
        sentence = "I found the letter while we lived in Cedarport."
        self.source.write_text(sentence + " Later, " + sentence, encoding="utf-8")
        snapshot = self.snapshot()
        with self.assertRaisesRegex(cc.ClassifierContextError, "ambiguous"):
            cc.validate_response(self.response(snapshot), snapshot, self.source.read_text())

    def test_source_or_context_race_rejects_the_old_response(self):
        old = self.snapshot()
        result = self.response(old)
        self.write_projection([node() | {"conflict_state": "contradicted"}])
        with self.assertRaises(cc.ClassifierContextError):
            cc.validate_response(result, self.snapshot(), self.source.read_text())

    def test_relation_is_refused_when_competing_context_is_truncated(self):
        self.write_projection([node(), node("node:second", "2002/2004", "claim:second")])
        snapshot = cc.build_context_snapshot(self.root, self.source, max_candidates=1)
        self.assertTrue(snapshot["context_truncated"])
        result = self.response(snapshot)
        with self.assertRaises(cc.ClassifierContextError):
            cc.validate_response(result, snapshot, self.source.read_text())

    def test_relation_is_refused_for_ambiguous_raw_subject_label(self):
        roster_dir = self.root / "state" / "entity_rosters"
        roster_dir.mkdir(parents=True)
        (roster_dir / "place.json").write_text(json.dumps({
            "version": 1,
            "type": "place",
            "entities": [
                {"name": "North Ranch", "slug": "north-ranch", "aliases": ["The Ranch"]},
                {"name": "South Ranch", "slug": "south-ranch", "aliases": ["The Ranch"]},
            ],
        }), encoding="utf-8")
        self.source.write_text("We lived at The Ranch.", encoding="utf-8")
        target = node("node:ranch", "1990/1992", "claim:ranch") | {
            "episode_id": None,
            "subject_refs": ["The Ranch", "self"],
        }
        self.write_projection([target])
        snapshot = self.snapshot()
        result = {
            "_classification_snapshot": cc.snapshot_metadata(snapshot),
            "events": [{
                "title": "Life at the ranch",
                "description": "We lived at The Ranch.",
                "timeline_relation": {
                    "relation": "within",
                    "candidate_id": "node:ranch",
                    "entity_refs": ["self"],
                    "evidence": {"quote": "We lived at The Ranch"},
                },
            }],
        }

        with self.assertRaisesRegex(cc.ClassifierContextError, "ambiguous"):
            cc.validate_response(result, snapshot, self.source.read_text())

    def test_repeated_stays_require_disambiguating_event_local_refs(self):
        second = node("node:second", "2002/2004", "claim:second") | {
            "episode_id": "episode:second",
        }
        self.write_projection([node(), second])
        snapshot = self.snapshot()
        result = self.response(snapshot)
        with self.assertRaises(cc.ClassifierContextError):
            cc.validate_response(result, snapshot, self.source.read_text())

        self.write_projection([node()])
        old = self.snapshot()
        result = self.response(old)
        self.source.write_text(self.source.read_text() + "\nNew source text.", encoding="utf-8")
        with self.assertRaises(cc.ClassifierContextError):
            cc.validate_response(result, self.snapshot(), self.source.read_text())

    def test_direct_date_and_context_relation_may_coexist(self):
        result = self.response()
        result["events"][0]["date"] = {"stated": "1999", "age": None}
        cc.validate_response(result, self.snapshot(), self.source.read_text())

    def test_failed_refresh_preserves_the_current_classification(self):
        classifications = self.root / "state" / "classifications"
        classifications.mkdir(parents=True, exist_ok=True)
        path = classifications / "sources-manual-story.json"
        existing = {
            "version": 2,
            "source_path": "sources/manual/story.md",
            "events": [{"description": "the prior accepted event"}],
            "classification_snapshot": cc.snapshot_metadata(self.snapshot()),
        }
        path.write_text(json.dumps(existing, sort_keys=True), encoding="utf-8")
        before = path.read_bytes()
        stale_response = self.response()
        self.write_projection([node(value="2005/2008")])
        with mock.patch.object(classify_story, "REPO_DIR", self.root), \
                mock.patch.object(classify_story, "CLASSIFICATIONS_DIR", classifications), \
                mock.patch.object(
                    classify_story,
                    "QUESTION_CANDIDATES_FILE",
                    self.root / "state" / "question_candidates.json",
                ):
            self.assertEqual(
                classify_story.classify_file(
                    self.source,
                    "external-agent",
                    skip_candidates=True,
                    precomputed_result=stale_response,
                ),
                1,
            )
        self.assertEqual(path.read_bytes(), before)


class ContextDiagnosticsTests(ContextCase):
    CANARY = "SYNTHETIC_PRIVATE_CANARY_never_log"

    def failure_cases(self):
        code = cc.ContextFailureCode
        snap = self.snapshot()
        response = self.response(snap)
        response["events"][0]["description"] = self.CANARY
        relation = ("events", 0, "timeline_relation")
        candidate = ("candidates", 0)
        missing = object()
        cases = [
            ("response", code.RESPONSE_NOT_MAPPING, "response", (), []),
            ("missing_snapshot", code.SNAPSHOT_MISMATCH, "response",
             ("_classification_snapshot",), missing),
            ("events", code.EVENTS_NOT_LIST, "response", ("events",), {}),
            ("event", code.EVENT_NOT_MAPPING, "response", ("events", 0), self.CANARY),
            ("relation_shape", code.RELATION_INVALID, "response", relation, []),
            ("relation_kind", code.RELATION_INVALID, "response",
             (*relation, "relation"), self.CANARY),
            ("candidate", code.CANDIDATE_UNKNOWN, "response",
             (*relation, "candidate_id"), self.CANARY),
            ("truncated", code.CONTEXT_INCOMPLETE, "snapshot", ("context_truncated",), True),
            ("incomplete_candidate", code.CONTEXT_INCOMPLETE, "snapshot",
             (*candidate, "candidate_set_complete"), False),
            ("unresolved", code.CANDIDATE_AMBIGUOUS, "snapshot",
             (*candidate, "unresolved_entity_mentions"), [self.CANARY]),
            ("ambiguous", code.CANDIDATE_AMBIGUOUS, "snapshot",
             (*candidate, "entity_ref_ambiguities"), [{"mention": self.CANARY}]),
            ("evidence", code.EVIDENCE_NOT_MAPPING, "response",
             (*relation, "evidence"), None),
            ("quote_empty", code.QUOTE_MISSING, "response",
             (*relation, "evidence", "quote"), ""),
            ("quote_type", code.QUOTE_MISSING, "response",
             (*relation, "evidence", "quote"), [self.CANARY]),
            ("quote_absent", code.QUOTE_NOT_FOUND, "response",
             (*relation, "evidence", "quote"), self.CANARY),
            ("quote_whitespace", code.QUOTE_NOT_EXACT, "response",
             (*relation, "evidence", "quote"), "while  we lived in Cedarport"),
            ("quote_repeated", code.QUOTE_AMBIGUOUS, "story", (),
             self.source.read_text() + " Again, while we lived in Cedarport."),
            ("refs_empty", code.ENTITY_REFS_INVALID, "response",
             (*relation, "entity_refs"), []),
            ("refs_null", code.ENTITY_REFS_INVALID, "response",
             (*relation, "entity_refs"), None),
            ("refs_missing", code.ENTITY_REFS_INVALID, "response",
             (*relation, "entity_refs"), missing),
            ("refs_type", code.ENTITY_REFS_INVALID, "response",
             (*relation, "entity_refs"), "place/cedarport"),
            ("refs_unknown", code.ENTITY_REFS_INVALID, "response",
             (*relation, "entity_refs"), [self.CANARY]),
            ("refs_competing", code.CANDIDATE_NOT_DISAMBIGUATED, "snapshot",
             ("candidates",), [snap["candidates"][0],
                              snap["candidates"][0] | {"candidate_id": "node:second"}]),
            ("event_key", code.EVENT_KEYS_INVALID, "response",
             ("events", 0, "event_key"), "0" * 12),
            ("grounding", code.GROUNDING_INVALID, "response",
             ("events", 0, "source_grounding"), {
                 "quote": "while we lived in Cedarport",
                 "temporal_quote": "Cedarport",
                 "subject_quote": "Cedarport",
                 "kind": "date",
             }),
            ("resolution", code.RESOLUTION_INVALID, "response",
             ("events", 0, "timeline_resolution"), {
                 "status": "invented",
                 "candidate_ids": ["node:stay"],
                 "reason": "Synthetic invalid status.",
             }),
            ("within_a_point", code.RELATION_SHAPE_INVALID, "snapshot",
             (*candidate, "temporal_shape"), "point"),
        ]
        for key in cc.SNAPSHOT_KEYS:
            cases.append((f"changed_{key}", code.SNAPSHOT_MISMATCH, "response",
                          ("_classification_snapshot", key), self.CANARY))
        for name, expected, target, path, value in cases:
            data = {"snapshot": deepcopy(snap), "response": deepcopy(response),
                    "story": self.source.read_text()}
            if path:
                parent = data[target]
                for key in path[:-1]:
                    parent = parent[key]
                if value is missing:
                    del parent[path[-1]]
                else:
                    parent[path[-1]] = deepcopy(value)
            else:
                data[target] = deepcopy(value)
            yield name, expected, data

    def test_every_rejection_has_exact_bounded_content_free_metadata(self):
        observed = set()
        for name, code, data in self.failure_cases():
            with self.subTest(case=name):
                with self.assertRaises(cc.ClassifierContextError) as raised:
                    cc.validate_response(data["response"], data["snapshot"], data["story"])
                exc = raised.exception
                self.assertIsInstance(exc, ValueError)
                self.assertIs(exc.code, code)
                observed.add(code)
                self.assertLessEqual(len(code.value), 64)
                self.assertRegex(code.value, r"^context_[a-z_]+$")
                self.assertEqual(
                    failure_metadata("classify-schema", exc),
                    "provider=ai operation=classify-schema "
                    f"failure=ClassifierContextError status={code.value}",
                )
        self.assertEqual(observed, set(cc.ContextFailureCode))

    def test_exception_text_and_untyped_codes_never_enter_metadata(self):
        for code in cc.ContextFailureCode:
            exc = cc.ClassifierContextError(self.CANARY, code=code)
            self.assertNotIn(self.CANARY, failure_metadata("classify-schema", exc))
        with self.assertRaises(ValueError) as raised:
            cc.ClassifierContextError(self.CANARY, code=self.CANARY)
        self.assertNotIn(self.CANARY, str(raised.exception))
        lookalike = ValueError(self.CANARY)
        lookalike.code = self.CANARY
        lookalike.status = self.CANARY
        self.assertEqual(
            failure_metadata("classify-schema", lookalike),
            "provider=ai operation=classify-schema failure=ValueError status=failed",
        )

    def test_all_failures_surface_on_stderr_before_any_persistence(self):
        classifications = self.root / "state" / "classifications"
        classifications.mkdir()
        prior = classifications / "sources-manual-story.json"
        prior.write_text(json.dumps({
            "stale": True,
            "events": [{"description": "Prior accepted reading"}],
        }))
        candidates = self.root / "state" / "question_candidates.json"
        candidates.write_text(json.dumps({"candidates": [{"id": "synthetic-prior"}]}))
        before = prior.read_bytes(), candidates.read_bytes()
        for name, code, data in self.failure_cases():
            with self.subTest(case=name), \
                    mock.patch.object(classify_story, "REPO_DIR", self.root), \
                    mock.patch.object(classify_story, "CLASSIFICATIONS_DIR", classifications), \
                    mock.patch.object(classify_story, "QUESTION_CANDIDATES_FILE", candidates), \
                    mock.patch.object(classify_story, "load_source_text",
                                      return_value=({}, data["story"])), \
                    mock.patch.object(cc, "build_context_snapshot", return_value=data["snapshot"]), \
                    redirect_stderr(io.StringIO()) as err, redirect_stdout(io.StringIO()) as out:
                self.assertEqual(classify_story.classify_file(
                    self.source, "synthetic-recorded", precomputed_result=data["response"],
                ), 1)
                self.assertEqual(out.getvalue(), "")
                self.assertEqual(
                    err.getvalue(),
                    "Error: AI classification schema failed: provider=ai "
                    "operation=classify-schema failure=ClassifierContextError "
                    f"status={code.value}\n",
                )
                self.assertEqual((prior.read_bytes(), candidates.read_bytes()), before)
                self.assertEqual(list(classifications.iterdir()), [prior])

    def test_valid_then_invalid_event_does_not_partially_file_or_drop_relation(self):
        response = self.response()
        invalid = deepcopy(response["events"][0])
        invalid["timeline_relation"]["entity_refs"] = []
        response["events"].append(invalid)
        prior = self.root / "state" / "prior.json"
        prior.write_text('{"events": [{"description": "Prior accepted reading"}]}')
        before = prior.read_bytes()
        with mock.patch.object(classify_story, "REPO_DIR", self.root), \
                mock.patch.object(classify_story, "classification_path", return_value=prior), \
                mock.patch.object(classify_story, "save_candidate_store") as save_candidates, \
                redirect_stderr(io.StringIO()) as err:
            self.assertEqual(classify_story.classify_file(
                self.source, "synthetic-recorded", precomputed_result=response,
            ), 1)
        self.assertIn("status=context_entity_refs_invalid", err.getvalue())
        self.assertEqual(prior.read_bytes(), before)
        self.assertEqual(len(response["events"]), 2)
        self.assertEqual(response["events"][1]["timeline_relation"]["entity_refs"], [])
        self.assertEqual(response["events"][1]["timeline_relation"]["candidate_id"], "node:stay")
        save_candidates.assert_not_called()

    def test_null_relation_files_event_and_direct_date_without_a_model_call(self):
        self.source.write_text("In 1999 I found the letter while we lived in Cedarport.")
        result = self.response()
        event = result["events"][0]
        event["timeline_relation"] = None
        event["date"] = {"stated": "1999", "age": None}
        unchanged = deepcopy(result)
        classifications = self.root / "state" / "classifications"
        candidates = self.root / "state" / "question_candidates.json"
        with mock.patch.object(classify_story, "REPO_DIR", self.root), \
                mock.patch.object(classify_story, "CLASSIFICATIONS_DIR", classifications), \
                mock.patch.object(classify_story, "QUESTION_CANDIDATES_FILE", candidates), \
                mock.patch.object(classify_story, "classify_with_ai") as model, \
                redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()) as err:
            self.assertEqual(classify_story.classify_file(
                self.source, "synthetic-recorded", precomputed_result=result,
            ), 0)
            saved = json.loads(classify_story.classification_path(self.source).read_text())
        self.assertEqual(err.getvalue(), "")
        self.assertEqual(saved["events"], [event])
        self.assertEqual(
            {key: result[key] for key in result if key != "events"},
            {key: unchanged[key] for key in unchanged if key != "events"},
        )
        self.assertEqual(result["events"][0]["title"], unchanged["events"][0]["title"])
        self.assertIsNone(result["events"][0]["source_grounding"])
        self.assertEqual(
            result["events"][0]["timeline_resolution"]["status"], "missing_evidence"
        )
        self.assertIsNone(cc.refresh_reason(self.snapshot(), saved))
        model.assert_not_called()

    def test_prompt_explicitly_covers_existing_eligibility_and_abstention(self):
        prompt = classify_story.build_prompt(
            self.source, {}, self.source.read_text(), context_snapshot=self.snapshot(),
        )
        text = " ".join(prompt.split())
        for rule in (
            '"event_contexts"',
            "compute this event's relevant candidates from its own source-grounded",
            "Specific names, aliases, entity refs, and reference keys win",
            "The provisional full-extraction context is retrieval input",
            "no `unresolved_entity_mentions` and no `entity_ref_ambiguities`",
            "`entity_refs` must be a nonempty list of exact refs supplied on THAT candidate",
            "the exact source quote must distinguish the selected role or stay",
            "one exact, unchanged substring of Story Text occurring exactly once",
            "empty, null, or missing entity refs",
            "return the WHOLE `timeline_relation` as null",
            "Keep the event and its independently stated date or age",
            "This list is event-local, not the entire catalog",
            "Timeline Evidence Uses Two Independent Decisions",
            "does NOT need a calendar date or age",
            "an empty candidate set for a real event is `missing_evidence`",
            "`incomplete` is allowed ONLY",
            "A supported rough `before` or `after` placement is also valid",
            "do not invent `within` merely to tighten bounds",
            "preserve the supported `before` relation",
            "CURRENT EXTRACTED EVENT relative to SELECTED CANDIDATE",
            "candidate's WHOLE occurrence",
            "before it starts",
            "after it ends",
            '"early in", and "late in"',
            '"two weeks after the wedding" are both `after`',
            "`temporal_shape`",
            "`within` a point is refused",
            "date.anchor_ref",
            f"1-{timeline_evidence.MAX_RESOLUTION_REASON_CHARS} character explanation",
            f"{timeline_evidence.MAX_RESOLUTION_REASON_CHARS} characters",
        ):
            with self.subTest(rule=rule):
                self.assertIn(rule, text)
        self.assertNotIn("across the ENTIRE supplied candidate list", text)
        self.assertNotIn("TIGHTEST SUPPORTED TIME BOUNDS", text)
        self.assertNotIn("`context_truncated` must be false", text)

    def test_v2_accepted_relations_and_null_relations_remain_current(self):
        snapshot = self.snapshot()
        self.assertEqual(snapshot["prompt_version"], "contextual-timeline:3")
        self.assertEqual(snapshot["extractor_version"], "story-classifier:2")
        self.assertEqual(snapshot["schema_version"], 1)
        for relation in ("within", "before", "after", None):
            result = self.response(snapshot)
            event = result["events"][0]
            event["date"] = {"stated": "1999", "age": None}
            if relation is None:
                event["timeline_relation"] = None
            else:
                event["timeline_relation"]["relation"] = relation
            with self.subTest(relation=relation):
                self.assertIs(cc.validate_response(result, snapshot, self.source.read_text()), result)
                self.assertEqual(event["date"], {"stated": "1999", "age": None})
                self.assertEqual(event["title"], "Finding the letter")
                self.assertIsNone(cc.refresh_reason(snapshot, {
                    "classification_snapshot": result["_classification_snapshot"],
                }))


class TellingIdentityIntegrationTests(ContextCase):
    def test_legacy_rule_one_refresh_without_stable_evidence_preserves_binding(self):
        classifications = self.root / "state" / "classifications"
        classifications.mkdir(parents=True, exist_ok=True)
        path = classifications / "sources-manual-story.json"
        body = "Two synthetic moments in one unchanged source.\n"
        metadata = {
            "title": "story",
            "type": "story",
            "source_id": "story:legacy-refresh",
            "source_path": "sources/manual/story.md",
            "content_sha256": temporal_store.payload_sha256(body),
        }
        self.source.write_text(
            f"{temporal_store.format_frontmatter(metadata)}\n\n{body}", encoding="utf-8"
        )
        legacy = {
            "version": 1,
            "source_path": "sources/manual/story.md",
            "places": ["Cedarport"],
            "events": [{
                "title": "A quiet afternoon",
                "description": "Old quiet wording.",
                "date": None,
            }],
        }
        legacy_event = legacy["events"][0]
        revision = classifier_claims.classification_revision(legacy)
        old_extractor = temporal_claims.extractor_version_string(
            classifier_claims.EXTRACTOR_NAME, rule_version="1"
        )
        old_ref = event_identity.classifier_telling_ref(path.stem, legacy_event)
        old_claim = temporal_claims.validate_temporal_claim({
            "source_ref": classifier_claims.event_source_ref(
                stem=path.stem,
                event=legacy_event,
                revision=revision,
                source_path="sources/manual/story.md",
            ),
            "source_kind": classifier_claims.SOURCE_KIND,
            "claim_type": temporal_claims.OCCURRENCE_CLAIM_TYPE,
            "subject_mention": "self",
            "event_kind": classifier_claims.MOMENT_EVENT_KIND,
            "event_ref": temporal_projection.derive_node_id(
                node_kind="event",
                event_kind=classifier_claims.MOMENT_EVENT_KIND,
                subject_refs=["self"],
                discriminator=classifier_claims.event_key(legacy_event),
            ),
            "event_mention": legacy_event["title"],
            "temporal_value": None,
            "evidence": [{"quote": legacy_event["description"]}],
            "basis": "explicit",
            "confidence": classifier_claims.OCCURRENCE_CLAIM_CONFIDENCE,
            "extractor_version": old_extractor,
            "place_mentions": list(legacy["places"]),
        }, now="2026-09-15T00:30:00Z")
        temporal_store.write_receipt(self.root, {
            "source_ref": old_claim["source_ref"],
            "extractor_version": old_extractor,
            "extractor": event_identity.declare_tellings(
                {
                    "name": classifier_claims.EXTRACTOR_NAME,
                    "rule_version": "1",
                    "deterministic": True,
                },
                telling_keys={old_claim["claim_id"]: old_ref},
                document_revision=classifier_claims.document_revision(
                    self.root, "sources/manual/story.md"
                ),
            ),
            "claims": [old_claim],
        }, now="2026-09-15T00:30:00Z")
        temporal_store.rebuild_active_index(self.root)
        event_identity.rebuild_telling_manifest(self.root)
        record, _created = event_identity.file_event_identity(
            self.root,
            telling_ref=old_ref,
            episode_id="episode:" + "e" * 24,
            relation="related",
            origin="confirmed",
            source_ref="sources/identity/legacy-review.md",
            created_at="2026-09-15T00:45:00Z",
        )
        binding_path = self.root / record["relative_path"]
        binding_bytes = binding_path.read_bytes()
        refreshed = {
            "version": 2,
            "source_path": "sources/manual/story.md",
            "places": ["Northport"],
            "events": [{
                "title": "A different evening",
                "description": "A wholly different reading.",
                "date": None,
            }],
        }
        path.write_text(json.dumps(refreshed), encoding="utf-8")
        with mock.patch.object(classify_story, "CLASSIFICATIONS_DIR", classifications):
            classifier_claims.migrate_classifier_moments(
                self.root, publish=False, dry_run=False,
                now="2026-09-15T01:00:00Z",
            )

        manifest = event_identity.read_telling_manifest(self.root)
        rows = {row["telling_ref"]: row for row in manifest["tellings"]}
        active = [row for row in rows.values() if row["status"] == "active"]
        self.assertFalse(any(old_ref in row["aliases"] for row in active))
        self.assertEqual(rows[old_ref]["bound_identity_ids"], [record["identity_id"]])
        self.assertEqual(rows[old_ref]["rekey_case"], "reworded")
        self.assertIn(
            event_identity.REKEY_DIAGNOSTIC,
            [row["finding"] for row in manifest["diagnostics"]],
        )
        self.assertEqual(binding_path.read_bytes(), binding_bytes)

    def test_multi_event_rewording_preserves_manual_binding_and_node_count(self):
        classifications = self.root / "state" / "classifications"
        classifications.mkdir(parents=True, exist_ok=True)
        path = classifications / "sources-manual-story.json"
        story_body = (
            "I found the letter while we lived in Cedarport. "
            "I learned piano while we lived in Cedarport.\n"
        )
        metadata = {
            "title": "story",
            "type": "story",
            "source_id": "story:manual-story",
            "source_path": "sources/manual/story.md",
            "content_sha256": temporal_store.payload_sha256(story_body),
        }
        self.source.write_text(
            f"{temporal_store.format_frontmatter(metadata)}\n\n{story_body}",
            encoding="utf-8",
        )

        def event(title, description, quote):
            start = self.source.read_text(encoding="utf-8").index(quote)
            return {
                "title": title,
                "description": description,
                "date": None,
                "places": ["Cedarport"],
                "timeline_relation": {
                    "relation": "within",
                    "candidate_id": "node:stay",
                    "entity_refs": ["place/cedarport"],
                    "evidence": {
                        "quote": quote,
                        "start": start,
                        "end": start + len(quote),
                    },
                },
            }

        def write(first_description, second_description):
            path.write_text(json.dumps({
                "version": 2,
                "source_path": "sources/manual/story.md",
                "events": [
                    event(
                        "Finding the letter", first_description,
                        "I found the letter while we lived in Cedarport",
                    ),
                    event(
                        "Learning piano", second_description,
                        "I learned piano while we lived in Cedarport",
                    ),
                ],
            }), encoding="utf-8")

        with mock.patch.object(classify_story, "CLASSIFICATIONS_DIR", classifications):
            write("I discovered the letter.", "I began piano lessons.")
            classifier_claims.migrate_classifier_moments(
                self.root, publish=False, dry_run=False,
                now="2026-09-15T01:00:00Z",
            )

            first_event = json.loads(path.read_text(encoding="utf-8"))["events"][0]
            old_ref = event_identity.classifier_telling_ref(path.stem, first_event)
            operation_id = event_identity.operation_digest(
                authority="human",
                op="create",
                rule_version=event_identity.IDENTITY_RULE_VERSION,
                member_refs=[old_ref],
            )
            episode_id = event_identity.episode_id_for(operation_id)
            binding = {
                "telling_ref": old_ref,
                "episode_id": episode_id,
                "relation": "same",
                "origin": "confirmed",
                "operation_id": operation_id,
                "source_ref": "sources/identity/manual-decision.md",
                "created_at": "2026-09-15T01:30:00Z",
            }
            binding_id = event_identity.validate_event_identity(binding)["identity_id"]
            event_identity.file_operation_envelope(
                self.root,
                operation={
                    "authority": "human",
                    "op": "create",
                    "episode_id": episode_id,
                    "members": [old_ref],
                    "creates_binding_ids": [binding_id],
                    "canonical_event_kind": "moment",
                    "source_ref": "sources/identity/manual-decision.md",
                    "created_at": "2026-09-15T01:30:00Z",
                },
                bindings=[binding],
            )
            event_identity.rebuild_telling_manifest(self.root)
            filed = event_identity.load_event_identities(self.root)[0]
            binding_path = self.root / filed["relative_path"]
            binding_bytes = binding_path.read_bytes()
            before = temporal_timeline.derive_calculated_timeline(
                temporal_store.fold_active_index(self.root),
                episode_records=episode_fold.load_episode_records(self.root),
                now="2026-09-15T01:45:00Z",
            )

            write("I came across the old letter.", "I started learning the piano.")
            classifier_claims.migrate_classifier_moments(
                self.root, publish=False, dry_run=False,
                now="2026-09-15T02:00:00Z",
            )

        manifest = event_identity.read_telling_manifest(self.root)
        active = [row for row in manifest["tellings"] if row["status"] == "active"]
        successor = next(row for row in active if old_ref in row["aliases"])
        self.assertEqual(successor["bound_identity_ids"], [binding_id])
        self.assertEqual(
            next(row for row in manifest["tellings"] if row["telling_ref"] == old_ref)[
                "superseded_by"
            ],
            [successor["telling_ref"]],
        )
        self.assertEqual(binding_path.read_bytes(), binding_bytes)

        after = temporal_timeline.derive_calculated_timeline(
            temporal_store.fold_active_index(self.root),
            episode_records=episode_fold.load_episode_records(self.root),
            now="2026-09-15T02:15:00Z",
        )
        self.assertEqual(len(before.nodes), 2)
        self.assertEqual(len(after.nodes), 2)
        episode_node = next(row for row in after.nodes if row.get("episode_id") == episode_id)
        self.assertEqual(episode_node["telling_count"], 1)
        self.assertEqual(episode_node["tellings"], [successor["telling_ref"]])

        snapshot = self.snapshot()
        identities = snapshot["prior_event_identities"]
        self.assertTrue(any(old_ref in row["aliases"] for row in identities), identities)
        before = snapshot["context_digest"]
        manifest = event_identity.read_telling_manifest(self.root)
        self.assertIsNotNone(manifest)
        # Prior machine telling ids are useful prompt context, but changing that
        # derived cache alone cannot invalidate the classifier.
        manifest["tellings"][0]["aliases"].append("classification:legacy#cccccccccccc")
        event_identity.write_telling_manifest(self.root, manifest)
        self.assertEqual(self.snapshot()["context_digest"], before)


class ProductionPipelineAcceptanceTests(ContextCase):
    def setUp(self):
        super().setUp()
        self.fold_patch.stop()

    def test_landmark_refresh_to_published_usable_window_retires_generic_item(self):
        body = "I found the envelope while we lived in Cedarport.\n"
        metadata = {
            "title": "envelope",
            "type": "story",
            "source_id": "story:cedarport-envelope",
            "source_path": "sources/manual/story.md",
            "content_sha256": temporal_store.payload_sha256(body),
        }
        self.source.write_text(
            f"{temporal_store.format_frontmatter(metadata)}\n\n{body}", encoding="utf-8"
        )
        roster_dir = self.root / "state" / "entity_rosters"
        roster_dir.mkdir(parents=True)
        place_roster = {
            "version": 1,
            "type": "place",
            "entities": [{"name": "Cedarport", "slug": "cedarport", "aliases": []}],
        }
        (roster_dir / "place.json").write_text(json.dumps(place_roster), encoding="utf-8")
        self.write_projection([])

        classifications = self.root / "state" / "classifications"
        classifications.mkdir(parents=True, exist_ok=True)
        old_snapshot = self.snapshot()
        classification_path = classifications / "sources-manual-story.json"
        classification_path.write_text(json.dumps({
            "version": 2,
            "source_path": "sources/manual/story.md",
            "events": [{"title": "Envelope", "description": "An earlier reading."}],
            "classification_snapshot": cc.snapshot_metadata(old_snapshot),
        }), encoding="utf-8")

        landmark_projection.file_landmark_record(
            self.root,
            "residences",
            {
                "domain": "residences",
                "label": "Cedarport",
                "city": "Cedarport",
                "span": {"start": date("1994"), "end": date("1998")},
            },
            ordinal=1,
            now="2026-09-15T03:00:00Z",
        )
        temporal_publication.publish(
            self.root,
            roster_snapshot=entity_roster.load_roster("person", vault_root=self.root),
            now="2026-09-15T03:01:00Z",
        )

        report = cc.select_refresh_targets(self.root, [self.source], limit=1)
        self.assertEqual(report["targets"][0]["reason"], "context_changed")

        tasks = self.root / "agent_tasks" / "classify"
        candidate_store = self.root / "state" / "question_candidates.json"
        with mock.patch.object(classify_story, "REPO_DIR", self.root), \
                mock.patch.object(classify_story, "CLASSIFICATIONS_DIR", classifications), \
                mock.patch.object(classify_story, "QUESTION_CANDIDATES_FILE", candidate_store):
            self.assertEqual(classify_story.emit_prompts([self.source], tasks), 0)
            task_manifest = json.loads((tasks / "manifest.json").read_text(encoding="utf-8"))
            task = task_manifest["items"][0]
            prompt = (tasks / task["prompt"]).read_text(encoding="utf-8")
            self.assertIn('"candidate_id":', prompt)
            snapshot = self.snapshot()
            stay = next(
                row for row in snapshot["candidates"]
                if row["kind"] == "residence"
            )
            response_path = tasks / task["response"]
            prior_event = json.loads(classification_path.read_text())["events"][0]
            response_path.write_text(json.dumps({
                "_classification_mode": "timeline",
                "_classification_snapshot": task["classification_snapshot"],
                "events": [{
                    "event_key": timeline_evidence.event_key(prior_event),
                    "source_grounding": None,
                    "timeline_relation": {
                        "relation": "within",
                        "candidate_id": stay["candidate_id"],
                        "entity_refs": ["place/cedarport"],
                        "evidence": {"quote": "while we lived in Cedarport"},
                    },
                    "timeline_resolution": {
                        "status": "linked",
                        "candidate_ids": list(
                            next(iter(snapshot["event_contexts"].values()))["candidate_ids"]
                        ),
                        "reason": "The source quote names the supplied residence.",
                    },
                }],
            }), encoding="utf-8")
            args = mock.Mock(
                source="sources/manual/story.md",
                from_response=str(response_path),
                model=None,
                dry_run=False,
                verbose=False,
                no_candidates=True,
            )
            self.assertEqual(classify_story.cmd_from_response(args), 0)

        classifier_claims.migrate_classifier_moments(
            self.root,
            classifications_dir=classifications,
            sources=["sources/manual/story.md"],
            publish=False,
            dry_run=False,
            now="2026-09-15T03:02:00Z",
        )
        temporal_publication.publish(
            self.root,
            roster_snapshot=entity_roster.load_roster("person", vault_root=self.root),
            now="2026-09-15T03:03:00Z",
        )
        view = temporal_publication.calculated_view(self.root)
        event_node = next(row for row in view["nodes"] if row.get("event_kind") == "moment")
        window = event_node.get("best_temporal_value") or event_node.get(
            "possible_temporal_value"
        )
        self.assertEqual(window["earliest"], "1994")
        self.assertEqual(window["latest"], "1998")
        self.assertEqual(window["basis"], "anchor")
        self.assertTrue(event_node["usable_placement"])
        work_items = temporal_publication.read_work_items(self.root)["work_items"]
        self.assertFalse(any(row.get("node_ref") == event_node["node_id"] for row in work_items))


class OwnerRecordIdentityTests(ContextCase):
    """An owner-scoped record named by its own label is the owner's, not a stranger's."""

    def record(self, label="Brightline Labs", scope="owner", event_kind="job", **extra):
        row = node("node:record", "2019/2021", "claim:record") | {
            "label": label, "event_kind": event_kind, "episode_id": None,
            "subject_refs": [label], "legacy_refs": [],
            "occurrence_subject_scope": scope,
        }
        row.update(extra)
        return row

    def test_an_owner_scoped_record_named_by_its_label_is_the_owners(self):
        row = cc._candidate(self.record(), roster_aliases={}, rosters={})
        self.assertEqual(row["entity_refs"], ["self"])
        self.assertEqual(row["unresolved_entity_mentions"], [])
        self.assertTrue(cc.candidate_identity_is_resolved(row))
        self.assertEqual(row["name"], "Brightline Labs")

    def test_a_person_mention_that_is_not_the_label_stays_unresolved(self):
        row = cc._candidate(
            self.record(label="Dad graduated", event_kind="graduation", subject_refs=["Dad"]),
            roster_aliases={}, rosters={},
        )
        self.assertEqual(row["entity_refs"], [])
        self.assertEqual(row["unresolved_entity_mentions"], ["Dad"])

    def test_an_other_person_scope_is_never_rewritten(self):
        row = cc._candidate(self.record(scope="other_person"), roster_aliases={}, rosters={})
        self.assertEqual(row["entity_refs"], [])
        self.assertEqual(row["unresolved_entity_mentions"], ["Brightline Labs"])


class TemporalShapeTests(ContextCase):
    """`within` attaches to a duration; a wedding day has no inside."""

    def test_shape_follows_role_then_bounds(self):
        day = {"granularity": "day", "earliest": "2007-01-11", "latest": "2007-01-11"}
        self.assertEqual(cc.temporal_shape("episode", "married", day), "point")
        self.assertEqual(cc.temporal_shape(
            "episode", "married", {"granularity": "range", "earliest": "2007", "latest": "2010"}
        ), "point")
        # A day-dated founding still has a week inside it: shape follows the
        # role, never the precision.
        self.assertEqual(cc.temporal_shape("event", "moment", day), "interval")
        self.assertEqual(cc.temporal_shape("event", "founded", day), "interval")
        self.assertEqual(cc.temporal_shape(
            "episode", "job", {"granularity": "month", "earliest": "2022-05", "latest": "2022-05"}
        ), "interval")
        self.assertEqual(cc.temporal_shape(
            "episode", "residence", {"granularity": "range", "earliest": "1998", "latest": "2001"}
        ), "interval")
        self.assertEqual(cc.temporal_shape("period", "named_era", day), "interval")

    def test_within_a_wedding_day_is_refused_and_after_is_accepted(self):
        wedding = node("node:wedding", "2007-01-11", "claim:wedding") | {
            "label": "Married Pat", "event_kind": "married", "episode_id": None,
            "subject_refs": ["self"], "legacy_refs": ["wedding"],
            "occurrence_subject_scope": "owner",
        }
        wedding["best_temporal_value"]["granularity"] = "day"
        self.write_projection([wedding])
        self.source.write_text("Early in my marriage, I went bankrupt.", encoding="utf-8")
        snapshot = self.snapshot()
        self.assertEqual(snapshot["candidates"][0]["temporal_shape"], "point")

        def response(relation):
            return {
                "_classification_snapshot": cc.snapshot_metadata(snapshot),
                "events": [{
                    "title": "Bankruptcy",
                    "description": "Early in my marriage, I went bankrupt.",
                    "places": [],
                    "timeline_relation": {
                        "relation": relation,
                        "candidate_id": "node:wedding",
                        "entity_refs": ["self"],
                        "evidence": {"quote": "Early in my marriage"},
                    },
                }],
            }

        with self.assertRaises(cc.ClassifierContextError) as raised:
            cc.validate_response(response("within"), snapshot, self.source.read_text())
        self.assertIs(raised.exception.code, cc.ContextFailureCode.RELATION_SHAPE_INVALID)
        cc.validate_response(response("after"), snapshot, self.source.read_text())


class SalvageValidationTests(ContextCase):
    """Under salvage one bad event field falls to its conservative state; the response survives."""

    def test_the_batch_filer_salvages_only_when_the_local_loop_asks(self):
        import inspect

        import classification_refresh as cr
        import classify_story as cs

        self.assertIs(inspect.signature(cs.file_batch_response).parameters["salvage"].default, False)
        self.assertIn("file_batch_response(envelope, model=selected_model, salvage=True)",
                      inspect.getsource(cr.run_batch))

    def test_grounding_failure_downgrades_to_null(self):
        snapshot = self.snapshot()
        result = self.response(snapshot)
        result["events"][0]["source_grounding"] = {
            "quote": "while we lived in Cedarport", "temporal_quote": "Cedarport",
            "subject_quote": "Cedarport", "kind": "date",
        }
        with self.assertRaises(cc.ClassifierContextError):
            cc.validate_response(deepcopy(result), snapshot, self.source.read_text())
        downgrades: list = []
        out = cc.validate_response(
            deepcopy(result), snapshot, self.source.read_text(), salvage=True, downgrades=downgrades,
        )
        self.assertIsNone(out["events"][0]["source_grounding"])
        self.assertIsNotNone(out["events"][0]["timeline_relation"])
        self.assertEqual([row["field"] for row in downgrades], ["source_grounding"])

    def test_unknown_candidate_becomes_a_missing_evidence_abstention(self):
        snapshot = self.snapshot()
        result = self.response(snapshot)
        result["events"][0]["timeline_relation"]["candidate_id"] = "node:invented"
        downgrades: list = []
        out = cc.validate_response(
            deepcopy(result), snapshot, self.source.read_text(), salvage=True, downgrades=downgrades,
        )
        event = out["events"][0]
        self.assertIsNone(event["timeline_relation"])
        self.assertEqual(event["timeline_resolution"]["status"], "missing_evidence")
        self.assertEqual(event["timeline_resolution"]["candidate_ids"], ["node:stay"])
        self.assertIn("context_candidate_unknown", event["timeline_resolution"]["reason"])
        self.assertEqual(downgrades[0]["code"], "context_candidate_unknown")

    def test_identity_blocked_link_becomes_ambiguous(self):
        self.write_projection([node() | {"subject_refs": ["The Ranch", "self"]}])
        snapshot = self.snapshot()
        self.assertFalse(cc.candidate_identity_is_resolved(snapshot["candidates"][0]))
        result = self.response(snapshot)
        result["events"][0]["timeline_relation"]["entity_refs"] = ["self"]
        out = cc.validate_response(deepcopy(result), snapshot, self.source.read_text(), salvage=True)
        self.assertIsNone(out["events"][0]["timeline_relation"])
        self.assertEqual(out["events"][0]["timeline_resolution"]["status"], "ambiguous")

    def test_a_partial_abstention_list_is_completed(self):
        self.write_projection([node(), node("node:second", "2002/2004", "claim:second")])
        snapshot = self.snapshot()
        result = self.response(snapshot)
        result["events"][0]["timeline_relation"] = None
        result["events"][0]["timeline_resolution"] = {
            "status": "missing_evidence", "candidate_ids": ["node:stay"], "reason": "Only one considered.",
        }
        with self.assertRaises(cc.ClassifierContextError):
            cc.validate_response(
                deepcopy(result), snapshot, self.source.read_text(), require_event_contract=True,
            )
        out = cc.validate_response(
            deepcopy(result), snapshot, self.source.read_text(),
            require_event_contract=True, salvage=True,
        )
        self.assertEqual(
            out["events"][0]["timeline_resolution"]["candidate_ids"], ["node:second", "node:stay"]
        )

    def test_a_stale_echo_list_is_replaced_by_the_supplied_set(self):
        snapshot = self.snapshot()
        result = self.response(snapshot)
        result["events"][0]["timeline_resolution"] = {
            "status": "linked", "candidate_ids": ["node:stay", "node:stale"], "reason": "Linked.",
        }
        with self.assertRaises(cc.ClassifierContextError):
            cc.validate_response(
                deepcopy(result), snapshot, self.source.read_text(), require_event_contract=True,
            )
        downgrades: list = []
        out = cc.validate_response(
            deepcopy(result), snapshot, self.source.read_text(),
            require_event_contract=True, salvage=True, downgrades=downgrades,
        )
        self.assertIsNotNone(out["events"][0]["timeline_relation"])
        self.assertEqual(out["events"][0]["timeline_resolution"]["candidate_ids"], ["node:stay"])
        self.assertEqual(downgrades[-1]["code"], "resolution_candidates_completed")

    def test_structural_failures_still_refuse(self):
        snapshot = self.snapshot()
        stale = self.response(snapshot)
        stale["_classification_snapshot"]["context_digest"] = "sha256:" + "0" * 64
        with self.assertRaises(cc.ClassifierContextError):
            cc.validate_response(stale, snapshot, self.source.read_text(), salvage=True)
        broken = self.response(snapshot)
        broken["events"] = {}
        with self.assertRaises(cc.ClassifierContextError):
            cc.validate_response(broken, snapshot, self.source.read_text(), salvage=True)


class OwnerNameAndPossessiveTests(ContextCase):
    def test_a_possessive_owner_mention_matches_its_second_person_label(self):
        row = node("node:mission", "1990/2000", "claim:mission") | {
            "label": "your mission", "event_kind": "transition", "episode_id": None,
            "subject_refs": ["speaker's mission"], "legacy_refs": [],
            "occurrence_subject_scope": "owner",
        }
        candidate = cc._candidate(row, roster_aliases={}, rosters={})
        self.assertEqual(candidate["entity_refs"], ["self"])
        self.assertEqual(candidate["unresolved_entity_mentions"], [])

    def test_the_owners_own_name_is_an_owner_subject_for_grounding(self):
        story = "I moved to Yucaipa in 1994."
        grounding = {"quote": story, "temporal_quote": "1994", "subject_quote": "I", "kind": "date"}
        event = {"title": "Move to Yucaipa", "subject": "Dave", "date": {"stated": "1994"}}
        with mock.patch.object(timeline_evidence, "owner_profile_terms", return_value=set()):
            with self.assertRaisesRegex(timeline_evidence.TimelineEvidenceError, "subject evidence"):
                timeline_evidence.normalize_source_grounding(
                    dict(grounding), dict(event), story_text=story, source_revision="sha256:" + "1" * 64,
                )
        with mock.patch.object(
            timeline_evidence, "owner_profile_terms", return_value={"dave", "david james taylor"}
        ):
            normalized = timeline_evidence.normalize_source_grounding(
                dict(grounding), dict(event), story_text=story, source_revision="sha256:" + "1" * 64,
            )
        self.assertEqual(normalized["subject_quote"], "I")


class ExtractJsonTests(unittest.TestCase):
    def test_narration_with_braces_before_a_fenced_answer(self):
        text = ("<think>\nEvent {abc} needs {x: y} care.\n```\nnot json\n```\n</think>\n"
                "```json\n{\"_classification_mode\": \"timeline\", \"events\": []}\n```")
        self.assertEqual(classify_story.extract_json(text)["_classification_mode"], "timeline")

    def test_unfenced_answer_after_prose_with_braces(self):
        text = ("Thinking {loosely} first. "
                "{\"_classification_mode\": \"timeline\", \"events\": [{\"event_key\": \"a\"}]}")
        self.assertEqual(len(classify_story.extract_json(text)["events"]), 1)

    def test_no_object_is_still_malformed(self):
        with self.assertRaises(Exception):
            classify_story.extract_json("no json here { broken")


if __name__ == "__main__":
    unittest.main()
