"""The reading contract — one model pass over volunteered text (Cut 6f).

Controlling design: `lifehug-platform
docs/decisions/2026-09-03-timeline-unification/add-landmark-reading-plan.md`
§2 (owner rulings R6–R9), §3.1 (the reading), §3.2 (the proposal's keys).
ADR 0033's Cut 6f amendment.

This file pins the LEAF and the PARSE. `tests/test_landmark_offer.py` pins
what `propose` makes of a reading, and `tests/test_landmark_offer_host.py`
pins a host driving the same pass from another process.

No live model call anywhere: every completion here is a literal.
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

import general_listener as gl  # noqa: E402
import landmark_reading as lr  # noqa: E402
import landmarks_interaction as li  # noqa: E402

MANIFEST = (ROOT / "interactions" / "landmarks"
            / "interaction.yaml").read_text(encoding="utf-8")

ELM = ("I lived on Elm from 1990 to 1992, we called it the blue house, "
       "I was at Lincoln Elementary then, and Dad started at the mill "
       "that spring.")

ELM_READING = {
    "units": [
        {"ref": "u1", "domain": "residences", "subject": "the blue house",
         "names": {"nickname": "the blue house", "city": "Elm"},
         "record": {"city": "Elm", "label": "the blue house"},
         "dates": {"start": "1990", "end": "1992", "ongoing": False,
                   "start_estimated": False, "end_estimated": False},
         "within": None,
         "quote": "I lived on Elm from 1990 to 1992, we called it the blue house"},
        {"ref": "u2", "domain": "schools", "subject": "Lincoln Elementary",
         "record": {"name": "Lincoln Elementary",
                    "label": "Lincoln Elementary"},
         "dates": None, "within": "u1",
         "quote": "I was at Lincoln Elementary then"},
    ],
    "events": [
        {"ref": "e1", "text": "Dad started at the mill", "kind": "job",
         "subject_mention": "Dad", "date": None, "within": "u1",
         "quote": "and Dad started at the mill that spring."},
    ],
    "stories": [], "unplaced": [],
}


def read(payload: object, text: str = ELM) -> lr.Reading:
    raw = payload if isinstance(payload, str) else json.dumps(payload)
    return lr.parse_reading(raw, text=text)


# --------------------------------------------------------------------------
# The leaf, and the vocabulary it teaches
# --------------------------------------------------------------------------


class LeafTests(unittest.TestCase):
    def test_the_manifest_declares_the_slot_this_module_names(self):
        self.assertIn(f"composition.reading: prompt/{lr.READING_PROMPT}",
                      MANIFEST)
        self.assertTrue((ROOT / "interactions" / "landmarks" / "prompt"
                         / lr.READING_PROMPT).is_file())

    def test_the_reading_role_matches_the_manifest(self):
        self.assertIn(f"role.reading: {lr.DEFAULT_READING_ROLE}", MANIFEST)

    def test_the_leaf_is_under_its_declared_budget(self):
        budget = int([line.split(": ")[1] for line in MANIFEST.splitlines()
                      if line.startswith("budget.reading: ")][0])
        self.assertLess(len(lr.load_reading_leaf()), budget * 4)

    def test_the_leaf_never_names_the_retired_product(self):
        """R4: nothing user-facing may mention Go Dig or the Reading Room."""
        body = lr.load_reading_leaf().lower()
        for forbidden in ("go dig", "go-dig", "go_dig", "reading room"):
            self.assertNotIn(forbidden, body)

    def test_the_prompt_substitutes_every_token(self):
        import re  # noqa: PLC0415

        prompt = lr.build_reading_prompt(ELM, landmarks={}, roster={})
        self.assertEqual(re.findall(r"\{[a-z_]+\}", prompt), [])
        self.assertIn(ELM, prompt)

    def test_the_domain_vocabulary_is_rendered_from_the_live_tables(self):
        """R6's whole point: the model is taught the keys the validator
        actually accepts, and nobody hand-copies them into the leaf."""
        prompt = lr.build_reading_prompt("x", landmarks={}, roster={})
        self.assertIn(gl.render_domain_digest(), prompt)
        self.assertIn(lr.render_name_keys(), prompt)
        self.assertIn(lr.render_date_shapes(), prompt)
        self.assertIn(lr.render_span_nouns(), prompt)
        self.assertIn(lr.render_estimation_marks(), prompt)
        leaf = lr.load_reading_leaf()
        # The leaf carries the TOKEN, never a copy of what it renders to.
        for domain in (row["domain"] for row in li.load_questions()):
            self.assertNotIn(f"- {domain}: ", leaf)

    def test_the_name_keys_are_probed_not_declared(self):
        """`validate_landmark` is the authority. `city` and `address` are the
        residences ladder's own rungs; the E-L2c fields are additive on every
        domain."""
        self.assertEqual(lr.name_keys_for("residences"),
                         ("nickname", "city", "address", "place_ref", "link"))
        self.assertEqual(lr.name_keys_for("work"),
                         ("nickname", "place_ref", "link"))
        self.assertEqual(lr.name_keys_for("not-a-domain"), ())

    def test_the_date_shape_is_the_domains_own_ladder(self):
        rows = {row["domain"]: row for row in li.load_questions()}
        self.assertEqual(lr.date_shape_for(rows["residences"]), "span")
        self.assertEqual(lr.date_shape_for(rows["children"]), "date")

    def test_the_span_noun_falls_back_to_the_unit_kind(self):
        self.assertEqual(lr.span_noun("residences"), "stay")
        self.assertEqual(lr.span_noun("work"), "tenure")
        self.assertEqual(lr.span_noun("schools"), "schooling")
        self.assertEqual(lr.span_noun("children"), "child")

    def test_the_extractor_is_versioned_by_the_leafs_own_bytes(self):
        block = lr.reading_extractor()
        self.assertEqual(block["name"], lr.READING_EXTRACTOR)
        self.assertEqual(block["model"], lr.DEFAULT_READING_ROLE)
        self.assertEqual(block["prompt_version"],
                         gl.leaf_prompt_version(lr.load_reading_leaf()))
        self.assertIn(block["prompt_version"], lr.reading_extractor_version())

    def test_the_leaf_shows_both_worked_readings(self):
        leaf = lr.load_reading_leaf()
        self.assertIn("A block out of a pasted document", leaf)
        self.assertIn("One sentence of ordinary prose", leaf)
        self.assertIn("I lived on Elm from 1990 to 1992", leaf)


# --------------------------------------------------------------------------
# Lenient in shape (§3.1)
# --------------------------------------------------------------------------


class ShapeTests(unittest.TestCase):
    def test_a_completion_that_is_not_json_is_an_empty_reading_with_a_finding(self):
        for raw in ("not JSON at all", "[1, 2, 3]", "", None, 17):
            with self.subTest(raw=raw):
                out = lr.parse_reading(raw, text=ELM)
                self.assertEqual(len(out), 0)
                self.assertEqual(len(out.findings), 1)

    def test_a_fenced_completion_still_parses(self):
        raw = "```json\n" + json.dumps(ELM_READING) + "\n```"
        self.assertEqual(len(read(raw).units), 2)

    def test_missing_lists_are_empty_lists(self):
        out = read({"units": ELM_READING["units"]})
        self.assertEqual(len(out.units), 2)
        self.assertEqual(out.events, ())
        self.assertEqual(out.stories, ())
        self.assertEqual(out.unplaced, ())

    def test_an_unknown_top_level_key_is_dropped_with_a_finding(self):
        out = read({"units": [], "verdict": "looks good"})
        self.assertIn("dropped unknown reading key: verdict", out.findings)

    def test_an_unknown_unit_key_is_dropped_with_a_finding(self):
        payload = json.loads(json.dumps(ELM_READING))
        payload["units"][0]["confidence"] = "high"
        out = read(payload)
        self.assertIn("dropped unknown unit key: confidence", out.findings)
        self.assertEqual(len(out.units), 2)

    def test_a_story_written_as_a_bare_string_is_still_read(self):
        text = "The dog died that summer."
        out = lr.parse_reading(json.dumps({"stories": [text]}), text=text)
        self.assertEqual([story.quote["text"] for story in out.stories], [text])


# --------------------------------------------------------------------------
# Strict in substance (§3.1)
# --------------------------------------------------------------------------


class SubstanceTests(unittest.TestCase):
    def test_every_quote_must_locate_in_the_text(self):
        payload = json.loads(json.dumps(ELM_READING))
        payload["units"][1]["quote"] = "I was at Kestrel Elementary then"
        out = read(payload)
        self.assertEqual([unit.ref for unit in out.units], ["u1"])
        self.assertTrue(any("quote is not in the text" in row
                            for row in out.findings))

    def test_a_unit_with_no_quote_is_dropped_with_a_finding(self):
        payload = json.loads(json.dumps(ELM_READING))
        payload["units"][1]["quote"] = ""
        out = read(payload)
        self.assertEqual([unit.ref for unit in out.units], ["u1"])
        self.assertIn("dropped unit u2: no quote", out.findings)

    def test_a_repeated_quote_is_located_once_per_unit_in_order(self):
        """A real document repeats itself: the same employer on three
        consecutive blocks is three units, not one line read three times."""
        text = ("Work: Delaney Hardware\n\nWork: Delaney Hardware\n\n"
                "Work: Delaney Hardware")
        payload = {"units": [
            {"ref": f"u{index}", "domain": "work", "subject": "Delaney Hardware",
             "record": {"what": "Delaney Hardware", "label": "Delaney Hardware"},
             "dates": None, "within": None, "quote": "Work: Delaney Hardware"}
            for index in (1, 2, 3)]}
        out = lr.parse_reading(json.dumps(payload), text=text)
        self.assertEqual([unit.quote["offset"] for unit in out.units],
                         [0, 24, 48])

    def test_a_dangling_within_is_a_finding_and_the_unit_survives(self):
        payload = json.loads(json.dumps(ELM_READING))
        payload["units"][1]["within"] = "u9"
        out = read(payload)
        self.assertEqual(len(out.units), 2)
        self.assertIsNone(out.units[1].within)
        self.assertIn("dropped within on u2: no unit 'u9'", out.findings)

    def test_a_cycle_is_broken_at_one_link_and_both_units_survive(self):
        """The cycle is cut where it is FOUND, not everywhere: u1 loses the
        parent that closed the loop, u2 keeps the real one it had. Losing both
        would be the silent drop this mode exists to end."""
        payload = json.loads(json.dumps(ELM_READING))
        payload["units"][0]["within"] = "u2"
        out = read(payload)
        self.assertEqual(len(out.units), 2)
        self.assertEqual([unit.within for unit in out.units], [None, "u1"])
        self.assertTrue(any("part of a cycle" in row for row in out.findings))
        # …and what survives is acyclic.
        by_ref = {unit.ref: unit for unit in out.units}
        for unit in out.units:
            seen, cursor = {unit.ref}, unit.within
            while cursor:
                self.assertNotIn(cursor, seen)
                seen.add(cursor)
                cursor = by_ref[cursor].within

    def test_a_unit_naming_itself_is_a_cycle(self):
        payload = json.loads(json.dumps(ELM_READING))
        payload["units"][0]["within"] = "u1"
        out = read(payload)
        self.assertIsNone(out.units[0].within)
        self.assertTrue(any("part of a cycle" in row for row in out.findings))

    def test_an_unknown_domain_is_dropped_with_a_finding(self):
        payload = {"units": [
            {"ref": "u1", "domain": "pets", "subject": "Rex",
             "record": {"label": "Rex"}, "dates": None, "within": None,
             "quote": ELM[:20]}]}
        out = read(payload)
        self.assertEqual(out.units, ())
        self.assertIn("dropped unit: unknown domain 'pets'", out.findings)

    def test_a_record_that_does_not_validate_is_dropped_with_a_finding(self):
        payload = {"units": [
            {"ref": "u1", "domain": "residences", "subject": "",
             "record": {}, "dates": None, "within": None,
             "quote": ELM[:20]}]}
        out = read(payload)
        self.assertEqual(out.units, ())
        self.assertTrue(any("did not validate" in row for row in out.findings))

    def test_names_are_mapped_onto_the_records_e_l2c_fields(self):
        out = read(ELM_READING)
        record = out.units[0].record
        self.assertEqual(record["nickname"], "the blue house")
        self.assertEqual(record["city"], "Elm")
        self.assertEqual(out.units[0].names["nickname"], "the blue house")

    def test_a_nicknames_parenthetical_becomes_a_note(self):
        text = "Nickname: The Blue House (rented)"
        payload = {"units": [
            {"ref": "u1", "domain": "residences", "subject": "The Blue House",
             "names": {"nickname": "The Blue House (rented)"},
             "record": {"city": "Riverbend", "label": "The Blue House"},
             "dates": None, "within": None, "quote": text}]}
        record = lr.parse_reading(json.dumps(payload), text=text).units[0].record
        self.assertEqual(record["nickname"], "The Blue House")
        self.assertEqual(record["note"], "rented")

    def test_a_name_a_domain_does_not_accept_is_dropped_with_a_finding(self):
        text = "I worked at the mill."
        payload = {"units": [
            {"ref": "u1", "domain": "work", "subject": "the mill",
             "names": {"city": "Riverbend"},
             "record": {"what": "the mill", "label": "the mill"},
             "dates": None, "within": None, "quote": text}]}
        out = lr.parse_reading(json.dumps(payload), text=text)
        self.assertIn("dropped name 'city': work does not accept it",
                      out.findings)
        self.assertNotIn("city", out.units[0].record)

    def test_a_link_that_is_not_https_is_simply_not_stored(self):
        text = "Link: javascript:alert(1)"
        payload = {"units": [
            {"ref": "u1", "domain": "residences", "subject": "Riverbend",
             "names": {"link": "javascript:alert(1)"},
             "record": {"city": "Riverbend", "label": "Riverbend"},
             "dates": None, "within": None, "quote": text}]}
        out = lr.parse_reading(json.dumps(payload), text=text)
        self.assertNotIn("link", out.units[0].record)


# --------------------------------------------------------------------------
# Dates (§3.1 rule 3, R8)
# --------------------------------------------------------------------------


class DateTests(unittest.TestCase):
    def _one(self, dates: object, text: str = "Dates: whatever") -> dict:
        payload = {"units": [
            {"ref": "u1", "domain": "residences", "subject": "Riverbend",
             "record": {"city": "Riverbend", "label": "Riverbend"},
             "dates": dates, "within": None, "quote": text}]}
        out = lr.parse_reading(json.dumps(payload), text=text)
        return out.units[0].record if out.units else {}

    def test_every_form_the_leaf_teaches_parses(self):
        for value, best in (("1974", "1974"), ("1974-06", "1974-06"),
                            ("1981-07-11", "1981-07-11"),
                            ("July 1981", "1981-07"),
                            ("Jul 1981", "1981-07"),
                            ("2 April 1979", "1979-04-02"),
                            ("April 2, 1979", "1979-04-02")):
            with self.subTest(value=value):
                record = self._one({"start": value})
                self.assertEqual(record["span"]["start"]["best"], best)

    def test_an_estimated_bound_becomes_approximate(self):
        record = self._one({"start": "Jun 1986", "end": "March 1991",
                            "start_estimated": True, "end_estimated": False})
        self.assertEqual(record["span"]["start"]["confidence"], "approximate")
        self.assertEqual(record["span"]["end"]["confidence"], "certain")

    def test_a_bracketed_bound_is_approximate_without_the_flag(self):
        """R8: the estimation mark is the interaction's own convention and
        `chronology.parse_loose_date` reads it directly."""
        record = self._one({"start": "[Jun 1986]"})
        self.assertEqual(record["span"]["start"]["confidence"], "approximate")

    def test_an_open_stay_is_ongoing_rather_than_undated(self):
        record = self._one({"start": "1989", "end": None, "ongoing": True})
        self.assertTrue(record["ongoing"])
        self.assertNotIn("end", record["span"])

    def test_a_domain_that_records_one_date_takes_the_start(self):
        text = "AJ was born March 20, 1990."
        payload = {"units": [
            {"ref": "u1", "domain": "children", "subject": "AJ",
             "record": {"who": "AJ", "label": "AJ"},
             "dates": {"start": "March 20, 1990", "end": "1991"},
             "within": None, "quote": text}]}
        out = lr.parse_reading(json.dumps(payload), text=text)
        record = out.units[0].record
        self.assertEqual(record["date"]["best"], "1990-03-20")
        self.assertNotIn("span", record)
        self.assertIn("dropped end date: children records one date, not a "
                      "stretch", out.findings)

    def test_an_unreadable_date_leaves_the_unit_undated(self):
        record = self._one({"start": "sometime in the before-times"})
        self.assertNotIn("span", record)

    def test_an_event_date_is_normalized_and_an_unreadable_one_is_a_finding(self):
        text = "AJ was born March 20, 1990."
        payload = {"events": [
            {"ref": "e1", "text": "AJ was born", "kind": "child_born",
             "subject_mention": "AJ", "date": "March 20, 1990",
             "within": None, "quote": text}]}
        out = lr.parse_reading(json.dumps(payload), text=text)
        self.assertEqual(out.events[0].date["best"], "1990-03-20")
        payload["events"][0]["date"] = "one summer"
        out = lr.parse_reading(json.dumps(payload), text=text)
        self.assertIsNone(out.events[0].date)
        self.assertIn("dropped date on event e1: unreadable", out.findings)


# --------------------------------------------------------------------------
# Wiring
# --------------------------------------------------------------------------


class WiringTests(unittest.TestCase):
    def test_the_new_files_ship(self):
        manifest = json.loads((SYSTEM / "version.json").read_text(
            encoding="utf-8"))
        for path in ("system/landmark_reading.py",
                     "interactions/landmarks/prompt/reading.md",
                     "tests/test_landmark_reading.py"):
            with self.subTest(path=path):
                self.assertIn(path, manifest["framework_files"])

    def test_the_module_reads_no_vault_and_calls_no_model(self):
        import ast  # noqa: PLC0415

        source = (SYSTEM / "landmark_reading.py").read_text(encoding="utf-8")
        called = {node.func.attr for node in ast.walk(ast.parse(source))
                  if isinstance(node, ast.Call)
                  and isinstance(node.func, ast.Attribute)}
        for forbidden in ("call_ai", "load_landmarks", "save_landmark",
                          "write_text"):
            self.assertNotIn(forbidden, called)


if __name__ == "__main__":
    unittest.main()
