"""Fresh metadata, reused directory names, and the unchanged full-fold oracle."""

from __future__ import annotations

import contextvars
import json
import os
import shutil
import sys
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "system"))

import temporal_store as ts
import vault_paths as vp
from test_landmark_offer import NOW, OfferVaultCase
from test_landmark_apply_publication_batch import seed_moments
from test_place_containment import moment_claim


class ReceiptInventoryTests(OfferVaultCase):
    def setUp(self):
        super().setUp()
        seed_moments(self.root, 3)
        self.paths = ts.receipt_relative_paths(self.root)

    def oracle(self):
        return contextvars.Context().run(ts.fold_active_index, self.root)

    def assert_current(self):
        actual = ts.fold_active_index(self.root)
        self.assertEqual(ts.active_index_bytes(actual), ts.active_index_bytes(self.oracle()))
        return actual

    def new_receipt(self, number=1):
        claim = moment_claim({"source": f"classification:new-{number}",
                              "quote": "Another entirely synthetic occasion.",
                              "mention": f"New occasion {number}"})
        return ts.write_receipt(self.root, {
            "source_ref": claim["source_ref"], "extractor_version": "classifier:1",
            "claims": [claim]}, now=NOW)

    def test_warm_fold_has_no_directory_enumeration_or_per_receipt_path_validation(self):
        with ts.receipt_read_batch(self.root):
            expected = ts.fold_active_index(self.root)
            with mock.patch.object(vp.os, "scandir", wraps=vp.os.scandir) as scan, \
                    mock.patch.object(ts, "read_receipt", wraps=ts.read_receipt) as read, \
                    mock.patch.object(ts, "_receipt_file_signature", wraps=ts._receipt_file_signature) as signature:
                self.assertEqual(ts.fold_active_index(self.root), expected)
            self.assertEqual(scan.call_count, 0)
            self.assertEqual(read.call_count, 0)
            self.assertEqual(signature.call_count, 0)

    def test_directory_membership_refresh_is_limited_to_changed_branches(self):
        with ts.receipt_read_batch(self.root):
            self.assert_current()
            self.new_receipt()
            with mock.patch.object(vp.os, "scandir", wraps=vp.os.scandir) as scan:
                after = ts.fold_active_index(self.root)
            # Receipt root plus this new source and revision; no old branch scan.
            self.assertEqual(scan.call_count, 3)
            self.assertEqual(after, self.oracle())
            path = self.root / self.paths[0]
            path.unlink()
            self.assert_current()
            self.assertNotIn(self.paths[0], ts._RECEIPT_READ_BATCH.get().receipts)

    def test_existing_file_edit_corruption_repair_without_parent_mtime_change(self):
        path = self.root / self.paths[0]
        original = path.read_bytes()
        with ts.receipt_read_batch(self.root):
            self.assert_current()
            parent_signature = vp.stat_signature(path.parent.stat())
            value = json.loads(original)
            value["extractor"]["synthetic_annotation"] = {"nested": [1, 2]}
            path.write_text(json.dumps(value))
            self.assertEqual(vp.stat_signature(path.parent.stat()), parent_signature)
            self.assert_current()
            path.write_text("not json")
            self.assertIn(self.paths[0], self.assert_current()["unreadable_receipt_paths"])
            path.write_bytes(original)
            self.assert_current()

    def test_nested_new_path_and_removed_then_recreated_subtree(self):
        base = self.root / ts.RECEIPTS_DIR
        with ts.receipt_read_batch(self.root):
            self.assert_current()
            nested = base / "additional" / "deeper" / "extra.json"
            nested.parent.mkdir(parents=True)
            nested.write_bytes((self.root / self.paths[0]).read_bytes())
            self.assert_current()
            shutil.rmtree(base)
            self.assertEqual(self.assert_current()["counts"]["receipts"], 0)
            self.new_receipt(2)
            self.assert_current()

    def test_reextraction_and_new_correction_still_use_whole_fold(self):
        path = self.root / self.paths[0]
        value = json.loads(path.read_bytes())
        with ts.receipt_read_batch(self.root):
            before = self.assert_current()
            value["extractor_version"] = "synthetic:2"
            value["created_at"] = "2026-09-16T00:00:00Z"
            value["claims"] = [{**row, "extractor_version": value["extractor_version"],
                                "created_at": value["created_at"]} for row in value["claims"]]
            ts.write_receipt(self.root, value, now=value["created_at"])
            revised = self.assert_current()
            self.assertGreater(revised["counts"]["superseded"], 0)
            target = next(key for key in before["active_claim_ids"]
                          if key in revised["active_claim_ids"])
            correction = ts.retract_claims(self.root, [target], reason="Synthetic correction", occurred_at=NOW)
            self.assert_current()
            (self.root / correction.relative_path).unlink()
            self.assert_current()

    def test_caller_mutation_does_not_poison_warm_inventory_results(self):
        with ts.receipt_read_batch(self.root):
            expected = self.assert_current()
            receipts, _ = ts.load_receipts(self.root)
            receipts[0].extractor["mutation"] = {"bad": ["value"]}
            expected["claims"][0]["source_ref"]["source_id"] = "caller mutation"
            self.assert_current()

    def test_symlink_substitution_at_every_receipt_ancestor_fails_closed(self):
        relative = Path(self.paths[0])
        targets = [self.root / relative, *(self.root / part for part in relative.parents if part != Path())]
        for target in targets:
            with self.subTest(target=target.relative_to(self.root)):
                saved = self.root / "saved"
                with ts.receipt_read_batch(self.root):
                    self.assert_current()
                    target.rename(saved)
                    target.symlink_to(saved, target_is_directory=saved.is_dir())
                    try:
                        with self.assertRaises(ts.TemporalStoreError):
                            ts.fold_active_index(self.root)
                    finally:
                        target.unlink()
                        saved.rename(target)
                    self.assert_current()

    def test_regular_directory_replacement_is_refreshed_not_borrowed(self):
        target = (self.root / self.paths[0]).parent
        saved = self.root / "saved"
        with ts.receipt_read_batch(self.root):
            self.assert_current()
            target.rename(saved)
            target.mkdir()
            self.assert_current()
            target.rmdir()
            saved.rename(target)
            self.assert_current()

    def test_root_replacement_after_scope_entry_is_rejected(self):
        root = self.root
        saved = root.with_name(root.name + "-saved")
        with ts.receipt_read_batch(root):
            self.assert_current()
            root.rename(saved)
            root.mkdir()
            try:
                with self.assertRaises(ts.TemporalStoreError):
                    ts.fold_active_index(root)
                with self.assertRaises(ts.TemporalStoreError):
                    ts.read_receipt(root, self.paths[0])
            finally:
                root.rmdir()
                saved.rename(root)
            self.assert_current()

    def test_same_vault_symlink_alias_cannot_borrow_a_warm_inventory(self):
        alias = self.root.with_name(self.root.name + "-alias")
        alias.symlink_to(self.root, target_is_directory=True)
        try:
            with ts.receipt_read_batch(self.root):
                self.assert_current()
                with self.assertRaises(ts.TemporalStoreError):
                    ts.fold_active_index(alias)
            with self.assertRaises(ts.TemporalStoreError):
                with ts.receipt_read_batch(alias):
                    pass
        finally:
            alias.unlink()

    def test_replacement_during_cached_visit_cannot_return_a_successful_fold(self):
        original = ts.copy.deepcopy
        target = (self.root / self.paths[0]).parent
        saved = self.root / "saved"
        replaced = False

        def replace(value, *args, **kwargs):
            nonlocal replaced
            if not replaced:
                replaced = True
                target.rename(saved)
                target.symlink_to(saved, target_is_directory=True)
            return original(value, *args, **kwargs)

        with ts.receipt_read_batch(self.root):
            self.assert_current()
            with mock.patch.object(ts.copy, "deepcopy", side_effect=replace):
                try:
                    with self.assertRaises(ts.TemporalStoreError):
                        ts.fold_active_index(self.root)
                finally:
                    target.unlink()
                    saved.rename(target)
            self.assert_current()

    def test_nested_exception_and_escaped_context_release_inventory(self):
        with self.assertRaisesRegex(RuntimeError, "synthetic"):
            with ts.receipt_read_batch(self.root):
                self.assert_current()
                batch = ts._RECEIPT_READ_BATCH.get()
                with ts.receipt_read_batch(self.root):
                    self.assertIs(ts._RECEIPT_READ_BATCH.get(), batch)
                    self.assert_current()
                escaped = contextvars.copy_context()
                raise RuntimeError("synthetic")
        self.assertTrue(batch.closed)
        self.assertEqual(batch.inventory.directories, {})
        self.assertEqual(batch.receipts, {})
        with mock.patch.object(ts, "receipt_relative_paths", wraps=ts.receipt_relative_paths) as listing:
            self.assertEqual(escaped.run(ts.fold_active_index, self.root), self.oracle())
            self.assertEqual(listing.call_count, 2)

    def test_caught_inner_exception_does_not_close_outer_inventory(self):
        with ts.receipt_read_batch(self.root):
            expected = self.assert_current()
            batch = ts._RECEIPT_READ_BATCH.get()
            try:
                with ts.receipt_read_batch(self.root):
                    self.assert_current()
                    raise RuntimeError("synthetic")
            except RuntimeError:
                pass
            self.assertFalse(batch.closed)
            self.assertEqual(self.assert_current(), expected)

    def test_mid_visit_membership_write_fails_closed_and_next_refresh_recovers(self):
        with ts.receipt_read_batch(self.root):
            self.assert_current()
            inventory = ts._RECEIPT_READ_BATCH.get().inventory
            changed = False

            def add_file(relative, signature):
                nonlocal changed
                if not changed:
                    changed = True
                    (self.root / relative).with_name("new.json").write_text("{}")

            with self.assertRaisesRegex(ValueError, "membership changed"):
                inventory.visit_files(add_file)
            self.assert_current()

    def test_all_directory_descriptors_close_when_the_visitor_raises(self):
        opened = set()
        real_open, real_close, real_dup = os.open, os.close, os.dup

        def track_open(*args, **kwargs):
            fd = real_open(*args, **kwargs)
            opened.add(fd)
            return fd

        def track_close(fd):
            opened.discard(fd)
            return real_close(fd)

        def track_dup(fd):
            duplicate = real_dup(fd)
            opened.add(duplicate)
            return duplicate

        def fail(*args):
            raise RuntimeError("synthetic visitor failure")

        with ts.receipt_read_batch(self.root):
            self.assert_current()
            inventory = ts._RECEIPT_READ_BATCH.get().inventory
            with mock.patch.object(vp.os, "open", side_effect=track_open), \
                    mock.patch.object(vp.os, "dup", side_effect=track_dup), \
                    mock.patch.object(vp.os, "close", side_effect=track_close):
                with self.assertRaisesRegex(RuntimeError, "visitor failure"):
                    inventory.visit_files(fail)
            self.assertEqual(opened, set())
            self.assert_current()
