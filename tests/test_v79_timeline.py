"""v79 — timeline data assembly + view + classify keyless path (issue #33)."""

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SYSTEM = ROOT / "system"
sys.path.insert(0, str(SYSTEM))


def load(name):
    spec = importlib.util.spec_from_file_location(name, SYSTEM / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


core = load("lifehug_core")
tl = load("timeline")


PERIOD_PAGE = """---
title: "{title}"
type: period
chrono: {chrono}
sources:
{sources}---

# {title}
"""

ENTITY_PAGE = """---
title: "{title}"
type: {type}
origin: mention
sources:
{sources}---

# {title}
"""

CHAPTERS_SOURCE = """---
title: "Life Chapters 2026"
type: "unprompted_story"
---

# The Chapters of My Life — 2026

## Chapter 1 — Moving
Growing up young in Arizona, moving a lot.
It ends when the moving stops.

## Chapter 2 — Home
The high school era in Mesa.
It ends when I leave for the mission.
"""


def _src_block(ids):
    return "".join(f'  - "answers/{i}.md"\n' for i in ids)


class TimelineFixture(unittest.TestCase):
    """Temp wiki tree with 2 periods, 3 entities, 1 chapters source, 1 classification."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        (root / "wiki" / "periods").mkdir(parents=True)
        (root / "wiki" / "people").mkdir()
        (root / "wiki" / "objects").mkdir()
        (root / "sources" / "manual").mkdir(parents=True)
        (root / "state" / "classifications").mkdir(parents=True)
        (root / "state" / "entity_rosters").mkdir()

        (root / "wiki" / "periods" / "childhood.md").write_text(
            PERIOD_PAGE.format(title="Childhood", chrono=1, sources=_src_block(["A2", "A5", "A14"])),
            encoding="utf-8")
        (root / "wiki" / "periods" / "high-school.md").write_text(
            PERIOD_PAGE.format(title="High School", chrono=2, sources=_src_block(["B3", "B7"])),
            encoding="utf-8")
        # the-cleats shares A5+A14 with Childhood → placed there, evidence shown
        (root / "wiki" / "objects" / "the-cleats.md").write_text(
            ENTITY_PAGE.format(title="The Cleats", type="object", sources=_src_block(["A5", "A14"])),
            encoding="utf-8")
        # katie shares B3 with High School, A14 with Childhood → max overlap tie broken by count
        (root / "wiki" / "people" / "katie.md").write_text(
            ENTITY_PAGE.format(title="Katie", type="person", sources=_src_block(["B3", "B7", "A14"])),
            encoding="utf-8")
        # orphan entity: no shared sources → unplaced
        (root / "wiki" / "people" / "trevor.md").write_text(
            ENTITY_PAGE.format(title="Trevor", type="person", sources=_src_block(["Z9"])),
            encoding="utf-8")
        (root / "sources" / "manual" / "2026-07-05-life-chapters-2026.md").write_text(
            CHAPTERS_SOURCE, encoding="utf-8")
        # one classification with two events: one placeable by source membership,
        # one undated + unplaceable
        (root / "state" / "classifications" / "answers-a5.json").write_text(json.dumps({
            "source_path": "answers/A5.md",
            "time_periods": [{"era": "Childhood", "approximate_dates": None, "life_stage": "child"}],
            "events": [
                {"description": "Dad bought the cleats", "when_hint": "sixth grade", "anchor": "the move to Yucaipa"},
            ],
        }), encoding="utf-8")
        (root / "state" / "classifications" / "answers-z9.json").write_text(json.dumps({
            "source_path": "answers/Z9.md",
            "time_periods": [],
            "events": [
                {"description": "Met Trevor somewhere", "when_hint": None, "anchor": None},
            ],
        }), encoding="utf-8")

        self._orig = (tl.WIKI_DIR, tl.MANUAL_SOURCES_DIR, tl.CLASSIFICATIONS_DIR, tl.STATE_DIR)
        tl.WIKI_DIR = root / "wiki"
        tl.MANUAL_SOURCES_DIR = root / "sources" / "manual"
        tl.CLASSIFICATIONS_DIR = root / "state" / "classifications"
        tl.STATE_DIR = root / "state"

    def tearDown(self):
        tl.WIKI_DIR, tl.MANUAL_SOURCES_DIR, tl.CLASSIFICATIONS_DIR, tl.STATE_DIR = self._orig
        self.tmp.cleanup()


class SpineTests(TimelineFixture):
    def test_periods_chrono_ordered_from_pages(self):
        periods = tl.load_periods()
        self.assertEqual([p["slug"] for p in periods], ["childhood", "high-school"])
        self.assertEqual(periods[0]["chrono"], 1)
        self.assertEqual(periods[0]["sources"], {"answers/A2.md", "answers/A5.md", "answers/A14.md"})

    def test_chapters_parsed(self):
        chapters = tl.load_chapters()
        self.assertEqual([c["title"] for c in chapters], ["Moving", "Home"])
        self.assertIn("It ends when the moving stops.", chapters[0]["body"])

    def test_chapter_alignment_by_period_name(self):
        data = tl.timeline_data()
        # Chapter 2 "Home" says "high school era" → aligns to high-school
        aligned = {c["title"]: c["aligned_period"] for c in data["chapters"]}
        self.assertEqual(aligned["Home"], "high-school")


class LineupTests(TimelineFixture):
    def test_entity_placed_by_max_source_overlap_with_evidence(self):
        data = tl.timeline_data()
        childhood = {r["slug"]: r for r in data["entity_lineup"]["childhood"]}
        self.assertIn("the-cleats", childhood)
        self.assertEqual(childhood["the-cleats"]["evidence"], ["A14", "A5"])

    def test_multi_period_entity_gets_also_in(self):
        data = tl.timeline_data()
        hs = {r["slug"]: r for r in data["entity_lineup"]["high-school"]}
        self.assertIn("katie", hs)                      # 2 shared beats 1
        self.assertIn("childhood", hs["katie"]["also_in"])

    def test_orphan_entity_unplaced(self):
        data = tl.timeline_data()
        self.assertEqual([r["slug"] for r in data["unplaced_entities"]], ["trevor"])


class EventTests(TimelineFixture):
    def test_event_placed_by_source_membership(self):
        data = tl.timeline_data()
        childhood_events = data["event_lineup"]["childhood"]
        self.assertEqual(len(childhood_events), 1)
        self.assertEqual(childhood_events[0]["when_hint"], "sixth grade")
        self.assertEqual(childhood_events[0]["anchor"], "the move to Yucaipa")

    def test_unplaceable_event_lands_in_bucket(self):
        data = tl.timeline_data()
        self.assertEqual(len(data["unplaced_events"]), 1)
        self.assertEqual(data["unplaced_events"][0]["description"], "Met Trevor somewhere")

    def test_era_keyword_fallback(self):
        events = [{"description": "x", "when_hint": "back in high school", "anchor": "",
                   "source": "answers/QQ.md", "source_short": "QQ", "eras": []}]
        periods = tl.load_periods()
        placed, unplaced = tl.place_events(events, periods)
        self.assertEqual(len(placed["high-school"]), 1)
        self.assertEqual(unplaced, [])


class GapTests(TimelineFixture):
    def test_gaps_flag_eventless_periods_and_unplaced(self):
        data = tl.timeline_data()
        hs_gaps = {g["kind"] for g in data["gaps_by_period"].get("high-school", [])}
        self.assertIn("no_events", hs_gaps)             # only childhood has an event
        global_kinds = {g["kind"] for g in data["global_gaps"]}
        self.assertIn("unplaced_events", global_kinds)
        self.assertIn("unplaced_entities", global_kinds)


class ViewSmokeTests(TimelineFixture):
    def test_view_renders_with_data(self):
        sw = load("serve_wiki")
        sys.modules["timeline"] = tl  # view imports by name; use our patched module
        title, body, wide = sw.view_timeline()
        self.assertEqual(title, "Timeline")
        self.assertIn("Childhood", body)
        self.assertIn("The Cleats", body)                # entity chip
        self.assertIn("sixth grade", body)               # dated event
        self.assertIn("Unplaced", body)                  # bucket rendered
        self.assertIn("Ch.2", body)                      # chapters band
        self.assertIn("tl-gap", body)                    # gap cards
        self.assertFalse(wide)

    def test_periods_are_collapsible(self):
        sw = load("serve_wiki")
        sys.modules["timeline"] = tl
        _, body, _ = sw.view_timeline()
        # v80: each period is a <details>, collapsed by default, with a
        # counts line in the summary so the folded row stays informative.
        self.assertIn("<details class='tl-period'>", body)
        self.assertNotIn("<details class='tl-period' open", body)
        self.assertIn("tl-summary-counts", body)
        self.assertIn("moment(s)", body)
        self.assertIn("expand all", body)
        self.assertIn("collapse all", body)
        # v81: the unplaced bucket is collapsible too, and expand/collapse
        # all reaches it.
        self.assertIn("<details class='tl-unplaced'>", body)
        self.assertIn("details.tl-period,details.tl-unplaced", body)

    def test_view_renders_empty_tree(self):
        with tempfile.TemporaryDirectory() as empty:
            orig = tl.WIKI_DIR, tl.STATE_DIR, tl.MANUAL_SOURCES_DIR, tl.CLASSIFICATIONS_DIR
            tl.WIKI_DIR = Path(empty) / "wiki"
            tl.STATE_DIR = Path(empty) / "state"
            tl.MANUAL_SOURCES_DIR = Path(empty) / "sources"
            tl.CLASSIFICATIONS_DIR = Path(empty) / "clf"
            try:
                sw = load("serve_wiki")
                sys.modules["timeline"] = tl
                title, body, _ = sw.view_timeline()
            finally:
                (tl.WIKI_DIR, tl.STATE_DIR, tl.MANUAL_SOURCES_DIR, tl.CLASSIFICATIONS_DIR) = orig
            self.assertIn("No period pages yet", body)


class ClassifyKeylessTests(unittest.TestCase):
    def test_from_response_round_trip_no_candidates(self):
        cls = load("classify_story")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            answers = root / "answers"
            answers.mkdir()
            src = answers / "T1.md"
            src.write_text("---\ntitle: \"T1\"\n---\n\n# T1\n\nA story about sixth grade.\n",
                           encoding="utf-8")
            clf_dir = root / "state" / "classifications"
            response = root / "resp.json"
            response.write_text(json.dumps({
                "people": [], "places": [], "themes": ["family"],
                "time_periods": [{"era": "childhood", "approximate_dates": None, "life_stage": "child"}],
                "events": [{"description": "d", "when_hint": "sixth grade", "anchor": None}],
                "candidate_questions": [{"text": "should be ignored?", "story_function": "scene", "priority": 0.9}],
            }), encoding="utf-8")

            live = sys.modules["classify_story"]
            orig = (live.REPO_DIR, live.CLASSIFICATIONS_DIR, live.ANSWERS_DIR,
                    live.QUESTION_CANDIDATES_FILE)
            live.REPO_DIR = root
            live.CLASSIFICATIONS_DIR = clf_dir
            live.ANSWERS_DIR = answers
            live.QUESTION_CANDIDATES_FILE = root / "state" / "question_candidates.json"
            try:
                rc = live.classify_file(src, model="external-agent",
                                        skip_candidates=True,
                                        precomputed_result=json.loads(response.read_text()))
            finally:
                (live.REPO_DIR, live.CLASSIFICATIONS_DIR, live.ANSWERS_DIR,
                 live.QUESTION_CANDIDATES_FILE) = orig
            self.assertEqual(rc, 0)
            written = list(clf_dir.glob("*.json"))
            self.assertEqual(len(written), 1)
            data = json.loads(written[0].read_text())
            self.assertEqual(data["events"][0]["when_hint"], "sixth grade")
            self.assertEqual(data["candidate_question_ids"], [])  # suppressed
            self.assertFalse((root / "state" / "question_candidates.json").exists())


if __name__ == "__main__":
    unittest.main()
