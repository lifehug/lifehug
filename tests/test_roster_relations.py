"""E-L2c — organizations, `located_in` and alias decisions on the roster.

Design: lifehug-platform `docs/design/timeline-eras.md` v2.1 §3.1, §3.3, §4.3.

Synthetic data only; NEVER references ~/Workspace/dave.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SYSTEM = ROOT / "system"
sys.path.insert(0, str(SYSTEM))

import episode_containers as ec  # noqa: E402
import roster_relations as rr  # noqa: E402


def _snapshot(entity_type: str, *entities: dict) -> dict:
    return {"version": 1, "type": entity_type, "entities": list(entities)}


class ResolveOrCreateTests(unittest.TestCase):
    def test_a_new_name_mints_a_minimal_entity(self):
        ref, snap, created = rr.resolve_or_create("place", "Cedarport", _snapshot("place"))
        self.assertTrue(created)
        self.assertEqual(ref, "place/cedarport")
        self.assertEqual(snap["entities"], [{"name": "Cedarport", "slug": "cedarport",
                                             "aliases": []}])

    def test_an_existing_name_is_reused_not_duplicated(self):
        snap = _snapshot("place", {"name": "Cedarport", "slug": "cedarport", "aliases": []})
        ref, snap2, created = rr.resolve_or_create("place", "Cedarport", snap)
        self.assertFalse(created)
        self.assertEqual(ref, "place/cedarport")
        self.assertEqual(len(snap2["entities"]), 1)

    def test_name_matching_is_case_and_whitespace_insensitive(self):
        snap = _snapshot("place", {"name": "Cedarport", "slug": "cedarport", "aliases": []})
        ref, _, created = rr.resolve_or_create("place", "  cedarport  ", snap)
        self.assertFalse(created)
        self.assertEqual(ref, "place/cedarport")

    def test_a_slug_collision_with_a_preexisting_entity_is_disambiguated(self):
        # A hand-edited or previously-imported roster can carry an entity
        # whose stored `slug` was not derived from its own name — this
        # proves the mint path never silently reuses that slug for a
        # genuinely different name.
        snap = _snapshot("place", {"name": "St Louis Historic District",
                                    "slug": "st-louis", "aliases": []})
        ref, snap2, created = rr.resolve_or_create("place", "St Louis", snap)
        self.assertTrue(created)
        self.assertNotEqual(ref, "place/st-louis")
        self.assertEqual(len(snap2["entities"]), 2)

    def test_an_organization_carries_its_kind(self):
        _ref, snap, created = rr.resolve_or_create(
            "organization", "Boeing", _snapshot("organization"),
            organization_kind="employer")
        self.assertTrue(created)
        self.assertEqual(snap["entities"][0]["organization_kind"], "employer")

    def test_an_unknown_organization_kind_is_refused(self):
        with self.assertRaises(rr.RosterRelationError):
            rr.resolve_or_create("organization", "Boeing", _snapshot("organization"),
                                 organization_kind="hobby")

    def test_an_empty_name_is_refused(self):
        with self.assertRaises(rr.RosterRelationError):
            rr.resolve_or_create("place", "   ", _snapshot("place"))


class AliasDecisionTests(unittest.TestCase):
    """Design §4.3: a nickname is a roster alias on the place entity."""

    def _one_place(self, name: str) -> tuple[str, dict]:
        ref, snap, _ = rr.resolve_or_create("place", name, _snapshot("place"))
        return ref, snap

    def test_a_fresh_alias_is_added(self):
        ref, snap = self._one_place("Cedarport")
        result = rr.alias_decision("place", ref, "The Fish House", snap)
        self.assertTrue(result["applied"])
        self.assertTrue(result["changed"])
        entity = rr.find_by_ref("place", result["snapshot"], ref)
        self.assertEqual(entity["aliases"], ["The Fish House"])

    def test_the_same_alias_twice_is_idempotent(self):
        ref, snap = self._one_place("Cedarport")
        once = rr.alias_decision("place", ref, "The Fish House", snap)
        twice = rr.alias_decision("place", ref, "the fish house", once["snapshot"])
        self.assertTrue(twice["applied"])
        self.assertFalse(twice["changed"])

    def test_an_unknown_entity_is_refused(self):
        result = rr.alias_decision("place", "place/nowhere", "X", _snapshot("place"))
        self.assertFalse(result["applied"])
        self.assertEqual(result["reason"], "entity_not_found")

    def test_an_empty_alias_is_refused(self):
        ref, snap = self._one_place("Cedarport")
        result = rr.alias_decision("place", ref, "   ", snap)
        self.assertFalse(result["applied"])
        self.assertEqual(result["reason"], "alias_empty")

    def test_two_places_sharing_an_alias_bind_to_neither(self):
        # Design §4.3, reusing the eras program's shared-alias rule verbatim
        # (row 17: "two places sharing the alias -> identity_uncertain
        # naming both").
        ref1, snap, _ = rr.resolve_or_create("place", "Cedarport", _snapshot("place"))
        ref2, snap, _ = rr.resolve_or_create("place", "Yucaipa", snap)
        first = rr.alias_decision("place", ref1, "The Fish House", snap)
        result = rr.alias_decision("place", ref2, "The Fish House", first["snapshot"])
        self.assertFalse(result["applied"])
        self.assertEqual(result["reason"], rr.IDENTITY_UNCERTAIN_KIND)
        refs = {c["ref"] for c in result["candidates"]}
        self.assertEqual(refs, {ref1, ref2})

    def test_an_alias_matching_another_entitys_name_also_collides(self):
        ref1, snap, _ = rr.resolve_or_create("place", "Cedarport", _snapshot("place"))
        ref2, snap, _ = rr.resolve_or_create("place", "The Fish House", snap)
        result = rr.alias_decision("place", ref1, "The Fish House", snap)
        self.assertFalse(result["applied"])
        self.assertEqual(result["reason"], rr.IDENTITY_UNCERTAIN_KIND)
        refs = {c["ref"] for c in result["candidates"]}
        self.assertEqual(refs, {ref1, ref2})

    def test_a_collision_leaves_the_colliding_entity_unaliased(self):
        ref1, snap, _ = rr.resolve_or_create("place", "Cedarport", _snapshot("place"))
        ref2, snap, _ = rr.resolve_or_create("place", "Yucaipa", snap)
        first = rr.alias_decision("place", ref1, "The Fish House", snap)
        result = rr.alias_decision("place", ref2, "The Fish House", first["snapshot"])
        self.assertFalse(result["applied"])
        # ref2 never got the alias; ref1 keeps the one it filed first.
        self.assertEqual(rr.find_by_ref("place", first["snapshot"], ref2)["aliases"], [])
        self.assertEqual(rr.find_by_ref("place", first["snapshot"], ref1)["aliases"],
                         ["The Fish House"])


class LocatedInTests(unittest.TestCase):
    """Design §3.3/§4.1 city rule: `located_in` (home -> city -> region)."""

    def test_a_child_gets_its_parent_ref(self):
        ref, snap, _ = rr.resolve_or_create("place", "Cedarport", _snapshot("place"))
        parent_ref, snap, _ = rr.resolve_or_create("place", "Arizona", snap)
        updated = rr.located_in(ref, parent_ref, snap)
        self.assertEqual(rr.find_by_ref("place", updated, ref)["located_in"], parent_ref)

    def test_the_chain_walks_nearest_first(self):
        home_ref, snap, _ = rr.resolve_or_create("place", "Cedarport", _snapshot("place"))
        city_ref, snap, _ = rr.resolve_or_create("place", "Mesa", snap)
        region_ref, snap, _ = rr.resolve_or_create("place", "Arizona", snap)
        snap = rr.located_in(home_ref, city_ref, snap)
        snap = rr.located_in(city_ref, region_ref, snap)
        self.assertEqual(rr.located_in_chain(home_ref, snap), (city_ref, region_ref))

    def test_a_cycle_stops_rather_than_hangs(self):
        a_ref, snap, _ = rr.resolve_or_create("place", "A", _snapshot("place"))
        b_ref, snap, _ = rr.resolve_or_create("place", "B", snap)
        snap = rr.located_in(a_ref, b_ref, snap)
        snap = rr.located_in(b_ref, a_ref, snap)
        chain = rr.located_in_chain(a_ref, snap, max_depth=8)
        self.assertLessEqual(len(chain), 8)

    def test_an_unknown_child_is_refused(self):
        with self.assertRaises(rr.RosterRelationError):
            rr.located_in("place/nowhere", "place/somewhere", _snapshot("place"))


class ContainmentBinderReadsOrganizationsTests(unittest.TestCase):
    """E-L2a's binder/rung must resolve organizations through this type
    (task item 2) — `episode_containers.ENTITY_ROSTER_TYPES` and
    `entity_index` are generic over the type name, so adding `organization`
    there is what makes this reachable."""

    def test_organization_is_in_the_binders_read_list(self):
        self.assertIn("organization", ec.ENTITY_ROSTER_TYPES)

    def test_an_organization_alias_resolves_through_the_entity_index(self):
        ref, snap, _ = rr.resolve_or_create(
            "organization", "Tidewheel Works", _snapshot("organization"),
            organization_kind="employer")
        decision = rr.alias_decision("organization", ref, "Tidewheel", snap)
        self.assertTrue(decision["applied"])
        index = ec.entity_index({"organization": decision["snapshot"]})
        found = ec.resolve_entities("I worked at Tidewheel for years", index)
        self.assertIn(ref, found)

    def test_a_missing_organization_roster_reads_as_empty_not_an_error(self):
        index = ec.entity_index({})
        self.assertEqual(ec.resolve_entities("Tidewheel", index), frozenset())


if __name__ == "__main__":
    unittest.main()
