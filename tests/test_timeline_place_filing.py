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

lifehug#228 (v215) is the SECOND half of the same bug. The v213 fix made the
filing exit 0; identity was still minted two different ways. `placement_key`
hashes `source + "\n" + description`, and that is what `place_events` joins on
— but the live conversational lane passed the unknown's LABEL as the
description, and since v195 a moment unknown's label is the event's TITLE. So
a filed placement landed in `stale_placements` and rendered nowhere: exit 0,
a green suite, and the date the person named silently gone. The v213 tests
could not see it because their fixture's title and description are the same
string. `TitleKeyedPlacementTests` below makes them differ, which is the whole
of the defect.
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
#: The event's own TITLE — deliberately NOT the description. Every pre-v215
#: conversational mint hashed this string; the join hashes the description.
TITLE = "Moving to Mesa"
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


def build_vault(root: Path, *, title: str = DESCRIPTION) -> None:
    """The minimum vault shape, plus the one classified moment the pin
    binds to and the one period it is placed in.

    `title` defaults to the description (the v213 shape, where the two recipes
    happened to agree); `TITLE` gives the real one, where they do not.
    """
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
        "events": [{"description": DESCRIPTION, "title": title}],
    }), encoding="utf-8")
    periods = root / "wiki" / "periods"
    periods.mkdir(parents=True)
    (periods / f"{PERIOD}.md").write_text(
        "---\ntitle: Childhood\nchrono: 1\n---\n\n# Childhood\n",
        encoding="utf-8")


def reclassified(vault: Path) -> None:
    """Stand in for the reclassification the stale-first batch performs.

    v237 (O-C) withholds a source's classification from every derived reader
    the moment a correction marks it stale — and `timeline-place` files a
    correction as its own durable half, so a test that places a date and reads
    the Timeline in the same breath is reading it BEFORE the batch has run.
    Every test that calls this is about placement IDENTITY (lifehug#228 / v213
    / v215), not about the currency gate, and each would otherwise be
    re-purposed into a proof of something it was never written to say.

    The product-level collision this papers over in THESE tests — placing a
    date withholds the moment you just placed until a model re-derives it — is
    real, is NOT resolved here, and is pinned as its own named test in
    `tests/test_classify_story_current.py::PlacementWithholdsItsOwnMomentTests`
    and reported against `docs/pr-specs/eras-o-c-stale-first-cursor.md`.
    """
    directory = vault / "state" / "classifications"
    for path in sorted(directory.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.pop("stale", None) is None:
            continue
        data.pop("stale_reason", None)
        data.pop("stale_at", None)
        path.write_text(json.dumps(data), encoding="utf-8")


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
        reclassified(self.vault)
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


class TitleKeyedPlacementTests(unittest.TestCase):
    """lifehug#228: the mint and the join must be ONE key.

    Every test here runs on a vault whose moment has a title that is NOT its
    description — the shape the v213 tests could not express, and the only
    shape in which the defect is visible.
    """

    def setUp(self):
        self.tmp = root_parent_tmp(self, ROOT, prefix="lifehug-place-key-")
        self.vault = self.tmp / "vault"
        build_vault(self.vault, title=TITLE)
        self.diagnostics: list[tuple] = []
        patch = mock.patch.object(
            cd, "_diagnostic",
            lambda *args, **kwargs: self.diagnostics.append((args, kwargs)))
        patch.start()
        self.addCleanup(patch.stop)

    def timeline_data(self) -> dict:
        reclassified(self.vault)
        with tl.vault_roots(**timeline_roots(self.vault)):
            return tl.timeline_data()

    def the_moments_unknown(self) -> dict:
        """The REAL unknown row for the fixture's undated moment — the thing a
        host hands the conversation as its timeline item."""
        rows = [row for row in self.timeline_data()["unknowns"]
                if row.get("kind") == "moment"]
        self.assertEqual(len(rows), 1, rows)
        # The fixture moment belongs to no era yet, so its row carries no
        # `period` — the host supplies the era the person named, exactly as
        # the viewer's own placement form does. Identity is the point here.
        return dict(rows[0], period=PERIOD)

    def live_key(self) -> str:
        reclassified(self.vault)
        with tl.vault_roots(**timeline_roots(self.vault)):
            events = tl.load_events()
        self.assertEqual(len(events), 1)
        return tl.placement_key(events[0])

    def placements(self) -> list[dict]:
        path = self.vault / "state" / "timeline_placements.json"
        self.assertTrue(path.exists(), "timeline-place wrote no placement store")
        return json.loads(path.read_text(encoding="utf-8"))["placements"]

    def file_from(self, item: dict) -> bool:
        return cd._file_placement(  # noqa: SLF001
            item, ti.validate_placed(PLACED), session_id="conversation:test",
            question_id="A1", question_text="When did you move?",
            vault_root=self.vault)

    # -- the mint ---------------------------------------------------------

    def test_the_unknown_row_carries_its_own_events_placement_key(self):
        """Identity is minted where the moment is known. `label` is what the
        person reads; it was never allowed to be the key."""
        row = self.the_moments_unknown()
        self.assertEqual(row["label"], TITLE)
        self.assertEqual(row["placement_key"], self.live_key())
        self.assertNotEqual(
            row["placement_key"],
            tl.placement_key({"source": SOURCE, "description": TITLE}),
            "the fixture must have a title that keys differently — otherwise "
            "this whole class proves nothing")

    def test_a_conversational_placement_files_under_the_joining_key(self):
        """The bug, end to end: file the real unknown row's answer through the
        real host and the real CLI, and the key on disk is the key the join
        computes."""
        self.assertTrue(self.file_from(self.the_moments_unknown()))
        self.assertEqual(self.diagnostics, [])
        record = self.placements()[0]
        self.assertEqual(record["key"], self.live_key())
        self.assertEqual(record["description"], TITLE,
                         "the description stays human-facing — it is not identity")

    def test_the_conversational_placement_renders(self):
        """Where the person looks: the moment, in its period, dated — and
        nothing stranded. Before v215 this landed in `stale_placements` with
        exit 0 and rendered nowhere."""
        self.assertTrue(self.file_from(self.the_moments_unknown()))
        data = self.timeline_data()
        moments = data["event_lineup"][PERIOD]
        self.assertEqual([m["title"] for m in moments], [TITLE])
        self.assertEqual(moments[0]["placement"], "manual")
        self.assertEqual(moments[0]["date"].best, "1984")
        self.assertEqual(data["stale_placements"], [])
        self.assertEqual(data["counts"]["stale_placements"], 0)
        self.assertEqual(data["counts"]["placements_rejoined"], 0)

    def test_the_cli_stores_the_given_key_verbatim(self):
        """`--placement-key` is identity travelling whole — the CLI stores it,
        it does not re-derive it from the description it was handed."""
        invocation = ti.place_invocation(
            ti.validate_placed(PLACED), source=SOURCE, description=TITLE,
            period=PERIOD, placement_key=self.live_key())
        self.assertIn("--placement-key", invocation.argv)
        result = subprocess.run(  # noqa: S603
            [sys.executable, str(ROOT / "system" / "lifehug.py"),
             "--vault-root", str(self.vault), *invocation.argv],
            input=invocation.stdin_text, text=True, capture_output=True, timeout=120)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.placements()[0]["key"], self.live_key())

    def test_a_malformed_key_is_refused_loudly(self):
        """A key that is not a key is a failed call, never a quiet re-derive."""
        result = subprocess.run(  # noqa: S603
            [sys.executable, str(ROOT / "system" / "lifehug.py"),
             "--vault-root", str(self.vault), "timeline-place", SOURCE,
             "--period", PERIOD, "--placement-key", "not-a-key"],
            input=TITLE, text=True, capture_output=True, timeout=120)
        self.assertEqual(result.returncode, 1)
        self.assertIn("--placement-key must be 12 hex", result.stderr)
        self.assertFalse((self.vault / "state" / "timeline_placements.json").exists())

    # -- the repair -------------------------------------------------------

    def file_a_v213_shaped_orphan(self) -> str:
        """Exactly what v213 wrote: no `--placement-key`, and the TITLE on
        stdin as the description. Returns the orphaned key it minted."""
        result = subprocess.run(  # noqa: S603
            [sys.executable, str(ROOT / "system" / "lifehug.py"),
             "--vault-root", str(self.vault), "timeline-place", SOURCE,
             "--period", PERIOD, "--date", "1984", "--basis", "stated"],
            input=TITLE, text=True, capture_output=True, timeout=120)
        self.assertEqual(result.returncode, 0, result.stderr)
        key = self.placements()[0]["key"]
        self.assertNotEqual(key, self.live_key(), "fixture must actually orphan")
        return key

    def test_a_v213_orphan_rejoins_its_event_at_compile(self):
        """The migration, and it is a READ: no state file, no model call, no
        rewrite of the store. The pin the person already made starts working."""
        orphan = self.file_a_v213_shaped_orphan()
        data = self.timeline_data()
        moments = data["event_lineup"][PERIOD]
        self.assertEqual([m["title"] for m in moments], [TITLE])
        self.assertEqual(moments[0]["placement"], "manual")
        self.assertEqual(moments[0]["date"].best, "1984")
        self.assertEqual(data["stale_placements"], [])
        self.assertEqual(data["counts"]["placements_rejoined"], 1)
        # The stored identity is untouched, so `remove` still names it.
        self.assertEqual(self.placements()[0]["key"], orphan)
        self.assertEqual(moments[0]["placement_key"], orphan)

    def test_a_rejoined_pin_is_still_removable(self):
        """A repaired pin unplaces under the key the store holds — the key the
        page's own remove button posts."""
        orphan = self.file_a_v213_shaped_orphan()
        self.assertEqual(self.timeline_data()["event_lineup"][PERIOD][0]["placement_key"],
                         orphan)
        reclassified(self.vault)
        with tl.vault_roots(**timeline_roots(self.vault)):
            self.assertTrue(tl.remove_placement(orphan))
        data = self.timeline_data()
        self.assertEqual(data["event_lineup"][PERIOD], [])
        self.assertEqual([e["title"] for e in data["unplaced_events"]], [TITLE])
        self.assertEqual(data["stale_placements"], [])

    def test_the_repair_never_guesses_between_two_events(self):
        """Two live moments sharing one legacy key resolve NEITHER. An
        ambiguous repair that picked one would file the person's date onto the
        wrong moment, which is worse than leaving it stranded."""
        orphan = self.file_a_v213_shaped_orphan()
        classification = self.vault / "state" / "classifications" / "A1.json"
        payload = json.loads(classification.read_text(encoding="utf-8"))
        payload["events"].append({"description": "a different moment entirely",
                                  "title": TITLE})
        classification.write_text(json.dumps(payload), encoding="utf-8")
        data = self.timeline_data()
        self.assertEqual([row["key"] for row in data["stale_placements"]], [orphan])
        self.assertEqual(data["counts"]["stale_placements"], 1)
        self.assertEqual(data["counts"]["placements_rejoined"], 0)

    # -- the loud end -----------------------------------------------------

    def test_a_placement_that_joins_nothing_stays_stale_and_is_counted(self):
        """Fail LOUD: a record that still matches no moment after the repair
        keeps surfacing, and `timeline_data()` carries the number a host can
        put in front of the person."""
        with tl.vault_roots(**timeline_roots(self.vault)):
            tl.save_placement("deadbeef0000", "answers/GONE.md",
                              "a moment no classification mentions", PERIOD)
        data = self.timeline_data()
        self.assertEqual([row["key"] for row in data["stale_placements"]],
                         ["deadbeef0000"])
        self.assertEqual(data["counts"]["stale_placements"], 1)
        self.assertEqual(data["counts"]["placements_rejoined"], 0)


class PlacementIdentityTests(unittest.TestCase):
    """`timeline.resolve_placements` — the ONE join, read directly."""

    EVENT = {"source": SOURCE, "description": DESCRIPTION, "title": TITLE}

    def resolve(self, keys: list[str], events: list[dict] | None = None):
        placements = {"placements": [{"key": key, "period": PERIOD} for key in keys]}
        return tl.resolve_placements(placements, events or [self.EVENT])

    def test_a_current_key_joins(self):
        key = tl.placement_key(self.EVENT)
        self.assertEqual([k for _, k in self.resolve([key])], [key])

    def test_a_legacy_title_key_joins(self):
        legacy = tl.placement_key({"source": SOURCE, "description": TITLE})
        self.assertEqual(tl.legacy_title_key(self.EVENT), legacy)
        self.assertEqual([k for _, k in self.resolve([legacy])],
                         [tl.placement_key(self.EVENT)])

    def test_an_unknown_key_joins_nothing(self):
        self.assertEqual([k for _, k in self.resolve(["ffffffffffff"])], [""])

    def test_only_the_first_claimant_of_a_key_wins(self):
        key = tl.placement_key(self.EVENT)
        legacy = tl.legacy_title_key(self.EVENT)
        self.assertEqual([k for _, k in self.resolve([key, legacy])], [key, ""])

    def test_an_event_whose_title_is_its_description_has_no_legacy_key(self):
        """Nothing to repair when the two recipes already agree — and no alias
        that could shadow another moment's real key."""
        self.assertEqual(
            tl.legacy_title_key({"source": SOURCE, "description": DESCRIPTION,
                                 "title": DESCRIPTION}), "")


if __name__ == "__main__":
    unittest.main()
