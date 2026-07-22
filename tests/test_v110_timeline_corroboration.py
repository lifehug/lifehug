"""v110 — timeline corroboration from connector date evidence (issue #44).

Connector date evidence ({date, entity, kind, message_id}) lines up against
periods (roster name/slug/alias token-subset) and events (entity tokens within
the moment's own text): corroboration badges render on the view and the
wiki/timeline.md export; evidence clustering against the story's own dates
surfaces as date_contradiction gaps and connector-mined question candidates.
No evidence file → the timeline renders exactly as before.
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
        self.assertEqual(data["corroboration"]["total"], 4)
        badge = data["periods"][0].get("corroboration")
        self.assertIsNotNone(badge)
        # 3 asu records matched; the chase record matched nothing.
        self.assertEqual(badge["count"], 3)
        self.assertEqual(badge["entities"], [
            {"entity": "asu", "count": 3, "first": 2010, "last": 2013}])
        self.assertEqual((badge["first"], badge["last"]), (2010, 2013))
        # stated 2010–2013 overlaps the evidence range → corroborated.
        self.assertEqual(badge["status"], "corroborated")

    def test_badge_counts_are_per_matched_entity_not_global(self):
        data = tl.timeline_data()
        badge = data["periods"][0]["corroboration"]
        # the ledger holds 4 records total — the badge reports only asu's 3.
        self.assertEqual(badge["count"], 3)
        self.assertEqual(sum(e["count"] for e in badge["entities"]), 3)

    def test_badge_text_format(self):
        data = tl.timeline_data()
        self.assertEqual(tcorr.badge_text(data["periods"][0]["corroboration"]),
                         "asu ×3 · 2010–2013")


class EventBadgeTests(CorroborationFixture):
    def test_event_badge_corroborated_by_when_hint_year(self):
        data = tl.timeline_data()
        slug, event = self.event_by_desc(data, "Moved into the ASU dorms")
        self.assertEqual(slug, "college")
        badge = event.get("corroboration")
        self.assertIsNotNone(badge)
        self.assertEqual(badge["count"], 3)
        self.assertEqual((badge["first"], badge["last"]), (2010, 2013))
        self.assertEqual(badge["status"], "corroborated")  # 2011 ∈ 2010–2013

    def test_unmatched_event_has_no_badge(self):
        # chase evidence matches no period and no event text.
        data = tl.timeline_data()
        for rows in data["event_lineup"].values():
            for event in rows:
                self.assertEqual(event["corroboration"]["entities"][0]["entity"], "asu")


class ContradictionTests(CorroborationFixture):
    def test_event_contradiction_detected(self):
        """Email says 2010–2013, memory says 2004 — surfaced, never applied."""
        data = tl.timeline_data()
        slug, event = self.event_by_desc(data, "First ASU football game")
        self.assertEqual(event["corroboration"]["status"], "contradiction")
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
        self.assertEqual(record["evidence_count"], 3)
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
        badge = data["periods"][0]["corroboration"]
        self.assertEqual(badge["status"], "contradiction")
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
        self.assertEqual(event["corroboration"]["status"], "neutral")
        self.assertEqual(data["corroboration"]["contradictions"], [])


class RenderTests(CorroborationFixture):
    def _view(self):
        sw = load("serve_wiki")
        sys.modules["timeline"] = tl  # view imports by name; use our patched module
        return sw.view_timeline()

    def test_view_renders_period_and_event_badges(self):
        _title, body, _wide = self._view()
        self.assertIn("✉ asu ×3 · 2010–2013", body)  # period summary + event dot
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
        self.assertIn("## College — ✉ asu ×3 · 2010–2013", text)
        self.assertIn("Moved into the ASU dorms", text)
        self.assertIn("· ✉ asu ×3 · 2010–2013", text)


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
    def test_badge_caps_at_a_few_entities_with_more_folded(self):
        aliases = ["ASU", "MIT", "Delta", "Chase", "Southwest"]
        self.write_roster(aliases=aliases)
        records = (
            [_evidence(f"2010-0{i + 1}-01", "asu", mid=f"a{i}") for i in range(5)]
            + [_evidence(f"2011-0{i + 1}-01", "mit", mid=f"m{i}") for i in range(3)]
            + [_evidence(f"2012-0{i + 1}-01", "delta", mid=f"d{i}") for i in range(2)]
            + [_evidence(f"2013-0{i + 1}-01", "chase", mid=f"c{i}") for i in range(2)]
            + [_evidence("2014-01-01", "southwest", mid="s0")]
        )
        self.write_evidence(records)
        data = tl.timeline_data()
        badge = data["periods"][0]["corroboration"]
        self.assertEqual(badge["count"], 13)
        # dominant first, per-entity counts — never the global total per row
        self.assertEqual([e["count"] for e in badge["entities"]], [5, 3, 2, 2, 1])
        text = tcorr.badge_text(badge)
        self.assertIn("asu ×5 · 2010", text)
        self.assertIn("mit ×3 · 2011", text)
        self.assertIn("+ 2 more", text)
        self.assertNotIn("southwest", text)


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
        self.assertEqual(event["corroboration"]["status"], "contradiction")
        record = summary["contradictions"][0]
        self.assertEqual(record["memory_says"], "2010–2013")
        self.assertIn("College", record["candidate_text"])

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
