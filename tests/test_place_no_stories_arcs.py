"""v200 / place-no-stories-arcs — a place you named with nothing in it.

v199 computed `timeline.timeline_data()["place_no_stories"]` and left
CONSUMPTION as a follow-up. This suite pins the follow-up: the rows become a
`place_no_stories` arc-card intent, ranked after the timeline whisper, at most
one per card, counted within the SAME `arc_planner.DEFAULT_GAP_MAX`, and
rendered into the conversation prompt through one definition.

The byte-identity half matters as much as the feature: a vault with no such
place must plan and prompt exactly as v199 did.

Synthetic data only; NEVER references ~/Workspace/dave.

    python3 -m unittest tests.test_place_no_stories_arcs -v
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

import arc_planner  # noqa: E402
import arc_walk  # noqa: E402
import conversation  # noqa: E402
import interaction_evals  # noqa: E402
import landmarks_interaction as li  # noqa: E402
import question_judgment  # noqa: E402
import timeline_interaction as ti  # noqa: E402


def _date(value: str) -> dict:
    import chronology as chrono  # noqa: PLC0415

    record = chrono.parse_edtf(value, basis="stated")
    return record.to_dict()


LANDMARKS = {"residences": [
    {"label": "Costa Mesa", "household": "my sister Ana",
     "span": {"start": _date("1990"), "end": _date("1993")}},
    {"label": "Bell Avenue",
     "span": {"start": _date("1984"), "end": _date("1990")}},
]}

QUEUE_ITEM = {"question_id": "W4", "category": "work", "focus": "the trade",
              "story_function": "turning_point", "reason": "coverage"}


def _rows() -> list[dict]:
    return [dict(row) for row in li.places_without_stories(LANDMARKS)]


def _material(**over) -> dict:
    """Material with every collector's key present and empty — the shape
    `collect_material` returns, so a planner test never depends on a vault."""
    base = {
        "scene_slots": {},
        "timeline_gaps": [],
        "places_without_stories": [],
        "sit_with": [],
        "neighborhoods": {},
        "answers": {},
        "studio_slots": {},
        "quality": {},
    }
    base.update(over)
    return base


WHISPER_GAP = {
    "kind": "all_undated", "period": "mesa", "leverage": 9,
    "unknown_key": "all_undated:mesa", "anchor": "period:mesa",
    "message": "the Mesa years",
    "probe": {"step": "residence", "text": "Where were you living when that happened?"},
    "anchors": [],
}


class RowShapeTests(unittest.TestCase):
    """The three ADDITIVE fields v200 puts on a row (the old ones are pinned
    by tests/test_landmarks.py and must not move)."""

    def test_a_row_carries_the_place_the_span_and_the_landmark_ref(self):
        row = _rows()[0]
        self.assertEqual(row["label"], "Costa Mesa")
        self.assertEqual(row["span"], "1990–1993")
        self.assertEqual(row["landmark"], {"domain": "residences", "label": "Costa Mesa"})
        self.assertEqual(row["witnesses"], "my sister Ana")

    def test_the_anchor_is_the_one_the_anchor_index_mints_for_that_residence(self):
        """One slug implementation, not two (recurring-defect doctrine)."""
        anchors = li.anchors_from_landmarks(LANDMARKS)
        for row in _rows():
            self.assertIn(row["anchor"], anchors)
            self.assertEqual(row["key"], f"place_no_stories:{row['anchor']}")

    def test_an_undated_residence_still_yields_nothing(self):
        """Its span is v196's `place_span` dating gap, and this kind never
        competes with it."""
        self.assertEqual(li.places_without_stories({"residences": [{"label": "Dayton"}]}), ())

    def test_a_place_with_moments_is_still_not_a_gap(self):
        rows = li.places_without_stories(LANDMARKS, event_places=("Costa Mesa",))
        self.assertEqual([r["label"] for r in rows], ["Bell Avenue"])


class RenderingTests(unittest.TestCase):
    """`landmarks_interaction.render_place_no_stories` — the ONE rendering."""

    def _intent(self, **over) -> dict:
        intent = arc_planner._place_no_stories_intent_from_row(_rows()[0])  # noqa: SLF001
        intent.update(over)
        return intent

    def test_the_line_names_the_place_the_span_and_the_ask(self):
        line = li.render_place_no_stories(self._intent())
        self.assertIn("Costa Mesa", line)
        self.assertIn("1990–1993", line)
        self.assertIn("no stories from there yet", line)
        self.assertIn("if it fits", line)

    def test_a_witness_rides_the_line_when_the_household_rung_supplied_one(self):
        self.assertIn("my sister Ana", li.render_place_no_stories(self._intent()))

    def test_no_witness_is_not_an_error(self):
        line = li.render_place_no_stories(self._intent(witnesses=None))
        self.assertIn("Costa Mesa", line)
        self.assertNotIn("someone who was there", line)

    def test_the_line_never_proposes_a_date(self):
        """ADR 0025's suggestive-interviewing hazard / Lindsay et al. 2004 —
        ONE definition, now three callers. Reporting the span they gave us is
        right; asking for a yes is the banned move."""
        self.assertIsNone(ti.proposes_a_date(li.render_place_no_stories(self._intent())))

    def test_the_line_never_demands_a_year(self):
        line = li.render_place_no_stories(self._intent()).lower()
        self.assertNotIn(arc_planner.BANNED_PHRASE, line)

    def test_without_a_probe_it_degrades_to_the_bare_kind(self):
        self.assertEqual(li.render_place_no_stories({"kind": "place_no_stories"}),
                         "place_no_stories")
        self.assertEqual(li.render_place_no_stories("nonsense"), "place_no_stories")


class PromptTests(unittest.TestCase):
    """How the aside reaches the model — the whisper's seam, reused."""

    def _intent(self) -> dict:
        return arc_planner._place_no_stories_intent_from_row(_rows()[0])  # noqa: SLF001

    def _session(self, *intents) -> dict:
        return {"arc": {"opening": "o", "intents": list(intents)}, "turns": []}

    def test_the_aside_renders_in_the_session_block(self):
        session = self._session({"kind": "scene_slot"}, self._intent())
        block = conversation._assemble_session_block(session)  # noqa: SLF001
        self.assertIn("Place with no stories:", block)
        self.assertIn("Costa Mesa", block)

    def test_the_aside_wins_the_current_intent_slot(self):
        session = self._session({"kind": "scene_slot"}, self._intent())
        label = conversation._current_intent_label(  # noqa: SLF001
            session, session["arc"]["intents"])
        self.assertIn("Costa Mesa", label)

    def test_an_unraised_whisper_still_wins_over_the_aside(self):
        whisper = {"kind": "timeline_gap", "probe": "Where were you living then?",
                   "leverage": 9, "label": "the Mesa years", "anchors": []}
        session = self._session(whisper, self._intent())
        label = conversation._current_intent_label(  # noqa: SLF001
            session, session["arc"]["intents"])
        self.assertIn("Where were you living then?", label)
        self.assertNotIn("Costa Mesa", label)

    def test_a_bare_intent_renders_byte_for_byte_like_every_other_kind(self):
        """The v196 golden (`test_every_other_intent_kind_renders_byte_for_
        byte_as_v195`) iterates the whole vocabulary minus timeline_gap, so
        the seventh kind must degrade exactly as the sixth does."""
        session = self._session({"kind": "place_no_stories"})
        self.assertEqual(conversation._assemble_session_block(session),  # noqa: SLF001
                         "Arc card: o (intents: place_no_stories)")
        self.assertEqual(
            conversation._current_intent_label(  # noqa: SLF001
                session, session["arc"]["intents"]), "place_no_stories")

    def test_no_aside_means_no_line(self):
        session = self._session({"kind": "scene_slot"})
        self.assertNotIn("Place with no stories:",
                         conversation._assemble_session_block(session))  # noqa: SLF001
        self.assertIsNone(conversation.place_no_stories_aside(session))


class PlannerTests(unittest.TestCase):
    """The ranking, the per-card cap, and the SHARED weekly budget."""

    def _plan(self, items, material, **kw):
        return arc_planner.plan_deterministic(items, material, now="2026-08-23T00:00:00Z", **kw)

    def _kinds(self, card) -> list[str]:
        return [i["kind"] for i in card["intents"]]

    def test_a_card_gets_the_aside_when_there_is_no_whisper(self):
        card = self._plan([QUEUE_ITEM], _material(places_without_stories=_rows()))[0]
        self.assertIn("place_no_stories", self._kinds(card))
        intent = next(i for i in card["intents"] if i["kind"] == "place_no_stories")
        self.assertEqual(intent["place"], "Costa Mesa")
        self.assertEqual(intent["span"], "1990–1993")
        self.assertEqual(intent["unknown_keys"], ["place_no_stories:residences-costa-mesa"])
        self.assertTrue(intent["probe"])

    def test_a_card_that_took_a_whisper_takes_no_aside(self):
        card = self._plan([QUEUE_ITEM], _material(timeline_gaps=[dict(WHISPER_GAP)],
                                                  places_without_stories=_rows()))[0]
        self.assertIn("timeline_gap", self._kinds(card))
        self.assertNotIn("place_no_stories", self._kinds(card))

    def test_at_most_one_aside_per_card(self):
        card = self._plan([QUEUE_ITEM], _material(places_without_stories=_rows()))[0]
        self.assertEqual(self._kinds(card).count("place_no_stories"), 1)

    def test_the_same_place_is_never_offered_twice_in_one_week(self):
        items = [dict(QUEUE_ITEM, question_id=f"W{n}") for n in range(1, 4)]
        cards = self._plan(items, _material(places_without_stories=_rows()))
        offered = [i["place"] for card in cards for i in card["intents"]
                   if i["kind"] == "place_no_stories"]
        self.assertEqual(offered, ["Costa Mesa", "Bell Avenue"])

    def test_the_two_kinds_share_one_weekly_budget(self):
        """gap_max=1, one whisper available and two places: the whisper takes
        the budget and no aside is ever planned."""
        items = [dict(QUEUE_ITEM, question_id=f"W{n}") for n in range(1, 4)]
        cards = self._plan(items, _material(timeline_gaps=[dict(WHISPER_GAP)],
                                            places_without_stories=_rows()),
                           gap_max=1)
        kinds = [k for card in cards for k in self._kinds(card)]
        self.assertEqual(kinds.count("timeline_gap"), 1)
        self.assertEqual(kinds.count("place_no_stories"), 0)

    def test_the_budget_is_the_one_number_not_a_second_dial(self):
        items = [dict(QUEUE_ITEM, question_id=f"W{n}") for n in range(1, 4)]
        cards = self._plan(items, _material(places_without_stories=_rows()), gap_max=1)
        kinds = [k for card in cards for k in self._kinds(card)]
        self.assertEqual(kinds.count("place_no_stories"), 1)

    def test_the_planner_reads_the_assembled_timeline_payload(self):
        payload = {"place_no_stories": [{"kind": "place_no_stories", "key": "k",
                                         "label": "Costa Mesa"}]}
        self.assertEqual(
            [r["label"] for r in arc_planner.collect_places_without_stories(payload=payload)],
            ["Costa Mesa"])

    def test_a_broken_payload_is_a_silent_no_op(self):
        self.assertEqual(arc_planner.collect_places_without_stories(payload={}), [])
        self.assertEqual(arc_planner.collect_places_without_stories(payload="nope"), [])

    def test_a_planned_card_survives_validation(self):
        card = self._plan([QUEUE_ITEM], _material(places_without_stories=_rows()))[0]
        clean, errors = arc_planner.validate_card(
            card, allowed_ids={"W4"}, material=_material())
        self.assertIsNotNone(clean)
        self.assertEqual(errors, [])

    def test_the_prompt_names_the_places_when_there_are_some(self):
        prompt = arc_planner.build_plan_prompt(
            [QUEUE_ITEM], _material(places_without_stories=_rows()),
            self._plan([QUEUE_ITEM], _material(places_without_stories=_rows())))
        self.assertIn("PLACES WITH NO STORIES", prompt)
        self.assertIn("Costa Mesa", prompt)
        self.assertIn("place_no_stories", prompt)


class ByteIdentityTests(unittest.TestCase):
    """THE GOLDEN this change owes: a vault with no such place plans and
    prompts exactly as it did before the kind existed."""

    def _v199_material(self) -> dict:
        material = _material()
        material.pop("places_without_stories")
        return material

    def test_planning_is_byte_identical_without_places(self):
        items = [dict(QUEUE_ITEM, question_id=f"W{n}") for n in range(1, 4)]
        before = arc_planner.plan_deterministic(items, self._v199_material(),
                                                now="2026-08-23T00:00:00Z")
        after = arc_planner.plan_deterministic(items, _material(),
                                               now="2026-08-23T00:00:00Z")
        self.assertEqual(json.dumps(before, sort_keys=True),
                         json.dumps(after, sort_keys=True))
        self.assertNotIn("place_no_stories",
                         [i["kind"] for card in after for i in card["intents"]])

    def test_the_prompt_is_byte_identical_without_places(self):
        cards = arc_planner.plan_deterministic([QUEUE_ITEM], _material(),
                                               now="2026-08-23T00:00:00Z")
        before = arc_planner.build_plan_prompt([QUEUE_ITEM], self._v199_material(), cards)
        after = arc_planner.build_plan_prompt([QUEUE_ITEM], _material(), cards)
        self.assertEqual(before, after)
        self.assertNotIn("PLACES WITH NO STORIES", after)

    def test_a_v199_shaped_session_block_is_unchanged(self):
        session = {"arc": {"opening": "o", "intents": [{"kind": "scene_slot"}]},
                   "turns": []}
        self.assertEqual(conversation._assemble_session_block(session),  # noqa: SLF001
                         "Arc card: o (intents: scene_slot)")


class ArcYieldTests(unittest.TestCase):
    """Requirement 3: the v196 arc-yield pass scores the new kind like the
    others, with NO new state — it is kind-agnostic by construction, and this
    is the test that keeps it that way."""

    SESSIONS = [
        {"arc": {"intents": [{"kind": "place_no_stories", "place": "Costa Mesa"}]},
         "turns": [{"role": "user", "question_id": "W4", "placed": {"best": "1991"}}],
         "extracted": {"entities": [{"slug": "costa-mesa"}]}},
        {"arc": {"intents": [{"kind": "scene_slot"}]},
         "turns": [{"role": "user", "question_id": "W5"}],
         "extracted": {"entities": []}},
    ]

    def test_the_new_kind_gets_its_own_row(self):
        rows = question_judgment.arc_yield(sessions=self.SESSIONS)
        self.assertIn("place_no_stories", rows)
        row = rows["place_no_stories"]
        self.assertEqual(row["sessions"], 1)
        self.assertEqual(row["placements"], 1)
        self.assertEqual(row["new_entities"], 1)
        self.assertEqual(row["yield_per_session"], 2.0)

    def test_it_is_summarized_exactly_like_the_others(self):
        summary = question_judgment.format_arc_yield(
            question_judgment.arc_yield(sessions=self.SESSIONS))
        self.assertIn("place_no_stories:", summary)
        self.assertIn("scene_slot:", summary)

    def test_the_pass_needed_no_branch_for_it(self):
        """Every kind on a card is scored; nothing enumerates the vocabulary."""
        rows = question_judgment.arc_yield(sessions=[
            {"arc": {"intents": [{"kind": kind}]}, "turns": [], "extracted": {}}
            for kind in sorted(conversation.ARC_INTENT_KINDS)
        ])
        self.assertEqual(set(rows), set(conversation.ARC_INTENT_KINDS))


class VocabularyTests(unittest.TestCase):
    """The closed vocabulary, bumped deliberately (ADR 0002's v200
    amendment)."""

    def test_the_kind_is_a_member_and_the_vocabulary_has_seven(self):
        self.assertIn("place_no_stories", conversation.ARC_INTENT_KINDS)
        self.assertEqual(len(conversation.ARC_INTENT_KINDS), 7)

    def test_there_is_exactly_one_definition_of_it(self):
        self.assertEqual(li.PLACE_NO_STORIES_KIND, "place_no_stories")
        self.assertIs(arc_planner.INTENT_KINDS, conversation.ARC_INTENT_KINDS)

    def test_it_is_still_not_a_dating_unknown(self):
        import timeline  # noqa: PLC0415

        self.assertNotIn(li.PLACE_NO_STORIES_KIND, timeline.UNKNOWN_KINDS)
        self.assertNotIn(li.PLACE_NO_STORIES_KIND, timeline.LEDGER_GAP_KINDS)

    def test_the_arc_walk_bridge_note_accepts_it(self):
        note = arc_walk.intent_note({"intents": [
            arc_planner._place_no_stories_intent_from_row(_rows()[0])]})  # noqa: SLF001
        self.assertIn("place they named", note)

    def test_the_definition_file_names_the_kind_for_the_model(self):
        text = " ".join((ROOT / "interactions" / "conversation" / "plan"
                         / "arc-templates.md").read_text(encoding="utf-8").split())
        self.assertIn("place with no stories", text)
        self.assertIn("Ranked after the timeline gap", text)


class GoldenPropertyTests(unittest.TestCase):
    """The committed golden and its new property id."""

    GOLDEN = (ROOT / "interactions" / "conversation" / "evals" / "goldens"
              / "chat-costa-mesa-place-no-stories.json")

    def _golden(self) -> dict:
        return json.loads(self.GOLDEN.read_text(encoding="utf-8"))

    def test_the_property_id_is_in_the_closed_vocabulary(self):
        self.assertIn("place_no_stories_asked_openly", interaction_evals.PROPERTY_IDS)
        self.assertIn("place_no_stories_asked_openly", interaction_evals.PROPERTY_CHECKERS)

    def test_the_committed_golden_passes_schema_lints_and_properties(self):
        self.assertEqual(interaction_evals.check_golden(self._golden()), [])

    def test_a_turn_that_never_names_the_place_fails(self):
        golden = self._golden()
        golden["turns"][2]["text"] = (
            "You put it as \"ate two years of my life\". "
            "What was life like at home then?")
        errors = interaction_evals.check_golden(golden)
        self.assertTrue(any("name the place" in e for e in errors), errors)

    def test_a_turn_that_proposes_a_date_fails(self):
        golden = self._golden()
        golden["turns"][2]["text"] = (
            "You put it as \"ate two years of my life\", and Costa Mesa "
            "across those years. Was it 1991?")
        errors = interaction_evals.check_golden(golden)
        self.assertTrue(any("proposing a date" in e for e in errors), errors)

    def test_declaring_it_without_the_intent_fails_the_schema(self):
        golden = self._golden()
        golden["arc"]["intents"] = [{"kind": "scene_slot"}]
        errors = interaction_evals.check_golden(golden)
        self.assertTrue(any("place_no_stories intent" in e for e in errors), errors)

    def test_the_golden_is_swept_up_with_the_others(self):
        ids = {g.get("golden_id") for g in interaction_evals.load_goldens()}
        self.assertIn("chat-costa-mesa-place-no-stories-01", ids)


if __name__ == "__main__":
    unittest.main()
