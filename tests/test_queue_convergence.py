"""Cut 5b — one chooser: gap and landmark questions reach the queue by value.

Owner ruling **R2** (2026-09-03) reverses `README.md` L288 (*"Timeline/Mirror
gap findings … never enter the bank themselves"*) for anything that clears the
shared bar, and only for that:

    *Landmark and timeline questions may enter the daily queue, and may
    surface as whispers, when they pass the shared value threshold.*

So these tests are about a door with four locks on it, not about a new lane:

* the ENTRY RULE — leverage at or above the one dial, not `offer_only`, not
  already in the bank, not dismissed by the owner;
* the WEIGHT — `leverage / timeline_leverage_per_story`, v196's exchange rate,
  unchanged;
* the CAPS — one landmark question minted per build, the weekly `timeline`
  group cap still one asked question, the whisper cap unchanged;
* the CLOSURE — a filed landmark checks the row off, and a rebuild mints
  nothing in its place.

The high-leverage fixture is Cut 5a's own `MesaVault`: a residence ladder the
legacy surface called "all filled in", one stay with no end, five events
waiting inside it — leverage 6, exactly the bar.

Synthetic data only; NEVER references ~/Workspace/dave.
"""

from __future__ import annotations

import importlib.util
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SYSTEM = ROOT / "system"
sys.path.insert(0, str(SYSTEM))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import landmark_opportunities as lo  # noqa: E402
import landmark_projection as lp  # noqa: E402
import temporal_publication as pub  # noqa: E402
import timeline_candidates as tcand  # noqa: E402
import timeline_interaction as ti  # noqa: E402

from test_landmark_opportunities import BAR, MesaVault, year  # noqa: E402


def load(name):
    """A fresh module instance, as `tests/test_work_item_queue.py` loads one."""
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

NOW = "2026-09-01T12:00:00Z"
EMPTY_BANK = "# Questions\n\n## A: Origins\n\n- [ ] A1: Where does your story start?\n"


def opportunity(**overrides) -> dict:
    """One published `landmark_opportunities` row, in 5a's own shape."""
    row = {
        "id": "lo:" + "a" * 24,
        "domain": "residences",
        "kind": "span_open_end",
        "subject": "node:mesa",
        "subject_kind": "episode",
        "label": "the Mesa house",
        "question": "When did you move out of the Mesa house?",
        "ladder_rung": "span",
        "leverage": BAR,
        "resolves": [f"node:m{n}" for n in range(BAR - 1)],
        "sensitivity": lo.SENSITIVITY_ORDINARY,
        "order": 3,
    }
    row.update(overrides)
    return row


def keystone(**overrides) -> dict:
    """One published `keystones` row, in Cut 3a's own shape."""
    row = {
        "id": "tl:kitchen-fire",
        "anchor": "node:kitchen-fire",
        "node_ref": "node:kitchen-fire",
        "work_item_id": "",
        "leverage": BAR + 2,
        "gain": BAR + 1,
        "resolves": [f"node:k{n}" for n in range(BAR + 1)],
        "question": "When was the kitchen fire?",
    }
    row.update(overrides)
    return row


def view(*, opportunities=(), keystones=(), work_items=()) -> dict:
    return {"published": True,
            "landmark_opportunities": tuple(opportunities),
            "keystones": tuple(keystones),
            "work_items": tuple(work_items)}


# --------------------------------------------------------------------------
# The entry rule
# --------------------------------------------------------------------------


class TheEntryRuleTests(unittest.TestCase):
    """Above the bar, not sensitive, not already asked, not dismissed."""

    def test_a_high_leverage_opportunity_becomes_a_candidate(self):
        [row] = tcand.candidates_from_view(view(opportunities=[opportunity()]),
                                           question_bank_text=EMPTY_BANK, dismissed=())
        self.assertEqual(row["id"], "lo:" + "a" * 24)
        self.assertEqual(row["provenance"], tcand.PROVENANCE)
        self.assertEqual(row["source"], tcand.SOURCE_OPPORTUNITY)
        self.assertEqual(row["question"], "When did you move out of the Mesa house?")
        self.assertEqual(row["leverage"], BAR)
        self.assertEqual(row["domain"], "residences")
        self.assertEqual(row["ladder_rung"], "span")

    def test_a_low_leverage_gap_is_not_minted_at_all(self):
        """§8.2.10: ordinary gaps do not flood the queue."""
        low = opportunity(id="lo:" + "b" * 24, leverage=BAR - 1, resolves=["node:m0"])
        self.assertEqual(tcand.candidates_from_view(view(opportunities=[low]),
                                                    question_bank_text=EMPTY_BANK,
                                                    dismissed=()), [])

    def test_the_bar_is_exactly_the_dial_not_one_above_it(self):
        at_the_bar = opportunity(leverage=BAR)
        self.assertEqual(len(tcand.candidates_from_view(
            view(opportunities=[at_the_bar]), question_bank_text=EMPTY_BANK,
            dismissed=())), 1)

    def test_an_offer_only_opportunity_never_becomes_a_candidate(self):
        """§4.6: losses stay offer-only, however they score."""
        loss = opportunity(id="lo:" + "c" * 24, domain="losses",
                           kind="relationship_anchor", leverage=BAR * 3,
                           question="Roughly when did you lose Nana?",
                           sensitivity=lo.SENSITIVITY_OFFER_ONLY)
        self.assertEqual(tcand.candidates_from_view(view(opportunities=[loss]),
                                                    question_bank_text=EMPTY_BANK,
                                                    dismissed=()), [])

    def test_an_owner_dismissal_is_honoured(self):
        row = opportunity()
        self.assertEqual(tcand.candidates_from_view(view(opportunities=[row]),
                                                    question_bank_text=EMPTY_BANK,
                                                    dismissed=[row["id"]]), [])

    def test_a_dismissal_persists_across_rebuilds(self):
        """A human negative is durable state; a candidate is derived state."""
        import tempfile  # noqa: PLC0415

        path = Path(tempfile.mkdtemp(prefix="lifehug-dismissals-")) / "dismissed.json"
        row = opportunity()
        tcand.dismiss(row["id"], reason="not something I want to be asked", path=path)
        self.assertIn(row["id"], tcand.dismissed_ids(path=path))
        # A rebuild republishes the same opportunity under the same id …
        again = tcand.candidates_from_view(view(opportunities=[opportunity()]),
                                           question_bank_text=EMPTY_BANK,
                                           dismissed=tcand.dismissed_ids(path=path))
        self.assertEqual(again, [])
        tcand.undismiss(row["id"], path=path)
        self.assertEqual(tcand.dismissed_ids(path=path), set())

    def test_a_row_the_bank_already_holds_is_not_minted_twice(self):
        row = opportunity()
        item = tcand.work_items([row], now=NOW)[0]
        minted = qp.mint_work_item_question(item, next_question_id=lambda cat: f"{cat}1",
                                            minted_at=NOW)
        bank = ti.insert_keystone_question(EMPTY_BANK, minted)
        self.assertEqual(tcand.candidates_from_view(view(opportunities=[row]),
                                                    question_bank_text=bank,
                                                    dismissed=()), [])

    def test_an_answered_row_is_never_re_asked(self):
        row = opportunity()
        item = tcand.work_items([row], now=NOW)[0]
        minted = qp.mint_work_item_question(item, next_question_id=lambda cat: f"{cat}1",
                                            minted_at=NOW)
        answered = ti.insert_keystone_question(EMPTY_BANK, minted).replace(
            "- [ ] T1:", "- [x] T1:")
        self.assertEqual(tcand.candidates_from_view(view(opportunities=[row]),
                                                    question_bank_text=answered,
                                                    dismissed=()), [])


class OneDialTests(unittest.TestCase):
    """§4.6: one base gain quantity feeds three hosts."""

    def test_the_threshold_is_the_queues_own_dial(self):
        self.assertEqual(tcand.entry_threshold(),
                         qp.DEFAULT_LANE_POLICY["timeline_leverage_per_story"])
        self.assertEqual(tcand.entry_threshold(), lo.default_threshold())

    def test_the_weight_is_leverage_over_the_dial(self):
        dial = qp.DEFAULT_LANE_POLICY["timeline_leverage_per_story"]
        self.assertEqual(qp.timeline_probe_weight(dial), 1.0)
        self.assertEqual(qp.timeline_probe_weight(dial * 2), 2.0)
        self.assertEqual(qp.timeline_probe_weight(0), 0.0)

    def test_the_provenance_has_one_spelling(self):
        self.assertEqual(tcand.PROVENANCE, qp.TIMELINE_GAIN_PROVENANCE)

    def test_the_module_reads_the_dial_and_never_copies_it(self):
        source = (SYSTEM / "timeline_candidates.py").read_text(encoding="utf-8")
        body = source[source.index("def entry_threshold"):]
        body = body[:body.index("\ndef ", 1)]
        self.assertIn("from question_planner import DEFAULT_LANE_POLICY", body)


# --------------------------------------------------------------------------
# Minting, weighting, and the caps
# --------------------------------------------------------------------------


class MintingTests(unittest.TestCase):
    """The bank row a candidate becomes, and what it carries."""

    def setUp(self):
        self.row = opportunity()
        self.items = tcand.work_items([self.row], now=NOW)

    def test_one_high_leverage_opportunity_mints_one_bank_row(self):
        minted = qp.mint_queue_questions(work_items=self.items,
                                         question_bank_text=EMPTY_BANK)
        self.assertEqual([r["text"] for r in minted],
                         ["When did you move out of the Mesa house?"])
        self.assertEqual(minted[0]["group"], ti.TIMELINE_GROUP)

    def test_the_row_is_asked_under_the_opportunitys_own_identity(self):
        [minted] = qp.mint_queue_questions(work_items=self.items,
                                           question_bank_text=EMPTY_BANK)
        self.assertEqual(minted["question_id"], self.row["id"])
        self.assertIn(f"timeline_probe: {self.row['id']};", minted["line"])
        bank = ti.insert_keystone_question(EMPTY_BANK, minted)
        index = ti.timeline_probe_index(bank)
        self.assertEqual([r["question_id"] for r in index.values()], [self.row["id"]])

    def test_the_row_carries_the_timeline_gain_provenance(self):
        [minted] = qp.mint_queue_questions(work_items=self.items,
                                           question_bank_text=EMPTY_BANK)
        self.assertEqual(minted["provenance"], tcand.PROVENANCE)
        bank = ti.insert_keystone_question(EMPTY_BANK, minted)
        [read_back] = qp.bank_work_items(bank).values()
        self.assertEqual(read_back["provenance"], tcand.PROVENANCE)

    def test_a_low_leverage_item_is_refused_by_the_entry_rule_too(self):
        """The rule holds however the item arrived, not only at the door."""
        weak = dict(self.items[0])
        weak["downstream_reach"] = BAR - 1
        weak.pop("leverage", None)
        self.assertEqual(qp.queue_candidates([weak], question_bank_text=EMPTY_BANK), [])

    def test_an_offer_only_item_is_refused_by_the_planner_as_well(self):
        sensitive = {**self.items[0], "offer_only": True}
        self.assertEqual(qp.queue_candidates([sensitive], question_bank_text=EMPTY_BANK), [])

    def test_at_most_one_landmark_question_is_minted_per_build(self):
        rows = [opportunity(id="lo:" + ch * 24, subject=f"node:{ch}",
                            label=f"house {ch}", leverage=BAR + n,
                            question=f"When did you move out of house {ch}?",
                            resolves=[f"node:{ch}{i}" for i in range(BAR + n - 1)])
                for n, ch in enumerate("def")]
        items = tcand.work_items(rows, now=NOW)
        self.assertEqual(len(items), 3)
        minted = qp.mint_queue_questions(work_items=items, question_bank_text=EMPTY_BANK)
        self.assertEqual(len(minted), tcand.LANDMARK_MINT_CAP)
        self.assertEqual(tcand.LANDMARK_MINT_CAP, 1)

    def test_the_view_door_applies_the_same_cap(self):
        rows = [opportunity(id="lo:" + ch * 24, subject=f"node:{ch}",
                            label=f"house {ch}", leverage=BAR + n,
                            resolves=[f"node:{ch}{i}" for i in range(BAR + n - 1)])
                for n, ch in enumerate("def")]
        chosen = tcand.candidates_from_view(view(opportunities=rows),
                                            question_bank_text=EMPTY_BANK, dismissed=())
        self.assertEqual(len(chosen), tcand.LANDMARK_MINT_CAP)
        self.assertEqual(chosen[0]["leverage"], BAR + 2)   # the best one


class TheKeystoneIsARealQueueEntryTests(unittest.TestCase):
    """lifehug-platform#586: the day's question can actually be a keystone."""

    def setUp(self):
        self.row = keystone()
        self.items = tcand.work_items([self.row], now=NOW)

    def test_a_keystone_from_the_calculated_view_mints_a_bank_row(self):
        [minted] = qp.mint_queue_questions(work_items=self.items,
                                           question_bank_text=EMPTY_BANK)
        self.assertEqual(minted["text"], "When was the kitchen fire?")
        self.assertEqual(minted["question_id"], "tl:kitchen-fire")
        self.assertEqual(minted["group"], ti.TIMELINE_GROUP)

    def test_the_entry_carries_the_tl_identity_and_the_weight(self):
        [minted] = qp.mint_queue_questions(work_items=self.items,
                                           question_bank_text=EMPTY_BANK)
        bank = ti.insert_keystone_question(EMPTY_BANK, minted)
        probes = ti.timeline_probe_index(bank)
        [probe] = probes.values()
        self.assertTrue(probe["question_id"].startswith(ti.KEYSTONE_ID_PREFIX))
        self.assertEqual(qp.timeline_probe_weight(probe["leverage"]),
                         (BAR + 2) / BAR)

    def test_a_queue_entry_carries_the_provenance_and_the_weight(self):
        data = qp.build_queue(limit=8, arc_max=2, seed=11)
        bank_ids = [row["question_id"] for row in data["queue"]]
        self.assertTrue(bank_ids)
        probes = {bank_ids[0]: {"question_id": "tl:kitchen-fire",
                                "anchor": "node:kitchen-fire",
                                "leverage": BAR,
                                "provenance": tcand.PROVENANCE}}
        marked = qp.build_queue(limit=8, arc_max=2, seed=11, timeline_probes=probes)
        entry = next(row for row in marked["queue"] if row["question_id"] == bank_ids[0])
        self.assertEqual(entry["provenance"], tcand.PROVENANCE)
        self.assertEqual(qp.timeline_probe_weight(BAR), 1.0)

    def test_the_weekly_group_cap_is_still_one_timeline_question(self):
        self.assertEqual(qp.max_counts(8, qp.GROUP_CAPS)["timeline"], 1)


# --------------------------------------------------------------------------
# Losses
# --------------------------------------------------------------------------


class LossesAreOfferOnlyTests(unittest.TestCase):
    def test_a_loss_opportunity_never_reaches_a_work_item(self):
        loss = opportunity(id="lo:" + "e" * 24, domain="losses",
                           sensitivity=lo.SENSITIVITY_OFFER_ONLY, leverage=BAR * 4)
        self.assertEqual(tcand.candidates_from_view(view(opportunities=[loss]),
                                                    question_bank_text=EMPTY_BANK,
                                                    dismissed=()), [])

    def test_the_generic_opener_is_still_refused_by_name(self):
        """Wave F's own refusal, untouched: a rule you can outbid is not a rule."""
        self.assertTrue(qp.is_loss_discovery({"prompt_intent": "loss_discovery"}))

    def test_an_offer_only_candidate_never_becomes_a_whisper_either(self):
        loss = opportunity(id="lo:" + "f" * 24, domain="losses",
                           sensitivity=lo.SENSITIVITY_OFFER_ONLY, leverage=BAR * 4)
        self.assertEqual(tcand.whisper_gaps(view(opportunities=[loss]),
                                            question_bank_text=EMPTY_BANK,
                                            dismissed=()), [])


# --------------------------------------------------------------------------
# Whispers — the same identity, the same question
# --------------------------------------------------------------------------


class WhisperTests(unittest.TestCase):
    """§4.6: whispers use the same candidate identity; stop rules unchanged."""

    def setUp(self):
        self.row = opportunity()
        self.gaps = tcand.whisper_gaps(view(opportunities=[self.row]),
                                       question_bank_text=EMPTY_BANK, dismissed=())

    def test_the_gap_carries_the_candidates_id_and_question(self):
        [gap] = self.gaps
        self.assertEqual(gap["question_id"], self.row["id"])
        self.assertEqual(gap["probe"]["text"], self.row["question"])
        self.assertEqual(gap["leverage"], BAR)

    def test_the_arc_cards_intent_is_the_same_thing(self):
        item = {"question_id": "A1", "category": "A", "focus": None}
        material = {"timeline_gaps": self.gaps}
        used = {"gaps": 0, "gap_max": 3, "gap_keys": set()}
        [intent] = ap._timeline_gap_intent(item, material, used)
        self.assertEqual(intent["kind"], "timeline_gap")
        self.assertEqual(intent["question_id"], self.row["id"])
        self.assertEqual(intent["probe"], self.row["question"])
        self.assertEqual(intent["provenance"], tcand.PROVENANCE)

    def test_at_most_one_whisper_per_card(self):
        second = opportunity(id="lo:" + "0" * 24, subject="node:phoenix",
                             label="the Phoenix house",
                             question="When did you move out of the Phoenix house?")
        gaps = tcand.whisper_gaps(view(opportunities=[self.row, second]),
                                  question_bank_text=EMPTY_BANK, dismissed=())
        self.assertEqual(len(gaps), 2)
        used = {"gaps": 0, "gap_max": 3, "gap_keys": set()}
        item = {"question_id": "A1", "category": "A", "focus": None}
        intents = ap._timeline_gap_intent(item, {"timeline_gaps": gaps}, used)
        self.assertEqual(len(intents), 1)
        self.assertEqual(used["gaps"], 1)

    def test_two_opportunities_are_two_gaps_not_one_kind(self):
        """The never-twice key is the identity, not the word 'landmark'."""
        second = opportunity(id="lo:" + "0" * 24, subject="node:phoenix",
                             label="the Phoenix house",
                             question="When did you move out of the Phoenix house?")
        gaps = tcand.whisper_gaps(view(opportunities=[self.row, second]),
                                  question_bank_text=EMPTY_BANK, dismissed=())
        used = {"gaps": 0, "gap_max": 3, "gap_keys": set()}
        asked = []
        for question_id in ("A1", "A2"):
            item = {"question_id": question_id, "category": "A", "focus": None}
            asked.extend(ap._timeline_gap_intent(item, {"timeline_gaps": gaps}, used))
        self.assertEqual(sorted(i["question_id"] for i in asked),
                         sorted([self.row["id"], second["id"]]))

    def test_the_weekly_gap_cap_still_bounds_the_week(self):
        gaps = tcand.whisper_gaps(view(opportunities=[self.row]),
                                  question_bank_text=EMPTY_BANK, dismissed=())
        used = {"gaps": 3, "gap_max": 3, "gap_keys": set()}
        item = {"question_id": "A1", "category": "A", "focus": None}
        self.assertEqual(ap._timeline_gap_intent(item, {"timeline_gaps": gaps}, used), [])

    def test_a_whisper_never_opens_with_a_calendar_year(self):
        """research.md §4 and `arc_planner.BANNED_PHRASE`, at the source."""
        yearly = opportunity(id="lo:" + "1" * 24, domain="family",
                             kind="relationship_anchor", subject="landmark:steph",
                             label="Steph", question="What year was Steph born?")
        self.assertEqual(tcand.whisper_gaps(view(opportunities=[yearly]),
                                            question_bank_text=EMPTY_BANK,
                                            dismissed=()), [])
        for gap in self.gaps:
            self.assertNotIn(ap.BANNED_PHRASE, gap["probe"]["text"].lower())

    def test_the_days_own_question_is_not_whispered_back(self):
        """Wave F's suppression rule, on a 5b candidate."""
        [gap] = self.gaps
        item = {"question_id": "A1", "category": "A", "focus": None,
                "work_item_id": gap["work_item_id"] or "work:mesa"}
        gap["work_item_id"] = item["work_item_id"]
        used = {"gaps": 0, "gap_max": 3, "gap_keys": set()}
        self.assertEqual(ap._timeline_gap_intent(item, {"timeline_gaps": [gap]}, used), [])


# --------------------------------------------------------------------------
# Legacy and calculated agree; the legacy path is the fallback
# --------------------------------------------------------------------------


class TheLegacyPathIsOnlyAFallbackTests(unittest.TestCase):
    def test_the_two_keystone_minters_agree_on_one_fixture(self):
        """One keystone row, two adapters, one question and one identity."""
        row = keystone()
        legacy = qp.work_item_from_keystone(
            {"anchor": row["anchor"], "question_id": row["id"],
             "label": row["anchor"], "leverage": row["leverage"],
             "probe": {"text": row["question"], "step": ""},
             "unknown_keys": row["resolves"], "anchors": []},
            now=NOW)
        [calculated] = tcand.work_items([row], now=NOW)
        self.assertEqual(calculated["work_item_id"], legacy["work_item_id"])
        self.assertEqual(calculated["prompt_intent"], legacy["prompt_intent"])
        legacy_row = qp.mint_work_item_question(
            legacy, next_question_id=lambda cat: f"{cat}1", minted_at=NOW)
        calculated_row = qp.mint_work_item_question(
            calculated, next_question_id=lambda cat: f"{cat}1", minted_at=NOW)
        self.assertEqual(legacy_row["text"], calculated_row["text"])
        self.assertEqual(legacy_row["question_id"], calculated_row["question_id"])

    def test_a_vault_with_no_projection_still_uses_the_legacy_keystones(self):
        self.assertFalse(tcand.view_has_projection({}))
        self.assertFalse(tcand.view_has_projection({"published": True}))
        self.assertTrue(tcand.view_has_projection(view(keystones=[keystone()])))
        source = (SYSTEM / "question_planner.py").read_text(encoding="utf-8")
        body = source[source.index("def current_work_items"):]
        body = body[:body.index("\ndef ", 1)]
        self.assertIn("_keystone_work_items(timeline_payload)", body)
        self.assertIn("_view_has_projection(view)", body)

    def test_the_calculated_supply_wins_over_the_raw_published_row(self):
        """One question, better words — never two questions."""
        row = opportunity(subject="node:mesa")
        raw = {"kind": "precision_gap", "state": "open", "subject_ref": "place/mesa",
               "event_ref": "node:mesa", "node_ref": "node:mesa",
               "requested_field": "date",
               "prompt_intent": "Do you know the year for the Mesa house?",
               "allowed_surfaces": ["timeline", "whisper", "daily_question"],
               "created_at": NOW}
        import temporal_projection as tp  # noqa: PLC0415

        published = tp.validate_temporal_work_item(raw, now=NOW)
        [item] = tcand.work_items([row], published=[published], now=NOW)
        self.assertEqual(item["work_item_id"], published["work_item_id"])
        self.assertEqual(item["prompt_intent"], row["question"])
        deduped = qp._dedupe_work_items([item, published])
        self.assertEqual(len(deduped), 1)
        self.assertEqual(deduped[0]["prompt_intent"], row["question"])

    def test_a_missing_bound_is_scored_as_a_placement_not_a_precision_gap(self):
        row = opportunity(subject="node:mesa")
        raw = {"kind": "precision_gap", "state": "open", "subject_ref": "place/mesa",
               "event_ref": "node:mesa", "node_ref": "node:mesa",
               "requested_field": "date",
               "prompt_intent": "Do you know the year for the Mesa house?",
               "allowed_surfaces": ["timeline", "whisper", "daily_question"],
               "created_at": NOW}
        import temporal_projection as tp  # noqa: PLC0415

        published = tp.validate_temporal_work_item(raw, now=NOW)
        [item] = tcand.work_items([row], published=[published], now=NOW)
        self.assertEqual(item["placement_gain"],
                         tcand.PLACEMENT_GAIN_BY_KIND["span_open_end"])
        self.assertGreaterEqual(qp.score_work_item(item)["combined_score"],
                                qp.DEFAULT_LANE_POLICY["work_item_queue_threshold"])


# --------------------------------------------------------------------------
# The whole path, on Cut 5a's own vault
# --------------------------------------------------------------------------


class TheMesaHouseReachesTheQueue(MesaVault):
    """The 5a fixture, carried one cut further: the opportunity is asked."""

    def setUp(self):
        super().setUp()
        self.publish()
        self.view = pub.calculated_view(self.vault)

    def test_the_served_view_offers_exactly_one_candidate(self):
        rows = tcand.candidates_from_view(self.view, question_bank_text=EMPTY_BANK,
                                          dismissed=())
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["question"], "When did you move out of the Mesa house?")
        self.assertEqual(rows[0]["leverage"], BAR)
        self.assertTrue(rows[0]["id"].startswith(lo.OPPORTUNITY_ID_PREFIX + ":"))

    def test_the_keystone_about_the_same_stay_is_not_a_second_question(self):
        """One gap, three names (`work:`, `tl:`, `lo:`) — one question."""
        self.assertEqual(len(self.view["keystones"]), 1)
        rows = tcand.candidates_from_view(self.view, question_bank_text=EMPTY_BANK,
                                          dismissed=())
        self.assertEqual([r["source"] for r in rows], [tcand.SOURCE_OPPORTUNITY])

    def test_it_mints_one_bank_row_in_the_timeline_group(self):
        items = tcand.from_view(self.view, question_bank_text=EMPTY_BANK)
        minted = qp.mint_queue_questions(work_items=items, question_bank_text=EMPTY_BANK)
        self.assertEqual(len(minted), 1)
        self.assertEqual(minted[0]["text"], "When did you move out of the Mesa house?")
        self.assertEqual(minted[0]["group"], ti.TIMELINE_GROUP)
        self.assertEqual(minted[0]["provenance"], tcand.PROVENANCE)
        self.assertEqual(qp.timeline_probe_weight(minted[0]["leverage"]), 1.0)

    def test_filing_the_answer_retires_the_row(self):
        items = tcand.from_view(self.view, question_bank_text=EMPTY_BANK)
        [minted] = qp.mint_queue_questions(work_items=items, question_bank_text=EMPTY_BANK)
        bank = ti.insert_keystone_question(EMPTY_BANK, minted)
        answer = {"domain": "residences", "label": "the Mesa house",
                  "city": "the Mesa house",
                  "span": {"start": year("1990"), "end": year("1992")}}
        retired = tcand.retire_for_landmark("residences", answer, view=self.view,
                                            question_bank_text=bank)
        self.assertEqual(retired, [minted["id"]])

    def test_a_rebuild_after_the_answer_mints_nothing_for_it(self):
        import episode_binder as eb  # noqa: PLC0415
        import temporal_store as ts  # noqa: PLC0415

        items = tcand.from_view(self.view, question_bank_text=EMPTY_BANK)
        [minted] = qp.mint_queue_questions(work_items=items, question_bank_text=EMPTY_BANK)
        answered = ti.insert_keystone_question(EMPTY_BANK, minted).replace(
            "- [ ] T1:", "- [x] T1:")
        lp.file_landmark_record(
            self.vault, "residences",
            {"domain": "residences", "label": "the Mesa house",
             "city": "the Mesa house", "address": "1220 E Palo Verde",
             "span": {"start": year("1990"), "end": year("1992")}},
            ordinal=3, now="2026-09-01T12:00:00Z",
        )
        ts.rebuild_active_index(self.vault)
        eb.bind_episodes(self.vault, apply=True, now="2026-09-01T12:00:00Z",
                         containment_authority="applied")
        self.publish()
        rebuilt = pub.calculated_view(self.vault)
        self.assertEqual(
            [r for r in rebuilt["landmark_opportunities"]
             if r["domain"] == "residences" and r["kind"].startswith("span")], [])
        self.assertEqual(tcand.from_view(rebuilt, question_bank_text=answered), [])

    def test_a_different_answer_does_not_retire_it(self):
        items = tcand.from_view(self.view, question_bank_text=EMPTY_BANK)
        [minted] = qp.mint_queue_questions(work_items=items, question_bank_text=EMPTY_BANK)
        bank = ti.insert_keystone_question(EMPTY_BANK, minted)
        other = {"domain": "residences", "label": "the Phoenix house",
                 "city": "the Phoenix house"}
        self.assertEqual(tcand.retire_for_landmark("residences", other, view=self.view,
                                                   question_bank_text=bank), [])


# --------------------------------------------------------------------------
# Shipped
# --------------------------------------------------------------------------


class TheModuleIsShippedTests(unittest.TestCase):
    def test_the_new_module_is_a_framework_file(self):
        version = json.loads((SYSTEM / "version.json").read_text(encoding="utf-8"))
        self.assertIn("system/timeline_candidates.py", version["framework_files"])

    def test_the_readme_no_longer_says_gaps_never_reach_the_bank(self):
        text = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertNotIn("lands in Cut 5b", text)
        self.assertIn("timeline-gain", text)

    def test_the_weekly_step_names_the_new_supply(self):
        text = (SYSTEM / "weekly_maintenance.sh").read_text(encoding="utf-8")
        self.assertIn("timeline-gain", text)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
