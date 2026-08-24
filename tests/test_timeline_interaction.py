"""v195 / ADR 0024 — the Timeline Interaction, the fifth child of Conversation.

The paradigm's checklist, applied: registered and audited, composition exact,
a stage derived from the transcript plus caller facts, exactly ONE additive
output field with two validation layers, five lints, and — ruling 7 — an
output-contract appendix that does not move by one byte for a passive user.

Synthetic data only; NEVER references ~/Workspace/dave.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SYSTEM = ROOT / "system"
sys.path.insert(0, str(SYSTEM))

import arc_planner  # noqa: E402
import chronology as chrono  # noqa: E402
import conversation_delivery as cd  # noqa: E402
import interaction_registry as registry  # noqa: E402
import timeline_interaction as ti  # noqa: E402

BIRTH = {"key": "birth", "label": "when you were born", "kind": "birth", "date": "1979"}
MESA = {"key": "mesa", "label": "the Mesa house", "kind": "residence", "date": "1984/1990"}
COLLEGE = {"key": "college", "label": "College", "kind": "period", "date": "1997/2001"}


def shape(**kwargs):
    base = {"position": "middle", "question_allowed": True, "user_turns": 2,
            "target_exchanges": 6}
    base.update(kwargs)
    return cd.TurnShape(**base)


class RegistrationTests(unittest.TestCase):
    def test_the_registry_is_exact_and_the_package_audits_clean(self):
        value = registry.load_interaction_registry()
        self.assertEqual(
            [(row["id"], row["package"]) for row in value["interactions"]],
            [
                ("conversation", "conversation"),
                ("focus_curation", "focus_curation"),
                ("question_judgment", "question_judgment"),
                ("question_candidate", "question_candidate"),
                ("focus_candidate", "focus_candidate"),
                ("entity_candidate", "entity_candidate"),
                ("arc_walk", "arc_walk"),
                ("timeline", "timeline"),
                ("landmarks", "landmarks"),
            ("reading_room", "reading_room"),
            ],
        )
        self.assertEqual(registry.audit_interaction_package("timeline"), [])

    def test_timeline_has_distinct_identity_and_parent_lineage(self):
        self.assertEqual(registry.resolve_interaction_lineage("timeline"),
                         ("conversation", "timeline"))
        manifest = registry.load_interaction_manifest("timeline")
        self.assertEqual(manifest["interaction"], "timeline")
        self.assertEqual(manifest["version"], "1.0.0")
        self.assertEqual(manifest["extends"], "conversation")
        self.assertEqual(manifest["extends.version"], "1.0.0")

    def test_composition_covers_every_composable_asset_exactly(self):
        manifest = registry.load_interaction_manifest("timeline")
        declared = set(manifest["composition.append"].split("|")) | set(
            manifest["composition.leaf"].split("|"))
        self.assertEqual(declared, set(registry.COMPOSABLE_FILES))

    def test_behavior_composes_parent_then_child_with_provenance(self):
        composed = registry.compose_interaction_asset("timeline", "prompt/behavior.md")
        parent = (ROOT / "interactions/conversation/prompt/behavior.md").read_text()
        child = (ROOT / "interactions/timeline/prompt/behavior.md").read_text()
        self.assertEqual(
            composed,
            "<!-- interaction:conversation asset:prompt/behavior.md -->\n" + parent
            + "\n<!-- interaction:timeline asset:prompt/behavior.md -->\n" + child,
        )

    def test_the_leaf_is_child_authority_only(self):
        composed = registry.compose_interaction_asset("timeline", "prompt/turn-instructions.md")
        self.assertIn("interaction:timeline", composed)
        self.assertNotIn("interaction:conversation", composed)

    def test_the_leaf_names_every_placeholder_the_manifest_promises(self):
        leaf = (ROOT / "interactions/timeline/prompt/turn-instructions.md").read_text()
        for placeholder in ("{timeline_stage}", "{unknown_label}", "{probe}",
                            "{anchors}", "{precision_so_far}"):
            self.assertIn(placeholder, leaf)

    def test_stop_rule_knobs_match_the_module_constants(self):
        manifest = registry.load_interaction_manifest("timeline")
        self.assertEqual(int(manifest["knob.stop_after_unproductive_probes"]),
                         ti.STOP_AFTER_UNPRODUCTIVE_PROBES)
        self.assertEqual(int(manifest["knob.max_probes"]), ti.MAX_PROBES)


class OutputContractTests(unittest.TestCase):
    def test_output_contract_block_byte_identical_without_timeline_stage(self):
        """Owner ruling 7, mechanically: the passive daily question's prompt
        does not move by one byte."""
        self.assertEqual(
            cd._output_contract_block(shape()),  # noqa: SLF001
            cd._output_contract_block(shape(timeline_stage=None)),  # noqa: SLF001
        )
        self.assertNotIn('"placed"', cd._output_contract_block(shape()))  # noqa: SLF001

    def test_the_placed_key_appears_only_when_the_gate_is_set(self):
        block = cd._output_contract_block(shape(timeline_stage="place"))  # noqa: SLF001
        self.assertIn('"placed"', block)

    def test_the_contract_no_longer_offers_a_deferral_shape(self):
        """v196: "I'll find out" is an ordinary answer — there is nothing to
        emit for it, and an interval is still a first-class placement."""
        block = cd._output_contract_block(shape(timeline_stage="place"))  # noqa: SLF001
        self.assertNotIn("deferred", block)
        self.assertIn("An interval is a finding", block)

    def test_the_gate_defaults_to_none_like_every_other_child(self):
        self.assertIsNone(shape().timeline_stage)


class StructuralParseTests(unittest.TestCase):
    def test_a_date_record_shape_survives(self):
        self.assertEqual(
            cd._parse_placed({"best": "1984~", "anchors": ["birth"]}),  # noqa: SLF001
            {"best": "1984~", "anchors": ["birth"]},
        )

    def test_the_deferral_shape_is_gone(self):
        """v196: the structural layer no longer knows the word."""
        self.assertIsNone(cd._parse_placed({"deferred": True}))  # noqa: SLF001

    def test_every_malformed_shape_degrades_to_none_and_never_raises(self):
        for value in (None, "1984", [], {}, {"deferred": "yes"},
                      {"best": "1984", "nope": 1}, {"granularity": "year"},
                      {"best": 1984}, {"best": "x" * 40}, {"anchors": ["a"]},
                      {"best": "  "}):
            with self.subTest(value=value):
                self.assertIsNone(cd._parse_placed(value))  # noqa: SLF001

    def test_the_structural_layer_owns_no_vocabulary(self):
        # "epoch" is not a granularity — and this layer deliberately does not
        # know that; the closed layer does.
        self.assertEqual(
            cd._parse_placed({"best": "1984", "granularity": "epoch"}),  # noqa: SLF001
            {"best": "1984", "granularity": "epoch"},
        )
        self.assertIsNone(ti.validate_placed({"best": "1984", "granularity": "epoch"}))

    def test_parse_turn_output_carries_the_field_and_degrades_without_it(self):
        import json  # noqa: PLC0415

        parsed = cd.parse_turn_output(json.dumps(
            {"message": "hello", "placed": {"best": "1984"}}))
        self.assertEqual(parsed["placed"], {"best": "1984"})
        self.assertIsNone(cd.parse_turn_output(json.dumps({"message": "hello"}))["placed"])


class StageTests(unittest.TestCase):
    OPEN = {"turns": []}
    STARTED = {"turns": [{"role": "lifehug"}, {"role": "user"}]}

    def test_no_assistant_turn_yet_is_open(self):
        self.assertEqual(ti.timeline_stage_for_session(self.OPEN), "open")
        self.assertEqual(ti.timeline_stage_for_session(None), "open")

    def test_an_episode_in_flight_is_place(self):
        self.assertEqual(ti.timeline_stage_for_session(self.STARTED), "place")

    def test_leaving_closes_from_anywhere(self):
        self.assertEqual(ti.timeline_stage_for_session(self.OPEN, user_leaving=True), "close")

    def test_a_settled_placement_closes(self):
        self.assertEqual(
            ti.timeline_stage_for_session(self.STARTED, placement_settled=True), "close")

    def test_two_probes_with_no_new_bound_close_the_ladder(self):
        self.assertEqual(
            ti.timeline_stage_for_session(self.STARTED, no_new_bound_streak=2), "close")
        self.assertEqual(
            ti.timeline_stage_for_session(self.STARTED, no_new_bound_streak=1), "place")

    def test_a_nonsense_streak_is_treated_as_zero(self):
        self.assertEqual(
            ti.timeline_stage_for_session(self.STARTED, no_new_bound_streak="lots"), "place")

    def test_the_absolute_probe_ceiling_closes(self):
        session = {"turns": [{"role": "lifehug"}] + [{"role": "user"}] * ti.MAX_PROBES}
        self.assertEqual(ti.timeline_stage_for_session(session), "close")

    def test_precision_so_far_takes_the_finest_record_in_the_transcript(self):
        session = {"turns": [
            {"role": "lifehug", "placed": {"best": "198X", "earliest": "1980",
                                           "latest": "1989", "granularity": "era"}},
            {"role": "lifehug", "placed": {"best": "1984", "earliest": "1984",
                                           "latest": "1984", "granularity": "year"}},
        ]}
        self.assertEqual(chrono.to_edtf(ti.precision_so_far(session)), "1984")
        self.assertIsNone(ti.precision_so_far({"turns": []}))


class AnchorTests(unittest.TestCase):
    def test_anchors_order_birth_then_residence_then_period_then_landmark(self):
        anchors = ti.anchors_for_person(
            birth_date="1979",
            places=[{"slug": "mesa", "title": "the Mesa house", "date": "1984/1990"}],
            periods=[{"slug": "college", "name": "College", "date": "1997/2001"}],
            events=[{"key": "A1", "title": "the letter", "date": "1986"}],
        )
        self.assertEqual([row["kind"] for row in anchors],
                         ["birth", "residence", "period", "landmark"])
        self.assertEqual(anchors[0]["key"], "birth")

    def test_undated_things_are_never_anchors(self):
        anchors = ti.anchors_for_person(places=[{"slug": "nowhere", "date": None}])
        self.assertEqual(anchors, ())

    def test_render_anchors_says_each_landmark_in_words(self):
        text = ti.render_anchors([BIRTH, MESA])
        self.assertIn("when you were born — 1979", text)
        self.assertIn("the Mesa house — 1984–1990", text)

    def test_render_anchors_is_honest_when_there_is_nothing(self):
        self.assertIn("nothing dated yet", ti.render_anchors([]))


class ProbeTests(unittest.TestCase):
    def test_the_ladder_starts_concretely_and_never_at_a_year(self):
        """v196 (owner-set): every probe NAMES its subject. An era gap opens on
        the stretch it is actually about, not on "tell me what happened"."""
        probe = ti.choose_probe({"kind": "era_gap", "label": "the gap",
                                 "between": ["yucaipa-years", "san-diego"]})
        self.assertEqual(probe["step"], "parallel_domain")
        self.assertIn("yucaipa years", probe["text"])
        self.assertNotIn("year?", probe["text"].lower())

    def test_the_bare_content_probe_survives_only_for_an_unanchored_moment(self):
        moment = {"kind": "moment", "label": "the dog that followed you home"}
        self.assertEqual(ti.choose_probe(moment)["step"], "content")
        self.assertIn("the dog that followed you home", ti.choose_probe(moment)["text"])
        anchored = ti.choose_probe(moment, anchors=[MESA])
        self.assertEqual(anchored["step"], "sequence")
        self.assertIn("the Mesa house", anchored["text"])

    def test_the_ladder_ascends_in_the_playbooks_order(self):
        """The rungs are unchanged; the kind's own opener leads, and the ladder
        takes over from the second probe on."""
        asked = []
        steps = []
        for _ in range(4):
            probe = ti.choose_probe({"kind": "era_gap", "label": "x",
                                     "between": ["a", "b"]},
                                    anchors=[MESA], asked_steps=asked)
            steps.append(probe["step"])
            asked.append(probe["step"])
        self.assertEqual(steps, ["parallel_domain", "residence", "role", "sequence"])

    def test_rungs_that_need_a_landmark_are_skipped_without_one(self):
        asked = ["content", "residence", "role", "parallel_domain"]
        self.assertEqual(
            ti.choose_probe({"kind": "era_gap", "label": "x"}, asked_steps=asked)["step"],
            "season",
        )
        self.assertEqual(
            ti.choose_probe({"kind": "era_gap", "label": "x"}, anchors=[MESA],
                            asked_steps=asked)["step"],
            "sequence",
        )

    def test_a_landmark_probe_names_the_persons_own_landmark(self):
        probe = ti.choose_probe({"kind": "era_gap", "label": "x"}, anchors=[MESA],
                                asked_steps=["content", "residence", "role",
                                             "parallel_domain", "sequence"])
        self.assertEqual(probe["step"], "landmark")
        self.assertIn("the Mesa house", probe["text"])

    def test_the_ladder_stops_early_once_precision_is_enough(self):
        probe = ti.choose_probe({"kind": "era_gap", "label": "x"},
                                precision_so_far="year")
        self.assertEqual(probe["step"], "convergence")

    def test_a_coarser_slot_stops_at_a_coarser_rung(self):
        self.assertEqual(
            ti.choose_probe({"kind": "place_span", "label": "x"},
                            precision_so_far="era")["step"], "convergence")
        self.assertNotEqual(
            ti.choose_probe({"kind": "era_gap", "label": "x"},
                            precision_so_far="era")["step"], "convergence")

    def test_the_defer_rung_survives_as_the_ladders_last_line(self):
        """v196 deleted the deferral STATE, not the courtesy: the gentlest
        rung is still reachable and still asks nothing."""
        probe = ti.choose_probe({"kind": "era_gap", "label": "x"},
                                asked_steps=ti.PLAYBOOK_ORDER)
        self.assertEqual(probe["step"], "defer")
        self.assertNotIn("?", probe["text"])

    def test_a_deferred_flag_is_no_longer_consulted(self):
        self.assertEqual(
            ti.choose_probe({"kind": "era_gap", "label": "x", "deferred": True}),
            ti.choose_probe({"kind": "era_gap", "label": "x"}),
        )

    def test_a_probe_is_always_returned(self):
        probe = ti.choose_probe({}, asked_steps=ti.PLAYBOOK_ORDER)
        self.assertIn(probe["step"], ti.PLAYBOOK_ORDER)


class ValidatePlacedTests(unittest.TestCase):
    GOOD = {"best": "1984~", "earliest": "1983", "latest": "1986",
            "granularity": "range", "confidence": "approximate", "basis": "age",
            "anchors": ["birth"]}

    def test_a_well_formed_record_survives_with_its_anchor(self):
        result = ti.validate_placed(self.GOOD, anchors=[BIRTH])
        self.assertEqual(result["best"], "1984~")
        self.assertEqual(result["anchors"], ["birth"])

    def test_an_anchor_the_episode_never_offered_drops_the_whole_record(self):
        self.assertIsNone(ti.validate_placed(self.GOOD, anchors=[MESA]))
        self.assertIsNone(ti.validate_placed(self.GOOD))

    def test_off_vocabulary_values_are_rejected(self):
        for key, value in (("granularity", "epoch"), ("confidence", "sure"),
                           ("basis", "vibes")):
            with self.subTest(key=key):
                self.assertIsNone(
                    ti.validate_placed({**self.GOOD, key: value}, anchors=[BIRTH]))

    def test_unparseable_edtf_is_rejected(self):
        self.assertIsNone(ti.validate_placed(
            {**self.GOOD, "best": "sometime"}, anchors=[BIRTH]))
        self.assertIsNone(ti.validate_placed(
            {**self.GOOD, "earliest": "whenever"}, anchors=[BIRTH]))

    def test_the_deferral_form_is_rejected(self):
        self.assertIsNone(ti.validate_placed({"deferred": True}))
        self.assertIsNone(ti.validate_placed({"deferred": False}))

    def test_a_range_with_a_basis_is_first_class(self):
        """"About preschool, three to five" files as an interval (v196)."""
        placed = ti.validate_placed(
            {"earliest": "1983", "latest": "1985", "best": "1983/1985",
             "granularity": "range", "confidence": "approximate", "basis": "age",
             "anchors": ["birth"]},
            anchors=[BIRTH])
        self.assertIsNotNone(placed)
        self.assertEqual(placed["granularity"], "range")
        self.assertEqual(placed["basis"], "age")
        argv = ti.place_invocation(placed, source="answers/A1.md",
                                   description="preschool", period="childhood")
        self.assertEqual(argv[argv.index("--date") + 1], "1983/1985")

    def test_every_other_shape_is_none(self):
        for value in (None, "1984", [], {}, 5, {"anchors": ["birth"]}):
            with self.subTest(value=value):
                self.assertIsNone(ti.validate_placed(value, anchors=[BIRTH]))


class PlaceInvocationTests(unittest.TestCase):
    def test_the_bridge_builds_the_exact_timeline_place_argv(self):
        args = ti.place_invocation(
            {"best": "1984~", "earliest": "1983", "latest": "1986",
             "granularity": "range", "confidence": "approximate", "basis": "age",
             "anchors": ["birth"]},
            source="answers/A1.md", description="the letter", period="childhood")
        self.assertEqual(args[:4], ["timeline-place", "answers/A1.md", "--period", "childhood"])
        self.assertIn("--date", args)
        self.assertEqual(args[args.index("--date") + 1], "1984~")
        self.assertEqual(args[args.index("--basis") + 1], "age")
        self.assertEqual(args[args.index("--anchor") + 1], "birth")

    def test_a_deferral_object_files_nothing(self):
        self.assertIsNone(ti.place_invocation({"deferred": True}, source="s",
                                              description="d", period="p"))

    def test_a_missing_target_files_nothing(self):
        self.assertIsNone(ti.place_invocation({"best": "1984"}, source="",
                                              description="d", period="p"))


class LintTests(unittest.TestCase):
    def test_the_year_demand_patterns_cover_the_planners_banned_phrase(self):
        """One rule, one definition: the planner's ban and this lint can never
        become two different rules."""
        self.assertTrue(any(pattern.search(f"So {arc_planner.BANNED_PHRASE} was that?")
                            for pattern in ti._YEAR_DEMAND_RES))  # noqa: SLF001

    def test_no_year_opener_fires_and_passes(self):
        self.assertIn("timeline_gates.no_year_opener",
                      {f["lint"] for f in ti.lint_timeline_reply(
                          "What year was that?", stage="open")})
        self.assertNotIn("timeline_gates.no_year_opener",
                         {f["lint"] for f in ti.lint_timeline_reply(
                             "Where were you living then?", stage="open")})

    def test_one_question_per_reply_fires_and_passes(self):
        self.assertIn("timeline_gates.one_question_per_reply",
                      {f["lint"] for f in ti.lint_timeline_reply(
                          "Where were you? And when?", stage="place")})
        self.assertNotIn("timeline_gates.one_question_per_reply",
                         {f["lint"] for f in ti.lint_timeline_reply(
                             "Where were you living then?", stage="place")})

    def test_offers_bounds_fires_and_passes(self):
        self.assertIn("timeline_gates.offers_bounds",
                      {f["lint"] for f in ti.lint_timeline_reply(
                          "Give me the month.", stage="place", probe_step="bounds")})
        self.assertNotIn("timeline_gates.offers_bounds",
                         {f["lint"] for f in ti.lint_timeline_reply(
                             "Spring, or is somewhere in a couple of years more honest?",
                             stage="place", probe_step="bounds")})

    def test_accepts_defer_fires_and_passes(self):
        self.assertIn("timeline_gates.accepts_defer",
                      {f["lint"] for f in ti.lint_timeline_reply(
                          "Sure, but even roughly?", stage="close", probe_step="defer")})
        self.assertIn("timeline_gates.accepts_defer",
                      {f["lint"] for f in ti.lint_timeline_reply(
                          "Fine — but which decade?", stage="close", probe_step="defer")})
        self.assertNotIn("timeline_gates.accepts_defer",
                         {f["lint"] for f in ti.lint_timeline_reply(
                             "Then let's leave it with her; it'll keep.",
                             stage="close", probe_step="defer")})

    def test_never_invents_a_date_fires_and_passes(self):
        self.assertIn("timeline_gates.never_invents_a_date",
                      {f["lint"] for f in ti.lint_timeline_reply(
                          "That would have been 1993, then.", stage="place",
                          probe_step="landmark", known_years=["1979"])})
        self.assertNotIn("timeline_gates.never_invents_a_date",
                         {f["lint"] for f in ti.lint_timeline_reply(
                             "That puts it around 1984.", stage="place",
                             probe_step="landmark", known_years=["1984"])})

    def test_an_unknown_stage_fails_toward_the_stricter_rule(self):
        findings = ti.lint_timeline_reply("What year was that?", stage="nonsense")
        self.assertTrue(findings)

    def test_findings_share_the_conversation_lint_shape(self):
        for finding in ti.lint_timeline_reply("What year was that?", stage="open"):
            self.assertEqual(set(finding), {"lint", "detail", "span"})
            self.assertEqual(len(finding["span"]), 2)


if __name__ == "__main__":
    unittest.main()
