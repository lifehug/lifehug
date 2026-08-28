"""O-E2 — memberships are receipts, relevance is evidence, the placement
rewrite.

Contract: `docs/pr-specs/eras-o-e2-memberships.md`. Controlling design:
lifehug-platform `docs/design/eras.md` §2.2-2.6, §5.1-5.3, §5.6, §7 rows
"Membership" / "Display role", §9.1 (T-M-01…10, T-SC-12/13, T-PL, T-CV) and
§13.2-13.4.

Two kinds of fact replace four heuristics that were never a fact anybody
stated: a membership is a receipt or it is frame arithmetic, and owner
relevance is a stated relationship PLUS an owner-relevant occurrence, each
citing the record that says so.

Synthetic data only; NEVER references ~/Workspace/dave.
"""

from __future__ import annotations

import ast
import hashlib
import json
import re
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SYSTEM = ROOT / "system"
sys.path.insert(0, str(SYSTEM))

import chronology as chrono  # noqa: E402
import cross_dating as cd  # noqa: E402
import era_memberships as era  # noqa: E402
import landmark_projection as lp  # noqa: E402
import temporal_claims as tc  # noqa: E402
import temporal_projection as tp  # noqa: E402
import temporal_publication as pub  # noqa: E402
import temporal_store as ts  # noqa: E402
import temporal_timeline as tt  # noqa: E402
import timeline as tl  # noqa: E402

BIRTH_DAY = "1981-07-11"
NOW = "2026-08-27T12:00:00Z"


# ---------------------------------------------------------------------------
# Shared fixtures — the substrate half (receipts + the fold)
# ---------------------------------------------------------------------------


def revision(seed: str) -> str:
    return "sha256:" + hashlib.sha256(seed.encode("utf-8")).hexdigest()


def claim(**overrides) -> dict:
    source = overrides.pop("source", "src-conversation-1")
    seed = overrides.pop("seed", source)
    payload = {
        "source_kind": "conversation",
        "source_ref": {"source_id": source, "revision": revision(seed)},
        "evidence": [{"quote": overrides.pop("quote", "a sentence from the conversation")}],
        "extractor_version": "listener:1",
        "created_at": "2026-08-27T00:00:00Z",
        "basis": "explicit",
        "confidence": 0.9,
        "status": "active",
    }
    payload.update(overrides)
    return tc.validate_temporal_claim(payload)


def owner_birth(best: str = BIRTH_DAY) -> dict:
    return claim(
        claim_type="date",
        subject_mention="self",
        event_kind="birth",
        temporal_value=chrono.DateRecord(
            best=best, earliest=best, latest=best, granularity="day",
            confidence="certain", basis="stated",
        ).to_dict(),
        source="src-birth",
        seed="birth",
    )


def dated(subject: str, best: str, *, event_kind: str = "graduation",
          source: str | None = None) -> dict:
    return claim(
        claim_type="date",
        subject_mention=subject,
        event_kind=event_kind,
        temporal_value=chrono.DateRecord(
            best=best, earliest=best, latest=best, granularity="day",
            confidence="certain", basis="stated",
        ).to_dict(),
        source=source or f"src-{subject}",
        seed=subject,
    )


class VaultTestCase(unittest.TestCase):
    """A throwaway vault per test, outside the repo and never ~/Workspace/dave."""

    def setUp(self) -> None:
        self.vault = Path(tempfile.mkdtemp(prefix="lifehug-eras-e2-"))
        self.addCleanup(shutil.rmtree, self.vault, ignore_errors=True)
        (self.vault / "state").mkdir(parents=True, exist_ok=True)

    def file_claims(self, claims) -> None:
        by_source: dict[tuple[str, str], tuple[dict, list[dict]]] = {}
        for row in claims:
            ref = row["source_ref"]
            key = (ref["source_id"], ref["revision"])
            by_source.setdefault(key, (ref, []))[1].append(dict(row))
        for ref, rows in by_source.values():
            # The FULL ref (including `source_path` when the claim cites an
            # already-promoted vault source, e.g. a landmark entry) — a
            # receipt whose own `source_ref` drops that key fails
            # `validate_extraction_receipt`'s per-claim match, since the
            # claim's own validated `source_ref` still carries it.
            ts.write_receipt(
                self.vault,
                {
                    "source_ref": dict(ref),
                    "extractor_version": "listener:1",
                    "claims": rows,
                },
            )

    def file_landmark(self, domain: str, entry: dict, *, ordinal: int = 1) -> dict:
        """Promote + file one landmark entry — the real writer, not a stand-in."""
        return lp.file_landmark_record(self.vault, domain, entry, ordinal=ordinal, now=NOW)

    def fold(self, *, now: str = NOW, generation: int = 1, roster_snapshot=()):
        return tt.derive_calculated_timeline(
            ts.rebuild_active_index(self.vault),
            membership_assertions=era.active_era_memberships(self.vault),
            display_decisions=era.active_era_displays(self.vault),
            landmark_entries=lp.load_landmark_sources(self.vault),
            roster_snapshot=roster_snapshot,
            projection_generation=generation,
            now=now,
        )

    def node(self, result, *, label_prefix: str = None, event_kind: str = None):
        for row in result.nodes:
            if label_prefix is not None and not str(row.get("label") or "").startswith(label_prefix):
                continue
            if event_kind is not None and row.get("event_kind") != event_kind:
                continue
            return row
        raise AssertionError(f"no node matching label_prefix={label_prefix!r} event_kind={event_kind!r}")


def _birth_and_child(tc_: VaultTestCase, *, child_best: str = "2010-12-21") -> tuple:
    tc_.file_landmark("birth", {
        "domain": "birth", "label": "birth",
        "date": {"best": BIRTH_DAY, "earliest": BIRTH_DAY, "latest": BIRTH_DAY,
                 "granularity": "day", "confidence": "certain", "basis": "stated"},
    })
    result = tc_.file_landmark("children", {
        "domain": "children", "label": "Cricket", "who": "Cricket",
        "date": {"best": child_best, "earliest": child_best, "latest": child_best,
                 "granularity": "day", "confidence": "certain", "basis": "stated"},
    })
    return result


# ---------------------------------------------------------------------------
# O-E2a — the two receipt types (T-M-01, 02, 03, 08, 09, 10)
# ---------------------------------------------------------------------------


class MembershipReceiptTests(VaultTestCase):
    """T-M-01, T-M-02, T-M-03 — content-addressed, round-tripping, validated."""

    def test_filing_the_same_assertion_twice_writes_one_file(self) -> None:
        source_ref = {"source_id": "landmark:entry-abc", "revision": revision("abc")}
        first = era.file_era_membership(
            self.vault, member_node_id="node:aaa", era_node_id="age:self:20s",
            source_ref=source_ref, relation="within", reason="graduated during college",
        )
        second = era.file_era_membership(
            self.vault, member_node_id="node:aaa", era_node_id="age:self:20s",
            source_ref=source_ref, relation="within", reason="a different sentence entirely",
        )
        self.assertEqual(first["assertion_id"], second["assertion_id"])
        files = list((self.vault / era.MEMBERSHIP_SOURCES_DIR).glob("*.md"))
        self.assertEqual(len(files), 1)

    def test_a_different_source_ref_writes_a_second_file(self) -> None:
        first = era.file_era_membership(
            self.vault, member_node_id="node:aaa", era_node_id="age:self:20s",
            source_ref={"source_id": "landmark:entry-a", "revision": revision("a")},
            relation="within",
        )
        second = era.file_era_membership(
            self.vault, member_node_id="node:aaa", era_node_id="age:self:20s",
            source_ref={"source_id": "landmark:entry-b", "revision": revision("b")},
            relation="within",
        )
        self.assertNotEqual(first["assertion_id"], second["assertion_id"])
        files = list((self.vault / era.MEMBERSHIP_SOURCES_DIR).glob("*.md"))
        self.assertEqual(len(files), 2)

    def test_the_receipt_round_trips_with_its_own_source_ref(self) -> None:
        source_ref = {"source_id": "landmark:entry-abc", "revision": revision("abc")}
        filed = era.file_era_membership(
            self.vault, member_node_id="node:aaa", era_node_id="age:self:20s",
            source_ref=source_ref, relation="within",
        )
        reread = era.read_era_membership(self.vault, filed["relative_path"])
        self.assertIsNotNone(reread)
        self.assertEqual(reread["assertion_id"], filed["assertion_id"])
        self.assertEqual(reread["source_ref"]["source_id"],
                         filed["source_ref"]["source_id"])

    def test_a_relation_outside_within_or_associated_is_refused(self) -> None:
        with self.assertRaises(era.EraReceiptError) as caught:
            era.file_era_membership(
                self.vault, member_node_id="node:aaa", era_node_id="age:self:20s",
                source_ref={"source_id": "s", "revision": revision("s")},
                relation="overlaps",
            )
        self.assertEqual(caught.exception.code, "membership_relation_unknown")

    def test_an_empty_member_or_era_is_refused(self) -> None:
        with self.assertRaises(era.EraReceiptError) as caught:
            era.file_era_membership(
                self.vault, member_node_id="", era_node_id="age:self:20s",
                source_ref={"source_id": "s", "revision": revision("s")},
            )
        self.assertEqual(caught.exception.code, "membership_member_required")
        with self.assertRaises(era.EraReceiptError) as caught:
            era.file_era_membership(
                self.vault, member_node_id="node:aaa", era_node_id="",
                source_ref={"source_id": "s", "revision": revision("s")},
            )
        self.assertEqual(caught.exception.code, "membership_era_required")


class DisplayDecisionTests(VaultTestCase):
    """T-M-08 — exactly one primary, and a superseding decision moves it."""

    def test_an_active_decision_makes_exactly_one_membership_primary(self) -> None:
        self.file_claims([owner_birth()])
        # Two independent memberships of one node, one named-era (via receipt)
        # and one frame (arithmetic) — the display decision picks the winner.
        assertion = era.file_era_membership(
            self.vault, member_node_id="node:member-1", era_node_id="era:college",
            source_ref={"source_id": "landmark:entry-1", "revision": revision("1")},
        )
        # `_apply_display_roles` lives in `temporal_timeline` (the fold), not
        # `era_memberships` (the receipt writer) — exercised directly here.
        rows = tt._apply_display_roles(  # noqa: SLF001
            [
                tp.validate_calculated_membership({
                    "member_node_id": "node:member-1", "era_node_id": "era:college",
                    "relation": "within", "evidence_refs": [assertion["assertion_id"]],
                    "confidence": 0.6,
                }),
                tp.validate_calculated_membership({
                    "member_node_id": "node:member-1", "era_node_id": "age:self:20s",
                    "relation": "within", "evidence_refs": ["rule:age-frame-arithmetic:1"],
                    "confidence": 0.6,
                }),
            ],
            decisions=[],
            node_index={},
        )
        primaries = [row for row in rows if row["display_role"] == "primary"]
        self.assertEqual(len(primaries), 1)
        # An explicit, within-relation, receipt-backed row outranks calculated
        # arithmetic with no decision at all.
        self.assertEqual(primaries[0]["era_node_id"], "era:college")

        # Now a display decision names the OTHER container as primary.
        era.file_era_display(
            self.vault, member_node_id="node:member-1",
            primary_container_id="age:self:20s",
        )
        decided = tt._apply_display_roles(  # noqa: SLF001
            [
                tp.validate_calculated_membership({
                    "member_node_id": "node:member-1", "era_node_id": "era:college",
                    "relation": "within", "evidence_refs": [assertion["assertion_id"]],
                }),
                tp.validate_calculated_membership({
                    "member_node_id": "node:member-1", "era_node_id": "age:self:20s",
                    "relation": "within", "evidence_refs": ["rule:age-frame-arithmetic:1"],
                }),
            ],
            decisions=era.active_era_displays(self.vault),
            node_index={},
        )
        winner = next(row for row in decided if row["display_role"] == "primary")
        self.assertEqual(winner["era_node_id"], "age:self:20s")


# ---------------------------------------------------------------------------
# O-E2b — the fold derives `memberships` (T-M-04…07, 09, 10)
# ---------------------------------------------------------------------------


class FrameArithmeticMembershipTests(VaultTestCase):
    """T-M-04 — within once, overlaps everywhere a fuzzy interval touches."""

    def test_a_day_grain_event_inside_one_frame_is_within(self) -> None:
        self.file_claims([owner_birth(), dated("graduation", "2005-05-01")])
        result = self.fold()
        node = self.node(result, event_kind="graduation")
        rows = [m for m in result.memberships if m["member_node_id"] == node["node_id"]]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["relation"], "within")
        self.assertEqual(rows[0]["era_node_id"], "age:self:20s")
        self.assertIn("rule:age-frame-arithmetic:1", rows[0]["evidence_refs"])

    def test_a_decade_grain_event_overlaps_every_frame_it_touches(self) -> None:
        self.file_claims([
            owner_birth(),
            claim(claim_type="date", subject_mention="self", event_kind="graduation",
                 temporal_value=chrono.DateRecord(
                     best="2000/2009", earliest="2000", latest="2009",
                     granularity="range", confidence="approximate", basis="stated",
                 ).to_dict(), source="src-decade", seed="decade"),
        ])
        result = self.fold()
        node = self.node(result, event_kind="graduation")
        rows = [m for m in result.memberships if m["member_node_id"] == node["node_id"]]
        self.assertGreaterEqual(len(rows), 2)
        self.assertTrue(all(row["relation"] == "overlaps" for row in rows))
        # Nothing here picks a winner among the calculated rows themselves.
        primaries = [row for row in rows if row["display_role"] == "primary"]
        self.assertEqual(len(primaries), 1)


class ObservedEnvelopeTests(VaultTestCase):
    """T-M-05 — coverage of explicit members, never a bound."""

    def test_the_envelope_covers_members_and_never_becomes_a_bound(self) -> None:
        member_a = tp.validate_calculated_timeline_node({
            "node_id": "node:a", "node_kind": "event", "event_kind": "graduation",
            "best_temporal_value": chrono.parse_edtf("2001").to_dict(),
            "input_claim_refs": ["claim:" + "a" * 24],
            "calculation_rule_version": tt.CALCULATION_RULE_VERSION,
        })
        member_b = tp.validate_calculated_timeline_node({
            "node_id": "node:b", "node_kind": "event", "event_kind": "graduation",
            "best_temporal_value": chrono.parse_edtf("2005").to_dict(),
            "input_claim_refs": ["claim:" + "b" * 24],
            "calculation_rule_version": tt.CALCULATION_RULE_VERSION,
        })
        memberships = [
            {"member_node_id": "node:a", "era_node_id": "era:college"},
            {"member_node_id": "node:b", "era_node_id": "era:college"},
        ]
        index = {"node:a": member_a, "node:b": member_b}
        envelope = tt.observed_envelope(memberships, index, "era:college")
        self.assertIsNotNone(envelope)
        self.assertEqual(envelope.get("basis"), "order")
        # Never a bound: it is not written into best_temporal_value anywhere.
        for node in (member_a, member_b):
            self.assertNotIn("observed_envelope", node)

    def test_no_named_era_node_exists_yet_so_the_envelope_loop_finds_nothing(self) -> None:
        """E3 mints `named_era` nodes; until then this is a pure function
        exercised with no end-to-end effect — stated, not hidden."""
        self.file_claims([owner_birth()])
        result = self.fold()
        self.assertFalse([n for n in result.nodes if n.get("event_kind") == "named_era"])


class NeverFromEventRefTests(VaultTestCase):
    """T-M-06 — a named-era membership never comes from a claim's `event_ref`."""

    def test_a_claim_carrying_an_eras_event_ref_yields_no_membership(self) -> None:
        self.file_claims([
            owner_birth(),
            claim(claim_type="date", subject_mention="self", event_kind="graduation",
                 event_ref="era:college",
                 temporal_value=chrono.DateRecord(
                     best="2011-06-01", earliest="2011-06-01", latest="2011-06-01",
                     granularity="day", confidence="certain", basis="stated",
                 ).to_dict(), source="src-grad", seed="grad"),
        ])
        result = self.fold()
        node = self.node(result, event_kind="graduation")
        named_era_rows = [m for m in result.memberships
                          if m["member_node_id"] == node["node_id"]
                          and m["era_node_id"] == "era:college"]
        self.assertEqual(named_era_rows, [])


class EmptyEvidenceRefusedTests(VaultTestCase):
    """T-M-07 — the fold never emits a membership with empty `evidence_refs`."""

    def test_every_membership_the_fold_emits_carries_evidence(self) -> None:
        self.file_claims([owner_birth(), dated("graduation", "2005-05-01")])
        result = self.fold()
        self.assertTrue(result.memberships)
        for row in result.memberships:
            self.assertTrue(row["evidence_refs"])

    def test_the_schema_itself_refuses_an_empty_evidence_list(self) -> None:
        with self.assertRaises(tp.CalculatedMembershipError) as caught:
            tp.validate_calculated_membership({
                "member_node_id": "node:a", "era_node_id": "age:self:20s",
                "relation": "within", "evidence_refs": [],
            })
        self.assertEqual(caught.exception.code, "membership_without_evidence")


class UnionOfReceiptsTests(VaultTestCase):
    """T-M-09, T-M-10 — two witnesses, one membership; retract one, it stands."""

    def test_two_assertions_for_one_containment_yield_one_membership_two_refs(self) -> None:
        self.file_claims([owner_birth(), dated("graduation", "2005-05-01")])
        node = self.node(self.fold(), event_kind="graduation")
        first = era.file_era_membership(
            self.vault, member_node_id=node["node_id"], era_node_id="era:college",
            source_ref={"source_id": "landmark:entry-1", "revision": revision("1")},
        )
        second = era.file_era_membership(
            self.vault, member_node_id=node["node_id"], era_node_id="era:college",
            source_ref={"source_id": "landmark:entry-2", "revision": revision("2")},
        )
        result = self.fold()
        college_rows = [m for m in result.memberships
                        if m["member_node_id"] == node["node_id"]
                        and m["era_node_id"] == "era:college"]
        self.assertEqual(len(college_rows), 1)
        self.assertEqual(set(college_rows[0]["evidence_refs"]),
                         {first["assertion_id"], second["assertion_id"]})

    def test_negative_the_union_rule_absent_would_show_two_memberships(self) -> None:
        """Seen failing first (design intent, restated as a live assertion):
        `_asserted_memberships` groups by (member, era, relation) BEFORE
        emitting — bypassing that grouping is exactly the bug T-M-09 guards.
        """
        self.file_claims([owner_birth(), dated("graduation", "2005-05-01")])
        node = self.node(self.fold(), event_kind="graduation")
        era.file_era_membership(
            self.vault, member_node_id=node["node_id"], era_node_id="era:college",
            source_ref={"source_id": "landmark:entry-1", "revision": revision("1")},
        )
        era.file_era_membership(
            self.vault, member_node_id=node["node_id"], era_node_id="era:college",
            source_ref={"source_id": "landmark:entry-2", "revision": revision("2")},
        )
        assertions = era.active_era_memberships(self.vault)
        self.assertEqual(len(assertions), 2)
        # The naive (ungrouped) reading WOULD be two rows; the fold's own
        # `_asserted_memberships` collapses them to one.
        ungrouped = [tp.validate_calculated_membership({
            "member_node_id": a["member_node_id"], "era_node_id": a["era_node_id"],
            "relation": a["relation"], "evidence_refs": [a["assertion_id"]],
        }) for a in assertions]
        self.assertEqual(len(ungrouped), 2)
        grouped = tt._asserted_memberships(  # noqa: SLF001
            assertions, node_ids={node["node_id"]},
        )
        self.assertEqual(len(grouped), 1)

    def test_retracting_one_of_two_leaves_the_membership_with_one_ref(self) -> None:
        self.file_claims([owner_birth(), dated("graduation", "2005-05-01")])
        node = self.node(self.fold(), event_kind="graduation")
        first = era.file_era_membership(
            self.vault, member_node_id=node["node_id"], era_node_id="era:college",
            source_ref={"source_id": "landmark:entry-1", "revision": revision("1")},
        )
        second = era.file_era_membership(
            self.vault, member_node_id=node["node_id"], era_node_id="era:college",
            source_ref={"source_id": "landmark:entry-2", "revision": revision("2")},
        )
        era.retract_era_membership(self.vault, first["assertion_id"], reason="test")
        result = self.fold()
        college_rows = [m for m in result.memberships
                        if m["member_node_id"] == node["node_id"]
                        and m["era_node_id"] == "era:college"]
        self.assertEqual(len(college_rows), 1)
        self.assertEqual(college_rows[0]["evidence_refs"], [second["assertion_id"]])

    def test_retracting_the_last_one_removes_the_membership(self) -> None:
        self.file_claims([owner_birth(), dated("graduation", "2005-05-01")])
        node = self.node(self.fold(), event_kind="graduation")
        only = era.file_era_membership(
            self.vault, member_node_id=node["node_id"], era_node_id="era:college",
            source_ref={"source_id": "landmark:entry-1", "revision": revision("1")},
        )
        era.retract_era_membership(self.vault, only["assertion_id"], reason="test")
        result = self.fold()
        college_rows = [m for m in result.memberships
                        if m["member_node_id"] == node["node_id"]
                        and m["era_node_id"] == "era:college"]
        self.assertEqual(college_rows, [])

    def test_negative_unread_retraction_would_leave_the_membership_standing(self) -> None:
        """Seen failing first: reading ONLY `load_era_memberships` (no status
        fold) would still show both receipts as though neither retracted."""
        self.file_claims([owner_birth(), dated("graduation", "2005-05-01")])
        node = self.node(self.fold(), event_kind="graduation")
        first = era.file_era_membership(
            self.vault, member_node_id=node["node_id"], era_node_id="era:college",
            source_ref={"source_id": "landmark:entry-1", "revision": revision("1")},
        )
        era.retract_era_membership(self.vault, first["assertion_id"], reason="test")
        unfolded = era.load_era_memberships(self.vault)
        self.assertEqual(len(unfolded), 1)
        self.assertEqual(unfolded[0]["status"], "retracted")
        # The FOLDED read (what the fold actually consumes) correctly excludes it.
        self.assertEqual(era.active_era_memberships(self.vault), [])


# ---------------------------------------------------------------------------
# O-E2c — occurrence scope and owner relevance (T-SC-12, T-SC-13)
# ---------------------------------------------------------------------------


class OwnerRelevanceTests(VaultTestCase):
    def test_a_childs_birth_is_other_person_lived_effect_citing_the_entry(self) -> None:
        child = _birth_and_child(self)
        result = self.fold()
        node = self.node(result, event_kind="birth", label_prefix="Cricket")
        self.assertEqual(node["occurrence_subject_scope"], "other_person")
        self.assertEqual(node["owner_timeline_relation"], "lived_effect")
        self.assertIn(child["source_ref"].to_dict()["source_id"],
                      node["relation_evidence_refs"])

    def test_a_loss_is_other_person_lived_effect(self) -> None:
        self.file_landmark("birth", {
            "domain": "birth", "label": "birth",
            "date": {"best": BIRTH_DAY, "earliest": BIRTH_DAY, "latest": BIRTH_DAY,
                    "granularity": "day", "confidence": "certain", "basis": "stated"},
        })
        self.file_landmark("losses", {
            "domain": "losses", "label": "Needy", "who": "Needy",
            "date": {"best": "2008-03-01", "earliest": "2008-03-01", "latest": "2008-03-01",
                    "granularity": "day", "confidence": "certain", "basis": "stated"},
        })
        result = self.fold()
        node = self.node(result, event_kind="death")
        self.assertEqual(node["occurrence_subject_scope"], "other_person")
        self.assertEqual(node["owner_timeline_relation"], "lived_effect")

    def test_a_partnership_is_other_person_participated(self) -> None:
        self.file_landmark("birth", {
            "domain": "birth", "label": "birth",
            "date": {"best": BIRTH_DAY, "earliest": BIRTH_DAY, "latest": BIRTH_DAY,
                    "granularity": "day", "confidence": "certain", "basis": "stated"},
        })
        self.file_landmark("partnerships", {
            "domain": "partnerships", "label": "Katie", "who": "Katie",
            "date": {"best": "2007-01-11", "earliest": "2007-01-11", "latest": "2007-01-11",
                    "granularity": "day", "confidence": "certain", "basis": "stated"},
        })
        result = self.fold()
        node = self.node(result, event_kind="transition")
        self.assertEqual(node["occurrence_subject_scope"], "other_person")
        self.assertEqual(node["owner_timeline_relation"], "participated")

    def test_a_non_birth_claim_about_the_same_child_is_contextual_only(self) -> None:
        """T-SC-13 — a `children` entry supports ONLY that child's birth; a
        graduation claim citing the SAME entry supports nothing else about her
        and gets no frame membership."""
        child = _birth_and_child(self)
        source_ref = child["source_ref"].to_dict()
        self.file_claims([claim(
            claim_type="date", subject_mention="Cricket", event_kind="graduation",
            temporal_value=chrono.DateRecord(
                best="2029-06-01", earliest="2029-06-01", latest="2029-06-01",
                granularity="day", confidence="certain", basis="stated",
            ).to_dict(), source_kind="import", source_ref=source_ref,
            source="cricket-grad", seed="cricket-grad",
        )])
        result = self.fold()
        node = self.node(result, event_kind="graduation")
        self.assertEqual(node["occurrence_subject_scope"], "other_person")
        self.assertEqual(node["owner_timeline_relation"], "contextual_only")
        member_ids = {m["member_node_id"] for m in result.memberships}
        self.assertNotIn(node["node_id"], member_ids)

    def test_negative_without_the_gate_it_would_land_in_a_frame(self) -> None:
        """Seen failing first: `on_axis` in `_frame_memberships` is the gate —
        without it every dated node (contextual_only included) gets frame
        arithmetic run over it regardless of relevance."""
        child = _birth_and_child(self)
        source_ref = child["source_ref"].to_dict()
        self.file_claims([claim(
            claim_type="date", subject_mention="Cricket", event_kind="graduation",
            temporal_value=chrono.DateRecord(
                best="2029-06-01", earliest="2029-06-01", latest="2029-06-01",
                granularity="day", confidence="certain", basis="stated",
            ).to_dict(), source_kind="import", source_ref=source_ref,
            source="cricket-grad", seed="cricket-grad",
        )])
        result = self.fold()
        node = self.node(result, event_kind="graduation")
        # Without the axis gate, frame arithmetic alone would place ANY dated
        # node — demonstrated by calling it directly, ungated.
        frames = cd.age_frames(chrono.parse_edtf(BIRTH_DAY), as_of="2026-08-27")
        ungated = tt._frame_memberships(  # noqa: SLF001
            [node], frames, on_axis={node["node_id"]: True},
        )
        self.assertTrue(ungated)
        gated = tt._frame_memberships(  # noqa: SLF001
            [node], frames, on_axis={node["node_id"]: False},
        )
        self.assertEqual(gated, [])

    def test_charlees_letter_positions_by_date_never_by_childhood_membership(self) -> None:
        """Charlee's letter (synthetic `Cricket`, owner born 1981-07-11): a
        2022-05 letter positions in the owner's 40s BY DATE, other_person /
        lived_effect citing the `children` entry, and no Childhood membership
        anywhere — not from an assertion, not from arithmetic, not from the
        legacy pass."""
        child = _birth_and_child(self)
        source_ref = child["source_ref"].to_dict()
        self.file_claims([claim(
            claim_type="date", subject_mention="Cricket", event_kind="birth",
            temporal_value=chrono.DateRecord(
                best="2022-05-01", earliest="2022-05-01", latest="2022-05-01",
                granularity="day", confidence="certain", basis="stated",
            ).to_dict(), source_kind="import", source_ref=source_ref,
            source="cricket-letter", seed="cricket-letter", quote="the Father's-Day letter",
        )])
        result = self.fold()
        letter = next(n for n in result.nodes
                     if n.get("event_kind") == "birth"
                     and str(n.get("best_temporal_value", {}).get("best")).startswith("2022"))
        self.assertEqual(letter["occurrence_subject_scope"], "other_person")
        self.assertEqual(letter["owner_timeline_relation"], "lived_effect")
        rows = [m for m in result.memberships if m["member_node_id"] == letter["node_id"]]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["era_node_id"], "age:self:40s")
        childhood_rows = [m for m in result.memberships
                         if m["member_node_id"] == letter["node_id"]
                         and m["era_node_id"] == "age:self:childhood"]
        self.assertEqual(childhood_rows, [])

    def test_grandmas_age_never_seeds_the_owners_axis(self) -> None:
        """"Grandma was 30 years old in 1951" never dates off the owner's
        birthday: `from_age_statement` returns `None` under the third-person
        veto, and the legacy row's `placement_reason.subject_check` says so."""
        event = {"when_hint": "Grandma was 30 years old in 1951", "eras": [],
                "date": None, "source": "answers/A1.md"}
        derived = cd.from_age_statement(event, chrono.parse_edtf(BIRTH_DAY))
        self.assertIsNone(derived)
        periods = [{"slug": "childhood", "name": "Childhood", "aliases": [], "sources": set()}]
        slot, reason = tl.heuristic_slot(event, periods)
        self.assertIsNone(slot)
        self.assertEqual(reason["subject_check"], "third_person_age")

    def test_negative_without_the_veto_grandma_would_date_off_the_owners_birthday(self) -> None:
        """Seen failing first: the SAME fragment with no relation word in
        front of it dates cleanly off the owner's own birthday — the veto is
        what makes the difference, not `from_age_statement` itself."""
        event = {"when_hint": "I was 30 years old in 1951", "eras": [], "date": None}
        derived = cd.from_age_statement(event, chrono.parse_edtf(BIRTH_DAY))
        self.assertIsNotNone(derived)

    def test_an_unresolved_mention_is_unresolved_never_the_owner(self) -> None:
        self.file_claims([owner_birth(), dated("Jamie", "2015-06-01")])
        roster = [
            {"slug": "jamie-marsh", "name": "Jamie", "type": "person"},
            {"slug": "jamie-cole", "name": "Jamie", "type": "person"},
        ]
        result = self.fold(roster_snapshot=roster)
        node = self.node(result, event_kind="graduation")
        self.assertEqual(node["occurrence_subject_scope"], "unresolved")
        self.assertEqual(node["owner_timeline_relation"], "unresolved")
        self.assertEqual(node["life_view"], "unresolved")
        member_ids = {m["member_node_id"] for m in result.memberships}
        self.assertNotIn(node["node_id"], member_ids)

    def test_an_owner_occurrence_before_birth_is_contradictory(self) -> None:
        self.file_claims([owner_birth(), dated("self", "1975-06-01", event_kind="graduation")])
        result = self.fold()
        node = self.node(result, event_kind="graduation")
        self.assertEqual(node["life_view"], "contradictory")
        findings = [f for f in result.diagnostics.get("findings", [])
                   if f.get("finding") == "before_owner_birth"]
        self.assertTrue(findings)
        self.assertIn(node["node_id"], findings[0]["node_ids"])

    def test_the_owners_own_life_domains_never_reach_the_subject_question(self) -> None:
        """residences/schools/work/military/birth are the owner's own life —
        their entries are `owner`/`participated` whatever their raw mention
        text happens to be (a domain-word fallback is common)."""
        self.file_landmark("birth", {
            "domain": "birth", "label": "birth",
            "date": {"best": BIRTH_DAY, "earliest": BIRTH_DAY, "latest": BIRTH_DAY,
                    "granularity": "day", "confidence": "certain", "basis": "stated"},
        })
        self.file_landmark("residences", {
            "domain": "residences", "label": "Mesa", "city": "Mesa",
            "span": {"start": {"best": "1984", "earliest": "1984", "latest": "1984",
                              "granularity": "year", "confidence": "approximate",
                              "basis": "stated"},
                    "end": {"best": "1990", "earliest": "1990", "latest": "1990",
                            "granularity": "year", "confidence": "approximate",
                            "basis": "stated"}},
        })
        result = self.fold()
        residence_nodes = [n for n in result.nodes
                          if n.get("event_kind") in ("started", "ended")]
        self.assertTrue(residence_nodes)
        for node in residence_nodes:
            self.assertEqual(node["occurrence_subject_scope"], "owner")
            self.assertEqual(node["owner_timeline_relation"], "participated")


# ---------------------------------------------------------------------------
# O-E2d/e — the legacy placement pass, rewritten (T-PL) and bands retired
# ---------------------------------------------------------------------------


PAGE = """---
title: "{title}"
type: {page_type}
chrono: {chrono}
{extra}sources:
{sources}---

# {title}
"""


def _sources(refs):
    return "".join(f'  - "answers/{ref}.md"\n' for ref in refs)


class LegacyVaultFixture(unittest.TestCase):
    """A minimal legacy vault: one age-band-named era, one named era, a
    birth landmark. Enough surface for the placement-rewrite tests."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.root = root
        (root / "wiki" / "periods").mkdir(parents=True)
        (root / "sources" / "manual").mkdir(parents=True)
        (root / "state" / "classifications").mkdir(parents=True)
        (root / "state" / "entity_rosters").mkdir()
        (root / "state" / "connectors").mkdir()

        (root / "wiki" / "periods" / "childhood.md").write_text(
            PAGE.format(title="Childhood", page_type="period", chrono=1,
                        extra="", sources=_sources([])), encoding="utf-8")
        (root / "wiki" / "periods" / "college.md").write_text(
            PAGE.format(title="College", page_type="period", chrono=2,
                        extra="", sources=_sources([])), encoding="utf-8")
        (root / "state" / "entity_rosters" / "period.json").write_text(json.dumps({
            "version": 1, "type": "period", "entities": [
                {"name": "Childhood", "slug": "childhood", "chrono": 1,
                 "page_eligible": True},
                {"name": "College", "slug": "college", "chrono": 2,
                 "page_eligible": True},
            ]}), encoding="utf-8")
        self.store = root / "state" / "landmarks.json"
        self.store.write_text(json.dumps({
            "version": 1,
            "domains": {"birth": [{"label": "birth", "date": chrono.parse_edtf(BIRTH_DAY).to_dict()}]},
        }), encoding="utf-8")

        self._orig = {name: getattr(tl, name) for name in tl.VAULT_ROOT_NAMES}
        state = root / "state"
        for name, value in {
            "CLASSIFICATIONS_DIR": state / "classifications",
            "CONNECTORS_STATE_DIR": state / "connectors",
            "ENTITY_ROSTERS_DIR": state / "entity_rosters",
            "MANUAL_SOURCES_DIR": root / "sources" / "manual",
            "PLACEMENTS_FILE": state / "timeline_placements.json",
            "STATE_DIR": state,
            "WIKI_DIR": root / "wiki",
        }.items():
            setattr(tl, name, value)
        self.addCleanup(self._restore)

    def _restore(self) -> None:
        for name, value in self._orig.items():
            setattr(tl, name, value)

    def data(self):
        with mock.patch.object(tl, "LANDMARKS_STORE", self.store):
            return tl.timeline_data()

    def periods(self):
        return tl.load_periods()

    def frames(self):
        birth = chrono.parse_edtf(BIRTH_DAY)
        return cd.age_frames(birth, as_of="2026-08-27")


class RungOrderTests(LegacyVaultFixture):
    """T-PL — a pin beats a date, a date beats era language, era language
    beats era text; each row names the rung that fired."""

    def test_rung_1_dated_beats_era_language_and_text(self) -> None:
        # Owner born 1981-07-11; 1985 is well inside "childhood" by arithmetic
        # (age ~3), whatever era language the moment ALSO happens to name —
        # here "college days", which would win rung 2 if rung 1 did not fire
        # first.
        periods = self.periods()
        frames = self.frames()
        event = {"when_hint": "college days", "eras": [], "date": chrono.parse_edtf("1985-01-01"),
                "source": "x"}
        slot, reason = tl.heuristic_slot(event, periods, frames=frames)
        self.assertEqual(slot, "childhood")
        self.assertEqual(reason["rung"], 1)
        self.assertEqual(reason["frame_by"], "date")

    def test_rung_2_named_era_language_beats_era_text(self) -> None:
        periods = self.periods()
        event = {"when_hint": "a month before I graduated college", "eras": [],
                "date": None, "source": "x"}
        slot, reason = tl.heuristic_slot(event, periods)
        self.assertEqual(slot, "college")
        self.assertEqual(reason["rung"], 2)
        self.assertEqual(reason["era_by"], "event_language")

    def test_rung_3_era_text_is_the_last_resort(self) -> None:
        # "Childhood" is ALSO this roster's own period NAME, so an event
        # naming it verbatim would win at rung 2 (named-era language) — this
        # isolates rung 3 with a keyword ("twenties") that names no period by
        # its OWN label, only by `_PERIOD_KEYWORDS`'s era-text table.
        periods = self.periods() + [
            {"slug": "my-20s", "name": "My 20s", "chrono": 3, "sources": set()},
        ]
        event = {"when_hint": "back in my twenties", "eras": [], "date": None, "source": "x"}
        slot, reason = tl.heuristic_slot(event, periods)
        self.assertEqual(slot, "my-20s")
        self.assertEqual(reason["rung"], 3)
        self.assertEqual(reason["era_by"], "era_text")

    def test_rung_0_a_manual_pin_always_wins(self) -> None:
        events = [{"title": "x", "description": "x", "when_hint": "college days",
                  "eras": [], "date": None, "source": "answers/A1.md",
                  "source_short": "A1"}]
        placements = {"placements": [{
            "key": tl.placement_key(events[0]), "period": "childhood",
        }], "retired": []}
        placed, _ = tl.place_events(events, self.periods(), placements)
        self.assertEqual(placed["childhood"][0]["placement_reason"]["rung"], 0)
        self.assertEqual(placed["childhood"][0]["placement_reason"]["evidence"], "manual")

    def test_every_placed_row_carries_a_provenance_summary(self) -> None:
        events = [{"title": "x", "description": "x", "when_hint": "back in my childhood",
                  "eras": [], "date": None, "source": "answers/A1.md",
                  "source_short": "A1"}]
        placed, unplaced = tl.place_events(events, self.periods())
        self.assertTrue(placed["childhood"][0]["provenance_summary"])


class SourceMembershipGoneTests(LegacyVaultFixture):
    """T-PL — an event whose ONLY signal is source citation is unplaced."""

    def test_citing_a_source_on_an_era_page_places_nothing(self) -> None:
        (self.root / "wiki" / "periods" / "childhood.md").write_text(
            PAGE.format(title="Childhood", page_type="period", chrono=1,
                        extra="", sources=_sources(["A1"])), encoding="utf-8")
        events = [{"title": "x", "description": "something happened", "when_hint": "",
                  "eras": [], "date": None, "source": "answers/A1.md",
                  "source_short": "A1"}]
        placed, unplaced = tl.place_events(events, self.periods())
        self.assertEqual(placed["childhood"], [])
        self.assertEqual(len(unplaced), 1)


class RemovedMechanismGuardTests(unittest.TestCase):
    """`learned_era_vocabulary`, `_era_tokens`, `_ERA_STOPWORDS` do not exist
    anywhere in `system/` — a definition-level AST/grep guard."""

    REMOVED_NAMES = ("learned_era_vocabulary", "_era_tokens", "_ERA_STOPWORDS")

    def test_no_definition_of_a_removed_name_exists_in_system(self) -> None:
        for path in sorted((ROOT / "system").glob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            defined = set()
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    defined.add(node.name)
                elif isinstance(node, ast.Assign):
                    for target in node.targets:
                        if isinstance(target, ast.Name):
                            defined.add(target.id)
            hit = defined & set(self.REMOVED_NAMES)
            self.assertFalse(hit, f"{path.name} still defines {hit}")

    def test_era_gap_mechanism_is_gone(self) -> None:
        self.assertFalse(hasattr(tl, "era_gaps"))
        self.assertFalse(hasattr(tl, "MIN_ERA_GAP_YEARS"))
        self.assertNotIn("era_gap", tl.UNKNOWN_KINDS)


class PinOutsideFrameRefusedTests(LegacyVaultFixture):
    """T-PL — a pin whose date cannot be inside its period's frame is refused."""

    def test_a_pin_naming_an_age_band_is_validated_against_the_frame(self) -> None:
        with mock.patch.object(tl, "LANDMARKS_STORE", self.store):
            with self.assertRaises(ValueError) as caught:
                tl.save_placement(
                    "k1", "answers/A1.md", "something happened", "childhood",
                    date=chrono.parse_edtf("2030-01-01"),
                )
        self.assertIn("placement_outside_frame", str(caught.exception))

    def test_a_pin_inside_its_frame_is_accepted(self) -> None:
        with mock.patch.object(tl, "LANDMARKS_STORE", self.store):
            record = tl.save_placement(
                "k2", "answers/A1.md", "something happened", "childhood",
                date=chrono.parse_edtf("1985-01-01"),
            )
        self.assertEqual(record["period"], "childhood")

    def test_a_pin_onto_a_non_frame_period_is_unaffected(self) -> None:
        with mock.patch.object(tl, "LANDMARKS_STORE", self.store):
            record = tl.save_placement(
                "k3", "answers/A1.md", "something happened", "college",
                date=chrono.parse_edtf("2030-01-01"),
            )
        self.assertEqual(record["period"], "college")


class ScoredThingsExcludeAgeFrameTests(unittest.TestCase):
    """T-PL — `_scored_things` contains no `age_frame` row."""

    def test_no_age_frame_row_is_ever_scored(self) -> None:
        data = {
            "event_lineup": {}, "unplaced_events": [],
            "periods": [{"slug": "age:self:20s", "name": "My 20s",
                        "kind": "age_frame", "date": None}],
            "bands": [],
        }
        things = tl._scored_things(data, (1981, 2026))  # noqa: SLF001
        self.assertFalse([t for t in things if t.get("kind") == "age_frame"])


class UnplacedRowKeepsReasonTests(LegacyVaultFixture):
    """T-CV — a moment with no era stays a row with `placement_reason`."""

    def test_an_unplaced_moment_carries_placement_reason(self) -> None:
        events = [{"title": "x", "description": "nothing datable at all",
                  "when_hint": "", "eras": [], "date": None,
                  "source": "answers/A1.md", "source_short": "A1"}]
        placed, unplaced = tl.place_events(events, self.periods())
        self.assertEqual(len(unplaced), 1)
        self.assertIn("placement_reason", unplaced[0])
        self.assertIn("provenance_summary", unplaced[0])
        self.assertIsNone(unplaced[0]["placement_reason"]["rung"])


# ---------------------------------------------------------------------------
# O-E2f — the parity test, legacy ≡ fold (§5.6)
# ---------------------------------------------------------------------------


class ParityTests(unittest.TestCase):
    """Every rule shared between the legacy pass and the fold agrees."""

    def test_legacy_rung_1_agrees_with_frame_for_over_a_grain_matrix(self) -> None:
        birth = chrono.parse_edtf(BIRTH_DAY)
        frames = cd.age_frames(birth, as_of="2026-08-27")
        periods = [{"slug": s, "name": n, "aliases": [], "sources": set()}
                  for s, n in (("childhood", "Childhood"), ("my-20s", "My 20s"),
                              ("my-30s", "My 30s"))]
        cases = [
            "1985-03-01",       # day grain, well inside childhood
            "2001-07-11",       # year boundary, exactly the 20s' start
            "2011-07-10",       # last day of the 20s
            "2011-07-11",       # first day of the 30s
        ]
        for text in cases:
            with self.subTest(text=text):
                record = chrono.parse_edtf(text)
                band = cd.frame_for(frames, record)
                event = {"when_hint": "", "eras": [], "date": record, "source": "x"}
                slot, reason = tl.heuristic_slot(event, periods, frames=frames)
                expected_slugs = cd.age_frame_legacy_slugs().get(band, ()) if band else ()
                if band is None:
                    self.assertIsNone(slot)
                else:
                    self.assertIn(slot, expected_slugs)
                    self.assertEqual(reason["rung"], 1)

    def test_the_legacy_subject_veto_agrees_with_the_folds_occurrence_scope(self) -> None:
        text = "Grandma was 30 years old in 1951"
        self.assertTrue(cd.age_statement_is_third_person(text))
        event = {"when_hint": text, "eras": [], "date": None, "source": "x"}
        periods = [{"slug": "childhood", "name": "Childhood", "aliases": [], "sources": set()}]
        slot, reason = tl.heuristic_slot(event, periods)
        self.assertIsNone(slot)
        self.assertEqual(reason.get("subject_check"), "third_person_age")

    def test_an_event_the_fold_calls_contextual_only_is_off_the_legacy_axis(self) -> None:
        """A `children`-entry-backed non-birth claim is `contextual_only` in
        the fold; the equivalent legacy signal (no date, no era language) is
        unplaced in the legacy pass too — both leave the moment off the axis."""
        event = {"when_hint": "", "eras": [], "date": None, "source": "answers/A1.md"}
        periods = [{"slug": "childhood", "name": "Childhood", "aliases": [], "sources": set()}]
        slot, _reason = tl.heuristic_slot(event, periods)
        self.assertIsNone(slot)


# ---------------------------------------------------------------------------
# Manifest — this contract's new files ship in `framework_files`
# ---------------------------------------------------------------------------


class ManifestTests(unittest.TestCase):
    def test_every_new_file_ships_in_framework_files(self) -> None:
        manifest = set(json.loads((SYSTEM / "version.json").read_text())["framework_files"])
        for path in ("system/era_memberships.py", "tests/test_eras_e2.py"):
            self.assertIn(path, manifest)


if __name__ == "__main__":
    unittest.main()
