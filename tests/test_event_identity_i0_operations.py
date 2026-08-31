"""Event identity I0 — contract C2: episode operations and the binding lifecycle.

Controlling design: lifehug-platform `docs/design/event-identity.md` v4 §3.2
and §3.3, with the §5.8 lifecycle matrix rows **1, 2, 3, 4 and 10** proved
here at the RECORD level (no fold — the fold is I1). Contract spec:
`docs/contracts/event-identity-i0-records.md`.

**Fixture inventory** (all synthetic; NOTHING here reads ~/Workspace/dave):

==============================  ===========================================
``fixture_create``              matrix row 1 — two standalone tellings become
                                one episode through ONE create envelope
``fixture_adopt``               matrix row 3 — the first human reference
                                adopts a deterministic episode
``fixture_rule_bump``           matrix row 7 at record level — a new rule
                                version over one adopted and one unadopted
                                episode
``fixture_proposal``            matrix row 2's record half — a proposal and
                                the confirmation that supersedes it
``fixture_split``               §3.2 — a split names each departing telling
                                and its destination
``fixture_merge``               §3.2 — a merge absorbs an episode into an
                                alias that resolves forever
``fixture_incomplete``          §3.2/G4 — an envelope naming a binding that
                                is not on disk
==============================  ===========================================

Every negative test here was run against a build with its guard removed and
SEEN failing first; the evidence table is in the PR body.
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "system"))
sys.path.insert(0, str(ROOT / "tests"))

import episode_fold_contract as efc  # noqa: E402
import event_identity as ei  # noqa: E402
import temporal_store as ts  # noqa: E402
from tempdirs import root_parent_tmp  # noqa: E402

NOW = "2026-08-30T09:00:00Z"
LATER = "2026-09-01T17:30:00Z"

TELLING_A = "classification:story-a#aaaa1111aaaa"
TELLING_B = "classification:story-b#bbbb2222bbbb"
TELLING_C = "classification:story-c#cccc3333cccc"


def _vault(case: unittest.TestCase, prefix: str) -> Path:
    root = root_parent_tmp(case, ROOT, prefix=prefix)
    (root / "state").mkdir(parents=True, exist_ok=True)
    (root / "sources").mkdir(parents=True, exist_ok=True)
    return root


def _files(root: Path, *, under: str) -> dict:
    base = root / under
    if not base.is_dir():
        return {}
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(base.rglob("*.json"))
    }


def _create_plan(
    members: tuple[str, ...] = (TELLING_A, TELLING_B),
    *,
    rule_version: str = ei.IDENTITY_RULE_VERSION,
    authority: str = "deterministic",
    origin: str = "deterministic",
    created_at: str = NOW,
) -> dict:
    """The R1 create, as it will be issued: one envelope, its own bindings.

    Written as a plan the test can replay because that is precisely the
    property under test — a binder re-run on the same durable inputs computes
    this same dictionary with no stored state to consult.
    """
    operation_id = ei.operation_digest(
        authority=authority, op="create", rule_version=rule_version, member_refs=members
    )
    episode_id = ei.episode_id_for(operation_id)
    bindings = [
        {
            "telling_ref": ref,
            "episode_id": episode_id,
            "relation": "same",
            "origin": origin,
            "rule_version": rule_version,
            "rule_id": "R1",
            "operation_id": operation_id,
            "created_at": created_at,
        }
        for ref in members
    ]
    binding_ids = [ei.validate_event_identity(row)["identity_id"] for row in bindings]
    operation = {
        "authority": authority,
        "op": "create",
        "episode_id": episode_id,
        "members": list(members),
        "creates_binding_ids": binding_ids,
        "canonical_event_kind": "job",
        "rule_version": rule_version,
        "created_at": created_at,
    }
    return {
        "operation": operation,
        "bindings": bindings,
        "operation_id": operation_id,
        "episode_id": episode_id,
        "binding_ids": binding_ids,
    }


def fixture_create(root: Path, **kwargs: object) -> dict:
    plan = _create_plan(**kwargs)  # type: ignore[arg-type]
    filed = ei.file_operation_envelope(
        root, operation=plan["operation"], bindings=plan["bindings"]
    )
    return {**plan, "filed": filed}


def fixture_adopt(root: Path) -> dict:
    plan = fixture_create(root)
    record = ei.adopt_envelope(
        episode_id=plan["episode_id"],
        creation_canonical_inputs=plan["filed"]["operation"]["canonical_inputs"],
        source_ref="sources/conversations/msg-abc.md",
        created_at=LATER,
    )
    filed, created = ei.file_adopt_envelope(
        root,
        episode_id=plan["episode_id"],
        creation_canonical_inputs=plan["filed"]["operation"]["canonical_inputs"],
        source_ref="sources/conversations/msg-abc.md",
        created_at=LATER,
    )
    return {**plan, "adopt": record, "filed_adopt": filed, "adopt_created": created}


def fixture_proposal(root: Path) -> dict:
    episode_id = "episode:" + "1" * 24
    proposal, _ = ei.file_event_identity(
        root,
        telling_ref=TELLING_C,
        episode_id=episode_id,
        relation="same",
        origin="proposed",
        rule_id="R3",
        created_at=NOW,
    )
    return {"episode_id": episode_id, "proposal": proposal}


def fixture_split(root: Path) -> dict:
    plan = fixture_create(root)
    departing = plan["binding_ids"][0]
    leaving = ei.validate_event_identity(plan["bindings"][0])["telling_ref"]
    operation = {
        "authority": "human",
        "op": "split",
        "episode_id": plan["episode_id"],
        "acted_on_episode_ids": [plan["episode_id"]],
        "supersedes_binding_ids": [departing],
        "destinations": {leaving: ei.STANDALONE_DESTINATION},
        "created_at": LATER,
    }
    return {**plan, "split": operation, "departing": departing, "leaving": leaving}


def fixture_merge(root: Path) -> dict:
    survivor = fixture_create(root, members=(TELLING_A, TELLING_B))
    absorbed = fixture_create(root, members=(TELLING_C,))
    operation = {
        "authority": "human",
        "op": "merge",
        "episode_id": survivor["episode_id"],
        "absorbed_episode_id": absorbed["episode_id"],
        "acted_on_episode_ids": [survivor["episode_id"], absorbed["episode_id"]],
        "members": [TELLING_C],
        "supersedes_binding_ids": absorbed["binding_ids"],
        "aliases_created": [absorbed["episode_id"]],
        "created_at": LATER,
    }
    return {"survivor": survivor, "absorbed": absorbed, "merge": operation}


# --------------------------------------------------------------------------
# Frozen shapes
# --------------------------------------------------------------------------


class FrozenShapeTests(unittest.TestCase):
    """The golden test the design asks for by name (§3.2, §3.3)."""

    def test_the_binding_identity_keys_are_frozen(self):
        self.assertEqual(
            ei.IDENTITY_IDENTITY_KEYS,
            ("telling_ref", "episode_id", "relation", "rule_version", "supersedes"),
        )

    def test_the_operation_identity_keys_are_frozen(self):
        self.assertEqual(
            ei.OPERATION_IDENTITY_KEYS,
            ("authority", "op", "rule_version", "member_refs_sorted", "acted_on_episode_ids"),
        )

    def test_the_vocabularies_have_one_home(self):
        # ADR 0021 applied to this program's own words. C3
        # (`episode_fold_contract`) owns the shared vocabulary; this module
        # IMPORTS it and adds only what the RECORD needs that the fold does
        # not: the split departure.
        self.assertIs(ei.RELATIONS, efc.RELATIONS)
        self.assertIs(ei.ORIGINS, efc.ORIGINS)
        self.assertIs(ei.GROUPING_RELATION, efc.GROUPING_RELATION)
        self.assertIs(ei.GROUPING_ORIGINS, efc.GROUPING_ORIGINS)
        self.assertIs(ei.IDENTITY_RULE_VERSION, efc.IDENTITY_RULE_VERSION)
        self.assertEqual(ei.RELATIONS, ("same", "part_of", "related", "not_same"))
        self.assertEqual(ei.SPLIT_DEPARTURE_RELATION, "none")
        self.assertEqual(ei.BINDING_RELATIONS, ei.RELATIONS + ("none",))
        self.assertEqual(ei.OPERATIONS, ("create", "merge", "split", "adopt", "retitle"))
        self.assertEqual(ei.AUTHORITIES, ("human", "deterministic"))
        # `unknown` is an epistemic state about a pair, never a relation (§2.2).
        self.assertNotIn("unknown", ei.BINDING_RELATIONS)
        # Derived, so a fifth origin upstream cannot leave a stale partition.
        self.assertEqual(
            sorted(ei.HUMAN_ORIGINS + ei.MACHINE_ORIGINS), sorted(ei.ORIGINS)
        )

    def test_the_shared_vocabulary_is_assigned_in_exactly_one_module(self):
        # The class guard, widened from #296's `IDENTITY_RULE_VERSION` sweep to
        # every name the three event-identity modules share. Scoped to this
        # program's modules on purpose: `chronology.RELATIONS` is a different
        # word about a different thing and is none of this guard's business.
        import re

        program = (
            # I2 (the binder) joined this program and joins this sweep with
            # it: the guard's value is that it FAILS when a new module gives
            # a shared word a second home, so a new module has to be in it.
            "episode_binder.py",
            "episode_fold.py",
            "episode_fold_contract.py",
            "episode_routing_contract.py",
            "event_identity.py",
        )
        for name in ("IDENTITY_RULE_VERSION", "RELATIONS", "ORIGINS",
                     "GROUPING_RELATION", "GROUPING_ORIGINS"):
            pattern = re.compile(rf"^{name}\s*=", re.MULTILINE)
            homes = sorted(
                module for module in program
                if pattern.search((ROOT / "system" / module).read_text("utf-8"))
            )
            self.assertEqual(
                homes, ["episode_fold_contract.py"],
                f"{name} has one home; every other module imports it",
            )

    def test_the_digest_payload_is_exactly_the_key_list(self):
        payload = ei.canonical_operation_inputs(
            authority="deterministic", op="create", member_refs=[TELLING_B, TELLING_A]
        )
        self.assertEqual(tuple(payload), ei.OPERATION_IDENTITY_KEYS)
        self.assertEqual(payload["member_refs_sorted"], sorted([TELLING_A, TELLING_B]))
        binding = ei.binding_identity_payload(
            telling_ref=TELLING_A, episode_id="episode:" + "0" * 24, relation="same"
        )
        self.assertEqual(tuple(binding), ei.IDENTITY_IDENTITY_KEYS)

    def test_every_code_the_module_raises_is_enumerated(self):
        # The `temporal_claims.ERROR_CODES` discipline, derived from source
        # rather than maintained by hand: a refusal nobody can enumerate is a
        # refusal a dashboard silently drops.
        import ast

        source = (ROOT / "system" / "event_identity.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        raised: set[str] = set()
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            name = getattr(node.func, "id", None) or getattr(node.func, "attr", None)
            if name == "_require" and len(node.args) >= 2:
                literal = node.args[1]
                if isinstance(literal, ast.Constant) and isinstance(literal.value, str):
                    raised.add(literal.value)
            if name == "EventIdentityError" and node.args:
                literal = node.args[0]
                if isinstance(literal, ast.Constant) and isinstance(literal.value, str):
                    raised.add(literal.value)
        self.assertTrue(raised, "the AST sweep found no refusals at all")
        self.assertEqual(
            sorted(raised - set(ei.EVENT_IDENTITY_ERROR_CODES)),
            [],
            "a refusal the module raises is missing from EVENT_IDENTITY_ERROR_CODES",
        )

    def test_the_error_codes_are_enumerated_and_unique(self):
        self.assertEqual(
            len(ei.EVENT_IDENTITY_ERROR_CODES), len(set(ei.EVENT_IDENTITY_ERROR_CODES))
        )
        for code in ("identity_envelope_incomplete", "identity_members_disagree",
                     "identity_unsuperseded_twin", "telling_spans_two_events"):
            self.assertIn(code, ei.EVENT_IDENTITY_ERROR_CODES)


# --------------------------------------------------------------------------
# Deterministic identity (G1)
# --------------------------------------------------------------------------

    def test_a_creates_episode_id_is_derived_and_a_supplied_one_is_replaced(self):
        # The `claim_id` convention: the derivation is the authority.
        record = ei.validate_episode_operation(
            {
                "authority": "deterministic",
                "op": "create",
                "members": [TELLING_A],
                "episode_id": "episode:" + "f" * 24,
            }
        )
        self.assertEqual(record["episode_id"], ei.episode_id_for(record["operation_id"]))
        self.assertNotEqual(record["episode_id"], "episode:" + "f" * 24)

    def test_the_two_doors_refuse_a_non_mapping_by_name(self):
        with self.assertRaises(ei.EventIdentityError) as caught:
            ei.validate_episode_operation("not a mapping")
        self.assertEqual(caught.exception.code, "operation_not_a_mapping")
        with self.assertRaises(ei.EventIdentityError) as caught:
            ei.validate_event_identity([])
        self.assertEqual(caught.exception.code, "identity_not_a_mapping")

    def test_a_malformed_binding_id_is_refused_by_its_own_name(self):
        with self.assertRaises(ei.EventIdentityError) as caught:
            ei.validate_episode_operation(
                {"authority": "human", "op": "adopt", "episode_id": "episode:" + "1" * 24,
                 "creates_binding_ids": ["not-a-binding"]}
            )
        self.assertEqual(caught.exception.code, "identity_binding_id_malformed")


class DeterministicIdentityTests(unittest.TestCase):
    def test_the_operation_id_is_semantic_inputs_and_nothing_else(self):
        first = ei.operation_digest(
            authority="deterministic", op="create", member_refs=[TELLING_A, TELLING_B]
        )
        second = ei.operation_digest(
            authority="deterministic", op="create", member_refs=[TELLING_B, TELLING_A]
        )
        self.assertEqual(first, second)
        self.assertTrue(first.startswith("eop:"))

    def test_every_semantic_input_moves_the_id(self):
        base = dict(authority="deterministic", op="create", member_refs=[TELLING_A])
        original = ei.operation_digest(**base)
        self.assertNotEqual(original, ei.operation_digest(**{**base, "authority": "human"}))
        self.assertNotEqual(original, ei.operation_digest(**{**base, "op": "merge"}))
        self.assertNotEqual(
            original, ei.operation_digest(**{**base, "rule_version": "event-identity:2"})
        )
        self.assertNotEqual(
            original, ei.operation_digest(**{**base, "member_refs": [TELLING_A, TELLING_B]})
        )
        self.assertNotEqual(
            original,
            ei.operation_digest(**{**base, "acted_on_episode_ids": ["episode:" + "0" * 24]}),
        )

    def test_the_episode_id_is_the_creating_operation(self):
        operation_id = ei.operation_digest(
            authority="deterministic", op="create", member_refs=[TELLING_A]
        )
        self.assertEqual(
            ei.episode_id_for(operation_id),
            ei.episode_id_at_rule_version(
                authority="deterministic",
                rule_version=ei.IDENTITY_RULE_VERSION,
                member_refs=[TELLING_A],
            ),
        )
        self.assertTrue(ei.episode_id_for(operation_id).startswith("episode:"))

    def test_two_adopts_of_two_episodes_do_not_collide(self):
        # `_implicit_acted_on` exists for exactly this: an op that acts on an
        # episode digests that episode even if the caller did not repeat it.
        left = ei.validate_episode_operation(
            {"authority": "human", "op": "adopt", "episode_id": "episode:" + "1" * 24}
        )
        right = ei.validate_episode_operation(
            {"authority": "human", "op": "adopt", "episode_id": "episode:" + "2" * 24}
        )
        self.assertNotEqual(left["operation_id"], right["operation_id"])


# --------------------------------------------------------------------------
# Matrix row 1 — create, then replay
# --------------------------------------------------------------------------


class CreateEnvelopeTests(unittest.TestCase):
    def test_row_1_two_standalone_tellings_become_one_episode_in_one_envelope(self):
        root = _vault(self, "ei-c2-create-")
        fixture = fixture_create(root)
        operation = fixture["filed"]["operation"]
        self.assertEqual(operation["op"], "create")
        self.assertEqual(operation["members"], sorted([TELLING_A, TELLING_B]))
        self.assertEqual(len(operation["creates_binding_ids"]), 2)
        self.assertEqual(operation["episode_id"], fixture["episode_id"])
        # Both bindings and the operation, one envelope, no dangling per-telling
        # path that could strand the pair (audit A3).
        self.assertEqual(len(ei.load_event_identities(root)), 2)
        self.assertEqual(len(ei.load_episode_operations(root)), 1)

    def test_row_1_replaying_the_operation_creates_nothing(self):
        root = _vault(self, "ei-c2-replay-")
        fixture_create(root)
        before = _files(root, under="state")
        again = fixture_create(root)
        self.assertFalse(again["filed"]["operation_created"])
        self.assertEqual(_files(root, under="state"), before)

    def test_the_storage_split_follows_authority_and_origin(self):
        root = _vault(self, "ei-c2-split-dirs-")
        fixture_create(root)
        fixture_create(root, authority="human", origin="confirmed", members=(TELLING_C,))
        state = sorted(_files(root, under="state"))
        sources = sorted(_files(root, under="sources"))
        self.assertTrue(all(path.startswith(ei.IDENTITY_STATE_DIR) for path in state), state)
        self.assertTrue(all(path.startswith(ei.IDENTITY_SOURCES_DIR) for path in sources), sources)
        self.assertTrue(any(ei.STATE_BINDINGS_DIR in path for path in state))
        self.assertTrue(any(ei.STATE_OPERATIONS_DIR in path for path in state))
        self.assertTrue(any(ei.HUMAN_BINDINGS_DIR in path for path in sources))
        self.assertTrue(any(ei.HUMAN_OPERATIONS_DIR in path for path in sources))

    def test_a_create_with_no_members_is_refused(self):
        with self.assertRaises(ei.EventIdentityError) as caught:
            ei.validate_episode_operation({"authority": "deterministic", "op": "create"})
        self.assertEqual(caught.exception.code, "operation_needs_members")

    def test_members_is_an_audit_copy_and_a_drifted_one_is_refused(self):
        # Audit F2: two truths about membership is the defect. `members` is the
        # envelope's audit copy; the bindings are the authority; disagreement is
        # a write-time refusal rather than a silent preference.
        root = _vault(self, "ei-c2-audit-")
        plan = _create_plan()
        plan["operation"]["members"] = [TELLING_A, TELLING_C]
        with self.assertRaises(ei.EventIdentityError) as caught:
            ei.file_operation_envelope(
                root, operation=plan["operation"], bindings=plan["bindings"]
            )
        self.assertEqual(caught.exception.code, "identity_members_disagree")


# --------------------------------------------------------------------------
# Matrix row 3 — adoption
# --------------------------------------------------------------------------


class AdoptionTests(unittest.TestCase):
    def test_row_3_the_first_human_reference_adopts_the_episode(self):
        root = _vault(self, "ei-c2-adopt-")
        fixture = fixture_adopt(root)
        self.assertTrue(fixture["adopt_created"])
        self.assertEqual(fixture["adopt"]["op"], "adopt")
        self.assertEqual(fixture["adopt"]["authority"], "human")
        self.assertEqual(
            fixture["adopt"]["adopted_canonical_inputs"]["member_refs_sorted"],
            sorted([TELLING_A, TELLING_B]),
        )
        self.assertTrue(ei.is_adopted(root, fixture["episode_id"]))
        # It landed under sources, which is the whole point of adopting.
        self.assertTrue(
            any(ei.HUMAN_OPERATIONS_DIR in path for path in _files(root, under="sources"))
        )

    def test_row_3_the_adopted_id_survives_deleting_every_cache(self):
        root = _vault(self, "ei-c2-adopt-delete-")
        fixture = fixture_adopt(root)
        import shutil

        shutil.rmtree(root / "state" / "temporal_claims")
        self.assertTrue(ei.is_adopted(root, fixture["episode_id"]))
        surviving = ei.load_episode_operations(root)
        self.assertEqual([row["op"] for row in surviving], ["adopt"])
        self.assertEqual(surviving[0]["episode_id"], fixture["episode_id"])
        # And it still says WHY that id is that id, with every cache gone.
        self.assertEqual(
            surviving[0]["adopted_canonical_inputs"]["member_refs_sorted"],
            sorted([TELLING_A, TELLING_B]),
        )

    def test_re_adopting_is_a_no_op(self):
        root = _vault(self, "ei-c2-readopt-")
        fixture = fixture_adopt(root)
        _record, created = ei.file_adopt_envelope(
            root,
            episode_id=fixture["episode_id"],
            creation_canonical_inputs=fixture["filed"]["operation"]["canonical_inputs"],
            created_at="2027-01-01T00:00:00Z",
        )
        self.assertFalse(created)

    def test_an_unadopted_episode_reads_as_unadopted(self):
        root = _vault(self, "ei-c2-unadopted-")
        fixture = fixture_create(root)
        self.assertFalse(ei.is_adopted(root, fixture["episode_id"]))


# --------------------------------------------------------------------------
# Matrix row 7 — the rule version moves
# --------------------------------------------------------------------------


class RuleVersionTests(unittest.TestCase):
    def test_row_7_the_new_rule_computes_the_old_id_from_the_old_formula(self):
        root = _vault(self, "ei-c2-rulebump-")
        adopted = fixture_adopt(root)
        unadopted = fixture_create(root, members=(TELLING_C,))

        # The new rule version, re-deriving the SAME grouping. It needs the old
        # id and has no stored state to look it up in — so it recomputes it.
        old_id = ei.episode_id_at_rule_version(
            authority="deterministic",
            rule_version=ei.IDENTITY_RULE_VERSION,
            member_refs=[TELLING_C],
        )
        self.assertEqual(old_id, unadopted["episode_id"])

        successor = _create_plan(members=(TELLING_C,), rule_version="event-identity:2")
        successor["operation"]["aliases_created"] = [old_id]
        record, created = ei.file_episode_operation(root, **successor["operation"])
        self.assertTrue(created)
        self.assertEqual(record["aliases_created"], [old_id])
        self.assertNotEqual(record["episode_id"], old_id)

        # And the ADOPTED episode is untouched: a new rule may propose against
        # it, and may not move it.
        self.assertTrue(ei.is_adopted(root, adopted["episode_id"]))
        proposal, _ = ei.file_event_identity(
            root,
            telling_ref=TELLING_A,
            episode_id=record["episode_id"],
            relation="same",
            origin="proposed",
            rule_version="event-identity:2",
            created_at=LATER,
        )
        self.assertEqual(proposal["origin"], "proposed")
        self.assertTrue(
            proposal["relative_path"].startswith(ei.STATE_BINDINGS_DIR),
            proposal["relative_path"],
        )

    def test_a_rule_version_re_derivation_files_with_supersedes_and_no_conflict(self):
        root = _vault(self, "ei-c2-supersede-")
        first, _ = ei.file_event_identity(
            root,
            telling_ref=TELLING_A,
            episode_id="episode:" + "3" * 24,
            relation="same",
            origin="deterministic",
            created_at=NOW,
        )
        second, _ = ei.file_event_identity(
            root,
            telling_ref=TELLING_A,
            episode_id="episode:" + "3" * 24,
            relation="same",
            origin="deterministic",
            rule_version="event-identity:2",
            supersedes=first["identity_id"],
            created_at=LATER,
        )
        self.assertNotEqual(first["identity_id"], second["identity_id"])
        active = ei.validate_identity_set(ei.load_event_identities(root))
        self.assertEqual([row["identity_id"] for row in active], [second["identity_id"]])


# --------------------------------------------------------------------------
# Matrix row 10 — delete the deterministic layer and re-run
# --------------------------------------------------------------------------


class DeleteAndRerunTests(unittest.TestCase):
    def test_row_10_re_running_reproduces_every_id_byte_for_byte(self):
        root = _vault(self, "ei-c2-rerun-")
        first = fixture_create(root)
        adopted = ei.adopt_envelope(
            episode_id=first["episode_id"],
            creation_canonical_inputs=first["filed"]["operation"]["canonical_inputs"],
            created_at=LATER,
        )
        ei.file_adopt_envelope(
            root,
            episode_id=first["episode_id"],
            creation_canonical_inputs=first["filed"]["operation"]["canonical_inputs"],
            created_at=LATER,
        )
        before_state = _files(root, under="state")
        before_sources = _files(root, under="sources")
        self.assertTrue(before_state)

        import shutil

        shutil.rmtree(root / "state" / "temporal_claims")
        self.assertEqual(_files(root, under="state"), {})
        # Nothing under sources/ was touched — that is the other half of row 10.
        self.assertEqual(_files(root, under="sources"), before_sources)

        second = fixture_create(root)
        self.assertEqual(second["operation_id"], first["operation_id"])
        self.assertEqual(second["episode_id"], first["episode_id"])
        self.assertEqual(second["binding_ids"], first["binding_ids"])
        self.assertEqual(_files(root, under="state"), before_state)
        self.assertEqual(
            ei.identity_assertion_view(second["filed"]["operation"]),
            ei.identity_assertion_view(first["filed"]["operation"]),
        )
        # And what the person did still points at the same identity.
        self.assertEqual(adopted["episode_id"], second["episode_id"])
        self.assertTrue(ei.is_adopted(root, second["episode_id"]))

    def test_a_clock_is_annotation_and_never_identity(self):
        early = ei.validate_episode_operation(
            {"authority": "deterministic", "op": "create", "members": [TELLING_A],
             "created_at": NOW}
        )
        late = ei.validate_episode_operation(
            {"authority": "deterministic", "op": "create", "members": [TELLING_A],
             "created_at": LATER}
        )
        self.assertEqual(early["operation_id"], late["operation_id"])
        self.assertEqual(ei.identity_assertion_view(early), ei.identity_assertion_view(late))
        for key in ei.ANNOTATION_KEYS:
            self.assertNotIn(key, ei.OPERATION_IDENTITY_KEYS)
            self.assertNotIn(key, ei.IDENTITY_IDENTITY_KEYS)


# --------------------------------------------------------------------------
# The envelope is atomic, or it is a loud refusal (G4)
# --------------------------------------------------------------------------


class EnvelopeIntegrityTests(unittest.TestCase):
    def test_an_incomplete_envelope_is_a_loud_refusal_from_the_loader(self):
        root = _vault(self, "ei-c2-incomplete-")
        fixture = fixture_create(root)
        missing = fixture["binding_ids"][0]
        path = ts.store_path(root, ei.binding_relative_path("deterministic", missing))
        path.unlink()
        with self.assertRaises(ei.EventIdentityError) as caught:
            ei.load_operation_envelope(root, fixture["filed"]["operation"])
        self.assertEqual(caught.exception.code, "identity_envelope_incomplete")
        self.assertEqual(caught.exception.detail["missing_binding_ids"], [missing])

    def test_a_complete_envelope_loads_back_whole(self):
        root = _vault(self, "ei-c2-whole-")
        fixture = fixture_create(root)
        envelope = ei.load_operation_envelope(root, fixture["filed"]["operation"])
        self.assertEqual(
            sorted(row["identity_id"] for row in envelope["bindings"]),
            sorted(fixture["binding_ids"]),
        )

    def test_the_operation_is_written_last_so_a_crash_leaves_nothing_promised(self):
        # Not atomicity — that is the mutation seat's. This is what makes a
        # crash INSIDE the seat recoverable: bindings nobody has been told
        # about are inert; an operation naming absent records is a refusal.
        root = _vault(self, "ei-c2-crash-")
        plan = _create_plan()
        for binding in plan["bindings"]:
            ei.file_event_identity(root, **binding)
        self.assertEqual(ei.load_episode_operations(root), [])
        self.assertEqual(len(ei.load_event_identities(root)), 2)
        # Resuming under the same ids completes the envelope and duplicates
        # nothing.
        resumed = ei.file_operation_envelope(
            root, operation=plan["operation"], bindings=plan["bindings"]
        )
        self.assertTrue(resumed["operation_created"])
        self.assertEqual(len(ei.load_event_identities(root)), 2)


# --------------------------------------------------------------------------
# Split and merge
# --------------------------------------------------------------------------


class SplitAndMergeTests(unittest.TestCase):
    def test_a_split_names_each_departing_telling_and_its_destination(self):
        root = _vault(self, "ei-c2-split-")
        fixture = fixture_split(root)
        record, _created = ei.file_episode_operation(root, **fixture["split"])
        self.assertEqual(record["destinations"], {fixture["leaving"]: "standalone"})
        self.assertEqual(record["supersedes_binding_ids"], [fixture["departing"]])
        self.assertEqual(record["authority"], "human")
        self.assertTrue(record["relative_path"].startswith(ei.HUMAN_OPERATIONS_DIR))

    def test_a_split_with_no_destinations_is_refused(self):
        with self.assertRaises(ei.EventIdentityError) as caught:
            ei.validate_episode_operation(
                {"authority": "human", "op": "split", "episode_id": "episode:" + "4" * 24}
            )
        self.assertEqual(caught.exception.code, "operation_split_needs_destinations")

    def test_a_split_destination_is_standalone_or_an_episode(self):
        with self.assertRaises(ei.EventIdentityError) as caught:
            ei.validate_episode_operation(
                {
                    "authority": "human", "op": "split", "episode_id": "episode:" + "4" * 24,
                    "destinations": {TELLING_A: "somewhere"},
                }
            )
        self.assertEqual(caught.exception.code, "operation_destination_unknown")

    def test_a_splits_destinations_must_match_the_bindings_it_supersedes(self):
        root = _vault(self, "ei-c2-split-drift-")
        fixture = fixture_split(root)
        drifted = dict(fixture["split"])
        drifted["destinations"] = {TELLING_C: ei.STANDALONE_DESTINATION}
        bindings = [ei.read_event_identity(
            root, ei.binding_relative_path("deterministic", fixture["departing"])
        )]
        with self.assertRaises(ei.EventIdentityError) as caught:
            ei.validate_envelope(drifted, bindings)
        self.assertEqual(caught.exception.code, "operation_split_needs_destinations")

    def test_a_merge_absorbs_an_episode_into_an_alias(self):
        root = _vault(self, "ei-c2-merge-")
        fixture = fixture_merge(root)
        record, _created = ei.file_episode_operation(root, **fixture["merge"])
        self.assertEqual(record["absorbed_episode_id"], fixture["absorbed"]["episode_id"])
        self.assertEqual(record["aliases_created"], [fixture["absorbed"]["episode_id"]])
        self.assertEqual(record["episode_id"], fixture["survivor"]["episode_id"])

    def test_a_merge_with_no_absorbed_episode_is_refused(self):
        with self.assertRaises(ei.EventIdentityError) as caught:
            ei.validate_episode_operation(
                {"authority": "human", "op": "merge", "episode_id": "episode:" + "5" * 24,
                 "members": [TELLING_A]}
            )
        self.assertEqual(caught.exception.code, "operation_merge_needs_absorbed")

    def test_an_operation_acting_on_an_episode_must_name_one(self):
        with self.assertRaises(ei.EventIdentityError) as caught:
            ei.validate_episode_operation({"authority": "human", "op": "retitle"})
        self.assertEqual(caught.exception.code, "operation_needs_episode")


# --------------------------------------------------------------------------
# The binding lifecycle
# --------------------------------------------------------------------------


class BindingLifecycleTests(unittest.TestCase):
    def test_canonical_bytes_create_or_keep_keeps_the_existing_bytes(self):
        # Audit A6. Everything outside the digest is written once at create; a
        # second filing of the same decision reports and does not overwrite.
        root = _vault(self, "ei-c2-keep-")
        first, created = ei.file_event_identity(
            root,
            telling_ref=TELLING_A,
            episode_id="episode:" + "6" * 24,
            relation="same",
            origin="confirmed",
            evidence={"telling_quote": "we started it in May"},
            created_at=NOW,
        )
        self.assertTrue(created)
        second, again = ei.file_event_identity(
            root,
            telling_ref=TELLING_A,
            episode_id="episode:" + "6" * 24,
            relation="same",
            origin="confirmed",
            evidence={"telling_quote": "COMPLETELY DIFFERENT WORDS"},
            created_at=LATER,
        )
        self.assertFalse(again)
        self.assertEqual(second["evidence"], {"telling_quote": "we started it in May"})
        self.assertEqual(second["created_at"], NOW)
        self.assertEqual(second["identity_id"], first["identity_id"])

    def test_row_2_a_proposal_becomes_confirmed_by_superseding_it(self):
        root = _vault(self, "ei-c2-confirm-")
        fixture = fixture_proposal(root)
        confirmed, _ = ei.file_event_identity(
            root,
            telling_ref=TELLING_C,
            episode_id=fixture["episode_id"],
            relation="same",
            origin="confirmed",
            supersedes=fixture["proposal"]["identity_id"],
            created_at=LATER,
        )
        self.assertTrue(confirmed["relative_path"].startswith(ei.HUMAN_BINDINGS_DIR))
        self.assertTrue(
            fixture["proposal"]["relative_path"].startswith(ei.STATE_BINDINGS_DIR)
        )
        active = ei.validate_identity_set(ei.load_event_identities(root))
        self.assertEqual([row["identity_id"] for row in active], [confirmed["identity_id"]])

    def test_an_unsuperseded_semantic_twin_across_directories_is_refused(self):
        # §3.3: "identical semantic keys in two directories are never two
        # active authorities". Without the supersedes, this is exactly that.
        root = _vault(self, "ei-c2-twin-")
        fixture = fixture_proposal(root)
        ei.file_event_identity(
            root,
            telling_ref=TELLING_C,
            episode_id=fixture["episode_id"],
            relation="same",
            origin="confirmed",
            created_at=LATER,
        )
        with self.assertRaises(ei.EventIdentityError) as caught:
            ei.validate_identity_set(ei.load_event_identities(root))
        self.assertEqual(caught.exception.code, "identity_unsuperseded_twin")
        self.assertEqual(caught.exception.detail["origins"], ["confirmed", "proposed"])

    def test_two_active_grouping_bindings_for_one_telling_are_a_conflict(self):
        root = _vault(self, "ei-c2-conflict-")
        for suffix in ("7", "8"):
            ei.file_event_identity(
                root,
                telling_ref=TELLING_A,
                episode_id="episode:" + suffix * 24,
                relation="same",
                origin="confirmed",
                created_at=NOW,
            )
        with self.assertRaises(ei.EventIdentityError) as caught:
            ei.validate_identity_set(ei.load_event_identities(root))
        self.assertEqual(caught.exception.code, "identity_conflict")

    def test_a_negative_and_a_membership_are_not_a_conflict(self):
        # `not_same` and `related` say nothing about where a telling groups, so
        # they coexist with a `same` binding by design.
        root = _vault(self, "ei-c2-coexist-")
        ei.file_event_identity(
            root, telling_ref=TELLING_A, episode_id="episode:" + "7" * 24,
            relation="same", origin="confirmed", created_at=NOW,
        )
        ei.file_event_identity(
            root, telling_ref=TELLING_A, episode_id="episode:" + "8" * 24,
            relation="not_same", origin="confirmed", created_at=NOW,
        )
        ei.file_event_identity(
            root, telling_ref=TELLING_A, episode_id="episode:" + "9" * 24,
            relation="related", origin="stated", created_at=NOW,
        )
        active = ei.validate_identity_set(ei.load_event_identities(root))
        self.assertEqual(len(active), 3)

    def test_a_deterministic_rung_binds_same_and_nothing_else(self):
        # §4.2: the deterministic floor is narrow on purpose. A rule that files
        # `part_of` or `related` by itself is the person's call taken from them.
        for relation in ("part_of", "related", "not_same", "none"):
            with self.assertRaises(ei.EventIdentityError, msg=relation) as caught:
                ei.validate_event_identity(
                    {
                        "telling_ref": TELLING_A,
                        "episode_id": "episode:" + "a" * 24,
                        "relation": relation,
                        "origin": "deterministic",
                    }
                )
            self.assertEqual(
                caught.exception.code, "identity_deterministic_relation_unsupported"
            )

    def test_unknown_relations_and_origins_are_refused_by_name(self):
        base = {"telling_ref": TELLING_A, "episode_id": "episode:" + "a" * 24}
        with self.assertRaises(ei.EventIdentityError) as caught:
            ei.validate_event_identity({**base, "relation": "unknown", "origin": "stated"})
        self.assertEqual(caught.exception.code, "identity_relation_unknown")
        with self.assertRaises(ei.EventIdentityError) as caught:
            ei.validate_event_identity({**base, "relation": "same", "origin": "guessed"})
        self.assertEqual(caught.exception.code, "identity_origin_unknown")

    def test_a_binding_round_trips_through_disk_unchanged(self):
        root = _vault(self, "ei-c2-roundtrip-")
        record, _ = ei.file_event_identity(
            root,
            telling_ref=TELLING_A,
            episode_id="episode:" + "b" * 24,
            relation="same",
            origin="stated",
            claim_ids_at_bind=["claim:" + "1" * 24],
            candidates=["episode:" + "c" * 24],
            evidence={"telling_quote": "we started it", "signals": ["place"]},
            source_ref="sources/conversations/msg-abc.md",
            created_at=NOW,
        )
        read = ei.read_event_identity(root, record["relative_path"])
        self.assertEqual(ei.identity_assertion_view(read), ei.identity_assertion_view(record))

    def test_a_binding_never_modifies_a_claim(self):
        # §13.1's plainest promise, stated as a file-system fact: this module
        # writes only under the two identity directories.
        root = _vault(self, "ei-c2-immutable-")
        fixture_create(root)
        touched = sorted(
            path.relative_to(root).as_posix()
            for path in root.rglob("*")
            if path.is_file()
        )
        self.assertTrue(
            all(
                path.startswith(ei.IDENTITY_STATE_DIR) or path.startswith(ei.IDENTITY_SOURCES_DIR)
                for path in touched
            ),
            touched,
        )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
