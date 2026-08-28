"""A placement records the DATE, never the era (v251).

Found by the E7a rehearsal. `timeline-place` files the durable half of a
placement as a `--role placement` correction (v103, narrowed by v237/O-C2),
and the body it filed read:

    “Charlee writes … Father's Day letter to Dave” happened during My 40s,
    May 2022

One sentence carrying both a date and an ERA — the sentence shape of the
2026-08-25 defect, one era to the right. Two authorities say it must not:

* **v244 / O-C2** (`docs/pr-specs/eras-o-c2-placement-keeps-its-moment.md`):
  a placement is *"a date DECISION about a moment the person accepts"*, not an
  assertion about the era it lands in.
* **The Eras design §5.1**: the period is DERIVED from the date by frame
  arithmetic. `My 40s` is not something the person said; it is what the
  arithmetic computed from `May 2022`.

The body is durable TWICE. It is the immutable payload of a vault source
record, and `classify_story.corrections_for` re-injects it into the next
classification prompt under the heading *"LATER CORRECTIONS (authoritative —
these OVERRIDE the story text above)"*. So the era prose does not merely sit
in the archive: it steers the next reclassification, with the same authority
as the date, and a later correction to the frame arithmetic cannot reach it —
prose in an immutable record is not a claim anything can supersede.

The fix is one definition — `timeline.placement_assertion` — and these tests
are its negative half: the era label appears in `state/timeline_placements.json`
(where rung 0 reads it) and NOWHERE in the prose.
"""

from __future__ import annotations

import io
import json
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "system"))
sys.path.insert(0, str(ROOT / "tests"))

import chronology as chrono  # noqa: E402
import classify_story as cs  # noqa: E402
import lifehug  # noqa: E402
import timeline as tl  # noqa: E402
from tempdirs import root_parent_tmp  # noqa: E402

#: The era the E7a rehearsal actually filed: an AGE FRAME, whose name is pure
#: arithmetic over the date beside it. `40s` is asserted separately because
#: "My 40s" surviving as "40s" would be the same defect wearing a shorter coat.
ERA_SLUG = "my-40s"
ERA_LABEL = "My 40s"
ERA_FRAGMENTS = (ERA_LABEL, "40s", "during")

DESCRIPTION = "Charlee writes her Father's Day letter to Dave"
SOURCE = "answers/A1.md"
DATE = "2022-05"
DATE_PROSE = "May 2022"


def build_vault(root: Path) -> None:
    """The minimum vault `timeline-place` needs, with the era named as the
    rehearsal named it."""
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
        "Charlee wrote me a letter that Father's Day.\n", encoding="utf-8")
    classifications = state / "classifications"
    classifications.mkdir()
    (classifications / "A1.json").write_text(json.dumps({
        "source_path": SOURCE,
        "time_periods": [],
        "events": [{"description": DESCRIPTION, "title": DESCRIPTION}],
    }), encoding="utf-8")
    periods = root / "wiki" / "periods"
    periods.mkdir(parents=True)
    (periods / f"{ERA_SLUG}.md").write_text(
        f"---\ntitle: {ERA_LABEL}\nchrono: 5\n---\n\n# {ERA_LABEL}\n",
        encoding="utf-8")


class PlacementAssertionTests(unittest.TestCase):
    """`timeline.placement_assertion` — the ONE definition, read directly."""

    def record(self, edtf: str = DATE, **kwargs):
        record = chrono.parse_edtf(edtf, basis="stated")
        self.assertIsNotNone(record, edtf)
        if kwargs:
            from dataclasses import replace

            record = replace(record, **kwargs)
        return record

    def test_the_body_states_the_date(self):
        body = tl.placement_assertion(DESCRIPTION, date=self.record())
        self.assertIn(DESCRIPTION, body)
        self.assertIn(DATE_PROSE, body)
        self.assertIn("happened", body)

    def test_the_body_names_no_era(self):
        """The defect, stated as a property: the era label cannot be in the
        prose, because the prose has no argument that could put it there."""
        body = tl.placement_assertion(DESCRIPTION, date=self.record())
        for fragment in ERA_FRAGMENTS:
            self.assertNotIn(fragment, body, f"the body still says {fragment!r}")

    def test_the_date_keeps_its_own_granularity(self):
        """"the date at its granularity" — a hedged date stays hedged, and a
        day-precise one keeps its day. The body never sharpens or blurs."""
        for edtf, prose in (("1984", "1984"), ("1984~", "around 1984"),
                            ("198X", "sometime in the 1980s"),
                            ("2001-21", "spring 2001"),
                            ("2010-12-21", "21 December 2010")):
            with self.subTest(edtf=edtf):
                body = tl.placement_assertion(DESCRIPTION, date=self.record(edtf))
                self.assertIn(prose, body)

    def test_anchors_still_say_what_the_date_leans_on(self):
        """The anchor clause is evidence for the DATE — it survives."""
        body = tl.placement_assertion(
            DESCRIPTION, date=self.record(anchors=("the move to Mesa",)))
        self.assertIn("anchored on the move to Mesa", body)

    def test_a_when_hint_that_is_the_date_is_not_said_twice(self):
        """`timeline_interaction.place_invocation` derives `--when-hint` FROM
        the record (`display_date`), so the conversational lane hands the same
        prose in twice. Without the era in front of it, that duplication is
        the whole sentence."""
        body = tl.placement_assertion(DESCRIPTION, date=self.record(),
                                      when_hint=DATE_PROSE)
        self.assertEqual(body.count(DATE_PROSE), 1, body)

    def test_a_when_hint_that_adds_something_is_kept(self):
        body = tl.placement_assertion(DESCRIPTION, date=self.record(),
                                      when_hint="the summer after we moved")
        self.assertIn(DATE_PROSE, body)
        self.assertIn("the summer after we moved", body)

    def test_a_hint_only_placement_states_the_hint(self):
        body = tl.placement_assertion(DESCRIPTION, when_hint="summer of first grade")
        self.assertIn("happened summer of first grade", body)
        for fragment in ERA_FRAGMENTS:
            self.assertNotIn(fragment, body, f"the body still says {fragment!r}")

    def test_a_placement_with_no_date_at_all_asserts_no_date(self):
        """A period-only pin from the viewer's form states no time. It used to
        state the era as fact, which was the only temporal thing it said —
        and it was derived, not said."""
        body = tl.placement_assertion(DESCRIPTION)
        self.assertIn(DESCRIPTION, body)
        self.assertNotIn("happened", body)
        for fragment in ERA_FRAGMENTS:
            self.assertNotIn(fragment, body, f"the body still says {fragment!r}")

    def test_the_description_is_clamped_for_prose(self):
        body = tl.placement_assertion("x" * 400, date=self.record())
        self.assertIn("x" * tl.PLACEMENT_ASSERTION_DESCRIPTION_MAX, body)
        self.assertNotIn("x" * (tl.PLACEMENT_ASSERTION_DESCRIPTION_MAX + 1), body)


class CmdTimelinePlaceBodyTests(unittest.TestCase):
    """The command files exactly what the one definition returns — no host
    re-adds the era on the way out."""

    def setUp(self):
        self.tmp = root_parent_tmp(self, ROOT, prefix="lifehug-place-body-")
        self._orig = tl.PLACEMENTS_FILE
        tl.PLACEMENTS_FILE = self.tmp / "placements.json"
        self.addCleanup(lambda: setattr(tl, "PLACEMENTS_FILE", self._orig))

    def place(self, *, date=DATE, when_hint=""):
        calls: list[tuple] = []

        def fake_run(args, **kwargs):
            calls.append((args, kwargs))
            return subprocess.CompletedProcess(
                args, 0, "✓ Created correction source: sources/corrections/c1.md", "")

        args = type("Args", (), {
            "source": SOURCE, "period": ERA_SLUG, "when_hint": when_hint,
            "note": "", "date": date, "basis": "stated", "anchor": [],
            "placement_key": "",
        })()
        with mock.patch.object(lifehug.subprocess, "run", fake_run), \
                mock.patch.object(tl, "load_periods",
                                  lambda: [{"slug": ERA_SLUG, "name": ERA_LABEL}]), \
                mock.patch("sys.stdin", io.StringIO(DESCRIPTION)), \
                mock.patch("sys.stdout", new_callable=io.StringIO):
            rc = lifehug.cmd_timeline_place(args)
        self.assertEqual(rc, 0)
        self.assertEqual(len(calls), 1)
        return calls[0]

    def test_the_filed_body_is_the_one_definitions_output(self):
        _args, kwargs = self.place()
        self.assertEqual(
            kwargs["input"],
            tl.placement_assertion(DESCRIPTION,
                                   date=chrono.parse_edtf(DATE, basis="stated")),
            "the command composed its own body instead of using the one "
            "definition — that is how the era got back in")

    def test_the_filed_body_names_no_era(self):
        _args, kwargs = self.place()
        for fragment in ERA_FRAGMENTS:
            self.assertNotIn(fragment, kwargs["input"],
                             f"the filed body still says {fragment!r}")
        self.assertIn(DATE_PROSE, kwargs["input"])

    def test_it_still_files_as_a_placement_role_date_correction(self):
        args, _kwargs = self.place()
        self.assertEqual(args[2:4], ["correct", SOURCE])
        self.assertEqual(args[args.index("--kind") + 1], "date")
        self.assertEqual(args[args.index("--role") + 1], "placement")

    def test_the_era_stays_on_the_placement_row(self):
        """Where rung 0 reads it (`timeline.save_placement`'s own contract).
        Removing the prose must not remove the information."""
        self.place()
        row = tl.load_placements()["placements"][0]
        self.assertEqual(row["period"], ERA_SLUG)
        self.assertEqual(row["date"]["best"], "2022-05")
        self.assertEqual(row["correction"], "sources/corrections/c1.md")

    def test_a_dateless_placement_files_a_body_with_no_era(self):
        _args, kwargs = self.place(date=None)
        for fragment in ERA_FRAGMENTS:
            self.assertNotIn(fragment, kwargs["input"],
                             f"the filed body still says {fragment!r}")


class FiledBytesTests(unittest.TestCase):
    """The real CLI, a real temp vault, and the bytes on disk."""

    def setUp(self):
        self.tmp = root_parent_tmp(self, ROOT, prefix="lifehug-place-bytes-")
        self.vault = self.tmp / "vault"
        build_vault(self.vault)

    def run_place(self, *extra: str) -> subprocess.CompletedProcess:
        return subprocess.run(  # noqa: S603
            [sys.executable, str(ROOT / "system" / "lifehug.py"),
             "--vault-root", str(self.vault), "timeline-place", SOURCE,
             "--period", ERA_SLUG, "--date", DATE, "--basis", "stated", *extra],
            input=DESCRIPTION, text=True, capture_output=True, timeout=180)

    def test_the_correction_on_disk_states_the_date_and_no_era(self):
        result = self.run_place()
        self.assertEqual(result.returncode, 0, result.stderr)
        row = json.loads(
            (self.vault / "state" / "timeline_placements.json").read_text(
                encoding="utf-8"))["placements"][0]
        self.assertEqual(row["period"], ERA_SLUG)
        correction = self.vault / row["correction"]
        self.assertTrue(correction.exists(), row["correction"])
        text = correction.read_text(encoding="utf-8")
        self.assertIn(DATE_PROSE, text)
        self.assertIn(DESCRIPTION, text)
        for fragment in ERA_FRAGMENTS:
            self.assertNotIn(fragment, text,
                             f"the durable record still says {fragment!r}")

    def test_the_classification_prompt_injection_carries_no_era(self):
        """The second durability: this body comes BACK, as an authoritative
        correction the next classification is told to obey."""
        result = self.run_place()
        self.assertEqual(result.returncode, 0, result.stderr)
        target = self.vault / "answers" / "A1.md"
        with mock.patch.object(cs, "SOURCES_DIR", self.vault / "sources"), \
                mock.patch.object(cs, "REPO_DIR", self.vault):
            bodies = cs.corrections_for(target)
            block = cs._corrections_block(target)  # noqa: SLF001
        self.assertEqual(len(bodies), 1, bodies)
        self.assertIn(DATE_PROSE, bodies[0])
        self.assertIn("authoritative", block)
        for fragment in ERA_FRAGMENTS:
            self.assertNotIn(fragment, bodies[0],
                             f"the prompt is still told {fragment!r}")
            self.assertNotIn(fragment, block,
                             f"the prompt is still told {fragment!r}")


if __name__ == "__main__":
    unittest.main()
