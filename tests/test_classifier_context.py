"""Canonical contextual classifier freshness and validation (PR342)."""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "system"))

import classifier_context as cc  # noqa: E402
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
        self.write_projection([node()])

    def write_projection(self, nodes, *, generation=1) -> None:
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


class StableFreshnessTests(ContextCase):
    def test_generation_and_timestamp_do_not_change_digest(self):
        first = self.snapshot()["context_digest"]
        self.write_projection([node()], generation=9)
        self.assertEqual(self.snapshot()["context_digest"], first)

    def test_this_sources_own_classifier_output_cannot_invalidate_itself(self):
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
        self.assertEqual(cc.refresh_reason(self.snapshot(), stored), "context_changed")

    def test_context_removal_invalidates_the_prior_reading(self):
        first = self.snapshot()
        stored = {"classification_snapshot": cc.snapshot_metadata(first)}
        self.write_projection([])
        self.assertEqual(cc.refresh_reason(self.snapshot(), stored), "context_changed")

    def test_inherited_job_episode_is_retrieved_by_grounded_entity_ref(self):
        (self.root / cc.ACTIVE_INDEX_PATH).write_text(json.dumps({"claims": [{
            "claim_id": "claim:source-org",
            "status": "active",
            "subject_ref": "org/tidewheel",
            "source_ref": {
                "source_id": "listener:story",
                "source_path": "sources/manual/story.md",
            },
        }]}), encoding="utf-8")
        job = node("node:tidewheel-job", "2002/2006", "claim:job") | {
            "episode_id": None,
            "event_kind": "job",
            "subject_refs": ["org/tidewheel", "self"],
        }
        self.write_projection([node(), job])
        snapshot = self.snapshot()
        self.assertEqual(
            [row["candidate_id"] for row in snapshot["candidates"]],
            ["node:tidewheel-job"],
        )

    def test_human_negative_identity_is_visible_and_changes_freshness(self):
        telling_ref = "classification:story#aaaaaaaaaaaa"
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

    def test_target_selection_loads_canonical_catalog_once_for_many_sources(self):
        sources = []
        for index in range(100):
            source = self.source.parent / f"story-{index:03d}.md"
            source.write_text(f"Synthetic story {index} in Cedarport.", encoding="utf-8")
            sources.append(source)

        with mock.patch.object(
            temporal_publication,
            "read_projection",
            wraps=temporal_publication.read_projection,
        ) as read_projection, mock.patch.object(
            temporal_store,
            "read_active_index",
            wraps=temporal_store.read_active_index,
        ) as read_active_index, mock.patch.object(
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
        self.assertEqual(read_projection.call_count, 1)
        self.assertEqual(read_active_index.call_count, 1)
        self.assertEqual(load_roster.call_count, 3)
        self.assertEqual(load_event_identities.call_count, 1)
        self.assertEqual(load_episode_operations.call_count, 1)
        self.assertEqual(read_telling_manifest.call_count, 1)

    def test_standalone_snapshots_keep_independent_fresh_catalog_reads(self):
        with mock.patch.object(
            temporal_publication,
            "read_projection",
            wraps=temporal_publication.read_projection,
        ) as read_projection, mock.patch.object(
            temporal_store,
            "read_active_index",
            wraps=temporal_store.read_active_index,
        ) as read_active_index:
            self.snapshot()
            self.snapshot()

        self.assertEqual(read_projection.call_count, 2)
        self.assertEqual(read_active_index.call_count, 2)

    def test_empty_target_inventory_does_not_load_the_catalog(self):
        with mock.patch.object(cc, "_load_context_catalog") as load_catalog:
            report = cc.select_refresh_targets(self.root, [], classifications={})

        load_catalog.assert_not_called()
        self.assertEqual(report["pending_count"], 0)
        self.assertTrue(report["complete"])

    def test_shared_catalog_applies_own_output_exclusion_per_source(self):
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

        self.assertEqual(own["candidates"], [])
        self.assertEqual(
            [row["candidate_id"] for row in other["candidates"]], ["node:stay"]
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

        self.assertTrue(snapshot["context_truncated"])
        self.assertNotIn(
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
        self.write_projection([node(value="2005/2008")])
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
            roster_snapshot=place_roster,
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
            response_path.write_text(json.dumps({
                "_classification_snapshot": task["classification_snapshot"],
                "people": [],
                "places": [{"name": "Cedarport", "slug": "cedarport"}],
                "time_periods": [],
                "themes": [],
                "events": [{
                    "title": "Finding the envelope",
                    "description": "I found the envelope.",
                    "places": ["Cedarport"],
                    "date": None,
                    "timeline_relation": {
                        "relation": "within",
                        "candidate_id": stay["candidate_id"],
                        "entity_refs": ["place/cedarport"],
                        "evidence": {"quote": "while we lived in Cedarport"},
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
            roster_snapshot=place_roster,
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


if __name__ == "__main__":
    unittest.main()
