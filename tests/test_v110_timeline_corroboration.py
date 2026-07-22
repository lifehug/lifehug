"""v110 — timeline corroboration from connector date evidence (issue #44);
v111 — calibrated against live data.

Connector date evidence ({date, entity, kind, message_id}) lines up against
periods (roster name/slug/alias token-subset) and events (entity tokens within
the moment's DESCRIPTION text): windowed corroboration badges render on the
view and the wiki/timeline.md export; a tight out-of-window cluster against
the story's own dates surfaces as date_contradiction gaps and connector-mined
question candidates. No evidence file → the timeline renders exactly as
before.
"""

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
    """Load a private copy of system/<name>.py WITHOUT clobbering the shared
    sys.modules entry — other test modules bind the canonical module at import
    time, and replacing it mid-suite splits state across two module objects."""
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


core = load("lifehug_core")
tl = load("timeline")
tcorr = load("timeline_corroboration")

PERIOD_PAGE = """---
title: "{title}"
type: period
chrono: {chrono}
sources:
{sources}---

# {title}
"""


def _src_block(ids):
    return "".join(f'  - "answers/{i}.md"\n' for i in ids)


def _evidence(date, entity, kind="billing", mid=None):
    return {"date": date, "entity": entity, "kind": kind,
            "message_id": mid or f"m-{entity}-{date}"}


ASU_RECORDS = [
    _evidence("2010-08-15", "asu", "enrollment", "m1"),
    _evidence("2011-08-05", "asu", "billing", "m2"),
    _evidence("2011-12-01", "asu", "billing", "m2b"),
    _evidence("2013-05-10", "asu", "institutional", "m3"),
]
CHASE_RECORD = _evidence("2012-03-01", "chase", "billing", "m4")


class CorroborationFixture(unittest.TestCase):
    """Temp tree: one period (College, alias ASU, approximate_dates
    2010–2013), two classifier events mentioning ASU — one corroborated
    (when_hint 2011), one contradicted (when_hint 2004) — and a gmail date
    evidence file with 3 asu records + 1 unmatched chase record."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.root = root
        (root / "wiki" / "periods").mkdir(parents=True)
        (root / "sources" / "manual").mkdir(parents=True)
        (root / "state" / "classifications").mkdir(parents=True)
        (root / "state" / "entity_rosters").mkdir()
        (root / "state" / "connectors").mkdir()

        (root / "wiki" / "periods" / "college.md").write_text(
            PERIOD_PAGE.format(title="College", chrono=1, sources=_src_block(["A1"])),
            encoding="utf-8")
        self.write_roster(approximate_dates="2010–2013")
        (root / "state" / "classifications" / "answers-a1.json").write_text(json.dumps({
            "source_path": "answers/A1.md",
            "time_periods": [{"era": "college", "approximate_dates": None, "life_stage": "student"}],
            "events": [
                {"description": "Moved into the ASU dorms", "when_hint": "2011",
                 "anchor": "the move to Tempe"},
                {"description": "First ASU football game", "when_hint": "2004",
                 "anchor": None},
            ],
        }), encoding="utf-8")
        self.write_evidence(ASU_RECORDS + [CHASE_RECORD])

        self._orig = (tl.WIKI_DIR, tl.MANUAL_SOURCES_DIR, tl.CLASSIFICATIONS_DIR,
                      tl.STATE_DIR, tl.PLACEMENTS_FILE)
        tl.WIKI_DIR = root / "wiki"
        tl.MANUAL_SOURCES_DIR = root / "sources" / "manual"
        tl.CLASSIFICATIONS_DIR = root / "state" / "classifications"
        tl.STATE_DIR = root / "state"
        tl.PLACEMENTS_FILE = root / "state" / "timeline_placements.json"

    def tearDown(self):
        (tl.WIKI_DIR, tl.MANUAL_SOURCES_DIR, tl.CLASSIFICATIONS_DIR,
         tl.STATE_DIR, tl.PLACEMENTS_FILE) = self._orig
        self.tmp.cleanup()

    def write_roster(self, approximate_dates="2010–2013", aliases=None):
        payload = {"version": 1, "type": "period", "entities": [{
            "name": "College", "slug": "college",
            "aliases": aliases if aliases is not None else ["ASU", "Arizona State"],
            "chrono": 1, "page_eligible": True,
            "approximate_dates": approximate_dates,
        }]}
        (self.root / "state" / "entity_rosters" / "period.json").write_text(
            json.dumps(payload), encoding="utf-8")

    def write_evidence(self, records):
        (self.root / "state" / "connectors" / "gmail_date_evidence.json").write_text(
            json.dumps({"version": 1, "updated_at": "2026-07-21T00:00:00Z",
                        "evidence": records}), encoding="utf-8")

    def remove_evidence(self):
        (self.root / "state" / "connectors" / "gmail_date_evidence.json").unlink()

    def event_by_desc(self, data, needle):
        for slug, rows in data["event_lineup"].items():
            for event in rows:
                if needle in event["description"]:
                    return slug, event
        raise AssertionError(f"event not found: {needle}")


class PeriodBadgeTests(CorroborationFixture):
    def test_period_badge_computed_with_range(self):
        data = tl.timeline_data()
        self.assertTrue(data["corroboration"]["available"])
        self.assertEqual(data["corroboration"]["total"], 5)
        badge = data["periods"][0].get("corroboration")
        self.assertIsNotNone(badge)
        # 4 asu records matched, all inside the stated 2010–2013 range; the
        # chase record matched nothing.
        self.assertEqual(badge["count"], 4)
        self.assertEqual(badge["entities"], [
            {"entity": "asu", "count": 4, "first": 2010, "last": 2013}])
        self.assertEqual((badge["first"], badge["last"]), (2010, 2013))
        self.assertEqual(badge["status"], "corroborated")

    def test_badge_counts_are_per_matched_entity_not_global(self):
        data = tl.timeline_data()
        badge = data["periods"][0]["corroboration"]
        # the ledger holds 5 records total — the badge reports only asu's 4.
        self.assertEqual(badge["count"], 4)
        self.assertEqual(sum(e["count"] for e in badge["entities"]), 4)

    def test_badge_text_format(self):
        data = tl.timeline_data()
        self.assertEqual(tcorr.badge_text(data["periods"][0]["corroboration"]),
                         "asu ×4 · 2010–2013")


class EventBadgeTests(CorroborationFixture):
    def test_event_badge_corroborated_by_when_hint_year(self):
        """Windowed badge (v111): when_hint 2011 counts ONLY the 2011 records,
        not asu's full 2010–2013 stream."""
        data = tl.timeline_data()
        slug, event = self.event_by_desc(data, "Moved into the ASU dorms")
        self.assertEqual(slug, "college")
        badge = event.get("corroboration")
        self.assertIsNotNone(badge)
        self.assertEqual(badge["count"], 2)
        self.assertEqual((badge["first"], badge["last"]), (2011, 2011))
        self.assertEqual(badge["status"], "corroborated")
        self.assertEqual(tcorr.badge_text(badge), "asu ×2 · 2011")

    def test_unmatched_and_contradicted_events_carry_no_badge(self):
        data = tl.timeline_data()
        # the contradicted event's records are all out-of-window → no badge
        _slug, football = self.event_by_desc(data, "First ASU football game")
        self.assertNotIn("corroboration", football)
        # and chase (matched by nothing) appears in no badge anywhere
        for period in data["periods"]:
            for ent in (period.get("corroboration") or {}).get("entities", []):
                self.assertNotEqual(ent["entity"], "chase")
        for rows in data["event_lineup"].values():
            for event in rows:
                for ent in (event.get("corroboration") or {}).get("entities", []):
                    self.assertNotEqual(ent["entity"], "chase")


class ContradictionTests(CorroborationFixture):
    def test_event_contradiction_detected(self):
        """Email clusters 2010–2013, memory says 2004 — surfaced, never applied.
        The contradicted moment carries NO badge (out-of-window records don't
        badge, v111); the conflict lives in the gap entry."""
        data = tl.timeline_data()
        slug, event = self.event_by_desc(data, "First ASU football game")
        self.assertNotIn("corroboration", event)
        contradictions = data["corroboration"]["contradictions"]
        self.assertEqual(len(contradictions), 1)
        record = contradictions[0]
        self.assertEqual(record["kind"], "date_contradiction")
        self.assertEqual(record["level"], "event")
        self.assertEqual(record["period"], "college")
        self.assertEqual(record["entity"], "asu")
        self.assertEqual(record["connector"], "gmail")
        self.assertEqual(record["memory_says"], "2004")
        self.assertEqual(record["evidence_says"], "2010–2013")
        self.assertEqual(record["evidence_count"], 4)
        self.assertTrue(record["key"].startswith("event-"))
        self.assertIn("First ASU football game", record["candidate_text"])
        self.assertIn("which is right?", record["candidate_text"])

    def test_contradiction_gap_entry_on_period(self):
        data = tl.timeline_data()
        gaps = [g for g in data["gaps_by_period"].get("college", [])
                if g["kind"] == "date_contradiction"]
        self.assertEqual(len(gaps), 1)
        self.assertIn("Date conflict", gaps[0]["message"])
        self.assertIn("2004", gaps[0]["message"])
        self.assertIn("2010–2013", gaps[0]["message"])
        self.assertIn("never silently overwritten", gaps[0]["hint"])

    def test_period_contradiction_when_evidence_outside_stated_range(self):
        self.write_roster(approximate_dates="2006–2009")
        data = tl.timeline_data()
        self.assertNotIn("corroboration", data["periods"][0])  # nothing in-window
        records = [c for c in data["corroboration"]["contradictions"]
                   if c["level"] == "period"]
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["memory_says"], "2006–2009")
        self.assertEqual(records[0]["evidence_says"], "2010–2013")
        self.assertEqual(records[0]["key"], "period-college")
        gaps = [g for g in data["gaps_by_period"].get("college", [])
                if g["kind"] == "date_contradiction"]
        self.assertTrue(any("outside College's stated dates" in g["message"] for g in gaps))

    def test_single_stray_record_is_not_a_contradiction(self):
        # One 2003 record against a 2011 memory: noise, not a cluster.
        self.write_evidence([_evidence("2003-01-01", "asu", "billing", "mx")])
        data = tl.timeline_data()
        _slug, event = self.event_by_desc(data, "Moved into the ASU dorms")
        self.assertNotIn("corroboration", event)
        self.assertEqual(data["corroboration"]["contradictions"], [])


class RenderTests(CorroborationFixture):
    def _view(self):
        sw = load("serve_wiki")
        sys.modules["timeline"] = tl  # view imports by name; use our patched module
        return sw.view_timeline()

    def test_view_renders_period_and_event_badges(self):
        _title, body, _wide = self._view()
        self.assertIn("✉ asu ×4 · 2010–2013", body)  # period summary
        self.assertIn("✉ asu ×2 · 2011", body)        # windowed event badge
        self.assertIn("Date conflict", body)          # contradiction gap card
        self.assertIn("tl-gap", body)

    def test_export_carries_the_same_badges(self):
        wc = load("wiki_compile")
        orig = (wc.STATE_DIR, wc.WIKI_DIR)
        wc.STATE_DIR = self.root / "state"
        wc.WIKI_DIR = self.root / "wiki"
        sys.modules["timeline"] = tl
        try:
            self.assertTrue(wc.compile_timeline())
        finally:
            wc.STATE_DIR, wc.WIKI_DIR = orig
        text = (self.root / "wiki" / "timeline.md").read_text(encoding="utf-8")
        self.assertIn("## College — ✉ asu ×4 · 2010–2013", text)
        self.assertIn("Moved into the ASU dorms", text)
        self.assertIn("· ✉ asu ×2 · 2011", text)


class NoEvidenceNoopTests(CorroborationFixture):
    def test_missing_file_attaches_nothing(self):
        self.remove_evidence()
        data = tl.timeline_data()
        self.assertFalse(data["corroboration"]["available"])
        for period in data["periods"]:
            self.assertNotIn("corroboration", period)
        for rows in data["event_lineup"].values():
            for event in rows:
                self.assertNotIn("corroboration", event)
        for gaps in data["gaps_by_period"].values():
            self.assertNotIn("date_contradiction", {g["kind"] for g in gaps})

    def test_render_identical_without_evidence(self):
        """Snapshot: the view + export with no evidence file are byte-identical
        to a run whose evidence matches nothing — connectors are optional."""
        sw = load("serve_wiki")
        sys.modules["timeline"] = tl
        self.remove_evidence()
        body_without = sw.view_timeline()[1]
        self.assertNotIn("✉", body_without)

        self.write_evidence([CHASE_RECORD])  # present, but matches nothing
        body_unmatched = sw.view_timeline()[1]
        self.assertEqual(body_without, body_unmatched)

        wc = load("wiki_compile")
        orig = (wc.STATE_DIR, wc.WIKI_DIR)
        wc.STATE_DIR = self.root / "state"
        wc.WIKI_DIR = self.root / "wiki"
        try:
            wc.compile_timeline()
            export_unmatched = (self.root / "wiki" / "timeline.md").read_text(encoding="utf-8")
            self.remove_evidence()
            wc.compile_timeline()
            export_without = (self.root / "wiki" / "timeline.md").read_text(encoding="utf-8")
        finally:
            wc.STATE_DIR, wc.WIKI_DIR = orig
        self.assertEqual(export_without, export_unmatched)
        self.assertNotIn("✉", export_without)


class AggregationCapTests(CorroborationFixture):
    ALIASES = ["ASU", "MIT", "Delta", "Chase", "Southwest"]
    RECORDS = (
        [_evidence(f"2010-0{i + 1}-01", "asu", mid=f"a{i}") for i in range(5)]
        + [_evidence(f"2011-0{i + 1}-01", "mit", mid=f"m{i}") for i in range(3)]
        + [_evidence(f"2012-0{i + 1}-01", "delta", mid=f"d{i}") for i in range(2)]
        + [_evidence(f"2013-0{i + 1}-01", "chase", mid=f"c{i}") for i in range(2)]
        + [_evidence("2014-01-01", "southwest", mid="s0")]
    )

    def test_badge_caps_at_a_few_entities_with_more_folded(self):
        # No stated range → context-only full-range badge over everything.
        self.write_roster(aliases=self.ALIASES, approximate_dates="")
        self.write_evidence(self.RECORDS)
        data = tl.timeline_data()
        badge = data["periods"][0]["corroboration"]
        self.assertEqual(badge["status"], "neutral")
        self.assertEqual(badge["count"], 13)
        # dominant first, per-entity counts — never the global total per row
        self.assertEqual([e["count"] for e in badge["entities"]], [5, 3, 2, 2, 1])
        text = tcorr.badge_text(badge)
        self.assertIn("asu ×5 · 2010", text)
        self.assertIn("mit ×3 · 2011", text)
        self.assertIn("+ 2 more", text)
        self.assertNotIn("southwest", text)

    def test_windowed_period_badge_excludes_out_of_range_records(self):
        """D (v111): with stated 2010–2013, the 2014 southwest record does not
        badge the period at all."""
        self.write_roster(aliases=self.ALIASES)  # fixture default: 2010–2013
        self.write_evidence(self.RECORDS)
        data = tl.timeline_data()
        badge = data["periods"][0]["corroboration"]
        self.assertEqual(badge["status"], "corroborated")
        self.assertEqual(badge["count"], 12)  # southwest 2014 excluded
        self.assertEqual([e["entity"] for e in badge["entities"]],
                         ["asu", "mit", "chase", "delta"])  # count desc, name asc
        self.assertIn("+ 1 more", tcorr.badge_text(badge))


class PureFunctionTests(unittest.TestCase):
    """The engine itself, no filesystem: direct corroborate() calls."""

    def test_frontmatter_range_path_and_unplaced_event_contradiction(self):
        periods = [{"slug": "college", "name": "College", "aliases": ["ASU"],
                    "chrono": 1, "sources": set(), "page": None,
                    "approximate_dates": "2010–2013"}]
        event = {"description": "ASU orientation week", "when_hint": "",
                 "anchor": "", "source": "answers/A1.md", "source_short": "A1",
                 "eras": []}
        # no when_hint year → the placement period's stated range is the memory
        summary = tcorr.corroborate(
            periods, {"college": [event]}, [], connectors_dir=None,
            evidence=[_evidence("2003-05-01", "asu"), _evidence("2004-06-01", "asu")])
        self.assertNotIn("corroboration", event)  # out-of-window doesn't badge
        record = summary["contradictions"][0]
        self.assertEqual(record["memory_says"], "2010–2013")
        self.assertIn("College", record["candidate_text"])

    # --- A (v111): entities match DESCRIPTION tokens only -------------------

    def test_eras_and_when_hint_do_not_match_entities(self):
        """Live-data flaw 1: 'Born in Redlands' (1980s) carried asu ×1100 ·
        2010–2026 via era tokens. Eras/when_hint no longer attach entities."""
        event = {"description": "Born in Redlands", "when_hint": "1981",
                 "anchor": "", "source": "answers/A2.md", "source_short": "A2",
                 "eras": ["early childhood", "the asu years"]}
        summary = tcorr.corroborate(
            [], {}, [event], connectors_dir=None,
            evidence=[_evidence("2010-08-15", "asu"), _evidence("2026-01-05", "asu")])
        self.assertNotIn("corroboration", event)
        self.assertEqual(summary["contradictions"], [])

    # --- C (v111): contradictions need a tight out-of-window cluster --------

    def test_entity_absent_from_description_never_contradicts(self):
        """Live-data flaw 2 (root): the bankruptcy moment contradicted 'apple',
        which appears nowhere in its description."""
        event = {"description": "Officially went bankrupt about a month before "
                                "graduating college",
                 "when_hint": "2013", "anchor": "", "source": "answers/A3.md",
                 "source_short": "A3", "eras": ["college", "apple store years"]}
        summary = tcorr.corroborate(
            [], {}, [event], connectors_dir=None,
            evidence=[_evidence("2015-03-01", "apple"), _evidence("2026-02-01", "apple")])
        self.assertNotIn("corroboration", event)
        self.assertEqual(summary["contradictions"], [])

    def test_diffuse_out_of_window_records_never_contradict(self):
        """Even description-matched: a 2015–2026 stream (>5y span) is not a
        date claim about a 2013 memory — no contradiction, no badge."""
        event = {"description": "My apple store interview loop",
                 "when_hint": "2013", "anchor": "", "source": "answers/A3.md",
                 "source_short": "A3", "eras": []}
        summary = tcorr.corroborate(
            [], {}, [event], connectors_dir=None,
            evidence=[_evidence("2015-03-01", "apple"),
                      _evidence("2020-06-01", "apple"),
                      _evidence("2026-02-01", "apple")])
        self.assertNotIn("corroboration", event)
        self.assertEqual(summary["contradictions"], [])

    def test_tight_cluster_still_contradicts(self):
        """The case that MUST keep firing: memory says 2004, a tight 2003-only
        cluster of enrollment records says otherwise."""
        event = {"description": "First ASU football game", "when_hint": "2004",
                 "anchor": "", "source": "answers/A4.md", "source_short": "A4",
                 "eras": []}
        summary = tcorr.corroborate(
            [], {}, [event], connectors_dir=None,
            evidence=[_evidence("2003-03-01", "asu", "enrollment"),
                      _evidence("2003-09-15", "asu", "enrollment")])
        self.assertNotIn("corroboration", event)
        self.assertEqual(len(summary["contradictions"]), 1)
        record = summary["contradictions"][0]
        self.assertEqual(record["memory_says"], "2004")
        self.assertEqual(record["evidence_says"], "2003")

    def test_junk_entity_diffuse_stream_badges_nothing(self):
        """Live-data flaw 3 mitigation: a junk domain entity CAN match a
        description, but its diffuse out-of-window records badge nothing and
        contradict nothing."""
        event = {"description": "We bought the house in Tempe",
                 "when_hint": "2011", "anchor": "", "source": "answers/A5.md",
                 "source_short": "A5", "eras": []}
        summary = tcorr.corroborate(
            [], {}, [event], connectors_dir=None,
            evidence=[_evidence("2015-01-01", "house"), _evidence("2024-01-01", "house")])
        self.assertNotIn("corroboration", event)
        self.assertEqual(summary["contradictions"], [])

    # --- B (v111): windowed badges ------------------------------------------

    def test_in_window_records_win_over_outliers(self):
        """Mixed stream: the in-window record badges; the outliers are simply
        not about this moment — corroborated, no contradiction."""
        event = {"description": "Moved into the ASU dorms", "when_hint": "2011",
                 "anchor": "", "source": "answers/A6.md", "source_short": "A6",
                 "eras": []}
        summary = tcorr.corroborate(
            [], {}, [event], connectors_dir=None,
            evidence=[_evidence("2011-08-05", "asu"),
                      _evidence("2020-01-01", "asu"),
                      _evidence("2026-01-01", "asu")])
        badge = event["corroboration"]
        self.assertEqual(badge["status"], "corroborated")
        self.assertEqual(badge["count"], 1)
        self.assertEqual((badge["first"], badge["last"]), (2011, 2011))
        self.assertEqual(summary["contradictions"], [])

    def test_no_window_badge_is_context_only(self):
        """No when_hint year and no placement range: full-range badge, status
        neutral — and it can NEVER feed a contradiction."""
        event = {"description": "ASU reunion picnic", "when_hint": "",
                 "anchor": "", "source": "answers/A7.md", "source_short": "A7",
                 "eras": []}
        summary = tcorr.corroborate(
            [], {}, [event], connectors_dir=None,
            evidence=[_evidence("2010-08-15", "asu"), _evidence("2026-01-05", "asu")])
        badge = event["corroboration"]
        self.assertEqual(badge["status"], "neutral")
        self.assertEqual(badge["count"], 2)
        self.assertEqual((badge["first"], badge["last"]), (2010, 2026))
        self.assertEqual(summary["contradictions"], [])

    # --- existing guards -----------------------------------------------------

    def test_evidence_override_needs_no_files(self):
        summary = tcorr.corroborate([], {}, [], connectors_dir=None, evidence=[])
        self.assertFalse(summary["available"])
        self.assertEqual(summary["contradictions"], [])

    def test_malformed_records_are_dropped(self):
        items = tcorr._normalize_evidence([
            {"date": "not-a-date", "entity": "asu"},
            {"date": "2011-08-05", "entity": ""},
            {"date": "2011-08-05", "entity": "asu"},
            "garbage",
        ])
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["year"], 2011)
        self.assertEqual(items[0]["entity_tokens"], {"asu"})


# ---------------------------------------------------------------------------
# Excavation integration: contradictions become question candidates (v110).
# ---------------------------------------------------------------------------

import source_integrity  # noqa: E402
from connectors import base as cbase  # noqa: E402
from connectors.gmail import GmailConnector  # noqa: E402

OWNER = "me@example.com"


def _ledger_entry(mid, ymd):
    from datetime import datetime, timezone
    year, month, day = ymd
    return {
        "message_id": mid,
        "thread_id": f"t-{mid}",
        "timestamp": int(datetime(year, month, day, tzinfo=timezone.utc).timestamp()),
        "date": f"{year:04d}-{month:02d}-{day:02d}",
        "from_email": "registrar@asu.edu",
        "from_name": "ASU Registrar",
        "to": [OWNER],
        "cc": [],
        "subject": "Enrollment confirmation",
        "labels": ["INBOX"],
        "list_id": None,
        "has_unsubscribe": False,
        "noreply": True,
        "sent_by_owner": False,
    }


class FakeGmailClient:
    def __init__(self, owner=OWNER):
        self._owner = owner

    def profile_email(self):
        return self._owner


class ContradictionCandidateTests(unittest.TestCase):
    """excavate() appends timeline date contradictions to
    state/question_candidates.json (provenance connector-mined), deduped by
    id across runs."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        for sub in ("state/connectors", "state/entity_rosters", "state/reports",
                    "state/classifications", "wiki/periods", "sources", "answers"):
            (self.root / sub).mkdir(parents=True, exist_ok=True)
        self._patched = {
            "REPO_DIR": source_integrity.REPO_DIR,
            "ANSWERS_DIR": source_integrity.ANSWERS_DIR,
            "SOURCES_DIR": source_integrity.SOURCES_DIR,
            "SOURCE_MANIFEST_FILE": source_integrity.SOURCE_MANIFEST_FILE,
        }
        source_integrity.REPO_DIR = self.root
        source_integrity.ANSWERS_DIR = self.root / "answers"
        source_integrity.SOURCES_DIR = self.root / "sources"
        source_integrity.SOURCE_MANIFEST_FILE = self.root / "state" / "source_manifest.json"
        self.connector = GmailConnector(
            repo_dir=self.root, state_dir=self.root / "state" / "connectors")

        (self.root / "wiki" / "periods" / "college.md").write_text(
            PERIOD_PAGE.format(title="College", chrono=1, sources=_src_block(["A1"])),
            encoding="utf-8")
        (self.root / "state" / "entity_rosters" / "period.json").write_text(json.dumps({
            "version": 1, "type": "period", "entities": [{
                "name": "College", "slug": "college", "aliases": ["ASU"],
                "chrono": 1, "page_eligible": True, "approximate_dates": "2010–2013"}],
        }), encoding="utf-8")
        (self.root / "state" / "classifications" / "answers-a1.json").write_text(json.dumps({
            "source_path": "answers/A1.md",
            "time_periods": [],
            "events": [{"description": "First ASU football game", "when_hint": "2004",
                        "anchor": None}],
        }), encoding="utf-8")
        cbase.rewrite_ledger(self.connector.ledger_path, [
            _ledger_entry("m1", (2010, 8, 15)),
            _ledger_entry("m2", (2011, 8, 5)),
            _ledger_entry("m3", (2013, 5, 10)),
        ])

    def tearDown(self):
        for key, value in self._patched.items():
            setattr(source_integrity, key, value)
        self.tmp.cleanup()

    def _candidates(self):
        path = self.root / "state" / "question_candidates.json"
        if not path.exists():
            return []
        return json.loads(path.read_text(encoding="utf-8")).get("candidates", [])

    def test_excavate_appends_date_contradiction_candidate(self):
        summary = self.connector.excavate(client=FakeGmailClient())
        self.assertEqual(summary["date_evidence"], 3)
        contradictions = [c for c in self._candidates()
                          if c.get("kind") == "date_contradiction"]
        self.assertEqual(len(contradictions), 1)
        candidate = contradictions[0]
        self.assertTrue(candidate["id"].startswith("cand-gmail-date-contradiction-event-"))
        self.assertEqual(candidate["provenance"], "connector-mined")
        self.assertEqual(candidate["status"], "candidate")
        self.assertIn("First ASU football game", candidate["text"])
        self.assertIn("2004", candidate["text"])
        self.assertIn("which is right?", candidate["text"])
        self.assertEqual(candidate["source_path"],
                         "state/connectors/gmail_date_evidence.json")

    def test_reexcavation_dedupes_by_candidate_id(self):
        self.connector.excavate(client=FakeGmailClient())
        self.connector.excavate(client=FakeGmailClient())
        contradictions = [c for c in self._candidates()
                          if c.get("kind") == "date_contradiction"]
        self.assertEqual(len(contradictions), 1)

    def test_no_evidence_no_candidates(self):
        self.connector.ledger_path.unlink()
        self.assertEqual(self.connector.timeline_contradiction_candidates(evidence=[]), [])


if __name__ == "__main__":
    unittest.main()
