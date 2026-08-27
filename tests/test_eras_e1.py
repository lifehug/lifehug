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


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
