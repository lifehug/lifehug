"""v205 / ADR 0026 — cross-dating: a resolved anchor places its moments.

The owner filed his birth landmark and the moment "Born in Redlands while the
family lived in the area" still read *undated*, carrying a stale free-text
`anchor: dad attending ASU` that was not even temporally right — ASU came
later. `keystones()` had been promising "one answer would place 53 more
things" since v196 and nothing in the package ever delivered it. These are the
goldens for the pass that does.

Synthetic data only; NEVER references ~/Workspace/dave.
"""

from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
import contextlib
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SYSTEM = ROOT / "system"
sys.path.insert(0, str(SYSTEM))

import chronology as chrono  # noqa: E402
import cross_dating as xd  # noqa: E402
import landmarks_interaction as li  # noqa: E402


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


@contextlib.contextmanager
def timeline_module():
    """Make `import timeline` resolve to OUR patched module for the duration.

    Restores whatever was cached before — popping the entry instead would make
    the next `import timeline` build a fresh, unpatched module, which is
    exactly how a sibling suite's patched `PLACEMENTS_FILE` gets lost.
    """
    saved = sys.modules.get("timeline")
    sys.modules["timeline"] = tl
    try:
        yield
    finally:
        if saved is not None:
            sys.modules["timeline"] = saved
        else:
            sys.modules.pop("timeline", None)

PAGE = """---
title: "{title}"
type: {page_type}
chrono: {chrono}
{extra}sources:
{sources}---

# {title}
"""


def _sources(refs):
    return "".join(f'  - "answers/{ref}.md"\n' for ref in refs)


def _date(edtf: str) -> dict:
    """A landmark's stored date, normalized the way `save_landmark` stores it."""
    return chrono.parse_edtf(edtf).to_dict()


BIRTHDAY = _date("1981-07-11")


def _anchors(landmarks: dict) -> dict:
    return li.anchors_from_landmarks(landmarks)


# ---------------------------------------------------------------------------
# The pure ladder.
# ---------------------------------------------------------------------------


class DefinitionalBirthTests(unittest.TestCase):
    """Golden 1 — the owner's own case."""

    LANDMARKS = {"birth": [{"label": "birth", "date": BIRTHDAY}]}

    MOMENT = {
        "title": "Born in Redlands",
        "description": "Born in Redlands while the family lived in the area.",
        "when_hint": "",
        # The classifier's free-text anchor, verbatim from the owner's vault —
        # and temporally WRONG: ASU came years later.
        "anchor": "dad attending ASU",
        "date": None,
    }

    def test_the_birth_landmark_dates_the_birth_moment_to_the_day(self):
        found = xd.derive(dict(self.MOMENT), anchors=_anchors(self.LANDMARKS))
        self.assertIsNotNone(found)
        self.assertEqual(found.record.best, "1981-07-11")
        self.assertEqual(found.rule, "definitional")
        self.assertEqual(found.join, "birth")
        self.assertEqual(found.anchor, "birth")

    def test_the_derived_date_names_the_landmark_it_leaned_on(self):
        found = xd.derive(dict(self.MOMENT), anchors=_anchors(self.LANDMARKS))
        self.assertEqual(found.provenance, "from your birthday")
        self.assertEqual(found.record.basis, "anchor")
        self.assertEqual(found.record.anchors, ("birth",))
        self.assertEqual([p["claim"] for p in found.record.provenance],
                         ["from your birthday"])

    def test_a_definitional_join_inherits_the_landmarks_own_confidence(self):
        """Owner ruling, 2026-08-24: the marker sets are deliberately
        exact-match, so a definitional identity — *this moment IS your birth* —
        is not an estimate. `chronology.from_anchor` floors a RELATION at
        `inferred`, which is right for "before the move" and wrong here."""
        found = xd.derive(dict(self.MOMENT), anchors=_anchors(self.LANDMARKS))
        self.assertEqual(found.record.confidence, "certain")
        self.assertEqual(chrono.from_dict(BIRTHDAY).confidence, "certain")

    def test_an_uncertain_landmark_is_inherited_just_as_faithfully(self):
        """Inheritance, not promotion: a hedged birthday stays hedged."""
        hedged = {"birth": [{"label": "birth", "date": _date("1981~")}]}
        found = xd.derive(dict(self.MOMENT), anchors=_anchors(hedged))
        self.assertEqual(found.record.confidence, "approximate")

    def test_a_derived_date_is_still_never_STATED(self):
        """Inheriting the confidence never inherits the warrant: the basis
        stays `anchor`, so `claim_score` keeps every stated claim above it."""
        found = xd.derive(dict(self.MOMENT), anchors=_anchors(self.LANDMARKS))
        self.assertEqual(found.record.basis, "anchor")
        stated = chrono.parse_edtf("1979", basis="stated")
        self.assertGreater(chrono.claim_score(stated), chrono.claim_score(found.record))

    def test_with_no_birthday_filed_nothing_is_derived(self):
        self.assertIsNone(xd.derive(dict(self.MOMENT), anchors={}))

    def test_somebody_elses_birth_is_never_joined_to_yours(self):
        """A miss is fine; a wrong join is not."""
        for description in (
            "My sister was born the winter after we moved.",
            "Born in Redlands, and two years later my brother was born there too.",
            "Our first child was born at the county hospital.",
        ):
            with self.subTest(description=description):
                moment = {"title": "", "description": description,
                          "when_hint": "", "anchor": "", "date": None}
                self.assertIsNone(xd.derive(moment, anchors=_anchors(self.LANDMARKS)))

    def test_a_free_text_anchor_that_names_no_landmark_derives_nothing(self):
        """The stale-anchor guard, stated as its own rule: `dad attending ASU`
        is not in the index, so it can never place anything."""
        moment = {"title": "The blue bicycle", "description": "I got a blue bicycle.",
                  "when_hint": "", "anchor": "dad attending ASU", "date": None}
        self.assertIsNone(xd.derive(moment, anchors=_anchors(self.LANDMARKS)))

    def test_a_free_text_anchor_that_names_a_landmark_exactly_does_place_it(self):
        anchors = _anchors({**self.LANDMARKS,
                            "residences": [{"label": "Redlands",
                                            "span": {"start": {"best": "1981"},
                                                     "end": {"best": "1986"}}}]})
        moment = {"title": "The blue bicycle", "description": "I got a blue bicycle.",
                  "when_hint": "", "anchor": "Redlands", "date": None}
        found = xd.derive(moment, anchors=anchors)
        self.assertEqual(found.join, "named_anchor")
        self.assertEqual(found.anchor, "residences-redlands")


class AgeStatementTests(unittest.TestCase):
    """Golden 2 — an age statement the classifier never lifted into a claim."""

    def test_an_age_in_the_hint_becomes_an_interval(self):
        moment = {"title": "Grandpa's letter", "description": "Grandpa sent a letter.",
                  "when_hint": "when I was about five", "anchor": "", "date": None}
        found = xd.derive(moment, anchors={}, birth_date=BIRTHDAY)
        self.assertEqual(found.rule, "age")
        self.assertEqual(found.record.basis, "age")
        self.assertEqual(found.record.best, "1986~")
        self.assertEqual((found.record.earliest, found.record.latest), ("1985", "1988"))

    def test_the_written_ages_the_detector_accepts(self):
        cases = {
            "when I was five": "five",
            "when I was about five": "about five",
            "when I was 5 or 6": "5 or 6",
            "I was seven years old": "seven",
            "a 12-year-old on a bike": "12",
            "at the age of 19": "19",
            "at 19 I left home": "19",
        }
        for text, fragment in cases.items():
            with self.subTest(text=text):
                moment = {"title": "", "description": text, "when_hint": "",
                          "anchor": "", "date": None}
                self.assertEqual(xd.age_statement(moment), fragment)

    def test_a_bare_number_is_never_read_as_an_age(self):
        """`chronology.parse_age` is greedy by design, so the pass hands it
        only what an age STATEMENT matched — never raw prose."""
        for text in ("We drove 400 miles that day.",
                     "The house at 19 Elm Street burned down.",
                     "It cost 30 dollars."):
            with self.subTest(text=text):
                moment = {"title": "", "description": text, "when_hint": "",
                          "anchor": "", "date": None}
                self.assertIsNone(xd.age_statement(moment))

    def test_without_a_birthday_an_age_places_nothing(self):
        moment = {"title": "", "description": "when I was about five",
                  "when_hint": "", "anchor": "", "date": None}
        self.assertIsNone(xd.derive(moment, anchors={}, birth_date=None))


class ResidenceBoundsTests(unittest.TestCase):
    """Golden 3 — a residence span, as a boundary and as bounds."""

    LANDMARKS = {
        "birth": [{"label": "birth", "date": BIRTHDAY}],
        "residences": [{"label": "Mesa", "span": {"start": {"best": "1984"},
                                                  "end": {"best": "1990"}}}],
    }

    def test_a_move_IS_the_spans_start(self):
        moment = {"title": "The move to Mesa", "description": "We moved to Mesa.",
                  "when_hint": "", "anchor": "", "date": None}
        found = xd.derive(moment, anchors=_anchors(self.LANDMARKS))
        self.assertEqual(found.join, "move_in")
        self.assertEqual(found.record.best, "1984")
        self.assertEqual(found.provenance, "from when you moved to Mesa")

    def test_leaving_IS_the_spans_end(self):
        moment = {"title": "Leaving Mesa", "description": "We left Mesa for good.",
                  "when_hint": "", "anchor": "", "date": None}
        found = xd.derive(moment, anchors=_anchors(self.LANDMARKS))
        self.assertEqual(found.join, "move_out")
        self.assertEqual(found.record.best, "1990")
        self.assertEqual(found.provenance, "from when you left Mesa")

    def test_a_move_to_a_place_with_no_landmark_derives_nothing(self):
        moment = {"title": "The move to Alder Street",
                  "description": "We moved into the little house on Alder.",
                  "when_hint": "", "anchor": "", "date": None}
        self.assertIsNone(xd.derive(moment, anchors=_anchors(self.LANDMARKS)))

    def test_containment_yields_BOUNDS_not_a_point(self):
        moment = {"title": "The bike with no brakes",
                  "description": "I rode a bike with no brakes.",
                  "when_hint": "", "anchor": "", "date": None}
        found = xd.derive(moment, anchors={},
                          place={"slug": "mesa", "title": "Mesa",
                                 "date": chrono.parse_edtf("1984/1990")})
        self.assertEqual(found.rule, "containment")
        self.assertEqual(found.join, "place")
        self.assertEqual(found.record.granularity, "range")
        self.assertEqual((found.record.earliest, found.record.latest), ("1984", "1990"))
        self.assertEqual(found.provenance, "within your years at Mesa")

    def test_an_era_bounds_more_loosely_than_a_place_and_says_so(self):
        moment = {"title": "The bike", "description": "I rode a bike.",
                  "when_hint": "", "anchor": "", "date": None}
        era = xd.derive(dict(moment), anchors={},
                        period={"slug": "childhood", "name": "Childhood",
                                "date": chrono.parse_edtf("1984/1990")})
        place = xd.derive(dict(moment), anchors={},
                          place={"slug": "mesa", "title": "Mesa",
                                 "date": chrono.parse_edtf("1984/1990")})
        self.assertEqual(era.record.confidence, "conjectural")
        self.assertEqual(place.record.confidence, "inferred")
        self.assertGreater(chrono.claim_score(place.record),
                           chrono.claim_score(era.record))

    def test_a_half_open_span_bounds_nothing(self):
        """Containment needs BOTH termini; one is not an interval."""
        self.assertIsNone(xd.containment(chrono.parse_edtf("1984/.."),
                                         anchor="period:x", label="X", join="era"))

    def test_only_the_definitional_rule_inherits(self):
        """The ruling is scoped: age and containment keep their own grading."""
        age = xd.derive({"title": "", "description": "when I was about five",
                         "when_hint": "", "anchor": "", "date": None},
                        anchors={}, birth_date=BIRTHDAY)
        self.assertEqual(age.record.confidence, "approximate")  # the hedge, not the landmark
        place = xd.derive({"title": "", "description": "I rode a bike.",
                           "when_hint": "", "anchor": "", "date": None},
                          anchors={},
                          place={"slug": "mesa", "title": "Mesa",
                                 "date": chrono.parse_edtf("1984/1990")})
        era = xd.derive({"title": "", "description": "I rode a bike.",
                         "when_hint": "", "anchor": "", "date": None},
                        anchors={},
                        period={"slug": "childhood", "name": "Childhood",
                                "date": chrono.parse_edtf("1984/1990")})
        # Both spans are `certain`; containment does NOT inherit that.
        self.assertEqual(chrono.parse_edtf("1984/1990").confidence, "certain")
        self.assertEqual(place.record.confidence, "inferred")
        self.assertEqual(era.record.confidence, "conjectural")

    def test_the_ladder_prefers_the_tightest_join_available(self):
        moment = {"title": "The move to Mesa", "description": "We moved to Mesa.",
                  "when_hint": "when I was about five", "anchor": "", "date": None}
        found = xd.derive(moment, anchors=_anchors(self.LANDMARKS),
                          birth_date=BIRTHDAY,
                          period={"slug": "childhood", "name": "Childhood",
                                  "date": chrono.parse_edtf("1984/1990")})
        self.assertEqual(found.rule, "definitional")
        self.assertEqual(xd.RULES, ("definitional", "age", "containment"))


class NeverOverwriteTests(unittest.TestCase):
    """Golden 4 — a conflicting explicit record is not touched."""

    LANDMARKS = {"birth": [{"label": "birth", "date": BIRTHDAY}]}

    def test_a_stated_date_that_contradicts_the_landmark_survives(self):
        stated = chrono.parse_edtf("1979", basis="stated")
        moment = {"title": "Born in Redlands",
                  "description": "Born in Redlands while the family lived in the area.",
                  "when_hint": "", "anchor": "", "date": stated}
        self.assertIsNone(xd.derive(moment, anchors=_anchors(self.LANDMARKS)))

    def test_the_pass_leaves_the_row_exactly_as_it_found_it(self):
        stated = chrono.parse_edtf("1979", basis="stated")
        moment = {"title": "Born in Redlands", "source": "answers/A1.md",
                  "source_short": "A1",
                  "description": "Born in Redlands while the family lived in the area.",
                  "when_hint": "", "anchor": "", "date": stated}
        report = xd.cross_date(event_lineup={"childhood": [moment]},
                               anchors=_anchors(self.LANDMARKS))
        self.assertEqual(report["derived"], 0)
        self.assertIs(moment["date"], stated)
        self.assertNotIn("date_derived", moment)


# ---------------------------------------------------------------------------
# End to end, through `timeline_data`.
# ---------------------------------------------------------------------------


class VaultFixture(unittest.TestCase):
    """A synthetic vault: one dated era with a dated place inside it, and four
    moments the classifier could not date on its own."""

    LANDMARKS = {
        "version": 1,
        "domains": {
            "birth": [{"label": "birth", "date": BIRTHDAY}],
            "residences": [{"label": "Mesa",
                            "span": {"start": {"best": "1984"},
                                     "end": {"best": "1990"}}}],
        },
    }

    EVENTS = [
        {"title": "Born in Redlands",
         "description": "Born in Redlands while the family lived in the area.",
         "when_hint": "", "anchor": "dad attending ASU", "date": None},
        {"title": "The move to Mesa", "description": "We moved to Mesa.",
         "when_hint": "", "anchor": None, "date": None},
        {"title": "Grandpa's two-page letter",
         "description": "Grandpa sent a two-page letter about the farm.",
         "when_hint": "when I was about five", "anchor": None, "date": None},
        {"title": "The bike with no brakes",
         "description": "I rode a bike with no brakes down the hill.",
         "when_hint": "", "anchor": None, "date": None},
    ]

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

        (root / "wiki" / "periods" / "childhood.md").write_text(
            PAGE.format(title="Childhood", page_type="period", chrono=1,
                        extra="date: 1984/1990\n", sources=_sources(["A1"])),
            encoding="utf-8")
        (root / "wiki" / "places" / "mesa.md").write_text(
            PAGE.format(title="Mesa", page_type="place", chrono=0,
                        extra="date: 1984/1990\n", sources=_sources(["A1"])),
            encoding="utf-8")
        (root / "state" / "entity_rosters" / "period.json").write_text(json.dumps({
            "version": 1, "type": "period", "entities": [
                {"name": "Childhood", "slug": "childhood", "chrono": 1,
                 "page_eligible": True, "date": "1984/1990"},
            ]}), encoding="utf-8")
        # eras O-E2: these moments enter Childhood by the classifier's OWN era
        # tag now (rung 2, `_era_label_match`), not by the retired
        # source-membership mechanism — the fixture's INTENT (four Childhood
        # moments) is unchanged; only how they get there is.
        self.write_events(self.EVENTS, eras=("childhood",))
        self.store = root / "state" / "landmarks.json"
        self.store.write_text(json.dumps(self.LANDMARKS), encoding="utf-8")

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

    def write_events(self, events, *, eras: tuple = ()):
        """`eras` (eras O-E2): the classifier's OWN era tags for this answer
        (`load_events`' `time_periods`) — the rung 2 signal that replaces
        source membership. Absent, exactly v206's byte-identical shape."""
        payload = {"source_path": "answers/A1.md", "events": events}
        if eras:
            payload["time_periods"] = [{"era": e} for e in eras]
        (self.root / "state" / "classifications" / "answers-a1.json").write_text(
            json.dumps(payload), encoding="utf-8")

    def write_one_per_source(self, events, *, eras: tuple = ()):
        """One classification per answer — `unknown_key` is (period, source),
        so N moments are only N unknowns when they came from N answers, which
        is the shape a real vault has. `eras`: see `write_events`."""
        for path in (self.root / "state" / "classifications").glob("*.json"):
            path.unlink()
        refs = []
        for index, event in enumerate(events, start=1):
            ref = f"A{index}"
            refs.append(ref)
            payload = {"source_path": f"answers/{ref}.md", "events": [event]}
            if eras:
                payload["time_periods"] = [{"era": e} for e in eras]
            (self.root / "state" / "classifications" / f"answers-a{index}.json").write_text(
                json.dumps(payload), encoding="utf-8")
        return refs

    def write_period_page(self, refs, *, dated: bool):
        (self.root / "wiki" / "periods" / "childhood.md").write_text(
            PAGE.format(title="Childhood", page_type="period", chrono=1,
                        extra="date: 1984/1990\n" if dated else "",
                        sources=_sources(refs)),
            encoding="utf-8")

    def data(self):
        with mock.patch.object(tl, "LANDMARKS_STORE", self.store):
            return tl.timeline_data()

    def moments(self, data):
        rows = [e for group in data["event_lineup"].values() for e in group]
        rows += list(data["unplaced_events"])
        return {row["title"]: row for row in rows}


class OwnerCaseTests(VaultFixture):
    def test_the_birth_moment_finally_carries_the_birthday(self):
        moments = self.moments(self.data())
        born = moments["Born in Redlands"]
        self.assertEqual(born["date"].best, "1981-07-11")
        # Owner ruling: a DEFINITIONAL join is an identity, not an estimate,
        # so the certain birthday reads as the certain date it is.
        self.assertEqual(chrono.display_date(born["date"], with_basis=False),
                         "11 July 1981")

    def test_the_stale_free_text_anchor_is_demoted_not_displayed(self):
        moments = self.moments(self.data())
        born = moments["Born in Redlands"]
        self.assertEqual(born["date_derived"]["provenance"], "from your birthday")
        # The classifier's own text survives on the row for the detail view —
        # never destroyed, never the thing the chip contradicts.
        self.assertEqual(born["anchor"], "dad attending ASU")

    def test_the_viewer_shows_the_provenance_where_the_anchor_used_to_be(self):
        sw = load("serve_wiki")
        with timeline_module(), mock.patch.object(tl, "LANDMARKS_STORE", self.store):
            _title, body, _wide = sw.view_timeline()
        self.assertIn("· from your birthday", body)
        self.assertIn("classified anchor: dad attending ASU", body)
        self.assertNotIn("anchor: dad attending ASU</span>", body)

    def test_the_compiled_export_carries_the_same_line(self):
        wc = load("wiki_compile")
        bindings = {
            "CLASSIFICATIONS_DIR": self.root / "state" / "classifications",
            "CONNECTORS_STATE_DIR": self.root / "state" / "connectors",
            "ENTITY_ROSTERS_DIR": self.root / "state" / "entity_rosters",
            "MANUAL_SOURCES_DIR": self.root / "sources" / "manual",
            "TIMELINE_PLACEMENTS_FILE": self.root / "state" / "timeline_placements.json",
            "STATE_DIR": self.root / "state",
            "WIKI_DIR": self.root / "wiki",
        }
        saved = {name: getattr(wc, name) for name in bindings}
        try:
            for name, value in bindings.items():
                setattr(wc, name, value)
            with timeline_module(), mock.patch.object(tl, "LANDMARKS_STORE", self.store):
                self.assertTrue(wc.compile_timeline())
        finally:
            for name, value in saved.items():
                setattr(wc, name, value)
        text = (self.root / "wiki" / "timeline.md").read_text(encoding="utf-8")
        self.assertIn("· from your birthday", text)
        self.assertIn("classified anchor: dad attending ASU", text)
        self.assertNotIn("· anchor: dad attending ASU", text)

    def test_every_rule_fires_on_the_same_read(self):
        report = self.data()["cross_dating"]
        self.assertEqual(report["derived"], 4)
        self.assertEqual(report["by_rule"]["definitional"], 2)   # birth + the move
        self.assertEqual(report["by_rule"]["age"], 1)
        self.assertEqual(report["by_rule"]["containment"], 1)

    def test_the_derivation_is_recomputed_not_stored(self):
        """No state: correct the landmark and the whole timeline re-derives."""
        before = self.moments(self.data())["Born in Redlands"]["date"].best
        self.store.write_text(json.dumps({
            "version": 1,
            "domains": {"birth": [{"label": "birth", "date": _date("1975-02-02")}]},
        }), encoding="utf-8")
        after = self.moments(self.data())["Born in Redlands"]["date"].best
        self.assertEqual(before, "1981-07-11")
        self.assertEqual(after, "1975-02-02")
        self.assertEqual(list(self.root.glob("state/cross_dating*")), [])

    def test_a_dated_moment_leaves_the_undated_unknowns(self):
        data = self.data()
        keys = {row["key"] for row in tl.unknowns(data)}
        self.assertFalse({key for key in keys if key.startswith("moment:")})
        self.assertEqual(data["counts"]["events_cross_dated"], 4)

    def test_the_compiled_page_prefers_the_landmark_provenance(self):
        row = self.moments(self.data())["Born in Redlands"]
        self.assertEqual(row["date_derived"]["join"], "birth")
        self.assertEqual(row["date_derived"]["anchor"], "birth")
        self.assertIn(row["date_derived"]["rule"], xd.RULES)


class PromiseEqualsDeliveryTests(VaultFixture):
    """Design item 3 — the leverage number and the pass are one join.

    `keystones()` promised "one answer would place N more things" and nothing
    delivered it. The test is the reconciliation: take the promise off an
    UNDATED vault, then supply exactly that one answer and count what dates.
    """

    def setUp(self):
        super().setUp()
        # Strip every span: nothing is dated, so the era is the open question.
        (self.root / "wiki" / "places" / "mesa.md").unlink()
        (self.root / "state" / "entity_rosters" / "period.json").write_text(json.dumps({
            "version": 1, "type": "period", "entities": [
                {"name": "Childhood", "slug": "childhood", "chrono": 1,
                 "page_eligible": True},
            ]}), encoding="utf-8")
        self.store.write_text(json.dumps({"version": 1, "domains": {}}),
                              encoding="utf-8")
        refs = self.write_one_per_source([
            {"title": f"moment {n}", "description": f"Something happened, number {n}.",
             "when_hint": "", "anchor": None, "date": None}
            for n in range(48)
        ], eras=("childhood",))
        self.write_period_page(refs, dated=False)

    def _date_the_era(self):
        """The ONE answer the keystone asks for: when did Childhood run?"""
        (self.root / "state" / "entity_rosters" / "period.json").write_text(json.dumps({
            "version": 1, "type": "period", "entities": [
                {"name": "Childhood", "slug": "childhood", "chrono": 1,
                 "page_eligible": True, "date": "1984/1990"},
            ]}), encoding="utf-8")

    def test_the_promise_is_exactly_what_the_pass_then_delivers(self):
        data = self.data()
        index = tl.dependency_index(data)
        promised = tl.leverage("period:childhood", index)
        moment_promises = {key for key in index["period:childhood"]
                           if key.startswith("moment:")}
        self.assertEqual(len(moment_promises), 48)

        self._date_the_era()
        after = self.data()
        delivered = after["cross_dating"]["derived"]
        self.assertEqual(delivered, len(moment_promises))
        self.assertGreaterEqual(promised, delivered)  # + the era's own bounds

        remaining = {row["key"] for row in tl.unknowns(after)
                     if row["key"].startswith("moment:")}
        self.assertEqual(remaining, set())

    def test_a_dated_moment_no_longer_claims_its_undated_neighbours(self):
        """v205 honesty: a point is not a span, and nothing has ever derived a
        date from an adjacent moment."""
        refs = self.write_one_per_source([
            {"title": "The barn fire", "description": "The barn burned down.",
             "when_hint": "", "anchor": None, "date": {"stated": "1986"}},
            {"title": "The dog", "description": "A dog followed me home.",
             "when_hint": "", "anchor": None, "date": None},
        ], eras=("childhood",))
        self.write_period_page(refs, dated=False)
        index = tl.dependency_index(self.data())
        event_keys = [key for key in index if key.startswith("event:")]
        self.assertTrue(event_keys)
        for key in event_keys:
            with self.subTest(anchor=key):
                self.assertFalse({k for k in index[key] if k.startswith("moment:")})

    def test_a_person_no_longer_claims_the_moments_that_share_its_sources(self):
        index = tl.dependency_index({
            "periods": [{"slug": "childhood", "name": "Childhood", "date": None}],
            "event_lineup": {"childhood": [
                {"title": "m", "source": "answers/A1.md", "source_short": "A1",
                 "date": None}]},
            "entity_lineup": {"childhood": [
                {"slug": "mom", "title": "Mom", "type": "person",
                 "sources": ["answers/A1.md"]}]},
            "unplaced_events": [], "bands": [], "global_gaps": [],
            "gaps_by_period": {}, "anchors": {},
        })
        self.assertEqual(index["entity:mom"], set())
        self.assertIn("moment:childhood:A1", index["period:childhood"])


class FoundersScaleTests(VaultFixture):
    """The measurement the owner asked for, on a synthetic mirror of the shape
    his vault has: 48 Childhood moments, none of them carrying a claim."""

    def setUp(self):
        super().setUp()
        (self.root / "wiki" / "places" / "mesa.md").unlink()
        refs = self.write_one_per_source([
            {"title": f"childhood moment {n}",
             "description": f"Something from those years, number {n}.",
             "when_hint": "", "anchor": None, "date": None}
            for n in range(48)
        ], eras=("childhood",))
        self.write_period_page(refs, dated=True)

    def test_a_dated_childhood_places_all_forty_eight(self):
        data = self.data()
        self.assertEqual(data["cross_dating"]["derived"], 48)
        self.assertEqual(data["counts"]["events_dated"], 48)
        # And every one of them is BOUNDS, never a manufactured point.
        for row in data["event_lineup"]["childhood"]:
            with self.subTest(title=row["title"]):
                self.assertEqual(row["date"].granularity, "range")
                self.assertEqual(row["date"].basis, "anchor")


# ---------------------------------------------------------------------------
# v207 — bands date themselves (ADR 0026 amendment, design D2/D3).
# ---------------------------------------------------------------------------


class BandLadderTests(unittest.TestCase):
    """The pure band ladder, one rung at a time."""

    def _period(self, name="Childhood", slug="childhood"):
        return {"slug": slug, "name": name, "date": None}

    # -- rule 1: residences ------------------------------------------------

    def test_a_bands_places_union_into_its_span(self):
        found = xd.band_span(self._period(), places=[
            {"key": "entity:mesa", "label": "Mesa", "date": chrono.parse_edtf("1984/1988")},
            {"key": "entity:yucaipa", "label": "Yucaipa", "date": chrono.parse_edtf("1988/1990")},
        ])
        self.assertEqual(found.rule, "residence")
        self.assertEqual(found.join, "residence_span")
        self.assertEqual(found.record.best, "1984/1990")
        self.assertEqual(found.record.confidence, "inferred")
        self.assertEqual(found.provenance, "from where you were living then")
        self.assertEqual(found.record.anchors, ("entity:mesa", "entity:yucaipa"))

    def test_one_place_is_named_in_the_provenance(self):
        found = xd.band_span(self._period(), places=[
            {"key": "residences-mesa", "label": "Mesa",
             "date": chrono.parse_edtf("1984/1990")}])
        self.assertEqual(found.provenance, "from your years at Mesa")
        self.assertEqual(chrono.display_date(found.record, with_basis=False), "1984\u20131990")

    def test_a_place_takes_its_span_from_the_residence_landmark_it_names(self):
        """The join the design asked for: the era is dated by the LANDMARK,
        through the place page that names it exactly."""
        anchors = li.anchors_from_landmarks(
            {"residences": [{"label": "Mesa", "span": {"start": {"best": "1984"},
                                                       "end": {"best": "1990"}}}]})
        places = xd.band_places({"childhood": [
            {"slug": "mesa", "title": "Mesa", "type": "place", "date": None},
            {"slug": "mom", "title": "Mom", "type": "person", "date": None},
        ]}, "childhood", anchors)
        self.assertEqual([row["key"] for row in places], ["residences-mesa"])
        self.assertEqual(places[0]["date"].best, "1984/1990")

    def test_a_place_page_that_names_no_landmark_and_has_no_span_contributes_nothing(self):
        anchors = li.anchors_from_landmarks(
            {"residences": [{"label": "Mesa", "span": {"start": {"best": "1984"},
                                                       "end": {"best": "1990"}}}]})
        self.assertEqual(xd.band_places({"childhood": [
            {"slug": "alder-street", "title": "Alder Street", "type": "place",
             "date": None}]}, "childhood", anchors), [])

    # -- the envelope: COVERAGE, never a bound (v254, issue #278) ----------
    #
    # These were `band_span`'s rule 2 until v254. They still assert the same
    # arithmetic — it is a genuinely useful number — but the thing it is
    # allowed to be has changed: an era is never dated by whatever got sorted
    # into it (ADR 0030 decision 4). The old assertions said `found.rule ==
    # "moments"` and the era took the span; they are gone with the rung.

    def test_the_envelope_covers_the_moments_already_dated_inside(self):
        found = xd.observed_envelope([
            {"date": chrono.parse_edtf("1984")},
            {"date": None},
            {"date": chrono.parse_edtf("1989")},
        ])
        self.assertEqual(found.best, "1984/1989")
        self.assertEqual(found.confidence, "inferred")
        self.assertEqual(found.basis, "order")

    def test_one_dated_moment_gives_a_conjectural_year_and_says_so(self):
        found = xd.observed_envelope([{"date": chrono.parse_edtf("1981-07-11")}])
        self.assertEqual(found.best, "1981?")
        self.assertEqual(found.confidence, "conjectural")
        self.assertEqual(chrono.display_date(found, with_basis=False), "around 1981")

    def test_the_envelope_is_the_one_definition_a_place_span_also_uses(self):
        """Recurring-defect doctrine: `timeline._place_span` delegates here,
        and so does `temporal_timeline.observed_envelope`."""
        events = [{"date": chrono.parse_edtf("1984")}, {"date": chrono.parse_edtf("1990")}]
        self.assertEqual(tl._place_span(events), xd.span_from_dated(events))  # noqa: SLF001
        self.assertEqual(xd.observed_envelope(events), xd.span_from_dated(events))

    def test_nothing_dated_inside_covers_nothing(self):
        self.assertIsNone(xd.observed_envelope([{"date": None}]))

    def test_the_envelope_can_no_longer_reach_the_band_ladder_at_all(self):
        """Not merely unused — removed, so a caller that still believes in it
        fails loud (ADR 0021)."""
        self.assertNotIn("moments", xd.BAND_RULES)
        self.assertNotIn("moment_envelope", xd.BAND_JOINS)
        self.assertFalse(hasattr(xd, "moment_envelope"))
        with self.assertRaises(TypeError):
            xd.band_span(self._period(), moments=[{"date": chrono.parse_edtf("1984")}])

    # -- rule 3: the age label --------------------------------------------

    def test_an_age_named_era_joins_the_birthday_definitionally(self):
        found = xd.band_span(self._period(name="My 20s"), birth_date=BIRTHDAY)
        self.assertEqual(found.rule, "age_label")
        self.assertEqual(found.join, "age_label")
        self.assertEqual(found.record.best, "2001/2011")
        self.assertEqual(found.provenance, "from your birthday")

    def test_the_age_label_inherits_the_birthdays_confidence(self):
        certain = xd.band_span(self._period(name="My Twenties"), birth_date=BIRTHDAY)
        hedged = xd.band_span(self._period(name="My Twenties"), birth_date=_date("1981~"))
        self.assertEqual(certain.record.confidence, "certain")
        self.assertEqual(hedged.record.confidence, "approximate")

    def test_the_labels_the_detector_accepts_and_the_ones_it_refuses(self):
        for name in ("My 20s", "my twenties", "In my thirties", "My teenage years"):
            with self.subTest(name=name):
                self.assertIsNotNone(xd.age_band_label(name))
        for name in ("The 1980s", "The Eighties", "his 40s", "Childhood",
                     "The Mesa Years", "Twenties"):
            with self.subTest(name=name):
                self.assertIsNone(xd.age_band_label(name))

    def test_without_a_birthday_an_age_label_places_nothing(self):
        self.assertIsNone(xd.band_span(self._period(name="My 20s"), birth_date=None))

    # -- the ladder --------------------------------------------------------

    def test_the_band_ladder_runs_in_its_own_declared_order(self):
        """Deliberately NOT `RULES`' order — an age LABEL is a name a roster
        model wrote, so it ranks under the rung grounded in what the person
        actually did. v254: `moments` is no longer between them."""
        found = xd.band_span(
            self._period(name="My 20s"),
            places=[{"key": "entity:mesa", "label": "Mesa",
                     "date": chrono.parse_edtf("2003/2008")}],
            birth_date=BIRTHDAY)
        self.assertEqual(found.rule, "residence")
        self.assertEqual(xd.BAND_RULES, ("residence", "age_label"))

    def test_an_explicit_band_date_is_never_overwritten(self):
        stated = chrono.parse_edtf("1975/1979", basis="stated")
        period = {"slug": "childhood", "name": "Childhood", "date": stated}
        self.assertIsNone(xd.band_span(period))
        report = xd.date_bands(periods=[period],
                               event_lineup={"childhood": [{"date": chrono.parse_edtf("1984")}]})
        self.assertEqual(report["derived"], 0)
        self.assertIs(period["date"], stated)
        self.assertNotIn("date_derived", period)
        # v254: a dated era still reports what its members cover — beside the
        # span the person stated, never instead of it.
        self.assertEqual(report["observed_envelopes"], 1)
        self.assertEqual(period["observed_envelope"]["best"], "1984?")

    def test_only_a_two_sided_span_may_bound_what_is_inside_it(self):
        """The sharpest line in the amendment: a floor is not a ceiling. One
        dated moment must never pin its era's other moments to its own year."""
        floor = {"slug": "childhood", "name": "Childhood",
                 "date": chrono.parse_edtf("1984"),
                 "date_derived": {"rule": "moments"}}
        closed = {"slug": "twenties", "name": "My 20s",
                  "date": chrono.parse_edtf("2001/2011"),
                  "date_derived": {"rule": "age_label"}}
        lookup = xd.containment_periods([floor, closed])
        self.assertIsNone(lookup["childhood"]["date"])
        self.assertIsNotNone(lookup["twenties"]["date"])
        # And the row a renderer holds still carries its span.
        self.assertIsNotNone(floor["date"])
        self.assertEqual(xd.BAND_RULES_THAT_BOUND, ("age_label",))


class FounderBandTests(VaultFixture):
    """v207's D2, as **v254 corrects it** (issue #278, ADR 0030 decision 4).

    D2 said: the birth is filed, and "Childhood" stops reading `undated` —
    because the era took the envelope of the moments dated inside it. The
    founder's real vault proved that wrong. Those moments are inside that era
    because of a PLACEMENT the same pass helps decide, so the era was dated by
    the accident of what got sorted into it: `high-school` read `1997/2021`
    off twelve moments that landed there only because rung 1 could not see
    their dates (lifehug-platform#720 CERT-02/03).

    So the birth moment is still dated to the day, the coverage is still
    computed and published — and "Childhood" reads `undated`, which is the
    honest answer until the person says when it was.
    """

    LANDMARKS = {"version": 1, "domains": {"birth": [{"label": "birth", "date": BIRTHDAY}]}}

    def setUp(self):
        super().setUp()
        (self.root / "wiki" / "places" / "mesa.md").unlink()
        refs = self.write_one_per_source([
            {"title": "Born in Redlands",
             "description": "Born in Redlands while the family lived in the area.",
             "when_hint": "", "anchor": "dad attending ASU", "date": None},
            {"title": "The bike with no brakes",
             "description": "I rode a bike with no brakes down the hill.",
             "when_hint": "", "anchor": None, "date": None},
        ], eras=("childhood",))
        self.write_period_page(refs, dated=False)
        self.write_roster(dated=False)

    def write_roster(self, *, dated: bool):
        entity = {"name": "Childhood", "slug": "childhood", "chrono": 1,
                  "page_eligible": True}
        if dated:
            entity["date"] = "1984/1990"
        (self.root / "state" / "entity_rosters" / "period.json").write_text(
            json.dumps({"version": 1, "type": "period", "entities": [entity]}),
            encoding="utf-8")

    def test_childhood_is_not_dated_by_the_moments_inside_it(self):
        """The v253 expectation was `1981?` / rule `moments` / 1 band derived.
        Every one of those was the defect."""
        data = self.data()
        childhood = data["periods"][0]
        self.assertEqual(childhood["slug"], "childhood")
        self.assertIsNone(childhood["date"])
        self.assertNotIn("date_derived", childhood)
        self.assertEqual(data["counts"]["periods_cross_dated"], 0)
        # …and the moment itself is dated exactly as before.
        self.assertEqual(self.moments(data)["Born in Redlands"]["date"].best,
                         "1981-07-11")

    def test_the_coverage_is_published_under_its_own_name(self):
        data = self.data()
        childhood = data["periods"][0]
        envelope = chrono.from_dict(childhood["observed_envelope"])
        self.assertEqual(envelope.best, "1981?")
        self.assertEqual(envelope.basis, "order")
        self.assertEqual(data["cross_dating"]["bands"]["observed_envelopes"], 1)

    def test_no_chip_claims_a_span_the_person_never_gave(self):
        childhood = self.data()["periods"][0]
        self.assertIsNone(childhood["date"])
        self.assertEqual(childhood.get("approximate_dates", ""), "")

    def test_the_viewer_no_longer_shows_a_member_derived_span(self):
        sw = load("serve_wiki")
        with timeline_module(), mock.patch.object(tl, "LANDMARKS_STORE", self.store):
            _title, body, _wide = sw.view_timeline()
        self.assertNotIn("· from the moments you have already dated", body)
        # The MOMENT's own provenance is untouched — only the era's went.
        self.assertIn("· from your birthday", body)

    def test_the_compiled_export_no_longer_carries_that_line(self):
        wc = load("wiki_compile")
        bindings = {
            "CLASSIFICATIONS_DIR": self.root / "state" / "classifications",
            "CONNECTORS_STATE_DIR": self.root / "state" / "connectors",
            "ENTITY_ROSTERS_DIR": self.root / "state" / "entity_rosters",
            "MANUAL_SOURCES_DIR": self.root / "sources" / "manual",
            "TIMELINE_PLACEMENTS_FILE": self.root / "state" / "timeline_placements.json",
            "STATE_DIR": self.root / "state",
            "WIKI_DIR": self.root / "wiki",
        }
        saved = {name: getattr(wc, name) for name in bindings}
        try:
            for name, value in bindings.items():
                setattr(wc, name, value)
            with timeline_module(), mock.patch.object(tl, "LANDMARKS_STORE", self.store):
                self.assertTrue(wc.compile_timeline())
        finally:
            for name, value in saved.items():
                setattr(wc, name, value)
        text = (self.root / "wiki" / "timeline.md").read_text(encoding="utf-8")
        self.assertNotIn("from the moments you have already dated", text)
        self.assertIn("## Childhood", text)

    def test_the_eras_bounds_stay_an_open_question(self):
        """Honest accounting, inverted by v254: the era's years are genuinely
        unknown, so `period_bound` is an outstanding question to ASK rather
        than one silently answered from its own members."""
        data = self.data()
        keys = {row["key"] for row in tl.unknowns(data)}
        self.assertIn("period_bound:childhood", keys)

    def test_derive_chrono_has_no_derived_span_to_consume(self):
        """v207's D3 still holds wherever a band IS derived (residence, age
        label) — there is simply nothing here for it to consume."""
        self.assertNotEqual(self.data()["periods"][0]["chrono_source"], "date")

    def test_a_floor_span_never_pins_the_eras_other_moments(self):
        """The bike is not from 1981 just because the birth is."""
        moments = self.moments(self.data())
        self.assertEqual(moments["Born in Redlands"]["date"].best, "1981-07-11")
        self.assertIsNone(moments["The bike with no brakes"]["date"])

    def test_an_explicit_span_still_wins_and_still_bounds(self):
        self.write_roster(dated=True)
        data = self.data()
        childhood = data["periods"][0]
        self.assertEqual(childhood["date"].best, "1984/1990")
        self.assertNotIn("date_derived", childhood)
        # …and an explicitly dated era DOES bound its moments, exactly as v205.
        self.assertEqual(self.moments(data)["The bike with no brakes"]["date"].best,
                         "1984/1990")

    def test_nothing_about_the_band_derivation_is_stored(self):
        self.data()
        self.assertEqual(list(self.root.glob("state/cross_dating*")), [])
        self.assertEqual(list(self.root.glob("state/band*")), [])


class AgeBandVaultTests(FounderBandTests):
    """The same vault, with the era NAMED after an age — a closed interval,
    so it bounds its moments the way an explicit span does."""

    def setUp(self):
        super().setUp()
        (self.root / "wiki" / "periods" / "childhood.md").unlink()
        # Nothing inside is dated, so the envelope rung above this one has
        # nothing to say and the age label is what the era has. (When an era
        # DOES carry dated moments they are the tighter, better-grounded claim,
        # which is exactly why they rank above the label — see BAND_RULES.)
        refs = self.write_one_per_source([
            {"title": "The bike with no brakes",
             "description": "I rode a bike with no brakes down the hill.",
             "when_hint": "", "anchor": None, "date": None},
            {"title": "The corner apartment",
             "description": "We rented the corner apartment for a while.",
             "when_hint": "", "anchor": None, "date": None},
        ], eras=("20s",))
        (self.root / "wiki" / "periods" / "my-20s.md").write_text(
            PAGE.format(title="My 20s", page_type="period", chrono=1, extra="",
                        sources=_sources(refs)),
            encoding="utf-8")
        (self.root / "state" / "entity_rosters" / "period.json").write_text(json.dumps({
            "version": 1, "type": "period", "entities": [
                {"name": "My 20s", "slug": "my-20s", "chrono": 1, "page_eligible": True},
            ]}), encoding="utf-8")

    def test_the_decade_join_dates_the_era_and_bounds_what_is_in_it(self):
        data = self.data()
        era = data["periods"][0]
        self.assertEqual(era["slug"], "my-20s")
        self.assertEqual(era["date"].best, "2001/2011")
        self.assertEqual(era["date_derived"]["join"], "age_label")
        self.assertEqual(era["date"].confidence, "certain")
        bike = self.moments(data)["The bike with no brakes"]
        self.assertEqual(bike["date"].best, "2001/2011")
        self.assertEqual(bike["date_derived"]["join"], "era")

    # The inherited founder assertions are about the envelope rung and do not
    # apply to a vault whose era carries an age label.
    test_childhood_is_not_dated_by_the_moments_inside_it = None
    test_the_coverage_is_published_under_its_own_name = None
    test_no_chip_claims_a_span_the_person_never_gave = None
    test_the_viewer_no_longer_shows_a_member_derived_span = None
    test_the_compiled_export_no_longer_carries_that_line = None
    test_a_floor_span_never_pins_the_eras_other_moments = None
    test_an_explicit_span_still_wins_and_still_bounds = None
    test_the_eras_bounds_stay_an_open_question = None
    test_derive_chrono_has_no_derived_span_to_consume = None


class ResidenceBandVaultTests(FounderBandTests):
    """A residence landmark bounds the era that contains the place page."""

    LANDMARKS = {
        "version": 1,
        "domains": {
            "birth": [{"label": "birth", "date": BIRTHDAY}],
            "residences": [{"label": "Mesa", "span": {"start": {"best": "1984"},
                                                      "end": {"best": "1990"}}}],
        },
    }

    def setUp(self):
        super().setUp()
        (self.root / "wiki" / "places" / "mesa.md").write_text(
            PAGE.format(title="Mesa", page_type="place", chrono=0, extra="",
                        sources=_sources(["A1", "A2"])),
            encoding="utf-8")

    def test_the_residence_landmark_dates_the_era_it_sits_in(self):
        era = self.data()["periods"][0]
        self.assertEqual(era["date"].best, "1984/1990")
        self.assertEqual(era["date_derived"]["join"], "residence_span")
        self.assertEqual(era["date_derived"]["provenance"], "from your years at Mesa")

    def test_the_dated_era_leaves_the_undated_unknowns(self):
        """A residence span IS a bound, so this era's `period_bound` question
        is genuinely answered — the rung v254 kept, doing its job."""
        keys = {row["key"] for row in tl.unknowns(self.data())}
        self.assertNotIn("period_bound:childhood", keys)

    test_childhood_is_not_dated_by_the_moments_inside_it = None
    test_the_coverage_is_published_under_its_own_name = None
    test_no_chip_claims_a_span_the_person_never_gave = None
    test_the_viewer_no_longer_shows_a_member_derived_span = None
    test_the_compiled_export_no_longer_carries_that_line = None
    test_a_floor_span_never_pins_the_eras_other_moments = None
    test_an_explicit_span_still_wins_and_still_bounds = None
    test_the_eras_bounds_stay_an_open_question = None
    test_derive_chrono_has_no_derived_span_to_consume = None


# ---------------------------------------------------------------------------
# v207 — the filing beat (design T3).
# ---------------------------------------------------------------------------


class GainSentenceTests(unittest.TestCase):
    """Exact composition. The sentence is short, warm, and never a report."""

    def test_the_four_shapes(self):
        self.assertEqual(xd.gain_sentence(1), "Got it — that dates one moment.")
        self.assertEqual(xd.gain_sentence(9), "Got it — that dates nine moments.")
        self.assertEqual(xd.gain_sentence(9, ["Childhood"]),
                         "Got it — that dates nine moments and your Childhood years.")
        self.assertEqual(xd.gain_sentence(0), "")

    def test_a_band_alone_is_still_worth_saying(self):
        self.assertEqual(xd.gain_sentence(0, ["Childhood"]),
                         "Got it — that dates your Childhood years.")

    def test_past_one_era_they_are_counted_not_listed(self):
        self.assertEqual(xd.gain_sentence(3, ["Childhood", "High School"]),
                         "Got it — that dates three moments and two of your eras.")

    def test_a_label_that_already_says_years_is_not_given_a_second_pair(self):
        self.assertEqual(xd.gain_sentence(0, ["The Yucaipa Years"]),
                         "Got it — that dates your Yucaipa Years.")

    def test_big_counts_read_as_digits(self):
        self.assertEqual(xd.gain_sentence(40), "Got it — that dates 40 moments.")

    def test_the_moment_clause_is_the_reading_rooms_own(self):
        """One definition: the Reading Room's sentence and the filing beat's
        can never drift into two wordings of the same true thing."""
        rr = load("reading_room")
        self.assertEqual(rr.placement_gain_sentence({"remaining": 14}, {"remaining": 5}),
                         "That dates nine moments.")
        self.assertIn(xd.moment_clause(9),
                      rr.placement_gain_sentence({"remaining": 14}, {"remaining": 5}))
        self.assertIn(xd.moment_clause(9), xd.gain_sentence(9))

    def test_nonsense_places_nothing_rather_than_raising(self):
        self.assertEqual(xd.gain_sentence(None), "")
        self.assertEqual(xd.gain_sentence("nine"), "")
        self.assertEqual(xd.gain_sentence(0, [""]), "")


class FilingGainSlotTests(unittest.TestCase):
    """The leaf slot, in both lanes that file."""

    LEAVES = ("interactions/timeline/prompt/turn-instructions.md",
              "interactions/landmarks/prompt/turn-instructions.md")

    def test_both_filing_lanes_carry_the_slot(self):
        for path in self.LEAVES:
            with self.subTest(path=path):
                self.assertIn("{filing_gain}", (ROOT / path).read_text(encoding="utf-8"))

    def test_an_absent_gain_leaves_the_prompt_byte_identical(self):
        """The whole direction is rendered WITH the sentence, so a turn that
        filed nothing substitutes the empty string and the leaf reads exactly
        as it did in v205 — no blank line, no dangling instruction."""
        for path in self.LEAVES:
            with self.subTest(path=path):
                leaf = (ROOT / path).read_text(encoding="utf-8")
                filled = leaf.replace("{filing_gain}", xd.render_filing_gain(""))
                self.assertEqual(filled, leaf.replace("{filing_gain}", ""))
                self.assertFalse(filled.endswith("\n\n"))
        self.assertEqual(xd.render_filing_gain(None), "")
        self.assertEqual(xd.render_filing_gain("   "), "")

    def test_a_present_gain_arrives_as_its_own_paragraph(self):
        rendered = xd.render_filing_gain("Got it — that dates nine moments.")
        self.assertTrue(rendered.startswith("\n\n**What their answer just placed.**"))
        self.assertIn("Got it — that dates nine moments.", rendered)
        for path in self.LEAVES:
            with self.subTest(path=path):
                leaf = (ROOT / path).read_text(encoding="utf-8")
                filled = leaf.replace("{filing_gain}", rendered)
                self.assertNotIn("{filing_gain}", filled)
                self.assertIn("What their answer just placed", filled)


class RecordGainTests(VaultFixture):
    """The count comes from the pass itself — promise equals delivery, said in
    a sentence instead of on a star."""

    LANDMARKS = {"version": 1, "domains": {}}

    def setUp(self):
        super().setUp()
        (self.root / "wiki" / "places" / "mesa.md").unlink()
        refs = self.write_one_per_source([
            {"title": "Born in Redlands",
             "description": "Born in Redlands while the family lived in the area.",
             "when_hint": "", "anchor": "dad attending ASU", "date": None},
            {"title": "Grandpa's letter", "description": "Grandpa sent a letter.",
             "when_hint": "when I was about five", "anchor": None, "date": None},
            {"title": "The bike with no brakes",
             "description": "I rode a bike with no brakes down the hill.",
             "when_hint": "", "anchor": None, "date": None},
        ], eras=("childhood",))
        self.write_period_page(refs, dated=False)
        (self.root / "state" / "entity_rosters" / "period.json").write_text(json.dumps({
            "version": 1, "type": "period", "entities": [
                {"name": "Childhood", "slug": "childhood", "chrono": 1,
                 "page_eligible": True},
            ]}), encoding="utf-8")

    def test_filing_the_birthday_says_exactly_what_it_placed(self):
        """v254: the era is no longer among what a birthday places, because a
        birthday no longer dates an era through its members. The sentence
        shrank to the truth — promise still equals delivery, which is the
        whole point of this class."""
        data = self.data()
        record = {"domain": "birth", "label": "birth", "date": BIRTHDAY}
        self.assertEqual(xd.record_gain(record, data),
                         {"moments": 2, "bands": []})
        self.assertEqual(xd.gain_sentence_for_record(record, data),
                         "Got it — that dates two moments.")

    def test_the_sentence_is_what_the_next_derivation_actually_delivers(self):
        """The reconciliation, in the shape the person hears it."""
        before = self.data()
        gain = xd.record_gain({"domain": "birth", "label": "birth", "date": BIRTHDAY},
                              before)
        self.store.write_text(json.dumps({
            "version": 1, "domains": {"birth": [{"label": "birth", "date": BIRTHDAY}]},
        }), encoding="utf-8")
        after = self.data()
        self.assertEqual(after["cross_dating"]["derived"], gain["moments"])
        self.assertEqual([row["label"] for row in after["cross_dating"]["bands"]["bands"]],
                         gain["bands"])

    def test_a_record_that_places_nothing_says_nothing(self):
        data = self.data()
        self.assertEqual(
            xd.gain_sentence_for_record({"domain": "schools", "label": "Mesa High"}, data), "")
        self.assertEqual(xd.gain_sentence_for_record(None, data), "")
        self.assertEqual(xd.gain_sentence_for_record({}, {}), "")

    def test_a_timeline_placement_no_longer_claims_to_bound_the_band(self):
        """v254: dating one moment inside an era says nothing about the era's
        years, so the beat says nothing about them either. An undated era with
        no residence and no age label has nothing this placement can move —
        and claiming otherwise is exactly what got `high-school` dated
        `1997/2021` on the founder's vault."""
        data = self.data()
        placed = {"source": "answers/A3.md",
                  "date": chrono.parse_edtf("1990", basis="stated").to_dict()}
        self.assertEqual(xd.record_gain(placed, data)["bands"], [])
        self.assertEqual(xd.gain_sentence_for_record(placed, data), "")

    def test_filing_a_residence_span_dates_the_era_that_holds_the_place(self):
        """The landmark shape the band ladder's first rung is built for — and
        the one `validate_landmark` actually emits, `span: {start, end}`."""
        (self.root / "wiki" / "places" / "mesa.md").write_text(
            PAGE.format(title="Mesa", page_type="place", chrono=0, extra="",
                        sources=_sources(["A1", "A2", "A3"])),
            encoding="utf-8")
        record = {"domain": "residences", "label": "Mesa",
                  "span": {"start": {"best": "1984"}, "end": {"best": "1990"}}}
        self.assertEqual(xd.gain_sentence_for_record(record, self.data()),
                         "Got it — that dates your Childhood years.")

    def test_computing_the_gain_never_touches_the_payload(self):
        data = self.data()
        snapshot = json.dumps(data, sort_keys=True, default=str)
        xd.gain_sentence_for_record({"domain": "birth", "label": "birth",
                                     "date": BIRTHDAY}, data)
        self.assertEqual(json.dumps(data, sort_keys=True, default=str), snapshot)


class ManifestTests(unittest.TestCase):
    def test_every_new_file_ships_in_framework_files(self):
        manifest = set(json.loads((SYSTEM / "version.json").read_text())["framework_files"])
        for path in ("system/cross_dating.py", "tests/test_cross_dating.py",
                     "docs/adr/0026-cross-dating.md"):
            with self.subTest(path=path):
                self.assertIn(path, manifest)

    def test_the_version_is_the_one_this_pass_shipped_in(self):
        version = json.loads((SYSTEM / "version.json").read_text())
        self.assertGreaterEqual(int(version["version"]), 207)


if __name__ == "__main__":
    unittest.main()
