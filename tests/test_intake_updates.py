"""Intake `--from-updates DIR` (lifehug#469, v399).

Each family-letters proposal file runs as its own record intake with the
WHOLE file as the source body; a flag file writes nothing; done files move to
``applied/`` with the receipt; a re-run on the same folder changes nothing.
Every subprocess is scripted (test_intake.FakeRunner); the cards come from a
REAL `landmark_offer.propose` in a synthetic vault. Synthetic data only.
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SYSTEM = ROOT / "system"
sys.path.insert(0, str(SYSTEM))
sys.path.insert(0, str(ROOT / "tests"))

import intake  # noqa: E402
import intake_updates as iu  # noqa: E402
from tempdirs import root_parent_tmp  # noqa: E402
from test_intake import NOW, FakeRunner, IntakeCase  # noqa: E402

LANDMARK = """# Orchard House: move-in was July 1982, not August

**Vault entry:** residences / "Orchard House"
**Current value:** start 1982-08.
**Proposed value:** start 1982-07 (approximate).

## Supporting quotes

- `box-1982/nan-letter` (1982-07-29): "you like your new home ward".
- `letters/people.md`: conventions.
"""

FLAG = """# Willow Street: an envelope gives a different house number

**Proposed value:** no change yet; flag the number for checking.
**Confidence:** low.

- `box-1979/envelope` (1979-09-17): "34534 AVE. F".
"""

RECORD = """---
kind: record
letters: box-1973/dawn, box-1974/david
---
# Namesake: named after a family friend

**Vault entry:** none yet.
"""

AUTO_NOTHING = """# A cousin's birthday

**Proposed value:** add to the family roster.

- `box-2001/kris` (2001-03-02): "Ashley turns 17".
"""

INDEX = """# Updates

| File | Entry |
|---|---|
| orchard-house.md | residences |
| willow-number.md | residences |
| namesake.md | family |
| cousin.md | family |
"""


class ScriptedUpdatesRunner(FakeRunner):
    """FakeRunner whose reading depends on the file read: the Orchard House
    file reads as the real proposal, every other file reads as nothing."""

    def __init__(self, vault_root, *, proposal):
        super().__init__(vault_root, ready=True, proposal=proposal)
        self.ingested: list[tuple[list[str], str]] = []

    def lifehug(self, *args, stdin=None):
        if args[0] == "ingest-story":
            self.ingested.append((list(args), stdin or ""))
            self.calls.append(list(args))
            slug = f"2026-10-06-u{len(self.ingested)}"
            return intake.Result(0, f"✓ Ingested third-party record (r): sources/manual/{slug}.md\n")
        if args[0] == "landmark-offer" and "--completions" in args:
            self.calls.append(list(args))
            text = Path(args[args.index("--from-file") + 1]).read_text(encoding="utf-8")
            if "Orchard House" in text:
                return intake.Result(0, json.dumps(self.proposal))
            return intake.Result(0, json.dumps({"proposal_id": "lmo:none", "state": "proposed",
                                                "units": []}))
        return super().lifehug(*args, stdin=stdin)


class ParseTests(unittest.TestCase):
    def setUp(self):
        self.dir = root_parent_tmp(self, ROOT, prefix="intake-updates-parse-")

    def write(self, name, text):
        path = Path(self.dir) / name
        path.write_text(text, encoding="utf-8")
        return path

    def test_kind_letters_and_ref_come_from_structure_only(self):
        landmark = iu.parse_update(self.write("orchard-house.md", LANDMARK))
        self.assertEqual(landmark["kind"], "auto")
        self.assertEqual(landmark["letters"], ["box-1982/nan-letter"])  # people.md is not a letter
        self.assertEqual(landmark["record_ref"], "family-letters:box-1982/nan-letter")
        self.assertEqual(landmark["title"], "Orchard House: move-in was July 1982, not August")
        flag = iu.parse_update(self.write("willow-number.md", FLAG))
        self.assertEqual(flag["kind"], "flag")
        self.assertIn("no change yet; flag the number for checking", flag["question"])
        record = iu.parse_update(self.write("namesake.md", RECORD))
        self.assertEqual(record["kind"], "record")
        self.assertEqual(record["letters"], ["box-1973/dawn", "box-1974/david"])
        bare = iu.parse_update(self.write("bare.md", "# Nothing cited\n"))
        self.assertEqual(bare["record_ref"], "family-letters:update/bare")

    def test_files_follow_the_index_and_skip_index_and_applied(self):
        for name, text in (("cousin.md", AUTO_NOTHING), ("orchard-house.md", LANDMARK),
                           ("zz-unlisted.md", AUTO_NOTHING), ("index.md", INDEX)):
            self.write(name, text)
        (Path(self.dir) / "applied").mkdir()
        (Path(self.dir) / "applied" / "old.md").write_text("x", encoding="utf-8")
        names = [p.name for p in iu.update_files(Path(self.dir))]
        self.assertEqual(names, ["orchard-house.md", "cousin.md", "zz-unlisted.md"])

    def test_move_applied_appends_the_receipt_and_is_crash_safe(self):
        path = self.write("orchard-house.md", LANDMARK)
        target = iu.move_applied(path, {"intake_id": "in-1", "at": NOW,
                                        "source_path": "sources/manual/x.md",
                                        "receipt_id": "lmr:abc"})
        self.assertFalse(path.exists())
        body = target.read_text(encoding="utf-8")
        self.assertTrue(body.startswith(LANDMARK.rstrip("\n")))
        self.assertIn("- receipt: lmr:abc (undo: python3 system/lifehug.py landmark-offer --retract lmr:abc)", body)
        # A crash after the write left the original too: the rerun only unlinks it.
        self.write("orchard-house.md", LANDMARK)
        iu.move_applied(path, {"intake_id": "in-2", "at": NOW})
        self.assertFalse(path.exists())
        self.assertEqual(target.read_text(encoding="utf-8"), body)


class FromUpdatesTests(IntakeCase):
    def setUp(self):
        super().setUp()
        self.updates = Path(root_parent_tmp(self, ROOT, prefix="intake-updates-"))
        for name, text in (("orchard-house.md", LANDMARK), ("willow-number.md", FLAG),
                           ("namesake.md", RECORD), ("cousin.md", AUTO_NOTHING),
                           ("index.md", INDEX)):
            (self.updates / name).write_text(text, encoding="utf-8")

    def run_updates(self, runner, **kwargs):
        return intake.run_updates(self.root, self.updates, runner=runner, say=self.say,
                                  now=NOW, no_push=True, **kwargs)

    def test_plan_counts_cards_flags_and_records_and_writes_nothing(self):
        runner = ScriptedUpdatesRunner(self.root, proposal=self.real_proposal(
            evidence="document", evidence_source="family-letters:box-1982/nan-letter"))
        summary = self.run_updates(runner, plan=True)
        self.assertEqual(summary["landmark_cards"], 1)  # the new stay; the duplicate is a line
        self.assertEqual(summary["flag_only"], 1)
        self.assertEqual(summary["record_only"], 2)
        self.assertEqual(summary["applied"], 0)
        self.assertEqual(runner.ingested, [])
        self.assertFalse(any("--apply" in c for c in runner.calls))
        self.assertFalse((self.updates / "applied").exists())
        self.assertIn("  flag-only — writes nothing. Question: Willow Street: an envelope "
                      "gives a different house number — no change yet; flag the number "
                      "for checking.", self.lines)
        # The record file is not read for landmarks at all.
        namesake = next(r for r in summary["files"] if r["file"] == "namesake.md")
        record = intake.load_intake(self.root, namesake["intake_id"])
        self.assertEqual(record["phases"]["reading"]["status"], "skipped")

    def test_each_file_is_filed_whole_as_a_family_record_then_moved_and_rerun_is_inert(self):
        runner = ScriptedUpdatesRunner(self.root, proposal=self.real_proposal(
            evidence="document", evidence_source="family-letters:box-1982/nan-letter"))
        summary = self.run_updates(runner, yes=True)
        # Three files filed (the flag is not), each the WHOLE file, each a family record.
        self.assertEqual(len(runner.ingested), 3)
        bodies = {stdin for _args, stdin in runner.ingested}
        self.assertIn(LANDMARK, bodies)
        self.assertIn(RECORD, bodies)
        for args, _stdin in runner.ingested:
            self.assertEqual(args[args.index("--record") + 1][:15], "family-letters:")
            self.assertEqual(args[args.index("--sensitivity") + 1], "family")
            self.assertEqual(args[args.index("--source") + 1], "family-letters")
        # Reading carried document evidence and the letters as the source.
        reading_call = next(c for c in runner.calls if "--prompts" in c)
        self.assertEqual(reading_call[reading_call.index("--evidence") + 1], "document")
        self.assertEqual(reading_call[reading_call.index("--evidence-source") + 1],
                         "family-letters:box-1982/nan-letter")
        # --yes filed the one NEW unit through the offer road; never landmark-record.
        applies = [c for c in runner.calls if "--apply" in c]
        self.assertEqual(len(applies), 1)
        self.assertFalse(any(c[0] == "landmark-record" for c in runner.calls))
        self.assertEqual(summary["applied"], 3)
        applied = self.updates / "applied" / "orchard-house.md"
        self.assertIn("- receipt: lmr:feed", applied.read_text(encoding="utf-8"))
        self.assertIn("no landmark filed", (self.updates / "applied" / "cousin.md").read_text(encoding="utf-8"))
        self.assertTrue((self.updates / "willow-number.md").is_file())  # the flag stays

        # Re-run on the same folder: nothing filed, nothing moved, the flag asked again.
        before = sorted(p.relative_to(self.updates).as_posix() for p in self.updates.rglob("*"))
        runner2 = ScriptedUpdatesRunner(self.root, proposal=runner.proposal)
        self.lines.clear()
        again = self.run_updates(runner2, yes=True)
        self.assertEqual(runner2.calls, [])
        self.assertEqual(runner2.git_calls, [])
        self.assertEqual(again["flag_only"], 1)
        self.assertEqual(len(again["files"]), 1)
        after = sorted(p.relative_to(self.updates).as_posix() for p in self.updates.rglob("*"))
        self.assertEqual(before, after)

    def test_a_revision_waits_even_under_yes_and_a_rerun_continues_not_restarts(self):
        self.file_stay("Orchard House", "1982-08", "1986-06")
        import landmark_offer as lo
        from test_landmark_offer import ScriptedCall, read_dates, read_unit, reading
        text = LANDMARK
        proposal = lo.propose(text, self.root, call=ScriptedCall(reading=reading(units=[
            read_unit("u1", "residences", "Orchard House", text,
                      record={"label": "Orchard House", "city": "Orchard City"},
                      dates=read_dates("1982-07", "1986-06"))])), now=NOW,
            evidence="document", evidence_source="family-letters:box-1982/nan-letter")
        runner = ScriptedUpdatesRunner(self.root, proposal=proposal)
        summary = self.run_updates(runner, yes=True)
        orchard = next(r for r in summary["files"] if r["file"] == "orchard-house.md")
        self.assertEqual(orchard["counts"]["revision"], 1)
        self.assertFalse(orchard["done"])
        self.assertTrue((self.updates / "orchard-house.md").is_file())  # not applied
        self.assertFalse(any("--apply" in c for c in runner.calls))
        filed = len(runner.ingested)
        # Re-run: the waiting intake is continued, its source is not filed twice.
        again = self.run_updates(runner, yes=True)
        self.assertEqual(len(runner.ingested), filed)
        self.assertEqual(next(r for r in again["files"] if r["file"] == "orchard-house.md")["intake_id"],
                         orchard["intake_id"])
        # The owner's explicit yes on the revision, then the batch finishes it.
        record = intake.load_intake(self.root, orchard["intake_id"])
        unit = record["phases"]["asking"]["cards"][0]["unit_id"]
        intake.Intake(self.root, record, runner=runner, say=self.say).run(units=[unit])
        final = self.run_updates(runner, yes=True)
        self.assertEqual(final["applied"], 1)
        self.assertTrue((self.updates / "applied" / "orchard-house.md").is_file())

    def test_a_missing_folder_is_a_typed_error(self):
        with self.assertRaises(intake.IntakeError):
            intake.run_updates(self.root, self.updates / "nope", runner=FakeRunner(self.root),
                               say=self.say)


if __name__ == "__main__":
    unittest.main()
