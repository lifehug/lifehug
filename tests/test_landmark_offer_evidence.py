"""Add Landmark reads EVIDENCE, and says when it REVISES (lifehug#469, v397).

Two gaps kept letter-derived dates from filing honestly through the offer
road, and these tests pin their closure:

* ``revises`` — a unit that is the SAME stay as a filed entry with a
  different bound used to be annotated ``duplicates`` ("filing adds
  nothing"). Now it names the bound, what is filed, what it says, and which
  side `chronology.reconcile` would show. Never `auto_file_eligible`.
* ``--evidence relative|document`` — `date_evidence` is a bytes test, so a
  year inside a letter quote made the bound ``stated``. The declaration
  re-stamps every bound the bytes test kept with the declared basis and one
  provenance entry naming the source and the words; the bytes test itself is
  untouched.

Fixtures are the issue's own four, with SYNTHETIC names and dates in the
founder's shapes; NEVER references ~/Workspace/dave.
"""

from __future__ import annotations

import contextlib
import io
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SYSTEM = ROOT / "system"
sys.path.insert(0, str(SYSTEM))
sys.path.insert(0, str(ROOT / "tests"))

import chronology as chrono  # noqa: E402
import entity_roster  # noqa: E402
import landmark_offer as lo  # noqa: E402
import landmarks_interaction as li  # noqa: E402
import timeline  # noqa: E402
from tempdirs import root_parent_tmp  # noqa: E402
from test_landmark_offer import (  # noqa: E402
    ScriptedCall, read_dates, read_unit, reading, synthetic_vault,
)

NOW = "2026-10-06T00:00:00Z"


class EvidenceVaultCase(unittest.TestCase):
    def setUp(self) -> None:
        tmp = root_parent_tmp(self, ROOT, prefix="evidence-")
        self._ctx = synthetic_vault(tmp)
        self.root = self._ctx.__enter__()
        self.addCleanup(self._ctx.__exit__, None, None, None)

    def entries(self, domain: str) -> list:
        path = self.root / "state" / "landmarks.json"
        if not path.is_file():
            return []
        return list(json.loads(path.read_text()).get("domains", {}).get(domain) or ())

    def file_stay(self, label: str, start: str, end: str, *,
                  city: str = "Orchard City") -> None:
        timeline.save_landmark("residences", {
            "domain": "residences", "label": label, "city": city,
            "span": {"start": chrono.parse_edtf(start).to_dict(),
                     "end": chrono.parse_edtf(end).to_dict()}})

    def propose(self, text: str, call, **kwargs) -> dict:
        return lo.propose(text, self.root, call=call, now=NOW, **kwargs)


# --------------------------------------------------------------------------
# Fixture 1 — a month moves on a letter: Orchard House Aug 1982 → Jun/Jul
# --------------------------------------------------------------------------

ORCHARD_LETTER = ("Grandma wrote on 29 July 1982: it was so good to hear that "
                  "you like your new home ward in Orchard City. So they were in "
                  "the Orchard House by July 1982.")


class RevisesTests(EvidenceVaultCase):
    def _orchard_unit(self, start: str = "1982-07") -> dict:
        return read_unit("u1", "residences", "Orchard House", ORCHARD_LETTER,
                         record={"label": "Orchard House", "city": "Orchard City"},
                         dates=read_dates(start, "1986-06"))

    def test_the_same_stay_with_a_different_bound_is_a_revision_not_a_duplicate(self):
        self.file_stay("Orchard House", "1982-08", "1986-06")
        proposal = self.propose(
            ORCHARD_LETTER, ScriptedCall(reading=reading(units=[self._orchard_unit()])),
            evidence="document", evidence_source="letters:grandma-1982-07-29")
        unit = proposal["units"][0]
        self.assertEqual(unit["duplicates"], [])
        self.assertEqual(unit["conflicts"], [])
        self.assertEqual(len(unit["revises"]), 1)
        row = unit["revises"][0]
        self.assertEqual(row["entry_id"], "residences/orchard house")
        self.assertEqual(row["bound"], "start")
        self.assertEqual(row["current"]["best"], "1982-08")
        self.assertEqual(row["current"]["basis"], "stated")
        self.assertEqual(row["proposed"]["best"], "1982-07")
        self.assertEqual(row["proposed"]["basis"], "document")
        self.assertEqual(row["winner"], "proposed")

    def test_a_revision_is_never_auto_file_eligible(self):
        self.file_stay("Orchard House", "1982-08", "1986-06")
        proposal = self.propose(
            ORCHARD_LETTER, ScriptedCall(reading=reading(units=[self._orchard_unit()])))
        unit = proposal["units"][0]
        self.assertTrue(unit["revises"])
        self.assertFalse(unit["auto_file_eligible"])

    def test_the_same_date_told_again_is_still_a_duplicate(self):
        self.file_stay("Orchard House", "1982-07", "1986-06")
        proposal = self.propose(
            ORCHARD_LETTER, ScriptedCall(reading=reading(units=[self._orchard_unit()])),
            evidence="document", evidence_source="letters:grandma-1982-07-29")
        unit = proposal["units"][0]
        self.assertEqual(unit["revises"], [])
        self.assertEqual(unit["duplicates"], ["residences/orchard house"])

    def test_a_relative_s_date_shows_the_filed_one_still_winning(self):
        """`relative` (5.5) sits under `stated` (6.0) by chronology's ruling:
        the card says so, and a yes files it as an alternate."""
        self.file_stay("Orchard House", "1982-08", "1986-06")
        proposal = self.propose(
            ORCHARD_LETTER, ScriptedCall(reading=reading(units=[self._orchard_unit()])),
            evidence="relative", evidence_source="witness:grandma")
        row = proposal["units"][0]["revises"][0]
        self.assertEqual(row["proposed"]["basis"], "relative")
        self.assertEqual(row["winner"], "current")
        self.assertIn("files as an alternate", lo.render_revision(row))

    def test_bound_revisions_is_pure_and_names_a_missing_bound_as_new(self):
        existing = {"label": "X", "span": {"start": chrono.parse_edtf("1990").to_dict()}}
        record = {"label": "X", "span": {"start": chrono.parse_edtf("1990").to_dict(),
                                         "end": chrono.parse_edtf("1992").to_dict()}}
        rows = lo.bound_revisions(existing, record, entry_id="residences/x")
        self.assertEqual([row["bound"] for row in rows], ["end"])
        self.assertIsNone(rows[0]["current"])
        self.assertEqual(rows[0]["winner"], "proposed")
        self.assertEqual(lo.REVISION_BOUNDS, ("date", "start", "end"))

    def test_revises_is_in_the_unit_contract_and_rendered(self):
        self.assertIn("revises", lo.UNIT_KEYS)
        self.file_stay("Orchard House", "1982-08", "1986-06")
        proposal = self.propose(
            ORCHARD_LETTER, ScriptedCall(reading=reading(units=[self._orchard_unit()])),
            evidence="document", evidence_source="letters:grandma-1982-07-29")
        rendered = lo.render_unit(proposal["units"][0])
        self.assertIn("revises residences/orchard house start: 1982-08 (stated, certain)"
                      " → 1982-07 (document, certain)", rendered)


# --------------------------------------------------------------------------
# Fixture 2 — an itinerary ends a stay a month later, and the memory stays
# --------------------------------------------------------------------------

ITINERARY = ("MISSION RETURN ITINERARY. 05 JUL 2002 - FRIDAY. LV: LAKESIDE "
             "955A. The stay at Lakeside, Switzerland ran from December 2001 "
             "to 5 July 2002.")


class DocumentWinsTests(EvidenceVaultCase):
    def _lakeside(self) -> dict:
        return read_unit("u1", "residences", "Lakeside, Switzerland", ITINERARY,
                         record={"label": "Lakeside, Switzerland",
                                 "city": "Lakeside"},
                         dates=read_dates("2001-12", "2002-07-05"))

    def test_a_document_date_outranks_the_remembered_one_and_keeps_it(self):
        self.file_stay("Lakeside, Switzerland", "2001-12", "2002-06-06",
                       city="Lakeside")
        proposal = self.propose(
            ITINERARY, ScriptedCall(reading=reading(units=[self._lakeside()])),
            evidence="document", evidence_source="letters:travel-itinerary")
        unit = proposal["units"][0]
        self.assertEqual([row["bound"] for row in unit["revises"]], ["end"])
        self.assertEqual(unit["revises"][0]["winner"], "proposed")
        receipt = lo.apply(proposal["proposal_id"], [unit["unit_id"]], self.root,
                           now=NOW)
        self.assertEqual(receipt["evidence"],
                         {"basis": "document", "source": "letters:travel-itinerary"})
        entries = self.entries("residences")
        self.assertEqual(len(entries), 1)
        end = entries[0]["span"]["end"]
        self.assertEqual(end["best"], "2002-07-05")
        self.assertEqual(end["basis"], "document")
        self.assertIn({"basis": "document", "source": "letters:travel-itinerary",
                       "claim": unit["quote"]["text"]}, end["provenance"])
        losers = entries[0][li.SPAN_ALTERNATES_KEY]["end"]
        self.assertEqual([row["best"] for row in losers], ["2002-06-06"])
        self.assertEqual(losers[0]["basis"], "stated")

    def test_apply_refuses_an_evidence_the_proposal_did_not_declare(self):
        proposal = self.propose(
            ITINERARY, ScriptedCall(reading=reading(units=[self._lakeside()])),
            evidence="document", evidence_source="letters:travel-itinerary")
        unit_ids = [proposal["units"][0]["unit_id"]]
        with self.assertRaises(lo.LandmarkOfferError) as caught:
            lo.apply(proposal["proposal_id"], unit_ids, self.root, now=NOW,
                     evidence="relative")
        self.assertEqual(caught.exception.code, "unsupported_input")
        with self.assertRaises(lo.LandmarkOfferError):
            lo.apply(proposal["proposal_id"], unit_ids, self.root, now=NOW,
                     evidence="document", evidence_source="letters:other")
        # The matching check passes, and naming nothing always passes.
        lo.apply(proposal["proposal_id"], unit_ids, self.root, now=NOW,
                 evidence="document", evidence_source="letters:travel-itinerary")


# --------------------------------------------------------------------------
# Fixture 3 — two stays at one address stay two
# --------------------------------------------------------------------------

RETURN_HOME = ("Dad wrote in July 2002 that David was back living with us on "
               "Willow Street from July 2002, the same house as before his "
               "mission.")


class TwoStaysTests(EvidenceVaultCase):
    def test_the_second_stay_is_revised_and_the_first_is_untouched(self):
        self.file_stay("Willow Street", "1997-06", "2000-08")
        self.file_stay("Willow Street", "2002-06-07", "2005-06")
        self.assertEqual(len(self.entries("residences")), 2)
        unit = read_unit("u1", "residences", "Willow Street", RETURN_HOME,
                         record={"label": "Willow Street", "city": "Orchard City"},
                         dates=read_dates("2002-07", "2005-06"))
        proposal = self.propose(
            RETURN_HOME, ScriptedCall(reading=reading(units=[unit])),
            evidence="relative", evidence_source="witness:dad")
        row = proposal["units"][0]
        self.assertEqual(row["duplicates"], [])
        self.assertEqual(row["conflicts"], [])
        self.assertEqual([r["bound"] for r in row["revises"]], ["start"])
        self.assertEqual(row["revises"][0]["current"]["best"], "2002-06-07")
        lo.apply(proposal["proposal_id"], [row["unit_id"]], self.root, now=NOW)
        entries = self.entries("residences")
        self.assertEqual(len(entries), 2)
        starts = sorted(entry["span"]["start"]["best"] for entry in entries)
        self.assertEqual(starts[0], "1997-06")
        first = next(e for e in entries if e["span"]["start"]["best"] == "1997-06")
        self.assertNotIn(li.SPAN_ALTERNATES_KEY, first)


# --------------------------------------------------------------------------
# Fixture 4 — a year inside a quote is the evidence's, never "stated"
# --------------------------------------------------------------------------

LETTER_YEAR = "The bishop's letter of 11 June 2001 says Pete came home in May 2001."


class EvidenceBasisTests(EvidenceVaultCase):
    def _unit(self) -> dict:
        return read_unit("u1", "work", "Pete's mission", LETTER_YEAR,
                         record={"label": "Pete's mission", "what": "mission"},
                         dates=read_dates(None, "2001-05"))

    def test_undeclared_a_year_in_the_text_is_stated_as_before(self):
        proposal = self.propose(LETTER_YEAR, ScriptedCall(reading=reading(units=[self._unit()])))
        unit = proposal["units"][0]
        self.assertEqual(unit["dates"]["basis"], "stated")
        self.assertEqual(unit["record"]["span"]["end"]["basis"], "stated")
        self.assertEqual(unit["record"]["span"]["end"]["provenance"], [])
        self.assertIsNone(proposal["evidence"])

    def test_declared_document_the_bound_is_a_document_s(self):
        proposal = self.propose(
            LETTER_YEAR, ScriptedCall(reading=reading(units=[self._unit()])),
            evidence="document", evidence_source="letters:bishop-2001-06-11")
        unit = proposal["units"][0]
        self.assertEqual(unit["dates"]["basis"], "document")
        bound = unit["record"]["span"]["end"]
        self.assertEqual(bound["basis"], "document")
        self.assertEqual(bound["confidence"], "certain")
        self.assertEqual(bound["provenance"], [{
            "basis": "document", "source": "letters:bishop-2001-06-11",
            "claim": LETTER_YEAR}])
        self.assertEqual(proposal["evidence"],
                         {"basis": "document", "source": "letters:bishop-2001-06-11"})
        self.assertEqual(lo.lint_offer_proposal(proposal), [])

    def test_the_bytes_test_still_drops_a_year_the_text_does_not_carry(self):
        unit = read_unit("u1", "work", "Pete's mission", LETTER_YEAR,
                         record={"label": "Pete's mission", "what": "mission"},
                         dates=read_dates("1999-04", "2001-05"))
        proposal = self.propose(
            LETTER_YEAR, ScriptedCall(reading=reading(units=[unit])),
            evidence="document", evidence_source="letters:bishop-2001-06-11")
        record = proposal["units"][0]["record"]
        self.assertNotIn("start", record["span"])
        self.assertEqual(record["span"]["end"]["basis"], "document")

    def test_a_declared_evidence_changes_the_proposal_id_an_undeclared_one_does_not(self):
        plain = self.propose(LETTER_YEAR, ScriptedCall(reading=reading(units=[self._unit()])))
        again = self.propose(LETTER_YEAR, ScriptedCall(reading=reading(units=[self._unit()])))
        evidenced = self.propose(
            LETTER_YEAR, ScriptedCall(reading=reading(units=[self._unit()])),
            evidence="document")
        self.assertEqual(plain["proposal_id"], again["proposal_id"])
        self.assertEqual(plain["proposal_id"],
                         lo.derive_proposal_id(LETTER_YEAR, plain["vault_generation"]))
        self.assertNotEqual(plain["proposal_id"], evidenced["proposal_id"])
        self.assertTrue(lo.is_current_proposal(evidenced, LETTER_YEAR))
        self.assertTrue(lo.is_current_proposal(plain, LETTER_YEAR))

    def test_an_unknown_evidence_is_refused_and_a_source_needs_a_basis(self):
        with self.assertRaises(lo.LandmarkOfferError) as caught:
            self.propose(LETTER_YEAR, ScriptedCall(), evidence="photo")
        self.assertEqual(caught.exception.code, "unsupported_input")
        with self.assertRaises(lo.LandmarkOfferError):
            self.propose(LETTER_YEAR, ScriptedCall(), evidence_source="letters:x")
        self.assertEqual(lo.EVIDENCE_BASES, ("relative", "document"))
        for basis in lo.EVIDENCE_BASES:
            self.assertIn(basis, chrono.BASES)
            self.assertIn(basis, lo.UNIT_BASES)

    def test_the_lint_names_an_evidence_bound_with_no_provenance(self):
        proposal = self.propose(
            LETTER_YEAR, ScriptedCall(reading=reading(units=[self._unit()])),
            evidence="document", evidence_source="letters:bishop-2001-06-11")
        stripped = json.loads(json.dumps(proposal))
        stripped["units"][0]["record"]["span"]["end"]["provenance"] = []
        findings = lo.lint_offer_proposal(stripped)
        self.assertEqual([f["lint"] for f in findings], [lo.HONEST_BASIS_LINT])

    def test_the_host_run_road_carries_the_evidence_too(self):
        completion = {"reading": reading(units=[self._unit()])}
        proposal = lo.propose_from_completions(
            LETTER_YEAR, self.root, completion, now=NOW,
            evidence="relative", evidence_source="witness:bishop")
        self.assertEqual(proposal["units"][0]["dates"]["basis"], "relative")
        self.assertEqual(proposal["evidence"],
                         {"basis": "relative", "source": "witness:bishop"})


class CliFlagTests(unittest.TestCase):
    def test_the_outer_and_inner_clis_carry_the_evidence_flags(self):
        import lifehug  # noqa: PLC0415

        parser = lifehug.build_parser()
        offer = next(action.choices["landmark-offer"]
                     for action in parser._subparsers._group_actions  # noqa: SLF001
                     if "landmark-offer" in getattr(action, "choices", ()))
        dests = {action.dest for action in offer._actions}  # noqa: SLF001
        self.assertIn("evidence", dests)
        self.assertIn("evidence_source", dests)
        out = io.StringIO()
        with contextlib.redirect_stderr(out), self.assertRaises(SystemExit):
            lo.main(["--propose", "--evidence", "photo"])
        self.assertIn("invalid choice", out.getvalue())


if __name__ == "__main__":
    unittest.main()
