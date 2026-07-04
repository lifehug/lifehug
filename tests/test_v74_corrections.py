"""v74 — corrections & retraction resolution (issue #24)."""

import importlib.util
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SYSTEM = ROOT / "system"
sys.path.insert(0, str(SYSTEM))


def load(name):
    spec = importlib.util.spec_from_file_location(name, SYSTEM / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


wc = load("wiki_compile")


def _answer(qid, body="original claim"):
    return {"id": qid, "path": Path(f"answers/{qid}.md"), "source": f"answers/{qid}.md",
            "body": body, "sensitivity": "private"}


def _correction(target_id, target_path, body):
    return {"id": f"correction:x", "source": "sources/corrections/x.md", "kind": "source_correction",
            "corrects": target_id, "corrects_path": target_path, "body": body,
            "retracts": "", "retracts_path": "", "suppress_on": []}


def _retraction(target_id, target_path, suppress_on=None):
    return {"id": "retraction:y", "source": "sources/corrections/y.md", "kind": "source_retraction",
            "retracts": target_id, "retracts_path": target_path,
            "suppress_on": suppress_on or [], "corrects": "", "corrects_path": "", "body": "reason"}


class SplitLayerTests(unittest.TestCase):
    def test_corrections_and_retractions_leave_narrative_pool(self):
        manual = {
            "manual:story": {"id": "manual:story", "kind": "unprompted_story", "body": "b",
                             "source": "sources/manual/story.md"},
            "correction:x": _correction("answer:A7", "answers/A7.md", "It was 2004."),
            "retraction:y": _retraction("answer:L20", "answers/L20.md"),
            "reflection:z": {"id": "reflection:z", "kind": "source_reflection", "body": "b",
                             "source": "sources/corrections/z.md"},
        }
        narrative, corrections, retractions = wc.split_correction_layer(manual)
        self.assertEqual(set(narrative), {"manual:story", "reflection:z"})  # reflections stay narrative
        self.assertEqual(len(corrections), 1)
        self.assertEqual(len(retractions), 1)


class CorrectionTests(unittest.TestCase):
    def test_correction_appends_authoritative_marker(self):
        answers = {"A7": _answer("A7", "We moved in 2006.")}
        n = wc.apply_corrections(answers, {}, [_correction("answer:A7", "answers/A7.md", "It was 2004, not 2006.")])
        self.assertEqual(n, 1)
        self.assertIn(wc.CORRECTION_MARKER, answers["A7"]["body"])
        self.assertIn("It was 2004", answers["A7"]["body"])
        self.assertIn("We moved in 2006.", answers["A7"]["body"])  # original preserved, never erased
        self.assertTrue(answers["A7"]["corrected"])

    def test_correction_matches_by_path_too(self):
        answers = {"A7": _answer("A7")}
        correction = _correction("", "answers/A7.md", "fix")
        self.assertEqual(wc.apply_corrections(answers, {}, [correction]), 1)

    def test_unmatched_correction_is_noop(self):
        answers = {"A7": _answer("A7")}
        self.assertEqual(wc.apply_corrections(answers, {}, [_correction("answer:ZZ", "answers/ZZ.md", "x")]), 0)

    def test_prompt_carries_override_instruction(self):
        corrected = {**_answer("A7", f"claim\n\n{wc.CORRECTION_MARKER} the fix"), "corrected": True}
        desc = {"type": "life", "title": "T", "slug": "t",
                "cited_items": [corrected], "supporting_items": []}
        prompt = wc.build_synthesis_prompt(desc, [], "")
        self.assertIn("never assert the corrected-away version", prompt)

    def test_no_correction_no_instruction(self):
        desc = {"type": "life", "title": "T", "slug": "t",
                "cited_items": [_answer("A7")], "supporting_items": []}
        prompt = wc.build_synthesis_prompt(desc, [], "")
        self.assertNotIn("corrected-away", prompt)


class RetractionTests(unittest.TestCase):
    def setUp(self):
        self._orig = wc._RETRACTIONS

    def tearDown(self):
        wc._RETRACTIONS = self._orig

    def _desc(self, slug):
        items = [_answer("L20"), _answer("A5")]
        return wc._descriptor("period", "Childhood", slug, [i["source"] for i in items],
                              items, [], summary="s", open_questions=[])

    def test_global_retraction_suppresses_everywhere(self):
        wc._RETRACTIONS = [_retraction("answer:L20", "answers/L20.md")]
        desc = self._desc("childhood")
        self.assertEqual([i["id"] for i in desc["cited_items"]], ["A5"])
        self.assertEqual(desc["sources"], ["answers/A5.md"])

    def test_scoped_retraction_only_hits_named_pages(self):
        wc._RETRACTIONS = [_retraction("answer:L20", "answers/L20.md", suppress_on=["childhood", "origins"])]
        on_childhood = self._desc("childhood")
        self.assertEqual([i["id"] for i in on_childhood["cited_items"]], ["A5"])
        on_katie = self._desc("katie")
        self.assertEqual([i["id"] for i in on_katie["cited_items"]], ["L20", "A5"])  # untouched elsewhere

    def test_no_retractions_no_filtering(self):
        wc._RETRACTIONS = []
        desc = self._desc("childhood")
        self.assertEqual(len(desc["cited_items"]), 2)


class RetractionRecordTests(unittest.TestCase):
    def test_retraction_record_shape(self):
        import tempfile
        si = load("source_integrity")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            answers = root / "answers"
            answers.mkdir()
            target = answers / "L20.md"
            target.write_text("---\ntitle: \"Q\"\nsource_id: \"answer:L20\"\n---\n\n# Q\n\nbody\n", encoding="utf-8")
            live = sys.modules["source_integrity"]
            orig = (live.REPO_DIR, live.CORRECTION_SOURCES_DIR, live.ANSWERS_DIR, live.SOURCE_MANIFEST_FILE)
            live.REPO_DIR = root
            live.CORRECTION_SOURCES_DIR = root / "sources" / "corrections"
            live.ANSWERS_DIR = answers
            live.SOURCE_MANIFEST_FILE = root / "state" / "source_manifest.json"
            try:
                path = live.create_linked_source(
                    "answers/L20.md", "About Katie's childhood, not the author's.",
                    source_type="source_retraction", title=None, source_medium="fix",
                    suppress_on=["childhood"])
                text = path.read_text(encoding="utf-8")
            finally:
                (live.REPO_DIR, live.CORRECTION_SOURCES_DIR, live.ANSWERS_DIR, live.SOURCE_MANIFEST_FILE) = orig
            self.assertIn('type: "source_retraction"', text)
            self.assertIn('retracts: "answer:L20"', text)
            self.assertIn("childhood", text)
            self.assertIn("About Katie's childhood", text)


class ClassifierCorrectionsTests(unittest.TestCase):
    def test_corrections_block_in_prompt(self):
        import tempfile
        cls = load("classify_story")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            corrections = root / "sources" / "corrections"
            corrections.mkdir(parents=True)
            (corrections / "c1.md").write_text(
                '---\ntitle: "Correction"\ntype: "source_correction"\n'
                'corrects: "answer:A7"\ncorrects_path: "answers/A7.md"\n---\n\n'
                "# Correction\n\nIt was 2004, not 2006.\n", encoding="utf-8")
            live = sys.modules["classify_story"]
            orig = (live.SOURCES_DIR, live.REPO_DIR)
            live.SOURCES_DIR = root / "sources"
            live.REPO_DIR = root
            try:
                src = root / "answers" / "A7.md"
                src.parent.mkdir()
                src.write_text("body", encoding="utf-8")
                prompt = live.build_prompt(src, {"title": "t"}, "We moved in 2006.")
            finally:
                live.SOURCES_DIR, live.REPO_DIR = orig
            self.assertIn("LATER CORRECTIONS", prompt)
            self.assertIn("It was 2004", prompt)


if __name__ == "__main__":
    unittest.main()
