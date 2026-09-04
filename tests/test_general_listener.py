"""v218 / ADR 0029 — the general listener: the system hears time.

ADR 0028's recorder is FOCUSED. It is handed a domain, shown that domain's
ladder and that domain's filed entries, and it records the answer to the
question that was asked — and the 2026-08-25 adversarial audit explicitly
REFUSED to repeal that restriction, because "something else in the same
breath never excuses the domain's own answer" is what stopped a mission
abroad being filed as military service.

But people say datable things when nobody asked. This is the second trigger
on the SAME loop: `landmark_recorder.record_answer(domain=None, ...)`, with
its own leaf, its own typed-list parse, and — the non-negotiable — its own
deterministic backstop, because the audit's Finding 2 is that prompt prose
alone cannot be certified.

Synthetic data only; NEVER references ~/Workspace/dave.
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

import chronology as chrono  # noqa: E402
import cross_dating  # noqa: E402
import general_listener as gl  # noqa: E402
import landmark_recorder as lr  # noqa: E402
import landmarks_interaction as li  # noqa: E402
from lifehug_core import _parse_simple_yaml  # noqa: E402
from recommend_focuses import TIME_PERIOD_PATTERNS  # noqa: E402

GOLDENS = ROOT / "interactions" / "landmarks" / "evals" / "goldens"
LISTENER_FIXTURE = GOLDENS / "listener-general-01.json"
PRESCREEN_FIXTURE = GOLDENS / "listener-prescreen-01.json"


def _date(best: str, basis: str = "stated") -> dict:
    record = chrono.parse_edtf(best, basis=basis)
    assert record is not None
    return chrono.normalized_date(record.to_dict())


class PrescreenTests(unittest.TestCase):
    """The deterministic half. Table-driven, and the tables are DERIVED."""

    def setUp(self) -> None:
        data = json.loads(PRESCREEN_FIXTURE.read_text(encoding="utf-8"))
        self.assertEqual(data["fixture_id"], "listener-prescreen-01")
        self.cases = data["cases"]

    def test_every_measured_shape_is_pinned(self):
        """The whole measurement, as data. Negatives are load-bearing."""
        for case in self.cases:
            with self.subTest(text=case["text"]):
                verdict = gl.may_contain_datable(case["text"])
                self.assertEqual(verdict.fired, case["fires"])
                if case.get("reason"):
                    self.assertIn(case["reason"], verdict.reasons)

    def test_the_fixture_carries_both_polarities_of_every_trap(self):
        """A prescreen with only positive cases proves nothing."""
        self.assertTrue(any(not case["fires"] for case in self.cases))
        texts = {case["text"] for case in self.cases}
        for trap in ("I hated marching band.",
                     "He may have been right about that.",
                     "At 19% interest nobody was buying.",
                     "We got there at 19:30."):
            self.assertIn(trap, texts)

    # -- the tables are the repo's own, not a sixth parallel list ----------

    def test_the_year_table_is_chronologys_one_year_pattern(self):
        """v218 promoted it and rewired the three private copies to it."""
        self.assertIs(gl.PRESCREEN_TABLES["year"][0], chrono.YEAR_RE)
        self.assertIs(li._ECHO_YEAR_RE, chrono.YEAR_RE)
        import timeline  # noqa: PLC0415
        import timeline_interaction  # noqa: PLC0415

        self.assertIs(timeline._CHAPTER_YEAR_RE, chrono.YEAR_RE)
        self.assertIs(timeline_interaction._YEAR_RE, chrono.YEAR_RE)

    def test_the_age_table_is_cross_datings_own(self):
        self.assertEqual(gl.PRESCREEN_TABLES["age"],
                         tuple(cross_dating.AGE_STATEMENT_RES))
        self.assertIs(cross_dating._AGE_STATEMENT_RES,
                      cross_dating.AGE_STATEMENT_RES)

    def test_the_life_stage_table_reads_recommend_focuses(self):
        self.assertIn(TIME_PERIOD_PATTERNS,
                      gl.PRESCREEN_TABLES["life_stage"])

    def test_the_month_words_are_chronologys_month_names(self):
        self.assertEqual(chrono.MONTH_NAMES, chrono._MONTH_NAMES)
        for name in chrono.MONTH_NAMES:
            with self.subTest(month=name):
                text = f"It was {name} 1979."
                self.assertIn("month", gl.may_contain_datable(text).reasons)

    def test_the_number_words_are_chronologys(self):
        for word in ("three", "seven", "twelve"):
            with self.subTest(word=word):
                self.assertTrue(
                    gl.may_contain_datable(f"We stayed {word} years.").fired)

    def test_a_bare_number_word_alone_never_fires(self):
        """The grouping bug this prescreen must not have.

        A bare alternation spliced into a longer pattern binds at the TOP
        level, so `\\bfive|...\\s+years\\b` matches the word "five" on its
        own. Every number-word form is grouped for exactly this reason.
        """
        for text in ("five", "I gave him five.", "Table for two."):
            with self.subTest(text=text):
                self.assertFalse(gl.may_contain_datable(text).fired)

    # -- the verdict itself -------------------------------------------------

    def test_every_reason_it_can_return_is_in_the_closed_vocabulary(self):
        self.assertEqual(sorted(gl.PRESCREEN_TABLES), sorted(gl.PRESCREEN_REASONS))
        for case in self.cases:
            verdict = gl.may_contain_datable(case["text"])
            for reason in verdict.reasons:
                self.assertIn(reason, gl.PRESCREEN_REASONS)

    def test_the_terms_are_bounded_and_quoted_back(self):
        long = ("I was born in 1948, we moved in 1961, again in 1974, "
                "in March, in May 1979, as a kid, growing up, turning forty, "
                "three years back, the summer after we moved.")
        verdict = gl.may_contain_datable(long)
        self.assertTrue(verdict.fired)
        self.assertLessEqual(len(verdict.terms), gl.MAX_TERMS)
        self.assertIn(verdict.terms[0], gl.listening_reminder(verdict))

    def test_an_empty_message_is_never_a_finding(self):
        for text in ("", "   ", None, 17):
            with self.subTest(text=text):
                self.assertFalse(gl.may_contain_datable(text).fired)

    def test_a_sentence_opening_capital_never_defeats_a_borrowed_table(self):
        """`_sentence_normalized`, and why it beats re-typing the patterns."""
        self.assertTrue(gl.may_contain_datable("At 19 I shipped out.").fired)
        # ...while every exclusion the borrowed table carries survives.
        self.assertFalse(
            gl.may_contain_datable("At 19 Elm Street we had a porch.").fired)


class PersonRecordTests(unittest.TestCase):
    """FAMILY ONLY — the owner's ruling, enforced where prose cannot be."""

    def test_the_family_relations_are_the_roster_vocabulary_minus_strangers(self):
        from focus_candidate import FOCUS_RELATIONSHIPS  # noqa: PLC0415

        self.assertEqual(li.person_date_relations(),
                         frozenset(FOCUS_RELATIONSHIPS) - li.NON_FAMILY_RELATIONS)
        # The family landmark's own three tiers are in it by construction.
        self.assertTrue(li.FAMILY_RELATIONS <= li.person_date_relations())
        # And the strangers are out, every one of them.
        self.assertFalse(li.NON_FAMILY_RELATIONS & li.person_date_relations())

    def test_a_family_date_is_kept_with_its_basis(self):
        record, finding = gl.validate_person_record(
            {"name": "Ruth", "relation": "sibling", "born": "1948",
             "basis": "stated"})
        self.assertEqual(finding, "")
        self.assertEqual(record["name"], "Ruth")
        self.assertEqual(record["relation"], "sibling")
        self.assertEqual(record["born"], _date("1948"))

    def test_a_non_family_relation_is_dropped_by_name(self):
        for relation in sorted(li.NON_FAMILY_RELATIONS):
            with self.subTest(relation=relation):
                record, finding = gl.validate_person_record(
                    {"name": "Hal", "relation": relation, "born": "1948"})
                self.assertIsNone(record)
                self.assertEqual(finding, gl.DROPPED_NON_FAMILY)

    def test_an_absent_relation_is_dropped_by_the_same_name(self):
        """The default must fail toward NOT filing a stranger."""
        for value in ({"name": "Hal", "born": "1948"},
                      {"name": "Hal", "relation": "", "born": "1948"},
                      {"name": "Hal", "relation": "neighbour", "born": "1948"}):
            with self.subTest(value=value):
                record, finding = gl.validate_person_record(value)
                self.assertIsNone(record)
                self.assertEqual(finding, gl.DROPPED_NON_FAMILY)

    def test_a_person_with_no_date_is_not_a_person_record(self):
        record, finding = gl.validate_person_record(
            {"name": "Ruth", "relation": "sibling"})
        self.assertIsNone(record)
        self.assertEqual(finding, gl.DROPPED_NO_DATE)

    def test_an_unreadable_date_drops_that_field_and_not_the_record(self):
        record, finding = gl.validate_person_record(
            {"name": "Ruth", "relation": "sibling", "born": "1948",
             "died": "sometime in the war"})
        self.assertEqual(finding, "")
        self.assertIn("born", record)
        self.assertNotIn("died", record)

    def test_a_nameless_or_malformed_record_is_never_kept(self):
        for value in (None, {}, [], "Ruth", {"relation": "sibling",
                                             "born": "1948"},
                      {"name": "   ", "relation": "sibling", "born": "1948"}):
            with self.subTest(value=value):
                record, finding = gl.validate_person_record(value)
                self.assertIsNone(record)
                self.assertTrue(finding)

    def test_an_unknown_basis_falls_back_rather_than_refusing_the_date(self):
        record, _ = gl.validate_person_record(
            {"name": "Ruth", "relation": "sibling", "born": "1948",
             "basis": "vibes"})
        self.assertEqual(record["basis"], "stated")

    # -- the v217 seam ------------------------------------------------------

    def test_the_invocation_is_the_v217_roster_seam(self):
        people = [{"name": "Ruth", "relation": "sibling", "basis": "stated",
                   "born": _date("1948")}]
        self.assertEqual(gl.person_invocations(people), [[
            "entity-verdict", "person", "ruth", "clear", "--name", "Ruth",
            "--relationship", "sibling", "--born", "1948",
            "--born-basis", "stated", "--ensure"]])

    def test_a_died_date_stamps_not_living(self):
        people = [{"name": "Ada", "relation": "grandparent",
                   "basis": "stated", "died": _date("2019")}]
        argv = gl.person_invocations(people)[0]
        self.assertIn("--not-living", argv)
        self.assertIn("--died", argv)
        self.assertNotIn("--born", argv)

    def test_the_basis_travels_with_the_date(self):
        """`entity_verdict._preferred_date` reads it: derived never
        overwrites stated, so a copy must not misreport its own support."""
        people = [{"name": "Ruth", "relation": "sibling", "basis": "anchor",
                   "born": _date("1948", basis="anchor")}]
        argv = gl.person_invocations(people)[0]
        self.assertEqual(argv[argv.index("--born-basis") + 1], "anchor")

    def test_the_basis_vocabulary_is_chronologys_closed_set(self):
        for basis in chrono.BASES:
            with self.subTest(basis=basis):
                record, _ = gl.validate_person_record(
                    {"name": "Ruth", "relation": "sibling", "born": "1948",
                     "basis": basis})
                self.assertEqual(record["basis"], basis)

    def test_the_leaf_asks_for_stated_and_nothing_else(self):
        """A worked-out date is `cross_dating`'s job, never the listener's."""
        self.assertIn("`basis` is always `stated`", gl.load_listener_leaf())

    def test_the_slug_is_the_one_definition_the_roster_join_uses(self):
        self.assertEqual(li.person_slug("Betty Jo Thorne"), "betty-jo-thorne")
        people = [{"name": "Betty Jo Thorne", "relation": "parent",
                   "basis": "stated", "born": _date("1930")}]
        self.assertEqual(gl.person_invocations(people)[0][2], "betty-jo-thorne")

    def test_a_person_the_slug_cannot_name_files_nothing(self):
        self.assertEqual(gl.person_invocations([{"name": "!!!",
                                                 "relation": "parent",
                                                 "born": _date("1930")}]), [])


class ListenerParseTests(unittest.TestCase):
    """Typed lists, each item through the PINNED validators, alone."""

    def test_landmarks_run_both_pinned_layers_exactly_as_the_recorder_does(self):
        raw = json.dumps({"landmarks": [
            {"domain": "residences", "label": "Dayton", "city": "Dayton"}],
            "people": []})
        heard = gl.parse_listener_output(raw)
        self.assertEqual(heard.landmarks,
                         lr.parse_recorder_output(raw))

    def test_any_domain_is_recordable_here_and_that_is_the_only_difference(self):
        raw = json.dumps({"landmarks": [
            {"domain": "residences", "label": "Dayton", "city": "Dayton"},
            {"domain": "work", "label": "Danforth", "what": "steel"},
            {"domain": "schools", "label": "Fairview", "name": "Fairview"}]})
        heard = gl.parse_listener_output(raw)
        self.assertEqual([r["domain"] for r in heard.landmarks],
                         ["residences", "work", "schools"])

    def test_one_invalid_record_drops_alone(self):
        raw = json.dumps({"landmarks": [
            {"domain": "residences", "label": "Dayton", "city": "Dayton"},
            {"domain": "pets", "label": "Rex"}]})
        heard = gl.parse_listener_output(raw)
        self.assertEqual(len(heard.landmarks), 1)

    def test_a_malformed_envelope_degrades_to_empty_never_to_an_error(self):
        for raw in ("", "not json", "{", "[]", json.dumps([1, 2]), None, 7,
                    json.dumps({"landmarks": "Dayton"})):
            with self.subTest(raw=raw):
                heard = gl.parse_listener_output(raw)
                self.assertEqual(len(heard), 0)

    def test_a_fenced_completion_is_read(self):
        raw = ("```json\n" + json.dumps({"landmarks": [
            {"domain": "work", "label": "Danforth", "what": "steel"}]})
            + "\n```")
        self.assertEqual(len(gl.parse_listener_output(raw).landmarks), 1)

    def test_the_v212_singular_envelope_still_reads(self):
        raw = json.dumps({"landmark": {"domain": "work", "label": "Danforth",
                                       "what": "steel"}})
        self.assertEqual(len(gl.parse_listener_output(raw).landmarks), 1)

    def test_duplicates_collapse_in_both_lists(self):
        person = {"name": "Ruth", "relation": "sibling", "born": "1948"}
        record = {"domain": "work", "label": "Danforth", "what": "steel"}
        heard = gl.parse_listener_output(json.dumps(
            {"landmarks": [record, dict(record)],
             "people": [person, dict(person)]}))
        self.assertEqual(len(heard.landmarks), 1)
        self.assertEqual(len(heard.people), 1)

    def test_a_dropped_person_is_named_in_the_findings(self):
        heard = gl.parse_listener_output(json.dumps({"landmarks": [], "people": [
            {"name": "Hal", "relation": "colleague", "born": "1948"}]}))
        self.assertEqual(heard.people, ())
        self.assertEqual(heard.findings, (gl.DROPPED_NON_FAMILY,))

    def test_there_is_no_placements_list_in_this_pass(self):
        """Moment identity for prose is phase 2 (ADR 0029), and says so."""
        heard = gl.parse_listener_output(json.dumps(
            {"landmarks": [], "people": [], "placements": [{"moment": "x"}]}))
        self.assertEqual(len(heard), 0)
        self.assertFalse(hasattr(heard, "placements"))


class ListenerPromptTests(unittest.TestCase):
    """A leaf with no voice, and a HONEST size pin."""

    def _prompt(self, **kwargs) -> str:
        base = {"answer": "We moved to Dayton in 1974.", "reply": "Dayton."}
        return gl.build_listener_prompt(**{**base, **kwargs})

    def test_it_has_no_voice_and_no_transcript(self):
        prompt = self._prompt()
        for absent in ("## IDENTITY", "## BEHAVIOR", "## EXAMPLES",
                       "## SESSION"):
            self.assertNotIn(absent, prompt)
        self.assertIn("You are not in the conversation", prompt)

    def test_the_measured_size_is_pinned(self):
        """MEASURED, not guessed: 11551 characters with an empty store.

        The focused recorder's leaf pins at 8400 for ONE domain. This one
        carries nine domain KEY lines (~780 characters), the person-record
        rules and — from v229 — the same `claims` contract the recorder leaf
        carries, which is what moved this pin from 5700. It carries no
        identity, no behavior, no examples and no transcript, which is the
        property this pin exists to hold, exactly as
        `test_the_recorder_has_no_voice_and_no_transcript` holds it there.
        The honest cost of the claims contract is written out at that pin.

        E3 (eras §4.3) moved it again, from 9181, by ONE bullet: the
        `event_mention` key and the paragraph that tells the ear it is writing
        down a NAME and not making a link. 480 characters, re-measured here
        rather than rounded up — a pin that gets padded "for headroom" stops
        being a measurement of anything.

        Event identity I3 moved it again, from 9661, by the `identity_
        assertions` section: the fourth list, its own worked example, the
        `{identity_relations}` vocabulary line and the (empty-store)
        `{identity_candidates}` block — 1890 characters, re-measured here for
        the same reason every prior move was.

        v290 (the reader-date-contract fix) moved it again, from 11800: the
        leaf had only ever SHOWN a date once (`"date": "1974"`) and never
        said what other forms were accepted or how an estimate is written,
        which is exactly the gap the reader's own defect traced back to.
        Naming the accepted forms, the bracket-estimate convention, and one
        `span` example costs 12004 characters measured here. Re-measured,
        not rounded up.
        """
        self.assertLess(len(self._prompt()), 12100)

    def test_the_digest_is_nine_lines_and_not_nine_ladders(self):
        digest = gl.render_domain_digest()
        rows = li.load_questions()
        self.assertEqual(len(digest.splitlines()), len(rows))
        self.assertLess(len(digest), 900)
        for row in rows:
            with self.subTest(domain=row["domain"]):
                self.assertIn(f"- {row['domain']}: ", digest)

    def test_the_digest_keys_are_the_recorders_own_derivation(self):
        """ONE declaration of what a domain can read, used in both modes."""
        digest = dict(line[2:].split(": ", 1)
                      for line in gl.render_domain_digest().splitlines())
        for row in li.load_questions():
            with self.subTest(domain=row["domain"]):
                self.assertEqual(digest[row["domain"]],
                                 " | ".join(lr.recordable_keys(row)))

    def test_a_none_domain_says_so_through_its_own_key(self):
        digest = dict(line[2:].split(": ", 1)
                      for line in gl.render_domain_digest().splitlines())
        for row in li.load_questions():
            with self.subTest(domain=row["domain"]):
                self.assertEqual("none" in digest[row["domain"]].split(" | "),
                                 li.domain_accepts_none(row))

    def test_the_family_vocabulary_is_rendered_into_the_leaf(self):
        prompt = self._prompt()
        for relation in li.person_date_relations():
            self.assertIn(relation, prompt)

    def test_the_reminder_is_appended_only_when_given(self):
        self.assertNotIn("You recorded nothing", self._prompt())
        self.assertIn("You recorded nothing",
                      self._prompt(reminder=gl.listening_reminder()))

    # -- the known-entries block, capped TWICE ------------------------------

    def test_an_empty_store_says_so_rather_than_pretending(self):
        self.assertEqual(gl.render_all_known_entries({}), gl.NO_KNOWN_ENTRIES)

    def test_the_block_names_the_domain_of_every_entry(self):
        store = {"children": [{"domain": "children", "label": "Corinne"}],
                 "work": [{"domain": "work", "label": "Danforth"}]}
        block = gl.render_all_known_entries(store)
        self.assertIn("- children · Corinne", block)
        self.assertIn("- work · Danforth", block)

    def test_the_block_is_capped_per_domain_and_in_total_and_says_how_many(self):
        store = {row["domain"]: [{"domain": row["domain"],
                                  "label": f"{row['domain']}-{n}"}
                                 for n in range(6)]
                 for row in li.load_questions()}
        block = gl.render_all_known_entries(store)
        lines = block.splitlines()
        self.assertLessEqual(len(lines) - 1, gl.KNOWN_TOTAL)
        self.assertIn("more already filed across the domains", lines[-1])
        for row in li.load_questions():
            shown = [line for line in lines
                     if line.startswith(f"- {row['domain']} · ")]
            with self.subTest(domain=row["domain"]):
                self.assertLessEqual(len(shown), gl.KNOWN_PER_DOMAIN)

    def test_the_entries_are_rendered_by_v216s_own_renderer(self):
        row = li.domain_row("children")
        entry = {"domain": "children", "label": "Corinne"}
        line = gl.render_all_known_entries({"children": [entry]})
        self.assertEqual(line, f"- children · {li.render_entry(entry, row)[2:]}")


class BackstopTests(unittest.TestCase):
    """The non-negotiable. Never silence."""

    def test_it_fires_on_prescreen_positive_and_nothing_heard(self):
        finding = gl.listener_heard_nothing(
            "We moved to Dayton in 1974.", (), ())
        self.assertIsNotNone(finding)
        self.assertEqual(finding["lint"], gl.LISTENER_HEARD_NOTHING_LINT)
        self.assertIn("year", finding["reasons"])

    def test_one_record_of_either_kind_clears_it(self):
        record = {"domain": "residences", "label": "Dayton"}
        person = {"name": "Ruth", "relation": "sibling", "born": _date("1948")}
        for records, people in (((record,), ()), ((), (person,))):
            with self.subTest(records=records, people=people):
                self.assertIsNone(gl.listener_heard_nothing(
                    "We moved to Dayton in 1974.", records, people))

    def test_a_prescreen_that_did_not_fire_never_lints(self):
        self.assertIsNone(gl.listener_heard_nothing(
            "I love a good pizza.", (), ()))

    def test_a_decline_clears_it_through_answer_shapes_own_rules(self):
        """ONE definition of "not now", never a second list of hedges."""
        for text in ("I don't remember any of that, it was 1974 or so.",
                     "Let's leave that one — sometime in the 1970s.",
                     "I'd rather not, it was around 1974."):
            with self.subTest(text=text):
                self.assertTrue(gl.may_contain_datable(text).fired)
                self.assertEqual(li.answer_shape(text, ""), "skip")
                self.assertIsNone(gl.listener_heard_nothing(text, (), ()))

    def test_a_non_family_drop_clears_it_and_a_malformed_one_does_not(self):
        """A refusal is a DECISION; a malformed object is not a thing heard."""
        message = "My old boss Hal was born in 1948."
        self.assertIsNone(gl.listener_heard_nothing(
            message, (), (), findings=(gl.DROPPED_NON_FAMILY,)))
        self.assertIsNotNone(gl.listener_heard_nothing(
            message, (), (), findings=(gl.DROPPED_NO_DATE,)))

    def test_a_pure_restatement_of_the_store_never_lints(self):
        """v216's dedupe, in the no-focus mode."""
        store = {"children": [{"domain": "children", "label": "Corinne",
                               "date": _date("1979-04-02")}]}
        message = "Corinne was born 2 April 1979."
        self.assertTrue(gl.may_contain_datable(message).fired)
        self.assertIsNotNone(gl.listener_heard_nothing(message, (), ()))
        self.assertIsNone(gl.listener_heard_nothing(
            message, (), (), landmarks=store))

    def test_something_new_beside_a_restatement_still_lints(self):
        store = {"children": [{"domain": "children", "label": "Corinne",
                               "date": _date("1979-04-02")}]}
        message = "Corinne was born 2 April 1979, and Wren in 1990."
        self.assertIsNotNone(gl.listener_heard_nothing(
            message, (), (), landmarks=store))

    def test_the_store_terms_are_v216s_own_two_readers(self):
        row = li.domain_row("children")
        entry = {"domain": "children", "label": "Corinne",
                 "date": _date("1979-04-02")}
        terms = gl.store_terms({"children": [entry]})
        self.assertIn(li.entry_name(entry, row).casefold(), terms)
        for token in chrono.display_date(entry["date"],
                                         with_basis=False).split():
            self.assertIn(token.casefold(), terms)

    def test_the_reminder_names_what_was_seen_and_forbids_inventing(self):
        verdict = gl.may_contain_datable("We moved to Dayton in 1974.")
        reminder = gl.listening_reminder(verdict)
        self.assertIn("1974", reminder)
        self.assertIn("never invent", reminder)

    def test_the_lint_id_is_distinguishable_from_the_focused_one(self):
        self.assertNotEqual(gl.LISTENER_HEARD_NOTHING_LINT,
                            li.ANSWER_MUST_RECORD_LINT)
        self.assertNotIn(gl.LISTENER_HEARD_NOTHING_LINT,
                         li.LANDMARK_LINT_CLASSES)


class OneLoopTests(unittest.TestCase):
    """One attempt/lint/retry loop, two modes. There is no second loop."""

    def _drive(self, raws, **kwargs):
        seen: list[str] = []
        sequence = list(raws)

        def call(prompt: str, model: str) -> str:
            seen.append(prompt)
            return sequence[min(len(seen) - 1, len(sequence) - 1)]

        return lr.listen_to_answer(call=call, **kwargs), seen

    EMPTY = json.dumps({"landmarks": [], "people": []})

    def test_listen_to_answer_is_a_door_onto_record_answer(self):
        raw = json.dumps({"landmarks": [
            {"domain": "work", "label": "Danforth", "what": "steel"}]})
        direct = lr.record_answer(domain=None, answer="I was at Danforth in 1974.",
                                  reply="", call=lambda p, m: raw)
        through, _ = self._drive([raw], answer="I was at Danforth in 1974.")
        self.assertEqual(direct.status, through.status)
        self.assertEqual(direct.records, through.records)

    def test_the_retry_budget_is_the_recorders_own(self):
        outcome, seen = self._drive([self.EMPTY],
                                    answer="We moved to Dayton in 1974.")
        self.assertEqual(outcome.status, lr.STATUS_WITHHELD)
        self.assertEqual(outcome.attempts, lr.MAX_ATTEMPTS)
        self.assertEqual(len(seen), lr.MAX_ATTEMPTS)
        self.assertEqual(outcome.lint_ids, (gl.LISTENER_HEARD_NOTHING_LINT,))
        self.assertIn("You recorded nothing", seen[1])

    def test_a_withheld_listener_pass_is_retryable_by_a_host(self):
        """v216+ semantics: withheld names its lint so a sweep can re-run it."""
        outcome, _ = self._drive([self.EMPTY],
                                 answer="We moved to Dayton in 1974.")
        self.assertTrue(outcome.reason)
        self.assertTrue(outcome.lint_ids)
        self.assertEqual(outcome.records, ())
        self.assertEqual(outcome.people, ())

    def test_the_retry_that_hears_something_files_it(self):
        good = json.dumps({"landmarks": [
            {"domain": "residences", "label": "Dayton", "city": "Dayton",
             "date": "1974"}]})
        outcome, _ = self._drive([self.EMPTY, good],
                                 answer="We moved to Dayton in 1974.")
        self.assertEqual(outcome.status, lr.STATUS_RECORDED)
        self.assertEqual(outcome.attempts, 2)
        self.assertEqual(len(outcome.records), 1)

    def test_an_unavailable_provider_never_touches_the_persons_turn(self):
        def call(prompt, model):
            raise RuntimeError("provider down")

        outcome = lr.listen_to_answer(answer="We moved in 1974.", call=call)
        self.assertEqual(outcome.status, lr.STATUS_UNAVAILABLE)
        self.assertEqual(outcome.records, ())

    def test_unavailable_on_the_retry_files_what_is_already_in_hand(self):
        good = json.dumps({"landmarks": [
            {"domain": "residences", "label": "Dayton", "city": "Dayton"}]})
        calls = {"n": 0}

        def call(prompt, model):
            calls["n"] += 1
            if calls["n"] == 1:
                return good
            raise RuntimeError("provider down")

        # One record is enough to clear the backstop, so this returns on the
        # first attempt — the branch is pinned through the focused twin.
        outcome = lr.listen_to_answer(answer="We moved to Dayton in 1974.",
                                      call=call)
        self.assertEqual(outcome.status, lr.STATUS_RECORDED)

    # -- the focused mode is UNTOUCHED --------------------------------------

    def test_the_focused_mode_still_refuses_an_unknown_domain(self):
        with self.assertRaises(li.LandmarkInteractionError):
            lr.record_answer(domain="pets", answer="x", call=lambda p, m: "{}")

    def test_the_focused_mode_never_returns_people(self):
        raw = json.dumps({"landmarks": [{"domain": "military", "none": True}]})
        outcome = lr.record_answer(domain="military", answer="I never served.",
                                   reply="No service, then.",
                                   call=lambda p, m: raw)
        self.assertEqual(outcome.status, lr.STATUS_RECORDED)
        self.assertEqual(outcome.people, ())
        self.assertEqual(outcome.findings, ())

    def test_the_focused_prompt_is_still_the_recorder_leaf(self):
        seen: list[str] = []

        def call(prompt, model):
            seen.append(prompt)
            return json.dumps({"landmarks": [{"domain": "military",
                                              "none": True}]})

        lr.record_answer(domain="military", answer="I never served.",
                         call=call)
        self.assertIn("DOMAIN BEING ASKED ABOUT: military", seen[0])
        self.assertNotIn("THE DOMAINS, AND THE ONLY KEYS", seen[0])

    def test_the_focused_restriction_is_a_property_of_focused_mode_only(self):
        """The audit's refusal, pinned as behavior.

        The recorder's leaf still says a mission abroad is a `none` for
        military; the listener's leaf carries no such sentence because it was
        never asked about a domain. Two leaves, one vocabulary.
        """
        recorder_leaf = lr.load_recorder_leaf()
        listener_leaf = gl.load_listener_leaf()
        self.assertIn("never excuses the domain's own answer", recorder_leaf)
        self.assertNotIn("never excuses the domain's own answer", listener_leaf)
        self.assertIn("DOMAIN BEING ASKED ABOUT", recorder_leaf)
        self.assertNotIn("DOMAIN BEING ASKED ABOUT", listener_leaf)

    def test_the_focused_cli_refuses_a_missing_domain_rather_than_listening(self):
        import io  # noqa: PLC0415
        from contextlib import redirect_stdout  # noqa: PLC0415

        stdout = io.StringIO()
        original = sys.stdin
        sys.stdin = io.StringIO(json.dumps({"answer": "We moved in 1974."}))
        try:
            with redirect_stdout(stdout):
                code = lr.main([])
        finally:
            sys.stdin = original
        self.assertEqual(code, 1)
        self.assertIn("a domain is required", stdout.getvalue())


class ManifestTests(unittest.TestCase):
    """The leaf, the role and the constants are one edit, not three."""

    def setUp(self) -> None:
        self.manifest = _parse_simple_yaml(
            ROOT / "interactions" / "landmarks" / "interaction.yaml")

    def test_the_listener_leaf_is_its_own_composition(self):
        self.assertEqual(self.manifest["composition.listener"],
                         "prompt/listener.md")
        self.assertNotIn("listener", self.manifest["load_order"])
        self.assertNotIn("listener", self.manifest["composition.append"])

    def test_the_listener_role_matches_the_manifest(self):
        self.assertEqual(self.manifest["role.listener"],
                         gl.DEFAULT_LISTENER_ROLE)

    def test_the_leaf_lives_where_the_manifest_says(self):
        self.assertTrue((ROOT / "interactions" / "landmarks" / "prompt"
                         / gl.LISTENER_PROMPT).exists())


class PurposeTests(unittest.TestCase):
    """A SECOND name, never a rename."""

    def test_the_two_purposes_are_two_names(self):
        self.assertEqual(gl.DATE_RECORD_PURPOSE, "date_record")
        self.assertEqual(gl.LANDMARK_RECORD_PURPOSE, "landmark_record")
        self.assertNotEqual(gl.DATE_RECORD_PURPOSE, gl.LANDMARK_RECORD_PURPOSE)

    def test_the_recorder_keeps_naming_its_own(self):
        self.assertEqual(lr.RECORDER_PURPOSE, gl.LANDMARK_RECORD_PURPOSE)


class GoldenTests(unittest.TestCase):
    """The founder-shaped cases, end to end."""

    def setUp(self) -> None:
        data = json.loads(LISTENER_FIXTURE.read_text(encoding="utf-8"))
        self.assertEqual(data["fixture_id"], "listener-general-01")
        self.cases = {case["case_id"]: case for case in data["cases"]}

    def _drive(self, case: dict):
        seen: list[str] = []

        def call(prompt: str, model: str) -> str:
            seen.append(prompt)
            return case["attempt"]["raw"]

        outcome = lr.listen_to_answer(
            answer=case["user_message"], reply=case["reply"],
            landmarks=case["landmarks"], call=call)
        return outcome, seen

    def test_every_golden_case_lands_exactly_where_it_says(self):
        for case_id, case in self.cases.items():
            with self.subTest(case=case_id):
                outcome, seen = self._drive(case)
                self.assertEqual(outcome.status, case["expected_status"])
                self.assertEqual(outcome.attempts, case["expected_attempts"])
                self.assertEqual(len(seen), case["expected_attempts"])
                self.assertEqual(list(outcome.lint_ids),
                                 case["expected_lint_ids"])
                self.assertEqual(list(outcome.findings),
                                 case["expected_findings"])
                self.assertEqual(list(outcome.people), case["expected_people"])

    def test_every_golden_cases_prescreen_verdict_is_pinned(self):
        for case_id, case in self.cases.items():
            with self.subTest(case=case_id):
                self.assertEqual(
                    gl.may_contain_datable(case["user_message"]).fired,
                    case["prescreen_fires"])

    def test_the_three_fact_case_files_three_records_across_three_domains(self):
        outcome, _ = self._drive(self.cases["three-datable-facts-across-domains"])
        self.assertEqual([r["domain"] for r in outcome.records],
                         ["residences", "schools", "work"])

    def test_the_person_case_files_through_the_roster_seam(self):
        case = self.cases["a-family-sibling-year-is-a-person-record"]
        outcome, _ = self._drive(case)
        self.assertEqual(gl.person_invocations(outcome.people),
                         [list(argv) for argv in case["expected_invocations"]])

    def test_the_invalid_record_case_keeps_its_sibling(self):
        outcome, _ = self._drive(self.cases["one-invalid-record-among-many-drops-alone"])
        self.assertEqual([r["domain"] for r in outcome.records], ["residences"])

    def test_the_restatement_costs_one_completion_and_files_nothing(self):
        outcome, seen = self._drive(self.cases["restated-known-entries-file-nothing"])
        self.assertEqual(len(seen), 1)
        self.assertEqual(outcome.records, ())
        # ...and the model was SHOWN them, which is what v216 is for.
        for name in ("Corinne", "Maddox"):
            self.assertIn(name, seen[0])


if __name__ == "__main__":
    unittest.main()
