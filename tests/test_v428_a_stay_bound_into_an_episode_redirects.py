"""v428 — a stay bound into an episode redirects to it.

`temporal_timeline.A_STAY_BOUND_INTO_AN_EPISODE_REDIRECTS_TO_IT`. Two filings
of ONE residence stay — the entry and a later revision of it (same entry key,
same address, a different end date) — each seed a participation node. When
`bind-episodes` rules the two landmark tellings one episode (R1 ``same``),
every claim of the revision's seed folds onto the episode node, and the emptied
seed used to be refused as ``node_without_inputs``: `derive_calculated_timeline`
raised and every publish (and every ``classify-story --prompt``) parked. The
emptied seed is now not drawn; its id is published in ``node_aliases`` as a
redirect to the node its claims went to.

Runs through the real recorder → receipt → active index → binder → fold path
(`test_participation_episodes.ParticipationEpisodeCase`). The fixture was SEEN
raising ``TimelineNodeError: node_without_inputs`` in ``setUp`` with the guard
removed.

Synthetic data only; NEVER references ~/Workspace/dave.
"""

from __future__ import annotations

import copy
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "system"))
sys.path.insert(0, str(ROOT / "tests"))

import temporal_timeline as tt  # noqa: E402
import test_participation_episodes as tpe  # noqa: E402
from test_participation_episodes import ParticipationEpisodeCase, value  # noqa: E402

PLACE_REF = "place/residence-gull-lane"


def approximate(text: str) -> dict:
    row = value(text)
    row["confidence"] = "approximate"
    return row


def _rosters() -> dict:
    rosters = copy.deepcopy(tpe.ROSTERS)
    rosters["place"]["entities"].append(
        {"name": "12 Gull Lane", "slug": PLACE_REF.split("/", 1)[1],
         "aliases": ["Our house (owned)"]})
    return rosters


class ARevisedStayBoundIntoOneEpisode(ParticipationEpisodeCase):
    """The entry, then the owner's revision of its end date."""

    ENTRIES = (
        ("residences", {"label": "Our house (owned)", "nickname": "Our house",
                        "note": "owned", "ongoing": False,
                        "address": "12 Gull Lane, Cedarport", "city": "Cedarport",
                        "place_ref": PLACE_REF,
                        "span": {"start": approximate("1988-06"),
                                 "end": approximate("1989-06")}}),
        ("residences", {"label": "Our house (owned)",
                        "nickname": "Our house (owned)",
                        "address": "12 Gull Lane, Cedarport", "city": "Cedarport",
                        "place_ref": PLACE_REF,
                        "span": {"start": value("1988-06"), "end": value("1988-10")}}),
    )
    STORIES = ()

    def setUp(self) -> None:
        with mock.patch.object(tpe, "ROSTERS", _rosters()):
            super().setUp()

    def residences(self) -> list:
        return [row for row in self.timeline.nodes if row["event_kind"] == "residence"]

    def test_the_rule_is_declared(self):
        self.assertIn("redirect", tt.A_STAY_BOUND_INTO_AN_EPISODE_REDIRECTS_TO_IT)

    def test_the_binder_rules_the_two_filings_one_episode(self):
        self.assertEqual(self.binder["plan"].counts["verdicts"]["bind"], 1)

    def test_the_stay_is_drawn_once_and_every_node_cites_a_claim(self):
        self.assertEqual(len(self.residences()), 1)
        for row in self.timeline.nodes:
            self.assertTrue(row["input_claim_refs"], row["node_id"])

    def test_the_emptied_seed_redirects_to_the_surviving_node(self):
        survivor = self.residences()[0]["node_id"]
        drawn = {row["node_id"] for row in self.timeline.nodes}
        aliases = self.timeline.node_aliases
        direct = [old for old, new in aliases.items() if new == survivor]
        self.assertTrue(direct, f"nothing redirects to {survivor}: {aliases}")
        for old in aliases:
            self.assertNotIn(old, drawn)
        # Every redirect, followed, reaches the drawing; none dangles.
        groups = dict.fromkeys(drawn)
        for old in aliases:
            self.assertIn(tt._follow_node_alias(old, aliases, groups), drawn, old)

if __name__ == "__main__":
    unittest.main()
