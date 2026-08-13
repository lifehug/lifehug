"""issue #118 — the weekly arc planner (Conversation Interaction, Wave 2 PR 5).

The daily Chat's ~3 exchanges become a coherent, pre-planned mini-arc: the
WEEKLY loop plans one arc card per queued question (opening framing + 2–4
typed follow-up intents) and the daily loop merely ATTACHES it, staying
AI-free by construction.

The convergence property (owner-set) is the load-bearing acceptance criteria
here: on a synthetic fixture vault carrying each gap type, every detectable
gap must have a named consumer that turns it into a conversation input.

Synthetic data only; NEVER references ~/Workspace/dave.
"""

from __future__ import annotations

import json
import subprocess
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SYSTEM = ROOT / "system"
sys.path.insert(0, str(SYSTEM))
sys.path.insert(0, str(ROOT / "tests"))

from tempdirs import symlink_free_tmp  # noqa: E402

import arc_planner  # noqa: E402
import book  # noqa: E402
import conversation  # noqa: E402
import question_planner  # noqa: E402
import timeline  # noqa: E402


def iso(moment: datetime) -> str:
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


NOW = datetime(2026, 8, 16, 9, 0, tzinfo=timezone.utc)


class VaultFixture:
    """A synthetic vault carrying every gap type the planner consumes."""

    def __init__(self, root: Path):
        self.root = root
        (root / "answers").mkdir(parents=True, exist_ok=True)
        (root / "state" / "classifications").mkdir(parents=True, exist_ok=True)
        (root / "wiki" / "self").mkdir(parents=True, exist_ok=True)

    # -- writers ---------------------------------------------------------
    def write_json(self, rel: str, data: object) -> None:
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")

    def write_text(self, rel: str, text: str) -> None:
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def answer(self, qid: str, body: str, answered_date: str = "2026-03-01") -> None:
        self.write_text(
            f"answers/{qid}.md",
            f"---\nquestion_id: \"{qid}\"\nanswered_date: \"{answered_date}\"\n"
            f"schema_version: 1\n---\n\n{body}\n",
        )

    def classification(self, qid: str, slots: dict[str, bool]) -> None:
        self.write_json(f"state/classifications/{qid}.json",
                        {"source_path": f"answers/{qid}.md", "scene_slots": slots})

    def queue(self, items: list[dict], *, generated_at: str | None = None,
              expires_at: str | None = None) -> None:
        self.write_json("state/question_queue.json", {
            "version": 3,
            "generated_at": generated_at or iso(NOW - timedelta(hours=1)),
            "expires_at": expires_at or iso(NOW + timedelta(days=8)),
            "queue": items,
        })

    def bank(self, rows: list[tuple[str, str, bool]]) -> None:
        """rows = [(qid, text, answered)] grouped into per-letter sections."""
        by_letter: dict[str, list[tuple[str, str, bool]]] = {}
        for qid, text, answered in rows:
            by_letter.setdefault(qid[0], []).append((qid, text, answered))
        names = {"A": "Origins (Childhood & Family)", "B": "Becoming",
                 "C": "Relationships & People", "D": "Purpose & Calling"}
        lines = ["# Life Hug — Question Bank", "", "Pass 1: Skeleton", "", "---", ""]
        for letter, entries in sorted(by_letter.items()):
            lines.append(f"## {letter}: {names.get(letter, letter)}")
            for qid, text, answered in entries:
                lines.append(f"- [{'x' if answered else ' '}] {qid}: {text}")
            lines.append("")
        self.write_text("question-bank.md", "\n".join(lines))


def queue_item(qid: str, **overrides) -> dict:
    item = {
        "question_id": qid,
        "category": qid[0],
        "group": "main",
        "focus": None,
        "source": "question_bank",
        "source_type": "bank",
        "story_function": "scene",
        "objective": None,
        "status": "queued",
        "reason": "focus main; scene story function; category coverage 20%",
    }
    item.update(overrides)
    return item


def timeline_payload(*, unplaced_events: int = 0, no_events_period: str | None = None,
                     all_undated_period: str | None = None) -> dict:
    """An assembled payload built with the REAL timeline.compute_gaps().

    The planner consumes timeline_data()'s assembled payload; assembling one
    here from the genuine gap function is what makes the convergence subtest
    an assertion about the real seam rather than about a hand-written dict.
    """
    periods: list[dict] = []
    event_lineup: dict[str, list[dict]] = {}
    entity_lineup: dict[str, list[dict]] = {}
    if no_events_period:
        periods.append({"slug": no_events_period, "name": "The Denver Years", "chrono": 1})
        event_lineup[no_events_period] = []
        entity_lineup[no_events_period] = [{"title": "Marbles"}]
    if all_undated_period:
        periods.append({"slug": all_undated_period, "name": "The Ghana Years", "chrono": 2})
        event_lineup[all_undated_period] = [{"description": "the move", "when_hint": ""}]
        entity_lineup[all_undated_period] = [{"title": "Accra"}]
    unplaced = [{"description": f"moment {n}"} for n in range(unplaced_events)]
    gaps = timeline.compute_gaps(periods, entity_lineup, event_lineup, [], unplaced)
    by_period: dict[str, list[dict]] = {}
    global_gaps: list[dict] = []
    for gap in gaps:
        if gap.get("period"):
            by_period.setdefault(gap["period"], []).append(gap)
        else:
            global_gaps.append(gap)
    return {"gaps_by_period": by_period, "global_gaps": global_gaps}


class BaseVaultTest(unittest.TestCase):
    """A queue of four questions with material for every intent kind."""

    prefix = "lifehug-118-arc-"

    def setUp(self):
        self.tmp = symlink_free_tmp(self, prefix=self.prefix)
        self.vault = self.tmp / "vault"
        self.vault.mkdir()
        self.fixture = VaultFixture(self.vault)
        self.build_fixture()

    def build_fixture(self):
        f = self.fixture
        f.bank([
            ("A1", "What's your earliest memory?", True),
            ("A2", "Tell me about where you grew up.", True),
            ("A3", "Tell me about the winter you moved.", False),
            ("B1", "When did you first feel agency over your life?", False),
            ("C1", "Who believed in you before you believed in yourself?", False),
            ("D1", "What moment made you choose this path?", False),
        ])
        f.answer("A1", "The diesel smell of my grandfather's truck on the farm road. "
                       "I was maybe four, and the seat was too hot to touch.")
        f.answer("A2", "A narrow house on Pearl Street with a cottonwood out front.",
                 answered_date="2026-04-02")
        # A1 has a partially-filled scene; A2 is fully unclassified.
        f.classification("A1", {"what_happened": True, "when_and_where": True,
                                "who_was_there": False, "thought_and_felt": False,
                                "what_it_says_about_me": False})
        f.write_text("wiki/self/mirror.md",
                     "---\ntitle: Mirror\n---\n\n## Tensions I keep circling\n\n- one\n\n"
                     "## What I seem to know about myself\n\n- two\n\n"
                     "## Stated positions\n\n- three\n\n"
                     "## Sit with\n\n"
                     "- You call yourself private, yet you tell strangers everything — which is true?\n"
                     "- Whose approval are you still working for?\n"
                     "- What would you keep doing if no one ever saw it?\n")
        f.write_json("state/neighborhoods.json", {"neighborhoods": [{
            "id": "the-ghana-years", "title": "the Ghana years", "type": "time_period",
            "target_output": "chapter", "status": "active",
            "arc": [{"story_function": "scene", "question_id": "C1", "status": "promoted"},
                    {"story_function": "meaning", "question_id": "cand-ghana-2", "status": "candidate"},
                    {"story_function": "tension", "question_id": "A1", "status": "answered"}],
        }]})
        f.write_json("state/question_candidates.json", {"candidates": [
            {"id": "cand-ghana-2", "neighborhood_id": "the-ghana-years", "status": "accepted",
             "story_function": "meaning", "text": "What did leaving Accra cost you?"},
            {"id": "cand-ghana-3", "neighborhood_id": "the-ghana-years", "status": "candidate",
             "story_function": "scene", "text": "Describe the last evening in the compound."},
        ]})
        f.queue([
            queue_item("A3", reason="scene story function; category coverage 40%"),
            queue_item("B1", story_function="growth_edge"),        # self-arc
            queue_item("C1", story_function="relationship"),        # neighborhood sibling
            queue_item("D1", story_function="meaning", focus="etherfuse"),
        ])

    # -- helpers ---------------------------------------------------------
    def plan(self, **kwargs):
        kwargs.setdefault("timeline_payload", timeline_payload(unplaced_events=2,
                                                               no_events_period="denver-years"))
        kwargs.setdefault("vault_root", self.vault)
        kwargs.setdefault("now", iso(NOW))
        code, report = arc_planner.plan(**kwargs)
        return code, report

    def container(self) -> dict:
        return conversation.load_arc_cards(vault_root=self.vault)

    def cards_by_id(self) -> dict[str, dict]:
        return {card["question_id"]: card for card in self.container()["cards"]}

    def all_intents(self) -> list[dict]:
        return [intent for card in self.container()["cards"] for intent in card["intents"]]


class DeterministicPlanTests(BaseVaultTest):
    """Every queued question gets a card, even with no model anywhere."""

    def test_deterministic_cards_for_every_queued_item(self):
        code, _ = self.plan()
        self.assertEqual(code, 0)
        container = self.container()
        self.assertEqual(container["source"], "deterministic")
        self.assertEqual(container["version"], conversation.ARC_CARDS_VERSION)
        cards = container["cards"]
        self.assertEqual([card["question_id"] for card in cards], ["A3", "B1", "C1", "D1"])
        for card in cards:
            self.assertGreaterEqual(len(card["intents"]), arc_planner.MIN_INTENTS, card)
            self.assertLessEqual(len(card["intents"]), arc_planner.MAX_INTENTS, card)
            self.assertEqual(card["planner"], "deterministic")
        # With this much material the target band is reachable for every card.
        for card in cards:
            self.assertGreaterEqual(len(card["intents"]), arc_planner.TARGET_MIN_INTENTS, card)

    def test_expiry_and_queue_stamps_are_copied_verbatim(self):
        self.plan()
        queue = arc_planner.load_queue(vault_root=self.vault)
        container = self.container()
        self.assertEqual(container["queue_generated_at"], queue["generated_at"])
        self.assertEqual(container["expires_at"], queue["expires_at"])

    def test_intent_vocabulary_closed(self):
        self.plan()
        for intent in self.all_intents():
            self.assertIn(intent["kind"], conversation.ARC_INTENT_KINDS)
        rogue = {"question_id": "A3", "intents": [{"kind": "vibe_check"}]}
        clean, errors = arc_planner.validate_card(
            rogue, allowed_ids={"A3"}, material={}, vault_root=self.vault)
        self.assertIsNone(clean)
        self.assertTrue(any("vibe_check" in error for error in errors), errors)

    def test_scene_slot_names_match_book_five_slots(self):
        self.assertEqual(arc_planner._five_slots(), tuple(book.FIVE_SLOTS))
        self.plan()
        named = {intent["slot"] for intent in self.all_intents()
                 if intent["kind"] == "scene_slot"}
        self.assertTrue(named)
        self.assertTrue(named.issubset(set(book.FIVE_SLOTS)), named)

    def test_unfilled_five_slot_probe_prefers_what_it_says_about_me(self):
        self.plan()
        card = self.cards_by_id()["A3"]
        slots = [intent["slot"] for intent in card["intents"] if intent["kind"] == "scene_slot"]
        self.assertTrue(slots)
        self.assertEqual(slots[0], "what_it_says_about_me")


class ConvergencePropertyTests(BaseVaultTest):
    """Owner-set acceptance criteria: every detectable gap type has a named
    consumer that turns it into a conversation input."""

    def test_timeline_gap_consumer_fires_and_never_says_what_year(self):
        self.plan(timeline_payload=timeline_payload(unplaced_events=3,
                                                    all_undated_period="ghana-years"))
        gap_intents = [intent for intent in self.all_intents() if intent["kind"] == "timeline_gap"]
        self.assertTrue(gap_intents, "the timeline gaps produced no conversation input")
        self.assertTrue({intent["gap_kind"] for intent in gap_intents}
                        <= set(arc_planner.CONSUMED_GAP_KINDS))
        blob = json.dumps(self.container()).lower()
        self.assertNotIn(arc_planner.BANNED_PHRASE, blob)
        self.assertTrue(any("landmark" in intent["note"] for intent in gap_intents))

    def test_timeline_gap_capped_per_card_and_per_week(self):
        self.plan(timeline_payload=timeline_payload(unplaced_events=2,
                                                    no_events_period="denver-years",
                                                    all_undated_period="ghana-years"),
                  gap_max=2)
        per_card = [sum(1 for intent in card["intents"] if intent["kind"] == "timeline_gap")
                    for card in self.container()["cards"]]
        self.assertLessEqual(max(per_card), 1, "at most one timeline_gap intent per card")
        self.assertLessEqual(sum(per_card), 2, "the week-wide gap cap must hold")

    def test_scene_slot_consumer_fires_for_unfilled_five_slot_scenes(self):
        self.plan()
        slot_intents = [intent for intent in self.all_intents() if intent["kind"] == "scene_slot"]
        self.assertTrue(slot_intents)
        for intent in slot_intents:
            self.assertIn(intent["slot"], book.FIVE_SLOTS)

    def test_sit_with_only_for_self_arc_items(self):
        self.plan()
        cards = self.cards_by_id()
        self.assertIn("growth_edge", question_planner.SELF_FUNCTIONS)
        b1_sit = [intent for intent in cards["B1"]["intents"] if intent["kind"] == "sit_with"]
        self.assertEqual(len(b1_sit), 1, "the self-arc item must get a sit_with intent")
        self.assertIn(b1_sit[0]["text"],
                      arc_planner.collect_sit_with(vault_root=self.vault))
        for qid in ("A3", "C1", "D1"):
            self.assertFalse([i for i in cards[qid]["intents"] if i["kind"] == "sit_with"],
                             f"{qid} is not a self-arc item")

    def test_neighborhood_sibling_consumer_fires(self):
        self.plan()
        siblings = [intent for intent in self.cards_by_id()["C1"]["intents"]
                    if intent["kind"] == "neighborhood_sibling"]
        self.assertTrue(siblings, "a neighborhood with pending siblings produced no input")
        self.assertEqual(siblings[0]["neighborhood_id"], "the-ghana-years")
        self.assertIn(siblings[0]["candidate_id"], {"cand-ghana-2", "cand-ghana-3"})

    def test_studio_slot_consumer_fires_or_no_ops_silently(self):
        cards = [{
            "format": "letter", "focus_id": "etherfuse",
            "slots": [{"id": "opening_address", "label": "Opening address", "filled": False},
                      {"id": "shared_history", "label": "Shared history", "filled": True}],
        }]
        self.plan(readiness_cards=cards)
        studio = [intent for intent in self.cards_by_id()["D1"]["intents"]
                  if intent["kind"] == "studio_slot"]
        self.assertTrue(studio, "an unfilled format slot produced no input")
        self.assertEqual(studio[0]["slot"], "opening_address")
        self.assertEqual(studio[0]["format"], "letter")
        # Documented silent no-op: no framework at all ⇒ no studio intents,
        # and every other consumer still fires.
        self.plan(readiness_cards=[])
        self.assertFalse([i for i in self.all_intents() if i["kind"] == "studio_slot"])
        self.assertTrue(self.container()["cards"])

    def test_demonstrated_knowledge_requires_two_answers_and_real_receipts(self):
        self.plan()
        cards = self.cards_by_id()
        a3 = [intent for intent in cards["A3"]["intents"]
              if intent["kind"] == "demonstrated_knowledge_summary"]
        self.assertTrue(a3, "category A has two answers on record")
        material = arc_planner.collect_material([], vault_root=self.vault)
        for receipt in a3[0]["receipts"]:
            self.assertTrue(arc_planner.receipt_resolves(receipt, material, vault_root=self.vault))
        for qid in ("B1", "C1", "D1"):  # categories with 0 answers
            self.assertFalse([i for i in cards[qid]["intents"]
                              if i["kind"] == "demonstrated_knowledge_summary"], qid)


class OpeningTests(BaseVaultTest):
    """The two-sentence rule and the receipts that make it honest."""

    def test_deterministic_opening_quotes_the_record_verbatim(self):
        self.plan()
        card = self.cards_by_id()["A3"]
        self.assertIsNotNone(card["opening"])
        # The FRESHEST on-record answer in the category (A2, 2026-04-02) is
        # the material — the most recent thing said is the most conversational.
        self.assertIn("Pearl Street", card["opening"])
        self.assertEqual(card["opening_receipts"], ["A2"])
        body = (self.vault / "answers" / "A2.md").read_text(encoding="utf-8")
        quote = card["opening"].split('"')[1]
        self.assertIn(quote, " ".join(body.split()))

    def test_opening_is_null_without_record_in_the_category(self):
        self.plan()
        for qid in ("B1", "C1", "D1"):
            card = self.cards_by_id()[qid]
            self.assertIsNone(card["opening"], f"{qid} has nothing on record to quote")
            self.assertEqual(card["opening_receipts"], [])

    def test_opening_receipts_must_resolve(self):
        material = arc_planner.collect_material([], vault_root=self.vault)
        fabricated = {
            "question_id": "A3",
            "opening": "You wrote about the summer in Lisbon.",
            "opening_receipts": ["Z99"],
            "intents": [{"kind": "scene_slot", "slot": "who_was_there"},
                        {"kind": "scene_slot", "slot": "thought_and_felt"}],
        }
        clean, errors = arc_planner.validate_card(
            fabricated, allowed_ids={"A3"}, material=material, vault_root=self.vault)
        self.assertIsNotNone(clean, "the card survives; only the opening is dropped")
        self.assertIsNone(clean["opening"])
        self.assertEqual(clean["opening_receipts"], [])
        self.assertTrue(any("Z99" in error for error in errors), errors)

        real = dict(fabricated, opening="You wrote: \"The diesel smell…\"",
                    opening_receipts=["A1"])
        clean, errors = arc_planner.validate_card(
            real, allowed_ids={"A3"}, material=material, vault_root=self.vault)
        self.assertIsNotNone(clean["opening"])
        self.assertEqual(errors, [])

    def test_what_year_is_rejected_anywhere_in_a_card(self):
        material = arc_planner.collect_material([], vault_root=self.vault)
        card = {"question_id": "A3",
                "intents": [{"kind": "timeline_gap", "gap_kind": "unplaced_events",
                             "note": "ask What Year that happened"},
                            {"kind": "scene_slot", "slot": "who_was_there"}]}
        clean, errors = arc_planner.validate_card(
            card, allowed_ids={"A3"}, material=material, vault_root=self.vault)
        self.assertIsNone(clean)
        self.assertTrue(any(arc_planner.BANNED_PHRASE in error for error in errors), errors)


class DailyAttachTests(BaseVaultTest):
    """The daily loop is a pure read: empty-vs-nonempty, marker preserved."""

    def test_daily_text_contains_qid_marker_and_is_empty_without_live_card(self):
        self.assertEqual(arc_planner.daily_text("A3", vault_root=self.vault, now=NOW), "",
                         "no cards planned yet ⇒ nothing attaches")
        self.plan()
        text = arc_planner.daily_text("A3", vault_root=self.vault, now=NOW)
        self.assertTrue(text)
        self.assertIn("[A3]", text)
        self.assertIn("Pearl Street", text)          # the framing, from the record
        self.assertIn("Tell me about the winter you moved.", text)  # …then the question
        # The marker is in ask.format_question's exact shape — daily_question.sh
        # parses it with this regex and the answer-filing flow keys on it.
        import re
        self.assertEqual(re.search(r"\[([A-Z]\d+[a-z]*)\]", text).group(1), "A3")

        # A card with no opening reads as "no attach" — today's format stands.
        self.assertEqual(arc_planner.daily_text("B1", vault_root=self.vault, now=NOW), "")

    def test_expiry_follows_queue_and_dead_cards_never_attach(self):
        self.plan()
        self.assertIsNotNone(arc_planner.live_card("A3", vault_root=self.vault, now=NOW))
        after_expiry = NOW + timedelta(days=9)
        self.assertIsNone(arc_planner.live_card("A3", vault_root=self.vault, now=after_expiry))
        self.assertEqual(arc_planner.daily_text("A3", vault_root=self.vault, now=after_expiry), "")

    def test_card_dies_when_its_question_leaves_the_queue(self):
        self.plan()
        self.fixture.queue([queue_item("D1", story_function="meaning")])
        self.assertIsNone(arc_planner.live_card("A3", vault_root=self.vault, now=NOW))
        self.assertEqual(arc_planner.daily_text("A3", vault_root=self.vault, now=NOW), "")

    def test_a_sent_question_keeps_its_card_for_the_day(self):
        self.plan()
        items = arc_planner.load_queue(vault_root=self.vault)["queue"]
        items[0]["status"] = "sent"
        self.fixture.queue(items)
        self.assertIsNotNone(arc_planner.live_card("A3", vault_root=self.vault, now=NOW))


def model_response(question_ids: list[str]) -> str:
    return json.dumps({"cards": [{
        "question_id": qid,
        "opening": "You wrote: \"A narrow house on Pearl Street with a cottonwood out front.\"",
        "opening_receipts": ["A2"],
        "intents": [{"kind": "scene_slot", "slot": "who_was_there", "note": "who else was there"},
                    {"kind": "demonstrated_knowledge_summary", "receipts": ["A1", "A2"],
                     "note": "summarize the two on record first"}],
    } for qid in question_ids]})


class ModelPassTests(BaseVaultTest):
    """One prompt per run; invalid or absent output never costs the week."""

    def test_model_cards_upgrade_the_deterministic_plan(self):
        with mock.patch("ai_provider.call_ai", return_value=model_response(["A3", "B1"])):
            code, report = self.plan()
        self.assertEqual(code, 0)
        container = self.container()
        self.assertEqual(container["source"], "mixed")
        cards = self.cards_by_id()
        self.assertEqual(cards["A3"]["planner"], "model")
        self.assertEqual(cards["B1"]["planner"], "model")
        self.assertEqual(cards["C1"]["planner"], "deterministic")
        self.assertTrue(any("2 card(s) planned by the model" in line for line in report), report)

    def test_model_failure_falls_back_to_deterministic(self):
        from ai_provider import AIUnavailableError
        with mock.patch("ai_provider.call_ai", side_effect=AIUnavailableError("no route")), \
             mock.patch.object(arc_planner, "_record_failure") as recorded:
            code, report = self.plan()
        self.assertEqual(code, 0)
        cards = self.container()["cards"]
        self.assertEqual(len(cards), 4, "the week still gets its cards")
        self.assertEqual(self.container()["source"], "deterministic")
        self.assertTrue(any("Model pass unavailable" in line for line in report), report)
        recorded.assert_called_once()
        self.assertEqual(recorded.call_args.args[0], "arc_plan_model")

    def test_invalid_model_output_falls_back_without_writing_a_broken_file(self):
        for raw in ("not json at all",
                    json.dumps({"cards": [{"question_id": "A3",
                                           "intents": [{"kind": "astrology"}]}]}),
                    json.dumps({"cards": [{"question_id": "ZZ9",
                                           "intents": [{"kind": "scene_slot"}]}]})):
            with self.subTest(raw=raw[:30]), \
                 mock.patch("ai_provider.call_ai", return_value=raw):
                code, _ = self.plan()
            self.assertEqual(code, 0)
            self.assertEqual(self.container()["source"], "deterministic")
            self.assertEqual(len(self.container()["cards"]), 4)

    def test_one_prompt_per_run_not_per_card(self):
        with mock.patch("ai_provider.call_ai", return_value=model_response(["A3"])) as call:
            self.plan()
        self.assertEqual(call.call_count, 1, "the weekly run makes exactly one model call")
        prompt = call.call_args.args[0]
        for qid in ("A3", "B1", "C1", "D1"):
            self.assertIn(f"QUESTION [{qid}]", prompt)
        # The definition file is carried verbatim, per the merged builder shape.
        self.assertIn("# Arc templates — how arc cards are planned", prompt)
        self.assertIn("INPUT (assembled at runtime", prompt)

    def test_model_resolution_order(self):
        with mock.patch.object(arc_planner, "load_config",
                               return_value={"arc_plan_model": "m-arc", "classify_model": "m-classify"}):
            self.assertEqual(arc_planner.resolve_model(), "m-arc")
        with mock.patch.object(arc_planner, "load_config", return_value={"classify_model": "m-classify"}):
            self.assertEqual(arc_planner.resolve_model(), "m-classify")
        with mock.patch.object(arc_planner, "load_config", return_value={}):
            import classify_story
            self.assertEqual(arc_planner.resolve_model(), classify_story.DEFAULT_MODEL)
        with mock.patch.object(arc_planner, "load_config", return_value={"arc_plan_model": "m-arc"}):
            self.assertEqual(arc_planner.resolve_model("explicit"), "explicit")


class KeylessTests(BaseVaultTest):
    """Keyless: deterministic cards land NOW, the prompt goes out as a task."""

    def test_emit_tasks_writes_cards_and_a_manifest(self):
        out = self.tmp / "agent_tasks" / "arcs"
        code, report = self.plan(emit_tasks_dir=out)
        self.assertEqual(code, 0)
        self.assertEqual(len(self.container()["cards"]), 4)
        self.assertEqual(self.container()["source"], "deterministic")
        manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["task"], "arcs")
        self.assertIn("--from-response", manifest["ingest_command"])
        self.assertEqual(manifest["items"][0]["response"], "arcs.response.json")
        self.assertTrue((out / "arcs.prompt.md").is_file())
        self.assertTrue(any("Emitted arc-plan task" in line for line in report), report)

    def test_from_response_upgrades_deterministic_cards(self):
        out = self.tmp / "agent_tasks" / "arcs"
        self.plan(emit_tasks_dir=out)
        self.assertTrue(all(card["planner"] == "deterministic"
                            for card in self.container()["cards"]))
        response = out / "arcs.response.json"
        response.write_text(model_response(["A3", "C1"]), encoding="utf-8")

        code, report = arc_planner.ingest_response(response, vault_root=self.vault, now=iso(NOW))
        self.assertEqual(code, 0, report)
        cards = self.cards_by_id()
        self.assertEqual(cards["A3"]["planner"], "model")
        self.assertEqual(cards["C1"]["planner"], "model")
        self.assertEqual(cards["B1"]["planner"], "deterministic")
        self.assertEqual(self.container()["source"], "mixed")
        self.assertEqual(len(self.container()["cards"]), 4, "no card is lost in an upgrade")

    def test_a_rerun_does_not_clobber_model_cards_unless_forced(self):
        out = self.tmp / "agent_tasks" / "arcs"
        self.plan(emit_tasks_dir=out)
        response = out / "arcs.response.json"
        response.write_text(model_response(["A3"]), encoding="utf-8")
        arc_planner.ingest_response(response, vault_root=self.vault, now=iso(NOW))

        self.plan(emit_tasks_dir=out)  # same queue, deterministic re-run
        self.assertEqual(self.cards_by_id()["A3"]["planner"], "model")

        self.plan(emit_tasks_dir=out, force=True)
        self.assertEqual(self.cards_by_id()["A3"]["planner"], "deterministic")


class ThreadOfferTests(BaseVaultTest):
    """Monthly conversation-thread offers: one line, never twice a quarter."""

    def test_conversation_ready_requires_somewhere_to_go_and_record_to_open_from(self):
        ready = arc_planner.conversation_ready_neighborhoods(vault_root=self.vault)
        self.assertEqual([n["id"] for n in ready], ["the-ghana-years"])

        # Every slot answered ⇒ nowhere to go ⇒ not conversation-ready.
        self.fixture.write_json("state/neighborhoods.json", {"neighborhoods": [{
            "id": "the-ghana-years", "title": "the Ghana years", "status": "active",
            "arc": [{"story_function": "tension", "question_id": "A1"}],
        }]})
        self.assertEqual(arc_planner.conversation_ready_neighborhoods(vault_root=self.vault), [])

    def test_thread_offers_never_repeat_within_quarter(self):
        lines, fresh = arc_planner.plan_thread_offers(vault_root=self.vault, now=NOW)
        self.assertEqual(len(lines), 1)
        self.assertIn("the Ghana years", lines[0])
        self.assertEqual(fresh[0]["neighborhood_id"], "the-ghana-years")
        self.assertEqual(fresh[0]["month"], "2026-08")
        self.assertEqual(self.container()["thread_offers"], fresh)

        next_month, _ = arc_planner.plan_thread_offers(
            vault_root=self.vault, now=NOW + timedelta(days=31))
        self.assertEqual(next_month, [], "an offered thread stays quiet for a quarter")

        later, later_fresh = arc_planner.plan_thread_offers(
            vault_root=self.vault, now=NOW + timedelta(days=arc_planner.THREAD_OFFER_QUIET_DAYS + 1))
        self.assertEqual(len(later), 1, "after a quarter it may be offered again")
        self.assertEqual(len(self.container()["thread_offers"]), 2)
        self.assertEqual(later_fresh[0]["neighborhood_id"], "the-ghana-years")

    def test_dry_run_offers_write_nothing(self):
        lines, fresh = arc_planner.plan_thread_offers(vault_root=self.vault, now=NOW, dry_run=True)
        self.assertEqual(len(lines), 1)
        self.assertEqual(self.container()["thread_offers"], [])
        self.assertTrue(fresh)

    def test_offers_survive_a_weekly_replan(self):
        arc_planner.plan_thread_offers(vault_root=self.vault, now=NOW)
        self.plan()
        self.assertEqual(len(self.container()["thread_offers"]), 1,
                         "the weekly rewrite must not drop the month's offers")


class DryRunTests(BaseVaultTest):
    """Dry runs print the plan and write nothing at all."""

    def test_plan_dry_run_writes_no_state(self):
        code, report = self.plan(dry_run=True)
        self.assertEqual(code, 0)
        self.assertFalse((self.vault / "state" / "arc_cards.json").exists())
        self.assertTrue(any("DRY RUN" in line for line in report), report)
        self.assertTrue(any("[A3]" in line for line in report), report)
        self.assertNotIn(arc_planner.BANNED_PHRASE, "\n".join(report).lower())

    def test_empty_queue_is_not_an_error(self):
        self.fixture.queue([])
        code, report = self.plan()
        self.assertEqual(code, 0)
        self.assertEqual(report, ["No queued questions to plan arcs for."])


class CommandSurfaceTests(unittest.TestCase):
    """The CLI + shell seams — the weekly step is the platform's parity SPEC."""

    def setUp(self):
        self.weekly = (SYSTEM / "weekly_maintenance.sh").read_text(encoding="utf-8")
        self.daily = (SYSTEM / "daily_question.sh").read_text(encoding="utf-8")
        self.monthly = (SYSTEM / "monthly_research.sh").read_text(encoding="utf-8")
        self.wrapper = (SYSTEM / "lifehug.py").read_text(encoding="utf-8")

    @property
    def weekly_real_run(self) -> str:
        """The weekly script below its dry-run block (which exits early)."""
        return self.weekly.split('if [[ "$DRY_RUN" == "1" ]]; then')[1].split("\nfi\n", 1)[1]

    def test_weekly_plans_arcs_directly_after_the_planner_queue(self):
        real = self.weekly_real_run
        queue_at = real.index('run_learning_step "planner_queue"')
        arcs_at = real.index("arc-plan")
        research_at = real.index('research_expand.py" --gaps')
        self.assertLess(queue_at, arcs_at, "arcs are planned against the queue just written")
        self.assertLess(arcs_at, research_at)
        self.assertIn('QUEUE_OUT="$LAST_STEP_OUT"', real)

    def test_weekly_step_carries_the_knobs_the_platform_transports(self):
        real = self.weekly_real_run
        self.assertIn("LIFEHUG_WEEKLY_ARC_GAP_MAX", real)
        self.assertIn('run_learning_step "arc_plan"', real)
        self.assertIn("$AGENT_TASKS_DIR/arcs", real)
        self.assertIn("Arc cards:ARCS_OUT", self.weekly)
        # The keyless branch reports the emitted task as a pause, not a failure.
        keyless_branch = real.split("ARC_GAP_MAX=")[1].split("run_step")[0]
        self.assertIn("⏸ keyless", keyless_branch)
        self.assertIn("arc_plan_emit", keyless_branch)

    def test_weekly_dry_run_previews_the_arc_plan(self):
        preview = self.weekly.split('if [[ "$DRY_RUN" == "1" ]]; then')[1].split("exit 0")[0]
        self.assertIn("arc-plan --dry-run", preview)

    def test_daily_attach_is_a_pure_read_that_keeps_the_marker(self):
        # One definition of the attach, called from the dry run and the send.
        self.assertIn('arc-card "$1" --daily-text', self.daily)
        self.assertIn("arc_card_text() {", self.daily)
        # The attach happens after the id parse and before the send.
        parse_at = self.daily.index("Could not parse question ID")
        attach_at = self.daily.index('ARC_TEXT=$(arc_card_text "$QUESTION_ID")')
        send_at = self.daily.index("RESPONSE=$(send_message")
        self.assertLess(parse_at, attach_at)
        self.assertLess(attach_at, send_at)
        self.assertIn("📖 Lifehug — Daily Question", self.daily)
        self.assertIn("(Answer whenever you want — voice or text)", self.daily)
        # Empty output ⇒ today's format, unchanged.
        self.assertIn('QUESTION_BODY="$QUESTION_OUTPUT"', self.daily)

    def test_daily_dry_run_shows_the_would_be_attach(self):
        preview = self.daily.split('if [[ "$DRY_RUN" == "1" ]]; then')[1].split("exit 0")[0]
        self.assertIn("arc_card_text", preview)
        self.assertIn("no live arc card", preview)

    def test_monthly_offers_threads_and_previews_them(self):
        self.assertIn("arc-thread-offers", self.monthly)
        self.assertIn("LIFEHUG_MONTHLY_THREAD_OFFERS", self.monthly)
        preview = self.monthly.split('if [[ "$DRY_RUN" == "1" ]]; then')[1].split("exit 0")[0]
        self.assertIn("arc-thread-offers", preview)
        self.assertIn("Conversation threads:THREAD_OFFERS_OUT", self.monthly)

    def test_monthly_resurfacing_closes_as_a_conversation_opener(self):
        self.assertIn("Reply and we'll talk it through", self.monthly)

    def test_wrapper_classifies_the_three_commands(self):
        import lifehug
        self.assertIn("arc-card", lifehug.READ_ONLY_COMMANDS)
        self.assertIn("arc-plan", lifehug.DIRECT_MUTATION_COMMANDS)
        self.assertIn("arc-thread-offers", lifehug.DIRECT_MUTATION_COMMANDS)

    def test_wrapper_subcommands_exist_and_forward_flags(self):
        result = subprocess.run(
            [sys.executable, str(SYSTEM / "lifehug.py"), "arc-plan", "--help"],
            capture_output=True, text=True, cwd=ROOT)
        self.assertEqual(result.returncode, 0, result.stderr)
        for flag in ("--limit", "--gap-max", "--model", "--dry-run", "--emit-tasks",
                     "--from-response", "--force"):
            self.assertIn(flag, result.stdout)
        result = subprocess.run(
            [sys.executable, str(SYSTEM / "lifehug.py"), "arc-card", "--help"],
            capture_output=True, text=True, cwd=ROOT)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("--daily-text", result.stdout)

    def test_arc_planner_is_registered_as_a_framework_file(self):
        version = json.loads((SYSTEM / "version.json").read_text(encoding="utf-8"))
        self.assertIn("system/arc_planner.py", version["framework_files"])

    def test_config_example_documents_the_model_key(self):
        example = (ROOT / "config.yaml.example").read_text(encoding="utf-8")
        self.assertIn("arc_plan_model", example)

    def test_no_reference_to_the_private_vault_anywhere(self):
        # The hard boundary: the private vault is never a fixture, a test
        # target, or a dev-writable target. (This test file names the path
        # exactly once, in its own docstring's prohibition, so the scan is
        # against code lines only.)
        private = "Workspace/" + "dave"  # assembled so this scan can scan itself
        self.assertNotIn(private, (SYSTEM / "arc_planner.py").read_text(encoding="utf-8"))
        body = Path(__file__).read_text(encoding="utf-8").split('"""', 2)[-1]
        self.assertNotIn(private, body)


if __name__ == "__main__":
    unittest.main()
