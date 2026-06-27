import argparse
import importlib.util
import json
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


class ArtifactWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.artifact = load("artifact")
        self.wiki = load("wiki_compile")

    def test_promote_source_writes_authored_artifact_metadata(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            out_dir = root / "outputs" / "mothers-day"
            out_dir.mkdir(parents=True)
            (out_dir / "context.md").write_text("# Artifact Context\n\nSource material.\n")
            (out_dir / "v1.md").write_text("Dear Mom,\n\nThank you.\n")
            data = {
                "version": 1,
                "artifact_id": "mothers-day",
                "title": "Mother's Day",
                "format": "letter",
                "subject": "Mom",
                "occasion": "Mother's Day",
                "occasion_date": "2026-05-10",
                "audience": "family",
                "privacy": "owner_only",
                "context_path": "outputs/mothers-day/context.md",
                "context_sources": ["answers/K1.md"],
                "versions": [{"version": 1, "path": "outputs/mothers-day/v1.md"}],
                "final_version": 1,
                "promoted_sources": [],
            }
            (out_dir / "artifact.json").write_text(json.dumps(data))

            self.artifact.REPO_DIR = root
            self.artifact.OUTPUTS_DIR = root / "outputs"
            self.artifact.ARTIFACT_SOURCES_DIR = root / "sources" / "artifacts"
            self.artifact.register_source = lambda _path: {}

            args = argparse.Namespace(output="mothers-day", kind="final", version="final", source="test")
            self.assertEqual(self.artifact.cmd_promote_source(args), 0)

            created = list((root / "sources" / "artifacts").glob("*.md"))
            self.assertEqual(len(created), 1)
            metadata, body = lifehug_core.split_frontmatter(created[0].read_text())
            self.assertEqual(metadata["type"], "authored_artifact")
            self.assertEqual(metadata["source_trust"], "authored_expression")
            self.assertEqual(metadata["authority"], "first_person_expression")
            self.assertEqual(metadata["generated_from"], ["answers/K1.md"])
            self.assertEqual(metadata["output_version"], "v1")
            self.assertIn("Dear Mom", body)

    def test_wiki_splits_derived_sources_into_supporting_bucket(self):
        primary = {
            "id": "manual:story",
            "kind": "unprompted_story",
            "source_trust": "",
            "body": "family",
            "source": "sources/manual/story.md",
        }
        derived = {
            "id": "artifact:mom:v1",
            "kind": "authored_artifact",
            "source_trust": "authored_expression",
            "body": "family",
            "source": "sources/artifacts/mom.md",
        }

        primary_items, supporting_items = self.wiki.split_primary_supporting([primary, derived])

        self.assertEqual(primary_items, [primary])
        self.assertEqual(supporting_items, [derived])
        self.assertTrue(self.wiki.is_derived_source(derived))


if __name__ == "__main__":
    unittest.main()
