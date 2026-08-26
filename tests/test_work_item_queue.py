"""Wave F — value earns the slot: work items reach the daily question.

The audited final timeline build plan §2.3, §2.4, §8.5 and the §10
questions-and-surfaces scenarios. v196 let exactly one class of timeline
question — a keystone, gated on leverage — reach the daily queue. Wave F
replaces that class gate with a value gate: any `TemporalWorkItem` whose
`allowed_surfaces` includes `daily_question` is a candidate, and the §8.5
combined score decides. A keystone still usually wins; it wins by SCORING
HIGHEST, never by being a keystone.

These tests construct work items DIRECTLY through v220's validators rather
than through wave D's derivation, which is building concurrently — the queue
adapter consumes the contract, not the module.

Synthetic data only; NEVER references ~/Workspace/dave.
"""

from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SYSTEM = ROOT / "system"
sys.path.insert(0, str(SYSTEM))

import hashlib  # noqa: E402
import identity_resolution as ident  # noqa: E402
import temporal_claims as tc  # noqa: E402
import temporal_projection as tp  # noqa: E402
import temporal_store as ts  # noqa: E402
import temporal_timeline as tt  # noqa: E402
import timeline_interaction as ti  # noqa: E402


def load(name):
    spec = importlib.util.spec_from_file_location(name, SYSTEM / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    orig = sys.modules.get(name)
    sys.modules[name] = mod
    try:
        spec.loader.exec_module(mod)
    finally:
        if orig is not None:
            sys.modules[name] = orig
        else:
            sys.modules.pop(name, None)
    return mod


qp = load("question_planner")
ap = load("arc_planner")

NOW = "2026-08-26T00:00:00Z"
EMPTY_BANK = "# Questions\n\n## A: Origins\n\n- [ ] A1: Where does your story start?\n"

#: A keystone the way `timeline.keystones()` hands one over.
KEYSTONE = {
    "anchor": "period:mesa",
    "question_id": "tl:mesa",
    "label": "the Mesa years",
    "leverage": 14,
    "unknown_keys": ["a", "b"],
    "anchors": [{"key": "birth", "label": "when you were born",
                 "kind": "birth", "date": "1979"}],
    "probe": {"step": "residence", "cost": 2,
              "text": "Where were you living when that happened?"},
}


def work_item(**overrides) -> dict:
    """A validated `TemporalWorkItem` dict, v220's own validator."""
    payload = {
        "kind": "missing_anchor",
        "state": "open",
        "subject_ref": "event:first-apartment",
        "requested_field": qp.TIMELINE_REQUESTED_FIELD,
        "prompt_intent": "When did you move into that first apartment?",
        "allowed_surfaces": ["timeline", "whisper", "daily_question"],
        "created_at": NOW,
    }
    reach = overrides.pop("downstream_reach", None)
    payload.update(overrides)
    item = tp.validate_temporal_work_item(payload)
    if reach is not None:
        item["downstream_reach"] = reach
    return item


class ScoreTests(unittest.TestCase):
    """§8.5: normalize, expose the components, version the formula."""

    def test_the_components_are_the_ones_the_plan_names(self):
        self.assertEqual(
            qp.WORK_ITEM_SCORE_COMPONENTS,
            ("person_value", "placement_gain", "downstream_reach",
             "context_fit", "interaction_cost", "sensitivity"))

    def test_the_positive_weights_normalize_to_one(self):
        positive = [w for w in qp.DEFAULT_WORK_ITEM_WEIGHTS.values() if w > 0]
        self.assertAlmostEqual(sum(positive), 1.0, places=6)
        self.assertTrue(all(qp.DEFAULT_WORK_ITEM_WEIGHTS[name] < 0
                            for name in ("interaction_cost", "sensitivity")),
                        "cost and sensitivity SUBTRACT, they do not merely fail to add")

    def test_every_score_is_a_unit_score_with_its_components_exposed(self):
        score = qp.score_work_item(work_item(person_value=1.0, downstream_reach=999))
        self.assertEqual(score["score_version"], qp.WORK_ITEM_SCORE_VERSION)
        self.assertLessEqual(score["combined_score"], 1.0)
        self.assertGreaterEqual(score["combined_score"], 0.0)
        self.assertEqual(set(score["components"]), set(qp.WORK_ITEM_SCORE_COMPONENTS))
        for value in score["components"].values():
            self.assertGreaterEqual(value, 0.0)
            self.assertLessEqual(value, 1.0)

    def test_reach_saturates_against_the_one_timeline_dial(self):
        """The exchange rate governs scoring as well as weighting — there is
        deliberately no second reach dial to keep in sync."""
        per_story = qp.DEFAULT_LANE_POLICY["timeline_leverage_per_story"]
        saturated = qp.score_work_item(
            work_item(downstream_reach=int(per_story * qp.WORK_ITEM_REACH_SATURATION_FACTOR)))
        self.assertEqual(saturated["components"]["downstream_reach"], 1.0)
        half = qp.score_work_item(work_item(downstream_reach=per_story))
        self.assertAlmostEqual(half["components"]["downstream_reach"], 0.5, places=3)

    def test_cadence_and_caps_are_not_folded_into_an_items_own_worth(self):
        """§8.5 lists caps among the things the queue normalizes for, but an
        item's score may not depend on what else happened to be queued."""
        self.assertNotIn("cadence", qp.WORK_ITEM_SCORE_COMPONENTS)
        alone = qp.score_work_item(work_item())
        crowded = qp.score_work_item(work_item())
        self.assertEqual(alone["combined_score"], crowded["combined_score"])

    def test_a_bad_number_degrades_to_the_default_rather_than_raising(self):
        score = qp.score_work_item({**work_item(), "person_value": "not a number"})
        self.assertEqual(score["components"]["person_value"],
                         qp.WORK_ITEM_SCORE_DEFAULTS["person_value"])


class QueueAdmissionTests(unittest.TestCase):
    """§10: value earns the slot, and low value stays passive."""

    def test_a_high_value_ordinary_landmark_gap_can_enter_the_queue(self):
        """The scenario v196 could not express: no keystone anywhere, and the
        gap still reaches the daily question because it is worth it."""
        item = work_item(person_value=0.9, context_fit=0.7, downstream_reach=6)
        [candidate] = qp.queue_candidates([item], question_bank_text=EMPTY_BANK)
        self.assertEqual(candidate["work_item_id"], item["work_item_id"])
        self.assertGreaterEqual(candidate["combined_score"],
                                qp.DEFAULT_LANE_POLICY["work_item_queue_threshold"])

    def test_a_low_value_gap_stays_visible_on_timeline_and_out_of_the_queue(self):
        item = work_item(kind="precision_gap", person_value=0.15, context_fit=0.2,
                         interaction_cost=0.6, sensitivity=0.1, downstream_reach=0)
        self.assertLess(qp.score_work_item(item)["combined_score"],
                        qp.DEFAULT_LANE_POLICY["work_item_queue_threshold"])
        self.assertEqual(qp.queue_candidates([item], question_bank_text=EMPTY_BANK), [])
        self.assertIn("timeline", item["allowed_surfaces"],
                      "it is not debt and it is not deleted — it stays an invitation")

    def test_a_keystone_wins_only_when_its_combined_score_is_highest(self):
        """Owner ethos: something of high value has a slot. A keystone has no
        class privilege — it outranks an ordinary gap because reach is a
        component, and it LOSES to one the person values more."""
        keystone = qp.work_item_from_keystone(KEYSTONE, now=NOW)
        ordinary = work_item(person_value=0.6, context_fit=0.5, downstream_reach=2)
        ranked = qp.queue_candidates([ordinary, keystone], question_bank_text=EMPTY_BANK)
        self.assertEqual([row["work_item_id"] for row in ranked],
                         [keystone["work_item_id"], ordinary["work_item_id"]])

        beloved = work_item(person_value=1.0, context_fit=1.0, downstream_reach=6)
        ranked = qp.queue_candidates([keystone, beloved], question_bank_text=EMPTY_BANK)
        self.assertEqual(ranked[0]["work_item_id"], beloved["work_item_id"])
        self.assertIn(keystone["work_item_id"], [row["work_item_id"] for row in ranked],
                      "losing the top slot is not being disqualified")

    def test_a_birthday_gets_no_automatic_daily_priority(self):
        """§2.2/§10: a birthday may be asked directly when contextual value
        justifies it. Nothing anywhere gives it a bonus for being a birthday."""
        birthday = work_item(subject_ref="person:mom", requested_field="birth_date",
                             prompt_intent="When is your mom's birthday?",
                             person_value=0.5, downstream_reach=3)
        ordinary = work_item(subject_ref="event:first-job", requested_field="start_date",
                             prompt_intent="When did that job start?",
                             person_value=0.5, downstream_reach=3)
        self.assertEqual(qp.score_work_item(birthday)["combined_score"],
                         qp.score_work_item(ordinary)["combined_score"])
        self.assertNotIn("birth", str(qp.WORK_ITEM_PLACEMENT_GAIN))

    def test_ranking_is_total_so_a_rebuild_produces_the_same_order(self):
        twins = [work_item(subject_ref=f"event:{name}", person_value=0.9, downstream_reach=6)
                 for name in ("alpha", "beta", "gamma")]
        first = [row["work_item_id"] for row in
                 qp.queue_candidates(twins, question_bank_text=EMPTY_BANK)]
        second = [row["work_item_id"] for row in
                  qp.queue_candidates(list(reversed(twins)), question_bank_text=EMPTY_BANK)]
        self.assertEqual(first, second)
        self.assertEqual(first, sorted(first))

    def test_the_cadence_cap_is_still_one_timeline_question_a_week(self):
        """§8.5: existing queue cadence may initially allow no more than one
        timeline-origin question per week; change only from evidence. Nothing
        in wave F is that evidence."""
        self.assertEqual(qp.max_counts(8, qp.GROUP_CAPS)["timeline"], 1)
        self.assertEqual(qp.max_counts(40, qp.GROUP_CAPS)["timeline"], 1)


class LossProtectionTests(unittest.TestCase):
    """§2.4: loss discovery is offer-only, and a rule you can outbid is not a rule."""

    def test_the_generic_loss_discovery_opener_never_enters_the_queue(self):
        opener = work_item(subject_ref="landmark:losses",
                           prompt_intent="loss_discovery",
                           person_value=1.0, context_fit=1.0, downstream_reach=99)
        self.assertTrue(qp.is_loss_discovery(opener))
        self.assertEqual(qp.queue_candidates([opener], question_bank_text=EMPTY_BANK), [])

    def test_it_is_refused_even_when_its_minter_listed_the_daily_surface(self):
        """The refusal is not "it happens to omit daily_question" — a wrong
        surface list is exactly the bug this rule has to survive."""
        opener = work_item(subject_ref="landmark:losses", prompt_intent="loss_discovery",
                           allowed_surfaces=["timeline", "daily_question"],
                           person_value=1.0)
        self.assertEqual(qp.queue_candidates([opener], question_bank_text=EMPTY_BANK), [])

    def test_a_named_person_who_died_is_an_ordinary_contextual_question(self):
        """Once the person names someone, §2.4 says that person participates in
        normal questions — the refusal keys off the GENERIC opener, never off
        the subject of loss."""
        named = work_item(subject_ref="person:grandma-ruth",
                          prompt_intent="When did your grandmother die?",
                          person_value=0.8, context_fit=0.8, downstream_reach=5)
        self.assertFalse(qp.is_loss_discovery(named))
        self.assertTrue(qp.queue_candidates([named], question_bank_text=EMPTY_BANK))

    def test_an_item_that_lists_no_daily_surface_stays_off_the_daily_queue(self):
        offer_only = work_item(allowed_surfaces=["timeline"], person_value=1.0,
                               downstream_reach=99)
        self.assertEqual(qp.queue_candidates([offer_only], question_bank_text=EMPTY_BANK), [])


class OneIdentityTests(unittest.TestCase):
    """§2.3, §5.4: one work_item_id across Timeline, whisper and daily question."""

    def test_a_keystone_and_the_gap_it_resolves_are_the_same_item(self):
        keystone = qp.work_item_from_keystone(KEYSTONE, now=NOW)
        gap_id = ap._gap_work_item_id(  # noqa: SLF001
            {"anchor": "period:mesa", "unknown_key": "unplaced:mesa-move"})
        self.assertTrue(gap_id)
        self.assertEqual(keystone["work_item_id"], gap_id)

    def test_an_anchorless_gap_still_gets_a_stable_identity_of_its_own(self):
        first = ap._gap_work_item_id({"unknown_key": "unplaced:the-lost-years"})  # noqa: SLF001
        second = ap._gap_work_item_id({"unknown_key": "unplaced:the-lost-years"})  # noqa: SLF001
        self.assertTrue(first)
        self.assertEqual(first, second)

    def test_a_gap_about_nothing_gets_no_identity_rather_than_a_shared_one(self):
        """An id derived from nothing would collide every anchorless gap into
        one item, which is worse than having no id."""
        self.assertEqual(qp.timeline_work_item_id(), "")
        self.assertEqual(ap._gap_work_item_id({}), "")  # noqa: SLF001

    def test_the_whisper_carries_the_id(self):
        intent = ap._whisper_intent({  # noqa: SLF001
            "kind": "unplaced_events", "period": "mesa", "anchor": "period:mesa",
            "unknown_key": "unplaced:mesa-move", "leverage": 14, "anchors": [],
            "keystone": KEYSTONE})
        self.assertEqual(intent["kind"], "timeline_gap")
        self.assertEqual(intent["work_item_id"],
                         qp.work_item_from_keystone(KEYSTONE, now=NOW)["work_item_id"])
        self.assertEqual(intent["question_id"], "tl:mesa",
                         "the tl: identity survives beside the work-item id")

    def test_the_minted_bank_row_carries_both_identities(self):
        keystone = qp.work_item_from_keystone(KEYSTONE, now=NOW)
        row = qp.mint_work_item_question(keystone, next_question_id=lambda cat: f"{cat}1",
                                         minted_at=NOW)
        self.assertIn("timeline_probe: tl:mesa", row["line"])
        self.assertIn(f"work_item: {keystone['work_item_id']}", row["line"])
        text = ti.insert_keystone_question(EMPTY_BANK, row)
        # every v196 reader still sees exactly what it saw
        index = ti.timeline_probe_index(text)
        self.assertEqual(index["T1"]["question_id"], "tl:mesa")
        self.assertEqual(index["T1"]["leverage"], 14)
        # and the new reader finds the work item
        self.assertEqual(qp.bank_work_items(text)[keystone["work_item_id"]]["bank_id"], "T1")

    def test_a_pre_wave_f_row_derives_its_identity_from_the_anchor_it_has(self):
        """No migration exists because none is needed: a bank minted by v196
        dedupes and closes exactly like one minted today."""
        legacy = ti.insert_keystone_question(EMPTY_BANK, ti.mint_keystone_question(
            KEYSTONE, next_question_id=lambda cat: f"{cat}1", minted_at=NOW))
        self.assertNotIn("work_item:", legacy)
        keystone = qp.work_item_from_keystone(KEYSTONE, now=NOW)
        self.assertIn(keystone["work_item_id"], qp.bank_work_items(legacy))

    def test_an_ordinary_work_item_mints_without_any_keystone_behind_it(self):
        item = work_item(person_value=0.9, downstream_reach=4)
        row = qp.mint_work_item_question(item, next_question_id=lambda cat: f"{cat}1",
                                         minted_at=NOW)
        self.assertEqual(row["group"], "timeline")
        self.assertEqual(row["text"], item["prompt_intent"])
        self.assertIn(f"work_item: {item['work_item_id']}", row["line"])

    def test_an_item_with_nothing_to_ask_mints_nothing(self):
        self.assertIsNone(qp.mint_work_item_question(
            {"work_item_id": "work:x"}, next_question_id=lambda cat: "T1"))


class NoSelfCompetitionTests(unittest.TestCase):
    """§2.3, §10: the same item is never main question AND whisper."""

    GAP = {"kind": "unplaced_events", "period": "mesa", "anchor": "period:mesa",
           "unknown_key": "unplaced:mesa-move", "leverage": 14, "anchors": [],
           "keystone": KEYSTONE}
    OTHER = {"kind": "all_undated", "period": "childhood", "anchor": "period:childhood",
             "unknown_key": "undated:childhood", "leverage": 9, "anchors": []}

    def used(self):
        return {"gaps": 0, "gap_max": 3, "gap_keys": set(), "place_keys": set()}

    def test_the_days_own_item_is_not_whispered_back_at_the_person(self):
        asking = qp.work_item_from_keystone(KEYSTONE, now=NOW)["work_item_id"]
        item = {"question_id": "T1", "category": "T", "work_item_id": asking}
        intents = ap._timeline_gap_intent(  # noqa: SLF001
            item, {"timeline_gaps": [self.GAP]}, self.used())
        self.assertEqual(intents, [], "the day is already asking this exact item")

    def test_a_different_item_is_still_whispered(self):
        asking = qp.work_item_from_keystone(KEYSTONE, now=NOW)["work_item_id"]
        item = {"question_id": "T1", "category": "T", "work_item_id": asking}
        [intent] = ap._timeline_gap_intent(  # noqa: SLF001
            item, {"timeline_gaps": [self.GAP, self.OTHER]}, self.used())
        self.assertNotEqual(intent["work_item_id"], asking)
        self.assertEqual(intent["gap_kind"], "all_undated")

    def test_suppression_is_by_identity_and_a_question_without_one_suppresses_nothing(self):
        item = {"question_id": "A1", "category": "A"}
        [intent] = ap._timeline_gap_intent(  # noqa: SLF001
            item, {"timeline_gaps": [self.GAP]}, self.used())
        self.assertEqual(intent["gap_kind"], "unplaced_events")

    def test_the_projections_own_duplicate_detector_agrees(self):
        asking = qp.work_item_from_keystone(KEYSTONE, now=NOW)
        self.assertEqual(tp.surfaces_conflict([asking, asking]), (asking["work_item_id"],))
        self.assertEqual(tp.surfaces_conflict([asking]), ())


class AnswerOnceTests(unittest.TestCase):
    """§2.3, §10: answering on any surface closes the item everywhere."""

    def setUp(self):
        self.item = qp.work_item_from_keystone(KEYSTONE, now=NOW)
        row = qp.mint_work_item_question(self.item, next_question_id=lambda cat: f"{cat}1",
                                         minted_at=NOW)
        self.bank = ti.insert_keystone_question(EMPTY_BANK, row)
        self.answered = self.bank.replace("- [ ] T1:", "- [x] T1:")

    def test_answering_closes_the_queue_candidate(self):
        self.assertEqual(qp.work_item_states_from_bank(self.answered)[self.item["work_item_id"]],
                         "answered")
        self.assertEqual(qp.queue_candidates([self.item], question_bank_text=self.answered), [])

    def test_an_asked_but_unanswered_item_is_offered_and_not_re_minted(self):
        """Asked once, answered once — the bank's own mechanism, not a second."""
        self.assertEqual(qp.work_item_states_from_bank(self.bank)[self.item["work_item_id"]],
                         "offered")
        self.assertEqual(qp.queue_candidates([self.item], question_bank_text=self.bank), [])

    def test_the_state_travels_back_onto_the_items(self):
        [closed] = qp.close_answered_work_items([self.item], question_bank_text=self.answered)
        self.assertEqual(closed["state"], "answered")
        self.assertEqual(closed["work_item_id"], self.item["work_item_id"])

    def test_an_item_the_bank_has_never_seen_is_untouched(self):
        unseen = work_item()
        [same] = qp.close_answered_work_items([unseen], question_bank_text=self.answered)
        self.assertEqual(same["state"], "open")

    def test_an_answered_item_is_not_a_candidate_however_it_scores(self):
        loud = {**self.item, "person_value": 1.0, "context_fit": 1.0}
        self.assertEqual(qp.queue_candidates([loud], question_bank_text=self.answered), [])


class MintingTests(unittest.TestCase):
    """The generalized minting path, and the guards that keep it harmless."""

    def test_the_earned_items_are_minted_in_score_order(self):
        best = work_item(subject_ref="event:wedding", person_value=1.0,
                         context_fit=1.0, downstream_reach=12,
                         prompt_intent="When did you and Katie get married?")
        good = work_item(subject_ref="event:first-apartment", person_value=0.8,
                         context_fit=0.6, downstream_reach=6,
                         prompt_intent="When did you move into that first apartment?")
        weak = work_item(subject_ref="event:haircut", kind="precision_gap",
                         person_value=0.1, context_fit=0.1, interaction_cost=0.8,
                         prompt_intent="Which month was that haircut?")
        minted = qp.mint_queue_questions(work_items=[good, weak, best],
                                         question_bank_text=EMPTY_BANK)
        self.assertEqual([row["text"] for row in minted],
                         [best["prompt_intent"], good["prompt_intent"]])
        self.assertEqual([row["id"] for row in minted], ["T1", "T2"])

    def test_nothing_earned_mints_nothing(self):
        weak = work_item(kind="precision_gap", person_value=0.05, context_fit=0.05,
                         interaction_cost=0.9)
        self.assertEqual(qp.mint_queue_questions(work_items=[weak],
                                                 question_bank_text=EMPTY_BANK), [])

    def test_the_keystone_name_still_works_and_is_the_same_path(self):
        """v196's entry point survives — a keystone simply has no private route
        any more."""
        source = (SYSTEM / "question_planner.py").read_text(encoding="utf-8")
        body = source[source.index("def mint_keystone_questions"):]
        body = body[:body.index("\ndef ", 1)]
        self.assertIn("mint_queue_questions(dry_run=dry_run)", body)

    def test_every_guarded_read_degrades_to_no_timeline_questions(self):
        original = sys.modules.get("timeline_interaction")
        sys.modules["timeline_interaction"] = object()  # no index, no minter
        try:
            self.assertEqual(qp.current_timeline_probes(), {})
            self.assertEqual(qp.mint_keystone_questions(), [])
            self.assertEqual(qp.mint_queue_questions(work_items=[work_item()],
                                                     question_bank_text=EMPTY_BANK), [])
        finally:
            if original is None:
                sys.modules.pop("timeline_interaction", None)
            else:
                sys.modules["timeline_interaction"] = original

    def test_a_broken_projection_never_breaks_the_identity_derivation(self):
        original = sys.modules.get("temporal_projection")
        sys.modules["temporal_projection"] = object()
        try:
            self.assertEqual(qp.timeline_work_item_id(anchor="period:mesa"), "")
            self.assertIsNone(qp.work_item_from_keystone(KEYSTONE, now=NOW))
        finally:
            if original is None:
                sys.modules.pop("temporal_projection", None)
            else:
                sys.modules["temporal_projection"] = original


class QueueWiringTests(unittest.TestCase):
    """The identity reaches the week, which is what the whisper lane reads."""

    def test_a_timeline_probe_entry_carries_its_work_item_id_into_the_queue(self):
        keystone = qp.work_item_from_keystone(KEYSTONE, now=NOW)
        data = qp.build_queue(limit=8, arc_max=2, seed=11)
        bank_ids = [row["question_id"] for row in data["queue"]]
        self.assertTrue(bank_ids)
        probes = {bank_ids[0]: {"question_id": "tl:mesa", "anchor": "period:mesa",
                                "leverage": 14}}
        marked = qp.build_queue(limit=8, arc_max=2, seed=11, timeline_probes=probes)
        entry = next(row for row in marked["queue"] if row["question_id"] == bank_ids[0])
        self.assertEqual(entry["work_item_id"], keystone["work_item_id"])
        self.assertIn(keystone["work_item_id"], marked["allocation"]["work_items"]["queued"])

    def test_the_week_records_the_formula_it_was_built_under(self):
        data = qp.build_queue(limit=8, arc_max=2, seed=11)
        block = data["allocation"]["work_items"]
        self.assertEqual(block["score_version"], qp.WORK_ITEM_SCORE_VERSION)
        self.assertEqual(block["threshold"],
                         qp.DEFAULT_LANE_POLICY["work_item_queue_threshold"])
        self.assertEqual(block["weights"], dict(qp.DEFAULT_WORK_ITEM_WEIGHTS))

    def test_no_timeline_probe_leaves_the_week_unchanged(self):
        without = qp.build_queue(limit=8, arc_max=2, seed=11)
        with_empty = qp.build_queue(limit=8, arc_max=2, seed=11, timeline_probes={})
        self.assertEqual([q["question_id"] for q in without["queue"]],
                         [q["question_id"] for q in with_empty["queue"]])
        self.assertEqual(with_empty["allocation"]["work_items"]["queued"], [])


# --------------------------------------------------------------------------
# The wave D seam — the adapter against the REAL derivation (v224)
# --------------------------------------------------------------------------


def _revision(seed: str) -> str:
    return "sha256:" + hashlib.sha256(seed.encode("utf-8")).hexdigest()


def claim(**overrides) -> dict:
    """One validated claim, in `temporal_timeline`'s own fixture shape."""
    source = overrides.pop("source", "src-conversation-1")
    seed = overrides.pop("seed", source)
    payload = {
        "source_kind": "conversation",
        "source_ref": {"source_id": source, "revision": _revision(seed)},
        "evidence": [{"quote": overrides.pop("quote", "a sentence from the conversation")}],
        "extractor_version": "listener:1",
        "created_at": "2026-08-26T00:00:00Z",
        "basis": "explicit",
        "confidence": 0.9,
        "status": "active",
    }
    payload.update(overrides)
    return tc.validate_temporal_claim(payload)


def derive(*claims, **kwargs):
    kwargs.setdefault("now", "2026-08-26T12:00:00Z")
    return tt.derive_calculated_timeline(
        {"version": ts.INDEX_VERSION, "claims": [dict(row) for row in claims]}, **kwargs)


def waiting_on_an_anchor(count: int = 3):
    """`count` events all waiting on one unresolved anchor — a high-reach
    missing_anchor, which is the shape wave F exists to admit."""
    return [claim(claim_type="relative_order", subject_mention=f"thing {index}",
                  event_kind="transition",
                  temporal_value={"relation": "after", "anchors": ["the big move"]},
                  seed=f"waiting-{index}")
            for index in range(count)]


class WaveDSeamTests(unittest.TestCase):
    """F1 consumes wave D's real output, not a hand-written stand-in."""

    def test_every_derived_work_item_carries_a_prompt_intent(self):
        """The adapter's stated requirement on D1: an item with nothing to ask
        mints nothing, so an item without a prompt is invisible work."""
        result = derive(*waiting_on_an_anchor(),
                        claim(claim_type="date", subject_mention="Katie",
                              event_kind="married", temporal_value="2004", seed="wed"))
        self.assertTrue(result.work_items)
        for row in result.work_items:
            self.assertTrue(str(row.get("prompt_intent") or "").strip(),
                            f"{row['kind']} item minted with nothing to ask")

    def test_the_projection_shape_is_consumed_as_published(self):
        result = derive(*waiting_on_an_anchor())
        items = qp.work_items_from_projection(result.to_dict())
        self.assertTrue(items)
        by_id = {row["work_item_id"]: row for row in items}
        self.assertEqual(set(by_id), {row["work_item_id"] for row in result.work_items})
        anchor = next(row for row in items if row["kind"] == "missing_anchor")
        self.assertEqual(anchor["downstream_reach"],
                         result.reach[anchor["work_item_id"]],
                         "the RAW count travels, as wave D kept it for us to calibrate against")

    def test_a_bare_list_of_items_is_accepted_too(self):
        result = derive(*waiting_on_an_anchor())
        items = qp.work_items_from_projection([dict(row) for row in result.work_items])
        self.assertEqual({row["work_item_id"] for row in items},
                         {row["work_item_id"] for row in result.work_items})

    def test_reach_is_counted_once_not_twice(self):
        """v224 states `system_value` as `reach / REACH_SATURATION` — it IS the
        downstream component. Scoring it as placement gain as well would count
        one quantity twice and leave placement gain unexpressed."""
        result = derive(*waiting_on_an_anchor())
        anchor = next(row for row in qp.work_items_from_projection(result.to_dict())
                      if row["kind"] == "missing_anchor")
        score = qp.score_work_item(anchor)
        self.assertEqual(score["reach_source"], "derivation")
        self.assertAlmostEqual(score["components"]["downstream_reach"],
                               anchor["system_value"], places=6)
        self.assertEqual(score["components"]["placement_gain"],
                         qp.WORK_ITEM_PLACEMENT_GAIN["missing_anchor"])
        self.assertEqual(score["reach"], anchor["downstream_reach"])

    def test_a_keystone_still_normalizes_its_own_raw_leverage(self):
        keystone = qp.work_item_from_keystone(KEYSTONE, now=NOW)
        score = qp.score_work_item(keystone)
        self.assertEqual(score["reach_source"], "leverage")
        self.assertEqual(score["reach"], KEYSTONE["leverage"])

    def test_a_high_reach_derived_gap_earns_the_slot(self):
        """§10 end to end: the substrate implies a question, and it reaches the
        daily queue on its value with no keystone anywhere in the story."""
        result = derive(*waiting_on_an_anchor(5))
        items = qp.work_items_from_projection(result.to_dict())
        ranked = qp.queue_candidates(items, question_bank_text=EMPTY_BANK)
        self.assertTrue(ranked)
        self.assertEqual(ranked[0]["kind"], "missing_anchor")
        row = qp.mint_work_item_question(ranked[0], next_question_id=lambda cat: f"{cat}1",
                                         minted_at=NOW)
        self.assertIn(f"work_item: {ranked[0]['work_item_id']}", row["line"])
        self.assertEqual(row["text"], ranked[0]["prompt_intent"])

    def test_wave_ds_own_score_is_kept_beside_wave_fs(self):
        result = derive(*waiting_on_an_anchor(5))
        items = qp.work_items_from_projection(result.to_dict())
        [candidate] = [row for row in qp.queue_candidates(items, question_bank_text=EMPTY_BANK)
                       if row["kind"] == "missing_anchor"]
        derived = next(row for row in result.work_items
                       if row["work_item_id"] == candidate["work_item_id"])
        self.assertEqual(candidate["derivation_score"], derived["combined_score"])
        self.assertEqual(candidate["combined_score"], candidate["score"]["combined_score"])

    LOSS_CLAIM = dict(claim_type="relative_order", subject_mention="somebody I lost",
                      event_kind="loss",
                      temporal_value={"relation": "before", "anchors": ["the move"]},
                      seed="loss")

    def test_a_generic_loss_question_from_the_derivation_never_reaches_the_queue(self):
        """§2.4 across the seam. The DIVISION OF AUTHORITY matters here and the
        test states it: wave D holds the event kind and the resolution fact, so
        wave D decides that this item is discovery and says so in
        `allowed_surfaces` — the exact mechanism v220 names. Wave F honors that
        verdict; it does not re-derive it from the prompt's wording, which would
        make the loss rule depend on phrasing."""
        items = qp.work_items_from_projection(derive(claim(**self.LOSS_CLAIM)).to_dict())
        about_the_loss = [row for row in items
                          if "lost" in str(row.get("subject_ref") or "")]
        self.assertTrue(about_the_loss, "the fixture must actually ask about the loss")
        for row in about_the_loss:
            self.assertEqual(tuple(row["allowed_surfaces"]), tt.LOSS_DISCOVERY_SURFACES)
        queued = qp.queue_candidates(items, question_bank_text=EMPTY_BANK)
        self.assertEqual([row for row in queued if row in about_the_loss], [])

    def test_the_other_question_in_a_loss_conversation_is_still_an_ordinary_one(self):
        """§2.4 is a rule about the LOSS question, not a quarantine on the
        conversation: "when was the move?" is an ordinary anchor question even
        when the sentence that produced it was about a loss."""
        also_waiting = [claim(claim_type="relative_order", subject_mention=f"thing {n}",
                              event_kind="transition",
                              temporal_value={"relation": "after", "anchors": ["the move"]},
                              seed=f"also-{n}") for n in range(4)]
        items = qp.work_items_from_projection(
            derive(claim(**self.LOSS_CLAIM), *also_waiting).to_dict())
        move = next(row for row in items if "the move" in str(row.get("subject_ref") or ""))
        self.assertIn("daily_question", move["allowed_surfaces"])
        self.assertFalse(qp.is_loss_discovery(move))
        self.assertIn(move["work_item_id"],
                      [row["work_item_id"] for row in
                       qp.queue_candidates(items, question_bank_text=EMPTY_BANK)])

    def test_one_event_waiting_is_not_enough_and_that_is_the_gate_working(self):
        """The same anchor question, with only the loss waiting on it, does not
        clear the threshold — §2.3's "ordinary low-value gaps remain on
        Timeline". Refused by VALUE, not by the loss rule: the distinction is
        the whole difference between a queue and a filter."""
        items = qp.work_items_from_projection(derive(claim(**self.LOSS_CLAIM)).to_dict())
        move = next(row for row in items if "the move" in str(row.get("subject_ref") or ""))
        self.assertFalse(qp.is_loss_discovery(move))
        self.assertIn("daily_question", move["allowed_surfaces"])
        self.assertLess(qp.score_work_item(move)["combined_score"],
                        qp.DEFAULT_LANE_POLICY["work_item_queue_threshold"])

    def test_wave_fs_own_loss_refusal_covers_the_path_wave_d_does_not_mint(self):
        """The two refusals are not redundant, and neither is dead: wave D
        refuses a DERIVED loss item by surface; wave F refuses a hand-minted
        generic opener — the Losses offer card — by name, whatever surfaces its
        minter listed. Nothing hand-mints one today; the rule is what makes it
        safe for something to start."""
        opener = work_item(subject_ref="landmark:losses", prompt_intent="loss_discovery",
                           allowed_surfaces=["timeline", "daily_question"])
        self.assertTrue(qp.is_loss_discovery(opener))
        self.assertEqual(qp.queue_candidates([opener], question_bank_text=EMPTY_BANK), [])

    def test_a_named_loss_is_an_ordinary_candidate_again(self):
        roster = {"type": "person", "entities": [{"name": "Aunt Della", "slug": "aunt-della"}]}
        death = claim(claim_type="date", subject_mention="Aunt Della", event_kind="death",
                      temporal_value="2011", seed="della")
        result = derive(death, roster_snapshot=roster)
        items = qp.work_items_from_projection(result.to_dict())
        gap = next(row for row in items if row["kind"] == "precision_gap")
        self.assertIn("daily_question", gap["allowed_surfaces"])
        self.assertFalse(qp.is_loss_discovery(gap))
        self.assertFalse(ident.is_unresolved_ref(gap["subject_ref"]))
        # It is a candidate on its merits — and sensitivity is doing real work,
        # which is the point of it being a component rather than a veto.
        self.assertGreaterEqual(gap["sensitivity"], 0.8)

    def test_no_contradiction_reaches_the_daily_queue_yet(self):
        """The named honest gap: for a contradiction the derivation states
        `system_value` as SEVERITY, not reach. Inert while Mirror's daily
        convergence is deferred — pinned so it cannot become live silently."""
        self.assertNotIn("daily_question", tt.SURFACES_BY_KIND["contradiction"])
        first = claim(claim_type="date", subject_mention="Katie", event_kind="married",
                      temporal_value="2004", seed="a")
        second = claim(claim_type="date", subject_mention="Katie", event_kind="married",
                       temporal_value="2009", seed="b", source="src-conversation-2")
        items = qp.work_items_from_projection(derive(first, second).to_dict())
        clashes = [row for row in items if row["kind"] == "contradiction"]
        self.assertTrue(clashes, "the fixture must actually contradict")
        for row in clashes:
            self.assertNotIn("daily_question", row["allowed_surfaces"])
        self.assertEqual([row for row in qp.queue_candidates(items, question_bank_text=EMPTY_BANK)
                          if row["kind"] == "contradiction"], [])

    def test_a_projection_written_by_a_stranger_degrades_row_by_row(self):
        result = derive(*waiting_on_an_anchor())
        payload = result.to_dict()
        payload["work_items"] = [{"kind": "nonsense"}, "not a mapping", *payload["work_items"]]
        items = qp.work_items_from_projection(payload)
        self.assertEqual(len(items), len(result.work_items))

    def test_an_empty_or_missing_projection_is_simply_no_items(self):
        self.assertEqual(qp.work_items_from_projection(None), [])
        self.assertEqual(qp.work_items_from_projection({}), [])
        self.assertEqual(qp.work_items_from_projection({"work_items": []}), [])


if __name__ == "__main__":
    unittest.main()
