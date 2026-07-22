"""Connector framework tests (v106): permanent ledger, recomputed relevance,
threshold promotion — with a fake Gmail client. No network, no google SDK."""

import json
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SYSTEM = ROOT / "system"
sys.path.insert(0, str(SYSTEM))

import source_integrity
from connectors import base as cbase
from connectors import scoring as cscoring
from connectors.gmail import GmailConnector


OWNER = "me@example.com"


def _ts(ymd):
    return int(datetime(*ymd, tzinfo=timezone.utc).timestamp())


def make_entry(mid, tid, from_email, subject, ymd, *, from_name="", noreply=False,
               list_id=None, unsub=False):
    return {
        "message_id": mid,
        "thread_id": tid,
        "timestamp": _ts(ymd),
        "date": f"{ymd[0]:04d}-{ymd[1]:02d}-{ymd[2]:02d}",
        "from_email": from_email,
        "from_name": from_name,
        "to": [OWNER],
        "cc": [],
        "subject": subject,
        "labels": ["INBOX"],
        "list_id": list_id,
        "has_unsubscribe": unsub,
        "noreply": noreply,
        "sent_by_owner": from_email == OWNER,
    }


def grandpa_thread(tid="t-grandpa", subject="Re: the old farm", year=2008):
    """An 8-message, 4/4 two-way one-on-one thread spanning 100 days."""
    days = [(year, 1, 1), (year, 1, 20), (year, 2, 10), (year, 3, 1),
            (year, 3, 15), (year, 3, 28), (year, 4, 5), (year, 4, 10)]
    senders = ["joe.taylor@example.com", OWNER] * 4
    return [
        make_entry(f"{tid}-m{i}", tid, sender, subject, day,
                   from_name="Joe Taylor" if sender != OWNER else "")
        for i, (sender, day) in enumerate(zip(senders, days))
    ]


class FakeGmailClient:
    """Injectable stand-in for gmail.GmailClient — the real API is never
    called in tests. Records calls so tests can prove no re-fetch happened."""

    def __init__(self, owner=OWNER, thread_bodies=None, metadata_by_id=None, history_id="h1"):
        self._owner = owner
        self._thread_bodies = thread_bodies or {}
        self._metadata_by_id = metadata_by_id or {}
        self._history_id = history_id
        self.list_queries = []
        self.metadata_requests = []
        self.thread_requests = []

    def profile_email(self):
        return self._owner

    def history_id(self):
        return self._history_id

    def list_message_ids(self, query=None):
        self.list_queries.append(query)
        return iter(list(self._metadata_by_id))

    def fetch_metadata(self, message_ids):
        self.metadata_requests.append(list(message_ids))
        return [dict(self._metadata_by_id[mid]) for mid in message_ids if mid in self._metadata_by_id]

    def fetch_thread(self, thread_id):
        self.thread_requests.append(thread_id)
        return self._thread_bodies.get(thread_id, [])


class ConnectorTestCase(unittest.TestCase):
    """Tmp repo layout; source_integrity's module-level paths patched to it
    (the established pattern for this suite) so register_source/manifest
    stay inside the fixture."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        for sub in ("state/connectors", "state/entity_rosters", "state/reports",
                    "wiki/people", "sources", "answers"):
            (self.root / sub).mkdir(parents=True, exist_ok=True)
        self.state_dir = self.root / "state" / "connectors"
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
        self.connector = GmailConnector(repo_dir=self.root, state_dir=self.state_dir)

    def tearDown(self):
        for key, value in self._patched.items():
            setattr(source_integrity, key, value)
        self.tmp.cleanup()

    def write_ledger(self, entries):
        cbase.rewrite_ledger(self.connector.ledger_path, entries)

    def write_roster(self, entities, roster_type="person"):
        payload = {"version": 1, "type": roster_type, "entities": entities}
        (self.root / "state" / "entity_rosters" / f"{roster_type}.json").write_text(
            json.dumps(payload), encoding="utf-8")

    def source_files(self):
        gmail_dir = self.root / "sources" / "gmail"
        return sorted(gmail_dir.glob("*.md")) if gmail_dir.exists() else []

    def manifest_source_ids(self):
        data = json.loads((self.root / "state" / "source_manifest.json").read_text())
        return {entry.get("source_id") for entry in data.get("sources", {}).values()}


class ScoringTests(unittest.TestCase):
    def test_axis_determinism_and_range(self):
        entries = grandpa_thread()
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "state" / "entity_rosters").mkdir(parents=True)
            config = cscoring.load_scoring_config()
            context = cscoring.build_context(root, entries, config, owner_email=OWNER)
            first = cscoring.score_thread(entries, context)
            context2 = cscoring.build_context(root, entries, config, owner_email=OWNER)
            second = cscoring.score_thread(entries, context2)
            self.assertEqual(first, second)
            for axis in cscoring.AXES:
                self.assertGreaterEqual(first["scores"][axis], 0.0, axis)
                self.assertLessEqual(first["scores"][axis], 1.0, axis)
            expected = round(sum(first["scores"][a] * config["weights"][a] for a in cscoring.AXES), 4)
            self.assertEqual(first["total"], expected)

    def test_band_boundaries(self):
        thresholds = dict(cscoring.DEFAULT_THRESHOLDS)
        cases = [
            (0.0, "noise"), (0.149, "noise"), (0.15, "evidence"),
            (0.449, "evidence"), (0.45, "near_band"), (0.599, "near_band"),
            (0.60, "promote"), (1.0, "promote"),
        ]
        for total, expected in cases:
            with self.subTest(total=total):
                self.assertEqual(cscoring.assign_band(total, thresholds), expected)

    def test_weights_override_from_state_config(self):
        with tempfile.TemporaryDirectory() as td:
            weights_path = Path(td) / "weights.json"
            weights_path.write_text(json.dumps({
                "weights": {"novelty": 0.5, "bogus_axis": 9.9},
                "thresholds": {"promote": 0.8, "bogus_threshold": 1},
            }))
            config = cscoring.load_scoring_config(weights_path)
            self.assertEqual(config["weights"]["novelty"], 0.5)
            self.assertEqual(config["thresholds"]["promote"], 0.8)
            self.assertNotIn("bogus_axis", config["weights"])
            self.assertNotIn("bogus_threshold", config["thresholds"])
            # untouched keys fall back to the committed defaults
            self.assertEqual(config["weights"]["date_anchor"],
                             cscoring.DEFAULT_WEIGHTS["date_anchor"])


class LedgerTests(ConnectorTestCase):
    def test_append_dedupes_by_message_id_and_cursor_roundtrips(self):
        entries = grandpa_thread()
        added, total = cbase.append_ledger(self.connector.ledger_path, entries)
        self.assertEqual((added, total), (8, 8))
        # re-append an overlapping window: only the genuinely new id lands
        again = [entries[3], make_entry("m-new", "t-other", "x@example.com", "hi", (2011, 5, 5))]
        added, total = cbase.append_ledger(self.connector.ledger_path, again)
        self.assertEqual((added, total), (1, 9))

        cbase.save_cursor(self.connector.cursor_path, {"version": 1, "owner": OWNER, "n": 9})
        cursor = cbase.load_cursor(self.connector.cursor_path)
        self.assertEqual(cursor["owner"], OWNER)
        self.assertEqual(cursor["n"], 9)

    def test_fetch_appends_once_and_advances_cursor(self):
        entries = grandpa_thread()
        metadata = {entry["message_id"]: entry for entry in entries}
        client = FakeGmailClient(metadata_by_id=metadata)
        first = self.connector.fetch(client=client)
        self.assertEqual(first["added"], 8)
        second = self.connector.fetch(client=client)
        self.assertEqual(second["added"], 0)
        self.assertEqual(len(cbase.load_ledger(self.connector.ledger_path)), 8)
        cursor = cbase.load_cursor(self.connector.cursor_path)
        self.assertEqual(cursor["owner"], OWNER)
        self.assertEqual(cursor["total_messages"], 8)
        # incremental fetch narrows the listing with an after: query
        self.assertIsNotNone(client.list_queries[1])
        self.assertIn("after:", client.list_queries[1])


class ExcavationFlipTests(ConnectorTestCase):
    """The core invariant: a thread sub-threshold against an empty roster
    crosses the threshold once the correspondent gains a roster entry — on
    the second run only, with NO re-fetch."""

    def test_relevance_flip_promotes_on_second_run_only(self):
        self.write_ledger(grandpa_thread())
        client = FakeGmailClient(thread_bodies={
            "t-grandpa": [
                {"date": "2008-01-01", "from_name": "Joe Taylor",
                 "from_email": "joe.taylor@example.com",
                 "subject": "Re: the old farm",
                 "body": "Do you remember the summer we rebuilt the fence?"},
            ],
        })

        first = self.connector.excavate(client=client)
        self.assertEqual(first["promoted"], [])
        self.assertEqual(self.source_files(), [])
        self.assertEqual(client.thread_requests, [])

        # Grandpa gets a roster entry — no fetch, just re-excavation.
        self.write_roster([{"name": "Grandpa Joe", "slug": "grandpa-joe",
                            "aliases": ["Joe Taylor"]}])
        second = self.connector.excavate(client=client)
        self.assertEqual(len(second["promoted"]), 1)
        self.assertEqual(len(self.source_files()), 1)
        # bodies fetched for the promoted thread only; listing never re-ran
        self.assertEqual(client.thread_requests, ["t-grandpa"])
        self.assertEqual(client.list_queries, [])
        self.assertEqual(client.metadata_requests, [])

        # scores were refreshed on the permanent entries, not trusted
        ledger = cbase.load_ledger(self.connector.ledger_path)
        self.assertEqual(len(ledger), 8)
        self.assertTrue(all(entry.get("band") == "promote" for entry in ledger))
        self.assertTrue(all(entry.get("promoted") for entry in ledger))

        # third run: manifest idempotency blocks re-promotion
        third = self.connector.excavate(client=client)
        self.assertEqual(third["promoted"], [])
        self.assertEqual(len(self.source_files()), 1)


class PromotionTests(ConnectorTestCase):
    def setUp(self):
        super().setUp()
        self.write_roster([
            {"name": "Grandpa Joe", "slug": "grandpa-joe", "aliases": ["Joe Taylor"]},
            {"name": "Uncle Bob", "slug": "uncle-bob", "aliases": ["Bob Taylor"]},
            {"name": "Aunt May", "slug": "aunt-may", "aliases": ["May Taylor"]},
        ])
        self.bodies = {
            tid: [{"date": "2008-01-01", "from_name": "X", "from_email": "x@example.com",
                   "subject": subject, "body": f"body of {tid}"}]
            for tid, subject in (("t1", "the old farm"), ("t2", "the lake house"),
                                 ("t3", "the wedding"))
        }

    def _three_thread_ledger(self):
        entries = grandpa_thread("t1", "the old farm", 2008)
        entries += grandpa_thread("t2", "the lake house", 2009)
        entries += grandpa_thread("t3", "the wedding", 2010)
        sender = {"t1": "joe.taylor@example.com", "t2": "bob.taylor@example.com",
                  "t3": "may.taylor@example.com"}
        names = {"t1": "Joe Taylor", "t2": "Bob Taylor", "t3": "May Taylor"}
        for entry in entries:
            if entry["from_email"] != OWNER:
                entry["from_email"] = sender[entry["thread_id"]]
                entry["from_name"] = names[entry["thread_id"]]
        return entries

    def test_cap_bounds_promotions_and_delta_promotes_next_run(self):
        self.write_ledger(self._three_thread_ledger())
        client = FakeGmailClient(thread_bodies=self.bodies)
        first = self.connector.excavate(cap=2, client=client)
        self.assertEqual(len(first["promoted"]), 2)
        self.assertEqual(first["skipped_cap"], 1)
        self.assertEqual(len(self.source_files()), 2)
        second = self.connector.excavate(cap=2, client=client)
        self.assertEqual(len(second["promoted"]), 1)
        self.assertEqual(len(self.source_files()), 3)
        self.assertEqual(self.manifest_source_ids(), {"gmail:t1", "gmail:t2", "gmail:t3"})

    def test_dry_run_writes_nothing(self):
        self.write_ledger(self._three_thread_ledger())
        ledger_before = self.connector.ledger_path.read_text()
        summary = self.connector.excavate(dry_run=True,
                                          client=FakeGmailClient(thread_bodies=self.bodies))
        self.assertEqual(len(summary["would_promote"]), 3)
        self.assertEqual(summary["promoted"], [])
        self.assertEqual(self.source_files(), [])
        self.assertFalse((self.root / "state" / "source_manifest.json").exists())
        self.assertFalse(self.connector.date_evidence_path.exists())
        self.assertFalse((self.root / "state" / "question_candidates.json").exists())
        self.assertEqual(self.connector.ledger_path.read_text(), ledger_before)

    def test_promoted_source_is_well_formed_and_lint_clean(self):
        self.write_ledger(grandpa_thread("t1", "the old farm", 2008))
        client = FakeGmailClient(thread_bodies=self.bodies)
        summary = self.connector.excavate(client=client)
        self.assertEqual(len(summary["promoted"]), 1)
        path = self.source_files()[0]
        self.assertRegex(path.name, r"^2008-01-01-the-old-farm\.md$")

        content = path.read_text(encoding="utf-8")
        metadata, body = source_integrity.split_frontmatter(content)
        self.assertEqual(metadata["type"], "external_record")
        self.assertEqual(metadata["source_trust"], "external_record")
        self.assertEqual(metadata["authority"], "third_party_record")
        self.assertEqual(metadata["visibility"], "owner_only")
        self.assertEqual(metadata["sensitivity"], "private")
        self.assertEqual(metadata["immutable"], True)
        self.assertEqual(metadata["status"], "raw")
        self.assertEqual(metadata["source_id"], "gmail:t1")
        self.assertIn("t1", metadata["raw_url"])
        self.assertEqual(metadata["content_sha256"], source_integrity.payload_sha256(body))
        self.assertIn("body of t1", body)

        record = source_integrity.source_record(path)
        self.assertEqual(record["required_missing"], [])
        findings = source_integrity.lint_records([record])
        bad = {"missing_source_metadata", "content_hash_mismatch", "manifest_missing"}
        self.assertEqual({f["type"] for f in findings} & bad, set())
        self.assertEqual([f for f in findings if f["severity"] == "error"], [])


class DateEvidenceTests(ConnectorTestCase):
    def test_generic_domain_words_never_become_evidence_entities(self):
        """v112: mail.house.gov must not yield entity 'house' — generic domain
        words are stoplisted out of date evidence."""
        entries = [
            make_entry("gov-1", "t-gov", "reprokhanna@mail.house.gov",
                       "Congressional update", (2020, 3, 1), noreply=True, unsub=True),
            make_entry("asu-1", "t-asu", "donotreply@asu.edu",
                       "Enrollment verification", (2011, 8, 1), noreply=True),
        ]
        connector = GmailConnector(repo_dir=self.root, state_dir=self.state_dir)
        evidence = connector.extract_date_evidence(entries, {"date_evidence": 0.0})
        entities = {e["entity"] for e in evidence}
        self.assertIn("asu", entities)
        self.assertNotIn("house", entities)

    def test_institutional_mail_yields_date_evidence(self):
        entries = [
            make_entry("asu-1", "t-asu", "registrar@asu.edu", "Enrollment confirmation",
                       (2003, 8, 15), from_name="ASU Registrar", noreply=True),
            *grandpa_thread(),
        ]
        self.write_ledger(entries)
        self.connector.excavate(client=FakeGmailClient())
        data = json.loads(self.connector.date_evidence_path.read_text())
        self.assertEqual(data["version"], 1)
        self.assertEqual(len(data["evidence"]), 1)
        row = data["evidence"][0]
        self.assertEqual(row, {"date": "2003-08-15", "entity": "asu",
                               "kind": "enrollment", "message_id": "asu-1"})

    def test_plain_noreply_without_institutional_signals_is_not_evidence(self):
        entries = [
            make_entry("m1", "t-promo", "noreply@shop.example.com", "50% off today only",
                       (2015, 3, 3), noreply=True, unsub=True),
        ]
        self.write_ledger(entries)
        self.connector.excavate(client=FakeGmailClient())
        data = json.loads(self.connector.date_evidence_path.read_text())
        self.assertEqual(data["evidence"], [])


class DiscoveryTests(ConnectorTestCase):
    def _sam_ledger(self):
        days = [(2009, 1, 5), (2009, 3, 10), (2009, 6, 20), (2009, 9, 1),
                (2009, 12, 25), (2010, 2, 14), (2010, 4, 1), (2010, 6, 30),
                (2010, 8, 15), (2010, 10, 10), (2010, 11, 11), (2010, 12, 31)]
        entries = []
        for i, day in enumerate(days):
            # Sam sends 10 of 12 (above the 10-message discovery bar)
            sender = OWNER if i in (0, 7) else "sam.rivera@example.com"
            entries.append(make_entry(f"sam-m{i}", f"t-sam-{i % 2}", sender,
                                      "Re: hello there", day, from_name="Sam Rivera"))
        return entries

    def test_unknown_high_volume_correspondent_becomes_candidate(self):
        self.write_ledger(self._sam_ledger())
        self.connector.excavate(client=FakeGmailClient())
        data = json.loads((self.root / "state" / "question_candidates.json").read_text())
        people = [c for c in data["candidates"] if c["kind"] == "discovery_person"]
        self.assertEqual(len(people), 1)
        candidate = people[0]
        self.assertEqual(candidate["id"], "cand-gmail-person-sam-rivera")
        self.assertEqual(candidate["provenance"], "connector-mined")
        self.assertEqual(candidate["connector"], "gmail")
        self.assertEqual(candidate["status"], "candidate")
        self.assertEqual(candidate["source_path"], "state/connectors/gmail_ledger.jsonl")
        self.assertIn("Sam Rivera", candidate["text"])
        self.assertIn("10 emails", candidate["text"])
        self.assertIsNone(candidate["target_page"])

        # re-excavation never duplicates candidate ids
        self.connector.excavate(client=FakeGmailClient())
        data = json.loads((self.root / "state" / "question_candidates.json").read_text())
        ids = [c["id"] for c in data["candidates"]]
        self.assertEqual(len(ids), len(set(ids)))

    def test_known_correspondent_is_not_mined(self):
        self.write_roster([{"name": "Sam Rivera", "slug": "sam-rivera", "aliases": []}])
        self.write_ledger(self._sam_ledger())
        self.connector.excavate(client=FakeGmailClient())
        candidates_path = self.root / "state" / "question_candidates.json"
        data = json.loads(candidates_path.read_text()) if candidates_path.exists() else {"candidates": []}
        self.assertEqual([c for c in data["candidates"] if c["kind"] == "discovery_person"], [])


class ProbeTests(ConnectorTestCase):
    def test_probe_writes_report_without_touching_ledger(self):
        metadata = {}
        for i, entry in enumerate(grandpa_thread()):
            metadata[entry["message_id"]] = entry
        metadata["asu-1"] = make_entry("asu-1", "t-asu", "registrar@asu.edu",
                                       "Enrollment confirmation", (2003, 8, 15), noreply=True)
        client = FakeGmailClient(metadata_by_id=metadata)
        path = self.connector.probe(client=client, per_window=5)
        self.assertTrue(path.exists())
        text = path.read_text(encoding="utf-8")
        self.assertIn("gmail probe", text)
        self.assertIn("2010-2014", text)
        self.assertIn("No ledger written", text)
        self.assertFalse(self.connector.ledger_path.exists())


class WrapperTests(unittest.TestCase):
    def test_lifehug_wrapper_parses_connector_commands(self):
        sys.path.insert(0, str(SYSTEM))
        import importlib.util
        spec = importlib.util.spec_from_file_location("lifehug", SYSTEM / "lifehug.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        parser = mod.build_parser()
        for command in [
            ["connector-auth", "gmail"],
            ["connector-fetch", "gmail"],
            ["connector-fetch", "gmail", "--probe", "--per-window", "25"],
            ["connector-excavate", "gmail", "--dry-run", "--cap", "5"],
            ["connector-report", "gmail"],
            ["connector-audit", "gmail"],
            ["connector-calibrate", "gmail"],
            ["connector-calibrate", "gmail", "--set-threshold", "0.7"],
        ]:
            with self.subTest(command=command):
                args = parser.parse_args(command)
                self.assertTrue(callable(args.func))


class VipTests(ConnectorTestCase):
    """Owner-declared VIP correspondents (v107): family emphasis is calibrated
    knowledge, not a heuristic — pins relationship, lifts totals, is never
    mined as 'unknown', and proposes a page when the graph lacks one."""

    VIP = {"joe.taylor@example.com": "Grandpa Joe"}

    def _context(self, entries, bonus=0.10):
        config = cscoring.load_scoring_config()
        config["vip_correspondents"] = dict(self.VIP)
        config["vip_bonus"] = bonus
        return cscoring.build_context(self.root, entries, config, owner_email=OWNER)

    @staticmethod
    def long_vip_thread(n=24):
        """A 24-message two-way thread: VIP volume clears the discovery floor."""
        days = [(2008 + (i // 12), 1 + (i % 12), 1 + (i % 27)) for i in range(n)]
        senders = ["joe.taylor@example.com", OWNER] * (n // 2)
        return [
            make_entry(f"t-vip-m{i}", "t-vip", sender, "Re: family stuff", day,
                       from_name="Joe Taylor" if sender != OWNER else "")
            for i, (sender, day) in enumerate(zip(senders, days))
        ]

    def test_vip_pins_relationship_and_lifts_total(self):
        entries = grandpa_thread()
        plain = cscoring.score_thread(entries, cscoring.build_context(
            self.root, entries, cscoring.load_scoring_config(), owner_email=OWNER))
        context = self._context(entries)
        scored = cscoring.score_thread(entries, context)
        self.assertEqual(scored["scores"]["relationship_signal"], 1.0)
        self.assertIn("declared VIP", scored["reasons"]["relationship_signal"])
        self.assertEqual(scored["vips"], ["joe.taylor@example.com"])
        expected = round(min(1.0, sum(scored["scores"][a] * context.weights[a]
                                      for a in cscoring.AXES) + 0.10), 4)
        self.assertEqual(scored["total"], expected)
        self.assertGreater(scored["total"], plain["total"])

    def test_vip_bonus_flips_band_across_threshold(self):
        entries = grandpa_thread()
        plain = cscoring.score_thread(entries, cscoring.build_context(
            self.root, entries, cscoring.load_scoring_config(), owner_email=OWNER))
        self.assertNotEqual(plain["band"], "promote")
        scored = cscoring.score_thread(entries, self._context(entries, bonus=0.5))
        self.assertEqual(scored["band"], "promote")
        self.assertIn("vip_bonus", scored["reasons"])

    def test_vip_never_mined_as_unknown_person(self):
        entries = self.long_vip_thread()
        context = self._context(entries)
        threads = cscoring.group_threads(entries)
        scored = {tid: cscoring.score_thread(te, context) for tid, te in threads.items()}
        result = scored["t-vip"]
        self.assertEqual(result["scores"]["discovery_signal"], 0.0)
        candidates = self.connector.mine_discovery(entries, threads, scored, context)
        ids = {c["id"] for c in candidates}
        self.assertNotIn("cand-gmail-person-joe-taylor", ids)
        vip_cands = [c for c in candidates if c["kind"] == "discovery_vip"]
        self.assertEqual(len(vip_cands), 1)
        self.assertIn("Grandpa Joe", vip_cands[0]["text"])

    def test_vip_page_candidate_skipped_when_page_exists(self):
        (self.root / "wiki" / "people" / "grandpa-joe.md").write_text("# Grandpa Joe\n")
        entries = self.long_vip_thread()
        context = self._context(entries)
        threads = cscoring.group_threads(entries)
        scored = {tid: cscoring.score_thread(te, context) for tid, te in threads.items()}
        candidates = self.connector.mine_discovery(entries, threads, scored, context)
        self.assertFalse([c for c in candidates if c["kind"] == "discovery_vip"])

    def test_vip_label_parenthetical_role_does_not_false_match(self):
        """Regression (v109): a VIP label like 'Kristine Thompson (sister)'
        must not be judged page-known just because an unrelated wiki entry
        tokenizes to {sister} — the parenthetical role is not the name."""
        (self.root / "wiki" / "objects").mkdir(parents=True, exist_ok=True)
        (self.root / "wiki" / "objects" / "sister-cleats.md").write_text("# The Cleats\n")
        vip = {"kristine@example.com": "Kristine Thompson (sister)"}
        entries = [
            make_entry(f"t-krist-m{i}", "t-krist",
                       "kristine@example.com" if i % 2 == 0 else OWNER,
                       "Re: Camping", (2012, 8, 4 + i), from_name="Kristine Thompson")
            for i in range(4)
        ]
        config = cscoring.load_scoring_config()
        config["vip_correspondents"] = dict(vip)
        config["vip_bonus"] = 0.10
        context = cscoring.build_context(self.root, entries, config, owner_email=OWNER)
        threads = cscoring.group_threads(entries)
        scored = {tid: cscoring.score_thread(te, context) for tid, te in threads.items()}
        candidates = self.connector.mine_discovery(entries, threads, scored, context)
        vip_cands = [c for c in candidates if c["kind"] == "discovery_vip"]
        self.assertEqual(len(vip_cands), 1)
        self.assertIn("Kristine Thompson", vip_cands[0]["text"])

    def test_roster_email_alias_binds_exact_address(self):
        """Wiki importance marked via a roster email alias (v107): a
        correspondent matches by exact address even when their display name
        shares no tokens with the page — and stops being a discovery."""
        self.write_roster([{
            "name": "Dad", "slug": "dad",
            "aliases": ["Harvey Rex Taylor", "bigdaddy.jet@gmail.com"],
        }])
        entries = [
            make_entry(f"t-alias-m{i}", "t-alias",
                       "bigdaddy.jet@gmail.com" if i % 2 == 0 else OWNER,
                       "Re: nuttin'", (2015, 6, 7 + i), from_name="BigDaddy")
            for i in range(4)
        ]
        context = cscoring.build_context(
            self.root, entries, cscoring.load_scoring_config(), owner_email=OWNER)
        self.assertIn("bigdaddy.jet@gmail.com", context.known_emails)
        scored = cscoring.score_thread(entries, context)
        self.assertEqual(scored["scores"]["relationship_signal"], 1.0)
        self.assertEqual(scored["scores"]["discovery_signal"], 0.0)


KRIS = "kristine.t@example.com"

FAMILY_VERDICT = {
    "classification": "family",
    "significance": "Owner's sister; holiday and parent-care coordination",
    "suggested_label": "Kristine Thompson (sister)",
    "confidence": 0.87,
}


def kristine_ledger():
    """Two 8-message two-way threads; Kristine sends 12 (> dossier floor of 10)."""
    entries = []
    senders = [KRIS, KRIS, KRIS, OWNER, KRIS, KRIS, OWNER, KRIS]
    for tid, year in (("t-kris-a", 2014), ("t-kris-b", 2015)):
        for i, sender in enumerate(senders):
            entries.append(make_entry(
                f"{tid}-m{i}", tid, sender, "Re: family news", (year, 1 + (i % 2), 2 + i * 3),
                from_name="Kristine Thompson" if sender != OWNER else ""))
    return entries


def kristine_bodies():
    bodies = {}
    for tid in ("t-kris-a", "t-kris-b"):
        bodies[tid] = [
            {"message_id": f"{tid}-m{i}", "date": "2014-01-02",
             "from_name": "Kristine Thompson", "from_email": KRIS,
             "subject": "Re: family news",
             "body": f"message {i} about Mom and the reunion\n\n> quoted old text"}
            for i in range(8)
        ]
    return bodies


class FakeAI:
    """Injectable stand-in for research_expand.call_ai — the real model is
    never called in tests. Records (prompt, model) calls."""

    def __init__(self, verdict):
        self._verdict = verdict
        self.calls = []

    def __call__(self, prompt, model):
        self.calls.append((prompt, model))
        return json.dumps(self._verdict)


class DossierTests(ConnectorTestCase):
    """AI correspondent dossiers (v108): verdicts persist and skip when fresh;
    family-class verdicts auto-apply as VIPs (declared VIPs win conflicts,
    vip_blocklist vetoes); bodies cache by message id; dry-run calls nothing."""

    def test_dossier_model_key_wins_over_classify_model(self):
        """v113: dossier_model lets the dossier run a different provider
        without moving the weekly classifier."""
        from connectors import dossier as cdossier
        from unittest import mock
        with mock.patch.object(cdossier, "load_config",
                               return_value={"dossier_model": "kimi-for-coding",
                                             "classify_model": "claude-sonnet-5"}):
            self.assertEqual(cdossier.resolve_model(), "kimi-for-coding")
        with mock.patch.object(cdossier, "load_config",
                               return_value={"classify_model": "claude-sonnet-5"}):
            self.assertEqual(cdossier.resolve_model(), "claude-sonnet-5")
        with mock.patch.object(cdossier, "load_config", return_value={}):
            self.assertEqual(cdossier.resolve_model("flag-model"), "flag-model")

    def _scored_with(self, *, weights=None, verdict=None, tid="t-kris-a"):
        entries = kristine_ledger()
        if weights is not None:
            (self.state_dir / "weights.json").write_text(json.dumps(weights), encoding="utf-8")
        if verdict is not None:
            record = {
                **verdict,
                "model": "fake-model",
                "classified_at": "2026-07-21T00:00:00Z",
                "thread_ids": ["t-kris-a", "t-kris-b"],
                "messages_at_classification": 12,
            }
            self.connector.dossiers_path.write_text(
                json.dumps({"version": 1, "dossiers": {KRIS: record}}), encoding="utf-8")
        config = cscoring.load_scoring_config(self.connector.weights_path)
        context = cscoring.build_context(self.root, entries, config, owner_email=OWNER)
        threads = cscoring.group_threads(entries)
        return context, cscoring.score_thread(threads[tid], context)

    def test_dossier_persists_and_skips_when_fresh(self):
        from connectors import dossier as cdossier
        self.write_ledger(kristine_ledger())
        client = FakeGmailClient(thread_bodies=kristine_bodies())
        ai = FakeAI(FAMILY_VERDICT)

        first = cdossier.run_dossier_pass(
            self.connector, client=client, model="fake-model", ai_caller=ai)
        self.assertEqual(first["classified"], [KRIS])
        self.assertEqual(first["errors"], [])
        self.assertEqual(len(ai.calls), 1)
        prompt, model = ai.calls[0]
        self.assertEqual(model, "fake-model")
        self.assertIn(KRIS, prompt)
        self.assertIn("Kristine Thompson", prompt)
        self.assertNotIn("quoted old text", prompt)  # quoted chains stripped
        self.assertEqual(sorted(client.thread_requests), ["t-kris-a", "t-kris-b"])

        record = json.loads(self.connector.dossiers_path.read_text())["dossiers"][KRIS]
        self.assertEqual(record["classification"], "family")
        self.assertEqual(record["confidence"], 0.87)
        self.assertEqual(record["suggested_label"], "Kristine Thompson (sister)")
        self.assertEqual(record["model"], "fake-model")
        self.assertEqual(record["thread_ids"], ["t-kris-a", "t-kris-b"])
        self.assertEqual(record["messages_at_classification"], 12)
        self.assertTrue(record["classified_at"])
        self.assertEqual(len(list(self.connector.body_cache_dir.glob("*.json"))), 16)

        # Fresh dossier: nothing re-classified, nothing fetched, no AI call.
        second = cdossier.run_dossier_pass(
            self.connector, client=client, model="fake-model", ai_caller=ai)
        self.assertEqual(second["classified"], [])
        self.assertEqual(second["skipped_fresh"], [KRIS])
        self.assertEqual(len(ai.calls), 1)
        self.assertEqual(len(client.thread_requests), 2)

        # Material change (new messages since classified_at) re-classifies.
        extra = [
            make_entry(f"t-kris-c-m{i}", "t-kris-c", KRIS, "Re: more news",
                       (2016, 2, 2 + i), from_name="Kristine Thompson")
            for i in range(3)
        ]
        client._thread_bodies["t-kris-c"] = [
            {"message_id": f"t-kris-c-m{i}", "date": "2016-02-02",
             "from_name": "Kristine Thompson", "from_email": KRIS,
             "subject": "Re: more news", "body": f"more {i}"}
            for i in range(3)
        ]
        self.write_ledger(kristine_ledger() + extra)
        third = cdossier.run_dossier_pass(
            self.connector, client=client, model="fake-model", ai_caller=ai)
        self.assertEqual(third["classified"], [KRIS])
        self.assertEqual(len(ai.calls), 2)
        # t-kris-a/t-kris-b served from the body cache; only the new thread fetched
        self.assertEqual(client.thread_requests.count("t-kris-c"), 1)
        self.assertEqual(len(client.thread_requests), 3)
        record = json.loads(self.connector.dossiers_path.read_text())["dossiers"][KRIS]
        self.assertEqual(record["messages_at_classification"], 15)

        # --redossier forces re-classification even when fresh.
        fourth = cdossier.run_dossier_pass(
            self.connector, client=client, model="fake-model", ai_caller=ai, redossier=True)
        self.assertEqual(fourth["classified"], [KRIS])
        self.assertEqual(len(ai.calls), 3)
        self.assertEqual(len(client.thread_requests), 3)  # all cached by now

    def test_body_cache_hit_avoids_refetch(self):
        entries = kristine_ledger()
        self.write_ledger(entries)
        client = FakeGmailClient(thread_bodies=kristine_bodies())
        threads = cscoring.group_threads(entries)
        first = self.connector.fetch_thread_cached(client, "t-kris-a", threads["t-kris-a"])
        self.assertEqual(len(first), 8)
        self.assertEqual(client.thread_requests, ["t-kris-a"])
        again = self.connector.fetch_thread_cached(client, "t-kris-a", threads["t-kris-a"])
        self.assertEqual(again, first)
        self.assertEqual(client.thread_requests, ["t-kris-a"])  # no second fetch

    def test_family_verdict_auto_vip_pins_and_lifts(self):
        plain_context, plain = self._scored_with()
        self.assertEqual(plain["scores"]["relationship_signal"], 0.0)
        context, scored = self._scored_with(weights={"vip_bonus": 0.10}, verdict=FAMILY_VERDICT)
        self.assertEqual(scored["scores"]["relationship_signal"], 1.0)
        self.assertIn("dossier: family (0.87)", scored["reasons"]["relationship_signal"])
        self.assertEqual(scored["vips"], [KRIS])
        self.assertIn("dossier VIP", scored["reasons"]["vip_bonus"])
        expected = round(min(1.0, sum(scored["scores"][a] * context.weights[a]
                                      for a in cscoring.AXES) + 0.10), 4)
        self.assertEqual(scored["total"], expected)
        self.assertGreater(scored["total"], plain["total"])
        # dossier VIPs are known by definition — never a discovery
        self.assertEqual(scored["scores"]["discovery_signal"], 0.0)

    def test_declared_vip_always_wins_conflict(self):
        _context, scored = self._scored_with(
            weights={"vip_bonus": 0.10, "vip_correspondents": {KRIS: "Sister Kristine"}},
            verdict={"classification": "colleague", "confidence": 0.95,
                     "significance": "x", "suggested_label": "y"})
        self.assertEqual(scored["scores"]["relationship_signal"], 1.0)
        self.assertIn("declared VIP correspondent: Sister Kristine",
                      scored["reasons"]["relationship_signal"])
        self.assertNotIn("dossier", scored["reasons"]["relationship_signal"])
        self.assertIn("owner-declared VIP", scored["reasons"]["vip_bonus"])

    def test_blocklist_vetoes_dossier_vip(self):
        _context, scored = self._scored_with(
            weights={"vip_blocklist": [KRIS]}, verdict=FAMILY_VERDICT)
        self.assertEqual(scored["scores"]["relationship_signal"], 0.0)
        self.assertEqual(scored["vips"], [])
        self.assertNotIn("vip_bonus", scored["reasons"])

    def test_non_family_verdicts_do_not_become_vips(self):
        for classification in ("colleague", "service", "unknown", "close_friend"):
            with self.subTest(classification=classification):
                _context, scored = self._scored_with(verdict={
                    "classification": classification, "confidence": 0.95,
                    "significance": "x", "suggested_label": "y"})
                self.assertEqual(scored["scores"]["relationship_signal"], 0.0)
                self.assertEqual(scored["vips"], [])
        # ...unless the owner configures that class as an auto-VIP class
        _context, scored = self._scored_with(
            weights={"dossier_vip_classes": ["close_friend"]},
            verdict={"classification": "close_friend", "confidence": 0.9,
                     "significance": "x", "suggested_label": "y"})
        self.assertEqual(scored["scores"]["relationship_signal"], 1.0)
        self.assertIn("dossier: close_friend (0.90)", scored["reasons"]["relationship_signal"])

    def test_confidence_floor_respected(self):
        _context, scored = self._scored_with(verdict={**FAMILY_VERDICT, "confidence": 0.59})
        self.assertEqual(scored["vips"], [])
        self.assertEqual(scored["scores"]["relationship_signal"], 0.0)
        _context, scored = self._scored_with(verdict={**FAMILY_VERDICT, "confidence": 0.60})
        self.assertEqual(scored["vips"], [KRIS])
        # owner-raised floor: 0.87 no longer clears 0.9
        _context, scored = self._scored_with(
            weights={"dossier_confidence_floor": 0.9}, verdict=FAMILY_VERDICT)
        self.assertEqual(scored["vips"], [])

    def test_dry_run_makes_no_calls(self):
        from connectors import dossier as cdossier
        self.write_ledger(kristine_ledger())
        client = FakeGmailClient(thread_bodies=kristine_bodies())
        ai = FakeAI(FAMILY_VERDICT)
        summary = cdossier.run_dossier_pass(
            self.connector, client=client, ai_caller=ai, dry_run=True)
        self.assertEqual([row["email"] for row in summary["candidates"]], [KRIS])
        self.assertEqual(summary["classified"], [])
        self.assertEqual(ai.calls, [])
        self.assertEqual(client.thread_requests, [])
        self.assertFalse(self.connector.dossiers_path.exists())
        self.assertFalse(self.connector.body_cache_dir.exists())

    def test_excavation_dossiers_before_scoring_and_reports_vips(self):
        (self.state_dir / "weights.json").write_text(
            json.dumps({"vip_bonus": 0.10}), encoding="utf-8")
        self.write_ledger(kristine_ledger())
        client = FakeGmailClient(thread_bodies=kristine_bodies())
        ai = FakeAI(FAMILY_VERDICT)
        summary = self.connector.excavate(client=client, ai_caller=ai, model="fake-model")
        self.assertEqual(summary["dossiers"]["classified"], 1)
        self.assertEqual(len(ai.calls), 1)
        # the fresh verdict calibrated THIS run: pinned relationship, promoted
        ledger = cbase.load_ledger(self.connector.ledger_path)
        self.assertTrue(all(e["scores"]["relationship_signal"] == 1.0 for e in ledger))
        self.assertEqual(len(summary["promoted"]), 2)
        report = (self.root / "state" / "reports" / "gmail_excavation.md").read_text()
        self.assertIn("Dossier VIPs", report)
        self.assertIn("Owner's sister", report)
        self.assertIn("vip_blocklist", report)

    def test_excerpt_strips_quotes_and_truncates(self):
        from connectors import dossier as cdossier
        body = "fresh words here\n\n> old quoted line\nOn Jan 1, 2010, Kristine wrote:\nolder stuff"
        self.assertEqual(cdossier.strip_quoted(body), "fresh words here")
        long_body = " ".join(["word"] * 2500)
        excerpt = cdossier.truncate_words(long_body, 2000)
        self.assertTrue(excerpt.endswith("…"))
        self.assertLessEqual(len(excerpt.split()), 2001)

    def test_wrapper_parses_connector_dossier(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location("lifehug", SYSTEM / "lifehug.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        parser = mod.build_parser()
        args = parser.parse_args(["connector-dossier", "gmail", "--limit", "5",
                                  "--model", "some-model", "--redossier", "--dry-run"])
        self.assertTrue(callable(args.func))
        self.assertEqual(args.limit, 5)
        self.assertEqual(args.model, "some-model")
        self.assertTrue(args.redossier)
        self.assertTrue(args.dry_run)


if __name__ == "__main__":
    unittest.main()
