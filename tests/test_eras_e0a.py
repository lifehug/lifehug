"""Eras / Timeline phase E0 — O-E0a and O-E0c (lifehug-platform#686).

Contract: ``docs/pr-specs/eras-o-e0-immediate-defects.md``. Design authority:
lifehug-platform ``docs/design/eras.md`` §1, §3.1, §5.4 and ADR 0030.

This file covers ONLY the two parts implemented on this branch:

* **O-E0a** — honest probe selection: `timeline_interaction.choose_probe` /
  `anchor_for_probe` pick an anchor by its RELATIONSHIP to the unknown, never
  by `anchor_rows`' own rank, so a residence or an era unknown never sorts
  itself against the person's own birth (T-E0-01…04).
* **O-E0c** — `period_bound` has no wrong writer: a `period_bound` placement
  is REFUSED loudly, as a typed diagnosable skip, and never misfiled onto
  whatever undated moment happens to sit in that era's lineup (T-E0-06…07).

O-E0b (the owner's birth binds to `self`) and O-E0d
(`source_integrity correct --supersedes`) are a SIBLING PR's scope
(`landmark_projection.py`, `temporal_timeline.py`, `source_integrity.py`,
`classify_story.py`) and their tests (T-BO-01, T-BO-01b, T-E0-05, T-E0-08…12)
land there — this file must never be overwritten wholesale at merge; union
the two files' test classes.

Synthetic data only; NEVER references ~/Workspace/dave.
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
import timeline_interaction as ti  # noqa: E402
from tempdirs import root_parent_tmp  # noqa: E402
from test_timeline_place_filing import build_vault, timeline_roots  # noqa: E402

BIRTH = {"key": "birth", "label": "when you were born", "kind": "birth", "date": "1979"}
SAN_DIEGO = {"key": "san-diego", "label": "the move to San Diego",
             "kind": "residence", "date": "1996"}
THE_YUCAIPA_YEARS = {"key": "the-yucaipa-years", "label": "the Yucaipa years",
                     "kind": "period", "date": "1995/2001"}


# --------------------------------------------------------------------------
# O-E0a — honest probe selection (anchors by relationship, never by rank)
# --------------------------------------------------------------------------


class ProbesByRelationshipTests(unittest.TestCase):
    """T-E0-01…04: a residence or an era never sorts against the birthday;
    a bare moment still may (the over-correction regression guard)."""

    def test_e0_01_residence_unknown_never_names_the_birthday_when_a_residence_exists(self):
        unknown = {"kind": "place_span", "label": "Mexico"}
        probe = ti.choose_probe(unknown, anchors=[BIRTH, SAN_DIEGO])
        self.assertNotIn("born", probe["text"].lower())
        self.assertIn("the move to San Diego", probe["text"])
        self.assertEqual(
            probe["text"],
            "Were you living in Mexico before or after the move to San Diego?",
        )

    def test_e0_02_residence_unknown_with_only_a_birth_anchor_falls_back_unanchored(self):
        unknown = {"kind": "place_span", "label": "Mexico"}
        probe = ti.choose_probe(unknown, anchors=[BIRTH])
        self.assertNotIn("born", probe["text"].lower())
        self.assertEqual(
            probe["text"],
            "When did you live in Mexico — moving in to moving out?",
        )

    def test_e0_03_period_bound_unknown_never_anchors_on_birth_or_on_itself(self):
        # Only eligible anchor in scope is the era's OWN row — excluded, so
        # this also falls back to the unanchored opener, never the birthday.
        unknown = {"kind": "period_bound", "label": "the Yucaipa years",
                  "slug": "the-yucaipa-years", "period": "the-yucaipa-years"}
        probe = ti.choose_probe(unknown, anchors=[BIRTH, THE_YUCAIPA_YEARS])
        self.assertNotIn("born", probe["text"].lower())
        self.assertEqual(probe["text"], "When did the Yucaipa years begin and end?")

        # A real eligible anchor (a residence) is still used, honestly.
        probe_anchored = ti.choose_probe(unknown, anchors=[BIRTH, SAN_DIEGO])
        self.assertNotIn("born", probe_anchored["text"].lower())
        self.assertIn("the move to San Diego", probe_anchored["text"])

    def test_e0_04_a_moment_unknown_may_still_anchor_on_birth(self):
        """Regression guard against over-correction: a moment MAY predate the
        person (a family story is older than they are), so the rule must not
        blanket-exclude birth for every kind — only place_span/period_bound."""
        unknown = {"kind": "moment", "label": "the barn fire"}
        probe = ti.choose_probe(unknown, anchors=[BIRTH])
        self.assertIn("born", probe["text"].lower())
        self.assertEqual(
            probe["text"],
            "the barn fire — was that before or after when you were born?",
        )

    def test_anchor_for_probe_excludes_birth_for_the_two_relational_kinds_only(self):
        rows = ti._anchor_rows([BIRTH, SAN_DIEGO])  # noqa: SLF001
        for kind in ("place_span", "period_bound"):
            with self.subTest(kind=kind):
                chosen = ti.anchor_for_probe({"kind": kind}, rows)
                self.assertIsNotNone(chosen)
                self.assertNotEqual(chosen["kind"], "birth")
        chosen = ti.anchor_for_probe({"kind": "moment"}, rows)
        # `moment` is unchanged: the general anchor_rows[0] rule (birth first).
        self.assertEqual(chosen["kind"], "birth")

    def test_anchor_for_probe_returns_none_when_nothing_is_eligible(self):
        rows = ti._anchor_rows([BIRTH])  # noqa: SLF001
        self.assertIsNone(ti.anchor_for_probe({"kind": "place_span"}, rows))
        self.assertIsNone(ti.anchor_for_probe({"kind": "period_bound"}, rows))

    def test_keystone_probe_period_kind_never_anchors_on_birth_or_itself(self):
        rows = [BIRTH, dict(THE_YUCAIPA_YEARS)]
        probe = ti.keystone_probe("period:the-yucaipa-years",
                                  label="the Yucaipa years", anchors=rows)
        self.assertNotIn("born", probe["text"].lower())
        self.assertEqual(probe["text"], "When did the Yucaipa years begin and end?")

    def test_keystone_probe_entity_and_event_kinds_are_unchanged(self):
        rows = [BIRTH]
        entity_probe = ti.keystone_probe("entity:charlee", label="Charlee", anchors=rows)
        self.assertIn("born", entity_probe["text"].lower())
        event_probe = ti.keystone_probe("event:childhood:A9", label="the barn fire",
                                        anchors=rows)
        self.assertIn("born", event_probe["text"].lower())


# --------------------------------------------------------------------------
# O-E0c — `period_bound` has no wrong writer (posture, not the final writer)
# --------------------------------------------------------------------------

DESCRIPTION = "the Yucaipa years"
SOURCE = "answers/A1.md"
PERIOD = "childhood"
PLACED = {"best": "1996", "earliest": "1996", "latest": "1996",
         "granularity": "year", "confidence": "certain", "basis": "stated",
         "anchors": []}


class PlaceRefusalTests(unittest.TestCase):
    """T-E0-06: a `period_bound` item is refused, never misfiled."""

    def test_place_refusal_names_the_reason_for_a_period_bound_kind(self):
        item = {"kind": "period_bound", "label": DESCRIPTION}
        self.assertEqual(ti.place_refusal(ti.validate_placed(PLACED), item),
                         ti.PLACE_REFUSED_NO_ERA_WRITER)

    def test_place_refusal_names_the_reason_for_a_whisper_gap_kind(self):
        # arc_planner._whisper_intent's own kind is always "timeline_gap"; the
        # unknown's real kind travels as `gap_kind`.
        item = {"kind": "timeline_gap", "gap_kind": "period_bound"}
        self.assertEqual(ti.place_refusal(ti.validate_placed(PLACED), item),
                         ti.PLACE_REFUSED_NO_ERA_WRITER)

    def test_place_refusal_names_the_reason_for_a_period_keystone_anchor(self):
        # A minted keystone question's identity is its anchor key; a "period:"
        # anchor is an era, with no moment to write onto.
        item = {"kind": "keystone_question", "anchor": "period:the-yucaipa-years"}
        self.assertEqual(ti.place_refusal(ti.validate_placed(PLACED), item),
                         ti.PLACE_REFUSED_NO_ERA_WRITER)

    def test_place_refusal_is_none_for_a_moment(self):
        item = {"kind": "moment", "label": "the barn fire"}
        self.assertIsNone(ti.place_refusal(ti.validate_placed(PLACED), item))

    def test_place_invocation_returns_none_for_a_period_bound_item(self):
        item = {"kind": "period_bound", "label": DESCRIPTION}
        invocation = ti.place_invocation(
            ti.validate_placed(PLACED), source=SOURCE, description=DESCRIPTION,
            period=PERIOD, item=item,
        )
        self.assertIsNone(invocation)


class FilePlacementRefusalTests(unittest.TestCase):
    """T-E0-06 (host half): `_file_placement` refuses loudly, writes nothing,
    and the answer text is unaffected (this function is never in the reply
    path — it is only ever called once a turn is already delivered)."""

    def setUp(self):
        self.tmp = root_parent_tmp(self, ROOT, prefix="lifehug-era-refusal-test-")
        self.vault = self.tmp / "vault"
        build_vault(self.vault)
        self.diagnostics: list[tuple] = []
        patch = mock.patch.object(
            cd, "_diagnostic",
            lambda *args, **kwargs: self.diagnostics.append((args, kwargs)))
        patch.start()
        self.addCleanup(patch.stop)

    def file_placement(self, item: dict) -> bool:
        placed = ti.validate_placed(PLACED)
        self.assertIsNotNone(placed, "fixture record must validate")
        with mock.patch("subprocess.run") as run:
            result = cd._file_placement(  # noqa: SLF001
                item, placed, session_id="conversation:test",
                question_id="A1", question_text="When did the Yucaipa years end?",
                vault_root=self.vault,
            )
        run.assert_not_called()  # the refusal must fire BEFORE any subprocess
        return result

    def test_a_period_bound_answer_is_refused_and_writes_nothing(self):
        item = {"kind": "period_bound", "label": DESCRIPTION,
               "source": SOURCE, "period": PERIOD}
        self.assertFalse(self.file_placement(item))
        self.assertEqual(
            [args[:2] for args, _ in self.diagnostics],
            [("timeline_place", ti.PLACE_REFUSED_NO_ERA_WRITER)],
        )
        self.assertFalse(
            (self.vault / "state" / "timeline_placements.json").exists(),
            "a period_bound answer must never reach the placements store",
        )

    def test_a_whisper_gap_kind_period_bound_is_refused_too(self):
        item = {"kind": "timeline_gap", "gap_kind": "period_bound",
               "label": DESCRIPTION, "source": SOURCE, "period": PERIOD}
        self.assertFalse(self.file_placement(item))
        self.assertEqual(
            [args[:2] for args, _ in self.diagnostics],
            [("timeline_place", ti.PLACE_REFUSED_NO_ERA_WRITER)],
        )
        self.assertFalse((self.vault / "state" / "timeline_placements.json").exists())


class MomentFilingGoldenTests(unittest.TestCase):
    """T-E0-07: `moment` items still file exactly as before — the golden argv,
    unaffected by the O-E0c refusal."""

    def test_the_moment_argv_is_byte_identical_with_or_without_the_item_kwarg(self):
        placed = ti.validate_placed({
            "best": "1984", "earliest": "1984", "latest": "1984",
            "granularity": "year", "confidence": "certain", "basis": "stated",
            "anchors": [],
        })
        without_item = ti.place_invocation(
            placed, source="answers/A1.md", description="the move to Mesa",
            period="childhood",
        )
        with_moment_item = ti.place_invocation(
            placed, source="answers/A1.md", description="the move to Mesa",
            period="childhood", item={"kind": "moment", "label": "the move to Mesa"},
        )
        self.assertIsNotNone(without_item)
        self.assertEqual(without_item.argv, with_moment_item.argv)
        self.assertEqual(without_item.stdin_text, with_moment_item.stdin_text)

    def test_a_moment_still_files_end_to_end(self):
        tmp = root_parent_tmp(self, ROOT, prefix="lifehug-era-moment-test-")
        vault = tmp / "vault"
        build_vault(vault, title="the move to Mesa")
        diagnostics: list[tuple] = []
        patch = mock.patch.object(
            cd, "_diagnostic",
            lambda *args, **kwargs: diagnostics.append((args, kwargs)))
        patch.start()
        self.addCleanup(patch.stop)
        item = {"kind": "moment", "label": "the move to Mesa",
               "source": "answers/A1.md", "period": "childhood"}
        placed = ti.validate_placed({
            "best": "1984", "earliest": "1984", "latest": "1984",
            "granularity": "year", "confidence": "certain", "basis": "stated",
            "anchors": [],
        })
        result = cd._file_placement(  # noqa: SLF001
            item, placed, session_id="conversation:test",
            question_id="A1", question_text="When did you move?",
            vault_root=vault,
        )
        self.assertTrue(result)
        self.assertEqual(diagnostics, [])
        placements = json.loads(
            (vault / "state" / "timeline_placements.json").read_text(
                encoding="utf-8"))["placements"]
        self.assertEqual(len(placements), 1)
        self.assertEqual(placements[0]["description"], "the move to Mesa")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
