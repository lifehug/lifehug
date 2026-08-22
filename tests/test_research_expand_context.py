"""v189 / focus-onboarding-context Design §E — the seed generator finally
hears the onboarding conversation.

Everything here is pure prompt construction plus one argv spy: no model, no
network, and no writes to the vault.
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SYSTEM = ROOT / "system"
sys.path.insert(0, str(SYSTEM))

import focus_candidate  # noqa: E402
import research_expand  # noqa: E402
import roadmap  # noqa: E402

CONTEXT = {
    "objective": "her working years at the synthetic mill",
    "type": "person",
    "relationship": "parent",
    "living": False,
    "label": "Ma",
    "first_answer": "She ran the second shift for thirty-one years.",
}


def _prompt(**overrides) -> str:
    kwargs = dict(
        topic="Synthetic Ada",
        topic_type="person",
        target_output="chapter",
        mission="synthetic mission",
        source_content="",
        relevant_answers=[],
        question_bank_categories="",
    )
    kwargs.update(overrides)
    return research_expand.build_expansion_prompt(**kwargs)


class OnboardingContextPromptTests(unittest.TestCase):
    def test_prompt_byte_identical_without_onboarding_context(self):
        # Owner ruling 6: Play with no answers must seed exactly as it did at
        # v188. Absent context, the prompt is byte-for-byte the old prompt —
        # including the explicit-None spelling the CLI passes.
        self.assertEqual(_prompt(), _prompt(onboarding_context=None))
        self.assertEqual(_prompt(), _prompt(onboarding_context={}))
        self.assertNotIn("FOCUS ONBOARDING CONTEXT", _prompt())

    def test_context_block_renders_objective_label_and_first_answer(self):
        prompt = _prompt(onboarding_context=focus_candidate.normalize_onboarding_context(CONTEXT))
        self.assertIn("## FOCUS ONBOARDING CONTEXT", prompt)
        self.assertIn("Objective: her working years at the synthetic mill", prompt)
        self.assertIn("Focus name: Ma", prompt)
        self.assertIn("Relationship to the author: parent", prompt)
        self.assertIn('"She ran the second shift for thirty-one years."', prompt)

    def test_context_block_lands_above_the_arc_so_it_frames_generation(self):
        prompt = _prompt(onboarding_context={"objective": "the mill years"})
        self.assertLess(
            prompt.index("## FOCUS ONBOARDING CONTEXT"), prompt.index("## ARC STRUCTURE")
        )

    def test_not_living_says_remember_never_ask(self):
        prompt = _prompt(onboarding_context={"living": False})
        self.assertIn("write questions that REMEMBER them", prompt)
        self.assertIn("never write a question that asks them something directly", prompt)
        self.assertIn("Living: yes.", _prompt(onboarding_context={"living": True}))

    def test_person_with_relationship_gets_its_interview_bank(self):
        prompt = _prompt(onboarding_context={"relationship": "parent", "living": True})
        self.assertIn("## INTERVIEW BANK FOR THIS RELATIONSHIP (parent)", prompt)
        for question in research_expand.INTERVIEW_BANKS["parent"]:
            self.assertIn(question, prompt)

    def test_not_living_selects_the_remembering_bank_over_the_relationship_one(self):
        prompt = _prompt(onboarding_context={"relationship": "parent", "living": False})
        self.assertIn("## INTERVIEW BANK FOR THIS RELATIONSHIP (remembering)", prompt)
        self.assertIn("What do you wish you'd asked them?", prompt)

    def test_mapped_relationships_reach_their_banks(self):
        for relationship, bank in (("partner", "spouse"), ("colleague", "cofounder"), ("other", "friend")):
            with self.subTest(relationship=relationship):
                prompt = _prompt(onboarding_context={"relationship": relationship, "living": True})
                self.assertIn(f"## INTERVIEW BANK FOR THIS RELATIONSHIP ({bank})", prompt)

    def test_non_person_topics_get_context_but_no_interview_bank(self):
        prompt = _prompt(
            topic="Synthetic Harbor",
            topic_type="place",
            onboarding_context={"objective": "the summers there", "relationship": "parent"},
        )
        self.assertIn("## FOCUS ONBOARDING CONTEXT", prompt)
        self.assertNotIn("INTERVIEW BANK", prompt)


class ContextFileCliTests(unittest.TestCase):
    def _args(self, **overrides) -> argparse.Namespace:
        fields = dict(
            output="chapter",
            dry_run=True,
            prompt=False,
            from_response=None,
            force=True,
            model=None,
            context_file=None,
        )
        fields.update(overrides)
        return argparse.Namespace(**fields)

    def test_the_flag_exists_with_the_spelling_the_platform_pins(self):
        parsed = research_expand.build_parser().parse_args(
            ["--topic", "Synthetic Ada", "--context-file", "/tmp/ctx.json"]
        )
        self.assertEqual(parsed.context_file, "/tmp/ctx.json")

    def test_context_file_missing_or_unparseable_is_an_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            bad = Path(tmp) / "not-json.json"
            bad.write_text("{not json", encoding="utf-8")
            for path in (str(Path(tmp) / "absent.json"), str(bad)):
                with self.subTest(path=path):
                    code = research_expand._run_expansion(
                        args=self._args(context_file=path),
                        topic="Synthetic Ada",
                        topic_type="person",
                        source_path="topic:person/synthetic-ada",
                        source_content="",
                    )
                    self.assertEqual(code, 1)

    def test_context_file_error_never_leaks_the_exception_text(self):
        # system/research_expand.py is on the model-callsite redaction guard's
        # list (tests/test_v123_local_ai_provider.py); the new failure path
        # reports metadata only.
        source = (SYSTEM / "research_expand.py").read_text(encoding="utf-8")
        self.assertIn("research-expand-context-file", source)
        self.assertNotIn("could not read onboarding context {context_path}: {exc}", source)

    def test_a_context_that_normalizes_to_nothing_is_not_an_error(self):
        # Owner ruling 6 again: nothing blocks. An empty or all-invalid
        # context file still seeds from the recommendation's own evidence.
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "ctx.json"
            path.write_text(json.dumps({"type": "spaceship"}), encoding="utf-8")
            code = research_expand._run_expansion(
                args=self._args(context_file=str(path)),
                topic="Synthetic Ada",
                topic_type="person",
                source_path="topic:person/synthetic-ada",
                source_content="",
            )
            self.assertEqual(code, 0)  # --dry-run path, no writes

    def test_a_mock_args_namespace_never_becomes_a_path(self):
        # Several suites drive _run_expansion with a Mock, and a Mock is
        # truthy for every attribute asked of it. The flag reads by isinstance
        # so an un-passed flag stays un-passed.
        code = research_expand._run_expansion(
            args=mock.Mock(
                output="chapter", dry_run=True, prompt=False, from_response=None,
                force=True, model=None,
            ),
            topic="Synthetic Ada",
            topic_type="person",
            source_path="topic:person/synthetic-ada",
            source_content="",
        )
        self.assertEqual(code, 0)


class ThreadingTests(unittest.TestCase):
    def test_generate_and_promote_threads_the_context_path_into_argv(self):
        with mock.patch("subprocess.run") as run:
            run.return_value = mock.Mock(returncode=1, stdout="", stderr="")
            roadmap._generate_and_promote(
                "Synthetic Ada", "person", "chapter", "F", context_path="/tmp/ctx.json"
            )
        argv = run.call_args[0][0]
        self.assertIn("--context-file", argv)
        self.assertEqual(argv[argv.index("--context-file") + 1], "/tmp/ctx.json")

    def test_no_context_path_builds_the_pre_v189_argv_exactly(self):
        with mock.patch("subprocess.run") as run:
            run.return_value = mock.Mock(returncode=1, stdout="", stderr="")
            roadmap._generate_and_promote("Synthetic Ada", "person", "chapter", "F")
        argv = run.call_args[0][0]
        self.assertNotIn("--context-file", argv)
        self.assertEqual(
            argv[1:],
            [
                str(SYSTEM / "research_expand.py"),
                "--topic", "Synthetic Ada",
                "--type", "person",
                "--output", "chapter",
                "--force",
            ],
        )

    def test_focus_new_passes_context_path_through(self):
        with mock.patch.object(roadmap, "_generate_and_promote", return_value=(False, 0)) as gen:
            with mock.patch.object(roadmap, "load_roadmap", return_value={"focuses": [{"id": "x"}]}), \
                 mock.patch.object(roadmap, "find_focus_by_key", return_value=None), \
                 mock.patch.object(roadmap, "scaffold_category", return_value=("bank", "F")), \
                 mock.patch.object(roadmap, "write_text"), \
                 mock.patch.object(roadmap, "write_json"), \
                 mock.patch.object(roadmap, "rebuild_roadmap", return_value={"focuses": []}), \
                 mock.patch.object(roadmap, "find_focus", return_value=None), \
                 mock.patch.object(roadmap, "rebuild_coverage"), \
                 mock.patch.object(roadmap.QUESTIONS_FILE, "read_text", return_value="bank"):
                roadmap.focus_new(
                    "Synthetic Ada", "person", "standard", context_path="/tmp/ctx.json"
                )
        self.assertEqual(gen.call_args.kwargs["context_path"], "/tmp/ctx.json")


class FocusSetFieldTests(unittest.TestCase):
    def test_the_four_onboarding_fields_are_all_user_fields(self):
        # They survive derive_roadmap re-derivation for free — that is why
        # focus-set can write them with no other change (Design §E.4).
        for field in ("label", "type", "relationship", "living"):
            self.assertIn(field, roadmap._USER_FIELDS)

    def test_focus_set_accepts_the_new_flags(self):
        import lifehug  # noqa: PLC0415

        args = lifehug.build_parser().parse_args(
            ["focus-set", "synthetic-ada", "--label", "Ma", "--type", "person",
             "--relationship", "parent", "--not-living"]
        )
        self.assertEqual(args.label, "Ma")
        self.assertEqual(args.focus_type, "person")
        self.assertEqual(args.relationship, "parent")
        self.assertIs(args.living, False)

    def test_roadmap_set_writes_label_type_relationship_and_living(self):
        focus = {"id": "synthetic-ada", "label": "Synthetic Ada", "type": "theme"}
        with mock.patch.object(roadmap, "load_roadmap", return_value={"focuses": [focus]}), \
             mock.patch.object(roadmap, "write_json") as write_json:
            self.assertEqual(
                roadmap.cli([
                    "set", "synthetic-ada", "--label", "Ma", "--type", "person",
                    "--relationship", "parent", "--not-living",
                ]),
                0,
            )
        self.assertTrue(write_json.called)
        self.assertEqual(focus["label"], "Ma")
        self.assertEqual(focus["type"], "person")
        self.assertEqual(focus["relationship"], "parent")
        self.assertIs(focus["living"], False)

    def test_roadmap_set_leaves_the_new_fields_alone_when_no_flag_is_given(self):
        focus = {"id": "synthetic-ada", "label": "Synthetic Ada", "type": "theme"}
        with mock.patch.object(roadmap, "load_roadmap", return_value={"focuses": [focus]}), \
             mock.patch.object(roadmap, "write_json"):
            self.assertEqual(roadmap.cli(["set", "synthetic-ada", "--tier", "extreme"]), 0)
        self.assertEqual(focus["label"], "Synthetic Ada")
        self.assertEqual(focus["type"], "theme")
        self.assertNotIn("relationship", focus)
        self.assertNotIn("living", focus)


if __name__ == "__main__":
    unittest.main()
