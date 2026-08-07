"""v119 — bounded, portable correction/retraction filenames (issue #50)."""

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SYSTEM = ROOT / "system"
sys.path.insert(0, str(SYSTEM))

# Keep the canonical shared module installed while this file loads isolated
# copies. Older correction tests intentionally verify that private test loads
# restore, rather than remove, the process-wide source_integrity module.
import source_integrity as _canonical_source_integrity  # noqa: E402,F401


def load(name):
    spec = importlib.util.spec_from_file_location(name, SYSTEM / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    original = sys.modules.get(name)
    sys.modules[name] = mod
    try:
        spec.loader.exec_module(mod)
    finally:
        if original is not None:
            sys.modules[name] = original
        else:
            sys.modules.pop(name, None)
    return mod


class BoundedLinkedFilenameTests(unittest.TestCase):
    def setUp(self):
        self.src = load("source_integrity")
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.answers = self.root / "answers"
        self.corrections = self.root / "sources" / "corrections"
        self.answers.mkdir(parents=True)
        self.corrections.mkdir(parents=True)
        self.target = self.answers / "A1.md"
        self.target.write_text(
            "---\n"
            'title: "Question A1: café / ../../ keep this out of filenames"\n'
            'source_id: "answer:A1"\n'
            'type: "prompted_answer"\n'
            "---\n\n# Question A1\n\nAnswer.\n",
            encoding="utf-8",
        )
        self.originals = (
            self.src.REPO_DIR, self.src.CORRECTION_SOURCES_DIR,
            self.src.SOURCE_MANIFEST_FILE, self.src.ANSWERS_DIR, self.src.WIKI_DIR,
        )
        self.src.REPO_DIR = self.root
        self.src.CORRECTION_SOURCES_DIR = self.corrections
        self.src.SOURCE_MANIFEST_FILE = self.root / "state" / "source_manifest.json"
        self.src.ANSWERS_DIR = self.answers
        self.src.WIKI_DIR = self.root / "wiki"

    def tearDown(self):
        (self.src.REPO_DIR, self.src.CORRECTION_SOURCES_DIR,
         self.src.SOURCE_MANIFEST_FILE, self.src.ANSWERS_DIR, self.src.WIKI_DIR) = self.originals
        self.tmp.cleanup()

    def test_new_names_are_bounded_ascii_and_never_embed_question_text(self):
        path = self.src.create_linked_source(
            "answers/A1.md", "It happened in 2004.", source_type="source_correction",
            title=None, source_medium="test", correction_kind="factual",
        )
        self.assertLessEqual(len(path.name.encode("utf-8")), self.src.MAX_LINKED_SOURCE_FILENAME_BYTES)
        self.assertRegex(path.name, r"^\d{4}-\d{2}-\d{2}-correction-answer-a1-[0-9a-f]+\.md$")
        self.assertNotIn("café", path.name)
        self.assertNotIn("keep-this", path.name)
        self.assertNotIn("..", path.name)
        self.assertLess(len((Path("sources/corrections") / path.name).as_posix()), 240)

    def test_same_visible_target_label_stays_unique_by_payload_hash(self):
        one = self.src._linked_source_path(
            self.corrections, "answer:A1", "source_correction", "# Correction\n\nOne\n", "2026-08-06T00:00:00Z"
        )
        two = self.src._linked_source_path(
            self.corrections, "answer:A1", "source_correction", "# Correction\n\nTwo\n", "2026-08-06T00:00:00Z"
        )
        self.assertNotEqual(one, two)

    def test_malformed_capture_time_cannot_escape_the_corrections_directory(self):
        path = self.src._linked_source_path(
            self.corrections, "answer:A1", "source_correction", "# Correction\n\nOne\n", "../../escape"
        )
        self.assertEqual(path.resolve().parent, self.corrections.resolve())
        self.assertRegex(path.name, r"^1970-01-01-correction-answer-a1-[0-9a-f]+\.md$")

    def test_impossible_capture_dates_use_the_deterministic_fallback(self):
        payload = "# Correction\n\nOne\n"
        for captured_at in ("2026-99-99T00:00:00Z", "2026-02-30T00:00:00Z"):
            path = self.src._linked_source_path(
                self.corrections, "answer:A1", "source_correction", payload, captured_at
            )
            self.assertRegex(path.name, r"^1970-01-01-correction-answer-a1-[0-9a-f]+\.md$")

    def test_valid_capture_date_is_preserved_in_linked_source_name(self):
        path = self.src._linked_source_path(
            self.corrections,
            "answer:A1",
            "source_correction",
            "# Correction\n\nOne\n",
            "2026-02-28T23:59:59Z",
        )
        self.assertRegex(path.name, r"^2026-02-28-correction-answer-a1-[0-9a-f]+\.md$")

    def test_hash_prefix_collision_extends_deterministically_without_counter_suffix(self):
        payload = "# Correction\n\nOne\n"
        first = self.src._linked_source_path(
            self.corrections, "answer:A1", "source_correction", payload, "2026-08-06T00:00:00Z"
        )
        first.write_text("---\ntype: source_retraction\nretracts: answer:other\n---\n\nother\n", encoding="utf-8")
        resolved = self.src._linked_source_path(
            self.corrections, "answer:A1", "source_correction", payload, "2026-08-06T00:00:00Z"
        )
        self.assertNotEqual(first, resolved)
        self.assertGreater(len(resolved.stem.rsplit("-", 1)[1]), self.src.LINKED_SOURCE_HASH_LENGTH)
        self.assertNotRegex(resolved.name, r"-\d+\.md$")

    def _legacy_retraction(self):
        old = self.corrections / ("2026-01-01-retraction-for-" + "very-long-question-" * 8 + "é.md")
        payload = "# Retraction for a very long question\n\nSynthetic reason only.\n"
        old.write_text(
            "---\n"
            'title: "Retraction for a synthetic traversal-like ../../ question"\n'
            'type: "source_retraction"\n'
            'source_id: "retraction:legacy-long-name"\n'
            'captured_at: "2026-01-01T00:00:00Z"\n'
            'source_path: "sources/corrections/placeholder.md"\n'
            'retracts: "answer:A1"\n'
            'retracts_path: "answers/A1.md"\n'
            "---\n\n" + payload,
            encoding="utf-8",
        )
        old_rel = self.src.rel(old)
        text = old.read_text(encoding="utf-8").replace("placeholder.md", old.name)
        old.write_text(text, encoding="utf-8")
        return old, old_rel

    def _patch_classifier_root(self):
        import classify_story

        original = (classify_story.REPO_DIR, classify_story.CLASSIFICATIONS_DIR)
        classify_story.REPO_DIR = self.root
        classify_story.CLASSIFICATIONS_DIR = self.root / "state" / "classifications"
        return classify_story, original

    def test_repair_is_dry_run_idempotent_and_updates_indexes(self):
        old, old_rel = self._legacy_retraction()
        target_before = self.target.read_text(encoding="utf-8")
        self.src.SOURCE_MANIFEST_FILE.parent.mkdir(parents=True)
        self.src.SOURCE_MANIFEST_FILE.write_text(
            json.dumps({"version": 1, "sources": {old_rel: {"source_id": "retraction:legacy-long-name"}}}),
            encoding="utf-8",
        )
        placements = self.root / "state" / "timeline_placements.json"
        placements.write_text(json.dumps({"pins": [{"correction": old_rel}]}), encoding="utf-8")
        wiki = self.root / "wiki" / "index.md"
        wiki.parent.mkdir(parents=True)
        wiki.write_text(f"---\nsources:\n  - {old_rel}\n---\n\n{old_rel}\n", encoding="utf-8")
        report = self.root / "state" / "reports" / "weekly.md"
        report.parent.mkdir(parents=True)
        report.write_text(f"Generated reference: {old_rel}\n", encoding="utf-8")
        classifier, classifier_original = self._patch_classifier_root()
        try:
            old_classification = classifier.classification_path(old)
            old_classification.parent.mkdir(parents=True)
            old_classification.write_text(json.dumps({"source_path": old_rel}), encoding="utf-8")
            preview = self.src.repair_linked_source_filenames(dry_run=True)
            self.assertEqual(len(preview), 1)
            self.assertTrue(old.exists())
            repaired = self.src.repair_linked_source_filenames()
            self.assertEqual(preview, repaired)
            new = self.root / repaired[0][1]
            self.assertFalse(old.exists())
            self.assertTrue(new.exists())
            self.assertLessEqual(len(new.name), self.src.MAX_LINKED_SOURCE_FILENAME_BYTES)
            metadata, _payload = self.src.split_frontmatter(new.read_text(encoding="utf-8"))
            self.assertEqual(metadata["source_path"], repaired[0][1])
            self.assertEqual(metadata["source_id"], "retraction:legacy-long-name")
            manifest = json.loads(self.src.SOURCE_MANIFEST_FILE.read_text(encoding="utf-8"))
            self.assertIn(repaired[0][1], manifest["sources"])
            self.assertNotIn(old_rel, manifest["sources"])
            self.assertEqual(json.loads(placements.read_text(encoding="utf-8"))["pins"][0]["correction"], repaired[0][1])
            self.assertNotIn(old_rel, wiki.read_text(encoding="utf-8"))
            self.assertIn(repaired[0][1], wiki.read_text(encoding="utf-8"))
            self.assertIn(repaired[0][1], report.read_text(encoding="utf-8"))
            new_classification = classifier.classification_path(new)
            self.assertTrue(new_classification.exists())
            self.assertFalse(old_classification.exists())
            self.assertEqual(json.loads(new_classification.read_text(encoding="utf-8"))["source_path"], repaired[0][1])
            self.assertEqual(self.target.read_text(encoding="utf-8"), target_before)
            self.assertEqual(self.src.repair_linked_source_filenames(), [])
        finally:
            classifier.REPO_DIR, classifier.CLASSIFICATIONS_DIR = classifier_original

    def test_repair_rolls_back_if_a_state_write_fails(self):
        old, old_rel = self._legacy_retraction()
        state = self.root / "state" / "timeline_placements.json"
        state.parent.mkdir(parents=True)
        original_state = json.dumps({"pins": [{"correction": old_rel}]})
        state.write_text(original_state, encoding="utf-8")
        original_source = old.read_text(encoding="utf-8")
        classifier, classifier_original = self._patch_classifier_root()
        try:
            with mock.patch.object(self.src, "write_json", side_effect=OSError("synthetic disk failure")):
                with self.assertRaises(OSError):
                    self.src.repair_linked_source_filenames()
        finally:
            classifier.REPO_DIR, classifier.CLASSIFICATIONS_DIR = classifier_original
        self.assertTrue(old.exists())
        self.assertEqual(old.read_text(encoding="utf-8"), original_source)
        self.assertEqual(state.read_text(encoding="utf-8"), original_state)
        self.assertEqual(len(list(self.corrections.glob("*.md"))), 1)

    def test_repair_refuses_symlinked_source_or_corrections_directory(self):
        old, _old_rel = self._legacy_retraction()
        external = self.root / "external.md"
        external.write_text("do not follow", encoding="utf-8")
        old.unlink()
        old.symlink_to(external)
        with self.assertRaisesRegex(ValueError, "symlinked correction/retraction source"):
            self.src.repair_linked_source_filenames()
        self.assertEqual(external.read_text(encoding="utf-8"), "do not follow")

        old.unlink()
        self.corrections.rmdir()
        external_dir = self.root / "external-corrections"
        external_dir.mkdir()
        self.corrections.symlink_to(external_dir, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, "symlinked corrections directory"):
            self.src.repair_linked_source_filenames()


if __name__ == "__main__":
    unittest.main()
