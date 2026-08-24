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
        row = li.domain_row("children")
        self.assertTrue(li.asserts_happened(self.LIVE_SHAPE))
        self.assertEqual(li.rung_reached(self.LIVE_SHAPE, row), "happened")

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
