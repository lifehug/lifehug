"""Timeline Fix 07 D1 — the birth is the floor, and never an anchor.

Owner, 2026-08-29, reading his own Timeline: *"When did Switzerland mission —
before, after author's birth. Obviously nothing can happen before my birth so
this is a silly question. No questions should ever be asked before my birth."*

Two mechanisms, one defect. `timeline_interaction.anchor_for_probe` has
excluded ``kind == "birth"`` since v236 — but the founder's birthday ALSO
entered `timeline.anchor_index` as an ordinary dated moment ("Author's birth",
``kind: "landmark"``), sorted first by year, and became ``anchor_rows[0]``. So
the exclusion never fired. And v236's own carve-out ("a moment MAY sort against
the birthday") is REVERSED here by the owner's ruling: nothing sorts against
the origin of the coordinate system.

Every test below FAILS on v261.

Synthetic data only; NEVER references ~/Workspace/dave.
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "system"))
sys.path.insert(0, str(ROOT / "tests"))

import chronology as chrono  # noqa: E402
import temporal_timeline as tt  # noqa: E402
import timeline as tl  # noqa: E402
import timeline_interaction as ti  # noqa: E402
from test_temporal_timeline import NOW, claim, index_of  # noqa: E402

BIRTHDAY = "1981-07-11"


def birth_record() -> chrono.DateRecord:
    return chrono.DateRecord(best=BIRTHDAY, earliest=BIRTHDAY, latest=BIRTHDAY,
                             granularity="day", confidence="certain", basis="stated")


def owner_birth_moment() -> dict:
    """The founder's own shape: the birthday ALSO filed as a dated moment."""
    return {"source_short": "A1", "title": "Author's birth", "slug": "author-s-birth",
            "date": birth_record()}


class TheOriginIsTypedBirth(unittest.TestCase):
    def test_owner_birth_entry_row_is_typed_birth(self):
        index = tl.anchor_index([], [], [owner_birth_moment()],
                                birth_date=birth_record())
        self.assertIn("birth", index)
        self.assertEqual(index["birth"]["kind"], "birth")
        moment = next(row for key, row in index.items() if key != "birth")
        self.assertEqual(
            moment["kind"], "birth",
            "a row whose date IS the birth is the origin, whatever minted it")

    def test_an_ordinary_landmark_keeps_its_kind(self):
        other = {"source_short": "A2", "title": "the barn fire", "slug": "the-barn-fire",
                 "date": chrono.DateRecord(best="1989", earliest="1989", latest="1989",
                                           granularity="year", confidence="certain",
                                           basis="stated")}
        index = tl.anchor_index([], [], [owner_birth_moment(), other],
                                birth_date=birth_record())
        kinds = {row["label"]: row["kind"] for row in index.values()}
        self.assertEqual(kinds["the barn fire"], "landmark")

    def test_no_birth_date_leaves_the_index_exactly_as_it_was(self):
        index = tl.anchor_index([], [], [owner_birth_moment()], birth_date=None)
        self.assertNotIn("birth", index)
        self.assertEqual({row["kind"] for row in index.values()}, {"landmark"})


class BirthIsNeverAnAnchor(unittest.TestCase):
    ROWS = ti._anchor_rows([  # noqa: SLF001
        {"key": "birth", "label": "when you were born", "kind": "birth",
         "date": BIRTHDAY},
        {"key": "moment-a1-author-s-birth", "label": "Author's birth",
         "kind": "birth", "date": BIRTHDAY},
    ])

    def test_birth_is_never_an_anchor_for_any_kind(self):
        for kind in ("moment", "place_span", "period_bound", "date_contradiction",
                     "era_gap", "residence_gap", "landmark_subject"):
            with self.subTest(kind=kind):
                self.assertIsNone(
                    ti.anchor_for_probe({"kind": kind, "label": "the mission"},
                                        self.ROWS))

    def test_no_probe_text_mentions_birth_as_an_anchor(self):
        for kind in ("moment", "place_span", "period_bound", "date_contradiction"):
            with self.subTest(kind=kind):
                probe = ti.choose_probe(
                    {"kind": kind, "label": "Switzerland Mission",
                     "slug": "switzerland-mission"},
                    anchors=self.ROWS,
                )
                self.assertNotIn("born", probe["text"].lower())
                self.assertNotIn("birth", probe["text"].lower())
                self.assertNotIn("before or after", probe["text"].lower())

    def test_the_keystone_probe_does_not_name_it_either(self):
        for key, label in (("period:the-mission", "the Mission"),
                           ("entity:charlee", "Charlee"),
                           ("event:childhood:A9", "the barn fire")):
            with self.subTest(key=key):
                probe = ti.keystone_probe(key, label=label, anchors=self.ROWS)
                self.assertNotIn("born", probe["text"].lower())
                self.assertNotIn("birth", probe["text"].lower())


class AnAnchorHasToBeRelevant(unittest.TestCase):
    """D5's second half — the owner's screenshot anchored Childhood against
    "First big paycheck arrives by mail", chosen by adjacency in a sorted
    list."""

    ROWS = ti._anchor_rows([  # noqa: SLF001
        {"key": "first-paycheck", "label": "First big paycheck arrives by mail",
         "kind": "landmark", "date": "1999"},
        {"key": "san-diego", "label": "the move to San Diego", "kind": "residence",
         "date": "1996"},
    ])

    def test_an_unrelated_landmark_is_dropped(self):
        """The owner's own sentence, minus the age frame: an era's bounds are
        never sorted against a landmark that has nothing to do with it."""
        landmark_only = ti._anchor_rows([  # noqa: SLF001
            {"key": "first-paycheck", "label": "First big paycheck arrives by mail",
             "kind": "landmark", "date": "1999"}])
        for kind in ("period_bound", "place_span"):
            with self.subTest(kind=kind):
                self.assertIsNone(ti.anchor_for_probe(
                    {"kind": kind, "slug": "the-mission", "label": "the Mission"},
                    landmark_only))

    def test_a_landmark_about_the_same_thing_is_kept(self):
        landmark_only = ti._anchor_rows([  # noqa: SLF001
            {"key": "first-paycheck", "label": "First big paycheck arrives by mail",
             "kind": "landmark", "date": "1999"}])
        chosen = ti.anchor_for_probe(
            {"kind": "period_bound", "slug": "the-paycheck-years",
             "label": "the paycheck years"}, landmark_only)
        self.assertIsNotNone(chosen)
        self.assertEqual(chosen["key"], "first-paycheck")

    def test_structure_still_anchors_structure(self):
        chosen = ti.anchor_for_probe(
            {"kind": "period_bound", "slug": "the-mission", "label": "the Mission"},
            self.ROWS)
        self.assertIsNotNone(chosen)
        self.assertEqual(chosen["kind"], "residence")

    def test_an_ordinary_moment_may_still_be_ordered_against_another(self):
        """The relevance rule is deliberately NOT extended to a bare moment:
        ordering one memory against another is how people date them, and the
        ladder's `sequence` rung exists for exactly that. Only the BIRTH is
        unconditionally excluded."""
        chosen = ti.anchor_for_probe(
            {"kind": "moment", "label": "the barn fire"}, self.ROWS)
        self.assertIsNotNone(chosen)
        self.assertNotEqual(chosen["kind"], "birth")


class TheInferredFloor(unittest.TestCase):
    """No interval on the owner's own axis opens before the origin."""

    def owner_birth(self):
        return claim(claim_type="date", subject_mention="self", event_kind="birth",
                     temporal_value=BIRTHDAY, quote="I was born 11 July 1981",
                     seed="b")

    def wide(self, basis="order"):
        record = chrono.DateRecord(best="1975/1995", earliest="1975", latest="1995",
                                   granularity="range", confidence="inferred",
                                   basis=basis).to_dict()
        return claim(claim_type="date", subject_mention="self", event_kind="span",
                     temporal_value=record, quote="somewhere in there", seed="w")

    def span_of(self, result):
        return next(row["best_temporal_value"] for row in result.nodes
                    if row.get("event_kind") == "span")

    def test_inferred_earliest_clamped_at_origin(self):
        result = tt.derive_calculated_timeline(
            index_of(self.owner_birth(), self.wide()), now=NOW)
        value = self.span_of(result)
        self.assertEqual(value["earliest"], BIRTHDAY)
        self.assertEqual(value["latest"], "1995")
        self.assertIn({"rule": tt.ORIGIN_FLOOR_RULE, "was": "1975",
                       "origin": BIRTHDAY}, value["provenance"])
        self.assertIn("origin_floor_applied",
                      [row["finding"] for row in result.diagnostics["findings"]])

    def test_a_stated_date_before_the_origin_is_a_contradiction_not_a_clamp(self):
        """A bound somebody SAID is never silently moved: that would hide the
        disagreement the substrate exists to surface."""
        result = tt.derive_calculated_timeline(
            index_of(self.owner_birth(), self.wide(basis="stated")), now=NOW)
        self.assertEqual(self.span_of(result)["earliest"], "1975")
        self.assertNotIn("origin_floor_applied",
                         [row["finding"] for row in result.diagnostics["findings"]])

    def test_with_no_birthday_there_is_no_floor_to_apply(self):
        result = tt.derive_calculated_timeline(index_of(self.wide()), now=NOW)
        self.assertEqual(self.span_of(result)["earliest"], "1975")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
