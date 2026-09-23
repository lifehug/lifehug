"""Synthetic receipt-to-publication coverage for classifier resolution outcomes."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "system"))
sys.path.insert(0, str(ROOT / "tests"))

import classifier_claims as cc
import temporal_claims as tc
import temporal_projection as tp
import temporal_publication as pub
import temporal_store as store
import temporal_timeline as tt
from test_classifier_claims import _files, _story, _vault
from test_temporal_claims import claim as legacy_claim
from test_temporal_timeline import claim, items_of, revision

NOW = "2026-09-17T00:00:00Z"
LATER = "2026-09-18T00:00:00Z"


class ResolutionPublicationTests(unittest.TestCase):
    def file_claims(self, root, claims):
        rows = []
        for value in claims:
            payload = tc.validate_extraction_receipt({
                "source_ref": value["source_ref"],
                "extractor_version": value["extractor_version"],
                "claims": [value],
            }, now=NOW)
            path = store.write_receipt(root, payload, now=NOW)
            rows.append((path, payload, path.read_bytes()))
        return rows

    def seed(self, status, *, with_anchor=True):
        root = _vault(self)
        source = _story(root, "synthetic-resolution", "I joined payroll after launching Acorn.")
        event = {
            "title": "Acorn payroll", "subject": "self", "places": [],
            "description": "I joined payroll after launching Acorn.",
            "date": None, "timeline_resolution": {"status": status},
        }
        if status == "linked":
            event.update({
                "date": {"stated": None, "age": None,
                         "anchor_ref": "launching Acorn", "relation": "after"},
                "timeline_relation": {
                    "relation": "within", "candidate_id": "node:synthetic-acorn-job",
                    "entity_refs": ["organization/acorn"],
                    "evidence": {"quote": "joined payroll"},
                },
            })
        emitted = cc.event_claims(stem="synthetic-resolution", event=event,
                                 revision=revision("synthetic-resolution"),
                                 source_path=source, now=NOW)
        rows = self.file_claims(root, emitted)
        if status == "linked" and with_anchor:
            anchor_source = _story(root, "synthetic-job", "I worked at Acorn from 2014 to 2020.")
            job = claim(
                source="synthetic-job", claim_type="date", subject_mention="Acorn",
                event_kind="job", event_ref="node:synthetic-acorn-job",
                event_mention="Acorn employment", temporal_value="2014/2020",
            )
            job["source_ref"]["source_path"] = anchor_source
            rows.extend(self.file_claims(root, [job]))
        return root, emitted, rows

    def test_all_statuses_survive_receipt_fold_derivation_and_real_publication(self):
        for status in sorted(tc.TIMELINE_RESOLUTION_STATUSES):
            with self.subTest(status=status):
                root, emitted, receipts = self.seed(status)
                for path, payload, original in receipts:
                    read = store.read_receipt(root, path.relative_to(root).as_posix())
                    self.assertEqual(read.to_dict(), payload)
                    self.assertEqual(path.read_bytes(), original)
                index = store.fold_active_index(root)
                by_id = {value["claim_id"]: value for value in index["claims"]}
                for value in emitted:
                    self.assertEqual(by_id[value["claim_id"]]["timeline_resolution_status"], status)
                derived = tt.derive_calculated_timeline(index, now=NOW)
                node = next(row for row in derived.nodes if row["node_id"] == emitted[0]["event_ref"])
                self.assertEqual(node["timeline_resolution_status"], status)
                self.assertEqual(tp.node_from_dict(node).to_dict(), node)
                gaps = items_of(derived, "precision_gap")
                # v333: `incomplete` asks its question like `missing_evidence`
                # and `ambiguous` do — the search never finished, so nothing
                # was decided, and this moment is unplaced. `not_temporal` is a
                # closed answer and `linked` is dated by its anchor; neither
                # asks.
                if status in {"not_temporal", "linked"}:
                    self.assertEqual(gaps, [])
                else:
                    self.assertEqual(len(gaps), 1)
                    self.assertEqual(gaps[0]["event_ref"], node["node_id"])
                if status == "linked":
                    self.assertEqual(node["best_temporal_value"]["earliest"], "2014")
                    self.assertEqual(node["best_temporal_value"]["latest"], "2020")
                    self.assertEqual(items_of(derived, "missing_anchor"), [])
                    self.assertEqual(emitted[0]["temporal_value"],
                                     {"relation": "after", "anchors": ["launching Acorn"]})
                    self.assertTrue(any(row.get("finding") == "anchor_unresolved"
                                        for row in derived.diagnostics["findings"]))
                first = pub.publish(root, now=NOW)
                projected = next(row for row in pub.read_projection(root)["nodes"]
                                 if row["node_id"] == node["node_id"])
                self.assertEqual(projected["timeline_resolution_status"], status)
                self.assertEqual(projected["best_temporal_value"], node["best_temporal_value"])
                self.assertEqual(pub.read_work_items(root)["work_items"], list(derived.work_items))
                snapshot = _files(root)
                for path, payload, original in receipts:
                    self.assertEqual(store.write_receipt(root, payload, now=LATER), path)
                    self.assertEqual(path.read_bytes(), original)
                self.assertEqual(store.active_index_bytes(store.fold_active_index(root)),
                                 store.active_index_bytes(index))
                second = pub.publish(root, now=LATER)
                self.assertTrue(second["unchanged"])
                self.assertEqual(first["generation"], second["generation"])
                self.assertEqual(_files(root), snapshot)

    def test_linked_status_without_current_anchor_keeps_missing_anchor_question(self):
        root, emitted, _receipts = self.seed("linked", with_anchor=False)
        pub.publish(root, now=NOW)
        node = next(row for row in pub.read_projection(root)["nodes"]
                    if row["node_id"] == emitted[0]["event_ref"])
        self.assertEqual(node["timeline_resolution_status"], "linked")
        self.assertIsNone(node["best_temporal_value"])
        self.assertTrue(any(row["kind"] == "missing_anchor"
                            and row["subject_ref"] == "anchor:launching acorn"
                            for row in pub.read_work_items(root)["work_items"]))

    def test_legacy_absent_status_receipt_and_active_claim_stay_identical(self):
        root = _vault(self)
        value = tc.validate_temporal_claim(legacy_claim())
        receipts = self.file_claims(root, [value])
        index = store.fold_active_index(root)
        self.assertEqual(index["claims"][0]["claim_id"], "claim:e3763c08ccb1e0a53d17e84f")
        self.assertNotIn("timeline_resolution_status", index["claims"][0])
        pub.publish(root, now=NOW)
        self.assertTrue(all("timeline_resolution_status" not in row
                            for row in pub.read_projection(root)["nodes"]))
        snapshot = _files(root)
        self.assertTrue(pub.publish(root, now=LATER)["unchanged"])
        for path, payload, original in receipts:
            self.assertEqual(store.read_receipt(root, path.relative_to(root).as_posix()).to_dict(), payload)
            store.write_receipt(root, payload, now=LATER)
            self.assertEqual(path.read_bytes(), original)
        self.assertEqual(_files(root), snapshot)


if __name__ == "__main__":
    unittest.main()
