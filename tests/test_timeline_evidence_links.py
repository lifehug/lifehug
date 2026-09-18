"""Focused synthetic contract tests for incremental timeline evidence links."""

from __future__ import annotations

import copy
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "system"))

import timeline_evidence as te  # noqa: E402
import classifier_claims as classifier_claims  # noqa: E402


def candidate(
    candidate_id: str,
    name: str,
    *,
    entity_refs: list[str],
    role: str = "residence",
    bounds: str = "2001/2003",
) -> dict:
    return {
        "candidate_id": candidate_id,
        "episode_id": candidate_id.replace("node:", "episode:"),
        "node_kind": "episode",
        "kind": role,
        "event_role": role,
        "name": name,
        "aliases": [],
        "canonical_roster_terms": [],
        "entity_refs": entity_refs,
        "unresolved_entity_mentions": [],
        "entity_ref_ambiguities": [],
        "supported_bounds": {
            "best": bounds,
            "earliest": bounds.split("/")[0],
            "latest": bounds.split("/")[-1],
            "granularity": "range",
        },
        "basis": "explicit",
        "conflict_state": "none",
        "alternatives": [],
        "grounding_identity": [{"source_revision": "sha256:" + "a" * 64}],
    }


class GroundingSubjectTests(unittest.TestCase):
    def test_owner_proof_does_not_accept_relative_or_substring(self) -> None:
        story = "My mother was 21 when she married."
        event = {
            "title": "Mother married",
            "description": story,
            "subject": "self",
            "date": {"age": "21"},
        }
        with self.assertRaisesRegex(te.TimelineEvidenceError, "subject evidence"):
            te.normalize_source_grounding(
                {
                    "quote": story,
                    "temporal_quote": "21",
                    "subject_quote": "My mother",
                    "kind": "age",
                },
                event,
                story_text=story,
                source_revision="sha256:" + "1" * 64,
            )

        other = {**event, "subject": "Ann"}
        other_story = "Joann was 21 when she married."
        with self.assertRaisesRegex(te.TimelineEvidenceError, "subject evidence"):
            te.normalize_source_grounding(
                {
                    "quote": other_story,
                    "temporal_quote": "21",
                    "subject_quote": "Joann",
                    "kind": "age",
                },
                other,
                story_text=other_story,
                source_revision="sha256:" + "2" * 64,
            )

    def test_exact_canonical_tail_and_declared_alias_are_supported(self) -> None:
        for proof, aliases in (("Mira", []), ("Mimi", ["Mimi"])):
            story = f"{proof} was 21 when she married."
            normalized = te.normalize_source_grounding(
                {
                    "quote": story,
                    "temporal_quote": "21",
                    "subject_quote": proof,
                    "kind": "age",
                },
                {
                    "subject": "person/mira",
                    "subject_aliases": aliases,
                    "date": {"age": "21"},
                },
                story_text=story,
                source_revision="sha256:" + "3" * 64,
            )
            self.assertEqual(normalized["subject_quote"], proof)


class NaturalRangeGroundingTests(unittest.TestCase):
    STORY = "River House was our home from January 2012 through December 2015."
    REVISION = "sha256:" + "8" * 64

    def grounding(self, **overrides) -> dict:
        payload = {
            "quote": self.STORY,
            "temporal_quote": "January 2012 through December 2015",
            "subject_quote": "River House",
            "kind": "date",
        }
        payload.update(overrides)
        return payload

    def event(self, stated: str = "2012-01/2015-12") -> dict:
        return {
            "title": "River House years",
            "description": self.STORY,
            "subject": "River House",
            "date": {"stated": stated, "age": None, "anchor_ref": None},
        }

    def test_exact_natural_range_proves_equivalent_normalized_bounds(self) -> None:
        normalized = te.normalize_source_grounding(
            self.grounding(),
            self.event(),
            story_text=self.STORY,
            source_revision=self.REVISION,
        )
        self.assertEqual(normalized["quote"], self.STORY)
        self.assertEqual(normalized["temporal_quote"],
                         "January 2012 through December 2015")
        self.assertEqual(normalized["subject_quote"], "River House")
        self.assertEqual(
            normalized["normalized_temporal_value"],
            {
                "best": "2012-01/2015-12",
                "earliest": "2012-01",
                "latest": "2015-12",
                "granularity": "range",
                "confidence": "certain",
                "basis": "stated",
                "anchors": [],
                "provenance": [],
            },
        )

    def test_wrong_normalized_bounds_are_still_refused(self) -> None:
        with self.assertRaisesRegex(te.TimelineEvidenceError, "does not support"):
            te.normalize_source_grounding(
                self.grounding(),
                self.event("2012-02/2015-12"),
                story_text=self.STORY,
                source_revision=self.REVISION,
            )

    def test_temporal_words_must_remain_inside_the_exact_quote(self) -> None:
        with self.assertRaisesRegex(te.TimelineEvidenceError, "inside quote"):
            te.normalize_source_grounding(
                self.grounding(quote="River House was our home"),
                self.event(),
                story_text=self.STORY,
                source_revision=self.REVISION,
            )

    def test_invalid_and_reversed_natural_ranges_are_refused(self) -> None:
        for temporal_quote in (
            "January 2012 through December",
            "December 2015 through January 2012",
        ):
            story = f"River House was our home {temporal_quote}."
            with self.subTest(temporal_quote=temporal_quote):
                with self.assertRaisesRegex(te.TimelineEvidenceError, "does not support"):
                    te.normalize_source_grounding(
                        self.grounding(quote=story, temporal_quote=temporal_quote),
                        self.event(),
                        story_text=story,
                        source_revision=self.REVISION,
                    )


class SelectiveRetrievalTests(unittest.TestCase):
    def test_narrow_reference_stays_complete_beyond_64_owner_facts(self) -> None:
        rows = [
            candidate(
                f"node:owner-{index:03d}",
                f"Owner moment {index}",
                entity_refs=["self"],
                role="moment",
            )
            for index in range(80)
        ]
        rows.append(candidate(
            "node:river-house",
            "River House residence",
            entity_refs=["self", "place/river-house"],
        ))
        context = te.build_event_context(
            {
                "title": "River House",
                "description": "We found the letter at River House.",
                "subject": "self",
                "date": None,
            },
            rows,
        )
        self.assertTrue(context["complete"])
        self.assertEqual(context["candidate_ids"], ["node:river-house"])
        self.assertEqual(context["remaining_candidate_count"], 0)

    def test_exact_alias_outranks_shared_domain_words_beyond_cap(self) -> None:
        rows = []
        for index in range(600):
            row = candidate(
                f"node:home-{index:03d}",
                f"Home number {index}",
                entity_refs=[f"place/home-{index}"],
            )
            row["aliases"] = [f"Residence {index}"]
            rows.append(row)

        context = te.build_event_context(
            {
                "title": "Residence 499",
                "description": "I found the photograph at Residence 499.",
                "subject": "self",
                "places": ["Residence 499"],
                "date": None,
            },
            rows,
        )

        self.assertTrue(context["complete"])
        self.assertEqual(context["candidate_ids"], ["node:home-499"])
        self.assertEqual(context["remaining_candidate_count"], 0)

    def test_whole_alias_normalizes_punctuation_and_rejects_numeric_prefix(self) -> None:
        forty_nine = candidate(
            "node:home-049",
            "Home 49",
            entity_refs=["place/home-49"],
        )
        forty_nine["aliases"] = ["St. John's Residence #49"]
        four_ninety_nine = candidate(
            "node:home-499",
            "Home 499",
            entity_refs=["place/home-499"],
        )
        four_ninety_nine["aliases"] = ["St. John's Residence #499"]

        context = te.build_event_context(
            {
                "title": "St. John's Residence #499",
                "description": "The photograph was at St. John's Residence #499.",
                "subject": "self",
                "places": ["St. John's Residence #499"],
                "date": None,
            },
            [forty_nine, four_ninety_nine],
        )

        self.assertEqual(context["candidate_ids"], ["node:home-499"])

    def test_exact_alias_retains_every_same_entity_competitor(self) -> None:
        first = candidate(
            "node:river-first",
            "River House first stay",
            entity_refs=["place/river-house"],
        )
        second = candidate(
            "node:river-second",
            "River House second stay",
            entity_refs=["place/river-house"],
        )
        second["aliases"] = ["River House return"]

        context = te.build_event_context(
            {
                "title": "River House return",
                "description": "During the River House return, I found a letter.",
                "subject": "self",
                "places": ["River House"],
                "date": None,
            },
            [first, second],
        )

        self.assertTrue(context["complete"])
        self.assertEqual(
            context["candidate_ids"],
            ["node:river-first", "node:river-second"],
        )

    def test_first_link_publish_has_the_same_semantic_fingerprint(self) -> None:
        row = candidate(
            "node:river-house",
            "River House residence",
            entity_refs=["place/river-house", "self"],
        )
        event = {
            "title": "River House letter",
            "description": "I found the letter at River House.",
            "subject": "self",
            "date": None,
        }
        before = te.build_event_context(copy.deepcopy(event), [copy.deepcopy(row)])
        linked = copy.deepcopy(event)
        linked["timeline_relation"] = {
            "relation": "within",
            "candidate_id": "node:river-house",
            "entity_refs": ["place/river-house"],
            "evidence": {"quote": "at River House"},
        }
        changed_bounds = copy.deepcopy(row)
        changed_bounds["supported_bounds"] = {
            "best": "2002/2004",
            "earliest": "2002",
            "latest": "2004",
            "granularity": "range",
        }
        after = te.build_event_context(linked, [changed_bounds])
        self.assertEqual(after["input_fingerprint"], before["input_fingerprint"])


class ClaimEmissionTests(unittest.TestCase):
    def grounded_event(self) -> dict:
        return {
            "title": "Joined Northstar",
            "description": "I joined Northstar in 2018.",
            "subject": "self",
            "date": {"stated": "2018", "age": None, "anchor_ref": None},
            "source_grounding": {
                "quote": "I joined Northstar in 2018.",
                "temporal_quote": "2018",
                "subject_quote": "I",
                "kind": "date",
                "start": 0,
                "end": 27,
                "source_revision": "sha256:" + "4" * 64,
                "normalized_temporal_value": {
                    "best": "2018", "earliest": "2018", "latest": "2018",
                    "granularity": "year",
                },
            },
        }

    def claims(self, event: dict, revision: str) -> list[dict]:
        return classifier_claims.event_claims(
            stem="northstar",
            event=event,
            revision=revision,
            source_path="sources/manual/northstar.md",
            now="2026-09-17T12:00:00Z",
        )

    def test_event_key_has_one_authority(self) -> None:
        event = self.grounded_event()
        self.assertEqual(classifier_claims.event_key(event), te.event_key(event))

    def test_event_key_preserves_the_v306_unicode_identity(self) -> None:
        event = {
            "title": "Mira’s wedding",
            "description": "We met in Bogotá.",
        }
        self.assertEqual(te.event_key(event), "363cccb54258")
        self.assertEqual(classifier_claims.event_key(event), "363cccb54258")

    def test_unchanged_grounded_direct_assertion_survives_link_refresh(self) -> None:
        event = self.grounded_event()
        event["timeline_resolution"] = {
            "status": "linked",
            "source_revision": "sha256:" + "4" * 64,
            "input_fingerprint": "sha256:" + "0" * 64,
        }
        before = self.claims(event, "sha256:" + "a" * 64)[0]
        linked = copy.deepcopy(event)
        linked["timeline_relation"] = {
            "relation": "within",
            "candidate_id": "node:northstar-job",
            "entity_refs": ["org/northstar"],
            "evidence": {"quote": "joined Northstar", "start": 2, "end": 18},
        }
        linked["timeline_resolution"] = {
            "status": "linked",
            "source_revision": "sha256:" + "4" * 64,
            "input_fingerprint": "sha256:" + "5" * 64,
        }
        after = self.claims(linked, "sha256:" + "b" * 64)
        direct = next(row for row in after if row["claim_type"] == "date")
        self.assertEqual(direct["claim_id"], before["claim_id"])
        self.assertEqual(direct["source_ref"], before["source_ref"])
        self.assertEqual(direct, before)
        self.assertEqual(direct["evidence"], [{
            "quote": "I joined Northstar in 2018.", "start": 0, "end": 27,
        }])

    def test_equivalent_raw_anchor_is_replaced_but_distinct_order_is_kept(self) -> None:
        event = {
            "title": "Moved",
            "description": "We moved after Mira's wedding.",
            "subject": "self",
            "date": {
                "stated": None,
                "age": None,
                "anchor_ref": "Mira's wedding",
                "relation": "after",
            },
            "timeline_relation": {
                "relation": "after",
                "candidate_id": "node:mira-wedding",
                "entity_refs": ["person/mira"],
                "evidence": {
                    "quote": "after Mira's wedding", "start": 9, "end": 29,
                },
            },
            "timeline_resolution": {
                "status": "linked",
                "source_revision": "sha256:" + "6" * 64,
                "input_fingerprint": "sha256:" + "7" * 64,
            },
        }
        canonical = self.claims(event, "sha256:" + "c" * 64)
        self.assertEqual(len(canonical), 1)
        self.assertEqual(
            canonical[0]["temporal_value"]["anchors"], ["node:mira-wedding"]
        )

        distinct = copy.deepcopy(event)
        distinct["timeline_relation"]["relation"] = "before"
        readings = self.claims(distinct, "sha256:" + "d" * 64)
        self.assertEqual(len(readings), 2)
        self.assertEqual(
            {row["temporal_value"]["relation"] for row in readings},
            {"before", "after"},
        )


if __name__ == "__main__":
    unittest.main()
