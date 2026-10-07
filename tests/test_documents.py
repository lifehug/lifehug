"""lifehug#471 PR 1: letters filed as immutable `type: letter` records.

The fixture under tests/fixtures/letters_repo is a synthetic letters
repository (people.yaml with collection-scoped aliases, a first-person letter,
a split letter in two parts, an undated part, month and year precision). Each
test copies it into a fresh git repository so the writer reads it the way it
reads the real one: through git, at a pinned commit.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SYSTEM = ROOT / "system"
FIXTURE = ROOT / "tests" / "fixtures" / "letters_repo"
sys.path.insert(0, str(SYSTEM))
sys.path.insert(0, str(ROOT / "tests"))

import documents  # noqa: E402
import mini_yaml  # noqa: E402
from tempdirs import root_parent_tmp  # noqa: E402

SCAN_TEMPLATE = "https://letters.example/letters/{id}/scan.pdf"
MAPS = ["--map", "pat-owner=self", "--map", "sam-owner=person/dad", "--map", "lee-owner=person/mom"]
GIT_ENV = {
    "GIT_AUTHOR_NAME": "Fixture", "GIT_AUTHOR_EMAIL": "fixture@example.invalid",
    "GIT_COMMITTER_NAME": "Fixture", "GIT_COMMITTER_EMAIL": "fixture@example.invalid",
    "GIT_CONFIG_NOSYSTEM": "1",
}


def _git(repo: Path, *args: str) -> str:
    env = {**os.environ, **GIT_ENV, "HOME": str(repo)}
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True,
                          text=True, env=env).stdout.strip()


class MiniYamlTests(unittest.TestCase):
    def test_reads_safe_dump_shapes(self):
        text = (
            "id: a/b\n"
            "date: '1984-03-05'\n"
            "date_evidence: 'It says ''Mar 5,'' and\n  nothing more.\n\n  New paragraph.'\n"
            "people:\n- Desi\n- 'Your mom (unnamed)'\n"
            "addresses: []\n"
            "page_confidence:\n  scan_page_1: 0.85\n"
            "fragment: false\n"
            "pages_scanned: 3\n"
            "date_null: null\n"
            "plain: a plain value\n  continued here\n"
            'quoted: "tab\\tand \\u00e9 and \\"q\\"\\\n  joined"\n'
        )
        self.assertEqual(mini_yaml.loads(text), {
            "id": "a/b",
            "date": "1984-03-05",
            "date_evidence": "It says 'Mar 5,' and nothing more.\nNew paragraph.",
            "people": ["Desi", "Your mom (unnamed)"],
            "addresses": [],
            "page_confidence": {"scan_page_1": 0.85},
            "fragment": False,
            "pages_scanned": 3,
            "date_null": None,
            "plain": "a plain value continued here",
            "quoted": 'tab\tand é and "q"joined',
        })

    def test_reads_hand_written_people_yaml_shapes(self):
        text = (
            "# comment\n"
            "people:\n"
            "  - id: x  # trailing comment\n"
            "    aliases:\n"
            '      - "Jim Taylor(?!,? Sr)"\n'
            '      - {p: "\\\\bDad\\\\b", in: [jim-mission-nz, memory-box-1974]}\n'
            '    other: ["Mortz?feld", "Morefield", "[^)]x"]\n'
        )
        self.assertEqual(mini_yaml.loads(text), {"people": [{
            "id": "x",
            "aliases": ["Jim Taylor(?!,? Sr)", {"p": "\\bDad\\b", "in": ["jim-mission-nz", "memory-box-1974"]}],
            "other": ["Mortz?feld", "Morefield", "[^)]x"],
        }]})

    def test_refuses_what_it_cannot_read_exactly(self):
        for text in ("a: &x 1\nb: *x\n", "a: |\n  block\n", "a: !!str 1\n", "a:\n\t- tab\n",
                     "a: 'unterminated\n", "---\na: 1\n"):
            with self.subTest(text=text):
                with self.assertRaises(mini_yaml.YamlSubsetError):
                    mini_yaml.loads(text)

    def test_matches_pyyaml_on_the_fixture_when_available(self):
        try:
            import yaml  # noqa: PLC0415
        except ImportError:
            self.skipTest("PyYAML not installed (the framework never needs it)")
        texts = [(FIXTURE / "letters" / "people.yaml").read_text(encoding="utf-8")]
        for path in sorted(FIXTURE.glob("letters/*/*/transcript.md")):
            texts.append(documents.split_transcript(path.read_text(encoding="utf-8"))[0])
        for text in texts:
            self.assertEqual(mini_yaml.loads(text), yaml.safe_load(text))


class PeopleTests(unittest.TestCase):
    def setUp(self):
        self.people = documents.People(
            mini_yaml.loads((FIXTURE / "letters" / "people.yaml").read_text(encoding="utf-8")))

    def test_collection_scoped_alias_names_a_different_person_per_collection(self):
        self.assertEqual(self.people.resolve("Dad", "pat-mission"), ["sam-owner"])
        self.assertEqual(self.people.resolve("Dad", "old-box"), ["ezra-owner"])

    def test_primary_is_earliest_and_secondaries_must_be_outside_parentheses(self):
        self.assertEqual(self.people.resolve("Mom and Dad", "pat-mission"), ["lee-owner", "sam-owner"])
        # Sam Owner is named only inside the parentheses: primary only.
        self.assertEqual(self.people.resolve("Dad (Sam Owner)", "old-box"), ["ezra-owner"])
        self.assertEqual(self.people.resolve("A stranger", "old-box"), ["other-a-stranger"])

    def test_people_list_mentions_need_a_whole_name(self):
        mention = self.people.resolve_mention
        self.assertEqual(mention("Pat (Elder Owner, the recipient)", "pat-mission"), "pat-owner")
        self.assertEqual(mention("Robin", "old-box"), "robin-friend")
        self.assertIsNone(mention("Your mom (unnamed)", "pat-mission"))
        self.assertEqual(mention("Somebody (Ezra Owner)", "old-box"), "ezra-owner")

    def test_refs(self):
        mapping = {"pat-owner": "self", "sam-owner": "person/dad"}
        self.assertEqual(documents.ref_for("pat-owner", mapping), "self")
        self.assertEqual(documents.ref_for("robin-friend", mapping), "person/robin-friend")
        self.assertIsNone(documents.ref_for("unknown", mapping))
        self.assertIsNone(documents.ref_for("other-a-stranger", mapping))
        with self.assertRaises(documents.DocumentsError):
            documents.validate_ref("Dad")


class _LettersVault(unittest.TestCase):
    """A synthetic external vault plus a git copy of the fixture letters repo."""

    def setUp(self):
        self.tmp = root_parent_tmp(self, ROOT, prefix="lifehug-471-documents-")
        self.repo = self.tmp / "letters-repo"
        shutil.copytree(FIXTURE, self.repo)
        _git(self.repo, "init", "-q", "-b", "main")
        _git(self.repo, "add", "-A")
        _git(self.repo, "commit", "-q", "-m", "fixture letters")
        self.commit1 = _git(self.repo, "rev-parse", "HEAD")
        self.vault = self.tmp / "vault"
        (self.vault / "state").mkdir(parents=True)
        (self.vault / "question-bank.md").write_text(
            "# Synthetic questions\n\n## A: Origins\n- [ ] A1: What is your earliest memory?\n",
            encoding="utf-8")
        (self.vault / "state" / "rotation.json").write_text(json.dumps({
            "version": 1, "current_pass": 1, "pass_names": ["skeleton"], "last_question_id": None,
            "last_asked_at": None, "questions_asked": 0, "questions_answered": 0,
            "next_question_id": None, "focus_frequency": 4}), encoding="utf-8")
        (self.vault / "state" / "coverage.json").write_text(json.dumps({
            "version": 1, "last_updated": None,
            "categories": {"A": {"total": 1, "answered": 0, "status": "red"}}}), encoding="utf-8")

    def run_cli(self, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
        env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": str(self.vault),
               "LIFEHUG_VAULT_ROOT": str(self.vault), "TMPDIR": os.environ.get("TMPDIR", "/tmp"),
               **GIT_ENV}
        result = subprocess.run([sys.executable, str(SYSTEM / "lifehug.py"), *args],
                                capture_output=True, text=True, cwd=str(self.vault), env=env)
        if check:
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return result

    def py(self, code: str) -> str:
        env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": str(self.vault),
               "LIFEHUG_VAULT_ROOT": str(self.vault), "PYTHONPATH": str(SYSTEM)}
        result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                                cwd=str(self.vault), env=env)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout.strip()

    def file_all(self, *extra: str, check: bool = True) -> subprocess.CompletedProcess[str]:
        return self.run_cli("documents", "file", str(self.repo), "--all", "--commit", "HEAD",
                            *MAPS, "--scan-url-template", SCAN_TEMPLATE, *extra, check=check)

    def records(self) -> dict[str, Path]:
        base = self.vault / "sources" / "letters"
        return {p.relative_to(base).as_posix(): p for p in sorted(base.rglob("*.md"))}

    def meta(self, rel: str) -> dict:
        from lifehug_core import split_frontmatter  # noqa: PLC0415

        return split_frontmatter((self.vault / "sources" / "letters" / rel).read_text(encoding="utf-8"))[0]



class FilingTests(_LettersVault):
    """The CLI end to end against a synthetic external vault."""

    def test_files_every_transcript_as_a_letter_record(self):
        out = self.file_all().stdout
        self.assertIn("wrote: 5 (5 new, 0 superseding)", out)
        self.assertEqual(sorted(self.records()), [
            "old-box/dad-to-sam.md", "pat-mission/dad-letter.md", "pat-mission/newsletter-002.md",
            "pat-mission/newsletter.md", "pat-mission/pat-to-home.md"])

        dad = self.meta("pat-mission/dad-letter.md")
        self.assertEqual(dad["type"], "letter")
        self.assertEqual(dad["source_id"], "letters:pat-mission/dad-letter")
        self.assertEqual(dad["source_trust"], "external_record")
        self.assertEqual(dad["authority"], "third_party_record")
        self.assertEqual(dad["sensitivity"], "family")
        self.assertIs(dad["immutable"], True)
        self.assertEqual(dad["captured_at"], "2001-06-12T00:00:00Z")
        self.assertEqual((dad["written_date"], dad["written_date_precision"]), ("2001-06-12", "day"))
        self.assertIn("JUN 13 2001", dad["written_date_evidence"])
        self.assertEqual(dad["author_refs"], ["person/dad"])
        self.assertEqual(dad["recipient_refs"], ["self"])
        # people list: Pat is the recipient (dropped), Robin is about, "Your mom" names nobody.
        self.assertEqual(dad["subject_refs"], ["person/robin-friend"])
        self.assertEqual(dad["author_label"], "Dad (Sam Owner)")
        origin = dad["origin"]
        self.assertEqual(origin["commit"], self.commit1)
        self.assertEqual(origin["id"], "pat-mission/dad-letter")
        self.assertEqual(origin["source_file"], "2001/DAD.pdf")
        self.assertEqual(origin["scan_blob"], _git(self.repo, "rev-parse", "HEAD:source/2001/DAD.pdf"))
        self.assertEqual(origin["scan_url"], "https://letters.example/letters/pat-mission/dad-letter/scan.pdf")
        self.assertEqual(origin["transcript_blob"],
                         _git(self.repo, "rev-parse", "HEAD:letters/pat-mission/dad-letter/transcript.md"))

    def test_first_person_scoped_alias_split_and_precision(self):
        self.file_all()
        home = self.meta("pat-mission/pat-to-home.md")
        self.assertEqual(home["authority"], "first_person_record")
        self.assertEqual(home["author_refs"], ["self"])
        self.assertEqual(home["recipient_refs"], ["person/mom", "person/dad"])
        self.assertEqual(home["document_type"], "card")
        self.assertEqual((home["written_date"], home["captured_at"]), ("2002", "2002"))

        old = self.meta("old-box/dad-to-sam.md")  # "Dad" in the old box is Ezra, not Sam
        self.assertEqual(old["author_refs"], ["person/ezra-owner"])
        self.assertEqual(old["recipient_refs"], [])  # "Sam" alone matches no alias
        self.assertEqual((old["written_date"], old["captured_at"]), ("1974-03", "1974-03"))

        part1, part2 = self.meta("pat-mission/newsletter.md"), self.meta("pat-mission/newsletter-002.md")
        self.assertEqual(part1["origin"]["source_file"], part2["origin"]["source_file"])
        self.assertEqual((part1["origin"]["source_pages"], part2["origin"]["source_pages"]), ([1, 2], [3]))
        self.assertEqual(part1["origin"]["scan_blob"], part2["origin"]["scan_blob"])
        self.assertEqual((part1["written_date"], part1["written_date_precision"], part1["captured_at"]),
                         (None, "unknown", ""))
        self.assertEqual(part1["author_refs"], ["person/mission-office"])

    def test_body_is_the_transcript_byte_for_byte_and_rebuilds_it(self):
        self.file_all()
        for rel, path in self.records().items():
            collection, name = rel.split("/")
            original = (self.repo / "letters" / collection / name[:-3] / "transcript.md").read_bytes()
            text = path.read_text(encoding="utf-8")
            header, body = documents.split_transcript(original.decode("utf-8"))
            payload = text[text.index("\n---\n", 3) + 5:]
            self.assertTrue(payload.startswith(body), rel)
            self.assertIn(header, payload[len(body):])
            self.assertEqual(documents.transcript_from_record(text), original, rel)

    def test_manifest_and_config(self):
        self.file_all()
        manifest = json.loads((self.vault / "state" / "source_manifest.json").read_text(encoding="utf-8"))
        entry = manifest["sources"]["sources/letters/pat-mission/dad-letter.md"]
        self.assertEqual(entry["type"], "letter")
        self.assertEqual(entry["author_label"], "Dad (Sam Owner)")
        self.assertEqual(entry["recipient_refs"], ["self"])
        self.assertEqual(entry["written_date"], "2001-06-12")
        self.assertEqual(entry["collection"], "pat-mission")
        self.assertEqual(entry["origin"]["id"], "pat-mission/dad-letter")
        config = json.loads((self.vault / "state" / "documents" / "letters.json").read_text(encoding="utf-8"))
        self.assertEqual(config["people_map"]["pat-owner"], "self")
        self.assertEqual(config["scan_url_template"], SCAN_TEMPLATE)

    def test_rerun_on_the_same_commit_changes_nothing(self):
        self.file_all()
        before = {rel: p.read_bytes() for rel, p in self.records().items()}
        manifest = (self.vault / "state" / "source_manifest.json").read_bytes()
        # The remembered map and template are enough the second time.
        out = self.run_cli("documents", "file", str(self.repo), "--all", "--commit", self.commit1).stdout
        self.assertIn("wrote: 0 (0 new, 0 superseding)", out)
        self.assertIn("unchanged: 5", out)
        self.assertEqual({rel: p.read_bytes() for rel, p in self.records().items()}, before)
        self.assertEqual((self.vault / "state" / "source_manifest.json").read_bytes(), manifest)

    def test_dry_run_and_working_tree_edits_write_nothing(self):
        out = self.file_all("--dry-run").stdout
        self.assertIn("would write: 5", out)
        self.assertFalse((self.vault / "sources").exists())
        self.assertFalse((self.vault / "state" / "documents").exists())
        self.file_all()
        # An uncommitted edit in the letters repo is not what the commit holds.
        path = self.repo / "letters" / "old-box" / "dad-to-sam" / "transcript.md"
        path.write_text(path.read_text(encoding="utf-8") + "\nAn uncommitted line.\n", encoding="utf-8")
        self.assertIn("wrote: 0", self.file_all().stdout)

    def test_changed_transcript_at_a_new_commit_supersedes(self):
        self.file_all()
        old_record = (self.vault / "sources" / "letters" / "old-box" / "dad-to-sam.md").read_bytes()
        path = self.repo / "letters" / "old-box" / "dad-to-sam" / "transcript.md"
        path.write_text(path.read_text(encoding="utf-8").replace("The farm is quiet.", "The farm is very quiet."),
                        encoding="utf-8")
        _git(self.repo, "commit", "-q", "-am", "reread a line")
        commit2 = _git(self.repo, "rev-parse", "HEAD")
        out = self.file_all().stdout
        self.assertIn("wrote: 1 (0 new, 1 superseding)", out)
        self.assertIn("unchanged: 4", out)
        newer = f"old-box/dad-to-sam--{commit2[:12]}.md"
        self.assertIn(newer, self.records())
        self.assertEqual((self.vault / "sources" / "letters" / "old-box" / "dad-to-sam.md").read_bytes(), old_record)
        meta = self.meta(newer)
        self.assertEqual(meta["supersedes"], f"letters:old-box/dad-to-sam@{self.commit1}")
        self.assertEqual(meta["supersedes_path"], "sources/letters/old-box/dad-to-sam.md")
        self.assertEqual(meta["source_id"], f"letters:old-box/dad-to-sam@{commit2[:12]}")
        self.assertEqual(meta["origin"]["commit"], commit2)
        self.assertIn("very quiet", (self.vault / "sources" / "letters" / newer).read_text(encoding="utf-8"))
        self.assertIn("wrote: 0", self.file_all().stdout)  # the new head is current
        lint = self.run_cli("source-lint", check=False).stdout
        self.assertNotIn("sources/letters", lint)

    def test_ids_subset_and_unknown_id(self):
        out = self.run_cli("documents", "file", str(self.repo), "--ids", "old-box/dad-to-sam",
                           "--commit", "HEAD", *MAPS).stdout
        self.assertIn("wrote: 1 (1 new", out)
        self.assertEqual(list(self.records()), ["old-box/dad-to-sam.md"])
        self.assertIsNone(self.meta("old-box/dad-to-sam.md")["origin"]["scan_url"])
        bad = self.run_cli("documents", "file", str(self.repo), "--ids", "old-box/nope",
                           "--commit", "HEAD", check=False)
        self.assertEqual(bad.returncode, 1)
        self.assertIn("old-box/nope: no transcript", bad.stdout)
        refused = self.run_cli("documents", "file", str(self.repo), "--all", "--commit", "no-such-commit",
                               check=False)
        self.assertNotEqual(refused.returncode, 0)

    def test_source_lint_is_clean_and_catches_a_tampered_record(self):
        self.file_all()
        lint = self.run_cli("source-lint", check=False).stdout
        self.assertNotIn("sources/letters", lint)
        path = self.vault / "sources" / "letters" / "pat-mission" / "dad-letter.md"
        path.write_text(path.read_text(encoding="utf-8").replace("The garden", "The yard"), encoding="utf-8")
        lint = self.run_cli("source-lint", check=False).stdout
        self.assertIn("letter_record_invalid sources/letters/pat-mission/dad-letter.md", lint)
        self.assertIn("no longer rebuilds the filed transcript", lint)
        tampered = path.read_bytes()
        self.run_cli("source-lint", "--fix", check=False)
        self.assertEqual(path.read_bytes(), tampered)  # --fix never rewrites a record

    def test_filing_feeds_no_loop_consumer_yet(self):
        self.file_all()
        story = self.vault / "sources" / "manual" / "2026-01-01-a-story.md"
        story.parent.mkdir(parents=True)
        story.write_text("# A story\n\nAn ordinary story the consumers do read.\n", encoding="utf-8")
        self.assertFalse((self.vault / "state" / "question_candidates.json").exists())
        self.assertFalse((self.vault / "state" / "conversations").exists())
        self.assertFalse((self.vault / "state" / "classifications").exists())
        self.assertEqual(self.py(
            "import classify_story as c; print([p.name for p in c.all_source_files()])"),
            "['2026-01-01-a-story.md']")
        self.assertEqual(self.py(
            "import classify_story as c\n"
            "try:\n c._safe_source_path('sources/letters/pat-mission/dad-letter.md')\n"
            "except c.ClassificationPreparationError as e: print(e.code)"),
            "source_classification_deferred")
        self.assertEqual(self.py(
            "import wiki_compile as w; print(sorted(i['source'] for i in w.read_manual_sources().values()))"),
            "['sources/manual/2026-01-01-a-story.md']")
        self.assertEqual(self.py(
            "import resolver; from pathlib import Path; import os\n"
            "print(sorted({d['path'] for d in resolver.story_documents(Path(os.environ['LIFEHUG_VAULT_ROOT']))}))"),
            "['sources/manual/2026-01-01-a-story.md']")


class ViewerTests(_LettersVault):
    """Sources view and the v120 reader on filed letter records."""

    def setUp(self):
        super().setUp()
        self.file_all()
        import serve_wiki  # noqa: PLC0415

        self.sw = serve_wiki
        names = ("ANSWERS_DIR", "SOURCES_DIR", "SOURCE_MANIFEST_FILE", "SOURCE_LINT_FINDINGS_FILE")
        originals = {name: getattr(serve_wiki, name) for name in names}
        self.addCleanup(lambda: [setattr(serve_wiki, k, v) for k, v in originals.items()])
        (self.vault / "answers").mkdir(exist_ok=True)
        serve_wiki.ANSWERS_DIR = self.vault / "answers"
        serve_wiki.SOURCES_DIR = self.vault / "sources"
        serve_wiki.SOURCE_MANIFEST_FILE = self.vault / "state" / "source_manifest.json"
        serve_wiki.SOURCE_LINT_FINDINGS_FILE = self.vault / "state" / "source_lint_findings.json"

    def test_sources_view_lists_letters_under_their_own_type(self):
        _title, body, _ = self.sw.view_sources()
        self.assertIn("<h3>letter (5)</h3>", body)
        self.assertIn("<h4>old-box (1)</h4>", body)
        self.assertIn("<h4>pat-mission (4)</h4>", body)
        for header in ("Written", "Writer", "Recipient"):
            self.assertIn(f"<th>{header}</th>", body)
        row = body[body.index("Dad (Sam Owner) to Elder Owner"):]
        row = row[: row.index("</tr>")]
        for cell in ("2001-06-12", "Dad (Sam Owner)", "Elder Owner", "letter"):
            self.assertIn(cell, row)
        self.assertIn('href="/source/sources/letters/pat-mission/dad-letter.md"', body)
        pat = body.index("<h4>pat-mission")
        order = [body.index(t, pat) for t in ("Dad (Sam Owner) to Elder Owner",
                                               "Mission office to All missionaries, 2001-12",
                                               "Pat (Elder Owner) to Mom and Dad",
                                               "Mission office to All missionaries, undated")]
        self.assertEqual(order, sorted(order))  # written-date order, undated last

    def test_reader_shows_the_letter_fields(self):
        _title, body = self.sw.source_document_html("sources/letters/pat-mission/dad-letter.md")
        for label, value in (("Writer", "Dad (Sam Owner)"), ("Recipient", "Elder Owner"),
                             ("Recipient refs", "self"), ("Written", "2001-06-12"),
                             ("Collection", "pat-mission"), ("Sensitivity", "family"),
                             ("About", "person/robin-friend")):
            self.assertIn(f"<td>{label}</td><td>{value}</td>", body.replace("\n", ""))
        self.assertIn('href="https://letters.example/letters/pat-mission/dad-letter/scan.pdf"', body)
        self.assertIn("<em>[scan page 1; confidence 0.90]</em>", body)
        self.assertIn('<details class="transcript-header">', body)
        self.assertIn("date_evidence: &#x27;Written at the top", body)
        self.assertNotIn("```", body)
        undated = self.sw.source_document_html("sources/letters/pat-mission/newsletter.md")[1]
        self.assertIn("<td>Written</td><td>undated</td>", undated.replace("\n", ""))

    def test_one_manifest_read_per_listing_gives_the_same_links(self):
        manifest = json.loads(self.sw.SOURCE_MANIFEST_FILE.read_text(encoding="utf-8"))["sources"]
        for ref in list(manifest)[:5] + ["sources/letters/nope.md", "../etc/passwd"]:
            self.assertEqual(self.sw.source_href(ref, manifest=manifest), self.sw.source_href(ref))


class DeferralDefinitionTests(unittest.TestCase):
    def test_one_letter_type_definition(self):
        import classify_story  # noqa: PLC0415
        import resolver  # noqa: PLC0415
        import source_integrity  # noqa: PLC0415
        import wiki_compile  # noqa: PLC0415

        self.assertIs(documents.LETTER_TYPE, source_integrity.LETTER_TYPE)
        for deferred in (classify_story.CLASSIFICATION_DEFERRED_TYPES,
                         wiki_compile.COMPILE_DEFERRED_TYPES, resolver.RETRIEVAL_DEFERRED_TYPES):
            self.assertIn(source_integrity.LETTER_TYPE, deferred)

    def test_documents_is_a_classified_mutation_command(self):
        import lifehug  # noqa: PLC0415

        self.assertIn("documents", lifehug.DIRECT_MUTATION_COMMANDS)


if __name__ == "__main__":
    unittest.main()
