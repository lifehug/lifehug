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
    """Load a private copy of system/<name>.py WITHOUT clobbering the shared
    sys.modules entry — other test modules bind the canonical module at import
    time, and replacing it mid-suite splits state across two module objects."""
    spec = importlib.util.spec_from_file_location(name, SYSTEM / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    orig = sys.modules.get(name)
    sys.modules[name] = mod
    try:
        spec.loader.exec_module(mod)
    finally:
        if orig is not None:
            sys.modules[name] = orig
        else:
            sys.modules.pop(name, None)
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

    def test_findings_change_detection_ignores_timestamp_only(self):
        finding = self.src.finding(
            "manifest_missing",
            "warning",
            "answers/A1.md",
            "source is not registered",
            fixability="safe",
            recommended_action="run source-lint --fix",
        )
        existing = self.src.findings_payload([finding], updated_at="2026-01-01T00:00:00Z")

        self.assertFalse(self.src.findings_changed(existing, [finding]))
        self.assertTrue(self.src.findings_changed(existing, []))


class EntityPageLintTests(unittest.TestCase):
    """entity_page_not_in_roster + duplicate_entity_suspect lint rules."""

    def setUp(self):
        self.src = load("source_integrity")
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.original_paths = (
            self.src.REPO_DIR,
            self.src.WIKI_DIR,
            self.src.ENTITY_ROSTERS_DIR,
        )
        self.src.REPO_DIR = self.root
        self.src.WIKI_DIR = self.root / "wiki"
        self.src.ENTITY_ROSTERS_DIR = self.root / "state" / "entity_rosters"
        (self.root / "wiki" / "people").mkdir(parents=True)
        (self.root / "state" / "entity_rosters").mkdir(parents=True)

    def tearDown(self):
        (
            self.src.REPO_DIR,
            self.src.WIKI_DIR,
            self.src.ENTITY_ROSTERS_DIR,
        ) = self.original_paths
        self.tmp.cleanup()

    def write_page(self, slug, sources, origin="mention"):
        body = ("---\n"
                f'title: "{slug.title()}"\n'
                "type: person\n"
                f"origin: {origin}\n"
                "sources:\n" +
                "".join(f'  - "{s}"\n' for s in sources) +
                "---\n\nBody.\n")
        (self.root / "wiki" / "people" / f"{slug}.md").write_text(body, encoding="utf-8")

    def write_roster(self, entities):
        import json
        payload = {"version": 1, "type": "person", "entities": entities}
        (self.root / "state" / "entity_rosters" / "person.json").write_text(
            json.dumps(payload), encoding="utf-8")

    def lint_types(self):
        return {f["type"] for f in self.src.lint_records([])}

    def test_page_missing_from_roster_flagged(self):
        self.write_roster([{"name": "Trevor", "slug": "trevor", "aliases": []}])
        self.write_page("betty-jo", ["answers/C2.md", "answers/A12.md"])
        self.assertIn("entity_page_not_in_roster", self.lint_types())

    def test_alias_slug_match_is_clean(self):
        self.write_roster([{"name": "Grandma Betty Jo", "slug": "grandma-betty-jo",
                            "aliases": ["Betty Jo"]}])
        self.write_page("betty-jo", ["answers/C2.md", "answers/A12.md"])
        self.assertNotIn("entity_page_not_in_roster", self.lint_types())

    def test_no_roster_no_finding(self):
        self.write_page("betty-jo", ["answers/C2.md", "answers/A12.md"])
        self.assertNotIn("entity_page_not_in_roster", self.lint_types())

    def test_subset_sources_flagged_once_on_smaller_page(self):
        # The Betty Jo shape: split page's sources ⊂ the full page's sources.
        self.write_roster([{"name": "Grandma", "slug": "grandma", "aliases": []},
                           {"name": "Betty Jo", "slug": "betty-jo", "aliases": []}])
        full = [f"answers/A{i}.md" for i in range(8)]
        self.write_page("grandma", full)
        self.write_page("betty-jo", full[:3])
        findings = [f for f in self.src.lint_records([]) if f["type"] == "duplicate_entity_suspect"]
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0]["path"], "wiki/people/betty-jo.md")

    def test_low_jaccard_overlap_is_clean(self):
        self.write_roster([{"name": "A", "slug": "a", "aliases": []},
                           {"name": "B", "slug": "b", "aliases": []}])
        self.write_page("a", ["answers/A1.md", "answers/A2.md", "answers/A3.md", "answers/A4.md"])
        self.write_page("b", ["answers/A1.md", "answers/A2.md", "answers/B3.md", "answers/B4.md"])
        self.assertNotIn("duplicate_entity_suspect", self.lint_types())

    def test_two_focus_pages_overlapping_is_clean(self):
        self.write_roster([{"name": "Katie", "slug": "katie", "aliases": []},
                           {"name": "Mom", "slug": "mom", "aliases": []}])
        full = [f"answers/A{i}.md" for i in range(4)]
        self.write_page("katie", full, origin="focus")
        self.write_page("mom", full[:2], origin="focus")
        self.assertNotIn("duplicate_entity_suspect", self.lint_types())


class CandidateResearchIntegrityTests(unittest.TestCase):
    def setUp(self):
        self.src = load("source_integrity")
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.original_paths = (
            self.src.REPO_DIR,
            self.src.ANSWERS_DIR,
            self.src.SOURCES_DIR,
            self.src.SOURCE_MANIFEST_FILE,
            self.src.WIKI_DIR,
        )
        self.src.REPO_DIR = self.root
        self.src.ANSWERS_DIR = self.root / "answers"
        self.src.SOURCES_DIR = self.root / "sources"
        self.src.SOURCE_MANIFEST_FILE = self.root / "state" / "source_manifest.json"
        self.src.WIKI_DIR = self.root / "wiki"

    def tearDown(self):
        (
            self.src.REPO_DIR,
            self.src.ANSWERS_DIR,
            self.src.SOURCES_DIR,
            self.src.SOURCE_MANIFEST_FILE,
            self.src.WIKI_DIR,
        ) = self.original_paths
        self.tmp.cleanup()

    def _record_and_manifest(self):
        import candidate_research

        from tests.test_candidate_research import _focus_assessment

        subject, turns, assessment = _focus_assessment(confirmed=True)
        plan = candidate_research.build_candidate_research_source(
            assessment, authoritative_turns=turns, current_subject=subject
        )
        path = self.root / plan["source_path"]
        path.parent.mkdir(parents=True)
        path.write_bytes(plan["source_bytes"])
        record = self.src.source_record(path)
        manifest = self.src.sync_manifest([record], write=False)
        self.src.SOURCE_MANIFEST_FILE.parent.mkdir(parents=True)
        self.src.SOURCE_MANIFEST_FILE.write_text(json.dumps(manifest), encoding="utf-8")
        return path, record, manifest

    def test_typed_fields_survive_manifest_and_lint_cleanly(self):
        _path, record, manifest = self._record_and_manifest()
        entry = manifest["sources"][record["path"]]
        self.assertEqual(entry["candidate_kind"], "focus_candidate")
        self.assertEqual(entry["subject_type"], "place")
        self.assertTrue(entry["user_confirmed"])
        self.assertFalse(entry["generated_seed_questions_evidence"])
        findings = self.src.lint_records([record])
        self.assertNotIn(
            "candidate_research_invalid", {finding["type"] for finding in findings}
        )
        self.assertNotIn(
            "candidate_research_manifest_mismatch",
            {finding["type"] for finding in findings},
        )

    def test_typed_manifest_mismatch_is_safe_manifest_repair(self):
        _path, record, manifest = self._record_and_manifest()
        manifest["sources"][record["path"]]["research_revision"] = "sha256:" + "0" * 64
        self.src.SOURCE_MANIFEST_FILE.write_text(json.dumps(manifest), encoding="utf-8")
        findings = self.src.lint_records([record])
        finding = next(
            item
            for item in findings
            if item["type"] == "candidate_research_manifest_mismatch"
        )
        self.assertEqual(finding["fixability"], "safe")

    def test_invalid_immutable_source_is_never_rewritten_by_safe_fix(self):
        path, _record, _manifest = self._record_and_manifest()
        tampered = path.read_text(encoding="utf-8").replace(
            "Only the literal user-turn excerpts", "Tampered user-turn excerpts", 1
        )
        path.write_text(tampered, encoding="utf-8")
        before = path.read_bytes()
        record = self.src.source_record(path)
        self.assertTrue(record["candidate_research_error"])
        self.src.apply_safe_fixes([record])
        self.assertEqual(path.read_bytes(), before)

    def test_candidate_research_invalid_utf8_fails_closed_without_rewrite(self):
        path, _record, _manifest = self._record_and_manifest()
        path.write_bytes(path.read_bytes() + b"\xff")
        before = path.read_bytes()
        record = self.src.source_record(path)
        self.assertEqual(record["type"], "candidate_research")
        self.assertIn("not strict UTF-8", record["candidate_research_error"])
        findings = self.src.lint_records([record])
        self.assertIn(
            "candidate_research_invalid", {item["type"] for item in findings}
        )
        self.src.apply_safe_fixes([record])
        self.assertEqual(path.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
