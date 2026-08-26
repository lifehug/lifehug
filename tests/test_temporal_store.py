"""v221 — the receipt store, the fold, and the promoted source (plan §4.2, §4.1).

Wave B's exit gate is one sentence: *delete the active index, rebuild it from
the checked-in receipts, and get the same bytes back*. Most of this file exists
to make that sentence hard to break — including a randomized property test that
shuffles the order receipts are written in, because "deterministic" that only
holds for the order the author happened to try is not deterministic.

The rest pins the promises that make the invariant worth having: a promoted
message is filed once and cited forever, a receipt is never rewritten, a
correction changes a claim's status without removing it, a receipt written by a
schema version we have never seen still folds, and a crash between promoting a
source and filing its receipt leaves a state the next identical call completes.

Synthetic data only; NEVER references ~/Workspace/dave.
"""

from __future__ import annotations

import json
import random
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "system"))

import temporal_claims as tc  # noqa: E402
import temporal_store as ts  # noqa: E402

LISTENER = tc.extractor_version_string(
    "listener", schema_version=1, prompt_version="c0ffee", model="test-model"
)
RECORDER = tc.extractor_version_string(
    "recorder", schema_version=1, prompt_version="beaded", model="test-model"
)
PRESCREEN = tc.extractor_version_string("prescreen", rule_version="3")


def date_value(best: str, *, granularity: str = "day") -> dict:
    return {
        "best": best,
        "earliest": best,
        "latest": best,
        "granularity": granularity,
        "confidence": "certain",
        "basis": "stated",
    }


def claim(
    subject: str,
    event_kind: str,
    best: str,
    *,
    quote: str = "they said so",
    turn_ref: str = "turn-1",
    granularity: str = "day",
) -> dict:
    """A claim with everything the contract requires and nothing it does not."""
    return {
        "claim_type": "date",
        "source_kind": "conversation",
        "subject_mention": subject,
        "event_kind": event_kind,
        "temporal_value": date_value(best, granularity=granularity),
        "evidence": [{"quote": quote, "turn_ref": turn_ref}],
        "basis": "explicit",
        "confidence": 0.9,
    }


class StoreTestCase(unittest.TestCase):
    """A throwaway vault root per test, outside the repo and never ~/Workspace/dave."""

    def setUp(self) -> None:
        self.vault = Path(tempfile.mkdtemp(prefix="lifehug-temporal-store-"))
        self.addCleanup(shutil.rmtree, self.vault, ignore_errors=True)

    # -- helpers ----------------------------------------------------------

    def promote(self, text: str, **metadata: object) -> tc.SourceRef:
        return ts.promote_conversational_source(self.vault, text, metadata)

    def file_receipt(
        self,
        source_ref: tc.SourceRef,
        claims: list[dict],
        *,
        extractor_version: str = LISTENER,
        created_at: str = "2026-08-26T10:00:00Z",
        recorder: str | None = None,
    ) -> Path:
        payload: dict = {
            "source_ref": source_ref.to_dict(),
            "extractor_version": extractor_version,
            "created_at": created_at,
            "claims": [
                dict(item, source_ref=source_ref.to_dict(), extractor_version=extractor_version)
                for item in claims
            ],
        }
        if recorder:
            payload["recorder"] = recorder
        return ts.write_receipt(self.vault, payload)

    def files(self) -> list[str]:
        return sorted(
            path.relative_to(self.vault).as_posix()
            for path in self.vault.rglob("*")
            if path.is_file()
        )


# --------------------------------------------------------------------------
# Option B — the promoted conversational source
# --------------------------------------------------------------------------


class PromotedSourceTests(StoreTestCase):
    def test_a_message_becomes_a_vault_source_with_an_immutable_revision(self) -> None:
        ref = self.promote("We married in the spring of 1978.", session_ref="s1", turn_ref="t1")
        self.assertTrue(ref.source_id.startswith("conversation:msg-"))
        self.assertTrue(ref.revision.startswith("sha256:"))
        self.assertEqual(ref.source_path, ts.conversation_source_relative_path(
            ts.promotion_digest("We married in the spring of 1978.",
                                {"session_ref": "s1", "turn_ref": "t1"})
        ))
        self.assertTrue((self.vault / ref.source_path).is_file())
        # The revision is the source's own content digest, so a claim citing it
        # is pinned to the exact words that were read.
        body = ts.split_frontmatter((self.vault / ref.source_path).read_text())[1]
        self.assertEqual(f"sha256:{ts.payload_sha256(body)}", ref.revision)

    def test_promotion_is_idempotent_on_content_and_writes_no_second_file(self) -> None:
        first = self.promote("Ada was born in 1978.", session_ref="s1", turn_ref="t1")
        second = self.promote("Ada was born in 1978.", session_ref="s1", turn_ref="t1")
        self.assertEqual(first, second)
        self.assertEqual(len(self.files()), 1)

    def test_promotion_ignores_annotation_drift_between_attempts(self) -> None:
        """A retry that stamps a new clock or a different channel is the same message."""
        first = self.promote(
            "Ada was born in 1978.",
            session_ref="s1",
            turn_ref="t1",
            channel="telegram",
            occurred_at="2026-08-26T10:00:00Z",
        )
        second = self.promote(
            "Ada was born in 1978.",
            session_ref="s1",
            turn_ref="t1",
            channel="web",
            occurred_at="2026-08-27T22:41:03Z",
        )
        self.assertEqual(first, second)
        self.assertEqual(len(self.files()), 1)

    def test_the_same_words_in_a_different_turn_are_a_different_utterance(self) -> None:
        first = self.promote("We married in 1978.", session_ref="s1", turn_ref="t1")
        second = self.promote("We married in 1978.", session_ref="s1", turn_ref="t9")
        self.assertNotEqual(first.source_id, second.source_id)
        self.assertEqual(len(self.files()), 2)

    def test_one_message_with_three_facts_is_promoted_once(self) -> None:
        ref = self.promote(
            "I met Rosa in 1971, we married in 1978, and Ada came in 1981.",
            session_ref="s1",
            turn_ref="t1",
        )
        self.file_receipt(
            ref,
            [
                claim("Rosa", "first_met", "1971", granularity="year"),
                claim("Rosa", "married", "1978", granularity="year"),
                claim("Ada", "birth", "1981", granularity="year"),
            ],
        )
        index = ts.fold_active_index(self.vault)
        self.assertEqual(index["counts"]["sources"], 1)
        self.assertEqual(index["counts"]["receipts"], 1)
        self.assertEqual(index["counts"]["active"], 3)
        cited = {row["source_ref"]["source_id"] for row in index["claims"]}
        self.assertEqual(cited, {ref.source_id})

    def test_an_empty_message_is_refused_by_name(self) -> None:
        with self.assertRaises(ts.TemporalStoreError) as caught:
            self.promote("   \n  ")
        self.assertEqual(caught.exception.code, "message_text_required")

    def test_a_source_edited_under_its_claims_is_a_named_failure(self) -> None:
        ref = self.promote("Ada was born in 1978.", session_ref="s1", turn_ref="t1")
        path = self.vault / ref.source_path
        path.write_text(path.read_text().replace("1978", "1979"), encoding="utf-8")
        with self.assertRaises(ts.TemporalStoreError) as caught:
            ts.read_source_ref(self.vault, ref.source_path)
        self.assertEqual(caught.exception.code, "source_content_drifted")


# --------------------------------------------------------------------------
# The receipt store
# --------------------------------------------------------------------------


class ReceiptStoreTests(StoreTestCase):
    def test_a_receipt_lands_at_the_contract_derived_path(self) -> None:
        ref = self.promote("Ada was born in 1978.", session_ref="s1", turn_ref="t1")
        path = self.file_receipt(ref, [claim("Ada", "birth", "1978", granularity="year")])
        self.assertEqual(
            path.relative_to(self.vault).as_posix(),
            tc.receipt_relative_path(ref, LISTENER),
        )
        self.assertTrue(path.relative_to(self.vault).as_posix().startswith(tc.RECEIPTS_DIR))

    def test_refiling_the_same_receipt_writes_nothing_new(self) -> None:
        ref = self.promote("Ada was born in 1978.", session_ref="s1", turn_ref="t1")
        rows = [claim("Ada", "birth", "1978", granularity="year")]
        first = self.file_receipt(ref, rows)
        before = first.read_bytes()
        second = self.file_receipt(ref, rows)
        self.assertEqual(first, second)
        self.assertEqual(before, second.read_bytes())

    def test_rewriting_an_existing_receipt_is_refused_by_name(self) -> None:
        """Re-extraction writes a NEW receipt; it never edits an old one."""
        ref = self.promote("Ada was born in 1978.", session_ref="s1", turn_ref="t1")
        self.file_receipt(ref, [claim("Ada", "birth", "1978", granularity="year")])
        with self.assertRaises(ts.TemporalStoreError) as caught:
            self.file_receipt(ref, [claim("Ada", "birth", "1979", granularity="year")])
        self.assertEqual(caught.exception.code, "receipt_immutable_conflict")

    def test_a_receipt_may_not_cite_a_source_that_is_not_in_the_vault(self) -> None:
        ref = tc.SourceRef(
            source_id="conversation:msg-missing",
            revision="sha256:" + "1" * 64,
            source_path="sources/conversations/msg-missing.md",
        )
        with self.assertRaises(ts.TemporalStoreError) as caught:
            self.file_receipt(ref, [claim("Ada", "birth", "1978", granularity="year")])
        self.assertEqual(caught.exception.code, "receipt_source_missing")

    def test_reextraction_writes_a_new_receipt_beside_the_old_one(self) -> None:
        ref = self.promote("Ada was born in 1978.", session_ref="s1", turn_ref="t1")
        old = self.file_receipt(
            ref,
            [claim("Ada", "birth", "1978", granularity="year")],
            extractor_version=PRESCREEN,
            created_at="2026-08-20T10:00:00Z",
        )
        new = self.file_receipt(
            ref,
            [claim("Ada", "birth", "1978-04-02")],
            extractor_version=LISTENER,
            created_at="2026-08-26T10:00:00Z",
        )
        self.assertNotEqual(old, new)
        self.assertTrue(old.is_file())
        receipts, unreadable = ts.load_receipts(self.vault)
        self.assertEqual(unreadable, [])
        self.assertEqual(len(receipts), 2)

    def test_an_unknown_schema_version_receipt_still_loads(self) -> None:
        """Compat rule 2: a newer writer degrades to the fields we know."""
        ref = self.promote("Ada was born in 1978.", session_ref="s1", turn_ref="t1")
        path = self.file_receipt(ref, [claim("Ada", "birth", "1978", granularity="year")])
        payload = json.loads(path.read_text())
        payload["schema_version"] = 99
        payload["a_field_from_the_future"] = {"unknown": True}
        payload["claims"][0]["another_future_field"] = "ignored"
        path.write_text(json.dumps(payload), encoding="utf-8")

        receipt = ts.read_receipt(self.vault, path.relative_to(self.vault).as_posix())
        self.assertIsNotNone(receipt)
        assert receipt is not None
        self.assertEqual(len(receipt.claims), 1)
        index = ts.fold_active_index(self.vault)
        self.assertEqual(index["counts"]["active"], 1)
        self.assertEqual(index["unreadable_receipt_paths"], [])

    def test_an_unparseable_receipt_is_reported_and_never_silently_dropped(self) -> None:
        ref = self.promote("Ada was born in 1978.", session_ref="s1", turn_ref="t1")
        path = self.file_receipt(ref, [claim("Ada", "birth", "1978", granularity="year")])
        path.write_text("{not json", encoding="utf-8")
        index = ts.fold_active_index(self.vault)
        self.assertEqual(
            index["unreadable_receipt_paths"], [path.relative_to(self.vault).as_posix()]
        )


# --------------------------------------------------------------------------
# Corrections
# --------------------------------------------------------------------------


class CorrectionTests(StoreTestCase):
    def seeded_claim_id(self) -> str:
        ref = self.promote("Ada was born in 1978.", session_ref="s1", turn_ref="t1")
        self.file_receipt(ref, [claim("Ada", "birth", "1978", granularity="year")])
        return ts.fold_active_index(self.vault)["active_claim_ids"][0]

    def test_a_correction_is_a_durable_source_not_state(self) -> None:
        claim_id = self.seeded_claim_id()
        correction = ts.supersede_claims(
            self.vault, [claim_id], reason="She was born in 1979."
        )
        self.assertTrue(correction.relative_path.startswith(tc.CORRECTION_SOURCES_DIR))
        self.assertTrue((self.vault / correction.relative_path).is_file())
        self.assertEqual(correction.source_ref.source_path, correction.relative_path)

    def test_a_correction_flips_status_without_deleting_the_claim(self) -> None:
        claim_id = self.seeded_claim_id()
        ts.supersede_claims(self.vault, [claim_id], reason="She was born in 1979.")
        index = ts.fold_active_index(self.vault)
        self.assertEqual(index["counts"]["claims"], 1)
        self.assertEqual(index["counts"]["active"], 0)
        self.assertEqual(index["counts"]["superseded"], 1)
        row = index["claims"][0]
        self.assertEqual(row["claim_id"], claim_id)
        self.assertEqual(row["status"], "superseded")
        self.assertIn("1978", json.dumps(row["temporal_value"]))
        self.assertEqual(
            [mark["reason"] for mark in row["status_marks"]], ["correction_supersede"]
        )

    def test_every_correction_kind_maps_to_its_one_status(self) -> None:
        for kind, expected in sorted(ts.STATUS_BY_CORRECTION_KIND.items()):
            with self.subTest(kind=kind):
                vault = Path(tempfile.mkdtemp(prefix="lifehug-temporal-kind-"))
                self.addCleanup(shutil.rmtree, vault, ignore_errors=True)
                ref = ts.promote_conversational_source(
                    vault, "Ada was born in 1978.", {"session_ref": "s1", "turn_ref": "t1"}
                )
                ts.write_receipt(
                    vault,
                    {
                        "source_ref": ref.to_dict(),
                        "extractor_version": LISTENER,
                        "created_at": "2026-08-26T10:00:00Z",
                        "claims": [
                            dict(
                                claim("Ada", "birth", "1978", granularity="year"),
                                source_ref=ref.to_dict(),
                                extractor_version=LISTENER,
                            )
                        ],
                    },
                )
                claim_id = ts.fold_active_index(vault)["active_claim_ids"][0]
                ts.file_temporal_correction(
                    vault, kind=kind, claim_ids=[claim_id], reason=f"because {kind}"
                )
                index = ts.fold_active_index(vault)
                self.assertEqual(index["claims"][0]["status"], expected)
                self.assertEqual(index["counts"][expected], 1)

    def test_refiling_the_same_correction_is_one_record(self) -> None:
        claim_id = self.seeded_claim_id()
        first = ts.retract_claims(self.vault, [claim_id], reason="Never happened.")
        second = ts.retract_claims(self.vault, [claim_id], reason="Never happened.")
        self.assertEqual(first.correction_id, second.correction_id)
        self.assertEqual(first.relative_path, second.relative_path)
        self.assertEqual(len(ts.load_temporal_corrections(self.vault)), 1)

    def test_the_strongest_mark_wins_regardless_of_filing_order(self) -> None:
        claim_id = self.seeded_claim_id()
        ts.dispute_claims(self.vault, [claim_id], reason="Two sources disagree.")
        ts.retract_claims(self.vault, [claim_id], reason="It was never said.")
        ts.supersede_claims(self.vault, [claim_id], reason="A better reading exists.")
        index = ts.fold_active_index(self.vault)
        row = index["claims"][0]
        self.assertEqual(row["status"], "retracted")
        # Every mark survives — the resolution is visible, not silent.
        self.assertEqual(len(row["status_marks"]), 3)

    def test_a_correction_naming_an_unknown_claim_is_reported(self) -> None:
        self.seeded_claim_id()
        ts.retract_claims(self.vault, ["claim:" + "0" * 24], reason="A stale id.")
        index = ts.fold_active_index(self.vault)
        self.assertEqual(index["unresolved_correction_targets"], ["claim:" + "0" * 24])

    def test_a_correction_needs_a_kind_targets_and_a_reason(self) -> None:
        claim_id = self.seeded_claim_id()
        cases = (
            ({"kind": "delete", "claim_ids": [claim_id], "reason": "x"}, "correction_kind_unknown"),
            ({"kind": "retract", "claim_ids": [], "reason": "x"}, "correction_claim_ids_required"),
            ({"kind": "retract", "claim_ids": [claim_id], "reason": " "}, "correction_reason_required"),
        )
        for kwargs, code in cases:
            with self.subTest(code=code):
                with self.assertRaises(ts.TemporalStoreError) as caught:
                    ts.file_temporal_correction(self.vault, **kwargs)  # type: ignore[arg-type]
                self.assertEqual(caught.exception.code, code)

    def test_a_claim_that_supersedes_another_retires_it_in_the_fold(self) -> None:
        first = self.promote("Ada was born in 1978.", session_ref="s1", turn_ref="t1")
        self.file_receipt(first, [claim("Ada", "birth", "1978", granularity="year")])
        stale = ts.fold_active_index(self.vault)["active_claim_ids"][0]

        second = self.promote("No — Ada was born in 1979.", session_ref="s1", turn_ref="t2")
        row = claim("Ada", "birth", "1979", granularity="year")
        row["supersedes_claim_ids"] = [stale]
        self.file_receipt(second, [row], created_at="2026-08-26T11:00:00Z")

        index = ts.fold_active_index(self.vault)
        statuses = {item["claim_id"]: item["status"] for item in index["claims"]}
        self.assertEqual(statuses[stale], "superseded")
        self.assertEqual(len(index["active_claim_ids"]), 1)
        self.assertNotIn(stale, index["active_claim_ids"])


# --------------------------------------------------------------------------
# Re-extraction precedence
# --------------------------------------------------------------------------


class ReextractionTests(StoreTestCase):
    def test_the_latest_receipt_wins_and_the_earlier_reading_is_retained(self) -> None:
        ref = self.promote("Ada was born in April 1978.", session_ref="s1", turn_ref="t1")
        self.file_receipt(
            ref,
            [claim("Ada", "birth", "1978", granularity="year")],
            extractor_version=PRESCREEN,
            created_at="2026-08-20T10:00:00Z",
        )
        self.file_receipt(
            ref,
            [claim("Ada", "birth", "1978-04", granularity="month")],
            extractor_version=LISTENER,
            created_at="2026-08-26T10:00:00Z",
        )
        index = ts.fold_active_index(self.vault)
        self.assertEqual(index["counts"]["claims"], 2)
        self.assertEqual(index["counts"]["active"], 1)
        self.assertEqual(index["counts"]["superseded"], 1)
        active = ts.active_claims(index)[0]
        self.assertEqual(active["temporal_value"]["best"], "1978-04")
        self.assertEqual(active["extractor_version"], LISTENER)
        stale = [row for row in index["claims"] if row["status"] == "superseded"][0]
        self.assertEqual(
            [mark["reason"] for mark in stale["status_marks"]], ["reextracted"]
        )
        # One source revision, one selected receipt, both receipts on disk.
        self.assertEqual(index["counts"]["sources"], 1)
        self.assertEqual(index["counts"]["selected_receipts"], 1)
        self.assertEqual(index["counts"]["receipts"], 2)

    def test_a_different_source_revision_is_its_own_group(self) -> None:
        first = self.promote("Ada was born in 1978.", session_ref="s1", turn_ref="t1")
        second = self.promote("Bo was born in 1981.", session_ref="s1", turn_ref="t2")
        self.file_receipt(first, [claim("Ada", "birth", "1978", granularity="year")])
        self.file_receipt(second, [claim("Bo", "birth", "1981", granularity="year")])
        index = ts.fold_active_index(self.vault)
        self.assertEqual(index["counts"]["sources"], 2)
        self.assertEqual(index["counts"]["active"], 2)


# --------------------------------------------------------------------------
# THE INVARIANT
# --------------------------------------------------------------------------


class RebuildInvariantTests(StoreTestCase):
    """Wave B's exit gate: the index is rebuildable, exactly, from evidence."""

    def seed(self, vault: Path, *, shuffle_seed: int | None = None) -> None:
        """File the same evidence into ``vault``, optionally in a shuffled order."""
        messages = [
            ("I met Rosa in the fall of 1971.", "t1", [claim("Rosa", "first_met", "1971", granularity="year")]),
            ("We married on June 3rd, 1978.", "t2", [claim("Rosa", "married", "1978-06-03")]),
            ("Ada arrived in 1981.", "t3", [claim("Ada", "birth", "1981", granularity="year")]),
            ("Bo came two years later.", "t4", [claim("Bo", "birth", "1983", granularity="year")]),
        ]
        order = list(range(len(messages)))
        if shuffle_seed is not None:
            random.Random(shuffle_seed).shuffle(order)
        refs: dict[str, tc.SourceRef] = {}
        for position in order:
            text, turn, claims = messages[position]
            ref = ts.promote_conversational_source(
                vault, text, {"session_ref": "s1", "turn_ref": turn}
            )
            refs[turn] = ref
            payload = {
                "source_ref": ref.to_dict(),
                "extractor_version": LISTENER,
                "created_at": f"2026-08-2{position + 1}T10:00:00Z",
                "claims": [
                    dict(item, source_ref=ref.to_dict(), extractor_version=LISTENER)
                    for item in claims
                ],
            }
            ts.write_receipt(vault, payload)

        # A second interpretation of one source, so the fold has a group to
        # resolve rather than four singletons.
        ts.write_receipt(
            vault,
            {
                "source_ref": refs["t2"].to_dict(),
                "extractor_version": RECORDER,
                "created_at": "2026-08-26T10:00:00Z",
                "claims": [
                    dict(
                        claim("Rosa", "married", "1978-06-03"),
                        source_ref=refs["t2"].to_dict(),
                        extractor_version=RECORDER,
                    )
                ],
            },
        )
        # And a correction, so statuses are in play. The target id is read back
        # from the fold rather than re-derived here: the claim's identity is
        # computed over the NORMALIZED temporal value, and a test that re-derived
        # it from the raw input would pass while pointing at nothing.
        seeded = ts.fold_active_index(vault)
        bo = [row for row in seeded["claims"] if row["subject_mention"] == "Bo"][0]
        ts.dispute_claims(vault, [bo["claim_id"]], reason="Two sources disagree about Bo.")

    def test_deleting_the_index_and_rebuilding_is_byte_identical(self) -> None:
        self.seed(self.vault)
        path = ts.write_active_index(self.vault, ts.fold_active_index(self.vault))
        original = path.read_bytes()
        self.assertNotIn(b"generated_at", original)

        path.unlink()
        self.assertFalse(path.exists())
        rebuilt = ts.rebuild_active_index(self.vault)
        self.assertEqual(path.read_bytes(), original)
        self.assertEqual(ts.read_active_index(self.vault), rebuilt)

    def test_rebuilding_repeatedly_never_drifts(self) -> None:
        self.seed(self.vault)
        first = ts.active_index_bytes(ts.rebuild_active_index(self.vault))
        for _ in range(3):
            ts.active_index_path(self.vault).unlink()
            self.assertEqual(ts.active_index_bytes(ts.rebuild_active_index(self.vault)), first)

    def test_fold_is_order_independent_across_randomized_receipt_orderings(self) -> None:
        """The property: the fold reads a SET of receipts, not a sequence."""
        reference: str | None = None
        for seed in range(8):
            with self.subTest(seed=seed):
                vault = Path(tempfile.mkdtemp(prefix="lifehug-temporal-order-"))
                self.addCleanup(shutil.rmtree, vault, ignore_errors=True)
                self.seed(vault, shuffle_seed=seed)
                rendered = ts.active_index_bytes(ts.fold_active_index(vault))
                if reference is None:
                    reference = rendered
                else:
                    self.assertEqual(rendered, reference)
        assert reference is not None
        index = json.loads(reference)
        self.assertEqual(index["version"], ts.INDEX_VERSION)
        self.assertEqual(index["counts"]["claims"], 5)
        self.assertEqual(index["counts"]["active"], 3)
        self.assertEqual(index["counts"]["superseded"], 1)
        self.assertEqual(index["counts"]["disputed"], 1)

    def test_the_index_can_be_rebuilt_from_receipts_alone_after_it_is_lost(self) -> None:
        """The materialized view is disposable; the evidence is not."""
        self.seed(self.vault)
        expected = ts.active_index_bytes(ts.rebuild_active_index(self.vault))

        # Lose the ENTIRE state tree — index and receipts alike. The promoted
        # sources and the correction survive, because they are evidence.
        shutil.rmtree(self.vault / tc.TEMPORAL_STATE_DIR, ignore_errors=True)
        self.assertIsNone(ts.read_active_index(self.vault))
        self.assertEqual(ts.fold_active_index(self.vault)["counts"]["claims"], 0)

        self.seed(self.vault)
        self.assertEqual(ts.active_index_bytes(ts.rebuild_active_index(self.vault)), expected)


# --------------------------------------------------------------------------
# The pairing rule and the crash between the two writes
# --------------------------------------------------------------------------


class PairingRuleTests(StoreTestCase):
    def claims_for(self, ref: tc.SourceRef) -> list[dict]:
        return [
            claim("Rosa", "first_met", "1971", granularity="year"),
            claim("Rosa", "married", "1978", granularity="year"),
            claim("Ada", "birth", "1981", granularity="year"),
        ]

    def file(self) -> tuple[tc.SourceRef, Path]:
        return ts.file_message_extraction(
            self.vault,
            message_text="I met Rosa in 1971, we married in 1978, and Ada came in 1981.",
            extractor_version=LISTENER,
            claims_for=self.claims_for,
            metadata={"session_ref": "s1", "turn_ref": "t1"},
            recorder="listener",
        )

    def test_one_message_three_facts_one_source_one_receipt_three_active_claims(self) -> None:
        ref, receipt_path = self.file()
        self.assertEqual(
            self.files(),
            sorted(
                [
                    ref.source_path or "",
                    receipt_path.relative_to(self.vault).as_posix(),
                ]
            ),
        )
        index = ts.rebuild_active_index(self.vault)
        self.assertEqual(index["counts"]["sources"], 1)
        self.assertEqual(index["counts"]["receipts"], 1)
        self.assertEqual(len(index["active_claim_ids"]), 3)
        self.assertEqual(
            sorted(row["subject_mention"] for row in ts.active_claims(index)),
            ["Ada", "Rosa", "Rosa"],
        )

    def test_the_whole_filing_is_idempotent(self) -> None:
        first_ref, first_path = self.file()
        second_ref, second_path = self.file()
        self.assertEqual(first_ref, second_ref)
        self.assertEqual(first_path, second_path)
        self.assertEqual(len(self.files()), 2)

    def test_a_crash_between_the_source_and_the_receipt_is_re_runnable(self) -> None:
        """The source lands first, so the survivable half-state is the safe one."""
        ref = self.promote(
            "I met Rosa in 1971, we married in 1978, and Ada came in 1981.",
            session_ref="s1",
            turn_ref="t1",
        )
        # This is exactly the on-disk state after a crash between the two
        # writes: a promoted source, no receipt, an empty fold.
        self.assertEqual(self.files(), [ref.source_path])
        self.assertEqual(ts.fold_active_index(self.vault)["counts"]["claims"], 0)

        rerun_ref, receipt_path = self.file()
        self.assertEqual(rerun_ref, ref)
        self.assertEqual(len(self.files()), 2)
        self.assertTrue(receipt_path.is_file())
        self.assertEqual(len(ts.rebuild_active_index(self.vault)["active_claim_ids"]), 3)

    def test_no_receipt_can_cite_a_source_that_is_not_on_disk(self) -> None:
        """The reverse half-state is refused rather than written."""
        ref, receipt_path = self.file()
        receipt_path.unlink()
        (self.vault / (ref.source_path or "")).unlink()
        with self.assertRaises(ts.TemporalStoreError) as caught:
            ts.write_receipt(
                self.vault,
                {
                    "source_ref": ref.to_dict(),
                    "extractor_version": LISTENER,
                    "created_at": "2026-08-26T10:00:00Z",
                    "claims": [],
                },
            )
        self.assertEqual(caught.exception.code, "receipt_source_missing")

    def test_the_receipt_carries_the_shared_idempotency_key(self) -> None:
        ref, receipt_path = self.file()
        payload = json.loads(receipt_path.read_text())
        self.assertEqual(
            payload["idempotency_key"],
            tc.derive_extraction_idempotency_key(
                session_ref="s1",
                turn_ref="t1",
                source_ref=ref,
                recorder="listener",
                extractor_version=LISTENER,
            ),
        )


# --------------------------------------------------------------------------
# Contract registration and conventions
# --------------------------------------------------------------------------


class ContractRegistrationTests(unittest.TestCase):
    def contract(self) -> dict:
        return json.loads((ROOT / "system" / "vault_contract.json").read_text())

    def test_the_store_paths_are_registered_durable_data(self) -> None:
        """The store and the hosted mirror read one path table, not two."""
        data_paths = self.contract()["data_paths"]
        for name, expected in (
            ("temporal_claims_state", tc.TEMPORAL_STATE_DIR),
            ("temporal_receipts", tc.RECEIPTS_DIR),
            ("temporal_active_index", tc.ACTIVE_INDEX_FILE),
            ("conversation_sources", ts.CONVERSATION_SOURCES_DIR),
            ("correction_sources", tc.CORRECTION_SOURCES_DIR),
        ):
            with self.subTest(name=name):
                self.assertIn(name, data_paths)
                self.assertEqual(data_paths[name]["path"], expected)

    def test_the_active_index_declares_the_version_the_fold_writes(self) -> None:
        entry = self.contract()["data_paths"]["temporal_active_index"]
        self.assertEqual(entry["schema"]["version_field"], "version")
        self.assertIn(ts.INDEX_VERSION, entry["schema"]["supported"])

    def test_the_new_files_ship_in_the_framework_manifest(self) -> None:
        shipped = set(json.loads((ROOT / "system" / "version.json").read_text())["framework_files"])
        for name in (
            "system/temporal_store.py",
            "tests/test_temporal_store.py",
            "sources/conversations/.gitkeep",
        ):
            with self.subTest(name=name):
                self.assertIn(name, shipped)

    def test_frontmatter_matches_the_source_layer_it_files_into(self) -> None:
        """One frontmatter algorithm, pinned against ``source_integrity``'s.

        The store reimplements the emitter because importing ``source_integrity``
        reaches ``lifehug_core``, whose import binds the interpreter to a single
        vault root — and this store is told which vault on every call. The
        reimplementation is only legitimate while it is byte-identical, so this
        test is the seam that keeps it honest.
        """
        import source_integrity  # noqa: PLC0415

        metadata = {
            "content_sha256": "a" * 64,
            "immutable": True,
            "schema_version": 1,
            "source_id": "conversation:msg-abc",
            "source_path": "sources/conversations/msg-abc.md",
            "title": "A message",
            "type": "conversation_message",
            "zzz_unknown_key": ["kept", "sorted"],
        }
        self.assertEqual(
            ts.format_frontmatter(metadata, order=source_integrity.FRONTMATTER_ORDER),
            source_integrity.format_frontmatter(dict(metadata)),
        )
        rendered = ts.format_frontmatter(metadata)
        self.assertEqual(ts.split_frontmatter(f"{rendered}\n\nbody\n")[0], metadata)
        self.assertEqual(ts.payload_sha256("x"), source_integrity.payload_sha256("x"))
        self.assertEqual(
            ts.normalize_payload("a\r\nb\n"), source_integrity.normalize_payload("a\r\nb\n")
        )

    def test_every_public_name_is_exported(self) -> None:
        for name in ts.__all__:
            with self.subTest(name=name):
                self.assertTrue(hasattr(ts, name))

    def test_the_module_imports_without_binding_a_vault(self) -> None:
        """``import temporal_store`` must not choose a vault for the process."""
        source = (ROOT / "system" / "temporal_store.py").read_text()
        for forbidden in ("import lifehug_core", "from lifehug_core", "import source_integrity"):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, source)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
