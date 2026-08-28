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
4. (O-C2) A PLACEMENT correction does not mark its target stale. Dating a
   moment is a decision about it, not a refutation of the text it was read out
   of — see `PlacementKeepsItsOwnMomentTests` and
   `docs/pr-specs/eras-o-c2-placement-keeps-its-moment.md`.

Synthetic data only; NEVER references ~/Workspace/dave.
"""

from __future__ import annotations

import argparse
import ast
import io
import json
import subprocess
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
import lifehug_core as core  # noqa: E402
import mirror  # noqa: E402
import progress  # noqa: E402
import question_planner  # noqa: E402
import recommend_focuses  # noqa: E402
import research_expand  # noqa: E402
import serve_wiki  # noqa: E402
import source_integrity as si  # noqa: E402
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


class PlacementKeepsItsOwnMomentTests(unittest.TestCase):
    """O-C2 — a placement is a DECISION about a moment, not a refutation of
    the text it was read out of.

    O-C's first draft pinned the opposite, as a reported contract collision:
    `timeline-place` files a date CORRECTION as its durable half (v103/v213),
    `source_integrity.create_linked_source` marked EVERY corrected source's
    classification stale, and this PR's `is_current` gate drops a stale
    classification from every derived reader at once — so the person's own act
    of dating a moment was what made it disappear, until a model re-derived
    it. That contradicts lifehug#224's stated guarantee ("the proof ends where
    the person looks: the moment, in its period, dated") and broke seven of
    lifehug#228's placement-identity tests.

    The ruling taken (option (c) of the three the pin listed, flagged to the
    owner for veto): only a CONTENT correction invalidates a reading. The
    correction record says which it is — `correction_role`, a closed
    vocabulary of exactly two values in `lifehug_core` — and both hosts ask
    the one predicate. Contract:
    `docs/pr-specs/eras-o-c2-placement-keeps-its-moment.md`.

    Every classification path here is derived through
    `cs.classification_path`, never spelled by hand: `classify_stem` slugifies
    (lowercasing) and a hand-written `answers-A1.json` matches on macOS and
    NOT on Linux — which is precisely why the pin this class replaces passed
    locally and failed on CI.
    """

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(
            lambda: __import__("shutil").rmtree(self.tmp, ignore_errors=True))
        self.clf = self.tmp / "state" / "classifications"
        self.source = self.tmp / "answers" / "A1.md"
        self.source.parent.mkdir(parents=True)
        self.source.write_text(
            '---\ntype: "prompted_answer"\nsource_id: "answer:A1"\n---\n\n'
            "# A1\n\nWe moved to Mesa.\n", encoding="utf-8")
        for patcher in (
            mock.patch.object(cs, "CLASSIFICATIONS_DIR", self.clf),
            mock.patch.object(cs, "REPO_DIR", self.tmp),
            mock.patch.object(cs, "ANSWERS_DIR", self.tmp / "answers"),
            mock.patch.object(si, "SOURCES_DIR", self.tmp / "sources"),
            mock.patch.object(si, "ANSWERS_DIR", self.tmp / "answers"),
            mock.patch.object(si, "REPO_DIR", self.tmp),
            mock.patch.object(si, "CORRECTION_SOURCES_DIR",
                              self.tmp / "sources" / "corrections"),
            mock.patch.object(si, "resolve_source_target", lambda _v: self.source),
            mock.patch.object(si, "register_source", lambda _p: {}),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)
        # The classification file the readers read, at the stem the code
        # itself derives.
        self.classification = cs.classification_path(self.source)
        _write(self.clf, self.classification.name, CURRENT)

    def _file(self, *, role, kind="date"):
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            path = si.create_linked_source(
                "answers/A1.md",
                # v251: the shape `timeline.placement_assertion` actually
                # files — the date decision, never the era it lands in.
                "“the move to Mesa” happened 1984",
                source_type="source_correction", title=None,
                source_medium="fix", correction_kind=kind,
                correction_role=role)
        return path, buffer.getvalue()

    def _moments(self):
        with mock.patch.object(tl, "CLASSIFICATIONS_DIR", self.clf):
            return [e["description"] for e in tl.load_events()]

    def _stale_flag(self):
        return json.loads(
            self.classification.read_text(encoding="utf-8")).get("stale")

    def test_a_placement_correction_keeps_the_moment_it_placed(self):
        self.assertEqual(self._moments(), ["the current event"])
        _path, output = self._file(role="placement")
        self.assertIsNone(self._stale_flag())
        self.assertTrue(cs.is_current(self.source))
        self.assertEqual(self._moments(), ["the current event"],
                         "the moment vanished the instant it was dated")
        self.assertIn("stays current", output)

    def test_a_content_correction_still_withholds_its_moment(self):
        """The positive control — the SAME call, the other role. The moment is
        absent because the reading was refuted, not because the fixture never
        reached the reader."""
        self.assertEqual(self._moments(), ["the current event"])
        _path, output = self._file(role="content", kind="factual")
        self.assertTrue(self._stale_flag())
        self.assertFalse(cs.is_current(self.source))
        self.assertEqual(self._moments(), [])
        self.assertIn("for re-classification", output)

    def test_an_unstated_role_is_a_content_correction(self):
        """`correct` and `fix` file no role and must behave exactly as they
        did before O-C2: a person correcting a fact still invalidates the
        reading it was extracted from."""
        self._file(role=None, kind="factual")
        self.assertTrue(self._stale_flag())
        self.assertFalse(cs.is_current(self.source))

    def test_the_correction_records_its_role_durably(self):
        path, _ = self._file(role="placement")
        metadata, _payload = si.split_frontmatter(
            path.read_text(encoding="utf-8"))
        self.assertEqual(metadata["correction_role"], "placement")
        self.assertEqual(metadata["correction_kind"], "date")
        content, _ = self._file(role="content", kind="factual")
        metadata, _payload = si.split_frontmatter(
            content.read_text(encoding="utf-8"))
        self.assertEqual(metadata["correction_role"], "content")

    def test_the_same_words_in_two_roles_are_two_records(self):
        """Linked-source identity is content-addressed, and the role is part of
        what "the same record" means. Byte-identical text filed as a placement
        and as a content correction are two different acts; treating the second
        as an idempotent retry left a record whose frontmatter described the
        other one (found by the test above, before this guard existed)."""
        placement, _ = self._file(role="placement")
        content, _ = self._file(role="content")
        self.assertNotEqual(placement, content)
        for path, role in ((placement, "placement"), (content, "content")):
            metadata, _payload = si.split_frontmatter(
                path.read_text(encoding="utf-8"))
            self.assertEqual(metadata["correction_role"], role)
        # And a genuine retry of either is still one record, not two.
        again, _ = self._file(role="placement")
        self.assertEqual(again, placement)

    def test_an_unknown_role_refuses_and_writes_nothing(self):
        with self.assertRaises(ValueError):
            self._file(role="whenever")
        self.assertIsNone(self._stale_flag())
        self.assertFalse((self.tmp / "sources" / "corrections").exists(),
                         "a refused correction still wrote its record")

    def test_mark_stale_itself_refuses_the_placement_role(self):
        """The seam, not just the caller: the predicate lives in ONE place and
        `mark_stale` asks it, so a future second caller cannot re-file a
        placement as a refutation by forgetting a guard."""
        self.assertFalse(
            cs.mark_stale(self.source, reason="placement filed",
                          correction_role="placement"))
        self.assertIsNone(self._stale_flag())
        self.assertTrue(
            cs.mark_stale(self.source, reason="correction filed",
                          correction_role="content"))
        self.assertTrue(self._stale_flag())

    def test_the_role_vocabulary_is_closed(self):
        self.assertEqual(core.CORRECTION_ROLES, ("content", "placement"))
        self.assertEqual(core.DEFAULT_CORRECTION_ROLE, "content")
        self.assertTrue(core.correction_role_marks_stale(None))
        self.assertTrue(core.correction_role_marks_stale("content"))
        self.assertFalse(core.correction_role_marks_stale("placement"))
        for bad in ("Placement", "placements", "date", "stale", "  ", "0"):
            with self.assertRaises(ValueError, msg=bad):
                core.normalize_correction_role(bad)
        # Surrounding whitespace is tolerated; the value itself is not guessed.
        self.assertEqual(core.normalize_correction_role(" placement "),
                         "placement")

    def test_timeline_place_files_in_the_placement_role(self):
        """The one line of `cmd_timeline_place` that carries the ruling, pinned
        where removing it fails loudly. The end-to-end proof — a real
        subprocess, a real vault, the moment read back at its placed date — is
        `tests/test_timeline_place_filing.py`, whose seven lifehug#228
        identity tests pass unchanged because of this flag."""
        import lifehug as lh  # noqa: PLC0415

        seen = {}

        def fake_run(argv, **kwargs):
            seen["argv"] = argv
            return subprocess.CompletedProcess(argv, 1, "", "")

        args = argparse.Namespace(
            source="answers/A1.md", period="childhood", date=None, basis=None,
            anchor=[], when_hint="", note="", placement_key="")
        with mock.patch.object(lh.sys, "stdin", io.StringIO("the move to Mesa")), \
                mock.patch.object(lh.subprocess, "run", fake_run), \
                mock.patch("timeline.load_periods", return_value=[]), \
                redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            lh.cmd_timeline_place(args)
        argv = seen["argv"]
        self.assertIn("--role", argv)
        self.assertEqual(argv[argv.index("--role") + 1], "placement")
        self.assertEqual(argv[argv.index("--kind") + 1], "date")


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
