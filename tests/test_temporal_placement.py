"""Cut 2a (ADR 0027, decision record §4.3/§7) — placement over the projection.

`timeline.placement_score` computes ADR 0027's level/band/per-year strip over
the legacy `timeline_data()` payload. `temporal_placement.placement_for_
projection` runs the SAME arithmetic — imported, not reimplemented — over a
calculated projection's own nodes. These tests pin three things: the two
inputs agree exactly on a fixture built to carry identical facts (the
oracle), the calculated side is deterministic and rebuild-stable exactly as
every other projection field is, and the empty/birthless case reads `None`
on both sides alike.

Synthetic data only; NEVER references ~/Workspace/dave.
"""

from __future__ import annotations

import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "system"))

import chronology as chrono  # noqa: E402
import temporal_placement as tpl  # noqa: E402
import temporal_publication as pub  # noqa: E402
import temporal_store as ts  # noqa: E402
import timeline as tl  # noqa: E402


def date(best: str, granularity: str = "year", basis: str = "stated") -> dict:
    return chrono.DateRecord(
        best=best, earliest=best, latest=best, granularity=granularity,
        confidence="certain", basis=basis,
    ).to_dict()


def date_range(start: str, end: str, granularity: str = "range",
               basis: str = "stated") -> dict:
    return chrono.DateRecord(
        best=f"{start}/{end}", earliest=start, latest=end, granularity=granularity,
        confidence="certain", basis=basis,
    ).to_dict()


# --------------------------------------------------------------------------
# The oracle fixture: the SAME facts, encoded once for each side.
# --------------------------------------------------------------------------

BIRTH = date("1981-07-11", "day")
MARRIED = date("1998-06", "month")
COLLEGE = date_range("1999", "2001")
MESA = date_range("1990", "1992")


def legacy_oracle_data() -> dict:
    """The legacy `timeline_data()`-shaped payload `timeline.placement_score`
    consumes: one dated moment, one fully unplaced moment, one dated named
    era, one dated residence span, all EXPLICITLY stated — no `date_derived`
    span and no inference anywhere, so the module docstring's one named
    simplification (the stated-basis fallback) never comes into play and the
    two sides can be compared byte-for-byte."""
    return {
        "anchors": {"birth": {"date": BIRTH}},
        "event_lineup": {"college": [{"date": MARRIED, "source_short": "m1"}]},
        "unplaced_events": [{"date": None, "source_short": "u1"}],
        "periods": [{"slug": "college", "date": COLLEGE, "kind": "period",
                     "name": "College"}],
        "bands": [{"ref": "college", "places": [{"slug": "mesa", "date": MESA}]}],
    }


def _node(node_id: str, node_kind: str, event_kind: str, subject_refs: list,
          best_temporal_value: object) -> dict:
    return {
        "node_id": node_id,
        "node_kind": node_kind,
        "event_kind": event_kind,
        "subject_refs": subject_refs,
        "basis": "explicit",
        "best_temporal_value": best_temporal_value,
        "input_claim_refs": ["claim:" + "a" * 24],
        "calculation_rule_version": "oracle:1",
    }


def calculated_oracle_projection() -> dict:
    """The calculated projection carrying EXACTLY `legacy_oracle_data()`'s
    facts, through the field mapping the module docstring names: the same
    birth, the same dated moment as an `event` node, the same unplaced
    moment as a dateless `event` node, the same named era as a `period`
    node, and the same residence span as an `episode` node."""
    return {"nodes": [
        _node("n:birth", "event", "birth", ["self"], BIRTH),
        _node("n:married", "event", "married", ["person/x"], MARRIED),
        _node("n:unplaced", "event", "story", [], None),
        _node("n:college", "period", "named_era", ["self"], COLLEGE),
        _node("n:mesa", "episode", "residence", ["place/mesa"], MESA),
    ]}


class OracleEqualityTests(unittest.TestCase):
    """(a) legacy and calculated agree exactly on identical facts."""

    def test_score_band_and_per_year_band_are_equal(self) -> None:
        legacy = tl.placement_score(legacy_oracle_data())
        calculated = tpl.placement_for_projection(calculated_oracle_projection())
        self.assertIsNotNone(legacy)
        self.assertIsNotNone(calculated)
        self.assertEqual(legacy["score"], calculated["score"])
        self.assertEqual(legacy["band"], calculated["band"])
        self.assertEqual(legacy["score_stated"], calculated["score_stated"])
        self.assertEqual(legacy["per_year_band"], calculated["per_year_band"])
        self.assertEqual(legacy["things"], calculated["things"])
        self.assertEqual(legacy["life_span_years"], calculated["life_span_years"])
        self.assertEqual(legacy["stated_fraction"], calculated["stated_fraction"])
        self.assertEqual(legacy["derived_fraction"], calculated["derived_fraction"])
        self.assertEqual(legacy["inferred_fraction"], calculated["inferred_fraction"])
        self.assertEqual(legacy["score_formula_version"],
                         calculated["score_formula_version"])
        # The one deliberate difference (module docstring): legacy computes a
        # margin over its own anchor graph; the calculated side does not
        # reinvent one (Cut 3 scope).
        self.assertIsNone(calculated["next_gain"])

    def test_determinism_across_two_runs(self) -> None:
        projection = calculated_oracle_projection()
        first = tpl.placement_for_projection(projection)
        second = tpl.placement_for_projection(projection)
        self.assertEqual(first, second)


class InferredAndDerivedBasisTests(unittest.TestCase):
    """The basis mapping (module docstring): explicit / calculated / inferred
    reads the same way legacy's date_derived + node_claim_basis pair does."""

    def test_a_calculated_basis_node_is_derived_but_not_inferred(self) -> None:
        projection = {"nodes": [
            _node("n:birth", "event", "birth", ["self"], BIRTH),
            {**_node("n:job", "episode", "job", ["org/acme"], COLLEGE),
             "basis": "calculated"},
        ]}
        result = tpl.placement_for_projection(projection)
        self.assertIsNotNone(result)
        self.assertEqual(result["derived_fraction"], 1.0)
        self.assertEqual(result["inferred_fraction"], 0.0)
        # score_stated must be strictly lower: a derived thing reads as
        # unplaced on the stated basis (ADR 0027 ruling 3).
        self.assertLess(result["score_stated"], result["score"])

    def test_an_inferred_basis_node_counts_as_derived_and_discounted(self) -> None:
        stated_projection = {"nodes": [
            _node("n:birth", "event", "birth", ["self"], BIRTH),
            {**_node("n:job", "episode", "job", ["org/acme"], COLLEGE)},
        ]}
        inferred_projection = {"nodes": [
            _node("n:birth", "event", "birth", ["self"], BIRTH),
            {**_node("n:job", "episode", "job", ["org/acme"], COLLEGE),
             "basis": "inferred"},
        ]}
        stated = tpl.placement_for_projection(stated_projection)
        inferred = tpl.placement_for_projection(inferred_projection)
        self.assertEqual(inferred["derived_fraction"], 1.0)
        self.assertEqual(inferred["inferred_fraction"], 1.0)
        # Half credit (INFERRED_PLACEMENT_WEIGHT): the inferred score sits
        # strictly between the fully-stated score and the floor.
        self.assertLess(inferred["score"], stated["score"])


class EmptyAndBirthlessTests(unittest.TestCase):
    """(c) empty/undated projection -> None, matching legacy exactly."""

    def test_no_nodes_at_all(self) -> None:
        self.assertIsNone(tpl.placement_for_projection({"nodes": []}))
        self.assertIsNone(tl.placement_score({}))

    def test_not_a_mapping(self) -> None:
        self.assertIsNone(tpl.placement_for_projection(None))
        self.assertIsNone(tpl.placement_for_projection("nope"))

    def test_no_birth_node_no_score(self) -> None:
        projection = {"nodes": [_node("n:married", "event", "married",
                                      ["person/x"], MARRIED)]}
        self.assertIsNone(tpl.placement_for_projection(projection))
        legacy_data = {"event_lineup": {"college": [{"date": MARRIED}]}}
        self.assertIsNone(tl.placement_score(legacy_data))

    def test_birth_with_no_other_scored_thing_is_also_none(self) -> None:
        """Birth itself is excluded from the scored population (the ruler,
        not a thing) — a projection holding only a birth node has nothing
        left to score, exactly as an empty `event_lineup`/`periods`/`bands`
        legacy payload does."""
        projection = {"nodes": [_node("n:birth", "event", "birth", ["self"], BIRTH)]}
        self.assertIsNone(tpl.placement_for_projection(projection))


# --------------------------------------------------------------------------
# (d)/(e) the published file, determinism, and full rebuild — real publish.
# --------------------------------------------------------------------------


def claim(**overrides) -> dict:
    source = overrides.pop("source", "src-oracle")
    payload = {
        "source_kind": "conversation",
        "source_ref": {"source_id": source,
                       "revision": "sha256:" + "0" * 64},
        "evidence": [{"quote": "a sentence from the conversation"}],
        "extractor_version": "listener:1",
        "created_at": "2026-08-26T00:00:00Z",
        "basis": "explicit",
        "confidence": 0.9,
        "status": "active",
    }
    payload.update(overrides)
    return payload


class PublicationTests(unittest.TestCase):
    """The real publisher, a real temp vault — the seam that matters."""

    def setUp(self) -> None:
        self.vault = Path(tempfile.mkdtemp(prefix="lifehug-placement-pub-"))
        self.addCleanup(shutil.rmtree, self.vault, ignore_errors=True)
        (self.vault / "state").mkdir(parents=True, exist_ok=True)
        claims = [
            claim(claim_type="date", subject_mention="birth", event_kind="birth",
                 subject_ref="self", temporal_value="1981-07-11",
                 seed="birth"),
            claim(claim_type="date", subject_mention="Katie", event_kind="married",
                 temporal_value="1998-06", seed="married"),
        ]
        ts.write_receipt(self.vault, {
            "source_ref": {"source_id": "src-oracle", "revision": "sha256:" + "0" * 64},
            "extractor_version": "listener:1",
            "claims": claims,
        })

    def published(self) -> dict:
        payload = pub.read_projection(self.vault)
        assert payload is not None
        return payload

    def test_the_published_projection_carries_placement(self) -> None:
        summary = pub.publish(self.vault, now="2026-09-03T00:00:00Z")
        self.assertEqual(summary["generation"], 1)
        payload = self.published()
        self.assertIn("placement", payload)
        self.assertIsInstance(payload["placement"]["score"], float)
        self.assertEqual(payload["placement"],
                         tpl.placement_for_projection(payload))
        # Generation semantics are untouched by the additive key.
        self.assertEqual(payload["projection_generation"], 1)
        self.assertEqual(pub.published_generation(self.vault), 1)

    def test_placement_is_absent_from_the_queue_slice(self) -> None:
        """The queue is deliberately a narrow slice (module docstring / the
        publisher's own comment) — `placement` rides the projection only, so
        the "queue is one generation behind" contract carries nothing new to
        exclude."""
        pub.publish(self.vault, now="2026-09-03T00:00:00Z")
        queue = pub.read_work_items(self.vault)
        self.assertNotIn("placement", queue)

    def test_two_publications_from_the_same_sources_are_byte_equal_in_placement(self) -> None:
        pub.publish(self.vault, now="2026-09-03T00:00:00Z")
        first = self.published()["placement"]
        pub.projection_path(self.vault).unlink()
        pub.work_items_path(self.vault).unlink()
        ts.active_index_path(self.vault).unlink()
        pub.publish(self.vault, now="2026-09-04T00:00:00Z")
        second = self.published()["placement"]
        self.assertEqual(first, second)

    def test_full_rebuild_reproduces_placement(self) -> None:
        """(e) the rebuild oracle, at the `placement` field specifically."""
        pub.publish(self.vault, now="2026-09-03T00:00:00Z")
        before = pub.rebuild_signature(self.published())
        pub.projection_path(self.vault).unlink()
        pub.work_items_path(self.vault).unlink()
        ts.active_index_path(self.vault).unlink()
        self.assertEqual(pub.published_generation(self.vault), 0)
        pub.publish(self.vault, now="2027-01-01T00:00:00Z")
        after = pub.rebuild_signature(self.published())
        self.assertEqual(after, before)
        self.assertIn("placement", after)

    def test_check_oracle_passes_on_the_placement_carrying_fixture(self) -> None:
        pub.publish(self.vault, now="2026-09-03T00:00:00Z")
        self.assertEqual(pub.main(["--vault-root", str(self.vault), "--check"]), 0)


if __name__ == "__main__":
    unittest.main()
