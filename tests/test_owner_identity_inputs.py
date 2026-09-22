"""v328 — ONE owner identity behind every publish seat (ADR 0021's failure class).

Before v328 three seats folded with three different owner-identity inputs:
`timeline.publish_calculated_timeline` loaded the roster and the profile's
`name`/`full_name`, while a Mirror resolution's republish and the frame-display
command called `temporal_publication.publish` with neither — so on a vault whose
roster listed the owner, which act republished last decided whether the owner's
own nodes were `owner` or `other_person`. Now `publish()` reads both through
`temporal_publication.owner_identity_inputs` when a caller names neither, and
stamps `owner_identity_digest` into the envelope so a reader can tell.

Synthetic data only; every vault is a throwaway directory, never ~/Workspace/dave.
"""
from __future__ import annotations

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "system"))

import resolver  # noqa: E402
import temporal_claims as tc  # noqa: E402
import temporal_projection as tp  # noqa: E402
import temporal_publication as pub  # noqa: E402
import temporal_store as ts  # noqa: E402
import timeline  # noqa: E402

NOW = "2026-09-01T12:00:00Z"
#: The roster lists the owner under the spelling the claims use ("Pat"), a
#: stranger, and a person who happens to bear the owner's MIDDLE name.
ROSTER = {"version": 1, "type": "person", "entities": [
    {"name": "Pat", "slug": "pat", "aliases": ["Pat Quincy Example"]},
    {"name": "Robin", "slug": "robin", "aliases": []},
    {"name": "Quincy", "slug": "quincy", "aliases": []},
]}
PROFILE = "name: Pat\nfull_name: Pat Quincy Example\ntimezone: UTC\n"
OWNER_NAMES = ("Pat", "Pat Quincy Example")


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


class OwnerIdentityVault(unittest.TestCase):
    """A vault whose roster lists the owner and whose profile names him."""

    def setUp(self) -> None:
        self.vault = self.make_vault()

    def make_vault(self, *, profile: str | None = PROFILE, roster: dict | None = ROSTER) -> Path:
        vault = Path(tempfile.mkdtemp(prefix="lifehug-owner-identity-"))
        self.addCleanup(shutil.rmtree, vault, ignore_errors=True)
        (vault / "state" / "entity_rosters").mkdir(parents=True)
        if roster is not None:
            (vault / "state" / "entity_rosters" / "person.json").write_text(json.dumps(roster))
        if profile is not None:
            (vault / "profile.yaml").write_text(profile)
        for mention, label, seed in (("Pat", "Pat's promotion", "s1"),
                                     ("Robin", "Robin's promotion", "s2"),
                                     ("Quincy", "Quincy's promotion", "s3")):
            row = claim(mention, label, seed)
            ts.write_receipt(vault, {
                "source_ref": dict(row["source_ref"]),
                "extractor_version": "classifier:1",
                "claims": [row],
            })
        return vault

    @staticmethod
    def subjects(payload: dict) -> dict:
        """`node_id -> (occurrence_subject_scope, subject_refs)`, the two
        fields the owner-name rule moves."""
        return {row["node_id"]: (row.get("occurrence_subject_scope"),
                                 tuple(row.get("subject_refs") or ()))
                for row in payload["nodes"]}

    @staticmethod
    def scopes(payload: dict) -> dict:
        return {row["label"]: row["occurrence_subject_scope"] for row in payload["nodes"]}


class OneDefinitionTests(OwnerIdentityVault):
    def test_the_helper_reads_the_vaults_roster_and_whole_spellings(self):
        roster, names = pub.owner_identity_inputs(self.vault)
        self.assertEqual(names, OWNER_NAMES)
        self.assertEqual([e["slug"] for e in roster["entities"]], ["pat", "robin", "quincy"])

    def test_every_seat_folds_the_same_subjects(self):
        """(a) `publish()` with nothing named, `timeline.publish_calculated_
        timeline`, the Mirror republish shape and the frame-display shape all
        land the same `occurrence_subject_scope` / `subject_refs`."""
        seats = {
            "publish": lambda vault: pub.publish(vault, now=NOW),
            "timeline": timeline.publish_calculated_timeline,
            "mirror": lambda vault: pub.publish(vault, now=NOW),      # mirror_work.py
            "frame_display": lambda vault: pub.publish(vault),        # lifehug.py
        }
        folded, digests = {}, set()
        for seat, act in seats.items():
            vault = self.make_vault()
            act(vault)
            payload = pub.read_projection(vault)
            folded[seat] = json.dumps(self.subjects(payload), sort_keys=True)
            digests.add(payload["owner_identity_digest"])
            scopes = self.scopes(payload)
            self.assertEqual(scopes["Pat's promotion"], "owner", seat)
            self.assertEqual(scopes["Robin's promotion"], "other_person", seat)
        self.assertEqual(len(set(folded.values())), 1, folded)
        self.assertEqual(len(digests), 1, digests)

    def test_an_explicit_empty_identity_is_still_honoured(self):
        """`()` keeps meaning "none": the owner becomes a stranger, and the
        envelope says so — the digest is the digest of no identity."""
        pub.publish(self.vault, now=NOW, roster_snapshot=ROSTER, owner_names=())
        payload = pub.read_projection(self.vault)
        self.assertEqual(self.scopes(payload)["Pat's promotion"], "other_person")
        self.assertEqual(payload["owner_identity_digest"], pub.owner_identity_digest((), ()))

    def test_a_vault_without_a_profile_folds_with_no_owner_names(self):
        vault = self.make_vault(profile=None, roster=None)
        roster, names = pub.owner_identity_inputs(vault)
        self.assertEqual(names, ())
        self.assertFalse(roster.get("entities") if isinstance(roster, dict) else roster)


class MiddleNameTests(OwnerIdentityVault):
    def test_a_middle_name_never_enters_the_set(self):
        """(b) WHOLE spellings only, as `tests/test_owner_name_subject.py` pins."""
        names = pub.owner_names_from_profile({"name": "Pat", "full_name": "Pat Quincy Example"})
        self.assertEqual(names, OWNER_NAMES)
        self.assertNotIn("Quincy", names)
        self.assertNotIn("Example", names)

    def test_the_fold_leaves_the_namesake_of_the_middle_name_a_stranger(self):
        pub.publish(self.vault, now=NOW)
        self.assertEqual(self.scopes(pub.read_projection(self.vault))["Quincy's promotion"],
                         "other_person")

    def test_the_resolver_variants_add_first_words_and_nothing_else(self):
        variants = pub.owner_name_variants(("Pat", "Patrick Q. Example"))
        self.assertEqual(variants, ("Pat", "Patrick Q. Example", "Patrick"))
        self.assertEqual(pub.owner_name_variants(OWNER_NAMES), OWNER_NAMES)
        self.assertEqual(pub.owner_name_variants(()), ())

    def test_the_resolver_reads_the_same_definition(self):
        pub.publish(self.vault, now=NOW)
        sp = resolver.spine(self.vault, pub.read_projection(self.vault))
        self.assertEqual(sp["owner_names"], ["pat", "pat quincy example"])
        self.assertEqual(sp["owner_name"], "Pat Quincy Example")


class EnvelopeDigestTests(OwnerIdentityVault):
    def test_the_envelope_carries_the_digest(self):
        """(c) additive envelope field; sha256 over the sorted whole spellings
        and the roster refs they resolve to."""
        pub.publish(self.vault, now=NOW)
        payload = pub.read_projection(self.vault)
        want = pub.owner_identity_digest(ROSTER, OWNER_NAMES)
        self.assertEqual(payload["owner_identity_digest"], want)
        self.assertNotEqual(want, pub.owner_identity_digest((), ()))
        self.assertEqual(want, pub.owner_identity_digest(ROSTER, tuple(reversed(OWNER_NAMES))))

    def test_the_digest_is_part_of_the_rebuild_signature_not_excluded_metadata(self):
        pub.publish(self.vault, now=NOW)
        payload = pub.read_projection(self.vault)
        self.assertIn("owner_identity_digest", pub.rebuild_signature(payload))
        self.assertNotIn("owner_identity_digest", pub.EXCLUDED_ENVELOPE_KEYS)
        # O-E1b: a published key is served or excused; this one is excused.
        self.assertIn("owner_identity_digest", pub.published_block_keys())
        self.assertNotIn("owner_identity_digest", pub.view_block_keys())

    def test_verify_reproduces_a_default_publish(self):
        pub.publish(self.vault, now=NOW)
        report = pub.verify(self.vault, now=NOW)
        self.assertTrue(report["identical"], report)

    def test_the_republish_shortcut_keys_on_the_same_identity(self):
        """A second seat republishing an unchanged vault mints no generation:
        both seats digest the same inputs, so v318's shortcut fires."""
        first = pub.publish(self.vault, now=NOW)
        second = timeline.publish_calculated_timeline(self.vault)
        self.assertEqual(second["generation"], first["generation"])
        self.assertTrue(second["unchanged"])


if __name__ == "__main__":
    unittest.main()
