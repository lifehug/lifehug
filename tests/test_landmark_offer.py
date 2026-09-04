"""Add Landmark, the `offer` mode of the Landmarks Interaction.

Controlling design: `lifehug-platform
docs/decisions/2026-09-03-timeline-unification/decision-record.md` — R3, R3a,
R3b, §4.2 (weight tiers), §5 — and, for the reading, that program's
`add-landmark-reading-plan.md` §2 (R6–R9) and §3.1/§3.2. ADR 0033 and its Cut
6f amendment.

Cut 6f (v291) replaced the three extraction passes with ONE reading, so every
test here scripts ONE completion in the reading contract's own shape. No live
model call anywhere — the same recorded discipline `tests/test_landmarks.py`
uses for the recorder.

Synthetic data only; NEVER references ~/Workspace/dave.
"""

from __future__ import annotations

import contextlib
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SYSTEM = ROOT / "system"
sys.path.insert(0, str(SYSTEM))
sys.path.insert(0, str(ROOT / "tests"))

import entity_roster  # noqa: E402
import landmark_offer as lo  # noqa: E402
import landmark_projection as lp  # noqa: E402
import landmarks_interaction as li  # noqa: E402
import temporal_publication as pub  # noqa: E402
import temporal_store as ts  # noqa: E402
import timeline  # noqa: E402
from tempdirs import root_parent_tmp  # noqa: E402

NOW = "2026-09-03T00:00:00Z"


# --------------------------------------------------------------------------
# A synthetic vault, wired exactly as tests/test_go_dig.py wires one
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


def _date(best: str, *, grain: str = "year", confidence: str = "certain",
          basis: str = "stated") -> dict:
    return {"best": best, "earliest": None, "latest": None,
            "granularity": grain, "confidence": confidence, "basis": basis,
            "anchors": [], "provenance": []}


def _span(start: str, end: str | None, **kwargs) -> dict:
    span = {"start": _date(start, **kwargs)}
    if end:
        span["end"] = _date(end, **kwargs)
    return span


def reading(units=(), events=(), stories=(), unplaced=()) -> dict:
    """One reading completion, in §3.1's own shape."""
    return {"units": list(units), "events": list(events),
            "stories": list(stories), "unplaced": list(unplaced)}


def read_unit(ref: str, domain: str, subject: str, quote: str, *,
              record=None, names=None, dates=None, within=None) -> dict:
    row = {"ref": ref, "domain": domain, "subject": subject, "quote": quote,
           "record": dict(record or {}), "dates": dates, "within": within}
    if names:
        row["names"] = dict(names)
    return row


def read_dates(start=None, end=None, *, ongoing=False,
               start_estimated=False, end_estimated=False) -> dict:
    return {"start": start, "end": end, "ongoing": ongoing,
            "start_estimated": start_estimated,
            "end_estimated": end_estimated}


class ScriptedCall:
    """One injected ``call`` that answers the ONE reading (Cut 6f, R6/R9).

    There is one prompt per submission now, so there is nothing to dispatch
    on: whatever `propose` composes, this answers with the scripted reading.
    """

    EMPTY = lo.EMPTY_COMPLETION

    def __init__(self, *, reading: object = None):
        self.reading = reading if reading is not None else self.EMPTY
        self.prompts: list[str] = []

    def __call__(self, prompt: str, model: str) -> str:
        self.prompts.append(prompt)
        return (self.reading if isinstance(self.reading, str)
                else json.dumps(self.reading))


class OfferVaultCase(unittest.TestCase):
    def setUp(self) -> None:
        tmp = root_parent_tmp(self, ROOT, prefix="offer-")
        self._ctx = synthetic_vault(tmp)
        self.root = self._ctx.__enter__()
        self.addCleanup(self._ctx.__exit__, None, None, None)

    def landmarks(self) -> dict:
        path = self.root / "state" / "landmarks.json"
        if not path.is_file():
            return {}
        return json.loads(path.read_text()).get("domains", {})

    def entries(self, domain: str) -> list:
        return list(self.landmarks().get(domain) or ())

    def propose(self, text: str, call) -> dict:
        return lo.propose(text, self.root, call=call, now=NOW)


# --------------------------------------------------------------------------
# The mode itself (R3b): no new interaction kind
# --------------------------------------------------------------------------


class ModeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.manifest = (ROOT / "interactions" / "landmarks"
                         / "interaction.yaml").read_text(encoding="utf-8")

    def test_the_manifest_declares_both_modes(self):
        self.assertIn(f"modes: {'|'.join(lo.MODES)}", self.manifest)
        self.assertEqual(lo.MODES, ("collect", "offer"))

    def test_the_offer_leaf_is_its_own_composition_slot(self):
        """Declaring the slot and naming it in code stay one edit."""
        self.assertIn(f"composition.offer_turn: prompt/{lo.OFFER_TURN_PROMPT}",
                      self.manifest)
        self.assertTrue((ROOT / "interactions" / "landmarks" / "prompt"
                         / lo.OFFER_TURN_PROMPT).is_file())
        self.assertIn("role.worker: sonnet-class", self.manifest)

    def test_the_offer_turn_composes_from_the_leaf(self):
        proposal = {
            "units": [{"kind": "residence", "subject": "Mesa",
                       "dates": {"start": "1990", "end": "1992",
                                 "basis": "stated", "confidence": "certain"},
                       "quote": {"text": "I lived in Mesa from 1990 to 1992."},
                       "questions": ["Do you remember the address on Mesa?"]}],
            "stories": [], "unrecognized": [],
            "questions": [{"domain": "residences", "text": "Where was that?"}],
        }
        turn = lo.build_offer_turn(proposal, landmark_stage="ask")
        self.assertNotIn("{proposed_units}", turn)
        self.assertNotIn("{open_questions}", turn)
        self.assertNotIn("{filing_gain}", turn)
        self.assertIn("LANDMARK_STAGE: ask", turn)
        self.assertIn("residence: Mesa — 1990–1992", turn)
        self.assertIn("Where was that?", turn)
        self.assertIn("Do you remember the address on Mesa?", turn)

    def test_an_inferred_date_is_shown_with_the_clause_that_earned_it(self):
        """§3.2: an inherited date renders its own provenance sentence
        VERBATIM, and one with no clause falls back to the general one."""
        clause = "from the dates of the Orchard House stay"
        turn = lo.build_offer_turn({"units": [
            {"kind": "schooling", "subject": "Kestrel Elementary",
             "dates": {"start": "1981", "end": "1982", "basis": "inferred",
                       "clause": clause},
             "quote": {"text": "School: Kestrel Elementary"},
             "questions": []}],
            "stories": [], "unrecognized": [], "questions": []})
        self.assertIn(clause, turn)
        bare = lo.build_offer_turn({"units": [
            {"kind": "residence", "subject": "Cedarport",
             "dates": {"start": "1993", "end": None, "basis": "inferred",
                       "clause": None},
             "quote": {"text": "Then Cedarport for a while."},
             "questions": []}], "stories": [], "unrecognized": [],
            "questions": []})
        self.assertIn(lo.INFERRED_CLAUSE, bare)

    def test_a_unit_with_no_date_read_says_so(self):
        turn = lo.build_offer_turn({"units": [
            {"kind": "residence", "subject": "Cedarport",
             "dates": {"start": None, "end": None, "basis": "none"},
             "quote": {"text": "Then Cedarport for a while."},
             "questions": []}], "stories": [], "unrecognized": [],
            "questions": []})
        self.assertIn(lo.NO_DATE_READ, turn)

    def test_the_registry_gains_no_interaction_kind(self):
        import interaction_registry as reg  # noqa: PLC0415

        registry = reg.load_interaction_registry()
        ids = [row["id"] for row in registry["interactions"]]
        self.assertIn("landmarks", ids)
        self.assertEqual(len(ids), len(set(ids)))
        for forbidden in ("landmark_offer", "add_landmark", "offer", "go_dig"):
            self.assertNotIn(forbidden, ids)

    def test_the_package_still_audits_clean(self):
        import interaction_registry as reg  # noqa: PLC0415

        self.assertEqual(reg.audit_interaction_package("landmarks"), [])

    def test_the_offer_leaf_is_under_its_declared_budget(self):
        leaf = (ROOT / "interactions" / "landmarks" / "prompt"
                / "turn-instructions-offer.md").read_text(encoding="utf-8")
        budget = int([line.split(": ")[1] for line in self.manifest.splitlines()
                      if line.startswith("budget.offer_turn: ")][0])
        self.assertLess(len(leaf), budget * 4)

    def test_the_offer_leaf_never_names_the_retired_product(self):
        """R4: nothing user-facing may mention Go Dig."""
        for path in (ROOT / "interactions" / "landmarks" / "prompt"
                     / "turn-instructions-offer.md",
                     ROOT / "interactions" / "landmarks" / "context"
                     / "manifest.md"):
            body = path.read_text(encoding="utf-8").lower()
            for forbidden in ("go dig", "go-dig", "go_dig", "reading room"):
                self.assertNotIn(forbidden, body, path.name)

    def test_every_domain_has_a_unit_word(self):
        domains = {row["domain"] for row in li.load_questions()}
        self.assertEqual(set(lo.UNIT_KIND_BY_DOMAIN), domains)

    def test_the_event_kind_routing_is_a_subset_of_the_claim_vocabulary(self):
        import temporal_claims as tc  # noqa: PLC0415

        self.assertTrue(set(lo.DOMAIN_BY_EVENT_KIND) <= set(tc.EVENT_KINDS))
        self.assertTrue(set(lo.DOMAIN_BY_EVENT_KIND.values())
                        <= {row["domain"] for row in li.load_questions()})


# --------------------------------------------------------------------------
# §5.6, example by example
# --------------------------------------------------------------------------


MESA = "I lived in Mesa from 1990 to 1992."
MESA_READING = reading(units=[read_unit(
    "u1", "residences", "Mesa", MESA, record={"city": "Mesa", "label": "Mesa"},
    names={"city": "Mesa"}, dates=read_dates("1990", "1992"))])

BOATWORKS = "I worked at the Boatworks from about '91 to '92."
BOATWORKS_READING = reading(units=[read_unit(
    "u1", "work", "the Boatworks", BOATWORKS,
    record={"what": "boat building", "label": "the Boatworks"},
    dates=read_dates("1991", "1992", start_estimated=True,
                     end_estimated=True))])

MOVED = "We moved around a lot after Dad changed jobs."
MOVED_READING = reading(events=[
    {"ref": "e1", "text": "we moved around a lot", "kind": "move",
     "subject_mention": "self", "date": None, "within": None,
     "quote": MOVED}])

DOG = "My dog died that summer."
DOG_READING = reading(stories=[{"quote": DOG, "within": None}])

#: One stay with a school inside it — R7's own shape, in one sentence.
ELM = ("I lived on Elm from 1990 to 1992, we called it the blue house, "
       "I was at Lincoln Elementary then, and Dad started at the mill "
       "that spring.")
ELM_READING = reading(
    units=[
        read_unit("u1", "residences", "the blue house",
                  "I lived on Elm from 1990 to 1992, we called it the blue house",
                  record={"city": "Elm", "label": "the blue house"},
                  names={"nickname": "the blue house", "city": "Elm"},
                  dates=read_dates("1990", "1992")),
        read_unit("u2", "schools", "Lincoln Elementary",
                  "I was at Lincoln Elementary then",
                  record={"name": "Lincoln Elementary",
                          "label": "Lincoln Elementary"},
                  within="u1"),
    ],
    events=[{"ref": "e1", "text": "Dad started at the mill", "kind": "job",
             "subject_mention": "Dad", "date": None, "within": "u1",
             "quote": "and Dad started at the mill that spring."}])


class OneReadingTests(OfferVaultCase):
    """R6/R9: one prompt, one completion, and everything after it
    deterministic."""

    def test_a_stated_residence_is_one_certain_quoted_unit(self):
        call = ScriptedCall(reading=MESA_READING)
        proposal = self.propose(MESA, call)
        self.assertEqual(proposal["state"], "proposed")
        self.assertEqual(len(proposal["units"]), 1)
        unit = proposal["units"][0]
        self.assertEqual(unit["domain"], "residences")
        self.assertEqual(unit["kind"], "residence")
        self.assertEqual(unit["subject"], "Mesa")
        self.assertEqual(unit["dates"], {
            "start": "1990", "end": "1992", "precision": "year",
            "basis": "stated", "confidence": "certain",
            "estimated": {"start": False, "end": False},
            "inherited_from": None, "clause": None})
        self.assertEqual(unit["quote"]["text"], MESA)
        self.assertIsNone(unit["within"])
        self.assertEqual(unit["names"], {"city": "Mesa"})
        self.assertTrue(unit["auto_file_eligible"])
        self.assertEqual(unit["questions"], [])
        self.assertEqual(proposal["questions"], [])
        self.assertEqual(lo.lint_offer_proposal(proposal), [])

    def test_the_reading_is_exactly_one_model_call(self):
        """R9: a long paste is ONE reading. No grammar first, no second pass,
        no per-domain call."""
        call = ScriptedCall(reading=ELM_READING)
        self.propose(ELM, call)
        self.assertEqual(len(call.prompts), 1)
        self.assertIn("THE DOMAINS, AND THE ONLY KEYS EACH ONE CAN READ",
                      call.prompts[0])
        self.assertNotIn("DOMAIN BEING ASKED ABOUT:", call.prompts[0])

    def test_the_prompt_is_the_reading_leaf_with_the_live_vocabulary(self):
        import general_listener as gl  # noqa: PLC0415
        import landmark_reading as lr  # noqa: PLC0415

        call = ScriptedCall(reading=MESA_READING)
        self.propose(MESA, call)
        prompt = call.prompts[0]
        self.assertIn(gl.render_domain_digest(), prompt)
        self.assertIn(lr.render_name_keys(), prompt)
        self.assertIn(MESA, prompt)

    def test_an_estimated_bound_is_approximate_and_says_so(self):
        """R8: brackets, 'about', '?' are the person's own convention and the
        system's word for them is `approximate`."""
        call = ScriptedCall(reading=BOATWORKS_READING)
        proposal = self.propose(BOATWORKS, call)
        unit = proposal["units"][0]
        self.assertEqual(unit["kind"], "tenure")
        self.assertEqual(unit["dates"]["basis"], "stated")
        self.assertEqual(unit["dates"]["confidence"], "approximate")
        self.assertEqual(unit["dates"]["estimated"],
                         {"start": True, "end": True})
        self.assertIn(lo.ESTIMATED_PHRASE, lo.render_unit(unit))
        self.assertEqual([c["confidence"] for c in unit["entity_candidates"]],
                         ["new"])
        self.assertEqual(unit["entity_candidates"][0]["type"], "organization")
        self.assertEqual(lo.lint_offer_proposal(proposal), [])

    def test_a_bracketed_bound_read_as_certain_is_a_finding(self):
        proposal = {
            "source_text": BOATWORKS,
            "units": [{"unit_id": "lmu:x", "record": {},
                       "quote": {"text": BOATWORKS, "offset": 0,
                                 "length": len(BOATWORKS)},
                       "dates": {"basis": "stated", "confidence": "certain",
                                 "estimated": {"start": True, "end": False},
                                 "clause": None}}],
            "events": [], "stories": [], "unrecognized": [],
        }
        self.assertEqual([row["lint"] for row in
                          lo.lint_offer_proposal(proposal)],
                         [lo.HONEST_BASIS_LINT])

    def test_the_two_digit_year_the_person_wrote_is_still_their_own_date(self):
        self.assertTrue(lo.date_evidence(_date("1991"), {"text": BOATWORKS},
                                         BOATWORKS))
        self.assertFalse(lo.date_evidence(_date("1994"), {"text": BOATWORKS},
                                          BOATWORKS))

    def test_a_month_the_person_abbreviated_is_still_their_own_date(self):
        """v291: `chronology.parse_loose_date` reads `Jun 1986`, so an
        evidence guard that only looked for `june` dropped the very date they
        typed."""
        text = "Dates: [Jun 1986] - March 1991"
        import chronology as chrono  # noqa: PLC0415

        for value in ("Jun 1986", "March 1991"):
            with self.subTest(value=value):
                self.assertTrue(lo.date_evidence(
                    chrono.normalized_date(value), {"text": text}, text))

    def test_vague_movement_fabricates_no_residence_and_asks_where(self):
        call = ScriptedCall(reading=MOVED_READING)
        proposal = self.propose(MOVED, call)
        self.assertEqual(proposal["units"], [])
        self.assertEqual(proposal["state"], "needs_clarification")
        self.assertEqual(len(proposal["questions"]), 1)
        question = proposal["questions"][0]
        self.assertEqual(question["domain"], "residences")
        self.assertIn("where", question["text"].lower())
        self.assertNotIn("199", question["text"])
        # The words themselves are retained, not thrown away — the event's own
        # quote covers them.
        self.assertEqual([event["quote"]["text"]
                          for event in proposal["events"]], [MOVED])
        self.assertEqual(proposal["events"][0]["filing"], "moment")

    def test_a_story_is_routed_as_a_story_and_never_refused(self):
        call = ScriptedCall(reading=DOG_READING)
        proposal = self.propose(DOG, call)
        self.assertEqual(proposal["units"], [])
        self.assertEqual([span["text"] for span in proposal["stories"]], [DOG])
        self.assertEqual([span["route"] for span in proposal["stories"]],
                         [lo.STORY_KIND])
        rendered = lo.render_proposal(proposal)
        self.assertIn("Read as story", rendered)
        self.assertEqual(lo.lint_offer_reply(
            "I've kept that as a story — it isn't one of the dated anchors."),
            [])

    def test_a_school_inside_a_stay_inherits_its_dates_and_says_where_from(self):
        """R7 rule 4, and the clause is rendered verbatim."""
        call = ScriptedCall(reading=ELM_READING)
        proposal = self.propose(ELM, call)
        by_subject = {unit["subject"]: unit for unit in proposal["units"]}
        stay = by_subject["the blue house"]
        school = by_subject["Lincoln Elementary"]
        self.assertEqual(school["within"], stay["unit_id"])
        self.assertEqual(school["dates"]["basis"], "inferred")
        self.assertEqual(school["dates"]["confidence"], "inferred")
        self.assertEqual(school["dates"]["start"], stay["dates"]["start"])
        self.assertEqual(school["dates"]["end"], stay["dates"]["end"])
        clause = "from the dates of the the blue house stay"
        self.assertEqual(school["dates"]["clause"], clause)
        self.assertEqual(school["dates"]["inherited_from"]["unit_id"],
                         stay["unit_id"])
        self.assertIn(clause, lo.render_unit(school))
        self.assertIn({"basis": "inferred", "claim": clause},
                      school["record"]["span"]["start"]["provenance"])
        # An inherited date carries its own provenance, so it is not asked
        # about a second time.
        self.assertEqual(school["questions"], [])
        self.assertEqual(lo.lint_offer_proposal(proposal), [])

    def test_a_dated_event_files_as_a_claim_and_an_undated_one_as_a_moment(self):
        call = ScriptedCall(reading=ELM_READING)
        proposal = self.propose(ELM, call)
        self.assertEqual(len(proposal["events"]), 1)
        event = proposal["events"][0]
        self.assertEqual(sorted(event), sorted(lo.EVENT_KEYS))
        self.assertEqual(event["filing"], "moment")
        self.assertIsNone(event["date"])
        self.assertEqual(event["within"], proposal["units"][0]["unit_id"])
        self.assertTrue(lo.valid_id(event["event_id"]))

    def test_an_event_quote_counts_as_coverage(self):
        call = ScriptedCall(reading=ELM_READING)
        proposal = self.propose(ELM, call)
        self.assertEqual(proposal["stories"], [])
        self.assertEqual(proposal["unrecognized"], [])
        self.assertEqual(lo.lint_offer_proposal(proposal), [])

    def test_a_unit_with_no_dates_and_no_dated_parent_reads_no_date(self):
        """R7 rule 5 / D5: `basis: none`, never `inferred`."""
        text = "We were in Cedarport for a while."
        call = ScriptedCall(reading=reading(units=[read_unit(
            "u1", "residences", "Cedarport", text,
            record={"city": "Cedarport", "label": "Cedarport"})]))
        proposal = self.propose(text, call)
        unit = proposal["units"][0]
        self.assertEqual(unit["dates"]["basis"], "none")
        self.assertIsNone(unit["dates"]["start"])
        self.assertIsNone(unit["dates"]["clause"])
        self.assertIn(lo.NO_DATE_READ, lo.render_unit(unit))
        self.assertTrue(unit["questions"])
        self.assertFalse(unit["auto_file_eligible"])

    def test_the_extraction_role_is_the_one_the_manifest_declares(self):
        import landmark_reading as lr  # noqa: PLC0415

        manifest = (ROOT / "interactions" / "landmarks"
                    / "interaction.yaml").read_text(encoding="utf-8")
        self.assertIn(f"role.reading: {lr.DEFAULT_READING_ROLE}", manifest)
        self.assertIn("role.worker: sonnet-class", manifest)

    def test_no_model_call_recalculates_a_date(self):
        """Every interval that files is `chronology`'s, derived from the
        person's own words — the offer path never asks a model for one."""
        import ast  # noqa: PLC0415

        source = (SYSTEM / "landmark_offer.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        called = {node.func.attr for node in ast.walk(tree)
                  if isinstance(node, ast.Call)
                  and isinstance(node.func, ast.Attribute)}
        self.assertNotIn("call_ai", called)
        # R6: the listener and the recorder are gone from this module
        # entirely. (`plan_import` survives inside `grammar_units`, which
        # nothing calls any more and Cut 6h deletes — the test below proves
        # `propose` does not reach it.)
        self.assertEqual(called & {"listen_to_answer", "record_answer"},
                         set())

    def test_the_offer_path_composes_no_listener_and_no_recorder(self):
        """R6, read off the source: `propose` must not reach the collect
        mode's own extraction passes."""
        source = (SYSTEM / "landmark_offer.py").read_text(encoding="utf-8")
        body = source[source.index("def propose("):
                      source.index("def _extractors(")]
        for forbidden in ("listen_to_answer", "record_answer", "grammar_units",
                          "build_listener_prompt", "build_recorder_prompt"):
            self.assertNotIn(forbidden, body)


# --------------------------------------------------------------------------
# Stated versus inferred (§4.2)
# --------------------------------------------------------------------------


class BasisTests(OfferVaultCase):
    def test_a_bound_the_text_does_not_carry_is_dropped_not_rewritten(self):
        """§3.1 rule 2, and D5: a year nobody typed is not turned into a
        confident-looking inference — it is dropped, and the unit says no date
        was read."""
        text = "I lived in Mesa from 1990 to 1992. Then Cedarport for a while."
        call = ScriptedCall(reading=reading(units=[
            read_unit("u1", "residences", "Mesa",
                      "I lived in Mesa from 1990 to 1992.",
                      record={"city": "Mesa", "label": "Mesa"},
                      dates=read_dates("1990", "1992")),
            read_unit("u2", "residences", "Cedarport",
                      "Then Cedarport for a while.",
                      record={"city": "Cedarport", "label": "Cedarport"},
                      dates=read_dates("1993", "1996")),
        ]))
        proposal = self.propose(text, call)
        by_subject = {unit["subject"]: unit for unit in proposal["units"]}
        self.assertEqual(by_subject["Mesa"]["dates"]["basis"], "stated")
        cedar = by_subject["Cedarport"]
        self.assertEqual(cedar["dates"]["basis"], "none")
        self.assertNotIn("span", cedar["record"])
        self.assertFalse(cedar["auto_file_eligible"])
        self.assertTrue(cedar["questions"])
        self.assertEqual(lo.lint_offer_proposal(proposal), [])

    def test_the_lint_refuses_a_date_the_text_does_not_carry(self):
        proposal = {
            "source_text": "I lived in Mesa.",
            "units": [{"unit_id": "lmu:x", "dates": {"basis": "stated"},
                       "quote": {"text": "I lived in Mesa.", "offset": 0,
                                 "length": 16},
                       "record": {"date": _date("1990")}}],
            "events": [], "stories": [], "unrecognized": [],
        }
        findings = lo.lint_offer_proposal(proposal)
        self.assertEqual([row["lint"] for row in findings],
                         [lo.NO_FABRICATED_DATE_LINT])

    def test_the_lint_refuses_an_inference_that_names_no_source(self):
        proposal = {
            "source_text": "I lived in Mesa.",
            "units": [{"unit_id": "lmu:x", "record": {},
                       "quote": {"text": "I lived in Mesa.", "offset": 0,
                                 "length": 16},
                       "dates": {"basis": "inferred", "clause": None}}],
            "events": [], "stories": [], "unrecognized": [],
        }
        self.assertEqual([row["lint"] for row in
                          lo.lint_offer_proposal(proposal)],
                         [lo.HONEST_BASIS_LINT])

    def test_the_lint_refuses_a_quote_that_is_not_in_the_text(self):
        proposal = {
            "source_text": "I lived in Mesa.",
            "units": [{"unit_id": "lmu:x", "record": {}, "dates": {},
                       "quote": {"text": "I lived in Tempe.", "offset": 0,
                                 "length": 17}}],
            "events": [], "stories": [], "unrecognized": [],
        }
        self.assertIn(lo.QUOTES_LOCATE_LINT,
                      [row["lint"] for row in lo.lint_offer_proposal(proposal)])

    def test_a_model_declaring_stated_over_a_year_nobody_typed_is_answered(self):
        """§4.2: the completion does not get to decide this."""
        text = "I lived in Mesa for a couple of years."
        call = ScriptedCall(reading=reading(units=[read_unit(
            "u1", "residences", "Mesa", text,
            record={"city": "Mesa", "label": "Mesa"},
            dates=read_dates("1990", "1992"))]))
        proposal = self.propose(text, call)
        unit = proposal["units"][0]
        self.assertEqual(unit["dates"]["basis"], "none")
        self.assertNotIn("span", unit["record"])
        self.assertEqual(lo.lint_offer_proposal(proposal), [])


# --------------------------------------------------------------------------
# What the vault already knows
# --------------------------------------------------------------------------


class KnownEntriesTests(OfferVaultCase):
    def _file_phoenix(self) -> None:
        import chronology as chrono  # noqa: PLC0415

        timeline.save_landmark("residences", {
            "domain": "residences", "label": "Phoenix", "city": "Phoenix",
            "span": {"start": chrono.parse_edtf("1980").to_dict(),
                     "end": chrono.parse_edtf("1985").to_dict()}})

    def test_a_second_stay_in_a_known_city_is_a_second_entry(self):
        self._file_phoenix()
        text = "I lived in Phoenix again from 1995 to 1999."
        call = ScriptedCall(reading=reading(units=[read_unit(
            "u1", "residences", "Phoenix", text,
            record={"city": "Phoenix", "label": "Phoenix"},
            dates=read_dates("1995", "1999"))]))
        proposal = self.propose(text, call)
        unit = proposal["units"][0]
        self.assertEqual(unit["duplicates"], [])
        self.assertEqual(unit["conflicts"], [])
        receipt = lo.apply(proposal["proposal_id"], [unit["unit_id"]],
                           self.root, now=NOW)
        self.assertEqual(len(receipt["filed"]), 1)
        self.assertEqual(len(self.entries("residences")), 2)

    def test_the_same_stay_told_again_is_a_duplicate(self):
        self._file_phoenix()
        text = "I lived in Phoenix from 1980 to 1985."
        call = ScriptedCall(reading=reading(units=[read_unit(
            "u1", "residences", "Phoenix", text,
            record={"city": "Phoenix", "label": "Phoenix"},
            dates=read_dates("1980", "1985"))]))
        proposal = self.propose(text, call)
        unit = proposal["units"][0]
        self.assertEqual(unit["duplicates"], ["residences/phoenix"])
        self.assertFalse(unit["auto_file_eligible"])

    def test_the_reading_is_shown_what_is_already_filed(self):
        self._file_phoenix()
        call = ScriptedCall()
        self.propose("I lived in Mesa too.", call)
        self.assertEqual(len(call.prompts), 1)
        self.assertIn("ALREADY FILED", call.prompts[0])
        self.assertIn("Phoenix", call.prompts[0])


# --------------------------------------------------------------------------
# Filing, idempotency, rebuild, undo
# --------------------------------------------------------------------------


class ApplyTests(OfferVaultCase):
    def _mesa_proposal(self) -> dict:
        return self.propose(MESA, ScriptedCall(reading=MESA_READING))

    def test_nothing_is_filed_before_a_person_confirms(self):
        proposal = self._mesa_proposal()
        self.assertEqual(self.entries("residences"), [])
        self.assertEqual(lp.load_landmark_sources(self.root), [])
        path = lo.proposal_path(self.root, proposal["proposal_id"])
        self.assertTrue(path.is_file())
        self.assertEqual(json.loads(path.read_text())["source_text"], MESA)

    def test_applying_twice_files_one_set_and_returns_one_receipt(self):
        proposal = self._mesa_proposal()
        unit_ids = [unit["unit_id"] for unit in proposal["units"]]
        first = lo.apply(proposal["proposal_id"], unit_ids, self.root, now=NOW)
        sources = list(lp.load_landmark_sources(self.root))
        entries = self.entries("residences")
        second = lo.apply(proposal["proposal_id"], unit_ids, self.root, now=NOW)
        self.assertEqual(first["receipt_id"], second["receipt_id"])
        self.assertEqual(first, second)
        self.assertEqual(len(lp.load_landmark_sources(self.root)), len(sources))
        self.assertEqual(self.entries("residences"), entries)
        self.assertEqual(len(entries), 1)

    def test_the_filing_identity_is_the_proposal_and_the_unit_never_an_ordinal(self):
        proposal = self._mesa_proposal()
        unit = proposal["units"][0]
        relative = lo.unit_source_relative_path(proposal["proposal_id"], unit)
        lo.apply(proposal["proposal_id"], [unit["unit_id"]], self.root, now=NOW)
        self.assertTrue((self.root / relative).is_file())

    def test_a_rebuild_reproduces_the_same_projection(self):
        proposal = self._mesa_proposal()
        lo.apply(proposal["proposal_id"],
                 [unit["unit_id"] for unit in proposal["units"]], self.root,
                 now=NOW)
        before = pub.read_projection(self.root)
        drawn = self.entries("residences")
        timeline.redraw_landmarks()
        after = pub.read_projection(self.root)
        self.assertEqual(self.entries("residences"), drawn)
        self.assertEqual(pub.rebuild_signature(before),
                         pub.rebuild_signature(after))

    def test_the_receipt_carries_the_realized_gain_sentence(self):
        proposal = self._mesa_proposal()
        receipt = lo.apply(proposal["proposal_id"],
                           [unit["unit_id"] for unit in proposal["units"]],
                           self.root, now=NOW)
        self.assertTrue(receipt["sentence"])
        self.assertIn("summary", receipt["gain"])
        self.assertEqual(receipt["filed"][0]["basis"], "stated")

    def test_a_confirmed_unit_files_through_the_one_landmark_writer(self):
        proposal = self._mesa_proposal()
        lo.apply(proposal["proposal_id"],
                 [unit["unit_id"] for unit in proposal["units"]], self.root,
                 now=NOW)
        entry = self.entries("residences")[0]
        self.assertEqual(entry["city"], "Mesa")
        self.assertEqual(entry["span"]["start"]["basis"], "stated")
        self.assertTrue(entry.get("place_ref"))

    def test_the_submitted_text_becomes_an_ordinary_vault_source(self):
        proposal = self._mesa_proposal()
        receipt = lo.apply(proposal["proposal_id"],
                           [unit["unit_id"] for unit in proposal["units"]],
                           self.root, now=NOW)
        self.assertTrue(receipt["evidence_ref"]["source_id"])

    def test_an_unknown_unit_is_a_typed_refusal(self):
        proposal = self._mesa_proposal()
        with self.assertRaises(lo.LandmarkOfferError) as caught:
            lo.apply(proposal["proposal_id"], ["lmu:" + "0" * 24], self.root)
        self.assertEqual(caught.exception.code, "unsupported_input")

    def test_confirming_nothing_is_a_typed_refusal(self):
        proposal = self._mesa_proposal()
        with self.assertRaises(lo.LandmarkOfferError) as caught:
            lo.apply(proposal["proposal_id"], [], self.root)
        self.assertEqual(caught.exception.code, "content_ambiguity")


class RetractTests(OfferVaultCase):
    def test_undo_keeps_the_evidence_and_the_receipt(self):
        call = ScriptedCall(reading=MESA_READING)
        proposal = self.propose(MESA, call)
        receipt = lo.apply(proposal["proposal_id"],
                           [unit["unit_id"] for unit in proposal["units"]],
                           self.root, now=NOW)
        source_paths = [row["relative_path"]
                        for row in lp.load_landmark_sources(self.root)]
        self.assertEqual(len(self.entries("residences")), 1)

        retraction = lo.retract(receipt["receipt_id"], self.root, now=NOW)

        self.assertEqual(self.entries("residences"), [])
        self.assertTrue(retraction["corrections"])
        self.assertTrue(lo.offer_receipt_path(self.root,
                                              receipt["receipt_id"]).is_file())
        self.assertTrue(lo.proposal_path(self.root,
                                         proposal["proposal_id"]).is_file())
        for relative in source_paths:
            self.assertTrue((self.root / relative).is_file(), relative)
        self.assertTrue(lo.receipt_is_retracted(self.root,
                                                receipt["receipt_id"]))

    def test_undo_is_idempotent(self):
        call = ScriptedCall(reading=MESA_READING)
        proposal = self.propose(MESA, call)
        receipt = lo.apply(proposal["proposal_id"],
                           [unit["unit_id"] for unit in proposal["units"]],
                           self.root, now=NOW)
        first = lo.retract(receipt["receipt_id"], self.root, now=NOW)
        second = lo.retract(receipt["receipt_id"], self.root, now=NOW)
        self.assertEqual(first, second)


# --------------------------------------------------------------------------
# The proposal file, the states and the failures
# --------------------------------------------------------------------------


class ProposalFileTests(OfferVaultCase):
    def test_unrecognized_text_is_retained_in_the_proposal(self):
        text = "I lived in Mesa from 1990 to 1992.\n\n???"
        call = ScriptedCall(reading=MESA_READING)
        proposal = self.propose(text, call)
        self.assertEqual([span["text"] for span in proposal["unrecognized"]],
                         ["???"])
        stored = json.loads(lo.proposal_path(
            self.root, proposal["proposal_id"]).read_text())
        self.assertEqual(stored["unrecognized"], proposal["unrecognized"])

    def test_every_span_of_the_submission_is_accounted_for(self):
        text = ("I lived in Mesa from 1990 to 1992. My dog died that summer. "
                "!!")
        call = ScriptedCall(reading=MESA_READING)
        proposal = self.propose(text, call)
        self.assertEqual(lo.lint_offer_proposal(proposal), [])
        accounted = (len(proposal["units"]) + len(proposal["stories"])
                     + len(proposal["unrecognized"]))
        self.assertEqual(accounted, len(lo.source_spans(text)))

    def test_a_provider_failure_still_retains_the_input(self):
        def boom(prompt: str, model: str) -> str:
            raise RuntimeError("provider down")

        proposal = self.propose(MESA, boom)
        self.assertEqual(proposal["state"], "failed")
        self.assertEqual(proposal["failure"]["class"], "service_unavailable")
        stored = json.loads(lo.proposal_path(
            self.root, proposal["proposal_id"]).read_text())
        self.assertEqual(stored["source_text"], MESA)

    def test_a_later_reading_replaces_a_failed_one(self):
        def boom(prompt: str, model: str) -> str:
            raise RuntimeError("provider down")

        failed = self.propose(MESA, boom)
        call = ScriptedCall(reading=MESA_READING)
        again = self.propose(MESA, call)
        self.assertEqual(failed["proposal_id"], again["proposal_id"])
        stored = json.loads(lo.proposal_path(
            self.root, again["proposal_id"]).read_text())
        self.assertEqual(stored["state"], "proposed")

    def test_empty_text_is_a_typed_refusal(self):
        with self.assertRaises(lo.LandmarkOfferError) as caught:
            self.propose("   ", ScriptedCall())
        self.assertEqual(caught.exception.code, "unsupported_input")

    def test_the_six_states_are_named_once(self):
        self.assertEqual(lo.OFFER_STATES,
                         ("submitted", "needs_clarification", "proposed",
                          "applying", "published", "failed"))
        self.assertTrue(set(lo.PROPOSAL_STATES) <= set(lo.OFFER_STATES))


# --------------------------------------------------------------------------
# The 5a seam
# --------------------------------------------------------------------------


class OpportunityHookTests(OfferVaultCase):
    def test_the_opportunity_id_is_cut_5as_one_definition(self):
        import landmark_opportunities as lop  # noqa: PLC0415

        self.assertEqual(
            lo.landmark_opportunity_id(domain="residences", subject="Mesa",
                                       kind="span_open_end"),
            lop.opportunity_id(domain="residences", kind="span_open_end",
                               subject="Mesa"))

    def test_a_unit_names_every_gap_kind_it_could_close(self):
        import landmark_opportunities as lop  # noqa: PLC0415

        unit = {"unit_id": "lmu:x", "domain": "residences", "subject": "Mesa",
                "kind": "residence"}
        ids = lo.opportunity_ids_for(unit)
        self.assertEqual(len(ids), len(lop.OPPORTUNITY_KINDS))
        self.assertIn(lop.opportunity_id(domain="residences",
                                         kind="span_open_end", subject="Mesa"),
                      ids)

    def test_a_unit_with_no_subject_names_nothing(self):
        self.assertEqual(lo.opportunity_ids_for(
            {"unit_id": "lmu:x", "domain": "birth", "subject": ""}), [])

    def test_the_open_ids_are_read_from_the_published_block(self):
        projection = {"landmark_opportunities": [{"id": "lo:abc"},
                                                 {"id": "lo:def"}]}
        self.assertEqual(lo.open_opportunity_ids(self.root,
                                                 projection=projection),
                         {"lo:abc", "lo:def"})
        self.assertEqual(lo.open_opportunity_ids(self.root, projection={}),
                         set())

    def test_an_unmeasured_before_claims_nothing(self):
        unit = {"unit_id": "lmu:x", "domain": "residences", "subject": "Mesa",
                "kind": "residence"}
        row = lo.retire_matching_opportunity(unit, self.root)
        self.assertEqual(row["retired"], [])

    def test_the_gap_that_closed_is_the_one_that_retired(self):
        import landmark_opportunities as lop  # noqa: PLC0415

        unit = {"unit_id": "lmu:x", "domain": "residences", "subject": "Mesa",
                "kind": "residence"}
        open_end = lop.opportunity_id(domain="residences",
                                      kind="span_open_end", subject="Mesa")
        missing = lop.opportunity_id(domain="residences", kind="span_missing",
                                     subject="Mesa")
        row = lo.retire_matching_opportunity(
            unit, self.root, open_before={open_end, missing},
            open_after={missing})
        self.assertEqual(row["retired"], [open_end])
        self.assertEqual(row["still_open"], [missing])

    def test_the_receipt_carries_the_retirement(self):
        call = ScriptedCall(reading=MESA_READING)
        proposal = self.propose(MESA, call)
        receipt = lo.apply(proposal["proposal_id"],
                           [unit["unit_id"] for unit in proposal["units"]],
                           self.root, now=NOW)
        row = receipt["retired_opportunities"][0]
        self.assertEqual(set(row), {"unit_id", "opportunity_ids", "retired",
                                    "still_open"})
        self.assertEqual(row["still_open"], [])


# --------------------------------------------------------------------------
# The manifest's three new blocks
# --------------------------------------------------------------------------


class ManifestBlockTests(OfferVaultCase):
    def test_the_roster_block_names_people_places_and_organizations(self):
        entity_roster.write_roster("person", [
            {"name": "Katie", "slug": "katie", "aliases": ["Kate"]}])
        entity_roster.write_roster("place", [
            {"name": "Mesa", "slug": "mesa", "aliases": []}])
        landmarks = {"work": [{"domain": "work", "label": "the Boatworks",
                               "what": "boat building"}]}
        block = li.render_roster(
            {"person": entity_roster.load_roster("person"),
             "place": entity_roster.load_roster("place")},
            landmarks=landmarks)
        self.assertIn("- person: Katie (also: Kate)", block)
        self.assertIn("- place: Mesa", block)
        self.assertIn("the Boatworks", block)

    def test_the_blocks_degrade_to_honest_absence(self):
        self.assertEqual(li.render_roster({}), li.NO_ROSTER)
        self.assertEqual(li.render_known_spans({}), li.NO_KNOWN_SPANS)
        self.assertEqual(li.render_age_frames({}), li.NO_AGE_FRAMES)

    def test_the_span_block_reads_the_published_projection(self):
        projection = {"nodes": [
            {"node_id": "era:college", "node_kind": "period",
             "event_kind": "named_era", "label": "College",
             "best_temporal_value": {"best": "1988", "earliest": "1988",
                                     "latest": "1992", "granularity": "year",
                                     "confidence": "certain",
                                     "basis": "stated"}},
            {"node_id": "frame:20s", "node_kind": "period",
             "event_kind": "age_frame", "label": "My twenties",
             "definition_span": {"start": "1988", "end": "1998"},
             "origin_basis": "stated"},
        ]}
        spans = li.render_known_spans(projection)
        self.assertIn("era: College", spans)
        self.assertNotIn("My twenties", spans)
        frames = li.render_age_frames(projection)
        self.assertIn("My twenties", frames)
        self.assertIn("stated", frames)

    def test_offer_context_renders_all_three(self):
        context = lo.offer_context(self.root)
        self.assertEqual(set(context), {"roster", "known_spans", "age_frames"})


# --------------------------------------------------------------------------
# The lints and the worker's reply
# --------------------------------------------------------------------------


class ReplyLintTests(unittest.TestCase):
    def test_the_offer_gates_have_their_own_namespace(self):
        import landmarks_evals as ev  # noqa: PLC0415

        gates = ev.load_offer_gates()
        self.assertEqual(
            sorted(gates),
            sorted(f"{name.split('.', 1)[1]}.compliance"
                   for name in lo.OFFER_LINT_CLASSES))
        self.assertFalse(set(gates) & set(ev.load_gates()))

    def test_a_refusal_is_a_finding(self):
        findings = lo.lint_offer_reply("I couldn't parse that paste right now.")
        self.assertIn(lo.NEVER_REFUSES_LINT, [row["lint"] for row in findings])

    def test_homework_is_a_finding(self):
        findings = lo.lint_offer_reply(
            "Got it. You still need to complete your residences.")
        self.assertIn(lo.KEEPS_STOP_RULES_LINT, [row["lint"] for row in findings])

    def test_naming_a_date_and_asking_agreement_is_a_finding(self):
        findings = lo.lint_offer_reply(
            "Was it 1991? That sounds about right.", domain="residences")
        self.assertTrue(findings)

    def test_a_clean_offer_reply_passes(self):
        self.assertEqual(lo.lint_offer_reply(
            "Reading this as a stay in Mesa, 1990 to 1992, from “I lived in "
            "Mesa from 1990 to 1992.” Does this look right?"), [])


# --------------------------------------------------------------------------
# Wiring: the verb, the contract, the manifest of shipped files
# --------------------------------------------------------------------------


class WiringTests(unittest.TestCase):
    def test_the_verb_is_registered_and_classified(self):
        import lifehug  # noqa: PLC0415

        parser = lifehug.build_parser()
        actions = {action.dest for action in parser._subparsers._group_actions}  # noqa: SLF001
        self.assertTrue(actions)
        self.assertIn("landmark-offer", lifehug.DIRECT_MUTATION_COMMANDS)
        self.assertNotIn("landmark-offer", lifehug.READ_ONLY_COMMANDS)

    def test_the_vault_contract_registers_the_offer_directory(self):
        contract = json.loads((SYSTEM / "vault_contract.json").read_text(
            encoding="utf-8"))
        row = contract["data_paths"]["landmark_offers"]
        self.assertEqual(row["path"], lo.OFFERS_DIR)
        self.assertEqual(row["kind"], "directory")
        self.assertTrue(row["tracked"])

    def test_the_new_modules_ship(self):
        manifest = json.loads((SYSTEM / "version.json").read_text(
            encoding="utf-8"))
        for path in ("system/landmark_offer.py",
                     "interactions/landmarks/prompt/turn-instructions-offer.md",
                     "interactions/landmarks/evals/goldens/offer_fixtures.json",
                     "docs/adr/0033-add-landmark-offer-mode.md",
                     "tests/test_landmark_offer.py"):
            with self.subTest(path=path):
                self.assertIn(path, manifest["framework_files"])

    def test_nothing_user_facing_names_the_retired_product(self):
        body = (SYSTEM / "landmark_offer.py").read_text(encoding="utf-8")
        for line in body.splitlines():
            if "go_dig" in line:
                self.assertTrue(
                    "import" in line or "#" in line or "_writer" in line,
                    f"user-facing mention: {line}")


if __name__ == "__main__":
    unittest.main()
