"""O-E1b — the view block serves what the file publishes.

Contract: `docs/pr-specs/eras-o-e1b-view-block.md`. Findings against `O-E1`
(merged, v238) found by lifehug-platform#691 executing the tolerant readers
against a real reader for the first time; recorded in that PR's body.
Controlling design: lifehug-platform `docs/design/eras.md` §2.2, §3.3-3.5,
§5.2, §7 row "Age frame node", §7.8.

Every negative test here was run against `origin/main` (before the
`ChapterOverlay`/guard functions in this branch existed) first and seen
failing — `AttributeError`, since the functions did not exist yet.

Synthetic data only; NEVER references ~/Workspace/dave.
"""

from __future__ import annotations

import hashlib
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "system"))

import chronology as chrono  # noqa: E402
import cross_dating as cd  # noqa: E402
import temporal_claims as tc  # noqa: E402
import temporal_projection as tp  # noqa: E402
import temporal_publication as pub  # noqa: E402
import temporal_store as ts  # noqa: E402
import temporal_timeline as tt  # noqa: E402

#: Every fixture birthday in this file is synthetic.
BIRTH_DAY = "1981-07-11"
NOW = "2026-08-26T12:00:00Z"


# ---------------------------------------------------------------------------
# Fixtures (mirrors tests/test_eras_e1.py's own helpers)
# ---------------------------------------------------------------------------


def revision(seed: str) -> str:
    return "sha256:" + hashlib.sha256(seed.encode("utf-8")).hexdigest()


def claim(**overrides) -> dict:
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


def owner_birth(best: str = BIRTH_DAY) -> dict:
    return claim(
        claim_type="date",
        subject_mention="self",
        event_kind="birth",
        temporal_value=chrono.DateRecord(
            best=best, earliest=best, latest=best, granularity="day",
            confidence="certain", basis="stated",
        ).to_dict(),
        source="src-birth",
        seed="birth",
    )


class VaultTestCase(unittest.TestCase):
    """A throwaway vault per test, outside the repo and never ~/Workspace/dave."""

    def setUp(self) -> None:
        # dir= pinned inside the repo's own tree (never the bare default
        # tempdir) — a symlinked /var breaks the vault-root guard on macOS.
        self.vault = Path(tempfile.mkdtemp(prefix="lifehug-eras-e1b-", dir=str(ROOT)))
        self.addCleanup(shutil.rmtree, self.vault, ignore_errors=True)
        (self.vault / "state").mkdir(parents=True, exist_ok=True)

    def file_claims(self, claims) -> None:
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

    def publish(self, *, now: str = NOW) -> dict:
        return pub.publish(self.vault, now=now)

    def published(self) -> dict:
        payload = pub.read_projection(self.vault)
        assert payload is not None
        return payload

    def current_frame(self, view: dict) -> dict:
        return next(
            node for node in view["nodes"] if node.get("event_kind") == "age_frame"
        )


# ---------------------------------------------------------------------------
# Finding 1 — memberships (+ reached_frame_epoch, projection_schema_version)
# must be in calculated_view()'s served/declared key set.
# ---------------------------------------------------------------------------


class ViewBlockKeySetTests(VaultTestCase):
    """`memberships` etc. must be visible in the SERVED key set, not only the
    published file — `test_the_envelope_keys_are_the_pinned_views_own` on the
    platform side pins the view's own key set, so a field absent from it is
    unreadable no matter what the file contains (lifehug-platform#691 finding 1).
    """

    def test_memberships_reached_frame_epoch_and_schema_version_are_served(self) -> None:
        self.file_claims([owner_birth()])
        self.publish()
        view = pub.calculated_view(self.vault)
        self.assertIn("memberships", view)
        self.assertIn("reached_frame_epoch", view)
        # projection_schema_version is served RENAMED, per PUBLISHED_KEYS_NOT_SERVED.
        self.assertIn("schema_version", view)
        self.assertEqual(view["schema_version"], self.published()["projection_schema_version"])

    def test_every_key_a_real_publish_writes_is_accounted_for(self) -> None:
        self.file_claims([owner_birth()])
        self.publish()
        published_keys = set(self.published().keys())
        accounted = set(pub.published_block_keys())
        extra = published_keys - accounted
        self.assertEqual(
            extra, set(),
            f"published a top-level key with no reader and no excuse: {extra}",
        )

    def test_view_block_keys_is_exactly_what_calculated_view_returns(self) -> None:
        self.file_claims([owner_birth()])
        self.publish()
        view = pub.calculated_view(self.vault)
        self.assertEqual(set(view.keys()), set(pub.view_block_keys()))

    def test_an_unnamed_key_is_not_silently_accepted(self) -> None:
        """The guard actually fires: inject a key no reader and no excuse
        covers, and prove `published_block_keys()` does NOT paper over it."""
        self.file_claims([owner_birth()])
        self.publish()
        payload = self.published()
        payload["a_brand_new_field_nobody_declared"] = "surprise"
        extra = set(payload.keys()) - set(pub.published_block_keys())
        self.assertEqual(extra, {"a_brand_new_field_nobody_declared"})

    def test_view_only_keys_are_served_but_never_in_the_published_file(self) -> None:
        self.file_claims([owner_birth()])
        self.publish()
        for key in pub.VIEW_ONLY_KEYS:
            self.assertNotIn(key, self.published())
            self.assertIn(key, pub.calculated_view(self.vault))

    def test_the_one_deliberate_name_overload_is_schema_version(self) -> None:
        """`schema_version` is the only name shared by both tables, and on
        purpose: the FILE's `schema_version` is the claim contract's version
        (excused, not served under that name — see `PUBLISHED_KEYS_NOT_SERVED`),
        while the VIEW's `schema_version` is a different number, the
        projection's, served RENAMED from `projection_schema_version`. Both
        facts are true about the same string; this pins that it stays the
        ONLY such overload rather than growing a second one unnoticed.
        """
        self.assertEqual(
            set(pub.view_block_keys()) & set(pub.PUBLISHED_KEYS_NOT_SERVED),
            {"schema_version"},
        )


# ---------------------------------------------------------------------------
# Finding 3 — chapter_overlays (design §5.2)
# ---------------------------------------------------------------------------


class ChapterOverlayTests(unittest.TestCase):
    """The schema lands here (empty); E3 files the rows."""

    def test_an_overlay_that_isnt_a_mapping_is_refused(self) -> None:
        with self.assertRaises(tp.ChapterOverlayError) as caught:
            tp.validate_chapter_overlay("not a mapping")
        self.assertEqual(caught.exception.code, "overlay_not_a_mapping")

    def test_an_overlay_with_no_chapter_is_refused(self) -> None:
        with self.assertRaises(tp.ChapterOverlayError) as caught:
            tp.validate_chapter_overlay({"frame_node_ids": ["age:self:20s"]})
        self.assertEqual(caught.exception.code, "overlay_needs_chapter")

    def test_an_overlay_covering_no_frame_is_refused(self) -> None:
        """Mirrors `membership_without_evidence` — a stripe across nothing is
        not a rendering instruction."""
        with self.assertRaises(tp.ChapterOverlayError) as caught:
            tp.validate_chapter_overlay({"chapter_node_id": "period:college"})
        self.assertEqual(caught.exception.code, "overlay_without_frames")

    def test_a_valid_overlay_normalizes_and_mints_an_id(self) -> None:
        row = tp.validate_chapter_overlay({
            "chapter_node_id": "period:college",
            "frame_node_ids": ["age:self:teens", "age:self:20s"],
        })
        self.assertTrue(row["overlay_id"].startswith("overlay:"))
        self.assertEqual(row["chapter_node_id"], "period:college")
        self.assertEqual(row["frame_node_ids"], ["age:self:teens", "age:self:20s"])
        self.assertEqual(row["schema_version"], tp.PROJECTION_SCHEMA_VERSION)

    def test_the_id_is_keyed_on_the_chapter_alone(self) -> None:
        """A chapter that grows to touch a fourth frame is the SAME overlay
        with a longer `frame_node_ids` — not a new identity."""
        narrow = tp.validate_chapter_overlay({
            "chapter_node_id": "period:college",
            "frame_node_ids": ["age:self:20s"],
        })
        wide = tp.validate_chapter_overlay({
            "chapter_node_id": "period:college",
            "frame_node_ids": ["age:self:teens", "age:self:20s", "age:self:30s"],
        })
        self.assertEqual(narrow["overlay_id"], wide["overlay_id"])

    def test_two_different_chapters_never_collide(self) -> None:
        college = tp.validate_chapter_overlay({
            "chapter_node_id": "period:college", "frame_node_ids": ["age:self:20s"],
        })
        first_job = tp.validate_chapter_overlay({
            "chapter_node_id": "period:first-job", "frame_node_ids": ["age:self:20s"],
        })
        self.assertNotEqual(college["overlay_id"], first_job["overlay_id"])

    def test_chapter_overlay_from_dict_is_tolerant(self) -> None:
        self.assertIsNone(tp.chapter_overlay_from_dict("garbage"))
        self.assertIsNone(tp.chapter_overlay_from_dict({"chapter_node_id": "x"}))
        overlay = tp.chapter_overlay_from_dict({
            "chapter_node_id": "period:college", "frame_node_ids": ["age:self:20s"],
        })
        self.assertIsInstance(overlay, tp.ChapterOverlay)
        self.assertEqual(overlay.chapter_node_id, "period:college")

    def test_chapter_overlay_fields_matches_to_dict_keys(self) -> None:
        overlay = tp.ChapterOverlay(
            overlay_id="overlay:abc", chapter_node_id="period:college",
            frame_node_ids=("age:self:20s",),
        )
        self.assertEqual(set(overlay.to_dict().keys()) - set(tp.CHAPTER_OVERLAY_FIELDS), set())
        self.assertEqual(set(tp.CHAPTER_OVERLAY_FIELDS) - set(overlay.to_dict().keys()),
                         {"label", "span"})  # optional, absent when unset


class ChapterOverlaysRideTheProjectionEmptyTests(VaultTestCase):
    """Same phase discipline as `memberships` in E1: the KEY lands, empty."""

    def test_chapter_overlays_defaults_to_empty_on_the_dataclass(self) -> None:
        self.file_claims([owner_birth()])
        result = tt.derive_calculated_timeline(
            ts.rebuild_active_index(self.vault), projection_generation=1, now=NOW
        )
        self.assertEqual(result.chapter_overlays, ())
        self.assertEqual(result.to_dict()["chapter_overlays"], [])

    def test_chapter_overlays_rides_a_real_publish_as_an_empty_list(self) -> None:
        self.file_claims([owner_birth()])
        self.publish()
        self.assertEqual(self.published()["chapter_overlays"], [])
        self.assertEqual(pub.calculated_view(self.vault)["chapter_overlays"], ())

    def test_publishing_is_still_a_semantic_no_op_with_the_new_key_present(self) -> None:
        """The E1 no-op mechanism (rebuild_signature) must not be broken by a
        key that is always empty right now — an ever-empty field cannot make
        two identical publications look different."""
        self.file_claims([owner_birth()])
        first = self.publish()
        self.assertFalse(first["unchanged"])
        second = self.publish(now=NOW)
        self.assertTrue(second["unchanged"])
        self.assertEqual(second["generation"], first["generation"])


# ---------------------------------------------------------------------------
# Finding 2 confirmation — the frame label carries the whole display string
# (shipped in this branch's first commit without its own test; confirmed here)
# ---------------------------------------------------------------------------


class FrameLabelConfirmationTests(unittest.TestCase):
    def test_a_named_band_states_its_ages(self) -> None:
        self.assertEqual(cd.age_frame_label("childhood"), "Childhood · ages 0–12")
        self.assertEqual(cd.age_frame_label("teens"), "Teen years · ages 13–19")

    def test_a_decade_carries_no_suffix(self) -> None:
        self.assertEqual(cd.age_frame_label("20s"), "My 20s")
        self.assertEqual(cd.age_frame_label("100s"), "My 100s")

    def test_a_bare_name_and_a_full_label_are_now_different_functions(self) -> None:
        self.assertEqual(cd.age_frame_name("childhood"), "Childhood")
        self.assertNotEqual(cd.age_frame_name("childhood"), cd.age_frame_label("childhood"))

    def test_the_stated_ages_are_derived_from_the_one_ladder(self) -> None:
        # inclusive pair, not typed a second time
        self.assertEqual(cd.age_frame_ages("childhood"), (0, 12))
        self.assertEqual(cd.age_frame_ages("teens"), (13, 19))


# ---------------------------------------------------------------------------
# Finding 4 confirmation — life_view carrier + the current frame's
# definition_span.start, through publish() -> calculated_view() (not the bare
# fold the O-E1 tests already exercise).
# ---------------------------------------------------------------------------


class LifeViewAndDefinitionSpanConfirmationTests(VaultTestCase):
    def test_the_served_current_frame_carries_life_view_and_a_start_edge(self) -> None:
        self.file_claims([owner_birth()])
        self.publish()
        view = pub.calculated_view(self.vault)
        frames = [n for n in view["nodes"] if n.get("event_kind") == "age_frame"]
        current = next(n for n in frames if n.get("life_clip_end") == "present")
        self.assertIn(current["life_view"], tp.LIFE_VIEWS)
        self.assertEqual(current["life_view"], "lived")
        self.assertTrue(current["definition_span"]["start"]["best"])
        # a host can render "<start>–present" from these two fields alone.
        rendered = f"{current['definition_span']['start']['best']}–present"
        self.assertTrue(rendered.endswith("present"))

    def test_life_view_is_a_closed_vocabulary(self) -> None:
        # eras O-E2 extends E1's two-value tuple with `contradictory` /
        # `unresolved` (§2.6) rather than replacing it — the vocabulary is
        # still closed, just no longer only these two.
        self.assertEqual(tp.LIFE_VIEWS[:2], ("lived", "future_plan"))
        self.assertEqual(set(tp.LIFE_VIEWS),
                         {"lived", "future_plan", "contradictory", "unresolved"})
        with self.assertRaises(tp.TimelineNodeError) as caught:
            tp.validate_calculated_timeline_node({
                "node_id": "node:aaa", "node_kind": "event", "label": "x",
                "input_claim_refs": ["claim:1"],
                "calculation_rule_version": "timeline-rules:2",
                "life_view": "someday-maybe",
            })
        self.assertEqual(caught.exception.code, "unknown_life_view")


if __name__ == "__main__":
    unittest.main()
