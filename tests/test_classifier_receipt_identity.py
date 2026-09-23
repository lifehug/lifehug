"""Rule-3 migration and assertion identity, using only synthetic sources."""

from __future__ import annotations

import copy
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "system"))
sys.path.insert(0, str(ROOT / "tests"))

import classifier_claims as cc
import event_identity as ei
import temporal_claims as tc
import temporal_publication as pub
import temporal_store as store
import timeline_evidence as te
from test_classifier_claims import _classification, _files, _run, _story, _vault, classification

GOLDEN = ROOT / "tests/goldens/classifier_receipt_identity.json"
NOW = "2026-09-17T00:00:00Z"
LATER = "2026-09-18T00:00:00Z"


def golden() -> dict:
    return json.loads(GOLDEN.read_text(encoding="utf-8"))


def receipt(claim: dict) -> dict:
    return tc.validate_extraction_receipt({
        "source_ref": claim["source_ref"],
        "extractor_version": claim["extractor_version"],
        "claims": [claim],
    }, now=NOW)


def anchor(root: Path) -> None:
    source = _story(root, "synthetic-job", "I worked at Acorn from 1996 to 1999.")
    claim = tc.validate_temporal_claim({
        "source_ref": {"source_id": "story:synthetic-job", "revision": "sha256:" + "7" * 64,
                       "source_path": source},
        "source_kind": "conversation", "subject_mention": "self",
        "claim_type": "date", "event_kind": "job",
        "event_ref": "node:synthetic-acorn-job", "temporal_value": "1996/1999",
        "evidence": "I worked at Acorn from 1996 to 1999.",
        "basis": "explicit", "extractor_version": "synthetic-recorder/rule:1",
    }, now=NOW)
    store.write_receipt(root, receipt(claim), now=NOW)


class HistoricalReceiptTests(unittest.TestCase):
    def seed(self, generation: str, *, declared=True):
        root = _vault(self)
        fixture = golden()
        source = root / fixture["source_path"]
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_text(fixture["source_text"], encoding="utf-8")
        _classification(root, fixture["stem"], fixture["classification"])
        for row in fixture[generation]:
            if not declared:
                row = copy.deepcopy(row)
                row["extractor"].pop("document_revision")
            store.write_receipt(root, row, now=NOW)
        anchor(root)
        store.rebuild_active_index(root)
        ei.rebuild_telling_manifest(root)
        pub.publish(root, now=NOW)
        return root, fixture

    def test_explicit_corrections_follow_equivalent_rekey_without_rewriting_history(self):
        for kind, status in (("retract", "retracted"), ("dispute", "disputed"), ("supersede", "superseded")):
            with self.subTest(kind=kind):
                root, fixture = self.seed("grouped_v306")
                old_ids = [row["claim_id"] for row in fixture["grouped_v306"][0]["claims"]]
                original = store.file_temporal_correction(
                    root, kind=kind, claim_ids=old_ids, reason="Synthetic explicit owner correction.",
                    scope="synthetic_owner_decision", author="owner", occurred_at=NOW)
                preserved = {path: (root / path).read_bytes() for path in store.receipt_relative_paths(root)}
                preserved[original.relative_path] = (root / original.relative_path).read_bytes()
                _run(root)
                index = store.fold_active_index(root)
                new = [row for row in index["claims"] if row["extractor_version"] == cc.CLASSIFIER_EXTRACTOR]
                self.assertEqual(len(new), 2)
                self.assertEqual({row["status"] for row in new}, {status})
                carries = [row for row in index["corrections"] if row["correction_id"] != original.correction_id]
                self.assertEqual(len(carries), 1)
                self.assertEqual(carries[0]["kind"], kind)
                self.assertEqual(carries[0]["scope"], "synthetic_owner_decision")
                self.assertEqual(carries[0]["claim_ids"], sorted(row["claim_id"] for row in new))
                self.assertIn(original.correction_id, carries[0]["reason"])
                for path, content in preserved.items():
                    self.assertEqual((root / path).read_bytes(), content)
                snapshot = _files(root)
                _run(root)
                self.assertEqual(_files(root), snapshot)

    def test_automatic_supersession_and_move_scopes_are_not_inherited(self):
        for scope in (cc.SUPERSEDE_SCOPE, store.CONSTRAINT_CORRECTION_SCOPE):
            with self.subTest(scope=scope):
                root, fixture = self.seed("grouped_v306")
                store.supersede_claims(root, [row["claim_id"] for row in fixture["grouped_v306"][0]["claims"]],
                                      reason="Synthetic excluded correction scope.", scope=scope)
                _run(root)
                index = store.fold_active_index(root)
                new = [row for row in index["claims"] if row["extractor_version"] == cc.CLASSIFIER_EXTRACTOR]
                self.assertEqual({row["status"] for row in new}, {"active"})
                self.assertEqual(len(index["corrections"]), 1)

    def test_changed_assertion_evidence_or_document_does_not_inherit_rejection(self):
        for change in ("status", "evidence", "document"):
            with self.subTest(change=change):
                root, fixture = self.seed("grouped_v306")
                store.retract_claims(root, [row["claim_id"] for row in fixture["grouped_v306"][0]["claims"]],
                                     reason="Synthetic rejected interpretation.")
                changed = copy.deepcopy(fixture["classification"])
                if change == "status":
                    changed["events"][0]["timeline_resolution"] = {"status": "linked"}
                elif change == "evidence":
                    changed["events"][0]["when_hint"] = "another stated detail"
                    changed["events"][0]["timeline_relation"]["evidence"]["start"] += 1
                else:
                    text = "I corrected the synthetic story."
                    (root / fixture["source_path"]).write_text(
                        "---\nsource_id: story:synthetic-envelope\ncontent_sha256: "
                        + store.payload_sha256(text) + "\n---\n\n" + text + "\n")
                _classification(root, fixture["stem"], changed)
                _run(root)
                index = store.fold_active_index(root)
                new = [row for row in index["claims"] if row["extractor_version"] == cc.CLASSIFIER_EXTRACTOR]
                self.assertEqual({row["status"] for row in new}, {"active"})
                self.assertEqual(len(index["corrections"]), 1)

    def test_undeclared_legacy_provenance_requires_exact_existing_revision(self):
        for unchanged in (True, False):
            with self.subTest(unchanged=unchanged):
                root, fixture = self.seed("grouped_v306", declared=False)
                store.retract_claims(root, [row["claim_id"] for row in fixture["grouped_v306"][0]["claims"]],
                                     reason="Synthetic legacy rejection.")
                if not unchanged:
                    changed = copy.deepcopy(fixture["classification"])
                    changed["classified_at"] = LATER
                    _classification(root, fixture["stem"], changed)
                _run(root)
                index = store.fold_active_index(root)
                new = [row for row in index["claims"] if row["extractor_version"] == cc.CLASSIFIER_EXTRACTOR]
                self.assertEqual({row["status"] for row in new}, {"retracted" if unchanged else "active"})

    def test_stale_classification_is_not_migrated_after_correction(self):
        root, fixture = self.seed("grouped_v306")
        store.retract_claims(root, [row["claim_id"] for row in fixture["grouped_v306"][0]["claims"]],
                             reason="Synthetic withdrawn source reading.")
        _classification(root, fixture["stem"], {**fixture["classification"], "stale": True})
        report = _run(root)
        self.assertEqual(report["classifications"], 0)
        self.assertEqual(report["receipts_written"], 0)
        self.assertFalse(any(cc.is_classifier_source_id(row["source_ref"]["source_id"])
                             for row in store.active_claims(store.fold_active_index(root))))

    def test_correction_equivalence_retains_raw_asserted_resolution_status(self):
        for stored_status in (None, "linked"):
            with self.subTest(stored_status=stored_status):
                root = _vault(self)
                fixture = golden()
                path = root / fixture["source_path"]
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(fixture["source_text"])
                old_ids = []
                for old in fixture["split_v309"]:
                    if stored_status:
                        for claim in old["claims"]:
                            claim["timeline_resolution_status"] = stored_status
                    store.write_receipt(root, old, now=NOW)
                    old_ids.extend(claim["claim_id"] for claim in old["claims"])
                store.retract_claims(root, old_ids, reason="Synthetic status-bearing rejection.")
                changed = fixture["classification"]
                changed["events"][0]["timeline_resolution"] = {"status": "linked"}
                _classification(root, fixture["stem"], changed)
                _run(root)
                new = [row for row in store.fold_active_index(root)["claims"]
                       if row["extractor_version"] == cc.CLASSIFIER_EXTRACTOR]
                self.assertEqual({row["status"] for row in new},
                                 {"retracted" if stored_status else "active"})

    def test_manual_move_and_undo_survive_generation_and_status_changes(self):
        root, fixture = self.seed("grouped_v306")
        node_id = fixture["grouped_v306"][0]["claims"][0]["event_ref"]
        move = store.file_ordering_constraint(
            root, relation="within", subject_node_id=node_id,
            anchor_node_ids=["node:synthetic-acorn-job"], reason="Synthetic manual Move.")
        move_path = root / move["relative_path"]
        original_move = move_path.read_bytes()
        _run(root)
        changed = copy.deepcopy(fixture["classification"])
        changed["events"][0]["timeline_resolution"] = {"status": "linked"}
        _classification(root, fixture["stem"], changed)
        _run(root)
        node = next(row for row in pub.read_projection(root)["nodes"] if row["node_id"] == node_id)
        self.assertIn(move["constraint_id"], node["input_constraint_refs"])
        self.assertEqual(node["best_temporal_value"]["best"], "1996/1999")
        self.assertEqual(move_path.read_bytes(), original_move)

        undo = store.retract_ordering_constraint(root, move["constraint_id"], reason="Synthetic Undo.")
        undo_path = root / undo.relative_path
        original_undo = undo_path.read_bytes()
        _run(root)
        node = next(row for row in pub.read_projection(root)["nodes"] if row["node_id"] == node_id)
        self.assertNotIn(move["constraint_id"], node["input_constraint_refs"])
        self.assertEqual(node["best_temporal_value"]["best"], "1996/1999")
        self.assertEqual(move_path.read_bytes(), original_move)
        self.assertEqual(undo_path.read_bytes(), original_undo)
        snapshot = _files(root)
        _run(root)
        self.assertEqual(_files(root), snapshot)

    def test_frozen_actual_producers_reproduce_subset_collision(self):
        root, fixture = self.seed("grouped_v306")
        old = fixture["grouped_v306"][0]
        new = next(row for row in fixture["split_v309"]
                   if row["receipt_id"] == old["receipt_id"])
        self.assertEqual(len(old["claims"]), 2)
        self.assertEqual({row["claim_type"] for row in old["claims"]}, {"relative_order"})
        self.assertEqual(new["claims"], old["claims"][:1])
        self.assertEqual(tc.validate_extraction_receipt(old, now=NOW), old)
        source_ref = store.read_source_ref(root, fixture["source_path"])
        self.assertEqual(old["extractor"]["document_revision"], source_ref.revision)
        telling = ei.classifier_telling_ref(fixture["stem"], fixture["classification"]["events"][0])
        self.assertEqual(old["extractor"]["telling_keys"],
                         {row["claim_id"]: telling for row in old["claims"]})
        before = _files(root)
        with self.assertRaises(store.TemporalStoreError) as caught:
            store.write_receipt(root, new, now=NOW)
        self.assertEqual(caught.exception.code, "receipt_immutable_conflict")
        self.assertEqual(_files(root), before)

    def test_grouped_and_split_rule2_migrate_append_publish_and_replay(self):
        self.assertEqual(cc.RULE_VERSION, "5")
        self.assertEqual(te.CLASSIFIER_CLAIMS_RULE_VERSION, "5")
        for generation in ("grouped_v306", "split_v309"):
            with self.subTest(generation=generation):
                root, fixture = self.seed(generation)
                old_bytes = {path: (root / path).read_bytes()
                             for path in store.receipt_relative_paths(root)}
                old_claims = [claim for row in fixture[generation] for claim in row["claims"]]
                old_node = next(row for row in pub.read_projection(root)["nodes"]
                                if row["node_id"] == old_claims[0]["event_ref"])
                before_manifest = ei.read_telling_manifest(root)
                report = _run(root)
                self.assertEqual(report["receipts_written"], 2)
                self.assertEqual(report["superseded_claims"], 2)
                self.assertEqual(report["claims_by_type"]["relative_order"], 2)
                index = store.fold_active_index(root)
                by_id = {row["claim_id"]: row for row in index["claims"]}
                for claim in old_claims:
                    self.assertEqual(by_id[claim["claim_id"]]["status"], "superseded")
                current = [row for row in store.active_claims(index)
                           if cc.is_classifier_source_id(row["source_ref"]["source_id"])]
                self.assertEqual(len(current), 2)
                self.assertEqual({row["extractor_version"] for row in current},
                                 {"classifier-claims/rule:5"})
                self.assertEqual({row["event_ref"] for row in current}, {old_node["node_id"]})
                projection = pub.read_projection(root)
                node = next(row for row in projection["nodes"] if row["node_id"] == old_node["node_id"])
                self.assertEqual(node["best_temporal_value"]["earliest"], "1996")
                self.assertEqual(node["best_temporal_value"]["latest"], "1999")
                self.assertEqual(node["best_temporal_value"], old_node["best_temporal_value"])
                manifest = ei.read_telling_manifest(root)
                telling = next(row for row in manifest["tellings"]
                               if row.get("source_path") == fixture["source_path"])
                old_telling = next(row for row in before_manifest["tellings"]
                                   if row.get("source_path") == fixture["source_path"])
                self.assertEqual(telling["telling_ref"], old_telling["telling_ref"])
                self.assertEqual(telling["active_claim_ids"], sorted(row["claim_id"] for row in current))
                self.assertEqual(set(telling["claim_ids"]),
                                 {row["claim_id"] for row in old_claims + current})
                for path, content in old_bytes.items():
                    self.assertEqual((root / path).read_bytes(), content)
                before = _files(root)
                replay = _run(root)
                self.assertEqual(replay["receipts_written"], 0)
                self.assertEqual(replay["receipts_kept"], 2)
                self.assertEqual(replay["superseded_claims"], 0)
                self.assertEqual(_files(root), before)
                self.assertEqual(pub.read_projection(root), projection)


class AssertionIdentityTests(unittest.TestCase):
    STORY = "I founded Acorn in 2004, before I joined its payroll."

    def event(self):
        row = {"title": "Acorn founding", "description": self.STORY,
               "subject": "self", "date": {"stated": "2004"},
               "timeline_relation": {"relation": "before", "candidate_id": "node:synthetic-acorn-job",
                   "entity_refs": ["organization/acorn"], "evidence": {
                       "quote": "before I joined its payroll", "start": 24, "end": 51}},
               "timeline_resolution": {"status": "linked", "source_revision": "sha256:" + "1" * 64,
                                       "input_fingerprint": "sha256:" + "2" * 64}}
        row["source_grounding"] = te.normalize_source_grounding({
            "quote": "I founded Acorn in 2004", "temporal_quote": "2004",
            "subject_quote": "I", "kind": "date",
        }, row, story_text=self.STORY, source_revision="sha256:" + "1" * 64)
        return row

    def claims(self, row, revision="sha256:" + "a" * 64, now=NOW):
        return cc.event_claims(stem="synthetic-founding", event=row, revision=revision,
                              source_path="sources/stories/synthetic-founding.md", now=now)

    def test_equal_assertions_ignore_unrelated_link_and_clocks(self):
        before_event = self.event()
        before = self.claims(before_event)[0]
        changed = copy.deepcopy(before_event)
        changed["timeline_relation"]["candidate_id"] = "node:another-job"
        changed["timeline_relation"]["evidence"]["quote"] = "I joined its payroll"
        changed["timeline_resolution"]["input_fingerprint"] = "sha256:" + "3" * 64
        after = self.claims(changed, revision="sha256:" + "b" * 64, now=LATER)[0]
        self.assertEqual(before["claim_id"], after["claim_id"])
        self.assertEqual(store._assertion_view(receipt(before)), store._assertion_view(receipt(after)))
        root = _vault(self)
        _story(root, "synthetic-founding", self.STORY)
        path = store.write_receipt(root, receipt(before), now=NOW)
        original = path.read_bytes()
        self.assertEqual(store.write_receipt(root, receipt(after), now=LATER), path)
        self.assertEqual(path.read_bytes(), original)

    def test_final_validation_remints_id_from_final_revision(self):
        row = self.event()
        for claim in self.claims(row):
            self.assertEqual(claim["claim_id"], tc.derive_claim_id(
                claim_type=claim["claim_type"], subject_mention=claim["subject_mention"],
                event_kind=claim["event_kind"], temporal_value=claim["temporal_value"],
                source_ref=claim["source_ref"], extractor_version=claim["extractor_version"]))
            provisional = {**claim, "source_ref": {**claim["source_ref"], "revision": "sha256:" + "a" * 64}}
            self.assertNotEqual(tc.validate_temporal_claim(provisional, now=NOW)["claim_id"], claim["claim_id"])

    def test_undeclared_grounded_source_proof_must_match_exactly(self):
        for matching in (True, False):
            with self.subTest(matching=matching):
                root = _vault(self)
                source = _story(root, "synthetic-founding", self.STORY)
                event = self.event()
                current = self.claims(event)[0]
                old = tc.validate_temporal_claim({
                    **current, "extractor_version": "classifier-claims/rule:2",
                    "source_ref": {**current["source_ref"], "revision":
                                   event["source_grounding"]["source_revision"] if matching else "sha256:" + "9" * 64},
                }, now=NOW)
                store.write_receipt(root, receipt(old), now=NOW)
                store.retract_claims(root, [old["claim_id"]], reason="Synthetic grounded-source rejection.")
                _classification(root, "synthetic-founding", classification(source, event))
                _run(root)
                direct = next(row for row in store.fold_active_index(root)["claims"]
                              if row["extractor_version"] == cc.CLASSIFIER_EXTRACTOR and row["claim_type"] == "date")
                self.assertEqual(direct["status"], "retracted" if matching else "active")

    def test_normalized_assertion_not_incidental_formatting_sets_revision(self):
        row = self.event()
        canonical = self.claims(row)
        padded = copy.deepcopy(row)
        padded["subject"] = " self "
        padded["title"] = " Acorn   founding "
        padded["source_grounding"]["quote"] = " I  founded Acorn in 2004 "
        self.assertEqual(self.claims(padded), canonical)

    def test_changed_assertion_matrix_never_reuses_a_receipt_path(self):
        event = self.event()
        variants = {}
        for status in sorted(tc.TIMELINE_RESOLUTION_STATUSES - {"linked"}):
            row = copy.deepcopy(event)
            row["timeline_resolution"]["status"] = status
            row["timeline_relation"] = None
            variants[status] = row
        row = copy.deepcopy(event)
        row["source_grounding"] = te.normalize_source_grounding({
            "quote": self.STORY, "temporal_quote": "2004", "subject_quote": "I", "kind": "date",
        }, row, story_text=self.STORY, source_revision="sha256:" + "1" * 64)
        variants["exact_evidence"] = row
        for name, value in (("date", {"stated": "2005"}), ("subject", "Mira"),
                            ("places", ["Cedarport"]), ("source_grounding", None)):
            row = copy.deepcopy(event)
            row[name] = value
            variants[name] = row
        before = self.claims(event)
        root = _vault(self)
        _story(root, "synthetic-founding", self.STORY)
        paths = {}
        for label, row in {"baseline": event, **variants}.items():
            with self.subTest(change=label):
                claims = self.claims(row)
                self.assertEqual(cc.event_key(row), cc.event_key(event))
                self.assertEqual(ei.classifier_telling_ref("synthetic-founding", row),
                                 ei.classifier_telling_ref("synthetic-founding", event))
                for index, claim in enumerate(claims):
                    self.assertEqual(claim["event_ref"], before[index]["event_ref"]
                                     if label != "subject" else claims[0]["event_ref"])
                    value = receipt(claim)
                    path = tc.receipt_relative_path(value["source_ref"], value["extractor_version"])
                    assertion = store._assertion_view(value)
                    if path in paths:
                        self.assertEqual(paths[path], assertion)
                    paths[path] = assertion
                    store.write_receipt(root, value, now=NOW)
                if label != "baseline":
                    self.assertNotEqual(claims[0]["claim_id"], before[0]["claim_id"])
                if label == "source_grounding":
                    self.assertEqual(before[1]["event_kind"], "founded")
                    self.assertEqual(claims[1]["event_kind"], "moment")
                    self.assertNotEqual(claims[1]["source_ref"], before[1]["source_ref"])

    def test_status_and_evidence_changes_append_supersede_publish_stable_event(self):
        for change in ("status", "evidence"):
            with self.subTest(change=change):
                root = _vault(self)
                source = _story(root, "synthetic-founding", self.STORY)
                before = self.event()
                _classification(root, "synthetic-founding", classification(source, before))
                _run(root)
                telling_ref = ei.classifier_telling_ref("synthetic-founding", before)
                binding, _ = ei.file_event_identity(
                    root, telling_ref=telling_ref, episode_id="episode:" + "c" * 24,
                    relation="same", origin="confirmed", created_at=NOW)
                binding_bytes = {path: path.read_bytes() for path in (root / ei.HUMAN_BINDINGS_DIR).glob("*.json")}
                _run(root)
                bound_node = next(row for row in pub.read_projection(root)["nodes"]
                                  if row.get("input_claim_refs"))
                original_claims = store.active_claims(store.fold_active_index(root))
                old_bytes = {path: (root / path).read_bytes() for path in store.receipt_relative_paths(root)}
                after = copy.deepcopy(before)
                if change == "status":
                    after["timeline_resolution"]["status"] = "incomplete"
                    after["timeline_relation"] = None
                else:
                    after["source_grounding"]["quote"] = self.STORY
                    after["source_grounding"]["end"] = len(self.STORY)
                _classification(root, "synthetic-founding", classification(source, after))
                report = _run(root)
                self.assertEqual(report["superseded_claims"], 2 if change == "status" else 1)
                active = store.active_claims(store.fold_active_index(root))
                self.assertEqual({row["event_ref"] for row in active},
                                 {row["event_ref"] for row in original_claims})
                node = next(row for row in pub.read_projection(root)["nodes"]
                            if row["node_id"] == bound_node["node_id"])
                self.assertEqual(node["best_temporal_value"]["best"], "2004")
                telling = next(row for row in ei.read_telling_manifest(root)["tellings"]
                               if row["telling_ref"] == telling_ref)
                self.assertEqual(telling["bound_identity_ids"], [binding["identity_id"]])
                for path, content in binding_bytes.items():
                    self.assertEqual(path.read_bytes(), content)
                for path, content in old_bytes.items():
                    self.assertEqual((root / path).read_bytes(), content)
                snapshot = _files(root)
                _run(root)
                self.assertEqual(_files(root), snapshot)


if __name__ == "__main__":
    unittest.main()
