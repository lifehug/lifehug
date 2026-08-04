import importlib.util
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SYSTEM = ROOT / "system"
sys.path.insert(0, str(SYSTEM))


def load_wrapper():
    return load_system("lifehug")


def load_system(name):
    spec = importlib.util.spec_from_file_location("lifehug", SYSTEM / "lifehug.py")
    if name != "lifehug":
        spec = importlib.util.spec_from_file_location(name, SYSTEM / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def subparser(parser, command):
    for action in parser._actions:
        if action.__class__.__name__ == "_SubParsersAction":
            return action.choices[command]
    raise AssertionError("subparser action not found")


def option_choices(parser, option):
    for action in parser._actions:
        if option in action.option_strings:
            return set(action.choices or [])
    raise AssertionError(f"{option} not found")


class LifehugWrapperTests(unittest.TestCase):
    def test_parser_accepts_canonical_commands(self):
        mod = load_wrapper()
        parser = mod.build_parser()
        for command in [
            ["status"],
            ["next"],
            ["compile", "--dry-run"],
            ["source-scan"],
            ["source-manifest", "--rebuild"],
            ["source-lint", "--fix", "--no-write-findings"],
            ["source-findings"],
            ["correct-source", "answers/A1.md", "--kind", "factual"],
            ["reflect-source", "answers/A1.md"],
            ["ingest-story", "--source", "telegram", "--title", "A Story"],
            ["candidates-list", "--status", "candidate", "--limit", "10"],
            ["candidates-review", "--source", "manual"],
            ["candidates-update", "cand-1", "--status", "accepted", "--target-category", "A"],
            ["candidates-promote", "cand-1", "--category", "A"],
            ["planner-report", "--limit", "5"],
            ["planner-queue", "--limit", "7", "--arc-max", "2", "--expires-days", "5"],
            ["planner-clear"],
            ["planner-state", "--init"],
            ["planner-objective-add", "Prepare Mom letter", "--category", "K", "--keyword", "mom"],
            ["planner-objective-clear"],
            ["artifact", "new", "--subject", "Mom", "--occasion", "Mother's Day", "--format", "letter"],
            ["artifact", "prompt", "outputs/mothers-day"],
            ["artifact", "save", "outputs/mothers-day", "--final"],
            ["artifact", "promote-source", "outputs/mothers-day", "--kind", "all"],
            ["classify-story", "--classify-all", "--unclassified", "--limit", "3", "--dry-run", "--verbose"],
            ["research-expand", "--topic", "Dad", "--type", "person", "--from-response", "/tmp/response.json"],
            ["recommend-focuses", "--type", "period"],
            ["entity-roster", "--type", "object", "--force-empty"],
            ["serve", "--port", "8765"],
            ["rebuild"],
            ["process-answer", "A1", "--source", "text", "--summary", "Short answer"],
            ["answer-ack-prompt"],
            ["daily-dry-run"],
            ["weekly-maintenance", "--dry-run"],
            ["monthly-research", "--dry-run", "--gap-limit", "2", "--self-topic", "Who I am becoming", "--focus-min-score", "15"],
            ["followups-status"],
            ["followups-prompt"],
            ["doctor", "--daily"],
        ]:
            with self.subTest(command=command):
                args = parser.parse_args(command)
                self.assertTrue(callable(args.func))

    def test_candidate_status_choices_match_candidate_manager(self):
        wrapper = load_wrapper()
        candidates = load_system("question_candidates")
        parser = wrapper.build_parser()
        expected = set(candidates.VALID_STATUSES)

        for command in ["candidates-list", "candidates-review", "candidates-update"]:
            with self.subTest(command=command):
                self.assertEqual(option_choices(subparser(parser, command), "--status"), expected)

    def test_research_expand_choices_match_expander(self):
        wrapper = load_wrapper()
        research = load_system("research_expand")
        parser = wrapper.build_parser()
        command = subparser(parser, "research-expand")

        self.assertEqual(option_choices(command, "--type"), set(research.VALID_TOPIC_TYPES))
        self.assertEqual(option_choices(command, "--output"), set(research.VALID_OUTPUT_TYPES))

    def test_recommend_focus_type_choices_match_recommender(self):
        wrapper = load_wrapper()
        recommends = load_system("recommend_focuses")
        parser = wrapper.build_parser()

        self.assertEqual(
            option_choices(subparser(parser, "recommend-focuses"), "--type"),
            set(recommends.FOCUS_RECOMMENDATION_TYPES),
        )

    def test_planner_queue_default_matches_delivery_horizon(self):
        wrapper = load_wrapper()
        planner = load_system("question_planner")
        parser = wrapper.build_parser()
        args = parser.parse_args(["planner-queue"])

        self.assertEqual(args.limit, planner.DEFAULT_DELIVERY_QUEUE_LIMIT)
        self.assertEqual(args.limit, 8)

    def test_telegram_target_detection_uses_config_or_env(self):
        mod = load_wrapper()
        self.assertTrue(mod.has_telegram_target({"telegram_chat_id": "123"}))
        self.assertTrue(mod.has_telegram_target({"group_chat_id": "-100123"}))
        self.assertFalse(mod.has_telegram_target({}))

    def test_weekly_maintenance_runs_classification_before_promotion(self):
        script = (SYSTEM / "weekly_maintenance.sh").read_text(encoding="utf-8")
        classify_index = script.index("classify-story --classify-all --unclassified --limit")
        promote_index = script.index("candidates-auto-promote")

        self.assertIn("CLASSIFY_LIMIT", script)
        self.assertIn("CLASSIFY_OUT=", script)
        self.assertLess(classify_index, promote_index)

    def test_weekly_dry_run_previews_candidate_auto_promotion(self):
        script = (SYSTEM / "weekly_maintenance.sh").read_text(encoding="utf-8")
        dry_run_index = script.index("candidates-auto-promote --dry-run")
        dry_run_exit_index = script.index("  exit 0", dry_run_index)
        real_promote_index = script.index("PROMOTE_OUT=")

        self.assertLess(dry_run_index, dry_run_exit_index)
        self.assertLess(dry_run_exit_index, real_promote_index)

    def test_weekly_maintenance_defaults_to_delivery_horizon(self):
        script = (SYSTEM / "weekly_maintenance.sh").read_text(encoding="utf-8")

        self.assertIn('QUEUE_LIMIT="${LIFEHUG_WEEKLY_QUEUE_LIMIT:-8}"', script)
        self.assertIn('planner-report --limit "$QUEUE_LIMIT"', script)
        self.assertIn('planner-queue --limit "$QUEUE_LIMIT"', script)

    def test_daily_compile_failure_is_recorded_without_blocking(self):
        script = (SYSTEM / "daily_question.sh").read_text(encoding="utf-8")

        self.assertIn('record_learning_failure "daily_question" "wiki_compile"', script)
        self.assertIn("COMPILE_STATUS=$?", script)
        self.assertIn('if [[ "$COMPILE_STATUS" -ne 0 ]]', script)

    def test_weekly_reports_recent_learning_failures(self):
        script = (SYSTEM / "weekly_maintenance.sh").read_text(encoding="utf-8")

        self.assertIn('record_learning_failure "weekly_maintenance" "classify_story"', script)
        self.assertIn("LEARNING_OUT=$(learning_failures_summary", script)
        # v86: learning failures go into the persisted report, not the
        # Telegram message (the summary derives its own failure counts).
        self.assertIn("Learning failures:LEARNING_OUT", script)
        self.assertIn("weekly-summary", script)

    def test_process_answer_learning_state_is_committed(self):
        script = (SYSTEM / "process_answer.py").read_text(encoding="utf-8")

        self.assertIn('"state"', script)
        self.assertIn('"quality_scoring"', script)

    def test_monthly_dry_run_previews_entity_roster_refresh(self):
        script = (SYSTEM / "monthly_research.sh").read_text(encoding="utf-8")
        dry_run_index = script.index('if [[ "$DRY_RUN" == "1" ]]')
        dry_run_exit_index = script.index("  exit 0", dry_run_index)
        preview_index = script.index("preview entity roster refreshes", dry_run_index)
        emit_task_index = script.index("--emit-task", preview_index)

        self.assertLess(preview_index, dry_run_exit_index)
        self.assertLess(emit_task_index, dry_run_exit_index)

    def test_monthly_report_includes_research_and_roster_output(self):
        # v86: research/roster output is persisted to the report document;
        # Telegram carries only the counts-first summary.
        script = (SYSTEM / "monthly_research.sh").read_text(encoding="utf-8")
        self.assertIn("Research neighborhoods:RESEARCH_OUT", script)
        self.assertIn("Entity rosters:ROSTER_OUT", script)
        notify_index = script.index('telegram_notify "')
        self.assertIn("${SUMMARY}", script[notify_index:])
        self.assertNotIn("${RESEARCH_OUT}", script[notify_index:])


if __name__ == "__main__":
    unittest.main()
