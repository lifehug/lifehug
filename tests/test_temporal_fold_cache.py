"""v318 — the incremental fold: same bytes, proportional cost.

The store's fold was a function of every receipt on disk and cost a full read
of all of them, four times per filing cycle. v318 keeps the function and
changes the reading: the receipts directory is walked on every call, and only
a file whose stat signature moved is opened, parsed and validated again.

Two promises, and this file exists to hold both at once:

1. **Nothing the fold produces may change.** Every test here that appends,
   edits, corrects or deletes something compares the incremental fold's bytes
   against a fold that read every file — not its parsed value, its bytes.
2. **A filing pays for what it filed.** The scaling tests count reads rather
   than seconds, because a wall clock measures the machine and a counter
   measures the algorithm.

Synthetic data only, built in the test; NEVER a real vault.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "system"))

import event_identity as ei  # noqa: E402
import temporal_claims as tc  # noqa: E402
import temporal_publication as pub  # noqa: E402
import temporal_store as ts  # noqa: E402
import temporal_timeline as tt  # noqa: E402

EXTRACTOR = tc.extractor_version_string(
    "listener", schema_version=1, prompt_version="f01ded", model="test-model"
)
CREATED = "2026-09-19T10:00:00Z"

#: Big enough that "reads everything" and "reads five things" are not the same
#: number by accident, small enough that the suite stays a suite. The v317 cost
#: of one fold over this vault is thousands of no-follow path validations; the
#: v318 cost of the second one is five.
SYNTHETIC_RECEIPTS = 3000


def synthetic_claim(index: int, *, best: str = "1994-05-01") -> dict:
    return {
        "claim_type": "date",
        "source_kind": "conversation",
        "subject_mention": f"synthetic subject {index}",
        "event_kind": "milestone",
        "temporal_value": {
            "best": best,
            "earliest": best,
            "latest": best,
            "granularity": "day",
            "confidence": "certain",
            "basis": "stated",
        },
        "evidence": [{"quote": f"synthetic sentence {index}", "turn_ref": f"turn-{index}"}],
        "basis": "explicit",
        "confidence": 0.9,
        "created_at": CREATED,
    }


class FoldCacheCase(unittest.TestCase):
    """A throwaway synthetic vault per test, built by this file and nothing else."""

    receipts = 12

    def setUp(self) -> None:
        self.vault = Path(tempfile.mkdtemp(prefix="lifehug-fold-cache-"))
        self.addCleanup(shutil.rmtree, self.vault, ignore_errors=True)
        self.addCleanup(ts.forget_fold_inputs)
        ts.forget_fold_inputs()
        self.filed = [self.file_one(index) for index in range(self.receipts)]

    # -- building a synthetic vault ---------------------------------------

    def file_one(self, index: int, *, best: str = "1994-05-01") -> dict:
        """Promote one synthetic utterance and file one receipt over it."""
        ref = ts.promote_conversational_source(
            self.vault,
            f"Synthetic utterance number {index}.",
            {"session_ref": "synthetic", "turn_ref": f"turn-{index}"},
        )
        claim = dict(
            synthetic_claim(index, best=best),
            source_ref=ref.to_dict(),
            extractor_version=EXTRACTOR,
        )
        payload = {
            "source_ref": ref.to_dict(),
            "extractor_version": EXTRACTOR,
            "created_at": CREATED,
            "claims": [claim],
        }
        # The claim's id is minted by the contract, not by this file, so the
        # id a correction later cites is read back off the normalized record
        # rather than guessed.
        normalized = tc.validate_extraction_receipt(payload)
        path = ts.write_receipt(self.vault, payload)
        return {"ref": ref, "claim": normalized["claims"][0], "path": path}

    # -- oracles ----------------------------------------------------------

    def full_bytes(self) -> str:
        """The fold that reads every file, in a process that remembers nothing."""
        ts.forget_fold_inputs(self.vault)
        return ts.active_index_bytes(ts.fold_active_index(self.vault, full=True))

    def incremental_bytes(self) -> str:
        return ts.active_index_bytes(ts.fold_active_index(self.vault))

    def assert_identical(self, message: str = "") -> str:
        incremental = self.incremental_bytes()
        self.assertEqual(incremental, self.full_bytes(), message)
        return incremental

    def counted_fold(self, **kwargs):
        with mock.patch.object(ts, "read_receipt", wraps=ts.read_receipt) as read:
            index = ts.fold_active_index(self.vault, **kwargs)
        return index, read.call_count


class ByteIdentityTests(FoldCacheCase):
    """The incremental read and the full read are the same fold."""

    def test_the_first_fold_of_a_vault_matches_a_full_read(self) -> None:
        self.assert_identical("a cold vault folds to the full read's bytes")

    def test_appending_receipts_is_byte_identical_to_a_full_rebuild(self) -> None:
        ts.rebuild_active_index(self.vault)
        for index in range(self.receipts, self.receipts + 5):
            self.file_one(index)
        self.assert_identical("five appended receipts fold like a whole re-read")

    def test_a_correction_is_byte_identical_to_a_full_rebuild(self) -> None:
        ts.rebuild_active_index(self.vault)
        ts.retract_claims(
            self.vault, [self.filed[0]["claim"]["claim_id"]],
            reason="Synthetic retraction", occurred_at=CREATED,
        )
        index = json.loads(self.assert_identical("a new correction folds like a re-read"))
        marked = next(row for row in index["claims"]
                      if row["claim_id"] == self.filed[0]["claim"]["claim_id"])
        self.assertEqual(marked["status"], "retracted")

    def test_reextraction_over_a_cached_receipt_is_byte_identical(self) -> None:
        ts.rebuild_active_index(self.vault)
        ref = self.filed[0]["ref"]
        later = tc.extractor_version_string(
            "listener", schema_version=1, prompt_version="beaded", model="test-model"
        )
        ts.write_receipt(self.vault, {
            "source_ref": ref.to_dict(),
            "extractor_version": later,
            "created_at": "2026-09-19T12:00:00Z",
            "claims": [dict(synthetic_claim(0, best="1994-06-01"),
                            source_ref=ref.to_dict(), extractor_version=later,
                            created_at="2026-09-19T12:00:00Z")],
        }, now="2026-09-19T12:00:00Z")
        index = json.loads(self.assert_identical("a second interpretation folds identically"))
        self.assertGreater(index["counts"]["superseded"], 0)

    def test_deleting_a_receipt_is_byte_identical_to_a_full_rebuild(self) -> None:
        ts.rebuild_active_index(self.vault)
        Path(self.filed[0]["path"]).unlink()
        index = json.loads(self.assert_identical("a removed receipt leaves no trace"))
        self.assertEqual(index["counts"]["receipts"], self.receipts - 1)

    def test_an_unreadable_receipt_is_reported_identically_either_way(self) -> None:
        ts.rebuild_active_index(self.vault)
        broken = Path(self.filed[0]["path"])
        broken.write_text("not json at all", encoding="utf-8")
        index = json.loads(self.assert_identical("an unparseable receipt is named, not hidden"))
        relative = broken.relative_to(self.vault).as_posix()
        self.assertEqual(index["unreadable_receipt_paths"], [relative])
        # And it is still named after the sidecar has recorded it as unreadable.
        ts.rebuild_active_index(self.vault)
        self.assertEqual(
            json.loads(self.assert_identical())["unreadable_receipt_paths"], [relative]
        )

    def test_rebuilding_repeatedly_never_drifts(self) -> None:
        first = ts.active_index_bytes(ts.rebuild_active_index(self.vault))
        for _ in range(3):
            self.assertEqual(ts.active_index_bytes(ts.rebuild_active_index(self.vault)), first)
        self.assertEqual(first, self.full_bytes())


class CacheInvalidationTests(FoldCacheCase):
    """Every way the cache can be wrong, and the same bytes out of each."""

    def cache(self) -> dict:
        return json.loads(ts.store_path(self.vault, ts.FOLD_CACHE_FILE).read_text())

    def test_touching_one_receipt_reparses_exactly_that_receipt(self) -> None:
        ts.rebuild_active_index(self.vault)
        ts.forget_fold_inputs(self.vault)
        path = Path(self.filed[0]["path"])
        # Same bytes, new signature: the cache keys on the file, not on a guess
        # about whether anybody would have changed it.
        payload = path.read_text(encoding="utf-8")
        path.write_text(payload, encoding="utf-8")
        _index, reads = self.counted_fold()
        self.assertEqual(reads, 1)
        self.assert_identical("a touched receipt is re-read and folds the same")

    def test_deleting_the_sidecar_falls_back_to_a_full_read(self) -> None:
        expected = ts.active_index_bytes(ts.rebuild_active_index(self.vault))
        ts.forget_fold_inputs(self.vault)
        ts.store_path(self.vault, ts.FOLD_CACHE_FILE).unlink()
        _index, reads = self.counted_fold()
        self.assertEqual(reads, self.receipts)
        self.assertEqual(self.incremental_bytes(), expected)

    def test_a_sidecar_whose_index_moved_is_refused(self) -> None:
        ts.rebuild_active_index(self.vault)
        ts.forget_fold_inputs(self.vault)
        # The index the sidecar describes is not the index on disk any more.
        index_path = ts.store_path(self.vault, tc.ACTIVE_INDEX_FILE)
        index_path.write_text(index_path.read_text() + "\n", encoding="utf-8")
        _index, reads = self.counted_fold()
        self.assertEqual(reads, self.receipts)
        self.assert_identical("a sidecar that no longer describes the index buys nothing")

    def test_a_sidecar_from_another_cache_version_is_refused(self) -> None:
        ts.rebuild_active_index(self.vault)
        ts.forget_fold_inputs(self.vault)
        path = ts.store_path(self.vault, ts.FOLD_CACHE_FILE)
        payload = json.loads(path.read_text())
        payload["cache_version"] = ts.FOLD_CACHE_VERSION + 1
        path.write_text(json.dumps(payload), encoding="utf-8")
        _index, reads = self.counted_fold()
        self.assertEqual(reads, self.receipts)

    def test_an_unparseable_sidecar_is_refused_rather_than_raised(self) -> None:
        ts.rebuild_active_index(self.vault)
        ts.forget_fold_inputs(self.vault)
        ts.store_path(self.vault, ts.FOLD_CACHE_FILE).write_text("{oh no", encoding="utf-8")
        _index, reads = self.counted_fold()
        self.assertEqual(reads, self.receipts)
        self.assert_identical("a corrupt sidecar is not a cache and not an error")

    def test_full_and_the_environment_switch_both_ignore_the_cache(self) -> None:
        ts.rebuild_active_index(self.vault)
        _index, reads = self.counted_fold(full=True)
        self.assertEqual(reads, self.receipts)
        ts.forget_fold_inputs(self.vault)
        with mock.patch.dict(os.environ, {ts.FOLD_CACHE_ENV: "0"}):
            _index, reads = self.counted_fold()
            self.assertEqual(reads, self.receipts)
            # And it writes no sidecar it would later be tempted to believe.
            ts.store_path(self.vault, ts.FOLD_CACHE_FILE).unlink()
            ts.rebuild_active_index(self.vault)
            self.assertFalse(ts.store_path(self.vault, ts.FOLD_CACHE_FILE).exists())

    def test_a_correction_edited_in_place_is_re_read(self) -> None:
        correction = ts.retract_claims(
            self.vault, [self.filed[0]["claim"]["claim_id"]],
            reason="Synthetic retraction", occurred_at=CREATED,
        )
        ts.rebuild_active_index(self.vault)
        ts.forget_fold_inputs(self.vault)
        path = self.vault / correction.relative_path
        path.unlink()
        index = json.loads(self.assert_identical("a deleted correction stops marking"))
        marked = next(row for row in index["claims"]
                      if row["claim_id"] == self.filed[0]["claim"]["claim_id"])
        self.assertEqual(marked["status"], "active")

    def test_an_index_with_a_claim_id_collision_falls_back_to_a_full_read(self) -> None:
        """The one thing the published index can lose, and the guard for it.

        ``entries`` is keyed by claim id, so two receipts filing the same claim
        id leave one row on disk where the fold saw two. The reconstruction
        refuses any index whose claim rows and claim counts disagree — here by
        simulating exactly that shape — rather than folding from a picture that
        is missing a row.
        """
        ts.rebuild_active_index(self.vault)
        ts.forget_fold_inputs(self.vault)
        index_path = ts.store_path(self.vault, tc.ACTIVE_INDEX_FILE)
        index = json.loads(index_path.read_text())
        index["claims"] = index["claims"][:-1]
        index_path.write_text(ts.active_index_bytes(index), encoding="utf-8")
        cache_path = ts.store_path(self.vault, ts.FOLD_CACHE_FILE)
        cache = json.loads(cache_path.read_text())
        cache["index_sha256"] = ts.hashlib.sha256(
            index_path.read_text().encode("utf-8")
        ).hexdigest()
        cache_path.write_text(json.dumps(cache), encoding="utf-8")
        _index, reads = self.counted_fold()
        self.assertEqual(reads, self.receipts)
        self.assert_identical("a lossy index is not an input")


class ScalingTests(FoldCacheCase):
    """The promise a large vault actually feels, counted rather than timed."""

    receipts = SYNTHETIC_RECEIPTS

    def test_a_filing_of_five_receipts_reads_five_receipts(self) -> None:
        ts.rebuild_active_index(self.vault)
        ts.forget_fold_inputs(self.vault)
        # A fresh process holding nothing but the sidecar beside the index —
        # which is exactly the hosted worker's situation on every invocation.
        _index, reads = self.counted_fold()
        self.assertEqual(reads, 0, "an unchanged vault re-reads nothing")

        for index in range(self.receipts, self.receipts + 5):
            self.file_one(index)
        ts.forget_fold_inputs(self.vault)
        index, reads = self.counted_fold()
        # Five receipts in, five receipts read — not three thousand and five.
        self.assertEqual(reads, 5)
        self.assertEqual(index["counts"]["receipts"], self.receipts + 5)
        self.assertEqual(
            ts.active_index_bytes(index),
            ts.active_index_bytes(ts.fold_active_index(self.vault, full=True)),
            "the five-read fold and the three-thousand-read fold are one fold",
        )

    def test_the_whole_cycle_after_an_append_reads_only_the_appended_files(self) -> None:
        """Index, manifest and publication, in the order a filing runs them."""
        ts.rebuild_active_index(self.vault)
        ei.rebuild_telling_manifest(self.vault)
        pub.publish(self.vault, now=CREATED)
        ts.forget_fold_inputs(self.vault)
        for index in range(self.receipts, self.receipts + 5):
            self.file_one(index)
        ts.forget_fold_inputs(self.vault)
        with mock.patch.object(ts, "read_receipt", wraps=ts.read_receipt) as read:
            ts.rebuild_active_index(self.vault)
            ei.rebuild_telling_manifest(self.vault)
            pub.publish(self.vault, now="2026-09-19T11:00:00Z")
        self.assertEqual(read.call_count, 5)


class TellingManifestTests(FoldCacheCase):
    """The manifest reads the same declarations without re-parsing the vault."""

    def test_the_manifest_is_byte_identical_incrementally_and_fully(self) -> None:
        ts.rebuild_active_index(self.vault)
        full = ei.telling_manifest_bytes(ei.rebuild_telling_manifest(self.vault, full=True))
        ts.forget_fold_inputs(self.vault)
        self.assertEqual(
            ei.telling_manifest_bytes(ei.rebuild_telling_manifest(self.vault)), full
        )
        for index in range(self.receipts, self.receipts + 3):
            self.file_one(index)
        ts.rebuild_active_index(self.vault)
        incremental = ei.telling_manifest_bytes(ei.rebuild_telling_manifest(self.vault))
        ts.forget_fold_inputs(self.vault)
        self.assertEqual(
            incremental,
            ei.telling_manifest_bytes(ei.rebuild_telling_manifest(self.vault, full=True)),
        )

    def test_a_declared_telling_key_survives_the_cache(self) -> None:
        """The extractor's own declaration is the one thing the index does not
        carry, so the sidecar carries it — and a manifest built from the cache
        must key the telling exactly as one built from the receipts does."""
        ref = ts.promote_conversational_source(
            self.vault, "A declared synthetic utterance.",
            {"session_ref": "synthetic", "turn_ref": "declared"},
        )
        payload = {
            "source_ref": ref.to_dict(),
            "extractor_version": EXTRACTOR,
            "created_at": CREATED,
            "claims": [dict(synthetic_claim(9001), source_ref=ref.to_dict(),
                            extractor_version=EXTRACTOR)],
        }
        claim_id = tc.validate_extraction_receipt(payload)["claims"][0]["claim_id"]
        payload["extractor"] = ei.declare_tellings(
            telling_keys={claim_id: f"{ref.source_id}#declared"},
        )
        ts.write_receipt(self.vault, payload)
        ts.rebuild_active_index(self.vault)
        full = ei.telling_manifest_bytes(ei.build_telling_manifest(
            self.vault, active_index=ts.fold_active_index(self.vault, full=True)
        ))
        ts.forget_fold_inputs(self.vault)
        declarations, unreadable = ts.receipt_declarations(self.vault)
        self.assertEqual(unreadable, [])
        self.assertIn(
            f"{ref.source_id}#declared",
            json.dumps([row.get("extractor") for row in declarations.values()]),
        )
        self.assertEqual(
            ei.telling_manifest_bytes(ei.build_telling_manifest(self.vault)), full
        )


class PublicationShortcutTests(FoldCacheCase):
    """The derive that a republish over unchanged inputs no longer pays for."""

    def derive_count(self, **kwargs) -> tuple[dict, int]:
        with mock.patch.object(
            tt, "derive_calculated_timeline", wraps=tt.derive_calculated_timeline
        ) as derive:
            summary = pub.publish(self.vault, **kwargs)
        return summary, derive.call_count

    def test_a_republish_over_unchanged_inputs_does_not_derive(self) -> None:
        first = pub.publish(self.vault, now=CREATED)
        self.assertFalse(first["unchanged"])
        summary, derives = self.derive_count(now=CREATED)
        self.assertEqual(derives, 0)
        self.assertTrue(summary["unchanged"])
        self.assertEqual(summary["generation"], first["generation"])
        self.assertEqual(summary["nodes"], first["nodes"])
        self.assertEqual(summary["work_items"], first["work_items"])
        self.assertEqual(summary["input_digest"], first["input_digest"])

    def test_a_moved_substrate_derives_and_publishes(self) -> None:
        first = pub.publish(self.vault, now=CREATED)
        self.file_one(self.receipts, best="1999-01-01")
        summary, derives = self.derive_count(now=CREATED)
        self.assertEqual(derives, 1)
        self.assertFalse(summary["unchanged"])
        self.assertEqual(summary["generation"], first["generation"] + 1)

    def test_a_new_day_derives_again(self) -> None:
        """Age frames make the projection a function of the day, so the
        shortcut is only ever taken inside the day that published it."""
        pub.publish(self.vault, now=CREATED)
        _summary, derives = self.derive_count(now="2026-09-20T10:00:00Z")
        self.assertEqual(derives, 1)

    def test_deleting_the_publication_cache_changes_no_answer(self) -> None:
        first = pub.publish(self.vault, now=CREATED)
        ts.store_path(self.vault, pub.PUBLICATION_CACHE_FILE).unlink()
        summary, derives = self.derive_count(now=CREATED)
        self.assertEqual(derives, 1)
        self.assertTrue(summary["unchanged"])
        self.assertEqual(summary["generation"], first["generation"])

    def test_an_edited_projection_is_never_treated_as_standing(self) -> None:
        pub.publish(self.vault, now=CREATED)
        path = pub.projection_path(self.vault)
        payload = json.loads(path.read_text())
        payload["nodes"] = []
        path.write_text(pub._canonical(payload), encoding="utf-8")
        _summary, derives = self.derive_count(now=CREATED)
        self.assertEqual(derives, 1)

    def test_the_repair_path_always_derives(self) -> None:
        pub.publish(self.vault, now=CREATED)
        _summary, derives = self.derive_count(now=CREATED, full=True)
        self.assertEqual(derives, 1)

    def test_verify_folds_from_the_receipts_themselves(self) -> None:
        pub.publish(self.vault, now=CREATED)
        with mock.patch.object(ts, "read_receipt", wraps=ts.read_receipt) as read:
            report = pub.verify(self.vault)
        self.assertTrue(report["identical"])
        self.assertEqual(read.call_count, self.receipts)


class ContractTests(FoldCacheCase):
    """Both caches are declared state, written through the vault's own writer."""

    def test_both_caches_are_declared_untracked_state(self) -> None:
        import vault_paths as vp  # noqa: PLC0415

        for name, relative in (
            ("temporal_fold_cache", ts.FOLD_CACHE_FILE),
            ("temporal_publication_cache", pub.PUBLICATION_CACHE_FILE),
        ):
            entry = vp.VAULT_DATA_PATHS[name]
            self.assertEqual(entry["external_path"], relative)
            self.assertEqual(entry["kind"], "file")
            self.assertFalse(entry["required"])
            self.assertIs(entry["tracked"], False)

    def test_both_caches_land_inside_the_vault_and_nowhere_else(self) -> None:
        ts.rebuild_active_index(self.vault)
        pub.publish(self.vault, now=CREATED)
        for relative in (ts.FOLD_CACHE_FILE, pub.PUBLICATION_CACHE_FILE):
            path = ts.store_path(self.vault, relative)
            self.assertTrue(path.is_file(), relative)
            self.assertTrue(path.is_relative_to(self.vault))
            self.assertFalse(path.is_symlink())

    def test_a_cache_path_that_escapes_the_vault_is_refused(self) -> None:
        with self.assertRaises(ts.TemporalStoreError):
            ts.store_path(self.vault, "../fold-cache.json")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
