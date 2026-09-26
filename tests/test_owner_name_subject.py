"""timeline-rules:8 — a roster entity bearing the owner's own name is the owner.

Synthetic data only; NEVER references any real vault.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "system"))

import identity_resolution as ident  # noqa: E402
import temporal_claims as tc  # noqa: E402
import temporal_projection as tp  # noqa: E402
import temporal_timeline as tt  # noqa: E402

NOW = "2026-09-01T12:00:00Z"
ROSTER = {"type": "person", "entities": [
    {"name": "Pat", "slug": "pat", "aliases": ["Pat Q. Example"]},
    {"name": "Robin", "slug": "robin", "aliases": []},
]}


def claim(mention: str, label: str, seed: str) -> dict:
    return tc.validate_temporal_claim({
        "source_kind": "conversation",
        "source_ref": {"source_id": f"conversation:{seed}", "revision": "sha256:" + "a" * 64},
        "evidence": [{"quote": f"{label}."}],
        "extractor_version": "classifier:1",
        "basis": "explicit", "confidence": 0.9, "status": "active",
        "claim_type": "date", "subject_mention": mention, "event_mention": label,
        "event_kind": "moment",
        "temporal_value": {"best": "2004", "earliest": "2004", "latest": "2004",
                           "granularity": "year", "basis": "stated", "confidence": "certain"},
        "event_ref": tp.derive_node_id(node_kind="event", event_kind="moment",
                                       subject_refs=[mention], discriminator=seed),
    }, now=NOW)


class OwnerNameSubjectTests(unittest.TestCase):
    def fold(self, **kwargs):
        index = {"claims": [claim("Pat", "Pat's promotion", "s1"),
                            claim("Robin", "Robin's promotion", "s2")]}
        return tt.derive_calculated_timeline(index, roster_snapshot=ROSTER, now=NOW, **kwargs)

    def scopes(self, result) -> dict:
        return {row["label"]: row["occurrence_subject_scope"] for row in result.nodes}

    def test_without_owner_names_the_roster_makes_the_owner_a_stranger(self):
        self.assertEqual(self.scopes(self.fold())["Pat's promotion"], "other_person")

    def test_the_owners_own_name_resolves_to_the_owner(self):
        scopes = self.scopes(self.fold(owner_names=("Pat", "Pat Q. Example")))
        self.assertEqual(scopes["Pat's promotion"], "owner")
        self.assertEqual(scopes["Robin's promotion"], "other_person")

    def test_a_spelling_of_his_own_name_the_roster_lacks_is_still_him(self):
        """`timeline-rules:9` re-reads a mention the roster cannot place. It
        must not re-read THIS one: a name is not third-party evidence, and a
        capitalisation heuristic would have made every spelling of the owner's
        own name somebody else. Only relation words move a subject."""
        index = {"claims": [claim("Patrick Q. Example", "the promotion", "s3")]}
        result = tt.derive_calculated_timeline(index, roster_snapshot=ROSTER, now=NOW)
        # v360 (owner, 2026-09-25): a title is sentence-cased now.
        row = next(r for r in result.nodes if r["label"] == "The promotion")
        self.assertEqual(row["occurrence_subject_scope"], "owner")
        self.assertEqual(row["owner_timeline_relation"], "participated")

    def test_the_rule_is_a_reversible_resolution_record(self):
        refs = ident.owner_name_refs(ROSTER, ("Pat Q. Example",))
        self.assertEqual(refs, frozenset({"person/pat"}))
        record = ident.owner_name_resolution("Pat", owner_ref="self", evidence_ref="claim:x", now=NOW)
        self.assertEqual(record.reason, ident.OWNER_NAME_REASON)
        self.assertEqual(record.resolved_ref, "self")


if __name__ == "__main__":
    unittest.main()
