"""v181 / ADR 0018 — registered Interaction composition and audit."""

from __future__ import annotations

import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SYSTEM = ROOT / "system"
sys.path.insert(0, str(SYSTEM))

import interaction_registry as registry  # noqa: E402


class RegistryContractTests(unittest.TestCase):
    def test_closed_registry_is_exact_and_all_packages_audit(self):
        value = registry.load_interaction_registry()
        self.assertEqual(value["schema_version"], 1)
        self.assertEqual(
            [(row["id"], row["package"]) for row in value["interactions"]],
            [
                ("conversation", "conversation"),
                ("focus_curation", "focus_curation"),
                ("question_judgment", "question_judgment"),
                ("question_candidate", "question_candidate"),
                ("focus_candidate", "focus_candidate"),
                ("entity_candidate", "entity_candidate"),
                ("arc_walk", "arc_walk"),
                ("timeline", "timeline"),
            ],
        )
        for entry in value["interactions"]:
            with self.subTest(entry=entry["id"]):
                self.assertEqual(registry.audit_interaction_package(entry["id"]), [])

    def test_question_candidate_has_distinct_identity_and_parent_lineage(self):
        self.assertEqual(
            registry.resolve_interaction_lineage("question_candidate"),
            ("conversation", "question_candidate"),
        )
        self.assertEqual(
            registry.resolve_interaction_lineage("conversation"), ("conversation",)
        )
        manifest = registry.load_interaction_manifest("question_candidate")
        self.assertEqual(manifest["interaction"], "question_candidate")
        self.assertEqual(manifest["version"], "1.0.0")
        self.assertEqual(manifest["extends"], "conversation")
        self.assertEqual(manifest["extends.version"], "1.0.0")

    def test_focus_candidate_has_distinct_identity_and_parent_lineage(self):
        self.assertEqual(
            registry.resolve_interaction_lineage("focus_candidate"),
            ("conversation", "focus_candidate"),
        )
        manifest = registry.load_interaction_manifest("focus_candidate")
        self.assertEqual(manifest["interaction"], "focus_candidate")
        self.assertEqual(manifest["version"], "1.0.0")
        self.assertEqual(manifest["extends"], "conversation")
        self.assertEqual(manifest["extends.version"], "1.0.0")

    def test_entity_candidate_has_distinct_identity_and_parent_lineage(self):
        self.assertEqual(
            registry.resolve_interaction_lineage("entity_candidate"),
            ("conversation", "entity_candidate"),
        )
        manifest = registry.load_interaction_manifest("entity_candidate")
        self.assertEqual(manifest["interaction"], "entity_candidate")
        self.assertEqual(manifest["version"], "1.0.0")
        self.assertEqual(manifest["extends.version"], "1.0.0")

    def test_focus_candidate_composition_preserves_exact_parent_and_child_bytes(self):
        composed = registry.compose_interaction_asset(
            "focus_candidate", "prompt/behavior.md"
        )
        parent = (ROOT / "interactions/conversation/prompt/behavior.md").read_text()
        child = (ROOT / "interactions/focus_candidate/prompt/behavior.md").read_text()
        self.assertEqual(
            composed,
            "<!-- interaction:conversation asset:prompt/behavior.md -->\n"
            + parent
            + "\n<!-- interaction:focus_candidate asset:prompt/behavior.md -->\n"
            + child,
        )

    def test_existing_interaction_assets_are_absent_from_focus_candidate_package(self):
        child_files = {
            path.relative_to(ROOT / "interactions/focus_candidate").as_posix()
            for path in (ROOT / "interactions/focus_candidate").rglob("*")
            if path.is_file()
        }
        self.assertNotIn("conversation.py", child_files)
        self.assertNotIn("question_candidate.py", child_files)
        self.assertNotIn("entity_candidate.py", child_files)

    def test_append_composition_reads_parent_then_child_with_provenance(self):
        composed = registry.compose_interaction_asset(
            "question_candidate", "prompt/behavior.md"
        )
        parent = (ROOT / "interactions/conversation/prompt/behavior.md").read_text()
        child = (
            ROOT / "interactions/question_candidate/prompt/behavior.md"
        ).read_text()
        self.assertEqual(
            composed,
            "<!-- interaction:conversation asset:prompt/behavior.md -->\n"
            + parent
            + "\n<!-- interaction:question_candidate asset:prompt/behavior.md -->\n"
            + child,
        )

    def test_leaf_composition_uses_only_child_authority(self):
        composed = registry.compose_interaction_asset(
            "question_candidate", "prompt/turn-instructions.md"
        )
        self.assertIn("interaction:question_candidate", composed)
        self.assertNotIn("interaction:conversation", composed)
        self.assertNotIn("Arc card intent", composed)

    def test_child_does_not_copy_parent_behavior_or_identity_files(self):
        child = ROOT / "interactions/question_candidate"
        parent = ROOT / "interactions/conversation"
        for relative in (
            "prompt/identity.md",
            "prompt/behavior.md",
            "prompt/examples.md",
        ):
            with self.subTest(relative=relative):
                self.assertNotEqual(
                    (child / relative).read_bytes(), (parent / relative).read_bytes()
                )
        self.assertNotIn(
            "# Behavior contract — Conversation",
            (child / "prompt/behavior.md").read_text(),
        )

    def test_only_child_runtime_imports_parent_lint_engine(self):
        offenders = []
        for path in sorted(SYSTEM.glob("question_candidate*.py")):
            if "import conversation_lints" in path.read_text():
                offenders.append(path.name)
        self.assertEqual(offenders, ["question_candidate.py"])

    def test_only_focus_child_runtime_imports_parent_lint_engine(self):
        offenders = []
        for path in sorted(SYSTEM.glob("focus_candidate*.py")):
            if "import conversation_lints" in path.read_text():
                offenders.append(path.name)
        self.assertEqual(offenders, ["focus_candidate.py"])

    def test_undeclared_and_traversal_assets_fail_closed(self):
        with self.assertRaises(registry.InteractionRegistryError):
            registry.compose_interaction_asset("question_candidate", "README.md")
        with self.assertRaises(registry.InteractionRegistryError):
            registry.compose_interaction_asset("question_candidate", "../version.json")

    def test_direct_composition_rejects_manifest_declared_noncomposable_asset(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            shutil.copytree(ROOT / "interactions", root / "interactions")
            manifest = root / "interactions/question_candidate/interaction.yaml"
            manifest.write_text(
                manifest.read_text().replace(
                    "composition.leaf: prompt/turn-instructions.md|context/manifest.md",
                    "composition.leaf: prompt/turn-instructions.md|context/manifest.md|README.md",
                )
            )
            with self.assertRaises(registry.InteractionRegistryError):
                registry.compose_interaction_asset(
                    "question_candidate", "README.md", framework_root=root
                )
            self.assertTrue(
                registry.audit_interaction_package(
                    "question_candidate", framework_root=root
                )
            )

    def test_composition_preserves_trailing_spaces_tabs_and_newlines(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            shutil.copytree(ROOT / "interactions", root / "interactions")
            parent = "parent line  \nparent tail\t"
            child = "child line \t\n\n"
            (root / "interactions/conversation/prompt/behavior.md").write_bytes(
                parent.encode("utf-8")
            )
            (root / "interactions/question_candidate/prompt/behavior.md").write_bytes(
                child.encode("utf-8")
            )
            self.assertEqual(
                registry.compose_interaction_asset(
                    "question_candidate",
                    "prompt/behavior.md",
                    framework_root=root,
                ),
                "<!-- interaction:conversation asset:prompt/behavior.md -->\n"
                + parent
                + "\n<!-- interaction:question_candidate asset:prompt/behavior.md -->\n"
                + child,
            )

    def test_unregistered_package_is_not_executable(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            shutil.copytree(ROOT / "interactions", root / "interactions")
            shutil.copytree(
                root / "interactions/question_candidate",
                root / "interactions/rogue_candidate",
            )
            with self.assertRaises(registry.InteractionRegistryError):
                registry.load_interaction_manifest(
                    "rogue_candidate", framework_root=root
                )

    def test_parent_version_mismatch_and_cycle_fail_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            shutil.copytree(ROOT / "interactions", root / "interactions")
            manifest = root / "interactions/question_candidate/interaction.yaml"
            manifest.write_text(
                manifest.read_text().replace(
                    "extends.version: 1.0.0", "extends.version: 9.9.9"
                )
            )
            with self.assertRaises(registry.InteractionRegistryError):
                registry.resolve_interaction_lineage(
                    "question_candidate", framework_root=root
                )

            manifest.write_text(
                manifest.read_text().replace(
                    "extends.version: 9.9.9", "extends.version: 1.0.0"
                )
            )
            parent = root / "interactions/conversation/interaction.yaml"
            parent.write_text(
                parent.read_text()
                + "\nextends: question_candidate\nextends.version: 1.0.0\n"
            )
            with self.assertRaises(registry.InteractionRegistryError):
                registry.resolve_interaction_lineage(
                    "question_candidate", framework_root=root
                )


if __name__ == "__main__":
    unittest.main()
