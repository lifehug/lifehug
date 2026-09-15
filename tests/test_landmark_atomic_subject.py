"""Issue #328: typed landmark names, not a global enumeration exemption.

All data is invented and all filing uses disposable synthetic vaults.
"""

from __future__ import annotations

import copy
import json
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "system"))
sys.path.insert(0, str(ROOT / "tests"))

import general_listener as gl
import landmark_offer as lo
import landmark_projection as lp
import landmarks_interaction as li
import temporal_claims as tc
import temporal_store as ts
import timeline
from test_landmark_offer import (
    NOW, OfferVaultCase, ScriptedCall, _span, read_dates, read_unit, reading,
)

SOURCE = {"source_id": "landmark:entry-" + "ab" * 12,
          "revision": "sha256:" + "cd" * 32}


def entry(domain="residences", label="Harbor City, ST"):
    return {"domain": domain, "label": label, "span": _span("1990", "1992")}


def claims(domain="residences", label="Harbor City, ST", **kwargs):
    return lp.entry_claims(domain, entry(domain, label), source_ref=SOURCE,
                           now=NOW, **kwargs)


class AtomicSubjectContractTests(unittest.TestCase):
    def test_validation_and_readback_remain_pure(self):
        row = claims()[0]
        with mock.patch.object(Path, "read_text", side_effect=AssertionError("unexpected I/O")):
            self.assertEqual(tc.validate_temporal_claim(row), row)
            self.assertIsNotNone(tc.claim_from_dict(row))

    def test_places_and_organizations_preserve_mentions_through_claim_roundtrip(self):
        for domain, label in (("residences", "Harbor City, ST"),
                              ("residences", "Rock & River"),
                              ("work", "Pell & Sons"),
                              ("work", "Harbor Company, Inc."),
                              ("schools", "Arts and Sciences Academy")):
            for version in (lp.LEGACY_EXTRACTOR, lp.LIVE_EXTRACTOR):
                with self.subTest(domain=domain, label=label, version=version):
                    rows = claims(domain, label, extractor_version=version)
                    self.assertEqual(len(rows), 3)
                    for row in rows:
                        self.assertEqual(row["landmark_identity_kind"],
                                         li.domain_row(domain)["identity_kind"])
                        self.assertEqual(row["subject_mention"], label)
                        self.assertEqual(tc.validate_temporal_claim(row), row)
                        decoded = tc.claim_from_dict(row)
                        self.assertIsNotNone(decoded)
                        self.assertEqual(decoded.landmark_identity_kind,
                                         row["landmark_identity_kind"])
                        self.assertEqual(tc.validate_temporal_claim(decoded), row)
                        self.assertEqual(tc.claim_from_dict(decoded.to_dict()).to_dict(),
                                         decoded.to_dict())

    def test_domain_authority_and_extractors_are_not_duplicate_allowlists(self):
        self.assertEqual(lp.LEGACY_EXTRACTOR, tc.LANDMARK_LEGACY_EXTRACTOR)
        self.assertEqual(lp.LIVE_EXTRACTOR, tc.LANDMARK_RECORD_EXTRACTOR)
        for row in li.load_questions():
            with self.subTest(domain=row["domain"]):
                if row.get("identity_kind") in tc.ATOMIC_LANDMARK_IDENTITY_KINDS:
                    self.assertEqual(claims(row["domain"])[0]["landmark_identity_kind"],
                                     row["identity_kind"])
                elif row["domain"] != "birth":
                    with self.assertRaises(tc.TemporalClaimError) as caught:
                        claims(row["domain"], "Ada and Bo")
                    self.assertEqual(caught.exception.code, "aggregate_subject_mention")
        # A future question-set change must affect both producer and validator.
        rows = [dict(row, identity_kind="person") if row["domain"] == "residences"
                else row for row in li.load_questions()]
        with mock.patch.object(li, "load_questions", return_value=tuple(rows)):
            with self.assertRaises(tc.TemporalClaimError):
                claims()

    def test_untyped_mentions_and_free_refs_never_bypass_people_guard(self):
        base = claims(label="Harbor City")[0]
        for additions in ({}, {"subject_ref": "place/harbor-city"},
                          {"subject_ref": "person/ada"},
                          {"subject_ref": "organization/pell-and-sons",
                           "subject_resolution": {
                               "candidates": ["organization/pell-and-sons"],
                               "reason": "unique_name", "confidence": 1.0}}):
            with self.subTest(additions=additions):
                with self.assertRaises(tc.TemporalClaimError) as caught:
                    tc.validate_temporal_claim(dict(base, subject_mention="Ada, Bo and Cy",
                                                    **additions))
                self.assertEqual(caught.exception.code, "aggregate_subject_mention")
                self.assertEqual(caught.exception.detail, ("Ada", "Bo", "Cy"))

    def test_foreign_provenance_and_invalid_kinds_are_typed_refusals(self):
        base = claims()[0]
        bad = ({"source_kind": "conversation"},
               {"source_ref": {**SOURCE, "source_id": "message:test"}},
               {"extractor_version": "listener/rule:1"},
               {"extractor_version": "landmark-record/rule:2"},
               {"landmark_identity_kind": "person"},
               {"landmark_identity_kind": "relationship_edge"},
               {"landmark_identity_kind": "episode"},
               {"landmark_identity_kind": "invented"}, {"landmark_identity_kind": ""},
               {"landmark_identity_kind": ["place"]})
        for patch in bad:
            with self.subTest(patch=patch):
                malformed = dict(base, **patch)
                with self.assertRaises(tc.TemporalClaimError) as caught:
                    tc.validate_temporal_claim(malformed)
                self.assertEqual(caught.exception.code, "invalid_landmark_identity_kind")
                self.assertIsNone(tc.claim_from_dict(malformed))

    def test_record_and_listener_cannot_inject_kind_annotation(self):
        with self.assertRaises(tc.TemporalClaimError) as caught:
            lp.entry_claims("children", {**entry("children", "Ada and Bo"),
                                         "landmark_identity_kind": "place"},
                            source_ref=SOURCE, now=NOW)
        self.assertEqual(caught.exception.code, "aggregate_subject_mention")
        draft, finding = gl.validate_claim_draft({
            "claim_type": "identity", "subject_mention": "Ada and Bo",
            "evidence": [{"quote": "Ada and Bo"}], "landmark_identity_kind": "place",
        })
        self.assertIsNone(draft)
        self.assertEqual(finding, gl.claim_refused(gl.CLAIM_UNKNOWN_KEY))
        with self.assertRaises(tc.TemporalClaimError):
            claims("invented", "Ada and Bo")

    def test_annotation_never_excuses_missing_evidence_or_invalid_dates(self):
        base = claims()[0]
        for patch, code in (({"evidence": []}, "evidence_required"),
                            ({"subject_mention": ""}, "subject_mention_required"),
                            ({"claim_type": "date", "event_kind": "started",
                              "temporal_value": None}, "temporal_claim_needs_value")):
            with self.subTest(code=code):
                with self.assertRaises(tc.TemporalClaimError) as caught:
                    tc.validate_temporal_claim(dict(base, **patch))
                self.assertEqual(caught.exception.code, code)

    def test_annotation_does_not_change_ids_or_ordinary_claim_bytes(self):
        for row in claims(label="Harbor City"):
            self.assertNotIn("landmark_identity_kind", row)
            annotated = tc.validate_temporal_claim(dict(row, landmark_identity_kind="place"))
            self.assertEqual(annotated.pop("landmark_identity_kind"), "place")
            self.assertEqual(annotated, row)
            self.assertNotIn("landmark_identity_kind", tc.claim_from_dict(row).to_dict())


class AtomicSubjectFilingTests(OfferVaultCase):
    def test_filed_names_survive_receipts_active_set_and_projection(self):
        for ordinal, (domain, label) in enumerate((("residences", "Harbor City, ST"),
                                                  ("work", "Pell & Sons"))):
            result = lp.file_landmark_record(self.root, domain, entry(domain, label),
                                             ordinal=ordinal, now=NOW)
            receipt = ts.read_receipt(self.root, result["receipt_path"])
            self.assertIsNotNone(receipt)
            self.assertEqual({c.subject_mention for c in receipt.claims}, {label})
            self.assertEqual({c.landmark_identity_kind for c in receipt.claims},
                             {li.domain_row(domain)["identity_kind"]})
            original = (self.root / result["receipt_path"]).read_bytes()
            replay = lp.file_landmark_record(self.root, domain, entry(domain, label),
                                             ordinal=ordinal, now="2026-09-16T00:00:00Z")
            self.assertEqual(replay["receipt_path"], result["receipt_path"])
            self.assertEqual((self.root / replay["receipt_path"]).read_bytes(), original)
            decoded = tc.receipt_from_dict(json.loads(original))
            self.assertIsNotNone(decoded)
            self.assertEqual(tc.validate_extraction_receipt(decoded),
                             tc.validate_extraction_receipt(json.loads(original)))
        active = ts.active_claims(ts.rebuild_active_index(self.root))
        self.assertEqual(len(active), 6)
        self.assertEqual({row["landmark_identity_kind"] for row in active},
                         {"place", "organization"})
        timeline.redraw_landmarks()
        self.assertEqual(self.entries("residences")[0]["label"], "Harbor City, ST")
        self.assertEqual(self.entries("work")[0]["label"], "Pell & Sons")

    def test_ordinary_historic_receipt_is_unchanged_on_refile(self):
        record = entry(label="Harbor City")
        first = lp.file_landmark_record(self.root, "residences", record, ordinal=0, now=NOW)
        path = self.root / first["receipt_path"]
        original = path.read_bytes()
        self.assertNotIn(b"landmark_identity_kind", original)
        again = lp.file_landmark_record(self.root, "residences", record, ordinal=0,
                                        now="2026-09-16T00:00:00Z")
        self.assertEqual(first["receipt_path"], again["receipt_path"])
        self.assertEqual(path.read_bytes(), original)
        altered = json.loads(original)
        altered["claims"][0]["subject_mention"] = "Different City"
        with self.assertRaises(ts.TemporalStoreError) as caught:
            ts.write_receipt(self.root, altered)
        self.assertEqual(caught.exception.code, "receipt_immutable_conflict")

    def test_grouped_mixed_offer_files_punctuation_and_reapply_is_idempotent(self):
        units, events, sentences = [], [], []
        for i in range(76):
            domain = "residences" if i < 30 else "schools" if i < 51 else "work"
            label = (f"Harbor{i:02d} City, ST" if i < 30 else
                     f"Arts and Sciences Academy{i:02d}" if i < 51 else
                     f"Workshop{i:02d} & Sons")
            quote = f"I was at {label} from 1990 to 1992."
            sentences.append(quote)
            field = "city" if domain == "residences" else "name" if domain == "schools" else "what"
            units.append(read_unit(f"u{i}", domain, label, quote,
                                   record={field: label, "label": label},
                                   dates=read_dates("1990", "1992"),
                                   within=None if i < 30 else "u0"))
        for i in range(30):
            quote = f"Person{i:02d} was born in 1991."
            sentences.append(quote)
            events.append({"ref": f"e{i}", "kind": "child_born",
                           "text": f"Person{i:02d} was born",
                           "subject_mention": f"Person{i:02d}", "date": "1991",
                           "quote": quote, "within": f"u{i}"})
        proposal = self.propose("\n".join(sentences), ScriptedCall(
            reading=reading(units=units, events=events)))
        self.assertEqual(len(proposal["units"]), 76)
        self.assertEqual(len(proposal["groups"]), 30)
        self.assertEqual(len(proposal["events"]), 30)
        original_proposal = copy.deepcopy(proposal)
        ids = [row["unit_id"] for row in proposal["units"]]
        first = lo.apply(proposal["proposal_id"], ids, self.root, now=NOW)
        self.assertEqual(first["counts"]["units"], 76)
        self.assertEqual(first["counts"]["claims"], 30)
        before = {p.relative_to(self.root): p.read_bytes() for p in self.root.rglob("*")
                  if p.is_file()}
        second = lo.apply(proposal["proposal_id"], ids, self.root,
                          now="2026-09-16T00:00:00Z")
        self.assertEqual(first, second)
        after = {p.relative_to(self.root): p.read_bytes()
                 for p in self.root.rglob("*") if p.is_file()}
        self.assertEqual(set(before), set(after))
        for path, original in before.items():
            with self.subTest(path=str(path)):
                if path == Path("state/entity_rosters/place.json"):
                    # Existing resolve_place_ref always persists the roster;
                    # write_roster refreshes only this metadata on a retry.
                    old_roster, new_roster = json.loads(original), json.loads(after[path])
                    old_roster.pop("resolved_at")
                    new_roster.pop("resolved_at")
                    self.assertEqual(old_roster, new_roster)
                else:
                    self.assertEqual(original, after[path])
        self.assertEqual(proposal, original_proposal)
        self.assertEqual(sum(len(self.entries(d)) for d in ("residences", "schools", "work")), 76)
        active = ts.active_claims(ts.rebuild_active_index(self.root))
        self.assertTrue(any(c.get("landmark_identity_kind") == "organization" for c in active))
        self.assertTrue(any(c["subject_mention"] == "Harbor00 City, ST" for c in active))


if __name__ == "__main__":
    unittest.main()
