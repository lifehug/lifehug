"""v254 / issue #278 — date before you place, and never date an era by what
landed in it.

Found by the platform's E7b certification against the founder's real vault
(lifehug-platform#720, CERT-02 and CERT-03). Two faces of one defect:

1. `timeline_data` called `place_events` BEFORE `cross_dating.cross_date`, and
   `heuristic_slot`'s rung 1 gates on `event["date"] is not None`. Twelve of
   the founder's thirteen dated moments take their date from the cross-dating
   pass, so at placement time they were undated and fell to rung 2/3 era
   language: "Married Katie" (2007), "Moved to Seattle" (2012) and Etherfuse
   (2020) all landed in `high-school`. `my-20s` and `my-30s` held ZERO moments.
2. `date_bands` → `band_span` → `moment_envelope` then dated `high-school`
   `1997/2021` from those very moments — the thing ADR 0030 decision 4 and the
   Eras design §4.2 forbid outright: *"The observed envelope of members is
   coverage, never a bound."*

The fixture below is founder-SHAPED and wholly synthetic: the real birthday's
shape (a day-grain 1981 birth), a legacy era whose page carries era-text
keywords, and moments that are dated ONLY by the cross-dating pass. Synthetic
data only; NEVER references ~/Workspace/dave.
"""

from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SYSTEM = ROOT / "system"
sys.path.insert(0, str(SYSTEM))

import chronology as chrono  # noqa: E402
import cross_dating as xd  # noqa: E402


def load(name):
    spec = importlib.util.spec_from_file_location(name, SYSTEM / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    orig = sys.modules.get(name)
    sys.modules[name] = mod
    try:
        spec.loader.exec_module(mod)
    finally:
        if orig is not None:
            sys.modules[name] = orig
        else:
            sys.modules.pop(name, None)
    return mod


tl = load("timeline")

PAGE = """---
title: "{title}"
type: period
chrono: {chrono}
sources:
{sources}---

# {title}
"""

BIRTHDAY = chrono.parse_edtf("1981-07-11").to_dict()

#: The three legacy eras this vault has. `high-school` is the trap: its own
#: name is era LANGUAGE (`_PERIOD_KEYWORDS["high-school"] == ("high school",)`)
#: and it is undated, so before v254 it both COLLECTED the mis-slotted moments
#: and then took its bounds from them.
ERAS = (("High School", "high-school", 1),
        ("My 20s", "my-20s", 2),
        ("My 30s", "my-30s", 3))

#: Dated ONLY by `cross_dating.from_age_statement` — exactly the founder's own
#: `date_derived.rule == "age"` shape, for twelve of his thirteen dated
#: moments. Each answer is classifier-tagged with the `high school` era, which
#: is how the founder's real moments reached rung 2.
MOMENTS = (
    {"title": "Married Katie",
     "description": "We got married at the courthouse.",
     "when_hint": "I was 26 when I married Katie",
     "anchor": None, "date": None},
    {"title": "Moved to Seattle",
     "description": "We packed the car and drove north.",
     "when_hint": "I was 31 when we moved to Seattle",
     "anchor": None, "date": None},
)


class FounderShapedVault(unittest.TestCase):
    """One vault, built the way a real one is: roster + pages + one
    classification per answer + a filed birth landmark."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.root = root
        (root / "wiki" / "periods").mkdir(parents=True)
        (root / "wiki" / "places").mkdir(parents=True)
        (root / "sources" / "manual").mkdir(parents=True)
        (root / "state" / "classifications").mkdir(parents=True)
        (root / "state" / "entity_rosters").mkdir()
        (root / "state" / "connectors").mkdir()

        refs = [f"A{index}" for index in range(1, len(MOMENTS) + 1)]
        for ref, moment in zip(refs, MOMENTS):
            (root / "state" / "classifications" / f"answers-{ref.lower()}.json").write_text(
                json.dumps({"source_path": f"answers/{ref}.md",
                            "events": [moment],
                            "time_periods": [{"era": "high school"}]}),
                encoding="utf-8")
        for name, slug, chrono_index in ERAS:
            (root / "wiki" / "periods" / f"{slug}.md").write_text(
                PAGE.format(title=name, chrono=chrono_index,
                            sources="".join(f'  - "answers/{ref}.md"\n'
                                            for ref in refs)),
                encoding="utf-8")
        (root / "state" / "entity_rosters" / "period.json").write_text(json.dumps({
            "version": 1, "type": "period",
            "entities": [{"name": name, "slug": slug, "chrono": index,
                          "page_eligible": True}
                         for name, slug, index in ERAS]}), encoding="utf-8")

        self.store = root / "state" / "landmarks.json"
        self.store.write_text(json.dumps({
            "version": 1,
            "domains": {"birth": [{"label": "birth", "date": BIRTHDAY}]}}),
            encoding="utf-8")

        self._orig = {name: getattr(tl, name) for name in tl.VAULT_ROOT_NAMES}
        state = root / "state"
        for name, value in {
            "CLASSIFICATIONS_DIR": state / "classifications",
            "CONNECTORS_STATE_DIR": state / "connectors",
            "ENTITY_ROSTERS_DIR": state / "entity_rosters",
            "MANUAL_SOURCES_DIR": root / "sources" / "manual",
            "PLACEMENTS_FILE": state / "timeline_placements.json",
            "STATE_DIR": state,
            "WIKI_DIR": root / "wiki",
        }.items():
            setattr(tl, name, value)

    def tearDown(self):
        for name, value in self._orig.items():
            setattr(tl, name, value)
        self.tmp.cleanup()

    def data(self):
        with mock.patch.object(tl, "LANDMARKS_STORE", self.store):
            return tl.timeline_data()

    def rows(self, data):
        found = {}
        for slug, group in data["event_lineup"].items():
            for row in group:
                found[row["title"]] = (slug, row)
        for row in data["unplaced_events"]:
            found[row["title"]] = (None, row)
        return found

    def period(self, data, slug):
        return next(row for row in data["periods"] if row["slug"] == slug)


class DateBeforeYouPlaceTests(FounderShapedVault):
    """Face 1 — rung 1 must see the date the pass derives."""

    def test_a_cross_dated_moment_lands_in_its_frame_by_date(self):
        """RED before v254: both moments land in `high-school` at rung 2."""
        rows = self.rows(self.data())
        self.assertEqual(rows["Married Katie"][0], "my-20s")
        self.assertEqual(rows["Moved to Seattle"][0], "my-30s")

    def test_it_lands_there_AT_RUNG_1_and_says_so(self):
        rows = self.rows(self.data())
        for title in ("Married Katie", "Moved to Seattle"):
            with self.subTest(title=title):
                reason = rows[title][1]["placement_reason"]
                self.assertEqual(reason["rung"], 1)
                self.assertEqual(reason["evidence"], "date")
                self.assertEqual(reason["frame_by"], "date")
                self.assertEqual(rows[title][1]["provenance_summary"],
                                 "Placed by its own date, against your age frames.")

    def test_the_date_still_comes_from_the_age_statement(self):
        """The reorder must not change WHAT is derived — only WHEN."""
        rows = self.rows(self.data())
        self.assertEqual(rows["Married Katie"][1]["date_derived"]["rule"], "age")
        self.assertEqual(rows["Moved to Seattle"][1]["date_derived"]["rule"], "age")
        self.assertEqual(chrono.year_of(rows["Married Katie"][1]["date"]), 2007)
        self.assertEqual(chrono.year_of(rows["Moved to Seattle"][1]["date"]), 2012)

    def test_the_era_whose_language_used_to_catch_them_now_catches_none(self):
        """`high-school` holds 56 moments on the founder's vault. Here: zero."""
        data = self.data()
        self.assertEqual(data["event_lineup"]["high-school"], [])

    def test_both_halves_of_the_pass_report_one_set_of_counts(self):
        report = self.data()["cross_dating"]
        self.assertEqual(report["derived"], 2)
        self.assertEqual(report["by_rule"]["age"], 2)
        self.assertEqual(self.data()["counts"]["events_cross_dated"], 2)

    def test_no_cycle_the_pre_placement_phase_reads_no_period(self):
        """Proved, not asserted: phase one is handed the events and the ENTITY
        lineup and nothing else, so a period cannot be an input to the
        placement it precedes. Handing it a period-shaped era with a span
        changes not one date."""
        events = [dict(row, source="answers/A1.md", source_short="A1")
                  for row in MOMENTS]
        alone = xd.cross_date_moments(events, birth_date=BIRTHDAY)
        again = xd.cross_date_moments(
            [dict(row, source="answers/A1.md", source_short="A1") for row in MOMENTS],
            entity_lineup={"high-school": [
                {"slug": "somewhere", "title": "Somewhere", "type": "place",
                 "date": None, "sources": ["answers/A1.md"]}]},
            birth_date=BIRTHDAY)
        self.assertEqual(alone["derived"], again["derived"])
        self.assertEqual([row["rule"] for row in alone["moments"]],
                         [row["rule"] for row in again["moments"]])
        self.assertEqual([row["period"] for row in alone["moments"]], [None, None])

    def test_the_owners_pin_still_outranks_the_derived_date(self):
        """And it leaves no derived provenance behind on a stated date."""
        events = tl.load_events()
        target = next(row for row in events if row["title"] == "Married Katie")
        tl.save_placement(tl.placement_key(target), target["source"],
                          target["description"], "high-school",
                          when_hint="", correction="", note="",
                          date=chrono.parse_edtf("2009").to_dict())
        rows = self.rows(self.data())
        slug, row = rows["Married Katie"]
        self.assertEqual(slug, "high-school")
        self.assertEqual(row["placement_reason"]["rung"], 0)
        self.assertEqual(chrono.year_of(row["date"]), 2009)
        self.assertNotIn("date_derived", row)


class AnEraIsNeverDatedByItsMembersTests(FounderShapedVault):
    """Face 2 — ADR 0030 decision 4, on the legacy band ladder."""

    def test_no_legacy_era_carries_a_member_derived_bound(self):
        """RED before v254: `high-school` reads 2007/2012, from the two
        moments that only landed there because of face 1."""
        data = self.data()
        for _name, slug, _index in ERAS:
            with self.subTest(slug=slug):
                period = self.period(data, slug)
                derived = period.get("date_derived") or {}
                self.assertNotIn(derived.get("rule"), ("moments",))
                self.assertNotIn(derived.get("join"), ("moment_envelope",))
        self.assertIsNone(self.period(data, "high-school")["date"])

    def test_the_coverage_is_still_reported_under_its_own_name(self):
        """Never lost — just never a bound. Same key and same arithmetic as
        `temporal_timeline.observed_envelope`."""
        data = self.data()
        twenties = self.period(data, "my-20s")
        envelope = chrono.from_dict(twenties["observed_envelope"])
        self.assertEqual(envelope.basis, "order")
        self.assertEqual(chrono.year_of(envelope), 2007)
        self.assertEqual(data["cross_dating"]["bands"]["observed_envelopes"], 2)
        # An era with no dated members says nothing at all.
        self.assertNotIn("observed_envelope", self.period(data, "high-school"))

    def test_the_envelope_never_reaches_the_span_a_reader_shows(self):
        """`My 20s` HAS a span — from the birthday, the rung that survives —
        and it is the decade, not the one year its lone member covers."""
        twenties = self.period(self.data(), "my-20s")
        self.assertEqual(twenties["date_derived"]["rule"], "age_label")
        self.assertEqual(twenties["date"].best, "2001/2011")
        self.assertEqual(twenties["approximate_dates"], "2001\u20132011")
        self.assertNotEqual(twenties["date"].to_dict(),
                            twenties["observed_envelope"])

    def test_the_rung_is_gone_from_the_ladder_not_merely_unused(self):
        self.assertEqual(xd.BAND_RULES, ("residence", "age_label"))
        self.assertEqual(xd.BAND_JOINS, ("residence_span", "age_label"))
        self.assertFalse(hasattr(xd, "moment_envelope"))
        with self.assertRaises(TypeError):
            xd.band_span({"slug": "x", "name": "x", "date": None},
                         moments=[{"date": chrono.parse_edtf("1984")}])

    def test_the_envelope_is_the_one_definition_the_projection_uses(self):
        rows = [{"date": chrono.parse_edtf("1984")},
                {"date": chrono.parse_edtf("1990")}]
        self.assertEqual(xd.observed_envelope(rows), xd.span_from_dated(rows))
        self.assertIsNone(xd.observed_envelope([{"date": None}]))

    def test_an_age_named_era_is_still_dated_by_the_birthday(self):
        """The rung that survives: `My 20s` means the decade from the twentieth
        birthday, and it bounds what is inside it exactly as before."""
        found = xd.band_span({"slug": "my-20s", "name": "My 20s", "date": None},
                             birth_date=BIRTHDAY)
        self.assertEqual(found.rule, "age_label")
        self.assertEqual(found.record.best, "2001/2011")
        self.assertEqual(xd.BAND_RULES_THAT_BOUND, ("age_label",))


if __name__ == "__main__":
    unittest.main()
