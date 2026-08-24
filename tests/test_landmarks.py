"""v197 / landmarks — the always-present dating question set.

The sixth child of Conversation. Its job is to fill the anchor index that four
existing systems already read, so that `chronology.from_age` and the two
`needs_anchor` playbook rungs stop being unreachable.

Synthetic data only; NEVER references ~/Workspace/dave.
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SYSTEM = ROOT / "system"
sys.path.insert(0, str(SYSTEM))
sys.path.insert(0, str(ROOT / "tests"))

import chronology as chrono  # noqa: E402
import conversation_delivery as engine  # noqa: E402
import landmarks_evals  # noqa: E402
import landmarks_interaction as li  # noqa: E402
from tempdirs import root_parent_tmp  # noqa: E402


def _date(best: str, basis: str = "stated") -> dict:
    record = chrono.parse_edtf(best, basis=basis)
    assert record is not None
    return record.to_dict()


class QuestionSetTests(unittest.TestCase):
    """The set is DATA, and the data is well formed."""

    def setUp(self) -> None:
        self.rows = li.load_questions()

    def test_the_set_is_ordered_and_complete(self):
        self.assertEqual([r["order"] for r in self.rows],
                         list(range(1, len(self.rows) + 1)))
        for row in self.rows:
            self.assertTrue(row["ask"])
            self.assertTrue(row["ladder"])
            self.assertTrue(row["why"], f"{row['domain']} has no sourced reason")
            self.assertIn(row["complete_at"], row["ladder"])

    def test_residences_and_schools_lead_and_are_chains(self):
        """landmarks.md §2.7: the two closed lists come first."""
        order = [r["domain"] for r in self.rows]
        self.assertEqual(order[0], "birth", "the axis is first")
        self.assertEqual(order[1:3], ["residences", "schools"])
        for domain in ("residences", "schools"):
            self.assertTrue(li.domain_row(domain)["chain"])

    def test_every_rung_has_a_question(self):
        for row in self.rows:
            for rung in row["ladder"]:
                self.assertIn((row["domain"], rung), li.RUNG_TEXTS,
                              f"no rung text for {row['domain']}.{rung}")

    def test_losses_is_sensitive_and_never_at_onboarding(self):
        losses = li.domain_row("losses")
        self.assertTrue(losses["sensitive"])
        self.assertFalse(losses["onboarding"])
        self.assertNotIn("losses", li.onboarding_domains())

    def test_onboarding_is_the_general_pass_only(self):
        """Owner ruling 1: onboarding asks in generalities."""
        self.assertEqual(li.onboarding_domains(),
                         ("birth", "residences", "schools", "partnerships",
                          "children"))

    def test_an_unknown_domain_is_refused(self):
        with self.assertRaises(li.LandmarkInteractionError):
            li.domain_row("pets")

    def test_stop_rule_knobs_match_the_module_constants(self):
        raw = (ROOT / "interactions" / "landmarks" / "interaction.yaml").read_text(
            encoding="utf-8"
        )
        self.assertIn(f"knob.max_asks: {li.MAX_ASKS}", raw)
        self.assertIn(f"knob.stop_after_skips: {li.STOP_AFTER_SKIPS}", raw)


class LadderTests(unittest.TestCase):
    """Owner ruling 3: a vague answer is an answer, and the ladder is a ladder."""

    def setUp(self) -> None:
        self.residences = li.domain_row("residences")

    def test_a_city_alone_reaches_the_first_rung(self):
        entry = {"label": "Dayton", "city": "Dayton"}
        self.assertEqual(li.rung_reached(entry, self.residences), "city")
        self.assertEqual(li.status_for_domain([entry], self.residences), "partial")

    def test_the_ladder_stops_at_the_first_hole(self):
        """A span with no address is still at `city` — rungs are not skipped."""
        entry = {"label": "Dayton", "city": "Dayton",
                 "span": {"start": _date("1984"), "end": _date("1990")}}
        self.assertEqual(li.rung_reached(entry, self.residences), "city")

    def test_the_next_question_is_the_next_rung(self):
        entry = {"label": "Bell Avenue", "city": "Dayton"}
        question = li.next_rung([entry], self.residences)
        self.assertEqual(question["rung"], "address")
        self.assertIn("Bell Avenue", question["text"])

    def test_an_empty_domain_opens_with_its_general_question(self):
        question = li.next_rung([], self.residences)
        self.assertEqual(question["rung"], "city")
        self.assertIsNone(question["subject"])
        self.assertEqual(question["text"], self.residences["ask"])

    def test_a_chain_is_not_complete_until_the_person_says_so(self):
        entry = {"label": "Bell Avenue", "city": "Dayton", "address": "11 Bell",
                 "span": {"start": _date("1984"), "end": _date("1990")}}
        self.assertEqual(li.status_for_domain([entry], self.residences), "partial")
        self.assertEqual(li.next_rung([entry], self.residences)["text"],
                         li.CHAIN_MORE_TEXTS["residences"])
        entry["chain_complete"] = True
        self.assertEqual(li.status_for_domain([entry], self.residences), "complete")
        self.assertIsNone(li.next_rung([entry], self.residences))


class LedgerTests(unittest.TestCase):
    """Owner ruling 2: only the open ones are offerable, and the ★ moves."""

    def test_complete_domains_are_never_offered(self):
        landmarks = {"birth": [{"year": "1978", "month": "04", "day": "12",
                                "date": _date("1978-04-12")}]}
        rows = li.landmark_rows(landmarks)
        birth = next(r for r in rows if r["domain"] == "birth")
        self.assertEqual(birth["status"], "complete")
        self.assertIsNone(birth["next"])
        self.assertNotIn("birth", [r["domain"] for r in li.open_landmarks(rows)])

    def test_the_keystone_star_moves_with_the_leverage(self):
        rows = li.landmark_rows({}, keystone_domains=("schools",))
        starred = [r["domain"] for r in rows if r["keystone"]]
        self.assertEqual(starred, ["schools"])
        self.assertEqual(li.open_landmarks(rows)[0]["domain"], "schools")

    def test_sensitive_domains_sort_behind_the_rest(self):
        rows = li.landmark_rows({})
        order = [r["domain"] for r in li.open_landmarks(rows)]
        self.assertEqual(order[-1], "losses")

    def test_the_block_never_names_what_remains(self):
        """`no_form_voice` in data form: the prompt block carries status, not
        a countdown."""
        rows = li.landmark_rows({"birth": [{"year": "1978",
                                            "date": _date("1978")}]})
        block = li.render_landmarks(rows)
        self.assertIn("birth", block)
        for banned in ("remaining", "of 8", "left", "to go", "%"):
            self.assertNotIn(banned, block)


class StageTests(unittest.TestCase):
    def test_the_first_turn_opens(self):
        self.assertEqual(li.landmark_stage_for_session({"turns": []}), "open")

    def test_leaving_closes(self):
        session = {"turns": [{"role": "user"}]}
        self.assertEqual(
            li.landmark_stage_for_session(session, user_leaving=True), "close"
        )

    def test_two_skips_in_a_row_close_it(self):
        session = {"turns": [{"role": "user"}]}
        self.assertEqual(
            li.landmark_stage_for_session(session,
                                          skip_streak=li.STOP_AFTER_SKIPS),
            "close",
        )

    def test_the_ask_ceiling_closes_it(self):
        session = {"turns": [{"role": "user"}] * li.MAX_ASKS}
        self.assertEqual(li.landmark_stage_for_session(session), "close")


class OutputContractTests(unittest.TestCase):
    """The additive field, and the byte-identity guarantee."""

    def _block(self, **kwargs) -> str:
        shape = engine.TurnShape(position="middle", question_allowed=True,
                                 user_turns=1, target_exchanges=6, **kwargs)
        return engine._output_contract_block(shape)  # noqa: SLF001

    def test_output_contract_block_byte_identical_without_landmark_stage(self):
        self.assertEqual(self._block(), self._block(landmark_stage=None))
        self.assertNotIn('"landmark"', self._block())

    def test_the_key_appears_only_with_the_stage(self):
        block = self._block(landmark_stage="ask")
        self.assertIn('"landmark"', block)
        self.assertIn("coarse answer is an answer", block)

    def test_the_structural_layer_refuses_an_extra_key(self):
        self.assertIsNone(engine._parse_landmark(  # noqa: SLF001
            {"domain": "residences", "favourite_colour": "blue"}
        ))

    def test_the_structural_layer_requires_a_domain(self):
        self.assertIsNone(engine._parse_landmark({"label": "Bell"}))  # noqa: SLF001

    def test_an_invented_domain_is_dropped_by_the_second_layer(self):
        structural = engine._parse_landmark({"domain": "pets",  # noqa: SLF001
                                             "label": "Rufus"})
        self.assertIsNotNone(structural)
        self.assertIsNone(li.validate_landmark(structural))

    def test_a_skip_survives_validation(self):
        self.assertEqual(li.validate_landmark({"domain": "work", "skipped": True}),
                         {"domain": "work", "skipped": True})

    def test_a_bare_domain_is_not_a_landmark(self):
        self.assertIsNone(li.validate_landmark({"domain": "birth"}))

    def test_a_date_gets_its_bounds_filled_in(self):
        """A record with no earliest/latest renders empty and dates nothing."""
        validated = li.validate_landmark({
            "domain": "birth", "year": "1978",
            "date": {"best": "1978", "granularity": "year",
                     "confidence": "certain", "basis": "stated"},
        })
        self.assertEqual(validated["date"]["earliest"], "1978")
        self.assertEqual(validated["date"]["latest"], "1978")
        self.assertTrue(chrono.display_date(chrono.from_dict(validated["date"])))

    def test_parse_turn_output_carries_the_field(self):
        raw = json.dumps({
            "message": "Where did you live?",
            "followup_question": None,
            "question_free": False,
            "landmark": {"domain": "residences", "label": "Dayton",
                         "city": "Dayton"},
        })
        parsed = engine.parse_turn_output(raw)
        self.assertEqual(parsed["landmark"]["domain"], "residences")


class LintTests(unittest.TestCase):
    def test_the_year_demand_is_a_finding(self):
        findings = li.lint_landmark_reply("What year was that?", stage="ask",
                                          domain="residences")
        self.assertEqual([f["lint"] for f in findings],
                         ["landmark_gates.no_year_demand"])

    def test_the_birthday_is_the_one_carve_out(self):
        self.assertEqual(
            li.lint_landmark_reply("What year were you born?", stage="ask",
                                   domain="birth"),
            [],
        )

    def test_sharpening_a_coarse_answer_is_a_finding(self):
        findings = li.lint_landmark_reply("Can you be more specific?",
                                          stage="ask", domain="residences")
        self.assertIn("landmark_gates.accepts_vague",
                      [f["lint"] for f in findings])

    def test_form_voice_is_a_finding(self):
        findings = li.lint_landmark_reply("You have 6 of 15 left to go.",
                                          stage="ask", domain="residences")
        self.assertIn("landmark_gates.no_form_voice",
                      [f["lint"] for f in findings])

    def test_two_domains_in_one_turn_is_a_finding(self):
        findings = li.lint_landmark_reply(
            "Where did you live, and where did you work?", stage="ask",
            domain="residences", domains_named=("residences", "work"),
        )
        self.assertIn("landmark_gates.one_domain_per_turn",
                      [f["lint"] for f in findings])

    def test_pressing_a_sensitive_domain_is_a_finding(self):
        findings = li.lint_landmark_reply("Are you sure? Try to think back.",
                                          stage="ask", domain="losses",
                                          sensitive=True)
        self.assertIn("landmark_gates.never_presses_sensitive",
                      [f["lint"] for f in findings])

    def test_pressure_is_not_scored_outside_a_sensitive_domain(self):
        """The parent Conversation contract owns pressure in general; this
        lane adds only the narrower rule."""
        findings = li.lint_landmark_reply("Are you sure?", stage="ask",
                                          domain="residences", sensitive=False)
        self.assertNotIn("landmark_gates.never_presses_sensitive",
                         [f["lint"] for f in findings])

    def test_an_unknown_stage_fails_toward_the_strict_rule(self):
        findings = li.lint_landmark_reply("What year was that?", stage="nonsense",
                                          domain="residences")
        self.assertTrue(findings)


class AnchorTests(unittest.TestCase):
    """The whole point: `from_age` becomes reachable."""

    def test_the_birthday_becomes_the_birth_anchor(self):
        anchors = li.anchors_from_landmarks(
            {"birth": [{"date": _date("1978-04-12")}]}
        )
        self.assertIn("birth", anchors)
        self.assertEqual(anchors["birth"]["kind"], "birth")

    def test_a_residence_span_becomes_one_dated_interval(self):
        anchors = li.anchors_from_landmarks({"residences": [
            {"label": "Bell Avenue",
             "span": {"start": _date("1984"), "end": _date("1990")}},
        ]})
        row = anchors["residences-bell-avenue"]
        self.assertEqual(row["kind"], "residence")
        self.assertEqual(row["date"].earliest, "1984")
        self.assertEqual(row["date"].latest, "1990")

    def test_a_half_open_span_is_still_an_anchor(self):
        anchors = li.anchors_from_landmarks({"residences": [
            {"label": "the farm", "span": {"start": _date("1996")}},
        ]})
        self.assertEqual(anchors["residences-the-farm"]["date"].earliest, "1996")

    def test_an_undated_landmark_is_not_an_anchor(self):
        self.assertEqual(
            li.anchors_from_landmarks({"residences": [{"label": "Dayton",
                                                       "city": "Dayton"}]}),
            {},
        )

    def test_the_birthday_makes_from_age_work(self):
        """The defect this Interaction exists to fix (landmarks.md §3.7)."""
        anchors = li.anchors_from_landmarks(
            {"birth": [{"date": _date("1978-04-12")}]}
        )
        placed = chrono.from_age(anchors["birth"]["date"], "about 5")
        self.assertIsNotNone(placed)
        self.assertEqual(placed.basis, "age")
        self.assertLessEqual(int(placed.earliest), 1983)
        self.assertGreaterEqual(int(placed.latest), 1984)

    def test_anchors_for_person_reads_the_filed_set(self):
        import timeline_interaction as ti  # noqa: PLC0415

        rows = ti.anchors_for_person(landmarks={
            "birth": [{"date": _date("1978-04-12")}],
            "residences": [{"label": "Bell Avenue",
                            "span": {"start": _date("1984"),
                                     "end": _date("1990")}}],
        })
        self.assertEqual([r["key"] for r in rows],
                         ["birth", "residences-bell-avenue"])
        self.assertIn("1984", ti.render_anchors(rows))


class PlaceNoStoriesTests(unittest.TestCase):
    """The gap only a landmark set can reveal (owner ruling 4)."""

    LANDMARKS = {"residences": [
        {"label": "Bell Avenue",
         "span": {"start": _date("1984"), "end": _date("1990")}},
    ]}

    def test_a_dated_place_with_no_moments_is_a_gap(self):
        rows = li.places_without_stories(self.LANDMARKS, event_places=())
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["kind"], li.PLACE_NO_STORIES_KIND)
        self.assertIn("Bell Avenue", rows[0]["probe"]["text"])

    def test_a_place_with_moments_is_not_a_gap(self):
        self.assertEqual(
            li.places_without_stories(self.LANDMARKS,
                                      event_places=("Bell Avenue",)),
            (),
        )

    def test_an_undated_place_is_the_dating_gap_v196_already_asks(self):
        """`place_span` owns the WHEN; this kind owns only the WHAT."""
        self.assertEqual(
            li.places_without_stories({"residences": [{"label": "Dayton",
                                                       "city": "Dayton"}]}),
            (),
        )

    def test_the_kind_does_not_collide_with_the_existing_unknown_kinds(self):
        import timeline  # noqa: PLC0415

        self.assertNotIn(li.PLACE_NO_STORIES_KIND, timeline.UNKNOWN_KINDS)
        self.assertNotIn(li.PLACE_NO_STORIES_KIND, timeline.LEDGER_GAP_KINDS)


class StoreTests(unittest.TestCase):
    """The durable store, and the birth date that finally has a source."""

    def test_a_landmark_round_trips(self):
        import timeline  # noqa: PLC0415

        tmp = root_parent_tmp(self, ROOT)
        store = tmp / "landmarks.json"
        with mock.patch.object(timeline, "LANDMARKS_STORE", store):
            timeline.save_landmark("residences", {
                "domain": "residences", "label": "Bell Avenue",
                "city": "Dayton",
            })
            self.assertEqual(
                timeline.load_landmarks()["residences"][0]["city"], "Dayton"
            )

    def test_a_later_rung_merges_into_the_same_entry(self):
        """The ladder revisits the same subject; it must not fork it."""
        import timeline  # noqa: PLC0415

        tmp = root_parent_tmp(self, ROOT)
        store = tmp / "landmarks.json"
        with mock.patch.object(timeline, "LANDMARKS_STORE", store):
            timeline.save_landmark("residences", {"label": "Bell Avenue",
                                                  "city": "Dayton"})
            timeline.save_landmark("residences", {"label": "Bell Avenue",
                                                  "address": "11 Bell Ave"})
            entries = timeline.load_landmarks()["residences"]
            self.assertEqual(len(entries), 1)
            self.assertEqual(entries[0]["city"], "Dayton")
            self.assertEqual(entries[0]["address"], "11 Bell Ave")

    def test_a_broken_store_degrades_to_empty(self):
        import timeline  # noqa: PLC0415

        tmp = root_parent_tmp(self, ROOT)
        store = tmp / "landmarks.json"
        store.write_text("[]", encoding="utf-8")
        with mock.patch.object(timeline, "LANDMARKS_STORE", store):
            self.assertEqual(timeline.load_landmarks(), {})

    def test_the_birth_date_has_a_source(self):
        import timeline  # noqa: PLC0415

        self.assertEqual(
            chrono.to_edtf(timeline.landmark_birth_date(
                {"birth": [{"date": _date("1978-04-12")}]}
            )),
            "1978-04-12",
        )


class FilingTests(unittest.TestCase):
    def test_the_invocation_names_the_write_verb(self):
        argv = li.landmark_invocation({
            "domain": "residences", "label": "Bell Avenue",
            "span": {"start": _date("1984"), "end": _date("1990")},
        })
        self.assertEqual(argv[:2], ["landmark-record", "residences"])
        self.assertIn("--start", argv)
        self.assertIn("1984", argv)

    def test_every_flag_the_invocation_emits_is_a_real_cli_flag(self):
        """One writer, and the package never names a flag the CLI refuses."""
        import lifehug  # noqa: PLC0415

        parser = lifehug.build_parser()
        argv = li.landmark_invocation({
            "domain": "residences", "label": "Bell Avenue", "city": "Dayton",
            "address": "11 Bell Ave", "chain_complete": True,
            "span": {"start": _date("1984"), "end": _date("1990")},
        })
        args = parser.parse_args(argv)
        self.assertEqual(args.domain, "residences")
        self.assertEqual(args.city, "Dayton")
        self.assertTrue(args.complete)

    def test_a_skip_files_nothing(self):
        self.assertIsNone(li.landmark_invocation({"domain": "work",
                                                  "skipped": True}))


class EvalsTests(unittest.TestCase):
    def test_the_recorded_seat_passes(self):
        fixtures = landmarks_evals.load_fixtures()
        self.assertEqual(landmarks_evals.validate_fixtures(fixtures), [])
        scores = landmarks_evals.score_goldens(
            fixtures, landmarks_evals.load_sample_predictions()
        )
        self.assertEqual(
            landmarks_evals.check_gates(scores, landmarks_evals.load_gates()), []
        )
        self.assertEqual(scores["_landmark_accuracy"], 1.0)
        self.assertEqual(scores["_unmatched_fixtures"], [])

    def test_every_lint_class_is_gated(self):
        gates = set(landmarks_evals.load_gates())
        for name in li.LANDMARK_LINT_CLASSES:
            self.assertIn(f"{name.split('.', 1)[1]}.compliance", gates)


class PlanTests(unittest.TestCase):
    def test_the_plan_offers_only_open_rows(self):
        plan = li.build_landmarks_plan(
            {"birth": [{"year": "1978", "month": "04", "day": "12",
                        "date": _date("1978-04-12")}]}
        )
        self.assertEqual(plan["complete"], 1)
        self.assertNotIn("birth", [i["domain"] for i in plan["items"]])
        self.assertTrue(all(i["text"] for i in plan["items"]))

    def test_the_description_stars_the_keystone(self):
        plan = li.build_landmarks_plan({}, keystone_domains=("schools",))
        self.assertTrue(any(line.startswith("★") for line
                            in li.describe_landmarks_plan(plan)))


if __name__ == "__main__":
    unittest.main()


class KeystoneStarTests(unittest.TestCase):
    """Owner ruling 5: the ★ moves with the leverage."""

    def test_no_birth_date_stars_the_axis(self):
        import timeline  # noqa: PLC0415

        rows = timeline.landmark_rows_for({}, landmarks={})
        starred = [r["domain"] for r in rows if r["keystone"]]
        self.assertEqual(starred, ["birth"])

    def test_a_period_keystone_stars_the_residence_chain(self):
        import timeline  # noqa: PLC0415

        rows = timeline.landmark_rows_for(
            {"keystones": [{"anchor": "period:mesa", "leverage": 9}]},
            landmarks={"birth": [{"date": _date("1978-04-12")}]},
        )
        starred = [r["domain"] for r in rows if r["keystone"]]
        self.assertEqual(starred, ["residences"])

    def test_an_unrelated_keystone_stars_nothing(self):
        import timeline  # noqa: PLC0415

        rows = timeline.landmark_rows_for(
            {"keystones": [{"anchor": "event:mesa:src", "leverage": 3}]},
            landmarks={"birth": [{"date": _date("1978-04-12")}]},
        )
        self.assertEqual([r["domain"] for r in rows if r["keystone"]], [])


class GreedyKeystoneTests(unittest.TestCase):
    """go-deep.md §8.2/§8.3: the plan is greedy over the RESIDUAL graph.

    The defect this replaces, reproduced from the real-vault analysis: two
    anchors where one's resolve set is a strict subset of the other's. Ranked
    independently by leverage they are the top two, and the second star's
    marginal gain is ZERO — two questions that place what one question places.
    """

    DATA = {
        "periods": [{"slug": "childhood", "name": "Childhood"},
                    {"slug": "mesa", "name": "Mesa"}],
        "entity_lineup": {},
        "event_lineup": {},
        "anchors": {},
    }

    def _keystones(self, index):
        import timeline  # noqa: PLC0415

        with mock.patch.object(timeline, "dependency_index",
                               lambda _data: index):
            return timeline.keystones(self.DATA, n=2)

    def test_a_subset_anchor_is_never_starred(self):
        rows = self._keystones({
            "period:childhood": {"a", "b", "c", "d"},
            "period:mesa": {"a", "b"},
        })
        self.assertEqual([r["anchor"] for r in rows], ["period:childhood"])
        self.assertEqual(rows[0]["gain"], 4)
        self.assertEqual(rows[0]["leverage"], 4)

    def test_the_second_star_is_chosen_for_marginal_gain(self):
        """Leverage would pick `mesa` (3) over `farm` (2); the residual graph
        picks `farm`, because `mesa` adds only one thing `childhood` misses."""
        rows = self._keystones({
            "period:childhood": {"a", "b", "c", "d"},
            "period:mesa": {"a", "b", "e"},
            "period:farm": {"f", "g"},
        })
        self.assertEqual([r["anchor"] for r in rows],
                         ["period:childhood", "period:farm"])
        self.assertEqual([r["gain"] for r in rows], [4, 2])

    def test_leverage_is_still_the_number_shown(self):
        """The person is told the total, not the marginal — "one answer would
        place N things" is about that answer, not about the plan."""
        rows = self._keystones({
            "period:childhood": {"a", "b", "c"},
            "period:mesa": {"c", "d"},
        })
        mesa = next(r for r in rows if r["anchor"] == "period:mesa")
        self.assertEqual(mesa["leverage"], 2)
        self.assertEqual(mesa["gain"], 1)

    def test_a_shorter_plan_is_the_honest_one(self):
        """When nothing left adds anything, the plan stops — it is never padded
        to the cap."""
        rows = self._keystones({
            "period:childhood": {"a", "b"},
            "period:mesa": {"a"},
            "period:farm": {"b"},
        })
        self.assertEqual(len(rows), 1)

    def test_ties_break_on_the_cheaper_probe(self):
        rows = self._keystones({
            "period:childhood": {"a", "b"},
            "period:mesa": {"c", "d"},
        })
        self.assertEqual(len(rows), 2)
        costs = [r["probe"].get("cost", 99) for r in rows]
        self.assertEqual(costs, sorted(costs))


class NeverProposesADateTests(unittest.TestCase):
    """go-deep.md §4.3 (Lindsay et al. 2004): one definition, two lanes.

    True photographs plus suggestive interviewing produced false memories in
    about two thirds of participants. A dating probe backed by the person's
    own evidence is that configuration, so nothing may name a date and ask for
    agreement.
    """

    PROPOSALS = (
        "Was it 1984?",
        "Shall we say around 1986?",
        "Can I put it down as 1990?",
        "Does 1986 sound right?",
        "Let's say 1979 then.",
    )
    ALLOWED = (
        "You were twelve then, so that puts it around 1986.",
        "So anything at the Bell house lands between '84 and '90 now.",
        "Where were you living when that happened?",
    )

    def test_the_definition_lives_in_one_place(self):
        import timeline_interaction as ti  # noqa: PLC0415

        for text in self.PROPOSALS:
            with self.subTest(text=text):
                self.assertIsNotNone(ti.proposes_a_date(text))
        for text in self.ALLOWED:
            with self.subTest(text=text):
                self.assertIsNone(ti.proposes_a_date(text))

    def test_reporting_the_arithmetic_is_not_proposing(self):
        """The line the research draws: a derivation states its working; a
        proposal asks for a yes."""
        for text in self.ALLOWED:
            with self.subTest(text=text):
                self.assertNotIn(
                    "landmark_gates.never_proposes_a_date",
                    [f["lint"] for f in li.lint_landmark_reply(
                        text, stage="ask", domain="residences")],
                )

    def test_the_landmarks_lane_runs_it(self):
        findings = li.lint_landmark_reply("Was it 1984?", stage="ask",
                                          domain="residences")
        self.assertIn("landmark_gates.never_proposes_a_date",
                      [f["lint"] for f in findings])

    def test_the_timeline_lane_runs_it(self):
        import timeline_interaction as ti  # noqa: PLC0415

        findings = ti.lint_timeline_reply("Was it 1984?", stage="place",
                                          probe_step="bounds",
                                          known_years=("1984",))
        self.assertIn("timeline_gates.never_proposes_a_date",
                      [f["lint"] for f in findings])

    def test_even_the_birthday_may_not_be_proposed(self):
        """`no_year_demand` carves out `birth`; this rule does not."""
        findings = li.lint_landmark_reply("Was it 1978?", stage="ask",
                                          domain="birth")
        self.assertIn("landmark_gates.never_proposes_a_date",
                      [f["lint"] for f in findings])

    def test_both_lanes_gate_the_class(self):
        import timeline_evals  # noqa: PLC0415

        self.assertIn("never_proposes_a_date.compliance",
                      landmarks_evals.load_gates())
        self.assertIn("never_proposes_a_date.compliance",
                      timeline_evals.load_gates())


class WitnessTests(unittest.TestCase):
    """go-deep.md §7: a witness is someone living who was there.

    No new state — the residence ladder's own `household` rung already holds
    them, and a place with no stories carries them because the people who were
    in the house are exactly the people who can answer about it.
    """

    def test_a_place_with_no_stories_carries_its_witnesses(self):
        rows = li.places_without_stories({"residences": [{
            "label": "Bell Avenue",
            "household": "Mom and my brother Jim",
            "span": {"start": _date("1984"), "end": _date("1990")},
        }]})
        self.assertEqual(rows[0]["witnesses"], "Mom and my brother Jim")

    def test_no_household_means_no_witness_not_an_error(self):
        rows = li.places_without_stories({"residences": [{
            "label": "Bell Avenue",
            "span": {"start": _date("1984"), "end": _date("1990")},
        }]})
        self.assertIsNone(rows[0]["witnesses"])

    def test_household_is_a_real_rung_so_no_new_state_is_needed(self):
        self.assertIn("household", li.domain_row("residences")["ladder"])


class TimelineStaysUpTests(unittest.TestCase):
    """A landmark problem must never take the timeline down.

    The same discipline v196 applies to the keystone read. Found the honest
    way: the external data-only vault subprocess test failed its compile
    because `timeline_data()` now reads a store and a question set that a
    minimal vault need not have.
    """

    def test_a_broken_question_set_does_not_break_timeline_data(self):
        import timeline  # noqa: PLC0415

        def boom(*_args, **_kwargs):
            raise li.LandmarkInteractionError("questions.yaml is missing")

        with mock.patch.object(li, "load_questions", boom):
            data = timeline.timeline_data()
        self.assertEqual(data["landmarks"], [])
        self.assertEqual(data["place_no_stories"], [])
        self.assertEqual(data["counts"]["landmarks_open"], 0)
        self.assertIn("periods", data)

    def test_a_broken_store_degrades_to_nothing_filed(self):
        """Not to an empty ledger — to a ledger that says nothing is filed,
        which is the truth the person can act on."""
        import timeline  # noqa: PLC0415

        def boom(*_args, **_kwargs):
            raise OSError("unreadable")

        with mock.patch.object(timeline, "load_landmarks", boom):
            data = timeline.timeline_data()
        self.assertIn("anchors", data)
        self.assertTrue(data["landmarks"])
        self.assertTrue(all(row["status"] == "open" for row in data["landmarks"]))
        self.assertEqual(data["place_no_stories"], [])


class DateGrainRungTests(unittest.TestCase):
    """lifehug#207: a DateRecord satisfies the date-grain rungs it resolves.

    `rung_reached` counted a rung only under that rung's own key, with a single
    `date` fallback for `span`. But the package's own CLI and turn writers
    produce ONE `date` record and no per-grain keys, so a day-precision
    birthday left `birth` `partial` with `next = year` forever — found live on
    the platform (lifehug-platform#613, which ships a read-side normalizer as a
    stopgap; remove it at the pin that carries this).
    """

    def test_a_day_precision_birthday_completes_the_birth_ladder(self):
        row = li.domain_row("birth")
        entry = {"date": _date("1978-04-12")}
        self.assertEqual(li.rung_reached(entry, row), "day")
        self.assertEqual(li.status_for_domain([entry], row), "complete")

    def test_a_year_only_date_stops_at_year(self):
        row = li.domain_row("birth")
        self.assertEqual(li.rung_reached({"date": _date("1978")}, row), "year")
        self.assertEqual(li.next_rung([{"date": _date("1978")}], row)["rung"], "month")

    def test_a_coarse_date_is_an_answer_that_claims_no_month(self):
        row = li.domain_row("birth")
        self.assertIsNone(li.rung_reached({"date": _date("1978/1982")}, row))

    def test_the_same_fix_reaches_children_and_partnerships(self):
        for domain in ("children", "partnerships"):
            with self.subTest(domain=domain):
                row = li.domain_row(domain)
                entry = {"label": "Ana", "happened": "yes", "who": "Ana",
                         "date": _date("2004-06")}
                self.assertEqual(li.rung_reached(entry, row), "month")

    def test_an_explicit_rung_key_still_wins(self):
        """The fallback only fires when the rung has no key of its own."""
        row = li.domain_row("birth")
        self.assertEqual(
            li.rung_reached({"year": "1978", "date": _date("1978-04-12")}, row),
            "day")
