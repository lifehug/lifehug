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


#: ONE block of the shape people actually paste, carrying every one of R7's
#: cases at once: a stay with a nickname (with a parenthetical), a city and an
#: address; a school inside it with no dates of its own; a DATED event; an
#: UNDATED one; and a story told about the same stay. Invented throughout.
ORCHARD_STAY = ("Dates: June 1986 - March 1988\n"
                "City/State: Riverbend, ST\n"
                "Nickname: the Orchard House (we rented the top floor)\n"
                "Address: 14 Orchard Lane, Riverbend, ST")
ORCHARD = (ORCHARD_STAY + "\n"
           "School: Kestrel Elementary, 3rd and 4th grade\n"
           "Events: Wren was born 12 May 1987; the winter the creek froze\n"
           "We left the keys with the neighbours.")
ORCHARD_READING = reading(
    units=[
        read_unit("u1", "residences", "the Orchard House", ORCHARD_STAY,
                  record={"city": "Riverbend", "label": "the Orchard House"},
                  names={"nickname": "the Orchard House (we rented the top floor)",
                         "city": "Riverbend",
                         "address": "14 Orchard Lane, Riverbend, ST"},
                  dates=read_dates("1986-06", "1988-03")),
        read_unit("u2", "schools", "Kestrel Elementary",
                  "School: Kestrel Elementary, 3rd and 4th grade",
                  record={"name": "Kestrel Elementary",
                          "label": "Kestrel Elementary",
                          "grades": "3rd and 4th grade"}, within="u1"),
    ],
    events=[
        {"ref": "e1", "text": "Wren was born", "kind": "child_born",
         "subject_mention": "Wren", "date": "1987-05-12", "within": "u1",
         "quote": "Wren was born 12 May 1987"},
        {"ref": "e2", "text": "the winter the creek froze", "kind": "flood",
         "subject_mention": "self", "date": None, "within": "u1",
         "quote": "the winter the creek froze"},
    ],
    stories=[{"quote": "We left the keys with the neighbours.",
              "within": "u1"}])


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
        # entirely. (`plan_import` used to survive, uncalled, inside
        # `grammar_units` — Cut 6h deleted both; the test below proves
        # `propose` never reached it, and `NoSecondCopyTests` below proves
        # the module cannot reach `go_dig_grammar` at all any more.)
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


class NoSecondCopyTests(unittest.TestCase):
    """Cut 6h: the block grammar leaves the Add Landmark path for good.

    `grammar_units`, `_date_dict` and `_grammar_block_quote` — the
    deterministic first pass ADR 0033 always allowed and R6 (v291) stopped
    calling — are DELETED, not merely unreached. This class is the guard
    against their return: an AST sweep (the discipline
    `tests/test_go_dig.py`'s `NoModelCallTest` already uses) proves neither
    `landmark_offer` nor `landmark_reading` — the two modules on the offer's
    READ path — can import `go_dig_grammar` by any route, and a source-text
    scope check proves `go_dig_writer`, the one still-legitimate WRITER seam
    (`apply`'s `record_unit` call, and `unit_filing_digest`'s pre-existing
    filing-identity helper, both of them writing/filing concerns Cut 6h does
    not touch), is never named anywhere else in the module — in particular,
    never again inside `propose` or anything it composes. Cut 7b deletes
    `go_dig_writer` and `go_dig_grammar` entirely; this test is what makes a
    reintroduction before then fail the build instead of waiting for 7b to
    notice.
    """

    def _imported_module_names(self, path: Path) -> set:
        import ast  # noqa: PLC0415

        tree = ast.parse(path.read_text(encoding="utf-8"))
        names: set = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                names.add(node.module.split(".")[0])
        return names

    def test_the_offer_path_never_imports_the_block_grammar(self):
        """Neither module can reach `go_dig_grammar` by any import — live,
        lazy, `import X` or `from X import Y` — anywhere in its source."""
        for module in ("landmark_offer.py", "landmark_reading.py"):
            with self.subTest(module=module):
                self.assertNotIn(
                    "go_dig_grammar",
                    self._imported_module_names(SYSTEM / module))

    def test_go_dig_writer_is_named_only_by_the_writer_seam(self):
        """`go_dig_writer` is a WRITER concern now — `apply`'s own
        `record_unit` call, and `unit_filing_digest`'s pre-existing (Cut 6a)
        filing-identity helper `apply` calls for its receipt. Nothing else in
        the module — least of all `propose` or the deleted `grammar_units` —
        may name it."""
        import ast  # noqa: PLC0415

        source = (SYSTEM / "landmark_offer.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        legitimate = {"apply", "unit_filing_digest"}
        naming_it: set = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef):
                segment = ast.get_source_segment(source, node) or ""
                if "go_dig_writer" in segment:
                    naming_it.add(node.name)
        self.assertEqual(naming_it, legitimate)
        # The letter of the rule this test exists for: the writer's OWN
        # write call is `apply`'s, and only `apply`'s.
        self.assertIn("apply", naming_it)


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


# --------------------------------------------------------------------------
# groups[] — the proposal read BY STAY (§3.2, Cut 6g)
# --------------------------------------------------------------------------


class GroupTests(OfferVaultCase):
    def _orchard(self) -> dict:
        return self.propose(ORCHARD, ScriptedCall(reading=ORCHARD_READING))

    def test_a_group_heads_one_stay_and_holds_everything_inside_it(self):
        proposal = self._orchard()
        self.assertEqual(len(proposal["groups"]), 1)
        group = proposal["groups"][0]
        self.assertEqual(sorted(group), sorted(lo.GROUP_KEYS))
        stay = next(unit for unit in proposal["units"]
                    if unit["subject"] == "the Orchard House")
        self.assertEqual(group["unit_id"], stay["unit_id"])
        self.assertEqual([member["kind"] for member in group["members"]],
                         ["unit", "event", "event", "story"])
        self.assertLessEqual({member["kind"] for member in group["members"]},
                             set(lo.MEMBER_KINDS))

    def test_a_story_carries_a_stable_content_addressed_id(self):
        first = self._orchard()
        second = self.propose(ORCHARD, ScriptedCall(reading=ORCHARD_READING))
        ids = [story["story_id"] for story in first["stories"]]
        self.assertEqual(ids, [story["story_id"] for story in second["stories"]])
        self.assertTrue(all(lo.valid_id(value) for value in ids))

    def test_a_school_inside_a_stay_brings_its_own_events(self):
        """Membership is TRANSITIVE: one card per stay, not one per level."""
        nested = reading(
            units=list(ORCHARD_READING["units"]),
            events=[{**ORCHARD_READING["events"][0], "within": "u2"},
                    ORCHARD_READING["events"][1]],
            stories=list(ORCHARD_READING["stories"]))
        proposal = self.propose(ORCHARD, ScriptedCall(reading=nested))
        self.assertEqual(len(proposal["groups"]), 1)
        kinds = [member["kind"] for member in proposal["groups"][0]["members"]]
        self.assertEqual(kinds, ["unit", "event", "event", "story"])

    def test_what_belongs_to_nothing_is_the_last_group(self):
        proposal = self.propose(MOVED, ScriptedCall(reading=MOVED_READING))
        self.assertEqual(proposal["groups"][-1]["unit_id"], None)
        self.assertEqual([member["kind"]
                          for member in proposal["groups"][-1]["members"]],
                         ["event"])

    def test_a_reading_with_no_relations_is_one_group_per_unit(self):
        proposal = self.propose(MESA, ScriptedCall(reading=MESA_READING))
        self.assertEqual([group["unit_id"] for group in proposal["groups"]],
                         [proposal["units"][0]["unit_id"]])
        self.assertEqual(proposal["groups"][0]["members"], [])

    def test_the_thirty_block_document_reads_as_thirty_cards(self):
        """The owner's own complaint, measured: ~30 cards, not ~90 rows."""
        import landmarks_evals as ev  # noqa: PLC0415

        fixture = next(row for row in ev.load_offer_fixtures()
                       if row["fixture_id"] == "offer-residence-document")
        proposal = lo.propose(fixture["source_text"], None,
                              call=ev._RecordedCall(fixture["completions"]),  # noqa: SLF001
                              write=False, landmarks={}, roster={}, generation=0)
        self.assertEqual(len(proposal["units"]), 42)
        self.assertEqual(len(proposal["groups"]), 30)
        self.assertTrue(all(group["unit_id"] for group in proposal["groups"]))

    def test_the_proposal_renders_by_group_with_members_indented(self):
        proposal = self._orchard()
        rendered = lo.render_proposal(proposal)
        lines = rendered.splitlines()
        self.assertTrue(lines[0].startswith("- residence: the Orchard House"))
        self.assertIn("  - schooling: Kestrel Elementary", rendered)
        self.assertIn("  - Wren was born", rendered)
        self.assertIn("  - “We left the keys with the neighbours.”", rendered)
        # The stay is rendered ONCE, as the head of its own group.
        self.assertEqual(sum(1 for line in lines
                             if line.startswith("- residence:")), 1)

    def test_a_proposal_written_before_groups_still_renders(self):
        """R5: an older pin's document is a flat list and must still show."""
        proposal = self._orchard()
        flat = {key: value for key, value in proposal.items() if key != "groups"}
        self.assertIn("the Orchard House", lo.render_proposal(flat))


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


# --------------------------------------------------------------------------
# What a confirmed stay HOLDS (Cut 6g, R7): names, inherited spans, the
# events, the moments and the stories, and the graph they end up in
# --------------------------------------------------------------------------


class FilingTests(OfferVaultCase):
    """The whole of R7's filing, proved over the CALCULATED projection.

    `bind_episodes` is run explicitly where a containment is asserted, because
    filing an `event_identity` binding is the BINDER's act and never `apply`'s
    — `apply` stamps the group's slice with the stay it was told about
    (`question_context`, event identity §12b ruling 5) and the binder's own
    deterministic rung turns that stamp into a `part_of`.
    """

    def _applied(self) -> dict:
        proposal = self.propose(ORCHARD, ScriptedCall(reading=ORCHARD_READING))
        receipt = lo.apply(proposal["proposal_id"],
                           [unit["unit_id"] for unit in proposal["units"]],
                           self.root, now=NOW)
        self.proposal = proposal
        return receipt

    def _nodes(self) -> list[dict]:
        projection = pub.read_projection(self.root) or {}
        return [node for node in (projection.get("nodes") or ())
                if isinstance(node, dict)]

    def _node(self, event_kind: str) -> dict:
        found = [node for node in self._nodes()
                 if node.get("event_kind") == event_kind]
        self.assertEqual(len(found), 1, event_kind)
        return found[0]

    def _bind(self) -> None:
        import episode_binder as eb  # noqa: PLC0415

        eb.bind_episodes(self.root, apply=True, now=NOW,
                         containment_authority="applied")
        timeline.redraw_landmarks()

    # -- names -----------------------------------------------------------

    def test_the_nickname_becomes_a_roster_alias_and_the_address_a_name(self):
        """§3 "why names matter": without this, "the Orchard House" in a later
        story finds nothing."""
        receipt = self._applied()
        entry = self.entries("residences")[0]
        self.assertEqual(entry["city"], "Riverbend")
        self.assertEqual(entry["address"], "14 Orchard Lane, Riverbend, ST")
        self.assertEqual(entry["nickname"], "the Orchard House")
        # The parenthetical is not a name anybody would say back; it survives
        # as the entry's note rather than vanishing (E-L2c).
        self.assertIn("we rented the top floor", entry["note"])
        place = entity_roster.load_roster("place")["entities"][0]
        self.assertEqual(place["name"], "Riverbend")
        self.assertIn("the Orchard House", place["aliases"])
        self.assertEqual(receipt["filed_names"][0]["place_ref"],
                         entry["place_ref"])
        self.assertTrue(receipt["filed_names"][0]["alias"]["changed"])

    def test_applying_the_same_receipt_twice_adds_no_second_name(self):
        first = self._applied()
        before = entity_roster.load_roster("place")
        second = lo.apply(first["proposal_id"], first["unit_ids"], self.root,
                          now=NOW)
        self.assertEqual(first, second)
        self.assertEqual(entity_roster.load_roster("place")["entities"],
                         before["entities"])
        self.assertEqual(len(self.entries("residences")), 1)
        self.assertEqual(len(lp.load_landmark_sources(self.root)), 2)

    # -- inherited units -------------------------------------------------

    def test_an_inherited_unit_files_its_bounds_with_the_clause_intact(self):
        """R7 rule 4 through the writer: every bound `basis: anchor`,
        `confidence: inferred`, and the verbatim provenance preserved."""
        self._applied()
        entry = self.entries("schools")[0]
        clause = "from the dates of the the Orchard House stay"
        for bound in ("start", "end"):
            record = entry["span"][bound]
            self.assertEqual(record["basis"], "anchor")
            self.assertEqual(record["confidence"], "inferred")
            self.assertIn({"basis": "inferred", "claim": clause},
                          record["provenance"])
        self.assertEqual(entry["span"]["start"]["best"], "1986-06")
        self.assertEqual(entry["span"]["end"]["best"], "1988-03")

    def test_a_unit_with_no_date_read_files_without_dates(self):
        text = "We were in Cedarport for a while."
        call = ScriptedCall(reading=reading(units=[read_unit(
            "u1", "residences", "Cedarport", text,
            record={"city": "Cedarport", "label": "Cedarport"})]))
        proposal = self.propose(text, call)
        self.assertEqual(proposal["units"][0]["dates"]["basis"], "none")
        lo.apply(proposal["proposal_id"],
                 [proposal["units"][0]["unit_id"]], self.root, now=NOW)
        entry = self.entries("residences")[0]
        self.assertNotIn("span", entry)
        self.assertNotIn("date", entry)

    # -- events, moments and stories -------------------------------------

    def test_a_group_files_one_slice_of_the_persons_own_words(self):
        receipt = self._applied()
        self.assertEqual(len(receipt["filed_slices"]), 1)
        row = receipt["filed_slices"][0]
        self.assertEqual(row["unit_id"], self.proposal["groups"][0]["unit_id"])
        self.assertTrue((self.root / row["relative_path"]).is_file())
        body = (self.root / row["relative_path"]).read_text(encoding="utf-8")
        self.assertIn("Kestrel Elementary", body)
        self.assertIn("the winter the creek froze", body)
        # The stay's own words are their OWN source, never the whole paste's:
        # a place join has to overlap with the stay and not with everything
        # the person ever pasted (`timeline._place_for_event`).
        self.assertNotEqual(row["source_id"],
                            receipt["evidence_ref"]["source_id"])
        # It is stamped with the stay it was told about, which is what makes
        # the containment deterministic rather than a guess.
        filed = [unit for unit in receipt["filed"]
                 if unit["unit_id"] == row["unit_id"]][0]
        self.assertEqual(row["question_context"], filed["telling_ref"])

    def test_two_stays_get_two_slices_and_neither_is_the_whole_paste(self):
        text = (ORCHARD + "\n\n"
                "Dates: April 1988 - September 1990\n"
                "City/State: Thornbury, ST\n"
                "Events: the summer the well ran dry")
        second = read_unit("u3", "residences", "Thornbury",
                           "Dates: April 1988 - September 1990\n"
                           "City/State: Thornbury, ST",
                           record={"city": "Thornbury", "label": "Thornbury"},
                           names={"city": "Thornbury"},
                           dates=read_dates("1988-04", "1990-09"))
        call = ScriptedCall(reading=reading(
            units=list(ORCHARD_READING["units"]) + [second],
            events=list(ORCHARD_READING["events"]) + [
                {"ref": "e3", "text": "the summer the well ran dry",
                 "kind": "drought", "subject_mention": "self", "date": None,
                 "within": "u3", "quote": "the summer the well ran dry"}],
            stories=list(ORCHARD_READING["stories"])))
        proposal = self.propose(text, call)
        self.assertEqual(len(proposal["groups"]), 2)
        receipt = lo.apply(proposal["proposal_id"],
                           [unit["unit_id"] for unit in proposal["units"]],
                           self.root, now=NOW)
        self.assertEqual(len(receipt["filed_slices"]), 2)
        for row in receipt["filed_slices"]:
            self.assertLess(row["length"], len(text))
        bodies = [(self.root / row["relative_path"]).read_text(encoding="utf-8")
                  for row in receipt["filed_slices"]]
        self.assertEqual([("Thornbury" in body) for body in bodies],
                         [False, True])

    def test_the_receipt_counts_every_kind_of_thing_it_filed(self):
        receipt = self._applied()
        self.assertEqual(receipt["counts"],
                         {"units": 2, "names": 1, "claims": 1, "moments": 1,
                          "stories": 1})
        self.assertTrue(receipt["sentence"])

    def test_a_dated_event_is_a_claim_placed_at_its_date(self):
        self._applied()
        node = self._node("child_born")
        self.assertEqual(node["node_kind"], "event")
        self.assertEqual(node["best_temporal_value"]["best"], "1987-05-12")

    def test_an_undated_event_takes_the_stays_bounds_by_containment(self):
        self._applied()
        self._bind()
        node = self._node("flood")
        self.assertIsNone(node["best_temporal_value"])
        window = node["possible_temporal_value"]
        self.assertEqual(window["earliest"], "1986-06")
        self.assertEqual(window["latest"], "1988-03")
        self.assertEqual(window["confidence"], "inferred")
        stay = self._node("residence")
        self.assertEqual([row["relation"] for row in node["containments"]],
                         ["part_of"])
        self.assertEqual(node["containments"][0]["episode_node_id"],
                         stay["node_id"])
        self.assertEqual(node["containments"][0]["origin"], "deterministic")

    def test_the_stay_is_an_episode_with_the_span_the_person_stated(self):
        self._applied()
        stay = self._node("residence")
        self.assertEqual(stay["node_kind"], "episode")
        self.assertEqual(stay["label"], "the Orchard House")
        self.assertEqual(stay["basis"], "explicit")
        self.assertEqual(stay["best_temporal_value"]["best"], "1986-06/1988-03")

    def test_the_school_is_an_episode_over_the_stays_own_span(self):
        """§4 "Done when": the school INSIDE its bounds, not a point at its
        start — and never `explicit`, because nobody stated it."""
        self._applied()
        school = self._node("school")
        self.assertEqual(school["node_kind"], "episode")
        stay = self._node("residence")
        self.assertEqual(school["best_temporal_value"]["best"],
                         stay["best_temporal_value"]["best"])
        self.assertEqual(school["best_temporal_value"]["basis"], "anchor")
        self.assertNotEqual(school["basis"], "explicit")

    def test_the_thirty_block_document_files_as_thirty_stays(self):
        """The owner's own document shape, applied end to end."""
        import landmarks_evals as ev  # noqa: PLC0415
        import temporal_claims as tc_  # noqa: PLC0415

        fixture = next(row for row in ev.load_offer_fixtures()
                       if row["fixture_id"] == "offer-residence-document")
        proposal = lo.propose(fixture["source_text"], self.root,
                              call=ev._RecordedCall(fixture["completions"]),  # noqa: SLF001
                              now=NOW)
        # One unit of this synthetic document is named "Pell & Sons", which
        # `temporal_claims.split_subject_enumeration` reads as two subjects and
        # the claim contract refuses by name. That refusal is the substrate's,
        # not this mode's, and it is filed as its own finding rather than
        # papered over here.
        confirmable = [unit["unit_id"] for unit in proposal["units"]
                       if len(tc_.split_subject_enumeration(unit["subject"])) == 1]
        receipt = lo.apply(proposal["proposal_id"], confirmable, self.root,
                           now=NOW)
        self.assertEqual(len(proposal["groups"]), 30)
        self.assertEqual(receipt["counts"]["units"], 41)
        self.assertEqual(receipt["counts"]["names"], 30)
        self.assertEqual(receipt["counts"]["claims"], 2)
        self.assertEqual(len(self.entries("residences")), 30)
        aliases = {alias for entity
                   in entity_roster.load_roster("place")["entities"]
                   for alias in (entity.get("aliases") or ())}
        self.assertIn("The Blue House", aliases)


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

    def test_undo_takes_back_the_names_the_events_and_the_moments(self):
        """v292: everything `apply` filed, and the immutable sources stay."""
        proposal = self.propose(ORCHARD, ScriptedCall(reading=ORCHARD_READING))
        receipt = lo.apply(proposal["proposal_id"],
                           [unit["unit_id"] for unit in proposal["units"]],
                           self.root, now=NOW)
        slice_path = receipt["filed_slices"][0]["relative_path"]
        claim_ids = {row["claim_id"] for row in receipt["filed_slices"][0]["events"]}
        self.assertTrue(claim_ids)
        self.assertIn("the Orchard House",
                      entity_roster.load_roster("place")["entities"][0]["aliases"])

        retraction = lo.retract(receipt["receipt_id"], self.root, now=NOW)

        self.assertEqual(self.entries("residences"), [])
        self.assertEqual(self.entries("schools"), [])
        # The alias came off the roster place; the place itself stays.
        place = entity_roster.load_roster("place")["entities"][0]
        self.assertEqual(place["aliases"], [])
        self.assertEqual([row["removed"] for row in retraction["aliases"]],
                         [True])
        # Every claim the events and moments stood on is retracted, not
        # deleted, and the slice they cite is still on disk.
        retracted = {value for row in retraction["corrections"]
                     for value in row["claim_ids"]}
        self.assertTrue(claim_ids <= retracted)
        self.assertIn(lo.EVENTS_SCOPE,
                      [row["domain"] for row in retraction["corrections"]])
        self.assertTrue((self.root / slice_path).is_file())
        index = ts.fold_active_index(self.root)
        self.assertEqual([row for row in ts.active_claims(index)
                          if row["claim_id"] in claim_ids], [])

    def test_undo_leaves_an_alias_the_place_already_answered_to(self):
        """A name this apply did not file is not this apply's to take away."""
        proposal = self.propose(ORCHARD, ScriptedCall(reading=ORCHARD_READING))
        receipt = lo.apply(proposal["proposal_id"],
                           [unit["unit_id"] for unit in proposal["units"]],
                           self.root, now=NOW)
        # Somebody else names the same place the same way afterwards.
        snapshot = entity_roster.load_roster("place")
        entity_roster.write_roster("place", [
            {**entity, "aliases": [*(entity.get("aliases") or ()), "the orchard"]}
            for entity in snapshot["entities"]])
        lo.retract(receipt["receipt_id"], self.root, now=NOW)
        place = entity_roster.load_roster("place")["entities"][0]
        self.assertEqual(place["aliases"], ["the orchard"])

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
