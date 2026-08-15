"""PR decisions-feed-the-loop — the review surface's decisions become real
training signal instead of being archived unread.

Covers: the field-overwrite fix (decision_reason vs. the generator's own
provenance reason), question_judgment.build_decision_context() assembly
and its injection into both generation prompts, and the weekly RUBRIC-EDIT
runtime (question_judgment.run_weekly_edit()) — cursor advance, the no-op
verdict, per-entry/file-cap enforcement, dry-run, the keyless
emit-task/--from-response convention, and --recalibrate.

Synthetic data only; NEVER references ~/Workspace/dave.
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SYSTEM = ROOT / "system"
sys.path.insert(0, str(SYSTEM))
sys.path.insert(0, str(ROOT / "tests"))

from tempdirs import root_parent_tmp  # noqa: E402

import classify_story  # noqa: E402
import question_candidates as qc  # noqa: E402
import question_judgment as qj  # noqa: E402
import research_expand as re_mod  # noqa: E402
from lifehug_core import _parse_simple_yaml  # noqa: E402

GOLDENS_DIR = ROOT / "interactions" / "question_judgment" / "evals" / "goldens"


def _store(candidates: list[dict]) -> dict:
    return {"version": 1, "candidates": candidates}


def _write_store(path: Path, candidates: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(_store(candidates), indent=2), encoding="utf-8")


class OverwriteFixTests(unittest.TestCase):
    """Scope 1: update_candidate() writes owner text to decision_reason;
    the generator's own reason is never touched again."""

    def _candidate(self, **overrides) -> dict:
        base = {
            "id": "cand-1",
            "status": "candidate",
            "text": "Did you go to the store?",
            "reason": "classifier inferred this from a receipt mentioned in the source",
        }
        base.update(overrides)
        return base

    def test_dismiss_with_reason_leaves_generator_provenance_untouched(self):
        data = _store([self._candidate()])
        candidate = qc.update_candidate(
            data, "cand-1", status="rejected", decision_reason="already covered by B7 last month",
        )
        self.assertEqual(candidate["reason"], "classifier inferred this from a receipt mentioned in the source")
        self.assertEqual(candidate["decision_reason"], "already covered by B7 last month")

    def test_decision_reason_lands_on_the_record(self):
        data = _store([self._candidate()])
        qc.update_candidate(data, "cand-1", status="deferred", decision_reason="not now, revisit after the move Focus")
        self.assertEqual(data["candidates"][0]["decision_reason"], "not now, revisit after the move Focus")

    def test_no_reason_given_leaves_decision_reason_absent(self):
        data = _store([self._candidate()])
        candidate = qc.update_candidate(data, "cand-1", status="rejected")
        self.assertNotIn("decision_reason", candidate)
        self.assertEqual(candidate["reason"], "classifier inferred this from a receipt mentioned in the source")

    def test_cmd_update_cli_flag_still_named_reason_but_writes_decision_reason(self):
        """candidates-update --reason maps to decision_reason (contract Scope 1) —
        the CLI surface is unchanged, only the field it writes changed."""
        import argparse
        data = _store([self._candidate()])

        class Args(argparse.Namespace):
            candidate_id = "cand-1"
            status = "rejected"
            target_page = None
            target_category = None
            priority = None
            reason = "dismissed from viewer"

        with tempfile.TemporaryDirectory() as tmp:
            store_path = Path(tmp) / "candidates.json"
            store_path.write_text(json.dumps(data), encoding="utf-8")
            orig_load, orig_save = qc.load_store, qc.save_store
            qc.load_store = lambda path=store_path: json.loads(store_path.read_text())
            qc.save_store = lambda d, path=store_path: store_path.write_text(json.dumps(d))
            try:
                qc.cmd_update(Args())
            finally:
                qc.load_store, qc.save_store = orig_load, orig_save
            saved = json.loads(store_path.read_text())
        self.assertEqual(saved["candidates"][0]["decision_reason"], "dismissed from viewer")
        self.assertEqual(saved["candidates"][0]["reason"], "classifier inferred this from a receipt mentioned in the source")

    def test_print_candidate_shows_both_fields(self):
        import io
        from contextlib import redirect_stdout
        candidate = self._candidate(decision_reason="already covered by B7 last month")
        out = io.StringIO()
        with redirect_stdout(out):
            qc.print_candidate(candidate, detail=True)
        text = out.getvalue()
        self.assertIn("reason: classifier inferred this from a receipt", text)
        self.assertIn("decision_reason: already covered by B7 last month", text)

    def test_viewer_history_lane_shows_both_reasons_distinctly(self):
        import serve_wiki
        candidate = self._candidate(status="rejected", decision_reason="already covered by B7 last month")
        cell = serve_wiki._history_reason_cell(candidate)
        self.assertIn("proposed: classifier inferred this from a receipt", cell)
        self.assertIn("owner: already covered by B7 last month", cell)
        self.assertIn("q-provenance-reason", cell)
        self.assertIn("q-decision-reason", cell)

    def test_viewer_history_lane_falls_back_to_dash_when_both_absent(self):
        import serve_wiki
        candidate = {"id": "cand-2", "status": "rejected", "text": "x"}
        self.assertEqual(serve_wiki._history_reason_cell(candidate), '<span class="muted">—</span>')


class DecisionContextAssemblyTests(unittest.TestCase):
    """Scope 2: build_decision_context() — ordering, human-only filter,
    truncation, empty history omitted."""

    def _write(self, path: Path, candidates: list[dict]) -> None:
        _write_store(path, candidates)

    def test_ordering_newest_first(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "candidates.json"
            self._write(path, [
                {"id": "c1", "status": "rejected", "text": "older", "updated_at": "2026-08-01T00:00:00Z"},
                {"id": "c2", "status": "deferred", "text": "newer", "updated_at": "2026-08-10T00:00:00Z"},
            ])
            context = qj.build_decision_context(path=path)
        lines = context.splitlines()
        self.assertTrue(lines[0].startswith('DEFERRED "newer"'))
        self.assertTrue(lines[1].startswith('DISMISSED "older"'))

    def test_human_only_auto_promoted_excluded(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "candidates.json"
            self._write(path, [
                {"id": "c1", "status": "auto_promoted", "text": "should not appear", "updated_at": "2026-08-10T00:00:00Z", "promoted_by": "auto"},
                {"id": "c2", "status": "rejected", "text": "should appear", "updated_at": "2026-08-09T00:00:00Z"},
                {"id": "c3", "status": "candidate", "text": "not a decision", "updated_at": "2026-08-08T00:00:00Z"},
                {"id": "c4", "status": "needs_review", "text": "parked, not decided", "updated_at": "2026-08-07T00:00:00Z"},
            ])
            context = qj.build_decision_context(path=path)
        self.assertIn("should appear", context)
        self.assertNotIn("should not appear", context)
        self.assertNotIn("not a decision", context)
        self.assertNotIn("parked, not decided", context)

    def test_truncates_text_over_120_chars(self):
        long_text = "x" * 200
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "candidates.json"
            self._write(path, [{"id": "c1", "status": "rejected", "text": long_text, "updated_at": "2026-08-10T00:00:00Z"}])
            context = qj.build_decision_context(path=path)
        quoted = context.split('"')[1]
        self.assertLessEqual(len(quoted), 120)
        self.assertTrue(quoted.endswith("..."))

    def test_empty_history_yields_empty_string(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "candidates.json"
            self._write(path, [])
            self.assertEqual(qj.build_decision_context(path=path), "")

    def test_limit_caps_result_count(self):
        rows = [
            {"id": f"c{i}", "status": "rejected", "text": f"q{i}", "updated_at": f"2026-08-{i:02d}T00:00:00Z"}
            for i in range(1, 21)
        ]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "candidates.json"
            self._write(path, rows)
            context = qj.build_decision_context(limit=15, path=path)
        self.assertEqual(len(context.splitlines()), 15)

    def test_decision_reason_preferred_over_promoted_by_fallback(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "candidates.json"
            self._write(path, [{
                "id": "c1", "status": "rejected", "text": "q", "updated_at": "2026-08-10T00:00:00Z",
                "decision_reason": "the owner's real reason",
            }])
            context = qj.build_decision_context(path=path)
        self.assertIn("the owner's real reason", context)

    def test_owner_judgment_signals_block_empty_when_no_context(self):
        self.assertEqual(qj.owner_judgment_signals_block(""), "")

    def test_owner_judgment_signals_block_has_instruction_line(self):
        block = qj.owner_judgment_signals_block('DISMISSED "x" — no reason given')
        self.assertIn("## Owner Judgment Signals", block)
        self.assertIn("must not be re-proposed", block)


class GenerationPromptInjectionTests(unittest.TestCase):
    """Scope 2: both generation prompts carry the Owner Judgment Signals
    block when history exists, and omit it entirely when it doesn't."""

    def _build_prompt_with_decision_context(self, decision_context: str) -> str:
        """classify_story.build_prompt calls build_decision_context(limit=15)
        with no path override (production always reads the real vault) — so
        the seam a test overrides is the name classify_story imported, not
        question_candidates.QUESTION_CANDIDATES_FILE's unrebindable default
        arg (evaluated once at def time, not per-call)."""
        with tempfile.TemporaryDirectory() as tmp:
            orig = classify_story.build_decision_context
            classify_story.build_decision_context = lambda limit=15: decision_context
            try:
                src = Path(tmp) / "story.md"
                src.write_text("body", encoding="utf-8")
                return classify_story.build_prompt(src, {"title": "t", "type": "unprompted_story"}, "Story text.")
            finally:
                classify_story.build_decision_context = orig

    def test_classify_story_prompt_contains_block_when_history_exists(self):
        prompt = self._build_prompt_with_decision_context('DISMISSED "yes/no question" — too formal')
        self.assertIn("## Owner Judgment Signals", prompt)
        self.assertIn("too formal", prompt)

    def test_classify_story_prompt_omits_block_when_no_history(self):
        prompt = self._build_prompt_with_decision_context("")
        self.assertNotIn("## Owner Judgment Signals", prompt)

    def test_research_expand_prompt_contains_block_when_history_exists(self):
        prompt = re_mod.build_expansion_prompt(
            topic="Ohio years", topic_type="time_period", target_output="chapter",
            mission="", source_content="", relevant_answers=[],
            question_bank_categories="",
            decision_context='DISMISSED "Did you go?" — yes/no wording',
        )
        self.assertIn("## OWNER JUDGMENT SIGNALS", prompt)
        self.assertIn("yes/no wording", prompt)

    def test_research_expand_prompt_omits_block_when_no_history(self):
        prompt = re_mod.build_expansion_prompt(
            topic="Ohio years", topic_type="time_period", target_output="chapter",
            mission="", source_content="", relevant_answers=[],
            question_bank_categories="",
        )
        self.assertNotIn("## OWNER JUDGMENT SIGNALS", prompt)


class WeeklyRubricEditTests(unittest.TestCase):
    """Scope 3: run_weekly_edit() — cursor advance, no-op, per-entry cap,
    file-cap compaction, dry-run, emit-task/--from-response, recalibrate."""

    def setUp(self):
        self.tmp = Path(root_parent_tmp(self, ROOT, prefix="lifehug-djl-"))
        self.cand_path = self.tmp / "candidates.json"
        self.cursor_path = self.tmp / "cursor.json"
        self.learned_path = self.tmp / "learned.md"
        _write_store(self.cand_path, [])

    def _seed_decisions(self) -> None:
        _write_store(self.cand_path, [
            {"id": "c1", "status": "rejected", "text": "Did you go to the store?",
             "decision_reason": "yes/no wording", "updated_at": "2026-08-14T10:00:00Z"},
            {"id": "c2", "status": "deferred", "text": "What was the hardest part of that year?",
             "updated_at": "2026-08-14T11:00:00Z"},
            {"id": "c3", "status": "promoted", "text": "Walk me through the morning of the move.",
             "updated_at": "2026-08-14T12:00:00Z"},
        ])

    def _write_response(self, **fields) -> Path:
        path = self.tmp / f"response-{len(list(self.tmp.glob('response-*.json')))}.json"
        path.write_text(json.dumps(fields), encoding="utf-8")
        return path

    def _run(self, **kwargs):
        kwargs.setdefault("candidates_path", self.cand_path)
        kwargs.setdefault("cursor_path", self.cursor_path)
        kwargs.setdefault("learned_path", self.learned_path)
        return qj.run_weekly_edit(**kwargs)

    def test_dry_run_writes_nothing(self):
        self._seed_decisions()
        result = self._run(dry_run=True)
        self.assertEqual(result["status"], "dry_run")
        self.assertIn("Decisions since last edit (3)", result["delta"])
        self.assertFalse(self.learned_path.exists())
        self.assertFalse(self.cursor_path.exists())

    def test_empty_delta_is_a_no_op_but_advances_cursor(self):
        result = self._run()
        self.assertEqual(result["status"], "no_change")
        self.assertFalse(self.learned_path.exists())
        cursor = json.loads(self.cursor_path.read_text())
        self.assertEqual(cursor["counts"]["runs"], 1)
        self.assertIsNone(cursor["last_edit_at"])

    def test_same_week_rerun_is_idempotent(self):
        self._seed_decisions()
        response = self._write_response(amendment=None, reason="nothing worth codifying yet")
        first = self._run(from_response=str(response))
        self.assertEqual(first["status"], "no_change")
        second = self._run()  # no new decisions since last_seen_at
        self.assertEqual(second["status"], "no_change")
        self.assertEqual(second["decisions_count"], 0)

    def test_model_no_op_verdict_writes_nothing_but_advances_cursor(self):
        self._seed_decisions()
        response = self._write_response(amendment=None, reason="no defensible pattern yet")
        result = self._run(from_response=str(response))
        self.assertEqual(result["status"], "no_change")
        self.assertEqual(result.get("amended"), False)
        self.assertFalse(self.learned_path.exists())
        cursor = json.loads(self.cursor_path.read_text())
        self.assertEqual(cursor["counts"]["decisions_seen"], 3)
        self.assertNotIn("amendments", cursor["counts"])

    def test_amendment_applied_respects_per_entry_cap(self):
        self._seed_decisions()
        response = self._write_response(
            amendment="x" * 601, evidence="some evidence", char_count=601,
        )
        result = self._run(from_response=str(response), max_edit_chars=600)
        self.assertEqual(result["status"], "invalid_response")
        self.assertFalse(self.learned_path.exists())

    def test_amendment_at_exactly_the_cap_is_accepted(self):
        self._seed_decisions()
        response = self._write_response(amendment="x" * 600, evidence="e")
        result = self._run(from_response=str(response), max_edit_chars=600)
        self.assertEqual(result["status"], "amended")

    def test_amendment_without_evidence_is_rejected(self):
        self._seed_decisions()
        response = self._write_response(amendment="a real amendment", evidence="")
        result = self._run(from_response=str(response))
        self.assertEqual(result["status"], "invalid_response")
        self.assertFalse(self.learned_path.exists())

    def test_amendment_appends_dated_entry_with_evidence_line(self):
        self._seed_decisions()
        response = self._write_response(
            amendment="Era-anchor candidates are exempt from the broad-generality reading.",
            evidence="c1, c2, c3 all show the pattern.",
        )
        result = self._run(from_response=str(response))
        self.assertEqual(result["status"], "amended")
        text = self.learned_path.read_text()
        self.assertRegex(text, r"(?m)^## \d{4}-\d{2}-\d{2}$")
        self.assertIn("Era-anchor candidates are exempt", text)
        self.assertIn("Evidence: c1, c2, c3 all show the pattern.", text)
        cursor = json.loads(self.cursor_path.read_text())
        self.assertIsNotNone(cursor["last_edit_at"])
        self.assertEqual(cursor["counts"]["amendments"], 1)

    def test_file_cap_compaction_folds_oldest_entries(self):
        self.learned_path.write_text("")
        for i in range(5):
            self._write_store(i)
            self.cursor_path.write_text(json.dumps({
                "version": 1, "last_edit_at": None, "last_run_at": None,
                "last_seen_at": None, "counts": {}, "quality_profile_snapshot": {},
            }))
            response = self._write_response(
                amendment=f"Amendment number {i} about something specific worth keeping a while.",
                evidence=f"evidence for entry {i}",
            )
            self._run(from_response=str(response), max_file_chars=300)
        text = self.learned_path.read_text()
        self.assertLessEqual(len(text), 400)  # cap + reserve headroom
        self.assertIn("compacted", text)
        self.assertIn("folded", text)
        self.assertIn("Amendment number 4", text)  # newest entry survives
        self.assertNotIn("Amendment number 0", text)  # oldest entry dropped

    def _write_store(self, i: int) -> None:
        _write_store(self.cand_path, [
            {"id": f"c{i}", "status": "rejected", "text": f"q{i}", "updated_at": f"2026-08-1{i}T10:00:00Z"},
        ])

    def test_emit_task_writes_a_well_formed_task_file(self):
        self._seed_decisions()
        task_path = self.tmp / "task.json"
        result = self._run(emit_task=str(task_path))
        self.assertEqual(result["status"], "emitted_task")
        task = json.loads(task_path.read_text())
        self.assertEqual(task["type"], "question_judgment_rubric_edit")
        self.assertEqual(task["mode"], "weekly")
        for key in ("prompt", "week_delta_summary", "distilled_prior_amendments", "current_learned_file", "response_format"):
            self.assertIn(key, task)
        self.assertIn("## Mode: RUBRIC-EDIT", task["prompt"])
        self.assertFalse(self.learned_path.exists())
        self.assertFalse(self.cursor_path.exists())  # emit-task never advances the cursor

    def test_from_response_applies_a_completed_task(self):
        self._seed_decisions()
        task_path = self.tmp / "task.json"
        self._run(emit_task=str(task_path))
        response = self._write_response(
            amendment="Owner-dismissed yes/no questions should be scored lower going forward.",
            evidence="c1 dismissed for yes_no_wording.",
        )
        result = self._run(from_response=str(response))
        self.assertEqual(result["status"], "amended")
        self.assertIn("Owner-dismissed yes/no", self.learned_path.read_text())

    def test_recalibrate_uses_full_ledger_not_the_delta(self):
        _write_store(self.cand_path, [
            {"id": f"c{i}", "status": "rejected", "text": f"q{i}", "updated_at": f"2026-01-{i:02d}T10:00:00Z"}
            for i in range(1, 11)
        ])
        # Mark the cursor as having already seen everything through mid-year —
        # a plain weekly run would see an empty delta, --recalibrate must not.
        self.cursor_path.write_text(json.dumps({
            "version": 1, "last_edit_at": None, "last_run_at": None,
            "last_seen_at": "2026-06-01T00:00:00Z", "counts": {}, "quality_profile_snapshot": {},
        }))
        weekly = self._run(dry_run=True)
        self.assertIn("Decisions since last edit: none.", weekly["delta"])
        recal = self._run(dry_run=True, recalibrate=True)
        self.assertIn("Full decision ledger (10 decisions)", recal["delta"])
        self.assertEqual(recal["mode"], "recalibrate")

    def test_recalibrate_from_response_still_writes_one_bounded_entry(self):
        _write_store(self.cand_path, [
            {"id": f"c{i}", "status": "rejected", "text": f"q{i}", "updated_at": f"2026-01-{i:02d}T10:00:00Z"}
            for i in range(1, 11)
        ])
        response = self._write_response(amendment="Quarterly recalibration note.", evidence="10 decisions reviewed.")
        result = self._run(from_response=str(response), recalibrate=True)
        self.assertEqual(result["status"], "amended")
        self.assertEqual(result["mode"], "recalibrate")


class GoldenFixtureTests(unittest.TestCase):
    """Scope 5: the two committed goldens — structural shape (JUDGE) and an
    end-to-end exercise through the real runtime (RUBRIC-EDIT)."""

    def _load(self, name: str) -> dict:
        return json.loads((GOLDENS_DIR / name).read_text(encoding="utf-8"))

    def test_judge_golden_matches_documented_shape(self):
        golden = self._load("judge-scene-slot-accept-01.json")
        self.assertIn("golden_id", golden)
        self.assertIn("candidate", golden)
        verdict = golden["expected_verdict"]
        self.assertIn(verdict["verdict"], ("accept", "reject"))
        lints = _parse_simple_yaml(GOLDENS_DIR.parent / "lints.yaml")
        floor, ceiling = float(lints["band.floor"]), float(lints["band.ceiling"])
        if verdict["verdict"] == "accept":
            self.assertIsNotNone(verdict["priority"])
            self.assertGreaterEqual(verdict["priority"], floor)
            self.assertLessEqual(verdict["priority"], ceiling)
            self.assertTrue(verdict["evidence"])
        else:
            self.assertIsNone(verdict["priority"])

    def test_rubric_edit_golden_matches_documented_shape(self):
        golden = self._load("rubric-edit-era-anchor-carveout-01.json")
        for key in ("week_delta_summary", "distilled_prior_amendments", "current_learned_file", "expected_amendment"):
            self.assertIn(key, golden)
        amendment = golden["expected_amendment"]
        self.assertTrue(amendment["amendment"])
        self.assertTrue(amendment["evidence"])
        lints = _parse_simple_yaml(GOLDENS_DIR.parent / "lints.yaml")
        max_chars = int(_parse_simple_yaml(GOLDENS_DIR.parent.parent / "interaction.yaml")["knob.weekly_edit_max_chars"])
        self.assertLessEqual(len(amendment["amendment"]), max_chars)
        self.assertEqual(lints["lint.amendment_within_edit_budget"], "on")

    def test_rubric_edit_golden_delta_reproduces_from_the_real_formatter(self):
        """The golden's week_delta_summary is not hand-typed prose — it is
        exactly what _format_week_delta() produces for the candidates the
        golden's evidence line cites (c-2291/c-2304/c-2318/c-2340)."""
        golden = self._load("rubric-edit-era-anchor-carveout-01.json")
        candidates = [
            {"id": "c-2291", "status": "rejected",
             "text": "What did a gallon of milk cost the year you moved to the farmhouse?",
             "decision_reason": "this is exactly the kind of specific texture I want — the too_broad flag is wrong here, promote next time",
             "updated_at": "2026-08-10T09:00:00Z"},
            {"id": "c-2304", "status": "rejected",
             "text": "Walk me through the house room by room the year you moved in.",
             "decision_reason": "same as c-2291 — era-anchor questions like this read as broad to the checker but are actually the good kind",
             "updated_at": "2026-08-11T09:00:00Z"},
            {"id": "c-2318", "status": "rejected",
             "text": "What was on the radio that whole summer?",
             "decision_reason": "another era-anchor false positive, I want more of these not fewer",
             "updated_at": "2026-08-12T09:00:00Z"},
            {"id": "c-2340", "status": "rejected",
             "text": "What did the car you drove that year actually cost you to keep running?",
             "decision_reason": "era-anchor again — this pattern keeps getting the too_broad flag and it should not",
             "updated_at": "2026-08-13T09:00:00Z"},
        ]
        summary = qj._format_week_delta(candidates, ["scene: 1.00 → 1.08 (+0.08)"])
        self.assertEqual(summary, golden["week_delta_summary"])

    def test_rubric_edit_golden_applies_end_to_end_through_run_weekly_edit(self):
        golden = self._load("rubric-edit-era-anchor-carveout-01.json")
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            cand_path = tmp / "candidates.json"
            cursor_path = tmp / "cursor.json"
            learned_path = tmp / "learned.md"
            _write_store(cand_path, [{"id": "seed", "status": "rejected", "text": "seed", "updated_at": "2026-08-01T00:00:00Z"}])
            response_path = tmp / "response.json"
            response_path.write_text(json.dumps(golden["expected_amendment"]), encoding="utf-8")
            result = qj.run_weekly_edit(
                from_response=str(response_path), candidates_path=cand_path,
                cursor_path=cursor_path, learned_path=learned_path,
            )
        self.assertEqual(result["status"], "amended")
        self.assertEqual(result["amendment"], golden["expected_amendment"]["amendment"])
        self.assertEqual(result["evidence"], golden["expected_amendment"]["evidence"])


class WiringTests(unittest.TestCase):
    """Scope 4/7: CLI registration, writer-lock classification, framework
    manifest, vault_contract, version bump, ADR presence."""

    def test_judgment_update_registered_as_a_direct_mutation_command(self):
        import lifehug
        self.assertIn("judgment-update", lifehug.DIRECT_MUTATION_COMMANDS)
        parser = lifehug.build_parser()
        subparsers = next(
            action for action in parser._actions  # noqa: SLF001
            if isinstance(action, __import__("argparse")._SubParsersAction)
        )
        self.assertIn("judgment-update", subparsers.choices)

    def test_weekly_maintenance_wires_judgment_update_after_quality_update(self):
        text = (SYSTEM / "weekly_maintenance.sh").read_text(encoding="utf-8")
        quality_idx = text.index('"quality_update" python3')
        # The real (non-keyless) wiring step, not the earlier dry-run preview
        # line — "judgment-update" as a bare substring appears in both.
        judgment_idx = text.index('"judgment_update" python3')
        auto_promote_idx = text.index('"auto_promote" python3')
        self.assertLess(quality_idx, judgment_idx)
        self.assertLess(judgment_idx, auto_promote_idx)

    def test_interaction_yaml_has_learned_max_chars_knob(self):
        interaction = _parse_simple_yaml(GOLDENS_DIR.parent.parent / "interaction.yaml")
        self.assertEqual(interaction["knob.learned_max_chars"], "8000")

    def test_vault_contract_registers_question_judgment_state_directory(self):
        import vault_paths
        entry = vault_paths.VAULT_DATA_PATHS["question_judgment_state"]
        self.assertEqual(entry["external_path"], "state/question_judgment")
        self.assertEqual(entry["kind"], "directory")
        self.assertTrue(entry.get("tracked"))
        self.assertFalse(entry.get("required", False))
        # learned.md's own file-level entry is unchanged — file, not folded
        # into the directory entry (test_question_judgment.py pins this too).
        learned = vault_paths.VAULT_DATA_PATHS["question_judgment_learned"]
        self.assertEqual(learned["kind"], "file")

    def test_question_judgment_state_and_learned_md_are_not_framework_files(self):
        version = json.loads((SYSTEM / "version.json").read_text(encoding="utf-8"))
        self.assertNotIn("state/question_judgment/learned.md", version["framework_files"])
        self.assertNotIn("state/question_judgment/last_edit.json", version["framework_files"])

    def test_new_goldens_are_framework_files(self):
        version = json.loads((SYSTEM / "version.json").read_text(encoding="utf-8"))
        self.assertIn(
            "interactions/question_judgment/evals/goldens/judge-scene-slot-accept-01.json",
            version["framework_files"],
        )
        self.assertIn(
            "interactions/question_judgment/evals/goldens/rubric-edit-era-anchor-carveout-01.json",
            version["framework_files"],
        )

    def test_version_bumped_past_v165(self):
        version = json.loads((SYSTEM / "version.json").read_text(encoding="utf-8"))
        self.assertGreaterEqual(version["version"], 166)

    def test_adr_0009_exists_and_links_the_followup_issue(self):
        adr = ROOT / "docs" / "adr" / "0009-decisions-feed-the-loop.md"
        self.assertTrue(adr.exists())
        text = adr.read_text(encoding="utf-8")
        self.assertIn("ADR 0009", text)
        self.assertIn("decision_reason", text)
        self.assertIn("lifehug/lifehug#148", text)


if __name__ == "__main__":
    unittest.main()
