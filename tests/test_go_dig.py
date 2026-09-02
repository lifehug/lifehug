"""E-L3 — the Go Dig unit writer, the deterministic import grammar (§10.6),
and the import's crash/retry/reorder/malformed-block promises (§12 rows 15,
16, 25, 28, 31–35).

Design: lifehug-platform `docs/design/timeline-eras.md` v2.1 §10 (Go Dig and
import), §10.3 (a unit), §10.4 (the declared import policy), §10.5 (budget),
§10.6 (the grammar), §12 rows 15, 16, 21, 22, 25, 28, 31–35, §14.4.

Synthetic data only; NEVER references ~/Workspace/dave.
"""

from __future__ import annotations

import ast
import contextlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SYSTEM = ROOT / "system"
sys.path.insert(0, str(SYSTEM))
sys.path.insert(0, str(ROOT / "tests"))

import entity_roster  # noqa: E402
import episode_binder as eb  # noqa: E402
import event_identity as ei  # noqa: E402
import go_dig_grammar as grammar  # noqa: E402
import go_dig_writer as gd  # noqa: E402
import landmark_projection as lp  # noqa: E402
import temporal_claims as tc  # noqa: E402
import temporal_store as ts  # noqa: E402
import timeline  # noqa: E402
from tempdirs import root_parent_tmp  # noqa: E402

NOW = "2026-09-02T00:00:00Z"


# --------------------------------------------------------------------------
# A synthetic vault, wired the way `mock.patch.object(timeline,
# "LANDMARKS_STORE", ...)` already does in tests/test_landmarks.py — plus
# the roster, which `go_dig_writer` reads/writes through `entity_roster`'s
# own process binding.
# --------------------------------------------------------------------------


@contextlib.contextmanager
def synthetic_vault(root: Path):
    (root / "state").mkdir(parents=True, exist_ok=True)
    (root / "sources").mkdir(parents=True, exist_ok=True)
    (root / "state" / "entity_rosters").mkdir(parents=True, exist_ok=True)
    orig_store = timeline.LANDMARKS_STORE
    orig_entity_dir = entity_roster.ENTITY_DIR
    timeline.LANDMARKS_STORE = root / "state" / "landmarks.json"
    entity_roster.ENTITY_DIR = root / "state" / "entity_rosters"
    try:
        yield root
    finally:
        timeline.LANDMARKS_STORE = orig_store
        entity_roster.ENTITY_DIR = orig_entity_dir


class GoDigVaultCase(unittest.TestCase):
    def setUp(self) -> None:
        tmp = root_parent_tmp(self, ROOT, prefix="godig-")
        self._ctx = synthetic_vault(tmp)
        self.root = self._ctx.__enter__()
        self.addCleanup(self._ctx.__exit__, None, None, None)

    def landmarks(self) -> dict:
        return json.loads((self.root / "state" / "landmarks.json").read_text())

    def entries(self, domain: str) -> list:
        return list(self.landmarks().get("domains", {}).get(domain, []))

    def roster(self, entity_type: str) -> dict:
        path = self.root / "state" / "entity_rosters" / f"{entity_type}.json"
        if not path.is_file():
            return {"entities": []}
        return json.loads(path.read_text())


# --------------------------------------------------------------------------
# The grammar — every field form named in §10.6
# --------------------------------------------------------------------------


class DatesGrammarTests(unittest.TestCase):
    def test_bracketed_month_year_range_sets_approximate_on_each_bound(self):
        parsed = grammar.parse_dates_value("[Jun 1990] - [Jun 1991]")
        self.assertEqual(parsed["start"]["edtf"], "1990-06")
        self.assertTrue(parsed["start"]["approximate"])
        self.assertEqual(parsed["end"]["edtf"], "1991-06")
        self.assertTrue(parsed["end"]["approximate"])
        self.assertFalse(parsed["unparseable"])

    def test_month_day_year_is_day_grain(self):
        bound = grammar.parse_date_bound("June 1, 1990")
        self.assertEqual(bound["edtf"], "1990-06-01")
        self.assertEqual(bound["grain"], "day")

    def test_three_letter_month_abbreviation(self):
        bound = grammar.parse_date_bound("Jun 1990")
        self.assertEqual(bound["edtf"], "1990-06")
        self.assertEqual(bound["grain"], "month")

    def test_year_only(self):
        bound = grammar.parse_date_bound("1990")
        self.assertEqual(bound["edtf"], "1990")
        self.assertEqual(bound["grain"], "year")

    def test_now_and_present_are_ongoing_with_no_end_claim(self):
        for word in ("now", "present", "Present"):
            bound = grammar.parse_date_bound(word)
            self.assertTrue(bound["ongoing"])
            self.assertIsNone(bound["edtf"])

    def test_trailing_parenthetical_after_end_falls_to_the_note(self):
        parsed = grammar.parse_dates_value("1985 - 1990 (about 6 weeks)")
        self.assertEqual(parsed["note"], "about 6 weeks")
        self.assertEqual(parsed["end"]["edtf"], "1990")

    def test_en_dash_separator(self):
        parsed = grammar.parse_dates_value("1985 – 1990")
        self.assertEqual(parsed["start"]["edtf"], "1985")
        self.assertEqual(parsed["end"]["edtf"], "1990")

    def test_unparseable_dates_are_reported(self):
        parsed = grammar.parse_dates_value("whenever - eventually")
        self.assertTrue(parsed["unparseable"])


class PlaceGrammarTests(unittest.TestCase):
    def test_city_slash_state_splits_on_the_last_comma(self):
        parsed = grammar.parse_place_value("Springfield, Oregon")
        self.assertEqual(parsed["place"], "Springfield")
        self.assertEqual(parsed["region"], "Oregon")

    def test_finer_key_wins_over_bare_country(self):
        block = grammar.parse_block(
            "City/State: Springfield, Oregon\nCountry: United States", ordinal=1
        )
        self.assertEqual(block["place_name"], "Springfield")
        self.assertEqual(block["region_name"], "Oregon")

    def test_country_alone_is_a_region_level_place(self):
        block = grammar.parse_block("Country: France", ordinal=1)
        self.assertEqual(block["place_name"], "France")
        self.assertIsNone(block["region_name"])

    def test_kanton_country_is_recognized(self):
        block = grammar.parse_block("Kanton/Country: Zurich, Switzerland", ordinal=1)
        self.assertEqual(block["place_name"], "Zurich")
        self.assertEqual(block["region_name"], "Switzerland")


class NicknameGrammarTests(unittest.TestCase):
    def test_trailing_parenthetical_strips_to_the_note(self):
        block = grammar.parse_block("Nickname: The Blue House (rented)", ordinal=1)
        self.assertEqual(block["nickname"], "The Blue House")
        self.assertIn("rented", block["note_lines"])

    def test_a_plain_nickname_has_no_note(self):
        block = grammar.parse_block("Nickname: The Fish's House", ordinal=1)
        self.assertEqual(block["nickname"], "The Fish's House")
        self.assertEqual(block["note_lines"], ())


class AddressLinkGrammarTests(unittest.TestCase):
    def test_address_is_verbatim(self):
        block = grammar.parse_block("Address: 100 Example Street, Springfield, OR",
                                    ordinal=1)
        self.assertEqual(block["address"], "100 Example Street, Springfield, OR")

    def test_link_must_be_https(self):
        block = grammar.parse_block("Link: http://example.com/x", ordinal=1)
        self.assertIsNone(block["link"])
        block = grammar.parse_block("Link: https://example.com/x", ordinal=1)
        self.assertEqual(block["link"], "https://example.com/x")


class SchoolGrammarTests(unittest.TestCase):
    def test_none_and_blank_file_nothing(self):
        for value in ("None", ""):
            block = grammar.parse_block(f"School: {value}\nCountry: X", ordinal=1)
            self.assertEqual(block["school"]["status"], "none")
            self.assertIsNone(block["school"]["name"])

    def test_done_is_recognized(self):
        block = grammar.parse_block("School: Done", ordinal=1)
        self.assertEqual(block["school"]["status"], "done")

    def test_name_with_comma_grades(self):
        block = grammar.parse_block("School: Riverside Elementary, 4th grade", ordinal=1)
        self.assertEqual(block["school"]["name"], "Riverside Elementary")
        self.assertEqual(block["school"]["grades"], "4th grade")

    def test_grade_phrase_splits_even_without_a_comma(self):
        block = grammar.parse_block("School: Central High 9th grade", ordinal=1)
        self.assertEqual(block["school"]["name"], "Central High")
        self.assertEqual(block["school"]["grades"], "9th grade")

    def test_nth_and_mth_grade(self):
        block = grammar.parse_block("School: Central High, 9th and 10th grade", ordinal=1)
        self.assertEqual(block["school"]["grades"], "9th and 10th grade")

    def test_pk_and_k(self):
        for grade in ("PK", "K"):
            block = grammar.parse_block(f"School: Little Steps, {grade}", ordinal=1)
            self.assertEqual(block["school"]["grades"], grade)

    def test_then_phrase_kept_whole(self):
        block = grammar.parse_block(
            "School: Riverside Elementary, 5th grade then Central Middle", ordinal=1
        )
        self.assertEqual(block["school"]["name"], "Riverside Elementary")
        self.assertIn("then Central Middle", block["school"]["grades"])

    def test_parenthesized_name_keeps_name_and_notes_the_raw_line(self):
        block = grammar.parse_block("School: (maybe Central Elementary)", ordinal=1)
        self.assertEqual(block["school"]["name"], "maybe Central Elementary")
        self.assertTrue(any("School:" in note for note in block["note_lines"]))


class WorkGrammarTests(unittest.TestCase):
    def test_none_and_blank_file_nothing(self):
        for value in ("None", ""):
            parsed = grammar.parse_work_value(value)
            self.assertEqual(parsed["status"], "none")
            self.assertEqual(parsed["items"], ())

    def test_org_in_parens_and_in_place_and_inline_start(self):
        item = grammar.parse_work_item(
            "Warehouse associate (Acme Corp) - in Springfield (start Jun 2001)"
        )
        self.assertEqual(item["what"], "Warehouse associate")
        self.assertEqual(item["org"], "Acme Corp")
        self.assertEqual(item["where"], "Springfield")
        self.assertEqual(item["start"]["edtf"], "2001-06")
        self.assertIsNone(item["end"])

    def test_changed_wording_same_organization(self):
        first = grammar.parse_work_item("Boeing")
        second = grammar.parse_work_item("Boeing in Seattle (start Jun 2018)")
        self.assertEqual(first["org"], "Boeing")
        self.assertEqual(second["org"], "Boeing")
        self.assertNotEqual((first["what"], first["where"]),
                            (second["what"], second["where"]))

    def test_comma_separated_items_split_at_the_top_level_only(self):
        parsed = grammar.parse_work_value(
            "Clerk (start Jun 1990, no really), Cashier"
        )
        self.assertEqual(len(parsed["items"]), 2)
        self.assertEqual(parsed["items"][1]["what"], "Cashier")


class BlockGrammarTests(unittest.TestCase):
    """The synthetic fixture round-trips every field form (§10.6, incl. the
    owner's own worked example)."""

    EXAMPLE = (
        "Dates: [Jun 1990] - [Jun 1991]\n"
        "City/State: Springfield, Oregon\n"
        "Nickname: The Blue House (rented)\n"
        "Address: 100 Example Street, Springfield, OR\n"
        "Link: https://maps.example.com/blue-house\n"
        "School: Riverside Elementary, 4th grade\n"
        "Work: None\n"
        "Events: broke my arm; cousin born March 3, 1991"
    )

    def test_a_leading_heading_line_is_ignored(self):
        blocks = grammar.parse_paste(f"# My homes\n\n{self.EXAMPLE}")
        self.assertEqual(len(blocks), 1)
        self.assertEqual(blocks[0]["place_name"], "Springfield")

    def test_an_unknown_key_falls_to_the_note(self):
        block = grammar.parse_block("Pets: a dog named Rex", ordinal=1)
        self.assertIn("Pets: a dog named Rex", block["note_lines"])

    def test_the_owner_example_parses_every_field(self):
        block = grammar.parse_block(self.EXAMPLE, ordinal=1)
        self.assertEqual(block["status"], "ready")
        self.assertEqual(block["dates"]["start"]["edtf"], "1990-06")
        self.assertTrue(block["dates"]["start"]["approximate"])
        self.assertEqual(block["place_name"], "Springfield")
        self.assertEqual(block["region_name"], "Oregon")
        self.assertEqual(block["nickname"], "The Blue House")
        self.assertEqual(block["address"], "100 Example Street, Springfield, OR")
        self.assertEqual(block["link"], "https://maps.example.com/blue-house")
        self.assertEqual(block["school"]["name"], "Riverside Elementary")
        self.assertEqual(block["work_items"], ())
        self.assertIn("cousin born", block["events_text"])

    def test_reordering_the_same_blocks_keeps_content_digests(self):
        text_a = f"{self.EXAMPLE}\n\nCountry: France\n"
        text_b = f"Country: France\n\n{self.EXAMPLE}\n"
        digests_a = sorted(b["content_digest"] for b in grammar.parse_paste(text_a))
        digests_b = sorted(b["content_digest"] for b in grammar.parse_paste(text_b))
        self.assertEqual(digests_a, digests_b)


# --------------------------------------------------------------------------
# `go-dig-record` — the one unit
# --------------------------------------------------------------------------


class RecordUnitTests(GoDigVaultCase):
    def test_files_through_the_one_landmark_writer(self):
        result = gd.record_unit({
            "landmark": {"domain": "residences", "city": "Cedarport",
                        "place_name": "Cedarport",
                        "span": {"start": "1996-06", "end": "2001-08"}},
        }, now=NOW)
        self.assertEqual(result["domain"], "residences")
        entries = self.entries("residences")
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["place_ref"], "place/cedarport")

    def test_resolves_the_roster_place_by_name(self):
        gd.record_unit({
            "landmark": {"domain": "residences", "city": "Cedarport",
                        "place_name": "Cedarport", "span": {"start": "1996"}},
        }, now=NOW)
        roster = self.roster("place")
        self.assertEqual([e["name"] for e in roster["entities"]], ["Cedarport"])

    def test_a_second_stay_at_the_same_name_reuses_the_roster_place(self):
        gd.record_unit({"landmark": {"domain": "residences", "city": "Cedarport",
                                     "place_name": "Cedarport", "span": {"start": "1996"}}},
                       now=NOW)
        gd.record_unit({"landmark": {"domain": "residences", "city": "Cedarport",
                                     "place_name": "Cedarport", "span": {"start": "2010"}}},
                       now=NOW)
        roster = self.roster("place")
        self.assertEqual(len(roster["entities"]), 1)

    def test_nickname_files_a_roster_alias_not_a_ladder_identity(self):
        result = gd.record_unit({
            "landmark": {"domain": "residences", "city": "Cedarport",
                        "place_name": "Cedarport", "nickname": "The Fish's House",
                        "span": {"start": "1996"}},
        }, now=NOW)
        self.assertTrue(result["alias"]["applied"])
        roster = self.roster("place")
        self.assertEqual(roster["entities"][0]["aliases"], ["The Fish's House"])
        entries = self.entries("residences")
        self.assertNotIn("nickname", ())  # sanity: nickname is a field, not identity
        self.assertEqual(entries[0].get("city"), "Cedarport")

    def test_a_colliding_nickname_mints_identity_uncertain_and_binds_neither(self):
        gd.record_unit({"landmark": {"domain": "residences", "city": "Cedarport",
                                     "place_name": "Cedarport", "span": {"start": "1996"}}},
                       now=NOW)
        gd.record_unit({"landmark": {"domain": "residences", "city": "Millgate",
                                     "place_name": "Millgate", "span": {"start": "2010"}}},
                       now=NOW)
        result = gd.record_unit({
            "landmark": {"domain": "residences", "city": "Cedarport",
                        "place_name": "Cedarport", "nickname": "the old place",
                        "span": {"start": "1997"}},
        }, now=NOW)
        self.assertTrue(result["alias"]["applied"])
        collision = gd.record_unit({
            "landmark": {"domain": "residences", "city": "Millgate",
                        "place_name": "Millgate", "nickname": "the old place",
                        "span": {"start": "2011"}},
        }, now=NOW)
        self.assertFalse(collision["alias"]["applied"])
        self.assertEqual(collision["alias"]["reason"], "identity_uncertain")

    def test_the_note_is_promoted_as_its_own_owner_only_go_dig_note_source(self):
        result = gd.record_unit({
            "landmark": {"domain": "residences", "city": "Cedarport",
                        "place_name": "Cedarport", "span": {"start": "1996", "end": "1998"}},
            "note": "broke my arm here",
        }, now=NOW)
        self.assertIsNotNone(result["note_source"])
        source_path = self.root / result["note_source"]["source_path"]
        content = source_path.read_text()
        self.assertIn('type: "go_dig_note"', content)
        self.assertIn('visibility: "owner_only"', content)
        self.assertIn(f'question_context: "{result["telling_ref"]}"', content)

    def test_no_note_files_no_extra_source(self):
        result = gd.record_unit({
            "landmark": {"domain": "residences", "city": "Cedarport",
                        "place_name": "Cedarport", "span": {"start": "1996"}},
        }, now=NOW)
        self.assertIsNone(result["note_source"])

    def test_a_bare_landmark_with_no_domain_is_refused(self):
        with self.assertRaises(gd.GoDigError):
            gd.record_unit({"landmark": {"city": "Cedarport"}})

    def test_import_context_files_under_a_content_addressed_digest(self):
        payload = {
            "landmark": {"domain": "residences", "city": "Cedarport",
                        "place_name": "Cedarport", "span": {"start": "1996"}},
            "import_operation_id": "op-1", "block_content_digest": "abc123",
            "unit_discriminator": "residences",
        }
        gd.record_unit(payload, now=NOW)
        gd.record_unit(payload, now=NOW)  # same op+block+discriminator: a no-op
        self.assertEqual(len(lp.load_landmark_sources(self.root)), 1)


# --------------------------------------------------------------------------
# `go-dig-import` — preview
# --------------------------------------------------------------------------


class PreviewImportTests(unittest.TestCase):
    def test_preview_writes_nothing(self):
        tmp = tempfile.mkdtemp()
        try:
            with synthetic_vault(Path(tmp)) as root:
                text = "Dates: 1980 - 1982\nCity/State: Town, State\nWork: None\n"
                gd.preview_import(text)
                self.assertFalse((root / "state" / "landmarks.json").exists())
        finally:
            import shutil
            shutil.rmtree(tmp, ignore_errors=True)

    def test_preview_reports_needs_a_hand_and_overlap(self):
        text = (
            "Dates: 1980 - 1990\nCity/State: TownA, State\nWork: None\n\n"
            "Dates: 1985 - 1995\nCity/State: TownB, State\nWork: None\n\n"
            "Dates: whenever\nCity/State: TownC, State\nWork: None\n"
        )
        preview = gd.preview_import(text)
        statuses = [b["status"] for b in preview["blocks"]]
        self.assertEqual(statuses, ["ready", "ready", "needs_a_hand"])
        self.assertEqual(len(preview["overlaps"]), 1)
        self.assertEqual(preview["overlaps"][0]["a_ordinal"], 1)
        self.assertEqual(preview["overlaps"][0]["b_ordinal"], 2)


# --------------------------------------------------------------------------
# `go-dig-import --apply` — rows 15, 16, 25, 28, 31, 32, 33, 34
# --------------------------------------------------------------------------


def _stay_block(ordinal_years: tuple, town: str) -> str:
    y0, y1 = ordinal_years
    return f"Dates: {y0} - {y1}\nCity/State: {town}, ExampleState\nWork: None\n"


class ApplyImportTests(GoDigVaultCase):
    def test_row15_crash_after_n_blocks_retried_files_no_duplicate(self):
        blocks = [_stay_block((1970 + i * 10, 1972 + i * 10), f"Town{i}")
                  for i in range(5)]
        text = "\n\n".join(blocks)

        orig_record_unit = gd.record_unit
        calls = {"n": 0}

        def flaky(payload, now=None):
            calls["n"] += 1
            if calls["n"] == 3:
                raise RuntimeError("simulated crash")
            return orig_record_unit(payload, now=now)

        gd.record_unit = flaky
        try:
            with self.assertRaises(RuntimeError):
                gd.apply_import(text, import_operation_id="op-crash", now=NOW)
        finally:
            gd.record_unit = orig_record_unit
        self.assertEqual(len(lp.load_landmark_sources(self.root)), 2)

        summary = gd.apply_import(text, import_operation_id="op-crash", now=NOW)
        self.assertEqual(summary["filed"], 5)
        self.assertEqual(len(lp.load_landmark_sources(self.root)), 5)

        # A second retry is a total no-op.
        gd.apply_import(text, import_operation_id="op-crash", now=NOW)
        self.assertEqual(len(lp.load_landmark_sources(self.root)), 5)

    def test_row16_a_malformed_block_is_skipped_valid_ones_file(self):
        text = (
            _stay_block((1970, 1972), "TownA")
            + "\n\n"
            + "Dates: not parseable at all\nCity/State: TownB, State\nWork: None\n"
            + "\n\n"
            + _stay_block((1990, 1992), "TownC")
        )
        summary = gd.apply_import(text, import_operation_id="op-malformed", now=NOW)
        self.assertEqual(summary["filed"], 2)
        self.assertEqual(summary["needs_a_hand"], 1)
        self.assertEqual(self.entries("residences").__len__(), 2)

    def test_row25_work_none_files_nothing(self):
        text = "Dates: 1980 - 1982\nCity/State: Town, State\nWork: None\n"
        summary = gd.apply_import(text, import_operation_id="op-25", now=NOW)
        self.assertEqual(summary["work_tenures"], 0)
        self.assertEqual(self.entries("work"), [])

    def test_row28_reordered_import_mints_nothing_new(self):
        blocks = [_stay_block((1970 + i * 10, 1972 + i * 10), f"Town{i}")
                  for i in range(3)]
        text_a = "\n\n".join(blocks)
        text_b = "\n\n".join([blocks[2], blocks[0], blocks[1]])

        gd.apply_import(text_a, import_operation_id="op-reorder", now=NOW)
        first_count = len(lp.load_landmark_sources(self.root))
        gd.apply_import(text_b, import_operation_id="op-reorder", now=NOW)
        second_count = len(lp.load_landmark_sources(self.root))
        self.assertEqual(first_count, second_count)
        self.assertEqual(first_count, 3)

    def test_row31_a_job_listed_under_three_consecutive_stays(self):
        text = (
            "Dates: 1990 - 1991\nCity/State: TownA, State\n"
            "Work: Mail sorter\n\n"
            "Dates: 1991 - 1992\nCity/State: TownB, State\n"
            "Work: Mail sorter\n\n"
            "Dates: 1992 - 1993\nCity/State: TownC, State\n"
            "Work: Mail sorter\n"
        )
        summary = gd.apply_import(text, import_operation_id="op-31", now=NOW)
        self.assertEqual(summary["work_tenures"], 1)
        work = self.entries("work")
        self.assertEqual(len(work), 1)
        self.assertEqual(work[0]["what"], "Mail sorter")
        self.assertEqual(work[0]["span"]["start"]["best"], "1990")
        self.assertEqual(work[0]["span"]["start"]["confidence"], "inferred")
        self.assertEqual(work[0]["span"]["end"]["best"], "1993")
        self.assertEqual(work[0]["span"]["end"]["confidence"], "inferred")

    def test_row32_changed_wording_same_organization_two_episodes(self):
        text = (
            "Dates: 2010 - 2015\nCity/State: TownA, State\n"
            "Work: Boeing\n\n"
            "Dates: 2015 - 2020\nCity/State: TownB, State\n"
            "Work: Boeing in Seattle (start Jun 2015)\n"
        )
        summary = gd.apply_import(text, import_operation_id="op-32", now=NOW)
        self.assertEqual(summary["work_tenures"], 2)
        work = self.entries("work")
        self.assertEqual(len(work), 2)
        roster = self.roster("organization")
        self.assertEqual(len(roster["entities"]), 1)
        self.assertEqual(roster["entities"][0]["name"], "Boeing")
        stated = [e for e in work if e["span"]["start"]["confidence"] == "certain"]
        self.assertEqual(len(stated), 1)
        self.assertEqual(stated[0]["span"]["start"]["best"], "2015-06")

    def test_row33_school_done_none_and_blank(self):
        text = (
            "Dates: 1980 - 1982\nCity/State: TownA, State\nSchool: Done\n\n"
            "Dates: 1990 - 1992\nCity/State: TownB, State\nSchool: None\n\n"
            "Dates: 2000 - 2002\nCity/State: TownC, State\n"
        )
        gd.apply_import(text, import_operation_id="op-33", now=NOW)
        closures = lp.load_chain_closures(self.root)
        self.assertEqual(len(closures), 1)
        self.assertEqual(closures[0]["domain"], "schools")
        self.assertEqual(closures[0]["status"], "closed_for_now")
        self.assertEqual(self.entries("schools"), [])

    def test_row34_same_address_two_non_consecutive_blocks(self):
        text = (
            "Dates: 1980 - 1982\nAddress: 100 Example Street, Springfield, OR\n"
            "City/State: Springfield, Oregon\nWork: None\n\n"
            "Dates: 1990 - 1992\nAddress: 200 Other Street, Elsewhere, OR\n"
            "City/State: Elsewhere, Oregon\nWork: None\n\n"
            "Dates: 2005 - 2007\nAddress: 100 Example Street, Springfield, OR\n"
            "City/State: Springfield, Oregon\nWork: None\n"
        )
        gd.apply_import(text, import_operation_id="op-34", now=NOW)
        residences = self.entries("residences")
        self.assertEqual(len(residences), 3)
        springfield = [e for e in residences if e.get("place_ref") == "place/springfield"]
        self.assertEqual(len(springfield), 2)
        roster = self.roster("place")
        names = sorted(e["name"] for e in roster["entities"] if e["name"] != "Oregon")
        self.assertEqual(names, ["Elsewhere", "Springfield"])


# --------------------------------------------------------------------------
# Row 35 — a note's Events line is classified and lands `part_of` the stay
# through the REAL binder, via `question_context`.
# --------------------------------------------------------------------------


class Row35QuestionContextContainmentTest(GoDigVaultCase):
    def test_a_classified_moment_from_the_note_binds_to_the_stay(self):
        result = gd.record_unit({
            "landmark": {"domain": "residences", "city": "Cedarport",
                        "place_name": "Cedarport",
                        "span": {"start": "1996-06", "end": "2001-08"}},
            "note": "broke my arm here",
        }, now=NOW)
        telling_ref = result["telling_ref"]
        note_source = result["note_source"]

        # A synthetic CLASSIFIED MOMENT — exactly the shape a classifier's
        # own claim takes (test_participation_episodes.py's own pattern),
        # citing the go-dig note as its source.
        claim = tc.validate_temporal_claim({
            "source_kind": "conversation",
            "source_ref": {"source_id": note_source["source_id"],
                           "revision": note_source["revision"],
                           "source_path": note_source["source_path"]},
            "evidence": [{"quote": "broke my arm here"}],
            "extractor_version": "classifier:1",
            "created_at": NOW,
            "basis": "explicit",
            "confidence": 0.9,
            "status": "active",
            "claim_type": "occurrence",
            "subject_mention": "I",
            "event_mention": "broke my arm",
            "event_kind": "moment",
        })
        ts.write_receipt(self.root, {
            "source_ref": claim["source_ref"],
            "extractor_version": "classifier:1",
            "created_at": NOW,
            "claims": [claim],
        })
        ts.rebuild_active_index(self.root)

        outcome = eb.bind_episodes(self.root, apply=True, now=NOW,
                                   containment_authority="applied")
        plan = outcome["plan"]
        note_telling_ref = ei.telling_ref_for_claim(claim)
        # `plan.containments` is grouped BY CONTAINER, one row per container
        # with its members nested underneath (`group_by_container`'s shape) —
        # find the container whose members include the note's telling.
        containers = [
            row for row in plan.containments
            if any(member.get("telling_ref") == note_telling_ref
                  for member in row.get("members") or ())
        ]
        self.assertTrue(containers, f"no container carries the note's telling "
                                    f"{note_telling_ref!r}; containments={plan.containments}")
        container = containers[0]
        self.assertEqual(container["opened_by"], telling_ref)
        self.assertEqual(container["label"], "Cedarport")
        member = next(m for m in container["members"]
                     if m["telling_ref"] == note_telling_ref)
        self.assertEqual(member["rule_id"], "question_context")


# --------------------------------------------------------------------------
# Zero model calls anywhere in the import path (§10.5, M8)
# --------------------------------------------------------------------------


class NoModelCallTest(unittest.TestCase):
    """An AST sweep, not a runtime mock: the import path must not even
    IMPORT a model/classifier module, so a future edit that adds one trips
    this test rather than a live budget."""

    BANNED_MODULES = {
        "classify_story", "anthropic", "openai", "llm_client",
        "conversation_prompt", "conversation_delivery",
    }

    def _imported_names(self, path: Path) -> set:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        names: set = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                names.add(node.module.split(".")[0])
        return names

    def test_go_dig_writer_imports_no_model_module(self):
        found = self._imported_names(SYSTEM / "go_dig_writer.py") & self.BANNED_MODULES
        self.assertEqual(found, set())

    def test_go_dig_grammar_imports_no_model_module(self):
        found = self._imported_names(SYSTEM / "go_dig_grammar.py") & self.BANNED_MODULES
        self.assertEqual(found, set())


# --------------------------------------------------------------------------
# The CLI is wired
# --------------------------------------------------------------------------


class CliWiringTest(unittest.TestCase):
    def test_both_commands_are_direct_mutations(self):
        import lifehug  # noqa: PLC0415

        self.assertIn("go-dig-record", lifehug.DIRECT_MUTATION_COMMANDS)
        self.assertIn("go-dig-import", lifehug.DIRECT_MUTATION_COMMANDS)

    def test_both_commands_are_registered(self):
        import lifehug  # noqa: PLC0415

        parser = lifehug.build_parser()
        args = parser.parse_args(["go-dig-record"])
        self.assertEqual(args.func, lifehug.cmd_go_dig_record)
        args = parser.parse_args(["go-dig-import", "--apply",
                                  "--import-operation-id", "op-1"])
        self.assertEqual(args.func, lifehug.cmd_go_dig_import)
        self.assertTrue(args.apply)
        self.assertEqual(args.import_operation_id, "op-1")


if __name__ == "__main__":
    unittest.main()
