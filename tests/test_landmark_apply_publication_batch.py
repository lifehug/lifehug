"""Real synthetic stores: sequential landmark truth, one calculated publication."""

from __future__ import annotations

import contextvars
import json
import sys
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "system"))

import go_dig_writer as writer
import landmark_offer as lo
import landmark_projection as lp
import temporal_publication as pub
import temporal_store as ts
import timeline
from test_landmark_offer import NOW, OfferVaultCase, ScriptedCall, read_dates, read_unit, reading
from test_place_containment import moment_claim, year


def mixed_submission(count=76, event_count=30):
    """The punctuation regression's mixed 76-unit / 30-event input."""
    units, events, sentences = [], [], []
    for i in range(count):
        domain = "residences" if i < 30 else "schools" if i < 51 else "work"
        label = (f"Harbor{i:02d} City, ST" if i < 30 else
                 f"Arts and Sciences Academy{i:02d}" if i < 51 else
                 f"Workshop{i:02d} & Sons")
        quote = f"I was at {label} from 1990 to 1992."
        sentences.append(quote)
        field = "city" if domain == "residences" else "name" if domain == "schools" else "what"
        units.append(read_unit(f"u{i}", domain, label, quote,
                               record={field: label, "label": label},
                               dates=read_dates("1990", "1992"),
                               within=None if i < 30 else "u0"))
    for i in range(event_count):
        quote = f"Person{i:02d} was born in 1991."
        sentences.append(quote)
        events.append({"ref": f"e{i}", "kind": "child_born",
                       "text": f"Person{i:02d} was born",
                       "subject_mention": f"Person{i:02d}", "date": "1991",
                       "quote": quote, "within": f"u{i}"})
    return "\n".join(sentences), reading(units=units, events=events)


def seed_moments(root, count):
    """Real receipt per unique classifier event; 16/17 deliberately undated."""
    lp.file_landmark_record(root, "birth", {
        "domain": "birth", "label": "birth", "date": year("1960")},
        ordinal=1, now=NOW)
    for i in range(count):
        claim = moment_claim({
            "source": f"classification:synthetic-{i:04d}#moment-{i:04d}",
            "quote": f"I remember synthetic occasion {i:04d}.",
            "mention": f"Synthetic occasion {i:04d}"},
            temporal_value="1980" if i % 17 == 0 else None)
        ts.write_receipt(root, {
            "source_ref": claim["source_ref"], "extractor_version": "classifier:1",
            "created_at": NOW, "claims": [claim]}, now=NOW)
    timeline.redraw_landmarks()


class PublicationBatchTests(OfferVaultCase):
    def snapshot(self):
        return {p.relative_to(self.root): p.read_bytes()
                for p in self.root.rglob("*") if p.is_file()}

    def offer(self, count=2, events=2):
        text, completion = mixed_submission(count, events)
        return self.propose(text, ScriptedCall(reading=completion))

    def apply(self, proposal):
        return lo.apply(proposal["proposal_id"],
                        [u["unit_id"] for u in proposal["units"]], self.root, now=NOW)

    def test_populated_archive_publishes_once_after_all_units_and_group_claims(self):
        seed_moments(self.root, 1000)
        prior = pub.read_projection(self.root)
        self.assertEqual(sum(n["event_kind"] == "moment" for n in prior["nodes"]), 1000)
        original_receipts = {p: (self.root / p).read_bytes()
                             for p in ts.receipt_relative_paths(self.root)}
        proposal = self.offer(76, 30)
        with mock.patch.object(pub, "publish", wraps=pub.publish) as publish, \
                mock.patch.object(timeline, "redraw_landmarks", wraps=timeline.redraw_landmarks) as redraw:
            receipt = self.apply(proposal)
        self.assertEqual(publish.call_count, 1)
        self.assertEqual(redraw.call_count, 77)
        self.assertEqual(receipt["counts"]["units"], 76)
        self.assertEqual(receipt["counts"]["claims"], 30)
        self.assertEqual(receipt["generation_after"], receipt["generation_before"] + 1)
        published = pub.read_projection(self.root)
        published_claims = {c for n in published["nodes"] for c in n["input_claim_refs"]}
        event_claims = {e["claim_id"] for s in receipt["filed_slices"] for e in s["events"]}
        self.assertTrue(event_claims <= published_claims)
        self.assertEqual(sum(n["event_kind"] == "moment" for n in published["nodes"]), 1000)
        self.assertEqual(original_receipts, {p: (self.root / p).read_bytes() for p in original_receipts})
        before = self.snapshot()
        with mock.patch.object(pub, "publish", wraps=pub.publish) as replay_publish:
            self.assertEqual(self.apply(proposal), receipt)
        self.assertEqual(replay_publish.call_count, 0)
        self.assertEqual(self.snapshot(), before)

    def test_no_group_still_publishes_once_and_no_change_redraw_keeps_generation(self):
        receipt = self.apply(self.offer(events=0))
        generation = receipt["generation_after"]
        before = pub.projection_path(self.root).read_bytes()
        with mock.patch.object(pub, "publish", wraps=pub.publish) as publish:
            with timeline.landmark_publication_batch(self.root):
                timeline.redraw_landmarks()
                timeline.redraw_landmarks()
        self.assertEqual(publish.call_count, 1)
        self.assertEqual(pub.published_generation(self.root), generation)
        self.assertEqual(pub.projection_path(self.root).read_bytes(), before)

    def test_empty_batch_and_empty_confirmation_write_nothing(self):
        proposal = self.offer()
        before = self.snapshot()
        with mock.patch.object(pub, "publish", wraps=pub.publish) as publish:
            with timeline.landmark_publication_batch(self.root):
                pass
            with self.assertRaises(lo.LandmarkOfferError):
                lo.apply(proposal["proposal_id"], [], self.root, now=NOW)
        self.assertEqual(publish.call_count, 0)
        self.assertEqual(self.snapshot(), before)

    def test_nested_same_vault_defers_only_to_outermost_success(self):
        with mock.patch.object(pub, "publish", wraps=pub.publish) as publish:
            with timeline.landmark_publication_batch(self.root):
                timeline.redraw_landmarks()
                with timeline.landmark_publication_batch(self.root):
                    timeline.redraw_landmarks()
                self.assertEqual(publish.call_count, 0)
            self.assertEqual(publish.call_count, 1)
            timeline.redraw_landmarks()
            self.assertEqual(publish.call_count, 2)

    def test_nested_failure_cannot_be_caught_and_published_as_success(self):
        with mock.patch.object(pub, "publish", wraps=pub.publish) as publish:
            with self.assertRaisesRegex(RuntimeError, "did not complete"):
                with timeline.landmark_publication_batch(self.root):
                    try:
                        with timeline.landmark_publication_batch(self.root):
                            timeline.redraw_landmarks()
                            raise RuntimeError("synthetic failure")
                    except RuntimeError:
                        pass
            self.assertEqual(publish.call_count, 0)
            timeline.redraw_landmarks()
            self.assertEqual(publish.call_count, 1)

    def test_cross_vault_and_binding_drift_refuse_before_other_vault_writes(self):
        other = self.root / "other"
        other.mkdir()
        with timeline.landmark_publication_batch(self.root):
            with mock.patch.object(timeline, "LANDMARKS_STORE", other / "state" / "landmarks.json"):
                for operation in (
                    lambda: timeline.redraw_landmarks(),
                    lambda: timeline.save_landmark("schools", {"domain": "schools", "label": "Academy"}),
                ):
                    with self.assertRaisesRegex(ValueError, "cannot cross vaults"):
                        operation()
                with self.assertRaisesRegex(ValueError, "cannot cross vaults"):
                    with timeline.landmark_publication_batch(other):
                        pass
        self.assertEqual(list(other.rglob("*")), [])
        with self.assertRaisesRegex(ValueError, "must match"):
            with timeline.landmark_publication_batch(other):
                pass

    def test_scope_checks_binding_again_at_exit_and_cleans_up(self):
        original = timeline.LANDMARKS_STORE
        try:
            with self.assertRaisesRegex(ValueError, "cannot cross vaults"):
                with timeline.landmark_publication_batch(self.root):
                    timeline.redraw_landmarks()
                    timeline.LANDMARKS_STORE = self.root / "other" / "state" / "landmarks.json"
        finally:
            timeline.LANDMARKS_STORE = original
        self.assertIsNone(pub.read_projection(self.root))
        timeline.redraw_landmarks()
        self.assertIsNotNone(pub.read_projection(self.root))

    def test_unrelated_execution_context_is_not_deferred(self):
        with mock.patch.object(pub, "publish", wraps=pub.publish) as publish:
            with timeline.landmark_publication_batch(self.root):
                timeline.redraw_landmarks()
                contextvars.Context().run(timeline.redraw_landmarks)
                self.assertEqual(publish.call_count, 1)
            self.assertEqual(publish.call_count, 2)

    def test_copied_context_cannot_defer_after_scope_closes(self):
        with mock.patch.object(pub, "publish", wraps=pub.publish) as publish:
            with timeline.landmark_publication_batch(self.root):
                timeline.redraw_landmarks()
                escaped = contextvars.copy_context()
            self.assertEqual(publish.call_count, 1)
            escaped.run(timeline.redraw_landmarks)
            self.assertEqual(publish.call_count, 2)
            escaped.run(timeline.redraw_landmarks)
            self.assertEqual(publish.call_count, 3)

    def test_mid_unit_failure_keeps_evidence_no_success_and_retry_no_duplicates(self):
        proposal = self.offer()
        original = writer.record_unit
        calls = 0

        def fail_second(*args, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise RuntimeError("synthetic unit failure")
            return original(*args, **kwargs)

        with mock.patch.object(writer, "record_unit", side_effect=fail_second), \
                mock.patch.object(pub, "publish", wraps=pub.publish) as publish:
            with self.assertRaises(lo.LandmarkOfferError) as caught:
                self.apply(proposal)
        self.assertEqual(caught.exception.code, "write_failure")
        self.assertEqual(publish.call_count, 0)
        self.assertEqual(len(lp.load_landmark_sources(self.root)), 1)
        self.assertIsNone(pub.read_projection(self.root))
        receipt = self.apply(proposal)
        self.assertEqual(len(lp.load_landmark_sources(self.root)), 2)
        self.assertEqual(receipt["counts"]["units"], 2)

    def test_final_publication_failure_leaves_no_success_receipt_and_retry_works(self):
        proposal = self.offer()
        receipt_id = lo.derive_receipt_id(proposal["proposal_id"],
                                         [u["unit_id"] for u in proposal["units"]])
        with mock.patch.object(pub, "publish", side_effect=OSError("synthetic disk failure")):
            with self.assertRaises(lo.LandmarkOfferError) as caught:
                self.apply(proposal)
        self.assertEqual(caught.exception.code, "write_failure")
        self.assertFalse(lo.offer_receipt_path(self.root, receipt_id).exists())
        original_receipts = {p: (self.root / p).read_bytes()
                             for p in ts.receipt_relative_paths(self.root)}
        receipt = self.apply(proposal)
        self.assertEqual(receipt["counts"]["claims"], 2)
        self.assertEqual(original_receipts, {p: (self.root / p).read_bytes() for p in original_receipts})
        self.assertEqual(len(lp.load_landmark_sources(self.root)), 2)

    def test_undo_then_replay_does_not_publish_or_revive(self):
        proposal = self.offer()
        receipt = self.apply(proposal)
        lo.retract(receipt["receipt_id"], self.root, now=NOW)
        before = self.snapshot()
        with mock.patch.object(pub, "publish", wraps=pub.publish) as publish:
            self.assertEqual(self.apply(proposal), receipt)
        self.assertEqual(publish.call_count, 0)
        self.assertEqual(self.snapshot(), before)

    def test_sequential_merge_and_supersession_are_visible_before_publication(self):
        with mock.patch.object(pub, "publish", wraps=pub.publish) as publish:
            with timeline.landmark_publication_batch(self.root):
                timeline.save_landmark("schools", {"domain": "schools", "label": "Academy", "grades": "1-6"})
                merged = timeline.save_landmark("schools", {"domain": "schools", "label": "Academy", "place": "Town"})
                self.assertEqual(merged["grades"], "1-6")
                self.assertEqual(merged["place"], "Town")
                timeline.save_landmark("partnerships", {"domain": "partnerships", "label": "Avery"})
                timeline.save_landmark("partnerships", {"domain": "partnerships", "none": True})
                self.assertEqual(self.entries("partnerships"), [{"domain": "partnerships", "none": True}])
                timeline.save_landmark("partnerships", {"domain": "partnerships", "label": "Jordan"})
                self.assertEqual([e["label"] for e in self.entries("partnerships")], ["Jordan"])
                self.assertEqual(publish.call_count, 0)
            self.assertEqual(publish.call_count, 1)
        self.assertTrue(ts.load_temporal_corrections(self.root))
        self.assertTrue(any(c["status"] == "superseded" for c in ts.fold_active_index(self.root)["claims"]))


class ReceiptReadBatchTests(OfferVaultCase):
    def setUp(self):
        super().setUp()
        seed_moments(self.root, 2)
        self.paths = ts.receipt_relative_paths(self.root)

    def test_unchanged_receipts_parse_once_but_every_fold_still_lists_paths(self):
        with mock.patch.object(ts, "receipt_from_dict", wraps=ts.receipt_from_dict) as parse, \
                mock.patch.object(ts, "receipt_relative_paths", wraps=ts.receipt_relative_paths) as listing:
            with ts.receipt_read_batch(self.root):
                first = ts.fold_active_index(self.root)
                second = ts.fold_active_index(self.root)
                self.assertEqual(first, second)
                self.assertEqual(parse.call_count, len(self.paths))
                self.assertEqual(listing.call_count, 2)
            self.assertEqual(ts.fold_active_index(self.root), first)
            self.assertEqual(parse.call_count, 2 * len(self.paths))

    def test_new_receipts_and_corrections_are_visible_in_the_next_fold(self):
        with ts.receipt_read_batch(self.root):
            before = ts.fold_active_index(self.root)
            claim = moment_claim({"source": "classification:synthetic-new#moment-new",
                                  "quote": "A new synthetic event.", "mention": "New event"})
            ts.write_receipt(self.root, {"source_ref": claim["source_ref"],
                                         "extractor_version": "classifier:1", "claims": [claim]}, now=NOW)
            after = ts.fold_active_index(self.root)
            self.assertEqual(after["counts"]["claims"], before["counts"]["claims"] + 1)
            ts.retract_claims(self.root, [claim["claim_id"]], reason="synthetic correction", occurred_at=NOW)
            corrected = ts.fold_active_index(self.root)
            self.assertEqual(next(c["status"] for c in corrected["claims"]
                                  if c["claim_id"] == claim["claim_id"]), "retracted")
        self.assertEqual(ts.fold_active_index(self.root), corrected)

    def test_reextraction_new_receipt_supersedes_cached_old_interpretation(self):
        relative = next(p for p in self.paths if "classifier" in (self.root / p).read_text())
        prior = json.loads((self.root / relative).read_text())
        with ts.receipt_read_batch(self.root):
            ts.fold_active_index(self.root)
            revised = dict(prior)
            revised["extractor_version"] = "classifier:2"
            revised["created_at"] = "2026-09-04T00:00:00Z"
            revised["claims"] = [{**claim, "extractor_version": "classifier:2",
                                   "created_at": revised["created_at"]} for claim in prior["claims"]]
            ts.write_receipt(self.root, revised, now=revised["created_at"])
            folded = ts.fold_active_index(self.root)
            self.assertTrue(all(c["status"] == "superseded" for c in folded["claims"]
                                if c["claim_id"] in {c["claim_id"] for c in prior["claims"]}))
        self.assertEqual(folded, ts.fold_active_index(self.root))

    def test_changed_unreadable_repaired_and_deleted_files_are_not_stale(self):
        relative = self.paths[0]
        path = self.root / relative
        original = path.read_bytes()
        with ts.receipt_read_batch(self.root):
            self.assertIsNotNone(ts.read_receipt(self.root, relative))
            path.write_text("invalid json")
            self.assertIsNone(ts.read_receipt(self.root, relative))
            self.assertIn(relative, ts.load_receipts(self.root)[1])
            path.write_bytes(original)
            self.assertIsNotNone(ts.read_receipt(self.root, relative))
            path.unlink()
            self.assertIsNone(ts.read_receipt(self.root, relative))
            self.assertEqual(len(ts.load_receipts(self.root)[0]), len(self.paths) - 1)

    def test_cached_objects_cannot_be_mutated_by_the_caller(self):
        relative = self.paths[0]
        with ts.receipt_read_batch(self.root):
            first = ts.read_receipt(self.root, relative)
            expected = first.to_dict()
            first.extractor["synthetic"] = "caller mutation"
            second = ts.read_receipt(self.root, relative)
            self.assertEqual(second.to_dict(), expected)
            second.extractor["synthetic"] = "another mutation"
            self.assertEqual(ts.read_receipt(self.root, relative).to_dict(), expected)

    def test_cache_never_weakens_immutable_write_conflict(self):
        relative = self.paths[0]
        path = self.root / relative
        original = path.read_bytes()
        with ts.receipt_read_batch(self.root):
            ts.read_receipt(self.root, relative)
            changed = json.loads(original)
            changed["claims"][0]["subject_mention"] = "Another subject"
            with self.assertRaises(ts.TemporalStoreError) as caught:
                ts.write_receipt(self.root, changed, now=NOW)
            self.assertEqual(caught.exception.code, "receipt_immutable_conflict")
        self.assertEqual(path.read_bytes(), original)

    def test_symlink_substitution_is_not_a_cache_hit(self):
        relative = self.paths[0]
        path = self.root / relative
        target = self.root / "preserved.json"
        with ts.receipt_read_batch(self.root):
            ts.read_receipt(self.root, relative)
            path.rename(target)
            path.symlink_to(target)
            with self.assertRaises(ts.TemporalStoreError):
                ts.read_receipt(self.root, relative)

    def test_cross_vault_refusal_and_exception_cleanup(self):
        other = self.root / "other"
        other.mkdir()
        with self.assertRaisesRegex(RuntimeError, "synthetic"):
            with ts.receipt_read_batch(self.root):
                ts.read_receipt(self.root, self.paths[0])
                with self.assertRaises(ts.TemporalStoreError):
                    ts.read_receipt(other, self.paths[0])
                with self.assertRaises(ts.TemporalStoreError):
                    with ts.receipt_read_batch(other):
                        pass
                raise RuntimeError("synthetic")
        with mock.patch.object(ts, "receipt_from_dict", wraps=ts.receipt_from_dict) as parse:
            ts.read_receipt(self.root, self.paths[0])
        self.assertEqual(parse.call_count, 1)

    def test_copied_context_cannot_reuse_closed_cache(self):
        relative = self.paths[0]
        with ts.receipt_read_batch(self.root):
            ts.read_receipt(self.root, relative)
            escaped = contextvars.copy_context()
        with mock.patch.object(ts, "receipt_from_dict", wraps=ts.receipt_from_dict) as parse:
            escaped.run(ts.read_receipt, self.root, relative)
            escaped.run(ts.read_receipt, self.root, relative)
        self.assertEqual(parse.call_count, 2)
