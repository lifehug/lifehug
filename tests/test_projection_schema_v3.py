"""E-L2d — `value_shape`, the lanes, and projection schema v3 behind a flag.

Controlling design: lifehug-platform `docs/design/timeline-eras.md` v2.1 §0.1
H3, §3.4, §9.2, §9.3, §9.6, §12 rows 8 and 20, §14.2, §14.5; the schema
rollout discipline is `docs/design/eras.md` §7.8.

    The node already carries the distinction structurally … but in four
    fields with four "never a bound" comments and no single tag, so a
    renderer can and did read a window as a bar. §3.4 adds ONE additive,
    derived read-model field, `value_shape`, defined once in the projection
    and consumed by every host. (H3)

Every test here was run against **v277 (`6356745`)** before any code existed
and seen failing — `AttributeError: module 'temporal_projection' has no
attribute 'derive_value_shape'` / `'projection_schema_version'`, and
`KeyError: 'value_shape'` on the published nodes.

Synthetic data only; NEVER references ~/Workspace/dave.
"""

from __future__ import annotations

import json
import os
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "system"))
sys.path.insert(0, str(ROOT / "tests"))

import chronology as chrono  # noqa: E402
import episode_binder as eb  # noqa: E402
import episode_fold as ef  # noqa: E402
import landmark_projection as lp  # noqa: E402
import temporal_claims as tc  # noqa: E402
import temporal_projection as tp  # noqa: E402
import temporal_publication as pub  # noqa: E402
import temporal_store as ts  # noqa: E402
import temporal_timeline as tt  # noqa: E402
import timeline as tl  # noqa: E402
from tempdirs import root_parent_tmp  # noqa: E402

NOW = "2026-09-01T12:00:00Z"
BIRTH_DAY = "1981-07-11"

ROSTERS = {
    "place": {"type": "place", "entities": [
        {"name": "Cedarport", "slug": "cedarport",
         "aliases": ["the Cedarport house"]},
    ]},
}

STORY_SOURCE = "classification:answers-a1#aaa1"


def value(text: str) -> dict:
    grain = {4: "year", 7: "month", 10: "day"}[len(text)]
    return {"best": text, "earliest": text, "latest": text, "granularity": grain,
            "basis": "stated", "confidence": "certain"}


def flag(version: object):
    """Set (or clear) the writer flag for the duration of a `with` block."""

    class _Flag:
        def __enter__(self):
            self.previous = os.environ.get(tp.PROJECTION_SCHEMA_FLAG)
            if version is None:
                os.environ.pop(tp.PROJECTION_SCHEMA_FLAG, None)
            else:
                os.environ[tp.PROJECTION_SCHEMA_FLAG] = str(version)
            return self

        def __exit__(self, *exc):
            if self.previous is None:
                os.environ.pop(tp.PROJECTION_SCHEMA_FLAG, None)
            else:
                os.environ[tp.PROJECTION_SCHEMA_FLAG] = self.previous
            return False

    return _Flag()


def node(**overrides) -> dict:
    payload = {
        "node_id": "node:one",
        "node_kind": "event",
        "event_kind": "moment",
        "input_claim_refs": ["claim:one"],
        "calculation_rule_version": tt.CALCULATION_RULE_VERSION,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# The flag itself (§7.8: tolerant readers first, writer behind a flag,
# rollback = flag off)
# ---------------------------------------------------------------------------


class TheWriterFlag(unittest.TestCase):

    def test_the_default_writer_is_still_v2(self):
        with flag(None):
            self.assertEqual(tp.projection_schema_version(), 2)
        self.assertEqual(tp.PROJECTION_SCHEMA_VERSION, 2)

    def test_the_flag_selects_v3(self):
        with flag(3):
            self.assertEqual(tp.projection_schema_version(), 3)

    def test_rollback_is_the_flag_and_nothing_else(self):
        with flag(3):
            self.assertEqual(tp.projection_schema_version(), 3)
        with flag(2):
            self.assertEqual(tp.projection_schema_version(), 2)

    def test_a_typo_rolls_back_rather_than_crashing_a_deploy(self):
        """§7.8 step 3's direction of failure. `LIFEHUG_PROJECTION_SCHEMA_
        VERSION=v3` is a mistake somebody makes at 2am; the safe answer is
        the current writer, not a stack trace in every job on the fleet."""
        for typo in ("v3", "", "  ", "3.0", "9", "1"):
            with flag(typo):
                self.assertEqual(tp.projection_schema_version(), 2, typo)

    def test_v1_is_a_read_shape_and_never_a_writer_target(self):
        self.assertIn(1, tp.PROJECTION_SCHEMA_VERSIONS)
        self.assertNotIn(1, tp.PROJECTION_SCHEMA_WRITABLE)
        self.assertEqual(tuple(tp.PROJECTION_SCHEMA_WRITABLE), (2, 3))


# ---------------------------------------------------------------------------
# §3.4 — the ONE tag, driven over all three sources (§14.2's parity promise)
# ---------------------------------------------------------------------------


class ValueShapeOverItsThreeSources(unittest.TestCase):
    """*`value_shape` is derived once in the projection and parity-tested
    against its three sources* (§14.2)."""

    def test_a_frames_definition_span_is_a_duration(self):
        self.assertEqual(
            tp.derive_value_shape(node(
                node_kind="period", event_kind="age_frame",
                definition_span={"start": value("2001-07-11"),
                                 "end": value("2011-07-11")},
            )),
            "duration",
        )

    def test_a_participation_episodes_started_ended_pair_is_a_duration(self):
        for kind in tp.PARTICIPATION_EVENT_KINDS:
            self.assertEqual(
                tp.derive_value_shape(node(
                    node_kind="episode", event_kind=kind,
                    best_temporal_value=chrono.parse_edtf("1996/2001").to_dict(),
                )),
                "duration",
                kind,
            )

    def test_a_best_temporal_value_is_a_point(self):
        self.assertEqual(
            tp.derive_value_shape(node(best_temporal_value=value("1996-06"))),
            "point",
        )

    def test_a_possible_value_is_a_window(self):
        self.assertEqual(
            tp.derive_value_shape(node(
                possible_temporal_value=chrono.parse_edtf("1996/2001").to_dict(),
            )),
            "window",
        )

    def test_nothing_at_all_is_none(self):
        self.assertEqual(tp.derive_value_shape(node()), "none")

    def test_the_four_shapes_are_the_closed_vocabulary(self):
        self.assertEqual(tp.VALUE_SHAPES, ("duration", "point", "window", "none"))

    def test_it_is_derived_and_never_an_input(self):
        """H3's whole point: the tag is a FUNCTION of the fields it describes,
        so a caller cannot set it to something they are not."""
        with flag(3):
            out = tp.validate_calculated_timeline_node(
                node(best_temporal_value=value("1996-06"), value_shape="duration")
            )
        self.assertEqual(out["value_shape"], "point")

    def test_a_month_grain_point_stays_a_point(self):
        """§3.4: *a mark as wide as its stated grain* — a month-grain value is
        a month-wide POINT, not a duration. Reading width instead of structure
        is exactly the mistake this tag exists to prevent."""
        self.assertEqual(
            tp.derive_value_shape(node(best_temporal_value=value("1996-06"))),
            "point",
        )


class RowEightAPointEventThatGainsAWindow(unittest.TestCase):
    """§12 row 8: *Point event gets a window → `window`, never `duration`.*

    The window record IS a multi-year interval — it is the containing
    episode's own span — so a renderer that decided by width would draw a bar
    across five years of somebody's life for a moment that lasted an
    afternoon.
    """

    def test_a_window_that_is_years_wide_is_still_a_window(self):
        window = chrono.parse_edtf("1996-06/2001-08").to_dict()
        self.assertEqual(tp.derive_value_shape(node(possible_temporal_value=window)),
                         "window")

    def test_even_on_an_episode_node_a_window_is_never_a_duration(self):
        """The duration branch is about the node's OWN interval. An episode
        that has not been dated and inherited a window has not got one."""
        self.assertEqual(
            tp.derive_value_shape(node(
                node_kind="episode", event_kind="residence",
                possible_temporal_value=chrono.parse_edtf("1996/2001").to_dict(),
            )),
            "window",
        )


class AWindowAddsNoWidth(unittest.TestCase):
    """ADR 0027 unchanged (§3.4): *the placement score counts stated/derived
    width of `point`/`duration` only*."""

    def test_a_window_node_carries_no_width_bearing_value(self):
        """The structural invariant behind the promise: a `window` has neither
        a `best_temporal_value` nor a `definition_span`, so there is no
        interval for the score to measure. Nothing has to remember to skip
        it."""
        with flag(3):
            out = tp.validate_calculated_timeline_node(node(
                possible_temporal_value=chrono.parse_edtf("1996/2001").to_dict(),
            ))
        self.assertEqual(out["value_shape"], "window")
        self.assertIsNone(out["best_temporal_value"])
        self.assertNotIn("definition_span", out)

    def test_the_score_never_reads_a_possible_value(self):
        """A source guard, because the promise is about a function that does
        NOT do something: `timeline`'s scorer reads dates off the timeline
        data it is handed and has no branch on `possible_temporal_value` at
        all. If one ever appears, this fails and somebody re-reads ADR 0027."""
        body = Path(tl.__file__).read_text("utf-8")
        self.assertNotIn("possible_temporal_value", body)


# ---------------------------------------------------------------------------
# §9.2 — the lanes, and the table that cannot go stale
# ---------------------------------------------------------------------------


class TheLaneTable(unittest.TestCase):

    def test_every_participation_kind_has_a_lane(self):
        """The parity guard (recurring-defect doctrine): a fifth span domain
        added to `landmark_projection.PARTICIPATION_EPISODE_KINDS` fails the
        BUILD here rather than drawing in no lane on somebody's Timeline."""
        self.assertEqual(
            set(tp.LANES_BY_EVENT_KIND),
            set(lp.PARTICIPATION_EPISODE_KINDS.values()),
        )

    def test_the_three_lanes_are_the_ones_the_design_names(self):
        self.assertEqual(tp.LANES, ("lived", "worked", "schooled"))
        self.assertEqual(set(tp.LANES_BY_EVENT_KIND.values()), set(tp.LANES))

    def test_service_draws_in_worked(self):
        """§9.2 has three peer lanes and a stint of service is time served
        somewhere; a fourth lane most lives never open would be worse."""
        self.assertEqual(tp.LANES_BY_EVENT_KIND["military"], "worked")

    def test_a_lane_row_names_its_group_and_a_known_lane(self):
        with self.assertRaises(tp.TimelineNodeError):
            tp.validate_lane_row({"lane": "lived", "episode_node_ids": []})
        with self.assertRaises(tp.TimelineNodeError):
            tp.validate_lane_row({"group_id": "age:self:20s", "lane": "loitered"})

    def test_the_two_lane_refusals_are_declared(self):
        """`ERROR_CODES` is the module's own list of what it can raise; a
        refusal missing from it is a reason no caller can route on."""
        self.assertIn("lane_needs_group", tp.ERROR_CODES)
        self.assertIn("unknown_lane", tp.ERROR_CODES)

    def test_members_are_sorted_so_two_hosts_publish_the_same_bytes(self):
        out = tp.validate_lane_row({
            "group_id": "age:self:20s", "lane": "lived",
            "episode_node_ids": ["episode:b", "episode:a", "episode:b"],
        })
        self.assertEqual(out["episode_node_ids"], ["episode:a", "episode:b"])


# ---------------------------------------------------------------------------
# The end-to-end vault: two stays, one job, one undated story inside one stay
# ---------------------------------------------------------------------------


class VaultCase(unittest.TestCase):

    def setUp(self) -> None:
        self.root = root_parent_tmp(self, ROOT, prefix="el2d-v3-")
        (self.root / "state").mkdir(parents=True, exist_ok=True)
        (self.root / "sources").mkdir(parents=True, exist_ok=True)
        rosters = self.root / "state" / "entity_rosters"
        rosters.mkdir(parents=True, exist_ok=True)
        for kind, snapshot in ROSTERS.items():
            (rosters / f"{kind}.json").write_text(json.dumps(snapshot), "utf-8")
        lp.file_landmark_record(
            self.root, "residences",
            {"label": "Cedarport", "city": "Cedarport",
             "span": {"start": value("1996-06"), "end": value("2001-08")}},
            ordinal=1, now=NOW,
        )
        lp.file_landmark_record(
            self.root, "work",
            {"label": "Tidewheel Works", "what": "Tidewheel Works",
             "span": {"start": value("1997-01"), "end": value("2000-12")}},
            ordinal=2, now=NOW,
        )
        lp.file_landmark_record(
            self.root, "birth",
            {"label": "born", "date": value(BIRTH_DAY)},
            ordinal=3, now=NOW,
        )
        story = tc.validate_temporal_claim({
            "source_kind": "conversation",
            "source_ref": {"source_id": STORY_SOURCE, "revision": "sha256:" + "a" * 64},
            "evidence": [{"quote": "A storm dropped a tree on the Cedarport house."}],
            "extractor_version": "classifier:1",
            "created_at": "2026-08-30T00:00:00Z",
            "basis": "explicit",
            "confidence": 0.9,
            "status": "active",
            "claim_type": "occurrence",
            "subject_mention": "I",
            "event_mention": "The tree fell on the Cedarport house",
            "event_kind": "moment",
            "event_ref": tp.derive_node_id(
                node_kind="event", event_kind="moment",
                subject_refs=["I"], discriminator=STORY_SOURCE,
            ),
        })
        ts.write_receipt(self.root, {
            "source_ref": story["source_ref"],
            "extractor_version": "classifier:1",
            "created_at": "2026-08-30T00:00:00Z",
            "claims": [story],
        })
        ts.rebuild_active_index(self.root)
        eb.bind_episodes(self.root, apply=True, now=NOW,
                         containment_authority="applied")

    def fold(self):
        return tt.derive_calculated_timeline(
            ts.fold_active_index(self.root),
            episode_records=ef.load_episode_records(self.root),
            landmark_entries=lp.load_landmark_sources(self.root),
            birth_date=BIRTH_DAY,
            now=NOW,
        )

    def publish(self, version) -> dict:
        with flag(version):
            pub.publish(self.root, roster_snapshot=(), now=NOW)
        return pub.read_projection(self.root) or {}

    def republish(self, version) -> dict:
        """Publish again over a projection the flag already wrote once."""
        return self.publish(version)


class TheV2FileIsUnchanged(VaultCase):
    """§7.8 step 3 — *rollback = flag off*, and it has to mean byte-for-byte."""

    def test_a_v2_publication_carries_no_v3_key_anywhere(self):
        payload = self.publish(2)
        self.assertEqual(payload["projection_schema_version"], 2)
        self.assertNotIn("lanes", payload)
        self.assertNotIn("frame_display", payload)
        for row in payload["nodes"]:
            self.assertNotIn("value_shape", row)
            self.assertEqual(row["schema_version"], 2)

    def test_the_default_writer_and_the_flag_at_two_are_the_same_bytes(self):
        with flag(2):
            first = json.dumps(
                pub.projection_payload(self.fold(), published_at=NOW,
                                       input_digest="d", timings={}),
                sort_keys=True,
            )
        with flag(None):
            second = json.dumps(
                pub.projection_payload(self.fold(), published_at=NOW,
                                       input_digest="d", timings={}),
                sort_keys=True,
            )
        self.assertEqual(first, second)

    def test_v3_is_purely_ADDITIVE_over_v2(self):
        """Every key and every node field a v2 file carries is carried
        identically by the v3 file; v3 only adds."""
        with flag(2):
            two = pub.projection_payload(self.fold(), published_at=NOW,
                                         input_digest="d", timings={})
        with flag(3):
            three = pub.projection_payload(self.fold(), published_at=NOW,
                                           input_digest="d", timings={})
        self.assertEqual(set(three) - set(two), {"lanes", "frame_display"})
        for left, right in zip(two["nodes"], three["nodes"], strict=True):
            trimmed = {k: v for k, v in right.items()
                       if k not in ("value_shape", "schema_version")}
            self.assertEqual({k: v for k, v in left.items()
                              if k != "schema_version"}, trimmed)


class TheV3File(VaultCase):

    def test_every_node_carries_a_known_value_shape(self):
        payload = self.publish(3)
        self.assertEqual(payload["projection_schema_version"], 3)
        self.assertTrue(payload["nodes"])
        for row in payload["nodes"]:
            self.assertIn(row["value_shape"], tp.VALUE_SHAPES)
            self.assertEqual(row["schema_version"], 3)

    def test_the_stay_is_a_duration_and_the_frames_are_durations(self):
        payload = self.publish(3)
        shapes = {row["node_id"]: row["value_shape"] for row in payload["nodes"]}
        stays = [row for row in payload["nodes"] if row.get("event_kind") == "residence"]
        self.assertTrue(stays)
        self.assertEqual(shapes[stays[0]["node_id"]], "duration")
        frames = [row for row in payload["nodes"] if row.get("event_kind") == "age_frame"]
        self.assertTrue(frames)
        for row in frames:
            self.assertEqual(shapes[row["node_id"]], "duration")

    def test_the_contained_story_is_a_window_and_not_a_bar(self):
        """§12 row 8 end to end, from the PUBLISHED FILE."""
        payload = self.publish(3)
        story = [row for row in payload["nodes"]
                 if row.get("label") == "The tree fell on the Cedarport house"]
        self.assertEqual(len(story), 1)
        self.assertIsNotNone(story[0].get("possible_temporal_value"))
        self.assertEqual(story[0]["value_shape"], "window")
        self.assertIsNone(story[0]["best_temporal_value"])

    def test_the_lanes_place_the_stay_and_the_job_in_their_own_lanes(self):
        payload = self.publish(3)
        rows = payload["lanes"]
        self.assertTrue(rows)
        lanes = {row["lane"] for row in rows}
        self.assertEqual(lanes, {"lived", "worked"})
        for row in rows:
            self.assertEqual(sorted(row), sorted(tp.LANE_ROW_KEYS))
            self.assertTrue(row["episode_node_ids"])

    def test_a_lane_row_belongs_to_a_row_group_that_exists(self):
        payload = self.publish(3)
        ids = {row["node_id"] for row in payload["nodes"]}
        for row in payload["lanes"]:
            self.assertIn(row["group_id"], ids)

    def test_the_frame_display_block_names_every_frame(self):
        payload = self.publish(3)
        frames = {row["node_id"] for row in payload["nodes"]
                  if row.get("event_kind") == "age_frame"}
        self.assertEqual({row["frame_id"] for row in payload["frame_display"]}, frames)
        for row in payload["frame_display"]:
            self.assertEqual(row["frame_display"], "frame")
            self.assertFalse(row["proposal_pending"])


class TheTolerantReader(VaultCase):
    """§7.8 step 1 — the reader lands first and never refuses an older file."""

    def test_a_v2_file_reads_as_two_empty_tuples(self):
        self.publish(2)
        view = pub.calculated_view(self.root)
        self.assertEqual(view["schema_version"], 2)
        self.assertEqual(view["lanes"], ())
        self.assertEqual(view["frame_display"], ())

    def test_a_v3_file_serves_both(self):
        self.publish(3)
        view = pub.calculated_view(self.root)
        self.assertEqual(view["schema_version"], 3)
        self.assertTrue(view["lanes"])
        self.assertTrue(view["frame_display"])

    def test_the_empty_view_declares_them_too(self):
        self.assertIn("lanes", pub.EMPTY_VIEW)
        self.assertIn("frame_display", pub.EMPTY_VIEW)
        self.assertIn("lanes", pub.view_block_keys())
        self.assertIn("frame_display", pub.view_block_keys())

    def test_every_v3_key_the_file_writes_is_accounted_for(self):
        """The `O-E1b` guard applied to v3: a key published with no reader and
        no excuse is unreadable to a host that pins the block."""
        payload = self.publish(3)
        extra = set(payload) - set(pub.published_block_keys())
        self.assertEqual(extra, set())

    def test_the_reserved_keys_are_named_and_deliberately_unwritten(self):
        """`coverage` and `closures` are E-L2c's. They are DECLARED here so the
        next PR adds a writer to a name a reader already knows, and NOT served,
        because an empty tuple for a chain nothing computes reads like an
        answer."""
        self.assertEqual(set(pub.RESERVED_SCHEMA_V3_KEYS), {"coverage", "closures"})
        payload = self.publish(3)
        for key in pub.RESERVED_SCHEMA_V3_KEYS:
            self.assertNotIn(key, payload)
            self.assertNotIn(key, pub.view_block_keys())


class RowTwentyFullRebuildEqualsIncremental(VaultCase):
    """§12 row 20, at v3: *byte-identical projection except `published_at` /
    `timings` / `projection_generation`* (the #664 wording)."""

    def assert_rebuild_is_identical(self, version) -> None:
        first = self.publish(version)
        (self.root / tp.PROJECTION_FILE).unlink()
        (self.root / tp.WORK_ITEMS_FILE).unlink()
        index = ts.active_index_path(self.root)
        if index.exists():
            index.unlink()
        ts.rebuild_active_index(self.root)
        second = self.publish(version)
        self.assertEqual(pub.rebuild_signature(first), pub.rebuild_signature(second))

    def test_at_v2(self):
        self.assert_rebuild_is_identical(2)

    def test_at_v3(self):
        self.assert_rebuild_is_identical(3)

    def test_the_lanes_and_the_frame_block_are_part_of_the_comparison(self):
        """Excluding them would make the row pass by not looking."""
        first = self.publish(3)
        self.assertIn("lanes", pub.rebuild_signature(first))
        self.assertIn("frame_display", pub.rebuild_signature(first))

    def test_the_oracle_agrees_with_the_file_at_both_versions(self):
        for version in (2, 3):
            self.publish(version)
            with flag(version):
                outcome = pub.verify(self.root, roster_snapshot=(),
                                     birth_date=BIRTH_DAY, now=NOW)
            self.assertTrue(outcome["identical"],
                            f"v{version}: {outcome.get('differences')}")

    def test_the_derivation_itself_is_stable_across_two_runs(self):
        """CERT-08's own property, with the v3 keys inside the signature."""
        for version in (2, 3):
            with flag(version):
                self.assertEqual(tt.structural_signature(self.fold()),
                                 tt.structural_signature(self.fold()))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
