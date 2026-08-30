"""v229 / Wave C item C3 — the ear speaks claims.

The controlling authority is the audited final timeline build plan
(``docs/design/temporal-claims.md`` in lifehug-platform), and this item is the
sentence in §2.1 that the capture path could not previously honour: *dates,
ranges, durations, ages, seasons, life-stage anchors and relative order stated
in any conversation are usable information*, and *capture is not restricted to
family*. §6.4 adds that relative phrasings must be RETAINED even when they
cannot yet be placed.

A landmark record could honour none of it. It belongs to a domain and carries
at most one date, so *"we moved when James was two"* had no shape (no date) and
*"my neighbour's boy was born in 2019"* had no home (no domain), and the
listener leaf said in so many words to leave the first one out. Both were
dropped BY DESIGN, and dropping them is the defect the claim substrate exists
to end.

So the two leaves gained a `claims` list in `temporal_claims`' own vocabulary,
and this file pins the whole bridge:

* the DRAFT contract — validated through the one door, refused by name, and
  carrying nothing the FILER is supposed to supply;
* BINDING — a draft plus a promoted source is a claim, and binding adds the
  binding and changes nothing else;
* the two backstops, read over the new shape;
* the founder-shaped goldens; and
* the write path: one message, one promoted source, one receipt, N claims,
  idempotent, and foldable back into an active index with no model call.

Synthetic data only; NEVER references ~/Workspace/dave.
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "system"))
sys.path.insert(0, str(ROOT / "tests"))

import general_listener as gl  # noqa: E402
import landmark_recorder as lr  # noqa: E402
import landmarks_interaction as li  # noqa: E402
import temporal_claims as tc  # noqa: E402
import temporal_store as ts  # noqa: E402
from tempdirs import root_parent_tmp  # noqa: E402

GOLDEN = (ROOT / "interactions" / "landmarks" / "evals" / "goldens"
          / "claims-extraction-01.json")

SOURCE_REF = {
    "source_id": "conversation:msg-abc123",
    "revision": "sha256:" + "a1" * 32,
    "source_path": "sources/conversations/2026/msg-abc123.md",
}
EXTRACTOR = tc.extractor_version_string(
    "general_listener", schema_version=1, prompt_version="c0ffeec0ffee",
    model="haiku-class")


def emitted(**lists: object) -> str:
    """One completion, as a leaf would emit it."""
    return json.dumps(lists)


# --------------------------------------------------------------------------
# The draft contract
# --------------------------------------------------------------------------


class ClaimDraftTests(unittest.TestCase):
    """What the ear may assert, and what it may not."""

    def test_a_draft_carries_nothing_the_filer_supplies(self):
        """The four fields the EAR cannot know never appear on a draft."""
        draft, finding = gl.validate_claim_draft({
            "claim_type": "date", "subject_mention": "Danforth Steel",
            "event_kind": "job", "temporal_value": "1974",
            "evidence": "I started at Danforth Steel that fall"})
        self.assertEqual(finding, "")
        assert draft is not None
        for key in ("claim_id", "source_ref", "extractor_version",
                    "created_at"):
            with self.subTest(key=key):
                self.assertNotIn(key, draft)
        self.assertLessEqual(set(draft), set(gl.CLAIM_DRAFT_KEYS))

    def test_no_unbound_placeholder_survives_the_draft(self):
        """The placeholder is a scaffold, and a scaffold that shipped would be
        a claim citing a source that does not exist."""
        draft, _ = gl.validate_claim_draft({
            "claim_type": "identity", "subject_mention": "Ruth",
            "evidence": "my sister Ruth"})
        self.assertNotIn(gl.UNBOUND_SOURCE_ID, json.dumps(draft))
        self.assertNotIn(gl.UNBOUND_EXTRACTOR, json.dumps(draft))

    def test_the_key_set_is_closed(self):
        """A key outside the vocabulary means the leaf and the parser
        disagree, and that is a defect to NAME rather than a field to
        quietly ignore."""
        draft, finding = gl.validate_claim_draft({
            "claim_type": "date", "subject_mention": "Dayton",
            "event_kind": "move", "temporal_value": "1974",
            "evidence": "we moved in 1974", "claim_id": "claim:deadbeef"})
        self.assertIsNone(draft)
        self.assertEqual(finding, gl.claim_refused(gl.CLAIM_UNKNOWN_KEY))

    def test_an_aggregate_subject_is_refused_by_the_contracts_own_name(self):
        """Plan §5.1: four children are four entries, never one label."""
        draft, finding = gl.validate_claim_draft({
            "claim_type": "date",
            "subject_mention": "Corinne, Maddox, Sela and Ivo",
            "event_kind": "child_born", "temporal_value": "1979",
            "evidence": "four of them"})
        self.assertIsNone(draft)
        self.assertEqual(finding,
                         gl.claim_refused("aggregate_subject_mention"))
        self.assertIn("aggregate_subject_mention", tc.ERROR_CODES)

    def test_a_dated_claim_without_an_event_is_refused(self):
        """A date is the date of an EVENT, never of a person (plan §5.1)."""
        _, finding = gl.validate_claim_draft({
            "claim_type": "date", "subject_mention": "Ruth",
            "temporal_value": "1948", "evidence": "Ruth, 1948"})
        self.assertEqual(
            finding, gl.claim_refused("temporal_claim_needs_event_kind"))

    def test_a_claim_with_no_quotation_is_refused(self):
        """§4.2: evidence spans make each claim traceable to its source."""
        _, finding = gl.validate_claim_draft({
            "claim_type": "date", "subject_mention": "Dayton",
            "event_kind": "move", "temporal_value": "1974"})
        self.assertEqual(finding, gl.claim_refused("evidence_required"))

    def test_the_ear_records_what_was_said_so_the_basis_is_explicit(self):
        """The contract's own default is `inferred`; for THIS layer that would
        be the understatement, and understating provenance is as dishonest as
        inflating it. A stated basis is never overridden."""
        draft, _ = gl.validate_claim_draft({
            "claim_type": "date", "subject_mention": "Dayton",
            "event_kind": "move", "temporal_value": "1974",
            "evidence": "we moved in 1974"})
        self.assertEqual(draft["basis"], gl.CAPTURE_BASIS)
        self.assertEqual(gl.CAPTURE_BASIS, "explicit")
        self.assertIn(gl.CAPTURE_BASIS, tc.CLAIM_BASES)
        calculated, _ = gl.validate_claim_draft({
            "claim_type": "date", "subject_mention": "Dayton",
            "event_kind": "move", "temporal_value": "1974",
            "basis": "calculated", "evidence": "we moved in 1974"})
        self.assertEqual(calculated["basis"], "calculated")

    def test_an_unstated_confidence_is_not_asserted_as_zero(self):
        draft, _ = gl.validate_claim_draft({
            "claim_type": "date", "subject_mention": "Dayton",
            "event_kind": "move", "temporal_value": "1974",
            "evidence": "we moved in 1974"})
        self.assertNotIn("confidence", draft)
        stated, _ = gl.validate_claim_draft({
            "claim_type": "date", "subject_mention": "Dayton",
            "event_kind": "move", "temporal_value": "1974",
            "confidence": 0.8, "evidence": "we moved in 1974"})
        self.assertEqual(stated["confidence"], 0.8)

    def test_a_length_is_stored_as_a_length_and_never_as_an_interval(self):
        """Plan §6.4: inference must not be rendered as a false exact date."""
        age, _ = gl.validate_claim_draft({
            "claim_type": "age", "subject_mention": "me",
            "event_kind": "move", "temporal_value": "about 12",
            "evidence": "when I was about 12 we moved"})
        self.assertEqual(age["temporal_value"]["kind"], "age")
        self.assertTrue(age["temporal_value"]["approximate"])
        self.assertNotIn("earliest", age["temporal_value"])

    def test_relative_order_keeps_the_anchor_in_the_persons_own_words(self):
        draft, _ = gl.validate_claim_draft({
            "claim_type": "relative_order",
            "subject_mention": "the move to Dayton", "event_kind": "move",
            "temporal_value": {"relation": "after", "anchors": ["Mom died"]},
            "evidence": "we moved the summer after Mom died"})
        self.assertEqual(draft["temporal_value"],
                         {"relation": "after", "anchors": ["Mom died"]})


# --------------------------------------------------------------------------
# Binding
# --------------------------------------------------------------------------


#: One emitted claim, for the binding tests. Module-level because a mutable
#: class attribute is a shared object every test in the class could edit.
EMITTED_CLAIM = {"claim_type": "date", "subject_mention": "Danforth Steel",
                 "event_kind": "job", "temporal_value": "1974",
                 "evidence": "I started at Danforth Steel that fall"}


class BindingTests(unittest.TestCase):
    """A draft plus a promoted source is a claim, and nothing else changes."""

    def _draft(self) -> dict:
        draft, finding = gl.validate_claim_draft(dict(EMITTED_CLAIM))
        self.assertEqual(finding, "")
        return draft

    def test_a_bound_draft_is_the_drafts_own_fields_plus_the_binding(self):
        """The guard on the placeholder: binding ADDS the binding. If this
        ever fails, the draft layer has started re-deciding something the
        contract already decided."""
        draft = self._draft()
        bound, = gl.bind_claims([draft], source_ref=SOURCE_REF,
                                extractor_version=EXTRACTOR)
        for key, value in draft.items():
            with self.subTest(key=key):
                self.assertEqual(bound[key], value)
        self.assertEqual(bound["source_ref"], tc.validate_source_ref(SOURCE_REF))
        self.assertEqual(bound["extractor_version"], EXTRACTOR)
        self.assertEqual(bound["source_kind"], "conversation")
        self.assertTrue(tc.is_safe_id(bound["claim_id"]))

    def test_binding_the_same_draft_twice_mints_the_same_id(self):
        """A retried extraction over the same revision files nothing twice."""
        draft = self._draft()
        first, = gl.bind_claims([draft], source_ref=SOURCE_REF,
                                extractor_version=EXTRACTOR)
        second, = gl.bind_claims([draft], source_ref=SOURCE_REF,
                                 extractor_version=EXTRACTOR,
                                 now="2031-01-01T00:00:00Z")
        self.assertEqual(first["claim_id"], second["claim_id"])
        self.assertNotEqual(first["created_at"], second["created_at"])

    def test_a_different_extractor_is_a_different_claim(self):
        """§1.3: a later reading of the same prose is a NEW interpretation."""
        draft = self._draft()
        mine, = gl.bind_claims([draft], source_ref=SOURCE_REF,
                               extractor_version=EXTRACTOR)
        theirs, = gl.bind_claims([draft], source_ref=SOURCE_REF,
                                 extractor_version=EXTRACTOR + "-next")
        self.assertNotEqual(mine["claim_id"], theirs["claim_id"])

    def test_binding_collapses_duplicates(self):
        draft = self._draft()
        self.assertEqual(len(gl.bind_claims([draft, dict(draft)],
                                            source_ref=SOURCE_REF,
                                            extractor_version=EXTRACTOR)), 1)

    def test_editing_a_leaf_is_a_new_extractor(self):
        """The prompt version is a digest of the leaf's own bytes, so a prompt
        edit lands on a NEW receipt path beside the old rather than rewriting
        yesterday's reading."""
        first = gl.claim_extractor("listener", leaf="a leaf", model="m")
        second = gl.claim_extractor("listener", leaf="a leaf, edited",
                                    model="m")
        self.assertNotEqual(first["prompt_version"], second["prompt_version"])
        self.assertNotEqual(gl.claim_extractor_version(first),
                            gl.claim_extractor_version(second))

    def test_the_block_and_the_string_cannot_say_two_different_things(self):
        block = lr.recorder_extractor(model="haiku-class")
        self.assertEqual(
            lr.recorder_extractor_version(model="haiku-class"),
            tc.extractor_version_string(
                block["name"], schema_version=block["schema_version"],
                prompt_version=block["prompt_version"], model=block["model"]))
        self.assertNotEqual(lr.recorder_extractor_version(),
                            gl.listener_extractor_version())


# --------------------------------------------------------------------------
# The parse
# --------------------------------------------------------------------------


class ParseTests(unittest.TestCase):
    """Each claim validated ALONE, exactly as each record already is."""

    def test_one_refused_claim_never_takes_a_sibling_with_it(self):
        drafts, findings = gl.parse_claims([
            {"claim_type": "date", "subject_mention": "Ada and Bo",
             "event_kind": "child_born", "temporal_value": "1979",
             "evidence": "Ada and Bo"},
            {"claim_type": "date", "subject_mention": "Ada",
             "event_kind": "child_born", "temporal_value": "1979",
             "evidence": "Ada, 1979"}])
        self.assertEqual([d["subject_mention"] for d in drafts], ["Ada"])
        self.assertEqual(findings,
                         (gl.claim_refused("aggregate_subject_mention"),))

    def test_the_singular_envelope_is_read_too(self):
        drafts, _ = lr.parse_recorder_claims(json.dumps(
            {"claim": {"claim_type": "identity", "subject_mention": "Ruth",
                       "evidence": "my sister Ruth"}}))
        self.assertEqual(len(drafts), 1)

    def test_a_completion_with_no_claims_list_yields_no_claims(self):
        """THE BRIDGE. Every pre-v229 stored completion parses as it did."""
        raw = '{"landmark": {"domain": "military", "none": true}}'
        self.assertEqual(lr.parse_recorder_claims(raw), ((), ()))
        self.assertEqual(lr.parse_recorder_output(raw),
                         ({"domain": "military", "none": True},))
        heard = gl.parse_listener_output('{"landmarks": [], "people": []}')
        self.assertEqual(heard.claims, ())

    def test_a_malformed_envelope_degrades_and_never_raises(self):
        for raw in ("not json", "[]", "", None, '{"claims": "nope"}'):
            with self.subTest(raw=raw):
                self.assertEqual(lr.parse_recorder_claims(raw), ((), ()))

    def test_a_fenced_completion_is_tolerated_exactly_as_elsewhere(self):
        raw = ('```json\n{"claims": [{"claim_type": "identity", '
               '"subject_mention": "Ruth", "evidence": "my sister Ruth"}]}\n```')
        drafts, _ = lr.parse_recorder_claims(raw)
        self.assertEqual(len(drafts), 1)

    def test_the_three_listener_lists_are_independent(self):
        heard = gl.parse_listener_output(emitted(
            landmarks=[{"domain": "residences", "label": "Dayton",
                        "city": "Dayton"}],
            people=[{"name": "Hal", "relation": "colleague", "born": "1948",
                     "basis": "stated"}],
            claims=[{"claim_type": "date", "subject_mention": "Hal",
                     "event_kind": "birth", "temporal_value": "1948",
                     "evidence": "my old boss Hal was born in 1948"}]))
        self.assertEqual(len(heard.landmarks), 1)
        self.assertEqual(heard.people, ())
        self.assertEqual(len(heard.claims), 1)
        self.assertIn(gl.DROPPED_NON_FAMILY, heard.findings)
        self.assertEqual(len(heard), 2)

    def test_the_prompt_key_set_is_the_contracts_names(self):
        """One vocabulary. Every key a leaf may write is a field name the
        contract already has, so a leaf edit cannot invent a shape."""
        self.assertLessEqual(gl.CLAIM_PROMPT_KEYS,
                             set(tc.TemporalClaim.__dataclass_fields__))
        self.assertLessEqual(set(gl.CLAIM_DRAFT_KEYS), gl.CLAIM_PROMPT_KEYS)


# --------------------------------------------------------------------------
# The backstops, read over the new shape
# --------------------------------------------------------------------------


class BackstopTests(unittest.TestCase):
    """Never silence, and never a fabricated claim to satisfy a lint."""

    MESSAGE = "We moved to Dayton in 1974."

    def test_a_claim_is_a_thing_heard(self):
        claim = {"claim_type": "date", "subject_mention": "Dayton",
                 "event_kind": "move", "temporal_value": "1974",
                 "evidence": "we moved to Dayton in 1974"}
        self.assertIsNone(gl.listener_heard_nothing(self.MESSAGE, (), (),
                                                    claims=(claim,)))
        self.assertIsNotNone(gl.listener_heard_nothing(self.MESSAGE, (), (),
                                                       claims=()))

    def test_the_lint_is_unchanged_when_neither_shape_comes_back(self):
        finding = gl.listener_heard_nothing(self.MESSAGE, (), (), claims=())
        self.assertEqual(finding["lint"], gl.LISTENER_HEARD_NOTHING_LINT)

    def test_the_plurality_class_answers_none_for_what_it_cannot_decide(self):
        for message, claims in (
            ("", ({"claim_type": "date", "subject_mention": "Ada"},)),
            ("Ada and Bo and Cy.", ()),
        ):
            with self.subTest(message=message):
                self.assertIsNone(
                    gl.claims_missing_subjects(message, claims))

    def test_one_claim_for_three_named_people_is_a_finding(self):
        claims = [{"claim_type": "date", "subject_mention": "Needy Beecham",
                   "event_kind": "death", "temporal_value": "1988",
                   "evidence": "Needy Beecham died in 1988"}]
        finding = gl.claims_missing_subjects(
            "Needy Beecham died in 1988, Darvin Beecham in 1991, and "
            "James Edwin Thorne in 2003.", claims)
        self.assertIsNotNone(finding)
        self.assertEqual(finding["lint"], gl.CLAIMS_MISSING_SUBJECTS_LINT)
        self.assertIn("darvin beecham", finding["missed"])

    def test_a_name_already_in_the_store_is_not_a_missed_claim(self):
        claims = [{"claim_type": "date", "subject_mention": "Darvin Beecham",
                   "event_kind": "death", "temporal_value": "1991",
                   "evidence": "Darvin in 1991"}]
        self.assertIsNone(gl.claims_missing_subjects(
            "Needy Beecham and Darvin Beecham.", claims,
            known_labels=("Needy Beecham",)))

    def test_it_borrows_v214s_primitives_rather_than_re_typing_them(self):
        """Recurring-defect doctrine: ONE definition of what a name looks
        like. If these ever diverge, the package has two."""
        self.assertIs(gl.claims_missing_subjects.__globals__["li"], li)
        self.assertTrue(callable(li._name_groups))  # noqa: SLF001
        self.assertTrue(callable(li._record_terms))  # noqa: SLF001

    def test_the_plurality_finding_never_withholds(self):
        """v214's severity, inherited: one regeneration, then file what you
        have. A partial set of claims is worth more than none."""
        message = ("Needy Beecham died in 1988, Darvin Beecham in 1991, and "
                   "James Edwin Thorne in 2003.")
        one = emitted(landmarks=[], people=[], claims=[
            {"claim_type": "date", "subject_mention": "Needy Beecham",
             "event_kind": "death", "temporal_value": "1988",
             "evidence": "Needy Beecham died in 1988"}])
        seen: list[str] = []

        def call(prompt: str, model: str) -> str:
            seen.append(prompt)
            return one

        outcome = lr.listen_to_answer(answer=message, reply="All three.",
                                      call=call)
        self.assertEqual(outcome.status, lr.STATUS_RECORDED)
        self.assertEqual(outcome.attempts, lr.MAX_ATTEMPTS)
        self.assertEqual(len(outcome.claims), 1)
        self.assertEqual(list(outcome.lint_ids),
                         [gl.CLAIMS_MISSING_SUBJECTS_LINT])
        self.assertIn("One claim per asserted fact", seen[1])

    def test_the_focused_guarantee_is_not_weakened_by_a_claim(self):
        """A claim never excuses the domain's own missing record. The focused
        recorder is the canonical writer for a focused turn (plan §2.1, §6.1),
        and `answer_must_record` still reads the RECORDS and only the
        records — the claim rides out on the outcome regardless."""
        raw = emitted(landmarks=[], claims=[
            {"claim_type": "identity", "subject_mention": "Zurich",
             "evidence": "I served that in Zurich"}])
        outcome = lr.record_answer(
            domain="military",
            answer="I have not served in the military. I did serve a mission "
                   "in Zurich.",
            reply="Zurich — two years of it.",
            call=lambda prompt, model: raw)
        self.assertEqual(outcome.status, lr.STATUS_WITHHELD)
        self.assertEqual(list(outcome.lint_ids), [li.ANSWER_MUST_RECORD_LINT])
        self.assertEqual(len(outcome.claims), 1)

    def test_a_claim_alongside_no_record_is_recorded_not_nothing(self):
        """...and where the domain genuinely had no answer, a claim heard
        beside it is still a thing heard."""
        raw = emitted(landmarks=[], claims=[
            {"claim_type": "date", "subject_mention": "the porch",
             "event_kind": "move", "temporal_value": "1974",
             "evidence": "we redid the porch in 1974"}])
        outcome = lr.record_answer(
            domain="military", answer="we redid the porch in 1974",
            reply="A good year for it.",
            call=lambda prompt, model: raw)
        self.assertEqual(outcome.status, lr.STATUS_RECORDED)
        self.assertEqual(outcome.records, ())
        self.assertEqual(len(outcome.claims), 1)


# --------------------------------------------------------------------------
# The goldens
# --------------------------------------------------------------------------


class GoldenTests(unittest.TestCase):
    """The founder shapes, end to end through the one loop."""

    def setUp(self) -> None:
        data = json.loads(GOLDEN.read_text(encoding="utf-8"))
        self.assertEqual(data["fixture_id"], "claims-extraction-01")
        self.cases = {case["case_id"]: case for case in data["cases"]}

    def _drive(self, case: dict):
        raws = [case["attempt"]["raw"]]
        if "regenerated" in case:
            raws.append(case["regenerated"]["raw"])
        seen: list[str] = []

        def call(prompt: str, model: str) -> str:
            seen.append(prompt)
            return raws[min(len(seen), len(raws)) - 1]

        if case["mode"] == "focused":
            outcome = lr.record_answer(
                domain=case["domain"], answer=case["user_message"],
                reply=case["reply"], landmarks=case["landmarks"], call=call)
        else:
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
                self.assertEqual(len(outcome.claims),
                                 case["expected_claim_count"])
                self.assertEqual(
                    [c["subject_mention"] for c in outcome.claims],
                    case["expected_claim_subjects"])
                self.assertEqual([c["claim_type"] for c in outcome.claims],
                                 case["expected_claim_types"])
                self.assertEqual([c.get("event_kind") for c in outcome.claims],
                                 case["expected_event_kinds"])
                self.assertEqual(len(outcome.records),
                                 case["expected_record_count"])
                if "prescreen_fires" in case:
                    self.assertEqual(
                        gl.may_contain_datable(case["user_message"]).fired,
                        case["prescreen_fires"])

    def test_twelve_jobs_are_twelve_claims(self):
        outcome, _ = self._drive(
            self.cases["twelve-jobs-are-twelve-claims-and-never-an-aggregate"])
        self.assertEqual(len(outcome.claims), 12)
        self.assertEqual({c["event_kind"] for c in outcome.claims}, {"job"})
        self.assertEqual(len({c["subject_mention"] for c in outcome.claims}), 12)
        # ...and the v214 record set beside them is untouched.
        self.assertEqual(len(outcome.records), 12)

    def test_four_children_are_four_people_and_four_births(self):
        """Plan §5.1: person identity and the event that dates them are
        DISTINCT records."""
        outcome, _ = self._drive(
            self.cases["four-children-are-four-people-and-four-births"])
        identities = [c for c in outcome.claims
                      if c["claim_type"] == "identity"]
        births = [c for c in outcome.claims
                  if c.get("event_kind") == "child_born"]
        self.assertEqual(len(identities), 4)
        self.assertEqual(len(births), 4)
        for claim in identities:
            with self.subTest(subject=claim["subject_mention"]):
                self.assertIsNone(claim["temporal_value"])
                self.assertNotIn("event_kind", claim)

    def test_the_relative_move_is_retained_and_not_dated(self):
        """§6.4's repeal: the leaf used to say to leave this out."""
        outcome, _ = self._drive(self.cases["we-moved-when-james-was-two"])
        claim, = outcome.claims
        self.assertEqual(claim["claim_type"], "relative_order")
        self.assertEqual(claim["temporal_value"]["relation"], "within")
        self.assertEqual(claim["temporal_value"]["anchors"],
                         ["when James was two"])
        # The landmark record beside it is still undated, exactly as before.
        self.assertNotIn("date", outcome.records[0])

    def test_a_non_family_date_is_refused_as_a_roster_row_and_kept_as_a_claim(self):
        """§2.1: capture is not restricted to family. The owner's family-only
        ruling is a rule about the ROSTER, and it is untouched."""
        case = self.cases["a-neighbours-child-is-a-claim-and-not-a-roster-row"]
        outcome, _ = self._drive(case)
        self.assertEqual(outcome.people, ())
        self.assertIn(gl.DROPPED_NON_FAMILY, outcome.findings)
        self.assertEqual(outcome.claims[0]["subject_mention"],
                         "my neighbour's boy")

    def test_the_backstop_still_withholds_on_silence(self):
        outcome, seen = self._drive(
            self.cases[
                "the-backstop-still-withholds-when-neither-shape-comes-back"])
        self.assertEqual(outcome.status, lr.STATUS_WITHHELD)
        self.assertEqual(len(seen), 2)
        self.assertIn("You recorded nothing", seen[1])


# --------------------------------------------------------------------------
# The write path
# --------------------------------------------------------------------------


class FilingTests(unittest.TestCase):
    """One message, one promoted source, one receipt, N claims."""

    MESSAGE = ("We moved to Dayton in 1974, and my sister Ruth was born "
               "in 1948.")

    def setUp(self) -> None:
        self.vault = root_parent_tmp(self, ROOT, prefix="claims-vault-")

    def _extraction(self):
        raw = emitted(landmarks=[], people=[], claims=[
            {"claim_type": "date", "subject_mention": "Dayton",
             "event_kind": "move", "temporal_value": "1974",
             "evidence": "We moved to Dayton in 1974"},
            {"claim_type": "identity", "subject_mention": "my sister Ruth",
             "evidence": "my sister Ruth was born in 1948"},
            {"claim_type": "date", "subject_mention": "my sister Ruth",
             "event_kind": "birth", "temporal_value": "1948",
             "evidence": "my sister Ruth was born in 1948"}])
        return lr.listen_to_answer(answer=self.MESSAGE, reply="Dayton, Ruth.",
                                   call=lambda prompt, model: raw)

    def _file_it(self, outcome, **kwargs):
        return lr.file_claims(
            self.vault, outcome, message_text=self.MESSAGE,
            extractor_version=gl.listener_extractor_version(),
            extractor=gl.listener_extractor(),
            session_ref="session:abc", turn_ref="turn:7",
            recorder=gl.LISTENER_EXTRACTOR, **kwargs)

    def test_the_message_becomes_a_vault_source_before_anything_cites_it(self):
        """Owner amendment 2 / option B: no claim's only citation is a session
        row, and one message with N facts is promoted ONCE."""
        outcome = self._extraction()
        source_ref, receipt_path = self._file_it(outcome)
        self.assertTrue((self.vault / source_ref.source_path).is_file())
        self.assertTrue(receipt_path.is_file())
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        self.assertEqual(len(receipt["claims"]), 3)
        for claim in receipt["claims"]:
            with self.subTest(claim=claim["claim_id"]):
                self.assertEqual(claim["source_ref"]["revision"],
                                 source_ref.revision)
        sources = list((self.vault / ts.CONVERSATION_SOURCES_DIR).rglob("*.md"))
        self.assertEqual(len(sources), 1)

    def test_the_receipt_names_the_idempotency_key_the_contract_derives(self):
        outcome = self._extraction()
        source_ref, receipt_path = self._file_it(outcome)
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        self.assertEqual(
            receipt["idempotency_key"],
            tc.derive_extraction_idempotency_key(
                session_ref="session:abc", turn_ref="turn:7",
                source_ref=source_ref, recorder=gl.LISTENER_EXTRACTOR,
                extractor_version=gl.listener_extractor_version()))

    def test_filing_the_same_extraction_twice_writes_nothing_twice(self):
        outcome = self._extraction()
        first_ref, first_path = self._file_it(outcome)
        before = first_path.read_bytes()
        second_ref, second_path = self._file_it(outcome)
        self.assertEqual(first_ref.key, second_ref.key)
        self.assertEqual(second_path, first_path)
        self.assertEqual(second_path.read_bytes(), before)
        self.assertEqual(len(ts.receipt_relative_paths(self.vault)), 1)

    def test_a_message_that_produced_nothing_files_nothing(self):
        """Amendment 2's own rule, not an optimization."""
        outcome = lr.listen_to_answer(
            answer="I love a good pizza.", reply="A short list.",
            call=lambda prompt, model: emitted(landmarks=[], people=[],
                                               claims=[]))
        self.assertIsNone(self._file_it(outcome))
        self.assertFalse((self.vault / ts.CONVERSATION_SOURCES_DIR).exists())

    def test_the_filed_claims_fold_into_an_active_index_with_no_model_call(self):
        """Wave B's exit gate, reached from wave C's writer."""
        self._file_it(self._extraction())
        index = ts.rebuild_active_index(self.vault)
        active = ts.active_claims(index)
        self.assertEqual(len(active), 3)
        self.assertEqual(
            {c["subject_mention"] for c in active},
            {"Dayton", "my sister Ruth"})
        again = ts.fold_active_index(self.vault)
        self.assertEqual(ts.active_index_bytes(again),
                         ts.active_index_bytes(index))

    def test_the_focused_recorder_files_through_the_same_seam(self):
        raw = emitted(
            landmarks=[{"domain": "residences", "label": "Dayton",
                        "city": "Dayton", "date": {"best": "1974"}}],
            claims=[{"claim_type": "date", "subject_mention": "Dayton",
                     "event_kind": "move", "temporal_value": "1974",
                     "evidence": "We moved to Dayton in 1974"}])
        outcome = lr.record_answer(
            domain="residences", answer=self.MESSAGE, reply="Dayton.",
            call=lambda prompt, model: raw)
        self.assertEqual(outcome.status, lr.STATUS_RECORDED)
        result = lr.file_claims(
            self.vault, outcome, message_text=self.MESSAGE,
            extractor_version=lr.recorder_extractor_version(),
            extractor=lr.recorder_extractor(),
            recorder=lr.RECORDER_EXTRACTOR)
        self.assertIsNotNone(result)
        receipt = json.loads(result[1].read_text(encoding="utf-8"))
        self.assertEqual(receipt["recorder"], lr.RECORDER_EXTRACTOR)
        self.assertEqual(receipt["extractor"]["name"], lr.RECORDER_EXTRACTOR)


# --------------------------------------------------------------------------
# The leaves, and what ships
# --------------------------------------------------------------------------


class LeafTests(unittest.TestCase):
    """The vocabulary the leaves offer is the contract's own, derived."""

    LEAVES = ("recorder.md", "listener.md")

    def _leaf(self, name: str) -> str:
        return (ROOT / "interactions" / "landmarks" / "prompt"
                / name).read_text(encoding="utf-8")

    def test_both_leaves_ask_for_claims_and_carry_the_vocabulary_tokens(self):
        for name in self.LEAVES:
            with self.subTest(leaf=name):
                leaf = self._leaf(name)
                self.assertIn('"claims": [', leaf)
                self.assertIn("{claim_types}", leaf)
                self.assertIn("{event_kinds}", leaf)

    def test_the_rendered_vocabulary_is_the_contracts_own(self):
        """DERIVED, never re-typed: the day a claim type or an event kind
        joins the MODEL's half of the contract, the leaf offers it with no
        second edit — and the day one joins the substrate's half WITHOUT
        joining the model's, the leaf keeps quiet about it.

        Timeline Fix 05 (lifehug-platform#759) made those two halves
        different: `occurrence` is a real claim type and it is the
        deterministic classifier migration's alone. These extractors exist to
        hear TIME and their backstops are built around a withheld date;
        offering them a dateless type would let a model file "something
        happened" instead of listening harder.
        """
        prompt = gl.build_listener_prompt(answer="x", reply="y")
        self.assertIn(" | ".join(tc.MODEL_CLAIM_TYPES), prompt)
        self.assertIn(gl.render_event_kinds(), prompt)
        for kind in tc.EVENT_KINDS:
            with self.subTest(kind=kind):
                self.assertIn(kind, prompt)
        recorder = lr.build_recorder_prompt(
            domain="work", question_asked="What work have you done?",
            answer="x", reply="y")
        self.assertIn(" | ".join(tc.MODEL_CLAIM_TYPES), recorder)
        self.assertIn(gl.render_event_kinds(), recorder)
        for rendered in (prompt, recorder):
            for kind in set(tc.CLAIM_TYPES) - set(tc.MODEL_CLAIM_TYPES):
                with self.subTest(withheld=kind):
                    self.assertNotIn(kind, rendered)

    def test_the_seed_set_says_out_loud_that_it_is_a_seed(self):
        """The contract accepts any lowercase token, and a leaf that read the
        list as a fence would drop an event the person plainly named."""
        for name in self.LEAVES:
            with self.subTest(leaf=name):
                self.assertIn("a starting set, not", self._leaf(name))

    def test_the_relative_time_repeal_is_in_the_listener_leaf(self):
        """§6.4. The old instruction — leave the record undated and the
        arithmetic will reach it later — was the drop, because nothing gave
        the arithmetic anything to reach."""
        leaf = self._leaf("listener.md")
        self.assertNotIn("leave the record undated and the", leaf)
        self.assertIn("Relative time is kept, not dropped", leaf)

    def test_the_non_family_repeal_is_in_the_listener_leaf(self):
        """§2.1. The family-only rule keeps its roster and loses its veto."""
        leaf = self._leaf("listener.md")
        self.assertNotIn("leave them out entirely", leaf)
        self.assertIn("Anyone's date counts", leaf)
        # ...and the roster rule itself is untouched.
        self.assertIn("A person who is not family\n  is not a `people` record",
                      leaf)

    def test_the_leaves_still_have_no_voice_and_no_transcript(self):
        """The property every size pin here has ever held."""
        for prompt in (gl.build_listener_prompt(answer="x", reply="y"),
                       lr.build_recorder_prompt(domain="work",
                                                question_asked="?",
                                                answer="x", reply="y")):
            for absent in ("## IDENTITY", "## BEHAVIOR", "## EXAMPLES",
                           "## SESSION"):
                self.assertNotIn(absent, prompt)

    def test_the_new_files_ship_in_framework_files(self):
        manifest = json.loads(
            (ROOT / "system" / "version.json").read_text(encoding="utf-8"))
        for shipped in (
            "interactions/landmarks/evals/goldens/claims-extraction-01.json",
            "tests/test_extraction_claims.py",
        ):
            with self.subTest(path=shipped):
                self.assertIn(shipped, manifest["framework_files"])


if __name__ == "__main__":
    unittest.main()
