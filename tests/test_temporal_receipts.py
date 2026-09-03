"""Cut 4c — the realized-gain receipt (decision record §4.5, §7 Cut 4;
execution plan "4c · OSS + platform · Realized-gain receipt; pending ->
published/failed on the page").

Every republish must record what actually changed between the previous
published generation and the new one, per affected node, so a host can say
"Moved 'College graduation' into North Desert Village. That narrowed three
related stories and placed one. Two items still need placing." from a
deterministic before/after receipt, never from a model.

Two layers are pinned here, deliberately kept separate:

* :class:`PureDiffTests` / :class:`RenderRealizedGainGoldenTests` exercise
  `temporal_receipts.diff_projections` and `render_realized_gain` directly,
  against hand-built projection payloads — the same style
  `tests/test_temporal_placement.py` uses for its own adapter, and for the
  same reason: the arithmetic under test is `timeline._record_width`, not
  the fold, and a hand-built fixture proves it without a real derive.
* :class:`ReceiptFileTests` exercises the real wiring — a real
  `temporal_publication.publish`, a real `temporal_store.file_ordering_
  constraint` move, a real fold — because the fixture-versus-seam
  distinction (Timeline Fix 08's own lesson, recorded on this program) is
  exactly what a fixture-only test cannot prove.

Synthetic data only; NEVER references ~/Workspace/dave.
"""

from __future__ import annotations

import hashlib
import io
import json
import shutil
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "system"))

import chronology as chrono  # noqa: E402
import lifehug  # noqa: E402
import temporal_claims as tc  # noqa: E402
import temporal_publication as pub  # noqa: E402
import temporal_receipts as trcpt  # noqa: E402
import temporal_store as ts  # noqa: E402

NOW = "2026-08-26T12:00:00Z"


def revision(seed: str) -> str:
    return "sha256:" + hashlib.sha256(seed.encode("utf-8")).hexdigest()


def claim(**overrides) -> dict:
    """One validated claim — the same door `tests/test_projection_publication.py`
    and `tests/test_temporal_timeline.py` use."""
    source = overrides.pop("source", "src-conversation-1")
    seed = overrides.pop("seed", source)
    payload = {
        "source_kind": "conversation",
        "source_ref": {"source_id": source, "revision": revision(seed)},
        "evidence": [{"quote": overrides.pop("quote", "a sentence from the conversation")}],
        "extractor_version": "listener:1",
        "created_at": "2026-08-26T00:00:00Z",
        "basis": "explicit",
        "confidence": 0.9,
        "status": "active",
    }
    payload.update(overrides)
    return tc.validate_temporal_claim(payload)


def date(best: str, granularity: str = "year", basis: str = "stated") -> dict:
    return chrono.DateRecord(
        best=best, earliest=best, latest=best, granularity=granularity,
        confidence="certain", basis=basis,
    ).to_dict()


def date_range(start: str, end: str, granularity: str = "range", basis: str = "stated") -> dict:
    return chrono.DateRecord(
        best=f"{start}/{end}", earliest=start, latest=end, granularity=granularity,
        confidence="certain", basis=basis,
    ).to_dict()


def node(node_id: str, node_kind: str, event_kind: str, *,
         best: object = None, possible: object = None) -> dict:
    """One hand-built node — `tests/test_temporal_placement.py`'s own `_node`
    pattern, extended with `possible_temporal_value` for the window case."""
    row = {
        "node_id": node_id, "node_kind": node_kind, "event_kind": event_kind,
        "subject_refs": [], "basis": "explicit",
        "input_claim_refs": ["claim:" + "a" * 24],
        "calculation_rule_version": "oracle:1",
    }
    if best is not None:
        row["best_temporal_value"] = best
    if possible is not None:
        row["possible_temporal_value"] = possible
    return row


def projection(generation: int, nodes: list) -> dict:
    return {"projection_generation": generation, "nodes": nodes}


# --------------------------------------------------------------------------
# The pure diff
# --------------------------------------------------------------------------


class PureDiffTests(unittest.TestCase):
    """`diff_projections` against hand-built payloads — no fold, no vault."""

    def test_first_publish_every_bounded_node_is_placed(self) -> None:
        after = projection(1, [
            node("n:a", "event", "story", best=date("2000")),
            node("n:b", "event", "story", best=date("2005")),
            node("n:c", "event", "story"),  # unbounded
        ])
        receipt = trcpt.diff_projections(None, after)
        self.assertIsNone(receipt["previous_generation"])
        self.assertEqual(receipt["generation"], 1)
        self.assertEqual(receipt["placed"], ["n:a", "n:b"])
        self.assertEqual(receipt["narrowed"], [])
        self.assertEqual(receipt["widened"], [])
        self.assertEqual(receipt["still_unplaced"], 1)
        self.assertEqual(receipt["summary"], {"placed": 2, "narrowed": 0, "widened": 0})

    def test_narrowed_placed_and_an_unrelated_node_in_neither(self) -> None:
        before = projection(1, [
            node("n:target", "event", "story"),  # unbounded
            node("n:wide", "event", "story", best=date_range("1980", "2020")),
            node("n:unrelated", "event", "story", best=date("1999")),
        ])
        after = projection(2, [
            node("n:target", "event", "story", best=date("2001")),  # placed
            node("n:wide", "event", "story", best=date_range("1990", "1995")),  # narrowed
            node("n:unrelated", "event", "story", best=date("1999")),  # unchanged
        ])
        receipt = trcpt.diff_projections(before, after)
        self.assertEqual(receipt["placed"], ["n:target"])
        self.assertEqual([row["node_id"] for row in receipt["narrowed"]], ["n:wide"])
        self.assertEqual(receipt["widened"], [])
        self.assertEqual(receipt["still_unplaced"], 0)
        for row in ("placed", "narrowed", "widened"):
            with self.subTest(row=row):
                ids = (receipt[row] if row == "placed"
                       else [entry["node_id"] for entry in receipt[row]])
                self.assertNotIn("n:unrelated", ids)
        narrowed_row = receipt["narrowed"][0]
        self.assertEqual(narrowed_row["before"], {"start": "1980", "end": "2020", "width": mock.ANY})
        self.assertEqual(narrowed_row["after"], {"start": "1990", "end": "1995", "width": mock.ANY})
        self.assertLess(narrowed_row["after"]["width"], narrowed_row["before"]["width"])

    def test_a_correction_that_widens_is_never_narrowed(self) -> None:
        before = projection(2, [node("n:target", "event", "story",
                                     best=date_range("2000", "2010"))])
        after = projection(3, [node("n:target", "event", "story",
                                    best=date_range("1995", "2015"))])
        receipt = trcpt.diff_projections(before, after)
        self.assertEqual(receipt["placed"], [])
        self.assertEqual(receipt["narrowed"], [])
        self.assertEqual([row["node_id"] for row in receipt["widened"]], ["n:target"])
        self.assertEqual(receipt["summary"], {"placed": 0, "narrowed": 0, "widened": 1})

    def test_a_window_possible_value_counts_as_bounded(self) -> None:
        """A node dated only by containment (`possible_temporal_value`, the
        `window` value_shape) has a real, finite interval — narrowing it is
        `narrowed`, exactly as a `best_temporal_value` narrowing is."""
        before = projection(1, [node("n:era", "period", "named_era",
                                     possible=date_range("1980", "2020"))])
        after = projection(2, [node("n:era", "period", "named_era",
                                    possible=date_range("1990", "1995"))])
        receipt = trcpt.diff_projections(before, after)
        self.assertEqual([row["node_id"] for row in receipt["narrowed"]], ["n:era"])

    def test_the_birth_node_and_age_frames_are_never_scored(self) -> None:
        """`temporal_placement._is_scored_node`'s own population, reused —
        the birth anchor and the age-frame ruler are excluded even when
        their own interval changes."""
        before = projection(1, [
            node("n:birth", "event", "birth", best=date("1980")),
            node("age:self:childhood", "period", "age_frame",
                 best=date_range("1980", "1992")),
        ])
        after = projection(2, [
            node("n:birth", "event", "birth", best=date("1981")),
            node("age:self:childhood", "period", "age_frame",
                 best=date_range("1981", "1993")),
        ])
        receipt = trcpt.diff_projections(before, after)
        self.assertEqual(receipt["placed"], [])
        self.assertEqual(receipt["narrowed"], [])
        self.assertEqual(receipt["widened"], [])
        self.assertEqual(receipt["still_unplaced"], 0)

    def test_a_no_op_republish_produces_an_empty_receipt(self) -> None:
        payload = projection(4, [
            node("n:a", "event", "story", best=date("2000")),
            node("n:b", "event", "story"),  # unbounded
        ])
        receipt = trcpt.diff_projections(payload, payload)
        self.assertEqual(receipt["summary"], {"placed": 0, "narrowed": 0, "widened": 0})
        self.assertEqual(receipt["placed"], [])
        self.assertEqual(receipt["narrowed"], [])
        self.assertEqual(receipt["widened"], [])
        self.assertEqual(receipt["still_unplaced"], 1)

    def test_deterministic_across_two_runs(self) -> None:
        before = projection(1, [node("n:a", "event", "story", best=date_range("1980", "2020"))])
        after = projection(2, [node("n:a", "event", "story", best=date_range("1990", "1995"))])
        first = trcpt.diff_projections(before, after)
        second = trcpt.diff_projections(before, after)
        self.assertEqual(first, second)

    def test_ordering_is_sorted_by_node_id(self) -> None:
        before = projection(1, [
            node("n:zebra", "event", "story", best=date_range("1980", "2020")),
            node("n:apple", "event", "story", best=date_range("1980", "2020")),
        ])
        after = projection(2, [
            node("n:zebra", "event", "story", best=date_range("1990", "1995")),
            node("n:apple", "event", "story", best=date_range("1990", "1995")),
        ])
        receipt = trcpt.diff_projections(before, after)
        self.assertEqual([row["node_id"] for row in receipt["narrowed"]], ["n:apple", "n:zebra"])

    def test_diff_projections_requires_an_after_payload(self) -> None:
        with self.assertRaises(trcpt.TemporalReceiptError):
            trcpt.diff_projections(None, None)  # type: ignore[arg-type]
        with self.assertRaises(trcpt.TemporalReceiptError):
            trcpt.diff_projections(None, "not a dict")  # type: ignore[arg-type]


# --------------------------------------------------------------------------
# The sentence
# --------------------------------------------------------------------------


def receipt_with(*, placed: int = 0, narrowed: int = 0, widened: int = 0,
                  still_unplaced: int = 0) -> dict:
    return {
        "generation": 2, "previous_generation": 1,
        "placed": [], "narrowed": [], "widened": [], "still_unplaced": still_unplaced,
        "summary": {"placed": placed, "narrowed": narrowed, "widened": widened},
    }


class RenderRealizedGainGoldenTests(unittest.TestCase):
    """Golden strings, in the `cross_dating.render_filing_gain` style."""

    def test_three_narrowed_one_placed_two_still_unplaced(self) -> None:
        receipt = receipt_with(placed=1, narrowed=3, still_unplaced=2)
        self.assertEqual(
            trcpt.render_realized_gain(receipt),
            "That narrowed three related stories and placed one. "
            "Two items still need placing.",
        )

    def test_empty_summary_reads_nothing_else_moved(self) -> None:
        receipt = receipt_with()
        self.assertEqual(trcpt.render_realized_gain(receipt), "Nothing else moved.")

    def test_one_narrowed_only(self) -> None:
        receipt = receipt_with(narrowed=1)
        self.assertEqual(
            trcpt.render_realized_gain(receipt), "That narrowed one related story."
        )

    def test_one_placed_only_singular_still_unplaced(self) -> None:
        receipt = receipt_with(placed=1, still_unplaced=1)
        self.assertEqual(
            trcpt.render_realized_gain(receipt),
            "That placed one. One item still needs placing.",
        )

    def test_widened_only(self) -> None:
        receipt = receipt_with(widened=2)
        self.assertEqual(
            trcpt.render_realized_gain(receipt), "That widened two."
        )

    def test_with_moved_and_target_labels(self) -> None:
        receipt = receipt_with(placed=1, narrowed=3, still_unplaced=2)
        self.assertEqual(
            trcpt.render_realized_gain(
                receipt, moved_label="College graduation",
                target_label="North Desert Village",
            ),
            "Moved 'College graduation' into North Desert Village. "
            "That narrowed three related stories and placed one. "
            "Two items still need placing.",
        )

    def test_a_partial_label_never_prefixes(self) -> None:
        receipt = receipt_with(narrowed=1)
        self.assertEqual(
            trcpt.render_realized_gain(receipt, moved_label="College graduation"),
            "That narrowed one related story.",
        )
        self.assertEqual(
            trcpt.render_realized_gain(receipt, target_label="North Desert Village"),
            "That narrowed one related story.",
        )

    def test_empty_summary_with_labels_still_names_the_move(self) -> None:
        receipt = receipt_with()
        self.assertEqual(
            trcpt.render_realized_gain(
                receipt, moved_label="A story", target_label="A container",
            ),
            "Moved 'A story' into A container. Nothing else moved.",
        )


# --------------------------------------------------------------------------
# The real wiring: publish(), a real move, the receipt file
# --------------------------------------------------------------------------


class VaultTestCase(unittest.TestCase):
    """A throwaway vault per test, outside the repo and never ~/Workspace/dave."""

    def setUp(self) -> None:
        self.vault = Path(tempfile.mkdtemp(prefix="lifehug-temporal-receipts-"))
        self.addCleanup(shutil.rmtree, self.vault, ignore_errors=True)
        (self.vault / "state").mkdir(parents=True, exist_ok=True)

    def file_claims(self, claims: list) -> None:
        by_source: dict[tuple[str, str], list[dict]] = {}
        for row in claims:
            ref = row["source_ref"]
            by_source.setdefault((ref["source_id"], ref["revision"]), []).append(dict(row))
        for (source_id, rev), rows in by_source.items():
            ts.write_receipt(
                self.vault,
                {
                    "source_ref": {"source_id": source_id, "revision": rev},
                    "extractor_version": "listener:1",
                    "claims": rows,
                },
            )

    def node_ids(self) -> dict:
        """Every `episode`-kind node's id, by its label — the shape a plain
        ``date``/``transition`` claim produces in this fold."""
        payload = pub.read_projection(self.vault)
        return {
            row["label"]: row["node_id"]
            for row in payload["nodes"] if row.get("node_kind") == "episode"
        }


class MovingOneNodeTests(VaultTestCase):
    """"Moving one node (file an ordering constraint via `temporal_store` on
    a fixture vault, republish) produces a receipt whose `narrowed` set
    equals exactly the nodes whose interval width decreased and `placed`
    equals those that went unbounded->bounded; an unrelated node appears in
    neither."" — the test point named in the task.
    """

    def setUp(self) -> None:
        super().setUp()
        self.birth = claim(claim_type="date", subject_mention="self", event_kind="birth",
                           temporal_value="1970-01-01", source="src-birth", seed="birth")
        self.grad = claim(claim_type="date", subject_mention="graduation",
                          event_kind="transition", temporal_value="2000",
                          source="src-grad", seed="grad")
        self.later = claim(claim_type="date", subject_mention="a later marker",
                           event_kind="transition", temporal_value="2010",
                           source="src-later", seed="later")
        self.unrelated = claim(claim_type="date", subject_mention="an unrelated moment",
                               event_kind="transition", temporal_value="1995",
                               source="src-unrelated", seed="unrelated")
        # The moved node: a `relative_order` claim citing an anchor nobody
        # defines, exactly `test_projection_publication.py`'s own
        # `waiting_on_an_anchor` shape — a real node that starts unplaced.
        self.target = claim(
            claim_type="relative_order", subject_mention="the summer job",
            event_kind="transition",
            temporal_value={"relation": "after", "anchors": ["nothing defines this"]},
            source="src-target", seed="target",
        )
        self.file_claims([self.birth, self.grad, self.later, self.unrelated, self.target])
        pub.publish(self.vault, now=NOW)
        ids = self.node_ids()
        self.target_id = ids["the summer job"]
        self.grad_id = ids["graduation"]
        self.later_id = ids["a later marker"]
        self.unrelated_id = ids["an unrelated moment"]

    def test_moving_the_node_places_it_and_leaves_the_unrelated_node_out(self) -> None:
        ts.file_ordering_constraint(
            self.vault, relation="after", subject_node_id=self.target_id,
            anchor_node_ids=[self.grad_id],
        )
        summary = pub.publish(self.vault, now="2026-08-26T13:00:00Z")
        receipt = summary["receipt"]
        self.assertEqual(receipt["previous_generation"], 1)
        self.assertEqual(receipt["placed"], [self.target_id])
        self.assertEqual(receipt["narrowed"], [])
        for row in ("placed", "narrowed", "widened"):
            ids = (receipt[row] if row == "placed"
                   else [entry["node_id"] for entry in receipt[row]])
            self.assertNotIn(self.unrelated_id, ids)
            self.assertNotIn(self.grad_id, ids)
        # The written file matches what publish() returned.
        on_disk = trcpt.read_receipt(self.vault, receipt["generation"])
        self.assertEqual(on_disk["placed"], receipt["placed"])
        self.assertEqual(on_disk["summary"], receipt["summary"])

    def test_a_second_bound_then_narrows_the_same_node(self) -> None:
        ts.file_ordering_constraint(
            self.vault, relation="after", subject_node_id=self.target_id,
            anchor_node_ids=[self.grad_id],
        )
        pub.publish(self.vault, now="2026-08-26T13:00:00Z")
        ts.file_ordering_constraint(
            self.vault, relation="before", subject_node_id=self.target_id,
            anchor_node_ids=[self.later_id],
        )
        summary = pub.publish(self.vault, now="2026-08-26T14:00:00Z")
        receipt = summary["receipt"]
        self.assertEqual(receipt["placed"], [])
        self.assertEqual([row["node_id"] for row in receipt["narrowed"]], [self.target_id])
        self.assertEqual(receipt["widened"], [])
        narrowed_row = receipt["narrowed"][0]
        self.assertLess(narrowed_row["after"]["width"], narrowed_row["before"]["width"])
        for row in ("placed", "narrowed", "widened"):
            ids = (receipt[row] if row == "placed"
                   else [entry["node_id"] for entry in receipt[row]])
            self.assertNotIn(self.unrelated_id, ids)

    def test_retracting_the_narrower_bound_widens_it_back(self) -> None:
        ts.file_ordering_constraint(
            self.vault, relation="after", subject_node_id=self.target_id,
            anchor_node_ids=[self.grad_id],
        )
        pub.publish(self.vault, now="2026-08-26T13:00:00Z")
        narrower = ts.file_ordering_constraint(
            self.vault, relation="before", subject_node_id=self.target_id,
            anchor_node_ids=[self.later_id],
        )
        pub.publish(self.vault, now="2026-08-26T14:00:00Z")
        correction = ts.retract_ordering_constraint(
            self.vault, narrower["constraint_id"], reason="wrong bound",
        )
        summary = pub.publish(
            self.vault, now="2026-08-26T15:00:00Z",
            correction_ref=correction.correction_id,
        )
        receipt = summary["receipt"]
        self.assertEqual(receipt["placed"], [])
        self.assertEqual(receipt["narrowed"], [])
        self.assertEqual([row["node_id"] for row in receipt["widened"]], [self.target_id])
        self.assertEqual(receipt["correction_ref"], correction.correction_id)
        on_disk = trcpt.read_receipt(self.vault, receipt["generation"])
        self.assertEqual(on_disk["correction_ref"], correction.correction_id)


class FirstPublishTests(VaultTestCase):
    def test_first_publish_every_bounded_node_is_placed_previous_generation_none(self) -> None:
        self.file_claims([
            claim(claim_type="date", subject_mention="self", event_kind="birth",
                  temporal_value="1970-01-01", source="src-birth", seed="birth"),
            claim(claim_type="date", subject_mention="graduation", event_kind="transition",
                  temporal_value="2000", source="src-grad", seed="grad"),
        ])
        summary = pub.publish(self.vault, now=NOW)
        receipt = summary["receipt"]
        self.assertIsNone(receipt["previous_generation"])
        self.assertEqual(receipt["generation"], 1)
        self.assertGreaterEqual(receipt["summary"]["placed"], 1)
        self.assertNotIn("correction_ref", receipt)


class NoOpAndAtomicityTests(VaultTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.file_claims([
            claim(claim_type="date", subject_mention="self", event_kind="birth",
                  temporal_value="1970-01-01", source="src-birth", seed="birth"),
            claim(claim_type="date", subject_mention="graduation", event_kind="transition",
                  temporal_value="2000", source="src-grad", seed="grad"),
        ])

    def test_a_no_op_republish_writes_no_new_receipt(self) -> None:
        first = pub.publish(self.vault, now=NOW)
        self.assertFalse(first["unchanged"])
        second = pub.publish(self.vault, now=NOW)
        self.assertTrue(second["unchanged"])
        self.assertEqual(second["generation"], first["generation"])
        self.assertIsNone(second["receipt"])
        self.assertIsNone(trcpt.read_receipt(self.vault, 2))
        self.assertIsNotNone(trcpt.read_receipt(self.vault, 1))

    def test_a_receipt_exists_for_every_published_generation_and_verify_still_passes(
        self,
    ) -> None:
        gens = []
        for index in range(3):
            self.file_claims([
                claim(claim_type="date", subject_mention=f"marker {index}",
                      event_kind="transition", temporal_value=f"{2001 + index}",
                      source=f"src-marker-{index}", seed=f"marker-{index}"),
            ])
            summary = pub.publish(self.vault, now=f"2026-08-26T1{index}:00:00Z")
            gens.append(summary["generation"])
        self.assertEqual(gens, [1, 2, 3])
        for generation in gens:
            with self.subTest(generation=generation):
                self.assertIsNotNone(trcpt.read_receipt(self.vault, generation))
        report = pub.verify(self.vault)
        self.assertTrue(report["identical"], report.get("differences"))

    def test_rebuild_still_produces_a_receipt_and_passes_verify(self) -> None:
        pub.publish(self.vault, now=NOW)
        pub.projection_path(self.vault).unlink(missing_ok=True)
        pub.work_items_path(self.vault).unlink(missing_ok=True)
        summary = pub.publish(self.vault, now=NOW)
        self.assertEqual(summary["generation"], 1)
        self.assertIsNotNone(trcpt.read_receipt(self.vault, 1))
        report = pub.verify(self.vault)
        self.assertTrue(report["identical"], report.get("differences"))


class DeterminismAcrossVaultsTests(unittest.TestCase):
    """"Publishing twice from the same sources yields byte-equal receipts
    (modulo generation numbers, which must be strictly increasing)."" — two
    FRESH, identically-built vaults publish the same generation 1 receipt.
    """

    def build(self) -> Path:
        vault = Path(tempfile.mkdtemp(prefix="lifehug-temporal-receipts-det-"))
        self.addCleanup(shutil.rmtree, vault, ignore_errors=True)
        (vault / "state").mkdir(parents=True, exist_ok=True)
        claims = [
            claim(claim_type="date", subject_mention="self", event_kind="birth",
                  temporal_value="1970-01-01", source="src-birth", seed="birth"),
            claim(claim_type="date", subject_mention="graduation", event_kind="transition",
                  temporal_value="2000", source="src-grad", seed="grad"),
            claim(claim_type="date", subject_mention="a later marker",
                  event_kind="transition", temporal_value="2010",
                  source="src-later", seed="later"),
        ]
        by_source: dict[tuple[str, str], list[dict]] = {}
        for row in claims:
            ref = row["source_ref"]
            by_source.setdefault((ref["source_id"], ref["revision"]), []).append(dict(row))
        for (source_id, rev), rows in by_source.items():
            ts.write_receipt(
                vault,
                {"source_ref": {"source_id": source_id, "revision": rev},
                 "extractor_version": "listener:1", "claims": rows},
            )
        return vault

    def test_two_fresh_vaults_from_identical_sources_publish_byte_equal_receipts(
        self,
    ) -> None:
        vault_a, vault_b = self.build(), self.build()
        summary_a = pub.publish(vault_a, now=NOW)
        summary_b = pub.publish(vault_b, now=NOW)
        self.assertEqual(summary_a["generation"], summary_b["generation"])
        self.assertGreater(summary_a["generation"], 0)
        receipt_a = trcpt.read_receipt(vault_a, summary_a["generation"])
        receipt_b = trcpt.read_receipt(vault_b, summary_b["generation"])
        self.assertEqual(receipt_a, receipt_b)


class ErrorPathTests(unittest.TestCase):
    def test_receipt_relative_path_rejects_a_non_positive_generation(self) -> None:
        for bad in (0, -1, "not-a-number", None):
            with self.subTest(bad=bad):
                with self.assertRaises(trcpt.TemporalReceiptError):
                    trcpt.receipt_relative_path(bad)

    def test_read_receipt_returns_none_for_an_unpublished_generation(self) -> None:
        vault = Path(tempfile.mkdtemp(prefix="lifehug-temporal-receipts-err-"))
        self.addCleanup(shutil.rmtree, vault, ignore_errors=True)
        self.assertIsNone(trcpt.read_receipt(vault, 1))
        self.assertIsNone(trcpt.latest_receipt_generation(vault))


# --------------------------------------------------------------------------
# The CLI
# --------------------------------------------------------------------------


class CliTests(VaultTestCase):
    def run_command(self, argv: list[str]) -> tuple[int, str]:
        parser = lifehug.build_parser()
        args = parser.parse_args(argv)
        buffer = io.StringIO()
        with mock.patch.object(lifehug, "REPO_DIR", self.vault), redirect_stdout(buffer):
            code = args.func(args)
        return code, buffer.getvalue()

    def test_prints_the_latest_receipt_as_json_by_default(self) -> None:
        self.file_claims([
            claim(claim_type="date", subject_mention="self", event_kind="birth",
                  temporal_value="1970-01-01", source="src-birth", seed="birth"),
            claim(claim_type="date", subject_mention="graduation", event_kind="transition",
                  temporal_value="2000", source="src-grad", seed="grad"),
        ])
        summary = pub.publish(self.vault, now=NOW)
        code, output = self.run_command(["timeline-receipt"])
        self.assertEqual(code, 0)
        payload = json.loads(output)
        self.assertEqual(payload["generation"], summary["generation"])

    def test_generation_flag_selects_an_older_receipt(self) -> None:
        self.file_claims([
            claim(claim_type="date", subject_mention="self", event_kind="birth",
                  temporal_value="1970-01-01", source="src-birth", seed="birth"),
            claim(claim_type="date", subject_mention="graduation", event_kind="transition",
                  temporal_value="2000", source="src-grad", seed="grad"),
        ])
        pub.publish(self.vault, now=NOW)
        self.file_claims([
            claim(claim_type="date", subject_mention="a later marker",
                  event_kind="transition", temporal_value="2010",
                  source="src-later", seed="later"),
        ])
        pub.publish(self.vault, now="2026-08-26T13:00:00Z")
        code, output = self.run_command(["timeline-receipt", "--generation", "1"])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(output)["generation"], 1)

    def test_no_publication_yet_is_a_clean_failure(self) -> None:
        code, _ = self.run_command(["timeline-receipt"])
        self.assertEqual(code, 1)

    def test_timeline_receipt_is_classified_read_only(self) -> None:
        self.assertIn("timeline-receipt", lifehug.READ_ONLY_COMMANDS)
        self.assertNotIn("timeline-receipt", lifehug.DIRECT_MUTATION_COMMANDS)
        self.assertNotIn("timeline-receipt", lifehug.QUEUED_MUTATION_COMMANDS)


if __name__ == "__main__":
    unittest.main()
