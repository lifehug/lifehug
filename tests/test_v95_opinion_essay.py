"""v95: opinion capture (--kind opinion) + seeded essay artifacts (--seed)."""

import argparse
import contextlib
import importlib.util
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SYSTEM = ROOT / "system"
sys.path.insert(0, str(SYSTEM))

import lifehug_core

SELF_FUNCTIONS = ("self_image", "value", "fear", "contradiction",
                  "perception_by_others", "growth_edge")


def load(name):
    spec = importlib.util.spec_from_file_location(name, SYSTEM / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


class OpinionIngestTests(unittest.TestCase):
    def setUp(self):
        self.ingest = load("ingest_story")

    def test_opinion_candidates_are_socratic_self_functions(self):
        candidates = self.ingest.generate_opinion_candidates(
            "The Mantle Of Responsibility", "sources/manual/x.md", "2026-07-06T00:00:00Z")
        self.assertEqual(len(candidates), 5)
        for candidate in candidates:
            self.assertIn(candidate["story_function"], SELF_FUNCTIONS)
            self.assertLessEqual(candidate["priority"], 0.65)
            self.assertNotEqual(candidate["kind"], "scene")
        kinds = {c["kind"] for c in candidates}
        self.assertEqual(kinds, {"origin", "counterexample", "evolution", "dissent", "stakes"})

    def test_story_candidates_unchanged(self):
        candidates = self.ingest.generate_candidates(
            "Arizona Memory", "short story text", "sources/manual/y.md", "2026-07-06T00:00:00Z")
        self.assertEqual({c["kind"] for c in candidates},
                         {"foundation", "scene", "relationships", "meaning"})

    def test_opinion_frontmatter_type(self):
        args = argparse.Namespace(title="A Position", source="manual",
                                  captured_at="2026-07-06T00:00:00Z",
                                  witness=None, sensitivity="private", kind="opinion")
        fm = self.ingest.frontmatter(args, "sources/manual/a-position.md", [], "# A Position\n\nbody\n")
        metadata, _ = lifehug_core.split_frontmatter(fm + "\n\nbody\n")
        self.assertEqual(metadata.get("type"), "opinion")

    def test_story_frontmatter_type_unchanged(self):
        args = argparse.Namespace(title="A Story", source="manual",
                                  captured_at="2026-07-06T00:00:00Z",
                                  witness=None, sensitivity="private", kind="story")
        fm = self.ingest.frontmatter(args, "sources/manual/a-story.md", [], "# A Story\n\nbody\n")
        metadata, _ = lifehug_core.split_frontmatter(fm + "\n\nbody\n")
        self.assertEqual(metadata.get("type"), "unprompted_story")

    def test_witness_kind_conflict_rejected(self):
        argv = ["ingest_story.py", "--kind", "opinion", "--witness", "Mom"]
        stderr = io.StringIO()
        with self._patched_argv(argv), self._patched_stdin("some text"), \
                contextlib.redirect_stderr(stderr):
            code = self.ingest.main()
        self.assertEqual(code, 1)
        self.assertIn("--witness", stderr.getvalue())

    def test_opinion_ingest_end_to_end(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            manual = root / "sources" / "manual"
            self.ingest.REPO_DIR = root
            self.ingest.MANUAL_SOURCES_DIR = manual
            self.ingest.QUESTION_CANDIDATES_FILE = root / "state" / "question_candidates.json"
            self.ingest.register_source = lambda _path: {}
            argv = ["ingest_story.py", "--kind", "opinion",
                    "--title", "The Mantle Of Responsibility", "--source", "test"]
            stdout = io.StringIO()
            with self._patched_argv(argv), \
                    self._patched_stdin("Parents wore a mantle of responsibility."), \
                    contextlib.redirect_stdout(stdout):
                code = self.ingest.main()
            self.assertEqual(code, 0)
            files = list(manual.glob("*.md"))
            self.assertEqual(len(files), 1)
            metadata, body = lifehug_core.split_frontmatter(files[0].read_text())
            self.assertEqual(metadata.get("type"), "opinion")
            self.assertIn("mantle of responsibility", body)
            candidates = json.loads(
                (root / "state" / "question_candidates.json").read_text())["candidates"]
            self.assertEqual(len(candidates), 5)
            self.assertTrue(all(c.get("story_function") in SELF_FUNCTIONS for c in candidates))
            self.assertIn("artifact new --format essay --seed", stdout.getvalue())

    @contextlib.contextmanager
    def _patched_argv(self, argv):
        old = sys.argv
        sys.argv = argv
        try:
            yield
        finally:
            sys.argv = old

    @contextlib.contextmanager
    def _patched_stdin(self, text):
        old = sys.stdin
        sys.stdin = io.StringIO(text)
        try:
            yield
        finally:
            sys.stdin = old


class EssayFormatTests(unittest.TestCase):
    def test_essay_in_valid_formats(self):
        compose = load("compose")
        self.assertIn("essay", compose.VALID_FORMATS)

    def test_essay_template_exists(self):
        template = ROOT / "templates" / "essay.md"
        self.assertTrue(template.exists())
        text = template.read_text()
        self.assertIn("Seed Source", text)
        self.assertIn("essay", text.lower())


class SeededArtifactTests(unittest.TestCase):
    def setUp(self):
        self.artifact = load("artifact")

    def _seed_repo(self, root):
        seed = root / "sources" / "manual" / "2026-07-06-mantle.md"
        seed.parent.mkdir(parents=True)
        seed.write_text(
            '---\ntitle: "The Mantle Of Responsibility"\ntype: "opinion"\n---\n\n'
            "# The Mantle Of Responsibility\n\n"
            "Parents wore a mantle of responsibility, living above their natural selves.\n")
        answers = root / "answers"
        answers.mkdir()
        (answers / "A1.md").write_text("# Question A1: Earliest memory?\n\nUnrelated answer body.\n")
        self.artifact.REPO_DIR = root
        self.artifact.OUTPUTS_DIR = root / "outputs"
        self.artifact.WIKI_DIR = root / "wiki"
        return seed

    def _meta(self, root, with_seed=True, categories=None):
        meta = {
            "version": 1,
            "artifact_id": "mantle-essay",
            "title": "mantle-essay",
            "format": "essay",
            "subject": "",
            "occasion": "",
            "occasion_date": "",
            "audience": "",
            "privacy": "owner_only",
            "categories": categories or [],
            "context_path": "outputs/mantle-essay/context.md",
            "context_sources": [],
            "versions": [],
            "promoted_sources": [],
        }
        if with_seed:
            meta["seed_source"] = "sources/manual/2026-07-06-mantle.md"
        return meta

    def test_seed_section_first_and_verbatim(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self._seed_repo(root)
            meta = self._meta(root)
            out_dir = root / "outputs" / "mantle-essay"
            out_dir.mkdir(parents=True)
            context, sources = self.artifact.build_context(meta, out_dir)
            self.assertIn("## Seed Source — the author's stated position (verbatim)", context)
            self.assertIn("mantle of responsibility", context)
            seed_pos = context.index("## Seed Source")
            answers_pos = context.index("## Source Answers")
            self.assertLess(seed_pos, answers_pos)
            self.assertEqual(sources[0], "sources/manual/2026-07-06-mantle.md")

    def test_seeded_unscoped_pack_skips_answer_corpus(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self._seed_repo(root)
            meta = self._meta(root)
            out_dir = root / "outputs" / "mantle-essay"
            out_dir.mkdir(parents=True)
            context, sources = self.artifact.build_context(meta, out_dir)
            self.assertNotIn("Unrelated answer body", context)
            self.assertNotIn("answers/A1.md", sources)

    def test_seeded_with_categories_still_gathers_answers(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self._seed_repo(root)
            meta = self._meta(root, categories=["A"])
            out_dir = root / "outputs" / "mantle-essay"
            out_dir.mkdir(parents=True)
            calls = []

            def fake_answers(categories):
                calls.append(categories)
                return [], []

            original = self.artifact.source_answers_for
            self.artifact.source_answers_for = fake_answers
            try:
                self.artifact.build_context(meta, out_dir)
            finally:
                self.artifact.source_answers_for = original
            self.assertEqual(calls, [["A"]])

    def test_unseeded_context_unchanged(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self._seed_repo(root)
            meta = self._meta(root, with_seed=False)
            out_dir = root / "outputs" / "mantle-essay"
            out_dir.mkdir(parents=True)
            # unscoped + unseeded keeps today's behavior: source_answers_for is
            # called with the empty category list (the whole-corpus path)
            calls = []
            original = self.artifact.source_answers_for
            self.artifact.source_answers_for = lambda cats: (calls.append(cats), original(cats))[1]
            try:
                context, _sources = self.artifact.build_context(meta, out_dir)
            finally:
                self.artifact.source_answers_for = original
            self.assertNotIn("Seed Source", context)
            self.assertEqual(calls, [[]])

    def test_prompt_seed_addendum(self):
        meta_seeded = {"format": "essay", "title": "t", "seed_source": "sources/manual/x.md"}
        meta_plain = {"format": "essay", "title": "t"}
        prompt_seeded = self.artifact.build_prompt(meta_seeded, "ctx")
        prompt_plain = self.artifact.build_prompt(meta_plain, "ctx")
        self.assertIn("SEED DEVELOPMENT", prompt_seeded)
        self.assertNotIn("SEED DEVELOPMENT", prompt_plain)
        # non-seeded prompt keeps the original spacing (regression guard)
        self.assertIn("excerpts or Q&A.\n\nFORMAT INSTRUCTIONS", prompt_plain)

    def test_cmd_prompt_rebuild_reproduces_seed(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self._seed_repo(root)
            meta = self._meta(root)
            out_dir = root / "outputs" / "mantle-essay"
            out_dir.mkdir(parents=True)
            (out_dir / "artifact.json").write_text(json.dumps(meta))
            stdout = io.StringIO()
            args = argparse.Namespace(output=str(out_dir))
            with contextlib.redirect_stdout(stdout):
                code = self.artifact.cmd_prompt(args)
            self.assertEqual(code, 0)
            self.assertIn("## Seed Source", stdout.getvalue())
            self.assertIn("## Seed Source", (out_dir / "context.md").read_text())

    def test_promoted_essay_carries_artifact_format(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            out_dir = root / "outputs" / "mantle-essay"
            out_dir.mkdir(parents=True)
            (out_dir / "context.md").write_text("# Artifact Context\n\nSeed.\n")
            (out_dir / "v1.md").write_text("The essay text.\n")
            meta = self._meta(root)
            meta["context_sources"] = ["sources/manual/2026-07-06-mantle.md"]
            meta["versions"] = [{"version": 1, "path": "outputs/mantle-essay/v1.md"}]
            meta["final_version"] = 1
            meta["context_path"] = "outputs/mantle-essay/context.md"
            (out_dir / "artifact.json").write_text(json.dumps(meta))
            self.artifact.REPO_DIR = root
            self.artifact.OUTPUTS_DIR = root / "outputs"
            self.artifact.ARTIFACT_SOURCES_DIR = root / "sources" / "artifacts"
            self.artifact.register_source = lambda _path: {}
            args = argparse.Namespace(output=str(out_dir), kind="final", version="final", source="test")
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                code = self.artifact.cmd_promote_source(args)
            self.assertEqual(code, 0)
            promoted = list((root / "sources" / "artifacts").glob("*.md"))
            self.assertEqual(len(promoted), 1)
            metadata, _ = lifehug_core.split_frontmatter(promoted[0].read_text())
            self.assertEqual(metadata.get("type"), "authored_artifact")
            self.assertEqual(metadata.get("artifact_format"), "essay")


if __name__ == "__main__":
    unittest.main()
