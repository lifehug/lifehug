"""v394 (ADR 0044) — a Focus at 100% is a milestone, not an end.

Every fixture is SYNTHETIC: an invented person (Katie), invented gaps, a
throwaway vault per test. Nothing is copied from any real vault.
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "system"))
sys.path.insert(0, str(ROOT / "tests"))

import entity_roster  # noqa: E402
import focus_complete as fc  # noqa: E402
import lifehug_core  # noqa: E402
import question_candidates as qcands  # noqa: E402
import question_planner  # noqa: E402
import recommend_focuses  # noqa: E402
import roadmap  # noqa: E402
import serve_wiki  # noqa: E402
import timeline_candidates  # noqa: E402
from tempdirs import root_parent_tmp  # noqa: E402

PRIMARY = {"id": "my-life", "label": "My Life", "type": "life_story", "primary": True,
           "tier": "extreme", "categories": ["A"], "phase": "active"}


def katie(**extra):
    base = {"id": "katie", "label": "Katie", "type": "person", "tier": "basic",
            "objective": "x", "deliverable": "letter", "categories": ["K"],
            "target_depth": 8, "phase": "active", "person_ref": "person/katie"}
    base.update(extra)
    return base


def bank(k_answered=3, k_open=0, retired=0):
    lines = ["## A: Origins", "- [x] A1: Where were you born and what do you remember of it?",
             "## Focus Areas", "## K: Focus — Katie"]
    n = 1
    for _ in range(k_answered):
        lines.append(f"- [x] K{n}: What do you remember about Katie, part {n}?")
        n += 1
    for _ in range(k_open):
        lines.append(f"- [ ] K{n}: What did Katie and you do on the open day, part {n}?")
        n += 1
    for _ in range(retired):
        lines.append(f"- [-] K{n}: Retired question {n}? *(retired 2026-01-01: duplicate)*")
        n += 1
    return "\n".join(lines) + "\n"


VIEW = {
    "landmark_opportunities": [
        {"id": "lo:aaaaaaaaaaaaaaaaaaaaaaaa", "subject": "Katie graduation",
         "label": "Katie's graduation", "kind": "landmark_opportunity",
         "question": "What do you remember about the day Katie finished high school?",
         "leverage": 9, "resolves": [], "sensitivity": "ordinary", "domain": "schools",
         "work_item_id": ""},
        {"id": "lo:bbbbbbbbbbbbbbbbbbbbbbbb", "subject": "the Mesa house",
         "label": "the Mesa house", "kind": "landmark_opportunity",
         "question": "What do you remember about the day you left the Mesa house?",
         "leverage": 9, "resolves": [], "sensitivity": "ordinary", "domain": "residences",
         "work_item_id": ""},
        {"id": "lo:cccccccccccccccccccccccc", "subject": "Katie wedding",
         "label": "Katie's wedding", "kind": "landmark_opportunity",
         "question": "Did Katie marry?", "leverage": 9, "resolves": [],
         "sensitivity": "ordinary", "domain": "partnerships", "work_item_id": ""},
    ],
    "keystones": [],
    "work_items": [],
}


class Base(unittest.TestCase):
    def setUp(self):
        # Other suites reload these modules; patch the LIVE ones, which are the
        # ones focus_complete imports lazily.
        global qcands, timeline_candidates
        qcands = __import__("question_candidates")
        timeline_candidates = __import__("timeline_candidates")
        self.tmp = root_parent_tmp(self, ROOT)
        self.bank_file = self.tmp / "question-bank.md"
        self.rm_file = self.tmp / "roadmap.json"
        self.cand_file = self.tmp / "question_candidates.json"
        self._patches = [
            mock.patch.object(lifehug_core, "QUESTIONS_FILE", self.bank_file),
            mock.patch.object(roadmap, "QUESTIONS_FILE", self.bank_file),
            mock.patch.object(timeline_candidates, "QUESTIONS_FILE", self.bank_file),
            mock.patch.object(timeline_candidates, "DISMISSALS_FILE", self.tmp / "tc.json"),
            mock.patch.object(roadmap, "ROADMAP_FILE", self.rm_file),
            mock.patch.object(qcands, "QUESTION_CANDIDATES_FILE", self.cand_file),
            mock.patch.object(entity_roster, "ENTITY_DIR", self.tmp / "no-rosters"),
        ]
        for p in self._patches:
            p.start()
        self.addCleanup(lambda: [p.stop() for p in reversed(self._patches)])

    def put(self, bank_text, focuses):
        self.bank_file.write_text(bank_text)
        self.rm_file.write_text(json.dumps({"version": 1, "focuses": focuses}))

    def focus(self, fid="katie"):
        return roadmap.find_focus(roadmap.load_roadmap(), fid)

    def store(self):
        return qcands.load_store(self.cand_file)

    def sweep(self, **kw):
        kw.setdefault("view", VIEW)
        kw.setdefault("now", "2026-10-04T12:00:00Z")
        return fc.sweep(**kw)


class CompletionRule(Base):
    def test_fires_at_100_percent_and_not_before(self):
        self.put(bank(3, 1), [PRIMARY, katie()])
        self.assertEqual(self.sweep()["completed"], [])
        self.assertEqual(self.focus()["phase"], "active")
        self.put(bank(3, 0), [PRIMARY, katie()])
        out = self.sweep()
        self.assertEqual([c["focus"] for c in out["completed"]], ["katie"])
        done = self.focus()
        self.assertEqual(done["phase"], "complete")
        self.assertEqual(done["completion"]["answered"], 3)
        self.assertEqual(done["completion"]["total"], 3)
        self.assertEqual(done["completion"]["completed_at"], "2026-10-04T12:00:00Z")

    def test_a_retired_row_does_not_hold_a_focus_open(self):
        self.put(bank(3, 0, retired=2), [PRIMARY, katie()])
        self.assertEqual(len(self.sweep()["completed"]), 1)

    def test_nothing_answered_is_not_complete_and_primary_never_is(self):
        self.put("## A: Origins\n- [ ] A1: Where?\n## K: Focus — Katie\n", [PRIMARY, katie()])
        self.assertEqual(self.sweep()["completed"], [])
        self.put("## A: Origins\n- [x] A1: Where were you born?\n", [PRIMARY])
        self.assertEqual(self.sweep()["completed"], [])

    def test_tier_does_not_change_what_complete_means(self):
        # D3: a basic Focus (target 8) with 3 of 3 answered is complete exactly
        # as an extreme one (target 50) with 3 of 3 answered is.
        self.put(bank(3, 0), [PRIMARY, katie(tier="basic", target_depth=8),
                               katie(id="mike", label="Mike", tier="extreme",
                                     target_depth=50, categories=["K"], person_ref=None)])
        out = self.sweep()
        self.assertEqual({c["focus"] for c in out["completed"]}, {"katie", "mike"})

    def test_dry_run_writes_nothing(self):
        self.put(bank(3, 0), [PRIMARY, katie()])
        before = self.rm_file.read_text()
        out = self.sweep(dry_run=True)
        self.assertEqual(len(out["completed"]), 1)
        self.assertEqual(self.rm_file.read_text(), before)
        self.assertFalse(self.cand_file.exists())

    def test_focus_finish_is_unchanged(self):
        self.put(bank(3, 0), [PRIMARY, katie()])
        self.assertEqual(roadmap.cli(["finish", "katie"]), 0)
        self.assertEqual(self.focus()["phase"], "finishing")
        self.assertNotIn("completion", self.focus())


class RestAndReopen(Base):
    def test_planner_excludes_a_complete_focus(self):
        self.put(bank(3, 0), [PRIMARY, katie()])
        self.sweep()
        qs = lifehug_core.parse_questions(bank(3, 0))
        index = question_planner.build_focus_index(roadmap.load_roadmap()["focuses"], qs)
        self.assertEqual(index["info"]["katie"]["weight"], 0.0)

    def test_planner_weights_a_reopened_focus_again(self):
        self.put(bank(3, 0), [PRIMARY, katie()])
        self.sweep()
        qs = lifehug_core.parse_questions(bank(3, 1))
        index = question_planner.build_focus_index(roadmap.load_roadmap()["focuses"], qs)
        self.assertGreater(index["info"]["katie"]["weight"], 0.0)

    def test_autopilot_count_excludes_complete_and_counts_a_reopened_one(self):
        self.put(bank(3, 0), [PRIMARY, katie(target_depth=100)])
        # Unswept, 3 of 100 answered: developing.
        qs = lifehug_core.parse_questions(bank(3, 0))
        self.assertEqual(len(recommend_focuses._developing_focuses(roadmap.load_roadmap(), qs)), 1)
        self.sweep()
        self.assertEqual(recommend_focuses._developing_focuses(roadmap.load_roadmap(), qs), [])
        # A new question is approved: developing again, before any persist.
        qs = lifehug_core.parse_questions(bank(3, 1))
        self.assertEqual(len(recommend_focuses._developing_focuses(roadmap.load_roadmap(), qs)), 1)

    def test_a_complete_focus_does_not_hold_the_completion_gate_shut(self):
        self.put(bank(3, 0), [PRIMARY, katie(target_depth=100)])
        self.sweep()
        self.assertTrue(recommend_focuses.focus_start_gate()["open"])

    def test_reopens_when_a_new_question_is_approved(self):
        self.put(bank(3, 0), [PRIMARY, katie()])
        self.sweep()
        self.bank_file.write_text(bank(3, 1))
        rebuilt = roadmap.rebuild_roadmap(write=True)
        reopened = roadmap.find_focus(rebuilt, "katie")
        self.assertEqual(reopened["phase"], "active")
        self.assertIn("reopened_at", reopened["completion"])
        # ...and the sweep itself persists it too.
        self.put(bank(3, 0), [PRIMARY, katie()])
        self.sweep()
        self.bank_file.write_text(bank(3, 1))
        out = self.sweep()
        self.assertEqual(out["reopened"], ["katie"])
        self.assertEqual(self.focus()["phase"], "active")

    def test_a_complete_focus_keeps_its_person_from_being_recommended(self):
        self.put(bank(3, 0), [PRIMARY, katie()])
        self.sweep()
        names = recommend_focuses._existing_focus_names(self.bank_file.read_text())
        self.assertIn("katie", names)

    def test_foundation_shows_a_quiet_complete_mark(self):
        self.put(bank(3, 0), [PRIMARY, katie()])
        self.sweep()
        with mock.patch.object(serve_wiki, "QUESTIONS_FILE", self.bank_file):
            html = serve_wiki.view_foundation()[1]
        self.assertIn("complete", html)
        self.assertIn("fnd-complete", html)
        self.put(bank(3, 1), [PRIMARY, katie(phase="complete",
                                              completion={"completed_at": "x", "row": "open"})])
        with mock.patch.object(serve_wiki, "QUESTIONS_FILE", self.bank_file):
            html = serve_wiki.view_foundation()[1]
        self.assertNotIn("fnd-complete", html)


class SecondPass(Base):
    def test_candidates_go_through_the_craft_door_and_never_the_bank(self):
        self.put(bank(3, 0), [PRIMARY, katie()])
        before = self.bank_file.read_bytes()
        out = self.sweep()
        self.assertEqual(self.bank_file.read_bytes(), before)
        cands = self.store()["candidates"]
        texts = {c["text"] for c in cands}
        # Katie's passing gap is filed; the Mesa house is not about her; the
        # bare yes/no fails the craft door and is dropped.
        self.assertEqual(texts, {"What do you remember about the day Katie finished high school?"})
        cand = cands[0]
        self.assertEqual(cand["source"], "focus_complete:katie")
        self.assertEqual(cand["status"], "needs_review")
        self.assertEqual(cand["target_category"], "K")
        self.assertEqual(out["completed"][0]["second_pass"], 1)
        self.assertEqual(self.focus()["completion"]["second_pass"], [cand["id"]])

    def test_the_auto_promoter_can_never_carry_one_into_the_bank(self):
        self.put(bank(3, 0), [PRIMARY, katie()])
        self.sweep()
        cand = self.store()["candidates"][0]
        self.assertNotIn(cand["status"], qcands.PROMOTABLE_STATUSES)
        self.assertFalse(qcands._is_resurfaceable(cand))

    def test_a_rerun_files_nothing_twice(self):
        self.put(bank(3, 0), [PRIMARY, katie()])
        self.sweep()
        filed = fc.second_pass(self.focus(), VIEW)
        self.assertEqual(filed, [])
        self.assertEqual(len(self.store()["candidates"]), 1)

    def test_a_focus_with_no_person_has_no_second_pass(self):
        self.put(bank(3, 0), [PRIMARY, katie(label="The Cabin Years", id="cabin",
                                              person_ref=None, type="theme")])
        self.sweep()
        self.assertEqual(self.store()["candidates"], [])

    def test_open_date_gaps_about_the_person_are_proposed_and_capped(self):
        items = [{"work_item_id": f"wi{i}", "kind": "precision_gap", "state": "open",
                  "subject_ref": "person/katie",
                  "prompt_intent": f"What do you remember about the year Katie started school, version {i}?"}
                 for i in range(6)]
        view = {**VIEW, "work_items": items}
        self.put(bank(3, 0), [PRIMARY, katie()])
        self.sweep(view=view)
        cands = self.store()["candidates"]
        self.assertLessEqual(len(cands), fc.SECOND_PASS_CAP)
        self.assertTrue(cands)


class TheOneRow(Base):
    def test_the_row_is_minted_once_per_completion(self):
        self.put(bank(3, 0), [PRIMARY, katie()])
        self.sweep()
        first = fc.rows()
        self.assertEqual(len(first), 1)
        row = first[0]
        self.assertEqual(row["kind"], "focus_complete")
        self.assertEqual(row["headline"], "Katie is complete — 3 of 3 answered")
        self.assertEqual(row["work_item_id"], "fc:katie:2026-10-04T12:00:00Z")
        self.assertEqual(row["plays"], ["keep_going", "rest", "make"])
        # Sweeping again, later, while still complete: same single row, same id.
        self.sweep(now="2026-10-11T12:00:00Z")
        again = fc.rows()
        self.assertEqual([r["work_item_id"] for r in again], [row["work_item_id"]])

    def test_a_played_row_is_never_re_minted_while_complete(self):
        self.put(bank(3, 0), [PRIMARY, katie()])
        self.sweep()
        fc.play("katie", "rest", now="2026-10-05T00:00:00Z")
        self.sweep(now="2026-10-11T12:00:00Z")
        self.assertEqual(fc.rows(), [])
        self.assertEqual(len(fc.rows(include_resolved=True)), 1)

    def test_a_focus_that_finishes_again_is_a_new_milestone(self):
        self.put(bank(3, 0), [PRIMARY, katie()])
        self.sweep()
        fc.play("katie", "rest")
        self.bank_file.write_text(bank(3, 1))
        self.sweep(now="2026-10-11T12:00:00Z")
        self.bank_file.write_text(bank(4, 0))
        self.sweep(now="2026-10-18T12:00:00Z")
        rows = fc.rows()
        self.assertEqual([r["work_item_id"] for r in rows], ["fc:katie:2026-10-18T12:00:00Z"])
        self.assertIn("4 of 4", rows[0]["headline"])


class ThePlays(Base):
    def setUp(self):
        super().setUp()
        self.put(bank(3, 0), [PRIMARY, katie()])
        self.sweep()

    def test_keep_going_gives_the_candidates_review_attention(self):
        out = fc.play("katie", "keep_going", now="2026-10-05T00:00:00Z")
        cand = self.store()["candidates"][0]
        self.assertEqual(out["review_attention"], [cand["id"]])
        self.assertTrue(cand["review_attention"])
        self.assertEqual(cand["status"], "needs_review")   # the owner still decides
        self.assertEqual(self.focus()["completion"]["row"], "kept_going")

    def test_rest_closes_the_row_and_does_nothing_else(self):
        cands_before = self.cand_file.read_text()
        bank_before = self.bank_file.read_bytes()
        fc.play("katie", "rest")
        self.assertEqual(self.cand_file.read_text(), cands_before)
        self.assertEqual(self.bank_file.read_bytes(), bank_before)
        self.assertEqual(self.focus()["phase"], "complete")
        self.assertEqual(self.focus()["completion"]["row"], "rested")

    def test_make_records_a_studio_card_hint(self):
        out = fc.play("katie", "make")
        card = out["studio_card"]
        self.assertEqual(card["kind"], "focus_story")
        self.assertEqual(card["title"], "The story of Katie so far")
        self.assertEqual(self.focus()["completion"]["studio_card"], card)

    def test_a_row_is_played_once_and_only_while_complete(self):
        fc.play("katie", "rest")
        with self.assertRaises(ValueError):
            fc.play("katie", "keep_going")
        with self.assertRaises(ValueError):
            fc.play("my-life", "rest")
        with self.assertRaises(ValueError):
            fc.play("katie", "dance")


if __name__ == "__main__":
    unittest.main()
