import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SYSTEM = ROOT / "system"
sys.path.insert(0, str(SYSTEM))

import lifehug_core


def load(name):
    spec = importlib.util.spec_from_file_location(name, SYSTEM / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


class SourceIntegrityTests(unittest.TestCase):
    def setUp(self):
        self.src = load("source_integrity")

    def test_metadata_fix_preserves_body_and_adds_hash(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "memory.md"
            original = "# Memory\n\nThis is the captured story.\n"
            path.write_text(original)

            self.src.apply_metadata_fix(path)
            metadata, body = lifehug_core.split_frontmatter(path.read_text())

            self.assertEqual(body, original)
            self.assertTrue(metadata["immutable"])
            self.assertEqual(metadata["status"], "raw")
            self.assertEqual(metadata["content_sha256"], self.src.payload_sha256(original))

    def test_lint_detects_declared_hash_mismatch(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "memory.md"
            metadata = {
                "title": "Memory",
                "type": "unprompted_story",
                "source_id": "manual:memory",
                "captured_at": "2026-01-01T00:00:00Z",
                "visibility": "owner_only",
                "status": "raw",
                "immutable": True,
                "schema_version": 1,
                "source_path": self.src.rel(path),
                "content_sha256": "not-the-real-hash",
            }
            path.write_text(f"{self.src.format_frontmatter(metadata)}\n\n# Memory\n\nChanged body.\n")

            findings = self.src.lint_records([self.src.source_record(path)])
            self.assertIn("content_hash_mismatch", {finding["type"] for finding in findings})

    def test_correction_metadata_links_to_target_source_id(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "memory.md"
            path.write_text("# Memory\n\nThis is the captured story.\n")
            self.src.apply_metadata_fix(path)

            record = self.src.source_record(path)
            self.assertEqual(record["source_id"], "source:memory")
            self.assertEqual(record["type"], "source")


if __name__ == "__main__":
    unittest.main()
