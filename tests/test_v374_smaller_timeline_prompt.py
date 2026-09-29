"""v374: a smaller timeline prompt. All data is synthetic.

The fixture is shaped like the audited refresh prompts: many candidates, each
carrying freshness-only grounding identity; stored events whose old
resolutions list every candidate id; forced events next to events that need
judgment.
"""

from __future__ import annotations

import copy
import hashlib
import io
import json
import sys
import tempfile
import unittest
from contextlib import ExitStack, redirect_stdout
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "system"))

import classifier_context as cc  # noqa: E402
import classify_story as cs  # noqa: E402
import timeline_evidence as te  # noqa: E402

#: `len(build_prompt(...))` for :func:`measurement_case` under the v373 builder
#: (branch classify/rule-forced-outcomes-and-link-remap at b395745d).
V373_PROMPT_CHARS = 191_750

STORY = (
    "The summer I turned twelve we drove north. I remember the orchard and the "
    "first harvest, and later the cannery job that paid for my first bicycle.\n"
)
N_CANDIDATES = 48


def _sha(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode()).hexdigest()


def _candidate(index: int, *, blocked: bool = False) -> dict:
    name = f"Synthetic stay {index:02d}"
    ref = f"place/synthetic-{index:02d}"
    year = 1980 + index % 20
    return {
        "candidate_id": "node:" + hashlib.sha256(name.encode()).hexdigest()[:24],
        "node_kind": "episode",
        "episode_id": "episode:" + hashlib.sha256(ref.encode()).hexdigest()[:24],
        "kind": "residence",
        "event_role": "residence",
        "name": name,
        "aliases": [name, f"the {index:02d} place"],
        "canonical_roster_terms": [{"entity_ref": ref, "terms": [name, f"the {index:02d} place"]}],
        "entity_refs": [ref],
        "unresolved_entity_mentions": ["somebody"] if blocked else [],
        "entity_ref_ambiguities": [],
        "supported_bounds": {"best": f"{year}/{year + 2}", "earliest": str(year),
                             "latest": str(year + 2), "granularity": "range"},
        "temporal_shape": "interval",
        "basis": "explicit",
        "conflict_state": "none",
        "alternatives": [],
        "reference_keys": sorted({name.lower(), f"the {index:02d} place", "home", "lived",
                                  "move", "moved", "residence", "stay", ref.replace("/", " ")}),
        "grounding_identity": [
            {"claim_type": kind, "subject_ref": None, "subject_mention": name,
             "temporal_value": {"anchors": [], "basis": "stated", "best": str(year + offset),
                                "confidence": "certain", "earliest": str(year + offset),
                                "granularity": "year", "latest": str(year + offset),
                                "provenance": []},
             "source_path": f"sources/landmarks/entry-{index:02d}{offset}.md",
             "source_revision": _sha(f"{index}-{offset}"),
             "evidence": [{"quote": f"residences.span = {year + offset} (synthetic record {index:02d})"}]}
            for offset, kind in ((0, "identity"), (0, "date"), (2, "date"))
        ],
        "candidate_set_complete": True,
        "relevant_event_keys": [],
    }


def measurement_case() -> tuple[dict, list[dict]]:
    """``(snapshot, events)``: 8 events, 4 settled by rule, 4 needing judgment."""
    candidates = [_candidate(i, blocked=(i == 7)) for i in range(N_CANDIDATES)]
    ids = [row["candidate_id"] for row in candidates]
    events = []
    contexts = {}
    plan = (
        ("truncated-a", ids[:40], False), ("truncated-b", ids[4:44], False),
        ("truncated-c", ids[8:48], False), ("blocked", [ids[7]], True),
        ("orchard", ids[10:16], True), ("harvest", ids[16:22], True),
        ("cannery", ids[22:28], True), ("bicycle", ids[28:34], True),
    )
    for name, context_ids, complete in plan:
        event = {"title": f"The {name} moment", "description": f"A synthetic {name} moment.",
                 "subject": "self", "places": [], "when_hint": None, "anchor": None, "date": None,
                 "source_grounding": None, "timeline_relation": None}
        key = te.event_key(event)
        event["event_key"] = key
        event["timeline_resolution"] = {
            "status": "incomplete" if not complete else "missing_evidence",
            "candidate_ids": sorted(ids[:40]), "reason": "An earlier synthetic reading.",
            "source_revision": _sha("source"), "event_key": key,
            "prompt_version": cc.PROMPT_VERSION, "input_fingerprint": _sha(f"old-{name}")}
        events.append(event)
        contexts[key] = {"event_key": key, "candidate_ids": sorted(context_ids),
                         "complete": complete, "reference_keys": ["home", "moved"],
                         "unmatched_reference_keys": [],
                         "remaining_candidate_count": 0 if complete else 24,
                         "input_fingerprint": _sha(f"context-{name}")}
    snapshot = {
        "schema_version": 1, "source_revision": _sha("source"),
        "context_digest": _sha("context"), "prompt_version": cc.PROMPT_VERSION,
        "extractor_version": cc.EXTRACTOR_VERSION, "context_complete": False,
        "context_truncated": True, "remaining_candidate_count": 24,
        "catalog_omitted_count": 0, "remaining_decision_count": 0,
        "candidates": candidates, "event_contexts": contexts,
        "human_identity_decisions": [],
        "prior_event_identities": [{"telling_ref": f"telling:{i}", "recorder_event_id": None,
                                    "event_refs": [ids[i]], "era_refs": [], "aliases": [],
                                    "superseded_by": None, "bound_identity_ids": []}
                                   for i in range(8)],
    }
    return snapshot, events


class Harness:
    def build(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="lifehug-v374-")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / "sources/manual").mkdir(parents=True)
        (self.root / "state/classifications").mkdir(parents=True)
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
        self.snapshot, self.events = measurement_case()
        self.source = self.write_source("alpha", STORY, self.events)
        self.stack.enter_context(mock.patch.object(
            cc, "load_context_catalog", return_value={"synthetic": True}))
        self.stack.enter_context(mock.patch.object(
            cc, "build_context_snapshot_from_catalog", side_effect=self._snapshot_for))
        self.stack.enter_context(mock.patch.object(
            cc, "build_context_snapshot", side_effect=self._snapshot_for))

    def _snapshot_for(self, _root, source, *_args, **_kwargs) -> dict:
        return {**self.snapshot, "source_revision": cc.source_revision(Path(source))}

    def write_source(self, name: str, text: str, events: list[dict]) -> Path:
        path = self.root / "sources/manual" / f"{name}.md"
        path.write_text(f"---\ntitle: {name}\n---\n{text}")
        old = {**self.snapshot, "context_digest": "sha256:" + "0" * 64,
               "source_revision": cc.source_revision(path)}
        cs.write_json(cs.classification_path(path), {
            "version": 2, "source_path": f"sources/manual/{name}.md",
            "model_used": "synthetic-old", "reviewable": True,
            "classification_snapshot": cc.snapshot_metadata(old),
            "events": copy.deepcopy(events)})
        return path

    def prompt(self, source: Path | None = None) -> str:
        source = source or self.source
        fm, story = cs.load_source_text(source)
        return cs.build_prompt(source, fm, story, context_snapshot=self._snapshot_for(None, source),
                               mode="timeline")


class PromptSizeTests(Harness, unittest.TestCase):
    def setUp(self) -> None:
        self.build()

    def test_the_prompt_is_at_least_sixty_percent_smaller_than_v373(self) -> None:
        size = len(self.prompt())
        self.assertGreater(V373_PROMPT_CHARS, 0)
        self.assertLessEqual(size, 0.4 * V373_PROMPT_CHARS, (size, V373_PROMPT_CHARS))

    def test_fixed_instructions_come_first_and_are_identical_for_every_source(self) -> None:
        other = self.write_source("bravo", STORY.replace("twelve", "eleven"), self.events)
        first, second = self.prompt(), self.prompt(other)
        block = cs.timeline_instruction_block()
        for prompt in (first, second):
            self.assertTrue(prompt.startswith(block))
            self.assertEqual(prompt.index(cs.TIMELINE_DATA_MARKER), len(block))
            self.assertNotIn("sources/manual", block)
            self.assertNotIn(self.snapshot["context_digest"], block)
        self.assertNotEqual(first[len(block):], second[len(block):])

    def test_only_judged_events_and_their_candidates_reach_the_prompt(self) -> None:
        prompt = self.prompt()
        data = prompt[len(cs.timeline_instruction_block()):]
        self.assertNotIn("grounding_identity", data)
        self.assertNotIn("canonical_roster_terms", data)
        self.assertNotIn("input_fingerprint", data)
        self.assertNotIn("\n  ", data)  # compact JSON
        context = json.loads(data.split("## Canonical Timeline Context\n", 1)[1].split("\n", 1)[0])
        judged = {event["event_key"] for event in self.events[4:]}
        self.assertEqual(set(context["event_contexts"]), judged)
        needed = {cid for key in judged for cid in self.snapshot["event_contexts"][key]["candidate_ids"]}
        self.assertEqual({row["candidate_id"] for row in context["candidates"]}, needed)
        for event in self.events[:4]:
            self.assertNotIn(event["event_key"], data)
        # The snapshot and digest inputs are untouched by the prompt's copy.
        self.assertIn("grounding_identity", self.snapshot["candidates"][0])


class NoEchoResponseTests(Harness, unittest.TestCase):
    def setUp(self) -> None:
        self.build()

    def _file(self, source: Path, deltas: list[dict], batch_id: str) -> dict:
        response = {"_classification_mode": "timeline",
                    "_classification_snapshot": cc.snapshot_metadata(self._snapshot_for(None, source)),
                    "events": deltas}
        return cs.file_batch_response({"schema_version": 1, "batch_id": batch_id,
            "skip_candidates": True, "items": [{
                "source_path": source.relative_to(self.root).as_posix(), "mode": "timeline",
                "response_text": json.dumps(response)}]})

    def _deltas(self, *, echo: bool) -> list[dict]:
        rows = []
        for event in self.events[4:]:
            resolution = {"status": "missing_evidence", "reason": "No quote places it."}
            if echo:
                resolution["candidate_ids"] = list(
                    self.snapshot["event_contexts"][event["event_key"]]["candidate_ids"])
            rows.append({"event_key": event["event_key"], "source_grounding": None,
                         "timeline_relation": None, "timeline_resolution": resolution})
        return rows

    def test_a_response_without_candidate_ids_stores_the_same_shape(self) -> None:
        other = self.write_source("bravo", STORY, self.events)
        self.assertEqual(self._file(self.source, self._deltas(echo=False), "no-echo")["counts"]["accepted"], 1)
        self.assertEqual(self._file(other, self._deltas(echo=True), "echo")["counts"]["accepted"], 1)
        quiet = json.loads(cs.classification_path(self.source).read_text())["events"]
        echoed = json.loads(cs.classification_path(other).read_text())["events"]
        def without_revision(events: list[dict]) -> list[dict]:
            # The two sources differ only in path, which the revision covers.
            rows = copy.deepcopy(events)
            for event in rows:
                (event.get("timeline_resolution") or {}).pop("source_revision", None)
            return rows

        self.assertEqual(without_revision(quiet), without_revision(echoed))
        for event in quiet[4:]:
            self.assertEqual(event["timeline_resolution"]["candidate_ids"],
                             self.snapshot["event_contexts"][event["event_key"]]["candidate_ids"])
            self.assertEqual(set(event["timeline_resolution"]),
                             {"status", "candidate_ids", "reason", "source_revision",
                              "event_key", "prompt_version", "input_fingerprint"})

    def test_quote_and_eligibility_validation_still_hold(self) -> None:
        deltas = self._deltas(echo=False)
        orchard = self.snapshot["event_contexts"][deltas[0]["event_key"]]["candidate_ids"]
        target = next(row for row in self.snapshot["candidates"] if row["candidate_id"] == orchard[0])
        deltas[0]["timeline_relation"] = {"relation": "within", "candidate_id": target["candidate_id"],
                                          "entity_refs": target["entity_refs"],
                                          "evidence": {"quote": "words that are not in the story"}}
        deltas[0]["timeline_resolution"]["status"] = "linked"
        _fm, story = cs.load_source_text(self.source)
        response = {"_classification_mode": "timeline",
                    "_classification_snapshot": cc.snapshot_metadata(self._snapshot_for(None, self.source)),
                    "events": deltas}
        with self.assertRaises(cc.ClassifierContextError) as caught:
            cs.prepare_classification(self.source, "m", copy.deepcopy(response), mode="timeline",
                                      snapshot=self._snapshot_for(None, self.source),
                                      candidate_store={"candidates": []}, salvage=False)
        self.assertEqual(caught.exception.code, cc.ContextFailureCode.QUOTE_NOT_FOUND)
        # A link to a candidate outside the event's own set is refused too.
        deltas[0]["timeline_relation"]["candidate_id"] = self.snapshot["candidates"][0]["candidate_id"]
        deltas[0]["timeline_relation"]["evidence"]["quote"] = "the orchard"
        with self.assertRaises(cc.ClassifierContextError) as caught:
            cs.prepare_classification(self.source, "m", copy.deepcopy(response | {"events": deltas}),
                                      mode="timeline", snapshot=self._snapshot_for(None, self.source),
                                      candidate_store={"candidates": []}, salvage=False)
        self.assertEqual(caught.exception.code, cc.ContextFailureCode.CANDIDATE_UNKNOWN)

    def test_versions_and_digest_inputs_are_unchanged(self) -> None:
        self.assertEqual(cc.PROMPT_VERSION, "contextual-timeline:3")
        self.assertEqual(cc.EXTRACTOR_VERSION, "story-classifier:2")
        self.assertIn("grounding_identity", cc._freshness_candidate({"grounding_identity": []}))


if __name__ == "__main__":
    unittest.main()
