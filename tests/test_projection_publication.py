"""v231 — the projection lands (audited timeline build plan §7, §7.1, §10).

Wave D item D3. The derivation existed and nothing wrote it down; the queue and
Mirror both read a file nobody published. These tests are organized around §7's
own four sentences — *whole*, *atomic*, *generation*, *rebuildable* — plus the
two seams that now have a real producer: wave F's question queue
(`question_planner`) and wave E's Mirror rows (`mirror_work`).

The cross-module tests deliberately use a REAL derivation, a REAL publish and
the consumers' REAL readers against a temp vault. A hand-written stand-in for
the published file would test the fixture, not the seam, and the seam is the
thing that was broken.

Synthetic data only; NEVER references ~/Workspace/dave.
"""

from __future__ import annotations

import copy
import hashlib
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "system"))

import chronology as chrono  # noqa: E402
import general_listener as gl  # noqa: E402
import landmark_recorder as lr  # noqa: E402
import mirror_work  # noqa: E402
import question_planner as qp  # noqa: E402
import temporal_claims as tc  # noqa: E402
import temporal_projection as tp  # noqa: E402
import temporal_publication as pub  # noqa: E402
import temporal_store as ts  # noqa: E402
import temporal_timeline as tt  # noqa: E402
import timeline  # noqa: E402

NOW = "2026-08-26T12:00:00Z"
EMPTY_BANK = "# Questions\n\n## A: Origins\n\n- [ ] A1: Where does your story start?\n"


def revision(seed: str) -> str:
    return "sha256:" + hashlib.sha256(seed.encode("utf-8")).hexdigest()


def claim(**overrides) -> dict:
    """One validated claim — `tests/test_temporal_timeline.py`'s own door."""
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


def waiting_on_an_anchor(count: int = 5) -> list[dict]:
    """`count` events waiting on one unresolved anchor: a high-reach
    `missing_anchor`, which is the shape wave F's queue exists to admit."""
    return [
        claim(
            claim_type="relative_order",
            subject_mention=f"thing {index}",
            event_kind="transition",
            temporal_value={"relation": "after", "anchors": ["the big move"]},
            seed=f"waiting-{index}",
        )
        for index in range(count)
    ]


def disagreeing() -> list[dict]:
    """Two incompatible explicit dates — §10's contradiction, Mirror's row."""
    return [
        claim(claim_type="date", subject_mention="Katie", event_kind="married",
              temporal_value="1998-06-20", source="src-a", seed="a"),
        claim(claim_type="date", subject_mention="Katie", event_kind="married",
              temporal_value="1999-06-20", source="src-b", seed="b"),
    ]


def date(best: str, *, granularity: str = "year") -> dict:
    return chrono.DateRecord(
        best=best, earliest=best, latest=best, granularity=granularity,
        confidence="certain", basis="stated",
    ).to_dict()


class VaultTestCase(unittest.TestCase):
    """A throwaway vault per test, outside the repo and never ~/Workspace/dave."""

    def setUp(self) -> None:
        self.vault = Path(tempfile.mkdtemp(prefix="lifehug-projection-publish-"))
        self.addCleanup(shutil.rmtree, self.vault, ignore_errors=True)
        (self.vault / "state").mkdir(parents=True, exist_ok=True)

    def file_claims(self, claims, *, source: str = "src-seed") -> None:
        """Put claims into the substrate the way a host does: receipts.

        One receipt per (source revision, extractor) — the contract a receipt
        IS — so a fixture spanning several conversations files several, exactly
        as the recorder would.
        """
        del source
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

    def published(self) -> dict:
        payload = pub.read_projection(self.vault)
        assert payload is not None
        return payload

    def queue_slice(self) -> dict:
        payload = pub.read_work_items(self.vault)
        assert payload is not None
        return payload


# --------------------------------------------------------------------------
# "A whole materialized projection"
# --------------------------------------------------------------------------


class WholeProjectionTests(VaultTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.file_claims(waiting_on_an_anchor() + disagreeing())

    def test_publishing_writes_both_files_of_one_generation(self) -> None:
        summary = pub.publish(self.vault, now=NOW)
        self.assertEqual(summary["generation"], 1)
        self.assertTrue(pub.projection_path(self.vault).is_file())
        self.assertTrue(pub.work_items_path(self.vault).is_file())
        self.assertEqual(self.published()["projection_generation"], 1)
        self.assertEqual(self.queue_slice()["projection_generation"], 1)

    def test_the_projection_is_the_whole_derivation_not_a_summary(self) -> None:
        """§7: a WHOLE materialized projection. Every key
        `CalculatedTimeline.to_dict()` produces survives the envelope."""
        pub.publish(self.vault, now=NOW)
        payload = self.published()
        fresh = tt.derive_calculated_timeline(
            ts.rebuild_active_index(self.vault), projection_generation=1, now=NOW
        )
        for key in fresh.to_dict():
            self.assertIn(key, payload, f"the published projection dropped {key}")
        self.assertTrue(payload["nodes"])
        self.assertTrue(payload["work_items"])

    def test_every_node_carries_the_generation_it_was_published_in(self) -> None:
        pub.publish(self.vault, now=NOW)
        # A SECOND publication needs something new to say: an unchanged
        # republish is a semantic no-op (eras E1, design §3.4).
        self.file_claims([claim(claim_type="date", subject_mention="the big move",
                                event_kind="transition", temporal_value="1994",
                                source="src-anchor", seed="anchor")])
        pub.publish(self.vault, now=NOW)
        for node in self.published()["nodes"]:
            self.assertEqual(node["projection_generation"], 2)

    def test_the_queue_slice_is_the_same_generations_items_not_a_second_derivation(self) -> None:
        pub.publish(self.vault, now=NOW)
        projection, queue = self.published(), self.queue_slice()
        self.assertEqual(queue["work_items"], projection["work_items"])
        self.assertEqual(queue["reach"], projection["reach"])
        self.assertEqual(queue["projection_generation"], projection["projection_generation"])
        self.assertEqual(queue["input_digest"], projection["input_digest"])

    def test_an_empty_substrate_publishes_an_empty_generation_not_nothing(self) -> None:
        """An honest empty projection is not the same fact as no projection,
        and only one of the two is a reason for a page to say "not yet"."""
        empty = Path(tempfile.mkdtemp(prefix="lifehug-projection-empty-"))
        self.addCleanup(shutil.rmtree, empty, ignore_errors=True)
        summary = pub.publish(empty, now=NOW)
        self.assertEqual(summary["nodes"], 0)
        self.assertTrue(pub.read_projection(empty))
        self.assertEqual(pub.calculated_view(empty)["published"], True)


# --------------------------------------------------------------------------
# "Publication is atomic"
# --------------------------------------------------------------------------


class AtomicityTests(VaultTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.file_claims(waiting_on_an_anchor())

    def test_the_order_is_declared_and_the_projection_goes_first(self) -> None:
        """The order IS the atomicity guarantee for the second file: the queue
        is allowed to trail the truth, never to run ahead of it."""
        self.assertEqual(pub.PUBLICATION_ORDER, (pub.PROJECTION_FILE, pub.WORK_ITEMS_FILE))
        seen: list[str] = []
        real = pub._write

        def spy(vault_root, relative, text):
            seen.append(relative)
            return real(vault_root, relative, text)

        with mock.patch.object(pub, "_write", spy):
            pub.publish(self.vault, now=NOW)
        self.assertEqual(seen, list(pub.PUBLICATION_ORDER))

    def test_a_payload_that_cannot_be_rendered_changes_nothing_on_disk(self) -> None:
        """Both payloads are built and serialized before either is written, so
        a failure in the second one is not half a publication."""
        pub.publish(self.vault, now=NOW)
        before = pub.projection_path(self.vault).read_text(encoding="utf-8")
        with mock.patch.object(pub, "work_items_payload", side_effect=RuntimeError("boom")), \
                self.assertRaises(RuntimeError):
            pub.publish(self.vault, now=NOW)
        self.assertEqual(pub.projection_path(self.vault).read_text(encoding="utf-8"), before)
        self.assertEqual(self.published()["projection_generation"], 1)

    def test_a_crash_between_the_two_files_leaves_a_re_runnable_state(self) -> None:
        """The torn state §7 admits: the truth is current, the queue is one
        generation behind. Never the reverse, and always repaired by re-running
        the same call — which is why the next generation is taken from the MAX
        across both files rather than from the projection alone."""
        pub.publish(self.vault, now=NOW)
        self.file_claims(disagreeing())
        real = pub._write

        def tear(vault_root, relative, text):
            if relative == pub.WORK_ITEMS_FILE:
                raise pub.TemporalPublicationError("publication_unwritable", "crash")
            return real(vault_root, relative, text)

        with mock.patch.object(pub, "_write", tear), \
                self.assertRaises(pub.TemporalPublicationError):
            pub.publish(self.vault, now=NOW)

        self.assertEqual(self.published()["projection_generation"], 2)
        self.assertEqual(self.queue_slice()["projection_generation"], 1)
        self.assertEqual(pub.published_generation(self.vault), 2)

        # And the repair needs NO new evidence: the two files disagree about
        # their generation, and a torn pair is never a no-op.
        summary = pub.publish(self.vault, now=NOW)
        self.assertFalse(summary["unchanged"])
        self.assertEqual(summary["generation"], 3)
        self.assertEqual(self.published()["projection_generation"], 3)
        self.assertEqual(self.queue_slice()["projection_generation"], 3)

    def test_a_reader_never_sees_a_partial_file(self) -> None:
        """Whole-file replacement: the temp file is renamed into place, so the
        path either holds the previous complete generation or the next one."""
        pub.publish(self.vault, now=NOW)
        first = json.loads(pub.projection_path(self.vault).read_text(encoding="utf-8"))
        self.file_claims(disagreeing())
        seen = {}

        def peek():
            seen["mid"] = json.loads(
                pub.projection_path(self.vault).read_text(encoding="utf-8")
            )

        from vault_paths import atomic_write_vault_text as real_write

        def watched(path, content, *, vault_root, **kwargs):
            if Path(path).name == Path(pub.PROJECTION_FILE).name:
                kwargs["_before_replace"] = peek
            return real_write(path, content, vault_root=vault_root, **kwargs)

        with mock.patch.object(pub, "atomic_write_vault_text", watched):
            pub.publish(self.vault, now=NOW)
        self.assertEqual(seen["mid"], first, "a reader saw something mid-publication")
        self.assertEqual(self.published()["projection_generation"], 2)


# --------------------------------------------------------------------------
# "Generation"
# --------------------------------------------------------------------------


class GenerationTests(VaultTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.file_claims(waiting_on_an_anchor())

    def test_generation_starts_at_one_and_never_repeats(self) -> None:
        self.assertEqual(pub.published_generation(self.vault), 0)
        self.assertEqual(pub.next_generation(self.vault), 1)
        for expected in (1, 2, 3):
            if expected > 1:
                self.file_claims([claim(
                    claim_type="date", subject_mention=f"a new thing {expected}",
                    event_kind="transition", temporal_value=f"199{expected}",
                    source=f"src-new-{expected}", seed=f"new-{expected}")])
            self.assertEqual(pub.publish(self.vault, now=NOW)["generation"], expected)
            self.assertEqual(pub.published_generation(self.vault), expected)

    def test_an_unchanged_republish_mints_no_generation_at_all(self) -> None:
        """Eras E1, design §3.4. Age frames make the projection a function of
        the clock too, so "publish again" would otherwise advance the counter
        every day and no reader could tell a frame boundary from a heartbeat."""
        self.assertFalse(pub.publish(self.vault, now=NOW)["unchanged"])
        second = pub.publish(self.vault, now="2026-08-27T09:00:00Z")
        self.assertTrue(second["unchanged"])
        self.assertEqual(second["generation"], 1)
        self.assertEqual(pub.published_generation(self.vault), 1)

    def test_the_counter_reads_the_max_across_both_files(self) -> None:
        """A generation number already on disk is never re-used, whichever of
        the two files happens to be carrying it."""
        pub.publish(self.vault, now=NOW)
        payload = self.queue_slice()
        payload["projection_generation"] = 9
        pub.work_items_path(self.vault).write_text(
            json.dumps(payload, indent=2) + "\n", encoding="utf-8"
        )
        self.assertEqual(pub.published_generation(self.vault), 9)
        # A hand-edited generation is a TEAR — the two files disagree — and a
        # torn pair always publishes, above both numbers.
        self.assertEqual(pub.publish(self.vault, now=NOW)["generation"], 10)

    def test_a_generation_that_is_not_a_number_is_refused_by_name(self) -> None:
        pub.publish(self.vault, now=NOW)
        payload = self.published()
        payload["projection_generation"] = "second"
        pub.projection_path(self.vault).write_text(
            json.dumps(payload, indent=2) + "\n", encoding="utf-8"
        )
        with self.assertRaises(pub.TemporalPublicationError) as caught:
            pub.published_generation(self.vault)
        self.assertEqual(caught.exception.code, "publication_generation_unusable")


# --------------------------------------------------------------------------
# "A clean full rebuild remains the correctness oracle"
# --------------------------------------------------------------------------


class RebuildOracleTests(VaultTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.file_claims(waiting_on_an_anchor() + disagreeing())

    def test_deleting_both_files_and_publishing_again_reproduces_the_projection(self) -> None:
        """§7's oracle, at the FILE level. `rebuild_signature` names the
        exclusions — the generation among them, deliberately: a repair that
        started counting again must still be recognized as the same truth."""
        pub.publish(self.vault, now=NOW)
        before = pub.rebuild_signature(self.published())
        queue_before = pub.rebuild_signature(self.queue_slice())

        pub.projection_path(self.vault).unlink()
        pub.work_items_path(self.vault).unlink()
        ts.active_index_path(self.vault).unlink()
        self.assertEqual(pub.published_generation(self.vault), 0)

        summary = pub.publish(self.vault, now="2027-01-01T00:00:00Z")
        self.assertEqual(summary["generation"], 1)
        self.assertEqual(pub.rebuild_signature(self.published()), before)
        self.assertEqual(pub.rebuild_signature(self.queue_slice()), queue_before)

    def test_republishing_an_unchanged_substrate_changes_nothing_at_all(self) -> None:
        """Eras E1 (design §3.4) INVERTED this: an unchanged republish used to
        rewrite both files with new metadata, and now it writes nothing. The
        signature is what the substrate implies, and it did not move."""
        pub.publish(self.vault, now=NOW)
        first = pub.rebuild_signature(self.published())
        before = pub.projection_path(self.vault).read_bytes()
        summary = pub.publish(self.vault, now=NOW)
        second = self.published()
        self.assertTrue(summary["unchanged"])
        self.assertEqual(pub.rebuild_signature(second), first)
        self.assertEqual(second["projection_generation"], 1)
        self.assertEqual(pub.projection_path(self.vault).read_bytes(), before)

    def test_a_new_claim_changes_the_projection_and_the_digest(self) -> None:
        pub.publish(self.vault, now=NOW)
        before = self.published()
        self.file_claims(
            [claim(claim_type="date", subject_mention="the big move",
                   event_kind="transition", temporal_value="1994",
                   source="src-anchor", seed="anchor")]
        )
        pub.publish(self.vault, now=NOW)
        after = self.published()
        self.assertNotEqual(after["input_digest"], before["input_digest"])
        self.assertNotEqual(pub.rebuild_signature(after), pub.rebuild_signature(before))

    def test_verify_confirms_the_published_generation_reproduces(self) -> None:
        pub.publish(self.vault, now=NOW)
        report = pub.verify(self.vault, now=NOW)
        self.assertTrue(report["published"])
        self.assertTrue(report["identical"], report.get("differences"))

    def test_verify_catches_a_projection_nobody_derived(self) -> None:
        pub.publish(self.vault, now=NOW)
        payload = self.published()
        payload["nodes"] = payload["nodes"][:1]
        pub.projection_path(self.vault).write_text(
            json.dumps(payload, indent=2) + "\n", encoding="utf-8"
        )
        report = pub.verify(self.vault, now=NOW)
        self.assertFalse(report["identical"])
        self.assertIn("nodes", report["differences"])

    def test_the_rebuild_command_is_the_repair_path(self) -> None:
        pub.publish(self.vault, now=NOW)
        before = pub.rebuild_signature(self.published())
        self.assertEqual(pub.main(["--vault-root", str(self.vault), "--rebuild"]), 0)
        self.assertEqual(self.published()["projection_generation"], 1)
        self.assertEqual(pub.rebuild_signature(self.published()), before)
        self.assertEqual(pub.main(["--vault-root", str(self.vault), "--check"]), 0)


# --------------------------------------------------------------------------
# §7.1 — the timings a wave-H decision would be made from
# --------------------------------------------------------------------------


class InstrumentationTests(VaultTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.file_claims(waiting_on_an_anchor())

    def test_every_phase_is_timed_separately(self) -> None:
        """§7.1 asks for the phases SEPARATELY: a single total tells nobody
        which phase to attack, and wave H is a measured decision."""
        summary = pub.publish(self.vault, now=NOW)
        for phase in tt.TIMING_PHASES:
            self.assertIn(phase, summary["timings"])
        for phase in pub.PUBLICATION_PHASES:
            self.assertIn(phase, summary["timings"])
        self.assertIn("publication_total", summary["timings"])

    def test_the_timings_are_published_and_excluded_from_the_signature(self) -> None:
        pub.publish(self.vault, now=NOW)
        self.assertIn("timings", self.published())
        self.assertNotIn("timings", pub.rebuild_signature(self.published()))

    def test_the_report_line_carries_the_counts_and_the_phases(self) -> None:
        line = pub.publication_report_line(pub.publish(self.vault, now=NOW))
        self.assertIn("generation 1", line)
        self.assertIn("work item", line)
        self.assertIn("total", line)


# --------------------------------------------------------------------------
# The consumers — real derivation, real publish, real read
# --------------------------------------------------------------------------


class QuestionQueueSeamTests(VaultTestCase):
    """Wave F reads what wave D now writes (`question_planner`)."""

    def setUp(self) -> None:
        super().setUp()
        self.file_claims(waiting_on_an_anchor() + disagreeing())
        self.summary = pub.publish(self.vault, now=NOW)

    def test_the_planner_consumes_the_published_file_from_the_vault(self) -> None:
        with mock.patch.object(qp, "REPO_DIR", self.vault):
            items = qp._published_work_items()
        self.assertTrue(items, "the planner read an empty door")
        self.assertEqual(
            {row["work_item_id"] for row in items},
            {row["work_item_id"] for row in self.queue_slice()["work_items"]},
        )

    def test_the_raw_reach_travels_across_the_seam(self) -> None:
        with mock.patch.object(qp, "REPO_DIR", self.vault):
            items = qp._published_work_items()
        anchor = next(row for row in items if row["kind"] == "missing_anchor")
        self.assertEqual(anchor["downstream_reach"],
                         self.queue_slice()["reach"][anchor["work_item_id"]])

    def test_a_high_reach_gap_reaches_the_daily_queue_end_to_end(self) -> None:
        """The whole point of the wave: substrate → publish → queue candidate."""
        with mock.patch.object(qp, "REPO_DIR", self.vault):
            items = qp._published_work_items()
        ranked = qp.queue_candidates(items, question_bank_text=EMPTY_BANK)
        self.assertTrue(ranked)
        self.assertEqual(ranked[0]["kind"], "missing_anchor")


class MirrorSeamTests(VaultTestCase):
    """Wave E reads the same file (`mirror_work`), and gets rows from it."""

    def setUp(self) -> None:
        super().setUp()
        self.file_claims(waiting_on_an_anchor() + disagreeing())
        pub.publish(self.vault, now=NOW)

    def test_mirrors_reader_consumes_the_published_slice(self) -> None:
        items = mirror_work.load_work_items(self.vault)
        self.assertEqual(
            [row["work_item_id"] for row in items],
            [row["work_item_id"] for row in self.queue_slice()["work_items"]],
        )

    def test_the_contradiction_becomes_a_mirror_row(self) -> None:
        rows = mirror_work.load_mirror_rows(self.vault)
        self.assertTrue(rows, "the published contradiction produced no Mirror row")
        self.assertIn("contradiction", {row.kind for row in rows})

    def test_before_the_first_publication_mirror_reads_an_honest_empty(self) -> None:
        empty = Path(tempfile.mkdtemp(prefix="lifehug-projection-unpublished-"))
        self.addCleanup(shutil.rmtree, empty, ignore_errors=True)
        self.assertEqual(mirror_work.load_work_items(empty), [])


class ConversationExtractionEndToEndTests(VaultTestCase):
    """C3's shape all the way through: a message is extracted into claims, the
    compile seat folds the receipt it wrote, and BOTH consumers see the
    result. Nothing here knows about landmarks — this is the path a spoken
    sentence takes."""

    def setUp(self) -> None:
        super().setUp()
        self.source_ref, _ = ts.file_message_extraction(
            self.vault,
            message_text="We got married in June '98. Well — '99, maybe.",
            extractor_version="listener:1",
            claims_for=lambda ref: [
                {
                    "claim_type": "date",
                    "subject_mention": "Katie",
                    "event_kind": "married",
                    "temporal_value": "1998-06-20",
                    "source_kind": "conversation",
                    "evidence": [{"quote": "We got married in June '98"}],
                    "basis": "explicit",
                    "confidence": 0.9,
                    "status": "active",
                },
                {
                    "claim_type": "relative_order",
                    "subject_mention": "the honeymoon",
                    "event_kind": "transition",
                    "temporal_value": {"relation": "after", "anchors": ["the big move"]},
                    "source_kind": "conversation",
                    "evidence": [{"quote": "right after the big move"}],
                    "basis": "explicit",
                    "confidence": 0.8,
                    "status": "active",
                },
            ],
            now=NOW,
        )
        self.second, _ = ts.file_message_extraction(
            self.vault,
            message_text="No, it was 1999 — I remember the eclipse that summer.",
            extractor_version="listener:1",
            claims_for=lambda ref: [
                {
                    "claim_type": "date",
                    "subject_mention": "Katie",
                    "event_kind": "married",
                    "temporal_value": "1999-06-20",
                    "source_kind": "conversation",
                    "evidence": [{"quote": "it was 1999"}],
                    "basis": "explicit",
                    "confidence": 0.9,
                    "status": "active",
                }
            ],
            now=NOW,
        )
        self.summary = pub.publish(self.vault, now=NOW)

    def test_the_extraction_reached_the_published_projection(self) -> None:
        self.assertGreaterEqual(self.summary["claims"], 3)
        self.assertTrue(self.published()["nodes"])
        kinds = {row["event_kind"] for row in self.published()["nodes"]}
        self.assertIn("married", kinds)

    def test_the_queue_sees_the_gap_the_conversation_left(self) -> None:
        with mock.patch.object(qp, "REPO_DIR", self.vault):
            items = qp._published_work_items()
        self.assertIn("missing_anchor", {row["kind"] for row in items})

    def test_mirror_sees_the_disagreement_the_conversation_created(self) -> None:
        rows = mirror_work.load_mirror_rows(self.vault)
        self.assertIn("contradiction", {row.kind for row in rows})

    def test_the_source_the_claims_cite_is_a_durable_vault_file(self) -> None:
        """Amendment 2: `source_ref` is vault-universal, so the projection's
        provenance resolves to a file that is still there."""
        relative = ts.conversation_source_relative_path(
            ts.promotion_digest("We got married in June '98. Well — '99, maybe.", {})
        )
        self.assertTrue((self.vault / relative).is_file())


# --------------------------------------------------------------------------
# Wave E item E2 — the drag has a home, and the publisher reads it
# --------------------------------------------------------------------------


def schooling() -> list[dict]:
    """High school with a date, college with none: the §10 drag scenario."""
    return [
        claim(claim_type="date", subject_mention="High School", event_kind="school",
              temporal_value="1994", source="src-hs", seed="hs"),
        claim(claim_type="date", subject_mention="College", event_kind="school",
              temporal_value="1990", source="src-col", seed="col"),
    ]


class DragCorrectionSeamTests(VaultTestCase):
    """v232: a move is a durable correction source, and the projection reads it.

    §8.4's transaction ends "rebuild and atomically publish". The publisher's
    ``constraints`` seat is no longer something every caller must remember to
    fill — it defaults to what this vault's filed moves say — so the republish
    is the seat that already exists.
    """

    def setUp(self) -> None:
        super().setUp()
        self.file_claims(schooling())
        pub.publish(self.vault, now=NOW)
        self.nodes = {
            row["provenance_summary"] and row["node_id"]: row
            for row in self.published()["nodes"]
        }
        by_subject = {row["subject_refs"][0]: row["node_id"]
                      for row in self.published()["nodes"] if row["subject_refs"]}
        self.college = by_subject["College"]
        self.high_school = by_subject["High School"]

    def move(self, **kwargs) -> dict:
        kwargs.setdefault("relation", "after")
        kwargs.setdefault("subject_node_id", self.college)
        kwargs.setdefault("anchor_node_ids", [self.high_school])
        return ts.file_ordering_constraint(self.vault, **kwargs)

    def test_the_publisher_reads_the_vaults_filed_moves_by_default(self) -> None:
        """§8.4 step 7, with nobody remembering to load anything."""
        constraint = self.move()
        pub.publish(self.vault, now=NOW)
        node = next(row for row in self.published()["nodes"]
                    if row["node_id"] == self.college)
        self.assertIn(constraint["constraint_id"], node["input_constraint_refs"])

    def test_an_explicit_empty_sequence_still_means_none(self) -> None:
        """A test deriving over a hand-built substrate is not silently given
        the vault's — ``()`` is "none" and ``None`` is "read them"."""
        self.move()
        pub.publish(self.vault, constraints=(), now=NOW)
        node = next(row for row in self.published()["nodes"]
                    if row["node_id"] == self.college)
        self.assertEqual(node["input_constraint_refs"], [])

    def test_moving_against_an_explicit_date_preserves_both_and_opens_mirror(self) -> None:
        """§10: *moving against an explicit incompatible date preserves both and
        creates/updates a Mirror contradiction*."""
        self.move()
        pub.publish(self.vault, now=NOW)
        node = next(row for row in self.published()["nodes"]
                    if row["node_id"] == self.college)
        # The date the person actually stated is still the node's own value.
        self.assertEqual(node["best_temporal_value"]["best"], "1990")
        self.assertEqual(node["conflict_state"], "contradicted")
        rows = mirror_work.load_mirror_rows(self.vault)
        self.assertIn("contradiction", {row.kind for row in rows})

    def test_undo_republishes_without_the_move(self) -> None:
        constraint = self.move()
        pub.publish(self.vault, now=NOW)
        ts.retract_ordering_constraint(
            self.vault, constraint["constraint_id"], reason="I mixed those up."
        )
        pub.publish(self.vault, now=NOW)
        node = next(row for row in self.published()["nodes"]
                    if row["node_id"] == self.college)
        self.assertEqual(node["input_constraint_refs"], [])
        self.assertNotEqual(node["conflict_state"], "contradicted")

    def test_the_rebuild_oracle_reads_the_same_home(self) -> None:
        """§10's *"deleting active index/projection and rebuilding produces the
        same semantic result"* has to include the moves, or a corrected vault
        would report itself unreproducible."""
        self.move()
        pub.publish(self.vault, now=NOW)
        self.assertTrue(pub.verify(self.vault, now=NOW)["identical"])


class RecorderSeatTests(VaultTestCase):
    """C3's filing seat publishes too: a claim heard in conversation becomes a
    visible projection change in the SAME act.

    `landmark_recorder.file_claims` is the only vault-touching function in the
    recorder, and before v231 it wrote a receipt that nothing derived from — so
    a fact the person said out loud waited for an unrelated landmark write
    before the queue or Mirror could ever see it. Same publisher as the
    landmark seat; there is not a second one.
    """

    MESSAGE = ("We moved to Dayton in 1974, and my sister Ruth was born "
               "in 1948.")

    def drafts(self, claims):
        return [dict(row) for row in claims]

    def file_it(self, claims, *, message: str | None = None):
        return lr.file_claims(
            self.vault,
            self.drafts(claims),
            message_text=message or self.MESSAGE,
            extractor_version=gl.listener_extractor_version(),
            extractor=gl.listener_extractor(),
            session_ref="session:abc",
            turn_ref="turn:7",
            recorder=gl.LISTENER_EXTRACTOR,
        )

    MOVE = {"claim_type": "date", "subject_mention": "Dayton",
            "event_kind": "move", "temporal_value": "1974",
            "evidence": [{"quote": "We moved to Dayton in 1974"}],
            "basis": "explicit", "confidence": 0.9, "status": "active"}
    RUTH = {"claim_type": "date", "subject_mention": "my sister Ruth",
            "event_kind": "birth", "temporal_value": "1948",
            "evidence": [{"quote": "my sister Ruth was born in 1948"}],
            "basis": "explicit", "confidence": 0.9, "status": "active"}

    def test_filing_a_conversation_claim_publishes_a_generation(self) -> None:
        self.assertEqual(pub.published_generation(self.vault), 0)
        filed = self.file_it([self.MOVE, self.RUTH])
        self.assertIsNotNone(filed, "the fixture must actually file something")
        self.assertEqual(pub.published_generation(self.vault), 1)
        labels = {row["event_kind"] for row in self.published()["nodes"]}
        self.assertEqual(labels, {"move", "birth"})

    def test_a_second_message_advances_the_generation_and_the_projection(self) -> None:
        self.file_it([self.MOVE])
        first = pub.published_generation(self.vault)
        self.file_it(
            [{"claim_type": "relative_order", "subject_mention": "the new school",
              "event_kind": "transition",
              "temporal_value": {"relation": "after", "anchors": ["the move to Dayton"]},
              "evidence": [{"quote": "the new school started after the move"}],
              "basis": "explicit", "confidence": 0.8, "status": "active"}],
            message="The new school started right after the move to Dayton.",
        )
        self.assertGreater(pub.published_generation(self.vault), first)
        labels = " ".join(str(row.get("label")) for row in self.published()["nodes"])
        self.assertIn("school", labels)

    def test_the_queue_and_mirror_see_the_new_item_without_a_landmark_write(self) -> None:
        """The deferral this closes, stated as its own assertion: nothing here
        touches `save_landmark`, and both consumers still see the work."""
        self.file_it([
            self.MOVE,
            {"claim_type": "date", "subject_mention": "Dayton",
             "event_kind": "move", "temporal_value": "1976",
             "evidence": [{"quote": "no, it was 1976"}],
             "basis": "explicit", "confidence": 0.9, "status": "active"},
        ])
        self.file_it(
            [{"claim_type": "relative_order", "subject_mention": f"thing {index}",
              "event_kind": "transition",
              "temporal_value": {"relation": "after", "anchors": ["the big move"]},
              "evidence": [{"quote": "after the big move"}],
              "basis": "explicit", "confidence": 0.8, "status": "active"}
             for index in range(5)],
            message="Thing zero through four all happened after the big move.",
        )
        with mock.patch.object(qp, "REPO_DIR", self.vault):
            items = qp._published_work_items()
            ranked = qp.queue_candidates(items, question_bank_text=EMPTY_BANK)
        self.assertIn("missing_anchor", {row["kind"] for row in items})
        self.assertTrue(ranked)
        rows = mirror_work.load_mirror_rows(self.vault)
        self.assertIn("contradiction", {row.kind for row in rows})

    def test_a_message_with_no_claims_files_nothing_and_publishes_nothing(self) -> None:
        """The amendment's own rule, carried through: nothing filed means
        nothing derived, so no generation is minted either."""
        self.assertIsNone(lr.file_claims(
            self.vault, [], message_text="Nice weather.",
            extractor_version=gl.listener_extractor_version()))
        self.assertEqual(pub.published_generation(self.vault), 0)
        self.assertIsNone(pub.read_projection(self.vault))

    def test_refiling_the_same_message_is_idempotent_in_evidence(self) -> None:
        """The receipt is immutable and idempotent, and since eras E1 so is the
        publication: refiling the same message says nothing new, so it mints no
        generation either. The claims must not double."""
        self.file_it([self.MOVE])
        claims = self.published()["counts"]["claims"]
        self.file_it([self.MOVE])
        self.assertEqual(self.published()["counts"]["claims"], claims)
        self.assertEqual(pub.published_generation(self.vault), 1)
        self.assertEqual(
            len(list((self.vault / ts.CONVERSATION_SOURCES_DIR).rglob("*.md"))), 1)

    def test_the_recorder_and_the_ladder_share_one_publisher(self) -> None:
        """One definition, two roads: the seam is asserted, not assumed."""
        source = (ROOT / "system" / "landmark_recorder.py").read_text(encoding="utf-8")
        self.assertIn("from temporal_publication import publish", source)
        self.assertNotIn("derive_calculated_timeline", source,
                         "the recorder grew its own derivation")


# --------------------------------------------------------------------------
# The seat: one compile, one drawing, one truth
# --------------------------------------------------------------------------


LANDMARKS = {
    "birth": [{"domain": "birth", "date": date("1962-03-04", granularity="day"),
               "year": "1962", "month": "03", "day": "04"}],
    "residences": [{"domain": "residences", "label": "Pike Hollow",
                    "city": "Pike Hollow",
                    "span": {"start": date("1962"), "end": date("1971")}}],
}


class CompileSeatTests(unittest.TestCase):
    """The publication rides the flip's redraw and has no trigger of its own."""

    def setUp(self) -> None:
        self.vault = Path(tempfile.mkdtemp(prefix="lifehug-projection-seat-"))
        self.addCleanup(shutil.rmtree, self.vault, ignore_errors=True)
        self.store = self.vault / "state" / "landmarks.json"
        self.store.parent.mkdir(parents=True, exist_ok=True)
        patch = mock.patch.object(timeline, "LANDMARKS_STORE", self.store)
        patch.start()
        self.addCleanup(patch.stop)
        self.store.write_text(
            json.dumps({"version": 1, "domains": copy.deepcopy(LANDMARKS)}, indent=2) + "\n",
            encoding="utf-8",
        )

    def test_the_flip_publishes_the_projection_in_the_same_call(self) -> None:
        timeline.flip_landmarks_if_needed()
        payload = pub.read_projection(self.vault)
        self.assertIsNotNone(payload)
        self.assertEqual(payload["projection_generation"], 1)
        self.assertTrue(payload["nodes"], "the flipped landmarks produced no nodes")

    def test_a_landmark_write_republishes_the_next_generation(self) -> None:
        timeline.flip_landmarks_if_needed()
        first = pub.published_generation(self.vault)
        timeline.save_landmark(
            "work",
            {"domain": "work", "label": "Halloway Press", "what": "compositor",
             "span": {"start": date("2001")}},
        )
        self.assertGreater(pub.published_generation(self.vault), first)
        labels = {row["label"] for row in pub.read_projection(self.vault)["nodes"]}
        self.assertTrue(any("Halloway" in label for label in labels),
                        f"the new landmark never reached the projection: {labels}")

    def test_the_projection_lands_in_the_vault_the_store_names(self) -> None:
        """`_projection_vault_root`'s hazard, applied to the publisher: rebind
        the store and the projection must follow it, never the process vault."""
        timeline.flip_landmarks_if_needed()
        self.assertTrue(pub.projection_path(self.vault).is_file())
        self.assertFalse(
            (ROOT / tp.PROJECTION_FILE).exists()
            and (ROOT / tp.PROJECTION_FILE).stat().st_mtime > self.store.stat().st_mtime,
            "the publisher wrote into the checkout's own vault",
        )

    def test_the_read_model_exposes_the_published_generation_additively(self) -> None:
        timeline.flip_landmarks_if_needed()
        view = timeline.temporal_publication.calculated_view(self.vault)
        self.assertTrue(view["published"])
        self.assertEqual(view["projection_generation"], 1)
        self.assertEqual(view["counts"]["nodes"], len(view["nodes"]))

    def test_an_unpublished_vault_says_so_rather_than_faking_an_empty_one(self) -> None:
        view = pub.calculated_view(self.vault)
        self.assertFalse(view["published"])
        self.assertEqual(view["counts"]["nodes"], 0)
        self.assertEqual(view["nodes"], ())


class ReadModelTests(VaultTestCase):
    def test_the_view_reads_the_publication_and_never_derives_one(self) -> None:
        self.file_claims(waiting_on_an_anchor())
        pub.publish(self.vault, now=NOW)
        with mock.patch.object(tt, "derive_calculated_timeline",
                               side_effect=AssertionError("the page derived")):
            view = pub.calculated_view(self.vault)
        self.assertTrue(view["published"])
        self.assertEqual(len(view["nodes"]), self.published()["counts"]["nodes"])

    def test_timeline_data_carries_the_calculated_section(self) -> None:
        """The additive wiring, asserted on the real payload: the legacy
        derivation's keys are untouched and `calculated` rides beside them."""
        self.file_claims(waiting_on_an_anchor())
        store = self.vault / "state" / "landmarks.json"
        store.write_text(json.dumps({"version": 1, "domains": {}}) + "\n", encoding="utf-8")
        pub.publish(self.vault, now=NOW)
        with mock.patch.object(timeline, "LANDMARKS_STORE", store):
            data = timeline.timeline_data()
        self.assertIn("calculated", data)
        self.assertTrue(data["calculated"]["published"])
        self.assertEqual(data["counts"]["projection_generation"], 1)
        self.assertEqual(data["counts"]["calculated_work_items"],
                         data["calculated"]["counts"]["work_items"])
        for key in ("periods", "bands", "unknowns", "keystones"):
            self.assertIn(key, data, "the legacy derivation lost a key")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
