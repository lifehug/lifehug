"""O-C (v237) — a stale classification leaves every derived reader NOW.

Three things are pinned here, all from
`docs/pr-specs/eras-o-c-stale-first-cursor.md`:

1. `classify_story.is_current` / `current_classification_files()` is the ONE
   reader gate. A classification carrying `stale: true` still exists on disk
   (it is the batch's target and the person's history) but it is an input to
   NOTHING derived — the Timeline, the Mirror, the Book, progress, research,
   focus recommendations and the wiki all skip it the moment it is marked.
2. `--stale-first` + `state/classify_cursor.json`: alphabetical first-N can
   never starve the tail again.
3. A correction document is never a classification TARGET — the source it
   corrects is.

Synthetic data only; NEVER references ~/Workspace/dave.
"""

from __future__ import annotations

import ast
import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SYSTEM = ROOT / "system"
sys.path.insert(0, str(SYSTEM))

import book  # noqa: E402
import classify_story as cs  # noqa: E402
import mirror  # noqa: E402
import progress  # noqa: E402
import question_planner  # noqa: E402
import recommend_focuses  # noqa: E402
import research_expand  # noqa: E402
import serve_wiki  # noqa: E402
import timeline as tl  # noqa: E402
import weekly_report  # noqa: E402


CURRENT = {
    "source_path": "answers/A1.md",
    "classified_at": "2026-08-20T00:00:00Z",
    "events": [{"description": "the current event", "title": "Current Event"}],
    "contradictions": ["the current contradiction"],
    "self_understanding_insights": ["the current insight"],
    "scene_slots": {"what_happened": True},
    "possible_outputs": [{"type": "piece", "description": "the current output"}],
}

STALE = {
    "source_path": "answers/B2.md",
    "classified_at": "2026-08-21T00:00:00Z",
    "stale": True,
    "stale_reason": "correction filed",
    "stale_at": "2026-08-22T00:00:00Z",
    "events": [{"description": "the stale event", "title": "Stale Event"}],
    "contradictions": ["the stale contradiction"],
    "self_understanding_insights": ["the stale insight"],
    "scene_slots": {"what_happened": True},
    "possible_outputs": [{"type": "piece", "description": "the stale output"}],
}


def _write(directory: Path, name: str, data: dict) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


class StaleLeavesEveryReaderTests(unittest.TestCase):
    """Contract test plan bullet 1 — platform T-C-05, layer 1."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(
            lambda: __import__("shutil").rmtree(self.tmp, ignore_errors=True))
        self.clf = self.tmp / "state" / "classifications"
        self.current_path = _write(self.clf, "answers-A1.json", CURRENT)
        self.stale_path = _write(self.clf, "answers-B2.json", STALE)

    def _patch(self, module):
        return mock.patch.object(module, "CLASSIFICATIONS_DIR", self.clf)

    def test_timeline_load_events_skips_stale(self):
        with self._patch(tl):
            descriptions = [e["description"] for e in tl.load_events()]
        self.assertEqual(descriptions, ["the current event"])

    def test_mirror_entries_skip_stale(self):
        with self._patch(mirror), mock.patch.object(
            mirror, "MIRROR_RESPONSES_FILE", self.tmp / "no-responses.json"
        ):
            texts = [e["text"] for e in mirror.load_mirror_entries()]
        self.assertIn("the current contradiction", texts)
        self.assertNotIn("the stale contradiction", texts)
        self.assertNotIn("the stale insight", texts)

    def test_book_scene_slots_skip_stale(self):
        with self._patch(book):
            slots = book._load_scene_slots()
        self.assertIn("A1", slots)
        self.assertNotIn("B2", slots)

    def test_progress_output_suggestions_skip_stale(self):
        with self._patch(progress):
            rows = progress._classifier_output_suggestions()
        descriptions = [desc for _kind, desc in rows]
        self.assertEqual(descriptions, ["the current output"])

    def test_research_self_signals_skip_stale(self):
        with self._patch(research_expand):
            signals = research_expand.load_classified_self_signals()
        joined = " ".join(signals)
        self.assertIn("the current contradiction", joined)
        self.assertNotIn("the stale contradiction", joined)

    def test_recommend_focuses_skips_stale(self):
        with self._patch(recommend_focuses):
            rows = recommend_focuses._load_classifications()
        self.assertEqual([r["source_path"] for r in rows], ["answers/A1.md"])

    def test_serve_wiki_reflection_pool_skips_stale(self):
        with self._patch(serve_wiki):
            pool = serve_wiki._reflection_pool()
        texts = [text for _kind, text, _source in pool]
        self.assertIn("the current contradiction", texts)
        self.assertNotIn("the stale contradiction", texts)

    def test_weekly_report_counts_stale_apart_from_current(self):
        with self._patch(weekly_report):
            lines = weekly_report.classification_section(
                weekly_report._parse_iso("2026-01-01T00:00:00Z"))
        blob = " ".join(lines)
        self.assertIn("1 ✅", blob)
        self.assertIn("stale", blob.lower())

    def test_question_planner_counts_current_only(self):
        sources = self.tmp / "sources"
        (sources / "manual").mkdir(parents=True)
        (sources / "manual" / "one.md").write_text("story", encoding="utf-8")
        (sources / "manual" / "two.md").write_text("story", encoding="utf-8")
        _write(self.clf, "sources-manual-one.json", dict(CURRENT))
        _write(self.clf, "sources-manual-two.json", dict(STALE))
        with mock.patch.object(question_planner, "REPO_DIR", self.tmp), \
                mock.patch.object(question_planner, "SOURCES_DIR", sources), \
                mock.patch.object(question_planner, "CLASSIFICATIONS_DIR", self.clf), \
                mock.patch.object(cs, "REPO_DIR", self.tmp), \
                mock.patch.object(cs, "CLASSIFICATIONS_DIR", self.clf):
            self.assertEqual(question_planner._count_classified("manual"), 1)

    def test_the_stale_file_is_still_on_disk(self):
        """Excluded is not deleted — it is the batch's target and the
        person's history."""
        self.assertTrue(self.stale_path.exists())
        self.assertTrue(json.loads(self.stale_path.read_text())["stale"])

    def test_iterator_reports_what_it_withheld(self):
        cs.reset_withheld_stale()
        list(cs.current_classification_files(self.clf))
        withheld = cs.withheld_stale()
        self.assertEqual([Path(p).name for p in withheld], ["answers-B2.json"])
        self.assertIn("reclassification pending", cs.WITHHELD_STALE_REASON)


class WikiCompileSkipsStaleTests(unittest.TestCase):
    """Contract test plan bullet 2 — the compiled Timeline export carries no
    moment from a stale classification. The wiki reads the Timeline through
    `timeline.vault_roots()`, so this also pins that the ONE gate survives a
    rebind (a reader that read `classify_story`'s own global instead of its
    caller's root would silently split the call across two vaults)."""

    def setUp(self):
        import wiki_compile  # noqa: PLC0415 — heavy; only this class needs it
        self.wc = wiki_compile
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(
            lambda: __import__("shutil").rmtree(self.tmp, ignore_errors=True))
        state = self.tmp / "state"
        self.clf = state / "classifications"
        _write(self.clf, "answers-A1.json", CURRENT)
        _write(self.clf, "answers-B2.json", STALE)
        (self.tmp / "wiki").mkdir(parents=True)
        (self.tmp / "sources" / "manual").mkdir(parents=True)
        for module, name, value in (
            (self.wc, "CLASSIFICATIONS_DIR", self.clf),
            (self.wc, "CONNECTORS_STATE_DIR", state / "connectors"),
            (self.wc, "ENTITY_ROSTERS_DIR", state / "entity_rosters"),
            (self.wc, "MANUAL_SOURCES_DIR", self.tmp / "sources" / "manual"),
            (self.wc, "TIMELINE_PLACEMENTS_FILE", state / "timeline_placements.json"),
            (self.wc, "STATE_DIR", state),
            (self.wc, "WIKI_DIR", self.tmp / "wiki"),
        ):
            patcher = mock.patch.object(module, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_wiki_compile_datable_moments_skip_stale(self):
        self.assertTrue(self.wc.compile_timeline(dry_run=False))
        page = (self.tmp / "wiki" / "timeline.md").read_text(encoding="utf-8")
        self.assertIn("Current Event", page)
        self.assertNotIn("Stale Event", page)

        # Positive control — the moment is absent because it is STALE, not
        # because the fixture never reached the page. Clear the flag and the
        # very same event compiles.
        _write(self.clf, "answers-B2.json",
               {k: v for k, v in STALE.items() if k != "stale"})
        self.assertTrue(self.wc.compile_timeline(dry_run=False))
        page = (self.tmp / "wiki" / "timeline.md").read_text(encoding="utf-8")
        self.assertIn("Stale Event", page)


class NoReaderGlobsClassificationsDirectlyTests(unittest.TestCase):
    """One iterator, so a ninth reader cannot re-glob by accident."""

    def test_no_module_globs_classifications_dir_outside_classify_story(self):
        offenders: list[str] = []
        for path in sorted(SYSTEM.rglob("*.py")):
            if path.name == "classify_story.py":
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if not isinstance(node, ast.Attribute):
                    continue
                if node.attr not in {"glob", "rglob", "iterdir"}:
                    continue
                base = node.value
                if isinstance(base, ast.Name) and base.id == "CLASSIFICATIONS_DIR":
                    offenders.append(
                        f"{path.relative_to(ROOT)}:{node.lineno} "
                        f"CLASSIFICATIONS_DIR.{node.attr}")
        self.assertEqual(offenders, [], "\n".join(offenders))


class OrderTargetsTests(unittest.TestCase):
    """Contract §2 — --stale-first and the durable cursor."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(
            lambda: __import__("shutil").rmtree(self.tmp, ignore_errors=True))
        self.clf = self.tmp / "state" / "classifications"
        self.clf.mkdir(parents=True)
        self.sources = self.tmp / "sources" / "manual"
        self.sources.mkdir(parents=True)
        self.ctx = [
            mock.patch.object(cs, "REPO_DIR", self.tmp),
            mock.patch.object(cs, "CLASSIFICATIONS_DIR", self.clf),
            mock.patch.object(cs, "SOURCES_DIR", self.tmp / "sources"),
            mock.patch.object(cs, "ANSWERS_DIR", self.tmp / "answers"),
            mock.patch.object(
                cs, "CLASSIFY_CURSOR_FILE",
                self.tmp / "state" / "classify_cursor.json"),
        ]
        for patcher in self.ctx:
            patcher.start()
            self.addCleanup(patcher.stop)

    def _source(self, name: str, *, mtime: float | None = None) -> Path:
        path = self.sources / f"{name}.md"
        path.write_text(f"# {name}\n\nbody\n", encoding="utf-8")
        if mtime is not None:
            import os
            os.utime(path, (mtime, mtime))
        return path

    def _classify(self, path: Path, *, stale_at: str | None = None) -> None:
        data = {"source_path": path.name}
        if stale_at is not None:
            data.update({"stale": True, "stale_at": stale_at})
        cs.classification_path(path).write_text(json.dumps(data), encoding="utf-8")

    def test_stale_first_orders_stale_before_unclassified(self):
        a = self._source("a", mtime=1000)
        b = self._source("b", mtime=2000)
        c = self._source("c", mtime=3000)
        d = self._source("d", mtime=4000)
        self._classify(a, stale_at="2026-08-22T00:00:00Z")
        self._classify(b, stale_at="2026-08-01T00:00:00Z")
        self._classify(c)  # current
        ordered = cs.order_targets([a, b, c, d], stale_first=True, cursor="")
        # oldest stale first, then never-classified (newest source first),
        # then everything already current.
        self.assertEqual(ordered, [b, a, d, c])

    def test_stale_first_is_deterministic(self):
        paths = [self._source(n, mtime=1000 + i)
                 for i, n in enumerate("abcde")]
        self._classify(paths[3], stale_at="2026-08-02T00:00:00Z")
        first = cs.order_targets(list(paths), stale_first=True, cursor="")
        second = cs.order_targets(list(reversed(paths)), stale_first=True, cursor="")
        self.assertEqual(first, second)

    def test_cursor_resumes_after_last_filed_key(self):
        paths = [self._source(n) for n in "abcde"]
        run1 = cs.order_targets(list(paths), stale_first=False, cursor="")[:2]
        self.assertEqual(run1, paths[:2])
        run2 = cs.order_targets(
            list(paths), stale_first=False,
            cursor=cs.source_key(run1[-1]))[:2]
        self.assertEqual(run2, paths[2:4])
        run3 = cs.order_targets(
            list(paths), stale_first=False,
            cursor=cs.source_key(run2[-1]))[:2]
        # the tail, then the wrap — the head is never re-run before the tail.
        self.assertEqual(run3, [paths[4], paths[0]])

    def test_stale_ignores_cursor(self):
        paths = [self._source(n, mtime=1000 + i) for i, n in enumerate("abcde")]
        self._classify(paths[0], stale_at="2026-08-02T00:00:00Z")
        ordered = cs.order_targets(
            list(paths), stale_first=True, cursor=cs.source_key(paths[3]))
        self.assertEqual(ordered[0], paths[0])

    def test_missing_or_malformed_cursor_starts_at_head(self):
        paths = [self._source(n) for n in "abc"]
        self.assertEqual(cs.read_classify_cursor(), "")
        cs.CLASSIFY_CURSOR_FILE.parent.mkdir(parents=True, exist_ok=True)
        cs.CLASSIFY_CURSOR_FILE.write_text("{not json", encoding="utf-8")
        self.assertEqual(cs.read_classify_cursor(), "")
        ordered = cs.order_targets(
            list(paths), stale_first=False, cursor=cs.read_classify_cursor())
        self.assertEqual(ordered, paths)

    def test_cursor_round_trips(self):
        path = self._source("a")
        cs.write_classify_cursor(path, run_id="run-1")
        data = json.loads(cs.CLASSIFY_CURSOR_FILE.read_text(encoding="utf-8"))
        self.assertEqual(data["version"], 1)
        self.assertEqual(data["last_source_key"], cs.source_key(path))
        self.assertEqual(data["run_id"], "run-1")
        self.assertTrue(data["updated_at"])
        self.assertEqual(cs.read_classify_cursor(), cs.source_key(path))

    def test_is_classified_meaning_unchanged(self):
        stale = self._source("s")
        current = self._source("c")
        self._classify(stale, stale_at="2026-08-02T00:00:00Z")
        self._classify(current)
        self.assertFalse(cs.is_classified(stale))   # batch: still needs a run
        self.assertFalse(cs.is_current(stale))      # readers: withheld
        self.assertTrue(cs.is_classified(current))
        self.assertTrue(cs.is_current(current))


class CorrectionsAreNeverTargetsTests(unittest.TestCase):
    """Contract §3 — platform T-C-08's package half."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(
            lambda: __import__("shutil").rmtree(self.tmp, ignore_errors=True))
        self.sources = self.tmp / "sources"
        self.answers = self.tmp / "answers"
        (self.sources / "manual").mkdir(parents=True)
        (self.sources / "corrections").mkdir(parents=True)
        self.answers.mkdir(parents=True)
        self.target = self.answers / "Z1.md"
        self.target.write_text("# Z1\n\nThe original telling.\n", encoding="utf-8")
        self.ordinary = self.sources / "manual" / "arizona.md"
        self.ordinary.write_text("---\ntype: manual\n---\n\n# Arizona\n\nbody\n",
                                 encoding="utf-8")
        self.correction = self.sources / "corrections" / "c1.md"
        self.correction.write_text(
            "---\ntype: source_correction\ncorrects_path: answers/Z1.md\n"
            "kind: date\n---\n\n# Correction\n\nIt was 1984, not 1985.\n",
            encoding="utf-8")
        self.answer_ref = self.sources / "corrections" / "c2.md"
        self.answer_ref.write_text(
            "---\ntype: source_correction\ncorrects: answer:Z1\n---\n\n"
            "# Correction\n\nAnother.\n", encoding="utf-8")
        self.misfiled = self.sources / "manual" / "misfiled-correction.md"
        self.misfiled.write_text(
            "---\ntype: source_correction\ncorrects_path: answers/Z1.md\n---\n\n"
            "# Correction\n\nFiled in the wrong folder.\n", encoding="utf-8")
        self.ctx = [
            mock.patch.object(cs, "REPO_DIR", self.tmp),
            mock.patch.object(cs, "SOURCES_DIR", self.sources),
            mock.patch.object(cs, "ANSWERS_DIR", self.answers),
        ]
        for patcher in self.ctx:
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_all_source_files_omits_corrections(self):
        found = cs.all_source_files()
        self.assertIn(self.ordinary, found)
        self.assertIn(self.target, found)
        self.assertNotIn(self.correction, found)
        self.assertNotIn(self.answer_ref, found)
        self.assertNotIn(self.misfiled, found)

    def test_classify_target_for_maps_correction_to_its_source(self):
        self.assertEqual(cs.classify_target_for(self.correction), self.target)
        self.assertEqual(cs.classify_target_for(self.answer_ref), self.target)
        self.assertEqual(cs.classify_target_for(self.misfiled), self.target)
        self.assertIsNone(cs.classify_target_for(self.ordinary))
        self.assertIsNone(cs.classify_target_for(self.target))

    def test_classify_a_correction_exits_non_zero_and_names_the_target(self):
        args = __import__("argparse").Namespace(
            classify=str(self.correction), model="test-model",
            dry_run=True, verbose=False, no_candidates=True)
        err = io.StringIO()
        out = io.StringIO()
        with redirect_stderr(err), redirect_stdout(out):
            rc = cs.cmd_classify(args)
        self.assertEqual(rc, 1)
        message = err.getvalue() + out.getvalue()
        self.assertIn("classify_target_is_correction", message)
        self.assertIn("answers/Z1.md", message)


class PlacementWithholdsItsOwnMomentTests(unittest.TestCase):
    """A REPORTED CONTRACT COLLISION, pinned rather than papered over.

    `timeline-place` files a date CORRECTION as its durable half (v103/v213),
    and `source_integrity.create_linked_source` marks every corrected source's
    classification stale. Under this PR's ruling — "a stale classification is
    excluded from every derived reader immediately" — that means placing a
    date on a moment WITHHOLDS THAT MOMENT from the Timeline until a model
    re-derives its classification. The person's own act of dating a moment is
    what makes it disappear.

    Both halves are ruled behavior and neither was written knowing about the
    other: the exclusion is decision 13 / design §6, and "the proof ends where
    the person looks: the moment, in its period, dated" is lifehug#224's own
    stated guarantee. `docs/pr-specs/eras-o-c-stale-first-cursor.md` names
    `mark_stale` as the source of `stale: true` and does not name this
    consequence, so it is reported as a contract error for the owner to rule
    on — the choices being (a) accept it, with the stale-first batch as the
    repair window, (b) place through the claim substrate's `timeline-move`
    instead of a correction, or (c) narrow `mark_stale` so a correction that
    ADDS a date the classifier never had does not invalidate the reading.

    This test asserts what the code DOES today. It is not an endorsement; when
    the ruling lands, this is the test that has to change, by name.
    """

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(
            lambda: __import__("shutil").rmtree(self.tmp, ignore_errors=True))
        self.clf = self.tmp / "state" / "classifications"
        self.source = self.tmp / "answers" / "A1.md"
        self.source.parent.mkdir(parents=True)
        self.source.write_text("# A1\n\nWe moved to Mesa.\n", encoding="utf-8")
        _write(self.clf, "answers-A1.json", CURRENT)

    def test_marking_a_placed_sources_classification_stale_withholds_its_moment(self):
        with mock.patch.object(cs, "CLASSIFICATIONS_DIR", self.clf), \
                mock.patch.object(cs, "REPO_DIR", self.tmp):
            with mock.patch.object(tl, "CLASSIFICATIONS_DIR", self.clf):
                before = [e["description"] for e in tl.load_events()]
            self.assertEqual(before, ["the current event"])

            # Exactly what filing a placement's correction does.
            self.assertTrue(cs.mark_stale(self.source, reason="correction filed"))

            with mock.patch.object(tl, "CLASSIFICATIONS_DIR", self.clf):
                after = [e["description"] for e in tl.load_events()]
        self.assertEqual(after, [], "the moment survived its own placement — "
                                    "the collision was resolved; update this test")


class VaultContractTests(unittest.TestCase):
    def test_classify_cursor_is_a_declared_state_file(self):
        raw = json.loads(
            (SYSTEM / "vault_contract.json").read_text(encoding="utf-8"))
        entry = raw["data_paths"]["classify_cursor"]
        self.assertEqual(entry["path"], "state/classify_cursor.json")
        self.assertEqual(entry["kind"], "file")
        self.assertFalse(entry["required"])


if __name__ == "__main__":
    unittest.main()
