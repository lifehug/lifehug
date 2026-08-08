"""v125: format framework registry (system/format_frameworks.py).

Two suites:

* ``FrameworkRegistryTests`` exercises the REAL ``templates/*.json`` specs.
  These fail until the spec files land (a parallel agent authors them) —
  that's expected while this PR's pieces are still landing.
* ``FrameworkLoaderUnitTests`` exercises the loader/validator in isolation
  against a synthetic ``templates/`` directory, independent of whether the
  real spec files exist yet.
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

import book  # noqa: E402
import compose  # noqa: E402
import format_frameworks  # noqa: E402
import jobs  # noqa: E402
import lifehug_core  # noqa: E402

EXPECTED_VALID_FORMATS = (
    "letter", "tweet", "instagram", "chapter", "post", "essay",
    "unsent_letter", "legacy_letter",
)


def _valid_spec(fid: str, **overrides) -> dict:
    """A minimal, schema-valid framework spec dict for ``fid``."""
    spec = {
        "id": fid,
        "label": fid.replace("_", " ").title(),
        "kind": "single",
        "summary": f"Summary for {fid}.",
        "template": f"templates/{fid}.md",
        "subject_kind": "person",
        "composable": True,
        "length": {"min_words": 100, "max_words": 500},
        "slots": [],
        "thresholds": {"ready": book.READY, "developing": book.DEVELOPING},
        "research": {"basis": "Test basis.", "citations": []},
        "ai_context": [],
    }
    spec.update(overrides)
    return spec


class FrameworkRegistryTests(unittest.TestCase):
    """Against the real templates/*.json specs."""

    def setUp(self):
        format_frameworks._CACHE = None

    def tearDown(self):
        format_frameworks._CACHE = None

    def _load(self):
        return format_frameworks.load_frameworks(refresh=True)

    def test_every_spec_file_parses_and_validates(self):
        frameworks = self._load()
        json_files = sorted(format_frameworks.TEMPLATES_DIR.glob("*.json"))
        self.assertTrue(json_files, "expected templates/*.json spec files to exist")
        self.assertEqual(set(frameworks), {p.stem for p in json_files})

    def test_every_template_file_exists(self):
        frameworks = self._load()
        for fid, spec in frameworks.items():
            with self.subTest(format=fid):
                template_path = format_frameworks.FRAMEWORK_ROOT / spec["template"]
                self.assertTrue(
                    template_path.exists(),
                    f"{fid}: template path {spec['template']} does not exist",
                )

    def test_every_slot_story_function_is_known(self):
        frameworks = self._load()
        for fid, spec in frameworks.items():
            for slot in spec.get("slots", []):
                for func in slot["story_functions"]:
                    with self.subTest(format=fid, slot=slot["id"], function=func):
                        self.assertIn(func, lifehug_core.STORY_FUNCTIONS)

    def test_thresholds_are_ordered(self):
        frameworks = self._load()
        for fid, spec in frameworks.items():
            with self.subTest(format=fid):
                ready = spec["thresholds"]["ready"]
                developing = spec["thresholds"]["developing"]
                self.assertGreater(developing, 0)
                self.assertLess(developing, ready)
                self.assertLessEqual(ready, 1)

    def test_default_thresholds_match_book_module(self):
        frameworks = self._load()
        for fid, spec in frameworks.items():
            with self.subTest(format=fid):
                self.assertEqual(spec["thresholds"]["ready"], book.READY)
                self.assertEqual(spec["thresholds"]["developing"], book.DEVELOPING)

    def test_valid_formats_pinned_order(self):
        self.assertEqual(format_frameworks.valid_formats(), EXPECTED_VALID_FORMATS)

    def test_compose_valid_formats_matches_registry(self):
        self.assertEqual(compose.VALID_FORMATS, format_frameworks.valid_formats())

    def test_book_framework_shape(self):
        frameworks = self._load()
        self.assertIn("book", frameworks)
        book_spec = frameworks["book"]
        self.assertEqual(book_spec["kind"], "composite")
        self.assertFalse(book_spec["composable"])
        self.assertEqual(
            book_spec.get("deliverables"),
            ["book", "chapter", "memoir", "manuscript"],
        )

    def test_build_artifact_new_accepts_every_valid_format(self):
        for fmt in format_frameworks.valid_formats():
            with self.subTest(format=fmt):
                invocations = jobs._build_artifact_new({"format": fmt, "subject": "X"})
                self.assertTrue(invocations)

    def test_build_artifact_new_rejects_unknown_format(self):
        with self.assertRaises(ValueError):
            jobs._build_artifact_new({"format": "nonexistent", "subject": "X"})


class FrameworkLoaderUnitTests(unittest.TestCase):
    """Against a synthetic templates/ directory."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(dir=ROOT.parent))
        self.templates_dir = self.tmp / "templates"
        self.templates_dir.mkdir(parents=True)
        self._saved = {
            "TEMPLATES_DIR": format_frameworks.TEMPLATES_DIR,
            "FRAMEWORK_ROOT": format_frameworks.FRAMEWORK_ROOT,
            "_CACHE": format_frameworks._CACHE,
        }
        format_frameworks.TEMPLATES_DIR = self.templates_dir
        format_frameworks.FRAMEWORK_ROOT = self.tmp
        format_frameworks._CACHE = None

    def tearDown(self):
        format_frameworks.TEMPLATES_DIR = self._saved["TEMPLATES_DIR"]
        format_frameworks.FRAMEWORK_ROOT = self._saved["FRAMEWORK_ROOT"]
        format_frameworks._CACHE = self._saved["_CACHE"]

    def _write(self, fid: str, spec: dict) -> None:
        (self.templates_dir / f"{fid}.md").write_text("template body\n")
        (self.templates_dir / f"{fid}.json").write_text(json.dumps(spec))

    def test_valid_spec_loads(self):
        self._write("mock_format", _valid_spec("mock_format"))
        frameworks = format_frameworks.load_frameworks(refresh=True)
        self.assertIn("mock_format", frameworks)
        self.assertEqual(format_frameworks.get("mock_format")["id"], "mock_format")

    def test_missing_required_key_raises_naming_file(self):
        spec = _valid_spec("mock_format")
        del spec["label"]
        self._write("mock_format", spec)
        with self.assertRaises(ValueError) as cm:
            format_frameworks.load_frameworks(refresh=True)
        self.assertIn("mock_format.json", str(cm.exception))
        self.assertIn("label", str(cm.exception))

    def test_bad_story_function_raises(self):
        spec = _valid_spec("mock_format", slots=[{
            "id": "s1",
            "label": "Slot One",
            "description": "A slot.",
            "story_functions": ["not_a_real_story_function"],
            "min_answers": 1,
        }])
        self._write("mock_format", spec)
        with self.assertRaises(ValueError) as cm:
            format_frameworks.load_frameworks(refresh=True)
        self.assertIn("mock_format.json", str(cm.exception))

    def test_developing_gte_ready_raises(self):
        spec = _valid_spec("mock_format", thresholds={"ready": 0.5, "developing": 0.5})
        self._write("mock_format", spec)
        with self.assertRaises(ValueError):
            format_frameworks.load_frameworks(refresh=True)

    def test_min_answers_zero_raises(self):
        spec = _valid_spec("mock_format", slots=[{
            "id": "s1",
            "label": "Slot One",
            "description": "A slot.",
            "story_functions": ["scene"],
            "min_answers": 0,
        }])
        self._write("mock_format", spec)
        with self.assertRaises(ValueError):
            format_frameworks.load_frameworks(refresh=True)

    def test_missing_templates_dir_falls_back_to_canonical_order(self):
        # Empty templates/ dir (no *.json specs at all): simulates an old
        # vault mid-update, before v125 spec files land.
        self.assertEqual(
            format_frameworks.valid_formats(),
            format_frameworks.CANONICAL_ORDER,
        )


if __name__ == "__main__":
    unittest.main()
