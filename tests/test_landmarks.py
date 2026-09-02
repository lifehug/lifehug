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
import landmark_projection as lp  # noqa: E402
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

    def test_the_closed_lists_lead_and_are_chains(self):
        """landmarks.md §2.7 + §2.9: the THREE closed lists come first.

        v202 inserts `family` at 2 — where practitioner intake puts it
        (Montana's data sheet; ND VHP Segment 1 items 3-4), and because it is a
        third closed list: enumerable, finite, ordered, finishable.
        """
        order = [r["domain"] for r in self.rows]
        self.assertEqual(order[0], "birth", "the axis is first")
        self.assertEqual(order[1:4], ["family", "residences", "schools"])
        for domain in ("family", "residences", "schools"):
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
                         ("birth", "family", "residences", "schools",
                          "partnerships", "children"))

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
        # v255: a day-precise birthday now yields a day-precise calendar
        # span rather than a year-only one — the old bare-year assertions
        # (`earliest <= 1983`, `latest >= 1984`) can no longer `int()` the
        # bound, so the exact calendar span is asserted directly instead.
        self.assertEqual(placed.earliest, "1982-04-12")
        self.assertEqual(placed.latest, "1985-04-11")

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


# ---------------------------------------------------------------------------
# v202 — the Family landmark (contract: docs/pr-specs/family-landmark.md)
# ---------------------------------------------------------------------------


def _family(label, relation, *, year=None, living=None, **extra):
    entry = {"domain": "family", "label": label, "who": label,
             "relation": relation, **extra}
    if year is not None:
        entry["date"] = _date(year)
    if living is not None:
        entry["living"] = living
    return entry


class FamilyDomainTests(unittest.TestCase):
    """The ninth domain: siblings as anchors, elders as witnesses (§B)."""

    def setUp(self) -> None:
        self.row = li.domain_row("family")

    def test_family_is_second_a_chain_and_at_onboarding(self):
        self.assertEqual(self.row["order"], 2)
        self.assertTrue(self.row["chain"])
        self.assertTrue(self.row["onboarding"])
        self.assertFalse(self.row["sensitive"])
        self.assertEqual(self.row["ladder"], ("who", "relation", "birth", "living"))
        self.assertEqual(self.row["complete_at"], "birth")

    def test_living_sits_past_the_completion_target(self):
        """Exactly like residences' `household`: recorded when stated, never
        demanded, and UNKNOWN unless stated."""
        ladder = list(self.row["ladder"])
        self.assertGreater(ladder.index("living"),
                           ladder.index(self.row["complete_at"]))

    def test_a_name_alone_sits_at_the_first_rung(self):
        self.assertEqual(li.rung_reached({"label": "Jackie", "who": "Jackie"},
                                         self.row), "who")

    def test_the_ladder_climbs_to_the_birth_year(self):
        entry = _family("James", "sibling", year="1976")
        self.assertEqual(li.rung_reached(entry, self.row), "birth")

    def test_the_next_question_NAMES_the_incomplete_person(self):
        """Owner ruling 4: never a generic re-ask."""
        entries = [_family("James", "sibling", year="1976"),
                   _family("Jackie", "sibling")]
        question = li.next_rung(entries, self.row)
        self.assertEqual(question["rung"], "birth")
        self.assertEqual(question["subject"], "Jackie")
        self.assertEqual(question["text"], "What year was Jackie born?")

    def test_the_chain_walks_the_tiers_siblings_parents_grandparents(self):
        entries = []
        self.assertEqual(li.family_next_tier(entries), "sibling")
        entries.append(_family("James", "sibling", year="1976"))
        self.assertEqual(li.family_next_tier(entries), "parent")
        entries.append(_family("Desi", "parent", year="1950"))
        self.assertEqual(li.family_next_tier(entries), "grandparent")
        entries.append(_family("Betty Jo", "grandparent", year="1921"))
        self.assertIsNone(li.family_next_tier(entries))

    def test_the_chain_more_question_asks_for_the_MISSING_tier(self):
        entries = [_family("James", "sibling", year="1976")]
        question = li.next_rung(entries, self.row)
        self.assertEqual(question["text"], li.FAMILY_TIER_TEXTS["parent"])
        self.assertIn("parents", question["text"])

    def test_the_family_opener_is_priced_like_every_other_opener(self):
        """Otherwise the row sorts behind the residence chain and the reason
        the domain exists is inverted (§A.1)."""
        self.assertEqual(li.next_rung([], self.row)["cost"], 1)
        rows = li.landmark_rows({})
        self.assertEqual(li.open_landmarks(rows)[0]["domain"], "birth",
                         "with no birthday the axis is starred and leads")
        unstarred = li.open_landmarks([r for r in rows if r["domain"] != "birth"])
        self.assertEqual(unstarred[0]["domain"], "family")

    def test_a_direct_year_question_is_permitted_for_a_sibling(self):
        """landmarks.md §2.9: the carve-out is about the KIND of fact."""
        text = "What year was Jackie born?"
        self.assertEqual(li.lint_landmark_reply(text, stage="ask", domain="family"), [])
        self.assertEqual(li.lint_landmark_reply(text, stage="ask", domain="children"), [])
        findings = li.lint_landmark_reply(text, stage="ask", domain="residences")
        self.assertEqual([f["lint"] for f in findings],
                         ["landmark_gates.no_year_demand"])

    def test_the_carve_out_is_ONE_named_set_read_by_the_harness_too(self):
        self.assertEqual(li.YEAR_OPENER_DOMAINS,
                         frozenset({"birth", "family", "children"}))
        for domain in li.YEAR_OPENER_DOMAINS:
            self.assertNotIn("no_year_demand",
                             landmarks_evals._applicable(domain, False))  # noqa: SLF001

    def test_every_domains_own_rung_text_survives_its_own_lints(self):
        """The defect this contract stops patching one at a time: a domain
        whose own question trips its own lint is a contradiction, not a
        subtlety (v199 shipped three)."""
        for (domain, _rung), text in li.RUNG_TEXTS.items():
            rendered = text.format(label="Jackie")
            with self.subTest(domain=domain, text=rendered):
                self.assertEqual(
                    li.lint_landmark_reply(
                        rendered, stage="ask", domain=domain,
                        sensitive=li.domain_row(domain)["sensitive"]),
                    [])

    def test_living_is_TRI_STATE_through_both_validation_layers(self):
        for value, expected in ((True, True), (False, False)):
            record = engine._parse_landmark(  # noqa: SLF001
                {"domain": "family", "label": "Betty Jo", "living": value})
            self.assertEqual(li.validate_landmark(record)["living"], expected)
        record = engine._parse_landmark(  # noqa: SLF001
            {"domain": "family", "label": "Betty Jo"})
        self.assertNotIn("living", li.validate_landmark(record))

    def test_birth_order_is_a_field_and_never_blocks_the_ladder(self):
        entry = _family("James", "sibling", year="1976",
                        birth_order="two years older")
        self.assertEqual(li.rung_reached(entry, self.row), "birth")
        self.assertNotIn("birth_order", self.row["ladder"])
        argv = li.landmark_invocation(entry)
        self.assertEqual(argv[argv.index("--birth-order") + 1], "two years older")

    def test_the_invocation_emits_the_living_bool_as_a_flag_pair(self):
        self.assertIn("--living",
                      li.landmark_invocation(_family("Desi", "parent", living=True)))
        self.assertIn("--not-living",
                      li.landmark_invocation(_family("Betty Jo", "grandparent",
                                                     living=False)))
        self.assertNotIn("--living",
                         li.landmark_invocation(_family("Desi", "parent")))

    def test_every_flag_the_family_invocation_emits_is_a_real_cli_flag(self):
        """One writer, and the package never names a flag the CLI refuses."""
        import lifehug  # noqa: PLC0415

        parser = lifehug.build_parser()
        args = parser.parse_args(li.landmark_invocation(
            _family("James", "sibling", year="1976",
                    birth_order="two years older", living=True)))
        self.assertEqual(args.domain, "family")
        self.assertEqual(args.relation, "sibling")
        self.assertEqual(args.birth_order, "two years older")
        self.assertTrue(args.living)
        args = parser.parse_args(li.landmark_invocation(
            _family("Betty Jo", "grandparent", living=False)))
        self.assertIs(args.living, False)

    def test_the_cli_round_trips_a_family_record_through_validation(self):
        import lifehug  # noqa: PLC0415

        parser = lifehug.build_parser()
        args = parser.parse_args(li.landmark_invocation(
            _family("Betty Jo", "grandparent", living=False)))
        record = {"domain": args.domain, "label": args.label, "who": args.who,
                  "relation": args.relation, "living": args.living}
        self.assertIs(li.validate_landmark(record)["living"], False)


class FamilyAnchorTests(unittest.TestCase):
    """§C: the join between a filed relative and the derived anchor index."""

    def test_a_sibling_birth_year_becomes_a_relation_qualified_anchor(self):
        anchors = li.anchors_from_landmarks(
            {"family": [_family("James", "sibling", year="1976")]})
        self.assertEqual(list(anchors), ["family:sibling-james:birth"])
        row = anchors["family:sibling-james:birth"]
        self.assertEqual(row["kind"], "landmark")
        self.assertEqual(row["label"], "James was born")

    def test_the_key_uses_the_CLOSED_relationship_word_not_the_spoken_one(self):
        """Deviation 2: `sibling`, never `brother` — one vocabulary."""
        key = next(iter(li.anchors_from_landmarks(
            {"family": [_family("James", "sibling", year="1976")]})))
        self.assertIn("sibling", key)
        self.assertNotIn("brother", key)

    def test_two_relatives_with_the_same_name_do_not_collide(self):
        anchors = li.anchors_from_landmarks({"family": [
            _family("James", "sibling", year="1976"),
            _family("James", "grandparent", year="1911"),
        ]})
        self.assertEqual(len(anchors), 2)

    def test_an_undated_relative_mints_no_anchor(self):
        self.assertEqual(
            li.anchors_from_landmarks({"family": [_family("Jackie", "sibling")]}), {})

    def test_the_family_anchor_reaches_the_timeline_index_like_any_other(self):
        import timeline  # noqa: PLC0415

        anchors = timeline.anchor_index(
            [], [], [], landmarks=li.anchors_from_landmarks(
                {"family": [_family("James", "sibling", year="1976")]}))
        self.assertIn("family:sibling-james:birth", anchors)


class FamilyRosterJoinTests(unittest.TestCase):
    """§D: the people go to the ROSTER; there is no parallel family store."""

    LANDMARKS = {"family": [
        _family("James", "sibling", year="1976", living=True),
        _family("Betty Jo", "grandparent", living=False),
        _family("Nobody", ""),
    ]}

    def _empty_roster(self):
        """A throwaway roster file, and every module that names one pointed at
        it. Synthetic only — nothing here ever touches a real vault."""
        import entity_roster  # noqa: PLC0415
        import entity_verdict  # noqa: PLC0415

        tmp = root_parent_tmp(self, ROOT)
        path = tmp / "person.json"
        path.write_text(json.dumps(
            {"version": 1, "type": "person", "entities": []}), encoding="utf-8")
        for module in (entity_roster, entity_verdict):
            patcher = mock.patch.object(module, "roster_file", lambda _t, p=path: p)
            patcher.start()
            self.addCleanup(patcher.stop)
        return path

    def test_the_relation_vocabulary_is_the_rosters_own(self):
        import focus_candidate  # noqa: PLC0415

        self.assertTrue(li.FAMILY_RELATIONS <= set(focus_candidate.FOCUS_RELATIONSHIPS))

    def test_the_invocations_name_the_existing_roster_verb(self):
        argvs = li.family_roster_invocations(self.LANDMARKS)
        self.assertEqual(len(argvs), 2, "a member with no relation is skipped")
        self.assertEqual(argvs[0][:4], ["entity-verdict", "person", "james", "clear"])
        self.assertIn("--relationship", argvs[0])
        self.assertIn("--living", argvs[0])
        self.assertIn("--not-living", argvs[1])
        for argv in argvs:
            self.assertIn("--ensure", argv)
            self.assertNotIn("graduate", argv)

    def test_every_flag_the_roster_invocation_emits_is_a_real_cli_flag(self):
        """The package never names a flag `lifehug.py entity-verdict` refuses."""
        import lifehug  # noqa: PLC0415

        parser = lifehug.build_parser()
        for argv in li.family_roster_invocations(self.LANDMARKS):
            with self.subTest(slug=argv[2]):
                args = parser.parse_args(argv)
                self.assertEqual(args.type, "person")
                self.assertEqual(args.verdict, "clear")
                self.assertTrue(args.ensure)
                self.assertTrue(args.name)
                self.assertIn(args.relationship, li.FAMILY_RELATIONS)

    def test_ensure_creates_a_row_that_is_never_page_eligible(self):
        """ADR 0013's >=1-mention floor: an identity fact is not a page."""
        import entity_roster  # noqa: PLC0415
        import entity_verdict  # noqa: PLC0415

        path = self._empty_roster()
        entry = entity_verdict.apply_verdict(
            "person", "james", "clear", relationship="sibling",
            living=True, ensure=True, name="James")
        self.assertFalse(entry["page_eligible"])
        self.assertFalse(entry["qualifies"])
        self.assertEqual(entry["relationship"], "sibling")
        self.assertTrue(entry["living"])
        self.assertTrue(entity_roster._has_settled_identity(entry))  # noqa: SLF001
        self.assertIn("james", path.read_text(encoding="utf-8"))

    def test_ensure_is_idempotent(self):
        import entity_verdict  # noqa: PLC0415

        path = self._empty_roster()
        for _ in range(2):
            entity_verdict.apply_verdict(
                "person", "james", "clear", relationship="sibling",
                ensure=True, name="James")
        data = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(len(data["entities"]), 1)

    def test_without_ensure_an_unknown_slug_is_still_refused(self):
        import entity_verdict  # noqa: PLC0415

        self._empty_roster()
        with self.assertRaises(entity_verdict.EntityVerdictError):
            entity_verdict.apply_verdict("person", "james", "clear",
                                         relationship="sibling")


class WitnessTests(unittest.TestCase):
    """§D: a witness is a LIVING person who was there — explicitly living."""

    def test_only_an_explicit_living_true_is_a_witness(self):
        rows = li.witness_candidates({"family": [
            _family("Desi", "parent", living=True),
            _family("Betty Jo", "grandparent", living=False),
            _family("Jackie", "sibling"),
        ]})
        self.assertEqual([row["name"] for row in rows], ["Desi"])
        self.assertEqual(rows[0]["can_supply"], ("residences", "schools"))

    def test_the_residence_household_witnesses_are_left_alone(self):
        """v200's narrower, better claim about ONE house is untouched."""
        rows = li.places_without_stories({"residences": [{
            "label": "Bell Avenue", "household": "Mom and James",
            "span": {"start": _date("1984"), "end": _date("1990")}}]})
        self.assertEqual(rows[0]["witnesses"], "Mom and James")


class ConcreteLandmarkUnknownTests(unittest.TestCase):
    """Owner rulings 4 and 5: unknowns are concrete, and they have names."""

    LANDMARKS = {
        "family": [_family("James", "sibling", year="1976"),
                   _family("Jackie", "sibling")],
        "residences": [
            {"label": "Mesa", "city": "Mesa", "address": "1 Mesa Rd",
             "span": {"start": _date("1988"), "end": _date("1992")}},
            {"label": "Yucaipa", "city": "Yucaipa",
             "span": {"start": _date("1995"), "end": _date("2001")}},
        ],
    }

    def test_each_incomplete_subject_is_its_own_named_unknown(self):
        by_label = {row["label"]: row
                    for row in li.incomplete_subjects(self.LANDMARKS)}
        self.assertIn("Jackie", by_label)
        self.assertNotIn("James", by_label, "a complete subject asks nothing")
        self.assertEqual(by_label["Jackie"]["kind"], "landmark_subject")
        self.assertEqual(by_label["Jackie"]["probe"]["text"],
                         "What year was Jackie born?")
        self.assertEqual(by_label["Jackie"]["landmark"],
                         {"domain": "family", "label": "Jackie"})

    def test_a_named_residence_without_a_span_asks_by_name_too(self):
        by_label = {row["label"]: row
                    for row in li.incomplete_subjects(self.LANDMARKS)}
        self.assertIn("Yucaipa", by_label)
        self.assertIn("Yucaipa", by_label["Yucaipa"]["probe"]["text"])

    def test_the_subject_probe_IS_the_ladders_own_next_question(self):
        """One definition — the row's `next` and the unknown cannot disagree."""
        for row in li.incomplete_subjects(self.LANDMARKS):
            question = li.next_rung(
                [e for e in self.LANDMARKS[row["domain"]]
                 if e.get("label") == row["label"]],
                li.domain_row(row["domain"]))
            self.assertEqual(row["probe"]["text"], question["text"])

    def test_enumeration_means_chain_true_not_a_hand_written_list(self):
        chains = {row["domain"] for row in li.load_questions() if row["chain"]}
        self.assertEqual(chains, {"family", "residences", "schools", "work"})

    def test_a_hole_between_two_residences_becomes_a_named_question(self):
        rows = li.residence_gaps(self.LANDMARKS)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["kind"], "residence_gap")
        self.assertEqual(rows[0]["between"], ["Mesa", "Yucaipa"])
        self.assertEqual(rows[0]["years"], ["1992", "1995"])
        self.assertEqual(
            rows[0]["probe"]["text"],
            "Where did you live between Mesa and Yucaipa, around 1992–1995?")

    def test_abutting_and_consecutive_spans_are_not_holes(self):
        for end, start in (("1992", "1992"), ("1992", "1993"), ("1995", "1992")):
            with self.subTest(end=end, start=start):
                self.assertEqual(li.residence_gaps({"residences": [
                    {"label": "A",
                     "span": {"start": _date("1988"), "end": _date(end)}},
                    {"label": "B",
                     "span": {"start": _date(start), "end": _date("2001")}},
                ]}), ())

    def test_no_gap_is_minted_before_the_first_or_after_the_last(self):
        self.assertEqual(li.residence_gaps({"residences": [
            {"label": "Only",
             "span": {"start": _date("1988"), "end": _date("1992")}}]}), ())

    def test_the_gap_question_reports_and_never_asks_for_agreement(self):
        import timeline_interaction as ti  # noqa: PLC0415

        for row in li.residence_gaps(self.LANDMARKS):
            self.assertIsNone(ti.proposes_a_date(row["probe"]["text"]))
            self.assertEqual(
                li.lint_landmark_reply(row["probe"]["text"], stage="ask",
                                       domain="residences"), [])

    def test_both_kinds_reach_the_timelines_unknowns_with_their_own_probe(self):
        import timeline  # noqa: PLC0415

        by_key = {row["key"]: row
                  for row in timeline.unknowns({}, landmarks=self.LANDMARKS)}
        self.assertEqual(by_key["landmark_subject:family:jackie"]["probe"]["text"],
                         "What year was Jackie born?")
        self.assertIn("Mesa", by_key["residence_gap:mesa:yucaipa"]["probe"]["text"])

    def test_the_new_kinds_are_declared_and_keyed(self):
        import timeline  # noqa: PLC0415

        self.assertIn("landmark_subject", timeline.UNKNOWN_KINDS)
        self.assertIn("residence_gap", timeline.UNKNOWN_KINDS)
        for row in (li.incomplete_subjects(self.LANDMARKS)
                    + li.residence_gaps(self.LANDMARKS)):
            self.assertEqual(timeline.unknown_key(row), row["key"])

    def test_a_broken_store_never_takes_the_unknowns_down(self):
        import timeline  # noqa: PLC0415

        self.assertIsInstance(timeline.unknowns({}, landmarks="not a store"), list)


class NoneTerminalTests(unittest.TestCase):
    """v203 / owner ruling 6 — a life with none of a thing can FINISH that
    domain.

    The live incident (staging, 2026-08-24): the founder Played the Military
    landmark, said plainly that he had never served, the message filed — and
    the Military row stayed in the open Landmarks list forever, because
    `military`'s ladder is happened → branch → span and there was no rung a
    "no" could ever reach. His reply is reproduced verbatim below because the
    shape of it is the point: a clear negative for the domain we asked about,
    with something adjacent volunteered in the same breath.
    """

    #: The founder's own words on staging, 2026-08-24 (synthetic ids only).
    LIVE_REPLY = (
        "I have not served in the military. It's not military service, but I "
        "did serve a two-year mission for my church as a Mormon missionary. I "
        "served that in Zurich, Switzerland, when I was 19."
    )

    def _validated(self, raw: dict) -> object:
        """Both layers, in the order a real caller runs them."""
        return li.validate_landmark(engine._parse_landmark(raw))  # noqa: SLF001

    def test_only_the_yes_no_domains_accept_a_none(self):
        """Derived from the set, not declared beside it: `happened` opens
        exactly the domains a person can close by saying it never happened."""
        self.assertEqual(li.none_domains(),
                         ("partnerships", "children", "military", "losses"))
        for domain in ("birth", "family", "residences", "schools", "work"):
            self.assertFalse(li.domain_accepts_none(li.domain_row(domain)),
                             f"{domain} opens at a THING, not a yes/no")

    def test_family_is_outside_the_terminal_by_derivation(self):
        """v202's ninth domain enumerates PEOPLE: its ladder opens at `who`,
        so the gate excludes it with no rule of its own. "No siblings" is not
        an empty family — there are still parents — and a chain finishes with
        `chain_complete`, which is a different fact from never having
        happened."""
        row = li.domain_row("family")
        self.assertEqual(row["ladder"][0], "who")
        self.assertTrue(row["chain"])
        self.assertFalse(li.domain_accepts_none(row))
        self.assertIsNone(self._validated({"domain": "family", "none": True}))
        # And a family entry that carries a none flag is still just an entry:
        # the flag is inert, the ladder is walked normally.
        entry = {"domain": "family", "none": True,
                 "label": "Jo", "who": "Jo", "relation": "sibling"}
        self.assertFalse(li.is_none_entry(entry, row))
        self.assertEqual(li.rung_reached(entry, row), "relation")

    def test_the_live_negative_answer_completes_the_domain(self):
        record = self._validated({"domain": "military", "none": True})
        self.assertEqual(record, {"domain": "military", "none": True})
        row = li.domain_row("military")
        self.assertEqual(li.rung_reached(record, row), "span")
        self.assertEqual(li.status_for_domain([record], row), "complete")
        self.assertIsNone(li.next_rung([record], row))

    def test_the_military_row_leaves_the_open_list(self):
        """The owner's ruling, stated as the assertion: an answered landmark
        leaves the list."""
        rows = li.landmark_rows({"military": [{"domain": "military",
                                               "none": True}]})
        military = next(r for r in rows if r["domain"] == "military")
        self.assertEqual(military["status"], "complete")
        self.assertNotIn("military",
                         [r["domain"] for r in li.open_landmarks(rows)])

    def test_a_person_with_no_partnerships_or_children_can_finish_those_too(self):
        for domain in ("partnerships", "children", "losses"):
            with self.subTest(domain=domain):
                record = self._validated({"domain": domain, "none": True})
                self.assertEqual(record, {"domain": domain, "none": True})
                row = li.domain_row(domain)
                self.assertEqual(li.status_for_domain([record], row), "complete")
                self.assertIsNone(li.next_rung([record], row))

    def test_a_none_on_a_thing_domain_is_dropped_not_honored(self):
        """`{"domain": "birth", "none": true}` would complete the axis with no
        date and take `chronology.from_age` down with it."""
        for domain in ("birth", "residences", "schools", "work"):
            with self.subTest(domain=domain):
                self.assertIsNone(self._validated({"domain": domain,
                                                   "none": True}))
        row = li.domain_row("birth")
        self.assertEqual(
            li.status_for_domain([{"domain": "birth", "none": True}], row),
            "partial",
        )

    def test_a_none_outranks_a_skip_and_is_not_one(self):
        """A skip is "not now" and files nothing; a none is "there is nothing
        here" and files, because it is the answer."""
        record = self._validated({"domain": "military", "none": True,
                                  "skipped": True})
        self.assertEqual(record, {"domain": "military", "none": True})
        self.assertEqual(li.landmark_invocation(record),
                         ["landmark-record", "military", "--none"])
        self.assertIsNone(li.landmark_invocation({"domain": "military",
                                                  "skipped": True}))

    def test_the_structural_layer_carries_the_flag(self):
        self.assertIn("none", engine._LANDMARK_KEYS)  # noqa: SLF001
        self.assertEqual(engine._parse_landmark({"domain": "military",  # noqa: SLF001
                                                 "none": True}),
                         {"domain": "military", "none": True})
        # A non-boolean flag is dropped, exactly as `skipped` is — and what
        # is left is a bare domain, which is not a landmark.
        self.assertEqual(engine._parse_landmark({"domain": "military",  # noqa: SLF001
                                                 "none": "yes"}),
                         {"domain": "military"})
        self.assertIsNone(self._validated({"domain": "military",
                                           "none": "yes"}))

    def test_the_turn_contract_tells_the_model_to_emit_it(self):
        shape = engine.TurnShape(position=1, question_allowed=True,
                                 user_turns=1, target_exchanges=4,
                                 landmark_stage="ask")
        block = engine._output_contract_block(shape)  # noqa: SLF001
        self.assertIn('"none": true | false', block)
        self.assertIn("I never served", block)
        leaf = (ROOT / "interactions" / "landmarks" / "prompt"
                / "turn-instructions.md").read_text(encoding="utf-8")
        self.assertIn('"none": true', leaf)

    def test_a_landmark_stageless_turn_is_untouched(self):
        """Passive users, and every non-landmark turn, see no new key."""
        shape = engine.TurnShape(position=1, question_allowed=True,
                                 user_turns=1, target_exchanges=4)
        self.assertNotIn("none", engine._output_contract_block(shape))  # noqa: SLF001

    def test_the_adjacent_story_is_not_filed_as_a_landmark(self):
        """He said "not the military, but I did serve a mission" in one
        breath. The mission is a story; it is not a military landmark, and it
        is not a domain of its own."""
        self.assertIsNone(self._validated({"domain": "mission", "none": True}))
        self.assertIsNone(self._validated({"domain": "military",
                                           "branch": ""}))
        self.assertIn("mission", self.LIVE_REPLY)


class HappenedIsEntailedTests(unittest.TestCase):
    """v203 — the ladder's first rung was unreachable in practice.

    Found in the same 2026-08-24 look: a person answered `children` fully —
    four names and a span — and the row still read `open`, because the model
    filled `label` and `span` and nothing ever filled `happened`. `happened`
    is not a fact anyone states separately; it is entailed by every other fact
    in the domain. Synthetic names throughout.
    """

    LIVE_SHAPE = {
        "domain": "children",
        "label": "Ada Vance, Roscoe Vance, Junie Vance, Wilbur Vance",
        "span": {"start": {"best": "2010-12-21", "earliest": "2010-12-21",
                           "latest": "2010-12-21", "granularity": "day",
                           "confidence": "certain", "basis": "stated"},
                 "end": {"best": "2021-10-11", "earliest": "2021-10-11",
                         "latest": "2021-10-11", "granularity": "day",
                         "confidence": "certain", "basis": "stated"}},
    }

    def test_a_full_answer_no_longer_lands_below_rung_one(self):
        """v203 got this entry to rung one; lifehug#219 gets it to rung two.

        The same live shape, one release later: `happened` is entailed by the
        label AND the label is a name list, so the entry now reaches `who` —
        the rung the names were always an answer to. Pinning `happened` here
        was pinning half the defect.
        """
        row = li.domain_row("children")
        self.assertTrue(li.asserts_happened(self.LIVE_SHAPE))
        self.assertEqual(li.rung_reached(self.LIVE_SHAPE, row), "who")
        self.assertEqual(li.identity_named(self.LIVE_SHAPE, row),
                         self.LIVE_SHAPE["label"])

    def test_bookkeeping_alone_does_not_assert_it(self):
        for entry in ({"domain": "children"},
                      {"domain": "children", "skipped": True},
                      {"domain": "children", "none": True},
                      {"domain": "children", "label": ""}):
            with self.subTest(entry=entry):
                self.assertFalse(li.asserts_happened(entry))

    def test_the_none_terminal_still_wins_over_the_entailment(self):
        """A none record carries nothing else, so the two never collide — and
        if one ever did, `none` is checked first."""
        row = li.domain_row("military")
        self.assertEqual(li.rung_reached({"domain": "military", "none": True},
                                         row), "span")

    def test_a_thing_domain_is_untouched(self):
        """`residences` opens at `city`; nothing is entailed there."""
        row = li.domain_row("residences")
        self.assertIsNone(li.rung_reached({"domain": "residences",
                                           "address": "11 Bell Ave"}, row))


class NoneSupersessionTests(unittest.TestCase):
    """"Actually I did serve, briefly" — the none record is superseded, not
    fought (owner ruling 6)."""

    def test_a_later_answer_clears_a_standing_none(self):
        """"Actually I did serve, briefly." The domain reopens at the rung the
        new answer reaches — it does not argue, and it does not fork."""
        merged = li.merge_landmark_entry({"domain": "military", "none": True},
                                         {"domain": "military",
                                          "happened": "yes",
                                          "branch": "the Army"})
        self.assertEqual(merged, {"domain": "military", "happened": "yes",
                                  "branch": "the Army"})
        row = li.domain_row("military")
        self.assertEqual(li.rung_reached(merged, row), "branch")
        self.assertEqual(li.status_for_domain([merged], row), "partial")
        self.assertEqual(li.next_rung([merged], row)["rung"], "span")
        rows = li.landmark_rows({"military": [merged]})
        self.assertIn("military",
                      [r["domain"] for r in li.open_landmarks(rows)])

    def test_a_none_replaces_whatever_was_there(self):
        merged = li.merge_landmark_entry({"domain": "military",
                                          "happened": "yes",
                                          "branch": "the Army"},
                                         {"domain": "military", "none": True})
        self.assertEqual(merged, {"domain": "military", "none": True})

    def test_the_ladder_still_merges_when_neither_side_is_a_none(self):
        merged = li.merge_landmark_entry({"domain": "residences",
                                          "label": "Bell Avenue",
                                          "city": "Dayton"},
                                         {"domain": "residences",
                                          "label": "Bell Avenue",
                                          "address": "11 Bell Ave"})
        self.assertEqual(merged["city"], "Dayton")
        self.assertEqual(merged["address"], "11 Bell Ave")

    def test_the_store_supersedes_in_both_directions(self):
        import timeline  # noqa: PLC0415

        tmp = root_parent_tmp(self, ROOT)
        store = tmp / "landmarks.json"
        with mock.patch.object(timeline, "LANDMARKS_STORE", store):
            timeline.save_landmark("military", {"domain": "military",
                                                "none": True})
            row = li.domain_row("military")
            entries = timeline.load_landmarks()["military"]
            self.assertEqual(li.status_for_domain(entries, row), "complete")

            timeline.save_landmark("military", {"domain": "military",
                                                "happened": "yes",
                                                "branch": "the Army"})
            entries = timeline.load_landmarks()["military"]
            self.assertEqual(len(entries), 1, "the reversal must not fork")
            self.assertNotIn("none", entries[0])
            self.assertEqual(li.status_for_domain(entries, row), "partial")

            timeline.save_landmark("military", {"domain": "military",
                                                "none": True})
            entries = timeline.load_landmarks()["military"]
            self.assertEqual(entries, [{"domain": "military", "none": True}])

    def test_a_none_domain_never_becomes_an_anchor(self):
        """It has no date, so there is nothing to anchor — and nothing must be
        invented for it."""
        index = li.anchors_from_landmarks({"military": [{"domain": "military",
                                                         "none": True}]})
        self.assertEqual(index, {})


class NoneCliTests(unittest.TestCase):
    """The one writer files it; a `--none` on a thing-domain is refused."""

    def _run(self, argv: list[str]) -> int:
        import lifehug  # noqa: PLC0415

        parser = lifehug.build_parser()
        args = parser.parse_args(argv)
        return args.func(args)

    def test_the_verb_files_a_none_and_completes_the_domain(self):
        import timeline  # noqa: PLC0415

        tmp = root_parent_tmp(self, ROOT)
        store = tmp / "landmarks.json"
        with mock.patch.object(timeline, "LANDMARKS_STORE", store):
            self.assertEqual(self._run(["landmark-record", "military",
                                        "--none"]), 0)
            entries = timeline.load_landmarks()["military"]
            self.assertEqual(entries, [{"domain": "military", "none": True}])
            self.assertEqual(
                li.status_for_domain(entries, li.domain_row("military")),
                "complete",
            )

    def test_the_verb_refuses_a_none_on_a_thing_domain(self):
        import timeline  # noqa: PLC0415

        tmp = root_parent_tmp(self, ROOT)
        store = tmp / "landmarks.json"
        with mock.patch.object(timeline, "LANDMARKS_STORE", store):
            self.assertEqual(self._run(["landmark-record", "birth",
                                        "--none"]), 1)
            self.assertFalse(store.exists())


# ---------------------------------------------------------------------------
# lifehug#219 — the ladder reads what the writer writes
# ---------------------------------------------------------------------------


class IdentityRungTests(unittest.TestCase):
    """The founder's own shapes, structurally verbatim, synthetic surnames.

    The live find (2026-08-25): the store held `partnerships` with his wife's
    name in `label` and a day-precision date, and `children` with every child
    labelled — and `/timeline` went on asking *"Who was that?"* and *"What are
    their names?"*, because `rung_reached` counted the `who` rung only under a
    `who` key that the writer never emits. Same class as lifehug#207.
    """

    PARTNERSHIP = {"domain": "partnerships", "label": "Marisol Reyes",
                   "date": _date("2007-01-11")}
    CHILDREN = ({"domain": "children", "label": "Charlee Joy Rivers"},
                {"domain": "children", "label": "James Everett Rivers"},
                {"domain": "children", "label": "Nora Belle Rivers"},
                {"domain": "children", "label": "Silas Reed Rivers"})

    def test_the_spouses_name_and_a_date_finish_the_partnership(self):
        row = li.domain_row("partnerships")
        self.assertEqual(li.rung_reached(self.PARTNERSHIP, row), "month")
        self.assertEqual(li.status_for_domain([self.PARTNERSHIP], row), "complete")
        self.assertIsNone(li.next_rung([self.PARTNERSHIP], row))

    def test_the_who_rung_alone_is_reached_by_the_name(self):
        """Strip the date and the row still climbs off `happened` onto `who`."""
        row = li.domain_row("partnerships")
        named = {k: v for k, v in self.PARTNERSHIP.items() if k != "date"}
        self.assertEqual(li.rung_reached(named, row), "who")
        self.assertEqual(li.next_rung([named], row)["rung"], "year")

    def test_the_partnership_row_leaves_the_open_list(self):
        rows = li.landmark_rows({"partnerships": [self.PARTNERSHIP]})
        offered = {r["domain"] for r in li.open_landmarks(rows)}
        self.assertNotIn("partnerships", offered)

    def test_every_labelled_child_reaches_who(self):
        row = li.domain_row("children")
        for entry in self.CHILDREN:
            with self.subTest(child=entry["label"]):
                self.assertEqual(li.rung_reached(entry, row), "who")
        self.assertEqual(li.status_for_domain(list(self.CHILDREN), row), "partial")

    def test_the_follow_up_asks_the_missing_year_BY_NAME(self):
        """Owner ruling 4 (v202) finally reachable here: never a generic re-ask."""
        row = li.domain_row("children")
        question = li.next_rung(list(self.CHILDREN), row)
        self.assertEqual(question["rung"], "year")
        self.assertEqual(question["subject"], "Charlee Joy Rivers")
        self.assertEqual(question["text"], "What year was Charlee Joy Rivers born?")

    def test_an_answered_child_hands_the_question_to_the_next_one(self):
        row = li.domain_row("children")
        entries = [{**self.CHILDREN[0], "date": _date("2009-03")},
                   *self.CHILDREN[1:]]
        question = li.next_rung(entries, row)
        self.assertEqual(question["subject"], "James Everett Rivers")

    def test_a_name_LIST_in_one_label_is_still_names(self):
        row = li.domain_row("children")
        entry = {"domain": "children",
                 "label": "Charlee Joy Rivers, James Everett Rivers"}
        self.assertEqual(li.rung_reached(entry, row), "who")

    def test_an_empty_or_placeholder_label_is_not_a_name(self):
        row = li.domain_row("children")
        for label in ("", "   ", "that one", "unknown", "children", "—"):
            with self.subTest(label=label):
                entry = {"domain": "children", "label": label,
                         "happened": "yes"}
                self.assertIsNone(li.identity_named(entry, row))
                self.assertEqual(li.rung_reached(entry, row), "happened")

    def test_the_identity_rung_is_DERIVED_not_a_hand_written_list(self):
        """The first rung that is neither `happened` nor a date grain."""
        self.assertIsNone(li.identity_rung(li.domain_row("birth")))
        expected = {"family": "who", "residences": "city", "schools": "name",
                    "partnerships": "who", "children": "who", "work": "what",
                    "military": "branch", "losses": "who"}
        for domain, rung in expected.items():
            with self.subTest(domain=domain):
                row = li.domain_row(domain)
                self.assertEqual(li.identity_rung(row), rung)
                ladder = list(row["ladder"])
                head = ladder[: ladder.index(rung)]
                self.assertTrue(
                    all(r == li.NONE_OPENER or r in ("year", "month", "day",
                                                     "birth")
                        for r in head),
                    f"{domain}: {head} is not entailment-or-date",
                )

    def test_the_schools_chain_reads_a_bare_school_name(self):
        """The turn contract says "the school in `label`" in so many words."""
        row = li.domain_row("schools")
        entry = {"domain": "schools", "label": "Lincoln High"}
        self.assertEqual(li.rung_reached(entry, row), "name")
        self.assertEqual(li.next_rung([entry], row)["rung"], "place")

    def test_a_labelled_subject_becomes_a_NAMED_unknown(self):
        """`incomplete_subjects` skipped these entirely: with `rung_reached`
        returning None the index was -1 and the probe re-asked the opener."""
        subjects = li.incomplete_subjects(
            {"schools": [{"domain": "schools", "label": "Lincoln High"}]})
        self.assertEqual([s["rung"] for s in subjects], ["place"])
        self.assertIn("Lincoln High", subjects[0]["probe"]["text"])

    def test_an_explicit_rung_key_still_wins_over_the_label(self):
        row = li.domain_row("residences")
        entry = {"domain": "residences", "label": "Bell Avenue",
                 "city": "Dayton", "address": "11 Bell Ave"}
        self.assertEqual(li.rung_reached(entry, row), "address")

    def test_the_goldens_carry_these_shapes_and_the_ladder_reads_them(self):
        """The eval seat's two new priors ARE these shapes — one definition of
        "what a real vault looks like", not a fixture that drifts from the
        suite that motivated it."""
        fixtures = {row["fixture_id"]: row
                    for row in landmarks_evals.load_fixtures()}
        children = fixtures["landmarks-the-label-is-the-name-it-asked-for"]
        self.assertEqual([e["label"] for e in children["landmarks"]["children"]],
                         [e["label"] for e in self.CHILDREN])
        self.assertEqual(
            li.next_rung(children["landmarks"]["children"],
                         li.domain_row("children"))["subject"],
            "Charlee Joy Rivers")
        self.assertEqual(
            li.status_for_domain(children["landmarks"]["partnerships"],
                                 li.domain_row("partnerships")),
            "complete")
        things = fixtures["landmarks-a-bare-label-climbs-the-thing-ladders"]
        for domain, rung in (("residences", "city"), ("schools", "name"),
                             ("work", "what")):
            with self.subTest(domain=domain):
                row = li.domain_row(domain)
                entry = things["landmarks"][domain][0]
                self.assertEqual(set(entry), {"domain", "label"})
                self.assertEqual(li.rung_reached(entry, row), rung)
                self.assertNotEqual(li.next_rung([entry], row)["text"],
                                    row["ask"])



class CardinalityMetadataTests(unittest.TestCase):
    """v219 (lifehug-platform#664, audited temporal-claims plan §6.2).

    `chain: true` meant multiplicity, order and list closure at once. Five
    fields now say five things, and this suite is the pin that no one of them
    quietly grows a second meaning again.
    """

    def setUp(self) -> None:
        self.rows = li.load_questions()

    def test_every_domain_declares_the_whole_cardinality_block(self):
        for row in self.rows:
            with self.subTest(domain=row["domain"]):
                self.assertIn(row["collection"], li.COLLECTIONS)
                self.assertIn(row["closure"], li.CLOSURES)
                self.assertTrue(row["date_semantics"])
                for kind in row["date_semantics"]:
                    self.assertIn(kind, li.DATE_SEMANTICS)
                self.assertIsInstance(row["per_entry_ladder"], bool)

    def test_identity_kind_and_identity_rung_agree_both_ways(self):
        """The one cross-check the loader makes in both directions: a ladder
        that names a subject must say what that subject IS, and `birth` — the
        axis, which has no subject — must not claim one."""
        for row in self.rows:
            with self.subTest(domain=row["domain"]):
                if li.identity_rung(row) is None:
                    self.assertEqual(row["identity_kind"], "")
                else:
                    self.assertIn(row["identity_kind"], li.IDENTITY_KINDS)

    def test_the_multi_entry_domains_are_the_ones_that_hold_many_entries(self):
        """THE DEFECT, as a test. Before v219 this set was the four
        `chain: true` domains, and `children`, `partnerships`, `losses` and
        `military` — every one of which holds many entries — were outside it."""
        multi = {row["domain"] for row in self.rows if li.is_multi_entry(row)}
        self.assertEqual(multi, {"family", "residences", "schools",
                                 "partnerships", "children", "work",
                                 "military", "losses"})
        self.assertFalse(li.is_multi_entry(li.domain_row("birth")))

    def test_closure_is_a_different_question_from_multiplicity(self):
        """The two halves of the old flag, pulled apart and pinned apart. The
        walked lists are closed by the person; a set of children is not a list
        the system asks the end of."""
        closed = {row["domain"] for row in self.rows
                  if li.requires_declared_closure(row)}
        self.assertEqual(closed, {"family", "residences", "schools", "work"})
        for domain in ("children", "partnerships", "losses", "military"):
            with self.subTest(domain=domain):
                row = li.domain_row(domain)
                self.assertTrue(li.is_multi_entry(row))
                self.assertFalse(li.requires_declared_closure(row))

    def test_order_is_its_own_field_and_not_multiplicity(self):
        walked = {row["domain"] for row in self.rows if li.is_sequence(row)}
        self.assertEqual(walked, {"residences", "schools", "work"})
        self.assertEqual(set(li.CHAIN_MORE_TEXTS), walked)

    def test_partnerships_dates_three_distinct_events(self):
        """Audited plan §2.2: "when this part began" is insufficient when the
        underlying events differ."""
        row = li.domain_row("partnerships")
        self.assertEqual(row["date_semantics"],
                         ("first_met", "dating_started", "married"))
        texts = [event["text"] for event in li.event_questions(row, "Katie")]
        self.assertEqual(texts, [
            "When did you and Katie first meet?",
            "When did you and Katie start dating?",
            "When did you and Katie get married?",
        ])

    def test_every_enumerating_domain_has_a_text_for_every_event_it_dates(self):
        for row in self.rows:
            if not li.enumerates_subjects(row):
                continue
            with self.subTest(domain=row["domain"]):
                events = li.event_questions(row, "Jackie")
                self.assertEqual([event["event"] for event in events],
                                 list(row["date_semantics"]))
                for event in events:
                    self.assertIn("Jackie", event["text"])

    def test_an_unnamed_subject_gets_no_event_questions(self):
        self.assertEqual(li.event_questions(li.domain_row("children"), ""), ())
        self.assertEqual(li.event_questions(li.domain_row("birth"), "me"), ())

    def test_chain_is_derived_backward_and_only_says_closure_now(self):
        """Kept on the row for hosts pinned to the pre-v219 shape, and it now
        answers exactly ONE question — the closure one."""
        for row in self.rows:
            with self.subTest(domain=row["domain"]):
                self.assertEqual(row["chain"], li.requires_declared_closure(row))

    def test_no_module_in_system_reads_the_retired_flag(self):
        """The grep-with-a-parser guard. A read of `chain` anywhere under
        `system/` is the overloaded flag coming back; the loader's single
        WRITE is the one thing this must not flag, which is why it is an AST
        walk and not a grep."""
        import ast  # noqa: PLC0415

        offenders = []
        for path in sorted(SYSTEM.glob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if (isinstance(node, ast.Subscript)
                        and isinstance(node.ctx, ast.Load)
                        and isinstance(node.slice, ast.Constant)
                        and node.slice.value == "chain"):
                    offenders.append(f"{path.name}:{node.lineno} [\"chain\"]")
                if (isinstance(node, ast.Call)
                        and isinstance(node.func, ast.Attribute)
                        and node.func.attr == "get"
                        and node.args
                        and isinstance(node.args[0], ast.Constant)
                        and node.args[0].value == "chain"):
                    offenders.append(f"{path.name}:{node.lineno} .get(\"chain\")")
        self.assertEqual(offenders, [], "cardinality is read from `collection`, "
                                        "`closure` and `per_entry_ladder` now")

    def test_the_question_file_no_longer_declares_the_flag(self):
        text = (ROOT / "interactions" / "landmarks" / "questions.yaml").read_text(
            encoding="utf-8")
        for row in self.rows:
            with self.subTest(domain=row["domain"]):
                self.assertNotIn(f"\n{row['domain']}.chain:", text)


class CardinalityValidationTests(unittest.TestCase):
    """A mis-declared domain fails at LOAD, loudly.

    `children` was mis-declared for two releases and the only symptom was a
    question that would not go away. Every rule that would have caught it is
    a refusal here.
    """

    BASE = {
        "version": "2",
        "domains": "children",
        "children.order": "1",
        "children.onboarding": "true",
        "children.ask": "Do you have children?",
        "children.ladder": "happened|who|year|month",
        "children.complete_at": "month",
        "children.precision": "month",
        "children.unlocks": "entity_date",
        "children.collection": "set",
        "children.closure": "open",
        "children.identity_kind": "person",
        "children.date_semantics": "birth",
        "children.per_entry_ladder": "true",
        "children.sensitive": "false",
        "children.why": "Because.",
    }

    def _load(self, **overrides):
        raw = dict(self.BASE)
        raw.update(overrides)
        with mock.patch.object(li, "_parse_simple_yaml", return_value=raw):
            return li.load_questions()

    def test_the_well_formed_row_loads(self):
        self.assertEqual(self._load()[0]["identity_kind"], "person")

    def test_an_unknown_collection_is_refused(self):
        with self.assertRaises(li.LandmarkInteractionError):
            self._load(**{"children.collection": "many"})

    def test_an_unknown_closure_is_refused(self):
        with self.assertRaises(li.LandmarkInteractionError):
            self._load(**{"children.closure": "sometimes"})

    def test_an_unknown_date_semantic_is_refused(self):
        with self.assertRaises(li.LandmarkInteractionError):
            self._load(**{"children.date_semantics": "birth|graduation"})

    def test_a_domain_with_no_date_semantics_is_refused(self):
        with self.assertRaises(li.LandmarkInteractionError):
            self._load(**{"children.date_semantics": ""})

    def test_a_named_subject_with_no_identity_kind_is_refused(self):
        with self.assertRaises(li.LandmarkInteractionError):
            self._load(**{"children.identity_kind": ""})

    def test_an_identity_kind_on_a_ladder_that_names_nobody_is_refused(self):
        with self.assertRaises(li.LandmarkInteractionError):
            self._load(**{"children.ladder": "year|month",
                          "children.complete_at": "month"})

    def test_a_singleton_cannot_carry_a_per_entry_ladder(self):
        with self.assertRaises(li.LandmarkInteractionError):
            self._load(**{"children.collection": "singleton"})

    def test_a_singleton_has_no_group_for_the_person_to_close(self):
        with self.assertRaises(li.LandmarkInteractionError):
            self._load(**{"children.collection": "singleton",
                          "children.per_entry_ladder": "false",
                          "children.closure": "user_completable"})

    def test_many_named_entries_without_a_per_entry_ladder_is_refused(self):
        """THE DEFECT's exact shape: a domain that holds many named people
        and claims its ladder is walked once for the whole domain."""
        with self.assertRaises(li.LandmarkInteractionError):
            self._load(**{"children.per_entry_ladder": "false"})


class StandaloneQuestionSubjectTests(unittest.TestCase):
    """Audited plan §10: no standalone question omits its target.

    A rung question reaches THREE standalone surfaces — the domain row's
    `next`, a Timeline unknown from `incomplete_subjects`, and the daily
    queue that can mint one of those. On all three it arrives alone, with no
    conversational turn before it, so "Do you remember the month?" and
    "Roughly when was that?" are questions about nothing. Contextual pronouns
    are for in-session follow-ups, which is a different call site.

    The rendered PRODUCT OBJECT is what is walked here, not the template
    table: a `{label}` in `RUNG_TEXTS` that `_rung` renders as "that one" is
    exactly the bug this is guarding against.
    """

    #: One entry per domain, named and stalled at each rung past identity, so
    #: every standalone question in the set gets rendered at least once.
    NAMED = {"family": "Jackie", "residences": "Bell Avenue",
             "schools": "Lincoln High", "partnerships": "Katie",
             "children": "Charlee", "work": "the mill",
             "military": "Navy", "losses": "Grandpa Ray"}

    #: The coarsest date that satisfies each date-grain rung and NOTHING
    #: finer — a day-precision record satisfies `month` too, which would walk
    #: the fixture straight past the rung it is meant to stall on.
    GRAIN = {"birth": "1976", "year": "1976", "month": "1976-04",
             "day": "1976-04-12"}

    def _entry(self, row: dict, upto: str) -> dict:
        """An entry filed exactly as far as ``upto``, and no further."""
        label = self.NAMED[row["domain"]]
        entry = {"domain": row["domain"], "label": label}
        for rung in row["ladder"]:
            if rung == upto:
                break
            if rung == li.NONE_OPENER or rung == li.identity_rung(row):
                continue
            if rung == "span":
                entry["span"] = {"start": _date("1984"), "end": _date("1990")}
            elif rung in self.GRAIN:
                entry["date"] = _date(self.GRAIN[rung])
            else:
                entry[rung] = "filled"
        return entry

    def _past_identity(self, row: dict) -> list[str]:
        """The rungs that actually reach a standalone surface: past the
        identity rung (which asks FOR the name) and at or before
        `complete_at` (past it, `next_rung` asks nothing at all — `living`
        and `household` are recorded when stated, never demanded)."""
        ladder = list(row["ladder"])
        identity = li.identity_rung(row)
        if identity is None:
            return []
        target = row["complete_at"]
        stop = ladder.index(target) if target in ladder else len(ladder) - 1
        return ladder[ladder.index(identity) + 1:stop + 1]

    def test_every_rung_past_the_identity_rung_names_its_subject(self):
        """Including the ones past `complete_at`: `living` and `household`
        never reach a standalone surface today, but they are one
        `complete_at` edit away from it."""
        for row in li.load_questions():
            ladder = list(row["ladder"])
            identity = li.identity_rung(row)
            if identity is None:
                continue
            for rung in ladder[ladder.index(identity) + 1:]:
                with self.subTest(domain=row["domain"], rung=rung):
                    self.assertIn("{label}", li.RUNG_TEXTS[(row["domain"], rung)])

    def test_the_rendered_row_question_names_the_subject(self):
        for row in li.load_questions():
            if row["domain"] not in self.NAMED:
                continue
            for rung in self._past_identity(row):
                entry = self._entry(row, rung)
                question = li.next_rung([entry], row)
                with self.subTest(domain=row["domain"], rung=rung):
                    self.assertIsNotNone(question)
                    self.assertIn(self.NAMED[row["domain"]], question["text"])
                    self.assertNotIn("that one", question["text"])

    def test_every_standalone_unknown_names_its_subject(self):
        """The rendered unknowns, walked as a product object — key, label,
        probe text. This is the surface the queue mints from."""
        for row in li.load_questions():
            if row["domain"] not in self.NAMED:
                continue
            for rung in self._past_identity(row):
                landmarks = {row["domain"]: [self._entry(row, rung)]}
                unknowns = li.incomplete_subjects(landmarks)
                with self.subTest(domain=row["domain"], rung=rung):
                    self.assertTrue(unknowns, f"{row['domain']}.{rung} "
                                              f"produced no unknown at all")
                    for unknown in unknowns:
                        self.assertIn(self.NAMED[row["domain"]],
                                      unknown["probe"]["text"])
                        self.assertNotIn("that one", unknown["probe"]["text"])

    def test_the_identity_rung_itself_is_the_one_exemption(self):
        """It is asking FOR the name — "Who was that?" is correct there, and
        the domain opener is the same question with no entry yet."""
        for row in li.load_questions():
            identity = li.identity_rung(row)
            if identity is None:
                continue
            with self.subTest(domain=row["domain"]):
                question = li.next_rung([], row)
                self.assertEqual(question["text"], row["ask"])
                self.assertIsNone(question["subject"])



class CaptureCardinalityAcceptanceTests(unittest.TestCase):
    """The audited temporal-claims plan §10, "Capture and cardinality".

    These are the release-blocking scenarios stated as tests. The ones this
    wave (A) can make green are green; the ones that belong to a later wave
    are skipped BY NAME with the wave that owns them, so the scenario is
    visible in the suite rather than absent from it.

    THE LIVE FAILURE this reproduces (ADR 0028, the founder's own vault):
    asked about his children, he named four of them with four exact birth
    dates. They collapsed into ONE entry carrying a `span` across all four
    birthdays, and `/timeline` went on asking one aggregate question that no
    answer could close.
    """

    NAMES = ("Charlee", "Ivo", "Jonah", "Marisol")

    def _children(self, dated: dict | None = None) -> dict:
        """The four children, as four entries — one per person."""
        dates = dated or {}
        entries = []
        for name in self.NAMES:
            entry = {"domain": "children", "label": name, "who": name}
            if name in dates:
                entry["date"] = _date(dates[name])
            entries.append(entry)
        return {"children": entries}

    # -- Wave A, green -----------------------------------------------------

    def test_four_children_are_four_independently_closable_gaps(self):
        """§10: "I have four children: A, B, C, and D" yields four distinct
        entries and no aggregate pseudo-person."""
        unknowns = li.incomplete_subjects(self._children())
        self.assertEqual([row["label"] for row in unknowns], list(self.NAMES))
        self.assertEqual(len({row["key"] for row in unknowns}), 4)
        self.assertEqual(len({row["anchor"] for row in unknowns}), 4)
        for row in unknowns:
            with self.subTest(child=row["label"]):
                self.assertEqual(row["kind"], li.LANDMARK_SUBJECT_KIND)
                self.assertEqual(row["identity_kind"], "person")
                self.assertEqual(row["probe"]["text"],
                                 f"What year was {row['label']} born?")

    def test_the_aggregate_is_never_asked_as_one_question(self):
        """No gap names two children, and no gap is the domain's own opener
        wearing four names."""
        unknowns = li.incomplete_subjects(self._children())
        opener = li.domain_row("children")["ask"]
        for row in unknowns:
            text = row["probe"]["text"]
            named = [name for name in self.NAMES if name in text]
            with self.subTest(child=row["label"]):
                self.assertEqual(named, [row["label"]])
                self.assertNotEqual(text, opener)

    def test_answering_one_child_closes_only_that_childs_gap(self):
        """"Independently closable" is the whole claim: Ivo's birth month
        closes Ivo's gap and touches none of the other three."""
        row = li.domain_row("children")
        # A YEAR moves Ivo one rung; his gap survives, asking the next thing.
        year_only = li.incomplete_subjects(self._children({"Ivo": "1979"}))
        by_label = {gap["label"]: gap["probe"]["text"] for gap in year_only}
        self.assertEqual(set(by_label), set(self.NAMES))
        self.assertEqual(by_label["Ivo"], "Do you remember the month Ivo was born?")
        self.assertEqual(by_label["Charlee"], "What year was Charlee born?")
        # The MONTH is `children`'s `complete_at`, so Ivo's gap closes — and
        # only Ivo's.
        closed = li.incomplete_subjects(self._children({"Ivo": "1979-03"}))
        self.assertEqual([gap["label"] for gap in closed],
                         ["Charlee", "Jonah", "Marisol"])
        entry = self._children({"Ivo": "1979-03"})["children"][1]
        self.assertEqual(li.rung_reached(entry, row), row["complete_at"])

    def test_each_entry_progresses_through_its_own_field_ladder(self):
        """§10: "Multiple entries in one response can each progress through
        their own field ladder." Four children at four different rungs get
        four different questions in the same read."""
        landmarks = self._children({"Ivo": "1979", "Jonah": "1981-06"})
        by_label = {row["label"]: row["probe"]["text"]
                    for row in li.incomplete_subjects(landmarks)}
        self.assertEqual(by_label, {
            "Charlee": "What year was Charlee born?",
            "Ivo": "Do you remember the month Ivo was born?",
            "Marisol": "What year was Marisol born?",
        })
        # Jonah reached `complete_at` on his own and left the list on his own.
        self.assertNotIn("Jonah", by_label)

    def test_the_domain_row_alone_could_never_have_closed_them(self):
        """Why the per-subject gap has to exist: the row carries exactly ONE
        `next` question however many people sit incomplete inside it."""
        landmarks = self._children()
        rows = {row["domain"]: row for row in li.landmark_rows(landmarks)}
        self.assertEqual(rows["children"]["count"], 4)
        self.assertEqual(rows["children"]["status"], "partial")
        self.assertEqual(rows["children"]["next"]["text"],
                         "What year was Charlee born?")
        self.assertEqual(len(li.incomplete_subjects(landmarks)), 4)

    def test_the_collapsed_aggregate_shape_is_recognized_as_unreadable(self):
        """The exact live record: one entry, all four names, a span across
        all four birthdays. `children` has no span rung, so the span is a
        field no ladder can read — and that is now a named shape rather than
        a silent one."""
        aggregate = {"domain": "children", "label": "Charlee, Ivo, Jonah, Marisol",
                     "span": {"start": _date("1976"), "end": _date("1984")}}
        row = li.domain_row("children")
        self.assertIn("span", li.unreadable_fields(aggregate, row))
        self.assertFalse(li.dates_each_entry(li.domain_row("residences")))
        self.assertTrue(li.dates_each_entry(row),
                        "a child is dated by ONE birth, so a second year in "
                        "one answer is a second child")

    def test_losses_and_partnerships_enumerate_too(self):
        """The other two domains the flag hid. Both hold people; neither is a
        walked list; both owe one gap per subject."""
        landmarks = {
            "losses": [{"domain": "losses", "label": "Grandpa Ray",
                        "who": "Grandpa Ray"}],
            "partnerships": [{"domain": "partnerships", "label": "Katie",
                              "who": "Katie"}],
        }
        by_label = {row["label"]: row for row in li.incomplete_subjects(landmarks)}
        self.assertEqual(set(by_label), {"Grandpa Ray", "Katie"})
        self.assertEqual(by_label["Grandpa Ray"]["probe"]["text"],
                         "Roughly when did you lose Grandpa Ray?")
        self.assertEqual(by_label["Katie"]["probe"]["text"],
                         "Roughly when did you and Katie get together?")

    def test_a_loss_gap_is_about_a_named_person_never_loss_discovery(self):
        """§2.4 / §10: loss DISCOVERY is offer-only and never enters the
        queue. A per-subject gap is a different question — it is about
        somebody the person already named, which is exactly why widening the
        enumeration to `losses` does not widen the discovery prompt. The
        structure guarantees it: `incomplete_subjects` renders only rungs
        PAST the identity rung, and only for an entry carrying a name."""
        row = li.domain_row("losses")
        opener = row["ask"]
        gaps = li.incomplete_subjects({"losses": [
            {"domain": "losses", "label": "Grandpa Ray", "who": "Grandpa Ray"},
            {"domain": "losses", "skipped": True},
            {"domain": "losses", "none": True},
        ]})
        self.assertEqual([gap["label"] for gap in gaps], ["Grandpa Ray"])
        self.assertNotEqual(gaps[0]["probe"]["text"], opener)
        self.assertNotIn("lost someone", gaps[0]["probe"]["text"])
        # An empty domain mints no gap at all — the opener stays where it is,
        # on the landmark row, offered rather than asked.
        self.assertEqual(li.incomplete_subjects({"losses": []}), ())
        self.assertTrue(row["sensitive"])

    def test_the_three_partnership_events_are_three_distinct_asks(self):
        """§2.2 / §10: first meeting, the start of dating and the marriage are
        distinct events. This wave delivers the QUESTIONS; the claim records
        are Wave C's, and the skipped test below says so."""
        landmarks = {"partnerships": [{"domain": "partnerships",
                                       "label": "Katie", "who": "Katie"}]}
        unknown, = li.incomplete_subjects(landmarks)
        self.assertEqual([event["event"] for event in unknown["events"]],
                         ["first_met", "dating_started", "married"])
        self.assertEqual([event["text"] for event in unknown["events"]], [
            "When did you and Katie first meet?",
            "When did you and Katie start dating?",
            "When did you and Katie get married?",
        ])

    # -- later waves, named rather than absent -----------------------------

    @unittest.skip("Wave C (semantic capture): a partnership entry carries "
                   "ONE date today. Per-event claim records — first_met, "
                   "dating_started and married with independent dates and "
                   "ranges — need the TemporalClaim substrate from Wave B, "
                   "and inventing a second storage shape here would be the "
                   "half-built machine the plan forbids. v219 ships the "
                   "questions only.")
    def test_partnership_events_carry_independent_dates(self):
        raise NotImplementedError

    @unittest.skip("Wave A, sibling item (recorder precedence): "
                   "'the same focused turn observed by two subsystems yields "
                   "one canonical semantic write set' is the landmark "
                   "recorder / general listener boundary, owned outside this "
                   "PR's file boundaries.")
    def test_one_canonical_write_set_per_focused_turn(self):
        raise NotImplementedError

    @unittest.skip("Wave B (truth substrate): 'retrying a successful or "
                   "uncertain request creates no duplicate claim, person, "
                   "event, question or correction' needs the idempotency key "
                   "over conversation/turn/source-revision/recorder/"
                   "extraction-version, which does not exist yet.")
    def test_a_retry_creates_no_duplicate_entry(self):
        raise NotImplementedError

    @unittest.skip("Wave F (queue coordination): 'answering on Timeline "
                   "closes the corresponding queue/whisper candidate and "
                   "vice versa' needs one work-item identity across "
                   "surfaces. v219 gives each gap a stable per-subject key, "
                   "which is the half of it this wave owes.")
    def test_one_work_item_identity_across_surfaces(self):
        raise NotImplementedError


class LadderConsistencyTests(unittest.TestCase):
    """The class guard (recurring-defect doctrine, docs/BUILDING.md §7).

    Three defects in this class have now shipped — `span` (v199), the date
    grains (lifehug#207) and the identity rung (lifehug#219) — and every one of
    them is the same sentence: *the ladder could not read what the writer
    writes*. Patching the fourth instance is not the fix. This suite asserts
    the property instead:

    1. every rung has a question, and every question is a rung;
    2. every rung text survives its own domain's lints;
    3. **every rung is reachable from every field that satisfies it**, which
       is what `rung_satisfiers` declares — this leg fails for lifehug#207 and
       for lifehug#219 on the pre-fix code;
    4. **every field the writer can store is a rung, a declared satisfier, or
       explicitly not a rung** — so a new writer field cannot land in a vault
       with no rung able to see it.
    """

    #: The grain a date must carry to satisfy each date-grain rung.
    GRAIN = {"birth": "1976", "year": "1976", "month": "1976-04",
             "day": "1976-04-12"}

    def setUp(self) -> None:
        self.rows = li.load_questions()

    def _value(self, field: str, rung: str) -> object:
        if field == "date":
            return _date(self.GRAIN.get(rung, "1976"))
        if field == "span":
            return {"start": _date("1984"), "end": _date("1990")}
        if rung in li._BOOL_RUNGS:  # noqa: SLF001
            return True
        return self.GRAIN.get(rung, "Jackie")

    def test_every_question_is_a_rung_and_every_rung_a_question(self):
        declared = {(row["domain"], rung)
                    for row in self.rows for rung in row["ladder"]}
        self.assertEqual(set(li.RUNG_TEXTS), declared)

    def test_every_rung_text_survives_its_own_domains_lints(self):
        for (domain, rung), text in li.RUNG_TEXTS.items():
            rendered = text.format(label="Jackie")
            with self.subTest(domain=domain, rung=rung):
                self.assertEqual(
                    li.lint_landmark_reply(
                        rendered, stage="ask", domain=domain,
                        sensitive=li.domain_row(domain)["sensitive"]),
                    [])

    def test_every_rung_is_reachable_from_every_field_that_satisfies_it(self):
        """The guard that would have caught lifehug#207 AND lifehug#219."""
        for row in self.rows:
            ladder = list(row["ladder"])
            for index, rung in enumerate(ladder):
                for field in li.rung_satisfiers(row, rung):
                    prefix = {earlier: self._value(earlier, earlier)
                              for earlier in ladder[:index]}
                    entry = {"domain": row["domain"], **prefix,
                             field: self._value(field, rung)}
                    reached = li.rung_reached(entry, row)
                    with self.subTest(domain=row["domain"], rung=rung,
                                      field=field):
                        self.assertIsNotNone(
                            reached,
                            f"{row['domain']}.{rung} unreachable via {field!r}")
                        self.assertGreaterEqual(
                            ladder.index(reached), index,
                            f"{row['domain']}.{rung} filed under {field!r} "
                            f"only reached {reached!r}")

    def test_the_entailed_opener_is_the_one_rung_with_no_named_field(self):
        """`happened` is satisfied by a SHAPE, not a field — said out loud so
        the leg above is not quietly counting it as covered."""
        for row in self.rows:
            if not li.domain_accepts_none(row):
                continue
            with self.subTest(domain=row["domain"]):
                self.assertEqual(li.rung_satisfiers(row, li.NONE_OPENER),
                                 (li.NONE_OPENER,))
                self.assertEqual(
                    li.rung_reached({"domain": row["domain"], "place": "Ohio"},
                                    row),
                    li.NONE_OPENER)

    #: Every field the writer stores that NO rung of that domain can read.
    #: Pinned, so the slack cannot grow: a `span` on `children` is exactly the
    #: shape the founder's own entry carried, filed and invisible.
    UNREAD = {("birth", "label"), ("birth", "span"), ("family", "span"),
              ("partnerships", "span"), ("children", "span"),
              ("losses", "span")}

    def _stored_fields(self, row: dict) -> set[str]:
        """Every field `validate_landmark` will keep for this domain."""
        ladder = list(row["ladder"])
        everything = {"domain": row["domain"], "label": "Jackie",
                      "place": "Dayton", "subject": "Jackie",
                      "birth_order": "the middle of five",
                      "date": _date("1976-04-12"),
                      "span": {"start": _date("1984"), "end": _date("1990")},
                      "chain_complete": True}
        everything.update({rung: self._value(rung, rung) for rung in ladder})
        return set(li.validate_landmark(everything))

    def test_every_field_the_writer_stores_maps_to_a_rung_or_is_declared(self):
        for row in self.rows:
            # v214: `unreadable_fields` IS this leg's sentence, moved onto the
            # module so the store can recognize the same shape.
            unread = set(li.unreadable_fields(
                dict.fromkeys(self._stored_fields(row), "x"), row))
            for field in self._stored_fields(row):
                with self.subTest(domain=row["domain"], field=field):
                    self.assertTrue(
                        field not in unread
                        or field in li.DOMAIN_AGNOSTIC_FIELDS,
                        f"{row['domain']}: {field!r} is stored by the writer "
                        f"but is neither a rung, a declared satisfier, nor "
                        f"declared NON_RUNG_FIELDS",
                    )

    def test_the_unread_fields_are_pinned_and_cannot_grow(self):
        """The domain-agnostic slack, named. Every pair here is a field the
        writer files that that domain's ladder has no rung for."""
        unread = set()
        for row in self.rows:
            stored = dict.fromkeys(self._stored_fields(row), "x")
            for field in li.unreadable_fields(stored, row):
                unread.add((row["domain"], field))
        self.assertEqual(unread, self.UNREAD)
        self.assertEqual({field for _domain, field in unread},
                         set(li.DOMAIN_AGNOSTIC_FIELDS))

    def test_a_rung_that_is_not_on_the_ladder_is_refused(self):
        with self.assertRaises(li.LandmarkInteractionError):
            li.rung_satisfiers(li.domain_row("birth"), "who")

    # -- leg 5 (v219): the ladder and the cardinality block agree ----------

    def test_date_semantics_and_the_ladder_agree_about_spans(self):
        """The two statements of "is one entry's date a stretch?" — the
        ladder's `span` rung and the `span` date semantic — are one fact, and
        a domain that declares one without the other is the same defect class
        as a rung the writer cannot reach. `dates_each_entry` reads the
        semantic; this is what keeps that honest."""
        for row in self.rows:
            with self.subTest(domain=row["domain"]):
                self.assertEqual("span" in row["date_semantics"],
                                 "span" in row["ladder"])
                self.assertEqual(li.dates_each_entry(row),
                                 "span" not in row["ladder"])

    def test_a_per_entry_ladder_has_rungs_below_its_identity_rung(self):
        """A domain that says its ladder is walked per entry must have a
        ladder left to walk once the entry is named."""
        for row in self.rows:
            if not row["per_entry_ladder"]:
                continue
            ladder = list(row["ladder"])
            identity = li.identity_rung(row)
            with self.subTest(domain=row["domain"]):
                self.assertIsNotNone(identity)
                self.assertTrue(ladder[ladder.index(identity) + 1:],
                                f"{row['domain']} claims a per-entry ladder "
                                f"with nothing past {identity!r}")

    def test_every_event_question_is_declared_and_every_declaration_is_one(self):
        declared = {(row["domain"], event) for row in self.rows
                    if li.enumerates_subjects(row)
                    for event in row["date_semantics"]}
        self.assertEqual(set(li.EVENT_QUESTION_TEXTS), declared)

    def test_every_event_question_survives_its_own_domains_lints(self):
        for (domain, event), text in li.EVENT_QUESTION_TEXTS.items():
            rendered = text.format(label="Jackie")
            with self.subTest(domain=domain, event=event):
                self.assertEqual(
                    li.lint_landmark_reply(
                        rendered, stage="ask", domain=domain,
                        sensitive=li.domain_row(domain)["sensitive"]),
                    [])


class LeafShapedAnswerMatrixTests(unittest.TestCase):
    """The certification audit's executed matrix, as the acceptance test.

    Audit (lifehug-platform#586, 2026-08-25): the ladder/writer mismatch is a
    NINE-domain class, not a `who` bug. The leaf (`prompt/turn-instructions.md`)
    teaches `label` — *"the school in `label`"* — while seven of the nine
    ladders demand `city` / `name` / `what` / `who`, so a PERFECT leaf-shaped
    answer left seven domains re-asking their own opening question forever.
    Only `birth` (a date) and `family` (whose leaf paragraph does teach the
    rung keys) worked.

    One row per domain: the leaf-shaped emission, through validation, then the
    rung it reaches, the status, and the question the row asks NEXT. Every
    row is a cell of the audit's table; the whole table is the contract.
    """

    LEAF: dict[str, dict] = {
        "birth": {"domain": "birth", "date": _date("1978-04-12")},
        "family": {"domain": "family", "label": "Steph", "who": "Steph",
                   "relation": "sibling"},
        "residences": {"domain": "residences", "label": "Costa Mesa"},
        "schools": {"domain": "schools", "label": "Lincoln High"},
        "partnerships": {"domain": "partnerships", "label": "Katie",
                         "date": _date("2007-01-11")},
        "children": {"domain": "children", "label": "Charlee",
                     "span": {"start": _date("2010-12-21"),
                              "end": _date("2021-10-11")}},
        "work": {"domain": "work", "label": "Line cook"},
        "military": {"domain": "military", "none": True},
        "losses": {"domain": "losses", "label": "Grandpa Ray"},
    }

    #: domain -> (rung reached, status, the next question — None when complete)
    EXPECTED = {
        "birth": ("day", "complete", None),
        "family": ("relation", "partial", "What year was Steph born?"),
        "residences": ("city", "partial",
                       "Do you remember the address on Costa Mesa?"),
        "schools": ("name", "partial", "Where was Lincoln High — what town?"),
        "partnerships": ("month", "complete", None),
        "children": ("who", "partial", "What year was Charlee born?"),
        "work": ("what", "partial", "Where were you doing Line cook?"),
        "military": ("span", "complete", None),
        "losses": ("who", "partial", "Roughly when did you lose Grandpa Ray?"),
    }

    def test_the_matrix_covers_every_domain_in_the_set(self):
        domains = tuple(row["domain"] for row in li.load_questions())
        self.assertEqual(tuple(self.LEAF), domains)
        self.assertEqual(set(self.EXPECTED), set(domains))

    def test_a_perfect_leaf_shaped_answer_never_re_asks_the_opener(self):
        for domain, (rung, status, question) in self.EXPECTED.items():
            with self.subTest(domain=domain):
                row = li.domain_row(domain)
                record = li.validate_landmark(self.LEAF[domain])
                self.assertIsNotNone(record, f"{domain}: the leaf shape "
                                             f"did not even validate")
                self.assertEqual(li.rung_reached(record, row), rung)
                self.assertEqual(li.status_for_domain([record], row), status)
                nxt = li.next_rung([record], row)
                self.assertEqual((nxt or {}).get("text"), question)
                if question is not None:
                    self.assertNotEqual(
                        question, row["ask"],
                        f"{domain} re-asks its own opening question")

    def test_the_completed_rows_leave_the_offered_list(self):
        filed = {domain: [li.validate_landmark(self.LEAF[domain])]
                 for domain in self.LEAF}
        offered = {r["domain"] for r in li.open_landmarks(li.landmark_rows(filed))}
        complete = {domain for domain, (_r, status, _q) in self.EXPECTED.items()
                    if status == "complete"}
        self.assertFalse(offered & complete)
        self.assertEqual(offered, set(self.EXPECTED) - complete)

    def test_the_leaf_teaches_the_label_which_is_why_this_is_a_class(self):
        """The mismatch's source, pinned: the turn contract says `label`."""
        leaf = " ".join(
            (ROOT / "interactions" / "landmarks" / "prompt"
             / "turn-instructions.md").read_text(encoding="utf-8").split())
        self.assertIn("`label`", leaf,
                      "the leaf no longer names `label` — re-derive this class")
        for domain in ("residences", "schools", "work", "partnerships",
                       "children", "losses", "military"):
            with self.subTest(domain=domain):
                row = li.domain_row(domain)
                self.assertIsNotNone(
                    li.identity_rung(row),
                    f"{domain} has no identity rung for a bare label to reach")


class AnswerMustRecordTests(unittest.TestCase):
    """v212 (lifehug#221) — replying is not recording.

    Two live landmark sessions on the platform's v207+ leaf came back with a
    warm, engaged reply and `landmark: null`: the military question answered
    with a plain "I have not served" alongside a mission story, and the losses
    question answered with the names of actual people. The record lost to the
    conversation, twice, on the same leaf. This class makes that shape
    mechanically visible.
    """

    BAD_FIXTURE = (ROOT / "interactions" / "landmarks" / "evals" / "goldens"
                   / "landmark-answer-not-recorded-bad-01.json")

    def _cases(self) -> list[dict]:
        data = json.loads(self.BAD_FIXTURE.read_text(encoding="utf-8"))
        self.assertEqual(data["fixture_id"], "landmark-answer-not-recorded-bad-01")
        return data["cases"]

    def _record(self, case: dict, raws: list[str]) -> object:
        """Drive the recorder over one case with scripted completions."""
        import landmark_recorder as recorder  # noqa: PLC0415

        seen: list[str] = []

        def _call(prompt: str, model: str) -> str:
            seen.append(prompt)
            return raws[min(len(seen), len(raws)) - 1]

        outcome = recorder.record_answer(
            domain=case["domain"], answer=case["user_message"],
            reply=case["reply"], call=_call,
        )
        return outcome, seen

    def _finding(self, case: dict, record: object) -> object:
        return li.answer_must_record(case["user_message"], record,
                                     reply=case["reply"],
                                     domain=case["domain"])

    def test_the_class_is_declared_and_named(self):
        self.assertIn(li.ANSWER_MUST_RECORD_LINT, li.LANDMARK_LINT_CLASSES)
        self.assertEqual(li.ANSWER_MUST_RECORD_LINT,
                         "landmark_gates.answer_must_record")

    def test_both_live_failures_are_caught_by_the_recorder(self):
        cases = self._cases()
        self.assertEqual([c["case_id"] for c in cases],
                         ["military-none-lost-to-the-mission-story",
                          "losses-named-back-but-never-filed"])
        import landmark_recorder as recorder  # noqa: PLC0415

        for case in cases:
            with self.subTest(case=case["case_id"]):
                # The empty first extraction, repeated: the recorder refuses
                # to call it done and withholds rather than dropping it.
                outcome, seen = self._record(case, [case["attempt"]["raw"]])
                self.assertEqual(outcome.status, recorder.STATUS_WITHHELD)
                self.assertEqual(outcome.lint_ids,
                                 (li.ANSWER_MUST_RECORD_LINT,))
                self.assertEqual(len(seen), recorder.MAX_ATTEMPTS)

    def test_the_recorder_regenerates_once_and_emits(self):
        """The retry path, end to end: lint -> reminder -> emit."""
        import landmark_recorder as recorder  # noqa: PLC0415

        for case in self._cases():
            with self.subTest(case=case["case_id"]):
                outcome, seen = self._record(
                    case, [case["attempt"]["raw"], case["regenerated"]["raw"]])
                self.assertEqual(outcome.status, recorder.STATUS_RECORDED)
                self.assertEqual(outcome.attempts, 2)
                self.assertEqual(outcome.record, case["expected_landmark"])
                # The reminder is what made the difference, and only the
                # SECOND prompt carries it.
                reminder = li.recording_reminder(case["domain"])
                self.assertNotIn(reminder, seen[0])
                self.assertIn(reminder, seen[1])
                self.assertIsNone(self._finding(case, outcome.record))

    def test_the_recorder_never_needed_the_reply(self):
        """The audit's hardest case: reply generation failed entirely."""
        import landmark_recorder as recorder  # noqa: PLC0415

        case = dict(self._cases()[0], reply="")
        outcome, _ = self._record(
            case, [case["attempt"]["raw"], case["regenerated"]["raw"]])
        self.assertEqual(outcome.status, recorder.STATUS_RECORDED)
        self.assertEqual(outcome.record, case["expected_landmark"])

    def test_a_mission_is_not_a_military_landmark(self):
        """The domain's own answer is a none; the story goes to capture."""
        case = self._cases()[0]
        import landmark_recorder as recorder  # noqa: PLC0415

        # v214: the parse returns a record SET, and a none is always alone
        # in it — a terminal answers the whole domain.
        records = recorder.parse_recorder_output(case["regenerated"]["raw"])
        self.assertEqual(records, ({"domain": "military", "none": True},))
        record = records[0]
        self.assertEqual(li.status_for_domain([record],
                                              li.domain_row("military")),
                         "complete")

    def test_a_loss_records_the_person_and_never_invents_a_date(self):
        case = self._cases()[1]
        record = case["expected_landmark"]
        self.assertEqual(record["who"], "Needy Beecham")
        self.assertEqual(record["subject"], "my mother's mother")
        self.assertNotIn("date", record)
        self.assertNotIn("year", record)

    def test_any_emitted_record_clears_the_class(self):
        for emitted in ({"domain": "military", "none": True},
                        {"domain": "military", "skipped": True},
                        {"domain": "military", "branch": "Navy"}):
            with self.subTest(emitted=emitted):
                self.assertNotIn(li.ANSWER_MUST_RECORD_LINT, [
                    f["lint"] for f in li.lint_landmark_reply(
                        "No service then. Zurich at nineteen, though.",
                        stage="ask", domain="military", landmark=emitted,
                        user_message="I have not served in the military.",
                    )
                ])

    def test_a_skip_is_never_a_missed_record(self):
        self.assertEqual(li.answer_shape("I don't remember, honestly.",
                                         "Of course — we'll leave it."),
                         "skip")
        self.assertNotIn(li.ANSWER_MUST_RECORD_LINT, [
            f["lint"] for f in li.lint_landmark_reply(
                "Of course — we'll leave it.", stage="ask", domain="military",
                user_message="I don't remember, honestly.",
            )
        ])

    def test_an_ambiguous_answer_is_not_punished(self):
        """Fail toward skip: no name, no year, no denial — no finding."""
        user = ("We moved around a fair bit when I was small — a few "
                "different places, and it all blurs together now.")
        reply = "A lot of moving. We can take them one at a time."
        self.assertEqual(li.answer_shape(user, reply), "unknown")
        self.assertNotIn(li.ANSWER_MUST_RECORD_LINT, [
            f["lint"] for f in li.lint_landmark_reply(
                reply, stage="ask", domain="residences", user_message=user)
        ])

    def test_a_negative_only_counts_where_a_none_can_be_recorded(self):
        """`family` opens at `who`: "no siblings" is not an empty family."""
        user = "I didn't have any brothers or sisters."
        reply = "An only child, then. Who else was at home?"
        self.assertNotIn(li.ANSWER_MUST_RECORD_LINT, [
            f["lint"] for f in li.lint_landmark_reply(
                reply, stage="ask", domain="family", user_message=user)
        ])
        self.assertIn(li.ANSWER_MUST_RECORD_LINT, [
            f["lint"] for f in li.lint_landmark_reply(
                "No children, then.", stage="ask", domain="children",
                user_message="No, we never had children.")
        ])

    def test_the_model_echoing_what_it_already_knew_is_not_evidence(self):
        """A label already in LANDMARKS is the model's own word, not theirs."""
        self.assertEqual(
            li.answer_shape("Yes, Bell Avenue.", "Bell Avenue, right.",
                            known_labels=("Bell Avenue",)),
            "unknown",
        )
        self.assertEqual(
            li.answer_shape("Yes, Bell Avenue.", "Bell Avenue, right."),
            "substantive",
        )

    def test_pre_v212_call_sites_are_byte_identical(self):
        """Every existing caller passes no user message, so it cannot fire."""
        self.assertEqual(
            li.lint_landmark_reply("Where did you live?", stage="ask",
                                   domain="residences"),
            [],
        )

    def test_the_shape_vocabulary_is_closed(self):
        for user, reply, expected in (
            ("", "", "unknown"),
            ("Let's leave that one.", "Of course.", "skip"),
            ("I never served.", "No service, then.", "negative"),
        ):
            with self.subTest(user=user):
                self.assertEqual(
                    li.answer_shape(user, reply, accepts_none=True), expected)
                self.assertIn(
                    li.answer_shape(user, reply, accepts_none=True),
                    li.ANSWER_SHAPES)

    def test_the_seat_scores_the_class_and_can_fail_it(self):
        """The gate has a real denominator — it is not free compliance."""
        import copy  # noqa: PLC0415

        fixtures = landmarks_evals.load_fixtures()
        predictions = landmarks_evals.load_sample_predictions()
        self.assertEqual(
            landmarks_evals.score_goldens(fixtures, predictions)
            ["answer_must_record.compliance"], 1.0)
        broken = copy.deepcopy(predictions)
        for row in broken:
            if row["fixture_id"] == "landmarks-military-none-with-a-story-alongside":
                row["turns"][0]["landmark"] = None
        scores = landmarks_evals.score_goldens(fixtures, broken)
        self.assertLess(scores["answer_must_record.compliance"], 1.0)
        self.assertTrue(landmarks_evals.check_gates(
            scores, landmarks_evals.load_gates()))

    def test_the_gate_and_the_class_list_agree(self):
        gates = landmarks_evals.load_gates()
        self.assertIn("answer_must_record.compliance", gates)
        self.assertEqual(
            sorted(gates),
            sorted(f"{name.split('.', 1)[1]}.compliance"
                   for name in li.LANDMARK_LINT_CLASSES),
        )

    def test_the_new_files_ship_in_framework_files(self):
        manifest = json.loads(
            (ROOT / "system" / "version.json").read_text(encoding="utf-8"))
        self.assertIn(
            "interactions/landmarks/evals/goldens/"
            "landmark-answer-not-recorded-bad-01.json",
            manifest["framework_files"],
        )

    def test_the_turn_instructions_state_recording_is_the_first_job(self):
        text = (ROOT / "interactions" / "landmarks" / "prompt"
                / "turn-instructions.md").read_text(encoding="utf-8")
        self.assertIn("Recording is this turn's FIRST job", text)
        behavior = (ROOT / "interactions" / "landmarks" / "prompt"
                    / "behavior.md").read_text(encoding="utf-8")
        self.assertIn("Replying is not recording", behavior)


class LandmarkRecorderTests(unittest.TestCase):
    """v212 / ADR 0028 — one recorder, two triggers.

    The conversation writes the reply; the recorder files the record. The
    audit (platform #586) certified that the emission instruction was already
    in the live leaf when the founder's military answer was swallowed, so the
    only certifiable mechanism is a deterministic pass with a blocking
    backstop. This is that pass.
    """

    def setUp(self) -> None:
        import landmark_recorder as recorder  # noqa: PLC0415

        self.recorder = recorder

    def _prompt(self, **kwargs) -> str:
        base = {"domain": "military", "question_asked": "Did you serve?",
                "answer": "I never served.", "reply": "No service, then."}
        return self.recorder.build_recorder_prompt(**{**base, **kwargs})

    def test_the_recorder_has_no_voice_and_no_transcript(self):
        """The whole reason the second call is small."""
        prompt = self._prompt()
        for absent in ("## IDENTITY", "## BEHAVIOR", "## EXAMPLES",
                       "## SESSION"):
            self.assertNotIn(absent, prompt)
        self.assertIn("You are not in the conversation", prompt)
        # v229 moves this ceiling from 4800 (v216 moved it from 4400, v214
        # from 4000). The leaf gained the whole `claims` contract — the claim
        # types, the seed event vocabulary, the raw-mention rule, the
        # quotation requirement, and the two repeals (relative time is kept,
        # anyone's date counts) — and every domain's prompt with an EMPTY
        # already-filed block now lands between 8007 and 8125.
        #
        # THE COST, stated rather than buried: this is ~2000 tokens where
        # v216's was ~1150, so the second completion roughly doubled. It is
        # still an order of magnitude under the conversation prompt (whose
        # own budgets sum past 8000 tokens BEFORE the transcript), and it is
        # still a leaf with NO identity, no behavior, no examples and no
        # transcript — which is the property this pin exists to hold and the
        # only one it has ever held. A ceiling that forced the contract to be
        # incomplete would be buying tokens with dropped facts.
        #
        # E3 (eras §4.3) moved it again, 8225 → 8555, by ONE bullet:
        # `event_mention` and the paragraph telling the ear it is writing down
        # a NAME rather than making a link. Re-measured, not rounded up — a
        # pin padded "for headroom" measures nothing.
        self.assertLess(len(prompt), 8700)
        for row in li.load_questions():
            with self.subTest(domain=row["domain"]):
                self.assertLess(len(self._prompt(domain=row["domain"],
                                                 question_asked=row["ask"])),
                                8700)

    def test_the_prompt_carries_the_domains_own_ladder_and_none_rule(self):
        military = self._prompt()
        self.assertIn("happened | branch | span", military)
        self.assertIn("CAN THIS DOMAIN BE ANSWERED \"NEVER HAPPENED\": yes",
                      military)
        family = self._prompt(domain="family",
                              question_asked="Who was in your family?")
        self.assertIn("CAN THIS DOMAIN BE ANSWERED \"NEVER HAPPENED\": no",
                      family)

    def test_the_reminder_is_appended_only_when_given(self):
        self.assertNotIn("first job", self._prompt())
        self.assertIn(li.recording_reminder("military"),
                      self._prompt(reminder=li.recording_reminder("military")))

    def test_an_unknown_domain_is_refused_at_composition(self):
        with self.assertRaises(li.LandmarkInteractionError):
            self._prompt(domain="pets")

    def test_parsing_runs_both_pinned_validation_layers(self):
        """v214: the same two layers, per record, into a record SET."""
        self.assertEqual(
            self.recorder.parse_recorder_output(
                '{"landmark": {"domain": "residences", "city": "Dayton", '
                '"label": "Dayton"}}'),
            ({"domain": "residences", "label": "Dayton", "city": "Dayton"},),
        )
        # A domain the question set never declares is dropped, not stored.
        self.assertEqual(self.recorder.parse_recorder_output(
            '{"landmark": {"domain": "pets", "label": "Rex"}}'), ())
        # A fence is tolerated; nothing looser is.
        self.assertEqual(
            self.recorder.parse_recorder_output(
                '```json\n{"landmark": {"domain": "military", "none": true}}\n```'),
            ({"domain": "military", "none": True},),
        )
        for junk in ("", "no idea", '{"landmark": "military"}', None, 7):
            with self.subTest(junk=junk):
                self.assertEqual(self.recorder.parse_recorder_output(junk), ())

    def test_the_v212_singleton_envelope_still_parses_unchanged(self):
        """No flag day: a v212 prompt, host or stored completion still reads."""
        singleton = self.recorder.parse_recorder_output(
            '{"landmark": {"domain": "military", "branch": "the Army", '
            '"label": "the Army"}}')
        listed = self.recorder.parse_recorder_output(
            '{"landmarks": [{"domain": "military", "branch": "the Army", '
            '"label": "the Army"}]}')
        self.assertEqual(singleton, listed)
        self.assertEqual(len(singleton), 1)
        # And `{"landmark": null}` and `{"landmarks": []}` say the same thing.
        self.assertEqual(self.recorder.parse_recorder_output(
            '{"landmark": null}'), ())
        self.assertEqual(self.recorder.parse_recorder_output(
            '{"landmarks": []}'), ())

    def test_nothing_said_about_the_domain_records_nothing_and_is_correct(self):
        outcome = self.recorder.record_answer(
            domain="residences", answer="Anyway, how are you today?",
            reply="Doing fine.", call=lambda p, m: '{"landmark": null}')
        self.assertEqual(outcome.status, self.recorder.STATUS_NOTHING)
        self.assertEqual(outcome.attempts, 1)
        self.assertIsNone(outcome.record)

    def test_a_skip_records_the_skip_and_never_retries(self):
        outcome = self.recorder.record_answer(
            domain="military", answer="Let's leave that one.",
            reply="Of course.",
            call=lambda p, m: '{"landmark": {"domain": "military", '
                              '"skipped": true}}')
        self.assertEqual(outcome.status, self.recorder.STATUS_RECORDED)
        self.assertEqual(outcome.record, {"domain": "military", "skipped": True})
        self.assertEqual(outcome.attempts, 1)

    def test_a_provider_failure_is_data_never_an_exception(self):
        def _boom(prompt: str, model: str) -> str:
            raise RuntimeError("no provider")

        outcome = self.recorder.record_answer(
            domain="military", answer="I never served.", reply="", call=_boom)
        self.assertEqual(outcome.status, self.recorder.STATUS_UNAVAILABLE)
        self.assertIn("no provider", outcome.reason)
        self.assertIsNone(outcome.record)

    def test_the_retry_is_bounded_at_exactly_one(self):
        calls: list[str] = []

        def _empty(prompt: str, model: str) -> str:
            calls.append(prompt)
            return '{"landmark": null}'

        outcome = self.recorder.record_answer(
            domain="children", answer="No, we never had children.",
            reply="No children, then.", call=_empty)
        self.assertEqual(len(calls), self.recorder.MAX_ATTEMPTS)
        self.assertEqual(self.recorder.MAX_ATTEMPTS, 2)
        self.assertEqual(outcome.status, self.recorder.STATUS_WITHHELD)

    def test_the_recorder_role_matches_the_manifest(self):
        """Tuning the knob and tuning the constant stay one edit."""
        raw = (ROOT / "interactions" / "landmarks"
               / "interaction.yaml").read_text(encoding="utf-8")
        self.assertIn(f"role.recorder: {self.recorder.DEFAULT_RECORDER_ROLE}",
                      raw)
        self.assertIn(f"composition.recorder: prompt/{self.recorder.RECORDER_PROMPT}",
                      raw)

    def test_the_recorder_ships_in_framework_files(self):
        manifest = json.loads(
            (ROOT / "system" / "version.json").read_text(encoding="utf-8"))
        for path in ("system/landmark_recorder.py",
                     "interactions/landmarks/prompt/recorder.md",
                     "docs/adr/0028-the-landmark-recorder.md"):
            with self.subTest(path=path):
                self.assertIn(path, manifest["framework_files"])

    def test_the_recorder_offers_only_keys_the_domain_can_read(self):
        """v211's `DOMAIN_AGNOSTIC_FIELDS`, from the writer's side.

        Both shapes it names are live founder shapes that validate, store,
        and are read by nothing: a `span` on `children`, whose ladder has no
        span, and a `label` on `birth`, whose ladder names no subject. The
        recorder is never told it may write either.
        """
        children = self.recorder.recordable_keys(li.domain_row("children"))
        self.assertNotIn("span", children)
        self.assertIn("who", children)
        self.assertIn("label", children)
        birth = self.recorder.recordable_keys(li.domain_row("birth"))
        self.assertNotIn("label", birth)
        self.assertNotIn("subject", birth)
        self.assertNotIn("span", birth)
        self.assertIn("date", birth)
        for field in li.DOMAIN_AGNOSTIC_FIELDS:
            for row in li.load_questions():
                if field in self.recorder.recordable_keys(row):
                    with self.subTest(field=field, domain=row["domain"]):
                        self.assertTrue(
                            any(field in li.rung_satisfiers(row, rung)
                                for rung in row["ladder"]),
                            f"{row['domain']} is offered {field} but no rung "
                            "of its ladder reads it",
                        )

    def test_recordable_keys_are_exactly_the_ladders_satisfiers(self):
        """The reconciliation (v212 onto v211): ONE declaration, not two.

        What the recorder may WRITE is derived from
        `landmarks_interaction.rung_satisfiers` — the same list the
        ladder-consistency guard walks on the READ side — intersected with
        what `validate_landmark` will actually keep for that domain. Nothing
        else may appear as a rung field, and no satisfier the validator keeps
        may go unoffered.
        """
        extras = {"domain", "subject", "birth_order", "skipped", "none",
                  "chain_complete"}
        for row in li.load_questions():
            offered = set(self.recorder.recordable_keys(row))
            satisfiers = set()
            for rung in row["ladder"]:
                if rung == li.NONE_OPENER:
                    continue
                satisfiers |= set(li.rung_satisfiers(row, rung))
            with self.subTest(domain=row["domain"]):
                self.assertFalse(
                    offered - satisfiers - extras,
                    f"{row['domain']} offers a field no rung satisfies",
                )
                storable = {f for f in satisfiers
                            if self.recorder._survives(row["domain"], f)}  # noqa: SLF001
                self.assertEqual(
                    offered & satisfiers, storable,
                    f"{row['domain']}: offered rung fields must be exactly "
                    "the satisfiers the validator keeps",
                )
                # `happened` is entailed by a SHAPE, not a field, so it is
                # never offered — v211's own statement of the same rule.
                self.assertNotIn(li.NONE_OPENER, offered)

    def test_a_field_the_validator_drops_is_never_offered(self):
        """`name` satisfies any identity rung on READ, and is dropped on WRITE.

        `identity_named` looks in `label` OR `name`, so `rung_satisfiers`
        lists both — but `validate_landmark` stores a rung key only when it
        is that domain's own rung, so a `name` filed on `children` never
        survives. Offering it would manufacture exactly the class this fixes.
        """
        self.assertIn("name", li.rung_satisfiers(li.domain_row("children"),
                                                 "who"))
        self.assertFalse(self.recorder._survives("children", "name"))  # noqa: SLF001
        self.assertNotIn("name",
                         self.recorder.recordable_keys(li.domain_row("children")))
        # On `schools` it IS the rung's own key, so it is offered.
        self.assertIn("name",
                      self.recorder.recordable_keys(li.domain_row("schools")))

    def test_every_offered_key_survives_validation(self):
        """Nothing the recorder is told to write is dropped downstream."""
        samples = {
            "who": "Jackie", "relation": "sibling", "living": True,
            "label": "Jackie", "subject": "my sister", "city": "Dayton",
            "address": "14 Bell Avenue", "household": "Mom and Dad",
            "name": "Fairview Elementary", "place": "Dayton",
            "grades": "K-6", "what": "linotype operator", "where": "Dayton",
            "branch": "Navy", "birth_order": "two years older",
            "year": "1978", "month": "April", "day": "12", "birth": "1976",
        }
        for row in li.load_questions():
            keys = self.recorder.recordable_keys(row)
            emitted: dict = {"domain": row["domain"]}
            for key in keys:
                if key in samples:
                    emitted[key] = samples[key]
            if len(emitted) == 1:
                continue
            with self.subTest(domain=row["domain"]):
                validated = li.validate_landmark(
                    engine._parse_landmark(emitted))  # noqa: SLF001
                self.assertIsNotNone(validated)
                for key in emitted:
                    self.assertIn(key, validated,
                                  f"{row['domain']} loses {key} in validation")

    def test_an_offered_record_actually_climbs_its_ladder(self):
        """The end the whole class exists for: the row stops re-asking.

        A leaf-shaped record built ONLY from the keys this domain is offered
        must reach a rung — the failure mode v211 fixed on the read side was
        a perfect answer reaching `None` and the row re-asking its own
        opening question forever.
        """
        samples = {
            "who": "Jackie", "label": "Jackie", "city": "Dayton",
            "name": "Fairview Elementary", "what": "linotype operator",
            "branch": "Navy", "year": "1978",
        }
        for row in li.load_questions():
            emitted = {"domain": row["domain"]}
            emitted.update({k: samples[k]
                            for k in self.recorder.recordable_keys(row)
                            if k in samples})
            if len(emitted) == 1:
                continue
            with self.subTest(domain=row["domain"]):
                record = li.validate_landmark(
                    engine._parse_landmark(emitted))  # noqa: SLF001
                self.assertIsNotNone(li.rung_reached(record, row),
                                     f"{row['domain']} reaches no rung")

    def test_the_leaf_names_the_readable_keys(self):
        prompt = self._prompt(domain="children",
                              question_asked="Do you have children?")
        self.assertIn("THE ONLY KEYS THIS DOMAIN CAN READ:", prompt)
        self.assertIn("Use only the keys listed above", prompt)
        self.assertNotIn("span", prompt.split("CAN THIS DOMAIN")[0])

    def test_only_the_family_ladder_offers_birth_order(self):
        for row in li.load_questions():
            with self.subTest(domain=row["domain"]):
                offered = "birth_order" in self.recorder.recordable_keys(row)
                self.assertEqual(offered, row["domain"] == "family")


class ManyRecordsTests(unittest.TestCase):
    """v214 / lifehug#227 — one answer, MANY records.

    Two live failures on the founder's own vault, 2026-08-25, both of them
    the same sentence: *one answer can carry many entries and the recorder
    could file one*. The work question was answered with a whole working
    life; v212's output held a single `landmark`, both attempts degraded, and
    the entire answer was WITHHELD. The children question was answered with
    four names and four exact birth dates; they were collapsed into one
    aggregate entry carrying a `span` that `children`'s ladder cannot even
    read, and the ladder went on asking who they were.
    """

    FIXTURE = (ROOT / "interactions" / "landmarks" / "evals" / "goldens"
               / "landmark-many-records-01.json")

    def setUp(self) -> None:
        import landmark_recorder as recorder  # noqa: PLC0415

        self.recorder = recorder
        data = json.loads(self.FIXTURE.read_text(encoding="utf-8"))
        self.assertEqual(data["fixture_id"], "landmark-many-records-01")
        self.cases = {case["case_id"]: case for case in data["cases"]}

    def _drive(self, case: dict, raws: list[str] | None = None):
        if raws is None:
            raws = [case["attempt"]["raw"]]
            if "regenerated" in case:
                raws.append(case["regenerated"]["raw"])
        seen: list[str] = []

        def _call(prompt: str, model: str) -> str:
            seen.append(prompt)
            return raws[min(len(seen), len(raws)) - 1]

        outcome = self.recorder.record_answer(
            domain=case["domain"], answer=case["user_message"],
            reply=case["reply"], call=_call,
        )
        return outcome, seen

    # -- the golden, end to end -------------------------------------------

    def test_every_golden_case_records_every_entry(self):
        for case_id, case in self.cases.items():
            with self.subTest(case=case_id):
                outcome, seen = self._drive(case)
                self.assertEqual(outcome.status, self.recorder.STATUS_RECORDED)
                self.assertEqual(list(outcome.records),
                                 case["expected_landmarks"])
                self.assertEqual(outcome.attempts, case["expected_attempts"])
                self.assertEqual(len(seen), case["expected_attempts"])
                # `record` is still the first of them, for every v212 caller.
                self.assertEqual(outcome.record, case["expected_landmarks"][0])

    def test_the_work_answer_that_was_withheld_now_files_every_job(self):
        """The first live failure: a working life, one record, withheld."""
        case = self.cases["work-twelve-jobs-recorded-as-one"]
        outcome, seen = self._drive(case)
        self.assertEqual(len(outcome.records), 6)
        self.assertEqual([r["label"] for r in outcome.records],
                         ["Harlow's", "Kessler", "Danforth Steel",
                          "Verity Tool", "Bramwell Freight",
                          "Ashby Community College"])
        # The retry is what made the difference, and only the SECOND prompt
        # carries the reminder.
        self.assertNotIn("One record per entry: send", seen[0].split(
            "Never invent a place")[-1])
        self.assertIn(li.many_records_reminder("work", 1), seen[1])

    def test_the_four_children_land_as_four_dated_entries(self):
        """The second live failure: four birth dates, one aggregate row."""
        case = self.cases["children-four-collapsed-into-one-aggregate"]
        outcome, _ = self._drive(case)
        self.assertEqual(len(outcome.records), 4)
        row = li.domain_row("children")
        for record in outcome.records:
            with self.subTest(child=record["label"]):
                self.assertEqual(record["date"]["granularity"], "day")
                self.assertEqual(li.rung_reached(record, row), "month")
        # The ladder reads them per ENTRY, so the domain is finished and the
        # question does not come back.
        self.assertEqual(li.status_for_domain(list(outcome.records), row),
                         "complete")
        self.assertIsNone(li.next_rung(list(outcome.records), row))

    def test_one_invalid_record_drops_alone(self):
        """Both layers run PER RECORD: a bad sibling never costs a good one."""
        case = self.cases["losses-one-invalid-record-drops-alone"]
        first = self.recorder.parse_recorder_output(case["attempt"]["raw"])
        self.assertEqual(list(first), case["attempt_landmarks"])
        self.assertEqual(len(first), 2)
        self.assertEqual([r["label"] for r in first],
                         ["Needy Beecham", "James Edwin Thorne"])
        # Three were sent; the middle one carried a key no landmark holds.
        self.assertEqual(len(json.loads(case["attempt"]["raw"])["landmarks"]), 3)

    # -- the boundary ------------------------------------------------------

    def test_a_single_entry_answer_never_retries(self):
        for case_id in ("one-fact-is-still-one-record",
                        "a-none-is-one-record-and-never-plural"):
            with self.subTest(case=case_id):
                outcome, seen = self._drive(self.cases[case_id])
                self.assertEqual(len(seen), 1)
                self.assertEqual(outcome.lint_ids, ())

    def test_a_terminal_is_never_plural_however_many_names_ride_along(self):
        """The mission story names Zurich AND Switzerland; the answer is a no."""
        case = self.cases["a-none-is-one-record-and-never-plural"]
        self.assertIsNone(li.records_missing_entries(
            case["user_message"], [{"domain": "military", "none": True}],
            reply=case["reply"], domain="military"))
        self.assertIsNone(li.records_missing_entries(
            case["user_message"], [{"domain": "military", "skipped": True}],
            reply=case["reply"], domain="military"))

    def test_one_uncovered_name_alone_is_never_evidence(self):
        """A qualifier is not a second entry: "Dayton, Ohio" is one place."""
        self.assertIsNone(li.records_missing_entries(
            "We lived on Bell Avenue in Dayton, Ohio.",
            [{"domain": "residences", "label": "Bell Avenue",
              "city": "Dayton", "address": "Bell Avenue"}],
            reply="Bell Avenue in Dayton.", domain="residences"))

    def test_a_domain_with_no_identity_rung_is_never_plural(self):
        """`birth` is one person and one birthday, whatever the message says."""
        self.assertIsNone(li.identity_rung(li.domain_row("birth")))
        self.assertIsNone(li.records_missing_entries(
            "I was born in Akron in 1952, my brother Wendell in 1955.",
            [{"domain": "birth", "date": {"best": "1952"}}],
            reply="Akron, 1952.", domain="birth"))

    def test_nothing_recorded_is_the_other_classs_question(self):
        """Two classes, two questions, no overlap."""
        message = "Corinne, Maddox, Sela and Ivo."
        self.assertIsNone(li.records_missing_entries(
            message, [], domain="children", reply=message))
        self.assertIsNotNone(li.answer_must_record(
            message, (), reply=message, domain="children"))
        # And ANY one valid record answers `answer_must_record`, whatever the
        # many-records class then says about the rest.
        self.assertIsNone(li.answer_must_record(
            message, ({"domain": "children", "label": "Corinne"},),
            reply=message, domain="children"))

    def test_unrecorded_years_are_evidence_only_where_entries_date_separately(self):
        """A `span` domain legitimately states two years for ONE entry.

        v219: the judgment moved off the LADDER and onto `date_semantics`,
        which is the field that states it — the answers are unchanged and
        this test is the pin that says so.
        """
        self.assertFalse(li.dates_each_entry(li.domain_row("residences")))
        self.assertFalse(li.dates_each_entry(li.domain_row("work")))
        self.assertFalse(li.dates_each_entry(li.domain_row("military")))
        for domain in ("birth", "children", "family", "losses", "partnerships"):
            with self.subTest(domain=domain):
                self.assertTrue(li.dates_each_entry(li.domain_row(domain)))
        self.assertIsNone(li.records_missing_entries(
            "I was at the mill from 1971 to 1994.",
            [{"domain": "work", "label": "the mill", "what": "the mill",
              "span": {"start": {"best": "1971"}, "end": {"best": "1994"}}}],
            reply="The mill, 1971 to 1994.", domain="work"))

    # -- the retry is bounded, and it never costs a record -----------------

    def test_a_still_plural_retry_files_what_it_has_and_never_withholds(self):
        case = self.cases["work-twelve-jobs-recorded-as-one"]
        outcome, seen = self._drive(case, [case["attempt"]["raw"]])
        self.assertEqual(len(seen), self.recorder.MAX_ATTEMPTS)
        self.assertEqual(outcome.status, self.recorder.STATUS_RECORDED)
        self.assertEqual(outcome.lint_ids, (li.RECORD_EVERY_ENTRY_LINT,))
        self.assertEqual(len(outcome.records), 1)
        self.assertIn("came back", outcome.reason)

    def test_a_shrinking_retry_never_loses_the_larger_set(self):
        case = self.cases["work-twelve-jobs-recorded-as-one"]
        outcome, _ = self._drive(
            case, [case["regenerated"]["raw"], '{"landmarks": []}'])
        self.assertEqual(len(outcome.records), 6)
        self.assertEqual(outcome.status, self.recorder.STATUS_RECORDED)

    def test_a_provider_failure_on_the_retry_files_what_it_has(self):
        case = self.cases["work-twelve-jobs-recorded-as-one"]
        calls: list[str] = []

        def _call(prompt: str, model: str) -> str:
            calls.append(prompt)
            if len(calls) > 1:
                raise RuntimeError("no provider")
            return case["attempt"]["raw"]

        outcome = self.recorder.record_answer(
            domain="work", answer=case["user_message"], reply=case["reply"],
            call=_call)
        self.assertEqual(outcome.status, self.recorder.STATUS_RECORDED)
        self.assertEqual(len(outcome.records), 1)
        self.assertIn("no provider", outcome.reason)

    def test_the_reminder_asks_for_the_list_and_forbids_padding_it(self):
        reminder = li.many_records_reminder("children", 1)
        self.assertIn('"landmarks"', reminder)
        self.assertIn("never invent an entry", reminder)
        self.assertIn("never split one entry into two", reminder)
        self.assertIn("(`children`)", reminder)

    # -- filing: one entry per record --------------------------------------

    def test_four_children_file_as_four_entries_and_retire_the_aggregate(self):
        import timeline  # noqa: PLC0415

        case = self.cases["children-four-collapsed-into-one-aggregate"]
        tmp = root_parent_tmp(self, ROOT)
        store = tmp / "landmarks.json"
        with mock.patch.object(timeline, "LANDMARKS_STORE", store):
            # The founder's vault, as it actually stood: ONE aggregate entry
            # with a span the ladder cannot read.
            timeline.save_landmark("children", {
                "domain": "children", "label": "our four",
                "span": {"start": chrono.parse_edtf("1979").to_dict(),
                         "end": chrono.parse_edtf("1990").to_dict()}})
            self.assertEqual(len(timeline.load_landmarks()["children"]), 1)
            outcome, _ = self._drive(case)
            saved = timeline.save_landmarks("children", outcome.records)
            entries = timeline.load_landmarks()["children"]
        self.assertEqual(len(saved), 4)
        self.assertEqual([e["label"] for e in entries],
                         ["Corinne", "Maddox", "Sela", "Ivo"])
        self.assertNotIn("our four", [e.get("label") for e in entries])

    def test_a_named_entry_the_person_gave_is_never_retired(self):
        import timeline  # noqa: PLC0415

        tmp = root_parent_tmp(self, ROOT)
        store = tmp / "landmarks.json"
        with mock.patch.object(timeline, "LANDMARKS_STORE", store):
            timeline.save_landmark("children", {"domain": "children",
                                                "label": "Corinne",
                                                "who": "Corinne"})
            timeline.save_landmark("children", {"domain": "children",
                                                "label": "Maddox",
                                                "who": "Maddox"})
            entries = timeline.load_landmarks()["children"]
        self.assertEqual([e["label"] for e in entries], ["Corinne", "Maddox"])

    def test_who_only_records_do_not_collapse_onto_one_another(self):
        """The label-keyed store's own defect: four `who`s, one entry."""
        import timeline  # noqa: PLC0415

        row = li.domain_row("children")
        keys = {li.landmark_entry_key({"domain": "children", "who": name}, row)
                for name in ("Corinne", "Maddox", "Sela", "Ivo")}
        self.assertEqual(len(keys), 4)
        tmp = root_parent_tmp(self, ROOT)
        store = tmp / "landmarks.json"
        with mock.patch.object(timeline, "LANDMARKS_STORE", store):
            for name in ("Corinne", "Maddox", "Sela", "Ivo"):
                timeline.save_landmark("children", {"domain": "children",
                                                    "who": name})
            entries = timeline.load_landmarks()["children"]
        self.assertEqual(len(entries), 4)

    def test_the_entry_key_is_the_read_sides_own_identity_order(self):
        row = li.domain_row("residences")
        self.assertEqual(li.IDENTITY_FIELDS, ("label", "name"))
        self.assertEqual(
            li.landmark_entry_key({"label": "Bell Avenue", "city": "Dayton"},
                                  row), "bell avenue")
        self.assertEqual(
            li.landmark_entry_key({"city": "Dayton"}, row), "dayton")
        # Case-folded: one place, one entry.
        self.assertEqual(li.landmark_entry_key({"label": "BELL AVENUE"}, row),
                         li.landmark_entry_key({"label": "bell avenue"}, row))
        # No identity at all still keys on "", which is right for `birth`.
        self.assertEqual(
            li.landmark_entry_key({"domain": "birth"}, li.domain_row("birth")),
            "")

    def test_a_none_retires_every_entry_in_its_domain(self):
        import timeline  # noqa: PLC0415

        tmp = root_parent_tmp(self, ROOT)
        store = tmp / "landmarks.json"
        with mock.patch.object(timeline, "LANDMARKS_STORE", store):
            timeline.save_landmark("children", {"domain": "children",
                                                "label": "Corinne",
                                                "who": "Corinne"})
            timeline.save_landmark("children", {"domain": "children",
                                                "label": "Maddox",
                                                "who": "Maddox"})
            timeline.save_landmark("children", {"domain": "children",
                                                "none": True})
            entries = timeline.load_landmarks()["children"]
        self.assertEqual(entries, [{"domain": "children", "none": True}])

    def test_a_substantive_record_clears_a_standing_terminal(self):
        import timeline  # noqa: PLC0415

        tmp = root_parent_tmp(self, ROOT)
        store = tmp / "landmarks.json"
        with mock.patch.object(timeline, "LANDMARKS_STORE", store):
            timeline.save_landmark("children", {"domain": "children",
                                                "none": True})
            timeline.save_landmark("children", {"domain": "children",
                                                "label": "Corinne",
                                                "who": "Corinne"})
            entries = timeline.load_landmarks()["children"]
        self.assertEqual([e["label"] for e in entries], ["Corinne"])

    def test_one_invocation_per_entry_and_no_aggregate_form(self):
        case = self.cases["children-four-collapsed-into-one-aggregate"]
        outcome, _ = self._drive(case)
        argvs = li.landmark_invocations(outcome.records)
        self.assertEqual(len(argvs), 4)
        for argv, record in zip(argvs, outcome.records):
            with self.subTest(child=record["label"]):
                self.assertEqual(argv[:2], ["landmark-record", "children"])
                self.assertIn(record["label"], argv)
                self.assertIn("--date", argv)
        # A skip files nothing, and its siblings still file.
        self.assertEqual(li.landmark_invocations(
            [{"domain": "children", "skipped": True},
             {"domain": "children", "label": "Ivo", "who": "Ivo"}]),
            [["landmark-record", "children", "--label", "Ivo", "--who", "Ivo"]])

    # -- where the class lives ---------------------------------------------

    def test_the_class_is_the_recorders_and_not_the_replys(self):
        """The turn's own `landmark` field is singular by its pinned contract.

        Failing a turn for recording one entry of three would fail it for
        obeying the only contract it has. The plural output belongs to the
        recorder, so the class that reads it does too — which is why this one
        is NOT in `LANDMARK_LINT_CLASSES` and its sibling is.
        """
        self.assertNotIn(li.RECORD_EVERY_ENTRY_LINT, li.LANDMARK_LINT_CLASSES)
        self.assertIn(li.ANSWER_MUST_RECORD_LINT, li.LANDMARK_LINT_CLASSES)
        self.assertEqual(li.RECORD_EVERY_ENTRY_LINT,
                         "landmark_gates.record_every_entry")
        case = self.cases["losses-one-invalid-record-drops-alone"]
        self.assertEqual(
            [f["lint"] for f in li.lint_landmark_reply(
                case["reply"], stage="ask", domain="losses", sensitive=True,
                landmark={"domain": "losses", "label": "Needy Beecham"},
                user_message=case["user_message"])],
            [])

    def test_the_reply_goldens_own_losses_turn_shows_why(self):
        """The v212 reference transcript, read with v214's eyes.

        Its person names three people and its expected turn field carries
        one, because one is all a turn field can carry. That is the whole
        case for a separate recorder pass with a plural output.
        """
        fixture = next(f for f in landmarks_evals.load_fixtures()
                       if f["fixture_id"]
                       == "landmarks-losses-are-recorded-not-only-received")
        turn = next(t for t in fixture["turns"] if t.get("user_message"))
        finding = li.records_missing_entries(
            turn["user_message"], turn["expected_landmark"],
            domain=turn["domain"])
        self.assertIsNotNone(finding)
        self.assertEqual(finding["lint"], li.RECORD_EVERY_ENTRY_LINT)

    def test_the_leaf_teaches_the_list_shape_with_a_worked_example(self):
        leaf = self.recorder.load_recorder_leaf()
        self.assertIn('{"landmarks": [', leaf)
        self.assertIn("One record per entry, and every entry they stated",
                      leaf)
        self.assertIn("THEY SAID:", leaf)
        self.assertIn("Three things they said, three records", leaf)
        self.assertNotIn("take the FIRST person they named", leaf)

    def test_the_new_golden_ships_in_framework_files(self):
        manifest = json.loads(
            (ROOT / "system" / "version.json").read_text(encoding="utf-8"))
        self.assertIn(
            "interactions/landmarks/evals/goldens/"
            "landmark-many-records-01.json",
            manifest["framework_files"])


class KnownEntriesTests(unittest.TestCase):
    """v216 / lifehug#230 — the recorder knows what it already knows.

    The design audit's D7. Since v212 the recorder's leaf has carried the
    heading *"ALREADY KNOWN — never record these again"* over a block that
    named DOMAIN STATUSES — `- children: partial (4)` — and a store dict, the
    shape every real caller holds, rendered as "(nothing yet)". A model cannot
    decline to re-file four children it has never been shown. `known_labels`,
    which both recording lints take, was hand-passed and therefore empty
    everywhere, so a person going back over their own life had their own filed
    names read back as fresh evidence.
    """

    FIXTURE = (ROOT / "interactions" / "landmarks" / "evals" / "goldens"
               / "landmark-known-entries-01.json")

    def setUp(self) -> None:
        import landmark_recorder as recorder  # noqa: PLC0415

        self.recorder = recorder
        data = json.loads(self.FIXTURE.read_text(encoding="utf-8"))
        self.assertEqual(data["fixture_id"], "landmark-known-entries-01")
        self.cases = {case["case_id"]: case for case in data["cases"]}

    def _drive(self, case: dict):
        seen: list[str] = []

        def _call(prompt: str, model: str) -> str:
            seen.append(prompt)
            return case["attempt"]["raw"]

        outcome = self.recorder.record_answer(
            domain=case["domain"], answer=case["user_message"],
            reply=case["reply"], landmarks=case["landmarks"], call=_call)
        return outcome, seen

    # -- the golden, end to end -------------------------------------------

    def test_every_golden_case_files_only_what_is_new(self):
        for case_id, case in self.cases.items():
            with self.subTest(case=case_id):
                outcome, seen = self._drive(case)
                self.assertEqual(outcome.status, case["expected_status"])
                self.assertEqual(list(outcome.records),
                                 case["expected_landmarks"])
                self.assertEqual(outcome.attempts, case["expected_attempts"])
                self.assertEqual(len(seen), case["expected_attempts"])
                self.assertEqual(outcome.lint_ids, ())

    def test_the_prompt_names_the_entries_not_the_domains_status(self):
        """The whole defect, in one assertion."""
        case = self.cases["children-re-answered-with-nothing-new"]
        _, seen = self._drive(case)
        block = seen[0].split("ALREADY FILED FOR THIS DOMAIN")[1]
        block = block.split("WHAT THEY SAID:")[0]
        for name in ("Corinne", "Maddox", "Sela", "Ivo"):
            self.assertIn(name, block)
        # The status row that was there before says nothing a model can act on.
        self.assertNotIn("children: partial", seen[0])

    def test_the_restatement_would_have_withheld_without_it(self):
        """Why this is a defect and not a nicety: the counterfactual.

        With no known labels, the four names coming back in the reply are read
        as the person's own fresh evidence, the blocking lint fires, and the
        answer costs a regeneration and comes back WITHHELD.
        """
        case = self.cases["children-re-answered-with-nothing-new"]
        self.assertIsNotNone(li.answer_must_record(
            case["user_message"], (), reply=case["reply"], domain="children"))
        self.assertIsNone(li.answer_must_record(
            case["user_message"], (), reply=case["reply"], domain="children",
            known_labels=li.known_entry_labels(case["landmarks"], "children")))

    def test_the_leaf_teaches_the_rule_the_heading_only_ever_claimed(self):
        leaf = self.recorder.load_recorder_leaf()
        self.assertIn("{known_entries}", leaf)
        self.assertIn("Never record an entry that is already filed above",
                      leaf)
        self.assertIn("finer date than the one shown", leaf)
        self.assertNotIn("{landmarks}\n", leaf)

    # -- ONE derivation, three consumers -----------------------------------

    def test_the_labels_and_the_block_come_from_the_same_entries(self):
        case = self.cases["children-re-answered-with-nothing-new"]
        labels = li.known_entry_labels(case["landmarks"], "children")
        self.assertEqual(labels, ("Corinne", "Maddox", "Sela", "Ivo"))
        block = li.render_known_entries(case["landmarks"], "children")
        for label in labels:
            self.assertIn(label, block)

    def test_a_name_filed_only_under_the_identity_rung_is_still_known(self):
        """The founder's four children were filed as `who` with no `label`."""
        row = li.domain_row("children")
        entry = {"domain": "children", "who": "Wren"}
        self.assertIsNone(li.identity_named(entry, row))
        self.assertEqual(li.entry_name(entry, row), "Wren")
        self.assertEqual(li.known_entry_labels({"children": [entry]},
                                               "children"), ("Wren",))

    def test_a_placeholder_label_is_a_merge_key_but_never_a_name(self):
        row = li.domain_row("residences")
        entry = {"domain": "residences", "label": "unknown"}
        self.assertEqual(li.landmark_entry_key(entry, row), "unknown")
        self.assertIsNone(li.entry_name(entry, row))
        self.assertIn("(unnamed)", li.render_entry(entry, row))

    def test_extra_labels_are_unioned_in_and_the_first_spelling_wins(self):
        entries = [{"domain": "children", "label": "Corinne"}]
        self.assertEqual(
            li.known_entry_labels({"children": entries}, "children",
                                  extra=("corinne", "Wren")),
            ("Corinne", "Wren"))

    def test_the_store_and_a_selected_list_read_the_same(self):
        entries = [{"domain": "children", "label": "Corinne"}]
        self.assertEqual(li.landmark_entries({"children": entries},
                                             "children"),
                         li.landmark_entries(entries, "children"))
        self.assertEqual(li.landmark_entries({"children": entries}, "work"),
                         ())
        self.assertEqual(li.landmark_entries(None, "children"), ())

    # -- the block itself ---------------------------------------------------

    def test_an_empty_domain_says_so_rather_than_pretending(self):
        self.assertEqual(li.render_known_entries({}, "children"),
                         li.NO_KNOWN_ENTRIES)

    def test_the_block_is_bounded_and_says_how_many_it_did_not_name(self):
        entries = [{"domain": "work", "label": f"Job {n}", "what": "work"}
                   for n in range(li.KNOWN_ENTRIES_LIMIT + 3)]
        block = li.render_known_entries({"work": entries}, "work")
        self.assertEqual(len(block.splitlines()), li.KNOWN_ENTRIES_LIMIT + 1)
        self.assertIn("…and 3 more already filed", block)

    def test_a_domain_with_no_subject_renders_the_date_alone(self):
        row = li.domain_row("birth")
        self.assertIsNone(li.identity_rung(row))
        self.assertEqual(li.render_entry({"domain": "birth",
                                          "date": _date("1952")}, row),
                         "- 1952")

    def test_the_two_terminals_say_what_they_are(self):
        military = li.domain_row("military")
        self.assertIn("never happened",
                      li.render_entry({"domain": "military", "none": True},
                                      military))
        self.assertIn("declined",
                      li.render_entry({"domain": "military", "skipped": True},
                                      military))

    def test_an_undated_entry_says_so_rather_than_inventing_one(self):
        row = li.domain_row("children")
        self.assertEqual(
            li.render_entry({"domain": "children", "label": "Wren"}, row),
            "- Wren — no date filed")

    # -- the store-side backstop -------------------------------------------

    def test_merging_a_record_already_filed_changes_nothing(self):
        """Whatever the model repeats anyway lands on the same entry."""
        case = self.cases["children-re-answered-with-nothing-new"]
        for entry in case["landmarks"]["children"]:
            with self.subTest(entry=entry["label"]):
                self.assertEqual(li.merge_landmark_entry(entry, entry), entry)
                self.assertEqual(li.merge_landmark_entry(entry, dict(entry)),
                                 entry)

    def test_a_repeated_record_never_becomes_a_second_entry(self):
        import timeline  # noqa: PLC0415

        case = self.cases["children-re-answered-with-nothing-new"]
        tmp = root_parent_tmp(self, ROOT)
        store = tmp / "landmarks.json"
        with mock.patch.object(timeline, "LANDMARKS_STORE", store):
            timeline.save_landmarks("children", case["landmarks"]["children"])
            first = timeline.load_landmarks()["children"]
            timeline.save_landmarks("children", case["landmarks"]["children"])
            second = timeline.load_landmarks()["children"]
        self.assertEqual(len(first), 4)
        self.assertEqual(second, first)

    def test_a_finer_date_refines_the_entry_it_names(self):
        import timeline  # noqa: PLC0415

        case = self.cases["children-a-finer-date-is-not-a-duplicate"]
        tmp = root_parent_tmp(self, ROOT)
        store = tmp / "landmarks.json"
        with mock.patch.object(timeline, "LANDMARKS_STORE", store):
            timeline.save_landmarks("children", case["landmarks"]["children"])
            outcome, _ = self._drive(case)
            timeline.save_landmarks("children", outcome.records)
            entries = timeline.load_landmarks()["children"]
        self.assertEqual(len(entries), 4)
        sela = next(e for e in entries if e["label"] == "Sela")
        self.assertEqual(sela["date"]["granularity"], "day")
        self.assertEqual(li.rung_reached(sela, li.domain_row("children")),
                         "month")

    def test_the_new_golden_ships_in_framework_files(self):
        manifest = json.loads(
            (ROOT / "system" / "version.json").read_text(encoding="utf-8"))
        self.assertIn(
            "interactions/landmarks/evals/goldens/"
            "landmark-known-entries-01.json",
            manifest["framework_files"])


class ProvenanceSurvivesTests(unittest.TestCase):
    """B4: basis, anchors and provenance survive the WHOLE path.

    The traced defect chain, closed end to end:
    ``conversation_delivery._parse_landmark_date`` allowlisted ``anchors`` and
    ``provenance`` and then dropped them; ``landmark_invocation`` serialized
    the EDTF expression alone; ``lifehug.cmd_landmark_record`` rebuilt every
    date with ``basis="stated"`` and an empty provenance. A date the system
    CALCULATED from an age therefore reached the vault claiming the person had
    STATED it — and `chronology.claim_score` paid it for the difference.
    """

    def setUp(self):
        self.calculated = chrono.DateRecord(
            best="1984", earliest="1984", latest="1984", granularity="year",
            confidence="approximate", basis="age", anchors=("birth",),
            provenance=({"claim": "about five", "basis": "age",
                         "source": "A12"},),
        ).to_dict()

    def _file(self, store, entry):
        """Run the package's own invocation through the real CLI."""
        import lifehug  # noqa: PLC0415
        import timeline  # noqa: PLC0415

        argv = li.landmark_invocation(entry)
        self.assertIsNotNone(argv)
        args = lifehug.build_parser().parse_args(argv)
        with mock.patch.object(timeline, "LANDMARKS_STORE", store):
            self.assertEqual(lifehug.cmd_landmark_record(args), 0)
            return timeline.load_landmarks()

    # -- the round trip ---------------------------------------------------

    def test_a_calculated_date_reaches_the_store_byte_faithfully(self):
        store = root_parent_tmp(self, ROOT) / "landmarks.json"
        filed = self._file(store, {"domain": "residences", "label": "Mesa",
                                   "city": "Mesa", "date": self.calculated})
        self.assertEqual(filed["residences"][0]["date"], self.calculated)

    def test_each_end_of_a_span_keeps_its_own_warrant(self):
        store = root_parent_tmp(self, ROOT) / "landmarks.json"
        moved_out = _date("1991", basis="stated")
        filed = self._file(store, {
            "domain": "residences", "label": "Bell Avenue", "city": "Mesa",
            "span": {"start": self.calculated, "end": moved_out}})
        span = filed["residences"][0]["span"]
        self.assertEqual(span["start"], self.calculated)
        self.assertEqual(span["end"], moved_out)
        self.assertEqual(span["start"]["basis"], "age")
        self.assertEqual(span["end"]["basis"], "stated")

    def test_the_recorder_output_carries_the_warrant_to_the_writer(self):
        """`_parse_landmark_date` used to allowlist these and drop them."""
        parsed = engine._parse_landmark({
            "domain": "residences", "label": "Mesa", "city": "Mesa",
            "date": self.calculated})
        self.assertEqual(parsed["date"]["anchors"], ["birth"])
        self.assertEqual(parsed["date"]["provenance"],
                         [{"claim": "about five", "basis": "age",
                           "source": "A12"}])
        self.assertEqual(li.validate_landmark(parsed)["date"], self.calculated)

    def test_an_over_long_or_malformed_warrant_degrades_and_never_errors(self):
        base = {"best": "1984", "earliest": "1984", "latest": "1984"}
        for bad in ({"provenance": "not a list"}, {"anchors": {"a": 1}}):
            with self.subTest(**bad):
                self.assertIsNone(engine._parse_landmark_date({**base, **bad}))
        loose = engine._parse_landmark_date(
            {**base, "provenance": [{"claim": "x" * 500}, {}, "junk"]})
        self.assertEqual(loose.get("provenance"), None)

    def test_every_warrant_flag_the_invocation_emits_is_a_real_cli_flag(self):
        import lifehug  # noqa: PLC0415

        argv = li.landmark_invocation({
            "domain": "residences", "label": "Mesa", "city": "Mesa",
            "date": self.calculated,
            "span": {"start": self.calculated, "end": _date("1991")}})
        args = lifehug.build_parser().parse_args(argv)
        self.assertEqual(args.basis, "age")
        self.assertEqual(args.anchor, ["birth"])
        self.assertEqual(args.start_basis, "age")
        self.assertEqual(args.end_basis, "stated")

    # -- the inflation, pinned dead ---------------------------------------

    def test_a_calculated_date_can_no_longer_masquerade_as_stated(self):
        """The incident: +2.0 of `claim_score` the claim had not earned.

        Filed pre-v222, this record came back ``basis="stated",
        confidence="certain"`` — 10.0 — and outscored the very claim it was
        derived FROM. It now lands at its own 8.0, and a genuinely stated
        rival beats it, which is the whole point of a basis.
        """
        store = root_parent_tmp(self, ROOT) / "landmarks.json"
        filed = self._file(store, {"domain": "residences", "label": "Mesa",
                                   "city": "Mesa", "date": self.calculated})
        landed = filed["residences"][0]["date"]
        self.assertEqual(chrono.claim_score(landed),
                         chrono.claim_score(self.calculated))
        masquerade = dict(landed, basis="stated", confidence="certain")
        self.assertGreater(chrono.claim_score(masquerade),
                           chrono.claim_score(landed))
        stated_rival = _date("1986", basis="stated")
        self.assertEqual(chrono.reconcile([landed, stated_rival])["best_supported"],
                         chrono.from_dict(stated_rival))

    # -- reconcile's seat in the fold --------------------------------------

    def test_a_conflicting_re_record_retains_both_claims(self):
        store = root_parent_tmp(self, ROOT) / "landmarks.json"
        self._file(store, {"domain": "residences", "label": "Mesa",
                           "city": "Mesa", "date": self.calculated})
        stated = _date("1986", basis="stated")
        filed = self._file(store, {"domain": "residences", "label": "Mesa",
                                   "address": "12 Bell Ave", "date": stated})
        entry = filed["residences"][0]
        self.assertEqual(len(filed["residences"]), 1)
        # The better-supported claim displays...
        self.assertEqual(entry["date"], stated)
        # ...and the one it beat is still THERE, not overwritten.
        self.assertEqual(entry[li.DATE_ALTERNATES_KEY], [self.calculated])
        # The ordinary dict merge is untouched for everything else.
        self.assertEqual(entry["city"], "Mesa")
        self.assertEqual(entry["address"], "12 Bell Ave")
        read = li.landmark_date(entry)
        self.assertEqual(read["best_supported"], stated)
        self.assertEqual(read["alternates"], [self.calculated])
        self.assertGreater(read["conflict"], 0.0)

    def test_the_losing_claim_is_never_deleted_by_a_later_pass(self):
        store = root_parent_tmp(self, ROOT) / "landmarks.json"
        self._file(store, {"domain": "residences", "label": "Mesa",
                           "city": "Mesa", "date": self.calculated})
        self._file(store, {"domain": "residences", "label": "Mesa",
                           "date": _date("1986", basis="stated")})
        filed = self._file(store, {"domain": "residences", "label": "Mesa",
                                   "address": "12 Bell Ave"})
        entry = filed["residences"][0]
        self.assertEqual(entry["date"]["best"], "1986")
        self.assertEqual(entry[li.DATE_ALTERNATES_KEY], [self.calculated])

    def test_refiling_the_same_claim_does_not_accumulate_alternates(self):
        store = root_parent_tmp(self, ROOT) / "landmarks.json"
        for _ in range(4):
            filed = self._file(store, {"domain": "residences", "label": "Mesa",
                                       "city": "Mesa", "date": self.calculated})
        entry = filed["residences"][0]
        self.assertEqual(entry["date"], self.calculated)
        self.assertNotIn(li.DATE_ALTERNATES_KEY, entry)

    def test_a_refinement_replaces_rather_than_fights_its_coarser_claim(self):
        store = root_parent_tmp(self, ROOT) / "landmarks.json"
        self._file(store, {"domain": "residences", "label": "Mesa",
                           "city": "Mesa", "date": _date("1986")})
        filed = self._file(store, {"domain": "residences", "label": "Mesa",
                                   "date": _date("1986-06-14")})
        entry = filed["residences"][0]
        self.assertEqual(entry["date"]["best"], "1986-06-14")
        self.assertEqual(li.landmark_date(entry)["conflict"], 0.0)

    def test_silence_about_a_date_is_not_a_correction(self):
        merged = li.merge_landmark_entry(
            {"domain": "residences", "label": "Mesa", "date": self.calculated},
            {"domain": "residences", "label": "Mesa", "city": "Mesa"})
        self.assertEqual(merged["date"], self.calculated)
        self.assertEqual(merged["city"], "Mesa")

    def test_a_none_still_replaces_the_whole_entry(self):
        merged = li.merge_landmark_entry(
            {"domain": "military", "label": "Army", "date": self.calculated},
            {"domain": "military", "none": True})
        self.assertEqual(merged, {"domain": "military", "none": True})

    def test_the_alternates_keys_are_bookkeeping_no_rung_can_read(self):
        """Unnamed, they would feed `entry_superseded_by` and RETIRE entries."""
        for key in (li.DATE_ALTERNATES_KEY, li.SPAN_ALTERNATES_KEY):
            with self.subTest(key):
                self.assertIn(key, li.NON_RUNG_FIELDS)
        row = li.domain_row("residences")
        entry = {"domain": "residences", "label": "Mesa", "city": "Mesa",
                 "date": self.calculated,
                 li.DATE_ALTERNATES_KEY: [_date("1986")],
                 li.SPAN_ALTERNATES_KEY: {"start": [_date("1986")]}}
        self.assertEqual(li.unreadable_fields(entry, row), ())
        self.assertFalse(li.entry_superseded_by(
            entry, {"domain": "residences", "label": "Mesa", "city": "Mesa"}, row))

    def test_reading_a_date_off_an_entry_that_has_no_alternates(self):
        read = li.landmark_date({"domain": "residences", "date": self.calculated})
        self.assertEqual(read["best_supported"], self.calculated)
        self.assertEqual(read["alternates"], [])
        self.assertEqual(read["conflict"], 0.0)
        empty = li.landmark_date(None)
        self.assertIsNone(empty["best_supported"])
        self.assertIsNone(li.landmark_date({"domain": "residences"},
                                           bound="start")["best_supported"])


class AdditiveLadderFieldTests(unittest.TestCase):
    """E-L2c (design §3.2, §10.3): approximate, ongoing, place_ref, nickname,
    link — all additive, none gates an existing rung."""

    def test_approximate_sets_the_dates_own_confidence(self):
        record = li.validate_landmark({"domain": "residences", "label": "Mesa",
                                       "date": "1990", "approximate": True})
        self.assertEqual(record["date"]["confidence"], "approximate")
        self.assertEqual(record["date"]["granularity"], "year")

    def test_a_record_with_no_approximate_flag_stays_certain(self):
        record = li.validate_landmark({"domain": "residences", "label": "Mesa",
                                       "date": "1990"})
        self.assertEqual(record["date"]["confidence"], "certain")

    def test_approximate_reaches_each_span_end_independently(self):
        record = li.validate_landmark({
            "domain": "residences", "label": "Mesa",
            "span": {"start": "1990", "end": "1994", "start_approximate": True},
        })
        self.assertEqual(record["span"]["start"]["confidence"], "approximate")
        self.assertEqual(record["span"]["end"]["confidence"], "certain")

    def test_ongoing_is_kept_only_when_the_span_has_no_end(self):
        record = li.validate_landmark({
            "domain": "residences", "label": "Mesa",
            "span": {"start": "1990"}, "ongoing": True,
        })
        self.assertTrue(record["ongoing"])
        self.assertNotIn("end", record["span"])

    def test_ongoing_true_is_dropped_when_an_end_is_also_stated(self):
        # An entry cannot be both ongoing and ended; the stated end wins,
        # and `ongoing: true` never lands beside it.
        record = li.validate_landmark({
            "domain": "residences", "label": "Mesa",
            "span": {"start": "1990", "end": "1994"}, "ongoing": True,
        })
        self.assertNotIn("ongoing", record)

    def test_an_end_never_carries_ongoing_unless_asked(self):
        # An ordinary answer that never mentions `ongoing` at all leaves the
        # field untouched — no new key appears on a ladder answer this
        # release did not change the shape of.
        record = li.validate_landmark({
            "domain": "work", "label": "Etherfuse",
            "span": {"start": "2021", "end": "2024"},
        })
        self.assertNotIn("ongoing", record)

    def test_ongoing_false_explicitly_clears_a_stale_prior_marker(self):
        # `merge_landmark_entry`'s generic dict merge only overwrites a key
        # the incoming record actually carries — a caller CLOSING OUT a
        # previously-ongoing stay (Go Dig's own grammar, §10.6) says
        # `ongoing: false` explicitly, and only then does it land, so a
        # stale `true` from an earlier turn cannot survive the merge.
        record = li.validate_landmark({
            "domain": "work", "label": "Etherfuse",
            "span": {"start": "2021", "end": "2024"}, "ongoing": False,
        })
        self.assertIn("ongoing", record)
        self.assertFalse(record["ongoing"])

    def test_no_end_claim_is_ever_filed_for_an_ongoing_entry(self):
        record = li.validate_landmark({
            "domain": "work", "label": "Etherfuse",
            "span": {"start": "2021"}, "ongoing": True,
        })
        source_ref = {"source_id": "landmark:entry-test", "revision": "sha256:" + "0" * 64,
                      "source_path": "sources/landmarks/entry-test.md"}
        claims = lp.entry_claims("work", record, source_ref=source_ref)
        kinds = {c.get("event_kind") for c in claims}
        self.assertNotIn("ended", kinds)
        self.assertIn("started", kinds)

    def test_place_ref_is_kept_verbatim(self):
        record = li.validate_landmark({"domain": "residences", "label": "Mesa",
                                       "place_ref": "place/mesa-house"})
        self.assertEqual(record["place_ref"], "place/mesa-house")

    def test_a_nickname_with_no_parenthetical_binds_whole(self):
        record = li.validate_landmark({"domain": "residences", "label": "Mesa",
                                       "nickname": "The Fish House"})
        self.assertEqual(record["nickname"], "The Fish House")
        self.assertNotIn("note", record)

    def test_a_nickname_parenthetical_moves_to_the_note(self):
        record = li.validate_landmark({"domain": "residences", "label": "Mesa",
                                       "nickname": "The Blue House (rented)"})
        self.assertEqual(record["nickname"], "The Blue House")
        self.assertEqual(record["note"], "rented")

    def test_an_explicit_note_and_a_nickname_note_both_survive(self):
        record = li.validate_landmark({
            "domain": "residences", "label": "Mesa",
            "nickname": "The Blue House (rented)",
            "note": "with James and Sarah",
        })
        self.assertIn("rented", record["note"])
        self.assertIn("with James and Sarah", record["note"])

    def test_strip_nickname_parenthetical_is_directly_testable(self):
        self.assertEqual(li.strip_nickname_parenthetical("The Blue House (rented)"),
                         ("The Blue House", "rented"))
        self.assertEqual(li.strip_nickname_parenthetical("The Blue House"),
                         ("The Blue House", None))

    def test_an_https_link_is_kept(self):
        record = li.validate_landmark({"domain": "residences", "label": "Mesa",
                                       "link": "https://maps.example.com/x"})
        self.assertEqual(record["link"], "https://maps.example.com/x")

    def test_a_non_https_link_is_never_stored(self):
        for bad in ("http://example.com", "javascript:alert(1)", "ftp://x"):
            with self.subTest(bad=bad):
                record = li.validate_landmark({"domain": "residences", "label": "Mesa",
                                               "link": bad})
                self.assertNotIn("link", record or {})

    def test_a_record_with_only_a_new_field_still_validates(self):
        record = li.validate_landmark({"domain": "residences", "nickname": "The Ranch"})
        self.assertEqual(record, {"domain": "residences", "nickname": "The Ranch"})

    def test_none_of_the_new_fields_leak_into_an_unrelated_domain_record(self):
        # A domain the model answers ordinarily still validates exactly as
        # it did before this release when none of the new fields are sent.
        record = li.validate_landmark({"domain": "family", "label": "Jackie",
                                       "relation": "sibling"})
        self.assertEqual(record, {"domain": "family", "label": "Jackie",
                                  "relation": "sibling"})


if __name__ == "__main__":
    unittest.main()
