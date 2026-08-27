"""v234 — one gap, one conversation: the work-item stage.

The audited final timeline build plan gives every actionable row a **Play
now** that "opens a conversation grounded in that exact contradiction"
(§2.5), and rules that resolving a temporal work item on ANY surface closes
it everywhere (§2.3). This suite pins the two decisions that follow from
those sentences and the behavior the plan spells out for the conversation
itself:

* the Play kind names the WORK ITEM, never the surface — `work_item`, with
  v227's `mirror_item` accepted on the read side for exactly one version (v234) and
  deleted in v235;
* the conversation is a STAGE of the existing `timeline` child, not an
  eighth child of Conversation (ADR 0024's 2026-08-26 amendment), so it adds
  no output vocabulary, no filing path and no lints of its own;
* §2.5's quiet case is structural: "I don't know", a skip, and a third answer
  each write nothing at all.

Synthetic data only; NEVER references ~/Workspace/dave.
"""

from __future__ import annotations

import json
import sys
import unittest
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "system"))
sys.path.insert(0, str(ROOT / "tests"))

import conversation_delivery as cd  # noqa: E402
import mirror_work as mw  # noqa: E402
import timeline_interaction as ti  # noqa: E402
from test_conversation_delivery import EngineTestCase  # noqa: E402
from test_mirror_work import MirrorWorkTestCase  # noqa: E402

GOLDENS = ROOT / "interactions" / "timeline" / "evals" / "goldens"
BAD_FIXTURE = GOLDENS / "timeline-work-item-proposes-a-date-bad-01.json"

ANCHORS = [
    {"key": "birth", "label": "when you were born", "kind": "birth", "date": "1979"},
    {"key": "mom-died", "label": "when your mother died", "kind": "landmark",
     "date": "1984"},
]


def reading(display: str, edtf: str, claim_id: str, source_id: str) -> dict:
    return {
        "display": display, "edtf": edtf, "basis": "stated", "confidence": "certain",
        "score": 0.5, "claim_refs": [claim_id],
        "sources": [{"claim_id": claim_id, "source_id": source_id, "status": "active",
                     "quote": f"It was {display}."}],
    }


def target(**overrides) -> dict:
    row = {
        "kind": mw.PLAY_TARGET_KIND,
        "ref": "work:dayton",
        "work_item_id": "work:dayton",
        "item_kind": "contradiction",
        "label": "the move to Dayton",
        "best_supported": reading("1984", "1984", "claim:a", "msg-a"),
        "alternatives": [reading("1986", "1986", "claim:b", "msg-b")],
        "evidence": [
            {"claim_id": "claim:a", "source_id": "msg-a",
             "quote": "We moved to Dayton the summer after Mom died."},
            {"claim_id": "claim:b", "source_id": "msg-b",
             "quote": "I was seven when we landed in Dayton."},
        ],
        "resolvable_claim_ids": ["claim:a", "claim:b"],
        "anchors": ANCHORS,
    }
    row.update(overrides)
    return row


def placed(best: str, *, granularity: str = "year", anchors: object = ()) -> dict:
    return ti.validate_placed(
        {"best": best, "earliest": best, "latest": best, "granularity": granularity,
         "confidence": "certain", "basis": "anchor" if anchors else "stated",
         "anchors": list(anchors)},
        anchors=ANCHORS,
    )


# --------------------------------------------------------------------------
# The rename
# --------------------------------------------------------------------------


class PlayKindTests(unittest.TestCase):
    """§2.3: one gap, one conversation, whatever surface it was seen on."""

    def test_the_canonical_kind_names_the_work_item_not_the_surface(self):
        self.assertEqual(mw.PLAY_TARGET_KIND, "work_item")
        self.assertNotIn("mirror", mw.PLAY_TARGET_KIND)

    def test_the_play_kind_and_the_stage_are_one_word(self):
        """A host binds ONE verb. Two strings would be two bindings waiting to
        drift, and the drift would be invisible until a target opened nothing."""
        self.assertEqual(mw.PLAY_TARGET_KIND, ti.WORK_ITEM_STAGE)
        self.assertIn(ti.WORK_ITEM_STAGE, ti.VALID_TIMELINE_STAGES)

    def test_the_v227_alias_is_gone(self):
        """v234 promised its own deprecation would end in v235. It did."""
        self.assertFalse(hasattr(mw, "LEGACY_PLAY_TARGET_KIND"))
        self.assertEqual(mw.PLAY_TARGET_KINDS, (mw.PLAY_TARGET_KIND,))
        self.assertTrue(mw.is_play_target_kind(mw.PLAY_TARGET_KIND))
        self.assertFalse(mw.is_play_target_kind("mirror_item"))

    def test_nothing_else_is_a_play_kind(self):
        for value in ("timeline", "mirror", "mirror_item", "", None, 17, "work_items"):
            with self.subTest(value=value):
                self.assertFalse(mw.is_play_target_kind(value))

    def test_a_v227_target_no_longer_opens_the_stage(self):
        """The one-version grace is over: a target still holding the old word
        is not silently rewritten, it is refused — a miss, never a wrong join."""
        legacy = target(kind="mirror_item")
        self.assertIsNone(ti.work_item_target(legacy))

    def test_the_evidence_caps_are_one_number(self):
        self.assertEqual(ti.MAX_WORK_ITEM_EVIDENCE, mw.MAX_PLAY_EVIDENCE)
        self.assertEqual(ti.MAX_WORK_ITEM_READINGS, mw.MAX_ALTERNATIVES + 1)


class LivePlayTargetTests(MirrorWorkTestCase):
    """The target the stage reads is the one Mirror actually emits."""

    def test_play_target_emits_only_the_canonical_kind(self):
        fixture = self.contradiction_fixture()
        row = mw.mirror_rows([fixture["item"]], self.index())[0]
        self.assertEqual(row.play["kind"], "work_item")
        self.assertNotIn("mirror_item", json.dumps(row.play))

    def test_a_live_mirror_target_is_readable_by_the_stage(self):
        fixture = self.contradiction_fixture()
        row = mw.mirror_rows([fixture["item"]], self.index())[0]
        normalized = ti.work_item_target(row.play)
        self.assertIsNotNone(normalized)
        self.assertEqual(normalized["item_kind"], "contradiction")
        self.assertEqual(normalized["work_item_id"], row.work_item_id)
        self.assertGreaterEqual(len(normalized["readings"]), 2)


# --------------------------------------------------------------------------
# The target
# --------------------------------------------------------------------------


class TargetReadingTests(unittest.TestCase):
    def test_a_bare_work_item_is_read_too(self):
        """A queue-minted gap has no evidence rendered on it yet."""
        normalized = ti.work_item_target(
            {"kind": "precision_gap", "work_item_id": "work:harvey",
             "requested_field": "day", "label": "when Harvey was born"}
        )
        self.assertEqual(normalized["item_kind"], "precision_gap")
        self.assertEqual(normalized["readings"], [])

    def test_every_refusal_returns_none_and_never_raises(self):
        for name, value in {
            "not a dict": "work:dayton",
            "empty": {},
            "unknown kind": target(kind="mirror_row"),
            "unknown item kind": target(item_kind="vibes"),
            "no identity": {k: v for k, v in target().items()
                            if k not in ("ref", "work_item_id")},
        }.items():
            with self.subTest(case=name):
                self.assertIsNone(ti.work_item_target(value))

    def test_normalizing_a_normalized_target_is_a_no_op(self):
        """It was not, once: `sources` flattened to ids on the first pass and
        the second pass dropped them, so a caller that normalized before
        filing retired nothing at all."""
        once = ti.work_item_target(target())
        self.assertEqual(ti.work_item_target(once), once)

    def test_evidence_is_bounded(self):
        crowded = target(evidence=[
            {"claim_id": f"claim:{i}", "source_id": f"msg-{i}", "quote": f"span {i}"}
            for i in range(20)
        ])
        self.assertEqual(len(ti.work_item_target(crowded)["evidence"]),
                         ti.MAX_WORK_ITEM_EVIDENCE)


class ProbeTests(unittest.TestCase):
    def test_a_contradiction_puts_both_readings_up_and_proposes_neither(self):
        probe = ti.work_item_probe(target(), anchors=())
        self.assertEqual(probe["step"], "convergence")
        self.assertIn("1984", probe["text"])
        self.assertIn("1986", probe["text"])
        self.assertIsNone(ti.proposes_a_date(probe["text"]))

    def test_a_precision_probe_offers_bounds_rather_than_demanding_a_point(self):
        probe = ti.work_item_probe(
            target(item_kind="precision_gap", requested_field="day",
                   label="when Harvey was born", alternatives=[]),
            anchors=(),
        )
        self.assertEqual(probe["step"], "bounds")
        self.assertIn("the day", probe["text"])
        self.assertTrue(any(p.search(probe["text"]) for p in ti._BOUNDS_OFFER_RES))

    def test_an_unlisted_requested_field_never_reaches_the_person_raw(self):
        probe = ti.work_item_probe(
            target(item_kind="precision_gap", requested_field="earliest_bound",
                   alternatives=[]), anchors=())
        self.assertNotIn("earliest_bound", probe["text"])
        self.assertIn(ti.DEFAULT_FIELD_DISPLAY, probe["text"])

    def test_an_identity_probe_names_the_candidates(self):
        probe = ti.work_item_probe(
            target(item_kind="identity_uncertain", label="AJ",
                   candidates=[{"ref": "person/aj-lang", "name": "AJ Lang"},
                               {"ref": "person/aj-vance", "name": "AJ Vance"}]),
            anchors=(),
        )
        self.assertIn("AJ Lang", probe["text"])
        self.assertIn("AJ Vance", probe["text"])

    def test_a_missing_anchor_probe_uses_the_landmark_when_there_is_one(self):
        row = target(item_kind="missing_anchor", label="the Dayton move")
        self.assertEqual(ti.work_item_probe(row)["step"], "sequence")
        self.assertEqual(
            ti.work_item_probe(target(item_kind="missing_anchor", anchors=[]))["step"],
            "content")

    def test_an_unusable_target_is_a_named_refusal(self):
        with self.assertRaises(ti.TimelineInteractionError):
            ti.work_item_probe({"kind": "nope"})


class ContextTests(unittest.TestCase):
    def test_the_block_carries_the_disagreement_and_their_own_words(self):
        body = ti.render_work_item(target())
        self.assertIn("contradiction", body)
        self.assertIn("the move to Dayton", body)
        self.assertIn("1984", body)
        self.assertIn("1986", body)
        self.assertIn("the summer after Mom died", body)

    def test_the_block_is_empty_for_an_unusable_target(self):
        self.assertEqual(ti.render_work_item(None), "")
        self.assertEqual(ti.render_work_item({"kind": "nope"}), "")

    def test_the_years_a_reply_may_repeat_come_from_the_target(self):
        """A contradiction reply MUST say both readings back; every other year
        is still an invention."""
        years = ti.work_item_known_years(target())
        self.assertEqual(set(years), {"1984", "1986"})
        self.assertNotIn("1985", years)


# --------------------------------------------------------------------------
# The stage
# --------------------------------------------------------------------------


class StageSelectionTests(unittest.TestCase):
    OPENING = {"turns": []}
    MIDDLE = {"turns": [{"role": "user", "text": "hi"},
                        {"role": "lifehug", "text": "hello"}]}

    def test_a_target_selects_the_stage_from_the_first_reply(self):
        """There is no open-then-place warm-up: the deep link already said
        which disagreement this is about."""
        self.assertEqual(ti.timeline_stage_for_session(self.OPENING), "open")
        self.assertEqual(
            ti.timeline_stage_for_session(self.OPENING, work_item=target()),
            ti.WORK_ITEM_STAGE)

    def test_without_a_target_nothing_moves(self):
        self.assertEqual(ti.timeline_stage_for_session(self.MIDDLE), "place")

    def test_every_close_rule_still_wins(self):
        for name, kwargs in {
            "leaving": {"user_leaving": True},
            "settled": {"placement_settled": True},
            "no new bound": {"no_new_bound_streak": ti.STOP_AFTER_UNPRODUCTIVE_PROBES},
        }.items():
            with self.subTest(case=name):
                self.assertEqual(
                    ti.timeline_stage_for_session(self.MIDDLE, work_item=target(),
                                                  **kwargs),
                    "close")

    def test_the_probe_ceiling_ends_a_work_item_episode_too(self):
        long = {"turns": [{"role": "user", "text": str(i)} for i in range(ti.MAX_PROBES)]}
        self.assertEqual(ti.timeline_stage_for_session(long, work_item=target()),
                         "close")

    def test_an_unusable_target_degrades_to_the_ordinary_stage(self):
        self.assertEqual(
            ti.timeline_stage_for_session(self.MIDDLE, work_item={"kind": "nope"}),
            "place")


class StageLintTests(unittest.TestCase):
    def _classes(self, text: str, *, asks: int = 1, step: str = "convergence") -> set:
        return {
            row["lint"] for row in ti.lint_timeline_reply(
                text, stage=ti.WORK_ITEM_STAGE, probe_step=step,
                known_years=ti.work_item_known_years(target()),
                timeline_asks_so_far=asks,
            )
        }

    def test_the_once_per_conversation_rule_does_not_apply_here(self):
        """§2.2 allows several progressively precise questions in a
        conversation the person opened. The ambient rule is for conversations
        they opened to talk about something else."""
        findings = self._classes("And before that — where were you living?",
                                 asks=3, step="residence")
        self.assertNotIn("timeline_gates.one_per_conversation", findings)
        ambient = {
            row["lint"] for row in ti.lint_timeline_reply(
                "And before that — where were you living?", stage="place",
                probe_step="residence", known_years=(), timeline_asks_so_far=3)
        }
        self.assertIn("timeline_gates.one_per_conversation", ambient)

    def test_repeating_both_readings_back_is_not_an_invention(self):
        self.assertEqual(
            self._classes("You've told me 1984, and you've told me 1986."), set())

    def test_the_negative_golden_fires_every_class_it_names(self):
        data = json.loads(BAD_FIXTURE.read_text(encoding="utf-8"))
        self.assertEqual(data["fixture_id"],
                         "timeline-work-item-proposes-a-date-bad-01")
        self.assertTrue(data["cases"])
        for case in data["cases"]:
            with self.subTest(case=case["case_id"]):
                findings = {
                    row["lint"] for row in ti.lint_timeline_reply(
                        case["reply"], stage=case["stage"],
                        probe_step=case["probe_step"],
                        known_years=data["known_years"], timeline_asks_so_far=1)
                }
                self.assertIn(case["expected_lint"], findings)

    def test_the_broken_replies_are_not_in_the_scored_goldens(self):
        """Gates are 1.0 compliance, so a deliberately-broken reply in the
        fixtures would fail the seat rather than document the defect."""
        import timeline_evals as te  # noqa: PLC0415

        ids = {row["fixture_id"] for row in te.load_fixtures()}
        self.assertNotIn("timeline-work-item-proposes-a-date-bad-01", ids)


# --------------------------------------------------------------------------
# What an answer settles — §2.5, made mechanical
# --------------------------------------------------------------------------


class ResolutionDecisionTests(unittest.TestCase):
    def test_naming_one_reading_retires_the_other_and_only_the_other(self):
        self.assertEqual(
            ti.work_item_retire_ids(target(), placed("1984", anchors=["mom-died"])),
            ("claim:b",))

    def test_i_dont_know_retires_nothing(self):
        self.assertEqual(ti.work_item_retire_ids(target(), None), ())
        self.assertIsNone(
            ti.work_item_resolution(target(), None,
                                    resolution_text="I honestly don't know."))

    def test_a_third_answer_retires_nothing(self):
        """New evidence, not a side being picked. It files as a claim through
        the ordinary extraction and the fold decides what it does."""
        self.assertEqual(ti.work_item_retire_ids(target(), placed("1991")), ())
        self.assertIsNone(
            ti.work_item_resolution(target(), placed("1991"),
                                    resolution_text="It was 91, I'm sure of it."))

    def test_a_conversation_cannot_reach_past_its_own_row(self):
        narrowed = target(resolvable_claim_ids=["claim:a"])
        self.assertEqual(
            ti.work_item_retire_ids(narrowed, placed("1984", anchors=["mom-died"])),
            ())

    def test_a_silent_turn_writes_nothing_even_with_a_placement(self):
        self.assertIsNone(
            ti.work_item_resolution(target(), placed("1984", anchors=["mom-died"]),
                                    resolution_text="   "))

    def test_the_resolution_is_the_seams_own_kwargs(self):
        kwargs = ti.work_item_resolution(
            target(), placed("1984", anchors=["mom-died"]),
            resolution_text="The summer after Mom died. 84.")
        self.assertEqual(kwargs["work_item_id"], "work:dayton")
        self.assertEqual(kwargs["retire_claim_ids"], ["claim:b"])
        self.assertEqual(kwargs["correction_kind"], "supersede")
        # No `claims_for`: replacements come from the general listener hearing
        # the same message, never from a second assertion here.
        self.assertNotIn("claims_for", kwargs)


# --------------------------------------------------------------------------
# The host seam
# --------------------------------------------------------------------------


class ContextBlockTests(unittest.TestCase):
    SHAPE = cd.TurnShape("mid_arc", True, 2, 25)

    def test_the_work_item_block_is_empty_without_a_target(self):
        self.assertEqual(cd._work_item_context_block(None), "")
        self.assertEqual(cd._work_item_context_block({"kind": "nope"}), "")

    def test_the_block_is_appended_like_every_other_gated_block(self):
        block = cd._work_item_context_block(target())
        self.assertTrue(block.startswith("\n\n## WORK ITEM\n\n"))
        self.assertIn("the move to Dayton", block)

    def test_the_stage_adds_no_output_key_at_all(self):
        """The whole argument for a stage rather than an eighth child: the
        output contract does not grow. `placed` is the lane's existing field
        and there is nothing beside it."""
        place = cd._output_contract_block(replace(self.SHAPE, timeline_stage="place"))
        work = cd._output_contract_block(
            replace(self.SHAPE, timeline_stage=ti.WORK_ITEM_STAGE))
        self.assertEqual(place, work)

    def test_an_ordinary_turns_contract_does_not_move_by_a_byte(self):
        self.assertNotIn("placed", cd._output_contract_block(self.SHAPE))


class FilingTests(MirrorWorkTestCase):
    """The end of the path: a settled contradiction reaches the vault through
    the seam that already settles contradictions, and nothing else does."""

    def play_target(self) -> tuple[dict, dict]:
        fixture = self.contradiction_fixture()
        row = mw.mirror_rows([fixture["item"]], self.index())[0]
        return fixture, ti.work_item_target(row.play)

    def test_choosing_a_reading_writes_a_correction_and_deletes_nothing(self):
        fixture, play = self.play_target()
        before = set(self.files())
        chosen = play["readings"][0]
        record = {"best": chosen["edtf"], "earliest": chosen["edtf"],
                  "latest": chosen["edtf"], "granularity": "year",
                  "confidence": "certain", "basis": "stated", "anchors": []}
        wrote = cd._file_work_item_resolution(
            play, ti.validate_placed(record) or record,
            answer_text="It was the first one — that's the year we married.",
            session_id="s1", vault_root=self.vault,
        )
        self.assertTrue(wrote)
        after = set(self.files())
        self.assertTrue(any("corrections" in path for path in after - before))
        # Nothing was removed: the claim that lost is retired, never deleted.
        self.assertEqual(before - after, set())

    def test_i_dont_know_writes_nothing_at_all(self):
        _fixture, play = self.play_target()
        before = set(self.files())
        self.assertFalse(cd._file_work_item_resolution(
            play, None, answer_text="I really don't remember.",
            session_id="s1", vault_root=self.vault))
        self.assertEqual(set(self.files()), before)

    def test_an_unpublished_item_is_a_diagnostic_not_an_exception(self):
        _fixture, play = self.play_target()
        stray = dict(play, work_item_id="work:nothing-published",
                     kind=mw.PLAY_TARGET_KIND, ref="work:nothing-published")
        chosen = play["readings"][0]
        record = ti.validate_placed(
            {"best": chosen["edtf"], "earliest": chosen["edtf"],
             "latest": chosen["edtf"], "granularity": "year",
             "confidence": "certain", "basis": "stated", "anchors": []})
        self.assertFalse(cd._file_work_item_resolution(
            stray, record, answer_text="The first one.",
            session_id="s1", vault_root=self.vault))


class EnginePathTests(EngineTestCase):
    """The engine's own wiring, on the real `run_post_answer_turn` path."""

    def test_the_prompt_carries_the_work_item_block(self):
        self.run_turn(work_item=target())
        prompt = self.prompts[-1]
        self.assertIn("## WORK ITEM", prompt)
        self.assertIn("the move to Dayton", prompt)
        self.assertIn("the summer after Mom died", prompt)

    def test_the_stage_puts_placed_in_the_contract(self):
        self.run_turn(work_item=target())
        self.assertIn('"placed"', self.prompts[-1])

    def test_an_ordinary_turn_carries_neither(self):
        self.run_turn()
        self.assertNotIn("## WORK ITEM", self.prompts[-1])
        self.assertNotIn('"placed"', self.prompts[-1])

    def test_an_unusable_target_degrades_to_an_ordinary_turn(self):
        self.run_turn(work_item={"kind": "nope", "ref": "x"})
        self.assertNotIn("## WORK ITEM", self.prompts[-1])
        self.assertNotIn('"placed"', self.prompts[-1])

    def test_the_turn_records_which_gap_it_was_about(self):
        self.run_turn(work_item=target())
        session = self.only_session()
        spoken = [turn for turn in session["turns"] if turn["role"] == "lifehug"]
        self.assertEqual(spoken[-1]["work_item_id"], "work:dayton")

    def test_the_lanes_additive_turn_fields_survive_the_append(self):
        """v196's own fields were dropped by `conversation.append_turn`'s
        optional allowlist and nothing noticed: every OSS session recorded a
        placement nowhere, so the ladder's `precision_so_far` was permanently
        blind. The allowlist is the pin."""
        import conversation  # noqa: PLC0415

        source = Path(conversation.__file__).read_text(encoding="utf-8")
        for field in ("placed", "timeline_probe_id", "work_item_id"):
            with self.subTest(field=field):
                self.assertIn(f'"{field}"', source)

    def test_an_ordinary_turn_records_no_work_item(self):
        self.run_turn()
        session = self.only_session()
        spoken = [turn for turn in session["turns"] if turn["role"] == "lifehug"]
        self.assertNotIn("work_item_id", spoken[-1])


if __name__ == "__main__":
    unittest.main()
