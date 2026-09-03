"""Cut 6a — Add Landmark, the `offer` mode of the Landmarks Interaction.

Controlling design: `lifehug-platform
docs/decisions/2026-09-03-timeline-unification/decision-record.md` — R3, R3a,
R3b, §4.2 (weight tiers), §5 (the interaction, the manifest, the six states,
filing and the loop, transport, the five examples of §5.6). ADR 0033.

No live model call: the two passes take an injected ``call``, and every test
here scripts it — the same recorded discipline `tests/test_landmarks.py` uses
for the recorder.

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


class ScriptedCall:
    """One injected ``call`` that answers the listener and each recorder.

    Dispatch is on the composed prompt's own header — the recorder leaf names
    its domain, the listener leaf does not — so the script is written the way
    a host's REPLAY reads it, and a prompt nobody scripted answers empty
    rather than silently borrowing another domain's completion.
    """

    EMPTY = '{"landmarks": [], "claims": []}'

    def __init__(self, *, listener: object = None, recorders: object = None):
        self.listener = listener if listener is not None else self.EMPTY
        self.recorders = dict(recorders or {})
        self.prompts: list[str] = []

    def __call__(self, prompt: str, model: str) -> str:
        self.prompts.append(prompt)
        for domain, payload in self.recorders.items():
            if f"DOMAIN BEING ASKED ABOUT: {domain}\n" in prompt:
                return payload if isinstance(payload, str) else json.dumps(payload)
        if "DOMAIN BEING ASKED ABOUT:" in prompt:
            return self.EMPTY
        return (self.listener if isinstance(self.listener, str)
                else json.dumps(self.listener))


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

    def test_an_inferred_date_is_shown_as_one(self):
        turn = lo.build_offer_turn({"units": [
            {"kind": "residence", "subject": "Cedarport",
             "dates": {"start": "1993", "end": None, "basis": "inferred"},
             "quote": {"text": "Then Cedarport for a while."},
             "questions": []}], "stories": [], "unrecognized": [],
            "questions": []})
        self.assertIn("you did not say a date", turn)

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
MESA_RECORD = {"domain": "residences", "label": "Mesa", "city": "Mesa",
               "span": _span("1990", "1992")}
MESA_CLAIM = {"claim_type": "range", "subject_mention": "Mesa",
              "event_kind": "move", "temporal_value": "1990/1992",
              "evidence": MESA}

BOATWORKS = "I worked at the Boatworks from about '91 to '92."
BOATWORKS_RECORD = {"domain": "work", "label": "the Boatworks",
                    "what": "boat building",
                    "span": _span("1991", "1992", confidence="approximate")}
BOATWORKS_CLAIM = {"claim_type": "range", "subject_mention": "the Boatworks",
                   "event_kind": "job", "temporal_value": "1991/1992",
                   "evidence": BOATWORKS}

MOVED = "We moved around a lot after Dad changed jobs."
MOVED_CLAIM = {"claim_type": "relative_order", "subject_mention": "we",
               "event_kind": "move",
               "temporal_value": {"relation": "after",
                                  "anchors": ["Dad changed jobs"]},
               "evidence": MOVED}

DOG = "My dog died that summer."


class TheFiveExamplesTests(OfferVaultCase):
    """Decision record §5.6, one test each."""

    def test_a_stated_residence_is_one_certain_quoted_unit(self):
        call = ScriptedCall(
            listener={"landmarks": [MESA_RECORD], "claims": [MESA_CLAIM]},
            recorders={"residences": {"landmarks": [MESA_RECORD],
                                      "claims": [MESA_CLAIM]}})
        proposal = self.propose(MESA, call)
        self.assertEqual(proposal["state"], "proposed")
        self.assertEqual(len(proposal["units"]), 1)
        unit = proposal["units"][0]
        self.assertEqual(unit["domain"], "residences")
        self.assertEqual(unit["kind"], "residence")
        self.assertEqual(unit["subject"], "Mesa")
        self.assertEqual(unit["dates"],
                         {"start": "1990", "end": "1992", "precision": "year",
                          "basis": "stated", "confidence": "certain"})
        self.assertEqual(unit["quote"]["text"], MESA)
        self.assertTrue(unit["auto_file_eligible"])
        self.assertEqual(unit["questions"], [])
        # The claim the listener heard is covered by the unit's own quote, so
        # nothing is asked twice.
        self.assertEqual(proposal["questions"], [])
        self.assertEqual(lo.lint_offer_proposal(proposal), [])

    def test_a_hedged_tenure_is_approximate_and_names_its_organization(self):
        call = ScriptedCall(
            listener={"landmarks": [BOATWORKS_RECORD], "claims": [BOATWORKS_CLAIM]},
            recorders={"work": {"landmarks": [BOATWORKS_RECORD],
                                "claims": [BOATWORKS_CLAIM]}})
        proposal = self.propose(BOATWORKS, call)
        self.assertEqual(len(proposal["units"]), 1)
        unit = proposal["units"][0]
        self.assertEqual(unit["kind"], "tenure")
        self.assertEqual(unit["dates"]["basis"], "stated")
        self.assertEqual(unit["dates"]["confidence"], "approximate")
        self.assertEqual([c["confidence"] for c in unit["entity_candidates"]],
                         ["new"])
        self.assertEqual(unit["entity_candidates"][0]["type"], "organization")
        self.assertEqual(proposal["questions"], [])
        self.assertEqual(lo.lint_offer_proposal(proposal), [])

    def test_a_claims_evidence_is_read_in_every_shape_the_contract_accepts(self):
        self.assertEqual(lo.claim_evidence_text({"evidence": MESA}), MESA)
        self.assertEqual(lo.claim_evidence_text({"evidence": [{"quote": MESA}]}),
                         MESA)
        self.assertEqual(lo.claim_evidence_text({"evidence": {"quote": MESA}}),
                         MESA)
        self.assertEqual(lo.claim_evidence_text({}), "")

    def test_the_two_digit_year_the_person_wrote_is_still_their_own_date(self):
        self.assertTrue(lo.date_evidence(_date("1991"), {"text": BOATWORKS},
                                         BOATWORKS))
        self.assertFalse(lo.date_evidence(_date("1994"), {"text": BOATWORKS},
                                          BOATWORKS))

    def test_vague_movement_fabricates_no_residence_and_asks_where(self):
        call = ScriptedCall(listener={"landmarks": [], "claims": [MOVED_CLAIM]})
        proposal = self.propose(MOVED, call)
        self.assertEqual(proposal["units"], [])
        self.assertEqual(proposal["state"], "needs_clarification")
        self.assertEqual(len(proposal["questions"]), 1)
        question = proposal["questions"][0]
        self.assertEqual(question["domain"], "residences")
        self.assertIn("where", question["text"].lower())
        self.assertNotIn("199", question["text"])
        # The words themselves are retained, not thrown away.
        self.assertEqual([span["text"] for span in proposal["stories"]], [MOVED])

    def test_a_story_is_routed_as_a_story_and_never_refused(self):
        call = ScriptedCall(listener={"landmarks": [], "claims": []})
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

    def test_a_thirty_block_document_proposes_thirty_units_and_drops_nothing(self):
        blocks = []
        for index in range(30):
            year = 1960 + index
            blocks.append(f"Dates: {year} - {year + 1}\n"
                          f"City/State: Town{index:02d}, ST")
        document = "\n\n".join(blocks)
        call = ScriptedCall(listener={"landmarks": [], "claims": []})
        proposal = self.propose(document, call)
        self.assertEqual(len(proposal["units"]), 30)
        self.assertEqual(proposal["unrecognized"], [])
        self.assertEqual(proposal["stories"], [])
        self.assertEqual({unit["extractor"] for unit in proposal["units"]},
                         {"grammar"})
        self.assertEqual({unit["dates"]["basis"] for unit in proposal["units"]},
                         {"stated"})
        self.assertEqual(lo.lint_offer_proposal(proposal), [])
        self.assertEqual(len({unit["unit_id"] for unit in proposal["units"]}), 30)

    def test_a_block_the_grammar_cannot_read_goes_to_the_listener(self):
        """R3: a paste the grammar cannot read is never refused — it is
        ordinary text, and the Haiku-class listener is what reads it."""
        document = ("Dates: 1970 - 1972\nCity/State: Rivermouth, ST\n\n"
                    "Dates: not sure really\nCity/State: Harbor End, ST")
        call = ScriptedCall(listener={"landmarks": [], "claims": []})
        proposal = self.propose(document, call)
        self.assertEqual([unit["subject"] for unit in proposal["units"]],
                         ["Rivermouth"])
        kept = " ".join(span["text"] for span in
                        proposal["stories"] + proposal["unrecognized"])
        self.assertIn("Harbor End", kept)
        self.assertIn("not sure really", kept)
        self.assertEqual(lo.lint_offer_proposal(proposal), [])

    def test_a_line_the_grammar_does_not_know_is_never_half_parsed(self):
        document = ("Dates: 1970 - 1972\nCity/State: Rivermouth, ST\n"
                    "It rained the whole two years.")
        units, _consumed = lo.grammar_units(document)
        self.assertEqual(units, [])

    def test_the_extraction_roles_are_the_ones_the_manifest_declares(self):
        import general_listener as gl  # noqa: PLC0415
        import landmark_recorder as recorder  # noqa: PLC0415

        manifest = (ROOT / "interactions" / "landmarks"
                    / "interaction.yaml").read_text(encoding="utf-8")
        self.assertIn(f"role.listener: {gl.DEFAULT_LISTENER_ROLE}", manifest)
        self.assertIn(f"role.recorder: {recorder.DEFAULT_RECORDER_ROLE}",
                      manifest)
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
        # The one model seam is the injected `call`, reached only through the
        # two passes the interaction already declares.
        self.assertEqual(
            sorted(name for name in called
                   if name in {"listen_to_answer", "record_answer"}),
            ["listen_to_answer", "record_answer"])

    def test_the_deterministic_pass_spends_no_completion(self):
        document = "Dates: 1970 - 1972\nCity/State: Rivermouth, ST"
        units, _consumed = lo.grammar_units(document)
        self.assertEqual(len(units), 1)
        self.assertEqual(units[0]["subject"], "Rivermouth")


# --------------------------------------------------------------------------
# Stated versus inferred (§4.2)
# --------------------------------------------------------------------------


class BasisTests(OfferVaultCase):
    def test_a_quoted_date_files_as_stated_and_an_unquoted_one_as_inferred(self):
        text = "I lived in Mesa from 1990 to 1992. Then Cedarport for a while."
        cedar = {"domain": "residences", "label": "Cedarport",
                 "city": "Cedarport", "span": _span("1993", "1996")}
        call = ScriptedCall(
            listener={"landmarks": [MESA_RECORD, cedar],
                      "claims": [MESA_CLAIM]},
            recorders={"residences": {"landmarks": [MESA_RECORD, cedar],
                                      "claims": [MESA_CLAIM]}})
        proposal = self.propose(text, call)
        by_subject = {unit["subject"]: unit for unit in proposal["units"]}
        self.assertEqual(by_subject["Mesa"]["dates"]["basis"], "stated")
        self.assertEqual(by_subject["Cedarport"]["dates"]["basis"], "inferred")
        filed = by_subject["Cedarport"]["record"]["span"]["start"]
        self.assertEqual(filed["confidence"], "inferred")
        self.assertNotEqual(filed["basis"], "stated")
        self.assertIn({"basis": "inferred", "claim": lo.INFERRED_CLAUSE},
                      filed["provenance"])
        self.assertFalse(by_subject["Cedarport"]["auto_file_eligible"])

    def test_the_lint_refuses_a_stated_date_the_text_does_not_carry(self):
        proposal = {
            "source_text": "I lived in Mesa.",
            "units": [{"unit_id": "lmu:x", "dates": {"basis": "stated"},
                       "quote": {"text": "I lived in Mesa.", "offset": 0,
                                 "length": 16},
                       "record": {"date": _date("1990")}}],
            "stories": [], "unrecognized": [],
        }
        findings = lo.lint_offer_proposal(proposal)
        self.assertEqual([row["lint"] for row in findings],
                         [lo.NO_FABRICATED_DATE_LINT])

    def test_a_model_declaring_stated_over_a_year_nobody_typed_is_answered(self):
        """§4.2: the completion does not get to decide this."""
        lying = {"domain": "residences", "label": "Mesa", "city": "Mesa",
                 "span": _span("1990", "1992", basis="stated")}
        call = ScriptedCall(
            listener={"landmarks": [lying], "claims": []},
            recorders={"residences": {"landmarks": [lying], "claims": []}})
        proposal = self.propose("I lived in Mesa for a couple of years.", call)
        unit = proposal["units"][0]
        self.assertEqual(unit["dates"]["basis"], "inferred")
        self.assertEqual(unit["record"]["span"]["start"]["confidence"],
                         "inferred")
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
        again = {"domain": "residences", "label": "Phoenix", "city": "Phoenix",
                 "span": _span("1995", "1999")}
        text = "I lived in Phoenix again from 1995 to 1999."
        call = ScriptedCall(
            listener={"landmarks": [again], "claims": []},
            recorders={"residences": {"landmarks": [again], "claims": []}})
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
        same = {"domain": "residences", "label": "Phoenix", "city": "Phoenix",
                "span": _span("1980", "1985")}
        text = "I lived in Phoenix from 1980 to 1985."
        call = ScriptedCall(
            listener={"landmarks": [same], "claims": []},
            recorders={"residences": {"landmarks": [same], "claims": []}})
        proposal = self.propose(text, call)
        unit = proposal["units"][0]
        self.assertEqual(unit["duplicates"], ["residences/phoenix"])
        self.assertFalse(unit["auto_file_eligible"])

    def test_the_recorder_is_shown_the_domains_filed_entries(self):
        self._file_phoenix()
        call = ScriptedCall(
            listener={"landmarks": [{"domain": "residences", "label": "Mesa",
                                     "city": "Mesa"}], "claims": []},
            recorders={"residences": {"landmarks": [], "claims": []}})
        self.propose("I lived in Mesa too.", call)
        recorder_prompts = [p for p in call.prompts
                            if "DOMAIN BEING ASKED ABOUT: residences" in p]
        self.assertTrue(recorder_prompts)
        self.assertIn("Phoenix", recorder_prompts[0])


# --------------------------------------------------------------------------
# Filing, idempotency, rebuild, undo
# --------------------------------------------------------------------------


class ApplyTests(OfferVaultCase):
    def _mesa_proposal(self) -> dict:
        call = ScriptedCall(
            listener={"landmarks": [MESA_RECORD], "claims": [MESA_CLAIM]},
            recorders={"residences": {"landmarks": [MESA_RECORD],
                                      "claims": [MESA_CLAIM]}})
        return self.propose(MESA, call)

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
        call = ScriptedCall(
            listener={"landmarks": [MESA_RECORD], "claims": [MESA_CLAIM]},
            recorders={"residences": {"landmarks": [MESA_RECORD],
                                      "claims": [MESA_CLAIM]}})
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
        call = ScriptedCall(
            listener={"landmarks": [MESA_RECORD], "claims": [MESA_CLAIM]},
            recorders={"residences": {"landmarks": [MESA_RECORD],
                                      "claims": [MESA_CLAIM]}})
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
        call = ScriptedCall(
            listener={"landmarks": [MESA_RECORD], "claims": [MESA_CLAIM]},
            recorders={"residences": {"landmarks": [MESA_RECORD],
                                      "claims": [MESA_CLAIM]}})
        proposal = self.propose(text, call)
        self.assertEqual([span["text"] for span in proposal["unrecognized"]],
                         ["???"])
        stored = json.loads(lo.proposal_path(
            self.root, proposal["proposal_id"]).read_text())
        self.assertEqual(stored["unrecognized"], proposal["unrecognized"])

    def test_every_span_of_the_submission_is_accounted_for(self):
        text = ("I lived in Mesa from 1990 to 1992. My dog died that summer. "
                "!!")
        call = ScriptedCall(
            listener={"landmarks": [MESA_RECORD], "claims": [MESA_CLAIM]},
            recorders={"residences": {"landmarks": [MESA_RECORD],
                                      "claims": [MESA_CLAIM]}})
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
        call = ScriptedCall(
            listener={"landmarks": [MESA_RECORD], "claims": [MESA_CLAIM]},
            recorders={"residences": {"landmarks": [MESA_RECORD],
                                      "claims": [MESA_CLAIM]}})
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
        call = ScriptedCall(
            listener={"landmarks": [MESA_RECORD], "claims": [MESA_CLAIM]},
            recorders={"residences": {"landmarks": [MESA_RECORD],
                                      "claims": [MESA_CLAIM]}})
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
