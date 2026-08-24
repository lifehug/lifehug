"""v195 / ADR 0024 — unknowns, leverage, keystones, and the deferred memory.

Every gap becomes a Play-able unknown carrying the playbook's cheapest probe;
a dated hole between dated eras is the new `era_gap` kind; leverage counts
what one anchor would resolve; keystones are capped at two; and a deferred
unknown goes quiet without ever being counted as outstanding.

Synthetic data only; NEVER references ~/Workspace/dave.
"""

from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SYSTEM = ROOT / "system"
sys.path.insert(0, str(SYSTEM))

import chronology as chrono  # noqa: E402
import timeline_interaction as ti  # noqa: E402


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
type: {page_type}
chrono: {chrono}
{extra}sources:
{sources}---

# {title}
"""


def _sources(refs):
    return "".join(f'  - "answers/{ref}.md"\n' for ref in refs)


class UnknownsFixture(unittest.TestCase):
    """Two dated eras twelve years apart with nothing between them, one
    undated era, one place, and two events — one dated, one not."""

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
        (root / "wiki" / "periods" / "my-30s.md").write_text(
            PAGE.format(title="My 30s", page_type="period", chrono=2,
                        extra="date: 2002/2012\n", sources=_sources(["A2"])),
            encoding="utf-8")
        (root / "wiki" / "periods" / "the-lost-years.md").write_text(
            PAGE.format(title="The Lost Years", page_type="period", chrono=3,
                        extra="", sources=_sources([])),
            encoding="utf-8")
        (root / "wiki" / "places" / "mesa.md").write_text(
            PAGE.format(title="Mesa", page_type="place", chrono=0,
                        extra="date: 1984/1990\n", sources=_sources(["A1"])),
            encoding="utf-8")
        (root / "state" / "entity_rosters" / "period.json").write_text(json.dumps({
            "version": 1, "type": "period", "entities": [
                {"name": "Childhood", "slug": "childhood", "chrono": 1,
                 "page_eligible": True, "date": "1984/1990"},
                {"name": "My 30s", "slug": "my-30s", "chrono": 2,
                 "page_eligible": True, "date": "2002/2012"},
                {"name": "The Lost Years", "slug": "the-lost-years", "chrono": 3,
                 "page_eligible": True},
            ]}), encoding="utf-8")
        (root / "state" / "classifications" / "answers-a1.json").write_text(json.dumps({
            "source_path": "answers/A1.md",
            "events": [
                {"title": "The move to Mesa", "description": "We moved to Mesa.",
                 "when_hint": "", "anchor": None, "date": {"stated": "1984"}},
                {"title": "The bike with no brakes",
                 "description": "I rode a bike with no brakes.",
                 "when_hint": "", "anchor": None, "date": None},
            ]}), encoding="utf-8")
        (root / "state" / "classifications" / "answers-a2.json").write_text(json.dumps({
            "source_path": "answers/A2.md",
            "events": [
                {"title": "The coast house", "description": "We bought the coast house.",
                 "when_hint": "", "anchor": None, "date": {"stated": "2008"}},
            ]}), encoding="utf-8")

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
        self.data = tl.timeline_data()

    def tearDown(self):
        for name, value in self._orig.items():
            setattr(tl, name, value)
        self.tmp.cleanup()


class UnknownRecordTests(UnknownsFixture):
    def test_every_gap_becomes_exactly_one_play_able_unknown(self):
        rows = self.data["unknowns"]
        self.assertTrue(rows)
        self.assertEqual(len(rows), len({row["key"] for row in rows}))
        for row in rows:
            self.assertIn(row["kind"], tl.UNKNOWN_KINDS)
            self.assertTrue(row["label"])
            self.assertIn(row["probe"]["step"], ti.PLAYBOOK_ORDER)
            self.assertTrue(row["probe"]["text"])

    def test_the_keys_are_stable_and_content_derived(self):
        first = {row["key"] for row in tl.unknowns(self.data)}
        second = {row["key"] for row in tl.unknowns(self.data)}
        self.assertEqual(first, second)
        self.assertIn("period_bound:the-lost-years", first)

    def test_no_unknown_is_ever_an_aggregate_count(self):
        """Owner-set, 2026-08-23: "116 moment(s) I can't place in any period"
        is a number, not a question. Every unknown is one subject."""
        for row in tl.unknowns(self.data):
            with self.subTest(key=row["key"]):
                self.assertNotIn(row["kind"], tl.LEDGER_GAP_KINDS)
                self.assertNotRegex(row["label"], r"^\d+ (moment|page)")
                self.assertIn("?", row["probe"]["text"] + "?")

    def test_the_counts_move_to_the_ledger(self):
        ledger = self.data["unknown_ledger"]
        self.assertIn("unplaced_moments", ledger)
        self.assertIn("gap_notes", ledger)
        self.assertEqual(set(ledger["gap_notes"]), set(tl.LEDGER_GAP_KINDS))

    def test_an_undated_moment_is_its_own_unknown_named_by_its_title(self):
        rows = [r for r in tl.unknowns(self.data) if r["kind"] == "moment"]
        self.assertTrue(rows)
        for row in rows:
            self.assertTrue(row["label"])
            self.assertIn(row["label"], row["probe"]["text"])

    def test_the_page_is_capped_and_leverage_ordered(self):
        rows = [{"key": f"k{n}", "kind": "moment", "label": f"m{n}",
                 "probe": {"cost": 1}} for n in range(50)]
        index = {"period:x": {"k7", "k8", "k9"}, "period:y": {"k1"}}
        offered = tl.offered_unknowns(rows, index, limit=3)
        self.assertEqual([row["key"] for row in offered], ["k7", "k8", "k9"])
        self.assertEqual(offered[0]["leverage"], 3)
        self.assertEqual(tl.UNKNOWNS_PAGE_CAP, 30)

    def test_an_era_gap_is_emitted_between_two_dated_eras(self):
        keys = {row["key"] for row in self.data["unknowns"]}
        self.assertIn("era_gap:childhood:my-30s", keys)
        row = next(r for r in self.data["unknowns"] if r["key"] == "era_gap:childhood:my-30s")
        self.assertEqual(row["years"], [1991, 2001])
        self.assertIn("1991–2001", row["label"])

    def test_no_era_gap_when_a_neighbour_is_undated(self):
        periods = [{"slug": "a", "name": "A", "date": chrono.parse_edtf("1984/1990")},
                   {"slug": "b", "name": "B", "date": None}]
        self.assertEqual(tl.era_gaps(periods, {}), [])

    def test_no_era_gap_when_the_eras_touch(self):
        periods = [{"slug": "a", "name": "A", "date": chrono.parse_edtf("1984/1990")},
                   {"slug": "b", "name": "B", "date": chrono.parse_edtf("1991/1999")}]
        self.assertEqual(tl.era_gaps(periods, {}), [])

    def test_an_occupied_hole_is_not_a_gap(self):
        periods = [{"slug": "a", "name": "A", "date": chrono.parse_edtf("1984/1990")},
                   {"slug": "b", "name": "B", "date": chrono.parse_edtf("2002/2012")}]
        lineup = {"a": [{"date": chrono.parse_edtf("1995"), "source_short": "A9"}]}
        self.assertEqual(tl.era_gaps(periods, lineup), [])


class LeverageTests(UnknownsFixture):
    def test_a_period_anchor_resolves_its_own_unknowns_and_the_eras_it_touches(self):
        index = tl.dependency_index(self.data)
        self.assertIn("period:childhood", index)
        self.assertIn("era_gap:childhood:my-30s", index["period:childhood"])
        self.assertGreater(tl.leverage("period:childhood", index), 0)

    def test_leverage_of_an_unknown_anchor_is_zero(self):
        self.assertEqual(tl.leverage("period:nowhere", tl.dependency_index(self.data)), 0)

    def test_keystones_are_capped_at_two_and_ordered_by_leverage(self):
        rows = self.data["keystones"]
        self.assertLessEqual(len(rows), tl.KEYSTONE_CAP)
        self.assertEqual(tl.KEYSTONE_CAP, 2)
        self.assertEqual([r["leverage"] for r in rows],
                         sorted((r["leverage"] for r in rows), reverse=True))
        for row in rows:
            self.assertTrue(row["probe"]["text"])

    def test_every_keystone_carries_the_identity_it_is_asked_under(self):
        """v196: a keystone is matched by exact id, never by adjacency."""
        rows = self.data["keystones"]
        self.assertTrue(rows)
        for row in rows:
            self.assertTrue(row["question_id"].startswith("tl:"))
            self.assertNotIn("/", row["question_id"])
            self.assertEqual(row["unknown_keys"], row["resolves"])
            self.assertEqual(row["leverage"], len(row["unknown_keys"]))
            self.assertIsInstance(row["anchors"], list)

    def test_an_anchor_slug_with_a_path_separator_is_sanitized_at_the_mint(self):
        self.assertEqual(ti.keystone_question_id("entity:person/friend"),
                         "tl:person-friend")

    def test_asking_for_no_keystones_returns_none(self):
        self.assertEqual(tl.keystones(self.data, n=0), [])


class ProbeGoldenTests(unittest.TestCase):
    """Owner-set, 2026-08-23 — "I need a question."

    One golden per unknown kind, unanchored and anchored, pinned exactly. If a
    probe ever goes abstract again ("tell me what happened") for a subject we
    can name, one of these fails.
    """

    ANCHOR = [{"key": "san-diego", "label": "the move to San Diego",
               "kind": "residence", "date": "1996"}]

    GOLDENS = {
        "moment": (
            {"kind": "moment", "label": "Dad lost the truck keys while camping"},
            "Tell me about Dad lost the truck keys while camping — just the "
            "moment itself, however it comes.",
            "Dad lost the truck keys while camping — was that before or after "
            "the move to San Diego?",
        ),
        "period_bound": (
            {"kind": "period_bound", "label": "the Yucaipa years"},
            "When did the Yucaipa years begin and end?",
            "When did the Yucaipa years end — before or after the move to San Diego?",
        ),
        "place_span": (
            {"kind": "place_span", "label": "the house on Third Street"},
            "When did you live in the house on Third Street — moving in to moving out?",
            "Were you living in the house on Third Street before or after the "
            "move to San Diego?",
        ),
        "era_gap": (
            {"kind": "era_gap", "label": "1991–2001 — nothing placed here yet.",
             "between": ["the-yucaipa-years", "the-denver-years"]},
            "What was going on in your life in the stretch between the yucaipa "
            "years and the denver years?",
            "Between the yucaipa years and the denver years — where were you "
            "living by then?",
        ),
        "date_contradiction": (
            {"kind": "date_contradiction", "label": "the christening photograph"},
            "Two accounts put the christening photograph in different places in "
            "time — which one feels right to you?",
            "Two accounts disagree about the christening photograph — was it "
            "before or after the move to San Diego?",
        ),
    }

    #: v202: two kinds are SELF-PROBING — `landmarks_interaction` mints them
    #: already carrying the ladder's own subject-named question ("What year was
    #: Jackie born?"), which `choose_probe` cannot see because it has no view
    #: of the question set. A KIND_OPENERS entry for them would be a second,
    #: never-used wording of the same question, so they are pinned against
    #: their BUILDERS instead. `timeline.unknowns` is what keeps them: it skips
    #: `choose_probe` for any row that arrived with a probe text of its own.
    SELF_PROBING_KINDS = ("landmark_subject", "residence_gap")

    SELF_PROBING_LANDMARKS = {
        "family": [{"domain": "family", "label": "Jackie", "who": "Jackie",
                    "relation": "sibling"}],
        "residences": [
            {"label": "Mesa", "city": "Mesa", "address": "1 Mesa Rd",
             "span": {"start": {"best": "1988", "earliest": "1988",
                                "latest": "1988", "granularity": "year",
                                "confidence": "approximate", "basis": "stated"},
                      "end": {"best": "1992", "earliest": "1992",
                              "latest": "1992", "granularity": "year",
                              "confidence": "approximate", "basis": "stated"}}},
            {"label": "Yucaipa", "city": "Yucaipa", "address": "2 Oak St",
             "span": {"start": {"best": "1995", "earliest": "1995",
                                "latest": "1995", "granularity": "year",
                                "confidence": "approximate", "basis": "stated"},
                      "end": {"best": "2001", "earliest": "2001",
                              "latest": "2001", "granularity": "year",
                              "confidence": "approximate", "basis": "stated"}}},
        ],
    }

    def test_every_unknown_kind_has_a_concrete_probe(self):
        self.assertEqual(set(self.GOLDENS) | set(self.SELF_PROBING_KINDS),
                         set(tl.UNKNOWN_KINDS))
        for kind, (row, bare, anchored) in self.GOLDENS.items():
            with self.subTest(kind=kind):
                self.assertEqual(ti.choose_probe(row)["text"], bare)
                self.assertEqual(
                    ti.choose_probe(row, anchors=self.ANCHOR)["text"], anchored)
                self.assertIn("?", anchored)
                self.assertEqual(anchored.count("?"), 1)
                self.assertNotIn("what year", anchored.lower())

    def test_the_self_probing_kinds_bring_their_own_named_question(self):
        """v202: the landmark set's own unknowns arrive with the ladder's
        exact, subject-named wording, and `unknowns()` does not replace it."""
        rows = {row["kind"]: row
                for row in tl.unknowns({}, landmarks=self.SELF_PROBING_LANDMARKS)}
        for kind in self.SELF_PROBING_KINDS:
            with self.subTest(kind=kind):
                text = rows[kind]["probe"]["text"]
                self.assertTrue(text.endswith("?"))
                self.assertEqual(text.count("?"), 1)
        self.assertEqual(rows["landmark_subject"]["probe"]["text"],
                         "What year was Jackie born?")
        self.assertEqual(
            rows["residence_gap"]["probe"]["text"],
            "Where did you live between Mesa and Yucaipa, around 1992–1995?")

    def test_every_keystone_anchor_kind_asks_a_real_question(self):
        goldens = {
            "period:the-yucaipa-years": (
                "When did the Yucaipa years begin and end?",
                "When did the Yucaipa years begin — before or after the move to "
                "San Diego?"),
            "entity:charlee": (
                "When did Charlee first come into your life?",
                "Did Charlee come into your life before or after the move to "
                "San Diego?"),
            "event:childhood:A9": (
                "When did the barn fire happen?",
                "the barn fire — was that before or after the move to San Diego?"),
        }
        labels = {"period:the-yucaipa-years": "the Yucaipa years",
                  "entity:charlee": "Charlee",
                  "event:childhood:A9": "the barn fire"}
        for anchor_key, (bare, anchored) in goldens.items():
            with self.subTest(anchor=anchor_key):
                self.assertEqual(
                    ti.keystone_probe(anchor_key, label=labels[anchor_key])["text"], bare)
                self.assertEqual(
                    ti.keystone_probe(anchor_key, label=labels[anchor_key],
                                      anchors=self.ANCHOR)["text"], anchored)


class KeystoneQuestionTests(UnknownsFixture):
    def test_a_starred_keystone_carries_a_question_about_its_own_anchor(self):
        for row in self.data["keystones"]:
            with self.subTest(anchor=row["anchor"]):
                self.assertIn("?", row["probe"]["text"])
                subject = row["label"].split(" —")[0]
                self.assertIn(subject.lower(), row["probe"]["text"].lower())


class TimelinePlanTests(UnknownsFixture):
    def test_the_plan_orders_by_leverage_then_playbook_cost(self):
        plan = ti.build_timeline_plan(self.data)
        offered = plan["offered"]
        self.assertTrue(offered)
        keys = [(not row["starred"], -row["leverage"], row["probe"]["cost"]) for row in offered]
        self.assertEqual(keys, sorted(keys))

    def test_era_scoping_keeps_only_that_eras_unknowns(self):
        plan = ti.build_timeline_plan(self.data, era="the-lost-years")
        self.assertTrue(plan["unknowns"])
        for row in plan["unknowns"]:
            self.assertIn("the-lost-years",
                          [row.get("period")] + list(row.get("between") or []))

    def test_the_target_is_a_timeline_target_not_an_arc_walk_one(self):
        self.assertEqual(ti.build_timeline_plan(self.data)["target"]["kind"], "timeline")

    def test_describe_renders_every_offered_row_with_its_probe(self):
        lines = "\n".join(ti.describe_timeline_plan(ti.build_timeline_plan(self.data)))
        self.assertIn("Timeline plan", lines)
        self.assertIn("probe (", lines)


class PlannerTimelineTests(unittest.TestCase):
    """v196: ONE knob, and no adjacency anywhere."""

    def setUp(self):
        self.qp = load("question_planner")

    def test_the_one_knob_ships_with_a_conservative_default(self):
        self.assertEqual(self.qp.DEFAULT_LANE_POLICY["timeline_leverage_per_story"], 6)

    def test_the_adjacency_nudge_is_gone(self):
        """The defect in lifehug/lifehug-platform#586: a bank question whose
        focus merely resembled a keystone slug was lifted and starred while
        never asking for a date."""
        self.assertNotIn("leverage_boost", self.qp.DEFAULT_LANE_POLICY)
        self.assertFalse(hasattr(self.qp, "current_keystone_slugs"))
        self.assertFalse(hasattr(tl, "keystone_slugs"))

    def test_the_group_cap_is_one_timeline_question_a_week(self):
        self.assertEqual(self.qp.max_counts(8, self.qp.GROUP_CAPS)["timeline"], 1)
        self.assertEqual(self.qp.max_counts(40, self.qp.GROUP_CAPS)["timeline"], 1)

    def test_no_timeline_probe_leaves_the_week_byte_identical(self):
        without = self.qp.build_queue(limit=8, arc_max=2, seed=11)
        with_empty = self.qp.build_queue(limit=8, arc_max=2, seed=11, timeline_probes={})
        self.assertEqual([q["question_id"] for q in without["queue"]],
                         [q["question_id"] for q in with_empty["queue"]])
        self.assertEqual(with_empty["allocation"]["leverage"]["minted"], [])
        self.assertEqual(with_empty["allocation"]["leverage"]["queued"], [])

    def test_an_unknown_probe_id_marks_nothing(self):
        data = self.qp.build_queue(limit=8, arc_max=2, seed=11, timeline_probes={
            "definitely-not-a-real-question": {"question_id": "tl:x", "leverage": 40}})
        self.assertEqual(data["allocation"]["leverage"]["minted"], [])
        self.assertEqual(data["allocation"]["leverage"]["per_story"], 6)

    def test_the_guarded_reads_never_raise(self):
        original = sys.modules.get("timeline_interaction")
        sys.modules["timeline_interaction"] = object()  # no index, no minter
        try:
            self.assertEqual(self.qp.current_timeline_probes(), {})
            self.assertEqual(self.qp.mint_keystone_questions(), [])
        finally:
            if original is None:
                sys.modules.pop("timeline_interaction", None)
            else:
                sys.modules["timeline_interaction"] = original


class KeystoneMintTests(unittest.TestCase):
    """The minted keystone question is an ORDINARY bank row (v196, ruling 3)."""

    KEYSTONE = {
        "anchor": "period:mesa",
        "question_id": "tl:mesa",
        "label": "the Mesa years",
        "leverage": 14,
        "unknown_keys": ["a", "b"],
        "resolves": ["a", "b"],
        "anchors": [{"key": "birth", "label": "when you were born",
                     "kind": "birth", "date": "1979"}],
        "probe": {"step": "residence", "cost": 2,
                  "text": "Where were you living when that happened?"},
    }
    BANK = "# Questions\n\n## A: Origins\n\n- [ ] A1: Where does your story start?\n"

    def test_the_row_is_a_real_bank_row_in_the_timeline_group(self):
        row = ti.mint_keystone_question(self.KEYSTONE, next_question_id=lambda cat: f"{cat}1")
        self.assertEqual(row["id"], "T1")
        self.assertEqual(row["group"], "timeline")
        self.assertEqual(row["text"], self.KEYSTONE["probe"]["text"])
        self.assertIn("- [ ] T1:", row["line"])
        self.assertIn("timeline_probe: tl:mesa", row["line"])

    def test_the_bank_text_round_trips_through_the_parsers(self):
        row = ti.mint_keystone_question(self.KEYSTONE, next_question_id=lambda cat: f"{cat}1")
        text = ti.insert_keystone_question(self.BANK, row)
        from lifehug_core import parse_categories, parse_questions  # noqa: PLC0415
        self.assertEqual(parse_categories(text)["T"]["group"], "timeline")
        self.assertIn("T1", [q["id"] for q in parse_questions(text)])
        index = ti.timeline_probe_index(text)
        self.assertEqual(index["T1"]["question_id"], "tl:mesa")
        self.assertEqual(index["T1"]["leverage"], 14)
        self.assertFalse(index["T1"]["answered"])

    def test_an_answered_row_reads_as_answered_so_it_is_never_re_asked(self):
        row = ti.mint_keystone_question(self.KEYSTONE, next_question_id=lambda cat: f"{cat}1")
        text = ti.insert_keystone_question(self.BANK, row).replace("- [ ] T1:", "- [x] T1:")
        self.assertTrue(ti.timeline_probe_index(text)["T1"]["answered"])

    def test_a_keystone_with_no_probe_mints_nothing(self):
        self.assertIsNone(ti.mint_keystone_question(
            {"anchor": "period:mesa"}, next_question_id=lambda cat: "T1"))

    def test_the_section_is_created_once(self):
        row = ti.mint_keystone_question(self.KEYSTONE, next_question_id=lambda cat: f"{cat}1")
        once = ti.insert_keystone_question(self.BANK, row)
        twice = ti.insert_keystone_question(once, {**row, "id": "T2",
                                                   "line": row["line"].replace("T1", "T2")})
        self.assertEqual(twice.count("## T: Timeline"), 1)
        self.assertEqual(len(ti.timeline_probe_index(twice)), 2)


if __name__ == "__main__":
    unittest.main()
