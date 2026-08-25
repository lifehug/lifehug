"""The one path that captures a date from live conversation must actually file.

lifehug#223. `timeline_interaction.place_invocation` took a `description` and
never used it; `lifehug.py timeline-place` requires that description on STDIN
(empty → exit 1); and `conversation_delivery._file_placement` ran the argv with
no ``input=``. So every validated ``placed`` record — a timeline whisper's
answer, a keystone question's answer — exited 1 into a `place_failed`
diagnostic and was silently discarded. The person named a date and the vault
never heard it.

Nothing executed the filing before this file: `grep -rn _file_placement tests/`
was empty, which is exactly why the bug could live end to end. These tests run
the REAL thing — the real host function, the real `lifehug.py` subprocess, a
real temp vault — and then read the date back out of `timeline.timeline_data()`
the way the page does.
"""

from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "system"))
sys.path.insert(0, str(ROOT / "tests"))

import conversation_delivery as cd  # noqa: E402
import timeline as tl  # noqa: E402
import timeline_interaction as ti  # noqa: E402
from tempdirs import root_parent_tmp  # noqa: E402

DESCRIPTION = "the move to Mesa"
SOURCE = "answers/A1.md"
PERIOD = "childhood"
PLACED = {"best": "1984", "earliest": "1984", "latest": "1984",
          "granularity": "year", "confidence": "certain", "basis": "stated",
          "anchors": []}


def timeline_roots(root: Path) -> dict[str, Path]:
    """Every vault root `timeline.py` reads, pointed at a fixture `root`. The
    rebind is all-or-nothing (`timeline.vault_roots`), so a root added there
    fails here loudly instead of quietly reading the real vault."""
    state = root / "state"
    return {
        "CLASSIFICATIONS_DIR": state / "classifications",
        "CONNECTORS_STATE_DIR": state / "connectors",
        "ENTITY_ROSTERS_DIR": state / "entity_rosters",
        "MANUAL_SOURCES_DIR": root / "sources" / "manual",
        "PLACEMENTS_FILE": state / "timeline_placements.json",
        "STATE_DIR": state,
        "WIKI_DIR": root / "wiki",
    }


def build_vault(root: Path) -> None:
    """The minimum vault shape, plus the one classified moment the pin
    binds to and the one period it is placed in."""
    root.mkdir(parents=True)
    (root / "question-bank.md").write_text(
        "# Questions\n\n## A: Origins\n\n- [ ] A1: Test question?\n",
        encoding="utf-8")
    state = root / "state"
    state.mkdir()
    (state / "rotation.json").write_text(json.dumps({
        "version": 1, "current_pass": 1,
        "pass_names": ["skeleton", "depth", "connections", "polish"],
        "last_question_id": None, "last_asked_at": None,
        "questions_asked": 0, "questions_answered": 0,
        "next_question_id": None, "focus_frequency": 4,
    }) + "\n", encoding="utf-8")
    (state / "coverage.json").write_text(json.dumps({
        "version": 1, "last_updated": None, "categories": {},
    }) + "\n", encoding="utf-8")
    answers = root / "answers"
    answers.mkdir()
    (answers / "A1.md").write_text(
        "---\ntitle: A1\nsource_id: answer:A1\ntype: answer\n---\n\n"
        "We moved to Mesa when I was five.\n", encoding="utf-8")
    classifications = state / "classifications"
    classifications.mkdir()
    (classifications / "A1.json").write_text(json.dumps({
        "source_path": SOURCE,
        "time_periods": [],
        # Undated on purpose: the date can only arrive through the filing.
        "events": [{"description": DESCRIPTION, "title": DESCRIPTION}],
    }), encoding="utf-8")
    periods = root / "wiki" / "periods"
    periods.mkdir(parents=True)
    (periods / f"{PERIOD}.md").write_text(
        "---\ntitle: Childhood\nchrono: 1\n---\n\n# Childhood\n",
        encoding="utf-8")


class FilePlacementTests(unittest.TestCase):
    """`conversation_delivery._file_placement`, executed for real."""

    def setUp(self):
        self.tmp = root_parent_tmp(self, ROOT, prefix="lifehug-place-test-")
        self.vault = self.tmp / "vault"
        build_vault(self.vault)
        # The repo's own vault must never be written by this test: the CLI is
        # selected with `--vault-root`, and a regression that lost it would
        # otherwise file the fixture's date into the developer's checkout.
        self.repo_placements = ROOT / "state" / "timeline_placements.json"
        self.repo_before = (self.repo_placements.read_bytes()
                            if self.repo_placements.exists() else None)
        self.addCleanup(self.assert_repo_vault_untouched)
        self.diagnostics: list[tuple] = []
        patch = mock.patch.object(
            cd, "_diagnostic",
            lambda *args, **kwargs: self.diagnostics.append((args, kwargs)))
        patch.start()
        self.addCleanup(patch.stop)

    def assert_repo_vault_untouched(self) -> None:
        after = (self.repo_placements.read_bytes()
                 if self.repo_placements.exists() else None)
        self.assertEqual(after, self.repo_before,
                         "the filing wrote into the repo vault, not the fixture")

    def file_placement(self, **overrides) -> bool:
        item = {"source": SOURCE, "label": DESCRIPTION, "period": PERIOD}
        item.update(overrides.pop("item", {}))
        placed = overrides.pop("placed", ti.validate_placed(PLACED))
        self.assertIsNotNone(placed, "fixture record must validate")
        return cd._file_placement(  # noqa: SLF001
            item, placed, session_id="conversation:test",
            question_id="A1", question_text="When did you move?",
            vault_root=self.vault, **overrides)

    def placements(self) -> list[dict]:
        path = self.vault / "state" / "timeline_placements.json"
        self.assertTrue(path.exists(),
                        "timeline-place wrote no placement store at all")
        return json.loads(path.read_text(encoding="utf-8"))["placements"]

    def test_a_placed_record_files_the_placement_and_the_correction(self):
        """The whole point: a validated date reaches durable storage.

        Before the fix this returned False with a `place_failed` diagnostic —
        the CLI exited 1 on empty stdin because nothing fed it the description.
        """
        self.assertTrue(self.file_placement())
        self.assertEqual(self.diagnostics, [])

        placements = self.placements()
        self.assertEqual(len(placements), 1)
        record = placements[0]
        self.assertEqual(record["source"], SOURCE)
        self.assertEqual(record["description"], DESCRIPTION)
        self.assertEqual(record["period"], PERIOD)
        self.assertEqual(record["date"]["best"], "1984")
        self.assertEqual(record["date"]["basis"], "stated")

        # The pin is display; the CORRECTION is the durable half.
        correction = self.vault / record["correction"]
        self.assertTrue(record["correction"].startswith("sources/corrections/"),
                        record["correction"])
        self.assertTrue(correction.exists(), record["correction"])
        text = correction.read_text(encoding="utf-8")
        self.assertIn(DESCRIPTION, text)
        self.assertIn("1984", text)

    def test_the_filed_date_reaches_the_timeline_read(self):
        """A date that files but never renders would be the same bug wearing a
        different coat, so the proof ends where the person looks: the moment,
        in its period, dated."""
        self.assertTrue(self.file_placement())
        with tl.vault_roots(**timeline_roots(self.vault)):
            data = tl.timeline_data()
        moments = data["event_lineup"][PERIOD]
        self.assertEqual([m["title"] for m in moments], [DESCRIPTION])
        moment = moments[0]
        self.assertEqual(moment["placement"], "manual")
        self.assertIsNotNone(moment["date"], "the moment came back undated")
        self.assertEqual(moment["date"].best, "1984")
        self.assertEqual(moment["date"].basis, "stated")

    def test_a_deferral_files_nothing_and_never_runs_the_cli(self):
        """"I'll find out" is not a date: no argv, no subprocess, no diagnostic."""
        with mock.patch("subprocess.run") as run:
            self.assertFalse(self.file_placement(placed={"deferred": True}))
        run.assert_not_called()
        self.assertEqual(self.diagnostics, [])
        self.assertFalse((self.vault / "state" / "timeline_placements.json").exists())

    def test_a_cli_failure_is_a_diagnostic_and_never_raises(self):
        """The message is already delivered; a failed filing must not raise."""
        with mock.patch("subprocess.run",
                        return_value=subprocess.CompletedProcess([], 1, "", "boom")):
            self.assertFalse(self.file_placement())
        self.assertEqual([args[:2] for args, _ in self.diagnostics],
                         [("timeline_place", "place_failed")])


class TimelinePlaceCliTests(unittest.TestCase):
    """The CLI guard that made the missing stdin fatal stays fatal."""

    def setUp(self):
        self.tmp = root_parent_tmp(self, ROOT, prefix="lifehug-place-cli-")
        self.vault = self.tmp / "vault"
        build_vault(self.vault)

    def run_place(self, stdin_text: str) -> subprocess.CompletedProcess:
        invocation = ti.place_invocation(ti.validate_placed(PLACED), source=SOURCE,
                                         description=DESCRIPTION, period=PERIOD)
        return subprocess.run(  # noqa: S603
            [sys.executable, str(ROOT / "system" / "lifehug.py"),
             "--vault-root", str(self.vault), *invocation.argv],
            input=stdin_text, text=True, capture_output=True, timeout=120)

    def test_an_empty_description_still_fails_loudly(self):
        result = self.run_place("")
        self.assertEqual(result.returncode, 1)
        self.assertIn("description must be provided on stdin", result.stderr)
        self.assertFalse((self.vault / "state" / "timeline_placements.json").exists())

    def test_the_invocations_own_stdin_is_what_the_cli_wants(self):
        """The pair `place_invocation` returns is a WORKING call — the argv it
        builds and the stdin it carries, run together, file the moment."""
        result = self.run_place(
            ti.place_invocation(ti.validate_placed(PLACED), source=SOURCE,
                                description=DESCRIPTION, period=PERIOD).stdin_text)
        self.assertEqual(result.returncode, 0, result.stderr)
        record = json.loads(
            (self.vault / "state" / "timeline_placements.json").read_text(
                encoding="utf-8"))["placements"][0]
        self.assertEqual(record["description"], DESCRIPTION)


if __name__ == "__main__":
    unittest.main()
