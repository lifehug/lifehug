"""Event identity I3c — idempotent answers, and `same` absorbing `part_of`.

Controlling design: lifehug-platform `docs/design/event-identity.md` v4 §3.3
(the canonical-bytes/origin-transition rule) and §2.2 (`same` is grouping;
`part_of` is containment — a member of two containers renders in both, but a
telling belongs to at most ONE episode by `same`). Two real defects, found
rehearsing the founder apply pass on a FRESH copy of the actual bound vault
(19 confirmed `same_event` answers over a vault `bind-episodes --apply` had
already filed 48 containments into):

**Defect A.** `bind-episodes --apply`'s containment rung can file a `part_of`
binding for a (telling, episode) pair before anyone ever answers a
`same_event` question about it. When a person later confirms `same` on that
EXACT pair, `identity_questions` filed a fresh `same` binding without
retiring the pair's own `part_of` — two active bindings on one (telling,
episode) pair that disagree about the relation, and the next fold or dry-run
correctly refused: `identity_conflict`. `same` now ABSORBS whatever the pair
already said; the reverse (filing `part_of`/`related`/`different` over an
active `same`) is refused with a message, because that is a contradiction of
what the person already said, not a revision of it.

**Defect B.** Re-filing an already-answered pair raised `identity_conflict`
instead of a create-or-keep no-op. Diagnosis: this was Defect A's OWN
conflict poisoning every subsequent read — `episode_fold_contract.
active_binding_index` processes the WHOLE vault and raises on the FIRST
conflict it finds anywhere, so once Defect A's bad state existed, every
single one of the 19 answers' idempotency checks failed alike, containment
or not. With Defect A's write prevented, a plain pair's replay was already
a no-op (I3b's own "same episode already" branch reaches `_bind_into_
episode`'s existing/no-op check before writing anything) — this file proves
it stays that way, and additionally proves the property the rehearsal
actually needed: after ANY sequence of confirmed answers over a vault
`bind-episodes` has already bound, the fold and the dry-run both load clean.

Every negative below was run against a build with its guard removed and SEEN
failing first; the evidence table is in the PR body. Synthetic data only;
nothing here reads ~/Workspace/dave — the container/member/opening-telling
shape reproduces the MECHANISM the rehearsal found, never its literal refs.
"""

from __future__ import annotations

import itertools
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "system"))
sys.path.insert(0, str(ROOT / "tests"))

import episode_fold_contract as efc  # noqa: E402
import event_identity as ei  # noqa: E402
import identity_questions as iq  # noqa: E402
from tempdirs import root_parent_tmp  # noqa: E402

NOW = "2026-08-31T09:00:00Z"


def _vault(case: unittest.TestCase, prefix: str) -> Path:
    root = root_parent_tmp(case, ROOT, prefix=prefix)
    (root / "state").mkdir(parents=True, exist_ok=True)
    (root / "sources").mkdir(parents=True, exist_ok=True)
    return root


def _loads_clean(root: Path) -> dict:
    """§ the property: the fold's own collapsed view, over the WHOLE vault —
    raises exactly the way a real fold or `bind-episodes --dry-run` would.
    """
    return efc.active_binding_index(ei.load_event_identities(root))


def _confirm_same(root: Path, telling_ref: str, counterpart_ref: str) -> dict:
    return iq.resolve_same_event_answer(
        root, telling_ref=telling_ref, candidate_telling_ref=counterpart_ref,
        answer="same", now=NOW,
    )


def _container(root: Path, opening_telling: str) -> str:
    """One deterministic container episode, anchored by its own opening
    telling — the founder shape (`bind-episodes`' own containment rung
    anchors a container on the telling that OPENS the span, e.g. a
    `landmark` "started X" entry)."""
    operation_id = ei.operation_digest(
        authority="deterministic", op="create", rule_version=ei.IDENTITY_RULE_VERSION,
        member_refs=[opening_telling],
    )
    episode_id = ei.episode_id_for(operation_id)
    binding_id = ei.binding_digest(
        telling_ref=opening_telling, episode_id=episode_id,
        relation=efc.GROUPING_RELATION, rule_version=ei.IDENTITY_RULE_VERSION,
    )
    ei.file_operation_envelope(
        root,
        operation={"authority": "deterministic", "op": "create",
                  "rule_version": ei.IDENTITY_RULE_VERSION, "members": [opening_telling],
                  "creates_binding_ids": [binding_id], "created_at": NOW},
        bindings=[{"telling_ref": opening_telling, "episode_id": episode_id,
                  "relation": efc.GROUPING_RELATION, "origin": "deterministic",
                  "rule_version": ei.IDENTITY_RULE_VERSION, "created_at": NOW}],
    )
    return episode_id


def _file_containment(root: Path, telling_ref: str, episode_id: str, *, origin: str = "proposed") -> dict:
    """One `part_of` binding, the shape `bind-episodes`' containment rung
    files (`entity_span`/`question_context`, `origin: proposed` by the CLI's
    own default)."""
    record, _ = ei.file_event_identity(
        root, telling_ref=telling_ref, episode_id=episode_id, relation="part_of",
        origin=origin, rule_version=ei.IDENTITY_RULE_VERSION, rule_id="entity_span",
        created_at=NOW,
    )
    return record


# ==========================================================================
# §1. Defect A — `same` absorbs an active `part_of` on the identical pair
# ==========================================================================


class SameAbsorbsPartOfTests(unittest.TestCase):
    def test_confirming_same_against_the_containers_own_opening_telling_absorbs_membership(self):
        """The founder's own shape: a member telling is `part_of` a
        container; the person then confirms it IS the container's own
        opening telling (`same`) — membership is absorbed, not doubled."""
        root = _vault(self, "absorb-direct-")
        opening = "landmark:entry-open00000001"
        member = "classification:member-a#111111111111"
        container = _container(root, opening)
        proposal = _file_containment(root, member, container)

        result = iq.resolve_same_event_answer(
            root, telling_ref=member, candidate_telling_ref=opening, answer="same", now=NOW,
        )
        self.assertEqual(result["episode_id"], container)
        self.assertEqual(result["binding"]["supersedes"], proposal["identity_id"])

        index = _loads_clean(root)  # never raises
        self.assertEqual(
            {row["relation"] for row in index[member]}, {efc.GROUPING_RELATION},
        )
        active = ei.validate_identity_set(ei.load_event_identities(root))
        grouping = {row["telling_ref"]: row["episode_id"] for row in active
                   if row["relation"] == efc.GROUPING_RELATION}
        self.assertEqual(grouping[member], container)
        self.assertEqual(grouping[opening], container)

    def test_absorption_works_regardless_of_the_containments_origin(self):
        """A CONFIRMED containment (a person's own prior "part of it" answer,
        not just a machine proposal) is absorbed the same way — a later
        `same` decision revises an earlier `part_of` one, human or not."""
        root = _vault(self, "absorb-confirmed-")
        opening = "landmark:entry-open00000002"
        member = "classification:member-b#222222222222"
        container = _container(root, opening)
        confirmed = _file_containment(root, member, container, origin="confirmed")

        result = iq.resolve_same_event_answer(
            root, telling_ref=member, candidate_telling_ref=opening, answer="same", now=NOW,
        )
        self.assertEqual(result["binding"]["supersedes"], confirmed["identity_id"])
        _loads_clean(root)

    def test_absorption_through_growth_when_the_member_is_named_as_telling_ref(self):
        """The mirrored direction: `telling_ref` is the member already
        `part_of` an episode; the counterpart names the container's own
        opening telling directly."""
        root = _vault(self, "absorb-mirrored-")
        opening = "landmark:entry-open00000003"
        member = "classification:member-c#333333333333"
        container = _container(root, opening)
        _file_containment(root, member, container)

        result = iq.resolve_same_event_answer(
            root, telling_ref=opening, candidate_telling_ref=member, answer="same", now=NOW,
        )
        self.assertEqual(result["episode_id"], container)
        _loads_clean(root)

    def test_a_stray_containment_on_the_merge_survivor_is_absorbed_too(self):
        """A member of the episode being ABSORBED into a merge may ALSO
        already carry a stray `part_of` directly on the SURVIVOR — two
        retirements, `supersedes` only names one, so the absorbed-episode
        retirement rides its own `none`-relation record (the split-
        departure shape) and the new `same` supersedes the stray."""
        root = _vault(self, "absorb-merge-stray-")
        m, n, q, r = (
            "classification:m#111111111111", "classification:n#222222222222",
            "classification:q#333333333333", "classification:r#444444444444",
        )
        e1 = _confirm_same(root, m, n)["episode_id"]
        e2 = _confirm_same(root, q, r)["episode_id"]
        survivor, absorbed = iq._merge_order(root, e1, e2)
        stray_member, cross_a, cross_b = (
            (m, m, q) if absorbed == e1 else (q, q, m)
        )
        stray = _file_containment(root, stray_member, survivor)

        result = iq.resolve_same_event_answer(
            root, telling_ref=cross_a, candidate_telling_ref=cross_b, answer="same", now=NOW,
        )
        self.assertEqual(result["episode_id"], survivor)
        self.assertEqual(result["merged"], absorbed)

        index = _loads_clean(root)  # never raises
        active = ei.validate_identity_set(ei.load_event_identities(root))
        grouping = {row["telling_ref"]: row["episode_id"] for row in active
                   if row["relation"] == efc.GROUPING_RELATION}
        self.assertEqual(len(set(grouping.values())), 1)
        self.assertEqual(grouping[stray_member], survivor)
        # The stray containment itself no longer counts as active.
        active_ids = {row["identity_id"] for row in active}
        self.assertNotIn(stray["identity_id"], active_ids)


# ==========================================================================
# §2. The reverse — filing part_of/related/different over an active `same`
# ==========================================================================


class ReverseRefusalTests(unittest.TestCase):
    def test_filing_part_of_over_an_active_same_is_refused(self):
        root = _vault(self, "reverse-part-of-")
        a, b = "classification:ra#111111111111", "classification:rb#222222222222"
        episode_id = _confirm_same(root, a, b)["episode_id"]
        with self.assertRaises(iq.IdentityQuestionsError) as caught:
            iq.resolve_same_event_answer(
                root, telling_ref=a, candidate_episode_id=episode_id, answer="part_of", now=NOW,
            )
        self.assertEqual(caught.exception.code, "identity_answer_contradicts_same")
        _loads_clean(root)  # the refusal wrote nothing to conflict with

    def test_filing_related_over_an_active_same_is_refused(self):
        root = _vault(self, "reverse-related-")
        a, b = "classification:rc#111111111111", "classification:rd#222222222222"
        episode_id = _confirm_same(root, a, b)["episode_id"]
        with self.assertRaises(iq.IdentityQuestionsError) as caught:
            iq.resolve_same_event_answer(
                root, telling_ref=a, candidate_episode_id=episode_id, answer="related", now=NOW,
            )
        self.assertEqual(caught.exception.code, "identity_answer_contradicts_same")

    def test_filing_different_over_an_active_same_is_refused(self):
        root = _vault(self, "reverse-different-")
        a, b = "classification:re#111111111111", "classification:rf#222222222222"
        episode_id = _confirm_same(root, a, b)["episode_id"]
        with self.assertRaises(iq.IdentityQuestionsError) as caught:
            iq.resolve_same_event_answer(
                root, telling_ref=a, candidate_episode_id=episode_id, answer="different", now=NOW,
            )
        self.assertEqual(caught.exception.code, "identity_answer_contradicts_same")

    def test_possible_overmerges_part_of_answer_still_demotes_a_confirmed_same(self):
        """The SANCTIONED reverse: the overmerge audit's own `part_of`
        answer is explicitly about demoting an active `same` — it must
        supersede a HUMAN-confirmed one too, not just a machine proposal."""
        root = _vault(self, "overmerge-demote-")
        a, b = "classification:om-a#111111111111", "classification:om-b#222222222222"
        episode_id = _confirm_same(root, a, b)["episode_id"]
        existing = ei.load_event_identities(root)
        same_binding = next(
            row for row in existing
            if row["telling_ref"] == a and row["relation"] == efc.GROUPING_RELATION
        )
        result = iq.resolve_possible_overmerge_answer(
            root, telling_ref=a, episode_id=episode_id, answer="part_of",
        )
        self.assertEqual(result["binding"]["supersedes"], same_binding["identity_id"])
        _loads_clean(root)


# ==========================================================================
# §3. Defect B — idempotent replay, with and without containment
# ==========================================================================


class IdempotentReplayTests(unittest.TestCase):
    def test_a_plain_pair_replay_is_a_no_op(self):
        root = _vault(self, "replay-plain-")
        a, b = "classification:cj-a#111111111111", "classification:cj-b#222222222222"
        first = _confirm_same(root, a, b)
        second = _confirm_same(root, a, b)
        self.assertEqual(first["episode_id"], second["episode_id"])
        self.assertFalse(second["created"])
        _loads_clean(root)

    def test_a_containment_absorbing_pair_replay_is_also_a_no_op(self):
        root = _vault(self, "replay-absorb-")
        opening = "landmark:entry-open00000004"
        member = "classification:member-d#444444444444"
        container = _container(root, opening)
        _file_containment(root, member, container)
        first = iq.resolve_same_event_answer(
            root, telling_ref=member, candidate_telling_ref=opening, answer="same", now=NOW,
        )
        second = iq.resolve_same_event_answer(
            root, telling_ref=member, candidate_telling_ref=opening, answer="same", now=NOW,
        )
        self.assertEqual(first["episode_id"], second["episode_id"])
        self.assertFalse(second["created"])
        _loads_clean(root)

    def test_a_merge_replay_stays_a_no_op_after_absorbing_a_stray(self):
        root = _vault(self, "replay-merge-stray-")
        m, n, q, r = (
            "classification:rm-m#111111111111", "classification:rm-n#222222222222",
            "classification:rm-q#333333333333", "classification:rm-r#444444444444",
        )
        e1 = _confirm_same(root, m, n)["episode_id"]
        e2 = _confirm_same(root, q, r)["episode_id"]
        survivor, absorbed = iq._merge_order(root, e1, e2)
        stray_member, cross_a, cross_b = (m, m, q) if absorbed == e1 else (q, q, m)
        _file_containment(root, stray_member, survivor)
        first = iq.resolve_same_event_answer(
            root, telling_ref=cross_a, candidate_telling_ref=cross_b, answer="same", now=NOW,
        )
        second = iq.resolve_same_event_answer(
            root, telling_ref=cross_a, candidate_telling_ref=cross_b, answer="same", now=NOW,
        )
        self.assertEqual(first["episode_id"], second["episode_id"])
        self.assertFalse(
            second.get("created", second.get("envelope", {}).get("created"))
        )
        _loads_clean(root)


# ==========================================================================
# §4. The general property: any sequence over a bound vault loads clean
# ==========================================================================


class BoundVaultPropertyTests(unittest.TestCase):
    """"After any sequence of confirmed answers over a bound vault, fold and
    dry-run load clean" — proven over every ordering of a mixed batch: two
    containment-absorbing confirmations sharing a container, a plain pair,
    and a merge-triggering cross-confirmation."""

    def _scenario(self, root: Path) -> list[tuple[str, str]]:
        opening = "landmark:entry-open00000005"
        member1 = "classification:prop-member1#111111111111"
        member2 = "classification:prop-member2#222222222222"
        plain_a = "classification:prop-plain-a#333333333333"
        plain_b = "classification:prop-plain-b#444444444444"
        cluster_a = "classification:prop-cluster-a#555555555555"
        cluster_b = "classification:prop-cluster-b#666666666666"
        _container(root, opening)
        _file_containment(root, member1, ei.episode_id_for(ei.operation_digest(
            authority="deterministic", op="create", rule_version=ei.IDENTITY_RULE_VERSION,
            member_refs=[opening],
        )))
        _file_containment(root, member2, ei.episode_id_for(ei.operation_digest(
            authority="deterministic", op="create", rule_version=ei.IDENTITY_RULE_VERSION,
            member_refs=[opening],
        )))
        return [
            (member1, opening),       # absorbs a containment
            (member2, opening),       # absorbs a containment, same container
            (plain_a, plain_b),       # a plain fresh pair
            (cluster_a, cluster_b),   # a second fresh pair
            (member1, cluster_a),     # a merge: member1's episode + cluster_a's episode
        ]

    def test_every_order_of_a_mixed_batch_loads_clean_and_converges(self):
        # Two DISJOINT final clusters: {member1, member2, opening, cluster_a,
        # cluster_b} (the container plus its absorbed members plus the
        # cross-cluster merge) and {plain_a, plain_b} (never connected to
        # anything else by any answer in the batch) — the property is that
        # BOTH partitions are the SAME regardless of order, not that
        # everything collapses into one episode.
        merged_cluster = {
            "landmark:entry-open00000005",
            "classification:prop-member1#111111111111",
            "classification:prop-member2#222222222222",
            "classification:prop-cluster-a#555555555555",
            "classification:prop-cluster-b#666666666666",
        }
        plain_cluster = {
            "classification:prop-plain-a#333333333333",
            "classification:prop-plain-b#444444444444",
        }
        for order in itertools.permutations(range(5)):
            with self.subTest(order=order):
                root = _vault(self, "property-")
                answers = self._scenario(root)
                ordered = [answers[i] for i in order]
                for telling_ref, counterpart_ref in ordered:
                    _confirm_same(root, telling_ref, counterpart_ref)
                _loads_clean(root)  # never raises, any order
                active = ei.validate_identity_set(ei.load_event_identities(root))
                grouping = {
                    row["telling_ref"]: row["episode_id"] for row in active
                    if row["relation"] == efc.GROUPING_RELATION
                }
                self.assertEqual(set(grouping), merged_cluster | plain_cluster)
                by_episode: dict = {}
                for telling_ref, episode_id in grouping.items():
                    by_episode.setdefault(episode_id, set()).add(telling_ref)
                self.assertEqual(
                    sorted(by_episode.values(), key=len),
                    sorted([plain_cluster, merged_cluster], key=len),
                )


# ==========================================================================
# §5. The containment rung never re-proposes over an active binding
# ==========================================================================
#
# The SECOND manifestation of Defect B: `bind-episodes --apply`, run again
# after a confirmed answer, re-derives containment PURELY from entity/span
# retrieval — blind to the identity substrate — and re-proposed `part_of`
# for a telling already `same`-confirmed to the exact episode its own
# container became. `episode_binder.plan()`'s containment rung now reads
# the SAME properly-collapsed `active` view R1 itself reads before minting
# a containment row, exactly as its own docstring already promised ("a
# telling is never placed inside a container it is already a member of")
# but had not actually implemented for this case.


import hashlib  # noqa: E402

import episode_binder as eb  # noqa: E402
import episode_containers as ec  # noqa: E402
import episode_fold as ef  # noqa: E402
import temporal_claims as tc  # noqa: E402

CONTAINMENT_ROSTERS = {
    "theme": {"type": "theme", "entities": [
        {"name": "Halcyon", "slug": "halcyon", "aliases": []},
    ]},
}
CONTAINMENT_OPEN = "landmark:entry-halcyon-open"
CONTAINMENT_MEMBER = "classification:halcyon-member#aaa1aaa1aaa1"


def _containment_revision(seed: str) -> str:
    return "sha256:" + hashlib.sha256(seed.encode("utf-8")).hexdigest()


def _containment_value(text: str) -> dict:
    grain = {4: "year", 7: "month"}[len(text)]
    return {"best": text, "earliest": text, "latest": text, "granularity": grain,
            "basis": "stated", "confidence": "certain"}


def _containment_claim(**overrides) -> dict:
    source = overrides.pop("source")
    payload = {
        "source_kind": "conversation",
        "source_ref": {"source_id": source, "revision": _containment_revision(source)},
        "evidence": [{"quote": overrides.pop("quote", "a sentence")}],
        "extractor_version": "classifier:1", "created_at": NOW,
        "basis": "explicit", "confidence": 0.9, "status": "active",
        "claim_type": "occurrence", "subject_mention": "I",
    }
    payload.update(overrides)
    return tc.validate_temporal_claim(payload)


def _containment_claims() -> list:
    return [
        _containment_claim(
            source=CONTAINMENT_OPEN, claim_type="date", subject_mention="Halcyon",
            event_kind="started", temporal_value=_containment_value("2022-05"),
            quote="Halcyon, May 2022 - Present",
        ),
        _containment_claim(
            source=CONTAINMENT_MEMBER, event_mention="Started Halcyon",
            event_kind="moment", quote="We started Halcyon.",
        ),
    ]


class ContainmentRungRespectsActiveBindingsTests(unittest.TestCase):
    def test_a_telling_already_same_to_the_containers_episode_gets_no_containment_row(self):
        container_id = ec.container_episode_id(CONTAINMENT_OPEN)
        # CONTAINMENT_MEMBER is ALREADY confirmed `same` to the container's
        # own eventual episode id — exactly what happens after a person
        # answers a `same_event` pair naming the container's opening
        # telling.
        member_binding_id = ei.binding_digest(
            telling_ref=CONTAINMENT_MEMBER, episode_id=container_id,
            relation=efc.GROUPING_RELATION, rule_version=ei.IDENTITY_RULE_VERSION,
        )
        member_binding = ei.validate_event_identity({
            "telling_ref": CONTAINMENT_MEMBER, "episode_id": container_id,
            "relation": efc.GROUPING_RELATION, "origin": "confirmed",
            "rule_version": ei.IDENTITY_RULE_VERSION, "created_at": NOW,
        })
        records = ef.normalize_episode_records({"bindings": [member_binding]})
        result = eb.plan(
            _containment_claims(), episode_records=records,
            entity_index=ec.entity_index(CONTAINMENT_ROSTERS), now=NOW,
        )
        self.assertNotIn(
            CONTAINMENT_MEMBER,
            {row["telling_ref"] for row in result.proposals
             if row.get("relation") == "part_of"},
        )
        # ...but a genuinely UNRELATED member still gets its containment —
        # the filter is pair-scoped, not a blanket suppression.
        active = ei.validate_identity_set([member_binding])
        self.assertEqual(len(active), 1)


if __name__ == "__main__":
    unittest.main()
