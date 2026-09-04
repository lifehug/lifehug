"""v290 — the landmark reader accepts the date shapes its own prompts teach.

`interactions/landmarks/prompt/listener.md` and `.../recorder.md` show
``"date": "1974"`` — a plain string — as their own worked example, and never
show any other shape for a date. `conversation_delivery._parse_landmark_date`
used to accept ONLY a ``{"best": ..., ...}`` dict; a string reached it and the
whole record was kept WITHOUT its date, silently, no finding. This file
proves the fix: a bare string date and a bare string span bound now survive
with the right granularity, natural date text parses through
`chronology.parse_loose_date`, a bracketed estimate comes back
``confidence: "approximate"``, and every existing DICT shape is untouched —
byte-identical to what it returned before this fix.

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

import chronology as chrono  # noqa: E402
import conversation_delivery as engine  # noqa: E402
import general_listener as gl  # noqa: E402
import landmark_recorder as lr  # noqa: E402


class ParseLooseDateTests(unittest.TestCase):
    """`chronology.parse_loose_date` — the one new fuzzy-date function."""

    def test_year(self):
        result = chrono.parse_loose_date("1974")
        self.assertEqual(result["best"], "1974")
        self.assertEqual(result["granularity"], "year")
        self.assertEqual(result["confidence"], "certain")

    def test_year_month(self):
        result = chrono.parse_loose_date("1974-06")
        self.assertEqual(result["best"], "1974-06")
        self.assertEqual(result["granularity"], "month")

    def test_full_date(self):
        result = chrono.parse_loose_date("1981-07-11")
        self.assertEqual(result["best"], "1981-07-11")
        self.assertEqual(result["granularity"], "day")

    def test_day_month_name_year(self):
        result = chrono.parse_loose_date("2 April 1979")
        self.assertEqual(result["best"], "1979-04-02")
        self.assertEqual(result["granularity"], "day")
        self.assertEqual(result["earliest"], "1979-04-02")
        self.assertEqual(result["latest"], "1979-04-02")

    def test_month_name_day_comma_year(self):
        result = chrono.parse_loose_date("April 2, 1979")
        self.assertEqual(result["best"], "1979-04-02")
        self.assertEqual(result["granularity"], "day")

    def test_month_name_day_comma_year_second_form(self):
        result = chrono.parse_loose_date("July 11, 1981")
        self.assertEqual(result["best"], "1981-07-11")
        self.assertEqual(result["granularity"], "day")

    def test_month_abbreviation_year(self):
        result = chrono.parse_loose_date("Jun 1986")
        self.assertEqual(result["best"], "1986-06")
        self.assertEqual(result["granularity"], "month")

    def test_month_full_name_year(self):
        result = chrono.parse_loose_date("June 1986")
        self.assertEqual(result["best"], "1986-06")
        self.assertEqual(result["granularity"], "month")

    def test_month_name_is_case_insensitive(self):
        self.assertEqual(chrono.parse_loose_date("jUnE 1986")["best"], "1986-06")
        self.assertEqual(chrono.parse_loose_date("JUL 11, 1981")["best"],
                         "1981-07-11")

    def test_bracketed_estimate_is_approximate(self):
        result = chrono.parse_loose_date("[Jun 1986]")
        self.assertEqual(result["granularity"], "month")
        self.assertEqual(result["confidence"], "approximate")
        self.assertEqual(result["earliest"], "1986-06")
        self.assertEqual(result["latest"], "1986-06")

    def test_bracketed_natural_form_is_also_approximate(self):
        result = chrono.parse_loose_date("[2 April 1979]")
        self.assertEqual(result["best"], "1979-04-02~")
        self.assertEqual(result["confidence"], "approximate")

    def test_unparseable_text_is_none(self):
        self.assertIsNone(chrono.parse_loose_date("sometime after we moved"))
        self.assertIsNone(chrono.parse_loose_date(""))
        self.assertIsNone(chrono.parse_loose_date("[]"))
        self.assertIsNone(chrono.parse_loose_date(None))

    def test_normalized_date_falls_back_to_loose_parsing(self):
        """The reader's actual path into this: `normalized_date` itself."""
        result = chrono.normalized_date("2 April 1979")
        self.assertEqual(result["best"], "1979-04-02")
        self.assertEqual(result["granularity"], "day")
        result = chrono.normalized_date({"best": "Jun 1986"})
        self.assertEqual(result["best"], "1986-06")
        self.assertEqual(result["granularity"], "month")

    def test_edtf_still_wins_when_it_already_parses(self):
        """No behaviour change for what `parse_edtf` already reads."""
        self.assertEqual(chrono.parse_loose_date("1970s")["granularity"], "era")
        self.assertEqual(chrono.parse_loose_date("spring 1998")["granularity"],
                         "season")


class ParseLandmarkDateStringTests(unittest.TestCase):
    """`conversation_delivery._parse_landmark_date` — the structural layer."""

    def test_bare_string_wraps_as_best(self):
        result = engine._parse_landmark_date("1974")  # noqa: SLF001
        self.assertEqual(result, {"best": "1974"})

    def test_natural_text_also_wraps_as_best(self):
        result = engine._parse_landmark_date("2 April 1979")  # noqa: SLF001
        self.assertEqual(result, {"best": "2 April 1979"})

    def test_blank_string_is_none(self):
        self.assertIsNone(engine._parse_landmark_date("   "))  # noqa: SLF001

    def test_overlong_string_is_none(self):
        self.assertIsNone(engine._parse_landmark_date("x" * 33))  # noqa: SLF001

    def test_max_length_string_survives(self):
        text = "x" * 32
        self.assertEqual(engine._parse_landmark_date(text),  # noqa: SLF001
                         {"best": text})

    def test_existing_dict_shape_is_byte_identical(self):
        """The one behaviour this fix must never touch."""
        raw = {"best": "1974", "earliest": "1974", "latest": "1974",
               "granularity": "year", "confidence": "certain",
               "basis": "stated", "anchors": ["you said you were about 5"],
               "provenance": [{"source": "A12"}]}
        before = {"best": "1974", "earliest": "1974", "latest": "1974",
                  "granularity": "year", "confidence": "certain",
                  "basis": "stated",
                  "anchors": ["you said you were about 5"],
                  "provenance": [{"source": "A12"}]}
        self.assertEqual(engine._parse_landmark_date(raw), before)  # noqa: SLF001

    def test_dict_with_unknown_key_is_still_rejected(self):
        self.assertIsNone(
            engine._parse_landmark_date({"best": "1974", "made_up": "x"}))  # noqa: SLF001

    def test_non_string_non_dict_is_none(self):
        self.assertIsNone(engine._parse_landmark_date(1974))  # noqa: SLF001
        self.assertIsNone(engine._parse_landmark_date(None))  # noqa: SLF001
        self.assertIsNone(engine._parse_landmark_date([]))  # noqa: SLF001


class ParseLandmarkStringSpanTests(unittest.TestCase):
    """`conversation_delivery._parse_landmark` — string dates AND string span bounds."""

    def test_string_date_survives_on_the_record(self):
        record = engine._parse_landmark(  # noqa: SLF001
            {"domain": "residences", "label": "Yucaipa", "date": "1981"})
        self.assertEqual(record["date"], {"best": "1981"})

    def test_string_span_bounds_survive(self):
        record = engine._parse_landmark({  # noqa: SLF001
            "domain": "residences", "label": "Yucaipa",
            "span": {"start": "1981-07-11", "end": "July 1982"},
        })
        self.assertEqual(record["span"],
                         {"start": {"best": "1981-07-11"},
                          "end": {"best": "July 1982"}})

    def test_mixed_dict_and_string_span_bounds(self):
        """One bound stated the old way, one the new — both survive."""
        record = engine._parse_landmark({  # noqa: SLF001
            "domain": "residences", "label": "Yucaipa",
            "span": {"start": {"best": "1981-07", "basis": "stated"},
                     "end": "1982-07"},
        })
        self.assertEqual(record["span"]["start"],
                         {"best": "1981-07", "basis": "stated"})
        self.assertEqual(record["span"]["end"], {"best": "1982-07"})


class ReproduceScenarioTests(unittest.TestCase):
    """The exact scenario named in the defect: date AND span both strings."""

    def test_the_defect_scenario_now_keeps_its_date_and_span(self):
        payload = json.dumps({
            "landmarks": [{
                "domain": "residences", "label": "Yucaipa", "city": "Yucaipa",
                "date": "1981",
                "span": {"start": "1981-07-11", "end": "July 1982"},
            }],
            "claims": [],
        })
        records = lr.parse_recorder_output(payload)
        self.assertEqual(len(records), 1)
        record = records[0]
        self.assertIn("date", record)
        self.assertEqual(record["date"]["best"], "1981")
        self.assertEqual(record["date"]["granularity"], "year")
        self.assertIn("span", record)
        self.assertEqual(record["span"]["start"]["best"], "1981-07-11")
        self.assertEqual(record["span"]["start"]["granularity"], "day")
        self.assertEqual(record["span"]["end"]["best"], "1982-07")
        self.assertEqual(record["span"]["end"]["granularity"], "month")


class RecorderPromptExampleRoundTripTests(unittest.TestCase):
    """The leaf's OWN worked example, verbatim, through the real recorder path."""

    def test_the_recorder_leaf_own_example_shape_round_trips(self):
        """`interactions/landmarks/prompt/recorder.md` shows exactly this
        shape for `birth`'s date rung: ``"date": "1974"``, a bare string.
        """
        completion = json.dumps({
            "landmarks": [{"domain": "birth", "date": "1974"}],
            "claims": [],
        })
        records = lr.parse_recorder_output(completion)
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["domain"], "birth")
        self.assertEqual(records[0]["date"]["best"], "1974")
        self.assertEqual(records[0]["date"]["granularity"], "year")
        self.assertEqual(records[0]["date"]["earliest"], "1974")
        self.assertEqual(records[0]["date"]["latest"], "1974")


class ListenerStringDateTests(unittest.TestCase):
    """One case through `general_listener.parse_listener_output`."""

    def test_listener_output_keeps_a_string_dated_landmark(self):
        completion = json.dumps({
            "landmarks": [{
                "domain": "residences", "label": "Dayton", "city": "Dayton",
                "date": "1974",
            }],
            "people": [],
            "claims": [],
            "identity_assertions": [],
        })
        heard = gl.parse_listener_output(completion)
        self.assertEqual(len(heard.landmarks), 1)
        landmark = heard.landmarks[0]
        self.assertEqual(landmark["city"], "Dayton")
        self.assertEqual(landmark["date"]["best"], "1974")
        self.assertEqual(landmark["date"]["granularity"], "year")


if __name__ == "__main__":
    unittest.main()
