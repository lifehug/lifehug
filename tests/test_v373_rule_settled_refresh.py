"""v373: rule-forced timeline outcomes settle in code; re-keyed links remap.

All data is synthetic. ``RekeyedLinkTests`` rebuilds the shape of a real
refresh audited in the owner's vault (a stored link to a landmark stay whose
nickname changed, so its node id moved and a model call re-found it); the
synthetic records mint the same two node ids that audit saw, because node ids
are pure functions of kind, subject words and discriminator.
"""

from __future__ import annotations

import copy
import hashlib
import io
import json
import shutil
import sys
import tempfile
import unittest
from contextlib import ExitStack, redirect_stdout
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "system"))
sys.path.insert(0, str(ROOT / "tests"))

import classification_refresh  # noqa: E402
import classifier_context as cc  # noqa: E402
import classify_story as cs  # noqa: E402
import identity_resolution as ir  # noqa: E402
import landmark_projection as lp  # noqa: E402
import timeline_evidence as te  # noqa: E402
import timeline_settlement as ts  # noqa: E402
from test_archive_classification_batch import full_response  # noqa: E402

NOW = "2026-09-16T12:00:00Z"
#: The two ids the audited refresh saw: the stay called "Crossridge", then the
#: same stay (same place, same start) after its nickname became "Kentucky".
OLD_NODE = "node:f5f65c26a0bdeee3f2f194bd"
NEW_NODE = "node:ae4f04cbb9c9cb43f31bc64d"
RESIDENCE = "place/residence-5ca1ab1e0ddba11c0ffe"
STORY = (
    "I was shy. The first day at the new school was when I moved from "
    "California to Kentucky. The kids laughed at my board shorts, and for the "
    "whole year my nickname was Surf Ninja.\n"
)
QUOTES = (
    "when I moved from California to Kentucky",
    "for the whole year my nickname was Surf Ninja",
)


def month(value: str) -> dict:
    return {"best": value, "earliest": value, "latest": value, "granularity": "month",
            "confidence": "certain", "basis": "stated", "anchors": [], "provenance": []}


def stay(label: str) -> dict:
    return {"domain": "residences", "label": label, "nickname": label,
            "city": "Bowling Green, Kentucky", "place_ref": RESIDENCE,
            "span": {"start": month("1994-06"), "end": month("1995-06")}}


def linked_event(title: str, description: str, quote: str) -> dict:
    return {"title": title, "description": description, "subject": "self",
            "places": ["Kentucky"], "when_hint": None, "anchor": None, "date": None,
            "timeline_relation": {"relation": "within", "candidate_id": OLD_NODE,
                                  "entity_refs": [RESIDENCE], "evidence": {"quote": quote}}}


class VaultFixture:
    """A small real vault: rosters, a landmark stay, stories, classifications."""

    def build_vault(self) -> None:
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.root = Path(self.stack.enter_context(tempfile.TemporaryDirectory(
            prefix="lifehug-v373-")))
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
        (self.root / "state/entity_rosters/place.json").write_text(json.dumps({
            "version": 1, "type": "place", "entities": [
                {"name": "Kentucky", "slug": "kentucky", "aliases": []},
                {"name": "California", "slug": "california", "aliases": []},
                {"name": "12 Synthetic Lane, Bowling Green, Kentucky",
                 "slug": RESIDENCE.split("/", 1)[1], "aliases": ["Crossridge"],
                 "place_kind": "residence"},
            ]}))
        lp.file_landmark_record(self.root, "residences", stay("Crossridge"), ordinal=1, now=NOW)
        self.source = self.write_source("first-day", STORY)
        self.other = self.write_source("garden", "We planted tomatoes behind the garage.\n")

    def write_source(self, name: str, text: str) -> Path:
        path = self.root / "sources/manual" / f"{name}.md"
        path.write_text(f"---\ntitle: {name}\n---\n{text}")
        return path

    def file_full(self, source: Path, events: list[dict], batch_id: str) -> dict:
        snapshot = cc.build_context_snapshot(self.root, source)
        response = full_response(snapshot, events=events)
        return cs.file_batch_response({"schema_version": 1, "batch_id": batch_id,
            "skip_candidates": True, "items": [{
                "source_path": source.relative_to(self.root).as_posix(), "mode": "full",
                "response_text": json.dumps(response)}]})

    def classify_before_rename(self) -> None:
        receipt = self.file_full(self.source, [
            linked_event("First day at the new school",
                         "The narrator moved from California to Kentucky and started a new school.",
                         QUOTES[0]),
            linked_event("Nicknamed Surf Ninja",
                         "Kids at the new school called him Surf Ninja for the whole year after the move.",
                         QUOTES[1]),
        ], "v373-first")
        self.assertEqual(receipt["counts"]["accepted"], 1, receipt)
        receipt = self.file_full(self.other, [{
            "title": "Planting tomatoes", "description": "We planted tomatoes.",
            "subject": "self", "places": [], "when_hint": None, "anchor": None,
            "date": None, "timeline_relation": None}], "v373-garden")
        self.assertEqual(receipt["counts"]["accepted"], 1, receipt)

    def rename_stay(self) -> None:
        lp.retire_entry(self.root, domain="residences", entry_key="crossridge",
                        reason="the stay's nickname changed", occurred_at=NOW)
        lp.file_landmark_record(self.root, "residences", stay("Kentucky"), ordinal=2, now=NOW)

    def stored(self, source: Path) -> dict:
        return json.loads(cs.classification_path(source).read_text())


class RekeyedLinkTests(VaultFixture, unittest.TestCase):
    """A_RE_KEYED_LINK_REMAPS_BY_IDENTITY, on the audited shape."""

    def setUp(self) -> None:
        self.build_vault()
        self.classify_before_rename()

    def test_the_fixture_mints_the_audited_ids(self) -> None:
        self.assertEqual(
            ir.derive_episode_ref(event_kind="residence", subject_mention="Crossridge",
                                  discriminator="1994-06"), OLD_NODE)
        self.assertEqual(
            ir.derive_episode_ref(event_kind="residence", subject_mention="Kentucky",
                                  discriminator="1994-06"), NEW_NODE)
        self.assertEqual(
            [event["timeline_relation"]["candidate_id"] for event in self.stored(self.source)["events"]],
            [OLD_NODE, OLD_NODE])

    def test_a_renamed_stay_remaps_both_links_without_a_model(self) -> None:
        before = self.stored(self.source)
        self.rename_stay()
        snapshot = cc.build_context_snapshot(self.root, self.source)
        # v375: the retired nickname leaves no redirect the fold can follow,
        # so the stored links are named `link_orphaned` (still settled by rule).
        self.assertEqual(cc.refresh_reason(snapshot, before), cc.LINK_ORPHANED)
        self.assertEqual([row["candidate_id"] for row in snapshot["candidates"]], [NEW_NODE])
        settled = cs.timeline_settlement_for(self.source, snapshot)
        self.assertEqual(settled["judgment_keys"], [])
        self.assertEqual({note["rule"] for note in settled["notes"]},
                         {ts.A_RE_KEYED_LINK_REMAPS_BY_IDENTITY})

        report = cc.select_refresh_targets(self.root, [self.source, self.other], limit=5)
        self.assertEqual([(row["source_path"], row["settle"]) for row in report["targets"]],
                         [("sources/manual/first-day.md", "rule")])
        self.assertEqual(report["settle_counts"], {"rule": 1, "model": 0})

        plan = cs.build_batch_plan(limit=5, sources=[self.source], skip_candidates=True)
        self.assertEqual(plan["items"][0]["settle"], "rule")
        with mock.patch.object(cs, "classify_with_ai", side_effect=AssertionError("no model")):
            receipt = cs.file_batch_response({"schema_version": 1, "batch_id": "v373-rule",
                "skip_candidates": True, "items": [{
                    "source_path": "sources/manual/first-day.md", "mode": "timeline",
                    "response_text": ts.rule_response_text(plan["items"][0]["snapshot"])}]})
        self.assertEqual(receipt["counts"]["accepted"], 1, receipt)
        after = self.stored(self.source)
        for event, old, quote in zip(after["events"], before["events"], QUOTES):
            relation = event["timeline_relation"]
            self.assertEqual(relation["candidate_id"], NEW_NODE)
            self.assertEqual(relation["remapped_from"], OLD_NODE)
            self.assertEqual(relation["relation"], old["timeline_relation"]["relation"])
            self.assertEqual(relation["evidence"]["quote"], quote)
            self.assertEqual(relation["entity_refs"], ["place/kentucky"])
            self.assertEqual(event["timeline_resolution"]["status"], "linked")
            self.assertEqual(event["timeline_resolution"]["candidate_ids"], [NEW_NODE])
        self.assertEqual(after["settled_by"], "rule")
        self.assertEqual(after["model_used"], before["model_used"])
        self.assertEqual(len(after["rule_settlements"]), 2)
        # Filed once, current after: the remap does not queue itself again.
        self.assertIsNone(cc.refresh_reason(cc.build_context_snapshot(self.root, self.source), after))

    def test_classify_file_settles_by_rule_without_calling_the_model(self) -> None:
        self.rename_stay()
        with mock.patch.object(cs, "classify_with_ai", side_effect=AssertionError("no model")):
            self.assertEqual(cs.classify_file(self.source, "claude-test"), 0)
        after = self.stored(self.source)
        self.assertEqual(after["settled_by"], "rule")
        self.assertEqual({e["timeline_relation"]["candidate_id"] for e in after["events"]}, {NEW_NODE})

    def test_the_local_refresh_worker_files_rule_items_without_a_model(self) -> None:
        self.rename_stay()
        with mock.patch.dict("os.environ", {"LIFEHUG_RESOLVER": "0"}), \
                mock.patch.object(cs, "classify_with_ai", side_effect=AssertionError("no model")), \
                mock.patch.object(cs, "all_source_files", return_value=[self.source, self.other]):
            result = classification_refresh.run_batch(self.root, limit=5, model="claude-test")
        self.assertEqual(result["counts"]["accepted"], 1, result)
        self.assertEqual(self.stored(self.source)["settled_by"], "rule")

    def test_no_shared_entity_means_no_remap(self) -> None:
        """Same kind and start, a different place: the model decides."""
        self.rename_stay()
        snapshot = cc.build_context_snapshot(self.root, self.source)
        snapshot[cc.CANDIDATE_IDENTITY_FIELD][NEW_NODE]["identity_refs"] = ["place/kentucky"]
        settled = ts.settle(snapshot, self.stored(self.source), STORY)
        self.assertEqual(len(settled["judgment_keys"]), 2)
        self.assertEqual(settled["deltas"], {})

    def test_two_provable_targets_means_no_remap(self) -> None:
        self.rename_stay()
        snapshot = cc.build_context_snapshot(self.root, self.source)
        twin = copy.deepcopy(snapshot["candidates"][0])
        twin["candidate_id"] = "node:" + "9" * 24
        snapshot["candidates"].append(twin)
        snapshot[cc.CANDIDATE_IDENTITY_FIELD][twin["candidate_id"]] = copy.deepcopy(
            snapshot[cc.CANDIDATE_IDENTITY_FIELD][NEW_NODE])
        for context in snapshot["event_contexts"].values():
            context["candidate_ids"] = sorted([NEW_NODE, twin["candidate_id"]])
        settled = ts.settle(snapshot, self.stored(self.source), STORY)
        self.assertEqual(len(settled["judgment_keys"]), 2)

    def test_a_quote_that_no_longer_occurs_goes_to_the_model(self) -> None:
        self.rename_stay()
        snapshot = cc.build_context_snapshot(self.root, self.source)
        settled = ts.settle(snapshot, self.stored(self.source), STORY.replace("Surf Ninja", "Surfer"))
        self.assertEqual(len(settled["judgment_keys"]), 1)


def fixture_digests(case: VaultFixture) -> dict:
    """Every context digest the fixture vault produces, before and after the
    stay is renamed. Shared with the v372 run that produced ``V372_DIGESTS``."""
    digests = {}
    case.classify_before_rename()
    for label, source in (("story", case.source), ("garden", case.other)):
        snapshot = cc.build_context_snapshot(case.root, source)
        digests[f"{label}:before"] = snapshot["context_digest"]
        digests[f"{label}:stored"] = case.stored(source)["classification_snapshot"]["context_digest"]
    case.rename_stay()
    for label, source in (("story", case.source), ("garden", case.other)):
        digests[f"{label}:after"] = cc.build_context_snapshot(case.root, source)["context_digest"]
    return digests


#: Produced by the v372 builder (main at b96b6ea2) on exactly this fixture.
V372_DIGESTS = {
    "garden:after": "sha256:472a953c9d2482e6fe3854355f12d68f983d72aac25c13d6eb2b091cdd954f6e",
    "garden:before": "sha256:472a953c9d2482e6fe3854355f12d68f983d72aac25c13d6eb2b091cdd954f6e",
    "garden:stored": "sha256:472a953c9d2482e6fe3854355f12d68f983d72aac25c13d6eb2b091cdd954f6e",
    "story:after": "sha256:966e574ba05af46e83496f6845424153d54805ca642995ad06326272c65860c9",
    "story:before": "sha256:f9b2cccbe05bf13f68a4ecb29a79049675932ccdf4ce3f63eaf641654b77063e",
    "story:stored": "sha256:f9b2cccbe05bf13f68a4ecb29a79049675932ccdf4ce3f63eaf641654b77063e",
}


class DigestStabilityTests(VaultFixture, unittest.TestCase):
    """v373 changes no ``context_digest``: releasing it queues no refresh."""

    def setUp(self) -> None:
        self.build_vault()

    def test_every_digest_is_byte_identical_to_v372(self) -> None:
        digests = fixture_digests(self)
        # v375 (A_RE_KEY_IS_NOT_A_CHANGE_TO_A_LIFE) names the renamed stay by
        # the id the story filed, so the one digest a rename touches is keyed
        # differently; it still differs from the stored one, because the rename
        # also changed what the stay is about (its entity refs). Every other
        # digest is the v372 digest byte for byte.
        after = digests.pop("story:after")
        self.assertNotEqual(after, digests["story:stored"])
        expected = dict(V372_DIGESTS)
        expected.pop("story:after")
        self.assertEqual(digests, expected)

    def test_versions_are_unchanged(self) -> None:
        self.assertEqual(cc.PROMPT_VERSION, "contextual-timeline:3")
        self.assertEqual(cc.EXTRACTOR_VERSION, "story-classifier:2")


def _snapshot(source: Path, context: str, *, candidates: list[dict], contexts: dict) -> dict:
    return {
        "schema_version": 1,
        "source_revision": cc.source_revision(source),
        "context_digest": "sha256:" + hashlib.sha256(context.encode()).hexdigest(),
        "prompt_version": cc.PROMPT_VERSION,
        "extractor_version": cc.EXTRACTOR_VERSION,
        "context_complete": all(row["complete"] for row in contexts.values()),
        "context_truncated": not all(row["complete"] for row in contexts.values()),
        "remaining_candidate_count": 0,
        "catalog_omitted_count": 0,
        "remaining_decision_count": 0,
        "candidates": candidates,
        "event_contexts": contexts,
        "human_identity_decisions": [],
        "prior_event_identities": [],
    }


def _candidate(candidate_id: str, *, blocked: bool = False) -> dict:
    return {"candidate_id": candidate_id, "kind": "residence", "node_kind": "episode",
            "entity_refs": ["place/" + candidate_id.split(":")[1]],
            "unresolved_entity_mentions": ["somebody"] if blocked else [],
            "entity_ref_ambiguities": [], "temporal_shape": "interval"}


class ForcedOutcomeTests(unittest.TestCase):
    """A_RULE_FORCED_OUTCOME_NEEDS_NO_MODEL, one event per forced case."""

    EVENTS = {
        "truncated": ["node:a", "node:b"],
        "empty": [],
        "blocked": ["node:c"],
        "judged": ["node:d"],
    }

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="lifehug-v373-forced-")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / "sources/manual").mkdir(parents=True)
        (self.root / "state/classifications").mkdir(parents=True)
        self.source = self.root / "sources/manual/alpha.md"
        self.source.write_text("---\ntitle: Alpha\n---\nFour synthetic moments.\n")
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        for name, value in (
            ("REPO_DIR", self.root), ("SOURCES_DIR", self.root / "sources"),
            ("MANUAL_SOURCES_DIR", self.root / "sources/manual"),
            ("ANSWERS_DIR", self.root / "answers"),
            ("CLASSIFICATIONS_DIR", self.root / "state/classifications"),
            ("QUESTION_CANDIDATES_FILE", self.root / "state/question_candidates.json"),
        ):
            self.stack.enter_context(mock.patch.object(cs, name, value))
        self.stack.enter_context(redirect_stdout(io.StringIO()))
        self.events = [
            {"title": name, "description": f"The {name} moment.", "subject": "self",
             "places": [], "when_hint": None, "anchor": None, "date": None}
            for name in self.EVENTS
        ]
        self.keys = {event["title"]: te.event_key(event) for event in self.events}
        candidates = [_candidate("node:a"), _candidate("node:b"),
                      _candidate("node:c", blocked=True), _candidate("node:d")]
        self.snapshot = _snapshot(self.source, "new", candidates=candidates, contexts={
            self.keys[name]: {"event_key": self.keys[name], "candidate_ids": ids,
                              "complete": name != "truncated",
                              "input_fingerprint": "sha256:" + "f" * 64}
            for name, ids in self.EVENTS.items()
        })
        old = {**self.snapshot, "context_digest": "sha256:" + "0" * 64}
        self.base = {"version": 2, "source_path": "sources/manual/alpha.md",
                     "model_used": "synthetic-old", "reviewable": True,
                     "classification_snapshot": cc.snapshot_metadata(old),
                     "events": copy.deepcopy(self.events)}
        cs.write_json(cs.classification_path(self.source), self.base)
        self.stack.enter_context(mock.patch.object(
            cc, "load_context_catalog", return_value={"synthetic": True}))
        self.stack.enter_context(mock.patch.object(
            cc, "build_context_snapshot_from_catalog",
            side_effect=lambda *_args, **_kwargs: self.snapshot))
        self.stack.enter_context(mock.patch.object(
            cc, "build_context_snapshot", side_effect=lambda *_args, **_kwargs: self.snapshot))

    def test_each_forced_case_is_settled_and_only_judgment_remains(self) -> None:
        settled = ts.settle(self.snapshot, self.base, "Four synthetic moments.")
        self.assertEqual(settled["judgment_keys"], [self.keys["judged"]])
        statuses = {note["event_key"]: note["status"] for note in settled["notes"]}
        self.assertEqual(statuses, {
            self.keys["truncated"]: "incomplete",
            self.keys["empty"]: "missing_evidence",
            self.keys["blocked"]: "ambiguous",
        })
        self.assertEqual(ts.settle_mode(self.snapshot, self.base, "x", reason="context_changed"), "model")
        self.assertEqual(ts.settle_mode(self.snapshot, self.base, "x", reason="source_changed"), "model")

    def test_the_prompt_carries_only_the_event_needing_judgment(self) -> None:
        prompt = cs.build_prompt(self.source, {"title": "Alpha"}, "Four synthetic moments.",
                                 context_snapshot=self.snapshot, mode="timeline")
        self.assertIn(self.keys["judged"], prompt)
        for name in ("truncated", "empty", "blocked"):
            self.assertNotIn(self.keys[name], prompt)

    def _file(self, events: list[dict], batch_id: str) -> dict:
        response = {"_classification_mode": "timeline",
                    "_classification_snapshot": cc.snapshot_metadata(self.snapshot),
                    "events": events}
        return cs.file_batch_response({"schema_version": 1, "batch_id": batch_id,
            "skip_candidates": True, "items": [{"source_path": "sources/manual/alpha.md",
                "mode": "timeline", "response_text": json.dumps(response)}]})

    def _judged_delta(self) -> dict:
        return {"event_key": self.keys["judged"], "source_grounding": None,
                "timeline_relation": None, "timeline_resolution": {
                    "status": "missing_evidence", "candidate_ids": ["node:d"],
                    "reason": "Nothing in the story places it."}}

    def test_a_response_for_the_judgment_event_files_all_four(self) -> None:
        receipt = self._file([self._judged_delta()], "v373-judged")
        self.assertEqual(receipt["counts"]["accepted"], 1, receipt)
        stored = json.loads(cs.classification_path(self.source).read_text())
        self.assertEqual([e["timeline_resolution"]["status"] for e in stored["events"]],
                         ["incomplete", "missing_evidence", "ambiguous", "missing_evidence"])
        self.assertEqual(stored["settled_by"], "model")
        self.assertEqual(stored["model_used"], "external-agent")
        self.assertEqual(len(stored["rule_settlements"]), 3)
        for event in stored["events"][:3]:
            self.assertTrue(event["timeline_resolution"]["reason"].startswith("Settled by rule"))
            self.assertEqual(event["timeline_resolution"]["prompt_version"], cc.PROMPT_VERSION)

    def test_a_pre_v373_response_naming_every_event_still_files(self) -> None:
        rule_keys = [self.keys[name] for name in ("truncated", "empty", "blocked")]
        legacy = [{"event_key": key, "source_grounding": None, "timeline_relation": None,
                   "timeline_resolution": {"status": "not_temporal", "candidate_ids": [],
                                           "reason": "An old prompt answered this too."}}
                  for key in rule_keys]
        receipt = self._file([*legacy, self._judged_delta()], "v373-legacy")
        self.assertEqual(receipt["counts"]["accepted"], 1, receipt)
        stored = json.loads(cs.classification_path(self.source).read_text())
        self.assertEqual(stored["events"][0]["timeline_resolution"]["status"], "incomplete")

    def test_omitting_the_judgment_event_is_still_refused(self) -> None:
        receipt = self._file([], "v373-omitted")
        self.assertEqual(receipt["counts"]["refused"], 1)
        self.assertEqual(json.loads(cs.classification_path(self.source).read_text()), self.base)

    def test_a_fully_forced_source_needs_no_model_anywhere(self) -> None:
        self.snapshot["event_contexts"][self.keys["judged"]]["complete"] = False
        self.assertEqual(ts.settle_mode(self.snapshot, self.base, "x", reason="context_changed"), "rule")
        with mock.patch.object(cs, "classify_with_ai", side_effect=AssertionError("no model")):
            self.assertEqual(cs.classify_file(self.source, "claude-test"), 0)
        stored = json.loads(cs.classification_path(self.source).read_text())
        self.assertEqual(stored["settled_by"], "rule")
        self.assertEqual(stored["model_used"], "synthetic-old")
        self.assertEqual({row["rule"] for row in stored["rule_settlements"]},
                         {ts.A_RULE_FORCED_OUTCOME_NEEDS_NO_MODEL})

    def test_the_plan_marks_a_fully_forced_source_rule(self) -> None:
        self.snapshot["event_contexts"][self.keys["judged"]]["complete"] = False
        plan = cs.build_batch_plan(limit=5, sources=[self.source], skip_candidates=True)
        self.assertEqual([item["settle"] for item in plan["items"]], ["rule"])
        response = json.loads(ts.rule_response_text(plan["items"][0]["snapshot"]))
        self.assertEqual(response, {"_classification_mode": "timeline",
                                    "_classification_snapshot": plan["items"][0]["snapshot"],
                                    "events": []})

if __name__ == "__main__":
    unittest.main()
