"""Letters D1 after v412: `documents file`, superseding versions, refs, the
verbatim-header trailer, and the letters listing and reader.

v404 filed a cited letter once, from the archive's working tree, through
`family_letters.file_letter`. v412 adds a bulk, pinned door (`lifehug.py
documents file <archive> --all | --ids … --commit <sha>`) that reads the
archive THROUGH GIT AT THE COMMIT and hands every transcript to the SAME
writer, so both doors produce the same record. On top of v404's record:
people.yaml refs, `authority: first_person_record` for the owner's own
letters, `origin` pinned to commit and blobs, the transcript's own YAML
header verbatim AFTER the verbatim body (so the archive's file rebuilds
byte for byte), and a superseding version when a transcript is revised.

The fixture under tests/fixtures/letters_repo is a synthetic archive
(people.yaml with collection-scoped aliases, a first-person card, a split
newsletter in two parts, one undated, month and year precision). Each test
commits it into a throwaway git repository. Synthetic data only; never the
real letters or a real vault.
"""

from __future__ import annotations

import json
import os
import re
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

import family_letters as fl  # noqa: E402
import letter_people as lp  # noqa: E402
import mini_yaml  # noqa: E402
from tempdirs import root_parent_tmp  # noqa: E402

SCAN_TEMPLATE = "https://letters.example/letters/{id}/scan.pdf"
MAPS = ["--map", "pat-owner=self", "--map", "sam-owner=person/dad", "--map", "lee-owner=person/mom"]
GIT_ENV = {
    "GIT_AUTHOR_NAME": "Fixture", "GIT_AUTHOR_EMAIL": "fixture@example.invalid",
    "GIT_COMMITTER_NAME": "Fixture", "GIT_COMMITTER_EMAIL": "fixture@example.invalid",
    "GIT_CONFIG_NOSYSTEM": "1",
}
STEMS = ["old-box--dad-to-sam.md", "pat-mission--dad-letter.md", "pat-mission--newsletter-002.md",
         "pat-mission--newsletter.md", "pat-mission--pat-to-home.md"]

#: Lifehug Cloud's vault validator (lifehug-platform
#: services/api/app/vault_safety/validator.py): `INVALID_ID` (hard reject)
#: and `INVALID_DATE` (manual review) both stop a vault being served.
PLATFORM_ID_KEYS = ("id", "source_id", "question_id")
PLATFORM_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9:._-]{0,127}$")
PLATFORM_DATE_KEY_RE = re.compile(r"(^date$|^created$|^updated$|^answered$|_date$|_at$)")


def _git(repo: Path, *args: str) -> str:
    env = {**os.environ, **GIT_ENV, "HOME": str(repo)}
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True,
                          text=True, env=env).stdout.strip()


class MiniYamlTests(unittest.TestCase):
    """people.yaml is read with the dependency-free `mini_yaml` (#473)."""

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
            texts.append(fl.split_exact(path.read_text(encoding="utf-8"))[0])
        for text in texts:
            self.assertEqual(mini_yaml.loads(text), yaml.safe_load(text))

    def test_v404s_header_reader_agrees_with_mini_yaml_on_the_fields_it_files(self):
        for path in sorted(FIXTURE.glob("letters/*/*/transcript.md")):
            raw = path.read_text(encoding="utf-8")
            header, _body = fl.parse_header(raw)
            full = mini_yaml.loads(fl.split_exact(raw)[0])
            for key in fl.HEADER_FIELDS + ("source_pages",):
                if key in full:
                    self.assertEqual(header.get(key), full[key], f"{path}: {key}")


class PeopleTests(unittest.TestCase):
    def setUp(self):
        self.people = lp.People.from_text(
            (FIXTURE / "letters" / "people.yaml").read_text(encoding="utf-8"))

    def test_collection_scoped_alias_names_a_different_person_per_collection(self):
        self.assertEqual(self.people.resolve("Dad", "pat-mission"), ["sam-owner"])
        self.assertEqual(self.people.resolve("Dad", "old-box"), ["ezra-owner"])

    def test_primary_is_earliest_and_secondaries_must_be_outside_parentheses(self):
        self.assertEqual(self.people.resolve("Mom and Dad", "pat-mission"), ["lee-owner", "sam-owner"])
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
        self.assertEqual(lp.ref_for("pat-owner", mapping), "self")
        self.assertEqual(lp.ref_for("robin-friend", mapping), "person/robin-friend")
        self.assertIsNone(lp.ref_for("unknown", mapping))
        self.assertIsNone(lp.ref_for("other-a-stranger", mapping))
        with self.assertRaises(lp.PeopleError):
            lp.parse_map_args(["sam-owner=Dad"])
        with self.assertRaises(lp.PeopleError):
            lp.parse_map_args(["no-equals"])


class IdTests(unittest.TestCase):
    def test_a_superseding_version_id_is_one_the_hosted_validator_accepts(self):
        sid = fl.versioned_source_id("old-box/dad-to-sam", "0123456789ab")
        self.assertEqual(sid, "letters:old-box--dad-to-sam:0123456789ab")
        self.assertRegex(sid, PLATFORM_ID_RE)
        self.assertNotRegex("letters:old-box--dad-to-sam@0123456789ab", PLATFORM_ID_RE)
        self.assertEqual(fl.normalize_id(sid), "old-box/dad-to-sam")

    def test_the_trailer_rebuilds_any_header_including_one_with_fences(self):
        raw = "---\nid: a/b\nnote: '```x```'\n---\n\n# A to B\n\nbody\n"
        letter = {"id": "a/b", "header": fl.parse_header(raw)[0], "body": fl.parse_header(raw)[1],
                  "raw": raw, "transcript_blob": fl.git_blob_sha(raw.encode())}
        _rel, content = fl.render_source(letter, filed_at="2026-10-10T00:00:00Z")
        self.assertEqual(fl.transcript_from_record(content), raw.encode())
        self.assertIn("\n````yaml\n", content)
        # No header to keep: v404's shape, no trailer.
        bare = {"id": "a/b", "header": {}, "body": "just text\n", "raw": "just text\n"}
        _rel, content = fl.render_source(bare, filed_at="2026-10-10T00:00:00Z")
        self.assertNotIn(fl.TRAILER_MARKER, content)
        self.assertTrue(content.endswith("---\n\njust text\n"))


class _LettersVault(unittest.TestCase):
    """A synthetic external vault plus a git copy of the fixture archive."""

    def setUp(self):
        self.tmp = root_parent_tmp(self, ROOT, prefix="lifehug-v412-documents-")
        self.repo = self.tmp / "letters-repo"
        shutil.copytree(FIXTURE, self.repo)
        _git(self.repo, "init", "-q", "-b", "main")
        _git(self.repo, "add", "-A")
        _git(self.repo, "commit", "-q", "-m", "fixture letters")
        self.commit1 = _git(self.repo, "rev-parse", "HEAD")
        self.vault = self.make_vault("vault")

    def make_vault(self, name: str) -> Path:
        vault = self.tmp / name
        (vault / "state").mkdir(parents=True)
        (vault / "question-bank.md").write_text(
            "# Synthetic questions\n\n## A: Origins\n- [ ] A1: What is your earliest memory?\n",
            encoding="utf-8")
        (vault / "state" / "rotation.json").write_text(json.dumps({
            "version": 1, "current_pass": 1, "pass_names": ["skeleton"], "last_question_id": None,
            "last_asked_at": None, "questions_asked": 0, "questions_answered": 0,
            "next_question_id": None, "focus_frequency": 4}), encoding="utf-8")
        (vault / "state" / "coverage.json").write_text(json.dumps({
            "version": 1, "last_updated": None,
            "categories": {"A": {"total": 1, "answered": 0, "status": "red"}}}), encoding="utf-8")
        return vault

    def env(self, vault: Path | None = None) -> dict:
        vault = vault or self.vault
        return {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": str(vault),
                "LIFEHUG_VAULT_ROOT": str(vault), "TMPDIR": os.environ.get("TMPDIR", "/tmp"),
                "LIFEHUG_FAMILY_LETTERS_DIR": str(self.repo), **GIT_ENV}

    def run_cli(self, *args: str, check: bool = True, vault: Path | None = None
                ) -> subprocess.CompletedProcess[str]:
        vault = vault or self.vault
        result = subprocess.run([sys.executable, str(SYSTEM / "lifehug.py"), *args],
                                capture_output=True, text=True, cwd=str(vault), env=self.env(vault))
        if check:
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return result

    def py(self, code: str) -> str:
        env = {**self.env(), "PYTHONPATH": str(SYSTEM)}
        result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                                cwd=str(self.vault), env=env)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout.strip()

    def file_all(self, *extra: str, check: bool = True, vault: Path | None = None
                 ) -> subprocess.CompletedProcess[str]:
        return self.run_cli("documents", "file", str(self.repo), "--all", "--commit", "HEAD",
                            *MAPS, "--scan-url-template", SCAN_TEMPLATE, *extra, check=check,
                            vault=vault)

    def records(self, vault: Path | None = None) -> dict[str, Path]:
        base = (vault or self.vault) / "sources" / "letters"
        return {p.name: p for p in sorted(base.glob("*.md"))} if base.is_dir() else {}

    def meta(self, name: str, vault: Path | None = None) -> dict:
        from lifehug_core import split_frontmatter  # noqa: PLC0415

        path = (vault or self.vault) / "sources" / "letters" / name
        return split_frontmatter(path.read_text(encoding="utf-8"))[0]


class FilingTests(_LettersVault):
    """`documents file` end to end against a synthetic external vault."""

    def test_files_every_transcript_in_the_v404_shape_with_refs_and_origin(self):
        out = self.file_all().stdout
        self.assertIn("wrote: 5 (5 new, 0 superseding)", out)
        self.assertEqual(sorted(self.records()), STEMS)

        dad = self.meta("pat-mission--dad-letter.md")
        # v404's shape: path, id, field names.
        self.assertEqual(dad["type"], "letter")
        self.assertEqual(dad["source_id"], "letters:pat-mission--dad-letter")
        self.assertEqual(dad["letter_id"], "pat-mission/dad-letter")
        self.assertEqual(dad["collection"], "pat-mission")
        self.assertEqual(dad["source_trust"], "external_record")
        self.assertEqual(dad["authority"], "third_party_record")
        self.assertEqual(dad["sensitivity"], "family")
        self.assertIs(dad["immutable"], True)
        self.assertEqual(dad["captured_at"], "2001-06-12T00:00:00Z")
        self.assertEqual((dad["date"], dad["date_edtf"], dad["date_precision"]),
                         ("2001-06-12", "2001-06-12", "day"))
        self.assertIn("JUN 13 2001", dad["date_evidence"])
        self.assertEqual((dad["from"], dad["to"]), ("Dad (Sam Owner)", "Elder Owner"))
        self.assertEqual(dad["people"], ["Pat (Elder Owner, the recipient)", "Robin",
                                         "Your mom (unnamed)"])
        # v412: refs beside the header's strings.
        self.assertEqual(dad["author_refs"], ["person/dad"])
        self.assertEqual(dad["recipient_refs"], ["self"])
        self.assertEqual(dad["subject_refs"], ["person/robin-friend"])
        origin = dad["origin"]
        self.assertEqual(origin["repo"], "lifehug/letters")
        self.assertEqual(origin["id"], "pat-mission/dad-letter")
        self.assertEqual(origin["path"], "letters/pat-mission/dad-letter/transcript.md")
        self.assertEqual(origin["commit"], self.commit1)
        self.assertEqual(origin["source_file"], "2001/DAD.pdf")
        self.assertIsNone(origin["source_pages"])
        self.assertEqual(origin["scan_blob"], _git(self.repo, "rev-parse", "HEAD:source/2001/DAD.pdf"))
        self.assertEqual(origin["scan_url"], "https://letters.example/letters/pat-mission/dad-letter/scan.pdf")
        self.assertEqual(origin["transcript_blob"],
                         _git(self.repo, "rev-parse", "HEAD:letters/pat-mission/dad-letter/transcript.md"))
        self.assertNotIn("supersedes", dad)

    def test_first_person_scoped_alias_split_and_precision(self):
        self.file_all()
        home = self.meta("pat-mission--pat-to-home.md")
        self.assertEqual(home["authority"], "first_person_record")
        self.assertEqual(home["author_refs"], ["self"])
        self.assertEqual(home["recipient_refs"], ["person/mom", "person/dad"])
        self.assertEqual(home["document_type"], "card")
        # Year precision: v404's rule — no invented ISO `date`, the year in
        # date_edtf, captured_at the filing time (never a made-up day).
        self.assertEqual(home["date_edtf"], "2002")
        self.assertNotIn("date", home)
        self.assertEqual(home["captured_at"], home["filed_at"])

        old = self.meta("old-box--dad-to-sam.md")  # "Dad" in the old box is Ezra, not Sam
        self.assertEqual(old["author_refs"], ["person/ezra-owner"])
        self.assertEqual(old["recipient_refs"], [])  # "Sam" alone matches no alias
        self.assertEqual(old["date_edtf"], "1974-03")

        part1, part2 = self.meta("pat-mission--newsletter.md"), self.meta("pat-mission--newsletter-002.md")
        self.assertEqual(part1["origin"]["source_file"], part2["origin"]["source_file"])
        self.assertEqual((part1["origin"]["source_pages"], part2["origin"]["source_pages"]), ([1, 2], [3]))
        self.assertEqual(part1["origin"]["scan_blob"], part2["origin"]["scan_blob"])
        self.assertNotIn("date_edtf", part1)
        self.assertEqual(part1["author_refs"], ["person/mission-office"])

    def test_body_is_the_transcript_verbatim_and_the_record_rebuilds_it(self):
        self.file_all()
        for name, path in self.records().items():
            letter_id = fl.normalize_id(name[:-3])
            original = (self.repo / "letters" / letter_id / "transcript.md").read_bytes()
            text = path.read_text(encoding="utf-8")
            header, body = fl.split_exact(original.decode("utf-8"))
            payload = text[text.index("\n---\n", 3) + 5:]
            self.assertTrue(payload.startswith(body), name)
            self.assertEqual(payload[len(body):], fl.trailer(header), name)
            self.assertEqual(fl.transcript_from_record(text), original, name)
            # content_sha256 is source_integrity's payload hash (body + trailer).
            self.assertEqual(self.meta(name)["content_sha256"], _payload_hash(text), name)

    def test_manifest_and_remembered_config(self):
        self.file_all()
        manifest = json.loads((self.vault / "state" / "source_manifest.json").read_text(encoding="utf-8"))
        entry = manifest["sources"]["sources/letters/pat-mission--dad-letter.md"]
        self.assertEqual(entry["type"], "letter")
        self.assertEqual(entry["from"], "Dad (Sam Owner)")
        self.assertEqual(entry["recipient_refs"], ["self"])
        self.assertEqual(entry["date_edtf"], "2001-06-12")
        self.assertEqual(entry["collection"], "pat-mission")
        self.assertEqual(entry["origin"]["id"], "pat-mission/dad-letter")
        config = json.loads((self.vault / "state" / "documents" / "letters.json").read_text(encoding="utf-8"))
        self.assertEqual(config["people_map"]["pat-owner"], "self")
        self.assertEqual(config["scan_url_template"], SCAN_TEMPLATE)

    def test_rerun_on_the_same_commit_changes_nothing(self):
        self.file_all()
        before = {name: p.read_bytes() for name, p in self.records().items()}
        manifest = (self.vault / "state" / "source_manifest.json").read_bytes()
        # The remembered map and template are enough the second time.
        out = self.run_cli("documents", "file", str(self.repo), "--all", "--commit", self.commit1).stdout
        self.assertIn("wrote: 0 (0 new, 0 superseding)", out)
        self.assertIn("unchanged: 5", out)
        self.assertEqual({name: p.read_bytes() for name, p in self.records().items()}, before)
        self.assertEqual((self.vault / "state" / "source_manifest.json").read_bytes(), manifest)

    def test_dry_run_and_working_tree_edits_write_nothing(self):
        out = self.file_all("--dry-run").stdout
        self.assertIn("would write: 5", out)
        self.assertFalse((self.vault / "sources").exists())
        self.assertFalse((self.vault / "state" / "documents").exists())
        self.file_all()
        # An uncommitted edit in the archive is not what the commit holds.
        path = self.repo / "letters" / "old-box" / "dad-to-sam" / "transcript.md"
        path.write_text(path.read_text(encoding="utf-8") + "\nAn uncommitted line.\n", encoding="utf-8")
        self.assertIn("wrote: 0", self.file_all().stdout)

    def test_a_revised_transcript_files_a_superseding_version_and_the_old_one_stays(self):
        self.file_all()
        old_path = self.vault / "sources" / "letters" / "old-box--dad-to-sam.md"
        old_record = old_path.read_bytes()
        path = self.repo / "letters" / "old-box" / "dad-to-sam" / "transcript.md"
        path.write_text(path.read_text(encoding="utf-8").replace("The farm is quiet.", "The farm is very quiet."),
                        encoding="utf-8")
        _git(self.repo, "commit", "-q", "-am", "reread a line")
        commit2 = _git(self.repo, "rev-parse", "HEAD")
        blob2 = _git(self.repo, "rev-parse", "HEAD:letters/old-box/dad-to-sam/transcript.md")
        out = self.file_all().stdout
        self.assertIn("wrote: 1 (0 new, 1 superseding)", out)
        self.assertIn("unchanged: 4", out)
        newer = f"old-box--dad-to-sam--{blob2[:12]}.md"
        self.assertIn(newer, self.records())
        self.assertEqual(old_path.read_bytes(), old_record)
        meta = self.meta(newer)
        self.assertEqual(meta["source_id"], f"letters:old-box--dad-to-sam:{blob2[:12]}")
        self.assertRegex(meta["source_id"], PLATFORM_ID_RE)
        self.assertEqual(meta["supersedes"], "letters:old-box--dad-to-sam")
        self.assertEqual(meta["supersedes_path"], "sources/letters/old-box--dad-to-sam.md")
        self.assertEqual(meta["origin"]["commit"], commit2)
        self.assertEqual(meta["letter_id"], "old-box/dad-to-sam")
        self.assertIn("very quiet", (self.vault / "sources" / "letters" / newer).read_text(encoding="utf-8"))
        self.assertIn("wrote: 0", self.file_all().stdout)  # the new version is current
        lint = self.run_cli("source-lint", check=False).stdout
        self.assertNotIn("sources/letters", lint)
        # The intake door now names the CURRENT version as the one on file.
        run = subprocess.run(
            [sys.executable, str(SYSTEM / "intake.py"), "letter", "old-box/dad-to-sam", "--no-commit"],
            capture_output=True, text=True, cwd=str(self.vault), env=self.env())
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        self.assertIn(f"already filed: sources/letters/{newer}", run.stdout)

    def test_a_v404_record_of_the_same_transcript_is_current_and_a_revision_supersedes_it(self):
        legacy = _v404_record(self.repo, "old-box/dad-to-sam")
        target = self.vault / "sources" / "letters" / "old-box--dad-to-sam.md"
        target.parent.mkdir(parents=True)
        target.write_text(legacy, encoding="utf-8")
        out = self.file_all().stdout
        self.assertIn("wrote: 4 (4 new, 0 superseding)", out)
        self.assertIn("unchanged: 1", out)
        self.assertEqual(target.read_text(encoding="utf-8"), legacy)
        path = self.repo / "letters" / "old-box" / "dad-to-sam" / "transcript.md"
        path.write_text(path.read_text(encoding="utf-8").replace("Robin Friend came by.", "Robin came by."),
                        encoding="utf-8")
        _git(self.repo, "commit", "-q", "-am", "reread")
        self.assertIn("wrote: 1 (0 new, 1 superseding)", self.file_all().stdout)
        self.assertEqual(target.read_text(encoding="utf-8"), legacy)

    def test_ids_subset_unknown_id_and_bad_commit(self):
        out = self.run_cli("documents", "file", str(self.repo), "--ids", "old-box/dad-to-sam",
                           "--commit", "HEAD", *MAPS).stdout
        self.assertIn("wrote: 1 (1 new", out)
        self.assertEqual(list(self.records()), ["old-box--dad-to-sam.md"])
        self.assertIsNone(self.meta("old-box--dad-to-sam.md")["origin"]["scan_url"])
        bad = self.run_cli("documents", "file", str(self.repo), "--ids", "old-box/nope",
                           "--commit", "HEAD", check=False)
        self.assertEqual(bad.returncode, 1)
        self.assertIn("old-box/nope: no transcript", bad.stdout)
        refused = self.run_cli("documents", "file", str(self.repo), "--all", "--commit", "no-such-commit",
                               check=False)
        self.assertNotEqual(refused.returncode, 0)
        self.assertNotIn("Traceback", refused.stderr)

    def test_source_lint_is_clean_and_catches_a_tampered_record(self):
        self.file_all()
        lint = self.run_cli("source-lint", check=False).stdout
        self.assertNotIn("sources/letters", lint)
        path = self.vault / "sources" / "letters" / "pat-mission--dad-letter.md"
        text = path.read_text(encoding="utf-8").replace("The garden", "The yard")
        # Keep the declared hash honest so ONLY the letter check can see it.
        text = re.sub(r'^content_sha256: ".*"$', f'content_sha256: "{_payload_hash(text)}"', text,
                      flags=re.M)
        path.write_text(text, encoding="utf-8")
        lint = self.run_cli("source-lint", check=False).stdout
        self.assertIn("letter_record_invalid sources/letters/pat-mission--dad-letter.md", lint)
        self.assertIn("no longer rebuilds the filed transcript", lint)
        tampered = path.read_bytes()
        self.run_cli("source-lint", "--fix", check=False)
        self.assertEqual(path.read_bytes(), tampered)  # --fix never rewrites a record

    def test_every_filed_record_passes_the_hosted_validators_id_and_date_rules(self):
        from datetime import date, datetime  # noqa: PLC0415

        self.file_all()
        path = self.repo / "letters" / "old-box" / "dad-to-sam" / "transcript.md"
        path.write_text(path.read_text(encoding="utf-8") + "\nP.S.\n", encoding="utf-8")
        _git(self.repo, "commit", "-q", "-am", "ps")
        self.file_all()
        self.assertEqual(len(self.records()), 6)
        for name in self.records():
            for key, value in self.meta(name).items():
                if key.lower() in PLATFORM_ID_KEYS:
                    self.assertRegex(value, PLATFORM_ID_RE, f"{name}: {key}")
                elif PLATFORM_DATE_KEY_RE.search(key.lower()) and value not in (None, ""):
                    try:
                        datetime.fromisoformat(str(value).replace("Z", "+00:00"))
                    except ValueError:
                        date.fromisoformat(str(value))  # raises: INVALID_DATE


class OneWriterTests(_LettersVault):
    """`intake letter` (working tree) and `documents file` (git at a commit)
    hand the same transcript to the same writer and get the same record."""

    def test_both_doors_file_the_same_record(self):
        other = self.make_vault("vault-b")
        self.file_all(vault=other)
        # The same map and template, remembered in the first vault's state.
        state = self.vault / "state" / "documents"
        state.mkdir(parents=True)
        shutil.copy(other / "state" / "documents" / "letters.json", state / "letters.json")
        ids = [fl.normalize_id(name[:-3]) for name in STEMS]
        run = subprocess.run([sys.executable, str(SYSTEM / "intake.py"), "letter", *ids, "--no-commit"],
                             capture_output=True, text=True, cwd=str(self.vault), env=self.env())
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        self.assertEqual(sorted(self.records()), sorted(self.records(other)))
        for name in STEMS:
            a = self.meta(name)
            b = self.meta(name, other)
            for meta in (a, b):
                stamp = meta.pop("filed_at")
                if meta.get("captured_at") == stamp:
                    meta.pop("captured_at")
            self.assertEqual(a, b, name)
            body_a = self.records()[name].read_text(encoding="utf-8").split("\n---\n", 1)[1]
            body_b = self.records(other)[name].read_text(encoding="utf-8").split("\n---\n", 1)[1]
            self.assertEqual(body_a, body_b, name)

    def test_an_uncommitted_transcript_through_intake_carries_no_commit(self):
        path = self.repo / "letters" / "old-box" / "dad-to-sam" / "transcript.md"
        path.write_text(path.read_text(encoding="utf-8") + "\nUncommitted.\n", encoding="utf-8")
        run = subprocess.run([sys.executable, str(SYSTEM / "intake.py"), "letter",
                              "old-box/dad-to-sam", "--no-commit"],
                             capture_output=True, text=True, cwd=str(self.vault), env=self.env())
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        origin = self.meta("old-box--dad-to-sam.md")["origin"]
        self.assertIsNone(origin["commit"])
        self.assertEqual(origin["transcript_blob"], fl.git_blob_sha(path.read_bytes()))


class ViewerTests(_LettersVault):
    """The Sources view's letters listing and the v120 reader on letter records."""

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
        for header in ("Written", "Writer", "Recipient", "Kind"):
            self.assertIn(f"<th>{header}</th>", body)
        row = body[body.index("Dad (Sam Owner) to Elder Owner"):]
        row = row[: row.index("</tr>")]
        for cell in ("2001-06-12", "Dad (Sam Owner)", "Elder Owner", "letter"):
            self.assertIn(cell, row)
        self.assertIn('href="/source/sources/letters/pat-mission--dad-letter.md"', body)
        pat = body.index("<h4>pat-mission")
        order = [body.index(t, pat) for t in ("Dad (Sam Owner) to Elder Owner",
                                               "Mission office to All missionaries, 2001-12",
                                               "Pat (Elder Owner) to Mom and Dad",
                                               "Mission office to All missionaries, undated")]
        self.assertEqual(order, sorted(order))  # written-date order, undated last

    def test_reader_shows_the_letter_fields_and_the_header_collapsed(self):
        _title, body = self.sw.source_document_html("sources/letters/pat-mission--dad-letter.md")
        flat = body.replace("\n", "")
        for label, value in (("Writer", "Dad (Sam Owner)"), ("Recipient", "Elder Owner"),
                             ("Writer refs", "person/dad"), ("Recipient refs", "self"),
                             ("Written", "2001-06-12"), ("Collection", "pat-mission"),
                             ("Sensitivity", "family"), ("About", "person/robin-friend")):
            self.assertIn(f"<td>{label}</td><td>{value}</td>", flat)
        self.assertIn('href="https://letters.example/letters/pat-mission/dad-letter/scan.pdf"', body)
        self.assertIn("<em>[scan page 1; confidence 0.90]</em>", body)
        self.assertIn('<details class="transcript-header">', body)
        self.assertIn("date_evidence: &#x27;Written at the top", body)
        self.assertNotIn("```", body)
        undated = self.sw.source_document_html("sources/letters/pat-mission--newsletter.md")[1]
        self.assertIn("<td>Written</td><td>undated</td>", undated.replace("\n", ""))

    def test_one_manifest_read_per_listing_gives_the_same_links(self):
        manifest = json.loads(self.sw.SOURCE_MANIFEST_FILE.read_text(encoding="utf-8"))["sources"]
        for ref in list(manifest)[:5] + ["sources/letters/nope.md", "../etc/passwd"]:
            self.assertEqual(self.sw.source_href(ref, manifest=manifest), self.sw.source_href(ref))


class WiringTests(unittest.TestCase):
    def test_documents_is_a_classified_mutation_command_and_parses(self):
        import lifehug  # noqa: PLC0415

        self.assertIn("documents", lifehug.DIRECT_MUTATION_COMMANDS)
        args = lifehug.build_parser().parse_args(
            ["documents", "file", "/x", "--ids", "a/b", "--commit", "HEAD", "--dry-run"])
        self.assertEqual((args.documents_action, args.ids, args.dry_run), ("file", ["a/b"], True))

    def test_framework_ships_the_code_and_never_the_fixture_or_the_letters(self):
        manifest = json.loads((SYSTEM / "version.json").read_text(encoding="utf-8"))
        shipped = set(manifest["framework_files"])
        for name in ("system/documents.py", "system/letter_people.py", "system/mini_yaml.py",
                     "system/family_letters.py", "tests/test_v412_letters_documents_file.py",
                     "tests/walkthrough_letters.py"):
            self.assertIn(name, shipped)
        # v416 (A_FIXTURE_NEVER_SHIPS_TO_A_VAULT): the fixture archive is test
        # data; shipping it put made-up transcripts into real vaults.
        self.assertFalse(any(path.startswith("tests/fixtures/") for path in shipped))
        self.assertFalse(any(path.startswith("sources/letters") for path in shipped))
        self.assertGreaterEqual(int(manifest["version"]), 412)


def _payload_hash(text: str) -> str:
    from lifehug_core import split_frontmatter  # noqa: PLC0415
    from source_integrity import payload_sha256  # noqa: PLC0415

    return payload_sha256(split_frontmatter(text)[1])


def _v404_record(repo: Path, letter_id: str) -> str:
    """The record v404's `render_source` wrote for a transcript: v404's
    frontmatter, then the body verbatim, no refs, no trailer, no blob."""
    from source_integrity import SCHEMA_VERSION, format_frontmatter, payload_sha256  # noqa: PLC0415

    raw = (repo / "letters" / letter_id / "transcript.md").read_text(encoding="utf-8")
    header, body = fl.parse_header(raw)
    body = body.lstrip("\n")
    values = {
        "title": "Dad (Ezra Owner) to Sam, March 1974", "type": "letter",
        "source_id": fl.source_id(letter_id), "source_medium": "letter",
        "source_trust": "external_record", "authority": "third_party_record",
        "captured_at": "2026-10-09T00:00:00Z", "visibility": "owner_only", "sensitivity": "family",
        "status": "raw", "immutable": True, "schema_version": SCHEMA_VERSION,
        "source_path": fl.source_relpath(letter_id), "content_sha256": payload_sha256(body),
        "letter_id": letter_id, "collection": letter_id.split("/")[0],
        "filed_at": "2026-10-09T00:00:00Z",
        "origin": {"repo": "lifehug/letters", "id": letter_id,
                   "path": f"letters/{letter_id}/transcript.md"},
        **fl.header_values(header),
    }
    return f"{format_frontmatter(values)}\n\n{body}"


if __name__ == "__main__":
    unittest.main()
