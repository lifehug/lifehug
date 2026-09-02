"""v224 — Mirror's actionable rows (audited timeline plan §2.5, §8.2, §10).

The §10 acceptance scenarios this file is responsible for, in the plan's own
words:

* *Mirror renders one stable contradiction row with Play now and
  source-grounded alternatives.*
* *A Mirror correction writes durable evidence, re-derives the timeline, and
  closes the item only when the claims no longer conflict.*
* *Opening Play and leaving, skipping, or answering "I don't know" invents no
  correction.*
* *An unresolved contradiction does not block unrelated nodes or queue work.*
* *An ambiguous name is retained as an unresolved claim and becomes a Mirror
  identity item rather than being dropped* — rendered here with its candidate
  set.
* *Mirror-to-daily-queue admission is absent in this release* — no row ever
  lists ``daily_question`` and nothing here pushes a count anywhere.

Work items are constructed through their own validators rather than through
the wave-D minting path, so this suite tests the read model and the write
seam and not the fold that will feed them.

Synthetic data only; NEVER references ~/Workspace/dave.
"""

from __future__ import annotations

import ast
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "system"))
sys.path.insert(0, str(ROOT / "tests"))

import identity_resolution as ident  # noqa: E402
import mirror_work as mw  # noqa: E402
import temporal_claims as tc  # noqa: E402
import temporal_projection as tp  # noqa: E402
import temporal_store as ts  # noqa: E402
from tempdirs import root_parent_tmp  # noqa: E402

LISTENER = tc.extractor_version_string(
    "listener", schema_version=1, prompt_version="c0ffee", model="test-model"
)
OWNER = tc.extractor_version_string("owner", rule_version="1")
NOW = "2026-08-26T12:00:00Z"


def date_value(best: str, *, granularity: str = "day", basis: str = "stated") -> dict:
    return {
        "best": best,
        "earliest": best,
        "latest": best,
        "granularity": granularity,
        "confidence": "certain",
        "basis": basis,
    }


def claim(
    subject: str,
    event_kind: str,
    best: str,
    *,
    quote: str,
    granularity: str = "day",
    created_at: str = "2026-08-26T09:00:00Z",
) -> dict:
    return {
        "claim_type": "date",
        "source_kind": "conversation",
        "subject_mention": subject,
        "event_kind": event_kind,
        "temporal_value": date_value(best, granularity=granularity),
        "evidence": [{"quote": quote, "turn_ref": "turn-1"}],
        "basis": "explicit",
        "confidence": 0.9,
        "created_at": created_at,
    }


class MirrorWorkTestCase(unittest.TestCase):
    """A throwaway vault per test, outside the repo and never ~/Workspace/dave."""

    def setUp(self) -> None:
        # ROOT.parent rather than $TMPDIR: on macOS /var is a symlink and the
        # vault's no-follow path guard refuses to write through it.
        self.vault = root_parent_tmp(self, ROOT, prefix="lifehug-mirror-work-")

    # -- vault helpers ----------------------------------------------------

    def file_claim(
        self,
        message: str,
        payload: dict,
        *,
        extractor_version: str = LISTENER,
        session_ref: str = "s1",
        turn_ref: str = "t1",
    ) -> str:
        """Promote a message, file its receipt, return the claim id."""
        source_ref, _path = ts.file_message_extraction(
            self.vault,
            message_text=message,
            extractor_version=extractor_version,
            claims_for=lambda ref: [payload],
            metadata={"session_ref": session_ref, "turn_ref": turn_ref},
            now=NOW,
        )
        normalized = tc.validate_temporal_claim(
            {
                **payload,
                "source_ref": source_ref.to_dict(),
                "extractor_version": extractor_version,
            },
            now=NOW,
        )
        return normalized["claim_id"]

    def index(self) -> dict:
        return ts.rebuild_active_index(self.vault)

    def files(self) -> list[str]:
        return sorted(
            path.relative_to(self.vault).as_posix()
            for path in self.vault.rglob("*")
            if path.is_file()
        )

    def publish_items(self, *items: dict) -> None:
        path = ts.store_path(self.vault, tp.WORK_ITEMS_FILE)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps({"version": 1, "work_items": list(items)}, indent=2) + "\n",
            encoding="utf-8",
        )

    # -- fixture builders -------------------------------------------------

    def contradiction_fixture(self, *, third: bool = False) -> dict:
        """Two (or three) incompatible explicit marriage dates, and the row."""
        first = self.file_claim(
            "We married on June 14th, 1978.",
            claim("Katie", "married", "1978-06-14", quote="We married on June 14th, 1978."),
            turn_ref="t1",
        )
        second = self.file_claim(
            "We married in 1981.",
            claim("Katie", "married", "1981", quote="We married in 1981.",
                  granularity="year"),
            turn_ref="t2",
        )
        refs = [first, second]
        if third:
            refs.append(
                self.file_claim(
                    "We married in 1983.",
                    claim("Katie", "married", "1983", quote="We married in 1983.",
                          granularity="year"),
                    turn_ref="t3",
                )
            )
        item = tp.validate_temporal_work_item(
            {
                "kind": "contradiction",
                "state": "open",
                "subject_ref": "person/katie",
                "event_ref": "event:married-katie",
                "claim_refs": refs,
                "evidence_refs": [f"claim:{refs[0]}"],
                "prompt_intent": "Which year did you and Katie marry?",
                "allowed_surfaces": ["mirror", "timeline"],
            },
            now=NOW,
        )
        self.publish_items(item)
        return {"item": item, "claims": refs}

    def identity_fixture(self) -> dict:
        """An ambiguous "AJ" kept as an uncertain claim, and its Mirror item."""
        roster = {
            "type": "person",
            "entities": [
                {"name": "AJ Lang", "slug": "aj-lang", "aliases": ["AJ"]},
                {"name": "AJ Vance", "slug": "aj-vance", "aliases": ["AJ"]},
            ],
        }
        record = ident.resolve_mention(
            "AJ", roster=roster, evidence_ref="conversation:msg-aj", now=NOW
        )
        self.assertEqual(record.resolution, "uncertain")
        self.assertEqual(len(record.candidates), 2)

        base = claim("AJ", "met", "1994", quote="I met AJ in 1994.", granularity="year")
        annotated = dict(base)
        annotated["subject_resolution"] = ident.resolution_annotation(record)
        claim_id = self.file_claim("I met AJ in 1994.", annotated, turn_ref="t9")

        item = ident.identity_work_item(record, claim_refs=[claim_id], now=NOW)
        self.assertIsNotNone(item)
        self.publish_items(item)
        return {"item": item, "claim": claim_id, "record": record}


# --------------------------------------------------------------------------
# A move is a side (v232, plan §2.6)
# --------------------------------------------------------------------------


class MoveContradictionTests(MirrorWorkTestCase):
    """§2.6: *if the new constraint conflicts with an explicit date, keep both
    claims and create/update a Mirror contradiction.*

    Before v232 this row was silently dropped: the contradiction cites ONE
    claim and ONE ordering constraint, and a state derived from active claims
    alone read "fewer than two, so it is settled".
    """

    def move_fixture(self) -> dict:
        claim_id = self.file_claim(
            "I started college in 1990.",
            claim("College", "school", "1990", quote="I started college in 1990.",
                  granularity="year"),
            turn_ref="t1",
        )
        constraint_id = "constraint:" + ("a" * 24)
        item = tp.validate_temporal_work_item(
            {
                "kind": "contradiction",
                "state": "open",
                "subject_ref": "College",
                "event_ref": "event:college",
                "node_ref": "node:college",
                "claim_refs": [claim_id, constraint_id],
                "evidence_refs": [f"claim:{claim_id}"],
                "prompt_intent": "The order given for College does not fit its date.",
                "allowed_surfaces": ["mirror", "timeline"],
            },
            now=NOW,
        )
        self.publish_items(item)
        return {"item": item, "claim": claim_id, "constraint": constraint_id}

    def test_a_move_against_a_date_renders_one_open_row(self) -> None:
        fixture = self.move_fixture()
        rows = mw.load_mirror_rows(self.vault)
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row.kind, "contradiction")
        self.assertEqual(row.state, "open")
        self.assertIn(fixture["constraint"], row.claim_refs)
        self.assertIn("moved", row.description)
        self.assertIn("1990", row.description)
        self.assertIn("both stay on the record", row.description)

    def test_the_constraint_ref_is_named_as_a_move_and_not_as_a_claim(self) -> None:
        fixture = self.move_fixture()
        item = tp.work_item_from_dict(fixture["item"])
        self.assertEqual(mw.moves_cited(item), (fixture["constraint"],))
        row = mw.load_mirror_rows(self.vault)[0]
        # A constraint is not a claim, so it never appears as an ACTIVE claim
        # ref and never gets a citation it cannot support.
        self.assertEqual(row.active_claim_refs, (fixture["claim"],))
        self.assertNotIn(fixture["constraint"], row.active_claim_refs)

    def test_the_row_can_be_played(self) -> None:
        self.move_fixture()
        row = mw.load_mirror_rows(self.vault)[0]
        self.assertIsNotNone(row.play)

    def test_retiring_the_dated_claim_closes_the_row(self) -> None:
        """One side left is not a disagreement, whichever side it was."""
        fixture = self.move_fixture()
        ts.retract_claims(self.vault, [fixture["claim"]], reason="Wrong year.")
        self.assertEqual(mw.load_mirror_rows(self.vault), [])

    def test_a_contradiction_citing_only_a_move_cannot_be_built(self) -> None:
        """A constraint with nothing to disagree with is not a disagreement, and
        the CONTRACT says so before Mirror ever sees it."""
        with self.assertRaises(tp.TemporalWorkItemError) as caught:
            tp.validate_temporal_work_item(
                {
                    "kind": "contradiction",
                    "state": "open",
                    "subject_ref": "College",
                    "claim_refs": ["constraint:" + ("b" * 24)],
                    "prompt_intent": "?",
                    "allowed_surfaces": ["mirror"],
                },
                now=NOW,
            )
        self.assertEqual(caught.exception.code, "contradiction_needs_two_claims")

    def test_two_dates_with_no_move_read_exactly_as_before(self) -> None:
        """The claim-vs-claim row is untouched by the new side-counting."""
        self.contradiction_fixture()
        row = mw.load_mirror_rows(self.vault)[0]
        self.assertTrue(row.headline.startswith("Two dates for"))
        self.assertNotIn("moved", row.description)


# --------------------------------------------------------------------------
# The stable contradiction row
# --------------------------------------------------------------------------


class ContradictionRowTests(MirrorWorkTestCase):
    def test_one_stable_row_with_alternatives_citations_and_play(self) -> None:
        fixture = self.contradiction_fixture()
        rows = mw.load_mirror_rows(self.vault)

        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row.work_item_id, fixture["item"]["work_item_id"])
        self.assertEqual(row.kind, "contradiction")
        self.assertEqual(row.state, "open")

        # Both readings survive: the best-supported one and the rival.
        self.assertIn("1978", row.best_supported["display"])
        self.assertEqual(len(row.alternatives), 1)
        self.assertIn("1981", row.alternatives[0]["display"])
        self.assertGreater(row.severity, 0.0)

        # Evidence-grounded: every claim cites its promoted source and quote.
        self.assertEqual(len(row.citations), 2)
        for citation in row.citations:
            self.assertTrue(citation["source_id"].startswith("conversation:msg-"))
            self.assertTrue(citation["quote"])
        self.assertIn("1978", row.description)
        self.assertIn("1981", row.description)
        self.assertIn("source", row.description)

        # Play now, bound to this exact item.
        self.assertEqual(row.play["kind"], mw.PLAY_TARGET_KIND)
        self.assertEqual(row.play["ref"], row.work_item_id)
        self.assertEqual(sorted(row.play["resolvable_claim_ids"]), sorted(fixture["claims"]))
        self.assertEqual(len(row.play["evidence"]), 2)

    def test_the_row_survives_a_rebuild_of_the_index_byte_for_byte(self) -> None:
        """Row identity is the work item's identity — not a position or a run."""
        self.contradiction_fixture()
        self.index()
        before = mw.load_mirror_rows(self.vault)[0].to_dict()

        ts.active_index_path(self.vault).unlink()
        ts.rebuild_active_index(self.vault)

        after = mw.load_mirror_rows(self.vault)[0].to_dict()
        self.assertEqual(before, after)

    def test_the_folded_index_is_used_when_none_has_been_published(self) -> None:
        self.contradiction_fixture()
        self.assertFalse(ts.active_index_path(self.vault).exists())
        rows = mw.load_mirror_rows(self.vault)
        self.assertEqual(len(rows), 1)
        # Reading Mirror folded the index on demand and published nothing.
        self.assertFalse(ts.active_index_path(self.vault).exists())

    def test_alternatives_are_bounded(self) -> None:
        fixture = self.contradiction_fixture(third=True)
        row = mw.load_mirror_rows(self.vault)[0]
        self.assertEqual(len(row.alternatives), 2)
        self.assertLessEqual(len(row.alternatives), mw.MAX_ALTERNATIVES)
        self.assertEqual(len(row.citations), len(fixture["claims"]))


# --------------------------------------------------------------------------
# Bounded scope and quiet
# --------------------------------------------------------------------------


class BoundedScopeTests(MirrorWorkTestCase):
    def _gap_item(self) -> dict:
        return tp.validate_temporal_work_item(
            {
                "kind": "missing_anchor",
                "subject_ref": "person/katie",
                "requested_field": "birth_date",
                "allowed_surfaces": ["mirror", "timeline"],
            },
            now=NOW,
        )

    def test_routine_gaps_never_render_as_mirror_rows(self) -> None:
        """§2.3: open gaps are Timeline's normal state, not Mirror's debt."""
        fixture = self.contradiction_fixture()
        self.publish_items(fixture["item"], self._gap_item())
        rows = mw.load_mirror_rows(self.vault)
        self.assertEqual([row.kind for row in rows], ["contradiction"])
        # Event identity I3: `same_event`/`possible_overmerge` join the
        # allowlist (design §6.3 — every actionable Mirror row has Play now),
        # and a routine gap still never renders regardless.
        self.assertEqual(
            mw.MIRROR_WORK_ITEM_KINDS,
            ("contradiction", "identity_uncertain", "residence_overlap",
         "same_event", "possible_overmerge"),
        )

    def test_an_item_that_does_not_allow_mirror_does_not_render(self) -> None:
        fixture = self.contradiction_fixture()
        item = dict(fixture["item"], allowed_surfaces=["timeline"])
        self.publish_items(item)
        self.assertEqual(mw.load_mirror_rows(self.vault), [])

    def test_dismissed_and_obsolete_items_do_not_render(self) -> None:
        fixture = self.contradiction_fixture()
        for state in mw.HIDDEN_ITEM_STATES:
            self.publish_items(dict(fixture["item"], state=state))
            self.assertEqual(mw.load_mirror_rows(self.vault), [], state)

    def test_rows_are_capped_and_ordered_by_severity(self) -> None:
        fixture = self.contradiction_fixture()
        identity = self.identity_fixture()
        self.publish_items(fixture["item"], identity["item"])

        rows = mw.load_mirror_rows(self.vault)
        self.assertEqual([row.kind for row in rows], ["contradiction", "identity_uncertain"])
        self.assertGreater(rows[0].severity, rows[1].severity)
        self.assertEqual(len(mw.load_mirror_rows(self.vault, cap=1)), 1)
        self.assertEqual(mw.MIRROR_ROW_CAP, 12)

    def test_no_row_is_admitted_to_the_daily_queue_in_this_release(self) -> None:
        """§8.3/§13: Mirror-to-queue admission is the deferred issue, not this."""
        fixture = self.contradiction_fixture()
        identity = self.identity_fixture()
        self.publish_items(fixture["item"], identity["item"])
        for row in mw.load_mirror_rows(self.vault):
            self.assertNotIn("daily_question", json.dumps(row.to_dict()))

    def test_reading_mirror_writes_nothing(self) -> None:
        self.contradiction_fixture()
        before = self.files()
        mw.load_mirror_rows(self.vault)
        self.assertEqual(before, self.files())

    def test_a_published_work_items_file_that_will_not_parse_is_refused_by_name(self) -> None:
        path = ts.store_path(self.vault, tp.WORK_ITEMS_FILE)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{not json", encoding="utf-8")
        with self.assertRaises(mw.MirrorWorkError) as caught:
            mw.load_work_items(self.vault)
        self.assertEqual(caught.exception.code, "work_items_unreadable")

    def test_no_work_items_file_is_a_normal_early_state(self) -> None:
        self.assertEqual(mw.load_work_items(self.vault), [])
        self.assertEqual(mw.load_mirror_rows(self.vault), [])

    def test_a_bare_list_of_items_is_accepted(self) -> None:
        fixture = self.contradiction_fixture()
        path = ts.store_path(self.vault, tp.WORK_ITEMS_FILE)
        path.write_text(json.dumps([fixture["item"]]), encoding="utf-8")
        self.assertEqual(len(mw.load_mirror_rows(self.vault)), 1)


# --------------------------------------------------------------------------
# Resolution — durable evidence, and closure only when the claims agree
# --------------------------------------------------------------------------


class ResolutionPublishesTests(MirrorWorkTestCase):
    """T-Q-06 — `eras.md` §10: *resolve_mirror_item publishes*.

    A correction that only reaches the receipts leaves every surface showing
    the row the person just closed: Timeline, the whisper lane, the daily queue
    and Mirror all read the PUBLISHED generation. "Answer once, closed
    everywhere" is a promise about what those surfaces show.

    Verified against v235/v236 first: `mirror_work` imported no publication
    module and `resolve_mirror_item` returned straight from the correction, so
    the projection only moved on the next compile.
    """

    def published(self) -> dict:
        import temporal_publication as tpub  # noqa: PLC0415

        return tpub.read_work_items(self.vault) or {}

    def test_the_generation_advances_and_the_row_stops_being_derived(self):
        fixture = self.contradiction_fixture()
        before = self.published().get("projection_generation") or 0

        resolution = mw.resolve_mirror_item(
            self.vault,
            item=fixture["item"],
            resolution_text="It was 1978 — I mixed our anniversary up with Ann's.",
            retire_claim_ids=[fixture["claims"][1]],
            author="owner",
            now=NOW,
        )

        after = self.published()
        self.assertGreater(resolution.projection_generation or 0, before)
        self.assertEqual(after.get("projection_generation"),
                         resolution.projection_generation)
        self.assertNotIn(
            fixture["item"]["work_item_id"],
            [row.get("work_item_id") for row in (after.get("work_items") or ())],
        )
        # The alias map travels in the same generation it describes.
        self.assertIn("work_item_aliases", after)

    def test_an_abandoned_resolution_publishes_nothing_because_it_wrote_nothing(self):
        fixture = self.contradiction_fixture()
        before = self.published().get("projection_generation") or 0
        resolution = mw.resolve_mirror_item(
            self.vault,
            item=fixture["item"],
            resolution_text="",
            retire_claim_ids=[fixture["claims"][1]],
            now=NOW,
        )
        self.assertEqual(resolution.outcome, "abandoned")
        self.assertIsNone(resolution.projection_generation)
        self.assertEqual(self.published().get("projection_generation") or 0, before)

    def test_a_publish_failure_is_loud_and_the_correction_survives_it(self):
        """The order that cannot lose the answer.

        The correction is durable BEFORE the projection is derived, so a
        publish that fails names the correction that survived it and a retry
        writes nothing twice. Swallowing this would leave the person looking at
        the row they just closed with nothing anywhere saying why.
        """
        import temporal_publication as tpub  # noqa: PLC0415

        fixture = self.contradiction_fixture()
        original = tpub.publish

        def explode(*args, **kwargs):
            raise RuntimeError("disk went away")

        tpub.publish = explode
        try:
            with self.assertRaises(mw.MirrorWorkError) as caught:
                mw.resolve_mirror_item(
                    self.vault,
                    item=fixture["item"],
                    resolution_text="It was 1978.",
                    retire_claim_ids=[fixture["claims"][1]],
                    now=NOW,
                )
        finally:
            tpub.publish = original

        self.assertEqual(caught.exception.code, "resolution_publish_failed")
        correction_id = caught.exception.detail["correction_id"]
        self.assertTrue(correction_id)
        # Durable: the correction is on disk and the claim is already retired.
        self.assertTrue((self.vault / caught.exception.detail["correction_path"]).is_file())
        index = self.index()
        by_id = {row["claim_id"]: row for row in index["claims"]}
        self.assertEqual(by_id[fixture["claims"][1]]["status"], "superseded")

        # Retrying is a no-op in evidence and publishes the same correction.
        retried = mw.resolve_mirror_item(
            self.vault,
            item=fixture["item"],
            resolution_text="It was 1978.",
            retire_claim_ids=[fixture["claims"][1]],
            now=NOW,
        )
        self.assertEqual(retried.correction_id, correction_id)
        self.assertGreater(retried.projection_generation or 0, 0)

    def test_publish_false_is_for_batching_and_states_that_it_did_not(self):
        fixture = self.contradiction_fixture()
        before = self.published().get("projection_generation") or 0
        resolution = mw.resolve_mirror_item(
            self.vault,
            item=fixture["item"],
            resolution_text="It was 1978.",
            retire_claim_ids=[fixture["claims"][1]],
            publish=False,
            now=NOW,
        )
        self.assertEqual(resolution.outcome, "corrected")
        self.assertIsNone(resolution.projection_generation)
        self.assertEqual(self.published().get("projection_generation") or 0, before)
        self.assertEqual(
            "resolution_publish_failed" in mw.MIRROR_WORK_ERROR_CODES, True
        )


class ResolutionTests(MirrorWorkTestCase):
    def test_a_resolution_writes_durable_evidence_and_the_row_then_closes(self) -> None:
        fixture = self.contradiction_fixture()
        losing = fixture["claims"][1]

        resolution = mw.resolve_mirror_item(
            self.vault,
            item=fixture["item"],
            resolution_text="It was 1978 — I mixed our anniversary up with Ann's.",
            retire_claim_ids=[losing],
            author="owner",
            now=NOW,
        )

        self.assertEqual(resolution.outcome, "corrected")
        self.assertTrue(resolution.wrote_correction)
        self.assertEqual(resolution.retired_claim_ids, (losing,))

        # The person's words are a durable source…
        source = self.vault / str(resolution.source_path)
        self.assertTrue(source.is_file())
        self.assertIn("I mixed our anniversary up", source.read_text())
        # …and the correction is a source too, naming what stops standing.
        correction = self.vault / str(resolution.correction_path)
        self.assertTrue(correction.is_file())
        text = correction.read_text()
        self.assertIn(losing, text)
        self.assertIn(fixture["item"]["work_item_id"], text)

        index = self.index()
        by_id = {row["claim_id"]: row for row in index["claims"]}
        self.assertEqual(by_id[losing]["status"], "superseded")
        # Nothing is deleted — the retired claim keeps its full record.
        self.assertEqual(by_id[losing]["subject_mention"], "Katie")
        self.assertTrue(by_id[losing]["status_marks"])

        # O-E6: the resolution PUBLISHED, so the file Mirror reads is the fold's
        # own generation and no longer implies this contradiction at all.
        self.assertGreater(resolution.projection_generation or 0, 0)
        self.assertEqual(mw.load_mirror_rows(self.vault), [])
        self.assertNotIn(
            fixture["item"]["work_item_id"],
            [row.get("work_item_id") for row in mw.load_work_items(self.vault)],
        )
        # The row's own state is still DERIVED from the claims, which is the
        # property this test is about: shown the item, Mirror says resolved.
        closed = mw.mirror_rows([fixture["item"]], self.index(), include_resolved=True)
        self.assertEqual([row.state for row in closed], ["resolved"])
        self.assertEqual(closed[0].work_item_id, fixture["item"]["work_item_id"])

    def test_retiring_one_of_three_leaves_the_row_open(self) -> None:
        """§2.5: it closes when the claims stop conflicting — not when answered."""
        fixture = self.contradiction_fixture(third=True)
        mw.resolve_mirror_item(
            self.vault,
            item=fixture["item"],
            resolution_text="Not 1983, definitely.",
            retire_claim_ids=[fixture["claims"][2]],
            now=NOW,
        )
        self.index()
        rows = mw.load_mirror_rows(self.vault)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].state, "open")

    def test_a_stored_resolved_state_does_not_close_a_row_whose_claims_conflict(self) -> None:
        fixture = self.contradiction_fixture()
        self.publish_items(dict(fixture["item"], state="resolved"))
        rows = mw.load_mirror_rows(self.vault)
        self.assertEqual([row.state for row in rows], ["open"])

    def test_claims_that_stop_conflicting_close_the_row_without_a_correction(self) -> None:
        """*1984* beside *1980/1990* is corroboration at a coarser grain."""
        narrow = self.file_claim(
            "We moved in 1984.",
            claim("the house", "move", "1984", quote="We moved in 1984.",
                  granularity="year"),
            turn_ref="t1",
        )
        wide = self.file_claim(
            "We moved sometime in the eighties.",
            {
                "claim_type": "range",
                "source_kind": "conversation",
                "subject_mention": "the house",
                "event_kind": "move",
                "temporal_value": {
                    "best": "1980/1990",
                    "earliest": "1980",
                    "latest": "1990",
                    "granularity": "range",
                    "confidence": "approximate",
                    "basis": "stated",
                },
                "evidence": [{"quote": "We moved sometime in the eighties."}],
                "basis": "explicit",
                "confidence": 0.5,
                "created_at": "2026-08-26T09:00:00Z",
            },
            turn_ref="t2",
        )
        item = tp.validate_temporal_work_item(
            {
                "kind": "contradiction",
                "subject_ref": "place/the-house",
                "event_ref": "event:move",
                "claim_refs": [narrow, wide],
                "allowed_surfaces": ["mirror"],
            },
            now=NOW,
        )
        self.publish_items(item)
        self.assertEqual(mw.load_mirror_rows(self.vault), [])

    def test_an_undated_active_claim_keeps_the_row_open(self) -> None:
        """We cannot measure that it stopped conflicting, so we do not claim it."""
        item = tp.work_item_from_dict(
            tp.validate_temporal_work_item(
                {
                    "kind": "contradiction",
                    "subject_ref": "person/katie",
                    "claim_refs": ["claim:" + "a" * 24, "claim:" + "b" * 24],
                    "allowed_surfaces": ["mirror"],
                },
                now=NOW,
            )
        )
        active = [
            {"claim_id": "claim:" + "a" * 24, "status": "active", "claim_type": "relative_order"},
            {"claim_id": "claim:" + "b" * 24, "status": "active", "claim_type": "relative_order"},
        ]
        self.assertEqual(mw.derive_row_state(item, active, view=None), "open")

    def test_resolution_is_idempotent(self) -> None:
        fixture = self.contradiction_fixture()
        kwargs = {
            "item": fixture["item"],
            "resolution_text": "It was 1978.",
            "retire_claim_ids": [fixture["claims"][1]],
            "now": NOW,
        }
        first = mw.resolve_mirror_item(self.vault, **kwargs)
        files = self.files()
        index = ts.active_index_bytes(ts.fold_active_index(self.vault))

        second = mw.resolve_mirror_item(self.vault, **kwargs)
        self.assertEqual(first.correction_id, second.correction_id)
        self.assertEqual(first.source_path, second.source_path)
        self.assertEqual(files, self.files())
        self.assertEqual(index, ts.active_index_bytes(ts.fold_active_index(self.vault)))

    def test_a_replacement_is_a_new_claim_through_a_new_receipt(self) -> None:
        fixture = self.contradiction_fixture()
        replacement = claim(
            "Katie",
            "married",
            "1979-06-14",
            quote="We married on June 14th, 1979 — I keep saying the wrong year.",
        )
        resolution = mw.resolve_mirror_item(
            self.vault,
            item=fixture["item"],
            resolution_text="We married on June 14th, 1979 — I keep saying the wrong year.",
            retire_claim_ids=fixture["claims"],
            claims_for=lambda ref: [replacement],
            extractor_version=OWNER,
            recorder="mirror",
            now=NOW,
        )
        self.assertEqual(resolution.outcome, "corrected")
        self.assertTrue(str(resolution.receipt_path).startswith("state/temporal_claims/receipts/"))
        self.assertTrue((self.vault / str(resolution.receipt_path)).is_file())

        index = self.index()
        by_id = {row["claim_id"]: row for row in index["claims"]}
        for retired in fixture["claims"]:
            self.assertEqual(by_id[retired]["status"], "superseded")
        fresh = [
            row for row in index["claims"]
            if row["status"] == "active" and row["extractor_version"] == OWNER
        ]
        self.assertEqual(len(fresh), 1)
        # The replacement cites the promoted words it came from — as
        # provenanced as the claim it replaced.
        self.assertEqual(fresh[0]["source_ref"]["source_id"], resolution.source_id)
        self.assertEqual(mw.load_mirror_rows(self.vault), [])

    def test_a_replacement_without_an_extractor_version_is_refused(self) -> None:
        fixture = self.contradiction_fixture()
        with self.assertRaises(mw.MirrorWorkError) as caught:
            mw.resolve_mirror_item(
                self.vault,
                item=fixture["item"],
                resolution_text="It was 1979.",
                retire_claim_ids=[fixture["claims"][1]],
                claims_for=lambda ref: [],
            )
        self.assertEqual(caught.exception.code, "resolution_needs_extractor_version")

    def test_mirror_cannot_retire_a_claim_its_row_does_not_cite(self) -> None:
        fixture = self.contradiction_fixture()
        stranger = self.file_claim(
            "I started at Boeing in 1990.",
            claim("Boeing", "job", "1990", quote="I started at Boeing in 1990.",
                  granularity="year"),
            turn_ref="t7",
        )
        before = self.files()
        with self.assertRaises(mw.MirrorWorkError) as caught:
            mw.resolve_mirror_item(
                self.vault,
                item=fixture["item"],
                resolution_text="Something else entirely.",
                retire_claim_ids=[stranger],
            )
        self.assertEqual(caught.exception.code, "resolution_targets_uncited_claim")
        self.assertEqual(before, self.files())

    def test_a_gap_item_is_not_resolvable_through_mirror(self) -> None:
        with self.assertRaises(mw.MirrorWorkError) as caught:
            mw.resolve_mirror_item(
                self.vault,
                item=tp.validate_temporal_work_item(
                    {
                        "kind": "precision_gap",
                        "subject_ref": "person/katie",
                        "requested_field": "married_date",
                        "allowed_surfaces": ["mirror"],
                    },
                    now=NOW,
                ),
                resolution_text="1978",
                retire_claim_ids=["claim:" + "a" * 24],
            )
        self.assertEqual(caught.exception.code, "mirror_item_not_actionable")


# --------------------------------------------------------------------------
# "I don't know" — the case §2.5 spends a whole bullet on
# --------------------------------------------------------------------------


class AbandonTests(MirrorWorkTestCase):
    def test_abandoning_invents_no_correction_and_the_row_remains(self) -> None:
        fixture = self.contradiction_fixture()
        before = self.files()

        resolution = mw.abandon_mirror_item(fixture["item"], reason="I don't know.")
        self.assertEqual(resolution.outcome, "abandoned")
        self.assertFalse(resolution.wrote_correction)
        self.assertEqual(resolution.retired_claim_ids, ())
        self.assertIsNone(resolution.correction_id)

        self.assertEqual(before, self.files())
        self.assertEqual([row.state for row in mw.load_mirror_rows(self.vault)], ["open"])

    def test_the_abandon_path_cannot_write_because_it_has_no_vault(self) -> None:
        """Structural, not a phrase list: no vault root, no possible write."""
        import inspect  # noqa: PLC0415

        params = inspect.signature(mw.abandon_mirror_item).parameters
        self.assertNotIn("vault_root", params)

    def test_an_answer_that_names_nothing_to_retire_writes_nothing(self) -> None:
        fixture = self.contradiction_fixture()
        before = self.files()
        resolution = mw.resolve_mirror_item(
            self.vault,
            item=fixture["item"],
            resolution_text="I honestly don't know which year it was.",
            retire_claim_ids=[],
        )
        self.assertEqual(resolution.outcome, "abandoned")
        self.assertEqual(before, self.files())
        self.assertEqual([row.state for row in mw.load_mirror_rows(self.vault)], ["open"])

    def test_naming_claims_with_no_words_writes_nothing(self) -> None:
        fixture = self.contradiction_fixture()
        before = self.files()
        resolution = mw.resolve_mirror_item(
            self.vault,
            item=fixture["item"],
            resolution_text="   ",
            retire_claim_ids=[fixture["claims"][1]],
        )
        self.assertEqual(resolution.outcome, "abandoned")
        self.assertEqual(before, self.files())


# --------------------------------------------------------------------------
# Identity rows
# --------------------------------------------------------------------------


class IdentityRowTests(MirrorWorkTestCase):
    def test_an_ambiguous_mention_renders_with_its_candidate_set(self) -> None:
        fixture = self.identity_fixture()
        rows = mw.load_mirror_rows(self.vault)

        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row.kind, "identity_uncertain")
        self.assertEqual(row.state, "open")
        self.assertEqual(row.headline, "Who is AJ?")
        self.assertEqual(
            sorted(c["ref"] for c in row.candidates),
            ["person/aj-lang", "person/aj-vance"],
        )
        self.assertIn("aj lang", row.description)
        self.assertIn("aj vance", row.description)
        self.assertIn("Nothing was guessed", row.description)
        self.assertEqual(row.play["kind"], mw.PLAY_TARGET_KIND)
        self.assertEqual(len(row.play["candidates"]), 2)
        self.assertEqual(row.play["resolvable_claim_ids"], [fixture["claim"]])

        # The claim itself was retained, not dropped (§6.3).
        index = self.index()
        kept = {row["claim_id"]: row for row in index["claims"]}[fixture["claim"]]
        self.assertEqual(kept["status"], "active")
        self.assertEqual(kept["subject_mention"], "AJ")

    def test_one_row_per_mention_however_many_claims_said_it(self) -> None:
        """§5.4: one row for "who is AJ?", not one per claim."""
        fixture = self.identity_fixture()
        second = ident.identity_work_item(
            fixture["record"], claim_refs=[fixture["claim"], "claim:" + "c" * 24], now=NOW
        )
        self.assertEqual(second["work_item_id"], fixture["item"]["work_item_id"])

    def test_the_row_closes_when_the_mention_is_placed(self) -> None:
        fixture = self.identity_fixture()
        resolution = mw.resolve_mirror_item(
            self.vault,
            item=fixture["item"],
            resolution_text="That's AJ Lang — my brother-in-law.",
            retire_claim_ids=[fixture["claim"]],
            claims_for=lambda ref: [
                {
                    **claim("AJ", "met", "1994", quote="That's AJ Lang — my brother-in-law.",
                            granularity="year"),
                    "subject_ref": "person/aj-lang",
                }
            ],
            extractor_version=OWNER,
            now=NOW,
        )
        self.assertEqual(resolution.outcome, "corrected")
        self.assertGreater(resolution.projection_generation or 0, 0)
        self.assertEqual(mw.load_mirror_rows(self.vault), [])
        closed = mw.mirror_rows([fixture["item"]], self.index(), include_resolved=True)
        self.assertEqual([row.state for row in closed], ["resolved"])

    def test_a_resolved_subject_is_not_a_mirror_row(self) -> None:
        record = ident.resolve_mention(
            "AJ Lang",
            roster={"type": "person", "entities": [{"name": "AJ Lang", "slug": "aj-lang"}]},
            evidence_ref="conversation:msg-aj",
            now=NOW,
        )
        self.assertEqual(record.resolution, "same")
        self.assertIsNone(ident.identity_work_item(record, claim_refs=["claim:" + "a" * 24]))


# --------------------------------------------------------------------------
# Blocking nothing, and reading only
# --------------------------------------------------------------------------


class NonBlockingTests(MirrorWorkTestCase):
    def test_an_unresolved_contradiction_blocks_no_other_claim_or_row(self) -> None:
        fixture = self.contradiction_fixture()
        identity = self.identity_fixture()
        unrelated = self.file_claim(
            "We moved to Redlands in 1969.",
            claim("Redlands", "move", "1969", quote="We moved to Redlands in 1969.",
                  granularity="year"),
            turn_ref="t5",
        )
        self.publish_items(fixture["item"], identity["item"])

        index = self.index()
        active = {row["claim_id"] for row in ts.active_claims(index)}
        # Every claim — the contradicting pair included — is still active and
        # available to derivation. Nothing is quarantined by disagreeing.
        self.assertIn(unrelated, active)
        for claim_id in fixture["claims"]:
            self.assertIn(claim_id, active)
        self.assertIn(identity["claim"], active)

        rows = {row.work_item_id: row for row in mw.load_mirror_rows(self.vault)}
        self.assertEqual(len(rows), 2)
        self.assertEqual(index["counts"]["retracted"], 0)
        self.assertEqual(index["unresolved_correction_targets"], [])

    def test_mirror_never_imports_timeline_derivation(self) -> None:
        """Read-side only: the substrate does not read Mirror, and Mirror does
        not reach into how the timeline is derived."""
        forbidden = {
            "temporal_timeline",
            "timeline",
            "timeline_interaction",
            "timeline_corroboration",
            "question_planner",
            "arc_planner",
        }
        for name in ("mirror_work.py", "mirror.py"):
            tree = ast.parse((ROOT / "system" / name).read_text(encoding="utf-8"))
            imported: set[str] = set()
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    imported.update(alias.name.split(".")[0] for alias in node.names)
                elif isinstance(node, ast.ImportFrom) and node.module:
                    imported.add(node.module.split(".")[0])
            self.assertEqual(imported & forbidden, set(), f"{name} imports {imported & forbidden}")

    def test_the_bound_entry_points_read_and_write_this_vault(self) -> None:
        """`mirror.load_actionable_rows` is the local binding, nothing more."""
        import mirror  # noqa: PLC0415

        fixture = self.contradiction_fixture()
        saved = mirror.REPO_DIR
        mirror.REPO_DIR = self.vault
        try:
            rows = mirror.load_actionable_rows()
            self.assertEqual([row.work_item_id for row in rows],
                             [fixture["item"]["work_item_id"]])
            resolution = mirror.resolve_actionable_item(
                fixture["item"],
                "It was 1978.",
                retire_claim_ids=[fixture["claims"][1]],
                now=NOW,
            )
            self.assertEqual(resolution.outcome, "corrected")
            self.assertEqual(mirror.load_actionable_rows(), [])
            # The abandon path is bound for symmetry and still writes nothing.
            before = self.files()
            abandoned = mirror.abandon_actionable_item(fixture["item"], "I don't know.")
            self.assertEqual(abandoned.outcome, "abandoned")
            self.assertEqual(before, self.files())
        finally:
            mirror.REPO_DIR = saved

    def test_the_synthesis_page_says_nothing_about_work_items(self) -> None:
        """Quiet: no counts pushed to another surface (§2.5)."""
        import mirror  # noqa: PLC0415

        prompt = mirror.build_mirror_prompt([])
        for token in ("work item", "work_item", "contradiction row", "Play now"):
            self.assertNotIn(token, prompt)
        page = mirror.compose_page("## Sit with\n\n- one\n", [])
        for line in page.splitlines():
            if line.startswith(("contradictions:", "insights:", "positions:")):
                continue
            self.assertNotIn("work", line.lower())


if __name__ == "__main__":
    unittest.main()
