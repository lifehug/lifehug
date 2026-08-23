"""v193 / arc-walk-interaction — the fourth child of Conversation.

One file for the whole contract, including the delivery-engine layer, so the
v193 surface reads as one thing rather than being scattered across five
existing files (the tests/test_entity_identity_context.py precedent).
"""

from __future__ import annotations

import ast
import hashlib
import json
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SYSTEM = ROOT / "system"
sys.path.insert(0, str(SYSTEM))
sys.path.insert(0, str(ROOT / "tests"))

from tempdirs import root_parent_tmp  # noqa: E402
import arc_walk  # noqa: E402
import conversation  # noqa: E402
import conversation_delivery as engine  # noqa: E402
import interaction_registry as registry  # noqa: E402
import question_planner  # noqa: E402

TARGET = {
    "kind": "focus",
    "ref": "synthetic-harbor",
    "label": "Synthetic Harbor",
    "categories": ["H"],
}


def question(qid, text, answered=False):
    return {"id": qid, "category": qid[0], "text": text, "answered": answered}


def plan_of(*qids, episode_size=3, label="Synthetic Harbor"):
    return {
        "target": {
            "kind": "focus",
            "ref": "synthetic-harbor",
            "label": label,
            "categories": ("H",),
        },
        "focus_label": label,
        "questions": [
            {"id": qid, "text": f"question {qid}", "category": qid[0], "intent": None}
            for qid in qids
        ],
        "episode_size": episode_size,
        "plan_n": len(qids),
        "answered_k": 0,
    }


def session_of(*turns):
    return {"turns": list(turns)}


def lifehug_turn(qid=None, text="a reply"):
    turn = {"role": "lifehug", "text": text}
    if qid is not None:
        turn["question_id"] = qid
    return turn


def user_turn(qid=None, text="an answer"):
    turn = {"role": "user", "text": text}
    if qid is not None:
        turn["question_id"] = qid
    return turn


# ---------------------------------------------------------------------------
# The delivery-engine layer (Design §C)
# ---------------------------------------------------------------------------


class OutputContractTests(unittest.TestCase):
    def shape(self, **kwargs):
        return engine.TurnShape(
            position="mid", question_allowed=True, user_turns=2,
            target_exchanges=3, **kwargs,
        )

    def test_output_contract_block_byte_identical_without_arc_stage(self):
        """Owner ruling 6, mechanically: the passive daily question's prompt
        does not move by one byte."""
        block = engine._output_contract_block(self.shape())
        self.assertNotIn("answered_question_id", block)
        # And the four gates are independent: turning any OTHER one on still
        # leaves answered_question_id out.
        for gate in ("placement_stage", "focus_stage", "entity_stage"):
            with self.subTest(gate=gate):
                other = engine._output_contract_block(self.shape(**{gate: "settled"}))
                self.assertNotIn("answered_question_id", other)

    def test_answered_question_id_line_and_note_present_when_staged(self):
        for stage in sorted(arc_walk.VALID_ARC_STAGES):
            with self.subTest(stage=stage):
                block = engine._output_contract_block(self.shape(arc_stage=stage))
                self.assertIn('"answered_question_id"', block)
                self.assertIn("name the primary", block)

    def test_all_four_additive_fields_coexist_in_a_stable_order(self):
        block = engine._output_contract_block(self.shape(
            placement_stage="ask", focus_stage="establish",
            entity_stage="establish", arc_stage="walk",
        ))
        order = [
            block.index('"placement"'),
            block.index('"focus_setup"'),
            block.index('"entity_setup"'),
            block.index('"answered_question_id"'),
            block.index('"rolling_summary"'),
        ]
        self.assertEqual(order, sorted(order))

    def test_answered_question_id_absent_is_none(self):
        parsed = engine.parse_turn_output(json.dumps({"message": "hello there"}))
        self.assertIsNone(parsed["answered_question_id"])

    def test_answered_question_id_parsed_and_trimmed(self):
        parsed = engine.parse_turn_output(
            json.dumps({"message": "hello there", "answered_question_id": "  H14 "})
        )
        self.assertEqual(parsed["answered_question_id"], "H14")

    def test_answered_question_id_malformed_degrades_never_raises(self):
        for bad in (None, "", "   ", 14, 1.5, True, ["H14"], {"id": "H14"}, "H" * 17):
            with self.subTest(bad=bad):
                parsed = engine.parse_turn_output(
                    json.dumps({"message": "hello there", "answered_question_id": bad})
                )
                self.assertIsNotNone(parsed)
                self.assertIsNone(parsed["answered_question_id"])


# ---------------------------------------------------------------------------
# The target and the plan (Design §B.1/§B.2)
# ---------------------------------------------------------------------------


class TargetTests(unittest.TestCase):
    def test_normalize_target_closed_kinds_and_dedupe(self):
        target = arc_walk.normalize_target(
            {"kind": "book", "ref": "b1", "label": " Etherfuse ", "categories": ["F", "F", " G "]}
        )
        self.assertEqual(target["kind"], "book")
        self.assertEqual(target["label"], "Etherfuse")
        self.assertEqual(target["categories"], ("F", "G"))

    def test_normalize_target_defaults_label_to_ref_and_accepts_one_string(self):
        target = arc_walk.normalize_target({"kind": "category", "ref": "H", "categories": "H"})
        self.assertEqual(target["label"], "H")
        self.assertEqual(target["categories"], ("H",))

    def test_normalize_target_raises_on_unusable(self):
        for bad in (
            None, "focus", {},
            {"kind": "question", "ref": "H1", "categories": ["H"]},
            {"kind": "FOCUS", "ref": "x", "categories": ["H"]},
            {"kind": "focus", "ref": "", "categories": ["H"]},
            {"kind": "focus", "ref": "x", "categories": []},
        ):
            with self.subTest(bad=bad):
                with self.assertRaises(arc_walk.ArcWalkError):
                    arc_walk.normalize_target(bad)


class PlanTests(unittest.TestCase):
    def build(self, questions, **kwargs):
        categories = {"H": {"name": "Harbor", "group": "focus"}}
        coverage = {"categories": {"H": {"total": len(questions), "answered": 0}}}
        return arc_walk.build_arc_plan(
            TARGET, questions=questions, categories=categories,
            coverage=coverage, tier="standard", **kwargs,
        )

    def test_plan_counts_are_bank_facts(self):
        questions = [
            question("H1", "one", answered=True),
            question("H2", "two"),
            question("H3", "three"),
        ]
        plan = self.build(questions)
        self.assertEqual(plan["plan_n"], 3)
        self.assertEqual(plan["answered_k"], 1)
        self.assertEqual(len(plan["questions"]), plan["plan_n"] - plan["answered_k"])
        self.assertEqual(plan["focus_label"], "Synthetic Harbor")

    def test_build_arc_plan_drops_answered_and_declined(self):
        questions = [question("H1", "one", answered=True), question("H2", "two"),
                     question("H3", "three")]
        plan = self.build(questions, declined_question_ids=["H3"])
        self.assertEqual(arc_walk.plan_question_ids(plan), ("H2",))

    def test_build_arc_plan_ignores_questions_outside_the_target(self):
        questions = [question("H2", "two"), question("K9", "elsewhere")]
        plan = self.build(questions)
        self.assertEqual(arc_walk.plan_question_ids(plan), ("H2",))
        self.assertEqual(plan["plan_n"], 1)

    def test_build_arc_plan_orders_by_planner_weight(self):
        """Bank order is irrelevant; the planner's weight decides."""
        questions = [question("H1", "one"), question("H2", "two")]
        categories = {"H": {"name": "Harbor", "group": "focus"}}
        coverage = {"categories": {"H": {"total": 2, "answered": 0}}}
        rows = question_planner.enriched_pending_questions(
            questions, categories, coverage, [], None
        )
        # Weight the LAST bank question higher and assert it leads the plan.
        for row in rows:
            row["weight"] = 9.0 if row["id"] == "H2" else 0.1
        original = question_planner.enriched_pending_questions
        question_planner.enriched_pending_questions = lambda *a, **k: rows
        try:
            plan = arc_walk.build_arc_plan(
                TARGET, questions=questions, categories=categories,
                coverage=coverage, tier="standard",
            )
        finally:
            question_planner.enriched_pending_questions = original
        self.assertEqual(arc_walk.plan_question_ids(plan)[0], "H2")

    def test_build_arc_plan_weight_expression_matches_build_queue(self):
        """The pin: `_plan_weight` IS `build_queue.weighted_pick`'s own weight
        expression. The reference is extracted from the planner's source and
        evaluated, so a change to the weighting or to the lane policy fails
        the build rather than letting a Play rank differently from the week."""
        tree = ast.parse((SYSTEM / "question_planner.py").read_text(encoding="utf-8"))
        expression = None
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "weighted_pick":
                for child in ast.walk(node):
                    if isinstance(child, ast.ListComp):
                        expression = ast.unparse(child.elt)
        self.assertIsNotNone(expression, "build_queue.weighted_pick vanished")
        self.assertIn("objective_boost", expression)
        policy = question_planner.DEFAULT_LANE_POLICY
        for weight in (0.0, 0.0001, 0.05, 1.0, 2.5, 12.0):
            for objective in (None, "", "ship the book"):
                row = {"weight": weight, "objective": objective}
                with self.subTest(weight=weight, objective=objective):
                    self.assertAlmostEqual(
                        arc_walk._plan_weight(row, policy),
                        eval(expression, {}, {"q": row, "policy": policy}),  # noqa: S307
                    )

    def test_default_arc_max_matches_planner_queue_cli_default(self):
        """The AST pin: the episode's streak cap and the weekly queue's are
        one number."""
        tree = ast.parse((SYSTEM / "lifehug.py").read_text(encoding="utf-8"))
        defaults = [
            keyword.value.value
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and getattr(node.func, "attr", "") == "add_argument"
            and node.args
            and isinstance(node.args[0], ast.Constant)
            and node.args[0].value == "--arc-max"
            for keyword in node.keywords
            if keyword.arg == "default" and isinstance(keyword.value, ast.Constant)
        ]
        self.assertEqual(defaults, [arc_walk.DEFAULT_ARC_MAX])

    def test_build_arc_plan_applies_the_arc_max_streak_cap(self):
        """Two categories interleave rather than marching; and with only one
        category available the last-resort still emits everything."""
        questions = [question(f"H{n}", f"h{n}") for n in range(1, 4)]
        questions += [question(f"K{n}", f"k{n}") for n in range(1, 4)]
        categories = {
            "H": {"name": "Harbor", "group": "focus"},
            "K": {"name": "Kin", "group": "focus"},
        }
        coverage = {"categories": {}}
        target = {**TARGET, "categories": ["H", "K"]}
        plan = arc_walk.build_arc_plan(
            target, questions=questions, categories=categories,
            coverage=coverage, tier="standard", arc_max=2,
        )
        ids = arc_walk.plan_question_ids(plan)
        self.assertEqual(len(ids), 6)
        letters = [qid[0] for qid in ids]
        for index in range(len(letters) - 2):
            self.assertNotEqual(
                letters[index:index + 3],
                [letters[index]] * 3,
                f"three in a row from one category: {letters}",
            )
        single = self.build([question(f"H{n}", f"h{n}") for n in range(1, 6)])
        self.assertEqual(len(single["questions"]), 5)  # last resort fills anyway

    def test_build_arc_plan_takes_intents_from_cards_and_never_invents(self):
        questions = [question("H1", "one"), question("H2", "two"), question("H3", "three")]
        cards = [
            {"question_id": "H1", "intents": [{"kind": "scene_slot", "note": "the dock"}]},
            {"question_id": "H2", "intents": [{"kind": "not_a_kind", "note": "nope"}]},
        ]
        plan = self.build(questions, cards=cards)
        by_id = {row["id"]: row["intent"] for row in plan["questions"]}
        self.assertEqual(by_id["H1"], "the dock")
        self.assertIsNone(by_id["H2"])  # unknown kind
        self.assertIsNone(by_id["H3"])  # no card

    def test_intent_note_vocabulary_is_conversations_own(self):
        card = {"question_id": "H1", "intents": [{"kind": "scene_slot", "slot": "what_it_cost"}]}
        self.assertEqual(arc_walk.intent_note(card), "what_it_cost")
        original = conversation.ARC_INTENT_KINDS
        conversation.ARC_INTENT_KINDS = frozenset()
        try:
            self.assertIsNone(arc_walk.intent_note(card))
        finally:
            conversation.ARC_INTENT_KINDS = original
        for bad in (None, {}, {"intents": []}, {"intents": ["scene_slot"]}):
            self.assertIsNone(arc_walk.intent_note(bad))

    def test_render_agenda_is_the_episode_slice_numbered(self):
        plan = plan_of("H1", "H2", "H3", "H4", episode_size=2)
        plan["questions"][0]["intent"] = "the dock"
        agenda = arc_walk.render_agenda(plan)
        self.assertEqual(len(agenda.splitlines()), 2)
        self.assertTrue(agenda.startswith("1. [H1] question H1 (the dock)"))
        self.assertEqual(len(arc_walk.episode_questions(plan)), 2)
        self.assertEqual(arc_walk.render_agenda(plan_of(episode_size=3)), "")


class EpisodeSizeTests(unittest.TestCase):
    def test_episode_size_by_tier_and_unknown_falls_back(self):
        self.assertEqual(arc_walk.episode_size_for("basic"), 4)
        self.assertEqual(arc_walk.episode_size_for("standard"), 6)
        self.assertEqual(arc_walk.episode_size_for("extreme"), 8)
        for unknown in (None, "", "  ", "gigantic", 7):
            self.assertEqual(
                arc_walk.episode_size_for(unknown), arc_walk.DEFAULT_EPISODE_SIZE
            )

    def test_episode_size_override_bounds(self):
        self.assertEqual(arc_walk.episode_size_for("basic", override=9), 9)
        for ignored in (0, -1, 13, "6", 6.0, True, None):
            self.assertEqual(arc_walk.episode_size_for("basic", override=ignored), 4)

    def test_episode_manifest_knobs_match_the_module_constants(self):
        manifest = registry.load_interaction_manifest("arc_walk")
        for tier, size in arc_walk.EPISODE_SIZES.items():
            self.assertEqual(int(manifest[f"knob.episode_size_{tier}"]), size)

    def test_max_episode_size_stays_under_the_conversation_turn_cap(self):
        parent = registry.load_interaction_manifest("conversation")
        self.assertLess(
            arc_walk.MAX_EPISODE_SIZE,
            int(parent["knob.conversation_turn_cap_exchanges"]),
        )


# ---------------------------------------------------------------------------
# Stage, progress, and the question on the table (Design §B.4/§B.5)
# ---------------------------------------------------------------------------


class StageTests(unittest.TestCase):
    def test_arc_stage_for_session_derived_from_transcript(self):
        plan = plan_of("H1", "H2", "H3", episode_size=2)
        self.assertEqual(arc_walk.arc_stage_for_session(session_of(), plan), "open")
        walking = session_of(lifehug_turn("H1"), user_turn("H1"))
        self.assertEqual(arc_walk.arc_stage_for_session(walking, plan), "walk")
        full = session_of(
            lifehug_turn("H1"), user_turn("H1"), lifehug_turn("H2"), user_turn("H2")
        )
        self.assertEqual(arc_walk.arc_stage_for_session(full, plan), "close")

    def test_user_leaving_forces_close_from_any_progress(self):
        plan = plan_of("H1", "H2", "H3")
        for session in (session_of(), session_of(lifehug_turn("H1"), user_turn("H1"))):
            self.assertEqual(
                arc_walk.arc_stage_for_session(session, plan, user_leaving=True), "close"
            )

    def test_answered_plan_question_ids_are_distinct_in_order_and_plan_only(self):
        plan = plan_of("H1", "H2")
        session = session_of(
            user_turn("H2"), user_turn("H2"), user_turn("H1"),
            user_turn("K9"), lifehug_turn("H1"),
        )
        self.assertEqual(
            arc_walk.answered_plan_question_ids(session, plan), ("H2", "H1")
        )

    def test_asked_question_id_reads_the_existing_assistant_turn_field(self):
        self.assertEqual(arc_walk.asked_question_id(lifehug_turn(" H12 ")), "H12")
        self.assertIsNone(arc_walk.asked_question_id(user_turn("H12")))
        self.assertIsNone(arc_walk.asked_question_id(lifehug_turn(None)))
        self.assertIsNone(arc_walk.asked_question_id(lifehug_turn("   ")))
        self.assertIsNone(arc_walk.asked_question_id(None))

    def test_question_on_the_table_prefers_the_asked_qid(self):
        plan = plan_of("H1", "H2", "H3")
        session = session_of(lifehug_turn("H1"), user_turn("H1"), lifehug_turn("H3"))
        self.assertEqual(arc_walk.question_on_the_table(session, plan), "H3")

    def test_question_on_the_table_falls_back_to_the_first_unanswered(self):
        plan = plan_of("H1", "H2", "H3")
        self.assertEqual(arc_walk.question_on_the_table(session_of(), plan), "H1")
        session = session_of(user_turn("H1"))
        self.assertEqual(arc_walk.question_on_the_table(session, plan), "H2")

    def test_question_on_the_table_is_none_when_off_plan_or_exhausted(self):
        plan = plan_of("H1")
        self.assertIsNone(
            arc_walk.question_on_the_table(session_of(lifehug_turn("K9")), plan)
        )
        self.assertIsNone(
            arc_walk.question_on_the_table(session_of(user_turn("H1")), plan)
        )


# ---------------------------------------------------------------------------
# The closed validator (Design §B.6)
# ---------------------------------------------------------------------------


class ValidateAnsweredQuestionIdTests(unittest.TestCase):
    def test_exact_plan_membership_only(self):
        plan = plan_of("H12", "H14")
        self.assertEqual(arc_walk.validate_answered_question_id("H14", plan=plan), "H14")
        self.assertEqual(
            arc_walk.validate_answered_question_id("  H12  ", plan=plan), "H12"
        )
        for bad in ("h14", "H1", "H", "H140", "K9", "", "   ", None, 14, ["H14"]):
            with self.subTest(bad=bad):
                self.assertIsNone(
                    arc_walk.validate_answered_question_id(bad, plan=plan)
                )

    def test_answered_question_id_keys_match_the_structural_layer(self):
        """Both layers run, in the order a real caller runs them."""
        plan = plan_of("H12")
        parsed = engine.parse_turn_output(
            json.dumps({"message": "hello there", "answered_question_id": "H12"})
        )
        self.assertEqual(
            arc_walk.validate_answered_question_id(
                parsed["answered_question_id"], plan=plan
            ),
            "H12",
        )
        self.assertLessEqual(
            engine._ANSWERED_QUESTION_ID_MAX_CHARS, arc_walk.MAX_TARGET_LABEL_CHARS
        )

    def test_the_field_is_primary_only_never_a_list(self):
        plan = plan_of("H12", "H14")
        self.assertIsNone(
            arc_walk.validate_answered_question_id(["H12", "H14"], plan=plan)
        )


# ---------------------------------------------------------------------------
# Lints (Design §D)
# ---------------------------------------------------------------------------


class LintTests(unittest.TestCase):
    def ids(self, text, **kwargs):
        kwargs.setdefault("stage", "walk")
        return {row["lint"] for row in arc_walk.lint_arc_reply(text, **kwargs)}

    def test_findings_share_the_inherited_shape(self):
        findings = arc_walk.lint_arc_reply("Nothing here.", stage="open")
        self.assertTrue(findings)
        for finding in findings:
            self.assertEqual(set(finding), {"lint", "detail", "span"})
            self.assertEqual(len(finding["span"]), 2)

    def test_agenda_announced_once(self):
        good = "Today I'd love to hear about the harbor. What kept you going back?"
        self.assertNotIn("arc_walk.agenda_announced_once", self.ids(good, stage="open"))
        self.assertIn(
            "arc_walk.agenda_announced_once",
            self.ids("So — what kept you going back?", stage="open"),
        )
        twice = (
            "Today I'd love to hear about the harbor. "
            "Today I want to hear about the boat too."
        )
        self.assertIn("arc_walk.agenda_announced_once", self.ids(twice, stage="open"))

    def test_agenda_never_repeated(self):
        repeat = "Today I'd love to hear about the harbor again."
        for stage in ("walk", "close"):
            self.assertIn("arc_walk.agenda_never_repeated", self.ids(repeat, stage=stage))
        # A second `open` turn (the agenda already announced) is a repeat too.
        self.assertIn(
            "arc_walk.agenda_never_repeated",
            self.ids(repeat, stage="open", agenda_announced=True),
        )
        self.assertNotIn(
            "arc_walk.agenda_never_repeated",
            self.ids("What did the water sound like?", stage="walk"),
        )

    def test_one_question_per_reply(self):
        self.assertNotIn(
            "arc_walk.one_question_per_reply", self.ids("What happened next?")
        )
        self.assertIn(
            "arc_walk.one_question_per_reply",
            self.ids("What happened next? And who was there?"),
        )

    def test_no_counters(self):
        for bad in (
            "That's 3 of 6 done.",
            "Two more and we're through.",
            "You still have four left.",
            "There are questions left for later.",
        ):
            with self.subTest(bad=bad):
                self.assertIn("arc_walk.no_counters", self.ids(bad))
        self.assertNotIn("arc_walk.no_counters", self.ids("Tell me about the boat."))

    def test_no_mechanism_talk(self):
        for bad in (
            "Next on the plan is the boat.",
            "I'll file this under the harbor.",
            "The system will remember that.",
            "Your question bank has more of these.",
        ):
            with self.subTest(bad=bad):
                self.assertIn("arc_walk.no_mechanism_talk", self.ids(bad))
        self.assertNotIn(
            "arc_walk.no_mechanism_talk", self.ids("Tell me about the boat.")
        )

    def test_no_pressure(self):
        for bad in (
            "We left this unfinished.",
            "You didn't get to the boat.",
            "You still need to finish the rest.",
            "That's a four-day streak.",
        ):
            with self.subTest(bad=bad):
                self.assertIn("arc_walk.no_pressure", self.ids(bad))

    def test_close_summarizes(self):
        good = (
            "We covered the harbor and the boat — that's a good stretch. "
            "The rest will keep for whenever you like."
        )
        self.assertNotIn("arc_walk.close_summarizes", self.ids(good, stage="close"))
        for bad in (
            "We covered the harbor and the boat.",              # no waits
            "The rest will keep for whenever you like.",        # no covered
            good + " What else is on your mind?",               # asks
        ):
            with self.subTest(bad=bad):
                self.assertIn("arc_walk.close_summarizes", self.ids(bad, stage="close"))

    def test_unknown_stage_fails_toward_walk(self):
        repeat = "Today I'd love to hear about the harbor."
        self.assertIn("arc_walk.agenda_never_repeated", self.ids(repeat, stage="banana"))
        self.assertNotIn(
            "arc_walk.close_summarizes", self.ids("Tell me more.", stage="banana")
        )

    def test_lint_classes_match_the_finding_ids(self):
        produced = set()
        for stage in ("open", "walk", "close"):
            for text in ("", "Today I'd love to hear about it? Really? 3 of 6. The plan. Unfinished."):
                produced |= {
                    row["lint"].split(".", 1)[1]
                    for row in arc_walk.lint_arc_reply(text, stage=stage)
                }
        self.assertEqual(produced, set(arc_walk.ARC_WALK_LINT_CLASSES))


# ---------------------------------------------------------------------------
# The package (Design §A)
# ---------------------------------------------------------------------------


class PackageTests(unittest.TestCase):
    def test_registry_audit_is_clean_and_lineage_is_conversation_arc_walk(self):
        self.assertEqual(registry.audit_interaction_package("arc_walk"), [])
        self.assertEqual(
            registry.resolve_interaction_lineage("arc_walk"),
            ("conversation", "arc_walk"),
        )
        manifest = registry.load_interaction_manifest("arc_walk")
        self.assertEqual(manifest["interaction"], "arc_walk")
        self.assertEqual(manifest["version"], "1.0.0")
        self.assertEqual(manifest["extends"], "conversation")
        self.assertEqual(manifest["extends.version"], "1.0.0")
        self.assertEqual(manifest["modes"], "walk")

    def test_leaf_is_stage_keyed_and_placeholder_bearing(self):
        leaf = registry.compose_interaction_asset(
            "arc_walk", "prompt/turn-instructions.md"
        )
        for placeholder in (
            "{arc_stage}", "{agenda}", "{focus_label}",
            "{episode_size}", "{answered_k}", "{plan_n}",
        ):
            self.assertIn(placeholder, leaf)
        for stage in sorted(arc_walk.VALID_ARC_STAGES):
            self.assertIn(f"`{stage}`", leaf)
        self.assertIn("answered_question_id", leaf)

    def test_router_deflection_routes_a_departure_to_the_close(self):
        deflection = registry.compose_interaction_asset("arc_walk", "router/deflection.md")
        self.assertIn("Close instead", deflection)

    def test_preexisting_interaction_assets_remain_byte_identical(self):
        """This PR adds a sibling package and must not move the two the
        placement/onboarding contracts pinned."""
        expected = {
            "conversation": (
                # v196: prompt/turn-instructions.md carries the whisper direction.
                "9e201849154a49d698aabc48cd856f5358a0f9e3e31bea85ad0690075b4b1970"
            ),
            "question_candidate": (
                "f549af401b4765166cc8d3618439d2b367ab799f16f43f3a1a3c5dae764786f5"
            ),
        }
        for package, digest in expected.items():
            with self.subTest(package=package):
                hasher = hashlib.sha256()
                root = ROOT / "interactions" / package
                for path in sorted(root.rglob("*")):
                    if path.is_file():
                        hasher.update(path.relative_to(root).as_posix().encode())
                        hasher.update(b"\0")
                        hasher.update(path.read_bytes())
                        hasher.update(b"\0")
                self.assertEqual(hasher.hexdigest(), digest)

    def test_every_new_file_ships_in_framework_files(self):
        manifest = json.loads((SYSTEM / "version.json").read_text(encoding="utf-8"))
        shipped = set(manifest["framework_files"])
        for path in sorted((ROOT / "interactions" / "arc_walk").rglob("*")):
            if path.is_file():
                self.assertIn(path.relative_to(ROOT).as_posix(), shipped)
        for name in ("system/arc_walk.py", "system/arc_walk_evals.py"):
            self.assertIn(name, shipped)


# ---------------------------------------------------------------------------
# The read-only CLI (Design §E)
# ---------------------------------------------------------------------------


class ArcPlanTargetCliTests(unittest.TestCase):
    """Full-process pin against a synthetic external vault
    (env LIFEHUG_VAULT_ROOT), the tests/test_ingest_and_planner.py style."""

    def setUp(self):
        self.tmp = root_parent_tmp(self, ROOT, prefix="lifehug-v193-arc-plan-")

    def _make_vault(self) -> Path:
        vault = self.tmp / "vault"
        (vault / "state").mkdir(parents=True)
        (vault / "question-bank.md").write_text(
            "# Synthetic Lifehug questions\n\n"
            "## H: Synthetic Harbor\n"
            "- [x] H1: What first brought you to the harbor?\n"
            "- [ ] H2: What did the water sound like in winter?\n"
            "- [ ] H3: Who was on the dock the first time?\n",
            encoding="utf-8",
        )
        (vault / "state" / "rotation.json").write_text(json.dumps({
            "version": 1, "current_pass": 1,
            "pass_names": ["skeleton", "depth", "connections", "polish"],
            "last_question_id": None, "last_asked_at": None, "questions_asked": 0,
            "questions_answered": 0, "next_question_id": None, "focus_frequency": 4,
        }), encoding="utf-8")
        (vault / "state" / "coverage.json").write_text(json.dumps({
            "version": 1, "last_updated": None,
            "categories": {"H": {"total": 3, "answered": 1, "status": "yellow"}},
        }), encoding="utf-8")
        roadmap = {
            "version": 1,
            "focuses": [{
                "id": "synthetic-harbor", "label": "Synthetic Harbor",
                "type": "place", "tier": "basic", "categories": ["H"],
                "target_depth": 10, "phase": "active",
            }],
        }
        (vault / "state" / "roadmap.json").write_text(json.dumps(roadmap), encoding="utf-8")
        return vault

    def _run(self, vault: Path, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(SYSTEM / "lifehug.py"), "arc-plan-target", *args],
            capture_output=True, text=True, cwd=str(vault),
            env={"PATH": "/usr/bin:/bin", "HOME": str(vault),
                 "LIFEHUG_VAULT_ROOT": str(vault)},
        )

    @staticmethod
    def _fingerprint(root: Path) -> dict[str, str]:
        return {
            str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(root.rglob("*")) if path.is_file()
        }

    def test_arc_plan_target_prints_k_of_n_and_writes_nothing(self):
        vault = self._make_vault()
        before = self._fingerprint(vault)
        result = self._run(vault, "--focus", "synthetic-harbor")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("1 of 3 answered", result.stdout)
        self.assertIn("Synthetic Harbor", result.stdout)
        self.assertIn("episode of 4", result.stdout)  # tier basic
        self.assertNotIn("H1", result.stdout)  # answered questions fall out
        self.assertEqual(self._fingerprint(vault), before)

    def test_arc_plan_target_json_emits_the_plan_dict(self):
        vault = self._make_vault()
        result = self._run(vault, "--focus", "synthetic-harbor", "--episode-size", "2", "--json")
        self.assertEqual(result.returncode, 0, result.stderr)
        plan = json.loads(result.stdout)
        self.assertEqual(
            set(plan),
            {"target", "focus_label", "questions", "episode_size", "plan_n", "answered_k"},
        )
        self.assertEqual(plan["episode_size"], 2)
        self.assertEqual(plan["plan_n"], 3)
        self.assertEqual(plan["answered_k"], 1)
        self.assertEqual([row["id"] for row in plan["questions"]], ["H2", "H3"])

    def test_arc_plan_target_refuses_an_unknown_focus(self):
        vault = self._make_vault()
        result = self._run(vault, "--focus", "nope")
        self.assertEqual(result.returncode, 1)
        self.assertIn("no focus", result.stderr)

    def test_arc_plan_target_resolves_a_bare_category_and_a_chapter(self):
        vault = self._make_vault()
        for flag in ("--category", "--chapter"):
            with self.subTest(flag=flag):
                result = self._run(vault, flag, "H", "--json")
                self.assertEqual(result.returncode, 0, result.stderr)
                plan = json.loads(result.stdout)
                self.assertEqual(plan["target"]["categories"], ["H"])
                self.assertEqual(plan["target"]["kind"], flag.lstrip("-"))

    def test_arc_plan_target_refuses_an_empty_queue_rather_than_planning_nothing(self):
        """An honest refusal: a target nobody can enumerate is a caller bug."""
        vault = self._make_vault()
        result = self._run(vault, "--queue")
        self.assertEqual(result.returncode, 1)
        self.assertIn("at least one category", result.stderr)


if __name__ == "__main__":
    unittest.main()
