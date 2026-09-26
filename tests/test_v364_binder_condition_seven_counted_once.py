"""v364: R1 condition 7 counts an episode's members once per plan, not per pair.

`_home_is_mature` asked "does this telling's own episode already hold two or
more tellings?" by walking EVERY active binding, and it asked it for every
candidate of every telling. On the owner's vault (1,261 nodes, ~1,330 bound
tellings, 83,600 condition-7 evaluations) that was 111 million
`grouping_binding` calls: 456 s of a 572 s `bind-episodes --apply`, past the
hosted worker's 600 s package budget on every run from 2026-09-25 on — each
killed run holding the vault lease while the owner's filings waited.

The count is a property of the binding index, so the plan takes it once
(`episode_member_counts`) and hands it down. These tests pin that the counts
are exactly the old loop's counts, that the verdict is unchanged, and that a
plan takes the count ONCE however many pairs it evaluates.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "system"))
sys.path.insert(0, str(ROOT / "tests"))

import episode_binder as eb  # noqa: E402
import episode_fold as ef  # noqa: E402
import episode_fold_contract as efc  # noqa: E402
from temporal_claims import collapsed_text  # noqa: E402
from test_event_identity_i2_binder import (  # noqa: E402
    create_records,
    direction_of,
    ref,
    refs,
    run,
)


def _naive_count(active, episode_id: str) -> int:
    """The pre-v364 loop, verbatim, as the reference."""
    count = 0
    for telling_ref in active:
        row = efc.grouping_binding(telling_ref, active)
        if row is not None and collapsed_text(row.get("episode_id")) == episode_id:
            count += 1
    return count


def _two_mature_episodes() -> dict:
    left = create_records(refs("ridgeline"), kind="job")
    right = create_records(refs("ridgeline_third", "ridgeline_undated"), kind="job")
    return {
        "records": {
            "operations": left["operations"] + right["operations"],
            "bindings": left["bindings"] + right["bindings"],
        },
        "left": left,
        "right": right,
    }


class EpisodeMemberCountsTests(unittest.TestCase):
    def test_the_counts_are_exactly_what_the_per_pair_loop_counted(self):
        fixture = _two_mature_episodes()
        records = ef.normalize_episode_records(fixture["records"])
        active = efc.active_binding_index(records["bindings"])
        counts = eb.episode_member_counts(active)
        episode_ids = {
            collapsed_text(row.get("episode_id"))
            for rows in active.values()
            for row in rows
        }
        self.assertTrue(episode_ids)
        for episode_id in episode_ids:
            self.assertEqual(counts.get(episode_id, 0), _naive_count(active, episode_id),
                             episode_id)

    def test_condition_seven_still_refuses_to_join_two_mature_episodes(self):
        fixture = _two_mature_episodes()
        result = run("ridgeline", "ridgeline_third", "ridgeline_undated",
                     episode_records=fixture["records"])
        pair = direction_of(result, ref("ridgeline"), fixture["right"]["episode_id"])
        by_name = {row.name: row for row in pair.conditions}
        self.assertFalse(by_name["not_joining_two_mature_episodes"].passed)
        self.assertEqual(result.envelopes, [])

    def test_a_plan_counts_members_once_however_many_pairs_it_evaluates(self):
        fixture = _two_mature_episodes()
        calls = []
        real = eb.episode_member_counts

        def counting(active):
            calls.append(len(active))
            return real(active)

        eb.episode_member_counts = counting
        try:
            result = run("ridgeline", "ridgeline_third", "ridgeline_undated",
                         episode_records=fixture["records"])
        finally:
            eb.episode_member_counts = real
        self.assertGreater(len(result.directional), 1)
        self.assertEqual(len(calls), 1, calls)

    def test_a_handed_in_count_is_one_lookup_not_a_walk_of_the_index(self):
        """The shape that made the binder quadratic: with the plan's counts in
        hand, condition 7 reads the telling's own binding and nothing else."""
        fixture = _two_mature_episodes()
        records = ef.normalize_episode_records(fixture["records"])
        active = efc.active_binding_index(records["bindings"])
        counts = eb.episode_member_counts(active)
        telling = ref("ridgeline_third")
        view = type("View", (), {"telling_ref": telling})()

        seen = []
        real = efc.grouping_binding

        def counting(telling_ref, active_bindings):
            seen.append(telling_ref)
            return real(telling_ref, active_bindings)

        efc.grouping_binding = counting
        try:
            with_counts = eb._home_is_mature(view, active, member_counts=counts)
            lookups = len(seen)
            without_counts = eb._home_is_mature(view, active)
        finally:
            efc.grouping_binding = real
        self.assertTrue(with_counts)
        self.assertEqual(with_counts, without_counts)
        self.assertEqual(lookups, 1, seen)


if __name__ == "__main__":
    unittest.main()
