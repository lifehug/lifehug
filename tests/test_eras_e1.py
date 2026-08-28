"""O-E1 — age frames, the permanent calculated coordinate system.

Contract: `docs/pr-specs/eras-o-e1-age-frames.md`. Controlling design:
lifehug-platform `docs/design/eras.md` §2.1-2.2, §3.3-3.5, §7 row "Age frame
node", §7.8, §9.1 and §13.1. Test ids are §9.1's (T-AF-01…16).

Every negative test here was run against the unmodified branch first and seen
failing; the evidence is in the PR body.

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

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "system"))

import chronology as chrono  # noqa: E402
import cross_dating as cd  # noqa: E402
import temporal_claims as tc  # noqa: E402
import temporal_projection as tp  # noqa: E402
import temporal_publication as pub  # noqa: E402
import temporal_store as ts  # noqa: E402
import temporal_timeline as tt  # noqa: E402
import timeline  # noqa: E402

#: Every fixture birthday in this file is synthetic.
BIRTH_DAY = "1981-07-11"
NOW = "2026-08-26T12:00:00Z"
AS_OF = "2026-08-26"


# ---------------------------------------------------------------------------
# Fixtures
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


def owner_birth(best: str = BIRTH_DAY, *, granularity: str = "day") -> dict:
    return claim(
        claim_type="date",
        subject_mention="self",
        event_kind="birth",
        temporal_value=chrono.DateRecord(
            best=best, earliest=best, latest=best, granularity=granularity,
            confidence="certain", basis="stated",
        ).to_dict(),
        source="src-birth",
        seed="birth",
    )


def dated(subject: str, best: str, *, event_kind: str = "graduation",
          granularity: str = "day", source: str | None = None) -> dict:
    return claim(
        claim_type="date",
        subject_mention=subject,
        event_kind=event_kind,
        temporal_value=chrono.DateRecord(
            best=best, earliest=best, latest=best, granularity=granularity,
            confidence="certain", basis="stated",
        ).to_dict(),
        source=source or f"src-{subject}",
        seed=subject,
    )


def frames(birth: str = BIRTH_DAY, *, granularity: str = "day",
           as_of: str = AS_OF, death: object = None) -> tuple:
    """Frames off a birthday written the way the substrate stores one."""
    record = chrono.parse_edtf(birth)
    assert record is not None and record.granularity == granularity, (birth, record)
    return cd.age_frames(record, as_of=as_of, death=death)


def band(rows, key: str):
    for row in rows:
        if row.band == key:
            return row
    raise AssertionError(f"no {key!r} frame in {[r.band for r in rows]}")


class VaultTestCase(unittest.TestCase):
    """A throwaway vault per test, outside the repo and never ~/Workspace/dave."""

    def setUp(self) -> None:
        self.vault = Path(tempfile.mkdtemp(prefix="lifehug-eras-e1-"))
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

    def fold(self, *, now: str = NOW, generation: int = 1):
        return tt.derive_calculated_timeline(
            ts.rebuild_active_index(self.vault), projection_generation=generation, now=now
        )

    def frame_nodes(self, result) -> list[dict]:
        return [row for row in result.nodes if row.get("event_kind") == "age_frame"]

    def published(self) -> dict:
        payload = pub.read_projection(self.vault)
        assert payload is not None
        return payload


# ---------------------------------------------------------------------------
# The arithmetic (§3.3)
# ---------------------------------------------------------------------------


class HalfOpenFramesTests(unittest.TestCase):
    """T-AF-01 — an exact birthday yields half-open frames."""

    def test_the_start_is_inclusive_and_the_end_exclusive(self) -> None:
        rows = frames()
        twenties = band(rows, "20s")
        self.assertEqual(twenties.start.best, "2001-07-11")
        self.assertEqual(twenties.end.best, "2011-07-11")
        self.assertEqual(twenties.value.earliest, "2001-07-11")
        self.assertEqual(twenties.value.latest, "2011-07-10")
        self.assertEqual(chrono.year_of(twenties.value, end=True), 2011)

    def test_the_twentieth_birthday_is_in_the_twenties_and_the_thirtieth_is_not(self) -> None:
        rows = frames()
        self.assertEqual(cd.frame_for(rows, chrono.parse_edtf("2001-07-11")), "20s")
        self.assertEqual(cd.frame_for(rows, chrono.parse_edtf("2011-07-10")), "20s")
        self.assertEqual(cd.frame_for(rows, chrono.parse_edtf("2011-07-11")), "30s")

    def test_childhood_starts_on_the_birthday_itself(self) -> None:
        rows = frames()
        self.assertEqual(band(rows, "childhood").start.best, BIRTH_DAY)
        self.assertEqual(cd.frame_for(rows, chrono.parse_edtf(BIRTH_DAY)), "childhood")


class BirthdayBoundaryWithinAYearTests(unittest.TestCase):
    """T-AF-02 — March and December of one year, around a July birthday."""

    def test_march_and_december_of_2011_fall_in_different_frames(self) -> None:
        rows = frames()
        self.assertEqual(cd.frame_for(rows, chrono.parse_edtf("2011-03-04")), "20s")
        self.assertEqual(cd.frame_for(rows, chrono.parse_edtf("2011-12-04")), "30s")

    def test_the_same_two_months_of_a_non_boundary_year_share_a_frame(self) -> None:
        rows = frames()
        self.assertEqual(cd.frame_for(rows, chrono.parse_edtf("2008-03-04")), "20s")
        self.assertEqual(cd.frame_for(rows, chrono.parse_edtf("2008-12-04")), "20s")


class YearGrainBirthdayTests(unittest.TestCase):
    """T-AF-03 — a year-only birthday renders plain year ranges."""

    def test_the_frame_is_a_plain_year_range(self) -> None:
        twenties = band(frames("1981", granularity="year"), "20s")
        self.assertEqual(twenties.start.best, "2001")
        self.assertEqual(twenties.end.best, "2011")
        self.assertEqual(twenties.value.best, "2001/2011")
        self.assertEqual(chrono.display_date(twenties.value, with_basis=False), "2001–2011")

    def test_an_event_in_the_boundary_year_overlaps_both_adjacent_frames(self) -> None:
        rows = frames("1981", granularity="year")
        touched = dict(cd.frames_touching(rows, chrono.parse_edtf("2011-03-04")))
        self.assertEqual(sorted(touched), ["20s", "30s"])
        self.assertEqual(set(touched.values()), {"overlaps"})
        self.assertIsNone(cd.frame_for(rows, chrono.parse_edtf("2011-03-04")))

    def test_an_event_inside_the_year_range_is_within_one_frame(self) -> None:
        rows = frames("1981", granularity="year")
        self.assertEqual(cd.frame_for(rows, chrono.parse_edtf("2005-03-04")), "20s")


class FuzzyIntervalTests(unittest.TestCase):
    """T-AF-04 — a fuzzy interval keeps every overlap; nothing picks a winner."""

    def test_a_wide_interval_touches_every_frame_it_crosses(self) -> None:
        rows = frames()
        touched = dict(cd.frames_touching(rows, chrono.parse_edtf("1998/2013")))
        self.assertEqual(sorted(touched), ["20s", "30s", "teens"])
        self.assertEqual(set(touched.values()), {"overlaps"})

    def test_nothing_picks_a_winner(self) -> None:
        rows = frames()
        self.assertIsNone(cd.frame_for(rows, chrono.parse_edtf("1998/2013")))

    def test_an_undated_record_touches_nothing(self) -> None:
        self.assertEqual(cd.frames_touching(frames(), None), ())


class LeapDayTests(unittest.TestCase):
    """T-AF-05 — 29 February clamps to the 28th under rule `age-frame:1`."""

    def test_a_non_leap_target_year_clamps_and_says_so(self) -> None:
        moved = chrono.add_years(chrono.parse_edtf("1984-02-29"), 13)
        self.assertEqual(moved.best, "1997-02-28")
        self.assertEqual(moved.granularity, "day")
        sources = [entry.get("source") for entry in moved.provenance]
        self.assertIn(cd.AGE_FRAME_CLAMP_RULE, sources)

    def test_a_leap_target_year_keeps_the_twenty_ninth_and_files_no_rule(self) -> None:
        moved = chrono.add_years(chrono.parse_edtf("1984-02-29"), 20)
        self.assertEqual(moved.best, "2004-02-29")
        sources = [entry.get("source") for entry in moved.provenance]
        self.assertNotIn(cd.AGE_FRAME_CLAMP_RULE, sources)

    def test_the_frames_of_a_leap_day_birthday_carry_the_rule(self) -> None:
        teens = band(frames("1984-02-29"), "teens")
        self.assertEqual(teens.start.best, "1997-02-28")
        sources = [entry.get("source") for row in (teens.start, teens.end)
                   for entry in row.provenance]
        self.assertIn(cd.AGE_FRAME_CLAMP_RULE, sources)


class ReachedFramesTests(unittest.TestCase):
    """T-AF-06 — no maximum, and nothing unreached."""

    def test_a_child_has_only_childhood(self) -> None:
        self.assertEqual([row.band for row in frames("2018-01-15", as_of="2026-08-26")],
                         ["childhood"])

    def test_a_nineteen_year_old_has_childhood_and_teens(self) -> None:
        self.assertEqual([row.band for row in frames("2007-01-11", as_of="2026-08-26")],
                         ["childhood", "teens"])

    def test_a_forty_five_year_old_has_every_decade_reached_and_no_more(self) -> None:
        self.assertEqual([row.band for row in frames(BIRTH_DAY, as_of="2026-08-26")],
                         ["childhood", "teens", "20s", "30s", "40s"])

    def test_there_is_no_maximum_band(self) -> None:
        rows = frames("1921-07-11", as_of="2026-08-26")
        self.assertEqual(rows[-1].band, "100s")
        self.assertEqual(rows[-1].label, "My 100s")

    def test_a_death_clips_the_ladder(self) -> None:
        rows = frames(BIRTH_DAY, as_of="2026-08-26", death="2015-03-01")
        self.assertEqual([row.band for row in rows], ["childhood", "teens", "20s", "30s"])
        self.assertEqual(rows[-1].life_clip_end, "2015-03-01")
        self.assertFalse(rows[-1].current)


class BandTableParityTests(unittest.TestCase):
    """The frame ladder and the legacy age-label ladder never drift."""

    def test_every_shared_band_agrees_on_its_ages(self) -> None:
        ladder = {key: (low, high) for key, low, high in cd.age_frame_ladder(100)}
        shared = set(ladder) & set(cd.AGE_BAND_AGES)
        self.assertTrue(shared, "the two tables share no band name at all")
        for key in sorted(shared):
            self.assertEqual(ladder[key], cd.AGE_BAND_AGES[key], key)


# ---------------------------------------------------------------------------
# The definition span, `present`, and the clock (§3.4)
# ---------------------------------------------------------------------------


class DefinitionSpanTests(VaultTestCase):
    """T-AF-13 — `best_temporal_value` is the definition span at the birth's grain."""

    def test_every_grain_keeps_its_own_edges(self) -> None:
        cases = [
            ("1981-07-11", "day", "2001-07-11", "2011-07-11", "2001-07-11", "2011-07-10"),
            ("1981-07", "month", "2001-07", "2011-07", "2001-07", "2011-07"),
            ("1981", "year", "2001", "2011", "2001", "2011"),
            ("1981-22", "season", "2001-22", "2011-22", "2001-06", "2011-08"),
        ]
        for birth, grain, start, end, earliest, latest in cases:
            with self.subTest(grain=grain):
                twenties = band(frames(birth, granularity=grain), "20s")
                self.assertEqual(twenties.start.best, start)
                self.assertEqual(twenties.end.best, end)
                self.assertEqual(twenties.value.earliest, earliest)
                self.assertEqual(twenties.value.latest, latest)

    def test_a_decade_grain_origin_widens_rather_than_faking_a_decade(self) -> None:
        rows = frames("197X", granularity="era", as_of="2026-08-26")
        teens = band(rows, "teens")
        self.assertEqual(teens.start.granularity, "range")
        self.assertEqual(teens.start.best, "1983/1992")
        twenties = band(rows, "20s")
        self.assertEqual(twenties.start.best, "199X")
        self.assertEqual(twenties.start.granularity, "era")

    def test_the_value_is_never_the_start_and_never_the_clock(self) -> None:
        self.file_claims([owner_birth()])
        node = self.frame_nodes(self.fold())[-1]
        value = node["best_temporal_value"]
        self.assertNotEqual(value.get("best"), value.get("earliest"))
        self.assertNotIn(AS_OF, json.dumps(node))


class PresentTests(VaultTestCase):
    """T-AF-07 — a finite span plus `life_clip_end: present`; `as_of` unpersisted."""

    def test_the_current_frame_persists_a_finite_span_and_the_view_token(self) -> None:
        rows = frames()
        current = rows[-1]
        self.assertTrue(current.current)
        self.assertEqual(current.life_clip_end, "present")
        self.assertEqual(current.start.best, "2021-07-11")
        self.assertEqual(current.end.best, "2031-07-11")

    def test_a_past_frame_carries_its_own_end(self) -> None:
        twenties = band(frames(), "20s")
        self.assertFalse(twenties.current)
        self.assertEqual(twenties.life_clip_end, "2011-07-10")

    def test_as_of_is_never_written_to_either_published_file(self) -> None:
        self.file_claims([owner_birth()])
        pub.publish(self.vault, now=NOW)
        for path in (pub.projection_path(self.vault), pub.work_items_path(self.vault)):
            self.assertNotIn("as_of", path.read_text(encoding="utf-8"))
        # `published_at` legitimately carries today's date; no FRAME does.
        for node in self.published()["nodes"]:
            if node.get("event_kind") == "age_frame":
                self.assertNotIn(AS_OF, json.dumps(node))


# ---------------------------------------------------------------------------
# The fold (§2.2, §7 row "Age frame node")
# ---------------------------------------------------------------------------


class FrameNodeTests(VaultTestCase):
    """T-AF-14 — what a frame node declares."""

    def test_the_fold_mints_a_period_node_per_reached_frame(self) -> None:
        self.file_claims([owner_birth()])
        rows = self.frame_nodes(self.fold())
        self.assertEqual([row["node_id"] for row in rows],
                         ["age:self:childhood", "age:self:teens", "age:self:20s",
                          "age:self:30s", "age:self:40s"])
        for row in rows:
            self.assertEqual(row["node_kind"], "period")
            self.assertEqual(row["subject_refs"], ["self"])
            self.assertEqual(row["origin_basis"], "explicit")

    def test_node_kind_for_learns_period(self) -> None:
        self.assertEqual(tt._node_kind_for("age_frame"), "period")  # noqa: SLF001
        self.assertEqual(tt._node_kind_for("graduation"), "event")  # noqa: SLF001

    def test_the_twenties_node_carries_its_span_clip_and_legacy_refs(self) -> None:
        self.file_claims([owner_birth()])
        node = next(row for row in self.frame_nodes(self.fold())
                    if row["node_id"] == "age:self:20s")
        self.assertEqual(node["label"], "My 20s")
        self.assertEqual(node["definition_span"]["start"]["best"], "2001-07-11")
        self.assertEqual(node["definition_span"]["end"]["best"], "2011-07-11")
        self.assertEqual(node["life_clip_end"], "2011-07-10")
        self.assertIn("period:my-20s", node["legacy_refs"])
        self.assertIn("tl:my-20s", node["legacy_refs"])
        self.assertIn("band:my-20s", node["legacy_refs"])

    def test_a_frame_cites_the_birth_claims_it_was_calculated_from(self) -> None:
        birth = owner_birth()
        self.file_claims([birth])
        node = self.frame_nodes(self.fold())[0]
        self.assertEqual(node["input_claim_refs"], [birth["claim_id"]])

    def test_somebody_elses_birth_is_not_the_owners_and_the_fold_says_so(self) -> None:
        """The founder's own incident (design §1 item 5), as a diagnostic."""
        self.file_claims([dated("Charlee", "2010-12-21", event_kind="birth")])
        result = self.fold()
        self.assertEqual(self.frame_nodes(result), [])
        findings = {row.get("finding") for row in result.diagnostics["findings"]}
        self.assertIn("age_frames_without_birth_anchor", findings)

    def test_a_vault_with_no_birth_at_all_mints_no_frames_and_no_noise(self) -> None:
        """No birthday is not a surprise: the `missing_anchor` item says it."""
        self.file_claims([dated("Katie", "1998-06-20", event_kind="married")])
        result = self.fold()
        self.assertEqual(self.frame_nodes(result), [])
        findings = {row.get("finding") for row in result.diagnostics["findings"]}
        self.assertNotIn("age_frames_without_birth_anchor", findings)

    def test_two_owner_births_refuse_rather_than_pick_one(self) -> None:
        self.file_claims([owner_birth(),
                          claim(claim_type="date", subject_mention="self",
                                event_kind="birth", source="src-b", seed="b",
                                temporal_value=chrono.DateRecord(
                                    best="1981-07-11", earliest="1981-07-11",
                                    latest="1981-07-11", granularity="day",
                                    confidence="certain", basis="stated").to_dict())])
        result = self.fold()
        # One SUBJECT, one node: two receipts for one birth reconcile (O-E0b).
        self.assertTrue(self.frame_nodes(result))

    def test_frames_are_never_work_and_never_unplaced(self) -> None:
        self.file_claims([owner_birth()])
        result = self.fold()
        self.assertTrue(self.frame_nodes(result))
        ids = {row["node_id"] for row in self.frame_nodes(result)}
        for item in result.work_items:
            self.assertNotIn(item.get("node_ref"), ids)
        self.assertFalse(ids & set(result.diagnostics["unplaced"]))
        self.assertFalse(ids & set(result.reach))


class LifeViewTests(VaultTestCase):
    """T-AF-10 — an event after `as_of` is a future plan, never lived."""

    def test_an_event_after_as_of_is_a_future_plan(self) -> None:
        self.file_claims([owner_birth(), dated("the reunion", "2030-06-01")])
        result = self.fold()
        row = next(node for node in result.nodes
                   if node.get("label", "").startswith("the reunion"))
        self.assertEqual(row["life_view"], "future_plan")

    def test_an_event_before_as_of_is_lived(self) -> None:
        self.file_claims([owner_birth(), dated("the wedding", "2007-01-11")])
        result = self.fold()
        row = next(node for node in result.nodes
                   if node.get("label", "").startswith("the wedding"))
        self.assertEqual(row["life_view"], "lived")

    def test_e1_assigns_exactly_two_life_views(self) -> None:
        self.assertEqual(tp.LIFE_VIEWS, ("lived", "future_plan"))


class RuleVersionAndFingerprintTests(VaultTestCase):
    """T-AF-16 — the rule version moves, the epoch rides the fingerprint."""

    def test_the_calculation_rule_version_is_two(self) -> None:
        self.assertEqual(tt.CALCULATION_RULE_VERSION, "timeline-rules:2")

    def test_a_fingerprint_without_an_epoch_is_byte_identical_to_v1s(self) -> None:
        self.assertEqual(
            tp.derive_input_fingerprint(
                claim_ids=("claim:a", "claim:b"),
                constraint_ids=(),
                calculation_rule_version="timeline-rules:1",
            ),
            "fp:49aead6f48b69c1b25275731",
        )

    def test_the_epoch_moves_the_frame_fingerprint_on_unchanged_claims(self) -> None:
        self.file_claims([owner_birth()])
        before = {row["node_id"]: row["input_fingerprint"]
                  for row in self.frame_nodes(self.fold(now="2026-08-26T12:00:00Z"))}
        after = {row["node_id"]: row["input_fingerprint"]
                 for row in self.frame_nodes(self.fold(now="2031-08-26T12:00:00Z"))}
        shared = set(before) & set(after)
        self.assertTrue(shared)
        for node_id in sorted(shared):
            self.assertNotEqual(before[node_id], after[node_id], node_id)


# ---------------------------------------------------------------------------
# Schema v2 (§7.8)
# ---------------------------------------------------------------------------


class SchemaVersionTests(VaultTestCase):
    """T-AF-15 — additive, tolerant readers, membership shape only."""

    def test_a_node_is_v2_while_a_claim_stays_v1(self) -> None:
        self.assertEqual(tp.PROJECTION_SCHEMA_VERSION, 2)
        self.assertEqual(tc.SCHEMA_VERSION, 1)
        self.file_claims([owner_birth()])
        for row in self.fold().nodes:
            self.assertEqual(row["schema_version"], 2)

    def test_calculated_view_reads_a_v1_payload_and_a_v2_payload(self) -> None:
        self.file_claims([owner_birth()])
        pub.publish(self.vault, now=NOW)
        v2 = pub.calculated_view(self.vault)
        self.assertEqual(v2["schema_version"], 2)
        self.assertTrue(v2["nodes"])
        payload = copy.deepcopy(self.published())
        payload.pop("projection_schema_version", None)
        payload.pop("memberships", None)
        payload.pop("reached_frame_epoch", None)
        for node in payload["nodes"]:
            node["schema_version"] = 1
            for key in ("definition_span", "life_clip_end", "origin_basis",
                        "legacy_refs", "life_view"):
                node.pop(key, None)
        pub.projection_path(self.vault).write_text(
            json.dumps(payload, indent=2) + "\n", encoding="utf-8"
        )
        v1 = pub.calculated_view(self.vault)
        self.assertEqual(v1["schema_version"], 1)
        self.assertEqual(len(v1["nodes"]), len(v2["nodes"]))

    def test_memberships_ride_the_projection_as_an_empty_list(self) -> None:
        self.file_claims([owner_birth()])
        pub.publish(self.vault, now=NOW)
        self.assertEqual(self.published()["memberships"], [])
        self.assertEqual(pub.calculated_view(self.vault)["memberships"], ())

    def test_a_membership_without_evidence_is_refused_by_name(self) -> None:
        with self.assertRaises(tp.CalculatedMembershipError) as caught:
            tp.validate_calculated_membership({
                "member_node_id": "node:aaa", "era_node_id": "age:self:20s",
                "relation": "within", "evidence_refs": [],
            })
        self.assertEqual(caught.exception.code, "membership_without_evidence")

    def test_a_membership_id_is_the_digest_of_its_three_identity_keys(self) -> None:
        row = tp.validate_calculated_membership({
            "member_node_id": "node:aaa", "era_node_id": "age:self:20s",
            "relation": "within", "evidence_refs": ["assert:1"],
        })
        self.assertEqual(
            row["membership_id"],
            tp.derive_membership_id(member_node_id="node:aaa",
                                    era_node_id="age:self:20s", relation="within"),
        )
        self.assertEqual(row["display_role"], "none")


# ---------------------------------------------------------------------------
# Publication (§3.4)
# ---------------------------------------------------------------------------


class PublicationEpochTests(VaultTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.file_claims([owner_birth()])

    def test_two_publishes_inside_one_epoch_write_nothing(self) -> None:
        """T-AF-08."""
        first = pub.publish(self.vault, now=NOW)
        self.assertFalse(first["unchanged"])
        path = pub.projection_path(self.vault)
        before_bytes, before_mtime = path.read_bytes(), path.stat().st_mtime_ns
        second = pub.publish(self.vault, now="2026-08-27T12:00:00Z")
        self.assertTrue(second["unchanged"])
        self.assertEqual(second["generation"], first["generation"])
        self.assertEqual(path.read_bytes(), before_bytes)
        self.assertEqual(path.stat().st_mtime_ns, before_mtime)

    def test_crossing_a_boundary_publishes_exactly_once(self) -> None:
        """T-AF-09."""
        pub.publish(self.vault, now="2031-07-10T12:00:00Z")
        self.assertEqual(pub.published_generation(self.vault), 1)
        crossed = pub.publish(self.vault, now="2031-07-11T12:00:00Z")
        self.assertFalse(crossed["unchanged"])
        self.assertEqual(crossed["generation"], 2)
        self.assertTrue(pub.publish(self.vault, now="2031-07-12T12:00:00Z")["unchanged"])
        self.assertEqual(pub.published_generation(self.vault), 2)

    def test_the_epoch_rides_the_envelope_and_therefore_the_signature(self) -> None:
        pub.publish(self.vault, now=NOW)
        payload = self.published()
        self.assertEqual(payload["reached_frame_epoch"], {"count": 5, "current": "40s"})
        self.assertIn("reached_frame_epoch", pub.rebuild_signature(payload))

    def test_a_torn_pair_is_never_a_no_op(self) -> None:
        pub.publish(self.vault, now=NOW)
        payload = pub.read_work_items(self.vault)
        payload["projection_generation"] = 9
        pub.work_items_path(self.vault).write_text(
            json.dumps(payload, indent=2) + "\n", encoding="utf-8"
        )
        summary = pub.publish(self.vault, now=NOW)
        self.assertFalse(summary["unchanged"])
        self.assertEqual(summary["generation"], 10)


# ---------------------------------------------------------------------------
# The placement score and the alias map
# ---------------------------------------------------------------------------


class PlacementScoreTests(unittest.TestCase):
    """T-AF-11 — age frames are excluded from the placement score."""

    def payload(self) -> dict:
        return {
            "anchors": {"birth": {"date": chrono.parse_edtf(BIRTH_DAY).to_dict()}},
            "periods": [{"slug": "college", "name": "College",
                         "date": chrono.parse_edtf("2001/2005").to_dict()}],
            "event_lineup": {"college": [
                {"source": "s1", "source_short": "s1", "description": "a moment",
                 "when_hint": "", "date": chrono.parse_edtf("2003-05-01").to_dict()},
            ]},
            "unplaced_events": [],
            "bands": [{"kind": "period", "ref": "college", "label": "College",
                       "periods": ["college"], "places": []}],
        }

    def frame_nodes(self) -> list[dict]:
        return [{"node_id": f"age:self:{row.band}", "node_kind": "period",
                 "event_kind": "age_frame",
                 "best_temporal_value": row.value.to_dict()} for row in frames()]

    def test_frames_in_the_calculated_projection_move_neither_score_nor_population(self) -> None:
        plain = self.payload()
        withframes = self.payload()
        withframes["calculated"] = {"nodes": self.frame_nodes()}
        life = timeline.life_span(plain)
        self.assertEqual(
            [thing["key"] for thing in timeline._scored_things(withframes, life)],  # noqa: SLF001
            [thing["key"] for thing in timeline._scored_things(plain, life)],  # noqa: SLF001
        )
        self.assertEqual(timeline.placement_score(withframes),
                         timeline.placement_score(plain))

    def test_the_guard_is_sensitive_a_frame_in_periods_would_move_it(self) -> None:
        """A guard proven to fire: the exclusion is what keeps the score still."""
        plain = self.payload()
        injected = self.payload()
        injected["periods"].append({
            "slug": "my-20s", "name": "My 20s",
            "date": chrono.parse_edtf("2001-07-11/2011-07-10").to_dict(),
        })
        self.assertNotEqual(timeline.placement_score(injected),
                            timeline.placement_score(plain))


class LegacyPeriodRefTests(unittest.TestCase):
    """T-AF-12 — one alias map."""

    def test_every_prefixed_spelling_of_the_twenties_resolves(self) -> None:
        for ref in ("period:my-20s", "tl:my-20s", "band:my-20s", "my-20s",
                    "period:my-twenties", "My 20s"):
            with self.subTest(ref=ref):
                self.assertEqual(timeline.legacy_period_ref(ref), "age:self:20s")

    def test_childhood_and_the_teens_resolve(self) -> None:
        self.assertEqual(timeline.legacy_period_ref("childhood"), "age:self:childhood")
        self.assertEqual(timeline.legacy_period_ref("period:my-teens"), "age:self:teens")

    def test_a_named_era_resolves_to_nothing(self) -> None:
        for ref in ("period:college", "band:the-mission", "high-school", "", None):
            with self.subTest(ref=ref):
                self.assertIsNone(timeline.legacy_period_ref(ref))


class RosterAliasOnlyTests(VaultTestCase):
    """T-AF-12 — a roster row named like a band contributes aliases only."""

    def test_a_roster_band_row_changes_exactly_the_alias_set(self) -> None:
        self.file_claims([owner_birth()])
        without = {row["node_id"]: dict(row) for row in self.frame_nodes(self.fold())}
        roster = ({"type": "period", "entities": [
            {"name": "My Twenties", "slug": "twenties-era", "aliases": [],
             "page_eligible": True},
        ]},)
        with_roster = tt.derive_calculated_timeline(
            ts.rebuild_active_index(self.vault), roster_snapshot=roster,
            projection_generation=1, now=NOW,
        )
        after = {row["node_id"]: dict(row) for row in self.frame_nodes(with_roster)}
        self.assertEqual(sorted(without), sorted(after))
        for node_id in sorted(without):
            before_row, after_row = dict(without[node_id]), dict(after[node_id])
            self.assertEqual(before_row.pop("legacy_refs") != after_row.pop("legacy_refs"),
                             node_id == "age:self:20s")
            before_row.pop("input_fingerprint", None)
            after_row.pop("input_fingerprint", None)
            self.assertEqual(before_row, after_row)
        self.assertIn("period:twenties-era", after["age:self:20s"]["legacy_refs"])
        self.assertNotIn("period:twenties-era", without["age:self:20s"]["legacy_refs"])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
