"""Event identity I0 — contract C1: the telling manifest and the re-key table.

Controlling design: lifehug-platform `docs/design/event-identity.md` v4 §3.1
(with §5.1's era-composition pin and §13.1's promises). Contract spec:
`docs/contracts/event-identity-i0-records.md`.

**Fixture inventory** (each named for the case it proves; all synthetic, and
NOTHING here ever reads ~/Workspace/dave):

===========================  ==============================================
``fixture_remint``           §3.1 case 1 — a new extractor version re-mints
                             claims over unchanged words
``fixture_reworded_evident`` §3.1 case 2 (re-key) — a rewording at an
                             unchanged document revision with two agreeing
                             signature components
``fixture_reworded_bare``    §3.1 case 2 (refuse) — the SAME cardinality with
                             no evidence at all: one old row gone, one new
                             row arrived, and nothing else in common
``fixture_fragmented``       §3.1 case 3 — one telling becomes two
``fixture_merged``           §3.1 case 3 — two tellings become one
``fixture_corrected``        §3.1 case 4 — the document's own revision moved
``fixture_undeclared``       the phase's honest gap: no extractor declared a
                             document revision, so nothing re-keys
``fixture_two_events``       §13.1 — one telling, two event identities
``fixture_era_composition``  §5.1 — a telling *within* an era stays eligible;
                             a telling *about* an era does not
``fixture_stable_sibling``   the cohort rule — an event that did NOT move is
                             not a candidate successor for one that did
``fixture_landmark``         the landmark mint — a durable recorder event id
===========================  ==============================================

Every negative test in this file was run against a build with its guard
removed and SEEN failing before the guard was written; the evidence table is
in the PR body.
"""

from __future__ import annotations

import hashlib
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "system"))
sys.path.insert(0, str(ROOT / "tests"))

import event_identity as ei  # noqa: E402
import temporal_claims as tc  # noqa: E402
import temporal_store as ts  # noqa: E402
from tempdirs import root_parent_tmp  # noqa: E402

NOW = "2026-08-30T09:00:00Z"

STORY = "answers/A1.md"
STEM = "story-a"
DOCUMENT = f"classification:{STEM}"


def _rev(tag: str) -> str:
    return "sha256:" + hashlib.sha256(tag.encode("utf-8")).hexdigest()


def _vault(case: unittest.TestCase, prefix: str) -> Path:
    root = root_parent_tmp(case, ROOT, prefix=prefix)
    (root / "state").mkdir(parents=True, exist_ok=True)
    (root / "sources").mkdir(parents=True, exist_ok=True)
    return root


def _claim(
    *,
    source_id: str,
    revision: str,
    extractor: str,
    subject: str,
    event_mention: str | None = None,
    claim_type: str = "occurrence",
    event_kind: str = "moment",
    temporal_value: object = None,
    places: tuple[str, ...] = (),
    span: tuple[int, int] | None = None,
    event_ref: str | None = None,
) -> dict:
    row: dict = {
        "source_ref": {"source_id": source_id, "revision": revision},
        "source_kind": "import",
        "claim_type": claim_type,
        "subject_mention": subject,
        "extractor_version": extractor,
        "basis": "explicit",
        "confidence": 0.9,
        "created_at": NOW,
        "evidence": [
            {
                "quote": f"{subject} — {event_mention or 'said so'}",
                **({"start": span[0], "end": span[1]} if span else {}),
            }
        ],
    }
    if claim_type != "identity":
        row["event_kind"] = event_kind
        if event_mention:
            row["event_mention"] = event_mention
        if event_ref:
            row["event_ref"] = event_ref
    if temporal_value is not None:
        row["temporal_value"] = temporal_value
    if places:
        row["place_mentions"] = list(places)
    return row


def _file(
    root: Path,
    *,
    source_id: str,
    revision: str,
    extractor: str,
    claims: list[dict],
    document_revision: str | None = None,
    telling_keys: dict | None = None,
    recorder_event_id: str | None = None,
) -> list[str]:
    ts.write_receipt(
        root,
        {
            "source_ref": {"source_id": source_id, "revision": revision},
            "extractor_version": extractor,
            "extractor": ei.declare_tellings(
                {"name": "test"},
                telling_keys=telling_keys,
                document_revision=document_revision,
                recorder_event_id=recorder_event_id,
            ),
            "created_at": NOW,
            "claims": claims,
        },
    )
    return [tc.validate_temporal_claim(claim)["claim_id"] for claim in claims]


def _retire(root: Path, claim_ids: list[str], reason: str) -> None:
    ts.file_temporal_correction(
        root, kind="supersede", claim_ids=claim_ids, reason=reason, occurred_at=NOW
    )


def _rows(manifest: dict) -> dict:
    return {row["telling_ref"]: row for row in manifest["tellings"]}


def _findings(manifest: dict) -> list[str]:
    return sorted(row["finding"] for row in manifest["diagnostics"])


# --------------------------------------------------------------------------
# Fixtures
# --------------------------------------------------------------------------


def fixture_remint(root: Path) -> dict:
    """Case 1 — the words did not move; a new extractor read them again."""
    revision = _rev("classification-1")
    document = _rev("story-a-v1")
    ref = f"{DOCUMENT}#aaaa1111aaaa"
    first = _file(
        root,
        source_id=ref,
        revision=revision,
        extractor="classify:1",
        document_revision=document,
        claims=[
            _claim(
                source_id=ref, revision=revision, extractor="classify:1",
                subject="Etherfuse", event_mention="Started Etherfuse",
                places=("San Diego",), span=(10, 40),
            )
        ],
    )
    second = _file(
        root,
        source_id=ref,
        revision=revision,
        extractor="classify:2",
        document_revision=document,
        claims=[
            _claim(
                source_id=ref, revision=revision, extractor="classify:2",
                subject="Etherfuse", event_mention="Started Etherfuse",
                places=("San Diego",), span=(10, 40),
            )
        ],
    )
    return {"telling_ref": ref, "first_claims": first, "second_claims": second}


def _reworded(root: Path, *, evident: bool, document_revision: str | None) -> dict:
    """Case 2 in both directions; ``evident`` decides whether the new row
    shares anything but the document with the old one."""
    old_revision, new_revision = _rev("classification-1"), _rev("classification-2")
    old_ref, new_ref = f"{DOCUMENT}#bbbb2222bbbb", f"{DOCUMENT}#cccc3333cccc"
    old_claims = _file(
        root,
        source_id=old_ref,
        revision=old_revision,
        extractor="classify:1",
        document_revision=document_revision,
        claims=[
            _claim(
                source_id=old_ref, revision=old_revision, extractor="classify:1",
                subject="Etherfuse", event_mention="Started Etherfuse",
                places=("San Diego",),
            )
        ],
    )
    if evident:
        new_claim = _claim(
            source_id=new_ref, revision=new_revision, extractor="classify:2",
            subject="Etherfuse", event_mention="Started Etherfuse",
            places=("San Diego",),
        )
    else:
        new_claim = _claim(
            source_id=new_ref, revision=new_revision, extractor="classify:2",
            subject="the county fair", event_mention="A trip to the county fair",
            places=("Mesa",),
        )
    _file(
        root,
        source_id=new_ref,
        revision=new_revision,
        extractor="classify:2",
        document_revision=document_revision,
        claims=[new_claim],
    )
    _retire(root, old_claims, "story-a was re-classified; the earlier reading no longer stands.")
    return {"old": old_ref, "new": new_ref}


def fixture_reworded_evident(root: Path) -> dict:
    return _reworded(root, evident=True, document_revision=_rev("story-a-v1"))


def fixture_reworded_bare(root: Path) -> dict:
    return _reworded(root, evident=False, document_revision=_rev("story-a-v1"))


def fixture_undeclared(root: Path) -> dict:
    return _reworded(root, evident=True, document_revision=None)


def fixture_corrected(root: Path) -> dict:
    """Case 4 — the person edited the story, so the document's revision moved."""
    old_revision, new_revision = _rev("classification-1"), _rev("classification-9")
    old_ref, new_ref = f"{DOCUMENT}#dddd4444dddd", f"{DOCUMENT}#eeee5555eeee"
    old_claims = _file(
        root,
        source_id=old_ref, revision=old_revision, extractor="classify:1",
        document_revision=_rev("story-a-v1"),
        claims=[
            _claim(
                source_id=old_ref, revision=old_revision, extractor="classify:1",
                subject="Etherfuse", event_mention="Started Etherfuse",
                places=("San Diego",),
            )
        ],
    )
    _file(
        root,
        source_id=new_ref, revision=new_revision, extractor="classify:1",
        document_revision=_rev("story-a-v2"),
        claims=[
            _claim(
                source_id=new_ref, revision=new_revision, extractor="classify:1",
                subject="Etherfuse", event_mention="Started Etherfuse",
                places=("San Diego",),
            )
        ],
    )
    _retire(root, old_claims, "the person corrected answers/A1.md.")
    return {"old": old_ref, "new": new_ref}


def fixture_fragmented(root: Path) -> dict:
    """Case 3 — one telling becomes two inside one re-extraction."""
    old_revision, new_revision = _rev("classification-1"), _rev("classification-2")
    document = _rev("story-a-v1")
    old_ref = f"{DOCUMENT}#ffff6666ffff"
    left, right = f"{DOCUMENT}#1111aaaa1111", f"{DOCUMENT}#2222bbbb2222"
    old_claims = _file(
        root,
        source_id=old_ref, revision=old_revision, extractor="classify:1",
        document_revision=document,
        claims=[
            _claim(
                source_id=old_ref, revision=old_revision, extractor="classify:1",
                subject="Etherfuse", event_mention="Founded Etherfuse and moved",
                places=("San Diego",),
            )
        ],
    )
    for ref, mention in ((left, "Founded Etherfuse"), (right, "Moved to San Diego")):
        _file(
            root,
            source_id=ref, revision=new_revision, extractor="classify:2",
            document_revision=document,
            claims=[
                _claim(
                    source_id=ref, revision=new_revision, extractor="classify:2",
                    subject="Etherfuse", event_mention=mention, places=("San Diego",),
                )
            ],
        )
    _retire(root, old_claims, "story-a was re-classified into two moments.")
    return {"old": old_ref, "left": left, "right": right}


def fixture_merged(root: Path) -> dict:
    """Case 3, the other direction — two tellings become one."""
    old_revision, new_revision = _rev("classification-1"), _rev("classification-2")
    document = _rev("story-a-v1")
    left, right = f"{DOCUMENT}#3333cccc3333", f"{DOCUMENT}#4444dddd4444"
    merged = f"{DOCUMENT}#5555eeee5555"
    retired: list[str] = []
    for ref, mention in ((left, "Founded Etherfuse"), (right, "Founded Etherfuse")):
        retired += _file(
            root,
            source_id=ref, revision=old_revision, extractor="classify:1",
            document_revision=document,
            claims=[
                _claim(
                    source_id=ref, revision=old_revision, extractor="classify:1",
                    subject="Etherfuse", event_mention=mention, places=("San Diego",),
                )
            ],
        )
    _file(
        root,
        source_id=merged, revision=new_revision, extractor="classify:2",
        document_revision=document,
        claims=[
            _claim(
                source_id=merged, revision=new_revision, extractor="classify:2",
                subject="Etherfuse", event_mention="Founded Etherfuse",
                places=("San Diego",),
            )
        ],
    )
    _retire(root, retired, "story-a's two readings were re-classified as one moment.")
    return {"left": left, "right": right, "merged": merged}


def fixture_two_events(root: Path) -> dict:
    """§13.1 — one telling whose claims name two distinct event identities."""
    revision = _rev("classification-1")
    ref = f"{DOCUMENT}#6666ffff6666"
    _file(
        root,
        source_id=ref, revision=revision, extractor="classify:1",
        document_revision=_rev("story-a-v1"),
        claims=[
            _claim(
                source_id=ref, revision=revision, extractor="classify:1",
                subject="Etherfuse", event_mention="Founded Etherfuse",
                event_ref="node:1111111111111111111111aa",
            ),
            _claim(
                source_id=ref, revision=revision, extractor="classify:1",
                subject="the wedding", event_mention="Our wedding",
                event_ref="node:2222222222222222222222bb",
            ),
        ],
    )
    return {"telling_ref": ref}


def fixture_era_composition(root: Path) -> dict:
    """§5.1 — within an era vs about an era."""
    revision = _rev("classification-1")
    within = f"{DOCUMENT}#7777aaaa7777"
    era_ref = "era:" + "a" * 24
    _file(
        root,
        source_id=within, revision=revision, extractor="classify:1",
        document_revision=_rev("story-a-v1"),
        claims=[
            _claim(
                source_id=within, revision=revision, extractor="classify:1",
                subject="the dorm fire", event_mention="The dorm fire",
                event_ref=era_ref,
            )
        ],
    )
    about_revision = _rev("era-source-1")
    about = "era:" + "b" * 24
    _file(
        root,
        source_id=about, revision=about_revision, extractor="era_identity",
        document_revision=_rev("era-doc-1"),
        claims=[
            _claim(
                source_id=about, revision=about_revision, extractor="era_identity",
                subject=about, claim_type="identity",
            )
        ],
    )
    return {"within": within, "about": about, "era_ref": era_ref}


def fixture_stable_sibling(root: Path) -> dict:
    """The cohort rule — a document holding two events, one of which moved.

    Without the cohort rule the retired row sees TWO live candidates (the
    reworded one and the untouched sibling) and reads as a fragmentation, so
    an ordinary rewording would stop re-keying the moment a story had more
    than one moment in it — which is every real story.
    """
    old_revision, new_revision = _rev("classification-1"), _rev("classification-2")
    document = _rev("story-a-v1")
    stable = f"{DOCUMENT}#8888bbbb8888"
    old_ref, new_ref = f"{DOCUMENT}#9999cccc9999", f"{DOCUMENT}#aaaadddd0000"
    for revision, extractor in ((old_revision, "classify:1"), (new_revision, "classify:2")):
        _file(
            root,
            source_id=stable, revision=revision, extractor=extractor,
            document_revision=document,
            claims=[
                _claim(
                    source_id=stable, revision=revision, extractor=extractor,
                    subject="the wedding", event_mention="Our wedding",
                    places=("Mesa",),
                )
            ],
        )
    old_claims = _file(
        root,
        source_id=old_ref, revision=old_revision, extractor="classify:1",
        document_revision=document,
        claims=[
            _claim(
                source_id=old_ref, revision=old_revision, extractor="classify:1",
                subject="Etherfuse", event_mention="Started Etherfuse",
                places=("San Diego",),
            )
        ],
    )
    _file(
        root,
        source_id=new_ref, revision=new_revision, extractor="classify:2",
        document_revision=document,
        claims=[
            _claim(
                source_id=new_ref, revision=new_revision, extractor="classify:2",
                subject="Etherfuse", event_mention="Started Etherfuse",
                places=("San Diego",),
            )
        ],
    )
    _retire(root, old_claims, "story-a's first moment was re-classified.")
    return {"stable": stable, "old": old_ref, "new": new_ref}


def fixture_landmark(root: Path) -> dict:
    """The landmark mint — the entry id is the durable recorder event id."""
    revision = _rev("promoted-1")
    entry = "entry-7f2a"
    ref = ei.landmark_telling_ref(entry)
    source_id = "conversation:msg-abc123"
    _file(
        root,
        source_id=source_id, revision=revision, extractor="landmark_record:1",
        document_revision=revision,
        recorder_event_id=entry,
        telling_keys=None,
        claims=[
            _claim(
                source_id=source_id, revision=revision, extractor="landmark_record:1",
                subject="Charlee", event_mention="Charlee was born",
                claim_type="date", event_kind="child_born",
                temporal_value="2010-12-21",
            )
        ],
    )
    # The recorder DECLARES its telling; the manifest reads the declaration.
    claim_id = tc.validate_temporal_claim(
        _claim(
            source_id=source_id, revision=revision, extractor="landmark_record:1",
            subject="Charlee", event_mention="Charlee was born",
            claim_type="date", event_kind="child_born",
            temporal_value="2010-12-21",
        )
    )["claim_id"]
    path = ts.receipt_path(root, {"source_id": source_id, "revision": revision}, "landmark_record:1")
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["extractor"][ei.TELLING_KEYS_FIELD] = {claim_id: ref}
    path.write_text(json.dumps(payload, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    return {"telling_ref": ref, "claim_id": claim_id, "entry_id": entry}


# --------------------------------------------------------------------------
# The mints
# --------------------------------------------------------------------------


class TellingRefTests(unittest.TestCase):
    """§3.1 — one mint per source kind, and only three source kinds."""

    def test_the_classifier_mint_is_the_extractors_own(self):
        # Bound, never re-derived: the 12-hex key is over the event's words and
        # a second implementation of that is a second answer to "which moment".
        import classifier_claims as cc

        event = {"title": "Started Etherfuse", "description": "the first office"}
        self.assertEqual(
            ei.classifier_telling_ref(STEM, event), cc.event_source_id(STEM, event)
        )
        self.assertTrue(ei.classifier_telling_ref(STEM, event).startswith("classification:"))

    def test_the_landmark_mint_is_the_entry_id(self):
        self.assertEqual(ei.landmark_telling_ref("entry-7f2a"), "landmark:entry-7f2a")
        with self.assertRaises(ei.EventIdentityError) as caught:
            ei.landmark_telling_ref("  ")
        self.assertEqual(caught.exception.code, "telling_entry_id_required")

    def test_the_conversation_mint_is_the_promoted_id_and_the_event_key(self):
        self.assertEqual(
            ei.conversation_telling_ref("conversation:msg-abc", "0f1e"),
            "conversation:msg-abc#0f1e",
        )
        with self.assertRaises(ei.EventIdentityError) as caught:
            ei.conversation_telling_ref("conversation:msg-abc", "")
        self.assertEqual(caught.exception.code, "telling_event_key_required")

    def test_the_source_kind_is_read_from_the_ref(self):
        self.assertEqual(ei.telling_source_kind("classification:a#b"), "classifier")
        self.assertEqual(ei.telling_source_kind("landmark:e1"), "landmark")
        self.assertEqual(ei.telling_source_kind("conversation:msg-a#b"), "conversation")
        # An unknown extractor is a row nobody groups yet, not an outage.
        self.assertEqual(ei.telling_source_kind("import:thing"), "other")

    def test_a_malformed_ref_is_refused_by_name(self):
        for value in ("", "no-colon", "Classification:A", "has space:x"):
            with self.assertRaises(ei.EventIdentityError, msg=value) as caught:
                ei.validate_telling_ref(value)
            self.assertIn(
                caught.exception.code, ("telling_ref_required", "telling_ref_malformed")
            )

    def test_a_claim_reaches_its_telling_with_no_new_claim_field(self):
        # §9 holds: TemporalClaim gains nothing. The classifier's per-event
        # source id already IS the telling ref.
        self.assertNotIn("telling_ref", tc.TemporalClaim.__dataclass_fields__)
        claim = {"claim_id": "claim:1", "source_ref": {"source_id": "classification:a#b"}}
        self.assertEqual(ei.telling_ref_for_claim(claim), "classification:a#b")

    def test_a_receipt_declaration_outranks_the_source_id(self):
        claim = {"claim_id": "claim:1", "source_ref": {"source_id": "conversation:msg-a"}}
        receipt = {"extractor": ei.declare_tellings(telling_keys={"claim:1": "landmark:e7"})}
        self.assertEqual(ei.telling_ref_for_claim(claim, receipt=receipt), "landmark:e7")

    def test_a_claim_citing_nothing_belongs_to_no_telling(self):
        with self.assertRaises(ei.EventIdentityError) as caught:
            ei.telling_ref_for_claim({"claim_id": "claim:1"})
        self.assertEqual(caught.exception.code, "telling_ref_required")


# --------------------------------------------------------------------------
# Signatures and evidence
# --------------------------------------------------------------------------


class SignatureTests(unittest.TestCase):
    """§3.1(c) — two INDEPENDENT components, zero contradictions."""

    def test_the_four_components_are_frozen(self):
        self.assertEqual(
            ei.SIGNATURE_COMPONENTS,
            ("label_stem", "place_set", "participant_set", "temporal_value"),
        )
        self.assertEqual(ei.MIN_SIGNATURE_AGREEMENT, 2)

    def test_absence_is_neither_agreement_nor_contradiction(self):
        agreeing, contradicting = ei.compare_signatures(
            {"label_stem": "etherfuse", "place_set": []},
            {"label_stem": "etherfuse", "place_set": ["san diego"]},
        )
        self.assertEqual(agreeing, ["label_stem"])
        self.assertEqual(contradicting, [])

    def test_the_owner_is_not_a_participant(self):
        signature = ei.telling_signature(
            [{"subject_mention": "self", "event_mention": "Started Etherfuse"}]
        )
        self.assertEqual(signature["participant_set"], [])

    def test_one_agreeing_component_is_not_evidence(self):
        # The whole G2 finding in one assertion: a single match is a hint.
        old = {"signature": {"label_stem": "etherfuse", "place_set": ["san diego"]}}
        new = {"signature": {"label_stem": "etherfuse", "place_set": ["mesa"]}}
        evidence = ei.rekey_evidence(old, new)
        self.assertEqual(evidence["agreeing"], ["label_stem"])
        self.assertEqual(evidence["contradicting"], ["place_set"])
        self.assertFalse(evidence["sufficient"])

    def test_two_agreeing_components_with_no_contradiction_are(self):
        old = {"signature": {"label_stem": "etherfuse", "place_set": ["san diego"]}}
        new = {"signature": {"label_stem": "etherfuse", "place_set": ["san diego"]}}
        evidence = ei.rekey_evidence(old, new)
        self.assertEqual(evidence["kinds"], ["signature_agreement"])
        self.assertTrue(evidence["sufficient"])

    def test_an_unchanged_locator_carries_it_alone(self):
        locator = {"spans": [[10, 40]], "turn_refs": []}
        evidence = ei.rekey_evidence({"locator": locator}, {"locator": locator})
        self.assertEqual(evidence["kinds"], ["locator"])
        self.assertTrue(evidence["sufficient"])

    def test_a_recorder_event_id_carries_it_alone(self):
        evidence = ei.rekey_evidence(
            {"recorder_event_id": "entry-7f2a"}, {"recorder_event_id": "entry-7f2a"}
        )
        self.assertEqual(evidence["kinds"], ["recorder_event_id"])

    def test_the_locator_is_coordinates_not_words(self):
        # A quote is the model's transcription and moves when the model does.
        locator = ei.telling_locator(
            [{"evidence": [{"quote": "we started it", "start": 3, "end": 9, "turn_ref": "t1"}]}]
        )
        self.assertEqual(locator, {"spans": [[3, 9]], "turn_refs": ["t1"]})
        self.assertIsNone(ei.telling_locator([{"evidence": [{"quote": "we started it"}]}]))


# --------------------------------------------------------------------------
# The transition table
# --------------------------------------------------------------------------


class TransitionTableTests(unittest.TestCase):
    """§3.1's four cases exist in CODE, not only in prose."""

    def test_the_four_design_cases_are_all_present(self):
        cases = {row.case for row in ei.TELLING_TRANSITIONS}
        for case in ("extractor_remint", "reworded", "fragmented", "source_corrected"):
            self.assertIn(case, cases)
        self.assertEqual(set(ei.REKEY_CASES) >= cases, True)

    def test_every_row_names_an_outcome_and_a_bindings_rule(self):
        for row in ei.TELLING_TRANSITIONS:
            self.assertIn(row.outcome, ei.REKEY_OUTCOMES, row.case)
            self.assertTrue(row.bindings, row.case)
            self.assertTrue(row.trigger, row.case)
            if row.diagnostic is not None:
                self.assertIn(row.diagnostic, ei.MANIFEST_DIAGNOSTICS)

    def test_fragmentation_never_carries_bindings(self):
        row = ei.transition_for("fragmented", "retired")
        self.assertIsNotNone(row)
        self.assertIn("never transferred", row.bindings)


# --------------------------------------------------------------------------
# The manifest — the four cases against real receipts
# --------------------------------------------------------------------------


class ManifestCaseTests(unittest.TestCase):
    def test_case_1_an_extractor_remint_leaves_the_ref_and_the_bindings_alone(self):
        root = _vault(self, "ei-c1-remint-")
        fixture = fixture_remint(root)
        manifest = ei.build_telling_manifest(root)
        rows = _rows(manifest)
        self.assertEqual(sorted(rows), [fixture["telling_ref"]])
        row = rows[fixture["telling_ref"]]
        self.assertEqual(row["status"], "active")
        self.assertIsNone(row["rekey_case"])
        self.assertEqual(row["aliases"], [])
        # The claim ids moved (a new extractor version mints new ones) and the
        # ref did not. That is the whole promise of case 1.
        self.assertEqual(row["active_claim_ids"], sorted(fixture["second_claims"]))
        self.assertNotEqual(sorted(fixture["first_claims"]), sorted(fixture["second_claims"]))
        self.assertTrue(set(fixture["first_claims"]) <= set(row["claim_ids"]))

    def test_case_2_a_rewording_with_stable_evidence_rekeys(self):
        root = _vault(self, "ei-c1-reword-")
        fixture = fixture_reworded_evident(root)
        rows = _rows(ei.build_telling_manifest(root))
        old, new = rows[fixture["old"]], rows[fixture["new"]]
        self.assertEqual(old["status"], "retired")
        self.assertEqual(old["rekey_case"], "reworded")
        self.assertEqual(old["superseded_by"], [fixture["new"]])
        self.assertEqual(new["aliases"], [fixture["old"]])
        self.assertEqual(
            sorted(old["rekey_evidence"]["agreeing"]), ["label_stem", "participant_set", "place_set"]
        )
        self.assertEqual(old["rekey_evidence"]["contradicting"], [])

    def test_case_2_CARDINALITY_ALONE_NEVER_REKEYS(self):
        # THE G2 FINDING. Exactly one old unmatched telling, exactly one new
        # unmatched telling, same document, same document revision — and they
        # are about completely different things. A build that re-keys here
        # attaches the wrong story to a confirmed episode, silently.
        root = _vault(self, "ei-c1-bare-")
        fixture = fixture_reworded_bare(root)
        manifest = ei.build_telling_manifest(root)
        rows = _rows(manifest)
        old, new = rows[fixture["old"]], rows[fixture["new"]]
        self.assertEqual(old["superseded_by"], [], "cardinality re-keyed a telling")
        self.assertEqual(new["aliases"], [], "cardinality carried an alias")
        self.assertEqual(old["status"], "retired")
        self.assertEqual(new["status"], "active")
        self.assertIn(ei.REKEY_DIAGNOSTIC, _findings(manifest))
        loud = [row for row in manifest["diagnostics"] if row["finding"] == ei.REKEY_DIAGNOSTIC]
        self.assertEqual(loud[0]["candidate"], fixture["new"])
        self.assertEqual(loud[0]["agreeing"], [])

    def test_case_3_a_split_retires_into_both_fragments_and_carries_nothing(self):
        root = _vault(self, "ei-c1-frag-")
        fixture = fixture_fragmented(root)
        manifest = ei.build_telling_manifest(root)
        rows = _rows(manifest)
        old = rows[fixture["old"]]
        self.assertEqual(old["rekey_case"], "fragmented")
        self.assertEqual(old["superseded_by"], sorted([fixture["left"], fixture["right"]]))
        self.assertEqual(rows[fixture["left"]]["aliases"], [])
        self.assertEqual(rows[fixture["right"]]["aliases"], [])
        self.assertIn(ei.FRAGMENT_DIAGNOSTIC, _findings(manifest))

    def test_case_3_a_merge_inside_one_extraction_carries_nothing_either(self):
        root = _vault(self, "ei-c1-merge-")
        fixture = fixture_merged(root)
        manifest = ei.build_telling_manifest(root)
        rows = _rows(manifest)
        for side in ("left", "right"):
            row = rows[fixture[side]]
            self.assertEqual(row["rekey_case"], "fragmented", side)
            self.assertEqual(row["superseded_by"], [fixture["merged"]], side)
        self.assertEqual(rows[fixture["merged"]]["aliases"], [])
        merged = [
            row for row in manifest["diagnostics"] if row["finding"] == ei.FRAGMENT_DIAGNOSTIC
        ]
        self.assertEqual(len(merged), 2)
        self.assertTrue(all(row.get("merged_with") for row in merged))

    def test_an_untouched_sibling_is_not_a_candidate_successor(self):
        # The cohort rule. A telling that existed ALONGSIDE the retired one is
        # not what replaced it — it is the other moment that was always there.
        root = _vault(self, "ei-c1-sibling-")
        fixture = fixture_stable_sibling(root)
        rows = _rows(ei.build_telling_manifest(root))
        old = rows[fixture["old"]]
        self.assertEqual(old["rekey_case"], "reworded")
        self.assertEqual(old["superseded_by"], [fixture["new"]])
        self.assertEqual(rows[fixture["new"]]["aliases"], [fixture["old"]])
        self.assertEqual(rows[fixture["stable"]]["status"], "active")
        self.assertEqual(rows[fixture["stable"]]["aliases"], [])

    def test_case_4_a_human_source_correction_is_a_new_telling(self):
        root = _vault(self, "ei-c1-corrected-")
        fixture = fixture_corrected(root)
        manifest = ei.build_telling_manifest(root)
        rows = _rows(manifest)
        self.assertEqual(rows[fixture["old"]]["rekey_case"], "source_corrected")
        self.assertEqual(rows[fixture["old"]]["superseded_by"], [])
        self.assertEqual(rows[fixture["new"]]["aliases"], [])
        self.assertIn(ei.CORRECTION_DIAGNOSTIC, _findings(manifest))

    def test_an_undeclared_document_revision_refuses_to_guess(self):
        # The phase's honest gap, and it fails toward "ask", not toward "move".
        root = _vault(self, "ei-c1-undeclared-")
        fixture = fixture_undeclared(root)
        manifest = ei.build_telling_manifest(root)
        rows = _rows(manifest)
        self.assertEqual(rows[fixture["old"]]["rekey_case"], "undeclared_document_revision")
        self.assertEqual(rows[fixture["new"]]["aliases"], [])
        self.assertIn(ei.UNDECLARED_DOCUMENT_REVISION, _findings(manifest))

    def test_a_durable_alias_on_a_binding_survives_the_manifest(self):
        # §3.1's lineage clause: aliases ride the binding records, so deleting
        # this file cannot lose a re-key the person already lives with.
        root = _vault(self, "ei-c1-alias-")
        fixture = fixture_reworded_bare(root)
        binding = {
            "telling_ref": fixture["new"],
            "episode_id": "episode:" + "1" * 24,
            "relation": "same",
            "origin": "confirmed",
            "telling_aliases": [fixture["old"]],
            "created_at": NOW,
        }
        ei.file_event_identity(root, **binding)
        rows = _rows(ei.build_telling_manifest(root))
        self.assertEqual(rows[fixture["new"]]["aliases"], [fixture["old"]])
        self.assertEqual(rows[fixture["old"]]["superseded_by"], [fixture["new"]])
        self.assertEqual(rows[fixture["old"]]["rekey_case"], "durable_alias")


# --------------------------------------------------------------------------
# One telling, one event; eras compose
# --------------------------------------------------------------------------


class OneEventIdentityTests(unittest.TestCase):
    def test_a_telling_naming_two_events_is_a_manifest_build_refusal(self):
        root = _vault(self, "ei-c1-two-")
        fixture_two_events(root)
        with self.assertRaises(ei.EventIdentityError) as caught:
            ei.build_telling_manifest(root)
        self.assertEqual(caught.exception.code, "telling_spans_two_events")

    def test_an_era_ref_is_a_membership_and_never_a_second_event(self):
        root = _vault(self, "ei-c1-era-")
        fixture = fixture_era_composition(root)
        rows = _rows(ei.build_telling_manifest(root))
        within = rows[fixture["within"]]
        self.assertTrue(within["episode_eligible"])
        self.assertEqual(within["era_refs"], [fixture["era_ref"]])
        self.assertEqual(within["event_refs"], [])
        about = rows[fixture["about"]]
        self.assertFalse(about["episode_eligible"])
        self.assertEqual(about["ineligible_reason"], ei.INELIGIBLE_TELLING_IS_AN_ERA)

    def test_two_era_refs_are_still_not_two_events(self):
        claims = [
            {"event_ref": "era:" + "a" * 24},
            {"event_ref": "era:" + "b" * 24},
        ]
        found = ei.assert_one_event_identity("classification:a#b", claims)
        self.assertEqual(found["event_refs"], [])
        self.assertEqual(len(found["era_refs"]), 2)


# --------------------------------------------------------------------------
# The projection's own promises
# --------------------------------------------------------------------------


class ManifestProjectionTests(unittest.TestCase):
    def test_every_row_carries_every_frozen_key(self):
        root = _vault(self, "ei-c1-keys-")
        fixture_remint(root)
        manifest = ei.build_telling_manifest(root)
        self.assertEqual(manifest["schema_version"], ei.MANIFEST_SCHEMA_VERSION)
        self.assertEqual(manifest["rule_version"], ei.IDENTITY_RULE_VERSION)
        for row in manifest["tellings"]:
            self.assertEqual(tuple(sorted(row)), tuple(sorted(ei.TELLING_ROW_KEYS)))

    def test_the_frozen_row_keys_are_pinned(self):
        self.assertEqual(
            ei.TELLING_ROW_KEYS,
            (
                "telling_ref", "source_kind", "source_id", "local_key", "source_path",
                "document_key", "document_revision", "extraction_revisions",
                "extractor_versions", "recorder_event_id", "claim_ids",
                "active_claim_ids", "status", "episode_eligible", "ineligible_reason",
                "event_refs", "era_refs", "signature", "locator", "aliases",
                "superseded_by", "rekey_case", "rekey_evidence", "bound_identity_ids",
            ),
        )

    def test_deleting_the_manifest_and_rebuilding_is_byte_identical(self):
        # §13.1: "the manifest deleted and rebuilt from durable lineage alone
        # is byte-identical". Not "equal" — byte-identical, because the file is
        # what the next reader gets.
        root = _vault(self, "ei-c1-rebuild-")
        fixture_reworded_evident(root)
        fixture_fragmented(root)
        first = ei.rebuild_telling_manifest(root)
        path = ts.store_path(root, ei.TELLING_MANIFEST_FILE)
        original = path.read_bytes()
        path.unlink()
        second = ei.rebuild_telling_manifest(root)
        self.assertEqual(path.read_bytes(), original)
        self.assertEqual(ei.telling_manifest_bytes(first), ei.telling_manifest_bytes(second))

    def test_nothing_in_the_manifest_is_a_clock(self):
        # The reason the rebuild above is arithmetic rather than luck.
        root = _vault(self, "ei-c1-clockless-")
        fixture_remint(root)
        blob = ei.telling_manifest_bytes(ei.build_telling_manifest(root))
        for stamp in ("created_at", "built_at", "generated_at", "published_at"):
            self.assertNotIn(stamp, blob)

    def test_a_manifest_reads_back_as_it_was_written(self):
        root = _vault(self, "ei-c1-roundtrip-")
        fixture_remint(root)
        written = ei.rebuild_telling_manifest(root)
        self.assertEqual(ei.read_telling_manifest(root), written)

    def test_an_unparseable_manifest_is_a_named_refusal(self):
        root = _vault(self, "ei-c1-broken-")
        path = ts.store_path(root, ei.TELLING_MANIFEST_FILE)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{not json", encoding="utf-8")
        with self.assertRaises(ei.EventIdentityError) as caught:
            ei.read_telling_manifest(root)
        self.assertEqual(caught.exception.code, "telling_manifest_unreadable")

    def test_a_landmark_telling_is_keyed_by_its_durable_entry_id(self):
        root = _vault(self, "ei-c1-landmark-")
        fixture = fixture_landmark(root)
        rows = _rows(ei.build_telling_manifest(root))
        row = rows[fixture["telling_ref"]]
        self.assertEqual(row["source_kind"], "landmark")
        self.assertEqual(row["recorder_event_id"], fixture["entry_id"])
        self.assertEqual(row["active_claim_ids"], [fixture["claim_id"]])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
