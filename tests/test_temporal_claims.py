"""v219 — the temporal claim contracts (audited timeline build plan §4.2, §5).

Every rule the module claims to enforce gets a test that would fail if the rule
were softened: the founder's four children stay four records, a date is the
date of an event, the raw mention survives resolution, a claim always cites a
vault source and an immutable revision, and every derived id is pinned by a
golden so a refactor cannot quietly re-mint the vault.

Synthetic data only; NEVER references ~/Workspace/dave.
"""

from __future__ import annotations

import ast
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "system"))

import chronology as chrono  # noqa: E402
import temporal_claims as tc  # noqa: E402

REV = "sha256:" + "1" * 64
REF = {"source_id": "sources/manual/2026-08-26-porch.md", "revision": REV}
EXT = "listener/schema:1/prompt:c0ffee/model:test-model"
NOW = "2026-08-26T10:00:00Z"


def raised_finding_codes(path: Path) -> set[str]:
    """Every finding id the module actually raises, read out of its own AST."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    codes: set[str] = set()
    for node in ast.walk(tree):
        # Every construction of an error class counts, not only `raise` — a
        # module may build the error in a helper and raise it at the call site.
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", "")
        if not (name.endswith("Error") or name == "error"):
            continue
        if node.args and isinstance(node.args[0], ast.Constant):
            value = node.args[0].value
            if isinstance(value, str):
                codes.add(value)
    return codes


def claim(**overrides) -> dict:
    """A minimal valid claim, overridable field by field."""
    base = {
        "source_ref": dict(REF),
        "source_kind": "conversation",
        "claim_type": "date",
        "subject_mention": "Ada",
        "event_kind": "birth",
        "temporal_value": "1984",
        "evidence": [{"quote": "Ada was born in 1984", "turn_ref": "turn:3"}],
        "basis": "explicit",
        "confidence": 0.9,
        "extractor_version": EXT,
        "created_at": NOW,
    }
    base.update(overrides)
    return {k: v for k, v in base.items() if v is not None or k == "temporal_value"}


class VocabularyTests(unittest.TestCase):
    def test_the_closed_vocabularies_are_the_plans(self):
        self.assertEqual(
            tc.SOURCE_KINDS, ("conversation", "correction", "import", "system_derived")
        )
        self.assertEqual(
            tc.CLAIM_TYPES,
            ("date", "range", "age", "duration", "relative_order", "identity"),
        )
        self.assertEqual(tc.CLAIM_BASES, ("explicit", "calculated", "inferred"))
        self.assertEqual(
            tc.CLAIM_STATUSES, ("active", "superseded", "retracted", "disputed")
        )
        self.assertEqual(
            tc.CONSTRAINT_RELATIONS, ("before", "after", "between", "within")
        )

    def test_every_relation_declares_an_anchor_arity(self):
        self.assertEqual(
            sorted(tc.RELATION_ANCHOR_ARITY), sorted(tc.CONSTRAINT_RELATIONS)
        )
        self.assertEqual(tc.RELATION_ANCHOR_ARITY["between"], (2, 2))

    def test_the_event_kind_seed_names_the_plans_examples(self):
        # §5.1's own list, plus §10's required relationship distinctions.
        for kind in ("met", "dating_started", "married", "school", "move", "job"):
            self.assertIn(kind, tc.EVENT_KINDS)
        for kind in ("engaged", "separated", "reconciled"):
            self.assertIn(kind, tc.EVENT_KINDS)
        self.assertTrue(all(tc.EVENT_KIND_RE.fullmatch(k) for k in tc.EVENT_KINDS))

    def test_event_kinds_are_a_seed_not_a_closed_set(self):
        # §5.1 ends its list with "...", and refusing an event the listener
        # genuinely heard would drop the claim.
        self.assertFalse(tc.is_seed_event_kind("apprenticeship_started"))
        normalized = tc.validate_temporal_claim(claim(event_kind="apprenticeship_started"))
        self.assertEqual(normalized["event_kind"], "apprenticeship_started")
        with self.assertRaises(tc.TemporalClaimError) as caught:
            tc.validate_temporal_claim(claim(event_kind="Not A Kind"))
        self.assertEqual(caught.exception.code, "unknown_event_kind")

    def test_every_claim_type_has_exactly_one_value_shape(self):
        # A new claim_type with no declared value shape would fall through to
        # the date branch and be silently mis-stored; this partition makes that
        # a build failure instead.
        shaped = set(tc.DATED_CLAIM_TYPES) | set(tc.QUANTITY_CLAIM_TYPES)
        self.assertEqual(
            set(tc.CLAIM_TYPES) - shaped - {"relative_order", "identity"}, set()
        )
        self.assertEqual(
            set(tc.DATED_CLAIM_TYPES) & set(tc.QUANTITY_CLAIM_TYPES), set()
        )

    def test_claim_basis_covers_every_chronology_basis(self):
        # Recurring-defect doctrine: a new date basis fails this test instead
        # of silently rendering as "inferred" on the page.
        self.assertEqual(
            sorted(tc.CLAIM_BASIS_BY_DATE_BASIS), sorted(chrono.BASES)
        )
        self.assertEqual(
            set(tc.CLAIM_BASIS_BY_DATE_BASIS.values()) - set(tc.CLAIM_BASES), set()
        )

    def test_unknown_date_basis_degrades_to_the_weakest_class(self):
        self.assertEqual(tc.claim_basis_for_date_basis("stated"), "explicit")
        self.assertEqual(tc.claim_basis_for_date_basis("age"), "calculated")
        self.assertEqual(tc.claim_basis_for_date_basis("nonsense"), "inferred")


class SourceRefTests(unittest.TestCase):
    def test_a_claim_always_cites_a_vault_source(self):
        # Owner amendment Q2/option B: no claim's only citation is a session row.
        with self.assertRaises(tc.SourceRefError) as caught:
            tc.validate_source_ref({"revision": REV})
        self.assertEqual(caught.exception.code, "source_ref_missing_source_id")

    def test_a_claim_always_cites_an_immutable_revision(self):
        with self.assertRaises(tc.SourceRefError) as caught:
            tc.validate_source_ref({"source_id": "sources/manual/x.md"})
        self.assertEqual(caught.exception.code, "source_ref_missing_revision")
        with self.assertRaises(tc.SourceRefError) as caught:
            tc.validate_source_ref({"source_id": "sources/manual/x.md", "revision": "latest"})
        self.assertEqual(caught.exception.code, "source_ref_revision_unrecognized")

    def test_both_revision_spellings_this_repo_already_uses_normalize(self):
        self.assertEqual(tc.normalized_revision("A" * 64), "sha256:" + "a" * 64)
        self.assertEqual(tc.normalized_revision("b" * 40), "git:" + "b" * 40)
        self.assertEqual(tc.normalized_revision("sha256:" + "c" * 64), "sha256:" + "c" * 64)
        self.assertIsNone(tc.normalized_revision("v1"))

    def test_the_key_form_round_trips(self):
        ref = tc.source_ref_from_dict(REF)
        self.assertEqual(ref.key, f"{REF['source_id']}@{REV}")
        self.assertEqual(tc.validate_source_ref(ref.key), dict(REF))

    def test_the_tolerant_reader_returns_none_rather_than_raising(self):
        self.assertIsNone(tc.source_ref_from_dict(None))
        self.assertIsNone(tc.source_ref_from_dict({"source_id": "x"}))


class OneFactOneRecordTests(unittest.TestCase):
    """Plan §5.1 and §10: the cardinality defect this substrate exists to end."""

    FOUNDER_SHAPE = "I have four children: Ada, Bo, Cy, and Della"

    def test_the_founder_shape_is_refused_by_name_with_its_parts(self):
        with self.assertRaises(tc.TemporalClaimError) as caught:
            tc.validate_temporal_claim(claim(subject_mention=self.FOUNDER_SHAPE))
        error = caught.exception
        self.assertEqual(error.code, "aggregate_subject_mention")
        self.assertEqual(error.detail, ("Ada", "Bo", "Cy", "Della"))

    def test_the_founder_shape_splits_into_four_and_only_four(self):
        self.assertEqual(
            tc.split_subject_enumeration(self.FOUNDER_SHAPE), ("Ada", "Bo", "Cy", "Della")
        )
        self.assertEqual(tc.split_subject_enumeration("Ada, Bo and Cy"), ("Ada", "Bo", "Cy"))
        self.assertEqual(tc.split_subject_enumeration("Ada and Bo"), ("Ada", "Bo"))

    def test_four_children_become_four_distinct_claims(self):
        ids = set()
        for name in tc.split_subject_enumeration(self.FOUNDER_SHAPE):
            normalized = tc.validate_temporal_claim(
                claim(
                    claim_type="identity",
                    subject_mention=name,
                    event_kind=None,
                    temporal_value=None,
                )
            )
            self.assertEqual(normalized["subject_mention"], name)
            ids.add(normalized["claim_id"])
        self.assertEqual(len(ids), 4)

    def test_grammar_is_not_a_list(self):
        # "and" inside an ordinary phrase must not be mistaken for enumeration:
        # the parts are longer than a name, so the "and" was grammar.
        for text in (
            "the summer after we moved and settled in",
            "my mother",
            "the place we rented before the second baby and after the fire",
        ):
            with self.subTest(text=text):
                self.assertEqual(tc.split_subject_enumeration(text), (text,))

    def test_two_name_sized_subjects_are_two_subjects(self):
        # The subject slot names ONE subject, so a conjunction of two
        # name-sized phrases is a list even without commas. This is the
        # deliberate trade recorded in split_subject_enumeration's docstring.
        self.assertEqual(tc.split_subject_enumeration("Mom and Dad"), ("Mom", "Dad"))
        self.assertEqual(
            tc.split_subject_enumeration("the house on Cedar and the barn behind it"),
            ("the house on Cedar", "the barn behind it"),
        )

    def test_a_subject_is_not_a_sentence(self):
        with self.assertRaises(tc.TemporalClaimError) as caught:
            tc.validate_temporal_claim(claim(subject_mention="x" * 400))
        self.assertEqual(caught.exception.code, "subject_mention_too_long")


class PersonVersusEventTests(unittest.TestCase):
    """Plan §5.1, §6.3: identity and event transitions are distinct records."""

    def test_a_date_is_the_date_of_an_event_never_of_a_person(self):
        with self.assertRaises(tc.TemporalClaimError) as caught:
            tc.validate_temporal_claim(claim(event_kind=None))
        self.assertEqual(caught.exception.code, "temporal_claim_needs_event_kind")

    def test_an_identity_claim_carries_no_date(self):
        with self.assertRaises(tc.TemporalClaimError) as caught:
            tc.validate_temporal_claim(
                claim(claim_type="identity", event_kind=None, temporal_value="1984")
            )
        self.assertEqual(
            caught.exception.code, "identity_claim_carries_no_temporal_value"
        )

    def test_an_identity_claim_carries_no_event(self):
        with self.assertRaises(tc.TemporalClaimError) as caught:
            tc.validate_temporal_claim(
                claim(claim_type="identity", event_kind="married", temporal_value=None)
            )
        self.assertEqual(caught.exception.code, "identity_claim_carries_no_event")

    def test_six_relationship_transitions_are_six_records(self):
        # "When did you and Katie first meet / start dating / get married" are
        # different questions with different answers (plan §2.2, §10).
        ids = {
            tc.validate_temporal_claim(
                claim(subject_mention="Katie", event_kind=kind, temporal_value=str(year))
            )["claim_id"]
            for kind, year in (
                ("met", 1994),
                ("dating_started", 1995),
                ("engaged", 1997),
                ("married", 1998),
                ("separated", 2005),
                ("reconciled", 2006),
            )
        }
        self.assertEqual(len(ids), 6)


class RawMentionTests(unittest.TestCase):
    def test_the_raw_mention_is_required_even_when_the_ref_resolves(self):
        with self.assertRaises(tc.TemporalClaimError) as caught:
            tc.validate_temporal_claim(
                claim(subject_mention="", subject_ref="person/ada")
            )
        self.assertEqual(caught.exception.code, "subject_mention_required")

    def test_resolving_later_never_re_mints_the_claim(self):
        before = tc.validate_temporal_claim(claim(subject_mention="AJ"))
        after = tc.validate_temporal_claim(
            claim(
                subject_mention="AJ",
                subject_ref="person/aj",
                subject_resolution={
                    "candidates": ["person/aj", "person/anna-jane"],
                    "reason": "only AJ in the roster with a birth year",
                    "confidence": 0.8,
                },
            )
        )
        self.assertEqual(before["claim_id"], after["claim_id"])
        self.assertEqual(after["subject_mention"], "AJ")
        self.assertEqual(after["subject_ref"], "person/aj")
        self.assertEqual(after["subject_resolution"]["candidates"][0], "person/aj")

    def test_typography_does_not_fork_identity(self):
        one = tc.validate_temporal_claim(claim(subject_mention="Aunt Della"))
        two = tc.validate_temporal_claim(claim(subject_mention="aunt  della."))
        self.assertEqual(one["claim_id"], two["claim_id"])


class EvidenceTests(unittest.TestCase):
    def test_a_claim_without_evidence_is_not_a_claim(self):
        with self.assertRaises(tc.TemporalClaimError) as caught:
            tc.validate_temporal_claim(claim(evidence=[]))
        self.assertEqual(caught.exception.code, "evidence_required")

    def test_a_quotation_is_bounded_and_never_cut_mid_word(self):
        long_quote = ("porchlight " * 60).strip()
        bounded = tc.bounded_quote(long_quote)
        self.assertLessEqual(len(bounded), tc.MAX_EVIDENCE_QUOTE_CHARS)
        self.assertTrue(bounded.endswith("…"))
        self.assertNotIn("porchligh…", bounded)
        self.assertTrue(bounded[:-1].rstrip().endswith("porchlight"))

    def test_a_short_quotation_is_left_alone(self):
        self.assertEqual(tc.bounded_quote("  we  moved in 1984 "), "we moved in 1984")

    def test_a_reversed_span_is_refused(self):
        with self.assertRaises(tc.TemporalClaimError) as caught:
            tc.validate_evidence_span({"quote": "we moved", "start": 40, "end": 12})
        self.assertEqual(caught.exception.code, "evidence_span_reversed")

    def test_the_turn_is_recorded_beside_the_source_not_instead_of_it(self):
        normalized = tc.validate_temporal_claim(claim())
        span = normalized["evidence"][0]
        self.assertEqual(span["turn_ref"], "turn:3")
        self.assertEqual(normalized["source_ref"]["revision"], REV)


class TemporalValueTests(unittest.TestCase):
    def test_dates_go_through_chronology_and_nowhere_else(self):
        normalized = tc.validate_temporal_claim(claim(temporal_value="spring 2001"))
        value = normalized["temporal_value"]
        self.assertEqual(value["best"], "2001-21")
        self.assertEqual((value["earliest"], value["latest"]), ("2001-03", "2001-05"))
        self.assertEqual(value["granularity"], "season")

    def test_a_date_record_object_is_accepted_as_itself(self):
        record = chrono.DateRecord(
            best="1984", earliest="1984", latest="1984", basis="stated",
            confidence="certain",
        )
        normalized = tc.validate_temporal_claim(claim(temporal_value=record))
        self.assertEqual(normalized["temporal_value"]["best"], "1984")

    def test_an_unusable_value_is_a_named_failure(self):
        with self.assertRaises(tc.TemporalClaimError) as caught:
            tc.validate_temporal_claim(claim(temporal_value="whenever"))
        self.assertEqual(caught.exception.code, "temporal_value_unusable")

    def test_a_relative_order_claim_carries_a_relation_not_a_date(self):
        normalized = tc.validate_temporal_claim(
            claim(
                claim_type="relative_order",
                event_kind="move",
                subject_mention="the Dayton house",
                temporal_value={"relation": "after", "anchors": ["the funeral"]},
            )
        )
        self.assertEqual(
            normalized["temporal_value"], {"relation": "after", "anchors": ["the funeral"]}
        )

    def test_relation_arity_is_enforced(self):
        with self.assertRaises(tc.TemporalClaimError) as caught:
            tc.validate_ordering_relation({"relation": "between", "anchors": ["a"]})
        self.assertEqual(caught.exception.code, "relation_anchor_arity")
        self.assertEqual(
            tc.validate_ordering_relation({"relation": "between", "anchors": ["a", "b"]}),
            {"relation": "between", "anchors": ["a", "b"]},
        )

    def test_an_age_is_a_length_not_a_calendar_position(self):
        # Plan §6.4, §10: "I was about 12" is a fuzzy quantity. It becomes an
        # interval only once a birth anchor exists, in the fold — storing a
        # computed birthday here would be the false precision §2.2 forbids.
        normalized = tc.validate_temporal_claim(
            claim(claim_type="age", event_kind="move", temporal_value="about 12")
        )
        value = normalized["temporal_value"]
        self.assertEqual(value["kind"], "age")
        self.assertEqual(value["unit"], "years")
        self.assertTrue(value["approximate"])
        self.assertEqual(value["text"], "about 12")
        self.assertNotIn("best", value)
        self.assertNotIn("earliest", value)

    def test_the_package_owns_the_one_age_parser(self):
        # chronology.parse_age decides what "about" means; this module does not
        # re-decide it.
        low, high, approximate = chrono.parse_age("about 12")
        value = tc.validate_temporal_quantity("about 12", claim_type="age")
        self.assertEqual((value["low"], value["high"]), (float(low), float(high)))
        self.assertEqual(value["approximate"], bool(approximate))

    def test_a_hedged_age_is_not_the_same_claim_as_a_flat_one(self):
        hedged = tc.validate_temporal_claim(
            claim(claim_type="age", event_kind="move", temporal_value="about 12")
        )
        flat = tc.validate_temporal_claim(
            claim(claim_type="age", event_kind="move", temporal_value="12")
        )
        self.assertNotEqual(hedged["claim_id"], flat["claim_id"])

    def test_a_duration_is_supplied_structurally_never_reparsed_here(self):
        normalized = tc.validate_temporal_claim(
            claim(
                claim_type="duration",
                event_kind="job",
                temporal_value={"amount": 3, "unit": "years", "text": "three years"},
            )
        )
        value = normalized["temporal_value"]
        self.assertEqual(
            (value["kind"], value["low"], value["high"], value["unit"]),
            ("duration", 3.0, 3.0, "years"),
        )
        # No free-text duration parser lives here — a second parser is the
        # recurring defect the package's doctrine forbids.
        with self.assertRaises(tc.TemporalClaimError) as caught:
            tc.validate_temporal_claim(
                claim(claim_type="duration", event_kind="job",
                      temporal_value="three years")
            )
        self.assertEqual(caught.exception.code, "duration_value_unusable")

    def test_an_unusable_age_is_a_named_failure(self):
        with self.assertRaises(tc.TemporalClaimError) as caught:
            tc.validate_temporal_claim(
                claim(claim_type="age", event_kind="move", temporal_value="banana")
            )
        self.assertEqual(caught.exception.code, "age_value_unusable")

    def test_a_band_must_be_a_band(self):
        with self.assertRaises(tc.TemporalClaimError) as caught:
            tc.validate_temporal_quantity(
                {"low": 9, "high": 4, "unit": "years"}, claim_type="duration"
            )
        self.assertEqual(caught.exception.code, "duration_value_unusable")
        with self.assertRaises(tc.TemporalClaimError) as caught:
            tc.validate_temporal_quantity(
                {"amount": 3, "unit": "fortnights"}, claim_type="duration"
            )
        self.assertEqual(caught.exception.code, "unknown_quantity_unit")

    def test_the_quantity_round_trips_through_its_dataclass(self):
        quantity = tc.TemporalQuantity(
            kind="duration", low=2.0, high=4.0, unit="months", approximate=True,
            text="a couple of months",
        )
        self.assertEqual(
            tc.validate_temporal_quantity(quantity, claim_type="duration"),
            quantity.to_dict(),
        )

    def test_confidence_is_calibrated_support_in_zero_to_one(self):
        with self.assertRaises(tc.TemporalClaimError) as caught:
            tc.validate_temporal_claim(claim(confidence=4))
        self.assertEqual(caught.exception.code, "confidence_out_of_range")


class DeterministicIdTests(unittest.TestCase):
    """Golden ids. A change here re-mints the vault — it is never incidental."""

    GOLDEN = (
        ("date/birth/Ada/1984", "claim:e3763c08ccb1e0a53d17e84f"),
        ("date/married/Katie/1998-06", "claim:89439937a05d96cb50dc8786"),
        ("date/met/Katie/1994", "claim:ae1e35f7eae5f60c7f779cfa"),
        ("identity/Aunt Della", "claim:37e46c0e41c8833c7a36a4c0"),
        ("relative_order/move", "claim:f7ff48b560a565b5a6ea9fc3"),
    )

    def _golden_inputs(self):
        return {
            "date/birth/Ada/1984": dict(
                claim_type="date", subject_mention="Ada", event_kind="birth",
                temporal_value=tc.normalized_temporal_value("1984", claim_type="date"),
            ),
            "date/married/Katie/1998-06": dict(
                claim_type="date", subject_mention="Katie", event_kind="married",
                temporal_value=tc.normalized_temporal_value("1998-06", claim_type="date"),
            ),
            "date/met/Katie/1994": dict(
                claim_type="date", subject_mention="Katie", event_kind="met",
                temporal_value=tc.normalized_temporal_value("1994", claim_type="date"),
            ),
            "identity/Aunt Della": dict(
                claim_type="identity", subject_mention="Aunt Della", event_kind=None,
                temporal_value=None,
            ),
            "relative_order/move": dict(
                claim_type="relative_order", subject_mention="the Dayton house",
                event_kind="move",
                temporal_value=tc.validate_ordering_relation(
                    {"relation": "after", "anchors": ["the funeral"]}
                ),
            ),
        }

    def test_the_golden_claim_ids_hold(self):
        inputs = self._golden_inputs()
        for label, expected in self.GOLDEN:
            with self.subTest(label=label):
                self.assertEqual(
                    tc.derive_claim_id(
                        source_ref=REF, extractor_version=EXT, **inputs[label]
                    ),
                    expected,
                )

    def test_the_golden_constraint_receipt_and_idempotency_ids_hold(self):
        self.assertEqual(
            tc.derive_constraint_id(
                relation="after",
                subject_node_id="node:college",
                anchor_node_ids=["node:highschool"],
                source_ref=REF,
            ),
            "constraint:e18dc15f5dbb821604989eba",
        )
        self.assertEqual(
            tc.derive_receipt_id(source_ref=REF, extractor_version=EXT),
            "receipt:61741e49f7d5c46af221d5cc",
        )
        self.assertEqual(
            tc.derive_extraction_idempotency_key(
                session_ref="session:abc",
                turn_ref="turn:4",
                source_ref=REF,
                recorder="landmark_recorder",
                extractor_version=EXT,
            ),
            "idem:f4d155a14d1221b4baececc1",
        )

    def test_a_retried_extraction_files_nothing_twice(self):
        first = tc.validate_temporal_claim(claim(created_at="2026-08-26T10:00:00Z"))
        retry = tc.validate_temporal_claim(
            claim(
                created_at="2026-08-26T10:07:41Z",
                confidence=0.55,
                status="disputed",
                evidence=[{"quote": "born in 1984, Ada was"}],
                subject_ref="person/ada",
                event_ref="node:ada-birth",
            )
        )
        self.assertEqual(first["claim_id"], retry["claim_id"])

    def test_a_different_source_revision_is_a_different_claim(self):
        other = dict(REF, revision="sha256:" + "2" * 64)
        self.assertNotEqual(
            tc.validate_temporal_claim(claim())["claim_id"],
            tc.validate_temporal_claim(claim(source_ref=other))["claim_id"],
        )

    def test_a_different_extractor_is_a_different_interpretation(self):
        self.assertNotEqual(
            tc.validate_temporal_claim(claim())["claim_id"],
            tc.validate_temporal_claim(
                claim(extractor_version="listener/schema:2/prompt:c0ffee/model:test-model")
            )["claim_id"],
        )

    def test_a_different_asserted_value_is_a_different_claim(self):
        self.assertNotEqual(
            tc.validate_temporal_claim(claim())["claim_id"],
            tc.validate_temporal_claim(claim(temporal_value="1985"))["claim_id"],
        )

    def test_the_identity_key_list_is_frozen_and_schema_free(self):
        self.assertEqual(
            tc.CLAIM_IDENTITY_KEYS,
            (
                "claim_type",
                "subject_key",
                "event_kind",
                "temporal_identity",
                "source_ref",
                "extractor_version",
            ),
        )
        payload = tc.claim_identity_payload(
            claim_type="date",
            subject_mention="Ada",
            event_kind="birth",
            temporal_value=tc.normalized_temporal_value("1984", claim_type="date"),
            source_ref=REF,
            extractor_version=EXT,
        )
        self.assertEqual(tuple(payload), tc.CLAIM_IDENTITY_KEYS)
        self.assertNotIn("schema_version", payload)

    def test_every_minted_id_is_document_id_safe(self):
        # Firestore document ids must not contain "/" (platform incident
        # 2026-08-22): a minted id that could is a live 500.
        minted = [
            tc.validate_temporal_claim(claim())["claim_id"],
            tc.derive_constraint_id(
                relation="within",
                subject_node_id="node:a",
                anchor_node_ids=["node:b"],
                source_ref=REF,
            ),
            tc.derive_receipt_id(source_ref=REF, extractor_version=EXT),
            tc.derive_extraction_idempotency_key(
                session_ref="chat:person/friend",
                turn_ref="turn:1",
                source_ref=REF,
                recorder="general_listener",
                extractor_version=EXT,
            ),
        ]
        for identifier in minted:
            with self.subTest(identifier=identifier):
                self.assertNotIn("/", identifier)
                self.assertTrue(tc.is_safe_id(identifier))

    def test_a_supplied_id_never_beats_the_derivation(self):
        normalized = tc.validate_temporal_claim(claim(claim_id="claim:deadbeef"))
        self.assertNotEqual(normalized["claim_id"], "claim:deadbeef")

    def test_a_claim_cannot_supersede_itself(self):
        derived = tc.validate_temporal_claim(claim())["claim_id"]
        with self.assertRaises(tc.TemporalClaimError) as caught:
            tc.validate_temporal_claim(claim(supersedes_claim_ids=[derived]))
        self.assertEqual(caught.exception.code, "supersedes_self")


class OrderingConstraintTests(unittest.TestCase):
    """Plan §2.6, §5.2: what a drag writes."""

    def _drag(self, **overrides) -> dict:
        base = {
            "relation": "after",
            "subject_node_id": "node:college",
            "anchor_node_ids": ["node:highschool"],
            "source_ref": dict(REF),
            "evidence": [{"quote": "moved College after High School"}],
            "created_at": NOW,
        }
        base.update(overrides)
        return base

    def test_a_drag_says_only_what_it_saw(self):
        normalized = tc.validate_ordering_constraint(self._drag())
        self.assertEqual(normalized["relation"], "after")
        self.assertEqual(normalized["anchor_node_ids"], ["node:highschool"])
        self.assertNotIn("temporal_value", normalized)
        self.assertNotIn("position", normalized)

    def test_the_same_drag_twice_is_one_constraint(self):
        self.assertEqual(
            tc.validate_ordering_constraint(self._drag())["constraint_id"],
            tc.validate_ordering_constraint(
                self._drag(created_at="2026-08-26T11:11:11Z")
            )["constraint_id"],
        )

    def test_a_node_cannot_be_its_own_anchor(self):
        with self.assertRaises(tc.OrderingConstraintError) as caught:
            tc.validate_ordering_constraint(
                self._drag(anchor_node_ids=["node:college"])
            )
        self.assertEqual(caught.exception.code, "constraint_anchor_is_subject")

    def test_between_needs_two_anchors(self):
        with self.assertRaises(tc.OrderingConstraintError) as caught:
            tc.validate_ordering_constraint(self._drag(relation="between"))
        self.assertEqual(caught.exception.code, "relation_anchor_arity")

    def test_a_constraint_cites_a_correction_source(self):
        with self.assertRaises(tc.SourceRefError):
            tc.validate_ordering_constraint(self._drag(source_ref=None))

    def test_undo_supersedes_rather_than_erases(self):
        normalized = tc.validate_ordering_constraint(
            self._drag(supersedes_constraint_id="constraint:" + "a" * 24, status="active")
        )
        self.assertEqual(
            normalized["supersedes_constraint_id"], "constraint:" + "a" * 24
        )
        self.assertIn("retracted", tc.CLAIM_STATUSES)

    def test_the_round_trip_preserves_every_field(self):
        normalized = tc.validate_ordering_constraint(self._drag())
        obj = tc.constraint_from_dict(normalized)
        self.assertEqual(tc.validate_ordering_constraint(obj.to_dict()), normalized)


class ExtractionReceiptTests(unittest.TestCase):
    """Plan §4.2: the immutable, versioned interpretation record."""

    def _receipt(self, **overrides) -> dict:
        base = {
            "source_ref": dict(REF),
            "extractor_version": EXT,
            "extractor": {
                "name": "listener",
                "schema_version": 1,
                "prompt_version": "c0ffee",
                "model": "test-model",
            },
            "created_at": NOW,
            "recorder": "general_listener",
            "claims": [claim()],
        }
        base.update(overrides)
        return base

    def test_a_receipt_names_the_revision_the_extractor_and_the_time(self):
        normalized = tc.validate_extraction_receipt(self._receipt())
        self.assertEqual(normalized["source_ref"]["revision"], REV)
        self.assertEqual(normalized["extractor_version"], EXT)
        self.assertEqual(normalized["created_at"], NOW)
        self.assertEqual(len(normalized["claims"]), 1)
        self.assertTrue(normalized["claims"][0]["evidence"][0]["quote"])

    def test_a_receipt_cannot_carry_somebody_elses_claim(self):
        other = dict(REF, revision="sha256:" + "9" * 64)
        with self.assertRaises(tc.ExtractionReceiptError) as caught:
            tc.validate_extraction_receipt(
                self._receipt(claims=[claim(source_ref=other)])
            )
        self.assertEqual(caught.exception.code, "receipt_claim_source_mismatch")

    def test_a_receipt_cannot_carry_another_extractors_claim(self):
        with self.assertRaises(tc.ExtractionReceiptError) as caught:
            tc.validate_extraction_receipt(
                self._receipt(claims=[claim(extractor_version="other/rule:1")])
            )
        self.assertEqual(caught.exception.code, "receipt_claim_extractor_mismatch")

    def test_one_claim_cannot_appear_twice_in_one_receipt(self):
        with self.assertRaises(tc.ExtractionReceiptError) as caught:
            tc.validate_extraction_receipt(self._receipt(claims=[claim(), claim()]))
        self.assertEqual(caught.exception.code, "receipt_duplicate_claim_id")

    def test_the_extractor_version_can_be_derived_from_its_parts(self):
        normalized = tc.validate_extraction_receipt(
            self._receipt(extractor_version=None, claims=[])
        )
        self.assertEqual(normalized["extractor_version"], EXT)

    def test_re_extraction_writes_a_new_receipt_beside_the_old_one(self):
        # Plan §1.3: a later model reading the same prose is a NEW
        # interpretation, not a cache rebuild — so it lands on a new path.
        first = tc.receipt_relative_path(REF, EXT)
        second = tc.receipt_relative_path(
            REF, "listener/schema:1/prompt:c0ffee/model:next-model"
        )
        self.assertNotEqual(first, second)
        self.assertTrue(first.startswith(tc.RECEIPTS_DIR + "/"))
        self.assertTrue(first.endswith(".json"))
        self.assertIn("1" * 64, first)

    def test_the_same_source_and_extractor_land_on_one_path(self):
        self.assertEqual(
            tc.receipt_relative_path(REF, EXT), tc.receipt_relative_path(dict(REF), EXT)
        )

    def test_a_source_key_is_bounded_and_filename_safe(self):
        key = tc.bounded_source_key("sources/manual/" + "long-" * 60 + "name.md")
        self.assertLessEqual(len(key), tc.MAX_SOURCE_KEY_CHARS)
        self.assertTrue(re.fullmatch(r"[a-z0-9-]+", key))

    def test_two_long_source_ids_never_share_a_key(self):
        a = tc.bounded_source_key("sources/manual/" + "x" * 200 + "-a.md")
        b = tc.bounded_source_key("sources/manual/" + "x" * 200 + "-b.md")
        self.assertNotEqual(a, b)

    def test_the_round_trip_is_lossless(self):
        normalized = tc.validate_extraction_receipt(self._receipt())
        obj = tc.receipt_from_dict(normalized)
        self.assertEqual(tc.validate_extraction_receipt(obj.to_dict()), normalized)
        self.assertEqual(obj.relative_path, tc.receipt_relative_path(REF, EXT))

    def test_the_extractor_version_string_is_one_spelling(self):
        self.assertEqual(
            tc.extractor_version_string(
                "listener", schema_version=1, prompt_version="c0ffee", model="test-model"
            ),
            EXT,
        )
        self.assertEqual(
            tc.extractor_version_string("prescreen", rule_version=3), "prescreen/rule:3"
        )
        with self.assertRaises(tc.ExtractionReceiptError):
            tc.extractor_version_string("")


class CompatibilityTests(unittest.TestCase):
    """The rule stated in the module docstring, tested as a rule."""

    def test_readers_are_tolerant_and_never_raise(self):
        for reader in (
            tc.claim_from_dict,
            tc.constraint_from_dict,
            tc.receipt_from_dict,
            tc.evidence_from_dict,
            tc.ordering_relation_from_dict,
            tc.source_ref_from_dict,
        ):
            with self.subTest(reader=reader.__name__):
                self.assertIsNone(reader(None))
                self.assertIsNone(reader({"nonsense": True}))
                self.assertIsNone(reader(17))

    def test_an_unknown_key_from_a_later_version_is_ignored_not_fatal(self):
        normalized = tc.validate_temporal_claim(
            claim(**{"a_field_added_in_v3": {"anything": [1, 2]}})
        )
        self.assertNotIn("a_field_added_in_v3", normalized)
        self.assertEqual(normalized["schema_version"], tc.SCHEMA_VERSION)

    def test_every_record_states_the_version_it_was_written_under(self):
        self.assertEqual(tc.SCHEMA_VERSION, 1)
        self.assertEqual(
            tc.validate_temporal_claim(claim())["schema_version"], tc.SCHEMA_VERSION
        )
        self.assertEqual(
            tc.validate_ordering_constraint(
                {
                    "relation": "before",
                    "subject_node_id": "node:a",
                    "anchor_node_ids": ["node:b"],
                    "source_ref": dict(REF),
                }
            )["schema_version"],
            tc.SCHEMA_VERSION,
        )

    def test_the_claim_round_trip_is_lossless(self):
        normalized = tc.validate_temporal_claim(
            claim(subject_ref="person/ada", event_ref="node:ada-birth")
        )
        obj = tc.claim_from_dict(normalized)
        self.assertEqual(tc.validate_temporal_claim(obj.to_dict()), normalized)

    def test_timestamps_normalize_to_one_spelling(self):
        for supplied in (
            "2026-08-26T10:00:00Z",
            "2026-08-26T10:00:00.500000Z",
            "2026-08-26T12:00:00+0200",
        ):
            with self.subTest(supplied=supplied):
                self.assertEqual(
                    tc.normalized_timestamp(supplied, error=tc.TemporalClaimError), NOW
                )
        with self.assertRaises(tc.TemporalClaimError) as caught:
            tc.normalized_timestamp("last tuesday", error=tc.TemporalClaimError)
        self.assertEqual(caught.exception.code, "timestamp_unusable")

    def test_every_raised_finding_id_is_declared(self):
        # AST-derived, not grep-derived: a finding id that is not in
        # ERROR_CODES cannot be counted in observability (plan §12) or retried
        # by class, and a stale ERROR_CODES entry is a lie about the surface.
        raised = raised_finding_codes(ROOT / "system" / "temporal_claims.py")
        self.assertTrue(raised)
        self.assertEqual(
            raised - set(tc.ERROR_CODES),
            set(),
            "an undeclared finding id cannot be counted or retried by class",
        )

    def test_no_declared_finding_id_is_dead(self):
        raised = raised_finding_codes(ROOT / "system" / "temporal_claims.py")
        self.assertEqual(set(tc.ERROR_CODES) - raised, set())

    def test_the_public_surface_is_exported(self):
        for name in (
            "TemporalClaim",
            "OrderingConstraint",
            "ExtractionReceipt",
            "SourceRef",
            "derive_claim_id",
            "derive_extraction_idempotency_key",
            "validate_temporal_claim",
            "split_subject_enumeration",
        ):
            with self.subTest(name=name):
                self.assertIn(name, tc.__all__)
                self.assertTrue(hasattr(tc, name))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
