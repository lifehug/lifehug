"""A cited letter is filed as a letter (letters-in-the-vault D1, v404).

`family-letters:<collection>/<letter>` on a record intake resolves to the
archive's transcript and files it ONCE as an immutable `sources/letters/`
source; the memo cites it; `intake letter <id>` files one with no memo and
links the memos that already cite it; the classifier reads the letter's own
date as a `document`-basis date. Synthetic family and synthetic archive only;
NEVER references ~/Workspace/dave or the real letters.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SYSTEM = ROOT / "system"
sys.path.insert(0, str(SYSTEM))
sys.path.insert(0, str(ROOT / "tests"))

import chronology as chrono  # noqa: E402
import classifier_claims as cc  # noqa: E402
import family_letters as fl  # noqa: E402
import intake  # noqa: E402
from tempdirs import root_parent_tmp  # noqa: E402
from test_intake import NOW, FakeRunner, IntakeCase  # noqa: E402

LETTER_ID = "orchard-box-1980/aunt-wren"
OTHER_ID = "orchard-box-1980/rowan-card"

TRANSCRIPT = """---
id: orchard-box-1980/aunt-wren
collection: orchard-box-1980
source_file: ORCHARD BOX/AUNT WREN.pdf
document_type: letter
handwriting: cursive
from: Aunt Wren (signed 'Wren + Bo')
from_relationship: Pell's great-aunt and great-uncle
to: Ivy, Corin and the little ones
date: '1983-04-11'
date_text: Mon 11
date_precision: day
date_evidence: "Only 'Mon 11' is written. Dated from content: 'little Pell'
  is two, and the 11th was a Monday in April 1983."
people:
- Ivy
- Corin
- Pell (little Pell, aged 2)
- 'Bo'
places:
- the creek
addresses:
- 'Ivy Fenwick

  12 Larch Row'
topics:
- photos of grandchild
summary: Aunt Wren thanks Ivy for pictures of a grinning little Pell and reports
  the creek is high.
confidence: 0.81
page_confidence:
  scan_page_1: 0.8
status: draft
---

# Aunt Wren (signed 'Wren + Bo') to Ivy, Corin and the little ones, Mon 11

<!-- scan page 1; confidence 0.80 -->
Mon 11,

Dear Ivy, Corin and the little sweethearts,
The pictures of little Pell made us laugh. The creek is high.

## Context

- **Date:** 1983-04-11 (day).
"""

CARD = """---
id: orchard-box-1980/rowan-card
date: '1985-12'
date_precision: month
from: Rowan
to: Pell
summary: A Christmas card.
---

# Rowan to Pell, December 1985

Merry Christmas.
"""

MEMO = "# Orchard House: move-in was April 1983\n\n**Proposed value:** start 1983-04.\n"


def make_archive(base: Path) -> Path:
    archive = base / "family-letters"
    for letter_id, text in ((LETTER_ID, TRANSCRIPT), (OTHER_ID, CARD)):
        folder = archive / "letters" / letter_id
        folder.mkdir(parents=True)
        (folder / "transcript.md").write_text(text, encoding="utf-8")
    return archive


def make_vault(base: Path) -> Path:
    vault = base / "vault"
    (vault / "state").mkdir(parents=True)
    (vault / "sources").mkdir()
    (vault / "question-bank.md").write_text(
        "# Synthetic questions\n\n## A: Origins\n- [ ] A1: What is your earliest memory?\n",
        encoding="utf-8")
    (vault / "state" / "rotation.json").write_text(json.dumps({
        "version": 1, "current_pass": 1, "pass_names": ["skeleton"],
        "last_question_id": None, "last_asked_at": None, "questions_asked": 0,
        "questions_answered": 0, "next_question_id": None, "focus_frequency": 4}),
        encoding="utf-8")
    (vault / "state" / "coverage.json").write_text(json.dumps({
        "version": 1, "last_updated": None,
        "categories": {"A": {"total": 1, "answered": 0, "status": "red"}}}), encoding="utf-8")
    return vault


def env_for(vault: Path, archive: Path | None) -> dict:
    env = {"PATH": "/usr/bin:/bin", "HOME": str(vault), "LIFEHUG_VAULT_ROOT": str(vault)}
    env["LIFEHUG_FAMILY_LETTERS_DIR"] = str(archive) if archive else str(vault / "no-archive")
    if os.environ.get("TMPDIR"):
        env["TMPDIR"] = os.environ["TMPDIR"]
    return env


def ingest_record(vault: Path, archive: Path | None, ref: str, title: str,
                  text: str = MEMO) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SYSTEM / "ingest_story.py"), "--source", "family-letters",
         "--title", title, "--record", ref, "--sensitivity", "family", "--no-candidates"],
        input=text, capture_output=True, text=True, cwd=str(vault), env=env_for(vault, archive))


def front(path: Path) -> dict:
    from lifehug_core import split_frontmatter  # noqa: PLC0415

    return split_frontmatter(path.read_text(encoding="utf-8"))[0]


class HeaderAndRefTests(unittest.TestCase):
    def test_the_transcript_header_subset_reads_like_yaml(self):
        header, body = fl.parse_header(TRANSCRIPT)
        self.assertEqual(header["id"], LETTER_ID)
        self.assertEqual(header["date"], "1983-04-11")
        self.assertEqual(header["date_precision"], "day")
        self.assertEqual(header["date_evidence"],
                         "Only 'Mon 11' is written. Dated from content: 'little Pell' "
                         "is two, and the 11th was a Monday in April 1983.")
        self.assertEqual(header["from"], "Aunt Wren (signed 'Wren + Bo')")
        self.assertEqual(header["people"], ["Ivy", "Corin", "Pell (little Pell, aged 2)", "Bo"])
        self.assertEqual(header["addresses"], ["Ivy Fenwick\n12 Larch Row"])
        self.assertEqual(header["summary"], "Aunt Wren thanks Ivy for pictures of a grinning "
                                            "little Pell and reports the creek is high.")
        self.assertEqual(header["confidence"], 0.81)
        self.assertEqual(header["page_confidence"], {"scan_page_1": 0.8})
        self.assertTrue(body.startswith("\n# Aunt Wren"))
        self.assertTrue(body.endswith("- **Date:** 1983-04-11 (day).\n"))

    def test_ids_come_from_a_family_letters_ref_only(self):
        self.assertEqual(fl.ids_from_ref(f"family-letters:{LETTER_ID}, {OTHER_ID},{LETTER_ID}"),
                         [LETTER_ID, OTHER_ID])
        self.assertEqual(fl.ids_from_ref("family-letters:update/namesake"), [])
        self.assertEqual(fl.ids_from_ref("letters:x/y"), [])
        self.assertEqual(fl.source_relpath(LETTER_ID), "sources/letters/orchard-box-1980--aunt-wren.md")
        self.assertEqual(fl.normalize_id(fl.source_id(LETTER_ID)), LETTER_ID)

    def test_the_archive_is_env_then_config_then_the_default(self):
        self.assertEqual(fl.letters_dir(env={"LIFEHUG_FAMILY_LETTERS_DIR": "/a"},
                                        config={"family_letters_dir": "/b"}), Path("/a"))
        self.assertEqual(fl.letters_dir(env={}, config={"family_letters_dir": "/b"}), Path("/b"))
        self.assertEqual(fl.letters_dir(env={}, config={}),
                         Path("~/Workspace/family-letters").expanduser())

    def test_cites_is_one_frontmatter_line_and_never_the_body(self):
        content = '---\ntitle: "x"\nrecord_ref: "family-letters:a/b"\n---\n\n# x\n\nbody --- here\n'
        once = fl.with_cites(content, ["letters:a/b"])
        self.assertEqual(once, '---\ntitle: "x"\nrecord_ref: "family-letters:a/b"\n'
                               'cites: ["letters:a/b"]\n---\n\n# x\n\nbody --- here\n')
        self.assertIsNone(fl.with_cites(once, ["letters:a/b"]))
        twice = fl.with_cites(once, ["letters:c/d"])
        self.assertIn('cites: ["letters:a/b", "letters:c/d"]', twice)
        self.assertEqual(twice.count("cites:"), 1)


class FilingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = root_parent_tmp(self, ROOT, prefix="v404-letters-")
        self.archive = make_archive(self.tmp)
        self.vault = make_vault(self.tmp)

    def test_a_cited_letter_is_filed_once_as_a_letter_and_the_memo_cites_it(self):
        done = ingest_record(self.vault, self.archive,
                             f"family-letters:{LETTER_ID},orchard-box-1980/lost-page",
                             "Orchard House move-in")
        self.assertEqual(done.returncode, 0, done.stderr)
        letter = self.vault / fl.source_relpath(LETTER_ID)
        self.assertTrue(letter.is_file(), done.stdout)
        meta = front(letter)
        self.assertEqual(meta["type"], "letter")
        self.assertEqual(meta["source_trust"], "external_record")
        self.assertEqual(meta["authority"], "third_party_record")
        self.assertEqual(meta["sensitivity"], "family")
        self.assertEqual(meta["source_id"], "letters:orchard-box-1980--aunt-wren")
        self.assertEqual(meta["letter_id"], LETTER_ID)
        self.assertTrue(meta["immutable"])
        self.assertEqual(meta["captured_at"], "1983-04-11T00:00:00Z")  # written, not filed
        for key in ("date", "date_precision", "date_evidence", "from", "from_relationship",
                    "to", "people", "places", "summary", "source_file"):
            self.assertEqual(meta[key], fl.parse_header(TRANSCRIPT)[0][key], key)
        self.assertNotIn("page_confidence", meta)
        # The body is the transcript's, byte for byte; since v412 it is
        # followed by exactly one trailer holding the header verbatim, and the
        # record rebuilds the archive's file.
        header_text, body = fl.split_exact(TRANSCRIPT)
        text = letter.read_text(encoding="utf-8")
        self.assertTrue(text.endswith(body + fl.trailer(header_text)))
        self.assertEqual(fl.transcript_from_record(text), TRANSCRIPT.encode("utf-8"))
        manifest = json.loads((self.vault / "state" / "source_manifest.json").read_text())
        self.assertEqual(manifest["sources"][fl.source_relpath(LETTER_ID)]["source_id"],
                         fl.source_id(LETTER_ID))
        # The memo cites what is on file — not the page that was not found.
        memo_rel = intake.INGESTED_RE.search(done.stdout).group(1)
        memo = front(self.vault / memo_rel)
        self.assertEqual(memo["cites"], [fl.source_id(LETTER_ID)])
        self.assertEqual(memo["record_ref"], f"family-letters:{LETTER_ID},orchard-box-1980/lost-page")
        self.assertIn(f"✓ Filed letter {LETTER_ID}: {fl.source_relpath(LETTER_ID)}", done.stdout)
        self.assertIn("! letter orchard-box-1980/lost-page not filed (missing_letter)", done.stdout)

        # A second memo citing the same letter: the letter is not written again.
        before = letter.read_bytes()
        again = ingest_record(self.vault, self.archive, f"family-letters:{LETTER_ID}",
                              "Another memo")
        self.assertEqual(again.returncode, 0, again.stderr)
        self.assertEqual(letter.read_bytes(), before)
        self.assertIn(f"  letter {LETTER_ID} already filed:", again.stdout)
        second = front(self.vault / intake.INGESTED_RE.search(again.stdout).group(1))
        self.assertEqual(second["cites"], [fl.source_id(LETTER_ID)])
        letters = sorted(p.name for p in (self.vault / "sources" / "letters").iterdir())
        self.assertEqual(letters, ["orchard-box-1980--aunt-wren.md"])

    def test_no_archive_files_the_memo_exactly_as_before(self):
        done = ingest_record(self.vault, None, f"family-letters:{LETTER_ID}", "No archive memo")
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn(f"! letter {LETTER_ID} not filed (missing_dir)", done.stdout)
        self.assertFalse((self.vault / "sources" / "letters").exists())
        memo = front(self.vault / intake.INGESTED_RE.search(done.stdout).group(1))
        self.assertNotIn("cites", memo)
        self.assertEqual(memo["type"], "external_record")

    def test_intake_letter_files_with_no_memo_and_links_the_memos_that_cite_it(self):
        # A memo filed before the archive was here (or before v404): no cites.
        old = ingest_record(self.vault, None, f"family-letters:{LETTER_ID},{OTHER_ID}",
                            "Old memo")
        memo_path = self.vault / intake.INGESTED_RE.search(old.stdout).group(1)
        body_before = memo_path.read_text(encoding="utf-8").split("\n---\n", 1)[1]
        run = subprocess.run(
            [sys.executable, str(SYSTEM / "intake.py"), "letter", LETTER_ID,
             f"family-letters:{OTHER_ID}", "--no-commit"],
            capture_output=True, text=True, cwd=str(self.vault),
            env=env_for(self.vault, self.archive))
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        self.assertTrue((self.vault / fl.source_relpath(LETTER_ID)).is_file())
        card = front(self.vault / fl.source_relpath(OTHER_ID))
        # Month precision: the month lives in date_edtf; no ISO `date` is
        # invented, and captured_at is the filing time, never a made-up day.
        self.assertEqual(card["date_edtf"], "1985-12")
        self.assertNotIn("date", card)
        self.assertEqual(card["captured_at"], card["filed_at"])
        self.assertEqual(front(memo_path)["cites"],
                         [fl.source_id(LETTER_ID), fl.source_id(OTHER_ID)])
        self.assertEqual(memo_path.read_text(encoding="utf-8").split("\n---\n", 1)[1], body_before)
        self.assertIn("intake: letters done (written, not committed)", run.stdout)
        # Nothing about an immutable source changed: lint finds no hash error.
        lint = subprocess.run(
            [sys.executable, "-c",
             "import source_integrity as si; f=si.lint_records(si.scan_sources());"
             "print([x['type'] for x in f if x['severity']=='error'])"],
            capture_output=True, text=True, cwd=str(SYSTEM), env=env_for(self.vault, self.archive))
        self.assertEqual(lint.stdout.strip(), "[]", lint.stderr)
        # Re-run: nothing new.
        rerun = subprocess.run(
            [sys.executable, str(SYSTEM / "intake.py"), "letter", LETTER_ID, "--no-commit"],
            capture_output=True, text=True, cwd=str(self.vault),
            env=env_for(self.vault, self.archive))
        self.assertEqual(rerun.returncode, 0, rerun.stderr)
        self.assertIn("intake: letters done (nothing new)", rerun.stdout)

    def test_intake_letter_says_one_line_for_a_missing_letter_and_exits_1(self):
        run = subprocess.run(
            [sys.executable, str(SYSTEM / "intake.py"), "letter", "orchard-box-1980/nope",
             "--no-commit"],
            capture_output=True, text=True, cwd=str(self.vault),
            env=env_for(self.vault, self.archive))
        self.assertEqual(run.returncode, 1)
        self.assertIn("letter orchard-box-1980/nope not filed (missing_letter)", run.stdout)
        self.assertNotIn("Traceback", run.stderr)


#: Lifehug Cloud's vault validator (lifehug-platform
#: `services/api/app/vault_safety/validator.py`): an id key outside this
#: pattern is `INVALID_ID` (hard_reject), a date-named key that is not ISO is
#: `INVALID_DATE` (manual_review) — and either verdict stops the vault being
#: served. A letter source must pass both.
PLATFORM_ID_KEYS = ("id", "source_id", "question_id")
PLATFORM_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9:._-]{0,127}$")
PLATFORM_DATE_KEY_RE = re.compile(r"(^date$|^created$|^updated$|^answered$|_date$|_at$)")


class PlatformValidatorTests(unittest.TestCase):
    def assert_platform_safe(self, header_text: str, letter_id: str):
        from datetime import date, datetime  # noqa: PLC0415

        header, body = fl.parse_header(header_text)
        _rel, content = fl.render_source({"id": letter_id, "header": header, "body": body},
                                         filed_at=NOW)
        meta = front_of(content)
        for key, value in meta.items():
            if key.lower() in PLATFORM_ID_KEYS:
                self.assertRegex(value, PLATFORM_ID_RE, key)
            elif PLATFORM_DATE_KEY_RE.search(key.lower()) and value not in (None, ""):
                try:
                    datetime.fromisoformat(str(value).replace("Z", "+00:00"))
                except ValueError:
                    date.fromisoformat(str(value))  # raises: INVALID_DATE

    def test_a_letter_source_is_one_the_hosted_validator_serves(self):
        self.assert_platform_safe(TRANSCRIPT, LETTER_ID)
        self.assert_platform_safe(CARD, OTHER_ID)
        self.assert_platform_safe(CARD.replace("date: '1985-12'", "date: '1985'").replace(
            "date_precision: month", "date_precision: year"), OTHER_ID)
        self.assert_platform_safe(CARD.replace("date: '1985-12'", "date: null").replace(
            "date_precision: month", "date_precision: unknown"), OTHER_ID)


def front_of(content: str) -> dict:
    from lifehug_core import split_frontmatter  # noqa: PLC0415

    return split_frontmatter(content)[0]


class LetterLinesRunner(FakeRunner):
    def lifehug(self, *args, stdin=None):
        if args[0] == "ingest-story":
            self.calls.append(list(args))
            return intake.Result(0, (
                f"✓ Filed letter {LETTER_ID}: {fl.source_relpath(LETTER_ID)}\n"
                f"! letter {OTHER_ID} not filed (missing_letter): letter {OTHER_ID} not found in /x\n"
                "✓ Ingested third-party record (r): sources/manual/2026-10-06-memo.md\n"))
        return super().lifehug(*args, stdin=stdin)


class IntakeReceiptTests(IntakeCase):
    def test_the_receipt_names_the_letters_on_file_and_the_ones_not_found(self):
        runner = LetterLinesRunner(self.root, ready=True)
        record, _finished = intake.start(
            self.root, MEMO, kind="record", title="memo",
            record_ref=f"family-letters:{LETTER_ID},{OTHER_ID}", runner=runner,
            say=self.say, now=NOW, no_push=True, read=False)
        filing = record["phases"]["filing"]
        self.assertEqual(filing["source_path"], "sources/manual/2026-10-06-memo.md")
        self.assertEqual(filing["letters_filed"],
                         [{"id": LETTER_ID, "path": fl.source_relpath(LETTER_ID)}])
        self.assertEqual(filing["letters_unresolved"], [{"id": OTHER_ID, "reason": "missing_letter"}])
        report = intake.render_report(record)
        self.assertIn(f"letters    on file: {LETTER_ID} · not found: {OTHER_ID}", report)
        self.assertTrue(any("the memo is filed without it" in line for line in self.lines))


class ClassificationTests(unittest.TestCase):
    META = {"type": "letter", "source_id": "letters:orchard-box-1980--aunt-wren", "date": "1983-04-11",
            "date_precision": "day", "date_text": "Mon 11",
            "from": "Aunt Wren (signed 'Wren + Bo')", "to": "Ivy, Corin and the little ones",
            "summary": "Aunt Wren thanks Ivy for pictures of little Pell."}
    REV = "sha256:" + "a" * 64

    def claims(self, capture, event):
        return cc.event_claims(stem="sources-letters-x", event=event, revision=self.REV,
                               source_path=fl.source_relpath(LETTER_ID), capture=capture,
                               now=NOW)

    def test_the_letter_is_a_moment_dated_by_the_letter_on_document_basis(self):
        capture = {"letter": cc.letter_context(self.META)}
        event = cc.letter_event(capture)
        self.assertEqual(event["subject"], self.META["from"])  # the writer; the axis rules decide
        [claim] = self.claims(capture, event)
        value = claim["temporal_value"]
        self.assertEqual(claim["claim_type"], "date")
        self.assertEqual(value["basis"], "document")
        self.assertEqual(value["best"], "1983-04-11")
        self.assertEqual(claim["source_ref"]["source_path"], fl.source_relpath(LETTER_ID))
        self.assertEqual(claim["event_mention"], "Aunt Wren's letter to Ivy, Corin and")
        self.assertEqual(chrono.display_date(value), "11 April 1983 — printed on Mon 11")
        self.assertEqual(chrono.BASIS_WEIGHT[value["basis"]], max(chrono.BASIS_WEIGHT.values()))

    def test_precision_is_the_letters_own(self):
        meta = dict(self.META, date=None, date_edtf="1985-12", date_precision="month")
        capture = {"letter": cc.letter_context(meta)}
        [claim] = self.claims(capture, cc.letter_event(capture))
        self.assertEqual(claim["temporal_value"]["granularity"], "month")
        undated = cc.letter_context(dict(self.META, date=None, date_precision="unknown"))
        self.assertEqual(undated, {})
        self.assertIsNone(cc.letter_event({"letter": undated}))

    def test_only_a_letter_source_gets_a_letter_moment_and_a_response_cannot_spoof_one(self):
        self.assertEqual(cc.letter_context(dict(self.META, type="external_record")), {})
        spoof = {"title": "x", "description": "x", "date": {"stated": "1990"},
                 cc.LETTER_EVENT_MARKER: "letter"}
        [claim] = self.claims({}, spoof)
        self.assertEqual(claim["temporal_value"]["basis"], "stated")


class ManifestTests(unittest.TestCase):
    def test_framework_ships_the_code_and_never_the_letters(self):
        manifest = json.loads((SYSTEM / "version.json").read_text(encoding="utf-8"))
        shipped = set(manifest["framework_files"])
        for name in ("system/family_letters.py", "tests/test_v404_letters_in_the_vault.py"):
            self.assertIn(name, shipped)
        # `sources/letters/` is user data: never shipped, not even a .gitkeep.
        self.assertFalse(any(path.startswith("sources/letters") for path in shipped))
        self.assertGreaterEqual(int(manifest["version"]), 401)


if __name__ == "__main__":
    unittest.main()
