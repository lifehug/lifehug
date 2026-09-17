"""Real receipt -> classification -> migration -> compile currency regressions."""

from __future__ import annotations

import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from contextlib import ExitStack, redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "system"))

import classifier_claims
import classifier_context as cc
import classify_story as cs
import event_identity as ei
import landmark_projection as lp
import temporal_claims as tc
import temporal_publication as pub
import temporal_store as store
import temporal_timeline as tt
import timeline_evidence as te
from test_archive_classification_batch import full_response
from test_classifier_context import date

NOW = "2026-09-16T12:00:00Z"


def event(*, subject="self", title="Arrival"):
    return {"title": title, "description": "I lived in Cedarport.",
            "subject": subject, "places": ["Cedarport"],
            "date": None, "timeline_relation": None}


class IndependentContextTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.root = Path(self.stack.enter_context(tempfile.TemporaryDirectory(
            prefix="lifehug-independent-context-")))
        for directory in ("sources/manual", "answers", "state/classifications",
                          "state/entity_rosters", "wiki", "home"):
            (self.root / directory).mkdir(parents=True, exist_ok=True)
        for name in ("question-bank.md", "rotation.json", "coverage.json"):
            target = name if name.endswith(".md") else "state/" + name
            shutil.copyfile(ROOT / "system" / name, self.root / target)
        for name, value in (
            ("REPO_DIR", self.root), ("SOURCES_DIR", self.root / "sources"),
            ("MANUAL_SOURCES_DIR", self.root / "sources/manual"),
            ("ANSWERS_DIR", self.root / "answers"),
            ("CLASSIFICATIONS_DIR", self.root / "state/classifications"),
            ("QUESTION_CANDIDATES_FILE", self.root / "state/question_candidates.json"),
        ):
            self.stack.enter_context(mock.patch.object(cs, name, value))
        self.stack.enter_context(mock.patch.object(cs, "load_mission", return_value="Synthetic."))
        self.stack.enter_context(redirect_stdout(io.StringIO()))
        self.sources = [self.source("producer", "I lived in Cedarport in 1997."),
                        self.source("observer", "I found a letter in Cedarport."),
                        self.source("fallback", "I wrote a notebook.")]
        self.roster = {"version": 1, "type": "place", "entities": [
            {"name": "Cedarport", "slug": "cedarport", "aliases": []},
            {"name": "Orchardvale", "slug": "orchardvale", "aliases": []},
        ]}
        self.roster_path = self.root / "state/entity_rosters/place.json"
        self.roster_path.write_text(json.dumps(self.roster))

    def source(self, name, text):
        path = self.root / "sources/manual" / f"{name}.md"
        path.write_text(f"---\ntitle: {name}\n---\n{text}\n")
        return path

    def migrate(self):
        return classifier_claims.migrate_classifier_moments(
            self.root, publish=False, dry_run=False, now=NOW)

    def publish(self):
        return pub.publish(self.root, roster_snapshot=self.roster, now=NOW)

    def plan(self):
        return cs.build_batch_plan(limit=10, sources=self.sources, skip_candidates=True)

    def file(self, *, events):
        plan = self.plan()
        items = []
        for item in plan["items"]:
            self.assertEqual(item["mode"], "full")
            source = self.root / item["source_path"]
            response = full_response(cc.build_context_snapshot(self.root, source), events=events if
                item["source_path"] == "sources/manual/producer.md" else [])
            items.append({"source_path": item["source_path"], "mode": "full",
                          "response_text": json.dumps(response)})
        receipt = cs.file_batch_response({"schema_version": 1,
            "batch_id": "synthetic-first", "skip_candidates": True, "items": items})
        self.assertEqual(receipt["counts"]["accepted"], 3)
        remaining = self.plan()
        self.assertEqual(remaining["pending_count"], 0, remaining)

    def bind(self, claims):
        manifest = ei.read_telling_manifest(self.root)
        refs = {row["telling_ref"] for row in manifest["tellings"]
                if row.get("source_path") == "sources/manual/producer.md"
                or set(row.get("claim_ids", [])).intersection(claims)}
        self.episode_id = "episode:" + "a" * 24
        for ref in sorted(refs):
            ei.file_event_identity(self.root, telling_ref=ref,
                episode_id=self.episode_id, relation="same", origin="confirmed",
                created_at=NOW)
        ei.rebuild_telling_manifest(self.root)

    def independent_anchor(self):
        path = self.source("anchor", "I lived in Cedarport from 1994 to 1998.")
        claim = tc.validate_temporal_claim({
            "source_ref": {"source_id": "conversation:synthetic-residence",
                "revision": store.payload_sha256(path.read_text()),
                "source_path": "sources/manual/anchor.md"},
            "source_kind": "conversation", "claim_type": "date",
            "subject_mention": "Cedarport", "subject_ref": "place/cedarport",
            "event_kind": "residence", "temporal_value": date("1994/1998"),
            "basis": "explicit", "confidence": 1.0,
            "evidence": [{"quote": "I lived in Cedarport from 1994 to 1998."}],
            "extractor_version": "landmark_recorder/rule:1",
        }, now=NOW)
        store.write_receipt(self.root, {"source_ref": claim["source_ref"],
            "extractor_version": "landmark_recorder/rule:1", "claims": [claim]}, now=NOW)
        return claim

    def assert_publication_fixed_point(self):
        frozen = {p: p.read_bytes() for p in self.root.rglob("*") if p.is_file()
                  and ("sources" in p.relative_to(self.root).parts
                       or "entity_rosters" in p.parts)}
        snapshots = [cc.snapshot_metadata(cc.build_context_snapshot(self.root, p))
                     for p in self.sources]
        for _ in range(2):
            self.migrate()
            self.assertEqual(self.plan()["pending_count"], 0)
            self.publish()
            self.assertEqual(self.plan()["pending_count"], 0)
        env = {k: v for k, v in os.environ.items() if not any(
            token in k.upper() for token in ("API_KEY", "TOKEN", "SECRET", "CREDENTIAL"))}
        env.update(LIFEHUG_VAULT_ROOT=str(self.root),
                   LIFEHUG_FRAMEWORK_SYSTEM_DIR=str(ROOT / "system"),
                   HOME=str(self.root / "home"), PYTHONDONTWRITEBYTECODE="1")
        result = subprocess.run([sys.executable, str(ROOT / "system/wiki_compile.py"),
                                 "--no-ai"], cwd=self.root, env=env,
                                capture_output=True, text=True, timeout=120)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.plan()["pending_count"], 0)
        self.assertEqual(snapshots, [cc.snapshot_metadata(cc.build_context_snapshot(
            self.root, p)) for p in self.sources])
        self.assertTrue(all(p.read_bytes() == raw for p, raw in frozen.items()))

    def test_mixed_episode_three_source_file_migrate_compile_fixed_point(self):
        claim = self.independent_anchor()
        cs.classification_path(self.sources[0]).write_text(json.dumps({
            "version": 2, "source_path": "sources/manual/producer.md",
            "events": [event(subject="Cedarport")]}))
        self.migrate()
        self.bind({claim["claim_id"]})
        self.publish()
        self.file(events=[event()])
        self.assert_publication_fixed_point()

    def test_four_to_two_retirement_does_not_borrow_sparse_identity_metadata(self):
        first = lp.file_landmark_record(self.root, "residences", {
            "domain": "residences", "label": "Cedar Shelter", "city": "Cedar Shelter",
            "span": {"start": date("1994")}}, ordinal=1, now=NOW)
        # A separate independent telling keeps the participation seed populated
        # when the first telling is explicitly bound to another episode.
        lp.file_landmark_record(self.root, "residences", {
            "domain": "residences", "label": "Cedar Shelter", "city": "Cedar Shelter",
            "span": {"start": date("1994"), "end": date("1998")}}, ordinal=2, now=NOW)
        cs.classification_path(self.sources[0]).write_text(json.dumps({
            "version": 2, "source_path": "sources/manual/producer.md",
            "events": [event(title="Arrival"), event(title="Return")]}))
        self.migrate()
        self.bind({c["claim_id"] for c in first["claims"]})
        self.publish()
        before = next(n for n in pub.read_projection(self.root)["nodes"]
                      if n.get("episode_id") == self.episode_id)
        self.assertEqual(len(before["input_claim_refs"]), 4)
        self.assertEqual(before["event_kind"], "moment")
        self.assertEqual(before["subject_refs"], ["Cedar Shelter", "self"])
        self.sources[2].write_text(
            "---\ntitle: fallback\n---\nI wrote a notebook at Cedar Shelter.\n"
        )
        candidate = next(c for c in cc.build_context_snapshot(
            self.root, self.sources[2])["candidates"] if c["episode_id"] == self.episode_id)
        self.assertEqual(candidate["kind"], "episode")
        self.assertEqual(candidate["entity_refs"], [])
        self.assertEqual(candidate["unresolved_entity_mentions"], ["Cedar Shelter"])
        self.file(events=[])
        self.assert_publication_fixed_point()
        after = next(n for n in pub.read_projection(self.root)["nodes"]
                     if n.get("episode_id") == self.episode_id)
        self.assertEqual(after["node_id"], before["node_id"])
        self.assertEqual(len(after["input_claim_refs"]), 2)
        self.assertIsNone(after.get("event_kind"))
        self.assertEqual(after["subject_refs"], ["Cedar Shelter"])
        self.assertEqual(after["best_temporal_value"], before["best_temporal_value"])
        claims = store.fold_active_index(self.root)["claims"]
        retired = [c for c in claims if c["claim_id"] in before["input_claim_refs"]
                   and c["claim_id"] not in after["input_claim_refs"]]
        self.assertEqual([c["status"] for c in retired], ["superseded", "superseded"])

    def test_catalog_is_read_only_and_one_fold_serves_500_snapshots(self):
        self.independent_anchor()
        paths = [self.source(f"bulk-{i}", "A story about Cedarport.") for i in range(500)]
        before = {p.relative_to(self.root): p.read_bytes()
                  for p in self.root.rglob("*") if p.is_file()}
        with mock.patch.object(store, "fold_active_index", wraps=store.fold_active_index) as fold, \
                mock.patch.object(tt, "derive_calculated_timeline",
                                  wraps=tt.derive_calculated_timeline) as derive:
            catalog = cc.load_context_catalog(self.root)
            snapshots = [cc.build_context_snapshot_from_catalog(self.root, p, catalog)
                         for p in paths]
        self.assertTrue(all(s["candidate_count"] == 1 for s in snapshots))
        self.assertEqual(fold.call_count, 1)
        self.assertEqual(derive.call_count, 1)
        self.assertEqual(before, {p.relative_to(self.root): p.read_bytes()
                                 for p in self.root.rglob("*") if p.is_file()})

    def test_machine_manifest_rekeys_do_not_select_candidates_or_human_decisions(self):
        self.independent_anchor()
        before = cc.build_context_snapshot(self.root, self.sources[0])
        record, _ = ei.file_event_identity(self.root,
            telling_ref="classification:other#aaaaaaaaaaaa",
            episode_id="episode:" + "b" * 24, relation="not_same", origin="confirmed",
            created_at=NOW)
        ei.write_telling_manifest(self.root, {"tellings": [{
            "telling_ref": "classification:new#bbbbbbbbbbbb",
            "source_path": "sources/manual/producer.md",
            "aliases": [record["telling_ref"]],
            "bound_identity_ids": [record["identity_id"]],
        }]})
        after = cc.build_context_snapshot(self.root, self.sources[0])
        self.assertNotEqual(before["prior_event_identities"], after["prior_event_identities"])
        self.assertEqual(before["candidates"], after["candidates"])
        self.assertEqual(before["human_identity_decisions"], after["human_identity_decisions"])
        self.assertEqual(before["context_digest"], after["context_digest"])

    def record_claim(self, source_id, **fields):
        claim = tc.validate_temporal_claim({
            "source_ref": {"source_id": source_id,
                           "revision": store.payload_sha256(source_id)},
            "source_kind": "conversation", "basis": "explicit", "confidence": 1.0,
            "subject_mention": "Synthetic subject",
            "evidence": [{"quote": "Synthetic evidence"}], "extractor_version": "test:1",
            **fields,
        }, now=NOW)
        store.write_receipt(self.root, {"source_ref": claim["source_ref"],
            "extractor_version": "test:1", "claims": [claim]}, now=NOW)
        return claim

    def test_ordering_cannot_import_classifier_date_support_into_independent_node(self):
        independent = self.record_claim("conversation:job", claim_type="occurrence",
            subject_ref="self", subject_mention="My job", event_kind="job")
        machine = self.record_claim("classification:other#aaaaaaaaaaaa", claim_type="date",
            subject_ref="self", subject_mention="The move", event_kind="move",
            temporal_value=date("1994/1998"))
        self.publish()
        nodes = pub.read_projection(self.root)["nodes"]
        job = next(n for n in nodes if independent["claim_id"] in n["input_claim_refs"])
        move = next(n for n in nodes if machine["claim_id"] in n["input_claim_refs"])
        before = cc.build_context_snapshot(self.root, self.sources[2])
        self.assertEqual(before["candidates"], [])
        store.file_ordering_constraint(self.root, relation="within",
            subject_node_id=job["node_id"], anchor_node_ids=[move["node_id"]])
        self.publish()
        placed_job = next(n for n in pub.read_projection(self.root)["nodes"]
                          if n["node_id"] == job["node_id"])
        self.assertTrue(placed_job["usable_placement"])
        after = cc.build_context_snapshot(self.root, self.sources[2])
        self.assertEqual(after["candidates"], [])
        self.assertEqual(before["context_digest"], after["context_digest"])

    def test_ongoing_landmark_does_not_acquire_wall_clock_bounds(self):
        lp.file_landmark_record(self.root, "residences", {
            "domain": "residences", "label": "Cedarport", "city": "Cedarport",
            "span": {"start": date("1994")}, "ongoing": True}, ordinal=1, now=NOW)
        derive = tt.derive_calculated_timeline
        snapshots = []
        for now in ("2026-09-16T00:00:00Z", "2028-10-20T00:00:00Z"):
            with mock.patch.object(tt, "derive_calculated_timeline",
                side_effect=lambda *args, **kwargs: derive(*args, **kwargs, now=now)):
                snapshots.append(cc.build_context_snapshot(self.root, self.sources[1]))
        self.assertEqual(snapshots[0]["candidate_count"], 1)
        self.assertEqual(snapshots[0]["candidates"], snapshots[1]["candidates"])
        self.assertEqual(snapshots[0]["context_digest"], snapshots[1]["context_digest"])

    def test_genuine_independent_date_alias_and_human_changes_remain_dependencies(self):
        anchor = self.independent_anchor()
        lp.file_landmark_record(self.root, "residences", {
            "domain": "residences", "label": "Orchardvale", "city": "Orchardvale",
            "span": {"start": date("1988"), "end": date("1990")}}, ordinal=2, now=NOW)
        unrelated = self.source("unrelated", "I lived in Orchardvale.")
        before = cc.build_context_snapshot(self.root, self.sources[1])
        other_before = cc.build_context_snapshot(self.root, unrelated)
        fallback_before = cc.build_context_snapshot(self.root, self.sources[2])
        store.supersede_claims(self.root, [anchor["claim_id"]], reason="The date was 1995.")
        self.record_claim("conversation:corrected-residence", claim_type="date",
            subject_ref="place/cedarport", event_kind="residence", temporal_value=date("1995/1998"))
        changed = cc.build_context_snapshot(self.root, self.sources[1])
        self.assertNotEqual(changed["context_digest"], before["context_digest"])
        self.assertEqual(cc.build_context_snapshot(self.root, unrelated)["context_digest"],
                         other_before["context_digest"])
        # A source with no matching reference is not poisoned by global changes.
        self.assertEqual(cc.build_context_snapshot(self.root, self.sources[2])["context_digest"],
                         fallback_before["context_digest"])
        with self.assertRaises(cc.ClassifierContextError) as refused:
            cc.validate_response(full_response(before), changed, self.sources[1].read_text())
        self.assertEqual(refused.exception.code, cc.ContextFailureCode.SNAPSHOT_MISMATCH)
        self.roster["entities"][0]["aliases"] = ["Thunderhead"]
        self.roster_path.write_text(json.dumps(self.roster))
        aliased = cc.build_context_snapshot(self.root, self.sources[1])
        self.assertNotEqual(aliased["context_digest"], changed["context_digest"])
        self.assertEqual(cc.build_context_snapshot(self.root, unrelated)["context_digest"],
                         other_before["context_digest"])
        # A human decision about a supplied independent episode is authoritative.
        ei.file_event_identity(self.root, telling_ref="conversation:corrected-residence",
            episode_id="episode:" + "c" * 24, relation="same", origin="confirmed", created_at=NOW)
        human = cc.build_context_snapshot(self.root, self.sources[1])
        self.assertNotEqual(human["context_digest"], aliased["context_digest"])
        self.assertEqual(cc.build_context_snapshot(self.root, unrelated)["context_digest"],
                         other_before["context_digest"])

    def test_mixed_grounded_fact_cannot_feed_its_source_context(self):
        anchor = self.independent_anchor()
        self.publish()
        anchor_node = next(
            node for node in pub.read_projection(self.root)["nodes"]
            if anchor["claim_id"] in node["input_claim_refs"]
        )
        self.sources[0].write_text(
            "---\ntitle: producer\n---\n"
            "I recorded Cedarport in 1996 and corrected the date to 1997.\n"
        )
        raw = self.sources[0].read_text()
        revision = store.payload_sha256(raw)

        def grounded_claim(year):
            quote = str(year)
            start = raw.index(quote)
            grounded_event = {
                **event(subject="Cedarport", title="Cedarport residence"),
                "date": {"stated": quote, "age": None, "anchor_ref": None,
                         "relation": None},
                "source_grounding": {
                    "kind": "date",
                    "quote": quote,
                    "temporal_quote": quote,
                    "subject_quote": "Cedarport",
                    "start": start,
                    "end": start + len(quote),
                    "source_revision": revision,
                },
            }
            generated = classifier_claims.event_claims(
                stem="producer",
                event=grounded_event,
                revision=revision,
                source_path="sources/manual/producer.md",
                now=NOW,
            )[0]
            return tc.validate_temporal_claim({
                **generated,
                "subject_ref": "place/cedarport",
                "event_ref": anchor_node["node_id"],
            }, now=NOW)

        first = grounded_claim(1997)
        store.write_receipt(self.root, {
            "source_ref": first["source_ref"],
            "extractor_version": classifier_claims.CLASSIFIER_EXTRACTOR,
            "claims": [first],
        }, now=NOW)
        producer_before = cc.build_context_snapshot(self.root, self.sources[0])
        target_before = next(
            row for row in producer_before["candidates"]
            if row["candidate_id"] == anchor_node["node_id"]
        )
        self.assertEqual(target_before["supported_bounds"]["best"], "1994/1998")
        self.assertNotIn(
            "sources/manual/producer.md",
            {row["source_path"] for row in target_before["grounding_identity"]},
        )
        self.assertEqual(
            cc.build_context_snapshot(self.root, self.sources[0])["context_digest"],
            producer_before["context_digest"],
        )
        observer = cc.build_context_snapshot(self.root, self.sources[1])
        observed = next(
            row for row in observer["candidates"]
            if row["candidate_id"] == anchor_node["node_id"]
        )
        self.assertIn(
            "sources/manual/producer.md",
            {row["source_path"] for row in observed["grounding_identity"]},
        )

    def test_grounded_source_roles_survive_migration_and_disambiguate_paraphrase(self):
        (self.root / "state/entity_rosters/organization.json").write_text(json.dumps({
            "version": 1,
            "type": "organization",
            "entities": [{"name": "Northstar", "slug": "northstar", "aliases": []}],
        }))
        founder = self.source("northstar-founder", "I founded Northstar in 2012.")
        employee = self.source("northstar-employee", "I joined Northstar payroll in 2014.")
        consumer = self.source(
            "northstar-memory",
            "I launched Northstar before I ever joined its payroll.",
        )

        cases = (
            (founder, "Northstar founding", "I founded Northstar in 2012.", "2012"),
            (employee, "Northstar employment", "I joined Northstar payroll in 2014.", "2014"),
        )
        for source, title, description, year in cases:
            snapshot = cc.build_context_snapshot(self.root, source)
            extracted = {
                "title": title,
                "description": description,
                "subject": "Northstar",
                "places": [],
                "date": {
                    "stated": year,
                    "age": None,
                    "anchor_ref": None,
                    "relation": None,
                },
                "timeline_relation": None,
                "source_grounding": {
                    "quote": description,
                    "temporal_quote": year,
                    "subject_quote": "Northstar",
                    "kind": "date",
                },
            }
            self.assertEqual(
                cs.classify_file(
                    source,
                    "synthetic-recorded",
                    skip_candidates=True,
                    precomputed_result=full_response(snapshot, events=[extracted]),
                ),
                0,
            )

        migrated = self.migrate()
        self.assertEqual(migrated["claims_by_type"]["date"], 2)
        snapshot = cc.build_context_snapshot(self.root, consumer)
        northstar = [
            row for row in snapshot["candidates"]
            if row.get("entity_refs") == ["organization/northstar"]
        ]
        self.assertEqual(
            {row["event_role"] for row in northstar},
            {"founded", "job"},
            snapshot,
        )
        founding = next(row for row in northstar if row["event_role"] == "founded")
        quote = "I launched Northstar before I ever joined its payroll."
        self.assertTrue(te.quote_disambiguates(founding, northstar, quote))

        linked = {
            "title": "Northstar founding",
            "description": quote,
            "subject": "Northstar",
            "places": [],
            "date": None,
            "source_grounding": None,
            "timeline_relation": {
                "relation": "within",
                "candidate_id": founding["candidate_id"],
                "entity_refs": ["organization/northstar"],
                "evidence": {"quote": quote},
            },
        }
        validated = cc.validate_response(
            full_response(snapshot, events=[linked]),
            snapshot,
            quote,
        )
        self.assertEqual(
            validated["events"][0]["timeline_relation"]["candidate_id"],
            founding["candidate_id"],
        )

    def test_grounded_roles_survive_legacy_moment_episode_bindings(self):
        (self.root / "state/entity_rosters/organization.json").write_text(json.dumps({
            "version": 1,
            "type": "organization",
            "entities": [{"name": "Northstar", "slug": "northstar", "aliases": []}],
        }))
        founder = self.source("legacy-founder", "I founded Northstar in 2012.")
        employee = self.source("legacy-employee", "I joined Northstar payroll in 2014.")
        consumer = self.source(
            "legacy-memory",
            "I launched Northstar before I ever joined its payroll.",
        )
        cases = (
            (founder, "Northstar founding", "I founded Northstar in 2012.", "2012"),
            (employee, "Northstar employment", "I joined Northstar payroll in 2014.", "2014"),
        )
        initial_events = {}
        for source, title, description, year in cases:
            initial_events[source] = {
                "title": title,
                "description": description,
                "subject": "Northstar",
                "places": [],
                "date": {
                    "stated": year,
                    "age": None,
                    "anchor_ref": None,
                    "relation": None,
                },
                "source_grounding": None,
                "timeline_relation": None,
            }
            cs.classification_path(source).write_text(json.dumps({
                "version": 2,
                "source_path": str(source.relative_to(self.root)),
                "events": [initial_events[source]],
            }))
        self.migrate()

        manifest = ei.read_telling_manifest(self.root)
        episode_ids = []
        for source, *_unused in cases:
            relative = str(source.relative_to(self.root))
            telling = next(
                row for row in manifest["tellings"]
                if row.get("source_path") == relative and row.get("status") == "active"
            )
            operation_id = ei.operation_digest(
                authority="human",
                op="create",
                rule_version=ei.IDENTITY_RULE_VERSION,
                member_refs=[telling["telling_ref"]],
            )
            episode_id = ei.episode_id_for(operation_id)
            binding = {
                "telling_ref": telling["telling_ref"],
                "episode_id": episode_id,
                "relation": "same",
                "origin": "confirmed",
                "operation_id": operation_id,
                "source_ref": "sources/identity/legacy-moment.md",
                "created_at": NOW,
            }
            binding_id = ei.validate_event_identity(binding)["identity_id"]
            ei.file_operation_envelope(
                self.root,
                operation={
                    "authority": "human",
                    "op": "create",
                    "episode_id": episode_id,
                    "members": [telling["telling_ref"]],
                    "creates_binding_ids": [binding_id],
                    "canonical_event_kind": "moment",
                    "source_ref": "sources/identity/legacy-moment.md",
                    "created_at": NOW,
                },
                bindings=[binding],
            )
            episode_ids.append(episode_id)
        ei.rebuild_telling_manifest(self.root)
        identities_before = ei.load_event_identities(self.root)
        operations_before = ei.load_episode_operations(self.root)

        for source, title, description, year in cases:
            refreshed = {
                **initial_events[source],
                "source_grounding": {
                    "quote": description,
                    "temporal_quote": year,
                    "subject_quote": "Northstar",
                    "kind": "date",
                },
            }
            snapshot = cc.build_context_snapshot(self.root, source)
            self.assertEqual(
                cs.classify_file(
                    source,
                    "synthetic-recorded",
                    skip_candidates=True,
                    precomputed_result=full_response(snapshot, events=[refreshed]),
                ),
                0,
            )
        self.migrate()

        snapshot = cc.build_context_snapshot(self.root, consumer)
        candidates = [
            row for row in snapshot["candidates"]
            if row.get("episode_id") in episode_ids
        ]
        self.assertEqual({row["kind"] for row in candidates}, {"moment"})
        self.assertEqual(
            {row["event_role"] for row in candidates},
            {"founded", "job"},
            snapshot,
        )
        founding = next(row for row in candidates if row["event_role"] == "founded")
        self.assertTrue(te.quote_disambiguates(
            founding,
            candidates,
            "I launched Northstar before I ever joined its payroll.",
        ))
        self.assertEqual(ei.load_event_identities(self.root), identities_before)
        self.assertEqual(ei.load_episode_operations(self.root), operations_before)

    def test_linked_event_absorbs_real_bound_correction_without_model_refresh(self):
        anchor = self.independent_anchor()
        self.publish()
        observer = self.sources[1]
        before = cc.build_context_snapshot(self.root, observer)
        stay = next(row for row in before["candidates"]
                    if row["event_role"] == "residence")
        linked_event = {
            "title": "Finding the letter",
            "description": "I found a letter in Cedarport.",
            "subject": "self",
            "places": ["Cedarport"],
            "date": None,
            "source_grounding": None,
            "timeline_relation": {
                "relation": "within",
                "candidate_id": stay["candidate_id"],
                "entity_refs": ["place/cedarport"],
                "evidence": {"quote": "I found a letter in Cedarport"},
            },
        }
        response = full_response(before, events=[linked_event])
        with redirect_stdout(io.StringIO()):
            self.assertEqual(cs.classify_file(
                observer, "synthetic-recorded", skip_candidates=True,
                precomputed_result=response,
            ), 0)
        self.migrate()
        self.publish()

        def linked_node():
            return next(
                node for node in pub.read_projection(self.root)["nodes"]
                if any(str(ref).startswith("claim:") for ref in node["input_claim_refs"])
                and node.get("event_kind") == "moment"
                and node.get("label") == "Finding the letter"
            )

        first = linked_node()
        self.assertEqual(first["best_temporal_value"]["best"], "1994/1998")
        first_plan = cs.build_batch_plan(
            limit=10, sources=[observer], skip_candidates=True
        )
        self.assertEqual(first_plan["pending_count"], 0)

        store.supersede_claims(
            self.root, [anchor["claim_id"]], reason="The stay ended in 1999."
        )
        replacement = tc.validate_temporal_claim({
            "source_ref": {
                "source_id": "conversation:synthetic-residence-correction",
                "revision": store.payload_sha256("corrected 1995/1999"),
                "source_path": "sources/manual/anchor.md",
            },
            "source_kind": "conversation",
            "claim_type": "date",
            "subject_mention": "Cedarport",
            "subject_ref": "place/cedarport",
            "event_kind": "residence",
            "temporal_value": date("1995/1999"),
            "basis": "explicit",
            "confidence": 1.0,
            "evidence": [{"quote": "I lived in Cedarport from 1995 to 1999."}],
            "extractor_version": "landmark_recorder/rule:1",
        }, now=NOW)
        store.write_receipt(self.root, {
            "source_ref": replacement["source_ref"],
            "extractor_version": "landmark_recorder/rule:1",
            "claims": [replacement],
        }, now=NOW)
        self.publish()

        corrected = linked_node()
        self.assertEqual(corrected["node_id"], first["node_id"])
        self.assertEqual(corrected["best_temporal_value"]["best"], "1995/1999")
        corrected_plan = cs.build_batch_plan(
            limit=10, sources=[observer], skip_candidates=True
        )
        self.assertEqual(corrected_plan["pending_count"], 0)

    def test_legacy_unclassified_prefilter_shares_one_catalog(self):
        self.independent_anchor()
        self.file(events=[])
        with mock.patch.object(cs, "all_source_files", return_value=self.sources), \
                mock.patch.object(store, "fold_active_index", wraps=store.fold_active_index) as fold, \
                mock.patch.object(tt, "derive_calculated_timeline",
                                  wraps=tt.derive_calculated_timeline) as derive:
            result = cs.cmd_classify_all(SimpleNamespace(model="synthetic", unclassified=True,
                stale_first=False, limit=50, dry_run=True, emit_prompts=None))
        self.assertEqual(result, 0)
        self.assertEqual(fold.call_count, 1)
        self.assertEqual(derive.call_count, 1)


if __name__ == "__main__":
    unittest.main()
