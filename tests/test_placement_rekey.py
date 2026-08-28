"""A pin must survive its moment's reclassification (lifehug#276, v253).

A placement's identity is content: ``placement_key(event) =
sha1(f"{source}\\n{description}")[:12]``. The description is not stable —
rewriting descriptions is what ``classify-story`` does every week — so every
reclassification minted a NEW key for the SAME moment and orphaned the pin the
person filed. ``resolve_placements`` had two rungs and neither of them helps:
rung 1 is the exact key, rung 2 (v215, lifehug#229) repairs one frozen
pre-v215 title-vs-description asymmetry. So the row resolved to ``''``, rung 0
of ``place_events`` never fired, the moment rendered UNPLACED, and the pin sat
forever in ``state/timeline_placements.json`` as a stale notice nobody could
act on. The person named a date, the date was on disk, the moment showed as
undated.

E7a (D16 on lifehug/lifehug-platform#686) measured it on one real moment whose
description a later pass rewrote and nothing else changed: the stored pin held
``b8c4b56293ed`` while the live event minted ``86ba74d3770f``. This suite
rebuilds that shape from scratch rather than pinning those two literals — the
defect is the key MOVING, not the particular bytes it moved between.

The fix is a third rung, and a durable one. This file was run in full against
``origin/main`` (v252) before the fix landed: 12 of its 17 cases failed there,
and the 5 that passed are the deliberately-invariant guards (the fixture's own
key really moves; a row with no source is a candidate for nothing; a live key
and a derived key still file; a malformed key is still refused). The two that
matter, measured on the pre-fix tree with the pre-fix API:

* the reclassification itself — stored pin ``36f7b6be7c84``, live event
  ``794f77dcaa7a``, ``resolve_placements`` → ``['']``,
  ``event_lineup[childhood]`` empty and the moment in ``unplaced_events``,
  ``counts["stale_placements"] == 1``. The same shape E7a measured.
* the filing refusal — ``timeline-place --placement-key <dead key>`` exited
  **0** with ``✓ Placed 36f7b6be7c84 in Childhood; durable assertion filed``:
  a pin dead on arrival, announced as a success.

``test_two_moments_of_one_source_are_never_guessed_between`` is a negative that
would pass on a tree with no repair at all, so it proves nothing alone —
``test_removing_the_ambiguity_re_proves_the_repair`` drops the second moment
and watches the SAME row re-key, which is how you know the guard refused
rather than the rung being absent.
"""

from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "system"))
sys.path.insert(0, str(ROOT / "tests"))

import timeline as tl  # noqa: E402
from tempdirs import root_parent_tmp  # noqa: E402

SOURCE = "answers/A1.md"
PERIOD = "childhood"
#: What the classifier said first, and what it says after the rewrite. Same
#: moment, same source, same answer file — only the prose moved.
FIRST = "the move to Mesa"
RECLASSIFIED = "the family's move to Mesa in the winter"
DATE = {"best": "1984", "earliest": "1984", "latest": "1984",
        "granularity": "year", "confidence": "certain", "basis": "stated",
        "anchors": []}


def timeline_roots(root: Path) -> dict[str, Path]:
    """Every vault root `timeline.py` reads, pointed at a fixture `root`."""
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
    """The minimum vault shape: one answer, one classified moment, one period.

    The moment's title IS its description on purpose, so `legacy_title_key` is
    `""` and rung 2 cannot quietly do rung 3's work — every join in this file
    is the rung it claims to be.
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
        "events": [{"description": FIRST, "title": FIRST}],
    }), encoding="utf-8")
    periods = root / "wiki" / "periods"
    periods.mkdir(parents=True)
    (periods / f"{PERIOD}.md").write_text(
        "---\ntitle: Childhood\nchrono: 1\n---\n\n# Childhood\n",
        encoding="utf-8")


class VaultCase(unittest.TestCase):
    def setUp(self):
        self.tmp = root_parent_tmp(self, ROOT, prefix="lifehug-rekey-")
        self.vault = self.tmp / "vault"
        build_vault(self.vault)
        self.store = self.vault / "state" / "timeline_placements.json"

    # -- the fixture's own moving parts, stated ---------------------------

    def classify(self, events: list[dict]) -> None:
        """Rewrite what the classifier says about this source."""
        path = self.vault / "state" / "classifications" / "A1.json"
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["events"] = events
        path.write_text(json.dumps(payload), encoding="utf-8")

    def reclassify(self) -> None:
        self.classify([{"description": RECLASSIFIED, "title": RECLASSIFIED}])

    def live_keys(self) -> list[str]:
        with tl.vault_roots(**timeline_roots(self.vault)):
            return [tl.placement_key(event) for event in tl.load_events()]

    def pin_the_moment(self) -> str:
        """File the pin the person made, under the key the moment mints TODAY.
        Returns that key — the one reclassification is about to orphan."""
        keys = self.live_keys()
        self.assertEqual(len(keys), 1, keys)
        with tl.vault_roots(**timeline_roots(self.vault)):
            tl.save_placement(keys[0], SOURCE, FIRST, PERIOD, date=dict(DATE))
        return keys[0]

    def rows(self) -> list[dict]:
        """The store as the PRODUCT reads it — off disk, never recomputed."""
        self.assertTrue(self.store.exists(), "no placement store on disk")
        return json.loads(self.store.read_text(encoding="utf-8"))["placements"]

    def timeline_data(self) -> dict:
        with tl.vault_roots(**timeline_roots(self.vault)):
            return tl.timeline_data()

    def resolve(self) -> list[tuple[dict, str, str]]:
        with tl.vault_roots(**timeline_roots(self.vault)):
            return tl.resolve_placements_with_rung(tl.load_placements(),
                                                   tl.load_events())

    def rekey(self, **kwargs) -> list[dict]:
        with tl.vault_roots(**timeline_roots(self.vault)):
            return tl.rekey_orphaned_placements(**kwargs)

    def diagnostics(self) -> list[dict]:
        with tl.vault_roots(**timeline_roots(self.vault)):
            return tl.placement_orphan_diagnostics(tl.load_placements(),
                                                   tl.load_events())


class ReclassificationRekeyTests(VaultCase):
    """The defect, and the third rung that repairs it."""

    def test_the_fixture_really_moves_the_key(self):
        """Guard on the guard: if reclassification did not change the key,
        every test below would pass for the wrong reason."""
        before = self.pin_the_moment()
        self.reclassify()
        after = self.live_keys()
        self.assertEqual(len(after), 1)
        self.assertNotEqual(before, after[0],
                            "the fixture must actually orphan the pin")
        with tl.vault_roots(**timeline_roots(self.vault)):
            events = tl.load_events()
        self.assertEqual(tl.legacy_title_key(events[0]), "",
                         "rung 2 must have nothing to say here")

    def test_the_pin_survives_a_reclassified_description(self):
        """The read heals immediately: rung 3 joins the orphan to the one live
        moment its source mints, and the moment places, dated, where the
        person put it. Pre-fix this row resolved to `''` and the moment
        rendered in `unplaced_events`."""
        old = self.pin_the_moment()
        self.reclassify()
        new = self.live_keys()[0]
        joined = self.resolve()
        self.assertEqual([(key, rung) for _, key, rung in joined],
                         [(new, tl.PLACEMENT_JOIN_SOURCE_REKEY)])
        data = self.timeline_data()
        moments = data["event_lineup"][PERIOD]
        self.assertEqual([m["description"] for m in moments], [RECLASSIFIED])
        self.assertEqual(moments[0]["placement"], "manual")
        self.assertEqual(moments[0]["date"].best, "1984")
        self.assertEqual(data["unplaced_events"], [])
        self.assertEqual(data["stale_placements"], [])
        self.assertEqual(data["counts"]["stale_placements"], 0)
        self.assertEqual(data["counts"]["placements_rejoined"], 1)
        self.assertEqual(data["counts"]["placements_orphaned_ambiguous"], 0)
        # The READ does not write. The store still holds the dead key until
        # the durable pass runs — stated, so the next test means something.
        self.assertEqual([row["key"] for row in self.rows()], [old])

    def test_the_repair_is_persisted_with_its_provenance(self):
        """A repair that only recomputes proves the substrate is right and
        says nothing about the file the product reads. So: read the file."""
        old = self.pin_the_moment()
        self.reclassify()
        new = self.live_keys()[0]
        rekeyed = self.rekey()
        self.assertEqual([r["key"] for r in rekeyed], [new])
        row = self.rows()[0]
        self.assertEqual(row["key"], new)
        self.assertEqual(row["rekeyed_from"], old)
        self.assertTrue(row["rekeyed_at"], "the repair must say when it ran")
        self.assertEqual(row["description"], FIRST,
                         "what the person pinned is provenance, not identity")

    def test_the_rekeyed_pin_is_removable_under_its_new_identity(self):
        """The whole point of persisting: every host that posts a key back —
        the viewer's remove button included — names an identity that joins."""
        self.pin_the_moment()
        self.reclassify()
        new = self.live_keys()[0]
        self.rekey()
        with tl.vault_roots(**timeline_roots(self.vault)):
            self.assertTrue(tl.remove_placement(new))
        data = self.timeline_data()
        self.assertEqual(data["event_lineup"][PERIOD], [])
        self.assertEqual([e["description"] for e in data["unplaced_events"]],
                         [RECLASSIFIED])

    def test_the_durable_pass_is_idempotent(self):
        """Replay it and it is a no-op, byte for byte. A runbook step that
        cannot be replayed is a step nobody can safely re-run."""
        self.pin_the_moment()
        self.reclassify()
        self.assertEqual(len(self.rekey()), 1)
        after_first = self.store.read_bytes()
        self.assertEqual(self.rekey(), [])
        self.assertEqual(self.store.read_bytes(), after_first)

    def test_a_dry_run_writes_nothing(self):
        self.pin_the_moment()
        self.reclassify()
        before = self.store.read_bytes()
        self.assertEqual(len(self.rekey(dry_run=True)), 1)
        self.assertEqual(self.store.read_bytes(), before)

    def test_rung_2_still_keeps_its_stored_key(self):
        """v215's contract is untouched: only rung 3 persists. A legacy
        title-keyed orphan renders under the identity the store holds."""
        with tl.vault_roots(**timeline_roots(self.vault)):
            self.classify([{"description": FIRST, "title": "Moving to Mesa"}])
            events = tl.load_events()
            legacy = tl.legacy_title_key(events[0])
            self.assertTrue(legacy)
            tl.save_placement(legacy, SOURCE, "Moving to Mesa", PERIOD)
        joined = self.resolve()
        self.assertEqual([rung for _, _, rung in joined],
                         [tl.PLACEMENT_JOIN_LEGACY_TITLE])
        self.assertEqual(self.rekey(), [])
        self.assertEqual([row["key"] for row in self.rows()], [legacy])


class NeverGuessTests(VaultCase):
    """Zero candidates or several: orphaned, named, and never guessed."""

    def test_two_moments_of_one_source_are_never_guessed_between(self):
        """Filing the person's date onto the wrong moment is worse than
        leaving it stranded — rung 2's rule, and rung 3 keeps it."""
        old = self.pin_the_moment()
        self.classify([{"description": RECLASSIFIED, "title": RECLASSIFIED},
                       {"description": "a different moment entirely",
                        "title": "a different moment entirely"}])
        self.assertEqual([(key, rung) for _, key, rung in self.resolve()],
                         [("", "")])
        diagnostics = self.diagnostics()
        self.assertEqual(len(diagnostics), 1, diagnostics)
        self.assertEqual(diagnostics[0]["diagnostic"],
                         tl.PLACEMENT_ORPHANED_AMBIGUOUS)
        self.assertEqual(diagnostics[0]["key"], old)
        self.assertEqual(diagnostics[0]["source"], SOURCE)
        self.assertEqual(sorted(diagnostics[0]["candidates"]),
                         sorted(self.live_keys()))
        data = self.timeline_data()
        self.assertEqual([row["key"] for row in data["stale_placements"]], [old])
        self.assertEqual(data["counts"]["stale_placements"], 1)
        self.assertEqual(data["counts"]["placements_rejoined"], 0)
        self.assertEqual(data["counts"]["placements_orphaned_ambiguous"], 1)
        # And nothing durable happened: an ambiguous pin is left exactly as
        # the person filed it.
        self.assertEqual(self.rekey(), [])
        self.assertEqual([row["key"] for row in self.rows()], [old])

    def test_removing_the_ambiguity_re_proves_the_repair(self):
        """The negative above passes on a tree with no repair at all, so it
        would prove nothing on its own. Drop the second moment and the SAME
        row re-keys — the guard is what refused, not the absence of a rung."""
        old = self.pin_the_moment()
        self.classify([{"description": RECLASSIFIED, "title": RECLASSIFIED},
                       {"description": "a different moment entirely",
                        "title": "a different moment entirely"}])
        self.assertEqual(self.rekey(), [])
        self.reclassify()
        self.assertEqual([r["rekeyed_from"] for r in self.rekey()], [old])

    def test_a_source_that_mints_no_live_moment_stays_orphaned(self):
        """The v215 shape, unchanged: a pin whose source is gone entirely has
        no candidate to re-key to, and says so by name."""
        with tl.vault_roots(**timeline_roots(self.vault)):
            tl.save_placement("deadbeef0000", "answers/GONE.md",
                              "a moment no classification mentions", PERIOD)
        self.assertEqual([key for _, key, _ in self.resolve()], [""])
        diagnostics = self.diagnostics()
        self.assertEqual([d["diagnostic"] for d in diagnostics],
                         [tl.PLACEMENT_ORPHANED_AMBIGUOUS])
        self.assertEqual(diagnostics[0]["candidates"], [])
        self.assertEqual(self.rekey(), [])
        data = self.timeline_data()
        self.assertEqual(data["counts"]["stale_placements"], 1)
        self.assertEqual(data["counts"]["placements_rejoined"], 0)

    def test_a_row_with_no_source_is_not_a_candidate_for_anything(self):
        """Rung 3 joins on the row's OWN source. A row that carries none —
        a hand-written store, a host that posted only a key — must not fall
        into some other source's single live moment."""
        with tl.vault_roots(**timeline_roots(self.vault)):
            events = tl.load_events()
            self.assertEqual(
                [key for _, key in tl.resolve_placements(
                    {"placements": [{"key": "ffffffffffff", "period": PERIOD}]},
                    events)],
                [""])


class PlacementKeyLivenessTests(VaultCase):
    """`timeline-place` refuses an identity nothing can join. Fail LOUD."""

    def place(self, *extra: str, stdin: str = FIRST) -> subprocess.CompletedProcess:
        return subprocess.run(  # noqa: S603
            [sys.executable, str(ROOT / "system" / "lifehug.py"),
             "--vault-root", str(self.vault), "timeline-place", SOURCE,
             "--period", PERIOD, *extra],
            input=stdin, text=True, capture_output=True, timeout=180)

    def test_a_live_placement_key_still_files(self):
        key = self.live_keys()[0]
        result = self.place("--placement-key", key)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual([row["key"] for row in self.rows()], [key])

    def test_a_dead_placement_key_is_refused_at_filing(self):
        """The key of a moment that no longer mints it — exactly what a host
        holding a stale timeline row would post. Pre-fix: exit 0, a correction
        filed, and a pin written that renders nowhere (lifehug#228's shape)."""
        stale = self.live_keys()[0]
        self.reclassify()
        result = self.place("--placement-key", stale)
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn("placement_key_not_live", result.stderr)
        self.assertIn(stale, result.stderr)
        self.assertFalse(self.store.exists(), "a refused filing wrote a pin")

    def test_the_refusal_happens_before_anything_durable(self):
        """No correction source, no pin: a refused call leaves the vault the
        way it found it."""
        stale = self.live_keys()[0]
        self.reclassify()
        answer = (self.vault / "answers" / "A1.md").read_bytes()
        self.assertEqual(self.place("--placement-key", stale).returncode, 1)
        self.assertFalse(self.store.exists(), "a refused filing wrote a pin")
        self.assertEqual(sorted(p.name for p in (self.vault / "sources").rglob("*")
                                if p.is_file()), [],
                         "a refused filing filed a durable correction source")
        self.assertEqual((self.vault / "answers" / "A1.md").read_bytes(), answer)

    def test_a_malformed_key_is_still_refused_loudly(self):
        result = self.place("--placement-key", "not-a-key")
        self.assertEqual(result.returncode, 1)
        self.assertIn("--placement-key must be 12 hex", result.stderr)
        self.assertFalse(self.store.exists())

    def test_a_derived_key_is_deliberately_not_checked(self):
        """v213-shaped filings (no flag) still mint from source+description
        and still file — the repair rungs are what rejoin them. Narrowing the
        refusal to the explicit flag is the deliberate scope."""
        result = self.place(stdin="Moving to Mesa")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(self.rows()), 1)


class WeeklyPinMaintenanceTests(VaultCase):
    """`timeline-retire` is the seat: it runs right after `classify-story`."""

    def test_the_weekly_pass_heals_the_store(self):
        old = self.pin_the_moment()
        self.reclassify()
        new = self.live_keys()[0]
        result = subprocess.run(  # noqa: S603
            [sys.executable, str(ROOT / "system" / "lifehug.py"),
             "--vault-root", str(self.vault), "timeline-retire"],
            text=True, capture_output=True, timeout=180)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(f"{old} → {new}", result.stdout)
        self.assertEqual([row["key"] for row in self.rows()], [new])


if __name__ == "__main__":
    unittest.main()
