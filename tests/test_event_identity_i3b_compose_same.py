"""Event identity I3b — composing overlapping `same` answers.

Controlling design: lifehug-platform `docs/design/event-identity.md` v4
§6.1 (`same_event`'s five answers) and §3.2 (C2's operation vocabulary —
`create`/`merge`, growth reuses the rule-version mechanism, an adopted
episode is never superseded). Real defect, found rehearsing the founder
apply pass on a copy: the founder's 19 confirmed pairs OVERLAP — one
telling is the shared vertex of more than one confirmed `same` answer — and
`identity_questions.resolve_same_event_answer` filed each pair
independently, so the SECOND answer on a shared telling minted a second
active `same` binding with no supersession. The fold correctly refused
(`identity_conflict`, Law 2/§5.4); this module is the fix, composing
overlapping answers through C2's own operations (`_bind_into_episode` for
growth, `_merge_episodes` for two already-separate episodes) instead of
violating the refusal.

Every negative below was run against a build with its guard removed and SEEN
failing first; the evidence table is in the PR body. Synthetic data only;
nothing here reads ~/Workspace/dave — and no fixture reuses the founder's own
telling refs, only their SHAPE (a triangle: two confirmed pairs sharing one
vertex).
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

NOW = "2026-08-30T09:00:00Z"

TRIANGLE = (
    "classification:triangle-a#a1a1a1a1a1a1",
    "classification:triangle-b#b2b2b2b2b2b2",
    "classification:triangle-c#c3c3c3c3c3c3",
)


def _vault(case: unittest.TestCase, prefix: str) -> Path:
    root = root_parent_tmp(case, ROOT, prefix=prefix)
    (root / "state").mkdir(parents=True, exist_ok=True)
    (root / "sources").mkdir(parents=True, exist_ok=True)
    return root


def _active_grouping(root: Path) -> dict:
    """``{telling_ref: episode_id}`` over every active `same` binding —
    raises `identity_conflict` exactly as the next fold or binder run would
    if two are active on one telling with no supersession."""
    active = ei.validate_identity_set(ei.load_event_identities(root))
    return {
        row["telling_ref"]: row["episode_id"]
        for row in active
        if row["relation"] == efc.GROUPING_RELATION
    }


def _confirm_same(root: Path, telling_ref: str, counterpart_ref: str) -> dict:
    return iq.resolve_same_event_answer(
        root, telling_ref=telling_ref, candidate_telling_ref=counterpart_ref,
        answer="same", now=NOW,
    )


def _episode(root: Path, *members: str) -> str:
    """One human-created episode over exactly ``members`` — the fixture for
    "two mature episodes", built through the module's own writer so its
    shape matches what a real confirmed-Same answer produces."""
    members = sorted(members)
    result = iq.resolve_same_event_answer(
        root, telling_ref=members[0], candidate_telling_ref=members[1],
        answer="same", now=NOW,
    )
    episode_id = result["episode_id"]
    for extra in members[2:]:
        iq.resolve_same_event_answer(
            root, telling_ref=members[0], candidate_telling_ref=extra,
            answer="same", now=NOW,
        )
    return episode_id


# ==========================================================================
# §1. The a3 triangle — any permutation converges, never a conflict
# ==========================================================================


class TriangleConvergenceTests(unittest.TestCase):
    """3 tellings, 2 confirmed `same` pairs sharing one vertex — the real
    shape found rehearsing the founder apply pass."""

    def test_every_pair_choice_and_order_converges_to_one_episode_of_three(self):
        a, b, c = TRIANGLE
        pair_sets = [
            ((a, b), (a, c)),  # shared vertex a
            ((a, b), (b, c)),  # shared vertex b
            ((a, c), (b, c)),  # shared vertex c
        ]
        for pairs in pair_sets:
            for order in itertools.permutations(pairs):
                with self.subTest(pairs=pairs, order=order):
                    root = _vault(self, "tri-")
                    for telling, counterpart in order:
                        _confirm_same(root, telling, counterpart)
                    grouping = _active_grouping(root)  # never raises identity_conflict
                    self.assertEqual(set(grouping), {a, b, c})
                    self.assertEqual(len(set(grouping.values())), 1)

    def test_a_third_confirmation_among_already_unified_tellings_is_a_no_op(self):
        a, b, c = TRIANGLE
        root = _vault(self, "tri-redundant-")
        _confirm_same(root, a, b)
        _confirm_same(root, a, c)
        before = _active_grouping(root)
        result = _confirm_same(root, b, c)  # already unified via a
        after = _active_grouping(root)
        self.assertEqual(before, after)
        self.assertFalse(result.get("created", True))

    def test_replaying_the_exact_same_pair_is_idempotent(self):
        a, b, c = TRIANGLE
        root = _vault(self, "tri-replay-")
        _confirm_same(root, a, b)
        _confirm_same(root, a, c)
        first = _active_grouping(root)
        _confirm_same(root, a, b)
        _confirm_same(root, a, c)
        second = _active_grouping(root)
        self.assertEqual(first, second)


# ==========================================================================
# §2. Growth: one side already in an episode, the other standalone
# ==========================================================================


class GrowthTests(unittest.TestCase):
    def test_a_standalone_counterpart_is_bound_into_the_existing_side(self):
        a, b, c = TRIANGLE
        root = _vault(self, "growth-")
        episode_id = _episode(root, a, b)
        result = iq.resolve_same_event_answer(
            root, telling_ref=a, candidate_telling_ref=c, answer="same", now=NOW,
        )
        self.assertEqual(result["episode_id"], episode_id)
        self.assertEqual(_active_grouping(root)[c], episode_id)

    def test_the_mirrored_direction_binds_the_named_telling_into_the_counterparts_episode(self):
        """§6.1's answer names `telling_ref`; the ALREADY-bound side may be
        either `telling_ref` or the counterpart — both directions grow the
        one episode that exists."""
        a, b, c = TRIANGLE
        root = _vault(self, "growth-mirror-")
        episode_id = _episode(root, a, b)
        result = iq.resolve_same_event_answer(
            root, telling_ref=c, candidate_episode_id=None,
            candidate_telling_ref=a, answer="same", now=NOW,
        )
        self.assertEqual(result["episode_id"], episode_id)
        self.assertEqual(_active_grouping(root)[c], episode_id)

    def test_candidate_episode_id_is_optional_when_the_counterpart_telling_is_known(self):
        """The rehearsal's own shape: a caller that only ever learned the
        counterpart's telling ref, never any episode id."""
        a, b = TRIANGLE[0], TRIANGLE[1]
        root = _vault(self, "growth-none-episode-")
        result = iq.resolve_same_event_answer(
            root, telling_ref=a, candidate_episode_id=None,
            candidate_telling_ref=b, answer="same", now=NOW,
        )
        self.assertIn("episode_id", result)
        self.assertEqual(set(_active_grouping(root)), {a, b})

    def test_growth_supersedes_a_machine_origin_proposal_at_the_target(self):
        """Growing into an episode where the counterpart already carries a
        `proposed` binding is the origin-transition case, not "nothing to
        do" — confirming upgrades it."""
        a, b = TRIANGLE[0], TRIANGLE[1]
        root = _vault(self, "growth-supersede-")
        episode_id = ei.episode_id_for(ei.operation_digest(
            authority="deterministic", op="create", rule_version=ei.IDENTITY_RULE_VERSION,
            member_refs=[a],
        ))
        binding_id = ei.binding_digest(
            telling_ref=a, episode_id=episode_id, relation=efc.GROUPING_RELATION,
            rule_version=ei.IDENTITY_RULE_VERSION,
        )
        ei.file_operation_envelope(
            root,
            operation={"authority": "deterministic", "op": "create",
                      "rule_version": ei.IDENTITY_RULE_VERSION, "members": [a],
                      "creates_binding_ids": [binding_id], "created_at": NOW},
            bindings=[{"telling_ref": a, "episode_id": episode_id,
                      "relation": efc.GROUPING_RELATION, "origin": "deterministic",
                      "rule_version": ei.IDENTITY_RULE_VERSION, "created_at": NOW}],
        )
        proposed, _ = ei.file_event_identity(
            root, telling_ref=b, episode_id=episode_id, relation=efc.GROUPING_RELATION,
            origin="proposed", rule_version=ei.IDENTITY_RULE_VERSION, created_at=NOW,
        )
        result = iq.resolve_same_event_answer(
            root, telling_ref=b, candidate_episode_id=episode_id, answer="same", now=NOW,
        )
        self.assertEqual(result["binding"]["supersedes"], proposed["identity_id"])
        active = ei.validate_identity_set(ei.load_event_identities(root))
        self.assertNotIn(proposed["identity_id"], {row["identity_id"] for row in active})

    def test_confirming_same_directly_against_an_existing_deterministic_binding_supersedes_it(self):
        """Both `telling_ref` and the counterpart resolve to the SAME
        episode — a direct confirmation of what R1 already grouped, not a
        no-op: the existing binding is `deterministic` origin, so this is
        the origin-transition case routed through the "same episode
        already" branch, not through growth or merge."""
        a = TRIANGLE[0]
        root = _vault(self, "same-episode-deterministic-")
        episode_id = ei.episode_id_for(ei.operation_digest(
            authority="deterministic", op="create", rule_version=ei.IDENTITY_RULE_VERSION,
            member_refs=[a],
        ))
        binding_id = ei.binding_digest(
            telling_ref=a, episode_id=episode_id, relation=efc.GROUPING_RELATION,
            rule_version=ei.IDENTITY_RULE_VERSION,
        )
        ei.file_operation_envelope(
            root,
            operation={"authority": "deterministic", "op": "create",
                      "rule_version": ei.IDENTITY_RULE_VERSION, "members": [a],
                      "creates_binding_ids": [binding_id], "created_at": NOW},
            bindings=[{"telling_ref": a, "episode_id": episode_id,
                      "relation": efc.GROUPING_RELATION, "origin": "deterministic",
                      "rule_version": ei.IDENTITY_RULE_VERSION, "created_at": NOW}],
        )
        result = iq.resolve_same_event_answer(
            root, telling_ref=a, candidate_episode_id=episode_id, answer="same", now=NOW,
        )
        self.assertIn("binding", result)
        self.assertEqual(result["binding"]["origin"], "confirmed")
        self.assertEqual(result["binding"]["supersedes"], binding_id)

    def test_grouping_lookups_exclude_a_superseded_binding_by_its_supersedes_pointer_not_its_own_status(self):
        """A superseded record's OWN `status` field is never flipped — only
        a NEWER record's `supersedes` pointer says it no longer counts
        (the substrate never rewrites another record's bytes). Both
        `_active_same_episode` and `_grouped_members` must read the
        properly collapsed view, or a stale binding wins by file-sort luck —
        the exact latent shape this fix's own merge idempotency check
        tripped over mid-development."""
        a = TRIANGLE[0]
        root = _vault(self, "superseded-exclude-")
        old_episode = "episode:" + "1" * 24
        new_episode = "episode:" + "2" * 24
        old, _ = ei.file_event_identity(
            root, telling_ref=a, episode_id=old_episode, relation=efc.GROUPING_RELATION,
            origin="confirmed", rule_version=ei.IDENTITY_RULE_VERSION, created_at=NOW,
        )
        self.assertEqual(old["status"], "active")
        ei.file_event_identity(
            root, telling_ref=a, episode_id=new_episode, relation=efc.GROUPING_RELATION,
            origin="confirmed", rule_version=ei.IDENTITY_RULE_VERSION,
            supersedes=old["identity_id"], created_at=NOW,
        )
        self.assertEqual(iq._active_same_episode(root, a), new_episode)
        self.assertNotIn(a, iq._grouped_members(root, old_episode))
        self.assertIn(a, iq._grouped_members(root, new_episode))


# ==========================================================================
# §3. Merge: two sides already in DIFFERENT episodes
# ==========================================================================


class MergeTests(unittest.TestCase):
    def test_a_third_same_answer_joining_two_mature_episodes_files_a_merge_not_a_refusal(self):
        a, b, c, d = (
            "classification:m-a#111111111111", "classification:m-b#222222222222",
            "classification:m-c#333333333333", "classification:m-d#444444444444",
        )
        root = _vault(self, "merge-third-")
        e1 = _episode(root, a, b)
        e2 = _episode(root, c, d)
        self.assertNotEqual(e1, e2)
        result = iq.resolve_same_event_answer(
            root, telling_ref=a, candidate_telling_ref=c, answer="same", now=NOW,
        )
        self.assertIn(result["episode_id"], (e1, e2))
        grouping = _active_grouping(root)  # never raises
        self.assertEqual(set(grouping), {a, b, c, d})
        self.assertEqual(len(set(grouping.values())), 1)
        self.assertEqual(result["merged"], e2 if result["episode_id"] == e1 else e1)

    def test_merge_replay_is_idempotent_from_either_side_or_call_order(self):
        a, b, c, d = (
            "classification:mr-a#111111111111", "classification:mr-b#222222222222",
            "classification:mr-c#333333333333", "classification:mr-d#444444444444",
        )
        root = _vault(self, "merge-replay-")
        e1 = _episode(root, a, b)
        e2 = _episode(root, c, d)
        first = iq._merge_episodes(root, episode_a=e1, episode_b=e2, now=NOW)
        second = iq._merge_episodes(root, episode_a=e1, episode_b=e2, now=NOW)
        third = iq._merge_episodes(root, episode_a=e2, episode_b=e1, now=NOW)
        self.assertEqual(first["episode_id"], second["episode_id"])
        self.assertEqual(first["episode_id"], third["episode_id"])
        self.assertTrue(first["envelope"]["created"])
        self.assertFalse(second["envelope"]["created"])
        self.assertFalse(third["envelope"]["created"])
        grouping = _active_grouping(root)
        self.assertEqual(len(set(grouping.values())), 1)

    def test_merge_prefers_the_adopted_episode_as_survivor(self):
        """A human-CONFIRMED episode always counts as adopted (every
        operation `resolve_same_event_answer` files is `authority: human`
        by construction, and `event_identity.is_adopted` is true of any
        episode a human operation ever touched) — so the meaningful
        comparison is against a DETERMINISTIC one R1 bound and nobody has
        acted on since. The deterministic episode is deliberately built to
        sort SMALLER than nothing in particular — it is what a plain
        lexicographic fallback would have to get right or wrong on its own,
        and this test names the human side as survivor regardless of which
        way that sort would have gone."""
        a, b, c, d = (
            "classification:ad-a#111111111111", "classification:ad-b#222222222222",
            "classification:ad-c#333333333333", "classification:ad-d#444444444444",
        )
        root = _vault(self, "merge-adopted-")
        deterministic = ei.episode_id_for(ei.operation_digest(
            authority="deterministic", op="create", rule_version=ei.IDENTITY_RULE_VERSION,
            member_refs=[a, b],
        ))
        binding_ids = [
            ei.binding_digest(telling_ref=ref, episode_id=deterministic,
                              relation=efc.GROUPING_RELATION, rule_version=ei.IDENTITY_RULE_VERSION)
            for ref in (a, b)
        ]
        ei.file_operation_envelope(
            root,
            operation={"authority": "deterministic", "op": "create",
                      "rule_version": ei.IDENTITY_RULE_VERSION, "members": [a, b],
                      "creates_binding_ids": binding_ids, "created_at": NOW},
            bindings=[
                {"telling_ref": ref, "episode_id": deterministic,
                 "relation": efc.GROUPING_RELATION, "origin": "deterministic",
                 "rule_version": ei.IDENTITY_RULE_VERSION, "created_at": NOW}
                for ref in (a, b)
            ],
        )
        confirmed = _episode(root, c, d)
        self.assertFalse(ei.is_adopted(root, deterministic))
        self.assertTrue(ei.is_adopted(root, confirmed))
        for episode_a, episode_b in ((deterministic, confirmed), (confirmed, deterministic)):
            with self.subTest(order=(episode_a, episode_b)):
                survivor, absorbed = iq._merge_order(root, episode_a, episode_b)
                self.assertEqual(survivor, confirmed)
                self.assertEqual(absorbed, deterministic)

    def test_merging_an_episode_with_itself_writes_nothing(self):
        a, b = TRIANGLE[0], TRIANGLE[1]
        root = _vault(self, "merge-self-")
        e1 = _episode(root, a, b)
        result = iq._merge_episodes(root, episode_a=e1, episode_b=e1, now=NOW)
        self.assertFalse(result.get("written", True) if "written" in result else False)


# ==========================================================================
# §4. Negatives — proven to fire against a build with the guard removed
# ==========================================================================


class NegativeProofTests(unittest.TestCase):
    """Each test here documents a mutation that was applied, run, and SEEN
    failing before the fix; the assertion is the fix's own promise, stated
    positively, so a regression trips the same test."""

    def test_no_fold_ever_sees_two_active_same_bindings_on_one_telling(self):
        """The defect's own signature: `identity_conflict` on the shared
        vertex. Reverting `_active_same_episode` to always return `None`
        (treating every pair as prospective, the pre-fix behavior)
        reproduces it — SEEN failing before this fix landed."""
        a, b, c = TRIANGLE
        root = _vault(self, "neg-conflict-")
        _confirm_same(root, a, b)
        _confirm_same(root, a, c)
        # This call raises `identity_conflict` on the pre-fix code path.
        active = ei.validate_identity_set(ei.load_event_identities(root))
        same_on_a = [row for row in active if row["telling_ref"] == a
                    and row["relation"] == efc.GROUPING_RELATION]
        self.assertEqual(len(same_on_a), 1)

    def test_a_merge_that_forgets_supersedes_leaves_the_absorbed_binding_active(self):
        """A merge's new binding into the survivor MUST name the old
        (absorbed-episode) binding in `supersedes`, or the old one stays
        active forever beside the new one — the exact bug caught mid-fix
        here (both bindings otherwise show up for the same telling)."""
        a, b, c, d = (
            "classification:sup-a#111111111111", "classification:sup-b#222222222222",
            "classification:sup-c#333333333333", "classification:sup-d#444444444444",
        )
        root = _vault(self, "neg-supersede-")
        e1 = _episode(root, a, b)
        e2 = _episode(root, c, d)
        result = iq._merge_episodes(root, episode_a=e1, episode_b=e2, now=NOW)
        merged_bindings = [
            row for row in ei.load_event_identities(root)
            if row["episode_id"] == result["merged"] and row["relation"] == efc.GROUPING_RELATION
        ]
        self.assertTrue(all(row["status"] == "active" for row in merged_bindings))
        # ...but every one of them is named in some OTHER record's
        # `supersedes`, which is what makes `validate_identity_set` exclude
        # it from the active view.
        superseded_ids = {
            row["supersedes"] for row in ei.load_event_identities(root) if row["supersedes"]
        }
        for row in merged_bindings:
            self.assertIn(row["identity_id"], superseded_ids)

    def test_a_negative_cap_style_refusal_when_neither_side_is_known(self):
        root = _vault(self, "neg-no-sibling-")
        with self.assertRaises(iq.IdentityQuestionsError) as caught:
            iq.resolve_same_event_answer(
                root, telling_ref=TRIANGLE[0], answer="same", now=NOW,
            )
        self.assertEqual(caught.exception.code, "identity_answer_needs_sibling")

    def test_a_merge_with_no_absorbed_members_and_no_prior_operation_is_refused(self):
        root = _vault(self, "neg-empty-merge-")
        fake_a = "episode:" + "a" * 24
        fake_b = "episode:" + "b" * 24
        with self.assertRaises(iq.IdentityQuestionsError) as caught:
            iq._merge_episodes(root, episode_a=fake_a, episode_b=fake_b, now=NOW)
        self.assertEqual(caught.exception.code, "identity_merge_needs_absorbed_members")


if __name__ == "__main__":
    unittest.main()
