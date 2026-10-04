"""A question never comes from a bare name (roster-identity §4.4, P5).

The founder's 2026-10-03 question narrated the vault's own records back to him
because a one-line promoted landmark entry (`{"domain":"partnerships",...}`)
was classified like a story and minted a candidate. A `landmark_entry` still
classifies (claims, people) but mints no candidates.
"""

from __future__ import annotations

import io
import json
import sys
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "system"))
sys.path.insert(0, str(ROOT / "tests"))

import classifier_context as cc  # noqa: E402
import classify_story  # noqa: E402
from test_classifier_context import ContextCase  # noqa: E402

LANDMARK = (
    '---\ntype: "landmark_entry"\n---\n'
    '{"domain":"partnerships","label":"Katie Ann Merrill","who":"Katie Ann Merrill"}\n'
)
STORY = '---\ntype: "story"\n---\nI met Katie Ann Merrill at a diner in 2005.\n'


class LandmarkEntryCandidates(ContextCase):
    def _classify(self, name: str, text: str, *, with_question: bool):
        source = self.root / "sources" / "landmarks" / name
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_text(text, encoding="utf-8")
        snapshot = cc.build_context_snapshot(self.root, source)
        response = {
            "_classification_snapshot": cc.snapshot_metadata(snapshot),
            "people": [{"name": "Katie Ann Merrill"}],
            "places": [],
            "events": [],
        }
        if with_question:
            response["candidate_questions"] = [{
                "text": "What do you remember about the day you first met Katie Ann Merrill?",
                "priority": 0.9,
                "reason": "a partner with one mention",
            }]
        candidates = self.root / "state" / "question_candidates.json"
        with mock.patch.object(classify_story, "REPO_DIR", self.root), \
                mock.patch.object(classify_story, "CLASSIFICATIONS_DIR",
                                  self.root / "state" / "classifications"), \
                mock.patch.object(classify_story, "QUESTION_CANDIDATES_FILE", candidates), \
                mock.patch.object(classify_story, "classify_with_ai") as model, \
                redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()) as err:
            rc = classify_story.classify_file(
                source, "synthetic-recorded", precomputed_result=response)
            path = classify_story.classification_path(source)
            saved = json.loads(path.read_text()) if path.exists() else None
        model.assert_not_called()
        return rc, saved, err.getvalue(), candidates

    def test_landmark_entry_mints_no_candidates(self):
        rc, saved, err, candidates = self._classify(
            "entry-x.md", LANDMARK, with_question=False)
        self.assertEqual(rc, 0, err)
        self.assertEqual(saved["candidate_question_ids"], [])
        self.assertIs(saved[classify_story.CLASSIFICATION_SKIP_CANDIDATES_FIELD], True)
        self.assertEqual([p["name"] for p in saved["people"]], ["Katie Ann Merrill"])
        if candidates.exists():
            self.assertEqual(json.loads(candidates.read_text()).get("candidates", []), [])

    def test_landmark_entry_prompt_asks_for_no_candidates(self):
        source = self.root / "sources" / "landmarks" / "entry-y.md"
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_text(LANDMARK, encoding="utf-8")
        with mock.patch.object(classify_story, "REPO_DIR", self.root):
            self.assertTrue(classify_story.source_mints_no_candidates(source))
        story = self.root / "sources" / "landmarks" / "story.md"
        story.write_text(STORY, encoding="utf-8")
        self.assertFalse(classify_story.source_mints_no_candidates(story))

    def test_batch_plan_never_reselects_landmark_for_candidate_pass(self):
        rc, _saved, err, _c = self._classify("entry-z.md", LANDMARK, with_question=False)
        self.assertEqual(rc, 0, err)
        source = self.root / "sources" / "landmarks" / "entry-z.md"
        with mock.patch.object(classify_story, "REPO_DIR", self.root), \
                mock.patch.object(classify_story, "CLASSIFICATIONS_DIR",
                                  self.root / "state" / "classifications"):
            plan = classify_story.build_batch_plan(
                sources=[source], require_candidates=True)
        self.assertEqual(plan["selected_count"], 0, plan)
